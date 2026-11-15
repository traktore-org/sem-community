"""(#1362) SEM never planned a night battery charge on a G12w tariff.

@matekogon, Calendar tariff through a Schedule helper (the #1310 home):
peak Mon-Fri 06:00-13:00 and 15:00-22:00 at 1.25 PLN, off-peak 0.6387 PLN,
the weekend all off-peak. The battery scheduler was on, the pack was near
empty, and the plan showed no battery charge: scheduler state
``not_profitable`` every night.

Cause (class 104, third catch): the break-even read the daytime rate with
``get_price_at(today 14:00)`` and the night rate with
``get_price_at(today 02:00)``. At the 21:00 trigger that is the day just
gone, and 14:00 is in G12w's midday off-peak window, so "peak" was the
off-peak price and a night charge never paid. A static tariff asked the
wrong day too: Friday night charged for a Saturday with one price, Sunday
night never charged for Monday.

Now every provider answers ``get_next_daytime_rate`` and
``get_charge_window_rate``: the base class asks ``get_price_at`` for each
quarter hour of the next window. The coordinator no longer samples a clock.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
    SchedulerState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    StaticTariffProvider,
    TariffProvider,
)

from .test_battery_scheduler_rolling_horizon import (
    COORD_DT_PATH,
    _build_rate_coordinator,
)

PEAK = 1.25
OFF = 0.6387
WORKDAYS = [0, 1, 2, 3, 4]
HELPER = "schedule.harmonogram_g12w"


def _at(day, hour, minute=0):
    """A local, tz-aware moment. 2026-11-16 is a Monday."""
    return datetime(2026, 11, day, hour, minute,
                    tzinfo=dt_util.get_default_time_zone())


MON, TUE, FRI, SAT, SUN = 16, 17, 20, 21, 15

#: G12w daytime 07-20: peak 07-13 (6 h) and 15-20 (5 h), off-peak 13-15.
WORKDAY_DAYTIME = (11 * PEAK + 2 * OFF) / 13


def _g12w_rules():
    return CalendarTariffProvider(
        None, peak_rate=PEAK, off_peak_rate=OFF, export_rate=0.0,
        rules=[
            {"days": WORKDAYS, "start": "06:00", "end": "13:00", "tariff": "ht"},
            {"days": WORKDAYS, "start": "15:00", "end": "22:00", "tariff": "ht"},
        ],
    )


def _helper_week():
    blocks = [{"from": time(6, 0), "to": time(13, 0), "data": {}},
              {"from": time(15, 0), "to": time(22, 0), "data": {}}]
    days = ("monday", "tuesday", "wednesday", "thursday", "friday")
    return {d: (list(blocks) if d in days else [])
            for d in days + ("saturday", "sunday")}


def _g12w_helper(*, state="on", next_event=None, week=True):
    """The reporter's real input: a Schedule helper whose blocks are peak."""
    hass = MagicMock()
    attrs = {"next_event": next_event} if next_event else {}
    states = {HELPER: SimpleNamespace(state=state, last_updated="t0",
                                      attributes=attrs)}
    hass.states.get = lambda eid: states.get(eid)
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock(return_value={HELPER: _helper_week()})
    p = CalendarTariffProvider(hass, peak_rate=PEAK, off_peak_rate=OFF,
                               export_rate=0.0, rules=[],
                               schedule_entity=HELPER)
    return p


def _static():
    return StaticTariffProvider(peak_rate=PEAK, off_peak_rate=OFF,
                                export_rate=0.0, peak_start=7, peak_end=20)


def _now(moment):
    return patch.object(dt_util, "now", return_value=moment)


# ---------------------------------------------------------------------------
# The provider: the next daytime is the day the charge is for
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTheNextDaytimeIsTheDayTheChargeIsFor:

    @pytest.mark.parametrize("now, want", [
        (_at(MON, 21), WORKDAY_DAYTIME),       # → Tuesday
        (_at(SUN, 21), WORKDAY_DAYTIME),       # → Monday (was: Sunday 14:00)
        (_at(FRI, 21), OFF),                   # → Saturday, one price
        (_at(SAT, 21), OFF),                   # → Sunday, one price
        (_at(TUE, 2), WORKDAY_DAYTIME),        # after midnight → today
        (_at(TUE, 2, 7), WORKDAY_DAYTIME),     # off the quarter hour
    ])
    def test_g12w_rules(self, now, want):
        p = _g12w_rules()
        with _now(now):
            assert p.get_next_daytime_rate() == pytest.approx(want)

    def test_the_old_sample_was_off_peak_on_every_workday(self):
        """Why the reporter never got a charge: 14:00 is off-peak."""
        p = _g12w_rules()
        for day in (MON, TUE, FRI):
            assert p.get_price_at(_at(day, 14)) == pytest.approx(OFF)

    @pytest.mark.parametrize("now", [_at(MON, 21), _at(FRI, 21), _at(SUN, 21)])
    def test_the_night_window_is_off_peak(self, now):
        p = _g12w_rules()
        with _now(now):
            assert p.get_charge_window_rate(hours=4.0, within_hours=12) == (
                pytest.approx(OFF))

    def test_the_night_window_is_the_cheapest_hours_not_the_average(self):
        """At 20:00 the next 12 h hold two peak hours; 4 h of off-peak win."""
        p = _g12w_rules()
        with _now(_at(MON, 20)):
            assert p.get_charge_window_rate(hours=4.0, within_hours=12) == (
                pytest.approx(OFF))

    def test_a_short_window_holds_peak_hours(self):
        """Within 1 h from 21:00 only peak is left: the answer says so."""
        p = _g12w_rules()
        with _now(_at(MON, 21)):
            assert p.get_charge_window_rate(hours=1.0, within_hours=1) == (
                pytest.approx(PEAK))

    def test_fewer_known_hours_than_the_charge_is_no_rate(self):
        """(review) A helper read only until 22:00 knows one peak hour of
        the night. Its average is not the night's rate."""
        p = _g12w_rules()
        real = p.get_price_at
        p.get_price_at = (lambda when: real(when)
                          if when < _at(MON, 22) else None)
        with _now(_at(MON, 21)):
            assert p.get_charge_window_rate(hours=4.0, within_hours=12) is None
            assert p.get_charge_window_rate(hours=1.0, within_hours=12) == (
                pytest.approx(PEAK))

    @pytest.mark.parametrize("now, day, want", [
        # (review) An 18:00 or 19:00 trigger: the rest of today is not
        # what the night charge is for.
        (_at(FRI, 18), SAT, OFF),
        (_at(FRI, 19, 44), SAT, OFF),
        (_at(SUN, 18), MON, WORKDAY_DAYTIME),
        (_at(MON, 19), TUE, WORKDAY_DAYTIME),
        (_at(TUE, 2), TUE, WORKDAY_DAYTIME),
        (_at(TUE, 9), TUE, (4 * PEAK + 2 * OFF + 5 * PEAK) / 11),
        (_at(MON, 21), MON, None),          # the day is over
    ])
    def test_the_plan_day(self, now, day, want):
        p = _g12w_rules()
        with _now(now):
            got = p.get_next_daytime_rate(day=_at(day, 0).date())
        if want is None:
            assert got is None
        else:
            assert got == pytest.approx(want)

    def test_thursday_night_is_for_friday(self):
        p = _g12w_rules()
        with _now(_at(19, 21)):     # Thursday 19.11
            assert p.get_next_daytime_rate() == pytest.approx(WORKDAY_DAYTIME)

    def test_the_first_window_ends_the_search(self):
        """A static tariff on Friday night: Saturday's window, not Monday's."""
        p = _static()
        with _now(_at(FRI, 21)):
            assert p.get_next_daytime_rate() == pytest.approx(OFF)

    def test_a_clock_change_night(self):
        """Europe/Warsaw, 25.10.2026: the clocks go back at 03:00. Twelve
        hours are 48 steps, and the next daytime is Sunday's (off-peak)."""
        import zoneinfo
        old = dt_util.get_default_time_zone()
        tz = zoneinfo.ZoneInfo("Europe/Warsaw")
        dt_util.set_default_time_zone(tz)
        try:
            now = datetime(2026, 10, 24, 21, 0, tzinfo=tz)   # Saturday
            p = _static()
            steps = list(p._next_steps(now, 12))
            assert len(steps) == 48
            # real time, not wall time: the 02:00 hour comes twice
            assert (dt_util.as_utc(steps[-1]) - dt_util.as_utc(steps[0])
                    == timedelta(hours=11, minutes=45))
            assert steps[-1].hour == 7 and steps[-1].minute == 45
            with _now(now):
                assert p.get_next_daytime_rate() == pytest.approx(OFF)
                assert p.get_next_daytime_rate(
                    day=datetime(2026, 10, 26).date()) == pytest.approx(PEAK)
                assert p.get_charge_window_rate() == pytest.approx(OFF)
        finally:
            dt_util.set_default_time_zone(old)

    @pytest.mark.parametrize("now, want", [
        (_at(FRI, 21), OFF),        # Saturday: no peak
        (_at(SUN, 21), PEAK),       # Monday 07-20 is all peak
        (_at(MON, 2), PEAK),        # after midnight → today
    ])
    def test_static_tariff(self, now, want):
        p = _static()
        with _now(now):
            assert p.get_next_daytime_rate() == pytest.approx(want)
            assert p.get_charge_window_rate() == pytest.approx(OFF)

    def test_no_known_price_is_no_rate(self):
        class _Blind(TariffProvider):
            get_current_import_rate = get_current_export_rate = (
                lambda self: 0.0)
            get_price_level = get_tariff_data = lambda self: None

            def get_price_at(self, when):
                return None

        p = _Blind()
        with _now(_at(MON, 21)):
            assert p.get_next_daytime_rate() is None
            assert p.get_charge_window_rate() is None

    def test_half_a_window_is_not_its_average(self):
        """One unknown daytime hour: no rate, not the average of the rest
        (it would read a known off-peak morning as the whole day)."""
        p = _g12w_rules()
        real = p.get_price_at

        def _gap(when):
            return None if when.hour == 16 else real(when)

        p.get_price_at = _gap
        with _now(_at(MON, 21)):
            assert p.get_next_daytime_rate() is None
            assert p.get_charge_window_rate() == pytest.approx(OFF)

    def test_the_dynamic_provider_reads_only_the_plan_day(self):
        """(review) At an 18:00 trigger the series' rest of today is not
        the day the charge is for."""
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            PriceLevel, PricePoint,
        )
        now = _at(FRI, 18)
        start = _at(FRI, 18)
        prices = [PricePoint(timestamp=start + timedelta(hours=i),
                             price=(2.0 if i < 2 else 0.5),
                             level=PriceLevel.NORMAL) for i in range(30)]
        prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
        prov._read_prices_list = lambda: prices
        prov._grid_import_surcharge = lambda: 0.0
        with _now(now):
            assert prov.get_next_daytime_rate(
                day=_at(SAT, 0).date()) == pytest.approx(0.5)
            # without the day, the rest of Friday (18-20) is mixed in
            assert prov.get_next_daytime_rate() > 0.5

    def test_the_dynamic_provider_keeps_its_series(self):
        """The base answers only for providers without a price series."""
        for name in ("get_next_daytime_rate", "get_charge_window_rate"):
            assert (getattr(DynamicTariffProvider, name)
                    is not getattr(TariffProvider, name))
            assert (getattr(StaticTariffProvider, name)
                    is getattr(TariffProvider, name))
            assert (getattr(CalendarTariffProvider, name)
                    is getattr(TariffProvider, name))


@pytest.mark.unit
class TestTheReportersScheduleHelper:

    @pytest.mark.asyncio
    async def test_monday_night_sees_tuesdays_peak(self):
        # Monday 21:00: the helper is on until its 22:00 edge.
        now = _at(MON, 21)
        p = _g12w_helper(state="on", next_event=_at(MON, 22))
        with _now(now):
            assert await p.async_refresh_service_prices() is True
            assert p.get_next_daytime_rate() == pytest.approx(WORKDAY_DAYTIME)
            assert p.get_charge_window_rate() == pytest.approx(OFF)

    @pytest.mark.asyncio
    async def test_sunday_night_sees_mondays_peak(self):
        now = _at(SUN, 21)
        p = _g12w_helper(state="off", next_event=_at(MON, 6))
        with _now(now):
            await p.async_refresh_service_prices()
            assert p.get_next_daytime_rate() == pytest.approx(WORKDAY_DAYTIME)

    @pytest.mark.asyncio
    async def test_friday_night_has_no_peak_tomorrow(self):
        now = _at(FRI, 21)
        p = _g12w_helper(state="on", next_event=_at(FRI, 22))
        with _now(now):
            await p.async_refresh_service_prices()
            assert p.get_next_daytime_rate() == pytest.approx(OFF)

    def test_a_week_not_read_is_no_rate(self):
        """Before ``schedule.get_schedule`` answered, tomorrow is unknown:
        no rate, so the configured rates stand in — as before."""
        p = _g12w_helper(state="off", next_event=_at(TUE, 6))
        with _now(_at(MON, 22, 30)):
            assert p.get_next_daytime_rate() is None


# ---------------------------------------------------------------------------
# The coordinator: the rates the scheduler is handed, and its answer
# ---------------------------------------------------------------------------

def _reporter_scheduler():
    sched = BatteryChargeScheduler(MagicMock(), SchedulerConfig.from_config({
        "battery_charge_scheduler_enabled": True,
        "battery_capacity_kwh": 30.0,
        "battery_max_charge_power_w": 2000,
        "battery_roundtrip_efficiency": 0.93,
        "battery_cycle_cost": 0,
        "battery_max_target_soc": 50,
        "battery_min_deficit_kwh": 1,
    }))
    return sched


async def _rates_at(provider, now):
    coord, scheduler = _build_rate_coordinator(
        provider, now, forecast_today=3.4, forecast_tomorrow=3.4)
    coord.config = {"electricity_off_peak_rate": OFF,
                    "electricity_import_rate": PEAK}
    # The plan after the evaluation is not what this pins.
    coord._shadow_energy_plan = MagicMock()
    with patch(COORD_DT_PATH) as mock_dt, _now(now):
        mock_dt.now.return_value = now
        await coord._maybe_run_scheduler_evaluation(
            MagicMock(battery_soc=2.0))
    return scheduler.evaluate.call_args.kwargs


@pytest.mark.unit
class TestTheSchedulerGetsTheNextDay:

    @pytest.mark.asyncio
    async def test_a_workday_night_is_worth_a_charge(self):
        kwargs = await _rates_at(_g12w_rules(), _at(MON, 21))
        assert kwargs["peak_rate"] == pytest.approx(WORKDAY_DAYTIME)
        assert kwargs["off_peak_rate"] == pytest.approx(OFF)

        sched = _reporter_scheduler()
        with _now(_at(MON, 21)):
            dec = sched.evaluate(
                current_soc=2.0, forecast_tomorrow_kwh=3.4,
                expected_consumption_kwh=12.0,
                off_peak_rate=kwargs["off_peak_rate"],
                peak_rate=kwargs["peak_rate"])
        assert dec.state is SchedulerState.SCHEDULED, dec.reason
        assert dec.target_soc > 2.0

    @pytest.mark.asyncio
    async def test_a_night_before_a_one_price_day_is_not(self):
        kwargs = await _rates_at(_g12w_rules(), _at(FRI, 21))
        assert kwargs["peak_rate"] == pytest.approx(OFF)
        sched = _reporter_scheduler()
        with _now(_at(FRI, 21)):
            dec = sched.evaluate(
                current_soc=2.0, forecast_tomorrow_kwh=3.4,
                expected_consumption_kwh=12.0,
                off_peak_rate=kwargs["off_peak_rate"],
                peak_rate=kwargs["peak_rate"])
        assert dec.state is SchedulerState.NOT_PROFITABLE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("now, want", [
        (_at(FRI, 18), OFF),                # → Saturday
        (_at(SUN, 19), WORKDAY_DAYTIME),    # → Monday
        (_at(TUE, 2), WORKDAY_DAYTIME),     # → today
    ])
    async def test_an_early_trigger_prices_the_plan_day(self, now, want):
        """(review) The trigger hour can be 18:00: the forecast's day and
        the price's day are one."""
        kwargs = await _rates_at(_g12w_rules(), now)
        assert kwargs["peak_rate"] == pytest.approx(want)

    @pytest.mark.asyncio
    async def test_static_sunday_night_plans_for_monday(self):
        kwargs = await _rates_at(_static(), _at(SUN, 21))
        assert kwargs["peak_rate"] == pytest.approx(PEAK)
        assert kwargs["off_peak_rate"] == pytest.approx(OFF)

    @pytest.mark.asyncio
    async def test_a_rate_no_one_knows_falls_back_to_the_config(self):
        p = _g12w_helper(state="off", next_event=_at(TUE, 6))   # week unread
        kwargs = await _rates_at(p, _at(MON, 22, 30))
        assert kwargs["peak_rate"] == pytest.approx(PEAK)        # config


@pytest.mark.unit
class TestNoClockSample:
    """The break-even reads the provider's next windows, never a moment
    built from today's clock (``now.replace(hour=…)``) — that moment is in
    the day just gone at the 21:00 trigger."""

    def test_the_evaluation_builds_no_moment_from_the_clock(self):
        src = textwrap.dedent(inspect.getsource(
            SEMCoordinator._maybe_run_scheduler_evaluation))
        tree = ast.parse(src)
        bad = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "get_price_at":
                bad.append(f"get_price_at at line {node.lineno}")
            if (isinstance(fn, ast.Attribute) and fn.attr == "replace"
                    and any(k.arg == "hour" for k in node.keywords)):
                bad.append(f".replace(hour=…) at line {node.lineno}")
        assert not bad, bad

    def test_the_check_catches_a_clock_sample(self):
        """The check above is not vacuous."""
        src = textwrap.dedent("""
            def f(self, now):
                return self._tariff_provider.get_price_at(
                    now.replace(hour=14, minute=0))
        """)
        tree = ast.parse(src)
        hits = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and (n.func.attr == "get_price_at"
                     or (n.func.attr == "replace"
                         and any(k.arg == "hour" for k in n.keywords)))]
        assert len(hits) == 2


def test_dates_are_the_weekdays_named():
    assert _at(MON, 0).weekday() == 0
    assert _at(TUE, 0).weekday() == 1
    assert _at(FRI, 0).weekday() == 4
    assert _at(SAT, 0).weekday() == 5
    assert _at(SUN, 0).weekday() == 6
    assert _at(SUN, 0) + timedelta(days=1) == _at(MON, 0)
