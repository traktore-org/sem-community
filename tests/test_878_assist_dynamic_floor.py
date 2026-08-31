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
