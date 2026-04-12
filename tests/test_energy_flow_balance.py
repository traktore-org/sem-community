"""Test energy flow balance and sensor reading logic."""
import pytest
from unittest.mock import Mock, patch
from freezegun import freeze_time
from datetime import datetime, date

from custom_components.solar_energy_management.coordinator import (
    SensorReader,
    FlowCalculator,
    EnergyCalculator,
    PowerReadings,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.states = Mock()
    hass.states.get = Mock(return_value=None)
    return hass


@pytest.fixture
def config():
    """Create a test configuration."""
    return {
        "update_interval": 30,
        "solar_production_sensor": "sensor.solar_power",
        "grid_power_sensor": "sensor.grid_power",
        "battery_power_sensor": "sensor.battery_power",
        "battery_soc_sensor": "sensor.battery_soc",
        "ev_power_sensor": "sensor.keba_p30_charging_power",
        "ev_plug_sensor": "binary_sensor.keba_p30_plug",
        "ev_charging_sensor": "binary_sensor.keba_p30_charging_state",
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
    }


@pytest.fixture
def sensor_reader(mock_hass, config):
    """Create a SensorReader instance."""
    return SensorReader(mock_hass, config)


@pytest.fixture
def flow_calculator():
    """Create a FlowCalculator instance."""
    return FlowCalculator()


@pytest.fixture
def energy_calculator(config, mock_hass):
    """Create an EnergyCalculator instance."""
    from custom_components.solar_energy_management.utils.time_manager import TimeManager
    return EnergyCalculator(config, TimeManager(mock_hass))


def create_mock_state(value, unit="W"):
    """Create a properly mocked state object."""
    state = Mock()
    state.state = str(value)
    state.attributes = {"unit_of_measurement": unit}
    return state


class TestSensorReader:
    """Test SensorReader functionality."""

    def test_reads_solar_power(self, sensor_reader, mock_hass):
        """Test reading solar power sensor."""
        mock_hass.states.get = Mock(return_value=create_mock_state(5000, "W"))

        readings = sensor_reader.read_power()

        assert readings.solar_power == 5000

    def test_reads_grid_power_import(self, sensor_reader, mock_hass):
        """Test reading grid power when importing."""
        # Hardware convention: negative = import
        mock_hass.states.get = Mock(return_value=create_mock_state(-2000, "W"))

        readings = sensor_reader.read_power()
        readings.calculate_derived()

        assert readings.grid_import_power == 2000
        assert readings.grid_export_power == 0

    def test_reads_grid_power_export(self, sensor_reader, mock_hass):
        """Test reading grid power when exporting."""
        # Hardware convention: positive = export
        mock_hass.states.get = Mock(return_value=create_mock_state(1500, "W"))

        readings = sensor_reader.read_power()
        readings.calculate_derived()

        assert readings.grid_import_power == 0
        assert readings.grid_export_power == 1500

    def test_reads_battery_power_charging(self, sensor_reader, mock_hass):
        """Test reading battery power when charging."""
        def mock_get_state(entity_id):
            if entity_id == "sensor.battery_power":
                return create_mock_state(1000, "W")  # Positive = charging
            return create_mock_state(0, "W")

        mock_hass.states.get = mock_get_state

        readings = sensor_reader.read_power()
        readings.calculate_derived()

        assert readings.battery_charge_power == 1000
        assert readings.battery_discharge_power == 0

    def test_reads_battery_power_discharging(self, sensor_reader, mock_hass):
        """Test reading battery power when discharging."""
        def mock_get_state(entity_id):
            if entity_id == "sensor.battery_power":
                return create_mock_state(-800, "W")  # Negative = discharging
            return create_mock_state(0, "W")

        mock_hass.states.get = mock_get_state

        readings = sensor_reader.read_power()
        readings.calculate_derived()

        assert readings.battery_charge_power == 0
        assert readings.battery_discharge_power == 800

    def test_handles_unavailable_sensor(self, sensor_reader, mock_hass):
        """Test handling of unavailable sensors."""
        state = Mock()
        state.state = "unavailable"
        mock_hass.states.get = Mock(return_value=state)

        readings = sensor_reader.read_power()

        # Should return 0 for unavailable sensors
        assert readings.solar_power == 0

    def test_converts_kw_to_w(self, sensor_reader, mock_hass):
        """Test automatic conversion from kW to W."""
        mock_hass.states.get = Mock(return_value=create_mock_state(5, "kW"))

        readings = sensor_reader.read_power()

        assert readings.solar_power == 5000  # Converted from kW


class TestPowerReadingsCalculateDerived:
    """Test PowerReadings.calculate_derived() method."""

    def test_calculates_grid_import(self):
        """Test grid import calculation from negative grid power."""
        readings = PowerReadings()
        readings.grid_power = -2000  # Negative = import

        readings.calculate_derived()

        assert readings.grid_import_power == 2000
        assert readings.grid_export_power == 0

    def test_calculates_grid_export(self):
        """Test grid export calculation from positive grid power."""
        readings = PowerReadings()
        readings.grid_power = 1500  # Positive = export

        readings.calculate_derived()

        assert readings.grid_import_power == 0
        assert readings.grid_export_power == 1500

    def test_calculates_battery_charge(self):
        """Test battery charge calculation from positive battery power."""
        readings = PowerReadings()
        readings.battery_power = 1000  # Positive = charging

        readings.calculate_derived()

        assert readings.battery_charge_power == 1000
        assert readings.battery_discharge_power == 0

    def test_calculates_battery_discharge(self):
        """Test battery discharge calculation from negative battery power."""
        readings = PowerReadings()
        readings.battery_power = -800  # Negative = discharging

        readings.calculate_derived()

        assert readings.battery_charge_power == 0
        assert readings.battery_discharge_power == 800

    def test_calculates_home_consumption(self):
        """Test home consumption from energy balance."""
        readings = PowerReadings()
        readings.solar_power = 5000
        readings.grid_power = -1000  # Importing
        readings.battery_power = -500  # Discharging
        readings.ev_power = 2000

        readings.calculate_derived()

        # Energy in = solar + grid_import + battery_discharge = 5000 + 1000 + 500 = 6500
        # Energy out = ev + grid_export + battery_charge = 2000 + 0 + 0 = 2000
        # Home = energy_in - energy_out = 6500 - 2000 = 4500
        assert readings.home_consumption_power == 4500


class TestFlowCalculatorIntegration:
    """Test FlowCalculator with sensor data."""

    def test_flows_from_sensor_readings(self, flow_calculator):
        """Test flow calculation from power readings."""
        readings = PowerReadings()
        readings.solar_power = 5000
        readings.grid_power = -1000
        readings.battery_power = -500
        readings.ev_power = 3000
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # Verify flows are calculated
        total_to_home = flows.solar_to_home + flows.grid_to_home + flows.battery_to_home
        total_to_ev = flows.solar_to_ev + flows.grid_to_ev + flows.battery_to_ev

        # Home and EV should receive power proportionally
        assert total_to_home > 0
        assert total_to_ev > 0

    def test_energy_balance_sources_equal_destinations(self, flow_calculator):
        """Test that total energy sources equal total destinations."""
        readings = PowerReadings()
        readings.solar_power = 8000
        readings.grid_power = -2000  # Import
        readings.battery_power = -1000  # Discharge
        readings.ev_power = 4000
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # Total supply = solar + grid_import + battery_discharge
        total_supply = (
            readings.solar_power +
            readings.grid_import_power +
            readings.battery_discharge_power
        )

        # Total demand = home + ev + grid_export + battery_charge
        total_demand = (
            readings.home_consumption_power +
            readings.ev_power +
            readings.grid_export_power +
            readings.battery_charge_power
        )

        # Supply should equal demand (within tolerance)
        assert abs(total_supply - total_demand) < 10


class TestNightScenarios:
    """Test night-time scenarios with no solar."""

    def test_zero_solar_at_night(self, flow_calculator):
        """Test calculations when solar is zero."""
        readings = PowerReadings()
        readings.solar_power = 0
        readings.grid_power = -3000  # Import
        readings.battery_power = -2000  # Discharge
        readings.ev_power = 1500
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # No solar flows
        assert flows.solar_to_home == 0
        assert flows.solar_to_ev == 0

        # Power comes from grid and battery
        assert flows.grid_to_home > 0
        assert flows.battery_to_home > 0

    def test_night_ev_charging(self, flow_calculator):
        """Test EV charging at night from grid and battery."""
        readings = PowerReadings()
        readings.solar_power = 0
        readings.grid_power = -5000  # Import
        readings.battery_power = -1000  # Discharge
        readings.ev_power = 3000
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # EV should receive from grid and battery
        assert flows.grid_to_ev > 0
        assert flows.battery_to_ev > 0


class TestExportScenarios:
    """Test grid export scenarios."""

    def test_high_solar_export(self, flow_calculator):
        """Test when solar exceeds demand and exports."""
        readings = PowerReadings()
        readings.solar_power = 10000
        readings.grid_power = 3000  # Export
        readings.battery_power = 2000  # Charge
        readings.ev_power = 3000
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # Solar should flow to grid
        assert flows.solar_to_grid > 0

        # All destinations receive from solar
        assert flows.solar_to_home > 0
        assert flows.solar_to_ev > 0
        assert flows.solar_to_battery > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_simultaneous_charge_discharge_impossible(self, flow_calculator):
        """Test that battery can't charge and discharge simultaneously."""
        readings = PowerReadings()
        readings.solar_power = 5000
        readings.battery_power = 2000  # Charging
        readings.ev_power = 3000
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # Battery is charging, so no discharge flows
        assert flows.battery_to_home == 0
        assert flows.battery_to_ev == 0

    def test_very_small_values_handled(self, flow_calculator):
        """Test handling of very small power values."""
        readings = PowerReadings()
        readings.solar_power = 10  # Very small
        readings.home_consumption_power = 10
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # Should not crash or produce NaN
        assert flows.solar_to_home >= 0

    def test_large_commercial_values(self, flow_calculator):
        """Test handling of large commercial-scale values."""
        readings = PowerReadings()
        readings.solar_power = 100000  # 100 kW
        readings.grid_power = -30000
        readings.battery_power = -20000
        readings.ev_power = 50000
        readings.calculate_derived()

        flows = flow_calculator.calculate_power_flows(readings)

        # Should handle large values correctly
        total_solar_flows = (
            flows.solar_to_home +
            flows.solar_to_ev +
            flows.solar_to_battery +
            flows.solar_to_grid
        )

        assert abs(total_solar_flows - 100000) < 10


class TestEnergyCalculatorIntegration:
    """Test EnergyCalculator with flow calculations."""

    @freeze_time("2025-11-12 14:00:00")
    def test_full_integration(self, energy_calculator, flow_calculator):
        """Test full integration from power to energy flows."""
        # Create power readings
        readings = PowerReadings()
        readings.solar_power = 5000
        readings.grid_power = -1000
        readings.battery_power = 500
        readings.ev_power = 2000
        readings.calculate_derived()

        # Calculate energy from power integration
        energy = energy_calculator.calculate_energy(readings)

        # Calculate flows
        power_flows = flow_calculator.calculate_power_flows(readings)
        energy_flows = flow_calculator.calculate_energy_flows(energy)

        # Verify energy totals exist
        assert energy.daily_solar >= 0
        assert energy.daily_home >= 0

        # Verify energy flows exist
        assert energy_flows.solar_to_home >= 0


class TestSensorAvailability:
    """Test sensor availability detection."""

    def test_sensors_ready_with_solar(self, sensor_reader, mock_hass):
        """Test sensors_ready returns True when solar is available."""
        mock_hass.states.get = Mock(return_value=create_mock_state(5000, "W"))

        assert sensor_reader.sensors_ready() is True

    def test_sensors_not_ready_when_unavailable(self, sensor_reader, mock_hass):
        """Test sensors_ready returns False when sensors unavailable."""
        state = Mock()
        state.state = "unavailable"
        mock_hass.states.get = Mock(return_value=state)

        assert sensor_reader.sensors_ready() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
