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
    # Removed (#670): sem_exclude ("Hide from dashboard") — attached to no
    # entity and read by nothing anywhere in the codebase. Since #670 these
    # keys are created as real labels in the user's HA registry, so a dead one
    # is no longer inert: it would show up in their label list promising to
    # hide entities and do nothing.
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
    # Removed (#667): ev_charging_power — sensor.py:125 deleted it as a
    # duplicate of ev_power, which is labelled above.

    # Core status sensors
    "charging_state": {"sem_status", "sem_core", "sem_mobile"},
    "solar_charging_status": {"sem_status", "sem_solar", "sem_primary", "sem_mobile"},
    "night_charging_status": {"sem_status", "sem_grid", "sem_primary"},
    "battery_priority_status": {"sem_status", "sem_battery", "sem_primary"},
    "load_management_status": {"sem_status", "sem_primary", "sem_mobile"},
    "charging_strategy": {"sem_status", "sem_core", "sem_mobile"},
    # Removed (#667): automation_decision_reason, controlled_tariff_status
    # (sensor.py:233 — debug sensors, use load_management_status),
    # solar_optimization_status (:231 — "just checks solar_power > 50"),
    # grid_management_status (:232 — duplicate of grid_status, labelled below),
    # charging_automation_status (no implementation anywhere).

    # Battery sensors
    "battery_soc": {"sem_battery", "sem_core", "sem_realtime", "sem_graph", "sem_mobile"},
    "battery_status": {"sem_status", "sem_battery", "sem_primary"},
    "battery_temperature": {"sem_battery", "sem_secondary", "sem_realtime"},
    "inverter_temperature": {"sem_solar", "sem_secondary", "sem_realtime"},
    # Repointed (#667): the entities are real, the label keys had drifted off
    # their names. Label sets carried over verbatim — several DIAGNOSTIC
    # entities already carry sem_primary (battery_status, load_management_status),
    # so the category is not a reason to rewrite them.
    "battery_cycles_estimated": {"sem_battery", "sem_advanced"},
    "battery_health_score": {"sem_battery", "sem_primary"},
    # Removed (#667): battery_voltage, battery_current — SEM has no such
    # entity. Those names exist only in hardware_detection.py as patterns for
    # finding a USER's sensors; SEM never republishes them.
    # battery_efficiency — a hardcoded 95/100 metric on PerformanceMetrics
    # (energy_calculator.py:1358), never exposed as an entity.

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
    "daily_grid_import_energy": {"sem_energy", "sem_grid", "sem_daily", "sem_primary", "sem_graph"},
    "daily_grid_export_energy": {"sem_energy", "sem_grid", "sem_daily", "sem_primary", "sem_graph"},
    "daily_battery_charge_energy": {"sem_energy", "sem_battery", "sem_daily", "sem_primary"},
    "daily_battery_discharge_energy": {"sem_energy", "sem_battery", "sem_daily", "sem_primary"},
    # Removed (#667): daily_solar_yield (sensor.py:254 — use daily_solar_energy)
    # and daily_ev_consumption (no such entity; daily_ev_energy is the one).
    # Both are labelled above — repointing would have double-labelled them.

    # Monthly energy sensors
    "monthly_solar_yield_energy": {"sem_energy", "sem_solar", "sem_monthly", "sem_secondary"},
    "monthly_home_consumption_energy": {"sem_energy", "sem_home", "sem_monthly", "sem_secondary"},
    "monthly_ev_consumption_energy": {"sem_energy", "sem_ev", "sem_monthly", "sem_secondary"},
    "monthly_grid_import_energy": {"sem_energy", "sem_grid", "sem_monthly", "sem_secondary"},
    "monthly_grid_export_energy": {"sem_energy", "sem_grid", "sem_monthly", "sem_secondary"},
    "monthly_battery_charge_energy": {"sem_energy", "sem_battery", "sem_monthly", "sem_secondary"},
    "monthly_battery_discharge_energy": {"sem_energy", "sem_battery", "sem_monthly", "sem_secondary"},

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
    "autarky_rate": {"sem_status", "sem_secondary"},
    # Removed (#667): sensor.py:721 and :729 deleted these as redundant,
    # naming them one by one — self_consumption_rate_daily, autarky_rate_daily,
    # solar_utilization, solar_efficiency, inverter_efficiency,
    # inverter_load_ratio. The two survivors are labelled above.

    # System status
    "grid_status": {"sem_status", "sem_grid", "sem_advanced"},
    # Removed (#667): power_factor, grid_frequency — sensor.py:874,
    # "GRID QUALITY & LOAD BALANCER - Hardware sensors not populated".

    # EV specific
    # Removed (#667): sensor.py:197 deleted ev_max_current and
    # ev_max_current_available as duplicates of calculated_current (labelled
    # above), and :198 deleted ev_session_energy / ev_total_energy as
    # "not useful (session resets on plug, total tracked by Energy Dashboard)".

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

    # Removed (#667): load_balancer_l1/l2/l3/total — sensor.py:874, never
    # populated. last_update, energy_data_quality, energy_tracking_mode,
    # energy_balance_check — sensor.py:877, "use HA native diagnostics".

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
}
