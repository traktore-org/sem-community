"""Main coordinator for Solar Energy Management.

This is a slim orchestrator that delegates to specialized modules:
- SensorReader: Hardware sensor reading
- EnergyCalculator: Energy integration from power
- FlowCalculator: Power and energy flow calculations
- ChargingStateMachine: Charging mode selection (solar, night, Min+PV)
- EVControlMixin: EV charging control (solar, night, Min+PV, session tracking)
- BatteryProtectionMixin: Battery discharge protection during night charging
- SEMStorage: Persistence
- NotificationManager: Mobile/KEBA notifications
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any, Dict, Optional

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
    ED_RESOLVE_MAX_ATTEMPTS,
    ChargingState,
    ENTITY_OBSERVER_MODE_SWITCH,
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
    UtilitySignalSensorData, SessionData, BatterySessionData,
)
from .health_check import HealthCheck
from .surplus_availability import SurplusAvailability
from .sensor_reader import SensorReader
from .energy_calculator import EnergyCalculator
from .flow_calculator import FlowCalculator
from .charging_control import ChargingStateMachine, ChargingContext
from .per_charger_context import PerChargerContext
from .storage import SEMStorage
from .notifications import NotificationManager
from .surplus_controller import SurplusController
from .cycle_trace import TraceCollector, LayerRecord, LayerStatus
from .energy_reclaim import reclaimable_battery_w
from .forecast_reader import ForecastReader
from .forecast_tracker import ForecastTracker
from .ev_control import EVControlMixin
from .battery_protection import BatteryProtectionMixin
from ..tariff import StaticTariffProvider, DynamicTariffProvider, PriceLevel
from ..tariff.calendar_provider import CalendarTariffProvider
from ..tariff.tariff_provider import _local_date as _tariff_local_date
from ..analytics.pv_performance import PVPerformanceAnalyzer
from ..analytics.consumption_predictor import ConsumptionPredictor
from .ev_taper_detector import EVTaperDetector
from ..analytics.energy_assistant import EnergyAssistant
from ..utility_signals import UtilitySignalMonitor

_LOGGER = logging.getLogger(__name__)


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


class SEMCoordinator(DataUpdateCoordinator, EVControlMixin, BatteryProtectionMixin):
    """Coordinator for Solar Energy Management.

    Orchestrates the flow:
    1. Read sensors (SensorReader)
    2. Calculate energy from power (EnergyCalculator)
    3. Calculate power/energy flows (FlowCalculator)
    4. Update charging state (ChargingStateMachine + CurrentControlDevice)
    5. Send notifications (NotificationManager)
    6. Persist data (SEMStorage)

    EV control and battery protection are provided by mixins
    (EVControlMixin, BatteryProtectionMixin) to keep this file focused
    on orchestration.
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
        self._ev_device = None  # Primary charger — set by __init__.py (backward compat)
        self._ev_devices: Dict[str, Any] = {}  # All chargers keyed by charger_id (#112)
        self._ev_last_change_time = None  # Reactive control timing
        self._ev_charge_started_at = None  # Disable delay: min hold timer to prevent cycling
        self._ev_enable_surplus_since = None  # Enable delay: surplus must persist before starting
        # Solar stability primary view (swapped per-charger by PerChargerContext).
        self._ev_last_set_amps_ts: Optional[float] = None
        self._ev_budget_history: list = []
        # Per-charger state dicts for multi-charger (#112)
        self._ev_stalled_since_per_charger: Dict[str, Optional[float]] = {}
        self._ev_enable_surplus_per_charger: Dict[str, Optional[float]] = {}
        self._ev_charge_started_per_charger: Dict[str, Optional[float]] = {}
        self._ev_last_change_per_charger: Dict[str, Any] = {}
        # False-stall guard per charger (#243)
        self._ev_reenable_attempts_per_charger: Dict[str, int] = {}
        self._ev_charge_refused_per_charger: Dict[str, bool] = {}
        # Solar stability layer (v1.7.1-beta.14): per-charger guard state.
        # last_set_amps_ts is the wall-clock of the most recent ``_set_current``
        # call so the time-debounce in ``ev_control.py`` knows when it's been
        # long enough to issue another one. budget_history is the rolling-median
        # window over recent budget_w samples so a single-cycle Huawei modbus
        # flicker (e.g. 8000 / 0 / 8000 W) does not propagate into a current
        # change. Mutated in place inside the per-charger loop.
        self._ev_last_set_amps_ts_per_charger: Dict[str, Optional[float]] = {}
        self._ev_budget_history_per_charger: Dict[str, list] = {}
        self._daily_ev_per_charger: Dict[str, float] = {}  # Per-charger daily energy (#193)
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

        # Phase 0: Surplus controller (always-on) & forecast reader
        regulation_offset = config.get("regulation_offset", 50)
        self._surplus_controller = SurplusController(hass, regulation_offset=regulation_offset)
        # (#559 Phase 0) debounced surplus availability signal
        self._surplus_availability = SurplusAvailability()
        self._surplus_controller.max_export_w = config.get("max_export_power", 0)  # 0 = no limit
        self._forecast_reader = ForecastReader(
            hass,
            custom_entities=None,  # Was config.get("forecast_entities") — never set via UI
        )
        self._forecast_tracker = ForecastTracker()
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

        # Phase 7: Utility signal monitor
        self._utility_monitor = UtilitySignalMonitor(
            hass,
            signal_entity_id=config.get("utility_signal_entity"),
            solar_loads_exempt=config.get("utility_solar_exempt", True),
        )

        # Phase 8: Consumption/solar predictor (#3)
        self._predictor = ConsumptionPredictor()

        # Phase 9: Battery charge scheduler (#6)
        from .battery_charge_adapter import create_charge_adapter
        from .battery_charge_scheduler import BatteryChargeScheduler, SchedulerConfig
        self._battery_scheduler_config = SchedulerConfig.from_config(config)
        self._battery_charge_adapter = create_charge_adapter(hass, config)
        self._battery_charge_scheduler = BatteryChargeScheduler(
            hass, self._battery_charge_adapter, self._battery_scheduler_config,
        )

        # EV Intelligence: taper detection, virtual SOC, charge skip (#106)
        self._ev_taper_detector = EVTaperDetector(config)  # Primary charger
        self._ev_taper_detectors: Dict[str, EVTaperDetector] = {}  # Per-charger (#112)

        # Calculation integrity checker (runs every cycle)
        self._health_check = HealthCheck()

        # Hourly activity tracker for schedule card (#63)
        self._today_surplus_hours: list = [False] * 24
        self._today_ev_hours: list = [False] * 24
        # Initialize to today so restarts don't re-apply daily decay
        self._tracker_date = dt_util.now().date()

        # Per-cycle caches (initialized here, populated in _async_update_data)
        self._cycle_forecast = None
        self._cycle_vehicle_soc: Optional[float] = None
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

        # Per-charger surplus budget for the active iteration.
        # ``None`` outside any per-charger iteration; set by
        # ``PerChargerContext.__enter__`` from the per-charger
        # distribution map and cleared on ``__exit__``.
        #
        # Loadbearing: ``PerChargerContext.__enter__`` snapshots this
        # field into ``_saved`` before pushing this charger's value —
        # if it's missing on the coordinator the very first cycle
        # raises ``AttributeError`` and the integration stops updating
        # (HA-TEST 2026-05-31 PROD repro: shipped v1.6.7 → v1.6.14
        # always crashed multi-charger first cycle; single-charger
        # never entered this code path and so didn't surface the bug).
        self._current_charger_budget: Optional[float] = None

        # EV stall detection for self-healing
        self._ev_stalled_since: Optional[float] = None
        # False-stall guard: consecutive failed re-enables + "car full" latch (#243)
        self._ev_reenable_attempts: int = 0
        self._ev_charge_refused: bool = False
        # Highest commanded amps across all chargers in the most recent
        # decide() cycle. Gates the fleet-level "0W means full" stall
        # path so it can't fire when SEM itself decided not to charge
        # (e.g. solar_only with surplus below the 3-phase 6 A floor —
        # the stall detector would otherwise falsely anchor SOC at 100 %).
        self._last_commanded_amps_fleet: int = 0

        # Session cost tracking (primary charger + per-charger dict)
        self._session_data = SessionData()
        self._session_data_per_charger: Dict[str, SessionData] = {}
        self._last_ev_connected = False
        self._last_ev_connected_per_charger: Dict[str, bool] = {}

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
        self._battery_protection_active: bool = False

        # Observer mode: read-only monitoring, no hardware control
        self._observer_mode = config.get("observer_mode", False)

        # Tracking flags
        self._initial_update_done = False
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
        from ..consts.ev_charge_modes import effective_charge_mode_for
        return effective_charge_mode_for(
            getattr(self, "hass", None),
            getattr(self, "config", {}) or {},
            charger_cfg,
        )

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
        """Does this charger's mode permit night/grid charging at all?"""
        from ..consts.ev_charge_modes import MODE_NIGHT_ALLOWED
        return self._effective_charge_mode_for(charger_cfg) in MODE_NIGHT_ALLOWED

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
        """
        energy_in = power.solar_power + power.grid_import_power + power.battery_discharge_power
        # FLEET-READ: energy balance — needs fleet total EV draw because
        # home_consumption is computed from the whole-house energy in/out.
        energy_out = power.ev_power + power.grid_export_power + power.battery_charge_power
        raw_balance = energy_in - energy_out
        if raw_balance < -500:
            self._negative_balance_count = getattr(self, '_negative_balance_count', 0) + 1
            if self._negative_balance_count >= 18:  # ~3 min sustained negative
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

        # EV energy reconciliation disabled — keba_p30_charging_daily resets at
        # midnight but daily_ev resets at sunrise, causing misalignment after sunrise
        # where reconciliation imports the full midnight-based counter into the fresh
        # sunrise counter, making SEM think the target is already reached.
        # SEM's own power integration (10s cycles) is reliable enough.

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

    def _collect_trace(self, sem_data, power, charging_context) -> None:
        # ``charging_context`` reserved for a future management-layer capture.
        try:
            self._trace.begin(wall_iso=dt_util.now().isoformat())
            trace = self._trace.current()
            self._trace_ev(trace, sem_data, power)
            self._trace_battery(trace, sem_data, power)
            self._trace_loads(trace, sem_data)
            self._trace_heat_pump(trace, sem_data)
        except Exception as e:  # pragma: no cover - defensive
            _LOGGER.debug("trace capture failed (non-fatal): %s", e)
        finally:
            # commit even if a capture raised — the partial trace + its
            # mismatch streak still count (H1). commit() no-ops if no begin.
            self._trace.commit()

    def _trace_ev(self, trace, sem_data, power) -> None:
        st = trace.subsystem("ev")
        soc = round(float(getattr(power, "battery_soc", 0.0) or 0.0), 1)
        connected = bool(getattr(power, "ev_connected", False))
        try:
            night = bool(self.time_manager.is_night_mode())
        except Exception:
            night = None
        st.management = LayerRecord(
            LayerStatus.OK, "policy inputs",
            {"soc": soc, "connected": connected, "night": night},
        )

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
        match = None
        if amps > 0 and connected:
            # real phases/voltage (M2 — a 1φ charger's nominal is far lower;
            # a hardcoded 3φ threshold false-mismatches every 1-phase install).
            phases = int(self.config.get("ev_phases", 3) or 3)
            voltage = int(self.config.get("ev_voltage", 230) or 230)
            commanded_w = amps * phases * voltage
            match = observed > commanded_w * 0.3
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
        st.process = LayerRecord(LayerStatus.OK, reason, {"soc": soc})
        st.integration = LayerRecord(
            LayerStatus.OK, "",
            {"charge_w": charge_w, "discharge_w": discharge_w, "match": None},
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
        st.process = LayerRecord(
            p_status, f"{active}/{total_dev} active",
            {"surplus_w": total_w, "distributable_w": dist_w, "allocated_w": alloc_w},
        )
        obs = "observer mode — not commanding" if getattr(
            self, "_observer_mode", False) else f"{active} device(s) on"
        st.integration = LayerRecord(
            LayerStatus.OK, obs, {"active": active, "allocated_w": alloc_w, "match": None},
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
        obs = "observer mode — not commanding" if getattr(
            self, "_observer_mode", False) else f"SG-Ready state {sg}"
        st.integration = LayerRecord(
            LayerStatus.OK, obs, {"sg_ready_state": sg, "match": None},
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

            # Restore device runtimes from storage
            self._restore_device_runtimes()

            # Restore EV session state (survives restarts)
            self._restore_ev_session_state()

            # Restore EV intelligence state (#106)
            ev_intel_state = self._storage.get_ev_intelligence_state()
            self._ev_taper_detector.restore_state(ev_intel_state)

            # Restore sign-detection locks (#476 item 5) — without this
            # every restart re-learned grid/battery signs from possibly
            # ambiguous low-power samples and could lock the wrong sign
            # until the next reload.
            self._sensor_reader.restore_sign_state(
                self._storage.get_sign_state()
            )

            # Restore the legionella timestamp (#508 I2). With the cycle
            # now driven every coordinator tick (#508 C1), a None
            # timestamp reads as "overdue" and would force a disinfection
            # run on every restart. Restore the persisted time; on a
            # fresh install (no stored time) seed to NOW so the first
            # cycle is ~interval_hours away, not immediate.
            hw_dev = self._surplus_controller._devices.get("hot_water") \
                if hasattr(self, "_surplus_controller") else None
            if hw_dev is not None and hasattr(hw_dev, "record_legionella_cycle"):
                stored_leg = self._storage.get_legionella_time()
                if stored_leg:
                    try:
                        hw_dev.record_legionella_cycle(
                            dt_util.parse_datetime(stored_leg)
                        )
                    except (ValueError, TypeError):
                        hw_dev.record_legionella_cycle(dt_util.now())
                else:
                    hw_dev.record_legionella_cycle(dt_util.now())

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
            await self._restore_battery_discharge_limit_on_startup()

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

        try:
            # Per-cycle caches — avoid redundant lookups within one 10s cycle (#52)
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

            # Step 4.5: Update session tracking (before charging decisions)
            # Multi-charger (#112): track sessions for each charger
            if self._ev_devices:
                # Collect per-charger power to proportionally attribute flows (#15)
                charger_powers: Dict[str, float] = {}
                for cid, ev_dev in self._ev_devices.items():
                    cp = 0.0
                    if ev_dev.power_entity_id:
                        pstate = self.hass.states.get(ev_dev.power_entity_id)
                        if pstate and pstate.state not in ("unknown", "unavailable"):
                            try:
                                cp = float(pstate.state)
                                unit = pstate.attributes.get("unit_of_measurement", "W")
                                if unit == "kW":
                                    cp *= 1000
                            except (ValueError, TypeError):
                                _LOGGER.debug(
                                    "Charger %s power not numeric: %r (#259)",
                                    cid, getattr(pstate, "state", None),
                                )
                    charger_powers[cid] = cp
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
                    pc_conn_sensor = charger_cfg.get("ev_connected_sensor")
                    pc_chrg_sensor = charger_cfg.get("ev_charging_sensor")
                    if pc_conn_sensor:
                        pc_state = self.hass.states.get(pc_conn_sensor)
                        if pc_state and pc_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                            power.ev_connected = pc_state.state == "on"
                    else:
                        # #351 M7 — without a per-charger plug sensor the
                        # session-end check (which reads ``power.ev_connected``)
                        # would otherwise see the fleet-OR and never fire on
                        # THIS charger's unplug while another car remains
                        # connected. Fall back to ``ev_connected_per_charger``
                        # if populated (the per-charger field on PowerReadings).
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
                    self._update_session_tracking(power, charger_flows)
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
            charging_context = self._build_charging_context(power, energy)
            charging_state = self._state_machine.update_state(charging_context)

            # Step 7.5a: Unified EV control via CurrentControlDevice
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

            if self._ev_devices and not self._observer_mode:
                # Multi-charger (#112): distribute budget + night target
                ev_budget_per_charger = {}
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
                    ev_chargers_cfg = self.config.get("ev_chargers", [])
                    charger_cfg_by_id = {c.get("id"): c for c in ev_chargers_cfg}

                    for cid in self._ev_devices:
                        cfg = charger_cfg_by_id.get(cid, {})
                        ttype = (cfg.get("ev_target_type") or cfg.get("ev_target_mode")
                                 or self.config.get("ev_target_type", "kwh"))
                        if ttype == "soc":
                            # SOC mode: kWh to reach the PER-CHARGER SOC floor (#245
                            # propagation fix) — not the kWh daily_ev_target.
                            per_soc = self._resolve_charger_soc(cid, cfg)
                            self._night_target_per_charger_map[cid] = (
                                self._calculate_remaining_need(energy, per_soc, cfg, bound="min")
                            )
                        else:
                            # kWh mode: per-charger daily target − this charger's delivered energy
                            target = cfg.get("daily_ev_target")
                            if target is None:
                                target = self.config.get("daily_ev_target", 10)
                                # Surface the inheritance once per charger (#259): a charger
                                # with no own target silently adopts the global floor (the
                                # #256 class). Behaviour change deferred to #255.
                                if cid not in self._night_global_fallback_logged:
                                    _LOGGER.info(
                                        "Charger %s has no per-charger night target; "
                                        "inheriting global %.1f kWh", cid, target,
                                    )
                                    self._night_global_fallback_logged.add(cid)
                            daily = self._daily_ev_per_charger.get(cid, 0.0)
                            # Single charger: the per-charger integrator is
                            # REBUILT FROM POWER each restart and under-reports
                            # after a restart, while the global ``daily_ev`` is
                            # persisted — the same quantity, and exactly what the
                            # dashboard "Today" shows (see _per_charger_daily_report).
                            # Use the persisted global so the night target's
                            # "delivered" matches the displayed Today figure;
                            # otherwise repeated restarts make the planner think
                            # the target isn't reached and it keeps charging past
                            # it (#536). Multi-charger keeps its own persisted
                            # per-charger accumulator.
                            chargers = self.config.get("ev_chargers") or []
                            if len(chargers) == 1:
                                daily = float(getattr(energy, "daily_ev", 0.0) or 0.0)
                            self._night_target_per_charger_map[cid] = max(0, target - daily)

                    # Backward compat: set the old scalar for single-value reads
                    self._night_target_per_charger = None

                # Solar budget: distribute by priority. Use the canonical
                # EVBudget computed in _build_charging_context (#282 Phase B.5).
                # Before this, multi-charger setups went through
                # _calculate_solar_ev_budget here, which has the legacy
                # ev_power + grid_export base — exactly the disagreement
                # mode Phase B eliminated for single-charger but left in
                # place for multi-charger distribution. Reported by @RienduPre
                # in #284 (Growatt + Wallbox Pulsar, 2-charger). The
                # distribution math (priority-weighted split across
                # chargers) is unchanged; we only swap the TOTAL the
                # distributor sees.
                if num_chargers >= 1 and charging_state in (
                    ChargingState.SOLAR_CHARGING_ACTIVE,
                    ChargingState.SOLAR_SUPER_CHARGING,
                    ChargingState.SOLAR_CHARGING_ALLOWED,
                    ChargingState.SOLAR_MIN_PV,
                ):
                    cycle_budget = getattr(self, "_cycle_ev_budget", None)
                    if cycle_budget is None:
                        # Phase D.2 cleanup (#282). ``_cycle_ev_budget`` is set
                        # unconditionally by ``_build_charging_context`` every
                        # cycle, so this branch only fires on a coordinator
                        # init bug. Fail-safe: log + 0 W = no distribution.
                        _LOGGER.error(
                            "Canonical EV budget not set in multi-charger "
                            "distribution — coordinator init bug. Distributing "
                            "0 W to fail safe. Investigate _build_charging_context."
                        )
                        total_budget = 0.0
                    else:
                        total_budget = cycle_budget.net_w
                    # #351 M5 — chargers in ``off`` mode must NOT receive
                    # an allocation. The actuator's #346 guard already
                    # refuses to actuate them, but the dashboard reads
                    # the distribution output directly and would otherwise
                    # show ``sem_charger_<id>_allocated_w > 0``.
                    excluded_cids = {
                        c["id"] for c in (self.config.get("ev_chargers") or [])
                        if isinstance(c, dict) and "id" in c
                        and self._effective_charge_mode_for(c) == "off"
                    }
                    ev_budget_per_charger = self._surplus_controller.distribute_ev_budget(
                        total_budget, self._ev_devices,
                        excluded_charger_ids=excluded_cids,
                    )

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
                        self, cid, ev_dev, ev_budget_per_charger,
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
                        # ``_cycle_vehicle_soc`` is one of the swap fields
                        # PerChargerContext restores in ``__exit__``.
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

                        # Per-charger off-mode override (v1.6.3 hotfix follow-up).
                        # The global ``charging_state`` is derived from the primary
                        # charger only — the multi-charger loop needs to correct it
                        # per charger so an OFF primary doesn't bleed its terminate
                        # into the other chargers. See the helper for details.
                        per_mode = self._effective_charge_mode_for(charger_cfg)
                        # Diagnostic check — only fire when an explicit mode
                        # was set AND it disagrees with what effective_charge_
                        # mode_for resolved. ``raw_mode = None`` is the
                        # legitimate "user hasn't picked a mode yet → use
                        # DEFAULT_EV_CHARGE_MODE" fallback and is not a bug.
                        _raw_mode = charger_cfg.get("charge_mode") if isinstance(charger_cfg, dict) else None
                        if _raw_mode is not None and _raw_mode != per_mode:
                            _LOGGER.warning(
                                "per-charger mode mismatch: cid=%s raw_cfg=%r per_mode=%r",
                                cid, _raw_mode, per_mode,
                            )
                        effective_state = self._apply_per_charger_off_override(
                            charging_state, per_mode
                        )
                        if charging_state in (
                            ChargingState.NIGHT_CHARGING_ACTIVE,
                            ChargingState.TARIFF_WAITING_FOR_CHEAP,
                        ):
                            pc_target = charging_context.night_target_kwh
                            if pc_target <= 0.1:
                                effective_state = ChargingState.NIGHT_TARGET_REACHED
                            else:
                                plan = self._compute_night_plan(charger_cfg, pc_target, energy)
                                self._night_plan_per_charger[cid] = plan
                                charging_context.night_deadline_amps = plan.deadline_amps
                                charging_context.night_deadline_active = plan.deadline_active
                                charging_context.night_tariff_wait = plan.should_wait_for_cheap
                                charging_context.night_deadline_reachable = plan.reachable
                                effective_state = (
                                    ChargingState.TARIFF_WAITING_FOR_CHEAP
                                    if plan.should_wait_for_cheap
                                    else ChargingState.NIGHT_CHARGING_ACTIVE
                                )
                                await self._maybe_warn_unreachable_deadline(cid, charger_cfg, plan)

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
                            charger_cfg=charger_cfg,
                            mode=per_mode,
                            daily_ev_kwh=self._daily_ev_per_charger.get(cid, 0.0),
                            target_kwh=decide_target_kwh,
                            deadline_amps=int(charging_context.night_deadline_amps or 0),
                            tariff_wait=bool(charging_context.night_tariff_wait),
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
                        )
                        # Track the highest commanded current across the
                        # fleet so the stall-detection path (line ~3725)
                        # can distinguish "SEM idle, EV at 0W is correct"
                        # from "SEM commanding, EV refused → really full".
                        if decision.commanded_amps > self._last_commanded_amps_fleet:
                            self._last_commanded_amps_fleet = decision.commanded_amps
                        _LOGGER.debug(
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
                            await actuate(decision, adapter, view.power, reconciler=reconciler)
                            # Add this charger's just-committed draw to the shared night
                            # peak budget so lower-priority chargers size against the
                            # remaining headroom (#274/H1). Estimate from the setpoint
                            # (the commitment), not the lagging measured power.
                            try:
                                self._night_committed_w += max(0.0, (
                                    ev_dev._current_setpoint * ev_dev.phases * ev_dev.voltage
                                ))
                            except (AttributeError, TypeError):
                                pass
                            # Step 6: thread solar commitment through to the next
                            # per-charger view so lower-priority chargers see only
                            # the surplus this one didn't take.
                            from .charger_types import ChargerIntent as _CI2
                            if decision.intent is _CI2.CHARGE_AT_AMPS:
                                committed_solar_w = min(
                                    decision.budget_w,
                                    decision.commanded_amps * adapter.phases * adapter.voltage,
                                )
                                self._solar_committed_w_per_cycle += committed_solar_w
                            elif decision.intent is _CI2.CHARGE_MAX:
                                self._solar_committed_w_per_cycle += (
                                    adapter.max_current_a * adapter.phases * adapter.voltage
                                )
                        except (HomeAssistantError, ServiceValidationError) as e:
                            _LOGGER.error("EV control service failed for %s: %s", cid, e)
                        except ValueError as e:
                            _LOGGER.warning("EV control invalid value for %s: %s", cid, e)
                self._save_ev_session_state()
            elif self._ev_device and not self._observer_mode:
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
                    charger_cfg={},
                    mode=per_mode,
                    daily_ev_kwh=getattr(energy, "daily_ev", 0.0),
                    target_kwh=getattr(charging_context, "night_target_kwh", None),
                    deadline_amps=int(getattr(charging_context, "night_deadline_amps", 0) or 0),
                    tariff_wait=bool(getattr(charging_context, "night_tariff_wait", False)),
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
                )
                try:
                    await actuate(decision, adapter, view.power, reconciler=reconciler)
                    self._save_ev_session_state()
                except (HomeAssistantError, ServiceValidationError) as e:
                    _LOGGER.error("EV control service failed: %s", e)
                except ValueError as e:
                    _LOGGER.warning("EV control invalid value: %s", e)

            # Step 7.5c+d (unified): Battery control via decide_battery + actuate_battery
            #
            # Replaces the legacy split (7.5c BatteryProtectionMixin +
            # 7.5d BatteryChargeScheduler.update) with one pure pipeline
            # mirroring the EV-side rebuild.
            discharge_limit = None
            if not self._observer_mode:
                try:
                    await self._run_battery_pipeline(power, energy, charging_state)
                    # Surface the most recent LIMIT_DISCHARGE for the
                    # discharge-limit sensor. #375: now reads across
                    # the per-battery adapter dict — picks the
                    # tightest active limit if multiple batteries are
                    # currently in LIMIT_DISCHARGE (the protection
                    # gate fires fleet-wide on EV night charging, so
                    # in practice all adapters report the same value
                    # — min() is just defensive).
                    adapters = getattr(self, "_battery_adapters", None) or {}
                    if adapters:
                        from .charger_types import BatteryIntent as _BI
                        active_limits = [
                            a._last_discharge_limit_w for a in adapters.values()
                            if a.last_intent is _BI.LIMIT_DISCHARGE
                            and a._last_discharge_limit_w is not None
                        ]
                        if active_limits:
                            discharge_limit = min(active_limits)
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
            if self._energy_dashboard_config and (
                not self._energy_calculator._yearly_seeded
                or not self._energy_calculator._yearly_cost_seeded
            ):
                try:
                    await self._energy_calculator.seed_yearly_from_statistics(
                        self.hass, self._energy_dashboard_config
                    )
                except Exception as e:
                    _LOGGER.warning("Yearly seeding from statistics failed (will retry): %s", e)

            # Step 9c: Calculate battery health metrics
            battery_capacity = self.battery_capacity_kwh
            if battery_capacity > 0:
                lifetime_charge = self._energy_calculator._get_lifetime("battery_charge")
                lifetime_discharge = self._energy_calculator._get_lifetime("battery_discharge")
                total_throughput = (lifetime_charge + lifetime_discharge) / 2
                power.battery_cycles_estimated = round(total_throughput / battery_capacity, 1)
                # Estimate health: assume 0.02% degradation per cycle (typical Li-ion)
                degradation = min(30, power.battery_cycles_estimated * 0.02)
                power.battery_health_score = round(100 - degradation, 1)

            # Steps 10–10.5: Analytics phases (extracted for readability, #29)
            forecast_data, tracker_data, tariff_data, surplus_data, \
                pv_data, assistant_data, utility_data, heat_pump_data, \
                hot_water_data = \
                await self._update_analytics_phases(
                    power, energy, energy_flows, performance,
                    charging_context.available_power,
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
                surplus_control=surplus_data,
                forecast=forecast_data,
                tariff=tariff_data,
                heat_pump=heat_pump_data,
                hot_water=hot_water_data,
                pv_analytics=pv_data,
                energy_assistant=assistant_data,
                utility_signal=utility_data,
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
                autarky=performance.autarky_rate,
                self_consumption=performance.self_consumption_rate,
                costs=costs,
                home_hold_active=getattr(self, "_home_hold_active", False),
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

            # Add per-charger data (#131): power + session
            per_charger_soc: Dict[str, float] = {}
            for cid, ev_dev in self._ev_devices.items():
                charger_power = 0.0
                if ev_dev.power_entity_id:
                    pstate = self.hass.states.get(ev_dev.power_entity_id)
                    if pstate and pstate.state not in ("unknown", "unavailable"):
                        try:
                            charger_power = float(pstate.state)
                            unit = pstate.attributes.get("unit_of_measurement", "W")
                            if unit.lower() == "kw":
                                charger_power *= 1000
                        except (ValueError, TypeError):
                            pass
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
                    _state = self.hass.states.get(_ext_sensor_id)
                    if _state and _state.state not in ("unavailable", "unknown", None):
                        try:
                            _ext_value = float(_state.state)
                            # Auto-convert Wh → kWh if the source reports in Wh.
                            _unit = _state.attributes.get("unit_of_measurement", "").lower()
                            if _unit == "wh":
                                _ext_value = _ext_value / 1000.0
                        except (ValueError, TypeError):
                            _ext_value = 0.0
                result[f"charger_{cid}_session_energy_external"] = round(_ext_value, 2)
                # Per-charger taper detection (#138)
                taper_det = self._ev_taper_detectors.get(cid)
                if taper_det:
                    result[f"charger_{cid}_taper_trend"] = taper_det._declining_phase and "declining" or "stable"
                    result[f"charger_{cid}_taper_ratio"] = round(
                        (charger_power / taper_det._session_peak_w * 100) if taper_det._session_peak_w > 0 else 0, 1
                    )
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
                total = lifetime.get("total_energy_kwh", 0)
                solar = lifetime.get("total_solar_kwh", 0)
                result["lifetime_ev_solar_share"] = round(solar / total * 100, 1) if total > 0 else 0

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
                    try:
                        result["ev_remaining_range"] = round(float(_rs.state))
                    except (ValueError, TypeError):
                        pass
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
                    result["ev_deadline_hours"] = _night_plan.hours_to_deadline
                if _night_plan.next_cheap_start is not None:
                    result["ev_next_cheap_window"] = _night_plan.next_cheap_start.isoformat()

            # Diagnostics summary for dashboard System tab
            result["diag_version"] = self._get_version()
            _disc = getattr(self._sensor_reader, "_split_grid_discovery", None) or {}
            if self.config.get("grid_import_power_entity") or self.config.get("grid_export_power_entity"):
                result["diag_grid_mode"] = "manual"
                # #461 follow-up: observe-only audit verdict — True when the
                # manual import/export assignment has contradicted the
                # Energy Dashboard counters for 5+ cycles (swapped fields).
                result["diag_grid_manual_mismatch"] = bool(
                    getattr(self._sensor_reader, "_manual_grid_mismatch", False)
                )
            elif _disc.get("import"):
                result["diag_grid_mode"] = "split" if _disc.get("confidence") == "same-device" else "split-lowconf"
            else:
                result["diag_grid_mode"] = "combined"
            result["diag_grid_sign"] = "negated" if self._sensor_reader._grid_sign_inverted else "normal"
            result["diag_charger_count"] = len(self._ev_devices)
            result["diag_charger_control"] = "number" if any(
                getattr(d, 'current_entity_id', None) for d in self._ev_devices.values()
            ) else "service" if self._ev_devices else "none"
            result["diag_battery_capacity"] = self.config.get("battery_capacity_kwh", 0)
            result["diag_update_interval"] = self.update_interval.total_seconds()
            result["diag_observer_mode"] = self._observer_mode
            # diag_ev_assist_headroom removed — #545 instrumentation, fixed+closed.
            unavail_count = sum(1 for eid in self._sensor_reader._sensor_unavailable)
            result["diag_sensors_unavailable"] = unavail_count
            result["diag_health_violations"] = self._health_check.total_violations

            # Energy Dashboard config summary — surfaces whether power AND energy are
            # configured per source, and where power came from. Pasted via the System
            # card's "Copy diagnostics" so "all values 0" reports (#250) are self-
            # diagnosing: all pwr=none / energy=MISSING ⇒ the dashboard isn't wired up.
            result["diag_ed_config"] = self._build_ed_config_summary()

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
                            if _cid and _cid in self._daily_ev_per_charger:
                                _daily = self._daily_ev_per_charger[_cid]
                            else:
                                _daily = getattr(energy, "daily_ev", 0.0) or 0.0
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
                                self._daily_ev_per_charger.get(_cid)
                                if _cid and _cid in self._daily_ev_per_charger
                                else (getattr(energy, "daily_ev", 0.0) or 0.0)
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

            # Hourly activity tracker for schedule card (#63)
            now_time = dt_util.now()
            today_date = now_time.date()
            if self._tracker_date != today_date:
                self._today_surplus_hours = [False] * 24
                self._today_ev_hours = [False] * 24
                # Day rollover: decay virtual SOC when car is unplugged (#106)
                if (
                    not power.ev_connected
                    and self._ev_taper_detector.last_full_timestamp
                ):
                    predicted = self._predictor.predict_ev_consumption_tomorrow(now_time)
                    fallback = self.config.get("daily_ev_target", 10)
                    outdoor_temp = self._read_outdoor_temperature()
                    temp_factor = EVTaperDetector.temperature_correction_factor(outdoor_temp)
                    self._ev_taper_detector.apply_daily_decay(predicted, fallback, temp_factor)
                self._tracker_date = today_date
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
            if bcs.decision.schedule:
                result["battery_scheduler_schedule"] = bcs.decision.schedule.as_dict()
            else:
                result["battery_scheduler_schedule"] = {}

            # Predictor sensors (#3)
            result["predictor_training_status"] = self._predictor.training_status
            result["predictor_model_accuracy"] = self._predictor.model_accuracy_pct
            now = dt_util.now()
            # (#544) predicted_consumption_next_hour / _today_kwh /
            # predicted_solar_next_hour removed — published, never charted/read.
            surplus_window = self._predictor.predict_surplus_window(now)
            if surplus_window:
                result["predicted_surplus_window"] = surplus_window

            return result

        except Exception as e:
            _LOGGER.error("Error updating SEM data: %s", e, exc_info=True)
            raise UpdateFailed(f"Update failed: {e}") from e

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
        """Run analytics phases: forecast, tariff, surplus, PV, assistant, utility (#29).

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
            self._forecast_tracker.update(
                forecast_data.forecast_today_kwh, energy.daily_solar, weather_condition,
            )
            tracker_data = self._forecast_tracker.get_data()
            # (#544) forecast_corrected_tomorrow removed — dead sensor.
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Forecast tracker update failed: %s", e)

        # Apply real-time dampening to forecast remaining and surplus
        try:
            if forecast_data.forecast_available:
                dampening = self._forecast_tracker.dampening_factor
                forecast_data.forecast_dampening_factor = dampening
                dampened_remaining = round(
                    forecast_data.forecast_remaining_today_kwh * dampening, 2
                )
                forecast_data.forecast_remaining_today_kwh = dampened_remaining
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

        # Surplus controller (Phase 0.2)
        surplus_data = SurplusControlData()
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
            _batt_decisions = getattr(self, "_last_battery_decisions", None) or {}
            battery_commanded = any(
                d.get("intent") in ("force_charge", "force_discharge")
                for d in _batt_decisions.values()
            )
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
            true_surplus_w = (
                float(getattr(power, "grid_export_power", 0.0) or 0.0)
                + self._surplus_controller.active_surplus_draw_w()
            )
            battery_priority = None
            _reg = getattr(self, "_device_registry", None)
            if _reg is not None:
                try:
                    # (#576) only surface the battery priority row on installs
                    # that actually have a battery. LATCH it: once we've seen a
                    # real battery reading it stays shown — a transient SOC
                    # "unavailable" must NOT flicker the row out of the list.
                    if getattr(power, "battery_soc", None) is not None:
                        _reg._has_battery = True
                    battery_priority = _reg.battery_surplus_priority()
                except Exception:  # pragma: no cover - never break the cycle
                    battery_priority = None
            # #508 W2 — hand the load-manager's peak posture to the surplus
            # controller so it stops adding discretionary load (and backs
            # its own devices off) when grid import is at risk, instead of
            # re-activating next cycle whatever the load manager just shed.
            peak_state = (
                self._load_manager.get_state() if self._load_manager else None
            )
            allocation = await self._surplus_controller.update(
                true_surplus_w,
                price_level=tariff_data.tariff_price_level,
                peak_state=peak_state,
                reclaim_w=reclaim_w,
                battery_priority=battery_priority,
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

        # Device runtimes
        try:
            meter_day = dt_util.now().date()
            for device in self._surplus_controller._devices.values():
                device.update_daily_runtime(meter_day)
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

        # Utility signal (Phase 7)
        utility_data = UtilitySignalSensorData()
        try:
            signal = self._utility_monitor.update(solar_power_w=power.solar_power)
            utility_data.utility_signal_active = signal.signal_active
            utility_data.utility_signal_source = signal.signal_source
            utility_data.utility_signal_count_today = signal.signal_count_today
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Utility signal update failed: %s", e)

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
            pv_data, assistant_data, utility_data, heat_pump_data,
            hot_water_data,
        )

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

    async def _run_battery_pipeline(self, power, energy, charging_state) -> None:
        """Per-cycle battery control via decide_battery + actuate_battery.

        Replaces the legacy 7.5c + 7.5d hooks
        (``_apply_battery_discharge_protection`` from
        BatteryProtectionMixin + ``_execute_battery_charge_scheduler``)
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
            ArbitrageSignals, BatteryIntent, BatteryRuntime, BatteryView,
            FleetContext,
        )
        from .decide_battery import decide_battery

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
                await self._maybe_run_scheduler_evaluation(power)
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
        # Evaluate arbitrage ONLY when globally enabled. In v1.7.3 the global
        # toggle is forced off (#533) so this whole block is dormant — automatic
        # battery→grid arbitrage is deactivated for the stable release.
        #
        # The per-battery ``allow_arbitrage`` opt-in (which used to run the
        # economic check even with the global toggle off) is intentionally NOT
        # honoured here for v1.7.3: it's removed from the selector and a stale
        # ``allow_arbitrage`` config goes dormant (behaves like ``auto`` — no
        # selling) rather than quietly selling to grid. Restored in v1.7.4.
        _any_allow_arb = False  # v1.7.3: per-battery arbitrage opt-in disabled (#533)
        # Market signals are computed ONCE here (#533) and carried on the
        # FleetContext below — single source of truth, no ad-hoc tariff/power
        # reads in the decision. ``None`` unless arbitrage is being evaluated
        # (the whole block is dormant while the toggle + _any_allow_arb are off).
        arb_signals = None
        if (self._battery_scheduler_config.arbitrage_enabled or _any_allow_arb):
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
                    enabled_override=(
                        self._battery_scheduler_config.arbitrage_enabled or _any_allow_arb
                    ),
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

        # Shared fleet context — same for every battery this cycle.
        fleet = FleetContext(
            solar_w=float(getattr(power, "solar_power", 0.0) or 0.0),
            home_w=float(getattr(power, "home_consumption_power", 0.0) or 0.0),
            battery_soc=float(getattr(power, "battery_soc", 0.0) or 0.0),
            is_night=self.time_manager.is_night_mode(),
            # #531: split per-battery LIMIT_DISCHARGE across the real fleet.
            battery_count=max(1, len(getattr(power, "batteries", {}) or {})),
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
                _pbc = self._per_battery_config(batt_idx, _bat_count)
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
                config=self._per_battery_config(batt_idx, _bat_count),
                fleet=fleet,
                charging_state=getattr(charging_state, "value", str(charging_state)),
                ev_charging=bool(getattr(power, "ev_charging", False)),
                ev_connected=bool(getattr(power, "ev_connected", False)),
                home_consumption_w=float(
                    getattr(power, "home_consumption_power", 0.0) or 0.0
                ),
                scheduler_decision=scheduler_decision,
            )

            # 3. Decide
            decision = decide_battery(view)
            _LOGGER.debug(
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

            # 4. Actuate
            await actuate_battery(decision, adapter)

        # Reset scheduler when night ends — preserved from legacy
        if (scheduler.enabled
                and not self.time_manager.is_night_mode()
                and scheduler.state.value not in ("idle", "not_needed", "not_profitable")):
            scheduler.reset()

    async def _maybe_run_scheduler_evaluation(self, power) -> None:
        """Trigger the scheduler's ``evaluate()`` at the daily time.

        Pure port of the daily-evaluation branch in the legacy
        ``_execute_battery_charge_scheduler``. The scheduler's
        ``evaluate()`` is itself a pure function; we just gather its
        inputs the same way the legacy hook did.
        """
        scheduler = self._battery_charge_scheduler
        now = dt_util.now()

        if not scheduler.should_trigger_evaluation(now):
            # Check for re-plan trigger (price update / SOC drift / EV change)
            ev_connected = bool(getattr(power, "ev_connected", False))
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

        ev_kwh_needed = 0.0
        ev_max_power = 0.0
        if self._ev_devices:
            daily_target = self.config.get("daily_ev_target", 10)
            ev_today = self._energy_calculator._get_daily("ev_charging")
            ev_kwh_needed = max(0, daily_target - ev_today)
            first_charger = next(iter(self._ev_devices.values()), None)
            if first_charger and hasattr(first_charger, "max_power_w"):
                ev_max_power = first_charger.max_power_w
            else:
                ev_max_power = self.config.get("ev_max_power_w", 11000)

        tariff_provider = None
        if hasattr(self._tariff_provider, "find_cheapest_hours"):
            tariff_provider = self._tariff_provider

        scheduler.evaluate(
            current_soc=power.battery_soc,
            forecast_tomorrow_kwh=forecast_tomorrow,
            expected_consumption_kwh=expected_consumption,
            off_peak_rate=off_peak_rate,
            peak_rate=peak_rate,
            tariff_provider=tariff_provider,
            correction_factor=correction,
            ev_kwh_needed=ev_kwh_needed,
            ev_max_power_w=ev_max_power,
            forecast_available=forecast.available,
            forecast_age_hours=forecast_age,
            current_price=current_price,
        )

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
        }
        per_charger_states = getattr(self, "_effective_states_per_charger", None) or {}
        if per_charger_states:
            for cid, (eff_state, name) in per_charger_states.items():
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
            is_night = self.time_manager.is_night_mode()
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
                # est_soc kept for the "nearly full" notification gate
                # logic that survived #440 (informational only — does not
                # gate the charge command).
                est_soc = intel.get("estimated_soc") or 0

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

                # Per-charger night-allowed gate — modes ``off`` and
                # ``solar_only`` are not eligible for night charging, so
                # firing a "skipped night charge" notification on those
                # is just noise. Default to allow-night when no cfg
                # entry exists for this cid (legacy single-charger or
                # config-list-empty cases). #351 M11.
                cfg_for_cid = chargers_cfg_by_id.get(cid)
                mode_allows_night = (
                    self._mode_allows_night_charging(cfg_for_cid)
                    if cfg_for_cid is not None
                    else True
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

    async def _retry_ev_device_setup(self) -> None:
        """Retry EV device setup if KEBA wasn't available at startup."""
        from ..hardware_detection import discover_ev_charger_from_registry
        from ..devices.base import CurrentControlDevice

        ev_auto = discover_ev_charger_from_registry(self.hass)
        if not ev_auto or not ev_auto.get("ev_charger_service"):
            return

        _LOGGER.info("Late-discovered EV charger: %s", list(ev_auto.keys()))

        ev_device = CurrentControlDevice(
            hass=self.hass,
            device_id="ev_charger",
            name="EV Charger",
            priority=self.config.get("ev_surplus_priority", 3),
            min_current=6.0,
            max_current=float(self.config.get("max_charging_current", 32)),
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
        """
        cfg = charger_cfg or {}
        ttype = (cfg.get("ev_target_type") or cfg.get("ev_target_mode")
                 or self.config.get("ev_target_type") or "kwh")
        charging = charging_state in self.SOLAR_CHARGING_STATES
        from . import repair_issues as _ri
        if ttype == "soc" and real_soc is None and charging:
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
            # If its current value is unavailable (network blip etc.),
            # return the full capacity so SEM keeps charging — taper
            # detection will eventually stop it on car-full. Never use
            # estimated_soc.
            if vehicle_soc is None:
                return float(ev_capacity)
            soc_target = self._resolve_target(cfg, "ev_target_soc", bound, 80, 100)
            return max(0, (soc_target - vehicle_soc) / 100 * ev_capacity)

        # kWh branch — the default mode for installs without a SOC sensor.
        daily_target = self._resolve_target(cfg, "daily_ev_target", bound, 10, 100)
        # #351 H1 — for a per-charger call (``charger_cfg`` provided),
        # subtract THIS charger's daily energy, not the fleet total.
        # Pre-fix charger B's "target reached" check was polluted by
        # charger A's energy: ``daily_target - energy.daily_ev`` would
        # underreport B's remaining need (or fire target-reached
        # spuriously) the moment A drew any energy.
        cid = cfg.get("id") if cfg else None
        pc_daily = getattr(self, "_daily_ev_per_charger", None) or {}
        consumed = pc_daily.get(cid, energy.daily_ev) if cid else energy.daily_ev
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

        return FleetCycleState(
            power=power,
            config=self.config,
            is_night=self.time_manager.is_night_mode(),
            tariff_level=tariff_level,
            forecast_remaining_kwh=float(forecast_remaining),
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
        night_target = remaining_floor
        if self.time_manager.is_night_mode() and self._smart_night_charging_enabled():
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
            charger_cfg=_primary_cfg,
            mode=self._effective_charge_mode_for(_primary_cfg),
            daily_ev_kwh=self._daily_ev_per_charger.get(
                _primary_cfg.get("id") or "ev_charger", 0.0,
            ),
            target_kwh=remaining_floor,
            # Night plan flags (#246 deadline + #247 tariff_wait).
            # Computed above so the primary view's decide() sees the
            # same wait-for-cheap and deadline-floor info the
            # multi-charger loop downstream gets.
            tariff_wait=tariff_wait,
            deadline_amps=deadline_amps,
            night_deliverable_kwh=self._night_deliverable_kwh(_primary_cfg),
            # #548 — max-SOC ceiling; stop surplus charging at the car's max.
            soc_ceiling_reached=soc_limit_active,
        )
        _primary_decision = _decide(_primary_view)
        strategy = _primary_decision.intent.value
        reason = _primary_decision.reason

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
            override_max_w = self.config.get("ev_max_current", 16) * _phase_v

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

        _LOGGER.debug(
            "Charging strategy: %s — %s",
            strategy, reason,
        )

        # Night plan was computed earlier (before primary view's decide())
        # — variables ``night_target``, ``deadline_amps``,
        # ``deadline_active``, ``tariff_wait``, ``deadline_reachable``
        # are already populated and consumed below.

        return ChargingContext(
            ev_connected=power.ev_connected,
            ev_charging=power.ev_charging,
            battery_soc=power.battery_soc,
            battery_too_low=battery_too_low,
            battery_needs_priority=battery_needs_priority,
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
        self._ev_last_change_time = None

    def _save_ev_session_state(self) -> None:
        """Persist EV session state to storage."""
        if not self._storage:
            return

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
            })
        elif self._ev_device:
            ev = self._ev_device
            self._storage.set_ev_session_state(
                self._serialize_session_state(
                    ev._session_active, ev._current_setpoint, self._session_data,
                ),
            )

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
        if per_hw_entity:
            hw_state = self.hass.states.get(per_hw_entity)
            if hw_state and hw_state.state not in ("unknown", "unavailable"):
                try:
                    per_hw_total = float(hw_state.state)
                except (ValueError, TypeError):
                    pass
        detector.update_energy(per_increment, per_hw_total)

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

                # Read per-charger power from device's power entity
                charger_power = 0.0
                if ev_dev.power_entity_id:
                    pstate = self.hass.states.get(ev_dev.power_entity_id)
                    if pstate and pstate.state not in ("unknown", "unavailable"):
                        try:
                            charger_power = float(pstate.state)
                            # Auto-convert kW to W
                            unit = pstate.attributes.get("unit_of_measurement", "W")
                            if unit == "kW":
                                charger_power *= 1000
                        except (ValueError, TypeError):
                            pass

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
                    self._ev_taper_detectors[cid].update(
                        charger_power, charger_setpoint, charger_connected, now,
                    )

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

            # Primary charger's detector drives SOC/skip (sync with main detector)
            primary_id = next(iter(self._ev_devices))
            if primary_id in self._ev_taper_detectors:
                self._ev_taper_detector = self._ev_taper_detectors[primary_id]

        # Get current EV setpoint (0 if no EV device)
        ev_setpoint = 0.0
        if self._ev_device:
            ev_setpoint = getattr(self._ev_device, "_current_setpoint", 0.0)

        # Run taper detection (primary / single charger). Multi-charger
        # taper is handled per-charger by
        # ``_update_per_charger_detector_energy`` (v1.6.6 #318); this
        # call only runs when no per-charger detectors are configured.
        # FLEET-READ: legacy single-detector path.
        if power.ev_power > 0 or power.ev_connected:
            taper_data = self._ev_taper_detector.update(
                # FLEET-READ: single-detector input — see comment above.
                power.ev_power, ev_setpoint, power.ev_connected, now,
            )
        else:
            taper_data = EVTaperData()

        # Track energy since last full charge (hardware counter preferred)
        if hasattr(energy, "daily_ev"):
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
            }

        return result

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
    def _restore_device_runtimes(self) -> None:
        """Restore device runtimes from storage on startup."""
        if not self._storage:
            return
        runtimes = self._storage.get_device_runtimes()
        for device_id, data in runtimes.items():
            device = self._surplus_controller.get_device(device_id)
            if device:
                from datetime import date
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

    def _persist_device_runtimes(self) -> None:
        """Save device runtimes to storage."""
        if not self._storage:
            return
        for device in self._surplus_controller._devices.values():
            if device.daily_min_runtime_sec > 0 and device._daily_runtime_meter_day:
                self._storage.set_device_runtime(
                    device.device_id,
                    device._daily_runtime_accumulated_sec,
                    device._daily_runtime_meter_day.isoformat(),
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
                    hp.priority = max(1, min(10, int(cfg.get("heat_pump_priority", 4))))
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
                    hw.priority = max(1, min(10, int(cfg.get("hot_water_priority", 6))))
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
                    # Match the construction resolution (__init__._cfg): the
                    # legacy ``ev_load_priority`` alias is the fallback.
                    surplus_prio = int(_cfg_charger(
                        ccfg, "ev_surplus_priority",
                        _cfg_charger(ccfg, "ev_load_priority", dev.priority),
                    ))
                    dev.priority = max(1, min(10, surplus_prio))
                    dev.min_current = float(_cfg_charger(ccfg, "ev_min_current", 6))
                    dev.max_current = float(
                        _cfg_charger(ccfg, "max_charging_current", 32)
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
                # Shed priority lives in the load manager's device dict
                # (load_device_<id>), independent of surplus order (#470).
                if lm is not None and isinstance(
                    getattr(lm, "_devices", None), dict
                ):
                    ld = lm._devices.get(f"load_device_{cid}")
                    if isinstance(ld, dict):
                        try:
                            ld["priority"] = int(
                                _cfg_charger(ccfg, "ev_shed_priority", surplus_prio)
                            )
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
