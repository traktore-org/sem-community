"""(#1081) The setpoint a unit had before SEM moved it, and its way back.

A load SEM steers by the unit's own setpoint (a climate unit, a heat pump
with a climate entity, a water_heater tank) used to get the CONFIGURED
setpoint back at the end of a run, or none at all. A setpoint the user, or
the unit's own schedule, had set was lost after every run.

Now the setpoint the unit shows just before SEM's first write is remembered
(kept by the coordinator beside the step-down memo, #1323, so a restart keeps
it) and written back when the run ends. Three rules keep it from ever
fighting the user:

* the unit no longer shows what SEM wrote: someone changed it by hand, so the
  memo is dropped and nothing is written;
* the unit already shows the remembered value: nothing is written;
* a memo older than 48 h is dropped without a write.

A setpoint that cannot be read at the start is not remembered; the caller
then keeps what it did before (the configured normal, or nothing).
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional

from ..utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)

#: a memo older than this is dropped without a write
SETPOINT_MEMO_MAX_AGE_S = 48 * 3600.0
#: how far a unit may round what SEM wrote and still count as SEM's value
SETPOINT_MATCH_K = 0.5
#: a value this close to the remembered one is already back
SETPOINT_SAME_K = 0.05


#: (#1396) After the device refuses a setpoint, the next try waits this long
#: (one step per refusal in a row, the last repeats). A cloud unit refused a
#: target every 10 s — some 8,600 calls a day against a per-account limit.
SETPOINT_BACKOFF_S = (5 * 60.0, 15 * 60.0, 60 * 60.0)


def _mono() -> float:
    """Monotonic seconds; a function so tests can move the clock."""
    return time.monotonic()


def _now() -> float:
    return time.time()


def _num(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


class SetpointMemoMixin:
    """Mixed into ``ControllableDevice``. Class-level defaults, so a device
    built without ``__init__`` (a fixture) still has them."""

    _sp_memo: Optional[Dict[str, Any]] = None
    _sp_pending: Optional[float] = None
    _sp_seeded: bool = False

    # ── reading ─────────────────────────────────────────────────────────

    def _sp_read(self, entity_id: Optional[str]) -> Optional[float]:
        """The unit's own target, in the unit it shows, or None."""
        hass = getattr(self, "hass", None)
        if not (hass and entity_id):
            return None
        state = hass.states.get(entity_id)
        attrs = getattr(state, "attributes", None) or {}
        return _num(attrs.get("temperature"))

    def _sp_tol(self, entity_id: Optional[str]) -> float:
        """How far a unit may round what SEM wrote: half a degree, or half
        the unit's own step when that is larger (a 5 K step)."""
        hass = getattr(self, "hass", None)
        state = hass.states.get(entity_id) if (hass and entity_id) else None
        step = _num((getattr(state, "attributes", None) or {}).get("target_temp_step"))
        return max(SETPOINT_MATCH_K, (step or 0.0) / 2.0)

    def _sp_fresh(self, memo: Dict[str, Any]) -> bool:
        at = _num(memo.get("at"))
        return at is not None and 0 <= _now() - at <= SETPOINT_MEMO_MAX_AGE_S

    # ── before the write ────────────────────────────────────────────────

    def _sp_restore_hint(self) -> Optional[float]:
        """A setpoint better than the one the unit shows now, or None. A heat
        pump stepped down shows SEM's LOWERED setpoint: its hint is the one
        the user had, so a boost does not take the lowered one for theirs."""
        return None

    def _sp_begin(self, entity_id: str, target: float) -> None:
        """Decide what a run's end writes back: the value the unit shows now,
        or, while the memo is still SEM's own, the one already remembered."""
        live = self._sp_read(entity_id)
        memo = self._sp_memo
        self._sp_pending = None
        if memo and self._sp_fresh(memo) and live is not None \
                and abs(live - float(memo["wrote"])) <= self._sp_tol(entity_id):
            self._sp_pending = float(memo["restore"])   # still SEM's own run
            return
        hint = _num(self._sp_restore_hint())
        if hint is not None:
            self._sp_pending = hint
            return
        if live is None:
            log_on_change(
                _LOGGER, f"setpoint-memo:{self.device_id}", logging.INFO,
                "%s: setpoint of %s cannot be read — SEM cannot remember it "
                "and does what it did before (#1081)", self.name, entity_id)
            return
        # equal to the target too: the end then finds the unit at the value to
        # restore and writes nothing.
        # Known gap (#1081 review, low): when an earlier memo EXPIRED (48 h)
        # while the unit still showed SEM's value, that value is taken here as
        # the user's own. Same outcome as the expiry itself; not worth a store.
        self._sp_pending = live

    def _sp_commit(self, domain: str, entity_id: str, target: float,
                   sent: bool) -> None:
        """Keep the memo only when the write really went out."""
        pending, self._sp_pending = self._sp_pending, None
        if not sent:
            return
        if pending is None:
            self._sp_memo = None
            return
        kept = self._sp_memo if (self._sp_memo and abs(
            float(self._sp_memo["restore"]) - pending) < 1e-9
            and self._sp_fresh(self._sp_memo)) else None
        self._sp_memo = {
            "restore": pending, "wrote": float(target),
            "at": kept["at"] if kept else _now(),
            "entity": entity_id, "domain": domain}

    def _sp_capped(self, entity_id: Optional[str], target: float) -> float:
        """(#1396) The target inside the unit's own ``min_temp``/``max_temp``:
        a value outside them is refused by the device, every time."""
        hass = getattr(self, "hass", None)
        state = hass.states.get(entity_id) if (hass and entity_id) else None
        attrs = getattr(state, "attributes", None) or {}
        lo, hi = _num(attrs.get("min_temp")), _num(attrs.get("max_temp"))
        capped = float(target)
        if hi is not None and capped > hi:
            capped = hi
        if lo is not None and capped < lo:
            capped = lo
        if capped != float(target):
            log_on_change(
                _LOGGER, f"setpoint-cap:{getattr(self, 'device_id', '')}",
                logging.INFO,
                "%s: %.1f is outside what %s takes (%s–%s) — SEM writes %.1f "
                "(#1396)", getattr(self, "name", ""), float(target), entity_id,
                lo, hi, capped)
        return capped

    @property
    def sp_refused(self) -> bool:
        """(#1396) The unit refused SEM's setpoint and the next try waits."""
        until = getattr(self, "_sp_retry_at", None)
        return until is not None and _mono() < until

    async def sp_write_target(self, domain: str, entity_id: str, target: float,
                              why: str = "") -> bool:
        """``set_temperature`` to SEM's target, remembering the setpoint the
        unit shows first. Returns what ``send`` returns.

        (#1396) The target is capped at the unit's own range. A write the unit
        refuses (the service raises) returns False and the next try waits
        5, 15, then 60 minutes — said once per wait, not every cycle. A
        changed target or a write that lands starts afresh."""
        target = self._sp_capped(entity_id, target)
        key = (entity_id, round(float(target), 2))
        if getattr(self, "_sp_refused_key", None) != key:
            self._sp_refusals, self._sp_retry_at = 0, None
        elif self.sp_refused:
            return False
        self._sp_begin(entity_id, target)
        try:
            sent = await self.send(
                domain, "set_temperature",
                {"entity_id": entity_id, "temperature": target}, why=why)
        except Exception as e:  # noqa: BLE001 — the device said no
            self._sp_pending = None
            n = int(getattr(self, "_sp_refusals", 0) or 0)
            wait = SETPOINT_BACKOFF_S[min(n, len(SETPOINT_BACKOFF_S) - 1)]
            self._sp_refusals, self._sp_refused_key = n + 1, key
            self._sp_retry_at = _mono() + wait
            _LOGGER.warning(
                "%s: %s refused the setpoint %.1f (%s) — SEM tries again in "
                "%d min (#1396)", getattr(self, "name", ""), entity_id,
                float(target), e, int(wait // 60))
            return False
        if sent:
            self._sp_refusals, self._sp_retry_at, self._sp_refused_key = 0, None, None
        self._sp_commit(domain, entity_id, target, bool(sent))
        return bool(sent)

    # ── the way back ────────────────────────────────────────────────────

    async def sp_restore(self, why: str = "setpoint restored") -> str:
        """Write the remembered setpoint back. Returns ``none`` (no memo),
        ``written``, ``unchanged``, ``hand_changed``, ``expired``,
        ``unreadable``, ``withheld`` or ``failed``. Only ``unreadable``,
        ``withheld`` and ``failed`` keep the memo for a later try."""
        memo = self._sp_memo
        if not memo:
            return "none"
        if not self._sp_fresh(memo):
            self._sp_memo = None
            return "expired"
        entity, domain = memo.get("entity"), memo.get("domain") or "climate"
        live = self._sp_read(entity)
        if live is None:
            return "unreadable"
        restore = float(memo["restore"])
        if abs(live - restore) <= SETPOINT_SAME_K:
            self._sp_memo = None
            return "unchanged"
        if abs(live - float(memo["wrote"])) > self._sp_tol(entity):
            self._sp_memo = None   # the user's own change: never fight it
            _LOGGER.info("%s: %s was changed by hand during the run — "
                         "its setpoint is left as it is (#1081)",
                         self.name, entity)
            return "hand_changed"
        try:
            sent = await self.send(
                domain, "set_temperature",
                {"entity_id": entity, "temperature": restore}, why=why)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("%s: could not restore the setpoint of %s: %s",
                            self.name, entity, e)
            return "failed"
        if not sent:
            return "withheld"
        self._sp_memo = None
        _LOGGER.info("%s: setpoint of %s put back to %.1f (#1081)",
                     self.name, entity, restore)
        return "written"

    async def sp_release_orphan(self, why: str = "setpoint restored") -> str:
        """A memo with no run behind it (a restart, a withheld restore): the
        coordinator calls this for a load SEM believes idle. A climate unit
        that is off is not written to (some integrations switch on when given
        a temperature): the memo waits, to the 48 h cap, until it runs again."""
        memo = self._sp_memo
        if not memo or getattr(self, "is_active", False):
            return "none"
        hass = getattr(self, "hass", None)
        state = hass.states.get(memo.get("entity")) if hass else None
        if memo.get("domain") == "climate" and str(
                getattr(state, "state", "")).lower() == "off":
            return "off"
        return await self.sp_restore(why)

    # ── across a restart ────────────────────────────────────────────────

    def sp_memo(self) -> Optional[Dict[str, Any]]:
        """What a restart must know, or None."""
        memo = self._sp_memo
        return dict(memo) if memo and self._sp_fresh(memo) else None

    def sp_adopt_memo(self, memo) -> bool:
        """Re-own a stored memo. Not believed on its own: the restore reads
        the unit first and drops it unless the unit still shows SEM's value."""
        self._sp_seeded = True
        if not isinstance(memo, dict) or self._sp_memo:
            return False
        restore, wrote = _num(memo.get("restore")), _num(memo.get("wrote"))
        if restore is None or wrote is None or not memo.get("entity"):
            return False
        clean = {"restore": restore, "wrote": wrote, "at": _num(memo.get("at")),
                 "entity": str(memo["entity"]),
                 "domain": str(memo.get("domain") or "climate")}
        if not self._sp_fresh(clean):
            return False
        self._sp_memo = clean
        return True
