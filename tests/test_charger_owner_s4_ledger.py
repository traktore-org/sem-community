"""(#1381, charger owner S4) The ledger: every write SEM sends to a charger,
with who asked and the entity's state just before.

Before this, four private records (the park record, the load manager's
``_pre_shed_current``, the pause timer, nothing at all for the guard) each
knew a little of what SEM had changed. The ledger sits at the one hardware
seam (``ControllableDevice.send``, #855), so no write can miss it. It only
records: nothing is sent that was not sent before.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import ControllableDevice


class _Dev(ControllableDevice):
    async def activate(self, w):
        return 0.0

    async def deactivate(self):
        return None

    async def adjust_power(self, w):
        return 0.0


def _dev(states=None, *, raise_on_states=False):
    hass = MagicMock()
    if raise_on_states:
        hass.states.get = MagicMock(side_effect=RuntimeError("boom"))
    else:
        hass.states.get = lambda e: (SimpleNamespace(state=(states or {})[e])
                                     if e in (states or {}) else None)
    hass.services.async_call = AsyncMock()
    dev = _Dev.__new__(_Dev)
    dev.hass = hass
    dev.device_id = dev.name = "wb"
    dev.observer_mode = False
    dev.external_yield = False
    return dev


@pytest.mark.asyncio
async def test_a_write_is_recorded_with_its_prior_state_and_who_asked():
    dev = _dev({"number.wb_current": "16"})
    dev.command_source, dev.command_klass = "decide", 6
    assert await dev.send("number", "set_value",
                          {"entity_id": "number.wb_current", "value": 10}) is True
    (entry,) = dev.command_ledger
    assert entry["prior"] == "16" and entry["data"]["value"] == 10
    assert entry["source"] == "decide" and entry["klass"] == 6
    assert entry["owed"] is False
    dev.hass.services.async_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_only_the_guard_stop_of_a_yielded_charger_is_owed():
    dev = _dev({"switch.wb_enable": "on"})
    dev.external_yield = True
    dev.phase_guard_override = True
    dev.command_source, dev.command_klass = "phase_guard", 1
    await dev.send("switch", "turn_off", {"entity_id": "switch.wb_enable"})
    await dev.send("keba", "set_failsafe", {"timeout": 0})
    owed = dev.take_owed()
    assert [e["service"] for e in owed] == ["turn_off"]
    assert owed[0]["prior"] == "on"
    assert dev.take_owed() == []          # taken once
    assert len(dev.command_ledger) == 2   # history stays


@pytest.mark.asyncio
async def test_a_withheld_write_is_not_in_the_ledger():
    dev = _dev({"switch.x": "on"})
    dev.observer_mode = True
    assert await dev.send("switch", "turn_off", {"entity_id": "switch.x"}) is False
    dev.observer_mode = False
    dev.external_yield = True            # yields, no guard override
    assert await dev.send("switch", "turn_off", {"entity_id": "switch.x"}) is False
    assert getattr(dev, "command_ledger", []) == []
    dev.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_recording_never_blocks_the_write():
    dev = _dev(raise_on_states=True)
    assert await dev.send("switch", "turn_on", {"entity_id": "switch.x"}) is True
    assert dev.command_ledger[0]["prior"] is None
    dev.hass.services.async_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_ledger_is_bounded():
    dev = _dev({})
    for i in range(ControllableDevice.LEDGER_KEEP + 15):
        await dev.send("number", "set_value", {"entity_id": "number.n", "value": i})
    assert len(dev.command_ledger) == ControllableDevice.LEDGER_KEEP
    assert dev.command_ledger[-1]["data"]["value"] == ControllableDevice.LEDGER_KEEP + 14


@pytest.mark.asyncio
async def test_actuate_stamps_who_asks_on_the_device():
    from custom_components.solar_energy_management.coordinator.actuate import actuate
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision, ChargerIntent,
    )
    dev = _dev({})
    d = ChargerDecision(charger_id="wb", mode="pv", intent=ChargerIntent.IDLE,
                        commanded_amps=0, budget_w=0.0, reason="r",
                        source="stability", klass=6)
    rec = SimpleNamespace(reconcile_and_apply=AsyncMock())
    await actuate(d, SimpleNamespace(_device=dev), SimpleNamespace(power_w=0.0),
                  rec, yielded=True)
    assert dev.command_source == "stability" and dev.command_klass == 6
