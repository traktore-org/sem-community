"""#915 B+C — what the roster is allowed to do on a running install.

Stage A proved the miner re-derives what SEM learned by hand. This file pins
what SEM may then DO with it, and the answer is deliberately small:

* **name** an unknown domain in the census, so "eg4_web_monitor" becomes
  "EG4 Web Monitor · 412 installs" and a near-miss becomes a filable report;
* **propose** a role for an entity the user's own registry already has, as
  report data the Config card shows and the user confirms;
* **ask the registry the semantic question first** in the discharge-control
  discovery — the integration's declared key before the entity-id regexes,
  behind the same unchanged unit gate.

And what it may never do: invent an entity, bind a control, or change what an
existing consumer of the census reads. Every key `tests/test_848_census.py`
asserts on is byte-identical; the new ones are additive.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management import hardware_detection as hd


def _ent(entity_id, platform, *, translation_key="", unique_id="",
         device_id="dev1", device_class=None, disabled_by=None,
         config_entry_id="entry1"):
    return SimpleNamespace(
        entity_id=entity_id, platform=platform, device_id=device_id,
        translation_key=translation_key, unique_id=unique_id,
        original_device_class=device_class, disabled_by=disabled_by,
        config_entry_id=config_entry_id)


def _registry(entities):
    return SimpleNamespace(entities={e.entity_id: e for e in entities},
                           async_get=lambda eid: {
                               e.entity_id: e for e in entities}.get(eid))


@pytest.mark.unit
class TestItNamesTheGap:
    def test_an_unknown_energy_domain_is_named_from_the_roster(self):
        ents = [
            _ent("sensor.eg4_battery_power", "eg4_web_monitor",
                 device_class="power"),
            _ent("sensor.eg4_soc", "eg4_web_monitor", device_class="battery"),
        ]
        census = hd.build_integration_census(registry=_registry(ents))
        assert census["unknown_energy_domains"] == ["eg4_web_monitor"]
        named = census["unknown_energy_domains_named"]
        assert named and named[0]["domain"] == "eg4_web_monitor"
        assert named[0]["name"] == "EG4 Web Monitor"
        assert named[0]["known_vocabulary"] is True

    def test_a_domain_the_roster_never_heard_of_is_still_reported(self):
        """Silence about the name must not become silence about the gap."""
        ents = [
            _ent("sensor.mystery_power", "totally_unknown_brand",
                 device_class="power"),
            _ent("sensor.mystery_soc", "totally_unknown_brand",
                 device_class="battery"),
        ]
        census = hd.build_integration_census(registry=_registry(ents))
        assert census["unknown_energy_domains"] == ["totally_unknown_brand"]
        assert census["unknown_energy_domains_named"] == []

    def test_the_census_keeps_every_key_848_reads(self):
        census = hd.build_integration_census(registry=_registry([]))
        for key in ("installed", "known_charger_platforms_present",
                    "known_inverter_domains_present", "rows_matched_nothing",
                    "unknown_energy_domains"):
            assert key in census, key

    def test_the_roster_says_when_it_was_generated(self):
        prov = hd.roster_provenance()
        assert prov.get("generated_at"), "a prior with no provenance is a rumour"

    def test_a_missing_roster_degrades_to_todays_behaviour(self):
        with patch.object(hd, "_roster", return_value=None):
            assert hd.describe_domain("eg4_web_monitor") is None
            assert hd.roster_role_keys("eg4_web_monitor", "battery_target_soc") == ()
            assert hd.propose_roles_from_roster([], "eg4_web_monitor") == {}
            census = hd.build_integration_census(registry=_registry([]))
            assert census["unknown_energy_domains_named"] == []


@pytest.mark.unit
class TestItProposesOnlyWhatTheRegistryHas:
    def test_a_declared_key_present_on_this_device_is_proposed(self):
        ents = [_ent("number.eg4_charge_soc", "eg4_web_monitor",
                     translation_key="system_charge_soc_limit")]
        out = hd.propose_roles_from_roster(ents, "eg4_web_monitor")
        assert out["battery_target_soc"]["entity"] == "number.eg4_charge_soc"
        assert out["battery_target_soc"]["matched_key"] == "system_charge_soc_limit"
        assert out["battery_target_soc"]["action"] == "set_option"

    def test_a_unique_id_suffix_counts_too(self):
        ents = [_ent("number.x", "eg4_web_monitor",
                     unique_id="abc123_system_charge_soc_limit")]
        assert "battery_target_soc" in hd.propose_roles_from_roster(
            ents, "eg4_web_monitor")

    def test_nothing_is_proposed_for_an_entity_this_install_lacks(self):
        """The intersection rule: the roster knows EG4 declares a charge-SOC
        limit, but this device does not have one, so nothing is proposed. A
        proposal can never invent hardware."""
        ents = [_ent("sensor.eg4_battery_power", "eg4_web_monitor")]
        assert hd.propose_roles_from_roster(ents, "eg4_web_monitor") == {}

    def test_the_entity_must_be_on_the_declared_platform(self):
        """A sensor named like a control is not the control."""
        ents = [_ent("sensor.eg4_charge_soc", "eg4_web_monitor",
                     translation_key="system_charge_soc_limit")]
        assert hd.propose_roles_from_roster(ents, "eg4_web_monitor") == {}

    def test_an_unknown_domain_proposes_nothing(self):
        ents = [_ent("number.x", "no_such_integration",
                     translation_key="system_charge_soc_limit")]
        assert hd.propose_roles_from_roster(ents, "no_such_integration") == {}

    def test_the_entity_id_is_never_matched_on(self):
        """A translation key is the author's label; an entity_id is the
        user's rename. Only the first may decide a role."""
        ents = [_ent("number.system_charge_soc_limit", "eg4_web_monitor",
                     translation_key="brightness")]
        assert hd.propose_roles_from_roster(ents, "eg4_web_monitor") == {}


@pytest.mark.unit
class TestTheDischargeControlRung:
    """The one place a mined key reaches a real decision — and it reaches it
    in FRONT of the entity-id regexes, behind the same unit gate."""

    def _run(self, entities, seed="sensor.huawei_battery_power"):
        reg = _registry(entities)
        hass = MagicMock()
        ed = SimpleNamespace(battery_power=seed, battery_charge_energy=None,
                             battery_discharge_energy=None, solar_power=None,
                             solar_energy=None, grid_import_power=None)
        with patch.object(hd.entity_registry, "async_get",
                          return_value=reg), \
             patch("custom_components.solar_energy_management.coordinator"
                   ".power_control.is_valid_power_control_entity",
                   return_value=True):
            return hd.discover_inverter_from_registry_verbose(hass, ed)

    def test_the_declared_key_answers_first(self):
        ents = [
            _ent("sensor.huawei_battery_power", "huawei_solar"),
            _ent("number.inverter_setting_a", "huawei_solar",
                 translation_key="storage_maximum_discharging_power"),
        ]
        entity, rung = self._run(ents)
        assert entity == "number.inverter_setting_a"
        assert rung == "translation_key"

    def test_the_regex_rung_still_answers_when_no_key_matches(self):
        """The same entity, the older reason — nothing regressed for an
        integration that publishes no vocabulary."""
        ents = [
            _ent("sensor.growatt_battery_power", "growatt_server"),
            _ent("number.growatt_max_discharge_power", "growatt_server"),
        ]
        entity, rung = self._run(ents, seed="sensor.growatt_battery_power")
        assert entity == "number.growatt_max_discharge_power"
        assert rung == "entity_id_pattern"

    def test_the_wrapper_contract_is_unchanged(self):
        ents = [
            _ent("sensor.huawei_battery_power", "huawei_solar"),
            _ent("number.inverter_setting_a", "huawei_solar",
                 translation_key="storage_maximum_discharging_power"),
        ]
        reg = _registry(ents)
        hass = MagicMock()
        ed = SimpleNamespace(battery_power="sensor.huawei_battery_power",
                             battery_charge_energy=None,
                             battery_discharge_energy=None, solar_power=None,
                             solar_energy=None, grid_import_power=None)
        with patch.object(hd.entity_registry, "async_get", return_value=reg), \
             patch("custom_components.solar_energy_management.coordinator"
                   ".power_control.is_valid_power_control_entity",
                   return_value=True):
            out = hd.discover_inverter_from_registry(hass, ed)
        assert out == "number.inverter_setting_a", "callers still get a string"

    def test_a_miss_still_returns_none_with_a_reason(self):
        entity, rung = self._run([_ent("sensor.x", "huawei_solar")])
        assert entity is None and rung


@pytest.mark.unit
class TestItRecognisesWhatIsAlreadyInstalled:
    """The question the near-miss walk could not answer: it only covers the
    charger platforms, so an INVERTER or battery SEM has no row for was named
    and then dropped. This walk asks every installed integration the same
    question."""

    def test_an_installed_inverter_gets_its_declared_controls_matched(self):
        ents = [
            _ent("number.sigen_charge", "sigen",
                 translation_key="dc_charger_max_charging_power_limit"),
            _ent("number.sigen_discharge", "sigen",
                 translation_key="dc_charger_max_discharging_power_limit"),
            _ent("sensor.sigen_power", "sigen", device_class="power"),
        ]
        out = hd.propose_for_installed(_registry(ents))
        assert len(out) == 1
        row = out[0]
        assert row["domain"] == "sigen"
        assert row["roster"]["name"] == "Sigenergy ESS"
        roles = row["proposed_roles"]
        assert roles["battery_charge_limit"]["entity"] == "number.sigen_charge"
        assert roles["battery_discharge_limit"]["entity"] == "number.sigen_discharge"
        assert all(v.get("action") for v in roles.values())

    def test_an_integration_the_roster_has_no_vocabulary_for_is_skipped(self):
        ents = [_ent("number.whatever", "some_unknown_platform",
                     translation_key="max_discharging_power")]
        assert hd.propose_for_installed(_registry(ents)) == []

    def test_an_installed_integration_with_none_of_its_controls_is_skipped(self):
        """Vocabulary is not presence: EG4 declares a charge-SOC limit, but a
        box that only has its sensors gets no proposal."""
        ents = [_ent("sensor.eg4_power", "eg4_web_monitor",
                     device_class="power")]
        assert hd.propose_for_installed(_registry(ents)) == []

    def test_disabled_entities_never_become_proposals(self):
        ents = [_ent("number.eg4_soc", "eg4_web_monitor",
                     translation_key="system_charge_soc_limit",
                     disabled_by="user")]
        assert hd.propose_for_installed(_registry(ents)) == []

    def test_the_report_carries_it_and_stays_serialisable(self):
        import json
        ents = [
            _ent("number.sigen_discharge", "sigen",
                 translation_key="dc_charger_max_discharging_power_limit"),
        ]
        report = hd.build_detection_report(registry=_registry(ents))
        assert report["roster_proposals"], "an installed brand must be asked"
        json.dumps(report)

    def test_a_missing_roster_leaves_the_report_intact(self):
        with patch.object(hd, "_roster", return_value=None):
            report = hd.build_detection_report(registry=_registry([]))
        assert report["roster_proposals"] == []


@pytest.mark.unit
class TestTheSecondAnchor:
    """(#915) SEM's install used to start — and end — at Home Assistant's
    Energy Dashboard. This is the other anchor: what do you already run, and
    what does it call the three sensors SEM needs."""

    def test_a_declared_key_names_the_solar_and_grid_sensors(self):
        ents = [
            _ent("sensor.wechselrichter_eingangsleistung", "huawei_solar",
                 translation_key="input_power", device_class="power"),
            _ent("sensor.leistungsmesser_wirkleistung", "huawei_solar",
                 translation_key="power_meter_active_power", device_class="power"),
            _ent("sensor.batterie_lade_entladeleistung", "huawei_solar",
                 translation_key="storage_charge_discharge_power",
                 device_class="power"),
            _ent("sensor.batterie_ladestand", "huawei_solar",
                 translation_key="state_of_capacity", device_class="battery"),
        ]
        out = hd.propose_energy_sources(registry=_registry(ents))
        assert out["solar_power_sensor"]["entity"] == "sensor.wechselrichter_eingangsleistung"
        assert out["grid_import_power_sensor"]["entity"] == "sensor.leistungsmesser_wirkleistung"
        assert out["battery_power_sensor"]["entity"] == "sensor.batterie_lade_entladeleistung"
        assert "declared as" in out["solar_power_sensor"]["why"]

    def test_it_works_on_a_german_install(self):
        """The point of matching a declared key rather than an entity id:
        every entity above is German and none of them contains 'solar',
        'grid' or 'battery'."""
        ents = [
            _ent("sensor.wechselrichter_eingangsleistung", "huawei_solar",
                 translation_key="input_power", device_class="power"),
        ]
        out = hd.propose_energy_sources(registry=_registry(ents))
        assert "solar_power_sensor" in out

    def test_shape_answers_when_nothing_is_declared(self):
        """A brand that publishes no vocabulary still gets help: a power
        sensor on an energy-shaped integration is a candidate."""
        ents = [
            _ent("sensor.growatt_solar_power", "growatt_server",
                 device_class="power"),
            _ent("sensor.growatt_grid_power", "growatt_server",
                 device_class="power"),
            _ent("sensor.growatt_battery_soc", "growatt_server",
                 device_class="battery"),
        ]
        out = hd.propose_energy_sources(registry=_registry(ents))
        assert out["solar_power_sensor"]["entity"] == "sensor.growatt_solar_power"
        assert out["grid_import_power_sensor"]["entity"] == "sensor.growatt_grid_power"
        assert "power sensor" in out["grid_import_power_sensor"]["why"]

    def test_a_daily_total_is_never_a_live_power_sensor(self):
        ents = [
            _ent("sensor.growatt_solar_power_today", "growatt_server",
                 device_class="power"),
            _ent("sensor.growatt_battery_soc", "growatt_server",
                 device_class="battery"),
        ]
        out = hd.propose_energy_sources(registry=_registry(ents))
        assert "solar_power_sensor" not in out

    def test_a_box_with_no_energy_hardware_proposes_nothing(self):
        ents = [_ent("sensor.lounge_temperature", "hue",
                     device_class="temperature")]
        assert hd.propose_energy_sources(registry=_registry(ents)) == {}

    def test_every_proposal_says_where_it_came_from(self):
        ents = [
            _ent("sensor.pv", "huawei_solar", translation_key="input_power",
                 device_class="power"),
        ]
        for body in hd.propose_energy_sources(registry=_registry(ents)).values():
            assert body["why"] and body["domain"] and body["entity"]


@pytest.mark.unit
class TestTheSourcesStepWritesKeysTheReaderConsumes:
    """The bug this class exists for: the sources step wrote
    ``solar_power_sensor`` / ``grid_import_power_sensor`` — the names the
    Energy Dashboard produces — and the install completed cleanly and then
    read **0 W from a 4.2 kW inverter**. An install that takes this step has
    no dashboard config by definition, so SensorReader falls to its LEGACY
    path, which reads ``solar_production_sensor`` / ``grid_power_sensor``.

    Every unit test passed while that was broken, because none of them
    followed the config from the step that writes it to the reader that
    consumes it. Caught on the .46 rig; pinned here.
    """

    def _install_data(self) -> dict:
        """The dict async_step_sources writes, extracted from the source so
        this test cannot drift from the flow it is guarding."""
        import ast
        import pathlib as _p
        src = (_p.Path(__file__).resolve().parent.parent
               / "config_flow.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "async_step_sources"):
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "update"
                            and call.args
                            and isinstance(call.args[0], ast.Dict)):
                        out = {}
                        for k, v in zip(call.args[0].keys, call.args[0].values):
                            if isinstance(k, ast.Constant):
                                out[k.value] = (
                                    v.value if isinstance(v, ast.Constant)
                                    else "sensor.chosen")
                        return out
        raise AssertionError("async_step_sources no longer updates _data")

    def test_the_reader_resolves_every_sensor_the_step_writes(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        data = self._install_data()
        assert data, "premise: the step writes an install config"
        reader = SensorReader(MagicMock(), data)
        cfg = reader.config
        assert cfg.solar_power_sensor, (
            "the sources step writes no key SensorReader reads for solar — "
            "the install would come up reading 0 W")
        assert cfg.grid_power_sensor, "same for grid"
        assert cfg.battery_power_sensor, "same for battery"
        assert cfg.battery_soc_sensor, (
            "no SOC means the four battery zones have nothing to read")

    def test_it_also_writes_the_dashboard_shaped_names(self):
        """The rest of the integration — flags, diagnostics, the Config
        card's pickers — reads those, so both sets are written."""
        data = self._install_data()
        for key in ("solar_power_sensor", "grid_import_power_sensor",
                    "has_solar", "has_grid"):
            assert key in data, key


@pytest.mark.unit
class TestANearMissIsAboutHardware:
    """Seen on the .46 card: 24 near-misses, most of them zigbee2mqtt bridge
    buttons, each telling the user *"a near miss is a brand we almost
    support — please report"* about a Zigbee coordinator. The line is right;
    the audience was wrong. ``mqtt`` is a transport carrying every brand at
    once, so a device there earns the line only when something about it is
    actually energy-shaped."""

    def _report(self, ents):
        return hd.build_detection_report(registry=_registry(ents))

    def test_a_zigbee_bridge_is_not_a_near_miss(self):
        ents = [
            _ent("binary_sensor.zigbee2mqtt_bridge_connection_state", "mqtt",
                 device_id="z1"),
            _ent("button.zigbee2mqtt_bridge_restart", "mqtt", device_id="z1"),
            _ent("select.zigbee2mqtt_bridge_log_level", "mqtt", device_id="z1"),
        ]
        assert self._report(ents)["near_misses"] == []

    def test_an_energy_shaped_mqtt_device_still_is_one(self):
        """The JuiceBox case (#816): a real charger rides mqtt, and if its
        roles stop matching the user must still see the gap."""
        ents = [
            _ent("sensor.homie_juicebox_power", "mqtt", device_id="j1",
                 device_class="power"),
            _ent("binary_sensor.homie_juicebox_plug", "mqtt", device_id="j1",
                 device_class="plug"),
        ]
        misses = self._report(ents)["near_misses"]
        assert [m["platform"] for m in misses] == ["mqtt"]

    def test_a_second_device_of_a_detected_brand_is_not_a_near_miss(self):
        """Zaptec ships an installation-level device beside the charger,
        holding the site's available-current and phase registers. With the
        charger detected, that device is not a brand SEM almost supports —
        on the .46 rig it was the last near miss standing, telling the owner
        of a working charger to file a report."""
        ents = [
            # the charger device — fully mapped
            _ent("number.zap_current", "zaptec", device_id="charger",
                 device_class="current"),
            _ent("sensor.zap_power", "zaptec", device_id="charger",
                 device_class="power"),
            _ent("binary_sensor.zap_cable", "zaptec", device_id="charger",
                 device_class="plug"),
            _ent("binary_sensor.zap_charging", "zaptec", device_id="charger",
                 device_class="power"),
            # the installation device — no role
            _ent("number.zap_available", "zaptec", device_id="site",
                 unique_id="sim-1_available_current"),
        ]
        report = self._report(ents)
        assert report["chargers"], "premise: the charger itself is detected"
        assert report["near_misses"] == []

    def test_a_branded_platform_is_never_gated(self):
        """Only the shared transports are filtered. A brand platform with
        entities and no role is exactly what the near-miss list is for."""
        ents = [_ent("sensor.wallbox_thing", "wallbox", device_id="w1")]
        misses = self._report(ents)["near_misses"]
        assert [m["platform"] for m in misses] == ["wallbox"]


@pytest.mark.unit
class TestAProposalCanActuallyBeAccepted:
    """Guido, reading the card: *"Huawei Solar unconfirmed — how do I
    confirm?"* Fair: the block said unconfirmed and offered no way to
    confirm, so the only route was to read the entity, scroll to the right
    section and re-enter it by hand. That is a chore wearing the word
    'proposal'. Every proposal now carries what the user can DO about it."""

    def _roles(self, ents, domain):
        return hd.propose_roles_from_roster(ents, domain)

    def test_a_settable_role_names_the_option_the_card_writes(self):
        ents = [_ent("number.eg4_soc", "eg4_web_monitor",
                     translation_key="system_charge_soc_limit")]
        p = self._roles(ents, "eg4_web_monitor")["battery_target_soc"]
        assert p["action"] == "set_option"
        assert p["config_key"] == "battery_target_soc_entity"

    def test_a_read_role_names_the_key_the_READER_uses(self):
        """Not the Energy-Dashboard-shaped name — the one SensorReader
        consumes. Writing the other one is what made a fresh install read
        0 W from a live inverter."""
        ents = [_ent("sensor.pv", "huawei_solar", translation_key="input_power",
                     device_class="power")]
        p = self._roles(ents, "huawei_solar")["solar_power"]
        assert p["config_key"] == "solar_production_sensor"

    def test_a_per_charger_role_offers_no_top_level_button(self):
        """ev_current_control lives inside a charger's own config. A button
        here would write one charger's entity into an install-wide key."""
        ents = [_ent("number.zap", "zaptec", translation_key="charger_max_current")]
        p = self._roles(ents, "zaptec")["ev_current_control"]
        assert p["action"] == "per_charger"
        assert p["config_key"] is None

    def test_an_auto_resolved_role_is_not_shown_as_a_chore(self):
        """SEM reads the capacity spec by translation key every time it
        looks (config_flow._spec_from_registry). Listing it as something to
        confirm would invent work that does not exist."""
        ents = [
            _ent("sensor.cap", "huawei_solar",
                 translation_key="storage_rated_capacity"),
            _ent("number.dis", "huawei_solar",
                 translation_key="storage_maximum_discharging_power"),
        ]
        out = hd.propose_for_installed(_registry(ents))
        roles = out[0]["proposed_roles"]
        assert "battery_capacity_spec" not in roles
        assert "battery_discharge_limit" in roles

    def test_every_settable_key_is_one_set_option_accepts(self):
        """The button calls solar_energy_management.set_option with this
        key. A key the service does not accept would fail silently in the
        card's catch."""
        import importlib.util
        import pathlib as _p
        root = _p.Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "role_lexicon", root / "consts" / "role_lexicon.py")
        lex = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lex)
        # The key has to be one SEM READS. Three of them (target SOC,
        # strategy, force-charge switch) are consumed by the battery adapters
        # without an options-flow field of their own, which is exactly why a
        # one-click accept is worth having: today the only way to set them is
        # the set_option service.
        read_by = " ".join(
            f.read_text() for f in (root / "coordinator").rglob("*.py"))
        flow_src = (root / "config_flow.py").read_text()
        card_src = (root / "dashboard" / "card" / "src" / "cards"
                    / "sem-config-card.js").read_text()
        for role, key in lex.SEM_CONFIG_KEY_FOR_ROLE.items():
            assert (f'"{key}"' in read_by or f'"{key}"' in flow_src
                    or key in card_src), (
                f"{role} would write {key}, which nothing in SEM reads — "
                "the card would save a key that does nothing")


@pytest.mark.unit
class TestANearMissIsAnOfferNotAChore:
    """Guido: *"'no role matched — please report' — how?"* Fair. When SEM has
    already worked out which entity is the charging current, asking the user
    to file a bug report is the wrong end of the offer: the answer is *add
    this charger*, pre-filled. "Please report" stays for the case where SEM
    genuinely has nothing — and then it is a prefilled issue, one click."""

    def test_a_charger_near_miss_comes_with_a_ready_charger(self):
        ents = [
            _ent("number.zap_current", "zaptec", device_id="z1",
                 unique_id="sim-1_available_current"),
            _ent("sensor.zap_power", "zaptec", device_id="z1",
                 device_class="power"),
            _ent("binary_sensor.zap_cable", "zaptec", device_id="z1",
                 device_class="plug"),
            _ent("binary_sensor.zap_charging", "zaptec", device_id="z1",
                 device_class="power"),
        ]
        proposed = hd.propose_roles_from_roster(ents, "zaptec")
        out = hd.charger_from_near_miss(ents, "zaptec", proposed)
        assert out["ev_current_control_entity"] == "number.zap_current"
        assert out["ev_charging_power_sensor"] == "sensor.zap_power"
        assert out["ev_connected_sensor"] == "binary_sensor.zap_cable"
        assert out["id"] and out["name"] == "Zaptec EV charger"

    def test_no_power_sensor_means_no_offer(self):
        """A charger SEM cannot measure is one it must not steer, so the
        honest line there is still 'please report'."""
        ents = [_ent("number.zap_current", "zaptec", device_id="z1",
                     unique_id="sim-1_available_current")]
        proposed = hd.propose_roles_from_roster(ents, "zaptec")
        assert hd.charger_from_near_miss(ents, "zaptec", proposed) == {}

    def test_no_proposed_control_means_no_offer(self):
        ents = [_ent("sensor.mystery_power", "wallbox", device_id="w1",
                     device_class="power")]
        assert hd.charger_from_near_miss(ents, "wallbox", {}) == {}

    def test_the_report_carries_the_offer(self):
        ents = [
            _ent("number.zap_current", "zaptec", device_id="z1",
                 unique_id="sim-1_available_current"),
            _ent("sensor.zap_power", "zaptec", device_id="z1",
                 device_class="power"),
        ]
        misses = hd.build_detection_report(registry=_registry(ents))["near_misses"]
        assert misses and misses[0]["suggested_charger"]["ev_current_control_entity"] \
            == "number.zap_current"

    def test_the_card_offers_the_action_before_the_report(self):
        """Both paths exist in the card, and the offer comes first: a user
        with a fixable near miss should never be sent to GitHub."""
        import pathlib as _p
        root = _p.Path(__file__).resolve().parent.parent
        card = (root / "dashboard" / "card" / "src" / "cards"
                / "sem-config-card.js").read_text()
        assert "_addSuggestedCharger" in card
        assert "_reportNearMissUrl" in card
        assert card.index("suggested_charger?.id") < card.index("_reportNearMissUrl(m)")
