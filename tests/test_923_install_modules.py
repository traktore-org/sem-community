"""#923 — the install-modules oracle: one answer, three states.

SEM is a core plus hardware modules (battery, EV, heat pump, hot water).
Every surface that depends on a module asks ONE function whether the install
has it. The verdict comes from configuration, never live state, and "the
Energy Dashboard could not be read" is UNKNOWN — never ABSENT (#925)."""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.install_modules import (
    CORE_BY_DECISION,
    ENTITY_MODULES,
    Module,
    Presence,
    absent_entity_ids,
    all_unknown,
    entity_kept,
    has_managed_charger,
    install_modules,
    keeps,
    kept_descriptions,
    presence_of,
    presence_summary,
)

ED_EMPTY = SimpleNamespace(has_battery=False, has_ev=False)
ED_BATTERY = SimpleNamespace(has_battery=True, has_ev=False)
ED_EV = SimpleNamespace(has_battery=False, has_ev=True)


class TestBattery:

    def test_a_wired_soc_sensor_is_present_before_the_dashboard_is_read(self):
        v = install_modules({"battery_soc_sensor": "sensor.soc"}, None, False)
        assert v[Module.BATTERY] is Presence.PRESENT

    def test_a_wired_control_entity_is_present(self):
        v = install_modules(
            {"battery_discharge_control_entity": "number.max_discharge"}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.PRESENT

    def test_the_energy_dashboard_alone_makes_it_present(self):
        assert install_modules({}, ED_BATTERY, True)[Module.BATTERY] is Presence.PRESENT

    def test_nothing_wired_and_the_dashboard_read_is_absent(self):
        assert install_modules({}, ED_EMPTY, True)[Module.BATTERY] is Presence.ABSENT

    def test_a_missing_dashboard_file_is_an_answer(self):
        # read_energy_dashboard_config_outcome() returns (None, True) when
        # .storage/energy does not exist: a definite "no dashboard".
        assert install_modules({}, None, True)[Module.BATTERY] is Presence.ABSENT

    def test_an_unread_dashboard_is_unknown_never_absent(self):
        # #925: "I could not ask" is not "no". UNKNOWN keeps every entity.
        assert install_modules({}, None, False)[Module.BATTERY] is Presence.UNKNOWN

    def test_capacity_alone_is_not_evidence(self):
        # The options flow's Settings step saves battery_capacity_kwh with a
        # default for every install that passes through it.
        v = install_modules({"battery_capacity_kwh": 10.0}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.ABSENT

    @pytest.mark.parametrize("value", [None, "", [], {}])
    def test_empty_values_are_not_wiring(self, value):
        v = install_modules({"battery_power_sensor": value}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.ABSENT


class TestEv:

    def test_a_charger_list_is_present(self):
        v = install_modules({"ev_chargers": [{"id": "ev_charger"}]}, ED_EMPTY, True)
        assert v[Module.EV] is Presence.PRESENT

    @pytest.mark.parametrize("key", ["ev_charging_power_sensor", "ev_power_sensor"])
    def test_the_legacy_single_charger_keys_are_present(self, key):
        assert install_modules({key: "sensor.wb"}, ED_EMPTY, True)[Module.EV] is Presence.PRESENT

    def test_an_energy_dashboard_ev_consumer_is_present_without_a_charger(self):
        # sensor_reader.py feeds sem_ev_power from ed.ev_power when no charger
        # is configured — that install HAS EV data.
        assert install_modules({}, ED_EV, True)[Module.EV] is Presence.PRESENT

    def test_nothing_and_the_dashboard_read_is_absent(self):
        assert install_modules({}, ED_EMPTY, True)[Module.EV] is Presence.ABSENT

    def test_an_unread_dashboard_is_unknown(self):
        assert install_modules({}, None, False)[Module.EV] is Presence.UNKNOWN


class TestHeatPump:

    @pytest.mark.parametrize("key", [
        "heat_pump_relay1_entity", "heat_pump_relay2_entity",
        "heat_pump_climate_entity", "heat_pump_sg_ready_service",
        "heat_pump_sg_ready_state_entity", "heat_pump_power_sensor",
        "heat_pump_energy_sensor",
    ])
    def test_any_wiring_key_is_present(self, key):
        assert install_modules({key: "x.y"}, ED_EMPTY, True)[Module.HEAT_PUMP] is Presence.PRESENT

    def test_an_additional_unit_list_is_present(self):
        v = install_modules({"heat_pumps": [{"id": "hp2"}]}, ED_EMPTY, True)
        assert v[Module.HEAT_PUMP] is Presence.PRESENT

    def test_tunables_alone_are_not_evidence(self):
        cfg = {"heat_pump_boost_offset": 2.0, "heat_pump_rated_power": 3000,
               "heat_pump_priority": 5}
        assert install_modules(cfg, ED_EMPTY, True)[Module.HEAT_PUMP] is Presence.ABSENT

    def test_config_only_so_never_unknown(self):
        assert install_modules({}, None, False)[Module.HEAT_PUMP] is Presence.ABSENT


class TestHotWater:

    def test_the_tank_entity_is_present(self):
        v = install_modules({"hot_water_entity": "water_heater.tank"}, ED_EMPTY, True)
        assert v[Module.HOT_WATER] is Presence.PRESENT

    def test_settings_alone_are_not_evidence(self):
        v = install_modules({"hot_water_max_temperature": 60}, None, False)
        assert v[Module.HOT_WATER] is Presence.ABSENT


class TestManagedCharger:
    """The #595 EV-TAB rule — not the same question as the EV module."""

    def test_no_charger(self):
        assert has_managed_charger({}) is False

    def test_charger_list(self):
        assert has_managed_charger({"ev_chargers": [{"id": "a"}]}) is True

    def test_legacy_power_sensor(self):
        assert has_managed_charger({"ev_charging_power_sensor": "sensor.wb"}) is True

    def test_dashboard_ev_alone_is_data_not_a_managed_charger(self):
        assert install_modules({}, ED_EV, True)[Module.EV] is Presence.PRESENT
        assert has_managed_charger({}) is False


_ORACLE_SRC = Path(__file__).resolve().parents[1] / "coordinator" / "install_modules.py"
LOOKS_LIKE_A_MODULE = re.compile(
    r"battery|(^|_)ev(_|$)|heat_pump|hot_water|legionella|charg|session|vehicle")


def _static_lists():
    from custom_components.solar_energy_management.binary_sensor import BINARY_SENSOR_TYPES
    from custom_components.solar_energy_management.button import BUTTONS
    from custom_components.solar_energy_management.number import NUMBER_TYPES
    from custom_components.solar_energy_management.sensor import SENSOR_TYPES
    from custom_components.solar_energy_management.switch import SWITCH_TYPES
    return {"sensor": SENSOR_TYPES, "number": NUMBER_TYPES, "switch": SWITCH_TYPES,
            "binary_sensor": BINARY_SENSOR_TYPES, "button": BUTTONS}


def _static_keys():
    return {(p, d.key) for p, ds in _static_lists().items() for d in ds}


class TestTheTable:

    def test_every_row_names_an_entity_a_platform_creates(self):
        stale = sorted(set(ENTITY_MODULES) - _static_keys())
        assert not stale, f"rows for keys no platform creates: {stale}"

    def test_core_by_decision_rows_are_real_and_not_modules(self):
        assert set(CORE_BY_DECISION) <= _static_keys()
        assert not set(CORE_BY_DECISION) & set(ENTITY_MODULES)

    def test_every_module_look_alike_has_chosen(self):
        undecided = sorted(
            pk for pk in _static_keys()
            if LOOKS_LIKE_A_MODULE.search(pk[1])
            and pk not in ENTITY_MODULES and pk not in CORE_BY_DECISION
        )
        assert not undecided, (
            "an entity named like a module must be put in ENTITY_MODULES or, "
            f"with its reason, in CORE_BY_DECISION: {undecided}")

    def test_charging_state_is_core(self):
        # It carries the Home tab's today_plan and is the Config tab's
        # "set up" marker on EVERY install.
        assert ("sensor", "charging_state") not in ENTITY_MODULES

    @pytest.mark.parametrize("pk", [
        ("switch", "battery_may_assist_ev"),
        ("number", "battery_assist_max_power"),
        ("number", "battery_assist_min_surplus"),
        ("sensor", "flow_battery_to_ev_power"),
        ("sensor", "flow_battery_to_ev_energy"),
        ("sensor", "lifetime_ev_battery_share"),
    ])
    def test_battery_to_ev_needs_both(self, pk):
        assert ENTITY_MODULES[pk] == {Module.BATTERY, Module.EV}

    def test_the_counts_the_spec_states(self):
        by_module = Counter(frozenset(m) for m in ENTITY_MODULES.values())
        assert by_module[frozenset({Module.BATTERY})] == 59
        assert by_module[frozenset({Module.BATTERY, Module.EV})] == 6
        assert by_module[frozenset({Module.EV})] == 33
        assert by_module[frozenset({Module.HEAT_PUMP})] == 11
        assert by_module[frozenset({Module.HOT_WATER})] == 4
        assert len(ENTITY_MODULES) == 113

    def test_the_oracle_stays_importable_without_home_assistant(self):
        # validate-sem.sh loads this file by path on sem-dev, where HA is
        # not installed.
        tree = ast.parse(_ORACLE_SRC.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add((node.module or "").split(".")[0])
        assert roots <= {"__future__", "enum", "typing"}, roots


class TestKeepRules:
    ALL_ABSENT = {m: Presence.ABSENT for m in Module}

    def test_unknown_keeps(self):
        assert keeps(all_unknown(), [Module.BATTERY])

    def test_absent_drops(self):
        assert not keeps({Module.BATTERY: Presence.ABSENT}, [Module.BATTERY])

    def test_core_is_always_kept(self):
        assert entity_kept("sensor", "solar_power", self.ALL_ABSENT)
        assert entity_kept("sensor", "charging_state", self.ALL_ABSENT)

    def test_cross_module_drops_when_either_is_absent(self):
        p = {Module.BATTERY: Presence.PRESENT, Module.EV: Presence.ABSENT}
        assert not entity_kept("switch", "battery_may_assist_ev", p)
        assert entity_kept("sensor", "battery_soc", p)

    def test_kept_descriptions_filters_by_key(self):
        descs = [SimpleNamespace(key="battery_soc"), SimpleNamespace(key="solar_power")]
        kept = kept_descriptions("sensor", descs, {Module.BATTERY: Presence.ABSENT})
        assert [d.key for d in kept] == ["solar_power"]

    def test_absent_entity_ids_are_the_forced_ids(self):
        gone = absent_entity_ids({**all_unknown(), Module.BATTERY: Presence.ABSENT})
        assert "sensor.sem_battery_soc" in gone
        assert "switch.sem_battery_may_assist_ev" in gone
        assert "number.sem_battery_capacity" in gone
        assert "button.sem_backfill_battery_nights" in gone
        assert "sensor.sem_ev_power" not in gone
        assert "sensor.sem_solar_power" not in gone

    def test_nothing_is_absent_while_unknown(self):
        assert absent_entity_ids(all_unknown()) == frozenset()


class TestPresenceOf:

    def test_a_test_double_builds_everything(self):
        assert presence_of(MagicMock()) == all_unknown()

    def test_no_coordinator_builds_everything(self):
        assert presence_of(None) == all_unknown()

    def test_the_setup_verdict_is_returned_and_completed(self):
        p = presence_of(SimpleNamespace(setup_presence={Module.BATTERY: Presence.ABSENT}))
        assert p[Module.BATTERY] is Presence.ABSENT
        assert p[Module.EV] is Presence.UNKNOWN

    def test_summary(self):
        assert presence_summary({Module.BATTERY: Presence.ABSENT}) == {
            "battery": "absent", "ev": "unknown", "heat_pump": "unknown",
            "hot_water": "unknown"}
