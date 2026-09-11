"""#923 — each platform builds only the entities of modules the install has,
and its stale-entity sweep (fed the SAME gated list) removes an ABSENT
module's leftovers from the registry. UNKNOWN keeps everything.

Real registry (the ``hass`` fixture), test-double coordinator: the platform
setup is called directly, so nothing else of SEM needs to load."""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.solar_energy_management import (  # noqa: E402
    binary_sensor, button, number, select, switch,
)
from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    Module, Presence,
)

ALL_ABSENT = {m: Presence.ABSENT for m in Module}
ALL_PRESENT = {m: Presence.PRESENT for m in Module}


def _entry(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, title="SEM #923")
    entry.add_to_hass(hass)
    return entry


def _coordinator(hass, entry, presence):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass.config.currency = "EUR"
    coordinator.setup_presence = presence
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def _run(platform_module, hass, entry):
    added: list = []
    await platform_module.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    return {e.entity_description.key for e in added}


def _seed(hass, entry, platform, unique_id):
    er.async_get(hass).async_get_or_create(
        platform, DOMAIN, unique_id, config_entry=entry)


def _exists(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id) is not None


@pytest.mark.asyncio
async def test_binary_sensor_builds_the_core_and_sweeps_an_absent_module(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_ABSENT)
    _seed(hass, entry, "binary_sensor", "sem_battery_charging")
    _seed(hass, entry, "binary_sensor", "sem_solar_active")
    keys = await _run(binary_sensor, hass, entry)
    assert "solar_active" in keys
    assert not {"battery_charging", "ev_connected", "heat_pump_registered"} & keys
    assert not _exists(hass, "binary_sensor", "sem_battery_charging")
    assert _exists(hass, "binary_sensor", "sem_solar_active")


@pytest.mark.asyncio
async def test_binary_sensor_unknown_keeps_everything(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, {m: Presence.UNKNOWN for m in Module})
    _seed(hass, entry, "binary_sensor", "sem_battery_charging")
    keys = await _run(binary_sensor, hass, entry)
    assert "battery_charging" in keys
    assert _exists(hass, "binary_sensor", "sem_battery_charging")


@pytest.mark.asyncio
async def test_number_drops_the_battery_and_its_legacy_unique_id(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_ABSENT)
    _seed(hass, entry, "number", f"{entry.entry_id}_battery_capacity_kwh")
    keys = await _run(number, hass, entry)
    assert "battery_capacity" not in keys
    assert "hot_water_solar_target" not in keys
    assert "night_earliest_start" in keys
    # The legacy map used to keep this unique_id valid unconditionally.
    assert not _exists(hass, "number", f"{entry.entry_id}_battery_capacity_kwh")


@pytest.mark.asyncio
async def test_number_keeps_the_battery_when_present(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_PRESENT)
    _seed(hass, entry, "number", f"{entry.entry_id}_battery_capacity_kwh")
    keys = await _run(number, hass, entry)
    assert {"battery_capacity", "battery_assist_max_power"} <= keys
    assert _exists(hass, "number", f"{entry.entry_id}_battery_capacity_kwh")


@pytest.mark.asyncio
async def test_switch_cross_module_follows_both(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, {**ALL_PRESENT, Module.EV: Presence.ABSENT})
    _seed(hass, entry, "switch", "sem_battery_may_assist_ev")
    keys = await _run(switch, hass, entry)
    assert "battery_may_export" in keys
    assert "battery_may_assist_ev" not in keys
    assert not _exists(hass, "switch", "sem_battery_may_assist_ev")


@pytest.mark.asyncio
async def test_button_is_a_battery_entity_and_is_swept(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_ABSENT)
    _seed(hass, entry, "button", "sem_backfill_battery_nights")
    keys = await _run(button, hass, entry)
    assert keys == set()
    assert not _exists(hass, "button", "sem_backfill_battery_nights")


def test_the_global_battery_select_asks_the_oracle():
    coordinator = MagicMock()
    coordinator.setup_presence = ALL_ABSENT
    assert select._has_battery(coordinator) is False
    coordinator.setup_presence = {m: Presence.UNKNOWN for m in Module}
    assert select._has_battery(coordinator) is True
