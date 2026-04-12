"""Button platform for SEM Solar Energy Management."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEM buttons from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # No buttons to add - recreation should be done via standalone scripts
    # See RECREATION_GUIDE.md for usage of standalone_recreation.py
    buttons = []

    async_add_entities(buttons)
