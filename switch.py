"""SEM Solar Energy Management switches."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SEMCoordinator
from .persisted_flags import PERSISTED_FLAG_DEFAULTS

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
    # #638 G4 — energy plan actuation: while ON, the joint energy plan's
    # blocks feed the existing signals (EV amps floor / wait, load window
    # gates). ON since the one-gate build (#638 C8) — this switch IS the
    # kill-switch, and OFF means pure shadow, log-only. Same persistence
    # pattern as observer/vacation mode.
    SwitchEntityDescription(
        key="energy_plan_actuation",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:calendar-clock",
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

        if description.key in self._PERSISTED_DEFAULTS:
            # (#777) Seed from the EXPLICIT config — options first (every
            # flip persists there via ``_persist_flag``), then entry data
            # (the install flow writes there), then the per-key default.
            # The old seed read options only, so "observer checked at
            # install" showed an OFF switch while the coordinator
            # observed.
            explicit = self._configured(description.key)
            self._is_on = (explicit if explicit is not None
                           else self._PERSISTED_DEFAULTS[description.key])
        else:
            self._is_on = False

    # (#777) The three persisted toggles and what a fresh install means by
    # silence. Defined in ``persisted_flags`` and shared by reference, not
    # copied: setup resolves the very same flags from the very same three
    # sources before building the coordinator, and two tables of "what
    # silence means" is exactly how the two readers drifted apart.
    _PERSISTED_DEFAULTS = PERSISTED_FLAG_DEFAULTS

    def _configured(self, key: str) -> Optional[bool]:
        """The explicit config value for ``key`` — None if never recorded.

        options outrank data: a runtime flip (persisted to options the
        moment it happens) is newer than the install-time choice by
        construction. Non-mapping sources (bare test stubs) are skipped.
        """
        from collections.abc import Mapping
        entry = self.coordinator.config_entry
        for src in (getattr(entry, "options", None),
                    getattr(entry, "data", None)):
            if isinstance(src, Mapping) and key in src:
                return bool(src[key])
        return None

    def _apply_restored_state(self, last_state) -> None:
        """(#777) Explicit config beats ghost restore.

        ``switch.sem_observer_mode`` has a forced-stable entity id and
        HA's restore-state store outlives the config entry — so a FRESH
        install on a machine that ever ran observer-ON restored the dead
        install's state over this install's explicit config and silently
        never controlled hardware (reported live, 15.08). Every flip
        persists to options the moment it happens, so the restore store
        is only ever a duplicate or a ghost; it is honored solely when
        neither options nor data carries the key at all — a pre-persist
        install upgrading, the one case where it is the only record.
        """
        key = self.entity_description.key
        if key not in self._PERSISTED_DEFAULTS:
            if last_state is not None:
                self._is_on = last_state.state == "on"
            return
        explicit = self._configured(key)
        if explicit is not None:
            self._is_on = explicit
            _LOGGER.info("%s: %s (explicit config)", key,
                         "ON" if self._is_on else "OFF")
        elif last_state is not None:
            self._is_on = last_state.state == "on"
            _LOGGER.info(
                "%s: %s (restored — no config record, legacy install)",
                key, "ON" if self._is_on else "OFF")
        else:
            self._is_on = self._PERSISTED_DEFAULTS[key]
            _LOGGER.info("%s: %s (default)", key,
                         "ON" if self._is_on else "OFF")

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant - restore previous state."""
        await super().async_added_to_hass()

        self._apply_restored_state(await self.async_get_last_state())

        # Observer mode must take hold the instant the entity restores — push the
        # restored state straight onto the coordinator so the very first control
        # cycle is hands-off if the switch was last ON (the per-cycle pull is only
        # a backstop). Without this, the startup config option (often unset →
        # False) won the race and SEM controlled hardware despite the switch.
        if self.entity_description.key == "observer_mode":
            self.coordinator._observer_mode = self._is_on
        # Same immediacy for vacation mode (#594): push the restored state so
        # the first control cycle after a reboot already gates comfort heating.
        if self.entity_description.key == "vacation_mode":
            self.coordinator._vacation_switch_on = self._is_on
        # #638 G4: actuation must NOT silently arm before the restore lands —
        # push the restored state so the first night cycle reads the truth.
        if self.entity_description.key == "energy_plan_actuation":
            self.coordinator._energy_plan_actuation = self._is_on


    def _persist_flag(self, value: bool) -> None:
        """Persist the toggle into entry.options WITHOUT a reload.

        PROD/TEST 2026-07-18: observer mode lived only in the switch entity +
        the running coordinator flag. Every config-entry RELOAD built a fresh
        coordinator from ``config.get("observer_mode", False)`` — and until
        the switch platform re-attached (minutes on a busy start), a
        supposedly hands-off install ran FULLY ARMED; a VPP test in that
        window force-discharged the real battery. Same no-reload write path
        as set_option's tunable branch: arm the skip mirror, update the
        running config in place, then write the entry options.
        """
        if self.hass is None:
            return  # pre-add lifecycle / bare test stubs — nothing to persist to
        key = self.entity_description.key
        entry = self.coordinator.config_entry
        new_options = {**(entry.options or {}), key: value}
        self.coordinator._skip_options_reload = dict(new_options)
        try:
            self.coordinator.config[key] = value
        except Exception:  # noqa: BLE001
            pass
        self.hass.config_entries.async_update_entry(entry, options=new_options)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """(#764) The observer switch carries observer mode's WOULD
        decisions — the standard simulation surface. A fresh reader gets
        the current per-device would-state without history; a sim bridge
        subscribes to the ``solar_energy_management_observer_decision``
        event for the edges. Empty when observing is off: the map would
        be stale the moment live actuation resumes."""
        if self.entity_description.key != "observer_mode":
            return None
        try:
            decisions = getattr(
                getattr(self.coordinator, "_surplus_controller", None),
                "observer_decisions", {}) or {}
        except Exception:  # noqa: BLE001 — attributes must never break the entity
            decisions = {}
        return {"would_decisions": dict(decisions) if self._is_on else {}}

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
        if self.entity_description.key == "energy_plan_actuation":
            self.coordinator._energy_plan_actuation = True  # #638 G4 — immediate
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
        if self.entity_description.key == "energy_plan_actuation":
            self.coordinator._energy_plan_actuation = False  # #638 G4 — immediate
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

