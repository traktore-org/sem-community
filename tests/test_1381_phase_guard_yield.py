"""#1381 — the fuse comes first: a yielded charger on an over-limit phase.

With "Yes, SEM yields" the phase guard rewrote the charger decision to a
stop, but the yield gate withheld it and, two cycles later, small loads were
shed for a car's overload. Now the guard's own stop (and only that, and only
while a phase is measured over its limit) goes out. Real guard, real send
seam; only the reconciler is a stub that issues the stop sequence.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.active_phase_guard import (
    ActivePhaseGuard,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)
from custom_components.solar_energy_management.devices.base import ControllableDevice
from custom_components.solar_energy_management.features.phase_shed import (
    CHARGERS_FIRST_CYCLES,
)


def _snapshot(current):
    reading = {"current_a": current, "limit_a": 25.0, "margin_a": 25.0 - current,
               "safe": current <= 25.0, "data_fresh": True,
               "reason": "over_limit" if current > 25.0 else None}
    return {"topology": "grid_only", "phase_count": 3, "safe": current <= 25.0,
            "data_fresh": True, "stop_reason": "",
            "grid": {"l1": dict(reading, current_a=10.0, margin_a=15.0, reason=None,
                                safe=True),
                     "l2": dict(reading),
                     "l3": dict(reading, current_a=10.0, margin_a=15.0, reason=None,
                                safe=True)},
            "inverter": {}}


def _guard(current, *, enforcing=True):
    g = ActivePhaseGuard()
    g.update(_snapshot(current), {"phase_guard_enabled": True,
                                  "phase_guard_enforcement_enabled": enforcing})
    return g


def _decision():
    return ChargerDecision(
        charger_id="c1", mode="pv", intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=16, budget_w=11000.0, reason="surplus")


def _device():
    class _Dev(ControllableDevice):
        async def activate(self, w):
            return 0.0

        async def deactivate(self):
            return None

        async def adjust_power(self, w):
            return 0.0

    dev = _Dev.__new__(_Dev)
    dev.hass = MagicMock()
    dev.hass.services.async_call = AsyncMock()
    dev.device_id, dev.name = "c1", "Wallbox"
    dev.observer_mode = False
    dev.external_yield = False
    return dev


async def _cycle(guard, dev):
    """One coordinator cycle for a yielded charger: filter, then actuate."""
    decision = guard.filter_decision(_decision())
    reason = guard.yield_override_reason(decision)

    async def _reconcile(*_a, **_k):
        await dev.send("keba", "disable", {}, why=decision.reason)

    rec = SimpleNamespace(reconcile_and_apply=_reconcile)
    await actuate(decision, SimpleNamespace(_device=dev), SimpleNamespace(), rec,
                  yielded=True, phase_override=reason)
    return decision, reason


@pytest.mark.asyncio
async def test_over_limit_sends_one_stop_to_a_yielded_charger():
    dev = _device()
    decision, reason = await _cycle(_guard(31.2), dev)
    assert decision.intent is ChargerIntent.DISABLE
    assert reason == "phase L2 at 31.2 A > 25.0 A"
    dev.hass.services.async_call.assert_awaited_once()
    assert dev.hass.services.async_call.await_args.args[:2] == ("keba", "disable")
    assert dev.external_yield is True and dev.phase_guard_override is False


@pytest.mark.asyncio
async def test_under_limit_sends_nothing_and_does_not_restart():
    dev = _device()
    decision, reason = await _cycle(_guard(20.0), dev)
    assert reason == ""
    dev.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_latched_but_back_under_the_limit_sends_nothing():
    g = _guard(31.2)
    g.update(_snapshot(24.0), {"phase_guard_enabled": True,
                               "phase_guard_enforcement_enabled": True})
    dev = _device()
    decision, reason = await _cycle(g, dev)
    assert decision.intent is ChargerIntent.DISABLE  # recovery hold
    assert reason == ""
    dev.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_watch_only_withholds_everything():
    dev = _device()
    decision, reason = await _cycle(_guard(31.2, enforcing=False), dev)
    assert reason == ""
    dev.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_a_normal_command_stays_withheld_in_the_same_cycle():
    dev = _device()
    await _cycle(_guard(31.2), dev)
    dev.hass.services.async_call.reset_mock()
    assert await dev.send("keba", "set_current", {"current": 16}) is False
    dev.hass.services.async_call.assert_not_called()


def test_loads_are_not_shed_before_the_charger_stop_has_had_its_turn():
    g = _guard(31.2)
    assert g.phase_shed_request(ev_drawing=True) == {}
    for _ in range(CHARGERS_FIRST_CYCLES - 1):
        g.update(_snapshot(31.2), {"phase_guard_enabled": True,
                                   "phase_guard_enforcement_enabled": True})
    assert g.phase_shed_request(ev_drawing=True) != {}  # only if the stop failed
