"""(#1409) A heat pump whose climate entity refuses SEM's setpoint is not "on".

A NIBE SMO S40, set up with only its climate entity (no SG-Ready contacts).
The NIBE climate entity reads "auto" while its "use room sensor" setting is
off, and in "auto" it refuses ``climate.set_temperature`` with only
``temperature``. ``SetpointDevice.activate`` saw the refusal (#1396) and
returned 0 W, but ``HeatPumpController.activate`` dropped that answer: it
marked the pump ACTIVE, booked its rated power and published SG-Ready BOOST.
The card showed the pump running while it did nothing.

Not changed on purpose: SEM does not send the target "in a form NIBE takes"
(``hvac_mode: heat`` or a low/high pair). In "auto" the room sensor is off,
so NIBE's room setpoint has no effect: such a write would land, and SEM would
again show the pump running while it does nothing.

``_Hass`` below copies the NIBE climate entity's ``async_set_temperature``
rule (homeassistant/components/nibe_heatpump/climate.py).
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    LoadIntent,
    reconcile_load,
)
from custom_components.solar_energy_management.devices import setpoint_memo
from custom_components.solar_energy_management.devices.base import (
    ClimateDevice,
    DeviceState,
    ScheduleDevice,
    SetpointDevice,
    SwitchDevice,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)

NIBE = "climate.smo_s40_climate_system_s1"
ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Hass:
    """HA with a NIBE climate entity and, if asked, two SG-Ready switches."""

    def __init__(self):
        self._states: dict = {}
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
        self.states = MagicMock()
        self.states.get = self._states.get
        self.services = MagicMock()
        self.services.async_call = AsyncMock(side_effect=self._call)

    def nibe(self, mode: str, setpoint: float = 20.0):
        """The entity as NIBE publishes it: no target at all in "auto"."""
        attrs = {"current_temperature": 20.0, "min_temp": 5.0, "max_temp": 35.0,
                 "target_temp_step": 0.5,
                 "hvac_modes": ["auto", "heat", "heat_cool"]}
        if mode == "heat":
            attrs["temperature"] = setpoint
        self._states[NIBE] = SimpleNamespace(entity_id=NIBE, state=mode,
                                             attributes=attrs)

    def switch(self, eid: str, state: str = "off"):
        self._states[eid] = SimpleNamespace(entity_id=eid, state=state, attributes={})

    async def _call(self, domain, service, data=None, **_kw):
        eid = data["entity_id"]
        st = self._states[eid]
        if domain == "climate" and service == "set_temperature":
            mode = data.get("hvac_mode", st.state)
            if "temperature" in data and mode not in ("heat", "cool"):
                raise ServiceValidationError(
                    "'set_temperature' requires 'hvac_mode' when passing"
                    " 'temperature' and 'hvac_mode' is not already set to"
                    " 'heat' or 'cool'")
            if "temperature" in data and st.state == "heat":
                st.attributes["temperature"] = data["temperature"]
        elif domain == "homeassistant":
            st.state = "on" if service == "turn_on" else "off"

    def setpoint_writes(self):
        return [c.args[2] for c in self.services.async_call.await_args_list
                if c.args[:2] == ("climate", "set_temperature")]


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(setpoint_memo, "_mono", lambda: t["now"], raising=False)
    return t


def _pump(hass, **kw):
    return HeatPumpController(hass=hass, climate_entity_id=NIBE,
                              rated_power=2000.0, normal_setpoint=21.0,
                              boost_offset=2.0, max_setpoint=30.0, **kw)


def _boost_intent():
    return LoadIntent(on=True, power_w=3000.0, source="solar", reason="surplus")


class TestTheReport:
    async def test_nibe_in_auto_refuses_and_sem_claims_nothing(self, clock):
        hass = _Hass()
        hass.nibe("auto")
        hp = _pump(hass)

        got = await hp.activate(3000.0)

        assert got == 0.0
        assert len(hass.setpoint_writes()) == 1          # it was tried
        assert not hp.is_active
        assert hp._status.state == DeviceState.ERROR
        assert hp._status.current_consumption_w == 0.0
        assert hp._status.allocated_power_w == 0.0
        assert hp.sg_ready_state == SGReadyState.NORMAL   # not BOOST
        assert hp.energy_split_label == "sg2"             # not booked as SEM's
        assert hp.hp_status.is_solar_boosted is False
        assert hp.to_dict()["activation_path"] == "boost+climate+refused"

    async def test_force_on_refused_keeps_normal_too(self, clock):
        hass = _Hass()
        hass.nibe("auto")
        hp = _pump(hass, force_on_threshold=5000.0)
        assert await hp.activate(8000.0) == 0.0
        assert hp.sg_ready_state == SGReadyState.NORMAL
        assert hp.to_dict()["activation_path"] == "force_on+climate+refused"

    async def test_the_real_load_walk_does_not_own_it(self, clock):
        """``reconcile_load`` → ``_activate_owned``: 0 W means not started,
        so SEM does not take the pump as its own."""
        hass = _Hass()
        hass.nibe("auto")
        hp = _pump(hass)
        consumed = await reconcile_load(hp, _boost_intent())
        assert consumed == 0.0
        assert not hp.is_active
        assert hp._sem_owned is False

    async def test_next_cycles_wait_and_claim_nothing(self, clock):
        hass = _Hass()
        hass.nibe("auto")
        hp = _pump(hass)
        await hp.activate(3000.0)
        for _ in range(6):                 # one minute of 10 s cycles
            clock["now"] += 10
            assert await hp.activate(3000.0) == 0.0
        assert len(hass.setpoint_writes()) == 1          # the #1396 wait holds
        assert not hp.is_active
        assert hp.sg_ready_state == SGReadyState.NORMAL

    async def test_once_the_pump_takes_a_target_the_boost_lands(self, clock):
        """The user turns the room sensor on (the entity reads "heat"): the
        next try after the wait lands and the pump is on, with no restart."""
        hass = _Hass()
        hass.nibe("auto")
        hp = _pump(hass)
        assert await hp.activate(3000.0) == 0.0
        hass.nibe("heat", setpoint=20.0)
        clock["now"] += 5 * 60 + 1
        assert await hp.activate(3000.0) == 2000.0
        assert hp.is_active
        assert hp.sg_ready_state == SGReadyState.BOOST
        assert hass._states[NIBE].attributes["temperature"] == 23.0


class TestTwins:
    async def test_nibe_in_heat_boosts_as_before(self, clock):
        hass = _Hass()
        hass.nibe("heat", setpoint=20.0)
        hp = _pump(hass)
        assert await hp.activate(3000.0) == 2000.0
        assert hp.is_active
        assert hp.sg_ready_state == SGReadyState.BOOST
        assert hp.to_dict()["activation_path"] == "boost+climate"
        assert hass.setpoint_writes() == [{"entity_id": NIBE, "temperature": 23.0}]

    async def test_with_contacts_the_pump_boosts_by_them(self, clock):
        """The contacts moved: the pump boosts whatever the setpoint did."""
        hass = _Hass()
        hass.nibe("auto")
        hass.switch("switch.sg1")
        hass.switch("switch.sg2")
        hp = _pump(hass, relay1_entity_id="switch.sg1", relay2_entity_id="switch.sg2")
        assert await hp.activate(3000.0) == 2000.0
        assert hp.is_active
        assert hp.sg_ready_state == SGReadyState.BOOST
        assert hass._states["switch.sg2"].state == "on"

    async def test_a_withheld_setpoint_claims_nothing(self, clock):
        hass = _Hass()
        hass.nibe("heat", setpoint=20.0)
        hp = _pump(hass)
        hp.observer_mode = True
        assert await hp.activate(3000.0) == 0.0
        assert not hp.is_active
        assert hp._status.state != DeviceState.ERROR
        assert hp.sg_ready_state == SGReadyState.NORMAL
        assert hp.to_dict()["activation_path"] == "boost+climate+withheld"
        assert hass.setpoint_writes() == []

    async def test_setpoint_device_alone(self, clock):
        hass = _Hass()
        hass.nibe("auto")
        dev = SetpointDevice(hass=hass, device_id="sp", name="sp",
                             rated_power=1500.0, climate_entity_id=NIBE)
        assert await dev.activate(2000.0) == 0.0
        assert not dev.is_active and dev._boosted is False
        hass.nibe("heat")
        dev2 = SetpointDevice(hass=hass, device_id="sp2", name="sp2",
                              rated_power=1500.0, climate_entity_id=NIBE)
        dev2.observer_mode = True
        assert await dev2.activate(2000.0) == 0.0
        assert not dev2.is_active and dev2._boosted is False


class TestSiblingsWithheld:
    """The same rule for every load: a withheld write claims nothing."""

    async def test_switch(self):
        hass = _Hass()
        hass.switch("switch.heater")
        dev = SwitchDevice(hass=hass, device_id="h", name="h", rated_power=1000.0,
                           entity_id="switch.heater")
        dev.observer_mode = True
        assert await dev.activate(1500.0) == 0.0
        assert not dev.is_active
        dev.observer_mode = False
        assert await dev.activate(1500.0) == 1000.0
        assert dev.is_active

    async def test_climate(self):
        hass = _Hass()
        hass.nibe("heat")
        dev = ClimateDevice(hass=hass, device_id="ac", name="ac", rated_power=900.0,
                            entity_id=NIBE, hvac_mode="heat", target_temperature=22.0)
        dev.observer_mode = True
        assert await dev.activate(1500.0) == 0.0
        assert not dev.is_active
        assert dev._sp_pending is None

    async def test_schedule(self):
        hass = _Hass()
        hass.switch("switch.dishwasher")
        dev = ScheduleDevice(hass=hass, device_id="dw", name="dw", rated_power=1800.0,
                             entity_id="switch.dishwasher")
        dev.observer_mode = True
        assert await dev.activate(2000.0) == 0.0
        assert not dev.is_active and dev._started is False


# ── guard: an activate never drops the answer of the write it made ─────────

def _dropped_answers(tree: ast.AST) -> list:
    """Bare ``await ….send(…)`` / ``await super().activate(…)`` statements
    inside any ``activate`` method: the answer (sent? withheld? watts?) is
    thrown away, and the device is then claimed on regardless."""
    found = []
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.AsyncFunctionDef) and fn.name == "activate"):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)):
                continue
            call = node.value.value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            if call.func.attr in ("send", "activate"):
                found.append(f"{fn.name}:{node.lineno}:{call.func.attr}")
    return found


def test_no_activate_drops_the_answer_of_its_write():
    bad = {}
    for path in sorted((ROOT / "devices").glob("*.py")):
        hits = _dropped_answers(ast.parse(path.read_text()))
        if hits:
            bad[path.name] = hits
    assert not bad, f"activate drops a write's answer: {bad}"


def test_the_guard_catches_a_dropped_answer():
    probe = ast.parse(
        "class X:\n"
        "    async def activate(self, w):\n"
        "        await super().activate(w)\n"
        "        await self.send('a', 'b', {})\n"
        "        return 1\n")
    assert len(_dropped_answers(probe)) == 2
