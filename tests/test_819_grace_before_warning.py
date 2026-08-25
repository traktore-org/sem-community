"""#819 follow-up — "not loaded yet" must not be reported as "not installed".

The reporter confirmed the picker fix on beta.15 by forecast VALUE across all
three integrations, and then found this in their diagnostics::

    WARNING  Chosen solar forecast source forecast_solar is not installed
             — falling back to auto-detection

while ``forecast_source`` read ``forecast_solar`` and the numbers were
Forecast.Solar's own. The message asserted something false.

A miss in the preferred-source branch has two very different meanings and the
code collapsed them:

* **not installed** — a stale preference, a removed integration. Worth a
  warning.
* **not loaded yet** — detection runs at coordinator construction and after a
  config reload, which can precede a slower forecast integration registering
  its entities. Worth nothing at all; ``should_retry_preference`` already
  exists to resolve it, and did.

Only the second happened here, and the retry fixed it seconds later — but the
warning was already written, nothing logged the recovery, and the diagnostics
buffer keeps the alarm while losing the resolution. So the reporter, who did
everything right, could not tell from the outside whether their install was
broken. That is precisely the failure #819 was raised to end: the picker got
fixed, and the message ABOUT the picker went on misleading.

These tests pin the distinction: silence while the retry is still in play, one
warning if it genuinely persists, and an explicit line when it recovers.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator import forecast_reader as fr
from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)

LOGGER_NAME = fr.__name__


def _reader(preferred="forecast_solar", *, found=False):
    """A reader whose preferred source is present (found) or not."""
    hass = MagicMock()
    hass.states.async_all.return_value = []
    hass.states.get.return_value = None
    r = ForecastReader(hass, custom_entities=None, preferred_source=preferred)
    r._locate_integration = MagicMock(
        return_value={"today": "sensor.x"} if found else {}
    )
    return r


def _warnings(caplog):
    return [rec for rec in caplog.records if rec.levelno >= logging.WARNING]


class TestTheTransientMissIsSilent:
    def test_first_miss_does_not_warn(self, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        r = _reader(found=False)
        r.detect_source()
        assert not _warnings(caplog), (
            "the first miss is the startup/reload race that "
            "should_retry_preference exists to resolve — warning about it "
            "reports a falsehood to the user (#819)"
        )

    def test_it_stays_silent_for_the_whole_grace_window(self, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        r = _reader(found=False)
        for _ in range(fr.PREFERRED_GRACE_CYCLES - 1):
            r.detect_source()
        assert not _warnings(caplog)

    def test_the_miss_is_still_visible_at_debug(self, caplog):
        """Silent to the user, not invisible to us."""
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        _reader(found=False).detect_source()
        assert any("forecast_solar" in r.getMessage() for r in caplog.records)


class TestAPersistentMissDoesWarn:
    def test_it_warns_once_the_grace_window_is_spent(self, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        r = _reader(found=False)
        for _ in range(fr.PREFERRED_GRACE_CYCLES):
            r.detect_source()
        warns = _warnings(caplog)
        assert len(warns) == 1, f"expected exactly one warning, got {len(warns)}"
        assert "forecast_solar" in warns[0].getMessage()

    def test_it_warns_only_once_however_long_it_persists(self, caplog):
        """A per-cycle warning on a 10 s loop is 8,640 lines a day, which
        trains people to ignore the log — the #762 lesson."""
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        r = _reader(found=False)
        for _ in range(fr.PREFERRED_GRACE_CYCLES * 4):
            r.detect_source()
        assert len(_warnings(caplog)) == 1

    def test_the_warning_does_not_state_installation_as_fact(self, caplog):
        """It cannot know the integration is absent — only that it never
        appeared. Say that instead."""
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        r = _reader(found=False)
        for _ in range(fr.PREFERRED_GRACE_CYCLES):
            r.detect_source()
        msg = _warnings(caplog)[0].getMessage()
        assert "is not installed" not in msg, (
            "the reporter's install HAD forecast.solar and was using it; "
            "claiming otherwise is what made them file (#819)"
        )


class TestRecoveryIsAnnounced:
    def test_finding_it_after_misses_logs_the_resolution(self, caplog):
        caplog.set_level(logging.INFO, logger=LOGGER_NAME)
        r = _reader(found=False)
        for _ in range(fr.PREFERRED_GRACE_CYCLES):
            r.detect_source()
        caplog.clear()
        r._locate_integration = MagicMock(return_value={"today": "sensor.x"})
        r.detect_source()
        assert any(
            r_.levelno == logging.INFO and "forecast_solar" in r_.getMessage()
            for r_ in caplog.records
        ), "diagnostics keep the alarm and lose the resolution unless we say so"

    def test_recovery_rearms_the_grace_window(self, caplog):
        """So a later, genuine disappearance is not silently swallowed by a
        warn-once flag set hours earlier."""
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        r = _reader(found=False)
        for _ in range(fr.PREFERRED_GRACE_CYCLES):
            r.detect_source()
        r._locate_integration = MagicMock(return_value={"today": "sensor.x"})
        r.detect_source()
        caplog.clear()
        r._locate_integration = MagicMock(return_value={})
        for _ in range(fr.PREFERRED_GRACE_CYCLES):
            r.detect_source()
        assert len(_warnings(caplog)) == 1


class TestHonouredIsUnchanged:
    """The visibility attributes #819 added must keep their meaning — the
    grace window changes when we SPEAK, never what is true."""

    def test_a_miss_is_still_not_honoured_during_grace(self):
        r = _reader(found=False)
        r.detect_source()
        assert r.honoured is False
        assert r.should_retry_preference is True

    def test_a_hit_is_honoured(self):
        r = _reader(found=True)
        r.detect_source()
        assert r.honoured is True
        assert r.should_retry_preference is False
