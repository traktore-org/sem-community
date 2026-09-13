"""#953 — the grid "finish" source ran first instead of last.

alexmc1510 (Huawei + LUNA, 2.1.0-beta.19, 13.09.2026): a pool pump in mode
"Solar only" with a 4 h/day target switched ON at **07:52:39** — sunrise, to
the second — and was still running at 08:24 with the sun at 78 W, the pack
DISCHARGING 857 W and the meter importing. The battery reclaim closed in #938
is provably inert in that picture (a discharging pack has no charge power to
reclaim), so the pool the pump ran on came from somewhere else. Two
mechanisms could put it there, both of them a price signal buying grid in
broad daylight, and both closed here.

**1. "Finish overnight from: Grid" had no window.** 07:52:39 is when the
sunrise-held meter day rolls (#703/#704): the previous day's met target
becomes a fresh 4 h deficit in that one cycle, and the cheap-hours grid pass
— gated on the deficit and the tariff level and nothing else — bought the
whole target from the meter before the sun had produced a watt. Its twin on
the SAME picker, "Finish overnight from: Battery", has been gated to the
night since #633 ("must not fire in daytime", caught live at 09:10 in full
sun). One control, two backend axes, and the qualifier in its label bound
only one of them.

The gate is the honest reading of "finish": while today's remaining daylight
is at least as long as the outstanding deficit, the sun can still deliver it,
so the meter waits. At night there is no daylight left, so the overnight
promise is untouched — and it is read from ``is_night`` directly, so it never
depends on a sunset reading at all.

**2. ``_apply_price_adjustment`` fabricated up to 10 kW of "surplus".** It
added a virtual +3 kW (cheap) / +10 kW (negative) to the pool *after* the
coordinator had bounded the real surplus by the sun (#620) and the reclaim by
the sun and the meter (#938) — class 80's own ``distributable + virtual``,
listed there and left open. It reached the ordinary SOLAR activation pass, so
a load in mode "Solar only" ("never imports from grid") ran from the grid,
was booked to the "h on solar today" bar, and carried no force marker for the
expiry pass or the deficit LIFO to end. A price signal may now only DAMP the
pool.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    compute_load_intent,
    grid_top_up_defers_to_sun,
    price_damped_pool,
    solar_bounded_surplus,
    sun_can_still_finish,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode

_SC = Path(__file__).resolve().parent.parent / "coordinator" / "surplus_controller.py"

H = 3600.0
#: The reporter's morning: sunrise 07:52, sunset 20:30, screenshot at 08:24.
DAYLIGHT_AT_0752 = 12.6 * H
DEFICIT_4H = 4 * H


# ── 1. the window itself ─────────────────────────────────────────────────


@pytest.mark.unit
class TestSunCanStillFinish:
    def test_the_reporters_morning_defers_to_the_sun(self):
        # 12.6 h of daylight ahead, 4 h still owed → the sun has time.
        assert sun_can_still_finish(
            DEFICIT_4H, daylight_remaining_s=DAYLIGHT_AT_0752, is_night=False)

    def test_the_tail_of_the_day_lets_the_meter_pay(self):
        # 17:30, sunset 20:30: 3 h left cannot cover 4 h → grid may finish.
        assert not sun_can_still_finish(
            DEFICIT_4H, daylight_remaining_s=3 * H, is_night=False)

    def test_night_is_never_blocked_whatever_the_sunset_reading_says(self):
        # The picker's promise rides on is_night alone — TimeManager's clock
        # fallback, not the sun entity. Even a nonsense daylight figure at
        # 03:00 must not withhold the overnight top-up.
        assert not sun_can_still_finish(
            DEFICIT_4H, daylight_remaining_s=12 * H, is_night=True)

    def test_no_sun_data_is_not_a_claim_about_the_sun(self):
        assert not sun_can_still_finish(
            DEFICIT_4H, daylight_remaining_s=None, is_night=False)

    def test_nothing_owed_is_not_a_deferral(self):
        assert not sun_can_still_finish(
            0.0, daylight_remaining_s=DAYLIGHT_AT_0752, is_night=False)

    def test_exactly_enough_daylight_still_belongs_to_the_sun(self):
        assert sun_can_still_finish(
            4 * H, daylight_remaining_s=4 * H, is_night=False)

    def test_it_cannot_flap_once_it_opens(self):
        # While the load runs, the deficit and the daylight both shrink one
        # second per second, so their difference is constant; while it is off
        # only the daylight shrinks. Walk a day at 10-minute steps from the
        # moment the gate opens and assert it never closes again.
        deficit, daylight, opened = DEFICIT_4H, 4 * H + 600.0, False
        for _ in range(60):
            blocked = sun_can_still_finish(
                deficit, daylight_remaining_s=daylight, is_night=False)
            if opened:
                assert not blocked, (deficit, daylight)
            elif not blocked:
                opened = True
            daylight = max(0.0, daylight - 600.0)
            if not blocked:                      # running: the deficit closes
                deficit = max(0.0, deficit - 600.0)
        assert opened


# ── 2. a price signal may damp the pool, never inflate it ────────────────


@pytest.mark.unit
class TestPriceDampedPool:
    def test_a_cheap_hour_no_longer_fabricates_three_kilowatts(self):
        assert price_damped_pool(80.0, "cheap") == 80.0

    def test_a_negative_hour_no_longer_fabricates_ten(self):
        assert price_damped_pool(80.0, "negative") == 80.0

    def test_very_cheap_is_not_a_loophole(self):
        assert price_damped_pool(80.0, "very_cheap") == 80.0

    def test_an_expensive_hour_still_damps(self):
        assert price_damped_pool(2000.0, "expensive") == 1500.0

    def test_damping_never_goes_below_zero(self):
        assert price_damped_pool(200.0, "expensive") == 0.0

    def test_normal_passes_through(self):
        assert price_damped_pool(1234.0, "normal") == 1234.0

    def test_no_level_can_raise_the_pool(self):
        for level in ("negative", "very_cheap", "cheap", "normal",
                      "expensive", "very_expensive", "", "nonsense"):
            for pool in (0.0, 78.0, 1500.0, 9000.0):
                assert price_damped_pool(pool, level) <= pool, (level, pool)


# ── 3. the walk: the reporter's morning ──────────────────────────────────


def _load(device_id="pump", priority=1, min_power=731, *,
          top_up_policy="cheap_hours", deficit_s=DEFICIT_4H):
    """A switch load in mode Surplus. ``top_up_policy`` is the dashboard's
    "Finish overnight from" picker: ``cheap_hours`` = Grid, ``solar_only`` =
    Off. No battery opt-ins either way — the card still reads "Solar only"."""
    d = MagicMock()
    d.device_id = device_id
    d.name = device_id
    d.priority = priority
    d.min_power_threshold = min_power
    d.rated_power = min_power
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = False
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = False
    d.top_up_policy = top_up_policy
    d.remaining_daily_runtime_sec = deficit_s
    d.has_runtime_deficit = deficit_s > 0
    d.needs_offpeak_activation = deficit_s > 0 and not d.is_active
    d.activate = AsyncMock(return_value=min_power)
    d.adjust_power = AsyncMock(return_value=min_power)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.status = MagicMock()
    d.status.allocated_power_w = 0.0
    d.status.state = MagicMock(value="idle")
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d._daily_runtime_meter_day = None
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.is_deadline_approaching = False
    d.start_reserve_w = 0.0
    d.comfort_state = ""
    d.__class__ = MagicMock

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


async def _run(sc, *, cycles=1, daylight_remaining_s, is_night,
               price_level="cheap", solar_w=78.0, export_w=0.0):
    """The reporter's readings through the coordinator's own surplus line."""
    for _ in range(cycles):
        surplus = solar_bounded_surplus(
            grid_export_w=export_w,
            active_draw_w=sc.active_surplus_draw_w(),
            solar_w=solar_w)
        await sc.update(
            surplus, price_level=price_level, reclaim_w=0.0,
            battery_priority=100, battery_soc=81.0, battery_reserve_soc=10.0,
            is_night=is_night, daylight_remaining_s=daylight_remaining_s)


@pytest.mark.unit
class TestTheReportersMorning:
    async def test_without_the_window_the_pump_starts_at_sunrise(self, mock_hass):
        # Pin the failure so the fix below is not a vacuous pass: the gate's
        # own "unknown sun" arm reproduces the pre-#953 pass exactly — deficit
        # + cheap hour and nothing else — and the pump switches on at 07:52
        # with 78 W of sun and a discharging pack.
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load()
        sc.register_device(pump)
        await _run(sc, daylight_remaining_s=None, is_night=False)
        pump.activate.assert_awaited_once()
        assert pump._offpeak_forced is True

    async def test_the_window_keeps_the_meter_out_of_the_morning(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load()
        sc.register_device(pump)
        await _run(sc, cycles=4, daylight_remaining_s=DAYLIGHT_AT_0752,
                   is_night=False)
        assert not pump.activate.called
        assert pump._offpeak_forced is False

    async def test_the_overnight_promise_is_untouched(self, mock_hass):
        # 03:00, cheap window, the same 4 h still owed: this is what the
        # picker sells and it must still happen.
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load()
        sc.register_device(pump)
        await _run(sc, daylight_remaining_s=12 * H, is_night=True, solar_w=0.0)
        pump.activate.assert_awaited_once()
        assert pump._offpeak_forced is True

    async def test_the_tail_of_a_short_day_still_tops_up(self, mock_hass):
        # A December midday cheap window with sunset close: 3 h of daylight
        # cannot cover the 4 h owed, so the meter may finish it.
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load()
        sc.register_device(pump)
        await _run(sc, daylight_remaining_s=3 * H, is_night=False, solar_w=400.0)
        pump.activate.assert_awaited_once()
        assert pump._offpeak_forced is True

    async def test_a_night_run_does_not_ride_into_the_morning(self, mock_hass):
        # Class 17: the start gate alone would leave a top-up that started
        # legitimately at 05:00 running all morning. The force-expiry twin
        # ends it the cycle the daylight can cover what is left.
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(deficit_s=3 * H)
        pump.is_active = True
        pump._sem_owned = True
        pump._offpeak_forced = True
        # Stamped the way production stamps it (#703): the load's OWN meter
        # day, which does NOT roll until sunrise. So at night-end (07:00, or
        # sunrise itself — the surplus pass runs before update_daily_runtime
        # in the same cycle) the pre-existing "day rollover" branch is
        # silent and this clause is the only thing that can end the run.
        pump._daily_runtime_meter_day = dt_util.now().date()
        pump._offpeak_forced_date = pump._daily_runtime_meter_day
        pump.needs_offpeak_activation = False
        pump.get_current_consumption = MagicMock(return_value=731.0)
        sc.register_device(pump)
        await _run(sc, daylight_remaining_s=DAYLIGHT_AT_0752, is_night=False)
        assert pump.deactivate.called
        assert pump._offpeak_forced is False

    async def test_a_night_run_is_not_cut_while_it_is_still_night(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(deficit_s=3 * H)
        pump.is_active = True
        pump._sem_owned = True
        pump._offpeak_forced = True
        pump._daily_runtime_meter_day = dt_util.now().date()
        pump._offpeak_forced_date = pump._daily_runtime_meter_day
        pump.needs_offpeak_activation = False
        pump.get_current_consumption = MagicMock(return_value=731.0)
        sc.register_device(pump)
        await _run(sc, daylight_remaining_s=12 * H, is_night=True, solar_w=0.0)
        assert not pump.deactivate.called
        assert pump._offpeak_forced is True

    async def test_a_solar_only_picker_still_never_grid_forces(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(top_up_policy="solar_only")
        sc.register_device(pump)
        for night in (True, False):
            await _run(sc, daylight_remaining_s=None, is_night=night,
                       solar_w=0.0)
        assert not pump.activate.called


@pytest.mark.unit
class TestTheVirtualSurplusIsGone:
    async def test_a_cheap_hour_no_longer_starts_a_solar_only_load(self, mock_hass):
        # The second mechanism: price_responsive_mode on (dynamic tariff),
        # cheap hour, 78 W of sun. Nothing about this load opted into the
        # grid — its picker is Off — and it must stay off.
        sc = SurplusController(mock_hass, regulation_offset=0)
        sc.price_responsive_mode = True
        pump = _load(top_up_policy="solar_only")
        sc.register_device(pump)
        await _run(sc, cycles=4, daylight_remaining_s=DAYLIGHT_AT_0752,
                   is_night=False)
        assert not pump.activate.called

    async def test_the_old_virtual_pool_would_have_started_it(self, mock_hass):
        # Non-vacuity for the clause above: hand the same walk the pool the
        # +3 kW used to make and the Solar-only pump switches on, unmarked.
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(top_up_policy="solar_only")
        sc.register_device(pump)
        for _ in range(4):
            await sc.update(78.0 + 3000.0, price_level="cheap", reclaim_w=0.0,
                            battery_priority=100, is_night=False,
                            daylight_remaining_s=DAYLIGHT_AT_0752)
        assert pump.activate.called
        assert pump._offpeak_forced is False   # no marker to ever expire

    async def test_an_expensive_hour_still_damps_the_pool(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        sc.price_responsive_mode = True
        pump = _load(top_up_policy="solar_only", min_power=900)
        sc.register_device(pump)
        # 1.2 kW of real surplus, damped by 500 → 700 W, below the load's bar.
        for _ in range(4):
            await sc.update(1200.0, price_level="expensive", reclaim_w=0.0,
                            battery_priority=100, is_night=False,
                            daylight_remaining_s=DAYLIGHT_AT_0752)
        assert not pump.activate.called
        assert sc.allocation_data.distributable_surplus_w == pytest.approx(700.0)


# ── 3b. the comfort band is not something the sun can "finish" ───────────


@pytest.mark.unit
class TestComfortIsExempt:
    def _dev(self, state):
        d = _load()
        d.comfort_state = state
        return d

    def test_a_breached_band_does_not_wait_for_the_afternoon(self):
        # ComfortBandMixin makes a breached band read as a runtime deficit.
        # A cold room is about NOW — deferring it to the sun would leave it
        # cold all morning because the load also happens to have a floor.
        assert not grid_top_up_defers_to_sun(
            self._dev("forced"), daylight_remaining_s=DAYLIGHT_AT_0752,
            is_night=False)

    def test_a_planned_banking_block_is_the_plans_to_place(self):
        # The #638-C5 banking pass sets _offpeak_forced on a "willing" band.
        # The finish window must not cut a run the joint plan created.
        assert not grid_top_up_defers_to_sun(
            self._dev("willing"), daylight_remaining_s=DAYLIGHT_AT_0752,
            is_night=False)

    def test_a_plain_runtime_floor_still_waits(self):
        assert grid_top_up_defers_to_sun(
            self._dev(""), daylight_remaining_s=DAYLIGHT_AT_0752,
            is_night=False)

    async def test_a_banking_run_is_not_cut_by_the_expiry_twin(self, mock_hass):
        # The walk, not just the predicate: the imperative force-expiry pass
        # leaves a comfort-banking run alone in the morning, where the plain
        # runtime-floor top-up beside it would be ended.
        sc = SurplusController(mock_hass, regulation_offset=0)
        dev = _load(deficit_s=3 * H)
        dev.comfort_state = "willing"
        dev.is_active = True
        dev._sem_owned = True
        dev._offpeak_forced = True
        dev._daily_runtime_meter_day = dt_util.now().date()
        dev._offpeak_forced_date = dev._daily_runtime_meter_day
        dev.needs_offpeak_activation = False
        dev.get_current_consumption = MagicMock(return_value=731.0)
        sc.register_device(dev)
        await _run(sc, daylight_remaining_s=DAYLIGHT_AT_0752, is_night=False)
        assert not dev.deactivate.called
        assert dev._offpeak_forced is True


# ── 4. the intent path says the same thing ───────────────────────────────


@pytest.mark.unit
class TestDesiredStateParity:
    def _intent(self, **kw):
        d = _load()
        for k, v in kw.pop("device", {}).items():
            setattr(d, k, v)
        return compute_load_intent(
            d, remaining_surplus_w=0.0, price_is_cheap=True, **kw)

    def test_the_morning_is_no_source(self):
        i = self._intent(is_night=False, daylight_remaining_s=DAYLIGHT_AT_0752)
        assert i.on is False and i.source is None

    def test_the_night_is_cheap_grid(self):
        i = self._intent(is_night=True, daylight_remaining_s=12 * H)
        assert i.on is True and i.source == "cheap_grid"

    def test_the_tail_of_the_day_is_cheap_grid(self):
        i = self._intent(is_night=False, daylight_remaining_s=3 * H)
        assert i.on is True and i.source == "cheap_grid"

    def test_an_unknown_sun_keeps_the_pre_fix_answer(self):
        i = self._intent(is_night=False, daylight_remaining_s=None)
        assert i.on is True and i.source == "cheap_grid"

    def test_a_running_top_up_in_the_morning_loses_its_marker(self):
        # No stop clause on this path by design: the intent is rebuilt each
        # cycle and _apply_source_markers derives _offpeak_forced from the
        # source, so a closed gate drops the marker by construction.
        i = self._intent(is_night=False, daylight_remaining_s=DAYLIGHT_AT_0752,
                         device={"is_active": True, "_offpeak_forced": True,
                                 "_sem_owned": True})
        assert i.on is False and i.source is None

    def test_real_surplus_still_carries_a_running_load(self):
        # The stop must not be a blanket one: the same load with the sun
        # behind it keeps running, as solar, marker cleared.
        d = _load()
        d.is_active = True
        d._offpeak_forced = True
        i = compute_load_intent(
            d, remaining_surplus_w=2000.0, price_is_cheap=True,
            is_night=False, daylight_remaining_s=DAYLIGHT_AT_0752)
        assert i.on is True and i.source == "solar"


# ── 4b. the number the gate is fed ───────────────────────────────────────


class _TM:
    """Just enough TimeManager for _daylight_remaining_s_now."""

    def __init__(self, hhmm, source, sunrise=None):
        self._hhmm, self._last_sunset_source, self._sunrise = \
            hhmm, source, sunrise

    def get_sunset_plus_10_time(self):
        return self._hhmm

    def get_sunrise_datetime(self):
        return self._sunrise


def _daylight(tm):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    shim = MagicMock()
    shim.time_manager = tm
    return SEMCoordinator._daylight_remaining_s_now(shim)


@pytest.mark.unit
class TestDaylightRemaining:
    def test_a_fabricated_sunset_is_not_a_reading(self):
        # get_sunset_plus_10_time() returns a hard-coded 20:30 on ANY
        # failure and marks the source. Gating a PAID action on a sunset
        # nobody measured is bug class 40 — so this reads None, and the
        # top-up keeps its pre-#953 behaviour instead of guessing.
        assert _daylight(_TM("20:30", "fallback_default")) is None

    def test_a_blink_reads_none_not_a_four_hour_jump(self):
        # The cycle after a real 16:31 sunset, sun.sun is briefly absent.
        # None leaves the gate open — it must never STOP a running top-up
        # by inventing daylight.
        assert _daylight(_TM("16:31", "fallback_default")) is None

    def test_the_dark_hour_before_sunrise_is_not_counted_as_sun(self):
        # Winter: night ends at 07:00 (min(sunrise, latest_end)) but the
        # sun does not rise until 08:03. Measuring from ``now`` would book
        # that dark hour as daylight.
        from datetime import timedelta
        now = dt_util.now()
        sunset = (now + timedelta(hours=4)).replace(second=0, microsecond=0)
        sunrise = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        tm = _TM(sunset.strftime("%H:%M"), "sun_integration", sunrise=sunrise)
        got = _daylight(tm)
        # 3 h of sun ahead, not 4 — the hour before sunrise is not daylight.
        assert got is not None and 3 * H - 120 <= got <= 3 * H + 120

    def test_a_sunset_already_behind_us_is_zero_not_negative(self):
        from datetime import timedelta
        past = (dt_util.now() - timedelta(hours=2)).strftime("%H:%M")
        assert _daylight(_TM(past, "sun_integration", sunrise=None)) == 0.0

    def test_a_measured_sunset_is_the_seconds_to_it(self):
        now = dt_util.now()
        target = now + __import__("datetime").timedelta(minutes=90)
        tm = _TM(target.strftime("%H:%M"), "sun_integration", sunrise=None)
        got = _daylight(tm)
        assert got is not None and 5000.0 <= got <= 5500.0


# ── 5. the guard: neither door can be reopened ───────────────────────────


def _func(name: str) -> ast.AST:
    tree = ast.parse(_SC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {_SC.name}")


def _calls(node: ast.AST) -> list:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.append(f.id if isinstance(f, ast.Name)
                       else (f.attr if isinstance(f, ast.Attribute) else ""))
    return out


@pytest.mark.unit
class TestSourceGuards:
    def test_the_price_path_contains_no_addition_at_all(self):
        # The invariant is structural, not a property of today's branches:
        # nothing in the price path may ADD to the pool it was handed.
        for name in ("price_damped_pool", "_apply_price_adjustment"):
            for n in ast.walk(_func(name)):
                assert not (isinstance(n, ast.BinOp)
                            and isinstance(n.op, ast.Add)), \
                    f"{name} adds to the pool again (#953)"

    def test_the_price_path_ends_in_a_clamp_to_its_input(self):
        assert "min" in _calls(_func("price_damped_pool"))

    def test_the_cheap_hours_pass_consults_the_finish_window(self):
        # Both halves, in the one function PROD runs: the start gate in the
        # off-peak activation pass and the force-expiry twin.
        assert _calls(_func("update")).count("grid_top_up_defers_to_sun") >= 2

    def test_the_intent_path_consults_it_too(self):
        assert "grid_top_up_defers_to_sun" in _calls(
            _func("compute_load_intent"))

    def test_the_one_wrapper_is_the_only_door_to_the_window(self):
        # Every caller goes through grid_top_up_defers_to_sun, so the comfort
        # exemption cannot be forgotten at one of the three sites.
        for name in ("update", "compute_load_intent"):
            assert "sun_can_still_finish" not in _calls(_func(name)), name
        assert "sun_can_still_finish" in _calls(
            _func("grid_top_up_defers_to_sun"))

    def test_the_coordinator_feeds_the_window_from_the_time_manager(self):
        coord = Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"
        tree = ast.parse(coord.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "update" \
                    and any(k.arg == "daylight_remaining_s" for k in node.keywords):
                kw = next(k for k in node.keywords
                          if k.arg == "daylight_remaining_s")
                assert isinstance(kw.value, ast.Call)
                assert kw.value.func.attr == "_daylight_remaining_s_now"
                break
        else:
            raise AssertionError(
                "the surplus update() is not handed daylight_remaining_s (#953)")
        # and that helper reads the SAME sun authority is_night_mode does
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) \
                    and node.name == "_daylight_remaining_s_now":
                assert "get_sunset_plus_10_time" in _calls(node)
                break
        else:
            raise AssertionError("_daylight_remaining_s_now not found")
