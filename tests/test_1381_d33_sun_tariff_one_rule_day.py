"""(#1381 D33) Sun + tariff over a whole synthetic day: one rule, both
stored strategies, the battery switch changing only the battery's part.

The verification review found D23 unproven: the pipeline replay's PROD days
carry no tariff levels and no plan, so "no corpus command changed" says
nothing about the peak pause, the cheap hour, the thin-sun rule or the
deadline floor. The replay rig cannot stamp a plan or run a price provider,
so this drives the decision itself over a 15-minute day that has all four:

* 06–08 normal price, weak sun → idle
* 08–10 thin sun, strong sun still to come → idle (the sun will do it free)
* 10–12 a cheap hour → the grid tops "At least" up
* 12–14 strong sun → solar charging
* 14–16 thin sun, no strong sun left, export 0.06, import 0.28, the night
  0.30 → the thin-sun rule (sun plus grid at the minimum)
* 16–17 normal, weak sun → idle
* 17–18 peak, the night can still deliver → paused
* 18–22 the night can no longer deliver "At least" → the deadline floor,
  through the peak hour too

Help off = ``solar_plus_cheap``, help on = ``min_plus_solar``. With the home
battery between its priority and buffer levels (it neither fills first nor
helps), the two must decide alike in every slot. With a full battery they may
differ only where the battery adds to the sun.
"""
from __future__ import annotations

from dataclasses import replace

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.thin_sun import ThinSun

from .test_decide import _view

NIGHT_PRICE = 0.30
EXPORT = 0.06


def _slot(hh: float):
    """(tariff level, import price, solar W, strong sun still to come kWh,
    night-deliverable kWh) for the slot starting at ``hh``."""
    if 10.0 <= hh < 12.0:
        level, price = "cheap", 0.12
    elif 17.0 <= hh < 20.0:
        level, price = "peak", 0.45
    else:
        level, price = "normal", 0.28
    if 8.0 <= hh < 10.0 or 14.0 <= hh < 16.0:
        solar = 1400.0
    elif 12.0 <= hh < 14.0:
        solar = 6500.0
    else:
        solar = 300.0
    strong_left = 15.0 if hh < 12.0 else 0.0
    deliverable = 20.0 if hh < 18.0 else 3.0
    return level, price, solar, strong_left, deliverable


def _decide_day(mode: str, battery_soc: float):
    out = []
    hh = 6.0
    while hh < 22.0:
        level, price, solar, strong_left, deliverable = _slot(hh)
        thin = ThinSun(export_price=EXPORT, import_now=price,
                       cheapest_later=NIGHT_PRICE, strong_sun_kwh=strong_left,
                       in_block=solar < 4140.0)
        v = _view(mode, solar_w=solar, home_w=500.0, battery_soc=battery_soc,
                  tariff_level=level, target_kwh=9.0, deadline_amps=6,
                  night_deliverable_kwh=deliverable)
        v = replace(v, thin_sun=thin)
        d = decide(v)
        out.append((hh, d.intent, d.commanded_amps, d.reason_code))
        hh += 0.25
    return out


def _window(day, a, b):
    return [r for r in day if a <= r[0] < b]


def test_help_off_and_help_on_decide_alike_when_the_battery_stays_out():
    off = _decide_day("solar_plus_cheap", battery_soc=50)
    on = _decide_day("min_plus_solar", battery_soc=50)
    diff = [(a, b) for a, b in zip(off, on) if a[1:] != b[1:]]
    assert diff == []


def test_the_day_follows_the_one_rule():
    day = _decide_day("solar_plus_cheap", battery_soc=50)
    idle = ChargerIntent.IDLE
    charge = ChargerIntent.CHARGE_AT_AMPS
    assert all(r[1] is idle for r in _window(day, 6.0, 8.0))
    assert all(r[1] is idle for r in _window(day, 8.0, 10.0)), \
        "thin sun with strong sun still to come must wait"
    assert all(r[1] is charge for r in _window(day, 10.0, 12.0)), "cheap hour"
    assert all(r[1] is charge for r in _window(day, 12.0, 14.0)), "strong sun"
    thin = _window(day, 14.0, 16.0)
    assert all(r[1] is charge and r[3] == RC.CHARGER_SUN_PLUS_GRID for r in thin)
    assert all(r[1] is idle for r in _window(day, 16.0, 18.0)), "peak pause"
    floor = _window(day, 18.0, 22.0)
    assert all(r[1] is charge and r[3] == RC.CHARGER_MIN_TODAY for r in floor), \
        "the deadline floor, through the peak hour too"


def test_with_a_full_battery_they_differ_only_where_the_battery_helps():
    off = _decide_day("solar_plus_cheap", battery_soc=95)
    on = _decide_day("min_plus_solar", battery_soc=95)
    for a, b in zip(off, on):
        if a[1:] == b[1:]:
            continue
        # the only allowed difference: help on charges, or charges more,
        # in a slot where the sun answer is the base (no grid rule acted)
        assert a[3] not in (RC.CHARGER_MIN_TODAY, RC.CHARGER_SUN_PLUS_GRID), a
        assert b[1] is ChargerIntent.CHARGE_AT_AMPS, (a, b)
        assert (b[2] or 0) >= (a[2] or 0), (a, b)
