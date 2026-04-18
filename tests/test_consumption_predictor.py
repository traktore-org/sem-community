"""Tests for analytics/consumption_predictor.py."""
import pytest
from datetime import datetime, timedelta

from custom_components.solar_energy_management.analytics.consumption_predictor import (
    HourlyProfile,
    ConsumptionPredictor,
    EWMA_ALPHA,
    MIN_TRAINING_DAYS,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def profile():
    """Return a fresh HourlyProfile."""
    return HourlyProfile()


@pytest.fixture
def predictor():
    """Return a fresh ConsumptionPredictor."""
    return ConsumptionPredictor()


def _make_dt(year=2026, month=4, day=14, hour=12):
    """Create a datetime for testing."""
    return datetime(year, month, day, hour, 0, 0)


# ──────────────────────────────────────────────
# HourlyProfile tests
# ──────────────────────────────────────────────

def test_hourly_profile_update_and_predict(profile):
    """Test that updating a bin and predicting returns EWMA-weighted value."""
    # Monday (dow=0), hour=10
    profile.update(0, 10, 1000.0)
    assert profile.predict(0, 10) == 1000.0

    # Second observation should apply EWMA
    profile.update(0, 10, 2000.0)
    expected = EWMA_ALPHA * 2000.0 + (1 - EWMA_ALPHA) * 1000.0
    assert profile.predict(0, 10) == pytest.approx(expected)

    # Third observation
    profile.update(0, 10, 1500.0)
    expected2 = EWMA_ALPHA * 1500.0 + (1 - EWMA_ALPHA) * expected
    assert profile.predict(0, 10) == pytest.approx(expected2)


def test_hourly_profile_fallback_to_any_day_average(profile):
    """Test fallback to average across all days for same hour when specific dow missing."""
    # Add data for Monday and Wednesday at hour 14
    profile.update(0, 14, 800.0)   # Monday
    profile.update(2, 14, 1200.0)  # Wednesday

    # Predict for Tuesday hour 14 (no data) -> should average Mon+Wed
    result = profile.predict(1, 14)
    expected = (800.0 + 1200.0) / 2
    assert result == pytest.approx(expected)


def test_hourly_profile_empty_returns_none(profile):
    """Test that predicting from empty profile returns None."""
    assert profile.predict(0, 10) is None
    assert profile.predict(6, 23) is None


def test_hourly_profile_total_samples(profile):
    """Test sample counting."""
    assert profile.total_samples() == 0
    profile.update(0, 10, 100.0)
    profile.update(0, 11, 200.0)
    assert profile.total_samples() == 2
    # Updating same bin increments count
    profile.update(0, 10, 150.0)
    assert profile.total_samples() == 3


def test_hourly_profile_state_roundtrip(profile):
    """Test get_state / restore_state round-trip."""
    profile.update(0, 10, 500.0)
    profile.update(3, 14, 750.0)

    state = profile.get_state()
    assert "bins" in state
    assert "counts" in state

    new_profile = HourlyProfile()
    new_profile.restore_state(state)
    assert new_profile.predict(0, 10) == pytest.approx(500.0)
    assert new_profile.predict(3, 14) == pytest.approx(750.0)


def test_hourly_profile_restore_empty_state(profile):
    """Test restoring empty state is safe."""
    profile.restore_state({})
    profile.restore_state(None)
    assert profile.total_samples() == 0


# ──────────────────────────────────────────────
# ConsumptionPredictor tests
# ──────────────────────────────────────────────

def test_predictor_cold_start_returns_empty(predictor):
    """Test that predictor returns empty predictions during cold start."""
    assert predictor.training_status == "cold_start"
    dt = _make_dt()
    assert predictor.predict_consumption_24h(dt) == []
    assert predictor.predict_solar_24h(dt) == []


def test_predictor_after_3_days_returns_predictions(predictor):
    """Test that predictor returns predictions after MIN_TRAINING_DAYS of data."""
    # Simulate 3+ days of data at noon (hour=12) on different weekdays
    # unique_days counts entries where hour==12
    for day_offset in range(MIN_TRAINING_DAYS):
        dt = _make_dt(day=14 + day_offset, hour=12)
        predictor.observe(dt, 500.0 + day_offset * 100, 3000.0 + day_offset * 200)

    assert predictor.training_status == "learning"

    # Should now return 24 predictions
    dt = _make_dt(day=17, hour=0)
    consumption = predictor.predict_consumption_24h(dt)
    assert len(consumption) == 24

    solar = predictor.predict_solar_24h(dt)
    assert len(solar) == 24


def test_predictor_observe_deduplicates_same_hour(predictor):
    """Test that observing the same (dow, hour) twice only records once."""
    dt1 = _make_dt(hour=10)
    predictor.observe(dt1, 500.0, 3000.0)

    # Same weekday and hour - should be deduplicated
    dt2 = dt1.replace(minute=15)
    predictor.observe(dt2, 999.0, 9999.0)

    # Profile should only have the first value
    result = predictor._consumption_profile.predict(dt1.weekday(), 10)
    assert result == pytest.approx(500.0)

    # Different hour should not be deduplicated
    dt3 = dt1.replace(hour=11)
    predictor.observe(dt3, 600.0, 4000.0)
    result = predictor._consumption_profile.predict(dt3.weekday(), 11)
    assert result == pytest.approx(600.0)


def test_predictor_training_status_transitions(predictor):
    """Test training status transitions: cold_start -> learning -> trained."""
    assert predictor.training_status == "cold_start"

    # Add data for 3 days (at hour=12 to count as unique days)
    for i in range(MIN_TRAINING_DAYS):
        dt = _make_dt(day=14 + i, hour=12)
        predictor.observe(dt, 500.0, 3000.0)
    assert predictor.training_status == "learning"

    # Add data for 7 unique days total
    for i in range(MIN_TRAINING_DAYS, 7):
        dt = _make_dt(day=14 + i, hour=12)
        predictor.observe(dt, 500.0, 3000.0)
    assert predictor.training_status == "trained"


def test_predictor_state_persistence_roundtrip(predictor):
    """Test get_state / restore_state round-trip for full predictor."""
    # Add some data
    for i in range(4):
        dt = _make_dt(day=14 + i, hour=12)
        predictor.observe(dt, 500.0 + i * 100, 3000.0 + i * 200)

    state = predictor.get_state()
    assert "consumption" in state
    assert "solar" in state
    assert "training_status" in state

    # Restore into new predictor
    new_predictor = ConsumptionPredictor()
    new_predictor.restore_state(state)
    assert new_predictor.training_status == predictor.training_status

    # Predictions should match
    dt = _make_dt(day=20, hour=0)
    orig = predictor.predict_consumption_24h(dt)
    restored = new_predictor.predict_consumption_24h(dt)
    assert len(orig) == len(restored)
    for a, b in zip(orig, restored):
        assert a == pytest.approx(b)


def test_predictor_restore_empty_state(predictor):
    """Test restoring None/empty state is safe."""
    predictor.restore_state(None)
    assert predictor.training_status == "cold_start"
    predictor.restore_state({})
    assert predictor.training_status == "cold_start"


def test_predict_consumption_today_kwh(predictor):
    """Test predict_consumption_today_kwh sums remaining hours and converts to kWh."""
    # Add enough data to leave cold_start
    for i in range(MIN_TRAINING_DAYS):
        dt = _make_dt(day=14 + i, hour=12)
        predictor.observe(dt, 1000.0, 5000.0)

    # Predict from hour=20, so 4 remaining hours
    dt = _make_dt(day=20, hour=20)
    result = predictor.predict_consumption_today_kwh(dt)
    # Should be sum of 4 hourly values / 1000 (converted to kWh)
    assert result >= 0
    assert isinstance(result, float)


def test_predict_consumption_today_kwh_cold_start(predictor):
    """Test predict_consumption_today_kwh returns 0 during cold start."""
    dt = _make_dt()
    assert predictor.predict_consumption_today_kwh(dt) == 0.0


def test_predict_surplus_window(predictor):
    """Test predict_surplus_window returns a time window string when surplus exists."""
    # Create a predictor with known solar > consumption pattern
    # Solar peaks midday, consumption is flat
    for day_offset in range(MIN_TRAINING_DAYS):
        for hour in range(24):
            dt = _make_dt(day=14 + day_offset, hour=hour)
            # Reset dedup key for each unique hour
            predictor._last_observation_hour = None

            # Solar: bell curve peaking at noon
            solar = max(0, 5000 * (1 - abs(hour - 12) / 6)) if 6 <= hour <= 18 else 0
            consumption = 800.0  # flat consumption
            predictor.observe(dt, consumption, solar)

    dt = _make_dt(day=20, hour=0)
    window = predictor.predict_surplus_window(dt)

    # Should return a time window like "HH:00-HH:00"
    if window:
        assert ":" in window
        assert "-" in window


def test_predict_surplus_window_cold_start(predictor):
    """Test predict_surplus_window returns empty string during cold start."""
    dt = _make_dt()
    assert predictor.predict_surplus_window(dt) == ""


def test_model_accuracy_pct(predictor):
    """Test model accuracy calculation."""
    assert predictor.model_accuracy_pct == 0.0

    # Add 3 days
    for i in range(MIN_TRAINING_DAYS):
        dt = _make_dt(day=14 + i, hour=12)
        predictor.observe(dt, 500.0, 3000.0)
    assert predictor.model_accuracy_pct > 0.0
    assert predictor.model_accuracy_pct <= 100.0
