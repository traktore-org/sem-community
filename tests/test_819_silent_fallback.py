"""#819 — a forecast source that could not be used must say so.

Reporter, 23.08 on beta.14: they picked Meteo, the picker kept showing Meteo,
and the source went back to Solcast on the next cycle. Same for Forecast.Solar.
Nothing on screen explained it.

The mechanism is not a lost setting. When the chosen integration cannot be
located, ``ForecastReader.detect_source`` logs a warning and falls back to the
ladder — whose first entry is Solcast — and records
``<chosen>_missing_then_<used>``. That trace reached ``get_diagnostics()`` and
nowhere else, so the card had no way to show it and the user had no way to
learn it. The picker reads the stored preference, so it keeps displaying the
choice that is not being honoured.

Two failures wear the same face here — "SEM cannot find your integration" and
"your setting never saved" — and the user cannot tell them apart. Publishing
the resolved source WITH the requested one separates them at a glance, and
turns the next report of this into a one-line answer instead of an
investigation.
"""

from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)


def _reader(preferred=None):
    hass = MagicMock()
    hass.states.async_all.return_value = []
    hass.states.get.return_value = None
    return ForecastReader(hass, custom_entities=None, preferred_source=preferred)


class TestTheReaderReportsWhatItWasAsked:
    def test_it_remembers_the_requested_source(self):
        r = _reader("open_meteo")
        assert r.requested_source == "open_meteo"

    def test_auto_requests_nothing(self):
        assert _reader("auto").requested_source is None
        assert _reader(None).requested_source is None

    def test_an_unknown_name_is_not_silently_forgotten(self):
        """A stored value that is not a known source is a real
        misconfiguration — most likely a renamed integration — and the user
        should be able to see that SEM was asked for something it does not
        recognise, rather than watching it behave as if nothing was set."""
        r = _reader("meteo")          # the name a user would guess
        assert r.requested_source == "meteo"
        assert r.honoured is False

    def test_a_source_it_could_not_find_is_reported_as_not_honoured(self):
        r = _reader("open_meteo")
        r._preferred_missing = "open_meteo"
        assert r.honoured is False

    def test_a_source_it_used_is_honoured(self):
        r = _reader("open_meteo")
        r._source = "open_meteo"
        r._preferred_missing = None
        assert r.honoured is True

    def test_auto_is_always_honoured(self):
        """Nothing was asked for, so nothing was denied — 'not honoured'
        must not light up for every install that never chose."""
        r = _reader(None)
        assert r.honoured is True


class TestItRidesTheSensor:
    def test_the_diagnostics_carry_the_request_and_the_verdict(self):
        r = _reader("open_meteo")
        r._preferred_missing = "open_meteo"
        d = r.get_diagnostics()
        assert d["requested_source"] == "open_meteo"
        assert d["honoured"] is False

    def test_the_sensor_publishes_them(self):
        """The lesson this issue already taught once, in its own comment: a key
        that only reaches coordinator.data is invisible to the card."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "sensor.py").read_text()
        i = src.index('== "forecast_source"')
        block = src[i:i + 1400]
        assert "requested_source" in block, (
            "the card cannot tell the user which source was asked for")
        assert "source_honoured" in block, (
            "the card cannot tell the user whether the choice was honoured")
