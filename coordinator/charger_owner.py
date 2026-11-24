"""(#1381) The charger command owner — who asked a charger for what, and why.

The charger-owner map (docs/ARCHITECTURE.md, "Charger command owner") found
that SEM already has ONE hardware seam (``ControllableDevice.send``, #855)
and ONE decision per charger per cycle, but no owner of PRECEDENCE and no
record of what SEM changed and must hand back. Seven rewriters ran in a call
order nobody wrote down, and the phase guard's stop of a charger another
party steers was never undone (#1381: a car left off for 9 hours).

This module holds the three pieces that close that:

* ``CommandClass`` — the precedence table, highest first. Every rewrite of a
  charger decision says which class and which source made it
  (``ChargerDecision.klass`` / ``.source``).
* ``resolve`` — the per-charger chain (decide → VPP → plan override →
  stability/yield → phase guard → phase sequencer) as ONE call with a trail
  of who changed what. Same steps, same order: behaviour does not move.
* the ledger and hand-back — what SEM changed on a charger it does not
  steer, and the undo (``after_charger_cycle`` / ``fleet_step``).
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from enum import IntEnum
from typing import Any, Awaitable, Callable, Iterable, List, Sequence, Tuple, Union

_LOGGER = logging.getLogger(__name__)


class CommandClass(IntEnum):
    """Precedence of a claim on a charger, highest first (1 wins).

    ==  ================  ==================================================
    1   SAFETY            phase guard over-limit stop, peak EMERGENCY, VPP
                          grid event — goes out even when SEM yields; a stop
                          of a yielded charger leaves an undo in the ledger
    2   HARD_LIMIT        peak-slot clamp, max-SOC ceiling, car absent,
                          charger limits, phase-sequencer hold
    3   USER              mode Off, pause, Skip tonight, Start/Charge now
    4   EXTERNAL          another party steers ("SEM yields"): drops 5–7
    5   PLAN              night At-least, deadline, departure, tariff block
    6   SUN               surplus charging, battery help
    7   MAINTENANCE       resume press, phase start/return, heartbeat
    ==  ================  ==================================================

    ``0`` (unstated) is a decision nobody stamped: the plain mode decision.
    """
    UNSTATED = 0
    SAFETY = 1
    HARD_LIMIT = 2
    USER = 3
    EXTERNAL = 4
    PLAN = 5
    SUN = 6
    MAINTENANCE = 7


# Sources — one name per producer, so a reader never keys on a reason text.
SRC_DECIDE = "decide"
SRC_PEAK_EMERGENCY = "peak_emergency"
SRC_VPP_PAUSE = "vpp_pause"
SRC_PLAN_SKIP = "plan_skip"
SRC_PLAN_FORCE = "plan_force"
SRC_STABILITY = "stability"
SRC_YIELD = "yield"
SRC_PHASE_GUARD = "phase_guard"
SRC_PHASE_SEQUENCER = "phase_sequencer"
SRC_HAND_BACK = "hand_back"


def is_guard_stop(decision: Any) -> bool:
    """Is this the phase guard's own stop (not a clamp, not a hold)?"""
    from .charger_types import ChargerIntent
    return (getattr(decision, "source", "") == SRC_PHASE_GUARD
            and getattr(decision, "intent", None) is ChargerIntent.DISABLE)


# ---------------------------------------------------------------------------
# resolve — the chain as one call
# ---------------------------------------------------------------------------

StepFn = Callable[[Any], Union[Any, Awaitable[Any]]]
Step = Tuple[str, CommandClass, StepFn]


async def resolve(decision: Any, steps: Sequence[Step]) -> Tuple[Any, List[Tuple[str, bool]]]:
    """Run the per-charger rewriters in their order and keep a trail.

    ``steps``: ``(source, klass, fn)``; ``fn(decision)`` returns the next
    decision (sync or async). A step that returns a DIFFERENT decision and
    did not stamp its own source gets this step's source and class, so the
    final decision says who decided it. Returns ``(decision, trail)`` with
    ``trail = [(source, changed), ...]``.

    The order is the caller's: it is the precedence the code has always had
    (lowest first, the safety gate last, the sequencer after it because it
    only ever weakens a charge). Nothing here reorders, so behaviour is the
    same as the explicit chain it replaces.
    """
    trail: List[Tuple[str, bool]] = []
    for source, klass, fn in steps:
        before = decision
        out = fn(decision)
        if inspect.isawaitable(out):
            out = await out
        if out is None:
            out = before
        changed = out is not before and out != before
        # A step that rewrote the decision without naming itself is named
        # here; one that stamped its own (finer) source keeps it.
        if changed and getattr(out, "source", "") == getattr(before, "source", ""):
            out = stamp(out, source, klass)
        trail.append((source, bool(changed)))
        decision = out
    return decision, trail


def stamp(decision: Any, source: str, klass: CommandClass) -> Any:
    """Name the producer of a rewritten decision."""
    try:
        return replace(decision, source=source, klass=int(klass))
    except (TypeError, ValueError):
        return decision


def trail_text(trail: Iterable[Tuple[str, bool]]) -> str:
    return " → ".join(f"{s}{'*' if c else ''}" for s, c in trail)


def note_trail(coord: Any, cid: str, trail: List[Tuple[str, bool]]) -> None:
    """Keep this cycle's trail per charger (diagnostics, the decision log)."""
    book = getattr(coord, "_owner_trail", None)
    if not isinstance(book, dict):
        book = {}
        try:
            coord._owner_trail = book
        except AttributeError:
            return
    book[cid] = list(trail)


# ---------------------------------------------------------------------------
# The undo: hand back what SEM's safety stop changed on a charger it yields
# (S5). The policy (when the phase has room, back-off, Repair) lives in
# ``guard_hand_back``; its record comes from the device's command ledger.
# ---------------------------------------------------------------------------

def after_charger_cycle(coord: Any, cid: str, adapter: Any, power: Any,
                        stop_reason: str, *, yielded: bool, now: float) -> bool:
    """Per charger, after ``actuate``: note the facts the hand-back judges
    by, and turn this cycle's owed writes into the charger's record. True
    when the stored record changed (persist it)."""
    from . import guard_hand_back as ghb
    ghb.note_facts(coord, cid, power, yielded=yielded)
    if not stop_reason:
        return False
    return ghb.note_guard_stop(coord, cid, adapter, power, stop_reason, now=now)


async def fleet_step(coord: Any, *, now: float) -> bool:
    """Once per cycle, after every charger: at most one hand-back. True when
    the stored records changed."""
    from . import guard_hand_back as ghb
    return await ghb.run_step(coord, now=now)


def effective_state(coord: Any, cid: str, state: str) -> str:
    from . import guard_hand_back as ghb
    return ghb.effective_state(coord, cid, state)


def fleet_state(coord: Any, state: str) -> str:
    from . import guard_hand_back as ghb
    return ghb.fleet_state(coord, state)


def to_store(coord: Any) -> dict:
    from . import guard_hand_back as ghb
    return ghb.to_store(coord)


def from_store(coord: Any, blob: Any) -> None:
    from . import guard_hand_back as ghb
    ghb.from_store(coord, blob)
