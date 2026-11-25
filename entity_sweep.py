"""(#1428) Nothing SEM made outlives the item it was made for.

Every SEM entity is ``<prefix><key>`` with prefix ``<entry_id>_`` or
``sem_`` (one unique_id producer per platform). Per-item keys carry the
item: ``charger_<id>_…``, ``battery_<id>_…``, ``pv_string_<slot>_…``,
``daily_tariff_cost_<device>``. When an item leaves SEM (a charger removed,
a battery or PV string gone, a load's own tariff removed), no platform
builds its keys any more.

Each platform reports the keys it built in this run — disabled-by-default
ones included, since a description is built either way — with
:func:`report_built_keys`. ONE sweep, after every platform is set up
(``remove_charger`` reloads the entry, so it also runs right after a
removal), removes this entry's rows whose key no platform built.

Safe by construction:

* a row is judged only by an EXACT key match, so ``ev_charger`` is never
  confused with ``ev_charger_1``;
* a platform that did not report this run is not swept at all (a platform
  whose build failed never reaches its report); a platform that reported
  nothing — its last charger removed — clears only per-item rows;
* only rows of this config entry and this integration.

This replaces the five copies of the same sweep that sensor, number, select,
switch and binary_sensor each ran (button borrowed sensor's); ``time`` had
none, which is how a removed charger's "Charge By" survived two weeks.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

_LOGGER = logging.getLogger(__name__)

DOMAIN = "solar_energy_management"
_KEY = "entity_sweep_built"
#: The per-item key families (one producer each: number/sensor/select/
#: switch/button/binary_sensor/time build ``charger_<id>_…``; sensor/number/
#: select ``battery_<id>_…``; sensor ``pv_string_<slot>_…`` and
#: ``daily_tariff_cost_<device>``).
PER_ITEM_PREFIXES = ("charger_", "battery_", "pv_string_", "daily_tariff_cost_")


def key_of(unique_id: str, entry_id: str) -> Optional[str]:
    """The entity key behind a SEM unique_id, or None for another entry."""
    for head in (f"{entry_id}_", "sem_"):
        if unique_id.startswith(head):
            return unique_id[len(head):]
    return None


def stale_rows(rows: Iterable[Any], entry_id: str,
               built: Mapping[str, set]) -> list:
    """This entry's rows whose key no reporting platform built this run."""
    out = []
    for r in rows:
        if getattr(r, "platform", None) != DOMAIN:
            continue
        keys = built.get(getattr(r, "domain", None))
        if keys is None:        # this platform did not report: leave it
            continue
        key = key_of(getattr(r, "unique_id", "") or "", entry_id)
        if not key or key in keys:
            continue
        # A platform that built nothing (its last charger removed) clears
        # only per-item rows, never a global one.
        if not keys and not key.startswith(PER_ITEM_PREFIXES):
            continue
        out.append(r)
    return out


def report_built_keys(hass, entry, platform: str, keys: Iterable[str]) -> None:
    """A platform says which keys it built in this run. Never raises."""
    try:
        store = hass.data.setdefault(DOMAIN, {}).setdefault(_KEY, {})
        store.setdefault(entry.entry_id, {}).setdefault(platform, set()).update(
            k for k in keys if k)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("entity sweep: could not record %s keys", platform, exc_info=True)


def sweep_stale_entities(hass, entry) -> int:
    """Remove this entry's rows no platform built this run; log each."""
    try:
        built = (hass.data.get(DOMAIN, {}).get(_KEY, {})).pop(entry.entry_id, {})
    except Exception:  # noqa: BLE001
        return 0
    if not built:
        return 0
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    removed = 0
    for r in stale_rows(er.async_entries_for_config_entry(registry, entry.entry_id),
                        entry.entry_id, built):
        _LOGGER.info("Removing %s: SEM no longer has the item it belonged to (#1428)",
                     r.entity_id)
        registry.async_remove(r.entity_id)
        removed += 1
    return removed
