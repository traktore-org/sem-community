"""(#1321) Tomorrow's preview places a car the way its mode charges.

PROD 09.11: a KEBA in "Solar + battery" mode, flat 0.36 CHF/kWh, 11.9 kWh of
sun forecast. The sun never gives the charger's 4.1 kW minimum, so the packer
fell back to grid slots and drew a car block at 07:15 — a charge that mode
never makes by day. A sun-only charger keeps only sun-slot blocks; with too
little sun the preview says so instead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.day_ledger import build_day_slots
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Allocation, Demand, build_night_ledger, keep_sun_only, pack_night,
)

TZ = timezone(timedelta(hours=1))
DAY = datetime(2026, 11, 9, 7, 0, tzinfo=TZ)


def _a(did, h, sun=False):
    s = DAY + timedelta(hours=h)
    return Allocation(demand_id=did, start=s, end=s + timedelta(hours=1), power_w=4140, price=0.0, reason="")


@pytest.mark.unit
def test_sun_only_ids_keep_only_sun_slots():
    sun = {DAY + timedelta(hours=4)}
    kept, empty = keep_sun_only([_a("ev:0", 0), _a("ev:0", 4), _a("ev:1", 0), _a("load:2", 1)], sun, ["ev:0", "ev:1"])
    assert [(a.demand_id, a.start.hour) for a in kept] == [("ev:0", 11), ("load:2", 8)]
    assert empty == ["ev:1"]


@pytest.mark.unit
def test_prod_day_too_little_sun_for_the_car_gives_no_block():
    slots = build_day_slots(
        start=DAY, end=DAY.replace(hour=17), day_kwh=11.9,
        sunrise=DAY.replace(hour=7, minute=30), sunset=DAY.replace(hour=16, minute=50),
        home_w_at=lambda t: 600.0, price_at=lambda t: 0.36, level_cheap_at=lambda t: False,
        export_rate=0.07,
    )
    demand = Demand(id="ev:0", kind="ev", energy_kwh=7.5, max_power_w=4140.0, min_power_w=4140.0,
                    deadline=DAY.replace(hour=17), priority=0, source="grid")
    ledger = build_night_ledger(slots, soc_kwh=3.0, floor_kwh=3.5, max_discharge_w=5000.0, peak_limit_w=6000.0)
    plan = pack_night([demand], ledger, floor_kwh=3.5, max_discharge_w=5000.0, peak_limit_w=6000.0)
    assert plan.allocations, "the grid-allowed packer still places it (the old preview's block)"
    sun = {s.start for s in slots if s.cap_override_w is not None}
    kept, empty = keep_sun_only(plan.allocations, sun, ["ev:0"])
    assert kept == [] and empty == ["ev:0"]


@pytest.mark.unit
def test_the_preview_asks_by_mode_and_drops_a_full_car():
    from .ast_contracts import calls
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
    fn = SEMCoordinator._compose_tomorrow_preview
    assert calls(fn, "effective_charge_mode_for")   # the charger's own mode decides
    assert calls(fn, "_plan_car_full")              # a full car asks nothing
    assert calls(fn, "keep_sun_only")               # sun-only modes keep sun slots only
