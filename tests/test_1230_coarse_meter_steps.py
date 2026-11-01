"""#1230 — an own-tariff meter with coarse steps booked too few kWh.

A device on its own tariff with its own meter booked the meter's step in the
cycle it showed up: the step × the grid's share of the house this cycle, at
most this cycle's import (#812). A real meter moves in whole ticks (0.01 or
0.1 kWh), or HA shows a new value only every few minutes. Then one step holds
what the device used over many cycles, and it was shared against about ten
seconds of import: a 2 kW heat pump booked 1.28 of 2.0 kWh in a night hour
on 0.01 kWh ticks, 0.13 on 0.1 kWh ticks. A meter shown every five minutes
booked nothing: its step was judged by one cycle's time and refused. The
house cost took the rest at the house price.

Now the baseline keeps the read the value last moved at. A step is judged by
the time since then, and spread over it when this run watched all of it: ×
the grid's share of the house over that time, leaving the house cost at the
rate the house booked them, at most the day's import no device took.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.device_tariff import (
    DeviceTariffs,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)
from custom_components.solar_energy_management.tests.test_812_device_tariff import (
    _hass_with, _load,
)
from custom_components.solar_energy_management.tests.test_1228_own_meter_outage import (
    _DT, HOUSE, METER, PUMP, T0, House, _kwh,
)


class Meter(House):
    """The #1228 night house, its meter shown as HA shows a real one: in
    whole ticks of ``tick`` kWh, and a new value only every ``every``
    seconds (0 = each cycle). ``grid`` is the grid's part of the house at a
    moment (the sun or the pack carry the rest); ``rate`` the house rate,
    ``own`` the pump's."""

    def __init__(self, *, tick=0.01, every=0, grid=None, rate=None, own=None,
                 **kw):
        self.tick, self.every = tick, every
        self.grid = grid or (lambda now: 1.0)
        self.rate, self.own = rate, own
        self.shown, self.shown_at = {}, None
        super().__init__(**kw)

    def _show(self):
        super()._show()
        due = (self.shown_at is None or not self.every
               or (self.now - self.shown_at).total_seconds() >= self.every)
        if due:
            self.shown_at = self.now
            self.shown = {m: math.floor(v / self.tick + 1e-9) * self.tick
                          for m, v in self.meters.items()}
        for meter, value in self.shown.items():
            if meter not in self.dark:
                self.states[meter] = _kwh(value)

    def cycle(self, *, house_w=2300.0):
        self._show()
        if self.rate is not None:
            self.calc._import_rate = self.rate(self.now)
        if self.own is not None:
            for pump in self.pumps:
                pump.tariff_rate = self.own(self.now)
        entries = DeviceTariffs(self.hass).cycle(
            self.pumps, self.calc.device_meter_last, self.now)
        self.calc.set_device_tariff_cycle(entries)
        grid_w = house_w * self.grid(self.now)
        p = PowerReadings(solar_power=house_w - grid_w, grid_power=-grid_w)
        p.calculate_derived()
        p.home_consumption_power = house_w
        flows = SimpleNamespace(
            grid_to_home=grid_w, solar_to_home=house_w - grid_w,
            solar_to_ev=0.0, grid_to_ev=0.0, grid_to_battery=0.0,
            battery_to_home=0.0, battery_to_ev=0.0, solar_to_battery=0.0,
            solar_to_grid=0.0, battery_to_grid=0.0)
        with patch(_DT) as dt:
            dt.now.return_value = self.now
            dt.utcnow.return_value = self.now
            dt.as_utc.side_effect = lambda x: x
            self.calc.calculate_energy(p, flows)

    def run(self, seconds, *, house_w=2300.0, pump_w=2000.0, step=10):
        for _ in range(int(seconds // step)):
            self.now += timedelta(seconds=step)
            self.imp += house_w * self.grid(self.now) * step / 3.6e6
            for meter in self.meters:
                self.meters[meter] += pump_w * step / 3.6e6
            self.cycle(house_w=house_w)

    def own_cost_per_kwh(self):
        return ((self.import_cost() - self.pump_cost())
                / (self.grid_kwh() - self.pump_kwh()))


def _hour(**kw):
    house = Meter(**kw)
    house.cycle()
    house.run(3600)
    return house


@pytest.mark.unit
class TestTheReportedHour:
    def test_ticks_of_a_hundredth_book_the_whole_hour(self):
        # 1.28 kWh before: each tick was shared against one cycle's import
        assert _hour(tick=0.01).pump_kwh() == pytest.approx(2.0, abs=0.002)

    def test_ticks_of_a_tenth_book_the_whole_hour(self):
        # 0.13 kWh before; the meter shows 502.0 at the hour's end
        assert _hour(tick=0.1).pump_kwh() == pytest.approx(2.0, abs=0.002)

    def test_a_meter_shown_every_five_minutes_books_it(self):
        # nothing before: 0.17 kWh in "10 s" was not possible for a 3 kW pump
        assert _hour(tick=0.001, every=300).pump_kwh() == pytest.approx(2.0, abs=0.002)

    def test_the_house_cost_holds_each_kwh_once(self):
        house = _hour(tick=0.1)
        pump, grid = house.pump_kwh(), house.grid_kwh()
        assert house.pump_cost() == pytest.approx(pump * PUMP)
        assert house.import_cost() == pytest.approx(
            (grid - pump) * HOUSE + pump * PUMP, abs=1e-9)


@pytest.mark.unit
class TestTheShareIsTheStepsTime:
    def test_not_the_share_at_the_read(self):
        # the sun carries the house in each cycle the meter shows a value in,
        # the grid all the others: a share read at the step would be 0
        def grid(now):
            return 0.0 if (now - T0).total_seconds() % 300 == 0 else 1.0
        house = _hour(tick=0.001, every=300, grid=grid, counters=False)
        assert house.pump_kwh() == pytest.approx(2.0 * 29 / 30, abs=0.005)

    def test_a_battery_carrying_half_halves_it(self):
        house = _hour(tick=0.1, grid=lambda now: 0.5, counters=False)
        assert house.pump_kwh() == pytest.approx(1.0, abs=0.002)

    def test_the_sun_carrying_it_all_books_none(self):
        house = _hour(tick=0.1, grid=lambda now: 0.0, counters=False)
        assert house.pump_kwh() == 0.0

    def test_a_half_hour_of_sun_then_grid(self):
        def grid(now):
            return 0.0 if now < T0 + timedelta(minutes=30) else 1.0
        house = _hour(tick=0.01, grid=grid, counters=False)
        # the cycle that ends at 30:00 is the first the grid carries
        assert house.pump_kwh() == pytest.approx(2.0 * 1810 / 3600, abs=0.002)


@pytest.mark.unit
class TestThePrice:
    def test_the_kwh_leave_at_the_rate_the_house_booked_them(self):
        # 0.30 for 20 min, then 0.50; the meter shows a value each half hour,
        # so the first step spans both rates. At the rate of the read the
        # house would keep −0.001 for its 0.3 kWh; booked when, it keeps
        # 0.1 kWh at 0.30 and 0.2 kWh at 0.50 (and the first 10 s cycle)
        def rate(now):
            return 0.30 if now <= T0 + timedelta(minutes=20) else 0.50
        house = _hour(tick=0.001, every=1800, rate=rate, counters=False)
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)
        own = house.import_cost() - house.pump_cost()
        first = 2.3 * 10 / 3600 * 0.30
        assert own == pytest.approx(0.1 * 0.30 + 0.2 * 0.50 + first, abs=0.001)
        assert house.pump_cost() == pytest.approx(house.pump_kwh() * PUMP)

    def test_the_pumps_own_price_is_its_price_over_the_step(self):
        # its rate is 0.10 for 20 min, then 0.40; at the price of the read
        # the first half hour would cost 0.40 too (0.80 in all)
        def own(now):
            return 0.10 if now <= T0 + timedelta(minutes=20) else 0.40
        house = _hour(tick=0.001, every=1800, own=own, counters=False)
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)
        assert house.pump_cost() == pytest.approx(
            2 / 3 * 0.10 + 1 / 3 * 0.40 + 1.0 * 0.40, abs=0.001)
        assert house.import_cost() - house.pump_cost() == pytest.approx(
            (house.grid_kwh() - house.pump_kwh()) * HOUSE, abs=1e-9)

    def test_an_unreadable_price_moves_no_money(self):
        house = Meter(tick=0.1)
        for pump in house.pumps:
            pump.tariff_rate, pump.tariff_entity = 0.0, "sensor.hp_price"
        house.cycle()
        house.run(3600)
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)
        assert house.import_cost() == pytest.approx(house.grid_kwh() * HOUSE, abs=1e-9)


@pytest.mark.unit
class TestNeverMoreThanWasImported:
    def test_two_meters_share_what_the_house_bought(self):
        # each meter says 1.5 kWh, the grid gave 2.0 kWh: in proportion
        house = Meter(tick=0.1, pumps=("heat_pump", "boiler"), counters=False)
        house.cycle()
        house.run(3600, house_w=2000.0, pump_w=1500.0)
        a, b = house.pump_kwh(), house.pump_kwh("boiler")
        assert a + b <= house.grid_kwh() + 1e-9
        assert a + b == pytest.approx(2.0, abs=0.01)
        assert a == pytest.approx(b, abs=0.002)
        assert house.import_cost() >= 0.0


@pytest.mark.unit
class TestTimeSemDidNotSee:
    def test_a_skipped_cycle_while_the_pump_stands_loses_nothing(self):
        # the read it last moved at is no start once a cycle was skipped:
        # the next read the value still stands at starts it again
        house = Meter(tick=0.1, counters=False)
        house.cycle()
        house.run(600, pump_w=0.0)
        house.down(130, import_kwh=0.0, pump_kwh=0.0)
        house.cycle()
        house.run(3600)
        # one tick shared against one cycle's import would leave 1.91
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)

    def test_a_whole_kwh_tick_after_a_skipped_cycle_is_not_refused(self):
        # the spread starts again after the skip, but the tick is judged by
        # the 30 min since the value moved: 1 kWh in the 2:40 since the
        # skip is more than a 3 kW pump can draw
        house = Meter(tick=1.0, counters=False)
        house.cycle()
        house.run(1500)
        house.down(130, import_kwh=0.0, pump_kwh=2.0 * 130 / 3600)
        house.cycle()
        house.run(2000)
        assert house.calc.device_meter_last["heat_pump"]["moved"] == (
            T0 + timedelta(seconds=3600)).isoformat()
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)

    def test_a_step_over_a_skipped_cycle_is_shared_over_its_rows(self):
        # the pack carries half the house while the cycles are skipped: the
        # step over that time is the #1228 one, not spread on what SEM saw
        house = Meter(tick=0.01, discharge=True)
        house.cycle()
        house.run(600)
        down = 2.0 * 600 / 3600
        house.down(600, import_kwh=2.3 * 600 / 3600 / 2,
                   out_kwh=2.3 * 600 / 3600 / 2, pump_kwh=down)
        house.cycle()
        house.run(600)
        live = 2.0 * 1210 / 3600
        assert house.pump_kwh() == pytest.approx(live + down / 2, abs=0.015)
        assert house.calc.device_meter_gaps == {}

    def test_a_restart_starts_the_read_again(self):
        house = Meter(tick=0.1)
        house.cycle()
        house.run(1800)
        before = house.pump_kwh()
        house.restart()
        house.down(30, import_kwh=2.3 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        house.run(1800)
        read = house.calc.device_meter_last["heat_pump"]
        assert read["since_rows"]["run"] == house.calc._run_token
        assert house.pump_kwh() - before == pytest.approx(1.0, abs=0.002)
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)


@pytest.mark.unit
class TestTheBaseline:
    def test_a_standing_value_keeps_the_read_it_moved_at(self):
        house = Meter(tick=0.1, counters=False)
        house.cycle()
        house.run(30, pump_w=0.0)
        read = dict(house.calc.device_meter_last["heat_pump"])
        house.run(60, pump_w=0.0)
        now = house.calc.device_meter_last["heat_pump"]
        assert now["since"] == read["since"] == T0.isoformat()
        assert now["moved"] == read["moved"] == T0.isoformat()
        assert now["since_rows"] == read["since_rows"]
        assert now["at"] == (T0 + timedelta(seconds=90)).isoformat()

    def test_a_step_is_judged_by_the_time_since_it_moved(self):
        pump = _load("heat_pump", rate=0.20, meter=METER)
        pump.rated_power = 3000.0
        at = datetime(2026, 10, 12, 2, 5, 0)
        read = {"entity": METER, "date": "2026-10-12", "value": 100.0,
                "at": (at - timedelta(seconds=10)).isoformat(),
                "moved": (at - timedelta(minutes=5)).isoformat()}

        def step(value, stored):
            return DeviceTariffs(_hass_with({METER: _kwh(value)})).meter_step(
                pump, {"heat_pump": stored}, at)[0]
        # 0.17 kWh in 5 min fits 3 kW; in 10 s it would not
        assert step(100.17, read) == pytest.approx(0.17)
        assert step(101.0, read) is None
        old = {k: v for k, v in read.items() if k != "moved"}
        assert step(100.17, old) is None

    def test_the_read_survives_a_restart(self):
        house = Meter(tick=0.1)
        house.cycle()
        house.run(600)
        read = house.calc.device_meter_last["heat_pump"]
        assert {"moved", "since", "since_rows", "since_dev"} <= set(read)
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(house.calc.get_state())
        assert fresh.device_meter_last["heat_pump"]["since"] == read["since"]
        assert fresh.device_meter_last["heat_pump"]["since_rows"] == read["since_rows"]


# ── the oracle: every meter a home may have ─────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("tick", [0.001, 0.01, 0.1, 0.5])
@pytest.mark.parametrize("every", [0, 60, 300])
@pytest.mark.parametrize("pump_w", [700.0, 2500.0])
def test_every_meter_books_what_the_pump_used(tick, every, pump_w):
    """A pump on all night: whatever the meter's tick and how often HA shows
    it, the grid kWh are what the pump used, less what the meter has not
    shown yet (at most a tick and one wait), and once more a tick the first
    read may refuse (a tick over 0.1 kWh in one cycle)."""
    house = Meter(tick=tick, every=every, counters=False)
    house.cycle(house_w=pump_w + 300.0)
    house.run(3600, house_w=pump_w + 300.0, pump_w=pump_w)
    used = pump_w / 1000.0
    unshown = tick + pump_w * every / 3.6e6 + (tick if tick > 0.1 else 0.0)
    assert used - unshown - 1e-6 <= house.pump_kwh() <= used + 1e-6
    assert house.import_cost() == pytest.approx(
        (house.grid_kwh() - house.pump_kwh()) * HOUSE
        + house.pump_kwh() * PUMP, abs=1e-9)

