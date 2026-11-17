"""#1321 — the SEM dashboard: five screens by question, one bundled card each,
at /sem-next. It is the only dashboard; "classic" is a deprecated alias.
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

    def test_the_classic_templates_are_gone(self):
        for name in ("sem_dashboard_template.yaml", "basic_template.yaml"):
            assert not os.path.exists(os.path.join(ROOT, "dashboard", name)), name


@pytest.mark.unit
class TestGeneratorNext:
    @pytest.mark.asyncio
    async def test_next_is_generated_at_its_own_path(self, mock_hass):
        gen = DashboardGenerator(mock_hass)
        config = await gen.generate_dashboard(
            dashboard_title="Solar Energy Management", dashboard_path="sem-next", template="next")
        assert [v["path"] for v in config["views"]] == EXPECTED_PATHS
        assert config["path"] == "sem-next"
        assert config["title"] == "Solar Energy Management"
        assert config["icon"] == NEXT_DASHBOARD_ICON

    @pytest.mark.asyncio
    async def test_it_is_saved_and_registered_at_its_path(self, mock_hass, tmp_path):
        gen = DashboardGenerator(mock_hass)
        assert await gen.create_dashboard(
            dashboard_title="Solar Energy Management", dashboard_path="sem-next") == "sem-next"
        storage = tmp_path / ".storage"
        saved = json.loads((storage / "lovelace.sem-next").read_text(encoding="utf-8"))
        assert [v["path"] for v in saved["data"]["config"]["views"]] == EXPECTED_PATHS
        items = json.loads((storage / "lovelace_dashboards").read_text(encoding="utf-8"))["data"]["items"]
        assert [i["url_path"] for i in items] == ["sem-next"]
        assert items[0]["icon"] == NEXT_DASHBOARD_ICON

    @pytest.mark.asyncio
    async def test_the_default_is_the_new_dashboard(self, mock_hass):
        config = await DashboardGenerator(mock_hass).generate_dashboard()
        assert [v["path"] for v in config["views"]] == EXPECTED_PATHS

    @pytest.mark.asyncio
    async def test_classic_is_an_alias_that_warns_once(self, mock_hass, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            config = await DashboardGenerator(mock_hass).generate_dashboard(template="classic")
        assert [v["path"] for v in config["views"]] == EXPECTED_PATHS
        warns = [r for r in caplog.records if "classic" in r.getMessage() and r.levelno == logging.WARNING]
        assert len(warns) == 1


@pytest.mark.unit
def test_service_accepts_the_template_field():
    with open(os.path.join(ROOT, "services.yaml"), encoding="utf-8") as f:
        services = yaml.safe_load(f)
    field = services["generate_dashboard"]["fields"]["template"]
    assert field["selector"]["select"]["options"] == ["classic", "next"]
    assert field["default"] == "next"          # SEM Next is the default dashboard
    with open(os.path.join(ROOT, "__init__.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'vol.Optional("template", default="next"): vol.In(["classic", "next"])' in src
    assert 'template = call.data.get("template", "next")' in src
    assert "retired" in field["description"]


@pytest.mark.unit
def test_links_follow_the_dashboard_url():
    from types import SimpleNamespace
    from custom_components.solar_energy_management.features.dashboard_generator import sem_dashboard_path
    for paths, want in (({"sem-next": 1}, "sem-next"), ({"sem-dashboard": 1}, "sem-dashboard"),
                        ({"sem-next": 1, "sem-dashboard": 1}, "sem-next"), ({}, "sem-next")):
        hass = MagicMock()
        hass.data = {"lovelace": SimpleNamespace(dashboards=paths)}
        assert sem_dashboard_path(hass) == want
    from custom_components.solar_energy_management import build_welcome_message
    assert "(/my-energy/now)" in build_welcome_message({}, None, "my-energy")


@pytest.mark.unit
def test_the_notifications_do_not_hard_code_the_old_path():
    with open(os.path.join(ROOT, "coordinator", "notifications.py"), encoding="utf-8") as f:
        assert "/sem-dashboard" not in f.read()
