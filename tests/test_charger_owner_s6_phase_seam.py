"""(#1381, charger owner S6) The phase switch goes through the one seam.

``_phase_switch_tick`` called ``hass.services.async_call`` itself, with its
own copy of the observer gate (#804). With a charger device at hand (the
fleet path always passes one), the switch now goes through
``ControllableDevice.send``: observer mode withholds it there and lists it
in ``withheld_commands``, a yielded charger's switch is held back by the same
yield gate, and the command ledger records it.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator import ev_control
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.devices.base import ControllableDevice


class _Dev(ControllableDevice):
    async def activate(self, w):
        return 0.0

    async def deactivate(self):
        return None

    async def adjust_power(self, w):
        return 0.0


def _host(observer=False):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = observer
    h._surplus_controller = None
    sun = MagicMock()
    h.hass = SimpleNamespace(states=SimpleNamespace(get=lambda eid: sun),
                             services=SimpleNamespace(async_call=AsyncMock()))
    h.cfg = {"ev_phase_switch_entity": "number.wb_phases",
             "ev_phase_switching_enabled": True, "phase_mode": "1",
             "ev_voltage": 230, "ev_min_current": 6}
    dev = _Dev.__new__(_Dev)
    dev.hass = h.hass
    dev.device_id = dev.name = "c1"
    dev.observer_mode = observer
    dev.external_yield = False
    return h, dev


def _decision():
    return ChargerDecision(charger_id="c1", mode="solar_only",
                           intent=ChargerIntent.CHARGE_AT_AMPS,
                           commanded_amps=10, budget_w=4600.0, reason="t")


def _cp(w, charging):
    return ChargerPower(charger_id="c1", power_w=w, connected=True,
                        charging=charging)


def _walk(h, dev):
    asyncio.run(h._phase_switch_tick("c1", h.cfg, _decision(), _cp(6900.0, True),
                                     0.0, device=dev))
    asyncio.run(h._phase_switch_tick("c1", h.cfg, _decision(), _cp(0.0, False),
                                     30.0, device=dev))


def test_the_switch_is_one_write_through_the_device_seam():
    h, dev = _host()
    _walk(h, dev)
    h.hass.services.async_call.assert_awaited_once()
    (entry,) = dev.command_ledger
    assert entry["service"] == "set_value"
    assert entry["data"] == {"entity_id": "number.wb_phases", "value": 1.0}


def test_observer_withholds_it_at_the_seam_and_lists_it():
    h, dev = _host(observer=True)
    _walk(h, dev)
    h.hass.services.async_call.assert_not_awaited()
    assert [c["service"] for c in dev.withheld_commands] == ["number.set_value"]
