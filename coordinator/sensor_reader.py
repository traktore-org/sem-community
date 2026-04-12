"""Sensor reading module for SEM coordinator."""
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .types import PowerReadings

_LOGGER = logging.getLogger(__name__)


@dataclass
class SensorConfig:
    """Configuration for sensor reading."""
    # Power sensors
    solar_power_sensor: Optional[str] = None
    grid_power_sensor: Optional[str] = None
    battery_power_sensor: Optional[str] = None
    ev_power_sensor: Optional[str] = None

    # Energy sensors (hardware counters)
    ev_daily_energy_sensor: Optional[str] = None

    # State sensors
    battery_soc_sensor: Optional[str] = None
    battery_temperature_sensor: Optional[str] = None

    # Binary sensors
    ev_plug_sensor: Optional[str] = None
    ev_charging_sensor: Optional[str] = None


class SensorReader:
    """Reads power and state values from Home Assistant sensors."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Initialize sensor reader."""
        self.hass = hass
        self.config = self._parse_config(config)
        self._energy_dashboard_config = None
        self._grid_sign_inverted = False
        self._grid_sign_detected = False  # True once sign is reliably determined
        self._grid_import_baseline: Optional[float] = None
        self._grid_export_baseline: Optional[float] = None

    def _parse_config(self, config: Dict[str, Any]) -> SensorConfig:
        """Parse configuration into SensorConfig."""
        # Layer 1: config_flow saves as ev_charging_power_sensor, legacy uses ev_power_sensor
        ev_power = config.get("ev_power_sensor") or config.get("ev_charging_power_sensor")

        # Auto-detect KEBA daily energy sensor if not explicitly configured
        ev_daily_energy = config.get("ev_daily_energy_sensor")
        if not ev_daily_energy and ev_power and "keba" in ev_power.lower():
            # Try common KEBA daily energy sensor pattern
            ev_daily_energy = "sensor.keba_p30_charging_daily"

        return SensorConfig(
            solar_power_sensor=config.get("solar_production_sensor"),
            grid_power_sensor=config.get("grid_power_sensor"),
            battery_power_sensor=config.get("battery_power_sensor"),
            ev_power_sensor=ev_power,
            ev_daily_energy_sensor=ev_daily_energy,
            battery_soc_sensor=config.get("battery_soc_sensor"),
            battery_temperature_sensor=config.get("battery_temperature_sensor"),
            ev_plug_sensor=config.get("ev_plug_sensor", "binary_sensor.keba_p30_plug"),
            ev_charging_sensor=config.get("ev_charging_sensor", "binary_sensor.keba_p30_charging_state"),
        )

    def set_energy_dashboard_config(self, ed_config) -> None:
        """Set energy dashboard configuration for alternative sensor reading."""
        self._energy_dashboard_config = ed_config

    def read_power(self) -> PowerReadings:
        """Read all power values from sensors."""
        readings = PowerReadings()

        # Try Energy Dashboard config first, then legacy config
        if self._energy_dashboard_config:
            readings = self._read_from_energy_dashboard()
        else:
            readings = self._read_from_legacy_config()

        # Calculate derived values
        readings.calculate_derived()

        # Auto-detect grid sign convention using Energy Dashboard counters.
        # SEM convention: negative = import, positive = export.
        # Compares power sensor sign against import/export energy counter
        # changes to determine if negation is needed.
        needs_negate = self._detect_grid_sign(readings)

        if needs_negate:
            readings.grid_power = -readings.grid_power
            readings.calculate_derived()

        return readings

    def _detect_grid_sign(self, readings: PowerReadings) -> bool:
        """Detect if grid power needs negation using Energy Dashboard counters.

        Compares the power sensor's sign against which energy counter
        (import or export) is increasing. This is reliable because the
        Energy Dashboard's flow_from/flow_to are always correct.

        Returns True if grid_power should be negated.
        """
        ed = self._energy_dashboard_config
        if not ed:
            return False  # No Energy Dashboard → trust the sensor

        import_entity = ed.grid_import_energy
        export_entity = ed.grid_export_energy

        if not import_entity or not export_entity:
            return False

        # Need meaningful power to detect (ignore noise)
        power = readings.grid_power
        if abs(power) < 100:
            return self._grid_sign_inverted  # Keep last known state

        # Read energy counter values
        import_state = self.hass.states.get(import_entity)
        export_state = self.hass.states.get(export_entity)

        if not import_state or import_state.state in ("unknown", "unavailable"):
            return self._grid_sign_inverted
        if not export_state or export_state.state in ("unknown", "unavailable"):
            return self._grid_sign_inverted

        try:
            import_val = float(import_state.state)
            export_val = float(export_state.state)
        except (ValueError, TypeError):
            return self._grid_sign_inverted

        # First call: store baselines, don't correct yet
        if self._grid_import_baseline is None:
            self._grid_import_baseline = import_val
            self._grid_export_baseline = export_val
            return False

        import_delta = import_val - self._grid_import_baseline
        export_delta = export_val - self._grid_export_baseline

        # Update baselines for next cycle
        self._grid_import_baseline = import_val
        self._grid_export_baseline = export_val

        # Determine convention from correlation:
        # power > 0 + import growing → HA convention (+ = import) → negate
        # power > 0 + export growing → SEM convention (+ = export) → no negate
        # power < 0 + import growing → SEM convention (- = import) → no negate
        # power < 0 + export growing → HA convention (- = export) → negate
        detected = None
        if import_delta > 0.001 and export_delta < 0.001:
            # Import counter increasing
            detected = power > 0  # If power positive during import → negate
        elif export_delta > 0.001 and import_delta < 0.001:
            # Export counter increasing
            detected = power < 0  # If power negative during export → negate

        if detected is not None and detected != self._grid_sign_inverted:
            if not self._grid_sign_detected:
                _LOGGER.info(
                    "Grid sign detected from Energy Dashboard counters: %s "
                    "(power=%.0fW, import_delta=%.3f, export_delta=%.3f)",
                    "negating (HA convention)" if detected else "no correction (SEM convention)",
                    power, import_delta, export_delta,
                )
            self._grid_sign_inverted = detected
            self._grid_sign_detected = True
        elif detected is not None and not self._grid_sign_detected:
            self._grid_sign_detected = True
            _LOGGER.info(
                "Grid sign confirmed from Energy Dashboard counters: %s",
                "negating (HA convention)" if detected else "no correction (SEM convention)",
            )

        return self._grid_sign_inverted

    def _read_from_energy_dashboard(self) -> PowerReadings:
        """Read power values from Energy Dashboard configured sensors."""
        ed = self._energy_dashboard_config
        readings = PowerReadings()

        # Solar power
        if ed.solar_power:
            readings.solar_power = self._read_sensor(ed.solar_power, "solar")

        # Grid power from Energy Dashboard.
        # SEM convention: negative = import, positive = export.
        # The stat_rate sensor may follow either inverter convention (+ = export,
        # matching SEM) or HA convention (+ = import, opposite of SEM).
        # read_power() auto-detects and corrects the sign after calculate_derived().
        if ed.grid_import_power:
            readings.grid_power = self._read_sensor(ed.grid_import_power, "grid")

        # Battery power — pass through the source sensor unchanged.
        #
        # The HA Energy Dashboard schema does not define a canonical signed
        # combined battery sensor — `stat_rate` is just a pass-through to
        # whatever the source integration exposes. Major inverters
        # (Huawei, Fronius, SolarEdge, Tesla Powerwall, BYD, Sonnen) all
        # report negative = discharge / positive = charge, which matches
        # SEM convention. No transformation needed.
        #
        # Historical note: commit 00e449c added a `-` here under the
        # mistaken belief that the source sensor was already inverted by
        # the user to "follow HA convention". On real hardware that's not
        # the case — the negation double-flipped the sign and made
        # `home_consumption_power` clamp to 0 W. Reverted in #101.
        if ed.battery_power:
            readings.battery_power = self._read_sensor(ed.battery_power, "battery")

        # Battery SOC - from config or auto-detect from battery power sensor prefix
        if self.config.battery_soc_sensor:
            readings.battery_soc = self._read_sensor(
                self.config.battery_soc_sensor, "battery_soc"
            )
        elif ed.battery_power:
            # Auto-detect SOC from same device as battery power sensor
            soc_entity = self._auto_detect_battery_soc(ed.battery_power)
            if soc_entity:
                readings.battery_soc = self._read_sensor(soc_entity, "battery_soc")

        # EV power — Energy Dashboard first, then config fallback
        if ed.ev_power:
            readings.ev_power = self._read_sensor(ed.ev_power, "ev")
        elif self.config.ev_power_sensor:
            readings.ev_power = self._read_sensor(self.config.ev_power_sensor, "ev")

        # EV connection status (from legacy config, not Energy Dashboard)
        readings.ev_connected = self._read_binary_sensor(
            self.config.ev_plug_sensor, "ev_plug"
        )
        readings.ev_charging = self._read_binary_sensor(
            self.config.ev_charging_sensor, "ev_charging"
        )

        # Battery temperature (from legacy config if available)
        if self.config.battery_temperature_sensor:
            readings.battery_temperature = self._read_sensor(
                self.config.battery_temperature_sensor, "battery_temp"
            )

        return readings

    def _read_from_legacy_config(self) -> PowerReadings:
        """Read power values from legacy configuration."""
        readings = PowerReadings()

        # Solar power
        if self.config.solar_power_sensor:
            readings.solar_power = self._read_sensor(
                self.config.solar_power_sensor, "solar"
            )

        # Grid power (hardware convention: negative=import, positive=export)
        if self.config.grid_power_sensor:
            readings.grid_power = self._read_sensor(
                self.config.grid_power_sensor, "grid"
            )

        # Battery power
        if self.config.battery_power_sensor:
            readings.battery_power = self._read_sensor(
                self.config.battery_power_sensor, "battery"
            )

        # Battery SOC
        if self.config.battery_soc_sensor:
            readings.battery_soc = self._read_sensor(
                self.config.battery_soc_sensor, "battery_soc"
            )

        # Battery temperature
        if self.config.battery_temperature_sensor:
            readings.battery_temperature = self._read_sensor(
                self.config.battery_temperature_sensor, "battery_temp"
            )

        # EV power
        if self.config.ev_power_sensor:
            readings.ev_power = self._read_sensor(
                self.config.ev_power_sensor, "ev"
            )

        # EV connection status
        readings.ev_connected = self._read_binary_sensor(
            self.config.ev_plug_sensor, "ev_plug"
        )
        readings.ev_charging = self._read_binary_sensor(
            self.config.ev_charging_sensor, "ev_charging"
        )

        return readings

    def _read_sensor(self, entity_id: Optional[str], name: str) -> float:
        """Read a numeric sensor value."""
        if not entity_id:
            return 0.0

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable", None):
            _LOGGER.debug(f"Sensor {entity_id} ({name}) unavailable")
            return 0.0

        try:
            value = float(state.state)

            # Convert kW to W if needed
            unit = state.attributes.get("unit_of_measurement", "")
            if unit.lower() == "kw":
                value *= 1000

            return value
        except (ValueError, TypeError) as e:
            _LOGGER.debug(f"Could not parse {entity_id} ({name}): {e}")
            return 0.0

    def _read_binary_sensor(self, entity_id: Optional[str], name: str) -> bool:
        """Read a binary sensor value."""
        if not entity_id:
            return False

        state = self.hass.states.get(entity_id)
        if not state:
            _LOGGER.debug(f"Binary sensor {entity_id} ({name}) not found")
            return False

        return state.state == "on"

    def _auto_detect_battery_soc(self, battery_power_entity: str) -> Optional[str]:
        """Auto-detect battery SOC sensor from the same device as the power sensor.

        Only matches entities that share the exact same device prefix as the
        battery power sensor (e.g., battery_1_*). This prevents matching
        mobile phone battery levels or other unrelated batteries.

        Common patterns:
        - Huawei: sensor.battery_1_batterieladung (from battery_1_lade_entladeleistung)
        - Generic: sensor.battery_1_soc, sensor.battery_1_state_of_charge
        """
        if not battery_power_entity or "." not in battery_power_entity:
            return None

        # Extract device prefix: sensor.battery_1_lade_entladeleistung -> battery_1
        entity_name = battery_power_entity.split(".", 1)[1]
        parts = entity_name.split("_")

        # Use first 2 parts as device prefix (e.g., "battery_1")
        # This is strict enough to avoid matching mobile devices
        if len(parts) < 2:
            return None
        prefix = "_".join(parts[:2])

        soc_keywords = ["soc", "state_of_charge", "batterieladung", "battery_level", "charge_level"]
        for keyword in soc_keywords:
            candidate = f"sensor.{prefix}_{keyword}"
            state = self.hass.states.get(candidate)
            if state and state.state not in ("unknown", "unavailable", None):
                try:
                    val = float(state.state)
                    if 0 <= val <= 100:
                        _LOGGER.info("Auto-detected battery SOC: %s = %.0f%%", candidate, val)
                        return candidate
                except (ValueError, TypeError):
                    pass

        return None

    def sensors_ready(self) -> bool:
        """Check if required sensors are available."""
        # Check at least solar or grid sensor is configured and available
        if self._energy_dashboard_config:
            ed = self._energy_dashboard_config
            if ed.solar_power:
                state = self.hass.states.get(ed.solar_power)
                if state and state.state not in ("unknown", "unavailable"):
                    return True
            if ed.grid_power:
                state = self.hass.states.get(ed.grid_power)
                if state and state.state not in ("unknown", "unavailable"):
                    return True
        else:
            if self.config.solar_power_sensor:
                state = self.hass.states.get(self.config.solar_power_sensor)
                if state and state.state not in ("unknown", "unavailable"):
                    return True
            if self.config.grid_power_sensor:
                state = self.hass.states.get(self.config.grid_power_sensor)
                if state and state.state not in ("unknown", "unavailable"):
                    return True

        return False
