"""Tests for tariff providers (Static, Dynamic, SpotMarket)."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from custom_components.solar_energy_management.tariff.tariff_provider import (
    StaticTariffProvider,
    DynamicTariffProvider,
    SpotMarketProvider,
    PriceLevel,
    TariffData,
    PricePoint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DT_UTIL_PATH = "custom_components.solar_energy_management.tariff.tariff_provider.dt_util"


def _weekday_noon():
    """Thursday 2026-03-19 12:00 (weekday, HT)."""
    return datetime(2026, 3, 19, 12, 0, 0)


def _weekday_night():
    """Thursday 2026-03-19 22:00 (weekday, NT)."""
    return datetime(2026, 3, 19, 22, 0, 0)


def _weekend_noon():
    """Saturday 2026-03-21 12:00 (weekend, NT)."""
    return datetime(2026, 3, 21, 12, 0, 0)


def _make_price_state(price, attributes=None):
    state = MagicMock()
    state.state = str(price)
    state.attributes = attributes or {}
    return state


# ---------------------------------------------------------------------------
# StaticTariffProvider
# ---------------------------------------------------------------------------

class TestStaticTariffProvider:

    def test_peak_rate_weekday_daytime(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_noon()
            assert provider.get_current_import_rate() == 0.3387

    def test_off_peak_rate_weekday_night(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_night()
            assert provider.get_current_import_rate() == 0.3387

    def test_off_peak_rate_weekend(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekend_noon()
            assert provider.get_current_import_rate() == 0.3387

    def test_export_rate_always_same(self):
        provider = StaticTariffProvider()
        assert provider.get_current_export_rate() == 0.075

    def test_price_level_ht_is_normal(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_noon()
            assert provider.get_price_level() == PriceLevel.NORMAL

    def test_price_level_nt_is_cheap(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_night()
            assert provider.get_price_level() == PriceLevel.CHEAP

    def test_get_price_at_ht_time(self):
        provider = StaticTariffProvider()
        assert provider.get_price_at(_weekday_noon()) == 0.3387

    def test_get_price_at_nt_time(self):
        provider = StaticTariffProvider()
        assert provider.get_price_at(_weekday_night()) == 0.3387

    def test_get_price_at_weekend(self):
        provider = StaticTariffProvider()
        assert provider.get_price_at(_weekend_noon()) == 0.3387

    def test_tariff_data_during_ht(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_noon()
            data = provider.get_tariff_data()
            assert data.current_import_rate == 0.3387
            assert data.current_export_rate == 0.075
            assert data.price_level == PriceLevel.NORMAL
            assert data.provider == "static"
            assert data.is_dynamic is False
            assert data.today_min_price == 0.3387
            assert data.today_max_price == 0.3387
            # Next cheap window starts at 20:00
            assert data.next_cheap_window_start is not None
            assert data.next_cheap_window_start.hour == 20

    def test_tariff_data_during_nt_no_cheap_window(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_night()
            data = provider.get_tariff_data()
            assert data.price_level == PriceLevel.CHEAP
            # Already in NT, so no next_cheap_window_start
            assert data.next_cheap_window_start is None


# ---------------------------------------------------------------------------
# DynamicTariffProvider
# ---------------------------------------------------------------------------

class TestDynamicTariffProvider:

    def test_read_current_price(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.22))
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
        assert provider.get_current_import_rate() == 0.22

    def test_read_current_price_fallback_no_entity(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(return_value=[])
        provider = DynamicTariffProvider(mock_hass)
        assert provider.get_current_import_rate() == 0.30

    def test_read_current_price_fallback_unavailable(self, mock_hass):
        state = MagicMock()
        state.state = "unavailable"
        mock_hass.states.get = MagicMock(return_value=state)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
        assert provider.get_current_import_rate() == 0.30

    def test_detect_provider_tibber(self, mock_hass):
        tibber_state = MagicMock()
        tibber_state.entity_id = "sensor.electricity_price_home"
        tibber_state.attributes = {"integration": "tibber"}

        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(return_value=[tibber_state])

        provider = DynamicTariffProvider(mock_hass)
        result = provider.detect_provider()
        assert result == "tibber"
        assert provider._price_entity == "sensor.electricity_price_home"

    def test_detect_provider_nordpool(self, mock_hass):
        nordpool_state = MagicMock()
        nordpool_state.entity_id = "sensor.nordpool_kwh_ch_eur_3_10_025"
        nordpool_state.attributes = {"integration": "nordpool"}

        # Tibber search returns nothing matching
        non_tibber = MagicMock()
        non_tibber.entity_id = "sensor.something_else"
        non_tibber.attributes = {}

        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(side_effect=lambda domain: {
            "sensor": [non_tibber, nordpool_state],
        }.get(domain, []))

        provider = DynamicTariffProvider(mock_hass)
        result = provider.detect_provider()
        assert result == "nordpool"

    def test_classify_price_negative(self, mock_hass):
        provider = DynamicTariffProvider(mock_hass)
        assert provider._classify_price(-0.05) == PriceLevel.NEGATIVE

    def test_classify_price_very_cheap(self, mock_hass):
        """#359 follow-up: these tests were exercising the static-cutoff
        buckets but constructing a percentile-default provider, so they
        only passed because of the silent CHF fallback that we just
        removed. Pass ``classification_mode='static'`` to make the
        original intent explicit — testing the fixed-cutoff bucketing.
        """
        provider = DynamicTariffProvider(mock_hass, classification_mode="static")
        # cheap_threshold default = 0.15, very_cheap < 0.075
        assert provider._classify_price(0.05) == PriceLevel.VERY_CHEAP

    def test_classify_price_cheap(self, mock_hass):
        provider = DynamicTariffProvider(mock_hass, classification_mode="static")
        # 0.075 <= price < 0.15
        assert provider._classify_price(0.10) == PriceLevel.CHEAP

    def test_classify_price_normal(self, mock_hass):
        provider = DynamicTariffProvider(mock_hass, classification_mode="static")
        # 0.15 <= price <= 0.35
        assert provider._classify_price(0.25) == PriceLevel.NORMAL

    def test_classify_price_expensive(self, mock_hass):
        provider = DynamicTariffProvider(mock_hass, classification_mode="static")
        # > 0.35 and <= 0.525
        assert provider._classify_price(0.40) == PriceLevel.EXPENSIVE

    def test_classify_price_very_expensive(self, mock_hass):
        provider = DynamicTariffProvider(mock_hass, classification_mode="static")
        # > 0.525 (1.5 * 0.35)
        assert provider._classify_price(0.60) == PriceLevel.VERY_EXPENSIVE

    def test_find_cheapest_hours(self, mock_hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices_today = [
            {"start": (now + timedelta(hours=i)).isoformat(), "total": 0.10 + i * 0.05}
            for i in range(1, 7)
        ]
        state = _make_price_state(0.20, attributes={"prices_today": prices_today})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
            cheapest = provider.find_cheapest_hours(2, within_hours=6)

        assert len(cheapest) == 2
        # Should be sorted by time, but the two cheapest are hours 1 and 2
        assert cheapest[0].price <= cheapest[1].price or cheapest[0].timestamp < cheapest[1].timestamp

    def test_tariff_data_with_prices(self, mock_hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices = [
            {"start": now.replace(hour=h).isoformat(), "total": 0.10 + h * 0.01}
            for h in range(24)
        ]
        state = _make_price_state(0.22, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
            data = provider.get_tariff_data()

        assert data.is_dynamic is True
        assert data.current_import_rate == 0.22
        assert data.today_min_price is not None
        assert data.today_max_price is not None
        assert data.today_avg_price is not None
        assert data.today_min_price <= data.today_avg_price <= data.today_max_price

    def test_export_rate(self, mock_hass):
        provider = DynamicTariffProvider(mock_hass, export_rate=0.09)
        assert provider.get_current_export_rate() == 0.09


# ---------------------------------------------------------------------------
# Amber Electric / Generic Forecast Provider
# ---------------------------------------------------------------------------

class TestAmberElectricProvider:
    """Tests for Amber Electric and generic forecast attribute parsing."""

    def _amber_price_state(self, price=0.28):
        """Create a mock Amber price sensor state."""
        return _make_price_state(price, attributes={
            "duration": 30,
            "per_kwh": price,
            "spot_per_kwh": 0.045,
            "renewables": 42.5,
            "spike_status": "none",
            "descriptor": "neutral",
        })

    def _amber_forecast_state(self, base_time, count=12, interval_min=30, base_price=0.20):
        """Create a mock Amber forecast sensor with forecasts attribute."""
        forecasts = []
        for i in range(count):
            start = base_time + timedelta(minutes=interval_min * i)
            end = start + timedelta(minutes=interval_min)
            price = base_price + (i % 5) * 0.05  # Varying prices
            forecasts.append({
                "duration": interval_min,
                "date": start.strftime("%Y-%m-%d"),
                "per_kwh": round(price, 4),
                "spot_per_kwh": round(price * 0.3, 4),
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "renewables": 40.0 + i,
                "spike_status": "none",
                "descriptor": "neutral" if price < 0.35 else "high",
                "channel_type": "general",
            })
        state = MagicMock()
        state.state = str(forecasts[0]["per_kwh"]) if forecasts else "0"
        state.attributes = {"forecasts": forecasts}
        return state, forecasts

    def _amber_feedin_state(self, price=-0.05):
        """Create a mock Amber feed-in price sensor (negative = earning)."""
        return _make_price_state(price)

    # ── Auto-detection ──

    def test_detect_amber_by_entity_name(self, mock_hass):
        """Amber detected from sensor name pattern."""
        amber = MagicMock()
        amber.entity_id = "sensor.amber_my_home_general_price"
        amber.attributes = {}
        amber.state = "0.28"

        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(return_value=[amber])

        provider = DynamicTariffProvider(mock_hass)
        result = provider.detect_provider()
        assert result == "amber"
        assert provider._price_entity == "sensor.amber_my_home_general_price"
        assert provider._provider_name == "amber"

    def test_detect_amber_finds_forecast_entity(self, mock_hass):
        """Detection also discovers the forecast entity."""
        amber_price = MagicMock()
        amber_price.entity_id = "sensor.amber_my_home_general_price"
        amber_price.attributes = {}
        amber_price.state = "0.28"

        forecast_state = MagicMock()
        forecast_state.state = "0.25"
        forecast_state.attributes = {"forecasts": []}

        feedin_state = MagicMock()
        feedin_state.state = "-0.05"

        def mock_get(entity_id):
            if "forecast" in entity_id:
                return forecast_state
            if "feed_in" in entity_id:
                return feedin_state
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        mock_hass.states.async_all = MagicMock(return_value=[amber_price])

        provider = DynamicTariffProvider(mock_hass)
        provider.detect_provider()
        assert provider._forecast_entity == "sensor.amber_my_home_general_forecast"
        assert provider._feedin_entity == "sensor.amber_my_home_feed_in_price"

    def test_detect_amber_no_forecast_entity(self, mock_hass):
        """Works without forecast entity (fallback to current price only)."""
        amber_price = MagicMock()
        amber_price.entity_id = "sensor.amber_general_price"
        amber_price.attributes = {}
        amber_price.state = "0.28"

        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(return_value=[amber_price])

        provider = DynamicTariffProvider(mock_hass)
        provider.detect_provider()
        assert provider._provider_name == "amber"
        assert provider._forecast_entity is None
        assert provider._feedin_entity is None

    # ── Current price reading ──

    def test_amber_current_price(self, mock_hass):
        """Read current price from Amber price sensor."""
        mock_hass.states.get = MagicMock(return_value=self._amber_price_state(0.32))
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        assert provider.get_current_import_rate() == 0.32

    # ── Dynamic export rate from feed-in sensor ──

    def test_dynamic_export_rate_from_feedin(self, mock_hass):
        """Export rate read from feed-in entity (abs of negative value)."""
        def mock_get(entity_id):
            if entity_id == "sensor.amber_general_price":
                return self._amber_price_state(0.28)
            if entity_id == "sensor.amber_feed_in_price":
                return self._amber_feedin_state(-0.08)
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        provider._feedin_entity = "sensor.amber_feed_in_price"
        assert provider.get_current_export_rate() == pytest.approx(0.08)

    def test_dynamic_export_rate_positive_feedin(self, mock_hass):
        """Feed-in price that's already positive."""
        def mock_get(entity_id):
            if "feed_in" in entity_id:
                return _make_price_state(0.06)
            return self._amber_price_state(0.28)

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        provider._feedin_entity = "sensor.amber_feed_in_price"
        assert provider.get_current_export_rate() == pytest.approx(0.06)

    def test_export_rate_fallback_no_feedin_entity(self, mock_hass):
        """Falls back to static export_rate when no feed-in entity."""
        mock_hass.states.get = MagicMock(return_value=self._amber_price_state(0.28))
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price", export_rate=0.075)
        assert provider.get_current_export_rate() == 0.075

    def test_export_rate_fallback_feedin_unavailable(self, mock_hass):
        """Falls back when feed-in entity is unavailable."""
        def mock_get(entity_id):
            if "feed_in" in entity_id:
                state = MagicMock()
                state.state = "unavailable"
                return state
            return self._amber_price_state(0.28)

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price", export_rate=0.075)
        provider._feedin_entity = "sensor.amber_feed_in_price"
        assert provider.get_current_export_rate() == 0.075

    # ── Forecast price parsing ──

    def test_read_amber_forecasts_from_forecast_entity(self, mock_hass):
        """Parse forecasts from dedicated forecast sensor."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecast_state, raw_forecasts = self._amber_forecast_state(now, count=12)

        def mock_get(entity_id):
            if "forecast" in entity_id:
                return forecast_state
            return self._amber_price_state(0.28)

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        provider._forecast_entity = "sensor.amber_general_forecast"
        prices = provider._read_prices_list()

        assert len(prices) == 12
        assert prices[0].price == raw_forecasts[0]["per_kwh"]
        assert prices[0].timestamp == datetime.fromisoformat(raw_forecasts[0]["start_time"])
        # Verify sorted by time
        for i in range(1, len(prices)):
            assert prices[i].timestamp >= prices[i - 1].timestamp

    def test_read_amber_forecasts_from_price_entity_attrs(self, mock_hass):
        """Parse forecasts from price entity attributes (if provider puts them there)."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecasts = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(), "per_kwh": 0.20 + i * 0.03}
            for i in range(6)
        ]
        state = _make_price_state(0.20, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        prices = provider._read_prices_list()

        assert len(prices) == 6
        assert prices[0].price == 0.20
        assert prices[5].price == pytest.approx(0.35)

    def test_amber_30min_intervals_get_price_at(self, mock_hass):
        """get_price_at works with 30-minute intervals."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecasts = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(), "per_kwh": 0.20 + i * 0.05}
            for i in range(6)
        ]
        state = _make_price_state(0.20, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")

            # At 14:00 exactly → first interval (0.20)
            assert provider.get_price_at(now) == pytest.approx(0.20)
            # At 14:15 → still first interval
            assert provider.get_price_at(now + timedelta(minutes=15)) == pytest.approx(0.20)
            # At 14:30 → second interval (0.25)
            assert provider.get_price_at(now + timedelta(minutes=30)) == pytest.approx(0.25)
            # At 14:45 → still second interval
            assert provider.get_price_at(now + timedelta(minutes=45)) == pytest.approx(0.25)
            # At 15:00 → third interval (0.30)
            assert provider.get_price_at(now + timedelta(minutes=60)) == pytest.approx(0.30)

    def test_amber_hourly_intervals_still_work(self, mock_hass):
        """get_price_at still works with hourly intervals (Tibber/Nordpool)."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        prices = [
            {"start": (now + timedelta(hours=i)).isoformat(), "total": 0.10 + i * 0.05}
            for i in range(4)
        ]
        state = _make_price_state(0.10, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.tibber_price")
            assert provider.get_price_at(now) == pytest.approx(0.10)
            assert provider.get_price_at(now + timedelta(minutes=30)) == pytest.approx(0.10)
            assert provider.get_price_at(now + timedelta(hours=1)) == pytest.approx(0.15)

    def test_amber_forecast_negative_prices(self, mock_hass):
        """Handle negative prices (renewable oversupply)."""
        now = datetime(2026, 5, 3, 12, 0, 0)
        forecasts = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(), "per_kwh": -0.05 + i * 0.03}
            for i in range(6)
        ]
        state = _make_price_state(-0.05, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        prices = provider._read_prices_list()

        assert len(prices) == 6
        assert prices[0].price == -0.05
        assert prices[0].level == PriceLevel.NEGATIVE

    def test_amber_forecast_spike_detection(self, mock_hass):
        """Classify spike prices as very_expensive.

        #359 follow-up: tests the static-cutoff branch explicitly (the
        2-point forecast is too small for percentile mode, so under the
        post-fix default the spike would be classified as NORMAL too).
        Static mode is the correct shape for testing the literal 'a
        price > 0.525 is very_expensive' assertion.
        """
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecasts = [
            {"start_time": now.isoformat(), "per_kwh": 0.25},
            {"start_time": (now + timedelta(minutes=30)).isoformat(), "per_kwh": 2.50},  # Spike!
        ]
        state = _make_price_state(0.25, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(
            mock_hass,
            price_entity="sensor.amber_general_price",
            classification_mode="static",
        )
        prices = provider._read_prices_list()

        assert prices[0].level == PriceLevel.NORMAL
        assert prices[1].level == PriceLevel.VERY_EXPENSIVE

    # ── E2E: full tariff data pipeline ──

    def test_amber_full_tariff_data(self, mock_hass):
        """End-to-end: detection → price → forecasts → tariff data."""
        now = datetime(2026, 5, 3, 14, 0, 0)

        # Create Amber entities
        amber_price = MagicMock()
        amber_price.entity_id = "sensor.amber_my_home_general_price"
        amber_price.attributes = {}
        amber_price.state = "0.28"

        forecast_state, _ = self._amber_forecast_state(now, count=24, base_price=0.15)
        feedin_state = self._amber_feedin_state(-0.06)

        def mock_get(entity_id):
            if "forecast" in entity_id:
                return forecast_state
            if "feed_in" in entity_id:
                return feedin_state
            if "general_price" in entity_id:
                return self._amber_price_state(0.28)
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        mock_hass.states.async_all = MagicMock(return_value=[amber_price])

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now

            provider = DynamicTariffProvider(mock_hass, currency="AUD")
            result = provider.detect_provider()
            assert result == "amber"

            data = provider.get_tariff_data()
            assert data.is_dynamic is True
            assert data.provider == "amber"
            assert data.current_import_rate == 0.28
            assert data.current_export_rate == pytest.approx(0.06)
            assert data.currency == "AUD"
            assert data.today_min_price is not None
            assert data.today_max_price is not None
            assert len(data.upcoming_prices) > 0

            # Serialization works
            d = data.to_dict()
            assert d["tariff_provider"] == "amber"
            assert d["tariff_is_dynamic"] is True
            assert d["tariff_current_import_rate"] == 0.28
            assert d["tariff_current_export_rate"] == pytest.approx(0.06)

    def test_amber_find_cheapest_hours(self, mock_hass):
        """find_cheapest_hours works with 30-minute Amber intervals."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecasts = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(), "per_kwh": price}
            for i, price in enumerate([0.30, 0.05, 0.25, 0.02, 0.40, 0.08])
        ]
        state = _make_price_state(0.30, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
            cheapest = provider.find_cheapest_hours(2, within_hours=6)

        assert len(cheapest) == 2
        # Two cheapest are 0.02 and 0.05
        prices_found = sorted([p.price for p in cheapest])
        assert prices_found == [0.02, 0.05]

    # ── Edge cases ──

    def test_empty_forecasts_array(self, mock_hass):
        """Empty forecasts array doesn't crash."""
        state = _make_price_state(0.28, attributes={"forecasts": []})
        mock_hass.states.get = MagicMock(return_value=state)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        assert provider._read_prices_list() == []

    def test_malformed_forecast_items_skipped(self, mock_hass):
        """Malformed items in forecasts array are skipped gracefully."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecasts = [
            {"start_time": now.isoformat(), "per_kwh": 0.25},    # Good
            {"start_time": "not-a-date", "per_kwh": 0.30},        # Bad timestamp
            {"per_kwh": 0.35},                                      # Missing timestamp
            {"start_time": now.isoformat()},                        # Missing price
            "not-a-dict",                                           # Not a dict
            {"start_time": (now + timedelta(minutes=30)).isoformat(), "per_kwh": 0.28},  # Good
        ]
        state = _make_price_state(0.25, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber_general_price")
        prices = provider._read_prices_list()
        assert len(prices) == 2  # Only the two valid entries

    def test_forecasts_not_used_when_tibber_prices_exist(self, mock_hass):
        """If Tibber prices_today exists, forecasts attribute is ignored."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        tibber_prices = [
            {"start": (now + timedelta(hours=i)).isoformat(), "total": 0.10 + i * 0.02}
            for i in range(3)
        ]
        amber_forecasts = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(), "per_kwh": 0.50 + i * 0.10}
            for i in range(3)
        ]
        # Both attributes present — Tibber format should win
        state = _make_price_state(0.10, attributes={
            "prices_today": tibber_prices,
            "forecasts": amber_forecasts,
        })
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.tibber_price")
        prices = provider._read_prices_list()
        # Should use Tibber prices (0.10, 0.12, 0.14), NOT Amber (0.50, 0.60, 0.70)
        assert len(prices) == 3
        assert prices[0].price == pytest.approx(0.10)

    def test_generic_forecast_attribute_with_price_key(self, mock_hass):
        """Generic provider using 'price' instead of 'per_kwh'."""
        now = datetime(2026, 5, 3, 14, 0, 0)
        forecasts = [
            {"start": now.isoformat(), "price": 0.22},
            {"start": (now + timedelta(hours=1)).isoformat(), "price": 0.18},
        ]
        state = _make_price_state(0.22, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.some_provider")
        prices = provider._read_prices_list()
        assert len(prices) == 2
        assert prices[0].price == 0.22
        assert prices[1].price == 0.18


# ---------------------------------------------------------------------------
# Octopus Energy Provider
# ---------------------------------------------------------------------------

class TestOctopusEnergyProvider:
    """Tests for Octopus Energy (UK) dynamic tariff support."""

    def _octopus_rates(self, base_time, count=48, interval_min=30, base_price=0.25):
        """Create mock Octopus rates array."""
        rates = []
        for i in range(count):
            start = base_time + timedelta(minutes=interval_min * i)
            end = start + timedelta(minutes=interval_min)
            price = base_price + (i % 8 - 4) * 0.03  # Varying prices
            rates.append({
                "start": start.isoformat(),
                "end": end.isoformat(),
                "value_inc_vat": round(price, 4),
                "is_capped": False,
                "is_intelligent_adjusted": False,
            })
        return rates

    def test_detect_octopus_by_entity_name(self, mock_hass):
        octopus = MagicMock()
        octopus.entity_id = "sensor.octopus_energy_electricity_abc123_12345_current_rate"
        octopus.attributes = {}
        octopus.state = "0.25"

        mock_hass.states.get = MagicMock(return_value=None)
        mock_hass.states.async_all = MagicMock(return_value=[octopus])

        provider = DynamicTariffProvider(mock_hass)
        result = provider.detect_provider()
        assert result == "octopus"
        assert provider._price_entity == octopus.entity_id
        assert provider._provider_name == "octopus"

    def test_detect_octopus_discovers_event_entity(self, mock_hass):
        octopus = MagicMock()
        octopus.entity_id = "sensor.octopus_energy_electricity_abc_123_current_rate"
        octopus.attributes = {}
        octopus.state = "0.25"

        event_state = MagicMock()
        event_state.state = "2026-05-03T14:00:00"
        event_state.attributes = {"rates": []}

        def mock_get(entity_id):
            if "current_day_rates" in entity_id:
                return event_state
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        mock_hass.states.async_all = MagicMock(return_value=[octopus])

        provider = DynamicTariffProvider(mock_hass)
        provider.detect_provider()
        assert provider._forecast_entity == "event.octopus_energy_electricity_abc_123_current_day_rates"

    def test_detect_octopus_discovers_export_entity(self, mock_hass):
        octopus = MagicMock()
        octopus.entity_id = "sensor.octopus_energy_electricity_abc_123_current_rate"
        octopus.attributes = {}
        octopus.state = "0.25"

        export_state = MagicMock()
        export_state.state = "0.04"

        def mock_get(entity_id):
            if "export_current_rate" in entity_id:
                return export_state
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        mock_hass.states.async_all = MagicMock(return_value=[octopus])

        provider = DynamicTariffProvider(mock_hass)
        provider.detect_provider()
        assert provider._feedin_entity == "sensor.octopus_energy_electricity_abc_123_export_current_rate"

    def test_read_octopus_rates_from_event_entity(self, mock_hass):
        now = datetime(2026, 5, 3, 0, 0, 0)
        rates = self._octopus_rates(now, count=48, base_price=0.20)

        event_state = MagicMock()
        event_state.state = "2026-05-03"
        event_state.attributes = {"rates": rates}

        def mock_get(entity_id):
            if "current_day_rates" in entity_id:
                return event_state
            return _make_price_state(0.20)

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.octopus_current_rate")
        provider._forecast_entity = "event.octopus_current_day_rates"
        prices = provider._read_prices_list()

        assert len(prices) == 48
        assert prices[0].price == rates[0]["value_inc_vat"]

    def test_octopus_30min_get_price_at(self, mock_hass):
        now = datetime(2026, 5, 3, 14, 0, 0)
        rates = [
            {"start": (now + timedelta(minutes=30 * i)).isoformat(), "value_inc_vat": 0.20 + i * 0.05}
            for i in range(4)
        ]
        state = _make_price_state(0.20, attributes={"rates": rates})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.octopus")
            assert provider.get_price_at(now) == pytest.approx(0.20)
            assert provider.get_price_at(now + timedelta(minutes=15)) == pytest.approx(0.20)
            assert provider.get_price_at(now + timedelta(minutes=30)) == pytest.approx(0.25)

    def test_octopus_dynamic_export_rate(self, mock_hass):
        def mock_get(entity_id):
            if "export" in entity_id:
                return _make_price_state(0.04)
            return _make_price_state(0.25)

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.octopus_rate")
        provider._feedin_entity = "sensor.octopus_export_rate"
        assert provider.get_current_export_rate() == pytest.approx(0.04)

    def test_octopus_full_tariff_data(self, mock_hass):
        now = datetime(2026, 5, 3, 14, 0, 0)
        rates = self._octopus_rates(now, count=24, base_price=0.22)

        octopus = MagicMock()
        octopus.entity_id = "sensor.octopus_energy_electricity_abc_123_current_rate"
        octopus.attributes = {}
        octopus.state = "0.25"

        event_state = MagicMock()
        event_state.state = "2026-05-03"
        event_state.attributes = {"rates": rates}

        export_state = MagicMock()
        export_state.state = "0.05"

        def mock_get(entity_id):
            if "current_day_rates" in entity_id:
                return event_state
            if "export_current_rate" in entity_id:
                return export_state
            if "current_rate" in entity_id:
                return _make_price_state(0.25)
            return None

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        mock_hass.states.async_all = MagicMock(return_value=[octopus])

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, currency="GBP")
            provider.detect_provider()

            data = provider.get_tariff_data()
            assert data.is_dynamic is True
            assert data.provider == "octopus"
            assert data.current_import_rate == 0.25
            assert data.current_export_rate == pytest.approx(0.05)
            assert data.currency == "GBP"
            assert len(data.upcoming_prices) > 0

    def test_octopus_empty_rates(self, mock_hass):
        event_state = MagicMock()
        event_state.state = "2026-05-03"
        event_state.attributes = {"rates": []}

        def mock_get(entity_id):
            if "rates" in entity_id:
                return event_state
            return _make_price_state(0.25)

        mock_hass.states.get = MagicMock(side_effect=mock_get)
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.octopus")
        provider._forecast_entity = "event.octopus_rates"
        assert provider._read_prices_list() == []

    def test_octopus_malformed_rates_skipped(self, mock_hass):
        now = datetime(2026, 5, 3, 14, 0, 0)
        rates = [
            {"start": now.isoformat(), "value_inc_vat": 0.25},
            {"start": "bad-date", "value_inc_vat": 0.30},
            {"value_inc_vat": 0.35},
            {"start": (now + timedelta(minutes=30)).isoformat()},
            "not-a-dict",
            {"start": (now + timedelta(hours=1)).isoformat(), "value_inc_vat": 0.28},
        ]
        state = _make_price_state(0.25, attributes={"rates": rates})
        mock_hass.states.get = MagicMock(return_value=state)

        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.octopus")
        prices = provider._read_prices_list()
        assert len(prices) == 2


# ---------------------------------------------------------------------------
# Dynamic Tariff Schedule Generation (#165)
# ---------------------------------------------------------------------------

class TestDynamicTariffSchedule:
    """Tests for get_schedule_for_day() on DynamicTariffProvider."""

    def test_schedule_from_hourly_prices(self, mock_hass):
        """Generate schedule from Tibber-style hourly prices."""
        now = datetime(2026, 5, 3, 0, 0, 0)
        prices = []
        for h in range(24):
            # Cheap at night (00-06), normal day (06-20), cheap evening (20-24)
            price = 0.08 if h < 6 or h >= 20 else 0.30
            prices.append({"start": now.replace(hour=h).isoformat(), "total": price})

        state = _make_price_state(0.08, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
            schedule = provider.get_schedule_for_day(now)

        # Block shape was extended in #282 with `level` + `avg_price` — assert
        # the legacy NT/HT contract still holds without locking the dict shape.
        assert len(schedule) == 3
        def _legacy(b): return {"start": b["start"], "end": b["end"], "tariff": b["tariff"]}
        assert _legacy(schedule[0]) == {"start": "00:00", "end": "06:00", "tariff": "NT"}
        assert _legacy(schedule[1]) == {"start": "06:00", "end": "20:00", "tariff": "HT"}
        assert _legacy(schedule[2]) == {"start": "20:00", "end": "24:00", "tariff": "NT"}

    def test_schedule_from_30min_prices(self, mock_hass):
        """Generate schedule from Amber/Octopus 30-min intervals."""
        now = datetime(2026, 5, 3, 12, 0, 0)
        forecasts = []
        for i in range(8):  # 4 hours of 30-min intervals
            start = now + timedelta(minutes=30 * i)
            # First 2 hours cheap, last 2 expensive
            price = 0.05 if i < 4 else 0.45
            forecasts.append({"start_time": start.isoformat(), "per_kwh": price})

        state = _make_price_state(0.05, attributes={"forecasts": forecasts})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber")
            schedule = provider.get_schedule_for_day(now)

        assert len(schedule) == 2
        assert schedule[0]["tariff"] == "NT"
        assert schedule[0]["start"] == "12:00"
        assert schedule[0]["end"] == "14:00"
        assert schedule[1]["tariff"] == "HT"
        assert schedule[1]["start"] == "14:00"
        assert schedule[1]["end"] == "24:00"

    def test_schedule_negative_prices(self, mock_hass):
        """Negative prices map to NT (cheap)."""
        now = datetime(2026, 5, 3, 12, 0, 0)
        prices = [
            {"start": now.isoformat(), "total": -0.05},
            {"start": (now + timedelta(hours=1)).isoformat(), "total": 0.30},
        ]
        state = _make_price_state(-0.05, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
            schedule = provider.get_schedule_for_day(now)

        assert schedule[0]["tariff"] == "NT"  # Negative = cheap
        assert schedule[1]["tariff"] == "HT"

    def test_schedule_all_cheap(self, mock_hass):
        """All prices cheap → single NT block.

        #359 follow-up: flat days (24 × €0.05) trip the degenerate-
        distribution guard, so percentile mode returns NORMAL = HT
        for every hour. Use static mode here — the test's semantics
        are about schedule generation from a flat-cheap day, which is
        exactly what static cutoffs were designed to encode.
        """
        now = datetime(2026, 5, 3, 0, 0, 0)
        prices = [
            {"start": now.replace(hour=h).isoformat(), "total": 0.05}
            for h in range(24)
        ]
        state = _make_price_state(0.05, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(
                mock_hass,
                price_entity="sensor.price",
                classification_mode="static",
            )
            schedule = provider.get_schedule_for_day(now)

        assert len(schedule) == 1
        # Block shape extended in #282; keep legacy NT/HT contract intact.
        assert schedule[0]["start"] == "00:00"
        assert schedule[0]["end"] == "24:00"
        assert schedule[0]["tariff"] == "NT"

    def test_schedule_empty_no_prices(self, mock_hass):
        """No prices for target day → empty schedule (card uses fallback)."""
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.25))

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 3, 12, 0, 0)
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.price")
            schedule = provider.get_schedule_for_day()

        assert schedule == []

    def test_schedule_with_spikes(self, mock_hass):
        """Spike prices map to HT.

        #359 follow-up: 3 prices is below the 4-point percentile
        minimum, so percentile mode returns NORMAL for every hour and
        the spike doesn't get singled out. Use static mode — the test
        is about absolute-magnitude spike detection.
        """
        now = datetime(2026, 5, 3, 14, 0, 0)
        prices = [
            {"start": now.isoformat(), "total": 0.10},           # Cheap
            {"start": (now + timedelta(hours=1)).isoformat(), "total": 2.50},  # Spike
            {"start": (now + timedelta(hours=2)).isoformat(), "total": 0.10},  # Cheap
        ]
        state = _make_price_state(0.10, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(
                mock_hass,
                price_entity="sensor.price",
                classification_mode="static",
            )
            schedule = provider.get_schedule_for_day(now)

        assert len(schedule) == 3
        assert schedule[0]["tariff"] == "NT"
        assert schedule[1]["tariff"] == "HT"  # Spike
        assert schedule[2]["tariff"] == "NT"

    def test_schedule_alternating_prices(self, mock_hass):
        """Rapidly alternating prices create many blocks."""
        now = datetime(2026, 5, 3, 10, 0, 0)
        prices = [
            {"start_time": (now + timedelta(minutes=30 * i)).isoformat(),
             "per_kwh": 0.05 if i % 2 == 0 else 0.40}
            for i in range(6)
        ]
        state = _make_price_state(0.05, attributes={"forecasts": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(mock_hass, price_entity="sensor.amber")
            schedule = provider.get_schedule_for_day(now)

        assert len(schedule) == 6  # NT-HT-NT-HT-NT-HT


# ---------------------------------------------------------------------------
# SpotMarketProvider
# ---------------------------------------------------------------------------

class TestSpotMarketProvider:

    def test_total_rate_includes_fees_and_taxes(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.08))
        provider = SpotMarketProvider(
            mock_hass,
            price_entity="sensor.spot",
            grid_fees=0.10,
            taxes=0.05,
        )
        # 0.08 + 0.10 + 0.05 = 0.23
        assert provider.get_current_import_rate() == pytest.approx(0.23)

    def test_total_rate_floors_at_zero(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(-0.50))
        provider = SpotMarketProvider(
            mock_hass,
            price_entity="sensor.spot",
            grid_fees=0.10,
            taxes=0.05,
        )
        # -0.50 + 0.10 + 0.05 = -0.35 -> max(0, -0.35) = 0
        assert provider.get_current_import_rate() == 0.0

    def test_has_negative_prices_true(self, mock_hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices = [
            {"start": (now + timedelta(hours=1)).isoformat(), "total": -0.02},
            {"start": (now + timedelta(hours=2)).isoformat(), "total": 0.10},
        ]
        state = _make_price_state(0.05, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = SpotMarketProvider(mock_hass, price_entity="sensor.spot")
            assert provider.has_negative_prices(hours=24) is True

    def test_has_negative_prices_false(self, mock_hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices = [
            {"start": (now + timedelta(hours=1)).isoformat(), "total": 0.05},
            {"start": (now + timedelta(hours=2)).isoformat(), "total": 0.10},
        ]
        state = _make_price_state(0.05, attributes={"prices_today": prices})
        mock_hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = SpotMarketProvider(mock_hass, price_entity="sensor.spot")
            assert provider.has_negative_prices(hours=24) is False

    def test_currency_default_eur(self, mock_hass):
        provider = SpotMarketProvider(mock_hass)
        assert provider.currency == "EUR"


# ---------------------------------------------------------------------------
# TariffData serialization
# ---------------------------------------------------------------------------

class TestTariffDataSerialization:

    def test_to_dict(self):
        data = TariffData(
            current_import_rate=0.25,
            current_export_rate=0.075,
            price_level=PriceLevel.NORMAL,
            currency="CHF",
            provider="static",
            is_dynamic=False,
            today_min_price=0.20,
            today_max_price=0.35,
            today_avg_price=0.27,
        )
        d = data.to_dict()
        assert d["tariff_current_import_rate"] == 0.25
        assert d["tariff_current_export_rate"] == 0.075
        assert d["tariff_price_level"] == "normal"
        assert d["tariff_currency"] == "CHF"
        assert d["tariff_provider"] == "static"
        assert d["tariff_is_dynamic"] is False
        assert d["tariff_today_min_price"] == 0.20
        assert d["tariff_today_max_price"] == 0.35

    def test_to_dict_none_prices(self):
        data = TariffData()
        d = data.to_dict()
        assert d["tariff_today_min_price"] is None
        assert d["tariff_next_cheap_start"] is None
