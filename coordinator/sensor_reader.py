"""Sensor reading module for SEM coordinator."""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, Optional
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .types import FleetEvPower, PowerReadings
from .sign_audit import CounterCorrelationAudit

_LOGGER = logging.getLogger(__name__)

# #593 — battery lifetime-cycle sensor autodetect keywords (EN + DE + common
# integration names). Extend this list as new hardware is reported — that is how
# the supported-hardware autodetect is maintained (see the manual override in
# the coordinator as the last-resort fallback).
_CYCLE_KEYWORDS = (
    "cycles", "cycle_count", "charge_cycles", "battery_cycles",
    "zyklen", "ladezyklen", "lade_zyklen",   # Sonnenbatterie / Huawei (DE)
    "full_cycles", "equivalent_full_cycles",
)
_CYCLES_UNSET = object()  # cache sentinel distinct from a None result

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

# #461 brand-lookup tier: deterministic grid-sign convention per
# integration. The grid-power sensor's own ``platform`` (HA integration
# domain) tells us the sign convention with certainty for well-tested
# brands — far stronger than inferring it. Value = ``needs_negate``:
#   False → meter reports +=export already (SEM convention, no negation)
#   True  → meter reports +=import (HA convention, negate to SEM)
# Mirrors the pipeline patterns in tests/test_split_grid_integration.py
# and the CLAUDE.md sign table. Only HIGH-CONFIDENCE entries belong here:
# an unknown/mismatched platform simply falls through to the solar /
# counter detectors, but a WRONG entry here would mis-seed a real user
# (the 00e449c lesson) — so when in doubt, leave a brand out. The seed is
# still overridable by the solar detector (ground truth) and the manual
# flip, so it is a strong default, not an immutable verdict.
PLATFORM_GRID_SIGN_INVERT: dict[str, bool] = {
    # Pattern A — grid +=export (SEM), no negation
    "huawei_solar": False,
    "sma": False,
    # Pattern B — grid +=import (HA), negate
    "fronius": True,
    "enphase_envoy": True,
    "powerwall": True,
    "solaredge": True,
    "kostal_plenticore": True,
    # Pattern C — grid +=export, no negation
    "goodwe": False,
    # Pattern D — grid +=import, negate
    "solax": True,
    # Deye via hass-deyecloud (#554): totalgridpower reports +=import /
    # −=export — live-verified from the reporter's diagnostics + observed
    # behavior (−4.9 kW while exporting, SEM read it as import until the
    # manual flip). HIGH-CONFIDENCE: platform string from his diagnostics.
    "deyecloud": True,
}

# #588 battery-sign brand-lookup tier — same semantics as PLATFORM_GRID_SIGN_INVERT
# but for the battery power sensor. Value = ``needs_negate``:
#   False → battery +=charge (SEM convention, no negation)
#   True  → battery +=discharge (opposite convention, negate to SEM)
# Only HIGH-CONFIDENCE entries belong here — same lesson as grid: a wrong
# entry here mis-seeds a real user, so when in doubt leave a brand out.
# The seed is overridable by the counter detector and the manual user flip.
PLATFORM_BATTERY_SIGN_INVERT: dict[str, bool] = {
    # SEM convention (+=charge): no negation
    "huawei_solar": False,
    "sma": False,
    # Opposite convention (+=discharge): negate
    "goodwe": True,
    "powerwall": True,
    "enphase_envoy": True,
    "solax": True,
}


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
    inverter_temperature_sensor: Optional[str] = None

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
        # (#564) autodetected battery temperature sibling (cached) + probe throttle
        self._battery_temp_entity: Optional[str] = None
        self._battery_temp_probe_mono: float = -1e9
        # (#564) same for the inverter temperature sibling
        self._inverter_temp_entity: Optional[str] = None
        self._inverter_temp_probe_mono: float = -1e9
        # v1.7.0 / #312: per-PV-string sensors discovered at config-
        # flow time. Empty dict in single-string setups (no discovery
        # hit), populated by ``set_pv_strings`` from
        # ``hardware_detection.discover_pv_strings_from_registry``.
        self._pv_strings: Dict[str, str] = {}
        self._pv_string_names: Dict[str, str] = {}  # (#566) slot -> custom name
        self._grid_sign_inverted = False
        self._grid_sign_detected = False  # True once sign is reliably determined
        # #461: accumulated sign-of-correlation evidence. The old ±1 vote
        # locked after three *consecutive* instantaneous matches — and a
        # contradicting sample only reset the run counter to ±1, never the
        # body of evidence. So a meter that was 55/45 inconsistent (come-up
        # counter replay, battery-flip transients) could still lock the
        # WRONG sign on any 3-in-a-row run. Replaced with a magnitude-
        # weighted accumulator scored by CONFIDENCE over ALL samples:
        #   +weight → SEM convention (no negate),  −weight → HA (negate),
        #   weight = |grid_power|.
        # Lock only when (a) at least MIN_SAMPLES directional cycles have
        # contributed AND (b) the dominant direction holds >= MIN_CONFIDENCE
        # of all accumulated magnitude. A consistent install (every sample
        # agrees → confidence 1.0) still locks in 3 cycles exactly as
        # before; an inconsistent one stays in passthrough indefinitely and
        # surfaces via diag rather than locking a wrong sign. (A genuinely
        # swapped/net-only meter reads consistently wrong and is undecidable
        # from software — that is what the one-tap flip override is for.)
        self._grid_sign_evidence: float = 0.0
        self._grid_sign_total_mag: float = 0.0
        self._grid_sign_samples: int = 0
        # Direction witnesses — diagnostics only (NOT a lock gate; a single-
        # direction install, e.g. import-only overnight, must still lock).
        self._grid_sign_seen_import: bool = False
        self._grid_sign_seen_export: bool = False
        self._GRID_SIGN_MIN_SAMPLES: int = 3
        self._GRID_SIGN_MIN_CONFIDENCE: float = 0.75
        # #461: solar-anchored grid-sign detection — the AUTHORITATIVE
        # primary for solar installs. Solar production has no sign
        # ambiguity, so the co-movement of the RAW grid reading with solar
        # reveals the grid convention directly and INDEPENDENTLY of the
        # Energy-Dashboard counters (which can be mis-mapped — the root
        # cause of RienduPre's #461 Sessy-P1 wrong lock):
        #   grid rises with solar      → +export meter (SEM) → no negate
        #   grid falls as solar rises  → +import meter (HA)  → negate
        # Only large solar swings vote, so home-load jitter can't flip the
        # correlation. This locks BEFORE the counter path for solar
        # installs and can OVERRIDE a wrong counter-derived lock once it is
        # highly confident and sustained (hard-gated self-heal). A
        # correctly-signed install computes the SAME sign as its current
        # lock → agreement → never flipped (the 00e449c safety lesson).
        self._grid_sign_solar_evidence: float = 0.0
        self._grid_sign_solar_mag: float = 0.0
        self._grid_sign_solar_samples: int = 0
        self._prev_solar_w: Optional[float] = None
        self._prev_grid_raw_w: Optional[float] = None
        self._SOLAR_SWING_MIN_W: float = 500.0
        self._SOLAR_SIGN_MIN_SAMPLES: int = 4
        self._SOLAR_SIGN_MIN_CONFIDENCE: float = 0.80
        # Battery-quiet filter: a charging/discharging battery intercepts
        # the solar swing before it reaches the grid, so only cycles where
        # the battery is near-idle (both ends of the delta) cast a vote.
        # ``None`` battery (no battery install) is treated as quiet.
        self._SOLAR_BATTERY_QUIET_W: float = 400.0
        self._prev_batt_w: Optional[float] = None
        # Overriding an EXISTING lock is gated harder than an initial lock.
        self._SOLAR_OVERRIDE_MIN_SAMPLES: int = 20
        self._SOLAR_OVERRIDE_MIN_CONFIDENCE: float = 0.90
        # #461 brand-lookup tier — attempt the deterministic platform seed
        # exactly once (the grid sensor / registry is stable for a session).
        self._brand_seed_done: bool = False
        self._grid_import_baseline: Optional[float] = None
        self._grid_export_baseline: Optional[float] = None
        # #487 follow-up (live PROD flip 2026-06-11): during HA's
        # come-up window counter states replay in bursts while power
        # sensors are already live — 3 quick wrong votes locked
        # grid_sign_inverted=True on a Huawei install whose convention
        # needs NO correction (RAM-only state, #476 item 5/6 gap).
        # Sign votes are ignored for the first cycles after
        # construction (~2 min at the 10 s interval).
        self._sign_vote_warmup: int = 12
        # Battery sign autodetect — #404: per-battery state.
        # Multi-battery installs (≥ 2 ``battery_power_list`` entries) run
        # the detection independently per battery using each one's own
        # ``battery_charge_energy_list[i]`` / ``discharge_energy_list[i]``
        # counters, so a dual-brand fleet (e.g., Sessy + Huawei) with
        # opposite sign conventions ends up canonical for both. Each
        # dict is keyed by the stable per-battery slug (``b1``, ``b2`` …)
        # assigned in the read-power loop below.
        #
        # Single-battery / combined-sensor installs fall back to the
        # legacy fleet-level detection using the ``ed.battery_*_energy``
        # (singular) counters. Both code paths share the same voting +
        # threshold heuristic — only the input scope differs.
        self._battery_sign_inverted: Dict[str, bool] = {}
        self._battery_sign_detected: Dict[str, bool] = {}
        # #588: per-bid magnitude-weighted accumulator — mirrors the grid
        # voter introduced in #461. Replaces the old ±1 consecutive-run
        # counter (_battery_sign_votes) with a confidence-gated approach:
        #   +weight → SEM convention (+=charge, no negate)
        #   −weight → opposite (+=discharge, negate)
        #   weight = |power_w|
        # Lock only when samples >= MIN_SAMPLES AND confidence >= MIN_CONFIDENCE.
        self._battery_sign_evidence: Dict[str, float] = {}
        self._battery_sign_total_mag: Dict[str, float] = {}
        self._battery_sign_samples: Dict[str, int] = {}
        # Keep legacy _battery_sign_votes so older serialised storage blobs
        # from pre-#588 builds don't crash on restore (the field is just unused).
        self._battery_sign_votes: Dict[str, int] = {}
        self._battery_charge_baseline: Dict[str, Optional[float]] = {}
        self._battery_discharge_baseline: Dict[str, Optional[float]] = {}
        # #588: per-bid brand-seed flag — attempt the deterministic platform
        # seed exactly once per bid (the battery sensor/registry is stable).
        self._battery_brand_seed_done: Dict[str, bool] = {}
        self._BATTERY_SIGN_MIN_SAMPLES: int = 3
        self._BATTERY_SIGN_MIN_CONFIDENCE: float = 0.75
        # Sentinel key for the legacy single-battery / fleet-sensor path.
        # Keeps the per-battery and fleet paths in one data model
        # without spreading two parallel sets of state across the class.
        self._FLEET_BID = "__fleet__"
        # Track sensor availability transitions (#5: robustness)
        self._sensor_unavailable: set[str] = set()
        # (HA Repairs, 2026-06-06) per-entity timestamp when sensor
        # first went unavailable in the current outage. Used to delay
        # the Repair issue past a transient flap window
        # (``repair_issues.UNAVAILABLE_REPAIR_THRESHOLD_S``). Cleared
        # on recovery.
        self._sensor_unavailable_since: dict[str, float] = {}
        # Per-entity flag — was the Repair already raised this outage?
        # Avoids re-raising every cycle past the threshold.
        self._sensor_repair_raised: set[str] = set()
        # W3 — frozen (available-but-not-updating) fast-power-sensor detector.
        # A Huawei modbus stall / Growatt cloud freeze keeps the entity
        # "available" with a stale value that silently poisons the energy
        # balance + sign detection (the #461/#462 triage had no log visibility
        # into this). Observe-only: warn ONCE per freeze; the reading is
        # unchanged. Only the fast power sensors (which update every few
        # seconds) are checked, with a generous threshold, so a legitimately
        # slow sensor never false-positives.
        self._frozen_sensors: set[str] = set()
        self._FAST_POWER_NAMES = frozenset(
            {"solar", "grid", "grid_import", "grid_export", "battery"}
        )
        self._STALE_THRESHOLD_S = 600  # 10 min: a fast power sensor stale this long is frozen
        # Cache last valid SOC to avoid 0% during sensor gaps
        self._last_valid_soc: float = 0.0
        # EV flap fix (2026-07-10): the KEBA charging-power sensor polls over
        # UDP and blips to ~0 for a cycle while the car is really drawing 10 kW.
        # ``ev_power`` feeds the home energy balance (``home = solar + grid −
        # ev − …``), so a 0-blip while the grid meter (fast) still shows the
        # import spikes ``home`` → crashes the EV surplus below the
        # battery-assist gate → the budget collapses to 0 → IDLE → the
        # contactor drops → the ~15 s flap seen on PROD. A median-of-3 kills
        # the single-cycle blip at the source (a real start/stop is 2+ cycles
        # and follows within one). Warm-up passes the raw value. Keyed per
        # charger (plus a "_fleet" key) so the multi-charger per-charger dict
        # stays consistent with the smoothed fleet sum.
        self._ev_power_hist: Dict[str, deque] = {}
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
        # Last (import, export, confidence) discovery result that was
        # logged at INFO — unchanged re-scans drop to debug (#485 H3).
        self._last_split_grid_log: Optional[tuple] = None
        # Manual grid override audit (#461 follow-up). When the user sets
        # grid_import_power_entity / grid_export_power_entity explicitly,
        # ALL sign auto-detection is bypassed — a swapped, single-sided or
        # wrong-kind (energy counter as power) configuration produces a
        # statically inverted grid with zero feedback. The audit compares
        # the manual-computed sign against the Energy Dashboard counters
        # in observe-only mode and warns loudly on sustained contradiction.
        self._manual_grid_config_warned: set[str] = set()
        # Three CounterCorrelationAudit instances replace the 15 scattered
        # fields (_*_baseline, _*_votes, _*_contradiction, _*_warned).
        # Logging is handled by the adapter methods that call .update() and
        # inspect the returned sentinel ("warn" / "clear" / None).
        self._manual_grid_audit = CounterCorrelationAudit()
        # #589 — post-lock contradiction audit for the auto-detected grid sign.
        # Uses separate baselines so the voter's own baselines are never disturbed.
        self._grid_sign_audit = CounterCorrelationAudit()
        # #589 — observe-only battery sign contradiction audit (post-lock).
        # Separate baselines keep the voter's _battery_charge/discharge_baseline clean.
        self._battery_sign_audit = CounterCorrelationAudit()

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
            inverter_temperature_sensor=config.get("inverter_temperature_sensor"),
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

    def set_pv_string_names(self, names: "Optional[Dict[str, str]]") -> None:
        """(#566) User-chosen display names per PV-string slot, e.g.
        ``{"pv1": "East", "pv2": "West"}`` from the options flow. Blank/absent
        slots fall back to the compact default (see ``pv_string_display_name``).
        """
        self._pv_string_names = {
            str(k): str(v).strip()
            for k, v in (names or {}).items()
            if v and str(v).strip()
        }

    def pv_string_display_name(self, slot: str) -> str:
        """(#566) Display name for a slot: the user's custom name, else the
        compact default ``PV1`` / ``PV2`` / …"""
        custom = getattr(self, "_pv_string_names", {}).get(slot)
        return custom or f"PV{slot.replace('pv', '')}"

    def set_energy_dashboard_config(self, ed_config) -> None:
        """Set energy dashboard configuration for alternative sensor reading."""
        self._energy_dashboard_config = ed_config

    def read_power(self) -> PowerReadings:
        """Read all power values from sensors."""
        readings = PowerReadings()

        # Sign-vote warm-up ticks once per cycle (#487 follow-up) —
        # decremented here so it expires even on installs where one
        # voter early-returns before its own check.
        if self._sign_vote_warmup > 0:
            self._sign_vote_warmup -= 1

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

            # #589 — observe-only post-lock contradiction check for the
            # auto/counter/solar/restored lock.  Runs only when the lock is
            # set AND we are on the combined/split auto path (manual entity
            # overrides use _audit_manual_grid_sign in _read_from_energy_dashboard).
            _manual_ent = (
                self._raw_config.get("grid_import_power_entity")
                or self._raw_config.get("grid_export_power_entity")
            )
            _ed_for_audit = self._energy_dashboard_config
            if (self._grid_sign_detected
                    and not _manual_ent
                    and _ed_for_audit is not None):
                self._audit_autodetect_grid_sign(readings.grid_power, _ed_for_audit)

        # #461: one-tap user sign flip from the Control-tab button. Sits on
        # TOP of whatever the manual-override / auto-detect path decided, so
        # a wrongly-locked sign (import/export inverted) can be corrected in
        # one tap regardless of how it was derived — without touching the
        # ``grid_sign_invert`` semantics that Enphase/Powerwall installs rely
        # on. Persisted as a config option, so it survives restart.
        if bool(self._raw_config.get("grid_sign_user_flip", False)):
            readings.grid_power = -readings.grid_power
            readings.calculate_derived()

        # Auto-detect battery sign convention using Energy Dashboard counters.
        # SEM convention: positive = charge, negative = discharge.
        #
        # #404: when the install has ≥ 2 per-battery power sensors AND
        # the matching per-battery energy counters, run the detection
        # independently per battery and rebuild the fleet sum from the
        # corrected per-battery values — this guarantees fleet ↔ per-
        # battery consistency by construction AND handles dual-brand
        # fleets (e.g., Sessy + Huawei) that need different per-battery
        # flip decisions.
        #
        # Single-battery / combined-sensor installs fall back to the
        # legacy fleet-level path.
        ed = self._energy_dashboard_config
        # #553 — units = combined entities + two-sensor pairs (#551). Pairs
        # are convention-authoritative (the user declared charge/discharge
        # directions in HA), so only combined units go through sign detect.
        _n_units = 0 if ed is None else (
            len(ed.battery_power_list) + len(ed.battery_power_pairs)
        )
        per_battery_mode = (
            ed is not None
            and _n_units >= 2
            and len(readings.batteries) == _n_units
        )

        if per_battery_mode:
            from dataclasses import replace
            corrected_total = 0.0
            for idx, entity in enumerate(ed.battery_power_list):
                bid = f"b{idx + 1}"
                bp = readings.batteries.get(bid)
                if bp is None:
                    continue
                charge_entity = (
                    ed.battery_charge_energy_list[idx]
                    if idx < len(ed.battery_charge_energy_list) else None
                )
                discharge_entity = (
                    ed.battery_discharge_energy_list[idx]
                    if idx < len(ed.battery_discharge_energy_list) else None
                )
                needs_negate = self._detect_battery_sign_for(
                    bid, bp.power_w, charge_entity, discharge_entity,
                    power_entity=entity,
                )
                if needs_negate:
                    bp = replace(bp, power_w=-bp.power_w)
                    readings.batteries[bid] = bp
                corrected_total += bp.power_w
            # #553 — pair units join the total as-is (never sign-flipped:
            # net = declared charge − declared discharge is already SEM
            # convention by construction).
            for k in range(len(ed.battery_power_pairs)):
                bid = f"b{len(ed.battery_power_list) + k + 1}"
                bp = readings.batteries.get(bid)
                if bp is not None:
                    corrected_total += bp.power_w
            readings.battery_power = corrected_total
            readings.calculate_derived()
            # #588 B1 — one-tap user battery sign flip. Applied AFTER the
            # per-battery auto-detect loop so it corrects the corrected total.
            # Mirrors the grid user flip at line ~431. Negates BOTH the fleet
            # total AND every per-battery ``power_w`` (H-1): the battery
            # actuator sources ``BatteryRuntime.last_known_w`` from the
            # per-battery dict, not the fleet scalar — flipping only the total
            # would desync the arbitrage/force-discharge direction on
            # multi-battery installs.
            if bool(self._raw_config.get("battery_sign_user_flip", False)):
                for bid, bp in list(readings.batteries.items()):
                    readings.batteries[bid] = replace(bp, power_w=-bp.power_w)
                readings.battery_power = -readings.battery_power
                readings.calculate_derived()
        else:
            from dataclasses import replace
            # #589 — keep the per-battery dict in lockstep with the fleet scalar
            # on EVERY negate below. The actuator sources BatteryRuntime.last_known_w
            # from readings.batteries[bid].power_w, not the fleet scalar. This
            # branch is reached when per_battery_mode is off (single/combined
            # battery, ed is None) — usually readings.batteries is empty so this
            # is a no-op, but a single per-battery meter (_n_units == 1) DOES
            # populate it, and flipping only the scalar would desync the
            # arbitrage/force-discharge direction. Mirrors #588 H-1.
            def _negate_per_battery():
                for bid, bp in list(readings.batteries.items()):
                    readings.batteries[bid] = replace(bp, power_w=-bp.power_w)

            battery_needs_negate = self._detect_battery_sign(readings)
            if battery_needs_negate:
                readings.battery_power = -readings.battery_power
                _negate_per_battery()
                readings.calculate_derived()
            # #588 B1 — one-tap user battery sign flip, same as per_battery_mode
            # branch. Sits on top of the auto-detect / manual-invert path.
            if bool(self._raw_config.get("battery_sign_user_flip", False)):
                readings.battery_power = -readings.battery_power
                _negate_per_battery()
                readings.calculate_derived()

        # #589 — observe-only post-lock battery sign contradiction audit.
        # Runs here so battery_power is final (all corrections applied).
        # The method guards on the fleet lock being set, so it is a no-op
        # until the sign is detected, and a no-op in per_battery_mode
        # (where __fleet__ lock is never set).
        if ed is not None:
            self._audit_battery_sign_lock(readings.battery_power, ed)

        return readings

    # ── Sign-state persistence (#476 item 5) ─────────────────────────
    #
    # The autodetect locks (`_grid_sign_detected` / per-battery dicts)
    # were RAM-only: every reload/restart re-learned the sign from
    # possibly ambiguous low-power samples — three bad votes right
    # after a reboot could lock the WRONG sign until the next reload
    # (the 2026-06-11 PROD flip). The coordinator persists this state
    # via SEMStorage and restores it at setup, so a lock survives
    # restarts and the warmup/vote machinery only ever runs once per
    # install (or after the user clears storage). A manual
    # ``grid_sign_invert`` config still short-circuits before the
    # autodetect, so restored state can never fight a manual override.

    def grid_sign_diagnostics(self) -> dict:
        """Build a #461 grid-sign support payload.

        Returns everything a maintainer needs to judge a wrong-sign
        report without a 5 MB diagnostics dump: the raw meter reading,
        the configured Energy-Dashboard import/export counters, the
        manual/auto/user-flip override state, and the live correlation
        evidence. Surfaced by the ``flip_grid_sign`` service so the
        Control-tab button can copy it straight into a GitHub issue.
        """
        ed = self._energy_dashboard_config

        def _entities(singular, list_name):
            lst = getattr(ed, list_name, None) if ed else None
            if isinstance(lst, (list, tuple)) and lst:
                return list(lst)
            single = getattr(ed, singular, None) if ed else None
            return [single] if single else []

        grid_entity = self.config.grid_power_sensor
        raw_state = None
        grid_platform = None
        if grid_entity and self.hass is not None:
            st = self.hass.states.get(grid_entity)
            if st is not None:
                raw_state = st.state
            try:
                entry = er.async_get(self.hass).async_get(grid_entity)
                pf = entry.platform if entry else None
                grid_platform = pf if isinstance(pf, str) else None
            except Exception:  # noqa: BLE001 — diagnostics must never raise
                grid_platform = None

        confidence = (
            abs(self._grid_sign_evidence) / self._grid_sign_total_mag
            if self._grid_sign_total_mag > 0 else 0.0
        )
        return {
            "grid_power_sensor": grid_entity,
            "grid_power_raw_state": raw_state,
            "grid_platform": grid_platform,
            "brand_seeded": grid_platform in PLATFORM_GRID_SIGN_INVERT
            if grid_platform else False,
            "manual_grid_sign_invert": bool(
                self._raw_config.get("grid_sign_invert", False)
            ),
            "user_flip": bool(self._raw_config.get("grid_sign_user_flip", False)),
            "auto_detected": self._grid_sign_detected,
            "auto_inverted": self._grid_sign_inverted,
            "evidence": round(self._grid_sign_evidence, 1),
            "total_magnitude": round(self._grid_sign_total_mag, 1),
            "samples": self._grid_sign_samples,
            "confidence": round(confidence, 3),
            "solar_evidence": round(self._grid_sign_solar_evidence, 1),
            "solar_samples": self._grid_sign_solar_samples,
            "solar_confidence": round(
                abs(self._grid_sign_solar_evidence) / self._grid_sign_solar_mag
                if self._grid_sign_solar_mag > 0 else 0.0, 3
            ),
            "seen_import": self._grid_sign_seen_import,
            "seen_export": self._grid_sign_seen_export,
            "import_counters": _entities(
                "grid_import_energy", "grid_import_energy_list"
            ),
            "export_counters": _entities(
                "grid_export_energy", "grid_export_energy_list"
            ),
        }

    def battery_sign_diagnostics(self) -> dict:
        """#588 battery-sign support payload, mirroring grid_sign_diagnostics.

        Returns everything a maintainer needs to judge a wrong-sign
        battery report: per-bid sign state, accumulator evidence, the
        battery power sensor entity, its platform (for brand-seed audit),
        and the user-flip state. Surfaced by the ``flip_battery_sign``
        service so the Config-tab button can copy it into a GitHub issue.
        """
        ed = self._energy_dashboard_config
        battery_entity = self.config.battery_power_sensor
        # In ED mode, the primary battery power entity is the first in the list
        if not battery_entity and ed is not None:
            lst = getattr(ed, "battery_power_list", None) or []
            battery_entity = lst[0] if lst else getattr(ed, "battery_power", None)

        raw_state = None
        battery_platform = None
        if battery_entity and self.hass is not None:
            st = self.hass.states.get(battery_entity)
            if st is not None:
                raw_state = st.state
            try:
                entry = er.async_get(self.hass).async_get(battery_entity)
                pf = entry.platform if entry else None
                battery_platform = pf if isinstance(pf, str) else None
            except Exception:  # noqa: BLE001 — diagnostics must never raise
                battery_platform = None

        per_bid = {}
        for bid in set(self._battery_sign_inverted) | set(self._battery_sign_detected):
            mag = self._battery_sign_total_mag.get(bid, 0.0)
            ev = self._battery_sign_evidence.get(bid, 0.0)
            per_bid[bid] = {
                "detected": self._battery_sign_detected.get(bid, False),
                "inverted": self._battery_sign_inverted.get(bid, False),
                "evidence": round(ev, 1),
                "total_magnitude": round(mag, 1),
                "samples": self._battery_sign_samples.get(bid, 0),
                "confidence": round(abs(ev) / mag if mag > 0 else 0.0, 3),
                "brand_seed_done": self._battery_brand_seed_done.get(bid, False),
            }

        return {
            "battery_power_sensor": battery_entity,
            "battery_power_raw_state": raw_state,
            "battery_platform": battery_platform,
            "brand_seeded": battery_platform in PLATFORM_BATTERY_SIGN_INVERT
            if battery_platform else False,
            "user_flip": bool(self._raw_config.get("battery_sign_user_flip", False)),
            "per_bid": per_bid,
            "charge_counters": (
                [ed.battery_charge_energy] if ed and ed.battery_charge_energy
                else list(getattr(ed, "battery_charge_energy_list", None) or [])
                if ed else []
            ),
            "discharge_counters": (
                [ed.battery_discharge_energy] if ed and ed.battery_discharge_energy
                else list(getattr(ed, "battery_discharge_energy_list", None) or [])
                if ed else []
            ),
        }

    # ------------------------------------------------------------------
    # Backward-compat properties for the CounterCorrelationAudit fields
    # ------------------------------------------------------------------
    # coordinator.py and tests access these as plain attributes on the
    # reader instance.  Surfacing them via @property keeps the external
    # interface identical while the state now lives on the audit objects.

    # ---- manual grid mismatch ----------------------------------------

    @property
    def _manual_grid_import_baseline(self) -> Optional[float]:
        return self._manual_grid_audit.baseline_a

    @_manual_grid_import_baseline.setter
    def _manual_grid_import_baseline(self, v: Optional[float]) -> None:
        self._manual_grid_audit.baseline_a = v

    @property
    def _manual_grid_export_baseline(self) -> Optional[float]:
        return self._manual_grid_audit.baseline_b

    @_manual_grid_export_baseline.setter
    def _manual_grid_export_baseline(self, v: Optional[float]) -> None:
        self._manual_grid_audit.baseline_b = v

    @property
    def _manual_grid_mismatch_votes(self) -> int:
        return self._manual_grid_audit.votes

    @property
    def _manual_grid_mismatch(self) -> bool:
        return self._manual_grid_audit.flagged

    @property
    def _manual_grid_mismatch_warned(self) -> bool:
        return self._manual_grid_audit.warned

    # ---- grid sign lock contradiction --------------------------------

    @property
    def _grid_audit_import_baseline(self) -> Optional[float]:
        return self._grid_sign_audit.baseline_a

    @_grid_audit_import_baseline.setter
    def _grid_audit_import_baseline(self, v: Optional[float]) -> None:
        self._grid_sign_audit.baseline_a = v

    @property
    def _grid_audit_export_baseline(self) -> Optional[float]:
        return self._grid_sign_audit.baseline_b

    @_grid_audit_export_baseline.setter
    def _grid_audit_export_baseline(self, v: Optional[float]) -> None:
        self._grid_sign_audit.baseline_b = v

    @property
    def _grid_sign_lock_contradiction_votes(self) -> int:
        return self._grid_sign_audit.votes

    @property
    def _grid_sign_lock_contradiction(self) -> bool:
        return self._grid_sign_audit.flagged

    @property
    def _grid_sign_lock_contradiction_warned(self) -> bool:
        return self._grid_sign_audit.warned

    # ---- battery sign contradiction ----------------------------------

    @property
    def _battery_audit_charge_baseline(self) -> Optional[float]:
        return self._battery_sign_audit.baseline_a

    @_battery_audit_charge_baseline.setter
    def _battery_audit_charge_baseline(self, v: Optional[float]) -> None:
        self._battery_sign_audit.baseline_a = v

    @property
    def _battery_audit_discharge_baseline(self) -> Optional[float]:
        return self._battery_sign_audit.baseline_b

    @_battery_audit_discharge_baseline.setter
    def _battery_audit_discharge_baseline(self, v: Optional[float]) -> None:
        self._battery_sign_audit.baseline_b = v

    @property
    def _battery_sign_contradiction_votes(self) -> int:
        return self._battery_sign_audit.votes

    @property
    def _battery_sign_contradiction(self) -> bool:
        return self._battery_sign_audit.flagged

    @property
    def _battery_sign_contradiction_warned(self) -> bool:
        return self._battery_sign_audit.warned

    def export_sign_state(self) -> dict:
        """Snapshot the LOCKED sign-detection state for persistence."""
        return {
            "grid_detected": self._grid_sign_detected,
            "grid_inverted": self._grid_sign_inverted,
            "battery_detected": dict(self._battery_sign_detected),
            "battery_inverted": dict(self._battery_sign_inverted),
        }

    def restore_sign_state(self, state) -> None:
        """Re-seed locked sign state from storage (setup time).

        Only LOCKED entries restore (detected must be True with a bool
        inversion) — votes, warmup counters and unlocked guesses never
        persist, so a half-learned state can't be resurrected. Garbage
        / legacy shapes are ignored wholesale.
        """
        if not isinstance(state, dict):
            return
        if state.get("grid_detected") is True and isinstance(
            state.get("grid_inverted"), bool
        ):
            self._grid_sign_detected = True
            self._grid_sign_inverted = state["grid_inverted"]
            _LOGGER.info(
                "Restored grid sign from storage: %s",
                "negating (HA convention)" if self._grid_sign_inverted
                else "no correction (SEM convention)",
            )
        bd = state.get("battery_detected")
        bi = state.get("battery_inverted")
        if isinstance(bd, dict) and isinstance(bi, dict):
            for bid, det in bd.items():
                if det is True and isinstance(bi.get(bid), bool):
                    self._battery_sign_detected[bid] = True
                    self._battery_sign_inverted[bid] = bi[bid]
                    _LOGGER.info(
                        "Restored battery '%s' sign from storage: %s",
                        bid,
                        "negating" if bi[bid] else "no correction",
                    )

    def reset_sign_state(self) -> None:
        """Forget all sign-detection locks and re-learn from scratch.

        #476 item 5 escape hatch: with persistence a WRONG lock would
        otherwise survive restarts forever (pre-persistence, a restart
        cleared it). Exposed via the ``reset_sign_detection`` service.
        Re-arms the startup warmup so the re-learn doesn't vote on the
        first ambiguous samples either.
        """
        self._grid_sign_inverted = False
        self._grid_sign_detected = False
        self._grid_sign_evidence = 0.0
        self._grid_sign_total_mag = 0.0
        self._grid_sign_samples = 0
        self._grid_sign_seen_import = False
        self._grid_sign_seen_export = False
        self._grid_sign_solar_evidence = 0.0
        self._grid_sign_solar_mag = 0.0
        self._grid_sign_solar_samples = 0
        self._prev_solar_w = None
        self._prev_grid_raw_w = None
        self._prev_batt_w = None
        # Re-arm the brand seed so a known-brand install re-locks its
        # deterministic sign on the next cycle after a reset.
        self._brand_seed_done = False
        self._grid_import_baseline = None
        self._grid_export_baseline = None
        self._battery_sign_inverted.clear()
        self._battery_sign_detected.clear()
        self._battery_sign_evidence.clear()
        self._battery_sign_total_mag.clear()
        self._battery_sign_samples.clear()
        self._battery_sign_votes.clear()
        self._battery_charge_baseline.clear()
        self._battery_discharge_baseline.clear()
        self._battery_brand_seed_done.clear()
        self._sign_vote_warmup = 12
        _LOGGER.info(
            "Sign-detection state reset — grid and battery signs will be "
            "re-learned from Energy Dashboard counters"
        )

    def _seed_grid_sign_from_platform(self) -> None:
        """Deterministic grid-sign seed from the meter's integration (#461).

        The grid-power sensor's own ``platform`` (HA integration domain)
        tells us the sign convention with certainty for well-tested brands
        — no inference needed. Runs once: if the platform is a known brand
        AND nothing has locked the sign yet (no restored lock, no manual
        override), it seeds + locks the sign immediately, so a fresh
        install of a known brand is correct from the first cycle instead of
        waiting for solar swings or counter deltas.

        Precedence: this seed is still OVERRIDABLE by the solar detector
        (physical ground truth) and the manual flip, so a wrong brand
        mapping self-heals rather than sticking. An unknown platform (e.g.
        a separate P1/CT meter) simply falls through to the statistical
        detectors.
        """
        if self._brand_seed_done or self._grid_sign_detected:
            self._brand_seed_done = True
            return
        self._brand_seed_done = True

        entity_id = self.config.grid_power_sensor
        if not entity_id:
            # Split-grid install: try the discovered import sensor's brand.
            entity_id = (self._split_grid_discovery or {}).get("import")
        if not entity_id:
            return
        try:
            registry = er.async_get(self.hass)
            entry = registry.async_get(entity_id)
            platform = entry.platform if entry else None
        except Exception as e:  # noqa: BLE001 — registry hiccup must not block reads
            _LOGGER.debug("Grid-sign brand lookup failed for %s: %s", entity_id, e)
            return
        if not isinstance(platform, str) or platform not in PLATFORM_GRID_SIGN_INVERT:
            return

        self._grid_sign_inverted = PLATFORM_GRID_SIGN_INVERT[platform]
        self._grid_sign_detected = True
        _LOGGER.info(
            "Grid sign seeded from integration '%s' (%s): %s — "
            "deterministic brand lookup; solar co-movement can still "
            "override if it disagrees",
            platform, entity_id,
            "negating (HA convention)" if self._grid_sign_inverted
            else "no correction (SEM convention)",
        )

    def _seed_battery_sign_from_platform(self, bid: str, power_entity: Optional[str]) -> None:
        """#588: deterministic battery-sign SOFT seed from the battery power
        sensor's integration, mirroring ``_seed_grid_sign_from_platform``.

        Runs once per bid: if the platform is a known brand AND the sign is
        not already locked for this bid, seeds a good STARTING default so a
        fresh install of a known brand is correct from the first cycle instead
        of waiting for counter deltas. Precedence: user_flip > manual > this
        seed > counter-vote.

        SOFT seed (H-2): unlike a hard lock, this sets the sign hint but leaves
        ``detected=False`` so the counter-correlation voter still runs and can
        CONFIRM or OVERRIDE the seed. This is the battery's analogue to the
        grid's solar override: a brand-deviant install (e.g. a Huawei battery
        whose Energy-Dashboard mapping happens to be reversed — the #588
        reporter's case) self-heals from the counters instead of being pinned
        to the wrong brand default and forced to use the manual flip. The
        magnitude-weighted voter (>=3 samples, >=0.75 confidence) guards
        against a bad override. The user flip / reset is still the ultimate
        backstop for a swapped-counter install where the counters themselves
        lie.

        An unknown platform simply falls through to the statistical detector.
        """
        if self._battery_brand_seed_done.get(bid) or self._battery_sign_detected.get(bid):
            self._battery_brand_seed_done[bid] = True
            return
        self._battery_brand_seed_done[bid] = True

        if not power_entity:
            return
        try:
            registry = er.async_get(self.hass)
            entry = registry.async_get(power_entity)
            platform = entry.platform if entry else None
        except Exception as e:  # noqa: BLE001 — registry hiccup must not block reads
            _LOGGER.debug("Battery-sign brand lookup failed for %s (%s): %s", bid, power_entity, e)
            return
        if not isinstance(platform, str) or platform not in PLATFORM_BATTERY_SIGN_INVERT:
            return

        # SOFT default only — do NOT set detected=True, so the counter voter
        # remains free to confirm or override this hint.
        self._battery_sign_inverted[bid] = PLATFORM_BATTERY_SIGN_INVERT[platform]
        _LOGGER.info(
            "Battery sign seeded from integration '%s' (%s, bid=%s): %s — "
            "soft brand default; the counter voter can still confirm/override, "
            "and a user flip / reset is the final backstop",
            platform, power_entity, bid,
            "negating (opposite convention)" if self._battery_sign_inverted[bid]
            else "no correction (SEM convention)",
        )

    def _accumulate_solar_sign(self, readings: PowerReadings) -> None:
        """Solar-anchored grid-sign detection (#461, authoritative primary).

        Solar production has no sign ambiguity, so the co-movement of the
        RAW grid reading with solar reveals the grid convention directly
        and independently of the (possibly mis-mapped) Energy-Dashboard
        counters:

          * grid rises with solar      → +export meter (SEM) → no negate
          * grid falls as solar rises  → +import meter (HA)  → negate

        Only large solar swings (``_SOLAR_SWING_MIN_W``) vote, so the
        solar-driven component of Δgrid dominates home-load jitter. Locks
        the sign before the counter path for solar installs, and can
        OVERRIDE a wrong counter-derived lock once it is highly confident
        and sustained — a correctly-signed install computes the same sign
        as its current lock, so agreement means it is never flipped.

        No-op for non-solar installs (no usable ``solar_power``), which
        fall through to the counter-correlation path.
        """
        solar = getattr(readings, "solar_power", None)
        grid_raw = getattr(readings, "grid_power", None)
        if not isinstance(solar, (int, float)) or isinstance(solar, bool):
            return
        if not isinstance(grid_raw, (int, float)) or isinstance(grid_raw, bool):
            return

        batt = getattr(readings, "battery_power", None)
        batt_q = (
            abs(float(batt))
            if isinstance(batt, (int, float)) and not isinstance(batt, bool)
            else 0.0  # no battery / unreadable → treat as quiet
        )
        prev_solar = self._prev_solar_w
        prev_grid = self._prev_grid_raw_w
        prev_batt_q = self._prev_batt_w
        self._prev_solar_w = float(solar)
        self._prev_grid_raw_w = float(grid_raw)
        self._prev_batt_w = batt_q
        if prev_solar is None or prev_grid is None:
            return

        d_solar = float(solar) - prev_solar
        d_grid = float(grid_raw) - prev_grid
        if abs(d_solar) < self._SOLAR_SWING_MIN_W:
            return  # swing too small to dominate load jitter
        # Both ends of the delta must be battery-quiet, else the swing was
        # (partly) absorbed by the battery rather than passed to the grid,
        # and Δgrid no longer tracks Δsolar (the battery-install confound).
        if batt_q >= self._SOLAR_BATTERY_QUIET_W or (
            prev_batt_q is not None and prev_batt_q >= self._SOLAR_BATTERY_QUIET_W
        ):
            return

        # product > 0 → grid co-moves with solar → SEM (no negate);
        # product < 0 → grid moves against solar → HA (negate).
        detected_negate = (d_grid * d_solar) < 0
        weight = abs(d_solar)
        self._grid_sign_solar_evidence += -weight if detected_negate else weight
        self._grid_sign_solar_mag += weight
        self._grid_sign_solar_samples += 1

        confidence = (
            abs(self._grid_sign_solar_evidence) / self._grid_sign_solar_mag
            if self._grid_sign_solar_mag > 0 else 0.0
        )
        implied_inverted = self._grid_sign_solar_evidence < 0

        if not self._grid_sign_detected:
            if (
                self._grid_sign_solar_samples >= self._SOLAR_SIGN_MIN_SAMPLES
                and confidence >= self._SOLAR_SIGN_MIN_CONFIDENCE
            ):
                self._grid_sign_inverted = implied_inverted
                self._grid_sign_detected = True
                _LOGGER.info(
                    "Grid sign locked from SOLAR co-movement: %s "
                    "(confidence=%.2f, samples=%d, evidence=%.0f) — "
                    "counter-independent, immune to mis-mapped Energy "
                    "Dashboard counters",
                    "negating (HA convention)" if implied_inverted
                    else "no correction (SEM convention)",
                    confidence, self._grid_sign_solar_samples,
                    self._grid_sign_solar_evidence,
                )
        elif (
            implied_inverted != self._grid_sign_inverted
            and self._grid_sign_solar_samples >= self._SOLAR_OVERRIDE_MIN_SAMPLES
            and confidence >= self._SOLAR_OVERRIDE_MIN_CONFIDENCE
        ):
            # Hard-gated self-heal: a sustained, high-confidence solar
            # verdict that DISAGREES with the current lock flips it. Only
            # ever triggers on a wrongly-signed install (a correct one
            # agrees), so it cannot disturb a working install (#461).
            _LOGGER.warning(
                "Grid sign OVERRIDDEN by solar co-movement: %s -> %s "
                "(confidence=%.2f, samples=%d) — the prior lock disagreed "
                "with the unambiguous solar signal, auto-healing",
                "negating" if self._grid_sign_inverted else "no correction",
                "negating" if implied_inverted else "no correction",
                confidence, self._grid_sign_solar_samples,
            )
            self._grid_sign_inverted = implied_inverted

    def _detect_grid_sign(self, readings: PowerReadings) -> bool:
        """Detect if grid power needs negation using Energy Dashboard counters.

        Compares the power sensor's sign against which energy counter
        (import or export) is increasing. This is reliable because the
        Energy Dashboard's flow_from/flow_to are always correct.

        Returns True if grid_power should be negated.
        """
        # Deterministic brand seed first (#461): a known meter integration
        # locks the sign immediately. Solar can still override it below.
        self._seed_grid_sign_from_platform()

        # Solar-anchored detection runs next and independently of the
        # Energy-Dashboard counters (#461). It is authoritative for solar
        # installs — it can set/override the lock here, and the counter
        # path below is gated on ``not self._grid_sign_detected``.
        self._accumulate_solar_sign(readings)

        ed = self._energy_dashboard_config
        if not ed:
            # No Energy Dashboard → trust the sensor. #476 item 5: a
            # restored/locked sign still applies (constructor default
            # False keeps the no-lock behaviour unchanged).
            return self._grid_sign_inverted

        # Sum across the counter LISTS when present (#485 H4): Dutch
        # dual-tariff DSMR meters split each direction into tarief 1 +
        # tarief 2 counters that move in different hours. Reading only
        # the first counter left the auto sign vote blind whenever the
        # untracked tariff was the active one — the beta.8 fix gave
        # only the manual-audit path this treatment.
        import_list = getattr(ed, "grid_import_energy_list", None)
        export_list = getattr(ed, "grid_export_energy_list", None)
        import_entities = (
            list(import_list) if isinstance(import_list, (list, tuple)) and import_list
            else ([ed.grid_import_energy] if ed.grid_import_energy else [])
        )
        export_entities = (
            list(export_list) if isinstance(export_list, (list, tuple)) and export_list
            else ([ed.grid_export_energy] if ed.grid_export_energy else [])
        )

        if not import_entities or not export_entities:
            # #476 item 5: a restored/locked sign must survive the
            # counters disappearing (e.g. Energy Dashboard reconfigured
            # after the lock was learned). Constructor default is False,
            # so the no-lock behaviour is unchanged.
            return self._grid_sign_inverted

        # Startup warm-up (#487 follow-up): no votes while HA's
        # recorder is still replaying counter states — keep baselines
        # fresh but cast nothing.
        if self._sign_vote_warmup > 0:
            iv = self._sum_counter_states(import_entities)
            ev = self._sum_counter_states(export_entities)
            if iv is not None and ev is not None:
                self._grid_import_baseline = iv
                self._grid_export_baseline = ev
            return self._grid_sign_inverted

        # Need meaningful power to detect (ignore noise)
        power = readings.grid_power
        if abs(power) < 100:
            return self._grid_sign_inverted  # Keep last known state

        import_val = self._sum_counter_states(import_entities)
        export_val = self._sum_counter_states(export_entities)
        if import_val is None or export_val is None:
            return self._grid_sign_inverted

        # First call: store baselines, don't correct yet
        if self._grid_import_baseline is None:
            self._grid_import_baseline = import_val
            self._grid_export_baseline = export_val
            # #476 item 5: honour a restored lock even on the very
            # first baseline call (counters can sit unknown for the
            # whole warmup). Default False = pre-#476 behaviour.
            return self._grid_sign_inverted

        deltas = self._counter_deltas(
            self._grid_import_baseline, self._grid_export_baseline,
            import_val, export_val,
        )

        # Update baselines for next cycle
        self._grid_import_baseline = import_val
        self._grid_export_baseline = export_val

        if deltas is None:
            # Counter reset (#476) — re-baselined above, sit this cycle out.
            _LOGGER.debug(
                "Grid energy counter reset detected — re-baselined, "
                "skipping sign vote",
            )
            return self._grid_sign_inverted
        import_delta, export_delta = deltas

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

        # Accumulate magnitude-weighted sign-of-correlation evidence
        # (#461). Each clear single-direction cycle adds |power| toward
        # SEM (+) or HA (−). Lock only when enough directional cycles have
        # contributed AND the dominant direction holds a strong majority of
        # ALL accumulated magnitude (confidence) — so a mixed/transient
        # burst that the old 3-consecutive vote could lock through now
        # stays diluted and never locks.
        if not self._grid_sign_detected:
            weight = abs(power)
            self._grid_sign_evidence += -weight if detected else weight
            self._grid_sign_total_mag += weight
            self._grid_sign_samples += 1
            if import_delta > 0.001:
                self._grid_sign_seen_import = True
            if export_delta > 0.001:
                self._grid_sign_seen_export = True

            confidence = (
                abs(self._grid_sign_evidence) / self._grid_sign_total_mag
                if self._grid_sign_total_mag > 0 else 0.0
            )
            if (
                self._grid_sign_samples >= self._GRID_SIGN_MIN_SAMPLES
                and confidence >= self._GRID_SIGN_MIN_CONFIDENCE
            ):
                self._grid_sign_inverted = self._grid_sign_evidence < 0
                self._grid_sign_detected = True
                # Name the evidence (#487 follow-up): a wrong lock is
                # otherwise undiagnosable after the fact — the 2026-06-11
                # PROD flip left only 'diag_grid_sign: negated' with no
                # trail of WHICH counters voted.
                _LOGGER.info(
                    "Grid sign detected from Energy Dashboard counters: %s "
                    "(confidence=%.2f, evidence=%.0f, total_mag=%.0f, "
                    "samples=%d, seen_import=%s, seen_export=%s, "
                    "last power=%.0fW, import_delta=%.3f, export_delta=%.3f, "
                    "import_counters=%s, export_counters=%s)",
                    "negating (HA convention)" if self._grid_sign_inverted
                    else "no correction (SEM convention)",
                    confidence, self._grid_sign_evidence,
                    self._grid_sign_total_mag, self._grid_sign_samples,
                    self._grid_sign_seen_import, self._grid_sign_seen_export,
                    power, import_delta, export_delta,
                    import_entities, export_entities,
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
            # #476 item 5: honour a restored fleet lock when the Energy
            # Dashboard disappears after the lock was learned — mirrors
            # the grid-path fix. Default False = pre-#476 behaviour.
            return self._battery_sign_inverted.get(self._FLEET_BID, False)

        charge_entity = ed.battery_charge_energy
        discharge_entity = ed.battery_discharge_energy
        return self._detect_battery_sign_for(
            self._FLEET_BID,
            readings.battery_power,
            charge_entity,
            discharge_entity,
            power_entity=getattr(ed, "battery_power", None),
        )

    def _detect_battery_sign_for(
        self,
        bid: str,
        power: float,
        charge_entity: Optional[str],
        discharge_entity: Optional[str],
        power_entity: Optional[str] = None,
    ) -> bool:
        """Run the sign-autodetect correlation against one (battery_id,
        power, charge_counter, discharge_counter) tuple.

        Used both by the legacy fleet path (``bid = _FLEET_BID``) and by
        the per-battery loop introduced in #404. Each ``bid`` gets its
        own voting accumulator + baselines, so dual-brand multi-battery
        installs end up with each battery independently corrected.

        #588 — voter upgraded to magnitude-weighted accumulator (mirrors
        the grid path from #461): old ±1 consecutive-run voter could lock
        the wrong sign on any 3-in-a-row run (jitter / come-up burst).
        New accumulator locks only when ALL of:
          * samples >= BATTERY_SIGN_MIN_SAMPLES (3)
          * confidence (|evidence| / total_mag) >= BATTERY_SIGN_MIN_CONFIDENCE (0.75)

        Returns True if ``power`` should be negated for this ``bid``.
        """
        # ``setdefault`` keeps the existing per-bid state stable across
        # cycles while letting new bids appear lazily (e.g., a second
        # battery added mid-session).
        self._battery_sign_inverted.setdefault(bid, False)
        self._battery_sign_detected.setdefault(bid, False)
        self._battery_sign_evidence.setdefault(bid, 0.0)
        self._battery_sign_total_mag.setdefault(bid, 0.0)
        self._battery_sign_samples.setdefault(bid, 0)
        self._battery_charge_baseline.setdefault(bid, None)
        self._battery_discharge_baseline.setdefault(bid, None)

        if not charge_entity or not discharge_entity:
            return self._battery_sign_inverted[bid]

        # #588 H2/B-1 — brand seed: attempt once per bid before the
        # statistical inference; seeds the pre-lock default for known brands.
        # Prefer the battery POWER sensor for the platform lookup (mirrors the
        # grid seed's use of ``grid_power_sensor``): its integration is always
        # the inverter brand, whereas the Energy-Dashboard charge/discharge
        # counters are frequently helper-derived (utility_meter / Riemann sum)
        # and would resolve to the wrong platform. Fall back to the charge
        # counter only when no power entity is known.
        self._seed_battery_sign_from_platform(bid, power_entity or charge_entity)

        # Startup warm-up (#487 follow-up / #588 H1) — same restart-window
        # protection as the grid voter; also REFRESH the baselines here so
        # the first post-warmup delta is fresh (mirror grid warmup ~line 921).
        if self._sign_vote_warmup > 0:
            charge_state = self.hass.states.get(charge_entity)
            discharge_state = self.hass.states.get(discharge_entity)
            if charge_state and charge_state.state not in ("unknown", "unavailable"):
                try:
                    self._battery_charge_baseline[bid] = float(charge_state.state)
                except (ValueError, TypeError):
                    pass
            if discharge_state and discharge_state.state not in ("unknown", "unavailable"):
                try:
                    self._battery_discharge_baseline[bid] = float(discharge_state.state)
                except (ValueError, TypeError):
                    pass
            return self._battery_sign_inverted[bid]

        # Need meaningful power to detect (ignore noise)
        if abs(power) < 100:
            return self._battery_sign_inverted[bid]  # Keep last known state

        # Read energy counter values
        charge_state = self.hass.states.get(charge_entity)
        discharge_state = self.hass.states.get(discharge_entity)

        if not charge_state or charge_state.state in ("unknown", "unavailable"):
            return self._battery_sign_inverted[bid]
        if not discharge_state or discharge_state.state in ("unknown", "unavailable"):
            return self._battery_sign_inverted[bid]

        try:
            charge_val = float(charge_state.state)
            discharge_val = float(discharge_state.state)
        except (ValueError, TypeError):
            return self._battery_sign_inverted[bid]

        # First call: store baselines, don't correct yet.
        # #476 item 5: honour a restored lock even here (counters can
        # sit unknown for the whole warmup). Default False unchanged.
        if self._battery_charge_baseline[bid] is None:
            self._battery_charge_baseline[bid] = charge_val
            self._battery_discharge_baseline[bid] = discharge_val
            return self._battery_sign_inverted[bid]

        deltas = self._counter_deltas(
            self._battery_charge_baseline[bid],
            self._battery_discharge_baseline[bid],
            charge_val, discharge_val,
        )

        # Update baselines for next cycle
        self._battery_charge_baseline[bid] = charge_val
        self._battery_discharge_baseline[bid] = discharge_val

        if deltas is None:
            # Counter reset (#476) — re-baselined above, sit this cycle out.
            _LOGGER.debug(
                "Battery '%s' energy counter reset detected — re-baselined, "
                "skipping sign vote",
                bid,
            )
            return self._battery_sign_inverted[bid]
        charge_delta, discharge_delta = deltas

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
            return self._battery_sign_inverted[bid]

        # #588 B2 — magnitude-weighted accumulator (mirrors grid path from #461).
        # Each clear single-direction cycle adds |power| toward SEM (+) or
        # opposite (−). Lock only when enough directional cycles have contributed
        # AND the dominant direction holds a strong majority of ALL accumulated
        # magnitude — so a mixed/transient burst that the old 3-consecutive vote
        # could lock through now stays diluted and never locks.
        if not self._battery_sign_detected[bid]:
            # Sign encoding (M-3): evidence accumulates NEGATIVE when the cycle
            # says "needs negate" (detected=True) and POSITIVE for SEM
            # convention. So a net-negative evidence → lock inverted=True below.
            weight = abs(power)
            self._battery_sign_evidence[bid] += -weight if detected else weight
            self._battery_sign_total_mag[bid] += weight
            self._battery_sign_samples[bid] += 1

            confidence = (
                abs(self._battery_sign_evidence[bid]) / self._battery_sign_total_mag[bid]
                if self._battery_sign_total_mag[bid] > 0 else 0.0
            )
            if (
                self._battery_sign_samples[bid] >= self._BATTERY_SIGN_MIN_SAMPLES
                and confidence >= self._BATTERY_SIGN_MIN_CONFIDENCE
            ):
                self._battery_sign_inverted[bid] = self._battery_sign_evidence[bid] < 0
                self._battery_sign_detected[bid] = True
                # #N1 — include counter entity IDs in the lock log so a wrong
                # lock is diagnosable from the log alone (mirrors grid lock log).
                _LOGGER.info(
                    "Battery sign detected for '%s' from Energy Dashboard counters: %s "
                    "(confidence=%.2f, evidence=%.0f, total_mag=%.0f, samples=%d, "
                    "power=%.0fW, charge_delta=%.3f, discharge_delta=%.3f, "
                    "charge_counter=%s, discharge_counter=%s)",
                    bid,
                    "negating (opposite convention)"
                    if self._battery_sign_inverted[bid]
                    else "no correction (SEM convention)",
                    confidence,
                    self._battery_sign_evidence[bid],
                    self._battery_sign_total_mag[bid],
                    self._battery_sign_samples[bid],
                    power, charge_delta, discharge_delta,
                    charge_entity, discharge_entity,
                )

        return self._battery_sign_inverted[bid]

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
        # Per-inverter breakdown is DECOUPLED from fleet-scalar selection: the
        # ``readings.inverters`` dict is populated whenever the Energy Dashboard
        # exposes ≥2 inverters — INDEPENDENTLY of which sensor supplies the fleet
        # scalar — so a higher-precedence fleet override can never suppress the
        # per-unit surface (#623, sibling of the battery path below). The
        # per-inverter sum then owns the fleet scalar, keeping the
        # ``solar_power == fleet_solar_w`` pin (types.py) true by construction.
        per_inverter_total = None
        if len(ed.solar_power_list) > 1:
            per_inverter_total = 0.0
            for entity in ed.solar_power_list:
                w = self._read_sensor(entity, "solar")
                per_inverter_total += w
                readings.inverters[entity] = InverterPower(
                    inverter_id=entity, power_w=w, name=entity,
                )
        if per_inverter_total is not None:
            readings.solar_power = per_inverter_total
        elif self.config.solar_power_sensor:
            # #592 — explicit SEM solar power override. Applies only when there
            # is no ≥2 per-inverter breakdown to sum: on energy-only installs the
            # Energy Dashboard exposes solar ENERGY only, so ``ed.solar_power`` is
            # None and the Home balance read solar=0 (→ Home clamped to 0); the
            # override lets the user supply a real solar power sensor. Sibling of
            # the #597 battery override.
            readings.solar_power = self._read_sensor(
                self.config.solar_power_sensor, "solar"
            )
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
            # Manual override — user explicitly set grid power sensors.
            # NO auto-detection runs on this path, so misconfiguration
            # (swapped roles, one side missing, energy counter instead of
            # power sensor) yields a statically wrong grid sign with zero
            # feedback (#461, RienduPre). Validate + audit below.
            self._validate_manual_grid_config(ed, manual_import, manual_export)
            import_w = self._read_sensor(manual_import, "grid_import") if manual_import else 0.0
            export_w = self._read_sensor(manual_export, "grid_export") if manual_export else 0.0
            readings.grid_power = export_w - import_w
            self._grid_sign_detected = True
            self._audit_manual_grid_sign(readings.grid_power, ed)
        elif ed.grid_power_from and ed.grid_power_to:
            # #553 — declared two-sensor pair from HA's grid dialog
            # (power_config.stat_rate_from/to). Same semantics as the manual
            # override above: grid_power = export − import, both sensors
            # always positive; the convention is fixed BY DECLARATION so no
            # sign auto-detection runs (nothing to detect).
            import_w = self._read_sensor(ed.grid_power_from, "grid_import")
            export_w = self._read_sensor(ed.grid_power_to, "grid_export")
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
            # The same-device lock only holds for a COMPLETE pair
            # (#485 H2): an import-only same-device pick used to stop
            # re-discovery entirely, so a later-loading export sensor
            # was never adopted until restart.
            locked = (
                disc["confidence"] == "same-device"
                and disc["import"] and disc["export"]
            )
            if not locked and self._split_grid_scan_due(disc):
                # Re-discovery runs while we don't hold a same-device lock,
                # but new ANY-DEVICE picks are only ADOPTED when (a) we have
                # no working picks yet, (b) the new match is a same-device
                # upgrade (deterministic), or (c) a current pick has gone
                # unavailable. Unconditional adoption let a flicker in HA's
                # state-list iteration order swap which sensor plays import
                # vs export, flipping the computed grid_power sign — the
                # root cause for #461 (Growatt sign inversion that
                # "sometimes works, sometimes inverted"). The late-loading
                # DSMR case (#166) still works: until a pick exists, every
                # cycle re-discovers; once a pick dies, re-adoption is
                # allowed again. With healthy two-sided picks held the
                # full sensor scan only runs periodically for the
                # same-device upgrade case (#485 H3 — the result was
                # otherwise computed and discarded every cycle).
                _prev_imp = disc["import"]
                _prev_exp = disc["export"]
                imp, exp, conf = self._discover_split_grid_power(ed)
                if self._should_adopt_split_grid_picks(disc, conf):
                    disc["import"] = imp
                    disc["export"] = exp
                    disc["confidence"] = conf
                    if (_prev_imp is not None or _prev_exp is not None) and (
                        _prev_imp != imp or _prev_exp != exp
                    ):
                        _LOGGER.warning(
                            "Split-grid sensor picks changed mid-run "
                            "(confidence=%s) — import: %s → %s, export: %s → %s. "
                            "This flips the computed grid_power sign if the new "
                            "picks identify the meters in the opposite role. "
                            "Set grid_import_power_entity / "
                            "grid_export_power_entity explicitly in the "
                            "config to lock the picks. (#461)",
                            conf, _prev_imp, imp, _prev_exp, exp,
                        )
                elif exp and disc["import"] and not disc["export"]:
                    # #485 H2: a late-loading export sensor completes a
                    # one-sided pick. The held import stays locked — only
                    # the MISSING side is filled (wholesale adoption here
                    # could re-roll the import side from an arbitrary
                    # any-device scan). The import-missing mirror case is
                    # covered by the gate (no import pick → adopt all).
                    disc["export"] = exp
                    _LOGGER.info(
                        "Split-grid export sensor appeared after the "
                        "import-only adoption — completing the pair: "
                        "import=%s (held), export=%s",
                        disc["import"], exp,
                    )
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
        # #553 — a battery "unit" is either a combined power entity OR a
        # two-sensor pair (#551). Multi-battery handling counts both.
        n_units = len(ed.battery_power_list) + len(ed.battery_power_pairs)
        # Per-battery breakdown is DECOUPLED from fleet-scalar selection: the
        # ``readings.batteries`` surface (which feeds the per-battery
        # ``sensor.sem_battery_b*`` entities AND the actuator's
        # ``BatteryRuntime.last_known_w``) is populated whenever the Energy
        # Dashboard exposes ≥2 battery units — INDEPENDENTLY of which sensor
        # supplies the fleet scalar. #597 inserted the ``battery_power_sensor``
        # override ABOVE this loop, which silently suppressed every per-battery
        # sensor for any multi-battery install that ALSO set the combined
        # override (#623: RienduPre's 2×Sessy fleet lost all individual battery
        # info). Mirrors the per-battery SOC path below and the per-inverter /
        # per-PV-string surfaces, which are already decoupled.
        per_battery_total = None
        if n_units > 1:
            per_battery_total = 0.0
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
                per_battery_total += w
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
            # #553 — two-sensor pair units, bids continue after the combined
            # ones. net = charge(to) − discharge(from); the user-declared
            # pair IS the sign convention, so these are never sign-flipped.
            for k, (p_from, p_to) in enumerate(ed.battery_power_pairs):
                bid = f"b{len(ed.battery_power_list) + k + 1}"
                w = (self._read_sensor(p_to, "battery")
                     - self._read_sensor(p_from, "battery"))
                per_battery_total += w
                soc_val = 0.0
                soc_entity = self._auto_detect_battery_soc(p_to)
                if soc_entity:
                    s = self._read_sensor(
                        soc_entity, "battery_soc", allow_none=True,
                    )
                    if s is not None and s >= 0:
                        soc_val = s
                readings.batteries[bid] = BatteryPower(
                    battery_id=bid, power_w=w, soc_pct=soc_val, name=p_to,
                )

        # Fleet scalar precedence: a real ≥2 per-battery breakdown owns the fleet
        # total (rebuilt sign-corrected in ``read_power``'s per_battery_mode →
        # #404/#589 consistency-by-construction). The explicit SEM
        # ``battery_power_sensor`` override (#597) applies only when there is no
        # such breakdown to sum — e.g. a Huawei install whose ED exposes battery
        # ENERGY only (``batt:pwr=none``). Read via ``_read_sensor(..., "battery")``
        # (same call the ED combined path uses); the ED ``battery_power_inverted``
        # flag is intentionally NOT applied to the override — that flag describes
        # HA's ED dialog sensor, whereas the SEM override is assumed already in SEM
        # convention (and if it isn't, the battery-sign detector self-corrects and
        # the manual flip service is the escape hatch). Mirrors the SOC override
        # precedence below.
        if per_battery_total is not None:
            readings.battery_power = per_battery_total
        elif self.config.battery_power_sensor:
            readings.battery_power = self._read_sensor(
                self.config.battery_power_sensor, "battery"
            )
        elif ed.battery_power:
            raw_batt = self._read_sensor(ed.battery_power, "battery")
            # #551 — the user chose "Inverted" in HA's battery dialog
            # (power_config.stat_rate_inverted): flip on read so the rest of
            # the pipeline sees the declared convention.
            if ed.battery_power_inverted:
                raw_batt = -raw_batt
            readings.battery_power = raw_batt
        elif ed.battery_power_from and ed.battery_power_to:
            # #551 — "Two sensors" battery power_config (e.g. Fronius Verto):
            # separate charge/discharge sensors, NO combined entity exists.
            # net = charge − discharge (SEM convention: positive = charging).
            charge_w = self._read_sensor(ed.battery_power_to, "battery")
            discharge_w = self._read_sensor(ed.battery_power_from, "battery")
            readings.battery_power = charge_w - discharge_w

        # Battery SOC — precedence (#551): SEM's own explicit override
        # (battery_soc_sensor option) > multi-battery average (the fleet SOC
        # must not be dominated by ONE source's stat_soc) > the entity the
        # user configured in HA's Energy Dashboard battery dialog (stat_soc —
        # deterministic, no guessing) > device-registry auto-detect.
        # Use allow_none so 0% SOC is distinguishable from "unavailable"
        soc_val = None
        ed_soc = ed.battery_soc
        if self.config.battery_soc_sensor:
            soc_val = self._read_sensor(
                self.config.battery_soc_sensor, "battery_soc", allow_none=True,
            )
        elif n_units > 1:
            # Multi-battery installs keep the per-battery average (a single
            # stat_soc from one source must not masquerade as the fleet SOC).
            # #553 — pair units contribute via their charge-power entity's
            # device (same auto-detect heuristic).
            soc_val = self._read_battery_soc_average(
                ed.battery_power_list + [to for _, to in ed.battery_power_pairs]
            ) or None
        elif ed_soc:
            soc_val = self._read_sensor(ed_soc, "battery_soc", allow_none=True)
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
        # Sum the per-charger power sensors whenever ANY charger carries a
        # nested ``ev_charging_power_sensor`` — including a SINGLE charger
        # defined through the modern config-flow ``ev_chargers`` list (its
        # sensor lives inside the list entry, not at top level). The old
        # ``len > 1`` guard skipped the single-charger-in-list case, so its
        # fleet ``ev_power`` fell through to the (empty) legacy top-level
        # sensor and read 0 — the EV's own draw then masqueraded as a home
        # consumption spike and the surplus budget oscillated (flap). Falls
        # through to ED / top-level only when NO charger has a nested sensor,
        # so legacy single-charger configs keep working.
        if self._read_ev_fleet_power(readings, ev_chargers):
            pass  # nested per-charger sensors handled the read (#642 helper)
        elif ed.ev_power:
            readings.ev_power = FleetEvPower(self._smooth_ev_power(
                self._read_sensor(ed.ev_power, "ev")))
        elif self.config.ev_power_sensor:
            readings.ev_power = FleetEvPower(self._smooth_ev_power(
                self._read_sensor(self.config.ev_power_sensor, "ev")
            ))

        # EV connection status — per-charger OR'd for global (#193), plus
        # per-charger maps so ``build_charger_view`` can gate each charger's
        # ``decide()`` on ITS OWN plug state (#584). Without the per-charger
        # maps, build_view falls back to the fleet OR — so a car on ONE
        # charger made SEM command a solar charge (and fire a "charging
        # started" push) on every OTHER car-less charger in the fleet.
        # ``ev_chargers`` is already in scope from the EV-power block above.
        self._read_ev_connection_status(readings, ev_chargers)

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

        # #584 follow-up: mirror the physics defence into the per-charger
        # map. build_charger_view now reads that map FIRST, so a fleet-only
        # correction wouldn't reach the specific charger whose plug sensor
        # lies — re-exposing #285+1 for multi-charger installs.
        self._infer_per_charger_connection_from_physics(readings)

        # Battery temperature (#564: configured sensor, else device sibling)
        self._read_battery_temperature(readings)
        # Inverter temperature (#564: configured sensor, else device sibling)
        self._read_inverter_temperature(readings)

        return readings

    def _read_battery_temperature(self, readings) -> None:
        """(#564) Fill battery_temperature honestly.

        Priority: the configured sensor, else a temperature-class sibling
        on the same device as the battery SOC/power sensor (Fronius & co.
        expose a cell temperature there). NO source → stays None and the
        entity shows *unknown* — the old fabricated 25.0 °C default was
        displayed as a real reading.
        """
        entity = (
            self.config.battery_temperature_sensor
            or self._autodetect_battery_temperature()
        )
        if not entity:
            return
        state = self.hass.states.get(entity)
        if not state or state.state in ("unknown", "unavailable", None):
            return
        try:
            readings.battery_temperature = float(state.state)
        except (ValueError, TypeError):
            return

    def _autodetect_battery_temperature(self) -> Optional[str]:
        """Find a temperature sensor on the battery's own device.

        Cached once found; a miss retries every 5 minutes (source
        integrations load late at boot).
        """
        if self._battery_temp_entity:
            return self._battery_temp_entity
        import time as _time
        now = _time.monotonic()
        if now - self._battery_temp_probe_mono < 300:
            return None
        self._battery_temp_probe_mono = now

        # Reuse the battle-tested hardware detection the dashboard's K-Flow
        # card already relies on (brand-aware battery_temp1 regexes) —
        # ONE source of truth instead of a parallel scan.
        ed = getattr(self, "_energy_dashboard_config", None)
        if ed is None:
            return None
        try:
            from ..hardware_detection import discover_battery_details_from_registry
            details = discover_battery_details_from_registry(self.hass, ed)
        except Exception as e:  # noqa: BLE001 — registry absent in tests
            _LOGGER.debug("Battery temperature autodetect skipped: %s", e)
            return None
        entity = details.get("battery_temp1")
        if entity:
            self._battery_temp_entity = entity
            _LOGGER.info("Battery temperature autodetected: %s", entity)
        return entity

    def _read_inverter_temperature(self, readings) -> None:
        """(#564) Fill inverter_temperature honestly.

        Priority: the configured sensor, else the ``inv_temp`` sibling on the
        inverter's device (brand-aware detection). NO source → stays None and
        the entity shows *unknown*. Previously the system diagram showed the
        BATTERY temperature in the inverter slot (a fabricated ~25 °C).
        """
        entity = (
            self.config.inverter_temperature_sensor
            or self._autodetect_inverter_temperature()
        )
        if not entity:
            return
        state = self.hass.states.get(entity)
        if not state or state.state in ("unknown", "unavailable", None):
            return
        try:
            readings.inverter_temperature = float(state.state)
        except (ValueError, TypeError):
            return

    def _autodetect_inverter_temperature(self) -> Optional[str]:
        """Find the inverter temperature sensor via hardware detection.

        Cached once found; a miss retries every 5 minutes (source
        integrations load late at boot). Shares the ``inv_temp`` result from
        the same detection the battery temperature uses.
        """
        if self._inverter_temp_entity:
            return self._inverter_temp_entity
        import time as _time
        now = _time.monotonic()
        if now - self._inverter_temp_probe_mono < 300:
            return None
        self._inverter_temp_probe_mono = now

        ed = getattr(self, "_energy_dashboard_config", None)
        if ed is None:
            return None
        try:
            from ..hardware_detection import discover_battery_details_from_registry
            details = discover_battery_details_from_registry(self.hass, ed)
        except Exception as e:  # noqa: BLE001 — registry absent in tests
            _LOGGER.debug("Inverter temperature autodetect skipped: %s", e)
            return None
        entity = details.get("inv_temp")
        if entity:
            self._inverter_temp_entity = entity
            _LOGGER.info("Inverter temperature autodetected: %s", entity)
        return entity

    def _validate_manual_grid_config(
        self, ed, manual_import: Optional[str], manual_export: Optional[str],
    ) -> None:
        """One-shot sanity checks on explicitly configured grid entities (#461).

        Each finding warns once per install run (keyed per entity / shape):

        * Entity is an ENERGY counter (kWh device-class/unit) — the manual
          fields take POWER sensors; a counter reads as a huge pseudo-watt
          value and swamps ``grid_power = export - import``.
        * Only one side is configured while the Energy Dashboard has BOTH
          flow counters — the missing side reads a hard 0 W, so the grid
          can never show that direction ("always exporting" / "always
          importing").
        """
        for role, eid in (("import", manual_import), ("export", manual_export)):
            if not eid or eid in self._manual_grid_config_warned:
                continue
            state = self.hass.states.get(eid)
            if state is None:
                continue  # unavailability is handled by _read_sensor/Repairs
            unit = (state.attributes.get("unit_of_measurement") or "").lower()
            device_class = state.attributes.get("device_class")
            if device_class == "energy" or unit in ("wh", "kwh", "mwh"):
                self._manual_grid_config_warned.add(eid)
                _LOGGER.warning(
                    "grid_%s_power_entity is set to %s, which is an ENERGY "
                    "counter (%s) — this field takes a POWER sensor (W/kW). "
                    "The computed grid power will be wrong until this is "
                    "fixed in the SEM config. (#461)",
                    role, eid, unit or device_class,
                )
        one_sided = bool(manual_import) != bool(manual_export)
        if (
            one_sided
            and "__one_sided__" not in self._manual_grid_config_warned
            and getattr(ed, "grid_import_energy", None)
            and getattr(ed, "grid_export_energy", None)
        ):
            self._manual_grid_config_warned.add("__one_sided__")
            missing = "grid_export_power_entity" if manual_import else "grid_import_power_entity"
            _LOGGER.warning(
                "Only one manual grid power entity is configured (%s is "
                "missing) while the Energy Dashboard tracks BOTH import and "
                "export. The missing side always reads 0 W, so SEM can never "
                "see that flow direction — the energy flow will look stuck "
                "on one side. Configure both entities (or neither). (#461)",
                missing,
            )

    @staticmethod
    def _counter_deltas(
        prev_a: Optional[float], prev_b: Optional[float],
        new_a: float, new_b: float,
    ) -> Optional[tuple]:
        """Delta pair for a counter couple, with the reset guard (#476).

        Single home for the counter-reset threshold (#485 K4 — the
        grid voter, the per-battery voter, and the manual-grid audit
        each hand-rolled this with the same magic number). Some
        inverters (Growatt) reset daily counters at midnight, and the
        two counters can reset in DIFFERENT cycles — a negative delta
        on either side means BOTH deltas are garbage this cycle (the
        surviving side could still cast a wrong vote). Returns ``None``
        on a reset; the caller re-baselines and sits the cycle out.
        """
        if prev_a is None or prev_b is None:
            return None
        delta_a = new_a - prev_a
        delta_b = new_b - prev_b
        if delta_a < -0.001 or delta_b < -0.001:
            return None
        return delta_a, delta_b

    def _sum_counter_states(self, entity_ids: list) -> Optional[float]:
        """Sum energy-counter states; ``None`` when any is unreadable.

        Partial sums are worse than no judgement — one missing tariff
        counter mid-cycle would look like a counter reset.
        """
        total = 0.0
        for eid in entity_ids:
            state = self.hass.states.get(eid)
            if not state or state.state in ("unknown", "unavailable"):
                return None
            try:
                total += float(state.state)
            except (ValueError, TypeError):
                return None
        return total

    def _audit_manual_grid_sign(self, grid_power: float, ed) -> None:
        """Observe-only cross-check of the manual grid sign (#461).

        The Energy Dashboard's import/export counters are ground truth for
        flow DIRECTION. Under SEM convention (negative = import), the
        import counter growing while the manual-computed ``grid_power`` is
        positive (or export growing while it's negative) means the manual
        entities are assigned in swapped roles — or the wrong sensors
        entirely. Five consecutive contradictions set
        ``_manual_grid_mismatch`` (surfaced as ``diag_grid_manual_mismatch``)
        and log one WARNING naming the configured entities.

        Observe-only by design: manual config is explicit user intent, so
        SEM never silently re-flips it — it makes the misconfiguration loud
        instead.

        Delegates to ``_manual_grid_audit`` (CounterCorrelationAudit).
        Counter-A = import (rising ↔ grid_power < 0 under SEM convention,
        i.e. ``positive_power_means_a=False`` since positive = export).
        """
        # Sum across the counter LISTS when present — Dutch dual-tariff
        # DSMR meters split each direction into tarief 1 + tarief 2
        # counters; judging from one tariff's counter alone leaves the
        # audit blind during the other tariff's hours.
        import_entities = (
            list(getattr(ed, "grid_import_energy_list", None) or [])
            or ([ed.grid_import_energy] if getattr(ed, "grid_import_energy", None) else [])
        )
        export_entities = (
            list(getattr(ed, "grid_export_energy_list", None) or [])
            or ([ed.grid_export_energy] if getattr(ed, "grid_export_energy", None) else [])
        )
        if not import_entities or not export_entities:
            return
        if abs(grid_power) < 100:
            return  # too little flow to judge direction
        import_val = self._sum_counter_states(import_entities)
        export_val = self._sum_counter_states(export_entities)
        if import_val is None or export_val is None:
            return

        # counter-A = import, counter-B = export.
        # positive_power_means_a=False: grid_power > 0 means export (B rising).
        signal = self._manual_grid_audit.update(
            import_val, export_val,
            positive_power_means_a=False,
            power_positive=grid_power > 0,
            counter_deltas_fn=self._counter_deltas,
        )
        if signal == "clear":
            _LOGGER.info(
                "Manual grid entities agree with the Energy Dashboard "
                "counters again — clearing the mismatch flag."
            )
        elif signal == "warn":
            # Reconstruct the human-readable context for the warning.
            manual_says_export = grid_power > 0
            # Which counter was rising at the moment the threshold was crossed?
            # We can infer from the current baselines vs prior: the audit has
            # already updated the baselines, so we re-derive the direction from
            # the last delta pair.  Instead, derive from the power sign to avoid
            # re-computing: if manual_says_export but audit fired, the import
            # counter must have been rising.
            _LOGGER.warning(
                "Manual grid power entities CONTRADICT the Energy "
                "Dashboard counters for 5+ cycles: SEM computes %s "
                "(grid_power=%.0f W) while the %s counter is the one "
                "increasing. grid_import_power_entity=%s / "
                "grid_export_power_entity=%s are most likely SWAPPED "
                "(or point at the wrong meters). SEM does not override "
                "manual config — fix the two fields in the SEM config. "
                "(#461)",
                "EXPORT" if manual_says_export else "IMPORT",
                grid_power,
                "import" if manual_says_export else "export",
                self._raw_config.get("grid_import_power_entity"),
                self._raw_config.get("grid_export_power_entity"),
            )

    def _audit_autodetect_grid_sign(self, grid_power: float, ed) -> None:
        """Observe-only post-lock contradiction check for the auto-detected grid sign (#589).

        Mirrors ``_audit_manual_grid_sign`` exactly but targets the auto/
        counter/solar/restored lock path (i.e. NOT the manual entity override).
        Five consecutive contradictions set ``_grid_sign_lock_contradiction``
        (surfaced as ``diag_grid_sign_contradiction``) and log one WARNING.

        Observe-only by design: never re-flips the sign — makes a wrong
        lock loud instead.

        Delegates to ``_grid_sign_audit`` (CounterCorrelationAudit).
        Counter-A = import; positive_power_means_a=False (positive = export).
        """
        import_entities = (
            list(getattr(ed, "grid_import_energy_list", None) or [])
            or ([ed.grid_import_energy] if getattr(ed, "grid_import_energy", None) else [])
        )
        export_entities = (
            list(getattr(ed, "grid_export_energy_list", None) or [])
            or ([ed.grid_export_energy] if getattr(ed, "grid_export_energy", None) else [])
        )
        if not import_entities or not export_entities:
            return
        if abs(grid_power) < 100:
            return
        import_val = self._sum_counter_states(import_entities)
        export_val = self._sum_counter_states(export_entities)
        if import_val is None or export_val is None:
            return

        signal = self._grid_sign_audit.update(
            import_val, export_val,
            positive_power_means_a=False,
            power_positive=grid_power > 0,
            counter_deltas_fn=self._counter_deltas,
        )
        if signal == "clear":
            _LOGGER.info(
                "Auto-detected grid sign now agrees with the Energy Dashboard "
                "counters again — clearing the grid sign contradiction flag. (#589)"
            )
        elif signal == "warn":
            lock_says_export = grid_power > 0
            _LOGGER.warning(
                "Auto-detected grid sign CONTRADICTS the Energy Dashboard "
                "counters for 5+ cycles: SEM computes %s (grid_power=%.0f W) "
                "while the %s counter is the one increasing. The locked "
                "grid sign convention may be wrong. Use the 'Fix grid sign' "
                "button in the SEM Config tab to correct it. (#589)",
                "EXPORT" if lock_says_export else "IMPORT",
                grid_power,
                "import" if lock_says_export else "export",
            )

    def _audit_battery_sign_lock(self, battery_power: float, ed) -> None:
        """Observe-only post-lock contradiction check for the fleet battery sign (#589).

        Runs only when the fleet battery sign is locked
        (``_battery_sign_detected[__fleet__]`` is True). Compares the
        sign-corrected ``battery_power`` against which Energy Dashboard energy
        counter (charge vs discharge) is rising.

        SEM convention (from types.py):
          battery_power > 0  → charging    → charge counter should be rising
          battery_power < 0  → discharging → discharge counter should be rising

        Five consecutive contradictions set ``_battery_sign_contradiction``
        (surfaced as ``diag_battery_sign_contradiction``) and log one WARNING.

        Observe-only by design: never re-flips the sign.
        Uses ``_battery_audit_charge_baseline`` / ``_battery_audit_discharge_baseline``
        so the voter's ``_battery_charge_baseline`` is never disturbed.

        Delegates to ``_battery_sign_audit`` (CounterCorrelationAudit).
        Counter-A = charge; positive_power_means_a=True (positive = charging).
        """
        if not self._battery_sign_detected.get(self._FLEET_BID):
            return
        if abs(battery_power) < 100:
            return

        charge_entities = (
            list(getattr(ed, "battery_charge_energy_list", None) or [])
            or ([ed.battery_charge_energy] if getattr(ed, "battery_charge_energy", None) else [])
        )
        discharge_entities = (
            list(getattr(ed, "battery_discharge_energy_list", None) or [])
            or ([ed.battery_discharge_energy] if getattr(ed, "battery_discharge_energy", None) else [])
        )
        if not charge_entities or not discharge_entities:
            return

        charge_val = self._sum_counter_states(charge_entities)
        discharge_val = self._sum_counter_states(discharge_entities)
        if charge_val is None or discharge_val is None:
            return

        # counter-A = charge, counter-B = discharge.
        # positive_power_means_a=True: battery_power > 0 means charging (A rising).
        signal = self._battery_sign_audit.update(
            charge_val, discharge_val,
            positive_power_means_a=True,
            power_positive=battery_power > 0,
            counter_deltas_fn=self._counter_deltas,
        )
        if signal == "clear":
            _LOGGER.info(
                "Battery sign now agrees with the Energy Dashboard "
                "counters again — clearing the battery sign contradiction flag. (#589)"
            )
        elif signal == "warn":
            power_says_charging = battery_power > 0
            charge_ent = charge_entities[0] if charge_entities else "unknown"
            discharge_ent = discharge_entities[0] if discharge_entities else "unknown"
            _LOGGER.warning(
                "Battery sign CONTRADICTS the Energy Dashboard counters "
                "for 5+ cycles: SEM computes battery_power=%.0f W (%s) "
                "while the %s counter (%s / %s) is the one increasing. "
                "The locked battery sign convention may be wrong. Use "
                "'Reset sign detection' in the SEM Config tab to clear "
                "the lock and re-learn it. (#589)",
                battery_power,
                "CHARGING" if power_says_charging else "DISCHARGING",
                "discharge" if power_says_charging else "charge",
                charge_ent,
                discharge_ent,
            )

    # With healthy two-sided any-device picks held, re-scan only every
    # N cycles for the same-device upgrade case (#485 H3). At the
    # default ~10s update interval this is one scan per ~5 minutes.
    _SPLIT_GRID_UPGRADE_SCAN_CYCLES = 30

    def _split_grid_scan_due(self, disc: dict) -> bool:
        """Whether the full split-grid sensor scan is worth running (#485 H3).

        The scan iterates every sensor state + does registry lookups;
        running it per cycle just to discard the result (the adopt gate
        refuses healthy held picks) wasted the work on every update.
        Scan every cycle while a side is missing or a held pick is
        unavailable (the adoption / recovery paths), otherwise only
        periodically for the same-device upgrade chance.
        """
        if not disc.get("import") and not disc.get("export"):
            return True  # nothing held → scan every cycle (#166)
        if not disc.get("import") or not disc.get("export"):
            # One side held, other missing (#485 H2): keep looking for
            # the late-loading side, but at ~1-min cadence — systems
            # that genuinely lack one sensor would otherwise pay the
            # full scan every cycle forever.
            countdown = disc.get("one_sided_scan_countdown", 0) - 1
            if countdown <= 0:
                disc["one_sided_scan_countdown"] = 6
                return True
            disc["one_sided_scan_countdown"] = countdown
            return False
        for side in ("import", "export"):
            state = self.hass.states.get(disc[side])
            if state is None or state.state in ("unavailable", "unknown"):
                return True  # recovery path — re-discover now
        countdown = disc.get("upgrade_scan_countdown", 0) - 1
        if countdown <= 0:
            disc["upgrade_scan_countdown"] = self._SPLIT_GRID_UPGRADE_SCAN_CYCLES
            return True
        disc["upgrade_scan_countdown"] = countdown
        return False

    def _should_adopt_split_grid_picks(self, disc: dict, new_confidence) -> bool:
        """Gate adopting freshly discovered split-grid picks (#461).

        Any-device discovery pattern-matches over ``hass.states.async_all``,
        whose iteration order isn't contractual — re-running it every cycle
        and adopting the result unconditionally let the import/export
        assignment swap mid-run, inverting the computed grid sign. Adopt
        only when:

        * we hold no import pick yet (initial discovery / late-loading
          DSMR meter, #166), or
        * the new match is ``same-device`` (deterministic — locks
          permanently at the call site), or
        * a currently held pick has gone unavailable (sensor renamed or
          integration reloaded — re-discovery is the recovery path).

        Otherwise the held picks win: stability over freshness.
        """
        if not disc.get("import"):
            return True
        if new_confidence == "same-device":
            return True
        for side in ("import", "export"):
            eid = disc.get(side)
            if not eid:
                continue
            state = self.hass.states.get(eid)
            if state is None or state.state in ("unavailable", "unknown"):
                return True
        return False

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

            # Deterministic candidate order (#485 H6): async_all's
            # iteration order isn't contractual, and any-device picks
            # are first-match-wins — an unsorted scan could re-roll
            # which sensor plays import vs export across restarts,
            # silently swapping the grid sign (the first-adoption case
            # the mid-run swap WARNING can't see).
            for state in sorted(
                self.hass.states.async_all("sensor"),
                key=lambda s: s.entity_id,
            ):
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
                # Log at INFO only when the result CHANGED (#485 H3) —
                # the periodic upgrade scan re-finding the same pair
                # wrote one INFO line per scan into the log + the
                # diagnose ring buffer.
                result_key = (import_power, export_power, confidence)
                if result_key != self._last_split_grid_log:
                    self._last_split_grid_log = result_key
                    _LOGGER.info(
                        "Discovered split grid power sensors (%s): import=%s, export=%s",
                        confidence, import_power, export_power,
                    )
                else:
                    _LOGGER.debug(
                        "Split grid power re-scan unchanged (%s): import=%s, export=%s",
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
        self._last_split_grid_log = None  # next discovery logs at INFO again

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

        # Battery temperature (#564: configured sensor, else device sibling)
        self._read_battery_temperature(readings)
        # Inverter temperature (#564: configured sensor, else device sibling)
        self._read_inverter_temperature(readings)

        # EV power — sum the per-charger sensors whenever ANY charger has a
        # nested one (incl. a single config-flow charger); see the primary
        # block above for why ``len > 1`` was wrong (single-charger-in-list
        # read ev_power=0 → false home spike → surplus-budget flap).
        ev_chargers = self._raw_config.get("ev_chargers", [])
        if self._read_ev_fleet_power(readings, ev_chargers):
            pass  # nested per-charger sensors handled the read (#642 helper)
        elif self.config.ev_power_sensor:
            readings.ev_power = FleetEvPower(self._smooth_ev_power(
                self._read_sensor(self.config.ev_power_sensor, "ev")
            ))

        # EV connection status — per-charger OR'd for global (#193), plus
        # per-charger maps so build_charger_view gates each charger on its
        # OWN plug state (#584). Mirror of the energy-dashboard path above.
        # ``ev_chargers`` is still in scope from the EV-power block above.
        self._read_ev_connection_status(readings, ev_chargers)

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

        # #584 follow-up — see the energy-dashboard path for the rationale.
        self._infer_per_charger_connection_from_physics(readings)

        return readings

    def _read_ev_fleet_power(self, readings, ev_chargers) -> bool:
        """(#642) ONE fleet + per-charger EV power read, shared by BOTH read
        paths (energy-dashboard and legacy) — the ``_read_ev_connection_status``
        precedent (#616), applied to the ev_power sibling.

        The two hand-maintained copies had already drifted: the legacy path
        smoothed the fleet SUM (one median over the sum half-passes a single
        charger's UDP 0-blip) and never populated ``ev_power_per_charger`` —
        so on a legacy-path multi-charger install ``build_charger_view``'s
        fleet fallback fed every charger the whole fleet draw (the
        #556/#616 per-charger-reads-fleet-sum class, again).

        Returns True when ANY charger carries a nested
        ``ev_charging_power_sensor`` (the read is then complete, per-charger
        smoothed, dict populated); False lets the caller run its own
        fallback chain (ED sensor / legacy top-level sensor).

        Chargers without a nested power sensor (misconfig) are excluded from
        both the dict AND the fleet sum — consumers must ``.get(cid)``.
        """
        if not any(c.get("ev_charging_power_sensor") for c in ev_chargers):
            return False
        total_ev = 0.0
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id")
            cps = charger_cfg.get("ev_charging_power_sensor")
            if cps:
                # Smooth per charger so the per-charger dict stays
                # consistent with the fleet sum (both blip-filtered).
                cw = self._smooth_ev_power(
                    self._read_sensor(cps, "ev"), key=cid or cps,
                )
                total_ev += cw
                if cid:
                    # Per-charger draw in watts, exposed for
                    # ``flow_calculator`` per-charger split and
                    # ``build_charger_view``'s this-charger read.
                    readings.ev_power_per_charger[cid] = cw
        # total_ev is already the sum of smoothed per-charger values.
        readings.ev_power = FleetEvPower(total_ev)
        return True

    def _smooth_ev_power(self, raw: float, key: str = "_fleet") -> float:
        """Median-of-3 filter for EV power (2026-07-10 flap fix).

        UDP-polled chargers (KEBA P30) blip to ~0 for a single cycle while
        the car is really drawing. Left raw, that blip corrupts the home
        energy balance and collapses the EV surplus/budget (see
        ``__init__``). The median of the last three readings passes a
        single-cycle blip through unchanged (``[10450, 0, 10450] → 10450``)
        while still tracking a genuine start/stop within one cycle
        (``[10450, 0, 0] → 0``). Warm-up (< 3 samples) returns raw.

        ``key`` scopes the history: a per-charger id keeps each charger's
        own median so the ``ev_power_per_charger`` dict stays consistent
        with the smoothed fleet sum; the default ``"_fleet"`` key smooths a
        single fleet-level sensor.
        """
        hist = self._ev_power_hist.get(key)
        if hist is None:
            hist = self._ev_power_hist[key] = deque(maxlen=3)
        hist.append(float(raw))
        if len(hist) < 3:
            return float(raw)
        return sorted(hist)[1]

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
            # (HA Repairs) Stamp the outage start AND escalate to a
            # Repair issue once we cross the threshold. Quiet for
            # transient flaps; user-visible for real outages.
            import time as _time
            now_mono = _time.monotonic()
            if entity_id not in self._sensor_unavailable_since:
                self._sensor_unavailable_since[entity_id] = now_mono
            elif entity_id not in self._sensor_repair_raised:
                from . import repair_issues as _ri
                outage_s = now_mono - self._sensor_unavailable_since[entity_id]
                if outage_s >= _ri.UNAVAILABLE_REPAIR_THRESHOLD_S:
                    friendly = None
                    if state is not None:
                        friendly = state.attributes.get("friendly_name")
                    _ri.raise_sensor_unavailable(
                        self.hass, entity_id,
                        friendly_name=friendly,
                        minutes_unavailable=int(outage_s // 60),
                    )
                    self._sensor_repair_raised.add(entity_id)
            return None if allow_none else 0.0

        try:
            value = float(state.state)

            # Convert kW to W if needed
            unit = state.attributes.get("unit_of_measurement", "")
            if unit.lower() == "kw":
                value *= 1000

            # Detect transition from unavailable → available. Demoted
            # to DEBUG so a flapping upstream sensor (e.g. Huawei
            # modbus over WiFi, common to bounce every 10-30 s) does
            # not spam INFO for every sensor on every recovery cycle.
            # Symmetric with the DEBUG unavailability log a few lines
            # above — recovery isn't user-actionable. Quality-scale
            # feedback 2026-06-06: "should handle unavailability
            # gracefully instead of spamming".
            if entity_id in self._sensor_unavailable:
                self._sensor_unavailable.discard(entity_id)
                _LOGGER.debug(
                    "Sensor %s (%s) recovered — now reading %.1f",
                    entity_id, name, value,
                )
                # (HA Repairs) Reset the outage clock and clear any
                # Repair issue we may have filed for this sensor.
                self._sensor_unavailable_since.pop(entity_id, None)
                if entity_id in self._sensor_repair_raised:
                    self._sensor_repair_raised.discard(entity_id)
                    from . import repair_issues as _ri
                    _ri.clear_sensor_unavailable(self.hass, entity_id)

            # W3 — observe-only frozen-sensor detection (does NOT alter value).
            # Wrapped so the audit can NEVER corrupt the read: an exception here
            # would otherwise hit the outer except → a wrong 0.0.
            try:
                self._audit_sensor_freshness(entity_id, name, state)
            except Exception:  # noqa: BLE001 — freshness must never break a read
                pass
            return value
        except (ValueError, TypeError) as e:
            _LOGGER.debug(f"Could not parse {entity_id} ({name}): {e}")
            return None if allow_none else 0.0

    def _audit_sensor_freshness(self, entity_id: str, name: str, state) -> None:
        """W3 — warn ONCE when a FAST power sensor is available but frozen.

        Only ``solar``/``grid``/``battery`` power sensors are checked (they
        update every few seconds, so a >10 min gap means the upstream
        integration stalled — Huawei modbus, Growatt cloud). Observe-only: the
        value is returned unchanged; this makes the freeze VISIBLE in the log
        (the #461/#462 triage blind spot) so a silently-stale reading poisoning
        the balance + sign detection is diagnosable. The generous threshold +
        fast-power-only scoping means a legitimately slow sensor never trips.
        """
        if name not in self._FAST_POWER_NAMES:
            return
        # Freshness = time since the entity last *reported* its state, NOT since
        # its value last *changed*. HA only advances ``last_updated`` when the
        # state/attributes actually change; ``last_reported`` advances on every
        # write to the state machine, even when the value is identical. A fast
        # power sensor legitimately holds a constant value for long stretches —
        # a split discharge-power sensor sits at 0 W while the battery charges
        # (Fronius exposes separate charge + discharge sensors), grid_export is
        # 0 while importing, solar is 0 overnight — and would look "frozen" for
        # >10 min on ``last_updated`` though it is reporting fine every poll
        # (#611). Only a genuine upstream stall (modbus/cloud) freezes
        # ``last_reported`` too. Fall back to ``last_updated`` when
        # ``last_reported`` is absent (pre-2024.4 HA / a test mock).
        last_seen = getattr(state, "last_reported", None)
        if last_seen is None:
            last_seen = getattr(state, "last_updated", None)
        if last_seen is None:
            return
        try:
            import homeassistant.util.dt as _dt
            age_s = (_dt.utcnow() - last_seen).total_seconds()
        except Exception:  # noqa: BLE001 — never break a read over freshness
            return
        # Guard a non-datetime last_updated (test MagicMock / naive dt): a
        # non-numeric age must never reach ``int(age_s//60)`` below, whose
        # TypeError would be swallowed by _read_sensor's except → wrong 0.0.
        if not isinstance(age_s, (int, float)) or isinstance(age_s, bool):
            return
        if age_s >= self._STALE_THRESHOLD_S:
            if entity_id not in self._frozen_sensors:
                self._frozen_sensors.add(entity_id)
                mins = int(age_s // 60)
                _LOGGER.warning(
                    "Sensor %s (%s) is FROZEN — last reported %d min ago but still "
                    "'available'; its stale value is feeding the energy balance "
                    "and sign detection. Check the upstream integration "
                    "(modbus/cloud stall). (W3)",
                    entity_id, name, mins,
                )
                # (HA Repairs) surface it in the UI, not just the log.
                from . import repair_issues as _ri
                _ri.raise_sensor_stale(
                    self.hass, entity_id,
                    friendly_name=state.attributes.get("friendly_name"),
                    minutes_stale=mins,
                )
        elif entity_id in self._frozen_sensors:
            # Fresh again — re-arm the warn-once, clear the Repair, note recovery.
            self._frozen_sensors.discard(entity_id)
            from . import repair_issues as _ri
            _ri.clear_sensor_stale(self.hass, entity_id)
            _LOGGER.info(
                "Sensor %s (%s) is updating again (was frozen).", entity_id, name,
            )

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

    def _read_ev_connection_status(
        self, readings: PowerReadings, ev_chargers: list,
    ) -> None:
        """Fill ``ev_connected`` / ``ev_charging`` + the per-charger maps.

        Per-charger sensors win whenever ANY charger in the list defines one
        — including a SINGLE config-flow charger whose plug/charging sensors
        live in ``ev_chargers[0]`` rather than the flat top-level keys (#616).
        The old ``len(ev_chargers) > 1`` guard treated a lone charger as
        "no fleet" and fell back to the legacy top-level ``ev_plug_sensor``,
        which is empty when the charger's config lives only in the list — so
        the fleet ``ev_connected`` stayed False while ``charger_<id>_connected``
        (read straight off the charger's own sensor in the coordinator's
        per-charger session loop) was True. ``build_charger_view`` then saw an
        empty per-charger map, fell back to the False fleet OR, and the EV
        policy reported "min_plus_solar but EV disconnected" → commanded 0 A
        forever. This mirrors the ``ev_power`` block, already fixed for the
        exact same single-charger-in-list reason (see the ``any(...)`` guard
        there). Shared by both read paths so the guard can't drift again.

        A signal that NO charger defines still falls back to the legacy
        top-level sensor, so a mixed config (nested plug sensor but a flat
        charging sensor, or vice-versa) isn't silently zeroed.
        """
        has_pc_connected = any(c.get("ev_connected_sensor") for c in ev_chargers)
        has_pc_charging = any(c.get("ev_charging_sensor") for c in ev_chargers)
        if not (has_pc_connected or has_pc_charging):
            readings.ev_connected = self._read_binary_sensor(
                self.config.ev_plug_sensor, "ev_plug"
            )
            readings.ev_charging = self._read_binary_sensor(
                self.config.ev_charging_sensor, "ev_charging"
            )
            return

        any_connected = False
        any_charging = False
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id")
            conn_sensor = charger_cfg.get("ev_connected_sensor")
            chrg_sensor = charger_cfg.get("ev_charging_sensor")
            # Read each sensor exactly once (avoid double side-effects / log
            # spam), then feed both the fleet OR and the per-charger map from
            # the same value.
            pc_connected = bool(
                conn_sensor and self._read_binary_sensor(conn_sensor, "ev_plug")
            )
            pc_charging = bool(
                chrg_sensor and self._read_binary_sensor(chrg_sensor, "ev_charging")
            )
            if pc_connected:
                any_connected = True
            if pc_charging:
                any_charging = True
            # Only populate the map when a per-charger sensor is configured —
            # an absent sensor means we can't know THIS charger's individual
            # state, so leave it unset and let build_view keep the documented
            # fleet-OR fallback.
            if cid and conn_sensor:
                readings.ev_connected_per_charger[cid] = pc_connected
            if cid and chrg_sensor:
                readings.ev_charging_per_charger[cid] = pc_charging
        # Per-signal legacy fallback: if NO charger defines a given sensor,
        # read the flat top-level key so a mixed config (nested plug sensor
        # but a flat charging sensor, or vice-versa) isn't silently zeroed.
        # Restricted to the single/legacy case (``len <= 1``): for a genuine
        # multi-charger fleet the flat keys are just charger[0]'s mirror and
        # were NEVER OR'd in separately by the old ``len > 1`` branch — keep
        # ``any_*`` alone there so this refactor is byte-for-byte behaviour on
        # multi-charger installs.
        single_or_legacy = len(ev_chargers) <= 1
        readings.ev_connected = (
            any_connected if has_pc_connected or not single_or_legacy
            else self._read_binary_sensor(self.config.ev_plug_sensor, "ev_plug")
        )
        readings.ev_charging = (
            any_charging if has_pc_charging or not single_or_legacy
            else self._read_binary_sensor(self.config.ev_charging_sensor, "ev_charging")
        )

    def _infer_per_charger_connection_from_physics(
        self, readings: PowerReadings,
    ) -> None:
        """Mirror the fleet-level physics defence into the per-charger map (#584).

        The fleet ``ev_connected`` correction (a lying plug sensor that
        reports "off" while current flows — #285+1) must also reach the
        per-charger map, because ``build_charger_view`` now gates each
        charger on ITS OWN entry first. Without this, a charger whose plug
        sensor lies during an HA restart would stop being supervised on
        multi-charger fleets — the exact bug #285+1 fixed.

        Attribution is per-charger: only flip a charger whose own power
        sensor shows draw (>100 W rules out standby) or whose own charging
        sensor reads on. The legacy reader path doesn't populate
        ``ev_power_per_charger``, so there it relies on the charging map.
        """
        for cid, connected in list(readings.ev_connected_per_charger.items()):
            if connected:
                continue
            pc_power = readings.ev_power_per_charger.get(cid, 0.0) or 0.0
            pc_charging = readings.ev_charging_per_charger.get(cid, False)
            if pc_power > 100 or pc_charging:
                _LOGGER.warning(
                    "ev_connected_per_charger[%s] inferred from physics: plug "
                    "sensor reported off but power=%.0fW / charging=%s. Treating "
                    "as connected. (#285+1 multi-charger protection.)",
                    cid, pc_power, pc_charging,
                )
                readings.ev_connected_per_charger[cid] = True

    def detect_battery_cycles_sensor(self, battery_anchor_entity: Optional[str]) -> Optional[str]:
        """#593 — autodetect a battery lifetime-cycle sensor on the SAME device
        as the battery power/SOC sensor (keyword scan), so Sonnen/Huawei/etc.
        users get the manufacturer's real cycle count without configuring
        anything. The manual ``battery_cycles_sensor`` override wins over this
        (resolved in the coordinator); this is the primary autodetect path.
        Cached per reader instance. Returns a numeric-validated sensor id or None.
        """
        if getattr(self, "_cycles_sensor_cache", _CYCLES_UNSET) is not _CYCLES_UNSET:
            return self._cycles_sensor_cache
        result = None
        if battery_anchor_entity and "." in battery_anchor_entity:
            try:
                registry = er.async_get(self.hass)
                anchor = registry.async_get(battery_anchor_entity)
                if anchor and anchor.device_id:
                    for entry in er.async_entries_for_device(registry, anchor.device_id):
                        if entry.domain != "sensor":
                            continue
                        eid = entry.entity_id
                        if not any(kw in eid.lower() for kw in _CYCLE_KEYWORDS):
                            continue
                        st = self.hass.states.get(eid)
                        if st is not None and st.state not in ("unknown", "unavailable", None):
                            try:
                                if float(st.state) >= 0:
                                    _LOGGER.info(
                                        "Auto-detected battery cycles sensor: %s = %s (#593)",
                                        eid, st.state,
                                    )
                                    result = eid
                                    break
                            except (ValueError, TypeError):
                                continue
            except Exception as e:  # noqa: BLE001 — best-effort autodetect
                _LOGGER.debug("Battery cycles autodetect failed: %s", e)
        self._cycles_sensor_cache = result
        return result

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

        # Strategy 1: Prefix-based matching (fast path). Try progressively
        # SHORTER stems, longest first, so an indexed device like
        # ``test_battery_2_power`` matches ``sensor.test_battery_2_soc``
        # (stem ``test_battery_2``) before falling back to the 2-part
        # ``battery_1`` prefix that finds Huawei's
        # ``sensor.battery_1_batterieladung``. The 2-part-only heuristic
        # missed any ``<vendor>_<name>_<index>_power`` battery (#523 —
        # per-battery tiles showed 0% SOC on multi-battery installs).
        entity_name = battery_power_entity.split(".", 1)[1]
        parts = entity_name.split("_")

        for k in range(len(parts), 1, -1):
            prefix = "_".join(parts[:k])
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

        # Strategy 3: guarded global last-resort scan (#529). Some installs
        # expose the battery SOC on a DIFFERENT device than the power sensor
        # (or as a standalone template helper) — e.g. Huawei users with a
        # generic ``sensor.battery_state_of_charge`` that the HA Energy
        # Dashboard reads fine but neither the name-prefix nor the same-device
        # scan above can reach. Fall back to a whole-system scan, but only
        # commit when EXACTLY ONE sensor is an unambiguous HOME-battery SOC —
        # a name SOC-keyword AND a ``%`` unit, excluding EV/vehicle/phone
        # batteries. Zero or multiple matches → return None (never guess).
        try:
            _EXCLUDE = ("ev", "car", "vehicle", "phone", "iphone", "laptop",
                        "tablet", "watch", "device_tracker")
            candidates: list[str] = []
            for state in self.hass.states.async_all("sensor"):
                eid = state.entity_id
                eid_lower = eid.lower()
                if any(x in eid_lower for x in _EXCLUDE):
                    continue
                unit = (state.attributes.get("unit_of_measurement") or "").strip()
                if unit != "%":
                    continue
                # Accept by SOC-keyword name OR by the canonical battery SOC
                # signature (device_class=battery + %). The signature path is
                # what catches a localized name with no English keyword — e.g.
                # the Dutch ``sensor.*_batterijpercentage`` (#529, DavidVM1982).
                by_keyword = any(kw in eid_lower for kw in soc_keywords)
                by_signature = state.attributes.get("device_class") == "battery"
                if not (by_keyword or by_signature):
                    continue
                if state.state in ("unknown", "unavailable", None):
                    continue
                try:
                    val = float(state.state)
                except (ValueError, TypeError):
                    continue
                if 0 <= val <= 100:
                    candidates.append(eid)
            if len(candidates) == 1:
                if not getattr(self, "_battery_soc_logged", False):
                    _LOGGER.info(
                        "Auto-detected battery SOC via global scan (#529): %s",
                        candidates[0],
                    )
                    self._battery_soc_logged = True
                return candidates[0]
            if len(candidates) > 1:
                _LOGGER.debug(
                    "Battery SOC global scan ambiguous (%d candidates: %s) — "
                    "set battery_soc_sensor explicitly (#529)",
                    len(candidates), candidates,
                )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Battery SOC global scan failed: %s", e)

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
