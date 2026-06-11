"""Integration tests for the full sensor pipeline.

Tests the complete chain for ALL supported hardware patterns:
1. Grid power: combined vs split vs solar-only (6 sign convention patterns)
2. EV charger: service vs number entity, kW vs W units
3. Energy balance: validates balance holds for every configuration

These tests verify that components work TOGETHER, not just in isolation.
The Growatt issue (#129) exposed that unit tests pass individually but
the full pipeline was never tested.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _state(value, unit="W", device_class=None):
    """Create a mock HA state."""
    s = MagicMock()
    s.state = str(value)
    s.entity_id = f"sensor.mock_{id(s)}"
    s.attributes = {"unit_of_measurement": unit}
    if device_class:
        s.attributes["device_class"] = device_class
    return s


def _make_energy_dashboard_config(
    solar_power="sensor.inverter_power",
    grid_import_power=None,
    grid_import_energy="sensor.grid_import_total",
    grid_export_energy="sensor.grid_export_total",
    battery_power="sensor.battery_power",
    battery_charge_energy="sensor.battery_charge_total",
    battery_discharge_energy="sensor.battery_discharge_total",
    solar_power_list=None,
    grid_power_list=None,
    battery_power_list=None,
):
    """Create a mock Energy Dashboard config."""
    ed = MagicMock()
    ed.solar_power = solar_power
    ed.solar_power_list = solar_power_list or ([solar_power] if solar_power else [])
    ed.grid_import_power = grid_import_power
    ed.grid_power_list = grid_power_list or ([grid_import_power] if grid_import_power else [])
    ed.grid_import_energy = grid_import_energy
    ed.grid_export_energy = grid_export_energy
    ed.grid_import_energy_list = [grid_import_energy] if grid_import_energy else []
    ed.grid_export_energy_list = [grid_export_energy] if grid_export_energy else []
    ed.battery_power = battery_power
    ed.battery_power_list = battery_power_list or ([battery_power] if battery_power else [])
    ed.battery_charge_energy = battery_charge_energy
    ed.battery_discharge_energy = battery_discharge_energy
    ed.ev_power = None
    ed.has_solar = bool(solar_power)
    ed.has_grid = bool(grid_import_energy or grid_import_power or grid_power_list)
    ed.has_battery = bool(battery_power)
    ed.has_ev = False
    return ed


def _make_reader_with_states(mock_hass, states_dict, ed_config, extra_config=None):
    """Create a SensorReader with mock states and Energy Dashboard config."""
    def mock_get(entity_id):
        return states_dict.get(entity_id)

    def mock_async_all(domain=None):
        all_states = []
        for eid, state in states_dict.items():
            s = MagicMock()
            s.entity_id = eid
            s.state = state.state
            s.attributes = state.attributes
            if domain is None or eid.startswith(f"{domain}."):
                all_states.append(s)
        return all_states

    mock_hass.states.get = mock_get
    mock_hass.states.async_all = mock_async_all

    config = {"update_interval": 10}
    if extra_config:
        config.update(extra_config)

    reader = SensorReader(mock_hass, config)
    reader._energy_dashboard_config = ed_config
    return reader


# ════════════════════════════════════════════
# Growatt: split grid sensors (no combined power)
# ════════════════════════════════════════════

class TestGrowattSplitGrid:
    """Test full pipeline for Growatt with split import/export power sensors."""

    def test_exporting_2kw(self):
        """Growatt exporting 2kW: grid_power should be +2000 (SEM: positive=export)."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,  # No combined sensor!
            grid_import_energy="sensor.mix_import_from_grid_today",
            grid_export_energy="sensor.mix_export_to_grid_today",
            battery_power="sensor.growatt_battery_power",
        )

        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.growatt_battery_power": _state(0),
            "sensor.mix_import_from_grid": _state(0, device_class="power"),
            "sensor.mix_export_to_grid": _state(2000, device_class="power"),
            "sensor.mix_import_from_grid_today": _state(10, "kWh"),
            "sensor.mix_export_to_grid_today": _state(20, "kWh"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        # Split sensors: grid_power = export - import = 2000 - 0 = 2000
        assert power.grid_power == 2000
        power.calculate_derived()
        assert power.grid_export_power == 2000
        assert power.grid_import_power == 0
        assert power.home_consumption_power > 0  # solar - export = 3000

    def test_importing_1500w(self):
        """Growatt importing 1.5kW: grid_power should be -1500 (SEM: negative=import)."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.mix_import_from_grid_today",
            grid_export_energy="sensor.mix_export_to_grid_today",
            battery_power="sensor.growatt_battery_power",
        )

        states = {
            "sensor.growatt_solar_power": _state(1000),
            "sensor.growatt_battery_power": _state(0),
            "sensor.mix_import_from_grid": _state(1500, device_class="power"),
            "sensor.mix_export_to_grid": _state(0, device_class="power"),
            "sensor.mix_import_from_grid_today": _state(10, "kWh"),
            "sensor.mix_export_to_grid_today": _state(20, "kWh"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == -1500
        power.calculate_derived()
        assert power.grid_import_power == 1500
        assert power.grid_export_power == 0
        assert power.home_consumption_power > 0  # solar + import = 2500

    def test_split_discovery_cached(self):
        """Split sensor discovery should only run once, then cache."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.mix_import_from_grid_today",
            grid_export_energy="sensor.mix_export_to_grid_today",
            battery_power=None,
        )

        states = {
            "sensor.growatt_solar_power": _state(3000),
            "sensor.mix_import_from_grid": _state(500, device_class="power"),
            "sensor.mix_export_to_grid": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)

        # First read: triggers discovery
        power1 = reader.read_power()
        assert reader._split_grid_discovery["import"] is not None

        # Second read: uses cached discovery
        power2 = reader.read_power()
        assert power2.grid_power == power1.grid_power

    def test_no_split_sensors_found(self):
        """When no split sensors exist, grid_power should be 0."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.some_energy_counter",
            grid_export_energy="sensor.some_export_counter",
            battery_power=None,
        )

        # No split power sensors in the system
        states = {
            "sensor.growatt_solar_power": _state(3000),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        # No discovery match → grid_power stays at 0
        assert power.grid_power == 0

    def test_tlx_pac_sensors(self):
        """Growatt TLX uses pac_to_user/pac_to_grid naming."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.tlx_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.tlx_import_energy",
            grid_export_energy="sensor.tlx_export_energy",
            battery_power=None,
        )

        states = {
            "sensor.tlx_solar_power": _state(8000),
            "sensor.tlx_pac_to_user_total": _state(0, device_class="power"),
            "sensor.tlx_pac_to_grid_total": _state(5000, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == 5000  # Exporting
        power.calculate_derived()
        assert power.grid_export_power == 5000
        assert power.home_consumption_power == 3000  # 8000 - 5000


# ════════════════════════════════════════════
# DSMR/P1 smart meter: split grid sensors (NL/BE)
# ════════════════════════════════════════════

class TestDSMRSplitGrid:
    """Test full pipeline for DSMR/P1 smart meter with split power sensors.

    Common in Netherlands and Belgium — dual-tariff metering with separate
    power_consumption (import) and power_production (export) sensors.
    """

    def test_dsmr_exporting(self):
        """DSMR exporting 2kW: power_production=2000, power_consumption=0."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power="sensor.sessy_power",
        )

        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.sessy_power": _state(0),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(2000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == 2000  # export - import = 2000 - 0
        power.calculate_derived()
        assert power.grid_export_power == 2000
        assert power.grid_import_power == 0
        assert power.home_consumption_power == 3000  # 5000 - 2000

    def test_dsmr_importing(self):
        """DSMR importing 1.5kW: power_consumption=1500, power_production=0."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power="sensor.sessy_power",
        )

        states = {
            "sensor.growatt_solar_power": _state(500),
            "sensor.sessy_power": _state(0),
            "sensor.electricity_meter_power_consumption": _state(1500, device_class="power"),
            "sensor.electricity_meter_power_production": _state(0, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == -1500  # export - import = 0 - 1500
        power.calculate_derived()
        assert power.grid_import_power == 1500
        assert power.grid_export_power == 0
        assert power.home_consumption_power == 2000  # 500 + 1500

    def test_dsmr_dual_tariff_with_battery(self):
        """DSMR dual-tariff + two Sessy batteries: full energy balance."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power="sensor.sessy_power",
        )

        states = {
            "sensor.growatt_solar_power": _state(6000),
            "sensor.sessy_power": _state(1000),  # Charging 1kW
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Balance: solar(6000) = home(2000) + export(3000) + charge(1000)
        assert power.grid_export_power == 3000
        assert power.battery_charge_power == 1000
        assert power.home_consumption_power == 2000
        energy_in = power.solar_power + power.grid_import_power + power.battery_discharge_power
        energy_out = power.home_consumption_power + power.grid_export_power + power.battery_charge_power + power.ev_power
        assert abs(energy_in - energy_out) < 1, f"Balance off: in={energy_in}, out={energy_out}"

    def test_dsmr_no_false_positive_heat_pump(self):
        """Heat pump power_consumption should NOT match when device filtering is active."""
        from unittest.mock import patch

        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power=None,
        )

        states = {
            "sensor.growatt_solar_power": _state(5000),
            # DSMR meter sensors (device_id = "meter_device")
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            # Heat pump sensor (different device_id = "heatpump_device")
            "sensor.heat_pump_power_consumption": _state(2000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }

        # Mock entity registry to return device_ids
        mock_registry = MagicMock()
        def mock_async_get_entry(entity_id):
            entry = MagicMock()
            if "electricity_meter" in entity_id:
                entry.device_id = "meter_device"
            elif "heat_pump" in entity_id:
                entry.device_id = "heatpump_device"
            else:
                entry.device_id = "other_device"
            return entry
        mock_registry.async_get = mock_async_get_entry

        reader = _make_reader_with_states(hass, states, ed)

        with patch("custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get", return_value=mock_registry):
            power = reader.read_power()

        # Should pick meter sensors (same device), NOT heat pump
        assert reader._split_grid_discovery["import"] == "sensor.electricity_meter_power_consumption"
        assert reader._split_grid_discovery["export"] == "sensor.electricity_meter_power_production"
        assert reader._split_grid_discovery["confidence"] == "same-device"
        assert power.grid_power == 3000  # export - import = 3000 - 0


# ════════════════════════════════════════════
# E3DC: split grid sensors
# ════════════════════════════════════════════

class TestE3DCSplitGrid:
    """Test full pipeline for E3DC with split consumption/export sensors."""

    def test_e3dc_exporting(self):
        """E3DC exporting: consumption_from_grid=0, export_to_grid=3000."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.s10x_solar_production",
            grid_import_power=None,
            grid_import_energy="sensor.s10x_grid_import_energy",
            grid_export_energy="sensor.s10x_grid_export_energy",
            battery_power="sensor.s10x_battery_power",
        )

        states = {
            "sensor.s10x_solar_production": _state(6000),
            "sensor.s10x_battery_power": _state(1000),  # Charging
            "sensor.s10x_consumption_from_grid": _state(0, device_class="power"),
            "sensor.s10x_export_to_grid": _state(2000, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == 2000
        power.calculate_derived()
        assert power.grid_export_power == 2000
        assert power.grid_import_power == 0
        assert power.home_consumption_power == 3000  # 6000 - 2000 - 1000

    def test_e3dc_importing(self):
        """E3DC importing: consumption_from_grid=1500, export_to_grid=0."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.s10x_solar_production",
            grid_import_power=None,
            grid_import_energy="sensor.s10x_grid_import_energy",
            grid_export_energy="sensor.s10x_grid_export_energy",
            battery_power=None,
        )

        states = {
            "sensor.s10x_solar_production": _state(500),
            "sensor.s10x_consumption_from_grid": _state(1500, device_class="power"),
            "sensor.s10x_export_to_grid": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == -1500
        power.calculate_derived()
        assert power.grid_import_power == 1500
        assert power.grid_export_power == 0


# ════════════════════════════════════════════
# GivEnergy: Pattern C (grid +=export, battery +=discharge)
# ════════════════════════════════════════════

class TestGivEnergySplitGrid:
    """Test GivEnergy with split import_power/export_power sensors."""

    def test_givenergy_exporting(self):
        """GivEnergy exporting 3kW via split sensors."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.givtcp_abc123_pv_power",
            grid_import_power=None,
            grid_import_energy="sensor.givtcp_abc123_grid_import_energy",
            grid_export_energy="sensor.givtcp_abc123_grid_export_energy",
            battery_power="sensor.givtcp_abc123_battery_power",
        )

        states = {
            "sensor.givtcp_abc123_pv_power": _state(6000),
            "sensor.givtcp_abc123_battery_power": _state(0),
            "sensor.givtcp_abc123_import_power": _state(0, device_class="power"),
            "sensor.givtcp_abc123_export_power": _state(3000, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == 3000  # export - import
        power.calculate_derived()
        assert power.grid_export_power == 3000
        assert power.grid_import_power == 0
        assert power.home_consumption_power == 3000

    def test_givenergy_importing(self):
        """GivEnergy importing 2kW at night."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.givtcp_abc123_pv_power",
            grid_import_power=None,
            grid_import_energy="sensor.givtcp_abc123_grid_import_energy",
            grid_export_energy="sensor.givtcp_abc123_grid_export_energy",
            battery_power="sensor.givtcp_abc123_battery_power",
        )

        states = {
            "sensor.givtcp_abc123_pv_power": _state(0),
            "sensor.givtcp_abc123_battery_power": _state(0),
            "sensor.givtcp_abc123_import_power": _state(2000, device_class="power"),
            "sensor.givtcp_abc123_export_power": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == -2000
        power.calculate_derived()
        assert power.grid_import_power == 2000
        assert power.grid_export_power == 0


# ════════════════════════════════════════════
# Fox ESS: Pattern A (grid +=export, battery +=charge) — combined
# ════════════════════════════════════════════

class TestFoxESSCombined:
    """Test Fox ESS with combined grid_ct sensor (Pattern A)."""

    def test_foxess_exporting(self):
        """Fox ESS exporting: grid_ct positive = export."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.foxess_pv1_power",
            grid_import_power="sensor.foxess_grid_ct",
            battery_power="sensor.foxess_battery_power",
        )

        states = {
            "sensor.foxess_pv1_power": _state(5000),
            "sensor.foxess_grid_ct": _state(2000),     # +2kW = export
            "sensor.foxess_battery_power": _state(1000),  # +1kW = charge
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Pattern A: same as SEM convention
        assert power.grid_export_power == 2000
        assert power.grid_import_power == 0
        assert power.battery_charge_power == 1000
        assert power.home_consumption_power == 2000  # 5000 - 2000 - 1000


# ════════════════════════════════════════════
# Alpha ESS: Pattern C (grid +=export, battery +=discharge) — combined
# ════════════════════════════════════════════

class TestAlphaESSCombined:
    """Test Alpha ESS Modbus with combined pmeter (Pattern C)."""

    def test_alphaess_exporting_discharging(self):
        """Alpha ESS exporting 1kW, battery discharging 500W."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.alpha_ess_ppv1",
            grid_import_power="sensor.alpha_ess_pmeter_l1",
            battery_power="sensor.alpha_ess_pbat",
        )

        states = {
            "sensor.alpha_ess_ppv1": _state(3000),
            "sensor.alpha_ess_pmeter_l1": _state(1000),   # +1kW = export
            "sensor.alpha_ess_pbat": _state(500),          # +500W = discharge
        }

        reader = _make_reader_with_states(hass, states, ed)
        # Pattern C: grid +=export (same as SEM), battery +=discharge (opposite of SEM)
        # #404: state is per-battery-id keyed. Fleet/single-battery
        # path uses the ``_FLEET_BID`` sentinel.
        reader._battery_sign_inverted = {reader._FLEET_BID: True}
        reader._battery_sign_detected = {reader._FLEET_BID: True}
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_export_power == 1000
        assert power.battery_discharge_power == 500
        assert power.home_consumption_power == 2500  # 3000 + 500 - 1000


# ════════════════════════════════════════════
# Senec: Pattern B (grid +=import, battery +=discharge) — split
# ════════════════════════════════════════════

class TestSenecSplitGrid:
    """Test Senec with split grid_imported/exported_power sensors."""

    def test_senec_exporting(self):
        """Senec exporting via split sensors."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.senec_solar_generated_power",
            grid_import_power=None,
            grid_import_energy="sensor.senec_grid_imported_energy",
            grid_export_energy="sensor.senec_grid_exported_energy",
            battery_power="sensor.senec_battery_state_power",
        )

        states = {
            "sensor.senec_solar_generated_power": _state(5000),
            "sensor.senec_battery_state_power": _state(0),
            "sensor.senec_grid_imported_power": _state(0, device_class="power"),
            "sensor.senec_grid_exported_power": _state(3000, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == 3000
        power.calculate_derived()
        assert power.grid_export_power == 3000
        assert power.home_consumption_power == 2000

    def test_senec_importing(self):
        """Senec importing via split sensors."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.senec_solar_generated_power",
            grid_import_power=None,
            grid_import_energy="sensor.senec_grid_imported_energy",
            grid_export_energy="sensor.senec_grid_exported_energy",
            battery_power=None,
        )

        states = {
            "sensor.senec_solar_generated_power": _state(500),
            "sensor.senec_grid_imported_power": _state(1500, device_class="power"),
            "sensor.senec_grid_exported_power": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == -1500
        power.calculate_derived()
        assert power.grid_import_power == 1500


# ════════════════════════════════════════════
# RCT Power: Pattern B (grid +=import, battery +=discharge) — combined
# ════════════════════════════════════════════

class TestRCTPowerCombined:
    """Test RCT Power with combined grid sensor (Pattern B)."""

    def test_rctpower_importing(self):
        """RCT Power importing: grid positive = import."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.rct_generators_power",
            grid_import_power="sensor.rct_grid_power",
            battery_power="sensor.rct_battery_power",
        )

        states = {
            "sensor.rct_generators_power": _state(2000),
            "sensor.rct_grid_power": _state(1500),     # +1500 = import (Pattern B)
            "sensor.rct_battery_power": _state(500),   # +500 = discharge (Pattern B)
        }

        reader = _make_reader_with_states(hass, states, ed)
        # Pattern B: grid +=import, battery +=discharge — both opposite of SEM
        reader._grid_sign_inverted = True
        # #404: state is per-battery-id keyed. Fleet path uses ``_FLEET_BID``.
        reader._battery_sign_inverted = {reader._FLEET_BID: True}
        reader._grid_sign_detected = True
        reader._battery_sign_detected = {reader._FLEET_BID: True}
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_import_power == 1500
        assert power.battery_discharge_power == 500
        assert power.home_consumption_power > 0


# ════════════════════════════════════════════
# KSTAR: Pattern A (grid +=export, battery +=charge) — combined
# ════════════════════════════════════════════

class TestKSTARCombined:
    """Test KSTAR via ha-solarman with combined grid sensor (Pattern A)."""

    def test_kstar_exporting_charging(self):
        """KSTAR exporting 2kW, battery charging 1kW."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.kstar_total_pv_power",
            grid_import_power="sensor.kstar_total_grid_power",
            battery_power="sensor.kstar_battery_power",
        )

        states = {
            "sensor.kstar_total_pv_power": _state(6000),
            "sensor.kstar_total_grid_power": _state(2000),  # +2kW = export
            "sensor.kstar_battery_power": _state(1000),     # +1kW = charge
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Pattern A: same as SEM convention
        assert power.grid_export_power == 2000
        assert power.battery_charge_power == 1000
        assert power.home_consumption_power == 3000  # 6000 - 2000 - 1000


# ════════════════════════════════════════════
# Sessy: Battery-only with external P1 meter
# ════════════════════════════════════════════

class TestSessyBatteryOnly:
    """Test Sessy battery system (no PV, grid via DSMR P1 meter)."""

    def test_sessy_charging_from_grid(self):
        """Sessy charging from grid: battery negative = charge, grid importing."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power=None,
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption",
            grid_export_energy="sensor.electricity_meter_energy_production",
            battery_power="sensor.sessy_battery_power",
        )

        states = {
            "sensor.sessy_battery_power": _state(2000),  # Charging
            "sensor.electricity_meter_power_consumption": _state(3000, device_class="power"),
            "sensor.electricity_meter_power_production": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_import_power == 3000
        assert power.battery_charge_power == 2000
        assert power.home_consumption_power == 1000  # 3000 - 2000

    def test_sessy_discharging_to_home(self):
        """Sessy discharging to home, reducing grid import."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power=None,
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption",
            grid_export_energy="sensor.electricity_meter_energy_production",
            battery_power="sensor.sessy_battery_power",
        )

        states = {
            "sensor.sessy_battery_power": _state(-1500),  # Discharging
            "sensor.electricity_meter_power_consumption": _state(500, device_class="power"),
            "sensor.electricity_meter_power_production": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_import_power == 500
        assert power.battery_discharge_power == 1500
        assert power.home_consumption_power == 2000  # 500 + 1500


# ════════════════════════════════════════════
# Manual grid power entity override
# ════════════════════════════════════════════

class TestManualGridConfig:
    """Test manual grid import/export power entity configuration.

    When auto-detection fails, users can manually set grid power sensors
    in Tariff & Advanced settings. These override all auto-detection.
    """

    def test_manual_override_exporting(self):
        """Manual grid sensors: exporting 2kW."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.grid_energy_import",
            grid_export_energy="sensor.grid_energy_export",
            battery_power=None,
        )

        states = {
            "sensor.solar_power": _state(5000),
            "sensor.my_grid_import_w": _state(0, device_class="power"),
            "sensor.my_grid_export_w": _state(2000, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed, extra_config={
            "grid_import_power_entity": "sensor.my_grid_import_w",
            "grid_export_power_entity": "sensor.my_grid_export_w",
        })
        power = reader.read_power()

        assert power.grid_power == 2000
        power.calculate_derived()
        assert power.grid_export_power == 2000
        assert power.grid_import_power == 0

    def test_manual_override_importing(self):
        """Manual grid sensors: importing 1.5kW."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.grid_energy_import",
            grid_export_energy="sensor.grid_energy_export",
            battery_power=None,
        )

        states = {
            "sensor.solar_power": _state(500),
            "sensor.my_grid_import_w": _state(1500, device_class="power"),
            "sensor.my_grid_export_w": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed, extra_config={
            "grid_import_power_entity": "sensor.my_grid_import_w",
            "grid_export_power_entity": "sensor.my_grid_export_w",
        })
        power = reader.read_power()

        assert power.grid_power == -1500
        power.calculate_derived()
        assert power.grid_import_power == 1500
        assert power.grid_export_power == 0

    def test_manual_overrides_auto_detection(self):
        """Manual config takes priority over Energy Dashboard stat_rate."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.wrong_combined_sensor",  # Would be used by auto
            grid_import_energy="sensor.grid_energy_import",
            grid_export_energy="sensor.grid_energy_export",
            battery_power=None,
        )

        states = {
            "sensor.solar_power": _state(3000),
            "sensor.wrong_combined_sensor": _state(9999, device_class="power"),
            "sensor.correct_import": _state(500, device_class="power"),
            "sensor.correct_export": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed, extra_config={
            "grid_import_power_entity": "sensor.correct_import",
            "grid_export_power_entity": "sensor.correct_export",
        })
        power = reader.read_power()

        # Manual config wins — should NOT use wrong_combined_sensor (9999)
        assert power.grid_power == -500  # 0 - 500
        power.calculate_derived()
        assert power.grid_import_power == 500

    def test_manual_import_only(self):
        """Only import entity set, export defaults to 0."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.grid_energy_import",
            grid_export_energy="sensor.grid_energy_export",
            battery_power=None,
        )

        states = {
            "sensor.solar_power": _state(1000),
            "sensor.my_grid_import_w": _state(800, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed, extra_config={
            "grid_import_power_entity": "sensor.my_grid_import_w",
        })
        power = reader.read_power()

        assert power.grid_power == -800  # 0 - 800
        power.calculate_derived()
        assert power.grid_import_power == 800
        assert power.grid_export_power == 0

    def test_no_manual_config_falls_through(self):
        """Without manual config, normal auto-detection runs."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_combined",
            battery_power=None,
        )

        states = {
            "sensor.solar_power": _state(3000),
            "sensor.grid_combined": _state(1500, device_class="power"),
        }

        # No manual override in config
        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        # Should use Energy Dashboard combined sensor
        assert power.grid_power == 1500

    def test_manual_energy_balance(self):
        """Full energy balance with manual grid sensors + battery."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.grid_energy_import",
            grid_export_energy="sensor.grid_energy_export",
            battery_power="sensor.battery_power",
        )

        states = {
            "sensor.solar_power": _state(6000),
            "sensor.battery_power": _state(1000),  # Charging
            "sensor.manual_import": _state(0, device_class="power"),
            "sensor.manual_export": _state(3000, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed, extra_config={
            "grid_import_power_entity": "sensor.manual_import",
            "grid_export_power_entity": "sensor.manual_export",
        })
        power = reader.read_power()
        power.calculate_derived()

        # Balance: solar(6000) = home(2000) + export(3000) + charge(1000)
        energy_in = power.solar_power + power.grid_import_power + power.battery_discharge_power
        energy_out = power.home_consumption_power + power.grid_export_power + power.battery_charge_power + power.ev_power
        assert abs(energy_in - energy_out) < 1, f"Balance off: in={energy_in}, out={energy_out}"


# ════════════════════════════════════════════
# Combined grid sensor (Huawei, SolarEdge, etc.)
# ════════════════════════════════════════════

class TestCombinedGridSensor:
    """Verify combined grid sensor pipeline for all sign convention patterns."""

    def test_pattern_a_export_charge(self):
        """Pattern A (Huawei, SMA, Victron): grid +=export, battery +=charge."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.inverter_power",
            grid_import_power="sensor.grid_power",
            battery_power="sensor.battery_power",
        )
        states = {
            "sensor.inverter_power": _state(6000),
            "sensor.grid_power": _state(3000),    # +3kW export
            "sensor.battery_power": _state(1000),  # +1kW charge
        }
        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_export_power == 3000
        assert power.grid_import_power == 0
        assert power.battery_charge_power == 1000
        assert power.battery_discharge_power == 0
        assert power.home_consumption_power == 2000  # 6000 - 3000 - 1000

    def test_pattern_b_import_discharge(self):
        """Pattern B (Fronius, Enphase, Powerwall, Kostal, SolarEdge): grid +=import, battery +=discharge.

        SEM auto-detects and negates both. Raw values are opposite of SEM convention.
        After sign correction: grid_power becomes negative (import), battery_power becomes negative (discharge).
        """
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_power",
            battery_power="sensor.battery_power",
        )
        # Raw: +1500 means importing, +500 means discharging
        states = {
            "sensor.solar_power": _state(3000),
            "sensor.grid_power": _state(1500),    # +1500 = importing (opposite)
            "sensor.battery_power": _state(500),   # +500 = discharging (opposite)
        }
        reader = _make_reader_with_states(hass, states, ed)
        # Simulate sign correction (normally done by auto-detect over multiple cycles)
        reader._grid_sign_inverted = True
        # #404: state is per-battery-id keyed. Fleet path uses ``_FLEET_BID``.
        reader._battery_sign_inverted = {reader._FLEET_BID: True}
        reader._grid_sign_detected = True
        reader._battery_sign_detected = {reader._FLEET_BID: True}
        power = reader.read_power()
        power.calculate_derived()

        # After negation: grid=-1500 (import), battery=-500 (discharge)
        assert power.grid_import_power == 1500
        assert power.grid_export_power == 0
        assert power.battery_discharge_power == 500
        assert power.battery_charge_power == 0
        assert power.home_consumption_power > 0

    def test_pattern_c_export_discharge(self):
        """Pattern C (GoodWe, Sonnen): grid +=export, battery +=discharge."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_power",
            battery_power="sensor.battery_power",
        )
        states = {
            "sensor.solar_power": _state(4000),
            "sensor.grid_power": _state(1000),     # +1kW export (SEM match)
            "sensor.battery_power": _state(800),    # +800W discharge (opposite)
        }
        reader = _make_reader_with_states(hass, states, ed)
        # #404: state is per-battery-id keyed. Fleet/single-battery
        # path uses the ``_FLEET_BID`` sentinel.
        reader._battery_sign_inverted = {reader._FLEET_BID: True}
        reader._battery_sign_detected = {reader._FLEET_BID: True}
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_export_power == 1000
        assert power.battery_discharge_power == 800
        assert power.home_consumption_power > 0

    def test_pattern_d_import_charge(self):
        """Pattern D (SolaX): grid +=import, battery +=charge."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_power",
            battery_power="sensor.battery_power",
        )
        states = {
            "sensor.solar_power": _state(2000),
            "sensor.grid_power": _state(500),      # +500W import (opposite)
            "sensor.battery_power": _state(300),    # +300W charge (SEM match)
        }
        reader = _make_reader_with_states(hass, states, ed)
        reader._grid_sign_inverted = True
        reader._grid_sign_detected = True
        power = reader.read_power()
        power.calculate_derived()

        assert power.grid_import_power == 500
        assert power.battery_charge_power == 300
        assert power.home_consumption_power > 0


# ════════════════════════════════════════════
# Solar-only config (no grid)
# ════════════════════════════════════════════

class TestSolarOnly:
    """Test with solar configured but no grid sensor."""

    def test_solar_only_no_grid(self):
        """Solar only: grid_power should be 0, home = solar."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power=None,
            grid_import_energy=None,
            grid_export_energy=None,
            battery_power=None,
        )

        states = {
            "sensor.solar_power": _state(4000),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.solar_power == 4000
        assert power.grid_power == 0
        power.calculate_derived()
        assert power.home_consumption_power == 4000  # All solar → home


# ════════════════════════════════════════════
# Energy balance validation
# ════════════════════════════════════════════

class TestEnergyBalance:
    """Verify energy balance holds for all grid modes."""

    def test_balance_split_grid(self):
        """Split grid: solar + import = home + export + charge."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar",
            grid_import_power=None,
            grid_import_energy="sensor.import_total",
            grid_export_energy="sensor.export_total",
            battery_power="sensor.battery",
        )

        states = {
            "sensor.solar": _state(5000),
            "sensor.battery": _state(1000),  # Charging 1kW
            "sensor.mix_import_from_grid": _state(500, device_class="power"),
            "sensor.mix_export_to_grid": _state(0, device_class="power"),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Balance: solar + import + discharge = home + export + charge + EV
        energy_in = power.solar_power + power.grid_import_power + power.battery_discharge_power
        energy_out = power.home_consumption_power + power.grid_export_power + power.battery_charge_power + power.ev_power
        assert abs(energy_in - energy_out) < 1, f"Balance off: in={energy_in}, out={energy_out}"


# ════════════════════════════════════════════
# EV charger control pipeline
# ════════════════════════════════════════════

class TestChargerControlPipeline:
    """Test EV charger current control for all control patterns.

    Two methods: service call (KEBA, Easee, Zaptec) vs number entity
    (Wallbox, go-eCharger, ChargePoint, Heidelberg, OpenWB, OCPP, Ohme,
    Peblar, V2C, Blue Current, OpenEVSE, Alfen).
    Two power units: W (most) vs kW (KEBA, Easee, Wallbox, Ohme, Alfen).
    """

    @pytest.mark.asyncio
    async def test_service_control_keba(self):
        """KEBA: service call keba.set_current with 'current' param."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="KEBA",
            priority=1, min_current=6, max_current=32, phases=3, voltage=230,
            power_entity_id="sensor.keba_power",
            charger_service="keba.set_current",
            charger_service_entity_id="binary_sensor.keba_plug",
            current_entity_id=None,
        )
        await device._set_current(16)

        hass.services.async_call.assert_called_once()
        call = hass.services.async_call.call_args
        assert call[0][0] == "keba"
        assert call[0][1] == "set_current"
        assert call[0][2]["current"] == 16

    @pytest.mark.asyncio
    async def test_number_control_wallbox(self):
        """Wallbox: number.set_value on max current entity."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="Wallbox",
            priority=1, min_current=6, max_current=32, phases=3, voltage=230,
            power_entity_id="sensor.wallbox_power",
            charger_service=None,
            charger_service_entity_id=None,
            current_entity_id="number.wallbox_max_current",
        )
        await device._set_current(10)

        hass.services.async_call.assert_called_once()
        call = hass.services.async_call.call_args
        assert call[0][0] == "number"
        assert call[0][1] == "set_value"
        assert call[0][2]["value"] == 10

    @pytest.mark.asyncio
    async def test_service_with_custom_param(self):
        """Easee: service with custom param name 'dynamicChargerCurrent'."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="Easee",
            priority=1, min_current=6, max_current=32, phases=3, voltage=230,
            power_entity_id="sensor.easee_power",
            charger_service="easee.set_charger_dynamic_limit",
            charger_service_entity_id=None,
            current_entity_id=None,
        )
        device.service_param_name = "dynamicChargerCurrent"
        await device._set_current(20)

        call = hass.services.async_call.call_args
        assert call[0][2]["dynamicChargerCurrent"] == 20

    def test_ev_power_kw_conversion(self):
        """Charger reporting power in kW should be converted to W."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar",
            grid_import_power="sensor.grid",
        )

        # KEBA reports in kW
        states = {
            "sensor.solar": _state(6000),
            "sensor.grid": _state(-2000),
        }

        reader = _make_reader_with_states(hass, states, ed)

        # Simulate reading an EV power sensor in kW
        kw_state = _state(7.5, unit="kW", device_class="power")
        hass.states.get = lambda eid: kw_state if eid == "sensor.keba_power" else states.get(eid)

        val = reader._read_sensor("sensor.keba_power", "ev")
        assert val == 7500  # Converted from 7.5 kW to 7500 W

    def test_ev_power_w_no_conversion(self):
        """Charger reporting power in W should not be converted."""
        hass = MagicMock()
        reader = SensorReader(hass, {"update_interval": 10})

        w_state = _state(4500, unit="W", device_class="power")
        hass.states.get = lambda eid: w_state

        val = reader._read_sensor("sensor.wallbox_power", "ev")
        assert val == 4500  # Already in W

    @pytest.mark.asyncio
    async def test_number_entity_with_all_charger_brands(self):
        """All number-entity chargers use the same control path."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        brands = [
            ("Wallbox", "number.wallbox_max_current"),
            ("go-eCharger", "number.goe_amp_current"),
            ("ChargePoint", "number.chargepoint_amperage"),
            ("Heidelberg", "number.heidelberg_current_limit"),
            ("OpenWB", "number.openwb_chargepoint_current"),
            ("OCPP", "number.ocpp_max_current"),
            ("Ohme", "number.ohme_max_current"),
            ("Peblar", "number.peblar_charge_limit"),
            ("V2C Trydan", "number.v2c_intensity"),
            ("OpenEVSE", "number.openevse_max_current"),
            ("Alfen Eve", "number.alfen_max_current"),
            ("Blue Current", "number.bluecurrent_max_current"),
        ]

        for brand, entity in brands:
            hass = MagicMock()
            hass.services = MagicMock()
            hass.services.async_call = AsyncMock()

            device = CurrentControlDevice(
                hass=hass, device_id=f"ev_{brand.lower()}", name=brand,
                priority=1, min_current=6, max_current=32, phases=3, voltage=230,
                power_entity_id=f"sensor.{brand.lower()}_power",
                charger_service=None,
                charger_service_entity_id=None,
                current_entity_id=entity,
            )
            await device._set_current(12)

            assert hass.services.async_call.called, f"{brand} set_current failed"
            call = hass.services.async_call.call_args
            assert call[0][0] == "number", f"{brand} wrong domain: {call[0][0]}"
            assert call[0][1] == "set_value", f"{brand} wrong service: {call[0][1]}"
            assert call[0][2]["value"] == 12, f"{brand} wrong value: {call[0][2]}"


# ════════════════════════════════════════════
# Multi-grid power sensor aggregation
# ════════════════════════════════════════════

class TestMultiGridPipeline:
    """Test full pipeline with multiple grid power sensors.

    Some setups have multiple grid meters (e.g. commercial sites with
    per-phase meters, or dual feed-in points). The Energy Dashboard
    can configure multiple power entries — SEM must sum them.
    """

    def test_two_grid_meters_importing(self):
        """Two grid meters both importing — power is summed."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_meter1",
            grid_import_energy="sensor.grid_import_total",
            grid_export_energy="sensor.grid_export_total",
            battery_power=None,
            grid_power_list=[
                "sensor.grid_meter1",
                "sensor.grid_meter2",
            ],
        )

        states = {
            "sensor.solar_power": _state(3000),
            "sensor.grid_meter1": _state(-800),
            "sensor.grid_meter2": _state(-400),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Sum: -800 + -400 = -1200W importing
        assert power.grid_power == -1200
        assert power.grid_import_power == 1200
        assert power.grid_export_power == 0
        assert power.home_consumption_power == 4200  # 3000 + 1200

    def test_two_grid_meters_mixed_direction(self):
        """Two grid meters: one importing, one exporting — net summed."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_meter1",
            grid_import_energy="sensor.grid_import_total",
            grid_export_energy="sensor.grid_export_total",
            battery_power=None,
            grid_power_list=[
                "sensor.grid_meter1",
                "sensor.grid_meter2",
            ],
        )

        states = {
            "sensor.solar_power": _state(5000),
            "sensor.grid_meter1": _state(-1000),  # importing
            "sensor.grid_meter2": _state(400),     # exporting
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Net: -1000 + 400 = -600W importing
        assert power.grid_power == -600
        assert power.grid_import_power == 600
        assert power.grid_export_power == 0

    def test_three_phase_meters_exporting(self):
        """Three per-phase grid meters all exporting."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_l1",
            grid_import_energy="sensor.grid_import_total",
            grid_export_energy="sensor.grid_export_total",
            battery_power="sensor.battery_power",
            grid_power_list=[
                "sensor.grid_l1",
                "sensor.grid_l2",
                "sensor.grid_l3",
            ],
        )

        states = {
            "sensor.solar_power": _state(9000),
            "sensor.battery_power": _state(0),
            "sensor.grid_l1": _state(1000),   # export
            "sensor.grid_l2": _state(1500),   # export
            "sensor.grid_l3": _state(500),    # export
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Sum: 1000 + 1500 + 500 = 3000W exporting
        assert power.grid_power == 3000
        assert power.grid_export_power == 3000
        assert power.grid_import_power == 0
        assert power.home_consumption_power == 6000  # 9000 - 3000

    def test_multi_grid_energy_balance(self):
        """Full energy balance with multi-grid + multi-solar + multi-battery."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.inv1_power",
            grid_import_power="sensor.grid_meter1",
            grid_import_energy="sensor.grid_import_total",
            grid_export_energy="sensor.grid_export_total",
            battery_power="sensor.batt1_power",
            solar_power_list=[
                "sensor.inv1_power",
                "sensor.inv2_power",
            ],
            grid_power_list=[
                "sensor.grid_meter1",
                "sensor.grid_meter2",
            ],
            battery_power_list=[
                "sensor.batt1_power",
                "sensor.batt2_power",
            ],
        )

        states = {
            "sensor.inv1_power": _state(4000),
            "sensor.inv2_power": _state(3000),
            "sensor.grid_meter1": _state(500),     # export
            "sensor.grid_meter2": _state(300),     # export
            "sensor.batt1_power": _state(1000),    # charging
            "sensor.batt2_power": _state(500),     # charging
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()
        power.calculate_derived()

        # Solar: 4000 + 3000 = 7000
        assert power.solar_power == 7000
        # Grid: 500 + 300 = 800 export
        assert power.grid_power == 800
        assert power.grid_export_power == 800
        # Battery: 1000 + 500 = 1500 charging
        assert power.battery_power == 1500
        assert power.battery_charge_power == 1500
        # Home: 7000 - 800 - 1500 = 4700
        assert power.home_consumption_power == 4700

        # Energy balance must hold
        energy_in = power.solar_power + power.grid_import_power + power.battery_discharge_power
        energy_out = power.home_consumption_power + power.grid_export_power + power.battery_charge_power + power.ev_power
        assert abs(energy_in - energy_out) < 1, f"Balance off: in={energy_in}, out={energy_out}"

    def test_single_grid_sensor_backward_compat(self):
        """Single grid sensor in list — same behavior as before."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar_power",
            grid_import_power="sensor.grid_power",
            battery_power=None,
            grid_power_list=["sensor.grid_power"],
        )

        states = {
            "sensor.solar_power": _state(5000),
            "sensor.grid_power": _state(-750),
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        # Single sensor in list (len==1) falls through to scalar ed.grid_import_power path
        assert power.grid_power == -750


# ════════════════════════════════════════════
# Issue #166: startup-race regression tests
# ════════════════════════════════════════════

class TestSplitGridStartupRace:
    """Regressions for the v1.5.x re-report of issue #166.

    The v1.4.6-beta.2 same-device filter only works when the grid energy
    sensor's device is resolvable. If DSMR is still loading at first refresh,
    _get_device_for_entity returns None and the any-device fallback picks the
    wrong sensor (e.g. heat pump). These tests assert the low-confidence pick
    is not permanently cached and that invalidation re-runs discovery.
    """

    def _meter_registry_mock(self):
        """Registry mock where meter sensors resolve to meter_device, others to other."""
        from unittest.mock import MagicMock as _MM
        registry = _MM()

        def _get(entity_id):
            entry = _MM()
            if "electricity_meter" in entity_id:
                entry.device_id = "meter_device"
            elif "heat_pump" in entity_id:
                entry.device_id = "heatpump_device"
            else:
                entry.device_id = None
            return entry

        registry.async_get = _get
        return registry

    def test_lowconf_pick_is_not_permanently_cached(self):
        """Any-device pick must be re-evaluated each cycle so a late meter wins."""
        from unittest.mock import patch, MagicMock as _MM
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power=None,
        )

        # Phase 1: DSMR not loaded yet — grid energy sensor has no device entry,
        # only a heat pump's power_consumption is visible.
        phase1_states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.heat_pump_power_consumption": _state(2000, device_class="power"),
        }

        phase1_registry = _MM()
        phase1_registry.async_get = lambda eid: None  # nothing resolvable yet

        reader = _make_reader_with_states(hass, phase1_states, ed)

        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=phase1_registry,
        ):
            reader.read_power()

        # Wrong pick — heat pump matched via any-device fallback
        assert reader._split_grid_discovery["import"] == "sensor.heat_pump_power_consumption"
        assert reader._split_grid_discovery["confidence"] == "any-device"

        # Phase 2: DSMR is now registered. Without re-discovery the wrong pick
        # would persist. With confidence-tiered cache the read re-runs discovery
        # and the same-device meter wins.
        phase2_states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.heat_pump_power_consumption": _state(2000, device_class="power"),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        # Re-mock hass with phase2 states (preserves the SensorReader instance)
        def _get2(entity_id):
            return phase2_states.get(entity_id)

        def _async_all2(domain=None):
            out = []
            for eid, st in phase2_states.items():
                m = _MM()
                m.entity_id = eid
                m.state = st.state
                m.attributes = st.attributes
                if domain is None or eid.startswith(f"{domain}."):
                    out.append(m)
            return out

        hass.states.get = _get2
        hass.states.async_all = _async_all2

        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=self._meter_registry_mock(),
        ):
            reader.read_power()

        assert reader._split_grid_discovery["import"] == "sensor.electricity_meter_power_consumption"
        assert reader._split_grid_discovery["export"] == "sensor.electricity_meter_power_production"
        assert reader._split_grid_discovery["confidence"] == "same-device"

    def test_same_device_pick_is_sticky(self):
        """Once same-device confidence is reached, subsequent reads reuse it."""
        from unittest.mock import patch
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power=None,
        )
        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        reader = _make_reader_with_states(hass, states, ed)

        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=self._meter_registry_mock(),
        ):
            reader.read_power()
            # If we now break the registry, a sticky same-device cache should
            # keep the previous pick (discovery must NOT re-run).
            reader.hass = hass  # keep states
            reader.read_power()

        assert reader._split_grid_discovery["confidence"] == "same-device"
        assert reader._split_grid_discovery["import"] == "sensor.electricity_meter_power_consumption"

    def test_invalidate_split_grid_cache_forces_rediscovery(self):
        """invalidate_split_grid_cache() resets the dict so next read re-runs discovery."""
        from unittest.mock import patch
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power=None,
        )
        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        reader = _make_reader_with_states(hass, states, ed)

        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=self._meter_registry_mock(),
        ):
            reader.read_power()
            assert reader._split_grid_discovery["confidence"] == "same-device"

            reader.invalidate_split_grid_cache()
            assert reader._split_grid_discovery["confidence"] is None
            assert reader._split_grid_discovery["import"] is None

            # Next read re-discovers
            reader.read_power()
            assert reader._split_grid_discovery["confidence"] == "same-device"
            assert reader._split_grid_discovery["import"] == "sensor.electricity_meter_power_consumption"

    def _make_coordinator_for_sign_flip(self, confidence="any-device"):
        """Create a minimal coordinator with mocked sensor reader for sign-flip tests."""
        from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator

        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._sensor_reader = MagicMock()
        coord._sensor_reader._split_grid_discovery = {
            "import": "sensor.wrong_power_consumption",
            "export": None,
            "confidence": confidence,
            "warned": False,
        }
        coord._sensor_reader._grid_sign_inverted = False
        coord._sensor_reader._grid_sign_detected = False
        coord._negative_balance_count = 0
        coord._sign_flip_suppression_count = 0
        return coord

    def _make_negative_power(self):
        """PowerReadings with a deeply negative balance to trigger sign flip.

        Balance = energy_in - energy_out
               = (solar + grid_import + batt_discharge) - (ev + grid_export + batt_charge)
               = (5000 + 0 + 0) - (0 + 8000 + 0) = -3000  (< -500 → triggers flip)
        """
        power = PowerReadings()
        power.solar_power = 5000.0
        power.grid_power = 3000.0  # non-zero so the outer guard passes
        power.grid_import_power = 0.0
        power.grid_export_power = 8000.0
        power.battery_power = 0.0
        power.battery_charge_power = 0.0
        power.battery_discharge_power = 0.0
        power.ev_power = 0.0
        return power

    def test_self_healing_flip_skipped_for_lowconf_split(self):
        """Sign flip must NOT fire when split-grid confidence is any-device."""
        coord = self._make_coordinator_for_sign_flip(confidence="any-device")
        power = self._make_negative_power()

        # Simulate 18 negative balance cycles (3 minutes)
        for _ in range(18):
            coord._check_sign_flip(power)

        # Should be suppressed — no flip
        assert coord._sensor_reader._grid_sign_inverted is False
        assert coord._sign_flip_suppression_count == 1

    def test_self_healing_flip_fires_for_same_device(self):
        """Sign flip fires normally when confidence is same-device."""
        coord = self._make_coordinator_for_sign_flip(confidence="same-device")
        power = self._make_negative_power()

        for _ in range(18):
            coord._check_sign_flip(power)

        assert coord._sensor_reader._grid_sign_inverted is True

    def test_suppression_escape_hatch_after_3_cycles(self):
        """After 3 suppression cycles (~9 min), flip fires anyway."""
        coord = self._make_coordinator_for_sign_flip(confidence="any-device")
        power = self._make_negative_power()

        # 3 suppression cycles × 18 ticks each = 54 ticks
        for _ in range(54):
            coord._check_sign_flip(power)

        # 3 suppressions exhausted, but flip hasn't fired yet (counter reset each time)
        assert coord._sign_flip_suppression_count == 3
        assert coord._sensor_reader._grid_sign_inverted is False

        # Next 18 ticks should trigger the actual flip (suppression limit reached)
        for _ in range(18):
            coord._check_sign_flip(power)

        assert coord._sensor_reader._grid_sign_inverted is True
        assert coord._sign_flip_suppression_count == 0

    def test_confidence_upgrade_resets_suppression_counter(self):
        """Upgrading to same-device after suppression cycles allows immediate flip."""
        coord = self._make_coordinator_for_sign_flip(confidence="any-device")
        power = self._make_negative_power()

        # One suppression cycle
        for _ in range(18):
            coord._check_sign_flip(power)
        assert coord._sign_flip_suppression_count == 1
        assert coord._sensor_reader._grid_sign_inverted is False

        # Upgrade confidence
        coord._sensor_reader._split_grid_discovery["confidence"] = "same-device"

        # Next 18 ticks should flip (same-device skips suppression)
        for _ in range(18):
            coord._check_sign_flip(power)
        assert coord._sensor_reader._grid_sign_inverted is True


class TestSplitGridCombinedGuard:
    """Combined-grid users should not get spurious _on_new_sensor refreshes."""

    def test_combined_grid_user_not_in_split_grid_mode(self):
        """Reader with combined grid_import_power never sets _uses_split_grid."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.inverter_power",
            grid_import_power="sensor.grid_power",
            battery_power="sensor.battery_power",
        )
        states = {
            "sensor.inverter_power": _state(5000),
            "sensor.grid_power": _state(-2000),
            "sensor.battery_power": _state(0),
        }
        reader = _make_reader_with_states(hass, states, ed)
        reader.read_power()

        assert reader._uses_split_grid is False

    def test_split_grid_user_sets_flag(self):
        """Reader entering split-grid discovery sets _uses_split_grid."""
        from unittest.mock import patch
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power=None,
        )
        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        reader = _make_reader_with_states(hass, states, ed)

        registry = MagicMock()
        registry.async_get = lambda eid: None

        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry,
        ):
            reader.read_power()

        assert reader._uses_split_grid is True


class TestSplitGridDiagnostics:
    """Diagnostics output includes split-grid discovery state."""

    def test_diagnostics_includes_split_grid_discovery(self):
        """The split_grid_discovery dict is surfaced in diagnostics."""
        from unittest.mock import patch
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power=None,
        )
        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_power_production": _state(3000, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        reader = _make_reader_with_states(hass, states, ed)

        registry = MagicMock()
        registry.async_get = lambda eid: None

        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry,
        ):
            reader.read_power()

        disc = reader._split_grid_discovery
        assert "import" in disc
        assert "export" in disc
        assert "confidence" in disc
        assert disc["confidence"] in ("same-device", "any-device")
        assert disc["import"] is not None


# ════════════════════════════════════════════
# #461: split-grid pick stability — any-device picks must not flip
# while the held picks still resolve
# ════════════════════════════════════════════

class TestSplitGridPickStability:
    """Any-device discovery re-runs while there's no same-device lock, but
    fresh picks are only ADOPTED when there's no working pick yet, the new
    match is a same-device upgrade, or a held pick went unavailable.
    Unconditional adoption let a flicker in HA's state-list iteration order
    swap import/export mid-run — inverting the computed grid_power sign
    (#461, Growatt 'sometimes works, sometimes inverted')."""

    def _reader(self):
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.mix_import_from_grid_today",
            grid_export_energy="sensor.mix_export_to_grid_today",
            battery_power=None,
        )
        states = {
            "sensor.growatt_solar_power": _state(3000),
            "sensor.mix_import_from_grid": _state(500, device_class="power"),
            "sensor.mix_export_to_grid": _state(0, device_class="power"),
        }
        reader = _make_reader_with_states(hass, states, ed)
        return reader, states

    def test_held_picks_survive_flipped_rediscovery(self):
        """A re-discovery returning swapped roles must NOT be adopted."""
        reader, states = self._reader()
        reader.read_power()
        disc = reader._split_grid_discovery
        first = (disc["import"], disc["export"])
        assert disc["import"] is not None
        disc["confidence"] = "any-device"  # ensure the re-discovery branch runs

        with patch.object(
            reader, "_discover_split_grid_power",
            return_value=(
                "sensor.mix_export_to_grid", "sensor.mix_import_from_grid",
                "any-device",
            ),
        ):
            reader.read_power()

        assert (disc["import"], disc["export"]) == first, (
            "#461 regression: a state-list flicker swapped the split-grid "
            "import/export picks mid-run even though the held picks still "
            "resolved — this inverts the computed grid sign."
        )

    def test_same_device_upgrade_is_adopted(self):
        """A same-device match is deterministic — upgrade is allowed."""
        reader, states = self._reader()
        reader.read_power()
        disc = reader._split_grid_discovery
        disc["confidence"] = "any-device"
        states["sensor.meter_import"] = _state(400, device_class="power")
        states["sensor.meter_export"] = _state(0, device_class="power")

        with patch.object(
            reader, "_discover_split_grid_power",
            return_value=("sensor.meter_import", "sensor.meter_export", "same-device"),
        ):
            reader.read_power()

        assert disc["import"] == "sensor.meter_import"
        assert disc["confidence"] == "same-device"

    def test_unavailable_pick_reopens_adoption(self):
        """When a held pick goes unavailable, re-discovery may adopt anew."""
        reader, states = self._reader()
        reader.read_power()
        disc = reader._split_grid_discovery
        disc["confidence"] = "any-device"
        states["sensor.mix_import_from_grid"].state = "unavailable"
        states["sensor.new_import"] = _state(250, device_class="power")
        states["sensor.new_export"] = _state(0, device_class="power")

        with patch.object(
            reader, "_discover_split_grid_power",
            return_value=("sensor.new_import", "sensor.new_export", "any-device"),
        ):
            reader.read_power()

        assert disc["import"] == "sensor.new_import"

    def test_late_loading_meter_still_discovered(self):
        """#166 contract preserved: with no pick yet, every cycle re-discovers."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.mix_import_from_grid_today",
            grid_export_energy="sensor.mix_export_to_grid_today",
            battery_power=None,
        )
        states = {"sensor.growatt_solar_power": _state(3000)}
        reader = _make_reader_with_states(hass, states, ed)

        reader.read_power()
        assert reader._split_grid_discovery["import"] is None

        # Meter loads late — next cycle must pick it up
        states["sensor.mix_import_from_grid"] = _state(500, device_class="power")
        states["sensor.mix_export_to_grid"] = _state(0, device_class="power")
        reader.read_power()
        assert reader._split_grid_discovery["import"] == "sensor.mix_import_from_grid"


# ════════════════════════════════════════════
# #461 follow-up: manual grid override validation + observe-only sign audit
# ════════════════════════════════════════════

class TestManualGridAudit:
    """When grid_import/export_power_entity are set explicitly, all sign
    auto-detection is bypassed — a swapped / one-sided / wrong-kind config
    yields a statically inverted grid with zero feedback (RienduPre's #461
    shape: explicit entities configured, no discovery logs, grid shows
    export while importing). The audit compares the manual-computed sign
    against the Energy Dashboard counters and warns on contradiction."""

    def _reader(self, manual_import, manual_export, states):
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar",
            grid_import_power=None,
            grid_import_energy="sensor.grid_import_kwh",
            grid_export_energy="sensor.grid_export_kwh",
            battery_power=None,
        )
        extra = {}
        if manual_import:
            extra["grid_import_power_entity"] = manual_import
        if manual_export:
            extra["grid_export_power_entity"] = manual_export
        reader = _make_reader_with_states(hass, states, ed, extra_config=extra)
        return reader

    def test_swapped_manual_entities_flag_mismatch(self, caplog):
        """Physically importing 1500 W with the two fields swapped → SEM
        computes +1500 (export) while the import counter grows. Five
        consecutive contradictions set the mismatch flag + WARNING."""
        states = {
            "sensor.solar": _state(0),
            "sensor.real_import": _state(1500, device_class="power"),
            "sensor.real_export": _state(0, device_class="power"),
            "sensor.grid_import_kwh": _state(100.0, unit="kWh"),
            "sensor.grid_export_kwh": _state(50.0, unit="kWh"),
        }
        # User swapped the roles: import field → the export meter, etc.
        reader = self._reader("sensor.real_export", "sensor.real_import", states)

        for cycle in range(7):
            states["sensor.grid_import_kwh"] = _state(100.0 + 0.1 * cycle, unit="kWh")
            power = reader.read_power()
            assert power.grid_power == 1500  # statically inverted

        assert reader._manual_grid_mismatch is True
        assert "SWAPPED" in caplog.text
        assert "sensor.real_export" in caplog.text

    def test_correct_manual_entities_stay_clean(self):
        states = {
            "sensor.solar": _state(0),
            "sensor.real_import": _state(1500, device_class="power"),
            "sensor.real_export": _state(0, device_class="power"),
            "sensor.grid_import_kwh": _state(100.0, unit="kWh"),
            "sensor.grid_export_kwh": _state(50.0, unit="kWh"),
        }
        reader = self._reader("sensor.real_import", "sensor.real_export", states)

        for cycle in range(7):
            states["sensor.grid_import_kwh"] = _state(100.0 + 0.1 * cycle, unit="kWh")
            power = reader.read_power()
            assert power.grid_power == -1500  # SEM convention: negative = import

        assert reader._manual_grid_mismatch is False
        assert reader._manual_grid_mismatch_votes == 0

    def test_mismatch_clears_when_agreement_returns(self):
        """After the user fixes the swap (counters and manual sign agree
        again), the flag clears."""
        states = {
            "sensor.solar": _state(0),
            "sensor.real_import": _state(1500, device_class="power"),
            "sensor.real_export": _state(0, device_class="power"),
            "sensor.grid_import_kwh": _state(100.0, unit="kWh"),
            "sensor.grid_export_kwh": _state(50.0, unit="kWh"),
        }
        reader = self._reader("sensor.real_export", "sensor.real_import", states)
        for cycle in range(7):
            states["sensor.grid_import_kwh"] = _state(100.0 + 0.1 * cycle, unit="kWh")
            reader.read_power()
        assert reader._manual_grid_mismatch is True

        # Physical flow reverses to genuine export: the export counter now
        # grows, matching the (still-positive) manual sign — agreement on
        # the next judged cycle clears the flag.
        for cycle in range(2):
            states["sensor.grid_export_kwh"] = _state(50.0 + 0.1 * (cycle + 1), unit="kWh")
            reader.read_power()
        assert reader._manual_grid_mismatch is False

    def test_energy_counter_in_power_field_warns(self, caplog):
        """A kWh counter configured as a manual POWER entity is flagged."""
        states = {
            "sensor.solar": _state(0),
            "sensor.import_counter": _state(5432.1, unit="kWh", device_class="energy"),
            "sensor.real_export": _state(0, device_class="power"),
            "sensor.grid_import_kwh": _state(100.0, unit="kWh"),
            "sensor.grid_export_kwh": _state(50.0, unit="kWh"),
        }
        reader = self._reader("sensor.import_counter", "sensor.real_export", states)
        reader.read_power()
        assert "ENERGY" in caplog.text
        assert "sensor.import_counter" in caplog.text

    def test_one_sided_manual_config_warns(self, caplog):
        """Only one manual entity while both flow counters exist → the
        missing side reads a hard 0 W and that direction can never show."""
        states = {
            "sensor.solar": _state(0),
            "sensor.real_export": _state(800, device_class="power"),
            "sensor.grid_import_kwh": _state(100.0, unit="kWh"),
            "sensor.grid_export_kwh": _state(50.0, unit="kWh"),
        }
        reader = self._reader(None, "sensor.real_export", states)
        power = reader.read_power()
        assert power.grid_power == 800  # permanently one-signed
        assert "Only one manual grid power entity" in caplog.text

    def test_dual_tariff_counters_are_summed(self, caplog):
        """NL DSMR meters split each direction into tarief 1/2 counters that
        can move in different hours. The audit sums the LISTS, so a swap is
        still caught when only the tarief-2 counter is moving."""
        states = {
            "sensor.solar": _state(0),
            "sensor.real_import": _state(1500, device_class="power"),
            "sensor.real_export": _state(0, device_class="power"),
            "sensor.import_t1": _state(100.0, unit="kWh"),
            "sensor.import_t2": _state(200.0, unit="kWh"),
            "sensor.export_t1": _state(50.0, unit="kWh"),
            "sensor.export_t2": _state(30.0, unit="kWh"),
        }
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar",
            grid_import_power=None,
            grid_import_energy="sensor.import_t1",
            grid_export_energy="sensor.export_t1",
            battery_power=None,
        )
        ed.grid_import_energy_list = ["sensor.import_t1", "sensor.import_t2"]
        ed.grid_export_energy_list = ["sensor.export_t1", "sensor.export_t2"]
        # Swapped manual fields, as in the two-counter base case.
        reader = _make_reader_with_states(
            hass, states, ed,
            extra_config={
                "grid_import_power_entity": "sensor.real_export",
                "grid_export_power_entity": "sensor.real_import",
            },
        )

        for cycle in range(7):
            # Only the tarief-2 import counter moves (peak hours).
            states["sensor.import_t2"] = _state(200.0 + 0.1 * cycle, unit="kWh")
            reader.read_power()

        assert reader._manual_grid_mismatch is True


# ════════════════════════════════════════════
# #485 pre-stable review batch (H2/H3/H4/H6)
# ════════════════════════════════════════════

class TestLateExportAdoption:
    """#485 H2: a late-loading export sensor completes a one-sided pick."""

    def _dsmr_setup(self, states):
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.growatt_solar_power",
            grid_import_power=None,
            grid_import_energy="sensor.electricity_meter_energy_consumption_tariff_1",
            grid_export_energy="sensor.electricity_meter_energy_production_tariff_1",
            battery_power="sensor.sessy_power",
        )
        reader = _make_reader_with_states(hass, states, ed)
        return reader, states

    def test_export_sensor_appearing_later_is_adopted(self):
        states = {
            "sensor.growatt_solar_power": _state(500),
            "sensor.sessy_power": _state(0),
            # Only the consumption (import) side has loaded so far.
            "sensor.electricity_meter_power_consumption": _state(1500, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        reader, states = self._dsmr_setup(states)
        reader.read_power()
        disc = reader._split_grid_discovery
        assert disc["import"] == "sensor.electricity_meter_power_consumption"
        assert disc["export"] is None
        held_import = disc["import"]

        # The production (export) sensor loads on a later cycle. The
        # one-sided re-scan runs at ~6-cycle cadence, so allow a few
        # cycles for the pickup.
        states["sensor.electricity_meter_power_production"] = _state(
            0, device_class="power",
        )
        for _ in range(7):
            reader.read_power()
            if disc["export"]:
                break
        assert disc["export"] == "sensor.electricity_meter_power_production"
        # The held import pick must NOT be re-rolled by the completion.
        assert disc["import"] == held_import

    def test_completed_pair_computes_grid_power(self):
        states = {
            "sensor.growatt_solar_power": _state(5000),
            "sensor.sessy_power": _state(0),
            "sensor.electricity_meter_power_consumption": _state(0, device_class="power"),
            "sensor.electricity_meter_energy_consumption_tariff_1": _state(150, "kWh"),
            "sensor.electricity_meter_energy_production_tariff_1": _state(200, "kWh"),
        }
        reader, states = self._dsmr_setup(states)
        reader.read_power()

        states["sensor.electricity_meter_power_production"] = _state(
            2000, device_class="power",
        )
        power = None
        for _ in range(7):
            power = reader.read_power()
            if reader._split_grid_discovery["export"]:
                power = reader.read_power()
                break
        assert power.grid_power == 2000  # export visible after completion


class TestSplitGridScanThrottle:
    """#485 H3: held healthy picks throttle the full sensor scan."""

    def _reader_with_picks(self, imp="sensor.imp", exp="sensor.exp"):
        hass = MagicMock()
        states = {
            imp: _state(100, device_class="power"),
            exp: _state(0, device_class="power"),
        }
        hass.states.get = lambda eid: states.get(eid)
        reader = SensorReader(hass, {"update_interval": 10})
        reader._split_grid_discovery.update(
            {"import": imp, "export": exp, "confidence": "any-device"},
        )
        return reader, states

    def test_two_sided_healthy_picks_scan_periodically(self):
        reader, _ = self._reader_with_picks()
        disc = reader._split_grid_discovery
        assert reader._split_grid_scan_due(disc) is True  # first call seeds
        for _ in range(reader._SPLIT_GRID_UPGRADE_SCAN_CYCLES - 1):
            assert reader._split_grid_scan_due(disc) is False
        assert reader._split_grid_scan_due(disc) is True  # periodic upgrade

    def test_one_sided_pick_scans_on_short_cadence(self):
        reader, _ = self._reader_with_picks()
        disc = reader._split_grid_discovery
        disc["export"] = None
        assert reader._split_grid_scan_due(disc) is True  # seeds countdown
        # Throttled, but on a much shorter cadence than the two-sided
        # upgrade scan — the missing side should be found within ~1 min.
        due_within = [reader._split_grid_scan_due(disc) for _ in range(6)]
        assert any(due_within)

    def test_empty_picks_scan_every_cycle(self):
        reader, _ = self._reader_with_picks()
        disc = reader._split_grid_discovery
        disc["import"] = None
        disc["export"] = None
        assert reader._split_grid_scan_due(disc) is True
        assert reader._split_grid_scan_due(disc) is True

    def test_unavailable_held_pick_scans_immediately(self):
        reader, states = self._reader_with_picks()
        disc = reader._split_grid_discovery
        reader._split_grid_scan_due(disc)  # seed countdown
        states["sensor.imp"] = _state("unavailable")
        states["sensor.imp"].state = "unavailable"
        assert reader._split_grid_scan_due(disc) is True


class TestDualTariffAutoSignVote:
    """#485 H4: the auto sign vote sums dual-tariff counter lists."""

    def _reader(self):
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            grid_import_energy="sensor.t1_consumption",
            grid_export_energy="sensor.t_production",
        )
        # Dutch dual-tariff: two import counters, one production.
        ed.grid_import_energy_list = [
            "sensor.t1_consumption", "sensor.t2_consumption",
        ]
        ed.grid_export_energy_list = ["sensor.t_production"]
        states = {}
        reader = _make_reader_with_states(hass, states, ed)
        return reader, states

    def test_other_tariff_counter_still_votes(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        reader, states = self._reader()

        def set_counters(t1, t2, prod):
            states["sensor.t1_consumption"] = _state(t1, "kWh")
            states["sensor.t2_consumption"] = _state(t2, "kWh")
            states["sensor.t_production"] = _state(prod, "kWh")

        # Tariff 1 counter is FROZEN (other tariff's hours); only
        # tariff 2 moves. Pre-fix the vote read t1 alone → blind.
        set_counters(150.0, 80.0, 200.0)
        reader._detect_grid_sign(PowerReadings(grid_power=800.0))  # baseline
        for step in range(1, 4):
            set_counters(150.0, 80.0 + step * 0.1, 200.0)
            result = reader._detect_grid_sign(PowerReadings(grid_power=800.0))

        # Import grows while power is positive → HA convention → negate.
        assert reader._grid_sign_detected is True
        assert result is True


class TestDeterministicDiscoveryOrder:
    """#485 H6: any-device picks are deterministic across state order."""

    def test_alphabetical_first_match_wins_regardless_of_insertion(self):
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power=None,
            grid_import_power=None,
            grid_import_energy="sensor.meter_energy",
            grid_export_energy="sensor.meter_energy_out",
            battery_power=None,
        )
        # Two import-pattern candidates inserted Z-first: an unsorted
        # scan picks Z (insertion order); the sorted scan must pick A.
        states = {
            "sensor.z_grid_import": _state(100, device_class="power"),
            "sensor.a_grid_import": _state(100, device_class="power"),
            "sensor.meter_energy": _state(150, "kWh"),
            "sensor.meter_energy_out": _state(20, "kWh"),
        }
        reader = _make_reader_with_states(hass, states, ed)
        reader._get_device_for_entity = lambda eid: None
        imp, exp, conf = reader._discover_split_grid_power(ed)
        assert imp == "sensor.a_grid_import"
