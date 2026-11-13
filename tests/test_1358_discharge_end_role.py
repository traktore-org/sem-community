"""(#1358) The inverter's own end-of-discharge level, read only.

The night plan draws the battery down to its floor. That floor is the higher
of SEM's reserve and the level where the inverter itself stops discharging,
when the crawler finds that entity. Someone may change the inverter's level
in the vendor's app; the plan follows it. SEM only reads it.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts import role_lexicon as lex
from custom_components.solar_energy_management.consts.battery_modes import (
    battery_floor_of,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .ast_contracts import calls

_ROOT = Path(__file__).resolve().parent.parent
_KEY = "battery_discharge_end_soc_entity"
ROLE = "battery_discharge_end_soc"


class TestTheRole:
    @pytest.mark.parametrize("key", [
        "storage_discharging_cutoff_capacity", "discharging_cutoff_capacity",
        "plant_discharge_cut_off_soc", "soc_lower_limit",
        "battery_min_discharge_soc", "minimum_discharge_soc",
        "end_of_discharge_soc", "discharge_end_soc",
    ])
    def test_an_end_of_discharge_name_is_the_read_only_role(self, key):
        assert lex.role_for("number", key) == ROLE, key

    @pytest.mark.parametrize("key", [
        # the end of CHARGE is the twin, not this
        "storage_charging_cutoff_capacity", "soc_upper_limit",
        # a reserve for a grid outage is another level
        "storage_backup_power_soc", "backup_discharge_end_soc",
        "eps_discharge_cutoff_soc", "offgrid_discharge_cut_off_soc",
        # a limit in watts, a peak-shaving level, the charge level itself
        "max_discharge_power", "battery_discharge_power_limit",
        "storage_capacity_control_soc_peak_shaving", "battery_soc",
    ])
    def test_lookalikes_are_not(self, key):
        assert lex.role_for("number", key) != ROLE, key
        assert lex.role_for("sensor", key) != ROLE, key

    def test_the_role_binds_one_key_by_one_click_and_is_read_only(self):
        assert lex.SEM_CONFIG_KEY_FOR_ROLE[ROLE] == _KEY
        assert lex.ROLE_EXPECTED_UNIT[ROLE] == "percent"
        assert ROLE in lex.READ_ONLY_CONTROL_ROLES

    def test_the_roster_carries_it(self):
        from custom_components.solar_energy_management.consts import (
            integration_roster as r)
        doms = [d for d, roles in r.ROLE_VOCAB.items() if ROLE in roles]
        assert doms, "the crawler found no end-of-discharge register at all"
        for dom, roles in r.ROLE_VOCAB.items():
            end = set((roles.get(ROLE) or {}).get("keys", ()))
            chg = set((roles.get("battery_charge_end_soc") or {}).get("keys", ()))
            assert not (end & chg), dom

    def test_every_declared_key_is_proposed_from_an_install(self):
        from custom_components.solar_energy_management.consts import (
            integration_roster as r)
        from custom_components.solar_energy_management.hardware_detection import (
            propose_roles_from_roster)
        seen = 0
        for dom, roles in r.ROLE_VOCAB.items():
            body = roles.get(ROLE)
            if not body:
                continue
            for key in body["keys"]:
                ent = SimpleNamespace(
                    entity_id=f"number.x_{key}", platform=dom, device_id="d1",
                    translation_key=key, unique_id="",
                    original_device_class=None, disabled_by=None,
                    config_entry_id="e1")
                got = propose_roles_from_roster([ent], dom).get(ROLE)
                assert got and got["entity"] == ent.entity_id, (dom, key)
                assert got["config_key"] == _KEY
                seen += 1
        assert seen


class TestTheFloor:
    @pytest.mark.parametrize("cfg, level, want", [
        ({"battery_reserve_soc": 20}, 25.0, (25.0, "inverter")),
        ({"battery_reserve_soc": 20}, 15.0, (20.0, "reserve")),
        ({"battery_reserve_soc": 20}, 20.0, (20.0, "reserve")),
        ({"battery_reserve_soc": 20}, None, (20.0, "reserve")),       # not read
        ({"battery_reserve_soc": 20}, "unknown", (20.0, "reserve")),
        ({"battery_reserve_soc": 20}, 150.0, (20.0, "reserve")),      # out of range
        ({"battery_reserve_soc": 20}, -5.0, (20.0, "reserve")),
        ({"battery_reserve_soc": 20}, float("nan"), (20.0, "reserve")),
        ({"battery_reserve_soc": 20}, True, (20.0, "reserve")),
        ({}, None, (20.0, "reserve")),                                  # no entity
        ({"battery_reserve_soc": 30}, 25.0, (30.0, "reserve")),
    ])
    def test_the_higher_of_reserve_and_inverter(self, cfg, level, want):
        assert battery_floor_of(cfg, level) == want

    def _coord(self, cfg, states):
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = cfg
        c.hass = SimpleNamespace(states=SimpleNamespace(
            get=lambda eid: (SimpleNamespace(state=states[eid])
                             if eid in states else None)))
        return c

    def test_prod_shaped_install_keeps_todays_floor(self):
        # PROD: reserve unset (default 20), Huawei end of discharge at 20
        c = self._coord(
            {"battery_reserve_soc": None,
             _KEY: "number.batteries_entlade_ende_ladestand"},
            {"number.batteries_entlade_ende_ladestand": "20.0"})
        assert c._battery_floor() == (20.0, "reserve")

    def test_a_higher_inverter_level_raises_the_floor(self):
        c = self._coord({_KEY: "number.end"}, {"number.end": "35"})
        assert c._battery_floor() == (35.0, "inverter")

    def test_an_unavailable_or_missing_entity_keeps_the_reserve(self):
        assert self._coord({_KEY: "number.end"}, {"number.end": "unavailable"}
                           )._battery_floor() == (20.0, "reserve")
        assert self._coord({_KEY: "number.gone"}, {})._battery_floor() == (20.0, "reserve")
        assert self._coord({}, {})._battery_floor() == (20.0, "reserve")

    def test_the_plan_reads_the_one_helper(self):
        from custom_components.solar_energy_management.coordinator import coordinator as cmod
        assert calls(SEMCoordinator._shadow_energy_plan, "_battery_floor_for")
        assert calls(cmod._battery_floor_for, "battery_floor_of")
        assert calls(cmod._battery_floor_for, "_discharge_end_reading")


class TestNeverWritten:
    def test_the_reader_calls_no_service(self):
        src = (_ROOT / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_discharge_end_reading")
        names = {getattr(c.func, "attr", getattr(c.func, "id", ""))
                 for c in ast.walk(fn) if isinstance(c, ast.Call)}
        assert not names & {"async_call", "call", "send", "async_set_value"}, names

    def test_no_adapter_or_actuator_names_the_key(self):
        for p in (_ROOT / "coordinator").rglob("*.py"):
            rel = p.relative_to(_ROOT).as_posix()
            if rel.startswith("coordinator/battery_adapters") or "actuate" in rel:
                assert _KEY not in p.read_text(encoding="utf-8"), rel
