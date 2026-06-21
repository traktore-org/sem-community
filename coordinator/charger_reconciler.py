"""Charger state reconciler — desired-vs-observed convergence (#392).

The per-cycle imperative actuator (``actuate.py``) re-issued a hardware
command EVERY coordinator cycle regardless of whether anything changed —
the root cause of the recurring KEBA 6 A reverts and the 391× repeated
``keba.disable`` seen on PROD 2026-06-21. This module replaces that with
a reconciliation loop: compute the desired state, read the observed
state, emit only the actions needed to converge, and emit nothing when
already converged.

Design: docs/superpowers/specs/2026-06-21-charger-reconciler-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple

from .charger_types import ChargerDecision, ChargerIntent

_LOGGER = logging.getLogger(__name__)


class DesiredState(Enum):
    """What SEM wants the charger to BE doing this cycle."""
    OFF = auto()     # user-explicit OFF (ChargerIntent.DISABLE)
    IDLE = auto()    # temporary pause (ChargerIntent.IDLE)
    CHARGE = auto()  # charging (CHARGE_AT_AMPS / CHARGE_MAX)


class ActionKind(Enum):
    """Minimal hardware action the reconciler may emit."""
    NONE = auto()           # already converged — issue nothing
    DISABLE = auto()        # open the contactor (brand disable service)
    WRITE_CURRENT = auto()  # set charging current (amps on the Action)
    START_AND_WRITE = auto()  # open a session + arm failsafe + write (amps)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    amps: int = 0


@dataclass(frozen=True)
class ObservedState:
    """What the charger is actually doing, read from the adapter."""
    charging: bool       # adapter.actual_charging(power) — power-based
    setpoint_a: int      # the value SEM last believes it set
    self_charging: bool  # adapter.is_self_charging(power)
    power_w: float


def desired_from_decision(decision: ChargerDecision) -> Tuple[DesiredState, int]:
    """Pure map: ChargerDecision → (DesiredState, amps).

    CHARGE_MAX returns amps=0 as a sentinel; the apply layer resolves
    the hardware max from the adapter (so this stays pure and the max
    isn't duplicated here)."""
    intent = decision.intent
    if intent is ChargerIntent.DISABLE:
        return DesiredState.OFF, 0
    if intent is ChargerIntent.IDLE:
        return DesiredState.IDLE, 0
    if intent is ChargerIntent.CHARGE_MAX:
        return DesiredState.CHARGE, 0
    if intent is ChargerIntent.CHARGE_AT_AMPS:
        return DesiredState.CHARGE, int(decision.commanded_amps)
    # Defensive: unknown intent → safest is IDLE (no draw, no spam).
    _LOGGER.error("desired_from_decision: unknown intent %r → IDLE", intent)
    return DesiredState.IDLE, 0
