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

from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    BATTERY_WIRING_KEYS, ENTITY_MODULES, Module, Presence, entity_kept,
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
    # Platforms do not agree on the shape, and changing one now would rename
    # an entity on every install — a migration, for nothing. numbers and
    # selects carry the entry id; switch/sensor/binary_sensor/button use the
    # bare ``sem_`` form. (#980 added the first select to this table.)
    if platform in ("number", "select"):
        return f"{entry.entry_id}_{'battery_capacity_kwh' if key == 'battery_capacity' else key}"
    return f"sem_{key}"


def _setting_gated_keys() -> set:
    """(#891) Entities that depend on a SETTING, not on hardware.

    This file's model is that a static description is either module-gated
    (absent when the module is) or core (always there). A third kind exists:
    the two house-meter sensors appear only when somebody names a house
    power sensor, which the module table cannot express.

    Read out of ``sensor.py``'s own gate rather than listed here — delete
    the gate and these stop being exempt, which is the point of deriving.
    """
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "sensor.py").read_text(encoding="utf-8")
    m = re.search(r'house_power_sensor.*?d\.key not in \(([^)]*)\)', src, re.S)
    return set(re.findall(r'"([a-z_0-9]+)"', m.group(1))) if m else set()

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
    setting_gated = _setting_gated_keys()
    wrong = []
    for platform, descriptions in _static_lists().items():
        for d in descriptions:
            if d.key in setting_gated:
                continue     # neither core nor module — see below
            is_module = (platform, d.key) in ENTITY_MODULES
            if _registered(hass, entry, platform, d.key) is is_module:
                wrong.append((platform, d.key, "exists" if is_module else "missing"))
    assert not wrong, wrong


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
    # (#996) the five capabilities ride along; a minimal install has none.
    assert diag["install_modules"] == {m.value: "absent" for m in Module}


@pytest.mark.asyncio
async def test_a_battery_and_ev_install_loses_nothing_it_has(
        hass, enable_custom_integrations, monkeypatch, sem_config_entry):
    _dashboard(monkeypatch)
    coordinator = await _setup(hass, sem_config_entry)
    presence = coordinator.setup_presence
    assert presence[Module.BATTERY] is Presence.PRESENT
    assert presence[Module.EV] is Presence.PRESENT
    wrong = []
    for platform, key in ENTITY_MODULES:
        # (#996) a row exists iff every module and capability it needs is
        # not ABSENT on this install — the same verdict the platforms read.
        expected = entity_kept(platform, key, presence)
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


def _charger(cid):
    return {
        "id": cid, "name": cid.upper(),
        "ev_connected_sensor": f"binary_sensor.{cid}_plug",
        "ev_charging_sensor": f"binary_sensor.{cid}_charging",
        "ev_charging_power_sensor": f"sensor.{cid}_power",
        "ev_charger_service": "number.set_value",
        "ev_charger_service_entity_id": f"number.{cid}_current",
        "ev_current_control_entity": f"number.{cid}_current",
        "min_current": 6, "max_current": 16, "vehicle_min_current": 6,
        "phases": 3, "voltage": 230, "charge_mode": "min_plus_solar",
        "daily_ev_target": 10, "daily_ev_target_max": 50,
        "ev_target_soc": 80, "ev_target_soc_max": 100,
        "ev_target_type": "kwh", "ev_target_time": "07:00", "ev_surplus_priority": 3,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("battery", [False, True])
async def test_per_charger_battery_to_ev_flows_follow_the_battery(
        hass, enable_custom_integrations, monkeypatch, battery):
    """(#923, found live on .175) The per-charger split of battery → EV is
    built per charger, outside the static list — it must follow the battery
    verdict like the fleet sensor does."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    _dashboard(monkeypatch)
    data = dict(MINIMAL_DATA, ev_chargers=[_charger("wb1"), _charger("wb2")])
    if battery:
        data["battery_soc_sensor"] = "sensor.test_battery_soc"
    entry = MockConfigEntry(domain=DOMAIN, version=12, minor_version=1, data=data,
                            options={}, title="SEM two chargers (#923)")
    await _setup(hass, entry)
    for cid in ("wb1", "wb2"):
        assert _registered(hass, entry, "sensor", f"charger_{cid}_flow_solar_to_ev_power")
        assert _registered(hass, entry, "sensor", f"charger_{cid}_flow_battery_to_ev_power") is battery
        assert _registered(hass, entry, "sensor", f"charger_{cid}_flow_battery_to_ev_energy") is battery
