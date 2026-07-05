"""#564 — battery temperature must never be fabricated.

The PowerReadings default was 25.0 °C, published as a real reading on
installs with no temperature source (reporter's Fronius showed a
constant 25° while the real cell temp was 24.5° and the inverter 40°).
Now: None → the entity shows *unknown*; a configured sensor wins; else
the brand-aware hardware detection (battery_temp1) finds the battery's
own temperature sensor.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def test_default_is_none_not_fabricated():
    assert PowerReadings().battery_temperature is None


def _reader(config=None, states=None):
    hass = MagicMock()
    st = states or {}
    hass.states.get = lambda e: st.get(e)
    return SensorReader(hass, config or {})


def test_configured_sensor_wins():
    r = _reader(
        {"battery_temperature_sensor": "sensor.batt_temp"},
        {"sensor.batt_temp": SimpleNamespace(state="24.5", attributes={})},
    )
    readings = PowerReadings()
    r._read_battery_temperature(readings)
    assert readings.battery_temperature == 24.5


def test_unavailable_sensor_stays_none():
    r = _reader(
        {"battery_temperature_sensor": "sensor.batt_temp"},
        {"sensor.batt_temp": SimpleNamespace(state="unavailable", attributes={})},
    )
    readings = PowerReadings()
    r._read_battery_temperature(readings)
    assert readings.battery_temperature is None


def test_no_source_stays_none():
    r = _reader()
    readings = PowerReadings()
    r._read_battery_temperature(readings)
    assert readings.battery_temperature is None


def test_autodetect_via_hardware_detection():
    r = _reader(states={
        "sensor.fronius_cell_temp": SimpleNamespace(state="24.5", attributes={}),
    })
    r._energy_dashboard_config = SimpleNamespace(battery_power="sensor.batt_p")
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "discover_battery_details_from_registry",
        return_value={"battery_temp1": "sensor.fronius_cell_temp"},
    ):
        readings = PowerReadings()
        r._read_battery_temperature(readings)
    assert readings.battery_temperature == 24.5
    # cached — no second discovery call needed
    assert r._battery_temp_entity == "sensor.fronius_cell_temp"


def test_autodetect_miss_is_throttled():
    r = _reader()
    r._energy_dashboard_config = SimpleNamespace(battery_power="sensor.batt_p")
    calls = []
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "discover_battery_details_from_registry",
        side_effect=lambda *a: calls.append(1) or {},
    ):
        readings = PowerReadings()
        r._read_battery_temperature(readings)
        r._read_battery_temperature(readings)  # within throttle window
    assert len(calls) == 1
