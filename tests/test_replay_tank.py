"""#1369 — the replay judges the hot water tank too.

A small synthetic day (built here, never from the corpus) with a tank is
replayed through the REAL ``HotWaterController``. Same trees give "same as
base"; a changed rule in the branch copy shows the first differing row; a
day with no tank role is skipped cleanly.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from custom_components.solar_energy_management.devices import hot_water_controller as hwc
from custom_components.solar_energy_management.tools.replay import invariants as inv
from custom_components.solar_energy_management.tools.replay.engine import replay_day
from custom_components.solar_energy_management.tools.replay.recorded_day import (
    ROLES, RecordedDay,
)

TZ = "Europe/Zurich"
DATE = "2026-06-15"


def _t(hour: float) -> float:
    d = datetime.fromisoformat(DATE).replace(tzinfo=ZoneInfo(TZ))
    return d.timestamp() + hour * 3600.0


def _day(*, tank: bool = True) -> RecordedDay:
    """Sun 07-19 h, 4.5 kW export 10-15 h; the water warms 45 -> 57 °C over
    the export hours and cools slowly after."""
    solar, grid, temp = [], [], []
    for h10 in range(0, 240, 5):                      # every half hour
        h = h10 / 10.0
        sun = 4000.0 if 7 <= h < 19 else 0.0
        solar.append((_t(h), sun))
        grid.append((_t(h), 4500.0 if 10 <= h < 15 else -300.0))
        temp.append((_t(h), 45.0 + 12.0 * min(max(h - 10.0, 0.0), 5.0) / 5.0
                     - 0.3 * max(h - 15.0, 0.0)))
    series = {"solar_power": solar, "grid_power": grid,
              "battery_power": [(_t(0), 0.0)]}
    if tank:
        series["tank_temp"] = temp
    return RecordedDay(date=DATE, tz=TZ, cycle_s=60, series=series,
                       tags={"tags": ["sunny"]})


def test_the_role_is_a_known_one():
    assert ROLES["tank_temp"] == "hot_water_current_temperature"


def test_the_tank_switches_on_for_the_sun_and_off_at_the_top():
    run = replay_day(_day())
    assert run.tank, "a recorded tank gives would-send rows"
    ons = [r for r in run.tank if r[2] == "on"]
    assert ons and 10 <= (ons[0][0] - _t(0)) / 3600.0 <= 11, run.tank
    assert run.tank[-1][2] == "off"
    assert run.writes == 0 and run.decision_error == ""


def test_identical_trees_are_the_same_as_base():
    a, b = replay_day(_day()), replay_day(_day())
    r = inv.tank_commands(a, b)
    assert r.ok and r.evidence_n == len(a.tank) > 0
    assert r.detail.endswith("would-send rows, same as base")


def test_a_replay_does_not_depend_on_the_wall_clock():
    day = _day()
    with patch.object(hwc.dt_util, "now", return_value=datetime(2031, 1, 1, tzinfo=ZoneInfo(TZ))):
        later = replay_day(day)
    assert later.tank == replay_day(day).tank


def test_a_changed_rule_shows_the_first_differing_row():
    base = replay_day(_day())
    with patch.object(hwc.HotWaterController, "band_top_c", return_value=50.0):
        branch = replay_day(_day())
    r = inv.tank_commands(branch, base)
    assert not r.ok and r.kind == "exact" and r.evidence_n
    assert "differ; first at row" in r.detail
    assert r.evidence[0]["branch"] != r.evidence[0]["base"]


def test_a_day_without_a_tank_simulates_one():
    run = replay_day(_day(tank=False))
    assert run.tank_mode == "simulated" and run.tank and run.decision_error == ""
    assert any(r[2] == "on" for r in run.tank), "real sun heats the simulated tank"
    assert replay_day(_day(tank=False)).tank == run.tank
    assert inv.tank_commands(run, replay_day(_day(tank=False))).detail.endswith("same as base")


def test_a_recorded_temperature_still_uses_the_recorded_path():
    run = replay_day(_day())
    assert run.tank_mode == "recorded"


def test_a_day_with_nothing_to_simulate_on_is_skipped_cleanly():
    day = _day(tank=False)
    day.series.pop("grid_power")
    run = replay_day(day)
    assert run.tank is None and run.decision_error == ""
    for r in (inv.tank_commands(run, run), inv.tank_sanity(run, run)):
        assert r.ok and r.evidence_n == 0 and "skipped" in r.detail


def test_the_simulated_tank_heats_cools_and_stays_bounded():
    from custom_components.solar_energy_management.tools.replay import tank as T
    t = 40.0
    for _ in range(360):                       # one hour on
        t = T.sim_step(t, True, 10.0)
    assert 40.0 + 8.0 < t < 40.0 + 9.2, t        # 3.2 kWh / 0.35 kWh/K ~ 9 K, less loss
    hot = T.sim_step(55.0, False, 3600.0)
    assert hot < 55.0 and 55.0 - hot < 0.2      # loss only, a slow fall
    assert T.sim_draw(55.0, 60.0) < 55.0 - 7.0  # a draw cools it
    assert T.SIM_COLD_C <= T.sim_draw(55.0, 300.0) <= 55.0
    run = replay_day(_day(tank=False))
    assert run.tank_faults == [], run.tank_faults


def test_a_changed_rule_shows_a_difference_on_a_simulated_day():
    base = replay_day(_day(tank=False))
    with patch.object(hwc.HotWaterController, "band_top_c", return_value=50.0):
        branch = replay_day(_day(tank=False))
    r = inv.tank_commands(branch, base)
    assert not r.ok and "first at row" in r.detail


def test_a_tank_that_stays_on_above_its_top_is_caught():
    mine = replay_day(_day())
    mine.tank_faults = [{"kind": "over_top", "t": 1, "temp_c": 57.0, "limit_c": 56.0}]
    r = inv.tank_sanity(mine, replay_day(_day()))
    assert not r.ok and r.kind == "relative" and r.evidence[0]["kind"] == "over_top"
    # a stretch the base shows too is shared, not blamed
    base = replay_day(_day())
    base.tank_faults = list(mine.tank_faults)
    assert inv.tank_sanity(mine, base).ok


def _always(on):
    from custom_components.solar_energy_management.coordinator import surplus_controller as sc
    return patch.object(sc, "compute_load_intent",
                        lambda *a, **k: sc.LoadIntent(on, 0.0, None, "forced"))


def test_a_rule_that_never_stops_is_a_fault_in_the_replay_itself():
    with _always(True):
        run = replay_day(_day())
    assert {f["kind"] for f in run.tank_faults} == {"over_top"}
    assert not inv.tank_sanity(run, None).ok


def test_a_rule_that_never_heats_a_cold_tank_is_a_fault_in_the_replay_itself():
    day = _day()
    day.series["tank_temp"] = [(_t(0), 30.0)]
    with _always(False):
        run = replay_day(day)
    assert {f["kind"] for f in run.tank_faults} == {"too_cold"}


def test_the_sane_day_has_no_fault():
    run = replay_day(_day())
    assert run.tank_faults == [], run.tank_faults
