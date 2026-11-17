"""(#1321) The classic dashboard is retired once, on each install.

Branches: unedited and the SEM dashboard exists (removed); unedited and it
does not (rewritten in place, URL kept); edited (kept, a Repair offers to
delete it, the SEM dashboard is created); second run (nothing).
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management import dashboard_migration as dm

ROOT = os.path.dirname(os.path.dirname(__file__))
EXPECTED_PATHS = ["now", "plan", "devices", "insights", "system"]


def _classic(extra_card=None, paths=("home", "energy", "system")):
    cards = [{"type": "vertical-stack", "cards": [
        {"type": "custom:sem-tab-header"}, {"type": "custom:sem-flow-card"},
        {"type": "horizontal-stack", "cards": [{"type": "custom:sem-gauge-card"}]},
        {"type": "conditional", "conditions": [], "card": {"type": "custom:sem-system-diagram-card"}},
    ]}]
    if extra_card:
        cards.append(extra_card)
    return {"views": [{"title": p, "path": p, "type": "panel", "cards": list(cards)} for p in paths]}


class TestClassify:
    def test_a_generated_classic_is_unedited(self):
        assert dm.classify(_classic()) == "classic"

    def test_the_real_last_classic_template_is_unedited(self):
        # The template exactly as the last release shipped it, and the shape
        # the generator stored on a test machine (sankey swapped in). A
        # hand-made fixture missed the PV health tile and every untouched
        # classic was judged edited.
        import yaml
        path = os.path.join(ROOT, "tests", "fixtures", "classic_dashboard_last.yaml")
        with open(path, encoding="utf-8") as fh:
            real = yaml.safe_load(fh)
        assert dm.classify(real) == "classic"
        real["views"][0]["cards"].append({"type": "custom:sankey-chart"})
        assert dm.classify(real) == "classic"

    def test_a_foreign_card_means_edited(self):
        assert dm.classify(_classic({"type": "entities", "entities": []})) == "edited"
        assert dm.classify(_classic({"type": "custom:mushroom-chips-card"})) == "edited"

    def test_a_view_of_the_users_own_means_edited(self):
        assert dm.classify(_classic(paths=("home", "my-view"))) == "edited"

    def test_the_new_dashboard_is_recognised(self):
        new = {"views": [{"path": p, "type": "panel", "cards": [{"type": f"custom:sem-next-{p}-card"}]}
                         for p in EXPECTED_PATHS]}
        assert dm.classify(new) == "next"

    def test_empty_or_missing_is_edited_never_deleted(self):
        assert dm.classify(None) == "edited"
        assert dm.classify({"views": []}) == "edited"


class FakeStores:
    """Stands in for HA's Store: one dict per key."""

    def __init__(self, data):
        self.data = data
        self.saved = {}
        self.removed = []

    def __call__(self, hass, version, key):
        outer = self
        store = MagicMock()

        async def load():
            return outer.data.get(key)

        async def save(value):
            outer.saved[key] = value
            outer.data[key] = value

        store.async_load = load
        store.async_save = save
        return store


def _hass(live=None):
    hass = MagicMock()
    hass.data = {"lovelace": SimpleNamespace(dashboards=live or {})}
    hass.config.config_dir = "/config"
    hass.config.language = "en"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    hass.services.async_call = AsyncMock()
    return hass


def _entry(options=None):
    entry = MagicMock()
    entry.options = dict(options or {})
    entry.runtime_data = SimpleNamespace(_skip_options_reload=None)
    return entry


def _stores(classic=None, next_registered=False):
    data = {}
    if classic is not None:
        data["lovelace.sem-dashboard"] = {"config": classic}
    items = [{"id": "sem-dashboard", "url_path": "sem-dashboard", "title": "SEM-classic",
              "icon": "mdi:solar-power", "mode": "storage"}] if classic is not None else []
    if next_registered:
        items.append({"id": "sem-next", "url_path": "sem-next", "title": "SEM-dashboard",
                      "icon": "mdi:view-dashboard-variant-outline", "mode": "storage"})
    data["lovelace_dashboards"] = {"items": items}
    return FakeStores(data)


@pytest.mark.asyncio
async def test_unedited_and_the_new_dashboard_exists_removes_the_classic():
    stores = _stores(_classic(), next_registered=True)
    hass, entry = _hass(), _entry()
    remove = AsyncMock(return_value=True)
    with patch.object(dm, "Store", stores), \
            patch("custom_components.solar_energy_management.cleanup.async_remove_dashboard", remove):
        assert await dm.async_retire_classic(hass, entry) == "removed"
    remove.assert_awaited_once_with(hass, "sem-dashboard")
    hass.config_entries.async_update_entry.assert_called_once()
    assert hass.config_entries.async_update_entry.call_args.kwargs["options"][dm.RETIRED_FLAG] is True


@pytest.mark.asyncio
async def test_unedited_without_the_new_dashboard_is_rewritten_in_place():
    stores = _stores(_classic())
    hass, entry = _hass(), _entry()
    with patch.object(dm, "Store", stores):
        assert await dm.async_retire_classic(hass, entry) == "rewritten"
    views = stores.saved["lovelace.sem-dashboard"]["config"]["views"]
    assert [v["path"] for v in views] == EXPECTED_PATHS
    item = stores.saved["lovelace_dashboards"]["items"][0]
    assert item["url_path"] == "sem-dashboard" and item["title"] == "SEM-dashboard"
    assert item["icon"] == "mdi:view-dashboard-variant-outline"
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_live_dashboard_is_rewritten_through_its_own_save():
    live = SimpleNamespace(async_save=AsyncMock())
    stores = _stores(_classic())
    with patch.object(dm, "Store", stores):
        assert await dm.async_retire_classic(_hass({"sem-dashboard": live}), _entry()) == "rewritten"
    live.async_save.assert_awaited_once()
    assert [v["path"] for v in live.async_save.call_args.args[0]["views"]] == EXPECTED_PATHS
    assert "lovelace.sem-dashboard" not in stores.saved


@pytest.mark.asyncio
async def test_an_edited_dashboard_is_kept_with_a_repair_and_the_new_one_is_made():
    stores = _stores(_classic({"type": "entities", "entities": []}))
    hass, entry = _hass(), _entry()
    with patch.object(dm, "Store", stores), patch.object(dm, "ir") as ir:
        assert await dm.async_retire_classic(hass, entry) == "kept"
    assert "lovelace.sem-dashboard" not in stores.saved
    kwargs = ir.async_create_issue.call_args.kwargs
    assert ir.async_create_issue.call_args.args[2] == dm.ISSUE_ID
    assert kwargs["is_fixable"] is True and kwargs["data"] == {"path": "sem-dashboard"}
    hass.services.async_call.assert_awaited_once()
    assert hass.services.async_call.call_args.args[:2] == ("solar_energy_management", "generate_dashboard")
    assert hass.services.async_call.call_args.args[2] == {"restart": False}


@pytest.mark.asyncio
async def test_an_edited_dashboard_with_the_new_one_beside_it_makes_no_second():
    stores = _stores(_classic({"type": "entities"}), next_registered=True)
    hass = _hass()
    with patch.object(dm, "Store", stores), patch.object(dm, "ir"):
        assert await dm.async_retire_classic(hass, _entry()) == "kept"
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_classic_dashboard_only_sets_the_flag():
    hass, entry = _hass(), _entry()
    with patch.object(dm, "Store", _stores(None)):
        assert await dm.async_retire_classic(hass, entry) == "none"
    assert hass.config_entries.async_update_entry.call_args.kwargs["options"][dm.RETIRED_FLAG] is True


@pytest.mark.asyncio
async def test_the_second_run_does_nothing():
    stores = _stores(_classic(), next_registered=True)
    hass, entry = _hass(), _entry({dm.RETIRED_FLAG: True})
    with patch.object(dm, "Store", stores):
        assert await dm.async_retire_classic(hass, entry) == "done"
    hass.config_entries.async_update_entry.assert_not_called()
    assert not stores.saved


@pytest.mark.asyncio
async def test_the_flag_write_does_not_reload_the_entry():
    hass, entry = _hass(), _entry()
    with patch.object(dm, "Store", _stores(None)):
        await dm.async_retire_classic(hass, entry)
    snapshot = entry.runtime_data._skip_options_reload
    assert snapshot == hass.config_entries.async_update_entry.call_args.kwargs["options"]


@pytest.mark.asyncio
async def test_the_repair_fix_flow_deletes_the_old_dashboard():
    from custom_components.solar_energy_management.repairs import (
        SEMClassicDashboardFlow, async_create_fix_flow,
    )
    flow = await async_create_fix_flow(MagicMock(), dm.ISSUE_ID, {"path": "sem-dashboard"})
    assert isinstance(flow, SEMClassicDashboardFlow)
    flow.hass = MagicMock()
    remove = AsyncMock(return_value=True)
    with patch("custom_components.solar_energy_management.cleanup.async_remove_dashboard", remove):
        shown = await flow.async_step_init()
        assert shown["type"] == "form" and shown["step_id"] == "confirm"
        done = await flow.async_step_confirm({})
    remove.assert_awaited_once_with(flow.hass, "sem-dashboard")
    assert done["type"] == "create_entry"


def test_the_repair_is_translated_in_every_language():
    import glob
    import json
    files = ["strings.json"] + [os.path.join("translations", os.path.basename(f))
                                for f in sorted(glob.glob(os.path.join(ROOT, "translations", "*.json")))]
    assert len(files) == 17
    for name in files:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            issue = json.load(f)["issues"][dm.ISSUE_ID]
        step = issue["fix_flow"]["step"]["confirm"]
        assert issue["title"] and step["title"] and "{path}" in step["description"], name
        assert "description" not in issue, f"{name}: a fixable issue carries its text in the flow"


@pytest.mark.asyncio
@pytest.mark.parametrize("classic,next_registered", [
    (None, False),
    (_classic(), True),
    (_classic(), False),
    (_classic({"type": "entities"}), False),
    (_classic({"type": "entities"}), True),
])
async def test_no_migration_branch_restarts_home_assistant(classic, next_registered):
    """(#1321) A migration never restarts HA, directly or through the service."""
    hass = _hass()
    with patch.object(dm, "Store", _stores(classic, next_registered)), patch.object(dm, "ir"), \
            patch("custom_components.solar_energy_management.cleanup.async_remove_dashboard", AsyncMock()):
        await dm.async_retire_classic(hass, _entry())
    for call in hass.services.async_call.call_args_list:
        assert call.args[:2] != ("homeassistant", "restart")
        if call.args[1] == "generate_dashboard":
            assert call.args[2].get("restart") is False
