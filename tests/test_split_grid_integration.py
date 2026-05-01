"""Integration tests for split grid power sensor pipeline.

Tests the full chain that the Growatt issue (#129) exposed:
  Energy Dashboard config (no grid power) → SensorReader → split discovery →
  grid_power calculation → calculate_derived() → correct import/export

These tests verify that the components work together, not just in isolation.
"""
import pytest
from unittest.mock import MagicMock, patch

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
):
    """Create a mock Energy Dashboard config."""
    ed = MagicMock()
    ed.solar_power = solar_power
    ed.solar_power_list = [solar_power] if solar_power else []
    ed.grid_import_power = grid_import_power
    ed.grid_power_list = [grid_import_power] if grid_import_power else []
    ed.grid_import_energy = grid_import_energy
    ed.grid_export_energy = grid_export_energy
    ed.grid_import_energy_list = [grid_import_energy] if grid_import_energy else []
    ed.grid_export_energy_list = [grid_export_energy] if grid_export_energy else []
    ed.battery_power = battery_power
    ed.battery_power_list = [battery_power] if battery_power else []
    ed.battery_charge_energy = battery_charge_energy
    ed.battery_discharge_energy = battery_discharge_energy
    ed.ev_power = None
    ed.has_solar = bool(solar_power)
    ed.has_grid = bool(grid_import_energy or grid_import_power)
    ed.has_battery = bool(battery_power)
    ed.has_ev = False
    return ed


def _make_reader_with_states(hass, states_dict, ed_config):
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

    hass.states.get = mock_get
    hass.states.async_all = mock_async_all

    reader = SensorReader(hass, {"update_interval": 10})
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
        assert reader._split_grid_import_power is not None

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
# Combined grid sensor (Huawei, SolarEdge, etc.)
# ════════════════════════════════════════════

class TestCombinedGridSensor:
    """Verify combined grid sensor pipeline still works correctly."""

    def test_huawei_exporting(self):
        """Huawei: positive=export (SEM convention match, no correction)."""
        hass = MagicMock()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.inverter_power",
            grid_import_power="sensor.power_meter_wirkleistung",
            battery_power="sensor.battery_1_power",
        )

        states = {
            "sensor.inverter_power": _state(6000),
            "sensor.power_meter_wirkleistung": _state(3000),  # Positive = export
            "sensor.battery_1_power": _state(1000),  # Positive = charge
        }

        reader = _make_reader_with_states(hass, states, ed)
        power = reader.read_power()

        assert power.grid_power == 3000
        power.calculate_derived()
        assert power.grid_export_power == 3000
        assert power.grid_import_power == 0


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
