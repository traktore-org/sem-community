"""#1050 — Helios Forecast as a solar forecast source.

Proven on the integration's real output: the rig's ``helios_forecast``
capture is Helios Forecast 2026.9.6 set up in a Home Assistant test
instance, its weather from its own test helper (tests/integrations_rig/
PINS.md). One 10 kWp line, Zurich, 21 June 2026 at 12:00.

What the capture showed, and what the role map is built on:

* ``energy_day_1`` is TODAY — 31.32 kWh, today's 15-minute curve summed —
  so ``energy_day_3`` is SEM's day after tomorrow (Solcast's numbering
  trap, #884, does not apply);
* ``energy_today_remaining`` is the curve from now on, ``power_now`` the
  current slot;
* power next hour, peak power, peak time and day 3 ship DISABLED, which is
  "switched off", not "not published".
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)

from .integrations_rig.rig import load_capture, replay

DEV = "sensor.helios_forecast_"


async def _reader(hass, preferred=None) -> ForecastReader:
    await replay(hass, load_capture("helios_forecast"))
    return ForecastReader(hass, preferred_source=preferred)


def _enable(hass, entity_id, state, attrs=None):
    """What the user does in Home Assistant: switch a sensor on."""
    from homeassistant.helpers import entity_registry as er
    er.async_get(hass).async_update_entity(entity_id, disabled_by=None)
    hass.states.async_set(entity_id, state, attrs or {})


def _other_source(hass, platform, key, object_id, state):
    """One enabled sensor of another forecast integration."""
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=platform, title=platform)
    entry.add_to_hass(hass)
    row = er.async_get(hass).async_get_or_create(
        "sensor", platform, f"{entry.entry_id}_{key}",
        suggested_object_id=object_id, config_entry=entry)
    hass.states.async_set(row.entity_id, state)
    return row.entity_id


async def test_helios_is_found_and_read(hass):
    r = await _reader(hass)
    assert r.detect_source() == "helios"
    assert r._last_source_detection_path == "helios"
    data = r.read_forecast()
    assert data.source == "helios" and data.available
    assert data.forecast_today_kwh == pytest.approx(31.318, abs=0.01)
    assert data.forecast_tomorrow_kwh == pytest.approx(31.319, abs=0.01)
    assert data.forecast_remaining_today_kwh == pytest.approx(19.843, abs=0.01)
    assert data.power_now_w == pytest.approx(2607.8, abs=0.5)
    assert "helios" in data.sources_available


async def test_today_is_day_one_on_the_curve_helios_publishes(hass):
    """The role map rests on this: the 15-minute curve on ``power_now``,
    summed over today, is what ``energy_day_1`` says."""
    await replay(hass, load_capture("helios_forecast"))
    curve = hass.states.get(DEV + "power_now").attributes["forecast"]
    today = sum(p["watts"] for p in curve
                if p["datetime"].startswith("2026-06-21")) * 0.25 / 1000
    assert float(hass.states.get(DEV + "energy_day_1").state) == pytest.approx(
        today, abs=0.01)


async def test_switched_off_is_not_said_as_not_published(hass):
    r = await _reader(hass)
    data = r.read_forecast()
    assert data.forecast_d2_kwh == 0.0
    assert data.forecast_d2_path == "disabled_by_integration"
    assert data.peak_power_today_w == 0.0
    assert data.peak_power_path == "no_entity"  # not "unsupported_by_source"
    assert data.peak_time_today is None


async def test_switched_on_they_are_read(hass):
    await hass.config.async_set_time_zone("Europe/Zurich")
    await replay(hass, load_capture("helios_forecast"))
    _enable(hass, DEV + "energy_day_3", "29.5", {"unit_of_measurement": "kWh"})
    _enable(hass, DEV + "peak_power_day_1", "2700",
            {"unit_of_measurement": "W"})
    _enable(hass, DEV + "peak_time_day_1", "2026-06-21T11:30:00+00:00")
    data = ForecastReader(hass).read_forecast()
    assert data.forecast_d2_kwh == pytest.approx(29.5)
    assert data.forecast_d2_path == "read"
    assert data.peak_power_today_w == pytest.approx(2700)
    assert data.peak_power_path == "read"
    assert data.peak_time_today == "13:30"  # local, Europe/Zurich in summer


async def test_an_install_that_reads_another_source_keeps_it(hass):
    """Helios is tried last."""
    _other_source(hass, "open_meteo_solar_forecast",
                  "energy_production_today", "roof_energy_production_today",
                  "12.0")
    r = await _reader(hass)
    assert r.detect_source() == "open_meteo"
    assert set(r.available_sources()) == {"open_meteo", "helios"}


async def test_chosen_helios_outranks_the_ladder(hass):
    _other_source(hass, "open_meteo_solar_forecast",
                  "energy_production_today", "roof_energy_production_today",
                  "12.0")
    r = await _reader(hass, preferred="helios")
    assert r.detect_source() == "helios"
    assert r._last_source_detection_path == "preferred_helios"


async def test_helios_off_duty_says_nothing_about_the_source_in_use(hass):
    """Helios installed beside Open-Meteo, Open-Meteo in use: Helios's
    switched-off day 3 must not tell the user to switch on a sensor SEM is
    not reading."""
    _other_source(hass, "open_meteo_solar_forecast",
                  "energy_production_today", "roof_energy_production_today",
                  "12.0")
    r = await _reader(hass)
    data = r.read_forecast()
    assert data.source == "open_meteo"
    assert data.forecast_d2_path == "unsupported_by_source"
    # Open-Meteo publishes no peak power: that stays "not published".
    assert data.peak_power_path == "unsupported_by_source"


async def test_the_comparison_and_the_plane_list_include_helios(hass):
    r = await _reader(hass)
    r.detect_source()
    assert r.peek_sources()["helios"]["today_kwh"] == pytest.approx(31.318,
                                                                    abs=0.01)
    assert [p["name"] for p in r.plane_breakdown()] == ["Helios Forecast"]


async def test_a_renamed_helios_sensor_is_never_a_grid_meter(hass):
    """#911's guard by registry platform: an entry titled "Roof" names its
    sensors ``sensor.roof_*`` — no "forecast" left in the id to go by."""
    from custom_components.solar_energy_management.coordinator.sensor_reader import (
        SensorReader,
    )
    from homeassistant.helpers import entity_registry as er
    await replay(hass, load_capture("helios_forecast"))
    er.async_get(hass).async_update_entity(DEV + "power_now",
                                           new_entity_id="sensor.roof_power_now")
    probe = SimpleNamespace(
        hass=hass,
        _FORECAST_PLATFORMS=SensorReader._FORECAST_PLATFORMS,
        _FORECAST_NAME_MARKERS=SensorReader._FORECAST_NAME_MARKERS,
    )
    assert SensorReader._looks_like_a_forecast(probe, "sensor.roof_power_now")
