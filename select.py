"""SEM Solar Energy Management select entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

EV_CHARGING_MODES = {
    "auto": "Auto",
    "minpv": "Min + PV",
    "now": "Maximum",
    "off": "Off",
}

EV_TARGET_MODES = {
    "kwh": "kWh target",
    "soc": "SOC % target",
}

SELECT_TYPES = [
    SelectEntityDescription(
        key="ev_charging_mode",
        options=list(EV_CHARGING_MODES.keys()),
    ),
    SelectEntityDescription(
        key="ev_target_mode",
        options=list(EV_TARGET_MODES.keys()),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SEMConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEM select entities."""
    coordinator: SEMCoordinator = entry.runtime_data
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
        entry: SEMConfigEntry,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info
        self._attr_translation_key = description.key

    @property
    def _valid_options(self) -> dict:
        """Return the valid options dict for this entity."""
        key = self.entity_description.key
        if key == "ev_target_mode":
            return EV_TARGET_MODES
        return EV_CHARGING_MODES

    @property
    def _default_option(self) -> str:
        """Return the default option for this entity."""
        if self.entity_description.key == "ev_target_mode":
            return "kwh"
        return "auto"

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        value = self.coordinator.config.get(
            self.entity_description.key, self._default_option
        )
        valid = self._valid_options
        # Map legacy EV charging modes to auto
        if self.entity_description.key == "ev_charging_mode" and value in ("pv", "self_consumption"):
            return "auto"
        return value if value in valid else self._default_option

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._valid_options:
            return

        config_key = self.entity_description.key

        # Update coordinator config immediately
        await self.coordinator.async_update_config({config_key: option})

        # Persist without triggering integration reload
        self.coordinator._skip_options_reload = True
        new_options = {**self._entry.options}
        new_options[config_key] = option
        self.hass.config_entries.async_update_entry(
            self._entry, options=new_options
        )

        self.async_write_ha_state()

        _LOGGER.info("Changed %s to %s", config_key, option)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
