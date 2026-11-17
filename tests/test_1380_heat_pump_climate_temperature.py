"""(#1380) The heat pump reads its climate entity's room temperature, with
the same order every device uses: picked sensor, then own entity, then None."""
from __future__ import annotations

from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.devices.temperature import (
    asked_temperature, read_device_temperature,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)

CLIMATE = "climate.room"
SENSOR = "sensor.picked"


def _pump(hass, sensor=None, climate=CLIMATE):
    return HeatPumpController(
        hass=hass, relay1_entity_id=None, relay2_entity_id=None,
        climate_entity_id=climate, temperature_entity_id=sensor)


def test_a_pump_with_only_a_climate_entity_reads_its_room_temperature():
    hass = _Hass()
    hass.set(CLIMATE, "heat", current_temperature=21.5)
    hp = _pump(hass)
    assert hp.get_current_temperature() == 21.5
    assert hp.to_dict()["current_temperature"] == 21.5
    assert hp._comfort_reading() == 21.5      # the Control tab's band reads it too


def test_a_picked_sensor_wins_over_the_climate_entity():
    hass = _Hass()
    hass.set(CLIMATE, "heat", current_temperature=21.5)
    hass.set(SENSOR, "47.0", unit_of_measurement="°C")
    assert _pump(hass, SENSOR).get_current_temperature() == 47.0


def test_a_broken_sensor_falls_back_to_the_climate_entity():
    hass = _Hass()
    hass.set(CLIMATE, "heat", current_temperature=21.5)
    hass.set(SENSOR, "unavailable")
    assert _pump(hass, SENSOR).get_current_temperature() == 21.5


def test_nothing_readable_is_none_never_zero():
    hass = _Hass()
    hass.set(CLIMATE, "unavailable")
    hp = _pump(hass)
    assert hp.get_current_temperature() is None
    assert read_device_temperature(hass, hp) is None
    assert hp.to_dict()["temperature_reading_path"] == "no_sensor_configured"
    assert asked_temperature(hp) is None


def test_the_coordinator_helper_never_raises_on_a_device_without_a_reader():
    class Bare:
        pass
    assert asked_temperature(Bare()) is None


def test_a_tank_with_both_reads_the_picked_sensor_first():
    hass = _Hass()
    hass.set("water_heater.tank", "eco", current_temperature=40.0)
    hass.set(SENSOR, "52.0", unit_of_measurement="°C")
    tank = HotWaterController(
        hass=hass, entity_id="water_heater.tank", temperature_entity_id=SENSOR)
    assert tank.get_current_temperature() == 52.0
