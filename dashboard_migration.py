"""(#1321) One-time retirement of the classic dashboard.

The classic dashboard (``/sem-dashboard``, nine tabs) is gone; the SEM
dashboard (five screens) is the only one. A stored classic dashboard is
handled once per install, flagged in the entry options:

* generated and never edited, and the SEM dashboard already exists: removed;
* generated and never edited, no SEM dashboard yet: rewritten in place with
  the SEM dashboard, so the URL and the sidebar entry stay;
* edited by the user: left alone, a Repair offers to delete it, and the SEM
  dashboard is created beside it, live when Lovelace runs it, else on the
  next normal restart (a notification says so). Never an automatic restart.

"Never edited" means every view path is a classic path and every card is a
SEM card (or a layout card or one of the cards the generator swapped in).
Home Assistant keeps no edit mark, so a rearranged classic dashboard that
still holds only these cards is read as unedited.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .features.dashboard_generator import (
    NEXT_DASHBOARD_ICON, NEXT_DASHBOARD_PATH, NEXT_DASHBOARD_TITLE, DashboardGenerator,
)

_LOGGER = logging.getLogger(__name__)

RETIRED_FLAG = "_classic_retired"
ISSUE_ID = "classic_dashboard_kept"
CLASSIC_PATH = "sem-dashboard"
CLASSIC_TITLE = "SEM-classic"

# The nine views of the last classic template and their icons, pinned against
# tests/fixtures/classic_dashboard_last.yaml. A view the user renamed, re-iconed
# or added to (badges, theme, visibility...) is edited work (#1321).
CLASSIC_VIEW_ICONS = {
    "home": "mdi:home-lightning-bolt", "energy": "mdi:lightning-bolt", "battery": "mdi:battery-charging-80",
    "ev": "mdi:car-electric", "control": "mdi:tune-vertical", "config": "mdi:cog-outline", "costs": "mdi:cash-multiple",
    "system": "mdi:heart-pulse", "simulation": "mdi:flask-outline",
}
CLASSIC_VIEWS = frozenset(CLASSIC_VIEW_ICONS)
CLASSIC_VIEW_TITLES = frozenset({
    "Home", "Energy", "Battery", "EV", "Control", "Configuration", "Costs", "System", "Simulation",
})
_VIEW_KEYS = frozenset({"path", "type", "cards", "icon", "title"})
NEXT_VIEWS = frozenset({"now", "plan", "devices", "insights", "system"})
# Layout cards hold other cards; they count as generated only when every child does.
_STACKS = frozenset({"vertical-stack", "horizontal-stack", "grid"})
# What the classic generator swapped in for a missing sankey, K-Flow and weather card.
_SWAPPED_TYPES = frozenset({"energy-sankey", "custom:sankey-chart", "custom:k-flow-card", "custom:clock-weather-card"})
_PV_HEALTH = "sensor.sem_pv_health"


def _card_generated(card: Any) -> bool:
    """Is this card, and everything inside it, something the classic generator wrote?

    A ``tile`` only for the PV health sensor, ``markdown`` never (the template
    held none, so a markdown card is the user's note), a stack or a
    conditional only when all its children are generated. Anything unknown is
    edited work: when in doubt the dashboard is kept (#1321).
    """
    if not isinstance(card, dict):
        return False
    kind = str(card.get("type", ""))
    if kind.startswith("custom:sem-") or kind in _SWAPPED_TYPES:
        return True
    if kind in _STACKS:
        children = card.get("cards")
        return isinstance(children, list) and all(_card_generated(c) for c in children)
    if kind == "conditional":
        return _card_generated(card.get("card"))
    if kind == "tile":
        return card.get("entity") == _PV_HEALTH
    return False


def _view_generated(view: Any, titles: frozenset[str]) -> bool:
    if not isinstance(view, dict) or not set(view) <= _VIEW_KEYS:
        return False
    path = str(view.get("path"))
    if path not in CLASSIC_VIEW_ICONS or view.get("icon") != CLASSIC_VIEW_ICONS[path]:
        return False
    if view.get("title") not in titles:
        return False
    cards = view.get("cards")
    return isinstance(cards, list) and all(_card_generated(c) for c in cards)


def classify(config: dict | None, titles: frozenset[str] | None = None) -> str:
    """``classic`` (generated, unedited), ``next`` (already the SEM dashboard)
    or ``edited``. ``titles`` = the view titles the generator can write
    (English plus its translations); default English only."""
    views = (config or {}).get("views") or []
    if not views:
        return "edited"
    paths = {str(v.get("path")) for v in views if isinstance(v, dict)}
    if paths <= NEXT_VIEWS and paths & {"now", "plan", "devices", "insights"}:
        return "next"
    known = CLASSIC_VIEW_TITLES | (titles or frozenset())
    return "classic" if all(_view_generated(v, known) for v in views) else "edited"


def _translated_titles() -> frozenset[str]:
    """Every language's word for each classic view title (from the dashboard translations)."""
    import json
    import os
    try:
        with open(os.path.join(os.path.dirname(__file__), "dashboard", "translations.json"), encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        return frozenset()
    en = table.get("en", {})
    keys = [k for k, v in en.items() if v in CLASSIC_VIEW_TITLES]
    return frozenset(t for lang in table.values() for k in keys if (t := lang.get(k)))


def _live_dashboards(hass: HomeAssistant) -> dict:
    ll_data = hass.data.get("lovelace")
    dashboards = getattr(ll_data, "dashboards", None)
    if dashboards is None and isinstance(ll_data, dict):
        dashboards = ll_data.get("dashboards")
    return dashboards if isinstance(dashboards, dict) else {}


async def _registered_paths(hass: HomeAssistant) -> set[str]:
    data = await Store(hass, 1, "lovelace_dashboards").async_load() or {}
    return {str(i.get("url_path")) for i in data.get("items") or []} | set(_live_dashboards(hass))


async def _save_next_in_place(hass: HomeAssistant, path: str) -> None:
    """Rewrite the dashboard served at ``path`` with the SEM dashboard.

    The row is found by its URL (a dashboard made in the UI has a slug id) and
    changed through HA's running collection when Lovelace is loaded, so HA
    never writes an old list back; the stored files are the fallback.
    """
    from .cleanup import async_dashboard_item, running_dashboards_collection

    config = await DashboardGenerator(hass).generate_dashboard(NEXT_DASHBOARD_TITLE, path)
    payload = {"views": config["views"]}
    item = await async_dashboard_item(hass, path)
    item_id = (item or {}).get("id", path)
    live = _live_dashboards(hass).get(path)
    if live is not None and hasattr(live, "async_save"):
        await live.async_save(payload)
    else:
        await Store(hass, 1, f"lovelace.{item_id}").async_save({"config": payload})
    if item is None:
        return
    changes = {"icon": NEXT_DASHBOARD_ICON}
    if item.get("title") == CLASSIC_TITLE:
        changes["title"] = NEXT_DASHBOARD_TITLE
    collection = running_dashboards_collection(hass)
    if collection is not None and hasattr(collection, "async_update_item"):
        try:
            await collection.async_update_item(item_id, changes)
            return
        except Exception:  # noqa: BLE001
            _LOGGER.debug("SEM migration: the running collection refused, using the file", exc_info=True)
    store = Store(hass, 1, "lovelace_dashboards")
    data = await store.async_load() or {"items": []}
    for row in data.get("items", []):
        if row.get("url_path") == path:
            row.update(changes)
    await store.async_save(data)


def _raise_repair(hass: HomeAssistant, path: str) -> None:
    ir.async_create_issue(
        hass, DOMAIN, ISSUE_ID,
        is_fixable=True, is_persistent=True, severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_ID, translation_placeholders={"path": path},
        data={"path": path},
    )


async def async_retire_classic(hass: HomeAssistant, entry) -> str:
    """Run the one-time migration. Returns what it did: ``done`` (ran
    before), ``none``, ``next``, ``removed``, ``rewritten`` or ``kept``."""
    if entry.options.get(RETIRED_FLAG):
        return "done"
    from .cleanup import async_dashboard_item

    row = await async_dashboard_item(hass, CLASSIC_PATH)  # found by URL; its config is stored under its id
    stored = await Store(hass, 1, f"lovelace.{row['id']}").async_load() if row else None
    titles = await hass.async_add_executor_job(_translated_titles) if stored else None
    verdict = classify((stored or {}).get("config"), titles) if stored else "none"
    result = "none" if verdict == "none" else verdict
    if verdict == "classic":
        if NEXT_DASHBOARD_PATH in await _registered_paths(hass):
            from .cleanup import async_remove_dashboard
            await async_remove_dashboard(hass, CLASSIC_PATH)
            result = "removed"
        else:
            await _save_next_in_place(hass, CLASSIC_PATH)
            result = "rewritten"
    elif verdict == "edited":
        _raise_repair(hass, CLASSIC_PATH)
        if NEXT_DASHBOARD_PATH not in await _registered_paths(hass):
            # (#1321) restart=False: a migration never restarts Home Assistant.
            await hass.services.async_call(
                DOMAIN, "generate_dashboard", {"restart": False}, blocking=True)
        result = "kept"
    new_options = {**entry.options, RETIRED_FLAG: True}
    if result == "rewritten":
        new_options["_next_dashboard_path"] = CLASSIC_PATH  # the SEM dashboard now lives at the old URL
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None:  # the flag is no reason to reload the integration
        coordinator._skip_options_reload = dict(new_options)
    hass.config_entries.async_update_entry(entry, options=new_options)
    _LOGGER.info("SEM classic dashboard retirement: %s", result)
    return result
