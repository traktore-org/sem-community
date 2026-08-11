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

# A stamped plan can never legitimately be older than one ENERGY DAY
# (night-end to night-end): since the horizon-spanning change a 07:30
# stamp is ~15 h old when its night blocks open, so the old 14 h cap
# silently un-covered every daytime-stamped night. Authority already
# ends at the plan's own SPAN; this cap is only the backstop against
# yesterday's plan surviving a span-parse quirk.
_MAX_PLAN_AGE = timedelta(hours=24)

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
    # (audit 2026-08-11) An uncovered gate NAMES its doubt. The fail-open
    # fallback used to be invisible — no artifact said whether a night was
    # plan-driven or legacy-driven. Covered gates carry no doubt ("").
    reason: str = ""


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
        return PlanGate(reason="no plan")
    try:
        computed = _parse_dt(plan.get("computed_at"))
        if computed is None or now - computed > _MAX_PLAN_AGE:
            return PlanGate(reason="stale stamp")
        slots = plan.get("slots") or []
        span_start = _parse_dt(slots[0].get("start")) if slots else None
        span_end = _parse_dt(slots[-1].get("end")) if slots else None
        if span_start is None or span_end is None:
            return PlanGate(reason="no span")
        # The plan's authority begins at the STAMP, not at the first slot.
        # Slots start on the next full hour, so a 22:00:55 stamp opens a
        # 23:00 grid — and gating on the slot span alone left every demand
        # UNCOVERED for that sliver. Armed night 1: Heizband, block 23:00,
        # started reactively at 22:00:57 in exactly that gap while the card
        # already promised "WAITS · 23:00". A stamped, fresh plan has an
        # opinion about the whole night it was computed for.
        span_start = min(span_start, computed)
        if not (span_start <= now < span_end):
            return PlanGate(reason="outside span")
        row = next((r for r in plan.get("demands") or []
                    if r.get("id") == demand_id), None)
        if row is None:
            return PlanGate(reason="not in plan")
        if row.get("status") != "fits":
            return PlanGate(reason=f"verdict {row.get('status')}")

        in_block = False
        block_power = 0.0
        remaining = 0.0
        next_start = None
        for b in plan.get("blocks") or []:
            if b.get("id") != demand_id:
                continue
            start = _parse_dt(b.get("start"))
            end = _parse_dt(b.get("end"))
            try:
                power = float(b.get("power_w") or 0.0)
            except (TypeError, ValueError):
                # Junk power_w is a malformed BLOCK, not an unreadable plan
                # — the reason must point at the row that broke trust.
                return PlanGate(reason="malformed block")
            if start is None or end is None or power <= 0.0:
                # ANY malformed block distrusts the whole demand: acting on
                # a partial view of its blocks (wrong remaining_kwh, wrong
                # membership) is worse than declining. Same direction as the
                # outer except — UNCOVERED, i.e. pre-G4 behaviour.
                return PlanGate(reason="malformed block")
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
        return PlanGate(reason="unreadable plan")


def coverage_transition(seen: dict, demand_id: str,
                        gate: PlanGate) -> Optional[str]:
    """The once-per-change log guard for the gate's verdict.

    ``seen`` is the caller's memory (demand_id → last (covered, reason)).
    Returns a log-ready line on first sight and on every change — including
    recovery to covered — and None on a repeat, so the 10-second cycle
    never floods a night's logs. The uncovered line says who decides,
    because the soak reads it to attribute the night to a layer.
    """
    state = (gate.covered, gate.reason)
    if seen.get(demand_id) == state:
        return None
    seen[demand_id] = state
    if gate.covered:
        return f"{demand_id}: plan COVERS — planned blocks drive the signals"
    return (f"{demand_id}: plan does not cover "
            f"({gate.reason or 'unknown'}) — the reactive layer decides alone")


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


def load_verdict(gate: PlanGate, *, deficit_kwh: float):
    """(#638 Stage 3) The load-side verdict, in the same PlanVerdict shape
    the EV decision consumes — loads graduate from a bare window bool to a
    hold that carries its reason and its ``until``.

    Same safety rule as ``ev_overlay``: a hold is only raised while the
    remaining blocks can still deliver the outstanding deficit. A plan
    that can no longer cover it has lost its authority over this load —
    NO_OPINION, the runtime guarantee falls back to the reactive layer.
    """
    from .plan_verdict import NO_OPINION, PlanVerdict
    if not gate.covered:
        return NO_OPINION
    if gate.in_block:
        return PlanVerdict(hold=False, in_block=True,
                           reason="joint overnight plan: in planned block")
    if gate.remaining_kwh + _EPS_KWH < deficit_kwh:
        return NO_OPINION
    when = (f" — block opens at {gate.next_block_start:%H:%M}"
            if gate.next_block_start else "")
    return PlanVerdict(
        hold=True,
        until=gate.next_block_start,
        reason=f"joint overnight plan: outside the planned window{when}",
    )


def merge_load_gates(load_gate: PlanGate, comfort_gate: PlanGate,
                     *, deficit_kwh: float):
    """(#638 C5) One device, two demands — the merged verdict.

    A device carries its runtime deficit (``load:``) and its comfort
    banking ask (``comfort:``). Either demand in-block → a run verdict;
    a hold only when EVERY covered demand holds (a demand whose verdict
    failed open keeps its reactive layer); the earliest block start wins
    ``until``. ``None`` = the plan has no say over this device.
    """
    from .plan_verdict import PlanVerdict
    covered = [g for g in (load_gate, comfort_gate) if g.covered]
    if not covered:
        return None
    if any(g.in_block for g in covered):
        return PlanVerdict(in_block=True,
                           reason="joint overnight plan: in planned block")
    holds = []
    if load_gate.covered:
        lv = load_verdict(load_gate, deficit_kwh=deficit_kwh)
        if not lv.hold:
            # The load half failed open — no hold may stand over the
            # device's reactive deficit run.
            return None
        holds.append(lv)
    if comfort_gate.covered:
        holds.append(PlanVerdict(
            hold=True, until=comfort_gate.next_block_start,
            reason="joint overnight plan: comfort block later"))
    if not holds:
        return None
    untils = [h.until for h in holds if h.until is not None]
    return PlanVerdict(hold=True,
                       until=min(untils) if untils else None,
                       reason=holds[0].reason)


def arbitrage_sell_gate(plan, now: datetime) -> Tuple[bool, float]:
    """(#638 C6) The plan's WHEN for the arbitrage SELL.

    Reads the stamped plan's ``arbitrage.discharge_blocks`` under the same
    trust discipline as :func:`plan_gate` — fresh stamp, well-formed rows,
    decline on any doubt. Returns ``(in_block, power_w)`` where power is
    the BLOCK-IMPLIED watts (kwh over the block's hours): the advisor
    bounded delivery by the home's own grid draw, so this keeps the sell
    an avoided-import delivery, never an export-at-max. The live
    economics (``evaluate_arbitrage``) stay the WHETHER; the per-battery
    mode gates stay the MAY — this function only answers WHEN.
    """
    closed = (False, 0.0)
    if not isinstance(plan, dict):
        return closed
    try:
        computed = _parse_dt(plan.get("computed_at"))
        if computed is None or now - computed > _MAX_PLAN_AGE:
            return closed
        arb = plan.get("arbitrage")
        if not isinstance(arb, dict):
            return closed
        for b in arb.get("discharge_blocks") or []:
            start = _parse_dt(b.get("start"))
            end = _parse_dt(b.get("end"))
            try:
                kwh = float(b.get("kwh") or 0.0)
            except (TypeError, ValueError):
                return closed
            if start is None or end is None or kwh <= 0.0:
                return closed
            if start <= now < end:
                hours = (end - start).total_seconds() / 3600.0
                if hours <= 0:
                    return closed
                return (True, kwh / hours * 1000.0)
        return closed
    except (TypeError, ValueError, KeyError):
        return closed
