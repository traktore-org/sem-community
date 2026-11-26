"""(#1428) Nothing SEM made outlives the item it was made for, or SEM itself.

A charger, battery, PV string or load with its own tariff leaves SEM: its
entities go at the next setup (``remove_charger`` reloads, so right away).
Every platform reports the keys it built in this run; ONE sweep after the
platforms are set up removes this entry's rows whose key no platform built.
A platform that did not report is left alone.
"""
import ast
import pathlib
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management import entity_sweep as es

E = "01ENTRY"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def row(domain, key, prefix=None, platform="solar_energy_management", disabled=None):
    uid = (prefix if prefix is not None else E + "_") + key
    return SimpleNamespace(entity_id=f"{domain}.sem_{key}", unique_id=uid,
                           platform=platform, domain=domain, disabled_by=disabled)


def gone(rows, built):
    return sorted(r.entity_id for r in es.stale_rows(rows, E, built))


FAMILIES = {   # family: (platform, key of a kept item, key of a removed item)
    "charger": ("time", "charger_ev_charger_target_time", "charger_ev_charger_1_target_time"),
    "battery": ("sensor", "battery_b1_soc", "battery_b2_soc"),
    "battery_number": ("number", "battery_b1_capacity_kwh", "battery_b2_capacity_kwh"),
    "battery_select": ("select", "battery_b1_mode", "battery_b2_mode"),
    "pv_string": ("sensor", "pv_string_1_power", "pv_string_3_power"),
    "load_tariff": ("sensor", "daily_tariff_cost_washer", "daily_tariff_cost_dishwasher"),
    "charger_switch": ("switch", "charger_ev_charger_night_charging", "charger_ev_charger_1_night_charging"),
    "charger_button": ("button", "charger_ev_charger_pause_charging", "charger_ev_charger_1_pause_charging"),
    "charger_binary": ("binary_sensor", "charger_ev_charger_connected", "charger_ev_charger_1_connected"),
}


def test_every_family_of_a_removed_item_goes():
    for fam, (dom, kept_key, old_key) in FAMILIES.items():
        pre = "sem_" if dom in ("sensor", "switch", "binary_sensor") else None
        kept, old = row(dom, kept_key, prefix=pre), row(dom, old_key, prefix=pre)
        assert gone([kept, old], {dom: {kept_key}}) == [old.entity_id], fam


def test_a_configured_items_entities_stay_even_with_prefix_ids():
    rows = [row("time", "charger_ev_charger_target_time"),
            row("time", "charger_ev_charger_1_target_time"),
            row("time", "charger_ev_charger_12_target_time")]
    built = {"time": {"charger_ev_charger_target_time", "charger_ev_charger_12_target_time"}}
    assert gone(rows, built) == ["time.sem_charger_ev_charger_1_target_time"]


def test_a_platform_that_did_not_report_is_untouched():
    rows = [row("time", "charger_old_target_time"), row("sensor", "x", prefix="sem_")]
    assert gone(rows, {"sensor": {"x"}}) == []


def test_no_report_removes_nothing_an_empty_report_clears_the_platform():
    rows = [row("time", "charger_ev_charger_target_time")]
    assert gone(rows, {}) == []
    # the last charger removed: the time platform built nothing on purpose
    assert gone(rows, {"time": set()}) == ["time.sem_charger_ev_charger_target_time"]


def test_other_integrations_and_entries_are_untouched():
    rows = [row("time", "a", platform="other"), row("time", "a", prefix="02OTHER_")]
    assert gone(rows, {"time": {"b"}}) == []


def test_a_disabled_entity_of_a_live_item_stays():
    # built keys include disabled-by-default descriptions; the row's key is built
    rows = [row("sensor", "charger_ev_charger_taper_ratio", prefix="sem_", disabled="integration")]
    assert gone(rows, {"sensor": {"charger_ev_charger_taper_ratio"}}) == []


def _platforms():
    tree = ast.parse((ROOT / "__init__.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PLATFORMS":
            return [elt.attr.lower() for elt in node.value.elts]
    raise AssertionError("PLATFORMS not found")


def test_every_entity_platform_reports_its_keys_and_no_copy_of_the_sweep_is_left():
    from .ast_contracts import call_sites
    reporters = {rel for rel, _l, _k in call_sites("report_built_keys")}
    removers = {rel for rel, _l, _k in call_sites("async_remove")}
    for p in _platforms():
        assert f"{p}.py" in reporters, f"{p}.py does not report its keys"
        assert f"{p}.py" not in removers, f"{p}.py keeps its own sweep"


def test_setup_runs_the_one_sweep():
    from .ast_contracts import calls
    from custom_components.solar_energy_management import async_setup_entry
    assert calls(async_setup_entry, "sweep_stale_entities")
    assert calls(async_setup_entry, "async_forward_entry_setups")


def _notification_ids():
    ids = set()
    for f in ROOT.rglob("*.py"):
        if {"tests", "tools", "scripts"} & set(f.relative_to(ROOT).parts):
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            vals = []
            if isinstance(n, ast.Call):
                vals += [k.value for k in n.keywords if k.arg == "notification_id"]
            if isinstance(n, ast.Dict):
                vals += [v for k, v in zip(n.keys, n.values, strict=True)
                         if isinstance(k, ast.Constant) and k.value == "notification_id"]
            ids |= {v.value for v in vals if isinstance(v, ast.Constant) and isinstance(v.value, str)}
    return ids


def test_uninstall_dismisses_every_notification_sem_can_raise():
    from custom_components.solar_energy_management import cleanup
    ids = _notification_ids()
    assert ids, "no notification ids found"
    assert ids <= set(cleanup.SEM_NOTIFICATION_IDS), sorted(ids - set(cleanup.SEM_NOTIFICATION_IDS))


def test_remove_leftovers_takes_every_sem_dashboard_and_the_classic_copy():
    """The service removed only ``sem-dashboard``; the dashboard SEM makes is
    ``sem-next`` since #1321, and the retired classic one's copy stayed."""
    from .ast_contracts import call_sites
    from custom_components.solar_energy_management import cleanup, dashboard_migration
    assert set(cleanup.SEM_DASHBOARD_PATHS) >= {"sem-dashboard", "sem-next"}
    assert cleanup.CLASSIC_DASHBOARD_COPY == dashboard_migration.COPY_KEY
    assert any(rel == "__init__.py" for rel, _l, _k in call_sites("async_remove_dashboards"))


# ── the live path, through the real setup ────────────────────────────────

def _rows(hass, entry):
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    return {(r.domain, es.key_of(r.unique_id, entry.entry_id), r.unique_id)
            for r in er.async_entries_for_config_entry(reg, entry.entry_id)}


def _of(rows, cid):
    """The rows of one charger: key ``charger_<cid>_<name>``, where the name
    does not start with a number (``ev_charger`` is not ``ev_charger_1``)."""
    head = f"charger_{cid}_"
    return {r for r in rows if (r[1] or "").startswith(head)
            and not r[1][len(head):].split("_", 1)[0].isdigit()}


@pytest.mark.asyncio
async def test_a_removed_chargers_entities_leave_the_registry(sem_real_hass, monkeypatch):
    """Seen live: a charger removed on 09.11 kept its "Charge By" time entity
    for two weeks. Two chargers; ev_charger_1 is removed with the card's ✕
    (the real service and reload). Every row of ev_charger_1 leaves the
    registry, "Charge By" too; the other charger's rows and SEM's own stay
    (but the flow sensors only two chargers have), and a plain reload after
    that removes nothing."""
    from .test_1144_saved_site_limit import _unload
    from .test_1149_second_charger_own_wiring import GO
    from .test_1154_removed_first_charger_flat_keys import (
        FIRST,
        _entry,
        _remove,
        _set_up,
    )
    hass = sem_real_hass
    entry = _entry(hass, [FIRST, GO])
    await _set_up(hass, entry)
    try:
        before = _rows(hass, entry)
        gone_rows = _of(before, "ev_charger_1")
        kept_rows = _of(before, "ev_charger")
        # not vacuous: the removed charger had rows on every per-charger platform
        # (switch has no per-charger entity since #277)
        assert {r[0] for r in gone_rows} >= {"time", "sensor", "number", "select",
                                              "binary_sensor", "button"}
        assert ("time", "charger_ev_charger_1_target_time",
                f"{entry.entry_id}_charger_ev_charger_1_target_time") in gone_rows
        assert kept_rows and not kept_rows & gone_rows
        assert ("time", "charger_ev_charger_target_time",
                f"{entry.entry_id}_charger_ev_charger_target_time") in kept_rows

        await _remove(hass, entry, "ev_charger_1", monkeypatch)
        after = _rows(hass, entry)
        assert not gone_rows & after, sorted(gone_rows & after)
        # per-charger flow sensors exist only with two chargers or more
        # (sensor.py): the kept charger's go too, nothing else does
        flows = {r for r in kept_rows if r[1].startswith("charger_ev_charger_flow_")}
        assert flows and {r[0] for r in flows} == {"sensor"}
        assert after == before - gone_rows - flows

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert _rows(hass, entry) == after
    finally:
        await _unload(hass, entry)


# ── uninstall takes the labels SEM made, not yours ──────────────────────

def _label_ids(hass):
    from homeassistant.helpers import label_registry as lr
    return {lab.label_id for lab in lr.async_get(hass).async_list_labels()}


@pytest.mark.asyncio
async def test_a_label_is_sems_only_as_made_and_on_nothing_else(hass):
    """Real registries: SEM's label goes only while it is as SEM made it and
    only SEM entities of the entries removed carry it."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import label_registry as lr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solar_energy_management import cleanup
    from custom_components.solar_energy_management.consts.labels import SEM_LABELS
    dom = "solar_energy_management"
    sem, other_sem, other = (MockConfigEntry(domain=d) for d in (dom, dom, "demo"))
    for e in (sem, other_sem, other):
        e.add_to_hass(hass)
    labels, ents = lr.async_get(hass), er.async_get(hass)
    for lid, text in SEM_LABELS.items():
        labels.async_create(name=lid, description=text)
    take, on_user, on_sibling, on_device, on_area, renamed, coloured = (
        "sem_power", "sem_ev", "sem_grid", "sem_solar", "sem_home", "sem_battery", "sem_flow")
    assert {take, on_user, on_sibling, on_device, on_area, renamed, coloured} <= set(SEM_LABELS)

    def labelled(entry, platform, uid, lid):
        row = ents.async_get_or_create("sensor", platform, uid, config_entry=entry)
        return ents.async_update_entity(row.entity_id, labels={lid})

    labelled(sem, dom, "sem_a", take)                    # SEM's own entity
    user_row = labelled(other, "demo", "u1", on_user)    # yours
    labelled(other_sem, dom, "sem_b", on_sibling)        # a second SEM entry
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id,
                                                 identifiers={("demo", "d1")})
    dr.async_get(hass).async_update_device(dev.id, labels={on_device})
    ar.async_get(hass).async_create("Garage", labels={on_area})
    labels.async_update(renamed, name="My battery")
    labels.async_update(coloured, color="red")

    n = cleanup.delete_own_labels(hass, [sem.entry_id])
    left = _label_ids(hass)
    assert take not in left
    assert {on_user, on_sibling, on_device, on_area, renamed, coloured} <= left
    # the labels nothing carries went too
    untouched = set(SEM_LABELS) - {on_user, on_sibling, on_device, on_area, renamed, coloured}
    assert not untouched & left and n == len(untouched)
    assert ents.async_get(user_row.entity_id).labels == {on_user}


@pytest.mark.asyncio
async def test_removing_sem_removes_its_labels(sem_real_hass, monkeypatch):
    """Through the real setup and removal: the labels SEM made and put on its
    sensors go with SEM; one you also put on your own entity stays on it."""
    from homeassistant.helpers import entity_registry as er

    from .test_1149_second_charger_own_wiring import GO
    from .test_1154_removed_first_charger_flat_keys import FIRST, _entry, _set_up
    hass = sem_real_hass
    entry = _entry(hass, [FIRST, GO])
    await _set_up(hass, entry)
    ents = er.async_get(hass)
    carried = set().union(*(r.labels for r in er.async_entries_for_config_entry(
        ents, entry.entry_id)))
    assert len(carried) >= 2, carried        # not vacuous: SEM labelled its sensors
    yours = sorted(carried)[0]
    row = ents.async_get_or_create("sensor", "demo", "mine")
    ents.async_update_entity(row.entity_id, labels={yours})

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    left = _label_ids(hass)
    assert yours in left and ents.async_get(row.entity_id).labels == {yours}
    assert not (carried - {yours}) & left, sorted((carried - {yours}) & left)
    assert not er.async_entries_for_config_entry(ents, entry.entry_id)


def test_only_the_last_sem_entry_takes_the_labels():
    """A second SEM entry still uses the labels: they go with the last one."""
    from .ast_contracts import calls
    from custom_components.solar_energy_management import _async_take_sems_own_files
    assert calls(_async_take_sems_own_files, "delete_own_labels")
    src = ast.parse(__import__("inspect").getsource(_async_take_sems_own_files).strip())
    under_last = [n for n in ast.walk(src) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "not remaining"
                  and "delete_own_labels" in ast.unparse(n)]
    assert under_last, "labels are taken outside the last-entry branch"
