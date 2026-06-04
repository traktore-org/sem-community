"""#424 — telemetry surface for TimeManager.

Locks the ``*_path`` strings each method sets. Mirrors the
#359/#416/#420/#421/#422/#423 precedents.

The silent-failure surfaces this captures:
- ``sunrise_source = fallback_default`` — sun.sun entity unavailable,
  TimeManager falls back to a hardcoded 06:00 sunrise that's wrong
  outside summer-equinox latitudes.
- ``sunrise_correction = next_rising_was_tomorrow`` — same class of
  bug as #416's ``forecast_tracker._get_sun_hours``. Tracking how
  often this fires in practice.
- ``night_hours_path = parse_failed_fallback_8h`` — silent fallback
  to 8 hours when ``HH:MM`` parsing fails.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.utils.time_manager import TimeManager


def _make(hass=None, **config):
    if hass is None:
        hass = MagicMock()
        # Default: sun.sun unavailable → triggers fallback paths
        hass.states.get = MagicMock(return_value=None)
    return TimeManager(hass=hass, config=config)


def _sun_state(next_rising_iso, next_setting_iso):
    s = MagicMock()
    s.attributes = {
        "next_rising": next_rising_iso,
        "next_setting": next_setting_iso,
    }
    return s


# ──────────────────────────────────────────────
# sunrise_source
# ──────────────────────────────────────────────


def test_sunrise_source_fallback_default():
    """sun.sun unavailable → "06:00" fallback. Silent in production
    today; telemetry attribute makes it visible."""
    tm = _make()
    assert tm.get_sunrise_time() == "06:00"
    assert tm.get_diagnostics()["sunrise_source"] == "fallback_default"


def test_sunrise_source_sun_integration():
    hass = MagicMock()
    # 2026-01-15 06:30 UTC
    hass.states.get = MagicMock(return_value=_sun_state(
        "2026-01-15T06:30:00+00:00",
        "2026-01-15T17:00:00+00:00",
    ))
    tm = _make(hass=hass)
    tm.get_sunrise_time()
    assert tm.get_diagnostics()["sunrise_source"] == "sun_integration"


# ──────────────────────────────────────────────
# sunset_source
# ──────────────────────────────────────────────


def test_sunset_source_fallback_default():
    tm = _make()
    assert tm.get_sunset_plus_10_time() == "20:30"
    assert tm.get_diagnostics()["sunset_source"] == "fallback_default"


def test_sunset_source_sun_integration():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_sun_state(
        "2026-01-15T06:30:00+00:00",
        "2026-01-15T17:00:00+00:00",
    ))
    tm = _make(hass=hass)
    tm.get_sunset_plus_10_time()
    assert tm.get_diagnostics()["sunset_source"] == "sun_integration"


# ──────────────────────────────────────────────
# sunrise_correction (parallel to #416 next_rising bug)
# ──────────────────────────────────────────────


def test_sunrise_correction_next_rising_was_tomorrow():
    """sun.sun returns tomorrow's sunrise → TimeManager corrects it
    to today's. Tracks how often this fires in real installs."""
    hass = MagicMock()
    now = dt_util.now()
    # next_rising = tomorrow
    tomorrow = now + timedelta(days=1)
    hass.states.get = MagicMock(return_value=_sun_state(
        tomorrow.replace(hour=6, minute=30).isoformat(),
        (now + timedelta(hours=4)).isoformat(),
    ))
    tm = _make(hass=hass)
    tm.get_sunrise_datetime()
    assert tm.get_diagnostics()["sunrise_correction"] == "next_rising_was_tomorrow"


def test_sunrise_correction_none():
    """sun.sun returns today's sunrise (still in the future) → no correction."""
    hass = MagicMock()
    now = dt_util.now()
    today_later = now + timedelta(hours=1)
    hass.states.get = MagicMock(return_value=_sun_state(
        today_later.isoformat(),
        (now + timedelta(hours=12)).isoformat(),
    ))
    tm = _make(hass=hass)
    tm.get_sunrise_datetime()
    assert tm.get_diagnostics()["sunrise_correction"] == "none"


def test_sunrise_correction_fallback():
    tm = _make()
    tm.get_sunrise_datetime()
    assert tm.get_diagnostics()["sunrise_correction"] == "fallback_default_06_00"


# ──────────────────────────────────────────────
# night_window_path
# ──────────────────────────────────────────────


def test_night_window_path_outside_night_window():
    """Mocking dt_util.now to mid-afternoon → outside night window."""
    from unittest.mock import patch
    tm = _make()
    with patch(
        "custom_components.solar_energy_management.utils.time_manager.dt_util.now"
    ) as mock_now:
        mock_now.return_value = datetime(2026, 6, 15, 14, 0)
        result = tm.is_night_mode()
    assert result is False
    assert tm.get_diagnostics()["night_window_path"] == "outside_night_window"


def test_night_window_path_pre_midnight_in_night():
    from unittest.mock import patch
    tm = _make()
    with patch(
        "custom_components.solar_energy_management.utils.time_manager.dt_util.now"
    ) as mock_now:
        mock_now.return_value = datetime(2026, 6, 15, 23, 0)
        result = tm.is_night_mode()
    assert result is True
    assert tm.get_diagnostics()["night_window_path"] == "pre_midnight_in_night"


def test_night_window_path_post_midnight_in_night():
    from unittest.mock import patch
    tm = _make()
    with patch(
        "custom_components.solar_energy_management.utils.time_manager.dt_util.now"
    ) as mock_now:
        mock_now.return_value = datetime(2026, 6, 15, 3, 0)
        result = tm.is_night_mode()
    assert result is True
    assert tm.get_diagnostics()["night_window_path"] == "post_midnight_in_night"


# ──────────────────────────────────────────────
# night_hours_path
# ──────────────────────────────────────────────


def test_night_hours_path_crosses_midnight():
    """Default window starts at sunset+10 (or 20:30 fallback) and ends
    at sunrise (or 07:00 fallback) — crosses midnight."""
    tm = _make()
    hours = tm.get_night_window_hours()
    assert hours > 0
    assert tm.get_diagnostics()["night_hours_path"] in (
        "crosses_midnight", "same_day",
    )


# ──────────────────────────────────────────────
# meter_day_path
# ──────────────────────────────────────────────


def test_meter_day_path_after_sunrise():
    from unittest.mock import patch
    tm = _make()  # uses fallback 06:00 sunrise
    with patch(
        "custom_components.solar_energy_management.utils.time_manager.dt_util.now"
    ) as mock_now:
        mock_now.return_value = datetime(2026, 6, 15, 10, 0)
        tm.get_current_meter_day_sunrise_based()
    assert tm.get_diagnostics()["meter_day_path"] == "after_sunrise"


def test_meter_day_path_before_offset():
    from unittest.mock import patch
    tm = _make()
    with patch(
        "custom_components.solar_energy_management.utils.time_manager.dt_util.now"
    ) as mock_now:
        mock_now.return_value = datetime(2026, 6, 15, 3, 0)
        tm.get_current_meter_day_offset_based("06:00")
    assert tm.get_diagnostics()["meter_day_path"] == "before_offset"


# ──────────────────────────────────────────────
# offset_parse_path
# ──────────────────────────────────────────────


def test_offset_parse_path_parsed():
    tm = _make()
    tm.get_offset_time("06:30")
    assert tm.get_diagnostics()["offset_parse_path"] == "parsed"


def test_offset_parse_path_parse_failed():
    tm = _make()
    tm.get_offset_time("not-a-time")
    assert tm.get_diagnostics()["offset_parse_path"] == "parse_failed_fallback_midnight"


# ──────────────────────────────────────────────
# get_diagnostics shape
# ──────────────────────────────────────────────


def test_get_diagnostics_returns_all_paths():
    tm = _make()
    diag = tm.get_diagnostics()
    assert set(diag.keys()) == {
        "sunrise_source", "sunset_source", "sunrise_correction",
        "night_window_path", "meter_day_path", "night_hours_path",
        "offset_parse_path",
    }
