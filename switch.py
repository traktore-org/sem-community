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
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SEMCoordinator
from .observer_readiness import observation_progress

_OBSERVER_STARTED_AT_OPTION = "_observer_mode_started_at"

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates

SWITCH_TYPES = [
    SwitchEntityDescription(
        key="observer_mode",
        entity_category=EntityCategory.CONFIG,
    ),
    # #594 — vacation mode: while ON, SEM suppresses comfort heating
    # (heat-pump SG-Ready boost + hot-water solar target). OR'd with the
    # optional external ``vacation_mode_entity`` config key each cycle.
    SwitchEntityDescription(
        key="vacation_mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:beach",
    ),
]

# (ev_limit_surplus (#235) was folded into the optional Max ceiling (#245); its
# global config-switch mechanism + entity are gone. Old entities are auto-removed
# by the stale-entity cleanup below since they're no longer in valid_keys.)
#
# Removed in #277 Phase C:
#   - global ``night_charging`` + ``smart_night_charging`` switches
#   - per-charger ``charger_<id>_night_charging`` switches
#   - per-charger ``charger_<id>_smart_night_charging`` switches
#   - per-charger ``charger_<id>_tariff_optimized`` switches
# All four intents are now carried by the per-charger
# ``select.sem_charger_<id>_charge_mode`` selector — picking a Charge
# mode is the only knob. The stale-entity cleanup below removes the
# orphaned entries from the registry on the next setup.


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management switches."""
    coordinator: SEMCoordinator = entry.runtime_data

    # #277 Phase C: all four legacy per-charger switches were removed.
    # The remaining global switch (``observer_mode``) is the only one
    # left in SWITCH_TYPES. The stale-entity cleanup at the bottom of
    # this function purges the removed entries from the registry.
    switches = [
        SEMSolarSwitch(coordinator, description, entry.entry_id)
        for description in SWITCH_TYPES
    ]
    per_charger_keys: set[str] = set()

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

        if description.key == "observer_mode":
            self._is_on = coordinator.config_entry.options.get("observer_mode", False)
        elif description.key == "vacation_mode":
            # #594 — same persistence pattern as observer_mode: seed from the
            # config option, then RestoreEntity takes over across reboots.
            self._is_on = coordinator.config_entry.options.get("vacation_mode", False)
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

        # Observer mode must take hold the instant the entity restores — push the
        # restored state straight onto the coordinator so the very first control
        # cycle is hands-off if the switch was last ON (the per-cycle pull is only
        # a backstop). Without this, the startup config option (often unset →
        # False) won the race and SEM controlled hardware despite the switch.
        if self.entity_description.key == "observer_mode":
            self.coordinator._observer_mode = self._is_on
            if self._is_on and not (
                self.coordinator.config_entry.options or {}
            ).get(_OBSERVER_STARTED_AT_OPTION):
                # Existing observer installs predate the countdown. Start their
                # clock at first load rather than guessing historical uptime.
                self._persist_flag(True)
        # Same immediacy for vacation mode (#594): push the restored state so
        # the first control cycle after a reboot already gates comfort heating.
        if self.entity_description.key == "vacation_mode":
            self.coordinator._vacation_switch_on = self._is_on


    def _persist_flag(self, value: bool) -> None:
        """Persist the toggle and observer countdown without a reload.

        Observer timing lives in entry options so a Home Assistant restart does
        not restart the 72-hour clock. Turning observer mode off clears the clock;
        turning it on starts a fresh one unless an existing start is being
        restored. Reaching zero never disables observer mode automatically.
        """
        if self.hass is None:
            return  # pre-add lifecycle / bare test stubs — nothing to persist to
        key = self.entity_description.key
        old_options = dict(self.coordinator.config_entry.options or {})
        new_options = {**old_options, key: value}
        if key == "observer_mode":
            if value:
                new_options.setdefault(
                    _OBSERVER_STARTED_AT_OPTION,
                    dt_util.utcnow().isoformat(),
                )
            else:
                new_options.pop(_OBSERVER_STARTED_AT_OPTION, None)
        self.coordinator._skip_options_reload = dict(new_options)
        try:
            self.coordinator.config[key] = value
        except Exception:  # noqa: BLE001
            pass
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry,
            options=new_options,
        )

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the restart-durable 72-hour observer readiness clock."""
        if self.entity_description.key != "observer_mode":
            return None
        started_at = (self.coordinator.config_entry.options or {}).get(
            _OBSERVER_STARTED_AT_OPTION
        )
        progress = observation_progress(started_at, now=dt_util.utcnow())
        return {
            "observation_started_at": started_at,
            "observation_target_hours": 72,
            "observation_elapsed_seconds": progress["elapsed_seconds"],
            "observation_remaining_seconds": progress["remaining_seconds"],
            "ready_for_manual_activation": progress["ready"],
            # Advisory only: observer mode remains read-only until explicitly off.
            "automatic_activation": False,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        _LOGGER.info("Turning on %s", self.entity_description.key)
        self._is_on = True
        # Drive the coordinator flag directly so observer mode flips this instant,
        # independent of the per-cycle entity lookup.
        if self.entity_description.key == "observer_mode":
            self.coordinator._observer_mode = True
        if self.entity_description.key == "vacation_mode":
            self.coordinator._vacation_switch_on = True  # #594 — immediate
        # Reload-durable: the flag must survive a config-entry reload (see
        # _persist_flag — the unprotected-window class).
        self._persist_flag(True)
        # Push the new state immediately (#259): otherwise the UI only reflects the
        # toggle on the next coordinator push, and a swallowed refresh error below
        # would silently leave HA showing the old state.
        self.async_write_ha_state()

        try:
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.warning("Failed to refresh coordinator when turning on %s: %s", self.entity_description.key, e)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        _LOGGER.info("Turning off %s", self.entity_description.key)
        self._is_on = False
        if self.entity_description.key == "observer_mode":
            self.coordinator._observer_mode = False
        if self.entity_description.key == "vacation_mode":
            self.coordinator._vacation_switch_on = False  # #594 — immediate
        self._persist_flag(False)  # reload-durable (see _persist_flag)
        self.async_write_ha_state()  # reflect immediately (#259)

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
        force_off: bool = False,
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
        # One-time #255 reconciliation: force OFF over the restored state when the removed
        # global night switch was last OFF (so a globally-disabled user isn't re-enabled).
        self._force_off = force_off
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
        if self._force_off:
            self._is_on = False  # #255 one-time reconciliation (global was OFF)

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
        self.async_write_ha_state()  # reflect immediately (#259)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off night charging for this charger."""
        self._is_on = False
        self.async_write_ha_state()  # reflect immediately (#259)
        await self.coordinator.async_request_refresh()

