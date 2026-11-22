"""(#1180) The pack's charge-target number, put back after a forced charge.

GoodWe and the generic switch setup write SEM's charge target into the
``battery_target_soc_entity`` number when a grid charge starts. On many
inverters that number is the pack's standing upper limit
(``soc_upper_limit``, ``battery_max_charge_soc`` …). The stop turned the
switch or the mode back and never wrote the old value back, so a night
charge to 60 % left the pack stopping at 60 % on every sunny day after.

The rules are charge pacing's (#949, #820), for the same reasons:

* the value is SAVED before SEM's first write and PUT BACK on the stop;
* the saved value is PERSISTED, so the next lifetime adopts it instead of
  saving SEM's own 60 % as the user's value (an HA restart never unloads
  the entry, so the number keeps SEM's value across it);
* a number whose value cannot be read is never written: the saved value is
  the only way back. Nor is one whose record could not be read or saved;
* EVERY value SEM wrote since the save is remembered, and a number reading
  any of them is SEM's write not yet read back, never the user's setting
  (class 95). A target can rise during a charge (60, then 70), and two
  packs on one number can ask for two;
* the put-back is not done when it is sent, but when a read shows it
  landed. Until then it is PENDING: tried again on a cycle with no forced
  charge, at most ``MAX_TRIES`` times ``RETRY_S`` apart, never by sending
  the whole stop again (class 108). A number that reads neither SEM's
  values nor the saved one was set by the user: that ends it too. Only
  then is the memory of SEM's values dropped — a user who later picks one
  of them on purpose is not overruled.

ONE hold per config entry, keyed by the ENTITY and shared by every
battery: there is no per-battery target list, so two packs behind one
inverter write the same number. A hold per battery would let the second
pack save the first one's 60 % as its own value to put back.

The store is injected at runtime and duck-typed (``async_load`` /
``async_save``), like ``ChargePacingWriter``'s, so this module stays free
of Home Assistant imports.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from ...utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)


@dataclass
class _Target:
    #: the value to put back (as SEM found it); None = lost
    prior: Optional[float]
    #: every value SEM wrote since the save
    sent: list = field(default_factory=list)
    #: SEM's value is on the number now (a charge holds it)
    held: bool = False
    #: the put-back has not been seen to land
    pending: bool = False
    #: put-backs sent while pending, and when the last one went
    tries: int = 0
    tried_at: Optional[float] = None
    #: held in the last lifetime: read again before SEM writes over it
    adopted: bool = False


def _as_number(raw) -> Optional[float]:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _wire(value: float):
    """Whole numbers go out as int, as the charge target always did."""
    return int(value) if float(value).is_integer() else float(value)


class ChargeTargetHold:
    """What SEM put on each charge-target number, and what goes back."""

    #: a put-back the number has not taken is sent again no faster than this
    RETRY_S: float = 300.0
    #: …and no more often than this, then SEM says so and stops
    MAX_TRIES: int = 3
    #: the longest a put-back may hold the cycle
    SEND_TIMEOUT_S: float = 10.0

    def __init__(self, hass, store: Any = None,
                 configured: Iterable[str] = ()) -> None:
        self._hass = hass
        self._store = store
        #: the target entities SEM's config names now; a held one that is
        #: not among them is put back (the user moved the setting)
        self._configured = {str(e) for e in configured if e}
        self._targets: dict[str, _Target] = {}
        self._adopted = store is None
        #: the record could not be read: SEM cannot tell its own value from
        #: the user's, so it writes no target this lifetime
        self._blind = False
        self._lock = asyncio.Lock()
        self._clock = time.monotonic

    # ─── the commands ────────────────────────────────────────────────

    async def write(self, entity_id: str, value: float) -> bool:
        """Save the number's value (first write only), then write ``value``.

        False when nothing was written: the value could never be put back.
        The charge goes on without it — the scheduler stops the charge at
        its own target anyway."""
        entity_id = str(entity_id)
        value = float(value)
        async with self._lock:
            await self._adopt()
            if self._blind:
                self._say(entity_id, logging.WARNING,
                          "Battery: SEM could not read its record of %s — it "
                          "writes no charge target there until the next start "
                          "(#1180)", entity_id)
                return False
            t = self._targets.get(entity_id)
            new = t if t is not None and t.held and not t.adopted else None
            if new is None:
                read = self._read(entity_id)
                if read is None:
                    self._say(entity_id, logging.WARNING,
                              "Battery: %s cannot be read — SEM does not write "
                              "its charge target there, as the value could not "
                              "be put back (#1180)", entity_id)
                    return False
                tol = self._tol(entity_id)
                sent = list(t.sent) if t is not None else []
                if any(abs(read - v) < tol for v in sent):
                    # SEM's own value, not yet read back (class 95)
                    prior = t.prior
                elif t is not None and t.prior is not None and abs(read - t.prior) < tol:
                    prior = t.prior
                else:
                    prior, sent = read, []      # the user's own value
                if prior is None:
                    self._say(entity_id, logging.WARNING,
                              "Battery: %s reads SEM's own %s and the value it "
                              "had before is lost — SEM writes no charge target "
                              "there; check its value (#1180)", entity_id, read)
                    return False
                new = _Target(prior=prior, sent=sent, held=True)
            grows = not any(abs(value - v) < 0.5 for v in new.sent)
            if grows:
                new.sent = [*new.sent, value]
            if new is not t or grows:
                # saved BEFORE the write: the record must describe a number
                # that may already carry SEM's value (#949). No record, no
                # write — the next lifetime would take SEM's value for the
                # user's.
                old = self._targets.get(entity_id)
                self._targets[entity_id] = new
                if not await self._save():
                    if old is None:
                        self._targets.pop(entity_id, None)
                    else:
                        self._targets[entity_id] = old
                    if grows and new is old:
                        new.sent = new.sent[:-1]
                    self._say(entity_id, logging.WARNING,
                              "Battery: SEM could not save the value of %s — "
                              "it does not write its charge target there "
                              "(#1180)", entity_id)
                    return False
                if new is not t:
                    self._say(entity_id, logging.INFO,
                              "Battery: %s saved at %s before SEM's charge "
                              "target (#1180)", entity_id, new.prior)
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": entity_id, "value": _wire(value)},
            )
            return True

    async def put_back(self, entity_id: str) -> None:
        """The stop: write the saved value back now."""
        async with self._lock:
            await self._adopt()
            t = self._targets.get(str(entity_id or ""))
            if t is not None and t.held:
                t.held, t.pending, t.tries, t.tried_at = False, True, 0, None
                await self._send_back(str(entity_id), t)
                await self._save()

    async def release(self, entity_id: str) -> None:
        """A start that failed after the target went out: nothing charges,
        so the value goes back — ``RETRY_S`` later on a cycle with no forced
        charge, not now: a switch that keeps failing would flip the number
        on every cycle of the block (the block's own retries take it over
        again and restart the wait)."""
        async with self._lock:
            await self._adopt()
            t = self._targets.get(str(entity_id or ""))
            if t is not None and t.held:
                t.held, t.pending, t.tries = False, True, 0
                t.tried_at = self._clock()
                await self._save()

    async def settle(self) -> None:
        """A cycle with no forced charge: see whether each put-back landed,
        and send the ones that did not."""
        async with self._lock:
            await self._adopt()
            changed = False
            for entity_id, t in list(self._targets.items()):
                if t.held or not t.pending:
                    continue
                read = self._read(entity_id)
                if read is None:
                    continue                    # unreadable: wait, send nothing
                tol = self._tol(entity_id)
                ours = any(abs(read - v) < tol for v in t.sent)
                at_prior = t.prior is not None and abs(read - t.prior) < tol
                if (not ours and not at_prior) or (t.tries and at_prior):
                    # the user set a value of their own — or a put-back that
                    # went out reads back. A put-back never sent is sent
                    # once whatever the read says: it may predate SEM's write.
                    del self._targets[entity_id]
                    changed = True
                    self._say(entity_id, logging.INFO,
                              "Battery: %s reads %s — SEM's charge target is "
                              "gone (#1180)", entity_id, read)
                    continue
                if t.prior is None:
                    continue                    # nothing known to put back
                if t.tries >= self.MAX_TRIES:
                    self._say(entity_id, logging.WARNING,
                              "Battery: %s still reads SEM's %s after %d "
                              "put-backs to %s — set it back by hand (#1180)",
                              entity_id, read, t.tries, t.prior)
                    continue
                if (t.tried_at is not None
                        and self._clock() - t.tried_at < self.RETRY_S):
                    continue                    # sent, or released, too lately
                await self._send_back(entity_id, t)
                changed = True
            if changed:
                await self._save()

    def readable(self, entity_id: str) -> bool:
        """(#1377) Does the number give a value now? ``write`` writes none
        that does not: the old value could not be put back."""
        return self._read(str(entity_id or "")) is not None

    def snapshot(self) -> dict:
        """For diagnostics: each number SEM holds or still has to put back."""
        out: dict = {e: {"saved": t.prior, "sent": list(t.sent),
                         "held": t.held, "pending": t.pending,
                         "tries": t.tries}
                     for e, t in self._targets.items() if t.held or t.pending}
        if self._blind:
            out["record"] = "unreadable"
        elif not self._adopted:
            out["record"] = "not read yet"
        return out

    # ─── inside ──────────────────────────────────────────────────────

    async def _send_back(self, entity_id: str, t: _Target) -> None:
        if t.prior is None:
            return                              # nothing known to put back
        if self._read(entity_id) is None:
            # Home Assistant drops a write to an unavailable entity without
            # a word; it goes once the number can be read
            self._say(entity_id, logging.WARNING,
                      "Battery: %s cannot be read — SEM puts %s back once it "
                      "can (#1180)", entity_id, t.prior)
            return
        t.tries += 1
        t.tried_at = self._clock()
        try:
            # blocking: a refusal must reach SEM, not only HA's log — and
            # bounded, so a device that never answers cannot hold the cycle
            async with asyncio.timeout(self.SEND_TIMEOUT_S):
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": _wire(t.prior)},
                    blocking=True,
                )
        except Exception as exc:  # noqa: BLE001 — tried again, never fatal
            self._say(entity_id, logging.WARNING,
                      "Battery: putting %s back to %s failed (%s) — SEM "
                      "tries again (#1180)", entity_id, t.prior, exc)
            return
        self._say(entity_id, logging.INFO,
                  "Battery: %s put back to %s after the forced charge "
                  "(#1180)", entity_id, t.prior)

    def _read(self, entity_id: str) -> Optional[float]:
        try:
            state = self._hass.states.get(entity_id)
        except Exception:  # noqa: BLE001
            return None
        return _as_number(getattr(state, "state", None)) if state is not None else None

    def _tol(self, entity_id: str) -> float:
        """Two values are one when they differ by less than the number's
        step: an inverter that rounds SEM's 62 to 60 still shows SEM's."""
        try:
            attrs = getattr(self._hass.states.get(entity_id), "attributes", None)
            step = _as_number(attrs.get("step")) if isinstance(attrs, dict) else None
        except Exception:  # noqa: BLE001
            step = None
        return max(0.5, step) if step is not None and step > 0 else 0.5

    @staticmethod
    def _say(entity_id: str, level: int, fmt: str, *args) -> None:
        log_on_change(_LOGGER, f"charge_target:{entity_id}", level, fmt, *args)

    async def _adopt(self) -> None:
        """Take over what the last lifetime left on the numbers. Once."""
        if self._adopted:
            return
        self._adopted = True
        try:
            record = await self._store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Battery: SEM's record of the charge targets it "
                            "wrote cannot be read (#1180)", exc_info=True)
            self._blind = True
            return
        if record is None:
            return
        entities = record.get("entities") if isinstance(record, dict) else None
        if not isinstance(entities, dict) or not all(
                isinstance(v, dict) for v in entities.values()):
            # a record of another shape says nothing SEM can trust
            _LOGGER.warning("Battery: SEM's record of the charge targets it "
                            "wrote is damaged (#1180)")
            self._blind = True
            return
        for entity_id, raw in entities.items():
            if not entity_id:
                continue
            sent = raw.get("sent")
            t = _Target(
                prior=_as_number(raw.get("prior")),
                sent=[v for v in (_as_number(x) for x in sent) if v is not None]
                if isinstance(sent, list) else [],
                held=raw.get("held") is True,
                pending=raw.get("pending") is True)
            if not (t.held or t.pending):
                continue
            if t.held and str(entity_id) not in self._configured:
                # no longer SEM's target setting: hand it back
                t.held, t.pending = False, True
            # read again before SEM writes over it: the user may have set it
            # while SEM was down, or its value may be lost (then SEM's own
            # value is refused, not saved)
            t.adopted = t.held
            self._targets[str(entity_id)] = t
            _LOGGER.info(
                "Battery: %s may still carry SEM's charge target %s — %s "
                "goes back (#1180)", entity_id, t.sent, t.prior)

    async def _save(self) -> bool:
        if self._store is None:
            return True
        data = {"entities": {
            e: {"prior": t.prior, "sent": list(t.sent), "held": t.held,
                "pending": t.pending}
            for e, t in self._targets.items() if t.held or t.pending}}
        try:
            await self._store.async_save(data)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Battery: SEM could not save its record of the "
                            "charge targets it wrote (#1180)", exc_info=True)
            return False
        return True
