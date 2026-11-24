"""(#1381, charger owner S7) The load manager never writes to a charger.

The map suspected the load manager writes 0 A to a charger; the code
refutes it for charger ROWS (#461-peak). What was left open: a row that is
not a charger row but names a charger's own entity (an old discovered
plug pointing at the charger's stop switch, #748) could still reach a
charger through the load manager's write seam. ``_send`` now refuses any
write to an entity (or a charger service) a registered charger owns —
the charger owner is the only one that writes to a charger.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)


def _lm():
    lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
    lm._devices = {
        "load_device_ev_charger": {
            "device_type": "ev_charger", "control_type": "current",
            "switch_entity": "number.wb_current", "charger_id": "ev_charger",
            "start_stop_entity": "switch.wb_enable",
            "charger_service": "keba.set_current", "priority": 3},
        # an old row that names the charger's own switch
        "load_device_ghost": {
            "device_type": "switch", "control_type": "switch",
            "control": {"type": "switch", "entity": "switch.wb_enable"},
            "switch_entity": "switch.wb_enable", "priority": 9,
            "is_critical": False},
    }
    lm.hass = MagicMock()
    lm.hass.states.get = MagicMock(
        return_value=SimpleNamespace(state="on", attributes={}))
    lm.hass.services.async_call = AsyncMock()
    lm._save_device_configuration = AsyncMock()
    lm._trigger_callbacks = MagicMock()
    lm.observer_mode = False
    lm._observer_mode = False
    return lm


@pytest.mark.asyncio
async def test_a_row_naming_a_charger_entity_is_never_written():
    lm = _lm()
    ok = await lm._send("load_device_ghost", "switch", "turn_off",
                        {"entity_id": "switch.wb_enable"})
    assert ok is False
    lm.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_a_charger_service_is_never_called_from_here():
    lm = _lm()
    ok = await lm._send("load_device_ghost", "keba", "set_current", {"current": 0})
    assert ok is False
    lm.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_an_ordinary_load_is_still_written():
    lm = _lm()
    lm._devices["load_device_plug"] = {"device_type": "switch",
                                       "switch_entity": "switch.dryer"}
    ok = await lm._send("load_device_plug", "switch", "turn_off",
                        {"entity_id": "switch.dryer"})
    assert ok is True
    lm.hass.services.async_call.assert_awaited_once()
