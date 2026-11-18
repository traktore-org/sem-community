"""#1383 — a car with a 4.1 kW minimum skipped a cheap thin-sun slot.

12:00-14:15 costs 0.11 from the grid, with 0.9 kW of sun; the hours after
cost 0.16-0.22. The sun slot offered only the surplus (export price), so a
car that needs 4.1 kW could not use it and moved to the dear hours. Now a
demand that opts in (``grid_in_sun``) takes the rest from the grid at the
slot's import price, within the grid limit. A load that fits the surplus
keeps the surplus at the export price.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)

TZ = ZoneInfo("Europe/Zurich")
EXPORT = 0.08
CAR_W = 4140.0
NEED = CAR_W / 1000.0 * 2.25            # 12:00-14:15 worth


def _t(h, m=0):
    return datetime(2026, 11, 18, h, m, tzinfo=TZ)


def _slots(sun_w=900.0):
    out, t = [], _t(12)
    while t < _t(16, 30):
        sun = t < _t(14, 15)
        price = 0.11 if sun else (0.16 if t < _t(15) else 0.22)
        out.append(LedgerSlot(
            start=t, end=t + timedelta(minutes=15),
            price=EXPORT if sun else price, level_cheap=sun,
            cap_override_w=sun_w if sun else None,
            import_price=0.11 if sun else None))
        t += timedelta(minutes=15)
    return out


def _plan(*, sun_w=900.0, grid_in_sun=True, peak=0.0, min_w=CAR_W):
    ledger = build_night_ledger(_slots(sun_w), soc_kwh=0.0, floor_kwh=0.0,
                                max_discharge_w=0.0, peak_limit_w=peak)
    car = Demand(id="ev:1", kind="ev", energy_kwh=NEED, max_power_w=CAR_W,
                 min_power_w=min_w, deadline=_t(16, 30), grid_in_sun=grid_in_sun)
    return pack_night([car], ledger, peak_limit_w=peak)


@pytest.mark.unit
def test_the_car_takes_the_cheap_thin_sun_hours():
    plan = _plan()
    assert min(a.start for a in plan.allocations) == _t(12)
    assert max(a.end for a in plan.allocations) == _t(14, 15)
    # sun at export, the rest at the import price: dearer than 0.11? no, cheaper
    assert plan.total_cost == pytest.approx(
        NEED * (0.9 * EXPORT + (CAR_W / 1000.0 - 0.9) * 0.11) / (CAR_W / 1000.0),
        abs=1e-3)
    assert plan.total_cost < NEED * 0.16


@pytest.mark.unit
def test_without_the_opt_in_the_car_moves_to_the_dear_hours():
    plan = _plan(grid_in_sun=False)
    assert min(a.start for a in plan.allocations) == _t(14, 15)


@pytest.mark.unit
def test_a_load_that_fits_the_surplus_keeps_the_surplus():
    plan = _plan(sun_w=6000.0)
    first = sorted(plan.allocations, key=lambda a: a.start)[0]
    assert first.start == _t(12)
    assert first.price == pytest.approx(EXPORT)
    assert first.power_w <= 6000.0


@pytest.mark.unit
def test_the_grid_limit_is_respected():
    # 900 W sun + 3000 W grid = 3900 W < the 4140 W minimum: no assist
    blocked = _plan(peak=3000.0)
    assert not [a for a in blocked.allocations if a.start < _t(14, 15)]
    # 900 + 3400 = 4300 W: the minimum fits, and no hour breaks the limit
    allowed = _plan(peak=3400.0)
    assert min(a.start for a in allowed.allocations) == _t(12)
    for a in allowed.allocations:
        assert a.power_w - 900.0 <= 3400.0 + 1e-6


@pytest.mark.unit
def test_a_slot_without_an_import_price_offers_the_surplus_only():
    slots = _slots()
    for s in slots:
        s.import_price = None
    ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                max_discharge_w=0.0, peak_limit_w=0.0)
    car = Demand(id="ev:1", kind="ev", energy_kwh=NEED, max_power_w=CAR_W,
                 min_power_w=CAR_W, deadline=_t(16, 30), grid_in_sun=True)
    plan = pack_night([car], ledger)
    assert min(a.start for a in plan.allocations) == _t(14, 15)


@pytest.mark.unit
def test_the_day_slot_carries_the_import_price():
    slots = build_day_slots(
        start=_t(10), end=_t(14), day_kwh=20.0, sunrise=_t(7), sunset=_t(17),
        home_w_at=lambda t: 300.0, price_at=lambda t: 0.11,
        level_cheap_at=lambda t: True, export_rate=EXPORT)
    sun = [s for s in slots if s.cap_override_w is not None]
    assert sun and all(s.import_price == pytest.approx(0.11) for s in sun)
    assert all(s.price == pytest.approx(EXPORT) for s in sun)
    deficit = [s for s in slots if s.cap_override_w is None]
    assert all(s.import_price is None for s in deficit)
