"""#1308 — the night plan counted hours after the night window's end.

@Elmardus: SmartEVSE, one phase, 28 A, Kona 64 kWh, 80 % by 08:15, Night
latest end 07:00, Solar + cheapest hours. The car plugged in at 00:20 owing
about 48.6 kWh. The night plan sized the charge and judged it reachable
against 08:15, so neither the card nor a notification said the target would
be missed. At 07:00 night charging ended (by design: the day is spare sun
only), 15.7 kWh short.

Night charging stops at the window's end, and the joint plan and the
night-deliverable gate already plan to it. The reactive night plan now
counts only the hours the night can charge in (``night_charge_end``): the
current is sized to finish by 07:00, "reachable" is false when it cannot,
and a cheap-hour hold picks its start from those hours too.
"""
from __future__ import annotations

import ast
import math
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    NightChargePlan,
    affordable_start,
    night_charge_end,
    plan_night_charge,
    window_charge_end,
)

from .ast_contracts import _callee_name, call_kwargs

AMS = ZoneInfo("Europe/Amsterdam")
ENDS = {"night_charge_end", "window_charge_end"}
WPA_1P = 230.0                    # one phase × 230 V
PLUG_IN = datetime(2026, 11, 4, 0, 20, tzinfo=AMS)
DEPARTURE = datetime(2026, 11, 4, 8, 15, tzinfo=AMS)
NIGHT_END = datetime(2026, 11, 4, 7, 0, tzinfo=AMS)


def _reporter_plan(now=PLUG_IN, need=48.6, **kw):
    args = dict(
        now=now, remaining_to_min_kwh=need, min_amps=6, max_amps=28,
        watts_per_amp=WPA_1P, target_time="08:15", night_end="07:00",
        night_start="20:30", tariff_optimized=True, peak_managed_amps=28,
        deadline_at=DEPARTURE,
    )
    args.update(kw)
    return plan_night_charge(**args)


# ── the reporter's night ────────────────────────────────────────────────

def test_the_reporters_night_is_not_reachable_by_the_window_end():
    """28 A × 230 V × 6 h 40 min is 42.9 kWh, under 48.6. Counted to 08:15
    (7 h 55 min, 51.0 kWh) it read as on track and nothing warned."""
    plan = _reporter_plan()
    assert plan.charge_end_dt == NIGHT_END
    assert plan.hours_to_deadline == pytest.approx(6.67, abs=0.01)
    assert plan.reachable is False
    assert plan.should_warn_unreachable is True
    assert plan.deadline_amps == 28
    # The card still shows the user's own time.
    assert plan.deadline_dt == DEPARTURE


def test_at_0659_the_floor_is_the_charger_max():
    plan = _reporter_plan(now=datetime(2026, 11, 4, 6, 59, tzinfo=AMS),
                          need=15.7)
    assert plan.deadline_amps == 28
    assert plan.reachable is False


def test_the_floor_is_sized_to_finish_by_the_window_end():
    """30 kWh from 00:20: 17 A was enough for 08:15 but delivers only 26 kWh
    by 07:00, when charging stops. The floor now delivers the 30 kWh."""
    plan = _reporter_plan(need=30.0)
    hours = (NIGHT_END - PLUG_IN).total_seconds() / 3600.0
    assert plan.deadline_amps == math.ceil(30_000 / hours / WPA_1P) == 20
    assert plan.deadline_amps * WPA_1P * hours / 1000.0 >= 30.0
    # what the old count gave, and why it missed
    old_hours = (DEPARTURE - PLUG_IN).total_seconds() / 3600.0
    old_amps = math.ceil(30_000 / old_hours / WPA_1P)
    assert old_amps == 17
    assert old_amps * WPA_1P * hours / 1000.0 < 30.0
    assert plan.reachable is True


def test_a_cheap_hour_hold_counts_only_the_night():
    """Expensive at 23:00, normal 00:00–07:00, very cheap from 07:00. Counted
    to 08:15 the hold waited until 06:14 for the cheap 07:00 hours, which SEM
    never charges in, and 6 kWh got 46 minutes. Now it starts at 00:00."""
    def level_at(t):
        if t.hour == 23:
            return "expensive"
        return "very_cheap" if t.hour >= 7 else "normal"

    now = datetime(2026, 11, 3, 23, 0, tzinfo=AMS)
    plan = _reporter_plan(now=now, need=6.0, peak_managed_amps=13,
                          max_amps=13, level_at=level_at)
    assert plan.should_wait_for_cheap is True
    assert plan.next_cheap_start == datetime(2026, 11, 4, 0, 0, tzinfo=AMS)
    # the old count: hold until 06:14, 46 minutes before charging stops
    rate_kw = 13 * WPA_1P / 1000.0
    old = affordable_start(now, DEPARTURE, 6.0, rate_kw, level_at)
    assert old == datetime(2026, 11, 4, 6, 14, tzinfo=AMS)
    assert (NIGHT_END - old).total_seconds() / 3600.0 * rate_kw < 6.0
    assert "07:00" in plan.reason


# ── what does not change ────────────────────────────────────────────────

def test_a_departure_at_the_window_end_is_unchanged():
    plan = _reporter_plan(deadline_at=NIGHT_END, target_time="07:00")
    assert plan.charge_end_dt == NIGHT_END == plan.deadline_dt


def test_an_earlier_departure_still_forces():
    early = datetime(2026, 11, 4, 5, 0, tzinfo=AMS)
    plan = _reporter_plan(deadline_at=early, target_time="05:00", need=20.0)
    assert plan.charge_end_dt == early
    assert plan.deadline_active is True


def test_a_departure_after_the_next_night_opens_counts_tonight_only():
    """Saturday 23:00, the calendar says Monday 10:00: only tonight's hours
    count, so the end is cut to Sunday 07:00 (#1309)."""
    sat = datetime(2026, 11, 7, 23, 0, tzinfo=AMS)
    monday = datetime(2026, 11, 9, 10, 0, tzinfo=AMS)
    plan = _reporter_plan(now=sat, deadline_at=monday, need=20.0)
    assert plan.charge_end_dt == datetime(2026, 11, 8, 7, 0, tzinfo=AMS)


def test_a_departure_the_day_after_the_night_stops_at_its_end():
    """Saturday 23:00, leaving Sunday 15:00: Sunday's day charges on sun
    only, so the night is all there is."""
    sat = datetime(2026, 11, 7, 23, 0, tzinfo=AMS)
    sunday = datetime(2026, 11, 8, 15, 0, tzinfo=AMS)
    plan = _reporter_plan(now=sat, deadline_at=sunday, need=20.0)
    assert plan.charge_end_dt == datetime(2026, 11, 8, 7, 0, tzinfo=AMS)


def test_the_default_on_a_summer_night_plans_to_sunrise():
    """Zero config: Charge by 07:00, Night latest end 07:00. In June the
    sun rises at 05:20, the night ends then, and so does night charging.
    The plan counted to 07:00 and sized 17 A for 30 kWh — 23 kWh by 05:20.
    The joint plan already stops at 05:20."""
    june = datetime(2026, 6, 21, 23, 0, tzinfo=AMS)
    plan = plan_night_charge(
        now=june, remaining_to_min_kwh=30.0, min_amps=6, max_amps=28,
        watts_per_amp=WPA_1P, target_time="07:00", night_end="05:20",
        night_start="22:30", peak_managed_amps=28)
    sunrise = datetime(2026, 6, 22, 5, 20, tzinfo=AMS)
    assert plan.charge_end_dt == sunrise
    assert plan.deadline_dt == datetime(2026, 6, 22, 7, 0, tzinfo=AMS)
    assert plan.deadline_amps == 21
    assert plan.deadline_amps * WPA_1P * (19 / 3) / 1000.0 >= 30.0
    assert plan.reachable is True
    assert plan.deadline_active is False


def test_the_default_on_a_winter_night_is_unchanged():
    """Sunrise after 07:00: the window ends at 07:00, the Charge by time."""
    plan = plan_night_charge(
        now=PLUG_IN, remaining_to_min_kwh=30.0, min_amps=6, max_amps=28,
        watts_per_amp=WPA_1P, target_time="07:00", night_end="07:00",
        night_start="20:30", peak_managed_amps=28)
    assert plan.charge_end_dt == plan.deadline_dt == NIGHT_END
    assert plan.deadline_amps == 20


def test_a_plan_made_before_the_window_opens_stops_at_its_end():
    """18:00, window 20:30–07:00, leaving 08:15 tomorrow: the next window
    is the one after tomorrow's 07:00, not tonight's 20:30."""
    evening = datetime(2026, 11, 3, 18, 0, tzinfo=AMS)
    plan = _reporter_plan(now=evening, deadline_at=DEPARTURE, need=20.0)
    assert plan.charge_end_dt == NIGHT_END


@pytest.mark.parametrize("now_h, want", [(14, NIGHT_END), (23, NIGHT_END)])
def test_the_day_preview_counts_the_same_night(now_h, want):
    """The preview's window opens at 20:30; at 23:00 the next 07:00 is
    still tomorrow's, at 14:00 it is too. Either way 08:15 is cut to it."""
    start = datetime(2026, 11, 3, 20, 30, tzinfo=AMS)
    end = NIGHT_END if now_h == 14 else NIGHT_END - timedelta(days=1)
    assert window_charge_end(DEPARTURE, start, end) == want
    # a departure after the next window opens is cut to this night (#1309)
    later = start + timedelta(days=1, hours=1)
    assert window_charge_end(later, start, end) == NIGHT_END
    # nothing known: the departure
    assert window_charge_end(DEPARTURE, None, None) == DEPARTURE


@pytest.mark.parametrize("dep, end, nxt, want", [
    (None, NIGHT_END, None, NIGHT_END),
    (DEPARTURE, None, None, DEPARTURE),
    (NIGHT_END - timedelta(hours=1), NIGHT_END, None,
     NIGHT_END - timedelta(hours=1)),
    (DEPARTURE, NIGHT_END, None, NIGHT_END),
    (DEPARTURE, NIGHT_END, DEPARTURE, NIGHT_END),
    (DEPARTURE, NIGHT_END, DEPARTURE - timedelta(minutes=1), NIGHT_END),  # #1309
])
def test_night_charge_end(dep, end, nxt, want):
    assert night_charge_end(dep, end, nxt) == want


# ── wiring ──────────────────────────────────────────────────────────────

class _Host(EVControlMixin):
    def __init__(self, tm):
        self.config = {"ev_target_time": "08:15"}
        self.time_manager = tm
        self._ev_device = None
        self._surplus_controller = None
        self._tariff_provider = None
        self._night_committed_w = 0.0

    def _tariff_optimized_for(self, charger_cfg):
        return True

    def _planning_peak_w(self):
        return math.inf

    def _expected_night_home_w(self, energy, window_hours=8.0):
        return 300.0


def test_the_coordinators_night_plan_stops_at_the_window_end():
    """The real ``_compute_night_plan`` reads the window from the time
    manager and hands the planner its start."""
    tm = MagicMock()
    tm.get_night_window.return_value = ("20:30", "07:00")
    tm.get_night_end_time.return_value = "07:00"
    tm.get_night_window_hours.return_value = 10.5
    cfg = {"id": "smartevse", "ev_target_time": "08:15",
           "ev_max_current": 28, "ev_phases": 1, "ev_voltage": 230}
    with patch("custom_components.solar_energy_management.coordinator."
               "ev_control.dt_util.now", return_value=PLUG_IN):
        plan = EVControlMixin._compute_night_plan(_Host(tm), cfg, 48.6)
    assert plan.deadline_dt == DEPARTURE
    assert plan.charge_end_dt == NIGHT_END
    assert plan.reachable is False


def test_the_planner_is_given_the_night_start():
    kwargs = call_kwargs(EVControlMixin._compute_night_plan, "plan_night_charge")
    assert kwargs and all("night_start" in k for k in kwargs), kwargs


@pytest.mark.asyncio
async def test_the_warning_names_when_charging_stops():
    """"can't reach its target by 07:00 — 48.6 kWh still needed in 6.7 h":
    the time and the hours agree."""
    nm = MagicMock()

    async def _notify(**kw):
        nm.sent = kw
    nm.notify_ev_deadline_unreachable = _notify
    host = MagicMock()
    host._notification_manager = nm
    host.hass = None
    plan = _reporter_plan()
    await EVControlMixin._maybe_warn_unreachable_deadline(
        host, "smartevse", {"id": "smartevse"}, plan)
    assert nm.sent["deadline"] == "07:00"
    assert nm.sent["hours_left"] == pytest.approx(6.67, abs=0.01)


def test_every_cheap_start_counts_only_the_night():
    """Class guard: every ``affordable_start`` call in the package takes its
    end from ``night_charge_end`` / ``window_charge_end`` — directly, or
    through a name bound only to one in the same function. The behaviour
    tests above pin what those return."""
    root = Path(__file__).resolve().parent.parent
    seen = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if {"tests", "scripts", "node_modules", ".git"} & set(rel.parts):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # a name bound ONLY to an end helper in this function
            assigns = {}
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            assigns.setdefault(t.id, []).append(n.value)
            bound = {
                name for name, values in assigns.items()
                if all(isinstance(v, ast.Call) and _callee_name(v) in ENDS
                       for v in values)
            }
            for n in ast.walk(fn):
                if not (isinstance(n, ast.Call)
                        and _callee_name(n) == "affordable_start"):
                    continue
                end = n.args[1] if len(n.args) > 1 else None
                ok = (isinstance(end, ast.Call)
                      and _callee_name(end) in ENDS) or (
                    isinstance(end, ast.Name) and end.id in bound)
                seen.append((str(rel), n.lineno, ok))
    assert len(seen) >= 2, seen
    assert all(ok for *_, ok in seen), [s for s in seen if not s[2]]


def test_the_plan_dataclass_keeps_the_field():
    assert NightChargePlan().charge_end_dt is None
