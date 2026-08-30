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
from .charger_types import ChargerDecision, ChargerPower, commanded_power_w
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
    if observer:
        _observe(decision, adapter, controller=controller)
    await reconciler.reconcile_and_apply(decision, adapter, power, time.monotonic())
