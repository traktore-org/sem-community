"""Tests for battery sign auto-detection in SensorReader.

Validates that SEM correctly detects and corrects battery power sign
conventions for inverters that use the opposite convention:
- SEM convention: positive = charge, negative = discharge
- Opposite (Enphase, GoodWe, Powerwall, Sunsynk): positive = discharge, negative = charge
"""
import pytest
from unittest.mock import Mock, MagicMock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _make_sensor_state(value, unit="W"):
    """Create a mock sensor state."""
    state = Mock()
    state.state = str(value)
    state.attributes = {"unit_of_measurement": unit}
    return state


def _make_energy_dashboard_config(
    battery_power="sensor.battery_power",
    battery_charge_energy="sensor.battery_charge_total",
    battery_discharge_energy="sensor.battery_discharge_total",
    solar_power="sensor.solar_power",
    grid_import_power="sensor.grid_power",
    grid_import_energy="sensor.grid_import_total",
    grid_export_energy="sensor.grid_export_total",
):
    """Create a mock EnergyDashboardConfig."""
    config = Mock()
    config.battery_power = battery_power
    config.battery_charge_energy = battery_charge_energy
    config.battery_discharge_energy = battery_discharge_energy
    config.solar_power = solar_power
    config.grid_import_power = grid_import_power
    config.grid_import_energy = grid_import_energy
    config.grid_export_energy = grid_export_energy
    config.ev_power = None
    config.has_battery = True
    config.has_solar = True
    config.has_grid = True
    config.has_ev = False
    config.grid_power = grid_import_power
    return config


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.states = Mock()
    return hass


@pytest.fixture
def sensor_reader(mock_hass):
    """Create a SensorReader with empty config."""
    return SensorReader(mock_hass, {})


class TestBatterySignAutoDetect:
    """Tests for _detect_battery_sign method."""

    def test_no_energy_dashboard_returns_false(self, sensor_reader):
        """Without Energy Dashboard, trust the sensor as-is."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        readings = PowerReadings(battery_power=500.0)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_missing_charge_energy_returns_false(self, sensor_reader):
        """If charge energy counter is missing, can't detect."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config(battery_charge_energy=None)
        sensor_reader.set_energy_dashboard_config(ed)
        readings = PowerReadings(battery_power=500.0)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_missing_discharge_energy_returns_false(self, sensor_reader):
        """If discharge energy counter is missing, can't detect."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config(battery_discharge_energy=None)
        sensor_reader.set_energy_dashboard_config(ed)
        readings = PowerReadings(battery_power=500.0)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_low_power_keeps_last_state(self, sensor_reader, mock_hass):
        """Power below 100W threshold should keep last known state."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)
        readings = PowerReadings(battery_power=50.0)  # Below 100W threshold
        # Default state is False (no inversion)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_first_call_stores_baselines(self, sensor_reader, mock_hass):
        """First call stores baselines and returns False."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)

        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False
        assert sensor_reader._battery_charge_baseline == 100.0
        assert sensor_reader._battery_discharge_baseline == 50.0

    def test_huawei_sem_convention_no_negate(self, sensor_reader, mock_hass):
        """Huawei Solar: positive=charge matches SEM → no negation needed.

        Scenario: battery_power=+500W (charging) and charge counter increasing.
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: store baselines (charge=100, discharge=50)
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: charge counter grew (100→100.5), power positive → SEM convention
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.5, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False, "Huawei (SEM convention) should NOT negate"

    def test_enphase_opposite_convention_negate(self, sensor_reader, mock_hass):
        """Enphase: positive=discharge is opposite SEM → negation needed.

        Scenario: battery_power=+500W but discharge counter is increasing
        (meaning the battery is actually discharging, so +500 means discharge).
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: store baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: discharge counter grew (50→50.5), but power is positive
        # → opposite convention (positive means discharge) → must negate
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.5, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is True, "Enphase (opposite convention) should negate"

    def test_goodwe_negative_charge_negate(self, sensor_reader, mock_hass):
        """GoodWe: negative=charge is opposite SEM → negation needed.

        Scenario: battery_power=-500W but charge counter is increasing
        (meaning negative = charging, opposite of SEM where positive = charge).
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: store baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=-500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: charge counter grew, power negative → opposite convention → negate
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.5, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=-500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is True, "GoodWe (negative=charge) should negate"

    def test_huawei_discharge_no_negate(self, sensor_reader, mock_hass):
        """Huawei: negative=discharge matches SEM → no negation.

        Scenario: battery_power=-500W and discharge counter increasing.
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=-500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: discharge counter grew, power negative → SEM convention
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.5, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=-500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False, "Huawei discharge (SEM convention) should NOT negate"

    def test_ambiguous_both_counters_moving_keeps_state(self, sensor_reader, mock_hass):
        """When both counters move, keep last known state (ambiguous)."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: both counters grew (ambiguous)
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.5, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.5, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False, "Ambiguous case should keep default (no negate)"

    def test_unavailable_counter_keeps_state(self, sensor_reader, mock_hass):
        """Unavailable counter should keep last known state."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        unavailable = Mock()
        unavailable.state = "unavailable"

        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": unavailable,
        }.get(eid)

        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False

    def test_detection_persists_across_calls(self, sensor_reader, mock_hass):
        """Once detected, the sign state persists even through low-power periods."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))

        # Call 2: detect opposite convention
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.5, "kWh"),
        }.get(eid)
        result = sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))
        assert result is True

        # Call 3: low power period — should keep the detected state
        result = sensor_reader._detect_battery_sign(PowerReadings(battery_power=30.0))
        assert result is True, "Low power should preserve detected inversion state"
