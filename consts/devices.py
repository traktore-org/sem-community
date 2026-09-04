"""Device discovery patterns and load management constants for SEM."""
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
