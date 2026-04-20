"""SEM Solar Energy Management select entities."""
import logging
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SEMCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

EV_CHARGING_MODES = {
    "auto": "Auto",
    "minpv": "Min + PV",
    "now": "Maximum",
    "off": "Off",
}

SELECT_TYPES = [
    SelectEntityDescription(
        key="ev_charging_mode",
        options=list(EV_CHARGING_MODES.keys()),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEM select entities."""
    coordinator: SEMCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        SEMSelectEntity(coordinator, entry, description)
        for description in SELECT_TYPES
    ]
    async_add_entities(entities)


class SEMSelectEntity(CoordinatorEntity, SelectEntity):
    """SEM select entity for charging mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SEMCoordinator,
        entry: ConfigEntry,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info
        self._attr_translation_key = description.key
        # Force stable entity ID regardless of language
        self.entity_id = f"select.sem_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        value = self.coordinator.config.get(
            self.entity_description.key, "auto"
        )
        # Map legacy modes to auto (pv and self_consumption are now internal)
        if value in ("pv", "self_consumption"):
            return "auto"
        return value if value in EV_CHARGING_MODES else "auto"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in EV_CHARGING_MODES:
            return

        config_key = self.entity_description.key

        # Update config entry options
        new_options = {**self._entry.options}
        new_options[config_key] = option
        self.hass.config_entries.async_update_entry(
            self._entry, options=new_options
        )

        # Update coordinator config immediately
        await self.coordinator.async_update_config({config_key: option})
        await self.coordinator.async_request_refresh()

        _LOGGER.info("Changed %s to %s", config_key, option)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
