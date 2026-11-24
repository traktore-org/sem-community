"""(#1381) Hand a charger back after the phase guard's safety stop.

A charger another party steers ("SEM yields") is stopped by the phase guard
when a phase goes over its limit (``actuate``'s yield override). Before this
module nothing switched it on again: SEM yields, and the other party did not
know SEM had stopped it. A two-minute overload at 16:43 left a car at 12 %
at 02:00 with an 08:00 deadline.

The rule here: SEM undoes its OWN stop, and nothing more.

* At the stop, the send seam's command ledger (charger owner S4) records
  each write it let through with the entity's state just before, marked as
  owed. This module takes the owed entries (``take_owed``) and turns them
  into a record per charger: what SEM changed, how to undo it, the draw the
  charger had, and when. The record is persisted with the EV session state,
  so an HA restart in between does not lose it.
* Hand back = the inverse of exactly those commands (a switch SEM turned off
  is turned on; a number SEM set is set back; a select back to its option).
  A command that cannot be inverted is never guessed at: the user is told the
  charger was left off.
* Only when the guard is armed again and every monitored phase has room for
  the charger's draw before the stop plus the guard's own recovery margin.
  The draw, not the charger's minimum: the other party chooses the current,
  so the draw it had is what it will take again.
* One charger per cycle, highest priority first, and a pause between two
  hand-backs so the meter shows the first one's draw before the next is
  judged.
* Dropped without acting when the car is known to be gone, when the other
  party (or the user) changed an entity SEM touched, or when SEM steers the
  charger itself again (its own reconciler converges then).
* If the guard stops the same charger again within ``RETRIP_WINDOW_S`` of a
  hand-back, the next try waits longer (``BACKOFF_S``); after
  ``MAX_FAILURES`` such re-trips SEM stops trying and raises a Repair that
  names the charger.

Pure functions plus one small async executor; the coordinator wires them.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .active_phase_guard import DEFAULT_RECOVERY_MARGIN_A

_LOGGER = logging.getLogger(__name__)

#: A re-stop within this time after a hand-back counts as the hand-back
#: having failed (the overload came straight back).
RETRIP_WINDOW_S = 15 * 60
#: Wait before the 1st, 2nd and 3rd retry after a failed hand-back.
BACKOFF_S = (10 * 60, 20 * 60, 40 * 60)
#: Failed hand-backs before SEM gives up and tells the user: every wait in
#: BACKOFF_S is used, the next failure leaves the charger off with a Repair.
MAX_FAILURES = len(BACKOFF_S) + 1
#: After the stop, the entity may still read its old state for a while (the
#: write is not shown yet, or the integration polls). Within this time that
#: is not "somebody changed it" (found by the pipeline replay, #1381).
STOP_SETTLE_S = 120
#: After a hand-back the charger must draw, or read back what SEM restored,
#: within this time; otherwise the hand-back counts as failed.
READBACK_S = 5 * 60
#: A record older than this is not handed back any more: after half a day
#: SEM cannot tell its own stop from somebody's later wish (a Repair says so).
MAX_AGE_S = 12 * 60 * 60
#: Between two hand-backs (any chargers): the meter must show the first.
BETWEEN_HAND_BACKS_S = 120
#: In observer mode the would-be hand-back is shown at most this often.
OBSERVER_REPEAT_S = 600

_SWITCH_DOMAINS = ("switch", "input_boolean")
_NUMBER_DOMAINS = ("number", "input_number")
_SELECT_DOMAINS = ("select", "input_select")
_DEAD = ("unknown", "unavailable", "", None)


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def inverse_of(sent: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The command that undoes ``sent``, or None when it cannot be undone.

    ``sent`` is one owed entry of the device's command ledger: domain, service, data and
    ``prior`` (the entity's state just before). The result carries the
    command and ``left`` — the state SEM left the entity in, which is how a
    later change by somebody else is recognised.
    """
    domain = str(sent.get("domain") or "")
    service = str(sent.get("service") or "")
    data = dict(sent.get("data") or {})
    entity = data.get("entity_id")
    prior = sent.get("prior")
    # Not handed back, on purpose (#1381 review F6): a stop sent as a brand
    # SERVICE without an entity (e.g. a wallbox "disable") or a BUTTON press
    # has no state to read back and no safe inverse — a brand "enable" on a
    # box another party steers can start a stop war (#1163), and SEM never
    # sends an authorize. Such a stop leaves the charger off with a Repair.
    if not isinstance(entity, str) or not entity or prior in _DEAD:
        return None
    if domain in _SWITCH_DOMAINS and service == "turn_off":
        if prior != "on":
            return {"noop": True}     # it was already off: SEM changed nothing
        return {"domain": domain, "service": "turn_on",
                "data": {"entity_id": entity}, "entity_id": entity,
                "left": "off", "target": "on"}
    if domain in _NUMBER_DOMAINS and service == "set_value":
        before, after = _f(prior), _f(data.get("value"))
        if before is None or after is None:
            return None
        if abs(before - after) < 1e-6:
            return {"noop": True}
        return {"domain": domain, "service": "set_value",
                "data": {"entity_id": entity, "value": before},
                "entity_id": entity, "left": after, "target": before}
    if domain in _SELECT_DOMAINS and service == "select_option":
        after = data.get("option")
        if not isinstance(after, str):
            return None
        if after == prior:
            return {"noop": True}
        return {"domain": domain, "service": "select_option",
                "data": {"entity_id": entity, "option": prior},
                "entity_id": entity, "left": after, "target": prior}
    return None


def build_record(sent: Iterable[Mapping[str, Any]], *, now: float,
                 reason: str, draw_w: float, phases: int, voltage: float,
                 min_current_a: float) -> Optional[Dict[str, Any]]:
    """A hand-back record from the commands the stop let through, or None
    when the stop changed nothing. ``undoable`` is False when one of the
    commands has no safe inverse."""
    restores: List[Dict[str, Any]] = []
    undoable = True
    changed = False
    for cmd in sent or ():
        if str(cmd.get("service") or "") == "set_failsafe":
            continue   # keeps the box's own safety net; steers nothing
        inv = inverse_of(cmd)
        if inv is None:
            undoable = False
            changed = True
            continue
        if inv.get("noop"):
            continue
        changed = True
        restores.append(inv)
    if not changed:
        return None
    phases = max(1, int(phases or 1))
    volt = float(voltage or 230.0) or 230.0
    draw_a = max(0.0, float(draw_w or 0.0)) / (phases * volt)
    return {
        "restores": restores,
        "undoable": bool(undoable and restores),
        "stopped_at": float(now),
        "reason": str(reason or ""),
        "draw_a": round(max(draw_a, float(min_current_a or 0.0)), 2),
        "phases": phases,
        "failures": 0,
        "next_try_at": 0.0,
        "handed_back_at": 0.0,
        "left_off": False,
        # restores already sent (SEM's own state, never "changed by other")
        "done": [],
        "confirmed": False,
    }


def note_failure(rec: Dict[str, Any], *, now: float,
                 retry_all: bool = True) -> None:
    """One failed hand-back (re-trip, a write that raised, no read-back):
    wait 10, then 20, then 40 minutes; the next failure leaves it off.

    ``retry_all``: the charger is off again (re-trip, no read-back), so the
    whole stop is undone again next time. False for a partial hand-back:
    what went out stays SEM's (``done``) and only the rest is retried."""
    failures = int(rec.get("failures") or 0) + 1
    rec["failures"] = failures
    rec["handed_back_at"] = 0.0
    rec["confirmed"] = False
    if retry_all:
        pending = list(rec.get("restores") or [])
        for res in rec.get("done") or ():
            if res not in pending:
                pending.append(res)
        rec["restores"] = pending
        rec["done"] = []
    if failures > len(BACKOFF_S):
        rec["left_off"] = True
        rec["next_try_at"] = 0.0
    else:
        rec["next_try_at"] = now + BACKOFF_S[failures - 1]


def merge_stop(existing: Optional[Mapping[str, Any]],
               new: Mapping[str, Any], *, now: float) -> Dict[str, Any]:
    """A new stop for a charger that already has a record.

    Within ``RETRIP_WINDOW_S`` of a hand-back the hand-back failed: count it
    and back off. The restores of the FIRST stop are kept — they undo the
    state the other party had; a second stop of an already-off charger
    records nothing new worth undoing."""
    if not existing:
        return dict(new)
    out = dict(existing)
    handed = float(existing.get("handed_back_at") or 0.0)
    if handed and now - handed <= RETRIP_WINDOW_S:
        note_failure(out, now=now)
    elif handed:
        # an old hand-back that held: this is a new event, start over
        out = dict(new)
    if new.get("restores") and not out.get("restores"):
        out["restores"] = list(new["restores"])
        out["undoable"] = bool(new.get("undoable"))
    out["reason"] = str(new.get("reason") or out.get("reason") or "")
    out["stopped_at"] = float(new.get("stopped_at") or now)
    out["draw_a"] = max(float(out.get("draw_a") or 0.0),
                        float(new.get("draw_a") or 0.0))
    return out


def _phase_margins(snapshot: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    """Smallest margin per monitored phase over the lanes, or None when the
    guard has no full reading."""
    if not isinstance(snapshot, Mapping):
        return None
    topology = str(snapshot.get("topology") or "")
    lanes = ("grid",) if topology == "grid_only" else ("grid", "inverter")
    out: Dict[str, float] = {}
    for lane_name in lanes:
        lane = snapshot.get(lane_name)
        if not isinstance(lane, Mapping) or not lane:
            if lane_name == "inverter" and out:
                continue      # a grid-only reading still answers
            return None
        for phase, row in lane.items():
            margin = _f(row.get("margin_a")) if isinstance(row, Mapping) else None
            if margin is None:
                return None
            out[phase] = min(out.get(phase, margin), margin)
    return out or None


def guard_allows(snapshot: Mapping[str, Any], need_a: float, *,
                 margin_a: float = DEFAULT_RECOVERY_MARGIN_A,
                 reserve_a: float = 0.0) -> Tuple[bool, str]:
    """May a charger drawing ``need_a`` per phase come back now?

    Armed, and every monitored phase has ``need_a`` plus the guard's own
    recovery margin to spare. A guard that is not enforcing (switched off,
    observer) claims no protection: with no full reading it does not block.
    """
    mode = str((snapshot or {}).get("mode") or "")
    margins = _phase_margins(snapshot or {})
    if mode.startswith("enforcing") and mode != "enforcing_armed":
        return False, mode or "guard_not_armed"
    if margins is None:
        if mode.startswith("enforcing"):
            return False, "guard_reading_incomplete"
        return True, "guard_not_enforcing"
    # ``reserve_a``: a charger just handed back whose car has not started
    # yet — the meter does not show its draw, so it is held for it here
    # (review F5), on every phase since SEM does not know which it takes.
    want = float(need_a) + float(margin_a) + max(0.0, float(reserve_a))
    short = {p: m for p, m in margins.items() if m < want}
    if short:
        worst = min(short, key=short.get)
        return False, f"{worst}: {short[worst]:.1f} A free < {want:.1f} A"
    return True, "room"


def _state_matches(current: Any, left: Any) -> Optional[bool]:
    """Is ``current`` still what SEM left? None = cannot tell now."""
    if current in _DEAD:
        return None
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        cur = _f(current)
        return None if cur is None else abs(cur - float(left)) < 1e-6
    return str(current) == str(left)


def _targets_met(rec: Mapping[str, Any], states: Mapping[str, Any]) -> Optional[bool]:
    """Do the entities SEM restored read what it wrote? None = cannot tell."""
    unknown = False
    done = list(rec.get("done") or ())
    if not done:
        return None
    for res in done:
        m = _state_matches(states.get(res.get("entity_id")), res.get("target"))
        if m is None:
            unknown = True
        elif m is False:
            return False
    return None if unknown else True


def plan(records: Mapping[str, Mapping[str, Any]], *, now: float,
         snapshot: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]],
         states: Mapping[str, Any], observer: bool = False,
         ) -> Dict[str, Any]:
    """This cycle's verdict: records to drop (with why), records to mark
    ``left_off``, hand-backs that failed their read-back, hand-backs that
    are confirmed, and at most ONE charger to hand back.

    ``facts[cid]``: ``car_absent`` (bool, "no car" as an answer), ``yielded``
    (SEM still yields this charger), ``priority`` (1 = highest), ``drawing``.
    ``states[entity_id]``: the entity's state now.
    """
    drop: Dict[str, str] = {}
    give_up: List[str] = []
    failed: List[str] = []
    confirm: List[str] = []
    hand_back: Optional[str] = None
    why: Dict[str, str] = {}
    last_hand = max((float(r.get("handed_back_at") or 0.0)
                     for r in records.values()), default=0.0)
    # (review F5) a charger handed back whose car has not started yet
    # (held until its car draws, at most the watch window: a switch that
    # reads "on" is not yet a car that pulls current)
    reserve_a = sum(
        float(r.get("draw_a") or 0.0) for c, r in records.items()
        if float(r.get("handed_back_at") or 0.0)
        and now - float(r.get("handed_back_at") or 0.0) <= RETRIP_WINDOW_S
        and not (facts.get(c) or {}).get("drawing"))
    candidates = []
    for cid, rec in records.items():
        fact = facts.get(cid) or {}
        handed = float(rec.get("handed_back_at") or 0.0)
        if handed:
            # (review F3) a hand-back counts once the charger draws or reads
            # back what SEM restored; otherwise it failed
            if not rec.get("confirmed"):
                met = _targets_met(rec, states)
                if fact.get("drawing") or met is True:
                    confirm.append(cid)
                elif met is False and now - handed >= 30.0:
                    failed.append(cid)
                    continue
                elif now - handed >= READBACK_S:
                    failed.append(cid)
                    continue
            if now - handed > RETRIP_WINDOW_S:
                drop[cid] = "handed_back"
            else:
                why[cid] = "watching"
            continue
        if fact.get("car_absent"):
            drop[cid] = "car_gone"
            continue
        if fact and not fact.get("yielded", True):
            drop[cid] = "sem_steers"
            continue
        if now - float(rec.get("stopped_at") or now) > MAX_AGE_S:
            if not rec.get("left_off"):
                give_up.append(cid)
            why[cid] = "too_old"
            continue
        changed = False
        unknown = False
        settling = now - float(rec.get("stopped_at") or now) < STOP_SETTLE_S
        for res in rec.get("restores") or ():
            cur = states.get(res.get("entity_id"))
            m = _state_matches(cur, res.get("left"))
            if m is None:
                unknown = True
            elif m is False:
                # still the state from before SEM's stop, just after it: the
                # write has not shown yet — wait, never "changed by other"
                if settling and _state_matches(cur, res.get("target")) is True:
                    unknown = True
                else:
                    changed = True
        # (review F1) what SEM itself already restored is SEM's state, not a
        # change by somebody else
        for res in rec.get("done") or ():
            m = _state_matches(states.get(res.get("entity_id")), res.get("target"))
            if m is False and _state_matches(
                    states.get(res.get("entity_id")), res.get("left")) is False:
                changed = True
        if changed:
            drop[cid] = "changed_by_other"
            continue
        if rec.get("left_off"):
            why[cid] = "left_off"
            continue
        if not rec.get("undoable"):
            give_up.append(cid)
            why[cid] = "cannot_undo"
            continue
        if unknown:
            why[cid] = "state_unknown"
            continue
        if now < float(rec.get("next_try_at") or 0.0):
            why[cid] = "backing_off"
            continue
        ok, reason = guard_allows(snapshot, float(rec.get("draw_a") or 0.0),
                                  reserve_a=reserve_a)
        if not ok:
            why[cid] = reason
            continue
        candidates.append((int(fact.get("priority") or 999),
                           float(rec.get("stopped_at") or 0.0), cid))
    if candidates and now - last_hand >= BETWEEN_HAND_BACKS_S:
        hand_back = sorted(candidates)[0][2]
    elif candidates:
        for _p, _t, cid in candidates:
            why[cid] = "waiting_for_previous"
    return {"drop": drop, "give_up": give_up, "failed": failed,
            "confirm": confirm, "hand_back": hand_back, "why": why,
            "observer": bool(observer)}


async def send_hand_back(device: Any, record: Dict[str, Any], *,
                         why: str) -> bool:
    """Send the record's pending restores through the device's one seam,
    one at a time. Each one that went to hardware moves to ``done``; a
    write that raised or was withheld stays pending. True when nothing is
    pending any more.

    ``undo=True`` lets these writes past the yield gate (per call, never a
    shared flag), as ``phase_guard_override`` lets the stop past it; the
    ledger records them as not owed. Observer mode still withholds them
    (and lists them in ``withheld_commands``)."""
    pending: List[Dict[str, Any]] = []
    done = list(record.get("done") or [])
    for res in list(record.get("restores") or ()):
        if not (isinstance(res, dict) and res.get("domain") and res.get("service")
                and isinstance(res.get("data"), dict)):
            # a damaged stored entry: never guess a write from it
            raise ValueError(f"damaged hand-back entry: {res!r}")
        try:
            ok = await device.send(res["domain"], res["service"],
                                   dict(res["data"]), why=why, undo=True)
        except Exception as e:  # noqa: BLE001 — a refused write is a failure, not a crash
            _LOGGER.warning("phase guard hand-back write %s.%s failed: %s",
                            res.get("domain"), res.get("service"), e)
            ok = False
        if ok:
            done.append(res)
        else:
            pending.append(res)
    record["restores"] = pending
    record["done"] = done
    return not pending


# ---------------------------------------------------------------------------
# Coordinator wiring (kept here so coordinator.py only calls in)
# ---------------------------------------------------------------------------

#: The charging state while SEM holds a charger it stopped for the guard.
from ..consts.states import ChargingState as _CS  # noqa: E402
PHASE_GUARD_STOPPED = _CS.PHASE_GUARD_STOPPED


def _stops(coord: Any) -> Dict[str, Dict[str, Any]]:
    book = getattr(coord, "_guard_stops", None)
    if not isinstance(book, dict):
        book = {}
        coord._guard_stops = book
    return book


def note_facts(coord: Any, cid: str, power: Any, *, yielded: bool) -> None:
    """Per charger, per cycle: what the fleet step needs to judge it."""
    facts = getattr(coord, "_hand_back_facts", None)
    if not isinstance(facts, dict):
        facts = {}
        coord._hand_back_facts = facts
    try:
        priority = int(coord._ev_priority_for(cid))
    except Exception:  # noqa: BLE001 — no priority is the lowest
        priority = 999
    facts[cid] = {
        "car_absent": bool(getattr(power, "car_absent", False)),
        "yielded": bool(yielded),
        "priority": priority,
        "drawing": float(getattr(power, "power_w", 0.0) or 0.0) > 500.0,
    }


def note_guard_stop(coord: Any, cid: str, adapter: Any, power: Any,
                    reason: str, *, now: float) -> bool:
    """After ``actuate``: turn what the guard's stop let through into this
    charger's record. True when the record changed (persist it)."""
    dev = getattr(adapter, "_device", None)
    take = getattr(dev, "take_owed", None)
    sent = list(take() if callable(take) else [])
    if not sent:
        return False
    draw_w = float(getattr(power, "power_w", 0.0) or 0.0)
    rec = build_record(
        sent, now=now, reason=reason,
        draw_w=draw_w,
        # (review F4) the phases that CARRY the charge: a one-phase car on a
        # three-phase box needs its whole current on one phase
        phases=_drawing_phases(coord, cid, adapter, dev, draw_w),
        voltage=float(getattr(adapter, "voltage", 230) or 230),
        min_current_a=float(getattr(adapter, "min_current_a", 6) or 6),
    )
    if rec is None:
        return False
    book = _stops(coord)
    book[cid] = merge_stop(book.get(cid), rec, now=now)
    _LOGGER.warning(
        "phase guard stopped %s (%s); SEM switches it back on when the phase "
        "has room (failures so far: %d)", cid, reason,
        int(book[cid].get("failures") or 0))
    return True


def _drawing_phases(coord: Any, cid: str, adapter: Any, dev: Any,
                    draw_w: float) -> int:
    """How many phases carried the charge at the stop: the charger's own
    current per phase (#1407) when it has it, else the charger's configured
    phases. Not SEM's phase belief: this charger is steered by another
    party, so the belief rests on a current SEM did not set (the pipeline
    replay showed a three-phase car read as one phase that way). Without
    per-phase readings a one-phase car on a three-phase box is judged on its
    three-phase share — the readings are the fix, not a guess."""
    reader = getattr(coord, "_charger_leg_phases", None)
    if callable(reader):
        try:
            legs = reader(cid, dev, draw_w)
        except Exception:  # noqa: BLE001 — a reading, never fatal
            legs = None
        if isinstance(legs, int) and 1 <= legs <= 3:
            return legs
    try:
        return max(1, int(getattr(adapter, "phases", 3) or 3))
    except (TypeError, ValueError):
        return 3


def holds(coord: Any, cid: str) -> bool:
    """Is SEM holding this charger off after its guard stop?"""
    rec = _stops(coord).get(cid)
    return bool(rec) and not float(rec.get("handed_back_at") or 0.0)


def effective_state(coord: Any, cid: str, state: str) -> str:
    """The charger's state while held: never a "charging" text at 0 W."""
    return PHASE_GUARD_STOPPED if holds(coord, cid) else state


def fleet_state(coord: Any, state: str) -> str:
    """The published fleet state: held chargers and none drawing → the
    guard-stopped text, not the plan's "night charging active"."""
    held = [cid for cid in _stops(coord) if holds(coord, cid)]
    if not held:
        return state
    facts = getattr(coord, "_hand_back_facts", None) or {}
    # FLEET-READ: the fleet text may say "charging" only if some car draws
    if any(f.get("drawing") for f in facts.values()):
        return state
    return PHASE_GUARD_STOPPED


async def run_step(coord: Any, *, now: float) -> bool:
    """Once per cycle, after the per-charger loop. True when the stored
    records changed (persist them). Never raises: a damaged record is left
    off with a Repair, a refused write is a failure with back-off."""
    book = _stops(coord)
    if not book:
        return False
    hass = getattr(coord, "hass", None)
    states: Dict[str, Any] = {}
    for cid, rec in list(book.items()):
        if not isinstance(rec, dict):
            book.pop(cid, None)
            continue
        for res in [*(rec.get("restores") or ()), *(rec.get("done") or ())]:
            ent = res.get("entity_id") if isinstance(res, dict) else None
            try:
                st = hass.states.get(ent) if (hass is not None and ent) else None
            except Exception:  # noqa: BLE001
                st = None
            states[ent] = getattr(st, "state", None)
    observer = bool(getattr(coord, "_observer_mode", False))
    try:
        verdict = plan(book, now=now,
                       snapshot=getattr(coord, "_phase_guard_snapshot", None) or {},
                       facts=getattr(coord, "_hand_back_facts", None) or {},
                       states=states, observer=observer)
    except Exception:  # noqa: BLE001 — a damaged record must not stop the cycle
        _LOGGER.warning("phase guard hand-back: a stored record is damaged; "
                        "leaving the chargers off", exc_info=True)
        for rec in book.values():
            rec["left_off"] = True
        return True
    changed = False
    # a charger that is no longer configured has nothing to hand back
    for cid in list(book):
        if _device_for(coord, cid) is None:
            verdict["drop"][cid] = "charger_removed"
            verdict["give_up"] = [c for c in verdict["give_up"] if c != cid]
            if verdict["hand_back"] == cid:
                verdict["hand_back"] = None
    for cid, why in verdict["drop"].items():
        book.pop(cid, None)
        _clear_repair(coord, cid)
        _LOGGER.info("phase guard hand-back for %s ends: %s", cid, why)
        changed = True
    for cid in verdict["confirm"]:
        if cid in book:
            book[cid]["confirmed"] = True
            changed = True
    for cid in verdict["failed"]:
        rec = book.get(cid)
        if rec is not None:
            note_failure(rec, now=now)
            _LOGGER.warning("phase guard: %s did not come back after the "
                            "hand-back (failures: %d)", cid,
                            int(rec.get("failures") or 0))
            changed = True
    for cid in verdict["give_up"]:
        rec = book.get(cid)
        if rec is not None and not rec.get("left_off"):
            rec["left_off"] = True
            changed = True
    for cid, rec in book.items():
        if rec.get("left_off"):
            _raise_repair(coord, cid, rec)
    coord._guard_hand_back_why = dict(verdict["why"])
    cid = verdict["hand_back"]
    if cid is None:
        return changed
    rec = book[cid]
    if observer and now - float(rec.get("observed_at") or 0.0) < OBSERVER_REPEAT_S:
        return changed
    dev = _device_for(coord, cid)
    if dev is None:
        return changed
    try:
        all_sent = await send_hand_back(
            dev, rec,
            why=f"phase guard hand-back after its stop ({rec.get('reason')})")
    except Exception:  # noqa: BLE001 — a damaged restore entry
        _LOGGER.warning("phase guard hand-back for %s failed", cid, exc_info=True)
        rec["left_off"] = True
        return True
    if observer:
        rec["observed_at"] = now
        return True
    if all_sent:
        rec["handed_back_at"] = now
        _LOGGER.warning("phase guard: %s switched back on (its stop: %s)",
                        cid, rec.get("reason"))
    else:
        # (review F1/F2) some or all writes did not go out: what went out is
        # kept as SEM's, the rest waits under the same back-off as a re-trip
        note_failure(rec, now=now, retry_all=False)
    return True


def _device_for(coord: Any, cid: str) -> Any:
    devs = getattr(coord, "_ev_devices", None) or {}
    dev = devs.get(cid)
    if dev is None:
        single = getattr(coord, "_ev_device", None)
        if single is not None and not devs:
            dev = single
    return dev


def _charger_name(coord: Any, cid: str) -> str:
    dev = _device_for(coord, cid)
    return str(getattr(dev, "name", None) or cid)


def _raise_repair(coord: Any, cid: str, rec: Mapping[str, Any]) -> None:
    raised = getattr(coord, "_guard_hand_back_repairs", None)
    if not isinstance(raised, set):
        raised = set()
        coord._guard_hand_back_repairs = raised
    if cid in raised:
        return
    hass = getattr(coord, "hass", None)
    if hass is None:
        return
    try:
        from homeassistant.helpers import issue_registry as ir
        from ..const import DOMAIN
        ir.async_create_issue(
            hass, domain=DOMAIN, issue_id=f"guard_left_off_{cid}",
            is_fixable=False, is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="guard_left_off",
            translation_placeholders={
                "charger": _charger_name(coord, cid),
                "tries": str(int(rec.get("failures") or 0)),
            },
        )
        raised.add(cid)
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.create (guard_left_off) failed: %s", e)


def _clear_repair(coord: Any, cid: str) -> None:
    raised = getattr(coord, "_guard_hand_back_repairs", None)
    hass = getattr(coord, "hass", None)
    if hass is None:
        return
    try:
        from homeassistant.helpers import issue_registry as ir
        from ..const import DOMAIN
        ir.async_delete_issue(hass, DOMAIN, f"guard_left_off_{cid}")
    except Exception:  # noqa: BLE001
        pass
    if isinstance(raised, set):
        raised.discard(cid)


def to_store(coord: Any) -> Dict[str, Any]:
    return {cid: dict(rec) for cid, rec in _stops(coord).items()}


def from_store(coord: Any, blob: Any) -> None:
    if not isinstance(blob, dict):
        return
    book = _stops(coord)
    for cid, rec in blob.items():
        if isinstance(cid, str) and isinstance(rec, dict):
            book[cid] = dict(rec)
