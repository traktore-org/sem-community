"""#1309 — a late departure must not turn day hours into charge time.

Charge by 21:00 with a night from 20:30, or a calendar departure two days
away: the night plan counted every hour to the departure. Only tonight's
hours count: the end is ``min(departure, tonight's night end)``, the rule
the joint plan uses (``night_charge_end`` is the one helper for both).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    night_charge_end,
    plan_night_charge,
    window_charge_end,
)

AMS = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 11, 4, 22, 0, tzinfo=AMS)
NIGHT_END = datetime(2026, 11, 5, 7, 0, tzinfo=AMS)


def _plan(**kw):
    args = dict(
        now=NOW, remaining_to_min_kwh=40.0, min_amps=6, max_amps=16,
        watts_per_amp=690.0, night_end="07:00", night_start="20:30",
        tariff_optimized=True, peak_managed_amps=16,
    )
    args.update(kw)
    return plan_night_charge(**args)


def test_departure_after_next_night_start_counts_tonight_only():
    # Charge by 21:00 tomorrow; tomorrow's night opens 20:30.
    dep = datetime(2026, 11, 5, 21, 0, tzinfo=AMS)
    plan = _plan(target_time="21:00", deadline_at=dep)
    assert plan.charge_end_dt == NIGHT_END
    # 40 kWh in 9 h at 16 A (11 kW) is 4.4 h: reachable; but 120 kWh is not.
    big = _plan(target_time="21:00", deadline_at=dep, remaining_to_min_kwh=120.0)
    assert big.reachable is False


def test_calendar_departure_two_days_away_counts_tonight_only():
    dep = NOW + timedelta(days=2)
    plan = _plan(deadline_at=dep, remaining_to_min_kwh=120.0)
    assert plan.charge_end_dt == NIGHT_END
    assert plan.reachable is False


def test_helper_is_min_of_departure_and_night_end():
    for dep in (NIGHT_END - timedelta(hours=2), NIGHT_END,
                NIGHT_END + timedelta(hours=14), NIGHT_END + timedelta(days=2)):
        assert night_charge_end(dep, NIGHT_END, NIGHT_END + timedelta(hours=13.5)) \
            == min(dep, NIGHT_END)
    assert window_charge_end(NIGHT_END + timedelta(days=1),
                             NOW.replace(hour=20, minute=30), NIGHT_END) == NIGHT_END


def test_joint_plan_uses_the_same_helper():
    import ast

    from .ast_contracts import call_sites

    assert any(path.endswith("coordinator.py")
               for path, _line, _kw in call_sites("night_charge_end"))
    tree = ast.parse((Path(__file__).resolve().parent.parent
                      / "coordinator" / "coordinator.py").read_text(encoding="utf-8"))
    own_min = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "min"
               and [getattr(a, "id", "") for a in n.args] == ["deadline", "night_end"]]
    assert own_min == [], "the joint plan cuts the deadline itself again"