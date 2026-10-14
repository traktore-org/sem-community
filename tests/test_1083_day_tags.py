"""#1083 — tag a day by its sky, the car, its prices and its data gaps.

The day shapes are PROD's own (Huawei 10 kW, Erlen, October 2026):

* 08.10 — 4.3 kWh made against an 18.3 kWh forecast (the #1068 day) → grey.
* 12.10 — the Huawei lifetime counter sat at 23 832.86 kWh all day while
  the forecast promised sun: a frozen inverter, not a dark sky → gap.
* 13.10 — a clear morning, clouds after noon, 14.2 kWh of a 20.2 forecast
  (the #1104 day) → mixed, never sunny.
"""
import math

from custom_components.solar_energy_management.analytics.day_tags import (
    GAP_DARK_MIN,
    tag_day,
    tag_prices,
    tag_sky,
)

SUNRISE, SUNSET = 7.6, 18.7


def _sine(peak_w, start=SUNRISE, end=SUNSET, step_min=5, after_noon=None):
    """5-minute (hour, watts) readings on the clear-sky sine; after_noon
    scales every reading past 12:00 (clouds) — with a ragged pattern."""
    out = []
    h = start
    i = 0
    while h <= end:
        w = peak_w * math.sin(math.pi * (h - start) / (end - start))
        if after_noon is not None and h >= 12.0:
            w *= after_noon * (0.4 if i % 3 == 0 else 1.0)
        out.append((h, max(0.0, w)))
        h += step_min / 60.0
        i += 1
    return out


def test_a_clear_steady_day_is_sunny():
    t = tag_day(date="2026-09-20", solar=_sine(7000), actual_kwh=24.0,
                forecast_kwh=23.0, clear_sky_kwh=25.0)
    assert t.sky == "sunny"
    assert t.tags == ["sunny"]


def test_prod_08_10_is_grey():
    t = tag_day(date="2026-10-08", solar=_sine(750), actual_kwh=4.3,
                forecast_kwh=18.3, clear_sky_kwh=25.0)
    assert t.sky == "grey"


def test_prod_13_10_clear_morning_cloudy_afternoon_is_mixed():
    t = tag_day(date="2026-10-13", solar=_sine(5200, after_noon=0.5),
                actual_kwh=14.2, forecast_kwh=20.2, clear_sky_kwh=25.0)
    assert t.sky == "mixed"
    assert "sunny" not in t.tags


def test_a_big_day_with_a_ragged_midday_is_not_sunny():
    """Enough kWh is not enough: passing clouds make it mixed."""
    ragged = [(h, w * (0.3 if i % 2 else 1.0))
              for i, (h, w) in enumerate(_sine(9000))]
    t = tag_day(date="2026-09-21", solar=ragged, actual_kwh=24.0,
                forecast_kwh=23.0, clear_sky_kwh=25.0)
    assert t.sky == "mixed"


def test_prod_12_10_frozen_counter_is_a_gap():
    t = tag_day(date="2026-10-12", solar=[(h, 0.0) for h, _ in _sine(1)],
                actual_kwh=0.0, forecast_kwh=15.0, clear_sky_kwh=25.0,
                counter_flat=True)
    assert t.gap
    assert "gap" in t.tags
    assert any("counter" in w for w in t.gap_why)


def test_a_flat_counter_on_a_dark_forecast_is_no_gap():
    t = tag_day(date="2026-12-20", actual_kwh=0.0, forecast_kwh=0.5,
                counter_flat=True)
    assert not t.gap


def test_a_long_dark_reading_or_a_restart_is_a_gap():
    assert tag_day(date="d", dark_daylight_min=GAP_DARK_MIN + 1).gap
    assert not tag_day(date="d", dark_daylight_min=GAP_DARK_MIN).gap
    assert tag_day(date="d", restarted=True).gap


def test_dark_readings_are_left_out_not_counted_as_zero():
    """A blink at noon must not make a clear day 'ragged'."""
    solar = [(h, None if 12.0 <= h < 12.2 else w) for h, w in _sine(7000)]
    t = tag_day(date="d", solar=solar, actual_kwh=24.0, forecast_kwh=23.0,
                clear_sky_kwh=25.0)
    assert t.sky == "sunny"


def test_car_needs_a_finished_session_with_energy():
    assert tag_day(date="d", session_kwh=[6.3]).car
    assert tag_day(date="d", session_kwh=[6.3, 2.0]).car_kwh == 8.3
    assert not tag_day(date="d", session_kwh=[0.0]).car
    assert not tag_day(date="d").car


def test_prices():
    assert tag_prices([0.20, -0.02, 0.30], 0.10) == "negative"
    assert tag_prices([0.20, 0.08, 0.30], 0.10) == "cheap"
    assert tag_prices([0.20, 0.15, 0.30], 0.10) is None
    # (#994) a flat tariff has no comparison to make
    assert tag_prices([0.36] * 24, 0.40) is None
    assert tag_prices(None, 0.10) is None


def test_missing_inputs_leave_tags_out_never_invent_them():
    t = tag_day(date="d")
    assert t.sky is None and t.prices is None
    assert t.tags == []
    # no forecast and no clear-sky day: the sky cannot be judged
    assert tag_sky(10.0, None, None, 0.05) is None


def test_as_dict_round_trips_the_tags():
    d = tag_day(date="2026-10-08", solar=_sine(750), actual_kwh=4.3,
                forecast_kwh=18.3, clear_sky_kwh=25.0).as_dict()
    assert d["date"] == "2026-10-08" and d["tags"] == ["grey"]
