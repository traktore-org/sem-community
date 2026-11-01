"""#1293 — an own meter's first step after a short restart booked too few kWh.

A device on its own tariff with its own meter has its step spread over the
time since the meter last moved (#1230), with the flows SEM watched over
that time. Those flows, and the time SEM saw, were kept for one run only. A
short restart (under two minutes, booked by its first cycle) lost the read
the step is spread from: a tick on the first read after it was shared
against one cycle's import, as before #1230. Up to one tick per restart, and
the house cost took it at the house price.

The same: a device that was off its own meter for a while, then a restart.
SEM no longer knew it watched that time, so the step over it was booked
again from the house rows (#1228), on top of the draw booked meanwhile.

Now the watched time and flows are kept in the store (``meter_watch``), with
a token of their own. A restart keeps them; only the wait for counters
(#1228) starts again with each run.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import storage
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    METER_FLOW_KEYS, EnergyCalculator,
)
from custom_components.solar_energy_management.tests.test_1228_own_meter_outage import (
    HOUSE, METER, PUMP,
)
from custom_components.solar_energy_management.tests.test_1230_coarse_meter_steps import (
    Meter,
)


def _restart_on_a_tick(*, down=30, **kw):
    """Live until just before a tick, a short restart over it, then live:
    the first read after the restart shows the tick."""
    house = Meter(**kw)
    house.cycle()
    house.run(1790)
    before = house.pump_kwh()
    house.restart()
    house.down(down, import_kwh=2.3 * house.grid(house.now) * down / 3600,
               pump_kwh=2.0 * down / 3600)
    house.cycle()
    return house, before


@pytest.mark.unit
class TestTheReportedRestart:
    def test_the_tick_on_the_first_read_is_booked_whole(self):
        # 0.019 before: the tick was shared against the 30 s cycle's import
        house, before = _restart_on_a_tick(tick=0.1)
        assert house.pump_kwh() - before == pytest.approx(0.1, abs=1e-6)

    def test_the_hour_books_what_the_pump_used(self):
        # 1.92 before: one tick lost to the restart
        house, _ = _restart_on_a_tick(tick=0.1)
        house.run(1790)
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.002)

    def test_a_meter_shown_every_five_minutes(self):
        # the restart lands inside HA's five-minute wait: the first read
        # shows over five minutes of use at once (0.02 of 0.18 kWh before)
        house = Meter(tick=0.001, every=300, counters=False)
        house.cycle()
        house.run(1790)
        house.restart()
        house.down(30, import_kwh=0.0, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        house.run(1790)
        # every kWh the meter has shown, all from the grid (1.69 before)
        assert house.pump_kwh() == pytest.approx(
            house.shown[METER] - 500.0, abs=1e-6)
        assert house.pump_kwh() > 1.8

    def test_the_house_cost_holds_each_kwh_once(self):
        house, _ = _restart_on_a_tick(tick=0.1)
        house.run(1790)
        pump, grid = house.pump_kwh(), house.grid_kwh()
        assert house.pump_cost() == pytest.approx(pump * PUMP)
        assert house.import_cost() == pytest.approx(
            (grid - pump) * HOUSE + pump * PUMP, abs=1e-9)

    def test_the_share_is_over_the_steps_time(self):
        # the sun carries half the house all night: half the tick is grid
        house, before = _restart_on_a_tick(tick=0.1, grid=lambda now: 0.5)
        assert house.pump_kwh() - before == pytest.approx(0.05, abs=1e-6)

    def test_its_own_price_over_the_steps_cycles(self):
        # the pump's rate is 0.10 until the restart, 0.20 after: the tick
        # was its 0.10 time but for the 30 s cycle
        house = Meter(tick=0.1, own=lambda now: 0.10)
        house.cycle()
        house.run(1790)
        before_kwh, before_cost = house.pump_kwh(), house.pump_cost()
        house.restart()
        house.own = lambda now: 0.20
        house.down(30, import_kwh=2.3 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        kwh = house.pump_kwh() - before_kwh
        cost = house.pump_cost() - before_cost
        assert kwh == pytest.approx(0.1, abs=1e-6)
        # the tick moved at 1620 s; its 200 s: 170 at 0.10, 30 at 0.20
        assert cost / kwh == pytest.approx((170 * 0.10 + 30 * 0.20) / 200, abs=0.002)


@pytest.mark.unit
class TestTimeSemDidNotSee:
    def test_a_long_restart_is_still_booked_from_the_rows(self):
        # ten minutes down, the pack carrying half: SEM did not see that
        # time, so its part is the #1228 one (the rows' half), never spread
        # on the flows SEM kept from before
        house = Meter(tick=0.01, discharge=True)
        house.cycle()
        house.run(600)
        house.restart()
        down = 2.0 * 600 / 3600
        house.down(600, import_kwh=2.3 * 600 / 3600 / 2,
                   out_kwh=2.3 * 600 / 3600 / 2, pump_kwh=down)
        house.cycle()
        house.run(600)
        live = 2.0 * 1210 / 3600
        assert house.pump_kwh() == pytest.approx(live + down / 2, abs=0.015)
        assert house.calc.device_meter_gaps == {}

    def test_the_wait_for_counters_still_starts_with_each_run(self):
        house = Meter(tick=0.01)
        house.cycle()
        house.run(60)
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.dark = {"sensor.grid_import_total"}
        house.run(10)
        gap = house.calc.device_meter_gaps["heat_pump"]
        assert gap["wait"]["run"] == house.calc._run_token
        house.restart()
        assert gap["wait"]["run"] != house.calc._run_token


@pytest.mark.unit
class TestOffItsMeterOverARestart:
    def test_its_kwh_are_not_counted_twice(self, caplog):
        # off its meter it is booked by its draw; a restart; the step after
        # spans that half hour too (3.0 kWh if the rows book it again)
        house = Meter(tick=0.1)
        house.cycle(house_w=4000.0)
        house.run(900, house_w=4000.0)
        pump = house.pumps[0]
        pump.tariff_meter = ""
        pump.get_current_consumption.return_value = 2000.0
        house.run(1800, house_w=4000.0)
        house.restart()
        pump.tariff_meter = METER
        pump.get_current_consumption.return_value = 0.0
        house.down(30, import_kwh=4.0 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        with caplog.at_level(logging.INFO):
            house.cycle(house_w=4000.0)
            house.run(870, house_w=4000.0)
        assert "off its own meter or tariff" in caplog.text
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.02)
        assert house.calc.device_meter_gaps == {}


@pytest.mark.unit
class TestDevicesRegisteredLate:
    """SEM's first cycle after a restart comes before its devices are
    registered: no device is staged in it, and its time is the restart's
    gap. That is not time off its meter. A device registered with no
    tariff is."""

    def _late(self, *, down, late, caplog):
        # no grid import counter: only the time SEM saw says the house rows
        # cover the step's time
        house = Meter(tick=0.1, counters=False)
        house.cycle()
        house.run(1790)
        house.restart()
        pumps, house.pumps = house.pumps, []
        house.down(down, import_kwh=2.3 * down / 3600, pump_kwh=2.0 * down / 3600)
        with caplog.at_level(logging.INFO):
            house.cycle()
            house.run(late)
            house.pumps = pumps
            house.run(1800)
        return house

    def test_the_step_after_is_booked(self, caplog):
        # 100 s down booked by the first cycle, the pump found 40 s later:
        # 140 s with no pump staged (the step was dropped as time off its
        # meter if that counted)
        house = self._late(down=100, late=40, caplog=caplog)
        assert "off its own meter" not in caplog.text
        assert "not priced" not in caplog.text
        assert house.pump_kwh() == pytest.approx(
            house.shown[METER] - 500.0, abs=0.01)

    def test_its_first_staged_cycle_is_its_own_time(self, caplog):
        # 30 s with no pump staged, then 130 s staged by its draw (off its
        # meter): those 130 s are its own time off, more than two minutes
        house = Meter(tick=0.1, counters=False)
        house.cycle()
        house.run(1790)
        house.restart()
        pumps, house.pumps = house.pumps, []
        house.down(30, import_kwh=2.3 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        house.pumps = pumps
        pump = pumps[0]
        pump.tariff_meter = ""
        pump.get_current_consumption.return_value = 2000.0
        house.run(130)
        pump.tariff_meter = METER
        pump.get_current_consumption.return_value = 0.0
        with caplog.at_level(logging.INFO):
            house.run(300)
        assert "off its own meter or tariff" in caplog.text
        assert house.calc.device_meter_gaps == {}

    def test_off_its_tariff_over_a_restart_stays_the_houses(self):
        # registered with no tariff for half an hour after a restart: that
        # half hour is the house's at the house rate (2.0 kWh at the pump's
        # price if it counted as time SEM did not have the pump)
        house = Meter(tick=0.1, counters=False)
        house.cycle()
        house.run(900)
        pump = house.pumps[0]
        pump.tariff_rate = 0.0
        house.restart()
        house.down(30, import_kwh=2.3 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        house.run(1770)
        pump.tariff_rate = PUMP
        house.run(900)
        assert house.pump_kwh() == pytest.approx(1.0, abs=0.002)
        assert house.pump_cost() == pytest.approx(house.pump_kwh() * PUMP)

    def test_a_run_that_never_had_the_device_is_not_time_off(self, caplog):
        # a restart, 100 s with no device registered, a second restart: SEM
        # never booked anything for the pump in that run
        house = Meter(tick=0.1, counters=False)
        house.cycle()
        house.run(1790)
        house.restart()
        pumps, house.pumps = house.pumps, []
        house.down(20, import_kwh=2.3 * 20 / 3600, pump_kwh=2.0 * 20 / 3600)
        house.cycle()
        house.run(100)
        house.restart()
        house.down(20, import_kwh=2.3 * 20 / 3600, pump_kwh=2.0 * 20 / 3600)
        house.cycle()
        house.pumps = pumps
        with caplog.at_level(logging.INFO):
            house.run(1800)
        assert "not priced" not in caplog.text
        assert house.pump_kwh() == pytest.approx(
            house.shown[METER] - 500.0, abs=0.01)

    def test_a_device_registered_late_then_read_counts_its_own_time(self, caplog):
        # registered late, read for a while in this run, then 200 s off its
        # meter: its late start is long past, the 200 s are its own
        house = Meter(tick=0.1, counters=False)
        house.cycle(house_w=4000.0)
        house.run(900, house_w=4000.0)
        house.restart()
        pumps, house.pumps = house.pumps, []
        house.down(100, import_kwh=4.0 * 100 / 3600, pump_kwh=2.0 * 100 / 3600)
        house.cycle(house_w=4000.0)
        house.run(40, house_w=4000.0)
        house.pumps = pumps
        house.run(600, house_w=4000.0)
        pump = pumps[0]
        pump.tariff_meter = ""
        pump.get_current_consumption.return_value = 2000.0
        house.run(200, house_w=4000.0)
        pump.tariff_meter = METER
        pump.get_current_consumption.return_value = 0.0
        with caplog.at_level(logging.INFO):
            house.run(300, house_w=4000.0)
        assert "off its own meter or tariff" in caplog.text
        assert house.calc.device_meter_gaps == {}

    def test_time_off_its_meter_in_this_run_still_counts(self, caplog):
        # found late, then off its meter for half an hour: that is its
        # own time off, booked by its draw, not booked again
        house = Meter(tick=0.1)
        house.cycle(house_w=4000.0)
        house.run(900, house_w=4000.0)
        house.restart()
        pumps, house.pumps = house.pumps, []
        house.down(30, import_kwh=4.0 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle(house_w=4000.0)
        house.run(40, house_w=4000.0)
        house.pumps = pumps
        pump = pumps[0]
        pump.tariff_meter = ""
        pump.get_current_consumption.return_value = 2000.0
        house.run(1800, house_w=4000.0)
        pump.tariff_meter = METER
        pump.get_current_consumption.return_value = 0.0
        with caplog.at_level(logging.INFO):
            house.run(900, house_w=4000.0)
        assert "off its own meter or tariff" in caplog.text
        # 0.5 h on its meter, 1 h by its draw, 0.5 h on its meter
        assert house.pump_kwh() == pytest.approx(2.0, abs=0.12)
        assert house.calc.device_meter_gaps == {}


@pytest.mark.unit
class TestTheStore:
    def test_the_key_is_stored(self):
        assert "meter_watch" in storage.CALCULATOR_STATE_KEYS

    def test_a_round_trip_keeps_the_watched_time_and_flows(self):
        house = Meter(tick=0.1)
        house.cycle()
        house.run(600)
        calc = house.calc
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(calc.get_state())
        assert fresh._watch_token == calc._watch_token
        assert fresh._seen_s == pytest.approx(calc._seen_s)
        assert fresh._meter_flow == pytest.approx(calc._meter_flow)
        assert fresh._meter_dev_flow == pytest.approx(calc._meter_dev_flow)
        assert fresh._known_s == pytest.approx(calc._known_s)
        assert fresh._known_s["heat_pump"] > 0.0
        # the run itself is new: its wait for counters starts again
        assert fresh._run_token != calc._run_token

    def test_through_the_real_store_layer(self):
        house = Meter(tick=0.1)
        house.cycle()
        house.run(60)
        store = storage.SEMStorage.__new__(storage.SEMStorage)
        store._daily_data, store._energy_data = {}, {}
        store.import_energy_calculator_state(house.calc.get_state())
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(store.export_energy_calculator_state())
        assert fresh._watch_token == house.calc._watch_token

    def test_a_store_from_before_starts_fresh(self):
        house, _ = _restart_on_a_tick(tick=0.1)
        calc = house.calc
        state = calc.get_state()
        del state["meter_watch"]
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(state)
        assert fresh._watch_token != calc._watch_token
        assert fresh._seen_s == 0.0
        assert fresh._meter_flow == dict.fromkeys(METER_FLOW_KEYS, 0.0)
        assert fresh._meter_dev_flow == {}
        assert fresh._known_s == {}

    @pytest.mark.parametrize("damage", [
        "junk",
        {"token": 1, "seen": 1.0, "flow": {}, "dev": {}},
        {"token": "t", "seen": float("nan")},
        {"token": "t", "seen": -1.0},
        {"token": "t", "seen": True},
        {"token": "t", "seen": 1.0, "flow": {"flow_t": "x"}},
        {"token": "t", "seen": 1.0, "flow": {"flow_t": float("inf")}},
        {"token": "t", "seen": 1.0, "dev": {"heat_pump": [1.0, 2.0]}},
        {"token": "t", "seen": 1.0, "dev": {"heat_pump": [1.0, 2.0, "x"]}},
        {"token": "t", "seen": 1.0, "dev": "junk"},
        {"token": "t", "seen": 1.0, "known": "junk"},
        {"token": "t", "seen": 1.0, "known": {"heat_pump": float("nan")}},
        {"token": "t", "seen": 1.0, "known": {"heat_pump": False}},
    ])
    def test_a_damaged_record_starts_fresh(self, damage):
        house = Meter(tick=0.1)
        house.cycle()
        house.run(600)
        state = house.calc.get_state()
        flow = dict(state["meter_watch"]["flow"])
        if isinstance(damage, dict) and "flow" in damage:
            flow.update(damage["flow"])
            damage = {"dev": {}, "known": {}, **damage, "flow": flow}
        elif isinstance(damage, dict):
            damage = {"flow": flow, "dev": {}, "known": {}, **damage}
        state["meter_watch"] = damage
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(state)
        assert fresh._watch_token not in ("t", house.calc._watch_token)
        assert fresh._seen_s == 0.0
        assert fresh._meter_flow == dict.fromkeys(METER_FLOW_KEYS, 0.0)
        assert fresh._meter_dev_flow == {}
        assert fresh._known_s == {}

    def test_after_a_damaged_record_the_step_is_never_spread_on_stale_rows(self):
        # the old rows are not this record's: booked as before #1293, never
        # from flows that went back to 0 (that would book nothing at all)
        house = Meter(tick=0.1)
        house.cycle()
        house.run(1790)
        before = house.pump_kwh()
        state = house.calc.get_state()
        state["meter_watch"] = "junk"
        fresh = house._new()
        fresh.restore_state(state)
        house.calc = fresh
        house.down(30, import_kwh=2.3 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        assert house.pump_kwh() - before == pytest.approx(2.3 * 30 / 3600, abs=1e-6)

    def test_rows_of_another_record_are_never_spread_on(self):
        # the same sums under another token are not the rows' sums: the
        # tick is shared against one cycle's import, as before #1293
        house = Meter(tick=0.1)
        house.cycle()
        house.run(1790)
        before = house.pump_kwh()
        house.restart()
        house.calc._watch_token = "another"
        house.down(30, import_kwh=2.3 * 30 / 3600, pump_kwh=2.0 * 30 / 3600)
        house.cycle()
        assert house.pump_kwh() - before == pytest.approx(2.3 * 30 / 3600, abs=1e-6)

    def test_rows_of_another_record_never_say_off_its_meter(self, caplog):
        house = Meter(tick=0.1, counters=False)
        house.cycle(house_w=4000.0)
        house.run(900, house_w=4000.0)
        pump = house.pumps[0]
        pump.tariff_meter = ""
        house.run(1800, house_w=4000.0)
        house.restart()
        house.calc._watch_token = "another"
        pump.tariff_meter = METER
        with caplog.at_level(logging.INFO):
            house.run(300, house_w=4000.0)
        assert "off its own meter" not in caplog.text
        assert "no grid import counter" in caplog.text

    def test_a_device_with_no_read_is_not_kept(self):
        house = Meter(tick=0.1, pumps=("heat_pump", "boiler"))
        house.cycle()
        house.run(60)
        state = house.calc.get_state()
        del state["device_meter_last"]["boiler"]
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(state)
        assert set(fresh._meter_dev_flow) == {"heat_pump"}
        assert set(fresh._known_s) == {"heat_pump"}
