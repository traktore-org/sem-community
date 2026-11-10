"""#1297 — observer mode holds hot-water heating back.

The Legionella check runs every cycle straight from the coordinator. When
the tank was overdue it called the ``water_heater`` or ``climate`` service
itself, past ``send()``, the one place observer mode withholds a command.
(#1335) The check no longer switches at all: the load engine starts the run.
A rig that shares a real tank heated it every 72 hours while it believed
it was only watching. The switch path already went through ``send()``.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.devices.base import DeviceState
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)


def _tank(hass, entity_id, observer):
    dev = HotWaterController(
        hass=hass, entity_id=entity_id,
        temperature_entity_id="sensor.boiler_temp",
        solar_target_temp=55.0, rated_power=2000.0)
    dev.observer_mode = observer
    dev.withheld_commands = []
    hass.set(entity_id, "off")
    hass.set("sensor.boiler_temp", "45.0")
    return dev


def _engine(hass, dev):
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    sc = SurplusController(hass)
    sc.register_device(dev)
    return sc


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_id", ["water_heater.boiler", "climate.boiler"])
async def test_an_overdue_tank_is_not_heated_under_observer(entity_id):
    hass = _Hass()
    dev = _tank(hass, entity_id, observer=True)
    assert await dev.check_legionella_cycle() == "legionella_started"
    await _engine(hass, dev).update(-3000.0, observer=True)
    hass.services.async_call.assert_not_awaited()
    assert not dev.is_active


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_id, first_service", [
    ("water_heater.boiler", "water_heater.set_temperature"),
    ("climate.boiler", "climate.set_temperature"),
])
async def test_a_direct_start_under_observer_is_withheld_and_claims_nothing(
        entity_id, first_service):
    """(#1335) Past the engine too: the seam withholds, and the tank is not
    believed ACTIVE for a write that never went out."""
    hass = _Hass()
    dev = _tank(hass, entity_id, observer=True)
    assert await dev.activate(2000.0) == 0.0
    hass.services.async_call.assert_not_awaited()
    assert [c["service"] for c in dev.withheld_commands][0] == first_service
    assert not dev.is_active


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_id, domain", [
    ("water_heater.boiler", "water_heater"),
    ("climate.boiler", "climate"),
])
async def test_the_same_tank_is_heated_when_observer_is_off(entity_id, domain):
    hass = _Hass()
    dev = _tank(hass, entity_id, observer=False)
    assert await dev.check_legionella_cycle() == "legionella_started"
    hass.services.async_call.assert_not_awaited()   # (#1335) the check never writes
    await _engine(hass, dev).update(-3000.0)
    domains = {c.args[0] for c in hass.services.async_call.await_args_list}
    assert domains == {domain}
    assert dev.is_active and dev._sem_commanded
    assert dev.withheld_commands == []


@pytest.mark.asyncio
async def test_switching_the_tank_off_is_withheld_too():
    hass = _Hass()
    dev = _tank(hass, "climate.boiler", observer=True)
    dev._status.state = DeviceState.ACTIVE
    await dev.deactivate()
    assert dev.is_active, "a withheld stop moved nothing (#1335)"
    hass.services.async_call.assert_not_awaited()
    assert dev.withheld_commands[-1]["service"] == "climate.set_hvac_mode"
    assert dev.withheld_commands[-1]["data"]["hvac_mode"] == "off"
