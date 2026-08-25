"""Zaptec simulator (#804) — a stand-in for hardware SEM supports and lacks."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PHASE_SWITCH_1P_A, PHASE_SWITCH_3P_A
from .coordinator import ZaptecSimState

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["number", "sensor", "binary_sensor", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    state = ZaptecSimState()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = state
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def _state() -> ZaptecSimState:
        return next(iter(hass.data[DOMAIN].values()))

    async def plug_in(call: ServiceCall) -> None:
        s = _state(); s.cable_connected = True; s.notify()

    async def unplug(call: ServiceCall) -> None:
        s = _state(); s.cable_connected = False; s.notify()

    async def hard_stop(call: ServiceCall) -> None:
        _state().hard_stop()

    async def set_phases(call: ServiceCall) -> None:
        s = _state()
        s.phase_switch_current = (
            PHASE_SWITCH_1P_A if int(call.data["phases"]) == 1
            else PHASE_SWITCH_3P_A)
        s.notify()

    hass.services.async_register(DOMAIN, "plug_in", plug_in)
    hass.services.async_register(DOMAIN, "unplug", unplug)
    hass.services.async_register(DOMAIN, "hard_stop", hard_stop)
    hass.services.async_register(
        DOMAIN, "set_phases", set_phases,
        schema=vol.Schema({vol.Required("phases"): vol.In([1, 3])}))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
