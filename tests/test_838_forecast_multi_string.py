"""#838 — multiple Forecast.Solar / Open-Meteo strings must be SUMMED.

Reporter (HorizonKane): "I use Forecast-Solar ... I have one Forecast set up
per String. SEM seems to only use one of them instead of summarising all
strings."

Root cause: both integrations model a multi-string array as one CONFIG ENTRY
PER PLANE — each plane emits its own ``energy_production_*`` sensor whose
unique_id ends in the same suffix (``{entry_id}_energy_production_today`` etc.,
entity_id disambiguated with ``_2``/``_3``). The registry scan kept only the
FIRST match per role (``role not in resolved``), so SEM read a single string's
forecast as the whole array. Fix: collect every plane per role and sum them on
read. Solcast is exact-matched on an already-total sensor and stays single.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
    FORECAST_SOLAR_PLATFORM,
    OPEN_METEO_SOLAR_PLATFORM,
    SOLCAST_PLATFORM,
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


def _state(value, unit=None):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit} if unit else {}
    return s


def _hass_with_states(mock_hass, states):
    mock_hass.states.get = (
        lambda e: (states[e] if isinstance(states[e], MagicMock) else _state(states[e]))
        if e in states else None
    )
    return mock_hass


def _two_plane(platform):
    """Two config entries (two strings) of the same forecast platform."""
    return [
        _reg_entry(platform, "e1_energy_production_today",
                   "sensor.energy_production_today"),
        _reg_entry(platform, "e1_energy_production_tomorrow",
                   "sensor.energy_production_tomorrow"),
        _reg_entry(platform, "e1_energy_production_today_remaining",
                   "sensor.energy_production_today_remaining"),
        _reg_entry(platform, "e1_power_production_now",
                   "sensor.power_production_now"),
        # Second string — HA disambiguates the entity_id with _2, the
        # unique_id keeps the same suffix under a different entry prefix.
        _reg_entry(platform, "e2_energy_production_today",
                   "sensor.energy_production_today_2"),
        _reg_entry(platform, "e2_energy_production_tomorrow",
                   "sensor.energy_production_tomorrow_2"),
        _reg_entry(platform, "e2_energy_production_today_remaining",
                   "sensor.energy_production_today_remaining_2"),
        _reg_entry(platform, "e2_power_production_now",
                   "sensor.power_production_now_2"),
    ]


TWO_PLANE_STATES = {
    "sensor.energy_production_today": "10.0",
    "sensor.energy_production_tomorrow": "12.0",
    "sensor.energy_production_today_remaining": "4.0",
    "sensor.power_production_now": "1500",
    "sensor.energy_production_today_2": "6.0",
    "sensor.energy_production_tomorrow_2": "8.0",
    "sensor.energy_production_today_remaining_2": "3.0",
    "sensor.power_production_now_2": "900",
}


class TestMultiStringForecastSolar:
    def test_two_strings_are_summed(self, mock_hass):
        """The reported bug: two Forecast.Solar strings must sum, not read
        one. 10+6 today, 12+8 tomorrow, 4+3 remaining, 1500+900 power."""
        _hass_with_states(mock_hass, TWO_PLANE_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(_two_plane(FORECAST_SOLAR_PLATFORM)),
        ):
            assert reader.detect_source() == "forecast_solar"
            data = reader.read_forecast()
        assert data.forecast_today_kwh == 16.0
        assert data.forecast_tomorrow_kwh == 20.0
        assert data.forecast_remaining_today_kwh == 7.0
        assert data.power_now_w == 2400.0

    def test_primary_entity_is_still_first_plane(self, mock_hass):
        """Detection/validity/peak parsing key off the representative
        (first) entity — that must be byte-for-byte the pre-#838 value."""
        _hass_with_states(mock_hass, TWO_PLANE_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(_two_plane(FORECAST_SOLAR_PLATFORM)),
        ):
            reader.detect_source()
        assert reader._entities["forecast_today"] == "sensor.energy_production_today"
        assert reader._entity_groups["forecast_today"] == [
            "sensor.energy_production_today",
            "sensor.energy_production_today_2",
        ]

    def test_partial_availability_sums_available_planes(self, mock_hass):
        """A NON-representative plane unavailable → sum the rest, never
        zero. Discriminating: three planes (10 + <dark> + 5); the fix
        returns 15, the pre-#838 first-match code returned only 10, so a
        revert fails this."""
        entries = [
            _reg_entry(FORECAST_SOLAR_PLATFORM, "e1_energy_production_today",
                       "sensor.energy_production_today"),
            _reg_entry(FORECAST_SOLAR_PLATFORM, "e2_energy_production_today",
                       "sensor.energy_production_today_2"),
            _reg_entry(FORECAST_SOLAR_PLATFORM, "e3_energy_production_today",
                       "sensor.energy_production_today_3"),
        ]
        _hass_with_states(mock_hass, {
            "sensor.energy_production_today": "10.0",
            "sensor.energy_production_today_2": _state("unavailable"),
            "sensor.energy_production_today_3": "5.0",
        })
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(entries),
        ):
            reader.detect_source()
            data = reader.read_forecast()
        assert data.forecast_today_kwh == 15.0   # 10 + (dark) + 5

    def test_dark_representative_plane_does_not_hide_the_array(self, mock_hass):
        """(#838) The FIRST plane being unavailable must not drop the whole
        forecast — detection/validity are plane-aware, so a live sibling
        still yields (and sums) a forecast."""
        entries = [
            _reg_entry(FORECAST_SOLAR_PLATFORM, "e1_energy_production_today",
                       "sensor.energy_production_today"),
            _reg_entry(FORECAST_SOLAR_PLATFORM, "e2_energy_production_today",
                       "sensor.energy_production_today_2"),
        ]
        _hass_with_states(mock_hass, {
            "sensor.energy_production_today": _state("unavailable"),
            "sensor.energy_production_today_2": "6.0",
        })
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(entries),
        ):
            assert reader.detect_source() == "forecast_solar"
            data = reader.read_forecast()
        assert data.available is True
        assert data.forecast_today_kwh == 6.0

    def test_single_string_unchanged(self, mock_hass):
        """A single-plane install must behave exactly as before — no sum,
        the one value passes through."""
        entries = _two_plane(FORECAST_SOLAR_PLATFORM)[:4]  # only string 1
        _hass_with_states(mock_hass, TWO_PLANE_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(entries),
        ):
            reader.detect_source()
            data = reader.read_forecast()
        assert data.forecast_today_kwh == 10.0
        assert data.power_now_w == 1500.0


class TestMultiStringOpenMeteo:
    """Sibling sweep — Open-Meteo shares the per-plane suffix scheme, so the
    same fix must cover it (same ``else`` branch). Its entity_ids are
    device-prefixed per string (registry-only detection, no fallback)."""

    OM_ENTRIES = [
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM, "sA_energy_production_today",
                   "sensor.east_roof_energy_production_today"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM, "sA_energy_production_tomorrow",
                   "sensor.east_roof_energy_production_tomorrow"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM,
                   "sA_energy_production_today_remaining",
                   "sensor.east_roof_energy_production_today_remaining"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM, "sA_power_production_now",
                   "sensor.east_roof_power_production_now"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM, "sB_energy_production_today",
                   "sensor.west_roof_energy_production_today"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM, "sB_energy_production_tomorrow",
                   "sensor.west_roof_energy_production_tomorrow"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM,
                   "sB_energy_production_today_remaining",
                   "sensor.west_roof_energy_production_today_remaining"),
        _reg_entry(OPEN_METEO_SOLAR_PLATFORM, "sB_power_production_now",
                   "sensor.west_roof_power_production_now"),
    ]
    OM_STATES = {
        "sensor.east_roof_energy_production_today": "10.0",
        "sensor.east_roof_energy_production_tomorrow": "12.0",
        "sensor.east_roof_energy_production_today_remaining": "4.0",
        "sensor.east_roof_power_production_now": "1500",
        "sensor.west_roof_energy_production_today": "6.0",
        "sensor.west_roof_energy_production_tomorrow": "8.0",
        "sensor.west_roof_energy_production_today_remaining": "3.0",
        "sensor.west_roof_power_production_now": "900",
    }

    def test_two_strings_are_summed(self, mock_hass):
        _hass_with_states(mock_hass, self.OM_STATES)
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(self.OM_ENTRIES),
        ):
            assert reader.detect_source() == "open_meteo"
            data = reader.read_forecast()
        assert data.forecast_today_kwh == 16.0
        assert data.forecast_tomorrow_kwh == 20.0
        assert data.forecast_remaining_today_kwh == 7.0
        assert data.power_now_w == 2400.0


class TestSolcastNotSummed:
    """Solcast exposes an already-summed site/account total (per-site
    sensors are deliberately not matched), so it must stay single even
    though it is the same reader — summing it would be wrong."""

    def test_solcast_total_read_once(self, mock_hass):
        entries = [
            _reg_entry(SOLCAST_PLATFORM, "total_kwh_forecast_today",
                       SOLCAST_ENTITIES["forecast_today"]),
            _reg_entry(SOLCAST_PLATFORM, "total_kwh_forecast_tomorrow",
                       SOLCAST_ENTITIES["forecast_tomorrow"]),
        ]
        _hass_with_states(mock_hass, {
            SOLCAST_ENTITIES["forecast_today"]: "25.5",
            SOLCAST_ENTITIES["forecast_tomorrow"]: "20.0",
        })
        reader = ForecastReader(mock_hass)
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=_registry(entries),
        ):
            assert reader.detect_source() == "solcast"
            data = reader.read_forecast()
        assert data.forecast_today_kwh == 25.5   # not doubled
        assert reader._entity_groups["forecast_today"] == [
            SOLCAST_ENTITIES["forecast_today"]
        ]
