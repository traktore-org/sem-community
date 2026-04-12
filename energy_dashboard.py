"""Energy Dashboard automatic configuration for SEM."""
import json
import logging
import os
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def configure_energy_dashboard(
    hass: HomeAssistant,
    config: Dict[str, Any],
) -> bool:
    """Automatically configure Home Assistant Energy Dashboard with SEM sensors.

    Args:
        hass: Home Assistant instance
        config: SEM configuration containing sensor mappings

    Returns:
        True if configuration was successful, False otherwise
    """
    try:
        energy_file = os.path.join(hass.config.config_dir, ".storage", "energy")

        # Load existing energy configuration or create new one
        if os.path.exists(energy_file):
            with open(energy_file, "r", encoding="utf-8") as f:
                energy_config = json.load(f)
            _LOGGER.info("Loaded existing energy configuration")
        else:
            energy_config = {
                "version": 1,
                "minor_version": 1,
                "key": "energy",
                "data": {
                    "energy_sources": [],
                    "device_consumption": []
                }
            }
            _LOGGER.info("Creating new energy configuration")

        # Ensure data structure exists
        if "data" not in energy_config:
            energy_config["data"] = {}
        if "energy_sources" not in energy_config["data"]:
            energy_config["data"]["energy_sources"] = []
        if "device_consumption" not in energy_config["data"]:
            energy_config["data"]["device_consumption"] = []

        # Get electricity rates — prefer SEM's live tariff sensors (dynamic),
        # fall back to static config values
        import_rate = config.get("electricity_import_rate", 0.36)
        export_rate = config.get("electricity_export_rate", 0.08)

        # SEM tariff sensors provide real-time pricing (dynamic tariffs).
        # HA energy dashboard supports entity_energy_price for this.
        import_price_entity = f"sensor.sem_tariff_current_import_rate"
        export_price_entity = f"sensor.sem_tariff_current_export_rate"

        # Check if tariff sensors exist in HA
        use_dynamic_import = hass.states.get(import_price_entity) is not None
        use_dynamic_export = hass.states.get(export_price_entity) is not None
        if use_dynamic_import:
            _LOGGER.info("Using dynamic import tariff: %s", import_price_entity)
        if use_dynamic_export:
            _LOGGER.info("Using dynamic export tariff: %s", export_price_entity)

        # Configure Grid (if sensors available)
        grid_import_sensor = config.get("grid_import_total_energy_sensor")
        grid_export_sensor = config.get("grid_export_total_energy_sensor")
        grid_power_sensor = config.get("grid_power_sensor")

        if grid_import_sensor or grid_export_sensor:
            _configure_grid_source(
                energy_config["data"]["energy_sources"],
                grid_import_sensor,
                grid_export_sensor,
                import_rate,
                export_rate,
                grid_power_sensor,
                import_price_entity if use_dynamic_import else None,
                export_price_entity if use_dynamic_export else None,
            )

        # Configure Solar (if sensor available)
        solar_sensor = config.get("solar_total_energy_sensor")
        solar_power_sensor = config.get("solar_production_sensor")
        if solar_sensor:
            _configure_solar_source(
                energy_config["data"]["energy_sources"],
                solar_sensor,
                solar_power_sensor,
            )

        # Configure Battery (if sensors available)
        battery_charge_sensor = config.get("battery_charge_total_energy_sensor")
        battery_discharge_sensor = config.get("battery_discharge_total_energy_sensor")
        battery_power_sensor = config.get("battery_power_sensor")

        if battery_charge_sensor and battery_discharge_sensor:
            _configure_battery_source(
                energy_config["data"]["energy_sources"],
                battery_charge_sensor,
                battery_discharge_sensor,
                battery_power_sensor,
            )

        # Configure EV Charger as individual device (if sensor available)
        ev_energy_sensor = config.get("ev_total_energy_sensor")
        if ev_energy_sensor:
            _configure_ev_device(
                energy_config["data"]["device_consumption"],
                ev_energy_sensor
            )

        # Create backup before saving
        if os.path.exists(energy_file):
            backup_file = f"{energy_file}.backup_sem"
            with open(backup_file, "w", encoding="utf-8") as f:
                with open(energy_file, "r", encoding="utf-8") as orig:
                    f.write(orig.read())
            _LOGGER.info("Created backup at: %s", backup_file)

        # Save updated configuration
        with open(energy_file, "w", encoding="utf-8") as f:
            json.dump(energy_config, f, indent=2)

        _LOGGER.info("Successfully configured Energy Dashboard with SEM sensors")
        return True

    except Exception as e:
        _LOGGER.error("Failed to configure Energy Dashboard: %s", e, exc_info=True)
        return False


def _configure_grid_source(
    energy_sources: list,
    grid_import_sensor: Optional[str],
    grid_export_sensor: Optional[str],
    import_rate: float,
    export_rate: float,
    grid_power_sensor: Optional[str] = None,
    import_price_entity: Optional[str] = None,
    export_price_entity: Optional[str] = None,
) -> None:
    """Configure grid energy source.

    When SEM tariff sensors exist, uses entity_energy_price for dynamic
    pricing (rate changes throughout the day). Falls back to static
    number_energy_price from config.
    """
    # Remove existing grid source
    energy_sources[:] = [s for s in energy_sources if s.get("type") != "grid"]

    grid_source = {
        "type": "grid",
        "flow_from": [],
        "flow_to": [],
        "cost_adjustment_day": 0
    }

    # stat_rate is the real-time power sensor — needed for power-sources-graph
    if grid_power_sensor:
        grid_source["stat_rate"] = grid_power_sensor

    if grid_import_sensor:
        flow_from = {
            "stat_energy_from": grid_import_sensor,
            "stat_cost": None,
        }
        if import_price_entity:
            # Dynamic: HA reads price from SEM tariff sensor each interval
            flow_from["entity_energy_price"] = import_price_entity
            flow_from["number_energy_price"] = None
            _LOGGER.info("Configured grid import: %s (dynamic: %s)", grid_import_sensor, import_price_entity)
        else:
            # Static: fixed rate from config
            flow_from["entity_energy_price"] = None
            flow_from["number_energy_price"] = import_rate
            _LOGGER.info("Configured grid import: %s (static: %.2f/kWh)", grid_import_sensor, import_rate)
        grid_source["flow_from"].append(flow_from)

    if grid_export_sensor:
        flow_to = {
            "stat_energy_to": grid_export_sensor,
            "stat_compensation": None,
        }
        if export_price_entity:
            flow_to["entity_energy_price"] = export_price_entity
            flow_to["number_energy_price"] = None
            _LOGGER.info("Configured grid export: %s (dynamic: %s)", grid_export_sensor, export_price_entity)
        else:
            flow_to["entity_energy_price"] = None
            flow_to["number_energy_price"] = export_rate
            _LOGGER.info("Configured grid export: %s (static: %.2f/kWh)", grid_export_sensor, export_rate)
        grid_source["flow_to"].append(flow_to)

    if grid_source["flow_from"] or grid_source["flow_to"]:
        energy_sources.append(grid_source)


def _configure_solar_source(
    energy_sources: list,
    solar_sensor: str,
    solar_power_sensor: Optional[str] = None,
) -> None:
    """Configure solar energy source."""
    # Remove existing solar source
    energy_sources[:] = [s for s in energy_sources if s.get("type") != "solar"]

    # Add new solar source
    solar_source = {
        "type": "solar",
        "stat_energy_from": solar_sensor,
        "config_entry_solar_forecast": None
    }

    # stat_rate is the real-time power sensor — needed for power-sources-graph
    if solar_power_sensor:
        solar_source["stat_rate"] = solar_power_sensor

    energy_sources.append(solar_source)
    _LOGGER.info("Configured solar production: %s (power: %s)", solar_sensor, solar_power_sensor)


def _configure_battery_source(
    energy_sources: list,
    battery_charge_sensor: str,
    battery_discharge_sensor: str,
    battery_power_sensor: Optional[str] = None,
) -> None:
    """Configure battery energy source."""
    # Remove existing battery source
    energy_sources[:] = [s for s in energy_sources if s.get("type") != "battery"]

    # Add new battery source
    battery_source = {
        "type": "battery",
        "stat_energy_from": battery_discharge_sensor,
        "stat_energy_to": battery_charge_sensor
    }

    # stat_rate is the real-time power sensor — needed for power-sources-graph
    if battery_power_sensor:
        battery_source["stat_rate"] = battery_power_sensor

    energy_sources.append(battery_source)
    _LOGGER.info("Configured battery: charge=%s, discharge=%s (power: %s)",
                 battery_charge_sensor, battery_discharge_sensor, battery_power_sensor)


def _configure_ev_device(
    device_consumption: list,
    ev_energy_sensor: str
) -> None:
    """Configure EV charger as individual device consumption."""
    # Remove existing EV device entry (check by sensor name)
    device_consumption[:] = [
        d for d in device_consumption
        if d.get("stat_consumption") != ev_energy_sensor
    ]

    # Add EV charger device
    ev_device = {
        "stat_consumption": ev_energy_sensor
    }

    device_consumption.append(ev_device)
    _LOGGER.info("Configured EV charger as individual device: %s", ev_energy_sensor)
