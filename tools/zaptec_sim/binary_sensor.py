"""Cable + charging state."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity,
)

from .const import DOMAIN, KEY_CABLE_CONNECTED, KEY_CHARGING
from .entity import ZaptecSimEntity, unmapped_fixture


async def async_setup_entry(hass, entry, async_add_entities):
    if unmapped_fixture(entry):
        return          # (#915) no cable/charging state = nothing to map
    state = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CableConnected(state, entry), Charging(state, entry)])


class CableConnected(ZaptecSimEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_CABLE_CONNECTED, on_charger=True)

    @property
    def is_on(self): return self._state.cable_connected


class Charging(ZaptecSimEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_CHARGING, on_charger=True)

    @property
    def is_on(self): return self._state.charging
