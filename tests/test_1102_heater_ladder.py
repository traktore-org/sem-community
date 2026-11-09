"""(#1102) A heater with a thermometer follows ONE ladder in layer 1.

The reporter's boiler (Keep at 50 °C, Extra 5 °C, Limit 36 °C) was switched by
several rules at once — the daily run time, the comfort band, Legionella, his
stop — and the last to fire won. In layer 1 the first rung that applies leads:

1. Stop when (your stop) → off. A Legionella run's own target is above SEM's
   own stops, so those do not apply during it; YOUR stop still ends it (#1102).
2. Legionella due → runs to its own temperature, sun or not.
3. Too cold (at or past the limit) → heats now on any tariff, on to Keep at.
4. Below Keep at → heats in its planned block, up to Keep at.
5. Sun → up to Keep at + Extra (the band banks there).
6. The daily run time asks nothing for a heater with a band.

.175 09.11 scenario 3: 34 °C on an expensive hour waited for the cheap block.
.175 09.11 scenario 2: a 52 °C tank was heated 2.25 kWh for its run time.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.plan_verdict import PlanVerdict
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    DeviceState,
    SwitchDevice,
)

TANK = "sensor.tank"


def _hass(**states):
    hass = MagicMock()
    hass.config.units.temperature_unit = "°C"

    def _get(eid):
        v = states.get(eid.replace(".", "__"))
        if v is None:
            return None
        st = MagicMock()
        st.state, st.attributes = str(v), {"unit_of_measurement": "°C"}
        return st
    hass.states.get.side_effect = _get
    return hass


def _boiler(temp, *, active=False, stop_at=None, runtime_min=60, policy="cheap_hours"):
    states = {"sensor__tank": temp}
    dev = SwitchDevice(_hass(**states), "boiler", "Boiler", rated_power=3000.0,
                       entity_id="switch.boiler", daily_min_runtime_sec=runtime_min * 60)
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity, dev.comfort_target, dev.comfort_offset, dev.comfort_limit = TANK, 50.0, 5.0, 36.0
    dev.top_up_policy = policy
    if stop_at is not None:
        dev.stop_entity, dev.stop_at = TANK, stop_at
    if active:
        dev._status.state = DeviceState.ACTIVE
    return dev


def _intent(dev, **kw):
    args = dict(remaining_surplus_w=0.0, price_is_cheap=False, is_night=True)
    args.update(kw)
    return compute_load_intent(dev, **args)


@pytest.mark.unit
class TestTooCold:
    def test_scenario_3_heats_now_on_an_expensive_hour(self):
        it = _intent(_boiler(34.0), price_is_cheap=False)
        assert it.on and it.source == "comfort_floor" and it.code == RC.LOAD_COMFORT_FLOOR

    def test_with_sun_it_is_counted_as_sun(self):
        it = _intent(_boiler(34.0), remaining_surplus_w=4000.0)
        assert it.on and it.source == "solar" and it.code == RC.LOAD_COMFORT_FLOOR

    def test_a_floor_run_goes_on_to_keep_at(self):
        dev = _boiler(45.0, active=True)
        dev._comfort_floor_run = True
        assert _intent(dev).code == RC.LOAD_COMFORT_FLOOR and _intent(dev).on
        dev._comfort_floor_run = False   # a run the floor did not start stops (no source)
        assert not _intent(dev).on

    def test_your_stop_beats_too_cold(self):
        it = _intent(_boiler(34.0, stop_at=30.0))
        assert not it.on and it.code == RC.LOAD_STOP_CONDITION

    def test_peak_shed_beats_too_cold(self):
        it = _intent(_boiler(34.0, active=True), is_shed_target=True)
        assert not it.on and it.code == RC.LOAD_PEAK_SHED


@pytest.mark.unit
class TestKeepAtIsAGoal:
    def test_below_keep_at_heats_in_its_planned_block(self):
        it = _intent(_boiler(45.0), plan=PlanVerdict(in_block=True, comfort_in_block=True))
        assert it.on and it.source == "cheap_grid" and it.code == RC.LOAD_COMFORT_GOAL

    def test_at_or_above_keep_at_the_plan_starts_nothing(self):
        it = _intent(_boiler(52.0), plan=PlanVerdict(in_block=True, comfort_in_block=True))
        assert not it.on

    def test_too_cold_outranks_waiting_for_the_plan(self):
        it = _intent(_boiler(34.0), plan=PlanVerdict(hold=True))
        assert it.on and it.code == RC.LOAD_COMFORT_FLOOR

    def test_sun_still_heats_up_to_keep_at_plus_extra(self):
        assert _intent(_boiler(53.0), remaining_surplus_w=4000.0).on
        it = _intent(_boiler(55.5, active=True), remaining_surplus_w=4000.0)
        assert not it.on and it.code == RC.LOAD_STOP_CONDITION   # banked at 55


@pytest.mark.unit
class TestTheBandLeadsTheRunTime:
    def test_scenario_2_a_hot_tank_is_not_heated_for_its_minutes(self):
        dev = _boiler(52.0, runtime_min=60)
        assert dev.has_runtime_deficit      # the old engine's input is unchanged
        it = _intent(dev, price_is_cheap=True, is_night=True)
        assert not it.on

    def test_a_load_without_a_band_keeps_its_run_time(self):
        dev = SwitchDevice(_hass(), "pump", "Pump", rated_power=800.0,
                           entity_id="switch.pump", daily_min_runtime_sec=3600)
        dev.control_mode = DeviceControlMode.SURPLUS
        dev.top_up_policy = "cheap_hours"
        it = _intent(dev, price_is_cheap=True, is_night=True)
        assert it.on and it.source == "cheap_grid"


@pytest.mark.unit
class TestLegionellaInLayerOne:
    def _hw(self, temp, *, active=False):
        from custom_components.solar_energy_management.devices.hot_water_controller import (
            HotWaterController,
        )
        hass = _hass(sensor__tank=temp)
        dev = HotWaterController(hass=hass, entity_id="switch.boiler",
                                 temperature_entity_id=TANK, solar_target_temp=55.0,
                                 rated_power=3000.0)
        dev.control_mode = DeviceControlMode.SURPLUS
        if active:
            dev._status.state = DeviceState.ACTIVE
        return dev

    def test_a_due_run_starts_in_layer_one_and_names_itself(self):
        dev = self._hw(45.0)
        dev._legionella_cycle_active = True
        it = _intent(dev)
        assert it.on and it.code == RC.LOAD_LEGIONELLA

    def test_sems_own_target_does_not_stop_the_run(self):
        dev = self._hw(57.0, active=True)    # above the 55 °C solar target
        dev._legionella_cycle_active = True
        it = _intent(dev)
        assert it.on and it.code == RC.LOAD_LEGIONELLA

    def test_where_the_ladder_leads_the_cycle_does_not_switch(self):
        dev = self._hw(45.0)
        dev.activate = AsyncMock(return_value=3000.0)
        dev.deactivate = AsyncMock()
        assert asyncio.run(dev.check_legionella_cycle(switch=False)) == "legionella_started"
        assert dev._legionella_cycle_active is True
        dev.activate.assert_not_called()


@pytest.mark.unit
class TestThePlanAsksForKeepAt:
    def test_goal_asks_below_keep_at_and_nothing_at_it(self):
        ask = _boiler(45.0).comfort_plan_demand(None, goal=True)
        assert ask and ask["energy_kwh"] == pytest.approx(3.0)   # no learned rate: 1 h at 3 kW
        assert _boiler(51.0).comfort_plan_demand(None, goal=True) is None

    def test_without_goal_the_old_drift_ask_is_unchanged(self):
        assert _boiler(45.0).comfort_plan_demand(None) is None   # no drift model learned yet

    def test_the_ladder_leads_only_where_the_layers_switch(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _band_engaged, _ladder_leads,
        )
        assert _ladder_leads(SimpleNamespace(_observer_mode=True, _surplus_controller=None))
        assert _ladder_leads(SimpleNamespace(_observer_mode=False,
                                             _surplus_controller=SimpleNamespace(_use_desired_state=True)))
        assert not _ladder_leads(SimpleNamespace(_observer_mode=False,
                                                 _surplus_controller=SimpleNamespace(_use_desired_state=False)))
        assert not _ladder_leads(MagicMock())
        assert _band_engaged(_boiler(45.0)) and not _band_engaged(SimpleNamespace())


@pytest.mark.unit
def test_layer_two_remembers_a_floor_run_and_a_dry_walk_puts_it_back():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    dev = _boiler(34.0)
    sc = SurplusController(dev.hass)
    sc.register_device(dev)
    kw = dict(remaining_surplus=0.0, reclaim_w=0.0, battery_priority=None, price_level=None,
              peak_freeze=False, peak_shed=False, peak_shed_all=False)
    sc._desired_intents([dev], dry=True, **kw)
    assert getattr(dev, "_comfort_floor_run", False) is False
    intents = sc._desired_intents([dev], **kw)
    assert intents["boiler"].code == RC.LOAD_COMFORT_FLOOR
    assert dev._comfort_floor_run is True
