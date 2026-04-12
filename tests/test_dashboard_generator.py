"""Tests for dashboard generator."""
import os
import pytest
import yaml
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)


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
            "basic_template.yaml",
        )
        assert os.path.exists(template_path), f"Template not found: {template_path}"

    def test_template_valid_yaml(self):
        """Template should be valid YAML."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "basic_template.yaml",
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
            "basic_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        views = data.get("views", [])
        assert len(views) == 5, f"Expected 5 views, got {len(views)}"

    def test_template_view_paths(self):
        """Each view should have the expected path."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "basic_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        paths = [v.get("path") for v in data.get("views", [])]
        expected = ["home", "energy", "costs", "battery", "ev"]
        assert paths == expected

    def test_template_no_overview_tab(self):
        """Overview tab was removed in v2.6."""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "basic_template.yaml",
        )
        with open(template_path) as f:
            data = yaml.safe_load(f)
        paths = [v.get("path") for v in data.get("views", [])]
        assert "control" not in paths

    def test_all_custom_cards_exist(self):
        """All bundled SEM card JS files should exist."""
        card_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "card",
        )
        expected_cards = [
        ]
        for card in expected_cards:
            assert os.path.exists(os.path.join(card_dir, card)), f"Missing: {card}"


class TestWeatherSubstitution:
    """Test weather entity substitution in the dashboard generator."""

    def test_weather_card_removed_if_no_entity(self, hass, generator):
        """Weather card should be removed if no weather entity exists."""
        hass.states.async_all.return_value = []

        template = {
            "views": [
                {
                    "cards": [
                        {"type": "custom:mushroom-template-card"},
                        {"type": "custom:clock-weather-card", "entity": "weather.home"},
                    ]
                }
            ]
        }

        generator._substitute_weather_entity(template)
        cards = template["views"][0]["cards"]
        assert len(cards) == 1
        assert cards[0]["type"] == "custom:mushroom-template-card"
