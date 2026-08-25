"""The resume button — the ONLY way out of a hard stop (EVCC's
CmdResumeCharging). Deliberately does nothing when merely soft-paused, which
is the distinction #804 turns on."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, KEY_RESUME
from .entity import ZaptecSimEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ResumeCharging(hass.data[DOMAIN][entry.entry_id], entry)])


class ResumeCharging(ZaptecSimEntity, ButtonEntity):
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_RESUME, on_charger=True)

    async def async_press(self) -> None:
        self._state.resume()
