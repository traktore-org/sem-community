"""#1121 — a Legionella run is not stopped by the first cloud.

The run used to start with a plain ``activate()`` (#1335: the load engine
starts it now). The deficit pass in
``SurplusController.update`` frees power by switching off the lowest
surplus loads; it spared forced night runs and Tier-2 battery runs, not a
Legionella run. The tank went off one cycle later and nothing switched it
back on, while the card kept saying "Legionella heating".

Pinned here through the real controllers: a due run keeps heating on a
deficit (both the acting path and the observer path), a normal solar run
is still stopped by the same deficit, and a peak shed still wins.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)


def _boiler(hass):
    return HotWaterController(
        hass=hass, entity_id="switch.boiler",
        temperature_entity_id="sensor.boiler_temp",
        solar_target_temp=55.0, rated_power=2000.0)


def _past_min_run(dev):
    dev._last_activated = datetime.now() - timedelta(hours=1)
    dev._status.last_activated = dev._last_activated


async def _legionella_running(hass):
    dev = _boiler(hass)
    sc = SurplusController(hass)
    sc.register_device(dev)
    hass.set("switch.boiler", "off")
    hass.set("sensor.boiler_temp", "45.0")
    status = await dev.check_legionella_cycle()   # never run → due now
    assert status == "legionella_started"
    # (#1335) the check only says the run is due; the engine starts it
    assert not dev.is_active and not hass.calls("turn_on")
    await sc.update(-3000.0)                      # no sun at all
    assert dev.is_active and hass.calls("turn_on")
    assert dev._sem_commanded, "a Legionella start is SEM's own command"
    _past_min_run(dev)
    return sc, dev


@pytest.mark.asyncio
class TestTheRunHoldsOnADeficit:

    async def test_a_cloud_does_not_stop_the_run(self):
        hass = _Hass()
        sc, dev = await _legionella_running(hass)
        for _ in range(6):             # importing: no sun left
            await sc.update(-3000.0)
        assert dev.is_active, "the deficit pass stopped a Legionella run"
        assert not hass.calls("turn_off")
        assert await dev.check_legionella_cycle() == "legionella_heating"

    async def test_the_observer_path_says_the_same(self):
        hass = _Hass()
        sc, dev = await _legionella_running(hass)
        intents = sc._desired_intents(
            [dev], remaining_surplus=-1500.0, reclaim_w=0.0,
            battery_priority=None, price_level=None, peak_freeze=False,
            peak_shed=False, peak_shed_all=False)
        assert intents[dev.device_id].on is True

    async def test_the_run_still_ends_at_its_target(self):
        hass = _Hass()
        sc, dev = await _legionella_running(hass)
        hass.set("sensor.boiler_temp", str(dev.legionella_target_temp + 1))
        await dev.check_legionella_cycle()          # hold starts
        dev._legionella_hold_start -= timedelta(hours=2)
        assert await dev.check_legionella_cycle() == "legionella_complete"
        assert dev.is_active, "the check never switches (#1335)"
        await sc.update(-3000.0)                    # layer 1 ends the run
        assert not dev.is_active and hass.calls("turn_off")

    async def test_a_peak_shed_still_wins(self):
        hass = _Hass()
        sc, dev = await _legionella_running(hass)
        intents = sc._desired_intents(
            [dev], remaining_surplus=-1500.0, reclaim_w=0.0,
            battery_priority=None, price_level=None, peak_freeze=True,
            peak_shed=True, peak_shed_all=True)
        assert intents[dev.device_id].on is False


@pytest.mark.asyncio
async def test_a_solar_run_is_still_stopped_by_the_deficit():
    """The control: without a Legionella run the same deficit stops it."""
    hass = _Hass()
    dev = _boiler(hass)
    sc = SurplusController(hass)
    sc.register_device(dev)
    hass.set("switch.boiler", "off")
    hass.set("sensor.boiler_temp", "45.0")
    dev._last_legionella_time = datetime.now().astimezone()
    await sc.update(5000.0)
    assert dev.is_active
    _past_min_run(dev)
    for _ in range(6):                # the smoothing lets the cloud in
        await sc.update(-3000.0)
    assert not dev.is_active
