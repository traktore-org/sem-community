"""#1083 — the replay tool feeds the Simulation tab's model.

A recorded 10-s day adds up into the model's 24 hours, and the model
re-prices that day to its recorded cost (``cost_identity``). The check is
``modelled``: it is reported when a 15-min price curve pulls the two
apart, never blocking.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.tools.replay import invariants as inv
from custom_components.solar_energy_management.tools.replay.engine import (
    DayRun,
    replay_day,
)
from custom_components.solar_energy_management.tools.replay.hourly import (
    day_costs,
    recorded_day_to_hourly,
)
from custom_components.solar_energy_management.tools.replay.recorded_day import (
    RecordedDay,
)

TZ = "Europe/Zurich"
DATE = "2026-09-15"


def _t(hour, minute=0):
    return datetime(2026, 9, 15, hour, minute, tzinfo=ZoneInfo(TZ)).timestamp()


def _day(series, tags=("mixed",)):
    return RecordedDay(date=DATE, tz=TZ, cycle_s=10, series=series,
                       tags={"tags": list(tags)})


def _plain_series(price=0.30):
    """Import 500 W all day; sun 2000 W 10–14; battery charges 1000 W in
    hour 11; SOC 40 % then 60 % from 12:00."""
    return {
        "solar_power": [(_t(0), 0.0), (_t(10), 2000.0), (_t(14), 0.0)],
        "grid_power": [(_t(0), -500.0)],
        "battery_power": [(_t(0), 0.0), (_t(11), 1000.0), (_t(12), 0.0)],
        "battery_soc": [(_t(0), 40.0), (_t(12), 60.0)],
        "import_price": [(_t(0), price)],
    }


def test_hourly_sums_match_the_recorded_day():
    hd = recorded_day_to_hourly(_day(_plain_series()))
    assert hd.date == DATE and hd.tags == ["mixed"]
    assert hd.grid_import == pytest.approx([0.5] * 24)
    assert hd.solar[10] == pytest.approx(2.0) and hd.solar[9] == 0.0
    assert hd.total("solar") == pytest.approx(8.0)
    assert hd.battery_charge[11] == pytest.approx(1.0)
    assert hd.total("battery_charge") == pytest.approx(1.0)
    assert hd.ev == [0.0] * 24 and hd.grid_export == [0.0] * 24
    # SEM's balance: hour 11 = 2.0 sun + 0.5 grid − 1.0 battery
    assert hd.home[11] == pytest.approx(1.5)
    assert hd.home[3] == pytest.approx(0.5)
    assert hd.soc_pct[0] == pytest.approx(40.0) and hd.soc_pct[12] == pytest.approx(60.0)
    assert hd.import_rate == pytest.approx([0.30] * 24)
    assert hd.missing_hours == []


def test_a_dark_grid_hour_is_missing_and_tags_can_be_given():
    s = _plain_series()
    s["grid_power"] = [(_t(0), -500.0), (_t(5), None), (_t(6), -500.0)]
    hd = recorded_day_to_hourly(_day(s), tags=["grey"])
    assert hd.missing_hours == [5] and hd.tags == ["grey"]
    assert hd.grid_import[5] == 0.0


def test_a_day_with_no_grid_reading_is_missing_every_hour():
    s = _plain_series()
    del s["grid_power"]
    assert recorded_day_to_hourly(_day(s)).missing_hours == list(range(24))


def test_cost_identity_holds_on_flat_prices():
    day = _day(_plain_series(price=0.30))
    fine, coarse = day_costs(day)
    assert fine == pytest.approx(0.5 * 24 * 0.30)
    assert coarse == pytest.approx(fine)
    run = DayRun(date=DATE, tags=["mixed"], cost=(fine, coarse))
    r = inv.cost_identity(run)
    assert r.ok and r.kind == "modelled"


def _quarter_curve_series():
    """15-min prices 0.10 / 0.50 by turns; the house imports 2000 W only
    in the dear quarter of every hour — the load moves inside the hour."""
    price, grid = [], []
    for h in range(24):
        for q, p in enumerate((0.10, 0.50, 0.10, 0.50)):
            price.append((_t(h, 15 * q), p))
        grid += [(_t(h, 0), 0.0), (_t(h, 15), -2000.0), (_t(h, 30), 0.0)]
    return {"solar_power": [(_t(0), 0.0)], "grid_power": grid, "import_price": price}


def test_cost_identity_is_reported_not_blocking_on_a_15_min_curve():
    day = _day(_quarter_curve_series())
    fine, coarse = day_costs(day)
    assert fine == pytest.approx(0.5 * 24 * 0.50)      # what the meter saw
    assert coarse == pytest.approx(0.5 * 24 * 0.30)    # the hour's mean price
    run = replay_day(day)
    res = inv.check(run)
    r = res["cost_identity"]
    assert not r.ok and r.kind == "modelled" and r.evidence
    assert inv.blocking(res, run.tags) == []


def test_no_price_recorded_says_so():
    s = _plain_series()
    del s["import_price"]
    run = replay_day(_day(s))
    assert run.cost is None
    assert any("no import price" in n for n in run.notes)
    assert inv.cost_identity(run).ok
