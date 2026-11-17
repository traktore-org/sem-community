"""#822 option 2 — recommend the source that has been closest, never switch."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    ForecastLedger,
    recommend_source,
)


def _days(n):
    return [f"2026-06-{d:02d}" for d in range(1, n + 1)]


def _led(forecast, actual=20.0, n=14, h=0, skip=()):
    led = ForecastLedger()
    for d in _days(n):
        if d not in skip:
            led.record(d, h, forecast(d) if callable(forecast) else forecast)
        led.settle(d, actual)
    return led


def test_clear_winner_is_recommended():
    ledgers = {"a": _led(30.0), "b": _led(21.0)}
    rec = recommend_source(ledgers, "a")
    assert rec["source"] == "b" and rec["days"] == 14
    assert rec["by_pct"] == 90.0


def test_within_margin_is_none():
    ledgers = {"a": _led(25.0), "b": _led(24.0)}   # 5 vs 4 kWh: 20 % less
    assert recommend_source(ledgers, "a") is not None
    ledgers = {"a": _led(25.0), "b": _led(24.5)}   # 10 % less
    assert recommend_source(ledgers, "a") is None


def test_current_best_is_none():
    ledgers = {"a": _led(21.0), "b": _led(30.0)}
    assert recommend_source(ledgers, "a") is None


def test_thirteen_days_is_none():
    ledgers = {"a": _led(30.0, n=13), "b": _led(21.0, n=13)}
    assert recommend_source(ledgers, "a") is None


def test_one_source_or_unknown_current_is_none():
    assert recommend_source({"a": _led(30.0)}, "a") is None
    assert recommend_source({"a": _led(30.0), "b": _led(21.0)}, "zzz") is None
    assert recommend_source({}, "a") is None


def test_days_not_shared_are_not_compared():
    # b only has 10 days of its own forecast: 10 shared < 14, even though
    # the roof has 14 settled days.
    skip = _days(14)[10:]
    ledgers = {"a": _led(30.0), "b": _led(21.0, skip=skip)}
    assert recommend_source(ledgers, "a") is None


def test_an_outage_day_is_not_rewarded():
    # b was down on the one day it would have been far off; that day drops
    # out for BOTH, so b is judged on the days it really answered.
    bad = _days(15)[0]
    a = _led(lambda d: 30.0, n=15)
    b = _led(lambda d: 21.0, n=15, skip=(bad,))
    rec = recommend_source({"a": a, "b": b}, "a")
    assert rec["days"] == 14
    b_bad = _led(lambda d: 21.0, n=15)
    b_bad.record(bad, 0, 21.0)
    # Same source, same days: the gap day never counted against a either.
    assert recommend_source({"a": a, "b": b_bad}, "a")["days"] == 15


def test_today_with_a_growing_actual_is_skipped():
    ledgers = {"a": _led(30.0, n=14), "b": _led(21.0, n=14)}
    assert recommend_source(ledgers, "a", today=_days(14)[-1]) is None


def test_tomorrow_rides_along_only_with_enough_days():
    a = _led(30.0)
    b = _led(21.0)
    for d in _days(14):
        a.record(d, 1, 30.0)
        b.record(d, 1, 21.0)
    assert recommend_source({"a": a, "b": b}, "a")["tomorrow_by_pct"] == 90.0
    assert recommend_source({"a": _led(30.0), "b": _led(21.0)}, "a")["tomorrow_by_pct"] is None


def test_the_coordinator_publishes_advice_and_repoints_nothing():
    reader = SimpleNamespace(source="a")
    coord = SimpleNamespace(
        _forecast_reader=reader,
        _source_ledgers={"a": _led(30.0), "b": _led(21.0)},
    )
    rec = SEMCoordinator.source_recommendation(coord)
    assert rec["source"] == "b"
    assert reader.source == "a"
    coord._forecast_reader = SimpleNamespace(source=None)
    assert SEMCoordinator.source_recommendation(coord) is None


def test_the_sensor_carries_the_recommendation_attributes():
    import inspect
    from custom_components.solar_energy_management import sensor
    src = inspect.getsource(sensor)
    for key in ("recommended_source", "recommended_by_pct", "recommended_days"):
        assert f'attrs["{key}"]' in src


def test_the_config_card_renders_it_through_the_picker_save_path():
    from pathlib import Path
    card = (Path(__file__).parent.parent / "dashboard/card/src/cards/sem-config-card.js").read_text()
    assert "_renderForecastRecommendation(attrs, raw)" in card
    assert "applyRecommendation((k, v) => this._saveOption(k, v), rec)" in card
