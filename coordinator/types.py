"""Type definitions for SEM coordinator modules.

Key dataclasses:
- PowerReadings: Instantaneous sensor values with derived splits
- PowerFlows / EnergyFlows: Source-to-destination flow distribution
- EnergyTotals: Daily/monthly energy accumulators
- CostData: Import costs, savings, export revenue
- SessionData: Per-EV-session cost attribution and energy source tracking
- SEMData: Complete coordinator output (flat dict via to_dict())
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum


class EnergySource(Enum):
    """Energy data source."""
    HARDWARE = "hardware"
    CALCULATED = "calculated"
    MIXED = "mixed"


@dataclass
class PowerReadings:
    """Current power readings from sensors."""
    solar_power: float = 0.0
    grid_power: float = 0.0  # Negative = import, Positive = export
    battery_power: float = 0.0  # Positive = charge, Negative = discharge
    ev_power: float = 0.0
    home_consumption_power: float = 0.0

    # Derived values
    grid_import_power: float = 0.0
    grid_export_power: float = 0.0
    battery_charge_power: float = 0.0
    battery_discharge_power: float = 0.0

    # Battery state
    battery_soc: float = 0.0
    battery_temperature: float = 25.0

    # EV state
    ev_connected: bool = False
    ev_charging: bool = False

    # Timestamps
    timestamp: Optional[datetime] = None

    def calculate_derived(self) -> None:
        """Calculate derived power values from raw readings."""
        # Grid: negative = import, positive = export
        self.grid_import_power = max(0, -self.grid_power)
        self.grid_export_power = max(0, self.grid_power)

        # Battery: positive = charge, negative = discharge
        self.battery_charge_power = max(0, self.battery_power)
        self.battery_discharge_power = max(0, -self.battery_power)

        # Home consumption from energy balance
        energy_in = self.solar_power + self.grid_import_power + self.battery_discharge_power
        energy_out = self.ev_power + self.grid_export_power + self.battery_charge_power
        self.home_consumption_power = max(0, energy_in - energy_out)


@dataclass
class PowerFlows:
    """Power flow distribution between sources and destinations."""
    # Solar flows (W)
    solar_to_home: float = 0.0
    solar_to_battery: float = 0.0
    solar_to_ev: float = 0.0
    solar_to_grid: float = 0.0

    # Grid flows (W)
    grid_to_home: float = 0.0
    grid_to_ev: float = 0.0
    grid_to_battery: float = 0.0

    # Battery flows (W)
    battery_to_home: float = 0.0
    battery_to_ev: float = 0.0


@dataclass
class EnergyTotals:
    """Daily/monthly energy totals."""
    # Daily totals (kWh)
    daily_solar: float = 0.0
    daily_home: float = 0.0
    daily_ev: float = 0.0
    daily_grid_import: float = 0.0
    daily_grid_export: float = 0.0
    daily_battery_charge: float = 0.0
    daily_battery_discharge: float = 0.0

    # Monthly totals (kWh)
    monthly_solar: float = 0.0
    monthly_home: float = 0.0
    monthly_grid_import: float = 0.0
    monthly_grid_export: float = 0.0
    monthly_battery_charge: float = 0.0
    monthly_battery_discharge: float = 0.0

    # Yearly totals (kWh)
    yearly_solar: float = 0.0
    yearly_home: float = 0.0
    yearly_grid_import: float = 0.0
    yearly_grid_export: float = 0.0
    yearly_battery_charge: float = 0.0
    yearly_battery_discharge: float = 0.0
    yearly_ev: float = 0.0


@dataclass
class EnergyFlows:
    """Daily energy flow distribution (kWh)."""
    # Solar flows
    solar_to_home: float = 0.0
    solar_to_battery: float = 0.0
    solar_to_ev: float = 0.0
    solar_to_grid: float = 0.0

    # Grid flows
    grid_to_home: float = 0.0
    grid_to_ev: float = 0.0
    grid_to_battery: float = 0.0

    # Battery flows
    battery_to_home: float = 0.0
    battery_to_ev: float = 0.0


@dataclass
class CostData:
    """Cost and savings calculations."""
    daily_costs: float = 0.0
    daily_savings: float = 0.0
    daily_export_revenue: float = 0.0
    daily_net_cost: float = 0.0
    daily_battery_savings: float = 0.0

    monthly_costs: float = 0.0
    monthly_savings: float = 0.0
    monthly_export_revenue: float = 0.0
    monthly_net_cost: float = 0.0

    # Yearly costs
    yearly_costs: float = 0.0
    yearly_savings: float = 0.0
    yearly_battery_savings: float = 0.0
    yearly_export_revenue: float = 0.0
    yearly_net_cost: float = 0.0

    # Environmental impact
    daily_co2_avoided_kg: float = 0.0
    yearly_co2_avoided_kg: float = 0.0
    yearly_trees_equivalent: float = 0.0
    lifetime_co2_avoided_kg: float = 0.0
    lifetime_trees_equivalent: float = 0.0

    # ROI
    lifetime_total_savings: float = 0.0  # all-time savings (solar + export + battery)
    lifetime_grid_cost: float = 0.0  # all-time grid spend
    roi_percentage: float = 0.0  # savings / investment × 100
    roi_payback_years: float = 0.0  # estimated years to payback
    roi_annual_savings: float = 0.0  # projected annual savings rate


@dataclass
class PerformanceMetrics:
    """System performance metrics."""
    self_consumption_rate: float = 0.0  # % of solar used locally
    autarky_rate: float = 0.0  # % of consumption from own generation
    solar_efficiency: float = 0.0
    battery_efficiency: float = 0.0


@dataclass
class SystemStatus:
    """System status indicators."""
    grid_status: str = "idle"  # import, export, idle
    battery_status: str = "idle"  # charging, discharging, idle
    solar_active: bool = False
    ev_connected: bool = False
    ev_charging: bool = False
    battery_charging: bool = False
    battery_discharging: bool = False
    grid_export_active: bool = False


@dataclass
class LoadManagementData:
    """Load management and peak tracking data."""
    target_peak_limit: float = 5.0  # kW
    peak_margin: float = 0.5  # kW
    load_management_status: str = "idle"
    loads_currently_shed: str = "none"
    available_load_reduction: float = 0.0  # kW
    controllable_devices_count: int = 0
    consecutive_peak_15min: float = 0.0  # kW
    monthly_consecutive_peak: float = 0.0  # kW
    current_vs_peak_percentage: float = 0.0
    controlled_tariff_status: str = "unknown"
    load_management_recommendation: str = "none"
    power_charge_cost: float = 0.0
    peak_trend: str = "stable"
    tariff_type: str = "unknown"


@dataclass
class SurplusControlData:
    """Surplus controller state for coordinator data."""
    surplus_total_w: float = 0.0
    surplus_distributable_w: float = 0.0
    surplus_regulation_offset_w: float = 50.0
    surplus_allocated_w: float = 0.0
    surplus_unallocated_w: float = 0.0
    surplus_active_devices: int = 0
    surplus_total_devices: int = 0


@dataclass
class ForecastSensorData:
    """Forecast data for coordinator sensors."""
    forecast_today_kwh: float = 0.0
    forecast_tomorrow_kwh: float = 0.0
    forecast_remaining_today_kwh: float = 0.0
    forecast_power_now_w: float = 0.0
    forecast_power_next_hour_w: float = 0.0
    forecast_peak_power_today_w: float = 0.0
    forecast_peak_time_today: str = ""
    forecast_source: str = "none"
    forecast_available: bool = False
    charging_recommendation: str = "no_forecast"
    best_surplus_window: str = ""
    forecast_surplus_kwh: float = 0.0


@dataclass
class TariffSensorData:
    """Tariff data for coordinator sensors."""
    tariff_current_import_rate: float = 0.0
    tariff_current_export_rate: float = 0.0
    tariff_price_level: str = "normal"
    tariff_provider: str = "static"
    tariff_is_dynamic: bool = False
    tariff_today_min_price: Optional[float] = None
    tariff_today_max_price: Optional[float] = None
    tariff_today_avg_price: Optional[float] = None
    tariff_next_cheap_start: Optional[str] = None


@dataclass
class HeatPumpSensorData:
    """Heat pump data for coordinator sensors."""
    heat_pump_mode: str = "normal"
    heat_pump_sg_ready_state: int = 2
    heat_pump_solar_boost: bool = False


@dataclass
class PVAnalyticsData:
    """PV analytics data for coordinator sensors."""
    pv_daily_specific_yield: float = 0.0
    pv_performance_vs_forecast: float = 0.0
    pv_estimated_annual_degradation: float = 0.0
    pv_degradation_trend: str = "unknown"


@dataclass
class EnergyAssistantSensorData:
    """Energy assistant data for coordinator sensors."""
    energy_optimization_score: int = 0
    energy_tip: str = "No recommendations at this time"
    energy_tip_category: str = "none"
    energy_ev_solar_percentage: float = 0.0


@dataclass
class UtilitySignalSensorData:
    """Utility signal data for coordinator sensors."""
    utility_signal_active: bool = False
    utility_signal_source: str = "none"
    utility_signal_count_today: int = 0


@dataclass
class SessionData:
    """Per-session EV charging cost and energy attribution.

    Tracked by SEMCoordinator._update_session_tracking() each cycle.
    Session starts when ev_power > 50W, ends when EV disconnects.
    Data is kept after session ends for display until next session starts.

    Attributes:
        active: Whether a charging session is currently in progress.
        start_time: ISO-format timestamp of session start.
        duration_minutes: Elapsed time since session start.
        energy_kwh: Total energy delivered (solar + grid + battery).
        solar_energy_kwh: Energy from solar (via solar_to_ev flow).
        grid_energy_kwh: Energy from grid (via grid_to_ev flow).
        battery_energy_kwh: Energy from battery (via battery_to_ev flow).
        solar_share_pct: Percentage of energy from solar (0-100).
        cost_chf: Grid energy cost (grid_energy × import_rate).
        avg_power_w: Average charging power over session duration.
    """
    active: bool = False
    start_time: Optional[str] = None
    duration_minutes: float = 0
    energy_kwh: float = 0
    solar_energy_kwh: float = 0
    grid_energy_kwh: float = 0
    battery_energy_kwh: float = 0
    solar_share_pct: float = 0
    cost_chf: float = 0
    avg_power_w: float = 0


@dataclass
class SEMData:
    """Complete SEM data structure combining all components."""
    power: PowerReadings = field(default_factory=PowerReadings)
    power_flows: PowerFlows = field(default_factory=PowerFlows)
    energy: EnergyTotals = field(default_factory=EnergyTotals)
    energy_flows: EnergyFlows = field(default_factory=EnergyFlows)
    costs: CostData = field(default_factory=CostData)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    status: SystemStatus = field(default_factory=SystemStatus)
    load_management: LoadManagementData = field(default_factory=LoadManagementData)

    # Charging control
    charging_state: str = "idle"
    charging_strategy: str = "idle"
    charging_strategy_reason: str = ""
    available_power: float = 0.0
    calculated_current: float = 0.0

    # New phase data
    surplus_control: SurplusControlData = field(default_factory=SurplusControlData)
    forecast: ForecastSensorData = field(default_factory=ForecastSensorData)
    tariff: TariffSensorData = field(default_factory=TariffSensorData)
    heat_pump: HeatPumpSensorData = field(default_factory=HeatPumpSensorData)
    pv_analytics: PVAnalyticsData = field(default_factory=PVAnalyticsData)
    energy_assistant: EnergyAssistantSensorData = field(default_factory=EnergyAssistantSensorData)
    utility_signal: UtilitySignalSensorData = field(default_factory=UtilitySignalSensorData)

    # Session tracking
    session: SessionData = field(default_factory=SessionData)

    # Timestamps
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to flat dictionary for coordinator.data."""
        return {
            # Power readings
            "solar_power": self.power.solar_power,
            "grid_power": self.power.grid_power,
            "battery_power": self.power.battery_power,
            "ev_power": self.power.ev_power,
            "home_consumption_power": self.power.home_consumption_power,
            "grid_import_power": self.power.grid_import_power,
            "grid_export_power": self.power.grid_export_power,
            "battery_charge_power": self.power.battery_charge_power,
            "battery_discharge_power": self.power.battery_discharge_power,
            "battery_soc": self.power.battery_soc,
            "battery_temperature": self.power.battery_temperature,
            "ev_connected": self.power.ev_connected,
            "ev_charging": self.power.ev_charging,

            # Power flows
            "flow_solar_to_home_power": self.power_flows.solar_to_home,
            "flow_solar_to_battery_power": self.power_flows.solar_to_battery,
            "flow_solar_to_ev_power": self.power_flows.solar_to_ev,
            "flow_solar_to_grid_power": self.power_flows.solar_to_grid,
            "flow_grid_to_home_power": self.power_flows.grid_to_home,
            "flow_grid_to_ev_power": self.power_flows.grid_to_ev,
            "flow_grid_to_battery_power": self.power_flows.grid_to_battery,
            "flow_battery_to_home_power": self.power_flows.battery_to_home,
            "flow_battery_to_ev_power": self.power_flows.battery_to_ev,

            # Daily energy
            "daily_solar_energy": self.energy.daily_solar,
            "daily_home_energy": self.energy.daily_home,
            "daily_ev_energy": self.energy.daily_ev,
            "daily_grid_import_energy": self.energy.daily_grid_import,
            "daily_grid_export_energy": self.energy.daily_grid_export,
            "daily_battery_charge_energy": self.energy.daily_battery_charge,
            "daily_battery_discharge_energy": self.energy.daily_battery_discharge,

            # Monthly energy
            "monthly_solar_yield_energy": self.energy.monthly_solar,
            "monthly_home_consumption_energy": self.energy.monthly_home,
            "monthly_grid_import_energy": self.energy.monthly_grid_import,
            "monthly_grid_export_energy": self.energy.monthly_grid_export,
            "monthly_battery_charge_energy": self.energy.monthly_battery_charge,
            "monthly_battery_discharge_energy": self.energy.monthly_battery_discharge,

            # Yearly energy
            "yearly_solar_yield_energy": self.energy.yearly_solar,
            "yearly_home_consumption_energy": self.energy.yearly_home,
            "yearly_grid_import_energy": self.energy.yearly_grid_import,
            "yearly_grid_export_energy": self.energy.yearly_grid_export,
            "yearly_battery_charge_energy": self.energy.yearly_battery_charge,
            "yearly_battery_discharge_energy": self.energy.yearly_battery_discharge,
            "yearly_ev_energy": self.energy.yearly_ev,

            # Energy flows
            "flow_solar_to_home_energy": self.energy_flows.solar_to_home,
            "flow_solar_to_battery_energy": self.energy_flows.solar_to_battery,
            "flow_solar_to_ev_energy": self.energy_flows.solar_to_ev,
            "flow_solar_to_grid_energy": self.energy_flows.solar_to_grid,
            "flow_grid_to_home_energy": self.energy_flows.grid_to_home,
            "flow_grid_to_ev_energy": self.energy_flows.grid_to_ev,
            "flow_grid_to_battery_energy": self.energy_flows.grid_to_battery,
            "flow_battery_to_home_energy": self.energy_flows.battery_to_home,
            "flow_battery_to_ev_energy": self.energy_flows.battery_to_ev,

            # Costs
            "daily_costs": self.costs.daily_costs,
            "daily_savings": self.costs.daily_savings,
            "daily_export_revenue": self.costs.daily_export_revenue,
            "daily_net_cost": self.costs.daily_net_cost,
            "daily_battery_savings": self.costs.daily_battery_savings,
            "monthly_costs": self.costs.monthly_costs,
            "monthly_savings": self.costs.monthly_savings,
            "monthly_export_revenue": self.costs.monthly_export_revenue,
            "monthly_net_cost": self.costs.monthly_net_cost,
            # Yearly costs
            "yearly_costs": self.costs.yearly_costs,
            "yearly_savings": self.costs.yearly_savings,
            "yearly_battery_savings": self.costs.yearly_battery_savings,
            "yearly_export_revenue": self.costs.yearly_export_revenue,
            "yearly_net_cost": self.costs.yearly_net_cost,

            # Environmental impact
            "daily_co2_avoided": self.costs.daily_co2_avoided_kg,
            "yearly_co2_avoided": self.costs.yearly_co2_avoided_kg,
            "yearly_trees_equivalent": self.costs.yearly_trees_equivalent,
            "lifetime_co2_avoided": self.costs.lifetime_co2_avoided_kg,
            "lifetime_trees_equivalent": self.costs.lifetime_trees_equivalent,

            # ROI
            "lifetime_total_savings": self.costs.lifetime_total_savings,
            "lifetime_grid_cost": self.costs.lifetime_grid_cost,
            "roi_percentage": self.costs.roi_percentage,
            "roi_payback_years": self.costs.roi_payback_years,
            "roi_annual_savings": self.costs.roi_annual_savings,

            # Financial additions
            "battery_discharge_value": self.costs.daily_battery_savings,
            "monthly_battery_savings": self.costs.monthly_savings * 0.3,  # Estimate 30% from battery

            # Performance
            "self_consumption_rate": self.performance.self_consumption_rate,
            "autarky_rate": self.performance.autarky_rate,
            "solar_efficiency": self.performance.solar_efficiency,
            "battery_efficiency": self.performance.battery_efficiency,

            # Status
            "grid_status": self.status.grid_status,
            "battery_status": self.status.battery_status,
            "sem_solar_active": self.status.solar_active,
            "sem_ev_connected": self.status.ev_connected,
            "sem_ev_charging": self.status.ev_charging,
            "sem_battery_charging": self.status.battery_charging,
            "sem_battery_discharging": self.status.battery_discharging,
            "sem_grid_export_active": self.status.grid_export_active,

            # Charging control
            "charging_state": self.charging_state,
            "charging_strategy": self.charging_strategy,
            "charging_strategy_reason": self.charging_strategy_reason,
            "available_power": self.available_power,
            "calculated_current": self.calculated_current,

            # EV aliases and routing
            "ev_charging_power": self.power.ev_power,
            "ev_max_current": self.calculated_current,
            "ev_max_current_available": self.calculated_current,

            # Status sensors (derived from charging_state)
            "solar_charging_status": self._get_solar_charging_status(),
            "night_charging_status": self._get_night_charging_status(),
            "battery_priority_status": self._get_battery_priority_status(),
            "solar_optimization_status": "active" if self.power.solar_power > 50 else "idle",
            "grid_management_status": self.status.grid_status,

            # Legacy aliases for compatibility
            "solar_production_total": self.power.solar_power,

            # Load management
            "target_peak_limit": self.load_management.target_peak_limit,
            "peak_margin": self.load_management.peak_margin,
            "load_management_status": self.load_management.load_management_status,
            "loads_currently_shed": self.load_management.loads_currently_shed,
            "available_load_reduction": self.load_management.available_load_reduction,
            "controllable_devices_count": self.load_management.controllable_devices_count,
            "consecutive_peak_15min": self.load_management.consecutive_peak_15min,
            "monthly_consecutive_peak": self.load_management.monthly_consecutive_peak,
            "current_vs_peak_percentage": self.load_management.current_vs_peak_percentage,
            "controlled_tariff_status": self.load_management.controlled_tariff_status,
            "load_management_recommendation": self.load_management.load_management_recommendation,
            "power_charge_cost": self.load_management.power_charge_cost,
            "peak_trend": self.load_management.peak_trend,
            "tariff_type": self.load_management.tariff_type,

            # Timestamp
            "last_update": self.last_update,

            # Surplus controller (Phase 0)
            "surplus_total_w": self.surplus_control.surplus_total_w,
            "surplus_distributable_w": self.surplus_control.surplus_distributable_w,
            "surplus_regulation_offset_w": self.surplus_control.surplus_regulation_offset_w,
            "surplus_allocated_w": self.surplus_control.surplus_allocated_w,
            "surplus_unallocated_w": self.surplus_control.surplus_unallocated_w,
            "surplus_active_devices": self.surplus_control.surplus_active_devices,
            "surplus_total_devices": self.surplus_control.surplus_total_devices,

            # Forecast (Phase 0)
            "forecast_today_kwh": self.forecast.forecast_today_kwh,
            "forecast_tomorrow_kwh": self.forecast.forecast_tomorrow_kwh,
            "forecast_remaining_today_kwh": self.forecast.forecast_remaining_today_kwh,
            "forecast_power_now_w": self.forecast.forecast_power_now_w,
            "forecast_power_next_hour_w": self.forecast.forecast_power_next_hour_w,
            "forecast_peak_power_today_w": self.forecast.forecast_peak_power_today_w,
            "forecast_peak_time_today": self.forecast.forecast_peak_time_today,
            "forecast_source": self.forecast.forecast_source,
            "forecast_available": self.forecast.forecast_available,
            "charging_recommendation": self.forecast.charging_recommendation,
            "best_surplus_window": self.forecast.best_surplus_window,
            "forecast_surplus_kwh": self.forecast.forecast_surplus_kwh,

            # Tariff (Phase 1)
            "tariff_current_import_rate": self.tariff.tariff_current_import_rate,
            "tariff_current_export_rate": self.tariff.tariff_current_export_rate,
            "tariff_price_level": self.tariff.tariff_price_level,
            "tariff_provider": self.tariff.tariff_provider,
            "tariff_is_dynamic": self.tariff.tariff_is_dynamic,
            "tariff_today_min_price": self.tariff.tariff_today_min_price,
            "tariff_today_max_price": self.tariff.tariff_today_max_price,
            "tariff_today_avg_price": self.tariff.tariff_today_avg_price,
            "tariff_next_cheap_start": self.tariff.tariff_next_cheap_start,

            # Heat pump (Phase 2)
            "heat_pump_mode": self.heat_pump.heat_pump_mode,
            "heat_pump_sg_ready_state": self.heat_pump.heat_pump_sg_ready_state,
            "heat_pump_solar_boost": self.heat_pump.heat_pump_solar_boost,

            # PV analytics (Phase 5)
            "pv_daily_specific_yield": self.pv_analytics.pv_daily_specific_yield,
            "pv_performance_vs_forecast": self.pv_analytics.pv_performance_vs_forecast,
            "pv_estimated_annual_degradation": self.pv_analytics.pv_estimated_annual_degradation,
            "pv_degradation_trend": self.pv_analytics.pv_degradation_trend,

            # Energy assistant (Phase 6)
            "energy_optimization_score": self.energy_assistant.energy_optimization_score,
            "energy_tip": self.energy_assistant.energy_tip,
            "energy_tip_category": self.energy_assistant.energy_tip_category,
            "energy_ev_solar_percentage": self.energy_assistant.energy_ev_solar_percentage,

            # Utility signals (Phase 7)
            "utility_signal_active": self.utility_signal.utility_signal_active,
            "utility_signal_source": self.utility_signal.utility_signal_source,
            "utility_signal_count_today": self.utility_signal.utility_signal_count_today,

            # Session tracking
            "session_active": self.session.active,
            "session_energy": self.session.energy_kwh,
            "session_solar_share": self.session.solar_share_pct,
            "session_cost": self.session.cost_chf,
            "session_duration": self.session.duration_minutes,
            "session_solar_energy": self.session.solar_energy_kwh,
            "session_grid_energy": self.session.grid_energy_kwh,
            "session_battery_energy": self.session.battery_energy_kwh,
            "session_avg_power": self.session.avg_power_w,
        }

    def _get_solar_charging_status(self) -> str:
        """Get solar charging status from charging state."""
        solar_states = ["solar_charging_active", "solar_super_charging", "solar_target_reached", "solar_min_pv"]
        if self.charging_state in solar_states:
            return "active"
        elif "solar" in self.charging_state.lower():
            return self.charging_state.replace("solar_", "")
        return "idle"

    def _get_night_charging_status(self) -> str:
        """Get night charging status from charging state."""
        night_states = ["night_charging_active", "night_target_reached"]
        if self.charging_state in night_states:
            return "active"
        elif "night" in self.charging_state.lower():
            return self.charging_state.replace("night_", "")
        return "idle"


    def _get_battery_priority_status(self) -> str:
        """Get battery priority status from charging state."""
        if self.charging_state == "solar_waiting_battery_priority":
            return "waiting"
        if self.power.battery_soc < 80:  # Default priority threshold
            return "priority"
        return "normal"
