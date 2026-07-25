"""#636 — config-card peak sliders live-apply through the load manager."""
from unittest.mock import AsyncMock, MagicMock

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
