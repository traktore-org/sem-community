"""(#1325) The night's cost includes what the house buys after the battery.

PROD 08.11: flat tariff 0.36 CHF/kWh, the battery's walk carried the house
until 02:00, and the house drew 0.2–0.56 kW from the grid from then to
07:00. The plan had no demands, so it published ``total_cost: None`` and the
dashboards showed 0.00 — as if the night were free.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    TRAJECTORY_KEYS,
    keep_decision_take_trajectory,
    plan_decision_core,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    house_grid_cost,
    takeover_of,
)

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 11, 8, 19, 0, tzinfo=timezone(timedelta(hours=1)))


class _Slot:
    def __init__(self, i, home_grid_w, price=0.36):
        self.start = T0 + timedelta(hours=i)
        self.end = self.start + timedelta(hours=1)
        self.home_grid_w = home_grid_w
        self.price = price

    @property
    def hours(self):
        return (self.end - self.start).total_seconds() / 3600.0


# The PROD night: battery carries 19–02, then the meter.
PROD_DRAW = [0, 0, 0, 0, 0, 0, 0, 200.5, 559.4, 547.8, 471.3, 538.7]


def _prod_ledger(price_at=None):
    price_at = price_at or {}
    return [_Slot(i, w, price_at.get(i, 0.36)) for i, w in enumerate(PROD_DRAW)]


@pytest.mark.unit
def test_prod_night_house_draw_is_priced():
    h = house_grid_cost(_prod_ledger())
    assert h["kwh"] == pytest.approx(2.32, abs=0.01)
    assert h["cost"] == pytest.approx(2.3177 * 0.36, abs=0.001)
    assert h["reason"] is None


@pytest.mark.unit
def test_unpriced_draw_is_unknown_not_zero():
    h = house_grid_cost(_prod_ledger({9: None}))
    assert h["cost"] is None
    assert h["reason"] == "unpriced"
    assert h["kwh"] == pytest.approx(2.32, abs=0.01)


@pytest.mark.unit
def test_unpriced_slot_without_draw_does_not_matter():
    h = house_grid_cost(_prod_ledger({0: None}))
    assert h["cost"] is not None


@pytest.mark.unit
def test_battery_all_night_is_a_real_zero():
    h = house_grid_cost([_Slot(i, 0.0) for i in range(12)])
    assert h == {"kwh": 0.0, "cost": 0.0, "reason": None}


@pytest.mark.unit
def test_no_ledger_is_unknown():
    assert house_grid_cost([])["cost"] is None
    assert house_grid_cost(None)["reason"] == "no_ledger"


@pytest.mark.unit
def test_takeover_is_the_first_metered_slot():
    assert takeover_of(_prod_ledger()) == T0 + timedelta(hours=7)
    assert takeover_of([_Slot(0, 0.5)]) is None  # under 1 W is noise


def _plan(device, house_cost, total):
    return {"blocks": [], "demands": [], "not_scheduled": [], "takeover": None,
            "fits": True, "device_cost": device, "total_cost": total,
            "house_grid": {"kwh": 2.3, "cost": house_cost, "reason": None}}


@pytest.mark.unit
def test_house_cost_moving_does_not_restamp_the_decision():
    a = _plan(1.0, 0.83, 1.83)
    b = _plan(1.0, 0.91, 1.91)
    assert plan_decision_core(a) == plan_decision_core(b)
    assert plan_decision_core(a) != plan_decision_core(_plan(2.0, 0.83, 2.83))


@pytest.mark.unit
def test_a_kept_stamp_takes_the_fresh_house_cost():
    assert "house_grid" in TRAJECTORY_KEYS and "total_cost" in TRAJECTORY_KEYS
    kept = keep_decision_take_trajectory(_plan(1.0, 0.83, 1.83), _plan(1.0, 0.91, 1.91), "now")
    assert kept["total_cost"] == 1.91
    assert kept["house_grid"]["cost"] == 0.91


@pytest.mark.unit
def test_both_plan_answers_publish_the_cost_parts():
    """The quiet night and the packed night both go through _cost_keys."""
    tree = ast.parse((ROOT / "coordinator" / "coordinator.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_cost_keys"]
    assert len(calls) == 2
    args = sorted(ast.unparse(c.args[1]) for c in calls)
    assert args == ["0.0", "plan.total_cost"]
