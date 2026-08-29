"""Constants for the Zaptec simulator (#804)."""
DOMAIN = "zaptec_sim"

# The real integration's entity-description keys, verbatim. Detection matches
# on these through the unique_id suffix, so they are the load-bearing part of
# the whole fixture — a typo here makes the simulator prove nothing.
KEY_AVAILABLE_CURRENT = "available_current"
KEY_PHASE_SWITCH_CURRENT = "three_to_one_phase_switch_current"
KEY_CHARGER_MAX_CURRENT = "charger_max_current"
KEY_CHARGER_MIN_CURRENT = "charger_min_current"
KEY_CABLE_CONNECTED = "cable_connected"
KEY_CHARGING = "charging"
KEY_CHARGE_POWER = "charge_power"
KEY_SESSION_ENERGY = "total_charge_power_session"
KEY_OPERATION_MODE = "charger_operation_mode"
KEY_RESUME = "resume_charging"

INSTALL_ID = "sim-installation-1"
CHARGER_ID = "sim-charger-1"

# Dutch, owner-prefixed — @coppe218's registry, which is what broke detection.
DEFAULT_PREFIX = "Guido Coppes"

NAMES_NL = {
    KEY_AVAILABLE_CURRENT: "Beschikbare stroom",
    KEY_PHASE_SWITCH_CURRENT: "Terugschakelen van drie naar een fase",
    KEY_CHARGER_MAX_CURRENT: "Maximale laadstroom",
    KEY_CHARGER_MIN_CURRENT: "Minimale laadstroom",
    KEY_CABLE_CONNECTED: "Kabel aangesloten",
    KEY_CHARGING: "Bezig met laden",
    KEY_CHARGE_POWER: "Laadvermogen",
    KEY_SESSION_ENERGY: "Sessie energie",
    KEY_OPERATION_MODE: "Laadmodus",
    KEY_RESUME: "Hervat laden",
}

VOLTAGE = 230.0
DEFAULT_MAX_A = 32.0
DEFAULT_MIN_A = 6.0
PHASE_SWITCH_1P_A = 32.0   # EVCC: ThreeToOnePhaseSwitchCurrent = 32 → 1-phase
PHASE_SWITCH_3P_A = 0.0    # 0 → 3-phase
