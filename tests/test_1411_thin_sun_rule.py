"""#1411 — thin sun plus grid: one rule for the plan and the live gate.

Spare sun below a charger's minimum power left through the meter at the
export price while the car's "At least" was bought at night. In the tariff
mode the car may now charge at its minimum on that sun plus the grid —
when the blended price beats the cheapest hour still open to it.

The cases are the three tariffs of the issue: net metering (never), one
price all day with a low export price (always), a cheaper night (only from
enough sun).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
)
from custom_components.solar_energy_management.coordinator.decide import (
    ChargerIntent, decide,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)
from custom_components.solar_energy_management.coordinator.thin_sun import (
    MIN_SUN_W, ThinSun, ThinSunRefs, blended_price, refs_from_ledger,
    thin_sun_pays, thin_sun_verdict,
)

TZ = ZoneInfo("Europe/Zurich")
MIN_W = 4140.0


def _t(h, m=0, day=18):
    return datetime(2026, 11, day, h, m, tzinfo=TZ)


def _pays(sun_w, *, export, day, night, running=False):
    return thin_sun_pays(sun_w=sun_w, min_w=MIN_W, export_price=export,
                         import_price=day, cheapest_other=night,
                         running=running)


# ── the sum ────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheSum:
    def test_the_blend_is_sun_at_export_and_the_rest_at_import(self):
        assert blended_price(1000.0, 4000.0, 0.06, 0.30) == pytest.approx(
            (1000 * 0.06 + 3000 * 0.30) / 4000)

    def test_net_metering_never_fires(self):
        """export = import: the blend IS the import price, never lower."""
        for sun in (300.0, 1000.0, 2500.0, 4000.0):
            assert not _pays(sun, export=0.30, day=0.30, night=0.30)

    def test_an_export_price_above_import_never_fires(self):
        for sun in (300.0, 2500.0, 4000.0):
            assert not _pays(sun, export=0.35, day=0.30, night=0.30)

    def test_one_price_and_a_low_export_price_fires_on_any_thin_sun(self):
        for sun in (MIN_SUN_W, 500.0, 1000.0, 2500.0, 4000.0):
            assert _pays(sun, export=0.06, day=0.30, night=0.30)

    def test_a_cheaper_night_needs_enough_sun(self):
        """day 0.30, night 0.20, export 0.06, 4.14 kW minimum: the blend
        beats the night from 4140 × 0.10 / 0.24 = 1725 W of sun."""
        edge = MIN_W * (0.30 - 0.20) / (0.30 - 0.06)
        assert edge == pytest.approx(1725.0)
        assert not _pays(1000.0, export=0.06, day=0.30, night=0.20)
        assert not _pays(edge - 25.0, export=0.06, day=0.30, night=0.20)
        assert _pays(edge + 25.0, export=0.06, day=0.30, night=0.20)
        assert _pays(3000.0, export=0.06, day=0.30, night=0.20)

    def test_a_dynamic_hour_compares_against_the_cheapest_hour_to_come(self):
        # now 0.18, a 0.12 hour tonight, export 0.05, 2 kW of sun
        blend = blended_price(2000.0, MIN_W, 0.05, 0.18)
        assert blend == pytest.approx(0.1172, abs=1e-4)
        assert _pays(2000.0, export=0.05, day=0.18, night=0.12)
        assert not _pays(2000.0, export=0.05, day=0.18, night=0.10)

    def test_a_negative_export_price_makes_the_sun_better_than_free(self):
        assert _pays(1000.0, export=-0.05, day=0.25, night=0.20)

    def test_strong_sun_and_noise_are_not_this_rule(self):
        assert not _pays(MIN_W, export=0.06, day=0.30, night=0.30)
        assert not _pays(MIN_W + 500, export=0.06, day=0.30, night=0.30)
        assert not _pays(MIN_SUN_W - 1, export=0.06, day=0.30, night=0.30)
        assert not _pays(0.0, export=0.06, day=0.30, night=0.30)

    @pytest.mark.parametrize("missing", ["sun_w", "min_w", "export_price",
                                         "import_price", "cheapest_other"])
    def test_any_unknown_is_a_no(self, missing):
        kw = dict(sun_w=1000.0, min_w=MIN_W, export_price=0.06,
                  import_price=0.30, cheapest_other=0.30)
        kw[missing] = None
        assert thin_sun_pays(**kw) is False

    def test_a_running_session_rides_through_a_thinner_moment(self):
        # starting needs 200 W; running holds down to 50 W
        assert not _pays(120.0, export=0.06, day=0.30, night=0.30)
        assert _pays(120.0, export=0.06, day=0.30, night=0.30, running=True)
        assert not _pays(40.0, export=0.06, day=0.30, night=0.30, running=True)
        # …and the price as if the sun were a quarter stronger, not more:
        # the 1725 W edge of a cheaper night holds down to 1380 W
        assert not _pays(1600.0, export=0.06, day=0.30, night=0.20)
        assert _pays(1600.0, export=0.06, day=0.30, night=0.20, running=True)
        assert _pays(1400.0, export=0.06, day=0.30, night=0.20, running=True)
        assert not _pays(1350.0, export=0.06, day=0.30, night=0.20, running=True)
        assert not _pays(1000.0, export=0.06, day=0.30, night=0.20, running=True)

    def test_a_running_session_gets_no_pass_where_sun_never_pays(self):
        """export >= import on one price: no amount of sun makes the blend
        cheaper, so "already running" must not keep a grid charge alive."""
        for export in (0.30, 0.35):
            for sun in (60.0, 300.0, 1000.0, 2500.0, 4000.0):
                assert not _pays(sun, export=export, day=0.30, night=0.30,
                                 running=True), (export, sun)


@pytest.mark.unit
def test_sweep_one_price_never_fires_at_or_above_the_import_price():
    """Every sun, every minimum, started or running: with one price all day
    and an export price at or above it, the rule buys nothing."""
    for p in (0.05, 0.20, 0.30, 0.45):
        for export in (p, p + 0.01, p * 2):
            for min_w in (1380.0, 4140.0, 11000.0):
                for sun in range(0, int(min_w) + 500, 137):
                    for running in (False, True):
                        assert not thin_sun_pays(
                            sun_w=float(sun), min_w=min_w, export_price=export,
                            import_price=p, cheapest_other=p, running=running)


@pytest.mark.unit
def test_sweep_it_never_fires_when_a_later_hour_is_cheaper_than_any_blend():
    """The blend is never below min(export, import now): a later hour at or
    below that price always wins."""
    for imp in (0.10, 0.30):
        for export in (-0.05, 0.0, 0.06, 0.30):
            ref = min(imp, export)
            for sun in range(200, 4140, 197):
                for running in (False, True):
                    assert not thin_sun_pays(
                        sun_w=float(sun), min_w=4140.0, export_price=export,
                        import_price=imp, cheapest_other=ref, running=running)


# ── the live verdict ──────────────────────────────────────────────────

FLAT = ThinSun(export_price=0.06, import_now=0.30, cheapest_later=0.30,
               strong_sun_kwh=0.0)


def _verdict(t=FLAT, **kw):
    args = dict(sun_w=1000.0, min_w=MIN_W, need_kwh=5.0)
    args.update(kw)
    return thin_sun_verdict(t, **args)


@pytest.mark.unit
class TestTheLiveVerdict:
    def test_it_fires_on_thin_sun_one_price_and_a_low_export_price(self):
        assert _verdict() == (True, "ok")

    def test_not_evaluated_is_a_no(self):
        assert _verdict(None) == (False, "not_evaluated")
        assert _verdict(ThinSun())[0] is False

    def test_an_unknown_export_price_behaves_as_before(self):
        from dataclasses import replace
        assert _verdict(replace(FLAT, export_price=None)) == (
            False, "export_unknown")

    def test_no_need_no_buy(self):
        assert _verdict(need_kwh=0.0) == (False, "no_need")
        assert _verdict(need_kwh=None) == (False, "no_need")
        assert _verdict(need_kwh=0.1) == (False, "no_need")

    def test_a_battery_taking_the_sun_keeps_it(self):
        assert _verdict(battery_charge_w=800.0) == (False, "battery_takes_sun")

    def test_a_battery_that_could_feed_the_car_decides_itself(self):
        assert _verdict(pack_could_pay=True) == (False, "battery_would_pay")

    def test_strong_sun_coming_today_does_it_for_free(self):
        from dataclasses import replace
        assert _verdict(replace(FLAT, strong_sun_kwh=6.0)) == (
            False, "forecast_covers")
        # not enough of it: the rest is still bought, and now is cheapest
        assert _verdict(replace(FLAT, strong_sun_kwh=2.0)) == (True, "ok")

    def test_an_unknown_forecast_does_not_fire(self):
        from dataclasses import replace
        assert _verdict(replace(FLAT, strong_sun_kwh=None)) == (
            False, "forecast_unknown")

    def test_the_peak_limit_needs_room_for_the_grid_share(self):
        # 4140 − 1000 = 3140 W from the grid
        assert _verdict(grid_room_w=3000.0) == (False, "no_grid_room")
        assert _verdict(grid_room_w=3200.0) == (True, "ok")
        assert _verdict(grid_room_w=None) == (True, "ok")

    def test_net_metering_says_not_cheaper(self):
        net = ThinSun(export_price=0.30, import_now=0.30, cheapest_later=0.30,
                      strong_sun_kwh=0.0)
        assert _verdict(net) == (False, "not_cheaper")

    def test_strong_sun_is_left_alone(self):
        assert _verdict(sun_w=MIN_W + 100) == (False, "strong_sun")


# ── the references the plan hands the live gate ───────────────────────

def _day(sun_by_hour, *, price=0.30, night=None, export=0.06,
         export_known=True, level_cheap=False, peak_hours=()):
    """12:00–16:00 with the given spare sun per hour (0 = a dark hour),
    then 20:00–24:00 at the night price."""
    out = []
    for n, sun in enumerate(sun_by_hour):
        t = _t(12 + n)
        if sun > 0:
            out.append(LedgerSlot(
                start=t, end=t + timedelta(hours=1), price=export,
                level_cheap=True, cap_override_w=float(sun),
                import_price=price, import_cheap=level_cheap,
                export_known=export_known,
                import_peak=(12 + n) in peak_hours))
        else:
            out.append(LedgerSlot(start=t, end=t + timedelta(hours=1),
                                  price=price))
    for h in range(20, 24):
        out.append(LedgerSlot(start=_t(h), end=_t(h) + timedelta(hours=1),
                              price=price if night is None else night))
    return out


def _pack(slots, *, need=4.14, grid_in_sun=True, peak=0.0):
    ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                max_discharge_w=0.0, peak_limit_w=peak)
    car = Demand(id="ev:1", kind="ev", energy_kwh=need, max_power_w=11000.0,
                 min_power_w=MIN_W, deadline=_t(23, 59), grid_in_sun=grid_in_sun)
    return pack_night([car], ledger, peak_limit_w=peak), ledger


@pytest.mark.unit
class TestThePlan:
    def test_one_price_low_export_the_car_takes_the_thin_sun_hours(self):
        plan, _ = _pack(_day([1000, 1000, 0, 0]), need=4.14 * 2)
        starts = sorted(a.start for a in plan.allocations)
        assert starts[0] == _t(12) and starts[-1] < _t(14)
        assert {a.code for a in plan.allocations} == {"sun_plus_grid"}
        # sun at 0.06, the rest at 0.30: cheaper than the night's 0.30
        assert plan.total_cost == pytest.approx(
            8.28 * blended_price(1000, MIN_W, 0.06, 0.30), abs=1e-3)

    def test_net_metering_the_car_waits_for_the_night(self):
        plan, _ = _pack(_day([1000, 1000, 0, 0], export=0.30))
        assert all(a.start >= _t(14) for a in plan.allocations)
        assert "sun_plus_grid" not in {a.code for a in plan.allocations}

    def test_an_export_price_nobody_gave_changes_nothing(self):
        plan, _ = _pack(_day([1000, 1000, 0, 0], export_known=False))
        assert "sun_plus_grid" not in {a.code for a in plan.allocations}
        base, _ = _pack(_day([1000, 1000, 0, 0], export_known=False),
                        grid_in_sun=False)
        assert plan.allocations == base.allocations

    def test_a_cheaper_night_wins_over_too_little_sun(self):
        plan, _ = _pack(_day([1000, 1000, 0, 0], night=0.20))
        assert all(a.start >= _t(20) for a in plan.allocations)

    def test_a_cheaper_night_loses_to_enough_sun(self):
        plan, _ = _pack(_day([2500, 2500, 0, 0], night=0.20))
        assert {a.code for a in plan.allocations} == {"sun_plus_grid"}
        assert all(a.start < _t(14) for a in plan.allocations)

    def test_strong_sun_later_today_is_used_first(self):
        """The forecast covers the need from sun alone: no grid by day."""
        plan, _ = _pack(_day([1000, 6000, 0, 0]))
        assert [a.code for a in plan.allocations] == ["solar"]
        assert plan.allocations[0].start == _t(13)

    def test_a_peak_hour_takes_no_grid_share(self):
        plan, _ = _pack(_day([1000, 1000, 0, 0], peak_hours=(12, 13)))
        assert "sun_plus_grid" not in {a.code for a in plan.allocations}

    def test_the_grid_limit_holds(self):
        # 1000 W sun + 3000 W grid < 4140 W: no thin-sun block
        plan, _ = _pack(_day([1000, 1000, 0, 0]), peak=3000.0)
        assert "sun_plus_grid" not in {a.code for a in plan.allocations}

    def test_with_a_home_battery_the_plan_books_no_thin_sun_block(self):
        """The pack takes that sun or decides itself whether it feeds the
        car; the plan cannot know hours ahead, so it keeps the night."""
        ledger = build_night_ledger(
            _day([1000, 1000, 0, 0]), soc_kwh=5.0, floor_kwh=1.0,
            max_discharge_w=5000.0, peak_limit_w=0.0, capacity_kwh=10.0)
        car = Demand(id="ev:1", kind="ev", energy_kwh=4.14, max_power_w=11000.0,
                     min_power_w=MIN_W, deadline=_t(23, 59), grid_in_sun=True)
        plan = pack_night([car], ledger)
        assert "sun_plus_grid" not in {a.code for a in plan.allocations}

    def test_never_above_the_need(self):
        plan, _ = _pack(_day([1000, 1000, 1000, 1000]), need=2.0)
        assert sum(a.energy_kwh for a in plan.allocations) == pytest.approx(
            2.0, abs=0.01)

    def test_without_the_opt_in_nothing_moves(self):
        slots = _day([1000, 1000, 0, 0])
        plan, _ = _pack(slots, grid_in_sun=False)
        assert "sun_plus_grid" not in {a.code for a in plan.allocations}

    def test_the_day_slot_carries_the_two_new_words(self):
        slots = build_day_slots(
            start=_t(10), end=_t(14), day_kwh=20.0, sunrise=_t(7), sunset=_t(17),
            home_w_at=lambda t: 300.0, price_at=lambda t: 0.30,
            level_cheap_at=lambda t: False, export_rate=0.06,
            export_known=True, level_peak_at=lambda t: t.hour == 12)
        sun = [s for s in slots if s.cap_override_w is not None]
        assert sun and all(s.export_known for s in sun)
        assert [s.import_peak for s in sun] == [s.start.hour == 12 for s in sun]
        old = build_day_slots(
            start=_t(10), end=_t(14), day_kwh=20.0, sunrise=_t(7), sunset=_t(17),
            home_w_at=lambda t: 300.0, price_at=lambda t: 0.30,
            level_cheap_at=lambda t: False, export_rate=0.06)
        assert not any(s.export_known or s.import_peak for s in old)


@pytest.mark.unit
class TestTheReferences:
    def test_they_are_the_plans_own_dark_and_strong_hours(self):
        slots = _day([1000, 6000, 0, 0], night=0.20)
        refs = refs_from_ledger(slots, deadline=_t(23, 59), min_w=MIN_W,
                                max_w=11000.0)
        assert refs.forecast_known
        assert refs.cheapest_after(_t(12)) == pytest.approx(0.20)
        assert refs.strong_kwh_after(_t(12)) == pytest.approx(6.0)
        # half of the strong hour is gone
        assert refs.strong_kwh_after(_t(13, 30)) == pytest.approx(3.0)
        assert refs.strong_kwh_after(_t(14)) == 0.0

    def test_a_past_hour_is_no_reference(self):
        slots = _day([1000, 0, 0, 0], price=0.10, night=0.30)
        refs = refs_from_ledger(slots, deadline=_t(23, 59), min_w=MIN_W,
                                max_w=11000.0)
        assert refs.cheapest_after(_t(12)) == pytest.approx(0.10)
        assert refs.cheapest_after(_t(16)) == pytest.approx(0.30)

    def test_the_deadline_bounds_them(self):
        slots = _day([1000, 0, 0, 0], price=0.30, night=0.10)
        refs = refs_from_ledger(slots, deadline=_t(16), min_w=MIN_W,
                                max_w=11000.0)
        assert refs.cheapest_after(_t(12)) == pytest.approx(0.30)

    def test_a_plan_without_sun_has_no_forecast_to_ask(self):
        refs = refs_from_ledger(_day([0, 0, 0, 0]), deadline=_t(23, 59),
                                min_w=MIN_W, max_w=11000.0)
        assert not refs.forecast_known
        assert ThinSunRefs().cheapest_after(_t(12)) is None

    def test_the_plan_and_the_live_rule_agree_on_every_tariff(self):
        """The #1387 discipline: where the plan books a thin-sun block, the
        live verdict fires on the same sun and prices — and nowhere else."""
        cases = [
            dict(sun=1000, price=0.30, night=None, export=0.06),   # one price
            dict(sun=1000, price=0.30, night=None, export=0.30),   # net metering
            dict(sun=1000, price=0.30, night=0.20, export=0.06),   # too little
            dict(sun=2500, price=0.30, night=0.20, export=0.06),   # enough
            dict(sun=2000, price=0.18, night=0.12, export=0.05),   # dynamic
            dict(sun=2000, price=0.18, night=0.10, export=0.05),
        ]
        for c in cases:
            slots = _day([c["sun"], 0, 0, 0], price=c["price"],
                         night=c["night"], export=c["export"])
            plan, ledger = _pack(slots, need=4.14)
            booked = "sun_plus_grid" in {a.code for a in plan.allocations}
            refs = refs_from_ledger(ledger, deadline=_t(23, 59), min_w=MIN_W,
                                    max_w=11000.0)
            live = ThinSun(export_price=c["export"], import_now=c["price"],
                           cheapest_later=refs.cheapest_after(_t(12)),
                           strong_sun_kwh=refs.strong_kwh_after(_t(12)))
            fires, _ = thin_sun_verdict(live, sun_w=float(c["sun"]),
                                        min_w=MIN_W, need_kwh=4.14)
            assert fires is booked, c


# ── the live gate, through decide ─────────────────────────────────────

def _view(**kw):
    from .test_decide import _view as base
    args = dict(mode="solar_plus_cheap", is_night=False, tariff_level="flat",
                target_kwh=9.0, solar_w=1500.0, home_w=500.0, battery_soc=0)
    thin = kw.pop("thin_sun", FLAT)
    args.update(kw)
    v = base(**args)
    from dataclasses import replace
    return replace(v, thin_sun=thin) if thin is not None else v


@pytest.mark.unit
class TestTheLiveGate:
    def test_one_price_low_export_thin_sun_charges_at_the_minimum(self):
        d = decide(_view())
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6
        assert d.reason_code == RC.CHARGER_SUN_PLUS_GRID
        assert "thin sun" in d.reason and d.mode == "solar_plus_cheap"

    def test_it_stays_at_the_minimum_whatever_rate_the_night_left(self):
        from dataclasses import replace
        v = replace(_view(), deadline_amps=14, top_up_amps=16)
        d = decide(v)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6

    def test_a_running_session_holds_through_a_thinner_moment(self):
        """300 W spare → start; 100 W spare while drawing → hold; 100 W
        spare from standstill → no start."""
        from dataclasses import replace
        idle = _view(solar_w=600.0, home_w=500.0)          # 100 W spare
        assert decide(idle).intent is ChargerIntent.IDLE
        drawing = replace(idle, power=replace(
            idle.power, charging=True, power_w=4100.0))
        d = decide(drawing)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.reason_code == RC.CHARGER_SUN_PLUS_GRID

    def test_a_battery_charging_from_that_sun_keeps_it(self):
        d = decide(_view(battery_soc=50, battery_charge_w=900.0))
        assert d.intent is ChargerIntent.IDLE

    def test_a_battery_that_may_feed_the_car_decides_itself(self):
        # full pack above its buffer, spare sun past the assist gate
        d = decide(_view(battery_soc=95, solar_w=2500.0, home_w=500.0))
        assert d.intent is ChargerIntent.IDLE
        # below the gate the pack is held to the house: the rule may act
        d = decide(_view(battery_soc=95, solar_w=1300.0, home_w=500.0))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_without_the_rule_inputs_the_mode_behaves_as_before(self):
        before = decide(_view(thin_sun=None))
        assert before.intent is ChargerIntent.IDLE
        assert before.reason_code == RC.CHARGER_LOW_SUN

    def test_an_unknown_export_price_behaves_as_before(self):
        from dataclasses import replace
        d = decide(_view(thin_sun=replace(FLAT, export_price=None)))
        assert d.intent is ChargerIntent.IDLE

    def test_net_metering_waits(self):
        net = ThinSun(export_price=0.30, import_now=0.30, cheapest_later=0.30,
                      strong_sun_kwh=0.0)
        assert decide(_view(thin_sun=net)).intent is ChargerIntent.IDLE

    def test_a_cheaper_night_waits_on_too_little_sun_and_charges_on_enough(self):
        two = ThinSun(export_price=0.06, import_now=0.30, cheapest_later=0.20,
                      strong_sun_kwh=0.0)
        low = decide(_view(thin_sun=two, tariff_level="normal",
                           solar_w=1500.0))            # 1000 W spare
        assert low.intent is ChargerIntent.IDLE
        high = decide(_view(thin_sun=two, tariff_level="normal",
                            solar_w=3000.0))           # 2500 W spare
        assert high.intent is ChargerIntent.CHARGE_AT_AMPS
        assert high.reason_code == RC.CHARGER_SUN_PLUS_GRID

    def test_the_at_least_met_buys_nothing(self):
        assert decide(_view(target_kwh=0.0)).intent is ChargerIntent.IDLE
        assert decide(_view(target_kwh=None)).intent is ChargerIntent.IDLE

    def test_strong_sun_coming_today_waits(self):
        from dataclasses import replace
        d = decide(_view(thin_sun=replace(FLAT, strong_sun_kwh=12.0)))
        assert d.intent is ChargerIntent.IDLE

    def test_an_unknown_forecast_waits(self):
        from dataclasses import replace
        d = decide(_view(thin_sun=replace(FLAT, strong_sun_kwh=None)))
        assert d.intent is ChargerIntent.IDLE

    def test_strong_sun_now_is_never_traded_for_the_grid(self):
        d = decide(_view(solar_w=6500.0))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.reason_code == RC.CHARGER_SUN
        assert d.commanded_amps > 6

    def test_a_peak_hour_pauses_as_before(self):
        d = decide(_view(tariff_level="expensive"))
        assert d.intent is ChargerIntent.IDLE

    def test_no_sun_at_all_waits(self):
        d = decide(_view(solar_w=400.0, home_w=500.0))
        assert d.intent is ChargerIntent.IDLE

    def test_the_other_modes_never_ask_the_rule(self):
        for mode in ("solar_only", "solar_plus_battery", "min_plus_solar"):
            d = decide(_view(mode=mode))
            assert d.reason_code != RC.CHARGER_SUN_PLUS_GRID, mode

    def test_night_is_untouched(self):
        d = decide(_view(is_night=True, solar_w=0.0))
        assert d.reason_code != RC.CHARGER_SUN_PLUS_GRID


# ── the coordinator: stamp-time references and the live inputs ────────

@pytest.mark.unit
class TestTheCoordinatorPlumbing:
    def _stamp(self, monkeypatch, *, optimized=True, kwh=6.0):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator import (
            ev_night_targets,
        )
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from .test_638_shadow_mode import _fake_self, _power, _scheduler
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {"ev_charger": kwh})
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: optimized
        fake._export_price_known = (
            lambda: SEMCoordinator._export_price_known(fake))
        assert SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        return fake, SEMCoordinator

    def test_the_stamp_keeps_the_plans_own_hours_per_charger(self, monkeypatch):
        fake, _ = self._stamp(monkeypatch)
        refs = fake._thin_sun_refs["ev_charger"]
        assert isinstance(refs, ThinSunRefs)
        assert refs.dark, "the night's priced hours are the reference"

    def test_a_charger_outside_the_tariff_mode_gets_no_references(self, monkeypatch):
        fake, _ = self._stamp(monkeypatch, optimized=False)
        assert fake._thin_sun_refs == {}

    def test_no_need_no_references(self, monkeypatch):
        fake, _ = self._stamp(monkeypatch, kwh=0.0)
        assert fake._thin_sun_refs == {}

    def test_the_live_inputs_read_the_refs_and_the_tariff(self, monkeypatch):
        fake, coord = self._stamp(monkeypatch)
        cfg = fake.config["ev_chargers"][0]
        fake.config["electricity_export_rate"] = 0.06
        slots = _day([1000, 6000, 0, 0], night=0.20)
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            slots, deadline=_t(23, 59), min_w=MIN_W, max_w=11000.0)}
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12, 30))
        t = coord._thin_sun_for(fake, "ev_charger", cfg)
        assert isinstance(t, ThinSun)
        assert t.export_price == pytest.approx(0.06)
        assert t.cheapest_later == pytest.approx(0.20)
        assert t.strong_sun_kwh == pytest.approx(6.0)
        assert t.import_now is not None

    def test_an_export_price_nobody_stored_is_unknown(self, monkeypatch):
        fake, coord = self._stamp(monkeypatch)
        fake.config.pop("electricity_export_rate", None)
        assert coord._export_price_known(fake) is False
        t = coord._thin_sun_for(fake, "ev_charger", fake.config["ev_chargers"][0])
        assert t is not None and t.export_price is None
        fake.config["electricity_export_rate"] = 0.0     # a stored zero IS known
        assert coord._export_price_known(fake) is True

    def test_a_live_feed_in_price_is_known(self, monkeypatch):
        fake, coord = self._stamp(monkeypatch)
        fake.config.pop("electricity_export_rate", None)
        fake._tariff_provider._feedin_entity = "sensor.feed_in_price"
        assert coord._export_price_known(fake) is True

    def test_a_plan_without_a_forecast_leaves_the_forecast_unknown(self, monkeypatch):
        fake, coord = self._stamp(monkeypatch)
        fake.config["electricity_export_rate"] = 0.06
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            _day([0, 0, 0, 0]), deadline=_t(23, 59), min_w=MIN_W,
            max_w=11000.0)}
        t = coord._thin_sun_for(fake, "ev_charger", fake.config["ev_chargers"][0])
        assert t.strong_sun_kwh is None
        assert thin_sun_verdict(t, sun_w=1000.0, min_w=MIN_W,
                                need_kwh=5.0) == (False, "forecast_unknown")

    def test_no_stamped_plan_no_inputs(self, monkeypatch):
        fake, coord = self._stamp(monkeypatch)
        fake._thin_sun_refs = {}
        assert coord._thin_sun_for(
            fake, "ev_charger", fake.config["ev_chargers"][0]) is None

    def test_a_fake_host_never_breaks_the_view(self):
        """A bare namespace has no method; a MagicMock answers with a mock.
        Both read as "not evaluated"."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _export_known_of, _thin_sun_of,
        )
        assert _thin_sun_of(SimpleNamespace(), "c", {}) is None
        assert _thin_sun_of(MagicMock(), "c", {}) is None
        assert _export_known_of(SimpleNamespace()) is False
        assert _export_known_of(MagicMock()) is False

        def boom(*a):
            raise RuntimeError("x")
        assert _thin_sun_of(SimpleNamespace(_thin_sun_for=boom), "c", {}) is None


@pytest.mark.unit
class TestOnePriceStillBuysAtLeastAtNight:
    """Item 2 of #1411: the mode is selectable on a flat price, so on a flat
    price it must still buy the "At least" at night as Min + Solar does."""

    @pytest.mark.parametrize("level", ["flat", "no_prices", None, "normal"])
    def test_night_tops_up_like_min_plus_solar(self, level):
        tariff = decide(_view(is_night=True, solar_w=0.0, home_w=400.0,
                              tariff_level=level, thin_sun=None))
        minsol = decide(_view(mode="min_plus_solar", is_night=True, solar_w=0.0,
                              home_w=400.0, tariff_level=level, thin_sun=None))
        assert tariff.intent is ChargerIntent.CHARGE_AT_AMPS, tariff.reason
        assert (tariff.intent, tariff.commanded_amps) == (
            minsol.intent, minsol.commanded_amps)

    def test_the_night_plan_does_not_hold_on_one_price(self):
        """``plan_night_charge`` holds a tariff mode through DEAR hours only;
        a one-price tariff has none, so the night starts as for Min + Solar."""
        from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
            plan_night_charge,
        )
        now = _t(21)

        def plan(optimized, level):
            return plan_night_charge(
                now=now, remaining_to_min_kwh=8.0, min_amps=6, max_amps=16,
                watts_per_amp=690.0, target_time="06:30", night_end="07:00",
                night_start=_t(20, 30), tariff_optimized=optimized,
                peak_managed_amps=16, level_at=lambda t: level)
        for level in ("flat", "no_prices", None):
            a, b = plan(True, level), plan(False, level)
            assert a.should_wait_for_cheap is False, level
            assert (a.deadline_amps, a.top_up_amps) == (
                b.deadline_amps, b.top_up_amps), level

    def test_the_planner_packs_a_one_price_night(self):
        """No cheap level anywhere: the car's floor still fits the night."""
        slots = [LedgerSlot(start=_t(h), end=_t(h) + timedelta(hours=1),
                            price=0.30, level_cheap=False)
                 for h in range(20, 24)]
        ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                    max_discharge_w=0.0, peak_limit_w=0.0)
        car = Demand(id="ev:1", kind="ev", energy_kwh=8.0, max_power_w=11000.0,
                     min_power_w=MIN_W, deadline=_t(23, 59), grid_in_sun=True)
        plan = pack_night([car], ledger)
        assert plan.fits
        assert sum(a.energy_kwh for a in plan.allocations) == pytest.approx(8.0)
