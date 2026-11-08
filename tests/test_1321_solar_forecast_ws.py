"""(#1321) The Plan chart's hourly sun forecast, from any forecast integration."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.config_entries import ConfigEntryState

from custom_components.solar_energy_management.solar_forecast_ws import (
    async_solar_forecast,
    merge_wh_hours,
)


@pytest.mark.unit
def test_two_arrays_add_up_hour_by_hour():
    merged = merge_wh_hours([
        {"wh_hours": {"2026-11-09T11:00:00+01:00": 900, "2026-11-09T12:00:00+01:00": 1200}},
        {"wh_hours": {"2026-11-09T12:00:00+01:00": 300}},
        None, {"wh_hours": "bad"}, {"wh_hours": {"x": "n/a"}},
    ])
    assert merged == {"2026-11-09T11:00:00+01:00": 900.0, "2026-11-09T12:00:00+01:00": 1500.0}


@pytest.mark.unit
def test_one_service_only_its_arrays_summed_from_today():
    from homeassistant.util import dt as dt_util
    today = dt_util.start_of_local_day()
    h = lambda d, hh: (today + __import__("datetime").timedelta(days=d, hours=hh)).isoformat()
    entries = {
        "forecast_solar": [SimpleNamespace(entry_id="a", state=ConfigEntryState.LOADED),
                           SimpleNamespace(entry_id="b", state=ConfigEntryState.LOADED),
                           SimpleNamespace(entry_id="x", state=ConfigEntryState.NOT_LOADED)],
        "open_meteo_solar_forecast": [SimpleNamespace(entry_id="c", state=ConfigEntryState.LOADED)],
    }
    calls = []

    async def fs(hass, entry_id):
        calls.append(entry_id)
        return {"wh_hours": {h(-1, 12): 999, h(1, 12): 1000}}   # yesterday is dropped

    async def om(hass, entry_id):
        calls.append(entry_id)
        return {"wh_hours": {h(1, 12): 5000}}

    reader = SimpleNamespace(platform="forecast_solar")
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda d: entries.get(d, [])),
        data={"solar_energy_management": {"e1": SimpleNamespace(coordinator=SimpleNamespace(_forecast_reader=reader))}},
    )

    async def platforms(_hass):
        return {"open_meteo_solar_forecast": om, "forecast_solar": fs}

    with patch("homeassistant.components.energy.websocket_api.async_get_energy_platforms", platforms):
        out = asyncio.run(async_solar_forecast(hass))
    assert out == {"wh_hours": {h(1, 12): 2000.0}, "source": "forecast_solar"}   # two arrays, never the other service
    assert calls == ["a", "b"]

    reader.platform = None   # SEM reads no service: the first that answers
    with patch("homeassistant.components.energy.websocket_api.async_get_energy_platforms", platforms):
        out = asyncio.run(async_solar_forecast(hass))
    assert out["source"] == "open_meteo_solar_forecast" and out["wh_hours"] == {h(1, 12): 5000.0}
