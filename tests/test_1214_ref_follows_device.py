"""#1214 — a charger moved to another integration kept naming the old device.

@bekovan built his own ABB Terra integration and picked its entities for his
charger. The charger ran on them, but a Repair said "Charger EV Charger: its
device is gone": the charger reference (#1054) keeps the device it was made
from, and that was the old integration's device, now removed. The old
device's last answer (``found``) also kept filling each role he did not set.

A ref now names the device its card's entities sit on: when none sits on its
own device and they sit on another one that holds a control, the ref is made
again from the card for that device — once Home Assistant has seen that
device whole (#1147), so a role it offers that the card lacks is cleared and
the card resolves to the same values at every later start.
"""
from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management import charger_refs as cr
from custom_components.solar_energy_management.const import DOMAIN

OLD_DEV, NEW_DEV = "old_abb_device", "new_abb_device"
OLD_LIVE = {
    "ev_connected_sensor": "binary_sensor.abb_terra_ac_plug",
    "ev_charging_sensor": "binary_sensor.abb_terra_ac_charging",
    "ev_charging_power_sensor": "sensor.abb_terra_ac_power",
    "ev_current_control_entity": "number.abb_terra_ac_current_limit",
    "ev_current_sensor": "sensor.abb_terra_ac_current",
}
#: what he picked on his own integration's device
MINE = {
    "ev_connected_sensor": "binary_sensor.abb_terra_charger_plugged_in",
    "ev_charging_sensor": "binary_sensor.abb_terra_charger_charging",
    "ev_charging_power_sensor": "sensor.abb_terra_charger_active_power",
    "ev_current_control_entity": "number.abb_terra_charger_current_limit",
}
SETTINGS = {"name": "EV Charger", "ev_min_current": 6}


def _his_store():
    """The ref as his install holds it: made on the old device, his picks
    folded in as overrides, the old device's answer kept in ``found``."""
    ref = {"id": "ev_charger", "device_id": OLD_DEV, "overrides": dict(MINE),
           "cleared": [], "found": dict(OLD_LIVE), "settings": dict(SETTINGS),
           "stored_complete": True, cr.PLUG_CHECKED: True}
    resolved = [cr.resolve(ref)]
    return [ref], resolved


def _old_gone(eid: str):
    """The old integration was removed: its entities have no device."""
    return NEW_DEV if "abb_terra_charger" in eid else None


def _start(refs, resolved, device_of, live, sure=(NEW_DEV,)):
    return cr.reconcile(data_list=None, legacy=resolved, refs=refs,
                        sig=cr.signature(resolved), device_of=device_of,
                        live_by_device=live, sure=sure)


def test_premise_his_store_names_the_gone_device():
    refs, resolved = _his_store()
    assert cr.problems(refs, resolved, device_exists=lambda d: d == NEW_DEV,
                       entity_exists=lambda e: True)[0]["kind"] == "charger_device_gone"


def test_the_ref_follows_his_entities():
    refs, resolved = _his_store()
    refs2, out = _start(refs, resolved, _old_gone, {})
    assert refs2[0]["device_id"] == NEW_DEV
    assert out == resolved, "SEM drives what it drove"
    assert cr.problems(refs2, out, device_exists=lambda d: d == NEW_DEV,
                       entity_exists=lambda e: e not in OLD_LIVE.values()) == [
        {"kind": "charger_role_entity_gone", "id": "ev_charger",
         "name": "EV Charger", "entity": OLD_LIVE["ev_current_sensor"]}], (
        "the one old entity he never picked again is named on its own")


def test_his_new_device_fills_only_what_he_left_empty():
    """The new device's answer does not override his card: a role the card
    lacks is cleared, as a complete card's refs are made."""
    live_new = {**MINE, "ev_start_stop_entity": "switch.abb_terra_charger_enable"}
    refs, resolved = _his_store()
    refs2, out = _start(refs, resolved, _old_gone, {NEW_DEV: live_new})
    assert refs2[0]["found"] == live_new
    assert "ev_start_stop_entity" in refs2[0]["cleared"]
    assert out == resolved


def test_the_next_start_keeps_it():
    refs, resolved = _his_store()
    refs2, out = _start(refs, resolved, _old_gone, {})
    refs3, out3 = _start(refs2, out, _old_gone, {})
    assert refs3 == refs2
    assert out3 == out


def test_a_ref_with_an_entity_on_its_device_stays():
    """One entity left on the old device: the card still runs on it."""
    refs, resolved = _his_store()

    def device_of(eid):
        if eid == OLD_LIVE["ev_current_sensor"]:
            return OLD_DEV
        return _old_gone(eid)
    refs2, _ = _start(refs, resolved, device_of, {})
    assert refs2[0]["device_id"] == OLD_DEV


def test_a_card_on_no_device_stays():
    """Every entity gone: "its device is gone" is true, so it is kept."""
    refs, resolved = _his_store()
    refs2, _ = _start(refs, resolved, lambda e: None, {})
    assert refs2[0]["device_id"] == OLD_DEV


def test_a_device_another_charger_names_is_left_alone():
    refs, resolved = _his_store()
    other = cr.card_to_ref({"id": "ev_charger_1", "name": "Two", **MINE},
                           NEW_DEV, {})
    refs = refs + [other]
    resolved = resolved + [cr.resolve(other)]
    refs2, _ = _start(refs, resolved, _old_gone, {})
    assert [r["device_id"] for r in refs2] == [OLD_DEV, NEW_DEV]


def test_a_held_role_stays_held():
    """(#1151) ``held`` is worked out at every start; the move keeps it."""
    refs, resolved = _his_store()
    refs[0]["held"] = ["ev_connected_sensor"]
    moved = cr.follow_device(refs, _old_gone, {}, {NEW_DEV})
    assert moved[0]["device_id"] == NEW_DEV
    assert moved[0]["held"] == ["ev_connected_sensor"]
    assert moved[0]["overrides"]["ev_connected_sensor"] == MINE["ev_connected_sensor"]


def test_a_reinstalled_integration_is_followed():
    """The same entity ids on a new device (an integration removed and
    added again): the ref follows, nothing in the card changes."""
    ref = cr.card_to_ref({"id": "ev_charger", **SETTINGS, **OLD_LIVE},
                         OLD_DEV, OLD_LIVE)
    resolved = [cr.resolve(ref, OLD_LIVE)]
    refs2, out = _start([ref], resolved, lambda e: NEW_DEV, {NEW_DEV: OLD_LIVE})
    assert refs2[0]["device_id"] == NEW_DEV
    assert refs2[0]["overrides"] == {}
    assert out == resolved


def test_device_less_refs_are_not_asked():
    ref = cr.card_to_ref({"id": "keba", **MINE}, None, None)
    assert cr.follow_device([ref], _old_gone, {}, {NEW_DEV}) == [ref]


# ── (review) a move never lets a later answer change the card ──────────

def test_a_blind_start_does_not_move():
    """Home Assistant still starting: the new device is not seen whole, so
    its answer may be part of it. The ref waits."""
    refs, resolved = _his_store()
    refs2, out = _start(refs, resolved, _old_gone, {}, sure=())
    assert refs2[0]["device_id"] == OLD_DEV
    assert out == resolved


def test_a_role_the_new_device_offers_later_does_not_fill_the_card():
    """The review's case: moved, then a later start's answer holds a
    start/stop switch the card never had. It must not be driven."""
    live_new = {**MINE, "ev_start_stop_entity": "switch.abb_terra_charger_enable"}
    refs, resolved = _his_store()
    refs2, out2 = _start(refs, resolved, _old_gone, {}, sure=())
    refs3, out3 = _start(refs2, out2, _old_gone, {NEW_DEV: live_new})
    refs4, out4 = _start(refs3, out3, _old_gone, {NEW_DEV: live_new})
    assert refs3[0]["device_id"] == NEW_DEV
    assert out3 == out4 == resolved


def test_a_role_the_user_cleared_stays_cleared():
    """Reinstalled integration: the user had cleared the switch; the new
    device offers it again."""
    switch = "switch.abb_terra_ac_enable"
    live_old = {**OLD_LIVE, "ev_start_stop_entity": switch}
    ref = cr.card_to_ref({"id": "ev_charger", **SETTINGS, **live_old},
                         OLD_DEV, live_old)
    ref["cleared"] = ["ev_start_stop_entity"]
    resolved = [cr.resolve(ref, live_old)]
    assert "ev_start_stop_entity" not in resolved[0], "premise"
    refs2, out = _start([ref], resolved, lambda e: NEW_DEV, {NEW_DEV: live_old})
    assert refs2[0]["device_id"] == NEW_DEV
    assert "ev_start_stop_entity" in refs2[0]["cleared"]
    assert out == resolved


def test_a_meter_is_not_a_charger():
    """No control on the other device (a power meter beside the box): the
    ref stays."""
    refs, resolved = _his_store()

    def device_of(eid):
        return "shelly_meter" if eid == MINE["ev_charging_power_sensor"] else None
    refs2, _ = _start(refs, resolved, device_of, {}, sure=("shelly_meter",))
    assert refs2[0]["device_id"] == OLD_DEV


def test_twin_connectors_move_together():
    two = {k: v.replace("abb_terra_charger", "abb_terra_charger_2")
           for k, v in MINE.items()}
    refs, _ = _his_store()
    refs[0]["settings"]["connector"] = 1
    resolved = [cr.resolve(refs[0])]
    twin = {"id": "ev_charger_1", "device_id": OLD_DEV, "overrides": two,
            "cleared": [], "found": {}, "stored_complete": True,
            "settings": {"name": "Two", "connector": 2}, cr.PLUG_CHECKED: True}
    refs, resolved = refs + [twin], resolved + [cr.resolve(twin)]

    def device_of(eid):
        return NEW_DEV if "abb_terra_charger" in eid else None
    refs2, out = _start(refs, resolved, device_of, {})
    assert [r["device_id"] for r in refs2] == [NEW_DEV, NEW_DEV]
    assert out == resolved


def test_the_plug_check_flag_is_not_made_up():
    """(#1152) A ref not yet asked stays unasked; the check decides."""
    refs, resolved = _his_store()
    del refs[0][cr.PLUG_CHECKED]
    moved = cr.follow_device(refs, _old_gone, {}, {NEW_DEV})
    assert moved[0]["device_id"] == NEW_DEV
    assert cr.PLUG_CHECKED not in moved[0]


# ── on real Home Assistant: the setup step clears the Repair ─────────────

@pytest.mark.asyncio
async def test_the_setup_step_clears_his_repair(hass):
    src = MockConfigEntry(domain="abb_terra_charger")
    src.add_to_hass(hass)
    src.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id, identifiers={("abb_terra_charger", "1")},
        name="ABB Terra Charger")
    ereg = er.async_get(hass)
    for eid in MINE.values():
        domain, obj = eid.split(".", 1)
        ereg.async_get_or_create(domain, "abb_terra_charger", obj,
                                 suggested_object_id=obj, config_entry=src,
                                 device_id=device.id)
        hass.states.async_set(eid, "0")
    refs, resolved = _his_store()
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        cr.REFS_KEY: refs, cr.LEGACY_KEY: resolved,
        cr.SIG_KEY: cr.signature(resolved)})
    entry.add_to_hass(hass)
    ir.async_create_issue(hass, DOMAIN, "charger_device_gone_ev_charger",
                          is_fixable=False, severity=ir.IssueSeverity.WARNING,
                          translation_key="charger_device_gone",
                          translation_placeholders={"name": "EV Charger"})

    (card,) = cr.async_reconcile(hass, entry)

    assert entry.options[cr.REFS_KEY][0]["device_id"] == device.id
    assert card == resolved[0]
    issues = {i for (d, i) in ir.async_get(hass).issues if d == DOMAIN}
    assert "charger_device_gone_ev_charger" not in issues
    assert ("charger_role_entity_gone_ev_charger_"
            + OLD_LIVE["ev_current_sensor"]) in issues


def test_it_runs_before_anything_reads_the_device():
    import inspect
    src = inspect.getsource(cr.reconcile)
    assert src.index("follow_device(") < src.index("refresh_found(")
    assert src.index("apply_legacy_edit(") < src.index("follow_device(")
