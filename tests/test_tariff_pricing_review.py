"""Regression tests from the Tariff & Pricing review (2026-06).

Covers bugs found while challenging the tariff module:

1. ``get_schedule_for_day`` compared a naked ``timestamp.date()``
   against the local date and labelled blocks with UTC hours — the same
   UTC-vs-local pitfall fixed for #359 in ``_get_percentile_breaks`` /
   ``get_tariff_data``, but missed in the schedule path (Nordpool emits
   UTC timestamps).
2. ``find_cheapest_hours`` treated ``hours_needed`` / ``within_hours``
   as *slot counts*: on 15-min markets a request for "2 hours within
   12" returned 30 minutes of charge time from a 3-hour lookahead
   (#274/H2 class).
3. ``SpotMarketProvider.get_tariff_data`` reported the raw spot price
   as ``current_import_rate``, dropping grid fees + taxes that its own
   ``get_current_import_rate`` adds — the coordinator feeds that value
   into the cost accumulators.
4. ``upcoming_prices`` was the first 24 parsed slots from midnight —
   mostly the past by the afternoon — instead of the upcoming curve.
5. Duplicate price points when an entity exposes the same curve under
   two recognised attribute names skewed the percentile breaks.
6. Mixed naive/aware timestamps in one attribute array crashed the
   sort with TypeError.
7. The Nordpool ``raw_today`` parse path never recorded
   ``_last_parsed_attribute`` for the diagnose surface.
"""
from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    SpotMarketProvider,
)

DT_UTIL_PATH = (
    "custom_components.solar_energy_management.tariff.tariff_provider.dt_util"
)

ZURICH = zoneinfo.ZoneInfo("Europe/Zurich")  # +02:00 in June (CEST)


def _make_price_state(price, attributes=None):
    state = MagicMock()
    state.state = str(price)
    state.attributes = attributes or {}
    return state


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.states.async_all = MagicMock(return_value=[])
    return hass


# ---------------------------------------------------------------------------
# 1. get_schedule_for_day with UTC provider timestamps
# ---------------------------------------------------------------------------

class TestScheduleLocalTz:

    def test_utc_timestamps_produce_local_day_schedule(self, mock_hass):
        """Nordpool-style UTC timestamps: the schedule must cover the
        *local* day 00:00–24:00, not the UTC day shifted by 2 hours."""
        # Local day 2026-06-10 in Europe/Zurich = 2026-06-09T22:00Z .. 2026-06-10T22:00Z
        utc_midnight_local = datetime(2026, 6, 9, 22, 0, tzinfo=timezone.utc)
        raw_today = [
            {
                "start": (utc_midnight_local + timedelta(hours=h)).isoformat(),
                "value": 0.10 + (h % 12) * 0.02,
            }
            for h in range(24)
        ]
        state = _make_price_state(0.20, attributes={"raw_today": raw_today})
        mock_hass.states.get = MagicMock(return_value=state)

        local_noon = datetime(2026, 6, 10, 12, 0, tzinfo=ZURICH)
        with patch(DT_UTIL_PATH + ".now", return_value=local_noon), \
                patch(DT_UTIL_PATH + ".as_local",
                      side_effect=lambda dt: dt.astimezone(ZURICH)), \
                patch(DT_UTIL_PATH + ".DEFAULT_TIME_ZONE", ZURICH):
            provider = DynamicTariffProvider(
                mock_hass, price_entity="sensor.nordpool",
            )
            schedule = provider.get_schedule_for_day()

        assert schedule, "UTC timestamps must not empty the local-day schedule"
        assert schedule[0]["start"] == "00:00"
        assert schedule[-1]["end"] == "24:00"
        # Labels are local hours: with 24 hourly points starting at local
        # midnight, no block may start at "22:00" of the previous UTC day.
        starts = [b["start"] for b in schedule]
        assert all(s < "24:00" for s in starts)

    def test_naive_timestamps_unchanged(self, mock_hass):
        """Naive timestamps (legacy installs / tests) keep working."""
        now = datetime(2026, 6, 10, 12, 0)
        prices_today = [
            {"start": now.replace(hour=h).isoformat(),
             "total": 0.10 if h < 12 else 0.40}
            for h in range(24)
        ]
        state = _make_price_state(0.20, attributes={"prices_today": prices_today})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            schedule = provider.get_schedule_for_day()

        assert schedule
        assert schedule[0]["start"] == "00:00"
        assert schedule[-1]["end"] == "24:00"


# ---------------------------------------------------------------------------
# 2. find_cheapest_hours on sub-hourly markets
# ---------------------------------------------------------------------------

class TestFindCheapestHoursSubHourly:

    def _provider_with_15min_prices(self, mock_hass, now, hours=12, cheap_at=None):
        cheap_at = cheap_at or []
        prices = []
        for i in range(hours * 4):
            ts = now + timedelta(minutes=15 * i)
            price = 0.05 if i in cheap_at else 0.30 + (i % 7) * 0.01
            prices.append({"start": ts.isoformat(), "total": price})
        state = _make_price_state(0.30, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)
        return DynamicTariffProvider(mock_hass, price_entity="sensor.p")

    def test_hours_needed_is_charge_time_not_slot_count(self, mock_hass):
        """2 hours on a 15-min market = 8 slots, not 2 (#274/H2)."""
        now = datetime(2026, 6, 10, 20, 0)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = self._provider_with_15min_prices(mock_hass, now)
            cheapest = provider.find_cheapest_hours(2, within_hours=12)

        assert len(cheapest) == 8
        # Total covered time = 8 × 15 min = the requested 2 hours
        span = (cheapest[-1].timestamp - cheapest[0].timestamp).total_seconds()
        assert span >= 0

    def test_consecutive_block_covers_requested_hours(self, mock_hass):
        now = datetime(2026, 6, 10, 20, 0)
        # Cheapest contiguous stretch: slots 16..23 (= 24:00-26:00)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = self._provider_with_15min_prices(
                mock_hass, now, cheap_at=list(range(16, 24)),
            )
            block = provider.find_cheapest_hours(
                2, within_hours=12, prefer_consecutive=True,
            )

        assert len(block) == 8
        # Contiguous 15-min steps
        for a, b in zip(block, block[1:]):
            assert (b.timestamp - a.timestamp) == timedelta(minutes=15)
        assert all(p.price == 0.05 for p in block)

    def test_within_hours_is_a_time_horizon(self, mock_hass):
        """On 15-min data, within_hours=6 must look 6 hours ahead —
        the old slot-count slice shrank it to 90 minutes."""
        now = datetime(2026, 6, 10, 20, 0)
        # Cheap stretch sits 5 hours out (slot 20 = +5h)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = self._provider_with_15min_prices(
                mock_hass, now, cheap_at=list(range(20, 28)),
            )
            cheapest = provider.find_cheapest_hours(1, within_hours=6)

        assert len(cheapest) == 4
        assert all(p.price == 0.05 for p in cheapest)

    def test_stale_slots_excluded(self, mock_hass):
        """Only the slot in progress may reach into the past: a 30-min
        slot that ended 15 minutes ago is not a candidate."""
        now = datetime(2026, 6, 10, 14, 0)
        forecasts = [
            # Ended 13:30-14:00 → stale
            {"start_time": (now - timedelta(minutes=30)).isoformat(), "per_kwh": 0.01},
            # In progress 14:00-14:30 → candidate
            {"start_time": now.isoformat(), "per_kwh": 0.20},
            {"start_time": (now + timedelta(minutes=30)).isoformat(), "per_kwh": 0.25},
        ]
        state = _make_price_state(0.20, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_x")
            cheapest = provider.find_cheapest_hours(1, within_hours=6)

        assert all(p.timestamp >= now - timedelta(minutes=29) for p in cheapest)
        assert 0.01 not in [p.price for p in cheapest]

    def test_hourly_behaviour_unchanged(self, mock_hass):
        """Hourly markets: slots == hours, exactly the legacy result."""
        now = datetime(2026, 3, 19, 12, 0)
        prices_today = [
            {"start": (now + timedelta(hours=i)).isoformat(), "total": 0.10 + i * 0.05}
            for i in range(1, 7)
        ]
        state = _make_price_state(0.20, attributes={"prices_today": prices_today})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            cheapest = provider.find_cheapest_hours(2, within_hours=6)

        assert len(cheapest) == 2
        assert sorted(p.price for p in cheapest) == [pytest.approx(0.15), pytest.approx(0.20)]


# ---------------------------------------------------------------------------
# 3. SpotMarketProvider effective import rate on TariffData
# ---------------------------------------------------------------------------

class TestSpotMarketTariffData:

    def test_tariff_data_includes_fees_and_taxes(self, mock_hass):
        state = _make_price_state(0.08)
        mock_hass.states.get = MagicMock(return_value=state)
        provider = SpotMarketProvider(
            mock_hass, price_entity="sensor.spot",
            grid_fees=0.10, taxes=0.05,
        )
        data = provider.get_tariff_data()
        # 0.08 spot + 0.10 fees + 0.05 taxes — the rate the cost
        # accumulators must use, not the bare spot price.
        assert data.current_import_rate == pytest.approx(0.23)

    def test_negative_spot_still_floors_at_zero(self, mock_hass):
        state = _make_price_state(-0.30)
        mock_hass.states.get = MagicMock(return_value=state)
        provider = SpotMarketProvider(
            mock_hass, price_entity="sensor.spot",
            grid_fees=0.10, taxes=0.05,
        )
        data = provider.get_tariff_data()
        assert data.current_import_rate == 0
        # Classification still sees the raw negative spot price.
        assert data.price_level is PriceLevel.NEGATIVE


# ---------------------------------------------------------------------------
# 4. upcoming_prices is actually upcoming
# ---------------------------------------------------------------------------

class TestUpcomingPrices:

    def test_upcoming_starts_at_slot_in_progress(self, mock_hass):
        now = datetime(2026, 6, 10, 12, 30)
        midnight = now.replace(hour=0, minute=0)
        today = [
            {"start": (midnight + timedelta(hours=h)).isoformat(), "total": 0.10 + h * 0.01}
            for h in range(24)
        ]
        tomorrow = [
            {"start": (midnight + timedelta(days=1, hours=h)).isoformat(), "total": 0.20}
            for h in range(24)
        ]
        state = _make_price_state(0.22, attributes={"today": today, "tomorrow": tomorrow})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            data = provider.get_tariff_data()

        assert data.upcoming_prices, "upcoming curve must not be empty"
        # First entry = the 12:00 slot in progress, nothing from the morning.
        assert data.upcoming_prices[0].timestamp == midnight + timedelta(hours=12)
        # Tomorrow's prices are part of the upcoming curve once published.
        assert any(
            p.timestamp >= midnight + timedelta(days=1)
            for p in data.upcoming_prices
        )
        assert len(data.upcoming_prices) <= 48


# ---------------------------------------------------------------------------
# 5–7. Parser robustness + diagnostics
# ---------------------------------------------------------------------------

class TestParserRobustness:

    def test_duplicate_attribute_shapes_deduped(self, mock_hass):
        """Same curve under two recognised keys must not double the
        points (it would skew the percentile breaks and today's avg)."""
        now = datetime(2026, 6, 10, 0, 0)
        curve = [
            {"start": (now + timedelta(hours=h)).isoformat(), "total": 0.10 + h * 0.01}
            for h in range(24)
        ]
        state = _make_price_state(0.15, attributes={
            "prices_today": curve,
            "prices": curve,  # alias exposing the identical curve
        })
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            prices = provider._read_prices_list()

        assert len(prices) == 24
        timestamps = [p.timestamp for p in prices]
        assert len(timestamps) == len(set(timestamps))

    def test_mixed_naive_and_aware_timestamps_do_not_crash(self, mock_hass):
        now = datetime(2026, 6, 10, 10, 0, tzinfo=ZURICH)
        attrs = {
            "prices_today": [
                {"start": "2026-06-10T10:00:00+02:00", "total": 0.20},
                {"start": "2026-06-10T11:00:00", "total": 0.25},  # naive
            ],
        }
        state = _make_price_state(0.20, attributes=attrs)
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH + ".now", return_value=now), \
                patch(DT_UTIL_PATH + ".as_local",
                      side_effect=lambda dt: dt.astimezone(ZURICH)), \
                patch(DT_UTIL_PATH + ".DEFAULT_TIME_ZONE", ZURICH):
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            prices = provider._read_prices_list()  # must not raise

        assert len(prices) == 2
        assert prices[0].price == pytest.approx(0.20)
        assert prices[1].price == pytest.approx(0.25)

    def test_nordpool_raw_today_records_parsed_attribute(self, mock_hass):
        now = datetime(2026, 6, 10, 0, 0)
        raw_today = [
            {"start": (now + timedelta(hours=h)).isoformat(), "value": 0.15}
            for h in range(24)
        ]
        state = _make_price_state(0.15, attributes={"raw_today": raw_today})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.nordpool")
            provider._read_prices_list()

        assert provider._last_parsed_attribute == "raw_today"

    def test_unavailable_entity_falls_back_to_cached_curve(self, mock_hass):
        """HA core#166742: Tibber flaps to ``unavailable`` between polls
        since the 2026.1 OAuth2 migration. The current rate must come
        from the cached day-ahead curve, not the hard-coded 0.30."""
        now = datetime(2026, 6, 10, 12, 30)
        midnight = now.replace(hour=12, minute=0)
        good_state = _make_price_state(0.42, attributes={
            "today": [
                {"startsAt": (midnight + timedelta(hours=h)).isoformat(),
                 "total": 0.40 + h * 0.01}
                for h in range(8)
            ],
        })
        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            # Warm the cache from a successful poll …
            mock_hass.states.get = MagicMock(return_value=good_state)
            provider._read_prices_list()
            # … then the entity flaps.
            mock_hass.states.get = MagicMock(return_value=unavailable)
            rate = provider._read_current_price()

        # 12:00 slot price, not the 0.30 constant.
        assert rate == pytest.approx(0.40)

    def test_unavailable_entity_without_cache_keeps_default(self, mock_hass):
        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}
        mock_hass.states.get = MagicMock(return_value=unavailable)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
        assert provider._read_current_price() == 0.30

    def test_empty_parse_does_not_wipe_cache(self, mock_hass):
        """An entity flap (attributes gone) must not destroy the cached
        curve — percentile classification and the schedule card depend
        on it until the next successful poll."""
        now = datetime(2026, 6, 10, 12, 30)
        midnight = now.replace(hour=0, minute=0)
        good_state = _make_price_state(0.20, attributes={
            "today": [
                {"startsAt": (midnight + timedelta(hours=h)).isoformat(),
                 "total": 0.10 + h * 0.02}
                for h in range(24)
            ],
        })
        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
            mock_hass.states.get = MagicMock(return_value=good_state)
            assert len(provider._read_prices_list()) == 24
            mock_hass.states.get = MagicMock(return_value=unavailable)
            prices = provider._read_prices_list()

        assert len(prices) == 24, "flap must serve the last good curve"
        assert len(provider._prices_cache) == 24

    def test_forecasts_path_records_parsed_attribute(self, mock_hass):
        now = datetime(2026, 6, 10, 14, 0)
        forecasts = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(), "per_kwh": 0.20}
            for i in range(4)
        ]
        state = _make_price_state(0.20, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_x")
            provider._read_prices_list()

        assert provider._last_parsed_attribute == "forecasts"


# ---------------------------------------------------------------------------
# Official Nord Pool core integration (service-based, core#132856)
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock  # noqa: E402

from custom_components.solar_energy_management.tariff.tariff_provider import (  # noqa: E402
    PricePoint,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (  # noqa: E402
    BatteryChargeScheduler,
    SchedulerConfig,
)
from homeassistant.util import dt as dt_util  # noqa: E402


def _nordpool_service_hass(response):
    """hass mock exposing the official integration's service surface."""
    hass = MagicMock()
    hass.states.async_all = MagicMock(return_value=[])
    hass.services.has_service = MagicMock(return_value=True)
    entry = MagicMock()
    entry.entry_id = "np-entry-1"
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.services.async_call = AsyncMock(side_effect=response)
    return hass


def _nordpool_action_response(start, count=24, base_mwh=120.0):
    """Action response shape: area-keyed list of start/end/price per MWh."""
    return {
        "CH": [
            {
                "start": (start + timedelta(hours=i)).isoformat(),
                "end": (start + timedelta(hours=i + 1)).isoformat(),
                "price": base_mwh + i,
            }
            for i in range(count)
        ],
    }


class TestOfficialNordPool:

    def test_detects_official_entity(self):
        hass = MagicMock()
        np_state = MagicMock()
        np_state.entity_id = "sensor.nord_pool_ch_current_price"
        np_state.attributes = {}
        hass.states.get = MagicMock(return_value=None)
        hass.states.async_all = MagicMock(return_value=[np_state])

        provider = DynamicTariffProvider(hass)
        assert provider.detect_provider() == "nordpool_official"
        assert provider._price_entity == "sensor.nord_pool_ch_current_price"

    async def test_service_fetch_scales_mwh_to_kwh(self):
        midnight = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = _nordpool_action_response(midnight, base_mwh=120.0)
        hass = _nordpool_service_hass([today, ValueError("tomorrow not published")])
        provider = DynamicTariffProvider(hass, price_entity="sensor.nord_pool_ch_current_price")

        assert await provider.async_refresh_service_prices() is True
        assert len(provider._service_prices) == 24
        # 120 CHF/MWh -> 0.120 CHF/kWh ("All prices are returned in
        # [Currency]/MWh" — integration docs)
        assert provider._service_prices[0].price == pytest.approx(0.120)
        # The failed tomorrow call must not poison the result.
        assert hass.services.async_call.await_count == 2

    async def test_service_prices_feed_read_prices_list(self):
        midnight = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = _nordpool_action_response(midnight)
        hass = _nordpool_service_hass([today, ValueError("no tomorrow")])
        # current_price sensor exists but exposes no arrays (core#132856)
        price_state = _make_price_state(0.121, attributes={})
        hass.states.get = MagicMock(return_value=price_state)
        provider = DynamicTariffProvider(hass, price_entity="sensor.nord_pool_ch_current_price")

        await provider.async_refresh_service_prices()
        prices = provider._read_prices_list()

        assert len(prices) == 24
        assert provider._last_parsed_attribute == "service:nordpool.get_prices_for_date"
        # Percentile classification works off the service curve.
        assert provider._classify_price(0.120) is PriceLevel.VERY_CHEAP

    async def test_service_fetch_throttled(self):
        midnight = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = _nordpool_action_response(midnight)
        hass = _nordpool_service_hass([today, ValueError("no tomorrow"), today, today])
        provider = DynamicTariffProvider(hass, price_entity="sensor.nord_pool_ch_current_price")

        assert await provider.async_refresh_service_prices() is True
        calls_after_first = hass.services.async_call.await_count
        # Within the refresh window: no further service calls.
        assert await provider.async_refresh_service_prices() is False
        assert hass.services.async_call.await_count == calls_after_first

    async def test_no_service_is_a_noop(self):
        hass = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_call = AsyncMock()
        provider = DynamicTariffProvider(hass, price_entity="sensor.whatever")
        assert await provider.async_refresh_service_prices() is False
        hass.services.async_call.assert_not_awaited()


# ---------------------------------------------------------------------------
# Rolling 24h percentile window
# ---------------------------------------------------------------------------

class TestRollingPercentileWindow:

    def test_evening_price_classified_against_night_ahead(self, mock_hass):
        """22:00, tomorrow published: a 0.30 evening price must be
        bucketed against the cheap night/tomorrow ahead (expensive),
        not against today's flat 0.30 curve (which the old per-day
        window reduced to a flat-day NORMAL fallback)."""
        now = datetime(2026, 6, 10, 22, 0)
        midnight = now.replace(hour=0, minute=0)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
        cache = [
            PricePoint(timestamp=midnight + timedelta(hours=h), price=0.30)
            for h in range(24)
        ] + [
            PricePoint(
                timestamp=midnight + timedelta(days=1, hours=h),
                price=0.10 + h * 0.001,
            )
            for h in range(24)
        ]
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider._prices_cache = cache
            level = provider._classify_price(0.30)

        assert level is PriceLevel.VERY_EXPENSIVE
        assert provider._last_classifier_path.startswith("percentile_active(")

    def test_short_future_padded_with_recent_past(self, mock_hass):
        """20:00 with a today-only cache: the window pads backwards so
        classification still sees a full day of context instead of
        falling back on 4 remaining points."""
        now = datetime(2026, 6, 10, 20, 0)
        midnight = now.replace(hour=0, minute=0)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
        provider._prices_cache = [
            PricePoint(timestamp=midnight + timedelta(hours=h), price=0.10 + h * 0.02)
            for h in range(24)
        ]
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            breaks = provider._get_percentile_breaks()

        assert breaks is not None
        assert "n=24" in provider._last_classifier_path

    def test_recompute_when_slot_advances(self, mock_hass):
        """Breaks must not stay pinned to the day — moving to a later
        slot with tomorrow cached shifts the window (and the breaks)."""
        midnight = datetime(2026, 6, 10, 0, 0)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
        provider._prices_cache = [
            PricePoint(timestamp=midnight + timedelta(hours=h), price=0.40 + h * 0.01)
            for h in range(24)
        ] + [
            PricePoint(
                timestamp=midnight + timedelta(days=1, hours=h),
                price=0.10 + h * 0.001,
            )
            for h in range(24)
        ]
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = midnight.replace(hour=1)
            morning_breaks = provider._get_percentile_breaks()
            mock_dt.now.return_value = midnight.replace(hour=23)
            evening_breaks = provider._get_percentile_breaks()

        assert morning_breaks is not None and evening_breaks is not None
        # Evening window is dominated by tomorrow's cheap prices.
        assert evening_breaks["p90"] < morning_breaks["p90"]


# ---------------------------------------------------------------------------
# Configurable fallback price
# ---------------------------------------------------------------------------

class TestConfigurableFallbackPrice:

    def test_configured_fallback_replaces_constant(self, mock_hass):
        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}
        mock_hass.states.get = MagicMock(return_value=unavailable)
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", fallback_price=2.5,  # SEK-ish
        )
        assert provider._read_current_price() == pytest.approx(2.5)

    def test_default_fallback_unchanged(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(return_value=[])
        provider = DynamicTariffProvider(mock_hass)
        assert provider._read_current_price() == pytest.approx(0.30)

    def test_stale_cache_average_beats_constant(self, mock_hass):
        """Cache holds only yesterday (no slot covers now): derive the
        fallback from the cached average rather than any constant."""
        now = datetime(2026, 6, 10, 12, 0)
        yesterday = now - timedelta(days=1)
        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}
        mock_hass.states.get = MagicMock(return_value=unavailable)
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", fallback_price=0.30,
        )
        provider._prices_cache = [
            PricePoint(timestamp=yesterday.replace(hour=h), price=1.00)
            for h in range(24)
        ]
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            rate = provider._read_current_price()
        assert rate == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestDerivativeEntityDiagnostic:
    """#359 ended with a derivative/template entity that mirrors only the
    current price (no array attributes): percentile silently degraded to
    NORMAL with nothing but classifier_path hinting why. SEM now warns
    once, actionably."""

    def _no_array_state(self):
        return _make_price_state(0.30, attributes={"unit": "EUR/kWh"})

    def test_warns_once_for_readable_entity_without_array(self, mock_hass, caplog):
        import logging
        mock_hass.states.get = MagicMock(return_value=self._no_array_state())
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.derivative")

        with caplog.at_level(logging.WARNING):
            provider._read_prices_list()
            provider._read_prices_list()  # second cycle: no repeat

        warnings = [
            r for r in caplog.records
            if "no recognised price-array attribute" in r.message
        ]
        assert len(warnings) == 1
        assert "sensor.derivative" in warnings[0].message

    def test_no_warning_when_entity_unavailable(self, mock_hass, caplog):
        import logging
        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}
        mock_hass.states.get = MagicMock(return_value=unavailable)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")

        with caplog.at_level(logging.WARNING):
            provider._read_prices_list()

        assert not [
            r for r in caplog.records
            if "no recognised price-array attribute" in r.message
        ]

    def test_warning_rearms_after_recovery(self, mock_hass, caplog):
        import logging
        now = datetime(2026, 6, 10, 12, 0)
        good = _make_price_state(0.30, attributes={
            "prices_today": [
                {"start": now.replace(hour=h).isoformat(), "total": 0.20}
                for h in range(24)
            ],
        })
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")

        with caplog.at_level(logging.WARNING), patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            mock_hass.states.get = MagicMock(return_value=self._no_array_state())
            provider._read_prices_list()  # warn #1
            mock_hass.states.get = MagicMock(return_value=good)
            provider._read_prices_list()  # recovery resets the latch
            mock_hass.states.get = MagicMock(return_value=self._no_array_state())
            provider._read_prices_list()  # warn #2

        warnings = [
            r for r in caplog.records
            if "no recognised price-array attribute" in r.message
        ]
        assert len(warnings) == 2


class TestProviderNameForConfiguredEntity:

    def test_configured_entity_reports_custom_not_unknown(self, mock_hass):
        """#359 diagnostics dump showed provider: unknown for a manually
        configured entity (autodetect never runs for those)."""
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.25))
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.my_prices")
        data = provider.get_tariff_data()
        assert data.provider == "custom"

    def test_detected_provider_name_unchanged(self, mock_hass):
        tibber_state = MagicMock()
        tibber_state.entity_id = "sensor.electricity_price_home"
        tibber_state.attributes = {"integration": "tibber"}
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.25))
        mock_hass.states.async_all = MagicMock(return_value=[tibber_state])
        provider = DynamicTariffProvider(mock_hass)
        provider.detect_provider()
        data = provider.get_tariff_data()
        assert data.provider == "tibber"
