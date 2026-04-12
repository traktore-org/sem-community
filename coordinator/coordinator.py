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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from ..const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_BATTERY_CAPACITY_KWH,
    ChargingState,
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
from ..analytics.pv_performance import PVPerformanceAnalyzer
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

        # Initialize modules
        self._sensor_reader = SensorReader(hass, config)
        self._energy_calculator = EnergyCalculator(config, self.time_manager)
        self._flow_calculator = FlowCalculator()
        self._state_machine = ChargingStateMachine(hass, config, self.time_manager)
        self._ev_device = None  # Set by __init__.py after EV device registration
        self._ev_last_change_time = None  # Reactive control timing
        self._ev_charge_started_at = None  # Disable delay: min hold timer to prevent cycling
        self._ev_enable_surplus_since = None  # Enable delay: surplus must persist before starting
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
        else:
            self._tariff_provider = StaticTariffProvider(
                ht_rate=config.get("electricity_import_rate", 0.3387),
                nt_rate=config.get("electricity_nt_rate", 0.3387),
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

        # EV stall detection for self-healing
        self._ev_stalled_since: Optional[float] = None

        # Session cost tracking
        self._session_data = SessionData()
        self._last_ev_connected = False

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
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, "sem")},
            name="SEM",
            manufacturer="Home Assistant",
            model="Solar EV Charging Controller",
            sw_version="1.2.0",
            configuration_url="https://github.com/traktore-org/solar_energy_management",
        )

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

            # Restore device runtimes from storage
            self._restore_device_runtimes()

            # Restore EV session state (survives restarts)
            self._restore_ev_session_state()

            # Ensure battery discharge limit is restored after restart
            # (protects against stale limit left by previous run)
            await self._restore_battery_discharge_limit_on_startup()

        # Run deployment health check once after startup
        if self._initial_update_done and not getattr(self, '_health_checked', False):
            self._health_checked = True
            issues = []
            if not self._ev_device:
                issues.append("EV device not registered (KEBA not discovered)")
            if not self._storage or not self._storage.is_loaded:
                issues.append("Storage not loaded")
            if self.hass.states.get("sensor.sem_solar_power") is None:
                issues.append("Solar power sensor missing")
            if issues:
                _LOGGER.warning("SEM health check: %s", "; ".join(issues))
            else:
                _LOGGER.info("SEM health check: all OK (EV=%s)", self._ev_device.name if self._ev_device else "none")

        # Read observer mode from switch entity (allows runtime toggle)
        observer_state = self.hass.states.get("switch.sem_observer_mode")
        if observer_state is not None:
            self._observer_mode = observer_state.state == "on"

        try:
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
            self._update_session_tracking(power, power_flows)

            # Step 5: Calculate energy flows (daily totals for Sankey)
            energy_flows = self._flow_calculator.calculate_energy_flows(energy)

            # Step 6: Calculate available power for EV
            available_power = self._flow_calculator.calculate_available_power(power)
            calculated_current = self._flow_calculator.calculate_charging_current(available_power)

            # Step 7: Update charging state machine (mode selection only)
            charging_context = self._build_charging_context(power, energy, available_power, calculated_current)
            charging_state = self._state_machine.update_state(charging_context)

            # Step 7.5a: Unified EV control via CurrentControlDevice
            # Retry EV device setup if it failed during startup (KEBA race condition)
            if not self._ev_device and not hasattr(self, '_ev_retry_count'):
                self._ev_retry_count = 0
            if not self._ev_device and getattr(self, '_ev_retry_count', 0) < 30:
                self._ev_retry_count = getattr(self, '_ev_retry_count', 0) + 1
                try:
                    await self._retry_ev_device_setup()
                except Exception as e:
                    _LOGGER.debug(f"EV device retry {self._ev_retry_count}/30: {e}")

            if self._ev_device and not self._observer_mode:
                try:
                    await self._execute_ev_control(
                        charging_state, power, energy, charging_context
                    )
                    # Persist EV session state after each control cycle
                    self._save_ev_session_state()
                except Exception as e:
                    _LOGGER.error(f"EV control failed: {e}", exc_info=True)

            # Step 7.5c: Battery discharge protection (night charging)
            discharge_limit = None
            if not self._observer_mode:
                try:
                    discharge_limit = await self._apply_battery_discharge_protection(
                        charging_state, power
                    )
                except Exception as e:
                    _LOGGER.error("Battery discharge protection failed: %s", e)

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
                        ev_is_charging=False,  # EV controlled by _execute_ev_control
                        grid_import_w=power.grid_import_power,
                        ev_power_w=power.ev_power,
                    )
                except Exception as e:
                    _LOGGER.error(f"Load management processing failed: {e}")

            # Step 8: Update system status
            status = self._build_system_status(power, charging_state)

            # Step 9: Get load management data
            load_management = self._build_load_management_data(power)

            # Step 9a: Seed lifetime accumulators from hardware (runs once)
            if self._energy_dashboard_config and not self._energy_calculator._lifetime_seeded:
                self._energy_calculator.seed_lifetime_from_hardware(
                    self.hass, self._energy_dashboard_config
                )

            # Step 10: Read forecast data (Phase 0.3)
            forecast_data = ForecastSensorData()
            try:
                forecast = self._forecast_reader.read_forecast()
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
                    # Charging recommendation (Phase 3.2)
                    daily_ev_target = self.config.get("daily_ev_target", 10)
                    forecast_data.charging_recommendation = self._forecast_reader.get_charging_recommendation(
                        daily_ev_target, energy.daily_ev,
                    )
                    # Smart surplus window estimation
                    forecast_data.best_surplus_window = self._estimate_best_surplus_window(
                        forecast, power, energy
                    )
                    forecast_data.forecast_surplus_kwh = max(
                        0,
                        forecast.forecast_remaining_today_kwh
                        - (energy.daily_home * 0.5)  # rough remaining home need
                    )
            except Exception as e:
                _LOGGER.debug("Forecast read failed: %s", e)

            # Step 10a: Update forecast tracker (deviation + correction factor)
            try:
                weather_state = self.hass.states.get("weather.home") or self.hass.states.get("weather.openweathermap")
                weather_condition = weather_state.state if weather_state else "unknown"
                self._forecast_tracker.update(
                    forecast_data.forecast_today_kwh,
                    energy.daily_solar,
                    weather_condition,
                )
                # Apply correction to tomorrow's forecast
                tracker_data = self._forecast_tracker.get_data()
                tracker_data["forecast_corrected_tomorrow"] = self._forecast_tracker.apply_correction(
                    forecast_data.forecast_tomorrow_kwh
                )
            except Exception as e:
                _LOGGER.debug("Forecast tracker update failed: %s", e)
                tracker_data = {}

            # Step 10.1: Read tariff data (Phase 1)
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
                # Update energy calculator with dynamic rates
                self._energy_calculator._import_rate = tariff.current_import_rate
                self._energy_calculator._export_rate = tariff.current_export_rate
            except Exception as e:
                _LOGGER.debug("Tariff read failed: %s", e)

            # Step 10.2: Update surplus controller (Phase 0.2)
            surplus_data = SurplusControlData()
            try:
                price_level = tariff_data.tariff_price_level
                allocation = await self._surplus_controller.update(
                    available_power, price_level=price_level,
                )
                surplus_data.surplus_total_w = allocation.total_surplus_w
                surplus_data.surplus_distributable_w = allocation.distributable_surplus_w
                surplus_data.surplus_regulation_offset_w = allocation.regulation_offset_w
                surplus_data.surplus_allocated_w = allocation.allocated_w
                surplus_data.surplus_unallocated_w = allocation.unallocated_w
                surplus_data.surplus_active_devices = allocation.active_devices
                surplus_data.surplus_total_devices = allocation.total_devices
            except Exception as e:
                _LOGGER.debug("Surplus controller update failed: %s", e)

            # Step 10.2b: Accumulate device daily runtimes
            try:
                meter_day = dt_util.now().date()  # Midnight-based, matches HA Energy Dashboard
                for device in self._surplus_controller._devices.values():
                    device.update_daily_runtime(meter_day)
            except Exception as e:
                _LOGGER.debug("Device runtime update failed: %s", e)

            # Step 10.3: Update PV analytics (Phase 5)
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
            except Exception as e:
                _LOGGER.debug("PV analytics update failed: %s", e)

            # Step 10.4: Update energy assistant (Phase 6)
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
            except Exception as e:
                _LOGGER.debug("Energy assistant update failed: %s", e)

            # Step 10.5: Update utility signal monitor (Phase 7)
            utility_data = UtilitySignalSensorData()
            try:
                signal = self._utility_monitor.update(solar_power_w=power.solar_power)
                utility_data.utility_signal_active = signal.signal_active
                utility_data.utility_signal_source = signal.signal_source
                utility_data.utility_signal_count_today = signal.signal_count_today
            except Exception as e:
                _LOGGER.debug("Utility signal update failed: %s", e)

            # Heat pump data (Phase 2 - populated when heat pump device is registered)
            heat_pump_data = HeatPumpSensorData()

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
                last_update=dt_util.now(),
            )

            # Step 12: Send notifications on state change
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

            # Step 12.1: Event-based notifications
            try:
                # Battery full
                if power.battery_soc >= 99.5:
                    await self._notification_manager.notify_battery_full(power.battery_soc)

                # High grid import (>90% of peak limit)
                peak_pct = performance.current_vs_peak_percentage if hasattr(performance, 'current_vs_peak_percentage') else 0
                if peak_pct > 90:
                    grid_import_w = power.grid_import_power
                    await self._notification_manager.notify_high_grid_import(grid_import_w, peak_pct)

                # Daily summary at 20:00
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

                # Low forecast alert (evening, <5 kWh tomorrow)
                if (now.hour == 19
                        and forecast_data.forecast_tomorrow_kwh > 0
                        and forecast_data.forecast_tomorrow_kwh < 5):
                    await self._notification_manager.notify_forecast_alert(
                        forecast_data.forecast_tomorrow_kwh
                    )
            except Exception as e:
                _LOGGER.debug("Event notification failed: %s", e)

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
            except Exception:
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

            # Vehicle SOC (if configured)
            vehicle_soc_entity = self.config.get("vehicle_soc_entity", "")
            if vehicle_soc_entity:
                soc_state = self.hass.states.get(vehicle_soc_entity)
                if soc_state and soc_state.state not in ("unknown", "unavailable"):
                    try:
                        result["vehicle_soc"] = float(soc_state.state)
                    except (ValueError, TypeError):
                        pass

            # EV departure time (if configured via input_datetime entity)
            departure_entity = self.config.get("ev_departure_time_entity", "")
            if departure_entity:
                dep_state = self.hass.states.get(departure_entity)
                if dep_state and dep_state.state not in ("unknown", "unavailable"):
                    result["ev_departure_time"] = dep_state.state

            return result

        except Exception as e:
            _LOGGER.error(f"Error updating SEM data: {e}", exc_info=True)
            raise UpdateFailed(f"Update failed: {e}") from e

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
        self._surplus_controller.register_device(ev_device)
        self._ev_device = ev_device
        ev_device.managed_externally = True
        self._ev_retry_count = 999  # Stop retrying

        # Update sensor reader with discovered entities
        for key in ("ev_connected_sensor", "ev_charging_sensor", "ev_total_energy_sensor"):
            if ev_auto.get(key) and not self.config.get(key):
                self._sensor_reader._config[key] = ev_auto[key]

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

        vehicle_soc = None
        if vehicle_soc_entity:
            soc_state = self.hass.states.get(vehicle_soc_entity)
            if soc_state and soc_state.state not in ("unknown", "unavailable"):
                try:
                    vehicle_soc = float(soc_state.state)
                except (ValueError, TypeError):
                    pass

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
                except Exception:
                    pass  # Fallback to immediate charging

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

        # No meaningful solar → wait
        if power.solar_power < 200:
            return ("idle", f"solar={power.solar_power:.0f}W < 200W threshold")

        # SOC zone thresholds
        auto_start_soc = self.config.get("battery_auto_start_soc", 90)
        buffer_soc = self.config.get("battery_buffer_soc", 70)
        priority_soc = self.config.get("battery_priority_soc", 30)
        battery_floor = self.config.get("battery_assist_floor_soc", 60)
        battery_capacity = self.config.get("battery_capacity_kwh", DEFAULT_BATTERY_CAPACITY_KWH)

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
                forecast = self._forecast_reader.read_forecast()
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
            except Exception:
                pass

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
                forecast = self._forecast_reader.read_forecast()
                if forecast.available:
                    surplus_factor = 0.5
                    estimated_surplus = forecast.forecast_remaining_today_kwh * surplus_factor
                    reason += f" (forecast surplus={estimated_surplus:.1f}kWh, need={remaining_need:.1f}kWh)"
            except Exception:
                pass
            return ("solar_only", reason)

        # Zone 1: SOC < priority_soc → battery priority
        # State machine will route to SOLAR_PAUSE_LOW_BATTERY via battery_too_low flag
        return ("idle", f"Zone 1: SOC={power.battery_soc:.0f}% < priority={priority_soc}% — battery priority")

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
            forecast = self._forecast_reader.read_forecast()
            if forecast.available:
                forecast_remaining = forecast.forecast_remaining_today_kwh
        except Exception:
            pass

        battery_capacity = self.config.get("battery_capacity_kwh", DEFAULT_BATTERY_CAPACITY_KWH)
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
        forecast_reduction = self.hass.states.is_state("switch.sem_forecast_night_reduction", "on")
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
        if not self._storage or not self._ev_device:
            return
        state = self._storage.get_ev_session_state()
        if not state:
            return
        ev = self._ev_device
        ev._session_active = state.get("session_active", False)
        ev._current_setpoint = state.get("current_setpoint", 0.0)
        self._ev_last_change_time = None  # Don't restore — let cooldown expire
        _LOGGER.info(
            "Restored EV session: active=%s, setpoint=%.0fA",
            ev._session_active, ev._current_setpoint,
        )

    def _save_ev_session_state(self) -> None:
        """Persist EV session state to storage."""
        if not self._storage or not self._ev_device:
            return
        ev = self._ev_device
        self._storage.set_ev_session_state({
            "session_active": ev._session_active,
            "current_setpoint": ev._current_setpoint,
        })

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
