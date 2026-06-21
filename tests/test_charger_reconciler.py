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
