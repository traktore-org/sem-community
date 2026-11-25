"""(#1428) A removed charger leaves no entities behind.

Every per-charger entity is built with the key ``charger_<id>_<suffix>``
(number.py, sensor.py, select.py, switch.py, button.py, binary_sensor.py,
time.py) and the unique_id ``<entry_id>_<key>`` or ``sem_<key>``. Removing
a charger dropped it from the config, but its registry rows stayed — on PROD
a "Charge By" time entity sat unavailable for two weeks after its charger
was removed on 09.11.

One sweep, run after the platforms are set up (so also after
``remove_charger``, which reloads the entry). It is deliberately narrow:

* only rows of this config entry's integration;
* a row counts only if its key reads ``charger_<id>_<suffix>`` with a suffix
  that a CONFIGURED charger also has right now — so the suffix list keeps
  itself current and a key it cannot read is kept;
* a row is kept if ANY reading of its key names a configured charger
  (``charger_ev_charger_flow_grid_to_ev_power`` also ends in ``_power``,
  and ``ev_charger`` is a prefix of ``ev_charger_1``);
* no configured charger, or a charger list that could not be read, removes
  nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

_LOGGER = logging.getLogger(__name__)

DOMAIN = "solar_energy_management"
_PREFIX = "charger_"


def _key_of(unique_id: str, entry_id: str) -> Optional[str]:
    """The entity key behind a SEM unique_id, or None for another entry."""
    for head in (f"{entry_id}_", "sem_"):
        if unique_id.startswith(head):
            return unique_id[len(head):]
    return None


def _readings(key: str, suffixes: Iterable[str]) -> list[str]:
    """Every charger id the key can be read as, one per matching suffix."""
    if not key.startswith(_PREFIX):
        return []
    body = key[len(_PREFIX):]
    out = []
    for s in suffixes:
        tail = "_" + s
        if body.endswith(tail) and len(body) > len(tail):
            out.append(body[: -len(tail)])
    return out


def orphan_charger_rows(rows: Iterable[Any], entry_id: str,
                        configured: Optional[set],
                        live: Optional[set] = None) -> list:
    """Registry rows that belong to a charger no longer configured.

    ``live`` is the set of entity ids a platform built in this run. The
    suffix list is read from those rows only: a removed charger's rows are
    never live, so they cannot teach the sweep a suffix (``ev_charger`` is a
    prefix of ``ev_charger_1``, whose leftover rows would otherwise read as
    ``ev_charger`` + ``1_power``). ``None`` = every row counts as live.
    """
    if not configured:
        return []
    rows = [r for r in rows if getattr(r, "platform", None) == DOMAIN]
    keyed = []
    for r in rows:
        key = _key_of(getattr(r, "unique_id", "") or "", entry_id)
        if key and key.startswith(_PREFIX):
            keyed.append((r, key))
    # Suffixes the configured chargers have now: the list keeps itself current.
    suffixes: set[str] = set()
    for r, key in keyed:
        if live is not None and r.entity_id not in live:
            continue
        body = key[len(_PREFIX):]
        owners = [c for c in configured if body.startswith(c + "_")]
        if owners:
            cid = max(owners, key=len)   # the longest id that prefixes it
            suffixes.add(body[len(cid) + 1:])
    if not suffixes:
        return []
    orphans = []
    for r, key in keyed:
        ids = _readings(key, suffixes)
        if ids and not any(i in configured for i in ids):
            orphans.append(r)
    return orphans


def sweep_removed_charger_entities(hass, entry, chargers) -> int:
    """Remove the registry rows of chargers no longer configured; log each."""
    try:
        configured = {c.get("id") for c in chargers or [] if isinstance(c, dict) and c.get("id")}
    except Exception:  # noqa: BLE001 — an unreadable list removes nothing
        return 0
    if not configured:
        return 0
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    rows = list(er.async_entries_for_config_entry(registry, entry.entry_id))
    # Live = built in this run: a state that is not the registry's restored
    # placeholder for an entity no platform provides.
    live = set()
    for r in rows:
        st = hass.states.get(r.entity_id)
        if st is not None and not st.attributes.get("restored"):
            live.add(r.entity_id)
    if not live:
        return 0   # platforms not up yet: nothing to learn suffixes from
    removed = 0
    for r in orphan_charger_rows(rows, entry.entry_id, configured, live):
        _LOGGER.info("Removing %s: its charger is no longer configured (#1428)", r.entity_id)
        registry.async_remove(r.entity_id)
        removed += 1
    return removed
