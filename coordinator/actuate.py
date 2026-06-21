"""Pure-dispatch actuate(decision, adapter) (Step 4 of
arch/multi-charger-primary).

The actuator's only job: take a :class:`ChargerDecision` and
invoke the matching :class:`ChargerAdapter` method. No branches on
mode, strategy, or state — the decision already encodes intent.
Brand quirks (KEBA's 6 A min, self-resume, set_current(0)
rejection) are encapsulated in the adapter, not in this layer.

This replaces the 300+ lines of branching in
``ev_control._execute_ev_control`` with one dispatch table. The
disagreement class that produced #315 / #346 / #353 cannot exist
here by construction: there is exactly one branch per intent,
and the intent is computed once by ``decide``.

The actuator does not consult fleet state, mutable context, or
sensor readings beyond what's on the :class:`ChargerPower` argument.
The pre-cycle ``power`` is the input; the adapter reads ``power``
on its own to decide whether self-resume guard fires.
"""
from __future__ import annotations

import logging
import time

from .charger_adapters.base import ChargerAdapter
from .charger_types import ChargerDecision, ChargerIntent, ChargerPower

_LOGGER = logging.getLogger(__name__)


async def actuate(
    decision: ChargerDecision,
    adapter: ChargerAdapter,
    power: ChargerPower,
    reconciler=None,
) -> None:
    """Apply a per-charger decision through the adapter.

    Two-pass:

    1. Self-resume guard — if the adapter reports the charger is
       drawing real power without our consent (``IDLE`` /
       ``DISABLE`` intent in last cycle + ``power_w > handshake``),
       force-disable BEFORE the new intent is applied. Catches
       cold-starts and KEBA self-resumes (#315 / #346 / #353
       collapsed to one guard).

    2. Intent dispatch — one branch per ``ChargerIntent``. The
       adapter does the brand-specific service call.

    Args:
        decision: The output of ``decide(view)`` for this charger
            this cycle.
        adapter: The brand-specific adapter wrapping this charger.
        power: The charger's current power reading (for the
            self-resume guard).
        reconciler: Optional :class:`ChargerReconciler`. When
            supplied, it owns the full convergence decision
            (idempotent idle/off, drift, heartbeat). The legacy
            dispatch below is kept only for callers/tests that
            don't pass one (#392).
    """
    # Reconciler path (#392): when a per-charger reconciler is supplied,
    # it owns the full convergence decision (idempotent idle/off, drift,
    # heartbeat). The legacy per-cycle dispatch below is kept only for
    # callers/tests that don't pass one, and is retired in Increment 3.
    if reconciler is not None:
        await reconciler.reconcile_and_apply(decision, adapter, power, time.monotonic())
        return

    # === Self-resume guard ===
    # Before applying the new intent, check whether the charger is
    # already drawing power against the PRIOR intent. Adapter
    # encapsulates the cutoff (handshake_power_w) and the
    # ``last_intent in {IDLE, DISABLE}`` predicate.
    if adapter.is_self_charging(power):
        _LOGGER.warning(
            "Charger %s self-charging detected (power=%.0fW, last intent=%s) "
            "— forcing disable before applying new intent %s",
            decision.charger_id, power.power_w,
            getattr(adapter, "last_intent", None),
            decision.intent.value,
        )
        await adapter.command_disable()
        # Fall through to apply the new intent — the new intent
        # might also be IDLE/DISABLE (in which case the call is
        # idempotent) OR a CHARGE_* (in which case the disable
        # just opened the contactor and the next command resumes
        # cleanly).

    # === Intent dispatch ===
    #
    # IDLE is the only intent subject to the debounce. DISABLE is the
    # user's explicit OFF — always execute. CHARGE_* obviously execute
    # and reset the counter so a subsequent single IDLE cycle starts
    # a fresh debounce window.
    if decision.intent is not ChargerIntent.IDLE:
        adapter.reset_idle_debounce()

    if decision.intent is ChargerIntent.DISABLE:
        await adapter.command_disable()
        _LOGGER.debug(
            "actuate(%s): DISABLE — %s",
            decision.charger_id, decision.reason,
        )
        return

    if decision.intent is ChargerIntent.IDLE:
        # Solar-flicker resilience — see ChargerAdapter docstring.
        # On the 1st consecutive IDLE we HOLD the previous setpoint
        # so a transient sensor flicker or 1-cycle surplus dip
        # doesn't cascade into ``keba.disable`` → KEBA stuck in
        # "authorization rejected" → contactor refuses subsequent
        # ``set_current``. On the 2nd consecutive IDLE the dip is
        # confirmed real (cloud, target reached, EV unplugged) and
        # ``command_idle`` fires normally.
        if adapter.attempt_idle():
            await adapter.command_idle()
            _LOGGER.info(
                "actuate(%s): IDLE — count=%d/%d — %s",
                decision.charger_id,
                adapter._consecutive_idle_count,
                adapter.IDLE_DEBOUNCE_THRESHOLD,
                decision.reason,
            )
        else:
            _LOGGER.info(
                "actuate(%s): IDLE DEBOUNCED — count=%d/%d, holding previous setpoint — %s",
                decision.charger_id,
                adapter._consecutive_idle_count,
                adapter.IDLE_DEBOUNCE_THRESHOLD,
                decision.reason,
            )
        return

    if decision.intent is ChargerIntent.CHARGE_MAX:
        await adapter.command_max()
        _LOGGER.debug(
            "actuate(%s): CHARGE_MAX — %s",
            decision.charger_id, decision.reason,
        )
        return

    if decision.intent is ChargerIntent.CHARGE_AT_AMPS:
        # Below-min commands are adapter-translated to command_idle
        # (KEBA: see KebaAdapter.command_current). The actuator
        # passes through; the adapter routes appropriately.
        await adapter.command_current(decision.commanded_amps)
        _LOGGER.debug(
            "actuate(%s): CHARGE_AT_AMPS %dA — %s",
            decision.charger_id, decision.commanded_amps, decision.reason,
        )
        return

    # Unreachable — every intent should have a branch. Loud failure
    # so a future intent enum addition can't accidentally silently
    # do nothing.
    _LOGGER.error(
        "actuate(%s): unknown intent %r — no action taken",
        decision.charger_id, decision.intent,
    )
