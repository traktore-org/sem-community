"""Tests for the SEM Coordinator orchestrator.

Tests the main SEMCoordinator class which orchestrates all sub-modules.
This tests integration between components, not internal implementation.
"""
import pytest
from unittest.mock import Mock, patch

from custom_components.solar_energy_management.coordinator import (
    SEMCoordinator,
    PowerReadings,
    EnergyTotals,
    SEMData,
)

@pytest.fixture(autouse=True)
def _patch_frame_helper():
    """Patch HA frame helper that requires full HA setup."""
    try:
        with patch("homeassistant.helpers.frame.report_usage"):
            yield
    except (ImportError, AttributeError):
        yield


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"
    # Plain HA-shaped stub. It used to be annotated "for
    # battery_charge_adapter._has_integration()" — that helper was deleted
    # with the dead create_charge_adapter factory in #659, and the live brand
    # detection (battery_adapters._integration_loaded) doesn't read
    # config.components at all; it looks at hass.data / hass.config_entries.
    hass.config.components = set()
    hass.states = Mock()
    hass.states.get = Mock(return_value=None)
    hass.states.is_state = Mock(return_value=False)
    hass.bus = Mock()
    hass.bus.async_listen_once = Mock()
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
        "battery_priority_soc": 80,
        "daily_ev_target": 10,
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
    }


@pytest.fixture
def coordinator(mock_hass, config):
    """Create a SEMCoordinator instance."""
    return SEMCoordinator(mock_hass, config)


class TestCoordinatorInitialization:
    """Test SEMCoordinator initialization."""

    def test_creates_with_config(self, mock_hass, config):
        """Test coordinator creates with configuration."""
        coord = SEMCoordinator(mock_hass, config)

        assert coord.hass == mock_hass
        assert coord.config == config

    def test_initializes_with_default_data(self, coordinator):
        """Test coordinator initializes with default data."""
        assert coordinator.data is not None
        assert isinstance(coordinator.data, dict)

    def test_device_info_property(self, coordinator):
        """Test device_info returns correct structure."""
        device_info = coordinator.device_info

        assert "identifiers" in device_info
        assert "name" in device_info
        assert "manufacturer" in device_info

    def test_update_interval_from_config(self, coordinator, config):
        """Test update interval is set from config."""
        expected_seconds = config["update_interval"]
        assert coordinator.update_interval.seconds == expected_seconds


class TestSEMDataStructure:
    """Test SEMData structure and to_dict conversion."""

    def test_sem_data_defaults(self):
        """Test SEMData has correct defaults."""
        data = SEMData()

        assert data.power.solar_power == 0
        assert data.charging_state == "idle"
        assert data.available_power == 0

    def test_sem_data_to_dict(self):
        """Test SEMData converts to dictionary correctly."""
        data = SEMData()
        data.power.solar_power = 5000
        data.charging_state = "solar_charging_active"

        result = data.to_dict()

        assert result["solar_power"] == 5000
        assert result["charging_state"] == "solar_charging_active"

    def test_sem_data_to_dict_includes_all_keys(self):
        """Test that to_dict includes all required sensor keys."""
        data = SEMData()
        result = data.to_dict()

        # Power keys
        assert "solar_power" in result
        assert "grid_power" in result
        assert "battery_power" in result
        assert "ev_power" in result

        # Flow keys
        assert "flow_solar_to_home_power" in result
        assert "flow_solar_to_ev_power" in result
        assert "flow_grid_to_home_power" in result

        # Energy keys
        assert "daily_solar_energy" in result
        assert "daily_ev_energy" in result

        # Status keys
        assert "charging_state" in result
        assert "available_power" in result
        assert "calculated_current" in result

    def test_every_binary_sensor_key_in_to_dict(self):
        # Guards against the sem_-prefix class of bug where to_dict() writes
        # a renamed key and the entity reads False forever.
        from custom_components.solar_energy_management.binary_sensor import (
            BINARY_SENSOR_TYPES,
        )

        produced = set(SEMData().to_dict().keys())
        missing = sorted(d.key for d in BINARY_SENSOR_TYPES if d.key not in produced)
        assert not missing, (
            f"Binary sensor keys declared but not produced by SEMData.to_dict(): "
            f"{missing}. Either add the key to to_dict() or remove the description."
        )

    def test_every_sensor_key_produced_somewhere(self):
        # Same contract for sensors, but the coordinator merges keys from many
        # sources at runtime (forecast tracker, storage, conditional blocks), so
        # a strict to_dict() check has false positives. Fall back to source-grep:
        # every SENSOR_TYPES key must appear as a string literal in coordinator/
        # or features/. Catches typos and dropped producers.
        import re
        from pathlib import Path
        import custom_components.solar_energy_management as pkg_module
        from custom_components.solar_energy_management.sensor import SENSOR_TYPES

        pkg = Path(pkg_module.__file__).resolve().parent
        producer_text = ""
        for sub in ("coordinator", "features"):
            for f in (pkg / sub).glob("*.py"):
                producer_text += f.read_text()
        produced_literals = set(re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', producer_text))

        missing = sorted(d.key for d in SENSOR_TYPES if d.key not in produced_literals)
        assert not missing, (
            f"Sensor keys declared but no producer found in coordinator/ or "
            f"features/: {missing}. Either populate the key or remove the description."
        )

    def test_sem_data_status_helpers(self):
        """Test status helper methods in SEMData."""
        data = SEMData()
        data.charging_state = "solar_charging_active"

        result = data.to_dict()

        assert result["solar_charging_status"] == "active"
        assert result["night_charging_status"] == "idle"


class TestPowerReadings:
    """Test PowerReadings dataclass."""

    def test_defaults_to_zero(self):
        """Test all power values default to zero."""
        readings = PowerReadings()

        assert readings.solar_power == 0
        assert readings.grid_power == 0
        assert readings.battery_power == 0
        assert readings.ev_power == 0

    def test_calculate_derived_grid_import(self):
        """Test derived grid import calculation."""
        readings = PowerReadings()
        readings.grid_power = -2000  # Importing

        readings.calculate_derived()

        assert readings.grid_import_power == 2000
        assert readings.grid_export_power == 0

    def test_calculate_derived_grid_export(self):
        """Test derived grid export calculation."""
        readings = PowerReadings()
        readings.grid_power = 1500  # Exporting

        readings.calculate_derived()

        assert readings.grid_import_power == 0
        assert readings.grid_export_power == 1500

    def test_calculate_derived_battery(self):
        """Test derived battery values."""
        readings = PowerReadings()
        readings.battery_power = 1000  # Charging

        readings.calculate_derived()

        assert readings.battery_charge_power == 1000
        assert readings.battery_discharge_power == 0


class TestCoordinatorMethods:
    """Test coordinator methods."""

    def test_sensors_ready_returns_false_initially(self, coordinator):
        """Test sensors_ready returns False when sensors unavailable."""
        assert coordinator.sensors_ready() is False

    @pytest.mark.asyncio
    async def test_async_update_config(self, coordinator):
        """Test configuration can be updated."""
        await coordinator.async_update_config({"daily_ev_target": 15})

        assert coordinator.config["daily_ev_target"] == 15


class TestEdConfigSummary:
    """Test the Energy Dashboard config summary used by Copy diagnostics (#250)."""

    def _ed(self, **kw):
        """Mock EnergyDashboardConfig with all fields None unless overridden."""
        ed = Mock()
        for f in (
            "solar_power", "solar_energy", "grid_import_power", "grid_import_energy",
            "grid_export_energy", "battery_power", "battery_charge_energy",
            "battery_discharge_energy",
        ):
            setattr(ed, f, kw.get(f))
        ed.derived_power = kw.get("derived_power", {})
        return ed

    def test_legacy_when_no_energy_dashboard(self, coordinator):
        coordinator._energy_dashboard_config = None
        assert coordinator._build_ed_config_summary() == "legacy"

    def test_fully_configured_via_stat_rate(self, coordinator):
        coordinator._energy_dashboard_config = self._ed(
            solar_power="sensor.s_p", solar_energy="sensor.s_e",
            grid_import_power="sensor.g_p", grid_import_energy="sensor.g_i",
            grid_export_energy="sensor.g_o", battery_power="sensor.b_p",
            battery_charge_energy="sensor.b_c", battery_discharge_energy="sensor.b_d",
        )
        summary = coordinator._build_ed_config_summary()
        assert summary == (
            "solar:pwr=stat_rate,energy=ok | "
            "grid:pwr=stat_rate,imp=ok,exp=ok | "
            "batt:pwr=stat_rate,chg=ok,dis=ok"
        )

    def test_derived_power_and_missing_export(self, coordinator):
        # SolaX #250 shape: power derived from device, no export energy configured.
        coordinator._energy_dashboard_config = self._ed(
            solar_power="sensor.solax_pv_power_total", solar_energy="sensor.solax_pv_energy_total",
            grid_import_power="sensor.solax_measured_power", grid_import_energy="sensor.solax_grid_import",
            battery_power="sensor.solax_battery_power_charge",
            battery_charge_energy="sensor.solax_battery_input_energy_total",
            battery_discharge_energy="sensor.solax_battery_output_energy_total",
            derived_power={
                "solar": "sensor.solax_pv_power_total",
                "grid": "sensor.solax_measured_power",
                "battery": "sensor.solax_battery_power_charge",
            },
        )
        summary = coordinator._build_ed_config_summary()
        assert "solar:pwr=derived,energy=ok" in summary
        assert "grid:pwr=derived,imp=ok,exp=MISSING" in summary
        assert "batt:pwr=derived,chg=ok,dis=ok" in summary

    def test_energy_only_no_power(self, coordinator):
        # The pre-fix all-zeros case: energy present, no power anywhere.
        coordinator._energy_dashboard_config = self._ed(
            solar_energy="sensor.s_e", grid_import_energy="sensor.g_i",
            grid_export_energy="sensor.g_o", battery_charge_energy="sensor.b_c",
            battery_discharge_energy="sensor.b_d",
        )
        summary = coordinator._build_ed_config_summary()
        assert "solar:pwr=none,energy=ok" in summary
        assert "grid:pwr=none" in summary
        assert "batt:pwr=none" in summary

    def test_detail_exposes_entity_ids_and_source(self, coordinator):
        coordinator._energy_dashboard_config = self._ed(
            solar_power="sensor.s_p", solar_energy="sensor.s_e",
            grid_import_power="sensor.g_p", grid_import_energy="sensor.g_i",
            grid_export_energy="sensor.g_o", battery_power="sensor.b_p",
            battery_charge_energy="sensor.b_c", battery_discharge_energy="sensor.b_d",
            derived_power={"battery": "sensor.b_p"},
        )
        detail = coordinator.get_ed_config_detail()
        assert detail["solar"] == {
            "power": "sensor.s_p", "power_source": "stat_rate", "energy": "sensor.s_e",
        }
        assert detail["grid"]["power"] == "sensor.g_p"
        assert detail["grid"]["import_energy"] == "sensor.g_i"
        assert detail["grid"]["export_energy"] == "sensor.g_o"
        # battery power was derived
        assert detail["battery"]["power_source"] == "derived"

    def test_detail_none_when_legacy(self, coordinator):
        coordinator._energy_dashboard_config = None
        assert coordinator.get_ed_config_detail() is None


class TestEnergyTotals:
    """Test EnergyTotals dataclass."""

    def test_defaults_to_zero(self):
        """Test all energy values default to zero."""
        totals = EnergyTotals()

        assert totals.daily_solar == 0
        assert totals.daily_home == 0
        assert totals.daily_ev == 0
        assert totals.monthly_solar == 0

    def test_can_set_values(self):
        """Test energy values can be set."""
        totals = EnergyTotals()
        totals.daily_solar = 15.5
        totals.daily_home = 10.2

        assert totals.daily_solar == 15.5
        assert totals.daily_home == 10.2


class TestDataKeyMapping:
    """Test that coordinator data provides all required sensor keys."""

    def test_power_keys_present(self, coordinator):
        """Test power sensor keys are present in data."""
        data = coordinator.data

        power_keys = [
            "solar_power", "grid_power", "battery_power", "ev_power",
            "grid_import_power", "grid_export_power",
            "battery_charge_power", "battery_discharge_power",
            "home_consumption_power"
        ]

        for key in power_keys:
            assert key in data, f"Missing power key: {key}"

    def test_flow_keys_present(self, coordinator):
        """Test flow sensor keys are present in data."""
        data = coordinator.data

        flow_keys = [
            "flow_solar_to_home_power", "flow_solar_to_ev_power",
            "flow_solar_to_battery_power", "flow_solar_to_grid_power",
            "flow_grid_to_home_power", "flow_grid_to_ev_power",
            "flow_battery_to_home_power", "flow_battery_to_ev_power",
        ]

        for key in flow_keys:
            assert key in data, f"Missing flow key: {key}"

    def test_energy_keys_present(self, coordinator):
        """Test energy sensor keys are present in data."""
        data = coordinator.data

        energy_keys = [
            "daily_solar_energy", "daily_home_energy", "daily_ev_energy",
            "daily_grid_import_energy", "daily_grid_export_energy",
        ]

        for key in energy_keys:
            assert key in data, f"Missing energy key: {key}"

    def test_status_keys_present(self, coordinator):
        """Test status sensor keys are present in data."""
        data = coordinator.data

        status_keys = [
            "charging_state", "available_power", "calculated_current",
            "battery_soc", "ev_connected", "ev_charging",
        ]

        for key in status_keys:
            assert key in data, f"Missing status key: {key}"

    def test_load_management_keys_present(self, coordinator):
        """Test load management sensor keys are present in data."""
        data = coordinator.data

        load_keys = [
            "target_peak_limit", "peak_margin", "load_management_status",
            "loads_currently_shed", "available_load_reduction",
        ]

        for key in load_keys:
            assert key in data, f"Missing load management key: {key}"


class TestCoordinatorIntegration:
    """Integration tests for coordinator data flow."""

    def test_initial_data_values_valid(self, coordinator):
        """Test initial data values are valid (not None or NaN)."""
        data = coordinator.data

        for key, value in data.items():
            if isinstance(value, (int, float)):
                assert value is not None, f"Key {key} is None"
                import math
                assert not math.isnan(value), f"Key {key} is NaN"

    def test_data_includes_timestamp(self, coordinator):
        """Test data includes last_update timestamp."""
        data = coordinator.data

        assert "last_update" in data


class TestEVAliases:
    """Test EV-related aliases in data."""

    def test_ev_charging_power_alias(self, coordinator):
        """Test ev_charging_power is aliased from ev_power."""
        data = coordinator.data

        assert "ev_charging_power" in data

    def test_ev_max_current_aliases(self, coordinator):
        """Test EV max current aliases exist."""
        data = coordinator.data

        assert "ev_max_current" in data
        assert "ev_max_current_available" in data


class TestChargingStatusDerivedValues:
    """Test derived charging status values."""

    def test_solar_charging_status_derived(self):
        """Test solar_charging_status is derived correctly."""
        data = SEMData()

        # Test idle state
        data.charging_state = "idle"
        assert data.to_dict()["solar_charging_status"] == "idle"

        # Test active state
        data.charging_state = "solar_charging_active"
        assert data.to_dict()["solar_charging_status"] == "active"

    def test_night_charging_status_derived(self):
        """Test night_charging_status is derived correctly."""
        data = SEMData()

        # Test idle state
        data.charging_state = "idle"
        assert data.to_dict()["night_charging_status"] == "idle"

        # Test active state
        data.charging_state = "night_charging_active"
        assert data.to_dict()["night_charging_status"] == "active"



if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
