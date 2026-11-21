"""#1147 — a saved charger kept a role detection stopped giving.

A charger SEM saved by itself is stored as a device reference. The reference
keeps what detection found last (``found``), so a start that cannot ask
detection still works. But ``refresh_found`` only ever added to it: when a
detection fix stopped giving a role, the old value stayed and every start
used it again (a Zaptec Go saved before #1142 kept the online sensor as its
charge; #1144 needed its own drop for the site limit).

Replacing ``found`` whole at every start would make roles come and go: a
start during Home Assistant's boot reads no states, and an integration that
is still loading shows part of its device. So a role is forgotten only when
detection saw the whole device (``charger_refs.sure_devices``) and no longer
gives it. What the user set (``overrides``, ``cleared``) is never touched.
"""
from __future__ import annotations

import json

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management import charger_refs as cr
from custom_components.solar_energy_management.const import DOMAIN

from .test_1139_orphan_charger_repairs import GO, _zaptec

DEV = "go-1"
POWER = "sensor.go_charge_power"
CURRENT = "number.go_charger_max_current"
START = "button.go_resume_charging"
PLUG = "sensor.go_charger_mode"
#: what the old crawler read as the charge: a sensor it no longer gives
OLD = "binary_sensor.go_online"

TODAY = {"ev_charging_power_sensor": POWER,
         "ev_current_control_entity": CURRENT,
         "ev_start_stop_entity": START}
THEN = {**TODAY, "ev_charging_sensor": OLD}
SAVE = {"id": "zaptec_1", "name": "Zaptec Charger", **THEN}


def _device(eid):
    return DEV if ".go_" in eid else None


def _stored():
    """The save as a ref, made by a start whose crawler gave ``OLD``."""
    return cr.reconcile(data_list=[dict(SAVE)], legacy=None, refs=None,
                        sig=None, device_of=_device,
                        live_by_device={DEV: dict(THEN)})


def _next(refs, resolved, live, sure, **kw):
    return cr.reconcile(data_list=None, legacy=resolved, refs=refs,
                        sig=cr.signature(resolved), device_of=_device,
                        live_by_device=live, sure=sure, **kw)


# ── premise ──────────────────────────────────────────────────────────────

def test_premise_found_keeps_a_role_the_crawler_stopped_giving():
    refs, _resolved = _stored()
    (merged,) = cr.refresh_found(refs, {DEV: dict(TODAY)})
    assert merged["found"]["ev_charging_sensor"] == OLD
    assert cr.resolve(merged, TODAY)["ev_charging_sensor"] == OLD


def test_premise_without_sure_the_setup_step_keeps_it():
    """A pure caller that does not say which devices were seen whole gets
    the old merge: nothing is forgotten."""
    refs, resolved = _stored()
    _refs, (card,) = cr.reconcile(
        data_list=None, legacy=resolved, refs=refs,
        sig=cr.signature(resolved), device_of=_device,
        live_by_device={DEV: dict(TODAY)})
    assert card["ev_charging_sensor"] == OLD


# ── the rule ─────────────────────────────────────────────────────────────

class TestForget:

    def test_a_device_seen_whole_forgets_it(self):
        refs, resolved = _stored()
        logged = []
        refs, (card,) = _next(refs, resolved, {DEV: dict(TODAY)}, {DEV},
                              log=logged.append)
        assert "ev_charging_sensor" not in card
        assert "ev_charging_sensor" not in refs[0]["found"]
        assert OLD not in json.dumps(refs)
        assert any("#1147" in m and OLD in m for m in logged)

    def test_a_device_not_seen_whole_keeps_it(self):
        """Boot, or the integration still loading: the device keeps what
        was found before, so roles never come and go."""
        refs, resolved = _stored()
        refs, (card,) = _next(refs, resolved, {DEV: dict(TODAY)}, set())
        assert card["ev_charging_sensor"] == OLD
        assert refs[0]["found"]["ev_charging_sensor"] == OLD

    def test_a_device_the_crawler_did_not_answer_for_keeps_it(self):
        refs, resolved = _stored()
        refs, (card,) = _next(refs, resolved, {}, {DEV})
        assert card["ev_charging_sensor"] == OLD

    def test_boot_then_reload_then_boot(self):
        """Boot keeps it, the reload (seen whole) forgets it, and the next
        boot cannot bring it back: it is no longer remembered."""
        refs, resolved = _stored()
        refs, resolved = _next(refs, resolved, {DEV: dict(TODAY)}, set())
        assert resolved[0]["ev_charging_sensor"] == OLD
        refs, resolved = _next(refs, resolved, {DEV: dict(TODAY)}, {DEV})
        assert "ev_charging_sensor" not in resolved[0]
        refs, resolved = _next(refs, resolved, {}, set())
        assert "ev_charging_sensor" not in resolved[0]

    def test_a_role_the_user_set_stays(self):
        """An override is the user's: detection not giving it changes
        nothing."""
        refs, resolved = _stored()
        mine = {**resolved[0], "ev_charging_sensor": "binary_sensor.my_relay"}
        refs, resolved = cr.reconcile(
            data_list=None, legacy=[mine], refs=refs,
            sig=cr.signature(resolved), device_of=_device,
            live_by_device={DEV: dict(TODAY)}, sure={DEV})
        assert resolved[0]["ev_charging_sensor"] == "binary_sensor.my_relay"
        assert refs[0]["overrides"] == {
            "ev_charging_sensor": "binary_sensor.my_relay"}

    def test_a_role_the_user_cleared_stays_cleared(self):
        refs, resolved = _stored()
        cleared = {k: v for k, v in resolved[0].items()
                   if k != "ev_start_stop_entity"}
        refs, resolved = cr.reconcile(
            data_list=None, legacy=[cleared], refs=refs,
            sig=cr.signature(resolved), device_of=_device,
            live_by_device={DEV: dict(TODAY)}, sure={DEV})
        assert refs[0]["cleared"] == ["ev_start_stop_entity"]
        assert "ev_start_stop_entity" not in resolved[0]

    def test_a_role_detection_still_gives_stays(self):
        refs, resolved = _stored()
        refs, (card,) = _next(refs, resolved, {DEV: dict(THEN)}, {DEV})
        assert card["ev_charging_sensor"] == OLD

    def test_another_device_is_not_touched(self):
        refs, resolved = _stored()
        refs, (card,) = _next(refs, resolved, {DEV: dict(TODAY)}, {"other"})
        assert card["ev_charging_sensor"] == OLD

    def test_a_device_less_charger_is_never_touched(self):
        keba = {"id": "keba", "name": "KEBA",
                "ev_charging_power_sensor": "sensor.keba_power",
                "ev_charger_service": "keba.set_current"}
        refs, resolved = cr.reconcile(
            data_list=[keba], legacy=None, refs=None, sig=None,
            device_of=lambda e: None, live_by_device={}, sure={DEV})
        refs, (card,) = _next(refs, resolved, {}, {DEV, None})
        assert card == keba

    def test_a_ref_left_half_can_be_replaced(self):
        """As with a refused role (#1144): a ref the forgetting left
        incomplete is no longer marked complete, so a new card for the box
        can take its place (#1054)."""
        save = {"id": "z", "name": "Z", **THEN,
                "ev_current_control_entity": "number.go_old_limit"}
        then = dict(save)
        then.pop("id")
        then.pop("name")
        refs, resolved = cr.reconcile(
            data_list=[save], legacy=None, refs=None, sig=None,
            device_of=_device, live_by_device={DEV: then})
        assert refs[0]["stored_complete"] is True, "premise"
        bare = {"ev_charging_sensor": OLD}
        refs, _ = _next(refs, resolved, {DEV: bare}, {DEV})
        assert refs[0]["stored_complete"] is False


# ── which devices are seen whole, on real Home Assistant ─────────────────

MODE = f"sensor.{GO}_charger_mode"


async def _go(hass):
    await _zaptec(hass, with_limit=False)
    (zaptec,) = hass.config_entries.async_entries("zaptec")
    reg = er.async_get(hass)
    dev = reg.async_get(MODE).device_id
    return zaptec, reg, dev


async def test_sure_needs_a_loaded_integration(hass):
    zaptec, _reg, dev = await _go(hass)
    assert hass.is_running, "premise: the test hass has started"
    assert cr.sure_devices(hass, [dev]) == set()
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    assert cr.sure_devices(hass, [dev]) == {dev}


async def test_sure_needs_home_assistant_started(hass):
    zaptec, _reg, dev = await _go(hass)
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    hass.set_state(CoreState.starting)
    try:
        assert cr.sure_devices(hass, [dev]) == set()
    finally:
        hass.set_state(CoreState.running)


async def test_sure_needs_every_entity_to_have_a_state(hass):
    zaptec, _reg, dev = await _go(hass)
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    hass.states.async_remove(f"sensor.{GO}_charge_power")
    assert cr.sure_devices(hass, [dev]) == set()


async def test_a_disabled_entity_does_not_count(hass):
    zaptec, reg, dev = await _go(hass)
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    reg.async_update_entity(MODE, disabled_by=er.RegistryEntryDisabler.USER)
    hass.states.async_remove(MODE)
    assert cr.sure_devices(hass, [dev]) == {dev}


async def test_an_unknown_device_is_not_sure(hass):
    zaptec, _reg, _dev = await _go(hass)
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    assert cr.sure_devices(hass, ["no-such-device"]) == set()


async def test_the_setup_step_forgets_only_when_the_integration_is_loaded(hass):
    """The user turned "Charger mode" off: detection no longer gives it as
    the plug and the charge. The save keeps it while the Zaptec
    integration is not loaded, and forgets it on a start where it is."""
    zaptec, reg, dev = await _go(hass)
    live = cr.live_charger_roles(hass)[dev]
    assert live.get("ev_connected_sensor") == MODE, "premise"
    save = {"id": "zaptec_go", "name": "Zaptec Charger",
            **{k: v for k, v in live.items() if k in cr.ROLE_KEYS}}
    device_of = (lambda e: getattr(reg.async_get(e), "device_id", None))
    refs, resolved = cr.reconcile(
        data_list=[save], legacy=None, refs=None, sig=None,
        device_of=device_of, live_by_device={dev: live})
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        cr.REFS_KEY: refs, cr.LEGACY_KEY: resolved,
        cr.SIG_KEY: cr.signature(resolved)})
    entry.add_to_hass(hass)
    reg.async_update_entity(MODE, disabled_by=er.RegistryEntryDisabler.USER)
    hass.states.async_remove(MODE)
    assert "ev_connected_sensor" not in cr.live_charger_roles(hass).get(
        dev, {}), "premise: detection no longer gives it"

    (card,) = cr.async_reconcile(hass, entry)
    assert card["ev_connected_sensor"] == MODE, "not loaded: kept"
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    (card,) = cr.async_reconcile(hass, entry)
    assert MODE not in json.dumps(card)
    assert MODE not in json.dumps(entry.options[cr.REFS_KEY])
    # the next start does not bring it back, loaded or not
    zaptec.mock_state(hass, ConfigEntryState.NOT_LOADED)
    (card,) = cr.async_reconcile(hass, entry)
    assert MODE not in json.dumps(card)


def test_the_forgetting_runs_before_the_plug_check():
    """``hold_new_state`` stays the last word on ``refs`` (#1151); the
    forgetting comes before it."""
    import ast
    import inspect
    src = inspect.getsource(cr.reconcile)
    assert src.index("forget_stale(") < src.index("hold_new_state(")
    tree = ast.parse(src.lstrip())
    names = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)]
    assert "forget_stale" in names


async def test_1312_the_deprecated_config_entries_shim_is_not_read(hass, monkeypatch):
    """(#1312) HA warns on ``DeviceEntry.config_entries`` and drops it in
    2027.10. The device's own ``config_entry_id`` answers the same question:
    with the shim made to fail, a sure device is still sure."""
    from homeassistant.helpers import device_registry as dr

    def gone(self):
        raise AttributeError("config_entries was removed (HA 2027.10)")

    monkeypatch.setattr(dr.DeviceEntry, "config_entries", property(gone))
    zaptec, _reg, dev = await _go(hass)
    zaptec.mock_state(hass, ConfigEntryState.LOADED)
    assert cr.sure_devices(hass, [dev]) == {dev}
