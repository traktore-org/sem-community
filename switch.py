"""SEM Solar Energy Management switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates

SWITCH_TYPES = [
    SwitchEntityDescription(
        key="night_charging",
        entity_category=EntityCategory.CONFIG,
    ),
    SwitchEntityDescription(
        key="observer_mode",
        entity_category=EntityCategory.CONFIG,
    ),
    SwitchEntityDescription(
        key="smart_night_charging",
        entity_category=EntityCategory.CONFIG,
    ),
]

# (ev_limit_surplus (#235) was folded into the optional Max ceiling (#245); its
# global config-switch mechanism + entity are gone. Old entities are auto-removed
# by the stale-entity cleanup below since they're no longer in valid_keys.)


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management switches."""
    coordinator: SEMCoordinator = entry.runtime_data

    switches = [
        SEMSolarSwitch(coordinator, description, entry.entry_id)
        for description in SWITCH_TYPES
    ]

    # Per-charger night charging switches (#193)
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    per_charger_keys = set()
    if len(ev_chargers) >= 1:
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id", "ev_charger")
            cname = charger_cfg.get("name", "EV Charger")
            desc = SwitchEntityDescription(
                key=f"charger_{cid}_night_charging",
                entity_category=EntityCategory.CONFIG,
            )
            per_charger_keys.add(desc.key)
            switches.append(SEMPerChargerSwitch(
                coordinator, desc, entry.entry_id, cid, cname,
            ))
            # Per-charger ev_limit_surplus switch (#235) removed (#245): folded into
            # the per-charger Solar Max ceiling. Old entity auto-removed by cleanup.
        _LOGGER.info(
            "Created per-charger switches for %d charger(s)",
            len(ev_chargers),
        )

    async_add_entities(switches)

    # Fix entity_ids from pre-translation installs
    try:
        registry = er.async_get(hass)
        for desc in SWITCH_TYPES:
            uid = f"sem_{desc.key}"
            correct_eid = f"switch.sem_{desc.key}"
            for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
                if entity_entry.unique_id == uid and entity_entry.entity_id != correct_eid:
                    existing = registry.async_get(correct_eid)
                    if existing is None:
                        registry.async_update_entity(entity_entry.entity_id, new_entity_id=correct_eid)
                        _LOGGER.info("Fixed switch entity_id: %s → %s", entity_entry.entity_id, correct_eid)
    except Exception as e:
        _LOGGER.debug("Switch entity ID fix skipped: %s", e)

    # Clean up stale switch entities from previous versions
    try:
        registry = er.async_get(hass)
        valid_keys = {d.key for d in SWITCH_TYPES} | per_charger_keys
        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.domain != "switch":
                continue
            # SEM uses two unique_id formats: "sem_{key}" or "{entry_id}_{key}"
            unique_id = entity_entry.unique_id or ""
            key = None
            if unique_id.startswith("sem_"):
                key = unique_id[4:]
            elif unique_id.startswith(f"{entry.entry_id}_"):
                key = unique_id[len(entry.entry_id) + 1:]
            if key and key not in valid_keys:
                _LOGGER.info("Removing stale switch entity %s (key '%s' removed)", entity_entry.entity_id, key)
                registry.async_remove(entity_entry.entity_id)
    except Exception as e:
        _LOGGER.debug("Stale switch cleanup skipped: %s", e)


class SEMSolarSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """SEM Solar Energy Management switch with state persistence."""

    _attr_has_entity_name = True
    _logged_unavailable: bool = False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        is_available = self.coordinator.last_update_success and self.coordinator.data is not None
        if not is_available and not self._logged_unavailable:
            _LOGGER.warning("Switch %s is unavailable (coordinator update failed)", self.entity_description.key)
            self._logged_unavailable = True
        elif is_available and self._logged_unavailable:
            _LOGGER.info("Switch %s is available again", self.entity_description.key)
            self._logged_unavailable = False
        return is_available

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: SwitchEntityDescription,
        entry_id: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"sem_{description.key}"
        self._attr_translation_key = description.key
        self._attr_suggested_object_id = f"sem_{description.key}"
        self._attr_device_info = coordinator.device_info
        # Force stable entity ID regardless of HA language
        self.entity_id = f"switch.sem_{description.key}"

        if description.key == "night_charging":
            # Opt-in (#256): default OFF so a fresh install charges on solar surplus only
            # and never grid-charges the car overnight unasked. RestoreEntity below
            # preserves existing users — they keep whatever state they already had.
            self._is_on = False
        elif description.key == "observer_mode":
            self._is_on = coordinator.config_entry.options.get("observer_mode", False)
        else:
            self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant - restore previous state."""
        await super().async_added_to_hass()

        # Both remaining switches persist across reboots
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
            _LOGGER.info("Restored %s state to: %s", self.entity_description.key, 'ON' if self._is_on else 'OFF')
        else:
            _LOGGER.info("No previous state for %s, using default: %s", self.entity_description.key, 'ON' if self._is_on else 'OFF')

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        _LOGGER.info("Turning on %s", self.entity_description.key)
        self._is_on = True

        try:
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.warning("Failed to refresh coordinator when turning on %s: %s", self.entity_description.key, e)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        _LOGGER.info("Turning off %s", self.entity_description.key)
        self._is_on = False

        try:
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.warning("Failed to refresh coordinator when turning off %s: %s", self.entity_description.key, e)


class SEMPerChargerSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Per-charger night charging switch (#193)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: SwitchEntityDescription,
        entry_id: str,
        charger_id: str,
        charger_name: str,
    ) -> None:
        """Initialize per-charger switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"sem_{description.key}"
        self._attr_translation_key = description.key
        self._attr_suggested_object_id = f"sem_{description.key}"
        self._attr_device_info = coordinator.device_info
        self.entity_id = f"switch.sem_{description.key}"
        self._charger_id = charger_id
        # Opt-in (#256): default OFF. A newly-added charger won't night-charge until
        # the user enables it, so it can't silently inherit a grid top-up. Existing
        # chargers keep their state via RestoreEntity in async_added_to_hass below.
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore previous state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on night charging for this charger."""
        self._is_on = True
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off night charging for this charger."""
        self._is_on = False
        await self.coordinator.async_request_refresh()

