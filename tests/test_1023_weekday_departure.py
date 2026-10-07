"""#1023 A1 — a departure time per weekday.

A charger may leave at a different time on each day of the week:
``ev_departure_by_weekday`` maps ``mon`` … ``sun`` to ``HH:MM``, and a day
left empty leaves at the charger's own ``ev_target_time`` (the default,
which also stays the boundary its EV day rolls at). The resolver picks the
next departure after now, so a night plan made on Sunday evening plans for
Monday morning.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.departure import (
    departure_for,
    departure_hhmm,
    departure_signature,
    weekday_departures,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    plan_night_charge,
)

from .ast_contracts import call_kwargs, calls

ZRH = ZoneInfo("Europe/Zurich")
# 9 October 2026 is a Friday.
FRI_2200 = datetime(2026, 10, 9, 22, 0, tzinfo=ZRH)
SUN_2300 = datetime(2026, 10, 11, 23, 0, tzinfo=ZRH)

CHARGER = {
    "id": "keba",
    "ev_target_time": "07:00",
    "ev_departure_by_weekday": {
        "mon": "06:15", "tue": "06:15", "wed": "", "thu": "06:15",
        "fri": "06:15", "sat": "", "sun": "",
    },
}


def test_friday_night_with_saturday_empty_leaves_at_the_default():
    assert departure_for(CHARGER, FRI_2200, {}) == datetime(
        2026, 10, 10, 7, 0, tzinfo=ZRH)


def test_sunday_night_plans_for_mondays_entry():
    assert departure_for(CHARGER, SUN_2300, {}) == datetime(
        2026, 10, 12, 6, 15, tzinfo=ZRH)


def test_a_departure_still_ahead_today_is_todays():
    monday_0500 = datetime(2026, 10, 12, 5, 0, tzinfo=ZRH)
    assert departure_for(CHARGER, monday_0500, {}) == datetime(
        2026, 10, 12, 6, 15, tzinfo=ZRH)


def test_without_weekdays_nothing_changes():
    plain = {"id": "zoe", "ev_target_time": "06:30"}
    for now in (FRI_2200, SUN_2300):
        assert departure_for(plain, now, {}).strftime("%H:%M") == "06:30"


def test_only_days_with_a_time_of_their_own_count():
    cfg = {"ev_departure_by_weekday": {
        "mon": "06:15", "tue": "", "wed": None, "thu": "soon",
        "fri": "25:00", "funday": "05:00"}}
    assert weekday_departures(cfg) == {"mon": "06:15"}
    assert weekday_departures({"ev_departure_by_weekday": "06:15"}) == {}
    assert weekday_departures({}) == {}


def test_the_default_stays_the_charger_time():
    """The EV day keeps rolling at the charger's own time (A1: the
    per-charger time stays the default)."""
    assert departure_hhmm(CHARGER, {}) == "07:00"


def test_a_departure_more_than_a_day_away_keeps_its_date():
    """Friday 06:00, Friday's 05:00 gone, Saturday leaving at 23:00: the
    next departure is 41 hours away. An HH:MM resolved from now would name
    Friday 23:00 instead."""
    cfg = {"ev_departure_by_weekday": {"fri": "05:00", "sat": "23:00"}}
    fri_0600 = datetime(2026, 10, 9, 6, 0, tzinfo=ZRH)
    dep = departure_for(cfg, fri_0600, {})
    assert dep == datetime(2026, 10, 10, 23, 0, tzinfo=ZRH)
    plan = plan_night_charge(
        now=fri_0600, remaining_to_min_kwh=5.0, min_amps=6, max_amps=16,
        watts_per_amp=230.0, target_time=dep.strftime("%H:%M"),
        night_end="07:00", deadline_at=dep)
    assert plan.deadline_dt == dep


def test_the_dst_night_departs_on_its_own_wall_clock():
    """25 October 2026: clocks go back at 03:00 in Zurich. Saturday 22:00 to
    Sunday 07:00 is nine hours on the wall and ten in fact; the departure
    carries the winter offset of its own wall time, so the planner's
    UTC-based hours (#274/M2) count ten."""
    from datetime import timezone
    sat_2200 = datetime(2026, 10, 24, 22, 0, tzinfo=ZRH)
    dep = departure_for(CHARGER, sat_2200, {})
    assert dep == datetime(2026, 10, 25, 7, 0, tzinfo=ZRH)
    assert dep.utcoffset() == timedelta(hours=1)
    real = dep.astimezone(timezone.utc) - sat_2200.astimezone(timezone.utc)
    assert real == timedelta(hours=10)


def test_the_night_plan_is_given_the_departure_as_a_moment():
    from custom_components.solar_energy_management.coordinator import ev_control
    assert calls(EVControlMixin._compute_night_plan, "departure_for")
    kwargs = call_kwargs(EVControlMixin._compute_night_plan, "plan_night_charge")
    assert any("deadline_at" in k for k in kwargs), kwargs
    assert ev_control.departure_for is departure_for


def test_tonights_window_ends_at_tomorrows_weekday_time():
    """Sunday afternoon, night 22:00–07:00: Monday leaves at 06:15, so
    tonight delivers for 8.25 hours, not the nine to the window's end."""
    tm = MagicMock()
    tm.get_night_window.return_value = ("22:00", "07:00")
    tm.get_night_window_hours.return_value = 9.0
    host = SimpleNamespace(config={}, time_manager=tm)
    cfg = {**CHARGER, "ev_max_current": 16, "ev_phases": 1, "ev_voltage": 230}
    sunday_1400 = datetime(2026, 10, 11, 14, 0, tzinfo=ZRH)
    with patch("custom_components.solar_energy_management.coordinator."
               "ev_control.dt_util.now", return_value=sunday_1400):
        kwh = EVControlMixin._night_deliverable_kwh(host, cfg)
    assert kwh == pytest.approx(8.25 * 16 * 230 / 1000)


def test_editing_a_weekday_replans_and_the_clock_does_not():
    before = departure_signature(CHARGER, {})
    edited = {**CHARGER, "ev_departure_by_weekday": {
        **CHARGER["ev_departure_by_weekday"], "sat": "09:00"}}
    assert departure_signature(edited, {}) != before
    assert departure_signature(CHARGER, {}) == before
    assert calls(SEMCoordinator._energy_plan_demand_signature,
                 "departure_signature")


def test_the_cards_write_path_keeps_the_map():
    """The Config card writes per-charger settings through ``set_option``,
    merged by charger id (#464): the map arrives whole and a sibling keeps
    its own."""
    from custom_components.solar_energy_management import (
        _merge_ev_chargers_by_id,
    )
    stored = [{"id": "keba", "ev_target_time": "07:00"},
              {"id": "zoe", "ev_departure_by_weekday": {"mon": "08:00"}}]
    week = {"mon": "06:15", "sat": ""}
    merged = _merge_ev_chargers_by_id(
        stored, [{"id": "keba", "ev_departure_by_weekday": week}])
    by_id = {c["id"]: c for c in merged}
    assert by_id["keba"]["ev_departure_by_weekday"] == week
    assert by_id["keba"]["ev_target_time"] == "07:00"
    assert by_id["zoe"]["ev_departure_by_weekday"] == {"mon": "08:00"}
