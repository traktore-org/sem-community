"""#1023 A2 — one continuous charging block per charger.

Slot-wise packing takes the cheapest priced slots one by one, so a car can be
charged in three pieces around an expensive hour. With ``ev_plan_one_block``
(per charger, default off) the demand is ``contiguous``: the packer takes the
cheapest run of back-to-back eligible priced slots that covers the need
within headroom. When no single run can, it packs slot-wise as before and
says so.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    LedgerSlot,
    build_night_ledger,
    pack_night,
)

from .ast_contracts import call_kwargs

ZRH = ZoneInfo("Europe/Zurich")
START = datetime(2026, 10, 9, 22, 0, tzinfo=ZRH)
KW = 7400.0                     # 32 A on one phase, the block's full rate


def _ledger(prices, headroom_w=11000.0):
    slots = [LedgerSlot(start=START + timedelta(hours=n),
                        end=START + timedelta(hours=n + 1), price=p)
             for n, p in enumerate(prices)]
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=0.0, peak_limit_w=headroom_w)


def _ev(kwh, contiguous, **kw):
    return Demand(id="ev:keba", kind="ev", energy_kwh=kwh, max_power_w=KW,
                  min_power_w=1400.0, contiguous=contiguous, **kw)


def _pieces(plan, demand_id="ev:keba"):
    """The allocations of one demand, merged where one ends as the next
    starts: what the charger actually does."""
    out = []
    for a in sorted((a for a in plan.allocations if a.demand_id == demand_id),
                    key=lambda a: a.start):
        if out and out[-1][1] == a.start:
            out[-1] = (out[-1][0], a.end)
        else:
            out.append((a.start, a.end))
    return out


# Three cheap hours, each split from the next by an expensive one.
SPLIT = [0.10, 0.40, 0.10, 0.40, 0.10]


def test_slot_wise_the_car_charges_in_three_pieces():
    plan = pack_night([_ev(3 * KW / 1000, contiguous=False)], _ledger(SPLIT),
                      peak_limit_w=11000.0)
    assert len(_pieces(plan)) == 3
    assert plan.fits


def test_one_block_the_car_charges_once():
    plan = pack_night([_ev(3 * KW / 1000, contiguous=True)], _ledger(SPLIT),
                      peak_limit_w=11000.0)
    pieces = _pieces(plan)
    assert len(pieces) == 1
    # Two runs tie at 0.60 (22–01 and 00–03): the earlier one.
    assert pieces[0] == (START, START + timedelta(hours=3))
    assert plan.fits
    r = plan.results[0]
    assert r.planned_kwh == pytest.approx(3 * KW / 1000)
    assert r.est_cost == pytest.approx(KW / 1000 * (0.10 + 0.40 + 0.10))


def test_the_cheapest_run_wins_not_the_cheapest_hours():
    prices = [0.50, 0.50, 0.10, 0.20, 0.15, 0.50]
    plan = pack_night([_ev(2 * KW / 1000, contiguous=True)], _ledger(prices),
                      peak_limit_w=11000.0)
    assert _pieces(plan) == [(START + timedelta(hours=2),
                              START + timedelta(hours=4))]


def test_the_last_hour_of_a_block_is_only_what_is_still_owed():
    plan = pack_night([_ev(1.5 * KW / 1000, contiguous=True)],
                      _ledger([0.30, 0.10, 0.10, 0.30]), peak_limit_w=11000.0)
    (start, end), = _pieces(plan)
    assert start == START + timedelta(hours=1)
    assert plan.results[0].planned_kwh == pytest.approx(1.5 * KW / 1000)


def test_a_need_longer_than_any_run_falls_back_and_says_so():
    """An unpublished hour breaks the night in two runs of two hours: three
    hours of need fit no single block."""
    prices = [0.10, 0.10, None, 0.10, 0.10]
    plan = pack_night([_ev(3 * KW / 1000, contiguous=True)], _ledger(prices),
                      peak_limit_w=11000.0)
    r = plan.results[0]
    assert r.status == "fits"
    assert "no single block fits" in r.note
    assert len(_pieces(plan)) == 2


def test_the_block_uses_and_leaves_headroom_like_any_allocation():
    """A second demand packed after the block sees the headroom the block
    took."""
    ledger = _ledger(SPLIT, headroom_w=9000.0)
    other = Demand(id="load:pool", kind="load", energy_kwh=2.0,
                   max_power_w=2000.0, min_power_w=2000.0, priority=1)
    plan = pack_night([_ev(3 * KW / 1000, contiguous=True), other], ledger,
                      peak_limit_w=9000.0)
    for a in plan.allocations:
        if a.demand_id == "load:pool":
            assert a.start >= START + timedelta(hours=3), (
                "the pool pump got an hour the car's block filled")


def test_the_deadline_bounds_the_block():
    plan = pack_night(
        [_ev(2 * KW / 1000, contiguous=True,
             deadline=START + timedelta(hours=3))],
        _ledger([0.40, 0.30, 0.20, 0.10, 0.10]), peak_limit_w=11000.0)
    assert _pieces(plan) == [(START + timedelta(hours=1),
                              START + timedelta(hours=3))]


def test_the_charger_switch_reaches_the_plan():
    kwargs = call_kwargs(SEMCoordinator._shadow_energy_plan, "Demand")
    assert any("contiguous" in k for k in kwargs), kwargs


def test_a_missing_hour_breaks_the_block():
    """Slots that do not meet are not one block, priced or not: 23:00–00:00
    is missing from the series."""
    slots = [LedgerSlot(start=START + timedelta(hours=n),
                        end=START + timedelta(hours=n + 1), price=0.10)
             for n in (0, 2, 3)]
    ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                max_discharge_w=0.0, peak_limit_w=11000.0)
    plan = pack_night([_ev(2 * KW / 1000, contiguous=True)], ledger,
                      peak_limit_w=11000.0)
    assert _pieces(plan) == [(START + timedelta(hours=2),
                              START + timedelta(hours=4))]


def test_switching_it_replans():
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(
        SEMCoordinator._energy_plan_demand_signature)))
    assert any(isinstance(n, ast.Constant) and n.value == "ev_plan_one_block"
               for n in ast.walk(tree))
