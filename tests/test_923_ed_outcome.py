"""#923 — "no Energy Dashboard" and "could not read it" are different answers.

read_energy_dashboard_config() returns None for both. That is fine for
reading sensors and wrong for deciding a battery is ABSENT (#925: "I could
not ask" is not "no"), so the oracle gets a sibling that keeps them apart."""
from __future__ import annotations

import importlib.util
import json
import os
from types import SimpleNamespace
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


_BATTERY = {"type": "battery",
            "stat_energy_from": "sensor.bat_out",
            "stat_energy_to": "sensor.bat_in"}


def _battery_file(tmp_path, **top):
    _write(tmp_path, json.dumps({
        "version": 1,
        "data": {"energy_sources": [_BATTERY], "device_consumption": []},
        **top,
    }))


def _no_derivation(monkeypatch):
    # The device-registry derivation needs a real hass; it is not what these
    # tests are about.
    monkeypatch.setattr(ha_energy_reader, "_derive_missing_power_sensors",
                        lambda hass, config: None)


_needs_real_hass = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)


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



# --- the file lags HA's energy manager by up to 60 s (#923 review C2) -------


@_needs_real_hass
@pytest.mark.asyncio
async def test_the_energy_manager_answers_before_the_file_is_written(hass):
    """A battery added in the Energy Dashboard is in HA's energy manager at
    once; ``.storage/energy`` follows up to 60 s later (``async_delay_save``),
    and the manager's update listeners run before that write. Reading only
    the file here answers "no battery" — the one false answer that later
    deletes a user's battery entities."""
    from homeassistant.components.energy.data import async_get_manager

    hass.config.components.add("energy")
    manager = await async_get_manager(hass)
    await manager.async_update({"energy_sources": [dict(_BATTERY)]})
    # The precondition that makes this a regression test: no file yet.
    assert not os.path.exists(os.path.join(hass.config.config_dir, ".storage", "energy"))

    config, answered = await read_energy_dashboard_config_outcome(hass)

    assert answered is True
    assert config is not None and config.has_battery is True


@_needs_real_hass
@pytest.mark.asyncio
async def test_an_energy_manager_holding_nothing_is_a_definite_no(hass):
    from homeassistant.components.energy.data import async_get_manager

    hass.config.components.add("energy")
    assert (await async_get_manager(hass)).data is None
    assert await read_energy_dashboard_config_outcome(hass) == (None, True)


@pytest.mark.asyncio
async def test_a_manager_that_cannot_be_had_falls_back_to_the_file(tmp_path, monkeypatch):
    from homeassistant.components.energy import data as energy_data

    async def _boom(hass):
        raise RuntimeError("energy manager unavailable")

    _no_derivation(monkeypatch)
    monkeypatch.setattr(energy_data, "async_get_manager", _boom)
    _battery_file(tmp_path)
    hass = _hass(tmp_path)
    hass.config.components = {"energy"}

    config, answered = await read_energy_dashboard_config_outcome(hass)

    assert answered is True
    assert config is not None and config.has_battery is True


@pytest.mark.asyncio
async def test_unreadable_manager_data_is_unanswered_not_the_file(tmp_path, monkeypatch):
    """A manager whose data SEM cannot parse is "could not ask" — and the
    file is not consulted instead: it can only be older than the manager."""
    from homeassistant.components.energy import data as energy_data

    async def _manager(hass):
        return SimpleNamespace(data={"energy_sources": {}, "device_consumption": []})

    _no_derivation(monkeypatch)
    monkeypatch.setattr(energy_data, "async_get_manager", _manager)
    _battery_file(tmp_path)
    hass = _hass(tmp_path)
    hass.config.components = {"energy"}

    assert await read_energy_dashboard_config_outcome(hass) == (None, False)


# --- only a missing file is an answer (#923 review I1, M4) ------------------


@pytest.mark.asyncio
async def test_an_error_after_parsing_is_unanswered(tmp_path, monkeypatch):
    def _boom(hass, config):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(ha_energy_reader, "_derive_missing_power_sensors", _boom)
    _battery_file(tmp_path)
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_file_of_another_version_is_unanswered(tmp_path, monkeypatch):
    _no_derivation(monkeypatch)
    _battery_file(tmp_path, version=2)
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_energy_sources_that_are_not_a_list_are_unanswered(tmp_path, monkeypatch):
    _no_derivation(monkeypatch)
    _write(tmp_path, json.dumps({"version": 1, "data": {
        "energy_sources": {}, "device_consumption": []}}))
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_opened_is_unanswered(tmp_path):
    """Only FileNotFoundError is "no dashboard"; any other OSError is not."""
    (tmp_path / ".storage" / "energy").mkdir(parents=True)
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_file_holding_json_null_is_unanswered(tmp_path):
    """The file exists — it is not the "no file" answer, whatever it holds."""
    _write(tmp_path, "null")
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)
