"""#1167 — Force charge waited on another battery's dark power sensor.

#1164 ends Force charge on a pack that takes no more at its own level. That
needs the pack's power to be a reading. The reader gave one flag for all
batteries, so a dark power sensor on battery 2 stopped battery 1's check
too, and battery 1 kept buying the next 1 % from the grid.

Each battery's reading now carries its own ``power_read``. The check gets a
map, one entry per battery, and nothing else. The SOC side had the same
shape: each unit's level was read only if the FLEET's SOC flag was clear,
and one dark unit moves the fleet average (the #902 step hold then darkens
every unit). Each unit now counts on its own level read.

Links, each driven for real:

* the reader sets ``BatteryPower.power_read`` per unit (combined sensor,
  two-sensor pair, a dark side, an impossible value, not a number) and the
  sign flip keeps it;
* ``_run_battery_pipeline`` hands each battery its own power and level flag
  to the check, from a real ``read_power``;
* ``_finish_manual_battery_modes`` on a real config entry ends battery 1's
  charge while battery 2's power sensor is dark, and takes nothing but a map.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
    BatteryRuntime,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as READS,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    MANUAL_CHARGE_STALL_S,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _Clock,
    _coordinator,
    _entry,
    _reader,
    _selects,
    _shows,
    _state,
)
from custom_components.solar_energy_management.coordinator import (
    coordinator as cmod,
)

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None


# ── 1. The reader: one flag per unit ───────────────────────────────────────

def _ed_reader(states, *, combined=(), pairs=(), config=None):
    from custom_components.solar_energy_management.ha_energy_reader import (
        EnergyDashboardConfig,
    )
    r = _reader(states, dict(config or {}))
    r.hass.states.async_all = MagicMock(return_value=[])
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(EnergyDashboardConfig(
        battery_power=(list(combined) or [None])[0],
        battery_power_list=list(combined),
        battery_power_pairs=list(pairs),
        has_battery=True, has_solar=False, has_grid=False))
    return r


class TestTheReaderGivesEachUnitItsOwnFlag:
    def test_a_dark_unit_does_not_unread_the_other(self):
        p = _ed_reader({"sensor.b1_power": _state(0, "W"),
                        "sensor.b2_power": _state("unavailable", "W")},
                       combined=["sensor.b1_power", "sensor.b2_power"]).read_power()
        assert p.battery_power_read is False, "the fleet flag is unchanged"
        assert p.battery_power_unavailable is True
        assert p.batteries["b1"].power_read is True
        assert p.batteries["b2"].power_read is False
        assert p.batteries["b2"].power_w == 0.0

    def test_every_unit_read_is_every_flag_set(self):
        p = _ed_reader({"sensor.b1_power": _state(0, "W"),
                        "sensor.b2_power": _state(300, "W")},
                       combined=["sensor.b1_power", "sensor.b2_power"]).read_power()
        assert {b: bp.power_read for b, bp in p.batteries.items()} == {
            "b1": True, "b2": True}

    def test_a_state_that_is_no_number_is_no_reading(self):
        p = _ed_reader({"sensor.b1_power": _state(0, "W"),
                        "sensor.b2_power": _state("none", "W")},
                       combined=["sensor.b1_power", "sensor.b2_power"]).read_power()
        assert p.batteries["b1"].power_read is True
        assert p.batteries["b2"].power_read is False

    def test_an_impossible_unit_is_no_reading_and_the_other_still_is(self):
        p = _ed_reader({"sensor.b1_power": _state(0, "W"),
                        "sensor.b2_power": _state(22806824, "W")},
                       combined=["sensor.b1_power", "sensor.b2_power"]).read_power()
        assert p.batteries["b2"].power_w == 0.0
        assert p.batteries["b2"].power_read is False
        assert p.batteries["b1"].power_read is True

    @pytest.mark.parametrize("to_state,from_state,read", [
        ("0", "0", True),
        ("unavailable", "0", False),
        ("0", "unavailable", False),
    ])
    def test_a_two_sensor_pair_needs_both_sides(self, to_state, from_state, read):
        p = _ed_reader({"sensor.b1_power": _state(0, "W"),
                        "sensor.p_to": _state(to_state, "W"),
                        "sensor.p_from": _state(from_state, "W")},
                       combined=["sensor.b1_power"],
                       pairs=[("sensor.p_from", "sensor.p_to")]).read_power()
        assert set(p.batteries) == {"b1", "b2"}
        assert p.batteries["b1"].power_read is True
        assert p.batteries["b2"].power_read is read

    def test_the_sign_flip_keeps_the_flag(self):
        p = _ed_reader({"sensor.b1_power": _state(250, "W"),
                        "sensor.b2_power": _state("unavailable", "W")},
                       combined=["sensor.b1_power", "sensor.b2_power"],
                       config={"battery_sign_user_flip": True}).read_power()
        assert p.batteries["b1"].power_w == -250.0, "the flip ran"
        assert p.batteries["b1"].power_read is True
        assert p.batteries["b2"].power_read is False

    def test_the_default_is_no_reading(self):
        assert BatteryPower(battery_id="b1").power_read is False


# ── 2. The pipeline hands each battery its own flags ───────────────────────

class _Stop(Exception):
    """Raised by the patched decide_battery: the check has run."""


async def _pipeline(monkeypatch, power):
    from custom_components.solar_energy_management.coordinator import (
        decide_battery as db,
    )
    seen: dict = {}
    stub = MagicMock()
    stub.setup_presence = {m: Presence.PRESENT for m in Module}
    stub._observer_mode = False
    stub._battery_charge_scheduler.enabled = False
    stub.config = {}
    stub._vpp_apply_battery_override = lambda pbc: {}

    def _finish(items, soc_read, count, power_read=None, site=None):
        seen["soc_read"] = soc_read
        seen["power_read"] = power_read

    def _decide(view):
        raise _Stop

    stub._finish_manual_battery_modes = _finish
    monkeypatch.setattr(db, "decide_battery", _decide)
    with pytest.raises(_Stop):
        await SEMCoordinator._run_battery_pipeline(
            stub, power, SimpleNamespace(), "idle")
    return seen


def _two(**fleet):
    base = dict(
        batteries={
            "b1": BatteryPower(battery_id="b1", power_w=0.0, soc_pct=95.0,
                               power_read=True),
            "b2": BatteryPower(battery_id="b2", power_w=0.0, soc_pct=None,
                               power_read=False),
        },
        battery_soc=95.0, battery_power=0.0, battery_soc_known=True,
        battery_soc_unavailable=False, battery_power_unavailable=True,
        battery_power_read=False)
    base.update(fleet)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
class TestThePipeline:
    async def test_each_battery_gets_its_own_power_flag(self, monkeypatch):
        seen = await _pipeline(monkeypatch, _two())
        assert seen["power_read"] == {"b1": True, "b2": False}

    async def test_each_battery_gets_its_own_level_flag(self, monkeypatch):
        # b2's dark SOC moved the fleet average, and the #902 hold darkened
        # the fleet: b1's level was still read.
        seen = await _pipeline(monkeypatch, _two(battery_soc_unavailable=True))
        assert seen["soc_read"] == {"b1": True, "b2": False}

    async def test_a_unit_without_the_flag_is_no_reading(self, monkeypatch):
        power = _two()
        power.batteries["b1"] = SimpleNamespace(
            battery_id="b1", power_w=0.0, soc_pct=95.0, capacity_kwh=0.0,
            name="b1")
        seen = await _pipeline(monkeypatch, power)
        assert seen["power_read"] == {"b1": False, "b2": False}

    async def test_one_battery_keeps_the_fleet_flags(self, monkeypatch):
        one = SimpleNamespace(
            batteries={}, battery_soc=95.0, battery_power=0.0,
            battery_soc_known=True, battery_soc_unavailable=True,
            battery_power_unavailable=False, battery_power_read=True)
        seen = await _pipeline(monkeypatch, one)
        assert seen["soc_read"] == {"primary": False}, "a held level"
        assert seen["power_read"] == {"primary": True}

    async def test_a_real_read_reaches_the_check(self, monkeypatch):
        # The whole chain: battery 2's power sensor is dark.
        p = _ed_reader({"sensor.b1_power": _state(0, "W"),
                        "sensor.b2_power": _state("unavailable", "W")},
                       combined=["sensor.b1_power", "sensor.b2_power"]).read_power()
        seen = await _pipeline(monkeypatch, p)
        assert seen["power_read"] == {"b1": True, "b2": False}


def _fleet_reads(nodes, names):
    return [ast.unparse(n) for node in nodes for n in ast.walk(node)
            if (isinstance(n, ast.Attribute) and n.attr in names)
            or (isinstance(n, ast.Constant) and n.value in names)
            or (isinstance(n, ast.Name) and n.id in names)]


_PIPELINE = ast.parse(textwrap.dedent(
    inspect.getsource(SEMCoordinator._run_battery_pipeline)))
_FLEET_POWER = {"battery_power_read", "battery_power_unavailable",
                "battery_power_all_unavailable"}
#: …and what stands for the fleet's level: its SOC flags, and the runtime's
#: ``available``, which carries the fleet SOC flag on every unit (#932).
_FLEET = _FLEET_POWER | {"battery_soc_unavailable", "battery_soc_known",
                         "available"}


def _tainted():
    """Local names assigned anywhere in the pipeline from a fleet flag, so a
    copy into a variable first is still a fleet read."""
    names: set = set()
    for _ in range(3):                  # a copy of a copy
        for n in ast.walk(_PIPELINE):
            if (isinstance(n, ast.Assign)
                    and _fleet_reads([n.value], _FLEET | names)):
                names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return names


def _many_battery_branch():
    branches = [n for n in ast.walk(_PIPELINE) if isinstance(n, ast.If)
                and ast.unparse(n.test) == "power.batteries"]
    assert len(branches) == 1, "the per-battery branch moved: update this guard"
    return branches[0]


def test_the_many_battery_branch_reads_no_fleet_power_flag():
    """Guard: inside ``if power.batteries:`` of the pipeline, each battery
    answers for itself. A fleet battery power flag read there is the #1167
    shape again."""
    assert _fleet_reads(_many_battery_branch().body,
                        _FLEET_POWER | _tainted()) == []


def test_each_unit_flag_is_its_own():
    """Guard: in the per-battery branch, what goes into the flags the check
    gets names no fleet flag, directly or through a copy."""
    flags = {"soc_seen", "power_seen"}
    stores = [n for stmt in _many_battery_branch().body for n in ast.walk(stmt)
              if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))
              and any(isinstance(t, ast.Subscript)
                      and ast.unparse(t.value) in flags
                      for t in (n.targets if isinstance(n, ast.Assign)
                                else [n.target]))]
    assert len(stores) == 2, "one store per flag: update this guard"
    assert _fleet_reads([n.value for n in stores], _FLEET | _tainted()) == []


def test_the_check_is_handed_the_unit_flags():
    """Guard: the end check gets those two maps by name and no fleet flag.
    #1167 was ``power_read=power.battery_power_read`` here, and the level
    was ``rt.available`` — the fleet's SOC flag on every unit."""
    calls = [n for n in ast.walk(_PIPELINE) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_finish_manual_battery_modes"]
    assert len(calls) == 1, "the end check moved: update this guard"
    call = calls[0]
    assert ast.unparse(call.args[1]) == "soc_seen"
    assert [ast.unparse(k.value) for k in call.keywords
            if k.arg == "power_read"] == ["power_seen"]
    args = list(call.args) + [k.value for k in call.keywords]
    assert _fleet_reads(args, _FLEET | _tainted()) == []


# ── 3. The check ends battery 1's charge while battery 2 is dark ───────────

@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(cmod, "_manual_stall_clock", c)
    return c


def _run(coordinator, clock, packs, minutes, *, power_read, step_s=30.0):
    items = [(bid, BatteryRuntime(battery_id=bid, last_known_soc=soc,
                                  last_known_w=w))
             for bid, (soc, w) in packs.items()]
    read = {bid: True for bid in packs}
    for _ in range(int(minutes * 60 / step_s)):
        clock.t += step_s
        SEMCoordinator._finish_manual_battery_modes(
            coordinator, items, read, len(items), power_read=power_read)


_ENOUGH_MIN = MANUAL_CHARGE_STALL_S / 60 + 1 + READS * 30 / 60


@pytest.mark.skipif(not _HAS_PHACC, reason="pytest-homeassistant-custom-component not installed")
class TestTheCheck:
    @pytest.mark.asyncio
    async def test_battery_1_ends_while_battery_2_is_dark(self, hass, clock):
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        selects = await _selects(hass, entry)
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (95.0, 0.0)},
             _ENOUGH_MIN, power_read={"b1": True, "b2": False})
        assert entry.options["battery_modes"] == ["auto", "force_charge"]
        assert _shows(selects["battery_b1_mode"]) == "auto"
        assert _shows(selects["battery_b2_mode"]) == "force_charge", (
            "b2's 0 W is no reading: its charge stays")

    @pytest.mark.asyncio
    async def test_a_missing_entry_is_no_reading(self, hass, clock):
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (95.0, 0.0)},
             _ENOUGH_MIN, power_read={"b1": True})
        assert entry.options["battery_modes"] == ["auto", "force_charge"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag", [True, 1, None, "yes"])
    async def test_one_flag_for_all_is_no_reading(self, hass, clock, flag):
        # Structural: a fleet bool cannot stand in for the map.
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (95.0, 0.0)},
             _ENOUGH_MIN, power_read=flag)
        assert entry.options["battery_modes"] == ["force_charge", "force_charge"]
        assert coordinator._manual_charge_stalls == {}

    @pytest.mark.asyncio
    async def test_a_shared_control_still_waits_for_the_dark_pack(
            self, hass, clock):
        # One select drives both: b2's job is not known to be done.
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["b1", "b2"])
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (95.0, 0.0)},
             _ENOUGH_MIN, power_read={"b1": True, "b2": False})
        assert entry.options["battery_mode"] == "force_charge"
        assert set(coordinator._manual_charge_stalls) == {"b1"}
