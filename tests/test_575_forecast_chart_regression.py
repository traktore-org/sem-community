"""Regression for #575 — forecast missing from the "Forecast vs Actual" chart.

Root cause chain:
  1. The LitElement migration (e36b66f) replaced the apexcharts "Forecast vs
     Actual" card (forecast_power_now_w vs solar_power) with
     ``sem-chart-card preset: power`` — a solar/home/grid chart with NO forecast
     series. The forecast silently vanished; the card kept its title.
  2. #544 then removed ``forecast_power_now_w`` as a "dead orphan" — dead only
     because step 1 had already orphaned its sole consumer.

Fix: give the sensor a real consumer again (a dedicated ``forecast`` chart
preset) and repoint the card at it. These asserts pin every link in the chain
so neither the sensor nor the wiring can silently regress again.
"""
import json
import os
from unittest.mock import MagicMock

import yaml

from custom_components.solar_energy_management.coordinator.types import SEMData
from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastData,
    ForecastReader,
    SOLCAST_ENTITIES,
)
from custom_components.solar_energy_management.consts.labels import (
    SENSOR_LABEL_MAPPING,
)
from custom_components.solar_energy_management.sensor import SENSOR_TYPES

_ROOT = os.path.dirname(os.path.dirname(__file__))
_SENSOR = "forecast_power_now_w"


def test_forecast_power_now_is_published_sensor():
    """The sensor must be a real published entity (regressed away in #544)."""
    keys = {d.key for d in SENSOR_TYPES}
    assert _SENSOR in keys
    # forecast_power_next_hour_w stays removed — still an orphan, no consumer.
    assert "forecast_power_next_hour_w" not in keys


def test_forecast_power_now_in_state_dict():
    """Coordinator state must export it so the chart's history recorder sees it."""
    d = SEMData()
    d.forecast.forecast_power_now_w = 3210.0
    state = d.to_dict()
    assert state[_SENSOR] == 3210.0
    assert "forecast_power_next_hour_w" not in state


def test_forecast_power_now_in_reader_dict():
    """forecast_reader serialization must round-trip the value."""
    fd = ForecastData(power_now_w=4200.0, available=True)
    assert fd.to_dict()[_SENSOR] == 4200.0


def test_forecast_power_now_in_census():
    """Census/label map must list it (test_translations keys off this)."""
    assert _SENSOR in SENSOR_LABEL_MAPPING


def test_forecast_power_now_localized():
    """strings.json must name it, or HA renders a raw slug."""
    with open(os.path.join(_ROOT, "strings.json"), encoding="utf-8") as f:
        strings = json.load(f)
    assert _SENSOR in strings["entity"]["sensor"]


def test_forecast_card_uses_forecast_preset_not_power():
    """The bug itself: the 'Forecast vs Actual' card must plot a forecast.

    Before the fix it used ``preset: power`` — a duplicate of the "24h Power"
    chart with a misleading title and no forecast series.
    """
    path = os.path.join(_ROOT, "dashboard", "sem_dashboard_template.yaml")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # Locate the card block titled "Forecast vs Actual" and read the preset that
    # immediately precedes it (same list item).
    with open(path, encoding="utf-8") as f:
        raw_lines = f.readlines()
    title_idx = next(
        i for i, ln in enumerate(raw_lines) if "title: Forecast vs Actual" in ln
    )
    window = "".join(raw_lines[max(0, title_idx - 3):title_idx + 1])
    assert "preset: forecast" in window, window
    assert "preset: power" not in window, window


def test_forecast_preset_defined_in_card_bundle():
    """The 'forecast' preset must reference the forecast + actual series."""
    src = os.path.join(
        _ROOT, "dashboard", "card", "src", "cards", "sem-chart-card.js"
    )
    with open(src, encoding="utf-8") as f:
        js = f.read()
    assert "forecast:" in js
    assert _SENSOR in js
    assert "'solar_power'" in js or '"solar_power"' in js

    # And the built bundle that actually ships must contain it too.
    dist = os.path.join(_ROOT, "dashboard", "card", "dist", "sem-cards.js")
    with open(dist, encoding="utf-8") as f:
        assert _SENSOR in f.read()


# ──────────────────────────────────────────────────────────────────────
# #575 (round 2) — spurious dawn/dusk spikes in "Forecast vs Actual"
#
# After the chart was rewired, the reporter saw the forecast series spike
# to ~80 kW at ~05:00 and ~20:00 while midday peaked at ~8 kW. Root cause:
# forecast_reader multiplied any Solcast power reading < 100 by 1000,
# assuming kW. Solcast actually publishes Watts (UnitOfPower.WATT), so a
# real ~80 W dawn reading became 80 kW. Conversion is now unit-aware.
# ──────────────────────────────────────────────────────────────────────

def _power_state(value, unit):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    return s


def _solcast_reader(state):
    r = ForecastReader(hass=MagicMock())
    r._source = "solcast"
    r._entities = dict(SOLCAST_ENTITIES)
    r.hass.states.get = MagicMock(return_value=state)
    return r


def test_low_watt_dawn_reading_is_not_inflated():
    """A genuine 80 W dawn reading must stay 80 W — not ×1000 into a spike."""
    r = _solcast_reader(_power_state("80.0", "W"))
    data = r.read_forecast()
    assert data.power_now_w == 80.0
    assert data.power_next_hour_w == 80.0
    assert data.peak_power_today_w == 80.0
    assert r.get_diagnostics()["unit_conversion_count"] == 0


def test_watt_daytime_reading_unchanged():
    """Daytime W readings were always fine (> 100) and must stay fine."""
    r = _solcast_reader(_power_state("8000.0", "W"))
    data = r.read_forecast()
    assert data.power_now_w == 8000.0


def test_kw_source_is_converted_to_watts():
    """A source that truly declares kW is still converted deterministically."""
    r = _solcast_reader(_power_state("8.0", "kW"))
    data = r.read_forecast()
    assert data.power_now_w == 8000.0
    assert r.get_diagnostics()["unit_conversion_count"] == 3
