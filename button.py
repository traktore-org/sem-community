"""SEM buttons — one-press actions that were Developer-Tools-only.

(2.1 audit, item 8) The battery-night backfill existed as a service with
log-only feedback. A button on the device + a persistent notification with
the recovered-nights count make it exist for people who do not read logs.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .utils.device_names import charger_display_name  # (#1053)
from .const import DOMAIN
from .coordinator.install_modules import kept_descriptions, presence_of
from .sensor import _cleanup_stale_entities, _fix_entity_ids

_LOGGER = logging.getLogger(__name__)

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
    # (#923) The battery-night backfill is a battery entity.
    static_descriptions = kept_descriptions("button", BUTTONS, presence_of(coordinator))
    entities: list = [SEMButton(coordinator, d) for d in static_descriptions]

    # (#980) One Pause button per charger. It applies the duration dropdown
    # beside it — which is how the same button also cancels.
    full_config = {**entry.data, **entry.options}
    for _cidx, charger_cfg in enumerate(full_config.get("ev_chargers") or []):
        if not isinstance(charger_cfg, dict):
            continue
        cid = charger_cfg.get("id", "ev_charger")
        entities.append(SEMChargerPauseButton(
            coordinator,
            ButtonEntityDescription(
                key=f"charger_{cid}_pause_charging",
                icon="mdi:pause-octagon-outline",
                entity_category=EntityCategory.CONFIG,
            ),
            entry, cid, charger_display_name(hass, charger_cfg, _cidx),
        ))

    async_add_entities(entities)
    # (#980) The sweep below deletes any button whose key it does not
    # recognise, so it must be told about the per-charger ones. Without
    # this they are registered and removed again in the same second —
    # which no unit test saw, and .175 showed on the first deploy.
    all_descriptions = list(static_descriptions) + [
        e.entity_description for e in entities
        if isinstance(e, SEMChargerPauseButton)
    ]
    # ``self.entity_id`` below is honoured only at FIRST registration; an
    # install that registered the button before the #815 id line existed
    # keeps the derived id (the .175 rig held
    # ``button.garden_sem_rebuild_battery_night_history`` on 01.09.2026).
    # Same registry repair switch/number/sensor run at setup.
    _fix_entity_ids(hass, entry, all_descriptions, "button")
    _cleanup_stale_entities(hass, entry, all_descriptions, "button")


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


class SEMChargerPauseButton(CoordinatorEntity, ButtonEntity):
    """(#980) "Pause charging" — for as long as the dropdown beside it says.

    @RienduPre wanted to stop a charger for a while without opening his
    Wallbox app. What SEM adds is not a new kind of stop: it is the mode he
    would have picked anyway — Off, which is hands-off and starts no fight
    with a box that restarts itself — plus the part he cannot do himself,
    which is remembering to put it back.

    The button always applies the dropdown, so two entities give three
    gestures: pause, re-arm with a different duration, and *Resume now*.
    All of the thinking is in ``charge_pause.press``, which is pure; this
    writes what it returns.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, description: ButtonEntityDescription,
                 entry: ConfigEntry, charger_id: str,
                 charger_name: str = "EV Charger") -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # (#677) the BARE key translates; the charger rides a placeholder.
        self._attr_translation_key = "pause_charging"
        self._attr_translation_placeholders = {"charger": charger_name}
        self._attr_device_info = coordinator.device_info
        self.entity_id = f"button.sem_{description.key}"
        self._entry = entry
        self._charger_id = charger_id

    def _charger_cfg(self) -> dict:
        for c in (self.coordinator.config.get("ev_chargers") or []):
            if isinstance(c, dict) and (c.get("id") or "ev_charger") == self._charger_id:
                return c
        return {}

    async def async_press(self) -> None:
        import homeassistant.util.dt as dt_util

        from .coordinator.charge_pause import press

        cfg = self._charger_cfg()
        # (#980) The duration is ONE global choice — see select.py. Each
        # charger keeps its own button, so pausing one and leaving the
        # other running still works; only the "how long" is shared.
        from .coordinator.charge_pause import DEFAULT_PAUSE_DURATION
        option = self.coordinator.config.get(
            "pause_duration", DEFAULT_PAUSE_DURATION)
        writes = press(cfg, option, dt_util.now())

        from . import persist_per_charger_option
        for key, value in writes.items():
            persist_per_charger_option(
                self.hass, self._entry, self.coordinator,
                self._charger_id, key, value,
            )
        _LOGGER.info(
            "Charger %s: pause button — %s", self._charger_id,
            ", ".join(f"{k}={v}" for k, v in writes.items()) or "nothing to do",
        )
