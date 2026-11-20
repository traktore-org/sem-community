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

    def unit(self, eid, state="heat", **attrs):
        self._states[eid] = SimpleNamespace(entity_id=eid, state=state, attributes=attrs)

    async def _call(self, domain, service, data=None, **_kw):
        eid = data["entity_id"]
        if service == "set_temperature":
            if self.refuse:
                raise RuntimeError("Command failed with status code 400: VALIDATION_ERROR")
            self._states[eid].attributes["temperature"] = data["temperature"]

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


async def test_a_new_target_is_tried_at_once(clock):
    hass = _Hass()
    hass.unit(TANK, temperature=48.0, current_temperature=40.0, max_temp=60)
    hass.refuse = True
    dev = _tank(hass, target=55.0)
    await dev._activate_water_heater()
    dev.solar_target_temp = 50.0                       # another target
    await dev._activate_water_heater()
    assert hass.writes() == [55.0, 50.0]


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
