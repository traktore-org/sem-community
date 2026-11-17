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

from ..coordinator.units import finite_float

_LOGGER = logging.getLogger(__name__)

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
