"""SEM Solar Energy Management button entities.

Per-charger "Set charge target as default" (#246, Phase 2B): copies this
charger's current charge target (Min/Max, kWh + SOC%, target type) and the
charge-by deadline into the GLOBAL config keys. Those globals are the source
the v3->v4 seed migration reads, so newly-added chargers inherit them and the
chosen target/time becomes the default for following setups.

Uses the same snapshot-keyed ``async_update_entry`` persistence as the
per-charger number/select/time entities (no integration reload).
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Keys copied from the charger into the global default config on press (#246).
_DEFAULT_KEYS = (
    "daily_ev_target",
    "daily_ev_target_max",
    "ev_target_soc",
    "ev_target_soc_max",
    "ev_target_type",
    "ev_target_time",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up per-charger 'set as default' buttons."""
    coordinator: SEMCoordinator = entry.runtime_data
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])

    entities: list[ButtonEntity] = []
    for charger_cfg in ev_chargers:
        cid = charger_cfg.get("id", "ev_charger")
        cname = charger_cfg.get("name", "EV Charger")
        desc = ButtonEntityDescription(
            key=f"charger_{cid}_set_default_target",
            name=f"{cname} Set Target As Default",
            icon="mdi:content-save-cog",
            entity_category=EntityCategory.CONFIG,
        )
        entities.append(SEMPerChargerSetDefaultButton(coordinator, desc, entry, cid))

    if entities:
        _LOGGER.info("Created %d per-charger set-default buttons", len(entities))
    async_add_entities(entities)


class SEMPerChargerSetDefaultButton(CoordinatorEntity, ButtonEntity):
    """Copy this charger's target + deadline into the global default config (#246)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: ButtonEntityDescription,
        entry: ConfigEntry,
        charger_id: str,
    ) -> None:
        """Initialize the set-default button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"button.sem_{description.key}"
        self._entry = entry
        self._charger_id = charger_id

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        """Return device information."""
        return self.coordinator.device_info

    def _charger_cfg(self) -> dict:
        for c in self.coordinator.config.get("ev_chargers", []):
            if c.get("id") == self._charger_id:
                return c
        return {}

    async def async_press(self) -> None:
        """Copy the charger's current target + deadline into the global defaults.

        Race-safety (#274/M1): there is intentionally NO ``await`` between reading
        ``self._entry.options`` below and ``async_update_entry`` at the end, so in
        HA's single-threaded event loop no concurrent options-flow / number write
        can interleave and be clobbered — the read reflects the latest committed
        options and the write is atomic with it.
        """
        cfg = self._charger_cfg()
        if not cfg:
            _LOGGER.warning("Set-default: charger %s not found", self._charger_id)
            return

        new_options = {**self._entry.options}
        copied = {}
        for key in _DEFAULT_KEYS:
            val = cfg.get(key)
            if val is not None:
                new_options[key] = val
                copied[key] = val

        if not copied:
            _LOGGER.info("Set-default: charger %s has no target to copy", self._charger_id)
            return

        if isinstance(getattr(self.coordinator, "config", None), dict):
            self.coordinator.config.update({**self._entry.data, **new_options})

        # Persist without a reload (snapshot-keyed skip — matches number/select).
        self.coordinator._skip_options_reload = new_options
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        _LOGGER.info(
            "Set charger %s target as global default: %s", self._charger_id, copied,
        )
