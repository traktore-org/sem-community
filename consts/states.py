"""State machine definitions for SEM Solar Energy Management."""
from typing import Final, Optional

from homeassistant.core import HomeAssistant


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
    # (#1403) SEM sends the charger's full current (``CHARGE_MAX``: Always
    # max, or "Start now"). Grid, sun or battery may feed it — the text
    # names none of them. Before, this showed "Battery assist".
    SOLAR_FULL_POWER = "solar_full_power"
    SOLAR_PAUSE_LOW_BATTERY = "solar_pause_low_battery"
    SOLAR_TARGET_REACHED = "solar_target_reached"

    # Night Charging States
    NIGHT_IDLE = "night_idle"
    NIGHT_DISABLED = "night_disabled"
    NIGHT_CHARGING_ACTIVE = "night_charging_active"
    NIGHT_TARGET_REACHED = "night_target_reached"
    NIGHT_WAITING_FOR_WINDOW = "night_waiting_for_window"
    NIGHT_TIME_EXPIRED = "night_time_expired"

    # Tariff-optimized (#247): night charging paused, waiting for a cheap price
    # window. The Min floor is still guaranteed before the deadline regardless.
    TARIFF_WAITING_FOR_CHEAP = "tariff_waiting_for_cheap"

    # Min+PV Mode
    SOLAR_MIN_PV = "solar_min_pv"

    # (#1381) SEM stopped a charger another party steers for the phase
    # guard, and switches it back on when the phase has room again.
    PHASE_GUARD_STOPPED = "phase_guard_stopped"


#: Every night state. The per-charger loop keeps one of these over the
#: state it would derive from the decision (PR A); #1402 then says it
#: again from the decision where the decision ignores the night plan.
NIGHT_STATES: Final = frozenset({
    ChargingState.NIGHT_CHARGING_ACTIVE,
    ChargingState.TARIFF_WAITING_FOR_CHEAP,
    ChargingState.NIGHT_TARGET_REACHED,
    ChargingState.NIGHT_IDLE,
    ChargingState.NIGHT_DISABLED,
    ChargingState.NIGHT_TIME_EXPIRED,
    ChargingState.NIGHT_WAITING_FOR_WINDOW,
})


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
    ChargingState.SOLAR_FULL_POWER: "Charging at full power",
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
    ChargingState.TARIFF_WAITING_FOR_CHEAP: "Tariff mode - Waiting for cheap price window",
    ChargingState.PHASE_GUARD_STOPPED: "Stopped by the phase guard - back on when the phase has room",
}

# Map charging states to translation keys in dashboard/translations.json (#62)
_STATE_TRANSLATION_KEYS: Final = {
    ChargingState.IDLE: "state_system_ready",
    ChargingState.WAITING_BATTERY_PRIORITY: "state_waiting_battery",
    ChargingState.CHARGING_ALLOWED: "state_charging_allowed",
    ChargingState.CHARGING_ACTIVE: "state_charging_active",
    ChargingState.PAUSE_LOW_BATTERY: "state_pause_low_battery",
    ChargingState.RESUME_PENDING: "state_resume_pending",
    ChargingState.NIGHT_CHARGING: "state_night_charging",
    ChargingState.SUPER_CHARGING: "state_battery_assist",
    ChargingState.TARGET_REACHED: "state_target_reached",
    ChargingState.ERROR: "state_error",
    ChargingState.SOLAR_IDLE: "state_solar_ready",
    ChargingState.SOLAR_WAITING_BATTERY_PRIORITY: "state_solar_waiting",
    ChargingState.SOLAR_CHARGING_ALLOWED: "state_solar_allowed",
    ChargingState.SOLAR_CHARGING_ACTIVE: "state_solar_charging",
    ChargingState.SOLAR_SUPER_CHARGING: "state_solar_battery_assist",
    ChargingState.SOLAR_FULL_POWER: "state_full_power",
    ChargingState.SOLAR_PAUSE_LOW_BATTERY: "state_solar_paused",
    ChargingState.SOLAR_TARGET_REACHED: "state_solar_target",
    ChargingState.SOLAR_MIN_PV: "state_solar_minpv",
    ChargingState.NIGHT_IDLE: "state_night_ready",
    ChargingState.NIGHT_DISABLED: "state_night_disabled",
    ChargingState.NIGHT_CHARGING_ACTIVE: "state_night_charging",
    ChargingState.NIGHT_TARGET_REACHED: "state_night_target",
    ChargingState.NIGHT_WAITING_FOR_WINDOW: "state_night_waiting",
    ChargingState.NIGHT_TIME_EXPIRED: "state_night_expired",
    ChargingState.TARIFF_WAITING_FOR_CHEAP: "state_tariff_waiting",
    ChargingState.PHASE_GUARD_STOPPED: "state_phase_guard_stopped",
}


def get_status_message(state: str, hass: Optional[HomeAssistant] = None) -> str:
    """Get translated status message for a charging state (#62).

    Falls back to English STATUS_MESSAGES if hass is not available
    or translation key is missing.
    """
    if hass is not None:
        key = _STATE_TRANSLATION_KEYS.get(state)
        if key:
            from ..utils.translate import get_text
            text = get_text(hass, key)
            if text:
                return text
    return STATUS_MESSAGES.get(state, state)


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
