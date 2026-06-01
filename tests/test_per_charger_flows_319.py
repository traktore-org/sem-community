"""Per-charger flow attribution in ``flow_calculator`` (v1.6.9).

Closes the bug class @RienduPre reported as #316 / #284: in
multi-charger setups the dashboard's flow sensors are fleet-aggregated,
so a user with charger A in ``solar_only`` mode and charger B in
``min_plus_solar`` mode sees grid-to-EV flow attributed across BOTH
chargers even when only B is drawing from grid. That perception was
correct — the math was fleet proportional, and there was no per-charger
split available.

v1.6.9 fixes this by:

1. ``sensor_reader`` populates ``PowerReadings.ev_power_per_charger``
   for multi-charger installs (single-charger: dict stays empty).
2. ``flow_calculator.calculate_power_flows`` reads that dict and
   produces ``PowerFlows.per_charger[cid] = ChargerFlows(...)`` whose
   sum across chargers equals the fleet-level ``flows.*_to_ev``.

These tests pin:

- Single-charger setups have an empty ``per_charger`` dict (no
  behaviour change).
- Multi-charger sums match the fleet-level values (sum invariant).
- Idle chargers get a zero-filled ``ChargerFlows`` (no KeyError for
  downstream readers).
- The proportional split honors each charger's share of the total EV
  draw (#316 regression: ``solar_only`` charger drawing 4 kW from
  available solar should NOT show grid_to_ev > 0 — gets the right
  share).
"""

import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    ChargerFlows,
    PowerReadings,
)


def _power(
    solar=0.0, grid=0.0, battery=0.0, ev=0.0, home=0.0,
    ev_per_charger=None,
):
    """Build a ``PowerReadings`` with derived fields populated so the
    flow calculator's signed-power split works correctly."""
    r = PowerReadings(
        solar_power=solar,
        grid_power=grid,
        battery_power=battery,
        ev_power=ev,
        home_consumption_power=home,
        ev_power_per_charger=ev_per_charger or {},
    )
    # Derive signed inflows/outflows from the raw signs (matches
    # ``PowerReadings.calculate_derived``).
    r.grid_import_power = abs(min(0.0, grid))
    r.grid_export_power = max(0.0, grid)
    r.battery_charge_power = max(0.0, battery)
    r.battery_discharge_power = abs(min(0.0, battery))
    return r


class TestSingleChargerBackCompat:
    """v1.6.9 must NOT change behaviour for single-charger setups.

    When ``ev_power_per_charger`` is empty (single-charger install), the
    per-charger split is skipped and ``flows.per_charger`` stays empty.
    Every downstream reader that only looks at the fleet-level fields
    sees identical numbers to v1.6.8.
    """

    def test_single_charger_per_charger_dict_empty(self):
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=4000, grid=0, battery=0, ev=4000, home=0,
        ))
        assert flows.solar_to_ev == 4000
        assert flows.per_charger == {}


class TestSumInvariant:
    """Sum of per-charger flows == fleet-level flows.

    The proportional split divides each fleet flow by each charger's
    share of total EV draw. With floats and a final ``round(.., 1)`` per
    sub-flow, the sum may differ from the fleet value by ≤ 0.1 W per
    fleet sub-flow — well below any user-visible threshold.
    """

    def test_two_chargers_solar_share_sums_to_fleet(self):
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=6000, grid=0, battery=0, ev=6000, home=0,
            ev_per_charger={"left": 4000.0, "right": 2000.0},
        ))
        # Both chargers covered by solar alone (no grid_to_ev).
        assert flows.solar_to_ev == 6000.0
        total = sum(c.solar_to_ev for c in flows.per_charger.values())
        assert total == pytest.approx(6000.0, abs=0.2)
        # Proportional: left took 4/6, right took 2/6.
        assert flows.per_charger["left"].solar_to_ev == pytest.approx(4000.0, abs=0.1)
        assert flows.per_charger["right"].solar_to_ev == pytest.approx(2000.0, abs=0.1)

    def test_two_chargers_grid_share_sums_to_fleet(self):
        """Solar = 2 kW, EV = 6 kW total (4 + 2), no battery, no home.
        4 kW deficit → grid imports it. Both chargers share solar AND
        grid proportionally; the per-charger sums match fleet."""
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=2000, grid=-4000, battery=0, ev=6000, home=0,
            ev_per_charger={"left": 4000.0, "right": 2000.0},
        ))
        # Fleet check.
        assert flows.solar_to_ev == pytest.approx(2000.0, abs=0.5)
        assert flows.grid_to_ev == pytest.approx(4000.0, abs=0.5)
        # Per-charger sums.
        solar_sum = sum(c.solar_to_ev for c in flows.per_charger.values())
        grid_sum = sum(c.grid_to_ev for c in flows.per_charger.values())
        assert solar_sum == pytest.approx(flows.solar_to_ev, abs=0.2)
        assert grid_sum == pytest.approx(flows.grid_to_ev, abs=0.2)


class TestIdleChargerGetsZeroFlow:
    """A configured but idle charger (draw 0) gets a ``ChargerFlows()``
    with all zeros — downstream code can do ``flows.per_charger[cid]``
    safely without KeyError checks."""

    def test_idle_charger_zero_filled(self):
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=4000, grid=0, battery=0, ev=4000, home=0,
            ev_per_charger={"left": 4000.0, "right": 0.0},
        ))
        assert "right" in flows.per_charger
        right = flows.per_charger["right"]
        assert right.solar_to_ev == 0.0
        assert right.grid_to_ev == 0.0
        assert right.battery_to_ev == 0.0


class TestRegressionForIssue316:
    """The user-reported scenario: charger A active and drawing all
    available solar; charger B idle. Fleet solar_to_ev should equal
    charger A's draw entirely. Per-charger split should attribute it
    all to A and zero to B — exactly the visible attribution
    @RienduPre's complaint expected to see and didn't pre-v1.6.9."""

    def test_charger_b_idle_no_attribution(self):
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=4000, grid=-2000, battery=0, ev=6000, home=0,
            ev_per_charger={"A": 6000.0, "B": 0.0},
        ))
        a = flows.per_charger["A"]
        b = flows.per_charger["B"]
        # A drew all of the fleet's flow.
        assert a.solar_to_ev == pytest.approx(flows.solar_to_ev, abs=0.1)
        assert a.grid_to_ev == pytest.approx(flows.grid_to_ev, abs=0.1)
        # B drew nothing — no attribution.
        assert b.solar_to_ev == 0.0
        assert b.grid_to_ev == 0.0
        assert b.battery_to_ev == 0.0

    def test_solar_only_charger_does_not_get_grid_attribution(self):
        """Step 5 (arch/multi-charger-primary): per-charger native
        priority allocation.

        Pre-Step-5 this test pinned proportional split — both chargers
        got 50% of solar AND 50% of grid even when one was on
        solar_only mode. The "principled fix lives upstream" caveat
        in the original comment IS this step.

        Now: A (inserted first / higher priority) gets ALL the solar.
        B (lower priority) gets ALL the grid. The user-visible
        interpretation is now structurally correct: a solar_only
        charger shows 0 grid_to_ev when there's enough solar to
        cover its draw alone.

        Setup: solar 4 kW, grid_import 4 kW, total EV 8 kW. Charger
        A draws 4 kW; B draws 4 kW. Solar pool exactly covers A;
        grid covers B.
        """
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=4000, grid=-4000, battery=0, ev=8000, home=0,
            ev_per_charger={"A_solar_only": 4000.0, "B_min_plus_solar": 4000.0},
        ))
        a = flows.per_charger["A_solar_only"]
        b = flows.per_charger["B_min_plus_solar"]
        # A (priority 1) gets all solar, no grid.
        assert a.solar_to_ev == pytest.approx(4000, abs=1)
        assert a.grid_to_ev == 0
        # B (priority 2) gets all grid, no solar.
        assert b.solar_to_ev == 0
        assert b.grid_to_ev == pytest.approx(4000, abs=1)
        # Sum equals fleet (the conservation invariant — preserved).
        assert a.solar_to_ev + b.solar_to_ev == pytest.approx(flows.solar_to_ev, abs=0.2)
        assert a.grid_to_ev + b.grid_to_ev == pytest.approx(flows.grid_to_ev, abs=0.2)


class TestNoEvDraw:
    """Edge case: ``ev_power_per_charger`` populated but total EV draw is 0.
    Pre-v1.6.14 behaviour skipped the loop entirely so ``per_charger`` stayed
    ``{}`` — this caused the per-charger flow SENSORS (added in v1.6.15)
    to go ``unavailable`` whenever no charger was drawing.

    Updated for v1.6.14: zero-fill each configured charger so the sensors
    stay AVAILABLE at 0 W. Avoids divide-by-zero via the ``ev <= 0``
    early-return in the inner loop."""

    def test_zero_ev_total_zero_fills_each_charger(self):
        fc = FlowCalculator()
        flows = fc.calculate_power_flows(_power(
            solar=2000, grid=2000, battery=0, ev=0, home=2000,
            ev_per_charger={"left": 0.0, "right": 0.0},
        ))
        assert flows.solar_to_ev == 0.0
        # Both chargers present with zero-filled entries.
        assert set(flows.per_charger.keys()) == {"left", "right"}
        for cid in ("left", "right"):
            cf = flows.per_charger[cid]
            assert cf.solar_to_ev == 0.0
            assert cf.grid_to_ev == 0.0
            assert cf.battery_to_ev == 0.0
