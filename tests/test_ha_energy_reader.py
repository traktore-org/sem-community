"""Tests for ha_energy_reader Energy Dashboard configuration reading."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
    read_energy_dashboard_config,
    _extract_solar_config,
    _extract_grid_config,
    _extract_battery_config,
    _extract_ev_from_devices,
    get_all_individual_devices,
    validate_energy_dashboard_sensors,
)


# --- Sample energy dashboard data ---
SAMPLE_ENERGY_DATA = {
    "data": {
        "energy_sources": [
            {
                "type": "solar",
                "stat_energy_from": "sensor.solar_energy",
                "stat_rate": "sensor.solar_power",
            },
            {
                "type": "grid",
                "flow_from": [{"stat_energy_from": "sensor.grid_import_energy"}],
                "flow_to": [{"stat_energy_to": "sensor.grid_export_energy"}],
                "power": [{"stat_rate": "sensor.grid_power"}],
            },
            {
                "type": "battery",
                "stat_energy_from": "sensor.battery_discharge",
                "stat_energy_to": "sensor.battery_charge",
                "stat_rate": "sensor.battery_power",
            },
        ],
        "device_consumption": [
            {
                "stat_consumption": "sensor.keba_total_energy",
                "stat_rate": "sensor.keba_power",
            }
        ],
    }
}


class TestEnergyDashboardConfig:
    """Test EnergyDashboardConfig dataclass."""

    def test_config_init_defaults(self):
        config = EnergyDashboardConfig()
        assert config.solar_power is None
        assert config.grid_import_power is None
        assert config.has_solar is False
        assert config.has_grid is False
        assert config.has_battery is False
        assert config.has_ev is False
        assert config.device_consumption == []

    def test_config_is_minimally_configured(self):
        config = EnergyDashboardConfig(has_solar=True, has_grid=True)
        assert config.is_minimally_configured() is True

    def test_config_not_minimally_configured(self):
        config = EnergyDashboardConfig(has_solar=True, has_grid=False)
        assert config.is_minimally_configured() is False

    def test_config_get_missing_components(self):
        config = EnergyDashboardConfig(has_solar=False, has_grid=False)
        missing = config.get_missing_components()
        assert "Solar" in missing
        assert "Grid" in missing

    def test_config_get_missing_components_only_grid(self):
        config = EnergyDashboardConfig(has_solar=True, has_grid=False)
        missing = config.get_missing_components()
        assert missing == ["Grid"]

    # --- power_resolution_incomplete (#274 cold-start recovery) ---

    def test_power_incomplete_when_solar_power_unresolved(self):
        # Solar energy sensor present but power not yet derived (source integration
        # not registered at cold start) → incomplete → coordinator keeps re-deriving.
        config = EnergyDashboardConfig(
            has_solar=True, has_grid=True,
            solar_energy="sensor.solax_pv_energy_total", solar_power=None,
            grid_import_power="sensor.solax_grid_power",
        )
        assert config.power_resolution_incomplete() is True

    def test_power_complete_when_solar_power_resolved(self):
        config = EnergyDashboardConfig(
            has_solar=True, has_grid=True,
            solar_energy="sensor.solax_pv_energy_total",
            solar_power="sensor.solax_pv_power_total",
            grid_import_power="sensor.solax_grid_power",
        )
        assert config.power_resolution_incomplete() is False

    def test_power_incomplete_when_battery_power_unresolved(self):
        config = EnergyDashboardConfig(
            has_solar=True, has_grid=True,
            solar_power="sensor.pv_power",
            battery_charge_energy="sensor.batt_charge_energy", battery_power=None,
        )
        assert config.power_resolution_incomplete() is True

    def test_power_complete_ignores_missing_grid_power_for_split_grid(self):
        # Split-grid setups resolve grid power via runtime discovery, not here —
        # a missing grid_import_power must NOT trigger endless re-derivation.
        config = EnergyDashboardConfig(
            has_solar=True, has_grid=True,
            solar_power="sensor.pv_power",
            grid_import_energy="sensor.grid_import_energy", grid_import_power=None,
        )
        assert config.power_resolution_incomplete() is False

    def test_power_complete_when_not_minimally_configured(self):
        config = EnergyDashboardConfig(has_solar=True, has_grid=False,
                                       solar_energy="s", solar_power=None)
        assert config.power_resolution_incomplete() is False

    def test_config_to_dict(self):
        config = EnergyDashboardConfig(
            solar_power="sensor.solar_power",
            solar_energy="sensor.solar_energy",
            has_solar=True,
            has_grid=True,
        )
        d = config.to_dict()
        assert "solar_power_sensor" in d
        assert "grid_import_power_sensor" in d
        assert "has_solar" in d
        assert "has_grid" in d
        assert "has_battery" in d
        assert "has_ev" in d
        assert d["solar_power_sensor"] == "sensor.solar_power"
        assert d["has_solar"] is True


class TestExtractSolarConfig:
    """Test _extract_solar_config()."""

    def test_extract_solar_config(self):
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.solar_energy",
            "stat_rate": "sensor.solar_power",
        }
        _extract_solar_config(source, config)
        assert config.solar_energy == "sensor.solar_energy"
        assert config.solar_power == "sensor.solar_power"
        assert config.has_solar is True
        assert config.solar_power_list == ["sensor.solar_power"]
        assert config.solar_energy_list == ["sensor.solar_energy"]

    def test_extract_solar_config_stat_rate(self):
        """Prefers stat_rate over stat_power."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.solar_energy",
            "stat_rate": "sensor.solar_rate",
            "stat_power": "sensor.solar_power_old",
        }
        _extract_solar_config(source, config)
        assert config.solar_power == "sensor.solar_rate"

    def test_extract_solar_config_fallback_stat_power(self):
        """Falls back to stat_power when no stat_rate."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.solar_energy",
            "stat_power": "sensor.solar_power_old",
        }
        _extract_solar_config(source, config)
        assert config.solar_power == "sensor.solar_power_old"

    def test_extract_solar_config_energy_only(self):
        config = EnergyDashboardConfig()
        source = {"stat_energy_from": "sensor.solar_energy"}
        _extract_solar_config(source, config)
        assert config.has_solar is True
        assert config.solar_power is None

    def test_extract_solar_two_inverters(self):
        """Two solar sources — both in list, primary = first."""
        config = EnergyDashboardConfig()
        source1 = {
            "stat_energy_from": "sensor.inverter1_energy",
            "stat_rate": "sensor.inverter1_power",
        }
        source2 = {
            "stat_energy_from": "sensor.inverter2_energy",
            "stat_rate": "sensor.inverter2_power",
        }
        _extract_solar_config(source1, config)
        _extract_solar_config(source2, config)
        # Primary is first
        assert config.solar_power == "sensor.inverter1_power"
        assert config.solar_energy == "sensor.inverter1_energy"
        # Lists have both
        assert config.solar_power_list == [
            "sensor.inverter1_power",
            "sensor.inverter2_power",
        ]
        assert config.solar_energy_list == [
            "sensor.inverter1_energy",
            "sensor.inverter2_energy",
        ]
        assert config.has_solar is True

    def test_extract_solar_three_inverters(self):
        """Three solar sources — all in list."""
        config = EnergyDashboardConfig()
        for i in range(1, 4):
            _extract_solar_config({
                "stat_energy_from": f"sensor.inv{i}_energy",
                "stat_rate": f"sensor.inv{i}_power",
            }, config)
        assert len(config.solar_power_list) == 3
        assert config.solar_power == "sensor.inv1_power"


class TestExtractGridConfig:
    """Test _extract_grid_config()."""

    def test_extract_grid_power_config_standard(self):
        """#553 — grid power_config.stat_rate (authoritative over legacy)."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.grid_import_e",
            "power_config": {"stat_rate": "sensor.grid_power"},
        }
        _extract_grid_config(source, config)
        assert config.grid_import_power == "sensor.grid_power"
        assert config.grid_power_list == ["sensor.grid_power"]

    def test_extract_grid_power_config_two_sensors(self):
        """#553 — grid Two-sensor mode maps onto split-grid support:
        from=import, to=export."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.grid_import_e",
            "stat_energy_to": "sensor.grid_export_e",
            "power_config": {
                "stat_rate_from": "sensor.grid_import_power",
                "stat_rate_to": "sensor.grid_export_power",
            },
        }
        _extract_grid_config(source, config)
        # #553 review B1 — dedicated pair fields, NOT grid_import_power
        # (that field is consumed as a COMBINED sensor by the reader) and
        # NOT grid_power_list (that feeds the multi-meter sum).
        assert config.grid_power_from == "sensor.grid_import_power"
        assert config.grid_power_to == "sensor.grid_export_power"
        assert config.grid_import_power is None
        assert config.grid_power_list == []
        assert config.has_grid is True

    def test_extract_grid_power_config_inverted_reads_as_combined(self):
        """#553 — inverted combined grid sensor is read as combined; the
        #461 sign-detection stack owns polarity."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.grid_import_e",
            "power_config": {"stat_rate_inverted": "sensor.grid_power_inv"},
        }
        _extract_grid_config(source, config)
        assert config.grid_import_power == "sensor.grid_power_inv"

    def test_extract_battery_two_pairs_collected(self):
        """#553 — two two-sensor batteries: BOTH pairs collected."""
        config = EnergyDashboardConfig()
        for i in (1, 2):
            _extract_battery_config({
                "stat_energy_from": f"sensor.b{i}_discharge_e",
                "stat_energy_to": f"sensor.b{i}_charge_e",
                "power_config": {
                    "stat_rate_from": f"sensor.b{i}_discharge_p",
                    "stat_rate_to": f"sensor.b{i}_charge_p",
                },
            }, config)
        assert config.battery_power_pairs == [
            ("sensor.b1_discharge_p", "sensor.b1_charge_p"),
            ("sensor.b2_discharge_p", "sensor.b2_charge_p"),
        ]
        assert config.battery_power_from == "sensor.b1_discharge_p"

    def test_extract_grid_config(self):
        config = EnergyDashboardConfig()
        source = {
            "flow_from": [{"stat_energy_from": "sensor.grid_import_energy"}],
            "flow_to": [{"stat_energy_to": "sensor.grid_export_energy"}],
            "power": [{"stat_rate": "sensor.grid_power"}],
        }
        _extract_grid_config(source, config)
        assert config.grid_import_energy == "sensor.grid_import_energy"
        assert config.grid_export_energy == "sensor.grid_export_energy"
        assert config.grid_import_power == "sensor.grid_power"
        assert config.has_grid is True

    def test_extract_grid_config_flow_from_to(self):
        """flow_from for import, flow_to for export."""
        config = EnergyDashboardConfig()
        source = {
            "flow_from": [{"stat_energy_from": "sensor.import"}],
            "flow_to": [{"stat_energy_to": "sensor.export"}],
        }
        _extract_grid_config(source, config)
        assert config.grid_import_energy == "sensor.import"
        assert config.grid_export_energy == "sensor.export"
        assert config.has_grid is True

    def test_extract_grid_config_empty(self):
        config = EnergyDashboardConfig()
        source = {}
        _extract_grid_config(source, config)
        assert config.has_grid is False

    def test_extract_grid_multiple_flow_from(self):
        """Dutch dual-tariff: 2 flow_from entries."""
        config = EnergyDashboardConfig()
        source = {
            "flow_from": [
                {"stat_energy_from": "sensor.grid_import_tarief_1"},
                {"stat_energy_from": "sensor.grid_import_tarief_2"},
            ],
            "flow_to": [
                {"stat_energy_to": "sensor.grid_export_tarief_1"},
                {"stat_energy_to": "sensor.grid_export_tarief_2"},
            ],
            "power": [{"stat_rate": "sensor.grid_power"}],
        }
        _extract_grid_config(source, config)
        # Primary is first
        assert config.grid_import_energy == "sensor.grid_import_tarief_1"
        assert config.grid_export_energy == "sensor.grid_export_tarief_1"
        # Lists have both
        assert config.grid_import_energy_list == [
            "sensor.grid_import_tarief_1",
            "sensor.grid_import_tarief_2",
        ]
        assert config.grid_export_energy_list == [
            "sensor.grid_export_tarief_1",
            "sensor.grid_export_tarief_2",
        ]
        assert config.grid_power_list == ["sensor.grid_power"]
        assert config.has_grid is True

    def test_extract_grid_single_flow_backward_compat(self):
        """Single flow_from — list has one entry, same as primary."""
        config = EnergyDashboardConfig()
        source = {
            "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
            "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
            "power": [{"stat_rate": "sensor.grid_power"}],
        }
        _extract_grid_config(source, config)
        assert config.grid_import_energy == "sensor.grid_import"
        assert config.grid_import_energy_list == ["sensor.grid_import"]
        assert len(config.grid_power_list) == 1


class TestExtractBatteryConfig:
    """Test _extract_battery_config()."""

    def test_extract_battery_config(self):
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.battery_discharge",
            "stat_energy_to": "sensor.battery_charge",
            "stat_rate": "sensor.battery_power",
        }
        _extract_battery_config(source, config)
        assert config.battery_discharge_energy == "sensor.battery_discharge"
        assert config.battery_charge_energy == "sensor.battery_charge"
        assert config.battery_power == "sensor.battery_power"
        assert config.has_battery is True

    def test_extract_battery_power_config_standard(self):
        """#551 — power_config.stat_rate (Standard mode). HA duplicates it at
        top level for back-compat; power_config is authoritative."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.batt_discharge_e",
            "stat_energy_to": "sensor.batt_charge_e",
            "power_config": {"stat_rate": "sensor.batt_power"},
            "stat_rate": "sensor.batt_power",
        }
        _extract_battery_config(source, config)
        assert config.battery_power == "sensor.batt_power"
        assert config.battery_power_inverted is False
        assert config.battery_power_from is None

    def test_extract_battery_power_config_inverted(self):
        """#551 — power_config.stat_rate_inverted flags the sign flip."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.batt_discharge_e",
            "power_config": {"stat_rate_inverted": "sensor.batt_power_inv"},
        }
        _extract_battery_config(source, config)
        assert config.battery_power == "sensor.batt_power_inv"
        assert config.battery_power_inverted is True

    def test_extract_battery_power_config_two_sensors(self):
        """#551 — the Fronius Verto shape (issue reporter): Two-sensor
        power_config + stat_soc, NO top-level stat_rate. Previously SEM saw
        no battery power at all ('sensor unavailable') and no SOC."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.fronius_storage_discharging_lifetime_energy",
            "stat_energy_to": "sensor.fronius_storage_charging_lifetime_energy",
            "power_config": {
                "stat_rate_from": "sensor.fronius_storage_discharging_power",
                "stat_rate_to": "sensor.fronius_storage_charging_power",
            },
            "stat_soc": "sensor.fronius_ladezustand",
        }
        _extract_battery_config(source, config)
        assert config.battery_power is None  # no combined entity exists
        assert config.battery_power_from == "sensor.fronius_storage_discharging_power"
        assert config.battery_power_to == "sensor.fronius_storage_charging_power"
        assert config.battery_soc == "sensor.fronius_ladezustand"
        assert config.battery_soc_list == ["sensor.fronius_ladezustand"]
        assert config.has_battery is True
        # Two-sensor power is fully resolved — must not trip the #274
        # re-derivation canary.
        config.has_solar = True
        config.has_grid = True
        config.solar_power = "sensor.pv"
        config.solar_energy = "sensor.pv_e"
        assert config.power_resolution_incomplete() is False

    def test_extract_battery_stat_soc_without_power_config(self):
        """#551 — stat_soc parsed independently of the power mode."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.b_discharge",
            "stat_rate": "sensor.b_power",
            "stat_soc": "sensor.b_soc",
        }
        _extract_battery_config(source, config)
        assert config.battery_soc == "sensor.b_soc"
        assert config.battery_power == "sensor.b_power"

    def test_extract_battery_config_fallback_stat_power(self):
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.batt_discharge",
            "stat_power": "sensor.batt_power_old",
        }
        _extract_battery_config(source, config)
        assert config.battery_power == "sensor.batt_power_old"
        assert config.has_battery is True

    def test_extract_battery_two_units(self):
        """Two battery sources — both in list, primary = first."""
        config = EnergyDashboardConfig()
        source1 = {
            "stat_energy_from": "sensor.sessy1_discharged",
            "stat_energy_to": "sensor.sessy1_charged",
            "stat_rate": "sensor.sessy1_power",
        }
        source2 = {
            "stat_energy_from": "sensor.sessy2_discharged",
            "stat_energy_to": "sensor.sessy2_charged",
            "stat_rate": "sensor.sessy2_power",
        }
        _extract_battery_config(source1, config)
        _extract_battery_config(source2, config)
        # Primary is first
        assert config.battery_power == "sensor.sessy1_power"
        assert config.battery_discharge_energy == "sensor.sessy1_discharged"
        assert config.battery_charge_energy == "sensor.sessy1_charged"
        # Lists have both
        assert config.battery_power_list == [
            "sensor.sessy1_power",
            "sensor.sessy2_power",
        ]
        assert config.battery_charge_energy_list == [
            "sensor.sessy1_charged",
            "sensor.sessy2_charged",
        ]
        assert config.battery_discharge_energy_list == [
            "sensor.sessy1_discharged",
            "sensor.sessy2_discharged",
        ]
        assert config.has_battery is True

    def test_extract_battery_single_backward_compat(self):
        """Single battery — list has one entry, same as primary."""
        config = EnergyDashboardConfig()
        source = {
            "stat_energy_from": "sensor.batt_discharge",
            "stat_energy_to": "sensor.batt_charge",
            "stat_rate": "sensor.batt_power",
        }
        _extract_battery_config(source, config)
        assert config.battery_power == "sensor.batt_power"
        assert config.battery_power_list == ["sensor.batt_power"]


class TestExtractEvFromDevices:
    """Test _extract_ev_from_devices()."""

    def test_extract_ev_from_devices(self):
        config = EnergyDashboardConfig()
        devices = [
            {"stat_consumption": "sensor.keba_total_energy", "stat_rate": "sensor.keba_power"},
        ]
        _extract_ev_from_devices(devices, config)
        assert config.has_ev is True
        assert config.ev_energy == "sensor.keba_total_energy"
        assert config.ev_power == "sensor.keba_power"

    def test_extract_ev_no_match(self):
        config = EnergyDashboardConfig()
        devices = [
            {"stat_consumption": "sensor.washing_machine_energy", "stat_rate": "sensor.washing_machine_power"},
        ]
        _extract_ev_from_devices(devices, config)
        assert config.has_ev is False

    def test_extract_ev_wallbox_pattern(self):
        config = EnergyDashboardConfig()
        devices = [
            {"stat_consumption": "sensor.wallbox_energy", "stat_rate": "sensor.wallbox_power"},
        ]
        _extract_ev_from_devices(devices, config)
        assert config.has_ev is True

    def test_extract_ev_easee_pattern(self):
        config = EnergyDashboardConfig()
        devices = [
            {"stat_consumption": "sensor.easee_lifetime_energy"},
        ]
        _extract_ev_from_devices(devices, config)
        assert config.has_ev is True


class TestReadEnergyDashboardConfig:
    """Test read_energy_dashboard_config() async function."""

    @pytest.mark.asyncio
    async def test_read_energy_dashboard_config_success(self, mock_hass):
        async def run_func(func):
            return func()

        mock_hass.async_add_executor_job = AsyncMock(side_effect=run_func)

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(SAMPLE_ENERGY_DATA))):
                config = await read_energy_dashboard_config(mock_hass)

        assert config is not None
        assert config.has_solar is True
        assert config.has_grid is True
        assert config.has_battery is True
        assert config.has_ev is True
        assert config.solar_energy == "sensor.solar_energy"
        assert config.solar_power == "sensor.solar_power"
        assert config.grid_import_energy == "sensor.grid_import_energy"
        assert config.grid_export_energy == "sensor.grid_export_energy"
        assert config.battery_discharge_energy == "sensor.battery_discharge"
        assert config.battery_charge_energy == "sensor.battery_charge"
        assert config.ev_energy == "sensor.keba_total_energy"

    @pytest.mark.asyncio
    async def test_read_energy_dashboard_config_no_file(self, mock_hass):
        async def run_func(func):
            return func()

        mock_hass.async_add_executor_job = AsyncMock(side_effect=run_func)

        with patch("os.path.exists", return_value=False):
            config = await read_energy_dashboard_config(mock_hass)

        assert config is None

    @pytest.mark.asyncio
    async def test_read_energy_dashboard_config_parse_error(self, mock_hass):
        async def run_func(func):
            return func()

        mock_hass.async_add_executor_job = AsyncMock(side_effect=run_func)

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="not valid json {")):
                config = await read_energy_dashboard_config(mock_hass)

        assert config is None

    @pytest.mark.asyncio
    async def test_read_energy_dashboard_config_no_data_section(self, mock_hass):
        async def run_func(func):
            return func()

        mock_hass.async_add_executor_job = AsyncMock(side_effect=run_func)
        no_data = {"version": 1}

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(no_data))):
                config = await read_energy_dashboard_config(mock_hass)

        assert config is None


SAMPLE_MULTI_DEVICE_DATA = {
    "data": {
        "energy_sources": [
            {
                "type": "solar",
                "stat_energy_from": "sensor.inverter1_energy",
                "stat_rate": "sensor.inverter1_power",
            },
            {
                "type": "solar",
                "stat_energy_from": "sensor.inverter2_energy",
                "stat_rate": "sensor.inverter2_power",
            },
            {
                "type": "grid",
                "flow_from": [
                    {"stat_energy_from": "sensor.grid_import_tarief_1"},
                    {"stat_energy_from": "sensor.grid_import_tarief_2"},
                ],
                "flow_to": [
                    {"stat_energy_to": "sensor.grid_export_tarief_1"},
                    {"stat_energy_to": "sensor.grid_export_tarief_2"},
                ],
                "power": [{"stat_rate": "sensor.grid_power"}],
            },
            {
                "type": "battery",
                "stat_energy_from": "sensor.sessy1_discharged",
                "stat_energy_to": "sensor.sessy1_charged",
                "stat_rate": "sensor.sessy1_power",
            },
            {
                "type": "battery",
                "stat_energy_from": "sensor.sessy2_discharged",
                "stat_energy_to": "sensor.sessy2_charged",
                "stat_rate": "sensor.sessy2_power",
            },
        ],
        "device_consumption": [
            {
                "stat_consumption": "sensor.wallbox_links_energy",
                "stat_rate": "sensor.wallbox_links_power",
            },
            {
                "stat_consumption": "sensor.wallbox_rechts_energy",
                "stat_rate": "sensor.wallbox_rechts_power",
            },
        ],
    }
}


class TestReadMultiDeviceConfig:
    """Test read_energy_dashboard_config() with multi-device setups."""

    @pytest.mark.asyncio
    async def test_multi_device_full(self, mock_hass):
        """Full multi-device setup: 2 inverters, 2 tariffs, 2 batteries, 2 wallboxes."""
        async def run_func(func):
            return func()

        mock_hass.async_add_executor_job = AsyncMock(side_effect=run_func)

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(SAMPLE_MULTI_DEVICE_DATA))):
                config = await read_energy_dashboard_config(mock_hass)

        assert config is not None
        # Solar: 2 inverters
        assert config.has_solar is True
        assert len(config.solar_power_list) == 2
        assert config.solar_power == "sensor.inverter1_power"
        assert config.solar_power_list[1] == "sensor.inverter2_power"
        # Grid: 2 tariffs
        assert config.has_grid is True
        assert len(config.grid_import_energy_list) == 2
        assert config.grid_import_energy == "sensor.grid_import_tarief_1"
        # Battery: 2 units
        assert config.has_battery is True
        assert len(config.battery_power_list) == 2
        assert config.battery_power == "sensor.sessy1_power"
        assert config.battery_power_list[1] == "sensor.sessy2_power"
        # EV: first wallbox matched
        assert config.has_ev is True
        assert config.ev_power == "sensor.wallbox_links_power"

    @pytest.mark.asyncio
    async def test_single_device_backward_compat(self, mock_hass):
        """Single-device setup still works — lists have exactly one entry."""
        async def run_func(func):
            return func()

        mock_hass.async_add_executor_job = AsyncMock(side_effect=run_func)

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(SAMPLE_ENERGY_DATA))):
                config = await read_energy_dashboard_config(mock_hass)

        assert config is not None
        assert len(config.solar_power_list) == 1
        assert config.solar_power_list[0] == config.solar_power
        assert len(config.battery_power_list) == 1
        assert config.battery_power_list[0] == config.battery_power
        assert len(config.grid_import_energy_list) == 1
        assert config.grid_import_energy_list[0] == config.grid_import_energy


class TestGetAllIndividualDevices:
    """Test get_all_individual_devices()."""

    def test_get_all_individual_devices(self):
        config = EnergyDashboardConfig(
            device_consumption=[
                {"stat_consumption": "sensor.keba_total_energy", "stat_rate": "sensor.keba_power"},
                {"stat_consumption": "sensor.heizband_energy", "stat_rate": "sensor.heizband_power"},
            ]
        )
        devices = get_all_individual_devices(config)
        assert len(devices) == 2
        assert devices[0]["energy_sensor"] == "sensor.keba_total_energy"
        assert devices[0]["power_sensor"] == "sensor.keba_power"
        assert devices[0]["is_ev"] is True
        assert devices[1]["is_ev"] is False

    def test_get_all_individual_devices_name_derivation(self):
        config = EnergyDashboardConfig(
            device_consumption=[
                {"stat_consumption": "sensor.heizband_energy"},
            ]
        )
        devices = get_all_individual_devices(config)
        assert len(devices) == 1
        assert devices[0]["name"] == "Heizband"  # Derived: strip sensor., strip _energy, title case

    def test_get_all_individual_devices_with_explicit_name(self):
        config = EnergyDashboardConfig(
            device_consumption=[
                {"stat_consumption": "sensor.some_device", "name": "My Device"},
            ]
        )
        devices = get_all_individual_devices(config)
        assert devices[0]["name"] == "My Device"

    def test_get_all_individual_devices_empty(self):
        config = EnergyDashboardConfig()
        devices = get_all_individual_devices(config)
        assert devices == []


class TestValidateEnergyDashboardSensors:
    """Test validate_energy_dashboard_sensors()."""

    @pytest.mark.asyncio
    async def test_validate_sensors_all_valid(self, mock_hass):
        mock_state = MagicMock()
        mock_state.state = "100"
        mock_hass.states.get = MagicMock(return_value=mock_state)

        config = EnergyDashboardConfig(
            solar_power="sensor.solar_power",
            solar_energy="sensor.solar_energy",
            grid_import_power="sensor.grid_power",
            grid_import_energy="sensor.grid_import_energy",
        )
        results = await validate_energy_dashboard_sensors(mock_hass, config)
        assert results["solar_power"] is True
        assert results["solar_energy"] is True
        assert results["grid_import_power"] is True
        assert results["grid_import_energy"] is True

    @pytest.mark.asyncio
    async def test_validate_sensors_some_missing(self, mock_hass):
        def mock_get(entity_id):
            if entity_id == "sensor.solar_power":
                state = MagicMock()
                state.state = "500"
                return state
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)

        config = EnergyDashboardConfig(
            solar_power="sensor.solar_power",
            solar_energy="sensor.solar_energy_missing",
        )
        results = await validate_energy_dashboard_sensors(mock_hass, config)
        assert results["solar_power"] is True
        assert results["solar_energy"] is False

    @pytest.mark.asyncio
    async def test_validate_sensors_not_configured(self, mock_hass):
        config = EnergyDashboardConfig()
        results = await validate_energy_dashboard_sensors(mock_hass, config)
        # All should be False since nothing is configured
        for _key, value in results.items():
            assert value is False


class TestBatteryDeriveRespectsPairs:
    """(#761, jappish84) The #744-era battery power deriver saw
    ``battery_power`` unset and derived the device's combined sensor —
    but a two-sensor power_config (#551) leaves it unset BY DESIGN ("the
    reader computes net = to − from"). The derive then created a SECOND
    power representation of the same physical battery: units b1 (derived
    combined) + b2 (the pair), identical values, summed — battery read
    2× while charging and home followed. The deriver's guard is "no
    power representation AT ALL", pairs included."""

    def _config_with_pair(self):
        from custom_components.solar_energy_management.ha_energy_reader import (
            EnergyDashboardConfig, _extract_battery_config,
        )
        config = EnergyDashboardConfig()
        _extract_battery_config({
            "stat_energy_from": "sensor.batt_discharge_total",
            "stat_energy_to": "sensor.batt_charge_total",
            "power_config": {
                "stat_rate_from": "sensor.batt_discharge_power",
                "stat_rate_to": "sensor.batt_charge_power",
            },
        }, config)
        return config

    def test_a_pair_is_a_power_representation(self):
        from custom_components.solar_energy_management import ha_energy_reader as her
        config = self._config_with_pair()
        assert config.battery_power_pairs
        assert not config.battery_power
        # The derive step must NOT add a combined sensor beside the pair.
        from unittest.mock import MagicMock, patch
        with patch.object(her, "_find_power_sensor_on_device",
                          return_value="sensor.batt_combined_power") as find:
            her._derive_battery_power_if_unrepresented(MagicMock(), config)
        find.assert_not_called()
        assert config.battery_power_list == []
        assert config.battery_power is None

    def test_a_counters_only_battery_still_derives(self):
        """The derive exists for a reason: counters with NO power
        representation anywhere still want a live power source."""
        from custom_components.solar_energy_management.ha_energy_reader import (
            EnergyDashboardConfig, _extract_battery_config,
        )
        from custom_components.solar_energy_management import ha_energy_reader as her
        config = EnergyDashboardConfig()
        _extract_battery_config({
            "stat_energy_from": "sensor.batt_discharge_total",
            "stat_energy_to": "sensor.batt_charge_total",
        }, config)
        from unittest.mock import MagicMock, patch
        with patch.object(her, "_find_power_sensor_on_device",
                          return_value="sensor.batt_combined_power"):
            her._derive_battery_power_if_unrepresented(MagicMock(), config)
        assert config.battery_power == "sensor.batt_combined_power"
        assert config.battery_power_list == ["sensor.batt_combined_power"]
