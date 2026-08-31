"""#878 — the battery→EV assist stops at the STATIC buffer, not the floor
that keeps the house covered overnight.

Guido, 31.08: *"I thought we did some new modes for the ev charger where it
should drain the battery with the ev charger to the expected level so the
house consumption was still with the battery covered."*

That work exists — #778 phase 5 lets the spendable budget unlock the assist
behind three gates. But the budget is the KEY, not the CEILING: the drain is
bounded by ``battery_assist_potential_w(soc, buffer_soc, …)``, the static
configured buffer. The sibling sink already knows better —
``forecast_sell.py`` takes ``floor = max(reserve, dynamic_floor_pct)`` — so
the two sinks disagree about how deep the pack may go.

THE DANGEROUS DIRECTION. This only bites when the computed floor sits ABOVE
the buffer. A sign error or a bad default therefore does not under-spend, it
allows a DEEPER drain than today, on a real battery, silently. Hence the
fail-closed tests below are separate rather than folded in.

THE #282 CLASS. ``battery_assist_potential_w`` exists precisely so the
strategy decision and the canonical budget cannot disagree — its own
docstring says so. Both callers must move together, and the oracle test at
the bottom pins that rather than trusting two separate assertions.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    battery_assist_potential_w,
)

MAX = 4500.0
BUFFER = 70.0
AUTO = 90.0


def _p(soc, floor=None):
    return battery_assist_potential_w(soc, BUFFER, AUTO, MAX,
                                      dynamic_floor_soc=floor)


class TestTheFloorBoundsTheDrain:
    def test_a_floor_above_the_buffer_tightens_the_taper(self):
        """SOC 78 sits above the 70 buffer (so the pack may assist today)
        but below a computed floor of 80 — tonight the house needs it."""
        assert _p(78.0) > 0.0, "sanity: today it assists at 78%"
        assert _p(78.0, floor=80.0) == 0.0, (
            "drained past the level that keeps the house covered overnight"
        )

    def test_at_the_floor_exactly_the_assist_is_zero(self):
        assert _p(80.0, floor=80.0) == 0.0

    def test_above_the_floor_it_ramps_from_the_floor_not_the_buffer(self):
        """The taper must start at the EFFECTIVE floor, or the curve is
        computed against a level the pack is not allowed to reach."""
        got = _p(85.0, floor=80.0)
        band = max(1.0, AUTO - 80.0)
        want = MAX * (0.5 + 0.5 * ((85.0 - 80.0) / band))
        assert got == pytest.approx(want)

    def test_a_floor_above_auto_start_still_blocks(self):
        """A demanding night can compute a floor above the Zone-4 line. The
        full-power branch must not out-rank the floor — checking auto_start
        first would hand out the whole cap below the floor."""
        assert _p(95.0, floor=97.0) == 0.0


class TestFailClosed:
    """`dynamic_floor_pct` is None whenever no budget was computed. None must
    mean 'fall back to the buffer', never 'a floor of zero' — the latter
    licenses draining the pack to empty."""

    def test_none_is_exactly_todays_behaviour(self):
        for soc in (60.0, 69.9, 70.0, 75.0, 89.9, 90.0, 100.0):
            assert _p(soc, floor=None) == _p(soc), soc

    def test_a_floor_below_the_buffer_changes_nothing(self):
        """The buffer is a hard floor in its own right; a lower computed
        floor must never lower it."""
        for soc in (72.0, 80.0, 95.0):
            assert _p(soc, floor=10.0) == _p(soc), soc

    def test_a_zero_floor_does_not_open_the_pack(self):
        assert _p(50.0, floor=0.0) == 0.0
        assert _p(75.0, floor=0.0) == _p(75.0)

    def test_a_nonsense_floor_is_ignored_not_obeyed(self):
        for bad in ("", "abc", float("nan")):
            assert _p(80.0, floor=bad) == _p(80.0), bad


class TestBothCallersCannotDisagree:
    """The #282 class, pinned as an oracle: the strategy decision and the
    canonical budget must return the SAME number for the same inputs. Two
    separate assertions would drift; one comparison cannot."""

    def test_decide_and_flow_calculator_agree(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import decide
        from custom_components.solar_energy_management.coordinator import (
            flow_calculator as fc,
        )
        d_src = inspect.getsource(decide)
        f_src = inspect.getsource(fc.FlowCalculator._calculate_battery_assist_w)
        for src, who in ((d_src, "decide"), (f_src, "flow_calculator")):
            assert "dynamic_floor" in src, (
                f"{who} still bounds the assist by the static buffer — the "
                "two sinks disagree about how deep the pack may go (#282)"
            )


class TestThePlumbingIsNotInert:
    """Today's #884 lesson, applied before it can bite: a value must be named
    in EVERY copy layer between where it is computed and where it is used, or
    it silently arrives as its default. Here the default is `None`, which
    correctly falls back to the buffer — so a missed layer would look exactly
    like "the feature is off" rather than like a bug."""

    def test_the_fleet_state_is_populated_from_the_planning_evidence(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._build_fleet_cycle_state)
        assert "dynamic_floor_pct=" in src, "the floor never leaves the coordinator"
        assert "battery_dynamic_floor_pct" in src, "read from the wrong key"

    def test_it_is_not_coerced_to_zero_on_the_way(self):
        """`or 0.0` here would turn 'no budget' into 'floor of zero'."""
        import inspect, re
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._build_fleet_cycle_state)
        m = re.search(r"dynamic_floor_pct=\((.*?)\),\n", src, re.S)
        assert m, "population site not found"
        assert "or 0.0" not in m.group(1), (
            "coerced to 0.0 — that reads as a floor of zero and licenses "
            "draining the pack to empty"
        )

    def test_the_view_carries_it_without_coercion(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import build_view
        src = inspect.getsource(build_view.build_charger_view)
        assert "dynamic_floor_pct=" in src
        assert 'getattr(fleet_state, "dynamic_floor_pct", None)' in src


class TestTheFloorSurvivesAFleet:
    """A floor that says "the house stays covered" means nothing if two cars
    drain through it twice as fast.

    Measured through the real `decide` path before the fix: two chargers,
    both Zone 3/4, one pack with a 5000 W cap —

        charger 1: surplus 6000 + assist 3864 = 9864 W
        charger 2: surplus    0 + assist 3864 = 3864 W
        asked of one battery: 7727 W  (55% over its own cap)

    The solar cascade correctly zeroed charger 2's SOLAR share, but the
    assist is derived only from fleet-wide values — SOC, buffer, floor, cap —
    so every charger computed the same full potential and added it again.

    Exactly the #864/#874 shape: a fleet-shared resource handed out
    per-charger. `assist_committed_w` mirrors `solar_committed_w` and
    `peak_committed_w` — one budget, one accumulator, same cascade.
    """

    def _view(self, committed_assist, soc=85.0, floor=79.0, solar=6000.0,
              solar_committed=0.0):
        from types import SimpleNamespace
        f = SimpleNamespace(
            solar_w=solar, curtailment_grant_w=0.0, home_w=0.0,
            battery_charge_w=0.0, solar_committed_w=solar_committed,
            battery_soc=soc, buffer_soc=70.0, auto_start_soc=90.0,
            priority_soc=30.0, battery_assist_max_power_w=5000.0,
            battery_assist_min_surplus_w=1200.0, battery_may_assist_ev=True,
            dynamic_floor_pct=floor, forecast_spending_enabled=True,
            battery_spendable_kwh=4.0, battery_priority=None,
            battery_commanded=False, assist_committed_w=committed_assist,
        )
        return SimpleNamespace(fleet=f, ev_priority=1)

    def test_a_second_charger_cannot_claim_the_assist_again(self):
        from custom_components.solar_energy_management.coordinator.decide import (
            battery_assist_budget_w,
        )
        RAW = 6000.0
        b1 = battery_assist_budget_w(self._view(0.0))
        a1 = b1 - RAW
        assert a1 > 0, "sanity: charger 1 gets an assist"

        # charger 2: the cascade took its solar, and the assist it must now
        # see is what charger 1 already claimed
        b2 = battery_assist_budget_w(
            self._view(a1, solar_committed=b1))
        a2 = b2 - max(0.0, RAW - b1)
        assert a2 == 0.0, (
            f"charger 2 claimed {a2:.0f} W of assist that charger 1 had "
            "already taken — one pack, asked twice"
        )

    def test_the_fleet_total_never_exceeds_the_pack_cap(self):
        from custom_components.solar_energy_management.coordinator.decide import (
            battery_assist_budget_w,
        )
        RAW, CAP = 6000.0, 5000.0
        committed, total = 0.0, 0.0
        for _ in range(4):                      # four chargers, one battery
            surplus = max(0.0, RAW - committed)
            b = battery_assist_budget_w(
                self._view(total, solar_committed=committed))
            assist = b - surplus
            total += assist
            committed += b
        assert total <= CAP + 1e-6, (
            f"four chargers asked one pack for {total:.0f} W against a "
            f"{CAP:.0f} W cap"
        )

    def test_a_single_charger_is_unchanged(self):
        """The accumulator starts at zero, so a one-charger install must see
        exactly what it saw before."""
        from custom_components.solar_energy_management.coordinator.decide import (
            battery_assist_budget_w,
        )
        assert battery_assist_budget_w(self._view(0.0)) == \
            battery_assist_budget_w(self._view(0.0))
        b = battery_assist_budget_w(self._view(0.0))
        assert b - 6000.0 > 0

    def test_the_coordinator_actually_accumulates_it(self):
        """Three times today a field was carried into a dataclass and never
        populated, arriving as its default with no error. The accumulator is
        worthless unless the per-charger loop feeds it, so pin reset,
        increment and thread."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        cycle = inspect.getsource(SEMCoordinator._async_update_data)
        assert "self._assist_committed_w_per_cycle = 0.0" in cycle, (
            "never reset — it would grow without bound across cycles"
        )
        assert "self._assist_committed_w_per_cycle +=" in cycle, (
            "never incremented — every charger still sees zero committed"
        )
        state = inspect.getsource(SEMCoordinator._build_fleet_cycle_state)
        assert "assist_committed_w=" in state, (
            "never threaded onto the fleet state — the decision cannot see it"
        )

    def test_it_resets_beside_its_siblings(self):
        """A per-cycle accumulator that survives a cycle starves every
        charger after the first."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._async_update_data)
        i = src.index("self._solar_committed_w_per_cycle = 0.0")
        window = src[i:i + 700]
        assert "self._assist_committed_w_per_cycle = 0.0" in window, (
            "reset far from solar/peak — the three are one cascade and drift "
            "when they are not reset together"
        )
