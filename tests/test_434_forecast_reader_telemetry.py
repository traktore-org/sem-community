"""#434 — telemetry surface for ForecastReader.

Locks the source_detection_path / read_path / recommendation_path
strings and the unit_conversion_count counter, all surfaced via
``get_diagnostics()``. Mirrors the established
#359/#416/#420/etc precedents.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    FORECAST_SOLAR_ENTITIES,
    SOLCAST_ENTITIES,
    ForecastData,
    ForecastReader,
)


def _state(state_val, attributes=None):
    s = MagicMock()
    s.state = str(state_val)
    s.attributes = attributes or {}
    return s


# ──────────────────────────────────────────────
# source_detection_path
# ──────────────────────────────────────────────


def test_source_detection_path_custom():
    hass = MagicMock()
    r = ForecastReader(
        hass=hass,
        custom_entities={"forecast_today": "sensor.my_custom"},
    )
    r.detect_source()
    assert r.get_diagnostics()["source_detection_path"] == "custom"


def test_source_detection_path_solcast():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("25.0"))
    r = ForecastReader(hass=hass)
    r.detect_source()
    assert r.get_diagnostics()["source_detection_path"] == "solcast"


def test_source_detection_path_forecast_solar():
    """Solcast entity unavailable → falls through to forecast.solar."""
    hass = MagicMock()
    def get(eid):
        if eid == SOLCAST_ENTITIES["forecast_today"]:
            return _state("unavailable")
        if eid == FORECAST_SOLAR_ENTITIES["forecast_today"]:
            return _state("25.0")
        return None
    hass.states.get = MagicMock(side_effect=get)
    r = ForecastReader(hass=hass)
    r.detect_source()
    assert r.get_diagnostics()["source_detection_path"] == "forecast_solar"


def test_source_detection_path_none_available():
    """Silent-failure surface — no forecast integration detected."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("unavailable"))
    r = ForecastReader(hass=hass)
    result = r.detect_source()
    assert result is None
    assert r.get_diagnostics()["source_detection_path"] == "none_available"


# ──────────────────────────────────────────────
# read_path
# ──────────────────────────────────────────────


def test_read_path_cold_detect():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("25.0"))
    r = ForecastReader(hass=hass)
    r.read_forecast()
    # After first read, the cold_detect path fired then completed
    diag = r.get_diagnostics()
    # The final state of _last_read_path is "read_complete" if reading
    # succeeded; cold_detect was intermediate.
    assert diag["read_path"] == "read_complete"


def test_read_path_no_source_after_detect():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("unavailable"))
    r = ForecastReader(hass=hass)
    result = r.read_forecast()
    assert isinstance(result, ForecastData)
    assert result.available is False
    assert r.get_diagnostics()["read_path"] == "no_source_after_detect"


def test_read_path_cached_source_valid():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("25.0"))
    r = ForecastReader(hass=hass)
    r.read_forecast()  # first read → cold_detect → read_complete
    r.read_forecast()  # second read → cached_source_valid → read_complete
    # _last_read_path holds the FINAL assignment, "read_complete"
    assert r.get_diagnostics()["read_path"] == "read_complete"


def test_read_path_cached_source_lost_redetected():
    """Cached solcast source becomes unavailable → re-detect fires."""
    hass = MagicMock()
    states_seq = iter([
        _state("25.0"),   # first detect_source for solcast
        _state("25.0"),   # read_forecast values
        _state("25.0"),
        _state("25.0"),
        _state("25.0"),
        _state("unavailable"),  # second read: cache check fails
        _state("unavailable"),  # re-detect: solcast fails
        _state("unavailable"),  # re-detect: forecast.solar fails too
    ])
    hass.states.get = MagicMock(side_effect=lambda eid: next(states_seq, _state("unavailable")))
    r = ForecastReader(hass=hass)
    r.read_forecast()  # works
    r.read_forecast()  # cache check fails → re-detect → no source found
    # After re-detect path fired, the final path is no_source_after_detect
    assert r.get_diagnostics()["read_path"] == "no_source_after_detect"


# ──────────────────────────────────────────────
# unit_conversion_count
# ──────────────────────────────────────────────


def test_unit_conversion_count_fires_on_solcast_low_values():
    """Solcast reports kW; values < 100 trigger the *1000 conversion.
    Counter exposes how many of the 3 readings fired the conversion."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("5.0"))  # 5 kW → triggers
    r = ForecastReader(hass=hass)
    r.read_forecast()
    # 3 conversions: power_now, power_next_hour, peak_power_today
    assert r.get_diagnostics()["unit_conversion_count"] == 3


def test_unit_conversion_count_zero_when_already_watts():
    """Solcast reporting values >= 100 are already in watts."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_state("5000.0"))
    r = ForecastReader(hass=hass)
    r.read_forecast()
    assert r.get_diagnostics()["unit_conversion_count"] == 0


# ──────────────────────────────────────────────
# recommendation_path
# ──────────────────────────────────────────────


def test_recommendation_path_target_reached():
    hass = MagicMock()
    r = ForecastReader(hass=hass)
    result = r.get_charging_recommendation(daily_ev_target_kwh=10.0, current_ev_energy_kwh=15.0)
    assert result == "target_reached"
    assert r.get_diagnostics()["recommendation_path"] == "target_reached"


def test_recommendation_path_no_forecast():
    """No forecast data → no_forecast recommendation."""
    hass = MagicMock()
    r = ForecastReader(hass=hass)
    # _last_data starts with available=False
    result = r.get_charging_recommendation(daily_ev_target_kwh=10.0, current_ev_energy_kwh=0.0)
    assert result == "no_forecast"
    assert r.get_diagnostics()["recommendation_path"] == "no_forecast"


def test_recommendation_path_solar_only():
    hass = MagicMock()
    r = ForecastReader(hass=hass)
    r._last_data = ForecastData(
        source="solcast", available=True,
        forecast_remaining_today_kwh=30.0,  # 30 * 0.5 = 15 kWh surplus
    )
    result = r.get_charging_recommendation(daily_ev_target_kwh=10.0, current_ev_energy_kwh=0.0)
    assert result == "solar_only"  # 15 >= 10
    assert r.get_diagnostics()["recommendation_path"] == "solar_only"


def test_recommendation_path_solar_plus_cheap():
    hass = MagicMock()
    r = ForecastReader(hass=hass)
    r._last_data = ForecastData(
        source="solcast", available=True,
        forecast_remaining_today_kwh=12.0,  # 12 * 0.5 = 6 kWh surplus
    )
    result = r.get_charging_recommendation(daily_ev_target_kwh=10.0, current_ev_energy_kwh=0.0)
    assert result == "solar_plus_cheap"  # 6 < 10 but 6 >= 5
    assert r.get_diagnostics()["recommendation_path"] == "solar_plus_cheap"


def test_recommendation_path_immediate():
    hass = MagicMock()
    r = ForecastReader(hass=hass)
    r._last_data = ForecastData(
        source="solcast", available=True,
        forecast_remaining_today_kwh=2.0,  # 2 * 0.5 = 1 kWh surplus
    )
    result = r.get_charging_recommendation(daily_ev_target_kwh=10.0, current_ev_energy_kwh=0.0)
    assert result == "immediate"  # 1 < 5
    assert r.get_diagnostics()["recommendation_path"] == "immediate"


# ──────────────────────────────────────────────
# get_diagnostics shape
# ──────────────────────────────────────────────


def test_get_diagnostics_shape():
    hass = MagicMock()
    r = ForecastReader(hass=hass)
    diag = r.get_diagnostics()
    assert set(diag.keys()) == {
        "source_detection_path", "read_path", "recommendation_path",
        "unit_conversion_count", "source",
    }
