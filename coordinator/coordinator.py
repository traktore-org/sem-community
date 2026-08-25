"""Main coordinator for Solar Energy Management.

This is a slim orchestrator that delegates to specialized modules:
- SensorReader: Hardware sensor reading
- EnergyCalculator: Energy integration from power
- FlowCalculator: Power and energy flow calculations
- ChargingStateMachine: Charging mode selection (solar, night, Min+PV)
- EVControlMixin: EV charging control (solar, night, Min+PV, session tracking)
- SEMStorage: Persistence
- NotificationManager: Mobile/KEBA notifications
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # Names used only in annotations. Their real imports are function-local
    # (circular-import avoidance) or live on an adapter package we do not want
    # to pull in at module load; without this block the annotations referenced
    # nothing at all (#786).
    from .types import EVIntelligenceData
    from .charger_types import ArbitrageSignals, FleetCycleState
    from .battery_adapters.base import BatteryControlAdapter

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from ..const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_MAX_CHARGING_CURRENT,
    ED_RESOLVE_MAX_ATTEMPTS,
    ChargingState,
    ENTITY_OBSERVER_MODE_SWITCH,
    ENTITY_VACATION_MODE_SWITCH,
    ENTITY_SOLAR_POWER,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from ..utils.time_manager import TimeManager
from ..ha_energy_reader import read_energy_dashboard_config, EnergyDashboardConfig

from .types import (
    SEMData, PowerReadings, PowerFlows, SystemStatus, LoadManagementData,
    SurplusControlData, ForecastSensorData, TariffSensorData,
    HeatPumpSensorData, HotWaterSensorData, PVAnalyticsData, EnergyAssistantSensorData,
    SessionData, BatterySessionData,
)
from .health_check import HealthCheck
from .units import energy_state_to_kwh, power_state_to_watts
from .distance_units import distance_to_km
from .ev_availability import operational_ev_connected, operational_night_target
from .surplus_availability import SurplusAvailability
from .sensor_reader import SensorReader
from .energy_calculator import EnergyCalculator
from .flow_calculator import FlowCalculator
from .charging_control import ChargingStateMachine, ChargingContext
from .plan_verdict import verdict_from_night_plan
from .per_charger_context import PerChargerContext, PerChargerState
from .storage import SEMStorage
from .notifications import NotificationManager
from .surplus_controller import (
    SurplusController, solar_bounded_surplus, build_battery_tier_context,
    effective_peak_state,
)
from .cycle_trace import (
    TraceCollector, LayerRecord, LayerStatus, CrossCheck,
    ev_layer_match, battery_layer_match, device_layer_match, battery_list_role,
    heat_pump_layer_match,
)
from .energy_reclaim import reclaimable_battery_w
from .forecast_reader import ForecastReader
from .forecast_tracker import ForecastTracker
from .ev_control import EVControlMixin
from ..tariff import StaticTariffProvider, DynamicTariffProvider
from ..tariff.calendar_provider import CalendarTariffProvider
from ..tariff.tariff_provider import _local_date as _tariff_local_date
from ..analytics.pv_performance import PVPerformanceAnalyzer
from ..analytics.consumption_predictor import ConsumptionPredictor
from .ev_taper_detector import EVTaperDetector
from .ev_soc_need import soc_remaining_need
from ..utils.log_gate import log_on_change
from ..analytics.energy_assistant import EnergyAssistant

_LOGGER = logging.getLogger(__name__)


def _f_or_none(value):
    """(#778) A float, or None — so "unconfigured" never reads as zero."""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

# (#638 finding #3) How long the energy plan shadow waits for every battery
# unit to report before planning on the ones that do. Long enough that a
# boot warm-up (seconds) always wins the wait, short enough that a failed
# unit costs one night's plan quality rather than the plan itself.
_SHADOW_PARTIAL_GRACE_S = 600.0


def _cfg_rate(config: dict, *keys: str, default: float) -> float:
    """First explicitly-configured numeric value among ``keys``.

    ``config.get(key) or default`` treats a configured 0.0 rate as
    missing and substitutes the constant (#485 F4) — a real value for
    free/zero-rate plans. Only ``None`` / non-numeric values fall
    through here.
    """
    for key in keys:
        value = config.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


# (#625 phase 3) moved to publish_diag; alias kept for existing imports.


def plan_decision_core(plan) -> tuple:
    """(#775) A stamped plan's DECISION, as a comparable value.

    Forecast.Solar re-publishes hourly and each revision is real — so the
    night re-PLANS on every one, but a repack that reaches the identical
    answer must not re-STAMP it. "Identical" means what the user reads as
    the decision: the blocks, each demand's verdict, the why-nots, the
    takeover hour, whether it fits, what it costs, and the arbitrage
    ACTIONABLES. Trajectory cosmetics (slots, self-consumption outlook,
    prose summaries, allocation reasons) re-derive from live numbers on
    every build and must not hold a restamp hostage. Anything unreadable
    degrades to a non-equal constant — a broken shape restamps, never
    silences."""
    if not isinstance(plan, dict):
        return ("<no-plan>",)
    try:
        blocks = tuple(sorted(
            (str(b.get("id")), str(b.get("start")), str(b.get("end")),
             round(float(b.get("power_w") or 0.0)))
            for b in (plan.get("blocks") or []) if isinstance(b, dict)))
        demands = tuple(sorted(
            (str(d.get("id")), str(d.get("status")),
             round(float(d.get("planned_kwh") or 0.0), 2),
             round(float(d.get("needed_kwh") or 0.0), 2))
            for d in (plan.get("demands") or []) if isinstance(d, dict)))
        whys = tuple(sorted(
            (str(n.get("id")), str(n.get("why")))
            for n in (plan.get("not_scheduled") or []) if isinstance(n, dict)))
        arb = plan.get("arbitrage")
        if isinstance(arb, dict):
            arb_core = (
                bool(arb.get("opportunity")),
                round(float(arb.get("charge_kwh") or 0.0), 1),
                tuple(sorted(
                    (str(b.get("start")), str(b.get("end")))
                    for b in (arb.get("charge_blocks") or [])
                    if isinstance(b, dict))),
                tuple(sorted(
                    (str(b.get("start")), str(b.get("end")))
                    for b in (arb.get("discharge_blocks") or [])
                    if isinstance(b, dict))),
            )
        else:
            arb_core = None
        return (
            blocks, demands, whys,
            str(plan.get("takeover")),
            bool(plan.get("fits")),
            round(float(plan.get("total_cost") or 0.0), 2),
            str(plan.get("battery_fleet_partial")),
            arb_core,
        )
    except Exception:  # noqa: BLE001 — an unreadable plan restamps, safely
        return ("<unreadable>", id(plan))


def demand_signature_changed(old, new) -> bool:
    """(#765) Did the night's ASK really change between two signatures?

    Every term compares strictly except ``price``, which gets the one rule
    the sliding window needs: a price differing at a SHARED absolute
    timestamp is a change, NEW timestamps (tomorrow's curve landing) are a
    change, and a PAST slot expiring off the front of the window is
    silence — time passing is not the night changing. An unrecognizable
    shape (a stored signature from an older build) reads as changed: one
    restamp after an upgrade, never a crash, never a stale night.
    """
    if old == new:
        return False
    try:
        def _split(sig):
            rest, price, loads = [], (), {}
            for term in sig:
                if isinstance(term, tuple) and term and term[0] == "price":
                    price = term[1] if len(term) > 1 else ()
                elif (isinstance(term, tuple) and len(term) >= 3
                        and term[0] == "load"):
                    loads[term[1]] = term[2:]
                else:
                    rest.append(term)
            return tuple(rest), price, loads

        old_rest, old_price, old_loads = _split(old)
        new_rest, new_price, new_loads = _split(new)
        if old_rest != new_rest:
            return True

        # (#765, second sighting) A RUNNING load's deficit shrinks through
        # the 0.1 h buckets — one replan per bucket, every 6 minutes, for
        # as long as it runs. Shrinking-but-nonzero is the plan WORKING;
        # news is: a demand appearing or vanishing, a deficit GROWING, or
        # any other field (the #760 stop flag) moving.
        if set(old_loads) != set(new_loads):
            return True
        for did, new_term in new_loads.items():
            old_term = old_loads[did]
            if old_term[1:] != new_term[1:]:
                return True                      # stop flag etc. moved
            if new_term[0] > old_term[0]:
                return True                      # the deficit grew
        return _price_changed(old_price, new_price)

    except Exception:  # noqa: BLE001 — unknown shapes replan once, safely
        return True


def _lifetime_ev_shares(lifetime: dict) -> dict:
    """The lifetime EV energy split, all three ways (#793).

    Only the solar share used to be derived — battery-sourced kWh sat in the
    denominator without appearing in any displayed number, so the "not solar"
    remainder and the "actually charged for" fraction read as the same split
    when they were two different numbers. Solar + battery + grid always sum
    to ~100 of what was attributed.
    """
    total = lifetime.get("total_energy_kwh", 0)
    if not total or total <= 0:
        return {
            "lifetime_ev_solar_share": 0,
            "lifetime_ev_battery_share": 0,
            "lifetime_ev_grid_share": 0,
        }
    return {
        "lifetime_ev_solar_share": round(
            lifetime.get("total_solar_kwh", 0) / total * 100, 1),
        "lifetime_ev_battery_share": round(
            lifetime.get("total_battery_kwh", 0) / total * 100, 1),
        "lifetime_ev_grid_share": round(
            lifetime.get("total_grid_kwh", 0) / total * 100, 1),
    }


def _price_changed(old_price, new_price) -> bool:
    """(#765) Shared-timestamp price change or new slots = news; a past
    slot expiring off the window = silence. Raises on old-format terms —
    the caller's except turns that into one safe restamp."""
    def _as_map(pairs):
        m = {}
        for item in pairs:
            if not (isinstance(item, tuple) and len(item) == 2):
                raise ValueError("old-format price term")
            m[item[0]] = item[1]
        return m

    old_map, new_map = _as_map(old_price), _as_map(new_price)
    if set(new_map) - set(old_map):
        return True                          # tomorrow landed / new slots
    return any(old_map.get(k) != v for k, v in new_map.items())


class SEMCoordinator(DataUpdateCoordinator, EVControlMixin):
    """Coordinator for Solar Energy Management.

    Orchestrates the flow:
    1. Read sensors (SensorReader)
    2. Calculate energy from power (EnergyCalculator)
    3. Calculate power/energy flows (FlowCalculator)
    4. Update charging state (ChargingStateMachine + CurrentControlDevice)
    5. Send notifications (NotificationManager)
    6. Persist data (SEMStorage)

    EV control is provided by EVControlMixin to keep this file
    focused on orchestration; the startup battery discharge restore is
    ``actuate_battery.restore_discharge_limit_on_startup`` (#624).
    """

    # #485 G5: the reload-skip snapshot is a property so arming it
    # automatically timestamps it. async_update_options only honors a
    # snapshot younger than its TTL — a lingering snapshot from the
    # last runtime tweak hours ago must not swallow a future listener
    # invocation (HA fires the listener for data/title-only entry
    # updates too, where options still equal the stale snapshot).
    @property
    def _skip_options_reload(self):
        return getattr(self, "_skip_options_reload_value", None)

    @_skip_options_reload.setter
    def _skip_options_reload(self, value):
        # NB: stdlib ``time`` is shadowed by this package's time.py
        # platform under pytest's path insertion — use dt_util.
        self._skip_options_reload_value = value
        self._skip_options_reload_armed_at = (
            dt_util.utcnow().timestamp() if value is not None else None
        )

    def _primary_charger_cfg(self) -> Dict[str, Any]:
        """Config dict of the fleet-primary charger (ev_chargers[0]).

        Single accessor for the ``(config.get("ev_chargers") or
        [{}])[0]`` idiom that was inlined at five call sites (#485 H1).
        """
        chargers = self.config.get("ev_chargers") or [{}]
        first = chargers[0]
        return first if isinstance(first, dict) else {}

    def _primary_hardware_max_a(self, cfg: Dict[str, Any]) -> Optional[float]:
        """The primary charger's real current ceiling, or None (#678).

        ``effective_max_current`` is the device's configured max clamped to
        its control number entity's own max — the same value the adapter
        clamps every command to (#536). Feeding it into the primary view
        keeps the strategy string and the actuator from disagreeing about
        what the hardware will accept.

        None when there is no device yet (early boot, observer mode): the
        view then falls back to the config chain, which is the pre-#678
        behaviour and never worse than it.
        """
        cid = cfg.get("id") or "ev_charger"
        dev = (getattr(self, "_ev_devices", None) or {}).get(cid)
        if dev is None:
            dev = getattr(self, "_ev_device", None)
        if dev is None:
            return None
        val = getattr(dev, "effective_max_current", None)
        if val is None:
            val = getattr(dev, "max_current", None)
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def _charge_stability_kwargs(self) -> Dict[str, Any]:
        """Stability-layer tunables for ``ChargeStability.filter``.

        All keys are the v1.7.1-beta.14 stability config keys — they
        survived the arch rewrite even while the code that read them
        was orphaned (#461), so existing installs keep their values.
        """
        from .charge_stability import (
            DEFAULT_DEEP_DEFICIT_GRACE_S,
            DEFAULT_DISABLE_DELAY_S,
            DEFAULT_ENABLE_DELAY_S,
            DEFAULT_MIN_CHANGE_AMPS,
            DEFAULT_MIN_CHANGE_INTERVAL_S,
            DEFAULT_RAMP_AMPS,
            DEFAULT_SMOOTH_WINDOW,
        )
        return {
            "enable_delay_s": self.config.get(
                "ev_enable_delay_seconds", DEFAULT_ENABLE_DELAY_S),
            "disable_delay_s": self.config.get(
                "ev_disable_delay_seconds", DEFAULT_DISABLE_DELAY_S),
            "smooth_window": self.config.get(
                "ev_surplus_smooth_window", DEFAULT_SMOOTH_WINDOW),
            "min_change_amps": self.config.get(
                "ev_min_change_amps", DEFAULT_MIN_CHANGE_AMPS),
            "min_change_interval_s": self.config.get(
                "ev_min_change_interval_sec", DEFAULT_MIN_CHANGE_INTERVAL_S),
            "ramp_amps": self.config.get(
                "ev_ramp_rate_amps", DEFAULT_RAMP_AMPS),
            "deep_deficit_grace_s": self.config.get(
                "ev_deep_deficit_grace_sec", DEFAULT_DEEP_DEFICIT_GRACE_S),
        }

    def primary_charger_id(self) -> str:
        """Canonical id of the fleet-primary charger (#485 H1).

        Mirrors registration's fallback (``ev_charger_<idx>`` for
        id-less entries, __init__.py): the strategy-display gate used
        a DIFFERENT fallback ("ev_charger"), so on an id-less first
        charger the equality never held and the fleet strategy sensor
        froze. The flat-key single-charger shape (no ev_chargers list)
        keeps the legacy "ev_charger" id.
        """
        chargers = self.config.get("ev_chargers") or []
        if not chargers or not isinstance(chargers[0], dict):
            return "ev_charger"
        return chargers[0].get("id") or "ev_charger_0"

    @staticmethod
    def _resolve_battery_cycles(hw_state, throughput_cycles):
        """#593 — prefer a hardware lifetime-cycle reading over the throughput
        estimate. ``hw_state`` is the raw sensor state (str) or None;
        ``throughput_cycles`` is the estimate (or None if no capacity). Returns
        ``(cycles, health_score)`` or ``(None, None)`` if neither is available.
        A present-but-unparseable hw reading falls back to the estimate (never
        drops the value)."""
        hw = None
        if hw_state is not None and hw_state not in ("unknown", "unavailable"):
            try:
                hw = round(float(hw_state), 1)
            except (ValueError, TypeError):
                hw = None
        cycles = hw if hw is not None else throughput_cycles
        if cycles is None:
            return None, None
        # 0.02% degradation per cycle (typical Li-ion), capped at 30%.
        health = round(100 - min(30, cycles * 0.02), 1)
        return cycles, health

    @staticmethod
    def _resolve_fleet_charging_state(global_state, effective_states):
        """The published fleet ``charging_state`` (#596).

        The global state machine computes ``global_state`` BEFORE the
        per-charger loop refines each charger's terminal state
        (NIGHT_TARGET_REACHED / SOLAR_IDLE / …). For a **single-charger**
        install that refinement IS the truth, so the fleet state must adopt it
        — otherwise the fleet state (and the ``night_charging_status`` /
        ``solar_charging_status`` sensors derived from it) stays "…_active"
        after the charger has reached target (the PROD symptom in #596).

        **Multi- (or zero-) charger** keeps ``global_state``: chargers can
        disagree and per-charger states are exposed separately (#351 M4), so
        they cannot collapse to one fleet value. Notifications are unaffected —
        they dispatch from ``_effective_states_per_charger`` when populated.
        """
        if len(effective_states) == 1:
            (only_eff, _name), = effective_states.values()
            if only_eff is not None:
                return only_eff
        return global_state

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.config = config
        self.config_entry: Optional[ConfigEntry] = None
        # #255: the duplicate GLOBAL EV settings entities were removed; per-charger is
        # canonical. Mirror the primary charger's values into the legacy global config
        # keys so the remaining global-context consumers (recommendations, notifications,
        # forecast, summaries) read fresh per-charger values — exact for single-charger,
        # primary charger as representative for multi.
        self._mirror_primary_charger_to_global()

        # Update interval
        update_interval = config.get("update_interval", DEFAULT_UPDATE_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

        # Initialize time manager
        self.time_manager = TimeManager(hass, config)

        # Battery capacity: config value, auto-detected, or default
        self._detected_battery_capacity_kwh: Optional[float] = None

        # Initialize modules
        self._sensor_reader = SensorReader(hass, config)
        self._energy_calculator = EnergyCalculator(config, self.time_manager)
        self._flow_calculator = FlowCalculator()
        self._state_machine = ChargingStateMachine(hass, config, self.time_manager)
        # Primary charger — set by __init__.py (backward compat). A PROPERTY
        # since the #589 swap retirement: in-loop reads resolve to the active
        # PerChargerContext's device; this assignment routes to the _default
        # backing via the setter.
        self._ev_device = None
        self._ev_devices: Dict[str, Any] = {}  # All chargers keyed by charger_id (#112)
        # #589 Surface-A: these three are PROPERTIES backed by the current
        # PerChargerContext's durable state; the _default variants back them
        # out-of-loop (no active pcc). Kept as plain assignments so that the
        # swap-attrs-initialized lint (which walks AST assignments) still fires
        # on accidental re-introduction of uninitialized attributes.
        self._ev_last_change_time_default: Optional[Any] = None
        self._ev_charge_started_at_default: Optional[float] = None
        self._ev_enable_surplus_since_default: Optional[float] = None
        # Solar stability primary view — also migrated (#589 Surface-A).
        self._ev_last_set_amps_ts_default: Optional[float] = None
        # #589 Surface-A — durable per-charger state objects (replacing the
        # parallel _ev_*_per_charger dicts field-by-field). Held by the loop's
        # PerChargerContext by reference; the migrated _ev_* properties read/
        # write it, so a field can't leak between chargers.
        self._pcc_store: Dict[str, PerChargerState] = {}
        # Per-charger state dicts for multi-charger (#112)
        # All 7 scalar Surface-A fields are migrated to _pcc_store (#589):
        #   _ev_stalled_since, _ev_enable_surplus_since, _ev_charge_started_at,
        #   _ev_last_change_time, _ev_reenable_attempts, _ev_charge_refused,
        #   _ev_last_set_amps_ts.
        # Their _per_charger dicts are retired; they are now coordinator
        # PROPERTIES backed by the durable PerChargerState object.
        # _ev_budget_history + _ev_budget_history_per_charger were DELETED
        # (#589 swap retirement): their only consumer (the ev_control
        # median-budget helper) was removed with the obsolete stability knobs
        # in #536; the swap machinery had been carrying dead state since.
        # Surplus smoothing lives in surplus_controller (median-of-3
        # pre-filter) and sensor_reader._smooth_ev_power.
        self._daily_ev_per_charger: Dict[str, float] = {}  # Per-charger daily energy (#193)
        # (#829) last calendar day the status-retention purge ran
        self._retention_last_day: Optional[str] = None
        # Per-charger "EV day" boundary, keyed by charger id. Each charger's day
        # ends at its own ``Charge by`` deadline (#246) — NOT at sunrise — so the
        # counter doesn't wipe between hitting Min and the deadline (which on
        # short summer nights happened between sunrise ~05:30 and night_end
        # 07:00, causing SEM to re-fire night charging and double-bill the user).
        self._daily_ev_per_charger_date: Dict[str, str] = {}
        # Warn-once guards so per-cycle surfacing (#259) doesn't spam the log.
        self._tariff_rate_warned: bool = False
        self._tariff_pause_warned: bool = False  # #274/L1 one-time provider-error warn
        self._night_global_fallback_logged: set[str] = set()
        self._notification_manager = NotificationManager(hass, config)

        # Storage will be initialized with entry_id later
        self._storage: Optional[SEMStorage] = None

        # Energy Dashboard config
        self._energy_dashboard_config: Optional[EnergyDashboardConfig] = None
        # Cold-start recovery (#274): re-derive ED power sensors each cycle while
        # they're unresolved (source integration registered after SEM), bounded.
        self._ed_resolve_pending: bool = False
        self._ed_resolve_attempts: int = 0

        # Layered-trace observability (2026-07-11, 1.7.5). Read-only per-cycle
        # ring buffer of the management→process→integration chain, dumped by
        # the diagnose service. Never affects a decision; never a recorder row.
        self._trace = TraceCollector(maxlen=30)
        # (#576) priority-walk inputs for the 3-layer trace, refreshed each
        # cycle in the surplus block (battery slot / reclaim / commanded).
        self._cycle_reclaim: dict = {}

        # Phase 0: Surplus controller (always-on) & forecast reader
        regulation_offset = config.get("regulation_offset", 50)
        self._surplus_controller = SurplusController(hass, regulation_offset=regulation_offset)
        # (#559 Phase 0) debounced surplus availability signal
        self._surplus_availability = SurplusAvailability()
        self._surplus_controller.max_export_w = config.get("max_export_power", 0)  # 0 = no limit
        self._forecast_reader = ForecastReader(
            hass,
            custom_entities=None,  # Was config.get("forecast_entities") — never set via UI
            # (#819) The user's chosen forecast integration, when several
            # are installed side by side. Unset/"auto" keeps the ladder.
            preferred_source=config.get("solar_forecast_source"),
        )
        self._forecast_tracker = ForecastTracker()
        # (#824) When each broken charger control entity was first seen,
        # and which ones already have a Repair filed. Keyed by
        # (charger_id, entity_id) so two chargers naming the same helper
        # cannot clear each other's issue.
        self._control_broken_since: dict[tuple, float] = {}
        self._control_repair_raised: set[tuple] = set()
        self._forecast_tracker.set_hass(hass)

        # Phase 1: Tariff provider
        tariff_mode = config.get("tariff_mode", "static")
        # Price-responsive mode is automatic: enabled when using dynamic tariffs
        self._surplus_controller.price_responsive_mode = (tariff_mode == "dynamic")
        currency = hass.config.currency
        if tariff_mode == "dynamic":
            self._tariff_provider = DynamicTariffProvider(
                hass,
                price_entity=config.get("dynamic_tariff_entity") or config.get("price_entity"),
                forecast_entity=config.get("dynamic_forecast_entity"),
                feedin_entity=config.get("dynamic_feedin_entity"),
                export_rate=config.get("electricity_export_rate", 0.075),
                cheap_threshold=config.get("cheap_price_threshold", 0.15),
                expensive_threshold=config.get("expensive_price_threshold", 0.35),
                currency=currency,
                # #359: percentile is the new default for users on
                # Tibber/Octopus/Amber/Nordpool where today's range
                # determines what "cheap" means — the static 0.15/0.35
                # CHF cutoffs misclassified the whole day on dynamic
                # tariffs.
                classification_mode=config.get(
                    "tariff_classification_mode", "percentile",
                ),
                # Last-resort rate when the price entity is unavailable
                # and no cached curve covers "now". The user's configured
                # import rate beats the CHF-shaped 0.30 constant on
                # SEK/NOK/HUF installs.
                fallback_price=_cfg_rate(
                    config, "electricity_import_rate", default=0.30,
                ),
                # Grid import surcharge: explicit constant
                # per-kWh network fee added to every IMPORTED kWh for
                # dynamic tariffs. 0 disables it. Defaults to 0.0 so an
                # existing config without the key is unaffected.
                grid_import_surcharge=config.get("grid_import_surcharge", 0.0),
            )
        elif tariff_mode == "calendar":
            schedule = {}  # Was config.get("tariff_schedule", {}) — never set via UI
            self._tariff_provider = CalendarTariffProvider(
                hass,
                peak_rate=config.get("electricity_import_rate", 0.35),
                off_peak_rate=_cfg_rate(
                    config, "electricity_off_peak_rate", "electricity_nt_rate",
                    default=0.22,
                ),
                export_rate=config.get("electricity_export_rate", 0.075),
                rules=schedule.get("rules", []),
                default_tariff=schedule.get("default_tariff", "off_peak"),
                holiday_entity=schedule.get("holiday_entity"),
                schedule_entity=schedule.get("schedule_entity"),
                currency=currency,
            )
        else:
            self._tariff_provider = StaticTariffProvider(
                peak_rate=config.get("electricity_import_rate", 0.3387),
                off_peak_rate=_cfg_rate(
                    config, "electricity_off_peak_rate", "electricity_nt_rate",
                    default=0.3387,
                ),
                export_rate=config.get("electricity_export_rate", 0.075),
                currency=currency,
            )

        # Phase 5: PV performance analyzer
        self._pv_analyzer = PVPerformanceAnalyzer(
            hass,
            system_size_kwp=config.get("system_size_kwp", 10.0),
            inverter_max_power_w=10000.0,  # Was config.get — never set via UI
            system_install_date=None,  # Was config.get — never set via UI
        )

        # Phase 6: Energy assistant
        self._energy_assistant = EnergyAssistant(hass)


        # Phase 8: Consumption/solar predictor (#3)
        self._predictor = ConsumptionPredictor()

        # Phase 9: Battery charge scheduler (#6). (#624) The scheduler is a
        # pure planner — actuation goes through the battery pipeline's
        # BatteryControlAdapter, so no standalone charge adapter exists.
        from .battery_charge_scheduler import BatteryChargeScheduler, SchedulerConfig
        self._battery_scheduler_config = SchedulerConfig.from_config(config)
        self._battery_charge_scheduler = BatteryChargeScheduler(
            hass, self._battery_scheduler_config,
        )

        # EV Intelligence: taper detection, virtual SOC, charge skip (#106)
        # #589 Surface-B retirement: the primary detector is now COMPUTED by the
        # _ev_taper_detector property (below) instead of swapped in each cycle.
        # This default backs the property before the per-charger detectors exist
        # (first-update restore) and for a bare single-charger install.
        self._ev_taper_detector_default = EVTaperDetector(config)  # Primary fallback
        self._ev_taper_detectors: Dict[str, EVTaperDetector] = {}  # Per-charger (#112)
        # (P3, 13.08) The energy plan tick holds off until the device
        # runtime restore has run — a cold-world demand signature must not
        # invalidate a warm restored stamp. Flipped in
        # ``_restore_device_runtimes`` (called unconditionally at setup and
        # re-invoked by the registry's rediscovery hook).
        self._runtimes_restored: bool = False

        # Calculation integrity checker (runs every cycle)
        self._health_check = HealthCheck()

        # Hourly activity tracker for schedule card (#63)
        self._today_surplus_hours: list = [False] * 24
        self._today_ev_hours: list = [False] * 24
        # Initialize to today: the arrays above start empty, so there is
        # nothing for a rollover to clear on the day of a restart.
        self._tracker_date = dt_util.now().date()
        # (#645) The virtual-SOC daily decay has its OWN date, restored from
        # storage in the first refresh. It used to ride on ``_tracker_date``,
        # which is re-initialised to today on every restart — so a restart
        # that spanned midnight silently skipped the decay for the day that
        # just ended. None until restore; see ``_run_due_daily_decay``.
        self._last_decay_date = None

        # Per-cycle caches (initialized here, populated in _async_update_data)
        self._cycle_forecast = None
        self._cycle_vehicle_soc: Optional[float] = None
        # (#657) The cycle's canonical EVBudget. ``_build_charging_context``
        # sets it on every cycle before ``SEMData`` is built, so this default
        # is never read on a healthy path — it exists so the ordering contract
        # is explicit rather than "it will exist by then", and so a future
        # early-return between the two can't turn into an AttributeError.
        self._cycle_ev_budget = None
        # Night charge plan for the (primary) charger this cycle (#246/#247)
        self._cycle_night_plan = None
        # Per-charger night plans for surfacing + the "unreachable deadline" notify
        # (notification dedup itself lives in NotificationManager._notified_flags)
        self._night_plan_per_charger = {}
        # Surplus-mode enable/disable delay timers (#461 flapping) — the
        # Hysteresis stability filter between decide() and actuate().
        from .charge_stability import ChargeStability
        self._charge_stability = ChargeStability()
        # Shared night peak budget (#274/H1): watts committed to higher-priority
        # chargers so far this cycle. Reset before the per-charger loop; each
        # charger's peak-managed sizing subtracts it so the fleet stays under peak.
        self._night_committed_w = 0.0
        # Tariff wait↔charge hysteresis (#274/M4): {cid: (should_wait, ts)} of the
        # last effective decision, so price hovering at the cheap boundary doesn't
        # stop/start the charger every cycle.
        self._tariff_decision_per_charger = {}
        # v1.6.9: per-charger effective state captured during the
        # multi-charger loop so ``_send_notifications`` can dispatch
        # ``notify_state_change`` per charger with its own
        # ``charger_id`` and flap-suppression key. Cleared at the top of
        # each loop pass; empty in single-charger setups (notification
        # falls back to the fleet-level call).
        # Shape: ``{cid: (effective_state, charger_name)}``. v1.6.14:
        # populated by ``PerChargerContext.__exit__`` (not by the loop
        # body directly) — pcc owns the write path now.
        self._effective_states_per_charger: Dict[str, tuple] = {}

        # v1.6.14: short-lived pointer to the currently active
        # ``PerChargerContext`` so ``ev_control._this_charger_power``
        # can serve the cached value computed once at ``__enter__``
        # instead of re-reading the HA state every call. Set in
        # ``PerChargerContext.__enter__`` / cleared in ``__exit__``.
        # ``None`` outside any per-charger iteration.
        self._current_pcc = None

        # _current_charger_budget was DELETED (#589 swap retirement) and
        # ``pcc.budget_w``, which it mirrored, followed it in #651 — that
        # whole distribution had no reader at either end. The per-charger
        # solar share is ``fleet.solar_committed_w``, threaded into each
        # charger's view from the previous charger's actual decision.

        # EV stall detection for self-healing.
        # #589 Surface-A: ALL of these are PROPERTIES backed by the current
        # PerChargerContext's durable state (self._current_pcc.state) so they
        # can't leak between chargers. The _default variants back them when
        # there is no active PerChargerContext (out-of-loop / single-charger).
        self._ev_stalled_since_default: Optional[float] = None
        # False-stall guard: consecutive failed re-enables + "car full" latch (#243)
        self._ev_reenable_attempts_default: int = 0
        self._ev_charge_refused_default: bool = False
        # Highest commanded amps across all chargers in the most recent
        # decide() cycle. Gates the fleet-level "0W means full" stall
        # path so it can't fire when SEM itself decided not to charge
        # (e.g. solar_only with surplus below the 3-phase 6 A floor —
        # the stall detector would otherwise falsely anchor SOC at 100 %).
        self._last_commanded_amps_fleet: int = 0
        # (#638) Measured watts-per-amp EMA per charger. Nameplate
        # (phases × voltage) overstates cars that don't pull every phase to
        # the rail — PROD's Zoe draws ~485 W/A at 10 A against a 690 W/A
        # nameplate — and the night packer modelling the EV floor at
        # nameplate concluded 6.9 kW can never fit under a 6.0 kW peak,
        # yielding a demand the reactive layer then charged anyway (first
        # armed night). Learned only while the charger is actually drawing;
        # consumers fall back to nameplate when empty.
        self._ev_wpa_ema: Dict[str, float] = {}

        # Session cost tracking (primary charger + per-charger dict)
        self._session_data = SessionData()
        # (#753) the warm-up reference: a 'disconnect' in the first two
        # minutes after boot is the sensor stack loading, not the car.
        import time as _time
        self._boot_monotonic = _time.monotonic()
        self._session_data_per_charger: Dict[str, SessionData] = {}
        self._last_ev_connected = False
        self._last_ev_connected_per_charger: Dict[str, bool] = {}
        # (#638) the plug debounce's own state — see
        # ``_confirm_ev_connection``. Keyed by charger id; ``""`` is the
        # flat/legacy fleet sensor.
        self._ev_conn_confirmed: Dict[str, bool] = {}
        self._ev_conn_streak: Dict[str, int] = {}
        # #708 — {charger_id: (last usable vehicle-SOC reading, the instant
        # it was taken)}. An unavailable entity rewrites its own
        # ``last_changed``, so the live state cannot date the reading it no
        # longer holds; this remembers it. In-memory only — after a restart
        # SEM honestly reports "unknown" until the sensor answers again.
        self._soc_last_seen: Dict[str, tuple] = {}

        # Battery session tracking
        self._battery_session = BatterySessionData()
        self._battery_session_idle_count = 0
        # #405 — direction-change hysteresis counter. Counts cycles
        # spent in the opposite direction of the active session;
        # session only ends when this reaches OPPOSITE_CYCLES_TO_FLIP.
        self._battery_session_opposite_count = 0

        # (#440) the per-charger night-skip safety counter latch was
        # removed alongside the skip-decision wiring — charge mode is
        # the sole authority on whether to charge at night now.

        # Zone-transition debounce: holds the last stable SOC zone and the
        # candidate zone being observed. A new zone is only applied after it
        # is seen for N consecutive cycles (zone_debounce_cycles, default 2).
        # Prevents Charging→Idle→Charging flapping when a user nudges a zone
        # threshold (e.g., Priority SOC 50→51%) or SOC oscillates near a
        # boundary. Tracks last-seen thresholds so a deliberate config change
        # also resets the candidate counter rather than amplifying the blip.
        self._stable_zone: Optional[int] = None
        self._pending_zone: Optional[int] = None
        self._pending_zone_count: int = 0
        self._last_zone_thresholds: Optional[tuple] = None

        # Initialize data with defaults
        self.data = self._get_initial_data()

        # Battery discharge protection state
        self._last_discharge_limit: Optional[float] = None

        # (#638) energy plan shadow state: the night it has been stamped
        # for, the plan itself, and when the battery fleet first came up
        # short (see _SHADOW_PARTIAL_GRACE_S).
        self._shadow_plan_date = None
        self._energy_plan_shadow: Optional[Dict[str, Any]] = None
        self._shadow_partial_since = None
        # (#638 G4) actuation opt-in — the plan's blocks feed the existing
        # night signals only while this is True. Seeded from the persisted
        # option, then driven live by ``switch.sem_energy_plan_actuation``
        # (same persistence pattern as observer/vacation mode). Default ON
        # since the one-gate build (C8): the private cheap-window selectors
        # are retired, so with actuation off a solar_plus_cheap install
        # would have NO cheap-window timing at all — default-off would be
        # a silent feature regression. The switch is the kill-switch.
        self._energy_plan_actuation = config.get("energy_plan_actuation", True)
        # (#638 G4) EV connection signature at stamp time — a plug/unplug
        # during the night re-derives the plan (the doc's replan trigger).
        self._plan_ev_conn_sig = None

        # Observer mode: read-only monitoring, no hardware control
        self._observer_mode = config.get("observer_mode", False)

        # Vacation mode (#594): suppress comfort heating (heat pump boost +
        # hot water solar target) while away. Two activation sources OR'd
        # per cycle: SEM's own ``switch.sem_vacation_mode`` (pushed onto
        # ``_vacation_switch_on`` by the switch entity, backstopped from the
        # entity state each cycle) and the optional external
        # ``vacation_mode_entity`` config key (binary_sensor / input_boolean
        # / switch / calendar — active while its state is ``on``).
        self._vacation_switch_on = config.get("vacation_mode", False)
        self._vacation_active = False

        # Tracking flags
        self._initial_update_done = False
        # #589 3a — warn-once-per-episode flag for enrichment-tail degradation.
        self._enrich_degraded = False
        self._load_manager = None  # Load management coordinator (external)
        self._device_registry = None  # UnifiedDeviceRegistry (set by __init__.py)

        if self._observer_mode:
            _LOGGER.info("Observer mode: hardware control disabled")
        _LOGGER.info("SEM Coordinator initialized with %ss update interval", update_interval)

    def _mirror_primary_charger_to_global(self) -> None:
        """Mirror the primary charger's per-charger EV settings into the legacy global
        config keys (#255).

        The duplicate global EV setting entities were removed — per-charger is canonical.
        A few global-context consumers (recommendations, notifications, forecast,
        summaries) still read the legacy global keys; this keeps those reads fresh from
        the primary charger so a single-charger setup is exact and multi-charger uses the
        primary as a representative. The per-charger control loop reads per-charger config
        directly and is unaffected.
        """
        chargers = self.config.get("ev_chargers") or []
        if not chargers or not isinstance(chargers[0], dict):
            return
        pc = chargers[0]
        for key in (
            "daily_ev_target", "daily_ev_target_max",
            "ev_target_soc", "ev_target_soc_max",
            "ev_min_current",
            "ev_kwh_per_100km", "ev_target_type",
            # ``ev_charging_mode`` removed in #277 Phase C — the v6→v7
            # migration drops the field; there's nothing to mirror.
            "ev_phases",
            "ev_target_time",  # #246 charge-by deadline
        ):
            if pc.get(key) is not None:
                self.config[key] = pc[key]

    @staticmethod
    def _apply_per_charger_off_override(global_state: str, per_mode: str) -> str:
        """Per-charger override of the global solar charging state (v1.6.3 hotfix).

        The global ``charging_state`` is derived from the primary
        charger's config only. Two correctness gaps in the multi-charger
        loop need to be closed:

        1. **This charger is off**: force ``SOLAR_IDLE`` so the actuator's
           TERMINAL branch calls ``stop_session()`` regardless of what
           the primary charger is doing. Without this, charger[1]=off
           would never be stopped.
        2. **Primary is off but this charger isn't**: don't propagate
           the primary's terminate. Fall back to ``SOLAR_CHARGING_ALLOWED``
           (warm-waiting) so this charger keeps participating in surplus
           distribution.

        Pure function — no side effects, no coordinator state read.
        Directly unit-testable.
        """
        if per_mode == "off":
            return ChargingState.SOLAR_IDLE
        if global_state == ChargingState.SOLAR_IDLE:
            return ChargingState.SOLAR_CHARGING_ALLOWED
        return global_state

    def _effective_charge_mode_for(self, charger_cfg: dict) -> str:
        """Resolve the user-intent Charge mode for one charger (#277).

        Phase A introduced this as the read-point Phase B switched
        authority on. Phase C wires it into the strategy machine
        directly + makes ``_tariff_optimized_for`` mode-driven, so
        ``charge_mode`` is now the only intent input anywhere.

        Delegates to the shared free function so ``ChargingStateMachine``
        (which is a separate class, not a coordinator mixin) can use
        the same resolver — one source of truth.

        Returns one of ``EV_CHARGE_MODES`` keys; never raises.
        Defensive against test stubs that build a coordinator via
        ``__new__`` without ``hass`` — the free function ignores
        ``hass`` post-Phase-C anyway.
        """
        # #580 — VPP per-cycle EV veto/boost. During an active (non-observer)
        # VPP event the grid signal outranks the user's charge mode FOR THAT
        # CYCLE ONLY: an export event pauses every charger (mode ``off`` →
        # the actuator's TERMINAL branch stops the session); an import event
        # boosts to ``always_max``. Nothing is persisted — the override drops
        # the moment the event ends and the user's mode resumes. Routed here
        # (the single mode read-point, #277) so no second veto path exists.
        _vpp_ev = getattr(self, "_vpp_ev_override", None)
        if _vpp_ev == "pause":
            return "off"
        if _vpp_ev == "boost":
            return "always_max"
        from ..consts.ev_charge_modes import effective_charge_mode_for
        return effective_charge_mode_for(
            getattr(self, "hass", None),
            getattr(self, "config", {}) or {},
            charger_cfg,
        )

    def _device_run_rows(self, now, peak_t) -> "List[Dict[str, Any]]":
        """(#576) Project each surplus device's run window for Today's Plan.

        MVP: a SURPLUS-mode device that hasn't met its daily goal is expected
        to run around the solar peak (when spare solar is most likely); a
        device that HAS met its goal shows a 'done' row at ``now``. EV and
        battery have their own rows. Coarse-but-honest — a precise per-device
        forecast simulation is a future refinement. Best-effort: never raises
        (the caller's cycle must not break on a plan detail).
        """
        rows: "List[Dict[str, Any]]" = []
        sc = getattr(self, "_surplus_controller", None)
        if sc is None:
            return rows
        # Resolve the solar peak to a datetime today (reuse compose's formats).
        # (#688) ``datetime`` was never imported in this module — only ``date``
        # and ``timedelta`` are — so the ISO branch below raised NameError,
        # which the ``except (ValueError, TypeError)`` does NOT catch, breaking
        # the docstring's "never raises". Normally ``peak_time_today`` arrives
        # as "HH:MM" (forecast_reader reformats it) and takes the other branch,
        # which is why this stayed hidden; the raw-passthrough fallback there
        # can still hand us an ISO string.
        from datetime import datetime as _dt
        anchor = None
        if peak_t is not None:
            try:
                s = str(peak_t)
                if "T" in s:
                    anchor = _dt.fromisoformat(s.replace("Z", "+00:00"))
                    if anchor.tzinfo and now.tzinfo:
                        anchor = anchor.astimezone(now.tzinfo)
                elif ":" in s:
                    h, m = s.split(":")[:2]
                    anchor = now.replace(hour=int(h), minute=int(m),
                                         second=0, microsecond=0)
            except (ValueError, TypeError):
                anchor = None
        try:
            from ..devices.base import DeviceControlMode
            for dev in sc.get_devices_sorted():
                if getattr(dev, "is_ev", False):
                    continue  # EV has its own rows
                if getattr(dev, "control_mode", None) != DeviceControlMode.SURPLUS:
                    continue  # only proactively-run devices
                # (#688) The floor is NOT the end of the day — past it a load
                # keeps riding free surplus up to the Max cap. "Done" must
                # mean SEM won't run it again today, so it needs the cap /
                # stop-condition, or a floor that's met with the load already
                # off. A load still running shows as running (at ``now``),
                # not as done — otherwise Today's Plan says "done" about a
                # device the user can hear working.
                active = bool(getattr(dev, "is_active", False))
                done = (bool(getattr(dev, "daily_max_runtime_reached", False))
                        or bool(getattr(dev, "stop_condition_met", False))
                        or (bool(getattr(dev, "daily_targets_met", False))
                            and not active))
                when = now if (done or active) else anchor
                if when is None or when < now:
                    when = now if (done or active) else None
                if when is None:
                    continue
                rows.append({"name": getattr(dev, "name", ""), "when": when,
                             "done": done})
        except Exception:  # pragma: no cover - never break the cycle
            return rows
        return rows

    def _ev_priority_for(self, cid: str) -> int:
        """(#576) This charger's authoritative list slot for decide()'s reclaim
        gate — a drag override wins IMMEDIATELY (read straight from the priority
        store), else the charger's config-seeded priority. Reading the store
        directly (not the cached ``dev.priority``, refreshed only on config
        events) means a drag takes effect next cycle, not after the next config
        change (ruflo review HIGH)."""
        dev = (self._ev_devices or {}).get(cid)
        seed = int(getattr(dev, "priority", 3) or 3)
        reg = getattr(self, "_device_registry", None)
        return reg.priority_for(cid, seed=seed) if reg is not None else seed

    def _ev_watts_per_amp(self, cid: str, cfg: dict, power=None) -> float:
        """(#638) This charger's real watts-per-amp: measured when known,
        nameplate otherwise.

        Nameplate (``phases × voltage``) is an upper bound, not a draw — a
        Zoe at 10 A pulls ~4.85 kW against a 6.9 kW nameplate. The night
        packer sizing the EV floor from nameplate declared it unplaceable
        under the peak on the first armed night while the car charged
        happily below the threshold.

        The sample is ``this charger's draw / commanded amps``, folded into
        a per-charger EMA while genuinely charging. SINGLE-charger installs
        only for the live sample: the fleet ``power.ev_power`` equals this
        charger's draw iff there is exactly one — on multi-charger installs
        we return the memo or nameplate rather than commit the fleet-read
        class bug (docs/MULTI_CHARGER.md).
        """
        nameplate = (float(cfg.get("ev_phases") or 3)
                     * float(cfg.get("ev_voltage") or 230))
        chargers = self.config.get("ev_chargers") or []
        if power is not None and len(chargers) == 1:
            amps = int(getattr(self, "_last_commanded_amps_fleet", 0) or 0)
            watts = float(getattr(power, "ev_power", 0.0) or 0.0)
            if amps >= 1 and watts > 400:
                sample = min(nameplate, max(100.0, watts / amps))
                prev = self._ev_wpa_ema.get(cid)
                self._ev_wpa_ema[cid] = (
                    sample if prev is None else 0.7 * prev + 0.3 * sample
                )
                # (#638 night 2) Mirror the learn into storage — the EMA
                # died at every restart, so a deploy minutes before the
                # night pack put the floor back at nameplate: 6.9 kW, no
                # slot under the peak, yield, and the reactive layer
                # charged a car the plan should have governed. Mirrored
                # on LEARN only; reads run several times per cycle.
                _st = getattr(self, "_storage", None)
                if _st is not None:
                    _st.set_ev_wpa_state(dict(self._ev_wpa_ema))
        learned = self._ev_wpa_ema.get(cid)
        return float(learned) if learned else nameplate

    def request_replan(self) -> None:
        """(#638) The explicit re-plan action: the next cycle discards
        the current stamp and re-plans with cause 'manual'."""
        self._manual_replan_requested = True

    def _restore_energy_plan(self, state) -> None:
        """(#638) Re-seat tonight's stamped plan after a reboot.

        The plan is STATE the actuation steers by — 'why would a reboot
        destroy the planning, it has to survive' (Guido, 00:20 on
        2026-08-09, his own Aug-5 follow-up note made acute). Restores
        the stash, the period key and the demand signature so the tick
        sees the same night and does not silently reshuffle it; the
        ask-change trigger still works because the signature is
        restored TUPLE-SHAPED — a JSON round-trip turns tuples into
        lists, and an unequal shape would re-plan immediately, defeating
        the persistence. Anything malformed restores nothing (the #563
        per-entry rule: fall back to re-plan-on-boot, never corrupt).
        """
        try:
            if not isinstance(state, dict):
                return
            plan = state.get("plan")
            period_s = state.get("period")
            if not isinstance(plan, dict) or not plan.get("computed_at"):
                return
            from datetime import date as _date
            period = _date.fromisoformat(str(period_s))

            def _tuples(v):
                if isinstance(v, list):
                    return tuple(_tuples(x) for x in v)
                return v

            self._energy_plan_shadow = plan
            self._shadow_plan_date = period
            self._plan_ev_conn_sig = _tuples(state.get("sig"))
            # (#638 C4c) re-seat the scheduler's SCHEDULED verdict so the
            # restored night's battery block can actuate before the next
            # evaluation window re-derives the WHAT.
            _bcs = getattr(self, "_battery_charge_scheduler", None)
            if _bcs is not None:
                from .battery_charge_scheduler import restore_battery_verdict
                restore_battery_verdict(_bcs, state.get("battery_verdict"))
            _LOGGER.info(
                "ENERGY-PLAN (#638): restored the stamped plan for "
                "period %s (computed %s) — the reboot does not reshuffle "
                "the night", period, str(plan.get("computed_at"))[:19],
            )
        except Exception:  # noqa: BLE001 — a bad stash is a re-plan, not a crash
            _LOGGER.debug("energy plan restore skipped", exc_info=True)

    def _restore_ev_wpa(self, state) -> None:
        """(#638 night 2) Seed the measured-W/A EMA from storage at boot.

        Per-entry repair (the #563 rule): a corrupt value is dropped
        alone, the rest restore. The bounds mirror the learn-time clamp —
        100 W/A is the accessor's own floor, 2000 comfortably covers any
        phases × voltage nameplate while rejecting the nonsense that
        would re-poison the pack this restore exists to protect.
        """
        for cid, val in (state or {}).items():
            try:
                wpa = float(val)
            except (TypeError, ValueError):
                continue
            if 100.0 <= wpa <= 2000.0:
                self._ev_wpa_ema[str(cid)] = wpa

    def _charger_priority_rows(self) -> "List[Dict[str, Any]]":
        """(#576 P2.1) Priority-list rows for every configured EV charger,
        keyed by CONTROL id, for the device registry.

        The registry emits these (suppressing the ED ``is_ev`` naming guess)
        so a charger's list position is its single authoritative priority —
        the same id the drag store and the reclaim gate use. Live power is
        best-effort from the charger's power sensor; the priority itself
        comes from ``dev.priority`` (already resolved from
        the drag store this cycle).
        """
        rows: "List[Dict[str, Any]]" = []
        for cid, dev in (self._ev_devices or {}).items():
            # (#643) canonical read path (raw fallback inside normalizes
            # kW — this display read previously showed a kW charger as ~0 W).
            pw = (
                self._charger_power_w(cid, None, dev)
                if getattr(self, "hass", None) is not None else 0.0
            )
            ent = getattr(dev, "power_entity_id", None)  # metadata only
            ph = int(getattr(dev, "phases", 3) or 3)
            volt = float(getattr(dev, "voltage", 230) or 230)
            max_a = float(getattr(dev, "max_current", 32) or 32)
            min_a = float(getattr(dev, "min_current", 6) or 6)
            connected = False
            per = getattr(self, "_last_ev_connected_per_charger", None)
            if isinstance(per, dict):
                connected = bool(per.get(cid, False))
            rows.append({
                "id": cid,
                "name": getattr(dev, "name", cid),
                "priority_seed": int(getattr(dev, "priority", 3) or 3),
                "power_entity": ent,
                # (#748) the charger's OTHER declared entities, so the registry's
                # identity fold + data-layer reconcile recognise an ED row or a
                # discovered switch that names the charger's stop switch /
                # current number / status sensor — not only its power sensor.
                # #700's fold saw only power_entity and missed "Billaddare"
                # (keyed on the stop switch). Empty strings ("" defaults on the
                # status / offer sensors) normalize to None; the registry
                # filters falsy entries.
                "control_entity": getattr(dev, "entity_id", None) or None,
                "current_entity": getattr(dev, "current_entity_id", None) or None,
                "current_sensor_entity": getattr(dev, "current_sensor_entity_id", None) or None,
                "status_entity": getattr(dev, "charging_status_entity", None) or None,
                "start_stop_entity": getattr(dev, "start_stop_entity", None) or None,
                "charge_mode_entity": getattr(dev, "charge_mode_entity", None) or None,
                "service_entity": getattr(dev, "charger_service_entity_id", None) or None,
                "current_power_w": pw,
                "is_on": pw > 50.0,
                # min = the surplus threshold to start (the meaningful "rating");
                # max kept for the EV status card.
                "min_power_w": min_a * ph * volt,
                "max_power_w": max_a * ph * volt,
                "connected": connected,
            })
        return rows

    # ─────────────────────────────────────────────────────────────────
    # Mode-driven adapters — #277 Phase B
    #
    # Phase A introduced ``_effective_charge_mode_for`` as the single
    # read-point for user intent. Phase B routes EVERY consumer of the
    # legacy four-toggle state through that mode. The strategy machine,
    # the night state machine, the EV-control loop, the dashboard sensor
    # — all derive their effective state from the per-charger mode, no
    # longer from individual switch reads.
    #
    # The mapping (see ``consts/ev_charge_modes.py`` for the source-of-
    # truth constants):
    #   solar_only        → no night, no tariff, smart N/A, mode≈auto
    #   solar_plus_cheap  → night ON, tariff ON, smart ON, mode≈auto
    #   min_plus_solar    → night ON, tariff OFF, smart ON, mode≈minpv
    #   always_max        → night ON (irrelevant, mode is now), tariff OFF, smart OFF, mode≈now
    #   off               → all OFF, mode≈off
    #
    # The legacy switch entities (`switch.sem_charger_<id>_night_charging`,
    # `_smart_night_charging`, `_tariff_optimized`) stay registered for
    # automation backward-compatibility but no longer drive behaviour.
    # Phase C removes them entirely after a v1.7.x soak.
    # ─────────────────────────────────────────────────────────────────

    def _mode_allows_night_charging(self, charger_cfg: dict) -> bool:
        """Does this charger's mode permit night/grid charging at all?

        (#634) solar_only participates ONLY when its "At least" floor is set —
        the floor is the mode-independent overnight guarantee. Floor 0 keeps the
        classic never-grids-at-night contract (#346).

        (#679) The rule moved to ``consts.ev_charge_modes`` instead of being
        hand-copied here and in ``ChargingStateMachine._night_capable``. Both
        copies carried a "keep in sync" note; the shared function IS the sync.
        It also fixes what made the #634 default unreachable — see
        ``mode_allows_night_charging`` for why a *global* floor cannot serve as
        an opt-in.
        """
        from ..consts.ev_charge_modes import mode_allows_night_charging
        return mode_allows_night_charging(self.config, charger_cfg)

    def _mode_uses_tariff(self, charger_cfg: dict) -> bool:
        """Does this charger's mode defer to tariff-cheap windows?

        Only ``solar_plus_cheap`` defers — all other night-charging modes
        run straight through. Replaces the legacy
        ``switch.sem_charger_<id>_tariff_optimized``.
        """
        from ..consts.ev_charge_modes import MODE_USES_TARIFF
        return self._effective_charge_mode_for(charger_cfg) in MODE_USES_TARIFF

    def _mode_uses_smart_night(self, charger_cfg: dict) -> bool:
        """Does this charger's mode use forecast-aware night sizing?

        ON implicitly for ``solar_plus_cheap`` and ``min_plus_solar``
        (Q3 decision: forecast-aware is strictly better than dumb; no
        value in user disablement). N/A elsewhere. Replaces the legacy
        ``switch.sem_charger_<id>_smart_night_charging``.
        """
        from ..consts.ev_charge_modes import MODE_USES_SMART_NIGHT
        return self._effective_charge_mode_for(charger_cfg) in MODE_USES_SMART_NIGHT

    # ``_legacy_charging_mode_for`` belongs to Phase C — it's the helper
    # that the strategy-machine rewrite will introduce alongside the
    # call site that uses it. Adding it here in Phase B as orphaned
    # infrastructure would confuse the Phase C author about whether
    # Phase B forgot to wire it. The mapping constants
    # (``MODE_TO_LEGACY_CHARGING_MODE``) live in
    # ``consts/ev_charge_modes.py`` so Phase C just imports them.

    def _smart_night_charging_enabled(self) -> bool:
        """True if smart (forecast-aware) night charging is on for any charger.

        Post-#277 Phase B: derives from ``charge_mode`` per charger, not
        from the legacy ``switch.sem_charger_<id>_smart_night_charging``.
        The switch entity stays registered for automation backward-compat
        but no longer drives this answer.
        """
        chargers = self.config.get("ev_chargers") or []
        if not chargers:
            # Pre-EV installs: no chargers, nothing to enable.
            return False
        return any(
            self._mode_uses_smart_night(c) for c in chargers
            if isinstance(c, dict)
        )

    def _per_charger_daily_report(self, energy) -> Dict[str, float]:
        """Per-charger daily EV energy for the sensors.

        The per-charger integrator (``_daily_ev_per_charger``) is rebuilt from power
        each restart, while the GLOBAL daily_ev is persisted + sunrise-reset — so after a
        restart the per-charger value under-reports vs the global summary. For a SINGLE
        charger the two are the same quantity by definition, so report the global daily_ev
        to keep them consistent. Multiple chargers report their own (persisted) accumulators,
        which sum to the global.
        """
        pcd = dict(self._daily_ev_per_charger)
        chargers = self.config.get("ev_chargers") or []
        if len(chargers) == 1 and isinstance(chargers[0], dict):
            # Same id fallback as registration (#485 H1) — an id-less
            # charger registers as ev_charger_0, and this key must hit
            # the same per-charger accumulator slot.
            cid = self.primary_charger_id()
            pcd[cid] = round(getattr(energy, "daily_ev", 0.0) or 0.0, 3)
        return pcd

    def _charger_daily_kwh(self, cid: str, energy) -> float:
        """THIS charger's delivered-today kWh, on the SAME basis the dashboard
        shows — the ONE accessor for every decision/preview read.

        PROD 2026-07-17 night-idle bug: the user raised the daily target to
        14.5 kWh with "Today" showing 13.09, but night charging stayed idle —
        ``_calculate_remaining_need`` read the RAW per-charger integrator
        (15.42 kWh, drifted high during a flap incident) while the dashboard
        showed the persisted global (13.09). Two accumulators for the same
        quantity → the paired-figure basis-mismatch class (BUG_CLASSES #11):
        the user tunes the target against the displayed figure, so decisions
        MUST measure against that same figure (same substitution
        ``_per_charger_daily_report`` applies for the sensors, #536).

        Contracts honoured (CI caught both on the first cut):
        - single charger → the persisted GLOBAL ``daily_ev`` (displayed basis);
        - multi-charger with own accounting → THIS charger's accumulator;
        - multi-charger, cid absent from the map → the FLEET total (#351 H1:
          conservative — over-counts consumed so a top-up never overshoots.
          Caveat since #724: on a fleet with DIFFERENT Charge-by times the
          fleet bucket rolls at midnight, so between 00:00 and this
          charger's own deadline it can UNDER-count a pre-midnight session
          — never-overshoot holds only from the charger's deadline onward.
          The path needs a fresh/unpersisted charger id AND a
          mixed-deadline fleet to matter);
        - defensive on stubs (no ``_daily_ev_per_charger`` attr → empty map).
        """
        pcd = getattr(self, "_daily_ev_per_charger", None) or {}
        chargers = self.config.get("ev_chargers") or []
        global_daily = float(getattr(energy, "daily_ev", 0.0) or 0.0)
        if len(chargers) == 1:
            return global_daily
        if cid in pcd:
            return float(pcd[cid] or 0.0)
        return global_daily

    @property
    def battery_capacity_kwh(self) -> float:
        """Battery capacity in kWh — auto-detected or from config (#84)."""
        val = self.config.get("battery_capacity_kwh")
        if val is not None and val > 0:
            return float(val)
        if self._detected_battery_capacity_kwh is None:
            detected = self._sensor_reader.auto_detect_battery_capacity_kwh()
            self._detected_battery_capacity_kwh = detected if detected is not None else 0.0
        if self._detected_battery_capacity_kwh > 0:
            return self._detected_battery_capacity_kwh
        return float(DEFAULT_BATTERY_CAPACITY_KWH)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, "sem")},
            name="SEM",
            manufacturer="Home Assistant",
            model="Solar EV Charging Controller",
            sw_version=self._get_version(),
            configuration_url="https://github.com/traktore-org/sem-community",
        )

    def _check_sign_flip(self, power) -> bool:
        """Check energy balance and auto-correct grid sign if persistently negative.

        Returns True if the sign was flipped (caller should re-read power).
        Low-confidence split-grid picks suppress the flip for up to 3 cycles
        (~9 min) to give late-loading integrations time to register (issue #166).

        Two things it must NOT do (#690):

        1. **Fight the user.** A negative balance proves the inputs disagree,
           not WHICH one is wrong — this heal always blames the grid. With
           ``grid_sign_invert`` set it is worse than useless: that path
           short-circuits the autodetect, so the flag toggled here is never
           read, the balance can't change, and 3 min later it toggles again —
           ``sensor.sem_diag_grid_sign`` oscillating normal↔negated forever.
        2. **Oscillate.** If the balance is negative for a NON-grid reason
           (wrong battery sign, unmetered load, missing sensor) one attempt
           won't fix it. Revert that attempt and latch off rather than flip
           on every 3-min window for the rest of the day.
        """
        energy_in = power.solar_power + power.grid_import_power + power.battery_discharge_power
        # FLEET-READ: energy balance — needs fleet total EV draw because
        # home_consumption is computed from the whole-house energy in/out.
        energy_out = power.ev_power + power.grid_export_power + power.battery_charge_power
        raw_balance = energy_in - energy_out
        if raw_balance < -500:
            # Guard 1 (#690): an explicit user decision is not a fault to heal.
            if getattr(self._sensor_reader, "grid_sign_user_override", False):
                return False
            self._positive_balance_count = 0
            self._negative_balance_count = getattr(self, '_negative_balance_count', 0) + 1
            if self._negative_balance_count >= 18:  # ~3 min sustained negative
                # Guard 2 (#690): one attempt only. The previous flip didn't
                # fix the balance, so the grid sign wasn't the problem — put
                # it back (including the persisted lock, #476) and stand down.
                if getattr(self, "_sign_flip_latched", False):
                    self._negative_balance_count = 0
                    return False
                if getattr(self, "_sign_flip_attempted", False):
                    self._sensor_reader._grid_sign_inverted = (
                        not self._sensor_reader._grid_sign_inverted
                    )
                    self._sensor_reader._grid_sign_detected = getattr(
                        self, "_sign_flip_detected_before", False
                    )
                    self._sign_flip_latched = True
                    self._sign_flip_attempted = False
                    self._negative_balance_count = 0
                    _LOGGER.warning(
                        "Grid-sign auto-correction did not fix the energy balance "
                        "(%.0fW still negative) — reverting it and standing down. "
                        "The imbalance is NOT the grid sign; check the battery "
                        "sign or an unmetered load. Use the Control-tab flip "
                        "button or reset_sign_detection to retry manually.",
                        raw_balance,
                    )
                    # True = "sign changed, re-read power". It changed BACK, so
                    # the re-read reproduces the pre-flip reading — one wasted
                    # read, but the contract stays honest and the caller's
                    # cached readings can't keep the reverted sign.
                    return True
                disc = getattr(self._sensor_reader, "_split_grid_discovery", None)
                self._sign_flip_suppression_count = getattr(self, '_sign_flip_suppression_count', 0)
                if disc and disc.get("confidence") == "any-device" and self._sign_flip_suppression_count < 3:
                    self._sign_flip_suppression_count += 1
                    _LOGGER.debug(
                        "Negative balance %.0fW with low-confidence split-grid "
                        "discovery — suppressing sign flip pending re-discovery "
                        "(attempt %d/3)",
                        raw_balance, self._sign_flip_suppression_count,
                    )
                    self._negative_balance_count = 0
                    return False
                # Auto-correct: flip the grid sign
                # (#690) Remember the pre-flip lock so a failed attempt can be
                # reverted cleanly — the flip below stamps `_grid_sign_detected`,
                # which is PERSISTED (#476), so a wrong guess would otherwise
                # outlive the restart that might have healed it.
                self._sign_flip_detected_before = bool(
                    self._sensor_reader._grid_sign_detected
                )
                self._sign_flip_attempted = True
                self._sensor_reader._grid_sign_inverted = not self._sensor_reader._grid_sign_inverted
                self._sensor_reader._grid_sign_detected = True
                _LOGGER.warning(
                    "Energy balance negative (%.0fW) for 3+ min — auto-correcting grid sign "
                    "(now %s). Solar=%.0fW Grid=%.0fW Battery=%.0fW",
                    raw_balance,
                    "negated" if self._sensor_reader._grid_sign_inverted else "normal",
                    power.solar_power, power.grid_power, power.battery_power,
                )
                self._negative_balance_count = 0
                self._sign_flip_suppression_count = 0
                return True
        else:
            self._negative_balance_count = max(0, getattr(self, '_negative_balance_count', 0) - 1)
            # (#690) The balance recovered, so the last flip was RIGHT — clear
            # the attempt so a genuinely new fault later (swapped hardware, a
            # re-configured meter) can still be healed once.
            #
            # Confirmation must be as sustained as the trip (~3 min), else an
            # INTERMITTENT non-grid fault re-opens the oscillation on a longer
            # period: negative ×18 → flip → one healthy cycle clears → negative
            # ×18 → flip back → … Symmetric thresholds close that.
            self._positive_balance_count = getattr(self, '_positive_balance_count', 0) + 1
            if self._positive_balance_count >= 18:
                self._sign_flip_attempted = False
        return False

    # Two-tier hold for transient home-consumption dips to 0 (#237, #444).
    #
    # The energy balance clamps ``home_consumption_power`` to 0 whenever the
    # instantaneous input sensors don't agree (one source updates 10–60 s before
    # another). On a typical Huawei + KEBA + LUNA2000 stack a 10-min PROD
    # recording on 2026-06-06 showed 16% of cycles with a zero clamp during
    # active EV charging.
    #
    # Two-tier hold exploits a strong signal already on hand: if the RAW balance
    # is strongly negative, energy is "flowing out faster than in" — physically
    # impossible, so we KNOW the inputs are inconsistent. Hold longer in that
    # case. For shallow zeros (raw ≈ 0), keep a short hold so a genuinely
    # sustained zero still gets reported as real.
    #
    # Simulated against the 2026-06-06 PROD recording: this drops the zero-clamp
    # rate from 37% (single-tier 2-cycle baseline) to 3% during active charging
    # at variable solar.
    HOME_HOLD_MAX_CYCLES = 10                  # ~100 s @ 10 s coordinator cycle
    HOME_HOLD_INCONSISTENT_MAX = 30            # ~5 min when raw balance is strongly negative
    SENSOR_INCONSISTENCY_THRESHOLD_W = -100.0  # raw_balance < this = guaranteed stale sensor
    # Spike guard (symmetric to the dip hold): a fast EV load ramp makes the
    # grid meter lead the KEBA ev_power sensor by a cycle, so home transiently
    # inflates by ~the EV draw. A one-cycle jump above last + this threshold is
    # treated as that lag and the last value is held — keeps the battery
    # discharge-protection limit (home/n) from briefly over-allowing discharge.
    HOME_SPIKE_THRESHOLD_W = 2000.0            # >2 kW one-cycle jump = likely sensor lag
    HOME_HOLD_SPIKE_MAX = 2                    # hold at most 2 cycles; a real rise is then accepted

    def _smooth_home_consumption(self, power) -> None:
        """Hold the last positive home-consumption value through transient dips to 0 (#237, #444).

        The energy balance clamps ``home_consumption_power`` to 0 when instantaneous
        sensor readings momentarily lag a large load. Two-tier hold:

          • **Inconsistency hold** (``HOME_HOLD_INCONSISTENT_MAX`` cycles): when the
            raw balance is strongly negative (below
            ``SENSOR_INCONSISTENCY_THRESHOLD_W``), the inputs are guaranteed
            inconsistent — energy can't actually flow out faster than in. Hold
            the last positive value for up to ~5 min while the slow sensor
            (typically Huawei battery, KEBA EV at 60+ s push gap, or grid meter
            trailing a solar drop) catches up.
          • **Transient hold** (``HOME_HOLD_MAX_CYCLES`` cycles): when the raw
            balance is at or near zero, only a brief hold — a sustained zero
            past that window is real and gets reported.

        Runs before energy integration so the held value also keeps the
        home-energy total from under-counting.
        """
        # Whether THIS cycle's home value is a hold substitute. Read by
        # the health check (#461): a substituted value breaks the
        # supply≈demand identity by construction, so the balance check
        # must not count those cycles as violations.
        self._home_hold_active = False
        if power.home_consumption_power > 0:
            last = getattr(self, "_last_home_consumption", 0.0)
            held = getattr(self, "_home_hold_count", 0)
            # Upward-spike guard (symmetric to the dip hold below). A fast EV
            # load ramp makes the grid meter register the car's draw a cycle
            # before the KEBA ev_power sensor does, so ``grid_import`` counts
            # the car while ``ev`` doesn't → home inflates by ~the EV draw for
            # 1-2 cycles. That would inflate the discharge-protection limit
            # (home/n) and briefly let the inverter feed the battery into the
            # car below the buffer (PROD 2026-06-26, always_max ramp: limit
            # spiked to 9213 W). Hold the last good value through the brief
            # spike; a genuine, persistent rise (an appliance) is accepted
            # once the short hold window expires.
            if (
                last > 0
                and power.home_consumption_power > last + self.HOME_SPIKE_THRESHOLD_W
                and held < self.HOME_HOLD_SPIKE_MAX
            ):
                self._home_hold_count = held + 1
                self._home_hold_active = True
                _spike = power.home_consumption_power
                power.home_consumption_power = last
                _LOGGER.debug(
                    "Home consumption spike %.0fW (> last %.0fW + %.0f) — "
                    "holding %.0fW (%d/%d) — likely EV/grid sensor lag",
                    _spike, last, self.HOME_SPIKE_THRESHOLD_W, last,
                    self._home_hold_count, self.HOME_HOLD_SPIKE_MAX,
                )
                return
            self._last_home_consumption = power.home_consumption_power
            self._home_hold_count = 0
            return
        last = getattr(self, "_last_home_consumption", 0.0)
        held = getattr(self, "_home_hold_count", 0)
        if last <= 0:
            # No prior positive value — accept the zero (cold start / first cycles).
            self._home_hold_count = held + 1
            return

        # Decide which hold tier applies using the raw balance.
        raw_in = (
            getattr(power, "solar_power", 0.0)
            + getattr(power, "grid_import_power", 0.0)
            + getattr(power, "battery_discharge_power", 0.0)
        )
        raw_out = (
            getattr(power, "ev_power", 0.0)
            + getattr(power, "grid_export_power", 0.0)
            + getattr(power, "battery_charge_power", 0.0)
        )
        raw_balance = raw_in - raw_out
        is_inconsistent = raw_balance < self.SENSOR_INCONSISTENCY_THRESHOLD_W
        max_cycles = (
            self.HOME_HOLD_INCONSISTENT_MAX if is_inconsistent
            else self.HOME_HOLD_MAX_CYCLES
        )

        if held < max_cycles:
            self._home_hold_count = held + 1
            self._home_hold_active = True
            power.home_consumption_power = last
            _LOGGER.debug(
                "Home consumption clamped to 0 — holding last %.0fW (%d/%d, raw_balance=%.0fW, %s)",
                last, self._home_hold_count, max_cycles, raw_balance,
                "inconsistent" if is_inconsistent else "transient",
            )
        else:
            # Hold window exhausted — accept the zero as real.
            self._home_hold_count = held + 1

    # (#699) The published set must satisfy the equation within this
    # tolerance to be cached as "coherent". In a clean cycle the residual is
    # ~0 BY CONSTRUCTION (home is computed from the other terms), so
    # anything beyond rounding noise means a hold substituted home or the
    # negative-balance clamp fired — the two ways a published set lies.
    SNAPSHOT_RESIDUAL_TOLERANCE_W = 150.0
    # (#699 follow-up) Attribution guard: the residual check cannot see a
    # MISATTRIBUTED set — once the spike guard accepts an EV start into
    # home (the KEBA power sensor can push 60+ s late), the equation
    # balances again with the car's draw sitting on the home node. The
    # charger's charging BINARY is the fast disambiguator: charging=on
    # while ev_power reads ~0 means the EV sensor is lagging and the
    # balance cannot attribute correctly — keep shipping the last coherent
    # set until the sensor catches up. Bounded: past this many cycles the
    # 0 is believed (a paused charge legitimately draws nothing).
    SNAPSHOT_EV_LAG_MAX_CYCLES = 12          # ~2 min @ 10 s cycles
    SNAPSHOT_EV_LAG_POWER_FLOOR_W = 100.0

    def _build_power_snapshot(self, power) -> dict:
        """(#699) The cards' balance set — the LAST SELF-CONSISTENT one.

        Publishing the raw per-cycle values reproduces the bug this fixes:
        during a source-cadence skew (grid meter leads the EV sensor on a
        fast ramp) the home hold (#237/#444) deliberately substitutes home
        while grid/EV carry the raw skewed reads — a set that violates its
        own equation, shipped to the view. The FIRST fix for this class
        was the held home entity itself (it protected home's value and the
        discharge limit, but knowingly published an inconsistent SET); the
        snapshot completes it: when this cycle's set is known-incoherent
        (hold active, or the residual exceeds tolerance), carry the whole
        previous coherent set forward — flagged ``held`` — instead of a
        chimera of fresh and substituted values. SOC is overlaid fresh:
        it is not balance-coupled, and a 5-minute-stale SOC would be worse
        than an honest one.
        """
        soc = None if getattr(power, "battery_soc_unavailable", False) \
            else getattr(power, "battery_soc", None)
        snap = {
            "solar_w": power.solar_power,
            "grid_w": power.grid_power,
            "grid_import_w": power.grid_import_power,
            "grid_export_w": power.grid_export_power,
            "battery_w": power.battery_power,
            "battery_charge_w": power.battery_charge_power,
            "battery_discharge_w": power.battery_discharge_power,
            # FLEET-READ: the cards' EV node shows the fleet total draw —
            # the balance equation needs the sum, not one charger's share.
            "ev_w": power.ev_power,
            "home_w": power.home_consumption_power,
            "battery_soc": soc,
            "held": False,
        }
        residual = abs(
            (power.solar_power or 0.0)
            + (power.grid_import_power or 0.0)
            + (power.battery_discharge_power or 0.0)
            - (power.grid_export_power or 0.0)
            - (power.battery_charge_power or 0.0)
            # FLEET-READ: same equation, same fleet-total semantics.
            - (power.ev_power or 0.0)
            - (power.home_consumption_power or 0.0)
        )
        # (#699 follow-up) EV-sensor lag: charging binary on, power sensor
        # still ~0 → any step the balance just absorbed into home may be
        # the car's. Hold the coherent set rather than misattribute; the
        # counter bounds it and only resets when the condition clears, so
        # a genuinely paused charge (binary on, truly 0 W) is believed
        # after the window instead of pinning the view forever.
        ev_lag = (
            bool(getattr(power, "ev_charging", False))
            # FLEET-READ: fleet charging-binary OR vs fleet power total —
            # the lag test compares like with like.
            and (power.ev_power or 0.0) <= self.SNAPSHOT_EV_LAG_POWER_FLOOR_W
        )
        if ev_lag:
            self._snapshot_ev_lag_count = getattr(
                self, "_snapshot_ev_lag_count", 0) + 1
        else:
            self._snapshot_ev_lag_count = 0
        ev_lag_hold = ev_lag and (
            self._snapshot_ev_lag_count <= self.SNAPSHOT_EV_LAG_MAX_CYCLES
        )
        incoherent = (
            getattr(self, "_home_hold_active", False)
            or residual > self.SNAPSHOT_RESIDUAL_TOLERANCE_W
            or ev_lag_hold
        )
        last = getattr(self, "_last_coherent_snapshot", None)
        if incoherent and last is not None:
            held = dict(last)
            held["battery_soc"] = soc
            held["held"] = True
            return held
        if not incoherent:
            cache = dict(snap)
            cache.pop("held", None)
            self._last_coherent_snapshot = cache
        # incoherent with no cache yet (cold start mid-transient): the raw
        # set is the best available — publish it rather than nothing.
        return snap

    # Class-level cache — the manifest never changes within a run, but
    # _get_version() used to re-open it on EVERY cycle (diag_version),
    # flagged live as "Detected blocking call to open" (#476 follow-up).
    # Setup warms the cache via async_add_executor_job so the single
    # file read happens off the event loop.
    _version_cache: str | None = None

    @classmethod
    def _get_version(cls) -> str:
        """Read version from manifest.json (single source of truth with HACS)."""
        if cls._version_cache is not None:
            return cls._version_cache
        import json as _json
        import os
        manifest = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manifest.json")
        try:
            with open(manifest) as f:
                cls._version_cache = _json.load(f).get("version", "0.0.0")
        except (OSError, ValueError):
            cls._version_cache = "0.0.0"
        return cls._version_cache

    def _collect_ev_counter_entities(self) -> List[str]:
        """Every charger's own energy counter, for #658 reconciliation.

        The bucket being reconciled is the FLEET daily total, so this must
        gather the whole fleet — one charger's counter alone would be adopted
        as if it were all of them.

        Preference order, and why each level is exclusive rather than additive:

        1. Each charger's ``ev_total_energy_sensor`` (lifetime, per-charger —
           the drift-free source ``_update_per_charger_detector_energy``
           already trusts). The top-level key belongs to the PRIMARY charger by
           the auto-fill convention in ``__init__`` (#639), so it is a fallback
           for the primary only — never for siblings.
        2. Otherwise the legacy ``ev_daily_energy_sensor``, or
        3. Otherwise the Energy Dashboard's ``ev_energy``.

        2 and 3 are fallbacks and NOT merged into 1: a daily counter and a
        lifetime counter for the same charger both report the same kWh, and
        summing their deltas would double-count every session.
        """
        chargers = self.config.get("ev_chargers") or []
        top_level = self.config.get("ev_total_energy_sensor")

        counters: List[str] = []
        for index, charger in enumerate(chargers):
            entity = charger.get("ev_total_energy_sensor")
            # "Primary" by POSITION, not by matching ``id`` against
            # ``chargers[0]["id"]`` — an id-less legacy entry would make that
            # comparison true for every sibling and lend them all the same
            # counter, which is the cross-contamination #639 removed.
            if not entity and index == 0:
                entity = top_level
            if entity:
                counters.append(entity)
        if not counters and top_level:
            counters.append(top_level)  # counters configured, no charger list yet

        if not counters:
            legacy = self.config.get("ev_daily_energy_sensor")
            ed_ev = getattr(self._energy_dashboard_config, "ev_energy", None)
            fallback = legacy or ed_ev
            if fallback:
                counters.append(fallback)
        return counters

    async def async_initialize_energy_dashboard(self, quiet: bool = False) -> bool:
        """Initialize sensors from HA Energy Dashboard.

        ``quiet`` demotes the routine INFO logs to DEBUG — used by the
        cold-start re-derivation retry (#274) so it doesn't spam the log each
        cycle while waiting for the source integration to register.
        """
        _info = _LOGGER.debug if quiet else _LOGGER.info
        try:
            dashboard_config = await read_energy_dashboard_config(self.hass, quiet=quiet)

            # Activate whenever the dashboard is minimally configured (solar + grid),
            # not only when a stat_rate power sensor exists. ha_energy_reader already
            # derives missing power sensors from the energy sensor's device (#250); if
            # none can be derived we still want energy counters + SOC working instead
            # of dropping to the empty legacy path (→ all zeros).
            if dashboard_config and dashboard_config.is_minimally_configured():
                self._energy_dashboard_config = dashboard_config
                self._sensor_reader.set_energy_dashboard_config(dashboard_config)
                _info(
                    f"Using Energy Dashboard sensors: "
                    f"solar={dashboard_config.solar_power}, "
                    f"grid={dashboard_config.grid_import_power}, "
                    f"battery={dashboard_config.battery_power}"
                )

                # (#556) daily-solar reconciliation against the inverter's
                # production counters — gated by prefer_hardware_energy.
                solar_counters = list(dashboard_config.solar_energy_list) or (
                    [dashboard_config.solar_energy] if dashboard_config.solar_energy else []
                )
                self._energy_calculator.configure_solar_counters(
                    self.hass,
                    solar_counters,
                    self.config.get("prefer_hardware_energy", True),
                )

                # (#628) grid + battery reconciliation against the SAME
                # counters HA's Energy Dashboard reads. Until now those
                # registers were read exactly once, at boot, to seed lifetime
                # totals — so the daily rows the user compares against the
                # Energy Dashboard were pure power integration, and every
                # dropped or mis-signed sample stayed in them forever.
                meter_counters: Dict[str, List[str]] = {}
                for category, single, listed in (
                    ("grid_import", dashboard_config.grid_import_energy,
                     dashboard_config.grid_import_energy_list),
                    ("grid_export", dashboard_config.grid_export_energy,
                     dashboard_config.grid_export_energy_list),
                    ("battery_charge", dashboard_config.battery_charge_energy,
                     dashboard_config.battery_charge_energy_list),
                    ("battery_discharge", dashboard_config.battery_discharge_energy,
                     dashboard_config.battery_discharge_energy_list),
                ):
                    entities = list(listed) or ([single] if single else [])
                    if entities:
                        meter_counters[category] = entities
                self._energy_calculator.configure_meter_counters(
                    self.hass,
                    meter_counters,
                    self.config.get("prefer_hardware_energy", True),
                )

                # v1.7.0 / #312: auto-discover per-PV-string sensors and
                # plumb them to the sensor reader so every cycle populates
                # ``readings.solar_power_per_string``. Discovery is a
                # config-flow-time operation — done once here, not per
                # cycle. ``discover_pv_strings_from_registry`` was already
                # used by ``dashboard_generator`` for the K-Flow card; we
                # now also feed SEM's own sensors + cards.
                try:
                    from ..hardware_detection import (
                        discover_pv_strings_from_registry,
                        discover_pv_string_vi_pairs,
                    )
                    pv_strings = discover_pv_strings_from_registry(
                        self.hass, dashboard_config,
                    ) or {}
                    # V+I synthesis (v1.7.0): for integrations that
                    # publish per-string voltage + current but no
                    # per-string power (Huawei Solar Modbus, generic
                    # Modbus drivers). SEM multiplies V × I at read
                    # time so these users get the per-string sensors
                    # without writing a template themselves. Direct
                    # power match wins over V+I synthesis when both
                    # exist for the same slot (real sensor preferred).
                    vi_pairs = discover_pv_string_vi_pairs(
                        self.hass, dashboard_config,
                    ) or {}
                    self._sensor_reader.set_pv_strings(pv_strings, vi_pairs)
                    # (#566) user-chosen per-string display names from options
                    if self.config_entry is not None:
                        self._sensor_reader.set_pv_string_names(
                            self.config_entry.options.get("pv_string_names", {})
                        )
                    if pv_strings or vi_pairs:
                        _info(
                            "Per-PV-string discovery: %d direct power, "
                            "%d V+I pairs",
                            len(pv_strings), len(vi_pairs),
                        )
                except Exception as err:  # noqa: BLE001 — discovery never fatal
                    _LOGGER.debug(
                        "PV string discovery skipped (non-fatal): %s", err,
                    )
            else:
                _info("Energy Dashboard not configured or incomplete")

        except Exception as e:
            _LOGGER.warning("Failed to read Energy Dashboard: %s", e)

        # (#556) No Energy Dashboard — fall back to the explicitly
        # configured solar energy counter for daily-solar reconciliation.
        if not self._energy_dashboard_config:
            manual_counter = self.config.get("solar_energy_sensor")
            if manual_counter:
                self._energy_calculator.configure_solar_counters(
                    self.hass,
                    [manual_counter],
                    self.config.get("prefer_hardware_energy", True),
                )

        # (#658) daily-EV reconciliation against the wallbox counters. This was
        # parked for years because a midnight-resetting charger counter cannot be
        # compared ABSOLUTELY against a bucket that rolls at the charge deadline —
        # true, and no longer relevant: the reconciliation is delta-based now, and
        # a counter reset is just a reset (see ``_reconcile_ev_energy``). Power
        # integration is only "reliable enough" while SEM is running; the energy
        # this recovers is precisely the energy charged while it was not.
        self._energy_calculator.configure_ev_counters(
            self.hass,
            self._collect_ev_counter_entities(),
            self.config.get("prefer_hardware_energy", True),
        )

        # Log EV sensor configuration
        ev_power = self._sensor_reader.config.ev_power_sensor
        ed_ev = getattr(self._energy_dashboard_config, 'ev_power', None) if self._energy_dashboard_config else None
        _info(
            "EV sensors: ed_power=%s, config_power=%s",
            ed_ev, ev_power,
        )

        # Cold-start recovery flag (#274): if a source has an energy sensor but its
        # real-time power sensor couldn't be derived yet (the source integration
        # hadn't registered its entities when we ran), keep re-deriving each cycle.
        self._ed_resolve_pending = bool(
            self._energy_dashboard_config
            and self._energy_dashboard_config.power_resolution_incomplete()
        )

        return self._energy_dashboard_config is not None

    async def _retry_energy_dashboard_resolution(self) -> None:
        """Re-derive Energy Dashboard power sensors after a cold start (#274).

        On HA restart SEM can run its power-sensor derivation before the source
        integration (e.g. solax-modbus) has registered its entities, so the
        device-registry lookup finds nothing and every reading sits at 0 until the
        user manually reloads. Re-running the derivation each update cycle picks
        the sensors up the moment the source registers — no reload needed.

        Bounded by ``ED_RESOLVE_MAX_ATTEMPTS`` so a genuinely power-less setup
        (energy-only sensors) stops retrying instead of re-reading the energy
        prefs forever. ``async_initialize_energy_dashboard`` recomputes
        ``_ed_resolve_pending``, so this clears itself the cycle it succeeds.
        """
        if self._ed_resolve_attempts >= ED_RESOLVE_MAX_ATTEMPTS:
            self._ed_resolve_pending = False
            _LOGGER.warning(
                "Energy Dashboard power sensors still unresolved after %d attempts "
                "— giving up (check the source integration is loaded). #274",
                self._ed_resolve_attempts,
            )
            return
        self._ed_resolve_attempts += 1
        try:
            await self.async_initialize_energy_dashboard(quiet=True)
        except Exception as e:  # never let recovery break the update cycle
            _LOGGER.debug("Energy Dashboard re-resolution attempt failed: %s", e)
            return
        if not self._ed_resolve_pending:
            _LOGGER.info(
                "Energy Dashboard power sensors resolved on attempt %d — "
                "readings starting (#274)", self._ed_resolve_attempts,
            )

    async def async_initialize_load_management(self, config_entry: ConfigEntry) -> None:
        """Initialize load management after coordinator is set up."""
        load_management_enabled = self.config.get("load_management_enabled", True)

        _LOGGER.debug("async_initialize_load_management called: enabled=%s", load_management_enabled)

        if load_management_enabled and not self._load_manager:
            try:
                from ..load_management import LoadManagementCoordinator

                _LOGGER.info("Creating LoadManagementCoordinator...")
                self._load_manager = LoadManagementCoordinator(self.hass, config_entry)
                await self._load_manager.async_initialize()
                _LOGGER.info("LoadManagementCoordinator initialized with %s devices", len(self._load_manager._devices))
            except Exception as e:
                _LOGGER.warning("Failed to initialize load management: %s", e)
                self._load_manager = None

    def _get_initial_data(self) -> Dict[str, Any]:
        """Get initial data with defaults."""
        sem_data = SEMData()
        return sem_data.to_dict()

    # ── Layered-trace observability (1.7.5) ─────────────────────────────
    #
    # A READ-ONLY capture of this cycle's management→process→integration
    # chain into the trace ring buffer (dumped by the diagnose service).
    # It reads values the control layers already computed and NEVER feeds
    # anything back — so it cannot change a decision. The whole thing is
    # wrapped in try/except: observability must never break control.

    @property
    def _ev_taper_detector(self) -> "EVTaperDetector":
        """Primary charger's taper detector — COMPUTED, not swapped (#589
        Surface-B retirement).

        Returns the primary per-charger detector when the per-charger detectors
        exist; otherwise the default (the first-update restore window, before
        the per-charger loop has built them, and a bare single-charger install).
        Read-only: the ~30 call sites read or MUTATE the returned detector
        object (e.g. ``._full_detected = True``) — that still works, it mutates
        the resolved primary. The former per-cycle
        ``_ev_taper_detector = _ev_taper_detectors[primary_id]``
        reassignment (one of the two parallel per-charger swap surfaces) is
        gone: the primary is derived, so it can never drift out of sync.
        """
        devices = getattr(self, "_ev_devices", None)
        if devices:
            primary_id = next(iter(devices))
            det = self._ev_taper_detectors.get(primary_id)
            if det is not None:
                return det
        return self._ev_taper_detector_default

    @_ev_taper_detector.setter
    def _ev_taper_detector(self, value) -> None:
        # Writes go to the default backing detector (construction + a test
        # harness that disables taper via ``= None``). When per-charger
        # detectors exist the getter still resolves the primary from them.
        self._ev_taper_detector_default = value

    def _reset_per_charger_estimate_state(self, cid: str, was_connected: bool) -> None:
        """#708 — clear THIS charger's energy-accounted-SOC anchor and
        estimate-stop/resume flags on ITS OWN disconnect transition.

        ``_update_ev_intelligence`` resets the taper detector too, but only
        the PRIMARY charger's (``self._ev_taper_detector`` is computed from
        ``_ev_taper_detectors[primary_id]``), gated on the fleet-wide OR of
        every charger's connection state. #708 added steering-critical
        session fields (the SOC anchor) to the same detector class, so a
        secondary charger's stale anchor could otherwise survive into its
        next session and falsely cap the SOC target as already met. Call
        this from inside the per-charger loop, where ``was_connected`` /
        ``self._last_ev_connected`` are already swapped to THIS charger's
        values, so the reset is scoped correctly regardless of which
        charger is primary.
        """
        if not (was_connected and not self._last_ev_connected):
            return
        det = (getattr(self, "_ev_taper_detectors", None) or {}).get(cid)
        if det is not None:
            det.reset_session()
        nm = getattr(self, "_notification_manager", None)
        if nm is not None:
            nm.clear_estimate_flags(flag_key=cid)

    @property
    def _ev_stalled_since(self) -> Optional[float]:
        """#589 Surface-A — this charger's stall timestamp, backed by the
        current PerChargerContext's durable state (``_current_pcc.state``).
        Out-of-loop (no active pcc) falls back to a default. Because the loop's
        context holds the ``_pcc_store[cid]`` object by reference, reads/writes
        mutate the stored per-charger object directly — no snapshot/write-back,
        so this field can't leak between chargers (the #315 class)."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.stalled_since
        return self._ev_stalled_since_default

    @_ev_stalled_since.setter
    def _ev_stalled_since(self, value: Optional[float]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.stalled_since = value
        else:
            self._ev_stalled_since_default = value

    @property
    def _ev_enable_surplus_since(self) -> Optional[float]:
        """#589 Surface-A — enable-delay timer, backed by _current_pcc.state."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.enable_surplus_since
        return self._ev_enable_surplus_since_default

    @_ev_enable_surplus_since.setter
    def _ev_enable_surplus_since(self, value: Optional[float]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.enable_surplus_since = value
        else:
            self._ev_enable_surplus_since_default = value

    @property
    def _ev_charge_started_at(self) -> Optional[float]:
        """#589 Surface-A — disable-delay hold timer, backed by _current_pcc.state."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.charge_started_at
        return self._ev_charge_started_at_default

    @_ev_charge_started_at.setter
    def _ev_charge_started_at(self, value: Optional[float]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.charge_started_at = value
        else:
            self._ev_charge_started_at_default = value

    @property
    def _ev_last_change_time(self) -> Optional[Any]:
        """#589 Surface-A — reactive control timing, backed by _current_pcc.state."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.last_change_time
        return self._ev_last_change_time_default

    @_ev_last_change_time.setter
    def _ev_last_change_time(self, value: Optional[Any]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.last_change_time = value
        else:
            self._ev_last_change_time_default = value

    @property
    def _ev_reenable_attempts(self) -> int:
        """#589 Surface-A — consecutive failed re-enables, backed by _current_pcc.state."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.reenable_attempts
        return self._ev_reenable_attempts_default

    @_ev_reenable_attempts.setter
    def _ev_reenable_attempts(self, value: int) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.reenable_attempts = value
        else:
            self._ev_reenable_attempts_default = value

    @property
    def _ev_charge_refused(self) -> bool:
        """#589 Surface-A — "car full" latch, backed by _current_pcc.state."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.charge_refused
        return self._ev_charge_refused_default

    @_ev_charge_refused.setter
    def _ev_charge_refused(self, value: bool) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.charge_refused = value
        else:
            self._ev_charge_refused_default = value

    @property
    def _ev_last_set_amps_ts(self) -> Optional[float]:
        """#589 Surface-A — solar stability timestamp, backed by _current_pcc.state."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            return pcc.state.last_set_amps_ts
        return self._ev_last_set_amps_ts_default

    @_ev_last_set_amps_ts.setter
    def _ev_last_set_amps_ts(self, value: Optional[float]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None and pcc.state is not None:
            pcc.state.last_set_amps_ts = value
        else:
            self._ev_last_set_amps_ts_default = value

    @property
    def _ev_device(self) -> Optional[Any]:
        """#589 swap retirement — the ACTIVE charger's device.

        Inside the per-charger loop this resolves to ``_current_pcc.ev_dev``
        (so every downstream ``self._ev_device`` read — config lookup,
        adapter resolution, session tracking helpers — sees THIS charger);
        out-of-loop it falls back to the primary device set by
        ``__init__.py`` registration. Replaces the last ``_saved`` swap in
        ``PerChargerContext`` — with no restore left to forget, the
        #284/#315/#318 leak class is structurally closed.

        Writers (registration, discovery, the legacy session-tracking
        loop's manual swap) all run out-of-loop and land on the default
        backing; an in-context write targets the context object and dies
        with it."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None:
            return pcc.ev_dev
        return self._ev_device_default

    @_ev_device.setter
    def _ev_device(self, value: Optional[Any]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None:
            pcc.ev_dev = value
        else:
            self._ev_device_default = value

    @property
    def _cycle_vehicle_soc(self) -> Optional[float]:
        """#589 swap retirement — vehicle SOC for the ACTIVE charger.

        Inside the per-charger loop this resolves to ``_current_pcc.vehicle_soc``
        (seeded from the global value at ``__enter__``, overridden by the loop
        body when the charger has its own ``vehicle_soc_entity``); out-of-loop
        it falls back to the global per-cycle value read from the primary
        ``vehicle_soc_entity``. Replaces the ``_saved_vehicle_soc``
        snapshot/restore in ``PerChargerContext`` — the per-charger override
        dies with the context, so it cannot leak into the next charger."""
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None:
            return pcc.vehicle_soc
        return self._cycle_vehicle_soc_default

    @_cycle_vehicle_soc.setter
    def _cycle_vehicle_soc(self, value: Optional[float]) -> None:
        pcc = getattr(self, "_current_pcc", None)
        if pcc is not None:
            pcc.vehicle_soc = value
        else:
            self._cycle_vehicle_soc_default = value

    def _collect_trace(self, sem_data, power, charging_context) -> None:
        # ``charging_context`` reserved for a future management-layer capture.
        try:
            self._trace.begin(wall_iso=dt_util.now().isoformat())
            trace = self._trace.current()
            self._trace_ev(trace, sem_data, power)
            self._trace_battery(trace, sem_data, power)
            self._trace_loads(trace, sem_data)
            self._trace_heat_pump(trace, sem_data)
            self._trace_perception(trace)
        except Exception as e:  # pragma: no cover - defensive
            _LOGGER.debug("trace capture failed (non-fatal): %s", e)
        finally:
            # commit even if a capture raised — the partial trace + its
            # mismatch streak still count (H1). commit() no-ops if no begin.
            self._trace.commit()

    def _trace_perception(self, trace) -> None:
        """#589 — Perception-layer cross-checks (Layer 0): do the sign-corrected
        readings agree with the energy counters? Reads the observe-only sign
        audits (which already ran in read_power) and files one CrossCheck per
        signal, so a persistent sign/counter contradiction trips
        sem_layer_mismatch — the fault the three control layers cohere straight
        past because they all execute on the same mis-signed input. Read-only;
        never changes a reading or a decision.
        """
        reader = self._sensor_reader
        grid_fault = bool(
            getattr(reader, "_grid_sign_lock_contradiction", False)
            or getattr(reader, "_manual_grid_mismatch", False)
        )
        batt_fault = bool(getattr(reader, "_battery_sign_contradiction", False))
        # #590 — pre_debounced: the CounterCorrelationAudit behind these flags
        # already requires 5 consecutive contradiction votes; the trace health
        # engine must not stack its own >=3-cycle streak on top (one debounce).
        trace.cross_checks["grid_sign"] = CrossCheck(
            signal="grid_sign",
            status=LayerStatus.OK,
            detail="grid sign vs import/export counters",
            data={"agree": (not grid_fault)},
            pre_debounced=True,
        )
        # #647 — name the offending unit. On a multi-battery install "battery
        # sign disagrees" is not actionable; "b2 disagrees" points at one
        # inverter's power sensor.
        batt_bids = list(getattr(reader, "battery_sign_contradiction_bids", []) or [])
        trace.cross_checks["battery_sign"] = CrossCheck(
            signal="battery_sign",
            status=LayerStatus.OK,
            detail="battery sign vs charge/discharge counters",
            data={"agree": (not batt_fault), "batteries": batt_bids},
            pre_debounced=True,
        )
        # #661 — split-pair exclusivity. Judged at the netting site (the last
        # moment both raw sides exist); this only reports what the audits
        # already decided. ``health_check`` used to "check" this on the NETTED
        # readings, where max(0, ±x) had already made a contradiction
        # unrepresentable — so the fault had no way to reach the trace at all.
        pair_audits = dict(getattr(reader, "_split_pair_audits", None) or {})
        pair_faults = sorted(pid for pid, a in pair_audits.items() if a.flagged)
        trace.cross_checks["split_pair_exclusivity"] = CrossCheck(
            signal="split_pair_exclusivity",
            status=LayerStatus.OK,
            detail="split import/export and charge/discharge pairs are exclusive",
            data={"agree": (not pair_faults), "pairs": pair_faults},
            pre_debounced=True,
        )

    def _trace_ev(self, trace, sem_data, power) -> None:
        st = trace.subsystem("ev")
        soc = round(float(getattr(power, "battery_soc", 0.0) or 0.0), 1)
        connected = bool(getattr(power, "ev_connected", False))
        try:
            night = bool(self.time_manager.is_night_mode())
        except Exception:
            night = None
        mgmt = {"soc": soc, "connected": connected, "night": night}
        # #743 — the curtailment probe's last tick, when the feature has
        # ever run. Opt-in, so an install that never enabled it keeps the
        # record it always had.
        curtailment = getattr(self, "_curtailment_last", None)
        if curtailment:
            mgmt["curtailment"] = dict(curtailment)
        st.management = LayerRecord(LayerStatus.OK, "policy inputs", mgmt)

        amps = int(getattr(sem_data, "calculated_current", 0) or 0)
        reason = str(getattr(sem_data, "charging_strategy_reason", "") or "")
        budget = round(float(getattr(sem_data, "available_power", 0.0) or 0.0))
        p_status = LayerStatus.OK if amps > 0 else LayerStatus.IDLE
        st.process = LayerRecord(
            p_status, reason, {"commanded_amps": amps, "budget_w": budget},
        )

        observed = round(float(getattr(power, "ev_power", 0.0) or 0.0))
        # Observer mode (global): SEM decided but does NOT command anything, so
        # there is no command to match against → match is N/A (never a false
        # mismatch). Uses the existing ``observer_mode`` flag.
        if getattr(self, "_observer_mode", False):
            st.integration = LayerRecord(
                LayerStatus.OK, "observer mode — not commanding",
                {"observed_w": observed, "commanded_amps": amps, "match": None},
            )
            return
        # match: we commanded a charge AND the car is plugged, but is it
        # actually drawing? (the flap linchpin). Unknowable (None) when we
        # aren't commanding or the car is disconnected.
        # real phases/voltage (M2 — a 1φ charger's nominal is far lower; a
        # hardcoded 3φ threshold false-mismatches every 1-phase install).
        match = ev_layer_match(
            amps, observed,
            int(self.config.get("ev_phases", 3) or 3),
            int(self.config.get("ev_voltage", 230) or 230),
            connected,
        )
        i_status = LayerStatus.OK if match in (None, True) else LayerStatus.DEGRADED
        st.integration = LayerRecord(
            i_status, f"observed {observed:.0f}W",
            {"observed_w": observed, "commanded_amps": amps, "match": match},
        )

    def _trace_battery(self, trace, sem_data, power) -> None:
        st = trace.subsystem("battery")
        soc = round(float(getattr(power, "battery_soc", 0.0) or 0.0), 1)
        status = getattr(sem_data, "status", None)
        reason = str(getattr(status, "battery_status", "") or "")
        charge_w = round(float(getattr(power, "battery_charge_power", 0.0) or 0.0))
        discharge_w = round(float(getattr(power, "battery_discharge_power", 0.0) or 0.0))
        # (#576) management layer — the battery's role in the ONE priority list,
        # so the trace explains who charges before whom this cycle.
        cr = getattr(self, "_cycle_reclaim", {}) or {}
        bp = cr.get("battery_priority")
        commanded = bool(cr.get("battery_commanded", False))
        prio_soc = float(self.config.get("battery_priority_soc", 30))
        role = battery_list_role(
            battery_priority=bp, battery_commanded=commanded,
            soc=soc, priority_soc=prio_soc, discharge_w=discharge_w,
        )
        st.management = LayerRecord(
            LayerStatus.OK, role,
            {"list_priority": bp, "reserve_soc": prio_soc,
             "reclaim_yielded_w": cr.get("reclaim_w", 0)},
        )
        st.process = LayerRecord(LayerStatus.OK, reason, {"soc": soc})
        # match: an explicit force command must be observed (force_charge →
        # charging, force_discharge → discharging). Normal/idle → None.
        _bd = getattr(self, "_last_battery_decisions", None) or {}
        _intents = {d.get("intent") for d in _bd.values()}
        b_intent = ("force_discharge" if "force_discharge" in _intents
                    else "force_charge" if "force_charge" in _intents else "normal")
        b_match = battery_layer_match(b_intent, charge_w, discharge_w)
        i_status = LayerStatus.OK if b_match in (None, True) else LayerStatus.DEGRADED
        st.integration = LayerRecord(
            i_status, "" if b_match in (None, True) else f"commanded {b_intent}, not observed",
            {"charge_w": charge_w, "discharge_w": discharge_w, "match": b_match},
        )

    def _trace_loads(self, trace, sem_data) -> None:
        sc = getattr(sem_data, "surplus_control", None)
        if sc is None:
            return
        total_dev = int(getattr(sc, "surplus_total_devices", 0) or 0)
        if total_dev == 0:
            return  # no controllable loads registered — nothing to trace
        st = trace.subsystem("loads")
        active = int(getattr(sc, "surplus_active_devices", 0) or 0)
        avail = bool(getattr(sc, "surplus_available", False))
        total_w = round(float(getattr(sc, "surplus_total_w", 0.0) or 0.0))
        dist_w = round(float(getattr(sc, "surplus_distributable_w", 0.0) or 0.0))
        alloc_w = round(float(getattr(sc, "surplus_allocated_w", 0.0) or 0.0))
        st.management = LayerRecord(
            LayerStatus.OK, "surplus policy",
            {"devices": total_dev, "surplus_available": avail},
        )
        p_status = LayerStatus.OK if active > 0 else LayerStatus.IDLE
        # (#576) show the battery-charge power the loads above the battery
        # reclaimed this cycle — the extra pool that let a pump run.
        reclaim_w = int((getattr(self, "_cycle_reclaim", {}) or {}).get("reclaim_w", 0) or 0)
        st.process = LayerRecord(
            p_status, f"{active}/{total_dev} active",
            {"surplus_w": total_w, "distributable_w": dist_w,
             "allocated_w": alloc_w, "reclaim_w": reclaim_w},
        )
        obs_mode = getattr(self, "_observer_mode", False)
        obs = "observer mode — not commanding" if obs_mode else f"{active} device(s) on"
        st.integration = LayerRecord(
            LayerStatus.OK, obs, {"active": active, "allocated_w": alloc_w, "match": None},
        )

        # (#576) per-device detail — "why didn't THIS device run?" answerable,
        # and each device's own commanded-vs-observed match feeds the watchdog.
        # Keyed "load:<name>". Skip the EV / heat pump (own subsystems) and
        # off-and-idle devices (noise). observed_on() reads the relay/mode, NOT
        # power — so a thermostat-satisfied heater (on @ 0 W) is not a fault.
        for did, dev in getattr(self._surplus_controller, "_devices", {}).items():
            if getattr(dev, "is_ev", False) or did == "heat_pump":
                continue
            mode = getattr(getattr(dev, "control_mode", None), "value", "surplus")
            is_active = bool(getattr(dev, "is_active", False))
            if mode == "off" and not is_active:
                continue
            dst = trace.subsystem(f"load:{getattr(dev, 'name', did)}")
            prio = int(getattr(dev, "priority", 0) or 0)
            dst.management = LayerRecord(
                LayerStatus.OK, f"prio {prio} · {mode}", {"priority": prio, "mode": mode},
            )
            try:
                draw = round(float(dev.get_current_consumption() or 0))
            except Exception:
                draw = 0
            pst = LayerStatus.OK if is_active else (
                LayerStatus.BLOCKED if mode == "off" else LayerStatus.IDLE)
            blocked = getattr(dev, "blocked_by_dependency", None)
            pdetail = ("on" if is_active else "mode off" if mode == "off"
                       else f"blocked: needs {blocked}" if blocked else "idle — no surplus / not its turn")
            dst.process = LayerRecord(
                pst, pdetail,
                {"rated_w": round(float(getattr(dev, "rated_power", 0) or 0)),
                 "sem_owned": bool(getattr(dev, "_sem_owned", False))},
            )
            try:
                observed_on = dev.observed_on() if hasattr(dev, "observed_on") else None
            except Exception:
                observed_on = None
            desired_on = is_active and bool(getattr(dev, "_sem_owned", False))
            d_match = None if obs_mode else device_layer_match(desired_on, observed_on)
            ist = LayerStatus.OK if d_match in (None, True) else LayerStatus.DEGRADED
            idetail = ("observer mode — not commanding" if obs_mode
                       else "commanded on, relay off" if d_match is False
                       else f"{'on' if observed_on else 'off'} · {draw}W")
            dst.integration = LayerRecord(
                ist, idetail,
                {"observed_on": observed_on, "draw_w": draw, "match": d_match},
            )

    def _trace_heat_pump(self, trace, sem_data) -> None:
        hp = getattr(sem_data, "heat_pump", None)
        if hp is None or not bool(getattr(hp, "heat_pump_registered", False)):
            return  # no heat pump configured — nothing to trace
        st = trace.subsystem("heat_pump")
        mode = str(getattr(hp, "heat_pump_mode", "normal") or "normal")
        sg = int(getattr(hp, "heat_pump_sg_ready_state", 2) or 2)
        boost = bool(getattr(hp, "heat_pump_solar_boost", False))
        st.management = LayerRecord(LayerStatus.OK, "hp policy", {"registered": True})
        st.process = LayerRecord(LayerStatus.OK, mode, {"solar_boost": boost})
        obs_mode = getattr(self, "_observer_mode", False)
        hp_match = None if obs_mode else heat_pump_layer_match(boost, sg)
        i_status = LayerStatus.OK if hp_match in (None, True) else LayerStatus.DEGRADED
        obs = ("observer mode — not commanding" if obs_mode
               else "boost commanded, relay not set" if hp_match is False
               else f"SG-Ready state {sg}")
        st.integration = LayerRecord(
            i_status, obs, {"sg_ready_state": sg, "match": hp_match},
        )

    def trace_recent(self, n: int = 30):
        """Serialised recent cycle traces for the diagnose service."""
        return self._trace.recent(n)

    def trace_latest_mismatch(self):
        """Most recent layer-boundary fault, if any (health signal)."""
        return self._trace.latest_mismatch()

    def trace_health(self):
        """Debounced health: is a layer-boundary mismatch persistent?"""
        return self._trace.health()

    def _zero_charger_setpoints(self) -> None:
        """Observer mode: command nothing — zero every charger's setpoint.

        ``commanded_current`` is published from each device's
        ``_current_setpoint``; left stale in observer mode, anything acting on
        that sensor (an external current-control bridge, a second SEM instance)
        would keep driving the charger. Zeroing makes SEM publish "not
        commanding" while it observes.

        ``_ev_devices`` is a ``{charger_id: device}`` dict — iterate VALUES, not
        keys. ``list(dict)`` yields the id strings, which have no
        ``_current_setpoint`` and crashed the whole update cycle (#542). The bug
        lay latent because this block never executed until the observer switch
        was un-broken.
        """
        devices = list((self._ev_devices or {}).values())
        if self._ev_device is not None and self._ev_device not in devices:
            devices.append(self._ev_device)
        for dev in devices:
            if dev is not None:
                dev._current_setpoint = 0.0

    def _sync_observer_mode_from_switch(self) -> None:
        """Backstop the observer flag from the switch entity each cycle.

        Only a DEFINITE ``on``/``off`` updates ``_observer_mode``. The switch is
        a CoordinatorEntity whose ``available`` flaps to False on any single
        failed update, so its state transiently reads ``unavailable``/``unknown``.
        Treating that as "not on" would clobber the value the switch pushed
        directly (see switch.py) back to False every cycle — silently
        re-enabling hardware control. So we hold the last known value across
        transient unavailability and only move on a real on/off.
        """
        observer_state = self.hass.states.get(ENTITY_OBSERVER_MODE_SWITCH)
        if observer_state is not None and observer_state.state in ("on", "off"):
            self._observer_mode = observer_state.state == "on"

    def _sync_vacation_mode_from_switch(self) -> None:
        """Backstop the vacation switch flag from the entity each cycle (#594).

        Same contract as ``_sync_observer_mode_from_switch``: only a DEFINITE
        ``on``/``off`` updates the flag — transient unavailable/unknown holds
        the last known value (the switch also pushes directly, see switch.py).
        """
        vac_state = self.hass.states.get(ENTITY_VACATION_MODE_SWITCH)
        if vac_state is not None and vac_state.state in ("on", "off"):
            self._vacation_switch_on = vac_state.state == "on"

    def _compute_vacation_active(self) -> bool:
        """Vacation is active when EITHER source says so (#594).

        1. The optional external ``vacation_mode_entity`` (tunable config
           key, read per cycle): ``binary_sensor.*`` / ``input_boolean.*`` /
           ``switch.*`` are active while ``on``; ``calendar.*`` is ``on``
           exactly while an event is ongoing — same check covers all four.
        2. SEM's own ``switch.sem_vacation_mode``.
        """
        self._sync_vacation_mode_from_switch()
        if self._vacation_switch_on:
            return True
        ext_entity = self.config.get("vacation_mode_entity") or ""
        if ext_entity:
            ext_state = self.hass.states.get(ext_entity)
            if ext_state is not None and ext_state.state == "on":
                return True
        return False

    async def _apply_vacation_mode(self) -> bool:
        """Set the per-cycle vacation flag on the comfort-heating controllers
        and deactivate them cleanly on the vacation transition (#594).

        Runs BEFORE ``SurplusController.update`` so this cycle's activation
        pass already sees the gate. SEM only stops ENCOURAGING: deactivation
        returns the heat pump to SG-Ready NORMAL (never BLOCKED) and the
        boiler to its own thermostat — frost/safety logic is untouched. EV /
        battery / load-priority devices are deliberately not touched.
        """
        was_active = self._vacation_active
        vacation = self._compute_vacation_active()
        self._vacation_active = vacation
        devices = getattr(self._surplus_controller, "_devices", {})
        for dev_id in ("heat_pump", "hot_water"):
            dev = devices.get(dev_id)
            if dev is None:
                continue
            dev.vacation = vacation
            if dev_id == "hot_water":
                dev.vacation_dhw_surplus = bool(
                    self.config.get("vacation_dhw_surplus", False)
                )
            if not vacation or self._observer_mode or not dev.is_active:
                continue
            # The hot-water surplus dump may stay active (it re-targets
            # ``min_temperature`` via ``_active_target_temp``) — but on the
            # rising edge deactivate once so the entity's written setpoint
            # drops from the solar/comfort target to the minimum on the next
            # (gated) activation. Legionella-in-flight is aborted by
            # ``check_legionella_cycle`` itself.
            dump_allowed = (
                dev_id == "hot_water"
                and dev.vacation_dhw_surplus
                and not getattr(dev, "_legionella_cycle_active", False)
            )
            if dump_allowed and was_active:
                continue
            try:
                await dev.deactivate()
                if not dev.is_active:
                    dev.record_deactivated()
                    _LOGGER.info(
                        "Vacation mode: deactivated %s (comfort heating "
                        "suspended while away)", dev.name,
                    )
            except Exception as e:  # noqa: BLE001 — never break the cycle
                _LOGGER.warning(
                    "Vacation deactivation of %s failed: %s", dev_id, e,
                )
        return vacation

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data from sensors and calculate derived values."""
        # Initialize storage on first update
        if self._storage is None and self.config_entry:
            self._storage = SEMStorage(self.hass, self.config_entry.entry_id)
            await self._storage.async_load()
            # Restore energy calculator state
            state = self._storage.export_energy_calculator_state()
            self._energy_calculator.restore_state(state)

            # Restore forecast tracker state
            forecast_state = self._storage.export_forecast_tracker_state()
            self._forecast_tracker.restore_state(forecast_state)

            # Restore consumption predictor state (#3)
            predictor_state = self._storage._daily_data.get("predictor", {})
            self._predictor.restore_state(predictor_state)

            # (#586) Device-runtime restore is deliberately NOT done here.
            # This first-refresh runs before the UnifiedDeviceRegistry is
            # initialised (see __init__.py:async_setup_entry), so no surplus
            # device exists yet and get_device() would find nothing — the
            # accrued "X/Y u op zon vandaag" progress would silently reset to
            # 0 on every restart. __init__ calls _restore_device_runtimes()
            # explicitly once the registry has (re-)registered the devices.

            # Restore EV session state (survives restarts)
            self._restore_ev_session_state()

            # Restore EV intelligence state (#106)
            ev_intel_state = self._storage.get_ev_intelligence_state()
            self._ev_taper_detector.restore_state(ev_intel_state)
            # (#756/P3) …and the whole per-charger fleet, EAGERLY. The
            # detectors used to be created+restored lazily inside the EV
            # cycle block, so the first boot tick computed the demand
            # signature's fullness term from an empty registry and
            # restamped a warm restored plan with "ask changed".
            self._restore_per_charger_detectors(ev_intel_state)

            # (#645) Restore the date the virtual-SOC daily decay last ran.
            # Must happen before the first rollover check, otherwise the
            # coordinator adopts today and the missed day is lost — exactly
            # the restart-spanning-midnight skip this fixes.
            self._restore_last_decay_date()

            # Restore sign-detection locks (#476 item 5) — without this
            # every restart re-learned grid/battery signs from possibly
            # ambiguous low-power samples and could lock the wrong sign
            # until the next reload.
            self._sensor_reader.restore_sign_state(
                self._storage.get_sign_state()
            )

            # (#638 night 2) Restore the measured W/A — in-memory only,
            # every restart reset the energy packer to nameplate until
            # the car's next charge, and a deploy at 23:36 + a re-plan at
            # 23:46 yielded an EV demand the plan should have placed.
            self._restore_ev_wpa(self._storage.get_ev_wpa_state())
            self._restore_energy_plan(
                self._storage.get_energy_plan_state())
            # (#755) The night's outcome record restores beside the plan it
            # measures. A reboot mid-night that kept the plan but lost the
            # actuals would produce a night whose "took N kWh" starts at the
            # reboot — a quietly wrong number in the morning report and, worse,
            # a quietly wrong training sample.
            self._restore_demand_outcomes(
                self._storage.get_demand_outcome_state())

            # (#640) The legionella-timestamp restore MOVED to the hot_water
            # registration site in __init__.py — this first-refresh block runs
            # BEFORE the device exists, so restoring here was a no-op and every
            # restart forced a 65°C disinfection cycle (audit class 14).

            # Restore per-charger daily EV energy. It was in-memory only, so it reset to
            # 0 on every restart while the global daily_ev persisted — desyncing the
            # per-charger daily sensor AND (worse) the per-charger night-charge remaining,
            # which would let a charger re-charge its full target after a restart in a
            # multi-charger setup. Persisting it keeps each charger's start/stop on its
            # own delivered+target.
            pcd = self._storage._daily_data.get("per_charger_daily", {})
            if isinstance(pcd, dict) and isinstance(pcd.get("values"), dict):
                self._daily_ev_per_charger = dict(pcd["values"])
                # Per-charger date is a dict[cid → iso-date] since #280. Legacy
                # stores hold a single string (global sunrise reset) — promote
                # it so every charger inherits the last reset cleanly. First
                # cycle after restore re-evaluates against each charger's own
                # deadline, so any drift self-heals within one update tick.
                raw_date = pcd.get("date")
                if isinstance(raw_date, dict):
                    self._daily_ev_per_charger_date = dict(raw_date)
                elif isinstance(raw_date, str):
                    self._daily_ev_per_charger_date = {
                        cid: raw_date for cid in self._daily_ev_per_charger
                    }
                else:
                    self._daily_ev_per_charger_date = {}

            # Restore daily flow accumulators (#282) — survives HA restart so
            # the new time-integrated flow_*_to_*_energy sensors don't rewind
            # mid-day. The flow_calculator checks the saved date against
            # today's and discards yesterday's snapshot automatically.
            flow_state = self._storage._daily_data.get("flow_accumulator", {})
            if isinstance(flow_state, dict):
                try:
                    self._flow_calculator.restore_flow_accumulator_state(flow_state)
                except (AttributeError, ValueError, TypeError) as e:
                    _LOGGER.debug("Flow accumulator restore skipped: %s", e)

            # Seed EV intelligence from recorder history (improves cold starts
            # and upgrades from older versions without EV intelligence data)
            ev_power_entity = (
                self._sensor_reader.config.ev_power_sensor
                or (self._energy_dashboard_config.ev_power if self._energy_dashboard_config else None)
            )
            # Only seed if the detector doesn't already have good state
            # (anchored SOC with a recent full charge detection)
            needs_seed = ev_power_entity and not (
                self._ev_taper_detector._soc_anchored
                and self._ev_taper_detector._last_full_timestamp
            )
            if needs_seed:
                try:
                    seed_result = await self._ev_taper_detector.async_seed_from_history(
                        self.hass, ev_power_entity, days=60,
                    )
                    if seed_result:
                        if seed_result.get("improved"):
                            self._storage.set_ev_intelligence_state(
                                self._ev_taper_detector.get_state()
                            )
                        # Feed weekday consumption to predictor
                        weekday_totals = seed_result.get("weekday_totals", {})
                        if weekday_totals and hasattr(self, '_predictor') and self._predictor:
                            for dow, avg_kwh in weekday_totals.items():
                                # Only seed if predictor has no data for this weekday
                                existing = self._predictor._ev_profile.predict(dow, 12)
                                if existing is None or existing == 0:
                                    self._predictor._ev_profile.update(dow, 12, avg_kwh)
                                    _LOGGER.info(
                                        "EV predictor seeded from history: weekday %d → %.1f kWh/day",
                                        dow, avg_kwh,
                                    )
                except Exception as e:
                    _LOGGER.debug("EV history seeding skipped: %s", e)

            # Ensure battery discharge limit is restored after restart
            # (protects against stale limit left by previous run)
            from .actuate_battery import restore_discharge_limit_on_startup
            await restore_discharge_limit_on_startup(self.hass, self.config)

        # Run deployment health check once after startup
        if self._initial_update_done and not getattr(self, '_health_checked', False):
            self._health_checked = True
            issues = []
            if not self._ev_device and not self._ev_devices:
                issues.append("No EV charger registered")
            if not self._storage or not self._storage.is_loaded:
                issues.append("Storage not loaded")
            if self.hass.states.get(ENTITY_SOLAR_POWER) is None:
                issues.append("Solar power sensor missing")
            if issues:
                _LOGGER.warning("SEM health check: %s", "; ".join(issues))
            else:
                charger_names = [d.name for d in self._ev_devices.values()] if self._ev_devices else [self._ev_device.name if self._ev_device else "none"]
                _LOGGER.info("SEM health check: all OK (EV chargers: %s)", ", ".join(charger_names))

        # Read observer mode from switch entity (allows runtime toggle).
        # The switch ALSO pushes its state straight onto ``self._observer_mode``
        # (see switch.py) so a toggle takes effect immediately and even if this
        # entity_id ever changes; this per-cycle pull is the backstop.
        self._sync_observer_mode_from_switch()

        # #589 3a (publish isolation) — once the core snapshot is built we
        # alias it here; a failure in the ~550-line analytics/diagnostic
        # enrichment tail then degrades to core data instead of taking the
        # WHOLE coordinator UpdateFailed (every entity on all tabs stale).
        core_result = None
        # #589 — single injected clock for the charge-stability layer so all
        # timer comparisons within one coordinator cycle use the same ``now``.
        # Computed once here and threaded into both filter() call sites via
        # _charge_stability_kwargs(); this also feeds snapshot_timers() in
        # _save_ev_session_state so the persisted elapsed values are coherent
        # with the filter timestamps of the same cycle.
        _now_mono_cycle = time.monotonic()
        try:
            # Per-cycle caches — avoid redundant lookups within one 10s cycle (#52)
            # (#819) Re-apply the chosen source on the PER-CYCLE read —
            # this is the one that actually runs every cycle. Idempotent
            # when unchanged; a real change drops the cached source so
            # this read re-detects, which is what makes the picker apply
            # without reloading the entry.
            self._forecast_reader.set_preferred_source(
                self.config.get("solar_forecast_source"))
            self._cycle_forecast = self._forecast_reader.read_forecast()
            # Cache vehicle SOC (read in both _async_update_data and _determine_charging_strategy)
            _vehicle_soc_entity = self.config.get("vehicle_soc_entity", "")
            self._cycle_vehicle_soc = None
            if _vehicle_soc_entity:
                _soc_state = self.hass.states.get(_vehicle_soc_entity)
                if _soc_state and _soc_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    try:
                        self._cycle_vehicle_soc = float(_soc_state.state)
                    except (ValueError, TypeError):
                        _LOGGER.debug("Vehicle SOC %s not numeric: %r (#259)", _vehicle_soc_entity, _soc_state.state)

            # Cold-start recovery (#274): re-derive Energy Dashboard power sensors
            # if they were unresolved at setup (source integration registered after
            # SEM). Bounded; clears itself once resolved. Runs BEFORE reading so the
            # very next read uses the recovered sensors.
            if self._ed_resolve_pending:
                await self._retry_energy_dashboard_resolution()

            # Step 1: Read power values from sensors
            power = self._sensor_reader.read_power()

            # Self-healing sign inversion: if balance goes negative with real
            # grid activity, the grid sign is wrong — auto-correct by flipping
            if power.grid_power != 0 and power.solar_power > 0:
                flipped = self._check_sign_flip(power)
                if flipped:
                    power = self._sensor_reader.read_power()

            # (#638) One plug answer for the whole cycle. Runs on the
            # cycle's own reading, before any consumer — the state machine,
            # decide(), the plan tick, session tracking, the entities.
            self._confirm_ev_connection(power)

            # Smooth transient one-cycle home-consumption dips to 0 (#237).
            # Under a large load (EV ramp) the source sensors update on slightly
            # different cadences, so the energy balance momentarily clamps home to 0
            # for a single cycle. Hold the last positive value through brief dips.
            self._smooth_home_consumption(power)

            # Official Nord Pool core integration exposes its day-ahead
            # curve only via the get_prices_for_date action (no attribute
            # arrays, core#132856) — fetch it on the event loop before the
            # sync attribute-parsing below. Self-throttled inside the
            # provider; no-op for every other provider.
            _svc_refresh = getattr(
                self._tariff_provider, "async_refresh_service_prices", None,
            )
            if _svc_refresh is not None:
                try:
                    await _svc_refresh()
                except Exception as e:  # noqa: BLE001
                    _LOGGER.debug("Tariff service-price refresh failed: %s", e)

            # Update tariff rates before energy/cost calculation so cost accumulators
            # use the current rate for this cycle (fixes dynamic tariff mid-day bug)
            try:
                _tariff = self._tariff_provider.get_tariff_data()
                self._energy_calculator._import_rate = _tariff.current_import_rate
                self._energy_calculator._export_rate = _tariff.current_export_rate
                if self._tariff_rate_warned:
                    _LOGGER.info("Tariff rate update recovered")
                    self._tariff_rate_warned = False
            except (ValueError, TypeError, AttributeError) as e:
                # Surface once at warning (#259): on failure cost calculations silently
                # keep using stale rates, so users get wrong cost feedback with no signal.
                # Warn on the first failure (and on recovery above); stay quiet otherwise.
                if not self._tariff_rate_warned:
                    _LOGGER.warning("Tariff rate update failed; using previous rates: %s", e)
                    self._tariff_rate_warned = True

            # Step 2a: Compute instantaneous power flows FIRST. v1.7.0
            # reorder — the autarky + cost-savings calculators need the
            # flow-attributed values (``solar_to_home``, ``grid_to_home``
            # etc.) so we can distinguish "grid → home" from "grid →
            # battery". Without this, autarky on HA-PROD was reading 0 %
            # any time the battery had been overnight-grid-charged
            # (raw ``daily_grid_import`` includes the battery-bound
            # slice; the flow attribution doesn't).
            power_flows = self._flow_calculator.calculate_power_flows(power)

            # Step 2b: Calculate energy from power integration. The
            # solar-self-consumed cost-savings accumulator inside
            # ``calculate_energy`` now uses ``power_flows.solar_to_home
            # + solar_to_ev`` directly instead of the legacy
            # subtraction heuristic. See the note inside the function.
            energy = self._energy_calculator.calculate_energy(power, power_flows)

            # Step 2c: Time-integrate the per-cycle flows into daily
            # kWh totals. ``energy_flows.grid_to_home + grid_to_ev``
            # feeds the autarky calculator below.
            energy_flows = self._flow_calculator.integrate_energy_flows(
                power_flows, self.update_interval.total_seconds(),
            )

            # Step 3: Calculate costs and performance. ``performance``
            # gets ``energy_flows`` so autarky uses the
            # flow-attributed grid-to-consumption rather than raw
            # grid_import.
            costs = self._energy_calculator.calculate_costs(energy)
            performance = self._energy_calculator.calculate_performance(
                power, energy, energy_flows,
            )

            # Step 4.4: The energy plan stamp/replan trigger — BEFORE the
            # charging decisions (#638 night 3). The EV chain used to run
            # first, so the cycle in which a car connected was decided
            # against the stale plan: a 10 s `active` blip in observer mode;
            # against real hardware, an enable command taken straight back.
            # The plan's authority begins at the stamp — the stamp must come
            # before the first decision that reads it. Inputs (`power`,
            # `energy`) exist since Step 2; the scheduler's decision it
            # reads is last cycle's either way (the battery pipeline runs
            # later in both orderings).
            self._energy_plan_tick(power, energy)

            # Step 4.5: Update session tracking (before charging decisions)
            # Multi-charger (#112): track sessions for each charger
            if self._ev_devices:
                # Collect per-charger power to proportionally attribute flows (#15)
                charger_powers: Dict[str, float] = {}
                for cid, ev_dev in self._ev_devices.items():
                    # (#643) canonical smoothed per-charger read — the raw
                    # entity blips to 0 mid-charge on UDP-polled chargers.
                    charger_powers[cid] = self._charger_power_w(cid, power, ev_dev)
                total_charger_power = sum(charger_powers.values())

                for cid, ev_dev in self._ev_devices.items():
                    if cid not in self._session_data_per_charger:
                        self._session_data_per_charger[cid] = SessionData()
                    if cid not in self._last_ev_connected_per_charger:
                        self._last_ev_connected_per_charger[cid] = False
                    # #351 M3 — prefer the flow_calculator's native
                    # priority-correct per-charger attribution
                    # (``power_flows.per_charger[cid]``) when populated.
                    # Higher-priority chargers got first claim on solar
                    # there; this re-proportionalisation by power share
                    # would otherwise mix the priority signal back out.
                    # Falls back to the proportional split when
                    # per_charger isn't populated (single-charger or
                    # missing per-charger power data).
                    pc_flows = (power_flows.per_charger or {}).get(cid)
                    if pc_flows is not None:
                        from .types import PowerFlows as _PF
                        charger_flows = _PF(
                            solar_to_ev=pc_flows.solar_to_ev,
                            grid_to_ev=pc_flows.grid_to_ev,
                            battery_to_ev=pc_flows.battery_to_ev,
                            solar_to_home=power_flows.solar_to_home,
                            solar_to_battery=power_flows.solar_to_battery,
                            solar_to_grid=power_flows.solar_to_grid,
                            grid_to_home=power_flows.grid_to_home,
                            grid_to_battery=power_flows.grid_to_battery,
                            battery_to_home=power_flows.battery_to_home,
                        )
                    elif total_charger_power > 0:
                        # Legacy fallback — fraction of fleet (pre-Step 5
                        # behaviour, kept for single-charger installs and
                        # cases where per_charger wasn't populated).
                        frac = charger_powers[cid] / total_charger_power
                        from .types import PowerFlows as _PF
                        charger_flows = _PF(
                            solar_to_ev=power_flows.solar_to_ev * frac,
                            grid_to_ev=power_flows.grid_to_ev * frac,
                            battery_to_ev=power_flows.battery_to_ev * frac,
                            solar_to_home=power_flows.solar_to_home,
                            solar_to_battery=power_flows.solar_to_battery,
                            solar_to_grid=power_flows.solar_to_grid,
                            grid_to_home=power_flows.grid_to_home,
                            grid_to_battery=power_flows.grid_to_battery,
                            battery_to_home=power_flows.battery_to_home,
                        )
                    else:
                        charger_flows = power_flows
                    # Swap context for per-charger session tracking
                    saved_dev, saved_sess, saved_conn = (
                        self._ev_device, self._session_data, self._last_ev_connected
                    )
                    # Per-charger vehicle SOC override (#193)
                    saved_vehicle_soc = self._cycle_vehicle_soc
                    ev_chargers_cfg = self.config.get("ev_chargers", [])
                    charger_cfg = next((c for c in ev_chargers_cfg if c.get("id") == cid), {})
                    per_charger_soc_entity = charger_cfg.get("vehicle_soc_entity", "")
                    if per_charger_soc_entity:
                        soc_state = self.hass.states.get(per_charger_soc_entity)
                        if soc_state and soc_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                            try:
                                self._cycle_vehicle_soc = float(soc_state.state)
                            except (ValueError, TypeError):
                                _LOGGER.debug("Vehicle SOC %s not numeric: %r (#259)", per_charger_soc_entity, soc_state.state)
                    self._ev_device = ev_dev
                    self._session_data = self._session_data_per_charger[cid]
                    self._last_ev_connected = self._last_ev_connected_per_charger[cid]
                    # Per-charger plug/charging state (#193): power.ev_connected is
                    # the OR of all chargers' plug sensors, so without this override
                    # every charger would report connected as soon as ANY car plugs in.
                    saved_ev_connected, saved_ev_charging = power.ev_connected, power.ev_charging
                    pc_chrg_sensor = charger_cfg.get("ev_charging_sensor")
                    # #351 M7 — without this override the session-end check
                    # (which reads ``power.ev_connected``) would see the
                    # fleet-OR and never fire on THIS charger's unplug while
                    # another car remains connected. The map is the reader's
                    # per-charger answer, CONFIRMED for this cycle by
                    # ``_confirm_ev_connection`` (#638) — re-reading the plug
                    # entity here smuggled the raw answer back in behind the
                    # debounce, so a missed UDP poll ended the session.
                    pc_conn_map = getattr(power, "ev_connected_per_charger", None) or {}
                    if cid in pc_conn_map:
                        power.ev_connected = bool(pc_conn_map[cid])
                    if pc_chrg_sensor:
                        pc_state = self.hass.states.get(pc_chrg_sensor)
                        if pc_state and pc_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                            power.ev_charging = pc_state.state == "on"
                    else:
                        # Symmetric fallback for ev_charging (#351 M7).
                        pc_chg_map = getattr(power, "ev_charging_per_charger", None) or {}
                        if cid in pc_chg_map:
                            power.ev_charging = bool(pc_chg_map[cid])
                    was_connected_this_cid = self._last_ev_connected
                    self._update_session_tracking(power, charger_flows)
                    self._reset_per_charger_estimate_state(cid, was_connected_this_cid)
                    # Save back per-charger state
                    self._session_data_per_charger[cid] = self._session_data
                    self._last_ev_connected_per_charger[cid] = self._last_ev_connected
                    # Restore
                    self._ev_device, self._session_data, self._last_ev_connected = (
                        saved_dev, saved_sess, saved_conn
                    )
                    self._cycle_vehicle_soc = saved_vehicle_soc
                    power.ev_connected, power.ev_charging = saved_ev_connected, saved_ev_charging
                # Primary charger session = first charger's session
                primary_id = next(iter(self._ev_devices))
                self._session_data = self._session_data_per_charger.get(
                    primary_id, self._session_data
                )
                self._last_ev_connected = self._last_ev_connected_per_charger.get(
                    primary_id, self._last_ev_connected
                )
            else:
                self._update_session_tracking(power, power_flows)

            # Step 4.5: Battery session tracking
            self._update_battery_session_tracking(power, power_flows)

            # Step 4.6: EV taper detection and intelligence (#106)
            ev_intelligence = self._update_ev_intelligence(power, energy)
            self._last_ev_intelligence = ev_intelligence  # For notifications (#106)

            # (``energy_flows`` was already computed up at step 2c so
            # ``calculate_performance`` could feed the autarky calculator
            # with flow-attributed grid_to_home + grid_to_ev. The
            # legacy step-5 ``integrate_energy_flows`` call here was
            # removed in v1.7.0 to avoid double-integration.)

            # Step 6: Build the charging context. The canonical EV budget
            # is computed inside (#282 unification, Phase B+D) and cached
            # on the coordinator as ``self._cycle_ev_budget`` for the
            # actuator to read on the same cycle. The previous step-6
            # ``calculate_available_power`` + ``calculate_charging_current``
            # bare-variable pair was dead-code after Phase B (their result
            # was passed in and ignored) and has been removed.
            # Step 5.9: VPP grid-event dispatch (#580) — pure decision core +
            # per-cycle overrides. Runs BEFORE the charging context / EV /
            # battery / surplus steps so an active event can veto the EV
            # (charge-mode override), force the battery (per-battery mode
            # override) and shed loads (peak-shed posture) THIS cycle.
            # Wrapped: a VPP fault must never break the coordinator cycle.
            try:
                await self._run_vpp_dispatch(power, energy)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("VPP dispatch error: %s", e, exc_info=True)
                self._vpp_ev_override = None
                self._vpp_battery_override = None
                self._vpp_shed_loads = False

            charging_context = self._build_charging_context(power, energy)
            charging_state = self._state_machine.update_state(charging_context)

            # Step 7.5a: Unified EV control via CurrentControlDevice
            # Evaluate the dual-source phase guard once per cycle before any
            # charger decision can reach an adapter.  The resulting state is
            # cached for every charger and for diagnostics publication.
            from .active_phase_guard import update_active_phase_guard
            if self.config.get("phase_guard_enabled", False):
                phase_guard_snapshot = update_active_phase_guard(self)
                await self._notification_manager.notify_phase_guard_transition(
                    phase_guard_snapshot,
                    enabled=True,
                )

            # Multi-charger (#112): control each charger in priority order
            if not self._ev_device and not self._ev_devices:
                await self._retry_ev_device_with_backoff()

            # Observer mode = read-only: command NOTHING to the chargers. The
            # decide/actuate blocks below are already gated by observer_mode,
            # but the published ``commanded_current`` is derived from each
            # device's ``_current_setpoint`` (sensor at coordinator.py:2230),
            # which would go STALE in observer mode — and anything acting on
            # that sensor (an external current-control bridge automation, a
            # second SEM instance) would keep driving the charger. So zero
            # every setpoint here: SEM then clearly publishes "not commanding"
            # while it observes. (#536 — HA-TEST's keba bridge automation drove
            # the real KEBA via the stale setpoint despite observer mode.)
            if self._observer_mode:
                self._zero_charger_setpoints()

            # (#764) The observer cut is at the WRITE, not here. Everything
            # below — adapters, views, decide(), the plan gate, the peak
            # cascade — runs for real under observer; ``actuate`` is handed
            # ``observer=`` and records what it WOULD command instead of
            # commanding it. Gating the block itself (the pre-#764 shape)
            # meant the executor half of #638 could not be simulated at all:
            # no adapter, no decision, nothing to observe.
            if self._ev_devices:
                # Multi-charger (#112): night targets. There is exactly ONE
                # solar allocator across chargers and it is
                # ``_solar_committed_w_per_cycle`` below — each charger's
                # decision subtracts what higher-priority chargers actually
                # committed. A second priority cascade
                # (``SurplusController.distribute_ev_budget`` →
                # ``pcc.budget_w``) used to run here every solar cycle with
                # its own 60 s / 500 W hysteresis; nothing ever read its
                # output. Deleted in #651 — do not reintroduce a parallel
                # per-charger budget without deleting this one.
                num_chargers = len(self._ev_devices)

                # Night target: use per-charger targets if configured (#193).
                # TARIFF_WAITING_FOR_CHEAP is also a night state (#247) — compute
                # the per-charger targets so a waiting charger can still re-plan.
                self._night_target_per_charger_map = {}
                # Per-charger night plans are rebuilt inside the loop each
                # night cycle; clear first so day cycles (and chargers whose
                # target was reached) don't serve yesterday's stale plan to
                # the per-charger today_plan composer (#464).
                self._night_plan_per_charger = {}
                if num_chargers >= 1 and charging_state in (
                    ChargingState.NIGHT_CHARGING_ACTIVE,
                    ChargingState.TARIFF_WAITING_FOR_CHEAP,
                ):
                    # (#629 slice 1) per-charger night-need computation
                    # extracted to ev_night_targets.build_night_target_map.
                    from .ev_night_targets import build_night_target_map
                    self._night_target_per_charger_map = build_night_target_map(
                        self, energy,
                    )
                    # Backward compat: set the old scalar for single-value reads
                    self._night_target_per_charger = None

                sorted_chargers = sorted(
                    self._ev_devices.items(),
                    key=lambda x: x[1].priority,
                )
                # Shared night peak budget (#274/H1): chargers are sized in
                # priority order against one peak headroom; reset the running
                # commitment before the loop.
                self._night_committed_w = 0.0
                # Step 6: shared solar surplus budget across per-charger loop.
                # Each charger's decide(view) sees solar_committed_w reflecting
                # higher-priority chargers' already-committed surplus, so
                # two solar_only chargers don't each think they can have ALL
                # the surplus.
                self._solar_committed_w_per_cycle = 0.0
                # v1.6.9: per-charger effective states are captured below
                # so the notification dispatch can fire per charger.
                # Reset before the loop so a removed charger's stale
                # state doesn't fire on the next cycle.
                self._effective_states_per_charger = {}
                # Reset the fleet-level commanded-amps tracker so the
                # stall path can tell "SEM isn't asking for charge this
                # cycle" from "SEM asked but EV refused" (see comment on
                # ``_last_commanded_amps_fleet`` in __init__).
                self._last_commanded_amps_fleet = 0
                # Pre-cache the per-charger configs once for the night
                # gate below — inline lookup is the same pattern other
                # branches use here. (#277 Phase B)
                _chargers_by_id = {
                    (c.get("id") or "ev_charger"): c
                    for c in (self.config.get("ev_chargers") or [])
                    if isinstance(c, dict)
                }
                for cid, ev_dev in sorted_chargers:
                    # Per-charger gate (#193): skip chargers whose mode
                    # opts out of night/grid charging. Pre-#277 Phase B
                    # this read ``switch.sem_charger_<cid>_night_charging``
                    # directly; post-B the named mode is authoritative —
                    # ``solar_only`` and ``off`` skip; the other three
                    # modes participate.
                    if charging_state in (
                        ChargingState.NIGHT_CHARGING_ACTIVE,
                        ChargingState.TARIFF_WAITING_FOR_CHEAP,
                    ):
                        per_cfg = _chargers_by_id.get(cid, {})
                        if not self._mode_allows_night_charging(per_cfg):
                            # #740 night sibling: skip means "no night
                            # budget", not "no supervision" — a box that
                            # auto-starts masterless at night must still
                            # be converged to stopped by its reconciler.
                            try:
                                await self._police_opted_out_charger(
                                    cid, ev_dev, per_cfg, power,
                                )
                            except Exception as _pol_exc:  # noqa: BLE001
                                _LOGGER.warning(
                                    "night-gate police failed for %s: %s",
                                    cid, _pol_exc,
                                )
                            continue  # mode opts this charger out of night

                    # v1.6.7: the swap/restore dance that used to live
                    # inline here as ``saved = {...}`` + a final
                    # ``finally`` block is now owned by
                    # ``PerChargerContext``. Everything in this block is
                    # the per-charger computation that was already
                    # specific to this iteration (SOC entity read, Min/Max
                    # remaining, night plan, etc.) — it stays inline for
                    # v1.6.7 and migrates onto the context object in
                    # v1.6.8/v1.6.9.
                    pcc = PerChargerContext.for_charger(
                        self, cid, ev_dev,
                        chargers_by_id=_chargers_by_id,
                        power=power,
                    )
                    with pcc:
                        # Set per-charger night target (#193). The
                        # scalar ``_night_target_per_charger`` is read by
                        # downstream methods that still expect it; the
                        # per-charger map drives the in-loop math.
                        per_charger_target = getattr(
                            self, '_night_target_per_charger_map', {},
                        ).get(cid)
                        if per_charger_target is not None:
                            self._night_target_per_charger = per_charger_target

                        # Per-charger SOC target and surplus limit (#215).
                        # ``_cycle_vehicle_soc`` is a pcc-dispatching
                        # property (#589): this write lands on the active
                        # context and dies with it — the global value is
                        # untouched, nothing to restore.
                        charger_cfg = pcc.charger_cfg
                        per_soc_entity = charger_cfg.get("vehicle_soc_entity", "")
                        if per_soc_entity:
                            soc_st = self.hass.states.get(per_soc_entity)
                            if soc_st and soc_st.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                                try:
                                    self._cycle_vehicle_soc = float(soc_st.state)
                                except (ValueError, TypeError):
                                    _LOGGER.debug("Vehicle SOC %s not numeric: %r (#259)", per_soc_entity, soc_st.state)
                        # Ceiling (Max) gates surplus; floor (Min) drives night top-up (#245).
                        # #351 M9 — capture the per-charger SOC into a
                        # local before the calls so both reads see the
                        # same value. Pre-fix both calls read
                        # ``self._cycle_vehicle_soc`` directly — fine
                        # under the current synchronous path, but a
                        # latent re-entry hazard mirroring the #345
                        # disagreement-class pattern.
                        cycle_soc_local = self._cycle_vehicle_soc
                        per_remaining = self._calculate_remaining_need(
                            energy, cycle_soc_local, charger_cfg, bound="max"
                        )
                        per_remaining_floor = self._calculate_remaining_need(
                            energy, cycle_soc_local, charger_cfg, bound="min"
                        )
                        # Surplus stops at this charger's Max ceiling (default full) (#245)
                        per_target_reached = per_remaining <= 0.1
                        charging_context.soc_limit_active = per_target_reached
                        charging_context.daily_target_reached = per_target_reached
                        charging_context.remaining_ev_energy = per_remaining
                        # #351 H2 — apply the forecast-aware night-target
                        # reduction to THIS charger too (the primary path
                        # does this at the equivalent line in
                        # ``_build_charging_context``). Pre-fix only the
                        # primary charger saw the "tomorrow is sunny → skip
                        # tonight" reduction; secondary chargers in
                        # min_plus_solar / solar_plus_cheap mode then
                        # night-charged unconditionally.
                        per_night_floor = per_remaining_floor
                        if (
                            self.time_manager.is_night_mode()
                            and self._mode_uses_smart_night(charger_cfg)
                        ):
                            per_night_floor = self._calculate_forecast_night_target(
                                per_remaining_floor, energy, charger_cfg,
                            )
                        charging_context.night_target_kwh = (
                            per_charger_target
                            if per_charger_target is not None
                            else per_night_floor
                        )

                        # Per-charger deadline + tariff plan (#246/#247): recompute
                        # for THIS charger and pick its effective night state. Each car
                        # can have its own deadline / tariff toggle, so the displayed
                        # (primary) state isn't authoritative for the rest.
                        effective_state = charging_state
                        charging_context.night_deadline_amps = 0
                        charging_context.night_deadline_active = False
                        charging_context.night_tariff_wait = False
                        charging_context.night_deadline_reachable = True
                        # (#638) Reset with the rest of the night inputs, not
                        # inside the branch below: ``decide()`` reads it at the
                        # bottom of every iteration, and a plan left over from
                        # a previous cycle would hold a charger the planner is
                        # no longer speaking about.
                        plan = None

                        # Per-charger off-mode override (v1.6.3 hotfix follow-up).
                        # The global ``charging_state`` is derived from the primary
                        # charger only — the multi-charger loop needs to correct it
                        # per charger so an OFF primary doesn't bleed its terminate
                        # into the other chargers. See the helper for details.
                        # (#629 slice 4) mode resolution + mismatch diagnostic
                        # extracted to ev_night_targets.resolve_per_charger_mode.
                        from .ev_night_targets import resolve_per_charger_mode
                        per_mode = resolve_per_charger_mode(self, cid, charger_cfg)
                        effective_state = self._apply_per_charger_off_override(
                            charging_state, per_mode
                        )
                        if charging_state in (
                            ChargingState.NIGHT_CHARGING_ACTIVE,
                            ChargingState.TARIFF_WAITING_FOR_CHEAP,
                        ):
                            pc_target = charging_context.night_target_kwh
                            if pc_target > 0.1:
                                plan = self._compute_night_plan(charger_cfg, pc_target, energy)
                                # (#638 G4) the joint energy plan's overlay,
                                # written onto the SAME NightChargePlan the
                                # private planner produced so every downstream
                                # consumer (context fields, the tri-state
                                # resolve, decide()) sees one consistent
                                # decision. UNCOVERED → both signals are
                                # no-ops and the plan is untouched. The
                                # reactive guarantees stay senior: a forcing
                                # deadline or an unreachable floor is never
                                # gated (see ev_overlay).
                                try:
                                    from .energy_plan_actuation import ev_overlay
                                    _gate = self._energy_plan_gate(f"ev:{cid}")
                                    # Same measured W/A the demand was packed
                                    # with — floor amps derived from the same
                                    # power model the plan promised.
                                    _wpa = self._ev_watts_per_amp(
                                        cid, charger_cfg, power)
                                    _wait, _floor = ev_overlay(
                                        _gate,
                                        remaining_kwh=pc_target,
                                        reachable=plan.reachable,
                                        deadline_active=plan.deadline_active,
                                        watts_per_amp=_wpa,
                                        min_amps=int(charger_cfg.get("ev_min_current") or 6),
                                        max_amps=int(charger_cfg.get("ev_max_current")
                                                       or DEFAULT_MAX_CHARGING_CURRENT),
                                    )
                                    if _wait:
                                        plan.should_wait_for_cheap = True
                                        plan.next_cheap_start = _gate.next_block_start
                                        plan.reason = (
                                            "joint energy plan: outside the "
                                            "planned window — waiting "
                                            f"({_gate.remaining_kwh:.1f} kWh "
                                            f"still deliverable)")
                                    elif _floor > 0:
                                        plan.should_wait_for_cheap = False
                                        plan.deadline_amps = max(
                                            plan.deadline_amps, _floor)
                                        plan.reason = (
                                            "joint energy plan: in planned "
                                            f"window — floor {_floor}A")
                                except Exception:  # noqa: BLE001 — overlay must
                                    # never break the night path; UNCOVERED-by-
                                    # crash equals "no plan", the safe direction.
                                    _LOGGER.debug(
                                        "#638 G4 EV overlay skipped",
                                        exc_info=True)
                                self._night_plan_per_charger[cid] = plan
                                charging_context.night_deadline_amps = plan.deadline_amps
                                charging_context.night_top_up_amps = plan.top_up_amps
                                charging_context.night_deadline_active = plan.deadline_active
                                charging_context.night_tariff_wait = plan.should_wait_for_cheap
                                charging_context.night_deadline_reachable = plan.reachable
                                await self._maybe_warn_unreachable_deadline(cid, charger_cfg, plan)
                            # (#629 slice 3) the tri-state resolution is pure —
                            # see ev_night_targets.resolve_night_effective_state.
                            from .ev_night_targets import resolve_night_effective_state
                            effective_state = resolve_night_effective_state(
                                effective_state, charging_state, pc_target, plan,
                                ChargingState.NIGHT_CHARGING_ACTIVE,
                                ChargingState.TARIFF_WAITING_FOR_CHEAP,
                                ChargingState.NIGHT_TARGET_REACHED,
                            )

                        # #526: surface (as a repair) when an SOC-% cap can't be
                        # enforced because no real vehicle SOC is readable.
                        self._maybe_warn_soc_cap(cid, charger_cfg, cycle_soc_local, effective_state)

                        # v1.6.14: write the effective state to ``pcc``;
                        # ``__exit__`` persists it into
                        # ``self._effective_states_per_charger`` so the
                        # post-loop ``_send_notifications`` dispatch sees
                        # the per-charger state. Writing through pcc
                        # makes the AST lint enforceable: no callsite
                        # outside the loop touches the parallel dict
                        # directly.
                        pcc.effective_state = effective_state

                        # ─── arch/multi-charger-primary: the new pipeline IS the actuator ───
                        # Build ChargerView → decide(view) → actuate(decision, adapter).
                        # The legacy _execute_ev_control is no longer authoritative
                        # for the per-charger loop. Every per-charger decision and
                        # command flows through this single pipeline.
                        #
                        # The structural payoff: the strategy/state-machine
                        # disagreement class (#346) cannot exist by construction —
                        # decide() is the only place a per-charger decision is made.
                        # Brand quirks (KEBA's 6A min, self-resume — #315/#346/#353)
                        # live entirely in ChargerAdapter, not in the actuator.
                        from .actuate import actuate
                        from .build_view import build_charger_view
                        from .charger_adapters import adapter_for
                        from .decide import decide as decide_v2

                        # Per-cycle adapter cache: KebaAdapter holds last_intent
                        # state used by is_self_charging(); recreating it each
                        # cycle would lose the self-resume detection. Stored on
                        # the coordinator keyed by charger_id.
                        adapter_cache = getattr(self, "_charger_adapters", None)
                        if adapter_cache is None:
                            adapter_cache = {}
                            self._charger_adapters = adapter_cache
                        adapter = adapter_cache.get(cid)
                        if adapter is None or adapter._device is not ev_dev:
                            adapter = adapter_for(ev_dev)
                            adapter_cache[cid] = adapter

                        # Per-charger reconciler (#392): owns convergence (idempotent idle/off,
                        # drift correction, failsafe heartbeat). Cached for the charger's life
                        # like the adapter — it holds transition state.
                        rec_cache = getattr(self, "_charger_reconcilers", None)
                        if rec_cache is None:
                            rec_cache = {}
                            self._charger_reconcilers = rec_cache
                        reconciler = rec_cache.get(cid)
                        if reconciler is None:
                            from .charger_reconciler import (
                                DEFAULT_IDLE_DISABLE_THRESHOLD,
                                ChargerReconciler,
                            )
                            reconciler = ChargerReconciler(
                                charger_id=cid,
                                heartbeat_s=float(getattr(ev_dev, "watchdog_refresh_interval_s", 5.0)),
                                idle_disable_threshold=DEFAULT_IDLE_DISABLE_THRESHOLD,
                            )
                            rec_cache[cid] = reconciler

                        # PR A — pass the same resolved per-charger target that
                        # the legacy state machine path above used
                        # (charging_context.night_target_kwh, lines 1287, 1323).
                        # Pre-fix this passed per_remaining_floor which can
                        # differ from per_charger_target, causing decide() to
                        # see 0.6 kWh remaining while the state machine path
                        # saw 0.05 — the resulting "Night mode - Target reached"
                        # sensor display vs CHARGE_AT_AMPS intent mismatch
                        # observed live on PROD 2026-06-01.
                        decide_target_kwh = (
                            charging_context.night_target_kwh
                            if charging_context.night_target_kwh is not None
                            else per_remaining_floor
                        )
                        view = build_charger_view(
                            self._cycle_fleet_state,
                            charger_id=cid,
                            # #576 — this charger's slot in the one list (drag
                            # override wins immediately via the priority store).
                            ev_priority=self._ev_priority_for(cid),
                            charger_cfg=charger_cfg,
                            mode=per_mode,
                            daily_ev_kwh=self._charger_daily_kwh(cid, energy),
                            target_kwh=decide_target_kwh,
                            deadline_amps=int(charging_context.night_deadline_amps or 0),
                            top_up_amps=int(getattr(charging_context, "night_top_up_amps", 0) or 0),
                            # (#638) The planning layer's verdict, as a typed
                            # field. Its predecessor rode along in
                            # ``charger_cfg`` as ``_tariff_wait``, where two of
                            # the three night modes never saw it — and on
                            # 2026-08-06 this charger finished half an hour
                            # before its own planned window opened.
                            plan=verdict_from_night_plan(plan),
                            # #678 — the ceiling the adapter will clamp to.
                            # Without it decide reads ``ev_max_current`` off a
                            # per-charger dict that never carries the key and
                            # falls back to 32 A, over-crediting the cascade.
                            hardware_max_a=getattr(adapter, "max_current_a", None),
                            solar_committed_w=self._solar_committed_w_per_cycle,
                            night_deliverable_kwh=self._night_deliverable_kwh(charger_cfg),
                            # #548 — max-SOC ceiling (bound="max"); stops surplus
                            # charging at the car's max SOC, in every mode.
                            soc_ceiling_reached=per_target_reached,
                        )
                        decision = decide_v2(view)
                        # Hysteresis stability layer (#461 flapping):
                        # median smoothing + ramp limit + delta/debounce
                        # guards + enable/disable delays. Applied BEFORE
                        # state display + actuation so the sensor state,
                        # strategy string and contactor all agree on the
                        # held decision.
                        decision = self._charge_stability.filter(
                            decision, view, adapter,
                            **self._charge_stability_kwargs(),
                            now_ts=_now_mono_cycle,
                        )
                        # Safety write gate is deliberately LAST: stability
                        # logic must never bridge or ramp around an emergency
                        # phase-guard stop.
                        from .active_phase_guard import filter_charger_decision
                        decision = filter_charger_decision(
                            self, decision, adapter=adapter, power=view.power,
                            # (#804 B4d) the live phase belief — a 3→1
                            # switch tightens the per-phase clamp at once.
                            believed_phases=getattr(
                                self, "_phase_believed", {}).get(cid),
                        )
                        # (#804 Phase B/C) The phase sequencer may hold the
                        # decision at IDLE while a switch walks its
                        # stop→switch→settle sequence. AFTER the safety gate
                        # on purpose: the tick only ever weakens a CHARGE
                        # into IDLE and passes emergency stops untouched.
                        decision = await self._phase_switch_tick(
                            cid, charger_cfg, decision, view.power,
                            _now_mono_cycle,
                            setpoint_a=int(float(getattr(
                                getattr(adapter, "_device", None),
                                "_current_setpoint", 0) or 0)),
                        )
                        # Track the highest commanded current across the
                        # fleet so the stall-detection path (line ~3725)
                        # can distinguish "SEM idle, EV at 0W is correct"
                        # from "SEM commanding, EV refused → really full".
                        if decision.commanded_amps > self._last_commanded_amps_fleet:
                            self._last_commanded_amps_fleet = decision.commanded_amps
                        # (#762) transition-gated — 833 identical idle
                        # lines per day on .175.
                        log_on_change(
                            _LOGGER, f"decide_ev:{cid}", logging.DEBUG,
                            "decide %s mode=%s → intent=%s amps=%d budget=%.0fW :: %s",
                            cid, per_mode, decision.intent.value,
                            decision.commanded_amps, decision.budget_w, decision.reason,
                        )
                        # Fleet-level strategy display: only the PRIMARY
                        # charger may write it, and it writes BOTH fields.
                        # Pre-fix every loop iteration overwrote
                        # ``charging_strategy`` (last charger won) while
                        # ``charging_strategy_reason`` kept the primary's
                        # value — RienduPre's dump showed strategy from
                        # charger 2 ("always_max …") next to reason from
                        # charger 1 ("off mode …"). Per-charger detail
                        # lives in ``charger_<id>_charging_state``.
                        _fleet_primary_cid = self.primary_charger_id()
                        if cid == _fleet_primary_cid:
                            charging_context.charging_strategy = decision.reason
                            charging_context.charging_strategy_reason = decision.reason
                        # Reflect decision into the effective_state sensor
                        # (for dashboards that read sem_charging_state).
                        #
                        # PR A — preserve night-specific states set above.
                        # The pre-decide block at lines 1316-1338 already
                        # computed the correct effective_state for night
                        # operation (NIGHT_TARGET_REACHED /
                        # TARIFF_WAITING_FOR_CHEAP / NIGHT_CHARGING_ACTIVE).
                        # Only overwrite when the global charging_state is a
                        # solar / non-night state — otherwise the night state
                        # wins. Pre-fix the intent-derived state unconditionally
                        # clobbered NIGHT_TARGET_REACHED with
                        # SOLAR_CHARGING_ACTIVE.
                        _NIGHT_STATES = (
                            ChargingState.NIGHT_CHARGING_ACTIVE,
                            ChargingState.TARIFF_WAITING_FOR_CHEAP,
                            ChargingState.NIGHT_TARGET_REACHED,
                            ChargingState.NIGHT_IDLE,
                            ChargingState.NIGHT_DISABLED,
                            ChargingState.NIGHT_TIME_EXPIRED,
                            ChargingState.NIGHT_WAITING_FOR_WINDOW,
                        )
                        if effective_state not in _NIGHT_STATES:
                            from .charger_types import ChargerIntent as _CI
                            if decision.intent is _CI.DISABLE:
                                effective_state = ChargingState.SOLAR_IDLE
                            elif decision.intent is _CI.IDLE:
                                # #548 — an IDLE caused by the max-SOC ceiling
                                # reads as "Target reached", not a bare "Idle".
                                effective_state = (
                                    ChargingState.SOLAR_TARGET_REACHED
                                    if getattr(view, "soc_ceiling_reached", False)
                                    else ChargingState.SOLAR_IDLE
                                )
                            elif decision.intent is _CI.CHARGE_MAX:
                                effective_state = ChargingState.SOLAR_SUPER_CHARGING
                            else:
                                effective_state = ChargingState.SOLAR_CHARGING_ACTIVE
                            # Cosmetic: if we're commanding a charge but the car
                            # isn't actually drawing past a ramp-up grace, show
                            # "ready" not "charging" so a satisfied/full car
                            # doesn't read as Charging at 0 W. Power-based — the
                            # SoC estimate is unreliable, so it's display-only and
                            # never changes the command.
                            _no_draw = getattr(self, "_charge_no_draw_since", None)
                            if _no_draw is None:
                                _no_draw = {}
                                self._charge_no_draw_since = _no_draw
                            if decision.intent in (_CI.CHARGE_AT_AMPS, _CI.CHARGE_MAX):
                                import time as _t
                                _hs = float(getattr(adapter, "handshake_power_w", 500.0))
                                _drawing = float(getattr(view.power, "power_w", 0.0) or 0.0) > _hs
                                if _drawing:
                                    _no_draw.pop(cid, None)
                                else:
                                    _since = _no_draw.setdefault(cid, _t.monotonic())
                                    from .decide import solar_charge_display_override
                                    _ov = solar_charge_display_override(
                                        decision.intent, _drawing, _t.monotonic() - _since)
                                    if _ov is not None:
                                        effective_state = _ov
                            else:
                                _no_draw.pop(cid, None)
                        pcc.effective_state = effective_state

                        try:
                            await actuate(
                                decision, adapter, view.power,
                                reconciler=reconciler,
                                observer=self._observer_mode,
                                controller=self._surplus_controller,
                            )
                            # Add this charger's just-committed draw to the shared night
                            # peak budget so lower-priority chargers size against the
                            # remaining headroom (#274/H1). Estimate from the setpoint
                            # (the commitment), not the lagging measured power.
                            try:
                                if self._observer_mode:
                                    # (#764) Nothing writes a setpoint under
                                    # observer — they're zeroed above (#536) —
                                    # so read the commitment off the decision
                                    # the actuator WOULD have applied. Without
                                    # this the junior charger sees phantom
                                    # headroom and a fleet simulation is fiction.
                                    from .charger_types import commanded_power_w
                                    self._night_committed_w += commanded_power_w(
                                        decision,
                                        phases=adapter.phases,
                                        voltage=adapter.voltage,
                                        max_current_a=adapter.max_current_a,
                                    )
                                else:
                                    self._night_committed_w += max(0.0, (
                                        ev_dev._current_setpoint * ev_dev.phases * ev_dev.voltage
                                    ))
                            except (AttributeError, TypeError):
                                pass
                            # Step 6: thread solar commitment through to the next
                            # per-charger view so lower-priority chargers see only
                            # the surplus this one didn't take.
                            #
                            # The arithmetic lives in ``solar_commitment_w``
                            # (#665) so the scenario harness runs the SAME
                            # function rather than a test-side copy that can
                            # drift. Keep this a call, not an inline formula —
                            # tests/test_665_allocator_coverage.py fails CI if
                            # the reset or this call disappears.
                            from .charger_types import solar_commitment_w
                            self._solar_committed_w_per_cycle += solar_commitment_w(
                                decision,
                                phases=adapter.phases,
                                voltage=adapter.voltage,
                                max_current_a=adapter.max_current_a,
                            )
                        except (HomeAssistantError, ServiceValidationError) as e:
                            _LOGGER.error("EV control service failed for %s: %s", cid, e)
                        except ValueError as e:
                            _LOGGER.warning("EV control invalid value for %s: %s", cid, e)
                self._save_ev_session_state()
            elif self._ev_device:
                # Single-charger legacy path — also flipped to the new pipeline.
                # Build a synthetic per-charger view from the global config.
                from .actuate import actuate
                from .build_view import build_charger_view
                from .charger_adapters import adapter_for
                from .decide import decide as decide_v2

                cid = getattr(self._ev_device, "device_id", "ev_charger") or "ev_charger"
                adapter_cache = getattr(self, "_charger_adapters", None)
                if adapter_cache is None:
                    adapter_cache = {}
                    self._charger_adapters = adapter_cache
                adapter = adapter_cache.get(cid)
                if adapter is None or adapter._device is not self._ev_device:
                    adapter = adapter_for(self._ev_device)
                    adapter_cache[cid] = adapter

                # Per-charger reconciler (#392): same cache as the multi-charger path.
                rec_cache = getattr(self, "_charger_reconcilers", None)
                if rec_cache is None:
                    rec_cache = {}
                    self._charger_reconcilers = rec_cache
                reconciler = rec_cache.get(cid)
                if reconciler is None:
                    from .charger_reconciler import (
                        DEFAULT_IDLE_DISABLE_THRESHOLD,
                        ChargerReconciler,
                    )
                    reconciler = ChargerReconciler(
                        charger_id=cid,
                        heartbeat_s=float(getattr(self._ev_device, "watchdog_refresh_interval_s", 5.0)),
                        idle_disable_threshold=DEFAULT_IDLE_DISABLE_THRESHOLD,
                    )
                    rec_cache[cid] = reconciler

                # Resolve mode from global config (no per-charger cfg in this branch).
                per_mode = self._effective_charge_mode_for(
                    self._primary_charger_cfg()
                )
                view = build_charger_view(
                    self._cycle_fleet_state,
                    charger_id=cid,
                    # #576 — this charger's slot in the one priority list.
                    ev_priority=self._ev_priority_for(cid),
                    charger_cfg={},
                    mode=per_mode,
                    daily_ev_kwh=getattr(energy, "daily_ev", 0.0),
                    target_kwh=getattr(charging_context, "night_target_kwh", None),
                    deadline_amps=int(getattr(charging_context, "night_deadline_amps", 0) or 0),
                    top_up_amps=int(getattr(charging_context, "night_top_up_amps", 0) or 0),
                    # (#638) This legacy single-charger branch drives the
                    # PRIMARY charger, whose plan ``_build_charging_context``
                    # already computed and parked on ``_cycle_night_plan``
                    # earlier this cycle — so it reads the same object the
                    # multi-charger loop does, through the same factory, and
                    # the planner's own words survive to the published reason.
                    # Reading ``night_tariff_wait`` off the context instead
                    # would carry the bit but drop the sentence.
                    plan=verdict_from_night_plan(self._cycle_night_plan),
                    night_deliverable_kwh=self._night_deliverable_kwh(
                        self._primary_charger_cfg()
                    ),
                    # #548 — max-SOC ceiling; stop surplus charging at the car's max.
                    soc_ceiling_reached=bool(
                        getattr(charging_context, "soc_limit_active", False)
                    ),
                )
                decision = decide_v2(view)
                # Hysteresis stability layer (#461 flapping) — the
                # single-charger legacy branch needs the same protection.
                decision = self._charge_stability.filter(
                    decision, view, adapter,
                    **self._charge_stability_kwargs(),
                    now_ts=_now_mono_cycle,
                )
                from .active_phase_guard import filter_charger_decision
                decision = filter_charger_decision(
                    self, decision, adapter=adapter, power=view.power,
                    # (#804 B4d) the legacy single-charger path never runs
                    # phase switching, so the belief is always absent here —
                    # passed for one uniform call shape, resolves to the
                    # nameplate fallback.
                    believed_phases=getattr(
                        self, "_phase_believed", {}).get("ev_charger"),
                )
                try:
                    await actuate(
                        decision, adapter, view.power, reconciler=reconciler,
                        observer=self._observer_mode,
                        controller=self._surplus_controller,
                    )
                    self._save_ev_session_state()
                except (HomeAssistantError, ServiceValidationError) as e:
                    _LOGGER.error("EV control service failed: %s", e)
                except ValueError as e:
                    _LOGGER.warning("EV control invalid value: %s", e)

            # Step 7.5c+d (unified): Battery control via decide_battery + actuate_battery
            #
            # Replaces the legacy split (7.5c the deleted BatteryProtectionMixin, #624, +
            # 7.5d BatteryChargeScheduler.update) with one pure pipeline
            # mirroring the EV-side rebuild.
            # (#638 night 3) The plan trigger moved ABOVE this block — see
            # _energy_plan_tick, called before the EV session/decision
            # chain: the stamp must precede the first decision that reads it.

            # (#764) Runs under observer too — the cut is inside
            # ``actuate_battery``. Pre-#764 this whole pipeline was skipped,
            # so a two-battery rig reported ``adapters = {}`` /
            # ``last_decisions = {}`` in diagnostics and no battery decision
            # could ever be simulated.
            discharge_limit = None
            try:
                await self._run_battery_pipeline(power, energy, charging_state)
                # (#625 phase 4) Surface the tightest ACTIVE
                # LIMIT_DISCHARGE for the sensor (#375) — extracted
                # to actuate_battery.active_discharge_limit.
                from .actuate_battery import active_discharge_limit
                discharge_limit = active_discharge_limit(
                    getattr(self, "_battery_adapters", None))
            except (HomeAssistantError, ServiceValidationError) as e:
                _LOGGER.error("Battery pipeline service failed: %s", e)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Battery pipeline error: %s", e, exc_info=True,
                )

            # Step 7.5b: Load management (peak tracking + device shedding, no EV)
            if self._load_manager:
                self._load_manager._observer_mode = self._observer_mode
                try:
                    lm_info = self._load_manager.get_load_management_data()
                    current_peak = lm_info.get("consecutive_peak_15min", 0)
                    monthly_peak = lm_info.get("monthly_consecutive_peak", 0)

                    await self._load_manager.process_peak_update(
                        current_peak,
                        monthly_peak,
                        ev_is_charging=False,
                        grid_import_w=power.grid_import_power,
                        # FLEET-READ: load manager peak budget is a
                        # whole-house concept; fleet EV total is correct.
                        ev_power_w=power.ev_power,
                    )
                except (HomeAssistantError, ServiceValidationError) as e:
                    _LOGGER.error("Load management service call failed: %s", e)
                except (ValueError, KeyError) as e:
                    _LOGGER.warning("Load management data error: %s", e)

            # Step 8: Update system status
            status = self._build_system_status(power, charging_state)

            # Step 9: Get load management data
            load_management = self._build_load_management_data(power)

            # Step 9a: Seed lifetime accumulators from hardware (runs once)
            if self._energy_dashboard_config and not self._energy_calculator._lifetime_seeded:
                self._energy_calculator.seed_lifetime_from_hardware(
                    self.hass, self._energy_dashboard_config
                )

            # Step 9a2: Detect system install date from statistics (runs once)
            if self._energy_calculator._install_year_decimal is None:
                try:
                    await self._energy_calculator.async_detect_install_date(self.hass)
                except Exception as e:
                    _LOGGER.debug("Install date detection skipped: %s", e)

            # Step 9b: Seed yearly accumulators from recorder statistics (runs once)
            # Also fire when only the COST backfill is outstanding (energy already
            # seeded on an older install) — the method no-ops the energy seed but
            # backfills the yearly cost so it stops equalling the monthly cost.
            # (#794) Gate on the property, not the two seed flags: both are
            # persisted, so an install carrying a bad seed restores them True
            # and would never call in again — the floor re-check that heals it
            # would be unreachable on exactly the system that needs it.
            if (
                self._energy_dashboard_config
                and self._energy_calculator.yearly_seed_pending
            ):
                try:
                    await self._energy_calculator.seed_yearly_from_statistics(
                        self.hass, self._energy_dashboard_config
                    )
                except Exception as e:
                    _LOGGER.warning("Yearly seeding from statistics failed (will retry): %s", e)

            # Step 9c: Calculate battery health metrics. #593 — a configured
            # HARDWARE lifetime-cycle sensor is preferred over the throughput
            # estimate (which only counts what SEM has seen since install and
            # can't match the manufacturer's counter, e.g. Sonnenbatterie 249 vs
            # SEM 165). Resolution + parse extracted to a pure helper for test.
            battery_capacity = self.battery_capacity_kwh
            hw_state = None
            # #593 — resolution order: manual override → autodetected cycle
            # sensor on the battery device (Sonnen/Huawei get it free) →
            # throughput estimate below. Manual wins; autodetect is primary.
            cycles_sensor = self.config.get("battery_cycles_sensor")
            if not cycles_sensor:
                _ed = self._energy_dashboard_config
                _anchor = (
                    self.config.get("battery_power_sensor")
                    or (getattr(_ed, "battery_power", None) if _ed else None)
                    or (getattr(_ed, "battery_soc", None) if _ed else None)
                )
                cycles_sensor = self._sensor_reader.detect_battery_cycles_sensor(_anchor)
            if cycles_sensor:
                _st = self.hass.states.get(cycles_sensor)
                hw_state = _st.state if _st is not None else None
            throughput_cycles = None
            if battery_capacity > 0:
                lifetime_charge = self._energy_calculator._get_lifetime("battery_charge")
                lifetime_discharge = self._energy_calculator._get_lifetime("battery_discharge")
                throughput_cycles = round(
                    (lifetime_charge + lifetime_discharge) / 2 / battery_capacity, 1
                )
            cycles, health = self._resolve_battery_cycles(hw_state, throughput_cycles)
            if cycles is not None:
                power.battery_cycles_estimated = cycles
                power.battery_health_score = health

            # Steps 10–10.5: Analytics phases (extracted for readability, #29)
            forecast_data, tracker_data, tariff_data, surplus_data, \
                pv_data, assistant_data, heat_pump_data, \
                hot_water_data = \
                await self._update_analytics_phases(
                    power, energy, energy_flows, performance,
                    charging_context.available_power,
                )

            # (#764) Every family has now had its say — chargers (step 7),
            # batteries (7.5), loads (inside the analytics phases). Sweep the
            # WOULD surface so it describes THIS cycle: a device that stopped
            # deciding leaves the map instead of lingering as a ghost row.
            if self._observer_mode and self._surplus_controller:
                self._surplus_controller.retire_unpublished_observer_decisions()

            # #596: reconcile the published fleet ``charging_state`` with the
            # per-charger effective state for single-charger installs (see
            # _resolve_fleet_charging_state).
            charging_state = self._resolve_fleet_charging_state(
                charging_state,
                getattr(self, "_effective_states_per_charger", None) or {},
            )

            # Step 11: Build complete data structure
            sem_data = SEMData(
                power=power,
                power_flows=power_flows,
                energy=energy,
                energy_flows=energy_flows,
                costs=costs,
                performance=performance,
                status=status,
                load_management=load_management,
                charging_state=charging_state,
                charging_strategy=charging_context.charging_strategy,
                charging_strategy_reason=charging_context.charging_strategy_reason,
                # Publish canonical budget (#282 unification, Phase B).
                # The state machine and the actuator now read from the
                # same EVBudget instance; publishing from it as well
                # ensures the dashboard shows what those two see, not a
                # third lower number from calculate_available_power.
                available_power=charging_context.available_power,
                calculated_current=charging_context.calculated_current,
                # (#657) The EV "why am I blocked" flags + budget internals.
                # Computed in _build_charging_context every cycle; the hop
                # onto coordinator.data was missing, so the attributes on
                # sem_ev_charging_status / sem_available_power were null.
                battery_too_low=charging_context.battery_too_low,
                battery_needs_priority=charging_context.battery_needs_priority,
                solar_sufficient=charging_context.solar_sufficient,
                excess_solar=charging_context.excess_solar,
                # The SOC-graduated battery allowance the canonical EVBudget
                # actually granted (0 below the buffer SOC or below the solar
                # gate) — i.e. how much the car may take from the battery now.
                safe_discharge_power=float(
                    getattr(self._cycle_ev_budget, "battery_assist", 0.0) or 0.0
                ),
                surplus_control=surplus_data,
                forecast=forecast_data,
                tariff=tariff_data,
                heat_pump=heat_pump_data,
                hot_water=hot_water_data,
                pv_analytics=pv_data,
                energy_assistant=assistant_data,
                session=self._session_data,
                sessions=self._session_data_per_charger,
                battery_session=self._battery_session,
                currency=self.hass.config.currency or "EUR",
                ev_charger_count=len(self._ev_devices),
                ev_charger_ids=list(self._ev_devices.keys()),
                ev_intelligence=ev_intelligence,
                per_charger_intelligence=self._build_per_charger_intelligence(),
                per_charger_daily_energy=self._per_charger_daily_report(energy),
                last_update=dt_util.now(),
            )

            # Layered-trace observability (1.7.5) — read-only capture of this
            # cycle's management→process→integration chain. Wrapped so it can
            # NEVER affect the control path or break the cycle.
            self._collect_trace(sem_data, power, charging_context)

            # Step 11.5: Energy balance / calculation health check
            self._health_check.run_all_checks(
                power,
                flows=power_flows,
                costs=costs,
                # (#660) the autarky / self-consumption range check is gone —
                # their producer clamps them into range, so it could never
                # fire. What the calculator's clamps HAD to remove is passed
                # instead, and a sustained correction is the violation.
                clamp_engagement=getattr(
                    self._energy_calculator, "clamp_engagement", {},
                ),
                home_hold_active=getattr(self, "_home_hold_active", False),
                # (#771) The three published per-device breakdowns, so they
                # can be reconciled against the fleet rows they decompose.
                # ``live_charger_ids`` is what makes the diagnostic
                # actionable: a member that is no longer configured is the
                # one whose stale bucket is inflating the sum.
                energy=energy,
                energy_flows=energy_flows,
                per_charger_daily=dict(self._daily_ev_per_charger),
                live_charger_ids=[
                    str(c.get("id"))
                    for c in (self.config.get("ev_chargers") or [])
                    if c.get("id")
                ],
                # (#773) The devices are members of the home row the way
                # chargers are members of the EV day (over-count only —
                # shortfall IS the baseload), and the sealed history feeds
                # the drift check that asks whether the leftover still
                # behaves like a house.
                per_device_daily={
                    d.device_id: float(
                        getattr(d, "daily_energy_kwh", 0.0) or 0.0)
                    for d in self._surplus_controller._devices.values()
                    if getattr(d, "device_id", None)
                },
                baseload_history=getattr(
                    self._energy_calculator, "baseload_history", None,
                ) if self._energy_calculator else None,
            )

            # Step 12: Notifications (extracted for readability, #29)
            await self._send_notifications(
                charging_state, power, energy, costs, performance,
                charging_context, forecast_data, discharge_limit,
                charging_context.calculated_current,
                charging_context.available_power,
            )

            # Step 13: Persist data
            if self._storage:
                self._storage.import_energy_calculator_state(
                    self._energy_calculator.get_state()
                )
                # Persist forecast tracker state
                self._storage.import_forecast_tracker_state(
                    self._forecast_tracker.get_state()
                )
                # Persist device runtimes
                self._persist_device_runtimes()
                # Persist predictor state (#3)
                self._storage._daily_data["predictor"] = self._predictor.get_state()
                # Persist EV intelligence state (#106)
                self._storage.set_ev_intelligence_state(self._ev_taper_detector.get_state())
                # (#635) per-charger detectors persist too — the restore has
                # always read chargers.<cid>; without this every restart
                # blanked the estimated SOC (not anchored → sensor None).
                for _cid, _det in (getattr(self, "_ev_taper_detectors", None) or {}).items():
                    self._storage.set_per_charger_intelligence_state(_cid, _det.get_state())
                # Persist per-charger daily EV energy so it survives restarts (so the
                # per-charger night-charge remaining + daily sensor stay correct).
                self._storage._daily_data["per_charger_daily"] = {
                    "date": self._daily_ev_per_charger_date,
                    "values": dict(self._daily_ev_per_charger),
                }
                # Persist daily flow accumulators (#282) — without this, an HA
                # restart mid-day rewinds flow_*_to_*_energy sensors to 0 and
                # users see broken Sankey totals for the rest of the day.
                self._storage._daily_data["flow_accumulator"] = (
                    self._flow_calculator.get_flow_accumulator_state()
                )
                # Persist sign-detection locks (#476 item 5) so a learned
                # grid/battery sign survives restarts.
                self._storage.set_sign_state(
                    self._sensor_reader.export_sign_state()
                )
                # Persist the legionella timestamp (#508 I2).
                _hw = self._surplus_controller._devices.get("hot_water") \
                    if hasattr(self, "_surplus_controller") else None
                _leg_t = getattr(_hw, "_last_legionella_time", None) if _hw else None
                if _leg_t is not None:
                    try:
                        self._storage.set_legionella_time(_leg_t.isoformat())
                    except (AttributeError, ValueError):
                        pass
                await self._storage.async_save_energy_delayed()
                # Flush the daily store too (device runtimes, predictor, EV
                # intelligence, flow/sign/per-charger state) on a throttled
                # immediate write — previously it only reached disk on a
                # graceful stop, so an unclean reboot lost the day's progress.
                await self._storage.async_save_daily_throttled()

            self._initial_update_done = True
            result = sem_data.to_dict()
            # (#699) the cards' atomic balance set — built HERE, where the
            # home-hold state lives, so a known-incoherent cycle ships the
            # last coherent set instead of a fresh/substituted chimera.
            result["power_snapshot"] = self._build_power_snapshot(power)
            # 3a — core snapshot complete (power/flows/energy/battery/EV/
            # charging). Everything below is enrichment; a throw past this
            # point degrades to core data (see the except handler), it does
            # not discard the cycle. ``result`` is only mutated below (keys
            # added), never reassigned, so this alias stays valid.
            core_result = result

            # (#755) The third number. The plan writes down what each demand
            # ASKED and what the packer PROMISED it; what it actually DID was
            # never recorded, so "fits" has never been checked against
            # reality. Taken here, after the cycle's decisions, so the gate
            # sampled is the one this cycle's actuation actually obeyed.
            self._record_demand_outcomes(dt_util.now(), power)
            # (#800) The battery's night rides the same cycle: drain /
            # refill / clipping series for the #778 budget's learner.
            try:
                await self._record_battery_night(power, power_flows, energy)
            except Exception:  # noqa: BLE001 — recording never costs a cycle
                _LOGGER.debug("battery night record skipped", exc_info=True)

            # Add per-charger data (#131): power + session
            per_charger_soc: Dict[str, float] = {}
            for cid, ev_dev in self._ev_devices.items():
                # (#643) canonical smoothed per-charger read
                charger_power = self._charger_power_w(cid, power, ev_dev)
                result[f"charger_{cid}_power"] = round(charger_power, 0)
                result[f"charger_{cid}_name"] = ev_dev.name
                result[f"charger_{cid}_connected"] = self._last_ev_connected_per_charger.get(cid, False)
                # #351 M4 — surface per-charger effective state so the
                # fleet ``sem_charging_state`` no longer hides per-charger
                # disagreements (e.g. fleet says NIGHT_CHARGING_ACTIVE
                # while a solar_only charger's effective state is
                # SOLAR_IDLE). The pair comes from
                # ``_effective_states_per_charger`` populated by the
                # per-charger loop.
                _pcs_entry = (
                    getattr(self, "_effective_states_per_charger", None) or {}
                ).get(cid)
                if _pcs_entry is not None:
                    _eff_state, _ = _pcs_entry
                    # ChargingState is a str-enum; store the value for JSON
                    # serialisability.
                    result[f"charger_{cid}_charging_state"] = str(
                        getattr(_eff_state, "value", _eff_state)
                    )
                # Per-charger SEM-commanded current (#291). Authoritative
                # "what did SEM ask the charger to do" — diagnostic counterpart
                # to the upstream max_current sensor which can read stale.
                result[f"charger_{cid}_commanded_current"] = round(
                    float(getattr(ev_dev, "_current_setpoint", 0.0) or 0.0), 1,
                )
                # Per-charger session data
                session = self._session_data_per_charger.get(cid)
                if session:
                    result[f"charger_{cid}_session_energy"] = round(session.energy_kwh, 2)
                    result[f"charger_{cid}_session_solar_share"] = round(session.solar_share_pct, 1)
                else:
                    result[f"charger_{cid}_session_energy"] = 0.0
                    result[f"charger_{cid}_session_solar_share"] = 0.0
                # #135: pass-through of the charger's own session-energy
                # sensor (e.g. KEBA's ``sensor.keba_p30_session_energy``).
                # Surfaces the charger's truth alongside SEM's internal
                # integration so users can compare on the dashboard. The
                # SEM-integrated value above stays load-bearing for the
                # solar-share / cost calculations.
                _per_charger_cfg = next(
                    (c for c in (self.config.get("ev_chargers") or [])
                     if c.get("id") == cid), {}
                )
                _ext_sensor_id = _per_charger_cfg.get("ev_session_energy_sensor", "")
                _ext_value = 0.0
                if _ext_sensor_id:
                    # #641 — was Wh-only; MWh counters now convert too, and the
                    # rule is shared with the rest of the energy path.
                    _ext_value = energy_state_to_kwh(
                        self.hass.states.get(_ext_sensor_id), default=0.0,
                    )
                result[f"charger_{cid}_session_energy_external"] = round(_ext_value, 2)
                # Per-charger taper detection (#138)
                taper_det = self._ev_taper_detectors.get(cid)
                if taper_det:
                    result[f"charger_{cid}_taper_trend"] = taper_det._declining_phase and "declining" or "stable"
                    result[f"charger_{cid}_taper_ratio"] = round(
                        (charger_power / taper_det._session_peak_w * 100) if taper_det._session_peak_w > 0 else 0, 1
                    )
                # (#804 Phase A, observe-only) Active phases from measured
                # W/A — detects the car's actual phase use and will confirm
                # a commanded switch physically took (Phase B+). The switch
                # capability is the entity the user NAMES, validated never
                # probed (evcc #30143's lesson). INERT: nothing writes to
                # that entity until Phase B.
                from .ev_phases import (
                    estimate_active_phases, validate_phase_switch_entity,
                )
                result[f"charger_{cid}_active_phases"] = estimate_active_phases(
                    charger_power,
                    int(float(getattr(ev_dev, "_current_setpoint", 0) or 0)),
                    float(_per_charger_cfg.get("ev_voltage")
                          or self.config.get("ev_voltage") or 230),
                )
                _ps_entity, _ps_valid = validate_phase_switch_entity(
                    _per_charger_cfg.get("ev_phase_switch_entity"),
                    lambda eid: self.hass.states.get(eid) is not None,
                )
                result[f"charger_{cid}_phase_switch_entity"] = _ps_entity
                result[f"charger_{cid}_phase_switch_valid"] = _ps_valid
                # (#824) The entities SEM COMMANDS, checked the same way.
                # A dead sensor makes the numbers look wrong and gets
                # reported; a dead control entity makes SEM look like it
                # is working while the car does as it likes, because the
                # write neither lands nor raises.
                self._check_charger_control_entities(
                    cid, _per_charger_cfg, result)
                # (#804 Phase B/C) The sequencer's live state and the held
                # belief — the belief outlives the instantaneous estimate
                # (which is None whenever the car isn't drawing).
                result[f"charger_{cid}_phase_switch_state"] = (
                    getattr(self, "_phase_switch_states", None) or {}
                ).get(cid, "idle")
                result[f"charger_{cid}_believed_phases"] = (
                    getattr(self, "_phase_believed", None) or {}
                ).get(cid)
                # Per-charger vehicle SOC (#193) — collected for the global
                # vehicle_soc/range fallback below (no dedicated per-charger
                # sensor consumes this, so don't write it into result; #245 review #2).
                ev_chargers_cfg = self.config.get("ev_chargers", [])
                charger_cfg = next((c for c in ev_chargers_cfg if c.get("id") == cid), {})
                charger_soc_entity = charger_cfg.get("vehicle_soc_entity", "")
                if charger_soc_entity:
                    soc_state = self.hass.states.get(charger_soc_entity)
                    if soc_state and soc_state.state not in ("unknown", "unavailable"):
                        try:
                            per_charger_soc[cid] = float(soc_state.state)
                        except (ValueError, TypeError):
                            pass

            # Add forecast tracker data (accuracy, correction factor)
            if tracker_data:
                result.update(tracker_data)

            # Add night window sensors
            try:
                night_start, night_end = self.time_manager.get_night_window()
                result["night_start_time"] = night_start
                result["night_end_time"] = night_end
                result["night_window_hours"] = round(self.time_manager.get_night_window_hours(), 1)
            except (ValueError, AttributeError):
                result["night_start_time"] = ""
                result["night_end_time"] = ""
                result["night_window_hours"] = 0

            # Add lifetime EV stats from storage
            if self._storage:
                lifetime = self._storage.get_lifetime_ev_stats()
                result["lifetime_ev_energy"] = lifetime.get("total_energy_kwh", 0)
                result["lifetime_ev_solar"] = lifetime.get("total_solar_kwh", 0)
                result["lifetime_ev_cost"] = lifetime.get("total_cost", 0)
                result["lifetime_ev_sessions"] = lifetime.get("total_sessions", 0)
                # (#793) all three shares — battery-sourced kWh were invisible
                result.update(_lifetime_ev_shares(lifetime))

            # Vehicle SOC (from per-cycle cache). Fall back to a per-charger SOC
            # when no GLOBAL vehicle_soc_entity is set but a charger has its own —
            # otherwise the global vehicle_soc/range sensors stay unavailable in a
            # multi-charger / per-charger-only setup (#245 review #3).
            if self._cycle_vehicle_soc is None and per_charger_soc:
                self._cycle_vehicle_soc = next(iter(per_charger_soc.values()))
            if self._cycle_vehicle_soc is not None:
                result["vehicle_soc"] = self._cycle_vehicle_soc

            # EV driving range (#245): prefer a real range entity, else derive
            # from SOC × usable capacity ÷ consumption (ev_kwh_per_100km).
            _range_entity = self.config.get("vehicle_range_entity", "")
            if _range_entity:
                _rs = self.hass.states.get(_range_entity)
                if _rs and _rs.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    _range_km = distance_to_km(
                        _rs.state,
                        _rs.attributes.get("unit_of_measurement"),
                    )
                    if _range_km is not None:
                        result["ev_remaining_range"] = round(_range_km)
                    else:
                        _LOGGER.warning(
                            "Ignoring vehicle range %s with unsupported/invalid unit %r",
                            _range_entity,
                            _rs.attributes.get("unit_of_measurement"),
                        )
            if "ev_remaining_range" not in result and self._cycle_vehicle_soc is not None:
                # Capacity + efficiency are per-car → read the (primary) charger's
                # values, falling back to global config. One car per charger (#245).
                _pcfg = self._primary_charger_cfg()

                def _per_car(key, default):
                    v = _pcfg.get(key)
                    return v if v is not None else self.config.get(key, default)

                _cap = _per_car("ev_battery_capacity_kwh", 40)
                _cons = _per_car("ev_kwh_per_100km", 18)  # consumption, kWh/100km
                if _cons and _cons > 0:
                    result["ev_remaining_range"] = round(
                        self._cycle_vehicle_soc / 100 * _cap / _cons * 100
                    )

            # EV departure time (if configured via input_datetime entity)
            departure_entity = self.config.get("ev_departure_time_entity", "")
            if departure_entity:
                dep_state = self.hass.states.get(departure_entity)
                if dep_state and dep_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    result["ev_departure_time"] = dep_state.state

            # EV charge-target deadline (#246) + tariff-optimized status (#247) —
            # surfaced for the EV card / status. target_time + tariff toggle are
            # always available (config); the deadline/cheap-window fields come from
            # the per-cycle night plan (primary charger), present only at night.
            _dl_pcfg = self._primary_charger_cfg()
            result["ev_target_time"] = self._charger_target_time(_dl_pcfg)
            result["ev_tariff_optimized"] = self._tariff_optimized_for(_dl_pcfg)
            _night_plan = self._cycle_night_plan
            if _night_plan is not None:
                result["ev_deadline_reachable"] = _night_plan.reachable
                result["ev_tariff_waiting"] = _night_plan.should_wait_for_cheap
                if _night_plan.hours_to_deadline is not None:
                    # (#829) 0.1 h. At two decimals this countdown moved
                    # every ~36 s and rewrote sensor.sem_charging_state
                    # with it; 6-minute resolution is all a deadline means.
                    result["ev_deadline_hours"] = round(
                        _night_plan.hours_to_deadline or 0.0, 1)
                if _night_plan.next_cheap_start is not None:
                    result["ev_next_cheap_window"] = _night_plan.next_cheap_start.isoformat()

            # VPP grid-event dispatch state (#580) — feeds sensor.sem_vpp_event
            # (state + per-event accounting attributes). Always present so the
            # sensor reads "idle" rather than unavailable when VPP is off.
            result.update(getattr(self, "_vpp_publish", None)
                          or {"vpp_event": "idle", "vpp_event_observer": True})

            # (#778) Planning evidence — measured, not assumed. Written out
            # EXPLICITLY rather than looped: #657's guard cannot see keys
            # published through a dynamic loop, and it is right not to — a
            # phantom key hiding behind clever publishing reads to a user as
            # "measured, and null", which is worse than an absent attribute.
            _pe = getattr(self, "_planning_evidence", None) or {}
            result["battery_measured_capacity_kwh"] = _pe.get("battery_measured_capacity_kwh")
            result["battery_capacity_kwh_per_pct"] = _pe.get("battery_capacity_kwh_per_pct")
            result["battery_capacity_samples"] = _pe.get("battery_capacity_samples")
            result["battery_capacity_drift_pct"] = _pe.get("battery_capacity_drift_pct")
            result["battery_capacity_reason"] = _pe.get("battery_capacity_reason")
            # (#820) what pacing decided this cycle (None until first run)
            # (#827) a brand whose discharge rate SEM cannot set says so.
            try:
                _ad = getattr(self, "_battery_adapter", None)
                _cav = getattr(_ad, "discharge_rate_caveat", None)
                if callable(_cav) and getattr(
                        _ad, "_system_work_mode_control", False):
                    result["battery_discharge_rate_caveat"] = _cav()
            except Exception:  # noqa: BLE001
                pass
            _cp = getattr(self, "_charge_pacing_state", None)
            if _cp:
                result["charge_pacing"] = dict(_cp)
                # scalar twin: the sensor's generic value path reads
                # data[key] directly, and a dict is not a state.
                result["battery_charge_pacing"] = _cp.get("cap_w")
            result["forecast_trust_d1"] = _pe.get("forecast_trust_d1")
            result["forecast_trust_d2"] = _pe.get("forecast_trust_d2")
            result["battery_overnight_need_kwh"] = _pe.get("battery_overnight_need_kwh")
            result["battery_expected_refill_kwh"] = _pe.get("battery_expected_refill_kwh")
            result["battery_refill_clipped_kwh"] = _pe.get("battery_refill_clipped_kwh")
            result["battery_refill_reason"] = _pe.get("battery_refill_reason")
            result["battery_spendable_kwh"] = _pe.get("battery_spendable_kwh")
            result["battery_dynamic_floor_pct"] = _pe.get("battery_dynamic_floor_pct")
            result["battery_spendable_reason"] = _pe.get("battery_spendable_reason")
            result["planning_phase"] = _pe.get("planning_phase")
            result["planning_nights_sealed"] = _pe.get("nights_sealed")
            result["planning_nights_required"] = _pe.get("nights_required")
            result["forecast_days_d1"] = _pe.get("forecast_days_d1")
            result["forecast_days_d2"] = _pe.get("forecast_days_d2")
            result["forecast_days_required"] = _pe.get("forecast_days_required")
            result["forecast_d1_available"] = _pe.get("forecast_d1_available")
            result["forecast_d2_available"] = _pe.get("forecast_d2_available")

            # (#625 phase 3) Diagnostics summary for the System tab —
            # read-only assembly extracted to publish_diag.build_diagnostics.
            from .publish_diag import build_diagnostics
            result.update(build_diagnostics(self))

            # Tariff schedule for dashboard card (#25)
            if hasattr(self._tariff_provider, 'get_schedule_for_day'):
                result["tariff_schedule_today"] = self._tariff_provider.get_schedule_for_day()
                # v1.7.2-beta.3 (2026-06-07): diagnose-only counter so
                # users with a misclassifying schedule (RienduPre,
                # Tibber NL, Discussion #432) can paste back the
                # distribution + source-entity shape. The full price
                # array isn't published (would explode coordinator.data
                # for any cache > 24 points) — just the counts.
                try:
                    _prices_for_diag = getattr(
                        self._tariff_provider, "_prices_cache", None,
                    ) or []
                    _today_for_diag = dt_util.now().date()
                    _today_prices = [
                        p for p in _prices_for_diag
                        if _tariff_local_date(p.timestamp) == _today_for_diag
                    ]
                    if _today_prices:
                        _level_counts: Dict[str, int] = {}
                        for p in _today_prices:
                            k = p.level.value if hasattr(p.level, "value") else str(p.level)
                            _level_counts[k] = _level_counts.get(k, 0) + 1
                        result["tariff_today_prices_count"] = len(_today_prices)
                        result["tariff_today_level_counts"] = _level_counts
                        result["tariff_today_first_price"] = round(_today_prices[0].price, 4)
                        result["tariff_today_last_price"] = round(_today_prices[-1].price, 4)
                    else:
                        result["tariff_today_prices_count"] = 0
                        result["tariff_today_level_counts"] = {}
                    # Parser diag: which attribute matched + the
                    # sample interval. Both are key for diagnosing
                    # 15-min vs hourly NL Tibber/ENTSO-E shapes.
                    result["tariff_parsed_attribute"] = getattr(
                        self._tariff_provider, "_last_parsed_attribute", None,
                    )
                    result["tariff_parsed_count"] = getattr(
                        self._tariff_provider, "_last_parsed_count", None,
                    )
                    result["tariff_parsed_interval_seconds"] = getattr(
                        self._tariff_provider, "_last_parsed_gap_seconds", None,
                    )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.debug("Tariff diag-counts failed: %s", e)

            # Dynamic price visibility (#257): surface the upcoming hourly price
            # curve + today's summary so the price card can render a live chart.
            try:
                _td = self._tariff_provider.get_tariff_data()
                result["tariff_upcoming"] = [
                    {"t": p.timestamp.isoformat(), "price": round(p.price, 4),
                     "level": p.level.value}
                    for p in (_td.upcoming_prices or [])[:48]
                ]
                result["tariff_currency"] = _td.currency
                result["tariff_today_min_price"] = _td.today_min_price
                result["tariff_today_max_price"] = _td.today_max_price
                result["tariff_today_avg_price"] = _td.today_avg_price
                result["tariff_next_cheap_end"] = (
                    _td.next_cheap_window_end.isoformat()
                    if _td.next_cheap_window_end else None
                )
            except Exception as e:
                _LOGGER.debug("Tariff price-curve surface failed (#257): %s", e)

            # Today's plan (#282): compose a forward-looking schedule from the
            # tariff curve + solar forecast + night window + EV state. Surfaced
            # on charging_state attributes for sem-today-plan-card. Pure helper
            # in coordinator/today_plan.py so logic is unit-testable.
            try:
                from .today_plan import compose_today_plan
                _now = dt_util.now()
                # Solar — read directly from the forecast reader's cached data
                _peak_t = None
                _solar_remaining = None
                try:
                    _fcd = self._forecast_reader.forecast_data
                    _peak_t = _fcd.peak_time_today
                    _solar_remaining = _fcd.forecast_remaining_today_kwh
                except AttributeError:
                    pass
                # Night window — get HH:MM endpoints, resolve to datetime.
                # If we're past the window's start today, the next window opens
                # tomorrow (handled by get_offset_time returning today's time
                # and us adding a day when it's already past).
                _night_start = None
                _night_end_dt = None
                try:
                    ns_hhmm, ne_hhmm = self.time_manager.get_night_window()
                    _night_start = self.time_manager.get_offset_time(ns_hhmm)
                    if _night_start <= _now:
                        _night_start = _night_start + timedelta(days=1)
                    _night_end_dt = self.time_manager.get_offset_time(ne_hhmm)
                    if _night_end_dt <= _now:
                        _night_end_dt = _night_end_dt + timedelta(days=1)
                except (AttributeError, ValueError):
                    pass
                # #298 — battery ETAs are fleet-shared; computed once.
                # Best-guess from the CURRENT power rate; steady-state at
                # the present rate is a useful approximation for "when
                # does this finish?" Suppress when SOC is already at the
                # boundary or the rate is too small for a sensible estimate.
                _MIN_USEFUL_RATE_KW = 0.2  # 200 W — below this an ETA is noise
                _battery_full_eta = None
                _battery_empty_eta = None
                try:
                    _bat_kw = (power.battery_power or 0.0) / 1000.0
                    _bat_cap = self.config.get("battery_capacity_kwh", 15.0)
                    _bat_soc = power.battery_soc if power.battery_soc is not None else None
                    # The battery-empty ETA references the real discharge
                    # floor — the SOC-zone priority floor — not the retired
                    # ``battery_minimum_soc`` knob (which never stopped
                    # discharge; it was a misleading "hard stop" label).
                    _bat_floor = self.config.get("battery_priority_soc", 30)
                    if _bat_soc is not None and _bat_cap > 0:
                        if _bat_kw > _MIN_USEFUL_RATE_KW and _bat_soc < 99:
                            remaining_kwh = (100 - _bat_soc) / 100 * _bat_cap
                            _battery_full_eta = _now + timedelta(
                                hours=remaining_kwh / _bat_kw,
                            )
                        elif _bat_kw < -_MIN_USEFUL_RATE_KW and _bat_soc > _bat_floor:
                            remaining_kwh = (_bat_soc - _bat_floor) / 100 * _bat_cap
                            _battery_empty_eta = _now + timedelta(
                                hours=remaining_kwh / abs(_bat_kw),
                            )
                except (AttributeError, TypeError, ValueError, ZeroDivisionError):
                    pass

                # Per-charger plan composition (#464): night plan, target,
                # deadline, mode and live-session ETA are all PER-CHARGER
                # quantities, but the plan used to be composed once from the
                # primary charger's values — the EV card then rendered that
                # identical strip under every charger ("why is this bar the
                # same for both chargers?"). Compose one plan per charger;
                # the fleet ``today_plan`` stays the primary's plan for
                # sem-today-plan-card and as the card-side legacy fallback.
                _shared_plan_kwargs = dict(
                    now=_now,
                    upcoming_prices=result.get("tariff_upcoming"),
                    solar_peak_time=_peak_t,
                    solar_remaining_kwh=_solar_remaining,
                    night_start=_night_start,
                    night_end=_night_end_dt,
                    battery_full_eta=_battery_full_eta,
                    battery_empty_eta=_battery_empty_eta,
                    currency=result.get("tariff_currency", ""),
                    device_runs=self._device_run_rows(_now, _peak_t),
                )
                _primary_cid = (_dl_pcfg or {}).get("id")
                # Legacy flat-config installs have no ev_chargers list —
                # keep one (possibly empty) primary entry so the night
                # plan from the primary pipeline still yields EV rows.
                _plan_cfgs = [
                    c for c in (self.config.get("ev_chargers") or [])
                    if isinstance(c, dict) and c.get("id")
                ] or [_dl_pcfg if isinstance(_dl_pcfg, dict) else {}]
                _fleet_plan = None
                from .ev_tariff_planner import resolve_deadline
                for _pcfg in _plan_cfgs:
                    _cid = _pcfg.get("id")
                    # Night plan: the per-charger one from the multi-charger
                    # loop; the primary additionally falls back to the
                    # primary-pipeline plan (single-charger installs never
                    # populate the per-charger dict). Both dicts are rebuilt
                    # each cycle, so day cycles see None here.
                    _np_c = self._night_plan_per_charger.get(_cid)
                    if _np_c is None and _cid == _primary_cid:
                        _np_c = self._cycle_night_plan
                    _ev_remaining = _np_c.remaining_kwh if _np_c else None
                    _ev_deadline_dt = _np_c.deadline_dt if _np_c else None
                    _ev_rate_kw = None
                    if _np_c and _np_c.hours_to_deadline and _np_c.hours_to_deadline > 0 and _np_c.remaining_kwh:
                        # The planner's reachable=True implies remaining/rate <= hours_left;
                        # this is the rough effective rate (peak-managed unless forcing).
                        _ev_rate_kw = _np_c.remaining_kwh / max(0.1, _np_c.hours_to_deadline)
                    # Daytime fallback (#282): the night planner only runs inside the
                    # night window, so during the day the plan is None and the strip
                    # would have no EV rows. Estimate remaining_to_min from the daily
                    # target vs accumulated, and resolve deadline from the charger
                    # config so the EV card can show "tonight's plan" as a preview.
                    #
                    # Gate on the charge mode permitting night charging (#277
                    # Phase B): when the user's mode never grid-charges
                    # overnight, surfacing a "EV will charge at 21:22" row is
                    # misleading — the charger will NOT actually charge.
                    if _ev_remaining is None or _ev_remaining <= 0.1:
                        try:
                            _night_on = _cid and self._mode_allows_night_charging(_pcfg)
                            if not _night_on:
                                raise ValueError("charge mode disables night charging — no EV preview")
                            _target = (_pcfg.get("daily_ev_target")
                                       or self.config.get("daily_ev_target", 10))
                            _daily = (self._charger_daily_kwh(_cid, energy)
                                      if _cid else (getattr(energy, "daily_ev", 0.0) or 0.0))
                            _remain = max(0.0, float(_target) - float(_daily))
                            if _remain > 0.1:
                                _ev_remaining = _remain
                                # Resolve deadline from charger config — same path the
                                # planner uses, just without the full plan computation.
                                _tt = self._charger_target_time(_pcfg)
                                _ev_deadline_dt = resolve_deadline(_now, _tt)
                                # Rate estimate at 3-phase peak floor; the strip is a
                                # preview, not the truth — close enough for the visual.
                                _ev_rate_kw = 4.1  # ~6A x 690 W/A
                        except (ValueError, TypeError, AttributeError):
                            pass
                    # #298 — live target ETA while THIS charger's session is in
                    # progress. Uses the charger's own power reading (already in
                    # ``result`` from the per-charger block above); falls back
                    # to the fleet total only when the per-charger key is
                    # missing (legacy single-charger path).
                    _ev_target_eta = None
                    _ev_target_kwh = None
                    try:
                        _pwr_w = result.get(f"charger_{_cid}_power")
                        if _pwr_w is None:
                            # FLEET-READ: legacy single-charger fallback — no
                            # per-charger power key exists, so the fleet
                            # total IS this charger's power.
                            _pwr_w = power.ev_power or 0.0
                        _ev_kw = float(_pwr_w or 0.0) / 1000.0
                        if _ev_kw > _MIN_USEFUL_RATE_KW:
                            # Target preference: explicit Max ceiling > daily
                            # target. Matches the surplus-stop semantics
                            # from #245 — Max is where solar charging stops,
                            # the natural ETA for an active session. Falls
                            # back to Min if Max isn't set so something is
                            # still surfaced.
                            _ev_target = (
                                _pcfg.get("daily_ev_target_max")
                                or _pcfg.get("daily_ev_target")
                                or self.config.get("daily_ev_target_max")
                                or self.config.get("daily_ev_target", 10)
                            )
                            _ev_daily = (
                                self._charger_daily_kwh(_cid, energy)
                                if _cid else (getattr(energy, "daily_ev", 0.0) or 0.0)
                            )
                            _remaining_to_target = max(
                                0.0, float(_ev_target) - float(_ev_daily),
                            )
                            if _remaining_to_target > 0.1:
                                _ev_target_eta = _now + timedelta(
                                    hours=_remaining_to_target / _ev_kw,
                                )
                                _ev_target_kwh = float(_ev_target)
                    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
                        pass

                    _plan = compose_today_plan(
                        **_shared_plan_kwargs,
                        ev_min_remaining_kwh=_ev_remaining,
                        ev_deadline=_ev_deadline_dt,
                        ev_tariff_optimized=self._tariff_optimized_for(_pcfg),
                        ev_tariff_waiting=bool(
                            _np_c.should_wait_for_cheap if _np_c else False
                        ),
                        ev_next_cheap_window=(
                            _np_c.next_cheap_start
                            if _np_c and _np_c.next_cheap_start else None
                        ),
                        # (#742) the joint plan's blocks drive the strip
                        # when covered; None = reactive fallback.
                        ev_plan_blocks=self._ev_blocks_for(_cid) if _cid else None,
                        ev_effective_rate_kw=_ev_rate_kw,
                        ev_target_eta=_ev_target_eta,
                        ev_target_kwh=_ev_target_kwh,
                    )
                    if _cid:
                        result[f"charger_{_cid}_today_plan"] = _plan
                    if _fleet_plan is None or _cid == _primary_cid:
                        _fleet_plan = _plan

                result["today_plan"] = (
                    _fleet_plan if _fleet_plan is not None
                    else compose_today_plan(**_shared_plan_kwargs)
                )
            except Exception as e:
                _LOGGER.debug("today_plan compose failed (#282): %s", e)
                result["today_plan"] = []

            # (#638 G3c) The shadow energy plan, published for the card.
            # Read from the stash rather than recomputed: the plan is stamped
            # ONCE per night by ``_shadow_energy_plan`` and must read the
            # same on every cycle after it — recomputing here would give the
            # card a value that drifts away from the one the logs quote.
            # (#638 G4) ``actuation`` rides along LIVE (not from the stash):
            # flipping the switch mid-night must change the chip on the next
            # cycle, not on the next stamp.
            _onp = getattr(self, "_energy_plan_shadow", None)
            # (#638 C7) ``coverage`` rides LIVE beside ``actuation``: a
            # demand falling to the reactive layer mid-night must change
            # the card on the next cycle, not on the next stamp.
            result["energy_plan"] = (
                {**_onp,
                 "actuation": bool(getattr(
                     self, "_energy_plan_actuation", False)),
                 "coverage": self._plan_coverage_view()}
                if isinstance(_onp, dict) else _onp)
            # (#638 consolidation / #722) the NEXT energy day's books,
            # previewed for the card's Tomorrow view — live like
            # ``actuation``, never stamped: the plan for that day honestly
            # does not exist yet.
            try:
                result["energy_plan_tomorrow"] = (
                    self._compose_tomorrow_preview(power))
            except Exception:  # noqa: BLE001 — a preview never costs a cycle
                result["energy_plan_tomorrow"] = None
            # (#820) apply charge pacing with the inputs the preview stashed.
            # Decision always computed+published; the write additionally
            # needs the master switch, a named entity, and non-observer.
            _cpi = getattr(self, "_charge_pacing_inputs", None)
            if _cpi is not None:
                try:
                    await self._run_charge_pacing(*_cpi)
                except Exception:  # noqa: BLE001 — pacing never costs a cycle
                    _LOGGER.debug("charge pacing skipped", exc_info=True)
                self._charge_pacing_inputs = None
            # (#755 pillar 4) Last night's verdict, on its OWN key. It has to
            # outlive the plan: ``energy_plan`` empties out in daylight, which
            # is exactly when somebody reads what the night taught.
            result["energy_plan_review"] = getattr(
                self, "_demand_review", None)

            # Hourly activity tracker for schedule card (#63)
            now_time = dt_util.now()
            today_date = now_time.date()
            if self._tracker_date != today_date:
                self._today_surplus_hours = [False] * 24
                self._today_ev_hours = [False] * 24
                self._tracker_date = today_date
            # (#645) Decay is checked against its OWN persisted date, NOT the
            # in-memory tracker above — a restart re-initialises the tracker to
            # today and would swallow the rollover.
            self._run_due_daily_decay(now_time, today_date, power)
            # (#829) Retention for SEM's own statistics-less status entities.
            # Off by default; the user sets it on the Config tab. Runs at most
            # once a calendar day and never touches an entity that carries
            # long-term statistics — see coordinator/retention.py.
            try:
                from .retention import retention_is_due, run_purge
                _ret = self.config.get("status_retention_days", 0)
                _today_s = str(today_date)
                if retention_is_due(_ret, self._retention_last_day, _today_s):
                    self._retention_last_day = _today_s
                    self.hass.async_create_task(run_purge(self.hass, _ret))
            except Exception as _e:  # noqa: BLE001
                _LOGGER.debug("retention purge skipped: %s", _e)
            hour = now_time.hour
            if surplus_data.surplus_total_w > 100:
                self._today_surplus_hours[hour] = True
            # FLEET-READ: "is the fleet drawing at all" gate for the
            # consumption hour-bucket — any charger counts.
            if power.ev_power > 10:
                self._today_ev_hours[hour] = True
            result["schedule_surplus_hours"] = list(self._today_surplus_hours)
            result["schedule_ev_hours"] = list(self._today_ev_hours)

            # Battery charge scheduler sensors (#6)
            bcs = self._battery_charge_scheduler
            result["battery_scheduler_state"] = bcs.state.value
            result["battery_scheduler_target_soc"] = bcs.decision.target_soc
            result["battery_scheduler_deficit_kwh"] = bcs.decision.deficit_kwh
            result["battery_scheduler_reason"] = bcs.decision.reason
            # (#638 C4c) the schedule view now derives from the stamped
            # plan's battery blocks — same dict shape as the deleted
            # NightChargeSchedule.as_dict, ev_w honestly 0.
            from .battery_charge_scheduler import schedule_view_from_plan
            result["battery_scheduler_schedule"] = schedule_view_from_plan(
                getattr(self, "_energy_plan_shadow", None), dt_util.now())

            # Predictor sensors (#3)
            result["predictor_training_status"] = self._predictor.training_status
            result["predictor_model_accuracy"] = self._predictor.model_accuracy_pct
            now = dt_util.now()
            # (#544) predicted_consumption_next_hour / _today_kwh /
            # predicted_solar_next_hour removed — published, never charted/read.
            surplus_window = self._predictor.predict_surplus_window(now)
            if surplus_window:
                result["predicted_surplus_window"] = surplus_window

            # 3a — full cycle incl. enrichment succeeded; clear the degrade flag
            # so the next enrichment failure warns again (warn-once per episode).
            self._enrich_degraded = False
            return result

        except Exception as e:
            if core_result is not None:
                # #589 3a — the failure is in the enrichment tail (the core
                # snapshot was already built). Publish the core data so
                # power/battery/EV/flows stay live instead of the whole
                # coordinator going UpdateFailed; only the analytics/diagnostic
                # keys added after the snapshot are missing this cycle.
                if not getattr(self, "_enrich_degraded", False):
                    self._enrich_degraded = True
                    _LOGGER.warning(
                        "SEM result enrichment failed after the core snapshot "
                        "(%s); publishing core data — some analytics/diagnostic "
                        "entities may be stale this cycle. Control (power, "
                        "battery, EV) is unaffected.", e, exc_info=True,
                    )
                return core_result
            _LOGGER.error("Error updating SEM data: %s", e, exc_info=True)
            raise UpdateFailed(f"Update failed: {e}") from e

    # (#824) The capabilities SEM commands on a charger, and the phrase that
    # goes into the Repair so it says what was actually lost rather than
    # naming a config key at the user.
    _CONTROL_CAPABILITIES = (
        ("ev_current_control_entity", "set the charging current"),
        ("ev_start_stop_entity", "start and stop charging"),
    )

    def _check_charger_control_entities(self, cid, charger_cfg, result) -> None:
        """Pre-flight the entities SEM COMMANDS on this charger (#824).

        Not error handling: @onkelfu's template number carried an
        unsupported ``mode: slider``, so HA loaded it only as ``restored``
        and every write vanished WITHOUT raising. The existing
        ``charger_actuation_failed`` Repair needs three raised writes and
        therefore never fired. The failure produces no error, so the check
        has to look at the entity before trusting it.

        A broken entity waits out ``UNAVAILABLE_REPAIR_THRESHOLD_S`` before
        becoming a Repair — a restart's warm-up window must not cry wolf
        (#611) — but the per-charger verdict publishes immediately so the
        Configuration card can mark the row straight away.
        """
        from .control_entity import validate_control_entity
        from . import repair_issues as _ri

        broken_now = None
        any_configured = False
        for key, capability in self._CONTROL_CAPABILITIES:
            verdict = validate_control_entity(
                charger_cfg.get(key),
                lambda eid: (
                    self.hass.states.get(eid).state
                    if self.hass.states.get(eid) is not None else None
                ),
            )
            result[f"charger_{cid}_{key}_valid"] = verdict.valid
            result[f"charger_{cid}_{key}_reason"] = verdict.reason
            if verdict.valid is None:
                continue
            any_configured = True
            entity_id = verdict.configured

            if verdict.valid:
                self._control_broken_since.pop((cid, entity_id), None)
                if (cid, entity_id) in self._control_repair_raised:
                    self._control_repair_raised.discard((cid, entity_id))
                    _ri.clear_charger_control_entity_broken(
                        self.hass, str(cid), entity_id)
                continue

            broken_now = broken_now or verdict.reason
            import time as _time
            now_mono = _time.monotonic()
            first = self._control_broken_since.setdefault(
                (cid, entity_id), now_mono)
            if ((cid, entity_id) not in self._control_repair_raised
                    and now_mono - first >= _ri.UNAVAILABLE_REPAIR_THRESHOLD_S):
                self._control_repair_raised.add((cid, entity_id))
                _ri.raise_charger_control_entity_broken(
                    self.hass, str(cid),
                    name=str(charger_cfg.get("name") or cid),
                    entity_id=entity_id,
                    capability=capability,
                    reason=verdict.reason or "unavailable",
                )

        # One roll-up for the card: False the moment any commanded entity is
        # broken, True when every configured one is live, None when this
        # charger names no control entity at all (service-driven brands).
        result[f"charger_{cid}_control_valid"] = (
            None if not any_configured else broken_now is None
        )
        result[f"charger_{cid}_control_reason"] = broken_now

    @staticmethod
    def _heat_pump_sensor_state(hp_controller) -> tuple[str, int, bool]:
        """Extract (mode, sg_ready_state_value, solar_boost) from a
        registered HeatPumpController for the sensor surface (#570).

        Returns the NORMAL defaults (``"normal"``, 2, ``False``) when no
        controller is registered — matching HeatPumpSensorData's own
        dataclass defaults. Before #570 the coordinator never copied the
        controller's live SG-Ready state into HeatPumpSensorData (the
        override promised in the pipeline comment was never implemented),
        so heat_pump_mode / heat_pump_sg_ready_state / heat_pump_solar_boost
        stayed frozen at those defaults even while the controller drove the
        relays to BOOST/FORCE_ON — RienduPre's Nibe read "normal · 2"
        with relay2 physically closed.
        """
        if hp_controller is None:
            return "normal", 2, False
        sg = getattr(hp_controller, "sg_ready_state", None)
        mode, sg_value = "normal", 2
        if sg is not None:
            sg_value = int(getattr(sg, "value", sg))
            mode = str(getattr(sg, "name", "normal")).lower()
        hp_stat = getattr(hp_controller, "hp_status", None)
        solar_boost = bool(getattr(hp_stat, "is_solar_boosted", False))
        return mode, sg_value, solar_boost

    async def _update_analytics_phases(
        self,
        power: PowerReadings,
        energy: Any,
        energy_flows: Any,
        performance: Any,
        available_power: float,
    ) -> tuple:
        """Run analytics phases: forecast, tariff, surplus, PV, assistant (#29).

        Extracted from _async_update_data to reduce cyclomatic complexity.
        Each phase is independent and fails gracefully.
        """
        # Forecast (Phase 0.3)
        forecast_data = ForecastSensorData()
        try:
            forecast = self._cycle_forecast
            if forecast.available:
                forecast_data.forecast_today_kwh = forecast.forecast_today_kwh
                forecast_data.forecast_tomorrow_kwh = forecast.forecast_tomorrow_kwh
                forecast_data.forecast_remaining_today_kwh = forecast.forecast_remaining_today_kwh
                forecast_data.forecast_power_now_w = forecast.power_now_w
                forecast_data.forecast_power_next_hour_w = forecast.power_next_hour_w
                forecast_data.forecast_peak_power_today_w = forecast.peak_power_today_w
                forecast_data.forecast_peak_time_today = forecast.peak_time_today or ""
                forecast_data.forecast_source = forecast.source
                # (#819) carry the install's available sources through to
                # the dashboard picker
                forecast_data.forecast_sources_available = list(
                    getattr(forecast, "sources_available", []) or [])
                forecast_data.forecast_available = forecast.available
                daily_ev_target = self.config.get("daily_ev_target", 10)
                forecast_data.charging_recommendation = self._forecast_reader.get_charging_recommendation(
                    daily_ev_target, energy.daily_ev,
                )
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Forecast data parsing error: %s", e)
        except AttributeError as e:
            _LOGGER.debug("Forecast source not available: %s", e)

        # Forecast tracker — update BEFORE applying dampening to remaining/surplus
        tracker_data = {}
        try:
            # Dynamic weather entity detection — find any weather.* entity,
            # skip forecast_* subentities (HA auto-generated, unusable)
            weather_state = None
            for state in self.hass.states.async_all("weather"):
                if state.entity_id.startswith("weather.forecast_"):
                    continue
                weather_state = state
                break
            weather_condition = weather_state.state if weather_state else STATE_UNKNOWN
            # (#743, 1.8 half) a day the probe CONFIRMED curtailed teaches
            # nothing: measured solar is clamped to consumption, and learning
            # from it sinks the dampening factor — every dampened consumer
            # (fleet remaining-solar, forecast night target) then under-plans
            # exactly the hidden kilowatts the probe reveals.
            if getattr(self, "_curtailment_day", None) == dt_util.now().date():
                _LOGGER.debug(
                    "Forecast tracker: skipping today's sample — curtailment "
                    "confirmed, measured solar is not the sky's answer (#743)")
            else:
                self._forecast_tracker.update(
                    forecast_data.forecast_today_kwh, energy.daily_solar, weather_condition,
                )
            tracker_data = self._forecast_tracker.get_data()
            # (#544) forecast_corrected_tomorrow removed — dead sensor.

            # (#778) The horizon ledger. The tracker above scores ONE horizon —
            # what we said about today. This scores the others: what we said
            # two days ago about today, and whether that deserved believing.
            # Settling runs every cycle (idempotent, so the last value before
            # midnight becomes the day's final); the forecasts are recorded
            # once a day, which fixes the convention to "what we believed at
            # the start of the day" for every horizon alike.
            try:
                self._record_forecast_horizons(forecast_data, energy, dt_util.now(), power)
            except (AttributeError, TypeError, ValueError, KeyError) as _fe:
                # Narrow deliberately. A broad `except Exception` here caught a
                # NameError for two hours on .175 and reported it as a DEBUG
                # line, so the suite stayed green while six sensors sat
                # unavailable. A programming error must not be indistinguishable
                # from a missing sensor reading.
                _LOGGER.warning(
                    "forecast ledger update skipped (%s): %s",
                    type(_fe).__name__, _fe,
                )
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Forecast tracker update failed: %s", e)

        # Apply real-time dampening to the *planning* view of remaining solar
        # (surplus + best-window). (#598) The dampened value is kept LOCAL and
        # deliberately NOT written back to
        # ``forecast_data.forecast_remaining_today_kwh`` — that field feeds the
        # user-facing "Remaining" tile, which must stay on the SAME (raw) basis
        # as the "Forecast today" tile beside it. Dampening the display field
        # while today stays raw produced a self-contradictory pair at dawn
        # (e.g. today 70.8 kWh / remaining 35 kWh with almost nothing produced,
        # because the morning dampening factor sits near its 0.5 clamp floor).
        # The EV/battery control path re-derives its own dampened remaining from
        # the raw ``_cycle_forecast`` (see _build_fleet_cycle_state), so it is
        # unaffected by keeping the display field raw.
        try:
            if forecast_data.forecast_available:
                dampening = self._forecast_tracker.dampening_factor
                forecast_data.forecast_dampening_factor = dampening
                dampened_remaining = round(
                    forecast_data.forecast_remaining_today_kwh * dampening, 2
                )
                battery_target_soc = self.config.get("battery_priority_soc", 90)
                battery_need_kwh = max(0, (battery_target_soc - power.battery_soc) / 100 * self.battery_capacity_kwh)
                predicted_home = self._predictor.predict_consumption_today_kwh(dt_util.now())
                remaining_home = predicted_home if predicted_home > 0 else energy.daily_home * 0.5
                forecast_data.forecast_surplus_kwh = max(
                    0, dampened_remaining - remaining_home - battery_need_kwh
                )
                # Surplus window uses dampened remaining
                forecast_sig = f"{dampened_remaining:.1f}:{forecast_data.forecast_peak_time_today}"
                if forecast_sig != getattr(self, '_last_forecast_sig', ''):
                    self._last_forecast_sig = forecast_sig
                    self._cached_surplus_window = self._estimate_best_surplus_window(
                        self._cycle_forecast, power, energy, dampened_remaining
                    )
                forecast_data.best_surplus_window = getattr(self, '_cached_surplus_window', '')
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Forecast dampening failed: %s", e)

        # Tariff (Phase 1)
        tariff_data = TariffSensorData()
        try:
            tariff = self._tariff_provider.get_tariff_data()
            tariff_data.tariff_current_import_rate = tariff.current_import_rate
            tariff_data.tariff_current_export_rate = tariff.current_export_rate
            tariff_data.tariff_price_level = tariff.price_level.value
            tariff_data.tariff_provider = tariff.provider
            tariff_data.tariff_is_dynamic = tariff.is_dynamic
            tariff_data.tariff_today_min_price = tariff.today_min_price
            tariff_data.tariff_today_max_price = tariff.today_max_price
            tariff_data.tariff_today_avg_price = tariff.today_avg_price
            tariff_data.tariff_classifier_path = tariff.classifier_path
            if tariff.next_cheap_window_start:
                tariff_data.tariff_next_cheap_start = tariff.next_cheap_window_start.isoformat()
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Tariff read failed: %s", e)

        # Vacation mode (#594) — resolve + apply BEFORE the surplus
        # allocation below so this cycle's activation pass already sees the
        # gate on the heat-pump / hot-water controllers. Own try: a failure
        # here must not take out the surplus phase.
        try:
            await self._apply_vacation_mode()
        except Exception as e:  # noqa: BLE001 — never break the cycle
            _LOGGER.debug("Vacation mode apply failed: %s", e)

        # Surplus controller (Phase 0.2)
        surplus_data = SurplusControlData()
        surplus_data.vacation_active = self._vacation_active
        try:
            # #508 W7 — feed the TRUE house surplus, not the EV budget.
            # ``grid_export_power`` is what the house is exporting after the
            # EV and battery take their share; add back this controller's
            # own active device draw so the signal is feedback-free (a
            # device it turned on doesn't shrink the surplus it reads next
            # cycle and oscillate). Heat pump / hot water now boost on real
            # spare solar instead of competing for the EV's allocation.
            # #576 — above the reserve zone, offer the loads the power that
            # would otherwise charge the battery (the inverter self-consumes
            # the residual), so the surplus loads — walked by their own
            # priority — outrank battery charging and the battery is the sink.
            # Gated only by the reserve floor (``battery_priority_soc``): below
            # it the battery still fills first. Battery control already ran this
            # cycle (Step 7.5c+d, above), so ``_last_battery_decisions`` reflects
            # THIS cycle: an explicit/scheduled FORCE_CHARGE (or FORCE_DISCHARGE
            # arbitrage) is honored — no reclaim.
            # Same definition the EV reclaim gate uses — one source of truth.
            battery_commanded = self._battery_commanded()
            reclaim_w = reclaimable_battery_w(
                battery_charge_power=float(getattr(power, "battery_charge_power", 0.0) or 0.0),
                soc=float(getattr(power, "battery_soc", 0.0) or 0.0),
                priority_soc=float(self.config.get("battery_priority_soc", 30)),
                battery_commanded=battery_commanded,
            )
            # #576 — pass the export surplus and the reclaimable battery-charge
            # power SEPARATELY (plus the battery's slot in the priority walk).
            # The controller offers the reclaim only to loads ABOVE the battery
            # and hands it back at the battery's slot, so its drag position
            # decides who charges before the battery.
            # (#620) Feedback-free SOLAR surplus, physically bounded by the live
            # solar production — one invariant ("surplus ≤ sun") that pins the
            # figure to 0 overnight and kills phantom surplus from the add-back,
            # a noisy sensor, or battery→grid flow (@onkelfu's night report).
            true_surplus_w = solar_bounded_surplus(
                grid_export_w=float(getattr(power, "grid_export_power", 0.0) or 0.0),
                active_draw_w=self._surplus_controller.active_surplus_draw_w(),
                solar_w=getattr(power, "solar_power", None),
            )
            # (#625) per-cycle registry priority sync + peak posture — both
            # extracted; see UnifiedDeviceRegistry.sync_cycle_priorities and
            # surplus_controller.effective_peak_state for the full rationale.
            _reg = getattr(self, "_device_registry", None)
            battery_priority = (
                _reg.sync_cycle_priorities(
                    getattr(power, "battery_soc", None) is not None,
                    self._charger_priority_rows(),
                ) if _reg is not None else None
            )
            peak_state = effective_peak_state(
                self._load_manager.get_state() if self._load_manager else None,
                bool(getattr(self, "_vpp_shed_loads", False)),
            )
            # (#576) stash the priority-walk inputs for the 3-layer trace so
            # "why did the pool pump stop early?" is answerable: the battery's
            # slot, how much charge power it yielded, and whether it's commanded.
            self._cycle_reclaim = {
                "reclaim_w": round(float(reclaim_w)),
                "battery_priority": battery_priority,
                "battery_commanded": battery_commanded,
            }
            # ONE pipeline, observer or not. Layers 1+2 (management + decision)
            # always run against the live sensors; the ``observer`` flag cuts the
            # trigger at the single execution seam (``reconcile_load`` logs the
            # command it WOULD send instead of actuating). No separate read-only
            # path — a clean layer cut makes observation a one-flag branch, and
            # HA-TEST gets the full real decision trace with zero hardware risk.
            #
            # (#620/#625) battery context for the device battery tiers —
            # pure computation extracted to build_battery_tier_context.
            btc = build_battery_tier_context(
                self.config, getattr(power, "battery_soc", None), true_surplus_w,
            )
            # (#653) Tick the appliance scheduler BEFORE allocation.
            #
            # ``schedule_appliance`` registers a ``ScheduleDevice`` with the
            # surplus controller and the deadline force-start works, but the
            # lifecycle half was never called from anywhere — so a dishwasher
            # that finished at 15:00 stayed ``_started`` for the rest of the
            # day. That is not merely a stale status: ``ScheduleDevice``
            # refuses to deactivate while ``_started`` and ``adjust_power``
            # keeps returning ``rated_power``, so the finished appliance held
            # its full allocation against every lower-priority load until the
            # next restart. Ticking here (before ``update``) means a run that
            # completed this cycle has already released its claim by the time
            # the controller allocates.
            self._tick_appliance_scheduler()
            allocation = await self._surplus_controller.update(
                true_surplus_w,
                price_level=tariff_data.tariff_price_level,
                peak_state=peak_state,
                reclaim_w=reclaim_w,
                battery_priority=battery_priority,
                battery_soc=btc.soc,
                battery_buffer_soc=btc.buffer_soc,
                battery_reserve_soc=btc.reserve_soc,
                battery_assist_budget_w=btc.assist_budget_w,
                observer=self._observer_mode,
                # (#633) overnight sources are NIGHT sources.
                is_night=bool(self.time_manager.is_night_mode()),
                # (#638 G4) joint-plan window verdicts; empty unless the
                # actuation switch is on AND tonight's plan covers the load.
                plan_windows=self._energy_plan_load_windows(
                    self._surplus_controller.get_devices_sorted()),
            )
            surplus_data.surplus_total_w = allocation.total_surplus_w
            surplus_data.surplus_distributable_w = allocation.distributable_surplus_w
            surplus_data.surplus_regulation_offset_w = allocation.regulation_offset_w
            surplus_data.surplus_allocated_w = allocation.allocated_w
            surplus_data.surplus_unallocated_w = allocation.unallocated_w
            surplus_data.surplus_active_devices = allocation.active_devices
            surplus_data.surplus_total_devices = allocation.total_devices

            # (#559 Phase 0) debounced surplus availability for user
            # automations (peak_only devices are self-managed — this is
            # their interface to the surplus). Event fires on transitions
            # only, so flapping clouds can't storm the automation bus.
            threshold_w = float(self.config.get("surplus_event_threshold", 1500))
            transition = self._surplus_availability.update(
                allocation.unallocated_w, threshold_w, time.monotonic()
            )
            surplus_data.surplus_available = self._surplus_availability.available
            if transition:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_surplus",
                    {
                        "available": transition.available,
                        "surplus_w": round(transition.surplus_w),
                        "unallocated_w": round(allocation.unallocated_w),
                        "threshold_w": round(transition.threshold_w),
                    },
                )
                _LOGGER.info(
                    "Surplus %s (unallocated %.0fW vs threshold %.0fW) — "
                    "event fired",
                    "available" if transition.available else "gone",
                    allocation.unallocated_w, threshold_w,
                )
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Surplus controller update failed: %s", e)

        # Device runtimes. (#620 + Guido) The load "day" rolls over at
        # SUNRISE, not calendar midnight: if the counter reset at 00:00, a
        # Tier-2 battery-eligible load would see 0/target in the small hours
        # and drain the battery overnight to refill a brand-new day's target
        # BEFORE the day's surplus has any chance.
        #
        # (#704) The day comes from the SAME TimeManager meter-day class the
        # EV uses (#279) — stateless, so it is restart-proof by construction.
        # The previous inline latch (hold the day while is_night_mode()) fell
        # back to the CALENDAR date when a mid-night restart cleared it: a
        # boot at 02:00 stamped the new day, reset every deficit hours early,
        # and re-armed exactly the battery drain this boundary exists to
        # prevent. Also feeds the #703 force-expiry boundary via
        # ``device._daily_runtime_meter_day`` — one class, one day.
        try:
            meter_day = self.time_manager.get_current_meter_day_sunrise_based()
            self._load_meter_day = meter_day   # observability/back-compat
            for device in self._surplus_controller._devices.values():
                device.update_daily_runtime(meter_day)
            # (#769) The tick that accrued the energy is the tick that files
            # it. Same meter day, so the device's four horizons all rest on
            # the one day boundary.
            self._file_device_energy(meter_day)
            # (#773) The W twin of the daily residual: home minus the live
            # device draws SEM can see. A device with no readable power
            # contributes nothing — its draw simply stays inside the
            # baseload, which is exactly what "SEM cannot see it" means.
            # NOT clamped at zero: negative is the diagnostic's sharpest
            # finding (a double-count or a sign error), and the drift/
            # partition checks depend on seeing it.
            _controlled_w = 0.0
            for device in self._surplus_controller._devices.values():
                try:
                    _controlled_w += float(device.observed_power_w() or 0.0)
                except (AttributeError, TypeError, ValueError):
                    continue
            energy.true_baseload_power = round(
                float(power.home_consumption_power or 0.0) - _controlled_w, 1
            )
        except (AttributeError, TypeError) as e:
            _LOGGER.debug("Device runtime update failed: %s", e)

        # PV analytics (Phase 5)
        pv_data = PVAnalyticsData()
        try:
            pv = self._pv_analyzer.update(
                daily_solar_kwh=energy.daily_solar,
                monthly_solar_kwh=energy.monthly_solar,
                current_solar_power_w=power.solar_power,
                forecast_today_kwh=forecast_data.forecast_today_kwh,
            )
            pv_data.pv_daily_specific_yield = pv.daily_specific_yield
            pv_data.pv_performance_vs_forecast = pv.performance_vs_forecast
            pv_data.pv_estimated_annual_degradation = pv.estimated_annual_degradation
            pv_data.pv_degradation_trend = pv.degradation_trend
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("PV analytics update failed: %s", e)

        # Energy assistant (Phase 6)
        assistant_data = EnergyAssistantSensorData()
        try:
            assistant = self._energy_assistant.analyze(
                daily_solar_kwh=energy.daily_solar,
                daily_home_kwh=energy.daily_home,
                daily_ev_kwh=energy.daily_ev,
                daily_grid_import_kwh=energy.daily_grid_import,
                daily_grid_export_kwh=energy.daily_grid_export,
                daily_battery_charge_kwh=energy.daily_battery_charge,
                daily_battery_discharge_kwh=energy.daily_battery_discharge,
                solar_to_ev_kwh=energy_flows.solar_to_ev,
                grid_to_ev_kwh=energy_flows.grid_to_ev,
                self_consumption_rate=performance.self_consumption_rate,
                autarky_rate=performance.autarky_rate,
                current_price_level=tariff_data.tariff_price_level,
                forecast_remaining_kwh=forecast_data.forecast_surplus_kwh,
                forecast_tomorrow_kwh=forecast_data.forecast_tomorrow_kwh,
                best_surplus_window=forecast_data.best_surplus_window,
                peak_time_today=forecast_data.forecast_peak_time_today,
                battery_soc=power.battery_soc,
            )
            assistant_data.energy_optimization_score = assistant.optimization_score
            assistant_data.energy_tip = assistant.current_tip or "No recommendations"
            assistant_data.energy_tip_category = assistant.tip_category or "none"
            assistant_data.energy_ev_solar_percentage = assistant.ev_solar_percentage
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Energy assistant update failed: %s", e)

        # Heat pump data (#437): populate ``registered`` from the
        # surplus controller's device list so the dashboard auto-hide
        # can distinguish "no controller registered" from "in NORMAL
        # state". When a HeatPumpController IS registered, its current
        # sg_ready_state / mode / boost flags will override below.
        registered_flag = (
            "heat_pump" in getattr(
                getattr(self, "_surplus_controller", None),
                "_devices",
                {},
            )
        )
        # #432: compute the registration status string + live entity
        # state attributes so users with non-standard SG-Ready wiring
        # (ESP relays, Shellies, Modbus-bridged template switches) can
        # self-diagnose via ``sensor.sem_heat_pump_registration_status``.
        # Reads the saved option values once per cycle + queries
        # ``hass.states.get()`` for each configured entity.
        hp_relay1 = self.config.get("heat_pump_relay1_entity") or None
        hp_relay2 = self.config.get("heat_pump_relay2_entity") or None
        hp_climate = self.config.get("heat_pump_climate_entity") or None

        def _entity_state(eid: Optional[str]) -> Optional[str]:
            """Return the live HA state of an entity, or "entity_missing"
            if the entity id is set but does not exist in ``hass.states``."""
            if not eid:
                return None
            st = self.hass.states.get(eid)
            return st.state if st else "entity_missing"

        if registered_flag:
            if hp_relay1 and hp_relay2 and hp_climate:
                _hp_status = "registered_sg_ready_and_climate"
            elif hp_relay1 and hp_relay2:
                _hp_status = "registered_sg_ready"
            elif hp_climate:
                _hp_status = "registered_climate_only"
            else:
                # Defensive — registration flag true but no config matches.
                # Surfaces as a useful "investigate" signal.
                _hp_status = "registered_unknown_mode"
        else:
            if hp_relay1 and not hp_relay2 and not hp_climate:
                _hp_status = "partial_sg_ready_only_relay1"
            elif hp_relay2 and not hp_relay1 and not hp_climate:
                _hp_status = "partial_sg_ready_only_relay2"
            else:
                _hp_status = "not_configured"

        relay1_state = _entity_state(hp_relay1)
        relay2_state = _entity_state(hp_relay2)
        climate_state = _entity_state(hp_climate)

        # v1.7.2-beta.2: surface the #421 audit's ``_last_*_path``
        # recorders to a user-visible diagnostic surface. The
        # controller already records these on every cycle; we just
        # publish them through. Falls back to ``"no_controller"`` when
        # heat-pump isn't registered so the diagnostic surface stays
        # consistent (vs missing keys).
        hp_controller = None
        if registered_flag and hasattr(self, "_surplus_controller"):
            hp_controller = self._surplus_controller._devices.get("heat_pump")

        def _hp_attr(name: str) -> Optional[str]:
            if hp_controller is None:
                return "no_controller" if registered_flag else None
            return getattr(hp_controller, name, None)

        hp_current_temp: Optional[float] = None
        if hp_controller is not None:
            try:
                t = hp_controller.get_current_temperature() if hasattr(hp_controller, "get_current_temperature") else None
                hp_current_temp = float(t) if t is not None else None
            except (ValueError, TypeError, AttributeError):
                hp_current_temp = None

        # #570: wire the registered controller's LIVE SG-Ready state into
        # the sensor surface — the override the comment above promised but
        # that was never implemented. Without this, heat_pump_mode /
        # heat_pump_sg_ready_state / heat_pump_solar_boost stayed at the
        # dataclass defaults (normal / 2 / False) forever.
        hp_mode, hp_sg_state, hp_solar_boost = self._heat_pump_sensor_state(
            hp_controller
        )

        # (#769) Read the ledger row back out. The device booked the kWh
        # (#768) and the seam filed it; here it becomes four horizons plus
        # the SEM-caused split. ``shifted`` sums the SG-Ready states that
        # mean "SEM asked for this" — energy booked in NORMAL is energy the
        # pump's own thermostat would have taken anyway, and keeping the two
        # apart is what makes "SG-Ready shifted X kWh" a measurement.
        hp_ledger = {
            "daily_kwh": 0.0, "monthly_kwh": 0.0,
            "yearly_kwh": 0.0, "lifetime_kwh": 0.0,
        }
        hp_shifted_today = 0.0
        hp_shifted_total = 0.0
        _calc = getattr(self, "_energy_calculator", None)
        if _calc is not None and hp_controller is not None:
            try:
                _day = getattr(hp_controller, "_daily_runtime_meter_day", None) \
                    or self.time_manager.get_current_meter_day_sunrise_based()
                hp_ledger = _calc.get_device_energy("heat_pump", _day)
                hp_shifted_today = _calc.get_device_shifted("heat_pump", _day)
                hp_shifted_total = _calc.get_device_shifted(
                    "heat_pump", _day, lifetime=True
                )
            except (AttributeError, TypeError, ValueError):
                pass

        heat_pump_data = HeatPumpSensorData(
            heat_pump_registered=registered_flag,
            heat_pump_mode=hp_mode,
            heat_pump_sg_ready_state=hp_sg_state,
            heat_pump_solar_boost=hp_solar_boost,
            heat_pump_registration_status=_hp_status,
            heat_pump_relay1_entity=hp_relay1,
            heat_pump_relay2_entity=hp_relay2,
            heat_pump_climate_entity=hp_climate,
            heat_pump_relay1_state=relay1_state,
            heat_pump_relay2_state=relay2_state,
            heat_pump_climate_state=climate_state,
            heat_pump_activation_path=_hp_attr("_last_activation_path"),
            heat_pump_deactivation_path=_hp_attr("_last_deactivation_path"),
            heat_pump_relay_path=_hp_attr("_last_relay_path"),
            heat_pump_temperature_reading_path=_hp_attr("_last_temperature_reading_path"),
            heat_pump_offpeak_path=_hp_attr("_last_offpeak_path"),
            heat_pump_current_temperature=hp_current_temp,
            heat_pump_energy_today=hp_ledger["daily_kwh"],
            heat_pump_energy_month=hp_ledger["monthly_kwh"],
            heat_pump_energy_year=hp_ledger["yearly_kwh"],
            heat_pump_energy_total=hp_ledger["lifetime_kwh"],
            heat_pump_energy_shifted_today=hp_shifted_today,
            heat_pump_energy_shifted_total=hp_shifted_total,
            heat_pump_energy_source=getattr(
                hp_controller, "daily_energy_source", "none"
            ) or "none",
            heat_pump_energy_measured=bool(getattr(
                hp_controller, "daily_energy_is_measured", False
            )),
        )

        # ── Hot water data (#454) ───────────────────────────────────
        # Same pattern as heat_pump_data above: pull live state from
        # the registered controller (if any) into a sensor dataclass
        # so the Diagnose modal + future UI surfaces show concrete
        # decision branches instead of black-box state.
        hw_controller = None
        hw_entity_cfg = self.config.get("hot_water_entity") or None
        if hasattr(self, "_surplus_controller"):
            hw_controller = self._surplus_controller._devices.get("hot_water")

        def _hw_attr(name: str) -> Optional[str]:
            if hw_controller is None:
                return "no_controller" if hw_entity_cfg else None
            return getattr(hw_controller, name, None)

        hw_current_temp: Optional[float] = None
        hw_hours_since_leg: Optional[float] = None
        hw_leg_active: bool = False
        if hw_controller is not None:
            # #508 C1 — drive the legionella state machine every cycle.
            # check_legionella_cycle() had no production caller, so the
            # disinfection cycle never ran and hours_since_legionella was
            # pinned at the 999 sentinel forever. Running it each cycle
            # advances the hold-timer and fires completion correctly.
            if hasattr(hw_controller, "check_legionella_cycle"):
                try:
                    await hw_controller.check_legionella_cycle()
                except Exception as e:  # noqa: BLE001 — never break the cycle
                    _LOGGER.debug("Legionella cycle check failed: %s", e)
            try:
                t = hw_controller.get_current_temperature() if hasattr(hw_controller, "get_current_temperature") else None
                hw_current_temp = float(t) if t is not None else None
            except (ValueError, TypeError, AttributeError):
                hw_current_temp = None
            try:
                hw_hours_since_leg = float(hw_controller.hours_since_legionella) if hasattr(hw_controller, "hours_since_legionella") else None
            except (ValueError, TypeError, AttributeError):
                hw_hours_since_leg = None
            hw_leg_active = bool(getattr(hw_controller, "_legionella_cycle_active", False))

        hot_water_data = HotWaterSensorData(
            hot_water_registered=hw_controller is not None,
            hot_water_entity=hw_entity_cfg,
            hot_water_temperature_sensor=self.config.get("hot_water_temperature_sensor") or None,
            hot_water_current_temperature=hw_current_temp,
            hot_water_solar_target=(
                float(hw_controller.solar_target_temp) if hw_controller else None
            ),
            hot_water_max_temperature=(
                float(hw_controller.max_temperature) if hw_controller else None
            ),
            hot_water_legionella_target=(
                float(hw_controller.legionella_target_temp) if hw_controller else None
            ),
            hot_water_hours_since_legionella=hw_hours_since_leg,
            hot_water_legionella_cycle_active=hw_leg_active,
            hot_water_activation_path=_hw_attr("_last_activation_path"),
            hot_water_deactivation_path=_hw_attr("_last_deactivation_path"),
            hot_water_temperature_safety_path=_hw_attr("_last_temperature_safety_path"),
            hot_water_temperature_reading_path=_hw_attr("_last_temperature_reading_path"),
            hot_water_legionella_path=_hw_attr("_last_legionella_path"),
        )

        # #546 — KEBA failsafe Repair, ONLY in don't-arm mode
        # (``keba_arm_failsafe`` off). Default is managed-neutralize: SEM arms a
        # long non-tripping failsafe itself, so there's nothing for the user to
        # fix → no Repair. In don't-arm mode SEM leaves the box's failsafe alone,
        # so surface a Repair while it reads on (guides disabling it at the box).
        try:
            from . import repair_issues as _ri_fs
            if bool(self.config.get("keba_arm_failsafe", True)):
                # Managed mode (default) → SEM arms the failsafe itself; nothing
                # for the user to fix. Clear any stale Repair from a prior
                # don't-arm config.
                _ri_fs.clear_keba_failsafe_active(self.hass)
            else:
                # Don't-arm mode → SEM leaves the box's failsafe alone; surface a
                # Repair while it reads on so the user disables it at the charger.
                _keba_devs = [
                    d for d in (self._ev_devices or {}).values()
                    if str(getattr(d, "charger_service", "") or "").lower().startswith("keba.")
                ]
                if not _keba_devs and str(
                    getattr(self._ev_device, "charger_service", "") or ""
                ).lower().startswith("keba."):
                    _keba_devs = [self._ev_device]
                if _keba_devs:
                    _fs_on = _ri_fs.detect_keba_failsafe_state(self.hass)
                    if _fs_on is True:
                        # H1 — name the KEBA device, not just the first charger.
                        _ri_fs.raise_keba_failsafe_active(
                            self.hass, charger_name=_keba_devs[0].name,
                        )
                    elif _fs_on is False:
                        _ri_fs.clear_keba_failsafe_active(self.hass)
                    # _fs_on None (sensor absent/unavailable) → hold, don't clear.
                else:
                    # M1 — no KEBA configured (anymore) → clear stale Repair.
                    _ri_fs.clear_keba_failsafe_active(self.hass)
        except Exception as _e_fs:  # noqa: BLE001 — never fail the cycle over a repair
            _LOGGER.debug("KEBA failsafe repair check failed: %s", _e_fs)

        # #432 — relay unavailability tracking + Repair issue. Mirrors the
        # SensorReader pattern (``_sensor_unavailable_since``). Per-relay
        # outage timer; if a configured relay stays unavailable past the
        # 5-minute threshold, file a Repair so the user knows WHICH relay
        # to investigate (ESP / Shelly / Modbus template switch). Cleared
        # the moment the entity returns a real state.
        try:
            import time as _ri_time
            from . import repair_issues as _ri
            _now_mono = _ri_time.monotonic()
            if not hasattr(self, "_heat_pump_relay_unavailable_since"):
                self._heat_pump_relay_unavailable_since = {}
            tracked = self._heat_pump_relay_unavailable_since
            # v1.7.2-beta.5 (2026-06-08): one-time orphan sweep per
            # coordinator instance. Cleans repairs left behind from a
            # PRIOR config (e.g. user replaced `switch.old_entity` with
            # `switch.new_entity` — the old repair stayed stuck in the
            # registry because the per-cycle clear only addresses
            # currently-configured entities). RienduPre #448.
            if not getattr(self, "_heat_pump_orphan_sweep_done", False):
                _ri.clear_orphan_heat_pump_relay_repairs(
                    self.hass,
                    currently_configured_ids={
                        eid for eid in (hp_relay1, hp_relay2) if eid
                    },
                )
                self._heat_pump_orphan_sweep_done = True
            # v1.7.2-beta.2 (2026-06-07): the prior in-memory ``raised``
            # set was reset on every reload, so once a config change
            # cleared the underlying condition AFTER a reload, the
            # ``clear_*`` calls never fired and the Repair stuck in the
            # registry forever. ``async_create_issue`` and
            # ``async_delete_issue`` are both idempotent — call them
            # unconditionally based on current state. The only thing we
            # still need to track in-memory is the *since-when*
            # threshold for the unavailable timer.
            for slot, eid, state in (
                ("relay1", hp_relay1, relay1_state),
                ("relay2", hp_relay2, relay2_state),
            ):
                if not eid:
                    # No entity configured for this slot — clear any
                    # stale issue from before the config change and
                    # forget the timer.
                    _ri.clear_heat_pump_relay_unavailable(
                        self.hass, slot, eid or "",
                    )
                    continue
                key = f"{slot}:{eid}"
                is_bad = state in (None, "unavailable", "unknown", "entity_missing")
                if is_bad:
                    if key not in tracked:
                        tracked[key] = _now_mono
                    outage_s = _now_mono - tracked[key]
                    if outage_s >= _ri.UNAVAILABLE_REPAIR_THRESHOLD_S:
                        # Idempotent — re-raises with current minute
                        # count on every cycle past threshold; HA
                        # collapses identical creates.
                        _ri.raise_heat_pump_relay_unavailable(
                            self.hass, slot, eid,
                            minutes_unavailable=int(outage_s // 60),
                        )
                else:
                    tracked.pop(key, None)
                    # Idempotent — no-op if the issue isn't currently
                    # in the registry. Crucial across reloads.
                    _ri.clear_heat_pump_relay_unavailable(
                        self.hass, slot, eid,
                    )
            # Partial SG-Ready repair — fires when exactly one relay is
            # set with no climate fallback. Same idempotent pattern: no
            # in-memory flag, just always raise/clear based on current
            # status. ``_hp_status`` is already computed above from the
            # live config.
            partial = _hp_status in (
                "partial_sg_ready_only_relay1",
                "partial_sg_ready_only_relay2",
            )
            if partial:
                _ri.raise_heat_pump_partial_sg_ready(self.hass)
            else:
                _ri.clear_heat_pump_partial_sg_ready(self.hass)
        except Exception as e:  # noqa: BLE001 — never fail a cycle over a repair
            _LOGGER.debug("Heat-pump repair tracking failed: %s", e)

        # ── Hot water repair tracking (#454) ────────────────────────
        # Mirror of the heat-pump repair block. Two distinct Repair
        # surfaces:
        #   * boiler-control entity unavailable for >5 min
        #   * temperature sensor unavailable for >5 min
        # Both auto-raise/clear idempotently — no in-memory ``raised``
        # flag (lesson from beta.2/5 — flags don't survive reload).
        try:
            import time as _ri_time
            from . import repair_issues as _ri
            _now_mono = _ri_time.monotonic()
            if not hasattr(self, "_hot_water_unavailable_since"):
                self._hot_water_unavailable_since = {}
            tracked_hw = self._hot_water_unavailable_since
            # One-time orphan sweep per coordinator instance (catches
            # stale repairs from a prior config).
            if not getattr(self, "_hot_water_orphan_sweep_done", False):
                _ri.clear_orphan_hot_water_repairs(
                    self.hass,
                    currently_configured_entity=hw_entity_cfg,
                    currently_configured_temp_sensor=self.config.get(
                        "hot_water_temperature_sensor"
                    ) or None,
                )
                self._hot_water_orphan_sweep_done = True

            hw_temp_sensor_cfg = self.config.get("hot_water_temperature_sensor") or None
            for kind, eid in (
                ("entity", hw_entity_cfg),
                ("temp_sensor", hw_temp_sensor_cfg),
            ):
                if not eid:
                    # Slot not configured — defensive clear of any
                    # stale repair from before the config change.
                    if kind == "entity":
                        _ri.clear_hot_water_entity_unavailable(self.hass, eid or "")
                    else:
                        _ri.clear_hot_water_temperature_sensor_unavailable(self.hass, eid or "")
                    continue
                key = f"{kind}:{eid}"
                st = self.hass.states.get(eid)
                state_str = st.state if st else "entity_missing"
                is_bad = state_str in (None, "unavailable", "unknown", "entity_missing")
                if is_bad:
                    if key not in tracked_hw:
                        tracked_hw[key] = _now_mono
                    outage_s = _now_mono - tracked_hw[key]
                    if outage_s >= _ri.UNAVAILABLE_REPAIR_THRESHOLD_S:
                        mins = int(outage_s // 60)
                        if kind == "entity":
                            _ri.raise_hot_water_entity_unavailable(
                                self.hass, eid, minutes_unavailable=mins,
                            )
                        else:
                            _ri.raise_hot_water_temperature_sensor_unavailable(
                                self.hass, eid, minutes_unavailable=mins,
                            )
                else:
                    tracked_hw.pop(key, None)
                    if kind == "entity":
                        _ri.clear_hot_water_entity_unavailable(self.hass, eid)
                    else:
                        _ri.clear_hot_water_temperature_sensor_unavailable(self.hass, eid)
        except Exception as e:  # noqa: BLE001 — never fail a cycle over a repair
            _LOGGER.debug("Hot-water repair tracking failed: %s", e)

        # Phase 8: Consumption/solar predictor (#3)
        try:
            now = dt_util.now()
            self._predictor.observe(
                now,
                consumption_w=power.home_consumption_power,
                solar_w=power.solar_power,
            )
            # Feed EV consumption predictor (#106) — deduplicates by day
            if hasattr(energy, "daily_ev") and energy.daily_ev > 0:
                self._predictor.observe_ev(now, energy.daily_ev)
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Predictor observation failed: %s", e)

        return (
            forecast_data, tracker_data, tariff_data, surplus_data,
            pv_data, assistant_data, heat_pump_data,
            hot_water_data,
        )

    def _tick_appliance_scheduler(self) -> None:
        """Advance appliance schedules one cycle (#653).

        The scheduler is lazily created by the ``schedule_appliance``
        service, so on the overwhelming majority of installs this is a
        single ``getattr`` returning ``None``. It is deliberately
        fail-soft: a scheduler fault must not take the coordinator cycle
        down with it, because the cycle is also what publishes every
        sensor in the integration.
        """
        scheduler = getattr(self, "_appliance_scheduler", None)
        if scheduler is None:
            return
        try:
            scheduler.update_schedules()
        except Exception as err:
            # Covered by test_a_scheduler_fault_does_not_kill_the_cycle.
            _LOGGER.warning("Appliance scheduler tick failed: %s", err)

    def _per_battery_config(self, idx: int, count: int = 1) -> dict:
        """Config for the battery at position ``idx`` with per-battery
        control entities overlaid (#523 multi-battery).

        SEM senses each battery separately but historically controlled
        them with single global entities, so only one battery could be
        force-discharged / limited. The ``battery_*_entities`` LIST keys
        (parallel to the Energy-Dashboard ``battery_power_list`` order)
        give each unit its own control entity. Empty / missing → the
        global single-entity keys apply (single-battery installs and
        existing configs are unchanged).

        ``count`` is the live battery count this cycle. It gates the
        global ``battery_mode`` / ``battery_reserve_soc`` fall-through:
        those keys are the SINGLE-battery selector's storage
        (``select.sem_battery_mode`` → global key). In a multi-battery
        fleet the per-battery selectors own ``battery_modes[]`` and the
        UI shows ``auto`` for any unset slot — so the global key must NOT
        bleed in as the fallback (#531: single→multi upgrade showed
        ``auto`` in the UI while a stale global ``force_discharge`` drove
        every battery). With >1 battery an unset slot defaults to ``auto``.
        """
        cfg = self.config
        overrides: dict = {}
        # Control-entity overlays (force-discharge / discharge-limit).
        for list_key, single_key in (
            ("battery_force_discharge_entities", "battery_force_discharge_control_entity"),
            ("battery_discharge_control_entities", "battery_discharge_control_entity"),
            ("battery_strategy_entities", "battery_strategy_control_entity"),
        ):
            lst = cfg.get(list_key)
            if isinstance(lst, list) and idx < len(lst) and lst[idx]:
                overrides[single_key] = lst[idx]
        # Per-battery mode + reserve SOC (#523). Absent / empty → the
        # single-key ``battery_mode`` default (``auto``) applies, so
        # single-battery installs and untouched batteries are unchanged.
        multi = count > 1
        for list_key, single_key, multi_default in (
            ("battery_modes", "battery_mode", "auto"),
            ("battery_reserve_socs", "battery_reserve_soc", 0),
        ):
            lst = cfg.get(list_key)
            if isinstance(lst, list) and idx < len(lst) and lst[idx] not in (None, ""):
                overrides[single_key] = lst[idx]
            elif multi:
                # #531: multi-battery + no per-battery value → force the UI
                # default, never inherit the single-battery global key.
                overrides[single_key] = multi_default
        return {**cfg, **overrides} if overrides else cfg

    def _arbitrage_enabled(self, battery_count: int = 0) -> bool:
        """(#533 / #638 C6+C7) Can battery→grid arbitrage act on THIS install?

        ONE fact, two consumers. The battery pipeline asks it to decide
        whether to compute market signals at all; the plan payload carries
        the answer so the card knows the advisor's verdict describes a
        CLOSED feature. Before this the rule was an inline expression in the
        pipeline and nowhere else — which is why Guido's PROD card (16.08,
        battery in ``auto``, global toggle off) still printed "Battery
        arbitrage — no room to buy into…", explaining a trade nothing was
        ever going to make.

        Every default keeps it shut (#533 stands): no battery ships in
        ``allow_arbitrage`` and the global toggle defaults off. The user
        opens the valve — and only then does arbitrage owe an explanation.

        Reads defensively in the CLOSED direction: a valve we cannot see is
        shut. Arbitrage is opt-in, so False is the safe default — and this
        accessor must never be able to void the advice it gates.
        """
        if getattr(getattr(self, "_battery_scheduler_config", None),
                   "arbitrage_enabled", False):
            return True
        per_battery = getattr(self, "_per_battery_config", None)
        if not callable(per_battery):
            return False
        return any(
            str((per_battery(i, battery_count) or {}).get(
                "battery_mode", "auto") or "auto").lower() == "allow_arbitrage"
            for i in range(battery_count)
        )

    def _battery_adapter_context(
        self, battery_id: str, index: int = 0, count: int = 1,
    ) -> Dict[str, Any]:
        """Runtime-only context used to build a battery adapter (#709).

        Merges the coordinator config with the per-battery entity overlays,
        then injects the runtime scope — ``config_entry_id``, ``battery_id``
        and, for the Deye platform, a persistent ``DeyeSnapshotStore``.

        The store and scope are *runtime attachments*: they are passed to the
        adapter constructor and held on the adapter object only.  They are
        never written into entry ``data``/``options`` (HA serialises those),
        so nothing here can leak into persisted config.
        """
        base = self._per_battery_config(index, count) or dict(self.config)
        ctx = dict(base)
        entry_id = str(getattr(self.config_entry, "entry_id", "") or "")
        ctx.setdefault("config_entry_id", "")
        if entry_id:
            ctx["config_entry_id"] = entry_id
        ctx["battery_id"] = str(battery_id)
        platform = (ctx.get("battery_charge_platform") or "auto").lower()
        if platform == "deye":
            if not entry_id:
                # Never share a degenerate ``entry_id=''`` persistence scope
                # between config entries.  The Deye adapter then remains
                # unavailable/fail-closed until runtime identity is complete.
                ctx["deye_snapshot_store"] = None
            else:
                from .battery_adapters.deye_snapshot_store import DeyeSnapshotStore

                ctx["deye_snapshot_store"] = DeyeSnapshotStore(
                    self.hass, entry_id, ctx["battery_id"],
                )
        return ctx

    def _warn_battery_entity_collision(self, battery_id: str, pbc: dict) -> None:
        """Warn (once per entity) when two batteries share a control entity.

        #531: per-battery control assumes each unit drives its OWN
        force-discharge / strategy / discharge-limit entity. If a multi-
        battery config accidentally points two batteries at the same
        entity (e.g. a mis-pasted ``battery_force_discharge_entities``
        list), SEM would have them fight over one setpoint — the second
        write clobbers the first. We can't auto-resolve it, but a loud,
        de-duplicated warning makes the mis-config visible.
        """
        seen = getattr(self, "_battery_control_entity_owner", None)
        if seen is None:
            seen = {}
            self._battery_control_entity_owner = seen
        for key in (
            "battery_force_discharge_control_entity",
            "battery_strategy_control_entity",
            "battery_discharge_control_entity",
        ):
            ent = pbc.get(key)
            if not ent:
                continue
            owner = seen.get(ent)
            if owner is not None and owner != battery_id:
                _LOGGER.warning(
                    "Battery control-entity collision: %s is configured for "
                    "BOTH battery %s and battery %s (%s) — they will fight "
                    "over one setpoint. Give each battery its own entity.",
                    ent, owner, battery_id, key,
                )
            else:
                seen[ent] = battery_id

    def _compute_arbitrage_signals(self, power) -> "ArbitrageSignals":
        """Compute the battery→grid arbitrage market signals in ONE place
        (#533) so the arbitrage decision reads them off the view instead of
        ad-hoc tariff/power reads scattered in the pipeline. Pure-ish: reads
        the tariff provider + power, no side effects. Only called when
        arbitrage is being evaluated (the block stays dormant until v1.7.4).
        """
        from .charger_types import ArbitrageSignals
        solar_w = float(getattr(power, "solar_power", 0.0) or 0.0)
        home_w = float(getattr(power, "home_consumption_power", 0.0) or 0.0)
        soc_now = float(getattr(power, "battery_soc", 0.0) or 0.0)
        surplus_w = solar_w - home_w
        # #531 charge-first: storable solar surplus the battery could absorb →
        # don't sell (storing free solar avoids a future ~retail import, worth
        # far more than the export price).
        storable = surplus_w > 200.0 and soc_now < 98.0
        export_rate = 0.0
        import_forecast_min = None
        provider = getattr(self, "_tariff_provider", None)
        if provider is not None:
            try:
                export_rate = float(provider.get_current_export_rate())
            except Exception:  # noqa: BLE001
                export_rate = 0.0
            try:
                ups = getattr(
                    provider.get_tariff_data(), "upcoming_prices", None
                ) or []
                prices = [
                    float(p.price) for p in ups
                    if getattr(p, "price", None) is not None
                ]
                if prices:
                    # Correct the raw spot min up to the all-in import floor so
                    # the break-even basis matches what the user pays to recharge
                    # (no-op for all-in providers like Tibber). #531.
                    raw_min = min(prices)
                    floor = getattr(provider, "effective_import_floor", None)
                    import_forecast_min = (
                        floor(raw_min) if callable(floor) else raw_min
                    )
            except Exception:  # noqa: BLE001
                import_forecast_min = None
        return ArbitrageSignals(
            export_rate=export_rate,
            import_forecast_min=import_forecast_min,
            storable_surplus_w=max(0.0, surplus_w),
            storable=storable,
        )

    # ── VPP grid-event dispatch (#580) ───────────────────────────────

    def _snapshot_vpp_states(self) -> dict:
        """Raw states of the wired VPP entities (None when unset/missing)."""
        out = {}
        for cfg_key, name in (
            ("vpp_event_active_entity", "event_active"),
            ("vpp_direction_entity", "direction"),
            ("vpp_event_end_entity", "event_end"),
            ("vpp_pre_event_entity", "pre_event"),
        ):
            eid = self.config.get(cfg_key) or ""
            st = self.hass.states.get(eid) if eid else None
            out[name] = st.state if st is not None else None
        return out

    def _vpp_apply_battery_override(self, pbc: dict) -> dict:
        """Merge the per-cycle VPP battery override into one battery's view
        config (#580).

        The override rides the EXISTING manual-mode road in decide_battery:
        ``battery_mode=force_discharge`` (respects the reserve floor, falls
        to NORMAL at/below it) or ``force_charge`` (max accepted power). A
        battery the user set to ``off`` stays hands-off — the user's opt-out
        outranks the grid event. Reserve = max(user's per-battery reserve,
        ``vpp_reserve_soc``) so VPP can only tighten, never loosen, the
        floor. Returns a NEW dict; the input is never mutated."""
        override = getattr(self, "_vpp_battery_override", None)
        if not override:
            return pbc
        if str(pbc.get("battery_mode", "auto") or "auto").lower() == "off":
            return pbc
        merged = {**pbc, **override}
        if "battery_reserve_soc" in override:
            try:
                user_reserve = float(pbc.get("battery_reserve_soc") or 0.0)
            except (TypeError, ValueError):
                user_reserve = 0.0
            merged["battery_reserve_soc"] = max(
                float(override["battery_reserve_soc"]), user_reserve,
            )
        return merged

    async def _vpp_notify(self, message: str) -> None:
        """Event start/end notification via the existing helper (best-effort,
        honours the global mobile-notifications opt-in)."""
        if not self.config.get("enable_mobile_notifications", False):
            return
        try:
            await self._notification_manager._send_mobile_notification(
                message, group="sem_alerts",
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("VPP notification failed: %s", e)

    async def _run_vpp_dispatch(self, power, energy) -> None:
        """Per-cycle VPP evaluation + override plumbing (#580).

        Calls the pure core with (config, entity-state snapshot, battery
        SOC, now), advances the dispatcher (phase edges + per-event energy
        accounting), then sets the three per-cycle override flags the
        existing control paths consume:

        * ``_vpp_ev_override``      → ``_effective_charge_mode_for``
        * ``_vpp_battery_override`` → ``_vpp_apply_battery_override``
        * ``_vpp_shed_loads``       → surplus-controller peak posture

        Observer mode (default) leaves all three cleared — the decision is
        computed, logged, notified and published, but actuates NOTHING."""
        from .vpp_dispatch import VppDispatcher, evaluate_vpp

        # Reset per-cycle flags first — they must never survive a cycle in
        # which the evaluation didn't (re-)assert them.
        self._vpp_ev_override = None
        self._vpp_battery_override = None
        self._vpp_shed_loads = False

        if not bool(self.config.get("vpp_enabled", False)):
            self._vpp_publish = {"vpp_event": "idle",
                                 "vpp_event_observer": True}
            return

        if getattr(self, "_vpp_dispatcher", None) is None:
            stored = self._storage.get_vpp_events() if self._storage else []
            self._vpp_dispatcher = VppDispatcher(events=stored)

        now = dt_util.now()
        soc = getattr(power, "battery_soc", None)
        if getattr(power, "battery_soc_unavailable", False):
            soc = None
        decision = evaluate_vpp(
            self.config, self._snapshot_vpp_states(), soc, now,
        )
        # Belt: the GLOBAL observer mode outranks vpp_observer_mode — a
        # hands-off install must never actuate through the VPP road either
        # (2026-07-18 incident class: an unprotected reload window let a
        # non-observer VPP test reach the real inverter).
        if getattr(self, "_observer_mode", False) and not decision.observer:
            from dataclasses import replace as _dc_replace
            decision = _dc_replace(decision, observer=True)

        out = self._vpp_dispatcher.update(
            decision,
            grid_import_kwh=float(
                getattr(energy, "daily_grid_import", 0.0) or 0.0),
            grid_export_kwh=float(
                getattr(energy, "daily_grid_export", 0.0) or 0.0),
            now=now,
        )

        # ── per-cycle overrides (actuation) — observer mode sets none ──
        kinds = {a.kind for a in decision.actions}
        if not decision.observer:
            if "pause_ev" in kinds:
                self._vpp_ev_override = "pause"
            elif "boost_ev" in kinds:
                self._vpp_ev_override = "boost"
            if "force_discharge" in kinds:
                self._vpp_battery_override = {
                    "battery_mode": "force_discharge",
                    "battery_reserve_soc": float(
                        self.config.get("vpp_reserve_soc", 20) or 20),
                }
            elif "force_charge" in kinds:
                self._vpp_battery_override = {"battery_mode": "force_charge"}
            self._vpp_shed_loads = "shed_loads" in kinds

        # ── transition logging + notifications ─────────────────────────
        verb = "WOULD dispatch" if decision.observer else "dispatching"
        if out["transition"] == "start":
            plan = ", ".join(sorted(kinds)) or "nothing"
            msg = (f"VPP event started ({decision.direction}) — "
                   f"{verb}: {plan}")
            _LOGGER.info("%s :: %s", msg, decision.reason)
            await self._vpp_notify(msg)
        elif out["transition"] == "end":
            ev = out.get("event") or {}
            msg = (f"VPP event ended ({ev.get('direction')}) — delivered "
                   f"{float(ev.get('kwh', 0.0) or 0.0):.2f} kWh"
                   + (" (observer — not dispatched)" if ev.get("observer")
                      else ""))
            _LOGGER.info(msg)
            await self._vpp_notify(msg)
        elif out["transition"] == "boot_reconcile":
            _LOGGER.warning(
                "VPP: stale open event record closed on boot — a restart "
                "interrupted an event window (accounting reconciled; force "
                "ops are cleared by the battery adapters' normal teardown)"
            )
        # log each non-event phase transition once (pre_event / back to idle)
        prev_phase = getattr(self, "_vpp_prev_phase", "idle")
        if decision.phase != prev_phase and out["transition"] is None:
            _LOGGER.info(
                "VPP phase %s → %s — %s (%s)", prev_phase, decision.phase,
                verb, decision.reason,
            )
        self._vpp_prev_phase = decision.phase

        # gate-stuck sanity cap — warn once per stuck episode
        if decision.gate_stuck:
            if not getattr(self, "_vpp_stuck_warned", False):
                _LOGGER.warning("VPP: %s", decision.reason)
                self._vpp_stuck_warned = True
        else:
            self._vpp_stuck_warned = False

        # persist event history (energy store already delay-saves each cycle)
        if out["events_changed"] and self._storage:
            self._storage.set_vpp_events(self._vpp_dispatcher.events)

        self._vpp_publish = self._vpp_dispatcher.publish_state(decision)

    async def _run_charge_pacing(self, ledger, capacity_kwh: float) -> None:
        """(#820) One cycle of charge pacing: decide, maybe write, publish."""
        from .charge_pacing import ChargePacingWriter, paced_charge_cap_w
        if getattr(self, "_charge_pacing_writer", None) is None:
            self._charge_pacing_writer = ChargePacingWriter()
        soc = None
        try:
            soc = float(self.data.get("battery_soc"))
        except (TypeError, ValueError):
            soc = None
        pe = getattr(self, "_planning_evidence", {}) or {}
        trusted = pe.get("forecast_trust_d1") is not None
        enabled = bool(self.config.get("battery_charge_pacing_enabled", False))
        entity = str(self.config.get(
            "battery_charge_power_limit_entity") or "")
        if soc is None or capacity_kwh <= 0:
            decision = None
        else:
            decision = paced_charge_cap_w(
                ledger=ledger, capacity_kwh=capacity_kwh, soc_pct=soc,
                target_soc_pct=float(self.config.get(
                    "battery_max_target_soc", 95.0) or 95.0),
                forecast_trusted=trusted,
                inverter_ac_limit_w=float(self.config.get(
                    "inverter_ac_limit_w", 0.0) or 0.0),
                hw_max_charge_w=float(self.config.get(
                    "battery_max_charge_power_w", 5000.0) or 5000.0),
            )
        cap = decision.cap_w if (decision and enabled) else None
        action = await self._charge_pacing_writer.apply(
            self.hass, entity, cap, observer=self._observer_mode)
        self._charge_pacing_state = {
            "enabled": enabled,
            "cap_w": decision.cap_w if decision else None,
            "reason": decision.reason if decision else "no day model",
            "full_at": getattr(decision, "full_at", None) if decision else None,
            "action": action,
            "entity": entity or None,
        }

    async def _run_battery_pipeline(self, power, energy, charging_state) -> None:
        """Per-cycle battery control via decide_battery + actuate_battery.

        Replaces the legacy 7.5c + 7.5d hooks
        (``_apply_battery_discharge_protection`` from
        the deleted BatteryProtectionMixin (#624) + ``_execute_battery_charge_scheduler``)
        with the unified per-device-primary pipeline mirroring the EV
        side rebuild (PR #358).

        Pipeline (one iteration per battery in ``power.batteries``):
          1. (Re-)evaluate the scheduler if it's time (preserved verbatim
             from the legacy hook). Fires ONCE per cycle — the scheduler
             plans against the fleet, not per battery.
          2. For each battery_id in ``power.batteries`` (or a synthetic
             ``"primary"`` entry on legacy single-battery installs):
                a. Build a :class:`BatteryView` from per-battery runtime
                   + the shared scheduler decision + fleet context.
                b. ``decide_battery(view)`` → :class:`BatteryDecision`.
                c. ``actuate_battery(decision, adapter)`` invokes the
                   per-battery adapter.

        Adapters are cached per-battery in ``self._battery_adapters``
        (#375) — keyed by ``battery_id`` so brand-specific hysteresis
        state (``last_discharge_limit_w``) doesn't leak between
        batteries. Recreating each cycle would lose that state.

        Single-battery installs (the 99% case today) see exactly one
        loop iteration and the same actuation pattern as v1.7.0 —
        the only difference is the adapter cache is now a dict-of-one
        keyed by ``"primary"``.
        """
        from .actuate_battery import actuate_battery
        from .battery_adapters import adapter_for, _integration_loaded
        from .charger_types import (
            BatteryIntent, BatteryRuntime, BatteryView,
            FleetContext,
        )
        from .decide_battery import decide_battery, effective_battery_count

        # Per-battery adapter cache (#375 — was a single
        # ``self._battery_adapter``). Adapters carry the
        # ``last_discharge_limit_w`` hysteresis state, so they're
        # cached for the coordinator's lifetime.
        if not hasattr(self, "_battery_adapters"):
            self._battery_adapters: Dict[str, "BatteryControlAdapter"] = {}

        # 1. Trigger scheduler evaluation (preserve legacy schedule cycle)
        scheduler = self._battery_charge_scheduler
        if scheduler.enabled:
            try:
                await self._maybe_run_scheduler_evaluation(power, energy)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Battery scheduler evaluate failed: %s", e, exc_info=True,
                )

        scheduler_decision = (
            scheduler._decision if scheduler.enabled else None
        )


        # #523 export arbitrage — the scheduler's discharge mirror. Runs
        # whenever arbitrage is enabled (independent of the night-charge
        # scheduler), but NEVER while a charge is planned/active — the
        # battery can't sell and charge at once. When it fires, its
        # decision replaces the charge decision for this cycle and
        # decide_battery actuates it as FORCE_DISCHARGE. The signed export
        # price + cheapest upcoming import price (recharge cost basis) are
        # only looked up when arbitrage is on.
        _charge_active = (
            scheduler_decision is not None and scheduler_decision.should_charge
        )
        # #691: the LIMIT_DISCHARGE home split (and the C6 sell split) must
        # divide by the batteries that actually CONSUME the budget — a
        # mode=off battery never gets the clamp, and batteries sharing one
        # discharge-limit entity are a single actuation surface.
        _n_cfg = len(getattr(power, "batteries", {}) or {})
        _eff_battery_count = effective_battery_count(
            [self._per_battery_config(i, _n_cfg) for i in range(_n_cfg)]
        ) if _n_cfg else 1

        # Evaluate arbitrage ONLY when globally enabled. In v1.7.3 the global
        # toggle is forced off (#533) so this whole block is dormant — automatic
        # battery→grid arbitrage is deactivated for the stable release.
        #
        # (#638 one-gate C6) The per-battery ``allow_arbitrage`` opt-in scan
        # is real again — the v1.7.3 hardcode is gone. Every DEFAULT stays
        # dormant (#533 stands): no battery ships in allow_arbitrage mode and
        # the global toggle defaults off; a user must open the valve, and the
        # sell then fires only inside the plan's own sell block.
        _any_allow_arb = self._arbitrage_enabled(_n_cfg)
        # Market signals are computed ONCE here (#533) and carried on the
        # FleetContext below — single source of truth, no ad-hoc tariff/power
        # reads in the decision. ``None`` unless arbitrage is being evaluated
        # (the whole block is dormant while the toggle + _any_allow_arb are off).
        arb_signals = None
        if _any_allow_arb:
            arb_signals = self._compute_arbitrage_signals(power)
            # #531 charge-first: never sell while there's storable solar surplus
            # the battery could absorb — storing free solar avoids a future
            # ~retail import, worth far more than the export price.
            if arb_signals.storable:
                _LOGGER.debug(
                    "Arbitrage held: %0.0f W storable solar surplus — "
                    "charge-first (#531)", arb_signals.storable_surplus_w,
                )
        if arb_signals is not None and not _charge_active and not arb_signals.storable:
            try:
                _arb = scheduler.evaluate_arbitrage(
                    current_soc=float(getattr(power, "battery_soc", 0.0) or 0.0),
                    export_rate=arb_signals.export_rate,
                    import_forecast_min=arb_signals.import_forecast_min,
                    # Run the economic check when globally enabled OR any
                    # battery is in allow_arbitrage mode (#523); decide_battery
                    # gates per battery which units actually sell.
                    enabled_override=_any_allow_arb,
                )
                if _arb.state.value == "discharging_arbitrage":
                    scheduler_decision = _arb
                else:
                    # #531: arbitrage evaluated but isn't selling this cycle.
                    # Propagate its non-firing verdict so decide_battery emits
                    # an explicit STOP rather than falling back to a possibly
                    # stale night decision — BUT never override an active or
                    # planned night charge (scheduled / should_charge), which
                    # owns this channel while it's running.
                    _night = scheduler_decision
                    _night_state = getattr(
                        getattr(_night, "state", None), "value", None
                    )
                    _night_charging = _night is not None and (
                        bool(getattr(_night, "should_charge", False))
                        or _night_state == "scheduled"
                    )
                    if not _night_charging and _arb.state.value in (
                        "not_profitable", "not_needed",
                    ):
                        scheduler_decision = _arb
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Export arbitrage evaluate failed: %s", e)

        # (#638 C6) The plan's WHEN for the arbitrage sell, computed once
        # per cycle and fleet-split — decide_battery receives the per-
        # battery share (the #531/#691 treatment).
        #
        # (#758) Behind the same kill switch as every other plan-driven
        # action. ``_energy_plan_gate`` opens with "actuation off" when
        # the switch is down; this gate reached the plan directly, so a user
        # who turned night actuation off still had the plan discharging the
        # battery to the grid. A kill switch that some callers ask is not a
        # kill switch.
        _sell_in, _sell_total_w = False, 0.0
        if getattr(self, "_energy_plan_actuation", False):
            from .energy_plan_actuation import arbitrage_sell_gate
            _sell_in, _sell_total_w = arbitrage_sell_gate(
                getattr(self, "_energy_plan_shadow", None), dt_util.now())
        _arb_sell = (_sell_in, _sell_total_w / max(1, _eff_battery_count))

        # Shared fleet context — same for every battery this cycle.
        fleet = FleetContext(
            solar_w=float(getattr(power, "solar_power", 0.0) or 0.0),
            home_w=float(getattr(power, "home_consumption_power", 0.0) or 0.0),
            battery_soc=float(getattr(power, "battery_soc", 0.0) or 0.0),
            is_night=self.time_manager.is_night_mode(),
            # #531: split per-battery LIMIT_DISCHARGE across the real fleet
            # (#691: effective consumers, not configured rows).
            battery_count=_eff_battery_count,
            # Solar gate for the unified discharge clamp (decide_battery):
            # below this much pure solar surplus the battery is off-limits
            # to the EV in any mode/time (0 = always allow).
            battery_assist_min_surplus_w=float(
                self.config.get("battery_assist_min_surplus", 1200)
            ),
            # Buffer SoC = the self-consumption reserve floor. Below it the
            # battery is off-limits to the EV in EVERY zone (the discharge
            # clamp keys on it so Zone 1/2 protect the battery regardless of
            # surplus — the surplus gate alone left it draining below buffer).
            buffer_soc=float(self.config.get("battery_buffer_soc", 70)),
            # #533: arbitrage market signals, computed once above (None unless
            # arbitrage is being evaluated → dormant until v1.7.4).
            arbitrage=arb_signals,
        )

        # 2. Source per-battery iteration. Multi-battery installs
        # populate ``power.batteries`` from the Energy Dashboard's
        # battery_power_list (multi-meter setup). Single-battery
        # installs leave it empty and we fall back to a synthetic
        # ``"primary"`` entry built from the fleet sensors — identical
        # behaviour to v1.7.0.
        battery_items: list[tuple[str, BatteryRuntime]] = []
        if power.batteries:
            for battery_id, bp in power.batteries.items():
                battery_items.append((battery_id, BatteryRuntime(
                    battery_id=battery_id,
                    last_known_soc=float(bp.soc_pct or 0.0),
                    last_known_w=float(bp.power_w or 0.0),
                    capacity_kwh=float(
                        bp.capacity_kwh
                        or self.config.get("battery_capacity_kwh", 0.0)
                    ),
                    available=True,  # populated → it reported this cycle
                    name=bp.name or battery_id,
                )))
        else:
            # Legacy single-battery fallback — synthesise one runtime.
            battery_items.append(("primary", BatteryRuntime(
                battery_id="primary",
                last_known_soc=float(getattr(power, "battery_soc", 0.0) or 0.0),
                last_known_w=float(getattr(power, "battery_power", 0.0) or 0.0),
                capacity_kwh=float(self.config.get("battery_capacity_kwh", 0.0)),
                available=not bool(
                    getattr(power, "battery_soc_unavailable", False)
                ),
            )))

        # #523: reset the per-cycle "selling to grid" flag; set it below
        # if any battery is commanded to FORCE_DISCHARGE this cycle.
        self._battery_arbitrage_active = False

        # #531: live battery count gates the global-mode fall-through in
        # _per_battery_config (single→multi bleed fix).
        _bat_count = len(battery_items)

        for batt_idx, (battery_id, runtime) in enumerate(battery_items):
            # Per-battery adapter cache. Each battery gets its OWN control
            # entities when configured (#523 multi-battery — RienduPre's
            # 2-battery setup), so both units can sell to grid / be limited
            # independently. Falls back to the global single-entity keys.
            adapter = self._battery_adapters.get(battery_id)
            if adapter is None:
                # #709: runtime context — injects the persistent Deye snapshot
                # store + config-entry/battery scope at build time (never part of
                # entry data/options, and never for non-Deye brands).
                _pbc = self._battery_adapter_context(battery_id, batt_idx, _bat_count)
                self._warn_battery_entity_collision(battery_id, _pbc)
                adapter = adapter_for(self.hass, _pbc)
                # H2 (review): share one orphan-stop guard across the fleet so a
                # multi-battery setup behind one inverter issues a single
                # stop_forcible_charge per device on restart (#532).
                if hasattr(adapter, "_orphan_guard"):
                    if not hasattr(self, "_battery_orphan_guard"):
                        self._battery_orphan_guard = {}
                    adapter._orphan_guard = self._battery_orphan_guard
                self._battery_adapters[battery_id] = adapter
                # (#764) Startup recovery is a real write — the #532
                # orphan-stop that saved a LUNA2000 from draining to grid.
                # Building the adapter under observer is fine (reads only);
                # recovering is not. The shadow stays a shadow.
                if not self._observer_mode:
                    recovered = await adapter.async_recover_pending()
                    if not recovered:
                        _LOGGER.warning(
                            "Battery %s: startup recovery blocked active control: %s",
                            battery_id, getattr(adapter, "last_error", "unknown error"),
                        )
                _LOGGER.info(
                    "Battery %s: %s (forced-discharge support=%s)",
                    battery_id, type(adapter).__name__,
                    getattr(adapter, "supports_forced_discharge", "n/a"),
                )
            elif type(adapter).__name__ == "GenericBatteryAdapter":
                # Self-heal a startup race: the brand integration (e.g.
                # huawei_solar) can finish loading AFTER SEM's first battery
                # cycle, so the cached adapter is a Generic fallback for a
                # battery that's really a Huawei/GoodWe. Re-detect once a
                # brand integration is actually loaded and upgrade in place
                # (cheap: only while still Generic + a brand entry exists).
                # #531: never self-heal a battery that has its OWN AC-coupled
                # control surface (strategy select / bidirectional setpoint —
                # e.g. a Sessy b2 in a Huawei fleet). adapter_for() now keeps
                # those Generic, but skip the per-cycle rebuild entirely so a
                # mixed-brand fleet doesn't churn an adapter that can't change.
                _heal_cfg = self._per_battery_config(batt_idx, _bat_count)
                _ac_coupled = bool(
                    _heal_cfg.get("battery_strategy_control_entity")
                    or _heal_cfg.get("battery_setpoint_bidirectional")
                )
                if not _ac_coupled and (
                    _integration_loaded(self.hass, "huawei_solar")
                    or _integration_loaded(self.hass, "goodwe")
                ):
                    _rebuilt = adapter_for(self.hass, _heal_cfg)
                    if type(_rebuilt).__name__ != "GenericBatteryAdapter":
                        adapter = _rebuilt
                        if hasattr(adapter, "_orphan_guard"):
                            if not hasattr(self, "_battery_orphan_guard"):
                                self._battery_orphan_guard = {}
                            adapter._orphan_guard = self._battery_orphan_guard
                        self._battery_adapters[battery_id] = adapter
                        _LOGGER.info(
                            "Battery %s: upgraded GenericBatteryAdapter → %s "
                            "(brand integration finished loading)",
                            battery_id, type(adapter).__name__,
                        )

            view = BatteryView(
                runtime=runtime,
                config=self._vpp_apply_battery_override(
                    self._per_battery_config(batt_idx, _bat_count)
                ),
                fleet=fleet,
                charging_state=getattr(charging_state, "value", str(charging_state)),
                ev_charging=bool(getattr(power, "ev_charging", False)),
                # (#778) The forecast budget and its dynamic floor. Both
                # come from the single published computation, so the export
                # decision cannot drift from the number the user was shown.
                battery_spendable_kwh=float(
                    (getattr(self, "_planning_evidence", None) or {})
                    .get("battery_spendable_kwh") or 0.0),
                forecast_spending_enabled=bool(
                    self.config.get("forecast_spending_enabled", False)),
                # (#778) The permission axis, resolved from the per-battery
                # config so a multi-battery install can grant export on one
                # pack and withhold it on another.
                battery_permissions=(
                    self._per_battery_config(batt_idx, _bat_count).get(
                        "battery_permissions")
                    or self.config.get("battery_permissions")),
                dynamic_floor_pct=(
                    getattr(self, "_planning_evidence", None) or {}
                ).get("battery_dynamic_floor_pct"),
                # Same operational gate as the charging context: a legacy flat
                # sensor with no registered charger must not make the battery
                # hold discharge protection for a phantom EV.
                ev_connected=operational_ev_connected(
                    self._ev_devices, getattr(power, "ev_connected", False)
                ),
                home_consumption_w=float(
                    getattr(power, "home_consumption_power", 0.0) or 0.0
                ),
                scheduler_decision=scheduler_decision,
                grid_funded_load_w=self._surplus_controller.grid_funded_draw_w(),
                # (#638 one-gate C4) the joint plan's WHEN for the battery
                # demand — same helper, same coverage log as every consumer.
                plan_gate=self._energy_plan_gate("battery"),
                # (#638 one-gate C6) the plan's WHEN for the sell, pre-split.
                arbitrage_sell=_arb_sell,
            )

            # 3. Decide
            decision = decide_battery(view)
            # (#762) transition-gated: 1423 identical lines per steady
            # day on .175. An unchanged intent is silent; every change
            # (and each edge of a flap) logs.
            log_on_change(
                _LOGGER, f"decide_battery:{battery_id}", logging.DEBUG,
                "decide_battery(%s) → intent=%s :: %s",
                battery_id, decision.intent.value, decision.reason,
            )
            # Capture the last decision per battery for diagnostics (#523) —
            # "is the EV draining the battery?" is answerable in one line.
            if not hasattr(self, "_last_battery_decisions"):
                self._last_battery_decisions = {}
            self._last_battery_decisions[battery_id] = {
                "intent": decision.intent.value,
                "reason": decision.reason,
                "mode": (view.config or {}).get("battery_mode", "auto"),
                "soc": getattr(runtime, "last_known_soc", None),
                "adapter": type(adapter).__name__,
                "supports_forced_discharge": getattr(
                    adapter, "supports_forced_discharge", None),
            }
            if decision.intent is BatteryIntent.FORCE_DISCHARGE:
                self._battery_arbitrage_active = True

            # 4. Actuate (#764: observer cuts here, inside the actuator)
            await actuate_battery(
                decision, adapter,
                observer=self._observer_mode,
                controller=self._surplus_controller,
                # (#818) same signal the charger side uses
                inputs_degraded=bool(
                    getattr(power, "inputs_degraded", False)),
            )

        # Reset scheduler when night ends — preserved from legacy
        if (scheduler.enabled
                and not self.time_manager.is_night_mode()
                and scheduler.state.value not in ("idle", "not_needed", "not_profitable")):
            scheduler.reset()

    async def _maybe_run_scheduler_evaluation(self, power, energy=None) -> None:
        """Trigger the scheduler's ``evaluate()`` at the daily time.

        Pure port of the daily-evaluation branch in the legacy
        ``_execute_battery_charge_scheduler``. The scheduler's
        ``evaluate()`` is itself a pure function; we just gather its
        inputs the same way the legacy hook did.
        """
        scheduler = self._battery_charge_scheduler
        now = dt_util.now()

        if not scheduler.should_trigger_evaluation(now):
            # Check for re-plan trigger (price update / SOC drift / EV change).
            # Operationally gated: a phantom EV (legacy sensor, no registered
            # charger) must not force scheduler re-plans either.
            ev_connected = operational_ev_connected(
                self._ev_devices, getattr(power, "ev_connected", False)
            )
            price_fp = None
            # Only worth computing when the scheduler holds a
            # fingerprint to compare against (#485 F2) — before the
            # first evaluation (or while a re-plan is already armed)
            # the comparison can't fire.
            if (
                getattr(scheduler, "has_price_fingerprint", False)
                and hasattr(self._tariff_provider, "price_series_fingerprint")
            ):
                price_fp = self._tariff_provider.price_series_fingerprint()
            if scheduler.should_replan(
                power.battery_soc, ev_connected, price_fingerprint=price_fp,
            ):
                scheduler._last_evaluation_date = None
                _LOGGER.info(
                    "Battery scheduler: re-plan triggered, will re-evaluate"
                )
            return

        # (#819) Re-apply the chosen source each cycle so changing it on
        # the card takes effect without reloading the entry. Idempotent
        # when unchanged, so this is a dict lookup on a normal cycle.
        self._forecast_reader.set_preferred_source(
            self.config.get("solar_forecast_source"))
        forecast = self._forecast_reader.read_forecast()
        # Rolling horizon: evaluations after midnight plan for
        # *today's* solar day; the evening evaluation plans for tomorrow.
        forecast_tomorrow = 0.0
        if forecast.available:
            forecast_tomorrow = (
                forecast.forecast_today_kwh
                if now.hour < 12
                else forecast.forecast_tomorrow_kwh
            )
        forecast_age = 0.0
        if hasattr(forecast, "last_update") and forecast.last_update:
            forecast_age = (now - forecast.last_update).total_seconds() / 3600

        correction = self._forecast_tracker.correction_factor

        expected_consumption = self._predictor.predict_consumption_today_kwh(now)
        if expected_consumption <= 0:
            expected_consumption = 12.0

        # Break-even rates: derive from the actual day-ahead series.
        # The legacy code sampled get_price_at(today 02:00 / 14:00) — both
        # already in the past at the 21:00 trigger, so dynamic tariffs fed
        # the break-even with stale morning prices (or None once the slots
        # rolled off, crashing the scheduler's division).
        off_peak_rate = None
        peak_rate = None
        if hasattr(self._tariff_provider, "get_charge_window_rate"):
            off_peak_rate = self._tariff_provider.get_charge_window_rate(
                hours=4.0, within_hours=12,
            )
        if hasattr(self._tariff_provider, "get_next_daytime_rate"):
            peak_rate = self._tariff_provider.get_next_daytime_rate()
        if off_peak_rate is None and hasattr(self._tariff_provider, "get_price_at"):
            # Static rule-based providers price purely by time-of-day, so
            # the date does not matter; dynamic providers without data
            # return None and fall through to the config rates.
            off_peak_rate = self._tariff_provider.get_price_at(
                now.replace(hour=2, minute=0)
            )
        if peak_rate is None and hasattr(self._tariff_provider, "get_price_at"):
            peak_rate = self._tariff_provider.get_price_at(
                now.replace(hour=14, minute=0)
            )
        if off_peak_rate is None:
            off_peak_rate = _cfg_rate(
                self.config, "electricity_off_peak_rate", "electricity_nt_rate",
                default=0.22,
            )
        if peak_rate is None:
            peak_rate = self.config.get("electricity_import_rate", 0.30)

        current_price = 0.0
        if hasattr(self._tariff_provider, "get_current_import_rate"):
            current_price = self._tariff_provider.get_current_import_rate()

        # (#638 one-gate C4) The phantom EV co-model is gone with the
        # scheduler's window pick (#652's model dies here): the joint plan
        # carries the real per-charger demands, so the scheduler needs
        # neither an EV estimate nor the tariff's cheap hours — the
        # provider is still handed over for the price fingerprint that
        # drives its replan trigger.
        scheduler.evaluate(
            current_soc=power.battery_soc,
            forecast_tomorrow_kwh=forecast_tomorrow,
            expected_consumption_kwh=expected_consumption,
            off_peak_rate=off_peak_rate,
            peak_rate=peak_rate,
            tariff_provider=self._tariff_provider,
            correction_factor=correction,
            forecast_available=forecast.available,
            forecast_age_hours=forecast_age,
            current_price=current_price,
        )

        # (#638 G3) SHADOW: the joint energy plan, computed + logged next
        # to the reactive planners it replaced.
        self._shadow_energy_plan(scheduler, energy, power)

    def _ev_blocks_for(self, cid: str, now=None) -> "Optional[list]":
        """(#742) THIS charger's blocks from the stamped plan — only when
        the gate covers the demand. The today-strip's rows come from these;
        None keeps the composer's reactive fallback."""
        gate = self._energy_plan_gate(f"ev:{cid}", now)
        if not getattr(gate, "covered", False):
            return None
        plan = getattr(self, "_energy_plan_shadow", None)
        if not isinstance(plan, dict):
            return None
        blocks = [b for b in (plan.get("blocks") or [])
                  if b.get("id") == f"ev:{cid}"]
        return blocks or None

    def _plan_coverage_view(self) -> dict:
        """(#638 C7) The per-demand verdict map, user-shaped: ``covered``
        or the gate's named doubt. The card renders this as the
        "reactive — why" chip — the user-facing twin of the
        ``#638 coverage`` log line.

        EVALUATED per publish, never replayed. ``_plan_coverage_seen`` is
        the transition log's memory — a demand is written there only when
        somebody ASKS its gate, and the load gates are asked from
        ``_energy_plan_load_windows``, which returns early with actuation off
        or nothing stamped. Replaying that memory as a live view therefore
        showed the answer from before the kill-switch: on .175 (15.08) the
        EV row read ``actuation off`` while a load still read ``covered``
        — the one surface a user checks to see the kill-switch took hold,
        contradicting the kill-switch. The gate is pure and cheap, so the
        view asks it rather than remembering it.
        """
        seen = getattr(self, "_plan_coverage_seen", None) or {}
        if not seen:
            return {}
        now = dt_util.now()
        out = {}
        for demand_id in list(seen):
            # No try/except here on purpose: ``plan_gate`` is total (every
            # doubt has a named reason, nothing raises), and a swallowed
            # error would silently BLANK the row — the same "the card
            # doesn't say" failure this method exists to fix.
            gate = self._plan_gate_now(str(demand_id), now)
            out[str(demand_id)] = "covered" if gate.covered else (
                str(gate.reason) or "uncovered")
        return out

    def _plan_gate_now(self, demand_id: str, now=None):
        """THE verdict for one demand — the kill-switch rule included.

        The single evaluator behind both consumers: ``_energy_plan_gate``
        (which logs transitions) and ``_plan_coverage_view`` (which renders).
        Two copies of "is actuation on?" is precisely how the log line and
        the card came to disagree.
        """
        from .energy_plan_actuation import PlanGate, plan_gate
        if not getattr(self, "_energy_plan_actuation", False):
            return PlanGate(reason="actuation off")
        return plan_gate(getattr(self, "_energy_plan_shadow", None),
                         demand_id, now or dt_util.now())

    def _energy_plan_gate(self, demand_id: str, now=None):
        """(#638 G4) The trust-rule verdict for one demand against tonight's
        stamped plan. UNCOVERED (→ callers change nothing) whenever actuation
        is off, no plan is stamped, the plan is stale/out-of-span, or this
        demand's verdict is not ``fits`` — see energy_plan_actuation.plan_gate.

        (audit 2026-08-11) Every verdict CHANGE is logged with its reason —
        the one line that says which layer drove a demand's night. Without
        it the fail-open fallback is invisible in every soak artifact."""
        from .energy_plan_actuation import coverage_transition
        gate = self._plan_gate_now(demand_id, now)
        seen = getattr(self, "_plan_coverage_seen", None)
        if seen is None:
            seen = self._plan_coverage_seen = {}
        msg = coverage_transition(seen, demand_id, gate)
        if msg:
            _LOGGER.info("#638 coverage: %s", msg)
        return gate

    def _plan_ev_connected(self, cid: str, charger_cfg, power):
        """(#638) THE plan layer's answer to "is this car connected?".

        Tri-state, same contract as ``plan_connectivity``: True / False /
        ``None`` (nothing to ask). One accessor, so the demand collector and
        the demand signature cannot answer differently — an AST ratchet
        pins it as the only caller of ``plan_connectivity`` here.

        The NO needs no second-guessing at this layer: ``power`` arrives
        already CONFIRMED (``_confirm_ev_connection``, step 1 of the cycle),
        so a UDP-polled charger's missed poll never reaches the planner as
        an unplug. Before that filter existed, one blip restamped the night
        with the EV dropped and the blip clearing restamped it back — two
        restamps and a window where the plan said "no car tonight", against
        #638's ≤1 stop/start per device.
        """
        from .ev_availability import plan_connectivity
        return plan_connectivity(cid, charger_cfg, self.config, power)

    def _plan_car_full(self, cid: str, power):
        """(#756) THE plan layer's answer to "is this car full?".

        Tri-state, same contract as ``_plan_ev_connected``: ``True`` (skip
        the demand) or ``None`` (nothing to ask → plan it). One accessor,
        so the demand collector and the demand signature cannot answer
        differently — answering differently is exactly what flipped the
        night on N2: the signature restamped because the car had "filled
        up", and the collector then built the new plan without it.

        Two readings, one question: the taper detector's anchor and THIS
        charger's draw (``_charger_power_w``, the canonical per-charger
        read) against the charger's own handshake threshold.
        """
        from .ev_availability import plan_car_fullness
        detector = (getattr(self, "_ev_taper_detectors", None) or {}).get(cid)
        if detector is None:
            return None
        drawing_w = None
        if power is not None:
            try:
                drawing_w = self._charger_power_w(cid, power)
            except Exception:  # noqa: BLE001 — no meter opinion, use the anchor
                drawing_w = None
        adapter = (getattr(self, "_charger_adapters", None) or {}).get(cid)
        handshake_w = float(getattr(adapter, "handshake_power_w", 500.0) or 500.0)
        return plan_car_fullness(detector, drawing_w=drawing_w,
                                 handshake_w=handshake_w)

    def _energy_plan_demand_signature(self, power, energy=None) -> tuple:
        """(#638) What the night is being ASKED for, as a comparable value.

        The stamp is once per night; this is how it learns the night changed
        underneath it. #638 specified the re-plan triggers as "price update,
        floor change, unplug, big deviation" — only unplug shipped, so on
        armed night 1 the EV target went 3.5 → 6.0 kWh at 22:19 and the
        ledger kept describing the old night while execution correctly
        followed the new floor.

        Deliberately COARSE: floors are rounded to 0.1 kWh and prices to the
        cent, so sensor jitter cannot re-plan the night every cycle — only a
        real change of the ask does. Anything unreadable degrades to a
        constant rather than raising, because a signature that throws would
        take the whole trigger down with it.
        """
        sig: list = []
        # 0. The collector's own gates, mirrored (round 4, 15.08). #759's
        #    rule — watch what the plan READS — has three more instances,
        #    and the collector names them: it stops at the charge MODE
        #    before it asks the plug or the car, and at the load's control
        #    MODE (then night-eligibility) before it asks the deficit or
        #    the room. A term past a closed gate is unread, so it can only
        #    restamp a plan that cannot change: live on .175 the mode sat
        #    at ``off``, the shared KEBA's plug flickered one cycle, and
        #    the night restamped TWICE with byte-identical output.
        #    Unevaluable gates fail VISIBLE (include the term) — the same
        #    direction the collector takes, for the same reason.
        from ..devices.base import DeviceControlMode as _DCM_SIG
        _cfgs = {str(c.get("id") or ""): c
                 for c in (self.config.get("ev_chargers") or [])}

        def _night_ok(cid: str) -> bool:
            """This charger's mode gate — ``off``, and #634's floorless
            ``solar_only``, never reach the plug/car questions."""
            try:
                return bool(self._mode_allows_night_charging(_cfgs.get(cid) or {}))
            except Exception:  # noqa: BLE001
                return True

        def _sem_may_switch(dev) -> bool:
            """The load/comfort collectors' first gate: SURPLUS only."""
            try:
                return getattr(dev, "control_mode",
                               _DCM_SIG.SURPLUS) == _DCM_SIG.SURPLUS
            except Exception:  # noqa: BLE001
                return True

        def _night_may_serve(dev) -> bool:
            """The load collector's ``day_only`` gate."""
            try:
                return bool(getattr(dev, "battery_eligible_overnight", False)
                            or getattr(dev, "top_up_policy", "") == "cheap_hours")
            except Exception:  # noqa: BLE001
                return True

        # 1. Connection — the original trigger, per-charger when available.
        #    ``power`` is the cycle's CONFIRMED plug answer
        #    (``_confirm_ev_connection``), so a UDP-polled charger's missed
        #    poll cannot restamp the night: the blip family arriving in the
        #    planner is what #753/N2-15.08 caught.
        _pc = getattr(power, "ev_connected_per_charger", None) or {}
        _fleet = bool(getattr(power, "ev_connected", False))
        _conn = tuple(sorted(
            (str(k), bool(self._plan_ev_connected(
                str(k), _cfgs.get(str(k)) or {}, power)))
            for k in _pc if _night_ok(str(k))
        ))
        if not _conn and not _pc and (not _cfgs or any(_night_ok(c) for c in _cfgs)):
            # No per-charger map at all: the fleet flag is the only answer
            # there is — but not on an install whose every charger has
            # opted out, where nobody reads it either.
            _conn = (("fleet", _fleet),)
        sig.append(("conn", _conn))
        # 2. Per-charger ask: floor, deadline, mode — and whether the car
        #    is still full (#756). Anchoring full happens mid-night with
        #    the plug still in; nothing else here moves, so without this
        #    term the stamped plan keeps its phantom EV blocks until an
        #    unrelated trigger fires.
        for cfg in (self.config.get("ev_chargers") or []):
            try:
                cid = str(cfg.get("id") or "")
                # The car-full question sits BELOW the mode gate in the
                # collector, so an opted-out charger's taper anchor is
                # unread — the knobs above stay, they are the opt-in.
                _full = bool(self._plan_car_full(cid, power)) if _night_ok(cid) else False
                sig.append((
                    "ev", cid,
                    round(float(cfg.get("daily_ev_target") or 0.0), 1),
                    str(cfg.get("ev_target_time") or ""),
                    str(cfg.get("charge_mode") or ""),
                    _full,
                ))
            except Exception:  # noqa: BLE001 — one odd charger cfg is not fatal
                continue
        # 3. Each load's remaining runtime deficit — the loads' equivalent of
        #    a floor. Rounded to 6-minute steps: a deficit shrinks every
        #    cycle while a device runs, and that is NOT a demand change.
        #    The stop flag (#760) is a demand-set input: the collector skips
        #    a stopped load, so the stop clearing mid-night (the room cooled
        #    back into the band) must re-plan to re-admit it.
        controller = getattr(self, "_surplus_controller", None)
        for dev in (controller.get_devices_sorted() if controller else []):
            try:
                if not getattr(dev, "has_runtime_deficit", False):
                    continue
                if not (_sem_may_switch(dev) and _night_may_serve(dev)):
                    continue  # the collector left it out before the deficit
                deficit_h = max(0.0, (dev.daily_min_runtime_sec
                                      - dev._daily_runtime_accumulated_sec) / 3600.0)
                sig.append(("load", str(dev.device_id), round(deficit_h * 10) / 10,
                            bool(getattr(dev, "stop_condition_met", False))))
            except Exception:  # noqa: BLE001
                continue
        # 4. Each engaged band's plannable ask (#638 Phase 3) — a comfort
        #    demand appearing or materially changing re-plans the day.
        #    Deliberately COARSE like the rest: kWh in 0.5 steps, the
        #    deadline in 30-min steps — a drifting thermometer must not
        #    re-plan every cycle.
        try:
            _now_sig = dt_util.now()
            for dev in (controller.get_devices_sorted() if controller else []):
                try:
                    if not _sem_may_switch(dev):
                        continue  # the band of a device SEM may not switch
                    _fn = getattr(dev, "comfort_plan_demand", None)
                    ask = _fn(_now_sig) if callable(_fn) else None
                    if not ask:
                        continue
                    sig.append((
                        "comfort", str(dev.device_id),
                        round(float(ask["energy_kwh"]) * 2) / 2,
                        int(ask["deadline"].timestamp() // 1800),
                    ))
                except Exception:  # noqa: BLE001 — one band, not the trigger
                    continue
        except Exception:  # noqa: BLE001
            pass
        # 5. The SUPPLY side (the week picture, 2026-08-08): the day's
        #    free energy is a forecast that revises through the morning
        #    — Aug 6 was a 34-kWh day a dawn stamp would have priced at
        #    ~55, and nothing on the ask side would have re-planned it.
        #
        #    The term watches what the PLAN READS: the hours still AHEAD
        #    (``forecast_remaining_today_kwh``) and TOMORROW's day (the
        #    sunrise floor, and the room arbitrage may buy into). It used
        #    to watch the day TOTAL — a number the builder consumes
        #    nowhere. With dampening live (.175, 15.08) the total is
        #    rewritten every ~30 min as the correction re-prices hours
        #    ALREADY PRODUCED: 11 restamps in 7.3 h, one of which
        #    (16:42:05, 42 → 38 kWh) rebuilt byte-identical blocks. A
        #    retrospective correction is not news about the night.
        #
        #    The remaining does burn down every daylight minute, and that
        #    is time passing rather than the ask changing — so measured
        #    production EXPLAINS the decay: expected = anchored remaining
        #    − what has been produced since the anchor. Only the gap
        #    between expectation and reality (clouds, a real revision)
        #    re-anchors. Without a production reading the expectation is
        #    flat and the plain #759 deadband applies — never worse than
        #    before, which is also how a frozen counter (#681) degrades.
        try:
            _fd = getattr(getattr(self, "_forecast_reader", None),
                          "forecast_data", None)
            _rem = float(getattr(_fd, "forecast_remaining_today_kwh", 0.0)
                         or 0.0)
            _tom = float(getattr(_fd, "forecast_tomorrow_kwh", 0.0) or 0.0)
            _made = getattr(energy, "daily_solar", None)
            _made = (float(_made) if isinstance(_made, (int, float))
                     and not isinstance(_made, bool) else None)
            # (#759) Quantizing alone cannot damp a value that LIVES at a
            # bucket edge: on N1 the dampened forecast wobbled 66.9↔67.1
            # around the 67 boundary, the rounding turned that into 66↔68,
            # and every flip was a full replan — coverage changed hands
            # every 20 s and no load could start under it. So the term is
            # computed from an ANCHOR that only moves when reality has
            # left the expectation by ≥ 3 kWh (1.5 buckets): jitter orbits
            # the anchor forever, a real revision re-anchors once.
            _a = getattr(self, "_sig_solar_anchor", None)
            if not (isinstance(_a, tuple) and len(_a) == 2):
                _a = None          # a pre-#759 float anchor: start over
            if _a is None:
                _expected = None
            else:
                _a_rem, _a_made = _a
                _expected = (max(0.0, _a_rem - max(0.0, _made - _a_made))
                             if _made is not None and _a_made is not None
                             else _a_rem)
            if _expected is None or abs(_rem - _expected) >= 3.0:
                self._sig_solar_anchor = _a = (_rem, _made)
            sig.append(("solar", round(_a[0] / 2.0) * 2.0))
            _at = getattr(self, "_sig_solar_anchor_tomorrow", None)
            if _at is None or abs(_tom - _at) >= 3.0:
                self._sig_solar_anchor_tomorrow = _at = _tom
            sig.append(("solar_tomorrow", round(_at / 2.0) * 2.0))
        except Exception:  # noqa: BLE001 — no forecast is a valid shape
            # A transient read failure keeps the anchors: flipping to 0.0
            # and back would be two replans for one hiccup (#759).
            _a = getattr(self, "_sig_solar_anchor", None)
            _a_rem = _a[0] if isinstance(_a, tuple) and len(_a) == 2 else None
            sig.append(("solar",
                        round(_a_rem / 2.0) * 2.0 if _a_rem is not None
                        else 0.0))
            _at = getattr(self, "_sig_solar_anchor_tomorrow", None)
            sig.append(("solar_tomorrow",
                        round(_at / 2.0) * 2.0 if _at is not None else 0.0))
        # 6. The night's price curve — a provider publishing tomorrow's
        #    prices mid-evening changes where everything should go.
        try:
            ups = getattr(
                self._tariff_provider.get_tariff_data(), "upcoming_prices", None
            ) or []
            # 96 entries: a full day even on a 15-min market (48 was
            # only 12 h there — tomorrow's curve landing late missed it).
            # (#765) ABSOLUTE keys, not window order: the upcoming window
            # slides every hour, and fingerprinting its contents by
            # position made a past slot dropping off read as "the night
            # changed" — 10 restamps in one N2 night with prices at
            # absolute timestamps identical throughout. Pairs of
            # (timestamp, price) let demand_signature_changed apply the
            # one rule that matters; index keys are the fallback for
            # providers whose points carry no timestamp.
            sig.append(("price", tuple(
                ((p.timestamp.isoformat()
                  if getattr(p, "timestamp", None) is not None else i),
                 round(float(p.price), 2))
                for i, p in enumerate(ups[:96])
                if getattr(p, "price", None) is not None
            )))
        except Exception:  # noqa: BLE001 — no tariff is a valid shape
            sig.append(("price", ()))
        return tuple(sig)

    def _energy_plan_load_windows(self, devices) -> dict:
        """(#638 G4) Per-device window verdicts for this cycle's surplus
        update: device_id → True/False for loads the plan covers; devices
        the plan has no say over are simply absent. Empty dict when
        actuation is off or nothing is stamped — the controller then
        behaves exactly as before G4."""
        windows: dict = {}
        if not getattr(self, "_energy_plan_actuation", False):
            return windows
        if not isinstance(getattr(self, "_energy_plan_shadow", None), dict):
            return windows
        from .energy_plan_actuation import merge_load_gates
        now = dt_util.now()
        for dev in devices:
            try:
                did = dev.device_id
                # (#638 C5) A device can carry TWO demands — its runtime
                # deficit (load:) and its comfort banking ask (comfort:).
                # The collector used to ask only load:, so a comfort block
                # could never reach its device. merge_load_gates carries
                # the rules; absence == no say, exactly as before.
                deficit_kwh = (max(0.0, float(getattr(dev, "daily_min_runtime_sec", 0) or 0)
                                   - float(getattr(dev, "_daily_runtime_accumulated_sec", 0) or 0))
                               / 3600.0
                               * float(getattr(dev, "rated_power", 0.0) or 0.0) / 1000.0)
                verdict = merge_load_gates(
                    self._energy_plan_gate(f"load:{did}", now),
                    self._energy_plan_gate(f"comfort:{did}", now),
                    deficit_kwh=deficit_kwh)
                if verdict is not None:
                    windows[did] = verdict
            except Exception:  # noqa: BLE001 — one odd device won't gate the rest
                continue
        return windows

    def _record_demand_outcomes(self, now, power) -> None:
        """(#755 pillar 1) Write down what each planned demand actually DID.

        The plan has always recorded two of the three numbers that matter —
        what a demand ASKED for and what the packer PROMISED it. The third was
        never written, so "fits" was a claim nobody checked, the morning report
        had nothing to compare, and a learning layer would have nothing to
        read.

        Called once per cycle after the decisions are taken. The night is keyed
        on ``_shadow_plan_date`` (the stamped energy day), NOT on the plan's
        ``computed_at``: a re-stamp because the ask changed is the SAME night
        and must keep the record it has accumulated so far.

        Every sample carries whether it was MEASURED (see ``demand_outcome``'s
        draw helpers). Nothing downstream re-decides that question.
        """
        from .demand_outcome import (
            DemandOutcomeRecorder, battery_draw, device_draw, ev_draw,
        )
        rec = getattr(self, "_demand_outcomes", None)
        if rec is None:
            rec = self._demand_outcomes = DemandOutcomeRecorder()

        plan = getattr(self, "_energy_plan_shadow", None)
        night = getattr(self, "_shadow_plan_date", None)
        if not isinstance(plan, dict) or night is None:
            # The stamp cleared: the night is over, not paused. Seal it so a
            # later night can never append to yesterday's record.
            if rec.open_records():
                self._seal_demand_outcomes()
            return

        key = str(night)
        if rec.night != key:
            # (#755 pillar 2) The plan's own claim about the night travels
            # WITH the night, so the morning compares the claim that was
            # actually made — a re-stamp restates it and the comparison
            # follows rather than being judged against a superseded one.
            _sc = plan.get("self_consumption") or {}
            rec.open_night(key, plan.get("demands") or [],
                           predicted_share=_sc.get("share"))

        # The meter side of the same question, integrated over the SAME
        # window under the same gap guard — never a calendar-day sensor.
        try:
            rec.observe_totals(
                now,
                solar_w=float(getattr(power, "solar_power", 0.0) or 0.0),
                # ``grid_export_power`` is the canonical derived split
                # (calculate_derived); re-deriving max(0, grid_power) here
                # would open a second sign path — the exact mistake #129
                # and the #588 sign work were about.
                export_w=float(
                    getattr(power, "grid_export_power", 0.0) or 0.0))
        except Exception:  # noqa: BLE001
            pass

        devices = {}
        try:
            for d in self._surplus_controller.get_devices_sorted():
                devices[getattr(d, "device_id", None)] = d
        except Exception:  # noqa: BLE001 — a bad device list costs no record
            pass
        charger_count = len(getattr(self, "_ev_devices", None) or {}) or 1

        for record in rec.open_records():
            did = record.demand_id
            try:
                gate = self._energy_plan_gate(did, now)
                if did.startswith("ev:"):
                    cid = did[3:]
                    _dev = (getattr(self, "_ev_devices", None) or {}).get(cid)
                    draw = ev_draw(
                        cid, power, charger_count,
                        # The canonical per-charger read (#643) — never a
                        # second path to the same number.
                        charger_w=self._charger_power_w(cid, power, _dev),
                        has_own_sensor=bool(
                            getattr(_dev, "power_entity_id", None)))
                elif did == "battery":
                    draw = battery_draw(power)
                else:
                    dev = devices.get(did.split(":", 1)[-1])
                    # A device can leave the list mid-night (reload, removal).
                    # Recording 0 kWh as fact would teach "it never ran".
                    draw = device_draw(dev) if dev is not None else (0.0, False)
                rec.observe(now, did, power_w=draw[0], measured=draw[1],
                            in_block=bool(gate.in_block),
                            covered=bool(gate.covered))
            except Exception:  # noqa: BLE001 — one odd demand won't cost the rest
                continue

        self._persist_demand_outcomes()

    def _seal_demand_outcomes(self) -> None:
        """Close the open night into history and persist it."""
        rec = getattr(self, "_demand_outcomes", None)
        if rec is None:
            return
        closed = rec.close_night()
        for r in closed:
            _LOGGER.info(
                "#755 outcome: %s asked %.2f, planned %.2f, took %.2f kWh "
                "(%.2f in-block)%s",
                r.demand_id, r.asked_kwh, r.planned_kwh, r.actual_kwh,
                r.in_block_kwh, "" if r.measured else " [estimated]")
        # (#772) The morning's comfort verdict: for every comfort demand the
        # night carried, the zone's running in/out-of-block ratio. This is
        # the feedback #705 Ph3 banks blind without — a pre-cool that ran
        # the AC in the block AND again at 17:00 shows up here as a low
        # banked share, where the per-night in_block_kwh above cannot see
        # it. Month figures, so one line answers the rolling question.
        calc = getattr(self, "_energy_calculator", None)
        if calc is not None and closed:
            try:
                _mday = self.time_manager.get_current_meter_day_sunrise_based()
                for r in closed:
                    demand_id = str(r.demand_id)
                    if not demand_id.startswith("comfort:"):
                        continue
                    did = demand_id.split(":", 1)[1]
                    split = calc.get_comfort_split(did, _mday)
                    in_m = split["in_block_month_kwh"]
                    out_m = split["out_block_month_kwh"]
                    total = in_m + out_m
                    if total <= 0:
                        continue
                    _LOGGER.info(
                        "#772 comfort: %s banked %.2f kWh in-block vs %.2f "
                        "outside this month (%d%% banked)",
                        did, in_m, out_m, round(100.0 * in_m / total),
                    )
            except Exception:  # noqa: BLE001 — a verdict never costs a seal
                _LOGGER.debug("#772 comfort ratio skipped", exc_info=True)
        self._persist_demand_outcomes()
        self._refresh_demand_review()

    def _refresh_demand_review(self) -> None:
        """(#755 pillar 4) Recompute the user-facing verdict.

        Only when a night CLOSES (and once at boot, from the restored
        record): the inputs cannot change in between, while the plan sensor
        this rides on is read every cycle.
        """
        from .demand_review import review_night
        rec = getattr(self, "_demand_outcomes", None)
        if rec is None:
            self._demand_review = None
            return
        try:
            self._demand_review = review_night(
                rec.history(), rec.night_summaries())
            # (#800 commit 2) The battery's sentence rides the same
            # verdict — last sealed night, same restraint rules.
            try:
                from .demand_review import review_battery_night
                tr = getattr(self, "_battery_night", None)
                # The OPEN record once its night half is done — a record
                # seals only at the NEXT night, and a morning verdict has
                # to be readable in the morning. Falls back to the last
                # sealed one (overnight, before the new night opens).
                rec = tr.current_record() if tr is not None else None
                if rec is None:
                    sealed = tr.sealed() if tr is not None else []
                    rec = sealed[-1] if sealed else None
                if rec is not None and isinstance(self._demand_review, dict):
                    batt = review_battery_night(rec)
                    if batt is not None:
                        self._demand_review["battery"] = batt
            except Exception:  # noqa: BLE001 — a verdict never costs a cycle
                pass
        except Exception:  # noqa: BLE001 — a verdict never costs a cycle
            _LOGGER.debug("demand review skipped", exc_info=True)
            self._demand_review = None

    async def _record_battery_night(self, power, power_flows,
                                    energy=None) -> None:
        """(#800) One tick of the battery-night recorder.

        Flow-attributed on purpose: a SOC delta would conflate the house
        drain with EV assist and export — the exact series separation the
        #778 budget needs. Night boundary = ``time_manager.is_night_mode``,
        the same clock the planner's night uses.
        """
        import time as _time

        from .battery_night import BatteryNightTracker, Sample

        tr = getattr(self, "_battery_night", None)
        if tr is None:
            tr = self._battery_night = BatteryNightTracker(
                reserve_soc=float(
                    self.config.get("battery_reserve_soc", 20) or 20),
                # (#800) The pack size, so a restart's sampling hole can be
                # bridged from the battery's own SOC instead of writing the
                # interval off. Users restart; a night must survive it.
                capacity_kwh=self.config.get("battery_capacity_kwh"),
            )
            store = getattr(self, "_storage", None)
            if store is not None:
                try:
                    tr.from_dict(store.get_battery_night_state())
                except Exception:  # noqa: BLE001
                    pass

        in_night = bool(self.time_manager.is_night_mode())
        if in_night and tr.phase == "idle":
            # ONE clock read answers both the record's date key and the
            # witness line (the #645 registry counts date() reads — two
            # would be two authorities for the same question).
            _opened_at = dt_util.now()
            tr.start(str(_opened_at.date()),
                     outdoor_temp_c=self._outdoor_temp_c())
            # Openings are witnessed like flips (#811 found a phantom
            # record whose birth nothing had logged — a night that opened
            # at 06:40, outside every window the sensors showed).
            try:
                _LOGGER.info(
                    "#800 night opened: date=%s at %s (window=%s-%s, "
                    "path=%s)",
                    _opened_at.date(),
                    _opened_at.strftime("%H:%M:%S"),
                    *self.time_manager.get_night_window(),
                    getattr(self.time_manager,
                            "_last_night_window_path", "?"),
                )
            except Exception:  # noqa: BLE001
                pass
        phase_before = tr.phase
        tr.tick(
            _time.time(), in_night,
            Sample(
                battery_to_home_w=float(
                    getattr(power_flows, "battery_to_home", 0.0) or 0.0),
                battery_to_ev_w=float(
                    getattr(power_flows, "battery_to_ev", 0.0) or 0.0),
                battery_to_grid_w=float(
                    getattr(power_flows, "battery_to_grid", 0.0) or 0.0),
                # (#778) The pack's own discharge POWER, so the recorder can
                # check its attributed flows against it per sample. Explicitly
                # NOT the daily energy counter: that resets at midnight while
                # a night does not, so comparing the two condemned ordinary
                # nights and silently starved the #778 learner.
                battery_discharge_w=(
                    max(0.0, -float(getattr(power, "battery_power", 0.0) or 0.0))
                    if getattr(power, "battery_power", None) is not None
                    else None),
                grid_to_home_w=float(
                    getattr(power_flows, "grid_to_home", 0.0) or 0.0),
                home_w=float(
                    getattr(power, "home_consumption_power", 0.0) or 0.0),
                soc=getattr(power, "battery_soc", None),
                soc_available=not bool(
                    getattr(power, "battery_soc_unavailable", False)),
                export_w=float(
                    getattr(power, "grid_export_power", 0.0) or 0.0),
                measured=not bool(
                    getattr(power, "battery_power_unavailable", False)),
            ),
        )
        if not in_night and tr.phase == "day":
            # The refill day's promise — dampened, first call wins. After
            # the tick, because the night→day flip happens inside it.
            try:
                fc = self._cycle_forecast
                if fc.available:
                    tr.set_forecast_kwh(float(
                        self._forecast_tracker.apply_dampening(
                            fc.forecast_today_kwh)))
            except Exception:  # noqa: BLE001
                pass
        if tr.phase != phase_before:
            # A flip is rare and load-bearing — log it WITH its inputs
            # (#762 transition-logging style). The first live nights showed
            # phase flips the window sensors could not explain; if that
            # ever recurs, this line is the witness: which branch of
            # is_night_mode fired, and what the window read as.
            try:
                _LOGGER.info(
                    "#800 phase flip %s -> %s (in_night=%s, window=%s-%s, "
                    "path=%s, sealed=%d)",
                    phase_before, tr.phase, in_night,
                    *self.time_manager.get_night_window(),
                    getattr(self.time_manager,
                            "_last_night_window_path", "?"),
                    len(tr.sealed()),
                )
            except Exception:  # noqa: BLE001
                pass
            # (#800 round 4) The verdict reads current_record()/sealed(),
            # and BOTH change exactly at a phase flip — but the review
            # otherwise refreshes only at the demand ledger's seal (which
            # runs BEFORE this tick in the same sunrise update pass, while
            # the tracker is still in night phase) or at restart-restore.
            # Without this, the morning battery row shows the PREVIOUS
            # night, all day. After the forecast capture, so the flip's
            # own verdict already knows the day's promise.
            try:
                self._refresh_demand_review()
            except Exception:  # noqa: BLE001 — a verdict never costs a cycle
                pass

        # Persist EVERY cycle, not only at seal: a restart mid-night would
        # otherwise drop the whole accumulated night, which is the silent
        # regression the store note warns about. The store is delayed-save,
        # so this costs a dict copy.
        store = getattr(self, "_storage", None)
        if store is not None:
            try:
                store.set_battery_night_state(tr.to_dict())
                # (#800 round 3) …and actually reach DISK, throttled. The
                # in-memory write above only survives a graceful stop; the
                # record exists to survive the other kind. Found live on
                # .175 mid-night: 35 min into the night, nothing on disk.
                await store.async_save_energy_throttled()
            except Exception:  # noqa: BLE001 — persist is best-effort
                pass

    def _outdoor_temp_c(self):
        """(#800) Covariate stamp: the first real weather entity's
        temperature, or None. ``weather.forecast_*`` is HA's auto
        subentity and unusable (the standing gotcha)."""
        try:
            for st in self.hass.states.async_all("weather"):
                if st.entity_id.startswith("weather.forecast_"):
                    continue
                t = st.attributes.get("temperature")
                if t is not None:
                    return float(t)
        except Exception:  # noqa: BLE001
            return None
        return None

    def _persist_demand_outcomes(self) -> None:
        rec = getattr(self, "_demand_outcomes", None)
        store = getattr(self, "_storage", None)
        if rec is None or store is None:
            return
        try:
            store.set_demand_outcome_state(rec.get_state())
        except Exception:  # noqa: BLE001 — persist is best-effort
            pass

    def _restore_demand_outcomes(self, state) -> None:
        """Re-seat the night's record after a restart (durable store)."""
        from .demand_outcome import DemandOutcomeRecorder
        rec = getattr(self, "_demand_outcomes", None)
        if rec is None:
            rec = self._demand_outcomes = DemandOutcomeRecorder()
        try:
            rec.restore_state(state or {})
        except Exception:  # noqa: BLE001 — a bad payload costs the record, not the cycle
            _LOGGER.debug("demand outcome restore skipped", exc_info=True)
        # A restart must not blank last night's verdict — it is read all day.
        self._refresh_demand_review()

    def _compose_tomorrow_preview(self, power=None):
        """(#638 consolidation / #722) The next energy day's books,
        previewed for the card's Tomorrow view — or None when the frame
        is unknowable. Anchored to TOMORROW's date throughout (the #722
        review's open MEDIUM was a tomorrow view composed from
        today-anchored values, whose rows changed with the hour you
        looked at it)."""
        from .day_ledger import tomorrow_preview
        from .ev_tariff_planner import resolve_deadline
        now = dt_util.now()
        try:
            ns_s, ne_s = self.time_manager.get_night_window()
            sr_s = self.time_manager.get_sunrise_time()
            ss_s = self.time_manager.get_sunset_plus_10_time()

            # The COMING energy day is the one that stamps at the next
            # period boundary — whose date is NOT always calendar-
            # tomorrow: at 00:07 the boundary (06:07) is TODAY, and a
            # "now + 1 day" anchor previewed the day AFTER next — a
            # ~36 h axis with every window in the second day (Guido,
            # 00:07 on 2026-08-09). Every anchor derives from the
            # boundary's own date.
            stamps_at = resolve_deadline(now, ne_s)
            if stamps_at is None:
                return None
            _day = stamps_at

            def _at(hhmm):
                h, m = (int(x) for x in hhmm.split(":"))
                return _day.replace(
                    hour=h, minute=m, second=0, microsecond=0)

            sunrise, sunset = _at(sr_s), _at(ss_s)
            day_start, day_end = sunrise, _at(ns_s)
        except Exception:  # noqa: BLE001 — no frame, no preview
            return None
        if day_end <= day_start:
            return None
        try:
            _fd = getattr(getattr(self, "_forecast_reader", None),
                          "forecast_data", None)
            day_kwh = float(getattr(_fd, "forecast_tomorrow_kwh", 0.0) or 0.0)
        except Exception:  # noqa: BLE001 — no forecast, dark preview
            day_kwh = 0.0
        try:
            flat_home = float(self._expected_night_home_w(None))
        except Exception:  # noqa: BLE001
            flat_home = 300.0
        from .day_ledger import tariff_cheap_at, tariff_price_at
        prov = self._tariff_provider
        preview = tomorrow_preview(
            day_start=day_start, day_end=day_end, day_kwh=day_kwh,
            sunrise=sunrise, sunset=sunset,
            home_w_at=lambda t: flat_home,
            price_at=lambda ts: tariff_price_at(prov, ts),
            level_cheap_at=lambda ts: tariff_cheap_at(prov, ts),
            stamps_at=stamps_at,
        )
        # (Guido, 08-08: "forecast and home consumption is something we
        # already know") — the preview's real content is what tomorrow
        # will ASK: each load's daily min-runtime × its calibrated draw,
        # each charger's daily target. Knowable today because the day
        # counters reset at midnight; no packing, no verdicts — that
        # plan honestly does not exist until it stamps.
        asks = []
        try:
            from ..devices.base import DeviceControlMode as _DCM
            _ctrl = getattr(self, "_surplus_controller", None)
            for _dev in (_ctrl.get_devices_sorted() if _ctrl else []):
                try:
                    # The preview must mirror the demand builder's intent
                    # gate (finding #1, PROD night 1 — and again 09.08:
                    # three peak_only Pro4PM metering channels showed
                    # 10 kWh asks). A device SEM never proactively runs —
                    # off / peak_only — asks nothing tomorrow.
                    if getattr(_dev, "control_mode", _DCM.SURPLUS) \
                            != _DCM.SURPLUS:
                        continue
                    _min_s = float(getattr(_dev, "daily_min_runtime_sec", 0)
                                   or 0)
                    _rated = float(getattr(_dev, "rated_power", 0.0) or 0.0)
                    if _min_s <= 0 or _rated <= 0:
                        continue
                    asks.append({
                        "kind": "load",
                        "label": str(getattr(_dev, "name", "") or "").strip()
                        or str(getattr(_dev, "device_id", "?")),
                        "kwh": round(_rated * _min_s / 3600.0 / 1000.0, 2),
                        "power_w": _rated,
                    })
                except Exception:  # noqa: BLE001 — one device, not the list
                    continue
            for _cfg in (self.config.get("ev_chargers") or []):
                try:
                    _tgt = float(_cfg.get("daily_ev_target")
                                 or self.config.get("daily_ev_target", 0)
                                 or 0)
                    if _tgt <= 0.05:
                        continue
                    asks.append({
                        "kind": "ev",
                        "label": str(_cfg.get("name") or "EV").strip(),
                        "kwh": round(_tgt, 2),
                    })
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001 — asks are additive, never fatal
            asks = []
        preview["known_asks"] = asks
        # (Guido, 08-08: "we can also predict the battery level and when
        # the devices get surplus — pull it together") — the PROVISIONAL
        # pack: tomorrow's asks placed into tomorrow's own books by the
        # same packer, the battery seeded with the level TODAY'S plan
        # predicts for the morning (its walk already ends there). No
        # stamped plan → no honest seed → no provisional, rather than an
        # invented battery level.
        preview["provisional"] = None
        try:
            # The SAME capacity source the plan itself walks with — the
            # coordinator attribute, not a config key (a parallel source
            # is how the clone's battery row went missing while its
            # arbitrage line happily said /15.0).
            cap_kwh2 = float(getattr(
                self, "battery_capacity_kwh", 0.0) or 0.0)
            _stash = getattr(self, "_energy_plan_shadow", None)
            _sl = (_stash.get("slots") if isinstance(_stash, dict)
                   else None) or []
            soc_seed = None
            if _sl:
                soc_seed = float(_sl[-1].get("soc_kwh") or 0.0)
            elif power is not None and getattr(
                    power, "battery_soc", None) is not None:
                # (Guido on PROD, 08-08) an IDLE today has no trajectory
                # to seed from — but the live SOC is not an invented
                # number, and a quiet today must not erase tomorrow's
                # battery row.
                soc_seed = max(0.0, float(power.battery_soc)) / 100.0                     * cap_kwh2
            if soc_seed is not None:
                from .day_ledger import (build_day_slots,
                                         provisional_soc_curve)
                from .energy_planner import (Demand, build_night_ledger,
                                                pack_night)
                slots2 = build_day_slots(
                    start=day_start, end=day_end, day_kwh=day_kwh,
                    sunrise=sunrise, sunset=sunset,
                    home_w_at=lambda t: flat_home,
                    price_at=lambda ts: tariff_price_at(prov, ts),
                    level_cheap_at=lambda ts: tariff_cheap_at(prov, ts),
                )
                labels2 = {}
                demands2 = []
                for i, ask in enumerate(asks):
                    did = f"{ask['kind']}:{i}"
                    labels2[did] = ask["label"]
                    power = float(ask.get("power_w") or 0.0)
                    if ask["kind"] == "ev" and power <= 0:
                        # the min-amps floor rate — the honest EV pace
                        power = 4140.0
                    if power <= 0:
                        continue
                    demands2.append(Demand(
                        id=did, kind=ask["kind"],
                        energy_kwh=float(ask["kwh"]),
                        max_power_w=power, min_power_w=power,
                        deadline=day_end, priority=i, source="grid",
                    ))
                _reserve = float(self.config.get(
                    "battery_priority_soc", 30) or 30)
                _floor2 = _reserve / 100.0 * cap_kwh2
                _md_w = float(self.config.get(
                    "battery_max_discharge_power", 5000.0) or 5000.0)
                try:
                    _peak_w = float(self._get_peak_limit_w() or 0.0)
                except Exception:  # noqa: BLE001
                    _peak_w = 0.0
                ledger2 = build_night_ledger(
                    slots2, soc_kwh=soc_seed, floor_kwh=_floor2,
                    max_discharge_w=_md_w, peak_limit_w=_peak_w)
                plan2 = pack_night(
                    demands2, ledger2, floor_kwh=_floor2,
                    max_discharge_w=_md_w, peak_limit_w=_peak_w)
                curve = provisional_soc_curve(
                    ledger2, capacity_kwh=cap_kwh2,
                    max_charge_w=float(self.config.get(
                        "battery_max_charge_power_w", 5000.0) or 5000.0))
                # (#820) Pace the fill: invert the SAME curve model. This
                # method is sync — stash the inputs; _async_update_data
                # applies the pacing right after the preview composes.
                self._charge_pacing_inputs = (ledger2, cap_kwh2)
                # Compress for the recorder budget: ≤ 5 waypoints + end.
                if len(curve) > 6:
                    step = max(1, (len(curve) - 1) // 5)
                    curve = curve[:-1:step] + [curve[-1]]
                # Allocations arrive SLOT-major — merge each ask's
                # back-to-back windows into runs (the #638 G3c lesson:
                # group by id first, neighbours in the list never merge).
                _by_id = {}
                for a in plan2.allocations:
                    _by_id.setdefault(a.demand_id, []).append(a)
                _blocks2 = []
                for _did, _rows in _by_id.items():
                    _rows.sort(key=lambda a: a.start)
                    for a in _rows:
                        if (_blocks2 and _blocks2[-1]["id"] == _did
                                and _blocks2[-1]["end"] == a.start.isoformat()):
                            _blocks2[-1]["end"] = a.end.isoformat()
                        else:
                            _blocks2.append({
                                "id": _did,
                                "label": labels2.get(_did),
                                "start": a.start.isoformat(),
                                "end": a.end.isoformat(),
                            })
                preview["provisional"] = {
                    "soc_start": round(soc_seed, 2),
                    "soc_curve": curve,
                    "fits": plan2.fits,
                    "blocks": _blocks2,
                }
        except Exception:  # noqa: BLE001 — provisional is additive, never fatal
            preview["provisional"] = None
        return preview

    def _energy_plan_tick(self, power, energy) -> None:
        """(#638) The once-per-night stamp + demand-shape replan trigger.

        (#638 G3) Runs in BOTH modes — the plan is itself an observer
        construct, and it does not depend on the battery scheduler being
        enabled (PROD: static tariff, summer — EV floors + Tier-2 loads
        still need a plan). Two live placement lessons in one: the
        scheduler.enabled gate AND the observer gate each silenced it on
        the machine it was soaking on. Own once-per-NIGHT trigger; the
        scheduler's evaluate/replans recompute on top when it runs.

        (night 3) Called BEFORE the charging decisions in the update cycle:
        the EV chain used to run first, so the cycle in which a car
        connected was decided against the stale plan — one honest `active`
        blip in observer, one real enable-then-revoke against hardware.
        """
        try:
            _sched = self._battery_charge_scheduler
            _now_l = dt_util.now()
            # (#638 Phase 3) Feed the drift learners — every cycle, not
            # only at stamp time: the comfort model needs continuous
            # ON/OFF temperature history to say when a room hits its
            # limit and what banking back costs.
            try:
                _ctrl = getattr(self, "_surplus_controller", None)
                for _dev in (_ctrl.get_devices_sorted() if _ctrl else []):
                    try:
                        _rec = getattr(_dev, "record_comfort_sample", None)
                        if callable(_rec):
                            _rec(_now_l)
                    except Exception:  # noqa: BLE001 — one device, not all
                        continue
            except Exception:  # noqa: BLE001 — sampling must never gate
                pass
            # (horizon-spanning) One plan per ENERGY DAY — night-end to
            # night-end — not one per night: the plan always covers now →
            # the coming night's end, so a daytime tick stamps the
            # day+night plan (comfort banking and load scheduling into
            # surplus windows need a daytime answer) and the sunrise
            # boundary opens the next period. The night end is the same
            # sunset/sunrise-anchored min(sunrise, latest_end) every
            # night source runs on. A restart at any hour still owes the
            # rest of the horizon a plan.
            _night_of = None
            try:
                from .ev_tariff_planner import resolve_deadline as _resolve
                _ne = _resolve(_now_l, self.time_manager.get_night_end_time())
                if _ne is not None:
                    _night_of = _ne.date()
            except Exception:  # noqa: BLE001 — degrade to the old night key
                _night_of = None
            if _night_of is None:
                _night_of = (_now_l - timedelta(hours=12)).date()
            # (P3, 13.08) A COLD world is not a changed night. The first
            # boot ticks run before the device-runtime restore (and, until
            # the eager fix above, before the per-charger detectors), so a
            # signature computed here reads wrong deficits and a cold
            # fullness term — and comparing it against the restored stamp's
            # warm signature restamped the night on every reboot
            # (11:13:26 restamp vs 11:13:37 restore, P3 provocation).
            # Neither compare NOR stamp until the restore has run; the tick
            # retries within a cycle. Default True: only the real setup
            # path sets False, so bare test fakes keep their behaviour.
            if not getattr(self, "_runtimes_restored", True):
                return
            # (#638) DEMAND-SHAPE replan. #638 specified the triggers as
            # "price update, floor change, unplug, big deviation"; only
            # unplug shipped, so raising the EV target at 22:19 on armed
            # night 1 left the ledger describing a night that no longer
            # existed while execution correctly followed the new floor.
            # One signature over every input that changes WHAT is asked of
            # the night — connection, EV floor/deadline/mode, each load's
            # runtime deficit, and the night's price curve.
            _demand_sig = self._energy_plan_demand_signature(power, energy)
            cause = "initial"
            # (Guido, 00:30 on 08-09) the explicit re-plan lever — now
            # that the plan survives reboots, restart-as-replan retires
            # and the service is the honest test/ops lever.
            if getattr(self, "_manual_replan_requested", False):
                self._manual_replan_requested = False
                self._shadow_plan_date = None
                cause = "manual"
                _LOGGER.info(
                    "ENERGY-PLAN (#638): manual re-plan requested — "
                    "restamping the period")
            # (#775) A revision re-PLANS unconditionally, but whether it
            # re-STAMPS is decided AFTER the rebuild, against the packed
            # answer — so the sig diff and the outgoing plan are carried
            # to the stamp site instead of logged here.
            _prev_sig_775 = _prev_plan_775 = None
            if (getattr(self, "_shadow_plan_date", None) == _night_of
                    and self._plan_ev_conn_sig is not None
                    and demand_signature_changed(
                        self._plan_ev_conn_sig, _demand_sig)):
                _prev_sig_775 = self._plan_ev_conn_sig
                _prev_plan_775 = getattr(self, "_energy_plan_shadow", None)
                self._shadow_plan_date = None
                # (night 3, finding 3) the re-stamp says why it exists —
                # Guido shrinking the ASK to 0.5 kWh silently became "the"
                # night, indistinguishable from the first answer.
                cause = "ask changed"
            if getattr(self, "_shadow_plan_date", None) != _night_of:
                # Stamp only on a READY-world answer: the first refresh
                # after a restart sees zero registered devices (delayed
                # rediscovery) — that degenerate shape retries next cycle.
                # Same for a battery SOC that hasn't reported yet (armed
                # night 1, second stamp): the 21:53:30 restart stamped
                # 86 s before the SOC's first reading, the trajectory
                # walked from nothing, takeover landed on the FIRST slot
                # and every battery demand yielded a battery that was
                # actually at 63 %. A silent sensor is not an empty
                # battery (#638 finding #3) — wait for the reading; the
                # no-battery install shape (capacity 0) stamps normally.
                _batt_ready = (
                    float(self.config.get("battery_capacity_kwh", 0) or 0) <= 0
                    or not getattr(power, "battery_soc_unavailable", False)
                )
                if _batt_ready and self._shadow_energy_plan(
                        _sched, energy, power,
                        replan_cause=cause):
                    if (cause == "ask changed"
                            and isinstance(_prev_plan_775, dict)
                            and plan_decision_core(self._energy_plan_shadow)
                            == plan_decision_core(_prev_plan_775)):
                        # (#775) The ask moved, the rebuild ran, and the
                        # packed answer is byte-for-byte the decision the
                        # night already has — an identical repack is free.
                        # Keep the stamp (computed_at marks a DECISION),
                        # advance the signature baseline so this revision
                        # does not re-fire every cycle. Manual re-plans
                        # never take this path: "decide again, now" must
                        # visibly answer, even with "same answer".
                        self._energy_plan_shadow = _prev_plan_775
                        _LOGGER.debug(
                            "ENERGY-PLAN (#775): the ask moved (%s → %s) "
                            "but the packed answer is identical — "
                            "stamp kept", _prev_sig_775, _demand_sig)
                    elif cause == "ask changed":
                        _LOGGER.info(
                            "ENERGY-PLAN (#638): the night's demands "
                            "changed (%s → %s) — replanning",
                            _prev_sig_775, _demand_sig)
                    self._shadow_plan_date = _night_of
                    self._plan_ev_conn_sig = _demand_sig
                    # (#638) the stamp is state — persist it so a reboot
                    # re-seats the SAME night (saved by the normal
                    # delayed-save cycle, the W/A precedent).
                    _st = getattr(self, "_storage", None)
                    if _st is not None:
                        try:
                            from .battery_charge_scheduler import (
                                serialize_battery_verdict,
                            )
                            _st.set_energy_plan_state({
                                "plan": self._energy_plan_shadow,
                                "period": _night_of.isoformat(),
                                "sig": _demand_sig,
                                # (#638 C4c) the WHAT beside the WHEN — a
                                # reboot mid-block outside the evaluation
                                # window must still actuate.
                                "battery_verdict": serialize_battery_verdict(
                                    getattr(_sched, "_decision", None)
                                    if _sched is not None else None),
                            })
                        except Exception:  # noqa: BLE001 — persist is best-effort
                            pass
        except Exception:  # noqa: BLE001 — shadow must never break the cycle
            _LOGGER.debug("shadow energy plan trigger skipped", exc_info=True)

    def _shadow_energy_plan(self, scheduler, energy, power=None,
                               replan_cause="initial") -> bool:
        """#638 G3 — compute the joint energy plan in shadow mode.

        Demands are built from the REAL models — ``build_night_target_map``
        per charger (mode-gated), load runtime deficits, the scheduler's own
        battery deficit — under one hourly price curve and one peak cap.
        Output: INFO summary (the 22:00 answer), DEBUG per-allocation lines,
        and ``self._energy_plan_shadow`` for diagnostics. No actuation.

        Returns True when the answer came from a READY world and the night
        may be stamped; False on the degenerate warm-up shape (first refresh
        after startup: zero devices registered, empty target map, zero
        deficit — caught live on TEST) so the trigger retries next cycle.
        """
        try:
            from datetime import timedelta as _td
            from .energy_planner import (
                Demand, LedgerSlot, build_night_ledger, pack_night,
            )
            from .ev_night_targets import build_night_target_map
            from .ev_tariff_planner import resolve_deadline

            now = dt_util.now()
            # (#638 G4) the log tag is the honest mode of THIS stamp: while
            # the actuation switch is on, the plan's blocks feed the night
            # signals — the lines must say so.
            tag = ("active" if getattr(self, "_energy_plan_actuation", False)
                   else "shadow")
            try:
                night_end_s = self.time_manager.get_night_end_time()
            except Exception:  # noqa: BLE001 — window end is best-effort
                night_end_s = None
            night_end = resolve_deadline(now, night_end_s) or (now + _td(hours=8))

            demands = []
            # Display names per demand id, for the card (#638 G3c). Kept OUT
            # of the pure planner: ``Demand`` stays free of presentation.
            labels = {}
            # EV floors — the REAL per-charger night-need map (#652 closure).
            targets = build_night_target_map(self, energy) if energy is not None else {}
            cfg_by_id = {c.get("id"): c for c in self.config.get("ev_chargers", [])
                         if isinstance(c, dict)}
            mode_opted_out = []
            disconnected = []
            car_full = []
            # (#638 C7) The load side's twin of those three lists.
            left_out_loads = []
            for cid, kwh in targets.items():
                cfg = cfg_by_id.get(cid, {})
                # Mirror the execution gate (finding #4, TEST night 2026-07-30).
                # ``build_night_target_map`` answers "how much does this charger
                # still NEED" — not "will SEM give it any tonight". The night
                # loop decides that separately, with
                # ``_mode_allows_night_charging`` (``off``, and ``solar_only``
                # without a per-charger "At least" floor, #634). Live: EV mode
                # Off, SEM's own state reading "Night charging disabled", and
                # the shadow still planned 10 kWh of grid for it. Sibling of
                # finding #1 (the off-mode load) — the plan is only worth
                # trusting where it packs what execution would actually run.
                try:
                    mode_night_ok = bool(self._mode_allows_night_charging(cfg))
                except Exception:  # noqa: BLE001 — unevaluable: plan it
                    # Over-planning shows up in the summary; a demand deleted
                    # by a broken gate would be invisible. Fail visible.
                    mode_night_ok = True
                if not mode_night_ok:
                    mode_opted_out.append(cid)
                    continue
                # (#638 night 3) A car that is KNOWN absent is not a demand:
                # both machines packed kWh for unplugged cars — ledger spent
                # on a demand that can never draw, real demands starved
                # behind it. Only a configured plug sensor may answer "no"
                # (None = nothing to ask → plan it, the mode-gate
                # precedent). The plug-in re-plans within a cycle because
                # connection is term 1 of the demand signature — proven
                # live on the clone: connect 00:07:32, stamp same second.
                if self._plan_ev_connected(cid, cfg, power) is False:
                    disconnected.append(cid)
                    continue
                # (#756, N1) A car that is KNOWN full is not a demand. The
                # target map answers ``target − daily`` off the calendar
                # counter, which rolls at midnight — at 00:01 the ask for a
                # 100 % car jumped to the full 20 kWh and the phantom
                # displaced the real loads under the peak cap (sim_heizband
                # fits→yields at exactly 00:01; the morning unplug flipped
                # it straight back). Only a definite yes skips; an unknown
                # car is planned — the two gates above set the precedent.
                # (N2, 15.08) The accessor asks the meter too: a car that
                # is DRAWING is not a full car, however the anchor's
                # arithmetic reads mid-delivery.
                if self._plan_car_full(cid, power):
                    car_full.append(cid)
                    continue
                if kwh <= 0.05:
                    continue
                # (#638 armed night 1) MEASURED W/A, nameplate fallback: the
                # packer sized the floor at nameplate 6.9 kW, found no slot
                # under the 6.0 kW peak, and yielded a car that then charged
                # at 4.85 kW below the threshold all night.
                wpa = self._ev_watts_per_amp(cid, cfg, power)
                deadline = resolve_deadline(now, cfg.get("ev_target_time"))
                try:
                    # The canonical one-list slot (#576): a drag override wins
                    # immediately — the same accessor decide() uses.
                    ev_prio = int(self._ev_priority_for(cid))
                except Exception:  # noqa: BLE001
                    ev_prio = int(cfg.get("priority") or 0)
                labels[f"ev:{cid}"] = str(cfg.get("name") or "").strip() or None
                demands.append(Demand(
                    id=f"ev:{cid}", kind="ev", energy_kwh=float(kwh),
                    max_power_w=float(cfg.get("ev_max_current")
                                      or DEFAULT_MAX_CHARGING_CURRENT) * wpa,
                    min_power_w=float(cfg.get("ev_min_current") or 6) * wpa,
                    deadline=min(deadline, night_end) if deadline else night_end,
                    # The one list counts 1 = HIGHEST (get_devices_sorted)
                    # and the packer packs LOWEST first — the directions
                    # already agree. The old negation REVERSED the list:
                    # armed night 1 packed rank 14 first and the EV (rank 1)
                    # dead last (#638).
                    priority=ev_prio,
                    source="grid",   # never-EV-from-battery (standing rule)
                    # (#638 one-gate C3) The contactor's anti-cycle window
                    # moved from the retired dwell hysteresis into the
                    # packer's #688 quantization: a 15-minute jagged market
                    # cannot hand the charger scattered quarter-hour blocks.
                    min_run_s=int(self.config.get(
                        "ev_min_block_minutes", 15)) * 60,
                    min_gap_s=int(self.config.get(
                        "ev_min_block_minutes", 15)) * 60,
                ))
            # Load min-runtime deficits eligible for a night source.
            controller = getattr(self, "_surplus_controller", None)
            loads_seen = 0
            loads_eligible = 0
            from ..devices.base import DeviceControlMode as _DCM
            # (#638 C7) Every load the collector leaves out owes the user a
            # why — the EV side has said so since C7 while the load side
            # skipped in five places silently, and "why isn't my heater in
            # tonight's plan?" had no answer anywhere on the card.
            # (#744) …and it owes it BY NAME. ``labels`` was assigned only
            # after every gate passed, so precisely the rows that need a
            # name never got one and the card fell back to the id slug:
            # Guido read `energy_dashboard_shellyplus1pm_441793d5470c`
            # where his roster says "Bad / Dusche / Gäste".
            def _left_out(dev, why):
                left_out_loads.append({
                    "id": f"load:{dev.device_id}", "why": why,
                    "label": str(getattr(dev, "name", "") or "").strip() or None,
                })

            for dev in (controller.get_devices_sorted() if controller else []):
                try:
                    loads_seen += 1
                    # (#744) Is this a night candidate AT ALL? A device that
                    # was never asked for guaranteed runtime cannot become a
                    # night demand in ANY mode — the demand's energy is
                    # ``rated × (min_runtime − accumulated)``, which is zero
                    # by construction. Asked FIRST, and silently: the mode
                    # gate below used to answer for these, so a roster of
                    # Energy-Dashboard imports (control_mode defaults to
                    # PEAK_ONLY) printed its own default state as a why-not
                    # list every night — nine of Guido's eleven rows, ~45 of
                    # #744's forty-seven. A non-candidate owes no
                    # explanation; ``loads_seen`` still counts it, so the
                    # quiet night keeps saying "no load needs a night run".
                    if int(getattr(dev, "daily_min_runtime_sec", 0) or 0) <= 0:
                        continue
                    # The plan must mirror the intent gate (finding #1, PROD
                    # night 1): an off/peak_only device is never night-run by
                    # compute_load_intent — planning it (the off-mode heizband
                    # "yielded" 3.1 kWh) diverges from execution.
                    if getattr(dev, "control_mode", _DCM.SURPLUS) != _DCM.SURPLUS:
                        _left_out(dev, "load_mode")
                        continue
                    if not getattr(dev, "has_runtime_deficit", False):
                        _left_out(dev, "no_runtime_need")
                        continue
                    # (#760, N1) The intent's HARD STOP outranks the deficit:
                    # a banked comfort band (room already past target+offset)
                    # sets ``stop_condition_met`` and clause 3 kills the run
                    # ABOVE tier-2 — every cycle, covered or not. The
                    # heizband spent a whole night packed fits+COVERED while
                    # the executor was rightly refusing. Fourth mirrored
                    # gate (mode, connectivity, car-full, this); the stop
                    # state rides the demand signature, so it CLEARING
                    # re-plans and re-admits the demand within a cycle.
                    if getattr(dev, "stop_condition_met", False):
                        _left_out(dev, "stop_condition")
                        continue
                    night_ok = (getattr(dev, "battery_eligible_overnight", False)
                                or getattr(dev, "top_up_policy", "") == "cheap_hours")
                    if not night_ok:
                        _left_out(dev, "day_only")
                        continue
                    loads_eligible += 1
                    deficit_h = max(0.0, (dev.daily_min_runtime_sec
                                          - dev._daily_runtime_accumulated_sec) / 3600.0)
                    # rated_power is the CALIBRATED draw (learned from the real
                    # consumption, #576) — the plan is only as accurate as this.
                    rated = float(getattr(dev, "rated_power", 0.0) or 0.0)
                    if deficit_h <= 0 or rated <= 0:
                        _left_out(dev, "no_rated_power")
                        continue
                    tier2 = bool(getattr(dev, "battery_eligible_overnight", False))
                    labels[f"load:{dev.device_id}"] = (
                        str(getattr(dev, "name", "") or "").strip() or None)
                    demands.append(Demand(
                        id=f"load:{dev.device_id}", kind="load",
                        energy_kwh=rated * deficit_h / 1000.0,
                        max_power_w=rated, min_power_w=rated,
                        deadline=night_end,
                        # 1 = highest in BOTH the one list and the packer —
                        # no negation (see the EV demand above).
                        priority=int(getattr(dev, "priority", 0) or 0),
                        # Tier-2 runs off the home battery: no grid meter, no
                        # peak cap, no price — it spends the trajectory.
                        source="battery" if tier2 else "grid",
                        # A cheap-hours load EXECUTES only when the provider's
                        # level says cheap — the plan must pack the same way.
                        needs_cheap_level=(not tier2 and getattr(
                            dev, "top_up_policy", "") == "cheap_hours"),
                        # (#688) the plan quantizes to the anti-cycle window.
                        min_run_s=int(getattr(dev, "min_on_seconds", 0) or 0),
                        min_gap_s=int(getattr(dev, "min_off_seconds", 0) or 0),
                    ))
                except Exception:  # noqa: BLE001 — one bad device won't kill the plan
                    continue
            # Comfort banking (#638 Phase 3 / #705): a drifting room is a
            # deadline-shaped demand — "hits the limit at T, banking back
            # costs E kWh". needs_cheap_level because banking is
            # opportunism: free sun or a cheap level, never plain-rate
            # paid power (a breach is the FORCED tier's job, on the
            # user's own source-axis terms). The ask lives on the device
            # — the band owns its model; a device without a band simply
            # has no method to call.
            for dev in (controller.get_devices_sorted() if controller else []):
                try:
                    if getattr(dev, "control_mode", _DCM.SURPLUS) != _DCM.SURPLUS:
                        continue
                    _ask_fn = getattr(dev, "comfort_plan_demand", None)
                    ask = _ask_fn(now) if callable(_ask_fn) else None
                    if not ask:
                        continue
                    rated = float(getattr(dev, "rated_power", 0.0) or 0.0)
                    if rated <= 0:
                        continue
                    did = dev.device_id
                    labels[f"comfort:{did}"] = (
                        str(getattr(dev, "name", "") or "").strip() or None)
                    demands.append(Demand(
                        id=f"comfort:{did}", kind="comfort",
                        energy_kwh=float(ask["energy_kwh"]),
                        max_power_w=rated, min_power_w=rated,
                        deadline=ask.get("deadline") or night_end,
                        priority=int(getattr(dev, "priority", 0) or 0),
                        source="grid",
                        needs_cheap_level=True,
                        min_run_s=int(getattr(dev, "min_on_seconds", 0) or 0),
                        min_gap_s=int(getattr(dev, "min_off_seconds", 0) or 0),
                    ))
                except Exception:  # noqa: BLE001 — one bad band won't kill the plan
                    continue
            # Battery pre-charge — the scheduler's own computed deficit.
            # (Grid-sourced: charging the battery draws through the meter.)
            dec = getattr(scheduler, "decision", None)
            deficit = float(getattr(dec, "deficit_kwh", 0.0) or 0.0)
            if deficit > 0.1:
                try:
                    # The battery's drag-set slot in the ONE list (#576).
                    batt_prio = int(self._device_registry.battery_surplus_priority())
                except Exception:  # noqa: BLE001
                    batt_prio = 0
                demands.append(Demand(
                    id="battery", kind="battery", energy_kwh=deficit,
                    max_power_w=float(getattr(
                        getattr(scheduler, "_config", None),
                        "battery_max_charge_power_w", 5000.0)),
                    priority=batt_prio,
                    source="grid",
                ))

            # ── Readiness, before anything gets stamped ─────────────────
            # Whatever is written below stands for the WHOLE night (one stamp
            # per night, and only a restart re-fires it), so a half-read world
            # must not produce one — not even the "nothing needs the night"
            # answer, which is just as final as a full ledger.
            soc = getattr(power, "battery_soc", None) if power is not None else None
            cap_kwh = float(getattr(self, "battery_capacity_kwh", 0.0) or 0.0)
            # Power readiness is the SECOND warm-up dimension (finding #2,
            # PROD night 1): at the first refresh the SOC sensor read
            # unavailable → None → the ledger put a 77%-full battery at
            # 0 kWh and derived a bogus 03:00 takeover. A configured battery
            # with no SOC reading yet is a not-ready world — retry.
            if cap_kwh > 0 and soc is None:
                _LOGGER.debug(
                    "ENERGY-PLAN (%s #638): battery SOC not ready — "
                    "retrying next cycle", tag)
                return False
            # Finding #3 (TEST, night 2026-07-29): readiness has a THIRD
            # dimension — a multi-battery fleet resolves one unit at a time.
            # Battery 1's modbus SOC took 2m43s to publish after a restart, so
            # ten seconds in the "fleet" SOC was battery 2's 65% (real fleet:
            # 74.5%) and the plan was stamped for the night on a battery
            # 1.4 kWh too small: takeover 04:00 → 02:00, a tier-2 load yielding
            # 0 kWh it would in fact get. A subset is not the fleet — wait for
            # every unit to report.
            #
            # Bounded, though: waiting FOREVER turns a skewed plan into no
            # plan at all, which is the worse failure. A unit still silent
            # ten minutes in is offline, not warming — plan on the units
            # that do report and carry the shortfall on the plan itself.
            read = int(getattr(power, "battery_soc_units_read", 0) or 0)
            known = int(getattr(power, "battery_soc_units_expected", 0) or 0)
            configured = int(
                getattr(power, "battery_soc_units_configured", 0) or 0)
            if (power is not None
                    and getattr(power, "battery_soc_partial", False)):
                since = self._shadow_partial_since
                if since is None:
                    self._shadow_partial_since = since = now
                if (now - since).total_seconds() < _SHADOW_PARTIAL_GRACE_S:
                    _LOGGER.debug(
                        "ENERGY-PLAN (%s #638): battery fleet only "
                        "%s/%s units resolved — retrying next cycle",
                        tag, read, known)
                    return False
                _LOGGER.warning(
                    "ENERGY-PLAN (%s #638): battery fleet still only "
                    "%s/%s units after %.0f min — planning on the units that "
                    "report. A unit silent this long is offline, not warming.",
                    tag, read, known, _SHADOW_PARTIAL_GRACE_S / 60.0)
            else:
                self._shadow_partial_since = None
            # Label the plan whenever its battery figures came from a SUBSET,
            # whichever reason: a unit that never reported (above) or one whose
            # SOC sensor was never findable at all. Both make "9.8 kWh usable"
            # a half-truth, and reading it as the fleet's is what cost a night.
            partial_note = (
                f"battery fleet partial: {read}/{configured} units"
                if configured and read < configured else None)

            # (15.08, .175 campaign) A quiet night is still a night. The
            # "nothing needs tonight" answer used to be RETURNED right here,
            # BEFORE the ledger was ever built — so a night with nothing to
            # schedule lost its price axis, its self-consumption expectation
            # and its arbitrage verdict, and the advisor's own ADVICE-ALWAYS
            # contract was quietly false in the one regime where the advice
            # is the only thing left to say. Decide the answer here; SPEAK
            # it below, once the books are open.
            quiet_night = not demands
            if quiet_night and loads_seen == 0 and not targets \
                    and deficit <= 0.0:
                # Warm-up shape: nothing registered yet (first refresh after
                # a restart) — not an answer, retry next cycle.
                _LOGGER.debug(
                    "ENERGY-PLAN (%s #638): world not ready "
                    "(0 devices, empty target map) — retrying next cycle", tag)
                return False

            def _slot_rows(rows):
                """The card's hour axis and battery trajectory.

                ONE shape, two callers (quiet night and packed night): a
                quiet night that drew a different strip would be a second
                bug wearing this fix. ``home_grid_w > 0`` is the takeover
                made visible per slot — the hour the battery stopped
                covering the house on its own.
                """
                return [{
                    "start": s.start.isoformat(),
                    # ``end`` is carried explicitly rather than left for the
                    # card to infer from the next slot's start: the last slot
                    # has no successor, and market slots are not always
                    # hourly (15-min curves exist), so the strip's time axis
                    # needs a real end.
                    "end": s.end.isoformat(),
                    "price": s.price,
                    "cheap": bool(s.level_cheap),
                    "home_w": round(s.home_w, 1),
                    "soc_kwh": round(s.soc_kwh, 2),
                    "home_grid_w": round(s.home_grid_w, 1),
                } for s in rows]

            def _quiet_answer(arb=None, ledger_rows=(), self_cons=None):
                # "Nothing needs the night" IS a valid 22:00 answer — say it,
                # WITH the why (a silent shadow is indistinguishable from a
                # broken one; burned three placement bugs learning that).
                why = (f"ev_targets={ {k: round(v, 2) for k, v in targets.items()} }, "
                       f"mode_opted_out={mode_opted_out}, "
                       f"disconnected={disconnected}, "
                       f"loads_seen={loads_seen}, loads_eligible={loads_eligible}, "
                       f"battery_deficit={deficit:.2f} kWh")
                _LOGGER.info(
                    "ENERGY-PLAN (%s #638): no overnight demands — %s", tag, why)
                # (#638 C7 follow-up, Guido's first live look) The card
                # renders translated SENTENCES from these codes; the raw
                # prose above stays for logs/diagnose — a rendered surface
                # showing `ev_targets={...}` read as unfinished.
                why_codes = []
                if targets and not disconnected and not mode_opted_out                         and all(v <= 0.05 for v in targets.values()):
                    why_codes.append("ev_target_met")
                if loads_seen and not loads_eligible:
                    why_codes.append("no_load_needs_night")
                if deficit <= 0.05:
                    why_codes.append("battery_no_deficit")
                return {
                    "computed_at": now.isoformat(),
                    "fits": True,
                    # (08-08) the quiet answer must explain itself ON the
                    # card, not only in diagnose — "the plan disappeared"
                    # was a correct idle answer nobody could read.
                    "why": why,
                    "why_codes": why_codes,
                    "not_scheduled": (
                        [{"id": f"ev:{c}", "why": "mode"}
                         for c in mode_opted_out]
                        + [{"id": f"ev:{c}", "why": "disconnected"}
                           for c in disconnected]
                        + [{"id": f"ev:{c}", "why": "car_full"}
                           for c in car_full]
                        + left_out_loads),
                    "summary": [f"no overnight demands tonight ({why})"],
                    # (#638 G3c) Same keys as a full plan, empty — the card
                    # renders "nothing needs the night" from the SHAPE, not
                    # from a missing key it would have to treat as an error.
                    "demands": [],
                    # …and the keys that are LEDGER facts rather than
                    # packing results are filled, not emptied: the night
                    # still has prices, a battery trajectory, a share it
                    # expects to keep and an arbitrage verdict. Only the
                    # scheduling is empty.
                    "slots": list(ledger_rows),
                    "blocks": [],
                    "arbitrage": arb,
                    "self_consumption": self_cons,
                    "battery_fleet_partial": partial_note,
                    # (night 3, finding 3) a re-stamped night must be
                    # distinguishable from the first answer.
                    "replan_cause": replan_cause,
                }

            # ── The Night Ledger (spec) ─────────────────────────────────
            # Battery state: live SOC → kWh; the sunrise floor reserves
            # tomorrow's need = max(reserve, the scheduler's target SOC).
            soc_kwh = max(0.0, float(soc or 0.0) / 100.0 * cap_kwh)
            reserve_pct = float(self.config.get("battery_priority_soc", 30) or 30)
            target_pct = float(getattr(getattr(scheduler, "decision", None),
                                       "target_soc", 0.0) or 0.0)
            floor_kwh = max(reserve_pct, target_pct) / 100.0 * cap_kwh
            max_discharge_w = float(
                self.config.get("battery_max_discharge_power", 5000.0) or 5000.0)
            # The SAME peak authority execution uses (finding #5, TEST night
            # 2026-07-30): the load manager's live target, config
            # ``target_peak_limit`` (kW) behind it. This used to read
            # ``config["peak_limit_w"]`` — a key NOTHING writes: not the config
            # flow, not a migration, nowhere in the repo outside its own
            # readers. So it was 0 on every install, the packer ran with
            # INFINITE headroom, and the plan handed a 10 kW EV slot to a house
            # on a 6 kW limit. A cap execution would enforce and the plan
            # ignores makes every "fits" verdict meaningless.
            # …and the limit is a SHED THRESHOLD, not a target to sit on
            # (finding #6, TEST night 2026-07-30) — the hysteresis-adjusted
            # level execution actually holds. ONE accessor for the ledger AND
            # the EV's peak-managed rate: see ``_planning_peak_w``.
            peak_w = float(self._planning_peak_w())

            # Home per slot: the weekday-aware hourly profile when trained,
            # else the flat night estimate (same fallback chain as the EV
            # peak-managed rate).
            hourly_home = None
            predictor = getattr(self, "_predictor", None)
            if predictor is not None:
                try:
                    hourly_home = predictor.predict_consumption_24h(now) or None
                except Exception:  # noqa: BLE001
                    hourly_home = None
            try:
                flat_home_w = float(self._expected_night_home_w(energy))
            except Exception:  # noqa: BLE001
                flat_home_w = 300.0

            def _home_at(t):
                if hourly_home:
                    i = int((t - now).total_seconds() // 3600)
                    # The profile appends 0.0 for hours it could not predict
                    # (trained_with_fallback) — a 0 W house is a data gap,
                    # not a forecast; fall through to the flat estimate.
                    if (0 <= i < len(hourly_home)
                            and hourly_home[i] is not None
                            and float(hourly_home[i]) > 0):
                        return float(hourly_home[i])
                return flat_home_w

            # Slots follow the market: honest None price when the day-ahead
            # has no data (the fingerprint replan re-derives later); the
            # level comes from the shared get_price_level_at accessor so the
            # plan packs exactly what execution's cheap-gate would fire on.
            # ONE pair of accessors for EVERY planner surface (night slots,
            # day slots, the tomorrow preview) — a second copy is how a
            # parallel price path starts (day_ledger.tariff_price_at).
            from .day_ledger import (align_to_step, market_step_s,
                                     tariff_cheap_at, tariff_price_at)
            prov = self._tariff_provider
            _price_at = lambda ts: tariff_price_at(prov, ts)  # noqa: E731
            _cheap_at = lambda ts: tariff_cheap_at(prov, ts)  # noqa: E731
            # (Rien's shape, 08-08) slots follow the MARKET: 15-min where
            # the published curve is 15-min, hourly where there is no
            # curve to ask. An hourly slot on a 15-min market wears its
            # first quarter's price for the whole hour and hides sub-hour
            # cheap windows.
            _step_s = market_step_s(prov)

            slots = []
            # Start AT the stamp (the 00:01 midnight-pause finding,
            # 09.08): the first slot is the PARTIAL remainder of the
            # current market interval, so a mid-interval re-plan can
            # continue an interrupted run instead of pausing it to the
            # next boundary. The loop's aligned ends return to the grid
            # from the second slot on; the gate's stamp-authority rule
            # (c45326f) now simply has a slot where it always claimed
            # authority.
            t = now.replace(microsecond=0)
            # (horizon-spanning) The DAY part — now → tonight's window
            # open. Expected-surplus hours arrive as price-0 slots capped
            # at the surplus W (day_ledger, sine-shaped from the scalar
            # forecast); with no forecast the day degrades to plain
            # priced slots — the horizon still spans, nothing free is
            # invented. Absent only when stamped inside the night.
            day_end = None
            try:
                _ns_s, _ = self.time_manager.get_night_window()
                _de = resolve_deadline(now, _ns_s)
                if _de is not None and _de < night_end:
                    day_end = _de
            except Exception:  # noqa: BLE001 — no window → night-only shape
                day_end = None
            if day_end is not None and t < day_end:
                day_kwh = 0.0
                sunrise = sunset = now
                try:
                    _fd = getattr(getattr(self, "_forecast_reader", None),
                                  "forecast_data", None)
                    day_kwh = float(getattr(
                        _fd, "forecast_remaining_today_kwh", 0.0) or 0.0)
                except Exception:  # noqa: BLE001 — no forecast, priced day
                    day_kwh = 0.0
                try:
                    _sr_h, _sr_m = (int(x) for x in
                                    self.time_manager.get_sunrise_time()
                                    .split(":"))
                    _ss_h, _ss_m = (int(x) for x in
                                    self.time_manager.get_sunset_plus_10_time()
                                    .split(":"))
                    sunrise = now.replace(hour=_sr_h, minute=_sr_m,
                                          second=0, microsecond=0)
                    sunset = now.replace(hour=_ss_h, minute=_ss_m,
                                         second=0, microsecond=0)
                except Exception:  # noqa: BLE001 — no curve, priced day
                    day_kwh = 0.0
                from .day_ledger import build_day_slots
                slots.extend(build_day_slots(
                    start=t, end=day_end, day_kwh=day_kwh,
                    sunrise=sunrise, sunset=sunset,
                    home_w_at=_home_at,
                    price_at=_price_at, level_cheap_at=_cheap_at,
                    # (#755) The sun is not free — it costs the feed-in you
                    # forgo. At 0 the packer preferred solar by fiat and a
                    # night hour cheaper than the export rate could never
                    # win; priced, the preference is economic and can lose.
                    export_rate=float(self.config.get(
                        "electricity_export_rate", 0.075) or 0.0),
                    step_s=_step_s,
                ))
                t = day_end
            while t < night_end:
                # Align to market boundaries even after an off-grid
                # day/night boundary (a 20:38 window open must not shift
                # every slot to :38 — prices change on the market grid).
                end = min(align_to_step(t + _td(seconds=_step_s), _step_s),
                          night_end)
                if end <= t:
                    end = min(t + _td(seconds=_step_s), night_end)
                slots.append(LedgerSlot(
                    start=t, end=end,
                    price=_price_at(t),
                    level_cheap=_cheap_at(t),
                    home_w=_home_at(t),
                ))
                t = end
            if not slots:
                _LOGGER.info(
                    "ENERGY-PLAN (%s #638): empty night window "
                    "(now past %s?) — no plan", tag, night_end)
                # An empty window is not a reason to erase a correct quiet
                # answer: with nothing to schedule, "nothing needs tonight"
                # is still what the card must show (it is what this branch
                # published before the answer moved below the ledger).
                self._energy_plan_shadow = (
                    _quiet_answer() if quiet_night else None)
                # No plan means no partial wait either — don't leave a clock
                # running that a later night would inherit.
                self._shadow_partial_since = None
                return True

            ledger = build_night_ledger(
                slots, soc_kwh=soc_kwh, floor_kwh=floor_kwh,
                max_discharge_w=max_discharge_w, peak_limit_w=peak_w)
            # ── Arbitrage advice (#638, the last string) ────────────────
            # The advisor reads the SAME walked ledger the pack consumes
            # — prices on both horizons, the home's hour-by-hour grid
            # draw, the SOC room, the power caps, tomorrow's forecast.
            # ADVICE ALWAYS (it is the framework's sharpest audit: if
            # the books lie anywhere, an absurd advice is the first
            # symptom); demand injection is config-gated OFF and nothing
            # actuates from it (#533 state — live proof post-1.8 on
            # Guido's call).
            arb = None
            try:
                from .arbitrage import arbitrage_advice
                try:
                    _fd2 = getattr(getattr(self, "_forecast_reader", None),
                                   "forecast_data", None)
                    _tom = float(getattr(
                        _fd2, "forecast_tomorrow_kwh", 0.0) or 0.0)
                except Exception:  # noqa: BLE001 — no forecast, no cap
                    _tom = 0.0
                # Never grid-charge what tomorrow's sun fills free:
                # tomorrow's production minus a flat 12-h daytime home
                # draw ≈ what could reach the battery unpaid. Over-
                # estimating the free sun UNDER-buys — restraint is the
                # safe direction for a shadow advisor.
                _tomorrow_free = max(0.0, _tom - flat_home_w * 12.0 / 1000.0)
                _adv = arbitrage_advice(
                    ledger,
                    soc_kwh=soc_kwh, capacity_kwh=cap_kwh,
                    max_charge_w=float(getattr(
                        getattr(scheduler, "_config", None),
                        "battery_max_charge_power_w", 5000.0) or 5000.0),
                    max_discharge_w=max_discharge_w,
                    round_trip_efficiency=float(self.config.get(
                        "battery_roundtrip_efficiency", 0.92) or 0.92),
                    # No flow surface yet — an options-dict override until
                    # the mode ships for real (post-1.8).
                    cycle_cost_per_kwh=float(self.config.get(
                        "battery_cycle_cost_per_kwh", 0.05) or 0.05),
                    tomorrow_free_kwh=_tomorrow_free,
                )
                _iso = lambda rows: [  # noqa: E731 — local shape adapter
                    {**b, "start": b["start"].isoformat(),
                     "end": b["end"].isoformat()} for b in rows]
                # (C7, Guido's PROD card 16.08) The advice is computed on
                # every stamp because it audits the ledger — but on an
                # install where arbitrage cannot act it is an instrument
                # readout, not an answer. Publish the gate WITH the verdict
                # so the card can stay silent about a closed feature while
                # diagnostics and the log line keep the full reading.
                _arb_on = self._arbitrage_enabled(
                    len(getattr(power, "batteries", {}) or {}))
                arb = {
                    "enabled": _arb_on,
                    "opportunity": _adv.opportunity,
                    "charge_kwh": _adv.charge_kwh,
                    "est_profit": _adv.est_profit,
                    "reason": _adv.reason,
                    "charge_blocks": _iso(_adv.charge_blocks),
                    "discharge_blocks": _iso(_adv.discharge_blocks),
                }
                _LOGGER.info("ENERGY-PLAN (%s) arbitrage: %s",
                             tag, _adv.reason)
                if _adv.opportunity and self.config.get(
                        "arbitrage_shadow_demand"):
                    # Worst priority is a hard property: the shadow cycle
                    # must never displace a real need from a slot.
                    labels["arbitrage:battery"] = None
                    demands.append(Demand(
                        id="arbitrage:battery", kind="battery",
                        energy_kwh=float(_adv.charge_kwh),
                        max_power_w=float(getattr(
                            getattr(scheduler, "_config", None),
                            "battery_max_charge_power_w", 5000.0) or 5000.0),
                        min_power_w=0.0,
                        deadline=night_end, priority=999, source="grid",
                    ))
            except Exception:  # noqa: BLE001 — advice must never cost a plan
                arb = None
            from .self_consumption import predict_self_consumption
            if quiet_night and not demands:
                # Nothing to pack — but the books are open now, so the quiet
                # answer carries what the ledger knows. (``demands`` can have
                # grown by exactly one above: with ``arbitrage_shadow_demand``
                # on, the shadow cycle IS tonight's plan and gets packed like
                # any other demand — that branch used to be unreachable.)
                self._energy_plan_shadow = _quiet_answer(
                    arb, _slot_rows(ledger),
                    predict_self_consumption(ledger, []).as_dict())
                return True
            plan = pack_night(demands, ledger, floor_kwh=floor_kwh,
                              max_discharge_w=max_discharge_w,
                              peak_limit_w=peak_w)
            real_ev = round(sum(d.energy_kwh for d in demands
                                if d.kind == "ev"), 2)
            _LOGGER.info(
                "ENERGY-PLAN (%s #638): %d demand(s), %d slot(s), "
                "est cost %.2f, fits=%s | EV %.1f kWh (per-charger map)",
                tag, len(demands), len(slots), plan.total_cost, plan.fits,
                real_ev,
            )
            if plan.takeover is not None:
                _LOGGER.info(
                    "ENERGY-PLAN (%s): battery carries home until "
                    "%s — the grid takes over from there "
                    "(floor %.1f kWh of %.1f kWh)",
                    tag, f"{plan.takeover:%H:%M}", floor_kwh, soc_kwh)
            else:
                _LOGGER.info(
                    "ENERGY-PLAN (%s): battery carries home through "
                    "the whole night (floor %.1f kWh of %.1f kWh)",
                    tag, floor_kwh, soc_kwh)
            for line in plan.summary_lines():
                _LOGGER.info("ENERGY-PLAN (%s): %s", tag, line)
            for a in plan.allocations:
                _LOGGER.debug("ENERGY-PLAN (%s) alloc: %s", tag, a.reason)
            # (#638 G3c) STRUCTURED shape for the card, beside the log-shaped
            # strings the diagnose payload has always carried. The card must
            # not have to parse "ev:x: YIELDS 1.5 kWh — 0.5/2.0 kWh (peak
            # cap)" back apart: the packer already has this as dataclasses,
            # so publish the fields, not the sentence. Both stay — the
            # strings are what the log lines and the soak notes quote.
            kind_of = {d.id: d.kind for d in demands}
            rows = [{
                "id": r.demand_id,
                "kind": kind_of.get(r.demand_id, "load"),
                # None = no device name to show; the card localizes by kind.
                "label": labels.get(r.demand_id),
                "status": r.status,
                "planned_kwh": round(r.planned_kwh, 2),
                "needed_kwh": round(r.needed_kwh, 2),
                "est_cost": round(r.est_cost, 2),
                "note": r.note or None,
            } for r in plan.results]
            # The ledger itself — the card's hour axis and battery
            # trajectory, in the ONE shape a quiet night draws too.
            slot_rows = _slot_rows(ledger)
            blocks = [{
                "id": a.demand_id,
                "start": a.start.isoformat(),
                "end": a.end.isoformat(),
                "power_w": round(a.power_w, 0),
                "price": a.price,
            } for a in plan.allocations]
            self._energy_plan_shadow = {
                "computed_at": now.isoformat(),
                "fits": plan.fits,
                "total_cost": plan.total_cost,
                "takeover": (plan.takeover.isoformat()
                             if plan.takeover is not None else None),
                "demands": rows,
                "slots": slot_rows,
                "blocks": blocks,
                "summary": plan.summary_lines() + (
                    # Say what was left OUT and why, next to what was packed
                    # (finding #4): "the plan has no EV line" reads identically
                    # whether the charger opted out or the builder lost it.
                    [f"ev opted out of the night by mode: "
                     f"{', '.join(mode_opted_out)}"] if mode_opted_out else []
                ) + (
                    # Same rule for an absent car (night 3): the missing EV
                    # line must say it was the plug, not the packer.
                    [f"ev not planned, no car connected: "
                     f"{', '.join(disconnected)}"] if disconnected else []),
                "allocations": [a.reason for a in plan.allocations],
                # (#638 C7) Every device deliberately left out, with a
                # MACHINE why — the card translates per user language.
                # Prose in ``summary`` is for logs, not for rendering.
                "not_scheduled": (
                    [{"id": f"ev:{c}", "why": "mode"} for c in mode_opted_out]
                    + [{"id": f"ev:{c}", "why": "disconnected"}
                       for c in disconnected]
                    + [{"id": f"ev:{c}", "why": "car_full"}
                       for c in car_full]
                    + left_out_loads),
                # None on a whole fleet. A string here means the battery
                # figures above cover a SUBSET — the plan is still the best
                # available answer, but it is not the fleet's answer (#638
                # finding #3). Never silently absent: a degraded plan that
                # reads like a healthy one is what made this bug invisible.
                "battery_fleet_partial": partial_note,
                # (night 3, finding 3) a re-stamped night must be
                # distinguishable from the first answer.
                "replan_cause": replan_cause,
                # (#638, the last string) the advisor's verdict with its
                # numbers — always present on a full plan, None only when
                # the advisor itself failed (never costs a plan).
                "arbitrage": arb,
                # (#755 pillar 2) The share of the horizon's solar this
                # schedule expects to keep, and how much of the keeping is
                # the plan's own doing rather than the house being awake.
                # Stated up front so the morning can be a comparison
                # instead of an anecdote.
                "self_consumption": predict_self_consumption(
                    ledger, blocks).as_dict(),
            }
            return True
        except Exception:  # noqa: BLE001 — shadow must never break the cycle
            # WARNING during the shadow soak: a swallowed failure here is
            # invisible in a 100-line journal window and cost a night of
            # verification. Never breaks the cycle either way. True: stamp
            # the night — one WARNING per night, not one per 10 s cycle.
            _LOGGER.warning("energy plan shadow failed (shadow-phase, "
                            "no impact on control)", exc_info=True)
            return True

    async def _send_notifications(
        self, charging_state, power, energy, costs, performance,
        charging_context, forecast_data, discharge_limit,
        calculated_current, available_power,
    ) -> None:
        """Send state-change and event-based notifications (#29).

        Extracted from _async_update_data to reduce cyclomatic complexity.

        v1.6.9 multi-charger: when ``_effective_states_per_charger`` was
        populated by the per-charger loop, dispatch one
        ``notify_state_change`` per charger with its own ``charger_id``
        and flap-suppression key so a state change on charger A doesn't
        suppress one on charger B. Single-charger setups (empty dict)
        fall back to the fleet-level call — identical behaviour to
        v1.6.8.
        """
        common_data = {
            "battery_soc": power.battery_soc,
            "calculated_current": calculated_current,
            "available_power": available_power,
            "daily_ev_energy": energy.daily_ev,
            "charging_strategy": charging_context.charging_strategy,
            "charging_strategy_reason": charging_context.charging_strategy_reason,
            "canonical_strategy": charging_context.canonical_strategy,
            "discharge_limit": discharge_limit,
            # (#631) the authoritative per-charger night remaining — what the
            # night decision actually consumed this cycle.
            "night_remaining_map": dict(
                getattr(self, "_night_target_per_charger_map", None) or {}),
        }
        per_charger_states = getattr(self, "_effective_states_per_charger", None) or {}
        if per_charger_states:
            # (#584) Don't push charging notifications for a charger with no car
            # connected. A charger with its own plug sensor uses its real state;
            # one without falls back to the fleet ``ev_connected`` (unchanged) —
            # so RienduPre's car-less "Laadpaal Links" stops firing a false
            # "solar charging started" whenever the OTHER charger has a car.
            conn_map = getattr(power, "ev_connected_per_charger", None) or {}
            for cid, (eff_state, name) in per_charger_states.items():
                if not conn_map.get(cid, power.ev_connected):
                    continue
                await self._notification_manager.notify_state_change(
                    eff_state, common_data, charger_id=cid, charger_name=name,
                )
        else:
            await self._notification_manager.notify_state_change(
                charging_state, common_data,
            )

        try:
            if power.battery_soc >= 99.5:
                await self._notification_manager.notify_battery_full(power.battery_soc)

            peak_pct = performance.current_vs_peak_percentage if hasattr(performance, 'current_vs_peak_percentage') else 0
            if peak_pct > 90:
                await self._notification_manager.notify_high_grid_import(power.grid_import_power, peak_pct)

            now = dt_util.now()
            if now.hour == 20 and now.minute < (self.config.get("update_interval", 30) // 60 + 1):
                await self._notification_manager.notify_daily_summary({
                    "daily_solar": energy.daily_solar,
                    "daily_home": energy.daily_home,
                    "autarky_rate": performance.autarky_rate,
                    "daily_savings": costs.daily_savings if hasattr(costs, 'daily_savings') else 0,
                    "daily_ev": energy.daily_ev,
                    "daily_net_cost": costs.daily_net_cost if hasattr(costs, 'daily_net_cost') else 0,
                    "forecast_tomorrow": forecast_data.forecast_tomorrow_kwh,
                })

            if (now.hour == 19
                    and forecast_data.forecast_tomorrow_kwh > 0
                    and forecast_data.forecast_tomorrow_kwh < 5):
                await self._notification_manager.notify_forecast_alert(
                    forecast_data.forecast_tomorrow_kwh
                )
            # EV Intelligence notifications — per-charger (#106, #193)
            per_charger_intel = self._build_per_charger_intelligence()
            chargers_cfg_by_id = {
                c["id"]: c for c in (self.config.get("ev_chargers") or [])
                if isinstance(c, dict) and "id" in c
            }
            for cid, intel in per_charger_intel.items():
                charger_name = self._ev_devices[cid].name if cid in self._ev_devices else cid
                charger_connected = self._last_ev_connected_per_charger.get(cid, False)
                # ``or 0`` covers both missing key AND None value — the
                # latter arises for chargers whose per-charger intel
                # builder hasn't populated the field yet (e.g. mock
                # chargers without a real upstream sensor). Without the
                # coercion the subsequent ``> 0`` comparison raised
                # ``TypeError`` every cycle (DEBUG log spam observed on
                # HA-TEST 2026-05-31 after the v1.6.14 deploy).
                mins_to_full = intel.get("minutes_to_full") or 0

                # Per-charger draw — gate nearly-full on THIS charger's
                # power, not the fleet flag. In a multi-charger fleet,
                # ``power.ev_charging`` is True whenever any charger is
                # drawing, which would fire nearly-full for an idle
                # charger that happens to have a stale ``minutes_to_full``
                # carry-over. ``ev_power_per_charger`` may be unpopulated
                # on single-charger installs — fall back to the fleet
                # flag in that case (still correct: one charger means
                # the fleet flag IS that charger's flag). #351 M6.
                per_charger_power = getattr(power, "ev_power_per_charger", None) or {}
                this_charger_drawing = (
                    (per_charger_power.get(cid) or 0) > 0
                    if per_charger_power
                    else bool(power.ev_charging)
                )

                # Nearly full: taper detector shows < 5 minutes remaining.
                # Pure informational — does NOT gate the charge command.
                # (#440: skip + recommended notifications removed — they
                # were gated on estimated_soc, which is no longer load-
                # bearing in any decision path.)
                if mins_to_full > 0 and mins_to_full < 5 and this_charger_drawing:
                    await self._notification_manager.notify_ev_nearly_full(
                        mins_to_full, charger_name=charger_name
                    )

                # #708 — estimate-stop / auto-resume announcements. The
                # decision itself lives in _calculate_remaining_need
                # (effective SOC = max(sensor, energy-accounted)); this
                # block only detects the two user-visible transitions:
                # the estimate ends a charge the stale sensor would have
                # kept running, and a fresh reading below target makes
                # SEM resume. Latch lives on the per-charger detector
                # (session-scoped, cleared on disconnect).
                det_708 = self._ev_taper_detectors.get(cid)
                cfg_708 = chargers_cfg_by_id.get(cid) or {}
                type_708 = (
                    cfg_708.get("ev_target_type") or cfg_708.get("ev_target_mode")
                    or self.config.get("ev_target_type")
                    or self.config.get("ev_target_mode", "kwh")
                )
                ea_708 = intel.get("energy_accounted_soc")
                soc_708 = intel.get("vehicle_soc")
                if (det_708 is not None and charger_connected
                        and type_708 == "soc"
                        and ea_708 is not None and soc_708 is not None):
                    cap_708 = (
                        cfg_708.get("ev_battery_capacity_kwh")
                        or self.config.get("ev_battery_capacity_kwh", 40)
                    )
                    for bound_708 in ("min", "max"):
                        tgt = self._resolve_target(
                            cfg_708, "ev_target_soc", bound_708, 80, 100
                        )
                        # (#708) same helper as the decision — see SITE 1.
                        need_708 = soc_remaining_need(
                            tgt, soc_708, ea_708, cap_708)
                        sensor_rem = need_708.sensor_kwh or 0.0
                        eff_rem = need_708.effective_kwh or 0.0
                        if (not det_708._estimate_stop_active
                                and sensor_rem > 0.1 and eff_rem <= 0.1):
                            det_708._estimate_stop_active = True
                            await self._notification_manager.notify_ev_estimate_stop(
                                target_soc=tgt, sensor_soc=soc_708,
                                sensor_age_min=intel.get("vehicle_soc_age_min") or 0,
                                charger_name=charger_name, flag_key=cid,
                            )
                            break
                        if det_708._estimate_stop_active and eff_rem > 0.1:
                            det_708._estimate_stop_active = False
                            await self._notification_manager.notify_ev_estimate_resume(
                                sensor_soc=soc_708, target_soc=tgt,
                                charger_name=charger_name, flag_key=cid,
                            )
                            break

        except (ValueError, TypeError) as e:
            _LOGGER.debug("Event notification failed: %s", e)
        except HomeAssistantError as e:
            _LOGGER.warning("Notification service call failed: %s", e)

    async def _retry_ev_device_with_backoff(self) -> None:
        """Retry EV device setup with exponential backoff (#27).

        Retries at increasing intervals: 10s, 20s, 40s, 80s, 160s, 320s.
        After max retries, creates a persistent notification so the user knows.
        """
        import time as _time

        if not hasattr(self, '_ev_retry_count'):
            self._ev_retry_count = 0
            self._ev_retry_next_at = 0.0

        now = _time.monotonic()
        if now < self._ev_retry_next_at:
            return  # Still in backoff period

        if self._ev_retry_count >= 10:
            return  # Give up after 10 retries

        self._ev_retry_count += 1
        backoff_seconds = min(320, 10 * (2 ** (self._ev_retry_count - 1)))
        self._ev_retry_next_at = now + backoff_seconds

        try:
            await self._retry_ev_device_setup()
            if self._ev_device or self._ev_devices:
                charger_count = len(self._ev_devices) if self._ev_devices else (1 if self._ev_device else 0)
                _LOGGER.info("EV device(s) discovered on retry %d (%d charger(s))", self._ev_retry_count, charger_count)
                self._ev_retry_count = 999  # Stop retrying
        except (HomeAssistantError, ValueError, AttributeError) as e:
            level = logging.WARNING if self._ev_retry_count >= 3 else logging.DEBUG
            _LOGGER.log(
                level,
                "EV device retry %d/10 failed (next in %ds): %s",
                self._ev_retry_count, backoff_seconds, e,
            )
            if self._ev_retry_count >= 10:
                _LOGGER.warning(
                    "EV charger not found after %d retries — EV control disabled. "
                    "Check that the KEBA integration is loaded.",
                    self._ev_retry_count,
                )

    def refresh_detection_report(self) -> None:
        """(#814 Pillar B) Rebuild the detection evidence report from the
        entity registry. Called at setup and after a late discovery; the
        result is published every cycle (``detection_report`` on
        coordinator.data → diag sensor attribute + diagnostics download +
        the Config tab's Detected-hardware section). Read-only, cheap."""
        try:
            from ..hardware_detection import build_detection_report
            self._detection_report = build_detection_report(self.hass)
        except Exception:  # noqa: BLE001 — evidence must never cost setup
            _LOGGER.debug("detection report skipped", exc_info=True)
            self._detection_report = None

    async def _retry_ev_device_setup(self) -> None:
        """Retry EV device setup if KEBA wasn't available at startup."""
        from ..hardware_detection import discover_ev_charger_from_registry
        from ..devices.base import CurrentControlDevice, resolve_max_current

        ev_auto = discover_ev_charger_from_registry(self.hass)
        if not ev_auto or not ev_auto.get("ev_charger_service"):
            return

        _LOGGER.info("Late-discovered EV charger: %s", list(ev_auto.keys()))
        self.refresh_detection_report()

        ev_device = CurrentControlDevice(
            hass=self.hass,
            device_id="ev_charger",
            name="EV Charger",
            priority=self.config.get("ev_surplus_priority", 3),
            min_current=6.0,
            # (#746) one resolver — see devices.base.resolve_max_current.
            max_current=resolve_max_current(self.config.get),
            phases=int(self.config.get("ev_phases", 3)),
            voltage=230.0,
            power_entity_id=ev_auto.get("ev_charging_power_sensor"),
            charger_service=ev_auto.get("ev_charger_service"),
            charger_service_entity_id=ev_auto.get("ev_charger_service_entity_id"),
            current_entity_id=ev_auto.get("ev_current_control_entity"),
        )
        # Per-integration charger profile (#82)
        if ev_auto.get("ev_service_param_name"):
            ev_device.service_param_name = ev_auto["ev_service_param_name"]
        if ev_auto.get("ev_service_device_id"):
            ev_device.service_device_id = ev_auto["ev_service_device_id"]
        if ev_auto.get("ev_start_stop_entity"):
            ev_device.start_stop_entity = ev_auto["ev_start_stop_entity"]
        if ev_auto.get("ev_charge_mode_entity"):
            ev_device.charge_mode_entity = ev_auto["ev_charge_mode_entity"]
            ev_device.charge_mode_start = ev_auto.get("ev_charge_mode_start")
            ev_device.charge_mode_stop = ev_auto.get("ev_charge_mode_stop")
        if ev_auto.get("ev_start_service"):
            ev_device.start_service = ev_auto["ev_start_service"]
            import json as _json
            ev_device.start_service_data = _json.loads(ev_auto.get("ev_start_service_data", "{}"))
        if ev_auto.get("ev_stop_service"):
            ev_device.stop_service = ev_auto["ev_stop_service"]
            import json as _json
            ev_device.stop_service_data = _json.loads(ev_auto.get("ev_stop_service_data", "{}"))
        self._surplus_controller.register_device(ev_device)
        self._ev_device = ev_device
        ev_device.managed_externally = True
        self._ev_retry_count = 999  # Stop retrying

        # Update sensor reader with discovered entities
        # Map discovery keys to sensor_reader config keys (they differ!)
        key_map = {
            "ev_connected_sensor": "ev_plug_sensor",
            "ev_charging_sensor": "ev_charging_sensor",
            "ev_total_energy_sensor": "ev_total_energy_sensor",
        }
        for discover_key, reader_key in key_map.items():
            value = ev_auto.get(discover_key)
            if value and not getattr(self._sensor_reader.config, reader_key, None):
                setattr(self._sensor_reader.config, reader_key, value)
                _LOGGER.info("Set sensor reader %s = %s", reader_key, value)

        _LOGGER.info("EV charger registered via late discovery: service=%s", ev_auto.get("ev_charger_service"))

    # ─── Legacy strategy machine removed (arch Step 7) ──────────
    # _determine_charging_strategy / _self_consumption_strategy /
    # _zone_based_strategy / _canonical_strategy_from_legacy and the
    # zone helpers (_raw_zone, _get_zone, _debounce_zone) all lived
    # here. The new architecture (coordinator/decide.py) replaces
    # every per-charger decision they made. See PR #358.


    def _resolve_target(
        self, cfg: dict, base_key: str, bound: str, default: float, full: float,
    ) -> float:
        """Resolve the floor (Min) or ceiling (Max) charge target (#245).

        The existing single-value key (e.g. ``daily_ev_target``) is the FLOOR
        (Min) — the grid-guaranteed amount that night charging tops up to. Night
        behaviour is therefore identical to pre-#245 and needs no migration.

        The new ``{base_key}_max`` key is the optional solar CEILING (Max):
        surplus charging may continue past Min up to Max. When Max is unset it
        defaults to ``full`` (100% / 100 kWh) — i.e. "charge freely from the sun",
        which preserves the pre-#245 default (surplus runs to car-full). Setting a
        Max below full caps surplus. Max is clamped to ``>= Min`` so a misconfigured
        Max can never fall below the guaranteed floor. (The old ev_limit_surplus
        switch was folded into Max: Max < full == limit on.)
        """
        min_val = cfg.get(base_key) if cfg.get(base_key) is not None else self.config.get(base_key, default)
        if bound == "min":
            return min_val
        max_key = f"{base_key}_max"
        max_val = cfg.get(max_key) if cfg.get(max_key) is not None else self.config.get(max_key)
        if max_val is None:
            return full
        return max(max_val, min_val)

    def _maybe_warn_soc_cap(self, cid, charger_cfg, real_soc, charging_state) -> None:
        """#526: raise/clear a repair when a SOC-% charge cap can't be enforced.

        A ``%`` target needs a readable vehicle SOC to stop at the cap. When the
        car isn't reporting SOC (``real_soc is None``) but the charger is
        actively solar-charging, SEM keeps charging to taper (RienduPre: "car
        went past 80%"). Surface it as a persistent repair instead of silently
        overshooting; clear it the moment a real SOC returns or the charger
        stops / isn't on a SOC target.

        (#708) ``charging_state`` is the FLEET state — the per-charger loop
        hands the same value to every charger, so one car drawing raised the
        repair on every box in the fleet, each naming its own target. Live on
        beta.9 with two EVSEs and one car (Azlinon). That is the fleet-read
        class (#616): a per-charger surface gated on a fleet term. The
        connected state is the missing per-charger half —
        ``_last_ev_connected_per_charger[cid]``, the same map the virtual-SOC
        decay gates on (#648) and the source of
        ``binary_sensor.sem_charger_<id>_connected``.

        A charger the map has not seen yet (first cycle after a restart, or no
        connected sensor) defaults to True: the fallback is the pre-#708
        behaviour, so missing tracking can never silently disable the cap
        warning on a charger that does have a car on it.
        """
        cfg = charger_cfg or {}
        ttype = (cfg.get("ev_target_type") or cfg.get("ev_target_mode")
                 or self.config.get("ev_target_type") or "kwh")
        connected = (getattr(self, "_last_ev_connected_per_charger", None)
                     or {}).get(cid, True)
        charging = charging_state in self.SOLAR_CHARGING_STATES
        from . import repair_issues as _ri
        if ttype == "soc" and real_soc is None and charging and connected:
            target = self._resolve_target(cfg, "ev_target_soc", "max", 80, 100)
            _ri.raise_soc_cap_unenforceable(
                self.hass, cid, name=cfg.get("name") or "EV", target_soc=target,
            )
        else:
            _ri.clear_soc_cap_unenforceable(self.hass, cid)

    def _resolve_charger_soc(self, cid: str, cfg: dict) -> float | None:
        """Per-charger vehicle SOC: real sensor, else anchored virtual SOC, else None."""
        ent = cfg.get("vehicle_soc_entity")
        if ent:
            st = self.hass.states.get(ent)
            if st and st.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    return float(st.state)
                except (ValueError, TypeError):
                    pass
        det = (getattr(self, "_ev_taper_detectors", {}) or {}).get(cid)
        if det is not None and getattr(det, "_soc_anchored", False):
            return det.get_virtual_soc(None)
        return None

    def _calculate_remaining_need(
        self, energy, vehicle_soc: float | None = None, charger_cfg: dict | None = None,
        bound: str = "min",
    ) -> float:
        """Calculate remaining EV charging need in kWh.

        Clean ``if SOC else kWh`` branch — no fallback, no cross-mode
        contamination (#446). The mode is the saved per-charger
        ``ev_target_type`` (with legacy ``ev_target_mode`` for back-compat),
        falling back to the integration-level default, then "kwh".

        The Configuration tab GUI is the gatekeeper that ensures
        ``ev_target_type="soc"`` is only ever saved when a real
        ``vehicle_soc_entity`` is configured (#446 GUI gate), and the
        v10 → v11 schema migration cleans up any pre-existing entries
        that had the bad combination on disk (#446 migration). The
        runtime trusts the saved config — no override, no rescue path.

        Branches:
          * **SOC branch:** compute ``(target_soc − vehicle_soc) × capacity``.
            If the user's real SOC sensor is momentarily ``unavailable``,
            return the full ``ev_capacity`` as the remaining need so SEM
            keeps charging — taper detection (hardware-level) is the
            real "full" stop. Never substitutes ``estimated_soc``.
          * **kWh branch:** ``daily_target − delivered_today`` for this
            specific charger (per #351 H1 per-charger accounting).

        ``bound`` selects which target to measure against (#245):
          * ``"min"`` (default): the guaranteed-floor target. Night /
            grid tops up to this.
          * ``"max"`` (ceiling): surplus charges up to this then stops.
            Defaults to "effectively unlimited" when no Max is set.
        """
        cfg = charger_cfg or {}
        ev_capacity = (
            cfg.get("ev_battery_capacity_kwh")
            if cfg.get("ev_battery_capacity_kwh") is not None
            else self.config.get("ev_battery_capacity_kwh", 40)
        )
        # ``ev_target_mode`` was renamed to ``ev_target_type`` (#235); read
        # both for back-compat. Per-charger config wins over the
        # integration-level default.
        ev_target_type = (
            cfg.get("ev_target_type") or cfg.get("ev_target_mode")
            or self.config.get("ev_target_type")
            or self.config.get("ev_target_mode", "kwh")
        )

        if ev_target_type == "soc":
            # Pre-condition guaranteed by GUI gate + v10→v11 migration:
            # a real ``vehicle_soc_entity`` is configured for this charger.
            #
            # #708 — the sensor value may be MINUTES old (OnStar polls every
            # 30; overshoot = lag × power). The pack cannot be emptier than
            # the last reading plus what this session measurably delivered
            # since, so the effective SOC is ``max(sensor, energy-accounted)``.
            # The sensor stays primary: every fresh value re-anchors the
            # estimate and wins (this is a CAP, not the #446-forbidden
            # substitution — the virtual/estimated SOC is still never used
            # here). When a later reading lands below target, the need goes
            # positive again and charging auto-resumes — the resumes are
            # spaced by the sensor's own update interval, and each round
            # shrinks, so the floor promise is kept without flapping.
            ceiling_soc = None
            detectors = getattr(self, "_ev_taper_detectors", None)
            det = detectors.get(cfg.get("id")) if (detectors and cfg) else None
            if det is None and detectors:
                det = self._ev_taper_detector  # primary (single-charger installs)
            if det is not None:
                ceiling_soc = det.energy_accounted_soc()
            soc_target = self._resolve_target(cfg, "ev_target_soc", bound, 80, 100)
            # (#708) ONE source for the effective-SOC remaining — same helper
            # the estimate-stop announcement uses, so the message can never
            # claim a stop the decision did not make. The measured ceiling
            # only ever caps (pulls the stop earlier); the speculative
            # estimate is not an input (#446).
            need = soc_remaining_need(
                soc_target, vehicle_soc, ceiling_soc, ev_capacity)
            if need.effective_kwh is None:
                # No sensor, no anchor: pre-#708 fallback — charge to taper.
                return float(ev_capacity)
            return need.effective_kwh

        # kWh branch — the default mode for installs without a SOC sensor.
        daily_target = self._resolve_target(cfg, "daily_ev_target", bound, 10, 100)
        # #351 H1 — for a per-charger call (``charger_cfg`` provided),
        # subtract THIS charger's daily energy, not the fleet total.
        # Pre-fix charger B's "target reached" check was polluted by
        # charger A's energy: ``daily_target - energy.daily_ev`` would
        # underreport B's remaining need (or fire target-reached
        # spuriously) the moment A drew any energy.
        cid = cfg.get("id") if cfg else None
        # Display-consistent basis (#536 / night-idle 2026-07-17): the raw
        # per-charger integrator can drift from the persisted global the
        # dashboard shows; measure the target against the DISPLAYED figure.
        consumed = (
            self._charger_daily_kwh(cid, energy) if cid else energy.daily_ev
        )
        return max(0, daily_target - consumed)

    def _build_fleet_cycle_state(
        self, power: PowerReadings, energy: Any,
    ) -> "FleetCycleState":
        """Build the per-cycle FleetCycleState that every charger's
        ``decide()`` sees this cycle.

        The single point of resolution for ALL fleet-level inputs:
        forecast_remaining, tariff_level, is_night, and the power
        readings + config snapshot. Both ``_build_charging_context``
        (for the primary view) and the multi-charger loop in
        ``_async_update_data`` consume this same object — so a new
        fleet input added here lands automatically in every charger's
        view, no per-call kwarg threading required.

        This eliminates the gap class that produced the v1.7 prep
        SOLAR_ONLY redirect / tariff_level / night-plan ordering
        regressions. The AST lint at
        ``tests/test_fleet_state_completeness.py`` keeps the
        invariant by forbidding any ``build_charger_view`` caller
        from bypassing this state.
        """
        from .charger_types import FleetCycleState

        # Forecast (dampened solar remaining today).
        forecast_remaining = 0.0
        try:
            forecast = self._cycle_forecast
            if forecast.available:
                forecast_remaining = self._forecast_tracker.apply_dampening(
                    forecast.forecast_remaining_today_kwh
                )
        except Exception:
            pass

        # Tariff price level (#524). The provider exposes ``get_price_level()``
        # (a PriceLevel enum) — there is NO ``current_level`` attribute, so the
        # old read of that non-existent attribute ALWAYS returned None. That
        # left FleetView.tariff_level dead for the whole EV decision layer:
        # solar_plus_cheap / min_plus_solar never saw their expensive windows,
        # so the daytime tariff pause never engaged. Read the canonical API and
        # take the enum's string value (same value the ``tariff_price_level``
        # sensor publishes via to_data()).
        tariff_level: Optional[str] = None
        try:
            provider = getattr(self, "_tariff_provider", None)
            if provider is not None and getattr(provider, "available", True):
                level = provider.get_price_level()
                level = getattr(level, "value", level)  # PriceLevel enum → str
                if isinstance(level, str):
                    tariff_level = level
        except Exception:
            tariff_level = None

        # #576 — the home battery's slot in the ONE priority list + whether
        # it's under an explicit command this cycle. The EV reclaim gate
        # (energy_reclaim.ev_reclaims_battery_charge) compares each charger's
        # ev_priority against battery_priority, and never reclaims while the
        # battery is commanded (force/scheduled/arbitrage — U6).
        battery_priority: Optional[int] = None
        # Known whenever there's a live battery reading (not the card's latched
        # flag — this must be right from cycle 1). When SOC is momentarily
        # unavailable → None → the EV yields (matches the pre-#576 default of
        # subtracting battery_charge when SOC reads as 0).
        reg = getattr(self, "_device_registry", None)
        if reg is not None and getattr(power, "battery_soc", None) is not None:
            try:
                battery_priority = reg.battery_surplus_priority()
            except Exception:
                battery_priority = None

        # (#747) the peak posture, resolved the same way the surplus
        # update resolves it — ONE vocabulary for both engines.
        from .surplus_controller import effective_peak_state
        try:
            _peak_state = effective_peak_state(
                self._load_manager.get_state() if self._load_manager else None,
                bool(getattr(self, "_vpp_shed_loads", False)),
            )
        except Exception:  # noqa: BLE001 — no LM yet (early startup)
            _peak_state = None
        # Enum → its string value; absent → "normal" (fresh install / LM off).
        _peak_state = str(getattr(_peak_state, "value", _peak_state)
                          or "normal").lower()

        return FleetCycleState(
            power=power,
            config=self.config,
            peak_state=_peak_state,
            is_night=self.time_manager.is_night_mode(),
            tariff_level=tariff_level,
            forecast_remaining_kwh=float(forecast_remaining),
            # (#778) Tonight's budget, computed a step earlier from measured
            # inputs. 0.0 until the evidence exists — never a guess.
            battery_spendable_kwh=float(
                (getattr(self, "_planning_evidence", None) or {})
                .get("battery_spendable_kwh") or 0.0),
            battery_priority=battery_priority,
            battery_commanded=self._battery_commanded(),
            curtailment_grant_w=self._curtailment_grant_w(power),
        )

    def _curtailment_grant_w(self, power) -> float:
        """#743 — one probe tick per cycle; the grant rides the fleet
        state into every charger's surplus. Opt-in
        (``curtailment_probe_enabled``, default off) — disabled, the
        probe stays in state 'off' and this returns 0.0 every cycle.
        See ``coordinator/curtailment.py`` for the state machine.
        """
        try:
            from .curtailment import CurtailmentProbe, ProbeInputs

            probe = getattr(self, "_curtailment_probe", None)
            if probe is None:
                probe = CurtailmentProbe()
                self._curtailment_probe = probe
            enabled = bool(self.config.get("curtailment_probe_enabled", False))
            if not enabled:
                # Cheap early-out, but tick once so the state reads 'off'.
                probe.tick(
                    ProbeInputs(
                        enabled=False, expected_w=0.0, production_w=0.0,
                        export_w=0.0, home_w=0.0, battery_charge_w=0.0,
                        ev_draw_w=0.0, ev_connected=False,
                        ev_wants_solar=False, probe_floor_w=0.0,
                    ),
                    now=time.monotonic(),
                )
                self._curtailment_last = {"state": probe.state, "grant_w": 0.0}
                return 0.0

            # RAW forecast "power now" — no forecast, no suspicion.
            # Deliberately NOT dampened (#743 follow-up): the dampening
            # factor is computed live from today's actual-vs-forecast
            # ratio, and a curtailed day's actual is clamped to
            # consumption — so on exactly the day the probe exists for,
            # the dampened value sinks toward what the inverter shows
            # and the probe measures its own blindness. Same class the
            # 1.8 half fixed one layer up ("every dampened consumer
            # under-plans exactly the hidden kilowatts the probe
            # reveals") — the probe is also a dampened consumer.
            # Optimism costs one bounded failed probe, which is the
            # probe's whole design.
            expected_w = 0.0
            try:
                forecast = self._cycle_forecast
                if forecast.available:
                    expected_w = float(forecast.power_now_w)
            except Exception:  # noqa: BLE001
                expected_w = 0.0

            from ..consts.ev_charge_modes import effective_charge_mode_for
            from .sensor_reader import parse_export_limited

            solar_modes = ("solar_only", "min_plus_solar", "solar_plus_cheap")
            chargers = [
                c for c in (self.config.get("ev_chargers") or [])
                if isinstance(c, dict)
            ] or [{}]
            wants_solar = False
            floor_w = 4140.0
            for cfg in chargers:
                try:
                    mode = effective_charge_mode_for(self.hass, self.config, cfg)
                except Exception:  # noqa: BLE001
                    mode = None
                if mode in solar_modes:
                    wants_solar = True
                    floor_w = (
                        float(cfg.get("ev_min_current")
                              or self.config.get("ev_min_current") or 6)
                        * float(cfg.get("ev_voltage")
                                or self.config.get("ev_voltage") or 230)
                        * float(cfg.get("ev_phases")
                                or self.config.get("ev_phases") or 3)
                    )
                    break

            # Brand sharpening: manual override wins, else autodetect on
            # the solar sensor's device (Huawei/GoodWe/SolaX/Victron/…).
            export_limited = None
            limit_entity = (
                self.config.get("export_limit_entity")
                or self._sensor_reader.detect_export_limit_entity(
                    self.config.get("solar_production_sensor"),
                )
            )
            if limit_entity:
                st = self.hass.states.get(limit_entity)
                if st is not None:
                    export_limited = parse_export_limited(
                        st.state,
                        st.attributes.get("unit_of_measurement"),
                    )

            grant = self._curtailment_probe.tick(
                ProbeInputs(
                    enabled=True,
                    expected_w=expected_w,
                    production_w=float(power.solar_power or 0.0),
                    export_w=float(power.grid_export_power or 0.0),
                    home_w=float(power.home_consumption_power or 0.0),
                    battery_charge_w=float(power.battery_charge_power or 0.0),
                    # FLEET-READ: the probe reasons about the whole
                    # house's energy balance (production vs total local
                    # consumption) — the fleet sum is the correct term.
                    ev_draw_w=float(power.ev_power or 0.0),
                    ev_connected=bool(power.ev_connected),
                    ev_wants_solar=wants_solar,
                    probe_floor_w=floor_w,
                    export_limited=export_limited,
                ),
                now=time.monotonic(),
            )
            grant = float(grant or 0.0)
            # Every tick records the terms it judged (#743). A probe that
            # DECLINES leaves no trace in the meters, so without this a
            # live "why didn't it fire?" has six indistinguishable
            # answers. Read-only; the trace copies it, nothing reads it
            # back into a decision.
            from .curtailment import marks_day_curtailed
            if marks_day_curtailed(probe.state):
                # (#743) today's measured solar is clamped to consumption —
                # a poisoned sample for the dampening tracker.
                self._curtailment_day = dt_util.now().date()
            self._curtailment_last = {
                "state": probe.state,
                "grant_w": round(grant),
                "expected_w": round(expected_w),
                "production_w": round(float(power.solar_power or 0.0)),
                "export_w": round(float(power.grid_export_power or 0.0)),
                "export_limited": export_limited,
                "limit_entity": limit_entity or None,
                "wants_solar": wants_solar,
                "floor_w": round(floor_w),
            }
            return grant
        except Exception:  # noqa: BLE001 — the probe must never break a cycle
            self._curtailment_last = {"state": "error", "grant_w": 0.0}
            return 0.0

    def _battery_commanded(self) -> bool:
        """True iff the home battery is under an explicit charge/discharge
        command (force_charge / scheduled / arbitrage). A commanded battery is
        honored, never reclaimed (#576 U6).

        Read by TWO callers with DIFFERENT timing — both correct:
        - ``_build_fleet_cycle_state`` (Step 6, BEFORE the battery pipeline):
          reads the PREVIOUS cycle's decision — the committed hardware state
          going into this cycle. The EV must decide before the battery runs, so
          guarding on last cycle's command is right (the battery is still under
          it).
        - the surplus/loads block (Step 8, AFTER battery control at 7.5c+d):
          reads THIS cycle's decision.
        Reads ``_last_battery_decisions`` (intent stored as its ``.value``
        string). ``scheduled`` night charge emits ``force_charge`` — covered,
        no U6 leak."""
        decisions = getattr(self, "_last_battery_decisions", None) or {}
        return any(
            d.get("intent") in ("force_charge", "force_discharge")
            for d in decisions.values()
        )

    def _build_charging_context(
        self,
        power: PowerReadings,
        energy: Any,
    ) -> ChargingContext:
        """Build charging context for state machine.

        Assembles all inputs the state machine needs: battery flags, EV
        budget, charging strategy (from SOC zones), and night-specific
        fields (NT period, night end time, EV max power, forecast-adjusted
        night target). Computes the canonical EV budget once via
        ``flow_calculator.calculate_canonical_ev_budget`` and caches it
        on ``self._cycle_ev_budget`` so the actuator can read the
        same value on the same cycle (#282 Phase B/D unification).

        Args:
            power: Current sensor readings.
            energy: Daily/monthly energy totals.

        Returns:
            Populated ChargingContext for state machine decision.
        """
        # Calculate charging-related flags.
        # Note: `battery_priority_soc` was previously read here with default 80,
        # while `_calculate_charging_strategy` (above) reads it with default 30.
        # Same key, two semantics — see #98. The 4-zone strategy meaning is
        # canonical: SOC below this = "all solar to battery, EV blocked".
        # The legacy "needs priority" check is just a safety gate and works
        # correctly with the 30 default too (it just unblocks earlier).
        # ``battery_minimum_soc`` retired (misleading "hard stop" — never
        # gated discharge). The legacy ``battery_too_low`` safety flag now
        # references the canonical zone floor ``battery_priority_soc``
        # (this whole legacy state-machine feed is removed in the legacy
        # retirement; the repoint keeps it sane until then).
        battery_priority_soc = self.config.get("battery_priority_soc", 30)

        battery_too_low = power.battery_soc < battery_priority_soc
        battery_needs_priority = power.battery_soc < battery_priority_soc
        # Ceiling (Max, default full) gates the surplus stop; floor (Min) drives
        # night top-up (#245). Resolve the (primary) charger's config so the base
        # context honors the PER-CHARGER targets, not just global. One car per
        # charger; the multi-charger loop still overrides per charger downstream.
        # #351 M9 — capture the cycle SOC into a local before the two
        # calls so both reads see the same value (mirrors the
        # per-charger-loop fix above).
        _primary_cfg = self._primary_charger_cfg()
        cycle_soc_local = self._cycle_vehicle_soc
        remaining = self._calculate_remaining_need(
            energy, cycle_soc_local, _primary_cfg, bound="max"
        )
        remaining_floor = self._calculate_remaining_need(
            energy, cycle_soc_local, _primary_cfg, bound="min"
        )
        # "daily_target_reached" here means the surplus CEILING (Max) is reached.
        daily_target_reached = remaining <= 0.1

        # Surplus stops at the Max ceiling (#245). Max defaults to full, so by
        # default this is only true at car-full — i.e. surplus charges freely.
        # (The ev_limit_surplus switch from #235 was folded into Max.)
        soc_limit_active = daily_target_reached

        # Calculate excess solar
        excess_solar = power.solar_power - power.home_consumption_power - power.battery_charge_power

        # Build the FleetCycleState — the single source of truth for
        # fleet inputs this cycle. Both the primary view (built below)
        # and the multi-charger loop downstream derive their views
        # from this SAME state object. Eliminates the post-#358
        # plumbing-asymmetry class: any new fleet input lands as a
        # field on FleetCycleState and is automatically visible to
        # every charger's decide() in this cycle.
        fleet_state = self._build_fleet_cycle_state(power, energy)
        self._cycle_fleet_state = fleet_state
        forecast_remaining = fleet_state.forecast_remaining_kwh

        battery_capacity = self.battery_capacity_kwh

        # Compute the night plan BEFORE the primary view so its
        # deadline_amps + should_wait_for_cheap (tariff_wait) flow
        # into the primary charger's ``decide()`` call. Pre-this
        # commit the night plan was computed at the END of
        # ``_build_charging_context``, after ``decide()`` had
        # already run — so the primary charger never saw the
        # tariff wait flag and ``SolarPlusCheapMode`` could only
        # take the non-wait branch. Multi-charger loop downstream
        # already had access via the cached ChargingContext; this
        # brings the primary to parity.
        night_target = operational_night_target(self._ev_devices, remaining_floor)
        if (
            self._ev_devices
            and self.time_manager.is_night_mode()
            and self._smart_night_charging_enabled()
        ):
            night_target = self._calculate_forecast_night_target(
                remaining_floor, energy, _primary_cfg,
            )
        night_plan = None
        deadline_amps = 0
        deadline_active = False
        tariff_wait = False
        deadline_reachable = True
        if self.time_manager.is_night_mode() and night_target > 0.1:
            night_plan = self._compute_night_plan(_primary_cfg, night_target, energy)
            # (#638 G4) the joint-plan overlay for the PRIMARY charger —
            # the same overlay the multi-charger loop applies to every
            # charger it visits. The primary's plan is computed HERE, at a
            # second site, so skipping it would actuate every charger
            # except the one a single-charger install actually has (the
            # per-charger-vs-primary parity class, #683/#684).
            try:
                from .energy_plan_actuation import ev_overlay
                _pcid = _primary_cfg.get("id") or "ev_charger"
                _gate = self._energy_plan_gate(f"ev:{_pcid}")
                # Same measured W/A the demand was packed with (see the
                # multi-charger site) — plan and floor share one power model.
                _wpa = self._ev_watts_per_amp(_pcid, _primary_cfg, power)
                _wait, _floor = ev_overlay(
                    _gate,
                    remaining_kwh=night_target,
                    reachable=night_plan.reachable,
                    deadline_active=night_plan.deadline_active,
                    watts_per_amp=_wpa,
                    min_amps=int(_primary_cfg.get("ev_min_current") or 6),
                    max_amps=int(_primary_cfg.get("ev_max_current")
                                   or DEFAULT_MAX_CHARGING_CURRENT),
                )
                if _wait:
                    night_plan.should_wait_for_cheap = True
                    night_plan.next_cheap_start = _gate.next_block_start
                    night_plan.reason = (
                        "joint energy plan: outside the planned window "
                        f"— waiting ({_gate.remaining_kwh:.1f} kWh "
                        f"still deliverable)")
                elif _floor > 0:
                    night_plan.should_wait_for_cheap = False
                    night_plan.deadline_amps = max(
                        night_plan.deadline_amps, _floor)
                    night_plan.reason = (
                        f"joint energy plan: in planned window — "
                        f"floor {_floor}A")
            except Exception:  # noqa: BLE001 — overlay must never break the
                # night path; a crash equals "no plan", the safe direction.
                _LOGGER.debug("#638 G4 primary EV overlay skipped",
                              exc_info=True)
            deadline_amps = night_plan.deadline_amps
            deadline_active = night_plan.deadline_active
            tariff_wait = night_plan.should_wait_for_cheap
            deadline_reachable = night_plan.reachable
        self._cycle_night_plan = night_plan

        # Step 7: use the new architecture's decide() for the primary
        # charger's strategy + reason. The legacy
        # _determine_charging_strategy / _self_consumption_strategy /
        # _zone_based_strategy / _canonical_strategy_from_legacy are
        # gone — every per-charger decision flows through decide(view).
        from .build_view import build_charger_view
        from .charger_types import ChargerIntent as _CI
        from .decide import decide as _decide
        from .flow_calculator import EVBudgetStrategy

        # Primary view — built from the FleetCycleState above.
        # All fleet inputs (power readings, is_night, tariff_level,
        # forecast_remaining_kwh) come from fleet_state. Only per-
        # charger overrides are direct kwargs.
        _primary_view = build_charger_view(
            fleet_state,
            charger_id=(_primary_cfg.get("id") or "ev_charger"),
            # #576 — the primary charger's slot in the one priority list.
            ev_priority=self._ev_priority_for(_primary_cfg.get("id") or "ev_charger"),
            charger_cfg=_primary_cfg,
            mode=self._effective_charge_mode_for(_primary_cfg),
            daily_ev_kwh=self._charger_daily_kwh(
                _primary_cfg.get("id") or "ev_charger", energy,
            ),
            target_kwh=remaining_floor,
            # Night plan flags (#246 deadline + #247 tariff wait).
            # Computed above so the primary view's decide() sees the
            # same wait-for-cheap and deadline-floor info the
            # multi-charger loop downstream gets.
            plan=verdict_from_night_plan(night_plan),
            deadline_amps=deadline_amps,
            top_up_amps=int(getattr(night_plan, "top_up_amps", 0) or 0) if night_plan else 0,
            night_deliverable_kwh=self._night_deliverable_kwh(_primary_cfg),
            # #548 — max-SOC ceiling; stop surplus charging at the car's max.
            soc_ceiling_reached=soc_limit_active,
            # #678 — same ceiling the actuator clamps to. ``effective_max_current``
            # already folds in the control number's own max (#536), so the
            # strategy string can't advertise amps the hardware refuses.
            hardware_max_a=self._primary_hardware_max_a(_primary_cfg),
        )
        _primary_decision = _decide(_primary_view)
        strategy = _primary_decision.intent.value
        reason = _primary_decision.reason

        # (#657) "Is there meaningful sun?" — read off the SAME view decide()
        # just consumed, so the flag the user sees can't disagree with the
        # gate that produced the decision (``decide.py`` calls the sun gone
        # below ``min_solar_w``). Deliberately not re-derived from config:
        # the min_solar_w fallback chain lives in build_view and duplicating
        # it is how the 200-vs-1000 divergence happened.
        #
        # Scope note: this is the SOLAR gate only, not "everything is fine".
        # A car can be blocked with solar_sufficient=True — by tariff (see the
        # already-published ``ev_tariff_waiting`` / ``ev_next_cheap_window``
        # attributes) or by the battery buffer (``battery_too_low`` /
        # ``battery_needs_priority``). The three flags plus the tariff pair are
        # the answer set; none of them alone is.
        solar_sufficient = (
            float(_primary_view.fleet.solar_w)
            >= float(_primary_view.fleet.min_solar_w)
        )

        # Map ChargerIntent → EVBudgetStrategy for the canonical budget
        # consumer (sem_available_power, sem_calculated_current).
        if _primary_decision.intent is _CI.DISABLE:
            canonical_strategy = EVBudgetStrategy.IDLE
        elif _primary_decision.intent is _CI.IDLE:
            canonical_strategy = EVBudgetStrategy.IDLE
        elif _primary_decision.intent is _CI.CHARGE_MAX:
            canonical_strategy = EVBudgetStrategy.NOW
        elif _primary_view.fleet.is_night and _primary_view.mode != "solar_only":
            # min_plus_solar / solar_plus_cheap night top-up uses MIN_PV
            canonical_strategy = EVBudgetStrategy.MIN_PV
        elif _primary_view.mode == "solar_only":
            canonical_strategy = EVBudgetStrategy.SOLAR_ONLY
        else:
            # min_plus_solar / solar_plus_cheap day → zone-aware
            # battery-assist OR self-consumption.
            from .decide import soc_zone as _zone
            _z = _zone(
                _primary_view.fleet.battery_soc,
                _primary_view.fleet.auto_start_soc,
                _primary_view.fleet.buffer_soc,
                _primary_view.fleet.priority_soc,
            )
            canonical_strategy = (
                EVBudgetStrategy.BATTERY_ASSIST if _z >= 3
                else EVBudgetStrategy.SOLAR_ONLY
            )
        # MIN_PV needs a min_power_floor; NOW needs an override. The
        # state machine doesn't read either, so leave them at defaults
        # here (the actuator's own dispatch fills those in when relevant —
        # see ev_control._cycle_ev_budget consumer in Phase B/C).
        min_power_floor_w = 0.0
        override_max_w = None
        # Use the configured phases × voltage, not a hardcoded 3×230 — a
        # 1-phase charger's amps→watts floor was 3× too high (it would refuse
        # to MIN_PV / over-cap NOW). Defaults (3, 230) keep 3-phase unchanged.
        _phase_v = (
            int(self.config.get("ev_phases", 3))
            * int(self.config.get("ev_voltage", 230))
        )
        if canonical_strategy == EVBudgetStrategy.MIN_PV:
            # min current × phases × voltage — KEBA / Wallbox EU minimum.
            min_power_floor_w = self.config.get("ev_min_current", 6) * _phase_v
        elif canonical_strategy == EVBudgetStrategy.BATTERY_ASSIST:
            # #501: BATTERY_ASSIST consumes the floor as the assist
            # top-up bound (assist fills surplus→min gap only), NOT
            # as a net_w floor — see the strategy branch.
            min_power_floor_w = self.config.get("ev_min_current", 6) * _phase_v
        elif canonical_strategy == EVBudgetStrategy.NOW:
            override_max_w = self.config.get(
                "ev_max_current", DEFAULT_MAX_CHARGING_CURRENT) * _phase_v

        ev_budget_obj = self._flow_calculator.calculate_canonical_ev_budget(
            power,
            strategy=canonical_strategy,
            battery_soc=power.battery_soc,
            battery_capacity_kwh=battery_capacity,
            forecast_remaining_kwh=forecast_remaining,
            battery_auto_start_soc=self.config.get("battery_auto_start_soc", 90),
            battery_buffer_soc=self.config.get("battery_buffer_soc", 70),
            battery_assist_max_power_w=self.config.get(
                "battery_assist_max_power",
                self.config.get("super_charger_power", 4500),
            ),
            battery_assist_min_surplus_w=self.config.get(
                "battery_assist_min_surplus", 1200
            ),
            min_power_floor_w=min_power_floor_w,
            override_max_w=override_max_w,
        )
        # Cache for the actuator — ev_control reads self._cycle_ev_budget
        # instead of recomputing.
        self._cycle_ev_budget = ev_budget_obj
        ev_budget = ev_budget_obj.net_w
        ev_current = ev_budget_obj.current_a

        # (The #545 observe-only assist-headroom diagnostic was retired here
        # once #545 shipped + closed — the chicken-and-egg is fixed.)

        # (#762) transition-gated — 1792 identical idle lines per day.
        log_on_change(
            _LOGGER, "charging_strategy", logging.DEBUG,
            "Charging strategy: %s — %s",
            strategy, reason,
        )

        # Night plan was computed earlier (before primary view's decide())
        # — variables ``night_target``, ``deadline_amps``,
        # ``deadline_active``, ``tariff_wait``, ``deadline_reachable``
        # are already populated and consumed below.

        return ChargingContext(
            ev_connected=operational_ev_connected(self._ev_devices, power.ev_connected),
            ev_charging=bool(self._ev_devices) and power.ev_charging,
            battery_soc=power.battery_soc,
            battery_too_low=battery_too_low,
            battery_needs_priority=battery_needs_priority,
            solar_sufficient=solar_sufficient,
            calculated_current=ev_current,
            excess_solar=excess_solar,
            available_power=ev_budget,
            daily_target_reached=daily_target_reached,
            daily_ev_energy=energy.daily_ev,
            daily_ev_energy_offset=0,  # TODO: Support offset utility meter
            remaining_ev_energy=remaining,
            charging_strategy=strategy,
            charging_strategy_reason=reason,
            # EVBudgetStrategy is a string-constant class (not an Enum),
            # so canonical_strategy is already the value string.
            canonical_strategy=canonical_strategy,
            night_target_kwh=night_target,
            soc_limit_active=soc_limit_active,
            night_deadline_amps=deadline_amps,
            night_deadline_active=deadline_active,
            night_tariff_wait=tariff_wait,
            night_deadline_reachable=deadline_reachable,
        )

    def _update_battery_session_tracking(
        self, power: PowerReadings, power_flows: PowerFlows
    ) -> None:
        """Track battery charge/discharge sessions with source attribution.

        Hysteresis on three axes so the session reflects the
        user-visible continuous flow, not the inverter's micro-
        rebalancing during sunset / cloud transits / load steps:

        - **Power dead-band** = 200 W. Below this the cycle counts as
          idle. Wider than the inverter's idle-state drift; still well
          below any meaningful charge/discharge.
        - **Idle cycles to end** = 18 (~3 min at the default 10 s
          interval). A 30 s gap that comes back into discharge keeps
          the session intact; 3 min of true idle ends it.
        - **Direction-change cycles to flip** = 3. A single cycle of
          the opposite direction (briefly +50 W of charge during a
          discharge transient) does NOT end the session. Three in a
          row does.

        Pre-hysteresis (50 W / 3 idle / 1-cycle flip) caused
        screenshots where the user's 1-hour continuous discharge was
        reported as a 2-minute session because the inverter briefly
        rebalanced through 0 W during the sunset transition (#405).
        """
        POWER_THRESHOLD = 200.0
        IDLE_CYCLES_TO_END = 18
        OPPOSITE_CYCLES_TO_FLIP = 3

        charging = power.battery_charge_power > POWER_THRESHOLD
        discharging = power.battery_discharge_power > POWER_THRESHOLD
        session = self._battery_session

        # Determine current activity
        if charging:
            current_type = "charge"
        elif discharging:
            current_type = "discharge"
        else:
            current_type = "idle"

        # Direction-change hysteresis — require N consecutive cycles
        # in the opposite direction before treating it as a real flip.
        if (
            session.active
            and current_type != "idle"
            and current_type != session.session_type
        ):
            self._battery_session_opposite_count += 1
            if self._battery_session_opposite_count >= OPPOSITE_CYCLES_TO_FLIP:
                session.active = False
                self._battery_session_opposite_count = 0
                _LOGGER.debug(
                    "Battery session ended (direction flip after %d cycles): %s, %.2f kWh, %d min",
                    OPPOSITE_CYCLES_TO_FLIP,
                    session.session_type,
                    session.energy_kwh,
                    session.duration_minutes,
                )
            else:
                # Transient opposite-direction blip — keep session
                # alive but skip accumulation this cycle.
                return
        elif current_type == session.session_type:
            # Matched the active session direction → reset the counter.
            self._battery_session_opposite_count = 0

        # Handle idle — count consecutive idle cycles
        if current_type == "idle":
            if session.active:
                self._battery_session_idle_count += 1
                if self._battery_session_idle_count >= IDLE_CYCLES_TO_END:
                    session.active = False
                    self._battery_session_opposite_count = 0
                    _LOGGER.debug(
                        "Battery session ended (idle): %s, %.2f kWh, %d min",
                        session.session_type, session.energy_kwh, session.duration_minutes,
                    )
            return

        # Reset idle counter when power is active
        self._battery_session_idle_count = 0

        # Start new session
        if not session.active:
            self._battery_session = BatterySessionData(
                active=True,
                session_type=current_type,
                start_time=dt_util.now().isoformat(),
            )
            session = self._battery_session
            _LOGGER.debug("Battery session started: %s", current_type)

        # Accumulate energy. Use the actual update interval (the
        # DataUpdateCoordinator base may throttle this under HA load —
        # config["update_interval"] is the REQUESTED interval, not the
        # observed one). #351 L1.
        interval_s = self.update_interval.total_seconds()
        hours = interval_s / 3600.0

        if session.session_type == "charge":
            total_increment = (power.battery_charge_power * hours) / 1000.0
            solar_increment = (power_flows.solar_to_battery * hours) / 1000.0
            grid_increment = (power_flows.grid_to_battery * hours) / 1000.0
            session.energy_kwh += total_increment
            session.solar_energy_kwh += solar_increment
            session.grid_energy_kwh += grid_increment
            if session.energy_kwh > 0:
                session.solar_share_pct = (session.solar_energy_kwh / session.energy_kwh) * 100
            # Use live dynamic tariff rate instead of static config value (#223)
            import_rate = self._energy_calculator._import_rate
            session.cost += grid_increment * import_rate
        else:  # discharge
            discharge_increment = (power.battery_discharge_power * hours) / 1000.0
            session.energy_kwh += discharge_increment
            # Use live dynamic tariff rate instead of static config value (#223)
            import_rate = self._energy_calculator._import_rate
            session.savings += discharge_increment * import_rate

        # Update duration and average power
        if session.start_time:
            try:
                start = dt_util.parse_datetime(session.start_time)
                if start:
                    elapsed = (dt_util.now() - start).total_seconds() / 60.0
                    session.duration_minutes = max(0, elapsed)
                    if session.duration_minutes > 0:
                        session.avg_power_w = (session.energy_kwh * 60000) / session.duration_minutes
            except (ValueError, TypeError):
                pass

    def _restore_ev_session_state(self) -> None:
        """Restore EV session state from storage on startup.

        Persists more than the session_active flag now (#282 follow-up): the
        whole SessionData record (energy, source split, start time, cost) gets
        round-tripped so an HA restart mid-session no longer wipes the meter
        and creates a phantom "new session" with 0 kWh. The previous code only
        persisted the active flag, so on restart _session_data was rebuilt
        empty and the next cycle started a brand-new SessionData — visible to
        the user as a session counter that resets to 0 mid-charge.
        """
        if not self._storage:
            return
        state = self._storage.get_ev_session_state()
        if not state:
            return

        from .types import SessionData

        def _restore_session_data(saved: dict) -> SessionData:
            return SessionData(
                active=saved.get("session_active", False),
                start_time=saved.get("start_time"),
                duration_minutes=saved.get("duration_minutes", 0.0),
                energy_kwh=saved.get("energy_kwh", 0.0),
                solar_energy_kwh=saved.get("solar_energy_kwh", 0.0),
                grid_energy_kwh=saved.get("grid_energy_kwh", 0.0),
                battery_energy_kwh=saved.get("battery_energy_kwh", 0.0),
                solar_share_pct=saved.get("solar_share_pct", 0.0),
                cost_chf=saved.get("cost_chf", 0.0),
                avg_power_w=saved.get("avg_power_w", 0.0),
            )

        # Multi-charger (#112): restore all chargers
        if self._ev_devices:
            per_charger = state.get("chargers", {})
            for cid, ev_dev in self._ev_devices.items():
                cstate = per_charger.get(cid, state if cid == next(iter(self._ev_devices)) else {})
                ev_dev._session_active = cstate.get("session_active", False)
                ev_dev._current_setpoint = cstate.get("current_setpoint", 0.0)
                # Restore the full SessionData (#282) — energy_kwh, source
                # split, start_time, cost. Without this the next cycle's
                # _update_session_tracking sees `not _session_data.active`
                # and starts a brand-new SessionData mid-charge.
                self._session_data_per_charger[cid] = _restore_session_data(cstate)
                _LOGGER.info(
                    "Restored EV session for %s: active=%s, setpoint=%.0fA, %.2fkWh",
                    ev_dev.name, ev_dev._session_active, ev_dev._current_setpoint,
                    self._session_data_per_charger[cid].energy_kwh,
                )
            # Seed the primary _session_data so legacy callers reading it
            # directly see the restored values too.
            primary_cid = next(iter(self._ev_devices))
            self._session_data = self._session_data_per_charger[primary_cid]
        elif self._ev_device:
            ev = self._ev_device
            ev._session_active = state.get("session_active", False)
            ev._current_setpoint = state.get("current_setpoint", 0.0)
            self._session_data = _restore_session_data(state)
            _LOGGER.info(
                "Restored EV session: active=%s, setpoint=%.0fA, %.2fkWh",
                ev._session_active, ev._current_setpoint, self._session_data.energy_kwh,
            )
        # #589 — restore stability timers so a deep-deficit countdown that was
        # in progress before the restart resumes from the correct elapsed time
        # rather than being reset to 0 (which would re-arm a full grace window
        # and allow the battery to drain for the full 45 s again).
        # The stability timers are at the top level of the blob (fleet-wide).
        # Be fully defensive: any error → skip, never raise.
        try:
            stability_blob = state.get("stability_timers")
            if stability_blob is not None:
                self._charge_stability.restore_timers(stability_blob, time.monotonic())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("restore_timers failed, skipping timer rebase", exc_info=True)
        self._ev_last_change_time = None

    def _save_ev_session_state(self) -> None:
        """Persist EV session state to storage."""
        if not self._storage:
            return

        # #589 — snapshot the charge-stability timers so that on restart
        # a deep-deficit countdown resumes from where it was rather than
        # re-arming a full fresh grace window (the battery-drain bug).
        # Stability timers are fleet-wide (one ChargeStability instance),
        # so they are stored at the top level of the blob, not per-charger.
        stability_snapshot = self._charge_stability.snapshot_timers(time.monotonic())

        # Multi-charger (#112): save all chargers
        if self._ev_devices:
            per_charger = {}
            for cid, ev_dev in self._ev_devices.items():
                sd = self._session_data_per_charger.get(cid)
                per_charger[cid] = self._serialize_session_state(
                    ev_dev._session_active, ev_dev._current_setpoint, sd,
                )
            # Also save primary charger at top level for backward compat with
            # older releases that read the top-level keys without traversing
            # the "chargers" dict.
            primary_cid = next(iter(self._ev_devices))
            primary_dev = self._ev_devices[primary_cid]
            primary_sd = self._session_data_per_charger.get(primary_cid)
            self._storage.set_ev_session_state({
                **self._serialize_session_state(
                    primary_dev._session_active, primary_dev._current_setpoint, primary_sd,
                ),
                "chargers": per_charger,
                "stability_timers": stability_snapshot,
            })
        elif self._ev_device:
            ev = self._ev_device
            self._storage.set_ev_session_state({
                **self._serialize_session_state(
                    ev._session_active, ev._current_setpoint, self._session_data,
                ),
                "stability_timers": stability_snapshot,
            })

    def _serialize_session_state(
        self, session_active: bool, current_setpoint: float, sd,
    ) -> dict:
        """Build a storage-safe dict for one charger's session state (#282).

        Persists more than session_active/current_setpoint now: the full
        SessionData record so an HA restart mid-charge doesn't reset the
        session meter to 0. ``sd`` may be None for chargers that have not
        had a session yet — emit only the always-on fields in that case.
        """
        payload = {
            "session_active": session_active,
            "current_setpoint": current_setpoint,
        }
        if sd is not None:
            payload.update({
                "start_time": sd.start_time,
                "duration_minutes": sd.duration_minutes,
                "energy_kwh": sd.energy_kwh,
                "solar_energy_kwh": sd.solar_energy_kwh,
                "grid_energy_kwh": sd.grid_energy_kwh,
                "battery_energy_kwh": sd.battery_energy_kwh,
                "solar_share_pct": sd.solar_share_pct,
                "cost_chf": sd.cost_chf,
                "avg_power_w": sd.avg_power_w,
            })
        return payload

    def _update_per_charger_detector_energy(
        self, cid: str, charger_power: float, interval_hours: float,
    ) -> None:
        """Feed the per-charger taper detector its own energy increment (#318).

        Mirrors what ``self._ev_taper_detector.update_energy(...)`` does
        for the primary detector — but per-charger, so each charger's
        ``_energy_since_full`` tracks its own session. Without this,
        every per-charger detector stays at 0 → ``get_virtual_soc()``
        returns the same default (100 %) for every charger → dashboard
        shows identical SOC across the fleet.

        Uses each charger's own ``ev_total_energy_sensor`` HW counter
        when configured (drift-free); falls back to incremental-only
        tracking when not (same behaviour the primary detector had for
        installs without a hardware counter).

        No-op when ``charger_power <= 0`` (idle) — matches the legacy
        per-charger ``update()`` gating at the call site.
        """
        if charger_power <= 0:
            return
        detector = self._ev_taper_detectors.get(cid)
        if detector is None:
            return
        per_charger_cfg = next(
            (c for c in (self.config.get("ev_chargers") or [])
             if c.get("id") == cid), {}
        ) or {}
        per_increment = charger_power * interval_hours / 1000
        per_hw_total = None
        per_hw_entity = per_charger_cfg.get("ev_total_energy_sensor")
        # (#639) legacy configs carry only the TOP-LEVEL counter: it belongs
        # to the PRIMARY charger by the auto-fill convention (__init__), so
        # fall back for the primary only — never for siblings (that would be
        # the cross-contamination this fix removes).
        if not per_hw_entity:
            _primary = (self.config.get("ev_chargers") or [{}])[0].get("id")
            if cid == _primary:
                per_hw_entity = self.config.get("ev_total_energy_sensor")
        if per_hw_entity:
            hw_state = self.hass.states.get(per_hw_entity)
            if hw_state and hw_state.state not in ("unknown", "unavailable"):
                try:
                    per_hw_total = float(hw_state.state)
                except (ValueError, TypeError):
                    pass
        detector.update_energy(per_increment, per_hw_total)

    def _charger_power_w(self, cid: str, power, ev_dev=None) -> float:
        """(#643) THIS charger's draw for coordinator-side consumers.

        Canonical read: the cycle's ``power.ev_power_per_charger[cid]`` —
        already median-of-3 smoothed and unit-normalized by the sensor
        reader (UDP-polled chargers blip to 0 for a cycle mid-charge; the
        raw entity is exactly the signal the rest of the system rejects
        as noise). Falls back to a raw entity read ONLY when the
        per-charger dict has no entry for this cid (legacy top-level-sensor
        configs never populate it — see sensor_reader misconfig note).

        Replaces three hand-rolled ``hass.states.get(power_entity_id)``
        blocks that each had their own kW rule and no blip filter (the
        class-3 sanctioned-accessor bypass, coordinator flavour of
        ``_this_charger_power``).
        """
        per = (getattr(power, "ev_power_per_charger", None) or {}) if power is not None else {}
        if cid in per:
            return float(per[cid] or 0.0)
        dev = ev_dev if ev_dev is not None else self._ev_devices.get(cid)
        eid = getattr(dev, "power_entity_id", None)
        if not eid:
            return 0.0
        pstate = self.hass.states.get(eid)
        if not pstate or pstate.state in ("unknown", "unavailable"):
            return 0.0
        # #641 — one shared rule. The non-numeric DEBUG line is kept: it is the
        # #259 diagnostic, and units.py returns the default silently.
        w = power_state_to_watts(pstate)
        if w is None:
            _LOGGER.debug(
                "Charger %s power not numeric: %r (#259)",
                cid, getattr(pstate, "state", None),
            )
            return 0.0
        return w

    def _update_ev_intelligence(
        self, power: PowerReadings, energy,
    ) -> "EVIntelligenceData":
        """Update EV taper detection, virtual SOC, and charge skip logic (#106).

        Multi-charger (#112): runs taper detection per charger using per-charger
        power readings. The primary charger's results drive virtual SOC and
        charge skip decisions (only one EV vehicle assumed for SOC tracking).
        """
        from .types import EVIntelligenceData, EVTaperData

        now = dt_util.now()
        interval_hours = self.update_interval.total_seconds() / 3600

        # #589 (EV W2/W3): the PRIMARY charger's own per-charger taper result,
        # captured in the loop below so the fleet-sum re-update is not needed.
        primary_id = next(iter(self._ev_devices)) if self._ev_devices else None
        primary_taper_data = None
        # Multi-charger (#112): run per-charger taper detection
        if self._ev_devices and len(self._ev_devices) >= 1:
            for cid, ev_dev in self._ev_devices.items():
                if cid not in self._ev_taper_detectors:
                    self._ev_taper_detectors[cid] = EVTaperDetector(self.config)
                    # Restore state if available
                    if self._storage:
                        stored = self._storage.get_ev_intelligence_state()
                        per_charger_state = (stored or {}).get("chargers", {}).get(cid)
                        if per_charger_state:
                            self._ev_taper_detectors[cid].restore_state(per_charger_state)

                # (#643) canonical smoothed per-charger read — the taper
                # detector was ingesting the raw 0-blip the rest of the
                # system median-filters away.
                charger_power = self._charger_power_w(cid, power, ev_dev)

                charger_setpoint = getattr(ev_dev, "_current_setpoint", 0.0)
                # Use per-charger session state; fall back to power threshold
                # as proxy — do NOT OR with global ev_connected which belongs
                # to the primary charger only.
                charger_connected = getattr(ev_dev, "_session_active", False)
                if not charger_connected and ev_dev.power_entity_id:
                    charger_connected = charger_power > 50

                # Accumulate per-charger daily energy (#193).
                #
                # Boundary: each charger's "EV day" ends at its own ``Charge by``
                # deadline (#280) — not sunrise. The legacy sunrise boundary
                # wiped the counter between hitting Min (~03:00) and the night
                # window's end (~07:00) on short summer nights, causing SEM to
                # see ``remaining = daily_target`` again and re-fire night
                # charging until 07:00 — billing the user twice for the same
                # daily target. Resetting at the deadline instead means the
                # counter only rolls over once today's commitment is closed.
                # Solar charging between sunrise and the deadline accumulates
                # into yesterday's bucket — harmless, since Min was already hit.
                # Per-charger daily rollover — MUST run every cycle, even when
                # the charger draws no power. #517: nesting the reset inside
                # ``if charger_power > 0`` meant an unplugged/idle charger never
                # rolled over, so its "today" counter carried yesterday's value
                # forward indefinitely and grew across idle days (RienduPre saw
                # 81.5 kWh "Vandaag" on a charger that wasn't even connected,
                # while the correctly-resetting fleet total showed 0). Only the
                # INCREMENT is gated on power; the date check / reset is not.
                cfg_for_cid = (
                    next((c for c in (self.config.get("ev_chargers") or [])
                          if c.get("id") == cid), {})
                ) or {}
                target_time = self._charger_target_time(cfg_for_cid)
                ev_day = self.time_manager.get_current_meter_day_offset_based(
                    target_time
                ).isoformat()
                if self._daily_ev_per_charger_date.get(cid) != ev_day:
                    # Per-charger reset (Car A at 07:00, Car B at 08:00 don't
                    # disturb each other) — only this cid's bucket rolls over.
                    self._daily_ev_per_charger[cid] = 0.0
                    self._daily_ev_per_charger_date[cid] = ev_day
                if charger_power > 0:
                    increment = charger_power * interval_hours / 1000  # W → kWh
                    self._daily_ev_per_charger[cid] = (
                        self._daily_ev_per_charger.get(cid, 0.0) + increment
                    )

                if charger_power > 0 or charger_connected:
                    _td = self._ev_taper_detectors[cid].update(
                        charger_power, charger_setpoint, charger_connected, now,
                    )
                    # #589 (EV W2/W3): keep the primary's OWN taper result so we
                    # don't re-feed the fleet sum into the primary detector below
                    # (that false-anchored the primary's SOC on another charger's
                    # power). Its own per-charger power is the correct input.
                    if cid == primary_id:
                        primary_taper_data = _td

                # Per-charger energy update (#318). Without this every
                # per-charger detector keeps ``_energy_since_full=0`` so
                # the SOC estimator falls through to the same default for
                # every charger — symptom: "Charger 1 and Charger 2 show
                # identical SOC, both rise when only one is charging"
                # (RienduPre, 2026-05-31 multi-charger Wallbox + Growatt).
                # The primary detector's update_energy below at line ~3326
                # was only feeding the global ``self._ev_taper_detector``,
                # not the per-charger detectors in ``self._ev_taper_detectors``.
                self._update_per_charger_detector_energy(
                    cid, charger_power, interval_hours,
                )

        # #589 Surface-B retirement: the primary charger's detector is now
        # resolved by the _ev_taper_detector property (computed from
        # _ev_taper_detectors[primary_id]) — no per-cycle swap. The former
        # `_ev_taper_detector = _ev_taper_detectors[primary_id]`
        # reassignment was one of the two parallel per-charger swap surfaces
        # (#589); deleting it removes a state-leak surface.

        # Get current EV setpoint (0 if no EV device)
        ev_setpoint = 0.0
        if self._ev_device:
            ev_setpoint = getattr(self._ev_device, "_current_setpoint", 0.0)

        # Run taper detection. #589 (EV W2/W3): for multi-charger the primary
        # charger's OWN detector was already updated per-charger above (#318),
        # and its result is in ``primary_taper_data``. The previous code then
        # re-updated that same primary detector with the FLEET sum
        # (``power.ev_power``) every cycle — so another charger's draw
        # false-anchored the primary's SOC/peak (the exact fleet-read class the
        # AST lint can't catch because the read was annotated). Now the fleet
        # update ONLY runs on the legacy single-detector path (no per-charger
        # devices configured at all).
        if self._ev_devices:
            taper_data = (
                primary_taper_data if primary_taper_data is not None
                else EVTaperData()
            )
        # FLEET-READ: legacy single-detector path — reached ONLY when no
        # per-charger devices exist, so the fleet total IS this one charger.
        elif power.ev_power > 0 or power.ev_connected:  # FLEET-READ: legacy single-detector gate
            taper_data = self._ev_taper_detector.update(
                power.ev_power, ev_setpoint, power.ev_connected, now,  # FLEET-READ: legacy single-detector input
            )
        else:
            taper_data = EVTaperData()

        # Track energy since last full charge (hardware counter preferred).
        # (#639, audit class 3) LEGACY-ONLY like the #589 W2/W3 update() gate:
        # on per-charger installs the primary detector is already fed its OWN
        # increment + counter by _update_per_charger_detector_energy — running
        # this fleet-sum block too double-fed it (energy_since_full at ~2x →
        # virtual SOC reads LOW → night over-charge + delayed nearly-full).
        if hasattr(energy, "daily_ev") and not self._ev_devices:
            # FLEET-READ: ``daily_ev`` is the fleet daily total; matches
            # the fleet-level ``sensor.sem_daily_ev_energy``. Per-charger
            # daily energy is on ``charger_<id>_daily_energy`` populated
            # separately by ``_update_per_charger_detector_energy``.
            ev_increment = power.ev_power * interval_hours / 1000
            # Read hardware total energy counter for drift-free tracking
            hw_total = None
            ev_total_entity = self.config.get("ev_total_energy_sensor") or getattr(
                self._sensor_reader.config, 'ev_daily_energy_sensor', None
            )
            if ev_total_entity:
                hw_state = self.hass.states.get(ev_total_entity)
                if hw_state and hw_state.state not in ("unknown", "unavailable"):
                    try:
                        hw_total = float(hw_state.state)
                    except (ValueError, TypeError):
                        pass
            self._ev_taper_detector.update_energy(ev_increment, hw_total)

        # Reset on disconnect
        if self._last_ev_connected and not power.ev_connected:
            if self._session_data.energy_kwh > 0:
                self._ev_taper_detector.on_session_end(
                    self._session_data.energy_kwh,
                    end_soc=self._cycle_vehicle_soc,
                )
                if self._storage:
                    self._storage.add_session_to_history({
                        "timestamp": self._session_data.start_time,
                        "energy_kwh": round(self._session_data.energy_kwh, 2),
                        "solar_share_pct": round(self._session_data.solar_share_pct, 1),
                        "duration_min": round(self._session_data.duration_minutes, 1),
                        "taper_detected": self._ev_taper_detector.full_detected,
                    })
            self._ev_taper_detector.reset_session()

        # Stall detection → full charge: if car is connected AND SEM has
        # been commanding a charge AND the EV still draws 0 W for ~3 min,
        # the BMS is refusing further current and the car is genuinely
        # full. The ``commanded_amps_fleet >= 6`` gate is the load-bearing
        # bit: without it, ``solar_only`` with insufficient surplus
        # (e.g. cloudy day, 869 W < 3-phase 4 140 W floor) trips the
        # stall and falsely anchors SOC at 100 %, after which
        # ``charge_needed`` stays False forever and the EV never starts.
        # Legacy single-detector stall path; runs only when multi-charger
        # isn't configured (per-charger stall lives on
        # ``_ev_stalled_since_per_charger``). Demo of the v1.6.16
        # ``.as_fleet_total(reason)`` form — the reason rides in the
        # bytecode rather than a comment line above the read.
        if (power.ev_connected and not power.ev_charging
                and power.ev_power.as_fleet_total("legacy single-detector stall path") < 50
                and self._last_commanded_amps_fleet >= 6
                and not self._ev_taper_detector._full_detected):
            stall_count = getattr(self, '_full_stall_count', 0) + 1
            self._full_stall_count = stall_count
            if stall_count >= 18:  # ~3 minutes of 0W while connected
                self._ev_taper_detector._full_detected = True
                self._ev_taper_detector._last_full_timestamp = dt_util.now().isoformat()
                self._ev_taper_detector._energy_since_full = 0.0
                self._ev_taper_detector._estimated_soc = 100.0
                self._ev_taper_detector._soc_anchored = True
                if self._ev_taper_detector._hw_total_last is not None:
                    self._ev_taper_detector._hw_total_at_full = self._ev_taper_detector._hw_total_last
                self._full_stall_count = 0
                _LOGGER.info(
                    "EV full charge detected from stall: car connected, 0W for 3+ min → SOC 100%%"
                )
        else:
            self._full_stall_count = 0

        # Virtual SOC (prefer real vehicle SOC if available)
        estimated_soc = self._ev_taper_detector.get_virtual_soc(self._cycle_vehicle_soc)

        # Self-healing: if SOC is at 0% but car just charged, something is wrong
        # Reset to a reasonable estimate based on recent session energy
        if estimated_soc <= 0 and self._session_data.energy_kwh > 1.0 and power.ev_connected:
            capacity = self.config.get("ev_battery_capacity_kwh", 40)
            session_soc = min(95.0, self._session_data.energy_kwh / capacity * 100 * 0.92) if capacity > 0 else 0.0
            self._ev_taper_detector._energy_since_full = (100 - session_soc) / 100 * capacity
            self._ev_taper_detector._estimated_soc = session_soc
            # #708 — anchor what we just wrote. ``update_energy`` is inert
            # until the detector is anchored, so a healed-but-unanchored
            # estimate would FREEZE for the rest of the charge: worse than
            # the moving-but-wrong value it replaced. The stall→full anchor
            # below sets this for the same reason.
            self._ev_taper_detector._soc_anchored = True
            estimated_soc = session_soc
            _LOGGER.warning(
                "SOC self-healed: was 0%% after %.1f kWh session → %.0f%%",
                self._session_data.energy_kwh, session_soc,
            )

        # EV consumption prediction (display-only — feeds the
        # ``predicted_daily_ev_kwh`` diagnostic sensor; no longer
        # drives skip decisions per #440).
        predicted_daily = self._predictor.predict_ev_consumption_tomorrow(now)

        # No real SOC and no calibration yet → the virtual 100% default is
        # misleading. Report None so the sensor shows "unknown" until a real
        # reference (sensor / taper / stall) — do NOT prefill a guessed value.
        # Matches the per-charger path in _build_per_charger_intelligence. (#245)
        _d = self._ev_taper_detector
        if self._cycle_vehicle_soc is None and not _d._soc_anchored and _d._energy_since_full == 0.0:
            estimated_soc_display: Optional[float] = None
        else:
            estimated_soc_display = round(estimated_soc, 1)

        return EVIntelligenceData(
            taper=taper_data,
            estimated_soc_pct=estimated_soc_display,
            last_full_charge=self._ev_taper_detector.last_full_timestamp,
            energy_since_full_kwh=round(self._ev_taper_detector.energy_since_full, 2),
            predicted_daily_ev_kwh=predicted_daily,
            ev_battery_health_pct=self._ev_taper_detector.battery_health_pct,
        )

    def _build_per_charger_intelligence(self) -> dict:
        """Build per-charger intelligence data from per-charger taper detectors (#193)."""
        if not self._ev_taper_detectors:
            return {}

        ev_chargers_cfg = self.config.get("ev_chargers", [])
        result = {}
        for cid, detector in self._ev_taper_detectors.items():
            # Per-charger vehicle SOC pass-through (#193): without this, every
            # detector starts at _energy_since_full=0 and reports 100% forever
            # — even when the user configured a real vehicle_soc_entity.
            charger_cfg = next((c for c in ev_chargers_cfg if c.get("id") == cid), {})
            per_charger_soc_entity = charger_cfg.get("vehicle_soc_entity", "")
            per_charger_vehicle_soc: Optional[float] = None
            # Explicit per-iteration reset: the provenance memo below reads
            # this, and a charger without a SOC entity must not inherit the
            # previous charger's state object (#708 / the #616 class).
            soc_state = None
            if per_charger_soc_entity:
                soc_state = self.hass.states.get(per_charger_soc_entity)
                if soc_state and soc_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    try:
                        per_charger_vehicle_soc = float(soc_state.state)
                    except (ValueError, TypeError):
                        _LOGGER.debug("Vehicle SOC %s not numeric: %r (#259)", per_charger_soc_entity, soc_state.state)

            # If we have no real SOC and the detector has no calibration data,
            # the virtual 100% default is misleading — return None so the sensor
            # displays as unavailable until first real reading.
            if per_charger_vehicle_soc is None and not detector._soc_anchored and detector._energy_since_full == 0.0:
                soc: Optional[float] = None
            else:
                soc = detector.get_virtual_soc(per_charger_vehicle_soc)

            taper_data = detector.get_taper_data() if hasattr(detector, 'get_taper_data') else None

            # (#440) Per-charger skip-decision latch removed alongside the
            # skip-decision wiring — charge mode is the sole authority
            # on whether to charge at night now.
            #
            # #708 — provenance of the SOC reading: WHAT was last read and
            # WHEN. The instant comes from the reading's own
            # ``last_changed``, deliberately: a poll that re-publishes the
            # same value bumps only ``last_reported``, and for steering a
            # value that hasn't CHANGED in 28 minutes of charging is
            # exactly as stale as one that wasn't re-published.
            #
            # It is remembered, equally deliberately. When an entity goes
            # unavailable HA writes a NEW state, so reading ``last_changed``
            # off the live entity dates the OUTAGE, not the reading — a
            # sensor dead for half an hour reported "0 min ago", and the
            # card's info line lost the value it was explaining at the
            # moment the estimate took over the gauge. The age of a reading
            # is measured from the reading, so we keep the last usable one.
            if per_charger_vehicle_soc is not None and soc_state is not None:
                self._soc_last_seen[cid] = (
                    per_charger_vehicle_soc, soc_state.last_changed
                )
            _seen = self._soc_last_seen.get(cid) if per_charger_soc_entity else None
            soc_last: Optional[float] = None
            soc_last_at: Optional[str] = None
            soc_age_min: Optional[float] = None
            if _seen is not None and _seen[1] is not None:
                soc_last, _seen_at = _seen
                soc_last_at = _seen_at.isoformat()
                soc_age_min = round(
                    (dt_util.utcnow() - _seen_at).total_seconds() / 60
                )

            result[cid] = {
                "estimated_soc": round(soc, 1) if soc is not None else None,
                # #383: surface the real per-charger vehicle SOC reading
                # so each charger card can display its own car's SOC
                # instead of falling back to the global ``sem_vehicle_soc``
                # sensor (which gets context-swap clobbered across the
                # per-charger loop). ``None`` when no
                # ``vehicle_soc_entity`` is configured for this charger.
                "vehicle_soc": (
                    round(per_charger_vehicle_soc, 1)
                    if per_charger_vehicle_soc is not None else None
                ),
                "minutes_to_full": taper_data.minutes_to_full if taper_data else None,
                "battery_health": detector.battery_health_pct,
                # #708 — measurement-only session estimate + sensor age,
                # for the charger card's stale-sensor info line. NOT a
                # SOC display value: the gauge keeps showing the sensor.
                "energy_accounted_soc": (
                    round(det_ea, 1)
                    if (det_ea := detector.energy_accounted_soc()) is not None
                    else None
                ),
                # #708 — provenance: the last usable reading and the instant
                # it was taken. The card renders "Car: {soc}% ({age} min
                # ago)" from these, so the line survives the sensor it
                # describes going unavailable. A TIMESTAMP, not an age: an
                # age attribute moves every minute and would re-arm the
                # #581 recorder churn; the card ticks the clock itself.
                "vehicle_soc_last": soc_last,
                "vehicle_soc_last_at": soc_last_at,
                "vehicle_soc_age_min": soc_age_min,
                "estimate_stop_active": detector._estimate_stop_active,
            }

        return result

    # Guard against an absurd catch-up after a long outage. The decay itself
    # is already clamped at battery capacity (``apply_daily_decay`` caps
    # ``energy_since_full``), so this only bounds the loop and the log noise.
    MAX_DECAY_CATCHUP_DAYS = 7

    def _record_source_ledgers(self, now_time, energy, today_s, today) -> None:
        """(#822) Score every installed forecast source against reality.

        One ``ForecastLedger`` per source, settled from the same actual as the
        active one, so ``trust()`` answers "how good is THIS source on THIS
        roof" with the maths #778 already proved out. No new statistics, no
        normalisation, and nothing here re-points the reader — comparing a
        source must not change which one is in use.
        """
        from datetime import timedelta

        from .forecast_ledger import ForecastLedger

        reader = getattr(self, "_forecast_reader", None)
        if reader is None or not hasattr(reader, "peek_sources"):
            return

        ledgers = getattr(self, "_source_ledgers", None)
        if ledgers is None:
            raw = {}
            if self._storage is not None:
                try:
                    raw = self._storage.get_source_ledgers_state() or {}
                except Exception:  # noqa: BLE001
                    raw = {}
            ledgers = {name: ForecastLedger.from_dict(state or {})
                       for name, state in raw.items()}
            self._source_ledgers = ledgers

        actual = getattr(energy, "daily_solar", None)

        seen = reader.peek_sources()
        for name in seen:
            led = ledgers.get(name)
            if led is None:
                led = ledgers[name] = ForecastLedger()
            if actual is not None:
                led.settle(today_s, actual)

        # Record the horizons once a day, and only once SUCCESSFULLY — the
        # same rule the active ledger learned the hard way (#778): marking the
        # day done before anything was written burns it permanently.
        if getattr(self, "_source_ledger_day", None) == today_s:
            return
        recorded = 0
        for name, values in seen.items():
            led = ledgers[name]
            for horizon, key in ((0, "today_kwh"), (1, "tomorrow_kwh")):
                value = values.get(key)
                # 0.0 means "this source does not publish that far"; recording
                # it would teach the ledger a lie.
                if value:
                    led.record(str(today + timedelta(days=horizon)),
                               horizon, value)
                    recorded += 1
        if not recorded:
            return
        self._source_ledger_day = today_s
        if self._storage is not None:
            try:
                self._storage.set_source_ledgers_state(
                    {n: l.to_dict() for n, l in ledgers.items()})
            except (AttributeError, TypeError, ValueError) as err:
                _LOGGER.warning("source ledgers not persisted: %s", err)
        _LOGGER.info(
            "#822 source ledgers: recorded %d horizon(s) across %d source(s) "
            "for %s — %s",
            recorded, len(seen), today_s,
            {n: v.get("today_kwh") for n, v in seen.items()},
        )

    def source_accuracy(self) -> dict:
        """(#822) Per-source trust, for the card and the diagnostics.

        ``None`` for a source with too few settled days — the ledger refuses
        to score on thin evidence and that refusal must reach the user rather
        than being rendered as a confident number.
        """
        out = {}
        for name, led in (getattr(self, "_source_ledgers", None) or {}).items():
            try:
                out[name] = {
                    "trust_today": led.trust(0),
                    "trust_tomorrow": led.trust(1),
                    "settled_days": len(getattr(led, "_days", {}) or {}),
                }
            except Exception:  # noqa: BLE001
                continue
        return out

    def _record_forecast_horizons(
        self, forecast_data, energy, now_time, power=None,
    ) -> None:
        """(#778) Keep the per-horizon forecast ledger up to date.

        Records what we believe today about today, tomorrow and the day after,
        and settles today with what the sun has actually delivered so far. The
        settle is deliberately every-cycle and idempotent: the last value
        written before midnight is the day's final figure, which needs no
        rollover hook and cannot be lost to a restart at 23:59.
        """
        from datetime import timedelta

        from .forecast_ledger import ForecastLedger

        led = getattr(self, "_forecast_ledger", None)
        if led is None:
            raw = {}
            if self._storage is not None:
                try:
                    raw = self._storage.get_forecast_ledger_state() or {}
                except Exception:  # noqa: BLE001
                    raw = {}
            led = ForecastLedger.from_dict(raw)
            self._forecast_ledger = led

        today = now_time.date()
        today_s = str(today)

        # Settle today with what has actually arrived (idempotent).
        actual = getattr(energy, "daily_solar", None)
        if actual is not None:
            led.settle(today_s, actual)

        # Record the horizons once a day — once SUCCESSFULLY, which is not the
        # same thing. The first version marked the day done before knowing
        # whether anything had been recorded, so a restart on a cycle where the
        # forecast was not yet populated burned that day permanently: the rig
        # showed `horizons=[]` against a settled actual, for a day whose
        # forecast was sitting right there.
        if getattr(self, "_forecast_ledger_day", None) != today_s:
            recorded = 0
            for horizon, value in (
                (0, getattr(forecast_data, "forecast_today_kwh", None)),
                (1, getattr(forecast_data, "forecast_tomorrow_kwh", None)),
                (2, getattr(forecast_data, "forecast_d2_kwh", None)),
            ):
                # 0.0 means "this source does not publish that far" — recording
                # it as a forecast of nothing would teach the ledger a lie.
                if value:
                    led.record(str(today + timedelta(days=horizon)), horizon, value)
                    recorded += 1
            if recorded:
                self._forecast_ledger_day = today_s
                _LOGGER.info(
                    "#778 ledger: recorded %d horizon(s) for %s "
                    "(today=%s tomorrow=%s d2=%s)",
                    recorded, today_s,
                    getattr(forecast_data, "forecast_today_kwh", None),
                    getattr(forecast_data, "forecast_tomorrow_kwh", None),
                    getattr(forecast_data, "forecast_d2_kwh", None),
                )
            else:
                _LOGGER.warning(
                    "#778 ledger: nothing recorded for %s — forecast reads "
                    "today=%r tomorrow=%r d2=%r",
                    today_s,
                    getattr(forecast_data, "forecast_today_kwh", None),
                    getattr(forecast_data, "forecast_tomorrow_kwh", None),
                    getattr(forecast_data, "forecast_d2_kwh", None),
                )
            if recorded and self._storage is not None:
                try:
                    self._storage.set_forecast_ledger_state(led.to_dict())
                except (AttributeError, TypeError, ValueError) as _se:
                    _LOGGER.warning("forecast ledger not persisted: %s", _se)

        # (#822) The same question, asked of every installed source.
        #
        # Users install two or three forecast integrations to find out which
        # one is right for their roof, and SEM has been picking one and
        # ignoring the rest. The obvious comparison — put their numbers side
        # by side — is worthless: on the dev rig they read 125.6 / 47.2 / 20.0
        # kWh for one day, and that 6x spread was three DIFFERENT CONFIGURED
        # ARRAYS, not three opinions. SEM cannot see how a third-party
        # integration was configured, so it cannot normalise them.
        #
        # What it can do is score each against what the roof actually
        # produced — exactly what the ledger above already does for the active
        # source. One ledger per source, same settle, same trust maths: a
        # source configured for the wrong array scores badly and says so, and
        # the answer is measured rather than assumed.
        try:
            self._record_source_ledgers(now_time, energy, today_s, today)
        except Exception:  # noqa: BLE001 — comparison never costs a cycle
            _LOGGER.debug("source ledgers skipped", exc_info=True)

        # (#778 phase 1) Publish the evidence, act on none of it. These are the
        # quantities honestly computable today; the spendable budget itself
        # waits for the day ledger's refill term (phase 3), because publishing
        # it from a raw forecast would systematically over-promise.
        def _round_or_none(value, digits):
            """Round for publication, preserving an honest None."""
            return None if value is None else round(float(value), digits)

        from .measured_capacity import measured_capacity

        tracker = getattr(self, "_battery_night", None)
        cap = None
        try:
            cap = measured_capacity(tracker.sealed) if tracker is not None else None
        except Exception:  # noqa: BLE001
            cap = None

        nameplate = self.config.get("battery_capacity_kwh")
        drift = None if cap is None else cap.drift_vs(nameplate)

        # (#778 phases 3-4) Assemble the budget from measured inputs. Every
        # term prefers evidence over configuration and falls back honestly:
        #   capacity  — measured kWh/% if enough qualifying nights, else the
        #               configured nameplate;
        #   need      — the high-percentile observed drain (the learner-safe
        #               envelope), else None, which spends nothing;
        #   refill    — tomorrow's forecast AFTER the house and committed
        #               demands, trust-scaled per horizon, never the raw scalar.
        from .measured_capacity import expected_overnight_need
        from .refill_estimate import estimate_refill
        from .spendable_budget import spendable_budget

        # `sealed` is a METHOD on BatteryNightTracker, not a property — reading
        # it without calling handed measured_capacity a bound method and every
        # sensor went unavailable. Caught on .175 only because the handler above
        # was narrowed to WARNING; as a DEBUG line it was invisible.
        sealed = []
        try:
            if tracker is not None:
                sealed = tracker.sealed() if callable(tracker.sealed) else tracker.sealed
        except (AttributeError, TypeError):
            sealed = []

        usable_kwh = cap.usable_kwh if cap is not None else _f_or_none(nameplate)
        need_kwh = expected_overnight_need(sealed)
        soc_now = getattr(power, "battery_soc", None)

        headroom = None
        if usable_kwh and soc_now is not None:
            try:
                headroom = max(0.0, usable_kwh * (100.0 - float(soc_now)) / 100.0)
            except (TypeError, ValueError):
                headroom = None

        refill = estimate_refill(
            getattr(forecast_data, "forecast_tomorrow_kwh", None),
            house_tomorrow_kwh=need_kwh,
            committed_demand_kwh=self.config.get("daily_ev_target") or 0.0,
            pack_headroom_kwh=headroom,
            trust=led.trust(1),
        )

        budget = spendable_budget(
            soc_pct=soc_now,
            usable_capacity_kwh=usable_kwh,
            overnight_need_kwh=need_kwh,
            expected_refill_kwh=refill.refill_kwh,
            # A dict default does NOT fire when the key is present holding
            # null, which is how an install that never set a reserve looks.
            # Pass the absence through and let spendable_budget name what
            # silence means, in one place.
            static_floor_pct=self.config.get("battery_reserve_soc"),
            # Absences pass through; spendable_budget names what silence
            # means, in one place, for all three tunables.
            pessimism=self.config.get("forecast_pessimism"),
            discharge_efficiency=self.config.get("battery_discharge_efficiency"),
            # (Build 0) measured trust on the refill relaxes the default
            # pessimism to 1.0 — the p20 measurement does that job now.
            refill_trusted=bool(getattr(refill, "trusted", False)),
        )

        # (#778 phase 6) The state a card renders, published rather than
        # inferred. See planning_phase for why the reason strings must not be
        # matched on.
        from .measured_capacity import MIN_NEED_SAMPLES, usable_nights
        from .forecast_ledger import MIN_SAMPLES_FOR_TRUST
        from .planning_phase import planning_phase

        phase = planning_phase(
            nights_sealed=usable_nights(sealed),
            nights_required=MIN_NEED_SAMPLES,
            overnight_need_kwh=need_kwh,
            usable_capacity_kwh=usable_kwh,
            spendable_kwh=budget.spendable_kwh,
        )

        self._planning_evidence = {
            "planning_phase": phase,
            # The progress a user watches while the evidence accrues. Without
            # these the learning state is a bare 0.0, which reads as "nothing
            # to spend" rather than "not measured yet".
            # The count the GATE uses, not the raw record length: a night
            # sealed twice, or sealed untrainable, is not progress.
            "nights_sealed": usable_nights(sealed),
            "nights_recorded_raw": len(sealed),
            "nights_required": MIN_NEED_SAMPLES,
            "forecast_days_d1": led.settled_samples(1),
            "forecast_days_d2": led.settled_samples(2),
            "forecast_days_required": MIN_SAMPLES_FOR_TRUST,
            # False means no source publishes this horizon at all — a fact
            # that never resolves by waiting, unlike thin evidence.
            "forecast_d1_available": led.has_horizon(1),
            "forecast_d2_available": led.has_horizon(2),
            "battery_measured_capacity_kwh": None if cap is None else cap.usable_kwh,
            "battery_capacity_kwh_per_pct": None if cap is None else cap.kwh_per_pct,
            "battery_capacity_samples": 0 if cap is None else cap.samples,
            "battery_capacity_drift_pct": (
                None if drift is None else round(drift * 100.0, 1)),
            "battery_capacity_reason": (
                "not enough qualifying nights yet" if cap is None else cap.reason),
            # Trust stays None until a horizon has earned it — never a
            # confident-looking 1.0 (see forecast_ledger).
            # Rounded at the publisher (bug class 51): trust is a ratio a
            # person reads as a percentage, and 0.840207806207237 churns a
            # recorder row on every cycle for digits nobody can act on.
            "forecast_trust_d1": _round_or_none(led.trust(1), 3),
            "forecast_trust_d2": _round_or_none(led.trust(2), 3),
            # (#778) The budget itself — still driving nothing. Published so a
            # season of mornings can judge it before it is allowed to spend.
            "battery_overnight_need_kwh": need_kwh,
            "battery_expected_refill_kwh": refill.refill_kwh,
            "battery_refill_clipped_kwh": refill.clipped_kwh,
            "battery_refill_reason": refill.reason,
            "battery_spendable_kwh": budget.spendable_kwh,
            "battery_dynamic_floor_pct": budget.floor_pct,
            "battery_spendable_reason": budget.reason,
        }

    def _run_due_daily_decay(self, now_time, today_date, power) -> None:
        """Run the virtual-SOC daily decay if it hasn't run yet today (#645).

        The decay used to be a side effect of the hour-bucket rollover, gated
        on ``_tracker_date``. That date is re-initialised to *today* in
        ``__init__`` on purpose — "so restarts don't re-apply daily decay" —
        and the trade-off was deliberate: never decay twice, at the cost of
        not decaying at all when a restart spans midnight. Only one of those
        two is actually required. Persisting the date the decay LAST RAN
        separates them:

        * restart later the same day → last-decay is today → no decay (the
          no-double-decay property the original comment was protecting);
        * restart spanning midnight → last-decay is yesterday → the decay
          fires once, where it used to be skipped;
        * fresh install / no persisted date → adopt today and don't decay
          (a brand-new detector has no ``last_full_timestamp`` anyway).

        A multi-day outage catches up one decay per missed day, bounded by
        ``MAX_DECAY_CATCHUP_DAYS``. Erring toward *more* decay is the safe
        direction: an under-decayed virtual SOC reads "still nearly full" and
        silently skips a night charge the car needed, while an over-decayed
        one at worst schedules a charge that tapers out early. Every catch-up
        day is charged the SAME predicted consumption (the predictor is asked
        about today, not about each missed weekday) — deliberately, since the
        alternative is inventing per-day history SEM never observed, and the
        result is clamped at battery capacity anyway.
        """
        if self._last_decay_date is None:
            # Nothing persisted (fresh install, or storage restore hasn't run
            # yet on the very first cycle). Adopt today without decaying.
            self._last_decay_date = today_date
            self._persist_last_decay_date()
            return

        if self._last_decay_date >= today_date:
            return

        missed = (today_date - self._last_decay_date).days
        runs = min(missed, self.MAX_DECAY_CATCHUP_DAYS)
        if missed > runs:
            _LOGGER.info(
                "Day rollover: %d days since the last virtual-SOC decay, "
                "applying %d (capped)", missed, runs,
            )
        for _ in range(runs):
            self._apply_daily_taper_decay(now_time, power)
        self._last_decay_date = today_date
        self._persist_last_decay_date()

    def _restore_last_decay_date(self) -> None:
        """Load ``_last_decay_date`` from storage at first refresh (#645).

        A method rather than three inline lines so the restore is testable
        on its own — the ordering pin (restore before the rollover check) is
        a source assertion, but "a stored date actually lands as a ``date``"
        has to be exercised, not read.
        """
        stored = self._storage.get_last_decay_date()
        if not stored:
            return
        try:
            self._last_decay_date = date.fromisoformat(stored)
        except ValueError:
            _LOGGER.debug("Ignoring malformed last_decay_date %r", stored)

    def _persist_last_decay_date(self) -> None:
        """Write ``_last_decay_date`` through to storage (#645).

        Writes through IMMEDIATELY rather than riding the batched save. The
        batched one uses ``async_delay_save``, which re-arms its timer on every
        call — under the continuous update loop that means it only ever fires
        at a clean shutdown (see ``async_save_daily_throttled``'s note). A
        value whose entire purpose is to survive a restart cannot be persisted
        by a mechanism that only runs at a graceful one. Cheap: at most one
        write per day. Live-caught on HA-TEST — the key was absent from the
        store ten minutes after deploy.
        """
        try:
            self._storage.set_last_decay_date(self._last_decay_date.isoformat())
            self.hass.async_create_task(self._storage.async_save_energy_now())
        except Exception as e:
            # Bookkeeping only — never take down the update cycle for it. The
            # cost of losing this write is one repeated decay after the next
            # restart, so WARNING (not DEBUG): it is rare, once-a-day, and
            # explains a virtual SOC that dropped twice.
            _LOGGER.warning("Could not persist last decay date: %s", e)

    def _apply_daily_taper_decay(self, now_time, power) -> None:
        """Day-rollover virtual-SOC decay, PER charger (#106, #648).

        While a car is away SEM can't see it being driven, so at each day
        rollover the taper detector's ``energy_since_full`` is advanced by the
        predicted daily consumption — that's what keeps the virtual SOC from
        reading "still full from Sunday" all week.

        It used to run through the ``_ev_taper_detector`` property, which
        resolves the PRIMARY detector only, gated on the FLEET
        ``power.ev_connected``. Two ways that goes wrong on a multi-charger
        install (ledger class 3, fleet-read-for-one):

        * **Secondary detectors never decayed at all.** Car 2 charges full on
          Sunday and drives all week; its detector still believes ~100 %. That
          is load-bearing, not cosmetic: ``_resolve_charger_soc`` falls back to
          the per-charger virtual SOC when the real SOC entity is offline, so
          ``build_night_target_map`` computes remaining ≈ 0 and silently skips
          a night charge that was needed.
        * **One plugged car suppressed decay for every other car.** The fleet
          gate is true while ANY charger is connected, so car 2 sitting plugged
          in overnight froze car 1's virtual SOC too.

        Each detector is now gated on its OWN
        ``_last_ev_connected_per_charger[cid]`` — the same per-charger
        connection state published as ``charger_<cid>_connected``.
        """
        detectors = dict(getattr(self, "_ev_taper_detectors", None) or {})
        if detectors:
            connected = getattr(self, "_last_ev_connected_per_charger", None) or {}
            targets = [
                (cid, det) for cid, det in detectors.items()
                if det is not None and not connected.get(cid, False)
            ]
        else:
            # Legacy / pre-first-loop: one default detector and no per-charger
            # connection state to consult, so the fleet flag IS this charger's.
            # FLEET-READ: single-detector install — no per-charger state exists.
            targets = (
                [] if power.ev_connected
                else [(None, self._ev_taper_detector)]
            )

        targets = [(cid, det) for cid, det in targets if det is not None
                   and det.last_full_timestamp]
        if not targets:
            return

        # Shared across chargers — computed once, only when something decays.
        predicted = self._predictor.predict_ev_consumption_tomorrow(now_time)
        fallback = self.config.get("daily_ev_target", 10)
        temp_factor = EVTaperDetector.temperature_correction_factor(
            self._read_outdoor_temperature()
        )
        for cid, det in targets:
            if cid is not None:
                _LOGGER.debug("Day rollover: decaying virtual SOC for %s", cid)
            det.apply_daily_decay(predicted, fallback, temp_factor)

    def _read_outdoor_temperature(self) -> float:
        """Read outdoor temperature from weather entity or configured sensor.

        Used for temperature-corrected EV consumption prediction (#106).
        Falls back to 15°C (spring-like) if no weather data available.
        """
        # Try configured entity first
        temp_entity = self.config.get("outdoor_temperature_entity", "")
        if temp_entity:
            state = self.hass.states.get(temp_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass

        # Fall back to any weather entity
        for state in self.hass.states.async_all("weather"):
            temp = state.attributes.get("temperature")
            if temp is not None:
                try:
                    return float(temp)
                except (ValueError, TypeError):
                    pass

        return 15.0  # Safe default

    # Solar charging state sets
    def _restore_per_charger_detectors(self, ev_intel_state) -> None:
        """(#756/P3) Warm every stored per-charger taper detector at setup.

        The demand signature's fullness term and the collector's car-full
        gate both read ``_ev_taper_detectors`` — state that exists in
        storage at boot but used to materialize lazily, one EV cycle in.
        A signature computed from the cold registry is not the same night
        as one computed from the warm one, and the tick restamped a
        restored plan over exactly that difference. A detector that
        already exists (accrued live state) is never clobbered.
        """
        try:
            chargers = (ev_intel_state or {}).get("chargers") or {}
            if not isinstance(chargers, dict):
                return
            for cid, per_charger_state in chargers.items():
                if cid in self._ev_taper_detectors:
                    continue
                if not isinstance(per_charger_state, dict):
                    continue
                det = EVTaperDetector(self.config)
                det.restore_state(per_charger_state)
                self._ev_taper_detectors[str(cid)] = det
        except Exception as e:  # noqa: BLE001 — a bad payload must not fail setup
            _LOGGER.warning(
                "#756: per-charger detector restore skipped (%s) — the "
                "fleet warms lazily as before", e,
            )

    def _restore_device_runtimes(self) -> None:
        """Restore device runtimes from storage onto empty devices.

        Safe to call repeatedly: only fills a device whose live accrued
        runtime is still 0 (a freshly-(re)built object), NEVER clobbering a
        value that already accrued this session. That idempotence is what lets
        the registry re-invoke this after EVERY ``async_refresh_devices``
        rebuild (#622), not just once at setup.

        Why re-invoking matters: an auto-discovered load (e.g. alexmc1510's
        pool pump) whose backing switch entity isn't ready during initial
        setup is only created by the 35 s delayed re-discovery — AFTER the
        one-shot setup restore already ran and found no device. That rebuild
        restores accrued runtime only from an in-memory snapshot
        (``_restore_accrued_runtimes``), which is empty for a device that was
        never populated from storage — so the "X/Y h on solar today" progress
        reset to 0 and the load re-ran its whole daily target on every restart.
        Re-running this from storage on each rebuild fills that late device.

        A restore that lands a stale ``meter_day`` (a restart spanning
        midnight fills yesterday's accrued onto a fresh device) self-corrects:
        the next ``update_daily_runtime(today)`` detects the rollover and
        resets accrued to 0 within one cycle — the same rebase #586 relies on.

        (P3, 13.08) Running at all is also a SIGNAL: ``_runtimes_restored``
        flips here and gates the energy plan tick — a demand signature
        computed before this ran reads zero accrued runtime (wrong
        deficits), and comparing that cold signature against a restored
        stamp's warm one restamped the night on every reboot. Set BEFORE
        the storage guard: an install with no storage has nothing to wait
        for, and a tick gated on a flag that never flips would never plan.
        """
        self._runtimes_restored = True
        if not self._storage:
            return
        runtimes = self._storage.get_device_runtimes()
        for device_id, data in runtimes.items():
            device = self._surplus_controller.get_device(device_id)
            if not device:
                continue
            # (#768) The day's ENERGY restores independently of the runtime,
            # under its own emptiness guard: a load with no runtime goal accrues
            # zero seconds forever, so the ``accumulated_sec > 0`` test below
            # would let this run re-fill a live value on every rebuild.
            # Class-qualified on purpose: the runtime-restore tests drive this
            # method with a duck-typed coordinator (#622), which has no bound
            # methods of its own.
            SEMCoordinator._restore_device_energy(device, data)
            # Never overwrite a live value — only fill a device that came back
            # empty (fresh object, nothing accrued yet). Mirrors the in-memory
            # _restore_accrued_runtimes contract so the two restore paths agree.
            if float(getattr(device, "_daily_runtime_accumulated_sec", 0.0) or 0.0) > 0.0:
                continue
            try:
                meter_day = date.fromisoformat(data["meter_day"])
                device._daily_runtime_accumulated_sec = data["accumulated_sec"]
                device._daily_runtime_meter_day = meter_day
                _LOGGER.debug(
                    "Restored runtime for %s: %.0fs (meter_day=%s)",
                    device_id, data["accumulated_sec"], meter_day,
                )
            except (KeyError, ValueError) as e:
                _LOGGER.debug("Failed to restore runtime for %s: %s", device_id, e)

    @staticmethod
    def _restore_device_energy(device, data: Dict[str, Any]) -> None:
        """(#768) Fill a fresh device's daily energy from storage.

        Only ever fills — a device that already booked energy this session
        keeps its live value, and a restored counter baseline is never pushed
        onto a device that has already read its counter. A stale meter day
        needs no guard here for the same reason the runtime doesn't: the next
        ``update_daily_runtime`` sees the rollover and zeroes both.
        """
        try:
            if float(getattr(device, "_daily_energy_kwh", 0.0) or 0.0) == 0.0:
                device._daily_energy_kwh = float(data.get("accumulated_kwh") or 0.0)
            if getattr(device, "_energy_counter_last_kwh", None) is None:
                baseline = data.get("counter_baseline_kwh")
                if baseline is not None:
                    device._energy_counter_last_kwh = float(baseline)
        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.debug("Failed to restore daily energy for %s: %s",
                          getattr(device, "device_id", "?"), e)

    def _file_device_energy(self, meter_day) -> None:
        """(#769) File each device's just-booked kWh into the ledger.

        The device knows what it consumed (#768) and, where it has modes worth
        telling apart, which bucket to file it under; the ledger knows about
        periods. This is the seam, and it is deliberately thin: no decision, no
        estimate, no reinterpretation of the number on the way through.

        (#772) One lookup joined the seam: a comfort zone that names no
        bucket of its own gets one derived from its ``comfort:{did}`` plan
        gate — in-block or out — because the plan's placement is coordinator
        state the device cannot see. Still no decision about the NUMBER;
        only about which shelf it lands on.

        A device that booked nothing this cycle is not filed at all — a device
        with an unreadable meter must not be recorded as one that consumed
        zero (#755 contract 1).
        """
        calc = getattr(self, "_energy_calculator", None)
        if calc is None:
            return
        now = dt_util.now()
        for device in self._surplus_controller._devices.values():
            increment = getattr(device, "last_cycle_energy_kwh", 0.0) or 0.0
            if not increment:
                continue
            split = getattr(device, "energy_split_label", None)
            if split is None:
                split = self._comfort_split_for(device, now)
            calc.accumulate_device_energy(
                device.device_id, increment, meter_day, split=split,
            )
            # (#773) The same increment, booked once more into the
            # midnight-keyed controlled-loads mirror the baseload
            # subtraction runs against. ``meter_day`` above is the
            # device's SUNRISE day; the mirror wants the calendar day —
            # the #703/#704 boundary lesson, applied at the seam.
            calc.accumulate_controlled_load(
                increment, now.date(),
                estimated=not getattr(
                    device, "daily_energy_is_measured", False),
            )

    def _comfort_split_for(self, device, now):
        """(#772) The comfort bucket for this cycle's kWh, or None.

        Derived HERE, at filing time, from the same ``comfort:{did}`` gate
        the actuation layer consults — not from a stamp cached on the
        device, which would go stale the moment the plan clears or the
        kill-switch flips mid-day.

        Three deliberate edges:
        - A DISENGAGED band (no band, dead thermometer, misconfig) returns
          None: the zone cannot say what its band wanted, so it files no
          comfort claim at all (#755 contract 1) — and the gate is not
          consulted, so a band-less pool pump never shows up in the
          coverage log as a comfort demand.
        - An UNCOVERED gate is OUT-of-block, not None: a night the planner
          never banked is banking-not-working, and it must land in the
          ratio's denominator. Filing it unsplit would make an idle
          planner look like a perfect one.
        - The device's own label (the heat pump's SG state, #769) is
          senior — the caller only asks here when the device named no
          bucket itself.
        """
        try:
            if getattr(device, "comfort_state", "disengaged") == "disengaged":
                return None
            gate = self._energy_plan_gate(
                f"comfort:{device.device_id}", now
            )
        except Exception:  # noqa: BLE001 — a broken band files no claim
            return None
        from .energy_calculator import COMFORT_SPLIT_IN, COMFORT_SPLIT_OUT
        if getattr(gate, "covered", False) and getattr(gate, "in_block", False):
            return COMFORT_SPLIT_IN
        return COMFORT_SPLIT_OUT

    def _persist_device_runtimes(self) -> None:
        """Save device runtimes — and, for EVERY device, the day's energy.

        (#768) The runtime half is gated on the device having a runtime goal;
        the energy half is not, deliberately. The loads that silently vanish
        into ``home`` (#767) are precisely the auto-discovered ones nobody
        configured a target on.
        """
        if not self._storage:
            return
        for device in self._surplus_controller._devices.values():
            if not device._daily_runtime_meter_day:
                continue  # never ran a cycle — nothing to stamp it with
            # The row used to be written only for a device with a runtime goal
            # (#620: including a cap-ONLY one, so a restart can't lose the cap
            # it had already hit). Now every device gets one, and the accrued
            # seconds ride along for free.
            self._storage.set_device_runtime(
                device.device_id,
                device._daily_runtime_accumulated_sec,
                device._daily_runtime_meter_day.isoformat(),
                accumulated_kwh=getattr(device, "_daily_energy_kwh", 0.0),
                counter_baseline_kwh=getattr(device, "_energy_counter_last_kwh", None),
            )

    def get_ed_config_detail(self) -> Optional[Dict[str, Any]]:
        """Full Energy Dashboard mapping (entity IDs + power source) per source.

        Exposed as attributes on the diag_ed_config sensor so the System card's
        Copy diagnostics can include the actual entity names — which makes a wrong
        mapping obvious, not just whether something is configured (#250). Returns
        None when SEM is not using the Energy Dashboard.
        """
        ed = self._energy_dashboard_config
        if ed is None:
            return None
        derived = getattr(ed, "derived_power", {}) or {}

        def _src(kind: str, entity_id) -> str:
            if kind in derived:
                return "derived"
            return "stat_rate" if entity_id else "none"

        return {
            "solar": {
                "power": ed.solar_power,
                "power_source": _src("solar", ed.solar_power),
                "energy": ed.solar_energy,
            },
            "grid": {
                "power": ed.grid_import_power,
                "power_source": _src("grid", ed.grid_import_power),
                "import_energy": ed.grid_import_energy,
                "export_energy": ed.grid_export_energy,
            },
            "battery": {
                "power": ed.battery_power,
                "power_source": _src("battery", ed.battery_power),
                "charge_energy": ed.battery_charge_energy,
                "discharge_energy": ed.battery_discharge_energy,
            },
        }

    def _build_ed_config_summary(self) -> str:
        """Summarize the Energy Dashboard mapping for the copy-diagnostics string.

        Shows, per source, whether power and energy are configured and where power
        came from (stat_rate / derived / none). Returns "legacy" when SEM is not
        using the Energy Dashboard. Kept compact (< 255 chars) for a sensor state.
        """
        ed = self._energy_dashboard_config
        if ed is None:
            return "legacy"

        derived = getattr(ed, "derived_power", {}) or {}

        def _pwr(kind: str, entity_id) -> str:
            if kind in derived:
                return "derived"
            return "stat_rate" if entity_id else "none"

        def _e(entity_id) -> str:
            return "ok" if entity_id else "MISSING"

        solar = f"solar:pwr={_pwr('solar', ed.solar_power)},energy={_e(ed.solar_energy)}"
        grid = (
            f"grid:pwr={_pwr('grid', ed.grid_import_power)},"
            f"imp={_e(ed.grid_import_energy)},exp={_e(ed.grid_export_energy)}"
        )
        batt = (
            f"batt:pwr={_pwr('battery', ed.battery_power)},"
            f"chg={_e(ed.battery_charge_energy)},dis={_e(ed.battery_discharge_energy)}"
        )
        return f"{solar} | {grid} | {batt}"

    def _build_system_status(self, power: PowerReadings, charging_state: str) -> SystemStatus:
        """Build system status from power readings."""
        status = SystemStatus()

        # Grid status
        if power.grid_import_power > 50:
            status.grid_status = "import"
        elif power.grid_export_power > 50:
            status.grid_status = "export"
        else:
            status.grid_status = "idle"

        # Battery status. #523: when the scheduler is actively selling to
        # the grid (FORCE_DISCHARGE this cycle), surface a distinct
        # "selling" state so the Battery card can show it instead of a
        # generic "discharging".
        if getattr(self, "_battery_arbitrage_active", False) and power.battery_discharge_power > 50:
            status.battery_status = "selling"
        elif power.battery_charge_power > 50:
            status.battery_status = "charging"
        elif power.battery_discharge_power > 50:
            status.battery_status = "discharging"
        else:
            status.battery_status = "idle"

        # Status flags
        status.solar_active = power.solar_power > 50
        status.ev_connected = power.ev_connected
        status.ev_charging = power.ev_charging
        status.battery_charging = power.battery_charge_power > 50
        status.battery_discharging = power.battery_discharge_power > 50
        status.grid_export_active = power.grid_export_power > 50

        return status

    async def async_update_config(self, config_update: Dict[str, Any]) -> None:
        """Update coordinator configuration.

        Mutate ``self.config`` in place rather than rebinding. Multiple
        components (TimeManager, EnergyCalculator, ChargingStateMachine,
        BatteryChargeAdapter, …) hold a reference to the original config
        dict captured at construction. Rebinding leaves them pointing at
        the stale dict, so a slider change like ``night_latest_end`` would
        update ``self.config`` but never reach ``time_manager._config``
        until the next integration reload. Caught live by
        tests/live/test_overnight_window.sh — without this, the night-end
        sensor stayed pinned at the old value after the slider moved.
        """
        self.config.update(config_update)
        self._mirror_primary_charger_to_global()  # keep legacy global keys fresh (#255)
        self.refresh_runtime_config()  # #547: push construction-cached scalars live
        _LOGGER.info("Configuration updated: %s", list(config_update.keys()))

    def refresh_runtime_config(self) -> None:
        """Push construction-cached scalar knobs into live controllers (#547).

        ``async_update_config`` (and the ``persist_*`` no-reload writers)
        mutate ``self.config`` in place, so every knob read *per-cycle* off
        ``self.config`` already applies live. The handful of scalars CACHED
        into a controller object at construction — and never re-read — used
        to need a full integration reload to take effect (the "I changed the
        setting but nothing happened until I restarted SEM" surprise).

        This re-derives those cached scalars from the current ``self.config``
        and assigns them via attribute / existing setter. It is a **refresh**,
        not a rebuild: stateful objects (the legionella timer, cost
        accumulators, smoothing windows, price-curve caches) are preserved —
        only the tunable is updated. Full-resync (re-read every knob, not just
        the changed one) keeps it idempotent and lets every config-mutation
        path call it without plumbing a changed-keys set.

        Structural keys (entity ids, EV phase count, tariff *mode*) still need
        a reload — those rebuild objects, not just retune them.
        """
        cfg = self.config

        # ── SurplusController: regulation offset + export cap ───────────
        sc = getattr(self, "_surplus_controller", None)
        if sc is not None:
            try:
                sc.regulation_offset = float(cfg.get("regulation_offset", 50))
                sc.max_export_w = float(cfg.get("max_export_power", 0))
            except (TypeError, ValueError):
                pass

            # Heat pump (registered with the surplus controller)
            hp = sc.get_device("heat_pump")
            if hp is not None:
                try:
                    hp.boost_offset = float(cfg.get("heat_pump_boost_offset", 2.0))
                    hp.max_setpoint = float(cfg.get("heat_pump_max_setpoint", 55.0))
                    hp.force_on_threshold = float(
                        cfg.get("heat_pump_force_on_threshold", 5000)
                    )
                    hp.invert_sg_ready = bool(cfg.get("heat_pump_invert_sg_ready", False))
                    # #602/#576 — priority is the DRAG-LIST position now (resolved
                    # by refresh_direct_device_priorities), NOT a standalone knob.
                    # (Previously clobbered here from heat_pump_priority every
                    # cycle, killing the drag position.)
                except (TypeError, ValueError):
                    pass

            # Hot water — push targets/interval only; the legionella timer
            # state (hours_since_legionella, _legionella_cycle_active) is
            # preserved because we never re-init the controller.
            hw = sc.get_device("hot_water")
            if hw is not None:
                try:
                    from ..devices.hot_water_controller import (
                        DEFAULT_LEGIONELLA_MIN_TEMP,
                    )
                    hw.max_temperature = float(cfg.get("hot_water_max_temperature", 70.0))
                    hw.min_temperature = float(
                        cfg.get("hot_water_minimum_temperature", 40.0)
                    )
                    hw.solar_target_temp = float(cfg.get("hot_water_solar_target", 50.0))
                    hw.legionella_target_temp = max(
                        float(cfg.get("hot_water_legionella_target", 65.0)),
                        DEFAULT_LEGIONELLA_MIN_TEMP,
                    )
                    hw.legionella_interval_hours = float(
                        cfg.get("hot_water_legionella_interval_hours", 168.0)
                    )
                    # #602/#576 — priority is the drag-list position now (see the
                    # heat-pump note above); was clobbered from hot_water_priority.
                except (TypeError, ValueError):
                    pass

        # ── EV chargers: per-charger surplus priority + min/max current on
        # the device; shed priority in the load manager. Per-charger writes
        # arm _skip_options_reload (no reload), so these device-cached
        # scalars are otherwise stuck until a real reload. Resolve each
        # charger's value with the same charger-override→global fallback the
        # construction path uses (__init__._cfg).
        ev_devices = getattr(self, "_ev_devices", None)
        if ev_devices:
            chargers_by_id = {
                c.get("id"): c
                for c in (cfg.get("ev_chargers") or [])
                if isinstance(c, dict)
            }

            from ..devices.base import resolve_max_current as _resolve_max_current

            def _cfg_charger(ccfg, key, default=None):
                v = ccfg.get(key) if isinstance(ccfg, dict) else None
                if v is not None:
                    return v
                v = cfg.get(key)
                return v if v is not None else default

            lm = getattr(self, "_load_manager", None)
            for cid, dev in ev_devices.items():
                ccfg = chargers_by_id.get(cid, {})
                try:
                    # Match the construction resolution (__init__._cfg).
                    # #604: the legacy ``ev_load_priority`` alias is gone —
                    # the v14→v15 migration mapped it into
                    # ``ev_surplus_priority``.
                    surplus_prio = int(_cfg_charger(
                        ccfg, "ev_surplus_priority", dev.priority,
                    ))
                    # (#576 P2.1) the drag list is the single authoritative
                    # priority axis: a drag override wins over the config seed,
                    # so the per-charger loop walks the chargers in the order
                    # the one list gives. ev_surplus_priority is now the seed
                    # default.
                    seed_prio = max(1, min(10, surplus_prio))
                    reg = getattr(self, "_device_registry", None)
                    dev.priority = (
                        reg.priority_for(cid, seed=seed_prio) if reg is not None
                        else seed_prio
                    )
                    dev.min_current = float(_cfg_charger(ccfg, "ev_min_current", 6))
                    # (#746) the refresh-in-place twin of the construction
                    # site — same resolver, so dragging the Max Amps slider
                    # takes effect without a reload.
                    dev.max_current = _resolve_max_current(
                        lambda k, d=None, _c=ccfg: _cfg_charger(_c, k, d)
                    )
                    # Re-derive the surplus-activation gate (HIGH, review): the
                    # SurplusController activates this charger on
                    # ``remaining_surplus >= min_power_threshold``, NOT on
                    # min_current directly — so a min-current change that didn't
                    # also update this scalar applied to the commanded current
                    # but not to whether the charger turns on. Mirror
                    # base.py:682 using the LIVE phases (post phase-switch).
                    ph = int(getattr(dev, "phases", 3) or 3)
                    volt = float(getattr(dev, "voltage", 230) or 230)
                    dev.min_power_threshold = dev.min_current * ph * volt
                except (TypeError, ValueError):
                    surplus_prio = dev.priority
                # (#576) Shed order = the ONE list position (reverse of charge
                # order under the load manager's "higher number sheds first").
                # ``dev.priority`` is the drag-authoritative slot (resolved from
                # the priority store above), so the latest-to-charge charger
                # (highest list number) sheds first — the #470 default coupling,
                # now driven by the single list. The separate ``ev_shed_priority``
                # knob (config field / number entity / v15 config data) was
                # removed entirely. Lives in the load manager's device dict
                # (load_device_<id>).
                if lm is not None and isinstance(
                    getattr(lm, "_devices", None), dict
                ):
                    ld = lm._devices.get(f"load_device_{cid}")
                    if isinstance(ld, dict):
                        try:
                            ld["priority"] = int(dev.priority)
                        except (TypeError, ValueError):
                            pass

        # ── Tariff provider: rates + thresholds. The EnergyCalculator's
        # cost rates are refreshed from the provider every cycle (see the
        # get_tariff_data() push in _async_update_data), so updating the
        # provider here is enough — the cost accumulators follow next cycle.
        tp = getattr(self, "_tariff_provider", None)
        if tp is not None:
            try:
                tp.export_rate = float(cfg.get("electricity_export_rate", 0.075))
                if isinstance(tp, DynamicTariffProvider):
                    tp.cheap_threshold = float(cfg.get("cheap_price_threshold", 0.15))
                    tp.expensive_threshold = float(
                        cfg.get("expensive_price_threshold", 0.35)
                    )
                    tp.fallback_price = _cfg_rate(
                        cfg, "electricity_import_rate", default=0.30
                    )
                    # #710: cached at construction, so options updates must
                    # push this live like the thresholds above. An absent key
                    # (upgraded install) preserves the current/legacy value.
                    tp.grid_import_surcharge = (
                        DynamicTariffProvider.normalize_grid_import_surcharge(
                            cfg.get(
                                "grid_import_surcharge",
                                tp.grid_import_surcharge,
                            )
                        )
                    )
                else:
                    # Static / Calendar share peak/off-peak rate fields. Fall
                    # back to the provider's CURRENT value when the key is
                    # absent so a factory-default calendar install (different
                    # construction default 0.35 vs static 0.3387) isn't nudged
                    # to a wrong rate by the refresh (MEDIUM, review).
                    tp.peak_rate = float(
                        cfg.get("electricity_import_rate", tp.peak_rate)
                    )
                    tp.off_peak_rate = _cfg_rate(
                        cfg, "electricity_off_peak_rate", "electricity_nt_rate",
                        default=tp.off_peak_rate,
                    )
            except (TypeError, ValueError):
                pass

    def sensors_ready(self) -> bool:
        """Check if required sensors are available."""
        return self._sensor_reader.sensors_ready()

    def _estimate_best_surplus_window(self, forecast, power, energy, dampened_remaining: float = None) -> str:
        """Estimate the best time window for running large appliances.

        Uses peak_time_today from forecast (if available) to suggest a window
        centered on peak solar production. Falls back to a generic midday
        window if no peak time data.

        Args:
            dampened_remaining: Real-time dampened remaining forecast (kWh).
                Falls back to raw forecast.forecast_remaining_today_kwh if not provided.
        """
        if not forecast.available:
            return ""

        now = dt_util.now()

        # If peak time is known (Solcast), build a window around it
        if forecast.peak_time_today:
            try:
                peak_parts = forecast.peak_time_today.split(":")
                peak_hour = int(peak_parts[0])
                # 2-hour window centered on peak
                start_h = max(6, peak_hour - 1)
                end_h = min(20, peak_hour + 1)
                return f"{start_h:02d}:00–{end_h:02d}:00"
            except (ValueError, IndexError):
                pass

        # Fallback: estimate from remaining forecast (dampened if available)
        remaining = dampened_remaining if dampened_remaining is not None else forecast.forecast_remaining_today_kwh
        current_hour = now.hour

        if current_hour >= 17 or remaining < 1:
            # Evening or very little solar left
            if forecast.forecast_tomorrow_kwh > 5:
                from ..utils.translate import get_text
                tomorrow_word = get_text(self.hass, "tomorrow", "tomorrow")
                return f"{tomorrow_word} 10:00–14:00"
            return ""

        # Generic midday window if we have decent forecast
        if remaining > 3:
            start_h = max(current_hour, 10)
            end_h = min(start_h + 3, 16)
            return f"{start_h:02d}:00–{end_h:02d}:00"

        return ""

    def _build_load_management_data(self, power: PowerReadings) -> LoadManagementData:
        """Build load management data from load manager or defaults."""
        lm_data = LoadManagementData()

        if self._load_manager:
            try:
                lm_info = self._load_manager.get_load_management_data()

                lm_data.target_peak_limit = lm_info.get("target_peak_limit", 5.0)
                lm_data.peak_limit_unlimited = lm_info.get("peak_limit_unlimited", False)
                lm_data.load_management_status = lm_info.get("state", "idle")
                lm_data.controllable_devices_count = lm_info.get("controllable_devices", 0)
                lm_data.available_load_reduction = lm_info.get("available_load_reduction", 0.0)

                # Devices shed info
                devices_shed = lm_info.get("devices_shed_list", [])
                if devices_shed:
                    lm_data.loads_currently_shed = ", ".join(devices_shed)
                else:
                    lm_data.loads_currently_shed = "none"

                # Calculate peak margin and percentage
                current_import_kw = power.grid_import_power / 1000
                lm_data.peak_margin = max(0, lm_data.target_peak_limit - current_import_kw)
                if lm_data.target_peak_limit > 0:
                    lm_data.current_vs_peak_percentage = min(100, (current_import_kw / lm_data.target_peak_limit) * 100)

                # Get consecutive peak values (15min rolling average)
                lm_data.consecutive_peak_15min = lm_info.get("consecutive_peak_15min", current_import_kw)
                lm_data.monthly_consecutive_peak = lm_info.get("monthly_consecutive_peak", 0.0)

                # (#657) The device table itself. Every other field of
                # lm_info was copied across; this one wasn't, so the load
                # management card's device list read a key nothing wrote.
                # ``or {}`` on purpose: a LoadManager with no managed devices
                # may report ``{"devices": None}``, and the card iterates this.
                lm_data.devices = lm_info.get("devices") or {}

                # Tariff info
                lm_data.controlled_tariff_status = lm_info.get("controlled_tariff_status", "unknown")
                lm_data.tariff_type = lm_info.get("tariff_type", "unknown")

                # Recommendation based on state — translated via get_text()
                from ..utils.translate import get_text as _gt
                state = lm_info.get("state", "normal")
                if state == "emergency":
                    lm_data.load_management_recommendation = _gt(self.hass, "Reduce load immediately!", "Reduce load immediately!")
                elif state == "shedding":
                    lm_data.load_management_recommendation = _gt(self.hass, "Reducing non-critical loads", "Reducing non-critical loads")
                elif state == "warning":
                    lm_data.load_management_recommendation = _gt(self.hass, "Monitor - approaching peak limit", "Monitor - approaching peak limit")
                else:
                    lm_data.load_management_recommendation = _gt(self.hass, "Normal operation", "Normal operation")

                # Peak trend based on recent changes
                if current_import_kw > lm_data.target_peak_limit * 0.9:
                    lm_data.peak_trend = "rising"
                elif current_import_kw < lm_data.target_peak_limit * 0.5:
                    lm_data.peak_trend = "low"
                else:
                    lm_data.peak_trend = "stable"

                # Calculate demand charge from monthly peak
                demand_rate = self.config.get("demand_charge_rate", 0.0)
                lm_data.power_charge_cost = round(lm_data.monthly_consecutive_peak * demand_rate, 2)

            except Exception as e:
                _LOGGER.debug("Could not get load management data: %s", e)

        return lm_data
