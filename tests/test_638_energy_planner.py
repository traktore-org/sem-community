"""#638 G2 — the pure-function corpus for the joint energy packer.

Each scenario is one of the issue's named packing cases: tight window,
competing cheapest slot, unreachable floor → priority yield — plus the
device-floor edges (EV min-amps, binary loads) and the determinism pin.
The packer is pure, so no hass, no mocks, no clock.
"""
from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.energy_planner import (
    Allocation, Demand, EnergyPlan,
)
# (#758) The flat-slot night is a fixture, not a shipping entry point — see
# synthetic_night.py for exactly which four things it pretends about a night.
from custom_components.solar_energy_management.tests.synthetic_night import (
    PriceSlot, pack_flat_night,
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
        plan = pack_flat_night([ev], slots)
        assert _by_id(plan, "ev").status == "fits"
        assert {a.price for a in _allocs(plan, "ev")} == {0.10, 0.12}

    def test_deadline_moves_when_not_whether(self):
        # Cheapest slots lie AFTER the deadline — the EV must pack into the
        # pricier pre-deadline hours. WHEN moves; the floor is still met.
        slots = _slots([0.30, 0.28, 0.10, 0.08])
        ev = Demand(id="ev", kind="ev", energy_kwh=4, max_power_w=4000,
                    min_power_w=1400, priority=0,
                    deadline=T0 + timedelta(hours=2))
        plan = pack_flat_night([ev], slots)
        r = _by_id(plan, "ev")
        assert r.status == "fits"
        assert all(a.price >= 0.28 for a in _allocs(plan, "ev"))

    def test_last_slot_is_shortened_not_overdelivered(self):
        slots = _slots([0.10, 0.20])
        ev = Demand(id="ev", kind="ev", energy_kwh=5, max_power_w=4000,
                    min_power_w=1400, priority=0)
        plan = pack_flat_night([ev], slots)
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
        plan = pack_flat_night([ev, heater], slots)
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
        plan = pack_flat_night([a, b], slots)
        assert _by_id(plan, "a").status == "fits"
        assert _by_id(plan, "b").status == "yields"
        assert not plan.fits
        assert any("YIELDS" in ln for ln in plan.summary_lines())

    def test_partial_fit_reports_the_shortfall(self):
        slots = _slots([0.10, 0.12], cap_w=2000)
        d = Demand(id="hw", kind="load", energy_kwh=6, max_power_w=2000,
                   min_power_w=2000, priority=0)
        plan = pack_flat_night([d], slots)
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
        plan = pack_flat_night([ev, batt], slots)
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
        plan = pack_flat_night([d], slots)
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
        p1 = pack_flat_night(demands, slots)
        p2 = pack_flat_night(list(reversed(demands)), slots)
        assert p1 == p2                       # input order must not matter

    def test_every_allocation_has_a_one_line_reason(self):
        slots = _slots([0.10, 0.20], cap_w=6000)
        plan = pack_flat_night(
            [Demand(id="ev", kind="ev", energy_kwh=6, max_power_w=4000,
                    min_power_w=1400, priority=0)], slots)
        for a in plan.allocations:
            assert a.reason and "W" in a.reason and "cheapest" in a.reason
            assert "\n" not in a.reason

    def test_total_cost_is_the_sum_of_allocations(self):
        slots = _slots([0.10, 0.20], cap_w=6000)
        plan = pack_flat_night(
            [Demand(id="ev", kind="ev", energy_kwh=6, max_power_w=4000,
                    min_power_w=1400, priority=0)], slots)
        assert plan.total_cost == pytest.approx(
            sum(a.energy_kwh * a.price for a in plan.allocations), abs=1e-6)

    def test_zero_need_fits_trivially_and_empty_inputs_are_safe(self):
        assert pack_flat_night([], []).fits is True
        plan = pack_flat_night(
            [Demand(id="ev", kind="ev", energy_kwh=0, max_power_w=4000)], [])
        assert _by_id(plan, "ev").status == "fits"


class TestBatterySourcedDemands:
    """Guido's axis: WHERE the energy comes from changes what constrains it.
    A Tier-2 load off the home battery touches no grid meter — no peak cap,
    no price — it spends the shared battery budget instead."""

    def test_battery_load_does_not_consume_the_grid_cap(self):
        # Cap fits exactly ONE 4 kW draw. The EV (grid) and the Tier-2 heater
        # (battery) both want the same hour — and both fit, because the heater
        # never touches the meter.
        slots = _slots([0.10], cap_w=4000)
        ev = Demand(id="ev", kind="ev", energy_kwh=4, max_power_w=4000,
                    min_power_w=1400, priority=0, source="grid")
        heater = Demand(id="heater", kind="load", energy_kwh=4,
                        max_power_w=4000, min_power_w=4000, priority=1,
                        source="battery")
        plan = pack_flat_night([ev, heater], slots, battery_budget_kwh=10)
        assert _by_id(plan, "ev").status == "fits"
        assert _by_id(plan, "heater").status == "fits"

    def test_battery_budget_exhausts_to_a_reported_yield(self):
        slots = _slots([0.10, 0.12], cap_w=10000)
        heater = Demand(id="heater", kind="load", energy_kwh=4,
                        max_power_w=2000, min_power_w=2000, priority=0,
                        source="battery")
        plan = pack_flat_night([heater], slots, battery_budget_kwh=1.0)
        r = _by_id(plan, "heater")
        assert r.status == "partial"
        assert r.planned_kwh == pytest.approx(1.0, abs=0.01)

    def test_battery_energy_is_free_in_the_plan_and_time_ordered(self):
        # Price curve says hour 2 is cheapest — irrelevant to a battery load:
        # it packs into the EARLIEST hour and costs 0 (the stored energy was
        # paid for when it was charged).
        slots = _slots([0.30, 0.10], cap_w=10000)
        heater = Demand(id="heater", kind="load", energy_kwh=1,
                        max_power_w=2000, min_power_w=2000, priority=0,
                        source="battery")
        plan = pack_flat_night([heater], slots, battery_budget_kwh=5)
        a = _allocs(plan, "heater")[0]
        assert a.start == T0                    # earliest, not cheapest
        assert a.price == 0.0
        assert _by_id(plan, "heater").est_cost == 0.0
        assert "from battery" in a.reason

    def test_shared_budget_spends_by_priority(self):
        slots = _slots([0.10, 0.12], cap_w=10000)
        a = Demand(id="a", kind="load", energy_kwh=2, max_power_w=2000,
                   min_power_w=2000, priority=0, source="battery")
        b = Demand(id="b", kind="load", energy_kwh=2, max_power_w=2000,
                   min_power_w=2000, priority=5, source="battery")
        plan = pack_flat_night([a, b], slots, battery_budget_kwh=2.0)
        assert _by_id(plan, "a").status == "fits"
        assert _by_id(plan, "b").status == "yields"     # budget went to a


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
        plan = pack_flat_night(demands, slots)
        assert plan.fits, plan.summary_lines()
        # No slot exceeds its cap.
        used = {}
        for a in plan.allocations:
            used[a.start] = used.get(a.start, 0.0) + a.power_w
        assert all(w <= 4500 + 1e-6 for w in used.values()), used
        # The EV owns the two cheapest hours; the others pack around it.
        ev_prices = {a.price for a in _allocs(plan, "ev")}
        assert 0.10 in ev_prices and 0.11 in ev_prices


# ---------------------------------------------------------------------------
# The Night Ledger (spec: 2026-07-28-overnight-flow-plan-design.md)
# ---------------------------------------------------------------------------

from custom_components.solar_energy_management.coordinator.energy_planner import (  # noqa: E402
    LedgerSlot, build_night_ledger, pack_night,
)


def _ledger(prices, home_w=500.0, soc=8.0, floor=2.0, peak=6000.0,
            hours=1, levels=None, max_discharge=5000.0):
    slots = []
    for n, p in enumerate(prices):
        s = T0 + timedelta(hours=n * hours)
        slots.append(LedgerSlot(
            start=s, end=s + timedelta(hours=hours), price=p,
            level_cheap=(levels[n] if levels else (p is not None and p < 0.15)),
            home_w=home_w))
    return build_night_ledger(slots, soc_kwh=soc, floor_kwh=floor,
                              max_discharge_w=max_discharge, peak_limit_w=peak)


class TestTrajectoryAndTakeover:
    def test_home_draws_battery_then_grid_takes_over(self):
        # 500 W home, 8→2 kWh usable = 6 kWh = 12 h... use soc 4.5, floor 2:
        # 2.5 kWh above floor = 5 h of home. Hour 6 is the takeover.
        led = _ledger([0.2] * 8, home_w=500, soc=4.5, floor=2.0)
        plan = pack_night([], led, floor_kwh=2.0, peak_limit_w=6000)
        assert led[4].home_grid_w == pytest.approx(0.0, abs=1)
        assert led[5].home_grid_w == pytest.approx(500.0, abs=1)
        assert plan.takeover == led[5].start
        # headroom shrinks by home exactly at the takeover
        assert led[4].headroom_w == pytest.approx(6000.0, abs=1)
        assert led[5].headroom_w == pytest.approx(5500.0, abs=1)

    def test_tier2_draw_moves_the_takeover_earlier(self):
        # Same battery; a Tier-2 load eats 1 kWh in hour 0 → home loses 2 h
        # of battery coverage → takeover moves from hour 5 to hour 3.
        led = _ledger([0.2] * 8, home_w=500, soc=4.5, floor=2.0)
        heater = Demand(id="t2", kind="load", energy_kwh=1.0,
                        max_power_w=1000, min_power_w=1000, priority=0,
                        source="battery")
        plan = pack_night([heater], led, floor_kwh=2.0, peak_limit_w=6000)
        assert _by_id(plan, "t2").status == "fits"
        assert plan.takeover == led[3].start
        assert led[3].home_grid_w > 400

    def test_sunrise_floor_reserves_tomorrows_need(self):
        # floor 4 kWh (the scheduler's sunrise target): only 0.5 kWh sits
        # above it, and HOME's overnight draw eats that first — home's claim
        # on the battery is absolute (spec decision), so Tier-2 gets NOTHING
        # and says so. The 0.5 goes to home's first hour, then the grid
        # takes over.
        led = _ledger([0.2] * 4, home_w=500, soc=4.5, floor=4.0)
        heater = Demand(id="t2", kind="load", energy_kwh=2.0,
                        max_power_w=1000, min_power_w=1000, priority=0,
                        source="battery")
        plan = pack_night([heater], led, floor_kwh=4.0, peak_limit_w=6000)
        r = _by_id(plan, "t2")
        assert r.status == "yields"
        assert r.planned_kwh == 0.0
        assert led[0].home_grid_w == pytest.approx(0.0, abs=1)
        assert led[1].home_grid_w == pytest.approx(500.0, abs=1)

    def test_precharge_raises_the_trajectory(self):
        led = _ledger([0.2] * 6, home_w=500, soc=2.5, floor=2.0)
        led[1].batt_in_kwh = 3.0            # scheduler charges in hour 1
        build_night_ledger(led, soc_kwh=2.5, floor_kwh=2.0,
                           max_discharge_w=5000, peak_limit_w=6000)
        # takeover would be hour 1 without the charge; with it home stays
        # on battery through hour 6.
        assert all(s.home_grid_w < 1 for s in led[1:6])


class TestTariffRobustness:
    def test_unpriced_tail_is_packed_around_and_noted(self):
        # Day-ahead missing for the last 2 slots (price=None). The EV packs
        # only priced slots; the report carries the replan note.
        led = _ledger([0.2, 0.1, None, None], home_w=0, soc=2, floor=2)
        ev = Demand(id="ev", kind="ev", energy_kwh=10, max_power_w=4000,
                    min_power_w=1400, priority=0)
        plan = pack_night([ev], led, floor_kwh=2, peak_limit_w=6000)
        r = _by_id(plan, "ev")
        assert r.status == "partial"
        assert "unpriced" in r.note
        assert all(a.price in (0.1, 0.2) for a in _allocs(plan, "ev"))

    def test_cheap_hours_load_respects_the_level_gate(self):
        # Static curve where NO slot is level-cheap: execution's
        # price_is_cheap would never fire — the plan must yield honestly,
        # not schedule the cheapest hour.
        led = _ledger([0.30, 0.25, 0.28], home_w=0, soc=2, floor=2,
                      levels=[False, False, False])
        hw = Demand(id="hw", kind="load", energy_kwh=2, max_power_w=2000,
                    min_power_w=2000, priority=0, needs_cheap_level=True)
        plan = pack_night([hw], led, floor_kwh=2, peak_limit_w=6000)
        r = _by_id(plan, "hw")
        assert r.status == "yields"
        assert "no cheap window" in r.note

    def test_15min_market_slots_pack_native(self):
        # Slots follow the market: 15-min granularity, cheap quarter wins.
        slots = []
        prices = [0.30, 0.05, 0.30, 0.30]
        for n, p in enumerate(prices):
            s = T0 + timedelta(minutes=15 * n)
            slots.append(LedgerSlot(start=s, end=s + timedelta(minutes=15),
                                    price=p, level_cheap=p < 0.15, home_w=0))
        led = build_night_ledger(slots, soc_kwh=0, floor_kwh=0,
                                 max_discharge_w=0, peak_limit_w=6000)
        ev = Demand(id="ev", kind="ev", energy_kwh=1.0, max_power_w=4000,
                    min_power_w=1400, priority=0)
        plan = pack_night([ev], led, peak_limit_w=6000)
        assert _allocs(plan, "ev")[0].price == 0.05


class TestAntiCycleQuantization:
    def test_short_need_plans_at_min_run(self):
        # 10-min worth of energy, min_run 30 min: the plan says 30 min
        # (that is what can_deactivate would physically do). Over-delivery
        # is honest and reported as fits.
        led = _ledger([0.1, 0.2], home_w=0, soc=2, floor=2)
        pump = Demand(id="pump", kind="load", energy_kwh=2.0 * (10 / 60),
                      max_power_w=2000, min_power_w=2000, priority=0,
                      min_run_s=1800)
        plan = pack_night([pump], led, peak_limit_w=6000)
        a = _allocs(plan, "pump")[0]
        assert (a.end - a.start).total_seconds() == pytest.approx(1800, abs=1)

    def test_blocks_respect_min_gap(self):
        # Contiguous slots are ONE continuous run (no off-period → no
        # cycling → min_gap doesn't apply). A real gap arises when the next
        # cheapest slot is NOT adjacent: hour 2 (0.11) starts only 1 h after
        # block one ends — inside the 2 h min-pause — so the pump must skip
        # it and land in hour 3 instead.
        led = _ledger([0.10, 0.30, 0.11, 0.12], home_w=0, soc=2, floor=2)
        pump = Demand(id="pump", kind="load", energy_kwh=4.0,
                      max_power_w=2000, min_power_w=2000, priority=0,
                      min_gap_s=7200)
        plan = pack_night([pump], led, peak_limit_w=6000)
        blocks = _allocs(plan, "pump")
        assert len(blocks) == 2
        assert blocks[0].price == 0.10                 # hour 0
        assert blocks[1].price == 0.12                 # hour 3, NOT 0.11
        gap = (blocks[1].start - blocks[0].end).total_seconds()
        assert gap >= 7200 - 1


class TestReviewFindings:
    """Pins for the 2026-07-29 pre-deploy review (reviewer HIGH/MEDIUM)."""

    def test_rewalk_preserves_grid_commitments(self):
        # HIGH: EV (grid) fills slot 1's headroom; a Tier-2 draw in slot 0
        # then re-walks the trajectory. The re-walk must NOT resurrect
        # slot 1's spent headroom — the battery pre-charge (grid, lower
        # priority) must not over-subscribe the peak there.
        led = _ledger([0.20, 0.10], home_w=0, soc=10, floor=2, peak=4000)
        ev = Demand(id="ev", kind="ev", energy_kwh=4, max_power_w=4000,
                    min_power_w=1400, priority=0, source="grid")
        t2 = Demand(id="t2", kind="load", energy_kwh=1, max_power_w=1000,
                    min_power_w=1000, priority=1, source="battery")
        pre = Demand(id="battery", kind="battery", energy_kwh=8,
                     max_power_w=5000, priority=2, source="grid")
        plan = pack_night([ev, t2, pre], led, floor_kwh=2,
                          max_discharge_w=5000, peak_limit_w=4000)
        # Per-slot grid power never exceeds the 4 kW peak.
        grid_by_slot = {}
        for a in plan.allocations:
            if a.price > 0 or a.demand_id in ("ev", "battery"):
                grid_by_slot[a.start] = grid_by_slot.get(a.start, 0) + a.power_w
        assert all(w <= 4000 + 1e-6 for w in grid_by_slot.values()), grid_by_slot

    def test_one_list_semantics_higher_number_packs_first(self):
        # The drag list's semantics (surplus walk + reclaim gate): a HIGHER
        # priority number outranks — the default battery slot (100) claims
        # surplus before the default charger (3), day AND night. Callers
        # negate, so the packer sees battery=-100 < ev=-3 and packs it
        # first: the battery pre-charge takes the cheapest slot.
        led = _ledger([0.10, 0.30], home_w=0, soc=2, floor=2, peak=3000)
        ev = Demand(id="ev", kind="ev", energy_kwh=3, max_power_w=3000,
                    min_power_w=1400, priority=-3, source="grid")
        pre = Demand(id="battery", kind="battery", energy_kwh=3,
                     max_power_w=3000, priority=-100, source="grid")
        plan = pack_night([ev, pre], led, floor_kwh=2, peak_limit_w=3000)
        assert _allocs(plan, "battery")[0].price == 0.10
        assert all(a.price == 0.30 for a in _allocs(plan, "ev"))

    def test_second_tier2_in_the_same_slot_is_not_undercounted(self):
        # MEDIUM: avail must come from the WALKED state (home's actual
        # battery share), not the raw home ask — else the second Tier-2
        # demand in a slot is under-scheduled.
        led = _ledger([0.20], home_w=500, soc=10, floor=2)
        a = Demand(id="a", kind="load", energy_kwh=1, max_power_w=1000,
                   min_power_w=1000, priority=0, source="battery")
        b = Demand(id="b", kind="load", energy_kwh=1, max_power_w=1000,
                   min_power_w=1000, priority=1, source="battery")
        plan = pack_night([a, b], led, floor_kwh=2, max_discharge_w=5000,
                          peak_limit_w=6000)
        assert _by_id(plan, "a").status == "fits"
        assert _by_id(plan, "b").status == "fits"


class TestSharedDischargeBudget:
    """Guido (2026-07-29): the battery TOTAL discharge limit is a shared
    per-slot bottleneck — home's battery share + every Tier-2 draw sum
    against the inverter's capability, not each against the full limit."""

    def test_discharge_limit_is_shared_not_per_consumer(self):
        # 2 kW total limit. Home takes 500 W from the battery; pump A
        # (1 kW binary) fits (1.5 kW total); pump B (1 kW binary) would
        # need 2.5 kW total → only 500 W left, below its floor → yields.
        led = _ledger([0.20, 0.20], home_w=500, soc=10, floor=2,
                      max_discharge=2000.0)
        a = Demand(id="a", kind="load", energy_kwh=0.5, max_power_w=1000,
                   min_power_w=1000, priority=0, source="battery")
        b = Demand(id="b", kind="load", energy_kwh=2.0, max_power_w=1000,
                   min_power_w=1000, priority=5, source="battery")
        plan = pack_night([a, b], led, floor_kwh=2, max_discharge_w=2000.0,
                          peak_limit_w=6000)
        assert _by_id(plan, "a").status == "fits"
        rb = _by_id(plan, "b")
        # b cannot share slot 1 with a (500 W home + 1000 W a + 1000 W b =
        # 2.5 kW peak > 2 kW limit — concurrent, since allocations start at
        # slot start) — it lands in slot 2 only: partial 1.0/2.0.
        assert rb.status == "partial"
        assert rb.planned_kwh == pytest.approx(1.0, abs=0.01)
        for s in led:
            peak_w = s.home_w + s.batt_out_w      # concurrent at slot start
            assert peak_w <= 2000.0 + 1e-6, peak_w
