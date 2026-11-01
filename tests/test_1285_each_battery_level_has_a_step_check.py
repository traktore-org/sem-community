"""#1285 — each battery's own level is held when it jumps no pack can.

The fleet test (#902) sees the average. Two packs at 40 %, one sending a
false 0 % for a read (Huawei does it when its link comes back): the average
is 20 %, a 20-point step under the 25-point limit, so the fleet took the
false read, and the pack's own level was 0 % for its sale and spend checks.
"""
from __future__ import annotations


from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as CONFIRM,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _state,
)
from custom_components.solar_energy_management.tests.test_1169_fleet_soc_dark_or_zero import (  # noqa: E501
    _fleet,
)


def _prime(r):
    """The first level counts once it has repeated (#1284)."""
    for _ in range(CONFIRM):
        p = r.read_power()
    return p


def _levels(p):
    return p.batteries["b1"].soc_pct, p.batteries["b2"].soc_pct, p.battery_soc


class TestAFalseZeroOnOnePack:
    def test_the_pack_and_the_fleet_keep_the_last_level(self):
        r, states = _fleet(40, 40)
        assert _levels(_prime(r)) == (40.0, 40.0, 40.0)
        states["sensor.soc2"] = _state(0, "%")
        assert _levels(r.read_power()) == (40.0, 40.0, 40.0), (
            "the false 0 % was this pack's level, and 20 % the fleet's")

    def test_a_level_that_repeats_is_the_truth(self):
        r, states = _fleet(40, 40)
        _prime(r)
        states["sensor.soc2"] = _state(5, "%")
        seen = [_levels(r.read_power())[1] for _ in range(CONFIRM)]
        assert seen[:-1] == [40.0] * (CONFIRM - 1)
        assert seen[-1] == 5.0, "a pack that really fell is believed"

    def test_one_stray_read_does_not_start_the_count(self):
        r, states = _fleet(40, 40)
        _prime(r)
        states["sensor.soc2"] = _state(0, "%")
        r.read_power()
        states["sensor.soc2"] = _state(41, "%")
        assert _levels(r.read_power())[1] == 41.0
        states["sensor.soc2"] = _state(0, "%")
        assert _levels(r.read_power())[1] == 41.0, "the count starts over"

    def test_a_small_step_is_taken_at_once(self):
        r, states = _fleet(40, 40)
        _prime(r)
        states["sensor.soc2"] = _state(38, "%")
        assert _levels(r.read_power())[1] == 38.0

    def test_the_first_read_is_taken_as_read(self):
        r, _ = _fleet(40, 0)
        assert _levels(r.read_power())[1] == 0.0


class TestWhatIsLeftAlone:
    def test_a_dark_unit_is_still_dark(self):
        r, states = _fleet(40, 40)
        _prime(r)
        states["sensor.soc2"] = _state("unavailable", "%")
        assert _levels(r.read_power())[1] is None

    def test_both_packs_falling_together_are_held_then_believed(self):
        r, states = _fleet(90, 90)
        _prime(r)
        states["sensor.soc1"] = _state(0, "%")
        states["sensor.soc2"] = _state(0, "%")
        seen = [_levels(r.read_power()) for _ in range(CONFIRM)]
        assert seen[0] == (90.0, 90.0, 90.0)
        assert seen[-1] == (0.0, 0.0, 0.0)

    def test_one_verdict_per_cycle(self):
        """The fleet average and the unit list both read the pack."""
        r, states = _fleet(40, 40)
        _prime(r)
        states["sensor.soc2"] = _state(5, "%")
        r.read_power()
        r.read_power()
        assert r._unit_soc_candidate["sensor.soc2"][1] == 2

    def test_a_held_unit_holds_the_fleet_like_one_battery_is_held(self):
        r, states = _fleet(40, 40)
        _prime(r)
        states["sensor.soc2"] = _state(0, "%")
        p = r.read_power()
        assert p.battery_soc_unavailable is True
        assert p.battery_soc == 40.0
