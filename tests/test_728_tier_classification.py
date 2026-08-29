"""Distinct-value tier classification for fixed Time-of-Use plans (#728).

@Azlinon ran the weekend test he predicted would fail, and it did — three
ways. His plan: weekday tiers off-peak 0.10 / mid 0.15 / peak 0.30, flat
0.10 all weekend (a 55-hour steady stretch). The replay of his sensor
shape through the shipped rolling-percentile classifier reproduced:

1. Fri 13:00 — Saturday's flat day publishes, the window floods with
   0.10s, and the ordinary 0.15 mid rate outranks into EXPENSIVE.
2. Fri 19:00 — the genuine 0.30 peak reads NORMAL: all four percentile
   breakpoints land inside the flooded 0.10 tier, spread collapses to
   0.0000, and the flat-day guard declares a day with a 3× peak "flat".
3. The weekend — 55 flat hours converge to all-NORMAL, and past hours
   re-classify at read time (Friday's honest very_expensive rewritten
   to normal on Saturday).

A rolling window is the wrong instrument for a fixed-tier plan. Cheap /
normal / expensive are STRUCTURAL there — the plan's 2–5 named rates —
not relative to the last 24 h. So: when the curve is a small set of
repeating discrete values (detected, not configured), classify by
distinct value tier, stable across any window and any publish event.
The percentile window stays for genuinely continuous curves, and
past-hour levels become append-only so the displayed history is never
rewritten in either mode.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
)
from homeassistant.util import dt as dt_util


def _make_provider() -> DynamicTariffProvider:
    hass = MagicMock()
    return DynamicTariffProvider(
        hass,
        price_entity="sensor.fake_tariff",
        classification_mode="percentile",
    )


def _points(values, start=None, interval_h=1.0):
    start = start or dt_util.now().replace(minute=0, second=0, microsecond=0)
    return [
        PricePoint(
            timestamp=start + timedelta(hours=interval_h * i),
            price=v,
            currency="USD",
            level=PriceLevel.NORMAL,
        )
        for i, v in enumerate(values)
    ]


def _seed(provider, values, start=None):
    provider._prices_cache = _points(values, start=start)


# Azlinon's shape, as replayed on the issue.
OFF, MID, PEAK = 0.10, 0.15, 0.30
WEEKDAY = [
    OFF if (h < 7 or h >= 21) else PEAK if 16 <= h < 21 else MID
    for h in range(24)
]
FLAT_DAY = [OFF] * 24


class TestTierDetection:
    """Discrete plans are detected, not configured."""

    def test_a_three_tier_day_classifies_by_tiers(self):
        p = _make_provider()
        _seed(p, WEEKDAY)

        p._classify_price(MID)

        assert p._last_classifier_path.startswith("tou_tiers")

    def test_a_continuous_day_keeps_the_percentile_window(self):
        p = _make_provider()
        _seed(p, [v / 100 for v in range(10, 81, 3)])  # 24 distinct values

        p._classify_price(0.45)

        assert p._last_classifier_path.startswith("percentile_active")

    def test_a_mostly_distinct_day_with_a_few_repeats_stays_percentile(self):
        """RienduPre's Tibber-NL day repeats a handful of values (0.18 ×3,
        0.22 ×3) but is a continuous market — 17 distinct prices in 24
        hours is nobody's tier plan."""
        p = _make_provider()
        _seed(p, [
            0.18, 0.16, 0.15, 0.14, 0.13, 0.14, 0.18, 0.24,
            0.30, 0.32, 0.28, 0.25, 0.22, 0.20, 0.22, 0.26,
            0.32, 0.42, 0.45, 0.40, 0.34, 0.28, 0.22, 0.18,
        ])

        p._classify_price(0.30)

        assert p._last_classifier_path.startswith("percentile_active")


class TestTheReplayDefects:
    """The three defects from the posted Fri→Mon replay, now fixed."""

    def test_fri_13_publish_flood_leaves_the_mid_rate_normal(self):
        """Saturday's flat day floods the window with 0.10s; the ordinary
        0.15 mid rate must NOT outrank into expensive."""
        p = _make_provider()
        start = dt_util.now().replace(minute=0, second=0, microsecond=0)
        _seed(p, WEEKDAY + FLAT_DAY, start=start - timedelta(hours=13))

        assert p._classify_price(MID) is PriceLevel.NORMAL

    def test_fri_19_the_real_peak_is_expensive_not_flat(self):
        """At Fri 19:00 the rolling window is [0.10 ×23, 0.30 ×2] — the
        old flat-day guard collapsed it to NORMAL while the actual 3×
        peak was live."""
        p = _make_provider()
        start = dt_util.now().replace(minute=0, second=0, microsecond=0)
        _seed(p, WEEKDAY + FLAT_DAY, start=start - timedelta(hours=19))

        assert p._classify_price(PEAK) is PriceLevel.EXPENSIVE

    def test_the_flat_weekend_reads_cheap_not_normal(self):
        """55 hours at the plan's cheapest rate ARE cheap hours. The
        weekday tiers were seen on Friday; the tier ledger remembers
        them across the cache rolling over to the flat weekend."""
        p = _make_provider()
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        # Friday's parse warms the ledger with all three tiers…
        _seed(p, WEEKDAY + FLAT_DAY, start=now - timedelta(hours=20))
        p._classify_price(OFF)
        # …then the cache rolls over to Sat+Sun, flat 0.10 only.
        _seed(p, FLAT_DAY + FLAT_DAY, start=now - timedelta(hours=6))
        p._tier_memo_for = None  # cache swapped, as _read_prices_list does

        assert p._classify_price(OFF) is PriceLevel.CHEAP

    def test_tiers_unseen_for_a_week_age_out(self):
        """A plan change must not haunt the ledger: tiers last carried
        8 days ago no longer count, and a genuinely flat cache falls
        back to the percentile path's neutral NORMAL."""
        p = _make_provider()
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        _seed(p, WEEKDAY, start=now - timedelta(days=8))
        p._classify_price(OFF)
        _seed(p, FLAT_DAY + FLAT_DAY, start=now - timedelta(hours=6))
        p._tier_memo_for = None

        assert p._classify_price(OFF) is PriceLevel.NORMAL
        assert not p._last_classifier_path.startswith("tou_tiers")


class TestTierMapping:
    """The plan's tier count maps onto the level scale center-out."""

    def test_three_tiers_map_cheap_normal_expensive(self):
        p = _make_provider()
        _seed(p, WEEKDAY)

        assert p._classify_price(OFF) is PriceLevel.CHEAP
        assert p._classify_price(MID) is PriceLevel.NORMAL
        assert p._classify_price(PEAK) is PriceLevel.EXPENSIVE

    def test_two_tiers_map_cheap_expensive(self):
        p = _make_provider()
        _seed(p, [OFF if h < 12 else PEAK for h in range(24)])

        assert p._classify_price(OFF) is PriceLevel.CHEAP
        assert p._classify_price(PEAK) is PriceLevel.EXPENSIVE

    def test_four_tiers_extend_the_cheap_end(self):
        """Super-off-peak / off-peak / mid / peak — the common 4-tier
        shape grows a deeper cheap end, not a second peak."""
        p = _make_provider()
        _seed(p, [0.05] * 6 + [0.10] * 6 + [0.15] * 7 + [0.30] * 5)

        assert p._classify_price(0.05) is PriceLevel.VERY_CHEAP
        assert p._classify_price(0.10) is PriceLevel.CHEAP
        assert p._classify_price(0.15) is PriceLevel.NORMAL
        assert p._classify_price(0.30) is PriceLevel.EXPENSIVE

    def test_five_tiers_use_the_full_scale(self):
        p = _make_provider()
        _seed(p, [0.05] * 5 + [0.10] * 5 + [0.15] * 6
                 + [0.30] * 4 + [0.60] * 4)

        assert p._classify_price(0.05) is PriceLevel.VERY_CHEAP
        assert p._classify_price(0.60) is PriceLevel.VERY_EXPENSIVE

    def test_negative_prices_short_circuit_before_tiers(self):
        p = _make_provider()
        _seed(p, WEEKDAY)

        assert p._classify_price(-0.02) is PriceLevel.NEGATIVE

    def test_six_or_more_distinct_values_are_not_a_tier_plan(self):
        p = _make_provider()
        _seed(p, [0.05] * 4 + [0.10] * 4 + [0.15] * 4
                 + [0.20] * 4 + [0.30] * 4 + [0.60] * 4)

        p._classify_price(0.15)

        assert not p._last_classifier_path.startswith("tou_tiers")


class TestAppendOnlyPast:
    """A level, once displayed for a past hour, is never rewritten."""

    def test_a_past_slot_keeps_its_first_displayed_level(self):
        p = _make_provider()
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        # A continuous morning: the 0.45 peak two hours ago read
        # very_expensive against its window.
        morning = _points(
            [0.10, 0.12, 0.15, 0.20, 0.45, 0.30],
            start=now - timedelta(hours=5),
        )
        p._prices_cache = morning
        p._apply_levels(morning)
        peak_slot = morning[4]
        assert peak_slot.level is PriceLevel.VERY_EXPENSIVE

        # The evening publishes a wall of 0.60s — under the old model
        # the morning's 0.45 would re-rank to normal at read time.
        evening = morning + _points(
            [0.60] * 12, start=now + timedelta(hours=1),
        )
        p._prices_cache = evening
        p._apply_levels(evening)

        assert evening[4].level is PriceLevel.VERY_EXPENSIVE

    def test_future_slots_reclassify_freely(self):
        p = _make_provider()
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        pts = _points(
            [0.10, 0.12, 0.15, 0.20, 0.45, 0.30],
            start=now + timedelta(hours=1),
        )
        p._prices_cache = pts
        p._apply_levels(pts)
        assert pts[4].level is PriceLevel.VERY_EXPENSIVE

        wall = pts + _points([0.60] * 12, start=now + timedelta(hours=7))
        p._prices_cache = wall
        p._apply_levels(wall)

        assert wall[4].level is not PriceLevel.VERY_EXPENSIVE

    def test_the_level_history_is_pruned(self):
        p = _make_provider()
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        old = _points([0.10] * 24, start=now - timedelta(days=4))
        p._prices_cache = old
        p._apply_levels(old)
        fresh = _points([0.10] * 6, start=now - timedelta(hours=3))
        p._prices_cache = fresh
        p._apply_levels(fresh)

        cutoff = now - timedelta(hours=48)
        assert all(ts >= cutoff for ts in p._level_history)
