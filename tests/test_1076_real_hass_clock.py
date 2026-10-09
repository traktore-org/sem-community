"""(#1076) A real-HA test must not depend on the hour it runs at.

``test_586`` failed once on CI: it stamped its device day at 05:59:35
Pacific, and its ~70 s run put the first tick after the reload at
06:00:05 — past the 06:00 sunrise fallback the test ``hass`` uses (it has
no ``sun.sun``). The device saw a new day and reset the runtime the test
was checking. Re-run, it passed: the wall clock was part of its input.

conftest's ``_real_hass_starts_at_noon`` starts every test that uses
phacc's real ``hass`` at 12:00 today, test-zone time, with the clock
still running — six hours from the sunrise fallback and twelve from
midnight. These tests pin that guard and its two limits: a test that
owns its clock is left alone, and a test without a real ``hass`` keeps
the real clock.
"""
from __future__ import annotations

import importlib.util
import time
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.utils.time_manager import (
    TimeManager,
)


@pytest.mark.asyncio
async def test_a_real_hass_test_starts_at_noon(sem_real_hass) -> None:
    hass = sem_real_hass
    # ``dt_util.now()`` is in hass's zone. The guard computes noon before
    # ``hass`` exists, from a zone it names itself; if phacc ever moves its
    # zone, this fails.
    now = dt_util.now()
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    assert noon <= now < noon + timedelta(minutes=1), (
        f"real-HA test started at {now.time()}, not at 12:00 — the hour "
        "it runs at is part of its input again (#1076)"
    )
    # SEM's own day agrees with the date: no day boundary is near.
    assert TimeManager(hass).get_current_meter_day_sunrise_based() == now.date()


@pytest.mark.asyncio
async def test_the_clock_still_runs(sem_real_hass) -> None:
    # Frozen, every timer and sleep in a real-HA test would stop.
    before = dt_util.utcnow()
    loop_before = sem_real_hass.loop.time()
    time.sleep(0.05)
    assert dt_util.utcnow() > before
    assert sem_real_hass.loop.time() > loop_before


_THREE_AM_PACIFIC = datetime(2026, 3, 1, 11, 0, tzinfo=dt_util.UTC)


# A stopped clock is fine here only because nothing sets SEM up. A test
# that does must pass ``tick=True``, or SEM's 35 s sleep never ends.
@pytest.mark.freeze_time("2026-03-01 11:00:00")
@pytest.mark.asyncio
async def test_a_test_with_a_freeze_time_marker_is_left_alone(hass) -> None:
    # Had the guard run too, it would have moved this test to 12:00
    # Pacific on the frozen date (20:00 UTC).
    assert dt_util.utcnow() == _THREE_AM_PACIFIC


@pytest.mark.asyncio
async def test_a_test_that_asks_for_freezer_is_left_alone(hass, freezer) -> None:
    # Asked for directly, ``freezer`` starts after the guard would, so it
    # always sits inside and moves the time this test reads. The guard's
    # ``freezer`` check is pinned by the marker test above, where
    # pytest-freezer starts first.
    freezer.move_to("2026-03-01 11:00:00")
    assert dt_util.utcnow() == _THREE_AM_PACIFIC


def test_a_test_without_a_real_hass_keeps_the_real_clock() -> None:
    # freezegun never touches CLOCK_REALTIME, so the two agree only when
    # nothing froze this test.
    assert abs(time.time() - time.clock_gettime(time.CLOCK_REALTIME)) < 5
