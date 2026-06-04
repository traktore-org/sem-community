"""#416 — telemetry surface for forecast correction + dampening.

Locks the ``forecast_dampening_path`` and ``forecast_correction_path``
strings the sensor publishes as ``extra_state_attributes``. Mirrors the
#359 ``classifier_path`` pattern: a string per branch so users can
self-diagnose why the published factor is what it is, without us reading
their debug log.

Storage round-trip: pre-beta.22 records lack the dampening snapshot
fields. ``restore_state`` must tolerate their absence (None propagates
through rather than crashing or fabricating zeros).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
    DailyForecastRecord,
)

DT_PATH = "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"


def _dt(hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 5, 7, hour, minute, 0)


def _seed(tracker: ForecastTracker, n: int, weather: str = "sunny",
          forecast: float = 30.0, actual: float = 30.0) -> None:
    for i in range(n):
        ratio = actual / forecast
        tracker._history.append(DailyForecastRecord(
            date=f"2026-05-{i + 1:02d}",
            forecast_kwh=forecast,
            actual_kwh=actual,
            weather=weather,
            accuracy_pct=round(actual / forecast * 100, 1),
            correction_factor=round(ratio, 3),
        ))


# ──────────────────────────────────────────────
# Dampening path branches
# ──────────────────────────────────────────────


@patch(DT_PATH)
def test_dampening_path_outside_daylight_pre_sunrise(mock_dt):
    mock_dt.now.return_value = _dt(hour=4)  # before sunrise
    t = ForecastTracker()
    t.update(30.0, 0.0, "sunny")
    data = t.get_data()
    assert data["forecast_dampening_path"] == "outside_daylight"
    assert data["forecast_dampening_confidence"] == 0.0


@patch(DT_PATH)
def test_dampening_path_outside_daylight_post_sunset(mock_dt):
    mock_dt.now.return_value = _dt(hour=22)  # after sunset
    t = ForecastTracker()
    t.update(30.0, 25.0, "clear-night")
    data = t.get_data()
    assert data["forecast_dampening_path"] == "outside_daylight"


@patch(DT_PATH)
def test_dampening_path_no_forecast(mock_dt):
    mock_dt.now.return_value = _dt(hour=12)
    t = ForecastTracker()
    t.update(0.0, 0.0, "sunny")  # forecast below MIN_FORECAST_KWH
    data = t.get_data()
    assert data["forecast_dampening_path"] == "no_forecast"


@patch(DT_PATH)
def test_dampening_path_early_morning_floor(mock_dt):
    mock_dt.now.return_value = _dt(hour=7)  # 1 solar hour
    t = ForecastTracker()
    # Forecast big enough that the day's total > MIN_FORECAST_KWH but
    # expected_so_far at 1 solar hour is still below it.
    t.update(20.0, 0.1, "sunny")
    data = t.get_data()
    assert data["forecast_dampening_path"] == "early_morning_floor"


@patch(DT_PATH)
def test_dampening_path_blended_live(mock_dt):
    mock_dt.now.return_value = _dt(hour=14)  # mid-afternoon, high confidence
    t = ForecastTracker()
    _seed(t, 5, weather="sunny", forecast=30.0, actual=30.0)
    t.update(30.0, 18.0, "sunny")  # tracking on plan
    data = t.get_data()
    assert data["forecast_dampening_path"] == "blended_live"
    assert 0.0 < data["forecast_dampening_confidence"] <= 1.0
    assert data["forecast_dampening_live_ratio"] > 0.0


@patch(DT_PATH)
def test_dampening_path_clamped_high(mock_dt):
    mock_dt.now.return_value = _dt(hour=14)
    t = ForecastTracker()
    _seed(t, 5, weather="sunny", forecast=30.0, actual=30.0)
    # Massive under-forecast: actual 3× expected → blended > 1.5 → clamp
    t.update(10.0, 30.0, "sunny")
    data = t.get_data()
    assert "clamped_high" in data["forecast_dampening_path"]
    assert data["forecast_dampening_factor"] == 1.5  # ceiling


@patch(DT_PATH)
def test_dampening_path_clamped_low(mock_dt):
    mock_dt.now.return_value = _dt(hour=14)
    t = ForecastTracker()
    _seed(t, 5, weather="sunny", forecast=30.0, actual=30.0)
    # Massive over-forecast: actual nothing → live ratio ≈ 0, history 1.0
    # → blended pulled below the 0.5 floor at high confidence
    t.update(30.0, 0.5, "sunny")
    data = t.get_data()
    assert "clamped_low" in data["forecast_dampening_path"]
    assert data["forecast_dampening_factor"] == 0.5  # floor


# ──────────────────────────────────────────────
# Correction path branches
# ──────────────────────────────────────────────


@patch(DT_PATH)
def test_correction_path_no_history(mock_dt):
    mock_dt.now.return_value = _dt(hour=12)
    t = ForecastTracker()
    t.update(30.0, 25.0, "sunny")
    data = t.get_data()
    assert data["forecast_correction_path"] == "no_history"
    assert data["forecast_correction_bucket_size"] == 0


@patch(DT_PATH)
def test_correction_path_weather_month_bucket(mock_dt):
    mock_dt.now.return_value = _dt(hour=12, minute=0)  # 2026-05-07
    t = ForecastTracker()
    # Seed >= 3 May records with sunny weather
    _seed(t, 5, weather="sunny", forecast=30.0, actual=33.0)
    t.update(30.0, 25.0, "sunny")
    data = t.get_data()
    # Path starts with the bucket name; may carry a clamp suffix
    assert data["forecast_correction_path"].startswith("weather_month_bucket")
    assert data["forecast_correction_bucket_size"] >= 3


@patch(DT_PATH)
def test_correction_path_rolling_7d_fallback(mock_dt):
    """Without enough weather-matching or month-matching records, the
    chain falls all the way through to the rolling 7d fallback."""
    mock_dt.now.return_value = _dt(hour=12)
    t = ForecastTracker()
    # 2 mismatched-weather, mismatched-month records → can't hit any
    # of the bucket branches (need >= 3 matching per bucket).
    t._history.append(DailyForecastRecord(
        date="2026-01-01", forecast_kwh=30.0, actual_kwh=33.0,
        weather="rainy", accuracy_pct=110.0, correction_factor=1.1,
    ))
    t._history.append(DailyForecastRecord(
        date="2026-02-01", forecast_kwh=30.0, actual_kwh=27.0,
        weather="cloudy", accuracy_pct=90.0, correction_factor=0.9,
    ))
    t.update(30.0, 25.0, "sunny")
    data = t.get_data()
    assert data["forecast_correction_path"].startswith("rolling_7d_fallback")


# ──────────────────────────────────────────────
# History schema extension + restore tolerance
# ──────────────────────────────────────────────


@patch(DT_PATH)
def test_save_day_record_captures_new_telemetry_fields(mock_dt):
    mock_dt.now.return_value = _dt(hour=14)
    t = ForecastTracker()
    _seed(t, 5, weather="sunny", forecast=30.0, actual=30.0)
    t.update(30.0, 18.0, "sunny")

    # Force a day-rollover write
    mock_dt.now.return_value = _dt(hour=14).replace(day=8)
    t.update(30.0, 0.0, "sunny")

    written = t._history[-1]
    assert written.date == "2026-05-07"
    assert written.dampening_factor is not None
    assert written.confidence is not None
    assert written.live_ratio is not None


def test_get_state_includes_new_fields():
    t = ForecastTracker()
    t._history.append(DailyForecastRecord(
        date="2026-05-07", forecast_kwh=30.0, actual_kwh=30.0,
        weather="sunny", accuracy_pct=100.0, correction_factor=1.0,
        dampening_factor=1.05, confidence=0.8, live_ratio=1.05,
    ))
    state = t.get_state()
    rec = state["history"][0]
    assert rec["dampening_factor"] == 1.05
    assert rec["confidence"] == 0.8
    assert rec["live_ratio"] == 1.05


def test_restore_state_tolerates_pre_beta22_records():
    """Records written by pre-beta.22 code lack the dampening snapshot
    fields. Restore must accept them — they load as None, not as zero,
    so downstream consumers can distinguish "never recorded" from
    "recorded as zero"."""
    legacy_state = {
        "correction_factor": 1.2,
        "history": [
            {
                "date": "2026-04-11",
                "forecast": 25.0,
                "actual": 30.0,
                "weather": "cloudy",
                "accuracy": 120.0,
                "factor": 1.2,
                # no dampening_factor / confidence / live_ratio keys
            },
        ],
    }
    t = ForecastTracker()
    t.restore_state(legacy_state)
    assert len(t._history) == 1
    rec = t._history[0]
    assert rec.dampening_factor is None
    assert rec.confidence is None
    assert rec.live_ratio is None
    # Existing fields still round-trip correctly
    assert rec.forecast_kwh == 25.0
    assert rec.actual_kwh == 30.0


def test_restore_state_round_trip_new_records():
    """Records written by beta.22+ code carry the new fields and survive
    a get_state → restore_state round-trip."""
    t1 = ForecastTracker()
    t1._history.append(DailyForecastRecord(
        date="2026-05-07", forecast_kwh=30.0, actual_kwh=30.0,
        weather="sunny", accuracy_pct=100.0, correction_factor=1.0,
        dampening_factor=1.1, confidence=0.9, live_ratio=1.05,
    ))
    state = t1.get_state()

    t2 = ForecastTracker()
    t2.restore_state(state)
    rec = t2._history[0]
    assert rec.dampening_factor == 1.1
    assert rec.confidence == 0.9
    assert rec.live_ratio == 1.05
