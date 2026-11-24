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
#: Failed hand-backs before SEM gives up and tells the user.
MAX_FAILURES = 3
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
    if not isinstance(entity, str) or not entity or prior in _DEAD:
        return None
    if domain in _SWITCH_DOMAINS and service == "turn_off":
        if prior != "on":
            return {"noop": True}     # it was already off: SEM changed nothing
        return {"domain": domain, "service": "turn_on",
                "data": {"entity_id": entity}, "entity_id": entity,
                "left": "off"}
    if domain in _NUMBER_DOMAINS and service == "set_value":
        before, after = _f(prior), _f(data.get("value"))
        if before is None or after is None:
            return None
        if abs(before - after) < 1e-6:
            return {"noop": True}
        return {"domain": domain, "service": "set_value",
                "data": {"entity_id": entity, "value": before},
                "entity_id": entity, "left": after}
    if domain in _SELECT_DOMAINS and service == "select_option":
        after = data.get("option")
        if not isinstance(after, str):
            return None
        if after == prior:
            return {"noop": True}
        return {"domain": domain, "service": "select_option",
                "data": {"entity_id": entity, "option": prior},
                "entity_id": entity, "left": after}
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
    }


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
        failures = int(existing.get("failures") or 0) + 1
        out["failures"] = failures
        out["handed_back_at"] = 0.0
        if failures >= MAX_FAILURES:
            out["left_off"] = True
            out["next_try_at"] = 0.0
        else:
            out["next_try_at"] = now + BACKOFF_S[min(failures, len(BACKOFF_S)) - 1]
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
                 margin_a: float = DEFAULT_RECOVERY_MARGIN_A) -> Tuple[bool, str]:
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
    want = float(need_a) + float(margin_a)
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


def plan(records: Mapping[str, Mapping[str, Any]], *, now: float,
         snapshot: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]],
         states: Mapping[str, Any], observer: bool = False,
         ) -> Dict[str, Any]:
    """This cycle's verdict: records to drop (with why), records to mark
    ``left_off``, and at most ONE charger to hand back.

    ``facts[cid]``: ``car_absent`` (bool, "no car" as an answer), ``yielded``
    (SEM still yields this charger), ``priority`` (1 = highest).
    ``states[entity_id]``: the entity's state now.
    """
    drop: Dict[str, str] = {}
    give_up: List[str] = []
    hand_back: Optional[str] = None
    why: Dict[str, str] = {}
    last_hand = max((float(r.get("handed_back_at") or 0.0)
                     for r in records.values()), default=0.0)
    candidates = []
    for cid, rec in records.items():
        fact = facts.get(cid) or {}
        handed = float(rec.get("handed_back_at") or 0.0)
        if handed:
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
        changed = False
        unknown = False
        for res in rec.get("restores") or ():
            m = _state_matches(states.get(res.get("entity_id")), res.get("left"))
            if m is None:
                unknown = True
            elif m is False:
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
        ok, reason = guard_allows(snapshot, float(rec.get("draw_a") or 0.0))
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
    return {"drop": drop, "give_up": give_up, "hand_back": hand_back,
            "why": why, "observer": bool(observer)}


async def send_hand_back(device: Any, record: Mapping[str, Any], *,
                         why: str) -> bool:
    """Send the record's restores through the device's one seam.

    ``owner_undo`` lets these writes past the yield gate, as
    ``phase_guard_override`` lets the stop past it; the ledger records them as
    not owed. Observer mode still withholds them (and lists them in
    ``withheld_commands``). True when every restore went to hardware."""
    sent_all = True
    try:
        device.owner_undo = True
        device.command_source = "hand_back"
        device.command_klass = 1
    except AttributeError:
        pass
    try:
        for res in record.get("restores") or ():
            ok = await device.send(res["domain"], res["service"],
                                   dict(res["data"]), why=why)
            sent_all = sent_all and bool(ok)
    finally:
        try:
            device.owner_undo = False
        except AttributeError:
            pass
    return sent_all


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
    rec = build_record(
        sent, now=now, reason=reason,
        draw_w=float(getattr(power, "power_w", 0.0) or 0.0),
        phases=int(getattr(adapter, "phases", 3) or 3),
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
    records changed (persist them)."""
    book = _stops(coord)
    if not book:
        return False
    hass = getattr(coord, "hass", None)
    states: Dict[str, Any] = {}
    for rec in book.values():
        for res in rec.get("restores") or ():
            ent = res.get("entity_id")
            try:
                st = hass.states.get(ent) if hass is not None else None
            except Exception:  # noqa: BLE001
                st = None
            states[ent] = getattr(st, "state", None)
    observer = bool(getattr(coord, "_observer_mode", False))
    verdict = plan(book, now=now,
                   snapshot=getattr(coord, "_phase_guard_snapshot", None) or {},
                   facts=getattr(coord, "_hand_back_facts", None) or {},
                   states=states, observer=observer)
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
    sent = await send_hand_back(
        dev, rec, why=f"phase guard hand-back after its stop ({rec.get('reason')})")
    if observer:
        rec["observed_at"] = now
        return True
    if sent:
        rec["handed_back_at"] = now
        _LOGGER.warning("phase guard: %s switched back on (its stop: %s)",
                        cid, rec.get("reason"))
    else:
        # nothing went out (a refused or failed write): wait and try again
        rec["next_try_at"] = now + BACKOFF_S[0]
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
