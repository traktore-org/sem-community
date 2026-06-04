"""Tests for Step 5 — per-charger native flow attribution.

Pre-Step-5: per-charger flow split was a fraction-of-fleet:
    flows.per_charger[cid].solar_to_ev = flows.solar_to_ev * (c/fleet)

If charger A consumes 6 kW of solar and charger B consumes 4 kW of
grid (mixed priority), both got the SAME proportional mix — the
priority signal from the main allocator was lost (#351 M3).

Post-Step-5: each charger consumes from solar/battery/grid pools in
priority order. Higher-priority chargers get first claim; lower
ones fall back. The sum invariant
    sum(per_charger.solar_to_ev) == fleet.solar_to_ev
is preserved by construction.
"""
import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _calc():
    from unittest.mock import MagicMock
    fc = FlowCalculator.__new__(FlowCalculator)
    fc.update_interval = MagicMock(total_seconds=lambda: 10.0)
    return fc


def _power(*, solar, grid, battery, home, ev_per_charger, priorities=None):
    """Build a PowerReadings with per-charger draws + priorities."""
    p = PowerReadings(
        solar_power=solar, grid_power=grid, battery_power=battery,
        home_consumption_power=home, ev_power=sum(ev_per_charger.values()),
    )
    p.grid_import_power = max(0.0, -grid)
    p.grid_export_power = max(0.0, grid)
    p.battery_charge_power = max(0.0, battery)
    p.battery_discharge_power = max(0.0, -battery)
    p.ev_power_per_charger = dict(ev_per_charger)
    if priorities is not None:
        p.ev_priority_per_charger = dict(priorities)
    return p


class TestPriorityNativeAllocation:
    """Per-charger flow split respects priority order on the source
    side (solar > battery > grid)."""

    def test_two_chargers_high_priority_gets_solar_first(self):
        """6 kW solar covers home (500W) + ev_a (4kW) fully + 1.5kW
        of ev_b (2kW). ev_b's remaining 500W comes from grid.
        Priorities: a=1, b=2. High-priority a gets solar; low-pri b
        gets the mix.
        """
        fc = _calc()
        p = _power(
            solar=6000, grid=-500, battery=0, home=500,
            ev_per_charger={"a": 4000, "b": 2000},
            priorities={"a": 1, "b": 2},
        )
        f = fc.calculate_power_flows(p)

        # Fleet (priority allocator output): solar covers home →
        # ev → battery → export. So solar_to_ev = 5500 W.
        # grid_to_ev = 500 W. Fleet sums:
        assert f.solar_to_ev == pytest.approx(5500, abs=1)
        assert f.grid_to_ev == pytest.approx(500, abs=1)

        # Per-charger: priority a gets ALL its 4000 W from solar.
        # Priority b gets 1500 W of remaining solar + 500 W grid.
        assert f.per_charger["a"].solar_to_ev == pytest.approx(4000, abs=1)
        assert f.per_charger["a"].grid_to_ev == 0
        assert f.per_charger["b"].solar_to_ev == pytest.approx(1500, abs=1)
        assert f.per_charger["b"].grid_to_ev == pytest.approx(500, abs=1)

    def test_sum_invariant_holds(self):
        """sum(per_charger.solar_to_ev) == fleet.solar_to_ev for
        every (source, destination) flow."""
        fc = _calc()
        p = _power(
            solar=8000, grid=-2000, battery=-1000, home=1000,
            ev_per_charger={"a": 5000, "b": 4000, "c": 1000},
            priorities={"a": 1, "b": 2, "c": 3},
        )
        f = fc.calculate_power_flows(p)

        sum_solar = sum(pc.solar_to_ev for pc in f.per_charger.values())
        sum_grid = sum(pc.grid_to_ev for pc in f.per_charger.values())
        sum_battery = sum(pc.battery_to_ev for pc in f.per_charger.values())

        assert sum_solar == pytest.approx(f.solar_to_ev, abs=1)
        assert sum_grid == pytest.approx(f.grid_to_ev, abs=1)
        assert sum_battery == pytest.approx(f.battery_to_ev, abs=1)

    def test_idle_charger_zero_filled(self):
        """A charger drawing 0 W gets an empty ChargerFlows
        (v1.6.9 behaviour preserved — sensors stay available)."""
        fc = _calc()
        p = _power(
            solar=8000, grid=2000, battery=0, home=2000,
            ev_per_charger={"a": 4000, "b": 0},
            priorities={"a": 1, "b": 2},
        )
        f = fc.calculate_power_flows(p)
        assert f.per_charger["b"].solar_to_ev == 0
        assert f.per_charger["b"].grid_to_ev == 0
        assert f.per_charger["b"].battery_to_ev == 0

    def test_priorities_inferred_from_dict_order_if_missing(self):
        """No ev_priority_per_charger → fall back to dict-insertion
        order. Preserves single-charger v1.6.9 behaviour."""
        fc = _calc()
        p = _power(
            solar=8000, grid=-3000, battery=0, home=1000,
            ev_per_charger={"a": 6000, "b": 4000},
            # No priorities dict
        )
        f = fc.calculate_power_flows(p)
        # First-inserted charger gets solar first
        assert f.per_charger["a"].solar_to_ev > f.per_charger["b"].solar_to_ev

    def test_single_charger_identical_to_v169(self):
        """Single charger: per_charger[only] equals fleet."""
        fc = _calc()
        p = _power(
            solar=5000, grid=-1000, battery=-500, home=500,
            ev_per_charger={"only": 5000},
        )
        f = fc.calculate_power_flows(p)
        assert f.per_charger["only"].solar_to_ev == pytest.approx(f.solar_to_ev, abs=1)
        assert f.per_charger["only"].grid_to_ev == pytest.approx(f.grid_to_ev, abs=1)
        assert f.per_charger["only"].battery_to_ev == pytest.approx(f.battery_to_ev, abs=1)


class TestPriorityIntent:
    """The PROD #349 / #351 scenarios SEM previously got wrong."""

    def test_two_chargers_one_on_solar_one_on_grid(self):
        """A pulls 4 kW from solar (high priority, lots of sun); B
        pulls 4 kW from grid (low priority, after solar exhausted).
        Pre-Step-5 the proportional split would have given EACH a
        ~50/50 solar/grid mix — wrong. Post-Step-5 A is 100% solar,
        B is 100% grid."""
        fc = _calc()
        # Balanced: solar 4500 + grid_import 4000 = 8500 supply;
        # home 500 + ev 8000 = 8500 demand.
        p = _power(
            solar=4500, grid=-4000, battery=0, home=500,
            ev_per_charger={"a": 4000, "b": 4000},
            priorities={"a": 1, "b": 2},
        )
        f = fc.calculate_power_flows(p)
        # Fleet: solar covers home(500) + 4000 of EV → solar_to_ev=4000
        # grid covers remaining 4000 of EV → grid_to_ev=4000
        # Per-charger: A gets all 4000 W of solar, B gets all 4000 W of grid
        assert f.per_charger["a"].solar_to_ev == pytest.approx(4000, abs=1)
        assert f.per_charger["a"].grid_to_ev == 0
        assert f.per_charger["b"].solar_to_ev == 0
        assert f.per_charger["b"].grid_to_ev == pytest.approx(4000, abs=1)
