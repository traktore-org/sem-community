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

The rule now: once every charger has a counter of its own and all of them
read, the counters own the row. What a box drew since its counter last moved
stays with the power integral — a cloud counter reports late, and one that
never moves must never pull a row down. So the row lies between what the
counters reported and that plus the unreported draw. The fleet row, the
calendar-day copy the home balance subtracts, and each charger's own row all
follow the same rule.
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
    EV_FLEET_OWNER,
    MIDNIGHT_EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.utils.time_manager import TimeManager

from .ast_contracts import call_sites, calls

LINKS = "sensor.wallbox_links_cumulative_added_energy"
RECHTS = "sensor.wallbox_rechts_cumulative_added_energy_2"
IMPORT = "sensor.p1_import"
OWNERS = {LINKS: "links", RECHTS: "rechts"}

START = "2026-10-04 03:00:00"
TODAY = "2026-10-04"
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


def _calc(values: dict, *, complete: bool = True, counters=(LINKS, RECHTS),
          owners=None) -> EnergyCalculator:
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
    calc.configure_ev_counters(
        hass, list(counters), True, complete=complete,
        owners=OWNERS if owners is None else owners,
    )
    return calc


def _cycle(calc: EnergyCalculator, links_w: float = 0.0, rechts_w: float = 0.0):
    """One 10 s cycle. ``_last_update`` is cleared so the configured interval
    is used — the clock jumps in these tests, and a >120 s gap would skip the
    cycle (accumulator-spike guard) and with it the code under test."""
    calc._last_update = None
    readings = PowerReadings(ev_power=links_w + rechts_w)
    readings.ev_power_per_charger = {"links": links_w, "rechts": rechts_w}
    readings.calculate_derived()
    return calc.calculate_energy(readings)


def _charge(calc, clock, values, cycles: int = 100, meter: float = METER_KWH):
    for _ in range(cycles):
        clock.tick(timedelta(seconds=10))
        values[LINKS] += meter
        _cycle(calc, READ_W)


def _rows(calc, day: str = TODAY) -> tuple:
    ev_day = calc._ev_reset_day(None)
    return (
        round(calc._daily_accumulators.get(f"{EV_CATEGORY}_{ev_day}", 0.0), 2),
        round(calc._daily_accumulators.get(
            f"{MIDNIGHT_EV_CATEGORY}_{day}", 0.0), 2),
    )


@pytest.mark.unit
class TestTheCountersOwnTheRow:
    def test_the_reporters_day_the_high_read_comes_out(self):
        """THE issue. 5.0 kWh read by the power sensor, 3.0 on the meter.
        Before #1049 both rows kept 5.0 for good; now they keep the meter,
        during the session too."""
        values = {LINKS: 3135.415, RECHTS: 1094.828}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)  # baselines + anchors at the day's first read
            _charge(calc, clock, values, cycles=50)
            assert _rows(calc) == pytest.approx((1.5, 1.5), abs=0.06)
            _charge(calc, clock, values, cycles=50)
            assert _rows(calc) == pytest.approx((3.0, 3.0), abs=0.06)
            power_kwh = 100 * READ_W * 10 / 3600 / 1000
            assert power_kwh == pytest.approx(5.0), "test is vacuous"

    def test_the_longer_periods_give_the_kwh_back_too(self):
        """#666: one call writes daily, monthly, yearly and lifetime, so one
        correction moves all four. The calendar copy is daily-only."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values)
        for acc, key in (
            (calc._monthly_accumulators, f"{EV_CATEGORY}_2026_10"),
            (calc._yearly_accumulators, f"{EV_CATEGORY}_2026"),
            (calc._lifetime_accumulators, f"lifetime_{EV_CATEGORY}"),
        ):
            assert acc[key] == pytest.approx(3.0, abs=0.06), key
        assert not any(k.startswith(MIDNIGHT_EV_CATEGORY)
                       for k in calc._monthly_accumulators)

    def test_a_counter_that_reports_late_never_dips_the_day(self):
        """A cloud counter can report a session minutes or an hour late. Until
        it does, what the box drew is still owed — the day may not fall below
        the integral, or the Charge-by target would charge it twice."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values, meter=0.0)  # the counter waits
            assert _rows(calc) == (5.0, 5.0)
            for _ in range(360):  # an hour idle, still no report
                clock.tick(timedelta(seconds=10))
                _cycle(calc)
            assert _rows(calc) == (5.0, 5.0), "the day dipped under a late counter"
            values[LINKS] = 3.0  # …the report lands
            _cycle(calc)
            assert _rows(calc) == (3.0, 3.0)

    def test_a_report_mid_session_owns_only_what_it_covers(self):
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values, cycles=50, meter=0.0)
            values[LINKS] = 1.5  # one report for the first half
            _charge(calc, clock, values, cycles=50, meter=0.0)
            # 1.5 reported + 2.5 drawn since that report
            assert _rows(calc) == pytest.approx((4.0, 4.0), abs=0.06)

    def test_a_counter_that_never_moves_never_pulls_the_day_down(self):
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values, meter=0.0)
            clock.tick(timedelta(hours=6))
            _cycle(calc)
            assert _rows(calc) == (5.0, 5.0)

    def test_upward_recovery_still_runs_at_once(self):
        """#658 is untouched: energy charged while SEM was not integrating is
        recovered on the next read."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            values[RECHTS] = 7.0
            clock.tick(timedelta(seconds=10))
            _cycle(calc)
            assert _rows(calc) == (7.0, 7.0)

    def test_a_dip_that_comes_back_is_not_booked(self):
        """Bug class 43: a dip read as a reset books the climb back as
        charging. With the finer threshold an owned row would gain every
        dip; held at the last reading, it gains nothing."""
        values = {LINKS: 3135.4, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            for _ in range(20):
                clock.tick(timedelta(seconds=10))
                values[LINKS] = 3135.2
                _cycle(calc)
                clock.tick(timedelta(seconds=10))
                values[LINKS] = 3135.4
                _cycle(calc)
            assert _rows(calc) == (0.0, 0.0)

    def test_a_real_reset_is_still_a_reset(self):
        """A daily or session counter drops to 0 and climbs again — that
        climb IS charging."""
        values = {LINKS: 10.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            values[LINKS] = 0.0
            clock.tick(timedelta(seconds=10))
            _cycle(calc)
            _charge(calc, clock, values)
            assert _rows(calc) == pytest.approx((3.0, 3.0), abs=0.06)

    def test_a_session_across_midnight_is_split_by_the_meter(self):
        """Evening charging is the common case: the part before midnight is
        corrected while it is still today, not left high on a closed day."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time("2026-10-03 23:43:00") as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values, cycles=100)  # to 23:59:40
            assert _rows(calc, "2026-10-03")[1] == pytest.approx(3.0, abs=0.06)
            _charge(calc, clock, values, cycles=100)
            assert _rows(calc, "2026-10-04")[1] == pytest.approx(3.0, abs=0.09)


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
            assert _rows(calc) == (5.0, 5.0)

    def test_a_counter_without_an_owner_leaves_the_set_partial(self):
        calc = _calc({LINKS: 0.0, RECHTS: 0.0}, owners={LINKS: "links"})
        assert calc._ev_counter_complete is False

    def test_a_counter_that_does_not_read_never_pulls_the_day_down(self):
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            values[RECHTS] = "unavailable"
            _charge(calc, clock, values)
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
            _cycle(calc)
            assert _rows(calc) == (5.0, 5.0)

    def test_a_counter_swapped_since_the_store_never_pulls_the_day_down(self):
        """Review of #1049: setup configures the counters BEFORE the first
        refresh restores the store, so the "set changed" clear never sees the
        old set. The restored anchor was taken with the OLD counter; the new
        one's delta starts at 0 and cannot account for the day."""
        old, new = "sensor.wallbox_session_energy", LINKS
        values = {old: 0.0, new: 3000.0}
        with freeze_time(START) as clock:
            before = _calc(values, counters=(old,), owners={old: "links"})
            _cycle(before)
            for _ in range(100):  # an honest power read, a live counter
                clock.tick(timedelta(seconds=10))
                values[old] += 0.05
                _cycle(before, READ_W)
            assert _rows(before) == (5.0, 5.0)
            saved = before.get_state()

            after = _calc(values, counters=(new,), owners={new: "links"})
            after.restore_state(saved)
            clock.tick(timedelta(seconds=10))
            _cycle(after)
            assert _rows(after) == (5.0, 5.0)

    def test_a_set_that_became_complete_never_pulls_todays_kwh_down(self):
        """A third box without a counter charged, then was removed: the set
        is the same and now complete, but today's integral still holds the
        removed box's kWh."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values, complete=False)
            _cycle(calc)
            for _ in range(100):
                clock.tick(timedelta(seconds=10))
                calc._last_update = None
                readings = PowerReadings(ev_power=READ_W)
                readings.ev_power_per_charger = {
                    "links": 0.0, "rechts": 0.0, "third": READ_W}
                readings.calculate_derived()
                calc.calculate_energy(readings)
            calc.configure_ev_counters(calc._hass, [LINKS, RECHTS], True,
                                       complete=True, owners=OWNERS)
            _cycle(calc)
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
            mirror = calc._daily_accumulators[f"{MIDNIGHT_EV_CATEGORY}_2026-10-05"]
            assert mirror == pytest.approx(3.0, abs=0.06)

    def test_what_is_owed_survives_a_restart(self):
        """The unreported draw is persisted: lost, a late counter's session
        would come out of the row at the first cycle after a restart."""
        from custom_components.solar_energy_management.coordinator import storage
        values = {LINKS: 0.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            _charge(calc, clock, values, meter=0.0)
            store = SimpleNamespace(_daily_data={}, _energy_data={})
            storage.SEMStorage.import_energy_calculator_state(store, calc.get_state())
            fresh = _calc(values)
            fresh.restore_state(storage.SEMStorage.export_energy_calculator_state(store))
            clock.tick(timedelta(minutes=5))
            _cycle(fresh)
            assert _rows(fresh) == (5.0, 5.0)
            assert fresh._ev_counter_pending[LINKS] == pytest.approx(5.0)

    def test_a_damaged_pending_blob_is_dropped(self):
        calc = _calc({})
        calc.restore_state({"ev_counter_pending": {
            "pending": {LINKS: "x", RECHTS: 1.5, "b": True}, "seen": "junk"}})
        assert calc._ev_counter_pending == {RECHTS: 1.5}
        assert calc._ev_counter_seen == {}


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
            day = calc._time_manager.get_current_meter_day_offset_based("00:00")
            calc._midnight_ev_since = day - timedelta(days=1)
            _cycle(calc)
            for _ in range(100):
                clock.tick(timedelta(seconds=10))
                values[LINKS] += METER_KWH
                values[IMPORT] += METER_KWH + 0.0028  # car + 1 kW house
                _cycle(calc, READ_W)
            home = calc._daily_accumulators.get(f"home_{TODAY}", 0.0)
            assert home == pytest.approx(0.28, abs=0.07)
            assert calc.daily_total_consumption(day) == pytest.approx(3.28, abs=0.07)


@pytest.mark.unit
class TestEachChargerFollowsItsOwnCounter:
    """The members must follow the same rule, or they would sum above a fleet
    row that moved down and the #771 partition check would cry double count."""

    def test_down_to_its_counter(self):
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START):
            calc = _calc(values)
            assert calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS) == 0.0
            values[LINKS] = 103.0
            assert calc.follow_charger_counter(
                "links", "2026-10-03", 5.0, LINKS) == pytest.approx(3.0)

    def test_what_its_box_drew_since_the_counter_moved_stays(self):
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START) as clock:
            calc = _calc(values)
            _cycle(calc)
            calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS)
            for _ in range(100):
                clock.tick(timedelta(seconds=10))
                _cycle(calc, READ_W)  # the counter waits
            assert calc.follow_charger_counter(
                "links", "2026-10-03", 5.0, LINKS) == 5.0

    def test_up_at_once(self):
        values = {LINKS: 100.0, RECHTS: 0.0}
        with freeze_time(START):
            calc = _calc(values)
            calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS)
            values[LINKS] = 104.0
            assert calc.follow_charger_counter(
                "links", "2026-10-03", 1.0, LINKS) == pytest.approx(4.0)

    def test_only_on_a_complete_fleet(self):
        """On a partial fleet the fleet row stays upward-only; members held
        to counters alone could then sum above it."""
        values = {LINKS: 100.0, RECHTS: 0.0}
        calc = _calc(values, complete=False)
        calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS)
        values[LINKS] = 103.0
        assert calc.follow_charger_counter("links", "2026-10-03", 5.0, LINKS) == 5.0

    def test_no_counter_of_its_own_leaves_the_row_alone(self):
        calc = _calc({LINKS: 100.0, RECHTS: 0.0})
        assert calc.follow_charger_counter("links", "2026-10-03", 5.0, None) == 5.0

    def test_a_new_counter_does_not_pull_out_the_earlier_kwh(self):
        """The anchor belongs to the counter it was set with. A swapped entity
        starts its delta at 0; kept, the old anchor would pull the row down
        to it."""
        values = {LINKS: 100.0, RECHTS: 0.0, "sensor.new": 7.0}
        calc = _calc(values)
        calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS)
        assert calc.follow_charger_counter(
            "links", "2026-10-03", 4.0, "sensor.new") == 4.0

    def test_one_box_has_one_boxs_ceiling(self):
        """Bug class 3: the fleet ceiling is N boxes' worth."""
        values = {LINKS: 0.0, RECHTS: 0.0}
        calc = _calc(values)
        calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS)
        one_box = calc._max_daily_ev_kwh() / 2
        values[LINKS] = one_box + 10.0
        assert calc.follow_charger_counter("links", "2026-10-03", 1.0, LINKS) == 1.0

    def test_the_baselines_survive_a_restart(self):
        from custom_components.solar_energy_management.coordinator import storage
        values = {LINKS: 100.0, RECHTS: 0.0}
        calc = _calc(values)
        calc.follow_charger_counter("links", "2026-10-03", 0.0, LINKS)
        store = SimpleNamespace(_daily_data={}, _energy_data={})
        storage.SEMStorage.import_energy_calculator_state(store, calc.get_state())
        fresh = _calc(values)
        fresh.restore_state(storage.SEMStorage.export_energy_calculator_state(store))
        values[LINKS] = 106.0  # charged while HA was down
        assert fresh.follow_charger_counter(
            "links", "2026-10-03", 0.0, LINKS) == pytest.approx(6.0)

    def test_a_damaged_stored_entry_is_dropped(self):
        calc = _calc({})
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
        assert SEMCoordinator._ev_counter_owners(ns) == OWNERS
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
        assert SEMCoordinator._ev_counter_owners(ns) == {}
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is False

    def test_id_less_chargers_take_registrations_ids(self):
        ns = self._ns({"ev_chargers": [
            {"ev_total_energy_sensor": LINKS}, {"ev_total_energy_sensor": RECHTS},
        ]})
        assert SEMCoordinator._own_ev_counters(ns) == {
            "ev_charger_0": LINKS, "ev_charger_1": RECHTS}

    def test_one_box_without_a_list(self):
        ns = self._ns({"ev_total_energy_sensor": LINKS})
        assert SEMCoordinator._ev_counters_cover_fleet(ns) is True
        assert SEMCoordinator._ev_counter_owners(ns) == {LINKS: EV_FLEET_OWNER}
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

    def test_every_counter_setup_hands_over_the_cover_and_the_owners(self):
        sites = call_sites("configure_ev_counters")
        assert sites, "nothing configures the EV counters"
        for _, _, kw in sites:
            assert "complete" in kw and "owners" in kw, sites

    def test_every_charger_row_is_held_to_its_counter(self):
        assert calls(SEMCoordinator._update_ev_intelligence,
                     "follow_charger_counter")
        assert calls(SEMCoordinator._update_ev_intelligence, "_own_ev_counters")

    def test_the_pending_draw_is_counted_every_cycle(self):
        assert calls(EnergyCalculator.calculate_energy, "_track_ev_pending")
