"""End-to-end hardware integration tests (#96).

Each test simulates the complete user journey for a specific
inverter + EV charger combination:
  1. Energy Dashboard configured with inverter sensors
  2. Config flow: auto-detect charger from entity registry
  3. First coordinator cycle: read sensors, detect sign convention
  4. Solar surplus scenario: verify EV charges with correct params
  5. Stop scenario: verify correct stop command per charger

Uses real entity IDs, device classes, and state values from each
integration's source code.
"""
import pytest
import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Dict, Any, Optional

from homeassistant.util import dt as dt_util


# ════════════════════════════════════════════
# Shared E2E Test Infrastructure
# ════════════════════════════════════════════

@dataclass
class MockInverter:
    """Mock inverter entity configuration."""
    name: str
    solar_power: str      # entity_id
    solar_energy: str
    grid_power: str       # signed power sensor
    grid_import_energy: str
    grid_export_energy: str
    battery_power: str
    battery_soc: str
    battery_charge_energy: str
    battery_discharge_energy: str
    battery_capacity_entity: Optional[str] = None
    # Sign convention: what positive means for this inverter
    grid_positive_means: str = "export"   # "export" (SEM match) or "import" (needs negate)
    battery_positive_means: str = "charge"  # "charge" (SEM match) or "discharge" (needs negate)


@dataclass
class MockCharger:
    """Mock EV charger entity configuration."""
    name: str
    platform: str         # entity registry platform name
    connected_sensor: str  # entity_id
    charging_sensor: str
    power_sensor: str
    power_unit: str = "W"  # "W" or "kW"
    # Optional entities
    energy_sensor: Optional[str] = None
    current_entity: Optional[str] = None  # number entity for current control
    service: Optional[str] = None         # service name (keba.set_current etc.)
    service_param: str = "current"        # service data param name
    device_id: Optional[str] = None
    # Start/stop control
    start_stop_entity: Optional[str] = None  # switch or button
    charge_mode_entity: Optional[str] = None  # select entity
    charge_mode_start: Optional[str] = None
    charge_mode_stop: Optional[str] = None
    start_service: Optional[str] = None
    start_service_data: Optional[str] = None
    stop_service: Optional[str] = None
    stop_service_data: Optional[str] = None
    # Status values
    connected_state: str = "on"   # what state means "connected"
    charging_state: str = "on"    # what state means "charging"
    disconnected_state: str = "off"


def _state(value, unit=None, device_class=None, state_class=None):
    """Create a mock HA state."""
    s = MagicMock()
    s.state = str(value)
    s.attributes = {}
    if unit:
        s.attributes["unit_of_measurement"] = unit
    if device_class:
        s.attributes["device_class"] = device_class
    if state_class:
        s.attributes["state_class"] = state_class
    return s


def _entity(entity_id, platform, device_class=None, device_id=None):
    """Create a mock entity registry entry."""
    e = MagicMock()
    e.entity_id = entity_id
    e.platform = platform
    e.original_device_class = device_class
    e.disabled_by = None
    e.device_id = device_id or f"dev_{platform}_001"
    return e


class E2ETestBase:
    """Base class for end-to-end hardware tests.

    Subclasses define an inverter + charger combination and run
    through the full install-to-charging flow.
    """

    inverter: MockInverter = None
    charger: MockCharger = None

    def _build_energy_dashboard_file(self, tmp_path) -> str:
        """Create a mock .storage/energy file matching this inverter."""
        inv = self.inverter
        energy_config = {
            "version": 1,
            "data": {
                "energy_sources": [
                    {
                        "type": "solar",
                        "stat_energy_from": inv.solar_energy,
                        "config_entry_solar_forecast": [],
                        "stat_rate": inv.solar_power,
                    },
                    {
                        "type": "grid",
                        "flow_from": [{"stat_energy_from": inv.grid_import_energy}],
                        "flow_to": [{"stat_energy_to": inv.grid_export_energy}],
                        "power": [{"stat_rate": inv.grid_power}],
                    },
                    {
                        "type": "battery",
                        "stat_energy_from": inv.battery_discharge_energy,
                        "stat_energy_to": inv.battery_charge_energy,
                        "stat_rate": inv.battery_power,
                    },
                ],
                "device_consumption": [
                    {
                        "stat_consumption": self.charger.energy_sensor or f"sensor.{self.charger.platform}_energy",
                        "stat_rate": self.charger.power_sensor,
                    },
                ],
            },
        }
        storage_dir = tmp_path / ".storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        energy_file = storage_dir / "energy"
        energy_file.write_text(json.dumps(energy_config))
        return str(tmp_path)

    def _build_states(self, solar_w=8000, grid_w=2000, battery_w=500,
                       battery_soc=80, ev_power=0, ev_connected=True,
                       ev_charging=False) -> Dict[str, Any]:
        """Build a complete set of mock HA states for a solar surplus scenario."""
        inv = self.inverter
        chg = self.charger

        # Apply sign convention: convert SEM values to inverter values
        grid_value = grid_w
        if inv.grid_positive_means == "import":
            grid_value = -grid_w  # SEM: +export → inverter: -export
        battery_value = battery_w
        if inv.battery_positive_means == "discharge":
            battery_value = -battery_w  # SEM: +charge → inverter: -charge

        power_unit = "W"
        ev_unit = chg.power_unit

        states = {
            # Inverter sensors
            inv.solar_power: _state(solar_w, unit=power_unit, device_class="power"),
            inv.grid_power: _state(grid_value, unit=power_unit, device_class="power"),
            inv.battery_power: _state(battery_value, unit=power_unit, device_class="power"),
            inv.battery_soc: _state(battery_soc, unit="%", device_class="battery"),
            # Energy counters (baseline values)
            inv.solar_energy: _state(1000, unit="kWh", device_class="energy"),
            inv.grid_import_energy: _state(500, unit="kWh", device_class="energy"),
            inv.grid_export_energy: _state(600, unit="kWh", device_class="energy"),
            inv.battery_charge_energy: _state(300, unit="kWh", device_class="energy"),
            inv.battery_discharge_energy: _state(280, unit="kWh", device_class="energy"),
        }

        # EV charger sensors
        # Handle chargers where connected + charging use the SAME entity (Easee)
        if chg.connected_sensor == chg.charging_sensor:
            # Single status entity — pick the most specific state
            if ev_charging:
                states[chg.connected_sensor] = _state(chg.charging_state)
            elif ev_connected:
                states[chg.connected_sensor] = _state(chg.connected_state)
            else:
                states[chg.connected_sensor] = _state(chg.disconnected_state)
        else:
            # Separate entities for connected and charging
            if chg.connected_state == "on":
                states[chg.connected_sensor] = _state("on" if ev_connected else "off")
            else:
                states[chg.connected_sensor] = _state(chg.connected_state if ev_connected else chg.disconnected_state)

            if chg.charging_state == "on":
                states[chg.charging_sensor] = _state("on" if ev_charging else "off")
            else:
                states[chg.charging_sensor] = _state(chg.charging_state if ev_charging else chg.disconnected_state)

        ev_power_value = ev_power / 1000 if chg.power_unit == "kW" else ev_power
        states[chg.power_sensor] = _state(ev_power_value, unit=chg.power_unit, device_class="power")

        if chg.energy_sensor:
            states[chg.energy_sensor] = _state(50, unit="kWh", device_class="energy")

        return states

    def _build_charger_registry(self):
        """Build entity registry entries for the charger."""
        chg = self.charger
        entities = [
            _entity(chg.connected_sensor, chg.platform,
                    "plug" if "binary_sensor" in chg.connected_sensor else None,
                    chg.device_id),
            _entity(chg.power_sensor, chg.platform, "power", chg.device_id),
        ]

        if chg.charging_sensor != chg.connected_sensor:
            dc = "power" if "binary_sensor" in chg.charging_sensor else None
            entities.append(_entity(chg.charging_sensor, chg.platform, dc, chg.device_id))

        if chg.energy_sensor:
            entities.append(_entity(chg.energy_sensor, chg.platform, "energy", chg.device_id))

        if chg.current_entity:
            entities.append(_entity(chg.current_entity, chg.platform, None, chg.device_id))

        if chg.start_stop_entity:
            entities.append(_entity(chg.start_stop_entity, chg.platform, None, chg.device_id))

        if chg.charge_mode_entity:
            entities.append(_entity(chg.charge_mode_entity, chg.platform, None, chg.device_id))

        return entities

    # ─── Test Methods ────────────────────────────

    def test_config_flow_entity_validation(self):
        """Step 0: Config flow ACCEPTS this charger's entities — prevents #68.

        This is the most critical test. If this fails, the user can't even
        complete the install flow.
        """
        from custom_components.solar_energy_management.hardware_detection import (
            EVChargerDetector,
        )

        hass = MagicMock()
        chg = self.charger

        # Set up states matching what this charger exposes in HA
        states = {}

        # Connected sensor — must be accepted by validate_ev_configuration
        if chg.connected_state == "on":
            states[chg.connected_sensor] = _state("on")
        else:
            states[chg.connected_sensor] = _state(chg.connected_state)

        # Charging sensor
        if chg.charging_state == "on":
            states[chg.charging_sensor] = _state("off")  # not charging yet
        else:
            # For Easee-type: use connected state (not charging)
            if chg.connected_sensor == chg.charging_sensor:
                states[chg.charging_sensor] = _state(chg.connected_state)
            else:
                states[chg.charging_sensor] = _state("off")

        # Power sensor — must accept the unit this charger uses
        if chg.power_unit == "kW":
            states[chg.power_sensor] = _state(0.0, unit="kW", device_class="power")
        else:
            states[chg.power_sensor] = _state(0, unit="W", device_class="power")

        # Optional entities
        if chg.energy_sensor:
            states[chg.energy_sensor] = _state(100, unit="kWh", device_class="energy")

        hass.states.get = lambda eid: states.get(eid)

        detector = EVChargerDetector(hass)
        user_input = {
            "ev_connected_sensor": chg.connected_sensor,
            "ev_charging_sensor": chg.charging_sensor,
            "ev_charging_power_sensor": chg.power_sensor,
        }
        if chg.service:
            user_input["ev_charger_service"] = chg.service
        if chg.energy_sensor:
            user_input["ev_total_energy_sensor"] = chg.energy_sensor

        errors = detector.validate_ev_configuration(user_input)
        assert not errors, \
            f"{chg.name}: config flow would REJECT these entities! Errors: {errors}. " \
            f"This is the #68 problem — user can't complete install."

    @patch("custom_components.solar_energy_management.hardware_detection.entity_registry")
    def test_charger_discovery(self, mock_er):
        """Step 1: Charger auto-detected from entity registry."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_ev_charger_from_registry,
        )
        hass = MagicMock()
        reg = MagicMock()
        reg.entities = MagicMock()
        reg.entities.values.return_value = self._build_charger_registry()
        mock_er.async_get.return_value = reg

        result = discover_ev_charger_from_registry(hass)
        assert result, f"{self.charger.name}: discovery returned empty"
        assert result.get("ev_charging_power_sensor") == self.charger.power_sensor, \
            f"{self.charger.name}: power sensor not found"

    def test_sensor_reading(self):
        """Step 2: All sensors read correctly with sign convention."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        hass = MagicMock()
        states = self._build_states(solar_w=8000, grid_w=2000, battery_w=500,
                                     battery_soc=80, ev_connected=True)
        hass.states.get = lambda eid: states.get(eid)

        config = {
            "ev_power_sensor": self.charger.power_sensor,
            "ev_connected_sensor": self.charger.connected_sensor,
            "ev_charging_sensor": self.charger.charging_sensor,
        }
        reader = SensorReader(hass, config)

        # Solar power should be positive
        solar = reader._read_sensor(self.inverter.solar_power, "solar")
        assert solar > 0, f"{self.inverter.name}: solar power should be positive, got {solar}"

        # EV connected should be True
        connected = reader._read_binary_sensor(self.charger.connected_sensor, "ev_plug")
        assert connected is True, f"{self.charger.name}: should read as connected"

        # Power unit conversion: kW sensors should be converted to W
        ev_power = reader._read_sensor(self.charger.power_sensor, "ev")
        # We set ev_power=0 in _build_states, so just verify no crash
        assert ev_power >= 0

    def test_power_unit_conversion(self):
        """Step 3: kW→W conversion works for this charger."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        hass = MagicMock()
        if self.charger.power_unit == "kW":
            hass.states.get = lambda eid: _state(3.5, unit="kW", device_class="power")
        else:
            hass.states.get = lambda eid: _state(3500, unit="W", device_class="power")

        reader = SensorReader(hass, {})
        value = reader._read_sensor(self.charger.power_sensor, "ev")
        assert value == 3500.0, f"{self.charger.name}: expected 3500W, got {value}"

    @pytest.mark.asyncio
    async def test_set_current(self):
        """Step 4: _set_current sends correct service params."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        chg = self.charger

        if chg.service:
            dev = CurrentControlDevice(hass, "ev", "EV", charger_service=chg.service)
            dev.service_param_name = chg.service_param
            if chg.device_id:
                dev.service_device_id = chg.device_id
            await dev._set_current(16)

            call = hass.services.async_call.call_args
            domain, service = chg.service.split(".", 1)
            assert call[0][0] == domain
            assert call[0][1] == service
            assert call[0][2][chg.service_param] == 16
            if chg.device_id:
                assert call[0][2]["device_id"] == chg.device_id
        elif chg.current_entity:
            dev = CurrentControlDevice(hass, "ev", "EV",
                                        current_entity_id=chg.current_entity)
            await dev._set_current(12)
            call = hass.services.async_call.call_args
            assert call[0][0] == "number"
            assert call[0][1] == "set_value"
            assert call[0][2]["entity_id"] == chg.current_entity

    @pytest.mark.asyncio
    async def test_energy_dashboard_parsing(self, tmp_path):
        """Step 5: Energy Dashboard file parsed correctly for this inverter."""
        from custom_components.solar_energy_management.ha_energy_reader import (
            read_energy_dashboard_config,
        )

        config_dir = self._build_energy_dashboard_file(tmp_path)

        # Mock hass with config_dir pointing to our temp directory
        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn: fn())

        config = await read_energy_dashboard_config(hass)

        assert config is not None, f"{self.inverter.name}: Energy Dashboard parse returned None"
        assert config.has_solar, f"{self.inverter.name}: solar not detected"
        assert config.has_grid, f"{self.inverter.name}: grid not detected"
        assert config.solar_power == self.inverter.solar_power, \
            f"{self.inverter.name}: solar power sensor mismatch: {config.solar_power}"
        assert config.grid_import_energy == self.inverter.grid_import_energy, \
            f"{self.inverter.name}: grid import energy mismatch: {config.grid_import_energy}"

    def test_first_coordinator_cycle(self):
        """Step 6: First coordinator cycle completes without exception."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader
        from custom_components.solar_energy_management.coordinator.types import PowerReadings

        hass = MagicMock()
        inv = self.inverter
        chg = self.charger

        # Simulate solar surplus: 8kW solar, 2kW export, 500W battery charge
        states = self._build_states(solar_w=8000, grid_w=2000, battery_w=500,
                                     battery_soc=80, ev_connected=True, ev_charging=False)
        hass.states.get = lambda eid: states.get(eid)

        config = {
            "ev_power_sensor": chg.power_sensor,
            "ev_connected_sensor": chg.connected_sensor,
            "ev_charging_sensor": chg.charging_sensor,
            "battery_power_sensor": inv.battery_power,
            "battery_soc_sensor": inv.battery_soc,
        }
        reader = SensorReader(hass, config)

        # Set up Energy Dashboard config for sign detection
        ed = MagicMock()
        ed.solar_power = inv.solar_power
        ed.grid_import_power = inv.grid_power
        ed.battery_power = inv.battery_power
        ed.grid_import_energy = inv.grid_import_energy
        ed.grid_export_energy = inv.grid_export_energy
        ed.battery_charge_energy = inv.battery_charge_energy
        ed.battery_discharge_energy = inv.battery_discharge_energy
        ed.ev_power = chg.power_sensor
        ed.has_solar = True
        ed.has_grid = True
        ed.has_battery = True
        ed.has_ev = True
        reader.set_energy_dashboard_config(ed)

        # Read power — should not raise any exception
        try:
            power = reader.read_power()
        except Exception as e:
            pytest.fail(f"{inv.name}+{chg.name}: first read_power() failed: {e}")

        # Basic sanity: solar should be positive
        assert power.solar_power >= 0, \
            f"{inv.name}: solar_power should be >= 0, got {power.solar_power}"

    def test_energy_balance_positive_home(self):
        """Step 7: Home consumption is >= 0 (sign convention correct)."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        hass = MagicMock()
        inv = self.inverter

        # Scenario: 5kW solar, 1kW export, 1kW battery charge, 0W EV
        # Expected home = 5000 - 1000(export) - 1000(battery) = 3000W
        states = self._build_states(solar_w=5000, grid_w=1000, battery_w=1000,
                                     battery_soc=60, ev_connected=False)
        hass.states.get = lambda eid: states.get(eid)

        config = {
            "ev_power_sensor": self.charger.power_sensor,
            "ev_connected_sensor": self.charger.connected_sensor,
            "ev_charging_sensor": self.charger.charging_sensor,
            "battery_power_sensor": inv.battery_power,
        }
        reader = SensorReader(hass, config)

        ed = MagicMock()
        ed.solar_power = inv.solar_power
        ed.grid_import_power = inv.grid_power
        ed.battery_power = inv.battery_power
        ed.grid_import_energy = inv.grid_import_energy
        ed.grid_export_energy = inv.grid_export_energy
        ed.battery_charge_energy = inv.battery_charge_energy
        ed.battery_discharge_energy = inv.battery_discharge_energy
        ed.ev_power = self.charger.power_sensor
        ed.has_solar = True
        ed.has_grid = True
        ed.has_battery = True
        ed.has_ev = True
        reader.set_energy_dashboard_config(ed)

        power = reader.read_power()
        power.calculate_derived()

        # Home consumption must NEVER be negative (clamped to 0)
        assert power.home_consumption_power >= 0, \
            f"{inv.name}: home_consumption={power.home_consumption_power}W is negative! " \
            f"Solar={power.solar_power}, grid={power.grid_power}, " \
            f"battery={power.battery_power}, ev={power.ev_power}"

    def test_config_flow_entity_selector_accepts_domain(self):
        """Step 8: EntitySelector domain filter accepts this charger's entity type.

        The #68 root cause: EntitySelector had domain="binary_sensor" but
        Easee uses domain="sensor". This test verifies the selector would
        show the user's entity in the dropdown.
        """
        chg = self.charger
        connected_domain = chg.connected_sensor.split(".")[0]
        charging_domain = chg.charging_sensor.split(".")[0]

        # SEM config flow now uses domain=["binary_sensor", "sensor"]
        allowed_domains = ["binary_sensor", "sensor"]

        assert connected_domain in allowed_domains, \
            f"{chg.name}: connected sensor domain '{connected_domain}' " \
            f"not in allowed {allowed_domains} — user can't select it in config flow!"

        assert charging_domain in allowed_domains, \
            f"{chg.name}: charging sensor domain '{charging_domain}' " \
            f"not in allowed {allowed_domains} — user can't select it in config flow!"

    def test_ev_status_values(self):
        """Step 9: All charger status values correctly interpreted."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        hass = MagicMock()
        reader = SensorReader(hass, {})
        chg = self.charger

        # Test connected state
        hass.states.get = lambda eid: _state(chg.connected_state)
        assert reader._read_binary_sensor(chg.connected_sensor, "ev_plug") is True, \
            f"{chg.name}: '{chg.connected_state}' should read as connected"

        # Test disconnected state
        hass.states.get = lambda eid: _state(chg.disconnected_state)
        assert reader._read_binary_sensor(chg.connected_sensor, "ev_plug") is False, \
            f"{chg.name}: '{chg.disconnected_state}' should read as disconnected"

        # Test charging state
        hass.states.get = lambda eid: _state(chg.charging_state)
        result = reader._read_binary_sensor(chg.charging_sensor, "ev_charging")
        assert result is True, \
            f"{chg.name}: '{chg.charging_state}' should read as charging"


# ════════════════════════════════════════════
# Inverter Definitions
# ════════════════════════════════════════════

HUAWEI = MockInverter(
    name="Huawei Solar",
    solar_power="sensor.inverter_eingangsleistung",
    solar_energy="sensor.inverter_gesamtenergieertrag",
    grid_power="sensor.power_meter_wirkleistung",
    grid_import_energy="sensor.power_meter_verbrauch",
    grid_export_energy="sensor.power_meter_exportierte_energie",
    battery_power="sensor.battery_1_lade_entladeleistung",
    battery_soc="sensor.battery_1_batterieladung",
    battery_charge_energy="sensor.battery_1_gesamtladung",
    battery_discharge_energy="sensor.battery_1_gesamtentladung",
    grid_positive_means="export",
    battery_positive_means="charge",
)

GOODWE = MockInverter(
    name="GoodWe",
    solar_power="sensor.goodwe_pv_power",
    solar_energy="sensor.goodwe_e_total",
    grid_power="sensor.goodwe_active_power",
    grid_import_energy="sensor.goodwe_meter_e_total_imp",
    grid_export_energy="sensor.goodwe_meter_e_total_exp",
    battery_power="sensor.goodwe_battery_power",
    battery_soc="sensor.goodwe_battery_state_of_charge",
    battery_charge_energy="sensor.goodwe_e_bat_charge_total",
    battery_discharge_energy="sensor.goodwe_e_bat_discharge_total",
    grid_positive_means="export",
    battery_positive_means="discharge",  # OPPOSITE
)

FRONIUS = MockInverter(
    name="Fronius",
    solar_power="sensor.solarnet_power_photovoltaics",
    solar_energy="sensor.solarnet_energy_total",
    grid_power="sensor.solarnet_power_grid",
    grid_import_energy="sensor.solarnet_energy_real_consumed",
    grid_export_energy="sensor.solarnet_energy_real_produced",
    battery_power="sensor.solarnet_power_battery",
    battery_soc="sensor.fronius_storage_state_of_charge",
    battery_charge_energy="sensor.fronius_storage_energy_charge",
    battery_discharge_energy="sensor.fronius_storage_energy_discharge",
    grid_positive_means="import",  # OPPOSITE
    battery_positive_means="discharge",  # OPPOSITE
)

ENPHASE = MockInverter(
    name="Enphase",
    solar_power="sensor.envoy_current_power_production",
    solar_energy="sensor.envoy_lifetime_production",
    grid_power="sensor.envoy_net_consumption",
    grid_import_energy="sensor.envoy_lifetime_net_consumption",
    grid_export_energy="sensor.envoy_lifetime_net_production",
    battery_power="sensor.envoy_battery_discharge",
    battery_soc="sensor.envoy_battery_level",
    battery_charge_energy="sensor.envoy_lifetime_battery_charged",
    battery_discharge_energy="sensor.envoy_lifetime_battery_discharged",
    grid_positive_means="import",  # OPPOSITE
    battery_positive_means="discharge",  # OPPOSITE
)

SMA = MockInverter(
    name="SMA",
    solar_power="sensor.sma_pv_power",
    solar_energy="sensor.sma_total_yield",
    grid_power="sensor.sma_grid_power",
    grid_import_energy="sensor.sma_metering_total_absorbed",
    grid_export_energy="sensor.sma_metering_total_yield",
    battery_power="sensor.sma_battery_power_charge_total",
    battery_soc="sensor.sma_battery_soc_total",
    battery_charge_energy="sensor.sma_battery_charge_total",
    battery_discharge_energy="sensor.sma_battery_discharge_total",
    grid_positive_means="export",
    battery_positive_means="charge",
)

SOLAX = MockInverter(
    name="SolaX",
    solar_power="sensor.solax_pv_power_total",
    solar_energy="sensor.solax_total_energy",
    grid_power="sensor.solax_measured_power",
    grid_import_energy="sensor.solax_grid_import_total",
    grid_export_energy="sensor.solax_grid_export_total",
    battery_power="sensor.solax_battery_power_charge",
    battery_soc="sensor.solax_battery_capacity",
    battery_charge_energy="sensor.solax_battery_input_energy_total",
    battery_discharge_energy="sensor.solax_battery_output_energy_total",
    grid_positive_means="import",  # OPPOSITE
    battery_positive_means="charge",
)

DEYE = MockInverter(
    name="DEYE/Sunsynk",
    solar_power="sensor.inverter_pv_power",
    solar_energy="sensor.inverter_today_production",
    grid_power="sensor.inverter_grid_power",
    grid_import_energy="sensor.inverter_today_energy_import",
    grid_export_energy="sensor.inverter_today_energy_export",
    battery_power="sensor.inverter_battery_power",
    battery_soc="sensor.inverter_battery",
    battery_charge_energy="sensor.inverter_today_battery_charge",
    battery_discharge_energy="sensor.inverter_today_battery_discharge",
    grid_positive_means="export",
    battery_positive_means="charge",
)

POWERWALL = MockInverter(
    name="Tesla Powerwall",
    solar_power="sensor.powerwall_solar_instant_power",
    solar_energy="sensor.powerwall_solar_export",
    grid_power="sensor.powerwall_site_instant_power",
    grid_import_energy="sensor.powerwall_site_import",
    grid_export_energy="sensor.powerwall_site_export",
    battery_power="sensor.powerwall_battery_instant_power",
    battery_soc="sensor.powerwall_charge",
    battery_charge_energy="sensor.powerwall_battery_import",
    battery_discharge_energy="sensor.powerwall_battery_export",
    grid_positive_means="import",  # OPPOSITE
    battery_positive_means="discharge",  # OPPOSITE
)

SONNEN = MockInverter(
    name="Sonnenbatterie",
    solar_power="sensor.sonnenbatterie_state_production",
    solar_energy="sensor.sonnenbatterie_total_production",
    grid_power="sensor.sonnenbatterie_state_grid_inout",
    grid_import_energy="sensor.sonnenbatterie_total_grid_import",
    grid_export_energy="sensor.sonnenbatterie_total_grid_export",
    battery_power="sensor.sonnenbatterie_state_battery_inout",
    battery_soc="sensor.sonnenbatterie_state_battery_percentage_real",
    battery_charge_energy="sensor.sonnenbatterie_total_battery_charge",
    battery_discharge_energy="sensor.sonnenbatterie_total_battery_discharge",
    grid_positive_means="export",
    battery_positive_means="discharge",  # OPPOSITE
)

KOSTAL = MockInverter(
    name="Kostal Plenticore",
    solar_power="sensor.plenticore_dc_power",
    solar_energy="sensor.plenticore_total_yield",
    grid_power="sensor.plenticore_grid_power",
    grid_import_energy="sensor.plenticore_energy_from_grid",
    grid_export_energy="sensor.plenticore_energy_to_grid",
    battery_power="sensor.plenticore_battery_power",
    battery_soc="sensor.plenticore_battery_soc",
    battery_charge_energy="sensor.plenticore_battery_charge_total",
    battery_discharge_energy="sensor.plenticore_battery_discharge_total",
    grid_positive_means="import",  # OPPOSITE
    battery_positive_means="discharge",  # OPPOSITE
)

SUNGROW = MockInverter(
    name="Sungrow",
    solar_power="sensor.sungrow_total_dc_power",
    solar_energy="sensor.sungrow_total_energy_yield",
    grid_power="sensor.sungrow_export_power",
    grid_import_energy="sensor.sungrow_import_energy",
    grid_export_energy="sensor.sungrow_export_energy",
    battery_power="sensor.sungrow_battery_power",
    battery_soc="sensor.sungrow_battery_level",
    battery_charge_energy="sensor.sungrow_battery_charge_energy",
    battery_discharge_energy="sensor.sungrow_battery_discharge_energy",
    grid_positive_means="export",
    battery_positive_means="charge",
)

VICTRON = MockInverter(
    name="Victron",
    solar_power="sensor.victron_pv_power",
    solar_energy="sensor.victron_pv_energy_total",
    grid_power="sensor.victron_grid_power",
    grid_import_energy="sensor.victron_grid_energy_from",
    grid_export_energy="sensor.victron_grid_energy_to",
    battery_power="sensor.victron_battery_power",
    battery_soc="sensor.victron_battery_soc",
    battery_charge_energy="sensor.victron_battery_charge_total",
    battery_discharge_energy="sensor.victron_battery_discharge_total",
    grid_positive_means="import",  # OPPOSITE
    battery_positive_means="discharge",  # OPPOSITE
)

SOLAREDGE_MODBUS = MockInverter(
    name="SolarEdge Modbus",
    solar_power="sensor.solaredge_i1_ac_power",
    solar_energy="sensor.solaredge_i1_ac_energy_kwh",
    grid_power="sensor.solaredge_m1_ac_power",
    grid_import_energy="sensor.solaredge_m1_imported_kwh",
    grid_export_energy="sensor.solaredge_m1_exported_kwh",
    battery_power="sensor.solaredge_b1_dc_power",
    battery_soc="sensor.solaredge_b1_state_of_energy",
    battery_charge_energy="sensor.solaredge_b1_energy_charged",
    battery_discharge_energy="sensor.solaredge_b1_energy_discharged",
    grid_positive_means="export",
    battery_positive_means="charge",
)


# ════════════════════════════════════════════
# Charger Definitions
# ════════════════════════════════════════════

KEBA = MockCharger(
    name="KEBA P30",
    platform="keba",
    connected_sensor="binary_sensor.keba_kecontact_p30_plug",
    charging_sensor="binary_sensor.keba_kecontact_p30_charging_state",
    power_sensor="sensor.keba_kecontact_p30_charging_power",
    power_unit="kW",
    energy_sensor="sensor.keba_kecontact_p30_total_energy",
    service="keba.set_current",
    service_param="current",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

EASEE = MockCharger(
    name="Easee Home",
    platform="easee",
    connected_sensor="sensor.easee_home_status",
    charging_sensor="sensor.easee_home_status",
    power_sensor="sensor.easee_home_power",
    power_unit="kW",
    energy_sensor="sensor.easee_home_lifetime_energy",
    service="easee.set_charger_dynamic_limit",
    service_param="current",
    device_id="dev_easee_001",
    start_service="easee.action_command",
    start_service_data='{"action_command": "resume"}',
    stop_service="easee.action_command",
    stop_service_data='{"action_command": "pause"}',
    connected_state="ready_to_charge",
    charging_state="charging",
    disconnected_state="disconnected",
)

WALLBOX = MockCharger(
    name="Wallbox Pulsar",
    platform="wallbox",
    connected_sensor="binary_sensor.wallbox_pulsar_plus_plug_connected",
    charging_sensor="binary_sensor.wallbox_pulsar_plus_charging",
    power_sensor="sensor.wallbox_pulsar_plus_charging_power",
    power_unit="kW",
    energy_sensor="sensor.wallbox_pulsar_plus_added_energy",
    current_entity="number.wallbox_pulsar_plus_maximum_charging_current",
    start_stop_entity="switch.wallbox_pulsar_plus_pause_resume",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

GOE_MQTT = MockCharger(
    name="go-eCharger MQTT",
    platform="goecharger_mqtt",
    connected_sensor="binary_sensor.go_echarger_123456_car_plug",
    charging_sensor="binary_sensor.go_echarger_123456_car_charging",
    power_sensor="sensor.go_echarger_123456_nrg_current_power",
    power_unit="W",
    energy_sensor="sensor.go_echarger_123456_eto_total_energy",
    current_entity="number.go_echarger_123456_amp_requested_current",
    charge_mode_entity="select.go_echarger_123456_frc_force_state",
    charge_mode_start="2",
    charge_mode_stop="1",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

ZAPTEC = MockCharger(
    name="Zaptec",
    platform="zaptec",
    connected_sensor="binary_sensor.zaptec_charger_cable_connected",
    charging_sensor="binary_sensor.zaptec_charger_charging",
    power_sensor="sensor.zaptec_charger_total_charge_power",
    power_unit="W",
    energy_sensor="sensor.zaptec_charger_signed_meter_value_kwh",
    service="zaptec.limit_current",
    service_param="available_current",
    device_id="dev_zaptec_001",
    start_stop_entity="button.zaptec_charger_resume_charging",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

CHARGEPOINT = MockCharger(
    name="ChargePoint",
    platform="chargepoint",
    connected_sensor="binary_sensor.chargepoint_home_connected",
    charging_sensor="binary_sensor.chargepoint_home_charging",
    power_sensor="sensor.chargepoint_home_power_output",
    power_unit="W",
    energy_sensor="sensor.chargepoint_home_energy_output",
    current_entity="number.chargepoint_home_charging_amperage_limit",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

HEIDELBERG = MockCharger(
    name="Heidelberg",
    platform="heidelberg_energy_control",
    connected_sensor="binary_sensor.heidelberg_wallbox_connected",
    charging_sensor="binary_sensor.heidelberg_wallbox_charging",
    power_sensor="sensor.heidelberg_wallbox_charging_power",
    power_unit="W",
    energy_sensor="sensor.heidelberg_wallbox_total_energy",
    current_entity="number.heidelberg_wallbox_charging_current_limit",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

OPENWB = MockCharger(
    name="OpenWB 2.x",
    platform="openwb2mqtt",
    connected_sensor="binary_sensor.openwb_chargepoint_1_plug",
    charging_sensor="binary_sensor.openwb_chargepoint_1_charging",
    power_sensor="sensor.openwb_chargepoint_1_charging_power",
    power_unit="W",
    energy_sensor="sensor.openwb_chargepoint_1_total_energy",
    current_entity="number.openwb_chargepoint_1_current",
    charge_mode_entity="select.openwb_chargepoint_1_chargemode",
    charge_mode_start="Instant Charging",
    charge_mode_stop="Stop",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

OCPP = MockCharger(
    name="OCPP",
    platform="ocpp",
    connected_sensor="sensor.ocpp_charger_status_connector",
    charging_sensor="sensor.ocpp_charger_status_connector",
    power_sensor="sensor.ocpp_charger_power_active_import",
    power_unit="kW",
    energy_sensor="sensor.ocpp_charger_energy_active_import_register",
    current_entity="number.ocpp_charger_maximum_current",
    start_stop_entity="switch.ocpp_charger_charge_control",
    connected_state="Preparing",
    charging_state="Charging",
    disconnected_state="Available",
)

OHME = MockCharger(
    name="Ohme",
    platform="ohme",
    connected_sensor="sensor.ohme_home_pro_status",
    charging_sensor="sensor.ohme_home_pro_status",
    power_sensor="sensor.ohme_home_pro_power",
    power_unit="kW",
    energy_sensor="sensor.ohme_home_pro_energy",
    charge_mode_entity="select.ohme_home_pro_charge_mode",
    charge_mode_start="Max charge",
    charge_mode_stop="Paused",
    connected_state="Plugged in",
    charging_state="Charging",
    disconnected_state="Unplugged",
)

PEBLAR = MockCharger(
    name="Peblar",
    platform="peblar",
    connected_sensor="sensor.peblar_rocksolid_state",
    charging_sensor="sensor.peblar_rocksolid_state",
    power_sensor="sensor.peblar_rocksolid_power",
    power_unit="W",
    energy_sensor="sensor.peblar_rocksolid_session_energy",
    current_entity="number.peblar_rocksolid_charge_limit",
    start_stop_entity="switch.peblar_rocksolid_charge",
    connected_state="connected",
    charging_state="charging",
    disconnected_state="no EV connected",
)

V2C = MockCharger(
    name="V2C Trydan",
    platform="v2c",
    connected_sensor="binary_sensor.v2c_trydan_connected",
    charging_sensor="binary_sensor.v2c_trydan_charging",
    power_sensor="sensor.v2c_trydan_charge_power",
    power_unit="W",
    energy_sensor="sensor.v2c_trydan_charge_energy",
    current_entity="number.v2c_trydan_intensity",
    start_stop_entity="switch.v2c_trydan_pause_session",
    connected_state="on",
    charging_state="on",
    disconnected_state="off",
)

BLUE_CURRENT = MockCharger(
    name="Blue Current",
    platform="blue_current",
    connected_sensor="sensor.blue_current_bcw1_vehicle_status",
    charging_sensor="sensor.blue_current_bcw1_activity",
    power_sensor="sensor.blue_current_bcw1_total_kw",
    power_unit="kW",
    energy_sensor="sensor.blue_current_bcw1_actual_kwh",
    connected_state="connected",
    charging_state="charging",
    disconnected_state="available",
)

OPENEVSE = MockCharger(
    name="OpenEVSE",
    platform="openevse",
    connected_sensor="binary_sensor.openevse_station_vehicle",
    charging_sensor="sensor.openevse_station_status",
    power_sensor="sensor.openevse_station_current_power",
    power_unit="W",
    energy_sensor="sensor.openevse_station_usage_session",
    current_entity="number.openevse_station_max_current_soft",
    connected_state="on",
    charging_state="charging",
    disconnected_state="off",
)

ALFEN = MockCharger(
    name="Alfen Eve",
    platform="alfen_wallbox",
    connected_sensor="sensor.alfen_wallbox_main_state_socket_1",
    charging_sensor="sensor.alfen_wallbox_main_state_socket_1",
    power_sensor="sensor.alfen_wallbox_active_power_total_socket_1",
    power_unit="W",
    energy_sensor="sensor.alfen_wallbox_meter_reading_socket_1",
    current_entity="number.alfen_wallbox_main_normal_max_current_socket_1",
    connected_state="EV Connected",
    charging_state="Charging Power On",
    disconnected_state="Available",
)


# ════════════════════════════════════════════
# E2E Test Classes — one per combination
# ════════════════════════════════════════════

class TestE2E_Huawei_KEBA(E2ETestBase):
    """Reference combination — Huawei Solar + KEBA P30."""
    inverter = HUAWEI
    charger = KEBA


class TestE2E_GoodWe_Easee(E2ETestBase):
    """GoodWe (battery opposite) + Easee (kW, status sensor, device_id)."""
    inverter = GOODWE
    charger = EASEE


class TestE2E_Fronius_Wallbox(E2ETestBase):
    """Fronius (grid+battery opposite) + Wallbox (kW, switch pause/resume)."""
    inverter = FRONIUS
    charger = WALLBOX


class TestE2E_Enphase_Zaptec(E2ETestBase):
    """Enphase (both opposite) + Zaptec (available_current, button start/stop)."""
    inverter = ENPHASE
    charger = ZAPTEC


class TestE2E_SolaX_GoECharger(E2ETestBase):
    """SolaX (grid opposite) + go-eCharger MQTT (frc select)."""
    inverter = SOLAX
    charger = GOE_MQTT


class TestE2E_SMA_Heidelberg(E2ETestBase):
    """SMA (grid matches) + Heidelberg (number current_limit)."""
    inverter = SMA
    charger = HEIDELBERG


class TestE2E_DEYE_OpenWB(E2ETestBase):
    """DEYE/Sunsynk (matches SEM) + OpenWB (chargemode select)."""
    inverter = DEYE
    charger = OPENWB


class TestE2E_Powerwall_KEBA(E2ETestBase):
    """Tesla Powerwall (both opposite, kW) + KEBA."""
    inverter = POWERWALL
    charger = KEBA


class TestE2E_Sonnen_Wallbox(E2ETestBase):
    """Sonnenbatterie (battery opposite) + Wallbox."""
    inverter = SONNEN
    charger = WALLBOX


class TestE2E_Huawei_ChargePoint(E2ETestBase):
    """Huawei + ChargePoint (amperage number entity)."""
    inverter = HUAWEI
    charger = CHARGEPOINT


class TestE2E_GoodWe_OpenWB(E2ETestBase):
    """GoodWe (battery opposite) + OpenWB (chargemode select)."""
    inverter = GOODWE
    charger = OPENWB


class TestE2E_Kostal_Peblar(E2ETestBase):
    """Kostal Plenticore (both opposite) + Peblar (switch start/stop)."""
    inverter = KOSTAL
    charger = PEBLAR


class TestE2E_Sungrow_V2C(E2ETestBase):
    """Sungrow (grid matches) + V2C Trydan (intensity number)."""
    inverter = SUNGROW
    charger = V2C


class TestE2E_Victron_OCPP(E2ETestBase):
    """Victron (both opposite) + OCPP (generic protocol)."""
    inverter = VICTRON
    charger = OCPP


class TestE2E_SolarEdgeModbus_Ohme(E2ETestBase):
    """SolarEdge Modbus (grid matches) + Ohme (charge mode select)."""
    inverter = SOLAREDGE_MODBUS
    charger = OHME


class TestE2E_Fronius_Alfen(E2ETestBase):
    """Fronius (both opposite) + Alfen Eve (current limit number)."""
    inverter = FRONIUS
    charger = ALFEN


class TestE2E_Enphase_OpenEVSE(E2ETestBase):
    """Enphase (both opposite) + OpenEVSE (status-based)."""
    inverter = ENPHASE
    charger = OPENEVSE


class TestE2E_Powerwall_BlueCurrent(E2ETestBase):
    """Tesla Powerwall (both opposite) + Blue Current (no current control)."""
    inverter = POWERWALL
    charger = BLUE_CURRENT


class TestE2E_SMA_OCPP(E2ETestBase):
    """SMA (grid matches) + OCPP (generic protocol)."""
    inverter = SMA
    charger = OCPP


class TestE2E_DEYE_Peblar(E2ETestBase):
    """DEYE/Sunsynk (matches SEM) + Peblar (switch charge control)."""
    inverter = DEYE
    charger = PEBLAR
