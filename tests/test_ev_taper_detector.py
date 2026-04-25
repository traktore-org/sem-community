"""Tests for EV taper detection, virtual SOC, and battery health (#106).

Tests the EVTaperDetector module using synthetic power profiles
matching real-world data from HA-PROD (2026-04-24):
    6290W → 5580W → 4970W → 4340W → 3740W → 3120W → 2550W → 1960W → 0W
    Total taper ~17 minutes, steps ~600W each.
"""
import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
    BUFFER_SIZE,
    FULL_POWER_THRESHOLD,
    SESSION_PEAK_MIN,
)


# ════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════

DEFAULT_CONFIG = {
    "ev_battery_capacity_kwh": 40,
    "ev_target_soc": 80,
    "ev_min_soc_threshold": 20,
}


def _make_dt(minutes_offset: float = 0) -> datetime:
    """Create a datetime offset from a base time."""
    return datetime(2026, 4, 24, 13, 0, 0) + timedelta(minutes=minutes_offset)


def _feed_constant(detector, power_w, setpoint_a, count, start_min=0):
    """Feed constant power readings to the detector."""
    results = []
    for i in range(count):
        dt = _make_dt(start_min + i * 10 / 60)
        result = detector.update(power_w, setpoint_a, True, dt)
        results.append(result)
    return results


def _feed_taper_profile(detector, setpoint_a=16.0):
    """Feed the real PROD taper profile into the detector.

    Profile: 6290 → 5580 → 4970 → 4340 → 3740 → 3120 → 2550 → 1960 → 0
    Each step held for ~2 minutes (12 samples at 10s).
    """
    steps = [6290, 5580, 4970, 4340, 3740, 3120, 2550, 1960, 0]
    samples_per_step = 12  # ~2 minutes per step
    results = []
    sample_idx = 0

    for power in steps:
        for _ in range(samples_per_step):
            dt = _make_dt(sample_idx * 10 / 60)
            result = detector.update(power, setpoint_a, True, dt)
            results.append(result)
            sample_idx += 1

    return results


# ════════════════════════════════════════════
# Buffer and basic operation
# ════════════════════════════════════════════

class TestBufferManagement:
    def test_buffer_size_limit(self):
        """Buffer should not exceed BUFFER_SIZE."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_constant(det, 7000, 32, BUFFER_SIZE + 20)
        assert len(det._buffer) == BUFFER_SIZE

    def test_reset_clears_session(self):
        """reset_session should clear buffer and session state."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_constant(det, 7000, 32, 20)
        assert len(det._buffer) > 0
        assert det._session_peak_w > 0

        det.reset_session()
        assert len(det._buffer) == 0
        assert det._session_peak_w == 0.0
        assert det._declining_phase is False

    def test_session_peak_tracking(self):
        """Should track the highest sustained power in session."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_constant(det, 5000, 16, 5)
        _feed_constant(det, 9500, 32, 5, start_min=1)
        _feed_constant(det, 7000, 24, 5, start_min=2)
        assert det._session_peak_w == 9500


# ════════════════════════════════════════════
# Linear regression
# ════════════════════════════════════════════

class TestLinearRegression:
    def test_constant_power_zero_slope(self):
        """Constant power should give ~0 slope."""
        samples = [(i, 5000.0) for i in range(20)]
        slope = EVTaperDetector._linear_regression(samples)
        assert abs(slope) < 0.1

    def test_declining_power_negative_slope(self):
        """Declining power should give negative slope."""
        # 5000W at t=0, 3000W at t=10 → -200 W/min
        samples = [(i, 5000 - 200 * i) for i in range(11)]
        slope = EVTaperDetector._linear_regression(samples)
        assert slope == pytest.approx(-200, abs=1)

    def test_rising_power_positive_slope(self):
        """Rising power should give positive slope."""
        samples = [(i, 1000 + 100 * i) for i in range(10)]
        slope = EVTaperDetector._linear_regression(samples)
        assert slope == pytest.approx(100, abs=1)

    def test_too_few_samples(self):
        """Should return 0 for fewer than 2 samples."""
        assert EVTaperDetector._linear_regression([]) == 0.0
        assert EVTaperDetector._linear_regression([(0, 5000)]) == 0.0


# ════════════════════════════════════════════
# Setpoint discrimination (BMS vs SEM)
# ════════════════════════════════════════════

class TestSetpointDiscrimination:
    def test_sem_change_marks_samples(self):
        """Changing setpoint should mark samples as sem_changed."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        # Stable setpoint
        det.update(7000, 16.0, True, _make_dt(0))
        det.update(7000, 16.0, True, _make_dt(0.17))
        assert det._buffer[-1].sem_changed is False

        # SEM changes setpoint
        det.update(7000, 24.0, True, _make_dt(0.33))
        assert det._buffer[-1].sem_changed is True

        # Settling window (3 cycles)
        det.update(9000, 24.0, True, _make_dt(0.5))
        assert det._buffer[-1].sem_changed is True
        det.update(9000, 24.0, True, _make_dt(0.67))
        assert det._buffer[-1].sem_changed is True
        det.update(9000, 24.0, True, _make_dt(0.83))
        assert det._buffer[-1].sem_changed is True

        # After settling, should be clean
        det.update(9000, 24.0, True, _make_dt(1.0))
        assert det._buffer[-1].sem_changed is False

    def test_no_false_taper_during_sem_ramp(self):
        """SEM ramping down current should not trigger taper detection."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        # Feed declining power with changing setpoint (SEM reducing current)
        for i in range(30):
            power = 9000 - i * 200
            setpoint = 32 - i * 0.5
            dt = _make_dt(i * 10 / 60)
            det.update(power, setpoint, True, dt)

        result = det._analyze(9000 - 29 * 200)
        # All samples should be sem_changed due to constant setpoint changes
        assert result.trend == "unknown"


# ════════════════════════════════════════════
# Taper detection with real profile
# ════════════════════════════════════════════

class TestTaperDetection:
    def test_real_prod_taper_detected(self):
        """Should detect taper from real PROD power profile."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        results = _feed_taper_profile(det)

        # Find first "declining" result
        declining_results = [r for r in results if r.trend == "declining"]
        assert len(declining_results) > 0, "Should detect declining trend"

    def test_full_detected_at_zero(self):
        """Should detect full charge when power drops to 0 after declining."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        assert det._full_detected is True
        assert det._last_full_timestamp is not None

    def test_taper_ratio_decreases(self):
        """Taper ratio should decrease as power drops."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        results = _feed_taper_profile(det)

        # Get taper ratios for non-zero power points
        ratios = [r.taper_ratio_pct for r in results if r.taper_ratio_pct > 0]
        # First ratio should be higher than last non-zero ratio
        assert ratios[0] > ratios[-1]

    def test_stable_power_no_taper(self):
        """Constant power should show stable trend, not declining."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_constant(det, 7000, 16, 40)
        result = det._analyze(7000)
        assert result.trend in ("stable", "unknown")

    def test_minutes_to_full_estimate(self):
        """Should estimate reasonable time to completion."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        results = _feed_taper_profile(det)
        declining = [r for r in results if r.trend == "declining" and r.minutes_to_full > 0]
        if declining:
            # Should estimate between 1-60 minutes
            assert 0 < declining[-1].minutes_to_full <= 60


# ════════════════════════════════════════════
# Virtual SOC
# ════════════════════════════════════════════

class TestVirtualSOC:
    def test_soc_100_after_full(self):
        """SOC should be 100% immediately after full charge detected."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        assert det._full_detected is True
        assert det._estimated_soc == 100.0
        assert det._energy_since_full == 0.0

    def test_soc_decreases_with_energy(self):
        """SOC should decrease as energy is consumed."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)

        # Simulate 8 kWh consumed (20% of 40 kWh)
        det.update_energy(8.0)
        soc = det.get_virtual_soc()
        assert soc == pytest.approx(80.0, abs=0.5)

    def test_soc_clamped_at_zero(self):
        """SOC should not go below 0."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.update_energy(50.0)  # More than capacity
        soc = det.get_virtual_soc()
        assert soc == 0.0

    def test_vehicle_soc_takes_precedence(self):
        """Real vehicle SOC should override virtual estimate."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.update_energy(8.0)

        # Virtual would be 80%, but real is 65%
        soc = det.get_virtual_soc(vehicle_soc=65.0)
        assert soc == 65.0

    def test_virtual_soc_calibrates_from_real(self):
        """When real SOC arrives, virtual SOC should calibrate."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.update_energy(8.0)

        # Real SOC = 72% → internal state should sync
        det.get_virtual_soc(vehicle_soc=72.0)
        assert det._estimated_soc == 72.0
        # energy_since_full should be recalculated: (100-72)/100 * 40 = 11.2
        assert det._energy_since_full == pytest.approx(11.2, abs=0.1)

        # Now if car API goes offline, virtual continues from 72%
        det.update_energy(4.0)  # +4 kWh consumed
        soc = det.get_virtual_soc(vehicle_soc=None)
        # Should be ~62% (11.2 + 4 = 15.2 kWh → 100 - 15.2/40*100 = 62%)
        assert soc == pytest.approx(62.0, abs=0.5)

    def test_soc_resets_on_next_full(self):
        """SOC should reset to 100% when next full charge detected."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.update_energy(20.0)
        assert det.get_virtual_soc() == pytest.approx(50.0, abs=0.5)

        # New session — reset and do another taper
        det.reset_session()
        _feed_taper_profile(det)
        assert det._estimated_soc == 100.0
        assert det._energy_since_full == 0.0


# ════════════════════════════════════════════
# Night charge skip
# ════════════════════════════════════════════

class TestNightsUntilCharge:
    def test_skip_when_soc_above_target(self):
        """Should skip charge when SOC > target."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        # SOC = 100%, target = 80%
        nights, needed, reason = det.calculate_nights_until_charge(8.0)
        assert needed is False
        assert nights > 0
        assert "above target" in reason

    def test_charge_needed_when_low(self):
        """Should recommend charge when SOC is low."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.update_energy(35.0)  # SOC ~12.5%
        det.get_virtual_soc()

        nights, needed, reason = det.calculate_nights_until_charge(8.0)
        assert needed is True
        assert "recommended" in reason

    def test_multiple_nights_range(self):
        """With high SOC and moderate daily use, should have multi-night range."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.update_energy(8.0)  # SOC ~80%
        det.get_virtual_soc()

        # Daily consumption = 8 kWh = 20% of 40 kWh
        nights, needed, reason = det.calculate_nights_until_charge(8.0)
        assert needed is False
        assert nights >= 2


# ════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════

class TestPersistence:
    def test_state_roundtrip(self):
        """get_state/restore_state should preserve key data."""
        det1 = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det1)
        det1.update_energy(8.0)
        det1.get_virtual_soc()

        state = det1.get_state()

        det2 = EVTaperDetector(DEFAULT_CONFIG)
        det2.restore_state(state)

        assert det2._last_full_timestamp == det1._last_full_timestamp
        assert det2._energy_since_full == pytest.approx(det1._energy_since_full, abs=0.01)
        assert det2._estimated_soc == pytest.approx(det1._estimated_soc, abs=0.1)

    def test_restore_empty_state(self):
        """Restoring empty state should not crash."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        det.restore_state({})
        assert det._last_full_timestamp is None
        assert det._energy_since_full == 0.0


# ════════════════════════════════════════════
# Battery health
# ════════════════════════════════════════════

class TestBatteryHealth:
    def test_health_needs_minimum_samples(self):
        """Should not report health with fewer than 3 full-cycle charges."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.on_session_end(38.0)  # One full cycle
        assert det._battery_health_pct == 0.0  # Not enough samples

    def test_health_after_multiple_cycles(self):
        """Should calculate health after 3+ full-cycle charges."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        for i in range(4):
            _feed_taper_profile(det)
            det.on_session_end(38.0)  # 38/40 = 95% health
            det.reset_session()

        assert det._battery_health_pct == pytest.approx(95.0, abs=1.0)

    def test_health_samples_bounded(self):
        """Health samples should be bounded to prevent unbounded growth."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        for i in range(25):
            _feed_taper_profile(det)
            det.on_session_end(38.0)
            det.reset_session()

        assert len(det._battery_health_samples) <= 20

    def test_health_from_partial_charge(self):
        """Should estimate health from partial charge with real SOC."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        for i in range(4):
            # Simulate session: 40% → 80% with 15 kWh
            # capacity_estimate = 15 / (0.40) = 37.5 kWh → 37.5/40 = 93.75%
            _feed_constant(det, 7000, 16, 10)
            det._session_peak_w = 7000
            det._session_start_soc = 40.0
            det.on_session_end(15.0, end_soc=80.0)
            det.reset_session()

        assert det._battery_health_pct == pytest.approx(93.75, abs=1.0)

    def test_partial_charge_needs_min_soc_delta(self):
        """Should reject partial charges with tiny SOC delta."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_constant(det, 7000, 16, 10)
        det._session_peak_w = 7000
        det._session_start_soc = 78.0
        det.on_session_end(2.0, end_soc=80.0)  # Only 2% delta
        assert len(det._battery_health_samples) == 0  # Rejected


# ════════════════════════════════════════════
# EV consumption predictor extension
# ════════════════════════════════════════════

class TestEVConsumptionPredictor:
    def test_ev_profile_observe_and_predict(self):
        """Should learn and predict EV daily consumption per weekday."""
        from custom_components.solar_energy_management.analytics.consumption_predictor import (
            ConsumptionPredictor,
        )
        pred = ConsumptionPredictor()

        # Feed 3 Mondays with 8 kWh each
        for week in range(3):
            monday = datetime(2026, 4, 6 + week * 7, 23, 0)  # Monday
            pred.observe_ev(monday, 8.0)

        # Predict next Monday
        sunday = datetime(2026, 4, 26, 20, 0)  # Sunday
        predicted = pred.predict_ev_consumption_tomorrow(sunday)
        assert predicted == pytest.approx(8.0, abs=1.0)

    def test_ev_profile_persistence(self):
        """EV profile should survive get_state/restore_state."""
        from custom_components.solar_energy_management.analytics.consumption_predictor import (
            ConsumptionPredictor,
        )
        pred1 = ConsumptionPredictor()
        pred1.observe_ev(datetime(2026, 4, 6, 23, 0), 8.0)  # Monday

        state = pred1.get_state()
        assert "ev" in state

        pred2 = ConsumptionPredictor()
        pred2.restore_state(state)

        # Should preserve the Monday observation
        sunday = datetime(2026, 4, 12, 20, 0)
        assert pred2.predict_ev_consumption_tomorrow(sunday) > 0

    def test_ev_no_data_returns_zero(self):
        """Should return 0 when no EV data observed."""
        from custom_components.solar_energy_management.analytics.consumption_predictor import (
            ConsumptionPredictor,
        )
        pred = ConsumptionPredictor()
        result = pred.predict_ev_consumption_tomorrow(datetime(2026, 4, 24, 20, 0))
        assert result == 0.0
