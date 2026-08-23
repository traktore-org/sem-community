"""#778 — recover a forecast ledger from history that already exists.

An install that has been running for months already knows how good its forecast
is; it just never wrote it down in a form the ledger could read. Waiting seven
days to learn something the recorder can already prove is a waste of the user's
time, and it is the difference between "the budget works next week" and "the
budget works now".

Guido's idea, and .175 makes the case: five months of ``forecast_tomorrow_kwh``
and ``daily_solar_energy`` sitting in the statistics table — 139 settled pairs,
which is what exposed the trust-model flaw in the first place.

The pairing rules are the whole substance here, so they are what is tested:

* the forecast FOR a day is the last one published BEFORE that day began —
  the figure a decision that evening would actually have used, not a
  mid-morning revision that already knew how the day was going;
* the actual FOR a day is the day's final daily-counter reading;
* a pair needs both halves and a positive forecast (a zero forecast has no
  ratio);
* backfilled evidence NEVER overwrites a day the coordinator recorded live.
"""

import datetime

import pytest

from custom_components.solar_energy_management.coordinator.ledger_backfill import (
    backfill_pairs,
    daily_maxima,
    last_reading_before,
)


def _dt(day, hour, minute=0):
    return datetime.datetime(2026, 8, day, hour, minute)


class TestLastReadingBefore:
    """The forecast a decision would actually have had."""

    def test_it_takes_the_latest_reading_in_the_window(self):
        series = {_dt(20, 18): 40.0, _dt(20, 21): 44.0, _dt(20, 23): 46.0}
        assert last_reading_before(series, datetime.date(2026, 8, 20), 18) == 46.0

    def test_readings_before_the_window_are_ignored(self):
        """A forecast published at 06:00 for 'tomorrow' is a different, older
        statement than the one standing at 23:00."""
        series = {_dt(20, 6): 99.0, _dt(20, 20): 40.0}
        assert last_reading_before(series, datetime.date(2026, 8, 20), 18) == 40.0

    def test_a_day_with_no_reading_in_the_window_yields_none(self):
        series = {_dt(20, 6): 99.0}
        assert last_reading_before(series, datetime.date(2026, 8, 20), 18) is None

    def test_other_days_do_not_leak_in(self):
        series = {_dt(19, 22): 10.0, _dt(21, 22): 30.0}
        assert last_reading_before(series, datetime.date(2026, 8, 20), 18) is None


class TestDailyMaxima:
    def test_a_daily_counter_resolves_to_its_high_water_mark(self):
        series = {_dt(20, 8): 3.0, _dt(20, 13): 21.0, _dt(20, 19): 34.4}
        assert daily_maxima(series)[datetime.date(2026, 8, 20)] == 34.4

    def test_a_counter_reset_does_not_lower_the_day(self):
        """Midnight resets the counter; the day's total is what it reached."""
        series = {_dt(20, 23): 34.4, _dt(20, 23, 59): 0.0}
        assert daily_maxima(series)[datetime.date(2026, 8, 20)] == 34.4


class TestBackfillPairs:
    FC = {_dt(19, 22): 59.6, _dt(20, 22): 27.17, _dt(21, 22): 8.88}
    ACT = {_dt(20, 19): 27.85, _dt(21, 19): 14.26, _dt(22, 19): 56.52}

    def test_a_forecast_pairs_with_the_NEXT_day(self):
        """Horizon 1 means 'made yesterday, for today'. Getting this off by a
        day would produce a ledger that looks full and measures nothing."""
        out = backfill_pairs(self.FC, self.ACT, horizon=1, settle_after_hour=18)
        assert out[datetime.date(2026, 8, 20)] == (59.6, 27.85)
        assert out[datetime.date(2026, 8, 21)] == (27.17, 14.26)
        assert out[datetime.date(2026, 8, 22)] == (8.88, 56.52)

    def test_horizon_zero_pairs_a_day_with_itself(self):
        fc = {_dt(20, 8): 30.0}
        act = {_dt(20, 19): 27.85}
        out = backfill_pairs(fc, act, horizon=0, settle_after_hour=6)
        assert out[datetime.date(2026, 8, 20)] == (30.0, 27.85)

    def test_an_unmatched_forecast_is_dropped(self):
        out = backfill_pairs({_dt(25, 22): 40.0}, self.ACT, horizon=1,
                             settle_after_hour=18)
        assert datetime.date(2026, 8, 26) not in out

    def test_a_zero_forecast_is_dropped(self):
        """No ratio exists; keeping it would divide by zero downstream or,
        worse, be silently skipped and inflate the 'days settled' count."""
        out = backfill_pairs({_dt(19, 22): 0.0}, self.ACT, horizon=1,
                             settle_after_hour=18)
        assert out == {}

    def test_a_zero_actual_is_kept(self):
        """A day that genuinely produced nothing IS evidence — and the most
        important kind: it is the forecast's worst miss."""
        out = backfill_pairs({_dt(19, 22): 40.0}, {_dt(20, 19): 0.0},
                             horizon=1, settle_after_hour=18)
        assert out[datetime.date(2026, 8, 20)] == (40.0, 0.0)

    def test_empty_inputs_are_not_an_error(self):
        assert backfill_pairs({}, {}, horizon=1, settle_after_hour=18) == {}


class TestLiveEvidenceWins:
    """A backfilled pair must never overwrite what the coordinator recorded
    live: the live record is what SEM actually saw at the moment it decided,
    while the backfill is a reconstruction from hourly buckets."""

    def test_backfill_skips_a_day_already_recorded(self):
        from custom_components.solar_energy_management.coordinator.forecast_ledger import (
            ForecastLedger,
        )
        led = ForecastLedger()
        led.record("2026-08-20", 1, 55.0)
        led.settle("2026-08-20", 30.0)
        added = led.backfill({
            datetime.date(2026, 8, 20): (59.6, 27.85),
            datetime.date(2026, 8, 21): (27.17, 14.26),
        }, horizon=1)
        assert added == 1
        assert led.forecast_for("2026-08-20", 1) == 55.0
        assert led.actual_for("2026-08-20") == 30.0
        assert led.forecast_for("2026-08-21", 1) == 27.17

    def test_backfill_reports_what_it_added(self):
        from custom_components.solar_energy_management.coordinator.forecast_ledger import (
            ForecastLedger,
        )
        led = ForecastLedger()
        added = led.backfill({datetime.date(2026, 8, d): (40.0, 35.0)
                              for d in range(10, 20)}, horizon=1)
        assert added == 10
        assert led.settled_samples(1) == 10
        assert led.trust(1) is not None
