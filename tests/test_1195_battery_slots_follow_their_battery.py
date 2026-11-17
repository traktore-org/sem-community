"""#1195 — each battery's saved settings stay with that battery.

SEM keeps per-battery settings in lists by position (``battery_modes``,
``battery_reserve_socs``, ``battery_force_discharge_entities``,
``battery_discharge_control_entities`` …): slot N is battery bN's. The reader
numbers combined power sensors first and two-sensor batteries after them, so
a battery added (or removed) in the Energy Dashboard moved the others. A
combined battery added to a home of two pairs became b1 and took the first
pair's discharge entity; SEM then wrote that entity when it decided for the
new battery (found while fixing #1171).

Now ``battery_slot_units`` records which battery each slot is for, and every
Energy Dashboard read puts the lists in the order of the batteries it read
(``battery_controls.align_battery_slots``). A loaded entry reloads once when
its battery list changed, so the adapters, selects and numbers are built
again for the new numbers.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_controls import (
    BATTERY_SLOT_UNITS_KEY, PER_BATTERY_LIST_KEYS, realign_battery_slots,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    _parse_prefs, battery_units,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
COORDINATOR_MODULE = "custom_components.solar_energy_management.coordinator.coordinator"

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None
real_ha = pytest.mark.skipif(
    not _HAS_PHACC,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

A, B, C = "sensor.verto1_charge_power", "sensor.verto2_charge_power", "sensor.sessy1_power"


# ── The rule, on its own ───────────────────────────────────────────────────

def test_a_combined_battery_added_before_two_pairs_takes_no_ones_slot():
    """The issue: two pairs A and B, then a combined C. C is b1 now."""
    saved = {
        BATTERY_SLOT_UNITS_KEY: [A, B],
        "battery_force_discharge_entities": ["number.a_sell", "number.b_sell"],
        "battery_discharge_control_entities": ["number.a_limit", "number.b_limit"],
        "battery_modes": ["force_discharge", "off"],
        "battery_reserve_socs": [30, 0],
    }
    changes, moved = realign_battery_slots(saved, [C, A, B])
    assert moved is True
    assert changes == {
        BATTERY_SLOT_UNITS_KEY: [C, A, B],
        "battery_force_discharge_entities": [None, "number.a_sell", "number.b_sell"],
        "battery_discharge_control_entities": [None, "number.a_limit", "number.b_limit"],
        "battery_modes": [None, "force_discharge", "off"],
        # an explicit 0 % is a value, not unset
        "battery_reserve_socs": [None, 30, 0],
    }


def test_a_removed_battery_takes_its_slots_with_it():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B, C],
             "battery_strategy_entities": [None, "select.b_strategy", "select.c_strategy"],
             "battery_modes": ["off", "auto", "force_charge"]}
    changes, moved = realign_battery_slots(saved, [B, C])
    assert moved is True
    assert changes["battery_strategy_entities"] == ["select.b_strategy", "select.c_strategy"]
    assert changes["battery_modes"] == ["auto", "force_charge"]
    # a leading unset slot stays where it is: it is b1's
    changes, _ = realign_battery_slots(saved, [A, C])
    assert changes["battery_strategy_entities"] == [None, "select.c_strategy"]


def test_the_first_record_takes_the_slots_as_they_stand_and_drops_the_rest():
    """The comment on #1195: a list left from an older home of three
    batteries drove the next third battery. With no record the slots are
    taken as they are; a slot past the last battery is no battery's."""
    saved = {"battery_force_discharge_entities": ["number.a", "number.b", "number.old"],
             "battery_modes": ["off"]}
    changes, moved = realign_battery_slots(saved, [A, B])
    assert moved is False
    assert changes == {BATTERY_SLOT_UNITS_KEY: [A, B],
                       "battery_force_discharge_entities": ["number.a", "number.b"]}
    # …and the third battery added later starts unset.
    grown, moved = realign_battery_slots({**saved, **changes}, [A, B, C])
    assert moved is True
    # C's slot past the end is unset ("number.old" is gone); nothing moves
    assert grown == {BATTERY_SLOT_UNITS_KEY: [A, B, C]}


def test_lists_already_in_order_change_nothing():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B], "battery_modes": ["off", "auto"]}
    assert realign_battery_slots(saved, [A, B]) is None
    assert realign_battery_slots(saved, (A, B)) is None


@pytest.mark.parametrize("units", [[], None, "sensor.x", [None, ""], [A, None, B], [A, ""]])
def test_no_battery_read_is_no_answer(units):
    """An empty read (no battery yet, a cold start) must not drop slots, and
    a gap in the read is no answer either: closed up, it would move every
    battery after it."""
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B], "battery_modes": ["off", "auto"]}
    assert realign_battery_slots(saved, units) is None


def test_a_damaged_record_or_list_is_not_trusted():
    saved = {BATTERY_SLOT_UNITS_KEY: "sensor.a",      # not a list: no record
             "battery_modes": ["off", "auto"],
             "battery_reserve_socs": "20"}             # not a list: left alone
    changes, moved = realign_battery_slots(saved, [A, B])
    assert moved is False
    assert changes == {BATTERY_SLOT_UNITS_KEY: [A, B]}


def test_one_sensor_named_twice_gives_each_battery_one_slot():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, A], "battery_modes": ["off", "force_charge"]}
    changes, _ = realign_battery_slots(saved, [B, A, A])
    assert changes["battery_modes"] == [None, "off", "force_charge"]


# ── Real setup ─────────────────────────────────────────────────────────────

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
# The combined battery is added LAST in the Energy Dashboard, and the reader
# still makes it b1.
TWO_PAIRS = [_pair(1), _pair(2)]
GROWN = [_pair(1), _pair(2), COMBINED]
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
# What the two-pair home saved: each pair's own sell and limit numbers.
PAIR_OPTIONS = {
    "battery_force_discharge_entities": ["number.verto1_sell", "number.verto2_sell"],
    "battery_discharge_control_entities": ["number.verto1_limit", "number.verto2_limit"],
    "battery_modes": ["force_discharge", "off"],
    "battery_reserve_socs": [40, 60],
}


def _prefs(batteries):
    return {"energy_sources": [SOLAR, GRID, *batteries], "device_consumption": []}


def test_the_grown_home_numbers_the_new_battery_first():
    """The premise: the reader makes the combined battery b1."""
    ed = _parse_prefs(MagicMock(), _prefs(GROWN), quiet=True)
    assert battery_units(ed) == [C, A, B]


async def _setup(hass, monkeypatch, batteries, options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solar_energy_management.const import DOMAIN
    for eid, state in STATES.items():
        hass.states.async_set(eid, state, {"unit_of_measurement": "W"})
    read = AsyncMock(return_value=(_parse_prefs(hass, _prefs(batteries), quiet=True), True))
    monkeypatch.setattr(f"{COORDINATOR_MODULE}.read_energy_dashboard_config_outcome", read)
    entry = MockConfigEntry(domain=DOMAIN, version=12, minor_version=1,
                            data=dict(MINIMAL_DATA), options=dict(options),
                            title="SEM #1195")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, read


def _select(hass, entry, bid):
    from homeassistant.helpers import entity_registry as er

    from custom_components.solar_energy_management.const import DOMAIN
    eid = er.async_get(hass).async_get_entity_id(
        "select", DOMAIN, f"{entry.entry_id}_battery_{bid}_mode")
    return hass.states.get(eid).state


def _assert_each_battery_has_its_own(hass, entry):
    """C (b1) has none of the pairs' entities; A (b2) and B (b3) keep theirs —
    in the config SEM decides from, in what its adapter is built from, and on
    the mode select the user sees."""
    from custom_components.solar_energy_management.consts.battery_modes import (
        reserve_soc_of,
    )
    coordinator = entry.runtime_data
    assert coordinator.battery_control_slugs == ("b1", "b2", "b3")
    want = {
        0: (None, None, "auto", 20),
        1: ("number.verto1_sell", "number.verto1_limit", "force_discharge", 40),
        2: ("number.verto2_sell", "number.verto2_limit", "off", 60),
    }
    for idx, (sell, limit, mode, reserve) in want.items():
        bid = f"b{idx + 1}"
        cfg = coordinator._per_battery_config(idx, 3)
        assert cfg.get("battery_force_discharge_control_entity") == sell, bid
        assert cfg.get("battery_discharge_control_entity") == limit, bid
        assert cfg["battery_mode"] == mode and reserve_soc_of(cfg) == reserve, bid
        ctx = coordinator._battery_adapter_context(bid, idx, 3)
        assert ctx.get("battery_force_discharge_control_entity") == sell, bid
        adapter = (getattr(coordinator, "_battery_adapters", None) or {}).get(bid)
        if adapter is not None:
            assert (getattr(adapter, "_force_discharge_entity", "") or None) == sell, bid
        assert _select(hass, entry, bid) == mode, bid
    assert entry.options[BATTERY_SLOT_UNITS_KEY] == [C, A, B]


@real_ha
@pytest.mark.asyncio
async def test_a_start_after_the_dashboard_grew_keeps_each_battery_on_its_own(
        hass, enable_custom_integrations, monkeypatch):
    """The two-pair home saved its record; the user added a combined battery
    while SEM was off. The first start moves each pair's settings with it."""
    entry, _read = await _setup(hass, monkeypatch, GROWN,
                                {**PAIR_OPTIONS, BATTERY_SLOT_UNITS_KEY: [A, B]})
    _assert_each_battery_has_its_own(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@real_ha
@pytest.mark.asyncio
async def test_a_dashboard_edit_while_sem_runs_moves_the_settings_and_reloads(
        hass, enable_custom_integrations, monkeypatch):
    """An install from before this fix: no record. The first start records
    the two pairs as they stand (and does not reload); the user then adds a
    combined battery in the Energy Dashboard while SEM runs (#923). The
    settings move and the entry reloads once, so the new numbers are built."""
    entry, read = await _setup(hass, monkeypatch, TWO_PAIRS, PAIR_OPTIONS)
    first = entry.runtime_data
    assert entry.options[BATTERY_SLOT_UNITS_KEY] == [A, B]
    assert entry.options["battery_force_discharge_entities"] == [
        "number.verto1_sell", "number.verto2_sell"]
    assert first._per_battery_config(0, 2)["battery_mode"] == "force_discharge"

    read.return_value = (_parse_prefs(hass, _prefs(GROWN), quiet=True), True)
    await first.async_initialize_energy_dashboard(quiet=True)
    await hass.async_block_till_done()

    assert entry.runtime_data is not first          # reloaded
    _assert_each_battery_has_its_own(hass, entry)

    # The reload's own read finds the lists in order: no second reload.
    second = entry.runtime_data
    options = dict(entry.options)
    await second.async_initialize_energy_dashboard(quiet=True)
    await hass.async_block_till_done()
    assert entry.runtime_data is second and dict(entry.options) == options
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def test_a_first_record_while_running_arms_the_no_reload_snapshot():
    """The same twin without HA: a record alone is written with the
    snapshot the options listener skips on; a moved list is not."""
    from types import SimpleNamespace

    from custom_components.solar_energy_management.coordinator.battery_controls import (
        align_battery_slots,
    )
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e", data={}, options={"battery_modes": ["off", "auto"]})
    coordinator = SimpleNamespace(config={"battery_modes": ["off", "auto"]},
                                  _skip_options_reload=None)
    assert align_battery_slots(hass, entry, coordinator, [A, B], running=True)
    written = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert written == {"battery_modes": ["off", "auto"], BATTERY_SLOT_UNITS_KEY: [A, B]}
    assert coordinator._skip_options_reload == written
    assert coordinator.config[BATTERY_SLOT_UNITS_KEY] == [A, B]

    entry.options = written
    coordinator._skip_options_reload = None
    assert align_battery_slots(hass, entry, coordinator, [C, A, B], running=True)
    moved = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert moved["battery_modes"] == [None, "off", "auto"]
    assert coordinator._skip_options_reload is None   # the listener reloads
    assert coordinator.config["battery_modes"] == [None, "off", "auto"]
    # nothing to do, nothing written
    entry.options = moved
    hass.config_entries.async_update_entry.reset_mock()
    assert not align_battery_slots(hass, entry, coordinator, [C, A, B], running=True)
    hass.config_entries.async_update_entry.assert_not_called()


def test_a_moved_list_while_running_holds_the_battery_commands():
    """Until the reload, the adapters hold the old places' entities: the
    pipeline is told to send nothing. A first record, or a move at setup
    (nothing built yet), holds nothing."""
    from types import SimpleNamespace

    from custom_components.solar_energy_management.coordinator.battery_controls import (
        align_battery_slots,
    )
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B], "battery_modes": ["off", "auto"]}
    for running, units, held in ((True, [C, A, B], True), (False, [C, A, B], False),
                                 (True, [A, B, C], True)):
        entry = SimpleNamespace(entry_id="e", data={}, options=dict(saved))
        coordinator = SimpleNamespace(config=dict(saved))
        assert align_battery_slots(MagicMock(), entry, coordinator, units, running=running)
        assert getattr(coordinator, "_battery_reload_pending", False) is held, (running, units)
    entry = SimpleNamespace(entry_id="e", data={}, options={"battery_modes": ["off"]})
    coordinator = SimpleNamespace(config={})
    assert align_battery_slots(MagicMock(), entry, coordinator, [A, B], running=True)
    assert not hasattr(coordinator, "_battery_reload_pending")


def test_a_battery_removed_while_sem_was_off_has_its_cap_lifted_at_start():
    """SEM's last discharge cap stays on a battery taken out of the
    Energy Dashboard while SEM was off. Its slot goes, so the start-up
    restore is handed its limit entity; a kept or shared one is not."""
    from types import SimpleNamespace

    from custom_components.solar_energy_management.coordinator.battery_controls import (
        align_battery_slots,
    )
    saved = {BATTERY_SLOT_UNITS_KEY: [C, A, B],
             "battery_discharge_control_entities": [
                 "number.c_limit", "number.shared_limit", "number.shared_limit"]}
    entry = SimpleNamespace(entry_id="e", data={}, options=dict(saved))
    coordinator = SimpleNamespace(config=dict(saved))
    align_battery_slots(MagicMock(), entry, coordinator, [A, B], running=False)
    assert coordinator._dropped_battery_limit_entities == ["number.c_limit"]
    # running: the unload lifts it, nothing is kept for a start
    entry = SimpleNamespace(entry_id="e", data={}, options=dict(saved))
    coordinator = SimpleNamespace(config=dict(saved))
    align_battery_slots(MagicMock(), entry, coordinator, [A, B], running=True)
    assert not hasattr(coordinator, "_dropped_battery_limit_entities")
    # B removed: its shared entity is still A's
    entry = SimpleNamespace(entry_id="e", data={}, options=dict(saved))
    coordinator = SimpleNamespace(config=dict(saved))
    align_battery_slots(MagicMock(), entry, coordinator, [C, A], running=False)
    assert not hasattr(coordinator, "_dropped_battery_limit_entities")


@real_ha
@pytest.mark.asyncio
async def test_the_start_lifts_a_removed_batterys_cap_and_holds_while_a_reload_is_due(
        hass, enable_custom_integrations, monkeypatch):
    """Through SEM's real setup and cycle: the start-up restore covers the
    removed battery's limit, and a cycle with a reload due sends no command
    and ends no manual mode (the twin: without it, both run)."""
    from custom_components.solar_energy_management.coordinator import (
        actuate_battery, battery_shared_limit,
    )
    restored = []

    async def _restore(_hass, config, yielded=False):
        listed = list(config.get("battery_discharge_control_entities") or [])
        restored.append(listed)
        if "number.sessy1_limit" in listed:
            raise RuntimeError("the removed battery does not answer")
    monkeypatch.setattr(actuate_battery, "restore_discharge_limit_on_startup", _restore)
    entry, _read = await _setup(hass, monkeypatch, TWO_PAIRS, {
        BATTERY_SLOT_UNITS_KEY: [C, A, B],
        "battery_discharge_control_entities": [
            "number.sessy1_limit", "number.verto1_limit", "number.verto2_limit"]})
    assert entry.options["battery_discharge_control_entities"] == [
        "number.verto1_limit", "number.verto2_limit"]
    # the live batteries first, then the removed one on its own: its write
    # fails, and the start goes on
    assert restored[:2] == [["number.verto1_limit", "number.verto2_limit"],
                            ["number.sessy1_limit"]]
    assert entry.state.value == "loaded"

    coordinator = entry.runtime_data
    sent = AsyncMock(return_value={})
    monkeypatch.setattr(battery_shared_limit, "actuate_batteries", sent)
    coordinator._finish_manual_battery_modes = MagicMock()
    coordinator._battery_reload_pending = True
    await coordinator.async_refresh()
    assert not sent.called and not coordinator._finish_manual_battery_modes.called

    coordinator._battery_reload_pending = False
    await coordinator.async_refresh()
    assert sent.called and coordinator._finish_manual_battery_modes.called

    # Due part way through the cycle (the scheduler awaits): still no command.
    sent.reset_mock()
    coordinator._finish_manual_battery_modes = MagicMock(
        side_effect=lambda *a, **k: setattr(coordinator, "_battery_reload_pending", True))
    await coordinator.async_refresh()
    assert coordinator._finish_manual_battery_modes.called and not sent.called
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# ── Guards ─────────────────────────────────────────────────────────────────

_LIST_KEY_RE = re.compile(
    r"^battery_[a-z_]+_(entities|socs)$|^battery_modes$|^battery_capacity_kwhs$")


def _package_sources():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/")) or "/tests/" in rel:
            continue
        yield rel, path.read_text(encoding="utf-8")


def test_every_per_battery_list_is_one_the_alignment_moves():
    """A per-battery list the alignment does not know would stay by position
    and shift again. Every such key in the package — and every list the
    Config card writes per battery — must be in ``PER_BATTERY_LIST_KEYS``."""
    found = {}
    for rel, src in _package_sources():
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and _LIST_KEY_RE.match(node.value)):
                found.setdefault(node.value, rel)
    from ._dashboard_src import dashboard_src
    card = dashboard_src()
    for m in re.finditer(r"'(battery_[a-z_]+_entities)'", card):
        found.setdefault(m.group(1), "next-settings.js")
    assert set(found) >= set(PER_BATTERY_LIST_KEYS)          # the scan sees them
    unknown = {k: v for k, v in found.items() if k not in PER_BATTERY_LIST_KEYS}
    assert not unknown, f"add to PER_BATTERY_LIST_KEYS: {unknown}"


def test_the_per_battery_config_reads_the_lists_the_alignment_moves():
    """``_per_battery_config`` names no list key of its own: it reads the
    pairs ``PER_BATTERY_LIST_KEYS`` is made of."""
    tree = ast.parse((ROOT / "coordinator/coordinator.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_per_battery_config")
    own = {n.value for n in ast.walk(fn)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and _LIST_KEY_RE.match(n.value)}
    assert not own, own
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert {"PER_BATTERY_ENTITY_LISTS", "PER_BATTERY_SETTING_LISTS"} <= names


def test_every_dashboard_read_aligns_right_after_the_reader_gets_it():
    """Setup, the #923 edit listener and the #274 retry all read through
    ``async_initialize_energy_dashboard``; the alignment follows the reader's
    new config at once, before the setup captures the controls."""
    tree = ast.parse((ROOT / "coordinator/coordinator.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "async_initialize_energy_dashboard")
    lines = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            lines.setdefault(n.func.attr, []).append(n.lineno)
    assert len(lines["_align_battery_slots"]) == 1
    assert lines["set_energy_dashboard_config"][0] < lines["_align_battery_slots"][0]
