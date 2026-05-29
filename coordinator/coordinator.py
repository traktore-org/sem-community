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
    ENTITY_SMART_NIGHT_CHARGING,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from ..utils.time_manager import TimeManager
from ..ha_energy_reader import read_energy_dashboard_config, EnergyDashboardConfig

from .types import (
    SEMData, PowerReadings, PowerFlows, SystemStatus, LoadManagementData,
    SurplusControlData, ForecastSensorData, TariffSensorData,
    HeatPumpSensorData, PVAnalyticsData, EnergyAssistantSensorData,
    UtilitySignalSensorData, SessionData, BatterySessionData,
)
from .health_check import HealthCheck
from .sensor_reader import SensorReader
from .energy_calculator import EnergyCalculator
from .flow_calculator import FlowCalculator
from .charging_control import ChargingStateMachine, ChargingContext
from .storage import SEMStorage
from .notifications import NotificationManager
from .surplus_controller import SurplusController
from .forecast_reader import ForecastReader
from .forecast_tracker import ForecastTracker
from .ev_control import EVControlMixin
from .battery_protection import BatteryProtectionMixin
from ..tariff import StaticTariffProvider, DynamicTariffProvider, PriceLevel
from ..tariff.calendar_provider import CalendarTariffProvider
from ..analytics.pv_performance import PVPerformanceAnalyzer
from ..analytics.consumption_predictor import ConsumptionPredictor
from .ev_taper_detector import EVTaperDetector
from ..analytics.energy_assistant import EnergyAssistant
from ..utility_signals import UtilitySignalMonitor

_LOGGER = logging.getLogger(__name__)


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
        # Per-charger state dicts for multi-charger (#112)
        self._ev_stalled_since_per_charger: Dict[str, Optional[float]] = {}
        self._ev_enable_surplus_per_charger: Dict[str, Optional[float]] = {}
        self._ev_charge_started_per_charger: Dict[str, Optional[float]] = {}
        self._ev_last_change_per_charger: Dict[str, Any] = {}
        # False-stall guard per charger (#243)
        self._ev_reenable_attempts_per_charger: Dict[str, int] = {}
        self._ev_charge_refused_per_charger: Dict[str, bool] = {}
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

        # Phase 0: Surplus controller (always-on) & forecast reader
        regulation_offset = config.get("regulation_offset", 50)
        self._surplus_controller = SurplusController(hass, regulation_offset=regulation_offset)
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
            )
        elif tariff_mode == "calendar":
            schedule = {}  # Was config.get("tariff_schedule", {}) — never set via UI
            self._tariff_provider = CalendarTariffProvider(
                hass,
                peak_rate=config.get("electricity_import_rate", 0.35),
                off_peak_rate=config.get("electricity_off_peak_rate") or config.get("electricity_nt_rate", 0.22),
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
                off_peak_rate=config.get("electricity_off_peak_rate") or config.get("electricity_nt_rate", 0.3387),
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
        # Shared night peak budget (#274/H1): watts committed to higher-priority
        # chargers so far this cycle. Reset before the per-charger loop; each
        # charger's peak-managed sizing subtracts it so the fleet stays under peak.
        self._night_committed_w = 0.0
        # Tariff wait↔charge hysteresis (#274/M4): {cid: (should_wait, ts)} of the
        # last effective decision, so price hovering at the cheap boundary doesn't
        # stop/start the charger every cycle.
        self._tariff_decision_per_charger = {}

        # EV stall detection for self-healing
        self._ev_stalled_since: Optional[float] = None
        # False-stall guard: consecutive failed re-enables + "car full" latch (#243)
        self._ev_reenable_attempts: int = 0
        self._ev_charge_refused: bool = False

        # Session cost tracking (primary charger + per-charger dict)
        self._session_data = SessionData()
        self._session_data_per_charger: Dict[str, SessionData] = {}
        self._last_ev_connected = False
        self._last_ev_connected_per_charger: Dict[str, bool] = {}

        # Battery session tracking
        self._battery_session = BatterySessionData()
        self._battery_session_idle_count = 0

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
            "ev_min_current", "ev_night_initial_current",
            "ev_kwh_per_100km", "ev_target_type",
            "ev_charging_mode", "ev_phases",
            "ev_target_time",  # #246 charge-by deadline
        ):
            if pc.get(key) is not None:
                self.config[key] = pc[key]

    def _smart_night_charging_enabled(self) -> bool:
        """True if smart (forecast-aware) night charging is on for any charger (#255).

        Per-charger is canonical; falls back to the global switch for legacy installs.
        (Also fixes the previously-malformed global entity reference — the feature was
        effectively dead before this.)
        """
        chargers = self.config.get("ev_chargers") or []
        if not chargers:
            return self.hass.states.is_state("switch.sem_smart_night_charging", "on")
        for c in chargers:
            cid = c.get("id", "ev_charger") if isinstance(c, dict) else "ev_charger"
            if self.hass.states.is_state(f"switch.sem_charger_{cid}_smart_night_charging", "on"):
                return True
        return False

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
            cid = chargers[0].get("id", "ev_charger")
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

    # Max consecutive cycles to hold the last home-consumption value (#237).
    # ~2 cycles (≈20-30s) smooths single/double-cycle sensor-lag dips while a
    # genuinely sustained zero is still reported after the hold window.
    HOME_HOLD_MAX_CYCLES = 2

    def _smooth_home_consumption(self, power) -> None:
        """Hold the last positive home-consumption value through transient dips to 0 (#237).

        The energy balance clamps ``home_consumption_power`` to 0 when instantaneous
        sensor readings momentarily lag a large load. Rather than emit a one-cycle 0,
        hold the last positive value for up to ``HOME_HOLD_MAX_CYCLES``; a zero that
        persists beyond that is reported as real. Runs before energy integration so
        the held value also keeps the home-energy total from under-counting.
        """
        if power.home_consumption_power > 0:
            self._last_home_consumption = power.home_consumption_power
            self._home_hold_count = 0
            return
        last = getattr(self, "_last_home_consumption", 0.0)
        held = getattr(self, "_home_hold_count", 0)
        if last > 0 and held < self.HOME_HOLD_MAX_CYCLES:
            self._home_hold_count = held + 1
            power.home_consumption_power = last
            _LOGGER.debug(
                "Home consumption clamped to 0 — holding last value %.0fW (%d/%d)",
                last, self._home_hold_count, self.HOME_HOLD_MAX_CYCLES,
            )
        else:
            # Sustained zero (beyond the hold window) — accept it as real.
            self._home_hold_count = held + 1

    @staticmethod
    def _get_version() -> str:
        """Read version from manifest.json (single source of truth with HACS)."""
        import json as _json
        import os
        manifest = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manifest.json")
        try:
            with open(manifest) as f:
                return _json.load(f).get("version", "0.0.0")
        except (OSError, ValueError):
            return "0.0.0"

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
            else:
                _info("Energy Dashboard not configured or incomplete")

        except Exception as e:
            _LOGGER.warning("Failed to read Energy Dashboard: %s", e)

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
            if self.hass.states.get(f"sensor.{ENTITY_SOLAR_POWER}") is None:
                issues.append("Solar power sensor missing")
            if issues:
                _LOGGER.warning("SEM health check: %s", "; ".join(issues))
            else:
                charger_names = [d.name for d in self._ev_devices.values()] if self._ev_devices else [self._ev_device.name if self._ev_device else "none"]
                _LOGGER.info("SEM health check: all OK (EV chargers: %s)", ", ".join(charger_names))

        # Read observer mode from switch entity (allows runtime toggle)
        observer_state = self.hass.states.get(f"switch.{ENTITY_OBSERVER_MODE_SWITCH}")
        if observer_state is not None:
            self._observer_mode = observer_state.state == "on"

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

            # Step 2: Calculate energy from power integration
            energy = self._energy_calculator.calculate_energy(power)

            # Step 3: Calculate costs and performance
            costs = self._energy_calculator.calculate_costs(energy)
            performance = self._energy_calculator.calculate_performance(power, energy)

            # Step 4: Calculate power flows (instantaneous)
            power_flows = self._flow_calculator.calculate_power_flows(power)

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
                    # Scale power flows proportionally to each charger's share (#15)
                    if total_charger_power > 0:
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
                    if pc_chrg_sensor:
                        pc_state = self.hass.states.get(pc_chrg_sensor)
                        if pc_state and pc_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                            power.ev_charging = pc_state.state == "on"
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

            # Step 5: Integrate energy flows from this cycle's instantaneous
            # power_flows (#282). Replaces the legacy daily proportional
            # allocation (calculate_energy_flows) which credited solar to the
            # EV even when the EV wasn't drawing. The integrated version
            # matches the session attribution: small honest numbers that
            # reflect what physically happened, not a daily average.
            energy_flows = self._flow_calculator.integrate_energy_flows(
                power_flows, self.update_interval.total_seconds(),
            )

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

            if self._ev_devices and not self._observer_mode:
                # Multi-charger (#112): distribute budget + night target
                ev_budget_per_charger = {}
                num_chargers = len(self._ev_devices)

                # Night target: use per-charger targets if configured (#193).
                # TARIFF_WAITING_FOR_CHEAP is also a night state (#247) — compute
                # the per-charger targets so a waiting charger can still re-plan.
                self._night_target_per_charger_map = {}
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
                    if cycle_budget is not None:
                        total_budget = cycle_budget.net_w
                    else:
                        # Defence-in-depth — partial init / unit tests.
                        # _calculate_solar_ev_budget is the legacy path; Phase D.2
                        # will remove this fallback after PROD soak confirms.
                        total_budget = self._calculate_solar_ev_budget(
                            charging_state, power, charging_context
                        )
                    ev_budget_per_charger = self._surplus_controller.distribute_ev_budget(
                        total_budget, self._ev_devices
                    )

                sorted_chargers = sorted(
                    self._ev_devices.items(),
                    key=lambda x: x[1].priority,
                )
                # Shared night peak budget (#274/H1): chargers are sized in
                # priority order against one peak headroom; reset the running
                # commitment before the loop.
                self._night_committed_w = 0.0
                for cid, ev_dev in sorted_chargers:
                    # Check per-charger night charging switch (#193)
                    if charging_state in (
                        ChargingState.NIGHT_CHARGING_ACTIVE,
                        ChargingState.TARIFF_WAITING_FOR_CHEAP,
                    ):
                        night_switch = self.hass.states.get(
                            f"switch.sem_charger_{cid}_night_charging"
                        )
                        if night_switch and night_switch.state == "off":
                            continue  # Skip this charger for night charging

                    # Save coordinator-level state, swap in per-charger state
                    saved = {
                        "dev": self._ev_device,
                        "stalled": self._ev_stalled_since,
                        "enable": self._ev_enable_surplus_since,
                        "started": self._ev_charge_started_at,
                        "change": self._ev_last_change_time,
                        "reenable_attempts": self._ev_reenable_attempts,
                        "charge_refused": self._ev_charge_refused,
                    }
                    self._ev_device = ev_dev
                    self._ev_stalled_since = self._ev_stalled_since_per_charger.get(cid)
                    self._ev_enable_surplus_since = self._ev_enable_surplus_per_charger.get(cid)
                    self._ev_charge_started_at = self._ev_charge_started_per_charger.get(cid)
                    self._ev_last_change_time = self._ev_last_change_per_charger.get(cid)
                    self._ev_reenable_attempts = self._ev_reenable_attempts_per_charger.get(cid, 0)
                    self._ev_charge_refused = self._ev_charge_refused_per_charger.get(cid, False)
                    self._current_charger_budget = ev_budget_per_charger.get(cid)
                    # Set per-charger night target (#193)
                    per_charger_target = getattr(self, '_night_target_per_charger_map', {}).get(cid)
                    if per_charger_target is not None:
                        self._night_target_per_charger = per_charger_target

                    # Per-charger SOC target and surplus limit (#215)
                    saved_vehicle_soc_ctrl = self._cycle_vehicle_soc
                    ev_chargers_cfg = self.config.get("ev_chargers", [])
                    charger_cfg = next((c for c in ev_chargers_cfg if c.get("id") == cid), {})
                    per_soc_entity = charger_cfg.get("vehicle_soc_entity", "")
                    if per_soc_entity:
                        soc_st = self.hass.states.get(per_soc_entity)
                        if soc_st and soc_st.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                            try:
                                self._cycle_vehicle_soc = float(soc_st.state)
                            except (ValueError, TypeError):
                                _LOGGER.debug("Vehicle SOC %s not numeric: %r (#259)", per_soc_entity, soc_st.state)
                    # Ceiling (Max) gates surplus; floor (Min) drives night top-up (#245)
                    per_remaining = self._calculate_remaining_need(
                        energy, self._cycle_vehicle_soc, charger_cfg, bound="max"
                    )
                    per_remaining_floor = self._calculate_remaining_need(
                        energy, self._cycle_vehicle_soc, charger_cfg, bound="min"
                    )
                    # Surplus stops at this charger's Max ceiling (default full) (#245)
                    per_target_reached = per_remaining <= 0.1
                    charging_context.soc_limit_active = per_target_reached
                    charging_context.daily_target_reached = per_target_reached
                    charging_context.remaining_ev_energy = per_remaining
                    charging_context.night_target_kwh = per_charger_target if per_charger_target is not None else per_remaining_floor

                    # Per-charger deadline + tariff plan (#246/#247): recompute
                    # for THIS charger and pick its effective night state. Each car
                    # can have its own deadline / tariff toggle, so the displayed
                    # (primary) state isn't authoritative for the rest.
                    effective_state = charging_state
                    charging_context.night_deadline_amps = 0
                    charging_context.night_deadline_active = False
                    charging_context.night_tariff_wait = False
                    charging_context.night_deadline_reachable = True
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

                    try:
                        await self._execute_ev_control(
                            effective_state, power, energy, charging_context
                        )
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
                    except (HomeAssistantError, ServiceValidationError) as e:
                        _LOGGER.error("EV control service failed for %s: %s", cid, e)
                    except ValueError as e:
                        _LOGGER.warning("EV control invalid value for %s: %s", cid, e)
                    finally:
                        # Save back per-charger state, restore coordinator state
                        self._ev_stalled_since_per_charger[cid] = self._ev_stalled_since
                        self._ev_enable_surplus_per_charger[cid] = self._ev_enable_surplus_since
                        self._ev_charge_started_per_charger[cid] = self._ev_charge_started_at
                        self._ev_last_change_per_charger[cid] = self._ev_last_change_time
                        self._ev_reenable_attempts_per_charger[cid] = self._ev_reenable_attempts
                        self._ev_charge_refused_per_charger[cid] = self._ev_charge_refused
                        self._ev_device = saved["dev"]
                        self._ev_stalled_since = saved["stalled"]
                        self._ev_enable_surplus_since = saved["enable"]
                        self._ev_charge_started_at = saved["started"]
                        self._ev_last_change_time = saved["change"]
                        self._ev_reenable_attempts = saved["reenable_attempts"]
                        self._ev_charge_refused = saved["charge_refused"]
                        self._current_charger_budget = None
                        self._cycle_vehicle_soc = saved_vehicle_soc_ctrl
                self._save_ev_session_state()
            elif self._ev_device and not self._observer_mode:
                try:
                    await self._execute_ev_control(
                        charging_state, power, energy, charging_context
                    )
                    self._save_ev_session_state()
                except (HomeAssistantError, ServiceValidationError) as e:
                    _LOGGER.error("EV control service failed: %s", e)
                except ValueError as e:
                    _LOGGER.warning("EV control invalid value: %s", e)

            # Step 7.5c: Battery discharge protection (night charging)
            discharge_limit = None
            if not self._observer_mode:
                try:
                    discharge_limit = await self._apply_battery_discharge_protection(
                        charging_state, power
                    )
                except (HomeAssistantError, ServiceValidationError) as e:
                    _LOGGER.error(
                        "Battery discharge protection service failed (resetting state): %s", e
                    )
                    self._battery_protection_active = False

            # Step 7.5d: Battery charge scheduler (#6)
            if not self._observer_mode and self._battery_charge_scheduler.enabled:
                try:
                    await self._execute_battery_charge_scheduler(power)
                except Exception as e:
                    _LOGGER.warning("Battery charge scheduler error: %s", e, exc_info=True)

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
            if self._energy_dashboard_config and not self._energy_calculator._yearly_seeded:
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
                pv_data, assistant_data, utility_data, heat_pump_data = \
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

            # Step 11.5: Energy balance / calculation health check
            self._health_check.run_all_checks(
                power,
                flows=power_flows,
                autarky=performance.autarky_rate,
                self_consumption=performance.self_consumption_rate,
                costs=costs,
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
                await self._storage.async_save_energy_delayed()

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
                # Per-charger session data
                session = self._session_data_per_charger.get(cid)
                if session:
                    result[f"charger_{cid}_session_energy"] = round(session.energy_kwh, 2)
                    result[f"charger_{cid}_session_solar_share"] = round(session.solar_share_pct, 1)
                else:
                    result[f"charger_{cid}_session_energy"] = 0.0
                    result[f"charger_{cid}_session_solar_share"] = 0.0
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
                _pcfg = (self.config.get("ev_chargers") or [{}])[0]

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
            _dl_pcfg = (self.config.get("ev_chargers") or [{}])[0]
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
                _np = self._cycle_night_plan
                _ev_remaining = _np.remaining_kwh if _np else None
                _ev_deadline_dt = _np.deadline_dt if _np else None
                _ev_rate_kw = None
                if _np and _np.hours_to_deadline and _np.hours_to_deadline > 0 and _np.remaining_kwh:
                    # The planner's reachable=True implies remaining/rate <= hours_left;
                    # this is the rough effective rate (peak-managed unless forcing).
                    _ev_rate_kw = _np.remaining_kwh / max(0.1, _np.hours_to_deadline)
                # Daytime fallback (#282): the night planner only runs inside the
                # night window, so during the day _np is None and the strip would
                # have no EV rows. Estimate remaining_to_min from the daily target
                # vs accumulated, and resolve deadline from the charger config so
                # the EV card can show "tonight's plan" as a preview.
                #
                # Gate on the night_charging switch being ON: when the user has
                # explicitly disabled overnight grid charging, surfacing a "EV
                # will charge at 21:22" row is misleading — the charger will
                # NOT actually charge. Respect their opt-out.
                if _ev_remaining is None or _ev_remaining <= 0.1:
                    try:
                        _pcfg = _dl_pcfg or {}
                        _cid = _pcfg.get("id")
                        _night_on = (
                            _cid and self.hass.states.is_state(
                                f"switch.sem_charger_{_cid}_night_charging", "on"
                            )
                        )
                        if not _night_on:
                            raise ValueError("night charging disabled — no EV preview")
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
                            from .ev_tariff_planner import resolve_deadline
                            _tt = self._charger_target_time(_pcfg)
                            _ev_deadline_dt = resolve_deadline(_now, _tt)
                            # Rate estimate at 3-phase peak floor; the strip is a
                            # preview, not the truth — close enough for the visual.
                            _ev_rate_kw = 4.1  # ~6A x 690 W/A
                    except (ValueError, TypeError, AttributeError):
                        pass
                result["today_plan"] = compose_today_plan(
                    now=_now,
                    upcoming_prices=result.get("tariff_upcoming"),
                    solar_peak_time=_peak_t,
                    solar_remaining_kwh=_solar_remaining,
                    night_start=_night_start,
                    night_end=_night_end_dt,
                    ev_min_remaining_kwh=_ev_remaining,
                    ev_deadline=_ev_deadline_dt,
                    ev_tariff_optimized=result.get("ev_tariff_optimized", False),
                    ev_tariff_waiting=result.get("ev_tariff_waiting", False),
                    ev_next_cheap_window=(
                        _np.next_cheap_start if _np and _np.next_cheap_start else None
                    ),
                    ev_effective_rate_kw=_ev_rate_kw,
                    currency=result.get("tariff_currency", ""),
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
            consumption_24h = self._predictor.predict_consumption_24h(now)
            if consumption_24h:
                result["predicted_consumption_next_hour"] = round(consumption_24h[0], 0)
                result["predicted_consumption_today_kwh"] = round(
                    self._predictor.predict_consumption_today_kwh(now), 2
                )
            solar_24h = self._predictor.predict_solar_24h(now)
            if solar_24h:
                result["predicted_solar_next_hour"] = round(solar_24h[0], 0)
            surplus_window = self._predictor.predict_surplus_window(now)
            if surplus_window:
                result["predicted_surplus_window"] = surplus_window

            return result

        except Exception as e:
            _LOGGER.error("Error updating SEM data: %s", e, exc_info=True)
            raise UpdateFailed(f"Update failed: {e}") from e

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
            tracker_data["forecast_corrected_tomorrow"] = self._forecast_tracker.apply_correction(
                forecast_data.forecast_tomorrow_kwh
            )
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
            if tariff.next_cheap_window_start:
                tariff_data.tariff_next_cheap_start = tariff.next_cheap_window_start.isoformat()
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("Tariff read failed: %s", e)

        # Surplus controller (Phase 0.2)
        surplus_data = SurplusControlData()
        try:
            allocation = await self._surplus_controller.update(
                available_power, price_level=tariff_data.tariff_price_level,
            )
            surplus_data.surplus_total_w = allocation.total_surplus_w
            surplus_data.surplus_distributable_w = allocation.distributable_surplus_w
            surplus_data.surplus_regulation_offset_w = allocation.regulation_offset_w
            surplus_data.surplus_allocated_w = allocation.allocated_w
            surplus_data.surplus_unallocated_w = allocation.unallocated_w
            surplus_data.surplus_active_devices = allocation.active_devices
            surplus_data.surplus_total_devices = allocation.total_devices
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

        heat_pump_data = HeatPumpSensorData()

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
        )

    async def _execute_battery_charge_scheduler(self, power) -> None:
        """Execute the battery charge scheduler cycle (#6).

        - Checks if it's time for daily evaluation (21:00)
        - Checks if re-plan is needed (SOC drift, EV change)
        - Runs the update cycle (start/stop/adjust forced charge)
        """
        scheduler = self._battery_charge_scheduler
        now = dt_util.now()

        # Daily evaluation trigger
        if scheduler.should_trigger_evaluation(now):
            forecast = self._forecast_reader.read_forecast()
            forecast_tomorrow = forecast.forecast_tomorrow_kwh if forecast.available else 0.0
            forecast_age = 0.0
            if hasattr(forecast, 'last_update') and forecast.last_update:
                forecast_age = (now - forecast.last_update).total_seconds() / 3600

            correction = self._forecast_tracker.correction_factor

            # Get expected consumption from predictor
            expected_consumption = self._predictor.predict_consumption_today_kwh(now)
            if expected_consumption <= 0:
                expected_consumption = 12.0  # Fallback: 12 kWh/day

            # Get tariff rates
            off_peak_rate = self._tariff_provider.get_price_at(
                now.replace(hour=2, minute=0)  # Night / off-peak rate
            ) if hasattr(self._tariff_provider, 'get_price_at') else self.config.get("electricity_off_peak_rate") or self.config.get("electricity_nt_rate", 0.22)
            peak_rate = self._tariff_provider.get_price_at(
                now.replace(hour=14, minute=0)  # Day / peak rate
            ) if hasattr(self._tariff_provider, 'get_price_at') else self.config.get("electricity_import_rate", 0.30)

            # Current price for negative tariff detection
            current_price = 0.0
            if hasattr(self._tariff_provider, 'get_current_import_rate'):
                current_price = self._tariff_provider.get_current_import_rate()

            # EV energy needed tonight
            ev_kwh_needed = 0.0
            ev_max_power = 0.0
            if self._ev_devices:
                daily_target = self.config.get("daily_ev_target", 10)
                ev_today = self._energy_calculator._get_daily("ev_charging")
                ev_kwh_needed = max(0, daily_target - ev_today)
                # Use first charger's max power as reference
                first_charger = next(iter(self._ev_devices.values()), None)
                if first_charger and hasattr(first_charger, 'max_power_w'):
                    ev_max_power = first_charger.max_power_w
                else:
                    ev_max_power = self.config.get("ev_max_power_w", 11000)

            # Dynamic tariff provider (if available)
            tariff_provider = None
            if hasattr(self._tariff_provider, 'find_cheapest_hours'):
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

        # Re-plan check
        ev_connected = power.ev_connected if hasattr(power, 'ev_connected') else False
        if scheduler.should_replan(power.battery_soc, ev_connected):
            # Force re-evaluation by clearing date guard
            scheduler._last_evaluation_date = None
            # Will trigger on next cycle since should_trigger won't match time
            # For immediate replan, just call evaluate again
            _LOGGER.info("Battery scheduler: re-plan triggered, will re-evaluate")

        # Execute the decision (start/stop/adjust charge)
        await scheduler.update(
            current_soc=power.battery_soc,
            ev_charging_power_w=power.ev_power,
        )

        # Reset scheduler when night ends
        if not self.time_manager.is_night_mode() and scheduler.state.value not in ("idle", "not_needed", "not_profitable"):
            scheduler.reset()

    async def _send_notifications(
        self, charging_state, power, energy, costs, performance,
        charging_context, forecast_data, discharge_limit,
        calculated_current, available_power,
    ) -> None:
        """Send state-change and event-based notifications (#29).

        Extracted from _async_update_data to reduce cyclomatic complexity.
        """
        await self._notification_manager.notify_state_change(
            charging_state,
            {
                "battery_soc": power.battery_soc,
                "calculated_current": calculated_current,
                "available_power": available_power,
                "daily_ev_energy": energy.daily_ev,
                "charging_strategy": charging_context.charging_strategy,
                "charging_strategy_reason": charging_context.charging_strategy_reason,
                "discharge_limit": discharge_limit,
            }
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
            for cid, intel in per_charger_intel.items():
                charger_name = self._ev_devices[cid].name if cid in self._ev_devices else cid
                charger_connected = self._last_ev_connected_per_charger.get(cid, False)
                mins_to_full = intel.get("minutes_to_full", 0)
                est_soc = intel.get("estimated_soc", 0)
                charge_needed = intel.get("charge_needed", False)
                nights = intel.get("nights_until_charge", 0)

                # 1. Nearly full: taper detector shows < 5 minutes remaining
                if mins_to_full > 0 and mins_to_full < 5 and power.ev_charging:
                    await self._notification_manager.notify_ev_nearly_full(
                        mins_to_full, charger_name=charger_name
                    )

                # 2. Night charge skipped: night mode, EV connected, skip decided
                if (is_night and charger_connected
                        and not charge_needed and est_soc > 0):
                    await self._notification_manager.notify_ev_charge_skip(
                        est_soc, nights, charger_name=charger_name
                    )

                # 3. Charge recommended: night mode, SOC low, charge needed
                if (is_night and charger_connected
                        and charge_needed and 0 < est_soc < 30):
                    await self._notification_manager.notify_ev_charge_recommended(
                        est_soc, charger_name=charger_name
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

    def _canonical_strategy_from_legacy(self, legacy_strategy: str, legacy_reason: str) -> str:
        """Map ``_determine_charging_strategy`` output → :class:`EVBudgetStrategy`.

        The legacy code returns ``"solar_only"`` for both Zone 3
        surplus-with-redirect AND Zone 2 surplus-only. The actuator
        distinguished via substring matching on the reason text — the
        proximate cause of the #282 three-way disagreement. This mapper
        immortalises that signal while we transition; Phase D promotes
        ``self_consumption`` to a first-class strategy return and the
        substring matching goes away.
        """
        from .flow_calculator import EVBudgetStrategy

        if legacy_strategy == "idle":
            return EVBudgetStrategy.IDLE
        if legacy_strategy == "now":
            return EVBudgetStrategy.NOW
        if legacy_strategy == "min_pv":
            return EVBudgetStrategy.MIN_PV
        if legacy_strategy == "night_grid":
            # Night charging tops up to the Min floor using grid (#245
            # semantic). Canonical MIN_PV is the right shape — its formula
            # is ``max(min_power_floor, surplus + redirect)`` and at night
            # the surplus term is ~0, leaving the grid floor as the actual
            # budget. The actuator's NIGHT_CHARGING_ACTIVE branch in
            # ev_control.py uses its own peak-aware, deadline-aware current
            # calculation independently — so this mapping affects only
            # what's published on sem_available_power / sem_calculated_current
            # (now reflects the canonical floor instead of 0). Pre-fix this
            # case was missing and raised ValueError on the first real night
            # charging cycle with remaining_need > 0.1.
            return EVBudgetStrategy.MIN_PV
        if legacy_strategy == "battery_assist":
            return EVBudgetStrategy.BATTERY_ASSIST
        if legacy_strategy == "solar_only":
            # Disambiguate Z2 self_consumption from Z3 solar_only via reason.
            # Both _self_consumption_strategy and Zone 2 in the zone logic
            # tag their reason with "self_consumption" or "Zone 2".
            if "self_consumption" in legacy_reason or "Zone 2" in legacy_reason:
                return EVBudgetStrategy.SELF_CONSUMPTION
            return EVBudgetStrategy.SOLAR_ONLY
        # Be loud about unknown strategies — silent fallthrough was the #282 root.
        raise ValueError(
            f"_canonical_strategy_from_legacy: unknown legacy strategy "
            f"{legacy_strategy!r} (reason: {legacy_reason!r}). Add a case "
            f"in this mapper if you introduced a new strategy value."
        )

    def _determine_charging_strategy(self, power: PowerReadings, energy: Any,
                                     charger_cfg: dict | None = None) -> tuple:
        """SOC-zone-based charging strategy decision (inspired by evcc).

        SOC Zones:
          Zone 4: SOC >= auto_start_soc (90%) — full battery assist, start EV even without surplus
          Zone 3: SOC >= buffer_soc (70%)     — battery can discharge to bridge gaps
          Zone 2: SOC >= priority_soc (30%)   — surplus only, no battery discharge
          Zone 1: SOC < priority_soc (30%)    — battery priority, EV blocked

        Returns: (strategy, reason) where strategy is one of:
            "solar_only", "battery_assist", "night_grid", "idle"
        """
        vehicle_soc = self._cycle_vehicle_soc
        # Measured against the floor (Min, the default): this is the guaranteed
        # target used for the night top-up decision and the auto-mode forecast
        # ratio. Solar surplus still continues past Min up to the Max ceiling —
        # that stop is gated separately by soc_limit_active, not here (#245).
        # charger_cfg makes the night go/stop decision honor the PER-CHARGER target
        # (Min floor) instead of only the global one (#245 propagation review).
        remaining_need = self._calculate_remaining_need(energy, vehicle_soc, charger_cfg)

        # EV not connected → idle
        if not power.ev_connected:
            return ("idle", f"ev disconnected")

        # Night mode → grid charging tops up to the floor (Min) (#245).
        # remaining_need above is already the Min-bound value (default bound="min").
        if self.time_manager.is_night_mode():
            # Threshold aligned with _night_state_machine (#282 followup): both
            # paths now agree at 0.1 kWh ≈ one cycle of 6A × 3 × 230 V min
            # current. Pre-fix the strategy used `< 0.5` while the state machine
            # used `<= 0.1`, producing the dashboard "Night charging active"
            # label while the strategy reported "idle, target reached" — same
            # disagreement class as #282 (display/decision mismatch).
            # Min is the GUARANTEED floor; deliver to it exactly.
            if remaining_need <= 0.1:
                soc_info = f", SOC={vehicle_soc:.0f}%" if vehicle_soc is not None else ""
                return ("idle", f"night target reached ({energy.daily_ev:.1f}kWh{soc_info})")

            _cfg = charger_cfg or {}
            _target_soc = (
                _cfg.get("ev_target_soc") if _cfg.get("ev_target_soc") is not None
                else self.config.get("ev_target_soc", 80)
            )
            soc_info = f", SOC={vehicle_soc:.0f}%→{_target_soc}%" if vehicle_soc is not None else ""

            # Tariff-optimized cheap-hour waiting is OPT-IN (#247). The authoritative
            # decision lives in the night planner (_compute_night_plan →
            # NightChargePlan.should_wait_for_cheap → TARIFF_WAITING_FOR_CHEAP
            # state). This branch only sets the strategy reason string; consult
            # the SAME plan to avoid the two paths disagreeing (#281/D3): the old
            # code re-ran its own cheap-hour calc with a hardcoded 12h lookahead
            # and no peak-awareness, so it could report "waiting for cheaper
            # hour" while the planner had already decided to charge now because
            # Min would miss — a contradictory state for debugging.
            if self._tariff_optimized_for(charger_cfg or {}):
                primary_cid = (charger_cfg or {}).get("id")
                cached_plan = self._night_plan_per_charger.get(primary_cid)
                if cached_plan is not None and cached_plan.should_wait_for_cheap:
                    nxt = cached_plan.next_cheap_start
                    when = nxt.strftime("%H:%M") if nxt else "?"
                    return ("idle", f"night: waiting for cheaper hour (next: {when}){soc_info}")

            return ("night_grid", f"night mode, remaining={remaining_need:.1f}kWh{soc_info}")

        # Solar mode: keep charging even past target (free surplus)
        # Target check only applies to night (grid) charging above

        # Charging mode selection: pv (default), minpv, now, off
        charging_mode = self.config.get("ev_charging_mode", "pv")
        _cmode = (charger_cfg or {}).get("ev_charging_mode")
        if _cmode:
            charging_mode = _cmode

        # Tariff-optimized daytime pause (#247): during expensive price windows,
        # drop the Min+PV grid guarantee and fall back to surplus / battery-assist
        # only (the zone logic below). Resumes automatically when the price drops
        # or solar is sufficient. The explicit "now" override and pure-surplus
        # modes are intentionally left untouched.
        if charging_mode == "minpv" and self._tariff_optimized_for(charger_cfg or {}):
            try:
                level = self._tariff_provider.get_price_level()
                if level in (PriceLevel.EXPENSIVE, PriceLevel.VERY_EXPENSIVE):
                    _LOGGER.debug(
                        "Tariff pause: %s price — Min+PV grid guarantee dropped "
                        "to surplus-only", level.value,
                    )
                    charging_mode = "pv"  # fall through to zone-based surplus logic
                if getattr(self, "_tariff_pause_warned", False):
                    self._tariff_pause_warned = False  # provider recovered
            except Exception as e:
                # Surface once (#274/L1): a persistently broken provider would
                # otherwise silently drop the Min+PV grid guarantee with no signal.
                if not getattr(self, "_tariff_pause_warned", False):
                    _LOGGER.warning(
                        "Tariff-optimized daytime pause disabled — price provider "
                        "error (Min+PV grid guarantee unchanged): %s", e,
                    )
                    self._tariff_pause_warned = True

        if charging_mode == "now":
            return ("now", "Now mode — charge at max immediately")
        if charging_mode == "off":
            return ("idle", "Solar charging disabled by user")
        if charging_mode == "minpv":
            return ("min_pv", f"Min+PV mode, remaining={remaining_need:.1f}kWh, solar={power.solar_power:.0f}W")
        if charging_mode == "self_consumption":
            return self._self_consumption_strategy(power, energy)

        if charging_mode == "auto":
            auto_result = self._auto_mode_strategy(power, energy, remaining_need)
            if auto_result is not None:
                return auto_result
            # None = fall through to normal zone-based pv logic below

        # No meaningful solar → wait
        if power.solar_power < 200:
            return ("idle", f"solar={power.solar_power:.0f}W < 200W threshold")

        # SOC zone thresholds
        auto_start_soc = self.config.get("battery_auto_start_soc", 90)
        buffer_soc = self.config.get("battery_buffer_soc", 70)
        priority_soc = self.config.get("battery_priority_soc", 30)
        battery_floor = self.config.get("battery_assist_floor_soc", 60)
        battery_capacity = self.battery_capacity_kwh

        already_assisting = (self._state_machine.current_state == ChargingState.SOLAR_SUPER_CHARGING)

        # Debounce zone selection so single-cycle blips (config tweak, SOC
        # jitter near a boundary) don't bounce strategy idle ↔ solar/assist.
        raw_zone = self._raw_zone(power.battery_soc, auto_start_soc, buffer_soc, priority_soc)
        zone = self._debounce_zone(raw_zone, (auto_start_soc, buffer_soc, priority_soc))

        # Zone 4: full battery assist (battery full enough to start EV even
        # without surplus).
        if zone == 4:
            usable_battery = max(0, (power.battery_soc - battery_floor) / 100 * battery_capacity)
            return (
                "battery_assist",
                f"Zone 4: SOC={power.battery_soc:.0f}% >= auto_start={auto_start_soc}% — "
                f"full battery assist (usable={usable_battery:.1f}kWh)"
            )

        # Zone 3: battery can discharge to bridge gaps.
        if zone == 3:
            try:
                forecast = self._cycle_forecast
                if forecast.available:
                    surplus_factor = 0.5
                    dampening = self._forecast_tracker.dampening_factor
                    estimated_surplus = forecast.forecast_remaining_today_kwh * dampening * surplus_factor
                    if estimated_surplus >= remaining_need * 1.5:
                        # Plenty of solar ahead — solar_only is fine
                        return (
                            "solar_only",
                            f"Zone 3: SOC={power.battery_soc:.0f}% >= buffer={buffer_soc}%, "
                            f"forecast surplus {estimated_surplus:.1f}kWh >> need {remaining_need:.1f}kWh"
                        )
            except Exception as e:
                _LOGGER.debug("Forecast unavailable in charging strategy: %s", e)

            usable_battery = max(0, (power.battery_soc - battery_floor) / 100 * battery_capacity)
            return (
                "battery_assist",
                f"Zone 3: SOC={power.battery_soc:.0f}% >= buffer={buffer_soc}% — "
                f"discharge assist (usable={usable_battery:.1f}kWh, need={remaining_need:.1f}kWh)"
            )

        # Zone 2: surplus only (battery still needs charge; forecast-aware
        # redirect lives in flow_calculator).
        if zone == 2:
            # Hysteresis: if already assisting, stay active down to floor_soc
            if already_assisting and power.battery_soc >= battery_floor:
                return (
                    "battery_assist",
                    f"Zone 2 hysteresis: SOC={power.battery_soc:.0f}% >= floor={battery_floor}%, "
                    f"keeping battery assist active"
                )
            reason = f"Zone 2: SOC={power.battery_soc:.0f}% in [{priority_soc}%..{buffer_soc}%) — surplus only"
            try:
                forecast = self._cycle_forecast
                if forecast.available:
                    surplus_factor = 0.5
                    dampening = self._forecast_tracker.dampening_factor
                    estimated_surplus = forecast.forecast_remaining_today_kwh * dampening * surplus_factor
                    reason += f" (forecast surplus={estimated_surplus:.1f}kWh, need={remaining_need:.1f}kWh)"
            except Exception as e:
                _LOGGER.debug("Forecast unavailable in charging strategy: %s", e)
            return ("solar_only", reason)

        # Zone 1: battery priority. State machine routes to
        # SOLAR_PAUSE_LOW_BATTERY via battery_too_low flag.
        return ("idle", f"Zone 1: SOC={power.battery_soc:.0f}% < priority={priority_soc}% — battery priority")

    def _self_consumption_strategy(self, power, energy) -> tuple:
        """Self-consumption mode: charge EV from true solar surplus only (#67).

        Budget = solar - home (no ev_power add-back, no battery discharge for EV).
        Zone 4 (SOC ≥ 90%): don't subtract battery charge (redirect to EV).
        Zone 1-3: battery charges first, subtract battery_charge from budget.
        Battery discharging for home is fine (that's using stored solar).
        """
        if power.solar_power < 200:
            return ("idle", f"self_consumption: solar={power.solar_power:.0f}W < 200W")

        auto_start_soc = self.config.get("battery_auto_start_soc", 90)
        available = power.solar_power - power.home_consumption_power

        if power.battery_soc < auto_start_soc:
            available -= power.battery_charge_power  # battery charges first

        available = max(0, available)
        zone = "Z4-redirect" if power.battery_soc >= auto_start_soc else f"Z{self._get_zone(power.battery_soc)}"
        return ("solar_only", f"self_consumption ({zone}): surplus={available:.0f}W, solar={power.solar_power:.0f}W")

    def _auto_mode_strategy(self, power, energy, remaining_need: float) -> tuple:
        """Auto mode: forecast-aware switching between self_consumption and pv (#67).

        ratio = remaining_solar / remaining_ev_need
        ratio > 2.0 → self_consumption (plenty of sun, no rush)
        1.0-2.0     → pv with cap (tight, charge when available)
        < 1.0       → pv aggressive (not enough, battery assist)
        """
        forecast = self._cycle_forecast
        remaining_solar = 0
        if forecast and forecast.available:
            remaining_solar = forecast.forecast_remaining_today_kwh
            try:
                remaining_solar = self._forecast_tracker.apply_dampening(remaining_solar)
            except (ValueError, AttributeError):
                pass

        if remaining_need < 0.5:
            # Floor (Min) met — no forecast-based pacing needed. Solar surplus
            # still continues up to the Max ceiling via the surplus path (#245).
            return ("idle", "auto: min target met, solar continues to ceiling")

        ratio = remaining_solar / remaining_need if remaining_need > 0 else 99

        if ratio > 2.0:
            # Plenty of sun → self_consumption
            result = self._self_consumption_strategy(power, energy)
            return (result[0], f"auto (ratio={ratio:.1f}→self_consumption): {result[1]}")
        elif not forecast or not forecast.available:
            # No forecast → default pv behavior (fall through to zone logic below)
            pass
        else:
            # Tight or insufficient → pv with zones (fall through)
            _LOGGER.debug("auto: ratio=%.1f → pv mode (zones active)", ratio)

        # Fall through to normal zone-based pv logic
        # (return None so caller continues to zone logic)
        return None  # Signal: continue to zone logic

    def _raw_zone(self, soc: float, auto_start: float, buffer: float, priority: float) -> int:
        """Map SOC to a zone number using raw (un-debounced) thresholds."""
        if soc >= auto_start: return 4
        if soc >= buffer: return 3
        if soc >= priority: return 2
        return 1

    def _get_zone(self, soc: float) -> int:
        """Get SOC zone number for logging (raw, no debounce)."""
        auto_start = self.config.get("battery_auto_start_soc", 90)
        buffer = self.config.get("battery_buffer_soc", 70)
        priority = self.config.get("battery_priority_soc", 30)
        return self._raw_zone(soc, auto_start, buffer, priority)

    def _debounce_zone(self, raw_zone: int, thresholds: tuple) -> int:
        """Hold the stable SOC zone until raw_zone is seen for N cycles.

        Returning a stable zone smooths over single-cycle blips that would
        otherwise flip charging strategy from solar_only → idle → solar_only
        (and bounce the battery Charging→Idle→Charging). The most common blip
        is a user adjusting a threshold via a number entity; the second is
        SOC noise around a zone boundary.

        A change in `thresholds` resets the pending-candidate counter so the
        new boundaries are evaluated from a clean slate without compounding
        the blip caused by the change itself.
        """
        cycles = max(1, int(self.config.get("zone_debounce_cycles", 2)))

        last_thresholds = getattr(self, "_last_zone_thresholds", None)
        if last_thresholds is not None and last_thresholds != thresholds:
            self._pending_zone = None
            self._pending_zone_count = 0
        self._last_zone_thresholds = thresholds

        stable = getattr(self, "_stable_zone", None)
        if stable is None:
            self._stable_zone = raw_zone
            return raw_zone

        if raw_zone == stable:
            self._pending_zone = None
            self._pending_zone_count = 0
            return stable

        if raw_zone == getattr(self, "_pending_zone", None):
            self._pending_zone_count = getattr(self, "_pending_zone_count", 0) + 1
        else:
            self._pending_zone = raw_zone
            self._pending_zone_count = 1

        if self._pending_zone_count >= cycles:
            _LOGGER.info(
                "SOC zone transition %d → %d applied after %d stable cycles",
                stable, raw_zone, self._pending_zone_count,
            )
            self._stable_zone = raw_zone
            self._pending_zone = None
            self._pending_zone_count = 0
            return raw_zone

        _LOGGER.debug(
            "SOC zone candidate %d (count=%d/%d), holding stable=%d",
            raw_zone, self._pending_zone_count, cycles, stable,
        )
        return stable

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
        """Calculate remaining EV charging need in kWh from the best available source.

        When ev_target_type is "soc" AND vehicle_soc is available: SOC-based.
        When ev_target_type is "kwh" OR vehicle_soc is unavailable: kWh daily target.
        Used by both _build_charging_context() and _determine_charging_strategy().

        ``bound`` selects which target to measure against (#245):
          - "min" (default, floor = the existing single target): the guaranteed
            amount; night/grid tops up to this. This is what callers usually mean
            by "remaining to target".
          - "max" (ceiling): surplus charges up to this, then stops. Defaults to
            full (100% / 100 kWh ≈ unlimited) when no Max is set.
        """
        cfg = charger_cfg or {}
        ev_capacity = cfg.get("ev_battery_capacity_kwh") if cfg.get("ev_battery_capacity_kwh") is not None else self.config.get("ev_battery_capacity_kwh", 40)
        # ev_target_mode was renamed to ev_target_type (#235); read both for back-compat.
        ev_target_type = (
            cfg.get("ev_target_type") or cfg.get("ev_target_mode")
            or self.config.get("ev_target_type") or self.config.get("ev_target_mode", "kwh")
        )

        # De-trap %: if % is selected but there's no real SOC sensor, fall back to
        # the EV-intelligence virtual SOC — but only when it has a confident anchor
        # (a detected full charge / car-API calibration). The estimate is a *soft*
        # ceiling: taper detection is still the hard "full" stop, and the Min floor
        # still grid-tops-up, so an estimate error is bounded. With no real SOC and
        # no anchored estimate, fall through to the kWh target (no silent no-op). (#245)
        if ev_target_type == "soc" and vehicle_soc is None:
            cid = cfg.get("id")
            detectors = getattr(self, "_ev_taper_detectors", {}) or {}
            detector = detectors.get(cid) if cid else getattr(self, "_ev_taper_detector", None)
            if detector is not None and getattr(detector, "_soc_anchored", False):
                vehicle_soc = detector.get_virtual_soc(None)

        use_soc = ev_target_type == "soc" and vehicle_soc is not None
        if use_soc:
            # SOC ceiling defaults to 100% (car full); floor default 80%.
            soc_target = self._resolve_target(cfg, "ev_target_soc", bound, 80, 100)
            return max(0, (soc_target - vehicle_soc) / 100 * ev_capacity)
        # kWh ceiling defaults to 100 kWh/day (≈ unlimited); floor default 10.
        daily_target = self._resolve_target(cfg, "daily_ev_target", bound, 10, 100)
        return max(0, daily_target - energy.daily_ev)

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
        battery_min_soc = self.config.get("battery_minimum_soc", 20)
        battery_priority_soc = self.config.get("battery_priority_soc", 30)

        battery_too_low = power.battery_soc < battery_min_soc
        battery_needs_priority = power.battery_soc < battery_priority_soc
        # Ceiling (Max, default full) gates the surplus stop; floor (Min) drives
        # night top-up (#245). Resolve the (primary) charger's config so the base
        # context honors the PER-CHARGER targets, not just global. One car per
        # charger; the multi-charger loop still overrides per charger downstream.
        _primary_cfg = (self.config.get("ev_chargers") or [{}])[0]
        remaining = self._calculate_remaining_need(
            energy, self._cycle_vehicle_soc, _primary_cfg, bound="max"
        )
        remaining_floor = self._calculate_remaining_need(
            energy, self._cycle_vehicle_soc, _primary_cfg, bound="min"
        )
        # "daily_target_reached" here means the surplus CEILING (Max) is reached.
        daily_target_reached = remaining <= 0.1

        # Surplus stops at the Max ceiling (#245). Max defaults to full, so by
        # default this is only true at car-full — i.e. surplus charges freely.
        # (The ev_limit_surplus switch from #235 was folded into Max.)
        soc_limit_active = daily_target_reached

        # Calculate excess solar
        excess_solar = power.solar_power - power.home_consumption_power - power.battery_charge_power

        # Use EV budget (with battery redirect) instead of surplus-style available_power
        forecast_remaining = 0
        try:
            forecast = self._cycle_forecast
            if forecast.available:
                forecast_remaining = self._forecast_tracker.apply_dampening(
                    forecast.forecast_remaining_today_kwh
                )
        except Exception:
            pass

        battery_capacity = self.battery_capacity_kwh

        # Forecast-driven charging strategy (per-charger target via _primary_cfg).
        # Run the strategy decision BEFORE the budget calc so the diagnostic
        # ev_current sensor reflects the surplus-aware cap when strategy is
        # solar_only — otherwise the dashboard shows a "calculated_current"
        # that disagrees with what the charger is actually told to do (#282).
        strategy, reason = self._determine_charging_strategy(power, energy, _primary_cfg)

        # Canonical EV budget (#282 unification, Phase B). One method,
        # one number, used by the state machine here, the published
        # sensors below, and the actuator in ev_control. The strategy
        # mapper translates the legacy strategy text into the canonical
        # enum.
        from .flow_calculator import EVBudgetStrategy
        canonical_strategy = self._canonical_strategy_from_legacy(strategy, reason)
        # MIN_PV needs a min_power_floor; NOW needs an override. The
        # state machine doesn't read either, so leave them at defaults
        # here (the actuator's own dispatch fills those in when relevant —
        # see ev_control._cycle_ev_budget consumer in Phase B/C).
        min_power_floor_w = 0.0
        override_max_w = None
        if canonical_strategy == EVBudgetStrategy.MIN_PV:
            # 6 A * 3 phases * 230 V — KEBA / Wallbox EU minimum.
            min_power_floor_w = self.config.get(
                "ev_min_current", 6,
            ) * 3 * 230
        elif canonical_strategy == EVBudgetStrategy.NOW:
            override_max_w = self.config.get(
                "ev_max_current", 16,
            ) * 3 * 230

        ev_budget_obj = self._flow_calculator.calculate_canonical_ev_budget(
            power,
            strategy=canonical_strategy,
            battery_soc=power.battery_soc,
            battery_capacity_kwh=battery_capacity,
            forecast_remaining_kwh=forecast_remaining,
            battery_auto_start_soc=self.config.get("battery_auto_start_soc", 90),
            battery_buffer_soc=self.config.get("battery_buffer_soc", 70),
            battery_assist_floor_soc=self.config.get("battery_assist_floor_soc", 60),
            battery_assist_max_power_w=self.config.get(
                "battery_assist_max_power",
                self.config.get("super_charger_power", 4500),
            ),
            min_power_floor_w=min_power_floor_w,
            override_max_w=override_max_w,
        )
        # Cache for the actuator — ev_control reads self._cycle_ev_budget
        # instead of recomputing.
        self._cycle_ev_budget = ev_budget_obj
        ev_budget = ev_budget_obj.net_w
        ev_current = ev_budget_obj.current_a

        _LOGGER.debug(
            "Charging strategy: %s — %s",
            strategy, reason,
        )

        # Night charging tops up to the floor (Min), optionally reduced by forecast (#245)
        night_target = remaining_floor
        forecast_reduction = self._smart_night_charging_enabled()
        if self.time_manager.is_night_mode() and forecast_reduction:
            night_target = self._calculate_forecast_night_target(
                remaining_floor, energy, _primary_cfg,
            )

        # Deadline (#246) + tariff-optimized timing (#247) plan for the (primary)
        # charger — drives the displayed state and the single-charger control path.
        # The multi-charger loop recomputes this per charger downstream.
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

        Similar to EV session tracking but adapted for battery:
        - Charge session: starts when charge_power > 50W
        - Discharge session: starts when discharge_power > 50W
        - Session ends when power drops below 50W for 3 consecutive cycles
        - Direction change ends current session and starts new one
        """
        POWER_THRESHOLD = 50.0
        IDLE_CYCLES_TO_END = 3

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

        # Handle direction change — end current session, start new one
        if session.active and current_type != "idle" and current_type != session.session_type:
            session.active = False
            _LOGGER.debug(
                "Battery session ended (direction change): %s, %.2f kWh, %d min",
                session.session_type, session.energy_kwh, session.duration_minutes,
            )

        # Handle idle — count consecutive idle cycles
        if current_type == "idle":
            if session.active:
                self._battery_session_idle_count += 1
                if self._battery_session_idle_count >= IDLE_CYCLES_TO_END:
                    session.active = False
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

        # Accumulate energy
        interval_s = self.config.get("update_interval", 10)
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
                if charger_power > 0:
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
                    increment = charger_power * interval_hours / 1000  # W → kWh
                    self._daily_ev_per_charger[cid] = (
                        self._daily_ev_per_charger.get(cid, 0.0) + increment
                    )

                if charger_power > 0 or charger_connected:
                    self._ev_taper_detectors[cid].update(
                        charger_power, charger_setpoint, charger_connected, now,
                    )

            # Primary charger's detector drives SOC/skip (sync with main detector)
            primary_id = next(iter(self._ev_devices))
            if primary_id in self._ev_taper_detectors:
                self._ev_taper_detector = self._ev_taper_detectors[primary_id]

        # Get current EV setpoint (0 if no EV device)
        ev_setpoint = 0.0
        if self._ev_device:
            ev_setpoint = getattr(self._ev_device, "_current_setpoint", 0.0)

        # Run taper detection (primary / single charger)
        if power.ev_power > 0 or power.ev_connected:
            taper_data = self._ev_taper_detector.update(
                power.ev_power, ev_setpoint, power.ev_connected, now,
            )
        else:
            taper_data = EVTaperData()

        # Track energy since last full charge (hardware counter preferred)
        if hasattr(energy, "daily_ev"):
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

        # Stall detection → full charge: if car is connected, SEM is sending current,
        # but power stays 0W for extended period, the car is full (BMS refusing)
        if (power.ev_connected and not power.ev_charging
                and power.ev_power < 50
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

        # EV consumption prediction
        predicted_daily = self._predictor.predict_ev_consumption_tomorrow(now)

        # Night charge skip calculation
        nights, charge_needed, skip_reason = self._ev_taper_detector.calculate_nights_until_charge(
            predicted_daily, self._cycle_vehicle_soc,
        )

        # Track consecutive skips for safety net (once per night, not every cycle)
        if self.time_manager.is_night_mode() and power.ev_connected:
            if not charge_needed:
                if not getattr(self, '_skip_recorded_tonight', False):
                    self._ev_taper_detector.record_skip()
                    self._skip_recorded_tonight = True
            else:
                self._ev_taper_detector.reset_skips()
                self._skip_recorded_tonight = False
        elif not self.time_manager.is_night_mode():
            self._skip_recorded_tonight = False

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
            nights_until_charge=nights,
            charge_needed=charge_needed,
            ev_battery_health_pct=self._ev_taper_detector.battery_health_pct,
            charge_skip_reason=skip_reason,
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

            predicted = getattr(self, '_predictor', None)
            predicted_daily = predicted.predict_ev_consumption_tomorrow(dt_util.now()) if predicted else 0
            nights, charge_needed, skip_reason = detector.calculate_nights_until_charge(
                predicted_daily, per_charger_vehicle_soc,
            )
            taper_data = detector.get_taper_data() if hasattr(detector, 'get_taper_data') else None

            result[cid] = {
                "estimated_soc": round(soc, 1) if soc is not None else None,
                "nights_until_charge": nights,
                "charge_needed": charge_needed,
                "charge_skip_reason": skip_reason,
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

        # Battery status
        if power.battery_charge_power > 50:
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
        _LOGGER.info("Configuration updated: %s", list(config_update.keys()))

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
