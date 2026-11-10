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


# ── step C: every reason a load stops lives in layer 1 ─────────────────────
from custom_components.solar_energy_management.coordinator import reason_codes as RC  # noqa: E402
from custom_components.solar_energy_management.coordinator.surplus_controller import (  # noqa: E402
    compute_load_intent,
    reconcile_load,
)


@pytest.mark.asyncio
class TestVacationIsALayerOneReason:

    async def test_a_run_going_when_away_starts_is_stopped_without_an_edge(self):
        """A restart while away: no rising edge is ever seen. Layer 1 reads
        the flag every cycle, so a SEM-started boost still ends."""
        hass = _Hass()
        sc, hp = _pump(hass)
        assert await _activate_owned(hp, 3000.0) > 0
        _past_min_run(hp)
        hp.vacation = True
        it = compute_load_intent(hp, remaining_surplus_w=6000.0)
        assert not it.on and it.code == RC.LOAD_VACATION
        await sc.update(6000.0)
        assert not hp.is_active and hp.sg_ready_state is SGReadyState.NORMAL

    async def test_under_observer_nothing_moves(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        assert await _activate_owned(hp, 3000.0) > 0
        _past_min_run(hp)
        hass.services.async_call.reset_mock()
        hp.vacation = True
        await sc.update(6000.0, observer=True)
        hass.services.async_call.assert_not_awaited()
        assert hp.is_active
        assert sc.observer_decisions["heat_pump"]["action"] == "deactivate"

    async def test_the_hot_water_dump_takes_free_sun_only(self):
        hass = _Hass()
        dev = HotWaterController(
            hass=hass, entity_id="switch.boiler",
            temperature_entity_id="sensor.boiler_temp",
            solar_target_temp=55.0, min_temperature=40.0, rated_power=2000.0,
            daily_min_runtime_sec=3600)
        dev.top_up_policy = "cheap_hours"
        dev._last_legionella_time = datetime.now().astimezone()
        hass.set("switch.boiler", "off")
        hass.set("sensor.boiler_temp", "35.0")
        dev.vacation, dev.vacation_dhw_surplus = True, True
        # a cheap hour and a deficit: away, nothing is bought
        assert not compute_load_intent(dev, remaining_surplus_w=0.0,
                                       price_is_cheap=True).on
        # free sun: it may take it, to the minimum temperature only
        assert compute_load_intent(dev, remaining_surplus_w=3000.0).on
        hass.set("sensor.boiler_temp", "41.0")
        assert not compute_load_intent(dev, remaining_surplus_w=3000.0).on


@pytest.mark.asyncio
class TestARefusedStartIsSaid:

    def _tank(self, hass, temp):
        dev = HotWaterController(
            hass=hass, entity_id="water_heater.boiler",
            temperature_entity_id="sensor.boiler_temp",
            solar_target_temp=55.0, rated_power=2000.0)
        dev._last_legionella_time = datetime.now().astimezone()
        hass.set("water_heater.boiler", "off", temperature=50.0)
        if temp is not None:
            hass.set("sensor.boiler_temp", str(temp))
        return dev

    async def test_a_tank_at_its_target_is_not_started(self):
        hass = _Hass()
        dev = self._tank(hass, 56.0)
        it = compute_load_intent(dev, remaining_surplus_w=5000.0)
        assert not it.on and it.code == RC.LOAD_STOP_CONDITION
        assert "target" in it.reason

    async def test_a_dead_sensor_is_not_heated_blind(self):
        hass = _Hass()
        dev = self._tank(hass, None)
        hass.set("sensor.boiler_temp", "unavailable")
        it = compute_load_intent(dev, remaining_surplus_w=5000.0)
        assert not it.on and "sensor" in it.reason
        sc = SurplusController(hass)
        sc.register_device(dev)
        await sc.update(5000.0)
        hass.services.async_call.assert_not_awaited()

    async def test_a_cold_tank_still_starts(self):
        hass = _Hass()
        dev = self._tank(hass, 40.0)
        assert compute_load_intent(dev, remaining_surplus_w=5000.0).on


@pytest.mark.asyncio
class TestModeOffIsOneReason:

    async def test_layer_one_writes_nothing_for_an_adopted_load(self):
        hass = _Hass()
        _sc, hp = _pump(hass)
        hp._status.state = hp._status.state.__class__.ACTIVE
        hp._sem_owned = True              # adopted, never commanded
        hp.control_mode = DeviceControlMode.OFF
        it = compute_load_intent(hp, remaining_surplus_w=0.0)
        assert it.on and it.release and hp._sem_owned is True
        await reconcile_load(hp, it, observer=True)
        assert hp._sem_owned is True, "observer lets go of nothing"
        await reconcile_load(hp, it)
        assert hp._sem_owned is False and hp.is_active
        hass.services.async_call.assert_not_awaited()

    async def test_the_users_off_beats_the_minimum_run(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        assert await _activate_owned(hp, 3000.0) > 0      # just started
        assert hp.can_deactivate() is False
        hp.control_mode = DeviceControlMode.OFF
        await sc.update(6000.0)
        assert not hp.is_active
