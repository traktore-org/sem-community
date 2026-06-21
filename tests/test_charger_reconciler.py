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
