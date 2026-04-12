"""Device discovery patterns and load management constants for SEM."""
from typing import Final, Dict

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
EV_CHARGER_MANUFACTURERS: Final = {
    "keba": {
        "name": "KEBA KeContact",
        "description": "KEBA P30 EV Charger",
        "confidence_bonus": 10,
        "patterns": {
            "ev_connected": ["binary_sensor.keba*connected*", "binary_sensor.keba*plug*"],
            "ev_charging": ["binary_sensor.keba*charging*", "binary_sensor.keba*state*"],
            "ev_power": ["sensor.keba*power*", "sensor.keba*charging_power*"],
            "ev_current": ["sensor.keba*current*", "sensor.keba*charging_current*"],
            "ev_energy": ["sensor.keba*energy*", "sensor.keba*session*"]
        }
    },
    "wallbox": {
        "name": "Wallbox",
        "description": "Wallbox EV Charger",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": ["binary_sensor.wallbox*connected*"],
            "ev_charging": ["binary_sensor.wallbox*charging*"],
            "ev_power": ["sensor.wallbox*power*"],
            "ev_current": ["sensor.wallbox*current*"],
            "ev_energy": ["sensor.wallbox*energy*", "sensor.wallbox*session*"]
        }
    },
    "goe": {
        "name": "go-eCharger",
        "description": "go-eCharger Gemini/HOME+ EV Charger",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": [
                "binary_sensor.goe*connected*",
                "binary_sensor.goe*car*",
                "binary_sensor.*goe*plug*"
            ],
            "ev_charging": [
                "binary_sensor.goe*charging*",
                "binary_sensor.goe*charge_state*"
            ],
            "ev_power": [
                "sensor.goe*power*",
                "sensor.goe*nrg*"
            ],
            "ev_current": [
                "sensor.goe*current*",
                "sensor.goe*amp*"
            ],
            "ev_energy": [
                "sensor.goe*energy*",
                "sensor.goe*session*",
                "sensor.goe*wh*"
            ]
        }
    },
    "easee": {
        "name": "Easee",
        "description": "Easee Home/Charge EV Charger",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": [
                "binary_sensor.easee*cable_locked*",
                "binary_sensor.easee*connected*"
            ],
            "ev_charging": [
                "binary_sensor.easee*charging*",
                "binary_sensor.easee*is_charging*"
            ],
            "ev_power": [
                "sensor.easee*power*",
                "sensor.easee*active_power*"
            ],
            "ev_current": [
                "sensor.easee*current*",
                "sensor.easee*circuit_current*"
            ],
            "ev_energy": [
                "sensor.easee*energy*",
                "sensor.easee*session_energy*",
                "sensor.easee*lifetime_energy*"
            ]
        }
    },
    "tesla_wall_connector": {
        "name": "Tesla Wall Connector",
        "description": "Tesla Wall Connector Gen 2/3",
        "confidence_bonus": 9,
        "patterns": {
            "ev_connected": [
                "binary_sensor.tesla_wall_connector*vehicle_connected*",
                "binary_sensor.*tesla*connected*"
            ],
            "ev_charging": [
                "binary_sensor.tesla_wall_connector*charging*",
                "binary_sensor.*tesla*charging*"
            ],
            "ev_power": [
                "sensor.tesla_wall_connector*power*",
                "sensor.*tesla*power*"
            ],
            "ev_current": [
                "sensor.tesla_wall_connector*current*",
                "sensor.*tesla*current*"
            ],
            "ev_energy": [
                "sensor.tesla_wall_connector*energy*",
                "sensor.*tesla*session_energy*"
            ]
        }
    },
    "zaptec": {
        "name": "Zaptec",
        "description": "Zaptec Pro/Go EV Charger",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": [
                "binary_sensor.zaptec*connected*",
                "binary_sensor.zaptec*cable_connected*"
            ],
            "ev_charging": [
                "binary_sensor.zaptec*charging*",
                "binary_sensor.zaptec*is_charging*"
            ],
            "ev_power": [
                "sensor.zaptec*power*",
                "sensor.zaptec*charge_power*"
            ],
            "ev_current": [
                "sensor.zaptec*current*",
                "sensor.zaptec*charge_current*"
            ],
            "ev_energy": [
                "sensor.zaptec*energy*",
                "sensor.zaptec*session_energy*",
                "sensor.zaptec*total_charge_power*"
            ]
        }
    },
    "openwb": {
        "name": "OpenWB",
        "description": "OpenWB open-source wallbox",
        "confidence_bonus": 7,
        "patterns": {
            "ev_connected": [
                "binary_sensor.openwb*plugged*",
                "binary_sensor.openwb*connected*",
                "binary_sensor.*openwb*plug_state*"
            ],
            "ev_charging": [
                "binary_sensor.openwb*charging*",
                "binary_sensor.openwb*charge_state*"
            ],
            "ev_power": [
                "sensor.openwb*power*",
                "sensor.openwb*w*"
            ],
            "ev_current": [
                "sensor.openwb*current*",
                "sensor.openwb*a*"
            ],
            "ev_energy": [
                "sensor.openwb*energy*",
                "sensor.openwb*kwh*"
            ]
        }
    },
    "myenergi_zappi": {
        "name": "Myenergi Zappi",
        "description": "Myenergi Zappi solar-optimized EV charger",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": [
                "binary_sensor.zappi*connected*",
                "binary_sensor.zappi*plug*",
                "binary_sensor.myenergi_zappi*connected*"
            ],
            "ev_charging": [
                "binary_sensor.zappi*charging*",
                "binary_sensor.zappi*status*",
                "sensor.zappi*status*"
            ],
            "ev_power": [
                "sensor.zappi*power*",
                "sensor.zappi*charge_power*",
                "sensor.myenergi_zappi*power*"
            ],
            "ev_current": [
                "sensor.zappi*current*",
                "sensor.zappi*charge_current*"
            ],
            "ev_energy": [
                "sensor.zappi*energy*",
                "sensor.zappi*session_energy*",
                "sensor.zappi*charge_added*"
            ]
        }
    },
    "chargepoint": {
        "name": "ChargePoint Home Flex",
        "description": "ChargePoint Home Flex EV charger",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": [
                "binary_sensor.chargepoint*connected*",
                "binary_sensor.chargepoint*plugged*",
                "binary_sensor.*chargepoint*vehicle*"
            ],
            "ev_charging": [
                "binary_sensor.chargepoint*charging*",
                "binary_sensor.chargepoint*status*"
            ],
            "ev_power": [
                "sensor.chargepoint*power*",
                "sensor.chargepoint*charging_power*"
            ],
            "ev_current": [
                "sensor.chargepoint*current*",
                "sensor.chargepoint*charging_current*"
            ],
            "ev_energy": [
                "sensor.chargepoint*energy*",
                "sensor.chargepoint*session_energy*",
                "sensor.chargepoint*total_energy*"
            ]
        }
    },
    "heidelberg": {
        "name": "Heidelberg Energy Control",
        "description": "Heidelberg Wallbox Energy Control",
        "confidence_bonus": 8,
        "patterns": {
            "ev_connected": [
                "binary_sensor.heidelberg*connected*",
                "binary_sensor.heidelberg*plug*",
                "binary_sensor.*wallbox*connected*"
            ],
            "ev_charging": [
                "binary_sensor.heidelberg*charging*",
                "binary_sensor.heidelberg*active*"
            ],
            "ev_power": [
                "sensor.heidelberg*power*",
                "sensor.heidelberg*charging_power*",
                "sensor.heidelberg*leistung*"
            ],
            "ev_current": [
                "sensor.heidelberg*current*",
                "sensor.heidelberg*strom*"
            ],
            "ev_energy": [
                "sensor.heidelberg*energy*",
                "sensor.heidelberg*energie*"
            ]
        }
    },
    "generic_ev": {
        "name": "Generic EV Charger",
        "description": "Generic or unknown EV charger",
        "confidence_bonus": 0,
        "patterns": {
            "ev_connected": ["binary_sensor.*charger*connected*", "binary_sensor.*ev*connected*"],
            "ev_charging": ["binary_sensor.*charger*charging*", "binary_sensor.*ev*charging*"],
            "ev_power": ["sensor.*charger*power*", "sensor.*ev*power*"],
            "ev_current": ["sensor.*charger*current*", "sensor.*ev*current*"],
            "ev_energy": ["sensor.*charger*energy*", "sensor.*ev*energy*"]
        }
    }
}

# System completeness scoring
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
