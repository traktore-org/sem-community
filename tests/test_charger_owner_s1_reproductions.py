"""(#1381, charger owner S1) The two conflicts the owner map names, as tests.

C1 — the phase guard stops a charger another party steers ("SEM yields"),
the phase recovers, and nothing switched the charger back on. The reporter's
car sat off for 9 hours (23→24.11). It was a strict xfail from S1 until the
owner's ledger handed it back (S5).

C2 — the map suspected the load manager writes 0 A to a charger and the
restore writes nothing. Reading the code refuted it: ``_shed_device`` and
both pickers refuse an ``ev_charger`` row (#461-peak,
``_peak_managed_elsewhere``). This test pins that, so the owner never has to
undo a load-manager write on a charger.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)
from custom_components.solar_energy_management.devices.base import ControllableDevice
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)

SW = "switch.links_charging_enable"
CID = "laadpaal_links"


class _States:
    def __init__(self, init):
        self.values = dict(init)

    def get(self, entity):
        if entity not in self.values:
            return None
        return SimpleNamespace(state=self.values[entity], attributes={})


def _hass(states):
    hass = MagicMock()
    hass.states = states
    hass.calls = []

    async def _call(domain, service, data, blocking=True):
        ent = data.get("entity_id")
        if service == "turn_off":
            states.values[ent] = "off"
        elif service == "turn_on":
            states.values[ent] = "on"
        hass.calls.append((domain, service, ent))

    hass.services.async_call = AsyncMock(side_effect=_call)
    return hass


def _device(hass):
    class _Dev(ControllableDevice):
        async def activate(self, w):
            return 0.0

        async def deactivate(self):
            return None

        async def adjust_power(self, w):
            return 0.0

    dev = _Dev.__new__(_Dev)
    dev.hass = hass
    dev.device_id = dev.name = CID
    dev.observer_mode = False
    dev.external_yield = False
    return dev


ARMED_ROOMY = {"mode": "enforcing_armed", "topology": "grid_only",
               "phase_count": 3,
               "grid": {p: {"margin_a": 18.0, "current_a": 5.0, "limit_a": 23.0}
                        for p in ("l1", "l2", "l3")},
               "inverter": {}}


@pytest.mark.asyncio
async def test_c1_a_yielded_charger_the_guard_stopped_is_handed_back():
    from custom_components.solar_energy_management.coordinator import (
        charger_owner,
    )
    states = _States({SW: "on"})
    hass = _hass(states)
    dev = _device(hass)
    adapter = SimpleNamespace(_device=dev, phases=3, voltage=230, min_current_a=6)
    power = SimpleNamespace(power_w=10400.0, car_absent=False)
    coord = SimpleNamespace(hass=hass, _ev_devices={CID: dev}, _ev_device=None,
                            _observer_mode=False, _phase_guard_snapshot={},
                            _ev_priority_for=lambda cid: 1)
    decision = ChargerDecision(charger_id=CID, mode="pv",
                               intent=ChargerIntent.DISABLE, commanded_amps=0,
                               budget_w=0.0, reason="phase guard")

    async def _reconcile(*_a, **_k):
        await dev.send("switch", "turn_off", {"entity_id": SW}, why="guard")

    reason = "phase L3 at 28.0 A > 23.0 A"
    await actuate(decision, adapter, power,
                  SimpleNamespace(reconcile_and_apply=_reconcile),
                  yielded=True, phase_override=reason)
    assert states.values[SW] == "off"
    charger_owner.after_charger_cycle(coord, CID, adapter, power, reason,
                                      yielded=True, now=1000.0)
    coord._phase_guard_snapshot = ARMED_ROOMY
    await charger_owner.fleet_step(coord, now=1300.0)
    assert states.values[SW] == "on"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["peak_shed", "emergency", "phase_guard"])
async def test_c2_the_load_manager_never_writes_to_a_charger_row(reason):
    lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
    lm._devices = {"load_device_ev_charger": {
        "device_type": "ev_charger", "control_type": "current",
        "switch_entity": "number.wb_current", "charger_id": "ev_charger",
        "control": {"type": "current", "entity": "number.wb_current"},
        "priority": 3, "is_critical": False,
    }}
    lm.hass = MagicMock()
    lm.hass.states.get = MagicMock(
        return_value=SimpleNamespace(state="16", attributes={}))
    lm.hass.services.async_call = AsyncMock()
    lm._save_device_configuration = AsyncMock()
    lm._trigger_callbacks = MagicMock()
    shed = await lm._shed_device("load_device_ev_charger", reason)
    assert shed is False
    lm.hass.services.async_call.assert_not_called()
