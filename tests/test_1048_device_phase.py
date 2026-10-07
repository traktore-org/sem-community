"""#1048 C1 — a load knows which phase it is on (D6: a per-device attribute).

RienduPre's house trips a 23 A limit on L3 while L1 and L2 have room. The
phase guard (C2) can only shed the RIGHT loads if it knows where they sit, and
SEM cannot see a wiring diagram — so the user says it, per load:

* ``phase`` ∈ L1 / L2 / L3 / 3ph / unknown, default ``unknown``;
* stored with the device's other settings (the registry's goals) and carried
  on the load manager's row, where the shed path reads it;
* a charger's phase is MEASURED — the held belief from its own W/A (#804),
  else the nameplate — and shown, never set.

Learning a load's phase from phase-current correlation (D6 b) can follow once
this attribute gives it ground truth.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.consts.devices import (
    DEFAULT_LOAD_PHASE,
    LOAD_PHASES,
    is_load_phase,
    load_phase,
)
from custom_components.solar_energy_management.devices.base import SwitchDevice
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDevice,
    UnifiedDeviceRegistry,
)

ROOT = Path(__file__).resolve().parents[1]


# ── The word ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, phase", [
    ("L1", "L1"), ("l2", "L2"), (" L3 ", "L3"), ("3ph", "3ph"), ("3", "3ph"),
    ("unknown", "unknown"), (None, "unknown"), ("", "unknown"),
    ("L4", "unknown"), ("phase 3", "unknown"), (3.0, "unknown"),
])
def test_a_stored_value_names_a_phase_or_none(value, phase):
    assert load_phase(value) == phase


def test_the_service_takes_the_five_words_exactly():
    assert LOAD_PHASES == ("L1", "L2", "L3", "3ph", "unknown")
    assert all(is_load_phase(p) for p in LOAD_PHASES)
    for typo in ("l1", "L4", "3", "", None):
        assert not is_load_phase(typo)


def test_a_device_starts_on_an_unknown_phase():
    dev = SwitchDevice(MagicMock(), device_id="pool", name="Pool pump",
                       rated_power=1500.0)
    assert dev.phase == DEFAULT_LOAD_PHASE == "unknown"


# ── The registry carries it to the shedder ───────────────────────────────

def _reg(goals=None, registered=()):
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    sc = MagicMock()
    sc.get_device = MagicMock(
        side_effect=lambda d: MagicMock() if d in registered else None)
    reg._surplus_controller = sc
    lm = MagicMock()
    lm._devices = {}
    reg._load_manager = lm
    reg._service_registrations = {}
    reg._control_mode_overrides = {}
    reg._dependency_overrides = {}
    reg._get_power_rating = MagicMock(return_value=1000.0)
    reg._device_goals = dict(goals or {})
    reg._goal_write_lock = asyncio.Lock()
    reg._save_storage = AsyncMock()
    return reg


POOL = "energy_dashboard_pool_heat_pump"
HP = "energy_dashboard_heat_pump"


def _devices():
    return [
        UnifiedDevice(energy_sensor="sensor.pool_heat_pump_energy",
                      power_sensor=None, name="Pool heat pump", priority=7,
                      control={"type": "switch", "entity": "switch.pool_hp"}),
        UnifiedDevice(energy_sensor="sensor.heat_pump_energy",
                      power_sensor=None, name="Heat pump", priority=3,
                      control={"type": "switch", "entity": "switch.hp"}),
    ]


def test_the_load_managers_row_carries_the_phase():
    reg = _reg(goals={POOL: {"phase": "L3"}})
    reg._devices = _devices()
    reg._sync_to_load_manager()
    rows = reg._load_manager._devices
    assert rows[POOL]["phase"] == "L3"
    assert rows[HP]["phase"] == "unknown", "unset is unknown, never a guess"


def test_a_service_registered_load_carries_it_too():
    reg = _reg(goals={"pool_pump": {"phase": "L2"}})
    row = reg._service_lm_row("pool_pump", {"name": "Pool pump",
                                            "entity_id": "switch.pool"})
    assert row["phase"] == "L2"


@pytest.mark.asyncio
async def test_setting_it_reaches_the_shedder_at_once():
    """Not at the next registry sync (up to 35 s): a phase over its limit
    is shed on the cycle after the user said where the load sits."""
    reg = _reg()
    reg._load_manager._devices[POOL] = {"phase": "unknown"}
    await reg.async_update_device_goal(POOL, "phase", "L3")
    assert reg._load_manager._devices[POOL]["phase"] == "L3"
    assert reg._device_goals[POOL]["phase"] == "L3"
    reg._save_storage.assert_awaited()


def test_the_live_device_gets_it_and_an_unset_one_keeps_unknown():
    reg = _reg(goals={"pool": {"phase": "3ph"}, "pump": {"daily_min_runtime_min": 30}})
    pool = SwitchDevice(MagicMock(), device_id="pool", name="Pool", rated_power=1500.0)
    pump = SwitchDevice(MagicMock(), device_id="pump", name="Pump", rated_power=800.0)
    reg._apply_goals(pool)
    reg._apply_goals(pump)
    assert pool.phase == "3ph"
    assert pump.phase == "unknown"


def test_the_card_reads_it_with_the_other_settings():
    reg = _reg(goals={POOL: {"phase": "L3"}})
    assert reg._goal_payload(POOL)["goals"]["phase"] == "L3"
    assert reg._goal_payload(HP)["goals"]["phase"] == "unknown"
    assert "phase" in UnifiedDeviceRegistry.GOAL_PROPERTIES


# ── A charger's phase is measured ────────────────────────────────────────

def _coordinator(believed=None, phases=3):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = None
    c._ev_devices = {"keba": SimpleNamespace(
        name="KEBA", priority=3, phases=phases, voltage=230,
        max_current=16, min_current=6)}
    c._last_ev_connected_per_charger = {"keba": True}
    c._phase_believed = {"keba": believed} if believed else {}
    return c


@pytest.mark.parametrize("believed, nameplate, phase, measured", [
    (None, 3, "3ph", False),        # nothing measured yet: the nameplate
    (3, 1, "3ph", True),            # the car draws on three
    (1, 3, "unknown", True),        # one phase — which line, nobody knows
    (None, 1, "unknown", False),
])
def test_a_charger_takes_its_measured_phases(believed, nameplate, phase, measured):
    row = _coordinator(believed, nameplate)._charger_priority_rows()[0]
    assert (row["phase"], row["phase_measured"]) == (phase, measured)
    reg = _reg()
    payload = reg._ev_charger_row({"id": "keba", **row})
    assert (payload["phase"], payload["phase_measured"]) == (phase, measured)


# ── The service ──────────────────────────────────────────────────────────

def test_every_property_list_accepts_it():
    """The handler's goal tuple, the schema's property list and the one-call
    registration's tuple — a property missing from one is refused by it."""
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    lists = [n for n in ast.walk(tree)
             if isinstance(n, (ast.List, ast.Tuple))
             and any(isinstance(e, ast.Constant)
                     and e.value == "daily_min_runtime_min" for e in n.elts)]
    assert len(lists) >= 3
    for node in lists:
        assert any(isinstance(e, ast.Constant) and e.value == "phase"
                   for e in node.elts), ast.unparse(node)[:120]


def _seed(hass):
    for eid, val, unit in (
        ("sensor.test_grid_power", "0", "W"),
        ("sensor.test_battery_power", "0", "W"),
        ("sensor.test_battery_soc", "50", "%"),
        ("sensor.test_solar_power", "0", "W"),
        ("sensor.test_ev_total_energy", "0", "kWh"),
        ("sensor.test_ev_charging_power", "0", "W"),
        ("number.test_charger_current", "0", "A"),
    ):
        hass.states.async_set(eid, val, {"unit_of_measurement": unit})
    hass.states.async_set("binary_sensor.test_ev_connected", "off")
    hass.states.async_set("binary_sensor.test_ev_charging", "off")
    hass.states.async_set("switch.pool_pump", "on")


@pytest.mark.asyncio
async def test_the_service_stores_a_phase_and_refuses_a_typo(
        sem_real_hass, sem_config_entry):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.solar_energy_management.const import DOMAIN
    _seed(sem_real_hass)
    sem_config_entry.add_to_hass(sem_real_hass)
    assert await sem_real_hass.config_entries.async_setup(sem_config_entry.entry_id)
    await sem_real_hass.async_block_till_done()
    await sem_real_hass.services.async_call(
        DOMAIN, "register_surplus_device",
        {"device_id": "pool_pump", "name": "Pool pump",
         "entity_id": "switch.pool_pump", "rated_power": 1500,
         "control_mode": "peak_only", "phase": "L1"},
        blocking=True)
    registry = sem_config_entry.runtime_data._device_registry
    assert registry.phase_for("pool_pump") == "L1"
    await sem_real_hass.services.async_call(
        DOMAIN, "update_device_config",
        {"device_id": "pool_pump", "property": "phase", "value": "L3"},
        blocking=True)
    assert registry.phase_for("pool_pump") == "L3"
    with pytest.raises(ServiceValidationError) as err:
        await sem_real_hass.services.async_call(
            DOMAIN, "update_device_config",
            {"device_id": "pool_pump", "property": "phase", "value": "L4"},
            blocking=True)
    assert err.value.translation_key == "invalid_device_property"
    assert registry.phase_for("pool_pump") == "L3"


def test_the_card_strings_are_in_every_language():
    import json
    import re
    tables = json.loads((ROOT / "dashboard" / "translations.json")
                        .read_text(encoding="utf-8"))
    keys = ("load_phase_label", "load_phase_tooltip", "load_phase_unknown",
            "load_phase_3ph", "load_phase_measured_hint", "shed_phase")
    for lang, table in tables.items():
        for key in keys:
            assert table.get(key), (lang, key)
            want = set(re.findall(r"\{(\w+)\}", tables["en"][key]))
            assert set(re.findall(r"\{(\w+)\}", table[key])) == want, (lang, key)
    src = (ROOT / "dashboard" / "card" / "src" / "cards"
           / "sem-load-priority-card.js").read_text(encoding="utf-8")
    assert set(re.findall(r"'(load_phase_[a-z_0-9]+)'", src)) <= set(keys)
