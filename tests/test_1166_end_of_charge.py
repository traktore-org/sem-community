"""#1166 — Force charge never ended on a pack set to stop below 90 %.

#1164 ends Force charge when the pack takes no more for 15 minutes at 90 %
or above. Some inverters let the user set a lower end of charge (80 %): such
a pack never reaches 90 %, the mode stays on, the house takes 1 % and SEM
buys it back from the grid at once.

The fix reads the pack's OWN end-of-charge level — a read-only entity per
battery (``battery_charge_end_soc_entity``), proposed by the crawler as the
role ``battery_charge_end_soc`` and bound only when the user accepts it —
and lets a stall count from ``min(90 %, level - margin)``. No level, or one
SEM cannot read: the 90 % rule exactly as before.

Four links:

* ``charge_stall_soc`` / ``charge_stall_read`` — the pure rule;
* ``SEMCoordinator._finish_manual_battery_modes`` on a real config entry,
  each pack reading its own level through ``_per_battery_config``;
* the crawler: the lexicon puts end-of-charge NAMES on the read-only role
  (never on the target SEM writes), and the roster proposes it from any
  install's entities by the same intersection as every other role;
* nothing in SEM writes the entity.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts import (
    role_lexicon as lex,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryRuntime,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    MANUAL_CHARGE_END_MARGIN,
    MANUAL_CHARGE_END_MIN_SOC,
    MANUAL_CHARGE_STALL_S,
    MANUAL_CHARGE_STALL_SOC,
    charge_stall_read,
    charge_stall_soc,
)
from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as READS,
)

# The coordinator harness of #1164: a real entry, the real overlay.
from .test_1164_force_charge_stall import (  # noqa: F401 — fixture
    _HAS_PHACC, _coordinator, _entry, clock,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_KEY = "battery_charge_end_soc_entity"
_LIST_KEY = "battery_charge_end_soc_entities"
_STALL = dict(soc_read=True, power_read=True, asked_w=5000.0, sem_charging=True)


# ── 1. The rule ────────────────────────────────────────────────────────────

class TestTheRule:
    def test_no_level_is_the_90_percent_rule(self):
        assert charge_stall_soc(None) == MANUAL_CHARGE_STALL_SOC == 90.0

    @pytest.mark.parametrize("bad", [
        "unknown", "unavailable", "", "abc", True, float("nan"),
        MANUAL_CHARGE_END_MIN_SOC - 1, 0.0, -5.0, 101.0, 150.0])
    def test_a_level_that_is_no_end_of_charge_is_the_90_percent_rule(self, bad):
        # A reserve or a floor bound by mistake must not end a cold
        # pack's charge at 20 %.
        assert charge_stall_soc(bad) == MANUAL_CHARGE_STALL_SOC

    @pytest.mark.parametrize("level,expect", [
        (80.0, 80.0 - MANUAL_CHARGE_END_MARGIN),
        ("85", 85.0 - MANUAL_CHARGE_END_MARGIN),
        (MANUAL_CHARGE_END_MIN_SOC, MANUAL_CHARGE_END_MIN_SOC - MANUAL_CHARGE_END_MARGIN),
        # At or above 90 + margin the 90 % rule is already the lower one.
        (95.0, MANUAL_CHARGE_STALL_SOC),
        (100.0, MANUAL_CHARGE_STALL_SOC),
    ])
    def test_the_level_is_never_above_90(self, level, expect):
        assert charge_stall_soc(level) == expect

    def test_a_pack_stopped_at_its_80_percent_is_a_stall_read(self):
        at = charge_stall_soc(80.0)
        assert charge_stall_read(80.0, 0.0, **_STALL, stall_soc=at) is True
        assert charge_stall_read(79.0, 0.0, **_STALL, stall_soc=at) is True

    def test_a_pack_below_its_own_level_is_not(self):
        # Cold, or grid charging off on the inverter: it refuses at 60 %.
        at = charge_stall_soc(80.0)
        assert charge_stall_read(60.0, 0.0, **_STALL, stall_soc=at) is False
        assert charge_stall_read(at - 0.1, 0.0, **_STALL, stall_soc=at) is False

    def test_the_default_is_develops_rule(self):
        assert charge_stall_read(80.0, 0.0, **_STALL) is False
        assert charge_stall_read(90.0, 0.0, **_STALL) is True


# ── 2. The coordinator ends the mode ───────────────────────────────────────

def _bind_end_soc(coordinator):
    coordinator._charge_end_soc = (
        lambda cfg: SEMCoordinator._charge_end_soc(coordinator, cfg))
    return coordinator


def _run(coordinator, clock, packs, minutes, *, step_s=30.0):
    items = [(bid, BatteryRuntime(battery_id=bid, last_known_soc=soc,
                                  last_known_w=w))
             for bid, (soc, w) in packs.items()]
    read = {bid: True for bid in packs}
    for _ in range(int(minutes * 60 / step_s)):
        clock.t += step_s
        SEMCoordinator._finish_manual_battery_modes(
            coordinator, items, read, len(items), power_read=dict(read))


_DONE_MIN = MANUAL_CHARGE_STALL_S / 60 + 1 + READS * 30 / 60


@pytest.mark.skipif(not _HAS_PHACC, reason="pytest-homeassistant-custom-component not installed")
class TestAPackSetToStopAt80:
    @pytest.mark.asyncio
    async def test_it_goes_back_to_auto_after_the_stall(self, hass, clock):
        hass.states.async_set("number.pack_end", "80", {"unit_of_measurement": "%"})
        entry = _entry(hass, {"battery_mode": "force_charge", _KEY: "number.pack_end"})
        coordinator = _bind_end_soc(_coordinator(hass, entry, (), ["primary"]))
        _run(coordinator, clock, {"primary": (80.0, 0.0)},
             MANUAL_CHARGE_STALL_S / 60 - 1)
        assert entry.options["battery_mode"] == "force_charge", (
            "14 minutes are not enough")
        _run(coordinator, clock, {"primary": (80.0, 0.0)}, 1 + READS * 30 / 60)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_a_cold_pack_below_its_level_keeps_the_mode(self, hass, clock):
        hass.states.async_set("number.pack_end", "80", {"unit_of_measurement": "%"})
        entry = _entry(hass, {"battery_mode": "force_charge", _KEY: "number.pack_end"})
        coordinator = _bind_end_soc(_coordinator(hass, entry, (), ["primary"]))
        _run(coordinator, clock, {"primary": (55.0, 0.0)}, 120)
        assert entry.options["battery_mode"] == "force_charge"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("options,state", [
        ({}, None),                                         # nothing configured
        ({_KEY: "number.pack_end"}, None),                  # entity missing
        ({_KEY: "number.pack_end"}, "unavailable"),
        ({_KEY: "number.pack_end"}, "unknown"),
        ({_KEY: "number.pack_end"}, "10"),                  # a floor, not an end
    ])
    async def test_without_a_level_it_is_develops_behaviour(
            self, hass, clock, options, state):
        if state is not None:
            hass.states.async_set("number.pack_end", state)
        entry = _entry(hass, {"battery_mode": "force_charge", **options})
        coordinator = _bind_end_soc(_coordinator(hass, entry, (), ["primary"]))
        _run(coordinator, clock, {"primary": (80.0, 0.0)}, 120)
        assert entry.options["battery_mode"] == "force_charge", (
            "an 80 % pack with no level read stays, as on develop")
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, _DONE_MIN)
        assert entry.options["battery_mode"] == "auto", "90 % still ends it"

    @pytest.mark.asyncio
    async def test_each_pack_reads_its_own_level(self, hass, clock):
        # b1 stops at 80 %, b2 at 100 %: at 80 % and idle, b1 is done and b2
        # (cold, below its own level) is not.
        hass.states.async_set("number.b1_end", "80")
        hass.states.async_set("number.b2_end", "100")
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"],
                              _LIST_KEY: ["number.b1_end", "number.b2_end"]})
        coordinator = _bind_end_soc(
            _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"]))
        _run(coordinator, clock, {"b1": (80.0, 0.0), "b2": (80.0, 0.0)}, 20)
        assert entry.options["battery_modes"] == ["auto", "force_charge"]

    @pytest.mark.asyncio
    async def test_an_empty_slot_uses_the_shared_entity(self, hass, clock):
        hass.states.async_set("number.shared_end", "80")
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"],
                              _KEY: "number.shared_end",
                              _LIST_KEY: [None, None]})
        coordinator = _bind_end_soc(
            _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"]))
        _run(coordinator, clock, {"b1": (80.0, 0.0), "b2": (80.0, 0.0)}, 20)
        assert entry.options["battery_modes"] == ["auto", "auto"]


# ── 3. The crawler proposes the role ───────────────────────────────────────

class TestTheLexicon:
    """Key SHAPES, not brands: what an end-of-charge register is called."""

    @pytest.mark.parametrize("key", [
        "soc_upper_limit", "battery_soc_upper_limit",
        "battery_max_charge_soc", "max_charge_soc", "maximum_charging_soc",
        "plant_charge_cut_off_soc", "charge_cutoff_soc",
        "charging_cutoff_capacity", "storage_charging_cutoff_capacity",
        "end_of_charge_soc", "charge_end_soc",
    ])
    def test_an_end_of_charge_name_is_the_read_only_role(self, key):
        assert lex.role_for("number", key) == "battery_charge_end_soc", key

    @pytest.mark.parametrize("key", [
        "forced_charging_target_soc_1", "battery_force_charge_soc",
        "ac_charge_soc_limit", "battery_charge_soc_limit",
    ])
    def test_a_charge_target_stays_the_target(self, key):
        assert lex.role_for("number", key) == "battery_target_soc", key

    @pytest.mark.parametrize("key", [
        "discharging_cutoff_capacity", "min_charge_soc", "lower_charge_soc",
        "system_charge_soc_limit", "ac_couple_end_of_charge",
        "backup_charge_cutoff_soc", "sockets_1_upper_limit",
        "charge_state_charge_limit_soc", "max_charge_power",
    ])
    def test_floors_and_lookalikes_are_not(self, key):
        assert lex.role_for("number", key) != "battery_charge_end_soc", key
        assert lex.role_for("sensor", key) != "battery_charge_end_soc", key

    def test_the_role_binds_one_key_by_one_click(self):
        assert lex.SEM_CONFIG_KEY_FOR_ROLE["battery_charge_end_soc"] == _KEY
        assert lex.ROLE_EXPECTED_UNIT["battery_charge_end_soc"] == "percent"
        assert "battery_charge_end_soc" in lex.READ_ONLY_CONTROL_ROLES

    def test_the_rule_comes_before_the_target(self):
        # First match wins; the end of charge must be asked first.
        order = list(lex.ROLE_RULES)
        assert order.index("battery_charge_end_soc") < order.index("battery_target_soc")


def _roster():
    from custom_components.solar_energy_management.consts import (
        integration_roster as r)
    return r


class TestTheRoster:
    def test_the_roster_carries_the_role(self):
        doms = [d for d, roles in _roster().ROLE_VOCAB.items()
                if "battery_charge_end_soc" in roles]
        assert doms, "the crawler found no end-of-charge register at all"

    def test_no_domain_offers_one_key_as_both_end_and_target(self):
        for dom, roles in _roster().ROLE_VOCAB.items():
            end = set((roles.get("battery_charge_end_soc") or {}).get("keys", ()))
            tgt = set((roles.get("battery_target_soc") or {}).get("keys", ()))
            assert not (end & tgt), dom
            for k in tgt:
                assert lex.role_for("number", k) != "battery_charge_end_soc", (dom, k)

    @pytest.mark.parametrize("by", ["translation_key", "unique_id"])
    def test_every_declared_key_is_proposed_from_an_install(self, by):
        """For every domain that declares the role, an install carrying that
        key is offered it, with the one-click key — the same intersection as
        every other role. Walked over the roster, not a brand list."""
        from custom_components.solar_energy_management.hardware_detection import (
            propose_roles_from_roster)
        seen = 0
        for dom, roles in _roster().ROLE_VOCAB.items():
            body = roles.get("battery_charge_end_soc")
            if not body:
                continue
            exact = set(body.get("exact_only", ()))
            for key in body["keys"]:
                if by == "unique_id" and key in exact:
                    continue
                ent = SimpleNamespace(
                    entity_id=f"number.x_{key}", platform=dom, device_id="d1",
                    translation_key=key if by == "translation_key" else "",
                    unique_id=f"SN123_{key}" if by == "unique_id" else "",
                    original_device_class=None, disabled_by=None,
                    config_entry_id="e1")
                prop = propose_roles_from_roster([ent], dom)
                got = prop.get("battery_charge_end_soc")
                assert got and got["entity"] == ent.entity_id, (dom, key)
                assert got["config_key"] == _KEY
                assert got["action"] == "set_option"
                seen += 1
        assert seen

    @pytest.mark.parametrize("unit,action", [
        ("%", "set_option"), ("W", "unit_mismatch"), (None, "no_unit")])
    def test_the_button_needs_a_percent(self, unit, action):
        from custom_components.solar_energy_management.hardware_detection import (
            propose_roles_from_roster)
        dom, body = next((d, r["battery_charge_end_soc"])
                         for d, r in sorted(_roster().ROLE_VOCAB.items())
                         if "battery_charge_end_soc" in r)
        key = body["keys"][0]
        ent = SimpleNamespace(entity_id=f"number.x_{key}", platform=dom,
                              device_id="d1", translation_key=key, unique_id="",
                              original_device_class=None, disabled_by=None,
                              config_entry_id="e1")
        attrs = {"unit_of_measurement": unit} if unit else {}
        st = SimpleNamespace(state="80", attributes=attrs)
        prop = propose_roles_from_roster([ent], dom, state_of=lambda _e: st)
        assert prop["battery_charge_end_soc"]["action"] == action

    def test_nothing_binds_before_the_user_accepts(self):
        # The proposal is report data: it carries the key, it writes nothing.
        from custom_components.solar_energy_management.hardware_detection import (
            propose_for_installed)
        dom, body = next((d, r["battery_charge_end_soc"])
                         for d, r in sorted(_roster().ROLE_VOCAB.items())
                         if "battery_charge_end_soc" in r)
        key = body["keys"][0]
        ent = SimpleNamespace(entity_id=f"number.x_{key}", platform=dom,
                              device_id="d1", translation_key=key, unique_id="",
                              original_device_class=None, disabled_by=None,
                              config_entry_id="e1")
        reg = SimpleNamespace(entities={ent.entity_id: ent})
        rows = propose_for_installed(reg)
        row = next(r for r in rows if r["domain"] == dom)
        assert row["proposed_roles"]["battery_charge_end_soc"]["config_key"] == _KEY
        # Already bound: not news any more.
        rows = propose_for_installed(reg, configured_entities=[ent.entity_id])
        assert all("battery_charge_end_soc" not in r["proposed_roles"]
                   for r in rows if r["domain"] == dom)


# ── 4. Never written ───────────────────────────────────────────────────────

_ALLOWED = {
    # the coordinator reads it; the stall rule, the flow, the reload list,
    # diagnostics, the lexicon and the install modules' evidence only NAME it
    "coordinator/coordinator.py", "coordinator/decide_battery.py",
    "config_flow.py", "__init__.py",
    "diagnostics.py", "consts/role_lexicon.py",
    "coordinator/install_modules.py",
    # (#1195) moves the saved list with its battery; sends nothing
    "coordinator/battery_controls.py",
    # (#1256) lists the wired entities that are gone; re-points, sends nothing
    "coordinator/battery_sensor_check.py",
}


class TestNeverWritten:
    def test_only_readers_name_the_key(self):
        hits = set()
        for p in _ROOT.rglob("*.py"):
            rel = p.relative_to(_ROOT).as_posix()
            if rel.startswith(("tests/", "scripts/")) or "node_modules" in rel:
                continue
            if "battery_charge_end_soc_entit" in p.read_text(encoding="utf-8"):
                hits.add(rel)
        assert hits == _ALLOWED, hits ^ _ALLOWED
        # No adapter, no actuator: nothing that sends a command knows it.
        assert not any(h.startswith("coordinator/battery_adapters") for h in hits)

    def test_the_reader_calls_no_service(self):
        src = (_ROOT / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_charge_end_soc")
        body = ast.unparse(fn)
        assert "states.get" in body
        for word in ("async_call", "services", "set_value", "persist_"):
            assert word not in body, word

    def test_no_service_call_targets_the_entity(self, monkeypatch):
        """Drive the read with a hass that records every service call."""
        calls = []
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda eid: SimpleNamespace(state="80")),
            services=SimpleNamespace(
                async_call=lambda *a, **k: calls.append((a, k))))
        me = SimpleNamespace(hass=hass)
        assert SEMCoordinator._charge_end_soc(me, {_KEY: "number.pack_end"}) == 80.0
        assert calls == []


@pytest.mark.skipif(importlib.util.find_spec("voluptuous") is None, reason="no voluptuous")
def test_the_options_flow_owns_both_keys():
    from custom_components.solar_energy_management import config_flow
    assert {_KEY, _LIST_KEY} <= set(config_flow.OPTIONS_FLOW_OWNED_KEYS)
