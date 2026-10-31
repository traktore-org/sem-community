"""(#1181) The forced charges SEM started, kept across a restart.

GoodWe and the generic switch setup start a grid charge by setting the
work mode (``inverter_work_mode_entity``) or turning a switch on
(``battery_force_charge_switch``). Only the stop turns it back. An HA
restart never unloads the entry, so a charge running at the restart keeps
running, and the next lifetime did not know SEM had started it. With night
charging turned off by then, no stop came: the pack charged from the grid
with nothing watching it, and the charge target SEM wrote stayed (#1180).

The rule is #936's: stop what SEM started, leave the rest. So the record
names each switch or mode select SEM turned on, and the batteries whose
charge turned it on:

* the name is SAVED before the start's write, so no lifetime turns one on
  without the next one knowing. A save that raises means no start. (Home
  Assistant's own store logs a disk error and returns, so trouble on disk
  does not hold a charge back.);
* it is DROPPED when a stop has landed, or when the entity reads that no
  charge runs. A start that failed keeps it while the entity reads on:
  the write may have landed anyway;
* the next lifetime reads it before each battery's decision
  (``BatteryControlAdapter.async_adopt_running_charge``). A battery named
  for an entity that still reads on has a charge SEM started and has not
  seen stop, so the stop goes out unless the plan still wants the charge.
  Until the entity can be read, nothing is adopted and nothing is dropped;
* a record that cannot be read names nothing: SEM cannot tell its own
  charge from the user's, so it stops none. The next start writes over it.

ONE record per config entry, keyed by the entity: packs behind one
inverter share its work mode select, and the switch key is not per
battery. Each name lists its batteries, so a pack in Off does not stop the
charge another pack started.

The store is injected at runtime and duck-typed (``async_load`` /
``async_save``), like ``ChargeTargetHold``'s, so this module stays free of
Home Assistant imports.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)


class ForcedChargeRecord:
    """The switches and mode selects SEM turned on for a grid charge."""

    def __init__(self, store: Any = None) -> None:
        self._store = store
        #: entity → the batteries whose charge turned it on
        self._running: dict[str, set[str]] = {}
        self._loaded = store is None
        self._lock = asyncio.Lock()

    async def started(self, entity_id: str, battery_id: str = "") -> bool:
        """Before the start's write. False: the name was not saved, so
        the start must not go out."""
        entity_id, battery_id = str(entity_id or ""), str(battery_id or "")
        if not entity_id:
            return True
        async with self._lock:
            await self._load()
            owners = self._running.get(entity_id)
            if owners is not None and battery_id in owners:
                return True
            self._running.setdefault(entity_id, set()).add(battery_id)
            if await self._save():
                return True
            if owners is None:
                self._running.pop(entity_id, None)
            else:
                owners.discard(battery_id)
            return False

    async def stopped(self, entity_id: str) -> None:
        """The entity is back: a stop landed, or it reads that no charge
        runs. Every battery's name for it goes. Never raises: a name left
        on disk is checked against the entity in the next lifetime."""
        entity_id = str(entity_id or "")
        async with self._lock:
            await self._load()
            if self._running.pop(entity_id, None) is None:
                return
            await self._save()

    async def running(self, entity_id: str, battery_id: str = "") -> bool:
        """Did this battery's charge turn ``entity_id`` on, with no stop
        seen since?"""
        async with self._lock:
            await self._load()
            return str(battery_id or "") in self._running.get(
                str(entity_id or ""), ())

    def snapshot(self) -> dict:
        """For diagnostics: each entity SEM turned on, and for which
        batteries."""
        return {e: sorted(b) for e, b in sorted(self._running.items())}

    async def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            record = await self._store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Battery: SEM's record of the forced charges it "
                            "started cannot be read — it stops none it may "
                            "have started before the restart (#1181)",
                            exc_info=True)
            return
        if record is None:
            return
        running = record.get("running") if isinstance(record, dict) else None
        if not isinstance(running, dict) or not all(
                isinstance(e, str) and isinstance(b, list)
                and all(isinstance(x, str) for x in b)
                for e, b in running.items()):
            _LOGGER.warning("Battery: SEM's record of the forced charges it "
                            "started is damaged — it stops none it may have "
                            "started before the restart (#1181)")
            return
        self._running = {e: set(b) for e, b in running.items() if e and b}
        if self._running:
            _LOGGER.info("Battery: SEM started a forced charge on %s and has "
                         "not seen it stop (#1181)",
                         ", ".join(sorted(self._running)))

    async def _save(self) -> bool:
        if self._store is None:
            return True
        try:
            await self._store.async_save({"running": self.snapshot()})
        except Exception as exc:  # noqa: BLE001
            log_on_change(_LOGGER, "forced_charge_record:save", logging.WARNING,
                          "Battery: SEM could not save its record of the "
                          "forced charges it started (%s) (#1181)", exc)
            return False
        return True
