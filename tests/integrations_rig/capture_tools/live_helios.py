"""Live capture: the REAL Helios Forecast integration (ReikanYsora/Helios-Forecast),
set up in a Home Assistant test instance by the same path its own entry tests
take (``tests/ha/test_init.py``): ``fetch_weather`` answered by its OWN
synthetic weather helper (``tests/ha/_weather.py``), everything else real —
its coordinator, its model, its sensor platform.

Run by hand from a checkout of ReikanYsora/Helios-Forecast at the pinned tag:

    git clone https://github.com/ReikanYsora/Helios-Forecast && cd Helios-Forecast
    git checkout <PIN in PINS.md>
    cp <this file> tests/ha/test_zz_sem_capture.py
    SEM_RIG=<sem>/tests/integrations_rig PYTHONPATH=. python -m pytest \\
      -p no:cacheprovider -o asyncio_mode=auto tests/ha/test_zz_sem_capture.py

The entry is what the config flow saves for one panel line (10 kWp facing
south at 30°, the shape of its own ``tests/test_checkup.py`` line) under its
default title "Helios Forecast", at the home's location, on 21 June 2026 at
12:00 Zurich time. Sensors Helios ships disabled stay disabled: the capture is
what an install has before the user changes anything.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.helios_forecast.coordinator as coordinator_mod
from homeassistant.util import dt as dt_util

from _weather import make_weather_series

RIG = Path(os.environ["SEM_RIG"])
sys.path.insert(0, str(RIG / "capture_tools"))
from dump import capture_from_hass, write_capture  # noqa: E402


@pytest.fixture(autouse=True)
def _custom(recorder_mock, enable_custom_integrations):
    # Helios depends on the recorder, which must exist before ``hass`` does:
    # hence ``recorder_mock`` first.
    # The test instance's config dir is the plugin's own testing_config, whose
    # ``custom_components`` package shadows this checkout's: add ours to it.
    import custom_components
    here = str(Path("custom_components").resolve())
    if here not in custom_components.__path__:
        custom_components.__path__.append(here)
    yield


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_capture(hass, freezer, monkeypatch):
    await hass.config.async_set_time_zone("Europe/Zurich")
    hass.config.latitude, hass.config.longitude = 47.38, 8.54
    freezer.move_to("2026-06-21T10:00:00+00:00")  # 12:00 CEST

    weather = make_weather_series(dt_util.utcnow())
    monkeypatch.setattr(coordinator_mod, "fetch_weather",
                        AsyncMock(return_value=weather))
    # A fixed entry id: it is part of every unique id, so a refresh changes
    # the capture only where the integration's output changed.
    entry = MockConfigEntry(domain="helios_forecast", entry_id="rig_helios",
                            title="Helios Forecast",
                            data={"arrays": [{"azimuth": 180.0, "tilt": 30.0,
                                              "kwp": 10.0, "tracker": "none"}]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    tag = subprocess.run(["git", "describe", "--tags", "--exact-match"],
                         capture_output=True, text=True).stdout.strip()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    cap = capture_from_hass(
        hass, "helios_forecast",
        source={"kind": "live-load", "repo": "ReikanYsora/Helios-Forecast",
                "tag": tag, "commit": commit,
                "data": "the integration's own tests/ha/_weather.py "
                        "make_weather_series as Open-Meteo's answer; one "
                        "panel line, 10 kWp south 30 deg; Zurich, 2026-06-21 "
                        "12:00 Europe/Zurich"},
        services_yaml=Path("custom_components/helios_forecast/services.yaml"))
    assert cap["entities"]
    write_capture(cap, RIG / "captures" / "helios_forecast.json")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
