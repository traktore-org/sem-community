"""#1204 — a writer that holds a per-battery list saves it in today's order.

Since #1195 SEM moves each battery's slot of the per-battery lists when the
batteries in the Energy Dashboard change (``battery_slot_units`` records
which battery owns each slot). Three writers held a copy of a list from
before such a change and saved it by place, so the old order came back and
a battery got another battery's entity again:

* the Config card saved a whole list from the copy it read when it opened
  (``_saveListField``); a copy that failed to read emptied every other slot;
* the Configure dialog copied the lists into its draft and saved them at
  the end (``async_step_settings_battery_limit``);
* a Mode select or reserve number writes its slot number, which is a place
  in the order it was built for, until the reload rebuilds it.

Now each writer says which order it read. The card sends one battery's edit
with its order (``battery_slot_edits``), the dialog keeps the order with its
draft (``lists_in_current_order`` at the save), and the select and number
write through ``put_battery_slot`` with the order they were built for.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.solar_energy_management.coordinator.battery_controls import (
    BATTERY_SLOT_UNITS_KEY, PER_BATTERY_LIST_KEYS, battery_slot_edits,
    lists_in_current_order, put_battery_slot, slot_today,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
COORDINATOR_MODULE = "custom_components.solar_energy_management.coordinator.coordinator"
LIMITS = "battery_discharge_control_entities"
ENDS = "battery_charge_end_soc_entities"

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None
real_ha = pytest.mark.skipif(
    not _HAS_PHACC,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

A, B, C = "sensor.verto1_charge_power", "sensor.verto2_charge_power", "sensor.sessy1_power"


# ── The rule, on its own ───────────────────────────────────────────────────

def test_a_battery_added_in_front_moves_the_place_a_writer_read():
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, B]}
    assert slot_today(0, [A, B], saved) == 1
    assert slot_today(1, [A, B], saved) == 2


def test_a_removed_battery_has_no_place_and_the_others_move_up():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, C]}
    assert slot_today(1, [A, B, C], saved) is None
    assert slot_today(2, [A, B, C], saved) == 1
    # a place the writer had no battery for, after a change
    assert slot_today(3, [A, B, C], saved) is None


@pytest.mark.parametrize("read, now", [
    (None, [A, B]),                 # the writer read no order (failed read)
    ([A, B], None),                 # nothing saved to follow
    ([A, B], [A, B]),               # no change
    (["", B], [B, A]),              # a damaged read
    ([A, B], [A, 3]),               # a damaged record
])
def test_with_no_order_to_follow_the_slot_stands(read, now):
    saved = {BATTERY_SLOT_UNITS_KEY: now}
    assert slot_today(1, read, saved) == 1
    # also a place past the batteries (a list longer than the record)
    assert slot_today(2, read, saved) == 2


def test_a_sensor_named_twice_takes_its_slots_in_turn():
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, A]}
    assert [slot_today(i, [A, A], saved) for i in range(2)] == [1, 2]


def test_one_slot_set_keeps_every_other_slot_as_saved():
    """The card's copy is older than another writer's change of B1: only
    the slot the user changed is written."""
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, B],
             LIMITS: ["number.c_limit", "number.a_limit_new", "number.b_limit"]}
    assert put_battery_slot(saved, LIMITS, 1, "number.b_new", [A, B]) == [
        "number.c_limit", "number.a_limit_new", "number.b_new"]
    assert saved[LIMITS][2] == "number.b_limit"          # not changed in place


def test_one_slot_set_grows_the_list():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B, C]}
    assert put_battery_slot(saved, LIMITS, 2, "number.c", [A, B, C]) == [
        None, None, "number.c"]


def test_one_slot_set_for_a_gone_battery_is_refused():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, C], LIMITS: ["number.a", "number.c"]}
    with pytest.raises(LookupError):
        put_battery_slot(saved, LIMITS, 1, "number.b", [A, B, C])


def test_whole_lists_follow_their_batteries():
    """The dialog's draft, read as [A, B]; C was added in front since and
    got its own limit from the card. A and B get the dialog's values at
    their new places; C keeps its own."""
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, B],
             LIMITS: ["number.c_limit", "number.a_old", "number.b_old"],
             ENDS: ["number.c_end"]}
    written = {LIMITS: ["number.a_new", "number.b_new"],
               ENDS: ["number.a_end", None],
               "battery_discharge_control_entity": "number.shared"}
    assert lists_in_current_order(written, [A, B], saved) == {
        LIMITS: ["number.c_limit", "number.a_new", "number.b_new"],
        ENDS: ["number.c_end", "number.a_end"],
    }


def test_whole_lists_drop_a_gone_battery():
    saved = {BATTERY_SLOT_UNITS_KEY: [B]}
    assert lists_in_current_order({LIMITS: ["number.a", "number.b"]}, [A, B], saved) == {
        LIMITS: ["number.b"]}


def test_whole_lists_in_todays_order_come_back_as_they_are():
    """A third slot left from an older home stays (#1089)."""
    lists = {LIMITS: ["number.a", "number.b", "number.c"]}
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B]}
    assert lists_in_current_order(lists, [A, B], saved) == lists
    assert lists_in_current_order(lists, None, saved) == lists


def test_set_option_edit_becomes_the_whole_list():
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, B], LIMITS: [None, "number.a", "number.b"]}
    out = battery_slot_edits({LIMITS: {"slot": 0, "value": "number.a2",
                                       BATTERY_SLOT_UNITS_KEY: [A, B]},
                              "battery_mode": "auto"}, saved)
    assert out == {LIMITS: [None, "number.a2", "number.b"], "battery_mode": "auto"}


def test_set_option_edit_emptied_is_unset():
    saved = {LIMITS: ["number.a", "number.b"]}
    out = battery_slot_edits({LIMITS: {"slot": 1, "value": ""}}, saved)
    assert out[LIMITS] == ["number.a", None]


def test_set_option_whole_list_is_todays_order():
    """A script that sends a whole list means today's batteries."""
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, B], LIMITS: ["x", "y", "z"]}
    options = {LIMITS: ["number.c", "number.a", "number.b"]}
    assert battery_slot_edits(options, saved) == options


@pytest.mark.parametrize("edit", [
    {"slot": True, "value": "number.a"},
    {"slot": -1, "value": "number.a"},
    {"slot": "0", "value": "number.a"},
    {"value": "number.a"},
    {"slot": 0, "value": ["number.a"]},
    {"slot": 0, "value": True},
    {"slot": 100_000_000, "value": "number.a"},
])
def test_set_option_damaged_edit_is_refused(edit):
    with pytest.raises(ValueError):
        battery_slot_edits({LIMITS: edit}, {})


def test_set_option_edit_for_a_gone_battery_is_refused():
    saved = {BATTERY_SLOT_UNITS_KEY: [B], LIMITS: ["number.b"]}
    with pytest.raises(LookupError):
        battery_slot_edits({LIMITS: {"slot": 0, "value": "number.a",
                                     BATTERY_SLOT_UNITS_KEY: [A, B]}}, saved)


# ── The Mode select and the reserve number ────────────────────────────────

def _persist(options, built, idx, value, key="battery_modes", count=2):
    from custom_components.solar_energy_management import persist_per_battery_option
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e", data={}, options=dict(options))
    hass.config_entries.async_update_entry.side_effect = (
        lambda e, options: setattr(e, "options", options))
    coordinator = SimpleNamespace(config={})
    with patch("custom_components.solar_energy_management._refresh_runtime_config"):
        persist_per_battery_option(hass, entry, coordinator, idx, key, value, count,
                                   read_units=built)
    return entry.options


def test_sems_own_mode_write_is_in_todays_order():
    """Review finding: ``_finish_manual_battery_modes`` counts batteries in
    today's reader order, not in the order the selects were built for."""
    options = {BATTERY_SLOT_UNITS_KEY: [C, A, B], "battery_modes": [None, "force_charge"]}
    assert _persist(options, None, 1, "auto")["battery_modes"] == [None, "auto"]


def test_a_select_built_before_the_change_writes_its_own_battery():
    """b2's select was built for B at place 2; the dashboard grew and the
    reload is due. Its write goes to B at place 3, not to A."""
    options = {BATTERY_SLOT_UNITS_KEY: [C, A, B],
               "battery_modes": [None, "force_discharge", "off"]}
    out = _persist(options, (A, B), 1, "auto")
    assert out["battery_modes"] == [None, "force_discharge", "auto"]


def test_a_select_with_no_change_writes_its_place():
    options = {BATTERY_SLOT_UNITS_KEY: [A, B], "battery_reserve_socs": [40]}
    assert _persist(options, (A, B), 1, 60, "battery_reserve_socs")[
        "battery_reserve_socs"] == [40, 60]
    # no order captured (a test double, or SEM set up before any record)
    assert _persist(options, None, 1, 60, "battery_reserve_socs")[
        "battery_reserve_socs"] == [40, 60]


def test_a_select_of_a_gone_battery_writes_nothing():
    options = {BATTERY_SLOT_UNITS_KEY: [A], "battery_modes": ["off"]}
    with pytest.raises(ServiceValidationError) as err:
        _persist(options, (A, B), 1, "auto")
    assert err.value.translation_key == "battery_list_changed"


def test_a_change_at_setup_is_the_order_the_controls_are_built_in():
    """Review finding: the #274 retry moves the lists during the first
    refresh, after the capture and before the platforms build (no reload).
    The controls are built in the new order, so that is the order they
    write in."""
    from custom_components.solar_energy_management.coordinator.battery_controls import (
        align_battery_slots,
    )
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e", data={}, options={
        BATTERY_SLOT_UNITS_KEY: [A, B], "battery_modes": ["force_charge", "off"]})
    coordinator = SimpleNamespace(config={}, battery_control_units=(A, B))
    assert align_battery_slots(hass, entry, coordinator, [C, A, B], running=False)
    assert coordinator.battery_control_units == (C, A, B)
    # its twin: once the platforms are forwarded the controls hold their
    # places, also before the entry is loaded
    entry.options = {BATTERY_SLOT_UNITS_KEY: [A, B], "battery_modes": ["force_charge", "off"]}
    coordinator = SimpleNamespace(config={}, battery_control_units=(A, B),
                                  _battery_controls_built=True)
    assert align_battery_slots(hass, entry, coordinator, [C, A, B], running=False)
    assert coordinator.battery_control_units == (A, B)


def test_a_first_record_while_running_keeps_the_order_the_slots_stood_in():
    """No record at setup; a running read writes the first one. With no
    older order the controls hold the places as they stand; with a #1226
    order the lists moved from it (no reload), so the controls write by it."""
    from custom_components.solar_energy_management.coordinator.battery_controls import (
        align_battery_slots,
    )
    for before, built in ((None, (A, B)), ([B], (B,))):
        entry = SimpleNamespace(entry_id="e", data={}, options={"battery_modes": ["off"]})
        coordinator = SimpleNamespace(config={}, _skip_options_reload=None)
        assert align_battery_slots(MagicMock(), entry, coordinator, [A, B],
                                   running=True, before=before)
        assert coordinator.battery_control_units == built, before


def test_the_select_shows_its_own_battery_before_the_reload():
    from custom_components.solar_energy_management.select import SEMPerBatterySelect
    sel = SEMPerBatterySelect.__new__(SEMPerBatterySelect)
    sel._idx = 1
    sel.coordinator = SimpleNamespace(battery_control_units=(A, B), config={
        BATTERY_SLOT_UNITS_KEY: [C, A, B], "battery_modes": [None, "force_charge", "off"]})
    assert sel._stored_mode() == "off"
    sel.coordinator.config[BATTERY_SLOT_UNITS_KEY] = [A]
    assert sel._stored_mode() is None            # gone: shows what it showed


@pytest.mark.asyncio
async def test_a_refused_select_keeps_showing_what_is_saved():
    from custom_components.solar_energy_management.select import SEMPerBatterySelect
    sel = SEMPerBatterySelect.__new__(SEMPerBatterySelect)
    sel._idx, sel._count, sel._value = 1, 2, "off"
    sel._entry, sel.coordinator, sel.hass = MagicMock(), MagicMock(), MagicMock()
    sel.entity_description = SimpleNamespace(options=["auto", "off"])
    sel.async_write_ha_state = MagicMock()
    with patch("custom_components.solar_energy_management.persist_per_battery_option",
               side_effect=ServiceValidationError("gone")):
        with pytest.raises(ServiceValidationError):
            await sel.async_select_option("auto")
    assert sel._value == "off"


# ── The Configure dialog ───────────────────────────────────────────────────

FIELD = "battery_discharge_control_entity"
END_FIELD = "battery_charge_end_soc_entity"


def _coordinator(slugs, sources=()):
    reader = SimpleNamespace(
        _energy_dashboard_config=SimpleNamespace(battery_power_list=list(sources)))
    return SimpleNamespace(battery_control_slugs=slugs, _sensor_reader=reader)


def _flow(mock_hass, config_entry, options, coordinator):
    from custom_components.solar_energy_management.config_flow import OptionsFlowHandler
    from custom_components.solar_energy_management.const import DOMAIN
    config_entry.options = options
    mock_hass.data = {DOMAIN: {config_entry.entry_id: coordinator}}
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    return flow


async def _call(flow, config_entry, step, user_input=None):
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: config_entry)):
        return await getattr(flow, f"async_step_{step}")(user_input)


async def _save(flow, config_entry):
    result = await _call(flow, config_entry, "notifications",
                         {"enable_charger_notifications": True})
    assert result["type"] == "create_entry"
    return result["data"]


@pytest.mark.asyncio
async def test_the_dialog_saves_each_battery_at_its_place_today(mock_hass, config_entry):
    """Opened on A and B; after the last page a combined battery C was added
    in front (the alignment moved the lists and gave C its own limit from
    the card). The save puts A's and B's answers at their new places and
    keeps C's."""
    flow = _flow(mock_hass, config_entry, {
        BATTERY_SLOT_UNITS_KEY: [A, B],
        LIMITS: ["number.a_limit", "number.b_limit"],
        ENDS: ["number.a_end", "number.b_end"]},
        _coordinator(("b1", "b2"), (A, B)))
    first = await _call(flow, config_entry, "settings_battery_limit")
    assert first["description_placeholders"]["sensor"] == A
    second = await _call(flow, config_entry, "settings_battery_limit",
                         {FIELD: "number.a_new", END_FIELD: "number.a_end"})
    assert second["description_placeholders"]["sensor"] == B
    await _call(flow, config_entry, "settings_battery_limit",
                {FIELD: "number.b_new", END_FIELD: "number.b_end"})
    config_entry.options = {
        BATTERY_SLOT_UNITS_KEY: [C, A, B],
        LIMITS: ["number.c_limit", "number.a_limit", "number.b_limit"],
        ENDS: [None, "number.a_end", "number.b_end"]}
    data = await _save(flow, config_entry)
    assert data[LIMITS] == ["number.c_limit", "number.a_new", "number.b_new"]
    assert data[ENDS] == [None, "number.a_end", "number.b_end"]
    assert data[BATTERY_SLOT_UNITS_KEY] == [C, A, B]


def _shown(result):
    marker = next(m for m in result["data_schema"].schema if m.schema == FIELD)
    return result["description_placeholders"]["sensor"], marker.description["suggested_value"]


@pytest.mark.asyncio
async def test_the_pages_follow_a_change_between_them(mock_hass, config_entry):
    """C added in front after A's page: A's answer goes with A, and the pages
    start again from today's first battery, each with its own value — every
    battery is shown, none twice in a row by number."""
    flow = _flow(mock_hass, config_entry, {
        BATTERY_SLOT_UNITS_KEY: [A, B],
        LIMITS: ["number.a_limit", "number.b_limit"]},
        _coordinator(("b1", "b2", "b3"), (A, B)))
    await _call(flow, config_entry, "settings_battery_limit")
    config_entry.options = {
        BATTERY_SLOT_UNITS_KEY: [C, A, B],
        LIMITS: ["number.c_limit", "number.a_limit", "number.b_limit"]}
    page = await _call(flow, config_entry, "settings_battery_limit", {FIELD: "number.a_new"})
    assert _shown(page) == (C, "number.c_limit")
    page = await _call(flow, config_entry, "settings_battery_limit", {FIELD: "number.c_limit"})
    assert _shown(page) == (A, "number.a_new")
    page = await _call(flow, config_entry, "settings_battery_limit", {FIELD: "number.a_new"})
    assert _shown(page) == (B, "number.b_limit")
    await _call(flow, config_entry, "settings_battery_limit", {FIELD: "number.b_new"})
    data = await _save(flow, config_entry)
    assert data[LIMITS] == ["number.c_limit", "number.a_new", "number.b_new"]


@pytest.mark.asyncio
@pytest.mark.parametrize("left, want", [
    ([B], ["number.b_limit"]),          # A, the page answered, removed
    ([A], ["number.a_new"]),            # B, the page to come, removed
])
async def test_the_dialog_drops_a_battery_removed_while_it_was_open(
        mock_hass, config_entry, left, want):
    """The reload after the removal is still due (the slugs are two): the
    pages start again on the one battery left, and its slot is its own."""
    flow = _flow(mock_hass, config_entry, {
        BATTERY_SLOT_UNITS_KEY: [A, B], LIMITS: ["number.a_limit", "number.b_limit"]},
        _coordinator(("b1", "b2"), (A, B)))
    await _call(flow, config_entry, "settings_battery_limit")
    config_entry.options = {BATTERY_SLOT_UNITS_KEY: left,
                            LIMITS: ["number.a_limit" if left == [A] else "number.b_limit"]}
    page = await _call(flow, config_entry, "settings_battery_limit", {FIELD: "number.a_new"})
    assert _shown(page) == (left[0], want[0])
    done = await _call(flow, config_entry, "settings_battery_limit", {FIELD: want[0]})
    assert done["step_id"] == "settings_ev"
    data = await _save(flow, config_entry)
    assert data[LIMITS] == want


@pytest.mark.asyncio
async def test_the_dialog_with_no_change_saves_as_before(mock_hass, config_entry):
    flow = _flow(mock_hass, config_entry, {
        BATTERY_SLOT_UNITS_KEY: [A, B],
        LIMITS: ["number.a_limit", "number.b_limit", "number.old_third"]},
        _coordinator(("b1", "b2"), (A, B)))
    await _call(flow, config_entry, "settings_battery_limit")
    await _call(flow, config_entry, "settings_battery_limit", {FIELD: "number.a_limit"})
    await _call(flow, config_entry, "settings_battery_limit", {})
    data = await _save(flow, config_entry)
    assert data[LIMITS] == ["number.a_limit", None, "number.old_third"]


@pytest.mark.asyncio
async def test_a_skipped_page_keeps_the_list_moved_since(mock_hass, config_entry):
    """One battery's controls (no pages): the saved lists still reach the
    save, in the order of the save."""
    flow = _flow(mock_hass, config_entry, {
        BATTERY_SLOT_UNITS_KEY: [A, B], LIMITS: ["number.a_limit", "number.b_limit"]},
        _coordinator(()))
    result = await _call(flow, config_entry, "settings_battery_limit")
    assert result["step_id"] == "settings_ev"
    config_entry.options = {
        BATTERY_SLOT_UNITS_KEY: [B, A], LIMITS: ["number.b_limit", "number.a_limit"]}
    data = await _save(flow, config_entry)
    assert data[LIMITS] == ["number.b_limit", "number.a_limit"]


# ── Every writer, from the source ─────────────────────────────────────────

#: Functions that name a per-battery list key where it is written, and why
#: that write cannot put an old order back.
_KNOWN_WRITERS = {
    ("config_flow.py", "async_step_settings_battery_limit"):
        "the draft; the final save puts it in today's order",
    ("coordinator/battery_controls.py", "adopt_shared_battery_settings"):
        "every slot the same value, at setup",
    ("__init__.py", "_migrate_legacy_arbitrage_mode"):
        "each slot's value changed in place, read and written at once",
    ("coordinator/coordinator.py", "_async_update_data"):
        "a one-call config for the start-up restore, never saved",
    ("diagnostics.py", "async_get_config_entry_diagnostics"):
        "a copy for the download, never saved",
}


def _innermost_functions(tree):
    """Each node with the innermost function around it (None at module level)."""
    out = []

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            inner = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            out.append((child, inner))
            visit(child, inner)
    visit(tree, None)
    return out


def _list_key_writes():
    keys = set(PER_BATTERY_LIST_KEYS)
    found = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "dashboard/", "scripts/", "tools/")) or "/node_modules/" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node, fn in _innermost_functions(tree):
            key = None
            if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                    and isinstance(node.slice, ast.Constant)):
                key = node.slice.value
            elif isinstance(node, ast.Dict):
                key = next((k.value for k in node.keys
                            if isinstance(k, ast.Constant) and k.value in keys), None)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "setdefault" and node.args
                  and isinstance(node.args[0], ast.Constant)):
                key = node.args[0].value
            if key in keys:
                found.setdefault((rel, fn.name if fn else "<module>"), node.lineno)
    return found


def test_every_writer_of_a_per_battery_list_is_known():
    """A new place that writes one of the six lists must follow today's
    battery order (``put_battery_slot`` / ``lists_in_current_order``) and
    be listed here with the reason."""
    found = _list_key_writes()
    assert set(found) == set(_KNOWN_WRITERS), (
        f"new per-battery list writers: {set(found) - set(_KNOWN_WRITERS)}; "
        f"gone: {set(_KNOWN_WRITERS) - set(found)}")


def test_the_scan_sees_a_new_writer():
    """Its twin: a function the list does not name is caught, also in a
    file that has a known writer."""
    src = (
        "def async_step_brand_new(self):\n"
        "    self._data['battery_modes'] = ['auto']\n"
        "def adopt_shared_battery_settings():\n"
        "    def helper():\n"
        "        return {'battery_reserve_socs': [20]}\n")
    hits = {(fn.name if fn else None) for node, fn in _innermost_functions(ast.parse(src))
            if isinstance(node, (ast.Subscript, ast.Dict))
            and "battery_" in ast.unparse(node)}
    assert hits == {"async_step_brand_new", "helper"}


def _calls(rel, fn_name):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name)
    return {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None)
            for n in ast.walk(fn) if isinstance(n, ast.Call)}


def _passes_read_units(rel, fn_name):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    calls = [n for fn in ast.walk(tree)
             if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == fn_name
             for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "persist_per_battery_option"]
    assert calls, (rel, fn_name)
    return all(any(k.arg == "read_units" and "battery_control_units" in ast.unparse(k.value)
                   for k in c.keywords) for c in calls)


def test_each_writer_follows_the_order():
    assert "put_battery_slot" in _calls("__init__.py", "persist_per_battery_option")
    # the controls write in the order they were built for
    assert _passes_read_units("select.py", "async_select_option")
    assert _passes_read_units("number.py", "async_set_native_value")
    assert "battery_slot_edits" in _calls("__init__.py", "async_set_option")
    assert "lists_in_current_order" in _calls("config_flow.py", "_battery_draft_follows")
    assert "_battery_draft_follows" in _calls("config_flow.py", "async_step_notifications")
    assert "_battery_draft_follows" in _calls(
        "config_flow.py", "async_step_settings_battery_limit")


# ── Real setup: the card's save after the dashboard changed ───────────────

SOLAR = {"type": "solar", "stat_energy_from": "sensor.pv_energy",
         "stat_rate": "sensor.pv_power"}
GRID = {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
        "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
        "stat_rate": "sensor.grid_power"}


def _pair(n):
    return {"type": "battery",
            "stat_energy_from": f"sensor.verto{n}_discharge_energy",
            "stat_energy_to": f"sensor.verto{n}_charge_energy",
            "power_config": {"stat_rate_from": f"sensor.verto{n}_discharge_power",
                             "stat_rate_to": f"sensor.verto{n}_charge_power"}}


COMBINED = {"type": "battery",
            "stat_energy_from": "sensor.sessy1_discharge_energy",
            "stat_energy_to": "sensor.sessy1_charge_energy",
            "stat_rate": "sensor.sessy1_power"}
STATES = {
    "sensor.verto1_charge_power": "800", "sensor.verto1_discharge_power": "0",
    "sensor.verto2_charge_power": "0", "sensor.verto2_discharge_power": "300",
    "sensor.sessy1_power": "0", "sensor.pv_power": "3000", "sensor.grid_power": "0",
}
MINIMAL_DATA = {
    "grid_power_sensor": "sensor.grid_power",
    "solar_power_sensor": "sensor.pv_power",
    "min_solar_power": 1000,
    "peak_load": 6000,
    "update_interval": 30,
    "electricity_import_rate": 0.30,
    "electricity_export_rate": 0.08,
}


def _prefs(batteries):
    return {"energy_sources": [SOLAR, GRID, *batteries], "device_consumption": []}


@real_ha
@pytest.mark.asyncio
async def test_the_cards_save_after_the_dashboard_changed_reaches_its_battery(
        hass, enable_custom_integrations, monkeypatch):
    """The card read A and B; the user then added C in the Energy Dashboard
    while SEM ran (the settings moved, SEM reloaded). The card's next save
    for B goes to B at place 3; A and C are not touched. A save for a
    battery removed since is refused."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solar_energy_management.const import DOMAIN
    from custom_components.solar_energy_management.ha_energy_reader import _parse_prefs
    for eid, state in STATES.items():
        hass.states.async_set(eid, state, {"unit_of_measurement": "W"})
    read = AsyncMock(return_value=(
        _parse_prefs(hass, _prefs([_pair(1), _pair(2)]), quiet=True), True))
    monkeypatch.setattr(f"{COORDINATOR_MODULE}.read_energy_dashboard_config_outcome", read)
    entry = MockConfigEntry(domain=DOMAIN, version=12, minor_version=1,
                            data=dict(MINIMAL_DATA), title="SEM #1204", options={
                                BATTERY_SLOT_UNITS_KEY: [A, B],
                                LIMITS: ["number.verto1_limit", "number.verto2_limit"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.battery_control_units == (A, B)

    card = (await hass.services.async_call(
        DOMAIN, "get_config", {}, blocking=True, return_response=True))["config"]
    assert card[BATTERY_SLOT_UNITS_KEY] == [A, B]

    first = entry.runtime_data
    read.return_value = (_parse_prefs(
        hass, _prefs([_pair(1), _pair(2), COMBINED]), quiet=True), True)
    await first.async_initialize_energy_dashboard(quiet=True)
    await hass.async_block_till_done()
    assert entry.runtime_data is not first
    assert entry.options[LIMITS] == [None, "number.verto1_limit", "number.verto2_limit"]
    assert entry.runtime_data.battery_control_units == (C, A, B)

    # the card's row B2 is B in the copy it read
    await hass.services.async_call(DOMAIN, "set_option", {"options": {
        LIMITS: {"slot": 1, "value": "number.verto2_new",
                 BATTERY_SLOT_UNITS_KEY: card[BATTERY_SLOT_UNITS_KEY]}}}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[LIMITS] == [None, "number.verto1_limit", "number.verto2_new"]
    cfg = entry.runtime_data._per_battery_config(2, 3)
    assert cfg["battery_discharge_control_entity"] == "number.verto2_new"

    # A copy that failed to read has no order: its row is today's place.
    await hass.services.async_call(DOMAIN, "set_option", {"options": {
        LIMITS: {"slot": 0, "value": "number.sessy_limit"}}}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[LIMITS] == [
        "number.sessy_limit", "number.verto1_limit", "number.verto2_new"]

    # B removed from the dashboard; the card still holds A and B
    second = entry.runtime_data
    read.return_value = (_parse_prefs(
        hass, _prefs([_pair(1), COMBINED]), quiet=True), True)
    await second.async_initialize_energy_dashboard(quiet=True)
    await hass.async_block_till_done()
    assert entry.options[LIMITS] == ["number.sessy_limit", "number.verto1_limit"]
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_option", {"options": {
            LIMITS: {"slot": 1, "value": "number.other",
                     BATTERY_SLOT_UNITS_KEY: card[BATTERY_SLOT_UNITS_KEY]}}}, blocking=True)
    assert err.value.translation_key == "battery_list_changed"
    assert entry.options[LIMITS] == ["number.sessy_limit", "number.verto1_limit"]
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
