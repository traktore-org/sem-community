"""Device discovery patterns and load management constants for SEM."""
import re as _re
from typing import Final

# Device discovery patterns for load management
LOAD_MANAGEMENT_DEVICE_PATTERNS: Final = {
    # Shelly devices
    "shelly": {
        "switch_pattern": "switch.shelly_*",
        "power_pattern": "sensor.shelly_*_power",
        "description": "Shelly Smart Switch"
    },
    # ESPHome devices
    "esphome": {
        "switch_pattern": "switch.*_switch",
        "power_pattern": "sensor.*_power",
        "description": "ESPHome Device"
    },
    # Generic smart switches (Tasmota, custom, etc.)
    "smart_switch": {
        "switch_pattern": "switch.*",
        "power_pattern": "sensor.*_power",
        "description": "Smart Switch with Power Monitoring"
    }
}

# EV Charger manufacturer groupings

# (#915) EV_CHARGER_MANUFACTURERS lived here: 11 brands x entity-id globs,
# the pre-registry detection matrix. It has been dead since #814 moved
# detection to the entity registry — the only reference left was a docstring
# example — and it named boxes (tesla_wall_connector, myenergi_zappi) that
# exist nowhere else in SEM. Deleting it rather than carrying it: brand
# knowledge now lives in ONE place per question — hardware_matrix.py for what
# SEM claims to support, _BRAND_HINTS for how detection recognises it, and
# consts/integration_roster.py for what the ecosystem publishes.

SYSTEM_COMPONENT_WEIGHTS: Final = {
    "solar_power": 25,      # Essential - solar production
    "grid_power": 25,       # Essential - grid monitoring
    "battery_soc": 20,      # Important - battery state
    "battery_power": 15,    # Important - battery power
    "ev_connected": 8,      # Useful - EV detection
    "ev_charging": 8,       # Useful - EV charging state
    "ev_power": 7,          # Useful - EV power monitoring
    "battery_temp": 5,      # Nice to have - battery temperature
    "ev_current": 3,        # Nice to have - EV current
    "ev_energy": 2          # Nice to have - EV energy tracking
}

# Confidence thresholds for system validation
CONFIDENCE_EXCELLENT: Final = 90    # Complete system, same manufacturer
CONFIDENCE_GOOD: Final = 70         # Most components found, mixed manufacturers
CONFIDENCE_BASIC: Final = 50        # Minimum required components only
CONFIDENCE_POOR: Final = 30         # Missing important components


# (#801) SG-Ready contacts that are not switches.
#
# The SG-Ready standard's two contacts are a pair of booleans, but the HA
# surface that carries them varies by hardware: a relay switch on most heat
# pumps, and on a Buderus/Bosch behind EMS-ESP a pair of ``text`` entities
# holding a bit string (``010000000000000``). Writing a contact's boolean is
# the same operation either way — only the service and the payload differ.
#
# A domain ABSENT from this table is a TOGGLE domain, driven by
# ``homeassistant.turn_on``/``turn_off`` exactly as SG-Ready always has been.
# A domain PRESENT is a VALUE domain: the user gives the ON and the OFF value
# for that contact and SEM writes it verbatim.
CONTACT_VALUE_SERVICES: Final[dict] = {
    # domain: (service domain, service, payload key)
    "text":         ("text", "set_value", "value"),
    "input_text":   ("input_text", "set_value", "value"),
    "number":       ("number", "set_value", "value"),
    "input_number": ("input_number", "set_value", "value"),
    "select":       ("select", "select_option", "option"),
    "input_select": ("input_select", "select_option", "option"),
}

# Every domain a SG-Ready contact may point at, in picker order: the two
# toggle domains first (what every existing install uses), then the value
# domains. Used by the config flow's EntitySelector for both contacts.
SG_READY_CONTACT_DOMAINS: Final[list] = [
    "switch", "input_boolean",
] + list(CONTACT_VALUE_SERVICES)


# (#804) A device RESTART is not a charging control.
#
# @HorizonKane's go-e Wattpilot publishes ``button.carport_wattpilot_
# 91114903_neustart`` — the button that reboots the box. SEM adopted it as
# the charger's start/stop control, so every attempt to resume charging
# rebooted the hardware and every stop wrote nothing. Each language ships
# one of these words, and each one of them contains "start".
REBOOT_WORDS: Final = (
    "restart", "neustart", "neu_starten", "herstart", "genstart", "omstart",
    "starta_om", "start_pa_nytt", "reboot", "redemarrer", "redemarrage",
    "reiniciar", "reinicio", "riavvia", "riavvio", "uruchom_ponownie",
    "ujrainditas", "uudelleenkaynnistys", "repornire",
)

#: The device class Home Assistant puts on a restart button
#: (``ButtonDeviceClass.RESTART``). It is the same in every language, which
#: a word list can never be — so it is asked FIRST and the words are the
#: fallback for integrations that declare no class.
REBOOT_DEVICE_CLASS: Final = "restart"


def names_a_reboot(entity_id: str, device_class: object = None) -> bool:
    """True when this entity is a device restart.

    ``device_class`` is the authoritative answer when the integration
    declares one: HA labels these buttons ``restart`` whatever the user's
    language. The words are the fallback, read on the entity id because
    that is where the label lands when no class is set. Used to keep a
    reboot out of every charger CONTROL role — a press SEM makes to start
    a car must never power-cycle the charger.
    """
    if isinstance(device_class, str) and device_class.lower() == REBOOT_DEVICE_CLASS:
        return True
    lowered = str(entity_id or "").lower()
    return any(word in lowered for word in REBOOT_WORDS)


# (#1042) A switch named for the PAUSE of the charge is on while stopped.
#
# A switch says in its name what "on" means. Most charger switches are named
# for the charge ("Charging enabled", "Charge control"): on is the charge.
# V2C's "Pause session" (key ``paused``) is named for the pause: core's
# ``turn_on`` calls ``evse.pause()``.
PAUSE_WORDS: Final = frozenset({"pause", "paused"})
RESUME_WORDS: Final = frozenset({"resume"})

#: The words a pause of the CHARGE may carry beside the pause. Any other word
#: says something else: Wallbox's ``pause_resume`` is on while it charges,
#: V2C's ``pause_dynamic`` pauses the box's own solar modulation, and
#: ``not_paused`` means the opposite.
CHARGE_PAUSE_WORDS: Final = frozenset({
    "session", "charge", "charger", "charging", "ev", "evse", "car"})


def _name_words(name: object) -> set:
    return set(_re.split(r"[^a-z0-9]+", str(name or "").lower())) - {""}


def names_a_pause(name: object) -> bool:
    """True when ``name`` says pause or paused as a whole word — of anything
    (``pausenraum`` is not one)."""
    return bool(_name_words(name) & PAUSE_WORDS)


def names_another_pause(name: object) -> bool:
    """True when ``name`` pauses something other than the charge (V2C's
    ``pause_dynamic``: the box's solar modulation) — never a pause/resume
    toggle, which IS the charge's start and stop."""
    return (names_a_pause(name) and not names_a_charge_pause(name)
            and not _name_words(name) & RESUME_WORDS)


def names_a_charge_pause(name: object) -> bool:
    """True when ``name`` — a translation key or an entity's own name — is a
    pause of the charge and nothing else, so its "on" is the stop."""
    words = _name_words(name)
    return bool(words & PAUSE_WORDS) and words <= PAUSE_WORDS | CHARGE_PAUSE_WORDS


# (#1048, D6) Which supply phase a load sits on. The phase guard sheds a
# phase's own loads first: ``L1``/``L2``/``L3`` draw on that line alone,
# ``3ph`` on all three; ``unknown`` — the default, because SEM cannot see a
# wiring diagram — is shed for a phase only after every load known to sit on
# it. A load's phase is the user's to say; a charger's is measured.
LOAD_PHASES: Final = ("L1", "L2", "L3", "3ph", "unknown")
DEFAULT_LOAD_PHASE: Final = "unknown"
_PHASE_ALIASES: Final = {
    "l1": "L1", "l2": "L2", "l3": "L3",
    "3ph": "3ph", "3": "3ph", "3p": "3ph", "three": "3ph",
    "unknown": "unknown", "": "unknown",
}


def load_phase(value: object) -> str:
    """The phase a stored or typed value names, ``unknown`` for anything
    that names none — a load is never placed on a line it was not given."""
    return _PHASE_ALIASES.get(str(value if value is not None else "").strip().lower(),
                              DEFAULT_LOAD_PHASE)


def is_load_phase(value: object) -> bool:
    """True when ``value`` names a phase exactly as the service takes it."""
    return isinstance(value, str) and value in LOAD_PHASES
