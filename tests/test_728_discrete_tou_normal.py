"""Percentile classification on discrete Time-of-Use tariffs (#728).

Reported by @Azlinon against Consumers Energy "Nighttime Savers": a rate
plan with exactly three prices per day was classified as *only* cheap and
expensive — ``NORMAL`` never appeared, so the middle tier (half the day)
was treated as expensive power.

The percentile path was written for continuous curves (Nordpool / Tibber /
Amber), where every quantile lands on a distinct value. A Time-of-Use plan
has a handful of repeated values, so a quantile lands *on* a tier — and
with an inclusive ``price >= p75`` the whole tier falls through to
EXPENSIVE. Concretely: whenever the top tier covers less than ~25% of the
day, p75 ties onto the middle tier and swallows it.

These tests pin the ToU shape. The continuous-curve behaviour that #359
established is asserted here too, so a fix for one can't silently regress
the other.
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


def _seed(provider: DynamicTariffProvider, values: list[float]) -> None:
    """Load one day of hourly prices into the provider's cache."""
    today = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    provider._prices_cache = [
        PricePoint(
            timestamp=today + timedelta(hours=i),
            price=v,
            currency="USD",
            level=PriceLevel.NORMAL,
        )
        for i, v in enumerate(values)
    ]


# Consumers Energy "Nighttime Savers", summer weekday — the reporter's own
# plan. Off-peak 0.187 (7h), mid-peak 0.209 (12h), on-peak 0.245 (5h).
OFF_PEAK, MID_PEAK, ON_PEAK = 0.187, 0.209, 0.245
NIGHTTIME_SAVERS = [
    OFF_PEAK if (h < 6 or h >= 23)
    else MID_PEAK if (6 <= h < 14 or 19 <= h < 23)
    else ON_PEAK
    for h in range(24)
]


class TestThreeTierTimeOfUse:
    def test_the_middle_tier_is_normal(self):
        """The reporter's mid-peak rate is the ordinary price of his day."""
        p = _make_provider()
        _seed(p, NIGHTTIME_SAVERS)

        assert p._classify_price(MID_PEAK) is PriceLevel.NORMAL

    def test_the_cheapest_tier_is_still_cheap(self):
        p = _make_provider()
        _seed(p, NIGHTTIME_SAVERS)

        assert p._classify_price(OFF_PEAK) in (
            PriceLevel.VERY_CHEAP, PriceLevel.CHEAP,
        )

    def test_the_priciest_tier_is_still_expensive(self):
        p = _make_provider()
        _seed(p, NIGHTTIME_SAVERS)

        assert p._classify_price(ON_PEAK) in (
            PriceLevel.VERY_EXPENSIVE, PriceLevel.EXPENSIVE,
        )

    def test_all_three_levels_appear_across_the_day(self):
        """A three-price day should use three buckets, not two."""
        p = _make_provider()
        _seed(p, NIGHTTIME_SAVERS)

        levels = {p._classify_price(v) for v in NIGHTTIME_SAVERS}
        cheap = levels & {PriceLevel.VERY_CHEAP, PriceLevel.CHEAP}
        pricey = levels & {PriceLevel.VERY_EXPENSIVE, PriceLevel.EXPENSIVE}

        assert cheap, f"no cheap bucket used: {levels}"
        assert PriceLevel.NORMAL in levels, f"NORMAL unreachable: {levels}"
        assert pricey, f"no expensive bucket used: {levels}"


class TestSkewedTimeOfUse:
    """The tie can land on either side — pin both."""

    def test_a_tiny_on_peak_block_does_not_swallow_the_middle_tier(self):
        """Top tier well under 25% of the day: p75 ties onto mid-peak."""
        p = _make_provider()
        # 2h on-peak only — the case that provoked the report.
        _seed(p, [
            OFF_PEAK if h < 8 else ON_PEAK if 17 <= h < 19 else MID_PEAK
            for h in range(24)
        ])

        assert p._classify_price(MID_PEAK) is PriceLevel.NORMAL

    def test_a_tiny_off_peak_block_does_not_swallow_the_middle_tier(self):
        """Mirror image: bottom tier under 25%, p25 ties onto mid-peak."""
        p = _make_provider()
        _seed(p, [
            OFF_PEAK if h < 2 else ON_PEAK if 17 <= h < 23 else MID_PEAK
            for h in range(24)
        ])

        assert p._classify_price(MID_PEAK) is PriceLevel.NORMAL


class TestContinuousCurveUnchanged:
    """#359's Nordpool/Tibber behaviour must survive the ToU fix."""

    def test_bottom_of_a_continuous_day_is_very_cheap(self):
        p = _make_provider()
        _seed(p, [v / 100 for v in range(10, 81, 3)])  # 24 distinct values

        assert p._classify_price(0.10) is PriceLevel.VERY_CHEAP

    def test_middle_of_a_continuous_day_is_normal(self):
        p = _make_provider()
        _seed(p, [v / 100 for v in range(10, 81, 3)])

        assert p._classify_price(0.45) is PriceLevel.NORMAL

    def test_top_of_a_continuous_day_is_very_expensive(self):
        p = _make_provider()
        _seed(p, [v / 100 for v in range(10, 81, 3)])

        assert p._classify_price(0.79) is PriceLevel.VERY_EXPENSIVE


class TestLonePricesKeepTheirBucket:
    """The guarantee that makes the #728 fix safe to ship.

    A price only ONE hour of the window carries must land in exactly
    the bucket it always did. Only tied tiers — several hours sharing
    one number — may move, and that is the entire scope of the bug.

    The curve below is RienduPre's synthetic Tibber-NL day from #359,
    whose p75 lands squarely on EUR 0.30 — a price his day carries for
    a single hour, and the exact value he reported as mis-classified.
    A #728 fix that demotes it to NORMAL has re-opened #359.
    """

    TIBBER_NL = [
        0.18, 0.16, 0.15, 0.14, 0.13, 0.14, 0.18, 0.24,
        0.30, 0.32, 0.28, 0.25, 0.22, 0.20, 0.22, 0.26,
        0.32, 0.42, 0.45, 0.40, 0.34, 0.28, 0.22, 0.18,
    ]

    def test_a_lone_price_sitting_on_p75_is_still_expensive(self):
        p = _make_provider()
        _seed(p, self.TIBBER_NL)

        assert p._classify_price(0.30) is PriceLevel.EXPENSIVE

    def test_the_rest_of_that_day_keeps_its_buckets_too(self):
        p = _make_provider()
        _seed(p, self.TIBBER_NL)

        assert p._classify_price(0.13) is PriceLevel.VERY_CHEAP
        assert p._classify_price(0.15) is PriceLevel.CHEAP
        assert p._classify_price(0.32) is PriceLevel.EXPENSIVE
        assert p._classify_price(0.45) is PriceLevel.VERY_EXPENSIVE


class TestTwoTierTimeOfUse:
    """A genuine two-price plan has no middle — it must NOT invent one."""

    def test_a_two_tier_day_uses_only_cheap_and_expensive(self):
        p = _make_provider()
        _seed(p, [OFF_PEAK if h < 12 else ON_PEAK for h in range(24)])

        assert p._classify_price(OFF_PEAK) in (
            PriceLevel.VERY_CHEAP, PriceLevel.CHEAP,
        )
        assert p._classify_price(ON_PEAK) in (
            PriceLevel.VERY_EXPENSIVE, PriceLevel.EXPENSIVE,
        )
