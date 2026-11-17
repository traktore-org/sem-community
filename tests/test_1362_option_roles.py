"""(#1362) A grid-charge select and a hold select, proposed by their OPTIONS.

An integration SEM has no vocabulary for (a Voltronic-family inverter whose
only controls are two selects) still has option words that say what each
select does. The crawler reads those words, on the device of a battery /
solar / grid power sensor, and proposes the select with the option that
means it. Selects of other kinds must propose nothing.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management import hardware_detection as hd
from custom_components.solar_energy_management.consts import role_lexicon as lex

DESS_MODE = ["SBU", "Solar", "Utility"]
DESS_CHARGE = ["Solar and mains", "Solar only"]
AXPERT_MODE = ["Utility first", "Solar first", "SBU"]
AXPERT_CHARGE = ["Solar first", "Solar + Utility", "Only Solar"]


def _ent(eid, dev="d1", platform="dess_monitor", **kw):
    base = dict(entity_id=eid, platform=platform, device_id=dev,
                translation_key=None, original_name=None, unique_id="",
                original_device_class=None, disabled_by=None,
                config_entry_id="e1")
    base.update(kw)
    return SimpleNamespace(**base)


def _site(selects, dev="d1", power="sensor.inv_battery_power"):
    """One device: a battery power sensor and the given ``{eid: options}``."""
    ents = [_ent(power, dev, original_device_class="power")]
    ents += [_ent(eid, dev) for eid in selects]
    reg = SimpleNamespace(entities={e.entity_id: e for e in ents})
    state = lambda eid: (SimpleNamespace(
        state=opts[0], attributes={"options": opts})
        if (opts := selects.get(eid)) else None)
    return reg, state


def _roles(rows):
    return {r: p for row in rows for r, p in row["proposed_roles"].items()}


def test_dess_shape_proposes_both_with_their_options():
    reg, st = _site({"select.inv_output_mode": DESS_MODE,
                     "select.inv_charge_source": DESS_CHARGE})
    got = _roles(hd.propose_option_roles(reg, state_of=st))
    assert got["battery_charge_select"]["entity"] == "select.inv_charge_source"
    assert got["battery_charge_select"]["option"] == "Solar and mains"
    assert got["battery_hold_select"]["entity"] == "select.inv_output_mode"
    assert got["battery_hold_select"]["option"] == "Utility"


def test_axpert_shape_proposes_both():
    reg, st = _site({"select.a_mode": AXPERT_MODE,
                     "select.a_charger": AXPERT_CHARGE})
    got = _roles(hd.propose_option_roles(reg, state_of=st))
    assert got["battery_charge_select"]["option"] == "Solar + Utility"
    assert got["battery_hold_select"]["option"] == "Utility first"


def test_the_proposal_writes_the_select_and_its_option():
    reg, st = _site({"select.c": DESS_CHARGE})
    p = _roles(hd.propose_option_roles(reg, state_of=st))["battery_charge_select"]
    assert p["config_key"] == "battery_charge_select_entity"
    assert p["write_extra"] == {"battery_charge_select_option": "Solar and mains"}
    assert p["action"] == "set_option"


def test_hold_has_no_button_until_its_setting_exists():
    reg, st = _site({"select.m": DESS_MODE})
    p = _roles(hd.propose_option_roles(reg, state_of=st))["battery_hold_select"]
    assert p["config_key"] == "battery_hold_select_entity"
    assert p["option_key"] == "battery_hold_select_option"
    assert p["action"] == "observe_only"


# Option sets of real selects that must NOT be proposed. Each one sits on a
# device with a battery power sensor, the case where the shape could fire.
NOT_THESE = {
    "huawei working mode": ["Maximise self consumption", "Fully fed to grid",
                            "Time of use(LG)", "Time of use(LUNA2000)",
                            "Third party dispatch"],
    "sessy strategy": ["api", "eco", "nom", "idle", "roi"],
    "goodwe operation mode": ["General mode", "Off grid mode", "Backup mode",
                              "Eco mode", "Peak shaving", "Self use"],
    "deye work mode": ["Selling First", "Zero Export To Load",
                       "Zero Export To CT"],
    "deye priority": ["Load First", "Battery First"],
    "solis storage mode": ["Self-Use", "Feed-in priority", "Off-Grid",
                           "Peak shaving"],
    "sma battery mode": ["Automatic", "Manual", "Time controlled"],
    "victron ess mode": ["Optimized with BatteryLife",
                         "Optimized without BatteryLife",
                         "Keep batteries charged", "External control"],
    "victron inverter mode": ["On", "Off", "Charger only", "Inverter only",
                              "Eco"],
    "ev solar mode": ["Solar", "Fast", "Eco"],
    "ev pv mode": ["PV only", "Min + PV", "Now"],
    "ev charge mode": ["Default", "Eco", "Next trip"],
    "heat pump mode": ["Auto", "Heating", "Cooling", "Off"],
    "heat pump comfort": ["Eco", "Comfort", "Boost"],
    "grid import mode": ["grid_import", "grid_export", "battery_charge"],
    "on off": ["on", "off"],
}


@pytest.mark.parametrize("name", sorted(NOT_THESE))
def test_other_selects_propose_nothing(name):
    reg, st = _site({"select.some_mode": NOT_THESE[name]})
    assert hd.propose_option_roles(reg, state_of=st) == []


def test_an_ev_select_with_the_charge_shape_is_vetoed_by_its_name():
    both = ["Solar only", "Solar + Grid", "Fast"]
    reg, st = _site({"select.wallbox_charge_mode": both})
    assert hd.propose_option_roles(reg, state_of=st) == []
    reg, st = _site({"select.inv_charge_source": both})
    assert "battery_charge_select" in _roles(hd.propose_option_roles(reg, state_of=st))


def test_a_select_on_a_device_without_a_power_sensor_is_not_proposed():
    ent = _ent("select.lonely_charge", "d9")
    reg = SimpleNamespace(entities={ent.entity_id: ent})
    st = lambda eid: SimpleNamespace(state="x", attributes={"options": DESS_CHARGE})
    assert hd.propose_option_roles(reg, state_of=st) == []


def test_two_candidates_of_one_role_on_a_device_propose_nothing():
    reg, st = _site({"select.a": DESS_CHARGE, "select.b": AXPERT_CHARGE})
    assert hd.propose_option_roles(reg, state_of=st) == []


def test_the_same_shape_on_two_devices_is_two_rows():
    reg, st = _site({"select.a": DESS_CHARGE})
    other, _ = _site({"select.b": DESS_CHARGE}, dev="d2", power="sensor.x_pv_power")
    reg.entities.update(other.entities)
    st2 = lambda eid: SimpleNamespace(state="x", attributes={"options": DESS_CHARGE})
    rows = hd.propose_option_roles(reg, state_of=st2)
    assert len(rows) == 2


def test_a_select_already_in_use_is_not_news():
    reg, st = _site({"select.c": DESS_CHARGE})
    assert hd.propose_option_roles(
        reg, state_of=st, configured_entities={"select.c"}) == []


def test_no_state_no_proposal():
    reg, _ = _site({"select.c": DESS_CHARGE})
    assert hd.propose_option_roles(reg, state_of=None) == []
    assert hd.propose_option_roles(reg, state_of=lambda e: None) == []


def test_a_select_that_fits_both_is_split_by_its_name():
    opts = ["SBU", "Utility", "Solar and mains", "Solar only"]
    assert set(lex.option_roles(opts, "select.x_charger_source")) == {
        "battery_charge_select"}
    assert set(lex.option_roles(opts, "select.x_output_mode")) == {
        "battery_hold_select"}


@pytest.mark.parametrize("opts,option", [
    (["Solar + Utility", "Only Solar"], "Solar + Utility"),
    (["SNU", "OSO", "CSO"], "SNU"),
    (["Solar and AC", "Solar only"], "Solar and AC"),
    (["Solar + Line", "Solar only"], "Solar + Line"),
])
def test_charge_words(opts, option):
    assert lex.option_roles(opts) == {"battery_charge_select": option}


@pytest.mark.parametrize("opts,option", [
    (["SBU", "Utility"], "Utility"),
    (["Battery first", "Grid first"], "Grid first"),
    (["Solar Battery Utility", "Line first"], "Line first"),
    (["SBU", "USB"], "USB"),
])
def test_hold_words(opts, option):
    assert lex.option_roles(opts) == {"battery_hold_select": option}


def test_the_detection_report_carries_the_proposals_to_the_card():
    reg, st = _site({"select.inv_charge_source": DESS_CHARGE})
    hass = SimpleNamespace(is_running=True, states=SimpleNamespace(get=st))
    rep = hd.build_detection_report(hass, registry=reg)
    got = _roles(rep["roster_proposals"])
    assert got["battery_charge_select"]["entity"] == "select.inv_charge_source"
    rep = hd.build_detection_report(
        hass, registry=reg, configured_entities={"select.inv_charge_source"})
    assert "battery_charge_select" not in _roles(rep["roster_proposals"])
