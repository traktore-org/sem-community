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


def test_no_report_removes_nothing_an_empty_one_only_per_item_rows():
    rows = [row("time", "charger_ev_charger_target_time"), row("time", "some_global_time")]
    assert gone(rows, {}) == []
    # the last charger removed: the time platform built nothing
    assert gone(rows, {"time": set()}) == ["time.sem_charger_ev_charger_target_time"]


def test_other_integrations_and_entries_are_untouched():
    rows = [row("time", "a", platform="other"), row("time", "a", prefix="02OTHER_")]
    assert gone(rows, {"time": {"b"}}) == []


def test_a_disabled_entity_of_a_live_item_stays():
    # built keys include disabled-by-default descriptions; the row's key is built
    rows = [row("sensor", "charger_ev_charger_taper_ratio", prefix="sem_", disabled="integration")]
    assert gone(rows, {"sensor": {"charger_ev_charger_taper_ratio"}}) == []


def test_every_entity_platform_reports_its_keys_and_no_copy_of_the_sweep_is_left():
    init = (ROOT / "__init__.py").read_text()
    tree = ast.parse(init)
    plats = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PLATFORMS":
            plats = [elt.attr.lower() for elt in node.value.elts]
    assert plats, "PLATFORMS not found"
    for p in plats:
        src = (ROOT / f"{p}.py").read_text()
        assert "report_built_keys(" in src, f"{p}.py does not report its keys"
        assert "registry.async_remove(entity_entry.entity_id)" not in src, f"{p}.py keeps its own sweep"
    i_setup = init.index("async_forward_entry_setups(entry, PLATFORMS)")
    assert init.index("sweep_stale_entities(") > i_setup


def test_uninstall_dismisses_every_notification_sem_can_raise():
    from custom_components.solar_energy_management import cleanup
    import re
    ids = set()
    for f in ROOT.rglob("*.py"):
        if "tests" in f.parts or "tools" in f.parts:
            continue
        ids |= set(re.findall(r'notification_id["\']?\s*[=:]\s*f?["\'](sem_[a-z0-9_]+)', f.read_text()))
    assert ids, "no notification ids found"
    assert ids <= set(cleanup.SEM_NOTIFICATION_IDS), sorted(ids - set(cleanup.SEM_NOTIFICATION_IDS))
