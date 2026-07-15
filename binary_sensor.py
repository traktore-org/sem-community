"""SEM Solar Energy Management binary sensors."""

from __future__ import annotations

import logging
from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates

BINARY_SENSOR_TYPES = [
    BinarySensorEntityDescription(
        key="ev_connected",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    BinarySensorEntityDescription(
        key="ev_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    BinarySensorEntityDescription(
        key="battery_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    BinarySensorEntityDescription(
        key="battery_discharging",
        device_class=BinarySensorDeviceClass.BATTERY,
    ),
    BinarySensorEntityDescription(
        key="grid_export_active",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    BinarySensorEntityDescription(
        key="solar_active",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    # (#559 Phase 0) debounced surplus availability for user automations
    # (no device class — POWER/RUNNING would show misleading icons)
    BinarySensorEntityDescription(
        key="surplus_available",
    ),
    # Phase 0: Forecast available
    BinarySensorEntityDescription(
        key="forecast_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    # Phase 1: Dynamic tariff active
    BinarySensorEntityDescription(
        key="tariff_is_dynamic",
    ),
    # Phase 2: Heat pump solar boost active
    BinarySensorEntityDescription(
        key="heat_pump_solar_boost",
    ),
    # #437: heat pump registered with the surplus controller (presence
    # flag for the dashboard auto-hide — sg_ready_state defaults to 2
    # even when no controller exists, so the dashboard needs an
    # explicit signal to distinguish "unconfigured" from "in normal").
    BinarySensorEntityDescription(
        key="heat_pump_registered",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    # Phase 7: Utility signal active
    BinarySensorEntityDescription(
        key="utility_signal_active",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    # #590 — layered-trace health: ON when a control OR perception layer-boundary
    # fault has persisted (a subsystem decided to act but reality disagreed, or a
    # sign reading contradicts its energy counters). The single surface for the
    # trace + the retired sign-contradiction sensors; attributes name the fault.
    BinarySensorEntityDescription(
        key="layer_mismatch",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management binary sensors."""
    coordinator: SEMCoordinator = entry.runtime_data

    entities = [
        SEMSolarBinarySensor(coordinator, description, entry)
        for description in BINARY_SENSOR_TYPES
    ]

    # Per-charger binary sensors (#193)
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    for charger_cfg in ev_chargers:
        cid = charger_cfg.get("id", "ev_charger")
        entities.append(SEMSolarBinarySensor(coordinator, BinarySensorEntityDescription(
            key=f"charger_{cid}_connected",
            device_class=BinarySensorDeviceClass.PLUG,
        ), entry))

    async_add_entities(entities)


class SEMSolarBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """EMS Solar Optimizer binary sensor entity."""

    _attr_has_entity_name = True

    # Disabled by default
    DISABLED_BY_DEFAULT = {
        "forecast_available", "tariff_is_dynamic",
        "heat_pump_solar_boost", "utility_signal_active",
    }

    # Diagnostic sensors
    DIAGNOSTIC_SENSORS = {
        "forecast_available", "tariff_is_dynamic", "utility_signal_active",
    }

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: BinarySensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"sem_{description.key}"
        self._attr_translation_key = description.key
        # Force stable entity ID regardless of HA language
        self.entity_id = f"binary_sensor.sem_{description.key}"
        self._entry = entry

        if description.key in self.DIAGNOSTIC_SENSORS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        if description.key in self.DISABLED_BY_DEFAULT:
            self._attr_entity_registry_enabled_default = False

        # Start unavailable until first coordinator update (#70)
        self._first_update_received = False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self._first_update_received:
            if self.coordinator.last_update_success and self.coordinator.data is not None:
                self._first_update_received = True
            else:
                return False
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        return self.coordinator.data.get(key, False)

    @property
    def extra_state_attributes(self) -> Dict[str, Any] | None:
        """#590 — for the layered-trace health sensor, name the persisted fault
        (which subsystem, e.g. ``perception:battery_sign``, and for how many
        cycles) so it's diagnosable without the diagnose dump."""
        if self.entity_description.key != "layer_mismatch" or not self.coordinator.data:
            return None
        return {
            "subsystem": self.coordinator.data.get("layer_mismatch_subsystem"),
            "persisted_cycles": self.coordinator.data.get("layer_mismatch_cycles", 0),
        }

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info
