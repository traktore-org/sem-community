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


# ── Inverter temperature (#564 part 2 — was showing battery temp) ──

def test_inverter_default_is_none_not_fabricated():
    assert PowerReadings().inverter_temperature is None


def test_inverter_configured_sensor_wins():
    r = _reader(
        {"inverter_temperature_sensor": "sensor.inv_temp"},
        {"sensor.inv_temp": SimpleNamespace(state="40.0", attributes={})},
    )
    readings = PowerReadings()
    r._read_inverter_temperature(readings)
    assert readings.inverter_temperature == 40.0


def test_inverter_no_source_stays_none():
    r = _reader()
    readings = PowerReadings()
    r._read_inverter_temperature(readings)
    assert readings.inverter_temperature is None


def test_inverter_unavailable_sensor_stays_none():
    r = _reader(
        {"inverter_temperature_sensor": "sensor.inv_temp"},
        {"sensor.inv_temp": SimpleNamespace(state="unknown", attributes={})},
    )
    readings = PowerReadings()
    r._read_inverter_temperature(readings)
    assert readings.inverter_temperature is None


def test_inverter_autodetect_via_hardware_detection():
    r = _reader(states={
        "sensor.fronius_verto_15_0_plus_temperature":
            SimpleNamespace(state="40.0", attributes={}),
    })
    r._energy_dashboard_config = SimpleNamespace(solar_power="sensor.pv_p")
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "discover_battery_details_from_registry",
        return_value={"inv_temp": "sensor.fronius_verto_15_0_plus_temperature"},
    ):
        readings = PowerReadings()
        r._read_inverter_temperature(readings)
    assert readings.inverter_temperature == 40.0
    assert r._inverter_temp_entity == "sensor.fronius_verto_15_0_plus_temperature"


def test_inverter_temperature_in_coordinator_dict():
    """#564 — inverter_temperature must be published in the coordinator data
    so the system diagram (and sem sensor) can read it instead of the battery."""
    from custom_components.solar_energy_management.coordinator.types import SEMData
    power = PowerReadings()
    power.inverter_temperature = 40.0
    data = SEMData(power=power).to_dict()
    assert data["inverter_temperature"] == 40.0


# ── #727 — the source unit is honoured on ingest ──
# SEM's sensor is °C-native and HA converts it to the user's display unit, so a
# °F source read as °C (48 stored as 48 °C) rendered as a nonsensical 118 °C in
# the Home view. The read must convert the source to °C first.

def test_inverter_fahrenheit_source_is_converted_to_celsius():
    r = _reader(
        {"inverter_temperature_sensor": "sensor.inv_temp"},
        {"sensor.inv_temp": SimpleNamespace(
            state="118.4", attributes={"unit_of_measurement": "°F"})},
    )
    readings = PowerReadings()
    r._read_inverter_temperature(readings)
    assert readings.inverter_temperature == pytest.approx(48.0)


def test_battery_fahrenheit_source_is_converted_to_celsius():
    r = _reader(
        {"battery_temperature_sensor": "sensor.batt_temp"},
        {"sensor.batt_temp": SimpleNamespace(
            state="77", attributes={"unit_of_measurement": "°F"})},
    )
    readings = PowerReadings()
    r._read_battery_temperature(readings)
    assert readings.battery_temperature == pytest.approx(25.0)


def test_celsius_source_still_passes_through():
    """The metric case every existing install relies on — untouched."""
    r = _reader(
        {"inverter_temperature_sensor": "sensor.inv_temp"},
        {"sensor.inv_temp": SimpleNamespace(
            state="40.0", attributes={"unit_of_measurement": "°C"})},
    )
    readings = PowerReadings()
    r._read_inverter_temperature(readings)
    assert readings.inverter_temperature == 40.0


def test_unitless_source_assumed_celsius():
    """No unit → assume °C (the historical behaviour, and what template/MQTT
    temperature sensors that omit the unit rely on)."""
    r = _reader(
        {"battery_temperature_sensor": "sensor.batt_temp"},
        {"sensor.batt_temp": SimpleNamespace(state="24.5", attributes={})},
    )
    readings = PowerReadings()
    r._read_battery_temperature(readings)
    assert readings.battery_temperature == 24.5
