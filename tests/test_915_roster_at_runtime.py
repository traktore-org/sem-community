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
        assert out["battery_target_soc"]["confirmed"] is False

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
        assert all(v["confirmed"] is False for v in roles.values())

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
