"""#638 G4 — actuation: the stamped energy plan feeds the EXISTING signals.

The verification ladder's last rung (docs/ENERGY_PLANNER.md): the plan's
blocks feed the EV's night amps and the loads' window gates. The reconcilers
do not change, and neither do the guarantees — every rule that DECIDES
whether something runs (deadline forcing, reserve SOC, peak shed, price
level, anti-cycle timers) stays with the reactive layer. Actuation only
narrows WHEN within the night, and only where the plan has proven itself
for that demand.

The trust rule, applied per demand, fail-open to today's behaviour:

    a demand follows its planned blocks ONLY when
      1. actuation is switched on (``switch.sem_energy_plan_actuation``,
         default off — the caller checks this before building a gate),
      2. tonight's plan is stamped and fresh (``computed_at`` within the
         night, ``now`` inside the plan's slot span),
      3. THIS demand's verdict is ``fits`` — a plan that could not place
         the full floor has nothing to promise, so the reactive layer
         keeps that demand entirely;
    anything else → :data:`UNCOVERED`, and every caller treats UNCOVERED
    as "behave exactly as before this module existed".

Pure: no clock reads, no I/O, no Home Assistant imports — ``now`` is always
passed in. The plan dict is the G3c stash (``_energy_plan_shadow``):
``demands`` rows carry ``id``/``status``, ``blocks`` carry ``id``/``start``/
``end``/``power_w`` as ISO strings, ``slots`` span the night window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from .energy_planner import FIT_EPS

# A stamped plan can never legitimately be older than one ENERGY DAY
# (night-end to night-end): since the horizon-spanning change a 07:30
# stamp is ~15 h old when its night blocks open, so the old 14 h cap
# silently un-covered every daytime-stamped night. Authority already
# ends at the plan's own SPAN; this cap is only the backstop against
# yesterday's plan surviving a span-parse quirk.
_MAX_PLAN_AGE = timedelta(hours=24)

_EPS_KWH = 1e-6


def blocks_hold(have: float, need: float) -> bool:
    """(#1289) Do the blocks still hold the need? The same share the planner
    calls "fits" (``FIT_EPS``); a tighter wait ended it for a plan the
    planner had just passed."""
    return have + _EPS_KWH >= max(0.0, float(need)) * FIT_EPS


@dataclass(frozen=True)
class PlanGate:
    """One demand's actuation verdict against the stamped plan.

    ``covered`` is the trust switch: False means "the plan has no say over
    this demand" — the caller must change nothing. When True:
    ``in_block`` — ``now`` sits inside one of this demand's planned blocks;
    ``block_power_w`` — that block's planned power in whole watts, the
    setpoint it asks for (0.0 outside a block);
    ``remaining_kwh`` — energy the blocks can still deliver from ``now``
    to their ends (the honest "can waiting still meet the floor" number),
    from the plan's exact watts: it is compared with the exact need
    (#1282).
    """
    covered: bool = False
    in_block: bool = False
    block_power_w: float = 0.0
    remaining_kwh: float = 0.0
    # (#1290) The same blocks in hours: a load's wait counts runtime, so it
    # needs no rating of its own.
    remaining_h: float = 0.0
    next_block_start: Optional[datetime] = None
    # (#1415) The highest power among this demand's blocks still ahead
    # (0.0 when none). The packer books no block above the headroom the
    # peak limit leaves, so the car cannot count on more. Not the lowest:
    # the last block often holds only the rest, at lower power.
    top_block_w: float = 0.0
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


def plan_blocks(allocations) -> list:
    """The stamped ``blocks`` rows, in the ONE shape ``plan_gate`` reads.

    ``power_w`` keeps its precision: the gate rebuilds deliverable kWh from
    it and compares with the unrounded need. Whole watts turned a complete
    plan into a 0.4 Wh shortage (#1282). Rounding is for the card.
    """
    return [{
        "id": a.demand_id,
        "start": a.start.isoformat(),
        "end": a.end.isoformat(),
        "power_w": a.power_w,
        "price": a.price,
        # (#1023) only on the top-up: the strip hatches it
        **({"late": True} if a.late else {}),
        # (#1321) why the packer put it here; the card says it in words
        **({"reason": a.code} if getattr(a, "code", "") else {}),
        **({"reason_params": dict(a.params)}
           if getattr(a, "code", "") and a.params else {}),
    } for a in allocations]


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
        # A DELIBERATELY empty plan is not an unreadable one. The quiet
        # 22:00 answer ("nothing needs the night") publishes demands, slots
        # and blocks as empty lists on purpose; falling through to the span
        # check made every demand answer "no span", which the card has no
        # sentence for — so the user read "the plan is unreadable" on a
        # night when the plan was perfectly readable and had nothing to do.
        # Uncovered either way; only the reason is honest now.
        # (15.08) The quiet regime is the empty DEMAND list, nothing else.
        # This once also required empty ``slots`` — true only while the
        # quiet plan published no ledger. The moment it published the
        # hours it judged, the discriminator stopped matching and every
        # device read ``not in plan``: the sentence for "the plan left YOU
        # out", on a night the plan left everyone out on purpose. Slots
        # are the books; demands are the schedule.
        if not (plan.get("demands") or []):
            return PlanGate(reason="nothing planned")
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
        remaining_h = 0.0
        top_block = 0.0
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
            # (#1282) A setpoint goes out in whole watts, as before; only
            # the energy sum below needs the plan's exact watts. A block
            # under half a watt (a float rest the packer placed) asks for
            # no power, so it is no block to run in: the battery reads a
            # 0 W block as "no cap" and would charge at full power. Its
            # energy still counts below.
            setpoint = round(power, 0)
            if start <= now < end and setpoint > 0.0:
                in_block = True
                block_power = max(block_power, setpoint)
            elif start > now and (next_start is None or start < next_start):
                next_start = start
            left_h = (end - max(start, now)).total_seconds() / 3600.0
            if left_h > 0:
                remaining += power / 1000.0 * left_h
                remaining_h += left_h
                # (#1415) a sub-watt rest asks for no power: not a rate
                if setpoint > 0.0:
                    top_block = max(top_block, power)
        return PlanGate(covered=True, in_block=in_block,
                        block_power_w=block_power,
                        remaining_kwh=round(remaining, 6),
                        remaining_h=round(remaining_h, 6),
                        next_block_start=None if in_block else next_start,
                        top_block_w=top_block)
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
    wpa_table=None,
    nominal_wpa=None,
    departure_floor: bool = False,
    charge_end: Optional[datetime] = None,
    departure_max_amps: Optional[int] = None,
    departure_wpa_table=None,
    departure_wpa: Optional[float] = None,
) -> Tuple[bool, int]:
    """The EV's joint-plan overlay → ``(wait, floor_amps)``.

    Callers use :func:`apply_ev_overlay`, which reads every flag below off
    the night plan in one place.

    ``wpa_table`` (#904): this charger's learned ``{amps: W/A}`` ladder.
    With it, block watts become the LARGEST setpoint whose predicted draw
    fits the block — the same walk the slot guard makes — never a division
    by one bucket's W/A. PROD 02.09: 5262 W ÷ the 16 A bucket's 389 W/A
    asked 14 A, which that very table says buys 8.7 kW; the ladder says
    10 A. Without a table the nameplate ceil stays as it was.

    Feeds the two signals the night path already consumes: ``wait`` maps
    onto ``NightChargePlan.should_wait_for_cheap`` (the existing
    TARIFF_WAITING state), ``floor_amps`` onto ``deadline_amps`` (the
    existing floor the decide layer clamps and peak-governs on top).

    The reactive guarantees outrank the plan, in order:
    - not ``covered`` → ``(False, 0)`` — nothing changes;
    - a forcing deadline (``deadline_active``) or an unreachable floor
      (``not reachable``) → ``(False, 0)`` — never hold back a charger
      the reactive planner says must run NOW;
    - (#1415) except the *Finish by departure* floor after the night end
      (``departure_floor``, the plan's ``to_departure``). That floor only
      spreads the need evenly up to the departure (``charge_end``), and
      the joint plan packed the same departure into its cheapest hours.
      So the blocks lead, under the two rules below, and one more for the
      wait: see :func:`departure_wait_is_safe` (``departure_max_amps``:
      the charger max the night plan used, when lower). The wait counts
      with the floor's own power model, ``departure_wpa_table`` and
      ``departure_wpa`` (the plan's ``wpa_table`` and ``watts_per_amp``):
      the floor is what charges when a wait fails. An unreachable floor
      still releases.
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
    if (deadline_active and not departure_floor) or not reachable:
        return (False, 0)
    if gate.in_block:
        wpa = max(1.0, float(watts_per_amp))
        if wpa_table:
            from .watts_per_amp import amps_that_fit
            # The ladder's ceiling is the NAMEPLATE (phases × voltage), never
            # the single measured number — predict_watts caps at ``a × nominal``,
            # and a low bucket's W/A as the cap would walk the ladder wrong.
            nominal = float(nominal_wpa) if nominal_wpa else wpa
            amps = amps_that_fit(wpa_table, gate.block_power_w, max(1.0, nominal),
                                 int(max_amps))
        else:
            amps = int(math.ceil(gate.block_power_w / wpa))
        return (False, max(int(min_amps), min(int(max_amps), amps)))
    if blocks_hold(gate.remaining_kwh, remaining_kwh):
        if departure_floor and not departure_wait_is_safe(
                gate, remaining_kwh, charge_end,
                wpa_table=departure_wpa_table,
                nominal_wpa=departure_wpa or watts_per_amp,
                max_amps=min(int(max_amps),
                             int(departure_max_amps or max_amps))):
            return (False, 0)
        return (True, 0)
    return (False, 0)


#: (#1415) Share of the car's known draw the even floor may count on after a
#: wait. A start takes minutes (a cloud charger answers late), and a car
#: can draw less than its best, cold or near full. Replayed minute by minute
#: on the reporter's day, a car at 80 % of its measured draw still lands
#: as well as with the floor that never waited.
DEPARTURE_WAIT_MARGIN = 0.8


def departure_wait_is_safe(gate: PlanGate, need_kwh: float,
                           charge_end: Optional[datetime], *,
                           wpa_table, nominal_wpa: float,
                           max_amps: int) -> bool:
    """(#1415) May the car wait for its next block before the departure?

    At night a failed plan still has the hours after the night end; with
    *Finish by departure* the departure is the hard end, and nothing
    charges after it. ``blocks_hold`` trusts the plan's power, and above
    the highest setpoint SEM has measured that is the nameplate: the
    reporter's 54 A read as 37 kW for a car that drew 7.5 kW at 12 A. A
    plan like that fails at its first block, and only the hours from there
    to the departure are left.

    So the wait is safe only while the even floor could still deliver the
    need from the next block's start, at the most this car has been SEEN
    to draw at or under ``max_amps`` (the measured table), less a margin
    for the start. No measured table: no proof, no wait.

    The peak limit caps that rate too (review): the packer put each block
    within the headroom the limit leaves, and the slot guard holds the
    car there. So the rate is never above what the highest block still
    ahead (``top_block_w``) buys at its setpoint. A 5 kW limit with 700 W
    of house load gives 4.3 kW blocks; the 10.6 kW the car was seen at is
    not there to use.

    Review 3: the rate is a MEASURED setpoint, the highest at or under the
    one the block runs at. Below the measured range ``predict_watts`` is
    the nameplate, and a car can draw far less there: 415 W/A at 8 A on
    PROD, 0.6 of nameplate. The reporter's table starts at 12 A, so a
    4.3 kW block (6 A) has no measured rate under it: no proof, no wait.
    """
    if gate.next_block_start is None or charge_end is None:
        return False
    try:
        hours = (charge_end - gate.next_block_start).total_seconds() / 3600.0
    except TypeError:      # naive vs aware: no proof
        return False
    if hours <= 0.0:
        return False
    seen = [int(a) for a in (wpa_table or {}) if 0 < int(a) <= int(max_amps)]
    if not seen:
        return False
    from .watts_per_amp import amps_that_fit, predict_watts
    nominal = max(1.0, float(nominal_wpa))
    block_amps = int(max_amps)
    if gate.top_block_w > 0.0:
        # The setpoint the block runs at: the in-block floor's own walk.
        block_amps = amps_that_fit(wpa_table, gate.top_block_w, nominal,
                                   int(max_amps))
    under = [a for a in seen if a <= block_amps]
    if not under:
        return False
    # a measured bucket: ``predict_watts`` returns its own draw, never
    # above the nameplate
    top_w = predict_watts(wpa_table, max(under), nominal)
    return (max(0.0, float(need_kwh))
            <= top_w / 1000.0 * hours * DEPARTURE_WAIT_MARGIN)


def apply_ev_overlay(plan, gate: PlanGate, *, remaining_kwh: float,
                     watts_per_amp: float, min_amps: int, max_amps: int,
                     wpa_table=None, nominal_wpa=None) -> Tuple[bool, int]:
    """(#638 G4) The overlay, written onto this charger's night plan.

    The ONE copy both coordinator sites call (primary and per charger,
    the #683/#684 parity class). It reads ``reachable``,
    ``deadline_active``, ``to_departure``, ``charge_end_dt``, ``max_amps``,
    ``wpa_table`` and ``watts_per_amp`` off the same plan it writes, so no
    site can pass one flag and forget another (#1415). ``wpa_table`` and
    ``nominal_wpa`` here are the charger's phases NOW, for the in-block
    floor. Returns ``(wait, floor_amps)``.
    """
    wait, floor = ev_overlay(
        gate,
        remaining_kwh=remaining_kwh,
        reachable=plan.reachable,
        deadline_active=plan.deadline_active,
        departure_floor=bool(getattr(plan, "to_departure", False)),
        charge_end=getattr(plan, "charge_end_dt", None),
        # the plan's max is the charger's own when it is below the config's
        departure_max_amps=int(getattr(plan, "max_amps", 0) or 0) or None,
        # (review 3) the floor's own power model: the table measured on
        # the phases the plan runs on, and its nameplate W/A
        departure_wpa_table=getattr(plan, "wpa_table", None),
        departure_wpa=float(getattr(plan, "watts_per_amp", 0.0) or 0.0) or None,
        watts_per_amp=watts_per_amp,
        min_amps=min_amps,
        max_amps=max_amps,
        wpa_table=wpa_table,
        nominal_wpa=nominal_wpa,
    )
    if wait:
        plan.should_wait_for_cheap = True
        plan.next_cheap_start = gate.next_block_start
        # CAUSE: ``wait`` is ev_overlay's answer for this gate: not in a
        # block, and blocks_hold says the remaining blocks hold the need.
        plan.reason = (
            "joint energy plan: outside the planned window — waiting "
            f"({gate.remaining_kwh:.1f} kWh still deliverable)")
    elif floor > 0:
        plan.should_wait_for_cheap = False
        plan.deadline_amps = max(plan.deadline_amps, floor)
        plan.reason = f"joint energy plan: in planned window — floor {floor}A"
    return (wait, floor)


def load_verdict(gate: PlanGate, *, deficit_kwh: float,
                 deficit_h: Optional[float] = None):
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
                           reason="joint energy plan: in planned block")
    # (#1290) With the deficit in hours, compare hours: the plan sized the
    # blocks with the rating of planning time, the rating now may be higher.
    if deficit_h is not None:
        if not blocks_hold(gate.remaining_h, deficit_h):
            return NO_OPINION
    elif not blocks_hold(gate.remaining_kwh, deficit_kwh):
        return NO_OPINION
    when = (f" — block opens at {gate.next_block_start:%H:%M}"
            if gate.next_block_start else "")
    return PlanVerdict(
        hold=True,
        until=gate.next_block_start,
        reason=f"joint energy plan: outside the planned window{when}",
    )


def merge_load_gates(load_gate: PlanGate, comfort_gate: PlanGate,
                     *, deficit_kwh: float,
                     deficit_h: Optional[float] = None):
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
        # (#1102) which block is open stays readable: only the comfort
        # block may start a banking run.
        return PlanVerdict(in_block=True,
                           comfort_in_block=bool(comfort_gate.covered
                                                 and comfort_gate.in_block),
                           reason="joint energy plan: in planned block")
    holds = []
    if load_gate.covered:
        lv = load_verdict(load_gate, deficit_kwh=deficit_kwh,
                          deficit_h=deficit_h)
        if not lv.hold:
            # The load half failed open — no hold may stand over the
            # device's reactive deficit run.
            return None
        holds.append(lv)
    if comfort_gate.covered:
        holds.append(PlanVerdict(
            hold=True, until=comfort_gate.next_block_start,
            reason="joint energy plan: comfort block later"))
    if not holds:
        return None
    untils = [h.until for h in holds if h.until is not None]
    return PlanVerdict(hold=True,
                       until=min(untils) if untils else None,
                       reason=holds[0].reason)


def _now_in_plan_span(plan: dict, computed: datetime, now: datetime) -> bool:
    """(#1272) ``now`` is inside the hours the plan was built for.

    The same span rule as :func:`plan_gate`: the plan's authority runs from
    its stamp (or its first slot, if earlier) to the end of its last slot.
    A plan stamped after midnight ends at sunrise, so a sale block it
    carries for that evening is not its to start. No readable span = no.
    """
    slots = plan.get("slots") or []
    if not slots:
        return False
    start = _parse_dt(slots[0].get("start"))
    end = _parse_dt(slots[-1].get("end"))
    if start is None or end is None:
        return False
    return min(start, computed) <= now < end


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
        if not _now_in_plan_span(plan, computed, now):
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


def forecast_sell_gate(plan, now: datetime) -> Tuple[bool, float]:
    """(#778) The plan's WHEN for the forecast-led SPEND.

    ``arbitrage_sell_gate``'s twin over ``plan["forecast_sell"].blocks`` —
    same trust discipline (fresh stamp, well-formed rows, decline on any
    doubt), same return shape ``(in_block, block-implied watts)``. Kept a
    separate gate on purpose: the two features have different master
    switches, and one gate answering for both would let either switch open
    the other's valve.
    """
    closed = (False, 0.0)
    if not isinstance(plan, dict):
        return closed
    try:
        computed = _parse_dt(plan.get("computed_at"))
        if computed is None or now - computed > _MAX_PLAN_AGE:
            return closed
        fs = plan.get("forecast_sell")
        if not isinstance(fs, dict):
            return closed
        if not _now_in_plan_span(plan, computed, now):
            return closed
        for b in fs.get("blocks") or []:
            start = _parse_dt(b.get("start"))
            bend = _parse_dt(b.get("end"))
            try:
                kwh = float(b.get("kwh") or 0.0)
            except (TypeError, ValueError):
                return closed
            if start is None or bend is None or kwh <= 0.0:
                return closed
            if start <= now < bend:
                hours = (bend - start).total_seconds() / 3600.0
                if hours <= 0:
                    return closed
                return (True, kwh / hours * 1000.0)
        return closed
    except (TypeError, ValueError, KeyError):
        return closed

