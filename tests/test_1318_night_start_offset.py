"""#1318 — the night window opens at sunset plus a user offset, in every season.

The fixed 20:30 floor is gone: a winter sunset at 17:00 opens the night at
17:30 by default, a summer sunset at 21:25 at 21:55. The offset is the only
knob (0..400 min); a start that would pass midnight is held at 23:59, and a
missing sun reading keeps the old 20:30 so the night never opens at noon.
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.utils.time_manager import TimeManager


def _local(hour: int, minute: int):
    now = dt_util.now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _tm(sunset_local, sunrise_local=None, **config) -> TimeManager:
    sun = MagicMock()
    sun.attributes = {
        "next_setting": sunset_local.isoformat(),
        "next_rising": (sunrise_local or _local(7, 15)).isoformat(),
    }
    sun.state = "below_horizon"
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=sun)
    return TimeManager(hass=hass, config=config)


@pytest.mark.unit
class TestTheStartFollowsTheSun:
    def test_winter_sunset_opens_the_night_half_an_hour_later(self):
        tm = _tm(_local(17, 0))
        assert tm.get_night_start_time() == "17:30"
        assert tm.get_night_window()[0] == "17:30"
        assert tm.get_diagnostics()["sunset_source"] == "sun_integration"

    def test_winter_night_is_night_at_17_45(self):
        tm = _tm(_local(17, 0), sunrise_local=_local(7, 15))
        with patch("homeassistant.util.dt.now", return_value=_local(17, 45)):
            assert tm.is_night_mode() is True

    def test_summer_sunset_opens_the_night_at_21_55(self):
        tm = _tm(_local(21, 25), sunrise_local=_local(5, 30))
        assert tm.get_night_start_time() == "21:55"
        with patch("homeassistant.util.dt.now", return_value=_local(21, 40)):
            assert tm.is_night_mode() is False

    def test_offset_zero_is_sunset_itself(self):
        tm = _tm(_local(17, 0), night_start_offset_min=0)
        assert tm.get_night_start_time() == "17:00"

    def test_offset_400_never_passes_midnight(self):
        tm = _tm(_local(21, 25), night_start_offset_min=400)
        assert tm.get_night_start_time() == "23:59"

    def test_offset_is_clamped_to_its_range(self):
        assert _tm(_local(17, 0), night_start_offset_min=900).get_night_start_time() == "23:40"
        assert _tm(_local(17, 0), night_start_offset_min=-30).get_night_start_time() == "17:00"
        assert _tm(_local(17, 0), night_start_offset_min="abc").get_night_start_time() == "17:30"

    def test_tomorrows_sunset_reading_is_rolled_back_to_today(self):
        """After sunset ``next_setting`` names tomorrow's; the start must
        still be today's sunset plus the offset."""
        tm = _tm(_local(17, 0) + timedelta(days=1))
        assert tm.get_night_start_time() == "17:30"

    def test_no_sun_reading_keeps_the_old_floor(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        tm = TimeManager(hass=hass, config={})
        assert tm.get_night_start_time() == "20:30"
        assert tm.get_diagnostics()["sunset_source"] == "fallback_default"

    def test_sunset_plus_10_is_still_the_sun_frame(self):
        """The day ledger, pacing and daylight code read sunset + 10; the
        offset must not move that frame."""
        tm = _tm(_local(17, 0), night_start_offset_min=120)
        assert tm.get_sunset_plus_10_time() == "17:10"
        assert tm.get_night_start_time() == "19:00"


@pytest.mark.unit
class TestTheNightCanDeliverMore:
    def test_winter_window_grows_from_the_old_floor(self):
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin,
        )
        tm = _tm(_local(17, 0), sunrise_local=_local(7, 15))
        host = SimpleNamespace(time_manager=tm, config={})
        cfg = {"id": "ev", "ev_max_current": 16, "ev_phases": 3, "ev_voltage": 230,
               "ev_target_time": "07:00"}
        with patch("homeassistant.util.dt.now", return_value=_local(12, 0)):
            kwh = EVControlMixin._night_deliverable_kwh(host, cfg)
        old_floor_kwh = 10.5 * 16 * 3 * 230 / 1000.0   # 20:30 → 07:00
        assert kwh > old_floor_kwh
        assert kwh == pytest.approx(13.5 * 16 * 3 * 230 / 1000.0, rel=1e-3)


pytestmark_real = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)


@pytestmark_real
@pytest.mark.asyncio
async def test_setup_removes_the_retired_number_and_switch(sem_real_hass, sem_config_entry):
    """An install that still holds the earliest-start number and the
    forecast night-target switch loses both rows at the next start."""
    from homeassistant.helpers import entity_registry as er
    from custom_components.solar_energy_management.const import DOMAIN

    sem_config_entry.add_to_hass(sem_real_hass)
    registry = er.async_get(sem_real_hass)
    eid = sem_config_entry.entry_id
    old_number = registry.async_get_or_create(
        "number", DOMAIN, f"{eid}_night_earliest_start", config_entry=sem_config_entry,
    ).entity_id
    old_switch = registry.async_get_or_create(
        "switch", DOMAIN, f"{eid}_smart_night_charging", config_entry=sem_config_entry,
    ).entity_id

    assert await sem_real_hass.config_entries.async_setup(eid)
    await sem_real_hass.async_block_till_done()
    try:
        assert registry.async_get(old_number) is None
        assert registry.async_get(old_switch) is None
        kept = {e.unique_id for e in er.async_entries_for_config_entry(registry, eid)}
        assert any(u.endswith("night_start_offset_min") for u in kept)
        assert any(u.endswith("night_latest_end") for u in kept)
    finally:
        await sem_real_hass.config_entries.async_unload(eid)
        await sem_real_hass.async_block_till_done()
