"""Tests for multi-device aggregation in sensor_reader.py.

Verifies that SEM correctly sums power from multiple inverters, batteries,
and grid tariffs when the Energy Dashboard has multiple sources (#112).
"""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
    SensorConfig,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)


def _make_state(value, unit="W"):
    """Create a mock HA state object."""
    state = MagicMock()
    state.state = str(value)
    state.attributes = {"unit_of_measurement": unit}
    return state


def _make_reader(hass, config=None):
    """Create a SensorReader with mocked hass."""
    reader = SensorReader(hass, config or {})
    return reader


class TestReadSensorsSum:
    """Test _read_sensors_sum helper."""

    def test_sum_two_sensors(self, hass):
        def mock_get(entity_id):
            return {
                "sensor.inv1_power": _make_state(3000),
                "sensor.inv2_power": _make_state(2000),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)
        total = reader._read_sensors_sum(
            ["sensor.inv1_power", "sensor.inv2_power"], "solar"
        )
        assert total == 5000.0

    def test_sum_three_sensors(self, hass):
        def mock_get(entity_id):
            return {
                "sensor.inv1_power": _make_state(1000),
                "sensor.inv2_power": _make_state(2000),
                "sensor.inv3_power": _make_state(3000),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)
        total = reader._read_sensors_sum(
            ["sensor.inv1_power", "sensor.inv2_power", "sensor.inv3_power"], "solar"
        )
        assert total == 6000.0

    def test_sum_with_unavailable_sensor(self, hass):
        """Unavailable sensor contributes 0, others still counted."""
        def mock_get(entity_id):
            if entity_id == "sensor.inv2_power":
                state = MagicMock()
                state.state = "unavailable"
                state.attributes = {}
                return state
            return {
                "sensor.inv1_power": _make_state(3000),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)
        total = reader._read_sensors_sum(
            ["sensor.inv1_power", "sensor.inv2_power"], "solar"
        )
        assert total == 3000.0

    def test_sum_with_kw_conversion(self, hass):
        """Sensors in kW are converted to W before summing."""
        def mock_get(entity_id):
            return {
                "sensor.inv1_power": _make_state(3.0, "kW"),
                "sensor.inv2_power": _make_state(2.5, "kW"),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)
        total = reader._read_sensors_sum(
            ["sensor.inv1_power", "sensor.inv2_power"], "solar"
        )
        assert total == 5500.0

    def test_sum_empty_list(self, hass):
        reader = _make_reader(hass)
        total = reader._read_sensors_sum([], "solar")
        assert total == 0.0

    def test_sum_single_sensor_same_as_read(self, hass):
        """Single sensor in list gives same result as _read_sensor."""
        hass.states.get = MagicMock(return_value=_make_state(4200))
        reader = _make_reader(hass)
        sum_result = reader._read_sensors_sum(["sensor.inv1_power"], "solar")
        single_result = reader._read_sensor("sensor.inv1_power", "solar")
        assert sum_result == single_result == 4200.0


class TestMultiSolarAggregation:
    """Test solar power aggregation with multiple inverters."""

    def test_two_inverters_summed(self, hass):
        """Two solar inverters → power is summed."""
        def mock_get(entity_id):
            return {
                "sensor.inverter1_power": _make_state(3000),
                "sensor.inverter2_power": _make_state(2000),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            solar_power="sensor.inverter1_power",
            solar_power_list=["sensor.inverter1_power", "sensor.inverter2_power"],
            solar_energy_list=["sensor.inv1_energy", "sensor.inv2_energy"],
            has_solar=True,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        assert readings.solar_power == 5000.0

    def test_single_inverter_unchanged(self, hass):
        """Single inverter → same behavior as before."""
        hass.states.get = MagicMock(return_value=_make_state(4000))
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            solar_power="sensor.solar_power",
            solar_power_list=["sensor.solar_power"],
            has_solar=True,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        assert readings.solar_power == 4000.0


class TestMultiBatteryAggregation:
    """Test battery power aggregation with multiple battery units."""

    def test_two_batteries_summed(self, hass):
        """Two batteries → power is summed."""
        def mock_get(entity_id):
            return {
                "sensor.sessy1_power": _make_state(500),
                "sensor.sessy2_power": _make_state(300),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            battery_power="sensor.sessy1_power",
            battery_power_list=["sensor.sessy1_power", "sensor.sessy2_power"],
            battery_charge_energy="sensor.sessy1_charged",
            battery_discharge_energy="sensor.sessy1_discharged",
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        assert readings.battery_power == 800.0

    def test_two_batteries_one_charging_one_discharging(self, hass):
        """Mixed: one battery charging (+500), one discharging (-300)."""
        def mock_get(entity_id):
            return {
                "sensor.sessy1_power": _make_state(500),
                "sensor.sessy2_power": _make_state(-300),
            }.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            battery_power="sensor.sessy1_power",
            battery_power_list=["sensor.sessy1_power", "sensor.sessy2_power"],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        # Net: 500 + (-300) = 200W charging
        assert readings.battery_power == 200.0

    def test_single_battery_unchanged(self, hass):
        """Single battery → same behavior as before."""
        hass.states.get = MagicMock(return_value=_make_state(-400))
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            battery_power="sensor.battery_power",
            battery_power_list=["sensor.battery_power"],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        assert readings.battery_power == -400.0


class TestBatterySocAverage:
    """Test battery SOC averaging across multiple units."""

    def test_two_batteries_soc_averaged(self, hass):
        """Two batteries with auto-detected SOC → averaged."""
        def mock_get(entity_id):
            states = {
                "sensor.sessy_1_power": _make_state(500),
                "sensor.sessy_2_power": _make_state(300),
                "sensor.sessy_1_soc": _make_state(80, "%"),
                "sensor.sessy_2_soc": _make_state(60, "%"),
            }
            return states.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            battery_power="sensor.sessy_1_power",
            battery_power_list=["sensor.sessy_1_power", "sensor.sessy_2_power"],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        # Average of 80 and 60
        assert readings.battery_soc == 70.0

    def test_soc_with_one_unavailable(self, hass):
        """One SOC unavailable → uses the available one only."""
        def mock_get(entity_id):
            states = {
                "sensor.sessy_1_power": _make_state(500),
                "sensor.sessy_2_power": _make_state(300),
                "sensor.sessy_1_soc": _make_state(80, "%"),
                # sessy_2_soc missing
            }
            return states.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            battery_power="sensor.sessy_1_power",
            battery_power_list=["sensor.sessy_1_power", "sensor.sessy_2_power"],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        assert readings.battery_soc == 80.0

    def test_config_soc_overrides_average(self, hass):
        """Explicit SOC config takes precedence over averaging."""
        def mock_get(entity_id):
            states = {
                "sensor.sessy_1_power": _make_state(500),
                "sensor.sessy_2_power": _make_state(300),
                "sensor.custom_soc": _make_state(55, "%"),
            }
            return states.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass, {"battery_soc_sensor": "sensor.custom_soc"})

        ed = EnergyDashboardConfig(
            battery_power="sensor.sessy_1_power",
            battery_power_list=["sensor.sessy_1_power", "sensor.sessy_2_power"],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()
        # Config SOC overrides auto-detect average
        assert readings.battery_soc == 55.0


class TestFullMultiDeviceSetup:
    """Integration test: full multi-device setup like issue #112."""

    def test_issue_112_growatt_sessy_wallbox(self, hass):
        """Simulate the #112 user: 2 Growatt inverters + 2 Sessy batteries."""
        def mock_get(entity_id):
            states = {
                # 2 Growatt inverters
                "sensor.growatt1_pv_power": _make_state(3500),
                "sensor.growatt2_pv_power": _make_state(2800),
                # 2 Sessy batteries
                "sensor.sessy_1_power": _make_state(400),
                "sensor.sessy_2_power": _make_state(350),
                "sensor.sessy_1_soc": _make_state(72, "%"),
                "sensor.sessy_2_soc": _make_state(68, "%"),
                # Grid
                "sensor.grid_power": _make_state(-1500),
                # Wallbox
                "sensor.wallbox_links_power": _make_state(4000),
            }
            return states.get(entity_id)

        hass.states.get = MagicMock(side_effect=mock_get)
        reader = _make_reader(hass)

        ed = EnergyDashboardConfig(
            # Primary (first) sensors
            solar_power="sensor.growatt1_pv_power",
            battery_power="sensor.sessy_1_power",
            grid_import_power="sensor.grid_power",
            ev_power="sensor.wallbox_links_power",
            # Multi-device lists
            solar_power_list=[
                "sensor.growatt1_pv_power",
                "sensor.growatt2_pv_power",
            ],
            battery_power_list=[
                "sensor.sessy_1_power",
                "sensor.sessy_2_power",
            ],
            grid_power_list=["sensor.grid_power"],
            has_solar=True,
            has_grid=True,
            has_battery=True,
            has_ev=True,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()

        # Solar: 3500 + 2800 = 6300
        assert readings.solar_power == 6300.0
        # Battery: 400 + 350 = 750
        assert readings.battery_power == 750.0
        # SOC: avg(72, 68) = 70
        assert readings.battery_soc == 70.0
        # Grid: single sensor, unchanged
        assert readings.grid_power == -1500.0
        # EV: single sensor, unchanged
        assert readings.ev_power == 4000.0
