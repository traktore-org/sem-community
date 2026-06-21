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
from typing import TYPE_CHECKING, List, Tuple

from .charger_types import ChargerDecision, ChargerIntent, ChargerPower

if TYPE_CHECKING:
    from .charger_adapters.base import ChargerAdapter

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


class ChargerReconciler:
    """Per-charger convergence engine. One instance per charger, cached
    for the charger's lifetime (it holds transition state). Pure
    ``reconcile`` for decisions; effectful ``reconcile_and_apply`` (Task 3)
    executes them via the adapter.
    """

    def __init__(self, charger_id: str, heartbeat_s: float,
                 idle_disable_threshold: int = 4) -> None:
        self.charger_id = charger_id
        self._heartbeat_s = float(heartbeat_s)
        self._idle_disable_threshold = int(idle_disable_threshold)
        self._last_write_at: float = 0.0
        self._consecutive_idle_count: int = 0
        self._charging_intent_active: bool = False
        """True once we've issued the START for the current charge episode.
        Gates the START_AND_WRITE action on the *desired-state transition*
        into CHARGE, NOT on ``observed.charging`` — otherwise a charger
        that isn't drawing yet (ramp lag, a full-but-plugged car held in a
        deadline mode, a mock charger) would re-START + re-arm the failsafe
        every single cycle (the exact spam this whole change removes; caught
        live on HA-TEST 2026-06-21). Reset whenever desired leaves CHARGE."""

    def reconcile(self, desired: DesiredState, amps: int,
                  observed: ObservedState, now: float) -> List[Action]:
        """Pure decision table (spec rows 1-8, first match wins)."""

        # OFF / IDLE share the convergence target (contactor open). The
        # only difference is the flicker grace, which OFF never gets.
        if desired in (DesiredState.OFF, DesiredState.IDLE):
            # Leaving CHARGE — the next CHARGE episode must START + re-arm.
            self._charging_intent_active = False
            drawing = observed.charging or observed.self_charging
            if not drawing:
                # Row 2 — already converged. THE spam fix: issue nothing.
                self._consecutive_idle_count = 0
                return [Action(ActionKind.NONE)]
            if desired is DesiredState.OFF:
                # Row 1 — user-explicit OFF: open immediately, no grace.
                return [Action(ActionKind.DISABLE)]
            # IDLE + drawing — flicker hold then confirm (rows 3-4).
            self._consecutive_idle_count += 1
            self._consecutive_idle_count = min(self._consecutive_idle_count, self._idle_disable_threshold)
            if self._consecutive_idle_count < self._idle_disable_threshold:
                return [Action(ActionKind.NONE)]
            return [Action(ActionKind.DISABLE)]

        # desired is CHARGE — reset idle grace.
        self._consecutive_idle_count = 0
        if not self._charging_intent_active:
            # Row 5 — TRANSITION into charging: open a session, arm the
            # failsafe, write. Gated on the desired transition (not on
            # observed.charging) so a not-yet-drawing charger doesn't
            # re-START every cycle. Recovery from a mid-charge device reset
            # is handled by the heartbeat WRITE below (command_current
            # re-opens a dropped KEBA session and keeps the already-armed
            # failsafe fed) — no re-arm spam needed.
            self._charging_intent_active = True
            self._last_write_at = now
            return [Action(ActionKind.START_AND_WRITE, amps)]
        if amps and observed.setpoint_a != amps:
            # Row 6 — target change or drift (failsafe revert) correction.
            self._last_write_at = now
            return [Action(ActionKind.WRITE_CURRENT, amps)]
        if (now - self._last_write_at) >= self._heartbeat_s:
            # Row 7 — refresh to feed the device failsafe watchdog.
            self._last_write_at = now
            return [Action(ActionKind.WRITE_CURRENT, amps)]
        # Row 8 — converged and fresh.
        return [Action(ActionKind.NONE)]

    async def reconcile_and_apply(self, decision: ChargerDecision,
                                 adapter: "ChargerAdapter",
                                 power: ChargerPower, now: float) -> None:
        """Compute desired+observed, reconcile, execute the actions."""
        desired, amps = desired_from_decision(decision)
        if desired is DesiredState.CHARGE and amps == 0:
            # Resolve the CHARGE_MAX sentinel to the hardware max so the
            # adapter writes a real value and drift detection works.
            amps = int(getattr(adapter, "max_current_a", 0)) or amps
        observed = observe(adapter, power)
        actions = self.reconcile(desired, amps, observed, now)

        for action in actions:
            if action.kind is ActionKind.NONE:
                continue
            if action.kind is ActionKind.DISABLE:
                await adapter.command_disable()
                _LOGGER.info("reconcile(%s): DISABLE — %s",
                             self.charger_id, decision.reason)
            elif action.kind is ActionKind.START_AND_WRITE:
                await adapter.arm_failsafe()
                await adapter.command_current(action.amps)
                _LOGGER.info("reconcile(%s): START %dA (failsafe armed) — %s",
                             self.charger_id, action.amps, decision.reason)
            elif action.kind is ActionKind.WRITE_CURRENT:
                await adapter.command_current(action.amps)
                _LOGGER.debug("reconcile(%s): WRITE %dA — %s",
                              self.charger_id, action.amps, decision.reason)


# ─────────────────────────────────────────────────────────────────
# Task 3 — effectful layer
# ─────────────────────────────────────────────────────────────────

def observe(adapter, power) -> ObservedState:
    """Read the observed state from the adapter (brand-agnostic)."""
    setpoint = int(round(float(getattr(getattr(adapter, "_device", None), "_current_setpoint", 0) or 0)))
    return ObservedState(
        charging=adapter.actual_charging(power),
        setpoint_a=setpoint,
        self_charging=adapter.is_self_charging(power),
        power_w=float(getattr(power, "power_w", 0.0) or 0.0),
    )
