"""(#1321) The hourly solar forecast for the dashboard's Plan chart.

Home Assistant's Energy dashboard reads hourly forecasts through each
integration's ``energy`` platform (``async_get_solar_forecast``); every solar
forecast integration that feeds that dashboard provides it. This command asks every loaded
config entry of such an integration — the same interface, no brand list — and
sums the hours, so several planes or arrays add up. It does not need the
forecast to be linked in the Energy settings.
"""
from __future__ import annotations

from typing import Any, Dict, List

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

WS_SOLAR_FORECAST = "solar_energy_management/solar_forecast"


def merge_wh_hours(answers: List[Dict[str, Any]]) -> Dict[str, float]:
    """Sum the ``wh_hours`` of several forecasts, hour by hour."""
    out: Dict[str, float] = {}
    for ans in answers:
        hours = (ans or {}).get("wh_hours") or {}
        if not isinstance(hours, dict):
            continue
        for ts, wh in hours.items():
            try:
                out[ts] = out.get(ts, 0.0) + float(wh)
            except (TypeError, ValueError):
                continue
    return dict(sorted(out.items()))


def _chosen_platform(hass: HomeAssistant):
    """The forecast integration SEM itself reads, if any (first SEM entry)."""
    from .const import DOMAIN
    for obj in (hass.data.get(DOMAIN) or {}).values():
        coord = getattr(obj, "coordinator", obj)
        reader = getattr(coord, "_forecast_reader", None)
        platform = getattr(reader, "platform", None)
        if isinstance(platform, str) and platform:
            return platform
    return None


async def async_solar_forecast(hass: HomeAssistant) -> Dict[str, Any]:
    """The hourly forecast of ONE service, its arrays summed, from today on.

    Two services side by side forecast the same roof, so they never add up:
    the one SEM reads wins, else the first that answers.
    """
    from homeassistant.components.energy.websocket_api import async_get_energy_platforms
    from homeassistant.util import dt as dt_util

    platforms = await async_get_energy_platforms(hass)
    chosen = _chosen_platform(hass)
    order = ([chosen] if chosen in platforms else []) + [d for d in platforms if d != chosen]
    since = dt_util.start_of_local_day()
    for domain in order:
        answers: List[Dict[str, Any]] = []
        for entry in hass.config_entries.async_entries(domain):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            try:
                ans = await platforms[domain](hass, entry.entry_id)
            except Exception:  # noqa: BLE001 — one broken array never hides the rest
                continue
            if ans and ans.get("wh_hours"):
                answers.append(ans)
        hours = {}
        for ts, wh in merge_wh_hours(answers).items():
            t = dt_util.parse_datetime(ts)
            if t is not None and t >= since:
                hours[ts] = wh
        if hours:
            return {"wh_hours": hours, "source": domain}
    return {"wh_hours": {}, "source": None}


@websocket_api.websocket_command({vol.Required("type"): WS_SOLAR_FORECAST})
@websocket_api.async_response
async def ws_solar_forecast(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The Plan chart's read: hourly Wh by ISO hour, summed over all sources."""
    connection.send_result(msg["id"], await async_solar_forecast(hass))


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the command. Idempotent: a reload overwrites the same slot."""
    websocket_api.async_register_command(hass, ws_solar_forecast)
