"""(#1321) One-time retirement of the classic dashboard.

The classic dashboard (``/sem-dashboard``, nine tabs) is gone; the SEM
dashboard (five screens) is the only one. A stored classic dashboard is
handled once per install, flagged in the entry options:

* generated and never edited, and the SEM dashboard already exists: removed;
* generated and never edited, no SEM dashboard yet: rewritten in place with
  the SEM dashboard, so the URL and the sidebar entry stay;
* edited by the user: left alone, a Repair offers to delete it, and the SEM
  dashboard is created beside it.

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

CLASSIC_VIEWS = frozenset({
    "home", "energy", "battery", "ev", "control", "config", "costs", "system",
    "simulation", "overview", "peak-load-management",
})
NEXT_VIEWS = frozenset({"now", "plan", "devices", "insights", "system"})
# Layout cards, and the cards the classic generator swapped in for a missing
# sankey, a K-Flow diagram and a weather card.
_GENERATED_TYPES = frozenset({
    "vertical-stack", "horizontal-stack", "grid", "conditional", "markdown",
    "energy-sankey", "custom:sankey-chart", "custom:k-flow-card",
    "custom:clock-weather-card",
})


def _card_types(card: Any):
    """Every card ``type`` in a view or card, through stacks and conditionals."""
    if not isinstance(card, dict):
        return
    if "type" in card and "path" not in card:
        yield str(card["type"])
    for key in ("cards", "sections"):
        for child in card.get(key) or []:
            yield from _card_types(child)
    yield from _card_types(card.get("card"))


def classify(config: dict | None) -> str:
    """``classic`` (generated, unedited), ``next`` (already the SEM dashboard)
    or ``edited``."""
    views = (config or {}).get("views") or []
    if not views:
        return "edited"
    paths = {str(v.get("path")) for v in views if isinstance(v, dict)}
    if paths <= NEXT_VIEWS and paths & {"now", "plan", "devices", "insights"}:
        return "next"
    if not paths <= CLASSIC_VIEWS:
        return "edited"
    for view in views:
        for card_type in _card_types({k: v for k, v in view.items() if k != "type"}):
            if not (card_type.startswith("custom:sem-") or card_type in _GENERATED_TYPES):
                return "edited"
    return "classic"


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
    """Rewrite the dashboard stored at ``path`` with the SEM dashboard."""
    config = await DashboardGenerator(hass).generate_dashboard(NEXT_DASHBOARD_TITLE, path)
    payload = {"views": config["views"]}
    live = _live_dashboards(hass).get(path)
    if live is not None and hasattr(live, "async_save"):
        await live.async_save(payload)
    else:
        await Store(hass, 1, f"lovelace.{path}").async_save({"config": payload})
    store = Store(hass, 1, "lovelace_dashboards")
    data = await store.async_load() or {"items": []}
    for item in data.get("items", []):
        if item.get("id") == path:
            item["icon"] = NEXT_DASHBOARD_ICON
            if item.get("title") == CLASSIC_TITLE:
                item["title"] = NEXT_DASHBOARD_TITLE
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
    stored = await Store(hass, 1, f"lovelace.{CLASSIC_PATH}").async_load()
    verdict = classify((stored or {}).get("config")) if stored else "none"
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
            await hass.services.async_call(DOMAIN, "generate_dashboard", {}, blocking=True)
        result = "kept"
    new_options = {**entry.options, RETIRED_FLAG: True}
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None:  # the flag is no reason to reload the integration
        coordinator._skip_options_reload = dict(new_options)
    hass.config_entries.async_update_entry(entry, options=new_options)
    _LOGGER.info("SEM classic dashboard retirement: %s", result)
    return result
