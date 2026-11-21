"""The resume button — the ONLY way out of a hard stop (EVCC's
CmdResumeCharging). Deliberately does nothing when merely soft-paused, which
is the distinction #804 turns on.

(#1399) Like the real integration (``ZaptecButton.available`` →
``Charger.is_command_valid``), the button is available only while the box is
paused by a final stop; otherwise HA skips a press on it without a word."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, KEY_RESUME
from .entity import ZaptecSimEntity, unmapped_fixture


async def async_setup_entry(hass, entry, async_add_entities):
    if unmapped_fixture(entry):
        return          # (#915) a resume button is an identity key
    async_add_entities([ResumeCharging(hass.data[DOMAIN][entry.entry_id], entry)])


class ResumeCharging(ZaptecSimEntity, ButtonEntity):
    def __init__(self, state, entry):
        super().__init__(state, entry, KEY_RESUME, on_charger=True)

    @property
    def available(self) -> bool:
        return bool(self._state.hard_stopped and self._state.cable_connected)

    async def async_press(self) -> None:
        self._state.resume()
