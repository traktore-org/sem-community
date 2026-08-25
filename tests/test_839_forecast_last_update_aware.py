"""#839 — the forecast's timestamp must be timezone-aware.

Reported by @coppe218 on 2026-08-25, in diagnostics attached to a different
issue (#804). Repeating every single cycle on their install:

    Battery scheduler evaluate failed: can't subtract offset-naive and
    offset-aware datetimes
      coordinator.py:6385
        forecast_age = (now - forecast.last_update).total_seconds() / 3600
    TypeError: can't subtract offset-naive and offset-aware datetimes

Both halves of that subtraction come from SEM:

* ``now = dt_util.now()`` — Home Assistant's local time, timezone-AWARE;
* ``ForecastData.last_update = datetime.now()`` — NAIVE.

So it could never have worked. It is not intermittent and not
environment-specific; it raises on every evaluation where a forecast is
available.

**Why nobody noticed.** ``_maybe_run_scheduler_evaluation`` only runs when the
battery charge scheduler is switched on, and it is off by default and off on
both of our rigs. The failure is caught and logged as a warning, so the
integration keeps running and the dashboard looks healthy — while the battery
charge scheduler never evaluates once. A user who enabled the feature got a
silently inert one plus a warning every ten seconds.

The fix is to stop producing naive timestamps at all. ``dt_util.now()`` is
what the rest of SEM uses; ``datetime.now()`` was the outlier, and it was the
outlier in three places, so all three are corrected rather than only the one
that happened to be reported.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.util import dt as dt_util


def _reader():
    """A reader whose cached source still validates, so ``read_forecast``
    reaches the branch that stamps ``last_update``.

    The first draft of this helper returned ``None`` for every state, so the
    cached source looked gone, detection re-ran, found nothing and returned an
    empty ForecastData with ``last_update=None`` — the test failed against a
    correct fix. The sensor has to actually read.
    """
    from types import SimpleNamespace

    from custom_components.solar_energy_management.coordinator.forecast_reader import (
        ForecastReader,
    )
    state = SimpleNamespace(state="12.5",
                            attributes={"unit_of_measurement": "kWh"})
    hass = MagicMock()
    hass.states.async_all.return_value = []
    hass.states.get = lambda eid: state if eid == "sensor.x" else None
    r = ForecastReader(hass, custom_entities=None, preferred_source=None)
    r._source = "forecast_solar"
    r._entities = {"forecast_today": "sensor.x"}
    return r


class TestTheTimestampIsAware:
    def test_read_forecast_stamps_an_aware_datetime(self):
        data = _reader().read_forecast()
        assert data.last_update is not None
        assert data.last_update.tzinfo is not None, (
            "last_update is naive — subtracting it from dt_util.now() raises "
            "and the battery scheduler never evaluates (#839)"
        )

    def test_the_exact_subtraction_that_crashed_now_works(self):
        """The reporter's line, verbatim in shape."""
        data = _reader().read_forecast()
        now = dt_util.now()
        age = (now - data.last_update).total_seconds() / 3600
        assert age >= 0.0

    def test_it_would_have_raised_before(self):
        """Guard the premise: naive really is incompatible here, so this test
        cannot quietly stop testing anything if HA's helpers change."""
        import datetime as _dt
        naive = _dt.datetime.now()
        with pytest.raises(TypeError):
            _ = dt_util.now() - naive


class TestNoNaiveStampsRemain:
    """Fix ALL instances in one pass, and keep them fixed."""

    def test_no_module_stamps_last_update_naively(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        pattern = re.compile(r"last_update\s*=\s*datetime\.now\(\)")
        for path in root.rglob("*.py"):
            parts = path.parts
            if "tests" in parts or "node_modules" in parts or "scripts" in parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(text):
                offenders.append(str(path.relative_to(root)))
        assert not offenders, (
            f"naive last_update stamps are back in {offenders} — they cannot "
            "be compared against dt_util.now() and raise TypeError (#839)"
        )
