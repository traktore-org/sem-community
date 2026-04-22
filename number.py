"""SEM Solar Energy Management number entities for settings control."""
import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
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
    # EV Charging
    NumberEntityDescription(
        key="daily_ev_target",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        native_min_value=0,
        native_max_value=100,
        native_step=0.5,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="ev_km_per_kwh",
        native_unit_of_measurement="km/kWh",
        native_min_value=3,
        native_max_value=10,
        native_step=0.5,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
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
    # EV Charging Parameters
    NumberEntityDescription(
        key="ev_night_initial_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=6,
        native_max_value=32,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="ev_minimum_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=6,
        native_max_value=16,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="ev_stall_cooldown",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=30,
        native_max_value=300,
        native_step=10,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key="ev_phases",
        native_min_value=1,
        native_max_value=3,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    # Tariff rates (previously only in OptionsFlow)
    NumberEntityDescription(
        key="electricity_import_rate",
        native_unit_of_measurement="CHF/kWh",  # CHF replaced dynamically with HA currency
        native_min_value=0.01,
        native_max_value=1.0,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="electricity_export_rate",
        native_unit_of_measurement="CHF/kWh",  # CHF replaced dynamically with HA currency
        native_min_value=0.01,
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
        native_max_value=1.0,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="expensive_price_threshold",
        native_unit_of_measurement="CHF/kWh",
        native_min_value=0.0,
        native_max_value=1.0,
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
    NumberEntityDescription(
        key="system_install_year",
        native_min_value=2015,
        native_max_value=2035.12,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
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
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up EMS Solar Optimizer number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        EMSSolarNumber(coordinator, description, entry)
        for description in NUMBER_TYPES
    ]

    async_add_entities(entities)


class EMSSolarNumber(CoordinatorEntity, NumberEntity):
    """EMS Solar Optimizer number entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    # All number entities are enabled by default
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
        # Keep entry_id-based unique_id for backward compatibility with existing entities
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
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
            DEFAULT_EV_NIGHT_INITIAL_CURRENT,
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
            "battery_assist_max_power": DEFAULT_BATTERY_ASSIST_MAX_POWER,
            "regulation_offset": DEFAULT_REGULATION_OFFSET,
            "demand_charge_rate": DEFAULT_DEMAND_CHARGE_RATE,
            "cheap_price_threshold": DEFAULT_CHEAP_PRICE_THRESHOLD,
            "expensive_price_threshold": DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
            "heat_pump_boost_offset": DEFAULT_HEAT_PUMP_BOOST_OFFSET,
            "hot_water_max_temperature": DEFAULT_HOT_WATER_MAX_TEMP,
            "system_size_kwp": DEFAULT_SYSTEM_SIZE_KWP,
            "ev_night_initial_current": DEFAULT_EV_NIGHT_INITIAL_CURRENT,
            "ev_minimum_current": DEFAULT_EV_MIN_CURRENT,
            "ev_stall_cooldown": DEFAULT_EV_STALL_COOLDOWN,
            "ev_phases": 3,
            "ev_km_per_kwh": 5.5,
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

        # Update the config entry options
        new_options = {**self._entry.options}
        new_options[config_key] = value

        self.hass.config_entries.async_update_entry(
            self._entry,
            options=new_options
        )

        # Update coordinator config
        await self.coordinator.async_update_config({config_key: value})

        # Force coordinator refresh
        await self.coordinator.async_request_refresh()

        _LOGGER.info(f"Updated {self.entity_description.key} to {value}")