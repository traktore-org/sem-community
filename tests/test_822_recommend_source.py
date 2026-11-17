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


def _act(d):
    return 8.0 + (int(d[-2:]) * 7 % 11)      # a varying real day: 8..18 kWh


def _led(forecast, n=14, h=0, skip=()):
    """``forecast``: a number (flat, no shape) or a function of the actual."""
    led = ForecastLedger()
    for d in _days(n):
        if d not in skip:
            led.record(d, h, forecast(_act(d)) if callable(forecast) else forecast)
        led.settle(d, _act(d))
    return led


def _flat():
    return _led(14.0)


def _shaped(scale=1.0, **kw):
    return _led(lambda a: a * scale, **kw)


def test_clear_winner_is_recommended():
    rec = recommend_source({"a": _flat(), "b": _shaped(1.4)}, "a")
    assert rec["source"] == "b" and rec["days"] == 14
    assert rec["by_pct"] > 90


def test_within_margin_is_none():
    noisy = _led(lambda a: a * 1.4 + (3 if int(a) % 2 else -3))
    flat_ish = _led(lambda a: 14.0 + (a - 13.0) * 0.05)
    # Both follow the day poorly; neither is 15 % better than the other.
    assert recommend_source({"a": noisy, "b": noisy}, "a") is None
    assert recommend_source({"a": flat_ish, "b": flat_ish}, "a") is None


def test_current_best_is_none():
    assert recommend_source({"a": _shaped(1.4), "b": _flat()}, "a") is None


def test_thirteen_days_is_none():
    ledgers = {"a": _led(14.0, n=13), "b": _shaped(1.4, n=13)}
    assert recommend_source(ledgers, "a") is None


def test_one_source_or_unknown_current_is_none():
    assert recommend_source({"a": _flat()}, "a") is None
    assert recommend_source({"a": _flat(), "b": _shaped()}, "zzz") is None
    assert recommend_source({}, "a") is None


def test_days_not_shared_are_not_compared():
    # b only has 10 days of its own forecast: 10 shared < 14, even though
    # the roof has 14 settled days.
    skip = _days(14)[10:]
    ledgers = {"a": _flat(), "b": _shaped(1.4, skip=skip)}
    assert recommend_source(ledgers, "a") is None


def test_an_outage_day_is_not_rewarded():
    # b was down on day 1; that day drops out for BOTH, so b is judged on
    # the days it answered (14 of 15), never on a gap.
    bad = _days(15)[0]
    a = _led(14.0, n=15)
    b = _shaped(1.4, n=15, skip=(bad,))
    assert recommend_source({"a": a, "b": b}, "a")["days"] == 14


def test_today_with_a_growing_actual_is_skipped():
    ledgers = {"a": _led(14.0, n=14), "b": _shaped(1.4, n=14)}
    assert recommend_source(ledgers, "a", today=_days(14)[-1]) is None


def test_tomorrow_rides_along_only_with_enough_days():
    a, b = _flat(), _shaped(1.4)
    for d in _days(14):
        a.record(d, 1, 14.0)
        b.record(d, 1, _act(d) * 1.4)
    assert recommend_source({"a": a, "b": b}, "a")["tomorrow_by_pct"] > 90
    assert recommend_source({"a": _flat(), "b": _shaped(1.4)}, "a")["tomorrow_by_pct"] is None


def test_the_coordinator_publishes_advice_and_repoints_nothing():
    reader = SimpleNamespace(source="a")
    coord = SimpleNamespace(
        _forecast_reader=reader,
        _source_ledgers={"a": _flat(), "b": _shaped(1.4)},
    )
    rec = SEMCoordinator.source_recommendation(coord)
    assert rec["source"] == "b"
    assert reader.source == "a"
    coord._forecast_reader = SimpleNamespace(source=None)
    assert SEMCoordinator.source_recommendation(coord) is None


# (#924) the sensor attributes and the card path are covered by behaviour:
# dashboard/card/test/forecast-recommend.test.js, not by source text.


ACTUAL = [12.5, 6.9, 2.5, 5.2, 5.4, 9.5, 12.2, 13.9, 2.9, 8.6, 6.2, 4.7, 16.1, 14.0, 14.0, 10.2]
FCSOLAR = [18.5, 13.0, 12.8, 12.7, 18.5, 11.9, 11.7, 27.1, 11.9, 11.6, 11.3, 11.2, 26.0, 28.6, 12.1, 10.5]
OPENMETEO = [18.2, 11.3, 6.7, 10.9, 12.9, 10.2, 12.0, 30.1, 2.9, 6.2, 5.4, 5.5, 24.9, 22.1, 13.6, 8.6]


def _series(fcs, actuals=ACTUAL):
    led = ForecastLedger()
    for d, f, a in zip(_days(len(actuals)), fcs, actuals, strict=True):
        led.record(d, 0, f)
        led.settle(d, a)
    return led


def test_real_data_six_percent_apart_is_no_recommendation():
    from custom_components.solar_energy_management.coordinator.forecast_ledger import (
        _shared_mae,
    )
    fc, om = _series(FCSOLAR), _series(OPENMETEO)
    (e_fc, e_om), n = _shared_mae(fc, om, 0, None)
    assert n == 16 and abs(e_fc - 3.15) < 0.05 and abs(e_om - 2.97) < 0.05
    assert recommend_source({"fc": fc, "om": om}, "fc") is None


def test_a_source_that_is_the_other_times_half_is_not_better():
    full = _series(FCSOLAR)
    half = _series([f * 0.5 for f in FCSOLAR])
    assert recommend_source({"a": full, "b": half}, "a") is None


def test_a_clearly_better_shape_is_recommended():
    shaped = _series([a * 1.8 for a in ACTUAL])   # wrong size, right shape
    rec = recommend_source({"fc": _series(FCSOLAR), "s": shaped}, "fc")
    assert rec["source"] == "s" and rec["days"] == 16 and rec["by_pct"] > 90
