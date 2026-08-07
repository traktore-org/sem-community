"""#638 G4 — actuation: the stamped overnight plan feeds the EXISTING signals.

The verification ladder's last rung (docs/OVERNIGHT_PLANNER.md): the plan's
blocks feed the EV's night amps and the loads' window gates. The reconcilers
do not change, and neither do the guarantees — every rule that DECIDES
whether something runs (deadline forcing, reserve SOC, peak shed, price
level, anti-cycle timers) stays with the reactive layer. Actuation only
narrows WHEN within the night, and only where the plan has proven itself
for that demand.

The trust rule, applied per demand, fail-open to today's behaviour:

    a demand follows its planned blocks ONLY when
      1. actuation is switched on (``switch.sem_overnight_actuation``,
         default off — the caller checks this before building a gate),
      2. tonight's plan is stamped and fresh (``computed_at`` within the
         night, ``now`` inside the plan's slot span),
      3. THIS demand's verdict is ``fits`` — a plan that could not place
         the full floor has nothing to promise, so the reactive layer
         keeps that demand entirely;
    anything else → :data:`UNCOVERED`, and every caller treats UNCOVERED
    as "behave exactly as before this module existed".

Pure: no clock reads, no I/O, no Home Assistant imports — ``now`` is always
passed in. The plan dict is the G3c stash (``_overnight_shadow_plan``):
``demands`` rows carry ``id``/``status``, ``blocks`` carry ``id``/``start``/
``end``/``power_w`` as ISO strings, ``slots`` span the night window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

# A stamped plan can never legitimately be older than one night. Anything
# beyond this is yesterday's plan surviving a missed restamp — do not act.
_MAX_PLAN_AGE = timedelta(hours=14)

_EPS_KWH = 1e-6


@dataclass(frozen=True)
class PlanGate:
    """One demand's actuation verdict against the stamped plan.

    ``covered`` is the trust switch: False means "the plan has no say over
    this demand" — the caller must change nothing. When True:
    ``in_block`` — ``now`` sits inside one of this demand's planned blocks;
    ``block_power_w`` — that block's planned power (0.0 outside a block);
    ``remaining_kwh`` — energy the blocks can still deliver from ``now``
    to their ends (the honest "can waiting still meet the floor" number).
    """
    covered: bool = False
    in_block: bool = False
    block_power_w: float = 0.0
    remaining_kwh: float = 0.0
    next_block_start: Optional[datetime] = None
    # (#638 Stage 2) When the NEXT of this demand's blocks opens — None
    # inside a block or when none remain. The verdict's ``until``, the
    # published reason's "(until HH:MM)" and the card countdown all quote
    # THIS instant, so the story the user reads is the instant the
    # decision actually used.


UNCOVERED = PlanGate()


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def plan_gate(plan: Optional[dict], demand_id: str, now: datetime) -> PlanGate:
    """Evaluate the trust rule for one demand id against the stamped plan.

    Returns :data:`UNCOVERED` on ANY doubt — a missing/malformed plan, a
    stale stamp, ``now`` outside the plan's own night span, the demand
    absent from the plan, or a verdict other than ``fits``. Naive/aware
    datetime mismatches (a test stash vs. a live ``dt_util.now()``) also
    resolve to UNCOVERED rather than raising: acting is opt-in, declining
    is always safe.
    """
    if not isinstance(plan, dict):
        return UNCOVERED
    try:
        computed = _parse_dt(plan.get("computed_at"))
        if computed is None or now - computed > _MAX_PLAN_AGE:
            return UNCOVERED
        slots = plan.get("slots") or []
        span_start = _parse_dt(slots[0].get("start")) if slots else None
        span_end = _parse_dt(slots[-1].get("end")) if slots else None
        if span_start is None or span_end is None:
            return UNCOVERED
        # The plan's authority begins at the STAMP, not at the first slot.
        # Slots start on the next full hour, so a 22:00:55 stamp opens a
        # 23:00 grid — and gating on the slot span alone left every demand
        # UNCOVERED for that sliver. Armed night 1: Heizband, block 23:00,
        # started reactively at 22:00:57 in exactly that gap while the card
        # already promised "WAITS · 23:00". A stamped, fresh plan has an
        # opinion about the whole night it was computed for.
        span_start = min(span_start, computed)
        if not (span_start <= now < span_end):
            return UNCOVERED
        row = next((r for r in plan.get("demands") or []
                    if r.get("id") == demand_id), None)
        if row is None or row.get("status") != "fits":
            return UNCOVERED

        in_block = False
        block_power = 0.0
        remaining = 0.0
        next_start = None
        for b in plan.get("blocks") or []:
            if b.get("id") != demand_id:
                continue
            start = _parse_dt(b.get("start"))
            end = _parse_dt(b.get("end"))
            power = float(b.get("power_w") or 0.0)
            if start is None or end is None or power <= 0.0:
                # ANY malformed block distrusts the whole demand: acting on
                # a partial view of its blocks (wrong remaining_kwh, wrong
                # membership) is worse than declining. Same direction as the
                # outer except — UNCOVERED, i.e. pre-G4 behaviour.
                return UNCOVERED
            if start <= now < end:
                in_block = True
                block_power = max(block_power, power)
            elif start > now and (next_start is None or start < next_start):
                next_start = start
            left_h = (end - max(start, now)).total_seconds() / 3600.0
            if left_h > 0:
                remaining += power / 1000.0 * left_h
        return PlanGate(covered=True, in_block=in_block,
                        block_power_w=block_power,
                        remaining_kwh=round(remaining, 6),
                        next_block_start=None if in_block else next_start)
    except (TypeError, ValueError, KeyError, IndexError):
        return UNCOVERED


def ev_overlay(
    gate: PlanGate,
    *,
    remaining_kwh: float,
    reachable: bool,
    deadline_active: bool,
    watts_per_amp: float,
    min_amps: int,
    max_amps: int,
) -> Tuple[bool, int]:
    """The EV's joint-plan overlay → ``(wait, floor_amps)``.

    Feeds the two signals the night path already consumes: ``wait`` maps
    onto ``NightChargePlan.should_wait_for_cheap`` (the existing
    TARIFF_WAITING state), ``floor_amps`` onto ``deadline_amps`` (the
    existing floor the decide layer clamps and peak-governs on top).

    The reactive guarantees outrank the plan, in order:
    - not ``covered`` → ``(False, 0)`` — nothing changes;
    - a forcing deadline (``deadline_active``) or an unreachable floor
      (``not reachable``) → ``(False, 0)`` — never hold back a charger
      the reactive planner says must run NOW;
    - inside a planned block → charge at least the planned power
      (ceil to amps, clamped to the charger's [min, max]);
    - outside a block → wait ONLY while the remaining blocks can still
      deliver the remaining floor; the moment they can't, fall back to
      reactive charging. Reality diverging from the plan (a slow charger,
      a shrunk block) therefore degrades to pre-G4 behaviour, never to a
      missed floor.
    """
    if not gate.covered:
        return (False, 0)
    if deadline_active or not reachable:
        return (False, 0)
    if gate.in_block:
        wpa = max(1.0, float(watts_per_amp))
        amps = int(math.ceil(gate.block_power_w / wpa))
        return (False, max(int(min_amps), min(int(max_amps), amps)))
    if gate.remaining_kwh + _EPS_KWH >= max(0.0, float(remaining_kwh)):
        return (True, 0)
    return (False, 0)


def load_window(gate: PlanGate) -> Optional[bool]:
    """The load-side window verdict: ``None`` = the plan has no say
    (behave as today), ``True`` = inside this load's planned block,
    ``False`` = the plan placed this load elsewhere tonight — don't
    start it now. Callers apply this ONLY as an extra AND-gate on the
    existing start conditions; it never creates a run reason."""
    if not gate.covered:
        return None
    return gate.in_block
