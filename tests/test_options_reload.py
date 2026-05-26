"""Regression tests for the options-flow reload skip (#245 review #1).

A bare `_skip_options_reload` boolean could leak: a stale flag from a number/
switch stepper could swallow a later options-FLOW save (e.g. vehicle_soc_entity),
which then only took effect after a full HA restart. The skip is now keyed to the
exact options payload the entity persisted, so a flow change (different options)
always reloads.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.solar_energy_management import async_update_options


def _make(hass_reload, options, snapshot):
    hass = MagicMock()
    hass.config_entries.async_reload = hass_reload
    entry = MagicMock()
    entry.entry_id = "abc"
    entry.options = options
    coordinator = MagicMock()
    coordinator._skip_options_reload = snapshot
    entry.runtime_data = coordinator
    return hass, entry, coordinator


@pytest.mark.asyncio
async def test_skips_reload_when_snapshot_matches():
    """Runtime tweak: persisted options == snapshot → no reload."""
    reload = AsyncMock()
    opts = {"daily_ev_target": 12}
    hass, entry, coord = _make(reload, opts, dict(opts))
    await async_update_options(hass, entry)
    reload.assert_not_called()
    assert coord._skip_options_reload is None  # consumed


@pytest.mark.asyncio
async def test_reloads_when_flow_changes_after_stale_snapshot():
    """Stale stepper snapshot must NOT swallow a later flow save (the bug)."""
    reload = AsyncMock()
    # snapshot left from an earlier stepper (daily_ev_target=12); the flow then
    # saved a different option (vehicle_soc_entity) → options differ → must reload.
    stale = {"daily_ev_target": 12}
    flow_opts = {"daily_ev_target": 12, "vehicle_soc_entity": "sensor.car_soc"}
    hass, entry, coord = _make(reload, flow_opts, stale)
    await async_update_options(hass, entry)
    reload.assert_called_once_with("abc")
    assert coord._skip_options_reload is None


@pytest.mark.asyncio
async def test_reloads_when_no_snapshot():
    """Plain flow save with no pending snapshot → reload."""
    reload = AsyncMock()
    hass, entry, coord = _make(reload, {"x": 1}, None)
    await async_update_options(hass, entry)
    reload.assert_called_once_with("abc")
