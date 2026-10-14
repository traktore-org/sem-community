"""#1054 — a charger is a device reference; the crawler fills in its roles.

Pure tests of ``charger_refs``: the migration, the resolver, the writers'
edits, the one-ref-per-device rule and the Repairs. The real-Home-Assistant
replay of weindler's install is ``test_1054_weindler_replay.py``.
"""
from __future__ import annotations

import random

import pytest

from custom_components.solar_energy_management import _heal_ev_chargers_options
from custom_components.solar_energy_management.charger_refs import (
    ROLE_KEYS,
    card_to_ref,
    problems,
    reconcile,
    refs_from_cards,
    resolve,
    signature,
)
from custom_components.solar_energy_management.hardware_detection import (
    CHARGER_ENTITY_KEYS,
    charger_is_complete,
)

P = "sensor.goecharger_wallbox_go_e"
GOE_DEV = "118c19168da8cdf95739aaf95b2598a4"
#: the crawler's answer for weindler's go-e (tests/integrations_rig/crawler/goecharger.json)
GOE_LIVE = {
    "ev_charger_service": "goecharger.set_max_current",
    "ev_charger_service_data": '{"charger_name": "wallbox_go_e"}',
    "ev_charging_power_sensor": f"{P}_p_all",
    "ev_charging_sensor": f"{P}_car_status",
    "ev_connected_sensor": f"{P}_car_status",
    "ev_service_param_name": "max_current",
    "ev_session_energy_sensor": f"{P}_current_session_charged_energy",
    "ev_start_stop_entity": "switch.goecharger_wallbox_go_e_allow_charging",
    "ev_total_energy_sensor": f"{P}_energy_total",
}
OLD = {"id": "goecharger_28eb748ac3", "name": "Goecharger Charger",
       "ev_total_energy_sensor": f"{P}_energy_total_corrected"}
NEW = {**GOE_LIVE, "id": f"goecharger_{GOE_DEV}", "name": "go-eCharger",
       "ev_min_current": 6, "ev_surplus_priority": 4}

#: PROD's real charger (read from HA-PROD 11.10.2026): a KEBA P30 whose
#: entities have no registry device — device-less.
PROD_KEBA = {
    "_platform": "keba", "charge_mode": "solar_plus_battery",
    "daily_ev_target": 0.0, "daily_ev_target_max": 200.0,
    "ev_battery_capacity_kwh": 40.0, "ev_charge_mode_entity": None,
    "ev_charge_mode_start": None, "ev_charge_mode_stop": None,
    "ev_charger_efficiency": 0.92, "ev_charger_service": "keba.set_current",
    "ev_charger_service_entity_id": "binary_sensor.keba_p30_plug",
    "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
    "ev_charging_sensor": "binary_sensor.keba_p30_charging_state",
    "ev_connected_sensor": "binary_sensor.keba_p30_plug",
    "ev_current_control_entity": None, "ev_current_sensor": "sensor.keba_p30_max_current",
    "ev_kwh_per_100km": 15.0, "ev_max_current": 16.0, "ev_min_current": 8.0,
    "ev_phase_switch_entity": None, "ev_phase_switch_value_1p": None,
    "ev_phase_switch_value_3p": None, "ev_phases": 3.0,
    "ev_service_param_name": "current",
    "ev_session_energy_sensor": "sensor.keba_p30_session_energy",
    "ev_start_stop_entity": None, "ev_surplus_priority": 5.0,
    "ev_target_soc": 80.0, "ev_target_soc_max": 100.0,
    "ev_total_energy_sensor": "sensor.keba_p30_total_energy", "id": "ev_charger",
    "initial_current": 10.0, "name": "EV Charger", "phase_mode": None,
    "vehicle_min_current": None, "vehicle_range_entity": None, "vehicle_soc_entity": None,
}


def _goe_device(eid: str):
    return GOE_DEV if "goecharger_wallbox_go_e" in eid else None


def _no_device(eid: str):
    return None


LIVE = {GOE_DEV: GOE_LIVE}


# ── the resolver gives back what was stored ───────────────────────────────

class TestNothingChangesForAWorkingCharger:

    def test_prod_keba_is_byte_identical(self):
        """PROD's KEBA is device-less: its card is kept whole."""
        out = reconcile(data_list=None, legacy=[dict(PROD_KEBA)], refs=None,
                        sig=None, device_of=_no_device, live_by_device={})
        refs, resolved = out
        assert resolved == [PROD_KEBA]
        assert refs[0]["device_id"] is None
        # and again on the next start, with no edit
        out2 = reconcile(data_list=None, legacy=resolved, refs=refs,
                         sig=signature(resolved), device_of=_no_device,
                         live_by_device={})
        assert out2[1] == [PROD_KEBA]

    def test_a_device_less_charger_ignores_the_crawler(self):
        ref = card_to_ref(dict(PROD_KEBA), None, None)
        assert resolve(ref, {"ev_charging_power_sensor": "sensor.other"}) == PROD_KEBA

    def test_complete_cards_resolve_to_themselves(self):
        """Property: any complete card on a device, any crawler answer."""
        rnd = random.Random(1054)
        roles = sorted(ROLE_KEYS)
        for _ in range(300):
            live = {k: f"x.{k}_{rnd.randint(0, 2)}" for k in roles if rnd.random() < .7}
            card = {"id": "c", "name": "n", "ev_min_current": 6}
            for k in roles:
                r = rnd.random()
                if r < .45:
                    card[k] = live.get(k) or f"x.{k}_own"
                elif r < .6:
                    card[k] = f"x.{k}_own"
                elif r < .7:
                    card[k] = None
            for k in ("ev_charging_power_sensor", "ev_charger_service"):
                if not card.get(k):
                    card[k] = f"x.{k}_req"
            assert charger_is_complete(card)
            ref = card_to_ref(card, "dev", live)
            assert resolve(ref, live) == card
            assert resolve(ref, {}) == card


# ── the migration: one ref per device ─────────────────────────────────────

class TestTheMigration:

    def test_weindler_beta13_one_charger_the_working_one(self):
        """data = [half], options = [half, complete] → one ref, the go-e, in
        the half card's place."""
        refs, resolved = reconcile(
            data_list=[dict(OLD)], legacy=[dict(OLD), dict(NEW)], refs=None,
            sig=None, device_of=_goe_device, live_by_device=LIVE)
        assert [r["id"] for r in refs] == [NEW["id"]]
        assert resolved == [NEW]

    def test_weindler_beta15_the_half_card_is_completed(self):
        """Only the half card left: the crawler completes it."""
        refs, resolved = reconcile(
            data_list=[dict(OLD)], legacy=[dict(OLD)], refs=None, sig=None,
            device_of=_goe_device, live_by_device=LIVE)
        assert [r["id"] for r in refs] == [OLD["id"]]
        card = resolved[0]
        assert charger_is_complete(card)
        assert card["ev_charger_service"] == "goecharger.set_max_current"
        # its own energy counter is kept: the user set it
        assert card["ev_total_energy_sensor"] == f"{P}_energy_total_corrected"

    def test_the_primary_keeps_its_place(self):
        keba = dict(PROD_KEBA)
        refs = refs_from_cards([dict(OLD), keba, dict(NEW)], _goe_device, LIVE)
        assert [r["id"] for r in refs] == [NEW["id"], "ev_charger"]

    def test_an_install_running_two_chargers_on_one_device_keeps_both(self):
        """Migration: two different working chargers on one device (a twin
        wallbox) are both kept, and the connector setting is SET on both —
        nothing working is dropped."""
        left = {**NEW, "id": "left"}
        right = {**NEW, "id": "right",
                 "ev_charging_power_sensor": f"{P}_p_l1",
                 "ev_charger_service_data": '{"charger_name": "right"}'}
        refs = refs_from_cards([left, right], _goe_device, LIVE)
        assert [r["id"] for r in refs] == ["left", "right"]
        assert [r["settings"]["connector"] for r in refs] == [1, 2]

    def test_a_copy_is_folded(self):
        copy = {**NEW, "id": f"{NEW['id']}_1"}
        refs = refs_from_cards([dict(NEW), copy], _goe_device, LIVE)
        assert [r["id"] for r in refs] == [NEW["id"]]

    def test_no_charger_list_means_nothing_to_manage(self):
        assert reconcile(data_list=None, legacy=None, refs=None, sig=None,
                         device_of=_no_device, live_by_device={}) is None

    def test_a_downgrade_reads_the_legacy_copy_as_it_is(self):
        """beta.15's start-up heal over what this writes: no data list, the
        legacy copy complete → it changes nothing."""
        _refs, resolved = reconcile(
            data_list=[dict(OLD)], legacy=[dict(OLD), dict(NEW)], refs=None,
            sig=None, device_of=_goe_device, live_by_device=LIVE)
        assert _heal_ev_chargers_options(None, resolved) is None


# ── the writers' edits ────────────────────────────────────────────────────

class TestEdits:

    @staticmethod
    def _start():
        refs, resolved = reconcile(data_list=None, legacy=[dict(OLD), dict(NEW)],
                                   refs=None, sig=None, device_of=_goe_device,
                                   live_by_device=LIVE)
        return refs, resolved

    def test_a_removed_charger_stays_removed(self):
        refs, resolved = self._start()
        refs2, resolved2 = reconcile(data_list=None, legacy=[], refs=refs,
                                     sig=signature(resolved), device_of=_goe_device,
                                     live_by_device=LIVE)
        assert refs2 == [] and resolved2 == []
        # nothing anywhere can bring it back
        refs3, _ = reconcile(data_list=None, legacy=resolved2, refs=refs2,
                             sig=signature(resolved2), device_of=_goe_device,
                             live_by_device=LIVE)
        assert refs3 == []

    def test_a_slider_change_is_a_setting(self):
        refs, resolved = self._start()
        edited = [{**resolved[0], "ev_target_soc": 70}]
        _, out = reconcile(data_list=None, legacy=edited, refs=refs,
                           sig=signature(resolved), device_of=_goe_device,
                           live_by_device=LIVE)
        assert out[0]["ev_target_soc"] == 70

    def test_a_picked_entity_is_an_override_and_survives_the_crawler(self):
        refs, resolved = self._start()
        edited = [{**resolved[0], "ev_charging_power_sensor": "sensor.my_meter"}]
        refs2, out = reconcile(data_list=None, legacy=edited, refs=refs,
                               sig=signature(resolved), device_of=_goe_device,
                               live_by_device=LIVE)
        assert refs2[0]["overrides"]["ev_charging_power_sensor"] == "sensor.my_meter"
        assert out[0]["ev_charging_power_sensor"] == "sensor.my_meter"

    def test_picking_the_detected_entity_again_drops_the_override(self):
        refs, resolved = self._start()
        refs[0]["overrides"]["ev_charging_power_sensor"] = "sensor.my_meter"
        resolved = [resolve(refs[0], GOE_LIVE)]
        edited = [{**resolved[0], "ev_charging_power_sensor": GOE_LIVE["ev_charging_power_sensor"]}]
        refs2, _ = reconcile(data_list=None, legacy=edited, refs=refs,
                             sig=signature(resolved), device_of=_goe_device,
                             live_by_device=LIVE)
        assert "ev_charging_power_sensor" not in refs2[0]["overrides"]

    def test_a_create_click_for_a_known_device_adds_nothing(self):
        refs, resolved = self._start()
        again = resolved + [{**GOE_LIVE, "id": f"goecharger_{GOE_DEV}_1", "name": "go-e"}]
        refs2, out = reconcile(data_list=None, legacy=again, refs=refs,
                               sig=signature(resolved), device_of=_goe_device,
                               live_by_device=LIVE)
        assert [r["id"] for r in refs2] == [NEW["id"]]

    def test_a_complete_create_replaces_a_lone_half_card(self):
        refs, resolved = reconcile(data_list=None, legacy=[dict(OLD)], refs=None,
                                   sig=None, device_of=_goe_device,
                                   live_by_device={})  # crawler blind: stays half
        assert not charger_is_complete(resolved[0])
        create = resolved + [dict(NEW)]
        refs2, out = reconcile(data_list=None, legacy=create, refs=refs,
                               sig=signature(resolved), device_of=_goe_device,
                               live_by_device={})
        assert [r["id"] for r in refs2] == [NEW["id"]]
        assert charger_is_complete(out[0])

    def test_a_second_charger_on_a_device_needs_a_connector(self):
        """Decided (Guido, 11.10): one charger per device unless the user
        says which connector it is. Without it, a second, different charger
        for the same device is not added; with it, it is."""
        refs, resolved = self._start()
        other = {**NEW, "id": "second", "ev_charging_power_sensor": f"{P}_p_l2",
                 "ev_charger_service_data": '{"charger_name": "second"}'}
        refs2, _ = reconcile(data_list=None, legacy=resolved + [dict(other)],
                             refs=refs, sig=signature(resolved),
                             device_of=_goe_device, live_by_device=LIVE)
        assert [r["id"] for r in refs2] == [NEW["id"]]
        refs3, _ = reconcile(data_list=None,
                             legacy=resolved + [{**other, "connector": 2}],
                             refs=refs, sig=signature(resolved),
                             device_of=_goe_device, live_by_device=LIVE)
        assert [r["id"] for r in refs3] == [NEW["id"], "second"]
        assert [r["settings"].get("connector") for r in refs3] == [1, 2]

    def test_a_half_card_the_user_finished_is_kept(self):
        """Once the user picks a role on a half card, it is their charger:
        a second, different complete card for the device is a second box."""
        refs, resolved = reconcile(data_list=None, legacy=[dict(OLD)], refs=None,
                                   sig=None, device_of=_goe_device,
                                   live_by_device=LIVE)
        mine = [{**resolved[0], "ev_charging_power_sensor": f"{P}_p_l1"}]
        refs, resolved = reconcile(data_list=None, legacy=mine, refs=refs,
                                   sig=signature(resolved), device_of=_goe_device,
                                   live_by_device=LIVE)
        assert refs[0]["stored_complete"] is True
        other = {**NEW, "id": "second", "ev_charging_power_sensor": f"{P}_p_l2",
                 "ev_connected_sensor": f"{P}_adapter", "ev_charging_sensor": f"{P}_adapter",
                 "connector": 2}
        refs2, _ = reconcile(data_list=None, legacy=resolved + [other], refs=refs,
                             sig=signature(resolved), device_of=_goe_device,
                             live_by_device=LIVE)
        assert [r["id"] for r in refs2] == [OLD["id"], "second"]

    def test_the_crawler_follows_a_rename(self):
        refs, resolved = self._start()
        renamed = {**GOE_LIVE, "ev_charging_power_sensor": f"{P}_power_total"}
        _, out = reconcile(data_list=None, legacy=resolved, refs=refs,
                           sig=signature(resolved), device_of=_goe_device,
                           live_by_device={GOE_DEV: renamed})
        assert out[0]["ev_charging_power_sensor"] == f"{P}_power_total"

    def test_a_blind_crawler_keeps_the_last_answer(self):
        refs, resolved = reconcile(data_list=None, legacy=[dict(OLD)], refs=None,
                                   sig=None, device_of=_goe_device,
                                   live_by_device=LIVE)
        _, out = reconcile(data_list=None, legacy=resolved, refs=refs,
                           sig=signature(resolved), device_of=_goe_device,
                           live_by_device={})
        assert out == resolved


# ── Repairs ───────────────────────────────────────────────────────────────

class TestProblems:

    def test_device_gone(self):
        ref = card_to_ref(dict(NEW), GOE_DEV, GOE_LIVE)
        out = problems([ref], [resolve(ref)], device_exists=lambda d: False,
                       entity_exists=lambda e: True)
        assert [p["kind"] for p in out] == ["charger_device_gone"]

    def test_role_missing(self):
        ref = card_to_ref(dict(OLD), GOE_DEV, {})
        out = problems([ref], [resolve(ref)], device_exists=lambda d: True,
                       entity_exists=lambda e: True)
        assert out[0]["kind"] == "charger_role_missing"
        assert "power reading" in out[0]["roles"]

    def test_override_entity_gone(self):
        ref = card_to_ref({**NEW, "ev_charging_power_sensor": "sensor.my_meter"},
                          GOE_DEV, GOE_LIVE)
        out = problems([ref], [resolve(ref, GOE_LIVE)], device_exists=lambda d: True,
                       entity_exists=lambda e: e != "sensor.my_meter")
        assert [(p["kind"], p.get("entity")) for p in out] == [
            ("charger_role_entity_gone", "sensor.my_meter")]

    def test_a_detected_entity_disabled_is_a_repair_too(self):
        ref = card_to_ref(dict(NEW), GOE_DEV, GOE_LIVE)
        gone = GOE_LIVE["ev_charging_power_sensor"]
        out = problems([ref], [resolve(ref, GOE_LIVE)], device_exists=lambda d: True,
                       entity_exists=lambda e: e != gone)
        assert [(p["kind"], p.get("entity")) for p in out] == [
            ("charger_role_entity_gone", gone)]

    def test_device_less_chargers_raise_nothing(self):
        ref = card_to_ref(dict(PROD_KEBA), None, None)
        assert problems([ref], [resolve(ref)], device_exists=lambda d: False,
                        entity_exists=lambda e: False) == []


@pytest.mark.parametrize("lang", [
    "cs", "da", "de", "en", "es", "fi", "fr", "hu", "it", "nl", "no", "pl",
    "pt", "ro", "sv", "zh-Hans"])
def test_repair_texts_exist_in_every_language(lang):
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    issues = json.loads((root / "translations" / f"{lang}.json").read_text())["issues"]
    for key, needs in (("charger_device_gone", "{name}"),
                       ("charger_role_missing", "{roles}"),
                       ("charger_role_entity_gone", "{entity}")):
        assert needs in issues[key]["description"], (lang, key)


def test_a_brand_charger_without_plug_sensors_is_complete():
    """V2C, NRGkick, OpenEVSE, Peblar, Zaptec: power + a control, no plug
    or charging sensor — a working charger, not a half card (#1092 caught
    the setup form's rule calling them half)."""
    v2c = {"id": "v2c", "ev_charging_power_sensor": "sensor.evse_charge_power",
           "ev_current_control_entity": "number.evse_intensity"}
    assert charger_is_complete(v2c)
    ref = card_to_ref(v2c, "dev", {})
    assert problems([ref], [resolve(ref)], device_exists=lambda d: True,
                    entity_exists=lambda e: True) == []


def test_role_keys_cover_every_charger_entity_key():
    assert CHARGER_ENTITY_KEYS <= ROLE_KEYS


def test_a_device_less_copy_is_folded():
    """(#1092 lifecycle) A device-less box (a KEBA): setup's discovery
    stored it, then a create click sent the same entities under a new id.
    One box, one charger — the exact entity set is its identity."""
    keba = {"id": "keba_fa87f74cd3", "ev_charging_power_sensor": "sensor.keba_power",
            "ev_charger_service": "keba.set_current",
            "ev_connected_sensor": "binary_sensor.keba_plug"}
    refs, resolved = reconcile(data_list=None, legacy=[dict(keba)], refs=None,
                               sig=None, device_of=_no_device, live_by_device={})
    again = resolved + [{**keba, "id": "keba_charger"}]
    refs2, _ = reconcile(data_list=None, legacy=again, refs=refs,
                         sig=signature(resolved), device_of=_no_device,
                         live_by_device={})
    assert [r["id"] for r in refs2] == ["keba_fa87f74cd3"]
    # a different device-less box is a second charger
    other = {**keba, "id": "keba_two", "ev_charging_power_sensor": "sensor.keba2_power",
             "ev_connected_sensor": "binary_sensor.keba2_plug"}
    refs3, _ = reconcile(data_list=None, legacy=resolved + [other], refs=refs,
                         sig=signature(resolved), device_of=_no_device,
                         live_by_device={})
    assert [r["id"] for r in refs3] == ["keba_fa87f74cd3", "keba_two"]
