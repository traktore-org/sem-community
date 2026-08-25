"""Shared entity base — mirrors the real integration's identity rules.

The two that matter for SEM's detection:

* ``unique_id = f"{object_id}_{key}"`` with FIXED ENGLISH keys, which is what
  makes a role identifiable in any language;
* ``has_entity_name = True``, so the entity_id is built from the DEVICE name —
  which is how a Dutch, owner-named install ends up with entity_ids that
  contain no English role word at all (#804).
"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CHARGER_ID, DOMAIN, INSTALL_ID, NAMES_NL


class ZaptecSimEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, state, entry, key: str, on_charger: bool) -> None:
        self._state = state
        self._key = key
        obj_id = CHARGER_ID if on_charger else INSTALL_ID
        # The real rule, verbatim.
        self._attr_unique_id = f"{obj_id}_{key}"
        self._attr_name = NAMES_NL.get(key, key)
        prefix = entry.data.get("device_prefix") or "Zaptec"
        dev_name = f"{prefix} Lader" if on_charger else prefix
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, obj_id)},
            name=dev_name,
            manufacturer="Zaptec",
            model="Go 2 (simulated)" if on_charger else "Installation (simulated)",
        )

    async def async_added_to_hass(self) -> None:
        self._state.add_listener(self.async_write_ha_state)
