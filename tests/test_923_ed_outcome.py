"""#923 — "no Energy Dashboard" and "could not read it" are different answers.

read_energy_dashboard_config() returns None for both. That is fine for
reading sensors and wrong for deciding a battery is ABSENT (#925: "I could
not ask" is not "no"), so the oracle gets a sibling that keeps them apart."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management import ha_energy_reader
from custom_components.solar_energy_management.ha_energy_reader import (
    read_energy_dashboard_config,
    read_energy_dashboard_config_outcome,
)


def _hass(tmp_path):
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)

    async def _executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor
    return hass


def _write(tmp_path, text):
    (tmp_path / ".storage").mkdir(exist_ok=True)
    (tmp_path / ".storage" / "energy").write_text(text, encoding="utf-8")


@pytest.mark.asyncio
async def test_a_missing_file_is_a_definite_no(tmp_path):
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, True)


@pytest.mark.asyncio
async def test_an_unparseable_file_is_unanswered(tmp_path):
    _write(tmp_path, "{not json")
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_file_without_data_is_unanswered(tmp_path):
    _write(tmp_path, json.dumps({"version": 1}))
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_parsed_file_answers_with_its_battery(tmp_path, monkeypatch):
    # The device-registry derivation needs a real hass; it is not what this
    # test is about.
    monkeypatch.setattr(ha_energy_reader, "_derive_missing_power_sensors",
                        lambda hass, config: None)
    _write(tmp_path, json.dumps({"data": {
        "energy_sources": [{"type": "battery",
                            "stat_energy_from": "sensor.bat_out",
                            "stat_energy_to": "sensor.bat_in"}],
        "device_consumption": [],
    }}))
    config, answered = await read_energy_dashboard_config_outcome(_hass(tmp_path))
    assert answered is True
    assert config is not None and config.has_battery is True


@pytest.mark.asyncio
async def test_the_old_reader_still_returns_only_the_config(tmp_path):
    assert await read_energy_dashboard_config(_hass(tmp_path)) is None
