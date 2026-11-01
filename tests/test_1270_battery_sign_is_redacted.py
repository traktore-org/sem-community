"""#1270 — the battery-sign block of a diagnostics download listed the
battery sensor and counter entity ids in the clear, while the config section
of the same file redacts them. One rule for the whole file."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_diagnostics import coordinator, entry, mock_hass  # noqa: F401

_IDS = (
    "sensor.my_battery_power", "sensor.my_charge_kwh",
    "sensor.my_discharge_kwh", "sensor.my_second_pack_power",
)


def _block():
    return {
        "battery_power_sensor": _IDS[0],
        "battery_power_raw_state": "-750",
        "battery_platform": "huawei_solar",
        "user_flip": False,
        "per_bid": {"battery_1": {
            "detected": True, "inverted": False, "evidence": 4.0,
            "samples": 20, "counters": [_IDS[1], _IDS[2]],
            "sensor": _IDS[3],
        }},
        "charge_counters": [_IDS[1]],
        "discharge_counters": [_IDS[2]],
    }


@pytest.mark.asyncio
async def test_no_battery_entity_id_reaches_the_file(mock_hass, entry, coordinator):  # noqa: F811
    reader = MagicMock()
    reader.battery_sign_diagnostics.return_value = _block()
    coordinator._sensor_reader = reader
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    out = (await async_get_config_entry_diagnostics(mock_hass, entry))["battery_sign"]
    assert not [i for i in _IDS if i in str(out)]


@pytest.mark.asyncio
async def test_the_readable_facts_stay(mock_hass, entry, coordinator):  # noqa: F811
    reader = MagicMock()
    reader.battery_sign_diagnostics.return_value = _block()
    coordinator._sensor_reader = reader
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    out = (await async_get_config_entry_diagnostics(mock_hass, entry))["battery_sign"]
    assert out["battery_platform"] == "huawei_solar"
    assert out["battery_power_raw_state"] == "-750"
    assert out["per_bid"]["battery_1"]["samples"] == 20
    assert out["per_bid"]["battery_1"]["detected"] is True
