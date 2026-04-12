"""Tests for diagnostics support."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import timedelta

from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
    REDACT_CONFIG_KEYS,
)


@pytest.fixture
def hass():
    hass = MagicMock()
    return hass


@pytest.fixture
def entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.version = 1
    entry.title = "Solar Energy Management"
    entry.domain = "solar_energy_management"
    entry.data = {
        "battery_capacity_kwh": 10,
        "target_peak_limit": 5.0,
        "ev_connected_sensor": "binary_sensor.keba_connected",
        "ev_charging_sensor": "binary_sensor.keba_charging",
    }
    entry.options = {
        "update_interval": 10,
        "ev_charging_power_sensor": "sensor.keba_power",
    }
    return entry


@pytest.fixture
def coordinator():
    coord = MagicMock()
    coord.last_update_success = True
    coord.update_interval = timedelta(seconds=10)
    coord._observer_mode = False
    coord._load_manager = None
    coord._energy_dashboard_config = None
    coord.data = {
        "solar_power": 5000.0,
        "grid_power": -500.0,
        "battery_power": 1000.0,
        "home_consumption_power": 3500.0,
        "ev_power": 0.0,
        "battery_soc": 72.0,
        "charging_state": "idle",
        "charging_strategy": "idle",
        "daily_solar_energy": 12.5,
        "yearly_co2_avoided": 1.7,
        "yearly_trees_equivalent": 0.1,
        "self_consumption_rate": 94.2,
        "autarky_rate": 56.0,
    }
    return coord


@pytest.mark.asyncio
async def test_diagnostics_returns_data(hass, entry, coordinator):
    """Diagnostics should return structured data."""
    hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "config_entry" in result
    assert "coordinator" in result
    assert "power" in result
    assert "charging" in result
    assert "energy_daily" in result
    assert "energy_yearly" in result
    assert "performance" in result


@pytest.mark.asyncio
async def test_diagnostics_redacts_sensitive_fields(hass, entry, coordinator):
    """Diagnostics should redact entity ID fields."""
    hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(hass, entry)

    config_data = result["config_entry"]["data"]
    # Redacted fields should be "**REDACTED**"
    assert config_data.get("ev_connected_sensor") == "**REDACTED**"
    assert config_data.get("ev_charging_sensor") == "**REDACTED**"
    # Non-sensitive fields should be visible
    assert config_data.get("battery_capacity_kwh") == 10


@pytest.mark.asyncio
async def test_diagnostics_power_values(hass, entry, coordinator):
    """Diagnostics should include current power values."""
    hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["power"]["solar_w"] == 5000.0
    assert result["power"]["battery_soc"] == 72.0


@pytest.mark.asyncio
async def test_diagnostics_yearly_environmental(hass, entry, coordinator):
    """Diagnostics should include yearly environmental data."""
    hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["energy_yearly"]["co2_avoided_kg"] == 1.7
    assert result["energy_yearly"]["trees_equivalent"] == 0.1


@pytest.mark.asyncio
async def test_diagnostics_empty_coordinator_data(hass, entry, coordinator):
    """Diagnostics should handle empty coordinator data gracefully."""
    coordinator.data = None
    hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["power"]["solar_w"] is None
    assert result["charging"]["state"] == "None"


def test_redact_keys_defined():
    """Redaction keys should cover sensitive entity fields."""
    assert "ev_connected_sensor" in REDACT_CONFIG_KEYS
    assert "ev_charging_power_sensor" in REDACT_CONFIG_KEYS
    assert "vehicle_soc_entity" in REDACT_CONFIG_KEYS
    # Non-sensitive keys should NOT be in redact list
    assert "battery_capacity_kwh" not in REDACT_CONFIG_KEYS
    assert "target_peak_limit" not in REDACT_CONFIG_KEYS
