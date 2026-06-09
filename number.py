"""SEM Solar Energy Management number entities for settings control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    UnitOfTime,
    PERCENTAGE,
)

from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates

NUMBER_TYPES = [
    # Delta Thresholds
    NumberEntityDescription(
        key="update_interval",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=10,
        native_max_value=60,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="power_delta",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=50,
        native_max_value=3000,
        native_step=50,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="current_delta",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=1,
        native_max_value=10,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="soc_delta",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=1,
        native_max_value=20,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    # Battery Management
    NumberEntityDescription(
        # 4-zone Zone 1 floor: below this, all solar → battery, EV blocked.
        # Range widened from 50–100 (legacy 3-zone meaning) to 5–60 to match
        # the 4-zone semantics documented in docs/ARCHITECTURE.md.
        key="battery_priority_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=5,
        native_max_value=60,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        # Hard stop: SOC below this halts EV charging entirely (safety).
        key="battery_minimum_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=5,
        native_max_value=50,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="battery_resume_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=30,
        native_max_value=80,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    # SOC Zone Thresholds
    NumberEntityDescription(
        key="battery_buffer_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=50,
        native_max_value=95,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="battery_auto_start_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=70,
        native_max_value=100,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="battery_assist_floor_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=30,
        native_max_value=80,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        native_min_value=5,
        native_max_value=100,
        native_step=5,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="battery_max_discharge_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=500,
        native_max_value=10000,
        native_step=500,
        mode=NumberMode.SLIDER,
    ),
    # Solar & Power
    NumberEntityDescription(
        key="minimum_solar_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=5000,
        native_step=100,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="maximum_grid_import",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=2000,
        native_step=100,
        mode=NumberMode.SLIDER,
    ),
    # EV charge-target / consumption settings (daily_ev_target[_max], ev_target_soc[_max],
    # ev_kwh_per_100km) are PER-CHARGER only (#255) — global duplicates removed; see the
    # per-charger descriptions in async_setup_entry. Stale registry entities are
    # auto-removed by _cleanup_stale_entities; values were seeded per-charger by the v3→v4
    # migration so nothing resets.
    NumberEntityDescription(
        key="public_charging_rate",
        native_unit_of_measurement="CHF/kWh",
        native_min_value=0,
        native_max_value=2,
        native_step=0.01,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="battery_assist_max_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=1000,
        native_max_value=10000,
        native_step=500,
        mode=NumberMode.SLIDER,
    ),
    # EV Charging Parameters — global night_initial_current + minimum_current removed as
    # per-charger duplicates (#255); ev_stall_cooldown stays a global tuning constant.
    NumberEntityDescription(
        key="ev_stall_cooldown",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=30,
        native_max_value=300,
        native_step=10,
        mode=NumberMode.SLIDER,
    ),
    # ev_phases is PER-CHARGER only (#255) — it's a charger hardware property. Global
    # entity removed (seeded per-charger by the v3→v4 migration; stale entity auto-removed).
    # Tariff rates (previously only in OptionsFlow)
    NumberEntityDescription(
        key="electricity_import_rate",
        native_unit_of_measurement="CHF/kWh",  # CHF replaced dynamically with HA currency
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="electricity_export_rate",
        native_unit_of_measurement="CHF/kWh",  # CHF replaced dynamically with HA currency
        native_min_value=0.0,
        native_max_value=0.50,
        native_step=0.005,
        mode=NumberMode.BOX,
    ),
    # Phase 0: Surplus controller
    NumberEntityDescription(
        key="regulation_offset",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=500,
        native_step=10,
        mode=NumberMode.SLIDER,
    ),
    # Phase 1: Demand charge
    NumberEntityDescription(
        key="demand_charge_rate",
        native_unit_of_measurement="CHF/kW/Mt",
        native_min_value=0.0,
        native_max_value=20.0,
        native_step=0.5,
        mode=NumberMode.BOX,
    ),
    # Phase 1: Price thresholds
    NumberEntityDescription(
        key="cheap_price_threshold",
        native_unit_of_measurement="CHF/kWh",
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="expensive_price_threshold",
        native_unit_of_measurement="CHF/kWh",
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
    # Phase 2: Heat pump
    NumberEntityDescription(
        key="heat_pump_boost_offset",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=0,
        native_max_value=5,
        native_step=0.5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="hot_water_max_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=40,
        native_max_value=80,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    # Hot water solar boost + Legionella prevention (#92)
    NumberEntityDescription(
        key="hot_water_solar_target",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=40,
        native_max_value=80,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="legionella_target_temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=60,
        native_max_value=80,
        native_step=5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="legionella_interval_hours",
        native_unit_of_measurement="h",
        native_min_value=24,
        native_max_value=168,
        native_step=24,
        mode=NumberMode.SLIDER,
    ),
    # Phase 5: PV system
    NumberEntityDescription(
        key="system_size_kwp",
        native_unit_of_measurement="kWp",
        native_min_value=1,
        native_max_value=100,
        native_step=0.5,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="system_investment_cost",
        native_min_value=0,
        native_max_value=200000,
        native_step=100,
        mode=NumberMode.BOX,
    ),
    # system_install_year removed — auto-detected from recorder statistics
    # Night charging schedule
    NumberEntityDescription(
        key="night_earliest_start",
        native_unit_of_measurement="h",
        native_min_value=18.0,
        native_max_value=23.0,
        native_step=0.5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="night_latest_end",
        native_unit_of_measurement="h",
        native_min_value=5.0,
        native_max_value=9.0,
        native_step=0.5,
        mode=NumberMode.SLIDER,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up EMS Solar Optimizer number entities."""
    coordinator: SEMCoordinator = entry.runtime_data

    entities = [
        SEMNumberEntity(coordinator, description, entry)
        for description in NUMBER_TYPES
    ]

    # Per-charger number entities (#193)
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    per_charger_descriptions = []
    if len(ev_chargers) >= 1:
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id", "ev_charger")
            cname = charger_cfg.get("name", "EV Charger")
            for base_desc, config_key, default_val in [
                (NumberEntityDescription(
                    key=f"charger_{cid}_daily_ev_target",
                    name=f"{cname} Night Target",
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    # #355: max raised 100 → 200 so the slider has drag room
                    # when the user (or default) has Solar Max sitting at the
                    # rail. Pre-fix a range slider with Min + Max both at 100
                    # had zero space between the handles and could not be
                    # dragged. Covers any practical EV battery size.
                    native_min_value=0, native_max_value=200, native_step=0.5,
                    mode=NumberMode.SLIDER,
                ), "daily_ev_target", full_config.get("daily_ev_target", 10)),
                # (#441) Renamed from ``night_initial_current`` to
                # ``initial_current`` (display "Vehicle Start Amps") to
                # group with the new per-vehicle Min Amps and decouple
                # from the now-misleading "night" prefix — the value is
                # the session-start ramp current, used at any time the
                # session begins, not strictly tied to nighttime.
                (NumberEntityDescription(
                    key=f"charger_{cid}_initial_current",
                    name=f"{cname} Vehicle Start Amps",
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    native_min_value=6, native_max_value=32, native_step=1,
                    mode=NumberMode.SLIDER,
                    icon="mdi:car-clock",
                ), "initial_current", full_config.get("initial_current", 10)),
                (NumberEntityDescription(
                    key=f"charger_{cid}_minimum_current",
                    name=f"{cname} Min Amps",
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    native_min_value=6, native_max_value=16, native_step=1,
                    mode=NumberMode.SLIDER,
                ), "ev_min_current", full_config.get("ev_min_current", 6)),
                # (#440 ADR 0010 #3) per-vehicle handshake-floor minimum.
                # Effective floor = max(ev_min_current, vehicle_min_current).
                # Default seeds to the charger's ev_min_current so the
                # entity is never empty in the UI; users with cars that
                # need > 6 A (e.g. Renault Zoe handshake) bump this.
                (NumberEntityDescription(
                    key=f"charger_{cid}_vehicle_min_current",
                    name=f"{cname} Vehicle Min Amps",
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    native_min_value=6, native_max_value=32, native_step=1,
                    mode=NumberMode.SLIDER,
                    icon="mdi:car-electric",
                ), "vehicle_min_current",
                    charger_cfg.get("vehicle_min_current") or
                    full_config.get("ev_min_current", 6)),
                (NumberEntityDescription(
                    key=f"charger_{cid}_target_soc",
                    name=f"{cname} Target SOC",
                    native_unit_of_measurement=PERCENTAGE,
                    native_min_value=50, native_max_value=100, native_step=5,
                    mode=NumberMode.SLIDER,
                    icon="mdi:battery-charging-80",
                ), "ev_target_soc", full_config.get("ev_target_soc", 80)),
                # Solar ceiling (Max) = the Max handle of the EV-card range slider;
                # defaults to full (charge freely from sun) until the user caps it (#245).
                (NumberEntityDescription(
                    key=f"charger_{cid}_daily_ev_target_max",
                    name=f"{cname} Solar Max",
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    # #355: max raised 100 → 200 — same reason as the Min slider
                    # above. With both defaulting to 100 (full charge intent),
                    # the range slider had zero drag room.
                    native_min_value=0, native_max_value=200, native_step=0.5,
                    mode=NumberMode.SLIDER,
                    icon="mdi:solar-power-variant",
                ), "daily_ev_target_max",
                    charger_cfg.get("daily_ev_target_max", 100)),
                (NumberEntityDescription(
                    key=f"charger_{cid}_target_soc_max",
                    name=f"{cname} Solar Max SOC",
                    native_unit_of_measurement=PERCENTAGE,
                    native_min_value=50, native_max_value=100, native_step=5,
                    mode=NumberMode.SLIDER,
                    icon="mdi:battery-charging-high",
                ), "ev_target_soc_max",
                    charger_cfg.get("ev_target_soc_max", 100)),
                # Car battery capacity (kWh) — feeds the SOC/range math; editable
                # from the EV card so users don't have to open the options flow (#245).
                (NumberEntityDescription(
                    key=f"charger_{cid}_ev_battery_capacity_kwh",
                    name=f"{cname} Battery Capacity",
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    native_min_value=10, native_max_value=120, native_step=1,
                    mode=NumberMode.BOX,
                    icon="mdi:car-battery",
                    entity_category=EntityCategory.CONFIG,
                ), "ev_battery_capacity_kwh",
                    charger_cfg.get("ev_battery_capacity_kwh",
                                    full_config.get("ev_battery_capacity_kwh", 40))),
                # Per-car consumption (kWh/100km) — feeds the driving-range estimate.
                # Individual per car, hence per charger (one car per charger). (#245)
                (NumberEntityDescription(
                    key=f"charger_{cid}_ev_kwh_per_100km",
                    name=f"{cname} Consumption",
                    native_unit_of_measurement="kWh/100km",
                    native_min_value=8, native_max_value=50, native_step=0.5,
                    mode=NumberMode.BOX,
                    icon="mdi:map-marker-distance",
                    entity_category=EntityCategory.CONFIG,
                ), "ev_kwh_per_100km",
                    charger_cfg.get("ev_kwh_per_100km",
                                    full_config.get("ev_kwh_per_100km", 18))),
                # Per-charger phase count (#255) — a charger hardware property (1 or 3).
                (NumberEntityDescription(
                    key=f"charger_{cid}_ev_phases",
                    name=f"{cname} Phases",
                    native_min_value=1, native_max_value=3, native_step=1,
                    mode=NumberMode.SLIDER,
                    entity_category=EntityCategory.CONFIG,
                ), "ev_phases",
                    charger_cfg.get("ev_phases", full_config.get("ev_phases", 3))),
            ]:
                per_charger_descriptions.append(base_desc)
                entities.append(SEMPerChargerNumber(
                    coordinator, base_desc, entry, cid, config_key,
                    charger_cfg.get(config_key, default_val),
                ))

    if per_charger_descriptions:
        _LOGGER.info(
            "Created %d per-charger number entities for %d charger(s)",
            len(per_charger_descriptions), len(ev_chargers),
        )

    async_add_entities(entities)

    # Fix entity_ids from pre-translation installs and clean up stale entities
    all_descriptions = list(NUMBER_TYPES) + per_charger_descriptions
    _fix_entity_ids(hass, entry, all_descriptions, "number")
    _cleanup_stale_entities(hass, entry, all_descriptions, "number")


def _fix_entity_ids(hass, entry, descriptions, platform):
    """Fix entity_ids from pre-translation installs."""
    try:
        registry = er.async_get(hass)
        expected = {}
        for desc in descriptions:
            # Numbers use {entry_id}_{key} unique_id, with legacy map
            _LEGACY = {"battery_capacity": "battery_capacity_kwh"}
            uid_key = _LEGACY.get(desc.key, desc.key)
            uid = f"{entry.entry_id}_{uid_key}"
            expected[uid] = f"{platform}.sem_{desc.key}"

        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.domain != platform:
                continue
            uid = entity_entry.unique_id or ""
            if uid in expected:
                correct_eid = expected[uid]
                if entity_entry.entity_id != correct_eid:
                    existing = registry.async_get(correct_eid)
                    if existing is None:
                        registry.async_update_entity(
                            entity_entry.entity_id, new_entity_id=correct_eid,
                        )
                        _LOGGER.info("Fixed entity_id: %s → %s", entity_entry.entity_id, correct_eid)
    except Exception as e:
        _LOGGER.debug("Entity ID fix skipped: %s", e)


def _cleanup_stale_entities(hass, entry, descriptions, platform):
    """Remove orphaned entities from previous SEM versions."""
    try:
        registry = er.async_get(hass)
        # Valid keys: both description keys AND legacy UID mapped keys
        valid_keys = {d.key for d in descriptions}
        _LEGACY_UID_MAP = {"battery_capacity": "battery_capacity_kwh"}
        valid_keys.update(_LEGACY_UID_MAP.values())

        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.domain != platform:
                continue
            unique_id = entity_entry.unique_id or ""
            key = unique_id.replace(f"{entry.entry_id}_", "", 1)
            if key and key not in valid_keys:
                _LOGGER.info("Removing stale entity %s (key '%s' removed)", entity_entry.entity_id, key)
                registry.async_remove(entity_entry.entity_id)
    except Exception as e:
        _LOGGER.debug("Stale entity cleanup skipped: %s", e)


class SEMNumberEntity(CoordinatorEntity, NumberEntity):
    """EMS Solar Optimizer number entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    # Solar-ceiling (Max) entities are enabled: they are the Max handle of the
    # dual-handle range slider on the EV card (#245), and default to full
    # (100% / 100 kWh) = "charge freely from sun" until the user caps surplus.
    DISABLED_BY_DEFAULT: set = set()

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: NumberEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        # Backward-compatible unique_id: old versions used the config key
        # (e.g. battery_capacity_kwh), not the description key (battery_capacity).
        _LEGACY_UID_MAP = {
            "battery_capacity": "battery_capacity_kwh",
        }
        uid_key = _LEGACY_UID_MAP.get(description.key, description.key)
        self._attr_unique_id = f"{entry.entry_id}_{uid_key}"
        self._attr_translation_key = description.key
        self._attr_suggested_object_id = f"sem_{description.key}"
        # Force stable entity ID regardless of HA language
        self.entity_id = f"number.sem_{description.key}"
        self._entry = entry

        if description.key in self.DISABLED_BY_DEFAULT:
            self._attr_entity_registry_enabled_default = False

        # Use HA configured currency for monetary number entities
        uom = description.native_unit_of_measurement or ""
        if "CHF" in uom:
            currency = coordinator.hass.config.currency
            self._attr_native_unit_of_measurement = uom.replace("CHF", currency)

        # Set initial value from config.
        # Some entity keys differ from config keys for dashboard compatibility.
        _CONFIG_KEY_MAP = {
            "battery_capacity": "battery_capacity_kwh",
            "ev_minimum_current": "ev_min_current",
        }
        config = {**entry.data, **entry.options}
        config_key = _CONFIG_KEY_MAP.get(description.key, description.key)
        # Null-safe: config may store None explicitly, which makes the
        # entity unavailable.  Fall through to the default in that case.
        # Note: don't use `or` — 0 is a valid value (e.g. max_grid_import=0).
        value = config.get(config_key)
        if value is None:
            value = config.get(description.key)
        if value is None:
            value = self._get_default_value(description.key)
        self._attr_native_value = value

    def _get_default_value(self, key: str) -> float:
        """Get default value for a setting."""
        from .const import (
            DEFAULT_UPDATE_INTERVAL,
            DEFAULT_POWER_DELTA,
            DEFAULT_CURRENT_DELTA,
            DEFAULT_SOC_DELTA,
            DEFAULT_BATTERY_PRIORITY_SOC,
            DEFAULT_BATTERY_MINIMUM_SOC,
            DEFAULT_BATTERY_RESUME_SOC,
            DEFAULT_MIN_SOLAR_POWER,
            DEFAULT_MAX_GRID_IMPORT,
            DEFAULT_DAILY_EV_TARGET,
            DEFAULT_BATTERY_ASSIST_MAX_POWER,
            DEFAULT_REGULATION_OFFSET,
            DEFAULT_DEMAND_CHARGE_RATE,
            DEFAULT_CHEAP_PRICE_THRESHOLD,
            DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
            DEFAULT_HEAT_PUMP_BOOST_OFFSET,
            DEFAULT_HOT_WATER_MAX_TEMP,
            DEFAULT_SYSTEM_SIZE_KWP,
            DEFAULT_EV_INITIAL_CURRENT,
            DEFAULT_EV_MIN_CURRENT,
            DEFAULT_EV_STALL_COOLDOWN,
            DEFAULT_BATTERY_CAPACITY_KWH,
        )

        defaults = {
            "update_interval": DEFAULT_UPDATE_INTERVAL,
            "power_delta": DEFAULT_POWER_DELTA,
            "current_delta": DEFAULT_CURRENT_DELTA,
            "soc_delta": DEFAULT_SOC_DELTA,
            "battery_priority_soc": DEFAULT_BATTERY_PRIORITY_SOC,
            "battery_minimum_soc": DEFAULT_BATTERY_MINIMUM_SOC,
            "battery_resume_soc": DEFAULT_BATTERY_RESUME_SOC,
            "minimum_solar_power": DEFAULT_MIN_SOLAR_POWER,
            "maximum_grid_import": DEFAULT_MAX_GRID_IMPORT,
            "daily_ev_target": DEFAULT_DAILY_EV_TARGET,
            # Ceiling defaults to full (charge freely from sun until capped) (#245)
            "daily_ev_target_max": 100,
            "ev_target_soc_max": 100,
            "battery_assist_max_power": DEFAULT_BATTERY_ASSIST_MAX_POWER,
            "regulation_offset": DEFAULT_REGULATION_OFFSET,
            "demand_charge_rate": DEFAULT_DEMAND_CHARGE_RATE,
            "cheap_price_threshold": DEFAULT_CHEAP_PRICE_THRESHOLD,
            "expensive_price_threshold": DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
            "heat_pump_boost_offset": DEFAULT_HEAT_PUMP_BOOST_OFFSET,
            "hot_water_max_temperature": DEFAULT_HOT_WATER_MAX_TEMP,
            "hot_water_solar_target": 50.0,
            "legionella_target_temp": 65.0,
            "legionella_interval_hours": 72,
            "system_size_kwp": DEFAULT_SYSTEM_SIZE_KWP,
            "initial_current": DEFAULT_EV_INITIAL_CURRENT,
            "ev_minimum_current": DEFAULT_EV_MIN_CURRENT,
            "ev_stall_cooldown": DEFAULT_EV_STALL_COOLDOWN,
            "ev_phases": 3,
            "ev_kwh_per_100km": 18,
            "public_charging_rate": 0.55,
            "electricity_import_rate": 0.3387,
            "electricity_export_rate": 0.075,
            "battery_buffer_soc": 70,
            "battery_auto_start_soc": 90,
            "battery_assist_floor_soc": 60,
            "battery_capacity": DEFAULT_BATTERY_CAPACITY_KWH,
            "night_earliest_start": 20.5,
            "night_latest_end": 7.0,
            "battery_max_discharge_power": 5000,
        }

        return defaults.get(key, 0)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        """Return device information."""
        return self.coordinator.device_info

    async def async_set_native_value(self, value: float) -> None:
        """Update the setting value."""
        self._attr_native_value = value

        # Map entity key back to config key if they differ
        _CONFIG_KEY_MAP = {
            "battery_capacity": "battery_capacity_kwh",
            "ev_minimum_current": "ev_min_current",
        }
        config_key = _CONFIG_KEY_MAP.get(self.entity_description.key, self.entity_description.key)

        # Update coordinator config (immediate, in-memory)
        await self.coordinator.async_update_config({config_key: value})

        # Persist to config entry options WITHOUT triggering integration reload.
        # async_update_entry fires the update listener which normally calls
        # async_reload — destroying all 255 entities for ~1s and causing card
        # flashes. The _skip_options_reload flag tells the listener to skip.
        new_options = {**self._entry.options}
        new_options[config_key] = value
        # Skip reload only for THIS exact payload (snapshot) — see async_update_options.
        self.coordinator._skip_options_reload = new_options
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=new_options
        )

        # Publish state immediately — no full coordinator refresh needed.
        # The entity already has the correct value via _attr_native_value.
        # Derived recalculations (charging strategy) happen on the next 10s cycle.
        self.async_write_ha_state()

        _LOGGER.info(f"Updated {self.entity_description.key} to {value}")


class SEMPerChargerNumber(CoordinatorEntity, NumberEntity):
    """Per-charger number entity that stores its value in the charger's config dict (#193)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: NumberEntityDescription,
        entry: ConfigEntry,
        charger_id: str,
        config_key: str,
        initial_value: float,
    ) -> None:
        """Initialize per-charger number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_suggested_object_id = f"sem_{description.key}"
        self.entity_id = f"number.sem_{description.key}"
        self._entry = entry
        self._charger_id = charger_id
        self._config_key = config_key
        self._attr_native_value = initial_value

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        """Return device information."""
        return self.coordinator.device_info

    async def async_set_native_value(self, value: float) -> None:
        """Update the per-charger setting value."""
        self._attr_native_value = value

        # Keep coordinator's in-memory config in sync immediately
        new_options = {**self._entry.options}
        # Copy each charger dict — in-place mutation leaves entry.options unchanged,
        # so async_update_entry skips persisting and the value reverts on restart (#245).
        #
        # Fall back to entry.data.ev_chargers when entry.options doesn't have
        # the key yet (fresh install / never edited via the Config card). Without
        # the fallback this writes ``new_options["ev_chargers"] = []`` and the
        # merge ``{**data, **options}`` on next reload overrides data's chargers
        # with the empty list — every charger disappears. Same latent foot-gun
        # as in select.py:SEMPerChargerSelect.async_select_option.
        source_chargers = (
            new_options.get("ev_chargers")
            or (self._entry.data or {}).get("ev_chargers")
            or []
        )
        ev_chargers = [dict(c) for c in source_chargers]
        for charger in ev_chargers:
            if charger.get("id") == self._charger_id:
                charger[self._config_key] = value
                break
        new_options["ev_chargers"] = ev_chargers

        if hasattr(self.coordinator, "config") and isinstance(self.coordinator.config, dict):
            self.coordinator.config.update({**self._entry.data, **new_options})

        # Persist without triggering integration reload (snapshot-keyed skip)
        self.coordinator._skip_options_reload = new_options
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=new_options,
        )

        self.async_write_ha_state()
        _LOGGER.info(
            "Updated per-charger %s.%s to %s",
            self._charger_id, self._config_key, value,
        )