"""#687 — Open-Meteo Solar Forecast autodetection.

The HACS integration rany2/ha-open-meteo-solar-forecast deliberately
mirrors core Forecast.Solar: unique_id = ``{entry_id}_{key}`` with the
same sensor keys. But its platform string is ``open_meteo_solar_forecast``
and its entity_ids are DEVICE-PREFIXED (the reporter's install:
``sensor.pole_barn_energy_production_today``), so neither the
``forecast_solar`` registry scan nor the hardcoded
``sensor.energy_production_today`` fallback ever matched — SEM reported
"No solar forecast integration detected" on a working install.

Detection is registry-only for this platform (no stable global entity
names exist to fall back on).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
    OPEN_METEO_SOLAR_PLATFORM,
    FORECAST_SOLAR_PLATFORM,
    SOLCAST_ENTITIES,
)


def _reg_entry(platform, unique_id, entity_id):
    return SimpleNamespace(
        platform=platform, unique_id=unique_id, entity_id=entity_id,
        disabled_by=None,
    )


def _registry(entries):
    reg = MagicMock()
    reg.entities.values.return_value = entries
    return reg


def _state(value):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {}
    return s


def _hass_with_states(mock_hass, states):
    mock_hass.states.get = lambda e: _state(states[e]) if e in states else None
    return mock_hass


# The reporter's real shape: one config entry, device-prefixed names.
POLE_BARN = [
    _reg_entry(OPEN_METEO_SOLAR_PLATFORM,
               "entry1_energy_production_today",
               "sensor.pole_barn_energy_production_today"),
    _reg_entry(OPEN_METEO_SOLAR_PLATFORM,
               "entry1_energy_production_tomorrow",
               "sensor.pole_barn_energy_production_tomorrow"),
    _reg_entry(OPEN_METEO_SOLAR_PLATFORM,
               "entry1_energy_production_today_remaining",
               "sensor.pole_barn_energy_production_today_remaining"),
    _reg_entry(OPEN_METEO_SOLAR_PLATFORM,
               "entry1_power_production_now",
               "sensor.pole_barn_power_production_now"),
]

POLE_BARN_STATES = {
    "sensor.pole_barn_energy_production_today": "21.4",
    "sensor.pole_barn_energy_production_tomorrow": "18.9",
    "sensor.pole_barn_energy_production_today_remaining": "7.2",
    "sensor.pole_barn_power_production_now": "3400",
}


class TestOpenMeteoDetection:
    def test_detects_open_meteo_by_registry(self, mock_hass):
        """Device-prefixed entities resolve via the registry unique_id —
        the exact install shape that previously went undetected."""
        _hass_with_states(mock_hass, POLE_BARN_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(POLE_BARN),
        ):
            assert reader.detect_source() == "open_meteo"
            data = reader.read_forecast()
        assert data.source == "open_meteo"
        assert data.forecast_today_kwh == 21.4
        assert data.forecast_tomorrow_kwh == 18.9
        assert data.forecast_remaining_today_kwh == 7.2

    def test_solcast_outranks_open_meteo(self, mock_hass):
        """Priority pin: Solcast > Open-Meteo when both installed."""
        states = dict(POLE_BARN_STATES)
        states[SOLCAST_ENTITIES["forecast_today"]] = "25.5"
        _hass_with_states(mock_hass, states)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(POLE_BARN),
        ):
            assert reader.detect_source() == "solcast"

    def test_forecast_solar_outranks_open_meteo(self, mock_hass):
        """Priority pin: Forecast.Solar > Open-Meteo when both installed
        (both use the same suffix map — the platform field keeps their
        registry scans apart)."""
        entries = POLE_BARN + [
            _reg_entry(FORECAST_SOLAR_PLATFORM,
                       "fs1_energy_production_today",
                       "sensor.fs_today"),
        ]
        states = dict(POLE_BARN_STATES)
        states["sensor.fs_today"] = "17.0"
        _hass_with_states(mock_hass, states)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(entries),
        ):
            assert reader.detect_source() == "forecast_solar"
            assert reader._entities["forecast_today"] == "sensor.fs_today"

    def test_no_registry_means_no_open_meteo(self, mock_hass):
        """Registry unavailable → honestly undetected. There is no
        hardcoded entity fallback for this platform (device-prefixed
        names are not predictable), so detection must NOT guess."""
        _hass_with_states(mock_hass, POLE_BARN_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            side_effect=RuntimeError("no registry"),
        ):
            assert reader.detect_source() is None

    def test_unavailable_today_entity_is_not_detected(self, mock_hass):
        """The forecast_today entity must be usable, not just registered
        (same contract as the other sources)."""
        _hass_with_states(mock_hass, {})  # registered but no states
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(POLE_BARN),
        ):
            assert reader.detect_source() is None

    def test_remaining_not_confused_with_today(self, mock_hass):
        """endswith('_energy_production_today') must not swallow the
        '..._today_remaining' unique_id — same pin as #562, now for the
        open_meteo platform scan."""
        _hass_with_states(mock_hass, POLE_BARN_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(POLE_BARN),
        ):
            reader.detect_source()
        assert reader._entities["forecast_today"] == (
            "sensor.pole_barn_energy_production_today")
        assert reader._entities["forecast_remaining"] == (
            "sensor.pole_barn_energy_production_today_remaining")
