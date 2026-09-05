"""Readings."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower

from .const import (
    DOMAIN, KEY_CHARGE_POWER, KEY_INSTALL_POWER, KEY_OPERATION_MODE,
    KEY_SESSION_ENERGY,
)
from .entity import ZaptecSimEntity, unmapped_fixture


async def async_setup_entry(hass, entry, async_add_entities):
    state = hass.data[DOMAIN][entry.entry_id]
    if unmapped_fixture(entry):
        # (#915) A site total on the INSTALLATION device. A charger SEM
        # cannot measure is one it must not steer, so without this the offer
        # correctly declines — which is the other half of the fixture.
        async_add_entities([InstallationPower(state, entry)])
        return
    async_add_entities([
        ChargePower(state, entry), SessionEnergy(state, entry),
        OperationMode(state, entry),
    ])


class ChargePower(ZaptecSimEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_CHARGE_POWER, on_charger=True)

    @property
    def native_value(self): return self._state.power_w


class InstallationPower(ZaptecSimEntity, SensorEntity):
    """(#915) The site's own power reading, on the installation device."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_INSTALL_POWER, on_charger=False)

    @property
    def native_value(self): return self._state.power_w


class SessionEnergy(ZaptecSimEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_SESSION_ENERGY, on_charger=True)

    @property
    def native_value(self): return round(self._state.session_energy, 3)


class OperationMode(ZaptecSimEntity, SensorEntity):
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_OPERATION_MODE, on_charger=True)

    @property
    def native_value(self): return self._state.operation_mode
