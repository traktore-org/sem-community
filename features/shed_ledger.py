"""(#896) What SEM switched off, kept on disk.

The shed list lives in memory. A restart, a crash or an unload (the shed
circuit fed the HA host itself, forum #30) left every shed load off with
nobody to turn it back on. This ledger holds one record per shed load, written
BEFORE the switch is thrown, so a later start can put it back.

A record names the entity and the value SEM found. It is only ever acted on
while the entity still shows the shed value: a load somebody changed since is
theirs, and nothing is written to it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..coordinator.units import finite_float

_LOGGER = logging.getLogger(__name__)

#: the store file's key (one name for the manager and the stand-alone helper)
LEDGER_KEY = "load_shed_ledger"

#: A record older than this is still acted on (an off fridge is worse than a
#: stale record) but says so in the log.
STALE_AFTER = timedelta(hours=24)

_ON = ("on", "true", "1")
_DARK = ("unavailable", "unknown", "")

KIND_SWITCH = "switch"
KIND_SETPOINT = "setpoint"

# What a resolve() says to do with one record.
RESTORE, DROP, WAIT = "restore", "drop", "wait"


def resolve(rec: Dict[str, Any], state: Any) -> Tuple[str, Optional[Tuple[str, str, dict]]]:
    """Decide one record against the entity's state now.

    Returns ``(RESTORE, (domain, service, data))``, ``(DROP, None)`` when the
    load no longer shows the shed value (changed by hand, or nothing to
    restore) or ``(WAIT, None)`` while the entity is not readable yet — right
    after a start its integration may not be up, and that is not "changed".
    """
    raw = None if state is None else str(getattr(state, "state", "")).lower()
    if raw is None or raw in _DARK:
        return WAIT, None
    entity = rec.get("entity")
    if rec.get("kind") == KIND_SETPOINT:
        return _resolve_setpoint(rec, entity, raw)
    if raw in _ON or raw != "off" or not rec.get("found_on"):
        return DROP, None
    return RESTORE, (rec.get("domain", "switch"), "turn_on", {"entity_id": entity})


def _resolve_setpoint(rec: Dict[str, Any], entity: str, raw: str):
    try:
        now = finite_float(raw)
    except (TypeError, ValueError):
        now = None
    floor, found = rec.get("shed_value"), rec.get("found")
    if now is None:
        return WAIT, None
    if floor is None or found is None or abs(now - float(floor)) > 0.5:
        return DROP, None
    return RESTORE, (rec.get("domain", "number"), "set_value",
                     {"entity_id": entity, "value": float(found)})


def make_record(kind: str, domain: str, entity: str, *, found_on: bool = False,
                found: Optional[float] = None,
                shed_value: Optional[float] = None) -> Dict[str, Any]:
    """The record written before a shed."""
    return {"kind": kind, "domain": domain, "entity": entity,
            "found_on": bool(found_on), "found": found,
            "shed_value": shed_value, "at": dt_util.now().isoformat()}


def age_of(rec: Dict[str, Any]) -> Optional[timedelta]:
    try:
        return dt_util.now() - datetime.fromisoformat(str(rec.get("at")))
    except (TypeError, ValueError):
        return None


class ShedLedger:
    """``{device_id: record}`` with its Store. Saves never raise: a failed
    write costs the restart's safety net, not the shed."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self.records: Dict[str, Dict[str, Any]] = {}

    async def async_load(self) -> None:
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001 — no ledger = nothing to restore
            _LOGGER.warning("Shed ledger could not be read", exc_info=True)
            return
        found = data.get("records") if isinstance(data, dict) else None
        if isinstance(found, dict):
            self.records = {str(k): dict(v) for k, v in found.items()
                            if isinstance(v, dict)}

    async def _save(self) -> bool:
        try:
            await self._store.async_save({"records": self.records})
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Shed ledger could not be saved — this shed will "
                            "not survive a crash", exc_info=True)
            return False

    async def async_remember(self, device_id: str, rec: Dict[str, Any]) -> bool:
        self.records[device_id] = rec
        return await self._save()

    async def async_drop(self, device_id: str) -> None:
        if self.records.pop(device_id, None) is not None:
            await self._save()

    def drop_soon(self, device_id: str) -> None:
        """Sync callers (the per-cycle sweep): in memory now, on disk soon."""
        if self.records.pop(device_id, None) is None:
            return
        try:
            self._store.async_delay_save(lambda: {"records": self.records}, 2)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("shed ledger delayed save failed", exc_info=True)


class OrphanRecovery:
    """(#896) Restoring is not shedding: it runs whenever a record exists,
    with load management on or off. When no load manager is built (it is off),
    this does the same job on its own — start-up passes, HA stop, unload —
    through the same hand-change rule, and writes nothing in observer mode."""

    PASSES = 20
    PAUSE_S = 30

    def __init__(self, hass: Any, observer: Any = False) -> None:
        from homeassistant.helpers.storage import Store
        self.hass = hass
        self._observer = observer if callable(observer) else (lambda: bool(observer))
        self.ledger = ShedLedger(Store(hass, 1, f"{DOMAIN}_{LEDGER_KEY}"))
        self._task = None
        self._unsub = None

    async def async_start(self) -> bool:
        """True when records exist and recovery is under way."""
        await self.ledger.async_load()
        if not self.ledger.records:
            return False
        from homeassistant.const import EVENT_HOMEASSISTANT_STOP
        self._unsub = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._on_stop)
        self._task = self.hass.async_create_task(self._loop())
        return True

    async def async_pass(self) -> int:
        """One sweep; returns the records still waiting."""
        for device_id, rec in list(self.ledger.records.items()):
            try:
                await self._one(device_id, rec)
            except Exception:  # noqa: BLE001 — one load must not stop the rest
                _LOGGER.warning("Shed recovery failed for %s", device_id, exc_info=True)
        return len(self.ledger.records)

    async def _one(self, device_id: str, rec: Dict[str, Any]) -> None:
        verdict, call = resolve(rec, self.hass.states.get(rec.get("entity")))
        if verdict == WAIT:
            return
        if verdict == RESTORE and call is not None:
            if self._observer():
                return    # watching only: nothing written, record kept
            age = age_of(rec)
            if age is not None and age > STALE_AFTER:
                _LOGGER.warning("Restoring %s from a shed record %s old",
                                rec.get("entity"), age)
            domain, service, data = call
            await self.hass.services.async_call(domain, service, dict(data), blocking=True)
            _LOGGER.info("Restored %s from the shed ledger", rec.get("entity"))
        await self.ledger.async_drop(device_id)

    async def _loop(self) -> None:
        import asyncio
        for _ in range(self.PASSES):
            if not await self.async_pass():
                return
            await asyncio.sleep(self.PAUSE_S)

    async def _on_stop(self, _event=None) -> None:
        self._unsub = None
        await self.async_pass()

    async def async_shutdown(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        task, self._task = self._task, None
        if task is not None and hasattr(task, "cancel"):
            task.cancel()
        await self.async_pass()
