"""Sensor reading module for SEM coordinator."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass, replace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .types import FleetEvPower, PowerReadings

_LOGGER = logging.getLogger(__name__)

# Known patterns for split grid power sensors — single source of truth.
# GRID_TRIGGER_HINTS is derived from these and used in __init__.py to
# pre-filter new sensor events. Adding a new brand here automatically
# updates the trigger filter — no second file to keep in sync.
IMPORT_PATTERNS: tuple[str, ...] = (
    "import_from_grid", "pac_to_user", "grid_import", "from_grid_power",
    "power_consumption",      # DSMR/P1 (NL/BE)
    "consumption_from_grid",  # E3DC
    "import_power",           # GivEnergy
    "grid_imported_power",    # Senec
)
EXPORT_PATTERNS: tuple[str, ...] = (
    "export_to_grid", "pac_to_grid", "grid_export", "to_grid_power",
    "power_production",       # DSMR/P1 (NL/BE)
    "export_power",           # GivEnergy
    "grid_exported_power",    # Senec
)
GRID_TRIGGER_HINTS: tuple[str, ...] = tuple(set(IMPORT_PATTERNS + EXPORT_PATTERNS))


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
        self._raw_config = config
        self._energy_dashboard_config = None
        # v1.7.0 / #312: per-PV-string sensors discovered at config-
        # flow time. Empty dict in single-string setups (no discovery
        # hit), populated by ``set_pv_strings`` from
        # ``hardware_detection.discover_pv_strings_from_registry``.
        self._pv_strings: Dict[str, str] = {}
        self._grid_sign_inverted = False
        self._grid_sign_detected = False  # True once sign is reliably determined
        self._grid_sign_votes: int = 0  # Consecutive same-sign detections needed
        self._grid_import_baseline: Optional[float] = None
        self._grid_export_baseline: Optional[float] = None
        self._battery_sign_inverted = False
        self._battery_sign_detected = False
        self._battery_sign_votes: int = 0  # Consecutive same-sign detections needed
        self._battery_charge_baseline: Optional[float] = None
        self._battery_discharge_baseline: Optional[float] = None
        # Track sensor availability transitions (#5: robustness)
        self._sensor_unavailable: set[str] = set()
        # Cache last valid SOC to avoid 0% during sensor gaps
        self._last_valid_soc: float = 0.0
        # Split grid power sensors (Growatt, DSMR, etc.) — discovered on first read.
        # confidence: "same-device" picks are permanently cached; "any-device" picks
        # are re-evaluated each cycle so a late-loading DSMR meter wins once it shows
        # up. See issue #166 startup race.
        self._split_grid_discovery: dict[str, Any] = {
            "import": None,
            "export": None,
            "confidence": None,  # "same-device" | "any-device" | None
            "warned": False,
        }
        self._uses_split_grid: bool = False
        # Warn-once guard for the discovery-*exception* path (#259); distinct from the
        # dict "warned" key (which guards "no sensor found"). Reset on cache invalidate.
        self._split_grid_discovery_warned: bool = False

    def _parse_config(self, config: Dict[str, Any]) -> SensorConfig:
        """Parse configuration into SensorConfig."""
        # Layer 1: config_flow saves as ev_charging_power_sensor, legacy uses ev_power_sensor
        ev_power = config.get("ev_power_sensor") or config.get("ev_charging_power_sensor")

        ev_daily_energy = config.get("ev_daily_energy_sensor")

        return SensorConfig(
            solar_power_sensor=config.get("solar_production_sensor"),
            grid_power_sensor=config.get("grid_power_sensor"),
            battery_power_sensor=config.get("battery_power_sensor"),
            ev_power_sensor=ev_power,
            ev_daily_energy_sensor=ev_daily_energy,
            battery_soc_sensor=config.get("battery_soc_sensor"),
            battery_temperature_sensor=config.get("battery_temperature_sensor"),
            ev_plug_sensor=config.get("ev_connected_sensor") or config.get("ev_plug_sensor", ""),
            ev_charging_sensor=config.get("ev_charging_sensor", ""),
        )

    def _read_pv_string_source(self, slot: str, source) -> float:
        """Read one per-PV-string source (v1.7.0 / #312).

        Handles both registered source shapes:

        - ``str`` → direct power entity. Read the value, return W.
        - ``tuple(V_entity, I_entity)`` → V+I synthesis. Read both,
          return ``V × I`` (W). Used for inverter integrations that
          publish voltage + current per string but no power sensor
          (Huawei Solar Modbus is the motivating case — confirmed
          on HA-PROD 2026-06-01: ``inverter_pv_1_spannung`` and
          ``..._strom`` exist but no ``..._power``).

        Returns 0.0 on any read failure (unavailable sensor, non-
        numeric state, etc.) — same fail-soft contract as
        ``_read_sensor``. The synthesised power is then surfaced
        through the same ``solar_power_per_string`` dict as a
        directly-read value; downstream consumers don't need to
        know the source shape.
        """
        if isinstance(source, tuple):
            v_entity, i_entity = source
            v = self._read_sensor(v_entity, f"pv_{slot}_voltage")
            i = self._read_sensor(i_entity, f"pv_{slot}_current")
            return float(v) * float(i)
        # Direct power entity — keep the legacy fast path.
        return self._read_sensor(source, f"pv_{slot}")

    def set_pv_strings(
        self,
        pv_strings_map: Dict[str, str],
        pv_vi_pairs_map: Optional[Dict[str, "Tuple[str, str]"]] = None,
    ) -> None:
        """Register the discovered per-PV-string sources (v1.7.0 / #312).

        Two sources supported, both feed the same ``_pv_strings`` dict:

        - ``pv_strings_map``: result of
          ``hardware_detection.discover_pv_strings_from_registry`` —
          direct power sensors (``{"pv1_power": "sensor.inverter_pv1_power"}``).
        - ``pv_vi_pairs_map`` (v1.7.0): result of
          ``hardware_detection.discover_pv_string_vi_pairs`` —
          V+I sibling pairs for inverters that publish only voltage
          and current per string (Huawei Solar Modbus, generic
          Modbus drivers). At read time SEM multiplies V × I to
          synthesise the per-string watts. Keys are stripped slot
          labels ``"pv1"`` / ``"pv2"`` / …; values are tuples
          ``(voltage_entity, current_entity)``.

        When the same slot appears in BOTH maps, the direct power
        sensor wins — it's a real measurement rather than a
        computed product, slightly more accurate (the inverter's
        own internal computation accounts for MPPT efficiency etc.).

        Single-string installs pass empty dicts; sensor reads stay
        identical to today.

        Called once from ``SEMCoordinator.async_initialize_energy_dashboard``
        after Energy Dashboard config is read — discovery is a config-
        flow operation, not something to repeat every cycle.
        """
        # Internal shape: ``{slot: str | (V_entity, I_entity)}``. Stored
        # as ``Any`` because the union type is awkward to express in
        # a single dataclass field; the per-cycle read loop tags by
        # ``isinstance(value, tuple)``.
        self._pv_strings: Dict[str, "Any"] = {}

        for slot_key, entity_id in (pv_strings_map or {}).items():
            # Slot keys arrive as ``pv1_power``, ``mppt1_power`` etc.
            # Normalise to ``pv1`` for stable downstream labelling.
            label = slot_key.replace("_power", "").replace("mppt", "pv")
            if entity_id:
                self._pv_strings[label] = entity_id

        for slot_label, vi_pair in (pv_vi_pairs_map or {}).items():
            # Don't override a direct power entry from a parallel
            # V+I match — see contract above.
            if slot_label in self._pv_strings:
                continue
            if vi_pair and len(vi_pair) == 2 and all(vi_pair):
                self._pv_strings[slot_label] = tuple(vi_pair)

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

        # Manual grid-sign override (#352): when the user sets
        # ``grid_sign_invert: True`` the auto-detect path is bypassed
        # entirely and the raw read is negated. Required for Enphase /
        # other installs where the energy-counter heuristic can't
        # stabilise.
        manual_grid_invert = bool(self._raw_config.get("grid_sign_invert", False))
        if manual_grid_invert:
            readings.grid_power = -readings.grid_power
            readings.calculate_derived()
        else:
            # Auto-detect grid sign convention using Energy Dashboard counters.
            # SEM convention: negative = import, positive = export.
            # Compares power sensor sign against import/export energy counter
            # changes to determine if negation is needed.
            needs_negate = self._detect_grid_sign(readings)

            if needs_negate:
                readings.grid_power = -readings.grid_power
                readings.calculate_derived()

        # Auto-detect battery sign convention using Energy Dashboard counters.
        # SEM convention: positive = charge, negative = discharge.
        battery_needs_negate = self._detect_battery_sign(readings)

        if battery_needs_negate:
            readings.battery_power = -readings.battery_power
            # #404: the autodetect previously flipped only the cached fleet
            # field, leaving each ``readings.batteries[bid].power_w`` with
            # its raw un-flipped value. Downstream the per-battery status
            # string in ``types.py:1077-1087`` then reported "discharging"
            # while batteries were physically charging — exactly
            # RienduPre's Growatt-multi-battery symptom (fleet correct,
            # per-battery tiles inverted). Widen the flip to cover every
            # per-battery dict entry so the autodetect's scope matches
            # the canonical-convention contract.
            # ``BatteryPower`` is a frozen dataclass — replace each entry
            # with a new one carrying the negated ``power_w`` rather than
            # mutating in place.
            for bid, bp in list(readings.batteries.items()):
                readings.batteries[bid] = replace(bp, power_w=-bp.power_w)
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

        if detected is None:
            return self._grid_sign_inverted

        # Require 3 consecutive consistent detections before locking in.
        # Prevents false sign flips from transient energy counter jitter
        # after reboots.
        if not self._grid_sign_detected:
            if detected == (self._grid_sign_votes > 0):
                self._grid_sign_votes += 1 if detected else -1
            else:
                self._grid_sign_votes = 1 if detected else -1

            if abs(self._grid_sign_votes) >= 3:
                self._grid_sign_inverted = detected
                self._grid_sign_detected = True
                _LOGGER.info(
                    "Grid sign detected from Energy Dashboard counters: %s "
                    "(power=%.0fW, import_delta=%.3f, export_delta=%.3f)",
                    "negating (HA convention)" if detected else "no correction (SEM convention)",
                    power, import_delta, export_delta,
                )

        return self._grid_sign_inverted

    def _detect_battery_sign(self, readings: PowerReadings) -> bool:
        """Detect if battery power needs negation using Energy Dashboard counters.

        Compares the power sensor's sign against which energy counter
        (charge or discharge) is increasing. SEM convention: positive = charge,
        negative = discharge.

        This enables automatic support for inverters with opposite battery
        sign conventions (Enphase, GoodWe, Tesla Powerwall, Sunsynk/DEYE).

        Returns True if battery_power should be negated.
        """
        ed = self._energy_dashboard_config
        if not ed:
            return False

        charge_entity = ed.battery_charge_energy
        discharge_entity = ed.battery_discharge_energy

        if not charge_entity or not discharge_entity:
            return False

        # Need meaningful power to detect (ignore noise)
        power = readings.battery_power
        if abs(power) < 100:
            return self._battery_sign_inverted  # Keep last known state

        # Read energy counter values
        charge_state = self.hass.states.get(charge_entity)
        discharge_state = self.hass.states.get(discharge_entity)

        if not charge_state or charge_state.state in ("unknown", "unavailable"):
            return self._battery_sign_inverted
        if not discharge_state or discharge_state.state in ("unknown", "unavailable"):
            return self._battery_sign_inverted

        try:
            charge_val = float(charge_state.state)
            discharge_val = float(discharge_state.state)
        except (ValueError, TypeError):
            return self._battery_sign_inverted

        # First call: store baselines, don't correct yet
        if self._battery_charge_baseline is None:
            self._battery_charge_baseline = charge_val
            self._battery_discharge_baseline = discharge_val
            return False

        charge_delta = charge_val - self._battery_charge_baseline
        discharge_delta = discharge_val - self._battery_discharge_baseline

        # Update baselines for next cycle
        self._battery_charge_baseline = charge_val
        self._battery_discharge_baseline = discharge_val

        # Determine convention from correlation:
        # power > 0 + charge growing → SEM convention (+ = charge) → no negate
        # power > 0 + discharge growing → opposite convention (+ = discharge) → negate
        # power < 0 + charge growing → opposite convention (- = charge) → negate
        # power < 0 + discharge growing → SEM convention (- = discharge) → no negate
        detected = None
        if charge_delta > 0.001 and discharge_delta < 0.001:
            # Charge counter increasing
            detected = power < 0  # If power negative during charge → negate
        elif discharge_delta > 0.001 and charge_delta < 0.001:
            # Discharge counter increasing
            detected = power > 0  # If power positive during discharge → negate

        if detected is None:
            return self._battery_sign_inverted

        # Require 3 consecutive consistent detections before locking in.
        # This prevents false sign flips from transient energy counter
        # jitter after reboots (e.g. both counters ticking simultaneously
        # during HA recorder settling).
        if not self._battery_sign_detected:
            if detected == (self._battery_sign_votes > 0):
                # Same direction as previous votes (True=negate votes positive)
                self._battery_sign_votes += 1 if detected else -1
            else:
                # Direction changed — reset
                self._battery_sign_votes = 1 if detected else -1

            if abs(self._battery_sign_votes) >= 3:
                self._battery_sign_inverted = detected
                self._battery_sign_detected = True
                _LOGGER.info(
                    "Battery sign detected from Energy Dashboard counters: %s "
                    "(power=%.0fW, charge_delta=%.3f, discharge_delta=%.3f)",
                    "negating (opposite convention)" if detected else "no correction (SEM convention)",
                    power, charge_delta, discharge_delta,
                )

        return self._battery_sign_inverted

    def _read_sensors_sum(self, entity_ids: list, name: str) -> float:
        """Sum values from multiple sensors of the same type."""
        return sum(self._read_sensor(eid, name) for eid in entity_ids)

    def _read_from_energy_dashboard(self) -> PowerReadings:
        """Read power values from Energy Dashboard configured sensors."""
        ed = self._energy_dashboard_config
        readings = PowerReadings()

        # Solar power — sum all inverters if multiple configured.
        # v1.7.0 arch/multi-inverter-battery-primary: also populate
        # the per-inverter dict so downstream consumers can attribute
        # by inverter (multi-inverter installs only — single-inverter
        # leaves the dict empty and falls back to readings.solar_power).
        from .charger_types import InverterPower
        if len(ed.solar_power_list) > 1:
            total = 0.0
            for entity in ed.solar_power_list:
                w = self._read_sensor(entity, "solar")
                total += w
                readings.inverters[entity] = InverterPower(
                    inverter_id=entity, power_w=w, name=entity,
                )
            readings.solar_power = total
        elif ed.solar_power:
            readings.solar_power = self._read_sensor(ed.solar_power, "solar")

        # v1.7.0 / #312: per-PV-string power. Gated on len ≥ 2 — single-
        # string setups get nothing here and downstream readers fall
        # back to ``readings.solar_power``. The discovery already
        # capped the slot count at 4, so the loop is O(≤4). Sources
        # may be either a direct power entity (str) or a V+I sibling
        # pair (tuple) — the per-cycle helper handles both.
        if len(self._pv_strings) >= 2:
            for slot, source in self._pv_strings.items():
                readings.solar_power_per_string[slot] = self._read_pv_string_source(
                    slot, source,
                )

        # Grid power from Energy Dashboard.
        # Three modes:
        # 0. Manual override: user sets grid_import/export_power_entity in config
        # 1. Combined sensor (Huawei, SolarEdge, Fronius): single stat_rate sensor
        #    SEM convention: negative = import, positive = export
        #    read_power() auto-detects and corrects the sign after calculate_derived()
        # 2. Split sensors (Growatt, DSMR/P1): separate import + export power sensors
        #    Both always positive — SEM calculates: grid_power = export - import
        manual_import = self._raw_config.get("grid_import_power_entity")
        manual_export = self._raw_config.get("grid_export_power_entity")
        if manual_import or manual_export:
            # Manual override — user explicitly set grid power sensors
            import_w = self._read_sensor(manual_import, "grid_import") if manual_import else 0.0
            export_w = self._read_sensor(manual_export, "grid_export") if manual_export else 0.0
            readings.grid_power = export_w - import_w
            self._grid_sign_detected = True
        elif len(ed.grid_power_list) > 1:
            # Multiple grid power sensors — sum all (e.g. multi-meter setups)
            readings.grid_power = self._read_sensors_sum(ed.grid_power_list, "grid")
        elif ed.grid_import_power:
            readings.grid_power = self._read_sensor(ed.grid_import_power, "grid")
        elif not ed.grid_import_power and ed.grid_import_energy:
            # No combined power sensor — try to find split import/export power sensors
            # from the same device as the energy sensors.
            # Re-run discovery unless we've already locked in a same-device match;
            # any-device matches stay re-evaluated so a late-loading DSMR meter
            # (issue #166) takes over within one update interval.
            self._uses_split_grid = True
            disc = self._split_grid_discovery
            if disc["confidence"] != "same-device":
                imp, exp, conf = self._discover_split_grid_power(ed)
                disc["import"] = imp
                disc["export"] = exp
                disc["confidence"] = conf
            if disc["import"]:
                import_w = self._read_sensor(disc["import"], "grid_import")
                export_w = self._read_sensor(disc["export"], "grid_export") if disc["export"] else 0.0
                # SEM convention: negative = import, positive = export
                readings.grid_power = export_w - import_w
                self._grid_sign_detected = True  # No sign correction needed
            elif not disc["warned"]:
                disc["warned"] = True
                _LOGGER.warning(
                    "No grid power sensor found (no combined and no split import/export). "
                    "Grid power will be 0. Check Energy Dashboard grid configuration."
                )

        # Battery power — sum all battery units if multiple configured.
        # v1.7.0 arch: also populate the per-battery dict so multi-
        # battery installs can be attributed per-unit. Single-battery
        # leaves the dict empty and downstream consumers fall back to
        # readings.battery_power.
        # Sign auto-detection (in read_power → _detect_battery_sign)
        # uses the primary sensor and assumes all units share the same
        # sign convention.
        from .charger_types import BatteryPower
        if len(ed.battery_power_list) > 1:
            total = 0.0
            # Phase A of per-battery card mirror: assign short stable
            # slugs (``b1``, ``b2`` …) keyed by the Energy Dashboard
            # battery_power_list order so the SEM-side sensor IDs are
            # predictable at setup time (``sensor.sem_battery_b1_power``
            # rather than echoing the source entity). The full source
            # entity stays in ``name`` for display + as the friendly
            # name override the card uses.
            for idx, entity in enumerate(ed.battery_power_list):
                bid = f"b{idx + 1}"
                w = self._read_sensor(entity, "battery")
                total += w
                # Per-battery SOC via the same auto-detect heuristic
                # the fleet average uses. Falls through to 0.0 when no
                # matching SOC sensor is discoverable — card displays
                # ``—`` in that case rather than fabricating a value.
                soc_entity = self._auto_detect_battery_soc(entity)
                soc_val = 0.0
                if soc_entity:
                    s = self._read_sensor(
                        soc_entity, "battery_soc", allow_none=True,
                    )
                    if s is not None and s >= 0:
                        soc_val = s
                readings.batteries[bid] = BatteryPower(
                    battery_id=bid, power_w=w, soc_pct=soc_val, name=entity,
                )
            readings.battery_power = total
        elif ed.battery_power:
            readings.battery_power = self._read_sensor(ed.battery_power, "battery")

        # Battery SOC — from config, or auto-detect and average across all units
        # Use allow_none so 0% SOC is distinguishable from "unavailable"
        soc_val = None
        if self.config.battery_soc_sensor:
            soc_val = self._read_sensor(
                self.config.battery_soc_sensor, "battery_soc", allow_none=True,
            )
        elif len(ed.battery_power_list) > 1:
            soc_val = self._read_battery_soc_average(ed.battery_power_list) or None
        elif ed.battery_power:
            soc_entity = self._auto_detect_battery_soc(ed.battery_power)
            if soc_entity:
                soc_val = self._read_sensor(soc_entity, "battery_soc", allow_none=True)

        if soc_val is not None:
            readings.battery_soc = soc_val
            self._last_valid_soc = soc_val
        else:
            # Use last known SOC to avoid charging logic seeing 0% during sensor gaps
            readings.battery_soc = self._last_valid_soc
            readings.battery_soc_unavailable = True

        # EV power — sum all chargers if multi-charger (#193), else single sensor.
        # v1.6.9 also populates ``ev_power_per_charger`` so the flow calculator
        # can produce per-charger flow attribution (closes #316 family).
        #
        # Note: chargers without a configured ``ev_charging_power_sensor``
        # (misconfig) are excluded from both ``ev_power_per_charger``
        # AND the fleet sum. Downstream consumers that iterate
        # ``config['ev_chargers']`` and look up the dict must guard
        # ``.get(cid)`` rather than ``[cid]`` — a charger that's
        # configured but has no power sensor will be silently absent.
        ev_chargers = self._raw_config.get("ev_chargers", [])
        if len(ev_chargers) > 1:
            total_ev = 0.0
            for charger_cfg in ev_chargers:
                cid = charger_cfg.get("id")
                cps = charger_cfg.get("ev_charging_power_sensor")
                if cps:
                    cw = self._read_sensor(cps, "ev")
                    total_ev += cw
                    if cid:
                        # Per-charger draw in watts, exposed for
                        # ``flow_calculator`` per-charger split.
                        readings.ev_power_per_charger[cid] = cw
            readings.ev_power = FleetEvPower(total_ev)
        elif ed.ev_power:
            readings.ev_power = FleetEvPower(self._read_sensor(ed.ev_power, "ev"))
        elif self.config.ev_power_sensor:
            readings.ev_power = FleetEvPower(
                self._read_sensor(self.config.ev_power_sensor, "ev")
            )

        # EV connection status — per-charger OR'd for global (#193)
        ev_chargers = self._raw_config.get("ev_chargers", [])
        if len(ev_chargers) > 1:
            any_connected = False
            any_charging = False
            for charger_cfg in ev_chargers:
                conn_sensor = charger_cfg.get("ev_connected_sensor")
                chrg_sensor = charger_cfg.get("ev_charging_sensor")
                if conn_sensor and self._read_binary_sensor(conn_sensor, "ev_plug"):
                    any_connected = True
                if chrg_sensor and self._read_binary_sensor(chrg_sensor, "ev_charging"):
                    any_charging = True
            readings.ev_connected = any_connected
            readings.ev_charging = any_charging
        else:
            readings.ev_connected = self._read_binary_sensor(
                self.config.ev_plug_sensor, "ev_plug"
            )
            readings.ev_charging = self._read_binary_sensor(
                self.config.ev_charging_sensor, "ev_charging"
            )

        # Physics-based defence against upstream plug-sensor quirks.
        # Reported 2026-05-29 on PROD: across an HA restart with a car
        # actively charging, ``binary_sensor.keba_p30_plug`` reported
        # "off" for 67 minutes while ``binary_sensor.keba_p30_charging_state``
        # cycled on/off through 15 transitions and the charging-power
        # sensor peaked at 8 kW. SEM correctly read the lying plug
        # sensor, returned "EV disconnected", and stopped supervising.
        # The KEBA kept its last commanded current and the car drew
        # ~6 kWh past the Max ceiling because SEM wasn't even watching.
        #
        # Current cannot flow without a connection. If we see active
        # charging power (>100 W rules out KEBA's own standby draw) or
        # the charging_state sensor reports True, infer connection — the
        # plug sensor is wrong.
        if not readings.ev_connected and (
            readings.ev_charging or readings.ev_power > 100
        ):
            _LOGGER.warning(
                "ev_connected inferred from physics: plug sensor reported off but "
                "ev_power=%.0fW / ev_charging=%s. Treating as connected. (Upstream "
                "charger-integration bug protection — see #285+1 in CHANGELOG.)",
                readings.ev_power, readings.ev_charging,
            )
            readings.ev_connected = True

        # Battery temperature (from legacy config if available)
        if self.config.battery_temperature_sensor:
            readings.battery_temperature = self._read_sensor(
                self.config.battery_temperature_sensor, "battery_temp"
            )

        return readings

    def _discover_split_grid_power(self, ed) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Discover separate import/export power sensors for setups without combined grid power.

        Supported naming patterns:
        - Growatt: *_import_from_grid / *_export_to_grid
        - Growatt TLX: *_pac_to_user* / *_pac_to_grid*
        - DSMR/P1 (NL/BE): *_power_consumption / *_power_production
        - E3DC: *_consumption_from_grid / *_export_to_grid
        - GivEnergy: *_import_power / *_export_power
        - Senec: *_grid_imported_power / *_grid_exported_power
        - Generic: *_grid_import / *_grid_export

        Prefers sensors on the same device as the grid energy sensors to avoid
        false positives (e.g. heat pump power_consumption vs meter power_consumption).

        Returns (import_entity, export_entity, confidence) where confidence is
        "same-device" if either side came from a device matching the grid energy
        sensor, "any-device" if matched by pattern only, or None if nothing matched.
        """
        import_patterns = IMPORT_PATTERNS
        export_patterns = EXPORT_PATTERNS

        try:
            # Get device_id of grid energy sensor for same-device preference
            grid_device_id = self._get_device_for_entity(ed.grid_import_energy)

            # Two-pass: same-device matches are preferred over any-device matches
            same_device = {"import": None, "export": None}
            any_device = {"import": None, "export": None}

            for state in self.hass.states.async_all("sensor"):
                eid = state.entity_id.lower()
                attrs = state.attributes
                # Must be a power sensor
                if attrs.get("device_class") != "power" and attrs.get("unit_of_measurement") not in ("W", "kW"):
                    continue

                is_import = any(p in eid for p in import_patterns)
                is_export = any(p in eid for p in export_patterns)
                if not is_import and not is_export:
                    continue

                # Check if sensor is on the same device as grid energy
                on_same_device = False
                if grid_device_id:
                    sensor_device_id = self._get_device_for_entity(state.entity_id)
                    on_same_device = sensor_device_id == grid_device_id

                if is_import:
                    if on_same_device:
                        same_device["import"] = state.entity_id
                    elif not any_device["import"]:
                        any_device["import"] = state.entity_id
                if is_export:
                    if on_same_device:
                        same_device["export"] = state.entity_id
                    elif not any_device["export"]:
                        any_device["export"] = state.entity_id

            # Prefer same-device matches, fall back to any match
            import_power = same_device["import"] or any_device["import"]
            export_power = same_device["export"] or any_device["export"]

            # "same-device" only if every resolved side came from the grid device.
            # A mix (one same-device, one any-device) stays "any-device" so
            # re-discovery can upgrade the any-device side later.
            import_is_same = (import_power is None or import_power == same_device["import"])
            export_is_same = (export_power is None or export_power == same_device["export"])
            if import_power or export_power:
                confidence = "same-device" if (import_is_same and export_is_same) else "any-device"
                _LOGGER.info(
                    "Discovered split grid power sensors (%s): import=%s, export=%s",
                    confidence, import_power, export_power,
                )
            else:
                confidence = None
                _LOGGER.debug("No split grid power sensors found")

        except Exception as e:
            # Surface once at warning (#259): a discovery failure leaves split-meter
            # setups (Growatt, P1/DSMR) reading 0 grid power with no signal. Warn on
            # the first failure, then drop to debug so we don't spam every cycle.
            if not self._split_grid_discovery_warned:
                _LOGGER.warning("Split grid power discovery failed: %s", e)
                self._split_grid_discovery_warned = True
            else:
                _LOGGER.debug("Split grid power discovery failed: %s", e)
            import_power = None
            export_power = None
            confidence = None

        return import_power, export_power, confidence

    def invalidate_split_grid_cache(self) -> None:
        """Reset split-grid discovery so the next read_power() rediscovers.

        Called from __init__.py when a new sensor appears or after HA has fully
        started. Same-device locks are wiped along with any-device picks.
        """
        self._split_grid_discovery = {
            "import": None,
            "export": None,
            "confidence": None,
            "warned": self._split_grid_discovery.get("warned", False),
        }
        # Re-allow the discovery-exception warning after a rediscovery (#259) — circumstances
        # have changed (e.g. a new sensor appeared), so a fresh failure is worth surfacing.
        self._split_grid_discovery_warned = False

    def _get_device_for_entity(self, entity_id: str) -> Optional[str]:
        """Get device_id for an entity from the entity registry."""
        if not entity_id:
            return None
        try:
            registry = er.async_get(self.hass)
            entry = registry.async_get(entity_id)
            return entry.device_id if entry else None
        except Exception as e:
            _LOGGER.debug("Device lookup failed for %s: %s (#259)", entity_id, e)
            return None

    def _read_battery_soc_average(self, battery_power_entities: list) -> float:
        """Average SOC across multiple battery units.

        Auto-detects the SOC sensor for each battery power sensor and
        returns the simple average of all valid readings.
        """
        soc_values = []
        for batt_power in battery_power_entities:
            soc_entity = self._auto_detect_battery_soc(batt_power)
            if soc_entity:
                val = self._read_sensor(soc_entity, "battery_soc")
                if val is not None and val >= 0:
                    soc_values.append(val)
        if soc_values:
            return sum(soc_values) / len(soc_values)
        return 0.0

    def _read_from_legacy_config(self) -> PowerReadings:
        """Read power values from legacy configuration."""
        readings = PowerReadings()

        # Solar power
        if self.config.solar_power_sensor:
            readings.solar_power = self._read_sensor(
                self.config.solar_power_sensor, "solar"
            )

        # v1.7.0 / #312: per-PV-string power on the legacy path too.
        # Same len ≥ 2 gate as the Energy Dashboard path.
        if len(self._pv_strings) >= 2:
            for slot, entity_id in self._pv_strings.items():
                readings.solar_power_per_string[slot] = self._read_sensor(
                    entity_id, f"pv_{slot}",
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

        # Battery SOC — use allow_none to distinguish 0% from unavailable
        if self.config.battery_soc_sensor:
            soc_val = self._read_sensor(
                self.config.battery_soc_sensor, "battery_soc", allow_none=True,
            )
            if soc_val is not None:
                readings.battery_soc = soc_val
                self._last_valid_soc = soc_val
            else:
                readings.battery_soc = self._last_valid_soc
                readings.battery_soc_unavailable = True

        # Battery temperature
        if self.config.battery_temperature_sensor:
            readings.battery_temperature = self._read_sensor(
                self.config.battery_temperature_sensor, "battery_temp"
            )

        # EV power — sum all chargers if multi-charger (#193)
        ev_chargers = self._raw_config.get("ev_chargers", [])
        if len(ev_chargers) > 1:
            total_ev = 0.0
            for charger_cfg in ev_chargers:
                cps = charger_cfg.get("ev_charging_power_sensor")
                if cps:
                    total_ev += self._read_sensor(cps, "ev")
            readings.ev_power = FleetEvPower(total_ev)
        elif self.config.ev_power_sensor:
            readings.ev_power = FleetEvPower(
                self._read_sensor(self.config.ev_power_sensor, "ev")
            )

        # EV connection status — per-charger OR'd for global (#193)
        ev_chargers_leg = self._raw_config.get("ev_chargers", [])
        if len(ev_chargers_leg) > 1:
            any_connected = False
            any_charging = False
            for charger_cfg in ev_chargers_leg:
                conn_sensor = charger_cfg.get("ev_connected_sensor")
                chrg_sensor = charger_cfg.get("ev_charging_sensor")
                if conn_sensor and self._read_binary_sensor(conn_sensor, "ev_plug"):
                    any_connected = True
                if chrg_sensor and self._read_binary_sensor(chrg_sensor, "ev_charging"):
                    any_charging = True
            readings.ev_connected = any_connected
            readings.ev_charging = any_charging
        else:
            readings.ev_connected = self._read_binary_sensor(
                self.config.ev_plug_sensor, "ev_plug"
            )
            readings.ev_charging = self._read_binary_sensor(
                self.config.ev_charging_sensor, "ev_charging"
            )

        # Physics-based defence against upstream plug-sensor quirks.
        # Same logic as the energy-dashboard path — see comment there for
        # the full PROD repro (#285+1).
        if not readings.ev_connected and (
            readings.ev_charging or readings.ev_power > 100
        ):
            _LOGGER.warning(
                "ev_connected inferred from physics: plug sensor reported off but "
                "ev_power=%.0fW / ev_charging=%s. Treating as connected.",
                readings.ev_power, readings.ev_charging,
            )
            readings.ev_connected = True

        return readings

    def _read_sensor(
        self, entity_id: Optional[str], name: str, *, allow_none: bool = False,
    ) -> float | None:
        """Read a numeric sensor value.

        Args:
            entity_id: HA entity ID to read.
            name: Human label for logging.
            allow_none: If True, return None when sensor is unavailable
                        instead of 0.0.  Use for sensors where 0 is a
                        valid reading (e.g. battery_soc: 0% vs unavailable).
        """
        if not entity_id:
            return None if allow_none else 0.0

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable", None):
            _LOGGER.debug(f"Sensor {entity_id} ({name}) unavailable")
            # Track unavailability for transition detection
            self._sensor_unavailable.add(entity_id)
            return None if allow_none else 0.0

        try:
            value = float(state.state)

            # Convert kW to W if needed
            unit = state.attributes.get("unit_of_measurement", "")
            if unit.lower() == "kw":
                value *= 1000

            # Detect transition from unavailable → available
            if entity_id in self._sensor_unavailable:
                self._sensor_unavailable.discard(entity_id)
                _LOGGER.info(
                    "Sensor %s (%s) recovered — now reading %.1f",
                    entity_id, name, value,
                )

            return value
        except (ValueError, TypeError) as e:
            _LOGGER.debug(f"Could not parse {entity_id} ({name}): {e}")
            return None if allow_none else 0.0

    def _read_binary_sensor(self, entity_id: Optional[str], name: str) -> bool:
        """Read a binary sensor or status sensor value.

        Supports both binary_sensor (on/off) and regular sensor entities
        used by chargers like Easee that expose status as a sensor (#68).
        """
        if not entity_id:
            return False

        state = self.hass.states.get(entity_id)
        if not state:
            _LOGGER.debug("Sensor %s (%s) not found", entity_id, name)
            return False

        s = state.state.lower()
        if s == "on":
            return True
        if s in ("off", "unknown", "unavailable"):
            return False
        # Regular sensor status values (Easee, Wallbox, OCPP, Ohme, Alfen, etc.)
        if name == "ev_plug" and s in (
            "connected", "ready_to_charge", "awaiting_start",
            "awaiting_authorization", "charging", "completed", "ready",
            # OCPP: Preparing/Charging/SuspendedEV mean EV is plugged in
            "preparing", "suspended_ev", "suspended_evse", "finishing",
            # Ohme
            "plugged in",
            # Alfen
            "ev connected", "charging power on",
            # Peblar
            # ("connected" already listed above)
            # Blue Current
            # ("connected" already listed above)
        ):
            return True
        if name == "ev_charging" and s in (
            "charging",
            # Alfen
            "charging power on",
        ):
            return True
        # Numeric: treat > 0 as True (e.g. power sensor as charging indicator)
        try:
            return float(s) > 0
        except (ValueError, TypeError):
            pass
        return False

    def _auto_detect_battery_soc(self, battery_power_entity: str) -> Optional[str]:
        """Auto-detect battery SOC sensor from the same device as the power sensor.

        Strategy:
        1. Try prefix-based matching (fast, works for Huawei/generic)
        2. If that fails, look up the device via entity registry and search
           all sensor entities on the same device for SOC keywords (#174)

        Common patterns:
        - Huawei: sensor.battery_1_batterieladung (from battery_1_lade_entladeleistung)
        - GoodWe: sensor.goodwe_battery_soc (from sensor.goodwe_pbattery1)
        - Generic: sensor.battery_1_soc, sensor.battery_1_state_of_charge
        """
        if not battery_power_entity or "." not in battery_power_entity:
            return None

        soc_keywords = ["soc", "state_of_charge", "batterieladung", "battery_level", "charge_level"]

        # Strategy 1: Prefix-based matching (fast path)
        entity_name = battery_power_entity.split(".", 1)[1]
        parts = entity_name.split("_")

        if len(parts) >= 2:
            prefix = "_".join(parts[:2])
            result = self._try_soc_candidates(prefix, soc_keywords)
            if result:
                return result

        # Strategy 2: Device registry lookup — find all entities on the same
        # device and check for SOC keywords. This handles integrations where
        # battery power and SOC have different name prefixes (e.g., GoodWe:
        # sensor.goodwe_pbattery1 vs sensor.goodwe_battery_soc)
        try:
            registry = er.async_get(self.hass)
            power_entry = registry.async_get(battery_power_entity)
            if power_entry and power_entry.device_id:
                device_entities = er.async_entries_for_device(
                    registry, power_entry.device_id
                )
                for entity_entry in device_entities:
                    if entity_entry.domain != "sensor":
                        continue
                    eid = entity_entry.entity_id
                    eid_lower = eid.lower()
                    state = self.hass.states.get(eid)
                    # Accept by name keyword OR by the canonical SOC signature:
                    # device_class "battery" + unit "%". The latter catches
                    # integrations that name SOC unconventionally — e.g. SolaX
                    # solax-modbus calls it "Battery Capacity"
                    # (sensor.*_battery_capacity), which no SOC keyword matches (#250).
                    by_keyword = any(kw in eid_lower for kw in soc_keywords)
                    by_signature = False
                    if state is not None:
                        dc = state.attributes.get("device_class")
                        unit = (state.attributes.get("unit_of_measurement") or "").strip()
                        by_signature = dc == "battery" and unit == "%"
                    if by_keyword or by_signature:
                        if state and state.state not in ("unknown", "unavailable", None):
                            try:
                                val = float(state.state)
                                if 0 <= val <= 100:
                                    if not getattr(self, '_battery_soc_logged', False):
                                        _LOGGER.info(
                                            "Auto-detected battery SOC via device registry: %s = %.0f%%",
                                            eid, val,
                                        )
                                        self._battery_soc_logged = True
                                    return eid
                            except (ValueError, TypeError):
                                _LOGGER.debug("Battery SOC candidate %s not numeric: %r (#259)", eid, state.state)
        except Exception as e:
            _LOGGER.debug("Device registry SOC lookup failed: %s", e)

        return None

    def _try_soc_candidates(self, prefix: str, soc_keywords: list) -> Optional[str]:
        """Try prefix + keyword combinations to find SOC entity."""
        for keyword in soc_keywords:
            candidate = f"sensor.{prefix}_{keyword}"
            state = self.hass.states.get(candidate)
            if state and state.state not in ("unknown", "unavailable", None):
                try:
                    val = float(state.state)
                    if 0 <= val <= 100:
                        if not getattr(self, '_battery_soc_logged', False):
                            _LOGGER.info("Auto-detected battery SOC: %s = %.0f%%", candidate, val)
                            self._battery_soc_logged = True
                        return candidate
                except (ValueError, TypeError):
                    _LOGGER.debug("Battery SOC candidate %s not numeric: %r (#259)", candidate, state.state)
        return None

    def auto_detect_battery_capacity_kwh(self) -> Optional[float]:
        """Auto-detect battery rated capacity from inverter sensors (#84).

        Searches for a capacity/rated sensor on the same device as the
        battery power sensor. Returns kWh or None if not found.

        Known patterns:
        - Huawei: sensor.batterien_akkukapazitat (Wh)
        - GoodWe: sensor.goodwe_*_capacity (Wh)
        - SolarEdge: sensor.*_rated_energy (Wh)
        """
        # Try Energy Dashboard battery sensor first, then config
        ed = self._energy_dashboard_config
        battery_entity = None
        if ed:
            battery_entity = ed.battery_power or ed.battery_charge_energy
        if not battery_entity:
            battery_entity = self.config.battery_power_sensor

        if not battery_entity:
            return None

        # Search all sensors for capacity keywords
        capacity_keywords = [
            "akkukapazit", "rated_capacity", "battery_capacity",
            "rated_energy", "nennkapazit", "usable_capacity",
        ]
        for state in self.hass.states.async_all("sensor"):
            eid = state.entity_id
            name = (state.attributes.get("friendly_name") or "").lower()
            if not any(kw in eid.lower() or kw in name for kw in capacity_keywords):
                continue
            if state.state in ("unknown", "unavailable", None):
                continue
            unit = (state.attributes.get("unit_of_measurement") or "").lower()
            dc = state.attributes.get("device_class")
            # Skip SOC sensors: "Battery Capacity" matches the keyword above but on
            # SolaX (and others) it is the SOC percentage, not rated energy. A 80%
            # SOC would otherwise be misread as 80 kWh of rated capacity (#250).
            if dc == "battery" or unit in ("%", "percent"):
                continue
            try:
                value = float(state.state)
                if value <= 0:
                    continue
                if unit == "wh" or value > 500:
                    value /= 1000  # Wh → kWh
                if 1 <= value <= 200:  # Sanity: 1-200 kWh
                    _LOGGER.info(
                        "Auto-detected battery capacity: %s = %.1f kWh",
                        eid, value,
                    )
                    return value
            except (ValueError, TypeError):
                continue

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
