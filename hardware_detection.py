"""EV charger detection for SEM Solar Energy Management.

This module provides detection of EV charger control entities. Solar, grid, and
battery sensors are now read from the HA Energy Dashboard (HA 2025.12+).

EV charger sensors are still detected here because the Energy Dashboard only
provides power/energy sensors, not the control entities needed for:
- Checking if a car is connected (binary_sensor.*_plug_connected)
- Checking if charging is active (binary_sensor.*_charging)
- Controlling charging current (number.*_charging_current, service calls)

Detection is integration-aware:
1. **Integration-Aware Detection**: Recognizes entity naming conventions from
   KEBA, Easee, Wallbox, go-eCharger, OpenWB, Zaptec, ChargePoint, Heidelberg, etc.

2. **Priority-Based Matching**: Each pattern has a priority score (1-10):
   - 10: Integration-specific patterns (highest accuracy)
   - 8-9: Well-known manufacturer patterns
   - 3-5: Common generic patterns

"""
import logging
import re
from typing import Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry

_LOGGER = logging.getLogger(__name__)

# EV charger integration-specific patterns
EV_INTEGRATION_PATTERNS = {
    "keba": {
        "integration_name": "KEBA KeContact",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.keba_*_plug_connected", "KEBA - Plug Connected", 10),
                ("binary_sensor.*_keba_*_plug*", "KEBA - Plug Status", 9),
            ],
            "ev_charging": [
                ("binary_sensor.keba_*_charging", "KEBA - Charging Status", 10),
                ("sensor.keba_*_state", "KEBA - Charger State", 8),
            ],
            "ev_charging_power": [
                ("sensor.keba_*_charging_power", "KEBA - Charging Power", 10),
                ("sensor.keba_*_power", "KEBA - Power", 9),
            ],
            "ev_current": [
                ("sensor.keba_*_charging_current", "KEBA - Charging Current", 10),
                ("sensor.keba_*_current", "KEBA - Current", 9),
            ],
            "ev_session_energy": [
                ("sensor.keba_*_session_energy", "KEBA - Session Energy", 10),
            ],
            "ev_total_energy": [
                ("sensor.keba_*_total_energy", "KEBA - Total Energy", 10),
            ],
        }
    },
    "easee": {
        "integration_name": "Easee",
        "patterns": {
            "ev_connected": [
                ("sensor.easee_status", "Easee - Status", 10),
                ("sensor.*_easee_status", "Easee - Multi Status", 9),
            ],
            "ev_charging": [
                ("sensor.easee_status", "Easee - Charging Status", 10),
                ("binary_sensor.easee_*_charging", "Easee - Charging Binary", 9),
                ("sensor.*_easee_status", "Easee - Multi Charging Status", 8),
            ],
            "ev_charging_power": [
                ("sensor.easee_power", "Easee - Power", 10),
                ("sensor.*_easee_power", "Easee - Multi Power", 9),
                ("sensor.easee_*_power", "Easee - Power Variant", 8),
            ],
            "ev_current": [
                ("sensor.easee_current", "Easee - Current", 10),
                ("sensor.*_easee_current", "Easee - Multi Current", 9),
                ("sensor.easee_*_current", "Easee - Current Variant", 8),
            ],
            "ev_session_energy": [
                ("sensor.easee_session_energy", "Easee - Session Energy", 10),
                ("sensor.*_easee_session*", "Easee - Multi Session", 9),
            ],
            "ev_total_energy": [
                ("sensor.easee_total_energy", "Easee - Total Energy", 10),
                ("sensor.*_easee_total*", "Easee - Multi Total", 9),
            ],
        }
    },
    "wallbox": {
        "integration_name": "Wallbox",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.wallbox*connected*", "Wallbox - Connected", 8),
                ("binary_sensor.wallbox*plug*", "Wallbox - Plug Status", 7),
            ],
            "ev_charging": [
                ("binary_sensor.wallbox*charging*", "Wallbox - Charging", 8),
                ("sensor.wallbox*state*", "Wallbox - State", 7),
            ],
            "ev_charging_power": [
                ("sensor.wallbox*charging_power*", "Wallbox - Charging Power", 9),
                ("sensor.wallbox*power*", "Wallbox - Power", 8),
            ],
            "ev_current": [
                ("sensor.wallbox*charging_current*", "Wallbox - Charging Current", 9),
                ("sensor.wallbox*current*", "Wallbox - Current", 8),
            ],
            "ev_session_energy": [
                ("sensor.wallbox*session*energy*", "Wallbox - Session Energy", 9),
                ("sensor.wallbox*session*", "Wallbox - Session", 8),
            ],
            "ev_total_energy": [
                ("sensor.wallbox*total*energy*", "Wallbox - Total Energy", 8),
                ("sensor.wallbox*total*", "Wallbox - Total", 7),
            ],
        }
    },
    "goecharger": {
        "integration_name": "go-eCharger",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.goe*connected*", "go-eCharger - Connected", 8),
                ("binary_sensor.go_e*plug*", "go-eCharger - Plug", 7),
            ],
            "ev_charging": [
                ("binary_sensor.goe*charging*", "go-eCharger - Charging", 8),
                ("sensor.go_e*status*", "go-eCharger - Status", 7),
            ],
            "ev_charging_power": [
                ("sensor.goe*power*", "go-eCharger - Power", 8),
                ("sensor.go_e*power*", "go-eCharger - Power", 8),
            ],
            "ev_current": [
                ("sensor.goe*current*", "go-eCharger - Current", 8),
                ("sensor.go_e*amp*", "go-eCharger - Amperage", 7),
            ],
            "ev_session_energy": [
                ("sensor.goe*session*", "go-eCharger - Session", 8),
                ("sensor.go_e*session*", "go-eCharger - Session", 8),
            ],
            "ev_total_energy": [
                ("sensor.goe*total*energy*", "go-eCharger - Total Energy", 8),
                ("sensor.go_e*total*", "go-eCharger - Total", 7),
            ],
        }
    },
    "openwb": {
        "integration_name": "OpenWB",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.openwb*connected*", "OpenWB - Connected", 8),
                ("binary_sensor.openwb*plug*", "OpenWB - Plug", 7),
            ],
            "ev_charging": [
                ("binary_sensor.openwb*charging*", "OpenWB - Charging", 8),
                ("sensor.openwb*status*", "OpenWB - Status", 7),
            ],
            "ev_charging_power": [
                ("sensor.openwb*charging*power*", "OpenWB - Charging Power", 9),
                ("sensor.openwb*power*", "OpenWB - Power", 8),
            ],
            "ev_current": [
                ("sensor.openwb*current*", "OpenWB - Current", 8),
                ("sensor.openwb*amp*", "OpenWB - Amperage", 7),
            ],
            "ev_session_energy": [
                ("sensor.openwb*session*", "OpenWB - Session", 8),
            ],
            "ev_total_energy": [
                ("sensor.openwb*total*energy*", "OpenWB - Total Energy", 8),
            ],
        }
    },
    "zaptec": {
        "integration_name": "Zaptec",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.zaptec_*_cable_connected", "Zaptec - Cable Connected", 10),
                ("binary_sensor.zaptec_*_connected", "Zaptec - Connected", 9),
            ],
            "ev_charging": [
                ("binary_sensor.zaptec_*_charging", "Zaptec - Charging", 10),
                ("sensor.zaptec_*_charger_operation_mode", "Zaptec - Operation Mode", 8),
            ],
            "ev_charging_power": [
                ("sensor.zaptec_*_charge_power", "Zaptec - Charge Power", 10),
                ("sensor.zaptec_*_power", "Zaptec - Power", 9),
            ],
            "ev_current": [
                ("number.zaptec_*_available_current", "Zaptec - Available Current", 10),
                ("sensor.zaptec_*_current", "Zaptec - Current", 9),
            ],
            "ev_session_energy": [
                ("sensor.zaptec_*_session_energy", "Zaptec - Session Energy", 10),
                ("sensor.zaptec_*_total_charge_power_session", "Zaptec - Session Charge", 9),
            ],
            "ev_total_energy": [
                ("sensor.zaptec_*_total_charge_power", "Zaptec - Total Energy", 10),
            ],
        }
    },
    "chargepoint": {
        "integration_name": "ChargePoint",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.chargepoint_*_connected", "ChargePoint - Connected", 10),
                ("binary_sensor.chargepoint_*_plugged*", "ChargePoint - Plugged", 9),
            ],
            "ev_charging": [
                ("binary_sensor.chargepoint_*_charging", "ChargePoint - Charging", 10),
                ("sensor.chargepoint_*_status", "ChargePoint - Status", 8),
            ],
            "ev_charging_power": [
                ("sensor.chargepoint_*_power_output", "ChargePoint - Power Output", 10),
                ("sensor.chargepoint_*_power", "ChargePoint - Power", 9),
            ],
            "ev_current": [
                ("number.chargepoint_*_charging_amperage_limit", "ChargePoint - Amperage Limit", 10),
                ("sensor.chargepoint_*_current", "ChargePoint - Current", 9),
            ],
            "ev_session_energy": [
                ("sensor.chargepoint_*_session_energy", "ChargePoint - Session Energy", 10),
            ],
            "ev_total_energy": [
                ("sensor.chargepoint_*_energy_output", "ChargePoint - Energy Output", 10),
                ("sensor.chargepoint_*_total_energy", "ChargePoint - Total Energy", 9),
            ],
        }
    },
    "heidelberg": {
        "integration_name": "Heidelberg Energy Control",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.heidelberg_*_connected", "Heidelberg - Connected", 10),
                ("binary_sensor.heidelberg_*_plug*", "Heidelberg - Plug", 9),
            ],
            "ev_charging": [
                ("binary_sensor.heidelberg_*_charging", "Heidelberg - Charging", 10),
                ("binary_sensor.heidelberg_*_active", "Heidelberg - Active", 8),
            ],
            "ev_charging_power": [
                ("sensor.heidelberg_*_charging_power", "Heidelberg - Charging Power", 10),
                ("sensor.heidelberg_*_power", "Heidelberg - Power", 9),
            ],
            "ev_current": [
                ("number.heidelberg_*_charging_current_limit", "Heidelberg - Current Limit", 10),
                ("sensor.heidelberg_*_current", "Heidelberg - Current", 9),
            ],
            "ev_session_energy": [
                ("sensor.heidelberg_*_session_energy", "Heidelberg - Session Energy", 10),
                ("sensor.heidelberg_*_energy_session", "Heidelberg - Energy Session", 9),
            ],
            "ev_total_energy": [
                ("sensor.heidelberg_*_total_energy", "Heidelberg - Total Energy", 10),
                ("sensor.heidelberg_*_energy_total", "Heidelberg - Energy Total", 9),
            ],
        }
    },
    "ocpp": {
        "integration_name": "OCPP",
        "patterns": {
            "ev_connected": [
                ("sensor.ocpp_*_status*connector*", "OCPP - Connector Status", 10),
                ("sensor.ocpp_*_status", "OCPP - Status", 9),
            ],
            "ev_charging": [
                ("sensor.ocpp_*_status*connector*", "OCPP - Connector Status", 10),
                ("sensor.ocpp_*_status", "OCPP - Status", 9),
            ],
            "ev_charging_power": [
                ("sensor.ocpp_*_power_active_import", "OCPP - Active Import Power", 10),
                ("sensor.ocpp_*_power*", "OCPP - Power", 8),
            ],
            "ev_current": [
                ("number.ocpp_*_maximum_current", "OCPP - Maximum Current", 10),
                ("sensor.ocpp_*_current_offered", "OCPP - Current Offered", 9),
                ("sensor.ocpp_*_current_import", "OCPP - Current Import", 8),
            ],
            "ev_session_energy": [
                ("sensor.ocpp_*_energy_active_import_register", "OCPP - Energy Register", 10),
                ("sensor.ocpp_*_session_energy", "OCPP - Session Energy", 9),
            ],
            "ev_total_energy": [
                ("sensor.ocpp_*_energy_active_import_register", "OCPP - Energy Register", 10),
            ],
        }
    },
    "alfen": {
        "integration_name": "Alfen Eve",
        "patterns": {
            "ev_connected": [
                ("sensor.*alfen*main_state*socket*", "Alfen - Main State", 10),
                ("sensor.*alfen*status*socket*", "Alfen - Status", 9),
            ],
            "ev_charging": [
                ("sensor.*alfen*main_state*socket*", "Alfen - Main State", 10),
                ("sensor.*alfen*status*socket*", "Alfen - Status", 9),
            ],
            "ev_charging_power": [
                ("sensor.*alfen*active_power_total*socket*", "Alfen - Active Power", 10),
                ("sensor.*alfen*active_power*", "Alfen - Active Power Alt", 8),
            ],
            "ev_current": [
                ("number.*alfen*max_current*socket*", "Alfen - Max Current", 10),
                ("number.*alfen*current_limit*", "Alfen - Current Limit", 9),
                ("sensor.*alfen*current*socket*", "Alfen - Current", 7),
            ],
            "ev_session_energy": [
                ("sensor.*alfen*transaction*charging*", "Alfen - Session Energy", 10),
                ("sensor.*alfen*meter_reading*", "Alfen - Meter Reading", 8),
            ],
            "ev_total_energy": [
                ("sensor.*alfen*meter_reading*socket*", "Alfen - Total Energy", 10),
            ],
        }
    },
    "ohme": {
        "integration_name": "Ohme",
        "patterns": {
            "ev_connected": [
                ("sensor.ohme_*_status", "Ohme - Status", 10),
            ],
            "ev_charging": [
                ("sensor.ohme_*_status", "Ohme - Status", 10),
            ],
            "ev_charging_power": [
                ("sensor.ohme_*_power", "Ohme - Power", 10),
            ],
            "ev_current": [
                ("sensor.ohme_*_current", "Ohme - Current", 10),
            ],
            "ev_session_energy": [
                ("sensor.ohme_*_energy", "Ohme - Energy", 10),
            ],
            "ev_total_energy": [
                ("sensor.ohme_*_energy", "Ohme - Total Energy", 9),
            ],
        }
    },
    "peblar": {
        "integration_name": "Peblar",
        "patterns": {
            "ev_connected": [
                ("sensor.peblar_*_state", "Peblar - State", 10),
            ],
            "ev_charging": [
                ("sensor.peblar_*_state", "Peblar - State", 10),
            ],
            "ev_charging_power": [
                ("sensor.peblar_*_power", "Peblar - Power", 10),
            ],
            "ev_current": [
                ("number.peblar_*_charge_limit", "Peblar - Charge Limit", 10),
                ("sensor.peblar_*_current", "Peblar - Current", 9),
            ],
            "ev_session_energy": [
                ("sensor.peblar_*_session_energy", "Peblar - Session Energy", 10),
            ],
            "ev_total_energy": [
                ("sensor.peblar_*_lifetime_energy", "Peblar - Lifetime Energy", 10),
            ],
        }
    },
    "v2c": {
        "integration_name": "V2C Trydan",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.v2c_*_connected", "V2C - Connected", 10),
            ],
            "ev_charging": [
                ("binary_sensor.v2c_*_charging", "V2C - Charging", 10),
            ],
            "ev_charging_power": [
                ("sensor.v2c_*_charge_power", "V2C - Charge Power", 10),
            ],
            "ev_current": [
                ("number.v2c_*_intensity", "V2C - Intensity", 10),
            ],
            "ev_session_energy": [
                ("sensor.v2c_*_charge_energy", "V2C - Charge Energy", 10),
            ],
            "ev_total_energy": [
                ("sensor.v2c_*_charge_energy", "V2C - Total Energy", 9),
            ],
        }
    },
    "blue_current": {
        "integration_name": "Blue Current",
        "patterns": {
            "ev_connected": [
                ("sensor.*blue_current*vehicle_status*", "Blue Current - Vehicle Status", 10),
                ("sensor.*blue_current*activity*", "Blue Current - Activity", 9),
            ],
            "ev_charging": [
                ("sensor.*blue_current*activity*", "Blue Current - Activity", 10),
            ],
            "ev_charging_power": [
                ("sensor.*blue_current*total_kw*", "Blue Current - Total kW", 10),
                ("sensor.*blue_current*total_power*", "Blue Current - Total Power", 9),
            ],
            "ev_current": [
                ("sensor.*blue_current*avg_current*", "Blue Current - Avg Current", 10),
                ("sensor.*blue_current*max_usage*", "Blue Current - Max Usage", 9),
            ],
            "ev_session_energy": [
                ("sensor.*blue_current*actual_kwh*", "Blue Current - Energy kWh", 10),
                ("sensor.*blue_current*energy_usage*", "Blue Current - Energy Usage", 9),
            ],
            "ev_total_energy": [
                ("sensor.*blue_current*actual_kwh*", "Blue Current - Total kWh", 10),
            ],
        }
    },
    "openevse": {
        "integration_name": "OpenEVSE",
        "patterns": {
            "ev_connected": [
                ("binary_sensor.openevse_*_vehicle", "OpenEVSE - Vehicle Plug", 10),
                ("sensor.openevse_*_status", "OpenEVSE - Status", 9),
                ("sensor.openevse_*_state", "OpenEVSE - State", 8),
            ],
            "ev_charging": [
                ("sensor.openevse_*_status", "OpenEVSE - Status", 10),
                ("sensor.openevse_*_state", "OpenEVSE - State", 9),
            ],
            "ev_charging_power": [
                ("sensor.openevse_*_current_power", "OpenEVSE - Current Power", 10),
                ("sensor.openevse_*_charging_power", "OpenEVSE - Charging Power", 9),
            ],
            "ev_current": [
                ("number.openevse_*_max_current*", "OpenEVSE - Max Current", 10),
                ("sensor.openevse_*_charging_current", "OpenEVSE - Charging Current", 9),
                ("sensor.openevse_*_current_capacity", "OpenEVSE - Current Capacity", 8),
            ],
            "ev_session_energy": [
                ("sensor.openevse_*_usage_session", "OpenEVSE - Session Usage", 10),
                ("sensor.openevse_*_usage_this_session", "OpenEVSE - Session Usage Alt", 9),
            ],
            "ev_total_energy": [
                ("sensor.openevse_*_usage_total", "OpenEVSE - Total Usage", 10),
                ("sensor.openevse_*_total_energy*", "OpenEVSE - Total Energy", 9),
            ],
        }
    },
}

# Generic EV charger patterns (fallback)
GENERIC_EV_PATTERNS = {
    "ev_connected": [
        ("binary_sensor.*charger*connected*", "Generic Charger - Connected", 3),
        ("binary_sensor.*ev*connected*", "Generic EV - Connected", 2),
        # NOTE: removed "binary_sensor.*plug*" — too greedy, matched generic smart plugs.
        # Use registry-based discovery for accurate plug detection.
    ],
    "ev_charging": [
        ("binary_sensor.*charger*charging*", "Generic Charger - Charging", 3),
        ("binary_sensor.*ev*charging*", "Generic EV - Charging", 2),
    ],
    "ev_charging_power": [
        ("sensor.*charger*power*", "Generic Charger - Power", 3),
        ("sensor.*ev*power*", "Generic EV - Power", 2),
        ("sensor.*wallbox*", "Generic Wallbox", 1),
    ],
    "ev_current": [
        ("sensor.*charger*current*", "Generic Charger - Current", 3),
        ("sensor.*ev*current*", "Generic EV - Current", 2),
    ],
    "ev_session_energy": [
        ("sensor.*charger*session*", "Generic Charger - Session", 3),
        ("sensor.*ev*session*", "Generic EV - Session", 2),
    ],
    "ev_total_energy": [
        ("sensor.*charger*total*energy*", "Generic Charger - Total Energy", 3),
        ("sensor.*ev*total*energy*", "Generic EV - Total Energy", 2),
    ],
}


class EVChargerDetector:
    """Auto-detect EV charger entities with integration awareness."""

    def __init__(self, hass: HomeAssistant):
        """Initialize EV charger detector."""
        self.hass = hass
        self._entity_registry = entity_registry.async_get(hass)

    def get_all_entities(self) -> List[str]:
        """Get all available entity IDs."""
        return list(self.hass.states.async_entity_ids())

    def _get_merged_patterns(self) -> Dict[str, List[Tuple[str, str, int]]]:
        """Merge integration-specific patterns with generic patterns.

        Returns:
            Dict with sensor type as key, list of (pattern, description, priority) tuples
        """
        merged = {}

        # Add integration-specific patterns first (highest priority)
        for integration_name, integration_data in EV_INTEGRATION_PATTERNS.items():
            for sensor_type, patterns in integration_data["patterns"].items():
                if sensor_type not in merged:
                    merged[sensor_type] = []
                merged[sensor_type].extend(patterns)

        # Add generic patterns
        for sensor_type, patterns in GENERIC_EV_PATTERNS.items():
            if sensor_type not in merged:
                merged[sensor_type] = []
            merged[sensor_type].extend(patterns)

        # Sort by priority (highest first)
        for sensor_type in merged:
            merged[sensor_type] = sorted(
                merged[sensor_type],
                key=lambda x: x[2],
                reverse=True
            )

        return merged

    def detect_ev_entities(self) -> Dict[str, List[Tuple[str, str, bool, int]]]:
        """Auto-detect EV charger entities with validation and priority scoring.

        Returns:
            Dict with sensor type as key, list of (entity_id, description, exists, priority) tuples
        """
        detected = {}
        all_entities = self.get_all_entities()
        merged_patterns = self._get_merged_patterns()

        for sensor_type, patterns in merged_patterns.items():
            detected[sensor_type] = []

            for pattern, description, priority in patterns:
                matches = self._find_pattern_matches(pattern, all_entities)
                for entity_id in matches:
                    exists = self._validate_entity(entity_id, sensor_type)
                    detected[sensor_type].append((entity_id, description, exists, priority))

        # Sort by priority and validation status
        for sensor_type in detected:
            detected[sensor_type] = sorted(
                detected[sensor_type],
                key=lambda x: (x[2], x[3]),  # Sort by exists (True first), then priority
                reverse=True
            )

        return detected

    def _find_pattern_matches(self, pattern: str, entities: List[str]) -> List[str]:
        """Find entities matching a pattern."""
        import fnmatch

        if "*" in pattern:
            return fnmatch.filter(entities, pattern)
        else:
            return [pattern] if pattern in entities else []

    def _validate_entity(self, entity_id: str, sensor_type: str) -> bool:
        """Validate entity exists and has reasonable values."""
        state = self.hass.states.get(entity_id)
        if not state:
            return False

        if state.state in ("unknown", "unavailable", "None"):
            return False

        try:
            if sensor_type == "ev_charging_power":
                value = float(state.state)
                return -20000 <= value <= 20000

            elif sensor_type in ["ev_connected", "ev_charging"]:
                # Accept binary_sensor values AND regular sensor status values
                # used by Easee, Wallbox, GoodWe, OCPP, Ohme, Alfen, etc. (#68, #105)
                return state.state.lower() in (
                    "on", "off", "true", "false", "0", "1",
                    "connected", "disconnected", "ready_to_charge",
                    "awaiting_start", "awaiting_authorization",
                    "charging", "completed", "ready", "idle",
                    "not_connected", "paused", "error",
                    # OCPP status values
                    "available", "preparing", "suspended_ev",
                    "suspended_evse", "finishing", "faulted",
                    # Ohme status values
                    "plugged in", "unplugged",
                    # Alfen status values
                    "ev connected", "charging power on",
                    # Peblar status values
                    "no ev connected",
                    # Blue Current status values
                    "a", "b1", "b2", "c1", "c2", "d1", "d2", "e", "f",
                )

            else:
                return True

        except (ValueError, TypeError):
            return False

    def get_best_match(self, sensor_type: str) -> Optional[str]:
        """Get the best matching entity for a sensor type.

        Returns the highest priority valid entity.
        """
        detected = self.detect_ev_entities()
        if sensor_type in detected and detected[sensor_type]:
            for entity_id, description, exists, priority in detected[sensor_type]:
                if exists:
                    _LOGGER.info(
                        f"Auto-detected {sensor_type}: {entity_id} ({description}) "
                        f"[Priority: {priority}]"
                    )
                    return entity_id
        return None

    def get_detected_ev_integrations(self) -> Dict[str, bool]:
        """Detect which EV charger integrations are installed.

        Returns:
            Dict with integration name as key and detection status as value
        """
        detected_integrations = {}
        all_entities = self.get_all_entities()

        for integration_name, integration_data in EV_INTEGRATION_PATTERNS.items():
            detected_integrations[integration_name] = False

            for sensor_type, patterns in integration_data["patterns"].items():
                for pattern, description, priority in patterns:
                    matches = self._find_pattern_matches(pattern, all_entities)
                    if matches:
                        for entity_id in matches:
                            if self._validate_entity(entity_id, sensor_type):
                                detected_integrations[integration_name] = True
                                _LOGGER.info(
                                    f"Detected EV integration: {integration_data['integration_name']} "
                                    f"(found valid entity: {entity_id})"
                                )
                                break
                    if detected_integrations[integration_name]:
                        break
                if detected_integrations[integration_name]:
                    break

        return detected_integrations

    def validate_ev_configuration(self, config: Dict[str, str]) -> Dict[str, str]:
        """Validate EV charger configuration.

        Returns:
            Dict with validation errors (empty if all valid)
        """
        errors = {}

        required_sensors = [
            "ev_connected_sensor",
            "ev_charging_sensor",
            "ev_charging_power_sensor",
        ]

        for sensor_key in required_sensors:
            entity_id = config.get(sensor_key)
            if not entity_id:
                errors[sensor_key] = "Required sensor not configured"
                continue

            sensor_type = sensor_key.replace("_sensor", "")
            if not self._validate_entity(entity_id, sensor_type):
                errors[sensor_key] = f"Entity {entity_id} not found or invalid"

        return errors

    def get_suggested_ev_defaults(self) -> Dict[str, str]:
        """Get suggested EV charger default values based on auto-detection."""
        suggestions = {}

        sensor_mappings = {
            "ev_connected_sensor": "ev_connected",
            "ev_charging_sensor": "ev_charging",
            "ev_charging_power_sensor": "ev_charging_power",
            "ev_current_sensor": "ev_current",
            "ev_session_energy_sensor": "ev_session_energy",
            "ev_total_energy_sensor": "ev_total_energy",
        }

        for config_key, detect_key in sensor_mappings.items():
            suggested = self.get_best_match(detect_key)
            if suggested:
                suggestions[config_key] = suggested
            else:
                suggestions[config_key] = ""

        return suggestions


# Backward compatibility alias
HardwareDetector = EVChargerDetector


# ============================================================
# Entity-registry-based EV charger discovery
# ============================================================
# Queries the entity registry for entities belonging to supported
# EV charger integrations and maps them to config keys.

_EV_CHARGER_PLATFORMS = [
    ("keba", _discover_keba),
    ("easee", _discover_easee),
    ("goecharger", _discover_goecharger),
    ("goecharger_mqtt", _discover_goecharger_mqtt),
    ("goecharger_api2", _discover_goecharger_mqtt),
    ("wallbox", _discover_wallbox),
    ("zaptec", _discover_zaptec),
    ("chargepoint", _discover_chargepoint),
    ("heidelberg_energy_control", _discover_heidelberg),
    ("openwb2mqtt", _discover_openwb),
    ("openwbmqtt", _discover_openwb),
    ("ocpp", _discover_ocpp),
    ("ohme", _discover_ohme),
    ("peblar", _discover_peblar),
    ("v2c", _discover_v2c),
    ("alfen_wallbox", _discover_alfen),
    ("openevse", _discover_openevse),
    ("blue_current", _discover_blue_current),
]


def discover_all_ev_chargers_from_registry(
    hass: HomeAssistant,
) -> List[Dict[str, str]]:
    """Auto-discover ALL EV chargers from known integrations via entity registry.

    Returns a list of charger configs, one per detected charger. Each dict
    contains the same keys as discover_ev_charger_from_registry().
    The first entry is the "primary" charger for backward compatibility.

    For charger integrations that expose multiple devices (e.g., 2 Wallbox
    Pulsars), each device produces a separate entry grouped by device_id.
    """
    entity_reg = entity_registry.async_get(hass)
    chargers: List[Dict[str, str]] = []

    for platform, discover_fn in _EV_CHARGER_PLATFORMS:
        entities = [
            e for e in entity_reg.entities.values()
            if e.platform == platform and not e.disabled_by
        ]
        if not entities:
            continue

        # Group entities by device_id to detect multiple chargers
        # of the same brand (e.g., 2 Wallbox Pulsars)
        devices: Dict[Optional[str], list] = {}
        for e in entities:
            devices.setdefault(e.device_id, []).append(e)

        for device_id, device_entities in devices.items():
            result = discover_fn(device_entities)
            if result:
                result["_platform"] = platform
                if device_id:
                    result["_device_id"] = device_id
                _LOGGER.info(
                    "Auto-discovered EV charger from %s (device %s): %s",
                    platform,
                    device_id or "default",
                    {k: v for k, v in result.items() if not k.startswith("_")},
                )
                chargers.append(result)

    return chargers


def discover_ev_charger_from_registry(hass: HomeAssistant) -> Dict[str, str]:
    """Auto-discover EV charger config from known integrations via entity registry.

    Backward-compatible wrapper: returns the first detected charger.

    Returns:
        Dict with config keys (ev_connected_sensor, ev_charging_sensor, etc.)
        Only includes keys where entities were found.
    """
    all_chargers = discover_all_ev_chargers_from_registry(hass)
    return all_chargers[0] if all_chargers else {}


def _discover_keba(entities) -> Dict[str, str]:
    """Discover EV charger config from KEBA integration entities."""
    result: Dict[str, str] = {}

    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class

        if eid.startswith("binary_sensor.") and dc == "plug":
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and dc == "power":
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result["ev_session_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "current":
            result["ev_current_sensor"] = eid

    if result:
        result["ev_charger_service"] = "keba.set_current"
        result["ev_service_param_name"] = "current"
        target = result.get("ev_connected_sensor")
        if target:
            result["ev_charger_service_entity_id"] = target

    return result


def _discover_easee(entities) -> Dict[str, str]:
    """Discover EV charger config from Easee integration."""
    result: Dict[str, str] = {}
    device_id = None
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        # Easee uses sensor (not binary_sensor) for status (#68)
        if eid.startswith("sensor.") and "status" in eid and dc is None:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
            if entry.device_id:
                device_id = entry.device_id
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
            if entry.device_id:
                device_id = entry.device_id
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result["ev_session_energy_sensor"] = eid
    if result:
        # Use dynamic limit (preferred, no flash wear) over max_limit
        result["ev_charger_service"] = "easee.set_charger_dynamic_limit"
        result["ev_service_param_name"] = "current"
        if device_id:
            result["ev_service_device_id"] = device_id
        # Start/stop via action_command service
        result["ev_start_service"] = "easee.action_command"
        result["ev_start_service_data"] = '{"action_command": "resume"}'
        result["ev_stop_service"] = "easee.action_command"
        result["ev_stop_service_data"] = '{"action_command": "pause"}'
    return result


def _discover_goecharger(entities) -> Dict[str, str]:
    """Discover EV charger config from go-eCharger integration."""
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and dc == "plug":
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in eid:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("number.") and ("amp" in eid or "current" in eid):
            result["ev_current_control_entity"] = eid
    return result


def _discover_wallbox(entities) -> Dict[str, str]:
    """Discover EV charger config from Wallbox integration."""
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and "plug" in eid:
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in eid:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("number.") and "current" in eid:
            result["ev_current_control_entity"] = eid
        # Wallbox pause/resume switch
        if eid.startswith("switch.") and "pause" in eid:
            result["ev_start_stop_entity"] = eid
    return result


def _discover_zaptec(entities) -> Dict[str, str]:
    """Discover EV charger config from Zaptec integration."""
    result: Dict[str, str] = {}
    device_id = None
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and ("cable" in eid or "connect" in eid):
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in eid:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
            if entry.device_id:
                device_id = entry.device_id
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result["ev_session_energy_sensor"] = eid
        if eid.startswith("number.") and "current" in eid:
            result["ev_current_control_entity"] = eid
    if result:
        # Prefer number entity control if found, otherwise use service
        if "ev_current_control_entity" not in result:
            result["ev_charger_service"] = "zaptec.limit_current"
            result["ev_service_param_name"] = "available_current"
            if device_id:
                result["ev_service_device_id"] = device_id
        # Discover resume/stop button entities
        for entry in entities:
            eid = entry.entity_id
            if eid.startswith("button.") and "resume" in eid:
                result["ev_start_stop_entity"] = eid  # button for start
    return result


def _discover_chargepoint(entities) -> Dict[str, str]:
    """Discover EV charger config from ChargePoint integration."""
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and ("connect" in eid or "plug" in eid):
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in eid:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result["ev_session_energy_sensor"] = eid
        if eid.startswith("number.") and ("amperage" in eid or "current" in eid):
            result["ev_current_control_entity"] = eid
    return result


def _discover_heidelberg(entities) -> Dict[str, str]:
    """Discover EV charger config from Heidelberg Energy Control integration."""
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and ("connect" in eid or "plug" in eid):
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and ("charg" in eid or "active" in eid):
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result["ev_session_energy_sensor"] = eid
        if eid.startswith("number.") and "current" in eid:
            result["ev_current_control_entity"] = eid
    return result


def _discover_goecharger_mqtt(entities) -> Dict[str, str]:
    """Discover EV charger config from go-eCharger MQTT integration.

    HACS: syssi/homeassistant-goecharger-mqtt
    Uses number entities for current control (amp, ama).
    Start/stop via select entity (frc: 0=neutral, 1=off, 2=on).
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and dc == "plug":
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "car" in eid:
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        # Requested current (amp) — primary control
        if eid.startswith("number.") and ("requested_current" in eid or eid.endswith("_amp")):
            result["ev_current_control_entity"] = eid
        # Force state select (frc) — start/stop control
        if eid.startswith("select.") and ("frc" in eid or "force_state" in eid):
            result["ev_charge_mode_entity"] = eid
            result["ev_charge_mode_start"] = "2"  # force ON
            result["ev_charge_mode_stop"] = "1"   # force OFF
    return result


def _discover_openwb(entities) -> Dict[str, str]:
    """Discover EV charger config from OpenWB 2.x MQTT integration.

    HACS: a529987659852/openwb2mqtt
    Uses select entity for charge mode, number entity for current.
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and ("plug" in eid or "connect" in eid):
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in eid:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power" and "charg" in eid:
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("number.") and "current" in eid:
            result["ev_current_control_entity"] = eid
        # Charge mode select — start/stop control
        if eid.startswith("select.") and "chargemode" in eid:
            result["ev_charge_mode_entity"] = eid
            result["ev_charge_mode_start"] = "Instant Charging"
            result["ev_charge_mode_stop"] = "Stop"
    return result


def _discover_ocpp(entities) -> Dict[str, str]:
    """Discover EV charger config from OCPP integration.

    OCPP chargers use sensor entities for status (not binary_sensor).
    Status values: Available, Preparing, Charging, SuspendedEV, Finishing, etc.
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "status" in eid and "connector" in eid:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and ("current" in eid or "limit" in eid):
            result["ev_current_control_entity"] = eid
        if eid.startswith("switch.") and "charge" in eid:
            result["ev_start_stop_entity"] = eid
    return result


def _discover_ohme(entities) -> Dict[str, str]:
    """Discover EV charger config from Ohme integration.

    Ohme uses sensor for status (Plugged in, Charging, Unplugged).
    Charge mode via select entity (Max charge, Paused, etc.).
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "status" in eid:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("sensor.") and "current" in eid:
            result.setdefault("ev_current_sensor", eid)
        if eid.startswith("select.") and "charge_mode" in eid:
            result["ev_charge_mode_entity"] = eid
            result["ev_charge_mode_start"] = "Max charge"
            result["ev_charge_mode_stop"] = "Paused"
    return result


def _discover_peblar(entities) -> Dict[str, str]:
    """Discover EV charger config from Peblar integration.

    Peblar uses sensor for state (connected, charging, no EV connected).
    Current control via number entity (charge_limit).
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "state" in eid and dc is None:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result.setdefault("ev_session_energy_sensor", eid)
        if eid.startswith("sensor.") and dc == "energy" and "lifetime" in eid:
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and ("charge" in eid or "limit" in eid):
            result["ev_current_control_entity"] = eid
        if eid.startswith("switch.") and "charge" in eid:
            result["ev_start_stop_entity"] = eid
    return result


def _discover_v2c(entities) -> Dict[str, str]:
    """Discover EV charger config from V2C Trydan integration.

    V2C uses binary_sensor for connected/charging status.
    Current control via number entity (intensity).
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and "connect" in eid:
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in eid:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and ("intensity" in eid or "current" in eid):
            result["ev_current_control_entity"] = eid
        if eid.startswith("switch.") and "pause" in eid:
            result["ev_start_stop_entity"] = eid
    return result


def _discover_alfen(entities) -> Dict[str, str]:
    """Discover EV charger config from Alfen Eve wallbox integration.

    Alfen uses sensor for main state (EV Connected, Charging Power On, Available).
    Current control via number entity (max_current).
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "main_state" in eid:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power" and "active_power" in eid:
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "meter_reading" in eid:
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and "max_current" in eid:
            result["ev_current_control_entity"] = eid
    return result


def _discover_openevse(entities) -> Dict[str, str]:
    """Discover EV charger config from OpenEVSE integration.

    OpenEVSE uses binary_sensor for vehicle detection, sensor for status.
    Current control via number entity (max_current).
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and "vehicle" in eid:
            result["ev_connected_sensor"] = eid
        if eid.startswith("sensor.") and "status" in eid:
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in eid:
            result.setdefault("ev_session_energy_sensor", eid)
        if eid.startswith("sensor.") and dc == "energy" and "total" in eid:
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and "current" in eid:
            result["ev_current_control_entity"] = eid
    return result


def _discover_blue_current(entities) -> Dict[str, str]:
    """Discover EV charger config from Blue Current integration.

    Blue Current uses sensor for vehicle_status and activity.
    No dedicated current control entity — power-only monitoring.
    """
    result: Dict[str, str] = {}
    for entry in entities:
        eid = entry.entity_id
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "vehicle_status" in eid:
            result["ev_connected_sensor"] = eid
        if eid.startswith("sensor.") and "activity" in eid:
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("sensor.") and ("avg_current" in eid or "max_usage" in eid):
            result.setdefault("ev_current_sensor", eid)
    return result


# ============================================================
# Inverter / battery discharge-control discovery
# ============================================================
# Seeded from a sensor we already learned from the HA Energy Dashboard
# (battery_power / solar_power / etc.). We look that entity up in the
# entity registry, read its `platform`, then iterate sibling entities
# from the same integration to find a `number.*` entity that controls
# battery discharge power. Multilingual patterns (English + German)
# cover the common Huawei Solar / Sungrow / SolarEdge naming.

# Compiled at import time so the discovery loop is hot-path friendly.
_DISCHARGE_CONTROL_PATTERNS = [
    # Huawei Solar (English)
    re.compile(r"max.*discharg.*power", re.IGNORECASE),
    re.compile(r"discharg.*max.*power", re.IGNORECASE),
    re.compile(r"battery.*max.*discharg", re.IGNORECASE),
    re.compile(r"battery.*discharg.*limit", re.IGNORECASE),
    # Huawei Solar (German locale, e.g. number.batteries_maximale_entladeleistung)
    re.compile(r"maximale.*entlade", re.IGNORECASE),
    re.compile(r"max.*entlade", re.IGNORECASE),
    re.compile(r"entlade.*maximum", re.IGNORECASE),
    # SolAX (solax-modbus)
    re.compile(r"solax.*discharg.*power", re.IGNORECASE),
    re.compile(r"solax.*battery.*discharg", re.IGNORECASE),
    # Solarman / DEYE / Sunsynk (ha-solarman)
    re.compile(r"(solarman|deye|sunsynk).*discharg", re.IGNORECASE),
    # Growatt (solax-modbus / growatt integration)
    re.compile(r"growatt.*discharg.*power", re.IGNORECASE),
    re.compile(r"growatt.*battery.*discharg", re.IGNORECASE),
    # Sofar
    re.compile(r"sofar.*discharg.*power", re.IGNORECASE),
    # Solis
    re.compile(r"solis.*discharg.*power", re.IGNORECASE),
    # GoodWe
    re.compile(r"goodwe.*discharg.*power", re.IGNORECASE),
    re.compile(r"goodwe.*battery.*discharg", re.IGNORECASE),
    # SolarEdge Modbus Multi (solaredge-modbus-multi HACS)
    re.compile(r"solaredge.*storage.*discharg", re.IGNORECASE),
    re.compile(r"solaredge.*discharg.*limit", re.IGNORECASE),
    # Enphase Envoy (IQ Battery reserve)
    re.compile(r"envoy.*reserve.*battery", re.IGNORECASE),
    re.compile(r"enphase.*reserve.*battery", re.IGNORECASE),
    re.compile(r"enpower.*reserve.*battery", re.IGNORECASE),
    # Tesla Powerwall (backup reserve %)
    re.compile(r"powerwall.*backup.*reserve", re.IGNORECASE),
    # Victron (ESS SOC limit)
    re.compile(r"victron.*ess.*soclimit", re.IGNORECASE),
    re.compile(r"victron.*minimum.*soc", re.IGNORECASE),
    re.compile(r"victron.*discharg", re.IGNORECASE),
    # Kostal Plenticore (battery DC power control)
    re.compile(r"kostal.*battery.*dc.*power", re.IGNORECASE),
    re.compile(r"plenticore.*battery.*dc.*power", re.IGNORECASE),
    re.compile(r"kostal.*discharg", re.IGNORECASE),
    # Sungrow (max discharge power)
    re.compile(r"sungrow.*discharg.*power", re.IGNORECASE),
    re.compile(r"sungrow.*battery.*discharg", re.IGNORECASE),
    re.compile(r"sungrow.*max.*discharg", re.IGNORECASE),
    # Generic fallback (any integration with standard naming)
    re.compile(r"discharg.*power.*limit", re.IGNORECASE),
    re.compile(r"backup.*reserve", re.IGNORECASE),
]


def discover_inverter_from_registry(
    hass: HomeAssistant,
    energy_dashboard_config,
) -> Optional[str]:
    """Auto-discover the battery discharge control number entity.

    Walks the entity registry from a sensor we already know (from the HA
    Energy Dashboard config) to find the integration responsible for the
    battery, then looks for a sibling ``number.*`` entity matching one of
    the discharge-power name patterns.

    Args:
        hass: Home Assistant instance.
        energy_dashboard_config: ``EnergyDashboardConfig`` returned by
            ``ha_energy_reader.read_energy_dashboard_config``.

    Returns:
        The entity_id of the discovered control entity, or ``None`` if no
        match was found. SEM falls back to no discharge protection when
        ``None`` is returned, matching today's behaviour for users without
        a configured entity.
    """
    if energy_dashboard_config is None:
        return None

    # Try battery sensors first (most likely to be on the same integration
    # as the discharge control), fall back to solar/grid.
    seed_candidates = [
        getattr(energy_dashboard_config, "battery_power", None),
        getattr(energy_dashboard_config, "battery_charge_energy", None),
        getattr(energy_dashboard_config, "battery_discharge_energy", None),
        getattr(energy_dashboard_config, "solar_power", None),
        getattr(energy_dashboard_config, "solar_energy", None),
        getattr(energy_dashboard_config, "grid_import_power", None),
    ]
    seed_candidates = [s for s in seed_candidates if s]
    if not seed_candidates:
        return None

    entity_reg = entity_registry.async_get(hass)

    seed_entry = None
    for seed in seed_candidates:
        entry = entity_reg.async_get(seed)
        if entry is not None:
            seed_entry = entry
            break

    if seed_entry is None or not seed_entry.platform:
        return None

    platform = seed_entry.platform
    config_entry_id = seed_entry.config_entry_id
    _LOGGER.info("Detected inverter platform: %s (seed: %s)", platform, seed_entry.entity_id)

    # Collect candidate number entities from the same integration. Prefer
    # the same config_entry_id (for installs with multiple inverters).
    same_integration: List[str] = []
    for entry in entity_reg.entities.values():
        if entry.platform != platform:
            continue
        if entry.disabled_by:
            continue
        if not entry.entity_id.startswith("number."):
            continue
        if config_entry_id and entry.config_entry_id != config_entry_id:
            # Skip number entities from a different inverter, but only when
            # we know the seed's config entry — avoids cross-contamination.
            continue
        same_integration.append(entry.entity_id)

    if not same_integration:
        return None

    # Score each candidate against the patterns; first hit wins. Prefer
    # entity IDs containing "batter" when multiple match the same pattern.
    def _score(eid: str) -> int:
        return 1 if "batter" in eid.lower() else 0

    for pattern in _DISCHARGE_CONTROL_PATTERNS:
        matches = [eid for eid in same_integration if pattern.search(eid)]
        if matches:
            matches.sort(key=lambda e: (-_score(e), e))
            chosen = matches[0]
            _LOGGER.info(
                "Auto-discovered battery discharge control entity: %s "
                "(platform=%s, pattern=%s)",
                chosen,
                platform,
                pattern.pattern,
            )
            return chosen

    return None
