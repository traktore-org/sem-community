"""Tests for real-time forecast dampening, outlier detection, and weather tracking.

Covers the dampening factor that blends historical correction with live
intraday performance to handle forecast misses in both directions.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
    DailyForecastRecord,
    MIN_FORECAST_KWH,
    CONFIDENCE_RAMP_HOURS,
    MAX_ACTUAL_RATIO,
)

DT_PATH = "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"


def _dt(year=2026, month=5, day=7, hour=12, minute=0):
    """Return a real datetime for dt_util.now mock."""
    return datetime(year, month, day, hour, minute, 0)


def _make_history(days, weather="sunny", forecast=30.0, actual=35.0):
    """Build a list of DailyForecastRecord entries."""
    records = []
    for i in range(days):
        ratio = actual / forecast if forecast > MIN_FORECAST_KWH else 1.0
        records.append(DailyForecastRecord(
            date=f"2026-05-{i + 1:02d}",
            forecast_kwh=forecast,
            actual_kwh=actual,
            weather=weather,
            accuracy_pct=round(actual / forecast * 100, 1) if forecast > 0 else 0,
            correction_factor=round(ratio, 3),
        ))
    return records


# ──────────────────────────────────────────────
# Dampening factor tests
# ──────────────────────────────────────────────

class TestDampeningFactor:
    """Test real-time dampening factor calculation."""

    @patch(DT_PATH)
    def test_rainy_surprise_dampens_heavily(self, mock_dt):
        """Rainy day with sunny history: forecast=31, actual@noon=0.12 → dampening near floor."""
        mock_dt.now.return_value = _dt(hour=12, minute=0)
        tracker = ForecastTracker()

        # 7 sunny days with actual > forecast → correction_factor > 1.0
        for r in _make_history(7, weather="sunny", forecast=30.0, actual=35.0):
            tracker._history.append(r)

        tracker.update(31.0, 0.12, "rainy")
        factor = tracker.dampening_factor

        # At noon (6h solar), sine-curve expected_fraction ≈ 0.389
        # normalized_ratio = (0.12/31) / 0.389 ≈ 0.01
        # With full confidence, dampening ≈ normalized_ratio, clamped to 0.5 (tightened bounds)
        assert factor == 0.5  # clamped floor (was 0.05, tightened in v1.5.8)

        dampened = tracker.apply_dampening(28.0)
        assert dampened == pytest.approx(14.0, abs=1.0)

    @patch(DT_PATH)
    def test_sunny_surprise_boosts(self, mock_dt):
        """Sunny day after rainy week: correction=0.35, actual tracking 180% → dampening > 1."""
        mock_dt.now.return_value = _dt(hour=12, minute=0)
        tracker = ForecastTracker()

        # 7 rainy days with actual << forecast → low correction factor
        for r in _make_history(7, weather="rainy", forecast=30.0, actual=10.0):
            tracker._history.append(r)

        # Today sunny: forecast=15, actual at noon = 9.0 kWh
        # Sine-curve expected_fraction at noon ≈ 0.389
        # live_ratio = 9.0/15 = 0.6, normalized = 0.6/0.389 ≈ 1.54
        tracker.update(15.0, 9.0, "sunny")
        factor = tracker.dampening_factor

        # correction_factor from history ≈ 0.333 (10/30)
        # At noon, confidence=1.0, so dampening ≈ normalized_ratio ≈ 1.54
        assert factor > 1.0
        assert factor < 2.0

    @patch(DT_PATH)
    def test_normal_accurate_day(self, mock_dt):
        """Forecast tracking ~100% → dampening ≈ 1.0."""
        mock_dt.now.return_value = _dt(hour=12, minute=0)
        tracker = ForecastTracker()

        for r in _make_history(7, weather="sunny", forecast=25.0, actual=25.0):
            tracker._history.append(r)

        # At noon: sine-curve expected_fraction ≈ 0.389
        # actual = 25 * 0.389 ≈ 9.7 → tracking perfectly
        tracker.update(25.0, 9.7, "sunny")
        factor = tracker.dampening_factor

        assert factor == pytest.approx(1.0, abs=0.1)

    @patch(DT_PATH)
    def test_early_morning_trusts_history(self, mock_dt):
        """At 6:30 AM, confidence is low → dampening ≈ correction_factor."""
        mock_dt.now.return_value = _dt(hour=6, minute=30)
        tracker = ForecastTracker()

        for r in _make_history(7, weather="sunny", forecast=25.0, actual=30.0):
            tracker._history.append(r)

        # At 6:30, solar_hours=0.5, confidence=0.5/3=0.167
        # Sine-curve expected_fraction ≈ 0.004, expected_so_far = 25*0.004 = 0.1 kWh
        # Below MIN_FORECAST_KWH threshold → falls back to correction_factor
        tracker.update(25.0, 0.1, "cloudy")
        factor = tracker.dampening_factor

        # correction_factor ≈ 1.2 (30/25)
        # At 6:30, expected_so_far < MIN_FORECAST_KWH → dampening = correction_factor
        correction = tracker.correction_factor
        assert factor == correction

    @patch(DT_PATH)
    def test_pre_sunrise_equals_correction(self, mock_dt):
        """Before 6 AM → dampening equals correction_factor exactly."""
        mock_dt.now.return_value = _dt(hour=5, minute=0)
        tracker = ForecastTracker()

        for r in _make_history(7, weather="sunny", forecast=25.0, actual=30.0):
            tracker._history.append(r)

        tracker.update(25.0, 0.0, "sunny")
        assert tracker.dampening_factor == tracker.correction_factor

    @patch(DT_PATH)
    def test_evening_equals_correction(self, mock_dt):
        """After 9 PM → dampening equals correction_factor exactly."""
        mock_dt.now.return_value = _dt(hour=21, minute=30)
        tracker = ForecastTracker()

        for r in _make_history(7, weather="sunny", forecast=25.0, actual=30.0):
            tracker._history.append(r)

        tracker.update(25.0, 22.0, "sunny")
        assert tracker.dampening_factor == tracker.correction_factor

    @patch(DT_PATH)
    def test_partial_clouds_adjusts_gradually(self, mock_dt):
        """Good morning → clouds at noon: dampening decreases as actual falls behind."""
        tracker = ForecastTracker()
        for r in _make_history(7, weather="sunny", forecast=30.0, actual=30.0):
            tracker._history.append(r)

        # At 10 AM: tracking well (actual matches sine-curve expected)
        # Sine fraction at 4h = (1-cos(4π/14))/2 ≈ 0.188, expected=5.65
        mock_dt.now.return_value = _dt(hour=10, minute=0)
        tracker.update(30.0, 5.65, "sunny")
        factor_10am = tracker.dampening_factor
        assert factor_10am == pytest.approx(1.0, abs=0.15)

        # At 2 PM: clouds rolled in, actual falling behind
        # Sine fraction at 8h ≈ 0.611, expected=18.3, but actual only 10
        mock_dt.now.return_value = _dt(hour=14, minute=0)
        tracker.update(30.0, 10.0, "cloudy")
        factor_2pm = tracker.dampening_factor
        # normalized_ratio = (10/30) / 0.611 ≈ 0.546
        assert factor_2pm < factor_10am
        assert factor_2pm < 0.7

    @patch(DT_PATH)
    def test_no_history_returns_one(self, mock_dt):
        """With no history, dampening factor should be 1.0."""
        mock_dt.now.return_value = _dt(hour=12, minute=0)
        tracker = ForecastTracker()
        tracker.update(25.0, 10.0, "sunny")

        # No history → correction_factor=1.0 → dampening blends with live
        factor = tracker.dampening_factor
        # confidence=1.0, correction=1.0, live varies
        # Should still be a reasonable value
        assert 0.05 <= factor <= 3.0

    @patch(DT_PATH)
    def test_dampening_clamped_upper(self, mock_dt):
        """Dampening cannot exceed 3.0."""
        mock_dt.now.return_value = _dt(hour=14, minute=0)
        tracker = ForecastTracker()

        # History with correction_factor=2.0 (actual far exceeds forecast)
        for r in _make_history(7, weather="sunny", forecast=10.0, actual=20.0):
            tracker._history.append(r)

        # Today also massively outperforming: forecast=5, actual at 2pm=8
        # expected_fraction=8/14=0.571, expected=2.86
        # live_ratio=8/5=1.6, normalized=1.6/0.571=2.8
        tracker.update(5.0, 8.0, "sunny")
        factor = tracker.dampening_factor
        assert factor <= 3.0


# ──────────────────────────────────────────────
# Outlier detection tests
# ──────────────────────────────────────────────

class TestOutlierDetection:
    """Test that impossible actual values are capped before saving to history."""

    @patch(DT_PATH)
    def test_outlier_capped(self, mock_dt):
        """Actual=200 with forecast=50 → capped at 100 (2x, tightened in v1.5.8)."""
        tracker = ForecastTracker()

        # Day 1: set up tracker state
        mock_dt.now.return_value = _dt(day=6, hour=20)
        tracker.update(50.0, 200.0, "sunny")

        # Day 2: trigger day rollover → saves day 1 record
        mock_dt.now.return_value = _dt(day=7, hour=8)
        tracker.update(30.0, 0.0, "sunny")

        assert len(tracker._history) == 1
        record = tracker._history[0]
        # Actual should be capped at 2x forecast = 100 (was 3x, tightened in v1.5.8)
        assert record.actual_kwh == pytest.approx(100.0, abs=0.1)
        assert record.correction_factor == pytest.approx(2.0, abs=0.01)

    @patch(DT_PATH)
    def test_normal_values_not_capped(self, mock_dt):
        """Normal actual=35 with forecast=30 → saved as-is."""
        tracker = ForecastTracker()

        mock_dt.now.return_value = _dt(day=6, hour=20)
        tracker.update(30.0, 35.0, "sunny")

        mock_dt.now.return_value = _dt(day=7, hour=8)
        tracker.update(25.0, 0.0, "sunny")

        assert len(tracker._history) == 1
        record = tracker._history[0]
        assert record.actual_kwh == pytest.approx(35.0, abs=0.1)


# ──────────────────────────────────────────────
# Weather detection tests
# ──────────────────────────────────────────────

class TestWeatherTracking:
    """Test weather-aware correction with proper weather data."""

    @patch(DT_PATH)
    def test_weather_stored_in_record(self, mock_dt):
        """Verify weather condition is stored in history records."""
        tracker = ForecastTracker()

        mock_dt.now.return_value = _dt(day=6, hour=20)
        tracker.update(30.0, 25.0, "rainy")

        mock_dt.now.return_value = _dt(day=7, hour=8)
        tracker.update(25.0, 0.0, "sunny")

        assert tracker._history[0].weather == "rainy"

    @patch(DT_PATH)
    def test_weather_aware_correction_activates(self, mock_dt):
        """With enough weather-specific records, correction uses weather match."""
        tracker = ForecastTracker()

        # 5 rainy days: actual = 30% of forecast
        for r in _make_history(5, weather="rainy", forecast=30.0, actual=9.0):
            tracker._history.append(r)
        # 5 sunny days: actual = 120% of forecast
        for r in _make_history(5, weather="sunny", forecast=30.0, actual=36.0):
            tracker._history.append(r)

        # Update with rainy weather → should use rainy-specific factor
        mock_dt.now.return_value = _dt(hour=12)
        tracker.update(30.0, 5.0, "rainy")

        # Rainy correction factor ≈ 0.3 (9/30) → clamped to 0.6, decayed to 0.7
        # Sunny ≈ 1.2 (36/30) → clamped to 1.2, decayed to 1.15
        # With rainy weather, correction uses rainy-specific factor (lower)
        correction = tracker.correction_factor
        assert correction < 0.85  # rainy factor dominates (clamped + decayed)

    @patch(DT_PATH)
    def test_get_data_includes_dampening(self, mock_dt):
        """Verify get_data() includes forecast_dampening_factor."""
        mock_dt.now.return_value = _dt(hour=12)
        tracker = ForecastTracker()
        tracker.update(25.0, 10.0, "sunny")

        data = tracker.get_data()
        assert "forecast_dampening_factor" in data
        assert isinstance(data["forecast_dampening_factor"], float)

    @patch(DT_PATH)
    def test_apply_dampening_method(self, mock_dt):
        """Test apply_dampening returns dampened value."""
        mock_dt.now.return_value = _dt(hour=12)
        tracker = ForecastTracker()

        for r in _make_history(7, weather="sunny", forecast=30.0, actual=30.0):
            tracker._history.append(r)

        tracker.update(30.0, 12.8, "sunny")  # tracking ~100%
        result = tracker.apply_dampening(15.0)

        # Should be close to 15.0 since tracking well
        assert 10.0 < result < 20.0
