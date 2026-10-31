"""#1286 — two wasted-work leftovers in the second-meter search.

1. A held second-meter pair that goes dark was searched again on EVERY cycle.
   It is searched once at once (a replacement may exist), then slowly, and
   the held pair is read in between.
2. A unit lookup that could not answer for a grid counter was kept as "one
   grid meter" for the rest of the lifetime, so a second meter was never
   found. "Could not ask" is not "there is one meter": it is asked again.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator import (
    sensor_reader as sr_mod,
)

from .test_1240_same_entry_is_same_device import Rig, _state
from .test_1241_two_grid_meters import (
    _EXP_B, _IMP_B, _IN_A, _IN_B, _OUT_A, _OUT_B, _meter, _two,
)


def _searches(rig, cycles):
    """How often the second-meter search ran over ``cycles`` reads."""
    real = sr_mod.SensorReader._discover_split_grid_power
    calls = []

    def spy(self, ed, *a, **k):
        if "counter" in k:
            calls.append(k["counter"])
        return real(self, ed, *a, **k)

    with patch.object(sr_mod.SensorReader, "_discover_split_grid_power", spy):
        for _ in range(cycles):
            rig.read()
    return len(calls)


class TestADarkHeldPairIsNotSearchedEveryCycle:
    def test_the_search_is_slow_while_a_held_sensor_is_dark(self):
        rig = _two()
        rig.read()
        rig.states[_IMP_B] = _state("unavailable", "kW")
        assert _searches(rig, 12) <= 3

    def test_the_search_runs_at_once_when_a_sensor_goes_dark(self):
        rig = _two()
        rig.read()
        rig.states[_EXP_B] = _state("unavailable", "kW")
        assert _searches(rig, 1) == 1

    def test_the_pair_is_read_again_when_the_sensor_returns(self):
        rig = _two()
        rig.read()
        good = rig.states[_IMP_B]
        rig.states[_IMP_B] = _state("unavailable", "kW")
        for _ in range(4):
            rig.read()
        rig.states[_IMP_B] = good
        assert rig.read().grid_power == pytest.approx(-1500.0)

    def test_a_healthy_pair_is_never_searched(self):
        rig = _two()
        rig.read()
        assert _searches(rig, 10) == 0


class TestACouldNotAskIsAskedAgain:
    def test_a_unit_that_answers_late_finds_the_second_meter(self):
        rig = _two()
        real = rig.reader._get_unit_for_entity
        counters = {_IN_B, _OUT_B}
        # registry not ready for the counters
        rig.reader._get_unit_for_entity = (
            lambda eid: None if eid in counters else real(eid))
        assert rig.read().grid_power == pytest.approx(-1000.0)   # one meter
        rig.reader._get_unit_for_entity = real
        power = None
        for _ in range(8):
            power = rig.read()
        assert power.grid_power == pytest.approx(-1500.0)

    def test_the_failed_answer_is_not_kept_as_the_final_one(self):
        rig = _two()
        counters = {_IN_B, _OUT_B}
        real = rig.reader._get_unit_for_entity
        rig.reader._get_unit_for_entity = (
            lambda eid: None if eid in counters else real(eid))
        rig.read()
        disc = rig.reader._split_grid_discovery
        assert disc.get("more_unasked")

    def test_a_real_single_meter_is_asked_once(self):
        rig = Rig(_single_rows(), [_IN_A], [_OUT_A])
        rig.read()
        calls = []
        real = rig.reader._grid_meters
        rig.reader._grid_meters = lambda ed: calls.append(1) or real(ed)
        for _ in range(10):
            rig.read()
        assert calls == []


def _single_rows():
    return _meter("house", "devA", imp_kw=1.0, exp_kw=0.0)
