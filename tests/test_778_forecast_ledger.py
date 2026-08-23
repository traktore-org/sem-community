"""#778 — a forecast ledger with a HORIZON, so day-2 can be trusted by evidence.

Guido, 23.08: *"Are we creating a ledger for the forecast as well so we can
plan today with the forecast of tomorrow or the day after tomorrow?"*

SEM already keeps a forecast-accuracy record (``DailyForecastRecord``:
forecast vs actual, feeding the dampening factor). But it only ever knew ONE
horizon — the forecast made for today. The spendable-battery budget needs the
day after tomorrow, and a two-day-out forecast is materially less reliable
than a one-day-out one. **By how much is an empirical question nobody has
measured**, so this ledger measures it rather than assuming.

The shape is deliberately: *on day D we said day D+h would produce X; on day
D+h it actually produced Y.* Accuracy is then reported PER HORIZON, and the
budget scales its confidence accordingly instead of believing all days
equally.

The rule that keeps it honest: **too few samples means unknown, not 1.0.**
A ledger that returns a confident-looking default before it has evidence is
worse than one that admits it does not know — the budget can be conservative
with "unknown", but it cannot detect a lie.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    MIN_SAMPLES_FOR_TRUST,
    ForecastLedger,
)


@pytest.mark.unit
class TestRecordingAndSettling:

    def test_a_forecast_is_recorded_against_its_target_day(self):
        led = ForecastLedger()
        led.record("2026-08-25", horizon_days=2, forecast_kwh=31.6)
        assert led.forecast_for("2026-08-25", 2) == 31.6

    def test_several_horizons_for_the_same_day_coexist(self):
        """The same day is forecast repeatedly as it approaches — that is the
        whole point: we compare the 2-day-out guess with the 1-day-out one."""
        led = ForecastLedger()
        led.record("2026-08-25", 2, 31.6)
        led.record("2026-08-25", 1, 38.0)
        led.record("2026-08-25", 0, 41.2)
        assert led.forecast_for("2026-08-25", 2) == 31.6
        assert led.forecast_for("2026-08-25", 1) == 38.0
        assert led.forecast_for("2026-08-25", 0) == 41.2

    def test_re_recording_the_same_horizon_overwrites(self):
        led = ForecastLedger()
        led.record("2026-08-25", 1, 30.0)
        led.record("2026-08-25", 1, 33.0)
        assert led.forecast_for("2026-08-25", 1) == 33.0

    def test_settling_stores_the_actual(self):
        led = ForecastLedger()
        led.record("2026-08-25", 1, 30.0)
        led.settle("2026-08-25", actual_kwh=27.0)
        assert led.actual_for("2026-08-25") == 27.0


@pytest.mark.unit
class TestAccuracyIsReportedPerHorizon:

    def _seed(self, led, n, horizon, ratio):
        for i in range(n):
            day = f"2026-07-{i + 1:02d}"
            led.record(day, horizon, 40.0)
            led.settle(day, 40.0 * ratio)

    def test_a_horizon_with_enough_samples_reports_its_ratio(self):
        led = ForecastLedger()
        self._seed(led, MIN_SAMPLES_FOR_TRUST, horizon=1, ratio=0.9)
        acc = led.accuracy(1)
        assert acc is not None
        assert acc.samples >= MIN_SAMPLES_FOR_TRUST
        assert acc.mean_ratio == pytest.approx(0.9, abs=0.01)

    def test_horizons_are_measured_independently(self):
        """Day-1 optimistic, day-2 far worse — the ledger must not blend them."""
        led = ForecastLedger()
        for i in range(MIN_SAMPLES_FOR_TRUST):
            day = f"2026-06-{i + 1:02d}"
            led.record(day, 1, 40.0)
            led.record(day, 2, 40.0)
            led.settle(day, 36.0)          # 0.9 of the day-1 guess…
        # …both horizons guessed 40, so both ratios are 0.9 here; the point is
        # that they are computed from separate buckets.
        assert led.accuracy(1).samples == MIN_SAMPLES_FOR_TRUST
        assert led.accuracy(2).samples == MIN_SAMPLES_FOR_TRUST

    def test_unsettled_days_do_not_count(self):
        led = ForecastLedger()
        for i in range(MIN_SAMPLES_FOR_TRUST + 3):
            led.record(f"2026-05-{i + 1:02d}", 2, 40.0)
        assert led.accuracy(2) is None


@pytest.mark.unit
class TestTooFewSamplesMeansUnknown:
    """A confident-looking default before there is evidence is worse than an
    honest 'I do not know' — the budget can be conservative with unknown."""

    def test_no_data_is_none_not_one(self):
        assert ForecastLedger().accuracy(2) is None
        assert ForecastLedger().trust(2) is None

    def test_below_the_threshold_is_still_none(self):
        led = ForecastLedger()
        for i in range(MIN_SAMPLES_FOR_TRUST - 1):
            day = f"2026-04-{i + 1:02d}"
            led.record(day, 2, 40.0)
            led.settle(day, 38.0)
        assert led.accuracy(2) is None
        assert led.trust(2) is None

    def test_trust_never_exceeds_one(self):
        """An over-delivering forecast does not license spending MORE than
        forecast — optimism is capped, pessimism is not."""
        led = ForecastLedger()
        for i in range(MIN_SAMPLES_FOR_TRUST):
            day = f"2026-03-{i + 1:02d}"
            led.record(day, 1, 40.0)
            led.settle(day, 60.0)          # reality beat the forecast by 50%
        assert led.trust(1) == pytest.approx(1.0)


@pytest.mark.unit
class TestItStaysBounded:

    def test_old_days_are_pruned(self):
        led = ForecastLedger(max_days=5)
        for i in range(1, 12):
            day = f"2026-02-{i:02d}"
            led.record(day, 1, 10.0)
            led.settle(day, 9.0)
        assert len(led.days()) <= 5

    def test_round_trips_through_a_plain_dict(self):
        """It has to survive a restart in SEM's storage."""
        led = ForecastLedger()
        led.record("2026-08-25", 2, 31.6)
        led.settle("2026-08-25", 30.0)
        restored = ForecastLedger.from_dict(led.to_dict())
        assert restored.forecast_for("2026-08-25", 2) == 31.6
        assert restored.actual_for("2026-08-25") == 30.0
