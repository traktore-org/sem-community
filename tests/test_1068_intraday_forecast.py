"""#1068 — the day plan keeps the morning forecast when the sun does not come.

PROD 08.10.2026: forecast 18.3 kWh, real 4.3 kWh. By noon the tracker knew
(confidence 1.0) but the correction floor was 0.5 and the plan's day slots
read the raw provider remaining."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
)

_NOW = ("custom_components.solar_energy_management.coordinator."
        "forecast_tracker.dt_util.now")
TZ_NOON = datetime(2026, 10, 8, 13, 0)


def _tracker(forecast_kwh: float, actual_kwh: float, now: datetime) -> ForecastTracker:
    t = ForecastTracker()
    t._today_forecast = forecast_kwh
    t._today_actual = actual_kwh
    t._correction_factor = 0.98
    t._get_sun_hours = lambda: (7.5, 18.9)
    # walk the EMA to steady state the way 5-min cycles would
    for k in range(36):
        with patch(_NOW, return_value=now - timedelta(minutes=5 * (36 - k))):
            t._calculate_dampening_factor()
    return t


def test_prod_day_noon_corrects_below_half():
    # 13:00, 5.5 sun-hours of 11.4: expected ≈ 47 % of 18.3 = 8.6 kWh,
    # measured 3.0 kWh → ratio ≈ 0.35. The 0.5 floor hid that.
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        rem = t.corrected_remaining_kwh(7.1)   # provider's raw remaining
    assert rem < 7.1 * 0.4


def test_published_dampening_factor_is_unchanged():
    # Asleep means asleep: the existing sensor and the surplus outlook keep
    # the 0.5 floor; only the new accessor reads the evidenced floor.
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        assert t.dampening_factor == pytest.approx(0.5)


def test_dawn_keeps_the_noise_floor():
    # 08:30: little expected yet — the 0.5 floor still applies.
    t = _tracker(18.3, 0.05, datetime(2026, 10, 8, 8, 30))
    with patch(_NOW, return_value=datetime(2026, 10, 8, 8, 30)):
        assert t.corrected_remaining_kwh(18.0) >= 18.0 * 0.5


def test_sunny_beat_still_capped_high():
    t = _tracker(10.0, 9.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        assert t.corrected_remaining_kwh(4.0) <= 4.0 * 1.5


def test_zero_and_garbage_stay_safe():
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        assert t.corrected_remaining_kwh(0) == 0.0
        assert t.corrected_remaining_kwh(None) == 0.0
        assert t.corrected_remaining_kwh("x") == 0.0
