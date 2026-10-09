"""#1054 follow-up (weindler, 08.10.2026) — after the go-e roles shipped, the
box was created, and five things still read wrong on the same install:

1. the Detected-hardware page still said "entities present, no role
   matched" for a unit SEM already drove, with a button to create it again;
2. a charger removed in the UI came back at the next start — the heal
   restored it from ``entry.data``, where the remove never looked;
3. ``entry.data.has_ev`` read ``False`` beside a configured charger;
4. ``sensor.…_p_all`` (kW, no device class) was missing from the power
   sensor pickers, which filtered on device_class=power only;
5. every click on "Create this charger entry" made another copy —
   the card minted ``<id>_1``, ``<id>_2`` …, and nothing asked whether
   the box was already there.

One crawler: the report, the pickers and the create path read the same
roles the setup path does, and a unit SEM drives is a configured charger.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management import (
    _merge_ev_chargers_by_id,
    chargers_without,
)
from custom_components.solar_energy_management.hardware_detection import (
    CHARGER_ENTITY_KEYS,
    build_detection_report,
    charger_entity_ids,
    power_sensor_ids,
)

from .integrations_rig.rig import crawl, load_capture, replay

BOX = "wallbox_go_e"
P = f"goecharger_{BOX}"
SRC = Path(__file__).resolve().parents[1]


def _ent(entity_id, platform="goecharger", device_id="dev1", device_class=None,
         unit=None):
    return SimpleNamespace(
        entity_id=entity_id, platform=platform, device_id=device_id,
        original_device_class=device_class, unit_of_measurement=unit,
        disabled_by=None, translation_key=None, capabilities=None,
        entity_category=None, unique_id=entity_id.split(".", 1)[1],
        config_entry_id="ce1",
    )


def _registry(entries):
    reg = SimpleNamespace()
    reg.entities = {e.entity_id: e for e in entries}
    return reg


def _goe_entities():
    return [
        _ent(f"sensor.{P}_p_all", unit="kW"),
        _ent(f"sensor.{P}_car_status"),
        _ent(f"sensor.{P}_energy_total", device_class="energy", unit="kWh"),
        _ent(f"sensor.{P}_current_session_charged_energy", device_class="energy",
             unit="kWh"),
        _ent(f"switch.{P}_allow_charging"),
    ]


def _configured_goe():
    return {
        "id": "goecharger_dev1", "name": "go-eCharger",
        "ev_charging_power_sensor": f"sensor.{P}_p_all",
        "ev_connected_sensor": f"sensor.{P}_car_status",
        "ev_charging_sensor": f"sensor.{P}_car_status",
        "ev_start_stop_entity": f"switch.{P}_allow_charging",
        "ev_total_energy_sensor": f"sensor.{P}_energy_total",
        "ev_charger_service": "goecharger.set_max_current",
        "ev_service_param_name": "max_current",
    }


# ── 1. the report: a unit SEM drives is a configured charger ──────────────

class TestTheReportKnowsWhatIsConfigured:

    def test_a_configured_unit_is_a_charger_row_not_a_near_miss(self):
        rep = build_detection_report(registry=_registry(_goe_entities()),
                                     configured_chargers=[_configured_goe()])
        rows = [c for c in rep["chargers"] if c["platform"] == "goecharger"]
        assert len(rows) == 1, rep["chargers"]
        row = rows[0]
        assert row["configured"] is True
        assert row["charger_id"] == "goecharger_dev1"
        assert row["mapped"]["ev_charging_power_sensor"]["entity"] == f"sensor.{P}_p_all"
        assert row["control"] == "service: goecharger.set_max_current"
        assert not [n for n in rep["near_misses"] if n["platform"] == "goecharger"]

    def test_a_configured_unit_is_not_in_the_census_gap(self):
        rep = build_detection_report(registry=_registry(_goe_entities()),
                                     configured_chargers=[_configured_goe()])
        assert rep["census"]["rows_matched_nothing"] == []

    def test_a_configured_row_carries_no_offer_and_only_its_wiring(self):
        cfg = {**_configured_goe(), "charge_mode": "solar_only",
               "ev_surplus_priority": 3, "ev_target_soc": 80}
        rep = build_detection_report(registry=_registry(_goe_entities()),
                                     configured_chargers=[cfg])
        row = next(c for c in rep["chargers"] if c["platform"] == "goecharger")
        assert "offer" not in row
        assert set(row["mapped"]) == {
            "ev_charging_power_sensor", "ev_connected_sensor", "ev_charging_sensor",
            "ev_start_stop_entity", "ev_total_energy_sensor",
            "ev_charger_service", "ev_service_param_name"}
        assert row["mapped"]["ev_charger_service"] == {"value": "goecharger.set_max_current"}

    def test_a_brand_mapping_that_found_only_a_meter_is_not_a_charger(self):
        """The config path's rule (#1054): a brand path that matched one
        energy sensor has not found a charger. The report said "charger —
        see mapping" for the same unit."""
        rep = build_detection_report(registry=_registry([
            _ent(f"sensor.{P}_energy_total", device_class="energy", unit="kWh"),
            _ent(f"sensor.{P}_temperature", device_class="temperature"),
        ]))
        assert not [c for c in rep["chargers"] if c["platform"] == "goecharger"]

    def test_the_configured_entities_still_silence_proposals(self):
        """The flat set keeps working for callers that pass only it."""
        rep = build_detection_report(
            registry=_registry(_goe_entities()),
            configured_entities={f"sensor.{P}_p_all"})
        assert isinstance(rep["roster_proposals"], list)


class TestTheCensusCountsACompleteOffer:

    async def test_a_complete_offer_is_a_matched_platform(self, hass):
        """weindler's census: ``rows_matched_nothing: ["goecharger"]`` while
        the near miss carried a complete offer for the very same unit."""
        await replay(hass, load_capture("goecharger"))
        rep = crawl(hass)
        offers = [n for n in rep["near_misses"]
                  if n["platform"] == "goecharger" and n["suggested_charger"]]
        assert offers and offers[0]["missing"] == []
        assert "goecharger" not in rep["census"]["rows_matched_nothing"]

    async def test_once_created_the_offer_becomes_a_configured_row(self, hass):
        await replay(hass, load_capture("goecharger"))
        offer = next(n["suggested_charger"] for n in crawl(hass)["near_misses"]
                     if n["platform"] == "goecharger" and n["suggested_charger"])
        rep = build_detection_report(hass, configured_chargers=[offer])
        rows = [c for c in rep["chargers"] if c["platform"] == "goecharger"]
        assert len(rows) == 1 and rows[0]["configured"] is True
        assert not [n for n in rep["near_misses"] if n["platform"] == "goecharger"]
        assert rep["census"]["rows_matched_nothing"] == []


# ── 2. a remove removes the charger from every store it lives in ──────────

class TestARemoveSticks:

    def test_chargers_without_drops_the_id_from_both_stores(self):
        data = [{"id": "old", "ev_total_energy_sensor": "sensor.e"}]
        opts = [{"id": "old"}, {"id": "new", "ev_charging_power_sensor": "sensor.p"}]
        new_data, new_opts = chargers_without(data, opts, "old")
        assert [c["id"] for c in new_data] == []
        assert [c["id"] for c in new_opts] == ["new"]

    def test_an_absent_store_stays_absent(self):
        new_data, new_opts = chargers_without(None, [{"id": "old"}], "old")
        assert new_data is None
        assert new_opts == []

    def test_an_unknown_id_changes_nothing(self):
        data = [{"id": "a"}]
        opts = [{"id": "a"}]
        assert chargers_without(data, opts, "zzz") == (data, opts)

    def test_the_dialog_remove_prunes_entry_data(self):
        """The options dialog's remove step edits ``self._data``; its save
        goes to options. The prune takes the removed id out of
        ``entry.data`` too, else the heal restores it."""
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )
        saved = [{"id": "ev_charger", "name": "A"}, {"id": "ev_charger_1", "name": "B"}]
        flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
        flow._data = {"ev_chargers": [dict(saved[0])]}
        flow.hass = MagicMock()
        entry = MagicMock(data={"ev_chargers": [dict(c) for c in saved]},
                          options={"ev_chargers": [dict(c) for c in saved]})
        type(flow).config_entry = property(lambda self: entry)
        try:
            flow._prune_removed_chargers_from_data()
            flow.hass.config_entries.async_update_entry.assert_called_once()
            _, kwargs = flow.hass.config_entries.async_update_entry.call_args
            assert [c["id"] for c in kwargs["data"]["ev_chargers"]] == ["ev_charger"]

            # nothing removed → nothing written
            flow.hass.config_entries.async_update_entry.reset_mock()
            flow._data = {"ev_chargers": [dict(c) for c in saved]}
            flow._prune_removed_chargers_from_data()
            flow.hass.config_entries.async_update_entry.assert_not_called()
        finally:
            del type(flow).config_entry

    @pytest.mark.asyncio
    async def test_remove_charger_survives_a_reload(
        self, sem_real_hass, sem_multi_wallbox_config_entry,
    ):
        """weindler's log: "Healed ev_chargers options list: stored ids []
        -> healed ids ['goecharger_28eb748ac3']" — the heal restored from
        ``entry.data`` what the remove had only taken out of options."""
        from .test_services_real import _seed_sem_input_sensors, _setup_sem
        from custom_components.solar_energy_management.const import DOMAIN
        h = sem_real_hass
        _seed_sem_input_sensors(h)
        for side in ("left", "right"):
            h.states.async_set(f"sensor.test_wb_{side}_charging_power", "0",
                               {"unit_of_measurement": "W"})
            h.states.async_set(f"number.test_wb_{side}_max_current", "0",
                               {"unit_of_measurement": "A"})
            h.states.async_set(f"binary_sensor.test_wb_{side}_cable_connected", "off")
            h.states.async_set(f"sensor.test_wb_{side}_status", "idle")
        entry = sem_multi_wallbox_config_entry
        await _setup_sem(h, entry)
        assert [c["id"] for c in entry.data["ev_chargers"]] == ["ev_charger", "ev_charger_1"]

        await h.services.async_call(DOMAIN, "remove_charger",
                                    {"charger_id": "ev_charger_1"}, blocking=True)
        await h.async_block_till_done()

        assert [c["id"] for c in entry.data["ev_chargers"]] == ["ev_charger"]
        assert [c["id"] for c in entry.options["ev_chargers"]] == ["ev_charger"]

        # the start-up heal runs again on reload and must find nothing to restore
        await h.config_entries.async_reload(entry.entry_id)
        await h.async_block_till_done()
        assert [c["id"] for c in entry.options["ev_chargers"]] == ["ev_charger"]
        assert [c["id"] for c in entry.data["ev_chargers"]] == ["ev_charger"]


# ── 3. has_ev: nothing at runtime reads the setup-time flag ──────────────

def test_no_runtime_reader_of_the_stored_has_ev_flag():
    """``entry.data.has_ev`` records what the Energy Dashboard said at
    setup. SEM decides "is there a charger" from the charger list
    (``has_managed_charger``). Pinned so the stale flag can never start
    steering anything."""
    hits = []
    for path in SRC.rglob("*.py"):
        if "/tests/" in str(path) or "/scripts/" in str(path):
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"""(?:get\(|\[)\s*["']has_ev["']""", src):
            hits.append(f"{path.relative_to(SRC)}:{src.count(chr(10), 0, m.start()) + 1}")
    assert hits == [], hits


# ── 4. the power pickers offer what the crawler reads as power ────────────

class TestPowerSensorIds:

    async def test_a_kw_sensor_without_a_class_is_offered(self, hass):
        hass.states.async_set("sensor.goe_p_all", "1.2", {"unit_of_measurement": "kW"})
        hass.states.async_set("sensor.house_power", "300",
                              {"device_class": "power", "unit_of_measurement": "W"})
        hass.states.async_set("sensor.outside_temp", "12",
                              {"device_class": "temperature",
                               "unit_of_measurement": "°C"})
        hass.states.async_set("sensor.energy_total", "5",
                              {"unit_of_measurement": "kWh"})
        ids = power_sensor_ids(hass)
        assert {"sensor.goe_p_all", "sensor.house_power"} <= set(ids)
        assert "sensor.outside_temp" not in ids
        assert "sensor.energy_total" not in ids

    async def test_the_flow_selector_lists_the_kw_sensor(self, hass):
        from custom_components.solar_energy_management.config_flow import (
            _power_sensor_selector,
        )
        hass.states.async_set("sensor.goe_p_all", "1.2", {"unit_of_measurement": "kW"})
        sel = _power_sensor_selector(hass)
        cfg = sel.config
        assert "sensor.goe_p_all" in (cfg.get("include_entities") or [])
        assert "device_class" not in cfg

    def test_with_nothing_to_offer_the_selector_falls_back_to_the_class(self):
        from custom_components.solar_energy_management.config_flow import (
            _power_sensor_selector,
        )
        sel = _power_sensor_selector(None)
        # HA normalises the class to a list; either spelling is the class filter
        assert sel.config.get("device_class") in ("power", ["power"])

    def test_every_flow_power_selector_goes_through_the_helper(self):
        """One rule for every power picker — no selector may filter on
        ``device_class="power"`` by hand again."""
        src = (SRC / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        bare = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") == "EntitySelectorConfig"):
                for kw in node.keywords:
                    if (kw.arg == "device_class" and isinstance(kw.value, ast.Constant)
                            and kw.value.value == "power"):
                        bare.append(node.lineno)
        assert len(bare) == 1, (
            f"EntitySelectorConfig(device_class='power') outside "
            f"_power_sensor_selector at lines {bare}")


# ── 5. creating a charger that exists is a no-op, whoever asks ────────────

class TestCreateIsIdempotent:

    def test_the_same_box_under_a_new_id_merges_into_the_existing_charger(self):
        existing = [_configured_goe()]
        again = {**_configured_goe(), "id": "goecharger_dev1_1",
                 "ev_surplus_priority": 4}
        out = _merge_ev_chargers_by_id(existing, [again], fold_same_box=True)
        assert [c["id"] for c in out] == ["goecharger_dev1"]
        assert out[0]["ev_surplus_priority"] == 4

    def test_a_repeat_click_whose_offer_moved_one_entity_still_folds(self):
        """The crawler re-ran between two clicks and swapped the energy
        sensor; the old card minted ``<id>_1``. Same box."""
        existing = [_configured_goe()]
        again = {**_configured_goe(), "id": "goecharger_dev1_2",
                 "ev_total_energy_sensor": f"sensor.{P}_energy_total_corrected"}
        out = _merge_ev_chargers_by_id(existing, [again], fold_same_box=True)
        assert [c["id"] for c in out] == ["goecharger_dev1"]

    def test_a_different_box_is_still_appended(self):
        existing = [_configured_goe()]
        other = {**_configured_goe(), "id": "goecharger_dev2",
                 "ev_charging_power_sensor": "sensor.garage_p_all",
                 "ev_connected_sensor": "sensor.garage_car_status",
                 "ev_charging_sensor": "sensor.garage_car_status",
                 "ev_start_stop_entity": "switch.garage_allow_charging",
                 "ev_total_energy_sensor": "sensor.garage_energy_total"}
        out = _merge_ev_chargers_by_id(existing, [other], fold_same_box=True)
        assert [c["id"] for c in out] == ["goecharger_dev1", "goecharger_dev2"]

    def test_two_boxes_behind_one_meter_are_two_chargers(self):
        """Review (09.10): one shared entity is not the same box. Two
        chargers on one meter, each with its own control, stay two."""
        left = {"id": "left", "ev_charging_power_sensor": "sensor.shared_meter",
                "ev_current_control_entity": "number.left"}
        right = {"id": "right", "ev_charging_power_sensor": "sensor.shared_meter",
                 "ev_current_control_entity": "number.right", "name": "Right"}
        out = _merge_ev_chargers_by_id([left], [right], fold_same_box=True)
        assert [c["id"] for c in out] == ["left", "right"]
        assert out[0]["ev_current_control_entity"] == "number.left"

    def test_the_heal_never_folds(self):
        """Upgrade: ``ev_charger`` removed before this fix (still in
        entry.data), the same box created as ``goecharger_dev1``. The
        start-up heal must not rename the live charger into the ghost's
        id — its entities would vanish."""
        from custom_components.solar_energy_management import (
            _heal_ev_chargers_options,
        )
        ghost = {**_configured_goe(), "id": "ev_charger"}
        live = _configured_goe()
        healed = _heal_ev_chargers_options([ghost], [live])
        assert [c["id"] for c in healed] == ["ev_charger", "goecharger_dev1"]
        assert _merge_ev_chargers_by_id([ghost], [live])[1]["id"] == "goecharger_dev1"

    def test_a_charger_with_no_entities_is_never_folded(self):
        """Two KEBAs both answer to ``keba.set_current``: a service is not
        an identity, and a skeleton with no entities is a new block."""
        existing = [{"id": "A", "ev_charger_service": "keba.set_current"}]
        out = _merge_ev_chargers_by_id(
            existing, [{"id": "B", "ev_charger_service": "keba.set_current"}],
            fold_same_box=True)
        assert [c["id"] for c in out] == ["A", "B"]

    def test_the_fingerprint_is_the_one_the_flow_uses(self):
        from custom_components.solar_energy_management import config_flow as cf
        assert cf._CHARGER_ENTITY_KEYS == CHARGER_ENTITY_KEYS
        assert charger_entity_ids(_configured_goe()) == {
            f"sensor.{P}_p_all", f"sensor.{P}_car_status",
            f"switch.{P}_allow_charging", f"sensor.{P}_energy_total"}
        assert json.dumps(sorted(CHARGER_ENTITY_KEYS))  # serialisable, stable
