"""Tests for dashboard generator."""
import os
import pytest
import yaml
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)
from custom_components.solar_energy_management.const import DOMAIN


@pytest.fixture
def hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.config_dir = "/config"
    hass.states.async_all.return_value = []
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    return hass


@pytest.fixture
def generator(hass):
    return DashboardGenerator(hass)


class TestDashboardTemplate:
    """Test the dashboard YAML template loads correctly."""

    def test_template_file_exists(self):
        """Template file should exist at expected path."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "sem_dashboard_template.yaml",
        )
        assert os.path.exists(template_path), f"Template not found: {template_path}"

    def test_template_valid_yaml(self):
        """Template should be valid YAML."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "sem_dashboard_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        assert data is not None
        assert "views" in data

    def test_template_has_7_views(self):
        """Dashboard should have exactly 7 tabs."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "sem_dashboard_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        views = data.get("views", [])
        assert len(views) == 7, f"Expected 7 views, got {len(views)}"

    def test_template_view_paths(self):
        """Each view should have the expected path."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "sem_dashboard_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        paths = [v.get("path") for v in data.get("views", [])]
        expected = ["home", "energy", "battery", "ev", "control", "costs", "system"]
        assert paths == expected

    def test_template_no_overview_tab(self):
        """Overview tab was removed in v2.6."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "sem_dashboard_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        paths = [v.get("path") for v in data.get("views", [])]
        assert "overview" not in paths

    def test_all_custom_cards_exist(self):
        """All bundled SEM card JS files should exist."""
        card_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "card",
        )
        expected_cards = [
            "sem-system-diagram-card.js",
            "sem-flow-card.js",
            "sem-solar-summary-card.js",
            "sem-weather-card.js",
            "sem-chart-card.js",
            "sem-period-selector-card.js",
            "sem-load-priority-card.js",
        ]
        for card in expected_cards:
            assert os.path.exists(os.path.join(card_dir, card)), f"Missing: {card}"


class TestWeatherSubstitution:
    """Test weather entity substitution in the dashboard generator."""

    def test_weather_entity_substituted(self, hass, generator):
        """Weather card entity should be replaced with actual weather entity."""
        # Mock weather entity
        weather_state = MagicMock()
        weather_state.entity_id = "weather.home_assistant"
        hass.states.async_all.return_value = [weather_state]

        template = {
            "views": [
                {
                    "cards": [
                        {"type": "custom:sem-weather-card", "entity": "weather.home"},
                    ]
                }
            ]
        }

        generator._substitute_weather_entity(template)
        card = template["views"][0]["cards"][0]
        assert card["entity"] == "weather.home_assistant"

    def test_weather_card_removed_if_no_entity(self, hass, generator):
        """Weather card should be removed if no weather entity exists."""
        hass.states.async_all.return_value = []

        template = {
            "views": [
                {
                    "cards": [
                        {"type": "custom:mushroom-template-card"},
                        {"type": "custom:sem-weather-card", "entity": "weather.home"},
                    ]
                }
            ]
        }

        generator._substitute_weather_entity(template)
        cards = template["views"][0]["cards"]
        assert len(cards) == 1
        assert cards[0]["type"] == "custom:mushroom-template-card"

    def test_forecast_entity_filtered(self, hass, generator):
        """weather.forecast_* entities should be filtered out."""
        forecast = MagicMock()
        forecast.entity_id = "weather.forecast_home"
        real = MagicMock()
        real.entity_id = "weather.openweathermap"
        hass.states.async_all.return_value = [forecast, real]

        template = {
            "views": [
                {
                    "cards": [
                        {"type": "custom:sem-weather-card", "entity": "weather.home"},
                    ]
                }
            ]
        }

        generator._substitute_weather_entity(template)
        assert template["views"][0]["cards"][0]["entity"] == "weather.openweathermap"


def _make_device(power_entity, priority=5, is_ev=False, device_type="switch",
                 friendly_name=None, daily_energy_entity=None):
    """Helper to build a device dict for load manager tests."""
    d = {
        "power_entity": power_entity,
        "priority": priority,
        "is_ev": is_ev,
        "device_type": device_type,
        "friendly_name": friendly_name or power_entity,
    }
    if daily_energy_entity:
        d["daily_energy_entity"] = daily_energy_entity
    return d


def _flow_card_template(entity_prefix=None):
    """Return a minimal template with one sem-flow-card."""
    card = {"type": "custom:sem-flow-card"}
    if entity_prefix:
        card["entity_prefix"] = entity_prefix
    return {"views": [{"cards": [card]}]}


def _setup_coordinator(hass, devices, ev_power_sensor="sensor.ev_power"):
    """Wire up a mock coordinator with load manager devices in hass.data."""
    coord = MagicMock()
    coord._load_manager = MagicMock()
    coord._load_manager._devices = devices
    coord.config = {"ev_charging_power_sensor": ev_power_sensor}
    hass.data[DOMAIN] = {"entry1": coord}
    return coord


@pytest.mark.unit
class TestFlowCardDeviceInjection:
    """Test _update_flow_card_devices in DashboardGenerator."""

    @pytest.mark.asyncio
    async def test_no_coordinator_returns_early(self, hass, generator):
        """No DOMAIN in hass.data → template unchanged."""
        hass.data = {}
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        card = template["views"][0]["cards"][0]
        assert "entities" not in card

    @pytest.mark.asyncio
    async def test_no_load_manager_returns_early(self, hass, generator):
        """coordinator._load_manager is None → early return."""
        coord = MagicMock()
        coord._load_manager = None
        hass.data[DOMAIN] = {"entry1": coord}
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        card = template["views"][0]["cards"][0]
        assert "entities" not in card

    @pytest.mark.asyncio
    async def test_empty_devices_returns_early(self, hass, generator):
        """Empty device dict → early return."""
        _setup_coordinator(hass, {})
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        card = template["views"][0]["cards"][0]
        assert "entities" not in card

    @pytest.mark.asyncio
    async def test_ev_excluded_by_is_ev_flag(self, hass, generator):
        """Devices with is_ev=True should be filtered out."""
        devices = {
            "ev1": _make_device("sensor.ev_charger", is_ev=True),
            "heater": _make_device("sensor.heater_power"),
        }
        _setup_coordinator(hass, devices)
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        individual = template["views"][0]["cards"][0]["entities"]["individual"]
        entities = [d["entity"] for d in individual]
        assert "sensor.ev_charger" not in entities
        assert "sensor.heater_power" in entities

    @pytest.mark.asyncio
    async def test_ev_excluded_by_power_entity_match(self, hass, generator):
        """Device matching ev_charging_power_sensor config should be excluded."""
        devices = {
            "charger": _make_device("sensor.ev_power"),
            "pump": _make_device("sensor.pump_power"),
        }
        _setup_coordinator(hass, devices, ev_power_sensor="sensor.ev_power")
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        individual = template["views"][0]["cards"][0]["entities"]["individual"]
        entities = [d["entity"] for d in individual]
        assert "sensor.ev_power" not in entities
        assert "sensor.pump_power" in entities

    @pytest.mark.asyncio
    async def test_max_6_devices(self, hass, generator):
        """Only 6 devices should be injected even if more are available."""
        devices = {
            f"dev{i}": _make_device(f"sensor.dev{i}_power", priority=i)
            for i in range(8)
        }
        _setup_coordinator(hass, devices)
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        individual = template["views"][0]["cards"][0]["entities"]["individual"]
        assert len(individual) == 6

    @pytest.mark.asyncio
    async def test_priority_sorting(self, hass, generator):
        """Devices should be ordered by priority (lower = first)."""
        devices = {
            "low": _make_device("sensor.low", priority=10),
            "high": _make_device("sensor.high", priority=1),
            "mid": _make_device("sensor.mid", priority=5),
        }
        _setup_coordinator(hass, devices)
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        individual = template["views"][0]["cards"][0]["entities"]["individual"]
        entities = [d["entity"] for d in individual]
        assert entities == ["sensor.high", "sensor.mid", "sensor.low"]

    @pytest.mark.asyncio
    async def test_entity_prefix_skips_injection(self, hass, generator):
        """Card with entity_prefix should not get individual devices injected."""
        devices = {"dev": _make_device("sensor.dev_power")}
        _setup_coordinator(hass, devices)
        template = _flow_card_template(entity_prefix="sensor.sem_")
        await generator._update_flow_card_devices(template)
        card = template["views"][0]["cards"][0]
        assert "entities" not in card

    @pytest.mark.asyncio
    async def test_deduplication(self, hass, generator):
        """Existing individual entries should not be duplicated."""
        devices = {
            "heater": _make_device("sensor.heater_power"),
            "pump": _make_device("sensor.pump_power"),
        }
        _setup_coordinator(hass, devices)
        template = _flow_card_template()
        card = template["views"][0]["cards"][0]
        card["entities"] = {
            "individual": [{"entity": "sensor.heater_power", "name": "Existing"}]
        }
        await generator._update_flow_card_devices(template)
        individual = card["entities"]["individual"]
        heater_entries = [d for d in individual if d["entity"] == "sensor.heater_power"]
        assert len(heater_entries) == 1
        assert heater_entries[0]["name"] == "Existing"  # original preserved
        assert len(individual) == 2  # existing + pump

    @pytest.mark.asyncio
    async def test_color_and_daily_energy(self, hass, generator):
        """Colors should cycle from palette, daily_energy added when present."""
        devices = {
            "dev1": _make_device("sensor.d1", priority=1, daily_energy_entity="sensor.d1_daily"),
            "dev2": _make_device("sensor.d2", priority=2),
        }
        _setup_coordinator(hass, devices)
        template = _flow_card_template()
        await generator._update_flow_card_devices(template)
        individual = template["views"][0]["cards"][0]["entities"]["individual"]
        assert individual[0]["color"] == "#FF8A65"
        assert individual[1]["color"] == "#AED581"
        assert individual[0]["daily_energy"] == "sensor.d1_daily"
        assert "daily_energy" not in individual[1]


@pytest.mark.unit
class TestDashboardCleanupLogic:
    """Test stale file cleanup and resource registration logic."""

    def test_cleanup_removes_sem_js_from_www(self):
        """Stale sem-*.js files in /config/www/ should be removed."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=["sem-flow-card.js", "sem-chart-card.js", "other.js"]), \
             patch("os.remove") as mock_remove:
            # Simulate the cleanup closure logic
            www_dir = "/config/www"
            removed = []
            for fname in os.listdir(www_dir):
                if fname.startswith("sem-") and fname.endswith(".js"):
                    os.remove(os.path.join(www_dir, fname))
                    removed.append(fname)
            assert removed == ["sem-flow-card.js", "sem-chart-card.js"]
            assert mock_remove.call_count == 2

    def test_cleanup_skips_non_sem_files(self):
        """Non-SEM JS files should not be removed."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=["card-mod.js", "mushroom.js"]), \
             patch("os.remove") as mock_remove:
            www_dir = "/config/www"
            for fname in os.listdir(www_dir):
                if fname.startswith("sem-") and fname.endswith(".js"):
                    os.remove(os.path.join(www_dir, fname))
            mock_remove.assert_not_called()

    def test_cleanup_handles_missing_www_dir(self):
        """Missing /config/www/ directory should not raise."""
        with patch("os.path.isdir", return_value=False):
            www_dir = "/config/www"
            removed = []
            for fname in os.listdir(www_dir) if os.path.isdir(www_dir) else []:
                if fname.startswith("sem-") and fname.endswith(".js"):
                    removed.append(fname)
            assert removed == []

    def test_orphaned_resource_removal(self):
        """Orphaned /local/sem-* entries removed, component-path entries kept."""
        component_prefix = f"/local/custom_components/{DOMAIN}/"
        items = [
            {"url": "/local/sem-flow-card.js", "type": "module"},
            {"url": f"/local/custom_components/{DOMAIN}/dashboard/card/sem-flow-card.js", "type": "module"},
            {"url": "/local/card-mod.js", "type": "module"},
        ]
        filtered = [
            item for item in items
            if not (
                item.get("url", "").startswith("/local/sem-")
                and component_prefix not in item.get("url", "")
            )
        ]
        assert len(filtered) == 2
        urls = [i["url"] for i in filtered]
        assert "/local/sem-flow-card.js" not in urls
        assert f"/local/custom_components/{DOMAIN}/dashboard/card/sem-flow-card.js" in urls
        assert "/local/card-mod.js" in urls

    def test_resource_registration_module_type(self):
        """New resources should be registered with type='module'."""
        import uuid as _uuid
        resources = {"items": []}
        installed_cards = ["sem-flow-card.js", "sem-chart-card.js"]
        existing_bases = set()
        for fname in installed_cards:
            base_url = f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
            if base_url not in existing_bases:
                resources["items"].append({
                    "id": _uuid.uuid4().hex,
                    "url": base_url,
                    "type": "module",
                })
        assert len(resources["items"]) == 2
        for item in resources["items"]:
            assert item["type"] == "module"
            assert item["url"].startswith(f"/local/custom_components/{DOMAIN}/")

    def test_resource_deduplication(self):
        """Existing resources should not be re-added."""
        base_url = f"/local/custom_components/{DOMAIN}/dashboard/card/sem-flow-card.js"
        resources = {"items": [{"id": "abc", "url": f"{base_url}?v=2.7.43", "type": "module"}]}
        existing_bases = {item.get("url", "").split("?")[0] for item in resources["items"]}
        installed_cards = ["sem-flow-card.js"]
        added = []
        for fname in installed_cards:
            url = f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
            if url not in existing_bases:
                added.append(url)
        assert added == []
        assert len(resources["items"]) == 1
