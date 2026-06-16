"""SEM Solar Energy Management select entities."""

from __future__ import annotations

import logging
import re
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

# #277 Phase A — consolidated Charge mode selector. Replaces the
# four-toggle combinatorial UX (``ev_charging_mode`` ×
# ``night_charging`` × ``tariff_optimized`` × ``smart_night_charging``)
# with one named intent per charger. See
# ``docs/plans/2026-05-30_ev_charge_mode_consolidation.md`` for the
# full mapping, migration rules, and resolved design questions.
#
# ``solar_plus_cheap`` is conditionally hidden when no dynamic tariff
# is configured — the option appears automatically when the user adds
# a tariff. Maintainer decision Q1, 2026-05-30. Constant lives in
# ``consts/ev_charge_modes.py`` so the coordinator's read-side helper
# imports the same source of truth (no duplicated tuple in
# ``coordinator/coordinator.py``).
from .consts.ev_charge_modes import (
    DEFAULT_EV_CHARGE_MODE,
    EV_CHARGE_MODES,
)
from .consts.battery_modes import BATTERY_MODES, DEFAULT_BATTERY_MODE


_BATTERY_SLUG_RE = re.compile(r"^sensor\.sem_battery_(b\d+)_power$")


def _battery_slugs(coordinator: SEMCoordinator) -> list[str]:
    """Short per-battery slugs (``b1`` …) for multi-battery installs.

    Primary source is the Energy Dashboard ``battery_power_list`` order
    (same as the per-battery sensors in ``sensor.py``). But that depends
    on ``_energy_dashboard_config`` being populated at platform-setup
    time, which can lag the first refresh — so we FALL BACK to the
    persisted per-battery power sensors in the entity registry
    (``sensor.sem_battery_b<N>_power``). The registry survives restarts,
    so once a multi-battery install has its sensors the control entities
    are created deterministically on every boot. Empty on single-battery
    installs (no per-battery control entities created).
    """
    sr = getattr(coordinator, "_sensor_reader", None)
    ed = getattr(sr, "_energy_dashboard_config", None) if sr is not None else None
    batt_list = list(getattr(ed, "battery_power_list", []) or []) if ed is not None else []
    if len(batt_list) > 1:
        return [f"b{i + 1}" for i in range(len(batt_list))]

    # Fallback: discover from the persisted per-battery power sensors.
    try:
        reg = er.async_get(coordinator.hass)
        slugs = sorted({
            m.group(1)
            for ent in reg.entities.values()
            if (m := _BATTERY_SLUG_RE.match(ent.entity_id))
        })
        _LOGGER.debug("battery slugs (registry fallback): %s", slugs)
        return slugs if len(slugs) > 1 else []
    except Exception as exc:  # noqa: BLE001 — discovery must never break setup
        _LOGGER.debug("battery slug discovery failed: %s", exc)
        return []

SELECT_TYPES = [
    # ev_charging_mode and ev_target_type are PER-CHARGER only (#255) — the global
    # duplicates were removed (seeded per-charger by the v3→v4 migration). The old
    # global entities are removed from the registry below. No global selects remain.
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

    # v1.6.10 (#309): the explicit removal block for the now-removed
    # GLOBAL selects (``{entry_id}_ev_target_type``,
    # ``{entry_id}_ev_target_mode``, ``{entry_id}_ev_charging_mode``)
    # was folded into the registry-key sweep below. Each of those
    # unique_ids has the prefix ``{entry_id}_`` and a key that is NOT
    # in ``valid_keys = {SELECT_TYPES keys} | per_charger_keys``, so
    # the sweep removes them just as cleanly. Per-charger values were
    # seeded from the globals by the v3→v4 migration (#255), so no
    # data is lost.

    entities = [
        SEMSelectEntity(coordinator, entry, description)
        for description in SELECT_TYPES
    ]

    # Per-charger selects (#235, #255): target-type (kWh / SOC %) + charging mode.
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    per_charger_keys: set[str] = set()
    if len(ev_chargers) >= 1:
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id", "ev_charger")
            target_key = f"charger_{cid}_ev_target_type"
            mode_key = f"charger_{cid}_charge_mode"
            per_charger_keys.update({target_key, mode_key})
            entities.append(SEMPerChargerSelect(
                coordinator,
                SelectEntityDescription(
                    key=target_key,
                    options=list(EV_TARGET_TYPES.keys()),
                    entity_category=EntityCategory.CONFIG,
                ),
                entry, cid, "ev_target_type",
                charger_cfg.get("ev_target_type") or charger_cfg.get("ev_target_mode") or "kwh",
            ))
            # The legacy ``ev_charging_mode`` per-charger select was
            # retired in #277 Phase C — the new ``charge_mode``
            # selector (registered below) is the only intent knob now.
            # The stale-key cleanup at the bottom of this function
            # purges orphaned ``charger_<id>_ev_charging_mode`` rows.
            entities.append(SEMPerChargerSelect(
                coordinator,
                SelectEntityDescription(
                    key=mode_key,
                    options=list(EV_CHARGE_MODES.keys()),
                    entity_category=EntityCategory.CONFIG,
                ),
                entry, cid, "charge_mode",
                charger_cfg.get("charge_mode") or DEFAULT_EV_CHARGE_MODE,
            ))

    # Per-battery mode selects (#523). Multi-battery installs (Energy
    # Dashboard battery_power_list ≥ 2) get one ``select.sem_battery_<bid>_mode``
    # each; single-battery installs create none and keep today's behaviour.
    batt_slugs = _battery_slugs(coordinator)
    batt_modes_cfg = full_config.get("battery_modes") or []
    per_battery_keys: set[str] = set()
    for idx, bid in enumerate(batt_slugs):
        key = f"battery_{bid}_mode"
        per_battery_keys.add(key)
        cur = (
            batt_modes_cfg[idx]
            if idx < len(batt_modes_cfg) and batt_modes_cfg[idx]
            else DEFAULT_BATTERY_MODE
        )
        entities.append(SEMPerBatterySelect(
            coordinator,
            SelectEntityDescription(
                key=key,
                options=list(BATTERY_MODES.keys()),
                entity_category=EntityCategory.CONFIG,
            ),
            entry, idx, len(batt_slugs), cur,
        ))

    async_add_entities(entities)

    # Stale-key cleanup (#304): scan the registry instead of iterating
    # the current config so entries left behind by previously-removed
    # chargers are caught. The per-config loop above only knew about
    # currently-attached chargers, so a charger that was renamed or
    # removed left its ``charger_<id>_ev_charging_mode`` (and any
    # other retired per-charger select) in the registry indefinitely.
    # Mirrors the pattern in ``switch.py`` (#277 Phase C cleanup).
    try:
        registry = er.async_get(hass)
        valid_keys = {d.key for d in SELECT_TYPES} | per_charger_keys | per_battery_keys
        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.domain != "select":
                continue
            unique_id = entity_entry.unique_id or ""
            key: str | None = None
            if unique_id.startswith("sem_"):
                key = unique_id[4:]
            elif unique_id.startswith(f"{entry.entry_id}_"):
                key = unique_id[len(entry.entry_id) + 1:]
            if key and key not in valid_keys:
                _LOGGER.info(
                    "Removing stale select entity %s (key '%s' no longer registered)",
                    entity_entry.entity_id, key,
                )
                registry.async_remove(entity_entry.entity_id)
    except Exception as e:
        _LOGGER.debug("Stale select cleanup skipped: %s", e)


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

        # Persist without triggering integration reload (snapshot-keyed skip — #245)
        new_options = {**self._entry.options}
        new_options[config_key] = option
        self.coordinator._skip_options_reload = new_options
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
    """Per-charger SELECT, persisted into the charger's config dict.

    Generalised in #282 to handle BOTH ``ev_target_type`` and
    ``ev_charging_mode`` (originally only target-type — #235). The class
    derives its option set and translation key from ``config_key`` so a
    single class covers every per-charger select:

    * ``ev_target_type``  → ``kwh`` / ``soc``  (#235)
    * ``ev_charging_mode`` → auto / minpv / now / off  (#255)

    The previous hardcoded-to-target-type behaviour meant the charging-mode
    select silently inherited the kwh/soc options on every dashboard,
    locking users to whatever charging mode was in the config dict because
    they couldn't actually change it from the UI (#282 follow-up).
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
        self._attr_translation_key = config_key
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"select.sem_{description.key}"
        valid_set = self._valid_value_set()
        # Fall back to the description-declared default when initial_value is
        # garbage. options[0] is a safe choice (kwh for target_type, auto for
        # charging_mode) — better than the old hardcoded "kwh".
        if initial_value in valid_set:
            self._value = initial_value
        else:
            self._value = list(description.options or [])[0] if description.options else ""

    def _charger_cfg(self) -> dict:
        for c in self.coordinator.config.get("ev_chargers", []):
            if c.get("id") == self._charger_id:
                return c
        return {}

    def _valid_value_set(self) -> set[str]:
        """Authoritative option universe for this select's config_key."""
        if self._config_key == "ev_target_type":
            return set(EV_TARGET_TYPES.keys())
        if self._config_key == "ev_charging_mode":
            return set(EV_CHARGING_MODES.keys())
        if self._config_key == "charge_mode":
            return set(EV_CHARGE_MODES.keys())
        # Future selects: trust the description's declared options.
        return set(self.entity_description.options or [])

    @property
    def options(self) -> list[str]:
        """Options shown in the UI.

        For ``ev_target_type``: SOC % only when this charger has a
        vehicle_soc_entity configured (#235). For ``ev_charging_mode``:
        the full mode set always. For ``charge_mode`` (#277): hide
        ``solar_plus_cheap`` when no dynamic tariff is configured —
        users without a tariff should not see a ghost option that
        silently degrades. For unknown keys: pass through what the
        description declared.
        """
        if self._config_key == "ev_target_type":
            has_soc = bool(self._charger_cfg().get("vehicle_soc_entity"))
            return _target_type_options(has_soc)
        if self._config_key == "ev_charging_mode":
            return list(EV_CHARGING_MODES.keys())
        if self._config_key == "charge_mode":
            has_dyn_tariff = (
                self.coordinator.config.get("tariff_mode") == "dynamic"
            )
            return [
                m for m in EV_CHARGE_MODES.keys()
                if has_dyn_tariff or m != "solar_plus_cheap"
            ]
        return list(self.entity_description.options or [])

    @property
    def current_option(self) -> str | None:
        """Currently selected option, clamped to available options."""
        opts = self.options
        if self._value in opts:
            return self._value
        return opts[0] if opts else None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        """Return device information."""
        return self.coordinator.device_info

    async def async_select_option(self, option: str) -> None:
        """Persist the selected value into the charger config."""
        if option not in self.options:
            return
        self._value = option
        # Shared per-charger write path (#485 K2) — owns the data-side
        # fallback, missing-charger recovery (#462/#464), coordinator
        # mirror and reload-skip arming. Do NOT inline a copy here; the
        # copy-paste class already produced one missed writer (#469).
        from . import persist_per_charger_option
        persist_per_charger_option(
            self.hass, self._entry, self.coordinator,
            self._charger_id, self._config_key, option,
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Updated per-charger %s.%s to %s",
            self._charger_id, self._config_key, option,
        )


class SEMPerBatterySelect(CoordinatorEntity, SelectEntity):
    """Per-battery mode SELECT (#523), persisted positionally into the
    ``battery_modes`` list key (idx-aligned to ``battery_power_list``).

    The battery-side mirror of :class:`SEMPerChargerSelect`. Options are
    the canonical :data:`BATTERY_MODES`; ``async_select_option`` writes
    through :func:`persist_per_battery_option` (no integration reload) so
    a live mode flip takes effect on the next coordinator cycle.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: SelectEntityDescription,
        entry: SEMConfigEntry,
        idx: int,
        count: int,
        initial_value: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._idx = idx
        self._count = count
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = "battery_mode"
        self._attr_name = "Mode"
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"select.sem_{description.key}"
        opts = list(description.options or [])
        self._value = initial_value if initial_value in opts else (
            opts[0] if opts else ""
        )

    @property
    def options(self) -> list[str]:
        return list(self.entity_description.options or [])

    @property
    def current_option(self) -> str | None:
        opts = self.options
        return self._value if self._value in opts else (opts[0] if opts else None)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        return self.coordinator.device_info

    async def async_select_option(self, option: str) -> None:
        """Persist the selected battery mode (no reload)."""
        if option not in self.options:
            return
        self._value = option
        from . import persist_per_battery_option
        persist_per_battery_option(
            self.hass, self._entry, self.coordinator,
            self._idx, "battery_modes", option, self._count,
        )
        self.async_write_ha_state()
        _LOGGER.info("Updated battery %d mode to %s", self._idx, option)
