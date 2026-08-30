"""#867 — PV degradation and trend were dead on every install.

``pv_estimated_annual_degradation`` reads 0.0 and ``pv_degradation_trend``
reads "unknown" on systems with years of production. The design is sound:
``_estimate_degradation`` compares the same month across years, which is the
honest way to cancel seasonality, and needs >= 13 monthly records.

It never had any. Two independent reasons, and each alone is fatal:

* ``record_monthly()`` — the only thing that appends to ``_monthly_history``
  — is called from **tests only**. Thirteen call sites, every one under
  ``tests/``. Nothing in production has ever recorded a month.
* ``_monthly_history`` is a plain in-memory list, created empty in
  ``__init__`` and persisted nowhere. Even with a caller, every restart
  would empty it, and 13 months of evidence cannot survive in a process
  that restarts on every upgrade.

This is #873's thesis in miniature: the PART was unit-tested thoroughly and
the ASSEMBLY — anything calling it — did not exist, so the tests passed
while the feature had never run once.

So this file tests the WIRING: that a completed month is recorded, exactly
once, and that the record survives a restart.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.analytics.pv_performance import (
    PVPerformanceAnalyzer,
)


def _analyzer(size_kwp=10.0):
    return PVPerformanceAnalyzer(MagicMock(), system_size_kwp=size_kwp)


class TestTheHistorySurvivesARestart:
    def test_state_round_trips(self):
        a = _analyzer()
        a.record_monthly(2025, 6, 300.0, forecast_kwh=320.0)
        a.record_monthly(2025, 7, 310.0, forecast_kwh=300.0)

        restored = _analyzer()
        restored.restore_state(a.export_state())

        assert restored.get_monthly_history() == a.get_monthly_history()

    def test_a_restart_no_longer_empties_the_evidence(self):
        """The concrete failure: 13 months of records, one restart, and the
        degradation verdict is back to 0.0 with nothing to say."""
        a = _analyzer()
        for i in range(26):
            a.record_monthly(2024 + i // 12, (i % 12) + 1, 300.0 - i)
        state = a.export_state()

        cold = _analyzer()
        assert cold.get_monthly_history() == [], "a fresh analyzer starts empty"
        cold.restore_state(state)
        assert len(cold.get_monthly_history()) == 26

    def test_restoring_nothing_is_survivable(self):
        a = _analyzer()
        for junk in ({}, None, {"monthly_history": None},
                     {"monthly_history": "not a list"}):
            a.restore_state(junk)
            assert a.get_monthly_history() == []

    def test_a_malformed_row_is_skipped_not_fatal(self):
        """Stored state outlives the code that wrote it."""
        a = _analyzer()
        a.restore_state({"monthly_history": [
            {"year": 2025, "month": 6, "total_kwh": 300.0,
             "specific_yield": 30.0, "forecast_kwh": 320.0,
             "performance_ratio": 93.8},
            {"year": "nonsense"},
            "not a dict",
        ]})
        assert len(a.get_monthly_history()) == 1

    def test_the_cap_survives_the_round_trip(self):
        """36 months is the retention rule; restoring must not smuggle in
        more than the recorder would ever keep."""
        a = _analyzer()
        a.restore_state({"monthly_history": [
            {"year": 2000 + i // 12, "month": (i % 12) + 1, "total_kwh": 100.0,
             "specific_yield": 10.0, "forecast_kwh": 0.0,
             "performance_ratio": 0.0}
            for i in range(60)
        ]})
        assert len(a.get_monthly_history()) == 36


class TestDegradationActuallyResolves:
    def test_thirteen_months_of_history_produce_a_verdict(self):
        """The whole point: with the evidence present, the number the card
        shows stops being 0.0."""
        a = _analyzer()
        # two full years, the second 5 % weaker — a real degradation signal
        for m in range(1, 13):
            a.record_monthly(2024, m, 300.0)
        for m in range(1, 13):
            a.record_monthly(2025, m, 285.0)
        assert a._estimate_degradation() == pytest.approx(5.0, abs=0.2)

    def test_a_restored_history_produces_the_same_verdict(self):
        """Persistence is only worth anything if the restored records feed
        the estimate exactly as the recorded ones did."""
        a = _analyzer()
        for m in range(1, 13):
            a.record_monthly(2024, m, 300.0)
        for m in range(1, 13):
            a.record_monthly(2025, m, 285.0)

        cold = _analyzer()
        cold.restore_state(a.export_state())
        assert cold._estimate_degradation() == pytest.approx(
            a._estimate_degradation(), abs=1e-9)


# ── the wiring: something must actually call the recorder ────────────────

import datetime  # noqa: E402

from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E402
    SEMCoordinator,
)


class _Calc:
    """An energy calculator holding one month's solar total."""

    def __init__(self, totals):
        self._totals = totals            # {"2026-08": kWh}

    def monthly_total_for(self, category, day):
        return self._totals.get(f"{day.year:04d}-{day.month:02d}", 0.0)


def _coord(totals, storage=None):
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord._pv_analyzer = _analyzer()
    coord._energy_calculator = _Calc(totals)
    coord._storage = storage
    return coord


class TestTheRecorderIsActuallyCalled:
    """``record_monthly`` had thirteen call sites and every one was a test.
    The production caller did not exist, which is why the feature had never
    run once on any install."""

    def test_the_month_that_just_ended_is_recorded(self):
        coord = _coord({"2026-08": 420.0})
        SEMCoordinator._record_completed_month(coord, datetime.date(2026, 9, 3))
        history = coord._pv_analyzer.get_monthly_history()
        assert len(history) == 1
        assert (history[0]["year"], history[0]["month"]) == (2026, 8)
        assert history[0]["kwh"] == pytest.approx(420.0)

    def test_it_is_recorded_once_not_once_per_cycle(self):
        """The check runs every cycle, so without an idempotence guard a
        month would be appended thousands of times and the 36-month window
        would hold a single month."""
        coord = _coord({"2026-08": 420.0})
        for day in range(3, 12):
            SEMCoordinator._record_completed_month(coord, datetime.date(2026, 9, day))
        assert len(coord._pv_analyzer.get_monthly_history()) == 1

    def test_a_month_with_no_production_is_not_recorded(self):
        """A zero is indistinguishable from 'the accumulator was swept
        before we looked', and a fabricated zero would read as total system
        failure a year later when it is compared against."""
        coord = _coord({"2026-08": 0.0})
        SEMCoordinator._record_completed_month(coord, datetime.date(2026, 9, 3))
        assert coord._pv_analyzer.get_monthly_history() == []

    def test_january_looks_back_into_the_previous_year(self):
        coord = _coord({"2025-12": 150.0})
        SEMCoordinator._record_completed_month(coord, datetime.date(2026, 1, 2))
        history = coord._pv_analyzer.get_monthly_history()
        assert (history[0]["year"], history[0]["month"]) == (2025, 12)

    def test_the_record_is_persisted_immediately(self):
        """A month recorded but not written is a month lost to the next
        restart — the same failure, one layer up."""
        storage = MagicMock()
        coord = _coord({"2026-08": 420.0}, storage=storage)
        SEMCoordinator._record_completed_month(coord, datetime.date(2026, 9, 3))
        storage.set_pv_performance_state.assert_called_once()
        saved = storage.set_pv_performance_state.call_args.args[0]
        assert saved["monthly_history"][0]["year"] == 2026

    def test_no_storage_is_survivable(self):
        coord = _coord({"2026-08": 420.0}, storage=None)
        SEMCoordinator._record_completed_month(coord, datetime.date(2026, 9, 3))
        assert len(coord._pv_analyzer.get_monthly_history()) == 1


class TestTheCycleActuallyCallsIt:
    """#873's lesson applied to #867's own fix: a recorder that exists and
    is never called is exactly the bug being fixed. Wiring it is not the
    same as proving the wiring runs."""

    @pytest.mark.asyncio
    async def test_a_real_cycle_reaches_the_recorder(self):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coordinator_module,
        )

        from .test_873_cycle_executes import WIRED, _sensors, run_cycle

        seen = []
        original = coordinator_module.SEMCoordinator._record_completed_month

        def spy(self, today):
            seen.append(today)
            return original(self, today)

        coordinator_module.SEMCoordinator._record_completed_month = spy
        try:
            await run_cycle(WIRED, _sensors(6000, 2000, 1500, 77))
        finally:
            coordinator_module.SEMCoordinator._record_completed_month = original

        assert seen, (
            "the main cycle never called _record_completed_month — the "
            "recorder would be as dead as record_monthly was"
        )
