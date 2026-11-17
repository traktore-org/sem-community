"""(#1081) Diagnose: "Heat cost per hour" — read only.

Per slot: price, COP from the forecast outdoor temperature, heat price
(price / COP), cheap, and whether the plan chose the slot for the device and
why. Nothing decides from it: the plan, the packer's allocations and the
sensor's other attributes are what they were without it.
"""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    _plan_cop_fn, _plan_heat_cost,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)
from custom_components.solar_energy_management.coordinator.heat_cost_view import (
    MAX_ROWS_PER_DEVICE, device_rows,
)
from custom_components.solar_energy_management.sensor import _energy_plan_attrs

CURVE = [(-7.0, 2.5), (12.0, 4.2)]


def _slots(prices, cheap_below=0.25):
    t0 = dt_util.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    rows = [LedgerSlot(start=t0 + timedelta(minutes=15 * n),
                       end=t0 + timedelta(minutes=15 * (n + 1)), price=p,
                       level_cheap=p < cheap_below, tariff_cheap=p < cheap_below,
                       home_w=300.0)
            for n, p in enumerate(prices)]
    return t0, build_night_ledger(rows, soc_kwh=0.0, floor_kwh=0.0,
                                  max_discharge_w=5000.0, peak_limit_w=0.0)


def _pump(did="hp", curve=CURVE, preheat=False):
    return SimpleNamespace(device_id=did, cop_curve=curve, cop=3.0, cop_source="",
                           comfort_preheat_on=lambda: preheat)


def _plain(did="boiler"):
    return SimpleNamespace(device_id=did, cop_curve=None, cop=None, cop_source="",
                           comfort_preheat_on=lambda: False)


class _Ctl:
    def __init__(self, *devs):
        self._d = list(devs)

    def get_devices_sorted(self):
        return self._d


class _Coord:
    """Outdoor temperature: -7 C in the first hour, 12 C after."""
    def __init__(self, t0):
        self.t0 = t0

    def _temperature_at(self, ts):
        return -7.0 if ts < self.t0 + timedelta(hours=1) else 12.0

    def _outdoor_temperature_or_none(self):
        return 5.0


def _run(devs, prices, demands_fn):
    t0, ledger = _slots(prices)
    demands = demands_fn(t0)
    plan = pack_night(demands, ledger)
    cache: list = []
    coord = _Coord(t0)
    cop_fn = lambda dev: _plan_cop_fn(coord, dev, cache)  # noqa: E731
    out = _plan_heat_cost(_Ctl(*devs), demands, plan.allocations, ledger, cop_fn)
    return t0, ledger, plan, out


def _demand(did, kind="load", **kw):
    def make(t0):
        return [Demand(id=f"{kind}:{did}", kind=kind, energy_kwh=1.0,
                       max_power_w=2000.0, min_power_w=2000.0,
                       deadline=t0 + timedelta(hours=24), unpriced_ok=True,
                       cop_at=kw.pop("cop_at", None), **kw)]
    return make


# ── the numbers ───────────────────────────────────────────────────────────

def test_slots_carry_price_cop_heat_price_and_cheap():
    pump = _pump()

    def mk(t0):
        cop = _plan_cop_fn(_Coord(t0), pump, [])
        return _demand("hp", cop_at=cop)(t0)
    prices = [0.30] * 4 + [0.20] * 4 + [0.30] * 4
    _t0, _l, _p, out = _run([pump], prices, mk)
    rows = out["hp"]
    first = rows[0]
    assert len(first) == 6
    by_time = {r[0]: r for r in rows}
    cold = by_time[min(by_time)]               # first hour, -7 C: COP 2.5
    assert cold[1] == 0.3 and cold[2] == 2.5
    assert cold[3] == pytest.approx(0.3 / 2.5, abs=1e-3)
    assert cold[4] == 0                        # 0.30 is not cheap
    mild = [r for r in rows if r[2] == 4.2][0]  # after the first hour
    assert mild[3] == pytest.approx(mild[1] / 4.2, abs=1e-3)


def test_the_plan_chose_flag_and_reason_for_a_heat_pump_load():
    pump = _pump()

    def mk(t0):
        return _demand("hp", cop_at=_plan_cop_fn(_Coord(t0), pump, []))(t0)
    _t0, _l, plan, out = _run([pump], [0.30] * 4 + [0.10] * 4 + [0.30] * 4, mk)
    chosen = [r for r in out["hp"] if r[5] is not None]
    assert chosen and {r[5] for r in chosen} == {"cheapest_heat"}
    placed = {a.start.isoformat(timespec="minutes") for a in plan.allocations}
    assert {r[0] for r in chosen} == placed


def test_a_comfort_goal_and_a_preheat_slot_are_told_apart():
    pump = _pump(preheat=True)

    def mk(t0):
        return [Demand(id="comfort:hp", kind="comfort", energy_kwh=2.0,
                       max_power_w=2000.0, min_power_w=2000.0,
                       deadline=t0 + timedelta(hours=24), unpriced_ok=True,
                       cheap_only_kwh=1.0,
                       cop_at=_plan_cop_fn(_Coord(t0), pump, []))]
    _t0, _l, _p, out = _run([pump], [0.10] * 12, mk)
    assert {r[5] for r in out["hp"] if r[5]} == {"preheat"}
    goal = _pump(preheat=False)

    def mk2(t0):
        return [Demand(id="comfort:hp", kind="comfort", energy_kwh=1.0,
                       max_power_w=2000.0, min_power_w=2000.0,
                       deadline=t0 + timedelta(hours=24), unpriced_ok=True,
                       cop_at=_plan_cop_fn(_Coord(t0), goal, []))]
    _t0, _l, _p, out2 = _run([goal], [0.10] * 12, mk2)
    assert {r[5] for r in out2["hp"] if r[5]} == {"comfort_goal"}


def test_a_tick_without_a_curve_has_no_cop_but_still_shows_the_slots():
    tank = _plain("tank")
    tank.comfort_preheat_on = lambda: True
    _t0, _l, _p, out = _run([tank], [0.1, 0.3, 0.2, 0.1], _demand("tank", kind="comfort"))
    assert all(r[2] is None and r[3] is None for r in out["tank"])
    assert any(r[5] == "comfort_goal" or r[5] == "preheat" for r in out["tank"])


# ── absent when nothing qualifies, and nothing moves ──────────────────────

def test_no_curve_and_no_tick_publishes_nothing():
    _t0, _l, _p, out = _run([_plain()], [0.1, 0.3, 0.2], _demand("boiler"))
    assert out == {}


def test_no_controller_and_broken_devices_publish_nothing():
    t0, ledger = _slots([0.1, 0.2])
    assert _plan_heat_cost(None, [], [], ledger, lambda d: None) == {}
    broken = SimpleNamespace(device_id="x")
    assert _plan_heat_cost(_Ctl(broken), [], [], ledger, lambda d: None) == {}


def test_the_packer_is_untouched_by_the_view():
    pump = _pump()

    def mk(t0):
        return _demand("hp", cop_at=_plan_cop_fn(_Coord(t0), pump, []))(t0)
    t0, ledger = _slots([0.30] * 4 + [0.10] * 4)
    demands = mk(t0)
    before = pack_night(demands, ledger)
    snap = [(a.demand_id, a.start, a.end, a.price, a.reason) for a in before.allocations]
    _plan_heat_cost(_Ctl(pump), demands, before.allocations, ledger,
                    lambda d: _plan_cop_fn(_Coord(t0), d, []))
    t1, ledger2 = _slots([0.30] * 4 + [0.10] * 4)
    after = pack_night(mk(t1), ledger2)
    assert snap == [(a.demand_id, a.start, a.end, a.price, a.reason)
                    for a in after.allocations]


# ── the entity attribute ──────────────────────────────────────────────────

def _plan(slots, heat_cost=None):
    plan = {"computed_at": "x", "fits": True, "demands": [], "blocks": [],
            "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat(),
                       "price": s.price, "cheap": s.tariff_cheap,
                       "home_grid_w": 100.0} for s in slots],
            "has_battery": False}
    if heat_cost is not None:
        plan["heat_cost"] = heat_cost
    return plan


def test_the_attribute_is_absent_without_the_key_and_additive_with_it():
    _t0, ledger = _slots([0.2] * 8)
    bare = _energy_plan_attrs(_plan(ledger))
    assert "heat_cost" not in bare and "heat_cost_omitted" not in bare
    withhc = _energy_plan_attrs(_plan(ledger, {"hp": [["t", 0.2, 3.0, 0.067, 1, None]]}))
    assert withhc.pop("heat_cost") == {"hp": [["t", 0.2, 3.0, 0.067, 1, None]]}
    assert withhc == bare


def test_two_devices_over_96_slots_stay_inside_the_budget():
    prices = [round(0.10 + 0.01 * (n % 17), 4) for n in range(96)]
    pumps = [_pump("hp1"), _pump("hp2")]

    def mk(t0):
        return (_demand("hp1", cop_at=_plan_cop_fn(_Coord(t0), pumps[0], []))(t0)
                + _demand("hp2", cop_at=_plan_cop_fn(_Coord(t0), pumps[1], []))(t0))
    _t0, ledger, _plan_, out = _run(pumps, prices, mk)
    assert set(out) == {"hp1", "hp2"}
    assert all(len(v) <= MAX_ROWS_PER_DEVICE for v in out.values())
    assert len(json.dumps(out)) < 4000
    attrs = _energy_plan_attrs(_plan(ledger, out))
    assert len(json.dumps(attrs, default=str)) <= 15000


def test_over_budget_the_table_goes_before_the_timeline():
    t0, ledger = _slots([0.2] * 96)
    fat = {f"d{n}": [["2026-11-17T01:00", 0.2, 3.0, 0.067, 1, "cheapest_heat"]] * 24
           for n in range(20)}
    attrs = _energy_plan_attrs(_plan(ledger, fat))
    assert "heat_cost" not in attrs and attrs["heat_cost_omitted"] is True
    assert attrs["slots"] and "timeline_omitted" not in attrs


def test_rows_are_rounded_and_capped():
    t0, ledger = _slots([0.123456 + 0.001 * n for n in range(96)])
    rows = device_rows(ledger, lambda ts: 3.14159, {})
    assert len(rows) == MAX_ROWS_PER_DEVICE
    assert rows[0][1] == round(rows[0][1], 4) and rows[0][2] == 3.1
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
