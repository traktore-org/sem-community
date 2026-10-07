"""#1020 A4 — a Home Assistant Schedule helper can set a device's mode.

A switch load or a charger may take ``schedule_entity`` (a Schedule helper)
and ``schedule_mode``. While the helper is on, that is the device's mode;
when it goes off, the stored mode applies again. The substitution happens
where the mode is READ — the stored mode is never written, so a restart, an
unavailable helper or a deleted one needs no restore. Batteries are not
devices with a mode here and are left out. No runtime deadline (D2 a).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from custom_components.solar_energy_management.consts.ev_charge_modes import (
    effective_charge_mode_for,
    mode_allows_night_charging,
)
from custom_components.solar_energy_management.devices.base import (
    ClimateDevice,
    DeviceControlMode,
    SwitchDevice,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

ROOT = Path(__file__).resolve().parents[1]
HELPER = "schedule.heat_rod_block"


def _heat_rod(hass):
    rod = SwitchDevice(hass, device_id="heat_rod", name="Heat rod",
                       rated_power=3000.0, entity_id="switch.heat_rod")
    rod.control_mode = DeviceControlMode.SURPLUS
    rod.schedule_entity = HELPER
    rod.schedule_mode = "off"
    return rod


async def test_the_heat_rod_is_off_while_the_schedule_runs(hass):
    """07:00–13:00 off, so the heat pump makes the hot water."""
    rod = _heat_rod(hass)
    hass.states.async_set(HELPER, "on")           # 08:00
    assert rod.control_mode == DeviceControlMode.OFF
    hass.states.async_set(HELPER, "off")          # 14:00
    assert rod.control_mode == DeviceControlMode.SURPLUS


@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
async def test_a_helper_that_does_not_answer_leaves_the_stored_mode(hass, state):
    rod = _heat_rod(hass)
    if state is not None:
        hass.states.async_set(HELPER, state)
    assert rod.control_mode == DeviceControlMode.SURPLUS


async def test_the_stored_mode_is_never_written(hass):
    rod = _heat_rod(hass)
    hass.states.async_set(HELPER, "on")
    assert rod.control_mode == DeviceControlMode.OFF
    assert rod.stored_control_mode == DeviceControlMode.SURPLUS
    # The user changes the mode while the schedule runs: that is the stored
    # mode, and it is the one that comes back.
    rod.control_mode = DeviceControlMode.PEAK_ONLY
    assert rod.control_mode == DeviceControlMode.OFF
    hass.states.async_set(HELPER, "off")
    assert rod.control_mode == DeviceControlMode.PEAK_ONLY


async def test_an_unknown_schedule_mode_is_no_mode(hass):
    rod = _heat_rod(hass)
    rod.schedule_mode = "turbo"
    hass.states.async_set(HELPER, "on")
    assert rod.control_mode == DeviceControlMode.SURPLUS


async def test_without_a_schedule_nothing_changes(hass):
    rod = SwitchDevice(hass, device_id="pump", name="Pump", rated_power=800.0)
    rod.control_mode = DeviceControlMode.SURPLUS
    assert rod.control_mode == DeviceControlMode.SURPLUS
    assert rod.schedule_entity == "" and rod.schedule_mode == ""


async def test_the_goals_carry_it_to_switch_loads_only(hass):
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg._device_goals = {
        "heat_rod": {"schedule_entity": HELPER, "schedule_mode": "off"},
        "ac": {"schedule_entity": HELPER, "schedule_mode": "off"},
    }
    rod = SwitchDevice(hass, device_id="heat_rod", name="Heat rod",
                       rated_power=3000.0)
    reg._apply_goals(rod)
    assert (rod.schedule_entity, rod.schedule_mode) == (HELPER, "off")
    ac = ClimateDevice(hass, device_id="ac", name="AC", rated_power=1500.0,
                       entity_id="climate.ac")
    reg._apply_goals(ac)
    assert ac.schedule_entity == ""
    for prop in ("schedule_entity", "schedule_mode"):
        assert prop in UnifiedDeviceRegistry.GOAL_PROPERTIES


# ── Chargers ─────────────────────────────────────────────────────────────

CHARGER = {"id": "keba", "charge_mode": "solar_plus_cheap",
           "schedule_entity": "schedule.weekend", "schedule_mode": "solar_only"}


async def test_a_charger_is_solar_only_at_the_weekend(hass):
    hass.states.async_set("schedule.weekend", "on")
    assert effective_charge_mode_for(hass, {}, CHARGER) == "solar_only"
    hass.states.async_set("schedule.weekend", "off")
    assert effective_charge_mode_for(hass, {}, CHARGER) == "solar_plus_cheap"


async def test_a_charger_schedule_with_an_unknown_mode_is_ignored(hass):
    hass.states.async_set("schedule.weekend", "on")
    cfg = {**CHARGER, "schedule_mode": "warp"}
    assert effective_charge_mode_for(hass, {}, cfg) == "solar_plus_cheap"


async def test_the_night_gate_sees_the_scheduled_mode(hass):
    """Stored Off — no night; the schedule makes it Min + Solar for the
    nights it runs."""
    cfg = {"id": "bike", "charge_mode": "off",
           "schedule_entity": "schedule.sunday", "schedule_mode": "min_plus_solar"}
    hass.states.async_set("schedule.sunday", "on")
    assert mode_allows_night_charging({}, cfg, hass) is True
    hass.states.async_set("schedule.sunday", "off")
    assert mode_allows_night_charging({}, cfg, hass) is False


def _calls(name):
    found = []
    skip = {"tests", "scripts", "node_modules", ".git", "__pycache__",
            "dist", "tools"}
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if set(rel.parts) & skip:
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call)
                    and getattr(n.func, "id", getattr(n.func, "attr", None)) == name):
                found.append((str(rel), n))
    return found


def test_every_mode_reader_can_see_the_schedule():
    """A reader that resolves the mode without ``hass`` cannot see a
    schedule: it would plan one mode while the charger runs another."""
    blind = []
    for rel, call in _calls("effective_charge_mode_for"):
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Constant) and first.value is None:
            blind.append(f"{rel}:{call.lineno}")
    for rel, call in _calls("mode_allows_night_charging"):
        if len(call.args) < 3 and not any(k.arg == "hass" for k in call.keywords):
            blind.append(f"{rel}:{call.lineno}")
    assert not blind, blind


def test_the_service_accepts_the_two_properties():
    src = (ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Every list of goal properties: the handler's tuple, the schema's list
    # and the one-call registration's tuple.
    lists = [n for n in ast.walk(tree)
             if isinstance(n, (ast.List, ast.Tuple))
             and any(isinstance(e, ast.Constant)
                     and e.value == "daily_min_runtime_min" for e in n.elts)]
    assert len(lists) >= 3
    for node in lists:
        values = {e.value for e in node.elts if isinstance(e, ast.Constant)}
        assert {"schedule_entity", "schedule_mode"} <= values


def test_a_charger_schedule_switching_replans():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )

    from .ast_contracts import calls
    assert calls(SEMCoordinator._energy_plan_demand_signature, "_ev_mode_now")
