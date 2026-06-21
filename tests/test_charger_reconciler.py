"""Charger state reconciler — desired-vs-observed convergence (#392).

Replaces the per-cycle imperative actuator. These tests pin the pure
decision table: given a desired state, an observed state and a clock,
the reconciler emits the MINIMUM set of actions to converge — and
emits NONE when already converged (the root-cause fix for the 391×
keba.disable spam seen on PROD 2026-06-21).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind,
    DesiredState,
    ObservedState,
    desired_from_decision,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)


def _decision(intent: ChargerIntent, amps: int = 0) -> ChargerDecision:
    # ChargerDecision requires: charger_id, mode, intent (+ optional fields).
    # mode is a required positional field — supply a stub value.
    return ChargerDecision(
        charger_id="ev_charger",
        mode="solar",
        intent=intent,
        commanded_amps=amps,
        reason="test",
        budget_w=0.0,
    )


def test_desired_from_decision_maps_every_intent():
    assert desired_from_decision(_decision(ChargerIntent.DISABLE)) == (DesiredState.OFF, 0)
    assert desired_from_decision(_decision(ChargerIntent.IDLE)) == (DesiredState.IDLE, 0)
    assert desired_from_decision(_decision(ChargerIntent.CHARGE_AT_AMPS, 10)) == (DesiredState.CHARGE, 10)
    # CHARGE_MAX maps to CHARGE with amps=0 sentinel — apply layer resolves max.
    assert desired_from_decision(_decision(ChargerIntent.CHARGE_MAX)) == (DesiredState.CHARGE, 0)


from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action, ActionKind, ChargerReconciler, ObservedState,
)

HEARTBEAT_S = 5.0  # KEBA refresh interval


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=HEARTBEAT_S,
                             idle_disable_threshold=4)


def _obs(charging=False, setpoint=0, self_charging=False, power=0.0) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=setpoint,
                         self_charging=self_charging, power_w=power)


def test_idle_not_drawing_emits_nothing_every_cycle():
    """The PROD bug: IDLE + already-open contactor must NOT re-disable."""
    rec = _rec()
    for cycle in range(100):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle} spammed: {actions}"


def test_off_drawing_disables_immediately_no_flicker_grace():
    rec = _rec()
    actions = rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4000.0), now=0.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_drawing_holds_then_disables_after_threshold():
    rec = _rec()
    # cycles 1..3 (< threshold 4): flicker hold → NONE
    for cycle in range(1, 4):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0),
                                now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"
    # cycle 4 (>= threshold): confirmed real → DISABLE
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=40.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_resets_flicker_counter_when_box_stops():
    rec = _rec()
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=10.0)  # count=1
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=20.0)  # stopped → NONE + reset
    # next drawing idle starts a fresh hold window, not an immediate disable
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=30.0)
    assert actions == [Action(ActionKind.NONE)]


def test_charge_not_charging_starts():
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    assert actions == [Action(ActionKind.START_AND_WRITE, 10)]


def test_charge_steady_writes_only_on_heartbeat():
    """Steady CHARGE(10): write on start, then only every heartbeat_s."""
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)  # START
    writes = 0
    for cycle in range(1, 100):
        t = cycle * 1.0  # 1 s cycle to make heartbeat counting easy
        actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, setpoint=10), now=t)
        if actions != [Action(ActionKind.NONE)]:
            writes += 1
            assert actions == [Action(ActionKind.WRITE_CURRENT, 10)]
    # 99 cycles over 1 s each, heartbeat 5 s → ~19 refreshes, not 99
    assert 15 <= writes <= 21, writes


def test_charge_target_change_writes_immediately():
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    actions = rec.reconcile(DesiredState.CHARGE, 12, _obs(charging=True, setpoint=10), now=1.0)
    assert actions == [Action(ActionKind.WRITE_CURRENT, 12)]


def test_charge_drift_rewrites():
    """Box silently reverted to 6 A (failsafe) while we wanted 10 → re-assert."""
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, setpoint=6), now=1.0)
    assert actions == [Action(ActionKind.WRITE_CURRENT, 10)]


# ─────────────────────────────────────────────────────────────────
# Task 3 — effectful layer: observe() + reconcile_and_apply()
# ─────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock
from custom_components.solar_energy_management.coordinator.charger_types import ChargerPower


def _mock_adapter(max_a=32):
    a = MagicMock()
    a.command_disable = AsyncMock()
    a.command_current = AsyncMock()
    a.command_max = AsyncMock()
    a.arm_failsafe = AsyncMock()
    a.max_current_a = max_a
    return a


def _power(power_w=0.0):
    return ChargerPower(charger_id="ev_charger", power_w=power_w)


@pytest.mark.asyncio
async def test_apply_idle_idempotent_no_calls_when_open():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    for cycle in range(50):
        await rec.reconcile_and_apply(
            _decision(ChargerIntent.IDLE), adapter, _power(0.0), now=cycle * 10.0)
    adapter.command_disable.assert_not_called()
    adapter.command_current.assert_not_called()


@pytest.mark.asyncio
async def test_apply_charge_max_resolves_hardware_max():
    rec = _rec()
    adapter = _mock_adapter(max_a=32)
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=32)
    await rec.reconcile_and_apply(
        _decision(ChargerIntent.CHARGE_MAX), adapter, _power(22000.0), now=100.0)
    # heartbeat due (last_write_at=0) → a refresh write at max
    adapter.command_current.assert_called_once_with(32)


# ─────────────────────────────────────────────────────────────────
# Task 4 — wire reconciler into actuate() as optional parameter
# ─────────────────────────────────────────────────────────────────

from custom_components.solar_energy_management.coordinator.actuate import actuate


@pytest.mark.asyncio
async def test_actuate_delegates_to_reconciler_when_provided():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    # IDLE + open contactor → reconciler issues nothing
    await actuate(_decision(ChargerIntent.IDLE), adapter, _power(0.0), reconciler=rec)
    adapter.command_disable.assert_not_called()


@pytest.mark.asyncio
async def test_actuate_legacy_path_unchanged_without_reconciler():
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.reset_idle_debounce = MagicMock()
    # CHARGE_MAX with no reconciler → legacy dispatch calls command_max
    await actuate(_decision(ChargerIntent.CHARGE_MAX), adapter, _power(0.0))
    adapter.command_max.assert_awaited_once()


def test_off_not_drawing_emits_nothing():
    """mode=off + EV unplugged/contactor open → zero service calls (the
    primary production scenario; must not fall through to DISABLE)."""
    rec = _rec()
    for cycle in range(10):
        actions = rec.reconcile(DesiredState.OFF, 0, _obs(charging=False), now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle} spammed: {actions}"


@pytest.mark.asyncio
async def test_start_arms_failsafe_once():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(side_effect=[False, True, True])
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=10)
    adapter.arm_failsafe = AsyncMock()
    # cycle 1: not charging → START arms failsafe
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(0.0), now=0.0)
    adapter.arm_failsafe.assert_awaited_once()
    # cycle 2: charging steady → no re-arm
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(7000.0), now=1.0)
    adapter.arm_failsafe.assert_awaited_once()


@pytest.mark.asyncio
async def test_failsafe_armed_once_per_charge_episode_not_on_transient_drop():
    """A transient observed-drop while desired stays CHARGE must NOT
    re-START / re-arm the failsafe. The failsafe is armed once on the
    idle→charge transition; recovery from a mid-charge drop rides the
    heartbeat WRITE (command_current re-opens a dropped session and keeps
    the already-armed failsafe fed). Re-arming every drop would be the
    keba.set_failsafe spam this design removes."""
    rec = _rec()
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=10)
    adapter.arm_failsafe = AsyncMock()
    # transition into charge → START + arm once
    adapter.actual_charging = MagicMock(return_value=True)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(7000.0), now=0.0)
    assert adapter.arm_failsafe.await_count == 1
    # box drops out while we still want CHARGE → NO re-arm (rides heartbeat)
    adapter.actual_charging = MagicMock(return_value=False)
    for cycle in range(1, 6):
        await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                      adapter, _power(0.0), now=float(cycle))
    assert adapter.arm_failsafe.await_count == 1  # still 1 — no re-arm spam
    # only a real idle→charge transition re-arms
    await rec.reconcile_and_apply(_decision(ChargerIntent.IDLE), adapter,
                                  _power(0.0), now=10.0)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(0.0), now=11.0)
    assert adapter.arm_failsafe.await_count == 2


@pytest.mark.asyncio
async def test_charge_never_drawing_starts_once_then_heartbeat_no_respam():
    """REGRESSION (HA-TEST 2026-06-21): a charger that never reports
    drawing (mock, ramp lag, or a full-but-plugged car held in a deadline
    mode) must START exactly once, then only heartbeat-WRITE — NOT re-START
    + re-arm-failsafe every cycle. 100 cycles, START gated on transition."""
    rec = _rec()
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.actual_charging = MagicMock(return_value=False)  # never draws
    adapter._device = MagicMock(_current_setpoint=6)
    adapter.arm_failsafe = AsyncMock()
    for cycle in range(100):
        await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 6),
                                      adapter, _power(0.0), now=cycle * 10.0)
    assert adapter.arm_failsafe.await_count == 1, "failsafe re-armed every cycle (spam)"
    # writes are heartbeat-paced (5s heartbeat, 10s cycles → ~1/cycle), not 0,
    # so the device watchdog stays fed — but no START/arm storm.
    assert adapter.command_current.call_count >= 1


@pytest.mark.asyncio
async def test_charge_max_drift_corrects():
    rec = _rec()
    adapter = _mock_adapter(max_a=32)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.arm_failsafe = AsyncMock()
    adapter._device = MagicMock(_current_setpoint=32)
    # establish the charge episode (START) so the next cycle exercises drift
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_MAX),
                                  adapter, _power(22000.0), now=0.0)
    adapter.command_current.reset_mock()
    # box reverted to 6 A failsafe floor while we still want max → re-assert 32
    adapter._device._current_setpoint = 6
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_MAX),
                                  adapter, _power(4000.0), now=1.0)
    adapter.command_current.assert_called_once_with(32)
