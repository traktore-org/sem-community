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


async def _chk(dev, when, *, sun=False, cheap=False, left=None):
    with patch.object(hwc.dt_util, "now", return_value=when):
        return await dev.check_legionella_cycle(
            good_hour=sun, sun_holds=sun, cheap_hour=cheap, cheap_hours_left=left)


def _cheap_left(dev, t):
    """What the coordinator passes: cheap hours from now to the due time."""
    left_h = dev.legionella_interval_hours - dev.hours_since_legionella
    if dev._last_legionella_time is None or not 0 < left_h <= 24:
        return None
    return 0.25 * sum(1 for i in range(int(left_h * 4))
                      if _cheap(t + timedelta(minutes=15 * i)))


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
    # the low tariff ends well before the run is due: it pauses at once —
    # a tariff does not flicker like a cloud
    assert await _chk(dev, now + timedelta(minutes=121)) == "legionella_early_paused"
    assert dev._legionella_blocked_until is None


@pytest.mark.asyncio
async def test_when_due_it_still_runs_whatever_the_price():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, -1)
    assert await _chk(dev, now) == "legionella_started"
    assert dev._last_legionella_path == "overdue_start"


async def _weeks(rate_k_per_min, days=14):
    hass = _Hass()
    dev = _tank(hass, 48.0)
    t = datetime(2026, 11, 16, 9, 0, tzinfo=hwc.dt_util.DEFAULT_TIME_ZONE)
    dev._last_legionella_time = t - timedelta(hours=40)
    temp, starts, last_done, gaps, dear_min = 48.0, [], dev._last_legionella_time, [], 0
    for _ in range(days * 24 * 60):
        hass.set(SENSOR, f"{temp:.2f}", unit_of_measurement="°C")
        with patch.object(hwc.dt_util, "now", return_value=t):
            left = _cheap_left(dev, t)
        out = await _chk(dev, t, cheap=_cheap(t), left=left)
        if out == "legionella_started":
            starts.append((t, dev._last_legionella_path))
        if out == "legionella_complete":
            gaps.append((t - last_done).total_seconds() / 3600.0)
            last_done = t
        heating = dev._legionella_cycle_active and dev.own_run_needs_heat
        if heating and not _cheap(t):
            dear_min += 1
        temp = min(61.0, temp + rate_k_per_min) if heating else max(48.0, temp - 0.01)
        t += timedelta(minutes=1)
    return starts, gaps, dear_min


@pytest.mark.asyncio
async def test_the_reporters_weeks_run_in_the_low_tariff_and_not_much_early():
    """Low tariff 23–07 and 12–17, no sun, a tank that takes 100 min from
    48 to 60 °C. Over 14 days every run starts in the low tariff, none is
    later than 72 h, none is more than 8 h early (it was 12), and no minute
    is heated at the high rate."""
    starts, gaps, dear_min = await _weeks(0.12)
    assert len(starts) >= 4, starts
    assert all(_cheap(s) for s, _ in starts), [s.strftime("%a %H:%M") for s, _ in starts]
    assert max(gaps) <= 72 + 3 and min(gaps) >= 72 - 8, gaps
    assert dear_min == 0


@pytest.mark.asyncio
async def test_a_slow_tank_learns_to_start_early_enough():
    """A tank that needs about 4.5 h (a run longer than 6 h is given up
    anyway). The first run is timed with a guess and may end at the due
    time; once SEM has timed a run, the next ones start early enough."""
    starts, gaps, _ = await _weeks(0.045, days=21)
    later = [p for _, p in starts[2:]]
    assert later and "overdue_start" not in later, starts
    assert max(gaps) <= 72 + 8, gaps


@pytest.mark.asyncio
async def test_a_sun_started_run_does_not_go_on_through_a_cheap_hour_a_day_early():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, 22)
    await _chk(dev, now, sun=True, left=13.0)
    assert await _chk(dev, now + timedelta(minutes=10), sun=True, left=13.0) == "legionella_started"
    # the sun goes; the hour is cheap, but 13 cheap hours are still ahead
    await _chk(dev, now + timedelta(minutes=20), cheap=True, left=13.0)
    assert await _chk(dev, now + timedelta(minutes=51), cheap=True, left=13.0) == "legionella_early_paused"


@pytest.mark.asyncio
async def test_with_cheap_hours_to_spare_a_cheap_hour_does_not_start_it():
    now = hwc.dt_util.now()
    dev = _tank(_Hass(), 48.0)
    _due_in(dev, now, 8)
    await _chk(dev, now, cheap=True, left=7.0)
    assert await _chk(dev, now + timedelta(minutes=10), cheap=True, left=7.0) is None
    # 5 cheap hours left = the run's 3 h × 1.5 + half an hour: now
    await _chk(dev, now + timedelta(minutes=120), cheap=True, left=5.0)
    assert await _chk(dev, now + timedelta(minutes=130), cheap=True, left=5.0) == "legionella_started"


def test_the_texts_name_the_cheap_hour_in_every_language():
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    d = json.loads((root / "dashboard" / "translations.json").read_text())
    for key in ("hq_st_" + "legionella_soon", "hq_st_" + "legionella_early"):
        assert all(d[lang].get(key) for lang in d)
        assert len({d[lang][key] for lang in d}) == len(d)
