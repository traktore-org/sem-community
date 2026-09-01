"""SEM buttons — one-press actions that were Developer-Tools-only.

(2.1 audit, item 8) The battery-night backfill existed as a service with
log-only feedback. A button on the device + a persistent notification with
the recovered-nights count make it exist for people who do not read logs.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import _fix_entity_ids

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="backfill_battery_nights",
        icon="mdi:database-clock",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SEMButton(coordinator, d) for d in BUTTONS)
    # ``self.entity_id`` below is honoured only at FIRST registration; an
    # install that registered the button before the #815 id line existed
    # keeps the derived id (the .175 rig held
    # ``button.garden_sem_rebuild_battery_night_history`` on 01.09.2026).
    # Same registry repair switch/number/sensor run at setup.
    _fix_entity_ids(hass, entry, list(BUTTONS), "button")


class SEMButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, description: ButtonEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"sem_{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_info = coordinator.device_info
        # Stable id like every other SEM entity (switch.sem_*, number.sem_*):
        # without it HA derives the id from device + translated name
        # ("button.garden_sem_rebuild_battery_night_history" on the rig),
        # which no card, doc or automation can address.
        self.entity_id = f"button.sem_{description.key}"

    async def async_press(self) -> None:
        if self.entity_description.key == "backfill_battery_nights":
            await self.hass.services.async_call(
                DOMAIN, "backfill_battery_nights", {"days": 365}, blocking=False,
            )
