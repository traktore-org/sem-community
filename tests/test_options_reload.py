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
    """Runtime tweak: persisted options == snapshot → no reload.

    Post-#476 the snapshot is KEPT on a match (it's cleared on mismatch):
    back-to-back runtime writes fire one listener invocation each, all
    seeing the final merged options — consuming on the first match made
    the second invocation reload spuriously.
    """
    reload = AsyncMock()
    opts = {"daily_ev_target": 12}
    hass, entry, coord = _make(reload, opts, dict(opts))
    await async_update_options(hass, entry)
    reload.assert_not_called()
    assert coord._skip_options_reload == opts  # kept for sibling invocations


@pytest.mark.asyncio
async def test_back_to_back_runtime_writes_skip_both_invocations():
    """#476: two quick entity writes → two listener invocations, both
    seeing the final options. Neither may reload."""
    reload = AsyncMock()
    # Writer A persisted {t:12}, writer B persisted {t:12, soc:80} and
    # overwrote the snapshot. Both listener invocations observe B's options.
    final = {"daily_ev_target": 12, "ev_target_soc": 80}
    hass, entry, coord = _make(reload, final, dict(final))
    await async_update_options(hass, entry)  # invocation for write A
    await async_update_options(hass, entry)  # invocation for write B
    reload.assert_not_called()


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
