"""(#1338) A tank below "Run now past" is heated at once, from any source.

The reporter's heat pump tank (climate entity, Mode "Solar + battery",
Keep at 45 °C, Extra 50 °C, Run now past 41 °C) cooled to 28 °C on a
November day with no sun and an empty home battery. On 2.3.0-beta.9 a
too-cold tank only read as a run-time deficit, served from the sources
the mode allows, so nothing could heat it: the diagnostics showed
``hot_water_activation_path: uninitialized``. Since the #1102 heater
ladder (2.3.0-beta.10) "too cold" heats now on any tariff.

The ladder's own tests use a switch boiler. These pin the setpoint tanks
(climate, water_heater) through the engine, with the reporter's numbers:
the engine must send the start, not only read the band as "forced".
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)

SENSOR = "sensor.tank"


def _tank(hass, entity_id, temp):
    """The reporter's setup: a 3 kW tank, its own thermometer picked on the
    Control tab, Keep at 45, Extra +5, Run now past 41, Finish overnight
    from Grid."""
    hass.set(entity_id, "off", current_temperature=temp, temperature=50.0)
    hass.set(SENSOR, str(temp), unit_of_measurement="°C")
    dev = HotWaterController(
        hass=hass, entity_id=entity_id, temperature_entity_id=SENSOR,
        solar_target_temp=50.0, rated_power=3000.0, legionella_target_temp=60.0)
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity = SENSOR
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 45.0, 5.0, 41.0
    dev.top_up_policy = "cheap_hours"
    dev.withheld_commands = []
    return dev


async def _cycle(hass, dev, *, is_night, price):
    """One engine cycle: the house imports, no sun, the battery is empty."""
    sc = SurplusController(hass)
    sc.register_device(dev)
    await sc.update(
        -300.0, price_level=price, is_night=is_night,
        battery_soc=12.0, battery_reserve_soc=10.0,
        daylight_remaining_s=0.0 if is_night else 3600.0, solar_w=0.0)


def _services(hass):
    return [f"{c.args[0]}.{c.args[1]}"
            for c in hass.services.async_call.await_args_list]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_night, price", [
    (False, "expensive"),   # the reporter's afternoon: 16:55, no sun
    (False, "normal"),
    (True, "normal"),       # the evening before the cheap hours begin
    (True, None),           # no price published
])
@pytest.mark.parametrize("entity_id, start", [
    ("climate.dhw", ["climate.set_temperature", "climate.set_hvac_mode"]),
    ("water_heater.dhw", ["water_heater.set_temperature", "water_heater.turn_on"]),
])
async def test_a_tank_below_run_now_past_is_heated_now(entity_id, start, is_night, price):
    hass = _Hass()
    dev = _tank(hass, entity_id, 28.0)
    assert dev.comfort_state == "forced"
    await _cycle(hass, dev, is_night=is_night, price=price)
    assert _services(hass) == start
    assert dev.is_active
    assert dev._last_activation_path == entity_id.split(".")[0]
    if entity_id.startswith("climate."):
        modes = [c.args[2].get("hvac_mode")
                 for c in hass.services.async_call.await_args_list]
        assert "heat" in modes


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_id", ["climate.dhw", "water_heater.dhw"])
async def test_a_tank_above_run_now_past_waits_for_the_sun_or_its_block(entity_id):
    """Between Run now past and Keep at, an expensive hour with no sun and
    no planned block starts nothing: the start above is the floor's."""
    hass = _Hass()
    dev = _tank(hass, entity_id, 43.0)
    assert dev.comfort_state == "willing"
    await _cycle(hass, dev, is_night=False, price="expensive")
    assert _services(hass) == []
    assert not dev.is_active
