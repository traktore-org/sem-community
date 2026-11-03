"""(#1303) The one place that says which grid-sign rule wins.

``SensorReader`` learns a sign in several places (restore, brand seed,
meter model, solar co-movement, counter vote, the balance self-heal). What
the read APPLIES each cycle is decided here, from a snapshot of that state,
in the order of ``PRECEDENCE``. Nothing in this module reads Home Assistant.

Read order (first match wins for the base sign):

1. ``option``  — ``grid_sign_invert`` is set: negate; no detection runs (#352).
2. ``pair``    — the grid is read as export minus import: nothing to negate,
                 no lock applies (#1215).
3. ``model``   — one meter whose model fixes its sign (a P1 meter): that
                 sign, over any lock (#1294).
4. ``lock``    — the learned or restored lock, when one is set.
5. ``none``    — no lock: the flag as it stands (False on a fresh reader).

Then the one-tap flip turns the base around when it is bound to the source
read now (#971, #1192) and was not tapped against an old lock on a meter
whose model sets the sign (#1294). It applies on top of the option too (#461).

Who may WRITE the lock, in the order they get to, is ``LOCK_WRITERS``; the
writers stay in ``SensorReader`` and the coordinator, this is the spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PRECEDENCE = ("option", "pair", "model", "lock", "none")

LOCK_WRITERS = (
    "restore (startup, a saved lock)",
    "model (every cycle, over any lock)",
    "seed (once, while nothing is locked)",
    "solar (sets while unlocked; overrides a lock on a strong, sustained disagreement)",
    "counter vote (while unlocked)",
    "balance self-heal (coordinator; not with a user override, a pair or a model)",
)


@dataclass(frozen=True)
class GridSignEvidence:
    option_invert: bool
    read_is_pair: bool
    model_fixed: Optional[bool]
    lock_detected: bool
    lock_inverted: bool
    flip_bound_here: bool
    flip_on_old_lock: bool


@dataclass(frozen=True)
class GridSignDecision:
    base_negate: bool
    flip: bool
    source: str
    why: str

    @property
    def negate(self) -> bool:
        return self.base_negate != self.flip


def lock_base(ev: GridSignEvidence) -> tuple[bool, str, str]:
    """Steps 2-5: what the detectors' state says, the option left aside."""
    if ev.read_is_pair:
        return False, "pair", "a pair sets its own sign; no lock applies"
    if ev.model_fixed is not None:
        return ev.model_fixed, "model", "the meter's model sets the sign"
    if ev.lock_detected:
        return ev.lock_inverted, "lock", "the learned lock"
    # The flag as it stands: False on a fresh reader. A writer that sets it
    # without locking (the self-heal's put-back) is still applied, as before.
    return ev.lock_inverted, "none", "no lock yet; the flag as it stands"


def flip_applies(ev: GridSignEvidence) -> bool:
    return ev.flip_bound_here and not ev.flip_on_old_lock


def grid_sign_decision(ev: GridSignEvidence) -> GridSignDecision:
    if ev.option_invert:
        base, source, why = True, "option", "grid_sign_invert is set"
    else:
        base, source, why = lock_base(ev)
    return GridSignDecision(base_negate=base, flip=flip_applies(ev),
                            source=source, why=why)
