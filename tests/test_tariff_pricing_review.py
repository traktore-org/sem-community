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
