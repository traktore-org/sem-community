"""Tests for coordinator/forecast_tracker.py."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
    DailyForecastRecord,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def tracker():
    """Return a fresh ForecastTracker."""
    return ForecastTracker()


def _freeze_dt(year=2026, month=4, day=18, hour=12, minute=0):
    """Return a mock for dt_util.now."""
    dt = datetime(year, month, day, hour, minute, 0)
    mock = MagicMock()
    mock.strftime = dt.strftime
    mock.month = dt.month
    mock.year = dt.year
    mock.hour = dt.hour
    mock.minute = dt.minute
    # #416 sub#2/#3 — the EMA smoothing reads now().timestamp() and the
    # sun-hours fix reads now().date(); bind the real datetime's methods.
    mock.timestamp = dt.timestamp
    mock.date = dt.date
    return mock


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_update_records_deviation(mock_dt, tracker):
    """Test that update records forecast vs actual deviation."""
    mock_dt.now.return_value = _freeze_dt()

    tracker.update(forecast_today_kwh=20.0, actual_solar_kwh=18.0, weather_condition="sunny")

    assert tracker.deviation_today == pytest.approx(-2.0)
    assert tracker._today_forecast == 20.0
    assert tracker._today_actual == 18.0


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_correction_factor_adjusts(mock_dt, tracker):
    """Test that correction factor adjusts after accumulating history."""
    # Seed history with records where actual is consistently 80% of forecast
    for i in range(7):
        record = DailyForecastRecord(
            date=f"2026-04-{10+i:02d}",
            forecast_kwh=25.0,
            actual_kwh=20.0,
            weather="sunny",
            accuracy_pct=80.0,
            correction_factor=0.8,
        )
        tracker._history.append(record)

    mock_dt.now.return_value = _freeze_dt()
    tracker._weather_today = "sunny"
    tracker._update_correction_factor()

    # Factor should be around 0.8 (actual/forecast ratio)
    assert tracker.correction_factor < 1.0
    assert tracker.correction_factor >= 0.3  # clamped min


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_get_data_returns_accuracy(mock_dt, tracker):
    """Test get_data returns a dict with the kept keys.

    (#544) forecast_accuracy_today/_7d and forecast_deviation_kwh were
    removed as dead sensors — get_data no longer publishes them. The
    accuracy is still computed internally (``tracker.accuracy_today``);
    only the dead sensor surface is gone. correction_factor and
    history_days stay (read by the dampening/correction sensor attrs)."""
    mock_dt.now.return_value = _freeze_dt()
    tracker.update(forecast_today_kwh=30.0, actual_solar_kwh=27.0)

    data = tracker.get_data()
    assert "forecast_correction_factor" in data
    assert "forecast_weather_category" in data
    assert "forecast_history_days" in data

    # accuracy_today = 27/30 * 100 = 90% (computed, no longer published)
    assert tracker.accuracy_today == pytest.approx(90.0)


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_apply_correction(mock_dt, tracker):
    """Test applying correction factor to a forecast value."""
    mock_dt.now.return_value = _freeze_dt()

    # Default factor is 1.0
    assert tracker.apply_correction(20.0) == pytest.approx(20.0)

    # Manually set factor
    tracker._correction_factor = 0.85
    assert tracker.apply_correction(20.0) == pytest.approx(17.0)
    assert tracker.apply_correction(0.0) == pytest.approx(0.0)


def test_restore_state(tracker):
    """Test restore_state loads history and correction factor."""
    state = {
        "history": [
            {
                "date": "2026-04-10",
                "forecast": 25.0,
                "actual": 22.0,
                "weather": "sunny",
                "accuracy": 88.0,
                "factor": 0.88,
            },
            {
                "date": "2026-04-11",
                "forecast": 30.0,
                "actual": 28.0,
                "weather": "cloudy",
                "accuracy": 93.3,
                "factor": 0.933,
            },
        ],
        "correction_factor": 0.9,
    }

    tracker.restore_state(state)

    assert len(tracker._history) == 2
    assert tracker._correction_factor == pytest.approx(0.9)
    assert tracker._history[0].date == "2026-04-10"
    assert tracker._history[1].weather == "cloudy"


def test_restore_state_empty(tracker):
    """Test restoring empty/None state is safe."""
    tracker.restore_state(None)
    assert len(tracker._history) == 0
    assert tracker._correction_factor == 1.0

    tracker.restore_state({})
    assert len(tracker._history) == 0


def test_get_state_roundtrip(tracker):
    """Test get_state / restore_state round-trip."""
    # Add some history
    for i in range(5):
        tracker._history.append(DailyForecastRecord(
            date=f"2026-04-{10+i:02d}",
            forecast_kwh=20.0 + i,
            actual_kwh=18.0 + i,
            weather="sunny",
            accuracy_pct=90.0,
            correction_factor=0.9,
        ))
    tracker._correction_factor = 0.92

    state = tracker.get_state()
    new_tracker = ForecastTracker()
    new_tracker.restore_state(state)

    assert len(new_tracker._history) == 5
    assert new_tracker._correction_factor == pytest.approx(0.92)


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_weather_condition_tracking(mock_dt, tracker):
    """Test weather condition normalization and tracking."""
    mock_dt.now.return_value = _freeze_dt()

    tracker.update(forecast_today_kwh=25.0, actual_solar_kwh=23.0, weather_condition="partlycloudy")
    assert tracker.weather_category == "cloudy"

    tracker.update(forecast_today_kwh=25.0, actual_solar_kwh=23.0, weather_condition="sunny")
    assert tracker.weather_category == "sunny"

    tracker.update(forecast_today_kwh=25.0, actual_solar_kwh=23.0, weather_condition="pouring")
    assert tracker.weather_category == "rainy"

    tracker.update(forecast_today_kwh=25.0, actual_solar_kwh=23.0, weather_condition="something_else")
    assert tracker.weather_category == "unknown"


# ──────────────────────────────────────────────
# #416 follow-up — mid-day weather snapshot for rollover writes
# ──────────────────────────────────────────────


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_weather_snapshot_taken_at_confident_midday(mock_dt, tracker):
    """Inside ``_calculate_dampening_factor``'s ``blended_live`` branch
    the tracker must snapshot ``_weather_today`` so a later rollover
    write records the mid-day weather, not the post-sunset value."""
    mock_dt.now.return_value = _freeze_dt(hour=13)
    # Force the dampening calc into the confident branch by seeding
    # enough actual + forecast history. The branch requires a meaningful
    # ``expected_so_far`` AND a meaningful ``live_ratio`` — both come
    # from ``update()``.
    for _ in range(5):
        tracker.update(
            forecast_today_kwh=25.0, actual_solar_kwh=15.0,
            weather_condition="sunny",
        )
    # The blended_live branch should have populated ``_weather_snapshot``.
    assert tracker._weather_snapshot == "sunny", (
        f"weather_snapshot={tracker._weather_snapshot!r} — expected "
        "the mid-day cycle to snapshot the day's actual weather."
    )


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_save_record_prefers_snapshot_over_live_weather(mock_dt, tracker):
    """Rollover write must use the mid-day weather snapshot, not the
    post-sunset live ``_weather_today``. This is the bug that caused
    42 % of PROD records to have ``weather_category=unknown``."""
    # Day 1 mid-day: feed multiple confident cycles. Note the dampening
    # blend needs forecast > MIN_FORECAST_KWH and an accumulating
    # actual reading, so loop a few cycles.
    mock_dt.now.return_value = _freeze_dt(day=18, hour=13)
    for _ in range(5):
        tracker.update(
            forecast_today_kwh=30.0, actual_solar_kwh=18.0,
            weather_condition="sunny",
        )
    assert tracker._weather_snapshot == "sunny", (
        "snapshot precondition not met — check the confident-branch gate"
    )

    # Simulate day rollover: the next ``update()`` lands in the new
    # day with the weather entity now reporting the post-sunset state.
    mock_dt.now.return_value = _freeze_dt(day=19, hour=1)
    tracker.update(
        forecast_today_kwh=20.0, actual_solar_kwh=0.0,
        weather_condition="clear-night",  # the typical post-sunset bug input
    )

    # The rollover should have saved a record for day 18 (forecast=30,
    # actual=18). It MUST use the mid-day "sunny" snapshot, not the
    # post-sunset "clear-night" we just fed in.
    assert len(tracker._history) == 1
    saved = tracker._history[0]
    assert saved.date == "2026-04-18"
    assert saved.weather == "sunny", (
        f"record.weather={saved.weather!r} — the rollover wrote the "
        "post-sunset weather instead of the mid-day snapshot. "
        "Regression of #416 weather-write-time bug."
    )


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_snapshot_resets_on_day_rollover(mock_dt, tracker):
    """``_weather_snapshot`` is per-day, like ``_dampening_snapshot``.
    Must reset on rollover so today's record never picks up yesterday's
    snapshot if the early-morning cycles haven't yet entered the
    confident branch."""
    mock_dt.now.return_value = _freeze_dt(day=18, hour=13)
    for _ in range(5):
        tracker.update(forecast_today_kwh=30.0, actual_solar_kwh=18.0,
                       weather_condition="sunny")
    assert tracker._weather_snapshot == "sunny"

    # Roll over to the next day. First post-rollover update should have
    # cleared yesterday's snapshot.
    mock_dt.now.return_value = _freeze_dt(day=19, hour=1)
    tracker.update(forecast_today_kwh=25.0, actual_solar_kwh=0.0,
                   weather_condition="clear-night")
    assert tracker._weather_snapshot is None, (
        "snapshot survived rollover — record on day 20 would pick up "
        "day 18's weather if no confident cycle fires today."
    )


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_eager_snapshot_on_low_forecast_day(mock_dt, tracker):
    """v1.7.2 (2026-06-07): the eager-snapshot path captures weather
    during daylight even when the day never reaches ``blended_live``
    (rainy day with forecast < MIN_FORECAST_KWH). Without this gap,
    low-forecast days landed in ``weather_category=unknown``."""
    mock_dt.now.return_value = _freeze_dt(day=18, hour=13)
    # Single cycle, low-forecast — won't trip the confident gate.
    tracker.update(forecast_today_kwh=10.0, actual_solar_kwh=8.0,
                   weather_condition="sunny")
    # Eager capture must have fired — daylight + non-unknown weather.
    assert tracker._weather_snapshot == "sunny", (
        "eager-snapshot did not fire on low-forecast day at hour=13 — "
        "this is the gap that left rainy/overcast days in weather=unknown."
    )
    # Manually nudge today's forecast above the save gate so the
    # rollover writes (otherwise the < MIN_FORECAST_KWH guard skips).
    tracker._today_forecast = 12.0

    mock_dt.now.return_value = _freeze_dt(day=19, hour=1)
    tracker.update(forecast_today_kwh=11.0, actual_solar_kwh=0.0,
                   weather_condition="clear-night")

    assert len(tracker._history) == 1
    # Eager snapshot from yesterday's hour=13 cycle wins over the
    # post-midnight live ``clear-night``.
    assert tracker._history[0].weather == "sunny"


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_eager_snapshot_ignores_unknown_weather(mock_dt, tracker):
    """v1.7.2 (2026-06-07): the eager-snapshot path must skip when the
    weather entity itself reports ``unknown``/``unavailable``. Otherwise
    a broken weather entity would *force* every record to ``unknown``."""
    mock_dt.now.return_value = _freeze_dt(day=18, hour=13)
    tracker.update(forecast_today_kwh=15.0, actual_solar_kwh=2.0,
                   weather_condition="unknown")
    assert tracker._weather_snapshot is None, (
        "eager-snapshot wrote ``unknown`` instead of skipping — would "
        "lock the day's record to unknown even if a later cycle reports "
        "a real value."
    )
    # A later cycle with a real value should land the snapshot.
    tracker.update(forecast_today_kwh=15.0, actual_solar_kwh=4.0,
                   weather_condition="partlycloudy")
    assert tracker._weather_snapshot == "partlycloudy"


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_eager_snapshot_skips_pre_sunrise_and_post_sunset(mock_dt, tracker):
    """v1.7.2 (2026-06-07): the eager-snapshot path is daylight-gated.
    A pre-sunrise or post-sunset cycle must NOT overwrite a confident
    mid-day snapshot, because the weather entity is unreliable outside
    daylight (``clear-night`` on Met.no, etc)."""
    # First, mid-day capture lands a confident snapshot.
    mock_dt.now.return_value = _freeze_dt(day=18, hour=13)
    tracker.update(forecast_today_kwh=15.0, actual_solar_kwh=8.0,
                   weather_condition="sunny")
    assert tracker._weather_snapshot == "sunny"

    # Now simulate a post-sunset cycle on the same day. Weather entity
    # has flipped to ``clear-night`` — the eager path must NOT
    # overwrite our mid-day ``sunny``.
    mock_dt.now.return_value = _freeze_dt(day=18, hour=22)
    tracker.update(forecast_today_kwh=15.0, actual_solar_kwh=10.0,
                   weather_condition="clear-night")
    assert tracker._weather_snapshot == "sunny", (
        "post-sunset cycle overwrote the mid-day snapshot — daylight "
        "gate is broken or absent."
    )


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_416_save_record_falls_back_to_live_when_no_snapshot(mock_dt, tracker):
    """The fallback path still exists for the truly-degenerate case:
    HA was restarted post-sunset AND the weather entity has been
    ``unknown`` the entire daylight portion of the day. Then there is
    nothing better to write than the live ``_weather_today``."""
    # First cycle is pre-sunrise — eager gate rejects on hour.
    mock_dt.now.return_value = _freeze_dt(day=18, hour=5)
    tracker.update(forecast_today_kwh=10.0, actual_solar_kwh=0.0,
                   weather_condition="clear-night")
    tracker._today_forecast = 12.0
    assert tracker._weather_snapshot is None, (
        "eager gate let a pre-sunrise cycle land — daylight gate broken."
    )

    # Day rollover at hour=1 with live weather still unknown.
    mock_dt.now.return_value = _freeze_dt(day=19, hour=1)
    tracker.update(forecast_today_kwh=11.0, actual_solar_kwh=0.0,
                   weather_condition="clear-night")

    assert len(tracker._history) == 1
    # No snapshot ever fired → falls back to live ``_weather_today``
    # as it was at rollover. Best-effort.
    assert tracker._history[0].weather == "clear-night"


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_day_rollover_saves_record(mock_dt, tracker):
    """Test that day rollover saves yesterday's record to history."""
    # Day 1
    mock_dt.now.return_value = _freeze_dt(day=17)
    tracker.update(forecast_today_kwh=25.0, actual_solar_kwh=22.0, weather_condition="sunny")
    assert len(tracker._history) == 0

    # Day 2 — triggers save of day 1
    mock_dt.now.return_value = _freeze_dt(day=18)
    tracker.update(forecast_today_kwh=30.0, actual_solar_kwh=28.0, weather_condition="cloudy")
    assert len(tracker._history) == 1
    assert tracker._history[0].date == "2026-04-17"
    assert tracker._history[0].forecast_kwh == 25.0
    assert tracker._history[0].actual_kwh == 22.0


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_accuracy_today_low_forecast(mock_dt, tracker):
    """Test accuracy is 0 when forecast is below minimum."""
    mock_dt.now.return_value = _freeze_dt()
    tracker.update(forecast_today_kwh=0.3, actual_solar_kwh=0.2)
    assert tracker.accuracy_today == 0.0


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_accuracy_7d(mock_dt, tracker):
    """Test 7-day accuracy average."""
    for i in range(7):
        tracker._history.append(DailyForecastRecord(
            date=f"2026-04-{10+i:02d}",
            forecast_kwh=20.0,
            actual_kwh=18.0,
            weather="sunny",
            accuracy_pct=90.0,
            correction_factor=0.9,
        ))
    assert tracker.accuracy_7d == pytest.approx(90.0)


@patch("custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util")
def test_correction_factor_clamped(mock_dt, tracker):
    """Test correction factor is clamped between 0.3 and 2.0."""
    # Extreme overperformance records
    for i in range(7):
        tracker._history.append(DailyForecastRecord(
            date=f"2026-04-{10+i:02d}",
            forecast_kwh=10.0,
            actual_kwh=50.0,
            weather="sunny",
            accuracy_pct=500.0,
            correction_factor=5.0,
        ))

    mock_dt.now.return_value = _freeze_dt()
    tracker._weather_today = "sunny"
    tracker._update_correction_factor()

    assert tracker.correction_factor <= 2.0
    assert tracker.correction_factor >= 0.3
