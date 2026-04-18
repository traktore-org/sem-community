"""Tests for coordinator/forecast_tracker.py."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
    DailyForecastRecord,
    MIN_FORECAST_KWH,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def tracker():
    """Return a fresh ForecastTracker."""
    return ForecastTracker()


def _freeze_dt(year=2026, month=4, day=18, hour=12):
    """Return a mock for dt_util.now."""
    dt = datetime(year, month, day, hour, 0, 0)
    mock = MagicMock()
    mock.strftime = dt.strftime
    mock.month = dt.month
    mock.year = dt.year
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
    """Test get_data returns a dict with expected keys."""
    mock_dt.now.return_value = _freeze_dt()
    tracker.update(forecast_today_kwh=30.0, actual_solar_kwh=27.0)

    data = tracker.get_data()
    assert "forecast_accuracy_today" in data
    assert "forecast_accuracy_7d" in data
    assert "forecast_correction_factor" in data
    assert "forecast_deviation_kwh" in data
    assert "forecast_weather_category" in data
    assert "forecast_history_days" in data

    # accuracy_today = 27/30 * 100 = 90%
    assert data["forecast_accuracy_today"] == pytest.approx(90.0)


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
