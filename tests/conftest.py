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
    # Battery session tracking
    "battery_session_active": False,
    "battery_session_type": "idle",
    "battery_session_energy": 0,
    "battery_session_solar_share": 0,
    "battery_session_cost": 0,
    "battery_session_savings": 0,
    "battery_session_duration": 0,
    "battery_session_avg_power": 0,
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
def mock_hass():
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

    # async_add_executor_job should execute the function and return its result
    async def _mock_executor_job(func, *args):
        return func(*args)
    hass_mock.async_add_executor_job = _mock_executor_job

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
    entry.runtime_data = None  # Set by test or via mock_coordinator
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
        "multi_inverter": {
            "solar_power": 6300,  # 3500 + 2800 from 2 inverters
            "grid_power": -1500,  # Single meter
            "battery_power": 750,  # 400 + 350 from 2 batteries
            "battery_soc": 70,  # avg(72, 68)
            "ev_charging_power": 4000,  # Single charger
            "home_consumption_total": 1050,
        },
        "multi_grid_meter": {
            "solar_power": 7000,  # 4000 + 3000 from 2 inverters
            "grid_power": -1200,  # -800 + -400 from 2 meters
            "battery_power": 300,  # 500 + (-200) from 2 batteries
            "battery_soc": 70,  # avg(80, 60)
            "ev_charging_power": 10500,  # 7000 + 3500 from 2 chargers
            "home_consumption_total": 0,  # derived
        },
        "multi_grid_mixed_direction": {
            "solar_power": 5000,
            "grid_power": -600,  # -1000 + 400 from 2 meters (net import)
            "battery_power": 0,
            "battery_soc": 50,
            "ev_charging_power": 0,
            "home_consumption_total": 4400,
        },
        "battery_charging_from_solar": {
            "solar_power": 5000,
            "grid_power": 0,
            "battery_power": 3000,  # 3kW charging
            "battery_soc": 60,
            "ev_charging_power": 0,
            "home_consumption_total": 2000,
            "battery_session_active": True,
            "battery_session_type": "charge",
            "battery_session_energy": 2.5,
            "battery_session_solar_share": 95.0,
            "battery_session_cost": 0.02,
        },
        "battery_discharging_to_home": {
            "solar_power": 0,
            "grid_power": -200,
            "battery_power": -2500,  # 2.5kW discharging
            "battery_soc": 75,
            "ev_charging_power": 0,
            "home_consumption_total": 2700,
            "battery_session_active": True,
            "battery_session_type": "discharge",
            "battery_session_energy": 4.2,
            "battery_session_savings": 1.26,
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


# ============================================================================
# pytest-homeassistant-custom-component framework fixtures
# ============================================================================
# Legacy MagicMock-based fixture has been renamed ``mock_hass``. New tests
# (config flow, services, scenarios) request ``hass`` — pytest-HA's plugin
# fixture, which yields a real HomeAssistant instance with full state
# machine, registries, and service dispatch.
# ============================================================================


@pytest.fixture
def sem_real_hass(hass, enable_custom_integrations):
    """Real-HA fixture for tests that drive the SEM integration end-to-end.

    Composes pytest-homeassistant-custom-component's ``hass`` (real
    HomeAssistant instance) and ``enable_custom_integrations`` (lets
    HA's setup machinery find ``custom_components/solar_energy_management/``).
    Without ``enable_custom_integrations`` an ``async_setup`` call
    fails with *Integration not found*.

    The reason this is NOT an autouse fixture: making
    ``enable_custom_integrations`` autouse breaks the pre-existing
    ``test_ev_daily_reset_boundary.py`` time-arithmetic tests because
    of scope-wide side effects in HA's component discovery. Tests that
    drive the SEM lifecycle should explicitly request ``sem_real_hass``;
    everything else (pure-helper contract tests, mocked-coordinator
    tests) keeps its current fixture set unchanged.

    Usage::

        async def test_set_option_does_something(sem_real_hass, sem_config_entry):
            sem_config_entry.add_to_hass(sem_real_hass)
            assert await sem_real_hass.config_entries.async_setup(sem_config_entry.entry_id)
            await sem_real_hass.async_block_till_done()
            # ... drive the integration and assert ...
    """
    return hass


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Override pytest-HA's ``verify_cleanup`` strict timer check.

    Core HA schedules background timers (e.g. ``_async_setup_cleanup`` at
    a 24h interval) the moment the ``hass`` fixture starts. Those timers
    are not bugs in SEM — they're core's own bookkeeping — but the
    auto-applied ``verify_cleanup`` would fail tests that observe them.
    Returning True downgrades the failure to a warning. Lingering-task
    detection (the real signal for SEM leaks) stays strict via the
    default ``expected_lingering_tasks=False``.
    """
    return True


@pytest.fixture
def sem_config_entry():
    """A ``MockConfigEntry`` at SEM's current schema version (v12.1).

    Pre-seeded with a multi-charger-ready config (``ev_chargers`` list,
    not legacy flat keys). Test-specific tweaks can mutate ``.data`` /
    ``.options`` before calling ``entry.add_to_hass(hass)``.

    Schema notes — version bumped from v7 to v12 on 2026-06-09:

    * **v12.1 is current**: must match the migration target so tests
      don't accidentally exercise the migration code path. Use the
      ``sem_legacy_config_entry`` fixture (below) when migration IS
      the thing under test.
    * **No top-level ``ev_session_energy_sensor``** (v11→v12 drops it
      when a per-charger value exists; #135).
    * **Per-charger ``charge_mode``** is required post-#277 Phase A
      (the named-mode consolidation that replaced
      ``ev_charging_mode`` + ``night_charging`` + ``tariff_optimized``).
    * **Per-charger ``min_current`` + ``vehicle_min_current``** are
      v8→v9 additions (#440 ADR 0010 #3).

    Use with the real ``hass`` fixture::

        async def test_setup(hass, sem_config_entry):
            sem_config_entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(
                sem_config_entry.entry_id
            )
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.solar_energy_management.const import DOMAIN

    return MockConfigEntry(
        domain=DOMAIN,
        version=12,
        minor_version=1,
        data={
            "grid_power_sensor": "sensor.test_grid_power",
            "battery_power_sensor": "sensor.test_battery_power",
            "battery_soc_sensor": "sensor.test_battery_soc",
            "solar_power_sensor": "sensor.test_solar_power",
            "ev_total_energy_sensor": "sensor.test_ev_total_energy",
            "battery_priority_soc": 90,
            "battery_minimum_soc": 30,
            "battery_resume_soc": 50,
            "min_solar_power": 1000,
            "max_grid_import": 100,
            "battery_assist_max_power": 4500,
            "daily_ev_target": 31,
            "battery_capacity_kwh": 10.0,
            "peak_load": 6000,
            "update_interval": 30,
            "electricity_import_rate": 0.30,
            "electricity_export_rate": 0.08,
            "ev_chargers": [{
                # Need at least one EV charger so per-charger SELECT
                # (charge_mode, target_type) and TIME (target_time)
                # entities get instantiated — without one the
                # ``test_setup_entry_forwards_all_platforms`` smoke
                # test fails on those two platforms.
                "id": "ev_charger",
                "name": "Test Wallbox",
                "ev_connected_sensor": "binary_sensor.test_ev_connected",
                "ev_charging_sensor": "binary_sensor.test_ev_charging",
                "ev_charging_power_sensor": "sensor.test_ev_charging_power",
                "ev_charger_service": "number.set_value",
                "ev_charger_service_entity_id": "number.test_charger_current",
                "ev_current_control_entity": "number.test_charger_current",
                # v8 → v9 (#440 ADR 0010 #3) per-charger current bounds.
                "min_current": 6,
                "max_current": 16,
                "vehicle_min_current": 6,
                "phases": 3,
                "voltage": 230,
                # Post-#277 Phase A: charge_mode is the source of truth
                # for the named-mode consolidation. Default is
                # ``min_plus_solar`` (DEFAULT_EV_CHARGE_MODE).
                "charge_mode": "min_plus_solar",
                "daily_ev_target": 10,
                "daily_ev_target_max": 50,
                "ev_target_soc": 80,
                "ev_target_soc_max": 100,
                "ev_target_type": "kwh",
                "ev_target_time": "07:00",
                "ev_surplus_priority": 3,
            }],
        },
        options={},
        title="SEM Test (real_hass v12.1)",
    )


@pytest.fixture
def sem_multi_wallbox_config_entry():
    """A ``MockConfigEntry`` modelling RienduPre's real-world setup —
    two Wallbox Pulsar chargers with different priorities + modes.

    Seeded from his v1.7.3-beta.1 diagnostic dump on #462 / #464
    (modulo entity-id sanitisation). Use this when a test needs to
    exercise the multi-charger code paths against a realistic shape:
    distinct priorities, distinct modes, distinct vehicles, distinct
    entity bindings.

    Specifically catches regressions in:

    * the ``smart_merge_ev_chargers_by_id`` path (#467) — that one
      charger's update doesn't drop the sibling.
    * the per-charger ``async_select_option`` /
      ``async_set_native_value`` fall-through (#469) — that
      ``entry.options.ev_chargers`` missing the key falls back to
      ``entry.data.ev_chargers`` instead of writing ``[]``.
    * the per-charger select/number entity-id discovery scan
      (``select.py:95`` loop) — that both chargers register their
      own ``select.sem_charger_<id>_charge_mode`` entity.

    Schema is v12.1 (matches ``sem_config_entry``).
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.solar_energy_management.const import DOMAIN

    return MockConfigEntry(
        domain=DOMAIN,
        version=12,
        minor_version=1,
        data={
            "grid_power_sensor": "sensor.test_grid_power",
            "battery_power_sensor": "sensor.test_battery_power",
            "battery_soc_sensor": "sensor.test_battery_soc",
            "solar_power_sensor": "sensor.test_solar_power",
            "battery_priority_soc": 90,
            "battery_minimum_soc": 30,
            "battery_resume_soc": 50,
            "min_solar_power": 1000,
            "max_grid_import": 100,
            "battery_capacity_kwh": 15.0,
            "peak_load": 6000,
            "update_interval": 30,
            "ev_chargers": [
                {
                    "id": "ev_charger",
                    "name": "Laadpaal Links",
                    "ev_connected_sensor": "binary_sensor.test_wb_left_cable_connected",
                    "ev_charging_sensor": "sensor.test_wb_left_status",
                    "ev_charging_power_sensor": "sensor.test_wb_left_charging_power",
                    "ev_charger_service": "number.set_value",
                    "ev_charger_service_entity_id": "number.test_wb_left_max_current",
                    "ev_current_control_entity": "number.test_wb_left_max_current",
                    "ev_total_energy_sensor": "sensor.test_wb_left_charging_energy",
                    "vehicle_soc_entity": "sensor.test_audi_etron_state_of_charge",
                    "vehicle_range_entity": "sensor.test_audi_etron_range",
                    "min_current": 6,
                    "max_current": 16,
                    "vehicle_min_current": 6,
                    "phases": 3,
                    "voltage": 230,
                    "charge_mode": "always_max",
                    "ev_battery_capacity_kwh": 95,
                    "ev_kwh_per_100km": 25,
                    "daily_ev_target": 10,
                    "daily_ev_target_max": 95,
                    "ev_target_soc": 50,
                    "ev_target_soc_max": 100,
                    "ev_target_type": "soc",
                    "ev_surplus_priority": 5,
                    "initial_current": 10,
                },
                {
                    "id": "ev_charger_1",
                    "name": "Laadpaal Rechts",
                    "ev_connected_sensor": "binary_sensor.test_wb_right_cable_connected",
                    "ev_charging_sensor": "sensor.test_wb_right_status",
                    "ev_charging_power_sensor": "sensor.test_wb_right_charging_power",
                    "ev_charger_service": "number.set_value",
                    "ev_charger_service_entity_id": "number.test_wb_right_max_current",
                    "ev_current_control_entity": "number.test_wb_right_max_current",
                    "vehicle_soc_entity": "sensor.test_cooper_state_of_charge",
                    "vehicle_range_entity": "sensor.test_cooper_range",
                    "min_current": 6,
                    "max_current": 16,
                    "vehicle_min_current": None,
                    "phases": 3,
                    "voltage": 230,
                    "charge_mode": "solar_plus_cheap",
                    "ev_battery_capacity_kwh": 29,
                    "ev_kwh_per_100km": 18,
                    "daily_ev_target": 10,
                    "daily_ev_target_max": 29,
                    "ev_target_soc": 100,
                    "ev_target_soc_max": 100,
                    "ev_target_type": "soc",
                    "ev_surplus_priority": 8,
                    "initial_current": 10,
                },
            ],
        },
        options={},
        title="SEM Test (multi-Wallbox v12.1)",
    )