"""(#1421) A new charger or heat pump takes an id no unit of its kind had.

SEM keeps a unit's data under its id: a charger's charging sessions (the
session list, the month totals, the Excel file), its taper and car-battery
estimate, its day counters, a heat pump's day runtime and meter reading, and
the HA entities with their history. A removed unit's data stays. The ids
used to be the first free one in the current list (``ev_charger``,
``ev_charger_1``, …), so a new unit could take a removed unit's id, and with
it every store kept under that id.

The ids a kind ever had are kept in SEM's store (``SEMStorage.unit_ids_used``),
noted at every setup; the store also reads them from the data it keeps per
unit, so a unit removed before this record existed counts too. A unit found
on its HA device keeps the id built from that device, so the same box added
again is the same unit (``stable_discovered_charger_id``).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Iterable, Optional

from .charger_refs import REFS_KEY

_LOGGER = logging.getLogger(__name__)

CHARGERS = "ev_chargers"
HEAT_PUMPS = "heat_pumps"

# (base, first number, the bare base is an id of this kind) per kind. The
# bare ``heat_pump`` is the primary unit of the flat keys, never a new row.
_SHAPE = {
    CHARGERS: ("ev_charger", 1, True),
    HEAT_PUMPS: ("heat_pump", 2, False),
}


def next_unit_id(kind: str, used: Iterable[Any], start: Optional[int] = None) -> str:
    """The first id of ``kind`` that is not in ``used``. ``start`` is the
    number tried first (the Configure dialog numbers a new charger from the
    list's length); without it the bare base comes first where it is an id
    of this kind, then the kind's first number. Pure."""
    base, first, bare = _SHAPE[kind]
    taken = {str(u) for u in (used or ()) if u}
    if start is None and bare and base not in taken:
        return base
    n = first if start is None else int(start)
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def _ids_in(rows: Any) -> set[str]:
    return {str(r.get("id")) for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and r.get("id")}


def used_unit_ids(entry: Optional[Any], kind: str) -> set[str]:
    """Every id ``kind`` has had on this entry: the saved lists (data and
    options), the charger refs, and what SEM's store kept. With no running
    store (setup failed) only the saved lists answer."""
    if entry is None:
        return set()
    out: set[str] = set()
    for store in (getattr(entry, "data", None), getattr(entry, "options", None)):
        if isinstance(store, Mapping):   # HA hands a read-only mapping
            out |= _ids_in(store.get(kind))
            if kind == CHARGERS:
                out |= _ids_in(store.get(REFS_KEY))
    storage = getattr(getattr(entry, "runtime_data", None), "_storage", None)
    if storage is not None:
        try:
            noted = storage.unit_ids_used(kind)
        except Exception:  # noqa: BLE001 — a half-built store adds nothing
            _LOGGER.debug("used unit ids unreadable", exc_info=True)
            noted = None
        if isinstance(noted, (set, frozenset)):   # only a real answer counts
            out |= {str(i) for i in noted if i}
    return out
