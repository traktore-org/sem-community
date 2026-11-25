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
