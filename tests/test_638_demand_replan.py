"""#638 — the night re-plans when the ASK changes, and only then.

The issue specified the re-plan triggers as "price update, floor change,
unplug, big deviation"; only unplug shipped. Armed night 1 made the gap
user-visible: the EV target went 3.5 → 6.0 kWh at 22:19, execution followed
the new floor within a cycle (fail-open), and the ledger kept describing a
night that no longer existed.

``_energy_plan_demand_signature`` folds every demand-shaping input into one
comparable value. These tests pin the two properties that matter:

* a REAL change (target, deadline, mode, a load's deficit appearing, the
  price curve) produces a different signature → the stamp trigger re-plans;
* jitter (a running load's deficit shrinking, sub-cent price noise, cycle
  after identical cycle) produces the SAME signature → one plan per night
  stays one plan per night.
"""
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _power(connected=True, per_charger=None):
    return SimpleNamespace(
        ev_connected=connected,
        ev_connected_per_charger=per_charger,
    )


class _Tariff:
    def __init__(self, prices=()):
        self._prices = [SimpleNamespace(price=p) for p in prices]

    def get_tariff_data(self):
        return SimpleNamespace(upcoming_prices=self._prices)


def _dev(did, deficit_h, has=True):
    # The collector packs a load only where SEM may switch it (SURPLUS, the
    # getattr default) AND the night can serve it. The default device here
    # is both, so a gate test can close exactly one of them at a time.
    return SimpleNamespace(
        device_id=did,
        has_runtime_deficit=has,
        daily_min_runtime_sec=int(deficit_h * 3600) + 3600,
        _daily_runtime_accumulated_sec=3600,
        battery_eligible_overnight=True,
    )


def _coord(chargers=None, devices=(), prices=()):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": chargers if chargers is not None else [
        {"id": "keba", "daily_ev_target": 3.5,
         "ev_target_time": "07:00", "charge_mode": "min_plus_solar"},
    ]}
    c._surplus_controller = SimpleNamespace(
        get_devices_sorted=lambda: list(devices))
    c._tariff_provider = _Tariff(prices)
    return c


class TestARealChangeReplans:
    def test_target_change_changes_the_signature(self):
        c = _coord()
        before = c._energy_plan_demand_signature(_power())
        c.config["ev_chargers"][0]["daily_ev_target"] = 6.0
        assert c._energy_plan_demand_signature(_power()) != before

    def test_deadline_and_mode_changes_change_the_signature(self):
        c = _coord()
        base = c._energy_plan_demand_signature(_power())
        c.config["ev_chargers"][0]["ev_target_time"] = "06:00"
        moved = c._energy_plan_demand_signature(_power())
        assert moved != base
        c.config["ev_chargers"][0]["charge_mode"] = "solar_only"
        assert c._energy_plan_demand_signature(_power()) != moved

    def test_unplug_still_replans(self):
        c = _coord()
        assert (c._energy_plan_demand_signature(_power(connected=True))
                != c._energy_plan_demand_signature(_power(connected=False)))

    def test_a_stop_condition_clearing_changes_the_signature(self):
        """#760: a banked comfort band is a hard stop the collector now
        mirrors — so the stop CLEARING mid-night (the room cooled below
        target−offset) must re-plan, or the demand it re-admits stays
        invisible until an unrelated trigger fires."""
        dev = _dev("heizband", 2.0)
        dev.stop_condition_met = True
        c = _coord(devices=[dev])
        before = c._energy_plan_demand_signature(_power())
        dev.stop_condition_met = False
        assert c._energy_plan_demand_signature(_power()) != before

    def test_a_new_load_deficit_changes_the_signature(self):
        quiet = _coord(devices=())
        asking = _coord(devices=(_dev("heizband", 2.0),))
        assert (quiet._energy_plan_demand_signature(_power())
                != asking._energy_plan_demand_signature(_power()))

    def test_a_price_update_changes_the_signature(self):
        flat = _coord(prices=(0.36,) * 8)
        published = _coord(prices=(0.36, 0.36, 0.12, 0.12, 0.36, 0.36, 0.36, 0.36))
        assert (flat._energy_plan_demand_signature(_power())
                != published._energy_plan_demand_signature(_power()))


class TestJitterDoesNot:
    def test_identical_cycles_are_identical(self):
        c = _coord(devices=(_dev("heizband", 2.0),), prices=(0.36,) * 8)
        assert (c._energy_plan_demand_signature(_power())
                == c._energy_plan_demand_signature(_power()))

    def test_a_running_loads_shrinking_deficit_is_not_a_demand_change(self):
        """The deficit shrinks every cycle while a device runs — the 6-minute
        rounding must absorb that, or the night re-plans continuously."""
        c = _coord(devices=(_dev("heizband", 2.0),))
        before = c._energy_plan_demand_signature(_power())
        # 90 seconds of running: deficit 2.0 h → 1.975 h — same 0.1 h bucket.
        c._surplus_controller.get_devices_sorted()[0]\
            ._daily_runtime_accumulated_sec += 90
        assert c._energy_plan_demand_signature(_power()) == before

    def test_sub_cent_price_noise_is_not_a_demand_change(self):
        a = _coord(prices=(0.361,) * 8)
        b = _coord(prices=(0.3649,) * 8)
        assert (a._energy_plan_demand_signature(_power())
                == b._energy_plan_demand_signature(_power()))

    def test_no_tariff_and_a_broken_provider_are_both_valid_shapes(self):
        c = _coord(prices=())
        sig = c._energy_plan_demand_signature(_power())
        assert ("price", ()) in sig
        c._tariff_provider = None  # provider gone entirely
        assert ("price", ()) in c._energy_plan_demand_signature(_power())

    def test_a_broken_device_never_takes_the_signature_down(self):
        bad = SimpleNamespace(device_id="x", has_runtime_deficit=True)
        c = _coord(devices=(bad,))  # missing runtime attrs → skipped
        assert isinstance(c._energy_plan_demand_signature(_power()), tuple)


def _comfort_ask_dev(did="ac1", kwh=1.5, minute=0):
    from datetime import datetime, timezone
    deadline = datetime(2026, 8, 8, 17, minute, tzinfo=timezone.utc)
    return SimpleNamespace(
        device_id=did, has_runtime_deficit=False,
        comfort_plan_demand=lambda now: {"energy_kwh": kwh,
                                         "deadline": deadline},
    )


class TestComfortAsksReplan:
    """(#638 Phase 3) A band's plannable ask is part of what the day is
    being ASKED for — appearing re-plans; thermometer jitter does not."""

    def test_an_ask_appearing_changes_the_signature(self):
        quiet = _coord()
        asking = _coord(devices=(_comfort_ask_dev(),))
        assert (quiet._energy_plan_demand_signature(_power())
                != asking._energy_plan_demand_signature(_power()))

    def test_drift_jitter_rounds_away(self):
        """+0.1 kWh and +10 min stay inside the 0.5 kWh / 30 min steps."""
        a = _coord(devices=(_comfort_ask_dev(kwh=1.5, minute=0),))
        b = _coord(devices=(_comfort_ask_dev(kwh=1.6, minute=10),))
        assert (a._energy_plan_demand_signature(_power())
                == b._energy_plan_demand_signature(_power()))

    def test_a_material_change_does_not(self):
        a = _coord(devices=(_comfort_ask_dev(kwh=1.5),))
        b = _coord(devices=(_comfort_ask_dev(kwh=2.5),))
        assert (a._energy_plan_demand_signature(_power())
                != b._energy_plan_demand_signature(_power()))


class TestTheSupplySideReplans:
    """(#638, the week picture 2026-08-08) The day's free energy is a
    FORECAST that revises — Aug 6 was a 34-kWh day a dawn stamp would have
    priced at ~55.

    The term watches what the PLAN reads: the hours still AHEAD
    (``forecast_remaining_today_kwh``) and TOMORROW's day (the sunrise
    floor and the room arbitrage may buy into). It used to watch the day
    TOTAL — a number the builder reads nowhere. On the .175 campaign
    (15.08) that cost both ways: a live dampening correction rewriting the
    already-produced morning restamped the night eleven times in one day
    (16:42:05, ``('solar', 42.0) → ('solar', 38.0)``, after which the
    packer allocated the byte-identical blocks), while tomorrow collapsing
    never restamped at all.

    Time passing is not news either: the remaining number shrinks all day
    as the sun is spent, exactly as forecast. So the anchor carries the
    production reading it was taken with and compares against what it
    EXPECTS now — a day spent as forecast keeps one anchor; clouds, or a
    provider revision, open a gap and re-anchor once per 3 kWh (#759).
    """

    def _with_forecast(self, today, remaining, tomorrow=0.0):
        c = _coord()
        c._forecast_reader = SimpleNamespace(
            forecast_data=SimpleNamespace(
                forecast_today_kwh=today,
                forecast_remaining_today_kwh=remaining,
                forecast_tomorrow_kwh=tomorrow))
        return c

    @staticmethod
    def _made(kwh):
        """The energy view the cycle already has — today's produced solar."""
        return SimpleNamespace(daily_solar=kwh)

    def test_a_provider_revision_replans(self):
        sunny = self._with_forecast(55.0, 40.0)
        clouded = self._with_forecast(34.0, 20.0)
        assert (sunny._energy_plan_demand_signature(_power())
                != clouded._energy_plan_demand_signature(_power()))

    def test_a_retrospective_revision_is_not_news(self):
        """.175 16:42:05, the restamp that started this: the day total
        went 42 → 38 while the hours ahead and tomorrow sat still. The
        dampening had re-corrected the morning — hours already produced.
        Nothing the plan reads moved, and the plan it rebuilt proved it by
        allocating the identical blocks."""
        c = self._with_forecast(42.0, 10.7, 25.5)
        first = c._energy_plan_demand_signature(
            _power(), energy=self._made(31.3))
        c._forecast_reader.forecast_data.forecast_today_kwh = 38.0
        assert c._energy_plan_demand_signature(
            _power(), energy=self._made(31.3)) == first

    def test_the_hours_still_ahead_revising_is_news(self):
        """The other half of the same coin: clouds for the rest of the day
        change what the plan can spend, and must re-plan it."""
        c = self._with_forecast(55.0, 40.0)
        first = c._energy_plan_demand_signature(
            _power(), energy=self._made(15.0))
        c._forecast_reader.forecast_data.forecast_remaining_today_kwh = 20.0
        assert c._energy_plan_demand_signature(
            _power(), energy=self._made(15.0)) != first

    def test_the_day_being_spent_is_not_an_ask_change(self):
        """30 kWh of the morning's forecast turned into 30 kWh of measured
        production: the day going exactly to plan. One signature."""
        c = self._with_forecast(55.0, 50.0)
        first = c._energy_plan_demand_signature(
            _power(), energy=self._made(5.0))
        c._forecast_reader.forecast_data.forecast_remaining_today_kwh = 20.0
        assert c._energy_plan_demand_signature(
            _power(), energy=self._made(35.0)) == first

    def test_tomorrow_collapsing_replans(self):
        """The plan reads tomorrow twice — the floor it must leave in the
        battery at sunrise and the room arbitrage may buy into — and the
        trigger did not watch it at all."""
        c = self._with_forecast(40.0, 2.0, 25.0)
        first = c._energy_plan_demand_signature(
            _power(), energy=self._made(38.0))
        c._forecast_reader.forecast_data.forecast_tomorrow_kwh = 4.0
        assert c._energy_plan_demand_signature(
            _power(), energy=self._made(38.0)) != first

    def test_without_a_production_reading_the_deadband_still_holds(self):
        """A bare tick with no energy view cannot explain the decay, so it
        re-anchors per 3 kWh — the behaviour before this change, never
        worse. A frozen solar counter (#681) degrades to exactly this."""
        c = self._with_forecast(55.0, 50.0)
        first = c._energy_plan_demand_signature(_power())
        c._forecast_reader.forecast_data.forecast_remaining_today_kwh = 40.0
        assert c._energy_plan_demand_signature(_power()) != first

    def test_sub_step_revisions_round_away(self):
        a = self._with_forecast(55.0, 40.0)
        b = self._with_forecast(55.9, 40.4)
        assert (a._energy_plan_demand_signature(_power())
                == b._energy_plan_demand_signature(_power()))

    def test_no_forecast_is_a_valid_shape(self):
        c = _coord()
        assert isinstance(c._energy_plan_demand_signature(_power()), tuple)

    def test_the_n1_bucket_edge_oscillation_is_one_night(self):
        """(#759) Quantizing cannot damp a value that LIVES at a bucket
        edge. N1 (.175, 13.08): the dampened forecast wobbled 66.9↔67.1
        around the 67 boundary, the 2-kWh rounding turned that into
        66↔68, and each flip was a full replan — four restamps in 110 s,
        coverage changing hands every 20 s. Same coordinator, same night,
        sub-hysteresis jitter: ONE signature."""
        c = self._with_forecast(70.0, 66.9)
        first = c._energy_plan_demand_signature(
            _power(), energy=self._made(3.1))
        for raw in (67.1, 66.9, 67.3, 66.8, 67.1):
            c._forecast_reader.forecast_data.forecast_remaining_today_kwh = raw
            assert c._energy_plan_demand_signature(
                _power(), energy=self._made(3.1)) == first, (
                f"forecast jitter to {raw} kWh re-planned the night"
            )

    def test_a_real_revision_on_the_same_coordinator_still_replans(self):
        """The hysteresis must not eat the week picture: a genuine
        provider revision (clouds rolling in) re-plans. A real revision
        moves the hours ahead — the dampening scales the whole curve."""
        c = self._with_forecast(70.0, 66.9)
        first = c._energy_plan_demand_signature(
            _power(), energy=self._made(3.1))
        c._forecast_reader.forecast_data.forecast_today_kwh = 60.0
        c._forecast_reader.forecast_data.forecast_remaining_today_kwh = 56.9
        assert c._energy_plan_demand_signature(
            _power(), energy=self._made(3.1)) != first

    def test_a_transient_forecast_outage_keeps_the_anchor(self):
        """A one-cycle unreadable forecast used to flip the term to 0.0
        and back — two replans for one hiccup. Degrade to the last
        anchored value, not to a different night."""
        c = self._with_forecast(66.9, 40.0)
        first = c._energy_plan_demand_signature(_power())

        class _Boom:
            @property
            def forecast_data(self):
                raise RuntimeError("reader down")
        c._forecast_reader = _Boom()
        assert c._energy_plan_demand_signature(_power()) == first


class TestThePriceWindowSlides:
    """(#765, N2 night) The price term fingerprinted ``upcoming_prices[:96]``
    — a SLIDING window. Every hour the leading (now past) slot dropped off,
    the tuple changed, and the plan restamped: 10 restamps in one night with
    prices at absolute timestamps identical throughout. The term now carries
    (absolute timestamp, price) pairs and the comparison knows one rule: a
    shared timestamp's price changing replans, NEW timestamps (tomorrow's
    curve landing) replan, a past slot expiring is silence."""

    def _coord_with_prices(self, pairs):
        from types import SimpleNamespace as NS
        import datetime
        pts = [NS(price=p, timestamp=datetime.datetime.fromisoformat(ts))
               for ts, p in pairs]
        c = _coord(prices=())
        c._tariff_provider = NS(
            get_tariff_data=lambda: NS(upcoming_prices=pts))
        return c

    def test_a_past_slot_expiring_is_not_a_changed_night(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            demand_signature_changed,
        )
        full = [("2026-08-14T22:00:00+02:00", 0.42),
                ("2026-08-14T23:00:00+02:00", 0.12),
                ("2026-08-15T00:00:00+02:00", 0.10)]
        old = self._coord_with_prices(full)._energy_plan_demand_signature(_power())
        new = self._coord_with_prices(full[1:])._energy_plan_demand_signature(_power())
        assert demand_signature_changed(old, new) is False

    def test_a_revised_price_at_a_shared_timestamp_replans(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            demand_signature_changed,
        )
        old = self._coord_with_prices([
            ("2026-08-14T23:00:00+02:00", 0.12)])._energy_plan_demand_signature(_power())
        new = self._coord_with_prices([
            ("2026-08-14T23:00:00+02:00", 0.30)])._energy_plan_demand_signature(_power())
        assert demand_signature_changed(old, new) is True

    def test_tomorrows_curve_landing_replans(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            demand_signature_changed,
        )
        today = [("2026-08-14T23:00:00+02:00", 0.12)]
        old = self._coord_with_prices(today)._energy_plan_demand_signature(_power())
        new = self._coord_with_prices(
            today + [("2026-08-15T01:00:00+02:00", 0.08)]
        )._energy_plan_demand_signature(_power())
        assert demand_signature_changed(old, new) is True

    def test_every_other_term_still_compares_strictly(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            demand_signature_changed,
        )
        a = self._coord_with_prices([("2026-08-14T23:00:00+02:00", 0.12)])
        old = a._energy_plan_demand_signature(_power())
        a.config["ev_chargers"][0]["daily_ev_target"] = 9.9
        new = a._energy_plan_demand_signature(_power())
        assert demand_signature_changed(old, new) is True

    def test_a_stored_old_format_signature_replans_once_never_crashes(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            demand_signature_changed,
        )
        new = self._coord_with_prices(
            [("2026-08-14T23:00:00+02:00", 0.12)])._energy_plan_demand_signature(_power())
        old_format = tuple(
            (("price", (0.42, 0.12)) if x[0] == "price" else x) for x in new)
        assert demand_signature_changed(old_format, new) is True


class TestAPlugBlipIsNotAnUnplug:
    """(#753 family, N2 15.08 on .175) The KEBA's UDP plug sensor drops for a
    cycle with the car still on the cable. A single blip restamped the night
    without the EV and the blip clearing restamped it back: two restamps and
    a window where the plan said "no car tonight", against #638's ≤1
    stop/start per device.

    Caught live: ``binary_sensor.sem_ev_connected`` off in the same cycle
    ``binary_sensor.sem_charger_keba_fa87f74cd3_connected`` was on — both
    read from one ``coordinator.data``, so an in-cycle contradiction.

    The plan asks what execution asks because they now ask the SAME reading:
    ``_confirm_ev_connection`` debounces ``power`` at the top of the cycle,
    so these tests drive it in production order. A disconnect counts after
    three confirmed cycles; a CONNECT is immediate (the night-3 proof
    "connect 00:07:32, stamp same second" must survive).
    """

    def _c(self, *, arrived=True):
        c = _coord()
        c._ev_conn_confirmed = {}
        c._ev_conn_streak = {}
        c._boot_monotonic = None  # long booted — warm-up is not the subject
        if arrived:
            c._confirm_ev_connection(_power(per_charger={"keba": True}))
        return c

    def _cycle(self, c, power):
        """One cycle: confirm at the source (step 1), then the trigger."""
        c._confirm_ev_connection(power)
        return c._energy_plan_demand_signature(power)

    def _blip(self):
        return _power(connected=False, per_charger={"keba": False})

    def test_an_unconfirmed_disconnect_is_not_an_unplug(self):
        c = self._c()
        plugged = self._cycle(c, _power(per_charger={"keba": True}))
        assert self._cycle(c, self._blip()) == plugged

    def test_a_confirmed_unplug_still_replans(self):
        c = self._c()
        plugged = self._cycle(c, _power(per_charger={"keba": True}))
        assert self._cycle(c, self._blip()) == plugged
        assert self._cycle(c, self._blip()) == plugged
        assert self._cycle(c, self._blip()) != plugged

    def test_a_fresh_connect_replans_without_waiting_for_the_debounce(self):
        c = self._c(arrived=False)
        away = self._cycle(c, self._blip())
        fresh = self._cycle(c, _power(connected=True, per_charger={"keba": True}))
        assert fresh != away

    def test_the_collector_and_the_signature_read_the_same_answer(self):
        """One accessor, or the plan's demands and its replan trigger can
        disagree about the same car in the same cycle."""
        c = self._c()
        cfg = c.config["ev_chargers"][0]
        blip = self._blip()
        c._confirm_ev_connection(blip)
        assert c._plan_ev_connected("keba", cfg, blip) is True

    def test_a_confirmed_unplug_reaches_the_collector(self):
        c = self._c()
        cfg = c.config["ev_chargers"][0]
        for _ in range(3):
            gone = self._blip()
            c._confirm_ev_connection(gone)
        assert c._plan_ev_connected("keba", cfg, gone) is False

    def test_a_charger_that_was_never_connected_honours_its_sensor(self):
        """Nothing to hold: an absent car is absent from the first cycle,
        and inventing a hold would starve a sensor-less install's plan."""
        c = self._c(arrived=False)
        cfg = c.config["ev_chargers"][0]
        gone = self._blip()
        c._confirm_ev_connection(gone)
        assert c._plan_ev_connected("keba", cfg, gone) is False

    def test_the_accessor_is_the_only_raw_reader(self):
        """The ratchet: a future call site that asks ``plan_connectivity``
        directly re-opens the bug silently."""
        import ast
        import pathlib
        src = (pathlib.Path(__file__).parent.parent
               / "coordinator" / "coordinator.py").read_text()
        offenders = [
            node.lineno
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "plan_connectivity"
        ]
        allowed = {
            n.lineno
            for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_plan_ev_connected"
            for n in ast.walk(n)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "plan_connectivity"
        }
        assert not (set(offenders) - allowed), (
            f"raw plan_connectivity call outside _plan_ev_connected at "
            f"coordinator.py:{sorted(set(offenders) - allowed)}"
        )

    def test_no_plug_sensor_stays_unknown(self):
        """The tri-state contract survives: ``None`` = nothing to ask, and
        the debounce map must not turn that into a definite no."""
        c = self._c(arrived=False)
        power = SimpleNamespace(ev_connected=False, ev_connected_per_charger=None)
        assert c._plan_ev_connected("keba", {}, power) is None


class TestAShrinkingDeficitIsProgress:
    """(#765 second sighting, PROD 14.08 midday) licht_og_guest_plug's
    deficit crossed a 0.1 h bucket every 6 minutes of running — one replan
    per bucket, ~30 per run. The term-3 comment always promised "a
    shrinking deficit is NOT a demand change"; the comparison now keeps
    that promise: shrink-but-nonzero is the plan WORKING, while a deficit
    growing, a demand appearing or vanishing, or the stop flag flipping is
    real news."""

    def _sig(self, deficit_h, stop=False, did="plug"):
        dev = _dev(did, deficit_h)
        dev.stop_condition_met = stop
        return _coord(devices=(dev,))._energy_plan_demand_signature(_power())

    def _changed(self, old, new):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            demand_signature_changed,
        )
        return demand_signature_changed(old, new)

    def test_running_progress_is_silence(self):
        assert self._changed(self._sig(1.4), self._sig(1.3)) is False
        assert self._changed(self._sig(1.3), self._sig(0.1)) is False

    def test_a_growing_deficit_replans(self):
        assert self._changed(self._sig(1.3), self._sig(1.5)) is True

    def test_a_vanishing_demand_replans(self):
        quiet = _coord()._energy_plan_demand_signature(_power())
        assert self._changed(self._sig(1.3), quiet) is True

    def test_a_new_demand_replans(self):
        quiet = _coord()._energy_plan_demand_signature(_power())
        assert self._changed(quiet, self._sig(1.3)) is True

    def test_a_stop_flag_flip_replans_even_while_shrinking(self):
        assert self._changed(self._sig(1.4, stop=False),
                             self._sig(1.3, stop=True)) is True


class TestTheSignatureMirrorsTheCollectorsGates:
    """(15.08, round 4) A term nobody reads must not re-plan the night.

    #759 fixed the solar term by the rule "watch what the plan READS". The
    same rule has three more instances, and the collector names them itself:
    it gates on the charge MODE before it asks the plug or the car, and on
    the load's control MODE (and night-eligibility) before it asks the
    deficit or the room. Everything past a closed gate is unread — so a
    plug blip on an ``off`` charger, or a deficit ticking on a peak_only
    heater, restamped a plan that could not possibly change.

    Live on .175 (18:33): the mode sat at ``off``, the shared KEBA's plug
    flickered for one cycle, and the night restamped twice — both times
    emitting byte-identical output. That is the #759 shape exactly.
    """

    @staticmethod
    def _charger(mode="min_plus_solar", floor=3.5):
        return [{"id": "keba", "daily_ev_target": floor,
                 "ev_target_time": "07:00", "charge_mode": mode}]

    def test_an_opted_out_chargers_plug_is_not_an_ask_change(self):
        """``off`` stops at the mode gate — the plug is never consulted."""
        c = _coord(chargers=self._charger(mode="off"))
        assert (c._energy_plan_demand_signature(_power(per_charger={"keba": True}))
                == c._energy_plan_demand_signature(
                    _power(per_charger={"keba": False})))

    def test_a_floorless_solar_only_chargers_plug_is_not_an_ask_change(self):
        """#346's default: solar_only with no floor never night-charges."""
        c = _coord(chargers=self._charger(mode="solar_only", floor=0))
        assert (c._energy_plan_demand_signature(_power(per_charger={"keba": True}))
                == c._energy_plan_demand_signature(
                    _power(per_charger={"keba": False})))

    def test_a_planned_chargers_plug_still_replans(self):
        """The gate must not swallow the trigger #638 shipped first."""
        c = _coord(chargers=self._charger())
        assert (c._energy_plan_demand_signature(_power(per_charger={"keba": True}))
                != c._energy_plan_demand_signature(
                    _power(per_charger={"keba": False})))

    def test_a_solar_only_charger_with_a_floor_still_watches_its_plug(self):
        """#634's opt-in puts it back in the night — and back in the term."""
        c = _coord(chargers=self._charger(mode="solar_only", floor=20.0))
        assert (c._energy_plan_demand_signature(_power(per_charger={"keba": True}))
                != c._energy_plan_demand_signature(
                    _power(per_charger={"keba": False})))

    def test_an_opted_out_car_filling_up_is_not_an_ask_change(self):
        """The car-full gate sits BELOW the mode gate in the collector."""
        full = _coord(chargers=self._charger(mode="off"))
        full._ev_taper_detectors = {"keba": SimpleNamespace(still_full=True)}
        blank = _coord(chargers=self._charger(mode="off"))
        assert (full._energy_plan_demand_signature(_power())
                == blank._energy_plan_demand_signature(_power()))

    def test_a_planned_car_filling_up_still_replans(self):
        full = _coord(chargers=self._charger())
        full._ev_taper_detectors = {"keba": SimpleNamespace(still_full=True)}
        blank = _coord(chargers=self._charger())
        assert (full._energy_plan_demand_signature(_power())
                != blank._energy_plan_demand_signature(_power()))

    def test_an_off_mode_loads_deficit_is_not_an_ask_change(self):
        """The collector's first load gate (finding #1): only SURPLUS packs."""
        from custom_components.solar_energy_management.devices.base import (
            DeviceControlMode,
        )
        dev = _dev("heizband", 2.0)
        dev.control_mode = DeviceControlMode.PEAK_ONLY
        assert (_coord(devices=(dev,))._energy_plan_demand_signature(_power())
                == _coord()._energy_plan_demand_signature(_power()))

    def test_a_day_only_loads_deficit_is_not_an_ask_change(self):
        """Neither battery-eligible overnight nor cheap-hours = day only."""
        dev = _dev("pump", 2.0)
        dev.battery_eligible_overnight = False
        dev.top_up_policy = "none"
        assert (_coord(devices=(dev,))._energy_plan_demand_signature(_power())
                == _coord()._energy_plan_demand_signature(_power()))

    def test_an_off_mode_rooms_comfort_ask_is_not_an_ask_change(self):
        """The comfort collector gates on control_mode too."""
        from custom_components.solar_energy_management.devices.base import (
            DeviceControlMode,
        )
        dev = _comfort_ask_dev()
        dev.control_mode = DeviceControlMode.OFF
        assert (_coord(devices=(dev,))._energy_plan_demand_signature(_power())
                == _coord()._energy_plan_demand_signature(_power()))
