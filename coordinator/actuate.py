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
from .charger_types import ChargerDecision, ChargerPower

_LOGGER = logging.getLogger(__name__)


async def actuate(
    decision: ChargerDecision,
    adapter: ChargerAdapter,
    power: ChargerPower,
    reconciler,
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
    """
    await reconciler.reconcile_and_apply(decision, adapter, power, time.monotonic())
