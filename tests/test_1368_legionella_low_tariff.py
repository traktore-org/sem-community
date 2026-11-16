"""(#1368) The Legionella run started in the high tariff.

The reporter's tank reaches 60 °C only with its electric resistances, so the
hour matters. Low tariff 23:00–07:00 and 12:00–17:00. The run was due at a
high-tariff hour and started there. Now a cheap hour in the last 12 hours
before it is due starts it (the sun still gets the first chance, #1369) —
and it is never later than before.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.devices import hot_water_controller as hwc
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import _Hass
from custom_components.solar_energy_management.tests.test_1369_band_decides_top import (
    SENSOR, _tank,
)


def _cheap(t: datetime) -> bool:
    return t.hour >= 23 or t.hour < 7 or 12 <= t.hour < 17


async def _chk(dev, when, *, sun=False, cheap=False):
    with patch.object(hwc.dt_util, "now", return_value=when):
        return await dev.check_legionella_cycle(
            good_hour=sun, sun_holds=sun, cheap_hour=cheap)


def _due_in(dev, now, hours):
    dev._last_legionella_time = now - timedelta(
        hours=dev.legionella_interval_hours - hours)


@pytest.mark.asyncio
async def test_a_cheap_hour_in_the_last_12_hours_starts_it():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, 8)
    assert await _chk(dev, now, cheap=True) is None                 # 10 min hold
    assert await _chk(dev, now + timedelta(minutes=10), cheap=True) == "legionella_started"
    assert dev._last_legionella_path == "early_start"


@pytest.mark.asyncio
async def test_earlier_than_12_hours_a_cheap_hour_waits_for_the_sun():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, 20)
    await _chk(dev, now, cheap=True)
    assert await _chk(dev, now + timedelta(minutes=10), cheap=True) is None
    # the sun may start it there
    await _chk(dev, now + timedelta(minutes=11), sun=True)
    assert await _chk(dev, now + timedelta(minutes=21), sun=True) == "legionella_started"


@pytest.mark.asyncio
async def test_a_run_goes_on_through_cheap_hours_and_stops_when_they_end():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, 8)
    await _chk(dev, now, cheap=True)
    await _chk(dev, now + timedelta(minutes=10), cheap=True)
    assert await _chk(dev, now + timedelta(minutes=120), cheap=True) == "legionella_heating"
    # the low tariff ends well before the run is due: it pauses after 30 min
    assert await _chk(dev, now + timedelta(minutes=121)) == "legionella_heating"
    assert await _chk(dev, now + timedelta(minutes=152)) == "legionella_early_paused"
    assert dev._legionella_blocked_until is None


@pytest.mark.asyncio
async def test_when_due_it_still_runs_whatever_the_price():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, -1)
    assert await _chk(dev, now) == "legionella_started"
    assert dev._last_legionella_path == "overdue_start"


@pytest.mark.asyncio
async def test_the_reporters_week_never_starts_in_the_high_tariff():
    """Low tariff 23–07 and 12–17, no sun, a tank that takes 100 min from
    48 to 60 °C: over 10 days every run starts in the low tariff, and no
    run is later than the 72 h interval."""
    hass = _Hass()
    dev = _tank(hass, 48.0)
    t = datetime(2026, 11, 16, 9, 0, tzinfo=hwc.dt_util.DEFAULT_TIME_ZONE)
    dev._last_legionella_time = t - timedelta(hours=40)
    temp, starts, last_done, gaps = 48.0, [], dev._last_legionella_time, []
    for _ in range(10 * 24 * 60):
        hass.set(SENSOR, f"{temp:.2f}", unit_of_measurement="°C")
        out = await _chk(dev, t, cheap=_cheap(t))
        if out == "legionella_started":
            starts.append(t)
        if out == "legionella_complete":
            gaps.append((t - last_done).total_seconds() / 3600.0)
            last_done = t
        heating = dev._legionella_cycle_active and dev.own_run_needs_heat
        temp = min(61.0, temp + 0.12) if heating else max(48.0, temp - 0.01)
        t += timedelta(minutes=1)
    assert len(starts) >= 3, starts
    assert all(_cheap(s) for s in starts), [s.strftime("%a %H:%M") for s in starts]
    assert max(gaps) <= dev.legionella_interval_hours + 3, gaps


def test_the_texts_name_the_cheap_hour_in_every_language():
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    d = json.loads((root / "dashboard" / "translations.json").read_text())
    key = "hq_st_" + "legionella_soon"
    assert all("12" in d[lang][key] for lang in d)
