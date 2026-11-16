"""#1102 — a Legionella run that your own stop keeps below its target.

The reporter's boiler: "stop when the tank reads >= 53 °C", Legionella target
60 °C or more. Since #1062 a stop the user set still applies during a
Legionella run, so the tank stopped at 53 °C. The run never reached its
target, so it never ended: every time the tank cooled below 53 °C it was
switched on again, sun or not, because a Legionella run is exempt from the
solar-only stop (#1121). The house bought power for it again and again.

Now the run ends when your stop fires below the target, or after
``LEGIONELLA_MAX_RUN_HOURS``; it does not count as a disinfection, and the
next try waits one full interval.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices import hot_water_controller as hwc
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)


def _boiler(hass, stop_at=53.0):
    dev = HotWaterController(
        hass=hass, entity_id="switch.boiler",
        temperature_entity_id="sensor.boiler_temp",
        solar_target_temp=55.0, rated_power=3000.0)
    dev.stop_entity, dev.stop_at = "sensor.boiler_temp", stop_at
    return dev


def _past_min_times(dev):
    long_ago = datetime.now() - timedelta(hours=1)
    dev._last_activated = long_ago
    dev._status.last_activated = long_ago
    dev._last_deactivated = long_ago


async def _overdue_run_started(hass, dev):
    sc = SurplusController(hass)
    sc.register_device(dev)
    hass.set("switch.boiler", "off")
    hass.set("sensor.boiler_temp", "45.0")
    assert await dev.check_legionella_cycle() == "legionella_started"
    await sc.update(-3000.0)          # (#1335) the engine starts the run
    assert dev.is_active
    _past_min_times(dev)
    return sc


@pytest.mark.asyncio
class TestTheReportersBoiler:
    """(#1369) A stop on the tank's own temperature below the target is
    known before the run, so no run starts: before, it heated on grid power
    up to the stop and then ended. What #1102 asked for still holds: no
    reheating on grid power, no false disinfection, one interval to the
    next try."""

    async def _blocked(self, hass, dev):
        sc = SurplusController(hass)
        sc.register_device(dev)
        hass.set("switch.boiler", "off")
        hass.set("sensor.boiler_temp", "45.0")
        assert await dev.check_legionella_cycle() == "legionella_blocked_by_stop"
        await sc.update(-3000.0)
        return sc

    async def test_a_run_your_stop_keeps_below_the_target_never_starts(self):
        hass = _Hass()
        dev = _boiler(hass)
        await self._blocked(hass, dev)
        assert not dev._legionella_cycle_active
        assert not dev.is_active
        assert not hass.calls("turn_on")

    async def test_it_is_not_switched_on_again_on_grid_power_when_it_cools(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = await self._blocked(hass, dev)
        hass.set("sensor.boiler_temp", "40.0")
        for _ in range(6):                           # importing, no sun
            await dev.check_legionella_cycle()
            await sc.update(-3000.0)
        assert not dev.is_active, "the boiler heats on grid power (#1102)"
        assert not hass.calls("turn_on")

    async def test_it_is_not_counted_as_a_disinfection(self):
        hass = _Hass()
        dev = _boiler(hass)
        await self._blocked(hass, dev)
        assert dev._last_legionella_time is None
        assert dev.hours_since_legionella == 999.0

    async def test_the_next_try_waits_one_interval(self):
        hass = _Hass()
        dev = _boiler(hass)
        await self._blocked(hass, dev)
        assert not dev.legionella_overdue
        assert await dev.check_legionella_cycle() is None
        dev._legionella_blocked_until = dt_util.now() - timedelta(minutes=1)
        assert dev.legionella_overdue
        # the stop is still there: still no heating for it
        assert await dev.check_legionella_cycle() == "legionella_blocked_by_stop"
        # once the user raises the stop above the target, the run starts
        dev._legionella_blocked_until = dt_util.now() - timedelta(minutes=1)
        dev.stop_at = 70.0
        assert await dev.check_legionella_cycle() == "legionella_started"

    async def test_a_stop_already_met_does_not_start_a_run(self):
        hass = _Hass()
        dev = _boiler(hass)
        SurplusController(hass).register_device(dev)
        hass.set("switch.boiler", "off")
        hass.set("sensor.boiler_temp", "54.0")
        assert await dev.check_legionella_cycle() == "legionella_blocked_by_stop"
        assert not dev.is_active
        assert not hass.calls("turn_on")

    async def test_a_stop_on_another_sensor_still_ends_the_run_at_the_stop(self):
        """A stop SEM cannot compare with the tank (another sensor): the run
        starts and ends when that stop fires, as #1102 fixed it."""
        hass = _Hass()
        dev = _boiler(hass)
        dev.stop_entity = "sensor.other"
        hass.set("sensor.other", "10.0")
        sc = await _overdue_run_started(hass, dev)
        hass.set("sensor.other", "60.0")
        assert await dev.check_legionella_cycle() == "legionella_blocked_by_stop"
        await sc.update(-3000.0)
        assert not dev.is_active


@pytest.mark.asyncio
class TestWhatStaysTheSame:

    async def test_a_stop_above_the_target_lets_the_run_finish(self):
        hass = _Hass()
        dev = _boiler(hass, stop_at=80.0)
        await _overdue_run_started(hass, dev)
        hass.set("sensor.boiler_temp", str(dev.legionella_target_temp + 1))
        assert (await dev.check_legionella_cycle()).startswith("legionella_holding")
        dev._legionella_hold_start -= timedelta(hours=2)
        assert await dev.check_legionella_cycle() == "legionella_complete"
        assert dev._last_legionella_time is not None
        assert dev._legionella_blocked_until is None

    async def test_no_stop_set_heats_on_as_before(self):
        hass = _Hass()
        dev = _boiler(hass, stop_at=0.0)
        await _overdue_run_started(hass, dev)
        hass.set("sensor.boiler_temp", "53.2")
        assert await dev.check_legionella_cycle() == "legionella_heating"
        assert dev._legionella_cycle_active


@pytest.mark.asyncio
class TestTheTimeLimit:

    async def test_a_run_that_cannot_reach_its_target_ends_after_the_limit(self):
        hass = _Hass()
        dev = _boiler(hass, stop_at=0.0)
        await _overdue_run_started(hass, dev)
        hass.set("sensor.boiler_temp", "58.0")       # a weak heater
        dev._legionella_started_at -= timedelta(hours=hwc.LEGIONELLA_MAX_RUN_HOURS + 0.1)
        assert await dev.check_legionella_cycle() == "legionella_timed_out"
        assert not dev._legionella_cycle_active
        assert dev._last_legionella_time is None

    async def test_a_run_inside_the_limit_keeps_heating(self):
        hass = _Hass()
        dev = _boiler(hass, stop_at=0.0)
        await _overdue_run_started(hass, dev)
        hass.set("sensor.boiler_temp", "58.0")
        dev._legionella_started_at -= timedelta(hours=hwc.LEGIONELLA_MAX_RUN_HOURS - 1)
        assert await dev.check_legionella_cycle() == "legionella_heating"
