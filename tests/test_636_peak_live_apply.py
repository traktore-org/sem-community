"""#636 — config-card peak sliders live-apply through the load manager."""
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)


def _lm():
    lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
    lm.hass = MagicMock()
    lm.config_entry = MagicMock(options={})
    lm.config_entry.runtime_data = MagicMock()
    lm._target_peak_limit = 6.0
    lm._warning_level = 4.5
    lm._emergency_level = 6.0
    lm._trigger_callbacks = MagicMock()
    return lm


@pytest.mark.asyncio
class TestLiveSetters636:
    async def test_warning_level_live_applies_real_field(self):
        lm = _lm()
        await lm.update_warning_peak_level(3.0)
        assert lm._warning_level == 3.0          # the REAL runtime field
        lm._trigger_callbacks.assert_called()

    async def test_emergency_level_live_applies_real_field(self):
        lm = _lm()
        await lm.update_emergency_peak_level(7.5)
        assert lm._emergency_level == 7.5

    async def test_target_peak_still_live(self):
        lm = _lm()
        await lm.update_target_peak_limit(9.0)
        assert lm._target_peak_limit == 9.0


@pytest.mark.asyncio
class TestSnapshotSentinel636b:
    """(#636b) The live setters must arm the SNAPSHOT convention the options
    listener honours — the legacy bool True never matched and a redundant
    reload followed every live-apply."""

    async def test_setter_arms_dict_snapshot_not_bool(self):
        lm = _lm()
        coord = lm.config_entry.runtime_data
        await lm.update_target_peak_limit(7.0)
        snap = coord._skip_options_reload
        assert isinstance(snap, dict)                    # not the legacy bool
        assert snap.get("target_peak_limit") == 7.0
        assert isinstance(coord._skip_options_reload_armed_at, float)

    async def test_snapshot_matches_persisted_options(self):
        lm = _lm()
        lm.config_entry.options = {"existing": 1}
        coord = lm.config_entry.runtime_data
        await lm.update_warning_peak_level(3.5)
        # the listener compares dict(entry.options) == snapshot: they must align
        args = lm.hass.config_entries.async_update_entry.call_args
        assert args.kwargs["options"] == coord._skip_options_reload
