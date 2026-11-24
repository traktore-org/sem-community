"""#1411 — what the refutation review found, pinned.

1. A worth-it margin: the blended price must be at least 10 % below the
   cheapest alternative to START, 5 % to keep running. 200 W of sun on a
   flat 0.30 with a pre-filled 0.075 export price bought ~95 % grid before.
2. The true invariant, with the dynamic-tariff case that reads odd and is
   right: now is the cheapest hour, so it buys now.
3. The plan and the live gate never disagree: the charger acts only inside
   a thin-sun block of the stamped plan, and the plan books one with a home
   battery only where the pack is full.
4. No flapping: every soft condition has a start/run pair, and a started
   session holds for the charger's minimum block.
5. An export price is unknown only when the key is absent or not a number.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator import thin_sun as ts
from custom_components.solar_energy_management.coordinator.decide import (
    ChargerIntent, decide,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.coordinator.thin_sun import (
    ThinSun, blended_price, thin_sun_pays, thin_sun_verdict,
)

TZ = ZoneInfo("Europe/Zurich")
MIN_W = 4140.0


def _t(h, m=0):
    return datetime(2026, 11, 18, h, m, tzinfo=TZ)


def _pays(sun_w, *, export, day, night, running=False):
    return thin_sun_pays(sun_w=sun_w, min_w=MIN_W, export_price=export,
                         import_price=day, cheapest_other=night,
                         running=running)


# ── 1. the worth-it margin ─────────────────────────────────────────────

@pytest.mark.unit
class TestTheMargin:
    def test_the_constants(self):
        assert ts.START_MARGIN == pytest.approx(0.10)
        assert 0 < ts.RUN_MARGIN < ts.START_MARGIN

    def test_200_w_of_sun_on_a_flat_price_no_longer_buys_95_percent_grid(self):
        """The review's case: export 0.075 (the pre-filled default), flat
        0.30, 200 W of sun: the blend is 0.289, a 3.6 % saving."""
        assert blended_price(200.0, MIN_W, 0.075, 0.30) == pytest.approx(
            0.289, abs=1e-3)
        assert not _pays(200.0, export=0.075, day=0.30, night=0.30)
        assert not _pays(500.0, export=0.075, day=0.30, night=0.30)

    def test_it_starts_at_ten_percent_below_the_alternative(self):
        # 0.30 → 0.27 needs S·0.225/4140 >= 0.03, i.e. 552 W of sun
        edge = MIN_W * 0.03 / (0.30 - 0.075)
        assert edge == pytest.approx(552.0)
        assert not _pays(edge - 10, export=0.075, day=0.30, night=0.30)
        assert _pays(edge + 10, export=0.075, day=0.30, night=0.30)

    def test_it_keeps_running_at_five_percent(self):
        # 0.30 → 0.285 needs 276 W of sun
        edge = MIN_W * 0.015 / (0.30 - 0.075)
        assert edge == pytest.approx(276.0)
        assert _pays(edge + 10, export=0.075, day=0.30, night=0.30,
                     running=True)
        assert not _pays(edge - 10, export=0.075, day=0.30, night=0.30,
                         running=True)
        # …and what keeps a session alive does not start one
        assert not _pays(edge + 10, export=0.075, day=0.30, night=0.30)

    def test_a_cheaper_night_now_needs_half_the_minimum_in_sun(self):
        # day 0.30, night 0.20, export 0.06: blend <= 0.18 from 2070 W
        assert not _pays(1900.0, export=0.06, day=0.30, night=0.20)
        assert _pays(2100.0, export=0.06, day=0.30, night=0.20)

    def test_net_metering_never_fires_started_or_running(self):
        for sun in (300.0, 1500.0, 4000.0):
            for running in (False, True):
                assert not _pays(sun, export=0.30, day=0.30, night=0.30,
                                 running=running)


# ── 2. the true invariant ──────────────────────────────────────────────

@pytest.mark.unit
class TestTheInvariant:
    def test_it_fires_exactly_when_the_blend_beats_the_alternative_by_the_margin(self):
        for export in (-0.05, 0.0, 0.06, 0.30):
            for imp in (0.10, 0.30):
                for ref in (0.10, 0.20, 0.30):
                    for sun in (300.0, 1000.0, 2500.0, 4000.0):
                        blend = blended_price(sun, MIN_W, export, imp)
                        want = blend <= ref * (1 - ts.START_MARGIN) - ts.PRICE_EPS
                        assert thin_sun_pays(
                            sun_w=sun, min_w=MIN_W, export_price=export,
                            import_price=imp, cheapest_other=ref) is want

    def test_on_one_price_that_reduces_to_export_below_import(self):
        """One price p all day: blend <= 0.9 p needs export < p (and enough
        sun); export >= p can never get there."""
        for p in (0.10, 0.30):
            for sun in range(200, 4140, 311):
                assert not _pays(float(sun), export=p, day=p, night=p)
                assert not _pays(float(sun), export=p * 1.2, day=p, night=p)
            assert _pays(4000.0, export=0.0, day=p, night=p)

    def test_now_is_the_cheapest_hour_so_it_buys_now_even_with_a_high_export_price(self):
        """The review's counter-example to "never when export >= import":
        export 0.30, import now 0.10, cheapest later 0.25. Charging now on
        1 kW of sun costs 0.148/kWh all in; later costs 0.25. It fires, and
        that is right: the grid is cheapest now."""
        assert blended_price(1000.0, MIN_W, 0.30, 0.10) == pytest.approx(
            0.148, abs=1e-3)
        assert _pays(1000.0, export=0.30, day=0.10, night=0.25)


# ── 3. the plan and the live gate never disagree ───────────────────────

GOOD = ThinSun(export_price=0.06, import_now=0.30, cheapest_later=0.30,
               strong_sun_kwh=0.0, in_block=True)


def _verdict(t=GOOD, **kw):
    args = dict(sun_w=1500.0, min_w=MIN_W, need_kwh=5.0)
    args.update(kw)
    return thin_sun_verdict(t, **args)


def _day(sun_by_hour, *, price=0.30, night=None, export=0.06):
    out = []
    for n, sun in enumerate(sun_by_hour):
        t = _t(12 + n)
        if sun > 0:
            out.append(LedgerSlot(
                start=t, end=t + timedelta(hours=1), price=export,
                level_cheap=True, cap_override_w=float(sun),
                import_price=price, import_cheap=False, export_known=True))
        else:
            out.append(LedgerSlot(start=t, end=t + timedelta(hours=1),
                                  price=price))
    for h in range(20, 24):
        out.append(LedgerSlot(start=_t(h), end=_t(h) + timedelta(hours=1),
                              price=price if night is None else night))
    return out


def _pack(slots, *, soc_kwh=0.0, cap=0.0, need=4.14):
    ledger = build_night_ledger(slots, soc_kwh=soc_kwh, floor_kwh=0.0,
                                max_discharge_w=5000.0 if cap else 0.0,
                                peak_limit_w=0.0, capacity_kwh=cap)
    car = Demand(id="ev:1", kind="ev", energy_kwh=need, max_power_w=11000.0,
                 min_power_w=MIN_W, deadline=_t(23, 59), grid_in_sun=True)
    return pack_night([car], ledger)


def _thin_blocks(plan):
    return [(a.start, a.end) for a in plan.allocations
            if a.code == "sun_plus_grid"]


@pytest.mark.unit
class TestPlanAndLiveAgree:
    def test_the_live_gate_acts_only_inside_a_block_of_the_plan(self):
        assert _verdict() == (True, "ok")
        assert _verdict(replace(GOOD, in_block=False)) == (
            False, "no_plan_block")

    def test_no_battery_the_plan_books_and_the_gate_acts_there(self):
        plan = _pack(_day([1500, 1500, 0, 0]))
        assert _thin_blocks(plan)
        assert _verdict()[0] is True

    def test_a_battery_that_is_not_full_no_block_and_no_action(self):
        plan = _pack(_day([1500, 1500, 0, 0]), soc_kwh=5.0, cap=10.0)
        assert _thin_blocks(plan) == []
        # the stash has no block for the charger, so the gate is told so
        assert _verdict(replace(GOOD, in_block=False))[0] is False

    def test_a_full_battery_exports_that_sun_so_the_plan_books_it(self):
        plan = _pack(_day([1500, 1500, 0, 0]), soc_kwh=9.9, cap=10.0)
        assert _thin_blocks(plan)
        assert _verdict(battery_charge_w=0.0)[0] is True

    def test_inside_a_block_a_battery_that_takes_the_sun_still_keeps_it(self):
        assert _verdict(battery_charge_w=600.0) == (False, "battery_takes_sun")

    def test_outside_the_hours_the_plan_picked_the_gate_waits(self):
        """The plan takes the sunniest thin hours first; in another thin
        hour that would pay on its own the charger does not act."""
        plan = _pack(_day([1200, 3000, 0, 0]))
        assert [s for s, _ in _thin_blocks(plan)] == [_t(13)]
        assert _verdict(replace(GOOD, in_block=False), sun_w=1200.0)[0] is False

    def test_a_plan_that_holds_the_charger_wins(self):
        from .test_1411_thin_sun_rule import _view
        v = _view(thin_sun=GOOD, solar_w=2000.0)
        assert decide(v).reason_code == RC.CHARGER_SUN_PLUS_GRID
        held = replace(v, plan=PlanVerdict(hold=True, reason="later block"))
        d = decide(held)
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code != RC.CHARGER_SUN_PLUS_GRID

    def test_the_coordinator_reads_the_block_off_the_stamped_plan(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.thin_sun import (
            refs_from_ledger,
        )
        from .test_638_shadow_mode import _fake_self
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: True
        fake._export_price_known = lambda: SEMCoordinator._export_price_known(fake)
        fake.config["electricity_export_rate"] = 0.06
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            _day([1500, 1500, 0, 0]), deadline=_t(23, 59), min_w=MIN_W,
            max_w=11000.0)}
        fake._energy_plan_shadow = {"computed_at": _t(8).isoformat(), "blocks": [
            {"id": "ev:ev_charger", "start": _t(13).isoformat(),
             "end": _t(14).isoformat(), "reason": "sun_plus_grid"},
            {"id": "ev:ev_charger", "start": _t(21).isoformat(),
             "end": _t(22).isoformat(), "reason": "cheapest_hours"},
            {"id": "ev:other", "start": _t(12).isoformat(),
             "end": _t(13).isoformat(), "reason": "sun_plus_grid"}]}
        cfg = fake.config["ev_chargers"][0]
        for now, want in ((_t(12, 30), False), (_t(13, 30), True),
                          (_t(21, 30), False)):
            monkeypatch.setattr(coord_mod.dt_util, "now", lambda n=now: n)
            assert SEMCoordinator._thin_sun_for(
                fake, "ev_charger", cfg).in_block is want, now


# ── 4. no flapping ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestNoFlapping:
    RUN = replace(GOOD, session_s=1200.0, min_block_s=900.0)   # past the hold

    def test_a_started_session_holds_for_the_minimum_block(self):
        young = replace(GOOD, session_s=120.0, min_block_s=900.0)
        # every SOFT condition turns against it: it holds (the hard
        # limits that break a hold: TestTheHoldBreaksOnHardLimits)
        for kw in (dict(sun_w=10.0), dict(battery_charge_w=450.0),
                   dict(pack_could_pay=True)):
            assert thin_sun_verdict(young, min_w=MIN_W, need_kwh=5.0,
                                    running=True, **{"sun_w": 1500.0, **kw}) == (
                True, "held"), kw
        dear = replace(young, cheapest_later=0.10)
        assert _verdict(dear, running=True) == (True, "held")
        left = replace(young, in_block=False)
        assert _verdict(left, running=True) == (True, "held")

    def test_the_hold_ends_with_the_block_time(self):
        old = replace(GOOD, session_s=901.0, min_block_s=900.0)
        assert _verdict(old, running=True, sun_w=10.0) == (False, "no_sun")

    def test_a_hard_limit_breaks_the_hold(self):
        young = replace(GOOD, session_s=120.0, min_block_s=900.0)
        assert _verdict(young, running=True, need_kwh=0.05) == (False, "no_need")

    def test_a_hold_needs_a_session_this_rule_started(self):
        # a car that is charging for another reason gets the strict start
        assert _verdict(GOOD, running=True, sun_w=100.0) == (False, "no_sun")

    def test_battery_power_hovering_at_its_boundary_does_not_toggle(self):
        """Start veto above 100 W; a running session lets go only above
        500 W. A pack hovering 60–140 W flipped ok/veto every cycle."""
        hover = [60.0, 140.0, 90.0, 130.0, 80.0, 139.0, 101.0, 99.0]
        started = [_verdict(battery_charge_w=w)[0] for w in hover]
        assert started.count(True) not in (0, len(hover)), "the start edge"
        running = [_verdict(self.RUN, running=True, battery_charge_w=w)[0]
                   for w in hover]
        assert all(running)
        assert _verdict(self.RUN, running=True, battery_charge_w=450.0)[0] is True
        assert _verdict(self.RUN, running=True, battery_charge_w=550.0) == (
            False, "battery_takes_sun")

    def test_surplus_hovering_at_the_start_edge_does_not_toggle(self):
        # flat 0.30 / 0.06: starts from 518 W, keeps running from 259 W
        hover = [540.0, 500.0, 530.0, 480.0, 520.0, 300.0, 525.0]
        running = [_verdict(self.RUN, running=True, sun_w=w)[0] for w in hover]
        assert all(running)
        assert _verdict(self.RUN, running=True, sun_w=240.0)[0] is False

    def test_a_growing_sun_at_the_packs_gate_does_not_stop_the_car(self):
        """The pack may feed the car above its own gate. Started below the
        gate, a session keeps going a little above it instead of stopping
        while the sun grows."""
        from .test_1411_thin_sun_rule import _view
        run = replace(GOOD, session_s=1200.0, min_block_s=900.0)

        def decided(spare_w, session):
            v = _view(thin_sun=run if session else GOOD, battery_soc=95,
                      solar_w=500.0 + spare_w, home_w=500.0)
            if session:
                v = replace(v, power=replace(v.power, charging=True,
                                             power_w=4100.0))
            return decide(v).reason_code == RC.CHARGER_SUN_PLUS_GRID

        assert decided(1100.0, False) is True        # below the 1200 W gate
        assert decided(1250.0, False) is False       # no start above it
        assert [decided(w, True) for w in (1150.0, 1250.0, 1180.0, 1300.0,
                                           1400.0)] == [True] * 5
        assert decided(1600.0, True) is False        # well above: the pack's

    def test_a_forecast_at_the_need_does_not_toggle(self):
        at = replace(self.RUN, strong_sun_kwh=5.2)
        assert _verdict(replace(GOOD, strong_sun_kwh=5.2)) == (
            False, "forecast_covers")
        assert _verdict(at, running=True)[0] is True
        assert _verdict(replace(self.RUN, strong_sun_kwh=6.5),
                        running=True) == (False, "forecast_covers")

    def test_a_price_drifting_at_the_reference_does_not_toggle(self):
        # blend 0.213 at 1500 W; reference drifting 0.230–0.240
        refs = [0.240, 0.232, 0.238, 0.230, 0.236]
        start = [_verdict(replace(GOOD, cheapest_later=r))[0] for r in refs]
        assert start.count(True) not in (0, len(refs)), "the start edge"
        run = [_verdict(replace(self.RUN, cheapest_later=r), running=True)[0]
               for r in refs]
        assert all(run)

    def test_the_coordinator_times_the_session(self, monkeypatch):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        note = coord_mod._note_thin_sun
        host = SimpleNamespace()
        on = SimpleNamespace(reason_code=RC.CHARGER_SUN_PLUS_GRID,
                             intent=ChargerIntent.CHARGE_AT_AMPS,
                             mode="solar_plus_cheap")
        off = SimpleNamespace(reason_code=RC.CHARGER_LOW_SUN,
                              intent=ChargerIntent.IDLE, mode="solar_plus_cheap")
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12))
        note(host, "a", on)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12, 5))
        note(host, "a", on)                       # the start time stays
        assert coord_mod._thin_sun_started(host, "a") == _t(12)
        note(host, "b", off)
        assert coord_mod._thin_sun_started(host, "b") is None
        note(host, "a", off)
        assert coord_mod._thin_sun_started(host, "a") is None

    def test_the_minimum_block_is_the_chargers_own_setting(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.thin_sun import (
            refs_from_ledger,
        )
        from .test_638_shadow_mode import _fake_self
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: True
        fake._export_price_known = lambda: True
        fake.config["ev_min_block_minutes"] = 20
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            _day([1500, 0, 0, 0]), deadline=_t(23, 59), min_w=MIN_W,
            max_w=11000.0)}
        fake._thin_sun_sessions = {"ev_charger": {"started": _t(12), "no_sun": 0}}
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12, 4))
        t = SEMCoordinator._thin_sun_for(
            fake, "ev_charger", fake.config["ev_chargers"][0])
        assert t.session_s == pytest.approx(240.0)
        assert t.min_block_s == pytest.approx(1200.0)
        fake._thin_sun_sessions = {}
        assert SEMCoordinator._thin_sun_for(
            fake, "ev_charger", fake.config["ev_chargers"][0]).session_s is None


# ── 5. an unknown export price ────────────────────────────────────────

@pytest.mark.unit
class TestExportPriceKnown:
    def _known(self, **cfg):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        fake = SimpleNamespace(
            config=dict(cfg),
            _tariff_provider=SimpleNamespace(_feedin_entity="sensor.feed_in"))
        return SEMCoordinator._export_price_known(fake)

    def test_a_stored_number_is_known_also_zero_and_negative(self):
        for v in (0.075, 0, 0.0, -0.02, "0.06"):
            assert self._known(electricity_export_rate=v) is True, v

    def test_an_absent_key_is_unknown_even_with_a_feed_in_entity(self):
        """The fallback behind an unavailable feed-in entity is the stored
        rate; with none stored there is no price to compare with."""
        assert self._known() is False

    @pytest.mark.parametrize("junk", [None, "", "abc", [], float("nan"),
                                      float("inf")])
    def test_not_a_number_is_unknown(self, junk):
        assert self._known(electricity_export_rate=junk) is False


# ── second review pass ────────────────────────────────────────────────

YOUNG = replace(GOOD, session_s=60.0, min_block_s=900.0)       # inside the hold
OLD = replace(GOOD, session_s=1200.0, min_block_s=900.0)       # past it


@pytest.mark.unit
class TestTheHoldBreaksOnHardLimits:
    """A hold bridges SOFT conditions only. Each hard limit ends a session
    at once, inside the minimum block too."""

    def test_the_reviews_case_no_sun_and_a_battery_charging_3_kw(self):
        fires, why = _verdict(YOUNG, running=True, sun_w=0.0,
                              battery_charge_w=3000.0, pack_could_pay=True)
        assert fires is False and why == "battery_takes_sun"

    def test_the_hard_limits_are_listed_in_one_place_with_their_reason(self):
        assert set(ts.HARD_LIMITS) == {
            "no_need", "car_absent", "peak_hour", "peak_limit",
            "battery_pays", "battery_takes_sun", "never_pays", "sun_gone",
            "price_unknown"}
        assert all(len(why) > 20 for why in ts.HARD_LIMITS.values())

    def test_at_least_reached(self):
        assert _verdict(YOUNG, running=True, need_kwh=0.05) == (False, "no_need")

    def test_the_peak_limit(self):
        assert _verdict(YOUNG, running=True, hard="peak_limit") == (
            False, "peak_limit")

    def test_the_home_battery_feeding_the_car(self):
        assert _verdict(YOUNG, running=True, hard="battery_pays") == (
            False, "battery_pays")

    def test_export_at_or_above_import_on_one_price(self):
        """Whatever the sun does, the blend can never get 5 % below the
        alternative: the price changed under the session."""
        for export in (0.30, 0.31, 0.29):
            net = replace(YOUNG, export_price=export)
            assert _verdict(net, running=True) == (False, "never_pays"), export

    def test_sun_gone_for_longer_than_the_grace(self):
        gone = dict(running=True, sun_w=10.0)
        assert _verdict(replace(YOUNG, sun_mean_w=None), **gone) == (True, "held")
        assert _verdict(replace(YOUNG, sun_mean_w=120.0), **gone) == (True, "held")
        assert _verdict(replace(YOUNG, sun_mean_w=20.0), **gone) == (
            False, "sun_gone")

    def test_a_battery_plainly_taking_the_sun(self):
        assert _verdict(YOUNG, running=True, battery_charge_w=450.0) == (
            True, "held")                                  # hovering: soft
        assert _verdict(YOUNG, running=True, battery_charge_w=1200.0) == (
            False, "battery_takes_sun")

    def test_soft_conditions_are_still_bridged(self):
        # a sun dip above the run floor, a price between the two margins,
        # a pack hovering at its veto, the block moved away
        assert _verdict(YOUNG, running=True, sun_w=80.0) == (True, "held")
        assert _verdict(replace(YOUNG, cheapest_later=0.23), running=True,
                        sun_w=300.0) == (True, "held")
        assert _verdict(YOUNG, running=True, battery_charge_w=300.0,
                        pack_could_pay=True) == (True, "held")
        assert _verdict(replace(YOUNG, in_block=False), running=True) == (
            True, "held")

    def test_decide_sees_the_pack_feeding_the_car(self):
        """The pack discharges 2 kW more than the house draws while the car
        charges: that is the pack paying, inside the hold or not."""
        from .test_1411_thin_sun_rule import _view
        v = _view(thin_sun=YOUNG, solar_w=1500.0, home_w=500.0, battery_soc=95,
                  battery_discharge_w=2500.0)
        v = replace(v, power=replace(v.power, charging=True, power_w=4100.0))
        d = decide(v)
        assert d.reason_code != RC.CHARGER_SUN_PLUS_GRID
        calm = _view(thin_sun=YOUNG, solar_w=1500.0, home_w=500.0,
                     battery_soc=95, battery_discharge_w=300.0)
        calm = replace(calm, power=replace(calm.power, charging=True,
                                           power_w=4100.0))
        assert decide(calm).reason_code == RC.CHARGER_SUN_PLUS_GRID

    def test_decide_sees_the_peak_limit(self):
        from .test_1411_thin_sun_rule import _view
        v = _view(thin_sun=YOUNG)
        v = replace(v, power=replace(v.power, charging=True, power_w=4100.0),
                    fleet=replace(v.fleet, peak_state="shedding"))
        assert decide(v).reason_code != RC.CHARGER_SUN_PLUS_GRID


@pytest.mark.unit
class TestTheSessionSurvivesStrongSun:
    def test_strong_sun_keeps_the_session_and_its_start_time(self, monkeypatch):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        note = coord_mod._note_thin_sun
        host = SimpleNamespace()
        thin = _dec(RC.CHARGER_SUN_PLUS_GRID)
        strong = _dec(RC.CHARGER_SUN)
        idle = _dec(RC.CHARGER_LOW_SUN, ChargerIntent.IDLE)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12))
        note(host, "a", thin)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12, 3))
        note(host, "a", strong)                    # a strong-sun stretch
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12, 5))
        note(host, "a", thin)                      # back to thin sun
        assert coord_mod._thin_sun_started(host, "a") == _t(12)
        note(host, "a", idle)                      # the car stopped: over
        assert coord_mod._thin_sun_started(host, "a") is None

    def test_strong_sun_alone_starts_no_session(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        host = SimpleNamespace()
        coord_mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert coord_mod._thin_sun_started(host, "a") is None

    def test_a_cloud_at_the_minimum_power_does_not_stop_the_car(self):
        """Sun around the charger's minimum (4140 W ± 300 W), a price
        between the two margins. Strong → solar charges; thin → the same
        session on run thresholds. No stop."""
        from .test_1411_thin_sun_rule import _view
        mid = replace(OLD, cheapest_later=0.065)   # blend 0.060–0.0617: 5–10 %
        seen = []
        for spare in (4300.0, 3900.0, 4400.0, 3850.0, 4200.0, 3950.0):
            v = _view(thin_sun=replace(mid, export_price=0.06, import_now=0.08),
                      solar_w=spare + 500.0, home_w=500.0, tariff_level="normal")
            v = replace(v, power=replace(v.power, charging=True, power_w=4100.0))
            d = decide(v)
            seen.append(d.intent)
            assert d.intent is ChargerIntent.CHARGE_AT_AMPS, (spare, d.reason)
        # the same thin moments from standstill would not start
        cold = _view(thin_sun=replace(GOOD, cheapest_later=0.065,
                                      export_price=0.06, import_now=0.08),
                     solar_w=3900.0 + 500.0, home_w=500.0, tariff_level="normal")
        assert decide(cold).intent is ChargerIntent.IDLE


@pytest.mark.unit
class TestThePlanBlockHasARunPair:
    def test_a_running_session_survives_a_block_that_moved_to_the_next_slot(self):
        moved = replace(OLD, in_block=False, block_near=True)
        assert _verdict(moved, running=True) == (True, "ok")
        gone = replace(OLD, in_block=False, block_near=False)
        assert _verdict(gone, running=True) == (False, "no_plan_block")

    def test_a_block_that_is_only_near_starts_nothing(self):
        near = replace(GOOD, in_block=False, block_near=True)
        assert _verdict(near) == (False, "no_plan_block")
        assert _verdict(near, running=True) == (False, "no_plan_block")

    def _fake(self, blocks, computed):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.thin_sun import (
            refs_from_ledger,
        )
        from .test_638_shadow_mode import _fake_self
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: True
        fake._export_price_known = lambda: True
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            _day([1500, 1500, 0, 0]), deadline=_t(23, 59), min_w=MIN_W,
            max_w=11000.0)}
        plan = {"blocks": blocks}
        if computed is not None:
            plan["computed_at"] = computed.isoformat()
        fake._energy_plan_shadow = plan
        return fake, SEMCoordinator

    def _at(self, monkeypatch, fake, coord, now):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda: now)
        return coord._thin_sun_for(fake, "ev_charger",
                                   fake.config["ev_chargers"][0])

    BLOCK = [{"id": "ev:ev_charger", "start": _t(13).isoformat(),
              "end": _t(14).isoformat(), "reason": "sun_plus_grid"}]

    def test_near_is_a_block_that_opens_within_the_next_slot(self, monkeypatch):
        fake, coord = self._fake(self.BLOCK, _t(8))
        t = self._at(monkeypatch, fake, coord, _t(12, 20))     # 40 min ahead
        assert (t.in_block, t.block_near) == (False, True)
        t = self._at(monkeypatch, fake, coord, _t(13, 20))
        assert (t.in_block, t.block_near) == (True, True)
        t = self._at(monkeypatch, fake, coord, _t(10, 30))     # 2.5 h ahead
        assert (t.in_block, t.block_near) == (False, False)
        t = self._at(monkeypatch, fake, coord, _t(14, 10))     # it is over
        assert (t.in_block, t.block_near) == (False, False)

    def test_a_stale_plan_books_nothing(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
            _MAX_PLAN_AGE,
        )
        now = _t(13, 20)
        fresh, coord = self._fake(self.BLOCK, now - _MAX_PLAN_AGE + timedelta(minutes=5))
        assert self._at(monkeypatch, fresh, coord, now).in_block is True
        stale, coord = self._fake(self.BLOCK, now - _MAX_PLAN_AGE - timedelta(minutes=5))
        t = self._at(monkeypatch, stale, coord, now)
        assert (t.in_block, t.block_near) == (False, False)

    def test_a_plan_without_a_stamp_time_books_nothing(self, monkeypatch):
        fake, coord = self._fake(self.BLOCK, None)
        t = self._at(monkeypatch, fake, coord, _t(13, 20))
        assert (t.in_block, t.block_near) == (False, False)


# ── third review pass ─────────────────────────────────────────────────

def _dec(code, intent=ChargerIntent.CHARGE_AT_AMPS, mode="solar_plus_cheap"):
    from types import SimpleNamespace
    return SimpleNamespace(reason_code=code, intent=intent, mode=mode)


@pytest.mark.unit
class TestTheSessionEnds:
    """A thin-sun session is not a licence: it ends with the mode, the
    day, the car, its plan block and any charge the sun does not fund."""

    def _host(self, monkeypatch, *, block_end=None, now=None):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        host = SimpleNamespace(config={"ev_min_block_minutes": 15})
        host._energy_plan_shadow = {
            "computed_at": _t(8).isoformat(),
            "blocks": ([{"id": "ev:a", "start": _t(12).isoformat(),
                         "end": block_end.isoformat(),
                         "reason": "sun_plus_grid"}] if block_end else [])}
        self.mod = coord_mod
        self.mp = monkeypatch
        self._now(now or _t(12, 5))
        coord_mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN_PLUS_GRID),
                                 sun_w=800.0)
        assert coord_mod._thin_sun_started(host, "a") is not None
        return host

    def _now(self, when):
        self.mp.setattr(self.mod.dt_util, "now", lambda: when)

    def _alive(self, host):
        return self.mod._thin_sun_started(host, "a") is not None

    def test_strong_sun_in_the_same_mode_keeps_it(self, monkeypatch):
        host = self._host(monkeypatch, block_end=_t(13))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert self._alive(host)

    def test_a_change_of_charge_mode_ends_it(self, monkeypatch):
        host = self._host(monkeypatch, block_end=_t(13))
        self.mod._note_thin_sun(
            host, "a", _dec(RC.CHARGER_MAX, ChargerIntent.CHARGE_MAX,
                            mode="always_max"))
        assert not self._alive(host)
        host = self._host(monkeypatch, block_end=_t(13))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN,
                                                mode="min_plus_solar"))
        assert not self._alive(host)

    def test_night_ends_it(self, monkeypatch):
        host = self._host(monkeypatch, block_end=_t(13))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN), is_night=True)
        assert not self._alive(host)

    @pytest.mark.parametrize("code", [RC.CHARGER_TOP_UP, RC.CHARGER_DEADLINE,
                                      RC.CHARGER_MIN_TODAY,
                                      RC.CHARGER_PLAN_OVERRIDE_RUN])
    def test_a_charge_the_sun_does_not_fund_ends_it(self, monkeypatch, code):
        host = self._host(monkeypatch, block_end=_t(13))
        self.mod._note_thin_sun(host, "a", _dec(code))
        assert not self._alive(host)

    def test_no_car_ends_it(self, monkeypatch):
        host = self._host(monkeypatch, block_end=_t(13))
        self.mod._note_thin_sun(
            host, "a", _dec(RC.CHARGER_NO_CAR, ChargerIntent.IDLE))
        assert not self._alive(host)

    def test_it_ends_a_minimum_block_after_its_plan_block(self, monkeypatch):
        """Started in a block that ends 13:00, a 15-minute minimum block:
        strong sun carries it to 13:15, not further."""
        host = self._host(monkeypatch, block_end=_t(13))
        self._now(_t(13, 10))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert self._alive(host)
        self._now(_t(13, 16))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert not self._alive(host)

    def test_a_following_block_carries_it_on(self, monkeypatch):
        host = self._host(monkeypatch, block_end=_t(13))
        host._energy_plan_shadow["blocks"].append(
            {"id": "ev:a", "start": _t(13).isoformat(),
             "end": _t(14).isoformat(), "reason": "sun_plus_grid"})
        self._now(_t(13, 30))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN_PLUS_GRID),
                                sun_w=800.0)
        self._now(_t(14, 10))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert self._alive(host)
        assert self.mod._thin_sun_started(host, "a") == _t(12, 5)
        self._now(_t(14, 16))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert not self._alive(host)

    def test_without_a_block_it_lives_one_minimum_block(self, monkeypatch):
        host = self._host(monkeypatch, block_end=None, now=_t(12, 5))
        self._now(_t(12, 19))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert self._alive(host)
        self._now(_t(12, 21))
        self.mod._note_thin_sun(host, "a", _dec(RC.CHARGER_SUN))
        assert not self._alive(host)


def _on():
    return _dec(RC.CHARGER_SUN_PLUS_GRID)


def _run_sun(monkeypatch, suns, *, step_s=10, start=None):
    """Feed ``_note_thin_sun`` one spare-sun reading per cycle; return the
    host, the module and the time of the last cycle."""
    from types import SimpleNamespace
    from custom_components.solar_energy_management.coordinator import (
        coordinator as coord_mod,
    )
    host = SimpleNamespace(config={"ev_min_block_minutes": 60})
    now = start or _t(12)
    for sun in suns:
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda n=now: n)
        coord_mod._note_thin_sun(host, "a", _on(), sun_w=sun)
        last = now
        now = now + timedelta(seconds=step_s)
    return host, coord_mod, last


@pytest.mark.unit
class TestSunGoneIsJudgedOverAWindow:
    """The fourth review pass: a consecutive timer reset on one good cycle,
    so spare sun alternating 0 W / 60 W never reached three minutes and a
    held session bought grid for the whole block."""

    def test_the_window_and_its_reason(self):
        assert ts.NO_SUN_GRACE_S == pytest.approx(180.0)
        assert "sun_gone" in ts.HARD_LIMITS

    def test_sun_alternating_0_and_60_w_is_gone(self, monkeypatch):
        host, mod, last = _run_sun(monkeypatch, [0.0, 60.0] * 12)   # 4 min
        mean = mod._thin_sun_sun_mean(host, "a", last)
        assert mean == pytest.approx(30.0, abs=4.0)
        assert _verdict(replace(YOUNG, sun_mean_w=mean), running=True,
                        sun_w=60.0) == (False, "sun_gone")

    def test_a_one_minute_cloud_is_not(self, monkeypatch):
        host, mod, last = _run_sun(
            monkeypatch, [800.0] * 8 + [0.0] * 6 + [800.0] * 6)
        mean = mod._thin_sun_sun_mean(host, "a", last)
        assert mean > 400.0
        assert _verdict(replace(YOUNG, sun_mean_w=mean), running=True,
                        sun_w=0.0) == (True, "held")

    def test_a_kettle_for_two_minutes_is_not(self, monkeypatch):
        # 2 of the last 3 minutes at 0 W, one at 300 W: mean 100 W
        host, mod, last = _run_sun(monkeypatch, [300.0] * 6 + [0.0] * 12)
        assert mod._thin_sun_sun_mean(host, "a", last) > 50.0

    def test_three_minutes_without_sun_are(self, monkeypatch):
        host, mod, last = _run_sun(monkeypatch, [600.0] * 6 + [5.0] * 19)
        assert mod._thin_sun_sun_mean(host, "a", last) < 50.0

    def test_a_window_that_is_not_full_yet_says_nothing(self, monkeypatch):
        host, mod, last = _run_sun(monkeypatch, [0.0] * 9)          # 80 s
        assert mod._thin_sun_sun_mean(host, "a", last) is None
        assert _verdict(replace(YOUNG, sun_mean_w=None), running=True,
                        sun_w=0.0) == (True, "held")

    def test_only_the_last_three_minutes_count(self, monkeypatch):
        host, mod, last = _run_sun(monkeypatch, [0.0] * 30 + [700.0] * 19)
        assert mod._thin_sun_sun_mean(host, "a", last) == pytest.approx(700.0)

    def test_the_mean_decides_not_the_cycle(self):
        # the sun happens to read 60 W this cycle: the window still says gone
        assert _verdict(replace(YOUNG, sun_mean_w=30.0), running=True,
                        sun_w=60.0) == (False, "sun_gone")
        # …and one dark cycle in a sunny window is nothing
        assert _verdict(replace(YOUNG, sun_mean_w=400.0), running=True,
                        sun_w=0.0) == (True, "held")

    def test_the_samples_are_bounded(self, monkeypatch):
        host, mod, _ = _run_sun(monkeypatch, [100.0] * 600, step_s=1)
        rec = mod._thin_sun_rec(host, "a")
        assert len(rec["sun"]) <= mod._THIN_SUN_MAX_SAMPLES

    def test_the_view_gets_the_mean(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.thin_sun import (
            refs_from_ledger,
        )
        from .test_638_shadow_mode import _fake_self
        host, mod, last = _run_sun(monkeypatch, [0.0, 60.0] * 12)
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: True
        fake._export_price_known = lambda: True
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            _day([1500, 0, 0, 0]), deadline=_t(23, 59), min_w=MIN_W,
            max_w=11000.0)}
        fake._thin_sun_sessions = {"ev_charger": host._thin_sun_sessions["a"]}
        monkeypatch.setattr(mod.dt_util, "now", lambda: last)
        t = SEMCoordinator._thin_sun_for(
            fake, "ev_charger", fake.config["ev_chargers"][0])
        assert t.sun_mean_w == pytest.approx(30.0, abs=4.0)


@pytest.mark.unit
class TestAnUnreadablePriceIsJudgedOverAWindow:
    BLIND = replace(YOUNG, import_now=None, min_block_s=1800.0)

    def test_the_window(self):
        assert ts.PRICE_BRIDGE_S == pytest.approx(300.0)
        assert "price_unknown" in ts.HARD_LIMITS

    def test_unreadable_for_more_than_half_of_it_ends_the_session(self):
        assert _verdict(replace(self.BLIND, price_blind_share=0.6),
                        running=True) == (False, "price_unknown")
        # also when the price happens to be readable this very cycle
        assert _verdict(replace(YOUNG, min_block_s=1800.0,
                                price_blind_share=0.6),
                        running=True) == (False, "price_unknown")

    def test_less_than_half_is_bridged(self):
        for share in (None, 0.0, 0.2, 0.5):
            assert _verdict(replace(self.BLIND, price_blind_share=share),
                            running=True) == (True, "held"), share

    def _feed(self, monkeypatch, readable_seq, step_s=10):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.thin_sun import (
            refs_from_ledger,
        )
        from .test_638_shadow_mode import _fake_self
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: True
        known = {"v": True}
        fake._export_price_known = lambda: known["v"]
        fake.config["electricity_export_rate"] = 0.06
        fake._thin_sun_refs = {"ev_charger": refs_from_ledger(
            _day([1500, 0, 0, 0]), deadline=_t(23, 59), min_w=MIN_W,
            max_w=11000.0)}
        fake._thin_sun_sessions = {"ev_charger": {"started": _t(12)}}
        cfg = fake.config["ev_chargers"][0]
        now, t = _t(12), None
        for ok in readable_seq:
            known["v"] = ok
            monkeypatch.setattr(coord_mod.dt_util, "now", lambda n=now: n)
            t = SEMCoordinator._thin_sun_for(fake, "ev_charger", cfg)
            SEMCoordinator._thin_sun_for(fake, "ev_charger", cfg)   # 2nd view
            now = now + timedelta(seconds=step_s)
        return t, fake, coord_mod

    def test_a_price_blinking_mostly_unreadable_is_caught(self, monkeypatch):
        """Readable one cycle in three: the consecutive timer never ran
        past 20 s; the window sees two thirds."""
        t, _, _ = self._feed(monkeypatch, [True, False, False] * 12)   # 6 min
        assert t.price_blind_share == pytest.approx(2 / 3, abs=0.06)

    def test_a_price_blinking_mostly_readable_is_bridged(self, monkeypatch):
        t, _, _ = self._feed(monkeypatch, [False, True, True] * 12)
        assert t.price_blind_share == pytest.approx(1 / 3, abs=0.06)

    def test_a_window_that_is_not_full_yet_says_nothing(self, monkeypatch):
        t, _, _ = self._feed(monkeypatch, [False] * 12)                # 2 min
        assert t.price_blind_share is None

    def test_two_views_in_one_cycle_are_one_sample_and_the_list_is_bounded(self, monkeypatch):
        t, fake, mod = self._feed(monkeypatch, [True] * 500, step_s=1)
        rec = mod._thin_sun_rec(fake, "ev_charger")
        assert len(rec["price"]) <= mod._THIN_SUN_MAX_SAMPLES
        assert t.price_blind_share == 0.0
