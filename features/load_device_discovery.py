"""Load management device discovery for SEM Solar Energy Management."""
import logging
from typing import Dict, List, Optional, Tuple, Any
import fnmatch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry

from ..const import LOAD_MANAGEMENT_DEVICE_PATTERNS
from ..ha_energy_reader import read_energy_dashboard_config, get_all_individual_devices

_LOGGER = logging.getLogger(__name__)


class LoadDeviceDiscovery:
    """Auto-discover controllable devices for load management."""

    def __init__(self, hass: HomeAssistant):
        """Initialize device discovery."""
        self.hass = hass
        self._entity_registry = entity_registry.async_get(hass)

    def get_all_entities(self) -> List[str]:
        """Get all available entity IDs."""
        return list(self.hass.states.async_entity_ids())

    def discover_controllable_devices(self) -> Dict[str, Dict]:
        """Discover devices that have both power monitoring and switch control.

        Returns:
            Dict with device_id as key, device info as value
        """
        discovered_devices = {}
        all_entities = self.get_all_entities()
        _LOGGER.info(f"Starting discovery with {len(all_entities)} total entities")

        for device_type, patterns in LOAD_MANAGEMENT_DEVICE_PATTERNS.items():
            switch_pattern = patterns["switch_pattern"]
            power_pattern = patterns["power_pattern"]
            description = patterns["description"]

            # Find all switches matching the pattern
            switches = self._find_pattern_matches(switch_pattern, all_entities)
            _LOGGER.info(f"Device type '{device_type}': found {len(switches)} switches matching pattern '{switch_pattern}'")

            for switch_entity in switches:
                # Try to find corresponding power sensor
                power_entity = self._find_corresponding_power_sensor(
                    switch_entity, power_pattern, all_entities
                )

                if power_entity:
                    _LOGGER.debug(f"Found power sensor for {switch_entity}: {power_entity}")
                    if self._validate_device_pair(switch_entity, power_entity):
                        device_id = self._generate_device_id(switch_entity)

                        discovered_devices[device_id] = {
                            "switch_entity": switch_entity,
                            "power_entity": power_entity,
                            "device_type": device_type,
                            "description": description,
                            "friendly_name": self._get_friendly_name(switch_entity),
                            "power_rating": self._get_device_power_rating(power_entity),
                            "is_available": self._is_device_available(switch_entity, power_entity),
                            "priority": 5,  # Default medium priority
                            "is_critical": False,  # Default not critical
                            "is_controllable": True,  # Default controllable
                        }

                        _LOGGER.info(
                            f"Discovered controllable device: {device_id} "
                            f"({switch_entity} + {power_entity})"
                        )
                    else:
                        _LOGGER.debug(f"Device pair validation failed for {switch_entity} + {power_entity}")
                else:
                    _LOGGER.debug(f"No matching power sensor found for {switch_entity}")

        _LOGGER.info(f"Discovery complete: found {len(discovered_devices)} controllable devices")
        return discovered_devices

    async def discover_from_energy_dashboard(self) -> Dict[str, Dict]:
        """Discover devices from HA Energy Dashboard individual devices.

        This method reads the 'Individual devices' section from the Energy Dashboard
        and creates load management device entries for each. It uses the new
        discover_control_for_energy_device() method to find control entities.

        Returns:
            Dict with device_id as key, device info as value including:
            - power_entity: Power sensor for monitoring
            - energy_entity: Energy sensor from Energy Dashboard
            - control: Dict with control type, entity/service, and discovery method
            - is_controllable: True if control method was found
        """
        _LOGGER.info("Discovering devices from Energy Dashboard individual devices...")

        energy_config = await read_energy_dashboard_config(self.hass)
        if not energy_config:
            _LOGGER.warning("Energy Dashboard not configured, no devices to discover")
            return {}

        individual_devices = get_all_individual_devices(energy_config, self.hass)
        if not individual_devices:
            _LOGGER.info("No individual devices configured in Energy Dashboard")
            return {}

        discovered_devices = {}

        for device in individual_devices:
            energy_sensor = device.get("energy_sensor", "")
            power_sensor = device.get("power_sensor")
            name = device.get("name", "")
            is_ev = device.get("is_ev", False)

            # Generate device ID from energy sensor
            device_id = self._generate_device_id_from_energy_sensor(energy_sensor)

            # Auto-discover control method using new unified discovery
            control = self.discover_control_for_energy_device(energy_sensor, power_sensor)

            # For backwards compatibility, also set switch_entity if control is a switch
            switch_entity = None
            if control and control.get("type") == "switch":
                switch_entity = control.get("entity")

            # Validate power sensor if provided
            if power_sensor:
                power_state = self.hass.states.get(power_sensor)
                if not power_state or power_state.state in ("unknown", "unavailable"):
                    _LOGGER.debug(f"Power sensor {power_sensor} not available for {name}")
                    power_sensor = None

            discovered_devices[device_id] = {
                "power_entity": power_sensor,
                "energy_entity": energy_sensor,
                "switch_entity": switch_entity,  # Backwards compatible
                "control": control,  # New control config
                "friendly_name": name,
                "device_type": "ev_charger" if is_ev else "individual_device",
                "description": f"Energy Dashboard: {name}",
                "source": "energy_dashboard",
                "power_rating": self._get_device_power_rating(power_sensor) if power_sensor else 0.0,
                "is_available": True,
                "priority": 8 if is_ev else 5,  # EV chargers higher priority (shed first)
                "is_critical": False,
                "is_controllable": control is not None,
                "is_ev": is_ev,
            }

            if control:
                control_desc = f"{control['type']} -> {control.get('entity', control.get('service'))}"
                _LOGGER.info(
                    f"Discovered Energy Dashboard device: {device_id} "
                    f"(power={power_sensor}, control={control_desc}, via={control.get('discovered_via')})"
                )
            else:
                _LOGGER.info(
                    f"Discovered Energy Dashboard device (monitoring only): {device_id} "
                    f"(power={power_sensor}, no control found)"
                )

        _LOGGER.info(f"Energy Dashboard discovery complete: found {len(discovered_devices)} devices")
        return discovered_devices

    def _generate_device_id_from_energy_sensor(self, energy_sensor: str) -> str:
        """Generate a device ID from an energy sensor entity ID."""
        if "." in energy_sensor:
            name = energy_sensor.split(".", 1)[1]
        else:
            name = energy_sensor

        # Remove common suffixes
        for suffix in ["_energy", "_total_energy", "_consumption", "_power"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break

        return f"energy_dashboard_{name}"

    def discover_control_for_energy_device(
        self, energy_sensor: str, power_sensor: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Auto-discover control entity for an Energy Dashboard device.

        Uses multiple discovery strategies in order of reliability:
        1. Device Registry - find control entities belonging to same device
        2. Name matching - match by base name patterns
        3. Integration patterns - KEBA, Shelly, etc. specific services

        Args:
            energy_sensor: The energy sensor entity ID from Energy Dashboard
            power_sensor: Optional power sensor entity ID

        Returns:
            Control config dict with type, entity/service, and discovery method,
            or None if no control found.
        """
        control = None

        # Strategy 1: Device Registry (most reliable)
        energy_entry = self._entity_registry.async_get(energy_sensor)
        if energy_entry and energy_entry.device_id:
            control = self._find_control_in_device(energy_entry.device_id)
            if control:
                control["discovered_via"] = "device_registry"
                _LOGGER.info(
                    f"Found control for {energy_sensor} via device registry: "
                    f"{control['type']} -> {control.get('entity', control.get('service'))}"
                )
                return control

        # Strategy 2: Name-based matching (fallback)
        base_name = self._extract_base_name(energy_sensor)
        control = self._find_control_by_name(base_name)
        if control:
            control["discovered_via"] = "name_matching"
            _LOGGER.info(
                f"Found control for {energy_sensor} via name matching: "
                f"{control['type']} -> {control.get('entity')}"
            )
            return control

        # Strategy 3: Integration-specific patterns (KEBA, etc.)
        control = self._find_control_by_integration(energy_sensor, power_sensor)
        if control:
            control["discovered_via"] = "integration_pattern"
            _LOGGER.info(
                f"Found control for {energy_sensor} via integration pattern: "
                f"{control['type']} -> {control.get('entity', control.get('service'))}"
            )
            return control

        _LOGGER.debug(f"No control method found for {energy_sensor}")
        return None

    def _find_control_in_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Find control entities belonging to same device.

        Priority order:
        1. switch.* entities (on/off control)
        2. number.* entities with 'current' in name (amperage control)
        3. input_boolean.* entities (automation triggers)

        Args:
            device_id: The device ID from entity registry

        Returns:
            Control config dict or None
        """
        device_entities = entity_registry.async_entries_for_device(
            self._entity_registry, device_id
        )

        # Priority 1: Switch entities
        for entry in device_entities:
            if entry.entity_id.startswith("switch.") and not entry.disabled_by:
                state = self.hass.states.get(entry.entity_id)
                # Trust entity registry even if state not yet loaded at startup
                if not state or state.state not in ("unavailable",):
                    return {
                        "type": "switch",
                        "entity": entry.entity_id,
                    }

        # Priority 2: Number entities for current control (EV chargers)
        for entry in device_entities:
            entity_lower = entry.entity_id.lower()
            if entry.entity_id.startswith("number.") and not entry.disabled_by and (
                "current" in entity_lower or "ampere" in entity_lower or "amp" in entity_lower
            ):
                state = self.hass.states.get(entry.entity_id)
                # Get original value if state is available
                original_value = None
                min_value = 0
                max_value = 32
                if state and state.state not in ("unavailable", "unknown"):
                    try:
                        original_value = float(state.state)
                    except (ValueError, TypeError):
                        pass
                    min_value = state.attributes.get("min", 0)
                    max_value = state.attributes.get("max", 32)

                return {
                    "type": "current",
                    "entity": entry.entity_id,
                    "original_value": original_value,
                    "min_value": min_value,
                    "max_value": max_value,
                }

        # Priority 3: Input boolean (for automation-based control)
        for entry in device_entities:
            if entry.entity_id.startswith("input_boolean.") and not entry.disabled_by:
                state = self.hass.states.get(entry.entity_id)
                if not state or state.state not in ("unavailable",):
                    return {
                        "type": "input_boolean",
                        "entity": entry.entity_id,
                    }

        return None

    def _find_control_by_name(self, base_name: str) -> Optional[Dict[str, Any]]:
        """Find control entity by matching base name patterns.

        Args:
            base_name: Base name extracted from energy sensor

        Returns:
            Control config dict or None
        """
        all_entities = self.get_all_entities()

        # Try switch patterns
        switch_patterns = [
            f"switch.{base_name}",
            f"switch.{base_name}_switch",
            f"switch.{base_name}_power",
            f"switch.{base_name}_outlet",
        ]

        for switch in switch_patterns:
            if switch in all_entities:
                state = self.hass.states.get(switch)
                if state and state.state not in ("unknown", "unavailable"):
                    return {
                        "type": "switch",
                        "entity": switch,
                    }

        # Try partial match for switches containing the base name
        for entity in all_entities:
            if entity.startswith("switch.") and base_name in entity:
                state = self.hass.states.get(entity)
                if state and state.state not in ("unknown", "unavailable"):
                    return {
                        "type": "switch",
                        "entity": entity,
                    }

        # Try number entities for current control
        current_patterns = [
            f"number.{base_name}_current",
            f"number.{base_name}_charging_current",
            f"number.{base_name}_max_current",
        ]

        for number in current_patterns:
            if number in all_entities:
                state = self.hass.states.get(number)
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        original_value = float(state.state)
                    except (ValueError, TypeError):
                        original_value = None

                    return {
                        "type": "current",
                        "entity": number,
                        "original_value": original_value,
                        "min_value": state.attributes.get("min", 0),
                        "max_value": state.attributes.get("max", 32),
                    }

        return None

    def _find_control_by_integration(
        self, energy_sensor: str, power_sensor: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Find control method based on integration-specific patterns.

        Supports:
        - KEBA: keba.set_current service
        - go-eCharger: number.*_amp_limit or service
        - Easee: easee.set_charger_max_limit
        - Shelly: switch.* entities
        - ESPHome: switch.* entities

        Args:
            energy_sensor: Energy sensor entity ID
            power_sensor: Power sensor entity ID (optional)

        Returns:
            Control config dict or None
        """
        sensor_lower = energy_sensor.lower()
        power_lower = power_sensor.lower() if power_sensor else ""

        # KEBA P30 / KeContact
        if "keba" in sensor_lower or "keba" in power_lower:
            # KEBA uses keba.set_current service
            # KEBA minimum current is 6A, to stop use keba.stop
            # Need to find the KEBA entity for service target
            base_name = self._extract_base_name(energy_sensor)
            all_entities = self.get_all_entities()

            # Look for KEBA sensor to use as target
            for entity in all_entities:
                if entity.startswith("sensor.") and "keba" in entity.lower():
                    return {
                        "type": "service",
                        "service": "keba.set_current",
                        "param": "current",
                        "target_entity": entity,
                        "shed_value": 6,  # KEBA minimum is 6A (use keba.stop for 0)
                        "restore_value": 16,  # Default 16A
                    }

            # Fallback: try number entity for current
            for entity in all_entities:
                if entity.startswith("number.") and "keba" in entity.lower() and "current" in entity.lower():
                    state = self.hass.states.get(entity)
                    if state and state.state not in ("unavailable", "unknown"):
                        try:
                            original_value = float(state.state)
                        except (ValueError, TypeError):
                            original_value = 16

                        return {
                            "type": "current",
                            "entity": entity,
                            "original_value": original_value,
                            "min_value": 0,
                            "max_value": state.attributes.get("max", 32),
                        }

        # go-eCharger
        if "go_e" in sensor_lower or "goe" in sensor_lower or "go-e" in sensor_lower:
            all_entities = self.get_all_entities()
            for entity in all_entities:
                if entity.startswith("number.") and ("go_e" in entity.lower() or "goe" in entity.lower()):
                    if "amp" in entity.lower() or "current" in entity.lower():
                        state = self.hass.states.get(entity)
                        if state and state.state not in ("unavailable", "unknown"):
                            try:
                                original_value = float(state.state)
                            except (ValueError, TypeError):
                                original_value = 16

                            return {
                                "type": "current",
                                "entity": entity,
                                "original_value": original_value,
                                "min_value": 0,
                                "max_value": state.attributes.get("max", 32),
                            }

        # Easee charger
        if "easee" in sensor_lower or "easee" in power_lower:
            return {
                "type": "service",
                "service": "easee.set_charger_max_limit",
                "param": "current",
                "shed_value": 0,
                "restore_value": 16,
            }

        # Shelly devices - look for switch
        if "shelly" in sensor_lower or "shelly" in power_lower:
            base_name = self._extract_base_name(energy_sensor)
            all_entities = self.get_all_entities()

            # Shelly typically has switch entities
            for entity in all_entities:
                if entity.startswith("switch.") and "shelly" in entity.lower():
                    # Try to match by checking if base name relates to this switch
                    if base_name in entity.lower() or self._names_match(
                        base_name, self._extract_base_name(entity)
                    ):
                        state = self.hass.states.get(entity)
                        if state and state.state not in ("unavailable", "unknown"):
                            return {
                                "type": "switch",
                                "entity": entity,
                            }

        # ESPHome devices
        if "esphome" in sensor_lower:
            base_name = self._extract_base_name(energy_sensor)
            all_entities = self.get_all_entities()

            for entity in all_entities:
                if entity.startswith("switch."):
                    if base_name in entity.lower():
                        state = self.hass.states.get(entity)
                        if state and state.state not in ("unavailable", "unknown"):
                            return {
                                "type": "switch",
                                "entity": entity,
                            }

        return None

    def _find_pattern_matches(self, pattern: str, entities: List[str]) -> List[str]:
        """Find entities matching a pattern."""
        if "*" in pattern:
            return fnmatch.filter(entities, pattern)
        else:
            return [pattern] if pattern in entities else []

    def _find_corresponding_power_sensor(
        self, switch_entity: str, power_pattern: str, all_entities: List[str]
    ) -> Optional[str]:
        """Find the power sensor corresponding to a switch entity."""
        # Extract the base name from switch entity
        base_name = self._extract_base_name(switch_entity)

        # Look for power sensors that match the base name
        potential_power_sensors = self._find_pattern_matches(power_pattern, all_entities)

        for power_entity in potential_power_sensors:
            power_base_name = self._extract_base_name(power_entity)

            # Check if they belong to the same device
            if self._names_match(base_name, power_base_name):
                return power_entity

        return None

    def _extract_base_name(self, entity_id: str) -> str:
        """Extract base name from entity ID for matching."""
        # Remove domain (sensor., switch., etc.)
        if "." in entity_id:
            name = entity_id.split(".", 1)[1]
        else:
            name = entity_id

        # Remove common suffixes
        suffixes_to_remove = [
            "_switch", "_power", "_energy", "_current",
            "_voltage", "_temperature", "_status"
        ]

        for suffix in suffixes_to_remove:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break

        return name

    def _names_match(self, name1: str, name2: str) -> bool:
        """Check if two base names match (same device)."""
        # Exact match
        if name1 == name2:
            return True

        # Check if one is a substring of the other
        if name1 in name2 or name2 in name1:
            return True

        # Check similarity for common patterns
        # Remove numbers and underscores for fuzzy matching
        clean_name1 = "".join(c for c in name1 if c.isalpha()).lower()
        clean_name2 = "".join(c for c in name2 if c.isalpha()).lower()

        return clean_name1 == clean_name2

    def _validate_device_pair(self, switch_entity: str, power_entity: str) -> bool:
        """Validate that switch and power sensor are both functional."""
        # Check switch
        switch_state = self.hass.states.get(switch_entity)
        if not switch_state or switch_state.state in ("unknown", "unavailable"):
            return False

        if switch_state.state.lower() not in ("on", "off", "true", "false", "1", "0"):
            return False

        # Check power sensor
        power_state = self.hass.states.get(power_entity)
        if not power_state or power_state.state in ("unknown", "unavailable"):
            return False

        try:
            power_value = float(power_state.state)
            # Power should be reasonable (0-10kW for most household devices)
            return 0 <= power_value <= 10000
        except (ValueError, TypeError):
            return False

    def _generate_device_id(self, switch_entity: str) -> str:
        """Generate a unique device ID."""
        base_name = self._extract_base_name(switch_entity)
        return f"load_device_{base_name}"

    def _get_friendly_name(self, entity_id: str) -> str:
        """Get friendly name for device."""
        state = self.hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]

        # Generate from entity ID
        base_name = self._extract_base_name(entity_id)
        return base_name.replace("_", " ").title()

    def _get_device_power_rating(self, power_entity: Optional[str]) -> float:
        """Get current power consumption of device."""
        if not power_entity:
            return 0.0
        state = self.hass.states.get(power_entity)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return 0.0

    def _is_device_available(self, switch_entity: Optional[str], power_entity: Optional[str]) -> bool:
        """Check if device is currently available.

        For devices with switch_entity = None (e.g., service-based EV charger),
        availability is based on power_entity only.
        For devices with power_entity = None, availability is based on switch_entity only.
        """
        # Handle None power_entity
        if power_entity:
            power_state = self.hass.states.get(power_entity)
            power_available = power_state and power_state.state not in ("unknown", "unavailable")
        else:
            power_available = True  # No power sensor, assume available

        # If no switch entity (service-based control), only check power entity
        if switch_entity is None:
            return power_available

        switch_state = self.hass.states.get(switch_entity)
        switch_available = switch_state and switch_state.state not in ("unknown", "unavailable")

        # If no power entity, only check switch
        if power_entity is None:
            return switch_available

        return switch_available and power_available

    def get_device_current_state(self, device_info: Dict) -> Dict:
        """Get current state of a device.

        For devices with switch_entity = None (e.g., service-based EV charger),
        the 'is_on' state is determined by whether power consumption > 0.
        """
        switch_entity = device_info.get("switch_entity")  # May be None for service-based devices
        power_entity = device_info.get("power_entity")

        power_state = self.hass.states.get(power_entity) if power_entity else None

        is_on = False
        current_power = 0.0

        # Get current power first (needed for is_on fallback)
        if power_state and power_state.state not in ("unknown", "unavailable"):
            try:
                current_power = float(power_state.state)
            except (ValueError, TypeError):
                pass

        # Determine is_on state
        if switch_entity:
            # Normal device with switch entity
            switch_state = self.hass.states.get(switch_entity)
            if switch_state and switch_state.state:
                state_lower = switch_state.state.lower() if isinstance(switch_state.state, str) else str(switch_state.state).lower()
                if state_lower in ("on", "true", "1"):
                    is_on = True
        else:
            # Service-based device (no switch entity) - infer is_on from power
            # If power > 0, device is on
            is_on = current_power > 0

        # Get the most recent last_updated timestamp
        last_updated = None
        timestamps = []
        if switch_entity:
            switch_state = self.hass.states.get(switch_entity)
            if switch_state and switch_state.last_updated:
                timestamps.append(switch_state.last_updated)
        if power_state and power_state.last_updated:
            timestamps.append(power_state.last_updated)
        if timestamps:
            last_updated = max(timestamps)

        return {
            "is_on": is_on,
            "current_power": current_power,
            "is_available": self._is_device_available(switch_entity, power_entity),
            "last_updated": last_updated
        }

    async def turn_off_device(self, device_info: Dict) -> bool:
        """Turn off a device."""
        switch_entity = device_info.get("switch_entity")
        if not switch_entity:
            _LOGGER.warning("Cannot turn off device: no switch_entity configured")
            return False

        domain = switch_entity.split(".")[0]

        try:
            await self.hass.services.async_call(
                domain, "turn_off", {"entity_id": switch_entity}
            )
            _LOGGER.info(f"Turned off device: {switch_entity}")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to turn off {switch_entity}: {e}")
            return False

    async def turn_on_device(self, device_info: Dict) -> bool:
        """Turn on a device."""
        switch_entity = device_info.get("switch_entity")
        if not switch_entity:
            _LOGGER.warning("Cannot turn on device: no switch_entity configured")
            return False

        domain = switch_entity.split(".")[0]

        try:
            await self.hass.services.async_call(
                domain, "turn_on", {"entity_id": switch_entity}
            )
            _LOGGER.info(f"Turned on device: {switch_entity}")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to turn on {switch_entity}: {e}")
            return False