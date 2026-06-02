"""Tests for diagnostics support."""
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from datetime import timedelta

from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
    REDACT_CONFIG_KEYS,
)


@pytest.fixture
def mock_hass(tmp_path):
    hass = MagicMock()
    # v1.6.11 ``_get_recent_sem_logs`` reads
    # ``hass.config.config_dir / home-assistant.log``. Point it at a
    # temp dir so each test gets isolated log content rather than the
    # absent /config path.
    hass.config = MagicMock()
    hass.config.config_dir = str(tmp_path)

    async def _executor(func, *args, **kwargs):
        return func(*args, **kwargs)
    hass.async_add_executor_job = _executor
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
async def test_diagnostics_returns_data(mock_hass, entry, coordinator):
    """Diagnostics should return structured data."""
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(mock_hass, entry)

    assert "config_entry" in result
    assert "coordinator" in result
    assert "power" in result
    assert "charging" in result
    assert "energy_daily" in result
    assert "energy_yearly" in result
    assert "performance" in result


@pytest.mark.asyncio
async def test_diagnostics_redacts_sensitive_fields(mock_hass, entry, coordinator):
    """Diagnostics should redact entity ID fields."""
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(mock_hass, entry)

    config_data = result["config_entry"]["data"]
    # Redacted fields should be "**REDACTED**"
    assert config_data.get("ev_connected_sensor") == "**REDACTED**"
    assert config_data.get("ev_charging_sensor") == "**REDACTED**"
    # Non-sensitive fields should be visible
    assert config_data.get("battery_capacity_kwh") == 10


@pytest.mark.asyncio
async def test_diagnostics_power_values(mock_hass, entry, coordinator):
    """Diagnostics should include current power values."""
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(mock_hass, entry)

    assert result["power"]["solar_w"] == 5000.0
    assert result["power"]["battery_soc"] == 72.0


@pytest.mark.asyncio
async def test_diagnostics_yearly_environmental(mock_hass, entry, coordinator):
    """Diagnostics should include yearly environmental data."""
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(mock_hass, entry)

    assert result["energy_yearly"]["co2_avoided_kg"] == 1.7
    assert result["energy_yearly"]["trees_equivalent"] == 0.1


@pytest.mark.asyncio
async def test_diagnostics_empty_coordinator_data(mock_hass, entry, coordinator):
    """Diagnostics should handle empty coordinator data gracefully."""
    coordinator.data = None
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(mock_hass, entry)

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


# ──────────────────────────────────────────────────────────────────────
# v1.6.11: recent SEM log tail bundled into the Copy-diagnostics output
# ──────────────────────────────────────────────────────────────────────

from pathlib import Path

from custom_components.solar_energy_management.diagnostics import (
    _get_recent_sem_logs,
    _LOG_MAX_LINES,
    _LOG_TAIL_KB,
)


def _write_log(mock_hass, lines: list[str]) -> Path:
    """Write a synthetic ``home-assistant.log`` into the temp config_dir."""
    p = Path(mock_hass.config.config_dir) / "home-assistant.log"
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.mark.asyncio
async def test_recent_logs_returns_only_sem_lines(mock_hass):
    """Filter must select only lines that mention
    ``solar_energy_management`` — other integrations' chatter is
    excluded."""
    _write_log(mock_hass, [
        "2026-05-31 17:42:01.000 INFO (MainThread) [homeassistant.core] starting",
        "2026-05-31 17:42:02.000 DEBUG (MainThread) [custom_components.solar_energy_management.coordinator] cycle ok",
        "2026-05-31 17:42:03.000 WARNING (MainThread) [homeassistant.components.wled] WLED unreachable",
        "2026-05-31 17:42:04.000 INFO (MainThread) [custom_components.solar_energy_management.devices.base] Charging session stopped via keba.disable",
    ])
    out = await _get_recent_sem_logs(mock_hass)
    assert len(out) == 2
    assert all("solar_energy_management" in line for line in out)


@pytest.mark.asyncio
async def test_recent_logs_caps_lines(mock_hass):
    """Even if the log has thousands of SEM lines, only the last
    ``_LOG_MAX_LINES`` (80) are returned."""
    many = [
        f"2026-05-31 17:42:00.{i:03d} INFO (MainThread) [custom_components.solar_energy_management] msg {i}"
        for i in range(_LOG_MAX_LINES * 3)
    ]
    _write_log(mock_hass, many)
    out = await _get_recent_sem_logs(mock_hass)
    assert len(out) == _LOG_MAX_LINES
    # Last line returned is the actual last matching line.
    assert f"msg {_LOG_MAX_LINES * 3 - 1}" in out[-1]


@pytest.mark.asyncio
async def test_recent_logs_missing_file_returns_placeholder(mock_hass):
    """Supervisor installs and other no-file setups must not crash
    and must explain themselves to the bug reporter."""
    # No log file written → ``_get_recent_sem_logs`` returns a single
    # explanatory line instead of raising.
    out = await _get_recent_sem_logs(mock_hass)
    assert len(out) == 1
    assert "no flat log file" in out[0]
    assert "ha core logs" in out[0]


@pytest.mark.asyncio
async def test_recent_logs_truncates_huge_file(mock_hass):
    """Files bigger than ``_LOG_TAIL_KB`` are only tailed — we must
    not OOM on multi-GB logs. The leading partial line gets discarded
    so we never emit a half-line."""
    # Write a > 2 MB log: padding non-SEM lines + SEM lines at the end.
    padding = "x" * (_LOG_TAIL_KB * 1024 + 50_000)  # bigger than the tail
    sem_marker = "2026-05-31 17:42:00.999 INFO [custom_components.solar_energy_management] late"
    _write_log(mock_hass, [padding, sem_marker])
    out = await _get_recent_sem_logs(mock_hass)
    # The SEM line near the end MUST be returned.
    assert any("late" in line for line in out)


@pytest.mark.asyncio
async def test_diagnostics_includes_recent_logs(mock_hass, entry, coordinator):
    """End-to-end: the diagnostics dump now carries a ``recent_logs``
    key. Bug reports come pre-loaded with surrounding context."""
    _write_log(mock_hass, [
        "2026-05-31 17:42:00.000 INFO [custom_components.solar_energy_management.coordinator] success: True",
    ])
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    result = await async_get_config_entry_diagnostics(mock_hass, entry)
    assert "recent_logs" in result
    assert isinstance(result["recent_logs"], list)
    assert any("success: True" in line for line in result["recent_logs"])
