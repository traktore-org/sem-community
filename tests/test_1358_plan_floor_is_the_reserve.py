"""(#1358) The night plan draws the battery down to the RESERVE, not the priority level.

PROD 13.11, 20:11: the battery was at 28 % and powered the house, while the
plan card said the house buys from the grid because the battery was "empty".
The plan used the priority level (30 %) as the floor. That level only says
when the car waits for the battery; the inverter discharges to the reserve
(20 %), so the house runs on below 30 %.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.consts.battery_modes import reserve_soc_of
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator

from .ast_contracts import calls


@pytest.mark.unit
def test_every_battery_floor_reads_the_reserve():
    # the night ledger and the tomorrow preview both live in the plan builder;
    # since the inverter's own end of discharge counts too, they read the one
    # floor helper, which starts from the reserve
    from custom_components.solar_energy_management.coordinator import coordinator as cmod
    assert calls(SEMCoordinator._shadow_energy_plan, "_battery_floor_for")
    assert calls(cmod._battery_floor_for, "battery_floor_of")


@pytest.mark.unit
@pytest.mark.parametrize("cfg, want", [
    ({"battery_reserve_soc": 20, "battery_priority_soc": 30}, 20.0),
    ({"battery_reserve_soc": None, "battery_priority_soc": 30}, 20.0),
    ({"battery_priority_soc": 30}, 20.0),
    ({"battery_reserve_soc": 10, "battery_priority_soc": 30}, 10.0),
])
def test_the_floor_is_the_reserve_not_the_priority_level(cfg, want):
    assert reserve_soc_of(cfg) == want


@pytest.mark.unit
def test_a_28_percent_pack_still_has_energy_for_the_house():
    from custom_components.solar_energy_management.coordinator.day_ledger import build_day_slots
    from custom_components.solar_energy_management.coordinator.energy_planner import build_night_ledger
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=1))
    start = datetime(2026, 11, 13, 20, 0, tzinfo=tz)
    slots = build_day_slots(
        start=start, end=start + timedelta(hours=11), day_kwh=0.0,
        sunrise=start.replace(hour=7, minute=30) + timedelta(days=1),
        sunset=start.replace(hour=16, minute=50),
        home_w_at=lambda t: 700.0, price_at=lambda t: 0.36,
        level_cheap_at=lambda t: False, export_rate=0.07)
    cap = 15.0
    soc_kwh = 0.28 * cap
    floor = reserve_soc_of({"battery_reserve_soc": 20, "battery_priority_soc": 30}) / 100 * cap
    ledger = build_night_ledger(slots, soc_kwh=soc_kwh, floor_kwh=floor,
                                max_discharge_w=5000.0, peak_limit_w=6000.0)
    given = sum(float(sl.home_batt_kwh) for sl in ledger)
    # 28 % → 20 % of 15 kWh = 1.2 kWh for the house tonight
    assert given == pytest.approx(1.2, abs=0.01)
    old = build_night_ledger(slots, soc_kwh=soc_kwh, floor_kwh=0.30 * cap,
                             max_discharge_w=5000.0, peak_limit_w=6000.0)
    assert sum(float(sl.home_batt_kwh) for sl in old) == 0.0, "the old floor called it empty"
