"""#1021 / #1068 — the diagnostics download says what the relay and the
intraday correction did, and never leaks the relay's entity id."""
import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture
def mock_hass(tmp_path):
    hass = MagicMock()
    hass.config = MagicMock()
    hass.config.config_dir = str(tmp_path)

    async def _executor(func, *args, **kwargs):
        return func(*args, **kwargs)
    hass.async_add_executor_job = _executor
    return hass


@pytest.fixture
def entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_1021"
    entry.version = 1
    entry.title = "Solar Energy Management"
    entry.domain = "solar_energy_management"
    entry.data = {}
    entry.options = {"shed_signal_entity": "binary_sensor.secret_relay",
                     "shed_signal_limit": 4.2}
    return entry


def _coordinator(data):
    coord = MagicMock()
    coord.last_update_success = True
    coord.update_interval = timedelta(seconds=10)
    coord._observer_mode = False
    coord._load_manager = None
    coord._energy_dashboard_config = None
    coord.config = {"intraday_forecast": True}
    coord.data = data
    return coord


async def _download(mock_hass, entry, data):
    coord = _coordinator(data)
    entry.runtime_data = coord
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coord}}
    return await async_get_config_entry_diagnostics(mock_hass, entry)


async def test_the_relay_block_and_no_entity_id(mock_hass, entry):
    out = await _download(mock_hass, entry, {
        "shed_signal_entity": "binary_sensor.secret_relay",
        "shed_signal_state": "on", "shed_signal_active": True,
        "shed_signal_cap_kw": 4.2, "shed_signal_since": "2026-10-08T14:05:00+02:00",
        "shed_signal_locked": ["boiler"],
    })
    sig = out["shed_signal"]
    assert sig == {"configured": True, "state": "on", "active": True,
                   "cap_kw": 4.2, "since": "2026-10-08T14:05:00+02:00",
                   "locked_devices": ["boiler"]}
    assert "secret_relay" not in json.dumps(out, default=str)


async def test_the_intraday_numbers(mock_hass, entry):
    out = await _download(mock_hass, entry, {
        "forecast_remaining_today_kwh": 7.1, "forecast_dampening_factor": 0.5,
        "forecast_dampening_path": "blended_live+clamped_low",
        "forecast_corrected_factor": 0.35, "forecast_corrected_floor": 0.1,
    })
    f = out["forecast"]
    assert f["corrected_factor"] == 0.35 and f["corrected_floor"] == 0.1
    assert f["intraday_forecast"] is True


async def test_no_relay_reads_as_not_configured(mock_hass, entry):
    out = await _download(mock_hass, entry, {})
    assert out["shed_signal"]["configured"] is False
    assert out["shed_signal"]["active"] is None
