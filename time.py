"""SEM Solar Energy Management time entities.

Per-charger "charge by" deadline (#246, Phase 2): the time the Min floor should
be reached by. Drives the night-charging current scaling in
``coordinator/ev_control.py`` (a short deadline raises the current; an
impossible one warns). Stored as ``HH:MM`` in the charger config dict so the
"set as default" button (#246) can copy it and it persists across restarts.
"""

from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_EV_TARGET_TIME
from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _parse_hhmm(value: str | None) -> dt_time:
    """Parse an ``HH:MM`` string into a ``datetime.time`` (falls back to default)."""
    try:
        parts = str(value).split(":")
        return dt_time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, AttributeError, IndexError):
        h, m = DEFAULT_EV_TARGET_TIME.split(":")
        return dt_time(int(h), int(m))


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up per-charger target-time entities."""
    coordinator: SEMCoordinator = entry.runtime_data
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])

    entities: list[TimeEntity] = []
    for charger_cfg in ev_chargers:
        cid = charger_cfg.get("id", "ev_charger")
        cname = charger_cfg.get("name", "EV Charger")
        desc = TimeEntityDescription(
            key=f"charger_{cid}_target_time",
            name=f"{cname} Charge By",
            icon="mdi:clock-end",
            entity_category=EntityCategory.CONFIG,
        )
        initial = charger_cfg.get("ev_target_time") or full_config.get(
            "ev_target_time", DEFAULT_EV_TARGET_TIME
        )
        entities.append(
            SEMPerChargerTime(coordinator, desc, entry, cid, "ev_target_time", initial)
        )

    if entities:
        _LOGGER.info("Created %d per-charger target-time entities", len(entities))
    async_add_entities(entities)


class SEMPerChargerTime(CoordinatorEntity, TimeEntity):
    """Per-charger charge-by deadline, persisted in the charger config dict (#246)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: TimeEntityDescription,
        entry: ConfigEntry,
        charger_id: str,
        config_key: str,
        initial_value: str,
    ) -> None:
        """Initialize per-charger time entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"time.sem_{description.key}"
        self._entry = entry
        self._charger_id = charger_id
        self._config_key = config_key
        self._attr_native_value = _parse_hhmm(initial_value)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        """Return device information."""
        return self.coordinator.device_info

    async def async_set_value(self, value: dt_time) -> None:
        """Persist the deadline (HH:MM) into the charger config (snapshot-keyed skip)."""
        self._attr_native_value = value
        hhmm = value.strftime("%H:%M")

        new_options = {**self._entry.options}
        # Copy charger dicts — in-place mutation leaves entry.options unchanged so
        # async_update_entry skips persisting and the value reverts on restart (#245).
        ev_chargers = [dict(c) for c in new_options.get("ev_chargers", [])]
        for charger in ev_chargers:
            if charger.get("id") == self._charger_id:
                charger[self._config_key] = hhmm
                break
        new_options["ev_chargers"] = ev_chargers

        if isinstance(getattr(self.coordinator, "config", None), dict):
            self.coordinator.config.update({**self._entry.data, **new_options})

        self.coordinator._skip_options_reload = new_options
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()
        _LOGGER.info(
            "Updated per-charger %s.%s to %s",
            self._charger_id, self._config_key, hhmm,
        )
