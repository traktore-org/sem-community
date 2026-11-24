"""(#1381 D19) Old charge-mode names in the user's automations and scripts.

HA core checks ``select.select_option`` against the select's options before
SEM sees the call, so an automation that still picks ``solar_only`` fails.
SEM's own ``set_option`` keeps the old names. A Repair names every automation
or script that still uses an old name, with the name to use now.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.old_mode_names import (
    find_old_mode_uses,
)

SEL = "select.sem_charger_ev_charger_charge_mode"


def test_a_select_option_call_with_an_old_name_is_found():
    cfg = {"alias": "Night car", "actions": [
        {"action": "select.select_option", "target": {"entity_id": SEL},
         "data": {"option": "min_plus_solar"}}]}
    assert find_old_mode_uses("automation", [cfg]) == [
        ("Night car", "min_plus_solar", "sun_tariff")]


def test_old_service_key_and_entity_in_data_are_found_too():
    cfg = {"alias": "Old style", "action": [
        {"service": "select.select_option",
         "data": {"entity_id": [SEL], "option": "solar_only"}}]}
    assert find_old_mode_uses("script", [cfg]) == [("Old style", "solar_only", "sun")]


def test_a_state_condition_or_trigger_on_an_old_name_is_found():
    cfg = {"alias": "When max", "triggers": [
        {"trigger": "state", "entity_id": SEL, "to": "always_max"}],
        "conditions": [{"condition": "state", "entity_id": SEL, "state": "off"}]}
    assert find_old_mode_uses("automation", [cfg]) == [("When max", "always_max", "now")]


def test_new_names_and_other_selects_are_left_alone():
    cfg = {"alias": "Fine", "actions": [
        {"action": "select.select_option", "target": {"entity_id": SEL},
         "data": {"option": "sun"}},
        {"action": "select.select_option", "target": {"entity_id": "select.other"},
         "data": {"option": "solar_only"}}]}
    assert find_old_mode_uses("automation", [cfg]) == []


def test_sems_own_set_option_service_is_not_reported():
    cfg = {"alias": "SEM svc", "actions": [
        {"action": "solar_energy_management.set_option",
         "data": {"key": "charge_mode", "value": "solar_only"}}]}
    assert find_old_mode_uses("automation", [cfg]) == []


def test_a_config_without_an_alias_is_named_by_its_id():
    cfg = {"id": "1234", "actions": [
        {"action": "select.select_option", "target": {"entity_id": SEL},
         "data": {"option": "solar_plus_battery"}}]}
    assert find_old_mode_uses("automation", [cfg]) == [("1234", "solar_plus_battery", "sun")]


def test_the_check_runs_after_start_and_after_reloads():
    from .ast_contracts import call_sites
    sites = call_sites("check_old_mode_uses")
    assert any(str(p).endswith("__init__.py") for p, _l, _k in sites), sites
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "__init__.py").read_text())
    events = {n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "async_listen"
              and n.args and isinstance(n.args[0], ast.Name) is False
              and isinstance(n.args[0], ast.Constant)}
    loops = {c.value for n in ast.walk(tree) if isinstance(n, ast.For)
             and isinstance(n.iter, ast.Tuple)
             for c in n.iter.elts if isinstance(c, ast.Constant)}
    assert {"automation_reloaded", "script_reloaded"} <= (events | loops)


def test_the_repair_has_its_words_in_every_language():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    files = [root / "strings.json", *sorted((root / "translations").glob("*.json"))]
    assert len(files) == 17
    for f in files:
        issue = json.loads(f.read_text())["issues"]["old_charge_mode_names"]
        assert issue["title"] and "{uses}" in issue["description"], f.name


# ── D32: the text of the whole config is scanned ─────────────────────────

def test_d32_a_template_condition_is_found():
    cfg = {"alias": "Tpl", "conditions": [
        {"condition": "template",
         "value_template": "{{ is_state('" + SEL + "', 'solar_only') }}"}]}
    assert ("Tpl", "solar_only", "sun") in find_old_mode_uses("automation", [cfg])


def test_d32_an_option_held_in_a_variable_is_found():
    cfg = {"alias": "Var", "variables": {"mode": "always_max"}, "actions": [
        {"action": "select.select_option", "target": {"entity_id": SEL},
         "data": {"option": "{{ mode }}"}}]}
    assert ("Var", "always_max", "now") in find_old_mode_uses("automation", [cfg])


def test_d32_an_entity_held_in_a_variable_is_found():
    cfg = {"alias": "Ent", "variables": {"ent": SEL}, "actions": [
        {"action": "select.select_option",
         "target": {"entity_id": "{{ ent }}"},
         "data_template": {"option": "min_plus_solar"}}]}
    assert ("Ent", "min_plus_solar", "sun_tariff") in find_old_mode_uses(
        "automation", [cfg])


def test_d32_an_entity_built_from_pieces_is_found():
    cfg = {"alias": "Built", "actions": [
        {"action": "select.select_option",
         "target": {"entity_id": "select.sem_charger_{{ cid }}_charge_mode"},
         "data": {"option": "solar_plus_cheap"}}]}
    assert ("Built", "solar_plus_cheap", "sun_tariff") in find_old_mode_uses(
        "automation", [cfg])


def test_d32_a_comma_string_of_entities_is_found():
    cfg = {"alias": "Comma", "actions": [
        {"action": "select.select_option",
         "data": {"entity_id": "select.x, " + SEL, "option": "solar_only"}}]}
    assert ("Comma", "solar_only", "sun") in find_old_mode_uses("script", [cfg])


def test_d32_blueprint_inputs_are_scanned():
    cfg = {"alias": "BP", "use_blueprint": {"path": "x.yaml", "input": {
        "charger_select": SEL, "mode": "solar_plus_battery"}}}
    assert ("BP", "solar_plus_battery", "sun") in find_old_mode_uses(
        "automation", [cfg])


def test_d32_an_old_word_without_a_sem_charge_mode_select_is_not_reported():
    cfg = {"alias": "Other", "actions": [
        {"action": "input_select.select_option",
         "target": {"entity_id": "input_select.my_modes"},
         "data": {"option": "solar_only"}}]}
    assert find_old_mode_uses("automation", [cfg]) == []


def test_d32_the_repair_text_names_its_limit():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    en = json.loads((root / "strings.json").read_text())
    text = en["issues"]["old_charge_mode_names"]["description"]
    assert "outside the UI" in text
