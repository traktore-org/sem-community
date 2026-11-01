"""#1228 — an own-tariff meter lost its kWh over an outage.

A device on its own tariff with its own meter books the meter's step each
cycle: the step × the grid's share of the house this cycle, at most this
cycle's import (#812). After an outage the step holds every kWh the device
used while SEM was down, and it was shared against about ten seconds of
import. Almost all of it was dropped, the baseline moved on, and the house
import cost took those kWh at the house price (the grid meter's
reconciliation books the outage's import, #628).

Now a step over more time than a cycle is held and booked against the house
rows over the same span, once they cover it: SEM watched the whole span, or
the grid import and home rows follow their counters. Its grid kWh leave the
house cost at the rate the house booked them.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import CoreState

from custom_components.solar_energy_management.coordinator import storage
from custom_components.solar_energy_management.coordinator.device_tariff import (
    DeviceTariffs,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    SOLAR_GAP_WAIT_S, EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)
from custom_components.solar_energy_management.tests.test_812_device_tariff import (
    _load,
)

_DT = ("custom_components.solar_energy_management.coordinator."
       "energy_calculator.dt_util")
IMPORT = "sensor.grid_import_total"
BATT_OUT = "sensor.battery_discharge_total"
METER = "sensor.hp_meter"
T0 = datetime(2026, 10, 12, 2, 0, 0)
DAY = T0.date()
HOUSE, PUMP = 0.30, 0.20


def _kwh(value):
    return SimpleNamespace(state=str(round(value, 6)),
                           attributes={"unit_of_measurement": "kWh"})


class House:
    """A house at night: the pump draws 2 kW of a 2.3 kW house, all from the
    grid, unless a test says otherwise. Counters run with it; a restart is
    a real store round trip."""

    def __init__(self, *, counters=True, discharge=False, pumps=("heat_pump",)):
        self.states = {}
        self.hass = MagicMock()
        self.hass.state = CoreState.running
        self.hass.states.get = lambda eid: self.states.get(eid)
        self.mapping = {"grid_import": [IMPORT]} if counters else {}
        if discharge:
            self.mapping["battery_discharge"] = [BATT_OUT]
        self.imp, self.out = 1000.0, 300.0
        self.meters = {}
        self.pumps = []
        for i, did in enumerate(pumps):
            meter = METER if i == 0 else f"{METER}_{i}"
            pump = _load(did, rate=PUMP, meter=meter)
            pump.rated_power = 3000.0
            self.pumps.append(pump)
            self.meters[meter] = 500.0
        self.calc = self._new()
        self.now = T0
        self.dark = set()
        self._show()

    def _new(self):
        calc = EnergyCalculator({"update_interval": 10}, MagicMock())
        calc._import_rate = HOUSE
        calc.configure_meter_counters(self.hass, self.mapping, True)
        calc._midnight_ev_since = date(2026, 10, 1)
        return calc

    def _show(self):
        """The counters as HA shows them; one in ``dark`` is unavailable."""
        values = {IMPORT: self.imp, BATT_OUT: self.out, **self.meters}
        for entity_id, value in values.items():
            self.states[entity_id] = (
                SimpleNamespace(state="unavailable", attributes={})
                if entity_id in self.dark else _kwh(value))

    def cycle(self, *, house_w=2300.0):
        """One real cycle at ``self.now``: stage the devices, book."""
        self._show()
        entries = DeviceTariffs(self.hass).cycle(
            self.pumps, self.calc.device_meter_last, self.now)
        # (#1293) as the coordinator: every registered device is known
        self.calc.set_device_tariff_cycle(
            entries, known=[p.device_id for p in self.pumps])
        p = PowerReadings(solar_power=0.0, grid_power=-house_w)
        p.calculate_derived()
        p.home_consumption_power = house_w
        flows = SimpleNamespace(
            grid_to_home=house_w, solar_to_home=0.0, solar_to_ev=0.0,
            grid_to_ev=0.0, grid_to_battery=0.0, battery_to_home=0.0,
            battery_to_ev=0.0, solar_to_battery=0.0, solar_to_grid=0.0,
            battery_to_grid=0.0)
        with patch(_DT) as dt:
            dt.now.return_value = self.now
            dt.utcnow.return_value = self.now
            dt.as_utc.side_effect = lambda x: x
            self.calc.calculate_energy(p, flows)

    def run(self, seconds, *, house_w=2300.0, pump_w=2000.0, step=10):
        """Live cycles: the counters move with each one."""
        for _ in range(int(seconds // step)):
            self.now += timedelta(seconds=step)
            self.imp += house_w * step / 3.6e6
            for meter in self.meters:
                self.meters[meter] += pump_w * step / 3.6e6
            self.cycle(house_w=house_w)

    def down(self, seconds, *, import_kwh, pump_kwh, out_kwh=0.0):
        """No cycle: SEM is down (or skips); the counters keep counting."""
        self.now += timedelta(seconds=seconds)
        self.imp += import_kwh
        self.out += out_kwh
        for meter in self.meters:
            self.meters[meter] += pump_kwh

    def restart(self):
        fresh = self._new()
        fresh.restore_state(self.calc.get_state())
        self.calc = fresh

    def pump_kwh(self, did="heat_pump"):
        return self.calc._daily_accumulators.get(f"device_tariff_kwh:{did}_{DAY}", 0.0)

    def pump_cost(self, did="heat_pump"):
        return self.calc._daily_cost_accumulators.get(
            f"device_tariff_cost:{did}_{DAY}", 0.0)

    def grid_kwh(self):
        return self.calc._daily_accumulators.get(f"grid_import_{DAY}", 0.0)

    def import_cost(self):
        return self.calc._daily_cost_accumulators.get(f"cost_import_{DAY}", 0.0)


def _outage(house, **down):
    """A minute watched, an hour down, back: the restart's first cycle is
    skipped (the gap is longer than the integrator's limit), the next books."""
    house.cycle()
    house.run(60)
    before = house.pump_kwh()
    house.restart()
    house.down(3600, **down)
    house.cycle()
    house.run(10)
    return before


@pytest.mark.unit
class TestTheReportedOutage:
    def test_the_pumps_hour_down_is_its_own(self):
        house = House()
        before = _outage(house, import_kwh=2.3, pump_kwh=2.0)
        # the 2 kWh used while down, and the 10 s after (0.03 before)
        assert house.pump_kwh() - before == pytest.approx(2.0 + 2.0 / 360, abs=0.002)
        assert house.calc.device_meter_gaps == {}

    def test_the_house_cost_takes_them_at_the_pumps_price(self):
        house = House()
        _outage(house, import_kwh=2.3, pump_kwh=2.0)
        pump, grid = house.pump_kwh(), house.grid_kwh()
        assert grid > 2.3
        assert house.pump_cost() == pytest.approx(pump * PUMP)
        # every kWh once: the house's at its rate, the pump's at its own
        assert house.import_cost() == pytest.approx(
            (grid - pump) * HOUSE + pump * PUMP, abs=1e-6)

    def test_a_short_restart_is_booked_live_as_before(self):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(60, import_kwh=2.3 / 60, pump_kwh=2.0 / 60)
        house.cycle()
        assert house.calc.device_meter_gaps == {}
        assert house.pump_kwh() - before == pytest.approx(2.0 / 60, abs=1e-4)


@pytest.mark.unit
class TestTheShareIsTheSpans:
    def test_a_battery_carrying_half_the_house_halves_it(self):
        house = House(discharge=True)
        before = _outage(house, import_kwh=1.15, pump_kwh=2.0, out_kwh=1.15)
        # the grid gave half of what the house used over the hour
        assert house.pump_kwh() - before == pytest.approx(1.0, abs=0.01)
        assert house.import_cost() == pytest.approx(
            (house.grid_kwh() - house.pump_kwh()) * HOUSE
            + house.pump_kwh() * PUMP, abs=1e-6)

    def test_a_battery_counter_still_loading_is_waited_for(self):
        # its row is still 0 today: the home balance reads it as no flow,
        # and the span would read as all grid
        house = House(discharge=True)
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=1.15, pump_kwh=2.0, out_kwh=1.15)
        house.cycle()
        house.dark = {BATT_OUT}
        house.run(30)
        assert "heat_pump" in house.calc.device_meter_gaps
        house.dark = set()
        house.run(10)
        assert house.calc.device_meter_gaps == {}
        # half of the hour, and the 40 s booked live (2.0 if read too early)
        assert house.pump_kwh() - before == pytest.approx(
            1.0 + 2.0 * 40 / 3600, abs=0.02)

    def test_no_import_over_the_span_books_nothing(self):
        house = House(discharge=True)
        before = _outage(house, import_kwh=0.0, pump_kwh=2.0, out_kwh=2.3)
        assert house.pump_kwh() - before == pytest.approx(0.0, abs=0.01)

    def test_two_pumps_never_take_more_than_was_imported(self):
        house = House(pumps=("heat_pump", "boiler"))
        house.cycle()
        house.run(60, pump_w=1000.0)
        house.restart()
        # each meter says 1.5 kWh, the grid gave 2.0 over the hour
        house.down(3600, import_kwh=2.0, pump_kwh=1.5)
        house.cycle()
        house.run(10, pump_w=1000.0)
        taken = house.pump_kwh() + house.pump_kwh("boiler")
        assert taken <= house.grid_kwh() + 1e-6
        assert house.import_cost() >= 0.0
        # in proportion, not by name: 1.5 and 1.5 wanted, 2.0 there
        gained = [house.pump_kwh(did) - 1000.0 * 70 / 3.6e6 for did in ("heat_pump", "boiler")]
        assert gained[0] == pytest.approx(gained[1], abs=0.01)


@pytest.mark.unit
class TestTheRowsMustCoverTheSpan:
    def test_without_a_grid_counter_the_hour_is_dropped_and_said(self, caplog):
        # the house books no import for that hour either: nothing to share,
        # and the cycle after the restart is not taken from the house
        house = House(counters=False)
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        with caplog.at_level(logging.INFO):
            house.run(10)
        assert house.pump_kwh() == pytest.approx(before)
        assert "no grid import counter" in caplog.text
        assert house.calc.device_meter_gaps == {}
        # the live cycles after it book as before
        house.run(60)
        assert house.pump_kwh() - before == pytest.approx(2.0 * 60 / 3600, abs=2e-4)

    def test_a_meter_dark_while_sem_runs_is_booked_from_the_rows(self):
        # no counters: the integrator watched every cycle of the span
        # (#1230: spread over this run's flows since the meter last moved)
        house = House(counters=False)
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.dark = {METER}
        house.run(300)
        house.dark = set()
        house.run(10)
        assert house.pump_kwh() - before == pytest.approx(2.0 * 310 / 3600, abs=0.002)
        assert house.import_cost() == pytest.approx(
            (house.grid_kwh() - house.pump_kwh()) * HOUSE
            + house.pump_kwh() * PUMP, abs=1e-6)

    def test_it_waits_for_the_counters_then_books(self):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        # the grid counter is still loading for two minutes
        house.dark = {IMPORT}
        house.run(120)
        house.dark = set()
        assert "heat_pump" in house.calc.device_meter_gaps
        # meanwhile the live cycles book as before
        assert house.pump_kwh() - before == pytest.approx(2.0 * 110 / 3600, abs=0.002)
        house.run(10)
        assert house.calc.device_meter_gaps == {}
        assert house.pump_kwh() - before == pytest.approx(2.0 + 2.0 * 130 / 3600, abs=0.01)
        assert house.import_cost() == pytest.approx(
            (house.grid_kwh() - house.pump_kwh()) * HOUSE
            + house.pump_kwh() * PUMP, abs=1e-6)

    def test_the_wait_ends(self, caplog):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.dark = {IMPORT}
        house.run(SOLAR_GAP_WAIT_S - 120, pump_w=0.0, step=60)
        assert "heat_pump" in house.calc.device_meter_gaps
        with caplog.at_level(logging.INFO):
            house.run(240, pump_w=0.0, step=60)
        assert house.calc.device_meter_gaps == {}
        assert "were not all read in time" in caplog.text
        assert house.pump_kwh() - before < 0.1

    def test_while_ha_starts_the_wait_has_no_clock(self):
        house = House()
        house.cycle()
        house.run(60)
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.hass.state = CoreState.starting
        house.dark = {IMPORT}
        house.run(SOLAR_GAP_WAIT_S + 300, pump_w=0.0, step=60)
        assert "heat_pump" in house.calc.device_meter_gaps
        assert "wait" not in house.calc.device_meter_gaps["heat_pump"]

    def test_a_new_day_drops_it(self, caplog):
        house = House()
        house.now = datetime(2026, 10, 12, 23, 30, 0)
        house.cycle()
        house.run(60)
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        with caplog.at_level(logging.INFO):
            house.run(10)
        assert house.calc.device_meter_gaps == {}
        assert "a new day began" in caplog.text
        assert house.calc._daily_accumulators.get(
            f"device_tariff_kwh:heat_pump_{house.now.date()}", 0.0) < 0.1

    def test_a_store_from_before_drops_it(self, caplog):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        for baseline in house.calc.device_meter_last.values():
            baseline.pop("rows")
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        with caplog.at_level(logging.INFO):
            house.run(10)
        assert "no house rows at its start" in caplog.text
        assert house.pump_kwh() - before < 0.1


@pytest.mark.unit
class TestThePrice:
    def test_an_unreadable_price_moves_no_money(self):
        house = House()
        house.cycle()
        house.run(60)
        cost_before = house.import_cost()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        for pump in house.pumps:
            pump.tariff_rate, pump.tariff_entity = 0.0, "sensor.hp_price"
        house.cycle()
        house.run(10)
        # the pump's kWh at the house's rate: the import cost is the house's
        assert house.import_cost() - cost_before == pytest.approx(
            (2.3 + 2.3 * 10 / 3600) * HOUSE, abs=0.002)
        assert house.pump_kwh() > 2.0

    def test_the_house_average_leaves_the_pumps_price_out(self):
        # most of the day's import was the pump's at 0.20: the outage's
        # import is still the house's at 0.30, not the mix
        house = House()
        house.cycle()
        house.run(1800)
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=0.0)
        house.cycle()
        house.run(10)
        pump, grid = house.pump_kwh(), house.grid_kwh()
        assert house.import_cost() == pytest.approx(
            (grid - pump) * HOUSE + pump * PUMP, abs=1e-6)


@pytest.mark.unit
class TestTheStore:
    def test_a_held_step_survives_a_restart(self):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.dark = {IMPORT}
        house.run(10)
        house.dark = set()
        held = dict(house.calc.device_meter_gaps["heat_pump"])
        house.restart()
        assert house.calc.device_meter_gaps["heat_pump"]["kwh"] == pytest.approx(held["kwh"])
        house.down(60, import_kwh=2.3 / 60, pump_kwh=2.0 / 60)
        house.cycle()
        house.run(10)
        assert house.calc.device_meter_gaps == {}
        assert house.pump_kwh() - before == pytest.approx(2.0 + 2.0 * 80 / 3600, abs=0.01)

    def test_the_key_is_stored(self):
        assert "device_meter_gaps" in storage.CALCULATOR_STATE_KEYS

    def test_damaged_entries_are_dropped(self):
        calc = EnergyCalculator({}, MagicMock())
        state = calc.get_state()
        state["device_meter_gaps"] = {
            "a": {"kwh": 1.0, "since": "2026-10-12T02:00:00"},
            "b": {"kwh": "x", "since": "2026-10-12T02:00:00"},
            "c": {"kwh": float("nan"), "since": "2026-10-12T02:00:00"},
            "d": {"kwh": 1.0},
            "e": "junk",
        }
        calc.restore_state(state)
        assert set(calc.device_meter_gaps) == {"a"}
        state["device_meter_gaps"] = "junk"
        calc.restore_state(state)
        assert calc.device_meter_gaps == {}


def _sun(house, up, rise="2026-10-12T05:40:00+00:00"):
    house.states["sun.sun"] = SimpleNamespace(
        state="above_horizon" if up else "below_horizon",
        attributes={"next_rising": rise,
                    "next_setting": "2026-10-12T16:40:00+00:00"})


@pytest.mark.unit
class TestPvWithoutASolarCounter:
    """The house has made solar, but no counter says how much while SEM
    was down: its row reads that time as no PV."""

    def _house(self):
        house = House()
        house.calc._lifetime_accumulators["lifetime_solar"] = 5000.0
        return house

    def test_a_span_the_sun_may_have_lit_is_dropped(self, caplog):
        house = self._house()
        _sun(house, up=False)
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(8 * 3600, import_kwh=1.0, pump_kwh=3.0)
        _sun(house, up=True, rise="2026-10-13T05:41:00+00:00")
        house.cycle()
        with caplog.at_level(logging.INFO):
            house.run(10)
        assert "no solar counter covers that time" in caplog.text
        assert house.pump_kwh() - before < 0.01

    def test_a_night_with_no_sunrise_inside_is_booked(self):
        house = self._house()
        _sun(house, up=False)
        before = _outage(house, import_kwh=2.3, pump_kwh=2.0)
        assert house.pump_kwh() - before == pytest.approx(2.0 + 2.0 / 360, abs=0.002)

    def test_a_night_to_the_next_night_is_dropped(self):
        house = self._house()
        _sun(house, up=False)
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        _sun(house, up=False, rise="2026-10-13T05:41:00+00:00")
        house.cycle()
        house.run(10)
        assert house.pump_kwh() - before < 0.01


@pytest.mark.unit
class TestTheWaitPerRun:
    def test_a_second_restart_starts_the_wait_again(self):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.dark = {IMPORT}
        house.run(60)
        assert "heat_pump" in house.calc.device_meter_gaps
        # down again for 40 min; back, the counter loads for 10 s
        house.restart()
        house.down(2400, import_kwh=1.5, pump_kwh=1.3)
        house.cycle()
        house.run(10)
        assert "heat_pump" in house.calc.device_meter_gaps
        house.dark = set()
        house.run(10)
        assert house.calc.device_meter_gaps == {}
        assert house.pump_kwh() - before == pytest.approx(3.3 + 2.0 * 80 / 3600, abs=0.01)


    def test_a_restart_with_no_new_step_starts_it_again_too(self):
        house = House()
        house.cycle()
        house.run(60)
        before = house.pump_kwh()
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.dark = {IMPORT}
        house.run(60)
        # down 40 min with the pump off: nothing joins the held step
        house.restart()
        house.down(2400, import_kwh=0.2, pump_kwh=0.0)
        house.cycle()
        house.run(10, pump_w=0.0)
        assert "heat_pump" in house.calc.device_meter_gaps
        house.dark = set()
        house.run(10, pump_w=0.0)
        assert house.calc.device_meter_gaps == {}
        assert house.pump_kwh() - before == pytest.approx(2.0 + 2.0 * 70 / 3600, abs=0.02)


@pytest.mark.unit
class TestAHeldStepOfAGoneMeter:
    def test_is_dropped_not_booked(self, caplog):
        house = House()
        house.cycle()
        house.run(60)
        house.restart()
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.dark = {IMPORT}
        house.run(10)
        assert "heat_pump" in house.calc.device_meter_gaps
        kwh, cost = house.pump_kwh(), house.import_cost()
        house.pumps[0].tariff_meter = ""
        house.dark = set()
        with caplog.at_level(logging.INFO):
            house.run(10)
        assert house.calc.device_meter_gaps == {}
        assert "has no own meter now" in caplog.text
        # no meter now and no draw read: the hour stays the house's
        assert house.pump_kwh() == pytest.approx(kwh)
        assert house.import_cost() - cost == pytest.approx(
            (2.3 + 2.3 * 10 / 3600) * HOUSE, abs=0.002)


@pytest.mark.unit
class TestTheRates:
    def test_the_pumps_kwh_leave_at_the_rate_the_house_booked(self):
        # the house rate went up after the restart: the outage's import was
        # booked at the day's 0.30, so the pump's kWh leave at 0.30
        house = House()
        house.cycle()
        house.run(900)
        house.restart()
        house.calc._import_rate = 0.50
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.run(10)
        # the house's own kWh stay at what it paid: 0.30, and the 10 s at
        # 0.50 since (taken out at 0.50, the house would pay −0.25 in all)
        own_cost = house.import_cost() - house.pump_cost()
        own_kwh = house.grid_kwh() - house.pump_kwh()
        assert 0.30 < own_cost / own_kwh < 0.32
        assert house.pump_cost() == pytest.approx(house.pump_kwh() * PUMP)

    def test_the_pumps_day_average_prices_its_hour(self):
        # its own rate changed after the restart; the hour is priced at its
        # day's average, as the house prices its own (0.40 at the read)
        house = House()
        house.cycle()
        house.run(900)
        house.restart()
        for pump in house.pumps:
            pump.tariff_rate = 0.40
        house.down(3600, import_kwh=2.3, pump_kwh=2.0)
        house.cycle()
        house.run(10)
        live = 2.0 * 910 / 3600
        assert house.pump_cost() == pytest.approx(
            live * PUMP + 2.0 * PUMP + 2.0 * 10 / 3600 * PUMP, abs=0.003)
