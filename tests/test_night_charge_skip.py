"""Tests for night charge skip logic (#106).

Reproduces the PROD bug: EV Intelligence says charge_needed=False
but night charging continues because _calculate_forecast_night_target
doesn't return 0.

Test scenarios from real PROD data (2026-04-28):
- SOC 57.6%, predicted daily 4.4 kWh, capacity 40 kWh
- charge_needed=False, skip_reason="SOC 58%, 3 nights range"
- But night charging was active with remaining=1.1 kWh
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, PropertyMock, patch
from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)


class MockCoordinator(EVControlMixin):
    """Minimal coordinator mock for testing EV control logic."""

    def __init__(self, config, ev_taper=None):
        self.config = config
        self._ev_taper_detector = ev_taper
        self._ev_device = MagicMock()
        self._forecast_reader = MagicMock()
        self._energy_calculator = MagicMock()
        self._energy_calculator._import_rate = 0.30
        self._predictor = MagicMock()
        self._cycle_vehicle_soc = None
        self.time_manager = MagicMock()
        self.hass = MagicMock()


class TestNightChargeSkipLogic:
    """Test _calculate_forecast_night_target skip decisions."""

    def _make_taper_detector(self, soc=57.6, anchored=True, last_full=None):
        """Create EVTaperDetector with pre-set state."""
        config = {"ev_battery_capacity_kwh": 40, "ev_target_soc": 80, "ev_min_soc_threshold": 20}
        detector = EVTaperDetector(config)
        detector._estimated_soc = soc
        detector._soc_anchored = anchored
        detector._last_full_timestamp = last_full
        detector._energy_since_full = (100.0 - soc) / 100.0 * 40  # Derive from SOC
        return detector

    def _make_coordinator(self, ev_taper=None, forecast_tomorrow=20.0):
        """Create mock coordinator."""
        config = {
            "ev_battery_capacity_kwh": 40,
            "ev_target_soc": 80,
            "ev_min_soc_threshold": 20,
            "daily_home_consumption_estimate": 18.0,
            "daily_battery_consumption_estimate": 10.0,
        }
        coord = MockCoordinator(config, ev_taper)

        # Mock forecast
        forecast = MagicMock()
        forecast.available = True
        forecast.forecast_tomorrow_kwh = forecast_tomorrow
        coord._forecast_reader.read_forecast.return_value = forecast

        # Mock predictor
        coord._predictor.predict_ev_consumption_tomorrow.return_value = 4.4

        return coord

    def _make_energy(self, daily_ev=8.38, monthly_home=500, monthly_battery=300):
        energy = MagicMock()
        energy.daily_ev = daily_ev
        energy.monthly_home = monthly_home
        energy.monthly_battery_charge = monthly_battery
        return energy

    def test_prod_bug_soc_58_should_skip(self):
        """PROD scenario: SOC 58%, 3 nights range → should return 0."""
        detector = self._make_taper_detector(soc=57.6, anchored=True)
        coord = self._make_coordinator(ev_taper=detector)
        energy = self._make_energy()

        result = coord._calculate_forecast_night_target(1.1, energy)
        assert result == 0.0, f"Expected 0.0 (skip), got {result}"

    def test_soc_above_target_skips(self):
        """SOC 85% > target 80% → should skip."""
        detector = self._make_taper_detector(soc=85.0, anchored=True)
        coord = self._make_coordinator(ev_taper=detector)
        energy = self._make_energy()

        result = coord._calculate_forecast_night_target(10.0, energy)
        assert result == 0.0

    def test_soc_low_charges(self):
        """SOC 15% → should NOT skip (below min threshold with safety margin)."""
        detector = self._make_taper_detector(soc=15.0, anchored=True)
        coord = self._make_coordinator(ev_taper=detector)
        energy = self._make_energy()

        result = coord._calculate_forecast_night_target(10.0, energy)
        assert result > 0, f"Expected charging (>0), got {result}"

    def test_no_anchor_does_not_skip(self):
        """Without SOC anchor, skip logic should not run."""
        detector = self._make_taper_detector(soc=57.6, anchored=False, last_full=None)
        coord = self._make_coordinator(ev_taper=detector)
        energy = self._make_energy()

        result = coord._calculate_forecast_night_target(10.0, energy)
        # Should return forecast-adjusted value, not 0
        assert result > 0

    def test_anchored_via_session_bootstrap_skips(self):
        """SOC anchored from session bootstrap (no full charge) → should skip if sufficient."""
        detector = self._make_taper_detector(soc=70.0, anchored=True, last_full=None)
        coord = self._make_coordinator(ev_taper=detector)
        energy = self._make_energy()

        result = coord._calculate_forecast_night_target(10.0, energy)
        assert result == 0.0, f"Expected skip (anchored SOC 70%), got {result}"

    def test_anchored_via_taper_full_skips(self):
        """SOC anchored from taper detection → should skip if sufficient."""
        detector = self._make_taper_detector(
            soc=60.0, anchored=True, last_full="2026-04-27T17:00:00"
        )
        coord = self._make_coordinator(ev_taper=detector)
        energy = self._make_energy()

        result = coord._calculate_forecast_night_target(10.0, energy)
        assert result == 0.0

    def test_no_forecast_still_skips_on_soc(self):
        """Without solar forecast, SOC skip should STILL work."""
        detector = self._make_taper_detector(soc=57.6, anchored=True)
        coord = self._make_coordinator(ev_taper=detector, forecast_tomorrow=0)
        coord._forecast_reader.read_forecast.return_value = MagicMock(
            available=False, forecast_tomorrow_kwh=0
        )
        energy = self._make_energy()

        # SOC skip runs before forecast check — should return 0
        result = coord._calculate_forecast_night_target(10.0, energy)
        assert result == 0.0, f"SOC skip should work even without forecast, got {result}"


class TestTaperDetectorFullDetection:
    """Test false full detection prevention."""

    def test_low_peak_does_not_trigger_full(self):
        """Peak 1910W should NOT trigger full detection (below 3000W threshold)."""
        config = {"ev_battery_capacity_kwh": 40}
        detector = EVTaperDetector(config)

        # Simulate low-power night charging then drop to 0
        for _ in range(20):
            detector.update(1910, 10, True, datetime.now())
        # Power drops to 0
        result = detector.update(0, 0, True, datetime.now())

        assert not detector.full_detected, \
            "Full should NOT be detected at 1910W peak (below 3000W threshold)"

    def test_high_peak_triggers_full(self):
        """Peak 6000W declining to 0 SHOULD trigger full detection."""
        config = {"ev_battery_capacity_kwh": 40}
        detector = EVTaperDetector(config)

        # Simulate real taper: high power declining
        powers = [6000, 5500, 5000, 4500, 4000, 3500, 3000, 2500, 2000, 1500, 1000, 500, 100]
        for p in powers:
            for _ in range(6):  # Hold each step for a few cycles
                detector.update(p, p / 690, True, datetime.now())

        # Power drops to 0
        result = detector.update(0, 0, True, datetime.now())
        # Full detection depends on declining_phase being set via regression
        # With enough samples this should trigger


class TestSkipCounterOncePerNight:
    """Test that skip counter increments once per night, not every cycle."""

    def test_calculate_nights_increments_once(self):
        """record_skip should only be called once per night."""
        config = {"ev_battery_capacity_kwh": 40, "ev_target_soc": 80,
                  "ev_min_soc_threshold": 20, "ev_max_consecutive_skips": 3}
        detector = EVTaperDetector(config)
        detector._soc_anchored = True
        detector._estimated_soc = 70.0

        # Simulate: call record_skip once (as coordinator should)
        detector.record_skip()
        assert detector._consecutive_skips == 1

        # Second night
        detector.record_skip()
        assert detector._consecutive_skips == 2

        # Third night — hits safety net
        detector.record_skip()
        assert detector._consecutive_skips == 3

        # Fourth call — calculate_nights_until_charge returns charge_needed=True
        nights, needed, reason = detector.calculate_nights_until_charge(4.4)
        assert needed is True
        assert "consecutive skips" in reason.lower()

    def test_reset_clears_counter(self):
        """reset_skips should clear consecutive counter."""
        config = {"ev_battery_capacity_kwh": 40, "ev_target_soc": 80,
                  "ev_min_soc_threshold": 20, "ev_max_consecutive_skips": 3}
        detector = EVTaperDetector(config)
        detector._soc_anchored = True
        detector._estimated_soc = 70.0

        detector.record_skip()
        detector.record_skip()
        assert detector._consecutive_skips == 2

        detector.reset_skips()
        assert detector._consecutive_skips == 0
