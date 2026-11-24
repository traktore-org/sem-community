"""Thin actuate(decision, adapter, power, reconciler) delegation.

The actuator's only job: hand a per-charger :class:`ChargerDecision`
to the :class:`ChargerReconciler`, which owns convergence (idempotent
idle/off, idle flicker-hold, drift correction, heartbeat refresh,
enable-reconcile with backoff). Brand quirks (KEBA's 6 A min,
self-resume, set_current(0) rejection) live in the adapter, not here.

Pre-architecture the same logic was spread across 300+ lines of
branching in ``ev_control._execute_ev_control``. The disagreement
class that produced #315 / #346 / #353 cannot exist here by
construction: ``decide`` computes the intent once, and the reconciler
is the single convergence authority.

The actuator does not consult fleet state, mutable context, or
sensor readings beyond what's on the :class:`ChargerPower` argument.
"""
from __future__ import annotations

import logging
import time

from .charger_adapters.base import ChargerAdapter
from . import reason_codes as RC
from .charger_types import ChargerDecision, ChargerPower, commanded_power_w, rewrite
from .decision_log import log_of
from ..utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)


def _observe(decision: ChargerDecision, adapter: ChargerAdapter,
             controller=None) -> None:
    """OBSERVER mode = the layer-3 intercept for chargers, in one place.

    Exactly the cut loads already had in
    ``surplus_controller._reconcile_load_observe``: ``build_view`` and
    ``decide`` already ran live against the real sensors and produced
    ``decision``. Here — the only execution seam — we record and log the
    command we WOULD send, and touch neither the reconciler nor the box.

    Before this, observer mode cut ABOVE the decision (the coordinator
    skipped the whole per-charger block), so no adapter was built and there
    was no charger decision to observe at all.
    """
    watts = commanded_power_w(
        decision,
        phases=int(getattr(adapter, "phases", 3) or 3),
        voltage=float(getattr(adapter, "voltage", 230.0) or 230.0),
        max_current_a=float(getattr(adapter, "max_current_a", 32.0) or 32.0),
    )
    if controller is not None:
        try:
            controller.publish_observer_decision(
                key=f"ev:{decision.charger_id}",
                name=str(decision.charger_id),
                action=decision.intent.value,
                power_w=watts,
                source=decision.mode,
                reason=decision.reason,
                kind="charger",
                amps=int(decision.commanded_amps or 0),
            )
        except Exception:  # noqa: BLE001 — the surface must never break the seam
            pass
    # (#762) transition-gated: a WOULD that has not changed is not news.
    log_on_change(
        _LOGGER, f"observer:ev:{decision.charger_id}", logging.INFO,
        "OBSERVER · WOULD %s %s @ %.0fW (%dA) [mode=%s] — %s",
        decision.intent.value.upper(), decision.charger_id, watts,
        int(decision.commanded_amps or 0), decision.mode, decision.reason,
    )


async def actuate(
    decision: ChargerDecision,
    adapter: ChargerAdapter,
    power: ChargerPower,
    reconciler,
    *,
    observer: bool = False,
    controller=None,
    yielded: bool = False,
    phase_override: str = "",
) -> None:
    """Apply a per-charger decision through the reconciler.

    The reconciler owns convergence; brand quirks live in the adapter.

    Args:
        decision: The output of ``decide(view)`` for this charger
            this cycle.
        adapter: The brand-specific adapter wrapping this charger.
        power: The charger's current power reading.
        reconciler: The per-charger :class:`ChargerReconciler` that
            owns the full convergence decision.
        observer: Observer mode — cut the trigger. Layers 1+2 still ran
            for real; this seam only records what it WOULD command
            (see :func:`_observe`).
        controller: The :class:`SurplusController` that owns the shared
            ``observer_decisions`` surface. Optional — bare callers keep
            the pure behavior.
    """
    # (#855) The cut is at the SEND, not here. Observer mode runs the whole
    # brand path and lets ``ControllableDevice.send`` withhold — that is what
    # makes ``withheld_commands`` name the exact service + payload, and it is
    # the entire point of the arc: #854's "stop" was a current write + an
    # energy target + an ENABLE, and the enable was INVISIBLE while the cut
    # sat above the adapter. Returning here left the withheld list empty on
    # every observer rig (found live on .46, 30.08.2026).
    #
    # ``_observe`` still publishes the DECISION surface (would_decisions);
    # the two are complements, not alternatives — one says what SEM decided,
    # the other what would have hit the wire.
    # (#1084) The decision log records in the reconciler's apply loop —
    # what is really written (or withheld by observer), not the decision. A
    # write the reconciler holds back makes no row. Hand it the log here,
    # the one place every charger cycle passes.
    _log = log_of(controller)
    if _log is not None:
        try:
            reconciler.decision_log = _log
        except Exception:  # noqa: BLE001 — a read-only stub is not a failure
            pass
    # (#1079) Another party steers this charger and the user said SEM
    # yields. Stamped on the device every cycle in BOTH directions, so the
    # send seam holds it back too; the reconciler is not run at all: it
    # would call a steered box's changes "drift" and fight them. Observer
    # mode, when on, still takes its own path below. Nothing is stopped or
    # started here, and the box's failsafe is left as it is.
    _ydev = getattr(adapter, "_device", None)
    _override = bool(phase_override) and yielded and not observer
    if _override:
        # (#1381) The fuse comes first: the guard's stop goes out even though
        # SEM yields. A safety stop, so the contactor's minimum ON time does
        # not hold it. The send seam lets only this cycle's stop through; the
        # failsafe stays unarmed, so the other party's session is not ended.
        decision = rewrite(decision, reason_code=RC.CHARGER_PHASE_STOP,
                           safety_stop=True, source="phase_guard", klass=1)
        log_on_change(
            _LOGGER, f"yield-override:ev:{decision.charger_id}",
            logging.WARNING,
            "phase guard overrides yield: %s — stopping %s. SEM will not "
            "restart it; the other party owns it",
            phase_override, decision.charger_id,
        )
    try:
        if _ydev is not None:
            try:
                _ydev.external_yield = bool(yielded) and not observer
                _ydev.phase_guard_override = _override
            except AttributeError:  # a frozen test double
                pass
        if _override:
            await reconciler.reconcile_and_apply(
                decision, adapter, power, time.monotonic())
            return
    finally:
        if _override and _ydev is not None:
            try:
                _ydev.phase_guard_override = False
            except AttributeError:
                pass
    if yielded and not observer:
        log_on_change(
            _LOGGER, f"yield:ev:{decision.charger_id}", logging.INFO,
            "YIELD · %s is steered by another party, SEM sends nothing "
            "(wanted %s: %s)", decision.charger_id, decision.intent.value,
            decision.reason,
        )
        return
    if observer:
        _observe(decision, adapter, controller=controller)
        # Belt and braces. Retiring the gate above means the seam in
        # ``ControllableDevice.send`` is now the ONLY thing between this
        # call and somebody's real charger — .46 and .175 are wired to a
        # real KEBA. ``send`` reads ``observer_mode`` with a getattr whose
        # documented default is False ("a device nobody told is a device
        # that acts"), and the flag arrives by a per-cycle push. Do not
        # depend on that push having reached THIS device: assert the flag
        # on the way past, at the last point that still knows.
        _dev = getattr(adapter, "_device", None)
        if _dev is not None:
            _dev.observer_mode = True
    await reconciler.reconcile_and_apply(decision, adapter, power, time.monotonic())
