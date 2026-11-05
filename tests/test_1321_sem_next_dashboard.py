"""#1321 — SEM Next, the second dashboard.

Five screens by question, one bundled card each, created on request at
/sem-next beside the classic dashboard, which is never touched.
"""
import json
import os
import re

import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.features.dashboard_generator import (
    NEXT_DASHBOARD_ICON,
    DashboardGenerator,
)

ROOT = os.path.dirname(os.path.dirname(__file__))
NEXT_TEMPLATE = os.path.join(ROOT, "dashboard", "sem_next_template.yaml")
CARD_SRC = os.path.join(ROOT, "dashboard", "card", "src", "cards")
EXPECTED_PATHS = ["now", "plan", "devices", "insights", "system"]


def _registered_card_tags():
    tags = set()
    for name in os.listdir(CARD_SRC):
        if not name.endswith(".js"):
            continue
        with open(os.path.join(CARD_SRC, name), encoding="utf-8") as f:
            tags.update(re.findall(r"semDefineCard\(\s*'([a-z0-9-]+)'", f.read()))
    return tags


@pytest.fixture
def mock_hass(tmp_path):
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)
    hass.data = {}
    hass.states.async_all.return_value = []
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    return hass


@pytest.mark.unit
class TestNextTemplate:
    def test_five_panel_views_by_question(self):
        with open(NEXT_TEMPLATE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        views = data["views"]
        assert [v["path"] for v in views] == EXPECTED_PATHS
        assert all(v.get("type") == "panel" for v in views)
        assert all(len(v["cards"]) == 1 for v in views), "one card per screen"

    def test_every_card_is_a_registered_sem_card(self):
        with open(NEXT_TEMPLATE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        tags = _registered_card_tags()
        for v in data["views"]:
            for card in v["cards"]:
                assert card["type"].startswith("custom:sem-next-")
                assert card["type"][len("custom:"):] in tags, card["type"]

    def test_classic_template_offers_the_link(self):
        with open(os.path.join(ROOT, "dashboard", "sem_dashboard_template.yaml"), encoding="utf-8") as f:
            assert "custom:sem-next-link-card" in f.read()


@pytest.mark.unit
class TestGeneratorNext:
    @pytest.mark.asyncio
    async def test_next_is_generated_at_its_own_path(self, mock_hass):
        gen = DashboardGenerator(mock_hass)
        config = await gen.generate_dashboard(
            dashboard_title="SEM Next", dashboard_path="sem-next", template="next")
        assert [v["path"] for v in config["views"]] == EXPECTED_PATHS
        assert config["path"] == "sem-next"
        assert config["title"] == "SEM Next"
        assert config["icon"] == NEXT_DASHBOARD_ICON

    @pytest.mark.asyncio
    async def test_classic_is_untouched_by_next(self, mock_hass, tmp_path):
        gen = DashboardGenerator(mock_hass)
        storage = tmp_path / ".storage"
        storage.mkdir()
        classic = storage / "lovelace.sem-dashboard"
        classic.write_text('{"data": {"config": {"views": ["classic"]}}}', encoding="utf-8")
        (storage / "lovelace_dashboards").write_text(json.dumps({
            "version": 1, "minor_version": 1, "key": "lovelace_dashboards",
            "data": {"items": [{"id": "sem-dashboard", "url_path": "sem-dashboard",
                                 "title": "Solar Energy Management", "icon": "mdi:solar-power",
                                 "mode": "storage", "show_in_sidebar": True, "require_admin": False}]},
        }), encoding="utf-8")

        assert await gen.create_dashboard(
            dashboard_title="SEM Next", dashboard_path="sem-next", template="next") == "sem-next"

        assert json.loads(classic.read_text(encoding="utf-8"))["data"]["config"]["views"] == ["classic"]
        saved = json.loads((storage / "lovelace.sem-next").read_text(encoding="utf-8"))
        assert [v["path"] for v in saved["data"]["config"]["views"]] == EXPECTED_PATHS
        items = json.loads((storage / "lovelace_dashboards").read_text(encoding="utf-8"))["data"]["items"]
        by_path = {i["url_path"]: i for i in items}
        assert by_path["sem-dashboard"]["title"] == "Solar Energy Management"
        assert by_path["sem-dashboard"]["icon"] == "mdi:solar-power"
        assert by_path["sem-next"]["title"] == "SEM Next"
        assert by_path["sem-next"]["icon"] == NEXT_DASHBOARD_ICON

    @pytest.mark.asyncio
    async def test_classic_default_is_unchanged(self, mock_hass):
        gen = DashboardGenerator(mock_hass)
        config = await gen.generate_dashboard()
        assert len(config["views"]) >= 8
        assert config["path"] == "sem-dashboard"


@pytest.mark.unit
def test_service_accepts_the_template_field():
    with open(os.path.join(ROOT, "services.yaml"), encoding="utf-8") as f:
        services = yaml.safe_load(f)
    field = services["generate_dashboard"]["fields"]["template"]
    assert field["selector"]["select"]["options"] == ["classic", "next"]
    with open(os.path.join(ROOT, "__init__.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'vol.Optional("template", default="classic"): vol.In(["classic", "next"])' in src
