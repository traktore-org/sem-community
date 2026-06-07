"""#440 — charge mode is the sole authority on whether to charge.

Pre-#440, ``coordinator/ev_control.py:_calculate_forecast_night_target``
ran two override paths (SOC-based skip + solar-forecast-based reduction)
that could zero out the night target even when the user's mode and Min
slider said "charge tonight". This violated the architectural principle
established for v1.7.1-beta.4:

> The truth sources for SEM are the user's sliders (Min / Max), the
> charge mode, and — only if target type is ``%`` — the real vehicle SOC.

These tests pin the post-#440 behaviour:

1. ``_calculate_forecast_night_target`` is a pure pass-through of the
   user's remaining-kWh delta — no taper-detector reads, no forecast
   reads.
2. The previously-overriding inputs (high ``estimated_soc``, predicted
   daily consumption, consecutive-skip count, tomorrow's forecast) do
   NOT change the function's output.
3. The skip-decision API surface is gone: ``calculate_nights_until_charge``,
   ``record_skip``, ``reset_skips``, ``_consecutive_skips``,
   ``notify_ev_charge_skip``, ``notify_ev_charge_recommended``.
4. The corresponding sensor entity keys (``ev_charge_needed``,
   ``ev_nights_until_charge``, ``ev_charge_skip_reason``) are no longer
   present in ``SENSOR_TYPES``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)


# ──────────────────────────────────────────────
# 1. The pass-through contract
# ──────────────────────────────────────────────


class _MockCoord:
    """Minimal mock matching the surface ``_calculate_forecast_night_target``
    touches. Used to drive the bound method directly."""

    def __init__(self, *, ev_taper=None, predictor=None, forecast=None,
                 cycle_vehicle_soc=None, config=None):
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin,
        )
        self.config = config or {}
        self._ev_taper_detector = ev_taper
        self._predictor = predictor
        self._forecast_reader = MagicMock()
        self._forecast_reader.read_forecast = MagicMock(return_value=forecast)
        self._cycle_vehicle_soc = cycle_vehicle_soc
        # Bind the real method.
        self._calculate_forecast_night_target = (
            EVControlMixin._calculate_forecast_night_target.__get__(self)
        )


def _fake_energy(monthly_home=0.0, monthly_battery_charge=0.0):
    e = MagicMock()
    e.monthly_home = monthly_home
    e.monthly_battery_charge = monthly_battery_charge
    return e


def test_passthrough_with_high_estimated_soc():
    """SOC = 100 % via anchored taper → night target unchanged."""
    taper = EVTaperDetector({"ev_battery_capacity_kwh": 40})
    taper._soc_anchored = True
    taper._estimated_soc = 100.0
    taper._last_full_timestamp = "2026-06-06T12:00:00"
    coord = _MockCoord(ev_taper=taper)
    out = coord._calculate_forecast_night_target(12.0, _fake_energy())
    assert out == 12.0, (
        f"night target {out} != input 12.0 — taper-detector override "
        "may have crept back in (see #440)."
    )


def test_passthrough_with_high_predicted_daily():
    """Predicted daily consumption = 0 (means car already has range) →
    night target still unchanged."""
    taper = EVTaperDetector({"ev_battery_capacity_kwh": 40})
    taper._soc_anchored = True
    taper._estimated_soc = 95.0
    predictor = MagicMock()
    predictor.predict_ev_consumption_tomorrow = MagicMock(return_value=0.0)
    coord = _MockCoord(ev_taper=taper, predictor=predictor)
    out = coord._calculate_forecast_night_target(8.0, _fake_energy())
    assert out == 8.0


def test_passthrough_with_strong_solar_forecast():
    """Tomorrow's forecast = 50 kWh — previously would have reduced the
    night target; post-#440 the user's delta is honoured verbatim."""
    forecast = MagicMock()
    forecast.available = True
    forecast.forecast_tomorrow_kwh = 50.0
    coord = _MockCoord(forecast=forecast)
    out = coord._calculate_forecast_night_target(14.0, _fake_energy(monthly_home=150.0))
    assert out == 14.0


def test_passthrough_with_real_vehicle_soc_at_target():
    """Real vehicle SOC > target — still no override. Mode controls
    whether to charge; ``%`` target gating happens at the slider/mode
    layer, not here."""
    taper = EVTaperDetector({"ev_battery_capacity_kwh": 40, "ev_target_soc": 80})
    coord = _MockCoord(ev_taper=taper, cycle_vehicle_soc=92.0)
    out = coord._calculate_forecast_night_target(10.0, _fake_energy())
    assert out == 10.0


def test_passthrough_negative_input_clamped_to_zero():
    """Defensive: a stale negative ``remaining_kwh`` is clamped to 0."""
    coord = _MockCoord()
    assert coord._calculate_forecast_night_target(-3.5, _fake_energy()) == 0.0


def test_passthrough_zero_input_returns_zero():
    coord = _MockCoord()
    assert coord._calculate_forecast_night_target(0.0, _fake_energy()) == 0.0


# ──────────────────────────────────────────────
# 2. Removed API surface — pin the deletions
# ──────────────────────────────────────────────


class TestRemovedAPIs:
    """The skip-decision API surface is gone. These tests fail loudly if
    anyone resurrects it without re-evaluating the architectural choice."""

    def test_detector_has_no_calculate_nights_until_charge(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "calculate_nights_until_charge"), (
            "calculate_nights_until_charge resurrected — see #440."
        )

    def test_detector_has_no_record_skip(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "record_skip")

    def test_detector_has_no_reset_skips(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "reset_skips")

    def test_detector_has_no_consecutive_skips_field(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "_consecutive_skips")

    def test_intelligence_data_has_no_charge_needed(self):
        from custom_components.solar_energy_management.coordinator.types import (
            EVIntelligenceData,
        )
        d = EVIntelligenceData()
        assert not hasattr(d, "charge_needed")
        assert not hasattr(d, "nights_until_charge")
        assert not hasattr(d, "charge_skip_reason")

    def test_notification_manager_has_no_skip_methods(self):
        from custom_components.solar_energy_management.coordinator.notifications import (
            NotificationManager,
        )
        assert not hasattr(NotificationManager, "notify_ev_charge_skip")
        assert not hasattr(NotificationManager, "notify_ev_charge_recommended")


# ──────────────────────────────────────────────
# 3. Sensor entity registry — keys are gone
# ──────────────────────────────────────────────


def test_obsolete_sensor_keys_absent_from_registry():
    from custom_components.solar_energy_management import sensor as sem_sensor
    keys = {d.key for d in sem_sensor.SENSOR_TYPES}
    for obsolete in ("ev_charge_needed", "ev_nights_until_charge",
                     "ev_charge_skip_reason"):
        assert obsolete not in keys, (
            f"sensor.{obsolete} resurrected — see #440. Charge mode is "
            "the sole authority on charging now."
        )


# ──────────────────────────────────────────────
# 4. Persistence — old payloads remain readable
# ──────────────────────────────────────────────


def test_restore_state_ignores_legacy_consecutive_skips():
    """A legacy payload with the removed ``consecutive_skips`` key must
    still restore cleanly (forward-compat for users upgrading from
    v1.7.1-beta.3)."""
    det = EVTaperDetector({"ev_battery_capacity_kwh": 40})
    det.restore_state({
        "last_full_charge": "2026-06-01T10:00:00",
        "energy_since_full": 5.0,
        "estimated_soc": 87.5,
        "battery_health_samples": [],
        "battery_health_pct": 98.0,
        "consecutive_skips": 4,   # legacy field — must be silently ignored
        "soc_anchored": True,
        "hw_total_at_full": 1234.5,
    })
    assert det._estimated_soc == 87.5
    assert det._soc_anchored is True
    assert det._hw_total_at_full == 1234.5
    assert not hasattr(det, "_consecutive_skips")
