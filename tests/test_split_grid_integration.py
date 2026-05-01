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
        reader._battery_sign_inverted = True
        reader._grid_sign_detected = True
        reader._battery_sign_detected = True
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
        reader._battery_sign_inverted = True
        reader._battery_sign_detected = True
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
