"""(#1412, reporter's review) A car that stays plugged in for days.

Day 1: the idle start sets 1 phase (switch 1); night, at rest, back to 3
phases (switch 2). Day 2: down to 1 phase (switch 3); night, 3 phases
(switch 4). Day 3: ``AUTO_MAX_PER_SESSION`` is spent, so no 1-phase start,
and the car sits idle in thin sun until it is unplugged.

Three findings:

1. A switch made while the charger is AT REST does not count toward the
   per-session cap — the cap protects the contactor under load, and these
   four cost it nothing. A separate hard daily bound keeps a broken charger
   from being written all day.
2. The night return to the configured phases fired every evening, also when
   nothing is owed tonight (two writes a day on the installation). It fires
   when a grid block is planned or commanded.
3. On some wallboxes the switch is an installation setting shared by every
   charger on it — said in the guide.

The charger is a fixture: a number entity with a range. No brand.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    AUTO_MAX_PER_SESSION, AUTO_MIN_INTERVAL_S, AUTO_START_DELAY_S,
    PhaseAutoPlanner, PhaseSwitchSequencer,
)

from .test_1412_phase_review import (
    ONE_PHASE_VALUE, THIN_SUN_W, THREE_PHASE_VALUE, _amps, _cp, _host, _idle,
    _values,
)

try:                                       # the daily bound, once it exists
    from custom_components.solar_energy_management.coordinator.ev_phases import (
        PHASE_REST_SWITCHES_PER_DAY,
    )
except ImportError:                        # pragma: no cover — before the fix
    PHASE_REST_SWITCHES_PER_DAY = 6

STEP_S = 60.0
DAY_S = 24 * 3600.0


# ── 1. the cap counts the switches under load, not the ones at rest ───────

class TestTheCapCountsTheSwitchesUnderLoad:

    def test_the_sequencer_says_when_a_switch_was_at_rest(self):
        seq = PhaseSwitchSequencer()
        r = seq.tick(now=0.0, desired_phases=1, believed_phases=3,
                     charging=False, capability_ready=True)
        assert r.issue_switch == 1 and r.at_rest is True

    def test_a_switch_that_needed_a_stop_was_not_at_rest(self):
        seq = PhaseSwitchSequencer()
        r = seq.tick(now=0.0, desired_phases=1, believed_phases=3,
                     charging=True, capability_ready=True)
        assert r.hold_charging and r.issue_switch is None
        r = seq.tick(now=10.0, desired_phases=1, believed_phases=3,
                     charging=False, capability_ready=True)
        assert r.issue_switch == 1 and r.at_rest is False

    def test_four_switches_at_rest_leave_the_start_open(self):
        p = PhaseAutoPlanner(min_current_a=6, voltage=230.0)
        t = 0.0
        for _ in range(AUTO_MAX_PER_SESSION):
            p.note_switched(t, at_rest=True)
            t += AUTO_MIN_INTERVAL_S + 1
        t += 10.0
        answer = None
        end = t + AUTO_START_DELAY_S + 20
        while t <= end:
            answer = p.desired(t, None, THIN_SUN_W, idle=True)
            t += 10.0
        assert answer == 1

    def test_four_switches_under_load_still_close_it(self):
        p = PhaseAutoPlanner(min_current_a=6, voltage=230.0)
        t = 0.0
        for _ in range(AUTO_MAX_PER_SESSION):
            p.note_switched(t)
            t += AUTO_MIN_INTERVAL_S + 1
        answer = None
        end = t + AUTO_START_DELAY_S + 20
        while t <= end:
            answer = p.desired(t, None, THIN_SUN_W, idle=True)
            t += 10.0
        assert answer is None

    def test_a_switch_at_rest_still_starts_the_interval(self):
        """The planner's own answers keep the half hour between switches."""
        p = PhaseAutoPlanner(min_current_a=6, voltage=230.0)
        p.note_switched(0.0, at_rest=True)
        t, answer = 10.0, None
        while t <= AUTO_START_DELAY_S + 200:
            answer = p.desired(t, None, THIN_SUN_W, idle=True)
            t += 10.0
        assert answer is None


# ── the pipeline: three days, one plug session ───────────────────────────

def _day_decisions(h, owed):
    """The plan the loop stores for a night, or none when nothing is owed."""
    h._night_plan_per_charger = (
        {"c1": SimpleNamespace(remaining_kwh=8.0, hours_to_deadline=9.0)}
        if owed else {})


def _simulate(h, days, owed, hours=None):
    """Step the tick once a minute through ``days`` days. Thin sun by day
    (the charger idles on 2 kW), night from 21:00 to 07:00. Returns the
    ``(day, hour, value)`` of every phase write."""
    loop = asyncio.new_event_loop()
    writes = []
    seen = 0
    try:
        t = 0.0
        while t < days * DAY_S:
            hour = (t % DAY_S) / 3600.0
            night = hour >= 21.0 or hour < 7.0
            _day_decisions(h, owed and night)
            d = _idle(0.0 if night else THIN_SUN_W)
            out = loop.run_until_complete(h._phase_switch_tick(
                "c1", h.cfg, d, _cp(), t, is_night=night))
            assert out.intent is not ChargerIntent.CHARGE_AT_AMPS
            vals = _values(h)
            for v in vals[seen:]:
                writes.append((int(t // DAY_S) + 1, round(hour, 1), v))
            seen = len(vals)
            t += STEP_S
    finally:
        loop.close()
    return writes


class TestThreeDaysOnePlugSession:

    def test_with_energy_owed_every_night_all_three_days_get_their_start(self):
        """The report: day 3 had no 1-phase start."""
        h = _host()
        writes = _simulate(h, 3, owed=True)
        values = [v for _d, _h, v in writes]
        assert values == [ONE_PHASE_VALUE, THREE_PHASE_VALUE] * 3, writes
        days = [d for d, _h, _v in writes]
        assert days == [1, 1, 2, 2, 3, 3], "day 3 starts on one phase again"

    def test_with_nothing_owed_it_stays_on_one_phase(self):
        """One write in three days, not five: nothing to buy tonight, so no
        reason to write the installation at 21:00."""
        h = _host()
        writes = _simulate(h, 3, owed=False)
        assert [v for _d, _h, v in writes] == [ONE_PHASE_VALUE], writes
        assert h._phase_believed["c1"] == 1

    def test_the_night_return_comes_with_the_night_when_owed(self):
        h = _host()
        writes = _simulate(h, 2, owed=True)
        returns = [(d, hr) for d, hr, v in writes if v == THREE_PHASE_VALUE]
        assert returns and all(hr >= 21.0 or hr < 8.0 for _d, hr in returns), writes

    def test_the_session_counter_never_reached_the_cap(self):
        h = _host()
        _simulate(h, 3, owed=True)
        assert h._phase_planners["c1"]._session_switches == 0, (
            "all five switches were made with the charger at rest")


# ── the night return waits for a reason ──────────────────────────────────

class TestTheNightReturnWaitsForAGridBlock:

    def _one_phase(self):
        from .test_1412_phase_review import _on_one_phase_by_sems_choice
        return _on_one_phase_by_sems_choice()

    def test_nothing_owed_no_return(self):
        h, t = self._one_phase()
        h._night_plan_per_charger = {}
        loop = asyncio.new_event_loop()
        try:
            for i in range(60):
                loop.run_until_complete(h._phase_switch_tick(
                    "c1", h.cfg, _idle(), _cp(), t + 10 * i, is_night=True))
        finally:
            loop.close()
        assert _values(h) == [ONE_PHASE_VALUE]

    def test_a_planned_block_brings_it(self):
        h, t = self._one_phase()
        h._night_plan_per_charger = {"c1": SimpleNamespace(
            remaining_kwh=8.0, hours_to_deadline=9.0)}
        loop = asyncio.new_event_loop()
        try:
            for i in range(6):
                loop.run_until_complete(h._phase_switch_tick(
                    "c1", h.cfg, _idle(), _cp(), t + 10 * i, is_night=True))
        finally:
            loop.close()
        assert _values(h) == [ONE_PHASE_VALUE, THREE_PHASE_VALUE]

    def test_a_charge_the_grid_pays_for_brings_it_with_or_without_a_plan(self):
        from custom_components.solar_energy_management.coordinator import (
            reason_codes as RC,
        )
        h, t = self._one_phase()
        h._night_plan_per_charger = {}
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(h._phase_switch_tick(
                "c1", h.cfg, _amps(6), _cp(), t, is_night=True,
                source_code=RC.CHARGER_TOP_UP))
        finally:
            loop.close()
        assert _values(h) == [ONE_PHASE_VALUE, THREE_PHASE_VALUE]

    def test_the_night_is_sized_on_one_phase_when_it_stays(self):
        """Nothing owed means no plan; with a plan owed the night is three."""
        from custom_components.solar_energy_management.coordinator import (
            ev_control,
        )
        h, t = self._one_phase()
        h._night_plan_per_charger = {}
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(h._phase_switch_tick(
                "c1", h.cfg, _idle(), _cp(), t, is_night=True))
        finally:
            loop.close()
        assert ev_control._phases_now(h, h.cfg, 3) == 1


# ── a broken charger is not written all day ──────────────────────────────

class TestADailyBoundOnWritesAtRest:

    def test_a_charger_that_flips_every_few_minutes_is_cut_off(self):
        """Night and day alternate every 40 minutes with energy owed: the
        interval alone allowed a pair of writes every hour."""
        h = _host()
        loop = asyncio.new_event_loop()
        try:
            t = 0.0
            while t < DAY_S:
                night = int(t // 2400) % 2 == 0
                h._night_plan_per_charger = (
                    {"c1": SimpleNamespace(remaining_kwh=8.0,
                                           hours_to_deadline=9.0)}
                    if night else {})
                loop.run_until_complete(h._phase_switch_tick(
                    "c1", h.cfg, _idle(0.0 if night else THIN_SUN_W),
                    _cp(), t, is_night=night))
                t += STEP_S
        finally:
            loop.close()
        assert 2 <= len(_values(h)) <= PHASE_REST_SWITCHES_PER_DAY

    def test_the_next_day_it_may_switch_again(self):
        h = _host()
        loop = asyncio.new_event_loop()
        try:
            t = 0.0
            while t < 2 * DAY_S:
                night = int(t // 2400) % 2 == 0
                h._night_plan_per_charger = (
                    {"c1": SimpleNamespace(remaining_kwh=8.0,
                                           hours_to_deadline=9.0)}
                    if night else {})
                loop.run_until_complete(h._phase_switch_tick(
                    "c1", h.cfg, _idle(0.0 if night else THIN_SUN_W),
                    _cp(), t, is_night=night))
                t += STEP_S
        finally:
            loop.close()
        assert len(_values(h)) > PHASE_REST_SWITCHES_PER_DAY
        assert len(_values(h)) <= 2 * PHASE_REST_SWITCHES_PER_DAY + 1

    def test_a_manual_phase_mode_is_the_owners_and_not_bound(self):
        h = _host({"phase_mode": "1"})
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(h._phase_switch_tick(
                "c1", h.cfg, _idle(), _cp(), 0.0))
        finally:
            loop.close()
        assert _values(h) == [ONE_PHASE_VALUE]
