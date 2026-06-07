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

        # Initialize with stable setpoint (first few samples settle from 0→16)
        for i in range(5):
            det.update(7000, 16.0, True, _make_dt(i * 0.17))

        # After settling, stable setpoint should be clean
        det.update(7000, 16.0, True, _make_dt(1.0))
        assert det._buffer[-1].sem_changed is False

        # SEM changes setpoint
        det.update(7000, 24.0, True, _make_dt(1.17))
        assert det._buffer[-1].sem_changed is True

        # Settling window (3 cycles)
        det.update(9000, 24.0, True, _make_dt(1.33))
        assert det._buffer[-1].sem_changed is True
        det.update(9000, 24.0, True, _make_dt(1.5))
        assert det._buffer[-1].sem_changed is True
        det.update(9000, 24.0, True, _make_dt(1.67))
        assert det._buffer[-1].sem_changed is True

        # After settling, should be clean
        det.update(9000, 24.0, True, _make_dt(1.83))
        assert det._buffer[-1].sem_changed is False

    def test_no_false_taper_during_sem_ramp(self):
        """SEM ramping down current should not trigger taper detection."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        # Feed declining power with large setpoint changes each cycle
        # (SEM reducing current by 2A each step — clearly SEM-initiated)
        for i in range(30):
            power = 9000 - i * 200
            setpoint = 32 - i * 2  # Large steps, always > 0.5A threshold
            dt = _make_dt(i * 10 / 60)
            result = det.update(power, setpoint, True, dt)

        # All samples should be sem_changed due to constant setpoint changes
        # so trend should be unknown (not enough BMS-only samples)
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
        det.reset_session()  # Clear full_detected for energy tracking
        det.update_energy(8.0)
        soc = det.get_virtual_soc()
        assert soc == pytest.approx(80.0, abs=0.5)

    def test_soc_clamped_at_zero(self):
        """SOC should not go below 0."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.reset_session()  # Clear full_detected for energy tracking
        det.update_energy(50.0)  # More than capacity
        soc = det.get_virtual_soc()
        assert soc == 0.0

    def test_vehicle_soc_takes_precedence(self):
        """Real vehicle SOC should override virtual estimate."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.reset_session()  # Clear full_detected for energy tracking
        det.update_energy(8.0)

        # Virtual would be 80%, but real is 65%
        soc = det.get_virtual_soc(vehicle_soc=65.0)
        assert soc == 65.0

    def test_virtual_soc_calibrates_from_real(self):
        """When real SOC arrives, virtual SOC should calibrate."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)
        det.reset_session()  # Clear full_detected for energy tracking
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
        det.reset_session()  # Clear full_detected for energy tracking
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
# Session-based SOC anchoring
# ════════════════════════════════════════════

class TestSessionAnchor:
    def test_first_session_bootstraps_soc(self):
        """First charge session should anchor SOC even without taper."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        assert det._soc_anchored is False

        # Simulate a night charge: 9.5 kWh delivered, no taper
        _feed_constant(det, 7000, 16, 10)  # Need peak for session validation
        det.on_session_end(9.5)

        assert det._soc_anchored is True
        # target=80%, added 9.5*0.92/40*100 ≈ 21.85% → pre=58.15%, post≈80%
        assert det._estimated_soc == pytest.approx(80.0, abs=2.0)

    def test_partial_charge_increases_soc(self):
        """Charging should increase SOC by delivered energy."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)  # Anchor at 100%

        # Decay 3 days → ~40%
        det.reset_session()  # Clear full_detected so partial charge logic runs
        for _ in range(3):
            det.apply_daily_decay(8.0, 10.0)
        assert det._estimated_soc == pytest.approx(40.0, abs=1.0)

        # Night charge delivers 9.5 kWh → +21.85% (with 92% efficiency)
        _feed_constant(det, 7000, 16, 10)
        det.on_session_end(9.5)
        assert det._estimated_soc == pytest.approx(61.8, abs=2.0)

    # (test_soc_anchored_enables_skip_logic) removed in #440 — skip-decision wiring is gone.


    def test_taper_anchor_overrides_session(self):
        """Taper detection (gold anchor) should override session estimate."""
        det = EVTaperDetector(DEFAULT_CONFIG)

        # Bootstrap from session → ~80%
        _feed_constant(det, 7000, 16, 10)
        det.on_session_end(9.5)
        soc_after_session = det._estimated_soc

        # Full taper → resets to 100%
        det.reset_session()
        _feed_taper_profile(det)
        assert det._estimated_soc == 100.0
        assert det._energy_since_full == 0.0

    def test_winter_scenario_no_taper(self):
        """Winter: charge nightly, never full, should still work.

        At 0°C: decay = 8 × 1.48 = 11.84 kWh/day
        Night charge: 9.5 × 0.92 = 8.74 kWh net to battery
        Net daily loss: 11.84 - 8.74 = 3.1 kWh → SOC drifts down
        This is realistic — winter charges don't fully compensate,
        so skip safety net (3 nights max) kicks in for larger charges.
        """
        config = {
            "ev_battery_capacity_kwh": 40,
            "ev_target_soc": 80,
            "ev_min_soc_threshold": 20,
            "ev_charger_efficiency": 0.92,
        }
        det = EVTaperDetector(config)

        # Day 1 evening: first charge session → bootstrap
        _feed_constant(det, 7000, 16, 10)
        det.on_session_end(9.5)
        assert det._soc_anchored is True

        for day in range(7):
            # Morning: drive to work
            det.reset_session()
            temp_factor = EVTaperDetector.temperature_correction_factor(0)  # Winter
            det.apply_daily_decay(8.0, 10.0, temp_factor)

            # Evening: night charge
            _feed_constant(det, 7000, 16, 10)
            det.on_session_end(9.5)

        # SOC should not be negative — clamped at 0
        assert det._estimated_soc >= 0
        # System should be anchored and functional
        assert det._soc_anchored is True

    def test_soc_anchor_persists(self):
        """Anchor state should survive restart."""
        det1 = EVTaperDetector(DEFAULT_CONFIG)
        _feed_constant(det1, 7000, 16, 10)
        det1.on_session_end(9.5)
        assert det1._soc_anchored is True

        state = det1.get_state()
        det2 = EVTaperDetector(DEFAULT_CONFIG)
        det2.restore_state(state)
        assert det2._soc_anchored is True


# (TestNightsUntilCharge) removed in #440 — skip-decision wiring is gone.

# ════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════

class TestPersistence:
    def test_state_roundtrip(self):
        """get_state/restore_state should preserve key data."""
        det1 = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det1)
        det1.reset_session()  # Clear full_detected for energy tracking
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


# ════════════════════════════════════════════
# Temperature correction
# ════════════════════════════════════════════

class TestTemperatureCorrection:
    def test_optimal_range(self):
        """10-28°C should return factor 1.0."""
        assert EVTaperDetector.temperature_correction_factor(10) == 1.0
        assert EVTaperDetector.temperature_correction_factor(20) == 1.0
        assert EVTaperDetector.temperature_correction_factor(28) == 1.0

    def test_winter_cold(self):
        """-5°C should give ~1.72 (+72% consumption)."""
        factor = EVTaperDetector.temperature_correction_factor(-5)
        assert factor == pytest.approx(1.72, abs=0.01)

    def test_freezing(self):
        """0°C should give ~1.48."""
        factor = EVTaperDetector.temperature_correction_factor(0)
        assert factor == pytest.approx(1.48, abs=0.01)

    def test_summer_hot(self):
        """35°C should give ~1.32."""
        factor = EVTaperDetector.temperature_correction_factor(35)
        assert factor == pytest.approx(1.32, abs=0.02)

    def test_mild_summer(self):
        """30°C should give ~1.09."""
        factor = EVTaperDetector.temperature_correction_factor(30)
        assert factor == pytest.approx(1.09, abs=0.01)


# ════════════════════════════════════════════
# SOC daily decay
# ════════════════════════════════════════════

class TestSOCDecay:
    def test_soc_decays_daily_when_unplugged(self):
        """SOC should drop by predicted daily amount."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)  # SOC = 100%

        det.apply_daily_decay(predicted_daily_kwh=8.0, fallback_kwh=10.0)
        # 8 kWh on 40 kWh battery = 20% drop
        assert det._estimated_soc == pytest.approx(80.0, abs=0.5)

    def test_decay_uses_fallback_when_no_prediction(self):
        """Should use fallback when predictor returns 0."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)

        det.apply_daily_decay(predicted_daily_kwh=0.0, fallback_kwh=10.0)
        # 10 kWh fallback = 25% drop
        assert det._estimated_soc == pytest.approx(75.0, abs=0.5)

    def test_decay_with_temperature_correction(self):
        """Winter temperature should increase decay."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)

        # 8 kWh × 1.48 (0°C) = 11.84 kWh → 29.6% drop
        det.apply_daily_decay(
            predicted_daily_kwh=8.0, fallback_kwh=10.0,
            temp_correction=EVTaperDetector.temperature_correction_factor(0),
        )
        assert det._estimated_soc == pytest.approx(70.4, abs=0.5)

    def test_decay_accumulates_over_days(self):
        """Multiple days of decay should accumulate."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)  # SOC = 100%

        for day in range(3):
            det.apply_daily_decay(8.0, 10.0)  # -20% each day

        # 100% - 3×20% = 40%
        assert det._estimated_soc == pytest.approx(40.0, abs=0.5)

    def test_decay_clamped_at_zero(self):
        """SOC should not go below 0%."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)

        for day in range(10):  # Way more than enough to drain
            det.apply_daily_decay(8.0, 10.0)

        assert det._estimated_soc == 0.0

    def test_calibration_overrides_decay(self):
        """Real vehicle SOC should override decayed estimate."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        _feed_taper_profile(det)

        # Decay 3 days → virtual SOC = 40%
        for _ in range(3):
            det.apply_daily_decay(8.0, 10.0)
        assert det._estimated_soc == pytest.approx(40.0, abs=0.5)

        # Car API says 65% → calibrate
        soc = det.get_virtual_soc(vehicle_soc=65.0)
        assert soc == 65.0
        assert det._estimated_soc == 65.0


# ════════════════════════════════════════════
# Consecutive skip safety net
# ════════════════════════════════════════════

# (TestConsecutiveSkips) removed in #440 — skip-decision wiring is gone.

# ════════════════════════════════════════════
# 10-day integration scenarios
# ════════════════════════════════════════════

# (TestMultiDayScenarios) removed in #440 — skip-decision wiring is gone.

# ════════════════════════════════════════════
# Night charge skip scenarios
# ════════════════════════════════════════════

# (TestNightChargeSkip) removed in #440 — skip-decision wiring is gone.

# ════════════════════════════════════════════
# History seeding tests
# ════════════════════════════════════════════

def _make_mock_state(entity_id, value, last_changed):
    """Create a mock state object for recorder history."""
    s = MagicMock()
    s.state = str(value)
    s.entity_id = entity_id
    s.last_changed = last_changed
    return s


def _generate_charge_session_history(
    entity_id,
    start,
    peak_kw=10.0,
    duration_min=30,
    taper=False,
):
    """Generate a synthetic charge session as recorder history states."""
    states = []
    # Ramp up
    for i in range(4):
        t = start + timedelta(seconds=i * 30)
        power = peak_kw * (i + 1) / 4
        states.append(_make_mock_state(entity_id, round(power, 1), t))

    # Steady state
    steady_samples = max(1, (duration_min - 4) * 2 // (2 if taper else 1))
    for i in range(steady_samples):
        t = start + timedelta(minutes=2, seconds=i * 30)
        states.append(_make_mock_state(entity_id, round(peak_kw, 1), t))

    if taper:
        taper_start = start + timedelta(minutes=duration_min // 2)
        for i in range(8):
            t = taper_start + timedelta(minutes=i * 2)
            power = peak_kw * (8 - i) / 8
            states.append(_make_mock_state(entity_id, round(power, 1), t))
        states.append(_make_mock_state(entity_id, 0.0, taper_start + timedelta(minutes=16)))
    else:
        states.append(_make_mock_state(entity_id, 0.0, start + timedelta(minutes=duration_min)))

    # Idle after
    for i in range(3):
        states.append(_make_mock_state(entity_id, 0.0, start + timedelta(minutes=duration_min + 5 + i * 30)))
    return states


def _patch_recorder(entity_id, history_states):
    """Return context managers to patch recorder for history seeding tests."""

    async def mock_add_executor_job(func, *args):
        return func(*args)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = mock_add_executor_job

    # Patch at the source modules since ev_taper_detector uses local imports
    return (
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "homeassistant.components.recorder.history.state_changes_during_period",
            return_value={entity_id: history_states},
        ),
    )


@pytest.mark.asyncio
async def test_history_seed_detects_sessions():
    """Test that history seeding detects charge sessions from power data."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    eid = "sensor.keba_p30_charging_power"
    base = datetime(2026, 4, 25, 14, 0, 0)
    states = (
        _generate_charge_session_history(eid, base, peak_kw=9.5, duration_min=30)
        + _generate_charge_session_history(eid, base + timedelta(days=1, hours=2), peak_kw=8.0, duration_min=20)
    )

    p1, p2 = _patch_recorder(eid, states)
    with p1, p2:
        result = await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert result is not None
    assert result["session_count"] == 2


@pytest.mark.asyncio
async def test_history_seed_detects_full_charge():
    """Test that taper-to-zero pattern is detected as full charge."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    eid = "sensor.keba_p30_charging_power"
    base = datetime(2026, 4, 25, 14, 0, 0)
    states = (
        _generate_charge_session_history(eid, base, peak_kw=10.0, duration_min=40, taper=True)
        + _generate_charge_session_history(eid, base + timedelta(days=1), peak_kw=8.0, duration_min=20)
    )

    p1, p2 = _patch_recorder(eid, states)
    with p1, p2:
        result = await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert result is not None
    assert result["improved"] is True
    assert det._soc_anchored is True
    assert det._last_full_timestamp is not None
    assert det._estimated_soc < 100.0
    assert det._estimated_soc > 0.0


@pytest.mark.asyncio
async def test_history_seed_weekday_totals():
    """Test weekday consumption totals are computed from sessions."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    eid = "sensor.keba_p30_charging_power"
    mon = datetime(2026, 4, 27, 14, 0, 0)
    tue = datetime(2026, 4, 28, 14, 0, 0)
    wed = datetime(2026, 4, 29, 14, 0, 0)
    states = (
        _generate_charge_session_history(eid, mon, peak_kw=9.0, duration_min=25)
        + _generate_charge_session_history(eid, tue, peak_kw=10.0, duration_min=30)
        + _generate_charge_session_history(eid, wed, peak_kw=8.0, duration_min=20)
    )

    p1, p2 = _patch_recorder(eid, states)
    with p1, p2:
        result = await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert result is not None
    wt = result["weekday_totals"]
    assert 0 in wt  # Monday
    assert 1 in wt  # Tuesday
    assert 2 in wt  # Wednesday
    assert all(v > 0 for v in wt.values())


@pytest.mark.asyncio
async def test_history_seed_no_overwrite_newer():
    """Test that a more recent existing last_full_charge is preserved."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    det._last_full_timestamp = "2026-04-28T18:00:00+00:00"
    det._energy_since_full = 5.0
    det._estimated_soc = 87.5
    det._soc_anchored = True

    eid = "sensor.keba_p30_charging_power"
    base = datetime(2026, 4, 25, 14, 0, 0)
    states = _generate_charge_session_history(eid, base, peak_kw=10.0, duration_min=40, taper=True)

    p1, p2 = _patch_recorder(eid, states)
    with p1, p2:
        await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert det._last_full_timestamp == "2026-04-28T18:00:00+00:00"
    assert det._energy_since_full == 5.0


@pytest.mark.asyncio
async def test_history_seed_empty_history():
    """Test graceful handling of empty recorder data."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    eid = "sensor.keba_p30_charging_power"

    p1, p2 = _patch_recorder(eid, [])
    with p1, p2:
        result = await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert result is None
    assert det._soc_anchored is False


@pytest.mark.asyncio
async def test_history_seed_recorder_unavailable():
    """Test graceful handling when recorder raises."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    eid = "sensor.keba_p30_charging_power"

    with patch(
        "homeassistant.components.recorder.get_instance",
        side_effect=Exception("Recorder not ready"),
    ):
        result = await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert result is None


@pytest.mark.asyncio
async def test_history_seed_no_entity():
    """Test that None entity returns None immediately."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    result = await det.async_seed_from_history(MagicMock(), None, days=7)
    assert result is None


@pytest.mark.asyncio
async def test_history_seed_kw_values():
    """Test that kW power values produce reasonable session energy."""
    det = EVTaperDetector(DEFAULT_CONFIG)
    eid = "sensor.keba_p30_charging_power"
    base = datetime(2026, 4, 27, 14, 0, 0)
    # 10 kW for 20 minutes
    states = []
    for i in range(40):
        states.append(_make_mock_state(eid, 10.0, base + timedelta(seconds=i * 30)))
    states.append(_make_mock_state(eid, 0.0, base + timedelta(minutes=20)))
    states.append(_make_mock_state(eid, 0.0, base + timedelta(minutes=25)))

    p1, p2 = _patch_recorder(eid, states)
    with p1, p2:
        result = await det.async_seed_from_history(MagicMock(), eid, days=7)

    assert result is not None
    assert result["session_count"] == 1
    total = list(result["weekday_totals"].values())[0]
    assert 2.0 < total < 5.0  # 10kW × 20min ≈ 3.3 kWh


# ════════════════════════════════════════════
# #438: false-full on min-current oscillation
# Reproduces the HA-PROD 2026-06-05 incident where a car/charger
# combo whose handshake floor is 9 A oscillated at a 6 A offer
# (cycling 4.24 / 1.57 / 0 kW), the detector saw 3 consecutive
# low-power samples after a >3 kW peak, and anchored full=true
# after only ~0.19 kWh of session energy. This pinned SOC=100 %
# and skipped subsequent charging.
#
# These tests pin the DESIRED post-fix behaviour:
#   (a) sessions with total energy below a sane minimum (~2 kWh)
#       must not anchor full
#   (b) the confirm window must be longer than 30 s to survive a
#       transient car-side phase renegotiation
# Both are expected to FAIL on develop until #438 lands.
# ════════════════════════════════════════════

class TestFalseFullOnMinCurrentOscillation:
    """Regression fixtures for the #438 stuck-state class.

    The session-energy floor (`FULL_SESSION_ENERGY_MIN_KWH`) is the
    structural guard — a tiny oscillation session cannot anchor full
    even if it satisfies the peak / declining / 3-low-samples pattern.
    """

    def _feed_oscillation(self, detector, setpoint_a=6.0):
        """Replay an extended PROD-style oscillation at 6 A offer.

        The 2026-06-05 PROD session integrated to ~0.19 kWh of
        ``session_energy`` before triggering false-full. Reconstruct
        a representative ~11-minute window with the same per-sample
        power pattern (4240 / 1570 / 0 W as the car renegotiated
        between 3-phase, 1-phase, and contactor-open at the 6 A
        offer that sits below its 9 A handshake floor):

            ~7 min of oscillation between 4240 and 1570 W (declining
                avg, satisfies MIN_SAMPLES=12 and produces a
                negative regression slope < -5 W/min)
            3 zero samples at the tail (triggers the
                ``_full_confirm_count >= 3`` branch)

        Total integrated energy ≈ 0.3 kWh — under any sensible
        session-energy floor for taper-to-full.
        """
        # 7 minutes of oscillation at 10 s sample interval = 42 samples.
        # Cycle: 4240 → 4240 → 1570 → 1570 → 0 (one minute period),
        # producing a declining average and a clear regression slope.
        oscillation = [4240.0, 4240.0, 1570.0, 1570.0, 0.0, 1570.0]
        t_offset_min = 0.0
        sample_period_min = 10.0 / 60.0  # 10 s between samples

        for i in range(42):
            power_w = oscillation[i % len(oscillation)]
            detector.update(power_w, setpoint_a, True, _make_dt(t_offset_min))
            t_offset_min += sample_period_min

        # Trailing 3 zero samples — the trigger pattern for
        # ``_full_confirm_count >= 3``. Separated so the test
        # intent is obvious: these zeros are what the bug
        # mistakes for end-of-charge.
        for _ in range(3):
            detector.update(0.0, setpoint_a, True, _make_dt(t_offset_min))
            t_offset_min += sample_period_min

    def test_short_oscillation_must_not_anchor_full(self):
        """A ~38-second oscillation totalling well under 1 kWh must
        not be interpreted as a completed charge.

        Pre-fix: detector sees peak=4250 W (> SESSION_PEAK_MIN),
        declining phase, 3 consecutive samples < FULL_POWER_THRESHOLD
        → ``_full_detected = True``. This is the bug.

        Post-fix: a session-energy floor (~2 kWh suggested) must
        gate taper-to-full so a tiny session cannot anchor SOC=100.
        """
        det = EVTaperDetector(DEFAULT_CONFIG)
        self._feed_oscillation(det)
        assert det._full_detected is False, (
            "False-full anchor: a ~0.2 kWh oscillation session must "
            "not mark the car as fully charged. See issue #438."
        )

    def test_short_oscillation_must_not_anchor_soc_100(self):
        """Companion check: if full anchored is False, SOC should
        not be pinned at 100 % either."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        self._feed_oscillation(det)
        assert det._estimated_soc < 100.0, (
            "SOC anchored at 100 % after a tiny oscillation session "
            "— sympom of the false-full anchor (issue #438)."
        )

    def test_short_oscillation_no_last_full_timestamp(self):
        """Companion check: no ``last_full_timestamp`` should be
        recorded for a session that never genuinely completed."""
        det = EVTaperDetector(DEFAULT_CONFIG)
        self._feed_oscillation(det)
        assert det._last_full_timestamp is None, (
            "last_full_charge anchored from a tiny oscillation — "
            "this pins skip_logic to 'SOC 100 %' until next "
            "disconnect (issue #438)."
        )


# ════════════════════════════════════════════
# Per-vehicle session-energy floor (#438 Phase A — small-battery cars)
# ════════════════════════════════════════════
#
# The 1.0 kWh constant is a CAP; the effective per-vehicle floor is
# ``min(constant, capacity * 0.025)``. This protects against the
# reviewer-flagged false-negative on small-battery cars arriving at
# very high SOC (e.g. a 24 kWh LEAF needing only ~0.6 kWh to top up).
# ════════════════════════════════════════════

class TestPerVehicleEnergyFloor:
    """Pin the per-vehicle scaling of the taper-to-full energy floor.

    A 24 kWh LEAF at 99 % only needs ~0.24 kWh to finish; a flat 1.0
    kWh floor would lock the full-anchor out for these cars. The
    proportional rule ``min(constant, capacity * 0.025)`` solves both
    ends: handshake oscillations still blocked (0.2 kWh below any
    floor), small-battery taper-to-full still anchorable.
    """

    def test_floor_small_battery_scales_down(self):
        """24 kWh LEAF: floor = 0.6 kWh (proportional binds)."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 24})
        assert det._session_energy_floor_kwh() == pytest.approx(0.6)

    def test_floor_medium_battery_at_cap(self):
        """40 kWh: floor = 1.0 kWh (cap binds at constant)."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 40})
        assert det._session_energy_floor_kwh() == pytest.approx(1.0)

    def test_floor_large_battery_at_cap(self):
        """80 kWh Tesla: floor = 1.0 kWh (cap binds)."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 80})
        assert det._session_energy_floor_kwh() == pytest.approx(1.0)

    def test_floor_default_capacity(self):
        """Config missing ``ev_battery_capacity_kwh`` → fallback 40."""
        det = EVTaperDetector({})
        assert det._session_energy_floor_kwh() == pytest.approx(1.0)

    def test_small_battery_legitimate_full_anchors_at_proportional_floor(self):
        """24 kWh LEAF: a legitimate ~0.7 kWh taper-to-full session
        must anchor full (above the 0.6 kWh proportional floor but
        below the old 1.0 kWh flat floor).

        Pre-Phase-A (flat 1.0 kWh floor): blocked → false-negative.
        Post-Phase-A (0.6 kWh floor for 24 kWh): anchors. ✓"""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 24})
        # 12-minute taper from 7 kW peak linearly to 0:
        #   avg ≈ 3.5 kW × 720 s = 0.70 kWh delivered.
        # 9 samples/step × 8 steps × 10 s = 720 s.
        steps = [7000, 6000, 5000, 4000, 3000, 2000, 1000, 0]
        samples_per_step = 9
        sample_idx = 0
        for power in steps:
            for _ in range(samples_per_step):
                det.update(power, 16.0, True, _make_dt(sample_idx * 10 / 60))
                sample_idx += 1
        # Trailing zeros to trigger _full_confirm_count >= 3
        for _ in range(3):
            det.update(0.0, 16.0, True, _make_dt(sample_idx * 10 / 60))
            sample_idx += 1
        assert det._current_session_energy_kwh > 0.6, (
            f"test profile only integrated to {det._current_session_energy_kwh:.2f} kWh — "
            "needs > 0.6 to validate the per-vehicle floor allows it."
        )
        assert det._full_detected is True, (
            f"legitimate 24 kWh taper-to-full ({det._current_session_energy_kwh:.2f} kWh) "
            f"must anchor full ≥ floor ({det._session_energy_floor_kwh():.2f} kWh). "
            "If this fails, the small-battery false-negative regression is back."
        )

    def test_handshake_oscillation_still_blocked_on_small_battery(self):
        """The PROD bug (0.19 kWh oscillation) must STILL be blocked
        even on a small-battery vehicle where the floor scales down.
        24 kWh × 0.025 = 0.6 kWh — well above the 0.19 kWh bug."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 24})
        # Reuse the oscillation pattern from TestFalseFullOnMinCurrentOscillation
        oscillation = [4240.0, 4240.0, 1570.0, 1570.0, 0.0, 1570.0]
        sample_idx = 0
        for i in range(42):
            power_w = oscillation[i % len(oscillation)]
            det.update(power_w, 6.0, True, _make_dt(sample_idx * 10 / 60))
            sample_idx += 1
        for _ in range(3):
            det.update(0.0, 6.0, True, _make_dt(sample_idx * 10 / 60))
            sample_idx += 1
        assert det._full_detected is False, (
            "small-battery floor (0.6 kWh) must still block the "
            "0.19 kWh handshake-oscillation bug."
        )
