"""Number entities — the control surface, on the right devices."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberDeviceClass
from homeassistant.const import UnitOfElectricCurrent

from .const import (
    DOMAIN, KEY_AVAILABLE_CURRENT, KEY_CHARGER_MAX_CURRENT,
    KEY_CHARGER_MIN_CURRENT, KEY_PHASE_SWITCH_CURRENT,
)
from .entity import ZaptecSimEntity


async def async_setup_entry(hass, entry, async_add_entities):
    state = hass.data[DOMAIN][entry.entry_id]
    ents = []
    if entry.data.get("expose_charger_current", True):
        # CHARGER — this is SEM's throttle.
        ents.append(ChargerMaxCurrent(state, entry))
    ents.append(ChargerMinCurrent(state, entry))
    async_add_entities(ents + [
        # INSTALLATION — the grid guard and the phase threshold. SEM must
        # never write either: available_current constrains every charger on
        # the site, and the phase threshold is a physical reconfiguration.
        AvailableCurrent(state, entry),
        PhaseSwitchCurrent(state, entry),
    ])


class _CurrentNumber(ZaptecSimEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_max_value = 32
    _attr_native_step = 1


class ChargerMaxCurrent(_CurrentNumber):
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_CHARGER_MAX_CURRENT, on_charger=True)

    @property
    def native_value(self): return self._state.charger_max_current

    async def async_set_native_value(self, value: float) -> None:
        # The soft pause: 0 stops, raising resumes, no command in between.
        self._state.set_charger_max_current(value)


class ChargerMinCurrent(_CurrentNumber):
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_CHARGER_MIN_CURRENT, on_charger=True)

    @property
    def native_value(self): return self._state.charger_min_current

    async def async_set_native_value(self, value: float) -> None:
        self._state.charger_min_current = float(value); self._state.notify()


class AvailableCurrent(_CurrentNumber):
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_AVAILABLE_CURRENT, on_charger=False)

    @property
    def native_value(self): return self._state.available_current

    async def async_set_native_value(self, value: float) -> None:
        self._state.available_current = float(value); self._state.notify()


class PhaseSwitchCurrent(_CurrentNumber):
    """EVCC's Go2 phase path: a CURRENT THRESHOLD, not a phase command.
    32 A → 1-phase, 0 A → 3-phase. #804's stop→switch→settle sequencer had
    nothing to talk to on this brand precisely because of this shape."""
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_PHASE_SWITCH_CURRENT, on_charger=False)

    @property
    def native_value(self): return self._state.phase_switch_current

    async def async_set_native_value(self, value: float) -> None:
        self._state.phase_switch_current = float(value); self._state.notify()
