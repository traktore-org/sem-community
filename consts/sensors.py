"""Sensor definitions for SEM Solar Energy Management."""
from typing import Final, Dict

# ============================================
# SEM MEASUREMENTS & SENSORS
# ============================================
# These are all the measurements from your automations
# SEM Sensors - These are the standardized sensors created by the component
# Hardware sensors are mapped to these via config_flow, then everything uses these
SEM_SENSORS: Final = {
    # Hardware-Mapped Sensors (directly from hardware via config_flow)
    "solar_power": "sensor.sem_solar_power",                 # Renamed: solar_production → solar_power
    "grid_power": "sensor.sem_grid_power",
    "battery_power": "sensor.sem_battery_power",
    "battery_soc": "sensor.sem_battery_soc",
    "ev_power": "sensor.sem_ev_power",                       # Renamed: ev_charging_power → ev_power

    # Calculated Power Sensors (computed from hardware sensors)
    "home_consumption": "sensor.sem_home_consumption",       # = Solar - Grid + Battery_discharge - EV
    "available_power": "sensor.sem_available_power",         # = Solar - Home + Battery_available
    "calculated_current": "sensor.sem_calculated_current",   # = Available_power / (230V * 3 phases)

    # Split Power Sensors (derived from hardware sensors)
    "grid_import_power": "sensor.sem_grid_import_power",     # Renamed: grid_power_import → grid_import_power
    "grid_export_power": "sensor.sem_grid_export_power",     # Renamed: grid_power_export → grid_export_power
    "battery_charge_power": "sensor.sem_battery_charge_power", # = max(0, battery_power)
    "battery_discharge_power": "sensor.sem_battery_discharge_power", # = max(0, -battery_power)

    # Energy Sensors (TOTAL_INCREASING for long-term statistics)
    "daily_solar_energy": "sensor.sem_daily_solar_energy",          # Renamed: solar_production_total → daily_solar_energy
    "daily_home_energy": "sensor.sem_daily_home_energy",            # Renamed: home_consumption_total → daily_home_energy
    "home_consumption_without_ev": "sensor.sem_home_consumption_without_ev",
    "daily_grid_import": "sensor.sem_daily_grid_import",            # Daily grid import energy
    "daily_grid_export": "sensor.sem_daily_grid_export",            # Daily grid export energy
    "daily_battery_charge": "sensor.sem_daily_battery_charge",      # Daily battery charge energy
    "daily_battery_discharge": "sensor.sem_daily_battery_discharge", # Daily battery discharge energy

    # EV Sensors (created/calculated)
    "ev_session_energy": "sensor.sem_ev_session_energy",
    "daily_ev_energy": "sensor.sem_daily_ev_energy",                # Renamed: ev_daily_energy → daily_ev_energy
    "ev_total_energy": "sensor.sem_ev_total_energy",

    # Energy Flow Sensors (for Sankey charts) - Removed flow_ prefix
    "solar_to_home_energy": "sensor.sem_solar_to_home_energy",       # Renamed: flow_solar_to_home → solar_to_home_energy
    "solar_to_ev_energy": "sensor.sem_solar_to_ev_energy",           # Renamed: flow_solar_to_ev → solar_to_ev_energy
    "solar_to_battery_energy": "sensor.sem_solar_to_battery_energy", # Renamed: flow_solar_to_battery → solar_to_battery_energy
    "solar_to_grid_energy": "sensor.sem_solar_to_grid_energy",       # Renamed: flow_solar_to_grid → solar_to_grid_energy
    "grid_to_home_energy": "sensor.sem_grid_to_home_energy",         # Renamed: flow_grid_to_home → grid_to_home_energy
    "grid_to_ev_energy": "sensor.sem_grid_to_ev_energy",             # Renamed: flow_grid_to_ev → grid_to_ev_energy
    "battery_to_home_energy": "sensor.sem_battery_to_home_energy",   # Renamed: flow_battery_to_home → battery_to_home_energy
    "battery_to_ev_energy": "sensor.sem_battery_to_ev_energy",       # Renamed: flow_battery_to_ev → battery_to_ev_energy

    # Peak Load Management (15-minute consecutive peak tracking)
    "consecutive_peak_15min": "sensor.sem_consecutive_peak_15min",
    "monthly_consecutive_peak": "sensor.sem_monthly_consecutive_peak",
    "current_vs_peak_percentage": "sensor.sem_current_vs_peak_percentage",
    "power_charge_cost": "sensor.sem_power_charge_cost",
    "controlled_tariff_status": "sensor.sem_controlled_tariff_status",

    # Battery Financial Metrics
    "daily_battery_savings": "sensor.sem_daily_battery_savings",
    "monthly_battery_savings": "sensor.sem_monthly_battery_savings",
    "battery_discharge_value": "sensor.sem_battery_discharge_value",
    "solar_storage_value": "sensor.sem_solar_storage_value",
    "peak_reduction_savings": "sensor.sem_peak_reduction_savings",
    "battery_value_percentage": "sensor.sem_battery_value_percentage",
    "annual_battery_savings_projection": "sensor.sem_annual_battery_savings_projection",

    # Performance Metrics (based on solar_v2 formulas)
    "self_consumption_rate_daily": "sensor.sem_self_consumption_rate_daily",
    "autarky_rate_daily": "sensor.sem_autarky_rate_daily",
    "performance_ratio": "sensor.sem_performance_ratio",
    "power_flow_efficiency": "sensor.sem_power_flow_efficiency",
    "energy_balance_check": "sensor.sem_energy_balance_check",

    # Real-time Power Flow Sensors (expose existing flow calculations)
    "flow_solar_to_home_power": "sensor.sem_flow_solar_to_home_power",
    "flow_solar_to_battery_power": "sensor.sem_flow_solar_to_battery_power",
    "flow_solar_to_ev_power": "sensor.sem_flow_solar_to_ev_power",
    "flow_solar_to_grid_power": "sensor.sem_flow_solar_to_grid_power",
    "flow_battery_to_home_power": "sensor.sem_flow_battery_to_home_power",
    "flow_battery_to_ev_power": "sensor.sem_flow_battery_to_ev_power",
    "flow_grid_to_home_power": "sensor.sem_flow_grid_to_home_power",
    "flow_grid_to_ev_power": "sensor.sem_flow_grid_to_ev_power",
    "flow_grid_to_battery_power": "sensor.sem_flow_grid_to_battery_power",

    # Tariff Sensors
    "tariff_current_import_rate": "sensor.sem_tariff_current_import_rate",
    "tariff_price_level": "sensor.sem_tariff_price_level",
    "tariff_next_cheap_start": "sensor.sem_tariff_next_cheap_start",

    # System Health Sensors
    "grid_status": "sensor.sem_grid_status",
    "battery_health": "sensor.sem_battery_health",
    "ev_max_current_available": "sensor.sem_ev_max_current_available",

    # EV Intelligence Sensors
    "ev_taper_trend": "sensor.sem_ev_taper_trend",
    "ev_taper_ratio": "sensor.sem_ev_taper_ratio",
    "ev_taper_minutes_to_full": "sensor.sem_ev_taper_minutes_to_full",
    "ev_estimated_soc": "sensor.sem_ev_estimated_soc",
    "ev_last_full_charge": "sensor.sem_ev_last_full_charge",
    "ev_energy_since_full": "sensor.sem_ev_energy_since_full",
    "ev_predicted_daily_consumption": "sensor.sem_ev_predicted_daily_consumption",
    "ev_nights_until_charge": "sensor.sem_ev_nights_until_charge",
    "ev_charge_needed": "sensor.sem_ev_charge_needed",
    "ev_battery_health": "sensor.sem_ev_battery_health",
    "ev_charge_skip_reason": "sensor.sem_ev_charge_skip_reason",
}

# SEM Binary Sensors - These are created from hardware binary sensors
SEM_BINARY_SENSORS: Final = {
    "ev_connected": "binary_sensor.sem_ev_connected",
    "ev_charging": "binary_sensor.sem_ev_charging",
    "battery_charging": "binary_sensor.sem_battery_charging",
    "battery_discharging": "binary_sensor.sem_battery_discharging",
    "grid_exporting": "binary_sensor.sem_grid_exporting",
    "solar_active": "binary_sensor.sem_solar_active",
}

# Input numbers for configuration
EMS_INPUT_NUMBERS: Final = {
    "min_solar_power": "input_number.min_solar_power",
    "daily_ev_target": "input_number.daily_ev_target",
    "max_grid_import": "input_number.max_grid_import",
    "min_charging_current": "input_number.min_charging_current",
    "keba_charging_current": "input_number.keba_charging_current",
}

# ============================================
# ENERGY SOURCE TYPES
# ============================================
ENERGY_SOURCE_HARDWARE: Final = "hardware"
ENERGY_SOURCE_RIEMANN: Final = "riemann"
ENERGY_SOURCE_MANUAL: Final = "manual"
ENERGY_SOURCE_NONE: Final = "none"

# Riemann Integration Sensor Names
RIEMANN_ENERGY_SENSORS: Final = {
    "solar_energy": "sensor.sem_solar_energy_riemann",
    "home_energy": "sensor.sem_home_energy_riemann",
    "grid_import_energy": "sensor.sem_grid_import_energy_riemann",
    "grid_export_energy": "sensor.sem_grid_export_energy_riemann",
    "battery_charge_energy": "sensor.sem_battery_charge_energy_riemann",
    "battery_discharge_energy": "sensor.sem_battery_discharge_energy_riemann",
    "ev_energy": "sensor.sem_ev_energy_riemann",
}

# ============================================
# HARDWARE ENERGY SENSORS (Optional)
# ============================================
# Configuration keys for hardware total energy counters
CONF_SOLAR_TOTAL_ENERGY: Final = "solar_total_energy_sensor"
CONF_GRID_IMPORT_TOTAL_ENERGY: Final = "grid_import_total_energy_sensor"
CONF_GRID_EXPORT_TOTAL_ENERGY: Final = "grid_export_total_energy_sensor"
CONF_BATTERY_CHARGE_TOTAL_ENERGY: Final = "battery_charge_total_energy_sensor"
CONF_BATTERY_DISCHARGE_TOTAL_ENERGY: Final = "battery_discharge_total_energy_sensor"

# Energy tracking modes
ENERGY_MODE_HARDWARE: Final = "hardware"
ENERGY_MODE_CALCULATED: Final = "calculated"
ENERGY_MODE_MIXED: Final = "mixed"

# Utility meter settings
ENERGY_METER_RESET_HOUR: Final = 0  # Midnight daily reset (standard)
ENERGY_METER_RESET_DAY: Final = 1   # Monthly reset on 1st day

# ============================================
# LOAD MANAGEMENT SENSORS
# ============================================
LOAD_MANAGEMENT_SENSORS: Final = {
    "target_peak_limit": "sensor.sem_target_peak_limit",
    "peak_margin": "sensor.sem_peak_margin",
    "load_management_status": "sensor.sem_load_management_status",
    "loads_currently_shed": "sensor.sem_loads_currently_shed",
    "available_load_reduction": "sensor.sem_available_load_reduction",
    "controllable_devices_count": "sensor.sem_controllable_devices_count",
    "load_shedding_active": "binary_sensor.sem_load_shedding_active",
}

# ============================================
# ATTRIBUTES FOR SENSORS
# ============================================
SENSOR_ATTRIBUTES: Final = [
    "last_update",
    "charging_state",
    "battery_soc",
    "available_power",
    "calculated_current",
    "solar_production",
    "home_consumption",
    "grid_import",
    "grid_export",
    "ev_session_energy",
    "daily_ev_energy",
    "daily_grid_import",
    "daily_grid_export",
    "daily_battery_charge",
    "daily_battery_discharge",
    "self_consumption_rate_daily",
    "autarky_rate_daily",
    "performance_ratio",
    "power_flow_efficiency",
    "energy_balance_check",
    "delta_triggered",
    "hysteresis_active",
    # Load management attributes
    "target_peak_limit",
    "peak_margin",
    "load_management_status",
    "controllable_devices",
    "devices_shed",
    "load_reduction_available",
]
