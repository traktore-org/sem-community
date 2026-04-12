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

    def test_ht_rate_weekday_daytime(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_noon()
            assert provider.get_current_import_rate() == 0.3387

    def test_nt_rate_weekday_night(self):
        provider = StaticTariffProvider()
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = _weekday_night()
            assert provider.get_current_import_rate() == 0.3387

    def test_nt_rate_weekend(self):
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

    def test_read_current_price(self, hass):
        hass.states.get = MagicMock(return_value=_make_price_state(0.22))
        provider = DynamicTariffProvider(hass, price_entity="sensor.price")
        assert provider.get_current_import_rate() == 0.22

    def test_read_current_price_fallback_no_entity(self, hass):
        hass.states.get = MagicMock(return_value=None)
        hass.states.async_all = MagicMock(return_value=[])
        provider = DynamicTariffProvider(hass)
        assert provider.get_current_import_rate() == 0.30

    def test_read_current_price_fallback_unavailable(self, hass):
        state = MagicMock()
        state.state = "unavailable"
        hass.states.get = MagicMock(return_value=state)
        provider = DynamicTariffProvider(hass, price_entity="sensor.price")
        assert provider.get_current_import_rate() == 0.30

    def test_detect_provider_tibber(self, hass):
        tibber_state = MagicMock()
        tibber_state.entity_id = "sensor.electricity_price_home"
        tibber_state.attributes = {"integration": "tibber"}

        hass.states.get = MagicMock(return_value=None)
        hass.states.async_all = MagicMock(return_value=[tibber_state])

        provider = DynamicTariffProvider(hass)
        result = provider.detect_provider()
        assert result == "tibber"
        assert provider._price_entity == "sensor.electricity_price_home"

    def test_detect_provider_nordpool(self, hass):
        nordpool_state = MagicMock()
        nordpool_state.entity_id = "sensor.nordpool_kwh_ch_eur_3_10_025"
        nordpool_state.attributes = {"integration": "nordpool"}

        # Tibber search returns nothing matching
        non_tibber = MagicMock()
        non_tibber.entity_id = "sensor.something_else"
        non_tibber.attributes = {}

        hass.states.get = MagicMock(return_value=None)
        hass.states.async_all = MagicMock(side_effect=lambda domain: {
            "sensor": [non_tibber, nordpool_state],
        }.get(domain, []))

        provider = DynamicTariffProvider(hass)
        result = provider.detect_provider()
        assert result == "nordpool"

    def test_classify_price_negative(self, hass):
        provider = DynamicTariffProvider(hass)
        assert provider._classify_price(-0.05) == PriceLevel.NEGATIVE

    def test_classify_price_very_cheap(self, hass):
        provider = DynamicTariffProvider(hass)
        # cheap_threshold default = 0.15, very_cheap < 0.075
        assert provider._classify_price(0.05) == PriceLevel.VERY_CHEAP

    def test_classify_price_cheap(self, hass):
        provider = DynamicTariffProvider(hass)
        # 0.075 <= price < 0.15
        assert provider._classify_price(0.10) == PriceLevel.CHEAP

    def test_classify_price_normal(self, hass):
        provider = DynamicTariffProvider(hass)
        # 0.15 <= price <= 0.35
        assert provider._classify_price(0.25) == PriceLevel.NORMAL

    def test_classify_price_expensive(self, hass):
        provider = DynamicTariffProvider(hass)
        # > 0.35 and <= 0.525
        assert provider._classify_price(0.40) == PriceLevel.EXPENSIVE

    def test_classify_price_very_expensive(self, hass):
        provider = DynamicTariffProvider(hass)
        # > 0.525 (1.5 * 0.35)
        assert provider._classify_price(0.60) == PriceLevel.VERY_EXPENSIVE

    def test_find_cheapest_hours(self, hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices_today = [
            {"start": (now + timedelta(hours=i)).isoformat(), "total": 0.10 + i * 0.05}
            for i in range(1, 7)
        ]
        state = _make_price_state(0.20, attributes={"prices_today": prices_today})
        hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(hass, price_entity="sensor.price")
            cheapest = provider.find_cheapest_hours(2, within_hours=6)

        assert len(cheapest) == 2
        # Should be sorted by time, but the two cheapest are hours 1 and 2
        assert cheapest[0].price <= cheapest[1].price or cheapest[0].timestamp < cheapest[1].timestamp

    def test_tariff_data_with_prices(self, hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices = [
            {"start": now.replace(hour=h).isoformat(), "total": 0.10 + h * 0.01}
            for h in range(24)
        ]
        state = _make_price_state(0.22, attributes={"prices_today": prices})
        hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = DynamicTariffProvider(hass, price_entity="sensor.price")
            data = provider.get_tariff_data()

        assert data.is_dynamic is True
        assert data.current_import_rate == 0.22
        assert data.today_min_price is not None
        assert data.today_max_price is not None
        assert data.today_avg_price is not None
        assert data.today_min_price <= data.today_avg_price <= data.today_max_price

    def test_export_rate(self, hass):
        provider = DynamicTariffProvider(hass, export_rate=0.09)
        assert provider.get_current_export_rate() == 0.09


# ---------------------------------------------------------------------------
# SpotMarketProvider
# ---------------------------------------------------------------------------

class TestSpotMarketProvider:

    def test_total_rate_includes_fees_and_taxes(self, hass):
        hass.states.get = MagicMock(return_value=_make_price_state(0.08))
        provider = SpotMarketProvider(
            hass,
            price_entity="sensor.spot",
            grid_fees=0.10,
            taxes=0.05,
        )
        # 0.08 + 0.10 + 0.05 = 0.23
        assert provider.get_current_import_rate() == pytest.approx(0.23)

    def test_total_rate_floors_at_zero(self, hass):
        hass.states.get = MagicMock(return_value=_make_price_state(-0.50))
        provider = SpotMarketProvider(
            hass,
            price_entity="sensor.spot",
            grid_fees=0.10,
            taxes=0.05,
        )
        # -0.50 + 0.10 + 0.05 = -0.35 -> max(0, -0.35) = 0
        assert provider.get_current_import_rate() == 0.0

    def test_has_negative_prices_true(self, hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices = [
            {"start": (now + timedelta(hours=1)).isoformat(), "total": -0.02},
            {"start": (now + timedelta(hours=2)).isoformat(), "total": 0.10},
        ]
        state = _make_price_state(0.05, attributes={"prices_today": prices})
        hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = SpotMarketProvider(hass, price_entity="sensor.spot")
            assert provider.has_negative_prices(hours=24) is True

    def test_has_negative_prices_false(self, hass):
        now = datetime(2026, 3, 19, 12, 0, 0)
        prices = [
            {"start": (now + timedelta(hours=1)).isoformat(), "total": 0.05},
            {"start": (now + timedelta(hours=2)).isoformat(), "total": 0.10},
        ]
        state = _make_price_state(0.05, attributes={"prices_today": prices})
        hass.states.get = MagicMock(return_value=state)

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            provider = SpotMarketProvider(hass, price_entity="sensor.spot")
            assert provider.has_negative_prices(hours=24) is False

    def test_currency_default_eur(self, hass):
        provider = SpotMarketProvider(hass)
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
