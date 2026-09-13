"""#935 — what SEM leaves behind, in ONE place.

Removing SEM today deletes a config entry and releases the loads it started.
Everything else it created stays: the per-entry stores, the version marker,
its Repairs, the Lovelace resources pointing at files that are about to
vanish, and — when SEM parked a wallbox — a charger holding "no" with nothing
left on the system to say "yes". @markusschloesser's Spook run on #908 found
119 leftover statistics; the statistics turned out to be the smallest part.

Three rules, from the issue:

* **Hand the hardware back** — and only what SEM itself commanded. That is
  #908's rule (loads), extended by #936 (batteries) and #949 (the charge
  pacer). The charger is the last one.
* **Take its own files** — this entry's stores, its version marker, its
  Repairs, its Lovelace resources. Orphans of older entry ids are swept on
  the next setup and reported, never silently.
* **Offer what is the user's** — the generated dashboard and the long-term
  statistics belong to them. Those are deleted only on an explicit choice.

This module is the INVENTORY and the mechanics; the lifecycle hooks in
``__init__.py`` decide when to call them. Nothing here raises: a teardown
that fails half way must still let HA remove the entry.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable, List, Optional, Sequence

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

#: Per-entry stores, by the key each owner builds. Kept as format strings so
#: the inventory reads like the code that creates them:
#:   coordinator/storage.py  -> f"{DOMAIN}_{entry_id}_energy" / "_daily"
#:   __init__.py             -> f"sem_seen_version_{entry_id}"
#:   coordinator/coordinator.py (#949) -> f"sem.pacing.{entry_id}"
_PER_ENTRY_STORE_FORMATS: tuple[str, ...] = (
    f"{DOMAIN}_{{entry_id}}_energy",
    f"{DOMAIN}_{{entry_id}}_daily",
    "sem_seen_version_{entry_id}",
    "sem.pacing.{entry_id}",
)

#: Per-entry stores whose key carries a SECOND scope (a battery id), so they
#: are matched by prefix rather than built by name.
#:   coordinator/battery_adapters/deye_snapshot_store.py
_PER_ENTRY_STORE_PREFIXES: tuple[str, ...] = (
    "sem.deye.snapshot.{entry_id}.",
    "sem.deye.unsafe.{entry_id}.",
)

#: Stores SEM keeps ONCE for the whole installation, not per entry. They are
#: removed only when the LAST SEM entry goes — a second entry still needs its
#: device mappings and its load priorities.
_INSTALL_WIDE_STORES: tuple[str, ...] = (
    "sem_device_mappings",
    f"{DOMAIN}_load_management_devices",
)

#: Names SEM used before the per-entry scheme and no longer writes. They are
#: pure leftovers on any install old enough to have them (both are live on
#: PROD today), so they go with the last entry like the install-wide ones.
_LEGACY_STORES: tuple[str, ...] = (
    f"{DOMAIN}_daily_storage",
    f"{DOMAIN}_energy_totals",
)


def per_entry_store_keys(entry_id: str) -> List[str]:
    """Every store key that belongs to exactly this config entry."""
    entry_id = str(entry_id or "")
    if not entry_id:
        # A degenerate id would match the prefix of every entry's stores.
        return []
    return [fmt.format(entry_id=entry_id) for fmt in _PER_ENTRY_STORE_FORMATS]


def per_entry_store_prefixes(entry_id: str) -> List[str]:
    """Key prefixes whose matches belong to this entry (Deye, per battery)."""
    entry_id = str(entry_id or "")
    if not entry_id:
        return []
    return [fmt.format(entry_id=entry_id) for fmt in _PER_ENTRY_STORE_PREFIXES]


def install_wide_store_keys() -> List[str]:
    """Stores shared by every SEM entry, plus the retired names."""
    return [*_INSTALL_WIDE_STORES, *_LEGACY_STORES]


def _storage_dir(hass) -> Optional[str]:
    try:
        return os.path.join(hass.config.config_dir, ".storage")
    except Exception:  # noqa: BLE001 — a stand-in hass in tests
        return None


def sem_store_names(names: Iterable[str]) -> List[str]:
    """The SEM-looking store keys out of a raw directory listing.

    Pure, so the sweep's judgement can be tested without a filesystem — and
    so the one call that touches the disk has a single home (below).
    """
    return sorted(
        n for n in names
        if (n.startswith((f"{DOMAIN}_", "sem_", "sem.")) and not n.endswith("."))
        and not n.endswith(".bak")
        and ".bak." not in n
    )


def _listdir(path: str) -> List[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


async def async_existing_store_files(hass) -> List[str]:
    """The SEM store keys actually present on disk.

    Reading the directory rather than trusting the inventory is deliberate:
    the point of the orphan sweep is to find files whose owner no longer
    exists, and an owner that no longer exists cannot name its own key.

    Off the event loop — a config directory on a slow SD card is exactly the
    kind of listing HA's blocking-call guard exists to catch.
    """
    path = _storage_dir(hass)
    if not path:
        return []
    names = await hass.async_add_executor_job(_listdir, path)
    return sem_store_names(names)


def orphan_store_keys(names: Iterable[str],
                      live_entry_ids: Iterable[str]) -> List[str]:
    """Which of ``names`` no live config entry owns.

    An install that has been removed and re-added carries the previous entry
    id's pair for ever — seven of them on the .46 rig, ninety-six version
    markers. They are dead weight, and worse, they make "is this a fresh
    install?" unanswerable.

    Install-wide and legacy stores are NOT orphans while any entry lives:
    they have no entry id in their name and are still in use.
    """
    live = {str(e) for e in live_entry_ids if e}
    keep_whole = set(install_wide_store_keys())
    owned: set[str] = set()
    prefixes: List[str] = []
    for entry_id in live:
        owned.update(per_entry_store_keys(entry_id))
        prefixes.extend(per_entry_store_prefixes(entry_id))
    out = []
    for name in sem_store_names(names):
        if name in keep_whole or name in owned:
            continue
        if any(name.startswith(p) for p in prefixes):
            continue
        # Only files that CARRY an entry-scoped shape can be orphans. A SEM
        # store nobody has taught this module about is left alone and named
        # in the report — deleting an unrecognised file is how a cleanup
        # becomes the problem it was written to solve.
        if _looks_entry_scoped(name):
            out.append(name)
    return out


#: What a Home Assistant config-entry id looks like: a 26-character ULID
#: (``01M2BQ1A7MWSNS021PMT5XQMQA``), or the 32-hex-character ids older
#: installs still carry.
_ENTRY_ID_RE = re.compile(r"^(?:[0-9A-Z]{26}|[0-9a-f]{32})$")


def _is_entry_id(text: str) -> bool:
    return bool(_ENTRY_ID_RE.match(text or ""))


def _looks_entry_scoped(name: str) -> bool:
    """True when the key carries a real config-entry id in one of SEM's shapes.

    The id must LOOK like one. The first cut accepted any middle segment, and
    a fault-injection run on the .46 rig (13.09) deleted a file a user had
    copied aside by hand as ``solar_energy_management_mybackup_energy`` — it
    read as an orphaned install's store. A sweep that deletes someone's own
    file is the exact problem this module exists to avoid, so the shape is
    checked rather than assumed: anything else is unrecognised, and
    unrecognised is left alone and named in the log.
    """
    for prefix in ("sem.pacing.", "sem.deye.snapshot.", "sem.deye.unsafe."):
        if name.startswith(prefix):
            # deye keys carry a second scope (the battery id) after the entry
            return _is_entry_id(name[len(prefix):].split(".", 1)[0])
    if name.startswith("sem_seen_version_"):
        return _is_entry_id(name[len("sem_seen_version_"):])
    if name.startswith(f"{DOMAIN}_") and name.endswith(("_energy", "_daily")):
        return _is_entry_id(name[len(DOMAIN) + 1:].rsplit("_", 1)[0])
    return False


async def async_delete_stores(hass, keys: Sequence[str]) -> List[str]:
    """Remove each store by key. Returns the keys actually removed."""
    from homeassistant.helpers.storage import Store

    removed: List[str] = []
    for key in keys:
        try:
            await Store(hass, 1, key).async_remove()
            removed.append(key)
        except Exception:  # noqa: BLE001 — one bad file never stops the rest
            _LOGGER.debug("SEM cleanup: could not remove store %s", key,
                          exc_info=True)
    return removed


async def async_entry_stores_removed(hass, entry_id: str) -> List[str]:
    """Delete everything this entry owns, including its prefix-scoped stores."""
    keys = list(per_entry_store_keys(entry_id))
    prefixes = per_entry_store_prefixes(entry_id)
    if prefixes:
        on_disk = await async_existing_store_files(hass)
        keys.extend(
            n for n in on_disk
            if any(n.startswith(p) for p in prefixes)
        )
    return await async_delete_stores(hass, keys)


def delete_repairs(hass) -> int:
    """Delete every Repair issue SEM raised. Returns how many.

    SEM's issues are all created under its own domain, so the domain IS the
    inventory — no list to keep in step with ``repair_issues.py``, which has
    a dozen issue-id builders and grows.
    """
    try:
        from homeassistant.helpers import issue_registry as ir

        registry = ir.async_get(hass)
        mine = [
            key[1] for key in list(getattr(registry, "issues", {}))
            if isinstance(key, tuple) and len(key) == 2 and key[0] == DOMAIN
        ]
        for issue_id in mine:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        return len(mine)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("SEM cleanup: could not clear repairs", exc_info=True)
        return 0


def _is_sem_resource(url: str) -> bool:
    """A Lovelace resource URL SEM registered.

    Matched on SEM's own path, not on the file name: a user who hand-added a
    resource of their own that happens to be called ``sem-cards.js`` from
    somewhere else keeps it.
    """
    url = str(url or "")
    return f"/{DOMAIN}/dashboard/card/" in url or url.startswith(
        f"/local/{DOMAIN}/")


async def async_deregister_resources(hass) -> List[str]:
    """Drop SEM's Lovelace resource rows. Returns the URLs removed.

    Registration happens on every setup and nothing ever undid it, so after a
    removal every dashboard load fetched a module that is gone — a console
    error on a system that no longer has SEM installed to explain it.
    """
    from homeassistant.helpers.storage import Store

    try:
        store = Store(hass, 1, "lovelace_resources")
        data = await store.async_load() or {}
        items = list(data.get("items") or [])
        keep = [i for i in items if not _is_sem_resource(i.get("url"))]
        dropped = [str(i.get("url")) for i in items if _is_sem_resource(i.get("url"))]
        if dropped:
            data["items"] = keep
            await store.async_save(data)
        return dropped
    except Exception:  # noqa: BLE001
        _LOGGER.debug("SEM cleanup: could not deregister resources",
                      exc_info=True)
        return []


def sem_statistic_ids(hass) -> List[str]:
    """The long-term statistic ids that belong to SEM's own entities.

    Read from the entity registry, so it is this install's actual entities
    and not a guess from a name pattern.
    """
    try:
        from homeassistant.helpers import entity_registry as er

        return sorted(
            e.entity_id for e in er.async_get(hass).entities.values()
            if e.platform == DOMAIN
        )
    except Exception:  # noqa: BLE001
        return []


async def async_clear_statistics(hass, statistic_ids: Sequence[str]) -> int:
    """Clear SEM's long-term statistics — ONLY ever on an explicit choice.

    Home Assistant keeps statistics after an entity is removed on purpose:
    they are the user's history, and a year of solar yield is not SEM's to
    throw away because SEM is being uninstalled. So this is never part of the
    automatic teardown; it is behind the ``remove_leftovers`` service.
    """
    ids = [s for s in statistic_ids if s]
    if not ids:
        return 0
    try:
        await hass.services.async_call(
            "recorder", "clear_statistics", {"statistic_ids": ids},
            blocking=True)
        return len(ids)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("SEM cleanup: could not clear statistics (recorder "
                        "may be disabled)")
        return 0


#: The dashboard SEM generates, and its sidebar entry. Both are the USER's
#: once created — they may have edited it — so nothing here runs without an
#: explicit ``remove_leftovers`` call.
_DASHBOARD_PATH = "sem-dashboard"
_DASHBOARD_STORE = f"lovelace.{_DASHBOARD_PATH}"


async def async_remove_dashboard(hass, path: str = _DASHBOARD_PATH) -> bool:
    """Delete the generated dashboard and its sidebar entry. Explicit only.

    Returns True when something was removed. The two halves are separate
    files — the view config (``lovelace.sem-dashboard``) and the row in
    ``lovelace_dashboards`` that puts it in the sidebar — and leaving either
    behind gives a broken sidebar entry or an invisible orphan, so both go or
    neither does.
    """
    from homeassistant.helpers.storage import Store

    removed = False
    try:
        await Store(hass, 1, f"lovelace.{path}").async_remove()
        removed = True
    except Exception:  # noqa: BLE001
        _LOGGER.debug("SEM cleanup: no dashboard store to remove",
                      exc_info=True)
    try:
        store = Store(hass, 1, "lovelace_dashboards")
        data = await store.async_load() or {}
        items = list(data.get("items") or [])
        keep = [i for i in items if i.get("id") != path]
        if len(keep) != len(items):
            data["items"] = keep
            await store.async_save(data)
            removed = True
    except Exception:  # noqa: BLE001
        _LOGGER.debug("SEM cleanup: could not drop the sidebar entry",
                      exc_info=True)
    return removed
