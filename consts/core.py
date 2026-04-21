"""Core configuration defaults for SEM Solar Energy Management integration."""
from typing import Final

DOMAIN: Final = "solar_energy_management"

# ============================================
# UPDATE & DELTA THRESHOLDS
# ============================================
DEFAULT_OBSERVER_MODE: Final = False  # When True, skip all hardware control (read-only monitoring)
DEFAULT_UPDATE_INTERVAL: Final = 10  # seconds - 10 seconds for highly accurate energy integration
DEFAULT_POWER_DELTA: Final = 1000  # Watts - only major changes
DEFAULT_CURRENT_DELTA: Final = 5  # Amps - significant current changes only
DEFAULT_SOC_DELTA: Final = 10  # Percent - battery changes slowly anyway

# Database protection levels
DATABASE_PROTECTION_MINIMAL: Final = 1   # All sensors enabled, normal updates
DATABASE_PROTECTION_BALANCED: Final = 2  # Reduced flow sensors, longer delays
DATABASE_PROTECTION_AGGRESSIVE: Final = 3  # Essential sensors only, max delays

# ============================================
# BATTERY MANAGEMENT DEFAULTS
# ============================================
DEFAULT_BATTERY_PRIORITY_SOC: Final = 30  # % - SOC zone floor: below this, all solar → battery, EV blocked
DEFAULT_BATTERY_MINIMUM_SOC: Final = 20  # % - Hard stop: SOC below this halts EV charging entirely
DEFAULT_BATTERY_RESUME_SOC: Final = 50  # % - Hysteresis: resume EV charging once SOC recovers above this
DEFAULT_BATTERY_SAFETY_SOC: Final = 60  # % - Safety threshold for discharge calculations
# 4-zone SOC strategy thresholds (see docs/ARCHITECTURE.md "SOC Zone Strategy")
DEFAULT_BATTERY_BUFFER_SOC: Final = 70  # % - Above: battery can discharge to help the EV (Zone 3 begins)
DEFAULT_BATTERY_AUTO_START_SOC: Final = 90  # % - Above: EV starts even without solar surplus (Zone 4)
DEFAULT_BATTERY_ASSIST_FLOOR_SOC: Final = 60  # % - Hysteresis floor for battery assist (drop-out below this)

# Battery Discharge Protection
DEFAULT_BATTERY_DISCHARGE_PROTECTION_ENABLED: Final = True  # Enable discharge protection during night charging
DEFAULT_BATTERY_MAX_DISCHARGE_POWER: Final = 5000  # Watts - Maximum allowed discharge (caps 1:1 home consumption matching)
DEFAULT_DISCHARGE_LIMIT_UPDATE_INTERVAL: Final = 60  # Seconds - How often to update discharge limits
DEFAULT_BATTERY_DISCHARGE_CONTROL_ENTITY: Final = ""  # Entity ID for battery discharge control (e.g., number.batteries_maximale_entladeleistung)

# EV Charger Control Configuration
DEFAULT_EV_CHARGER_SERVICE: Final = ""  # Service for EV charger current control (e.g., "keba.set_current" for KEBA chargers without number entity)
DEFAULT_EV_CHARGER_SERVICE_ENTITY_ID: Final = ""  # Entity ID to use for service targeting (e.g., "binary_sensor.keba_p30_plug")

# EV Charging Parameters
DEFAULT_EV_RAMP_RATE_AMPS: Final = 2  # Max ±2A per 10s cycle during solar/night charging
DEFAULT_EV_CHARGING_MODE: Final = "auto"  # "auto" (forecast-aware), "pv" (solar+battery), "self_consumption" (true surplus only), "minpv" (min+PV), "now" (max), "off" (disabled)
DEFAULT_EV_NIGHT_INITIAL_CURRENT: Final = 10  # Amps - starting current for night charging
DEFAULT_EV_MIN_CURRENT: Final = 6  # Amps - IEC 61851 minimum (increase for sensitive cars)
DEFAULT_EV_STALL_COOLDOWN: Final = 120  # Seconds between KEBA re-enable attempts
DEFAULT_EV_CHARGER_NEEDS_CYCLE: Final = False  # True = disable/enable cycle for session start (sensitive cars)
DEFAULT_EV_BATTERY_CAPACITY_KWH: Final = 40  # kWh — usable EV battery capacity
DEFAULT_EV_TARGET_SOC: Final = 80  # % — target SOC for night charging

# ============================================
# EFFICIENCY CORRECTION FACTORS
# ============================================
# Based on Huawei Solar approach - accounts for real-world conversion losses

# Solar Inverter Efficiency (load-dependent, from datasheet curves)
DEFAULT_INVERTER_EFFICIENCY_LOW: Final = 0.90   # <10% load - startup inefficiencies
DEFAULT_INVERTER_EFFICIENCY_MED: Final = 0.95   # 10-20% load - medium efficiency
DEFAULT_INVERTER_EFFICIENCY_HIGH: Final = 0.98  # >20% load - optimal efficiency
DEFAULT_INVERTER_LOAD_THRESHOLD_LOW: Final = 10  # % load threshold for low efficiency
DEFAULT_INVERTER_LOAD_THRESHOLD_MED: Final = 20  # % load threshold for medium efficiency

# Battery Round-Trip Efficiency (typical Li-ion losses)
DEFAULT_BATTERY_CHARGE_EFFICIENCY: Final = 0.95   # Charging efficiency (5% heat loss)
DEFAULT_BATTERY_DISCHARGE_EFFICIENCY: Final = 1.0 # Discharge uses raw value (loss in charge)

# EV Charger Efficiency (AC to DC conversion)
DEFAULT_EV_CHARGER_EFFICIENCY: Final = 0.92  # Typical for KEBA/Wallbox chargers (8% loss)

# Grid Import/Export (minimal losses for direct metering)
DEFAULT_GRID_EFFICIENCY: Final = 1.0  # Grid meter measures after all losses

# Energy Source Configuration
DEFAULT_ENERGY_SOURCE_PRIORITY: Final = "auto"  # auto, hardware, riemann, manual
DEFAULT_RIEMANN_INTEGRATION_ENABLED: Final = True  # Enable Riemann fallback sensors
DEFAULT_AUTO_CREATE_MISSING_ENERGY: Final = True  # Auto-create missing energy sensors

# Energy Source Types
ENERGY_SOURCE_HARDWARE: Final = "hardware"
ENERGY_SOURCE_RIEMANN: Final = "riemann"
ENERGY_SOURCE_MANUAL: Final = "manual"
ENERGY_SOURCE_NONE: Final = "none"

DEFAULT_PREFER_HARDWARE_ENERGY: Final = True  # Prefer hardware energy sensors over calculated
DEFAULT_ENERGY_SOURCE_AUTO: Final = True  # Auto-select best available energy source

# ============================================
# SOLAR & POWER DEFAULTS
# ============================================
DEFAULT_MIN_SOLAR_POWER: Final = 1000  # Watts
DEFAULT_MIN_EXCESS_POWER: Final = 500  # Watts
DEFAULT_MAX_GRID_IMPORT: Final = 0  # Watts during solar charging — 0 = pure-solar mode
DEFAULT_BATTERY_ASSIST_MAX_POWER: Final = 4500  # Watts — max battery discharge for EV assist
DEFAULT_BATTERY_CAPACITY_KWH: Final = 15  # kWh — total usable battery capacity

# ============================================
# CHARGING CURRENT DEFAULTS
# ============================================
DEFAULT_MIN_CHARGING_CURRENT: Final = 6  # Amps
DEFAULT_MAX_CHARGING_CURRENT: Final = 32  # Amps (KEBA P30 supports 6-32A range)
DEFAULT_VOLTAGE_PER_PHASE: Final = 230  # Volts
DEFAULT_PHASES: Final = 3
DEFAULT_POWER_FACTOR: Final = 0.8  # For power calculations

# ============================================
# DAILY TARGETS & LIMITS
# ============================================
DEFAULT_DAILY_EV_TARGET: Final = 10  # kWh
DEFAULT_SESSION_LIMIT: Final = 10  # kWh per session during hysteresis

# ============================================
# TIME SCHEDULES
# ============================================
DEFAULT_NIGHT_EARLIEST_START: Final = 20.5  # 20:30 — floor: night mode never starts before this (hours as float)
DEFAULT_NIGHT_LATEST_END: Final = 7.0      # 07:00 — ceiling: night mode always ends by this (hours as float)
DEFAULT_DAILY_RESET: Final = "00:00"
DEFAULT_DAILY_ENERGY_OFFSET: Final = "07:00"  # Daily energy reset time (handles night charging across midnight)

# ============================================
# KEBA SERVICES
# Services: keba.start, keba.stop, keba.set_curr, keba.set_energy, keba.authorize
# Documentation: https://www.home-assistant.io/integrations/keba/
# ============================================
KEBA_DOMAIN: Final = "keba"
KEBA_SERVICE_START: Final = "enable"             # Enable/start charging
KEBA_SERVICE_STOP: Final = "disable"             # Disable/stop charging
KEBA_SERVICE_SET_CURRENT: Final = "set_current"  # Set max current in Ampere
KEBA_SERVICE_SET_ENERGY: Final = "set_energy"    # Set session target energy in kWh
KEBA_SERVICE_AUTHORIZE: Final = "authorize"      # Authorize with RFID tag
KEBA_COMMAND_DELAY: Final = 2  # seconds between commands

# ============================================
# CALCULATION FORMULAS
# ============================================
FORMULAS: Final = {
    # Available power calculation
    "available_power": """
        solar_power - home_consumption + battery_discharge - battery_charge
        + (grid_import_allowed if grid_allowed else 0)
    """,

    # Charging current from power
    "power_to_current": """
        power / (phases * voltage * power_factor)
    """,

    # Safe discharge power based on SOC
    "safe_discharge": """
        if soc >= battery_buffer_soc:
            battery_assist_max_power (proportional by zone)
        elif soc > safety_threshold:
            (soc - safety_threshold) * 50  # 50W per % above safety
        else:
            0
    """,
}

# ============================================
# LOAD MANAGEMENT & TARGET PEAK CONTROL
# ============================================
# Target peak limits and thresholds
DEFAULT_TARGET_PEAK_LIMIT: Final = 5.0  # kW - Main target to never exceed
DEFAULT_WARNING_PEAK_LEVEL: Final = 4.5  # kW - Early warning level
DEFAULT_EMERGENCY_PEAK_LEVEL: Final = 6.0  # kW - Hard emergency limit
DEFAULT_PEAK_HYSTERESIS: Final = 0.2  # kW - Prevent rapid cycling

# Load management settings
DEFAULT_LOAD_MANAGEMENT_ENABLED: Final = True
DEFAULT_CRITICAL_DEVICE_PROTECTION: Final = True
DEFAULT_LOAD_SHEDDING_DELAY: Final = 5  # seconds - Delay before shedding
DEFAULT_LOAD_RESTORE_DELAY: Final = 30  # seconds - Delay before restoring
DEFAULT_MIN_ON_DURATION: Final = 300  # seconds - Minimum time device stays on (anti-flicker)
DEFAULT_MIN_OFF_DURATION: Final = 60  # seconds - Minimum time device stays off (anti-flicker)
PEAK_SAFETY_MARGIN: Final = 0.5  # kW - Safety margin when limiting EV charging for peak

# ============================================
# SURPLUS CONTROLLER (Phase 0)
# ============================================
DEFAULT_REGULATION_OFFSET: Final = 50  # Watts - always keep small export to grid
DEFAULT_SURPLUS_CONTROL_ENABLED: Final = True

# ============================================
# TARIFF SETTINGS (Phase 1)
# ============================================
DEFAULT_TARIFF_MODE: Final = "static"  # static, dynamic
DEFAULT_CHEAP_PRICE_THRESHOLD: Final = 0.15  # CHF/kWh
DEFAULT_EXPENSIVE_PRICE_THRESHOLD: Final = 0.35  # CHF/kWh
DEFAULT_ELECTRICITY_NT_RATE: Final = 0.3387  # CHF/kWh nighttime incl. VAT (default flat rate = HT)
DEFAULT_DEMAND_CHARGE_RATE: Final = 4.32  # CHF/kW/month incl. VAT (default residential base tariff)

# ============================================
# HEAT PUMP SETTINGS (Phase 2)
# ============================================
DEFAULT_HEAT_PUMP_ENABLED: Final = False
DEFAULT_HEAT_PUMP_PRIORITY: Final = 4
DEFAULT_HEAT_PUMP_MIN_POWER: Final = 2000  # Watts
DEFAULT_HEAT_PUMP_BOOST_OFFSET: Final = 2.0  # Degrees
DEFAULT_HEAT_PUMP_FORCE_ON_THRESHOLD: Final = 5000  # Watts

# Hot water settings
DEFAULT_HOT_WATER_ENABLED: Final = False
DEFAULT_HOT_WATER_PRIORITY: Final = 6
DEFAULT_HOT_WATER_POWER: Final = 2000  # Watts
DEFAULT_HOT_WATER_MAX_TEMP: Final = 60.0  # Degrees

# ============================================
# PV PERFORMANCE (Phase 5)
# ============================================
DEFAULT_SYSTEM_SIZE_KWP: Final = 10.0
DEFAULT_INVERTER_MAX_POWER_W: Final = 10000

# ============================================
# ENTITY ID REFERENCES
# ============================================
# Used for internal state lookups — avoids magic strings scattered across modules.
ENTITY_OBSERVER_MODE_SWITCH: Final = f"{DOMAIN}.observer_mode"  # switch.sem_observer_mode
ENTITY_SOLAR_POWER: Final = f"{DOMAIN}.solar_power"  # sensor.sem_solar_power
ENTITY_FORECAST_NIGHT_REDUCTION: Final = f"{DOMAIN}.forecast_night_reduction"  # switch.sem_forecast_night_reduction

# Weather entity: auto-detected at runtime, fallback order
WEATHER_ENTITY_CANDIDATES: Final = ("weather.home", "weather.openweathermap")

# HA state constants (avoid magic strings)
STATE_UNKNOWN: Final = "unknown"
STATE_UNAVAILABLE: Final = "unavailable"
