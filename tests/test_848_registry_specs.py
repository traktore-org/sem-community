"""#848 — hardware specs detect by STABLE registry keys before entity_id
globs. The betriebsmodus lesson as a regression test: a German install's
entity ids match no English glob, but ``translation_key``/``unique_id``
never localise.
"""
from __future__ import annotations

from types import SimpleNamespace


def _ent(eid, platform, tk=None, uid=None, disabled=False):
    return SimpleNamespace(entity_id=eid, platform=platform,
                           translation_key=tk, unique_id=uid or eid,
                           disabled_by=("user" if disabled else None),
                           original_device_class=None)


def _hass(states: dict):
    ns = SimpleNamespace()
    ns.states = SimpleNamespace(
        get=lambda eid: states.get(eid),
        async_all=lambda *_a: list(states.values()),
    )
    return ns


def _state(eid, value, unit=None):
    return SimpleNamespace(entity_id=eid, state=str(value),
                           attributes=({"unit_of_measurement": unit} if unit else {}))


def _registry(entries):
    reg = SimpleNamespace(); reg.entities = {e.entity_id: e for e in entries}
    return reg


def _detect(states, entries):
    from custom_components.solar_energy_management.config_flow import (
        _detect_hardware_specs,
    )
    return _detect_hardware_specs(_hass(states), registry=_registry(entries))


class TestRegistryFirst:
    def test_a_german_install_no_glob_could_match(self):
        """Entity ids chosen to defeat every glob — only the stable keys
        can place them (live shape from the .175 huawei_solar registry)."""
        states = {
            "sensor.speicher_gesamt": _state("sensor.speicher_gesamt", 15000, "Wh"),
            "sensor.anlage_leistung": _state("sensor.anlage_leistung", 10000, "W"),
            "number.speicher_limit": _state("number.speicher_limit", 5000, "W"),
        }
        entries = [
            _ent("sensor.speicher_gesamt", "huawei_solar",
                 tk="storage_rated_capacity", uid="SN1_storage_rated_capacity"),
            _ent("sensor.anlage_leistung", "huawei_solar",
                 tk="rated_power", uid="SN1_rated_power"),
            _ent("number.speicher_limit", "huawei_solar",
                 tk="storage_maximum_discharging_power",
                 uid="SN1_storage_maximum_discharging_power"),
        ]
        d = _detect(states, entries)
        assert d["battery_capacity_kwh"] == 15.0
        assert d["system_size_kwp"] == 10.0
        assert d["battery_max_discharge_power"] == 5000
        assert d["battery_assist_max_power"] == 5000

    def test_unique_id_suffix_carries_when_translation_key_is_absent(self):
        states = {"sensor.x1": _state("sensor.x1", 20, "kWh")}
        entries = [_ent("sensor.x1", "solax", uid="abc123_battery_capacity")]
        assert _detect(states, entries)["battery_capacity_kwh"] == 20.0

    def test_disabled_entities_never_place_a_spec(self):
        states = {"sensor.x1": _state("sensor.x1", 20, "kWh")}
        entries = [_ent("sensor.x1", "solax",
                        tk="storage_rated_capacity", disabled=True)]
        assert "battery_capacity_kwh" not in _detect(states, entries)

    def test_the_glob_fallback_still_stands_without_a_registry_match(self):
        states = {
            "sensor.my_battery_capacity_total":
                _state("sensor.my_battery_capacity_total", 12, "kWh"),
        }
        entries = [_ent("sensor.my_battery_capacity_total", "some_brand")]
        d = _detect(states, entries)
        assert d.get("battery_capacity_kwh") == 12.0   # via the old glob
