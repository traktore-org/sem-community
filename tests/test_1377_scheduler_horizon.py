"""(#1377) The night charge compared two different spans.

@fburgod, Tesla Powerwall at 0 % with a 20 % reserve, cheap 20:00-04:00,
dear 04:00-20:00. At 21:30 the plan said "Solar forecast covers expected
consumption", target 0 %, and planned no charge. The evening evaluation set
ALL of tomorrow's solar against only the hours of TODAY that remain, and the
battery's floor and the dear hours before sunrise were in no sum.

Now both sides are the plan day, and the battery carries the dear hours
until the sun covers the house, from the floor up.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
    SchedulerState,
    bridge_slots,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

COORD_DT = "custom_components.solar_energy_management.coordinator.coordinator.dt_util"
CHEAP, DEAR = 0.10, 0.30


def _cfg(**kw):
    base = dict(enabled=True, battery_capacity_kwh=13.5,
                battery_usable_capacity_kwh=13.5, battery_min_soc=5.0,
                roundtrip_efficiency=0.92, min_deficit_kwh=2.0,
                forecast_confidence=0.8, max_target_soc=95.0)
    base.update(kw)
    return SchedulerConfig(**base)


def _sched(**kw):
    return BatteryChargeScheduler(MagicMock(), _cfg(**kw))


def _day_start(day=18):
    return datetime(2026, 11, day, tzinfo=dt_util.get_default_time_zone())


def _price(when):
    """Cheap 20-04, dear 04-20 (the reporter's calendar tariff)."""
    return DEAR if 4 <= when.hour < 20 else CHEAP


# House: 400 W at night, 1 kW over 04-07, sun covers from 08:00.
CONS = [400.0] * 4 + [1000.0] * 3 + [500.0] * 17          # 3 kWh in 04-07
SOLAR = [0.0] * 8 + [3000.0] * 8 + [0.0] * 8


def _slots():
    return bridge_slots(_day_start(), CONS, SOLAR, _price)


class _Predictor:
    """The coordinator's predictor: a trained 24 h house, no sun gaps."""
    def __init__(self, cons=CONS, solar=SOLAR):
        self.cons, self.solar = cons, solar

    def predict_consumption_24h(self, start):
        return list(self.cons)

    def predict_solar_24h(self, start):
        return list(self.solar)

    def predict_consumption_for_day_kwh(self, start):
        return sum(self.cons) / 1000.0

    def predict_consumption_today_kwh(self, now):
        return sum(self.cons[now.hour:]) / 1000.0


def _eval(soc, slots, forecast=20.0, consumption=11.0, floor=20.0,
          off=CHEAP, peak=DEAR, **cfg):
    s = _sched(**cfg)
    with patch.object(dt_util, "now", return_value=datetime(
            2026, 11, 17, 21, 30, tzinfo=dt_util.get_default_time_zone())):
        return s.evaluate(
            current_soc=soc, forecast_tomorrow_kwh=forecast,
            expected_consumption_kwh=consumption, off_peak_rate=off,
            peak_rate=peak, floor_soc=floor, bridge_slots=slots)


@pytest.mark.unit
class TestTheBatteryCarriesTheDearHours:
    def test_the_bridge_is_the_hours_before_the_sun(self):
        dear = [k for p, k in _slots() if p == DEAR]
        assert sum(dear) == pytest.approx(3.0 + 0.5)   # 04-07 + 07:00 hour
        assert len(_slots()) == 8                       # stops at 08:00

    def test_reporters_night_charges_to_at_least_the_floor(self):
        d = _eval(0.0, _slots())
        assert d.state == SchedulerState.SCHEDULED
        assert d.target_soc >= 20.0
        # floor 20 % + 3.5 kWh of dear hours = 20 + 25.9 %
        assert d.target_soc == pytest.approx(20 + 3.5 / 13.5 * 100)
        assert d.deficit_kwh == pytest.approx(0.2 * 13.5 + 3.5)

    def test_before_the_fix_the_sum_saw_nothing(self):
        d = _eval(0.0, None, floor=0.0)
        assert d.state == SchedulerState.NOT_NEEDED
        assert "Solar forecast covers" in d.reason

    def test_a_full_battery_needs_no_charge(self):
        assert _eval(100.0, _slots()).state == SchedulerState.NOT_NEEDED

    def test_a_one_price_day_buys_nothing(self):
        flat = bridge_slots(_day_start(), CONS, SOLAR, lambda t: CHEAP)
        d = _eval(0.0, flat, peak=CHEAP)
        assert d.state == SchedulerState.NOT_NEEDED

    def test_a_thin_spread_is_not_profitable(self):
        # 0.10 / 0.92 = 0.109 > 0.105: storing costs more than the hour saves
        slots = bridge_slots(_day_start(), CONS, SOLAR,
                             lambda t: 0.105 if 4 <= t.hour < 20 else CHEAP)
        assert _eval(0.0, slots, peak=0.105).state == SchedulerState.NOT_NEEDED

    def test_an_unknown_price_is_never_bought(self):
        slots = bridge_slots(_day_start(), CONS, SOLAR, lambda t: None)
        assert _eval(0.0, slots).state == SchedulerState.NOT_NEEDED

    def test_no_sun_profile_no_bridge(self):
        assert bridge_slots(_day_start(), CONS, [], _price) == []

    def test_a_charging_battery_does_not_raise_its_own_target(self):
        """The anchor (#485 F1) still holds: SOC after charging started."""
        s = _sched()
        t = datetime(2026, 11, 17, 21, 30, tzinfo=dt_util.get_default_time_zone())
        with patch.object(dt_util, "now", return_value=t):
            first = s.evaluate(0.0, 20.0, 11.0, CHEAP, DEAR, floor_soc=20.0,
                               bridge_slots=_slots())
        with patch.object(dt_util, "now", return_value=t + timedelta(hours=2)):
            later = s.evaluate(30.0, 20.0, 11.0, CHEAP, DEAR, floor_soc=20.0,
                               bridge_slots=_slots())
        assert later.target_soc == pytest.approx(first.target_soc)

    def test_a_small_day_deficit_still_ends_at_the_floor(self):
        d = _eval(0.0, None, forecast=10.0, consumption=14.0, floor=20.0)
        assert d.state == SchedulerState.SCHEDULED
        assert d.target_soc >= 20.0
        assert d.deficit_kwh >= 0.2 * 13.5 - 1e-9

    def test_no_floor_no_bridge_is_the_old_sum(self):
        d = _eval(50.0, None, forecast=10.0, consumption=14.0, floor=0.0)
        old = _sched().evaluate(
            50.0, 10.0, 14.0, CHEAP, DEAR)
        assert d.target_soc == pytest.approx(old.target_soc)


def _coord(now, forecast_today=6.0, forecast_tomorrow=30.0):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord._battery_charge_scheduler = MagicMock()
    coord._battery_charge_scheduler.should_trigger_evaluation.return_value = True
    fc = MagicMock(available=True, forecast_today_kwh=forecast_today,
                   forecast_tomorrow_kwh=forecast_tomorrow,
                   last_update=now - timedelta(hours=1))
    coord._forecast_reader = MagicMock()
    coord._forecast_reader.read_forecast.return_value = fc
    coord._forecast_tracker = MagicMock(correction_factor=1.0)
    coord._predictor = _Predictor()
    prov = MagicMock()
    prov.get_charge_window_rate.return_value = CHEAP
    prov.get_next_daytime_rate.return_value = DEAR
    prov.get_price_at.side_effect = _price
    prov.price_series_fingerprint.return_value = 1
    coord._tariff_provider = prov
    coord._ev_devices = {}
    coord.config = {"battery_reserve_soc": 20}
    return coord, coord._battery_charge_scheduler


async def _run(coord, now):
    with patch(COORD_DT) as m, patch.object(coord, "_shadow_energy_plan"):
        m.now.return_value = now
        await coord._maybe_run_scheduler_evaluation(MagicMock(battery_soc=0.0))


@pytest.mark.unit
class TestBothSidesAreThePlanDay:
    async def test_evening_consumption_is_tomorrows_whole_day(self):
        now = datetime(2026, 11, 17, 21, 30, tzinfo=dt_util.get_default_time_zone())
        coord, sched = _coord(now)
        await _run(coord, now)
        kw = sched.evaluate.call_args.kwargs
        assert kw["forecast_tomorrow_kwh"] == pytest.approx(30.0)
        # not the 3 h of today that remain
        assert kw["expected_consumption_kwh"] == pytest.approx(sum(CONS) / 1000)
        assert kw["expected_consumption_kwh"] > _Predictor().predict_consumption_today_kwh(now)
        assert kw["floor_soc"] == pytest.approx(20.0)
        assert sum(k for p, k in kw["bridge_slots"] if p == DEAR) == pytest.approx(3.5)

    async def test_morning_consumption_stays_remaining_today(self):
        now = datetime(2026, 11, 18, 2, 0, tzinfo=dt_util.get_default_time_zone())
        coord, sched = _coord(now)
        await _run(coord, now)
        kw = sched.evaluate.call_args.kwargs
        assert kw["forecast_tomorrow_kwh"] == pytest.approx(6.0)
        assert kw["expected_consumption_kwh"] == pytest.approx(
            _Predictor().predict_consumption_today_kwh(now))

    async def test_the_reporters_night_end_to_end(self):
        now = datetime(2026, 11, 17, 21, 30, tzinfo=dt_util.get_default_time_zone())
        coord, sched = _coord(now)
        await _run(coord, now)
        kw = sched.evaluate.call_args.kwargs
        real = _sched()
        with patch.object(dt_util, "now", return_value=now):
            d = real.evaluate(current_soc=0.0, off_peak_rate=CHEAP,
                              peak_rate=DEAR, **{k: kw[k] for k in (
                                  "forecast_tomorrow_kwh",
                                  "expected_consumption_kwh", "floor_soc",
                                  "bridge_slots")})
        assert d.state == SchedulerState.SCHEDULED
        assert d.target_soc >= 20.0


def test_the_hour_the_sun_rises_counts_only_the_gap():
    """(#1377 review) load 1000 W, sun 900 W: the battery carries 0.1 kWh,
    not 1.0 — buying the whole hour would charge more than needed."""
    from datetime import datetime, timezone
    from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import bridge_slots
    start = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)
    slots = bridge_slots(start, [1000.0, 1000.0, 1000.0, 1000.0], [0.0, 0.0, 900.0, 1500.0], lambda t: 0.30)
    assert [round(k, 2) for _, k in slots] == [1.0, 1.0, 0.1]
