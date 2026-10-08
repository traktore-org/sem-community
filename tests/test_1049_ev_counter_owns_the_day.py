"""#1049 — the EV day rows follow the wallbox counters DOWN as well as up.

@RienduPre, 2× Wallbox Pulsar behind the MQTT bridge, 4 Oct 2026: SEM's
calendar-day EV row said 19.56 kWh, the two ``cumulative_added_energy``
counters said 10.99. Home is the meters minus that row, so home read 8.49 kWh
where the to-home flows said 17.28.

The counters were configured, both live, and right. #658 made the EV rows
adopt them UPWARD ONLY, on the belief that a counter "can only ever reveal
energy the integrator missed". A charger power sensor can read high (the
bridge's open issue #110: 7.6 kW on one phase at 16 A), and upward-only kept
every kWh of it. The grid and battery rows have followed their meters both
ways since #628.

The rule now: once every charger has a counter of its own, all of them read,
and the box has been idle ``EV_COUNTER_SETTLE_SECONDS``, the counters own the
row both ways. While a car charges — when a cloud counter can trail the power
by minutes — adoption stays upward-only, so the day never freezes under the
Charge-by target. The fleet row, the calendar-day copy the home balance
subtracts, and each charger's own row all follow the same rule.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EV_CATEGORY,
    EV_COUNTER_SETTLE_SECONDS,
    MIDNIGHT_EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.utils.time_manager import TimeManager

from .ast_contracts import call_sites, calls

LINKS = "sensor.wallbox_links_cumulative_added_energy"
RECHTS = "sensor.wallbox_rechts_cumulative_added_energy_2"
IMPORT = "sensor.p1_import"

START = "2026-10-04 03:00:00"
TODAY = "2026-10-04"
SETTLE = timedelta(seconds=EV_COUNTER_SETTLE_SECONDS)
# 18 kW read by the power sensor, 10.8 kW on the meter: 0.05 vs 0.03 kWh per
# 10 s cycle. 100 cycles book 5.0 kWh against a counter's 3.0.
READ_W = 18_000.0
METER_KWH = 0.03


def _hass(values: dict) -> Mock:
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"

    def _get(entity_id):
        if entity_id not in values:
            return None
        state = Mock()
        state.state = str(values[entity_id])
        state.attributes = {"unit_of_measurement": "kWh"}
        return state

    hass.states.get = _get
    return hass


def _calc(values: dict, *, complete: bool = True,
          counters=(LINKS, RECHTS)) -> EnergyCalculator:
    hass = _hass(values)
    calc = EnergyCalculator(
        {
            "update_interval": 10,
            "ev_target_time": "11:00",
            "ev_chargers": [{"id": "links"}, {"id": "rechts"}],
            "ev_max_current": 32, "ev_phases": 3, "ev_voltage": 230,
        },
        TimeManager(hass),
    )
    calc.configure_ev_counters(hass, list(counters), True, complete=complete)
    return calc


def _cycle(calc: EnergyCalculator, watts: float = 0.0):
    """One 10 s cycle. ``_last_update`` is cleared so the configured interval
    is used — the clock jumps in these tests, and a >120 s gap would skip the
    cycle (accumulator-spike guard) and with it the code under test."""
    calc._last_update = None
    readings = PowerReadings(ev_power=watts)
    readings.calculate_derived()
    return calc.calculate_energy(readings)


def _charge(calc, clock, values, cycles: int = 100, meter: float = METER_KWH):
    for _ in range(cycles):
        clock.tick(timedelta(seconds=10))
        values[LINKS] += meter
        _cycle(calc, READ_W)


def _rows(calc) -> tuple:
    ev_day = calc._ev_reset_day(None)
    return (
        round(calc._daily_accumulators.get(f"{EV_CATEGORY}_{ev_day}", 0.0), 2),
        round(calc._daily_accumulators.get(
            f"{MIDNIGHT_EV_CATEGORY}_{TODAY}", 0.0), 2),
    )


def _settle(calc, clock, gap: timedelta = SETTLE + timedelta(minutes=1)):
    """Stop charging and wait ``gap``: one idle cycle starts the clock, one
    after the wait reads it."""
    clock.tick(timedelta(seconds=10))
    _cycle(calc)
    clock.tick(gap)
    return _cycle(calc)


@pytest.mark.unit
class TestTheCountersOwnASettledDay:
    def test_the_reporters_day_the_high_read_comes_out(self):
        """THE issue. 5.0 kWh integrated, 3.0 on the meter. Before #1049 the
        row kept 5.0 for good."""
        values = {LINKS: 3135.415, RECHTS: 1094.828}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)  # baselines + anchors at the day's first read
            _charge(calc, clock, values)
            assert _rows(calc) == (5.0, 5.0), "test is vacuous: no high read"

            _settle(calc, clock)
            assert _rows(calc) == (3.0, 3.0)

    def test_the_longer_periods_give_the_kwh_back_too(self):
        """#666: one call writes daily, monthly, yearly and lifetime, so one
        correction moves all four. The calendar copy is daily-only."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
            _settle(calc, clock)
        assert calc._monthly_accumulators[f"{EV_CATEGORY}_2026_10"] == pytest.approx(3.0)
        assert calc._yearly_accumulators[f"{EV_CATEGORY}_2026"] == pytest.approx(3.0)
        assert calc._lifetime_accumulators[f"lifetime_{EV_CATEGORY}"] == pytest.approx(3.0)
        assert not any(k.startswith(MIDNIGHT_EV_CATEGORY)
                       for k in calc._monthly_accumulators)

    def test_nothing_comes_out_before_the_box_has_settled(self):
        """A cloud counter can trail the power by minutes. Held to it while
        the car charges, the day would freeze and the Charge-by target would
        overshoot — so during the session and the settle window, the
        integrator is the floor, exactly as before."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
            _settle(calc, clock, gap=SETTLE - timedelta(minutes=1))
            assert _rows(calc) == (5.0, 5.0)

    def test_a_counter_that_lags_the_session_does_not_freeze_the_day(self):
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values, meter=0.0)  # the counter waits
            assert _rows(calc) == (5.0, 5.0), "the day froze under a lagging counter"
            values[LINKS] = 3.0  # …and reports a few minutes after the stop
            _settle(calc, clock)
            assert _rows(calc) == (3.0, 3.0)

    def test_standby_draw_is_not_charging(self):
        """Bug class 36: a box idles at ~150 W. That must not hold the settle
        clock open for ever, or the fix never runs on such a box."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
            _cycle(calc, 150.0)
            clock.tick(SETTLE + timedelta(minutes=1))
            _cycle(calc, 150.0)
            assert _rows(calc)[0] == pytest.approx(3.0, abs=0.01)

    def test_a_new_charge_restarts_the_settle_clock(self):
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
            _cycle(calc)
            clock.tick(SETTLE - timedelta(minutes=5))
            _charge(calc, clock, values, cycles=1)
            clock.tick(timedelta(minutes=10))  # 35 min since the first stop
            _cycle(calc)
            assert _rows(calc) == (5.05, 5.05)

    def test_upward_adoption_still_runs_while_charging(self):
        """#658 is untouched: energy charged while SEM was not integrating is
        still recovered at once, settled or not."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            values[RECHTS] = 7.0
            clock.tick(timedelta(seconds=10))
            _cycle(calc, READ_W)
            assert _rows(calc) == (7.0, 7.0)


@pytest.mark.unit
class TestOnlyAWholeCounterSetPullsDown:
    def test_a_partial_set_never_pulls_the_day_down(self):
        """Charger B has no counter: its kWh are in the integral and in no
        counter. #658's promise stands — a partial set only ever adds."""
        values = {LINKS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values, complete=False, counters=(LINKS,))
            _cycle(calc)
            _charge(calc, clock, values)
            _settle(calc, clock)
            assert _rows(calc) == (5.0, 5.0)

    def test_a_counter_that_does_not_read_never_pulls_the_day_down(self):
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
            values[RECHTS] = "unavailable"
            _settle(calc, clock)
            assert _rows(calc) == (5.0, 5.0)

    def test_a_counter_first_seen_after_the_anchor_never_pulls_the_day_down(self):
        """RECHTS was dark at the day's first read and charged meanwhile. Its
        base starts late, so its earlier kWh are in no counter delta: the
        target is short, and must not pull the row under them."""
        values = {LINKS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
            values[RECHTS] = 50.0
            _settle(calc, clock)
            assert _rows(calc) == (5.0, 5.0)

    def test_the_next_day_anchors_whole_again(self):
        values = {LINKS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            values[RECHTS] = 50.0
            _cycle(calc)
            clock.move_to("2026-10-05 01:00:00")  # a new calendar day
            _cycle(calc)
            _charge(calc, clock, values)
            _settle(calc, clock)
            mirror = calc._daily_accumulators[f"{MIDNIGHT_EV_CATEGORY}_2026-10-05"]
            assert mirror == pytest.approx(3.0)


@pytest.mark.unit
class TestTheHomeRowGetsItsKwhBack:
    def test_home_is_the_meter_minus_the_meter(self):
        """The reporter's own sum: home = meters − car. With the car row on
        the integral, home read 0 for the whole session; on the counter it
        reads what the house drew."""
        values = {LINKS: 0.0, RECHTS: 0.0, IMPORT: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            calc.configure_meter_counters(
                calc._hass, {"grid_import": [IMPORT]}, True)
            calc._midnight_ev_since = calc._time_manager.get_current_meter_day_offset_based(
                "00:00") - timedelta(days=1)
            _cycle(calc)
            for _ in range(100):
                clock.tick(timedelta(seconds=10))
                values[LINKS] += METER_KWH
                values[IMPORT] += METER_KWH + 0.0028  # car + 1 kW house
                _cycle(calc, READ_W)
            home = lambda: calc._daily_accumulators.get(f"home_{TODAY}", 0.0)  # noqa: E731
            assert home() == pytest.approx(0.0, abs=0.01), "vacuous: home not short"
            _settle(calc, clock)
            assert home() == pytest.approx(0.28, abs=0.01)
            assert calc.daily_total_consumption(
                calc._time_manager.get_current_meter_day_offset_based("00:00")
            ) == pytest.approx(3.28, abs=0.01)


@pytest.mark.unit
class TestEachChargerFollowsItsOwnCounter:
    """The members must follow the same rule, or they would sum above a fleet
    row that moved down and the #771 partition check would cry double count."""

    def _calc(self, values):
        return _calc(values)

    def test_down_once_this_charger_is_idle(self):
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = self._calc(values)
            row = calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS, 0.0)
            assert row == 0.0
            row = calc.follow_charger_counter("links", "2026-10-03", 5.0, LINKS, READ_W)
            values[LINKS] = 103.0
            row = calc.follow_charger_counter("links", "2026-10-03", row, LINKS, 0.0)
            assert row == 5.0, "pulled down before the box settled"
            clock.tick(SETTLE + timedelta(minutes=1))
            assert calc.follow_charger_counter(
                "links", "2026-10-03", row, LINKS, 0.0) == pytest.approx(3.0)

    def test_up_at_once(self):
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START):
            calc = self._calc(values)
            calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS, READ_W)
            values[LINKS] = 104.0
            assert calc.follow_charger_counter(
                "links", "2026-10-03", 1.0, LINKS, READ_W) == pytest.approx(4.0)

    def test_no_counter_of_its_own_leaves_the_row_alone(self):
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = self._calc(values)
            clock.tick(SETTLE * 2)
            assert calc.follow_charger_counter(
                "links", "2026-10-03", 5.0, None, 0.0) == 5.0

    def test_a_new_counter_does_not_pull_out_the_earlier_kwh(self):
        """The anchor belongs to the counter it was set with. A swapped entity
        starts its delta at 0; kept, the old anchor would pull the row down
        to it."""
        values = {LINKS: 100.0, RECHTS: 0.0, "sensor.new": 7.0}
        with freeze_time(START) as clock:
            calc = self._calc(values)
            calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS, 0.0)
            clock.tick(SETTLE * 2)
            row = calc.follow_charger_counter(
                "links", "2026-10-03", 4.0, "sensor.new", 0.0)
            assert row == 4.0

    def test_the_baselines_survive_a_restart(self):
        from custom_components.solar_energy_management.coordinator import storage
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START):
            calc = self._calc(values)
            calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS, 0.0)
            store = SimpleNamespace(_daily_data={}, _energy_data={})
            storage.SEMStorage.import_energy_calculator_state(store, calc.get_state())
            fresh = self._calc(values)
            fresh.restore_state(
                storage.SEMStorage.export_energy_calculator_state(store))
            values[LINKS] = 106.0  # charged while HA was down
            assert fresh.follow_charger_counter(
                "links", "2026-10-03", 0.0, LINKS, 0.0) == pytest.approx(6.0)

    def test_a_damaged_stored_entry_is_dropped(self):
        calc = self._calc({})
        calc.restore_state({"charger_counter_baselines": {"a": "junk", "b": {}}})
        assert calc._charger_counter_baselines == {"b": {}}


@pytest.mark.unit
class TestWhichCountersAreAChargersOwn:
    @staticmethod
    def _ns(config):
        ns = SimpleNamespace(config=config)
        ns._own_ev_counters = lambda: SEMCoordinator._own_ev_counters(ns)
        return ns

    def test_the_reporters_two_wallboxes_cover_the_fleet(self):
        ns = self._ns({"ev_chargers": [
            {"id": "links", "ev_total_energy_sensor": LINKS},
            {"id": "rechts", "ev_total_energy_sensor": RECHTS},
        ]})
        assert SEMCoordinator._own_ev_counters(ns) == {"links": LINKS, "rechts": RECHTS}
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is True

    def test_a_charger_without_a_counter_breaks_the_cover(self):
        ns = self._ns({"ev_chargers": [
            {"id": "links", "ev_total_energy_sensor": LINKS}, {"id": "rechts"},
        ]})
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is False

    def test_the_top_level_counter_is_the_primarys_only(self):
        ns = self._ns({"ev_total_energy_sensor": LINKS,
                       "ev_chargers": [{"id": "a"}, {"id": "b"}]})
        assert SEMCoordinator._own_ev_counters(ns) == {"a": LINKS, "b": None}
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is False

    def test_a_shared_counter_is_nobodys(self):
        ns = self._ns({"ev_chargers": [
            {"id": "a", "ev_total_energy_sensor": LINKS},
            {"id": "b", "ev_total_energy_sensor": LINKS},
        ]})
        assert SEMCoordinator._own_ev_counters(ns) == {"a": None, "b": None}
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is False

    def test_id_less_chargers_take_registrations_ids(self):
        ns = self._ns({"ev_chargers": [
            {"ev_total_energy_sensor": LINKS}, {"ev_total_energy_sensor": RECHTS},
        ]})
        assert SEMCoordinator._own_ev_counters(ns) == {
            "ev_charger_0": LINKS, "ev_charger_1": RECHTS}

    def test_one_box_without_a_list(self):
        assert SEMCoordinator._ev_counters_cover_fleet(
            self._ns({"ev_total_energy_sensor": LINKS})) is True
        assert SEMCoordinator._ev_counters_cover_fleet(self._ns({})) is False

    def test_the_fallback_counters_never_cover_the_fleet(self):
        """The legacy daily sensor and the Energy Dashboard row are not tied
        to one box — the latter is found by a substring of its name."""
        ns = self._ns({"ev_daily_energy_sensor": "sensor.ev_daily",
                       "ev_chargers": [{"id": "a"}]})
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is False


@pytest.mark.unit
class TestTheWiringIsThere:
    """A rule nothing calls is the #653 orphan shape. Every production call
    is checked, not one function's text (#924)."""

    def test_every_counter_setup_hands_over_the_cover(self):
        sites = call_sites("configure_ev_counters")
        assert sites, "nothing configures the EV counters"
        assert all("complete" in kw for _, _, kw in sites), sites

    def test_every_charger_row_is_held_to_its_counter(self):
        assert calls(SEMCoordinator._update_ev_intelligence,
                     "follow_charger_counter")
        assert calls(SEMCoordinator._update_ev_intelligence, "_own_ev_counters")
