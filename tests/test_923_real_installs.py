"""#923 — real Home Assistant, real SEM setup, real registry.

None of our three machines runs the ABSENT path by default, which is why a
minimal install is part of the work (spec §9)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

import yaml  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    BATTERY_WIRING_KEYS, ENTITY_MODULES, Module, Presence,
)

COORDINATOR_MODULE = "custom_components.solar_energy_management.coordinator.coordinator"
TEMPLATE = Path(__file__).resolve().parents[1] / "dashboard" / "sem_dashboard_template.yaml"

MINIMAL_DATA = {
    "grid_power_sensor": "sensor.test_grid_power",
    "solar_power_sensor": "sensor.test_solar_power",
    "min_solar_power": 1000,
    "peak_load": 6000,
    "update_interval": 30,
    "electricity_import_rate": 0.30,
    "electricity_export_rate": 0.08,
}


def _static_lists():
    from custom_components.solar_energy_management.binary_sensor import BINARY_SENSOR_TYPES
    from custom_components.solar_energy_management.button import BUTTONS
    from custom_components.solar_energy_management.number import NUMBER_TYPES
    from custom_components.solar_energy_management.sensor import SENSOR_TYPES
    from custom_components.solar_energy_management.switch import SWITCH_TYPES
    return {"sensor": SENSOR_TYPES, "number": NUMBER_TYPES, "switch": SWITCH_TYPES,
            "binary_sensor": BINARY_SENSOR_TYPES, "button": BUTTONS}


def _dashboard(monkeypatch, config=None, answered=True):
    monkeypatch.setattr(
        f"{COORDINATOR_MODULE}.read_energy_dashboard_config_outcome",
        AsyncMock(return_value=(config, answered)))


def _minimal_entry():
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    return MockConfigEntry(domain=DOMAIN, version=12, minor_version=1,
                           data=dict(MINIMAL_DATA), options={},
                           title="SEM minimal (#923)")


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _uid(entry, platform, key):
    if platform == "number":
        return f"{entry.entry_id}_{'battery_capacity_kwh' if key == 'battery_capacity' else key}"
    return f"sem_{key}"


def _registered(hass, entry, platform, key):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, _uid(entry, platform, key)) is not None


@pytest.mark.asyncio
async def test_a_minimal_install_builds_the_core_and_nothing_else(
        hass, enable_custom_integrations, monkeypatch):
    _dashboard(monkeypatch)
    entry = _minimal_entry()
    coordinator = await _setup(hass, entry)
    assert coordinator.setup_presence == {m: Presence.ABSENT for m in Module}
    wrong = []
    for platform, descriptions in _static_lists().items():
        for d in descriptions:
            is_module = (platform, d.key) in ENTITY_MODULES
            if _registered(hass, entry, platform, d.key) is is_module:
                wrong.append((platform, d.key, "exists" if is_module else "missing"))
    assert not wrong, wrong


@pytest.mark.asyncio
async def test_the_minimal_dashboard_has_no_battery_or_ev_tab(
        hass, enable_custom_integrations, monkeypatch):
    from custom_components.solar_energy_management.features.dashboard_generator import (
        DashboardGenerator,
    )
    _dashboard(monkeypatch)
    await _setup(hass, _minimal_entry())
    tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    DashboardGenerator(hass)._prune_absent_modules(tpl)
    assert {"battery", "ev"}.isdisjoint(v.get("path") for v in tpl["views"])


@pytest.mark.asyncio
async def test_the_diagnostics_carry_the_verdict(
        hass, enable_custom_integrations, monkeypatch):
    from custom_components.solar_energy_management.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    _dashboard(monkeypatch)
    entry = _minimal_entry()
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["install_modules"] == {
        "battery": "absent", "ev": "absent", "heat_pump": "absent", "hot_water": "absent"}


@pytest.mark.asyncio
async def test_a_battery_and_ev_install_loses_nothing_it_has(
        hass, enable_custom_integrations, monkeypatch, sem_config_entry):
    _dashboard(monkeypatch)
    await _setup(hass, sem_config_entry)
    wrong = []
    for (platform, key), modules in ENTITY_MODULES.items():
        expected = modules <= {Module.BATTERY, Module.EV}
        if _registered(hass, sem_config_entry, platform, key) is not expected:
            wrong.append((platform, key, "expected" if expected else "unexpected"))
    assert not wrong, wrong


@pytest.mark.asyncio
async def test_removing_the_battery_removes_its_entities_on_reload(
        hass, enable_custom_integrations, monkeypatch, sem_config_entry):
    _dashboard(monkeypatch)
    await _setup(hass, sem_config_entry)
    assert _registered(hass, sem_config_entry, "sensor", "battery_soc")

    def _without_battery(d):
        return {k: v for k, v in d.items() if k not in BATTERY_WIRING_KEYS}

    hass.config_entries.async_update_entry(
        sem_config_entry,
        data=_without_battery(sem_config_entry.data),
        options=_without_battery(sem_config_entry.options))
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    assert sem_config_entry.runtime_data.setup_presence[Module.BATTERY] is Presence.ABSENT
    for platform, key in [("sensor", "battery_soc"), ("number", "battery_capacity"),
                          ("binary_sensor", "battery_charging"),
                          ("button", "backfill_battery_nights"),
                          ("switch", "battery_may_assist_ev")]:
        assert not _registered(hass, sem_config_entry, platform, key), (platform, key)
    assert _registered(hass, sem_config_entry, "sensor", "ev_power")


@pytest.mark.asyncio
async def test_an_unreadable_dashboard_hides_nothing(
        hass, enable_custom_integrations, monkeypatch):
    _dashboard(monkeypatch, None, answered=False)
    entry = _minimal_entry()
    coordinator = await _setup(hass, entry)
    assert coordinator.setup_presence[Module.BATTERY] is Presence.UNKNOWN
    assert _registered(hass, entry, "sensor", "battery_soc")
    assert _registered(hass, entry, "sensor", "ev_power")
    # Heat pump lives only in SEM's options — never UNKNOWN.
    assert not _registered(hass, entry, "sensor", "heat_pump_mode")
