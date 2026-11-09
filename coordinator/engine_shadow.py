"""(#1102) The three-layer load engine, run beside the imperative passes.

Every real install switches loads with the imperative passes in
``SurplusController.update()``; the three layers (``compute_load_intent`` →
``_desired_intents`` → ``reconcile_load``) only switch in observer mode. Before
the layers may lead, they must be shown to decide the same — or every
difference must be understood. This module records where they differ, live,
with zero effect on what the passes switch.

* ``snapshot`` / ``restore`` keep a dry intent walk from leaving any trace on
  the controller or the devices (the layer-1 Off branch and the layer-2
  battery bookkeeping write state; a few properties latch log flags).
* ``disagreement`` compares one device after the passes ran.
* ``EngineShadow`` keeps CHANGES only — a difference that starts, changes
  its reason, or ends — in a ring of 200, plus counts and a small summary.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

#: Power differences at or under this are measurement noise, not a decision.
POWER_TOLERANCE_W = 100.0
#: The summary rides a sensor attribute; the recorder budget is 16 KB.
SUMMARY_MAX_BYTES = 1900
RECORDS_MAX = 200


def snapshot(controller: Any, devices) -> list:
    """Everything a dry intent walk could touch, to put back afterwards."""
    saved = [("__ctl__", controller, {"_tier1_budget_left": getattr(controller, "_tier1_budget_left", 0.0)})]
    for d in devices:
        vals = dict(getattr(d, "__dict__", {}))
        status = vals.get("status")
        status_vals = dict(status.__dict__) if status is not None and hasattr(status, "__dict__") else None
        saved.append((d, vals, status_vals))
    return saved


def restore(saved: list) -> None:
    """Put back what ``snapshot`` saved — attributes AND the status object
    in place (its identity is kept; only its fields are reset)."""
    for item in saved:
        if item[0] == "__ctl__":
            for k, v in item[2].items():
                setattr(item[1], k, v)
            continue
        d, vals, status_vals = item
        d.__dict__.clear()
        d.__dict__.update(vals)
        status = vals.get("status")
        if status_vals is not None and status is not None:
            status.__dict__.clear()
            status.__dict__.update(status_vals)


def start_blocked(device: Any, now: datetime) -> bool:
    """Would the anti-cycle rules refuse a start right now? A read-only twin
    of ``can_activate`` — that one starts the activation-delay timer, and a
    comparison must never change what the passes do next cycle."""
    try:
        if isinstance(getattr(device, "_phase_hold", None), str):
            return True
        if getattr(device, "daily_max_runtime_reached", False) is True:
            return True
        deps = getattr(device, "_check_dependencies", None)
        if callable(deps) and deps() is False:
            return True
        until = getattr(device, "_external_off_until", None)
        if isinstance(until, datetime) and now < until:
            return True
        min_off = float(getattr(device, "min_off_seconds", 0) or 0)
        last_off = getattr(device, "_last_deactivated", None)
        if min_off > 0 and isinstance(last_off, datetime) and (now - last_off).total_seconds() < min_off:
            return True
        delay = float(getattr(device, "activation_delay_seconds", 0) or 0)
        if delay > 0:
            since = getattr(device, "_surplus_since", None)
            if not isinstance(since, datetime) or (now - since).total_seconds() < delay:
                return True
    except Exception:  # noqa: BLE001 — unknown is not blocked
        return False
    return False


def stop_blocked(device: Any) -> bool:
    """Would the minimum on-time refuse a stop? (``can_deactivate`` is a read.)"""
    try:
        fn = getattr(device, "can_deactivate", None)
        return callable(fn) and fn() is False
    except Exception:  # noqa: BLE001
        return False


def _old_why(device: Any, on: bool) -> str:
    if not on:
        return "off"
    if getattr(device, "_offpeak_forced", False) is True:
        return "cheap-hours grid"
    if getattr(device, "_batt_overnight_forced", False) is True:
        return "overnight battery"
    if getattr(device, "runs_without_surplus", False) is True:
        return "own run"
    return "running"


def disagreement(device: Any, intent: Any, *, was_on: bool, now: datetime) -> Optional[Dict[str, Any]]:
    """How the passes' result differs from the layered intent, or None.

    * ``on_off`` — one engine runs it, the other does not. Where the passes
      left the load as it was and the minimum on/off times or the activation
      delay would block the change anyway, it is not counted (both engines
      wait for those); a stop or start the passes made always counts.
    * ``power`` — both run it, more than 100 W apart (only for a load that
      was already running: a fresh start has no measurement yet).
    * ``marker`` — both run it, but on a different paid source.
    """
    if intent is None or getattr(device, "locked_by_operator", False) is True:
        return None
    on = bool(getattr(device, "is_active", False))
    try:
        power = float(device.get_current_consumption() or 0.0) if on else 0.0
    except Exception:  # noqa: BLE001
        power = 0.0
    kinds: List[str] = []
    if bool(intent.on) != on:
        # The timers excuse a difference only where the passes changed
        # nothing this cycle: a stop or start the passes MADE is their
        # decision, whatever the timers say about undoing it.
        if on == was_on:
            if intent.on and not on and start_blocked(device, now):
                return None
            if on and not intent.on and stop_blocked(device):
                return None
        kinds.append("on_off")
    elif on:
        if was_on and abs(float(intent.power_w or 0.0) - power) > POWER_TOLERANCE_W:
            kinds.append("power")
        want_grid = intent.source == "cheap_grid"
        want_batt = intent.source == "tier2_battery"
        if (bool(getattr(device, "_offpeak_forced", False)) != want_grid
                or bool(getattr(device, "_batt_overnight_forced", False)) != want_batt):
            kinds.append("marker")
    if not kinds:
        return None
    return {
        "kinds": kinds,
        "old": {"on": on, "power_w": round(power), "why": _old_why(device, on)},
        "new": {"on": bool(intent.on), "power_w": round(float(intent.power_w or 0.0)),
                "source": intent.source, "reason": str(intent.reason or "")[:160],
                "reason_code": getattr(intent, "reason_code", "") or ""},
    }


class EngineShadow:
    """Where the two engines differ: changes only, counts, a small summary."""

    def __init__(self, maxlen: int = RECORDS_MAX) -> None:
        self._records: deque = deque(maxlen=maxlen)
        self._open: Dict[str, tuple] = {}
        self._open_rows: Dict[str, Dict[str, Any]] = {}
        self._total = 0
        self._by_device: Dict[str, int] = {}
        self._by_kind: Dict[str, int] = {}
        self._kinds_seen: set = set()
        self._cycles = 0

    def compare(self, intents: Dict[str, Any], devices, *, was_on: Dict[str, bool],
                now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        self._cycles += 1
        current: Dict[str, Dict[str, Any]] = {}
        for d in devices:
            did = getattr(d, "device_id", None)
            if did is None:
                continue
            diff = disagreement(d, intents.get(did), was_on=bool(was_on.get(did, False)), now=now)
            if diff is not None:
                diff["name"] = str(getattr(d, "name", did))
                current[did] = diff
        for did, diff in current.items():
            sig = (tuple(diff["kinds"]), diff["new"]["reason_code"] or diff["new"]["reason"],
                   diff["old"]["on"], diff["new"]["on"])
            if self._open.get(did) == sig:
                continue
            self._add("start" if did not in self._open else "change", did, diff, now)
            self._total += 1
            self._by_device[did] = self._by_device.get(did, 0) + 1
            for k in diff["kinds"]:
                self._by_kind[k] = self._by_kind.get(k, 0) + 1
                if k not in self._kinds_seen:
                    self._kinds_seen.add(k)
                    _LOGGER.info("Load engines differ (%s) for %s: old %s, new %s (%s)",
                                 k, diff["name"], diff["old"]["why"],
                                 "on" if diff["new"]["on"] else "off", diff["new"]["reason"])
            self._open[did] = sig
            self._open_rows[did] = diff
        for did in [x for x in self._open if x not in current]:
            ended = dict(self._open_rows.get(did) or {})
            self._add("end", did, ended, now)
            self._open.pop(did, None)
            self._open_rows.pop(did, None)

    def _add(self, event: str, did: str, diff: Dict[str, Any], now: datetime) -> None:
        row = {"t": now.isoformat(timespec="seconds"), "event": event, "device_id": did,
               "name": diff.get("name", did), "kinds": list(diff.get("kinds", [])),
               "old": diff.get("old"), "new": diff.get("new")}
        self._records.append(row)
        _LOGGER.debug("Load engine shadow %s: %s", event, row)

    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def summary(self, max_bytes: int = SUMMARY_MAX_BYTES) -> Dict[str, Any]:
        """Counts and the last five changes, kept under ``max_bytes`` as JSON."""
        top = dict(sorted(self._by_device.items(), key=lambda kv: -kv[1])[:10])
        last = []
        for r in list(self._records)[-5:]:
            new = dict(r.get("new") or {})
            new["reason"] = str(new.get("reason", ""))[:80]
            last.append({"t": r["t"], "event": r["event"], "device": r["name"][:40],
                         "kinds": r["kinds"], "old": r.get("old"), "new": new})
        # (no cycle counter here: the summary is a sensor attribute and must
        # only change when a difference does — a per-cycle change writes a
        # recorder row every 10 s)
        out = {"disagreements": self._total, "open": len(self._open),
               "by_kind": dict(self._by_kind), "by_device": top, "last": last}
        while len(json.dumps(out, default=str)) > max_bytes and out["last"]:
            out["last"] = out["last"][1:]
        return out
