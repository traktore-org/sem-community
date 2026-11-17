"""(#1369) The three fixes the tank goal showed: C1 one thermometer, C2 too
cold wins while away, C3 Legionella counts its own target."""
from __future__ import annotations

from datetime import timedelta

import pytest

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


# ── C3: Legionella counts its own target ───────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("target,temp,counted", [
    (65.0, 61.0, False), (65.0, 65.0, True), (60.0, 61.0, True), (60.0, 59.0, False)])
async def test_c3_natural_achievement_needs_the_own_target(target, temp, counted):
    dev = _tank(_Hass(), temp)
    dev.legionella_target_temp = target
    dev._last_legionella_time = hwc.dt_util.now() - timedelta(hours=10)
    before = dev._last_legionella_time
    await dev.check_legionella_cycle(good_hour=False)
    assert (dev._last_legionella_time != before) is counted
    assert (dev._last_legionella_path == "natural_achievement") is counted
