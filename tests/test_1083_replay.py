"""#1083 — the replay engine runs the REAL code, and every check can fail.

Fixtures are two short windows of PROD's 13.10.2026, moved to 2026-09-15
(same clock hours): the sunny morning that #1104 over-planned, and the
21:30 battery stop that showed 3064 W of home for 30 s (#1105). The tests
do not depend on whether those fixes are merged: they prove the engine
and the checks, not today's code.
"""
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator import forecast_tracker as ft
from custom_components.solar_energy_management.tools.replay import invariants as inv
from custom_components.solar_energy_management.tools.replay.engine import (
    DayRun,
    replay_day,
    replay_forecast,
    replay_home,
)
from custom_components.solar_energy_management.tools.replay.recorded_day import (
    RecordedDay,
    from_history,
    load_day,
)

FIX = Path(__file__).parent / "fixtures" / "replay"


def _fixture(name):
    return load_day(next((FIX / name).glob("*.json.gz")))


# ── the engine drives the real code ──────────────────────────────────────

def test_the_forecast_path_is_the_real_tracker(monkeypatch):
    """Break the real ForecastTracker and the replay must see it."""
    day = _fixture("sunny_morning")
    good = DayRun(date=day.date, tags=[])
    monkeypatch.setattr(ft.ForecastTracker, "corrected_factor", lambda self: 1.0)
    replay_forecast(day, good)
    assert good.forecast and inv.forecast_overshoot(good).ok

    bad = DayRun(date=day.date, tags=[])
    monkeypatch.setattr(ft.ForecastTracker, "corrected_factor", lambda self: 1.5)
    replay_forecast(day, bad)
    r = inv.forecast_overshoot(bad)
    assert not r.ok and r.evidence


def test_the_shown_home_path_is_the_real_hold():
    """A battery reading that goes dark: the real #1047 hold keeps the
    last shown home instead of showing the whole solar as home."""
    tz = "Europe/Zurich"
    from datetime import datetime
    from zoneinfo import ZoneInfo
    t0 = datetime(2026, 9, 15, 12, tzinfo=ZoneInfo(tz)).timestamp()
    day = from_history("2026-09-15", tz, {
        "solar_power": [(t0, "4700")],
        "grid_power": [(t0, "0")],
        "battery_power": [(t0, "3900"), (t0 + 60, "unavailable"), (t0 + 90, "3900")],
        "ev_power": [(t0, "0")],
    })
    run = DayRun(date=day.date, tags=[])
    replay_home(day, run, (t0, t0 + 120))
    shown = {round(t - t0): s for t, s, _r, _d in run.home}
    assert shown[50] == pytest.approx(800.0)
    assert shown[70] == pytest.approx(800.0)        # held, not 4700
    assert run.writes == 0


def test_a_whole_day_is_one_day_in_memory_and_writes_nothing():
    run = replay_day(_fixture("battery_stop"))
    assert run.home and run.writes == 0


# ── every check can fail ─────────────────────────────────────────────────

def _recorded_home_run(day: RecordedDay) -> DayRun:
    """A run whose shown home IS what PROD recorded — independent of code."""
    run = DayRun(date=day.date, tags=[])
    for c in day.cycles():
        v = c.values.get("home_power")
        if v is not None:
            run.home.append((c.t, v, v, False))
    return run


def test_the_spike_check_finds_prods_21_30_spike():
    day = _fixture("battery_stop")
    spikes = inv.home_spikes(_recorded_home_run(day))
    assert any(s["before_w"] == 1537 and s["spike_w"] == 3064 for s in spikes)


def test_a_real_load_that_stays_is_not_a_spike():
    run = DayRun(date="d", tags=[], home=[(i * 10, 500.0 if i < 5 else 2500.0, None, False)
                                          for i in range(30)])
    assert inv.home_spikes(run) == []


def test_relative_check_blames_only_new_spikes():
    spike = [(i * 10, 3000.0 if i == 5 else 600.0, None, False) for i in range(20)]
    flat = [(i * 10, 600.0, None, False) for i in range(20)]
    base_with, base_without = DayRun("d", [], home=spike), DayRun("d", [], home=flat)
    assert inv.home_spike_regression(DayRun("d", [], home=flat), base_with).ok   # fixed
    assert inv.home_spike_regression(DayRun("d", [], home=spike), base_with).ok  # shared
    assert not inv.home_spike_regression(DayRun("d", [], home=spike), base_without).ok


def test_no_writes_fails_on_a_write():
    assert not inv.no_writes(DayRun("d", [], writes=1)).ok


def test_gap_days_and_inherited_failures_never_block():
    bad = inv.Result("forecast_overshoot", "exact", False)
    assert inv.blocking({"forecast_overshoot": bad}, ["gap"]) == []
    assert inv.blocking({"forecast_overshoot": bad}, ["sunny"],
                        {"forecast_overshoot": inv.Result("forecast_overshoot", "exact", False)}) == []
    assert inv.blocking({"forecast_overshoot": bad}, ["sunny"],
                        {"forecast_overshoot": inv.Result("forecast_overshoot", "exact", True)}) == [bad]
    modelled = inv.Result("grid_limit", "modelled", False)
    assert inv.blocking({"grid_limit": modelled}, ["sunny"]) == []


# ── memory: one day at a time, never the whole corpus ──────────────────

def test_run_tree_holds_one_day_at_a_time(monkeypatch, capsys):
    """run_tree loads a day, writes it out and drops it before the next:
    never two days alive at once."""
    import gc
    import weakref
    from custom_components.solar_energy_management.tools.replay import run_tree as rt

    src = next((FIX / "battery_stop").glob("*.json.gz"))
    alive, peak = [], [0]
    real_load = rt.load_day

    def _load(p):
        alive[:] = [r for r in alive if r() is not None]
        gc.collect()
        alive[:] = [r for r in alive if r() is not None]
        peak[0] = max(peak[0], len(alive) + 1)
        day = real_load(p)
        alive.append(weakref.ref(day))
        return day

    monkeypatch.setattr(rt, "load_day", _load)
    assert rt.main([str(src)] * 4) == 0
    assert peak[0] == 1
    assert len(capsys.readouterr().out.strip().splitlines()) == 4


def test_one_replayed_day_stays_under_a_memory_budget():
    """A whole day through the engine: well under 300 MB of new memory."""
    import tracemalloc
    tracemalloc.start()
    replay_day(_fixture("sunny_morning"))
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 300 * 1024 * 1024
