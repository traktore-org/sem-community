"""State machine definitions for SEM Solar Energy Management."""
from typing import Final, Dict


# ============================================
# CHARGING STATES (Dual State Machine)
# ============================================
class ChargingState:
    """Dual charging state machine states."""

    # Legacy states (kept for compatibility)
    IDLE = "idle"
    WAITING_BATTERY_PRIORITY = "waiting_battery_priority"
    CHARGING_ALLOWED = "charging_allowed"
    CHARGING_ACTIVE = "charging_active"
    PAUSE_LOW_BATTERY = "pause_low_battery"
    RESUME_PENDING = "resume_pending"
    NIGHT_CHARGING = "night_charging"
    SUPER_CHARGING = "super_charging"
    TARGET_REACHED = "target_reached"
    ERROR = "error"

    # Solar EV Charging States
    SOLAR_IDLE = "solar_idle"
    SOLAR_WAITING_BATTERY_PRIORITY = "solar_waiting_battery_priority"
    SOLAR_CHARGING_ALLOWED = "solar_charging_allowed"
    SOLAR_CHARGING_ACTIVE = "solar_charging_active"
    SOLAR_SUPER_CHARGING = "solar_super_charging"
    SOLAR_PAUSE_LOW_BATTERY = "solar_pause_low_battery"
    SOLAR_TARGET_REACHED = "solar_target_reached"

    # Night Charging States
    NIGHT_IDLE = "night_idle"
    NIGHT_DISABLED = "night_disabled"
    NIGHT_CHARGING_ACTIVE = "night_charging_active"
    NIGHT_TARGET_REACHED = "night_target_reached"
    NIGHT_WAITING_FOR_WINDOW = "night_waiting_for_window"
    NIGHT_TIME_EXPIRED = "night_time_expired"

    # Min+PV Mode
    SOLAR_MIN_PV = "solar_min_pv"


# ============================================
# STATUS MESSAGES
# ============================================
STATUS_MESSAGES: Final = {
    # General states (legacy)
    ChargingState.IDLE: "System ready",
    ChargingState.WAITING_BATTERY_PRIORITY: "Waiting for battery",
    ChargingState.CHARGING_ALLOWED: "Charging allowed",
    ChargingState.CHARGING_ACTIVE: "Charging active",
    ChargingState.PAUSE_LOW_BATTERY: "Pause - Battery too low",
    ChargingState.RESUME_PENDING: "Waiting for battery resume",
    ChargingState.NIGHT_CHARGING: "Night charging active",
    ChargingState.SUPER_CHARGING: "Battery assist",
    ChargingState.TARGET_REACHED: "Daily target reached",
    ChargingState.ERROR: "Error",

    # Solar charging states
    ChargingState.SOLAR_IDLE: "Solar mode - System ready",
    ChargingState.SOLAR_WAITING_BATTERY_PRIORITY: "Solar mode - Waiting for battery",
    ChargingState.SOLAR_CHARGING_ALLOWED: "Solar mode - Charging allowed",
    ChargingState.SOLAR_CHARGING_ACTIVE: "Solar mode - Charging active",
    ChargingState.SOLAR_SUPER_CHARGING: "Solar mode - Battery assist",
    ChargingState.SOLAR_PAUSE_LOW_BATTERY: "Solar mode - Paused, battery low",
    ChargingState.SOLAR_TARGET_REACHED: "Solar mode - Daily target reached",
    ChargingState.SOLAR_MIN_PV: "Solar mode - Min+PV charging",

    # Night charging states
    ChargingState.NIGHT_IDLE: "Night mode - Ready",
    ChargingState.NIGHT_DISABLED: "Night charging disabled",
    ChargingState.NIGHT_CHARGING_ACTIVE: "Night charging active",
    ChargingState.NIGHT_TARGET_REACHED: "Night mode - Target reached",
    ChargingState.NIGHT_WAITING_FOR_WINDOW: "Night mode - Waiting for charging window",
    ChargingState.NIGHT_TIME_EXPIRED: "Night charging window expired",
}


# ============================================
# LOAD MANAGEMENT STATES
# ============================================
class LoadManagementState:
    """Load management system states."""
    NORMAL = "normal"
    WARNING = "warning"
    SHEDDING = "shedding"
    EMERGENCY = "emergency"
    DISABLED = "disabled"
    ERROR = "error"


# Device priority levels
DEVICE_PRIORITY_LEVELS: Final = {
    1: "Critical - Never shed",
    2: "High priority",
    3: "Medium-high priority",
    4: "Medium priority",
    5: "Normal priority",
    6: "Low priority",
    7: "Very low priority",
    8: "Comfort loads",
    9: "Non-essential",
    10: "First to shed"
}
