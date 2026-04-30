"""SEM Solar Energy Management switches."""
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SEMCoordinator

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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    switches = [
        SEMSolarSwitch(coordinator, description, entry.entry_id)
        for description in SWITCH_TYPES
    ]

    async_add_entities(switches)


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
            self._is_on = True  # Default to ON (will be restored from last state if available)
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
            _LOGGER.info(f"Restored {self.entity_description.key} state to: {'ON' if self._is_on else 'OFF'}")
        else:
            _LOGGER.info(f"No previous state for {self.entity_description.key}, using default: {'ON' if self._is_on else 'OFF'}")

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        _LOGGER.info(f"Turning on {self.entity_description.key}")
        self._is_on = True

        try:
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.warning(f"Failed to refresh coordinator when turning on {self.entity_description.key}: {e}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        _LOGGER.info(f"Turning off {self.entity_description.key}")
        self._is_on = False

        try:
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.warning(f"Failed to refresh coordinator when turning off {self.entity_description.key}: {e}")
