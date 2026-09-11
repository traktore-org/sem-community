"""(#914) SEM's hot-water boost must not outlive a restart.

The reporter's second half: on 2.0.0 the heat-pump tank sat at SEM's 50 °C
boost setpoint through the night and reheated to it whenever it cooled —
"SEM has kept the state on with a setpoint of 50 during the night".

#656 decided that a reload (every options change) and an HA restart leave
loads exactly as they are, and rely on SEM re-adopting them when it comes
back. The direct hot-water and heat-pump controllers were registered with no
adopter at all, and the one the tank inherits reads a SWITCH truth
(``state == "on"``). A water_heater reports its operation mode as its state
("heat_pump", "eco"), a climate its hvac mode ("heat") — neither is ever
"on". So after a restart SEM believed the tank idle, the reconciler filed it
as external_on, and no stop path ever visited it: SEM's own boost stayed
armed on the tank and the appliance's thermostat reheated to it at any hour.

The adopter now reads the axis SEM actually commands:

* water_heater / climate tank — the SETPOINT. Adopted only while the entity
  still holds one of SEM's own boost setpoints (solar target, legionella
  target). A setpoint the user chose is not SEM's and is left alone — SEM
  releases what it commanded, nothing else (#847, #908).
* SG-Ready heat pump — the relay pair (or a service pump's state entity).
  Adopted only in BOOST / FORCE_ON, the states SEM commands on surplus.

An entity that is still unavailable when SEM registers (its integration
loads later on an HA restart) keeps the adoption PENDING; the first readable
observation decides it, once. SEM never re-adopts after that, so a setpoint
the user sets later is never claimed.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.solar_energy_management as sem
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    DeviceState,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)


def _state(value, **attrs):
    s = MagicMock()
    s.state = value
    s.attributes = attrs
    return s


def _hass(states: dict):
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states.get = lambda eid: states.get(eid)
    return h


def _tank(entity_id: str, state, **kw) -> HotWaterController:
    """A fresh controller (IDLE — a restart) facing the tank as SEM left it."""
    hass = _hass({entity_id: state} if state is not None else {})
    return HotWaterController(hass, entity_id=entity_id, solar_target_temp=50.0,
                              legionella_target_temp=65.0, min_temperature=40.0,
                              **kw)


def _service_calls(hass, domain=None, service=None):
    out = []
    for c in hass.services.async_call.call_args_list:
        d, s, data = c[0][0], c[0][1], c[0][2]
        if (domain is None or d == domain) and (service is None or s == service):
            out.append((d, s, data))
    return out


class TestTheTankSEMLeftBoostedIsReadopted:

    def test_water_heater_at_sems_solar_boost_is_adopted(self):
        hw = _tank("water_heater.dhw",
                   _state("heat_pump", temperature=50.0, current_temperature=48.2))
        assert hw.adopt_if_running() is True, (
            "a tank still at SEM's 50 °C boost after a restart was never "
            "re-adopted — the adopter read state == 'on', which a "
            "water_heater never reports")
        assert hw.is_active
        assert hw._sem_owned is True          # Solar mode: SEM's to stop
        assert hw._sem_commanded is False     # adopted, not commanded (#847)

    def test_water_heater_mid_legionella_cycle_is_adopted(self):
        hw = _tank("water_heater.dhw", _state("eco", temperature=65.0))
        assert hw.adopt_if_running() is True

    def test_a_device_that_rounds_the_written_setpoint_still_reads_as_sems(self):
        hw = _tank("water_heater.dhw", _state("heat_pump", temperature=50.5))
        assert hw.adopt_if_running() is True

    def test_state_unknown_is_a_tank_without_operation_modes_not_an_off(self):
        """HA writes ``unknown`` for a water_heater whose current_operation is
        None — permanently, for tanks without modes. The setpoint still
        answers."""
        hw = _tank("water_heater.dhw", _state("unknown", temperature=50.0))
        assert hw.adopt_if_running() is True

    def test_climate_tank_in_sems_heat_mode_at_the_boost_is_adopted(self):
        hw = _tank("climate.dhw", _state("heat", temperature=50.0))
        assert hw.adopt_if_running() is True

    def test_switch_tank_keeps_the_switch_truth(self):
        assert _tank("switch.boiler", _state("on")).adopt_if_running() is True
        assert _tank("switch.boiler", _state("off")).adopt_if_running() is False


class TestWhatIsNotSEMsIsLeftAlone:

    @pytest.mark.parametrize("setpoint", [55.0, 45.0, 51.0, 40.0])
    def test_a_setpoint_sem_does_not_write_is_not_claimed(self, setpoint):
        """55 (a user who runs the tank hotter than SEM's target and whom SEM
        therefore never boosts), 45, 51, and the release floor itself."""
        hw = _tank("water_heater.dhw", _state("heat_pump", temperature=setpoint))
        assert hw.adopt_if_running() is False
        assert not hw.is_active

    def test_a_tank_released_by_turn_off_is_not_adopted(self):
        hw = _tank("water_heater.dhw", _state("off", temperature=50.0))
        assert hw.adopt_if_running() is False

    def test_a_climate_tank_in_a_mode_sem_does_not_write_is_not_adopted(self):
        """Same line ClimateDevice.adopt_if_running holds: SEM writes
        hvac_mode 'heat'; a unit the user runs in 'auto' is theirs."""
        hw = _tank("climate.dhw", _state("auto", temperature=50.0))
        assert hw.adopt_if_running() is False

    @pytest.mark.parametrize("state", [
        None,
        _state("unavailable", temperature=50.0),
        _state("heat_pump"),
        _state("heat_pump", temperature="n/a"),
    ])
    def test_an_unreadable_tank_is_not_claimed(self, state):
        hw = _tank("water_heater.dhw", state)
        assert hw.adopt_if_running() is False
        assert not hw.is_active

    def test_mode_off_adopts_the_belief_but_not_the_claim(self):
        """(#779) the gate lives in _adopt_ownership — the books see the
        running tank, SEM does not claim it."""
        hw = _tank("water_heater.dhw", _state("heat_pump", temperature=50.0))
        hw.control_mode = DeviceControlMode.OFF
        assert hw.adopt_if_running() is True
        assert hw._sem_owned is False


class TestAnEntityThatLoadsAfterSEM:
    """On an HA restart the tank's own integration may still be loading when
    SEM registers. The adoption waits for the first readable observation."""

    def test_the_first_readable_cycle_adopts(self):
        states = {"water_heater.dhw": _state("unavailable")}
        hw = HotWaterController(_hass(states), entity_id="water_heater.dhw")
        assert hw.adopt_if_running() is False
        states["water_heater.dhw"] = _state("heat_pump", temperature=50.0)
        assert hw.sync_belief_to_observation() is True
        assert hw.is_active and hw._sem_owned

    def test_once_decided_a_later_setpoint_is_never_claimed(self):
        states = {"water_heater.dhw": _state("heat_pump", temperature=45.0)}
        hw = HotWaterController(_hass(states), entity_id="water_heater.dhw")
        assert hw.adopt_if_running() is False       # readable: decided, not SEM's
        states["water_heater.dhw"] = _state("heat_pump", temperature=50.0)
        assert hw.sync_belief_to_observation() is False, (
            "a setpoint the user raised AFTER SEM came back is theirs")
        assert not hw.is_active

    def test_a_tank_sem_boosts_itself_first_closes_the_window(self):
        states = {"water_heater.dhw": _state("unavailable")}
        hw = HotWaterController(_hass(states), entity_id="water_heater.dhw")
        hw.adopt_if_running()
        hw._status.state = DeviceState.ACTIVE      # SEM started it itself
        states["water_heater.dhw"] = _state("heat_pump", temperature=50.0)
        assert hw.sync_belief_to_observation() is False
        assert hw._boot_adoption_pending is False


def _hp(states: dict, **kw) -> HeatPumpController:
    return HeatPumpController(_hass(states), relay1_entity_id="switch.sg1",
                              relay2_entity_id="switch.sg2", **kw)


class TestTheSGReadyBoostSEMLeftOnIsReadopted:

    @pytest.mark.parametrize("r1,r2,invert,expected", [
        ("off", "on", False, SGReadyState.BOOST),
        ("on", "on", False, SGReadyState.FORCE_ON),
        ("off", "off", False, None),        # NORMAL — nothing of SEM's
        ("on", "off", False, None),         # BLOCKED — SEM never commands it
        ("on", "off", True, SGReadyState.BOOST),      # NC wiring (#523)
        ("off", "off", True, SGReadyState.FORCE_ON),
        ("on", "on", True, None),
    ])
    def test_the_relay_pair_decides(self, r1, r2, invert, expected):
        hp = _hp({"switch.sg1": _state(r1), "switch.sg2": _state(r2)},
                 invert_sg_ready=invert)
        assert hp.adopt_if_running() is (expected is not None)
        if expected is not None:
            assert hp.is_active and hp._sem_owned
            assert hp.sg_ready_state == expected

    def test_an_unreadable_relay_is_not_claimed(self):
        hp = _hp({"switch.sg1": _state("off"), "switch.sg2": _state("unavailable")})
        assert hp.adopt_if_running() is False
        assert hp._boot_adoption_pending is True    # decided on a later cycle

    def test_the_relays_loading_late_are_adopted_on_the_first_readable_cycle(self):
        states = {"switch.sg1": _state("unavailable"), "switch.sg2": _state("unavailable")}
        hp = _hp(states)
        assert hp.adopt_if_running() is False
        states["switch.sg1"] = _state("off")
        states["switch.sg2"] = _state("on")
        assert hp.sync_belief_to_observation() is True
        assert hp.sg_ready_state == SGReadyState.BOOST

    @pytest.mark.parametrize("reported,adopted", [
        ("3", True), ("boost", True), ("4", True), ("2", False), ("normal", False),
    ])
    def test_a_service_pump_is_read_through_its_state_entity(self, reported, adopted):
        hp = HeatPumpController(
            _hass({"sensor.sg_state": _state(reported)}),
            sg_ready_service="ems.set_sg_ready",
            sg_ready_state_entity="sensor.sg_state")
        assert hp.adopt_if_running() is adopted

    def test_a_service_pump_without_a_state_entity_is_unobservable(self):
        hp = HeatPumpController(_hass({}), sg_ready_service="ems.set_sg_ready")
        assert hp.adopt_if_running() is False

    def test_a_climate_only_pump_is_not_adopted(self):
        """Named residual: its boost is a thermostat setpoint the user also
        owns — normal + offset cannot be told apart from their own choice."""
        hp = HeatPumpController(_hass({"climate.hp": _state("heat", temperature=23.0)}),
                                climate_entity_id="climate.hp")
        assert hp.adopt_if_running() is False


@pytest.mark.asyncio
class TestTheNightReleasesWhatWasAdopted:
    """End to end: the restart the reporter's tank went through, then a
    night cycle with no surplus. Before #914 the second half never happened."""

    async def test_the_boost_setpoint_is_released_at_night(self):
        hw = _tank("water_heater.dhw", _state("heat_pump", temperature=50.0))
        assert hw.adopt_if_running() is True
        # The restart was longer ago than the anti-cycle run window.
        hw._last_activated = datetime.now() - timedelta(seconds=hw.min_on_seconds + 60)
        sc = SurplusController(hw.hass)
        sc.register_device(hw)
        await sc.update(0.0, is_night=True)
        released = (_service_calls(hw.hass, "water_heater", "turn_off")
                    + _service_calls(hw.hass, "water_heater", "set_temperature"))
        assert released, (
            "no release reached the tank — SEM's 50 °C boost stays armed "
            "all night, which is what the reporter saw")
        assert not hw.is_active

    async def test_a_tank_sem_did_not_boost_is_not_touched_at_night(self):
        hw = _tank("water_heater.dhw", _state("heat_pump", temperature=55.0))
        hw.adopt_if_running()
        sc = SurplusController(hw.hass)
        sc.register_device(hw)
        await sc.update(0.0, is_night=True)
        assert _service_calls(hw.hass) == []

    async def test_the_sg_ready_boost_returns_to_normal_at_night(self):
        hp = _hp({"switch.sg1": _state("off"), "switch.sg2": _state("on")})
        assert hp.adopt_if_running() is True
        hp._last_activated = datetime.now() - timedelta(seconds=hp.min_on_seconds + 60)
        sc = SurplusController(hp.hass)
        sc.register_device(hp)
        await sc.update(0.0, is_night=True)
        relays = {data["entity_id"]: s for _d, s, data in
                  _service_calls(hp.hass, "homeassistant")}
        assert relays == {"switch.sg1": "turn_off", "switch.sg2": "turn_off"}, (
            "SG-Ready NORMAL is (off, off) — the pump stayed in BOOST")
        assert not hp.is_active


class TestEveryDirectRegistrationAdopts:
    """The structural half. ``async_setup_entry`` registers the direct
    controllers itself (hot water, every heat pump); #656 relies on each of
    them being re-adopted when SEM comes back. A controller registered there
    without an adopter is this bug again — the next one fails here."""

    # The EV has its own restart path: the charger reconciler re-reads the
    # session every cycle (#855).
    _OWN_RECONCILER = {"ev_device"}

    @staticmethod
    def _setup_body_calls():
        tree = ast.parse(Path(sem.__file__).read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "async_setup_entry")
        found = []

        def visit(node):
            for child in ast.iter_child_nodes(node):
                # nested defs are service handlers — a live call, not a boot
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.Lambda)):
                    continue
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.args and isinstance(child.args[0], ast.Name)
                        and child.func.attr == "register_device"):
                    found.append(("register", child.args[0].id, child.lineno))
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "adopt_if_running"
                        and isinstance(child.func.value, ast.Name)):
                    found.append(("adopt", child.func.value.id, child.lineno))
                visit(child)
        visit(fn)
        return found

    def test_each_direct_controller_is_adopted_before_it_is_registered(self):
        calls = self._setup_body_calls()
        registered = [(name, line) for kind, name, line in calls
                      if kind == "register" and name not in self._OWN_RECONCILER]
        assert {"hw_device", "hp_extra"} <= {n for n, _ in registered}, (
            "the guard no longer sees the direct registrations — it would "
            "pass vacuously")
        missing = [
            f"{name} (line {line})" for name, line in registered
            if not any(kind == "adopt" and n == name and l < line
                       for kind, n, l in calls)
        ]
        assert not missing, (
            "registered at setup with no restart adoption — a reload or HA "
            "restart strands whatever SEM had it doing (#914, #656): "
            + ", ".join(missing))
