"""#1169 — the fleet SOC: a dark unit is no reading, and 0 % is a reading.

The report: with two batteries, battery 1 at 95 % and battery 2's SOC sensor
dark gave a fleet SOC of 47.5 % after three reads (the #902 step check holds
a jump for three reads, then takes it). ``_read_battery_soc_average`` read
each unit without ``allow_none``, so the dark unit was a 0 % unit. #1202's
review fixed that read; these tests drive the reported case through
``read_power`` so it stays fixed.

The sibling, the same "is this a reading?" question the other way round: the
average returned 0.0 for "no unit read", so its caller wrote ``or None`` —
and that turned a real 0 % fleet into a dark one. Two empty packs published
no SOC, held an old level, and after a restart were "never read". A single
battery at 0 % never had that problem. The average now returns None for "no
unit read" and 0.0 only for 0 %.

Guard for both: a fleet whose units all read the same thing reads exactly as
one battery that reads it — a number, or dark — read by read, on both
one-battery paths (SEM's own SOC sensor, and the Energy Dashboard's). Found
by that guard in review: one battery took a level below 0 % as a reading,
while the fleet average and each battery's own SOC already left it out.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _reader,
    _state,
)

DARK = ["unavailable", "unknown", "none", "nan"]
#: what a SOC consumer reads off the readings
_SOC_FIELDS = ("battery_soc", "battery_soc_unavailable", "battery_soc_known")


def _fleet(soc1, soc2):
    """Two batteries in the Energy Dashboard, each with its own SOC sensor."""
    states = {"sensor.b1": _state(0, "W"), "sensor.b2": _state(0, "W"),
              "sensor.imp": _state(0, "W"), "sensor.exp": _state(0, "W"),
              "sensor.soc1": _state(soc1, "%"), "sensor.soc2": _state(soc2, "%")}
    r = _reader(states, {})
    r.hass.states.async_all = MagicMock(return_value=[])
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(EnergyDashboardConfig(
        grid_power_from="sensor.imp", grid_power_to="sensor.exp",
        battery_power="sensor.b1", battery_power_list=["sensor.b1", "sensor.b2"],
        has_grid=True, has_battery=True))
    r._soc_entity_by_power = {"sensor.b1": "sensor.soc1",
                              "sensor.b2": "sensor.soc2"}
    return r, states


def _one(soc):
    """One battery, its SOC on SEM's own SOC sensor setting."""
    states = {"sensor.soc": _state(soc, "%")}
    return _reader(states, {"battery_soc_sensor": "sensor.soc"}), states


def _one_ed(soc):
    """One battery in the Energy Dashboard, with the SOC set there."""
    states = {"sensor.b1": _state(0, "W"), "sensor.imp": _state(0, "W"),
              "sensor.exp": _state(0, "W"), "sensor.soc": _state(soc, "%")}
    r = _reader(states, {})
    r.hass.states.async_all = MagicMock(return_value=[])
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(EnergyDashboardConfig(
        grid_power_from="sensor.imp", grid_power_to="sensor.exp",
        battery_power="sensor.b1", battery_power_list=["sensor.b1"],
        battery_soc="sensor.soc", has_grid=True, has_battery=True))
    return r, states


def _set_all(states, value):
    for eid in [e for e in states if "soc" in e]:
        states[eid] = _state(value, "%")


def _soc(power):
    return tuple(getattr(power, f) for f in _SOC_FIELDS)


# ── 1. The report: a dark unit is left out, not averaged in as 0 % ──────────

class TestADarkUnitIsNoReading:
    @pytest.mark.parametrize("raw", DARK)
    def test_95_and_dark_stays_95_past_the_three_read_check(self, raw):
        r, states = _fleet(95, 95)
        assert r.read_power().battery_soc == 95.0
        states["sensor.soc2"] = _state(raw, "%")
        seen = [r.read_power() for _ in range(5)]
        assert [p.battery_soc for p in seen] == [95.0] * 5, (
            "a dark unit was averaged in as 0 % (95 % and dark gave 47.5 %)")
        assert all(p.battery_soc_partial for p in seen)
        assert not any(p.battery_soc_unavailable for p in seen)

    @pytest.mark.parametrize("raw", DARK)
    def test_dark_from_the_first_read(self, raw):
        r, _ = _fleet(95, raw)
        p = r.read_power()
        assert _soc(p) == (95.0, False, True)
        assert (p.battery_soc_units_expected, p.battery_soc_units_read) == (2, 1)


# ── 2. The sibling: 0 % is a reading ───────────────────────────────────────

class TestZeroIsAReading:
    def test_two_empty_packs_read_0_after_a_restart(self):
        """The old code: dark, and "never read" — the charger path then
        treated an empty fleet as an unknown one."""
        r, _ = _fleet(0, 0)
        p = r.read_power()
        assert _soc(p) == (0.0, False, True)
        assert p.battery_soc_partial is False

    def test_a_fleet_that_drains_to_0_reads_0(self):
        """The old code held the last level (3.5 %) for as long as both packs
        stayed at 0 %."""
        r, states = _fleet(4, 3)
        assert r.read_power().battery_soc == 3.5
        states["sensor.soc1"] = _state(0, "%")
        states["sensor.soc2"] = _state(0, "%")
        for _ in range(3):
            p = r.read_power()
            assert _soc(p) == (0.0, False, True)
            assert p.battery_soc_stale_s is None

    @pytest.mark.parametrize("raw", DARK)
    def test_one_empty_pack_and_one_dark_reads_0(self, raw):
        r, _ = _fleet(0, raw)
        p = r.read_power()
        assert _soc(p) == (0.0, False, True)
        assert p.battery_soc_partial is True

    def test_0_and_10_still_average(self):
        r, _ = _fleet(0, 10)
        assert _soc(r.read_power()) == (5.0, False, True)


# ── 3. A whole dark fleet is still dark ────────────────────────────────────

class TestAWholeDarkFleetIsDark:
    @pytest.mark.parametrize("raw", DARK)
    def test_held_then_dark(self, raw):
        r, states = _fleet(60, 60)
        r.read_power()
        states["sensor.soc1"] = _state(raw, "%")
        states["sensor.soc2"] = _state(raw, "%")
        assert _soc(r.read_power()) == (60.0, True, True)

    @pytest.mark.parametrize("raw", DARK)
    def test_never_read(self, raw):
        r, _ = _fleet(raw, raw)
        p = r.read_power()
        assert (p.battery_soc_unavailable, p.battery_soc_known) == (True, False)


# ── 4. Guard: a fleet of like units reads as one battery ───────────────────

VALUES = [0, 0.0, 1, 37.5, 100, -5] + DARK


class TestAFleetOfLikeUnitsReadsAsOneBattery:
    @pytest.mark.parametrize("single", [_one, _one_ed])
    @pytest.mark.parametrize("value", VALUES)
    def test_first_read(self, value, single):
        fleet, _ = _fleet(value, value)
        one, _ = single(value)
        assert _soc(fleet.read_power()) == _soc(one.read_power())

    @pytest.mark.parametrize("single", [_one, _one_ed])
    @pytest.mark.parametrize("value", VALUES)
    def test_from_a_held_60_read_by_read(self, value, single):
        """60 % to each value: the same reads held, the same read taken
        (60 to 0 is held for two reads by the step check, then taken)."""
        fleet, f_states = _fleet(60, 60)
        one, o_states = single(60)
        assert _soc(fleet.read_power()) == _soc(one.read_power())
        _set_all(f_states, value)
        _set_all(o_states, value)
        f_seen = [_soc(fleet.read_power()) for _ in range(4)]
        o_seen = [_soc(one.read_power()) for _ in range(4)]
        assert f_seen == o_seen
        if value in (0, 0.0):
            assert [s[0] for s in f_seen] == [60.0, 60.0, 0.0, 0.0]
