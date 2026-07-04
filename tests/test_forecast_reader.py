"""Tests for ForecastReader solar forecast integration."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
    ForecastData,
    SOLCAST_ENTITIES,
    FORECAST_SOLAR_ENTITIES,
)

DT_UTIL_PATH = "custom_components.solar_energy_management.coordinator.forecast_reader.dt_util"


def _make_state(value):
    """Create a mock HA state with the given value."""
    s = MagicMock()
    s.state = str(value)
    return s


def _unavailable_state():
    s = MagicMock()
    s.state = "unavailable"
    return s


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestForecastReaderInit:

    def test_init_defaults(self, mock_hass):
        reader = ForecastReader(mock_hass)
        assert reader.source is None
        assert reader.forecast_data.available is False
        assert reader.forecast_data.source == "none"

    def test_init_with_custom_entities(self, mock_hass):
        custom = {"forecast_today": "sensor.my_solar_today"}
        reader = ForecastReader(mock_hass, custom_entities=custom)
        assert reader._custom_entities == custom


# ---------------------------------------------------------------------------
# Source detection
# ---------------------------------------------------------------------------

class TestDetectSource:

    def test_detect_solcast(self, mock_hass):
        def mock_get(entity_id):
            if entity_id == SOLCAST_ENTITIES["forecast_today"]:
                return _make_state("25.5")
            return None
        mock_hass.states.get = mock_get

        reader = ForecastReader(mock_hass)
        result = reader.detect_source()
        assert result == "solcast"
        assert reader.source == "solcast"

    def test_detect_forecast_solar(self, mock_hass):
        def mock_get(entity_id):
            if entity_id == FORECAST_SOLAR_ENTITIES["forecast_today"]:
                return _make_state("18.0")
            return None
        mock_hass.states.get = mock_get

        reader = ForecastReader(mock_hass)
        result = reader.detect_source()
        assert result == "forecast_solar"
        assert reader.source == "forecast_solar"

    def test_detect_custom_entities(self, mock_hass):
        custom = {"forecast_today": "sensor.custom_solar"}
        reader = ForecastReader(mock_hass, custom_entities=custom)
        result = reader.detect_source()
        assert result == "custom"
        assert reader._entities == custom

    def test_detect_no_source(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=None)
        reader = ForecastReader(mock_hass)
        result = reader.detect_source()
        assert result is None
        assert reader.source is None

    def test_detect_solcast_unavailable_falls_through(self, mock_hass):
        def mock_get(entity_id):
            if entity_id == SOLCAST_ENTITIES["forecast_today"]:
                return _unavailable_state()
            return None
        mock_hass.states.get = mock_get

        reader = ForecastReader(mock_hass)
        result = reader.detect_source()
        assert result is None


# ---------------------------------------------------------------------------
# Reading forecasts
# ---------------------------------------------------------------------------

class TestReadForecast:

    def _solcast_states(self):
        return {
            SOLCAST_ENTITIES["forecast_today"]: _make_state("25.5"),
            SOLCAST_ENTITIES["forecast_tomorrow"]: _make_state("20.0"),
            SOLCAST_ENTITIES["forecast_remaining"]: _make_state("15.0"),
            SOLCAST_ENTITIES["power_now"]: _make_state("5.2"),  # kW for solcast
            SOLCAST_ENTITIES["power_next_hour"]: _make_state("6.0"),
            SOLCAST_ENTITIES["peak_power_today"]: _make_state("8.5"),
            SOLCAST_ENTITIES["peak_time_today"]: _make_state("13:30"),
        }

    def test_read_forecast_solcast(self, mock_hass):
        states = self._solcast_states()
        mock_hass.states.get = lambda eid: states.get(eid)

        reader = ForecastReader(mock_hass)
        data = reader.read_forecast()

        assert data.source == "solcast"
        assert data.available is True
        assert data.forecast_today_kwh == 25.5
        assert data.forecast_tomorrow_kwh == 20.0
        assert data.forecast_remaining_today_kwh == 15.0
        # Solcast reports kW, values < 100 get *1000
        assert data.power_now_w == 5200.0
        assert data.power_next_hour_w == 6000.0
        assert data.peak_power_today_w == 8500.0
        assert data.peak_time_today == "13:30"

    def test_read_forecast_solar(self, mock_hass):
        states = {
            FORECAST_SOLAR_ENTITIES["forecast_today"]: _make_state("18.0"),
            FORECAST_SOLAR_ENTITIES["forecast_tomorrow"]: _make_state("22.0"),
            FORECAST_SOLAR_ENTITIES["power_now"]: _make_state("3500"),  # W
        }
        mock_hass.states.get = lambda eid: states.get(eid)

        reader = ForecastReader(mock_hass)
        data = reader.read_forecast()

        assert data.source == "forecast_solar"
        assert data.forecast_today_kwh == 18.0
        assert data.forecast_tomorrow_kwh == 22.0
        # forecast.solar reports W directly (3500 > 100, no conversion)
        assert data.power_now_w == 3500.0

    def test_read_forecast_no_source(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=None)
        reader = ForecastReader(mock_hass)
        data = reader.read_forecast()

        assert data.available is False
        assert data.source == "none"
        assert data.forecast_today_kwh == 0.0

    def test_read_float_unavailable_returns_default(self, mock_hass):
        states = {
            SOLCAST_ENTITIES["forecast_today"]: _make_state("25.5"),
            SOLCAST_ENTITIES["forecast_tomorrow"]: _unavailable_state(),
        }
        mock_hass.states.get = lambda eid: states.get(eid)

        reader = ForecastReader(mock_hass)
        data = reader.read_forecast()

        assert data.forecast_today_kwh == 25.5
        assert data.forecast_tomorrow_kwh == 0.0  # default for unavailable


# ---------------------------------------------------------------------------
# Remaining day fraction
# ---------------------------------------------------------------------------

class TestRemainingDayFraction:

    def test_morning_full_day(self, mock_hass):
        reader = ForecastReader(mock_hass)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 19, 5, 0)  # before sunrise
            fraction = reader._remaining_day_fraction()
        assert fraction == 1.0

    def test_noon_half_day(self, mock_hass):
        reader = ForecastReader(mock_hass)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 19, 13, 0)  # 13:00
            fraction = reader._remaining_day_fraction()
        # remaining = 20 - 13 = 7, total = 14, fraction = 0.5
        assert fraction == pytest.approx(0.5)

    def test_evening_zero(self, mock_hass):
        reader = ForecastReader(mock_hass)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 19, 21, 0)  # after sunset
            fraction = reader._remaining_day_fraction()
        assert fraction == 0.0

    def test_sunrise_exact(self, mock_hass):
        reader = ForecastReader(mock_hass)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 19, 6, 0)
            fraction = reader._remaining_day_fraction()
        assert fraction == pytest.approx(1.0)

    def test_sunset_exact(self, mock_hass):
        reader = ForecastReader(mock_hass)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 19, 20, 0)
            fraction = reader._remaining_day_fraction()
        assert fraction == 0.0


# ---------------------------------------------------------------------------
# Charging recommendations
# ---------------------------------------------------------------------------

class TestChargingRecommendation:

    def _setup_reader(self, mock_hass, remaining_kwh, available=True):
        """Set up a reader with pre-loaded forecast data."""
        reader = ForecastReader(mock_hass)
        reader._last_data = ForecastData(
            forecast_remaining_today_kwh=remaining_kwh,
            available=available,
            source="solcast" if available else "none",
        )
        return reader

    def test_target_reached(self, mock_hass):
        reader = self._setup_reader(mock_hass, remaining_kwh=20.0)
        result = reader.get_charging_recommendation(
            daily_ev_target_kwh=10.0,
            current_ev_energy_kwh=12.0,  # already exceeded target
        )
        assert result == "target_reached"

    def test_solar_only(self, mock_hass):
        # remaining 30 kWh * 0.5 = 15 kWh surplus, need 8 kWh -> solar_only
        reader = self._setup_reader(mock_hass, remaining_kwh=30.0)
        result = reader.get_charging_recommendation(
            daily_ev_target_kwh=10.0,
            current_ev_energy_kwh=2.0,
        )
        assert result == "solar_only"

    def test_solar_plus_cheap(self, mock_hass):
        # remaining 12 kWh * 0.5 = 6 kWh surplus, need 8 kWh (6 >= 4 = 50%)
        reader = self._setup_reader(mock_hass, remaining_kwh=12.0)
        result = reader.get_charging_recommendation(
            daily_ev_target_kwh=10.0,
            current_ev_energy_kwh=2.0,
        )
        assert result == "solar_plus_cheap"

    def test_immediate(self, mock_hass):
        # remaining 2 kWh * 0.5 = 1 kWh surplus, need 8 kWh (1 < 4)
        reader = self._setup_reader(mock_hass, remaining_kwh=2.0)
        result = reader.get_charging_recommendation(
            daily_ev_target_kwh=10.0,
            current_ev_energy_kwh=2.0,
        )
        assert result == "immediate"

    def test_no_forecast(self, mock_hass):
        reader = self._setup_reader(mock_hass, remaining_kwh=0.0, available=False)
        result = reader.get_charging_recommendation(
            daily_ev_target_kwh=10.0,
            current_ev_energy_kwh=2.0,
        )
        assert result == "no_forecast"

    def test_target_exactly_reached(self, mock_hass):
        reader = self._setup_reader(mock_hass, remaining_kwh=20.0)
        result = reader.get_charging_recommendation(
            daily_ev_target_kwh=10.0,
            current_ev_energy_kwh=10.0,
        )
        assert result == "target_reached"


# ---------------------------------------------------------------------------
# ForecastData serialization
# ---------------------------------------------------------------------------

class TestForecastDataSerialization:

    def test_to_dict(self):
        data = ForecastData(
            forecast_today_kwh=25.5,
            forecast_tomorrow_kwh=20.0,
            forecast_remaining_today_kwh=15.0,
            power_now_w=5200.0,
            power_next_hour_w=6000.0,
            peak_power_today_w=8500.0,
            peak_time_today="13:30",
            source="solcast",
            available=True,
        )
        d = data.to_dict()
        assert d["forecast_today_kwh"] == 25.5
        assert d["forecast_tomorrow_kwh"] == 20.0
        assert d["forecast_remaining_today_kwh"] == 15.0
        # (#544) forecast_power_now_w / forecast_power_next_hour_w removed from
        # to_dict — dead sensors. The dataclass fields stay for internal use.
        assert "forecast_power_now_w" not in d
        assert d["forecast_peak_power_today_w"] == 8500.0
        assert d["forecast_peak_time_today"] == "13:30"
        assert d["forecast_source"] == "solcast"
        assert d["forecast_available"] is True

    def test_to_dict_empty(self):
        data = ForecastData()
        d = data.to_dict()
        assert d["forecast_today_kwh"] == 0.0
        assert d["forecast_source"] == "none"
        assert d["forecast_available"] is False


# ---------------------------------------------------------------------------
# #562 — cached-source upgrade to Solcast
# ---------------------------------------------------------------------------

class TestSourceUpgradeToSolcast:
    """Solcast > Forecast.Solar priority must survive the source cache.

    Integration start order is arbitrary: if Solcast loads after SEM's
    first detection, SEM used to latch onto Forecast.Solar until the
    next restart (#562, reported by ebnerjoh — Solcast installed and
    active, SEM stuck on a misconfigured Forecast.Solar).
    """

    def _forecast_solar_only(self, entity_id):
        if entity_id == FORECAST_SOLAR_ENTITIES["forecast_today"]:
            return _make_state("18.0")
        if entity_id == FORECAST_SOLAR_ENTITIES["forecast_tomorrow"]:
            return _make_state("16.0")
        return None

    def _both_sources(self, entity_id):
        if entity_id == SOLCAST_ENTITIES["forecast_today"]:
            return _make_state("25.5")
        if entity_id == SOLCAST_ENTITIES["forecast_tomorrow"]:
            return _make_state("20.0")
        return self._forecast_solar_only(entity_id)

    def test_upgrades_when_solcast_appears(self, mock_hass):
        mock_hass.states.get = self._forecast_solar_only
        reader = ForecastReader(mock_hass)
        data = reader.read_forecast()
        assert data.source == "forecast_solar"

        # Solcast integration finishes loading later
        mock_hass.states.get = self._both_sources
        data = reader.read_forecast()
        assert reader.source == "solcast"
        assert data.source == "solcast"
        assert data.forecast_today_kwh == 25.5

    def test_no_upgrade_without_solcast(self, mock_hass):
        mock_hass.states.get = self._forecast_solar_only
        reader = ForecastReader(mock_hass)
        reader.read_forecast()
        reader.read_forecast()
        assert reader.source == "forecast_solar"

    def test_no_upgrade_on_unavailable_solcast(self, mock_hass):
        def get(entity_id):
            if entity_id == SOLCAST_ENTITIES["forecast_today"]:
                return _unavailable_state()
            return self._forecast_solar_only(entity_id)
        mock_hass.states.get = get
        reader = ForecastReader(mock_hass)
        reader.read_forecast()
        reader.read_forecast()
        assert reader.source == "forecast_solar"

    def test_cycle_after_upgrade_is_stable(self, mock_hass):
        mock_hass.states.get = self._forecast_solar_only
        reader = ForecastReader(mock_hass)
        reader.read_forecast()
        mock_hass.states.get = self._both_sources
        reader.read_forecast()
        assert reader.source == "solcast"
        # Next cycle: normal cached-source validation, no re-upgrade churn
        data = reader.read_forecast()
        assert reader.source == "solcast"
        assert data.source == "solcast"

    def test_custom_source_never_upgrades(self, mock_hass):
        custom = {"forecast_today": "sensor.custom_solar"}

        def get(entity_id):
            if entity_id == "sensor.custom_solar":
                return _make_state("12.0")
            if entity_id == SOLCAST_ENTITIES["forecast_today"]:
                return _make_state("25.5")
            return None
        mock_hass.states.get = get
        reader = ForecastReader(mock_hass, custom_entities=custom)
        reader.read_forecast()
        reader.read_forecast()
        assert reader.source == "custom"
