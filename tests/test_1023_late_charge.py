"""#1023 A3 — a late charge right before departure.

``ev_late_charge_min`` (per charger, 0–120 min, 0 = off) splits the EV's
night in two. The late part runs in the last L minutes before the deadline,
at the rate the charger gets there (its peak-managed headroom), capped by
what is still owed, and ENDS at the deadline. It is never held back for
price. The rest is packed as before, to end before that window opens. Both
are the same demand, so execution reads the late block like any other.
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

from custom_components.solar_energy_management.coordinator.departure import (
    late_charge_s,
)

from .ast_contracts import call_kwargs, calls

ZRH = ZoneInfo("Europe/Zurich")
START = datetime(2026, 10, 9, 22, 0, tzinfo=ZRH)
DEPART = datetime(2026, 10, 10, 7, 0, tzinfo=ZRH)
KW = 7400.0


def _ledger(prices, headroom_w=11000.0, minutes=60):
    step = timedelta(minutes=minutes)
    slots = [LedgerSlot(start=START + n * step, end=START + (n + 1) * step,
                        price=p) for n, p in enumerate(prices)]
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=0.0, peak_limit_w=headroom_w)


# Nine hours, 22:00–07:00. Cheap at 02:00–04:00, dear at the end.
NIGHT = [0.30, 0.30, 0.25, 0.20, 0.10, 0.10, 0.30, 0.35, 0.40]


def _ev(kwh, late_min, **kw):
    return Demand(id="ev:keba", kind="ev", energy_kwh=kwh, max_power_w=KW,
                  min_power_w=1400.0, deadline=DEPART,
                  late_s=late_min * 60, min_run_s=900, min_gap_s=900, **kw)


def test_off_by_default_nothing_moves():
    plan = pack_night([_ev(10.0, 0)], _ledger(NIGHT), peak_limit_w=11000.0)
    assert max(a.end for a in plan.allocations) <= START + timedelta(hours=6)


def test_thirty_minutes_end_at_departure_and_the_floor_still_holds():
    plan = pack_night([_ev(10.0, 30)], _ledger(NIGHT), peak_limit_w=11000.0)
    late = [a for a in plan.allocations if a.end == DEPART]
    assert late, [(a.start, a.end) for a in plan.allocations]
    assert late[0].start == DEPART - timedelta(minutes=30)
    assert late[0].power_w == pytest.approx(KW)
    assert "late charge" in late[0].reason
    r = plan.results[0]
    assert r.status == "fits"
    assert r.planned_kwh == pytest.approx(10.0)
    # the rest stays in the cheap hours and ends before the late window
    rest = [a for a in plan.allocations if "late charge" not in a.reason]
    assert all(a.end <= DEPART - timedelta(minutes=30) for a in rest)


def test_the_late_part_is_capped_by_what_is_owed():
    """2 kWh owed, 30 minutes at 7.4 kW could take 3.7: the late run is
    the whole need and starts no earlier than it must."""
    plan = pack_night([_ev(2.0, 30)], _ledger(NIGHT), peak_limit_w=11000.0)
    assert len(plan.allocations) == 1
    a = plan.allocations[0]
    assert a.end == DEPART
    assert a.energy_kwh == pytest.approx(2.0)
    assert a.start > DEPART - timedelta(minutes=30)


def test_it_is_sized_at_the_headroom_there():
    """Only 4 kW is left in the last hour: the late part is 30 min at
    4 kW, and the rest moves to the cheap hours."""
    ledger = _ledger(NIGHT)
    ledger[-1].headroom_w = 4000.0
    plan = pack_night([_ev(10.0, 30)], ledger, peak_limit_w=11000.0)
    late = [a for a in plan.allocations if a.end == DEPART]
    assert late[0].power_w == pytest.approx(4000.0)
    assert plan.results[0].planned_kwh == pytest.approx(10.0)


def test_never_held_back_for_price():
    """The last hour is the dearest of the night; the late part runs there
    anyway, and its cost is on the books."""
    plan = pack_night([_ev(10.0, 30)], _ledger(NIGHT), peak_limit_w=11000.0)
    late = next(a for a in plan.allocations if a.end == DEPART)
    assert late.price == pytest.approx(0.40)
    assert plan.results[0].est_cost >= late.energy_kwh * 0.40


def test_quarter_hour_slots_hold_it_too():
    prices = [0.20] * 36            # 22:00–07:00 in 15-minute slots
    plan = pack_night([_ev(10.0, 30)], _ledger(prices, minutes=15),
                      peak_limit_w=11000.0)
    late = sorted((a for a in plan.allocations
                   if a.start >= DEPART - timedelta(minutes=30)),
                  key=lambda a: a.start)
    assert late[-1].end == DEPART
    assert late[0].start == DEPART - timedelta(minutes=30)


def test_the_charger_number_reaches_the_plan():
    kwargs = call_kwargs(SEMCoordinator._shadow_energy_plan, "Demand")
    assert any("late_s" in k for k in kwargs), kwargs


def test_changing_it_replans():
    assert calls(SEMCoordinator._energy_plan_demand_signature, "late_charge_s")


@pytest.mark.parametrize("value, seconds", [
    (None, 0), (0, 0), (30, 1800), ("45", 2700), (120, 7200), (500, 7200),
    (-10, 0), ("soon", 0), (float("nan"), 0),
])
def test_the_minutes_are_read_and_bounded(value, seconds):
    assert late_charge_s({"ev_late_charge_min": value}) == seconds


def test_the_rest_ends_before_the_window_even_when_it_is_cheapest():
    """The last hour is the cheapest of the night: without the late charge
    the floor would go there. With it, the rest must end by 06:30."""
    prices = [0.40, 0.40, 0.35, 0.35, 0.30, 0.30, 0.25, 0.20, 0.05]
    plan = pack_night([_ev(10.0, 30)], _ledger(prices), peak_limit_w=11000.0)
    rest = [a for a in plan.allocations if "late charge" not in a.reason]
    assert rest and all(a.end <= DEPART - timedelta(minutes=30) for a in rest)
    assert plan.results[0].planned_kwh == pytest.approx(10.0)


def test_two_cars_share_the_window():
    """Both leave at 07:00 with a 30-minute late charge under an 11 kW
    limit: the second gets what the first left, 3.6 kW."""
    second = Demand(id="ev:zoe", kind="ev", energy_kwh=6.0, max_power_w=KW,
                    min_power_w=1400.0, deadline=DEPART, late_s=1800,
                    priority=1)
    plan = pack_night([_ev(10.0, 30), second], _ledger(NIGHT),
                      peak_limit_w=11000.0)
    zoe_late = next(a for a in plan.allocations
                    if a.demand_id == "ev:zoe" and a.end == DEPART)
    assert zoe_late.power_w == pytest.approx(11000.0 - KW)


def test_with_one_block_the_rest_is_one_block_before_the_window():
    plan = pack_night([_ev(10.0, 30, contiguous=True)], _ledger(NIGHT),
                      peak_limit_w=11000.0)
    early = sorted((a for a in plan.allocations
                    if "late charge" not in a.reason), key=lambda a: a.start)
    for prev, nxt in zip(early, early[1:]):
        assert prev.end == nxt.start
    assert early[-1].end <= DEPART - timedelta(minutes=30)
    assert plan.results[0].planned_kwh == pytest.approx(10.0)
