"""#1335 — a load is switched in one place.

Three writers moved loads past ``reconcile_load``:

* the Legionella check started and ended its run with a plain
  ``activate()`` / ``deactivate()``. The start was never SEM's own command
  (``_sem_commanded`` stayed False), so Mode Off and teardown left a tank
  heating to 60 °C+ when SEM went away mid-run.
* the heat pump wrote its SG-Ready contacts and service with a raw
  ``async_call``, past ``send()``. Mode Off and teardown reach the pump
  directly, so a pump SEM boosted before observer mode was switched on was
  moved for real.
* a water_heater tank claimed ACTIVE when ``send()`` withheld its write.

Pinned through the real controllers.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    _activate_owned,
    deactivate_devices,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)


def _past_min_run(dev):
    dev._last_activated = datetime.now() - timedelta(hours=1)
    dev._status.last_activated = dev._last_activated


async def _legionella_started(hass):
    dev = HotWaterController(
        hass=hass, entity_id="switch.boiler",
        temperature_entity_id="sensor.boiler_temp",
        solar_target_temp=55.0, rated_power=2000.0)
    sc = SurplusController(hass)
    sc.register_device(dev)
    hass.set("switch.boiler", "off")
    hass.set("sensor.boiler_temp", "45.0")
    assert await dev.check_legionella_cycle() == "legionella_started"
    await sc.update(-3000.0)
    assert dev.is_active and dev._sem_commanded
    _past_min_run(dev)
    return sc, dev


@pytest.mark.asyncio
class TestALegionellaRunIsSemsOwn:

    async def test_teardown_stops_it(self):
        hass = _Hass()
        _sc, dev = await _legionella_started(hass)
        assert await deactivate_devices([dev]) == 1
        assert not dev.is_active and hass.calls("turn_off")

    async def test_mode_off_stops_it(self):
        hass = _Hass()
        sc, dev = await _legionella_started(hass)
        dev.control_mode = DeviceControlMode.OFF
        await sc.update(-3000.0)
        assert not dev.is_active and hass.calls("turn_off")

    async def test_the_end_of_the_run_switches_it_off_once(self):
        hass = _Hass()
        sc, dev = await _legionella_started(hass)
        hass.set("sensor.boiler_temp", str(dev.legionella_target_temp + 1))
        await dev.check_legionella_cycle()
        dev._legionella_hold_start -= timedelta(hours=1)
        assert await dev.check_legionella_cycle() == "legionella_complete"
        assert dev.is_active, "the check itself never switches"
        await sc.update(-3000.0)
        assert not dev.is_active
        assert len(hass.calls("turn_off")) == 1
        await dev.check_legionella_cycle()
        assert dev.own_run_ending is False


def _pump(hass):
    hass.set("switch.sg1", "off")
    hass.set("switch.sg2", "off")
    hp = HeatPumpController(hass, relay1_entity_id="switch.sg1",
                            relay2_entity_id="switch.sg2",
                            rated_power=2000.0, min_power_threshold=2000.0)
    hp._boot_adoption_pending = False
    sc = SurplusController(hass)
    sc.register_device(hp)
    return sc, hp


async def _boosted_then_observer(hass):
    sc, hp = _pump(hass)
    assert await _activate_owned(hp, 3000.0) > 0
    assert hp.is_active and hp._sem_commanded
    assert hp.sg_ready_state is SGReadyState.BOOST
    _past_min_run(hp)
    hp.observer_mode = True            # observer switched on afterwards
    hp.withheld_commands = []
    hass.services.async_call.reset_mock()
    return sc, hp


@pytest.mark.asyncio
class TestTheHeatPumpWritesThroughTheSeam:

    async def test_teardown_under_observer_writes_nothing(self):
        hass = _Hass()
        _sc, hp = await _boosted_then_observer(hass)
        await deactivate_devices([hp])
        hass.services.async_call.assert_not_awaited()
        assert hp.withheld_commands, "the seam names what it held back"
        assert hp.is_active, "the pump did not move, so neither does the belief"
        assert hp.sg_ready_state is SGReadyState.BOOST

    async def test_mode_off_under_observer_writes_nothing(self):
        hass = _Hass()
        sc, hp = await _boosted_then_observer(hass)
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._control_mode_overrides = {}
        reg._user_control_modes = set()
        reg._service_registrations = {}
        reg._surplus_controller = sc
        reg._load_manager = None

        async def _save():
            return None
        reg._save_storage = _save
        await reg.update_device_control_mode("heat_pump", "off")
        await sc.update(-3000.0, observer=True)
        hass.services.async_call.assert_not_awaited()
        assert hp.is_active

    async def test_a_direct_boost_under_observer_claims_nothing(self):
        hass = _Hass()
        _sc, hp = _pump(hass)
        hp.observer_mode = True
        assert await hp.activate(3000.0) == 0.0
        hass.services.async_call.assert_not_awaited()
        assert not hp.is_active
        assert hp._last_relay_path == "withheld"

    async def test_observer_off_still_moves_the_relays(self):
        hass = _Hass()
        _sc, hp = _pump(hass)
        assert await hp.activate(3000.0) == 2000.0
        assert hass.calls("turn_on", "switch.sg2")
        await hp.deactivate()
        assert not hp.is_active
        assert hass.calls("turn_off", "switch.sg2")
