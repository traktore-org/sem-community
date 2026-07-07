"""Desired-vs-observed reconciliation for generic surplus devices (the "arc").

The EV charger has ``charger_reconciler.py``; generic on/off + climate loads had
no equivalent. ``SurplusController`` fires ``activate()``/``deactivate()`` and
trusts the device's internal belief (``is_active``), never reading back reality.
That let state drift silently:

* a ``turn_on`` that failed (entity unavailable) — SEM still believed ACTIVE and
  credited daily runtime to a load drawing nothing;
* a user or another automation toggling the load — SEM's belief and the real
  state diverged, and SEM would fight a manual on/off;
* no verification that the device followed a command.

This reconciler keeps SEM's belief in sync with observed reality each cycle,
**idempotently and additively** — it does NOT rewrite the tuned allocation loop.
It only:

1. corrects the belief when a SEM-active load is observed OFF past a grace
   window (accurate runtime accounting; no crediting a load that isn't drawing),
2. tracks whether SEM owns the on-state (it activated it) vs an external actor,
3. holds a short re-activate cooldown after an external OFF so SEM respects a
   user's manual turn-off instead of turning it straight back on.

Design notes:
* The grace window uses a MONOTONIC clock (``time.monotonic``) so a wall-clock
  jump can't spuriously fire; the cooldown uses wall-clock (it gates
  ``can_activate``, which is wall-clock throughout).
* "Observable" is decided by ``device.observed_on()`` — None means the entity is
  unavailable/unknown, and we leave the belief untouched rather than guess.
* Peak-only and off-mode devices are still reconciled for *belief accuracy* but
  the cooldown only matters to surplus-mode activation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# A SEM-believed-ON load must read OFF at the entity for this long before we
# correct the belief — rides out a transient poll gap / unavailable flicker.
# Tuned for local integrations (Z-Wave/Zigbee/local Shelly, <5s state updates).
# A slow *cloud* integration (30–60s poll) could still read "off" just after a
# successful turn_on and trip a correction; harmless (the load is on; belief
# flips idle, the cooldown holds, SEM re-activates after it) but costs the
# cooldown. Raise this if a cloud device flaps.
OFF_GRACE_S: float = 45.0

# After an external OFF (SEM-active load went off at the entity), don't
# re-activate for this long — respect a possible user turn-off.
EXTERNAL_OFF_COOLDOWN_S: int = 300


@dataclass
class ReconcileResult:
    """Outcome of one device reconciliation (telemetry / test surface)."""
    device_id: str
    action: str  # "none" | "unobservable" | "corrected_off" | "external_on"
    sem_owned: bool
    detail: str = ""


def reconcile_device(
    device,
    now_mono: Optional[float] = None,
    now_wall: Optional[datetime] = None,
) -> ReconcileResult:
    """Reconcile one device's belief with its observed state. Idempotent.

    Returns a :class:`ReconcileResult`. Side effects are limited to the device's
    own belief/ownership fields (never a service call — the reconciler observes
    and corrects, it does not actuate).
    """
    now_mono = time.monotonic() if now_mono is None else now_mono
    now_wall = datetime.now() if now_wall is None else now_wall

    obs = device.observed_on()
    if obs is None:
        # Can't read the entity — don't guess. Drop any pending drift anchor so a
        # later real OFF starts a fresh grace window.
        device._observed_off_since = None
        return ReconcileResult(device.device_id, "unobservable",
                               getattr(device, "_sem_owned", False))

    if device.is_active and obs is False:
        # Belief ON, entity OFF — start/continue the grace window.
        if device._observed_off_since is None:
            device._observed_off_since = now_mono
            return ReconcileResult(device.device_id, "none",
                                   device._sem_owned, "off-grace started")
        if now_mono - device._observed_off_since < OFF_GRACE_S:
            return ReconcileResult(device.device_id, "none",
                                   device._sem_owned, "off-grace pending")
        # Sustained OFF → the load really is off. Correct the belief without a
        # service call, and hold a re-activate cooldown (respect a user off).
        was_owned = device._sem_owned
        device.mark_reconciled_off(
            cooldown_until=now_wall + timedelta(seconds=EXTERNAL_OFF_COOLDOWN_S)
        )
        reason = ("SEM-active load is off (failed actuation or external off)"
                  if was_owned else "load off at the entity (external)")
        _LOGGER.info(
            "Reconcile %s: %s — belief → idle, %ds re-activate cooldown",
            device.name, reason, EXTERNAL_OFF_COOLDOWN_S,
        )
        return ReconcileResult(device.device_id, "corrected_off", False, reason)

    if not device.is_active and obs is True:
        # Entity ON, belief IDLE — an external actor (user/automation) turned it
        # on. Don't fight it; just record that SEM does not own this on-state.
        device._observed_off_since = None
        if device._sem_owned:
            device._sem_owned = False
        return ReconcileResult(device.device_id, "external_on", False,
                               "load on but SEM idle — not SEM-owned")

    # Converged (belief matches reality).
    device._observed_off_since = None
    return ReconcileResult(device.device_id, "none", device._sem_owned)


def reconcile_all(devices, now_mono: Optional[float] = None,
                  now_wall: Optional[datetime] = None) -> list[ReconcileResult]:
    """Reconcile a collection of devices; returns the per-device results.

    A single shared ``now`` keeps every device on the same clock for the cycle.
    """
    now_mono = time.monotonic() if now_mono is None else now_mono
    now_wall = datetime.now() if now_wall is None else now_wall
    out = []
    for dev in devices:
        try:
            out.append(reconcile_device(dev, now_mono, now_wall))
        except Exception as e:  # noqa: BLE001 — one bad device must not stall the cycle
            _LOGGER.debug("Reconcile skipped for %s: %s",
                          getattr(dev, "device_id", "?"), e)
    return out
