"""#724 — moving the ``Charge by`` time must not re-bucket the day that is
already running.

The EV day is deadline-based (#279): ``_ev_reset_day`` asks
``get_current_meter_day_offset_based(deadline)``, which answers *yesterday*
whenever ``now < deadline``. That is right for a FIXED deadline and wrong the
moment the user moves it, because the answer is re-derived from the live config
on every cycle:

    deadline 07:00, now 12:00              → ev_day = today
    user moves the deadline to 23:00       → now < 23:00 → ev_day = YESTERDAY

...so ``sensor.sem_daily_ev_energy`` starts reading yesterday's bucket (which
``_check_rollover`` deliberately keeps for EV) and every further increment
lands there too, merging two days. Nothing charged, the number just moved.

A boundary change is legitimate; applying it to a day that has already been
accumulated into is not. The rule pinned here: **the boundary that opened the
current EV day owns it until that day rolls.** A new deadline is adopted at the
next rollover of the OLD boundary — and the memo survives a restart, per #645
rule 2 (a memo about a boundary that does not outlive a restart across that
boundary just reinstates the bug on the next reboot).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)


class _FakeTimeManager:
    """Only the two meter-day helpers ``_ev_reset_day`` reaches for.

    Faithful to the REAL TimeManager's contract (review of f9045aa): it never
    raises on a junk offset — ``get_offset_time`` silently falls back to
    midnight. An earlier fake raised instead, which let a test document a
    discard path production didn't actually have.
    """

    def __init__(self, now: datetime):
        self.now = now

    def get_current_meter_day_offset_based(self, offset: str = "00:00") -> date:
        try:
            hh_s, mm_s = str(offset).split(":")[:2]
            hh, mm = int(hh_s), int(mm_s)
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError(offset)
        except (ValueError, AttributeError):
            hh, mm = 0, 0  # the real TM's midnight fallback
        boundary = self.now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return (self.now.date() - timedelta(days=1)) if self.now < boundary \
            else self.now.date()

    def get_current_meter_day_sunrise_based(self) -> date:
        return self.now.date()


def _calc(now: datetime, deadline: str) -> EnergyCalculator:
    calc = EnergyCalculator.__new__(EnergyCalculator)
    calc.config = {"ev_chargers": [{"id": "keba", "ev_target_time": deadline}]}
    calc._time_manager = _FakeTimeManager(now)
    calc._ev_day_offset = None
    calc._ev_day_key = None
    return calc


NOON = datetime(2026, 8, 5, 12, 0)
TODAY = date(2026, 8, 5)
YESTERDAY = date(2026, 8, 4)


class TestBoundaryMoveDoesNotRebucketToday:
    def test_a_stable_deadline_is_unchanged(self):
        """The whole #279 behaviour must survive: before the deadline we are
        still in yesterday's EV day, after it we are in today's."""
        calc = _calc(datetime(2026, 8, 5, 6, 0), "07:00")
        assert calc._ev_reset_day(calc._time_manager.now) == YESTERDAY

        calc = _calc(NOON, "07:00")
        assert calc._ev_reset_day(NOON) == TODAY

    def test_moving_the_deadline_later_keeps_the_running_day(self):
        """The live bug: 07:00 → 23:00 at midday flipped the key to yesterday."""
        calc = _calc(NOON, "07:00")
        assert calc._ev_reset_day(NOON) == TODAY

        calc.config["ev_chargers"][0]["ev_target_time"] = "23:00"
        assert calc._ev_reset_day(NOON) == TODAY, (
            "moving the deadline re-bucketed the day that was already running"
        )

    def test_moving_the_deadline_earlier_keeps_the_running_day(self):
        """Mirror direction: a day opened under a late deadline must not jump
        forward and orphan what it already holds."""
        calc = _calc(NOON, "23:00")
        assert calc._ev_reset_day(NOON) == YESTERDAY

        calc.config["ev_chargers"][0]["ev_target_time"] = "06:00"
        assert calc._ev_reset_day(NOON) == YESTERDAY

    def test_the_new_deadline_is_adopted_once_the_old_boundary_rolls(self):
        """Deferred, not ignored — the change takes effect at the next
        rollover of the boundary that owned the day."""
        calc = _calc(NOON, "07:00")
        assert calc._ev_reset_day(NOON) == TODAY

        calc.config["ev_chargers"][0]["ev_target_time"] = "23:00"
        assert calc._ev_reset_day(NOON) == TODAY

        # 07:00 next morning: the old boundary has rolled, so the pending
        # 23:00 deadline takes over — and at 08:00 that means yesterday's day.
        tomorrow_morning = datetime(2026, 8, 6, 8, 0)
        calc._time_manager.now = tomorrow_morning
        assert calc._ev_reset_day(tomorrow_morning) == TODAY  # = 05.08, under 23:00

    def test_no_chargers_falls_back_to_the_global_default(self):
        calc = _calc(NOON, "07:00")
        calc.config = {"ev_chargers": [], "ev_target_time": "07:00"}
        assert calc._ev_reset_day(NOON) == TODAY


class TestFleetNeedsASharedBoundary:
    """#724 part 2 — a fleet total bucketed on one member's clock describes
    none of them."""

    def _two_chargers(self, first: str, second: str) -> EnergyCalculator:
        calc = _calc(NOON, first)
        calc.config["ev_chargers"].append(
            {"id": "second", "ev_target_time": second}
        )
        return calc

    def test_an_agreeing_fleet_still_uses_the_shared_deadline(self):
        """#279 is untouched wherever it was actually reported: one charger,
        or several on the same Charge-by time."""
        calc = self._two_chargers("07:00", "07:00")
        assert calc._ev_reset_day(NOON) == TODAY

        early = _calc(datetime(2026, 8, 5, 6, 0), "07:00")
        early.config["ev_chargers"].append(
            {"id": "second", "ev_target_time": "07:00"}
        )
        assert early._ev_reset_day(early._time_manager.now) == YESTERDAY

    def test_a_disagreeing_fleet_falls_back_to_calendar_midnight(self):
        """Was: max() = 23:00 → yesterday, a bucket belonging to charger two
        alone. Now: midnight, the boundary both chargers share."""
        calc = self._two_chargers("06:00", "23:00")
        assert calc._ev_reset_day(NOON) == TODAY

    def test_the_calendar_fallback_holds_all_day(self):
        """Midnight-bucketed means today's key from 00:00 to 23:59 — never the
        pre-deadline 'yesterday' answer that made the fleet figure jump."""
        for hour in (0, 5, 12, 22, 23):
            calc = self._two_chargers("06:00", "23:00")
            calc._time_manager.now = datetime(2026, 8, 5, hour, 30)
            assert calc._ev_reset_day(calc._time_manager.now) == TODAY, (
                f"fleet day wrong at {hour:02d}:30"
            )

    def test_agreement_arriving_later_is_deferred_like_any_boundary_change(self):
        """Aligning two chargers is itself a boundary change, so the same
        deferral applies — no retroactive re-bucket."""
        calc = self._two_chargers("06:00", "23:00")
        assert calc._ev_reset_day(NOON) == TODAY  # calendar

        calc.config["ev_chargers"][1]["ev_target_time"] = "06:00"
        # Under midnight the day has not rolled, so the newly-shared 06:00
        # deadline waits rather than re-keying the running day.
        assert calc._ev_reset_day(NOON) == TODAY


class TestMemoSurvivesRestart:
    """#645 rule 2 — a boundary memo that dies on restart reinstates the bug."""

    def test_state_round_trips_the_boundary_in_effect(self):
        calc = _calc(NOON, "07:00")
        calc._ev_reset_day(NOON)

        state = {
            "ev_day_offset": calc._ev_day_offset,
            "ev_day_key": calc._ev_day_key.isoformat(),
        }
        assert state["ev_day_offset"] == "07:00"
        assert state["ev_day_key"] == "2026-08-05"

        # Restart mid-day with the deadline already moved: the restored memo
        # keeps the running day instead of re-deriving from the new config.
        restored = _calc(NOON, "23:00")
        restored._ev_day_offset = state["ev_day_offset"]
        restored._ev_day_key = date.fromisoformat(state["ev_day_key"])
        assert restored._ev_reset_day(NOON) == TODAY

    @pytest.mark.parametrize("bad", ["", "not-a-time", "25:00", "07:60", None])
    def test_an_unusable_offset_is_discarded_not_held(self, bad):
        """The discard must be REAL (review of f9045aa): the time manager
        treats junk as midnight rather than raising, so without explicit
        validation a corrupt memo would silently HOLD the running day on a
        midnight boundary nobody configured. Fixture chosen so hold-on-junk
        and derive-from-config give DIFFERENT answers: at 06:00 under a
        07:00 deadline the honest answer is YESTERDAY, while a junk memo
        interpreted as midnight would have held TODAY."""
        early = datetime(2026, 8, 5, 6, 0)
        calc = _calc(early, "07:00")
        calc._ev_day_offset = bad
        calc._ev_day_key = TODAY  # what a midnight-read junk memo would hold
        assert calc._ev_reset_day(early) == YESTERDAY
        # ...and the memo was cleansed, not left to trip the next cycle.
        assert calc._ev_day_offset == "07:00"

    @pytest.mark.parametrize("bad", ["", "not-a-time", "25:00", "07:60", 7])
    def test_a_corrupt_stored_offset_never_restores(self, bad):
        """restore_state's gate: a memo with a junk offset is equivalent to
        no memo (the upgrade seam takes over), never adopted as-is."""
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            _valid_hhmm,
        )
        assert not _valid_hhmm(bad)
        assert _valid_hhmm("07:00") and _valid_hhmm("23:59") and _valid_hhmm("0:05")


class TestUpgradeSeam:
    """A pre-#724 store has EV buckets but no day memo. The new fleet rule
    must take over at a ROLLOVER, not mid-flight at upgrade."""

    def test_a_disagreeing_fleet_keeps_its_legacy_day_through_the_upgrade(self):
        # Legacy rule at noon under max(06:00, 23:00)=23:00 → the running day
        # is YESTERDAY's key. Without the seam, the new calendar rule would
        # re-key to TODAY at upgrade and the sensor would jump once.
        calc = _calc(NOON, "06:00")
        calc.config["ev_chargers"].append(
            {"id": "second", "ev_target_time": "23:00"}
        )
        calc._seed_ev_day_memo_from_legacy_rule()
        assert (calc._ev_day_offset, calc._ev_day_key) == ("23:00", YESTERDAY)
        assert calc._ev_reset_day(NOON) == YESTERDAY  # continuity held

        # ...and once the legacy boundary rolls (23:00 tonight), the calendar
        # rule takes over for good.
        after_roll = datetime(2026, 8, 5, 23, 30)
        calc._time_manager.now = after_roll
        assert calc._ev_reset_day(after_roll) == TODAY
        assert calc._ev_day_offset == "00:00"

    def test_an_agreeing_fleet_seeds_a_value_the_new_rule_reproduces(self):
        calc = _calc(NOON, "07:00")
        calc._seed_ev_day_memo_from_legacy_rule()
        assert (calc._ev_day_offset, calc._ev_day_key) == ("07:00", TODAY)
        assert calc._ev_reset_day(NOON) == TODAY

    def test_an_ev_less_config_seeds_the_default_and_stays_harmless(self):
        """DEFAULT_EV_TARGET_TIME means _ev_deadlines is never empty, so the
        seed always seeds — pin what it seeds and that an EV-less install is
        unharmed: the memo matches what the live rule derives anyway, so
        _ev_reset_day's hold branch never engages and daily_ev stays on the
        exact key it would have used without any memo. (An earlier version
        of this test asserted a 'seeds nothing' path that is unreachable —
        review of f9045aa.)"""
        calc = _calc(NOON, "07:00")
        calc.config = {"ev_chargers": [], "ev_target_time": None}
        calc._seed_ev_day_memo_from_legacy_rule()
        assert (calc._ev_day_offset, calc._ev_day_key) == ("07:00", TODAY)
        assert calc._ev_reset_day(NOON) == TODAY
