"""#1408 — the house's grid kWh per hour survive the size trim.

The Plan card's headline counts the house's grid kWh from now to the end of
its chart. It read them from the plan's slots. When the plan is too big for
the recorder, ``_energy_plan_attrs`` sends ``slots: []`` (``timeline_omitted``),
and the card fell back to the whole plan's ``house_grid`` total: at 03:00 a
plan made at 22:00 still counted the house from 22:00, and the Today view
counted the hours after midnight.

The trim now sends ``house_grid_hours`` (kWh per hour) and ``batt_times``
(where the battery covers the house, by time), read from the FULL slots.
No trim step below drops them. ``dashboard/card/test/plan-house-hours.test.js``
reads the same fixture on the card side.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from custom_components.solar_energy_management import sensor as sensor_mod
from custom_components.solar_energy_management.sensor import (
    _PLAN_ATTR_BUDGET_BYTES,
    _batt_times,
    _energy_plan_attrs,
    _house_grid_hours,
)

from .test_1406_plan_end_kept import _day_plan
from .test_638_plan_surface import _size, _synthetic_plan
from .test_638_shadow_mode import freeze_targets  # noqa: F401 — fixture

FIXTURE = Path(__file__).resolve().parent.parent / (
    "dashboard/card/test/fixtures/house-hours-1408.json")


def _hours_sum(h):
    return sum(h["kwh"])


def test_the_report_a_trimmed_plan_keeps_the_house_per_hour(freeze_targets, monkeypatch):
    """The real planner by day: the house draws from the grid 20:00 – 02:00.
    Too big for the sensor, the slots go; the hours stay and add up to the
    plan's own total, hour by hour."""
    plan, _ = _day_plan(monkeypatch, hour=9, minute=0)
    assert plan["house_grid"]["kwh"] > 1, "the plan has no house grid draw; the test proves nothing"
    monkeypatch.setattr(sensor_mod, "_PLAN_ATTR_BUDGET_BYTES", 1500)
    attrs = _energy_plan_attrs(plan)
    assert attrs["timeline_omitted"] is True and attrs["slots"] == []
    hours = attrs["house_grid_hours"]
    assert hours["start"] == plan["slots"][0]["start"]
    assert _hours_sum(hours) == pytest.approx(plan["house_grid"]["kwh"], abs=0.01)
    # hour by hour, the slots' own energy
    t0 = datetime.fromisoformat(hours["start"])
    for i, k in enumerate(hours["kwh"]):
        lo, hi = t0 + timedelta(hours=i), t0 + timedelta(hours=i + 1)
        want = sum(
            s["home_grid_w"] / 1000.0 for s in plan["slots"]
            if lo <= datetime.fromisoformat(s["start"]) < hi)
        assert k == pytest.approx(want, abs=0.001), f"hour {i}"
    # the battery's house runs by time, from the full slots
    assert attrs["batt_times"] == _batt_times(plan["slots"])
    assert attrs["batt_times"], "the plan has no battery run; the battery part proves nothing"
    for s, e in attrs["batt_times"]:
        assert any(r["start"] == s for r in plan["slots"])
        assert any(r["end"] == e for r in plan["slots"])


def test_a_plan_that_fits_sends_its_slots_and_no_copy(freeze_targets, monkeypatch):
    """The slots carry the house per slot; a plan that fits pays no bytes twice."""
    plan, _ = _day_plan(monkeypatch, hour=9, minute=0)
    attrs = _energy_plan_attrs(plan)
    assert not attrs.get("timeline_omitted") and attrs["slots"]
    assert "house_grid_hours" not in attrs and "batt_times" not in attrs


def test_the_fixture_the_card_reads_is_what_the_sensor_sends():
    """One fixture, both sides: the card's test reads the same file."""
    fx = json.loads(FIXTURE.read_text())
    assert _house_grid_hours(fx["slots"]) == fx["house_grid_hours"]
    assert _batt_times(fx["slots"]) == fx["batt_times"]
    # by hand: the battery covers the house to 02:15, the grid from there
    assert fx["batt_times"] == [["2026-11-21T22:00:00+01:00", "2026-11-22T02:15:00+01:00"]]
    assert fx["house_grid_hours"]["runs"] == [["2026-11-22T02:15:00+01:00", "2026-11-22T07:00:00+01:00"]]
    # 02:00 – 03:00: 02:15 at 450 W, 02:30 at 500 W, 02:45 at 550 W
    assert fx["house_grid_hours"]["kwh"][4] == pytest.approx((450 + 500 + 550) * 0.25 / 1000)
    assert sum(fx["house_grid_hours"]["kwh"]) == pytest.approx(fx["house_grid"]["kwh"], abs=0.01)


@pytest.mark.parametrize("shape,blocks_kept", [
    # 190 quarter-hours: 47.5 h, inside the 48 h a list may cover
    (dict(slots=190, demands=3, blocks_per_demand=1), True),
    (dict(slots=96, demands=12, blocks_per_demand=60), False),
    (dict(slots=96, demands=40, blocks_per_demand=60), False),   # runs dropped too
])
def test_every_trim_level_keeps_the_hours(shape, blocks_kept):
    plan = _synthetic_plan(**shape)
    plan["has_battery"] = True
    for i, b in enumerate(plan["blocks"]):
        b["power_w"] = 100.0 + i          # no two touch: merging cannot save it
    attrs = _energy_plan_attrs(plan)
    assert attrs["timeline_omitted"] is True and attrs["slots"] == []
    assert bool(attrs["blocks"]) is blocks_kept, "the shape did not reach its trim level"
    assert attrs["house_grid_hours"] == _house_grid_hours(plan["slots"])
    # each hour is rounded to 1 Wh: at most half of it off per hour
    hours = attrs["house_grid_hours"]["kwh"]
    assert _hours_sum(attrs["house_grid_hours"]) == pytest.approx(
        451.7 * 0.25 * shape["slots"] / 1000, abs=0.0005 * len(hours))
    assert attrs["batt_times"] == []          # no slot marked: no run, not None
    assert _size(attrs) <= _PLAN_ATTR_BUDGET_BYTES


def test_the_last_trim_step_keeps_the_hours(monkeypatch):
    plan = _synthetic_plan(slots=96, demands=3, blocks_per_demand=4)
    monkeypatch.setattr(sensor_mod, "_PLAN_ATTR_BUDGET_BYTES", 1200)
    attrs = _energy_plan_attrs(plan, extra={"review": {"rows": ["x" * 400] * 3}})
    assert attrs.get("extras_omitted") is True, "the last step was not reached"
    assert attrs["house_grid_hours"] == _house_grid_hours(plan["slots"])


def test_a_plan_from_before_1063_sends_no_battery_times():
    """No ``has_battery``: the plan never marked a slot. None, as ``batt_runs``
    is, so the card keeps its old drawing."""
    plan = _synthetic_plan(slots=190, demands=3, blocks_per_demand=1)
    attrs = _energy_plan_attrs(plan)
    assert attrs["timeline_omitted"] is True
    assert attrs["batt_times"] is None


TZ1 = timezone(timedelta(hours=1))


def _row(start, minutes, w, **kw):
    return {"start": start.isoformat(),
            "end": (start + timedelta(minutes=minutes)).isoformat(),
            "home_grid_w": w, **kw}


def test_a_slot_across_an_hour_is_split_by_time():
    t = datetime(2026, 11, 21, 22, 45, tzinfo=TZ1)
    h = _house_grid_hours([_row(t, 30, 1000.0)])
    assert h["start"] == "2026-11-21T22:00:00+01:00"
    assert h["kwh"] == [0.25, 0.25]


def test_hours_count_from_the_first_slot_by_time_not_by_order():
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    rows = [_row(t + timedelta(hours=1), 60, 500.0), _row(t, 60, 300.0)]
    assert _house_grid_hours(rows) == {
        "start": "2026-11-21T22:00:00+01:00", "kwh": [0.3, 0.5],
        "runs": [[rows[1]["start"], rows[0]["end"]]]}


def test_the_autumn_clock_change_keeps_every_hour():
    """02:00+02:00 and 02:00+01:00 are two hours. Hours run on real time."""
    rows = [
        {"start": "2026-10-25T01:00:00+02:00", "end": "2026-10-25T02:00:00+02:00", "home_grid_w": 100.0},
        {"start": "2026-10-25T02:00:00+02:00", "end": "2026-10-25T02:00:00+01:00", "home_grid_w": 200.0},
        {"start": "2026-10-25T02:00:00+01:00", "end": "2026-10-25T03:00:00+01:00", "home_grid_w": 300.0},
    ]
    h = _house_grid_hours(rows)
    assert h["start"] == "2026-10-25T01:00:00+02:00"
    assert h["kwh"] == [0.1, 0.2, 0.3]


def test_a_zone_off_the_whole_hour_starts_on_its_own_hour():
    """India is +05:30: the first hour starts at 22:00 there, not at 21:30."""
    tz = timezone(timedelta(hours=5, minutes=30))
    h = _house_grid_hours([_row(datetime(2026, 11, 21, 22, 15, tzinfo=tz), 45, 800.0)])
    assert h["start"] == "2026-11-21T22:00:00+05:30"
    assert h["kwh"] == [0.6]


@pytest.mark.parametrize("w", [None, "abc", float("nan"), -500.0, [1]])
def test_no_draw_counts_zero(w):
    """Export, a gap or garbage is no house draw: 0, never negative."""
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    assert _house_grid_hours([_row(t, 60, w)])["kwh"] == [0.0]


@pytest.mark.parametrize("slots", [
    [], None, "not a list",
    [{"start": "x", "end": "not a time", "home_grid_w": 400}],
    [{"start": "2026-11-21T22:00:00", "end": "2026-11-22T07:00:00", "home_grid_w": 400}],   # no zone
    [{"start": "2026-11-21T23:00:00+01:00", "end": "2026-11-21T22:00:00+01:00", "home_grid_w": 400}],
    ["not a row", 5, None],
])
def test_no_readable_slot_sends_none(slots):
    assert _house_grid_hours(slots) is None


def test_a_bad_row_beside_good_ones_is_skipped():
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    rows = [_row(t, 60, 400.0), {"start": "x", "end": "y", "home_grid_w": 9999}]
    assert _house_grid_hours(rows)["kwh"] == [0.4]


def test_a_row_days_away_sends_none():
    """A wrong date must not grow a long list: None past two days. A real
    plan (now to the next night end) stays well inside."""
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    rows = [_row(t, 60, 400.0), _row(t + timedelta(hours=47), 60, 400.0)]
    assert len(_house_grid_hours(rows)["kwh"]) == 48
    rows = [_row(t, 60, 400.0), _row(t + timedelta(hours=48), 60, 400.0)]
    assert _house_grid_hours(rows) is None


def test_the_runs_say_when_the_house_draws():
    """Touching drawing slots join; a slot with no draw ends a run; rows
    that overlap give one run to the later end."""
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    q = timedelta(minutes=15)
    rows = [_row(t + i * q, 15, w) for i, w in enumerate([0, 300, 300, 450, 0, 0, 200])]
    h = _house_grid_hours(rows)
    assert h["runs"] == [[rows[1]["start"], rows[3]["end"]], [rows[6]["start"], rows[6]["end"]]]
    assert h["kwh"] == [round((300 + 300 + 450) * 0.25 / 1000, 3), 0.05]
    over = [_row(t, 60, 100.0), _row(t + timedelta(minutes=30), 60, 100.0)]
    assert _house_grid_hours(over)["runs"] == [[over[0]["start"], over[1]["end"]]]
    assert _house_grid_hours([_row(t, 60, 0.0)])["runs"] == []


def test_battery_times_follow_the_marked_slots():
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    rows = [_row(t + timedelta(hours=i), 60, 0.0, **({"batt": True} if i in (0, 1, 4) else {}))
            for i in range(6)]
    assert _batt_times(rows) == [
        [rows[0]["start"], rows[1]["end"]], [rows[4]["start"], rows[4]["end"]]]
    assert _batt_times(None) == [] and _batt_times("x") == []
    # a marked row without times names no run
    assert _batt_times([{"batt": True}]) == []


def test_too_many_runs_are_left_out():
    """Draw on and off every quarter-hour: past 24 runs the list goes, the
    hours stay, and the card spreads over whole hours."""
    t = datetime(2026, 11, 21, 22, 0, tzinfo=TZ1)
    q = timedelta(minutes=15)
    rows = [_row(t + i * q, 15, 400.0 if i % 2 == 0 else 0.0) for i in range(48)]
    assert len(_house_grid_hours(rows[:47])["runs"]) == 24
    h = _house_grid_hours(rows + [_row(t + 48 * q, 15, 400.0)])
    assert h["runs"] == []
    assert sum(h["kwh"]) == pytest.approx(25 * 0.1, abs=0.001)
