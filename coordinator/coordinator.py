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
    ChargingState,
    ENTITY_OBSERVER_MODE_SWITCH,
    ENTITY_SOLAR_POWER,
    ENTITY_SMART_NIGHT_CHARGING,
    WEATHER_ENTITY_CANDIDATES,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from ..utils.time_manager import TimeManager
from ..ha_energy_reader import read_energy_dashboard_config, EnergyDashboardConfig

from .types import (
    SEMData, PowerReadings, PowerFlows, SystemStatus, LoadManagementData,
    SurplusControlData, ForecastSensorData, TariffSensorData,
    HeatPumpSensorData, PVAnalyticsData, EnergyAssistantSensorData,
    UtilitySignalSensorData, SessionData,
)
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
        self._notification_manager = NotificationManager(hass, config)

        # Storage will be initialized with entry_id later
        self._storage: Optional[SEMStorage] = None

        # Energy Dashboard config
        self._energy_dashboard_config: Optional[EnergyDashboardConfig] = None

        # Phase 0: Surplus controller (always-on) & forecast reader
        regulation_offset = config.get("regulation_offset", 50)
        self._surplus_controller = SurplusController(hass, regulation_offset=regulation_offset)
        self._surplus_controller.max_export_w = config.get("max_export_power", 0)  # 0 = no limit
        self._forecast_reader = ForecastReader(
            hass,
            custom_entities=config.get("forecast_entities"),
        )
        self._forecast_tracker = ForecastTracker()

        # Phase 1: Tariff provider
        tariff_mode = config.get("tariff_mode", "static")
        # Price-responsive mode is automatic: enabled when using dynamic tariffs
        self._surplus_controller.price_responsive_mode = (tariff_mode == "dynamic")
        currency = hass.config.currency
        if tariff_mode == "dynamic":
            self._tariff_provider = DynamicTariffProvider(
                hass,
                price_entity=config.get("price_entity"),
                export_rate=config.get("electricity_export_rate", 0.075),
                cheap_threshold=config.get("cheap_price_threshold", 0.15),
                expensive_threshold=config.get("expensive_price_threshold", 0.35),
                currency=currency,
            )
        elif tariff_mode == "calendar":
            schedule = config.get("tariff_schedule", {})
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
            inverter_max_power_w=config.get("inverter_max_power_w", 10000.0),
            system_install_date=config.get("system_install_date"),
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

        # Hourly activity tracker for schedule card (#63)
        self._today_surplus_hours: list = [False] * 24
        self._today_ev_hours: list = [False] * 24
        self._tracker_date = None

        # Per-cycle caches (initialized here, populated in _async_update_data)
        self._cycle_forecast = None
        self._cycle_vehicle_soc: Optional[float] = None

        # EV stall detection for self-healing
        self._ev_stalled_since: Optional[float] = None

        # Session cost tracking (primary charger + per-charger dict)
        self._session_data = SessionData()
        self._session_data_per_charger: Dict[str, SessionData] = {}
        self._last_ev_connected = False
        self._last_ev_connected_per_charger: Dict[str, bool] = {}

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
        _LOGGER.info(f"SEM Coordinator initialized with {update_interval}s update interval")

    @property
    def battery_capacity_kwh(self) -> float:
        """Battery capacity in kWh — auto-detected or from config (#84)."""
        val = self.config.get("battery_capacity_kwh")
        if val is not None and val > 0:
            return float(val)
        if self._detected_battery_capacity_kwh is None:
            self._detected_battery_capacity_kwh = (
                self._sensor_reader.auto_detect_battery_capacity_kwh() or 0.0
            )
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

    async def async_initialize_energy_dashboard(self) -> bool:
        """Initialize sensors from HA Energy Dashboard."""
        try:
            dashboard_config = await read_energy_dashboard_config(self.hass)

            if dashboard_config and (dashboard_config.solar_power or dashboard_config.grid_import_power):
                self._energy_dashboard_config = dashboard_config
                self._sensor_reader.set_energy_dashboard_config(dashboard_config)
                _LOGGER.info(
                    f"Using Energy Dashboard sensors: "
                    f"solar={dashboard_config.solar_power}, "
                    f"grid={dashboard_config.grid_import_power}, "
                    f"battery={dashboard_config.battery_power}"
                )
            else:
                _LOGGER.info("Energy Dashboard not configured or incomplete")

        except Exception as e:
            _LOGGER.warning(f"Failed to read Energy Dashboard: {e}")

        # EV energy reconciliation disabled — keba_p30_charging_daily resets at
        # midnight but daily_ev resets at sunrise, causing misalignment after sunrise
        # where reconciliation imports the full midnight-based counter into the fresh
        # sunrise counter, making SEM think the target is already reached.
        # SEM's own power integration (10s cycles) is reliable enough.

        # Log EV sensor configuration
        ev_power = self._sensor_reader.config.ev_power_sensor
        ed_ev = getattr(self._energy_dashboard_config, 'ev_power', None) if self._energy_dashboard_config else None
        _LOGGER.info(
            "EV sensors: ed_power=%s, config_power=%s",
            ed_ev, ev_power,
        )

        return self._energy_dashboard_config is not None

    async def async_initialize_load_management(self, config_entry: ConfigEntry) -> None:
        """Initialize load management after coordinator is set up."""
        load_management_enabled = self.config.get("load_management_enabled", True)

        _LOGGER.debug(f"async_initialize_load_management called: enabled={load_management_enabled}")

        if load_management_enabled and not self._load_manager:
            try:
                from ..load_management import LoadManagementCoordinator

                _LOGGER.info("Creating LoadManagementCoordinator...")
                self._load_manager = LoadManagementCoordinator(self.hass, config_entry)
                await self._load_manager.async_initialize()
                _LOGGER.info(f"LoadManagementCoordinator initialized with {len(self._load_manager._devices)} devices")
            except Exception as e:
                _LOGGER.warning(f"Failed to initialize load management: {e}")
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

            # Seed EV intelligence from recorder history (improves cold starts
            # and upgrades from older versions without EV intelligence data)
            ev_power_entity = (
                self._sensor_reader.config.ev_power_sensor
                or (self._energy_dashboard_config.ev_power if self._energy_dashboard_config else None)
            )
            if ev_power_entity:
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
                        pass

            # Step 1: Read power values from sensors
            power = self._sensor_reader.read_power()

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
                for cid, ev_dev in self._ev_devices.items():
                    if cid not in self._session_data_per_charger:
                        self._session_data_per_charger[cid] = SessionData()
                    if cid not in self._last_ev_connected_per_charger:
                        self._last_ev_connected_per_charger[cid] = False
                    # Swap context for per-charger session tracking
                    saved_dev, saved_sess, saved_conn = (
                        self._ev_device, self._session_data, self._last_ev_connected
                    )
                    self._ev_device = ev_dev
                    self._session_data = self._session_data_per_charger[cid]
                    self._last_ev_connected = self._last_ev_connected_per_charger[cid]
                    self._update_session_tracking(power, power_flows)
                    # Save back per-charger state
                    self._session_data_per_charger[cid] = self._session_data
                    self._last_ev_connected_per_charger[cid] = self._last_ev_connected
                    # Restore
                    self._ev_device, self._session_data, self._last_ev_connected = (
                        saved_dev, saved_sess, saved_conn
                    )
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

            # Step 4.6: EV taper detection and intelligence (#106)
            ev_intelligence = self._update_ev_intelligence(power, energy)
            self._last_ev_intelligence = ev_intelligence  # For notifications (#106)

            # Step 5: Calculate energy flows (daily totals for Sankey)
            energy_flows = self._flow_calculator.calculate_energy_flows(energy)

            # Step 6: Calculate available power for EV
            available_power = self._flow_calculator.calculate_available_power(power)
            calculated_current = self._flow_calculator.calculate_charging_current(available_power)

            # Step 7: Update charging state machine (mode selection only)
            charging_context = self._build_charging_context(power, energy, available_power, calculated_current)
            charging_state = self._state_machine.update_state(charging_context)

            # Step 7.5a: Unified EV control via CurrentControlDevice
            # Multi-charger (#112): control each charger in priority order
            if not self._ev_device and not self._ev_devices:
                await self._retry_ev_device_with_backoff()

            if self._ev_devices and not self._observer_mode:
                # Multi-charger (#112): distribute budget + night target
                ev_budget_per_charger = {}
                num_chargers = len(self._ev_devices)

                # Night target: split equally across connected chargers
                if num_chargers > 1 and charging_state == ChargingState.NIGHT_CHARGING_ACTIVE:
                    connected_count = sum(
                        1 for d in self._ev_devices.values()
                        if getattr(d, '_session_active', False) or power.ev_connected
                    )
                    if connected_count > 1:
                        per_charger_night_kwh = charging_context.night_target_kwh / connected_count
                        self._night_target_per_charger = per_charger_night_kwh
                    else:
                        self._night_target_per_charger = None
                else:
                    self._night_target_per_charger = None

                # Solar budget: distribute by priority
                if num_chargers > 1 and charging_state in (
                    ChargingState.SOLAR_CHARGING_ACTIVE,
                    ChargingState.SOLAR_SUPER_CHARGING,
                    ChargingState.SOLAR_CHARGING_ALLOWED,
                    ChargingState.SOLAR_MIN_PV,
                ):
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
                for cid, ev_dev in sorted_chargers:
                    # Save coordinator-level state, swap in per-charger state
                    saved = {
                        "dev": self._ev_device,
                        "stalled": self._ev_stalled_since,
                        "enable": self._ev_enable_surplus_since,
                        "started": self._ev_charge_started_at,
                        "change": self._ev_last_change_time,
                    }
                    self._ev_device = ev_dev
                    self._ev_stalled_since = self._ev_stalled_since_per_charger.get(cid)
                    self._ev_enable_surplus_since = self._ev_enable_surplus_per_charger.get(cid)
                    self._ev_charge_started_at = self._ev_charge_started_per_charger.get(cid)
                    self._ev_last_change_time = self._ev_last_change_per_charger.get(cid)
                    self._current_charger_budget = ev_budget_per_charger.get(cid)
                    try:
                        await self._execute_ev_control(
                            charging_state, power, energy, charging_context
                        )
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
                        self._ev_device = saved["dev"]
                        self._ev_stalled_since = saved["stalled"]
                        self._ev_enable_surplus_since = saved["enable"]
                        self._ev_charge_started_at = saved["started"]
                        self._ev_last_change_time = saved["change"]
                        self._current_charger_budget = None
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
                    power, energy, energy_flows, performance, available_power,
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
                available_power=available_power,
                calculated_current=calculated_current,
                surplus_control=surplus_data,
                forecast=forecast_data,
                tariff=tariff_data,
                heat_pump=heat_pump_data,
                pv_analytics=pv_data,
                energy_assistant=assistant_data,
                utility_signal=utility_data,
                session=self._session_data,
                sessions=self._session_data_per_charger,
                currency=self.hass.config.currency or "EUR",
                ev_charger_count=len(self._ev_devices),
                ev_charger_ids=list(self._ev_devices.keys()),
                ev_intelligence=ev_intelligence,
                last_update=dt_util.now(),
            )

            # Step 12: Notifications (extracted for readability, #29)
            await self._send_notifications(
                charging_state, power, energy, costs, performance,
                charging_context, forecast_data, discharge_limit,
                calculated_current, available_power,
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
                await self._storage.async_save_energy_delayed()

            self._initial_update_done = True
            result = sem_data.to_dict()

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

            # Vehicle SOC (from per-cycle cache)
            if self._cycle_vehicle_soc is not None:
                result["vehicle_soc"] = self._cycle_vehicle_soc

            # EV departure time (if configured via input_datetime entity)
            departure_entity = self.config.get("ev_departure_time_entity", "")
            if departure_entity:
                dep_state = self.hass.states.get(departure_entity)
                if dep_state and dep_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    result["ev_departure_time"] = dep_state.state

            # Tariff schedule for dashboard card (#25)
            if hasattr(self._tariff_provider, 'get_schedule_for_day'):
                result["tariff_schedule_today"] = self._tariff_provider.get_schedule_for_day()

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
            _LOGGER.error(f"Error updating SEM data: {e}", exc_info=True)
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
                forecast_sig = f"{forecast.forecast_remaining_today_kwh:.1f}:{forecast.peak_time_today}"
                if forecast_sig != getattr(self, '_last_forecast_sig', ''):
                    self._last_forecast_sig = forecast_sig
                    self._cached_surplus_window = self._estimate_best_surplus_window(
                        forecast, power, energy
                    )
                forecast_data.best_surplus_window = getattr(self, '_cached_surplus_window', '')
                forecast_data.forecast_surplus_kwh = max(
                    0, forecast.forecast_remaining_today_kwh - (energy.daily_home * 0.5)
                )
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Forecast data parsing error: %s", e)
        except AttributeError as e:
            _LOGGER.debug("Forecast source not available: %s", e)

        # Forecast tracker
        tracker_data = {}
        try:
            weather_state = None
            for candidate in WEATHER_ENTITY_CANDIDATES:
                weather_state = self.hass.states.get(candidate)
                if weather_state:
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
            self._energy_calculator._import_rate = tariff.current_import_rate
            self._energy_calculator._export_rate = tariff.current_export_rate
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
                forecast_remaining_kwh=forecast_data.forecast_remaining_today_kwh,
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
            # EV Intelligence notifications (#106)
            ev_intel = getattr(self, '_last_ev_intelligence', None)
            if ev_intel:
                # 1. Nearly full: taper detector shows < 5 minutes remaining
                if (ev_intel.taper.minutes_to_full > 0
                        and ev_intel.taper.minutes_to_full < 5
                        and power.ev_charging):
                    await self._notification_manager.notify_ev_nearly_full(
                        ev_intel.taper.minutes_to_full
                    )

                # 2. Night charge skipped: night mode, EV connected, skip decided
                if (self.time_manager.is_night_mode()
                        and power.ev_connected
                        and not ev_intel.charge_needed
                        and ev_intel.estimated_soc_pct > 0):
                    await self._notification_manager.notify_ev_charge_skip(
                        ev_intel.estimated_soc_pct,
                        ev_intel.nights_until_charge,
                    )

                # 3. Charge recommended: night mode, SOC low, charge needed
                if (self.time_manager.is_night_mode()
                        and power.ev_connected
                        and ev_intel.charge_needed
                        and ev_intel.estimated_soc_pct < 30
                        and ev_intel.estimated_soc_pct > 0):
                    await self._notification_manager.notify_ev_charge_recommended(
                        ev_intel.estimated_soc_pct
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

    def _determine_charging_strategy(self, power: PowerReadings, energy: Any) -> tuple:
        """SOC-zone-based charging strategy decision (inspired by evcc).

        SOC Zones:
          Zone 4: SOC >= auto_start_soc (90%) — full battery assist, start EV even without surplus
          Zone 3: SOC >= buffer_soc (70%)     — battery can discharge to bridge gaps
          Zone 2: SOC >= priority_soc (30%)   — surplus only, no battery discharge
          Zone 1: SOC < priority_soc (30%)    — battery priority, EV blocked

        Returns: (strategy, reason) where strategy is one of:
            "solar_only", "battery_assist", "night_grid", "idle"
        """
        daily_target = self.config.get("daily_ev_target", 10)

        # Vehicle SOC-based remaining calculation (if configured)
        vehicle_soc_entity = self.config.get("vehicle_soc_entity", "")
        ev_battery_capacity = self.config.get("ev_battery_capacity_kwh", 40)
        ev_target_soc = self.config.get("ev_target_soc", 80)

        vehicle_soc = self._cycle_vehicle_soc

        if vehicle_soc is not None:
            # SOC-based: remaining = (target_soc - current_soc) / 100 * capacity
            remaining_need = max(0, (ev_target_soc - vehicle_soc) / 100 * ev_battery_capacity)
        else:
            # Fallback: fixed kWh target
            remaining_need = max(0, daily_target - energy.daily_ev)

        # EV not connected → idle
        if not power.ev_connected:
            return ("idle", f"ev disconnected")

        # Night mode → grid charging, but only if target not reached
        if self.time_manager.is_night_mode():
            if remaining_need < 0.5:
                soc_info = f", SOC={vehicle_soc:.0f}%" if vehicle_soc is not None else ""
                return ("idle", f"night target reached ({energy.daily_ev:.1f}kWh{soc_info})")

            soc_info = f", SOC={vehicle_soc:.0f}%→{ev_target_soc}%" if vehicle_soc is not None else ""

            # Price-optimized: check if current hour is cheap enough for charging
            tariff = getattr(self, '_tariff_provider', None)
            if tariff and hasattr(tariff, 'find_cheapest_hours'):
                try:
                    ev_max_power = self.config.get("ev_night_initial_current", 10) * 3 * 230 / 1000  # kW
                    hours_needed = max(1, int(remaining_need / ev_max_power + 0.5))
                    cheapest = tariff.find_cheapest_hours(hours_needed, within_hours=12)
                    if cheapest:
                        now = dt_util.now()
                        is_cheap_hour = any(
                            p.timestamp <= now < p.timestamp + timedelta(hours=1)
                            for p in cheapest
                        )
                        if not is_cheap_hour:
                            cheap_start = cheapest[0].timestamp.strftime("%H:%M")
                            return ("idle", f"night: waiting for cheaper hour (next: {cheap_start}){soc_info}")
                except (ValueError, TypeError, AttributeError) as e:
                    _LOGGER.debug("Price optimization unavailable, falling back to immediate charging: %s", e)

            return ("night_grid", f"night mode, remaining={remaining_need:.1f}kWh{soc_info}")

        # Solar mode: keep charging even past target (free surplus)
        # Target check only applies to night (grid) charging above

        # Charging mode selection: pv (default), minpv, now, off
        charging_mode = self.config.get("ev_charging_mode", "pv")
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

        # Zone 4: SOC >= auto_start_soc → always battery_assist
        # Battery is full enough to start EV even without surplus
        if power.battery_soc >= auto_start_soc:
            usable_battery = max(0, (power.battery_soc - battery_floor) / 100 * battery_capacity)
            return (
                "battery_assist",
                f"Zone 4: SOC={power.battery_soc:.0f}% >= auto_start={auto_start_soc}% — "
                f"full battery assist (usable={usable_battery:.1f}kWh)"
            )

        # Zone 3: SOC >= buffer_soc → battery can discharge to bridge gaps
        if power.battery_soc >= buffer_soc:
            # Use forecast if available to check if surplus alone is enough
            try:
                forecast = self._cycle_forecast
                if forecast.available:
                    surplus_factor = 0.5
                    estimated_surplus = forecast.forecast_remaining_today_kwh * surplus_factor
                    if estimated_surplus >= remaining_need * 1.5:
                        # Plenty of solar ahead — solar_only is fine
                        return (
                            "solar_only",
                            f"Zone 3: SOC={power.battery_soc:.0f}% >= buffer={buffer_soc}%, "
                            f"forecast surplus {estimated_surplus:.1f}kWh >> need {remaining_need:.1f}kWh"
                        )
            except Exception as e:
                _LOGGER.debug("Forecast unavailable in charging strategy: %s", e)

            # Battery assist: bridge gaps when surplus alone won't reach KEBA minimum
            usable_battery = max(0, (power.battery_soc - battery_floor) / 100 * battery_capacity)
            return (
                "battery_assist",
                f"Zone 3: SOC={power.battery_soc:.0f}% >= buffer={buffer_soc}% — "
                f"discharge assist (usable={usable_battery:.1f}kWh, need={remaining_need:.1f}kWh)"
            )

        # Zone 2: priority_soc <= SOC < buffer_soc → surplus only
        # Battery still needs charge, only use pure surplus (+ forecast-aware redirect in flow_calculator)
        if power.battery_soc >= priority_soc:
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
                    estimated_surplus = forecast.forecast_remaining_today_kwh * surplus_factor
                    reason += f" (forecast surplus={estimated_surplus:.1f}kWh, need={remaining_need:.1f}kWh)"
            except Exception as e:
                _LOGGER.debug("Forecast unavailable in charging strategy: %s", e)
            return ("solar_only", reason)

        # Zone 1: SOC < priority_soc → battery priority
        # State machine will route to SOLAR_PAUSE_LOW_BATTERY via battery_too_low flag
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
                remaining_solar = self._forecast_tracker.apply_correction(remaining_solar)
            except (ValueError, AttributeError):
                pass

        if remaining_need < 0.5:
            return ("idle", "auto: EV target reached")

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

    def _get_zone(self, soc: float) -> int:
        """Get SOC zone number for logging."""
        auto_start = self.config.get("battery_auto_start_soc", 90)
        buffer = self.config.get("battery_buffer_soc", 70)
        priority = self.config.get("battery_priority_soc", 30)
        if soc >= auto_start: return 4
        if soc >= buffer: return 3
        if soc >= priority: return 2
        return 1

    def _build_charging_context(
        self,
        power: PowerReadings,
        energy: Any,
        available_power: float,
        calculated_current: float
    ) -> ChargingContext:
        """Build charging context for state machine.

        Assembles all inputs the state machine needs: battery flags, EV budget,
        charging strategy (from SOC zones), and night-specific fields (NT period,
        night end time, EV max power, forecast-adjusted night target).

        Args:
            power: Current sensor readings.
            energy: Daily/monthly energy totals.
            available_power: Surplus power for non-EV devices (W).
            calculated_current: Available current from surplus calculation (A).

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
        daily_ev_target = self.config.get("daily_ev_target", 10)

        battery_too_low = power.battery_soc < battery_min_soc
        battery_needs_priority = power.battery_soc < battery_priority_soc
        daily_target_reached = energy.daily_ev >= daily_ev_target

        # Calculate excess solar
        excess_solar = power.solar_power - power.home_consumption_power - power.battery_charge_power

        # Use EV budget (with battery redirect) instead of surplus-style available_power
        forecast_remaining = 0
        try:
            forecast = self._cycle_forecast
            if forecast.available:
                forecast_remaining = forecast.forecast_remaining_today_kwh
        except Exception:
            pass

        battery_capacity = self.battery_capacity_kwh
        ev_budget = self._flow_calculator.calculate_ev_budget(
            power, forecast_remaining, power.battery_soc, battery_capacity,
        )
        ev_current = self._flow_calculator.calculate_charging_current(ev_budget)

        # Forecast-driven charging strategy
        strategy, reason = self._determine_charging_strategy(power, energy)

        _LOGGER.debug(
            "Charging strategy: %s — %s",
            strategy, reason,
        )

        remaining = max(0, daily_ev_target - energy.daily_ev)

        # Night charging target: optionally reduced by forecast
        night_target = remaining
        forecast_reduction = self.hass.states.is_state(f"switch.{ENTITY_SMART_NIGHT_CHARGING}", "on")
        if self.time_manager.is_night_mode() and forecast_reduction:
            night_target = self._calculate_forecast_night_target(
                remaining, energy,
            )

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
        )

    def _restore_ev_session_state(self) -> None:
        """Restore EV session state from storage on startup."""
        if not self._storage:
            return
        state = self._storage.get_ev_session_state()
        if not state:
            return

        # Multi-charger (#112): restore all chargers
        if self._ev_devices:
            per_charger = state.get("chargers", {})
            for cid, ev_dev in self._ev_devices.items():
                cstate = per_charger.get(cid, state if cid == next(iter(self._ev_devices)) else {})
                ev_dev._session_active = cstate.get("session_active", False)
                ev_dev._current_setpoint = cstate.get("current_setpoint", 0.0)
                _LOGGER.info(
                    "Restored EV session for %s: active=%s, setpoint=%.0fA",
                    ev_dev.name, ev_dev._session_active, ev_dev._current_setpoint,
                )
        elif self._ev_device:
            ev = self._ev_device
            ev._session_active = state.get("session_active", False)
            ev._current_setpoint = state.get("current_setpoint", 0.0)
            _LOGGER.info(
                "Restored EV session: active=%s, setpoint=%.0fA",
                ev._session_active, ev._current_setpoint,
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
                per_charger[cid] = {
                    "session_active": ev_dev._session_active,
                    "current_setpoint": ev_dev._current_setpoint,
                }
            # Also save primary charger at top level for backward compat
            primary = next(iter(self._ev_devices.values()))
            self._storage.set_ev_session_state({
                "session_active": primary._session_active,
                "current_setpoint": primary._current_setpoint,
                "chargers": per_charger,
            })
        elif self._ev_device:
            ev = self._ev_device
            self._storage.set_ev_session_state({
                "session_active": ev._session_active,
                "current_setpoint": ev._current_setpoint,
            })

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
        if self._ev_devices and len(self._ev_devices) > 1:
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
                charger_connected = getattr(ev_dev, "_session_active", False) or power.ev_connected

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

        # Track energy since last full charge
        if hasattr(energy, "daily_ev"):
            ev_increment = power.ev_power * interval_hours / 1000
            self._ev_taper_detector.update_energy(ev_increment)

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

        # Virtual SOC (prefer real vehicle SOC if available)
        estimated_soc = self._ev_taper_detector.get_virtual_soc(self._cycle_vehicle_soc)

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

        return EVIntelligenceData(
            taper=taper_data,
            estimated_soc_pct=round(estimated_soc, 1),
            last_full_charge=self._ev_taper_detector.last_full_timestamp,
            energy_since_full_kwh=round(self._ev_taper_detector.energy_since_full, 2),
            predicted_daily_ev_kwh=predicted_daily,
            nights_until_charge=nights,
            charge_needed=charge_needed,
            ev_battery_health_pct=self._ev_taper_detector.battery_health_pct,
            charge_skip_reason=skip_reason,
        )

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
        """Update coordinator configuration."""
        self.config = {**self.config, **config_update}
        _LOGGER.info(f"Configuration updated: {list(config_update.keys())}")

    def sensors_ready(self) -> bool:
        """Check if required sensors are available."""
        return self._sensor_reader.sensors_ready()

    def _estimate_best_surplus_window(self, forecast, power, energy) -> str:
        """Estimate the best time window for running large appliances.

        Uses peak_time_today from forecast (if available) to suggest a window
        centered on peak solar production. Falls back to a generic midday
        window if no peak time data.
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

        # Fallback: estimate from remaining forecast
        remaining = forecast.forecast_remaining_today_kwh
        current_hour = now.hour

        if current_hour >= 17 or remaining < 1:
            # Evening or very little solar left
            if forecast.forecast_tomorrow_kwh > 5:
                return "tomorrow 10:00–14:00"
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

                # Recommendation based on state
                state = lm_info.get("state", "normal")
                if state == "emergency":
                    lm_data.load_management_recommendation = "Reduce load immediately!"
                elif state == "shedding":
                    lm_data.load_management_recommendation = "Reducing non-critical loads"
                elif state == "warning":
                    lm_data.load_management_recommendation = "Monitor - approaching peak limit"
                else:
                    lm_data.load_management_recommendation = "Normal operation"

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
                _LOGGER.debug(f"Could not get load management data: {e}")

        return lm_data
