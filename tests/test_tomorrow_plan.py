"""Tests for the calendar-day forecast shown by the Tomorrow schedule tab."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.solar_energy_management.coordinator.today_plan import (
    KIND_CHEAP_START,
    KIND_NOW,
    KIND_SOLAR_PEAK,
    compose_tomorrow_plan,
)


NOW = datetime(2026, 5, 28, 9, 0, 0)
TOMORROW = datetime(2026, 5, 29, 0, 0, 0)


def _price(when: datetime, level: str, price: float) -> dict:
    return {"t": when.isoformat(), "level": level, "price": price}


def test_tomorrow_plan_is_preliminary_until_prices_are_published():
    result = compose_tomorrow_plan(
        now=NOW,
        upcoming_prices=[],
        solar_peak_time="12:30",
        solar_forecast_kwh=14.2,
    )

    assert result["status"] == "preliminary"
    assert all(row["kind"] != KIND_NOW for row in result["rows"])
    peak = next(row for row in result["rows"] if row["kind"] == KIND_SOLAR_PEAK)
    assert datetime.fromisoformat(peak["when"]) == TOMORROW.replace(hour=12, minute=30)


def test_tomorrow_plan_handles_timezone_aware_calendar_day():
    tz = ZoneInfo("Europe/Stockholm")
    now = datetime(2026, 3, 28, 23, 30, tzinfo=tz)
    tomorrow = (now + timedelta(days=1)).date()
    result = compose_tomorrow_plan(
        now=now,
        upcoming_prices=[
            {
                "t": datetime(2026, 3, 29, 3, 0, tzinfo=tz).isoformat(),
                "price": 0.42,
            }
        ],
        solar_peak_time=datetime(2026, 3, 28, 13, 15, tzinfo=tz).isoformat(),
        solar_forecast_kwh=18.0,
        night_start=None,
        night_end=None,
    )

    assert result["date"] == tomorrow.isoformat()
    assert result["status"] == "final"
    for row in result["rows"]:
        when = datetime.fromisoformat(row["when"])
        assert when.astimezone(tz).date() == tomorrow


def test_tomorrow_plan_remaps_iso_solar_peak_to_tomorrow():
    result = compose_tomorrow_plan(
        now=NOW,
        upcoming_prices=[],
        solar_peak_time=NOW.replace(hour=13, minute=15).isoformat(),
        solar_forecast_kwh=10.0,
    )

    peak = next(row for row in result["rows"] if row["kind"] == KIND_SOLAR_PEAK)
    assert datetime.fromisoformat(peak["when"]) == TOMORROW.replace(hour=13, minute=15)


def test_tomorrow_plan_becomes_final_with_tomorrow_prices_only():
    prices = [
        _price(NOW.replace(hour=22), "cheap", 0.05),
        _price(TOMORROW.replace(hour=1), "cheap", 0.08),
        _price(TOMORROW.replace(hour=2), "cheap", 0.10),
        _price(TOMORROW.replace(hour=3), "normal", 0.25),
        _price(TOMORROW + timedelta(days=1, hours=1), "cheap", 0.06),
        _price(TOMORROW + timedelta(days=1, hours=2), "cheap", 0.07),
    ]

    result = compose_tomorrow_plan(
        now=NOW,
        upcoming_prices=prices,
        currency="SEK",
    )

    assert result["status"] == "final"
    cheap = [row for row in result["rows"] if row["kind"] == KIND_CHEAP_START]
    assert len(cheap) == 1
    assert datetime.fromisoformat(cheap[0]["when"]) == TOMORROW.replace(hour=1)
    assert cheap[0]["values"]["currency"] == "SEK"
    assert all(
        datetime.fromisoformat(row["when"]).date() == TOMORROW.date()
        for row in result["rows"]
    )


def test_tomorrow_plan_keeps_overnight_ev_window_inside_calendar_day():
    result = compose_tomorrow_plan(
        now=NOW,
        upcoming_prices=[
            _price(TOMORROW.replace(hour=0), "normal", 0.2),
        ],
        night_start=TOMORROW.replace(hour=0),
        ev_min_remaining_kwh=8.0,
        ev_effective_rate_kw=4.0,
        ev_deadline=TOMORROW.replace(hour=7),
    )

    starts = [row for row in result["rows"] if row["kind"] == "ev_charge_start"]
    reached = [row for row in result["rows"] if row["kind"] == "ev_min_reached"]
    assert starts[0]["when"] == TOMORROW.isoformat()
    assert reached[0]["when"] == TOMORROW.replace(hour=2).isoformat()
