"""(#1369) Two fixes the tank goal showed: C1 one thermometer, C2 too cold
wins while away. (C3 was dropped: natural Legionella stays at 60 C.)"""
from __future__ import annotations


import pytest

from custom_components.solar_energy_management.devices.base import DeviceState
from custom_components.solar_energy_management.devices.tank_goal import differences
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)
from custom_components.solar_energy_management.tests.test_1369_band_decides_top import (
    SENSOR, _tank,
)
from custom_components.solar_energy_management.devices import hot_water_controller as hwc


def _agrees(dev):
    return differences(dev.tank_goal(), dev._goal_seen()) == {}


# ── C1: one thermometer ────────────────────────────────────────────────────

def _two(tank, band):
    hass = _Hass()
    dev = _tank(hass, tank)
    hass.set("sensor.band", str(band), unit_of_measurement="°C")
    dev.comfort_entity = "sensor.band"
    dev.comfort_offset = 4.0          # top 56
    return dev


@pytest.mark.parametrize("tank,band,stops", [(45.0, 57.0, True), (58.0, 50.0, False)])
def test_c1_the_stop_reads_the_band_sensor(tank, band, stops):
    dev = _two(tank, band)
    assert dev.stop_condition_met is stops
    assert _agrees(dev)


def test_c1_start_and_stop_use_one_reading_across_the_top():
    for band in (50.0, 54.9, 55.5, 56.0, 57.0):
        dev = _two(tank=40.0, band=band)       # the tank sensor always says cool
        dev._margin_refused = False
        starts = dev.start_refusal is None
        stops = dev.stop_condition_met
        assert starts == (band <= 55.0) and stops == (band >= 56.0), band


# ── C1 stays out of the away dump: its start reads the TANK sensor ─────────

def _away_two(tank, band, limit, minimum=45.0):
    dev = _two(tank, band)
    dev.comfort_limit = limit
    dev.min_temperature = minimum
    dev.vacation, dev.vacation_dhw_surplus = True, True
    return dev


@pytest.mark.parametrize("tank,band,limit,minimum,stops", [
    (40.0, 65.0, 30.0, 45.0, False),    # heats to 45: the band's 65 is not the tank
    (43.0, 65.0, 30.0, 45.0, False),
    (45.0, 65.0, 30.0, 45.0, True),
    (42.0, 60.0, 44.0, 40.0, True),     # band 60 is not too cold: the minimum rules
])
def test_c1_away_dump_reads_the_tank_sensor(tank, band, limit, minimum, stops):
    dev = _away_two(tank, band, limit, minimum)
    assert dev.stop_condition_met is stops
    assert _agrees(dev)


def test_c1_away_dump_start_and_stop_agree():
    dev = _away_two(40.0, 65.0, 30.0)
    assert dev.is_temperature_safe() is True       # starts
    assert dev.stop_condition_met is False         # and is not stopped at once


# ── C2: too cold wins while away ───────────────────────────────────────────

def _away(temp, dump):
    dev = _tank(_Hass(), temp)
    dev.comfort_limit = 44.0          # above the minimum temperature (40)
    dev.vacation, dev.vacation_dhw_surplus = True, dump
    return dev


@pytest.mark.parametrize("temp", [41.0, 43.0, 44.0])
def test_c2_a_too_cold_tank_is_not_stopped_at_the_minimum_with_the_dump(temp):
    dev = _away(temp, dump=True)
    assert dev.stop_condition_met is False        # before: stopped at 40
    assert _agrees(dev)


def test_c2_a_too_cold_run_goes_on_to_limit_plus_gap_then_stops():
    dev = _away(44.4, dump=True)
    dev._status.state = DeviceState.ACTIVE
    dev._comfort_floor_run = True
    assert dev.stop_condition_met is False and _agrees(dev)   # 44.4 < 44 + 1
    dev.hass.set(SENSOR, "45.0", unit_of_measurement="°C")
    assert dev.stop_condition_met is True and _agrees(dev)


def test_c2_a_warm_tank_still_stops_at_the_minimum_with_the_dump():
    dev = _away(46.0, dump=True)                  # above limit + gap
    assert dev.stop_condition_met is True and _agrees(dev)


@pytest.mark.parametrize("temp", [41.0, 43.0])
def test_c2_without_the_dump_nothing_changed(temp):
    dev = _away(temp, dump=False)
    assert dev.stop_condition_met is False        # the Solar Heating Target (50) rules
    assert _agrees(dev)
    assert _away(51.0, dump=False).stop_condition_met is True


def test_c2_the_setpoint_written_stays_the_minimum():
    dev = _away(43.0, dump=True)
    assert dev._active_target_temp() == 40.0
    assert dev._stop_target_temp(peek=False) == 45.0


# ── step 2: the registry reads the goal, the published block is the same ───

def test_the_comfort_block_is_identical_when_read_from_the_goal():
    """Over the step-1 grid (reading, Keep at, Extra, limit incl. a
    misconfigured one, user stop, away modes, Legionella states, a silent
    sensor) every key of the block equals what the old derivation gave.
    No C1/C2/C3 case changes a published key."""
    import itertools
    from unittest.mock import patch

    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry as R,
    )
    hass = _Hass()
    dev = _tank(hass, 45.0)
    n = 0
    combos = itertools.product(
        ("30", "45", "51", "56", "62", "unavailable"), (45.0, 52.0, 70.0),
        (0.0, 4.0, 9.0), (36.0, 44.0, 52.0), (None, 44.0, 58.0, 65.0),
        ("home", "dump", "nodump"), ("off", "run", "hold"))
    for temp, keep, extra, limit, stop, away, leg in combos:
        hass.set(SENSOR, temp, unit_of_measurement="°C")
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = keep, extra, limit
        dev.stop_entity, dev.stop_at = (SENSOR, stop) if stop is not None else ("", 0.0)
        dev.vacation = away != "home"
        dev.vacation_dhw_surplus = away == "dump"
        dev._legionella_cycle_active = leg != "off"
        dev._legionella_hold_start = hwc.dt_util.now() if leg == "hold" else None
        new = R._comfort_payload(dev)
        with patch.object(R, "_tank_goal", staticmethod(lambda live: None)):
            old = R._comfort_payload(dev)
        assert new == old, (temp, keep, extra, limit, stop, away, leg)
        n += 1
    assert n > 5000


def test_a_device_without_a_goal_keeps_its_own_block():
    from unittest.mock import MagicMock

    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry as R,
    )
    assert R._tank_goal(MagicMock()) is None
    assert R._tank_goal(object()) is None
