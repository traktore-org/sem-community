"""#729 — a plan window's ``end`` is its closing boundary, not its last slot.

Reported by @Azlinon in #686: a cheap window covering the hourly slots 00:00
through 05:00 — cheap power right up until 06:00 — rendered as "cheap hours
open until 05:00", so the reader loses the final hour of it.

The asymmetry was the bug: ``start`` is genuinely when the window opens, but
``end`` was the *start timestamp of the last slot*. One endpoint was a
boundary, the other a slot label. These tests pin ``end`` as a boundary, and
pin that the boundary is derived from the curve's own cadence rather than
assumed hourly, because 15-minute price curves exist.
"""
from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.today_plan import (
    compose_today_plan,
    _consecutive_blocks,
    KIND_CHEAP_START,
    KIND_EXPENSIVE_START,
)


NOW = datetime(2026, 5, 28, 22, 0, 0)


def _prices(now: datetime, levels: list[tuple[float, str, float]]) -> list[dict]:
    """Build upcoming_prices from (hour_offset, level, price) tuples."""
    return [
        {"t": (now + timedelta(hours=h)).isoformat(), "level": lvl, "price": p}
        for h, lvl, p in levels
    ]


def _end_of(plan: list[dict], kind: str) -> str:
    rows = [r for r in plan if r["kind"] == kind]
    assert len(rows) == 1, f"expected exactly one {kind} row, got {len(rows)}"
    return rows[0]["values"]["end"]


class TestReportedWindowReadsOneHourShort:
    """The exact shape from #686 — six cheap hours, 00:00 through 05:00."""

    # NOW is 22:00, so +2h .. +7h are the slots 00:00 .. 05:00.
    CURVE = [
        (1, "normal", 0.20),
        (2, "cheap", 0.10), (3, "cheap", 0.10), (4, "cheap", 0.10),
        (5, "cheap", 0.10), (6, "cheap", 0.10), (7, "cheap", 0.10),
        (8, "normal", 0.20),
    ]

    def test_the_window_closes_at_06_00_not_05_00(self):
        plan = compose_today_plan(now=NOW, upcoming_prices=_prices(NOW, self.CURVE))
        assert _end_of(plan, KIND_CHEAP_START) == "06:00"

    def test_the_opening_endpoint_is_untouched(self):
        # ``start`` was always right; the fix must not shift it.
        plan = compose_today_plan(now=NOW, upcoming_prices=_prices(NOW, self.CURVE))
        rows = [r for r in plan if r["kind"] == KIND_CHEAP_START]
        assert datetime.fromisoformat(rows[0]["when"]) == NOW + timedelta(hours=2)


class TestExpensiveWindowsToo:
    def test_an_expensive_block_closes_on_its_boundary(self):
        curve = [
            (1, "normal", 0.20),
            (2, "expensive", 0.40), (3, "very_expensive", 0.50),
            (4, "normal", 0.20),
        ]
        plan = compose_today_plan(now=NOW, upcoming_prices=_prices(NOW, curve))
        # Peak runs 00:00 and 01:00 → it is over at 02:00.
        assert _end_of(plan, KIND_EXPENSIVE_START) == "02:00"


class TestQuarterHourCurves:
    """Slot length comes from the curve, not from an assumption."""

    def test_a_15_minute_curve_closes_a_quarter_hour_past_the_last_slot(self):
        curve = [
            (0.00, "normal", 0.20),
            (0.25, "cheap", 0.10), (0.50, "cheap", 0.10), (0.75, "cheap", 0.10),
            (1.00, "normal", 0.20),
        ]
        plan = compose_today_plan(now=NOW, upcoming_prices=_prices(NOW, curve))
        # Cheap slots 22:15, 22:30, 22:45 → cheap until 23:00.
        assert _end_of(plan, KIND_CHEAP_START) == "23:00"


class TestGapsDoNotStretchTheBoundary:
    def test_a_missing_slot_does_not_widen_the_others(self):
        # Hourly curve with the +4h slot absent. The cadence is still one
        # hour; the gap must not be mistaken for a two-hour slot.
        curve = [
            (1, "cheap", 0.10), (2, "cheap", 0.10), (3, "cheap", 0.10),
            (5, "normal", 0.20), (6, "normal", 0.20),
        ]
        plan = compose_today_plan(now=NOW, upcoming_prices=_prices(NOW, curve))
        assert _end_of(plan, KIND_CHEAP_START) == "02:00"


class TestDegenerateCurves:
    def test_a_single_slot_falls_back_to_one_hour(self):
        # Nothing to measure a cadence against — assume the common case
        # rather than emitting a zero-length window.
        points = [{"t": NOW, "level": "cheap", "price": 0.10}]
        blocks = _consecutive_blocks(points, ("cheap",), min_block_len=1)
        assert len(blocks) == 1
        assert blocks[0]["end"] == NOW + timedelta(hours=1)

    def test_repeated_timestamps_do_not_collapse_the_window(self):
        # A duplicated timestamp yields a zero delta; it must not be taken
        # as the slot length or every window would close where it opened.
        points = [
            {"t": NOW, "level": "cheap", "price": 0.10},
            {"t": NOW, "level": "cheap", "price": 0.10},
            {"t": NOW + timedelta(hours=1), "level": "cheap", "price": 0.10},
        ]
        blocks = _consecutive_blocks(points, ("cheap",), min_block_len=1)
        assert blocks[0]["end"] == NOW + timedelta(hours=2)

    def test_an_empty_curve_still_returns_no_blocks(self):
        assert _consecutive_blocks([], ("cheap",), min_block_len=1) == []
