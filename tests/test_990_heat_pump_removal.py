"""#990 — removing the last additional heat pump must STICK.

@RienduPre: "Cannot remove second heatpump using config flow UI" — the
Remove row is offered, accepted, and the pump is still on the menu.

``self._data`` is the DRAFT this dialog is building; ``entry.options`` is
what is saved. The menu resolved the two with ``or``, and ``or`` cannot
tell "the flow has not touched the list" from "the user just emptied it"
— both are falsy. Removing the ONLY additional pump writes ``[]`` into
the draft, which the very next read discards in favour of the saved copy.
The one state that means "removed" is the one state the resolver cannot
represent.
"""
from __future__ import annotations

from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _flow_self(data=None, options=None):
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    stub = SimpleNamespace(
        _data=dict(data or {}),
        config_entry=SimpleNamespace(data={}, options=dict(options or {})),
        _edit_hp_index=None,
        shown=None,
    )
    def async_show_form(self, **kw):
        self.shown = kw
        return {"type": "form", **kw}
    stub.async_show_form = MethodType(async_show_form, stub)
    for name in ("async_step_heat_pump_menu", "async_step_heat_pump_unit"):
        setattr(stub, name, MethodType(getattr(OptionsFlowHandler, name), stub))
    stub.async_step_battery_scheduler = AsyncMock(return_value={"type": "next"})
    return stub


def _menu_values(form):
    return [o["value"] for o in
            form["data_schema"].schema["action"].config["options"]]


SAVED_ONE = {"heat_pumps": [
    {"id": "heat_pump_2", "name": "Cellar",
     "heat_pump_climate_entity": "climate.cellar"}]}


@pytest.mark.asyncio
async def test_removing_the_only_saved_pump_is_gone_from_the_next_menu():
    """The reporter's gesture: one additional pump, saved, remove it."""
    f = _flow_self(options=SAVED_ONE)
    await f.async_step_heat_pump_menu({"action": "remove_heat_pump:0"})
    assert f._data["heat_pumps"] == []
    form = f.shown                       # the menu re-rendered by the remove
    assert _menu_values(form) == ["continue", "add_heat_pump"]
    label = form["data_schema"].schema["action"].config["options"][0]["label"]
    assert "1 heat pump" in label


@pytest.mark.asyncio
async def test_a_second_remove_press_cannot_resurrect_it():
    f = _flow_self(options=SAVED_ONE)
    await f.async_step_heat_pump_menu({"action": "remove_heat_pump:0"})
    await f.async_step_heat_pump_menu(None)
    assert _menu_values(f.shown) == ["continue", "add_heat_pump"]
    assert f._data["heat_pumps"] == []


@pytest.mark.asyncio
async def test_adding_after_the_removal_starts_from_empty():
    """The resurrected row must not come back as a phantom sibling."""
    f = _flow_self(options=SAVED_ONE)
    await f.async_step_heat_pump_menu({"action": "remove_heat_pump:0"})
    await f.async_step_heat_pump_unit({"heat_pump_climate_entity": "climate.attic"})
    pumps = f._data["heat_pumps"]
    assert len(pumps) == 1
    assert pumps[0]["heat_pump_climate_entity"] == "climate.attic"
    # (#1421) not the removed pump's heat_pump_2: SEM keeps its data under it
    assert pumps[0]["id"] == "heat_pump_3"


@pytest.mark.asyncio
async def test_removing_one_of_two_still_works():
    f = _flow_self(options={"heat_pumps": [
        {"id": "heat_pump_2", "name": "Cellar"},
        {"id": "heat_pump_3", "name": "Attic"}]})
    await f.async_step_heat_pump_menu({"action": "remove_heat_pump:0"})
    assert [p["id"] for p in f._data["heat_pumps"]] == ["heat_pump_3"]
    assert _menu_values(f.shown) == [
        "continue", "edit_heat_pump:0", "remove_heat_pump:0", "add_heat_pump"]


@pytest.mark.asyncio
async def test_an_untouched_draft_still_reads_the_saved_list():
    """The fallback itself is correct — only the EMPTY draft was wrong."""
    f = _flow_self(options=SAVED_ONE)
    await f.async_step_heat_pump_menu(None)
    assert _menu_values(f.shown) == [
        "continue", "edit_heat_pump:0", "remove_heat_pump:0", "add_heat_pump"]


# ── the sibling: the EV list resolves the same way ──────────────────

@pytest.mark.asyncio
async def test_the_ev_charger_list_honours_an_empty_draft_too():
    """Same resolver, same rule — a draft the flow emptied is the answer."""
    from custom_components.solar_energy_management.config_flow import _draft_list
    f = _flow_self(data={"ev_chargers": []},
                   options={"ev_chargers": [{"id": "ev_charger"}]})
    assert _draft_list(f, "ev_chargers") == []


def test_draft_list_still_falls_back_and_never_aliases():
    from custom_components.solar_energy_management.config_flow import _draft_list
    saved = [{"id": "heat_pump_2"}]
    f = _flow_self(options={"heat_pumps": saved})
    got = _draft_list(f, "heat_pumps")
    assert got == saved
    got.append({"id": "x"})              # a copy, not the stored list
    assert f.config_entry.options["heat_pumps"] == saved
    # and the ROWS are copies too — `entry.options` is read-only at the top
    # and wide open one level down, and the live coordinator shares those
    # same row objects, so a form merged into row 0 was editing the running
    # config with no save at all.
    got[0]["heat_pump_climate_entity"] = "climate.scribbled"
    assert saved[0] == {"id": "heat_pump_2"}
    assert _draft_list(f, "nothing_here") == []
    # a null sitting in options reads as empty, not as a crash (class 54)
    f.config_entry.options["heat_pumps"] = None
    assert _draft_list(f, "heat_pumps") == []


# ── the guard: the shape itself is banned from the flow ─────────────

def test_no_step_resolves_a_draft_against_the_saved_copy_with_or():
    """AST lint — ``draft.get(K) or saved.get(K)`` is unrepresentable (#990).

    ``or`` reads an emptied collection as an absent one, so every such
    chain silently refuses the user's last deletion. The only resolver
    allowed to look at both sides is ``_draft_list``, which asks whether
    the key is PRESENT. One instance of this cost @RienduPre a heat pump
    that would not go away; the lint is what keeps the next list — loads,
    batteries, tariff rows — from re-learning it.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "config_flow.py"
    tree = ast.parse(src.read_text())

    def getter(node):
        """('<receiver>', 'key') for a ``<receiver>.get("key")`` call."""
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            return None
        return (ast.unparse(node.func.value), node.args[0].value)

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        by_key: dict[str, set[str]] = {}
        for operand in node.values:
            hit = getter(operand)
            if hit:
                by_key.setdefault(hit[1], set()).add(hit[0])
        for key, receivers in by_key.items():
            if len(receivers) > 1:
                offenders.append(
                    f"line {node.lineno}: '{key}' read from "
                    f"{sorted(receivers)} in one `or` chain")

    assert not offenders, (
        "a value must not be resolved from two stores with `or` — an empty "
        "or zero value in the first store falls through to the second and "
        "the user's edit is undone. Use `_draft_list` (or an explicit "
        "`key in ...` test). Offenders:\n  " + "\n  ".join(offenders))


# ── the sibling the lint found: a CLEARED sensor must stay cleared ──

def _phase_guard_form(saved, discovered):
    """Render the phase-guard page with a stubbed discovery."""
    from unittest.mock import MagicMock, patch
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    import asyncio
    stub = SimpleNamespace(
        _data={},
        config_entry=SimpleNamespace(data={}, options=dict(saved)),
        hass=MagicMock(),
        cur_step=None,
    )
    stub.hass.states.async_all.return_value = []
    stub.async_show_form = MethodType(
        lambda self, **kw: {"type": "form", **kw}, stub)
    stub._cfg = MethodType(
        lambda self, cfg, key, fb: cfg.get(key, fb) if cfg.get(key) is not None else fb,
        stub)
    stub.async_step_settings_phase_guard = MethodType(
        OptionsFlowHandler.async_step_settings_phase_guard, stub)

    import importlib
    mod = importlib.import_module(
        "custom_components.solar_energy_management.coordinator"
        ".phase_current_discovery")
    with patch.object(mod, "discover_grid_phase_current_entities",
                      return_value=dict(discovered)):
        form = asyncio.run(stub.async_step_settings_phase_guard(None))
    return {str(k.schema): k for k in form["data_schema"].schema}


L1 = "phase_guard_grid_l1_current_entity"
DISCOVERED = {L1: "sensor.auto_l1"}


def test_discovery_still_fills_a_phase_guard_sensor_nobody_ever_set():
    marker = _phase_guard_form({"phase_guard_topology": "grid_only"},
                               DISCOVERED)[L1]
    assert marker.description["suggested_value"] == "sensor.auto_l1"


def test_a_cleared_phase_guard_sensor_is_not_re_suggested_by_discovery():
    """#990's shape on a scalar: clearing it wrote None (#690), and the
    `or` read that deletion as silence and handed the sensor back."""
    marker = _phase_guard_form(
        {"phase_guard_topology": "grid_only", L1: None}, DISCOVERED)[L1]
    assert marker.description["suggested_value"] is None


def test_a_configured_phase_guard_sensor_still_wins():
    marker = _phase_guard_form(
        {"phase_guard_topology": "grid_only", L1: "sensor.mine"},
        DISCOVERED)[L1]
    assert marker.description["suggested_value"] == "sensor.mine"


# ── the sequel: remove, then add, must not mint a duplicate id ──────

@pytest.mark.asyncio
async def test_add_after_a_remove_does_not_reuse_a_live_id():
    """Positional ids are unique only while the list is append-only, and
    removal ends that. [2, 3] minus 2 then +1 used to mint heat_pump_3
    twice — and `register_device` keys on device_id, so one physical pump
    stopped being driven while the log still counted two."""
    f = _flow_self(options={"heat_pumps": [
        {"id": "heat_pump_2", "name": "Cellar",
         "heat_pump_climate_entity": "climate.c"},
        {"id": "heat_pump_3", "name": "Attic",
         "heat_pump_climate_entity": "climate.a"}]})
    await f.async_step_heat_pump_menu({"action": "remove_heat_pump:0"})
    await f.async_step_heat_pump_unit({"heat_pump_climate_entity": "climate.shed"})
    ids = [p["id"] for p in f._data["heat_pumps"]]
    # not 3 (live), and (#1421) not 2: SEM keeps the removed Cellar's day
    # runtime and meter reading under its id
    assert ids == ["heat_pump_3", "heat_pump_4"]
    assert len(set(ids)) == len(ids)


@pytest.mark.asyncio
async def test_ids_stay_unique_across_a_remove_add_remove_add_run():
    f = _flow_self(options={"heat_pumps": [
        {"id": "heat_pump_2"}, {"id": "heat_pump_3"}, {"id": "heat_pump_4"}]})
    for action in ("remove_heat_pump:1", "remove_heat_pump:0"):
        await f.async_step_heat_pump_menu({"action": action})
    for _ in range(3):
        await f.async_step_heat_pump_unit(
            {"heat_pump_climate_entity": "climate.x"})
    ids = [p["id"] for p in f._data["heat_pumps"]]
    assert len(set(ids)) == len(ids) == 4


def test_a_stored_duplicate_id_is_registered_instead_of_dropped():
    """Configs written by beta.31 can already hold a collision — the
    registration layer must not resolve it by losing a pump."""
    from custom_components.solar_energy_management import _heat_pump_rows
    rows = _heat_pump_rows({
        "heat_pump_climate_entity": "climate.main",
        "heat_pumps": [
            {"id": "heat_pump_3", "heat_pump_climate_entity": "climate.a"},
            {"id": "heat_pump_3", "heat_pump_climate_entity": "climate.b"},
        ],
    })
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids) == 3
    assert [r["heat_pump_climate_entity"] for r in rows] == [
        "climate.main", "climate.a", "climate.b"]


def test_a_row_may_not_collide_with_the_primary_either():
    from custom_components.solar_energy_management import _heat_pump_rows
    rows = _heat_pump_rows({
        "heat_pump_climate_entity": "climate.main",
        "heat_pumps": [{"id": "heat_pump", "heat_pump_climate_entity": "climate.a"}],
    })
    assert [r["id"] for r in rows] == ["heat_pump", "heat_pump_2"]
