"""Tests for percentile-based tariff classification (#359).

The static 0.15 / 0.35 CHF cutoffs mis-bucket prices on dynamic
tariffs whose daily range is 0.05–0.80 €/kWh (Tibber / Octopus /
Amber / Nordpool). Percentile mode buckets relative to today's
distribution.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
)
from homeassistant.util import dt as dt_util


def _make_provider(mode: str = "percentile") -> DynamicTariffProvider:
    hass = MagicMock()
    return DynamicTariffProvider(
        hass,
        price_entity="sensor.fake_tariff",
        classification_mode=mode,
    )


def _today_prices(values: list[float]) -> list[PricePoint]:
    today = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        PricePoint(
            timestamp=today + timedelta(hours=i),
            price=v,
            currency="EUR",
            level=PriceLevel.NORMAL,
        )
        for i, v in enumerate(values)
    ]


class TestClassificationModeSelect:
    def test_default_is_percentile(self):
        p = _make_provider()
        assert p.classification_mode == "percentile"

    def test_explicit_static(self):
        p = _make_provider("static")
        assert p.classification_mode == "static"

    def test_invalid_falls_back_to_percentile(self):
        # Anything unknown defaults to the safer percentile path.
        hass = MagicMock()
        p = DynamicTariffProvider(
            hass, classification_mode="garbage",
        )
        assert p.classification_mode == "percentile"


class TestPercentileBucketing:
    def test_bottom_10_pct_is_very_cheap(self):
        # 24h Tibber-style distribution from €0.10 to €0.80.
        prices = list(range(10, 81, 3))  # 24 values: 10, 13, ..., 79
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([v / 100 for v in prices])

        # 0.10 is below the 10th percentile of the distribution.
        assert p._classify_price(0.10) is PriceLevel.VERY_CHEAP

    def test_25_to_75_is_normal(self):
        prices = list(range(10, 81, 3))
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([v / 100 for v in prices])

        # Middle of the distribution.
        assert p._classify_price(0.45) is PriceLevel.NORMAL

    def test_top_25_pct_is_expensive(self):
        prices = list(range(10, 81, 3))
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([v / 100 for v in prices])

        # 0.70 is in the top quartile but below p90.
        assert p._classify_price(0.70) is PriceLevel.EXPENSIVE

    def test_top_10_pct_is_very_expensive(self):
        prices = list(range(10, 81, 3))
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([v / 100 for v in prices])

        # 0.79 — top of the distribution.
        assert p._classify_price(0.79) is PriceLevel.VERY_EXPENSIVE

    def test_negative_always_negative_regardless_of_mode(self):
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.10, 0.20, 0.30, 0.40])

        # Negative price (spot-market overproduction).
        assert p._classify_price(-0.05) is PriceLevel.NEGATIVE

    def test_cold_start_returns_normal(self):
        """#359 follow-up: before _prices_cache is populated, percentile
        mode must return NORMAL — not fall through to the static
        thresholds, which are CHF-calibrated (0.15 / 0.35) and silently
        mis-classify any other currency. RienduPre's Tibber NL install
        hit this and reported €0.30 as ``normal`` for hours before the
        Tibber sensor populated."""
        p = _make_provider("percentile")
        # No cache yet.
        assert p._prices_cache == []
        # NORMAL is the safe default until we have data.
        assert p._classify_price(0.10) is PriceLevel.NORMAL
        assert p._classify_price(0.50) is PriceLevel.NORMAL
        assert p._classify_price(0.25) is PriceLevel.NORMAL
        # Negative prices remain NEGATIVE even pre-data.
        assert p._classify_price(-0.05) is PriceLevel.NEGATIVE

    def test_insufficient_data_returns_normal(self):
        """#359 follow-up: 3 prices isn't enough for percentiles — return
        NORMAL, not the CHF-calibrated static fallback."""
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.10, 0.20, 0.30])

        assert p._classify_price(0.10) is PriceLevel.NORMAL
        assert p._classify_price(0.50) is PriceLevel.NORMAL

    def test_flat_distribution_returns_normal(self):
        """#359 follow-up: a flat day collapses p90-p10 < 1 ct/kWh; the
        degenerate guard returns None. In percentile mode that now
        means NORMAL, not the CHF-calibrated static fallback."""
        p = _make_provider("percentile")
        # 24-point flat day at 0.20 €/kWh.
        p._prices_cache = _today_prices([0.20] * 24)

        assert p._classify_price(0.20) is PriceLevel.NORMAL
        # Even values that would static-classify differently come back
        # as NORMAL because we have no real distribution to compare to.
        assert p._classify_price(0.05) is PriceLevel.NORMAL
        assert p._classify_price(0.40) is PriceLevel.NORMAL

    def test_near_flat_distribution_returns_normal(self):
        """Spread under the 1 ct threshold also returns NORMAL."""
        p = _make_provider("percentile")
        prices = [0.20 + i * 0.0001 for i in range(24)]  # ~0.20 → ~0.2023
        p._prices_cache = _today_prices(prices)

        assert p._classify_price(0.20) is PriceLevel.NORMAL
        assert p._classify_price(0.40) is PriceLevel.NORMAL


class TestStaticMode:
    """Static mode (opt-out) ignores percentiles even when cache is
    populated — useful for users with flat tariffs."""

    def test_static_uses_fixed_cutoffs(self):
        p = _make_provider("static")
        p._prices_cache = _today_prices(
            [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
        )

        # Should use the fixed 0.15 / 0.35 cutoffs regardless of
        # the populated cache.
        assert p._classify_price(0.10) is PriceLevel.CHEAP   # < 0.15
        assert p._classify_price(0.07) is PriceLevel.VERY_CHEAP  # < 0.075
        assert p._classify_price(0.25) is PriceLevel.NORMAL  # 0.15..0.35
        assert p._classify_price(0.40) is PriceLevel.EXPENSIVE  # > 0.35
        assert p._classify_price(0.55) is PriceLevel.VERY_EXPENSIVE  # > 0.525


class TestPercentileCaching:
    def test_breaks_cached_per_day(self):
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.10, 0.20, 0.30, 0.40, 0.50])

        # First call populates the cache.
        breaks1 = p._get_percentile_breaks()
        assert breaks1 is not None
        # Second call returns the same dict instance from cache.
        breaks2 = p._get_percentile_breaks()
        assert breaks2 is breaks1

    def test_breaks_invalidated_on_cache_change(self):
        """When ``_prices_cache`` is replaced by ``_read_prices_list``
        the explicit invalidation in that path clears the cached
        breakpoints."""
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.10, 0.20, 0.30, 0.40, 0.50])

        breaks1 = p._get_percentile_breaks()
        # Simulate ``_read_prices_list`` updating the cache.
        p._prices_cache = _today_prices([0.50, 0.60, 0.70, 0.80, 0.90])
        p._percentile_breaks = None
        p._percentile_breaks_for = None

        breaks2 = p._get_percentile_breaks()
        assert breaks2 is not None
        assert breaks2["p10"] != breaks1["p10"]


class TestTimezoneSkew359Followup:
    """#359 follow-up — RienduPre reported €0.30 still showing as ``normal``
    after the percentile fix shipped in beta.3. Root cause was the date
    filter doing ``p.timestamp.date()`` directly: providers like Nordpool
    emit UTC timestamps, so on a non-UTC HA install the array filtered
    by 'today' could come up empty or partial → percentiles return None →
    silent fall-through to static thresholds → 0.30 = NORMAL.
    """

    def test_utc_timestamps_count_as_local_today(self):
        """Provider emits UTC, HA tz = Europe/Amsterdam (+02:00). A
        full 24h of prices tagged in UTC must still be recognised as
        'today' once converted to local."""
        from datetime import timezone
        try:
            import zoneinfo
            ams = zoneinfo.ZoneInfo("Europe/Amsterdam")
        except Exception:
            pytest.skip("zoneinfo unavailable")

        original_tz = dt_util.get_default_time_zone()
        dt_util.set_default_time_zone(ams)
        try:
            # Local "today" — anchor at noon local so the day boundary
            # isn't ambiguous regardless of when the test runs.
            local_today_noon = dt_util.now().replace(
                hour=12, minute=0, second=0, microsecond=0
            )
            # Build 24 hourly prices in UTC for the LOCAL today, spanning
            # 00:00 → 23:00 local. The first and last entries land on
            # different UTC dates, which is precisely the case the
            # pre-fix code lost.
            local_midnight = local_today_noon.replace(hour=0)
            prices = []
            for i in range(24):
                local_dt = local_midnight + timedelta(hours=i)
                # Convert to UTC — this is what Nordpool stores.
                utc_dt = local_dt.astimezone(timezone.utc)
                prices.append(PricePoint(
                    timestamp=utc_dt,
                    price=0.10 + i * 0.025,  # 0.10 → 0.685, full spread
                    currency="EUR",
                    level=PriceLevel.NORMAL,
                ))

            p = _make_provider("percentile")
            p._prices_cache = prices

            breaks = p._get_percentile_breaks()
            assert breaks is not None, (
                "TZ skew: UTC-tagged prices for today must be "
                "recognised after as_local() conversion"
            )
            # With prices 0.10..0.685 step 0.025, p75 ≈ 0.525. Use a
            # value that's clearly above p75 to confirm we're really
            # using percentile (and not silently fell back to static
            # where 0.55 would also be EXPENSIVE; the load-bearing
            # assertion is `breaks is not None` above).
            assert p._classify_price(0.60) is PriceLevel.EXPENSIVE
        finally:
            dt_util.set_default_time_zone(original_tz)

    def test_utc_timestamps_pre_fix_would_have_emptied_today_array(self):
        """Sanity test: without the as_local() fix, the old filter
        ``p.timestamp.date() == today`` would lose every UTC point
        whose UTC date differs from local. We can't easily run the
        pre-fix code here, but we can prove that today's-local date
        ≠ UTC date for some of the points and verify the FIXED filter
        still picks them up."""
        from datetime import timezone
        try:
            import zoneinfo
            ams = zoneinfo.ZoneInfo("Europe/Amsterdam")
        except Exception:
            pytest.skip("zoneinfo unavailable")

        original_tz = dt_util.get_default_time_zone()
        dt_util.set_default_time_zone(ams)
        try:
            local_today_noon = dt_util.now().replace(
                hour=12, minute=0, second=0, microsecond=0
            )
            local_today = local_today_noon.date()
            # The early-morning local slot (01:00 local) is the previous
            # UTC date in summer (DST +02:00) — i.e. 23:00 UTC the day before.
            local_01 = local_today_noon.replace(hour=1)
            utc_repr = local_01.astimezone(timezone.utc)
            # The naive comparison would treat utc_repr.date() as
            # yesterday — that's the bug we're guarding against.
            naive_date = utc_repr.date()
            fixed_date = dt_util.as_local(utc_repr).date()
            assert fixed_date == local_today
            # If this assertion fails the test environment isn't on +02:00,
            # in which case the pitfall doesn't apply.
            if naive_date != fixed_date:
                assert naive_date < local_today  # would be lost pre-fix
        finally:
            dt_util.set_default_time_zone(original_tz)


class TestRienduPreRegressionFromReproScript:
    """#359 follow-up — regression tests that mirror the live reproduction
    on HA-TEST against synthetic Tibber-NL data, validated 2026-06-04.
    Each test reproduces one of the three scenarios that caused €0.30 to
    render as ``normal`` for RienduPre's install before the fix."""

    @pytest.mark.parametrize("hour, price, expected", [
        # Cherry-picked from the 24h synthetic Tibber NL curve in
        # /tmp/sem-359-repro.py (scenario A). Breaks compute to
        # p10=0.140, p25=0.180, p75=0.300, p90=0.400.
        (4, 0.13, PriceLevel.VERY_CHEAP),     # below p10
        (2, 0.15, PriceLevel.CHEAP),          # at p25 boundary (0.180)
        (10, 0.32, PriceLevel.EXPENSIVE),     # above p75
        (18, 0.45, PriceLevel.VERY_EXPENSIVE),  # above p90
        # RienduPre's exact symptom price — at p75 = 0.30 → EXPENSIVE,
        # NOT NORMAL (which is what static-fallback was producing).
        (8, 0.30, PriceLevel.EXPENSIVE),
    ])
    def test_a_realistic_tibber_nl_percentile(self, hour, price, expected):
        """Scenario A from the repro script: realistic 24h Tibber NL curve,
        percentile mode, breaks compute cleanly."""
        p = _make_provider("percentile")
        curve = [
            0.18, 0.16, 0.15, 0.14, 0.13, 0.14, 0.18, 0.24,
            0.30, 0.32, 0.28, 0.25, 0.22, 0.20, 0.22, 0.26,
            0.32, 0.42, 0.45, 0.40, 0.34, 0.28, 0.22, 0.18,
        ]
        p._prices_cache = _today_prices(curve)
        assert p._classify_price(price) is expected

    def test_b_static_mode_user_choice(self):
        """Scenario B: user explicitly chose static mode. Their choice is
        respected — the CHF-calibrated cutoffs apply. This is the only
        scenario where €0.30 → NORMAL is the correct outcome (because
        the user opted in to those thresholds)."""
        p = _make_provider("static")
        p._prices_cache = _today_prices([0.18, 0.30, 0.45])
        assert p._classify_price(0.30) is PriceLevel.NORMAL

    def test_d_cold_start_no_silent_fallback(self):
        """Scenario D: percentile mode but cache is empty (cold start
        before Tibber populates). Pre-fix: silently used CHF cutoffs and
        €0.30 → NORMAL. Post-fix: returns NORMAL as a safe default
        rather than running through the wrong-currency thresholds."""
        p = _make_provider("percentile")
        p._prices_cache = []
        # NORMAL because we have no data — NOT because a stray €0.15
        # CHF threshold happened to put €0.30 in the middle.
        assert p._classify_price(0.30) is PriceLevel.NORMAL
        # The point: every value comes back as NORMAL during cold
        # start, no matter the magnitude. That's the safe behaviour.
        assert p._classify_price(0.05) is PriceLevel.NORMAL
        assert p._classify_price(0.80) is PriceLevel.NORMAL

    def test_e_flat_day_no_silent_fallback(self):
        """Scenario E: 24h of perfectly-flat €0.30 pricing. The
        degenerate-distribution guard returns None; percentile mode
        should return NORMAL — NOT use the CHF cutoffs and pretend
        anything below €0.15 is CHEAP."""
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.30] * 24)
        assert p._classify_price(0.30) is PriceLevel.NORMAL
        assert p._classify_price(0.10) is PriceLevel.NORMAL  # would have been CHEAP pre-fix
        assert p._classify_price(0.50) is PriceLevel.NORMAL  # would have been EXPENSIVE pre-fix


class TestClassifierPathDiagnostic:
    """#359 follow-up — surface WHICH classifier branch produced each
    ``price_level`` value via ``self._last_classifier_path``. RienduPre's
    install hits the cold-start branch because his Tibber price entity is a
    derivative template that doesn't pass through ``prices_today``, so the
    classifier has nothing to compute breaks from. Without this attribute he
    had no way to self-diagnose; with it, the ``tariff_price_level`` sensor
    carries the reason as an attribute."""

    def test_default_path_is_unknown(self):
        """Before any classification runs, the path should be 'unknown' so
        users in broken-tariff-config setups see a clear signal that the
        classifier never executed."""
        p = _make_provider("percentile")
        assert p._last_classifier_path == "unknown"

    def test_negative_price_short_circuits(self):
        p = _make_provider("percentile")
        p._classify_price(-0.05)
        assert p._last_classifier_path == "negative_price_shortcircuit"

    def test_static_mode_records_fixed_cutoffs(self):
        p = _make_provider("static")
        p._prices_cache = _today_prices([0.18, 0.30, 0.45])
        p._classify_price(0.30)
        assert p._last_classifier_path == "static_fixed_cutoffs"

    def test_cold_start_records_cache_empty(self):
        """RienduPre's exact case: cache empty → fallback path documented."""
        p = _make_provider("percentile")
        p._prices_cache = []
        p._classify_price(0.30)
        assert p._last_classifier_path == "percentile_fallback_cache_empty"

    def test_too_few_prices_records_count(self):
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.20, 0.30])  # n=2 < 4
        p._classify_price(0.30)
        assert p._last_classifier_path.startswith(
            "percentile_fallback_too_few_prices("
        )
        assert "n=2" in p._last_classifier_path

    def test_flat_day_records_spread(self):
        p = _make_provider("percentile")
        p._prices_cache = _today_prices([0.30] * 24)
        p._classify_price(0.30)
        assert p._last_classifier_path.startswith(
            "percentile_fallback_flat_day("
        )
        assert "spread=" in p._last_classifier_path

    def test_happy_path_records_breaks(self):
        """When the classifier produces a real bucket, the path string
        embeds p10/p25/p75/p90 + n so debugging support tickets is trivial:
        a screenshot of the attribute proves the buckets were computed."""
        p = _make_provider("percentile")
        curve = [
            0.18, 0.16, 0.15, 0.14, 0.13, 0.14, 0.18, 0.24,
            0.30, 0.32, 0.28, 0.25, 0.22, 0.20, 0.22, 0.26,
            0.32, 0.42, 0.45, 0.40, 0.34, 0.28, 0.22, 0.18,
        ]
        p._prices_cache = _today_prices(curve)
        p._classify_price(0.30)
        assert p._last_classifier_path.startswith("percentile_active(")
        # All four break keys + n should be visible.
        for token in ("p10=", "p25=", "p75=", "p90=", "n=24"):
            assert token in p._last_classifier_path

    def test_get_tariff_data_surfaces_path_on_tariffdata(self):
        """End-to-end: get_tariff_data() copies _last_classifier_path onto
        TariffData.classifier_path so the coordinator → sensor pipeline can
        publish it as an entity attribute."""
        p = _make_provider("percentile")
        p._prices_cache = []
        # Make _read_current_price return 0.30 (cold-start scenario).
        p._read_current_price = lambda: 0.30
        p._read_prices_list = lambda: []
        td = p.get_tariff_data()
        assert td.classifier_path == "percentile_fallback_cache_empty"
        assert td.to_dict()["tariff_classifier_path"] == (
            "percentile_fallback_cache_empty"
        )

    def test_static_provider_path_is_static_ht_nt(self):
        """StaticTariffProvider hard-codes 'static_ht_nt' — gives users a
        clear indicator that their classification mode never engaged the
        percentile machinery at all."""
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            StaticTariffProvider,
        )
        sp = StaticTariffProvider(
            peak_rate=0.35, off_peak_rate=0.15, export_rate=0.08,
        )
        td = sp.get_tariff_data()
        assert td.classifier_path == "static_ht_nt"
