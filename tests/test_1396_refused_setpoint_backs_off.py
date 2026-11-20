"""(#1396) A setpoint the unit refuses is not sent again every cycle.

A cloud heat pump's hot-water tank refused SEM's target with a validation
error every 10 s (19.11, 15:50–16:03): about 8,600 calls a day against a
per-account limit, and the same account runs the heat pump. The target was
above the tank's own range (stored maximum 74 °C), and a refusal was retried
every cycle.

Now the target is capped at the unit's ``min_temp``/``max_temp``, and after a
refusal the next try waits 5, 15, then 60 minutes.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices import setpoint_memo
from custom_components.solar_energy_management.devices.base import SetpointDevice
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)

TANK = "water_heater.tank"
UNIT = "climate.unit"


class _Hass:
    """A unit with its own range; ``refuse`` makes every set_temperature raise."""

    def __init__(self):
        self._states: dict = {}
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
        self.states = MagicMock()
        self.states.get = self._states.get
        self.services = MagicMock()
        self.services.async_call = AsyncMock(side_effect=self._call)
        self.refuse = False
        self.landed: list = []

    def unit(self, eid, state="heat", **attrs):
        self._states[eid] = SimpleNamespace(entity_id=eid, state=state, attributes=attrs)

    async def _call(self, domain, service, data=None, **_kw):
        eid = data["entity_id"]
        if service == "set_temperature":
            if self.refuse:
                raise RuntimeError("Command failed with status code 400: VALIDATION_ERROR")
            self._states[eid].attributes["temperature"] = data["temperature"]
            self.landed.append(data["temperature"])

    def writes(self):
        return [c.args[2]["temperature"] for c in self.services.async_call.await_args_list
                if c.args[1] == "set_temperature"]


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(setpoint_memo, "_mono", lambda: t["now"], raising=False)
    return t


def _tank(hass, target=55.0):
    return HotWaterController(hass=hass, entity_id=TANK, rated_power=2000.0,
                              solar_target_temp=target)


async def _cycles(dev, clock, minutes, every_s=10):
    for _ in range(int(minutes * 60 // every_s)):
        await dev._activate_water_heater()
        clock["now"] += every_s


async def test_a_refused_target_is_tried_a_few_times_an_hour_not_every_cycle(clock, caplog):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, min_temp=10, max_temp=60)
    hass.refuse = True
    dev = _tank(hass)
    with caplog.at_level(logging.WARNING):
        await _cycles(dev, clock, minutes=60)
    # at 0, 5 and 20 min — not 360 times
    assert len(hass.writes()) == 3
    assert dev._last_activation_path == "water_heater_refused"
    assert not dev.is_active
    refused = [r for r in caplog.records if "refused the setpoint" in r.getMessage()]
    assert len(refused) == 3, "said once per wait, not every cycle"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_the_target_is_capped_at_the_units_own_range(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, min_temp=10, max_temp=60)
    dev = _tank(hass, target=74.0)
    await dev._activate_water_heater()
    assert hass.writes() == [60]


async def test_a_unit_without_a_range_gets_the_target_as_before(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0)
    dev = _tank(hass, target=58.0)
    await dev._activate_water_heater()
    assert hass.writes() == [58.0]


async def test_a_write_that_lands_ends_the_wait(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, max_temp=60)
    hass.refuse = True
    dev = _tank(hass)
    await dev._activate_water_heater()                 # refused
    clock["now"] += 5 * 60 + 1
    hass.refuse = False
    await dev._activate_water_heater()                 # lands
    assert dev.is_active
    hass.refuse = True
    await dev._activate_water_heater()                 # refused again: first wait
    clock["now"] += 5 * 60 + 1
    await dev._activate_water_heater()
    assert len(hass.writes()) == 4, "the waits started again from 5 min"


async def test_a_new_target_waits_too(clock):
    """(review) The cap keeps targets in range, so a refusal is the unit's
    own state: another value does not end the wait."""
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, max_temp=60)
    hass.refuse = True
    dev = _tank(hass, target=55.0)
    await dev._activate_water_heater()
    dev.solar_target_temp = 50.0                       # another target
    await dev._activate_water_heater()
    assert hass.writes() == [55.0]


async def test_a_refused_boost_is_not_counted_as_boosted(clock):
    hass = _Hass()
    hass.unit(UNIT, temperature=20.0, min_temp=10, max_temp=30)
    hass.refuse = True
    dev = SetpointDevice(hass, "hp", "Pump", 2000.0, climate_entity_id=UNIT,
                         normal_setpoint=20.0, boost_offset=2.0)
    assert await dev.activate(3000) == 0.0
    assert dev._boosted is False
    for _ in range(30):                                # 5 minutes of cycles
        await dev.activate(3000)
        clock["now"] += 10
    assert len(hass.writes()) == 1


# ── review: one wait per unit for SEM's target; every write capped ──────

async def test_alternating_targets_wait_as_one_unit(clock):
    """Solar and grid targets taking turns must not restart the wait."""
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, max_temp=60)
    hass.refuse = True
    dev = _tank(hass, target=55.0)
    for i in range(360):                               # an hour at 10 s
        dev.solar_target_temp = 55.0 if i % 2 else 50.0
        await dev._activate_water_heater()
        clock["now"] += 10
    assert len(hass.writes()) == 3


async def test_a_step_down_is_not_delayed_by_a_refused_target(clock):
    """(review 2) Only SEM's own target waits: a price step-down goes at once."""
    from custom_components.solar_energy_management.devices.heat_pump_controller import (
        HeatPumpController, STEP_DOWN_SETPOINT)
    hass = _Hass()
    hass.unit(UNIT, temperature=21.0, min_temp=15, max_temp=30)
    dev = HeatPumpController(hass=hass, climate_entity_id=UNIT, rated_power=2500.0)
    dev.step_down_action = STEP_DOWN_SETPOINT
    hass.refuse = True
    await dev.sp_write_target("climate", UNIT, 23.0)  # SEM's target refused
    assert dev.sp_refused_for(UNIT)
    hass.refuse = False
    clock["now"] += 30                                 # well inside the wait
    assert await dev.step_down() is True
    assert hass.landed[-1] < 21.0


async def test_every_write_is_capped(clock):
    """(review 2) Restores and minimums are capped too, through one helper."""
    hass = _Hass()
    hass.unit(UNIT, temperature=20.0, min_temp=10, max_temp=25)
    dev = SetpointDevice(hass, "hp", "Pump", 2000.0, climate_entity_id=UNIT,
                         normal_setpoint=28.0, boost_offset=2.0)
    dev._boosted = True
    await dev.deactivate()                            # no memo: the normal setpoint
    assert hass.landed[-1] == 25


async def test_a_refused_tank_minimum_keeps_the_memo_and_tries_again(clock):
    """(review 1) A tank with no off: the minimum refused must not drop the
    user's setpoint nor read idle."""
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, min_temp=30, max_temp=60)
    real = hass._call

    async def no_off(domain, service, data=None, **kw):
        if service == "turn_off":
            raise RuntimeError("no off")
        return await real(domain, service, data, **kw)
    hass.services.async_call.side_effect = no_off
    dev = _tank(hass)
    await dev._activate_water_heater()                 # 55 out, 48 remembered
    assert dev.is_active and dev._sp_memo
    hass.refuse = True
    await dev._deactivate_water_heater()
    assert dev._sp_memo, "the user's setpoint is kept"
    assert dev.is_active, "not counted idle"
    assert dev._last_deactivation_path == "water_heater_minimum_refused"
    hass.refuse = False
    await dev._deactivate_water_heater()               # the next cycle
    assert hass.landed[-1] == dev.min_temperature
    assert not dev._sp_memo and not dev.is_active


def _legionella(hass, target=65.0):
    return HotWaterController(hass=hass, entity_id=TANK, rated_power=2000.0,
                              solar_target_temp=55.0, legionella_target_temp=target)


async def test_legionella_ends_at_the_tanks_maximum(clock, caplog):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=60.0, max_temp=60)
    dev = _legionella(hass)
    assert dev.legionella_reach_c == 60.0
    assert dev.legionella_above_unit_max == 60.0
    dev._legionella_cycle_active = True
    assert dev.is_temperature_safe() is False, "60 °C is all this tank takes"
    with caplog.at_level(logging.WARNING):
        await dev._activate_water_heater()
        await dev._activate_water_heater()
    assert hass.writes()[-1] == 60
    assert len([r for r in caplog.records if "above what" in r.getMessage()]) == 1


def test_legionella_without_a_max_is_unchanged():
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=59.5)
    dev = _legionella(hass, target=60.0)
    assert dev.legionella_reach_c == 60.0
    assert dev.legionella_above_unit_max is None
    dev._legionella_cycle_active = True
    assert dev.is_temperature_safe() is True, "59.5 is below 60: heat on, as before"


def test_a_tank_gone_unavailable_mid_run_keeps_its_reach():
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=55.0, max_temp=58)
    dev = _legionella(hass)
    dev._legionella_cycle_active = True
    assert dev.legionella_reach_c == 58.0
    hass.unit(TANK, state="unavailable")               # attributes gone
    assert dev.legionella_reach_c == 58.0
    dev._legionella_cycle_active = False
    assert dev.legionella_reach_c == 65.0, "outside a run: nothing assumed"


def test_a_max_above_the_target_changes_nothing():
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=55.0, max_temp=75)
    dev = _legionella(hass)
    assert dev.legionella_reach_c == 65.0 and dev.legionella_above_unit_max is None


def test_the_repair_is_raised_and_cleared(monkeypatch):
    from custom_components.solar_energy_management.coordinator import repair_issues as ri
    made, gone = [], []
    monkeypatch.setattr(ri.ir, "async_create_issue",
                        lambda hass, **kw: made.append((kw["issue_id"], kw["translation_key"],
                                                        kw["translation_placeholders"])))
    monkeypatch.setattr(ri.ir, "async_delete_issue",
                        lambda hass, domain, issue_id: gone.append(issue_id))
    ri.raise_legionella_above_unit_max(object(), "hot_water", name="Tank", max_c=60, target_c=65)
    ri.clear_legionella_above_unit_max(object(), "hot_water")
    assert made == [("legionella_above_unit_max_hot_water", "legionella_above_unit_max",
                     {"name": "Tank", "max": "60", "target": "65"})]
    assert gone == ["legionella_above_unit_max_hot_water"]


def test_the_coordinator_raises_and_clears_it():
    """The coordinator raises and clears the Repair (AST, not spelling)."""
    from custom_components.solar_energy_management.tests.ast_contracts import call_sites
    for fn in ("raise_legionella_above_unit_max", "clear_legionella_above_unit_max"):
        files = {str(p).rsplit("/", 1)[-1] for p, *_ in call_sites(fn)}
        assert "coordinator.py" in files, fn


# ── final review: one wait per purpose; direct writes are never raised ──────

async def test_a_refused_everyday_target_does_not_hold_back_legionella(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, max_temp=70)
    dev = _legionella(hass, target=65.0)
    hass.refuse = True
    await dev._activate_water_heater()                 # everyday 55 refused
    assert dev.sp_refused_for(TANK, "everyday")
    hass.refuse = False
    clock["now"] += 30                                 # well inside that wait
    dev._legionella_cycle_active = True
    await dev._activate_water_heater()                 # Legionella goes at once
    assert hass.landed[-1] == 65.0


async def test_a_refused_target_does_not_hold_back_a_boost(clock):
    hass = _Hass()
    hass.unit(UNIT, temperature=20.0, min_temp=10, max_temp=30)
    dev = SetpointDevice(hass, "hp", "Pump", 2000.0, climate_entity_id=UNIT,
                         normal_setpoint=20.0, boost_offset=2.0)
    hass.refuse = True
    await dev.sp_write_target("climate", UNIT, 21.0)   # an everyday target refused
    hass.refuse = False
    clock["now"] += 30
    assert await dev.activate(3000) > 0
    assert hass.landed[-1] == 22.0


async def test_a_refused_legionella_starts_only_its_own_wait(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, max_temp=70)
    dev = _legionella(hass, target=65.0)
    dev._legionella_cycle_active = True
    hass.refuse = True
    await dev._activate_water_heater()
    assert dev.sp_refused_for(TANK, "legionella")
    assert not dev.sp_refused_for(TANK, "everyday")


async def test_a_step_down_below_the_units_minimum_is_never_raised(clock):
    from custom_components.solar_energy_management.devices.heat_pump_controller import (
        HeatPumpController, STEP_DOWN_SETPOINT)
    hass = _Hass()
    hass.unit(UNIT, temperature=22.0, min_temp=25, max_temp=30)
    dev = HeatPumpController(hass=hass, climate_entity_id=UNIT, rated_power=2500.0,
                             boost_offset=2.0)
    dev.step_down_action = STEP_DOWN_SETPOINT
    dev.min_setpoint = 15.0
    await dev.step_down()
    assert 25.0 not in hass.landed
    assert all(v < 22.0 for v in hass.landed), hass.landed


async def test_sems_own_raise_target_is_lifted_to_the_minimum(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, min_temp=50, max_temp=70)
    dev = _tank(hass, target=45.0)
    await dev._activate_water_heater()
    assert hass.landed[-1] == 50
