"""(#1054) A charger is a DEVICE reference; the crawler fills in its roles.

Before this, a charger was stored as a copy of its entity ids, twice
(``entry.data`` and ``entry.options``), joined at every start by a heal and
de-duplicated by guesswork. weindler's go-e was lost that way (beta.15): an old
half-filled card sat first in both lists, so it was the primary — the one the
Configure dialog never offers to remove — and because it named one go-e entity
the detection page counted the box as configured and hid the offer that could
rebuild it.

Now ``entry.options["ev_charger_refs"]`` is the one store. A ref says WHICH
device a charger is, what the user set by hand, and the user's settings::

    {"id": …, "device_id": "<HA device id>" | None,
     "overrides": {role: value},   # roles the user set; device-less: all
     "cleared": [role, …],         # roles the crawler offers, the user has not
     "found": {role: value},       # the crawler's last answer for the device
     "held": [role, …],            # (#1151) state roles kept back until the
                                   # card's controls are the crawler's
     "plug_checked": True,         # (#1152) its plug went through the check
     "settings": {…}}              # name, mode, priority, targets, …

Every start resolves each ref into today's charger dict — the crawler's live
answer for its device, the overrides on top — so the rest of SEM reads the
shape it always read (``coordinator.config["ev_chargers"]``).

One release long the resolved list is also written to
``entry.options["ev_chargers"]``: a downgrade reads it as before, and today's
writers (sliders, the options flow, the card, ``remove_charger``) still write
it. A change there is seen by its fingerprint at the next start and folded
into the refs. ``entry.data`` holds no charger list any more, so nothing can
be healed back.

Rules the refs keep:

* one ref per device. A half card beside a complete one for the same device
  is folded into it; a copy of a charger is folded into it. A second charger
  on a device (a twin wallbox) needs the explicit ``connector`` setting; the
  migration sets it on an install that already runs two, so nothing working
  is dropped.
* a complete charger resolves to exactly what it was when it became a ref —
  every role that differs from the crawler is an override, every role the
  crawler adds is ``cleared``. Only a half card is completed by the crawler.
* a device-less charger (no registry device — PROD's KEBA, service-only
  boxes) keeps its whole mapping as overrides: the crawler is not asked.

Pure functions first; ``async_reconcile`` is the one place that touches Home
Assistant, called once per setup.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .hardware_detection import (
    CHARGER_ENTITY_KEYS,
    CHARGER_WIRING_KEYS,
    _offer_missing,
    charger_is_complete,
)

_LOGGER = logging.getLogger(__name__)

REFS_KEY = "ev_charger_refs"
LEGACY_KEY = "ev_chargers"
SIG_KEY = "ev_charger_refs_sig"
#: (#1152) a ref whose plug sensor went through the control check once
PLUG_CHECKED = "plug_checked"

#: What the crawler answers for a device. Everything else on a charger is a
#: setting the user chose.
ROLE_KEYS = frozenset(CHARGER_ENTITY_KEYS | {
    "ev_charger_service", "ev_charger_service_data", "ev_service_param_name",
})

DeviceOf = Callable[[str], Optional[str]]
#: (#1144) a charger dict → the keys SEM must never drive, or (#1143) read
#: as the charge
Refuse = Callable[[Dict[str, Any]], Iterable[str]]
#: (#1144) the roles a charger's current is written through
CURRENT_CONTROL_ROLES = frozenset({
    "ev_current_control_entity", "ev_charger_service",
    "ev_service_param_name", "ev_charger_service_data",
    "ev_charger_service_entity_id",
})
#: (#1143) the roles a charger's car is read through
STATE_ROLES = frozenset({"ev_connected_sensor", "ev_charging_sensor"})
#: (#1126, #1134) What a charger reads its power from and drives. Seeing the
#: car puts these to work, so a charger that read no car gets a state sensor
#: only when each is what detection finds today — in the startup heal
#: (``_fill_state_sensors_of_own_save``) and in a ref (#1151). A Peblar saved
#: before #1035 can hold one phase as its power and the single-phase switch
#: as start/stop.
STATE_MUST_MATCH = (
    "ev_charging_power_sensor", "ev_current_control_entity",
    "ev_start_stop_entity", "ev_charge_mode_entity",
    "ev_charger_service", "ev_start_service", "ev_stop_service",
)


# ── pure ──────────────────────────────────────────────────────────────────

def signature(cards: Any) -> str:
    """A stable fingerprint of a charger list."""
    return hashlib.sha1(
        json.dumps(cards or [], sort_keys=True, default=str).encode()
    ).hexdigest()


def roles_of(card: dict) -> Dict[str, Any]:
    return {k: card[k] for k in ROLE_KEYS if card.get(k)}


def device_of_card(card: dict, device_of: DeviceOf) -> Optional[str]:
    """The device most of a card's role entities sit on; None if none do."""
    votes = Counter()
    for key in CHARGER_ENTITY_KEYS:
        eid = card.get(key)
        if eid:
            dev = device_of(str(eid))
            if dev:
                votes[dev] += 1
    if not votes:
        return None
    return sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def card_to_ref(card: dict, device_id: Optional[str],
                live: Optional[Dict[str, Any]]) -> dict:
    """A stored charger card → a ref that resolves back to the same card."""
    roles = roles_of(card)
    settings = {k: v for k, v in card.items()
                if k != "id" and (k not in ROLE_KEYS or not v)}
    whole = charger_is_complete(card)
    if device_id is None:
        return {"id": card["id"], "device_id": None, "overrides": roles,
                "cleared": [], "found": {}, "settings": settings,
                "stored_complete": whole}
    live = dict(live or {})
    overrides = {k: v for k, v in roles.items() if live.get(k) != v}
    cleared = sorted(k for k in live if k not in roles) if whole else []
    return {"id": card["id"], "device_id": device_id, "overrides": overrides,
            "cleared": cleared, "found": live, "settings": settings,
            "stored_complete": whole}


def resolve(ref: dict, live: Optional[Dict[str, Any]] = None) -> dict:
    """A ref → today's charger dict: the crawler's answer, then the user's."""
    found = {**(ref.get("found") or {}), **(live or {})}
    card = {"id": ref["id"], **(ref.get("settings") or {})}
    cleared = set(ref.get("cleared") or ()) | set(ref.get("held") or ())
    for role in ROLE_KEYS:
        if role in cleared:
            continue
        value = (ref.get("overrides") or {}).get(role) or found.get(role)
        if value:
            card[role] = value
    return card


def _box(card: dict, device_id: Optional[str]) -> Optional[str]:
    """What makes two cards the same box: the HA device, or — for a
    device-less charger (a KEBA) — its exact entity set. The old set_option
    fold caught a device-less copy the same way (#1092 lifecycle: setup's
    auto-discovery, then a create click for the same box under a new id)."""
    if device_id is not None:
        return device_id
    from .hardware_detection import charger_entity_ids
    ids = charger_entity_ids(card)
    return "entities:" + ",".join(sorted(ids)) if ids else None


def _is_half(ref: dict) -> bool:
    """A ref made from a half card. The crawler may complete what it
    RESOLVES to, but a complete charger for the same device still replaces
    it: weindler's old card must never outrank the working go-e."""
    return not ref.get("stored_complete", True)


def _copy_of(small: dict, big: dict) -> bool:
    """``small``'s roles are all in ``big`` — a copy or a half card of it."""
    sr, br = roles_of(small), roles_of(big)
    return all(br.get(k) == v for k, v in sr.items())


def refs_from_cards(cards: Iterable[dict], device_of: DeviceOf,
                    live_by_device: Dict[str, Dict[str, Any]],
                    log: Callable[[str], None] = _LOGGER.info) -> List[dict]:
    """Stored cards → refs, one per device (the migration).

    The ref for a device takes the place of the FIRST card for it, so a
    primary stays the primary. The complete card wins; a half card or a copy
    of it is folded in. Two complete chargers with different entities on one
    device are both kept, the second marked with ``connector``."""
    out: List[dict] = []
    by_device: Dict[str, List[int]] = {}
    for card in cards or []:
        if not isinstance(card, dict) or not card.get("id"):
            continue
        if any(r["id"] == card["id"] for r in out):
            continue
        dev = device_of_card(card, device_of)
        live = live_by_device.get(dev) if dev else None
        box = _box(card, dev)
        if box is not None and box in by_device:
            placed = False
            for idx in by_device[box]:
                existing = resolve(out[idx], live)
                if _is_half(out[idx]) and charger_is_complete(card):
                    keep_place = out[idx]["id"]
                    out[idx] = card_to_ref(card, dev, live)
                    log(f"charger {keep_place} was a half card for the device "
                        f"of {card['id']} — replaced by it")
                    placed = True
                    break
                if not charger_is_complete(card) or _copy_of(card, existing):
                    log(f"charger {card['id']} is a half card or a copy of "
                        f"{out[idx]['id']} on the same device — folded into it")
                    placed = True
                    break
            if placed:
                continue
            # (Decision 3) a second charger on one device needs the
            # explicit ``connector`` setting. An install that already runs
            # two different chargers on one device keeps both: the
            # migration SETS it, numbering by position, so nothing working
            # is dropped.
            first = out[by_device[box][0]]
            first["settings"].setdefault("connector", 1)
            ref = card_to_ref(card, dev, live)
            ref["settings"].setdefault("connector", len(by_device[box]) + 1)
            log(f"charger {card['id']} is a second charger on the device of "
                f"{first['id']} — kept, as connector "
                f"{ref['settings']['connector']}")
            by_device[box].append(len(out))
            out.append(ref)
            continue
        ref = card_to_ref(card, dev, live)
        if box is not None:
            by_device[box] = [len(out)]
        out.append(ref)
    return out


def apply_legacy_edit(refs: List[dict], legacy: List[dict],
                      device_of: DeviceOf,
                      live_by_device: Dict[str, Dict[str, Any]],
                      log: Callable[[str], None] = _LOGGER.info) -> List[dict]:
    """Fold a change a writer made to the legacy list into the refs.

    The legacy list is what the writers edit: its ids are the chargers, its
    order is the order, its settings are the settings, and a role that
    differs from what the ref resolves to is something the user set. A ref
    whose id is gone was removed."""
    by_id = {r["id"]: r for r in refs}
    out: List[dict] = []
    new_cards: List[Tuple[int, dict]] = []
    for card in legacy or []:
        if not isinstance(card, dict) or not card.get("id"):
            continue
        ref = by_id.get(card["id"])
        if ref is None:
            new_cards.append((len(out), card))
            out.append(None)  # placeholder, keeps the order
            continue
        dev = ref.get("device_id")
        live = live_by_device.get(dev) if dev else None
        was = resolve(ref, live)
        upd = {**ref, "overrides": dict(ref.get("overrides") or {}),
               "cleared": list(ref.get("cleared") or []),
               "settings": {k: v for k, v in card.items()
                            if k != "id" and (k not in ROLE_KEYS or not v)}}
        found = {**(ref.get("found") or {}), **(live or {})}
        for role in ROLE_KEYS:
            now, before = card.get(role), was.get(role)
            if now == before:
                continue
            if now:
                if dev is not None and found.get(role) == now:
                    upd["overrides"].pop(role, None)
                else:
                    upd["overrides"][role] = now
                if role in upd["cleared"]:
                    upd["cleared"].remove(role)
            else:
                upd["overrides"].pop(role, None)
                if dev is not None and found.get(role) and role not in upd["cleared"]:
                    upd["cleared"].append(role)
        upd["cleared"].sort()
        if any(card.get(r) != was.get(r) for r in ROLE_KEYS):
            # the user set a role by hand: what they built is theirs now
            upd["stored_complete"] = charger_is_complete(card)
        out.append(upd)
    for pos, card in new_cards:
        dev = device_of_card(card, device_of)
        live = live_by_device.get(dev) if dev else None
        box = _box(card, dev)
        twins = [i for i, r in enumerate(out)
                 if r is not None and box is not None
                 and _box(resolve(r, live_by_device.get(r.get("device_id"))
                                  if r.get("device_id") else None),
                          r.get("device_id")) == box]
        if twins:
            existing = resolve(out[twins[0]], live)
            if _is_half(out[twins[0]]) and charger_is_complete(card):
                old = out[twins[0]]["id"]
                out[twins[0]] = card_to_ref(card, dev, live)
                log(f"charger {old} was a half card for the device of "
                    f"{card['id']} — replaced by it")
                continue
            if not charger_is_complete(card) or _copy_of(card, existing):
                log(f"charger {card['id']} is a copy of {out[twins[0]]['id']} "
                    "on the same device — not added twice")
                continue
            if not card.get("connector"):
                # (Decision 3) one charger per device unless the user says
                # which connector this one is
                log(f"charger {card['id']} is a second charger on the device "
                    f"of {out[twins[0]]['id']} without a connector setting — "
                    "not added")
                continue
            out[twins[0]]["settings"].setdefault("connector", 1)
            out[pos] = card_to_ref(card, dev, live)
            continue
        out[pos] = card_to_ref(card, dev, live)
    gone = [r["id"] for r in refs if r["id"] not in {c.get("id") for c in legacy or []
                                                     if isinstance(c, dict)}]
    for cid in gone:
        log(f"charger {cid} was removed")
    return [r for r in out if r is not None]


#: (#1214) The roles that drive a charger. A ref follows only to a device
#: that holds one: a power meter beside the box is not the charger.
_CONTROL_ENTITY_ROLES = ("ev_current_control_entity", "ev_start_stop_entity",
                         "ev_charge_mode_entity")


def _connector(ref: dict) -> bool:
    return bool((ref.get("settings") or {}).get("connector"))


def follow_device(refs: List[dict], device_of: DeviceOf,
                  live_by_device: Dict[str, Dict[str, Any]],
                  sure: Iterable[str],
                  log: Callable[[str], None] = _LOGGER.info) -> List[dict]:
    """(#1214) A ref names the device its card's entities sit on.

    The device was set once, when the ref was made. A user who moved a
    charger to another integration picked the new device's entities, and
    the ref still named the old device. Once that device was removed, a
    Repair said "its device is gone" about a charger that runs, and the old
    device's last answer (``found``) still filled each role the user did not
    set.

    When no entity of the card sits on the ref's device and they sit on
    another one, which holds one of the card's controls, the ref is made
    again from the card for that device (``card_to_ref``). The new device
    must be in ``sure`` (#1147: the crawler saw it whole): a role it offers
    that the card lacks is then ``cleared``, so a whole card resolves to the
    same values now and at later starts. A role the user cleared stays
    cleared. A device another ref names takes a second ref only when both
    carry the ``connector`` setting (one charger per device, #1054)."""
    sure = set(sure or ())
    names: Dict[str, List[bool]] = {}
    for r in refs:
        if r.get("device_id"):
            names.setdefault(r["device_id"], []).append(_connector(r))
    out: List[dict] = []
    for r in refs:
        dev = r.get("device_id")
        if dev is None:
            out.append(r)
            continue
        live = live_by_device.get(dev)
        # a held role is still the card's (#1151); ``held`` is kept below
        card = resolve(_without(r, {"held"}), live)
        on = [device_of(str(card[k])) for k in sorted(CHARGER_ENTITY_KEYS)
              if card.get(k)]
        new = device_of_card(card, device_of)
        if dev in on or new is None or new == dev or not any(
                card.get(k) and device_of(str(card[k])) == new
                for k in _CONTROL_ENTITY_ROLES):
            out.append(r)
            continue
        others = names.get(new, [])
        if others and not (_connector(r) and all(others)):
            log(f"charger {r['id']}: its entities sit on device {new}, which "
                "another charger names; kept on its own device (#1214)")
            out.append(r)
            continue
        if new not in sure:
            # not seen whole yet: a later start moves it
            out.append(r)
            continue
        log(f"charger {r['id']}: its entities now sit on device {new}, not "
            f"{dev}; its reference follows them (#1214)")
        names[dev].remove(_connector(r))
        names.setdefault(new, []).append(_connector(r))
        moved = card_to_ref(card, new, live_by_device.get(new))
        moved["cleared"] = sorted({*moved["cleared"], *(r.get("cleared") or ())})
        out.append({**r, **moved})
    return out


def refresh_found(refs: List[dict],
                  live_by_device: Dict[str, Dict[str, Any]]) -> List[dict]:
    """Remember the crawler's latest answer per device (a start where it
    cannot ask keeps the last one)."""
    out = []
    for r in refs:
        dev = r.get("device_id")
        live = live_by_device.get(dev) if dev else None
        out.append({**r, "found": {**(r.get("found") or {}), **live}} if live else r)
    return out


def forget_stale(refs: List[dict], live_by_device: Dict[str, Dict[str, Any]],
                 sure: Iterable[str],
                 log: Callable[[str], None] = _LOGGER.info) -> List[dict]:
    """(#1147) Forget a role the crawler stopped giving — only when it saw
    the whole device.

    ``refresh_found`` only adds: a start that cannot ask keeps the last
    answer. So a role a detection fix took away stayed in ``found``, and
    every start used it again (a Zaptec Go saved before #1142 kept the
    online sensor as its charge; #1144 needed its own drop for the site
    limit). Replacing ``found`` whole at every start would make roles come
    and go: a start during Home Assistant's boot reads no states, and an
    integration that is still loading shows part of its device.

    ``sure`` names the devices whose answer is whole (``sure_devices``: Home
    Assistant runs, every integration of the device is loaded, each of its
    entities has a state). For those, a role of ``found`` that today's
    answer (``live``) does not hold goes. A device the crawler did not see
    keeps its ``found``. ``overrides`` (what the user set) and ``cleared``
    are never touched."""
    sure = set(sure or ())
    out: List[dict] = []
    for r in refs:
        dev = r.get("device_id")
        live = live_by_device.get(dev) if dev in sure else None
        found = r.get("found") or {}
        gone = {k: v for k, v in found.items() if live and k not in live}
        if not gone:
            out.append(r)
            continue
        log(f"charger {r['id']}: detection no longer finds {gone} on its "
            "device; forgotten (#1147)")
        new = {**r, "found": {k: v for k, v in found.items()
                              if k not in gone}}
        if r.get("stored_complete", True):
            # as in ``drop_refused``: a ref left half can be replaced (#1054)
            new["stored_complete"] = charger_is_complete(resolve(new, live))
        out.append(new)
    return out


def check_saved_plugs(refs: List[dict], ran: Dict[str, dict],
                      live_by_device: Dict[str, Dict[str, Any]], *,
                      sure: Iterable[str], own: Iterable[str], fresh: Iterable[str],
                      refuse: Optional[Refuse] = None,
                      log: Callable[[str], None] = _LOGGER.info,
                      ) -> Tuple[List[dict], Dict[str, dict]]:
    """(#1152) Put a plug a start before #1151 added through the control
    check, once.

    2.2.0-beta.20 merged the crawler's answer into every ref with no check,
    so setup's own Zaptec save got "Charger mode" as its plug (#1142). The
    #1151 check asks only a charger that read no car before the start; this
    one reads one now, so its controls (a switch from before 2.2.0-beta.5,
    #1134) were never asked.

    The store does not say where a plug came from. So the check is asked of
    a ref only when it is setup's own save (its id is in ``own``: the id
    setup gives that box, the startup heal's own rule) and every state
    sensor its card read came from the crawler (none in ``overrides``) and
    is what the crawler finds today. For such a ref the card it ran on
    counts as one that read no car, so ``hold_new_state`` holds the sensors
    unless its controls are today's, and the startup heal decides — as for
    a save that never had a plug. A card the user set up (its own id) is
    never asked.

    Each ref is marked ``plug_checked`` once it was asked, or is not setup's
    own save on a device seen whole (``sure``), or was made at this start
    (``fresh``: the #1151 check covers it). An unmarked ref is asked again
    at the next start. Once held, the #1151 check asks every start."""
    sure, own, fresh = set(sure or ()), set(own or ()), set(fresh or ())
    ran = dict(ran)
    out: List[dict] = []
    for r in refs:
        dev = r.get("device_id")
        if r.get(PLUG_CHECKED) or dev is None:
            out.append(r)
            continue
        live = live_by_device.get(dev) or {}
        before = ran.get(r["id"])
        if r["id"] in fresh or (dev in sure and r["id"] not in own):
            out.append({**r, PLUG_CHECKED: True})
            continue
        if r["id"] not in own or not live:
            out.append(r)
            continue
        if before is not None:
            not_read = set(refuse(before)) if refuse is not None else set()
            reads = [k for k in STATE_ROLES
                     if before.get(k) and k not in not_read]
            mine = r.get("overrides") or {}
            if reads and all(k not in mine and before[k] == live.get(k)
                             for k in reads):
                log(f"charger {r['id']}: its {reads} came from detection "
                    "with no control check; checked once now (#1152)")
                ran[r["id"]] = _without(before, set(STATE_ROLES))
        out.append({**r, PLUG_CHECKED: True})
    return out, ran


def problems(refs: List[dict], resolved: List[dict], *,
             device_exists: Callable[[str], bool],
             entity_exists: Callable[[str], bool]) -> List[dict]:
    """What a start can say is wrong with each charger (for Repairs)."""
    out: List[dict] = []
    for ref, card in zip(refs, resolved, strict=True):
        dev = ref.get("device_id")
        if dev is None:
            continue
        name = (ref.get("settings") or {}).get("name") or ref["id"]
        if not device_exists(dev):
            out.append({"kind": "charger_device_gone", "id": ref["id"],
                        "name": name})
            continue
        # the crawler's own rule for a charger SEM can run (#1092)
        missing = _offer_missing({k: v for k, v in card.items() if v})
        if missing:
            out.append({"kind": "charger_role_missing", "id": ref["id"],
                        "name": name, "roles": ", ".join(missing)})
        # every entity the charger runs on — set by the user or detected —
        # that is gone or disabled
        for role in sorted(CHARGER_ENTITY_KEYS):
            value = card.get(role)
            if value and "." in str(value) and not entity_exists(str(value)):
                out.append({"kind": "charger_role_entity_gone", "id": ref["id"],
                            "name": name, "entity": str(value)})
    return out


def drop_refused(refs: List[dict], live_by_device: Dict[str, Dict[str, Any]],
                 refuse: Refuse) -> List[dict]:
    """(#1144) Take out of each ref what SEM must never drive.

    A ref keeps the crawler's last answer (``found``) when a start cannot
    ask, so a role the crawler stopped giving stays there. The old setup
    offer gave a Zaptec Go its site's "Available current" (#1141), and every
    start drove it again. Whether the crawler found it or the user set it,
    it goes: SEM never writes a whole site's current limit (#804).

    Asked of the card the ref resolves to (a service in ``overrides`` and
    its field in ``found`` make one write), and of ``found`` and
    ``overrides`` alone (a value a ``cleared`` role hides now would show
    the day the role is set again). A part keeps a value the card does not
    use. When the card's own current control goes, its current roles are no
    longer ``cleared``, so what the crawler finds today shows through: a
    complete card cleared them only because it had that control. The ref is
    then complete only if what it resolves to is, so a new card for the same
    box can replace it (#1054).

    (#1143) A link sensor read as the charge goes the same way: a Zaptec's
    "Charger" is on while the box is online (#1142), and the setup wizard
    prefilled it, so a save the user confirmed holds it as their own. A card
    with a plug sensor (the wizard asks for both) then reads the charge the
    crawler finds today. A card with none is setup's own save: the charge
    role is ``cleared``, so the card has neither sensor and the startup heal
    (``_fill_state_sensors_of_own_save``) decides, with its control check
    (#1134). The next start folds what it gave. The current roles are
    un-cleared only when a current control goes."""
    out: List[dict] = []
    for r in refs:
        dev = r.get("device_id")
        live = live_by_device.get(dev) if dev else None
        card = resolve(r, live)
        bad = set(refuse(card))
        new = dict(r)
        gone: Dict[str, Any] = {}
        for part in ("found", "overrides", "settings"):
            d = r.get(part) or {}
            own = set(refuse(d)) if part != "settings" else set()
            keep = {k: v for k, v in d.items()
                    if k not in own and not (k in bad and v == card.get(k))}
            gone.update({k: v for k, v in d.items() if k not in keep})
            new[part] = keep
        if not gone:
            out.append(r)
            continue
        _log_refused(f"Charger {r['id']}", gone)
        if bad & CURRENT_CONTROL_ROLES:
            new["cleared"] = [k for k in new.get("cleared") or ()
                              if k not in CURRENT_CONTROL_ROLES]
        # (#1151) a held plug is still the card's: a hold is asked again
        # every start, a clear would last
        if bad & STATE_ROLES and not resolve(_without(new, {"held"}), live).get(
                "ev_connected_sensor"):
            # (#1143) no plug sensor: setup's own save (#1142). Nothing takes
            # the link's place here; the startup heal gives the save both
            # sensors only when its controls match detection (#1134).
            new["cleared"] = sorted({*(new.get("cleared") or ()),
                                     *(bad & STATE_ROLES)})
        if r.get("stored_complete", True):
            new["stored_complete"] = charger_is_complete(resolve(new, live))
        out.append(new)
    return out


def _log_refused(where: str, gone: Dict[str, Any]) -> None:
    """Say what a start took out of a save, and why. Only the link rule
    (#1143) refuses a state role; every other refused key is a site limit."""
    link = {k: v for k, v in gone.items() if k in STATE_ROLES}
    site = {k: v for k, v in gone.items() if k not in STATE_ROLES}
    if site:
        _LOGGER.warning(
            "%s: %s write a whole site's current limit, not this charger's; "
            "SEM no longer writes it (#804, #1144).", where, site)
    if link:
        _LOGGER.warning(
            "%s: %s says the charger is online, not that a car charges; SEM "
            "no longer reads it as charging (#1142, #1143).", where, link)


def hold_new_state(refs: List[dict], ran: Dict[str, dict],
                   live_by_device: Dict[str, Dict[str, Any]],
                   refuse: Optional[Refuse] = None,
                   log: Callable[[str], None] = _LOGGER.info) -> List[dict]:
    """(#1151) A charger that read no car gets a plug or charging sensor from
    the crawler only when each control its card drives is what it finds
    today.

    The crawler fills a ref's roles, so when it learns to read a plug (a
    Peblar's ``enum`` state, #1126; a Zaptec's "Charger mode", #1142) a save
    that read none gets one at the next start, and seeing the car puts the
    card's controls to work. The startup heal gives setup's own save its
    sensors only when its controls are what detection finds (#1134); a save
    with a plug skips that heal. So a stale control in ``overrides`` (a
    Peblar's single-phase switch as start/stop) was driven.

    ``ran`` is the card each charger ran on before this start. When it read
    no car (no state sensor, or only one ``refuse`` takes: a link as the
    charge, #1143) and the card has a state sensor, it shows only when every
    ``STATE_MUST_MATCH`` key of the card equals today's answer (``live``).
    The crawler's last answer (``found``) does not count: it keeps a control
    the crawler stopped giving. A start or stop service is never in the
    crawler's answer, so a card with one does not pass. Otherwise the state
    roles are ``held``: the card reads no car, and the heal decides with its
    check. When it fills them, the next start folds them in as any edit,
    and the card then read the car. ``held`` is worked out again at every
    start, so a start that saw only part of the device, or a control the
    user set right, lets them show once the controls match. A charger that
    already read the car (the wizard asks for both sensors) has had its
    controls in use; nothing of it is held."""
    out: List[dict] = []
    for r in refs:
        dev = r.get("device_id")
        before = ran.get(r["id"])
        if dev is None or before is None:
            out.append(r)
            continue
        free = {k: v for k, v in r.items() if k != "held"}
        not_read = set(refuse(before)) if refuse is not None else set()
        if any(before.get(k) and k not in not_read for k in STATE_ROLES):
            out.append(free if "held" in r else r)
            continue
        live = live_by_device.get(dev) or {}
        card = resolve(free, live)
        new = sorted(k for k in STATE_ROLES if card.get(k))
        differ = [k for k in STATE_MUST_MATCH
                  if (card.get(k) or None) != (live.get(k) or None)]
        if not new or not differ:
            out.append(free if "held" in r else r)
            continue
        if new != list(r.get("held") or ()):
            stale = {k: card.get(k) for k in differ}
            log(f"charger {r['id']}: detection now finds {new}, but {stale} "
                "differ from what it finds; the startup check decides "
                "(#1151)")
        out.append({**free, "held": new})
    return out


def _without(d: Dict[str, Any], keys: set) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


# ── (#1154) the flat keys follow the first charger ───────────────────────

#: The flat values that name ONE box: its entities and the device a current
#: service is sent to. A service name or a field name can be the same on two
#: boxes of one brand, so it says nothing about whose the flat keys are.
_FLAT_IDENTITY_KEYS = CHARGER_ENTITY_KEYS | {"ev_service_device_id"}


def first_card(cards: Any) -> Optional[dict]:
    """The first charger of a stored list, or None."""
    for c in cards or ():
        if isinstance(c, dict):
            return c
    return None


def flat_wiring(store: Any) -> Dict[str, Any]:
    """The flat top-level charger wiring a store holds (set values only)."""
    if not isinstance(store, dict):
        return {}
    return {k: store[k] for k in CHARGER_WIRING_KEYS
            if store.get(k) not in (None, "")}


def flat_wiring_is_of(card: Optional[dict], flat: Any,
                      device_of: Optional[DeviceOf] = None) -> bool:
    """(#1154) Do the flat charger keys belong to ``card``?

    The setup wizard and the v2→v3 migration wrote the FIRST charger's wiring
    there and its card holds a copy, so they share an entity — or they sit
    on one HA device. A card that became first because the one before it
    was removed names its own box: where both name, say, a power sensor,
    they name different ones, and the flat keys still name the removed box.
    The wizard always saved a power sensor, so a card without one does not
    take the flat one from a box it shares nothing with; a card that names
    no entity at all (the config card's new charger) owns nothing. What is
    left is an old save that split one box between the card and the flat
    keys, each naming different roles: those are the card's. The device
    only ever says yes: a site limit sits on the site's device (#1144), and
    the builder must still see it to refuse it."""
    wiring = flat_wiring(flat)
    if not wiring:
        return True
    if not isinstance(card, dict):
        return False
    ident = {k: v for k, v in wiring.items() if k in _FLAT_IDENTITY_KEYS}
    if any(card.get(k) == v for k, v in ident.items()):
        return True
    if device_of is not None:
        mine = device_of_card(card, device_of)
        if mine and mine == device_of_card(wiring, device_of):
            return True
    if any(card.get(k) not in (None, "") for k in ident):
        return False      # both name this role, each a different entity
    if not any(card.get(k) not in (None, "") for k in _FLAT_IDENTITY_KEYS):
        return False      # the card names no box
    return "ev_charging_power_sensor" not in wiring


def without_flat_wiring(store: Any) -> Optional[Dict[str, Any]]:
    """``store`` without any flat charger wiring key, or None when it holds
    none (nothing to write)."""
    if not isinstance(store, dict) or not any(k in store for k in CHARGER_WIRING_KEYS):
        return None
    return {k: v for k, v in store.items() if k not in CHARGER_WIRING_KEYS}


def stale_flat_wiring(data: Any, options: Any, cards: Any,
                      device_of: Optional[DeviceOf] = None) -> Dict[str, Any]:
    """(#1154) The flat charger wiring of ``{**data, **options}`` that does
    not belong to the first of ``cards`` — empty when it does, or when there
    is none. With no card the flat keys ARE the charger on an install that
    never kept charger refs (a pre-migration save: setup builds its charger
    from them), so they stay; once refs exist, an empty list is the user
    having removed every charger."""
    if not cards and REFS_KEY not in (options or {}):
        return {}
    merged = {**(data or {}), **(options or {})}
    if flat_wiring_is_of(first_card(cards), merged, device_of):
        return {}
    return flat_wiring(merged)


def registry_device_of(hass) -> DeviceOf:
    """An entity id → its HA device id, through the entity registry."""
    from homeassistant.helpers import entity_registry as er
    ereg = er.async_get(hass)

    def _device_of(eid: str) -> Optional[str]:
        ent = ereg.async_get(eid)
        return getattr(ent, "device_id", None) if ent else None
    return _device_of


def reconcile(*, data_list: Optional[list], legacy: Optional[list],
              refs: Optional[list], sig: Optional[str],
              device_of: DeviceOf,
              live_by_device: Dict[str, Dict[str, Any]],
              log: Callable[[str], None] = _LOGGER.info,
              refuse: Optional[Refuse] = None,
              sure: Optional[Iterable[str]] = None,
              own: Optional[Iterable[str]] = None,
              ) -> Optional[Tuple[List[dict], List[dict]]]:
    """The whole setup step, pure. Returns ``(refs, resolved)`` or None when
    there is nothing to manage (no charger list was ever stored).

    (#1144) ``refuse`` names the keys of a charger SEM must never drive —
    or (#1143) read as the charge; they leave the crawler's answer and every
    ref before anything resolves.

    (#1147, #1152) ``sure`` names the devices the crawler saw whole, and
    ``own`` the ids setup gives the boxes it finds. Given ``sure`` (the
    setup step always gives it, maybe empty), a role the crawler stopped
    giving on such a device is forgotten; given ``own`` too, a plug an
    older start added to setup's own save is checked once. Left out, the
    step does not run."""
    if refuse is not None:
        live_by_device = {dev: _without(roles, set(refuse(roles)))
                          for dev, roles in live_by_device.items()}
        # a site limit sits on the site's device: it must not decide which
        # device a card is (the Go's crawler answer would never show)
        _device_of = device_of

        def device_of(eid: str) -> Optional[str]:
            if refuse({"ev_current_control_entity": eid}):
                return None
            return _device_of(eid)
    # (#1151) what each charger ran on before this start: the stored list
    ran = {c["id"]: c for c in _union_by_id(data_list, legacy)}
    stored = {r.get("id") for r in refs or () if isinstance(r, dict)}
    if refs is None:
        cards = list(ran.values())
        if not cards:
            return None
        refs = refs_from_cards(cards, device_of, live_by_device, log)
        log(f"chargers stored as device references: {[r['id'] for r in refs]}")
    elif legacy is not None and signature(legacy) != sig:
        refs = apply_legacy_edit(refs, legacy, device_of, live_by_device, log)
    # (#1214) at every start: a ref moved before this fix is set right too
    if sure is not None:
        refs = follow_device(refs, device_of, live_by_device, sure, log)
    ran = {r["id"]: ran.get(r["id"]) or resolve(r) for r in refs}
    refs = refresh_found(refs, live_by_device)
    if refuse is not None:
        refs = drop_refused(refs, live_by_device, refuse)
    if sure is not None:
        refs = forget_stale(refs, live_by_device, sure, log)
    if sure is not None and own is not None:
        refs, ran = check_saved_plugs(
            refs, ran, live_by_device, sure=sure, own=own,
            fresh=[r["id"] for r in refs if r["id"] not in stored],
            refuse=refuse, log=log)
    refs = hold_new_state(refs, ran, live_by_device, refuse, log)
    resolved = [resolve(r, live_by_device.get(r.get("device_id"))
                        if r.get("device_id") else None) for r in refs]
    return refs, resolved


def _union_by_id(data_list: Optional[list], opts_list: Optional[list]) -> List[dict]:
    """The two old stores, options winning per id, data's order first — what
    the old start-up heal produced."""
    out: List[dict] = []
    seen: Dict[str, int] = {}
    for src in (data_list or [], opts_list or []):
        for c in src:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            if c["id"] in seen:
                out[seen[c["id"]]] = {**out[seen[c["id"]]], **c}
            else:
                seen[c["id"]] = len(out)
                out.append(dict(c))
    return out


# ── Home Assistant ───────────────────────────────────────────────────────

def live_charger_roles(hass) -> Dict[str, Dict[str, Any]]:
    """The crawler's answer per device: ``{device_id: {role: value}}``.

    The detection report with nothing configured, so every device is walked:
    a brand row's mapping, or a near miss's complete offer."""
    from .hardware_detection import build_detection_report
    try:
        report = build_detection_report(hass, configured_chargers=[])
    except Exception:  # noqa: BLE001 — a blind crawler keeps the last answer
        _LOGGER.debug("crawler unavailable for charger refs", exc_info=True)
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in report.get("chargers") or []:
        dev = row.get("device_id")
        if not dev:
            continue
        roles = {k: (v.get("entity") or v.get("value"))
                 for k, v in (row.get("mapped") or {}).items()
                 if k in ROLE_KEYS and isinstance(v, dict)}
        if roles:
            out.setdefault(dev, {}).update({k: v for k, v in roles.items() if v})
    for near in report.get("near_misses") or []:
        dev = near.get("device_id")
        offer = near.get("suggested_charger") or {}
        if dev and offer:
            out.setdefault(dev, {}).update(
                {k: v for k, v in offer.items() if k in ROLE_KEYS and v})
    return out


def sure_devices(hass, devices: Iterable[str]) -> set:
    """(#1147) The devices whose crawler answer is whole.

    Home Assistant has finished starting (``CoreState.running``: before
    that the crawler may read no states, a select's options or a status
    sensor's words), every integration the device belongs to is loaded,
    and each of its enabled entities has a state (an integration still
    adding them shows part of the device). Any doubt: not sure, and the
    device keeps what was found before."""
    from homeassistant.core import CoreState
    # ``is_running`` is true while Home Assistant is still starting too
    if hass is None or getattr(hass, "state", None) is not CoreState.running:
        return set()
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    dreg, ereg = dr.async_get(hass), er.async_get(hass)
    out = set()
    for dev in devices or ():
        device = dreg.async_get(dev)
        if device is None or not device.config_entries:
            continue
        loaded = [hass.config_entries.async_get_entry(eid)
                  for eid in device.config_entries]
        if any(e is None or e.state is not ConfigEntryState.LOADED
               for e in loaded):
            continue
        ents = er.async_entries_for_device(ereg, dev)
        if not ents or any(hass.states.get(e.entity_id) is None for e in ents):
            continue
        out.add(dev)
    return out


def own_save_ids(hass) -> Optional[set]:
    """(#1152) The ids setup gives the boxes the crawler finds — the startup
    heal's rule for "SEM saved this itself". None when it cannot ask."""
    from . import _own_saves
    try:
        return set(_own_saves(hass))
    except Exception:  # noqa: BLE001 — no answer: nothing is checked or marked
        _LOGGER.debug("own charger saves unavailable", exc_info=True)
        return None


def async_reconcile(hass, entry) -> Optional[List[dict]]:
    """Setup step: refs ← (first start) the old stores, or (a writer changed
    the legacy list) that change. Writes the refs, the resolved legacy copy
    and its fingerprint; drops ``entry.data``'s list. Raises/clears the
    charger Repairs. Returns the resolved list, or None when SEM manages no
    charger list on this install."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    options = dict(entry.options or {})
    data = dict(entry.data or {})
    ereg = er.async_get(hass)
    dreg = dr.async_get(hass)

    def _device_of(eid: str) -> Optional[str]:
        ent = ereg.async_get(eid)
        return getattr(ent, "device_id", None) if ent else None

    from .hardware_detection import link_as_charging, site_limit_controls

    def _refuse(card: Dict[str, Any]) -> Tuple[str, ...]:
        return (site_limit_controls(card, ereg.async_get)
                + link_as_charging(card, ereg.async_get))

    # (#1144) the primary charger's old flat keys are read when its card
    # has none: a site limit there would come back the moment the card's
    # is gone. (#1143) The setup wizard saved them too, the online sensor
    # as the charge among them, and the reader reads the flat one.
    flat = {}
    for name, store in (("data", data), ("options", options)):
        flat[name] = {k: store.pop(k) for k in _refuse(store)}
        if flat[name]:
            _log_refused(f"Saved setting ({name})", flat[name])

    live = live_charger_roles(hass)
    stored = options.get(REFS_KEY)
    # (#1214) a device a saved charger's entities sit on may give the
    # crawler no answer (a user's own integration); it can be seen whole too
    named = set()
    for c in [*(stored or ()), *(options.get(LEGACY_KEY) or ())]:
        if not isinstance(c, dict):
            continue
        for part in (c, c.get("overrides") or {}, c.get("found") or {}):
            named.update(_device_of(str(part[k])) for k in CHARGER_ENTITY_KEYS
                         if part.get(k))
    named.discard(None)
    # (#1152) only an older ref can hold a plug no check asked about
    unchecked = isinstance(stored, list) and any(
        isinstance(r, dict) and r.get("device_id") and not r.get(PLUG_CHECKED)
        for r in stored)
    out = reconcile(
        data_list=data.get(LEGACY_KEY), legacy=options.get(LEGACY_KEY),
        refs=stored, sig=options.get(SIG_KEY),
        device_of=_device_of, live_by_device=live,
        refuse=_refuse, sure=sure_devices(hass, set(live) | named),
        own=own_save_ids(hass) if unchecked else ())
    refs, resolved = out if out is not None else (None, None)
    new_options = options if out is None else {
        **options, REFS_KEY: refs, LEGACY_KEY: resolved,
        SIG_KEY: signature(resolved)}
    update: Dict[str, Any] = {}
    if new_options != dict(entry.options or {}):
        update["options"] = new_options
    if out is not None and LEGACY_KEY in data:
        data.pop(LEGACY_KEY)
        update["data"] = data
    if flat["data"]:
        update["data"] = data
    if update:
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None and "options" in update:
            coordinator._skip_options_reload = dict(new_options)
        hass.config_entries.async_update_entry(entry, **update)
    if out is None:
        return None

    _sync_repairs(hass, refs, problems(
        refs, resolved,
        device_exists=lambda d: dreg.async_get(d) is not None,
        entity_exists=lambda e: _entity_usable(ereg, hass, e)))
    return resolved


def _entity_usable(ereg, hass, entity_id: str) -> bool:
    """In the registry and not disabled — or, for an entity with no registry
    entry (a template, a YAML sensor), it has a state."""
    ent = ereg.async_get(entity_id)
    if ent is not None:
        return not ent.disabled_by
    return hass.states.get(entity_id) is not None


def _sync_repairs(hass, refs: List[dict], found: List[dict]) -> None:
    from homeassistant.helpers import issue_registry as ir
    from .const import DOMAIN

    kinds = ("charger_device_gone", "charger_role_missing",
             "charger_role_entity_gone")
    want = {}
    for p in found:
        suffix = p.get("entity", "")
        want[f"{p['kind']}_{p['id']}{('_' + suffix) if suffix else ''}"] = p
    try:
        reg = ir.async_get(hass)
        for (domain, issue_id) in list(reg.issues):
            if domain == DOMAIN and issue_id.startswith(kinds) \
                    and issue_id not in want:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
        for issue_id, p in want.items():
            ir.async_create_issue(
                hass, DOMAIN, issue_id, is_fixable=False, is_persistent=False,
                severity=ir.IssueSeverity.WARNING, translation_key=p["kind"],
                translation_placeholders={k: str(v) for k, v in p.items()
                                          if k not in ("kind",)})
    except Exception:  # noqa: BLE001 — a Repair never costs a setup
        _LOGGER.debug("charger repairs failed", exc_info=True)
