"""Label definitions for SEM dynamic dashboards."""
from typing import Final, Dict

# LABEL DEFINITIONS FOR DYNAMIC DASHBOARDS
# ============================================
# Labels are used with auto-entities card to create dynamic dashboards
# that automatically adapt to available entities

SEM_LABELS: Final[Dict[str, str]] = {
    # Type-based labels
    "sem_power": "Power sensors (W)",
    "sem_energy": "Energy totals (kWh)",
    "sem_flow": "Energy flow sensors",
    "sem_status": "Automation status",
    "sem_config": "Configuration entities",

    # Category labels
    "sem_battery": "Battery related",
    "sem_solar": "Solar related",
    "sem_ev": "EV charging related",
    "sem_grid": "Grid related",
    "sem_home": "Home consumption",

    # Importance labels
    "sem_core": "Core dashboard sensors",
    "sem_primary": "Primary sensors",
    "sem_secondary": "Secondary sensors",
    "sem_advanced": "Advanced/debug sensors",

    # Time-based labels
    "sem_daily": "Daily statistics",
    "sem_monthly": "Monthly statistics",
    "sem_realtime": "Real-time values",

    # Visibility labels
    "sem_exclude": "Hide from dashboard",
    "sem_graph": "Include in graphs",
    "sem_mobile": "Show on mobile view"
}

# Mapping of sensor keys to their labels
SENSOR_LABEL_MAPPING: Final[Dict[str, set]] = {
    # Core power sensors
    "solar_power": {"sem_power", "sem_solar", "sem_core", "sem_realtime", "sem_mobile"},
    "grid_power": {"sem_power", "sem_grid", "sem_core", "sem_realtime", "sem_mobile"},
    "battery_power": {"sem_power", "sem_battery", "sem_core", "sem_realtime", "sem_mobile"},
    "ev_power": {"sem_power", "sem_ev", "sem_core", "sem_realtime", "sem_mobile"},
    "home_consumption_power": {"sem_power", "sem_home", "sem_core", "sem_realtime"},
    "available_power": {"sem_power", "sem_primary", "sem_realtime", "sem_mobile"},
    "ev_charging_power": {"sem_power", "sem_ev", "sem_secondary", "sem_realtime"},

    # Core status sensors
    "charging_state": {"sem_status", "sem_core", "sem_mobile"},
    "solar_charging_status": {"sem_status", "sem_solar", "sem_primary", "sem_mobile"},
    "night_charging_status": {"sem_status", "sem_grid", "sem_primary"},
    "battery_priority_status": {"sem_status", "sem_battery", "sem_primary"},
    "load_management_status": {"sem_status", "sem_primary", "sem_mobile"},
    "automation_decision_reason": {"sem_status", "sem_core"},
    "charging_automation_status": {"sem_status", "sem_primary"},
    "charging_strategy": {"sem_status", "sem_core", "sem_mobile"},
    "solar_optimization_status": {"sem_status", "sem_solar", "sem_secondary"},
    "grid_management_status": {"sem_status", "sem_grid", "sem_secondary"},

    # Battery sensors
    "battery_soc": {"sem_battery", "sem_core", "sem_realtime", "sem_graph", "sem_mobile"},
    "battery_status": {"sem_status", "sem_battery", "sem_primary"},
    "battery_temperature": {"sem_battery", "sem_secondary", "sem_realtime"},
    "battery_voltage": {"sem_battery", "sem_advanced", "sem_realtime"},
    "battery_current": {"sem_battery", "sem_advanced", "sem_realtime"},
    "battery_cycles": {"sem_battery", "sem_advanced"},
    "battery_health": {"sem_battery", "sem_primary"},
    "battery_efficiency": {"sem_battery", "sem_secondary"},

    # Energy flow sensors (real-time power)
    "flow_solar_to_home_power": {"sem_flow", "sem_solar", "sem_home", "sem_secondary"},
    "flow_solar_to_battery_power": {"sem_flow", "sem_solar", "sem_battery", "sem_secondary"},
    "flow_solar_to_ev_power": {"sem_flow", "sem_solar", "sem_ev", "sem_secondary"},
    "flow_solar_to_grid_power": {"sem_flow", "sem_solar", "sem_grid", "sem_secondary"},
    "flow_grid_to_home_power": {"sem_flow", "sem_grid", "sem_home", "sem_secondary"},
    "flow_grid_to_ev_power": {"sem_flow", "sem_grid", "sem_ev", "sem_secondary"},
    "flow_grid_to_battery_power": {"sem_flow", "sem_grid", "sem_battery", "sem_secondary"},
    "flow_battery_to_home_power": {"sem_flow", "sem_battery", "sem_home", "sem_secondary"},
    "flow_battery_to_ev_power": {"sem_flow", "sem_battery", "sem_ev", "sem_secondary"},

    # Daily energy sensors
    "daily_solar_energy": {"sem_energy", "sem_solar", "sem_daily", "sem_core", "sem_graph"},
    "daily_home_energy": {"sem_energy", "sem_home", "sem_daily", "sem_core", "sem_graph"},
    "daily_ev_energy": {"sem_energy", "sem_ev", "sem_daily", "sem_core", "sem_graph", "sem_mobile"},
    "daily_grid_import": {"sem_energy", "sem_grid", "sem_daily", "sem_primary", "sem_graph"},
    "daily_grid_export": {"sem_energy", "sem_grid", "sem_daily", "sem_primary", "sem_graph"},
    "daily_battery_charge": {"sem_energy", "sem_battery", "sem_daily", "sem_primary"},
    "daily_battery_discharge": {"sem_energy", "sem_battery", "sem_daily", "sem_primary"},
    "daily_ev_consumption": {"sem_energy", "sem_ev", "sem_daily", "sem_primary"},
    "daily_solar_yield": {"sem_energy", "sem_solar", "sem_daily", "sem_primary"},

    # Monthly energy sensors
    "monthly_solar_yield": {"sem_energy", "sem_solar", "sem_monthly", "sem_secondary"},
    "monthly_home_consumption": {"sem_energy", "sem_home", "sem_monthly", "sem_secondary"},
    "monthly_ev_consumption": {"sem_energy", "sem_ev", "sem_monthly", "sem_secondary"},
    "monthly_grid_import": {"sem_energy", "sem_grid", "sem_monthly", "sem_secondary"},
    "monthly_grid_export": {"sem_energy", "sem_grid", "sem_monthly", "sem_secondary"},
    "monthly_battery_charge": {"sem_energy", "sem_battery", "sem_monthly", "sem_secondary"},
    "monthly_battery_discharge": {"sem_energy", "sem_battery", "sem_monthly", "sem_secondary"},

    # Load management
    "target_peak_limit": {"sem_config", "sem_primary", "sem_realtime"},
    "peak_margin": {"sem_power", "sem_primary", "sem_realtime"},
    "loads_currently_shed": {"sem_status", "sem_secondary"},
    "available_load_reduction": {"sem_status", "sem_secondary"},
    "controllable_devices_count": {"sem_status", "sem_advanced"},

    # Calculated/derived power
    "calculated_current": {"sem_power", "sem_advanced", "sem_realtime"},
    "grid_import_power": {"sem_power", "sem_grid", "sem_secondary", "sem_realtime"},
    "grid_export_power": {"sem_power", "sem_grid", "sem_secondary", "sem_realtime"},

    # Efficiency and rates
    "self_consumption_rate": {"sem_status", "sem_secondary"},
    "solar_utilization": {"sem_status", "sem_secondary"},
    "solar_efficiency": {"sem_status", "sem_secondary"},
    "autarky_rate": {"sem_status", "sem_secondary"},
    "self_consumption_rate_daily": {"sem_status", "sem_daily", "sem_secondary"},
    "autarky_rate_daily": {"sem_status", "sem_daily", "sem_secondary"},

    # System status
    "grid_status": {"sem_status", "sem_grid", "sem_advanced"},
    "inverter_efficiency": {"sem_status", "sem_solar", "sem_advanced"},
    "inverter_load_ratio": {"sem_status", "sem_solar", "sem_advanced"},
    "power_factor": {"sem_status", "sem_advanced"},
    "grid_frequency": {"sem_status", "sem_grid", "sem_advanced"},

    # EV specific
    "ev_max_current": {"sem_ev", "sem_config", "sem_secondary"},
    "ev_max_current_available": {"sem_ev", "sem_secondary", "sem_realtime"},
    "ev_session_energy": {"sem_energy", "sem_ev", "sem_secondary"},
    "ev_total_energy": {"sem_energy", "sem_ev", "sem_secondary"},

    # Cost and savings
    "daily_savings": {"sem_energy", "sem_daily", "sem_secondary"},
    "monthly_savings": {"sem_energy", "sem_monthly", "sem_secondary"},
    "daily_costs": {"sem_energy", "sem_daily", "sem_secondary"},
    "monthly_costs": {"sem_energy", "sem_monthly", "sem_secondary"},
    "daily_export_revenue": {"sem_energy", "sem_grid", "sem_daily", "sem_secondary"},
    "monthly_export_revenue": {"sem_energy", "sem_grid", "sem_monthly", "sem_secondary"},

    # Tariff sensors
    "consecutive_peak_15min": {"sem_status", "sem_grid", "sem_secondary"},
    "monthly_consecutive_peak": {"sem_status", "sem_grid", "sem_secondary"},
    "controlled_tariff_status": {"sem_status", "sem_grid", "sem_secondary"},

    # Load balancing
    "load_balancer_l1": {"sem_power", "sem_advanced", "sem_realtime"},
    "load_balancer_l2": {"sem_power", "sem_advanced", "sem_realtime"},
    "load_balancer_l3": {"sem_power", "sem_advanced", "sem_realtime"},
    "load_balancer_total": {"sem_power", "sem_advanced", "sem_realtime"},

    # Data quality and system
    "last_update": {"sem_status", "sem_advanced"},
    "energy_data_quality": {"sem_status", "sem_advanced"},
    "energy_tracking_mode": {"sem_status", "sem_advanced"},
    "energy_balance_check": {"sem_status", "sem_advanced"},

    # Surplus controller (Phase 0)
    "surplus_total_w": {"sem_power", "sem_realtime", "sem_secondary"},
    "surplus_distributable_w": {"sem_power", "sem_realtime", "sem_secondary"},
    "surplus_allocated_w": {"sem_power", "sem_realtime", "sem_secondary"},
    "surplus_active_devices": {"sem_status", "sem_secondary"},
    "surplus_total_devices": {"sem_status", "sem_advanced"},

    # Forecast (Phase 0)
    "forecast_today_kwh": {"sem_energy", "sem_solar", "sem_daily", "sem_primary"},
    "forecast_tomorrow_kwh": {"sem_energy", "sem_solar", "sem_daily", "sem_primary"},
    "forecast_remaining_today_kwh": {"sem_energy", "sem_solar", "sem_daily", "sem_primary", "sem_mobile"},
    "forecast_power_now_w": {"sem_power", "sem_solar", "sem_realtime", "sem_secondary"},
    "charging_recommendation": {"sem_status", "sem_ev", "sem_primary"},

    # Tariff (Phase 1)
    "tariff_current_import_rate": {"sem_status", "sem_grid", "sem_primary", "sem_realtime"},
    "tariff_price_level": {"sem_status", "sem_grid", "sem_primary", "sem_mobile"},
    "tariff_next_cheap_start": {"sem_status", "sem_grid", "sem_secondary"},

    # Heat pump (Phase 2)
    "heat_pump_mode": {"sem_status", "sem_primary"},
    "heat_pump_sg_ready_state": {"sem_status", "sem_secondary"},
    "heat_pump_solar_boost": {"sem_status", "sem_secondary"},

    # PV analytics (Phase 5)
    "pv_daily_specific_yield": {"sem_energy", "sem_solar", "sem_daily", "sem_secondary"},
    "pv_performance_vs_forecast": {"sem_status", "sem_solar", "sem_secondary"},
    "pv_estimated_annual_degradation": {"sem_status", "sem_solar", "sem_advanced"},
    "pv_degradation_trend": {"sem_status", "sem_solar", "sem_advanced"},

    # Energy assistant (Phase 6)
    "energy_optimization_score": {"sem_status", "sem_primary", "sem_mobile"},
    "energy_tip": {"sem_status", "sem_primary", "sem_mobile"},
    "energy_ev_solar_percentage": {"sem_status", "sem_ev", "sem_secondary"},

    # Utility signals (Phase 7)
    "utility_signal_active": {"sem_status", "sem_grid", "sem_secondary"},
    "utility_signal_count_today": {"sem_status", "sem_grid", "sem_advanced"},
}
