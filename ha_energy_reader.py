"""Read sensor configuration from Home Assistant Energy Dashboard.

This module reads the Energy Dashboard configuration (.storage/energy) to extract
sensor entity IDs for solar, grid, battery, and EV charger. This allows SEM to
use the same sensors the user has already configured in the HA Energy Dashboard.

Requires Home Assistant 2025.12+ for stat_power fields.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class EnergyDashboardConfig:
    """Configuration extracted from HA Energy Dashboard."""

    # Power sensors (for real-time flow calculations)
    solar_power: Optional[str] = None
    grid_import_power: Optional[str] = None
    grid_export_power: Optional[str] = None
    battery_power: Optional[str] = None  # Combined: positive=charge, negative=discharge
    ev_power: Optional[str] = None

    # Energy sensors (for cumulative tracking)
    solar_energy: Optional[str] = None
    grid_import_energy: Optional[str] = None
    grid_export_energy: Optional[str] = None
    battery_charge_energy: Optional[str] = None
    battery_discharge_energy: Optional[str] = None
    ev_energy: Optional[str] = None

    # Multi-device lists (all sources, not just first)
    solar_power_list: List[str] = field(default_factory=list)
    solar_energy_list: List[str] = field(default_factory=list)
    battery_power_list: List[str] = field(default_factory=list)
    battery_charge_energy_list: List[str] = field(default_factory=list)
    battery_discharge_energy_list: List[str] = field(default_factory=list)
    grid_import_energy_list: List[str] = field(default_factory=list)
    grid_export_energy_list: List[str] = field(default_factory=list)
    grid_power_list: List[str] = field(default_factory=list)

    # Additional device consumption entries (for EV detection)
    device_consumption: List[Dict[str, str]] = field(default_factory=list)

    # Validation flags
    has_solar: bool = False
    has_grid: bool = False
    has_battery: bool = False
    has_ev: bool = False

    def is_minimally_configured(self) -> bool:
        """Check if Energy Dashboard has minimum required configuration.

        Requires at least solar and grid to be configured.
        """
        return self.has_solar and self.has_grid

    def get_missing_components(self) -> List[str]:
        """Return list of missing required components."""
        missing = []
        if not self.has_solar:
            missing.append("Solar")
        if not self.has_grid:
            missing.append("Grid")
        return missing

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for use in coordinator."""
        return {
            # Power sensors
            "solar_power_sensor": self.solar_power,
            "grid_import_power_sensor": self.grid_import_power,
            "grid_export_power_sensor": self.grid_export_power,
            "battery_power_sensor": self.battery_power,
            "ev_power_sensor": self.ev_power,
            # Energy sensors
            "solar_energy_sensor": self.solar_energy,
            "grid_import_energy_sensor": self.grid_import_energy,
            "grid_export_energy_sensor": self.grid_export_energy,
            "battery_charge_energy_sensor": self.battery_charge_energy,
            "battery_discharge_energy_sensor": self.battery_discharge_energy,
            "ev_energy_sensor": self.ev_energy,
            # Flags
            "has_solar": self.has_solar,
            "has_grid": self.has_grid,
            "has_battery": self.has_battery,
            "has_ev": self.has_ev,
        }


async def read_energy_dashboard_config(hass: HomeAssistant) -> Optional[EnergyDashboardConfig]:
    """Read sensor configuration from HA Energy Dashboard.

    Args:
        hass: Home Assistant instance

    Returns:
        EnergyDashboardConfig with extracted sensor entity IDs, or None if not configured
    """
    _LOGGER.info("Reading Energy Dashboard config from .storage/energy...")
    try:
        energy_file = os.path.join(hass.config.config_dir, ".storage", "energy")
        _LOGGER.info("Energy Dashboard file path: %s", energy_file)

        if not os.path.exists(energy_file):
            _LOGGER.info("Energy Dashboard not configured (file not found)")
            return None

        # Read the energy configuration file
        def read_file():
            with open(energy_file, "r", encoding="utf-8") as f:
                return json.load(f)

        energy_config = await hass.async_add_executor_job(read_file)

        if "data" not in energy_config:
            _LOGGER.warning("Energy Dashboard has no data section")
            return None

        data = energy_config["data"]
        config = EnergyDashboardConfig()

        # Extract energy sources
        energy_sources = data.get("energy_sources", [])
        for source in energy_sources:
            source_type = source.get("type")

            if source_type == "solar":
                _extract_solar_config(source, config)

            elif source_type == "grid":
                _extract_grid_config(source, config)

            elif source_type == "battery":
                _extract_battery_config(source, config)

        # Extract device consumption (for EV charger)
        device_consumption = data.get("device_consumption", [])
        config.device_consumption = device_consumption
        _extract_ev_from_devices(device_consumption, config)

        _LOGGER.info(
            "Read Energy Dashboard config: solar=%s (%d sources), grid=%s (%d import, %d export), battery=%s (%d units), ev=%s",
            config.has_solar, len(config.solar_power_list),
            config.has_grid, len(config.grid_import_energy_list), len(config.grid_export_energy_list),
            config.has_battery, len(config.battery_power_list),
            config.has_ev,
        )

        return config

    except json.JSONDecodeError as e:
        _LOGGER.error("Failed to parse Energy Dashboard config: %s", e)
        return None
    except Exception as e:
        _LOGGER.error("Failed to read Energy Dashboard config: %s", e, exc_info=True)
        return None


def _extract_solar_config(source: Dict[str, Any], config: EnergyDashboardConfig) -> None:
    """Extract solar configuration from energy source.

    Called once per solar source in the Energy Dashboard. Appends to lists
    and sets the primary (single) field from the first source only.
    """
    energy = source.get("stat_energy_from")
    power = source.get("stat_rate") or source.get("stat_power")

    if energy:
        config.solar_energy_list.append(energy)
        if not config.solar_energy:
            config.solar_energy = energy
    if power:
        config.solar_power_list.append(power)
        if not config.solar_power:
            config.solar_power = power

    config.has_solar = bool(config.solar_energy_list or config.solar_power_list)

    if energy or power:
        _LOGGER.debug(
            "Found solar source #%d: energy=%s, power=%s",
            len(config.solar_power_list),
            energy,
            power,
        )


def _extract_grid_config(source: Dict[str, Any], config: EnergyDashboardConfig) -> None:
    """Extract grid configuration from energy source.

    Grid uses separate flow_from (import) and flow_to (export) arrays for energy.
    Power is configured in a separate "power" array with "stat_rate" field.
    Arrays may contain multiple entries (e.g. dual-tariff metering in NL/BE).

    HA 2025.12 grid power convention:
    - Single combined sensor: positive=import, negative=export
    - Huawei Solar is OPPOSITE: positive=export, negative=import
    - User may have created a template sensor to invert the sign
    """
    # Grid import energy — collect ALL flow_from entries
    flow_from = source.get("flow_from", [])
    if flow_from:
        for entry in flow_from:
            eid = entry.get("stat_energy_from")
            if eid:
                config.grid_import_energy_list.append(eid)
                if not config.grid_import_energy:
                    config.grid_import_energy = eid
    elif source.get("stat_energy_from"):
        eid = source.get("stat_energy_from")
        config.grid_import_energy_list.append(eid)
        if not config.grid_import_energy:
            config.grid_import_energy = eid

    # Grid export energy — collect ALL flow_to entries
    flow_to = source.get("flow_to", [])
    if flow_to:
        for entry in flow_to:
            eid = entry.get("stat_energy_to")
            if eid:
                config.grid_export_energy_list.append(eid)
                if not config.grid_export_energy:
                    config.grid_export_energy = eid
    elif source.get("stat_energy_to"):
        eid = source.get("stat_energy_to")
        config.grid_export_energy_list.append(eid)
        if not config.grid_export_energy:
            config.grid_export_energy = eid

    # Grid power — collect ALL power entries
    power_config = source.get("power", [])
    if power_config:
        for entry in power_config:
            eid = entry.get("stat_rate")
            if eid:
                config.grid_power_list.append(eid)
                if not config.grid_import_power:
                    config.grid_import_power = eid
    elif source.get("stat_rate"):
        eid = source.get("stat_rate")
        config.grid_power_list.append(eid)
        if not config.grid_import_power:
            config.grid_import_power = eid

    config.has_grid = bool(
        config.grid_import_energy_list
        or config.grid_power_list
        or config.grid_export_energy_list
    )

    if config.has_grid:
        _LOGGER.debug(
            "Found grid: %d import energy, %d export energy, %d power sensors",
            len(config.grid_import_energy_list),
            len(config.grid_export_energy_list),
            len(config.grid_power_list),
        )


def _extract_battery_config(source: Dict[str, Any], config: EnergyDashboardConfig) -> None:
    """Extract battery configuration from energy source.

    Called once per battery source in the Energy Dashboard. Appends to lists
    and sets the primary (single) field from the first source only.

    Battery uses:
    - stat_energy_from: discharge energy
    - stat_energy_to: charge energy
    - stat_rate/stat_power: combined power (positive=charge, negative=discharge in HA 2025.12)
    """
    discharge_energy = source.get("stat_energy_from")
    charge_energy = source.get("stat_energy_to")
    power = source.get("stat_rate") or source.get("stat_power")

    if discharge_energy:
        config.battery_discharge_energy_list.append(discharge_energy)
        if not config.battery_discharge_energy:
            config.battery_discharge_energy = discharge_energy
    if charge_energy:
        config.battery_charge_energy_list.append(charge_energy)
        if not config.battery_charge_energy:
            config.battery_charge_energy = charge_energy
    if power:
        config.battery_power_list.append(power)
        if not config.battery_power:
            config.battery_power = power

    config.has_battery = bool(
        config.battery_discharge_energy_list
        or config.battery_charge_energy_list
        or config.battery_power_list
    )

    if discharge_energy or charge_energy or power:
        _LOGGER.debug(
            "Found battery source #%d: charge_energy=%s, discharge_energy=%s, power=%s",
            len(config.battery_power_list),
            charge_energy,
            discharge_energy,
            power,
        )


def _extract_ev_from_devices(
    device_consumption: List[Dict[str, Any]], config: EnergyDashboardConfig
) -> None:
    """Extract EV charger from device consumption list.

    Looks for devices that appear to be EV chargers based on naming patterns.
    Takes the first match.

    HA 2025.12 uses "stat_rate" for power sensors in device consumption.
    """
    ev_patterns = ["ev", "charger", "keba", "wallbox", "easee", "zappi", "tesla_wall"]

    for device in device_consumption:
        stat_consumption = device.get("stat_consumption", "")
        # HA 2025.12 uses "stat_rate" for power, not "stat_power"
        stat_power = device.get("stat_rate") or device.get("stat_power")

        # Check if this looks like an EV charger
        entity_lower = stat_consumption.lower()
        is_ev = any(pattern in entity_lower for pattern in ev_patterns)

        if is_ev:
            config.ev_energy = stat_consumption
            config.ev_power = stat_power
            config.has_ev = True
            _LOGGER.debug(
                "Found EV charger in devices: energy=%s, power=%s",
                config.ev_energy,
                config.ev_power,
            )
            break


def get_all_individual_devices(config: EnergyDashboardConfig, hass=None) -> List[Dict[str, Any]]:
    """Return all individual devices from Energy Dashboard for load management.

    These are devices listed in the Energy Dashboard's "Individual devices" section
    (device_consumption). Each device can be used for peak management if a
    corresponding switch entity is found for control.

    Args:
        config: EnergyDashboardConfig from read_energy_dashboard_config()

    Returns:
        List of device dicts with energy_sensor, power_sensor, name, is_ev
    """
    devices = []
    ev_patterns = ["ev", "charger", "keba", "wallbox", "easee", "zappi", "tesla_wall"]

    for device in config.device_consumption:
        energy_sensor = device.get("stat_consumption", "")
        power_sensor = device.get("stat_rate") or device.get("stat_power")
        name = device.get("name", "")

        # Determine if this looks like an EV charger
        entity_lower = energy_sensor.lower()
        is_ev = any(pattern in entity_lower for pattern in ev_patterns)

        # Derive a name: prefer the entity's friendly_name (user-set description)
        if not name and hass:
            state = hass.states.get(energy_sensor)
            if state and state.attributes.get("friendly_name"):
                name = state.attributes["friendly_name"]

        # Fallback: extract from entity ID
        if not name:
            if "." in energy_sensor:
                name_part = energy_sensor.split(".", 1)[1]
                for suffix in ["_energy", "_total_energy", "_power", "_consumption"]:
                    if name_part.endswith(suffix):
                        name_part = name_part[:-len(suffix)]
                        break
                name = name_part.replace("_", " ").title()

        devices.append({
            "energy_sensor": energy_sensor,
            "power_sensor": power_sensor,
            "name": name,
            "is_ev": is_ev,
        })

    _LOGGER.debug("Found %d individual devices in Energy Dashboard", len(devices))
    return devices


async def validate_energy_dashboard_sensors(
    hass: HomeAssistant, config: EnergyDashboardConfig
) -> Dict[str, bool]:
    """Validate that the sensors from Energy Dashboard actually exist in HA.

    Args:
        hass: Home Assistant instance
        config: EnergyDashboardConfig to validate

    Returns:
        Dictionary mapping sensor names to their validity (True if exists)
    """
    sensors_to_check = {
        "solar_power": config.solar_power,
        "solar_energy": config.solar_energy,
        "grid_import_power": config.grid_import_power,
        "grid_import_energy": config.grid_import_energy,
        "grid_export_power": config.grid_export_power,
        "grid_export_energy": config.grid_export_energy,
        "battery_power": config.battery_power,
        "battery_charge_energy": config.battery_charge_energy,
        "battery_discharge_energy": config.battery_discharge_energy,
        "ev_power": config.ev_power,
        "ev_energy": config.ev_energy,
    }

    results = {}
    for name, entity_id in sensors_to_check.items():
        if entity_id:
            state = hass.states.get(entity_id)
            results[name] = state is not None
            if not results[name]:
                _LOGGER.warning("Sensor from Energy Dashboard not found: %s", entity_id)
        else:
            results[name] = False  # Not configured

    return results
