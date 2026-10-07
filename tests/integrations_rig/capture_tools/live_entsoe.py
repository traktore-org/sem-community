"""Live capture: the REAL ENTSO-e integration (JaccoR/hass-entso-e), set up in
a Home Assistant test instance. Its one network call is answered with the
integration's OWN test datasets (``custom_components/entsoe/test/datasets``),
so its own parser, coordinator and sensors produce everything in the capture.

Run by hand from a checkout of JaccoR/hass-entso-e at the pinned commit:

    git clone https://github.com/JaccoR/hass-entso-e && cd hass-entso-e
    git checkout <PIN in PINS.md>
    mkdir -p tests && cp <this file> tests/test_zz_sem_capture.py
    SEM_RIG=<sem>/tests/integrations_rig PYTHONPATH=. python -m pytest \\
      -p no:cacheprovider -o asyncio_mode=auto tests/test_zz_sem_capture.py

Two captures, both at 14:07 local on 6 October 2024, when today's and
tomorrow's prices are both published:

* ``entsoe`` — what the config flow saves without advanced options: hourly,
  EUR/kWh, no entity name. DE-LU (``DE_60M_15M_overlap.xml``).
* ``entsoe_named_15m`` — 15-minute prices and an entity name, which the
  integration puts into every entity id and unique id. BE
  (``BE_60M_15M_mix.xml``).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

RIG = Path(os.environ["SEM_RIG"])
sys.path.insert(0, str(RIG / "capture_tools"))
from dump import capture_from_hass, write_capture  # noqa: E402

DATASETS = Path("custom_components/entsoe/test/datasets")

VARIANTS = {
    "entsoe": {"area": "DE", "period": "PT60M", "name": "",
               "dataset": "DE_60M_15M_overlap.xml", "tz": "Europe/Berlin"},
    "entsoe_named_15m": {"area": "BE", "period": "PT15M", "name": "Home",
                         "dataset": "BE_60M_15M_mix.xml",
                         "tz": "Europe/Brussels"},
}


@pytest.fixture(autouse=True)
def _custom(enable_custom_integrations):
    # The test instance's config dir is the plugin's own testing_config, whose
    # ``custom_components`` package shadows this checkout's: add ours to it.
    import custom_components
    here = str(Path("custom_components").resolve())
    if here not in custom_components.__path__:
        custom_components.__path__.append(here)
    yield


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.parametrize("capture", sorted(VARIANTS))
async def test_capture(hass, freezer, capture):
    v = VARIANTS[capture]
    # The integration's parser converts with a bare ``astimezone()`` — the
    # PROCESS time zone — and its coordinator buckets by Home Assistant's.
    # A real install has both on the house's zone.
    os.environ["TZ"] = v["tz"]
    time.tzset()
    await hass.config.async_set_time_zone(v["tz"])
    freezer.move_to("2024-10-06T12:07:00+00:00")  # 14:07 CEST

    xml = (DATASETS / v["dataset"]).read_text()

    async def _answer(self, params, start, end):
        return xml

    # A fixed entry id: it is part of the device identifier, so a refresh
    # changes the capture only where the integration's output changed.
    entry = MockConfigEntry(
        domain="entsoe", entry_id=f"rig_{capture}",
        title=v["name"] or "ENTSO-e", data={},
        options={"api_key": "rig", "area": v["area"], "period": v["period"],
                 "modifyer": "{{current_price}}", "currency": "EUR",
                 "energy_scale": "kWh", "advanced_options": False,
                 "VAT_value": 0, "name": v["name"],
                 "calculation_mode": "publish"})
    entry.add_to_hass(hass)
    with patch("custom_components.entsoe.api_client.EntsoeClient._base_request",
               _answer):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    cap = capture_from_hass(
        hass, "entsoe",
        source={"kind": "live-load", "repo": "JaccoR/hass-entso-e",
                "commit": commit,
                "data": f"the integration's own test/datasets/{v['dataset']} "
                        f"as the API's answer, area {v['area']}, period "
                        f"{v['period']}, name {v['name']!r}, at 2024-10-06 "
                        f"14:07 {v['tz']}"},
        services_yaml=Path("custom_components/entsoe/services.yaml"))
    assert cap["entities"]
    write_capture(cap, RIG / "captures" / f"{capture}.json")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
