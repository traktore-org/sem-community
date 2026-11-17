"""(#1369) The three fixes the tank goal showed: C1 one thermometer, C2 too
cold wins while away, C3 Legionella counts its own target."""
from __future__ import annotations

from datetime import timedelta

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
