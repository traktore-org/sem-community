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


# ── through the REAL reconciler, adapter and send seam ────────────────

from custom_components.solar_energy_management.coordinator.charger_adapters import (  # noqa: E402
    adapter_for,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (  # noqa: E402
    STOP_REASSERT_DWELL_S,
    ChargerReconciler,
)
from custom_components.solar_energy_management.devices.base import (  # noqa: E402
    CurrentControlDevice,
)

DRAWING = SimpleNamespace(power_w=7000.0, connected=True, charging=True)


def _real(kind):
    """A yielded charger of ``kind`` on a real device + adapter."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    def _state(eid):
        on = eid.startswith(("switch.", "input_boolean."))
        return SimpleNamespace(
            state="on" if on else "16",
            attributes={"min": 0, "max": 32, "step": 1,
                        "options": ["stop", "start"]})
    hass.states.get = MagicMock(side_effect=_state)
    kw = dict(charger_service=None, current_entity_id="number.ev_current")
    if kind == "keba":
        kw["charger_service"] = "keba.set_current"
    dev = CurrentControlDevice(
        hass=hass, device_id="c1", name="Wallbox", priority=3, min_current=6.0,
        max_current=32.0, phases=3, voltage=230.0, power_entity_id="sensor.p",
        **kw)
    if kind == "switch":
        dev.start_stop_entity = "switch.wallbox_pause"
    elif kind == "select":
        dev.charge_mode_entity, dev.charge_mode_stop = "select.mode", "stop"
    elif kind == "service":
        dev.stop_service = "wallbox.stop"
    elif kind == "ocpp":
        dev.zero_amps_parks_a_limit = True
    dev.external_yield = True
    return dev, hass, adapter_for(dev)


def _written(hass):
    return [(c.args[0], c.args[1], dict(c.args[2]) if len(c.args) > 2 else {})
            for c in hass.services.async_call.await_args_list]


async def _real_cycle(guard, dev, adapter, rec, now_ref, current=31.2):
    decision = guard.filter_decision(_decision())
    reason = guard.yield_override_reason(decision)
    real_mono = __import__("time").monotonic
    import time as _t
    _t.monotonic = lambda: now_ref[0]
    try:
        await actuate(decision, adapter, DRAWING, rec, yielded=True,
                      phase_override=reason)
    finally:
        _t.monotonic = real_mono


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["keba", "switch", "select", "service", "number", "ocpp"])
async def test_each_charger_kind_gets_only_its_own_stop(kind):
    dev, hass, adapter = _real(kind)
    rec = ChargerReconciler(charger_id="c1", heartbeat_s=5.0, idle_disable_threshold=4)
    await _real_cycle(_guard(31.2), dev, adapter, rec, [1000.0])
    calls = _written(hass)
    # an OCPP number with no switch cannot be stopped safely (#976): the
    # reconciler writes nothing, and the override must not change that
    assert calls or kind == "ocpp", f"{kind}: the stop never went out"
    assert not any(s == "set_failsafe" for _d, s, _x in calls)  # no dead-man
    assert not any(s in ("authorize", "enable", "turn_off") and kind == "keba"
                   for _d, s, _x in calls)
    if kind == "keba":
        assert calls == [("keba", "disable", {})]
    if kind == "ocpp":  # #976: a persisted 0 A profile is never written
        assert not any(d == "number" and x.get("value") == 0 for d, _s, x in calls)


@pytest.mark.asyncio
async def test_the_real_reconciler_writes_one_stop_then_holds_the_dwell():
    dev, hass, adapter = _real("keba")
    rec = ChargerReconciler(charger_id="c1", heartbeat_s=5.0, idle_disable_threshold=4)
    g, now = _guard(31.2), [1000.0]
    for _ in range(5):  # five cycles, 10 s apart, all over the limit
        await _real_cycle(g, dev, adapter, rec, now)
        now[0] += 10.0
    assert _written(hass) == [("keba", "disable", {})]
    now[0] += STOP_REASSERT_DWELL_S
    await _real_cycle(g, dev, adapter, rec, now)
    assert len(_written(hass)) == 2  # one re-assert after the dwell, no more


@pytest.mark.asyncio
async def test_a_stop_goes_out_inside_the_contactor_minimum_on_time():
    dev, hass, adapter = _real("keba")
    rec = ChargerReconciler(charger_id="c1", heartbeat_s=5.0, idle_disable_threshold=4)
    now = [1000.0]
    rec._charge_started_at = now[0] - 30.0  # charging for 30 s only
    await _real_cycle(_guard(31.2), dev, adapter, rec, now)
    assert _written(hass) == [("keba", "disable", {})]


@pytest.mark.asyncio
async def test_a_third_party_that_keeps_re_enabling_hits_the_ceasefire():
    global DRAWING
    dev, hass, adapter = _real("keba")
    rec = ChargerReconciler(charger_id="c1", heartbeat_s=5.0, idle_disable_threshold=4)
    g, now = _guard(31.2), [1000.0]
    try:
        for _ in range(12):  # stop lands, the third party starts it again
            for watts in (0.0, 7000.0):
                DRAWING = SimpleNamespace(power_w=watts, connected=True,
                                          charging=watts > 0)
                await _real_cycle(g, dev, adapter, rec, now)
                now[0] += STOP_REASSERT_DWELL_S + 1.0
    finally:
        DRAWING = SimpleNamespace(power_w=7000.0, connected=True, charging=True)
    assert rec._stop_war_backoff_until > 0  # the ceasefire armed
    assert len(_written(hass)) < 12
