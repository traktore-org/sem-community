"""(#1081) The heat meter: found by the crawler, read once a cycle, learned
from, and acted on only when the user picks "learned".
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts import role_lexicon as lex
from custom_components.solar_energy_management.coordinator import cop_learner as cl
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .ast_contracts import calls

_ROOT = Path(__file__).resolve().parent.parent
ROLE = "heat_pump_heat_energy"
KEY = "heat_pump_heat_energy_sensor"


class TestTheRole:
    @pytest.mark.parametrize("key", [
        "produced_heating_total", "total_heat_energy", "hp_thermal_energy_total",
        "compressor_thermal_energy_output_accumulated", "heat_meter",
        "heat_quantity", "heating_thermal_energy_total",
    ])
    def test_a_heat_meter_name_is_the_role(self, key):
        assert lex.role_for("sensor", key) == ROLE, key

    @pytest.mark.parametrize("key", [
        # a counter that resets, the electricity side, other heat
        "produced_heating_today", "heat_energy_daily", "heat_energy_month",
        "consumed_power_heating_total", "electric_energy_heating",
        "heat_energy_consumption", "produced_hot_water_total",
        "dhw_heat_energy", "thermal_energy_cooling", "defrost_heat_energy",
        # not energy at all
        "flow_temperature", "heat_power", "cop_heating",
    ])
    def test_lookalikes_are_not(self, key):
        assert lex.role_for("sensor", key) != ROLE, key

    def test_the_role_sets_the_primary_key_and_wants_energy(self):
        assert lex.SEM_CONFIG_KEY_FOR_ROLE[ROLE] == KEY
        assert lex.ROLE_EXPECTED_UNIT[ROLE] == "energy"
        assert lex.UNIT_CLASSES["energy"] == {"Wh", "kWh", "MWh"}

    def test_the_roster_carries_it_and_proposes_it(self):
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
                    entity_id=f"sensor.x_{key}", platform=dom, device_id="d1",
                    translation_key=key, unique_id="",
                    original_device_class="energy", disabled_by=None,
                    config_entry_id="e1")
                got = propose_roles_from_roster([ent], dom).get(ROLE)
                assert got and got["config_key"] == KEY, (dom, key)
                seen += 1
        assert seen >= 3


class TestWiring:
    def test_every_heat_pump_row_carries_the_key(self):
        from custom_components.solar_energy_management import _heat_pump_rows
        rows = _heat_pump_rows({
            KEY: "sensor.hm1",
            "heat_pumps": [{"id": "heat_pump_2", KEY: "sensor.hm2"}]})
        assert [r.get(KEY) for r in rows] == ["sensor.hm1", "sensor.hm2"]

    def test_a_change_reloads(self):
        src = (_ROOT / "__init__.py").read_text(encoding="utf-8")
        head = src[:src.index("def _heat_pump_rows")]
        assert f'"{KEY}"' in head

    def test_both_forms_ask_for_it_in_every_language(self):
        import json
        flow = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
        assert flow.count(f'"{KEY}"') >= 3      # known key + two forms
        for f in [_ROOT / "strings.json", *(_ROOT / "translations").glob("*.json")]:
            st = json.loads(f.read_text(encoding="utf-8"))["options"]["step"]
            assert st["heat_pump"]["data"].get(KEY), f.name
            assert st["heat_pump_unit"]["data"].get(KEY), f.name


class _Dev(SimpleNamespace):
    def observed_power_w(self):
        return self.watts


def _coord(devs, states, lifetime, outdoor=4.0, stored=None):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = SimpleNamespace(states=SimpleNamespace(
        get=lambda eid: (SimpleNamespace(state=str(states[eid]),
                                         attributes={"unit_of_measurement": "kWh"})
                         if eid in states else None)))
    c._surplus_controller = SimpleNamespace(_devices={d.device_id: d for d in devs})
    c._energy_calculator = SimpleNamespace(
        get_device_energy=lambda did, day: {"lifetime_kwh": lifetime[did]})
    c.time_manager = SimpleNamespace(
        get_current_meter_day_sunrise_based=lambda: date(2026, 12, 1))
    c._outdoor_temperature_or_none = lambda: outdoor
    saved = {"cop_learn_state": dict(stored or {})}
    c._storage = SimpleNamespace(
        get_cop_learn_state=lambda: dict(saved["cop_learn_state"]),
        set_cop_learn_state=lambda s: saved.__setitem__("cop_learn_state", s))
    return c, saved


def _hp(did="heat_pump", meter="sensor.hm", measured=True, watts=2000.0):
    return _Dev(device_id=did, heat_energy_entity_id=meter, cop=3.0,
                cop_curve=None, cop_source="", cop_learned=[],
                cop_learn_summary=None, rated_power=2000.0,
                daily_energy_is_measured=measured, daily_energy_blind_s=0.0,
                _daily_runtime_meter_day=None, watts=watts)


def _run_hours(c, dev, states, lifetime, hours, monkeypatch, cop=3.5):
    from custom_components.solar_energy_management.coordinator import coordinator as cmod
    for h in range(hours + 1):
        for m in (0, 20, 40):
            when = datetime(2026, 12, 1, h % 24, m) if h < 24 else \
                datetime(2026, 12, 2, h - 24, m)
            monkeypatch.setattr(cmod.dt_util, "now", lambda w=when: w)
            c._feed_cop_learners()
            lifetime[dev.device_id] += 2.0 / 3
            states[dev.heat_energy_entity_id] += 2.0 / 3 * cop


class TestTheCoordinatorFeed:
    def test_hours_become_a_learned_point(self, monkeypatch):
        dev = _hp()
        states, life = {"sensor.hm": 100.0}, {"heat_pump": 50.0}
        c, _ = _coord([dev], states, life)
        _run_hours(c, dev, states, life, cl.TRUST_HOURS, monkeypatch)
        assert dev.cop_learned == [(4.0, 3.5)]
        assert dev.cop_learn_summary["state"] == cl.LEARNED

    def test_an_estimated_draw_teaches_nothing(self, monkeypatch):
        dev = _hp(measured=False)
        states, life = {"sensor.hm": 100.0}, {"heat_pump": 50.0}
        c, _ = _coord([dev], states, life)
        _run_hours(c, dev, states, life, cl.TRUST_HOURS, monkeypatch)
        assert dev.cop_learned == []
        assert c._cop_learn_states["heat_pump"]["rejected"].get("unread")

    def test_a_blind_meter_spoils_the_hour(self, monkeypatch):
        dev = _hp()
        states, life = {"sensor.hm": 100.0}, {"heat_pump": 50.0}
        c, _ = _coord([dev], states, life)
        from custom_components.solar_energy_management.coordinator import coordinator as cmod
        monkeypatch.setattr(cmod.dt_util, "now", lambda: datetime(2026, 12, 1, 3, 0))
        c._feed_cop_learners()
        dev.daily_energy_blind_s = 30.0
        monkeypatch.setattr(cmod.dt_util, "now", lambda: datetime(2026, 12, 1, 3, 30))
        c._feed_cop_learners()
        assert c._cop_learn_states["heat_pump"]["hour"]["bad"] is True

    def test_no_meter_reads_nothing_and_stores_nothing(self, monkeypatch):
        dev = _hp(meter=None)
        reads = []
        c, saved = _coord([dev], {}, {"heat_pump": 1.0})
        c._outdoor_temperature_or_none = lambda: reads.append(1)
        c._feed_cop_learners()
        assert reads == []
        assert dev.cop_learn_summary["state"] == cl.NO_METER
        assert c._cop_learn_states == {}

    def test_a_restart_goes_on_from_the_store(self, monkeypatch):
        dev = _hp()
        states, life = {"sensor.hm": 100.0}, {"heat_pump": 50.0}
        c, saved = _coord([dev], states, life)
        _run_hours(c, dev, states, life, 3, monkeypatch)
        stored = {"heat_pump": c._cop_learn_states["heat_pump"]}
        dev2 = _hp()
        c2, _ = _coord([dev2], states, life, stored=stored)
        _run_hours(c2, dev2, states, life, cl.TRUST_HOURS - 3, monkeypatch)
        assert dev2.cop_learned, c2._cop_learn_states["heat_pump"]

    def test_the_cycle_and_the_save_call_it(self):
        assert calls(SEMCoordinator._feed_cop_learners, "observe")
        src = (_ROOT / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        assert "self._feed_cop_learners()" in src
        assert "set_cop_learn_state(" in src


class TestTheChoice:
    @pytest.mark.parametrize("raw, want", [
        ("learned", "learned"), ("Curve", "curve"), ("flat", "flat"),
        ("", ""), ("bogus", ""),
    ])
    def test_the_goal_reaches_the_live_pump(self, hass, raw, want):
        from custom_components.solar_energy_management.devices.heat_pump_controller import (
            HeatPumpController)
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry as DeviceRegistry)
        assert "cop_source" in DeviceRegistry.GOAL_PROPERTIES
        dev = HeatPumpController(hass=hass, device_id="heat_pump", name="HP",
                                 climate_entity_id="climate.hp")
        assert dev.cop_source == "" and dev.heat_energy_entity_id is None
        dev.cop_source = "unchanged"
        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg._device_goals = {"heat_pump": {"cop_source": raw}}
        reg._apply_goals(dev)
        assert dev.cop_source == want

    def test_the_plan_and_the_sensor_ask_the_one_reader(self):
        assert calls(SEMCoordinator._plan_cop_fn, "device_cop_at")
        src = (_ROOT / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        assert src.count("cop_at=_plan_cop_at(dev)") == 2
        assert "cop_at=ask_cop.get(i)" in src     # tomorrow's preview too
