"""#778 — a JIT sell block must not cancel itself in its final minutes.

Found by the compressed evening simulation on .175, 30.08.2026. With the
floor pulled to 18:00 the block was live and selling at 5009 W, and then:

    17:39:00  sell=selling  until=18:00  rate=5009.0
    17:45:21  sell=None     until=       rate=None      ← and None onward

The sell stopped at ``night_start − 15 min`` — the exact moment the
"just-in-time" design is named for.

``forecast_sell_blocks`` anchors the block to ``now``::

    start   = max(now, night_start - hours)
    span_h  = night_start - start
    if span_h * 60 < MIN_BLOCK_MIN: return []

so the window SHRINKS as the evening advances, and once fewer than
MIN_BLOCK_MIN minutes remain the function returns no block at all. The plan
is recomputed periodically, so at the next recompute the plan simply loses
its ``forecast_sell`` entry, ``forecast_sell_gate`` closes, and the verdict
flips to STOP_FORCE_DISCHARGE.

MIN_BLOCK_MIN exists to stop a 4-minute block being PLANNED ("contactor
churn, not a plan"). Applied to the REMAINING span it also cancels a block
that is already running — a different question with the same number.

The block is what its own docstring says it is: ``[night_start − duration,
night_start)``. That interval does not depend on when you ask. Anchoring it
to ``night_start`` makes it stable across recomputes, which also keeps the
gate's derived rate (``kwh / hours``) constant instead of tapering.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.forecast_sell import (
    MIN_BLOCK_MIN,
    forecast_sell_blocks,
)

NIGHT = datetime(2026, 8, 30, 18, 0)
SPENDABLE = 4.64      # what .175 reported
RATE_W = 5000.0


def _blocks(now):
    return forecast_sell_blocks(now, NIGHT, SPENDABLE, RATE_W)


class TestTheBlockSurvivesToNightStart:
    def test_still_open_inside_the_final_fifteen_minutes(self):
        """The .175 regression, to the minute."""
        for mins_left in (15, 14, 10, 5, 1):
            now = NIGHT - timedelta(minutes=mins_left)
            got = _blocks(now)
            assert got, (
                f"{mins_left} min before the night the block vanished — "
                "the sell stops exactly when 'just in time' means to act"
            )
            b = got[0]
            assert b["start"] <= now < b["end"], (
                "the returned block must contain the moment it was asked about"
            )

    def test_the_block_always_ends_at_night_start(self):
        for mins_left in (60, 30, 15, 5, 1):
            assert _blocks(NIGHT - timedelta(minutes=mins_left))[0]["end"] == NIGHT

    def test_the_window_is_stable_across_recomputes(self):
        """The gate derives the rate as kwh/hours from the STORED block. A
        window that moves with ``now`` re-derives a different rate every
        recompute; an anchored one holds the rate it planned."""
        early = _blocks(NIGHT - timedelta(minutes=50))[0]
        late = _blocks(NIGHT - timedelta(minutes=5))[0]
        assert early["start"] == late["start"]
        assert early["end"] == late["end"]
        assert early["kwh"] == late["kwh"], (
            "a shrinking kwh tapers the sell rate toward zero as the night "
            "approaches — the opposite of a just-in-time block"
        )

    def test_the_planned_block_is_never_shorter_than_the_minimum(self):
        """MIN_BLOCK_MIN still governs what may be PLANNED."""
        tiny = forecast_sell_blocks(
            NIGHT - timedelta(hours=2), NIGHT, 0.25, 20000.0)
        assert tiny, "a small budget still earns a block"
        span_min = (tiny[0]["end"] - tiny[0]["start"]).total_seconds() / 60.0
        assert span_min >= MIN_BLOCK_MIN


class TestTheOldRefusalsStillHold:
    def test_nothing_once_the_night_has_begun(self):
        assert _blocks(NIGHT) == []
        assert _blocks(NIGHT + timedelta(minutes=1)) == []

    def test_nothing_without_a_budget(self):
        assert forecast_sell_blocks(
            NIGHT - timedelta(hours=1), NIGHT, 0.0, RATE_W) == []

    def test_nothing_without_a_rate(self):
        assert forecast_sell_blocks(
            NIGHT - timedelta(hours=1), NIGHT, SPENDABLE, 0.0) == []

    def test_nothing_without_a_night_boundary(self):
        assert forecast_sell_blocks(
            NIGHT - timedelta(hours=1), None, SPENDABLE, RATE_W) == []
