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
        assert not it.on and it.code == RC.LOAD_AT_TARGET
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


# ── step D: the three layers switch on every install ───────────────────────
from custom_components.solar_energy_management.tests.test_1048_phase_shed import (  # noqa: E402,F401
    _house, _switched_off, lm,
)


@pytest.mark.asyncio
async def test_every_install_starts_a_load_through_the_layers():
    """A plain switch load on sun: the start carries layer 1's own reason
    code ("solar") — the imperative passes logged "surplus"."""
    hass = _Hass()
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    dev = SwitchDevice(hass=hass, device_id="pump", name="Pump",
                       rated_power=800.0, entity_id="switch.pump")
    dev.control_mode = DeviceControlMode.SURPLUS
    hass.set("switch.pump", "off")
    sc = SurplusController(hass)
    sc.register_device(dev)
    await sc.update(3000.0)
    assert dev.is_active and dev._sem_commanded
    rows = [r for r in sc.decision_log.records() if r["device_id"] == "pump"]
    assert rows and rows[-1]["reason_code"] == RC.LOAD_SOLAR


@pytest.mark.asyncio
class TestTheLoadManagerWritesThroughItsSeam:

    async def test_a_phase_shed_under_observer_writes_nothing(self, lm):
        _house(lm)
        lm._observer_mode = True
        verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
        assert _switched_off(lm) == []
        lm.hass.services.async_call.assert_not_awaited()
        assert verdict["thrown"] == []
        assert lm.withheld_commands[-1]["service"] == "switch.turn_off"
        assert lm.withheld_commands[-1]["why"] == "observer"

    async def test_a_load_another_party_steers_is_not_written(self, lm):
        _house(lm)
        lm._devices["pool"]["external_yield"] = True
        await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
        assert "switch.pool_heat_pump" not in _switched_off(lm)
        assert lm.withheld_commands[-1]["why"] == "yield"

    async def test_observer_off_still_sheds(self, lm):
        _house(lm)
        verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
        assert verdict["thrown"] == ["pool"]
        assert lm.withheld_commands == []


# ── a real watt setpoint: booked what it is sent, not its rating ───────────
from custom_components.solar_energy_management.devices.power_setpoint import (  # noqa: E402
    PowerSetpointDevice,
)
from custom_components.solar_energy_management.tests.test_1102_import_counts_against_loads import (  # noqa: E402
    ENTITY as _HEATER,
    _Hass as _NumberHass,
)


def _heater(hass):
    heater = PowerSetpointDevice(
        hass=hass, device_id="heater", name="Heater",
        rated_power=9000.0, min_power_threshold=500.0, entity_id=_HEATER)
    heater.control_mode = DeviceControlMode.SURPLUS
    heater.min_on_seconds = heater.min_off_seconds = 0
    return heater


@pytest.mark.asyncio
class TestARealWattSetpoint:

    async def test_it_starts_at_the_free_power_below_its_rating(self):
        """9 kW rated, 1.5 kW free: booking the rating read as a 7.5 kW
        shortfall and cancelled the start."""
        hass = _NumberHass(0.0)
        heater = _heater(hass)
        sc = SurplusController(hass)
        sc.regulation_offset = 0.0
        sc.register_device(heater)
        await sc.update(1500.0)
        assert heater.is_active
        assert hass.value == pytest.approx(1500.0)

    async def test_it_ramps_down_with_the_sun_instead_of_stopping(self):
        hass = _NumberHass(3000.0)
        heater = _heater(hass)
        heater.adopt_if_running()
        sc = SurplusController(hass)
        sc.regulation_offset = 0.0
        sc.register_device(heater)
        for _ in range(8):                 # the smoothing lets the cloud in
            await sc.update(1200.0)
        assert heater.is_active, "stopped instead of following the sun down"
        assert hass.value == pytest.approx(1200.0, abs=30.0)

    async def test_no_sun_at_all_still_stops_it(self):
        hass = _NumberHass(3000.0)
        heater = _heater(hass)
        heater.adopt_if_running()
        sc = SurplusController(hass)
        sc.regulation_offset = 0.0
        sc.register_device(heater)
        for _ in range(12):
            await sc.update(0.0)
        assert not heater.is_active
        assert hass.value == 0.0


# ── review round: stops say their own cause; no sun means off ──────────────
from unittest.mock import MagicMock  # noqa: E402

from custom_components.solar_energy_management.devices.base import (  # noqa: E402
    DeviceState,
    SwitchDevice,
)
from custom_components.solar_energy_management.tests.test_desired_state import (  # noqa: E402
    _PDev,
)


def test_no_code_serves_both_a_start_and_a_stop():
    """A stop logged with a start's sentence read "it heats to the
    Legionella temperature" for a turn-off."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "coordinator" / "surplus_controller.py").read_text()
    on, off = set(), set()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "LoadIntent"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, bool)):
            continue
        code = node.args[4] if len(node.args) > 4 else next(
            (k.value for k in node.keywords if k.arg == "code"), None)
        if isinstance(code, ast.Attribute):
            (on if node.args[0].value else off).add(code.attr)
    assert on and off
    assert not (on & off), f"one code for a start and a stop: {on & off}"


@pytest.mark.asyncio
async def test_the_end_of_a_legionella_run_says_it_is_over():
    hass = _Hass()
    sc, dev = await _legionella_started(hass)
    hass.set("sensor.boiler_temp", str(dev.legionella_target_temp + 1))
    await dev.check_legionella_cycle()
    dev._legionella_hold_start -= timedelta(hours=1)
    await dev.check_legionella_cycle()
    await sc.update(-3000.0)
    last = [r for r in sc.decision_log.records() if r["device_id"] == dev.device_id][-1]
    assert (last["new"], last["reason_code"]) == ("off", RC.LOAD_LEGIONELLA_END)


def test_a_refused_start_names_its_cause():
    hass = _Hass()
    tank = TestARefusedStartIsSaid()._tank(hass, 56.0)
    assert compute_load_intent(tank, remaining_surplus_w=5000.0).code == RC.LOAD_AT_TARGET
    hass.set("sensor.boiler_temp", "unavailable")
    assert compute_load_intent(tank, remaining_surplus_w=5000.0).code == RC.LOAD_NO_READING


def _switch(hass, **kw):
    dev = SwitchDevice(hass=hass, device_id="pump", name="Pump",
                       rated_power=800.0, entity_id="switch.pump", **kw)
    dev.control_mode = DeviceControlMode.SURPLUS
    hass.set("switch.pump", "off")
    return dev


@pytest.mark.asyncio
class TestADisabledLoadSemStartedIsStillStopped:

    async def test_it_is_stopped_once_through_layer_three(self):
        hass = _Hass()
        dev = _switch(hass)
        sc = SurplusController(hass)
        sc.register_device(dev)
        await sc.update(3000.0)
        assert dev.is_active and dev._sem_commanded
        dev.disable()                       # inside its minimum run
        await sc.update(3000.0)
        assert not dev.is_active and len(hass.calls("turn_off", "switch.pump")) == 1
        last = sc.decision_log.records()[-1]
        assert (last["new"], last["reason_code"]) == ("off", RC.LOAD_MODE_OFF)
        await sc.update(3000.0)             # and never visited again
        assert not hass.calls("turn_on", "switch.pump")[1:]

    async def test_disabled_and_then_set_off_too(self):
        hass = _Hass()
        dev = _switch(hass)
        sc = SurplusController(hass)
        sc.register_device(dev)
        await sc.update(3000.0)
        dev.disable()
        dev.control_mode = DeviceControlMode.OFF
        await sc.update(3000.0)
        assert not dev.is_active

    async def test_a_disabled_load_the_user_runs_is_left_alone(self):
        hass = _Hass()
        dev = _switch(hass)
        sc = SurplusController(hass)
        sc.register_device(dev)
        hass.set("switch.pump", "on")
        dev._status.state = DeviceState.ACTIVE      # running, never SEM's
        dev.disable()
        await sc.update(0.0)
        assert dev.is_active and not hass.calls("turn_off", "switch.pump")

    async def test_an_externally_managed_device_stays_untouched(self):
        """The EV chargers: their whole lifecycle is ev_control's, whoever
        started them."""
        hass = _Hass()
        dev = _switch(hass)
        sc = SurplusController(hass)
        sc.register_device(dev)
        await _activate_owned(dev, 800.0)
        dev.managed_externally = True
        dev.control_mode = DeviceControlMode.OFF
        await sc.update(0.0)
        assert dev.is_active and dev._sem_owned
        assert not hass.calls("turn_off", "switch.pump")


async def _small(**kw):
    sc = SurplusController(MagicMock())
    sc.regulation_offset = 0.0
    d = _PDev("a", 1, **kw)
    sc.register_device(d)
    return sc, d


@pytest.mark.asyncio
class TestNoSunMeansOff:

    @pytest.mark.parametrize("reading", ["0", "unavailable", "1500"])
    async def test_a_boiler_whose_power_sensor_reads_zero_stops_at_night(self, reading):
        hass = _Hass()
        hass.set("switch.boiler", "off")
        hass.set("sensor.t", "40")
        hass.set("sensor.p", "0", unit_of_measurement="W")
        dev = HotWaterController(
            hass=hass, entity_id="switch.boiler", temperature_entity_id="sensor.t",
            solar_target_temp=55.0, rated_power=2000.0, power_entity_id="sensor.p")
        dev._last_legionella_time = datetime.now().astimezone()
        dev.min_on_seconds = dev.min_off_seconds = 0
        sc = SurplusController(hass)
        sc.regulation_offset = 0.0
        sc.register_device(dev)
        for _ in range(4):
            await sc.update(5000.0)
        assert dev.is_active
        _past_min_run(dev)
        hass.set("sensor.p", reading, unit_of_measurement="W")
        for _ in range(15):
            await sc.update(-200.0, is_night=True)
        assert not dev.is_active

    @pytest.mark.parametrize("draw", [60.0, 90.0, 120.0, 800.0])
    async def test_a_small_load_stops_with_no_sun(self, draw):
        sc, d = await _small(is_active=True, draw=draw, min_power=50.0, rated_power=draw)
        await sc.update(0.0)
        assert not d.is_active

    async def test_a_boiler_idling_on_its_thermostat_at_noon_stays(self):
        """0 W on its sensor, sun in the pool: it costs the sun nothing and
        is left on, so its thermostat can take over — no flapping."""
        sc, d = await _small(is_active=True, draw=0.0, min_power=800.0, rated_power=2000.0)
        for _ in range(10):
            await sc.update(3000.0)
        assert d.is_active

    async def test_inside_the_band_with_sun_it_stays(self):
        sc, d = await _small(is_active=True, draw=800.0, min_power=800.0)
        for _ in range(10):
            await sc.update(750.0)          # 50 W short, sun in the pool
        assert d.is_active

    async def test_the_minimum_run_still_holds(self):
        sc, d = await _small(is_active=True, draw=60.0, min_power=50.0,
                             can_deactivate=False)
        await sc.update(0.0)
        assert d.is_active
        d._can_deact = True
        await sc.update(0.0)
        assert not d.is_active

    async def test_a_paid_run_and_a_battery_share_are_reasons_to_run(self):
        sc, d = await _small(is_active=True, draw=60.0, min_power=50.0,
                             _offpeak_forced=True, has_runtime_deficit=True,
                             top_up_policy="cheap_hours")
        await sc.update(0.0, price_level="cheap")
        assert d.is_active
        sc, d = await _small(is_active=True, draw=60.0, min_power=50.0,
                             battery_assist_enabled=True)
        await sc.update(0.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=3000.0)
        assert d.is_active
