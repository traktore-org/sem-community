"""(#1081) A unit SEM steers by its own setpoint gets back the setpoint it HAD,
not the configured one; a hand change during the run is never overwritten.

One fake Home Assistant moves the unit's ``temperature`` the way a real
thermostat does, so every assertion reads what the unit shows at the end.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.storage import SEMStorage
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    deactivate_devices,
)
from custom_components.solar_energy_management.devices import setpoint_memo
from custom_components.solar_energy_management.devices.base import (
    ClimateDevice,
    SetpointDevice,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)

UNIT = "climate.unit"
TANK = "water_heater.tank"


class _Hass:
    def __init__(self):
        self._states: dict = {}
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
        self.states = MagicMock()
        self.states.get = self._states.get
        self.services = MagicMock()
        self.services.async_call = AsyncMock(side_effect=self._call)

    def unit(self, eid, state="heat", **attrs):
        from types import SimpleNamespace as NS
        self._states[eid] = NS(entity_id=eid, state=state, attributes=attrs)

    def hand(self, eid, temperature):
        """The user turns the dial."""
        self._states[eid].attributes["temperature"] = temperature

    async def _call(self, domain, service, data=None, **_kw):
        eid = data["entity_id"]
        if service == "set_temperature":
            self._states[eid].attributes["temperature"] = data["temperature"]
        elif service in ("set_hvac_mode",):
            self._states[eid].state = data["hvac_mode"]
        elif service in ("turn_on", "turn_off"):
            self._states[eid].state = "on" if service == "turn_on" else "off"

    def now(self, eid):
        return self._states[eid].attributes.get("temperature")

    def setpoint_writes(self):
        return [c.args[2]["temperature"] for c in self.services.async_call.await_args_list
                if c.args[1] == "set_temperature"]


def _pump(hass, **kw):
    return SetpointDevice(
        hass, "hp", "Pump", 2000.0, climate_entity_id=UNIT,
        normal_setpoint=20.0, boost_offset=2.0, **kw)


def _ac(hass, **kw):
    return ClimateDevice(
        hass, "ac", "AC", 1500.0, entity_id=UNIT, hvac_mode="heat",
        target_temperature=24.0, min_on_time=0, min_off_time=0, **kw)


def _tank(hass):
    return HotWaterController(
        hass=hass, entity_id=TANK, rated_power=2000.0, solar_target_temp=55.0)


@pytest.fixture
def hass():
    h = _Hass()
    h.unit(UNIT, "heat", temperature=21.5)
    h.unit(TANK, "heat", temperature=48.0, current_temperature=40.0)
    return h


# ── the run's end puts back the setpoint the unit had ─────────────────────

@pytest.mark.asyncio
async def test_a_boosted_unit_gets_21_5_back_not_the_configured_20(hass):
    dev = _pump(hass)
    await dev.activate(3000)
    assert hass.now(UNIT) == 22.0                  # normal 20 + offset 2
    await dev.deactivate()
    assert hass.now(UNIT) == 21.5
    assert dev.sp_memo() is None


@pytest.mark.asyncio
async def test_a_climate_unit_sent_to_its_target_gets_21_5_back(hass):
    dev = _ac(hass)
    await dev.activate(3000)
    assert hass.now(UNIT) == 24.0
    await dev.deactivate()
    assert hass.now(UNIT) == 21.5
    assert hass._states[UNIT].state == "off"
    assert dev.sp_memo() is None


@pytest.mark.asyncio
async def test_a_water_heater_tank_gets_its_own_setpoint_back(hass):
    dev = _tank(hass)
    await dev._activate_water_heater()
    assert hass.now(TANK) != 48.0
    await dev._deactivate_water_heater()
    assert hass.now(TANK) == 48.0
    assert dev.sp_memo() is None


@pytest.mark.asyncio
async def test_a_second_boost_in_one_run_keeps_the_first_memory(hass):
    dev = _tank(hass)
    await dev._activate_water_heater()
    dev.legionella_target_temp = 65.0
    dev._legionella_cycle_active = True            # the target changes mid-run
    await dev._activate_water_heater()
    assert dev.sp_memo()["restore"] == 48.0
    await dev._deactivate_water_heater()
    assert hass.now(TANK) == 48.0


# ── a hand change is never fought ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_hand_change_during_the_run_is_not_written_over(hass):
    dev = _pump(hass)
    await dev.activate(3000)
    hass.hand(UNIT, 23.0)
    before = len(hass.setpoint_writes())
    await dev.deactivate()
    assert hass.now(UNIT) == 23.0
    assert len(hass.setpoint_writes()) == before
    assert dev.sp_memo() is None                    # the memo is dropped


@pytest.mark.asyncio
async def test_a_hand_change_on_a_climate_unit_and_a_tank_is_left_too(hass):
    ac, tank = _ac(hass), _tank(hass)
    await ac.activate(3000)
    hass.hand(UNIT, 19.0)
    await ac.deactivate()
    assert hass.now(UNIT) == 19.0
    await tank._activate_water_heater()
    hass.hand(TANK, 61.0)
    await tank._deactivate_water_heater()
    assert hass.now(TANK) == 61.0


# ── a setpoint that cannot be read ────────────────────────────────────────

@pytest.mark.asyncio
async def test_unreadable_at_start_falls_back_to_the_configured_value_and_logs_once(
        hass, caplog):
    hass.unit(UNIT, "heat")                         # no temperature attribute
    dev = _pump(hass)
    with caplog.at_level(logging.INFO):
        await dev.activate(3000)
        await dev.deactivate()
        await dev.activate(3000)
        await dev.deactivate()
    assert hass.setpoint_writes() == [22.0, 20.0, 22.0, 20.0]
    said = [r for r in caplog.records if "cannot be read" in r.getMessage()]
    assert len(said) == 1


@pytest.mark.asyncio
async def test_unreadable_for_a_climate_unit_writes_nothing_back(hass):
    hass.unit(UNIT, "heat")
    dev = _ac(hass)
    await dev.activate(3000)
    await dev.deactivate()
    assert hass.setpoint_writes() == [24.0]        # as before: no write-back


# ── a restart in the middle of a run ──────────────────────────────────────

@pytest.mark.asyncio
async def test_a_restart_mid_run_still_restores_21_5(hass):
    first = _pump(hass)
    await first.activate(3000)
    stored = first.sp_memo()
    fresh = _pump(hass)                             # a restart: nothing in memory
    assert fresh._boosted is False and fresh.sp_memo() is None
    assert fresh.sp_adopt_memo(stored) is True
    await fresh.deactivate()
    assert hass.now(UNIT) == 21.5


@pytest.mark.asyncio
async def test_a_stored_memo_the_unit_no_longer_matches_is_dropped_unwritten(hass):
    first = _pump(hass)
    await first.activate(3000)
    stored = first.sp_memo()
    hass.hand(UNIT, 18.0)                           # changed while SEM was down
    fresh = _pump(hass)
    fresh.sp_adopt_memo(stored)
    writes = len(hass.setpoint_writes())
    await fresh.deactivate()
    assert hass.now(UNIT) == 18.0 and len(hass.setpoint_writes()) == writes
    assert fresh.sp_memo() is None


@pytest.mark.asyncio
async def test_an_idle_unit_with_a_memo_is_put_back_by_the_sweep(hass):
    first = _pump(hass)
    await first.activate(3000)
    fresh = _pump(hass)
    fresh.sp_adopt_memo(first.sp_memo())
    assert fresh.is_active is False
    assert await fresh.sp_release_orphan() == "written"
    assert hass.now(UNIT) == 21.5


@pytest.mark.asyncio
async def test_the_sweep_leaves_a_running_unit_alone(hass):
    dev = _pump(hass)
    await dev.activate(3000)
    assert await dev.sp_release_orphan() == "none"
    assert hass.now(UNIT) == 22.0


# ── observer mode: nothing is sent, nothing is remembered ─────────────────

@pytest.mark.asyncio
async def test_observer_mode_sends_nothing_and_remembers_nothing(hass):
    for dev in (_pump(hass), _ac(hass), _tank(hass)):
        dev.observer_mode = True
        hass.services.async_call.reset_mock()
        if isinstance(dev, HotWaterController):
            await dev._activate_water_heater()
            await dev._deactivate_water_heater()
        else:
            await dev.activate(3000)
            await dev.deactivate()
        assert hass.services.async_call.await_count == 0
        assert dev.sp_memo() is None
    assert hass.now(UNIT) == 21.5 and hass.now(TANK) == 48.0


@pytest.mark.asyncio
async def test_observer_switched_on_mid_run_keeps_the_memo_for_later(hass):
    dev = _pump(hass)
    await dev.activate(3000)
    dev.observer_mode = True
    await dev.deactivate()
    assert hass.now(UNIT) == 22.0                   # nothing went out
    assert dev.sp_memo() is not None                # …and it is not forgotten
    dev.observer_mode = False
    assert dev.is_active                            # belief kept: the engine retries
    await dev.deactivate()
    assert hass.now(UNIT) == 21.5


# ── a memo older than 48 h ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_memo_older_than_48_hours_is_dropped_without_a_write(hass, monkeypatch):
    dev = _pump(hass)
    await dev.activate(3000)
    real = setpoint_memo._now()
    monkeypatch.setattr(setpoint_memo, "_now", lambda: real + 48 * 3600 + 60)
    before = len(hass.setpoint_writes())
    await dev.deactivate()
    assert len(hass.setpoint_writes()) == before    # not even the configured one
    assert dev.sp_memo() is None


def test_a_stored_memo_older_than_48_hours_is_not_adopted(hass, monkeypatch):
    dev = _pump(hass)
    old = {"restore": 21.5, "wrote": 22.0, "at": setpoint_memo._now() - 49 * 3600,
           "entity": UNIT, "domain": "climate"}
    assert dev.sp_adopt_memo(old) is False
    assert dev.sp_memo() is None


# ── unload ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unload_restores_the_setpoint_of_a_running_and_an_idle_unit(hass):
    running = _pump(hass)
    await running.activate(3000)
    running._sem_owned = running._sem_commanded = True
    other = _ac(hass)
    hass.unit("climate.other", "heat", temperature=19.0)
    other.entity_id = "climate.other"
    await other.activate(3000)
    other._status.state = other._status.state.__class__.IDLE   # believed idle
    await deactivate_devices([running, other], "unload")
    assert hass.now(UNIT) == 21.5
    assert hass.now("climate.other") == 19.0


# ── idempotent ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_unit_already_at_the_remembered_value_gets_no_write(hass):
    dev = _pump(hass)
    await dev.activate(3000)
    hass.hand(UNIT, 21.5)                           # the user put it back
    before = len(hass.setpoint_writes())
    await dev.deactivate()
    assert len(hass.setpoint_writes()) == before
    assert dev.sp_memo() is None


@pytest.mark.asyncio
async def test_a_unit_already_at_sems_value_at_the_start_keeps_it(hass):
    hass.unit(UNIT, "heat", temperature=22.0)       # = normal + offset
    dev = _pump(hass)
    await dev.activate(3000)
    assert dev.sp_memo()["restore"] == 22.0
    before = len(hass.setpoint_writes())
    await dev.deactivate()
    assert hass.now(UNIT) == 22.0                   # the user's value, not 20
    assert len(hass.setpoint_writes()) == before


# ── a heat pump keeps working through its own controller ──────────────────

@pytest.mark.asyncio
async def test_a_heat_pump_with_a_climate_entity_restores_through_its_deactivate(hass):
    hp = HeatPumpController(hass=hass, climate_entity_id=UNIT, normal_setpoint=20.0,
                            boost_offset=2.0)
    await hp.activate(3000)
    await hp.deactivate()
    assert hass.now(UNIT) == 21.5


# ── storage: kept by the coordinator beside the step-down memo ────────────

def test_the_memos_are_stored_and_merged_over_what_is_stored(hass):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    store = SimpleNamespace(_energy_data={})
    assert SEMStorage.get_setpoint_memo_state(store) == {}
    dev = _pump(hass)
    dev._sp_memo = {"restore": 21.5, "wrote": 22.0, "at": setpoint_memo._now(),
                    "entity": UNIT, "domain": "climate"}
    host = SimpleNamespace(
        _surplus_controller=SimpleNamespace(_devices={"hp": dev}),
        _storage=SimpleNamespace(get_setpoint_memo_state=lambda: {
            "later": {"restore": 1.0}, "hp": {"restore": 9.0}}),
        _setpoint_devices=lambda: [("hp", dev)])
    memos = SEMCoordinator._setpoint_memos(host)
    assert memos["hp"]["restore"] == 21.5           # the live one wins
    assert memos["later"] == {"restore": 1.0}       # a device not built yet keeps its own
    SEMStorage.set_setpoint_memo_state(store, memos)
    assert SEMStorage.get_setpoint_memo_state(store)["hp"]["restore"] == 21.5


@pytest.mark.asyncio
async def test_the_coordinator_seeds_once_and_sweeps_an_idle_unit(hass):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    first = _pump(hass)
    await first.activate(3000)
    stored = {"hp": first.sp_memo()}
    fresh = _pump(hass)
    host = SimpleNamespace(
        _storage=SimpleNamespace(get_setpoint_memo_state=lambda: stored),
        _setpoint_devices=lambda: [("hp", fresh)])
    await SEMCoordinator._sweep_setpoint_memos(host)
    assert hass.now(UNIT) == 21.5
    assert fresh.sp_memo() is None


def test_the_memo_travels_with_a_rebuilt_device():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    assert "_sp_memo" in SurplusController._VOLATILE_CONTROL_FIELDS


@pytest.mark.asyncio
async def test_a_boost_that_replaces_a_step_down_restores_the_users_setpoint(hass):
    hp = HeatPumpController(hass=hass, climate_entity_id=UNIT, normal_setpoint=20.0,
                            boost_offset=2.0)
    hass.unit(UNIT, "heat", temperature=19.5)       # SEM lowered 21.5 by 2
    hp._stepped_down, hp._step_restore_setpoint = True, 21.5
    await hp.activate(3000)
    await hp.deactivate()
    assert hass.now(UNIT) == 21.5                   # not the lowered 19.5


@pytest.mark.asyncio
async def test_a_tank_without_an_off_stays_at_its_minimum_and_is_not_restored(hass, caplog):
    real = hass._call

    async def _call(domain, service, data=None, **kw):
        if service == "turn_off":
            raise RuntimeError("no off")
        await real(domain, service, data, **kw)
    hass.services.async_call = AsyncMock(side_effect=_call)
    dev = _tank(hass)
    await dev._activate_water_heater()
    with caplog.at_level(logging.INFO):
        await dev._deactivate_water_heater()
    assert hass.now(TANK) == dev.min_temperature     # SEM's off state
    assert dev.sp_memo() is None
    assert any("no off" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_the_sweep_never_writes_to_a_climate_unit_that_is_off(hass):
    first = _pump(hass)
    await first.activate(3000)
    fresh = _pump(hass)
    fresh.sp_adopt_memo(first.sp_memo())
    hass._states[UNIT].state = "off"
    writes = len(hass.setpoint_writes())
    assert await fresh.sp_release_orphan() == "off"
    assert len(hass.setpoint_writes()) == writes and fresh.sp_memo() is not None
    hass._states[UNIT].state = "heat"                # running again
    assert await fresh.sp_release_orphan() == "written"
    assert hass.now(UNIT) == 21.5


@pytest.mark.asyncio
async def test_a_unit_with_big_steps_still_restores(hass):
    hass.unit(UNIT, "heat", temperature=20.0, target_temp_step=5.0)
    dev = _pump(hass)
    await dev.activate(3000)                         # wrote 22.0
    hass.hand(UNIT, 20.0)                            # the unit rounds 22 to 20
    await dev.deactivate()
    assert dev.sp_memo() is None
    hass.hand(UNIT, 22.5)                            # 2.5 K off: within step / 2
    dev2 = _pump(hass)
    dev2.sp_adopt_memo({"restore": 15.0, "wrote": 22.0, "at": setpoint_memo._now(),
                        "entity": UNIT, "domain": "climate"})
    await dev2.deactivate()
    assert hass.now(UNIT) == 15.0
