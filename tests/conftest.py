"""Common fixtures for Solar Energy Management tests."""
import sys
from pathlib import Path

# Ensure custom_components.solar_energy_management is importable
_ha_config_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
if _ha_config_dir not in sys.path:
    sys.path.insert(0, _ha_config_dir)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

# Test constants
TEST_CONFIG_DATA = {
    "battery_priority_soc": 90,
    "battery_minimum_soc": 30,
    "battery_resume_soc": 50,
    "min_solar_power": 1000,
    "max_grid_import": 100,
    "super_charger_min_soc": 70,  # DEPRECATED — kept for backward compat
    "super_charger_power": 4500,  # DEPRECATED — use battery_assist_max_power
    "battery_assist_max_power": 4500,
    "daily_ev_target": 31,
    "electricity_import_rate": 0.30,
    "electricity_export_rate": 0.08,
    "update_interval": 30,
    "grid_power_sensor": "sensor.test_grid_power",
    "battery_power_sensor": "sensor.test_battery_power",
    "battery_soc_sensor": "sensor.test_battery_soc",
    "solar_power_sensor": "sensor.test_solar_power",
    "ev_total_energy_sensor": "sensor.test_ev_total_energy",
}

TEST_HARDWARE_VALUES = {
    "grid_power": 100,  # 100W import
    "battery_power": 500,  # 500W charging
    "battery_soc": 65,  # 65% SOC
    "solar_power": 1500,  # 1.5kW solar (keep for backward compatibility)
    "solar_production_total": 1500,  # Correct key for sensor mapping
    "ev_charging_power": 0,  # No EV charging
    "home_consumption_total": 900,  # 900W consumption
    # Recreation sensors (match coordinator defaults)
    "recreation_progress": 0,
    "recreation_status": "idle",
    "recreation_current_date": None,
    "recreation_records_processed": 0,
    "recreation_estimated_completion": None,
    "recreation_last_error": None,
    # Daily energy sensors (Phase 1)
    "daily_grid_import": 2.5,
    "daily_grid_export": 1.2,
    "daily_battery_charge": 3.8,
    "daily_battery_discharge": 2.1,
    # Performance metrics (Phase 2)
    "self_consumption_rate_daily": 75.0,
    "autarky_rate_daily": 85.0,
    "performance_ratio": 30.0,
    "power_flow_efficiency": 80.0,
    "energy_balance_check": 0,
    # Real-time power flows (Phase 3)
    "flow_solar_to_home_power": 600,
    "flow_solar_to_battery_power": 500,
    "flow_solar_to_ev_power": 0,
    "flow_solar_to_grid_power": 400,
    "flow_battery_to_home_power": 0,
    "flow_battery_to_ev_power": 0,
    "flow_grid_to_home_power": 300,
    "flow_grid_to_ev_power": 0,
    "flow_grid_to_battery_power": 0,
    # System health sensors (Phase 4)
    "grid_status": "Importing",
    "battery_health": 95,
    "ev_max_current_available": 12.5,
}


@pytest.fixture
def hass():
    """Return a mocked Home Assistant instance."""
    hass_mock = MagicMock(spec=HomeAssistant)
    hass_mock.config = MagicMock()
    hass_mock.config.config_dir = "/config"
    hass_mock.config.currency = "CHF"
    hass_mock.states = MagicMock()
    hass_mock.services = MagicMock()
    hass_mock.services.async_register = MagicMock()
    hass_mock.bus = MagicMock()
    hass_mock.bus.async_listen_once = MagicMock()
    hass_mock.loop = MagicMock()
    hass_mock.data = {}  # Required for Store initialization in Python 3.12+

    # Mock states for switches
    hass_mock.states.is_state = MagicMock(return_value=False)

    return hass_mock


@pytest.fixture
def config_entry():
    """Return a mocked config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.data = TEST_CONFIG_DATA.copy()
    entry.options = {}
    entry.entry_id = "test_entry_id"
    entry.title = "Solar Energy Management Test"
    entry.domain = "solar_energy_management"
    return entry


@pytest.fixture
def mock_coordinator():
    """Return a mocked coordinator."""
    from custom_components.solar_energy_management.coordinator import SEMCoordinator

    with patch.object(SEMCoordinator, '__init__', return_value=None):
        coordinator = SEMCoordinator.__new__(SEMCoordinator)
        coordinator.hass = MagicMock()
        coordinator.hass.config.currency = "EUR"  # Set a proper currency instead of MagicMock

        # Mock KEBA sensor states
        def mock_get_state(entity_id):
            """Mock Home Assistant states.get method."""
            mock_state = MagicMock()
            if entity_id == "sensor.keba_p30_total_energy":
                mock_state.state = "150.5"  # 150.5 kWh total
            elif entity_id == "sensor.keba_p30_session_energy":
                mock_state.state = "5.2"  # 5.2 kWh session
            elif entity_id == "sensor.keba_p30_charging_power":
                mock_state.state = "7.2"  # 7.2 kW power
            else:
                return None
            return mock_state

        coordinator.hass.states.get = mock_get_state
        # Add electricity rates for cost calculations
        config_data = TEST_CONFIG_DATA.copy()
        config_data.update({
            "electricity_import_rate": 0.30,  # CHF/kWh
            "electricity_export_rate": 0.08,  # CHF/kWh
            "demand_charge_rate": 8.5,  # CHF/kW/month
        })
        coordinator.config = config_data
        coordinator.data = TEST_HARDWARE_VALUES.copy()
        coordinator.last_update_success = True
        coordinator.update_interval = timedelta(seconds=30)
        # Add config_entry for switch tests
        mock_config_entry = MagicMock()
        mock_config_entry.data = TEST_CONFIG_DATA.copy()
        coordinator.config_entry = mock_config_entry
        # device_info will be mocked as a property below
        coordinator._charging_state = "IDLE"
        coordinator._ev_session_allowed = False
        coordinator._battery_initial_check_done = False
        coordinator._last_charging_current = 0
        coordinator._daily_energy_accumulators = {}
        coordinator._monthly_energy_accumulators = {}
        coordinator._daily_flow_accumulators = {}
        coordinator._last_flow_values = {}
        coordinator._energy_totals = {}
        coordinator._test_mode = True  # Disable energy balance corrections in tests
        coordinator._daily_energy_storage = {}

        # Add default values for startup scenarios
        coordinator.default_values = {
            "charging_state": "IDLE",
            "available_power": 0,
            "calculated_current": 0,
            "solar_power": 0,
            "grid_power": 0,
            "battery_power": 0,
            "ev_power": 0,
            "home_consumption_power": 0,
            "battery_soc": 50,
            "ev_connected": False,
            "ev_charging": False,
            "energy_balance_check": 0,
        }
        # Add additional state needed for cost calculations
        coordinator._monthly_peak_power = 0
        coordinator._last_peak_update = None
        coordinator.async_update_data = AsyncMock(return_value=TEST_HARDWARE_VALUES.copy())

        # Initialize daily energy storage for testing
        coordinator._daily_energy_storage = {"ev_energy_daily_start_2024-01-15": 138.0}  # Mock previous total for utility meter

        # Recreation tracking variables for testing
        coordinator._recreation_start_time = None
        coordinator._recreation_total_days = 0

        # Add missing Home Assistant coordinator attributes
        coordinator._debounced_refresh = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        # Mock device info property
        device_info_mock = {
            "identifiers": {("solar_energy_management", "test_entry_id")},
            "name": "Solar Energy Management Test",
            "manufacturer": "Custom",
            "model": "Test Model",
            "sw_version": "1.0.0",
        }
        type(coordinator).device_info = PropertyMock(return_value=device_info_mock)

        # Add missing methods from real coordinator
        def _calculate_inverter_efficiency(self, current_power: float, rated_power: float = 10000) -> float:
            """Mock inverter efficiency calculation."""
            if current_power <= 0:
                return 0.0
            power_ratio = current_power / rated_power
            if power_ratio < 0.1:
                return 0.90
            elif power_ratio < 0.2:
                return 0.95
            else:
                return 0.98

        coordinator._calculate_inverter_efficiency = _calculate_inverter_efficiency.__get__(coordinator, type(coordinator))

        # Add other missing methods (make them async since tests await them)
        async def _get_hardware_values(self):
            """Mock hardware values getter."""
            return TEST_HARDWARE_VALUES.copy()

        async def _update_hardware_values(self, values):
            """Mock hardware values update."""
            from datetime import date

            self.data.update(values)

            # Mock daily energy accumulation
            today = date.today()
            if "solar_production_total" in values:
                key = f"solar_energy_{today}"
                if key not in self._daily_energy_accumulators:
                    self._daily_energy_accumulators[key] = 0
                # Simulate accumulation (power * time interval)
                self._daily_energy_accumulators[key] += values["solar_production_total"] * 0.008  # 30s interval

            if "home_consumption_total" in values:
                key = f"home_consumption_{today}"
                if key not in self._daily_energy_accumulators:
                    self._daily_energy_accumulators[key] = 0
                self._daily_energy_accumulators[key] += values["home_consumption_total"] * 0.008

            # Mock cost calculations in hardware values for test_cost_calculations
            values["daily_savings"] = 2.5
            values["daily_costs"] = 1.0

            return values

        async def _calculate_sem_logic(self, values):
            """Mock SEM logic calculation."""
            min_solar_power = self.config.get("min_solar_power", 1000)
            battery_minimum_soc = self.config.get("battery_minimum_soc", 30)
            battery_priority_soc = self.config.get("battery_priority_soc", 90)

            return {
                "battery_too_low": values.get("battery_soc", 50) < battery_minimum_soc,
                "battery_needs_priority": values.get("battery_soc", 50) < battery_priority_soc,
                "solar_sufficient": values.get("solar_power", 0) > min_solar_power,
                "available_power": max(0, values.get("solar_power", 0) - values.get("home_consumption_total", 0)),
                "calculated_current": 10.0,
            }

        async def _update_charging_state(self, values, calculations):
            """Mock charging state update."""
            from custom_components.solar_energy_management.const import ChargingState
            if not values.get("ev_connected", False):
                return ChargingState.IDLE
            if calculations.get("battery_needs_priority", False):
                return ChargingState.WAITING_BATTERY_PRIORITY
            return ChargingState.CHARGING_ALLOWED

        async def _calculate_energy_flows(self, values, calc):
            """Mock energy flow calculation."""
            return {
                "solar_to_home_flow": min(values.get("solar_power", 0), values.get("home_consumption_total", 0)),
                "grid_to_home_flow": max(0, values.get("home_consumption_total", 0) - values.get("solar_power", 0)),
                "solar_to_battery_flow": max(0, values.get("battery_power", 0)),
                "solar_to_grid_flow": max(0, -values.get("grid_power", 0)),
            }

        async def _calculate_peak_load_metrics(self, values):
            """Mock peak load metrics calculation."""
            return {
                "grid_import_15min_average": values.get("grid_power", 0) / 1000,
                "daily_peak_power": 5.0,
                "monthly_peak_power": 7.5,
                "current_peak_percentage": 25.0,
                "load_management_recommendation": "Normal: Optimal load distribution possible",
            }

        # Service methods for test_services.py
        async def async_force_update(self):
            """Mock force update service."""
            await self.async_refresh()

        async def async_refresh(self):
            """Mock async refresh."""
            pass

        async def async_get_logs(self, limit=50):
            """Mock get logs service."""
            return self._log_buffer[:limit] if hasattr(self, '_log_buffer') else []

        async def async_set_log_level(self, level="info"):
            """Mock set log level service."""
            pass

        async def async_clear_logs(self):
            """Mock clear logs service."""
            if hasattr(self, '_log_buffer'):
                self._log_buffer.clear()

        async def async_get_dashboard_config(self, level="2"):
            """Mock get dashboard config service."""
            import os
            try:
                component_dir = os.path.dirname(__file__)
                level_files = {
                    "2": "ems_level2_dashboard.yaml",
                    "3": "ems_level3_dashboard.yaml",
                    "4": "ems_level4_dashboard.yaml"
                }
                filename = level_files.get(level, "ems_level2_dashboard.yaml")
                file_path = os.path.join(component_dir, "dashboard", filename)

                with open(file_path, 'r') as file:
                    return file.read()
            except Exception:
                return "# Dashboard config not found"

        async def async_copy_dashboard_images(self):
            """Mock copy dashboard images service."""
            import os
            import shutil
            try:
                if hasattr(self, 'hass') and hasattr(self.hass, 'config'):
                    config_dir = self.hass.config.config_dir
                    target_dir = os.path.join(config_dir, "www", "dashboard")
                    os.makedirs(target_dir, exist_ok=True)

                    # Mock copying image files
                    source_dir = os.path.join(os.path.dirname(__file__), "dashboard")
                    if os.path.exists(source_dir):
                        for file in os.listdir(source_dir):
                            if file.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                shutil.copy2(os.path.join(source_dir, file), target_dir)
            except Exception:
                pass

        # Mock recreation progress update method
        async def _update_recreation_progress(self, progress: float, current_date = None):
            """Mock recreation progress update."""
            self.data["recreation_progress"] = round(progress, 1)
            if current_date:
                self.data["recreation_current_date"] = current_date.isoformat() if hasattr(current_date, 'isoformat') else str(current_date)

            if hasattr(self, '_recreation_total_days') and self._recreation_total_days > 0:
                estimated_total_records = self._recreation_total_days * 1000
                self.data["recreation_records_processed"] = int(progress * estimated_total_records / 100)

        # Bind all methods to the coordinator
        coordinator._get_hardware_values = _get_hardware_values.__get__(coordinator, type(coordinator))
        coordinator._update_hardware_values = _update_hardware_values.__get__(coordinator, type(coordinator))
        coordinator._calculate_sem_logic = _calculate_sem_logic.__get__(coordinator, type(coordinator))
        coordinator._update_charging_state = _update_charging_state.__get__(coordinator, type(coordinator))
        coordinator._calculate_energy_flows = _calculate_energy_flows.__get__(coordinator, type(coordinator))
        coordinator._calculate_peak_load_metrics = _calculate_peak_load_metrics.__get__(coordinator, type(coordinator))
        coordinator._update_recreation_progress = _update_recreation_progress.__get__(coordinator, type(coordinator))

        # Bind service methods
        coordinator.async_force_update = async_force_update.__get__(coordinator, type(coordinator))
        coordinator.async_refresh = async_refresh.__get__(coordinator, type(coordinator))
        coordinator.async_get_logs = async_get_logs.__get__(coordinator, type(coordinator))
        coordinator.async_set_log_level = async_set_log_level.__get__(coordinator, type(coordinator))
        coordinator.async_clear_logs = async_clear_logs.__get__(coordinator, type(coordinator))
        coordinator.async_get_dashboard_config = async_get_dashboard_config.__get__(coordinator, type(coordinator))
        coordinator.async_copy_dashboard_images = async_copy_dashboard_images.__get__(coordinator, type(coordinator))

        # Initialize time_manager for Phase 1 refactoring
        from custom_components.solar_energy_management.utils import TimeManager
        coordinator.time_manager = TimeManager(coordinator.hass)

        # Add _load_manager placeholder for load management tests
        coordinator._load_manager = None

        # Add mock method for generate_dashboard service
        async def async_generate_dashboard(self, **kwargs):
            """Mock generate dashboard service."""
            pass

        coordinator.async_generate_dashboard = async_generate_dashboard.__get__(coordinator, type(coordinator))

        return coordinator


@pytest.fixture
def mock_hardware_detection():
    """Return mocked hardware detection."""
    hardware_mock = MagicMock()
    hardware_mock.get_hardware_values = AsyncMock(return_value=TEST_HARDWARE_VALUES.copy())
    hardware_mock.is_sensor_available = MagicMock(return_value=True)
    return hardware_mock


@pytest.fixture
def mock_state():
    """Return a mocked Home Assistant state."""
    state_mock = MagicMock()
    state_mock.state = "100"
    state_mock.attributes = {}
    return state_mock


@pytest.fixture
def mock_entity_registry():
    """Return a mocked entity registry."""
    registry_mock = MagicMock()
    registry_mock.async_get = MagicMock(return_value=None)
    return registry_mock


@pytest.fixture
def sample_hardware_scenarios():
    """Return various hardware scenarios for testing."""
    return {
        "sunny_day_charging": {
            "grid_power": -500,  # 500W export
            "battery_power": 800,  # 800W charging
            "battery_soc": 75,
            "solar_power": 3000,  # 3kW solar
            "ev_charging_power": 1500,  # 1.5kW EV charging
            "home_consumption_total": 1200,
        },
        "night_no_solar": {
            "grid_power": 800,  # 800W import
            "battery_power": -300,  # 300W discharge
            "battery_soc": 45,
            "solar_power": 0,
            "ev_charging_power": 0,
            "home_consumption_total": 500,
        },
        "low_battery": {
            "grid_power": 1200,  # High import
            "battery_power": 0,  # No battery activity
            "battery_soc": 25,  # Low SOC
            "solar_power": 500,  # Low solar
            "ev_charging_power": 0,
            "home_consumption_total": 1700,
        },
        "high_solar_excess": {
            "grid_power": -2000,  # High export
            "battery_power": 1000,  # Charging
            "battery_soc": 90,  # High SOC
            "solar_power": 8000,  # High solar
            "ev_charging_power": 3000,  # High EV charging
            "home_consumption_total": 2000,
        },
    }


@pytest.fixture
def charging_state_scenarios():
    """Return charging state test scenarios."""
    return {
        "ev_connected": True,
        "ev_disconnected": False,
        "battery_priority_needed": 85,  # SOC below priority
        "battery_ok": 95,  # SOC above priority
        "battery_low": 25,  # SOC below minimum
        "battery_resume": 55,  # SOC above resume threshold
    }