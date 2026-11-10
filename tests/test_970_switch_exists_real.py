"""(#970) The peak-hold switch exists on a real setup, off by default."""
from __future__ import annotations

import pytest

from .test_services_real import _seed_sem_input_sensors, _setup_sem


@pytest.mark.asyncio
async def test_the_switch_is_created_and_off(sem_real_hass, sem_config_entry):
    _seed_sem_input_sensors(sem_real_hass)
    await _setup_sem(sem_real_hass, sem_config_entry)
    ids = sorted(s.entity_id for s in sem_real_hass.states.async_all("switch"))
    state = sem_real_hass.states.get("switch.sem_battery_peak_hold_enabled")
    assert state is not None, ids
    assert state.state == "off"
