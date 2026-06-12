"""#416 sub#2 + sub#3 — live-signal EMA smoothing + correct sun hours.

Sub#2: at 7-9 AM ``expected_fraction`` is tiny, so the normalized live
ratio amplifies the actual-sensor noise floor into large cycle-to-cycle
dampening swings (no smoothing existed). An EMA (τ = 300 s) over the
normalized ratio now feeds the blend; the raw value stays diagnostic.

Sub#3: ``next_rising``/``next_setting`` are NEXT events — during the
day next_rising is tomorrow's sunrise. Mixing tomorrow-rise with
today-set skewed the daylight window. Tomorrow-dated events now roll
back one day.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
    LIVE_RATIO_EMA_TAU_S,
)

TZ = timezone.utc


def _dt(hour, minute=0, day=18):
    return datetime(2026, 4, day, hour, minute, tzinfo=TZ)


def _tracker():
    t = ForecastTracker()
    t._hass = None
    t._today_date = "2026-04-18"
    t._today_forecast = 30.0
    t._correction_factor = 1.0
    return t


def _run_cycle(t, now, actual_kwh):
    """Drive one _calculate_dampening_factor cycle at a frozen time."""
    t._today_actual = actual_kwh
    with patch(
        "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.DEFAULT_TIME_ZONE = TZ
        return t._calculate_dampening_factor()


# ── Sub#2: EMA damps cycle-to-cycle jitter ───────────────────────────

def test_morning_jitter_is_damped():
    """Two cycles 10 s apart with a 25% jump in normalized ratio: the
    published dampening moves only a fraction of the raw swing
    (alpha = 1 - exp(-10/300) ≈ 0.033)."""
    t = _tracker()
    # 10:00 — well past the early-morning floor for a 30 kWh day.
    d1 = _run_cycle(t, _dt(10, 0), actual_kwh=6.0)
    s1 = t._smoothed_normalized_ratio
    # 10 s later the sensor jumps 25% (cloud-transit noise).
    d2 = _run_cycle(t, _dt(10, 0).replace(second=10), actual_kwh=7.5)
    s2 = t._smoothed_normalized_ratio
    raw2 = t._last_normalized_ratio

    # The raw ratio moved ~25%; the smoothed value moved ≲5% of that gap.
    assert raw2 > s1 * 1.2
    alpha_10s = 1 - pytest.approx(0.9672, abs=0.001).expected  # ≈ 0.033
    assert s2 - s1 == pytest.approx((raw2 - s1) * alpha_10s, rel=0.05)
    # And the published factor barely moved between the two cycles.
    assert abs(d2 - d1) < 0.05


def test_smoothed_converges_to_steady_signal():
    """A steady ratio converges: after >> τ the smoothed value equals
    the raw value and the blend behaves exactly as pre-#416."""
    t = _tracker()
    _run_cycle(t, _dt(10, 0), actual_kwh=6.0)
    # 30 minutes later (6×τ), same conditions → converged.
    d = _run_cycle(t, _dt(10, 30), actual_kwh=6.9)
    assert t._smoothed_normalized_ratio == pytest.approx(
        t._last_normalized_ratio, rel=0.02
    )
    assert d == pytest.approx(t._last_blended_pre_clamp, abs=0.51)  # clamp window


def test_ema_seeds_on_first_blended_cycle():
    t = _tracker()
    assert t._smoothed_normalized_ratio is None
    _run_cycle(t, _dt(12, 0), actual_kwh=15.0)
    # _last_normalized_ratio is rounded to 4dp; the EMA seed isn't.
    assert t._smoothed_normalized_ratio == pytest.approx(
        t._last_normalized_ratio, abs=1e-4
    )


def test_ema_resets_at_day_rollover():
    t = _tracker()
    _run_cycle(t, _dt(12, 0), actual_kwh=15.0)
    assert t._smoothed_normalized_ratio is not None
    with patch(
        "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = _dt(0, 5, day=19)
        mock_dt.DEFAULT_TIME_ZONE = TZ
        t.update(forecast_today_kwh=25.0, actual_solar_kwh=0.0)
    assert t._smoothed_normalized_ratio is None
    assert t._smoothed_ratio_ts is None


def test_clock_rewind_reseeds_instead_of_negative_alpha():
    """now_ts earlier than the stored ts (clock adjust / test reuse)
    re-seeds rather than computing exp() of a positive number."""
    t = _tracker()
    _run_cycle(t, _dt(12, 0), actual_kwh=15.0)
    before = t._smoothed_normalized_ratio
    _run_cycle(t, _dt(11, 0), actual_kwh=20.0)  # clock went backwards
    assert t._smoothed_normalized_ratio == pytest.approx(
        t._last_normalized_ratio, abs=1e-4
    )
    assert t._smoothed_normalized_ratio != before


# ── Sub#3: sun hours roll tomorrow's events back to today ────────────

def _sun_state(next_rising, next_setting):
    sun = MagicMock()
    sun.attributes = {
        "next_rising": next_rising.isoformat(),
        "next_setting": next_setting.isoformat(),
    }
    return sun


def test_sun_hours_daytime_uses_todays_sunrise():
    """At noon, next_rising is TOMORROW 06:12 — the old code mixed it
    with today's 20:00 sunset. Now it rolls back to today."""
    hass = MagicMock()
    hass.states.get.return_value = _sun_state(
        next_rising=_dt(6, 12, day=19),   # tomorrow morning
        next_setting=_dt(20, 0, day=18),  # today evening
    )
    t = ForecastTracker()
    t._hass = hass
    with patch(
        "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = _dt(12, 0, day=18)
        mock_dt.DEFAULT_TIME_ZONE = TZ
        rise, sett = t._get_sun_hours()
    assert rise == pytest.approx(6.2)
    assert sett == pytest.approx(20.0)


def test_sun_hours_after_sunset_rolls_both_back():
    """At 22:00 both next events are tomorrow's — both roll back so the
    window still describes TODAY."""
    hass = MagicMock()
    hass.states.get.return_value = _sun_state(
        next_rising=_dt(6, 12, day=19),
        next_setting=_dt(20, 2, day=19),
    )
    t = ForecastTracker()
    t._hass = hass
    with patch(
        "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = _dt(22, 0, day=18)
        mock_dt.DEFAULT_TIME_ZONE = TZ
        rise, sett = t._get_sun_hours()
    assert rise == pytest.approx(6.2)
    assert sett == pytest.approx(20.0, abs=0.05)


def test_sun_hours_pre_sunrise_unchanged():
    """Before sunrise both next events are today's — no rollback."""
    hass = MagicMock()
    hass.states.get.return_value = _sun_state(
        next_rising=_dt(6, 12, day=18),
        next_setting=_dt(20, 0, day=18),
    )
    t = ForecastTracker()
    t._hass = hass
    with patch(
        "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = _dt(4, 0, day=18)
        mock_dt.DEFAULT_TIME_ZONE = TZ
        rise, sett = t._get_sun_hours()
    assert rise == pytest.approx(6.2)
    assert sett == pytest.approx(20.0)
