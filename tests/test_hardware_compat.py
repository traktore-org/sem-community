"""Hardware compatibility tests — mock real integration entities.

Tests SEM's auto-detection, sensor reading, and charger control against
exact entity IDs, device classes, and state values from real integrations.
Each fixture uses values from the actual integration source code.

Covers:
- 8 EV chargers: KEBA, Easee, Wallbox, go-eCharger, Zaptec, ChargePoint, Heidelberg, OpenWB
- 5 inverters: Huawei Solar, GoodWe, Fronius, Enphase, SolarEdge
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.hardware_detection import (
    discover_ev_charger_from_registry,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


# ════════════════════════════════════════════
# Mock Helpers
# ════════════════════════════════════════════

def _entity(entity_id, platform, device_class=None, device_id=None, disabled=False):
    """Create a mock entity registry entry matching a real integration."""
    e = MagicMock()
    e.entity_id = entity_id
    e.platform = platform
    e.original_device_class = device_class
    e.disabled_by = "user" if disabled else None
    e.device_id = device_id or f"dev_{platform}_001"
    return e


def _state(value, unit=None, device_class=None, attrs=None):
    """Create a mock HA state object."""
    s = MagicMock()
    s.state = str(value)
    s.attributes = attrs or {}
    if unit:
        s.attributes["unit_of_measurement"] = unit
    if device_class:
        s.attributes["device_class"] = device_class
    return s


def _mock_registry(entities):
    """Create a mock entity registry with given entries."""
    reg = MagicMock()
    reg.entities = MagicMock()
    reg.entities.values.return_value = entities
    return reg


# ════════════════════════════════════════════
# EV Charger Discovery Tests
# ════════════════════════════════════════════

class TestKEBADiscovery:
    """KEBA KeContact P30 — core HA integration."""

    def _entities(self):
        return [
            _entity("binary_sensor.keba_kecontact_p30_plug", "keba", "plug"),
            _entity("binary_sensor.keba_kecontact_p30_charging_state", "keba", "power"),
            _entity("sensor.keba_kecontact_p30_charging_power", "keba", "power"),
            _entity("sensor.keba_kecontact_p30_max_current", "keba", "current"),
            _entity("sensor.keba_kecontact_p30_session_energy", "keba", "energy"),
            _entity("sensor.keba_kecontact_p30_total_energy", "keba", "energy"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_keba_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_connected_sensor") == "binary_sensor.keba_kecontact_p30_plug"
        assert result.get("ev_charging_sensor") == "binary_sensor.keba_kecontact_p30_charging_state"
        assert result.get("ev_charging_power_sensor") == "sensor.keba_kecontact_p30_charging_power"
        assert result.get("ev_charger_service") == "keba.set_current"
        assert result.get("ev_service_param_name") == "current"

    def test_keba_power_kw_conversion(self):
        """KEBA reports power in kW — SEM must convert to W."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(3.5, unit="kW") if "power" in eid else None
        reader = SensorReader(hass, {"ev_power_sensor": "sensor.keba_kecontact_p30_charging_power"})
        value = reader._read_sensor("sensor.keba_kecontact_p30_charging_power", "ev")
        assert value == 3500.0  # 3.5 kW → 3500 W

    def test_keba_binary_sensor_status(self):
        """KEBA uses binary_sensor with on/off."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state("on")
        reader = SensorReader(hass, {})
        assert reader._read_binary_sensor("binary_sensor.keba_kecontact_p30_plug", "ev_plug") is True
        hass.states.get = lambda eid: _state("off")
        assert reader._read_binary_sensor("binary_sensor.keba_kecontact_p30_plug", "ev_plug") is False


class TestEaseeDiscovery:
    """Easee Home — HACS integration (nordicopen/easee_hass)."""

    def _entities(self):
        return [
            _entity("sensor.easee_home_status", "easee", None, "dev_easee_001"),
            _entity("sensor.easee_home_power", "easee", "power", "dev_easee_001"),
            _entity("sensor.easee_home_lifetime_energy", "easee", "energy", "dev_easee_001"),
            _entity("sensor.easee_home_session_energy", "easee", "energy", "dev_easee_001"),
            _entity("sensor.easee_home_current", "easee", "current", "dev_easee_001"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_easee_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_connected_sensor") == "sensor.easee_home_status"
        assert result.get("ev_charging_sensor") == "sensor.easee_home_status"
        assert result.get("ev_charging_power_sensor") == "sensor.easee_home_power"
        assert result.get("ev_charger_service") == "easee.set_charger_dynamic_limit"
        assert result.get("ev_service_device_id") == "dev_easee_001"
        assert result.get("ev_start_service") == "easee.action_command"

    def test_easee_status_connected(self):
        """Easee uses sensor with status strings — 'ready_to_charge' = connected."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state("ready_to_charge")
        reader = SensorReader(hass, {})
        assert reader._read_binary_sensor("sensor.easee_home_status", "ev_plug") is True
        assert reader._read_binary_sensor("sensor.easee_home_status", "ev_charging") is False

    def test_easee_status_charging(self):
        """Easee status 'charging' = both connected and charging."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state("charging")
        reader = SensorReader(hass, {})
        assert reader._read_binary_sensor("sensor.easee_home_status", "ev_plug") is True
        assert reader._read_binary_sensor("sensor.easee_home_status", "ev_charging") is True

    def test_easee_status_disconnected(self):
        """Easee status 'disconnected' = not connected."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state("disconnected")
        reader = SensorReader(hass, {})
        assert reader._read_binary_sensor("sensor.easee_home_status", "ev_plug") is False
        assert reader._read_binary_sensor("sensor.easee_home_status", "ev_charging") is False

    def test_easee_power_kw(self):
        """Easee reports power in kW — must convert to W."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(3.5, unit="kW")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.easee_home_power", "ev") == 3500.0


class TestWallboxDiscovery:
    """Wallbox Pulsar Plus — core HA integration."""

    def _entities(self):
        return [
            _entity("binary_sensor.wallbox_pulsar_plus_plug_connected", "wallbox"),
            _entity("binary_sensor.wallbox_pulsar_plus_charging", "wallbox"),
            _entity("sensor.wallbox_pulsar_plus_charging_power", "wallbox", "power"),
            _entity("sensor.wallbox_pulsar_plus_added_energy", "wallbox", "energy"),
            _entity("number.wallbox_pulsar_plus_maximum_charging_current", "wallbox"),
            _entity("switch.wallbox_pulsar_plus_pause_resume", "wallbox"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_wallbox_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_charging_power_sensor") == "sensor.wallbox_pulsar_plus_charging_power"
        assert result.get("ev_current_control_entity") == "number.wallbox_pulsar_plus_maximum_charging_current"
        assert result.get("ev_start_stop_entity") == "switch.wallbox_pulsar_plus_pause_resume"

    def test_wallbox_power_kw(self):
        """Wallbox reports power in kW."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(7.4, unit="kW")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.wallbox_pulsar_plus_charging_power", "ev") == 7400.0


class TestGoEChargerMQTTDiscovery:
    """go-eCharger MQTT — HACS (syssi/homeassistant-goecharger-mqtt)."""

    def _entities(self):
        return [
            _entity("binary_sensor.go_echarger_123456_car_plug", "goecharger_mqtt", "plug"),
            _entity("sensor.go_echarger_123456_nrg_current_power", "goecharger_mqtt", "power"),
            _entity("sensor.go_echarger_123456_eto_total_energy", "goecharger_mqtt", "energy"),
            _entity("number.go_echarger_123456_amp_requested_current", "goecharger_mqtt"),
            _entity("select.go_echarger_123456_frc_force_state", "goecharger_mqtt"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_goe_mqtt_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_current_control_entity") == "number.go_echarger_123456_amp_requested_current"
        assert result.get("ev_charge_mode_entity") == "select.go_echarger_123456_frc_force_state"
        assert result.get("ev_charge_mode_start") == "2"
        assert result.get("ev_charge_mode_stop") == "1"

    def test_goe_power_watts(self):
        """go-eCharger MQTT reports power in W (not kW)."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(4800, unit="W")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.go_echarger_123456_nrg_current_power", "ev") == 4800.0


class TestZaptecDiscovery:
    """Zaptec — HACS (custom-components/zaptec)."""

    def _entities(self):
        return [
            _entity("binary_sensor.zaptec_charger_cable_connected", "zaptec"),
            _entity("binary_sensor.zaptec_charger_charging", "zaptec"),
            _entity("sensor.zaptec_charger_total_charge_power", "zaptec", "power", "dev_zaptec_001"),
            _entity("sensor.zaptec_charger_signed_meter_value_kwh", "zaptec", "energy"),
            _entity("button.zaptec_charger_resume_charging", "zaptec"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_zaptec_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_charging_power_sensor") == "sensor.zaptec_charger_total_charge_power"
        assert result.get("ev_start_stop_entity") == "button.zaptec_charger_resume_charging"


class TestChargePointDiscovery:
    """ChargePoint — HACS (mbillow/ha-chargepoint)."""

    def _entities(self):
        return [
            _entity("binary_sensor.chargepoint_home_connected", "chargepoint"),
            _entity("binary_sensor.chargepoint_home_charging", "chargepoint"),
            _entity("sensor.chargepoint_home_power_output", "chargepoint", "power"),
            _entity("sensor.chargepoint_home_energy_output", "chargepoint", "energy"),
            _entity("number.chargepoint_home_charging_amperage_limit", "chargepoint"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_chargepoint_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_charging_power_sensor") == "sensor.chargepoint_home_power_output"
        assert result.get("ev_current_control_entity") == "number.chargepoint_home_charging_amperage_limit"


class TestHeidelbergDiscovery:
    """Heidelberg Energy Control — HACS."""

    def _entities(self):
        return [
            _entity("binary_sensor.heidelberg_wallbox_connected", "heidelberg_energy_control"),
            _entity("binary_sensor.heidelberg_wallbox_charging", "heidelberg_energy_control"),
            _entity("sensor.heidelberg_wallbox_charging_power", "heidelberg_energy_control", "power"),
            _entity("sensor.heidelberg_wallbox_total_energy", "heidelberg_energy_control", "energy"),
            _entity("number.heidelberg_wallbox_charging_current_limit", "heidelberg_energy_control"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_heidelberg_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_charging_power_sensor") == "sensor.heidelberg_wallbox_charging_power"
        assert result.get("ev_current_control_entity") == "number.heidelberg_wallbox_charging_current_limit"


class TestOpenWBDiscovery:
    """OpenWB 2.x — HACS (openwb2mqtt)."""

    def _entities(self):
        return [
            _entity("binary_sensor.openwb_chargepoint_1_plug", "openwb2mqtt"),
            _entity("binary_sensor.openwb_chargepoint_1_charging", "openwb2mqtt"),
            _entity("sensor.openwb_chargepoint_1_charging_power", "openwb2mqtt", "power"),
            _entity("sensor.openwb_chargepoint_1_total_energy", "openwb2mqtt", "energy"),
            _entity("number.openwb_chargepoint_1_current", "openwb2mqtt"),
            _entity("select.openwb_chargepoint_1_chargemode", "openwb2mqtt"),
        ]

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_openwb_discovery(self, mock_er):
        hass = MagicMock()
        mock_er.async_get.return_value = _mock_registry(self._entities())
        result = discover_ev_charger_from_registry(hass)
        assert result.get("ev_charging_power_sensor") == "sensor.openwb_chargepoint_1_charging_power"
        assert result.get("ev_current_control_entity") == "number.openwb_chargepoint_1_current"
        assert result.get("ev_charge_mode_entity") == "select.openwb_chargepoint_1_chargemode"
        assert result.get("ev_charge_mode_start") == "Instant Charging"
        assert result.get("ev_charge_mode_stop") == "Stop"


# ════════════════════════════════════════════
# Inverter Sign Convention Tests
# ════════════════════════════════════════════

class TestInverterSignConventions:
    """Test that SEM auto-detects grid and battery sign for each inverter.

    The detection needs 2 calls: first sets baseline, second detects from delta.
    """

    def _make_reader(self, hass):
        """Create a SensorReader with mock Energy Dashboard config."""
        config = {"battery_power_sensor": "sensor.battery_power"}
        reader = SensorReader(hass, config)

        ed = MagicMock()
        ed.solar_power = "sensor.solar_power"
        ed.grid_import_power = "sensor.grid_power"
        ed.battery_power = "sensor.battery_power"
        ed.grid_import_energy = "sensor.grid_import_energy"
        ed.grid_export_energy = "sensor.grid_export_energy"
        ed.battery_charge_energy = "sensor.battery_charge_energy"
        ed.battery_discharge_energy = "sensor.battery_discharge_energy"
        ed.ev_power = None
        ed.has_solar = True
        ed.has_grid = True
        ed.has_battery = True
        ed.has_ev = False
        reader.set_energy_dashboard_config(ed)
        return reader

    def _detect_grid(self, reader, hass, power, import_v1, export_v1, import_v2, export_v2):
        """Run 2-call grid sign detection (baseline + detect)."""
        # Call 1: set baseline
        hass.states.get = lambda eid: {
            "sensor.grid_import_energy": _state(import_v1, unit="kWh"),
            "sensor.grid_export_energy": _state(export_v1, unit="kWh"),
        }.get(eid)
        reader._detect_grid_sign(MagicMock(grid_power=power))
        # Call 2: detect from delta
        hass.states.get = lambda eid: {
            "sensor.grid_import_energy": _state(import_v2, unit="kWh"),
            "sensor.grid_export_energy": _state(export_v2, unit="kWh"),
        }.get(eid)
        return reader._detect_grid_sign(MagicMock(grid_power=power))

    def _detect_battery(self, reader, hass, power, charge_v1, discharge_v1, charge_v2, discharge_v2):
        """Run 2-call battery sign detection (baseline + detect)."""
        hass.states.get = lambda eid: {
            "sensor.battery_charge_energy": _state(charge_v1, unit="kWh"),
            "sensor.battery_discharge_energy": _state(discharge_v1, unit="kWh"),
        }.get(eid)
        reader._detect_battery_sign(MagicMock(battery_power=power))
        hass.states.get = lambda eid: {
            "sensor.battery_charge_energy": _state(charge_v2, unit="kWh"),
            "sensor.battery_discharge_energy": _state(discharge_v2, unit="kWh"),
        }.get(eid)
        return reader._detect_battery_sign(MagicMock(battery_power=power))

    def test_huawei_sign_convention(self):
        """Huawei Solar: grid +export, battery +charge — matches SEM → no negate."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # Grid: positive power + export increasing → SEM convention
        assert self._detect_grid(reader, hass, 2000, 100, 100, 100, 101) is False
        # Battery: positive power + charge increasing → SEM convention
        reader2 = self._make_reader(hass)
        assert self._detect_battery(reader2, hass, 500, 50, 50, 51, 50) is False

    def test_goodwe_battery_opposite(self):
        """GoodWe: battery +discharge (OPPOSITE) → negate."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # Battery: positive power + discharge increasing → OPPOSITE
        assert self._detect_battery(reader, hass, 2000, 50, 50, 50, 51) is True

    def test_fronius_grid_opposite(self):
        """Fronius: grid +import (OPPOSITE) → negate."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # Grid: positive power + import increasing → OPPOSITE
        assert self._detect_grid(reader, hass, 3000, 100, 100, 101, 100) is True

    def test_enphase_both_opposite(self):
        """Enphase: grid +import (OPPOSITE), battery +discharge (OPPOSITE)."""
        hass = MagicMock()
        reader1 = self._make_reader(hass)
        assert self._detect_grid(reader1, hass, 1500, 100, 100, 101, 100) is True
        reader2 = self._make_reader(hass)
        assert self._detect_battery(reader2, hass, 1000, 50, 50, 50, 51) is True

    def test_sofar_sign_convention(self):
        """Sofar (via solax-modbus): grid +export, battery +charge — matches SEM."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # Sofar typically matches SEM convention
        assert self._detect_grid(reader, hass, 2000, 100, 100, 100, 101) is False
        reader2 = self._make_reader(hass)
        assert self._detect_battery(reader2, hass, 500, 50, 50, 51, 50) is False


# ════════════════════════════════════════════
# Charger Control Tests
# ════════════════════════════════════════════

class TestChargerServiceCalls:
    """Test that _set_current sends correct params per integration."""

    @pytest.mark.asyncio
    async def test_keba_set_current(self):
        """KEBA: keba.set_current with {"current": X}."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        dev = CurrentControlDevice(hass, "ev", "EV", charger_service="keba.set_current")
        dev.service_param_name = "current"
        await dev._set_current(16)
        hass.services.async_call.assert_called_with(
            "keba", "set_current", {"current": 16}, blocking=True)

    @pytest.mark.asyncio
    async def test_easee_set_current_with_device_id(self):
        """Easee: easee.set_charger_dynamic_limit with device_id."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        dev = CurrentControlDevice(hass, "ev", "EV",
                                    charger_service="easee.set_charger_dynamic_limit")
        dev.service_param_name = "current"
        dev.service_device_id = "dev_easee_001"
        await dev._set_current(12)
        hass.services.async_call.assert_called_with(
            "easee", "set_charger_dynamic_limit",
            {"current": 12, "device_id": "dev_easee_001"}, blocking=True)

    @pytest.mark.asyncio
    async def test_zaptec_available_current_param(self):
        """Zaptec: zaptec.limit_current with {"available_current": X, "device_id": Y}."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        dev = CurrentControlDevice(hass, "ev", "EV",
                                    charger_service="zaptec.limit_current")
        dev.service_param_name = "available_current"
        dev.service_device_id = "dev_zaptec_001"
        await dev._set_current(10)
        hass.services.async_call.assert_called_with(
            "zaptec", "limit_current",
            {"available_current": 10, "device_id": "dev_zaptec_001"}, blocking=True)

    @pytest.mark.asyncio
    async def test_wallbox_number_entity(self):
        """Wallbox: number.set_value (no service call)."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        dev = CurrentControlDevice(hass, "ev", "EV",
                                    current_entity_id="number.wallbox_pulsar_plus_maximum_charging_current")
        await dev._set_current(8)
        hass.services.async_call.assert_called_with(
            "number", "set_value",
            {"entity_id": "number.wallbox_pulsar_plus_maximum_charging_current", "value": 8},
            blocking=True)


# ════════════════════════════════════════════
# Additional Inverter Sign Convention Tests
# ════════════════════════════════════════════

class TestAdditionalInverterSigns(TestInverterSignConventions):
    """Additional inverters not in the base set."""

    def test_solax_grid_opposite(self):
        """SolaX (solax-modbus): grid +import/-export (OPPOSITE)."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # SolaX: positive power during import → opposite
        assert self._detect_grid(reader, hass, 3000, 100, 100, 101, 100) is True

    def test_solax_battery_matches(self):
        """SolaX: battery +charge/-discharge (matches SEM)."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        assert self._detect_battery(reader, hass, 1000, 50, 50, 51, 50) is False

    def test_deye_sunsynk_matches(self):
        """DEYE/Sunsynk (ha-solarman): grid -import/+export, battery +charge/-discharge — matches SEM."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # Grid: positive during export → matches SEM
        assert self._detect_grid(reader, hass, 2000, 100, 100, 100, 101) is False
        reader2 = self._make_reader(hass)
        # Battery: positive during charge → matches SEM
        assert self._detect_battery(reader2, hass, 500, 50, 50, 51, 50) is False

    def test_solark_same_as_deye(self):
        """SolArk uses DEYE profiles — same convention."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        assert self._detect_grid(reader, hass, 1500, 100, 100, 100, 101) is False
        reader2 = self._make_reader(hass)
        assert self._detect_battery(reader2, hass, 800, 50, 50, 51, 50) is False

    def test_solis_modbus_matches(self):
        """Solis (modbus): grid +export/-import, battery +charge/-discharge — matches SEM."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        assert self._detect_grid(reader, hass, 2000, 100, 100, 100, 101) is False
        reader2 = self._make_reader(hass)
        assert self._detect_battery(reader2, hass, 500, 50, 50, 51, 50) is False

    def test_sma_grid_matches(self):
        """SMA: grid +export/-import — matches SEM."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        assert self._detect_grid(reader, hass, 2000, 100, 100, 100, 101) is False

    def test_solaredge_battery_opposite(self):
        """SolarEdge (native): battery +discharge/-charge (OPPOSITE)."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        # Positive power + discharge increasing → opposite
        assert self._detect_battery(reader, hass, 1500, 50, 50, 50, 51) is True

    def test_kstar_grid_matches(self):
        """KSTAR (ha-solarman with scale:-1): grid -import/+export — matches SEM."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        assert self._detect_grid(reader, hass, 2000, 100, 100, 100, 101) is False

    def test_powerwall_both_opposite(self):
        """Tesla Powerwall: grid +import (OPPOSITE), battery -charge/+discharge (OPPOSITE)."""
        hass = MagicMock()
        reader1 = self._make_reader(hass)
        # Grid: positive during import → opposite
        assert self._detect_grid(reader1, hass, 2000, 100, 100, 101, 100) is True
        reader2 = self._make_reader(hass)
        # Battery: positive during discharge → opposite
        assert self._detect_battery(reader2, hass, 1500, 50, 50, 50, 51) is True

    def test_sonnen_grid_matches_battery_opposite(self):
        """Sonnenbatterie: grid +export (matches), battery +discharge (OPPOSITE)."""
        hass = MagicMock()
        reader1 = self._make_reader(hass)
        assert self._detect_grid(reader1, hass, 2000, 100, 100, 100, 101) is False
        reader2 = self._make_reader(hass)
        assert self._detect_battery(reader2, hass, 1000, 50, 50, 50, 51) is True

    def test_myenergi_grid_opposite(self):
        """Myenergi hub: grid +import/-export (OPPOSITE)."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        assert self._detect_grid(reader, hass, 1500, 100, 100, 101, 100) is True


# ════════════════════════════════════════════
# Power Reading: kW vs W unit handling
# ════════════════════════════════════════════

class TestPowerUnitConversion:
    """Test kW→W conversion for integrations that report in kW."""

    def test_growatt_mix_kw(self):
        """Growatt Mix: power in kW."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(5.2, unit="kW")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.growatt_mix_wattage_pv_all", "solar") == 5200.0

    def test_powerwall_meter_kw(self):
        """Tesla Powerwall meter: instant_power in kW."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(2.5, unit="kW")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.powerwall_solar_instant_power", "solar") == 2500.0

    def test_sma_daily_yield_wh(self):
        """SMA daily yield in Wh (not kWh) — no conversion needed for power."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(3500, unit="W")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.sma_pv_power", "solar") == 3500.0

    def test_solaredge_power_watts(self):
        """SolarEdge Modbus: power in W."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(8000, unit="W")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.solaredge_ac_power", "solar") == 8000.0

    def test_sonnen_power_watts(self):
        """Sonnenbatterie: power in W."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(4500, unit="W")
        reader = SensorReader(hass, {})
        assert reader._read_sensor("sensor.sonnenbatterie_state_production", "solar") == 4500.0


# ════════════════════════════════════════════
# Monitoring-Only Chargers
# ════════════════════════════════════════════

class TestMonitoringOnlyChargers:
    """Chargers that can be monitored but not controlled."""

    def test_tesla_wall_connector_no_power_sensor(self):
        """Tesla Wall Connector has no power sensor — only current + voltage."""
        hass = MagicMock()
        # Only current and voltage, no power
        hass.states.get = lambda eid: {
            "sensor.tesla_wall_connector_current_a_a": _state(15.2, unit="A"),
            "sensor.tesla_wall_connector_voltage_a_v": _state(230, unit="V"),
            "sensor.tesla_wall_connector_session_energy_wh": _state(12500, unit="Wh"),
        }.get(eid)
        reader = SensorReader(hass, {})
        # No power sensor → returns 0
        assert reader._read_sensor("sensor.tesla_wall_connector_power", "ev") == 0.0

    def test_zappi_status_reading(self):
        """Myenergi Zappi: can read charging power but cannot control current."""
        hass = MagicMock()
        hass.states.get = lambda eid: _state(3200, unit="W")
        reader = SensorReader(hass, {})
        # Can read power (monitoring works)
        assert reader._read_sensor("sensor.myenergi_zappi_ct1_power", "ev") == 3200.0
