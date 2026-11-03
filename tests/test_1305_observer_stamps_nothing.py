"""#1305 — a stop that observer mode never sent arms no relay clock.

The reconciler stamped ``_last_disable_at`` and believed the relay open
the moment it DECIDED a stop. Under observer mode (and an external yield)
the device's ``send`` withholds every write, so nothing opened. A charger
with no readable switch (KEBA, service control) kept the false belief, and
the first real start after observer went off waited the 300 s minimum-off
for a relay nobody moved. The decision table still runs in full, so the
observer surface keeps showing what SEM WOULD send.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    CONTACTOR_MIN_OFF_S,
    ChargerReconciler,
    commands_leave,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)


def _keba_like(*, observer=False, yielded=False):
    dev = MagicMock()
    dev.observer_mode = observer
    dev.external_yield = yielded
    dev.contactor_surface = True            # a relay: the #940 floors apply
    dev._current_setpoint = 0
    a = MagicMock()
    a._device = dev
    a.max_current_a = 16
    a.is_self_charging = lambda p: False
    a.enable_state = lambda: (None, True)   # no readable start switch
    for name in ("command_disable", "command_park_off", "command_current",
                 "arm_failsafe", "ensure_enabled", "command_idle"):
        setattr(a, name, AsyncMock())
    return a


DRAWING = ChargerPower(charger_id="keba", power_w=4100.0, connected=True, charging=True)
IDLE = ChargerPower(charger_id="keba", power_w=0.0, connected=True, charging=False)
OFF = ChargerDecision(charger_id="keba", mode="off", intent=ChargerIntent.DISABLE, reason="off")
CHARGE = ChargerDecision(charger_id="keba", mode="min_plus_solar",
                         intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=6, reason="sun")


async def _stop_then_start(adapter, gap_s: float):
    rec = ChargerReconciler(charger_id="keba", heartbeat_s=5.0)
    adapter.actual_charging = lambda p: True
    await rec.reconcile_and_apply(OFF, adapter, DRAWING, 100.0)
    stop_actions = list(rec._last_actions)
    adapter._device.observer_mode = False
    adapter._device.external_yield = False
    adapter.actual_charging = lambda p: False
    await rec.reconcile_and_apply(CHARGE, adapter, IDLE, 100.0 + gap_s)
    return rec, stop_actions


@pytest.mark.asyncio
async def test_a_stop_nobody_sent_does_not_hold_the_next_real_start():
    rec, stop_actions = await _stop_then_start(_keba_like(observer=True), 20.0)
    assert stop_actions == ["DISABLE"]               # the would-send is right
    assert "START_AND_WRITE" in rec._last_actions, rec._last_actions
    assert rec.anticycle_snapshot(120.0)["holding"] is None


@pytest.mark.asyncio
async def test_observer_mode_stamps_no_clock_and_no_belief():
    rec = ChargerReconciler(charger_id="keba", heartbeat_s=5.0)
    adapter = _keba_like(observer=True)
    adapter.actual_charging = lambda p: True
    await rec.reconcile_and_apply(OFF, adapter, DRAWING, 100.0)
    assert rec._last_disable_at == float("-inf")
    assert rec._last_disable_issued_at == 0.0
    assert rec._contactor_closed is not False
    snap = rec.anticycle_snapshot(100.0)
    assert snap["would_close"] is False              # what SEM would have done
    assert snap["closed"] is not False               # what SEM knows it did


@pytest.mark.asyncio
async def test_a_sent_stop_still_holds_the_next_start():
    rec, _ = await _stop_then_start(_keba_like(observer=False), 20.0)
    assert rec._last_actions == ["NONE"]
    assert rec.anticycle_snapshot(120.0)["holding"] == "min_off"
    rec2, _ = await _stop_then_start(_keba_like(observer=False), CONTACTOR_MIN_OFF_S + 1)
    assert "START_AND_WRITE" in rec2._last_actions


@pytest.mark.asyncio
async def test_an_external_yield_is_the_same_as_observer():
    rec, stop_actions = await _stop_then_start(_keba_like(yielded=True), 20.0)
    assert stop_actions == ["DISABLE"]
    assert "START_AND_WRITE" in rec._last_actions


@pytest.mark.asyncio
async def test_observer_keeps_deciding_the_stop_every_cycle():
    # #1233 counts the stop INTENT against a live draw; with no dwell stamp
    # the DISABLE is decided each cycle and the count still climbs.
    rec = ChargerReconciler(charger_id="keba", heartbeat_s=5.0)
    adapter = _keba_like(observer=True)
    adapter.actual_charging = lambda p: True
    for n in range(3):
        await rec.reconcile_and_apply(OFF, adapter, DRAWING, 100.0 + n * 10)
        assert rec._last_actions == ["DISABLE"]
    assert rec._stop_commanded_while_drawing == 3


@pytest.mark.asyncio
async def test_mode_off_under_observer_stamps_no_gap_anchor():
    rec = ChargerReconciler(charger_id="keba", heartbeat_s=5.0)
    adapter = _keba_like(observer=True)
    adapter.actual_charging = lambda p: True
    await rec.reconcile_and_apply(CHARGE, adapter, DRAWING, 90.0)   # a session
    released = ChargerDecision(charger_id="keba", mode="off",
                               intent=ChargerIntent.RELEASE, reason="off")
    await rec.reconcile_and_apply(released, adapter, DRAWING, 100.0)
    assert rec._last_actions == ["DISABLE"]           # Off: the one would-stop
    assert rec._released_stop_at == 0.0
    assert rec._last_disable_at == float("-inf")


def test_commands_leave_reads_the_device():
    assert commands_leave(_keba_like()) is True
    assert commands_leave(_keba_like(observer=True)) is False
    assert commands_leave(_keba_like(yielded=True)) is False
    bare = MagicMock()
    bare._device = None
    assert commands_leave(bare) is True              # nobody told it: it acts
