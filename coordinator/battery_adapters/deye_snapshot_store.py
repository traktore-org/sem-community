"""Persistent Deye snapshot store backed by Home Assistant's ``Store`` (#709).

``DeyeBatteryAdapter`` implements a transactional snapshot/restore protocol,
but the *production* persistence behind it lived only as an in-memory
test stand-in.  This module ships the first production slice:

- :class:`DeyeSnapshotStore` wraps Home Assistant's persistent
  :class:`~homeassistant.helpers.storage.Store` and exposes the exact
  interface the adapter already talks to (``async_save`` / ``async_load`` /
  ``async_clear`` / ``async_set_unsafe`` plus the ``unsafe`` property) and
  the startup latch load (``async_load_latch``).
- Scope safety: every underlying store key embeds ``config_entry_id`` +
  ``battery_id``, so two batteries or two config entries never share a
  snapshot or a safety latch.  The runtime store object is never written
  into entry ``data``/``options`` — the coordinator attaches it to the
  adapter object only (runtime injection).
- Fail-closed startup: if a persisted unsafe latch (or a corrupt latch)
  is present, ``async_load_latch`` latches the adapter ``unsafe`` True so
  the pending snapshot is never replayed to the inverter.  A corrupt
  snapshot is surfaced by the adapter's strict load path (no service
  writes), and a valid pending snapshot is restored and cleared by the
  adapter's ``command_normal`` recovery path.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_SNAPSHOT_VERSION = 1
_UNSAFE_VERSION = 1


def _snapshot_store_key(config_entry_id: str, battery_id: str) -> str:
    """Persistent Store key for a battery control snapshot — scope-separated.

    Both identifiers are embedded so two batteries / two config entries
    never alias the same persisted snapshot.
    """
    return f"sem.deye.snapshot.{config_entry_id}.{battery_id}"


def _unsafe_store_key(config_entry_id: str, battery_id: str) -> str:
    """Persistent Store key for the Deye safety latch — scope-separated."""
    return f"sem.deye.unsafe.{config_entry_id}.{battery_id}"


class DeyeSnapshotStore:
    """Persistent, scope-separated snapshot + safety-latch store (HA Store).

    The instance is constructed per (config entry, battery) scope and handed
    to the adapter at runtime.  It is *not* part of entry ``data``/``options``.
    """

    def __init__(self, hass, config_entry_id: str, battery_id: str) -> None:
        self.hass = hass
        self.config_entry_id = str(config_entry_id)
        self.battery_id = str(battery_id)
        # The unsafe latch defaults closed (False); only an explicitly
        # persisted True (or a load failure -> fail-closed) flips it open.
        self.unsafe = False
        self._snapshot_key = _snapshot_store_key(self.config_entry_id, self.battery_id)
        self._unsafe_key = _unsafe_store_key(self.config_entry_id, self.battery_id)
        self._store = Store(self.hass, _SNAPSHOT_VERSION, self._snapshot_key)
        self._unsafe_store = Store(self.hass, _UNSAFE_VERSION, self._unsafe_key)

    # ─── snapshot payload ───────────────────────────────────────

    async def async_save(self, data: dict[str, Any]) -> None:
        """Persist the control snapshot dict for this scope."""
        await self._store.async_save(data)

    async def async_load(self) -> Optional[dict[str, Any]]:
        """Return the persisted snapshot dict (or None when empty/corrupt)."""
        return await self._store.async_load()

    async def async_clear(self) -> None:
        """Remove the persisted snapshot for this scope."""
        await self._store.async_remove()

    # ─── safety latch ───────────────────────────────────────────

    @property
    def unsafe(self) -> bool:
        """Current in-memory unsafe-latch state (defaults closed / False)."""
        return self._unsafe

    @unsafe.setter
    def unsafe(self, value: bool) -> None:
        self._unsafe = bool(value)

    async def async_set_unsafe(self, value: bool) -> None:
        """Persist and update the safety latch.

        ``True`` latches the scope unsafe — the adapter must not replay a
        pending snapshot to the inverter.
        """
        new_value = bool(value)
        self._unsafe = new_value
        try:
            await self._unsafe_store.async_save({"unsafe": new_value})
        except Exception as err:  # noqa: BLE001 — never let persistence fail the call
            _LOGGER.exception("Deye: failed to persist unsafe latch: %s", err)

    async def async_load_latch(self) -> bool:
        """Load the persisted safety latch at startup (fail-closed).

        A missing latch, an explicit ``True``, or any load error leaves the
        scope latched closed-safely per the persisted truth; on a load error
        we latch ``unsafe=True`` so recovery never replays an unknown
        snapshot to the inverter.
        """
        try:
            data = await self._unsafe_store.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Deye: unsafe latch load failed — fail closed: %s", err)
            self._unsafe = True
            return True
        if isinstance(data, dict):
            unsafe_value = data.get("unsafe")
            if type(unsafe_value) is bool:
                self._unsafe = unsafe_value
            else:
                # Corrupt / non-boolean unsafe payload → fail-closed. Only an
                # exact ``bool`` Truth may open the latch; anything else (a
                # stray string, ``0``/``1``, ``None``) keeps the scope unsafe
                # so a pending snapshot is never replayed to the inverter.
                _LOGGER.warning(
                    "Deye: unsafe latch payload is not an exact bool (%r) — "
                    "fail closed", unsafe_value,
                )
                self._unsafe = True
        elif data:
            # Any residual truthy payload → keep it latched unsafe.
            self._unsafe = True
        return self._unsafe


__all__ = [
    "DeyeSnapshotStore",
    "_snapshot_store_key",
    "_unsafe_store_key",
]
