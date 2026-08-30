"""#861 item 2 — the backfill notification's content, with real values.

The substring check in test_21_usability proved the notification EXISTS;
nothing proved what it says. Pulling on this thread found a naming lie:
the report key was `days_of_history` while carrying HOURLY statistic rows
(the message said "hour(s)" and was right by accident). The key is now
`hours_of_history`, and these tests pin the content against a real report.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.night_backfill import (
    nights_from_statistics,
)


def _hourly(start, hours, step_kwh):
    t0 = start
    return {t0 + timedelta(hours=i): 100.0 + i * step_kwh for i in range(hours)}


class TestTheReportSpeaksHours:
    def test_hours_key_counts_hourly_rows(self):
        """72 hourly rows are 72 HOURS (3 days) — the report must not call
        them days. Pinned at the source (`run_backfill` builds the report
        from `len(discharge)` of the hourly series)."""
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            night_backfill as nb,
        )
        src = inspect.getsource(nb.run_backfill)
        assert '"hours_of_history"' in src
        assert '"days_of_history"' not in src

    def test_the_notification_text_agrees_with_the_key(self):
        """__init__'s notification interpolates the hours key next to the
        word 'hour(s)' — the pair must never drift apart again."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "__init__.py").read_text()
        i = src.index("sem_backfill_battery_nights")
        block = src[i - 1200:i]
        assert "hours_of_history" in block
        assert "hour(s) of history" in block
        assert "days_of_history" not in block


class TestNightsFromStatisticsRealValues:
    """The recovery math on a real-shaped hourly counter, not a mock."""

    def test_recovers_a_night_from_a_monotone_counter(self):
        start = datetime(2026, 8, 25, 0, 0)  # naive, matching _window
        series = _hourly(start, 48, step_kwh=0.2)  # 0.2 kWh discharge/hour
        nights = nights_from_statistics(
            series, night_start_hour=22, night_end_hour=6,
        )
        assert nights, "two days of hourly rows must yield at least one night"
        n = nights[0]
        # 8 night hours x 0.2 kWh of counter delta belong to the night —
        # the drain is exact, the record trainable, keyed by its evening.
        assert n["date"] == "2026-08-25"
        assert n["drain_kwh"] == 1.6
        assert n["trainable"] is True
        assert n["source"] == "backfill"
