"""#645 — a restart that spans midnight must not swallow the daily decay.

The virtual-SOC daily decay (#106/#648) used to be a side effect of the
hour-bucket rollover, gated on the coordinator's in-memory ``_tracker_date``.
That date is re-initialised to *today* in ``__init__``, deliberately:

    # Initialize to today so restarts don't re-apply daily decay

The intent (never decay twice) was right; the mechanism conflated it with a
second, unwanted property (never decay after a restart at all). HA restarting
at 00:30 — a nightly-backup reboot, an update, a power blip — meant the decay
for the day that just ended never ran.

That is load-bearing, not cosmetic. ``_resolve_charger_soc`` falls back to the
virtual SOC when the real SOC entity is offline, so an un-decayed detector
reads "still nearly full", ``build_night_target_map`` computes remaining ≈ 0,
and a night charge the car actually needed is silently skipped.

The fix persists the date the decay LAST RAN, separately from the hour-bucket
tracker, so "already decayed today" and "never decayed today" stop being the
same state.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.storage import (
    SEMStorage,
)


def _coord(last_decay):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._last_decay_date = last_decay
    c._storage = MagicMock()
    c.hass = MagicMock()
    c._apply_daily_taper_decay = MagicMock()
    return c


TODAY = date(2026, 7, 25)


@pytest.mark.unit
class TestRestartSpanningMidnight645:
    def test_the_bug_restart_after_midnight_still_decays(self):
        """THE closure. HA restarted at 00:30; the last decay was yesterday's
        rollover. Pre-fix the tracker read "today" and nothing happened."""
        c = _coord(date(2026, 7, 24))

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._apply_daily_taper_decay.assert_called_once()
        assert c._last_decay_date == TODAY

    def test_restart_later_the_same_day_does_not_decay_again(self):
        """The property the original comment was protecting, kept intact."""
        c = _coord(TODAY)

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._apply_daily_taper_decay.assert_not_called()

    def test_repeated_cycles_within_the_day_decay_exactly_once(self):
        """The rollover check runs every coordinator cycle (~10 s), so "once
        per day" has to survive being asked hundreds of times."""
        c = _coord(date(2026, 7, 24))

        for _ in range(50):
            c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._apply_daily_taper_decay.assert_called_once()

    def test_fresh_install_adopts_today_without_decaying(self):
        """No persisted date = nothing to catch up on. Decaying here would
        knock a brand-new install's virtual SOC down for no reason."""
        c = _coord(None)

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._apply_daily_taper_decay.assert_not_called()
        assert c._last_decay_date == TODAY
        c._storage.set_last_decay_date.assert_called_once_with("2026-07-25")

    def test_a_multi_day_outage_catches_up_one_decay_per_missed_day(self):
        """HA was off for three days; the car was presumably driven on each."""
        c = _coord(date(2026, 7, 22))

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        assert c._apply_daily_taper_decay.call_count == 3

    def test_the_catchup_is_bounded(self):
        """A months-long outage (or a clock jump) must not spin. The decay is
        already clamped at battery capacity, so the cap only bounds the loop."""
        c = _coord(date(2025, 1, 1))

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        assert (
            c._apply_daily_taper_decay.call_count
            == SEMCoordinator.MAX_DECAY_CATCHUP_DAYS
        )
        assert c._last_decay_date == TODAY

    def test_a_backwards_clock_does_not_decay(self):
        """DST / NTP correction can move the date backwards. Treat it as
        "already decayed" rather than computing a negative day count."""
        c = _coord(date(2026, 7, 26))

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._apply_daily_taper_decay.assert_not_called()

    def test_persisting_writes_through_immediately(self):
        """Setting the key only mutates the in-memory energy dict, and the
        BATCHED save cannot flush it: ``async_delay_save`` re-arms its timer on
        every call, so under the continuous update loop it only ever fires at a
        clean shutdown. A value that exists to survive a restart must not
        depend on the restart being graceful. Caught live on HA-TEST — the key
        was still absent from the store ten minutes after deploy."""
        c = _coord(date(2026, 7, 24))

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._storage.set_last_decay_date.assert_called_once_with("2026-07-25")
        c.hass.async_create_task.assert_called_once()
        c._storage.async_save_energy_now.assert_called_once()
        c._storage.async_save_energy_delayed.assert_not_called()

    def test_a_storage_failure_does_not_break_the_cycle(self):
        """Persistence is bookkeeping — a failed write must not take down the
        update cycle. Worst case the decay repeats after the next restart."""
        c = _coord(date(2026, 7, 24))
        c._storage.set_last_decay_date.side_effect = RuntimeError("disk full")

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())   # must not raise

        c._apply_daily_taper_decay.assert_called_once()


@pytest.mark.unit
class TestDecayDatePersistence645:
    def _storage(self):
        s = SEMStorage.__new__(SEMStorage)
        s._energy_data = {}
        return s

    def test_round_trip(self):
        s = self._storage()
        s.set_last_decay_date("2026-07-25")
        assert s.get_last_decay_date() == "2026-07-25"

    def test_absent_reads_none(self):
        assert self._storage().get_last_decay_date() is None

    def test_a_non_string_reads_none(self):
        """Hand-edited or legacy stores. A bad value must degrade to "unknown"
        (adopt today) rather than raise inside the update cycle."""
        s = self._storage()
        s._energy_data["last_decay_date"] = 20260725
        assert s.get_last_decay_date() is None

    def test_the_immediate_save_carries_the_whole_energy_dict(self):
        """The write-through must not replace the store with just this key —
        ``ev_intelligence`` / ``sign_state`` / accumulators live in the same
        dict and would be wiped."""
        import asyncio

        s = self._storage()
        s._energy_data = {"sign_state": {"grid": "negated"}}
        s.set_last_decay_date("2026-07-25")
        s._energy_store = MagicMock()
        saved = {}

        async def _save(payload):
            saved.update(payload)

        s._energy_store.async_save = _save
        asyncio.run(s.async_save_energy_now())

        assert saved["last_decay_date"] == "2026-07-25"
        assert saved["sign_state"] == {"grid": "negated"}

    def test_it_lives_in_energy_data_not_daily_data(self):
        """``_daily_data`` is wiped at the daily reset — persisting the decay
        date there would make it unreadable exactly when it's needed."""
        s = self._storage()
        s.set_last_decay_date("2026-07-25")
        assert s._energy_data["last_decay_date"] == "2026-07-25"


@pytest.mark.unit
class TestRestore645:
    """Behavioural — the source pin below only proves ORDER, not that a stored
    date survives the trip back into memory."""

    def _c(self, stored):
        c = SEMCoordinator.__new__(SEMCoordinator)
        c._last_decay_date = None
        c._storage = MagicMock()
        c._storage.get_last_decay_date.return_value = stored
        return c

    def test_a_stored_date_lands_as_a_date_object(self):
        c = self._c("2026-07-24")
        c._restore_last_decay_date()
        assert c._last_decay_date == date(2026, 7, 24)

    def test_nothing_stored_leaves_it_none(self):
        c = self._c(None)
        c._restore_last_decay_date()
        assert c._last_decay_date is None

    def test_a_malformed_date_is_ignored_not_raised(self):
        """A hand-edited store must not break the whole first refresh."""
        c = self._c("last tuesday")
        c._restore_last_decay_date()          # must not raise
        assert c._last_decay_date is None

    def test_restore_then_rollover_decays_the_missed_day(self):
        """The end-to-end shape of the bug: yesterday's date comes back out of
        storage and the decay for the day that ended actually fires."""
        c = self._c("2026-07-24")
        c._apply_daily_taper_decay = MagicMock()

        c._restore_last_decay_date()
        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())

        c._apply_daily_taper_decay.assert_called_once()

    def test_without_restore_the_missed_day_is_lost(self):
        """The counter-case that makes the test above mean something — this is
        exactly what the pre-fix code did on every restart."""
        c = self._c("2026-07-24")
        c._apply_daily_taper_decay = MagicMock()

        c._run_due_daily_decay(MagicMock(), TODAY, MagicMock())   # no restore

        c._apply_daily_taper_decay.assert_not_called()


@pytest.mark.unit
class TestRestoreIsWiredBeforeTheRollover645:
    def test_restore_runs_before_the_rollover_check(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            coordinator as mod,
        )

        src = inspect.getsource(mod.SEMCoordinator._async_update_data)
        assert "self._restore_last_decay_date()" in src
        # Restore must come BEFORE the rollover check in the same method,
        # otherwise the first cycle adopts today and the missed day is lost.
        assert src.index("_restore_last_decay_date") < src.index("_run_due_daily_decay")

    def test_the_tracker_date_no_longer_gates_the_decay(self):
        """The whole point: the hour-bucket rollover and the decay are two
        separate decisions now."""
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            coordinator as mod,
        )

        src = inspect.getsource(mod.SEMCoordinator._async_update_data)
        tracker_branch = src[src.index("if self._tracker_date != today_date:"):]
        tracker_branch = tracker_branch[: tracker_branch.index("_run_due_daily_decay")]
        assert "_apply_daily_taper_decay" not in tracker_branch, (
            "decay is back inside the restart-reinitialised tracker branch (#645)"
        )
