"""(#1377) A planned battery charge raises the plan's own battery level.

The reporter's night: a 13.5 kWh Powerwall at 0 %, the plan charges it to
100 % in blocks 21:00-00:00 (about 4.5 kW) next to a 16.4 kWh car, 12 kW
grid limit. Before the fix the end level stayed 0 % and every slot said 0 kWh.
"""
from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, battery_at_end, build_night_ledger, pack_night,
)

START = datetime(2026, 11, 18, 21, 0)
CAP = 13.5


def _night(hours=9, home_w=600.0):
    slots = []
    for n in range(hours):
        s = START + timedelta(hours=n)
        # the first three hours are cheap; the rest cost more
        slots.append(LedgerSlot(start=s, end=s + timedelta(hours=1),
                                price=0.10 if n < 3 else 0.30,
                                level_cheap=n < 3, home_w=home_w))
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=5000.0, peak_limit_w=12000.0)


def _plan(ledger):
    battery = Demand(id="battery", kind="battery", energy_kwh=CAP,
                     max_power_w=4500.0, priority=0, source="grid")
    ev = Demand(id="ev:keba", kind="ev", energy_kwh=16.4,
                max_power_w=7400.0, min_power_w=1400.0, priority=1)
    return pack_night([battery, ev], ledger, floor_kwh=0.0,
                      max_discharge_w=5000.0, peak_limit_w=12000.0)


def test_battery_ends_full_after_the_planned_charge():
    ledger = _night(home_w=0.0)     # a quiet house: nothing drains the pack
    plan = _plan(ledger)
    charge = [a for a in plan.allocations if a.demand_id == "battery"]
    assert sum(a.energy_kwh for a in charge) > 13.0
    end = battery_at_end(ledger, 0.0, CAP)
    assert end["pct"] >= 95.0, end


def test_house_draw_after_the_charge_lowers_the_end_level_honestly():
    ledger = _night(home_w=600.0)
    _plan(ledger)
    end = battery_at_end(ledger, 0.0, CAP)
    assert 50.0 < end["pct"] < 95.0, end


def test_slot_level_rises_through_the_charge_blocks():
    ledger = _night()
    _plan(ledger)
    levels = [s.soc_kwh for s in ledger]
    assert levels[0] == 0.0
    assert levels[1] > 0.0 and levels[2] > levels[1]
    assert levels[3] > levels[2] or levels[3] > 10.0


def test_house_after_the_charge_runs_on_the_battery_not_the_grid():
    ledger = _night()
    _plan(ledger)
    # the hour after the blocks: the full pack carries the 600 W house
    assert ledger[4].home_grid_w < 1.0
    assert ledger[4].home_batt_kwh > 0.0


def test_no_charge_planned_leaves_the_level_alone():
    ledger = _night()
    pack_night([], ledger, floor_kwh=0.0, max_discharge_w=5000.0,
               peak_limit_w=12000.0)
    assert battery_at_end(ledger, 0.0, CAP)["pct"] == 0.0
