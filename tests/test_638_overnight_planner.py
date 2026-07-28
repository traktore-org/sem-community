"""#638 G2 — the pure-function corpus for the overnight joint packer.

Each scenario is one of the issue's named packing cases: tight window,
competing cheapest slot, unreachable floor → priority yield — plus the
device-floor edges (EV min-amps, binary loads) and the determinism pin.
The packer is pure, so no hass, no mocks, no clock.
"""
from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.overnight_planner import (
    Allocation, Demand, OvernightPlan, PriceSlot, plan_overnight,
)

T0 = datetime(2026, 7, 28, 22, 0)


def _slots(prices, cap_w=10000.0, hours=1):
    """Hourly night slots starting 22:00 with the given prices."""
    out = []
    for n, p in enumerate(prices):
        s = T0 + timedelta(hours=n * hours)
        out.append(PriceSlot(start=s, end=s + timedelta(hours=hours),
                             price=p, cap_w=cap_w))
    return out


def _by_id(plan, did):
    return next(r for r in plan.results if r.demand_id == did)


def _allocs(plan, did):
    return [a for a in plan.allocations if a.demand_id == did]


class TestBasicPacking:
    def test_single_ev_picks_the_cheapest_slots(self):
        # 6 hours, cheapest are hours 3+4 (0.10, 0.12). EV needs 8 kWh @ 4 kW.
        slots = _slots([0.30, 0.28, 0.25, 0.10, 0.12, 0.27])
        ev = Demand(id="ev", kind="ev", energy_kwh=8, max_power_w=4000,
                    min_power_w=1400, priority=0)
        plan = plan_overnight([ev], slots)
        assert _by_id(plan, "ev").status == "fits"
        assert {a.price for a in _allocs(plan, "ev")} == {0.10, 0.12}

    def test_deadline_moves_when_not_whether(self):
        # Cheapest slots lie AFTER the deadline — the EV must pack into the
        # pricier pre-deadline hours. WHEN moves; the floor is still met.
        slots = _slots([0.30, 0.28, 0.10, 0.08])
        ev = Demand(id="ev", kind="ev", energy_kwh=4, max_power_w=4000,
                    min_power_w=1400, priority=0,
                    deadline=T0 + timedelta(hours=2))
        plan = plan_overnight([ev], slots)
        r = _by_id(plan, "ev")
        assert r.status == "fits"
        assert all(a.price >= 0.28 for a in _allocs(plan, "ev"))

    def test_last_slot_is_shortened_not_overdelivered(self):
        slots = _slots([0.10, 0.20])
        ev = Demand(id="ev", kind="ev", energy_kwh=5, max_power_w=4000,
                    min_power_w=1400, priority=0)
        plan = plan_overnight([ev], slots)
        r = _by_id(plan, "ev")
        assert r.status == "fits"
        assert r.planned_kwh == pytest.approx(5.0, abs=0.01)   # not 8 kWh


class TestCompetition:
    def test_competing_cheapest_slot_second_cheapest_is_used(self):
        # THE packing win over today's greedy collision: both want the 0.10
        # slot; cap fits only one. Priority takes it, the loser packs into
        # 0.12 — and BOTH floors are met (reactive sheds would have starved one).
        slots = _slots([0.30, 0.10, 0.12, 0.28], cap_w=4000)
        ev = Demand(id="ev", kind="ev", energy_kwh=4, max_power_w=4000,
                    min_power_w=1400, priority=0)
        heater = Demand(id="heater", kind="load", energy_kwh=2,
                        max_power_w=2000, min_power_w=2000, priority=1)
        plan = plan_overnight([ev, heater], slots)
        assert _by_id(plan, "ev").status == "fits"
        assert _by_id(plan, "heater").status == "fits"
        assert _allocs(plan, "ev")[0].price == 0.10          # priority wins the cheapest
        assert all(a.price == 0.12 for a in _allocs(plan, "heater"))

    def test_unreachable_floor_yields_by_priority(self):
        # One 4 kW slot, two 4 kW demands with the same deadline: the
        # low-priority floor cannot fit — it YIELDS and says so; the
        # high-priority floor is untouched.
        slots = _slots([0.10], cap_w=4000)
        a = Demand(id="a", kind="ev", energy_kwh=4, max_power_w=4000,
                   min_power_w=1400, priority=0)
        b = Demand(id="b", kind="load", energy_kwh=4, max_power_w=4000,
                   min_power_w=4000, priority=5)
        plan = plan_overnight([a, b], slots)
        assert _by_id(plan, "a").status == "fits"
        assert _by_id(plan, "b").status == "yields"
        assert not plan.fits
        assert any("YIELDS" in ln for ln in plan.summary_lines())

    def test_partial_fit_reports_the_shortfall(self):
        slots = _slots([0.10, 0.12], cap_w=2000)
        d = Demand(id="hw", kind="load", energy_kwh=6, max_power_w=2000,
                   min_power_w=2000, priority=0)
        plan = plan_overnight([d], slots)
        r = _by_id(plan, "hw")
        assert r.status == "partial"
        assert r.planned_kwh == pytest.approx(4.0, abs=0.01)
        assert any("YIELDS 2.0 kWh" in ln for ln in plan.summary_lines())


class TestDeviceFloors:
    def test_ev_min_amps_skips_a_thin_slot_battery_takes_it(self):
        # 1 kW of cap left in the cheapest slot: below the EV's 1.4 kW
        # min-amps floor → the EV must skip it; the battery (continuous
        # from 0) packs there instead. Nothing is wasted.
        slots = [
            PriceSlot(T0, T0 + timedelta(hours=1), 0.10, cap_w=1000),
            PriceSlot(T0 + timedelta(hours=1), T0 + timedelta(hours=2),
                      0.20, cap_w=5000),
        ]
        ev = Demand(id="ev", kind="ev", energy_kwh=3, max_power_w=4000,
                    min_power_w=1400, priority=0)
        batt = Demand(id="battery", kind="battery", energy_kwh=1,
                      max_power_w=3000, min_power_w=0, priority=1)
        plan = plan_overnight([ev, batt], slots)
        assert all(a.price == 0.20 for a in _allocs(plan, "ev"))
        assert _allocs(plan, "battery")[0].price == 0.10
        assert _by_id(plan, "ev").status == "fits"
        assert _by_id(plan, "battery").status == "fits"

    def test_binary_load_is_all_or_nothing_per_slot(self):
        # A 2 kW switch load can't run at 1.5 kW: a slot with only 1.5 kW
        # cap left is skipped even though it is cheapest.
        slots = _slots([0.10, 0.30], cap_w=1500)
        d = Demand(id="pump", kind="load", energy_kwh=1, max_power_w=2000,
                   min_power_w=2000, priority=0)
        plan = plan_overnight([d], slots)
        assert _by_id(plan, "pump").status == "yields"


class TestPlanQuality:
    def test_deterministic(self):
        slots = _slots([0.22, 0.10, 0.10, 0.31, 0.15], cap_w=6000)
        demands = [
            Demand(id="ev", kind="ev", energy_kwh=7, max_power_w=4000,
                   min_power_w=1400, priority=0),
            Demand(id="hw", kind="load", energy_kwh=3, max_power_w=3000,
                   min_power_w=3000, priority=1),
            Demand(id="battery", kind="battery", energy_kwh=4,
                   max_power_w=3000, priority=2),
        ]
        p1 = plan_overnight(demands, slots)
        p2 = plan_overnight(list(reversed(demands)), slots)
        assert p1 == p2                       # input order must not matter

    def test_every_allocation_has_a_one_line_reason(self):
        slots = _slots([0.10, 0.20], cap_w=6000)
        plan = plan_overnight(
            [Demand(id="ev", kind="ev", energy_kwh=6, max_power_w=4000,
                    min_power_w=1400, priority=0)], slots)
        for a in plan.allocations:
            assert a.reason and "W" in a.reason and "cheapest" in a.reason
            assert "\n" not in a.reason

    def test_total_cost_is_the_sum_of_allocations(self):
        slots = _slots([0.10, 0.20], cap_w=6000)
        plan = plan_overnight(
            [Demand(id="ev", kind="ev", energy_kwh=6, max_power_w=4000,
                    min_power_w=1400, priority=0)], slots)
        assert plan.total_cost == pytest.approx(
            sum(a.energy_kwh * a.price for a in plan.allocations), abs=1e-6)

    def test_zero_need_fits_trivially_and_empty_inputs_are_safe(self):
        assert plan_overnight([], []).fits is True
        plan = plan_overnight(
            [Demand(id="ev", kind="ev", energy_kwh=0, max_power_w=4000)], [])
        assert _by_id(plan, "ev").status == "fits"


class TestEnsembleScenario:
    """G1's in-process shape: the #634 ensemble — EV floor + cheap-hours
    heater + battery pre-charge in ONE plan under ONE peak cap."""

    def test_ensemble_night_all_floors_met_under_the_cap(self):
        # 6-hour night, 5 kW peak cap, home draws ~500 W → 4.5 kW usable.
        slots = _slots([0.28, 0.24, 0.11, 0.10, 0.13, 0.26], cap_w=4500)
        demands = [
            Demand(id="ev", kind="ev", energy_kwh=6, max_power_w=4100,
                   min_power_w=1400, priority=0,
                   deadline=T0 + timedelta(hours=6)),
            Demand(id="heater", kind="load", energy_kwh=2, max_power_w=1000,
                   min_power_w=1000, priority=1),
            Demand(id="battery", kind="battery", energy_kwh=3,
                   max_power_w=3000, priority=2),
        ]
        plan = plan_overnight(demands, slots)
        assert plan.fits, plan.summary_lines()
        # No slot exceeds its cap.
        used = {}
        for a in plan.allocations:
            used[a.start] = used.get(a.start, 0.0) + a.power_w
        assert all(w <= 4500 + 1e-6 for w in used.values()), used
        # The EV owns the two cheapest hours; the others pack around it.
        ev_prices = {a.price for a in _allocs(plan, "ev")}
        assert 0.10 in ev_prices and 0.11 in ev_prices
