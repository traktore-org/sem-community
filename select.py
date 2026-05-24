"""SEM Solar Energy Management select entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
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

# ev_target_mode was renamed to ev_target_type (#235).
EV_TARGET_TYPES = {
    "kwh": "kWh target",
    "soc": "SOC % target",
}

SELECT_TYPES = [
    SelectEntityDescription(
        key="ev_charging_mode",
        options=list(EV_CHARGING_MODES.keys()),
    ),
    SelectEntityDescription(
        key="ev_target_type",
        options=list(EV_TARGET_TYPES.keys()),
    ),
]


def _target_type_options(has_vehicle_soc: bool) -> list[str]:
    """Target-type options — only offer SOC % when a vehicle SOC entity exists (#235)."""
    return ["kwh", "soc"] if has_vehicle_soc else ["kwh"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SEMConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEM select entities."""
    coordinator: SEMCoordinator = entry.runtime_data

    # Migrate the renamed global select entity (#235): ev_target_mode → ev_target_type.
    # Idempotent registry rename so existing installs don't leave an orphaned entity.
    # (Config values are read with a back-compat fallback, so no data migration is needed.)
    try:
        registry = er.async_get(hass)
        old_uid = f"{entry.entry_id}_ev_target_mode"
        new_uid = f"{entry.entry_id}_ev_target_type"
        old_eid = registry.async_get_entity_id("select", DOMAIN, old_uid)
        if old_eid:
            if registry.async_get_entity_id("select", DOMAIN, new_uid) is None:
                new_eid = "select.sem_ev_target_type"
                update = {"new_unique_id": new_uid}
                if registry.async_get(new_eid) is None:
                    update["new_entity_id"] = new_eid
                registry.async_update_entity(old_eid, **update)
                _LOGGER.info("Migrated select entity %s → %s (%s)", old_uid, new_uid, old_eid)
            else:
                # New entity already exists — drop the orphaned old one.
                registry.async_remove(old_eid)
                _LOGGER.info("Removed orphaned select entity %s", old_eid)
    except Exception as e:
        _LOGGER.debug("ev_target_type select migration skipped: %s", e)

    entities = [
        SEMSelectEntity(coordinator, entry, description)
        for description in SELECT_TYPES
    ]

    # Per-charger target-type selects (#235) — kWh / SOC %, SOC gated on vehicle SOC entity
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    if len(ev_chargers) >= 1:
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id", "ev_charger")
            desc = SelectEntityDescription(
                key=f"charger_{cid}_ev_target_type",
                options=list(EV_TARGET_TYPES.keys()),
                entity_category=EntityCategory.CONFIG,
            )
            entities.append(SEMPerChargerSelect(
                coordinator, desc, entry, cid, "ev_target_type",
                charger_cfg.get("ev_target_type") or charger_cfg.get("ev_target_mode") or "kwh",
            ))

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
        # Force a stable, language-independent entity_id (matches the switch pattern)
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"select.sem_{description.key}"

    @property
    def _is_target_type(self) -> bool:
        return self.entity_description.key == "ev_target_type"

    @property
    def options(self) -> list[str]:
        """Selectable options — SOC % only when a vehicle SOC entity is set (#235)."""
        if self._is_target_type:
            has_soc = bool(self.coordinator.config.get("vehicle_soc_entity"))
            return _target_type_options(has_soc)
        return list(EV_CHARGING_MODES.keys())

    @property
    def _default_option(self) -> str:
        """Return the default option for this entity."""
        if self._is_target_type:
            return "kwh"
        return "auto"

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        if self._is_target_type:
            # ev_target_mode was renamed to ev_target_type (#235) — read both.
            value = (
                self.coordinator.config.get("ev_target_type")
                or self.coordinator.config.get("ev_target_mode")
                or self._default_option
            )
        else:
            value = self.coordinator.config.get(
                self.entity_description.key, self._default_option
            )
            # Map legacy EV charging modes to auto
            if value in ("pv", "self_consumption"):
                return "auto"
        return value if value in self.options else self._default_option

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self.options:
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


class SEMPerChargerSelect(CoordinatorEntity, SelectEntity):
    """Per-charger target-type select, persisted into the charger's config dict (#235).

    Offers SOC % only when the charger has a ``vehicle_soc_entity`` configured;
    otherwise only kWh is selectable. Mirrors ``SEMPerChargerNumber`` persistence.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: SelectEntityDescription,
        entry: SEMConfigEntry,
        charger_id: str,
        config_key: str,
        initial_value: str,
    ) -> None:
        """Initialize per-charger select."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._charger_id = charger_id
        self._config_key = config_key
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = "ev_target_type"
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"select.sem_{description.key}"
        self._value = initial_value if initial_value in EV_TARGET_TYPES else "kwh"

    def _charger_cfg(self) -> dict:
        for c in self.coordinator.config.get("ev_chargers", []):
            if c.get("id") == self._charger_id:
                return c
        return {}

    @property
    def options(self) -> list[str]:
        """SOC % only when this charger has a vehicle SOC entity (#235)."""
        has_soc = bool(self._charger_cfg().get("vehicle_soc_entity"))
        return _target_type_options(has_soc)

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option, clamped to available options."""
        return self._value if self._value in self.options else "kwh"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        """Return device information."""
        return self.coordinator.device_info

    async def async_select_option(self, option: str) -> None:
        """Persist the selected target type into the charger config."""
        if option not in self.options:
            return
        self._value = option
        new_options = {**self._entry.options}
        ev_chargers = list(new_options.get("ev_chargers", []))
        for charger in ev_chargers:
            if charger.get("id") == self._charger_id:
                charger[self._config_key] = option
                break
        new_options["ev_chargers"] = ev_chargers
        if isinstance(getattr(self.coordinator, "config", None), dict):
            self.coordinator.config.update({**self._entry.data, **new_options})
        self.coordinator._skip_options_reload = True
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()
        _LOGGER.info(
            "Updated per-charger %s.%s to %s",
            self._charger_id, self._config_key, option,
        )
