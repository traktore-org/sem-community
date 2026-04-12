"""SEM Solar Energy Management binary sensors."""
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
    # Phase 7: Utility signal active
    BinarySensorEntityDescription(
        key="utility_signal_active",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SEMSolarBinarySensor(coordinator, description, entry)
        for description in BINARY_SENSOR_TYPES
    ]

    async_add_entities(entities)


class SEMSolarBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """EMS Solar Optimizer binary sensor entity."""

    _attr_has_entity_name = True
    _logged_unavailable: bool = False

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
        self._entry = entry

        if description.key in self.DIAGNOSTIC_SENSORS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        if description.key in self.DISABLED_BY_DEFAULT:
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        """Return if entity is available. Logs once on transition."""
        is_available = self.coordinator.last_update_success and self.coordinator.data is not None
        if not is_available and not self._logged_unavailable:
            _LOGGER.warning("Binary sensor %s is unavailable", self.entity_description.key)
            self._logged_unavailable = True
        elif is_available and self._logged_unavailable:
            _LOGGER.info("Binary sensor %s is available again", self.entity_description.key)
            self._logged_unavailable = False
        return is_available

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        return self.coordinator.data.get(key, False)

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info
