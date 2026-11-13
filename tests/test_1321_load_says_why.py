"""#1321 — every load publishes what the load engine decided for it now.

Discussion 1059: a tank at 45.8 °C under Keep at 52 sat off and nothing told
the user why, or what would make SEM heat. Outside observer mode SEM
published no per-load reason at all — only the log of changes. Layer 1's
intent (on / source / reason code) now rides each device row the cards read,
with the band's own lines, so the card can say it in words.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.plan_verdict import PlanVerdict
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    LoadIntent,
    SurplusController,
    intent_record,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    SwitchDevice,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import _Hass

TANK = "sensor.tank"
BLOCK = {"boiler": PlanVerdict(in_block=True, comfort_in_block=True, reason="planned block")}


def _boiler(hass, temp="45.8", *, band=True, grid=False):
    hass.set("switch.boiler", "off")
    hass.set(TANK, temp, unit_of_measurement="°C")
    dev = SwitchDevice(hass, "boiler", "Boiler", rated_power=3000.0, entity_id="switch.boiler")
    dev.control_mode = DeviceControlMode.SURPLUS
    if band:
        dev.comfort_entity, dev.comfort_target = TANK, 52.0
        dev.comfort_offset, dev.comfort_limit = 4.0, 36.0
    # (#1102) a Keep at run is bought only with the grid allowed
    dev.top_up_policy = "cheap_hours" if grid else "solar_only"
    dev.min_on_seconds = dev.min_off_seconds = 0
    dev.min_on_time = dev.min_off_time = 0
    return dev


def _controller(hass, *devs):
    sc = SurplusController(hass)
    for d in devs:
        sc.register_device(d)
    return sc


def _registry(sc, goals=None):
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg._device_goals = goals or {}
    reg._surplus_controller = sc
    return reg


@pytest.mark.unit
class TestTheRecordIsTinyAndCarriesNoProse:
    def test_a_coded_intent(self):
        rec = intent_record(LoadIntent(False, 0.0, None, "no source available", RC.LOAD_NO_SOURCE))
        assert rec == {"on": False, "source": None, "code": "no_source"}

    def test_an_intent_without_a_code_is_named_by_its_source(self):
        rec = intent_record(LoadIntent(True, 3000.0, "solar", "solar: 4000W ≥ 3000W"))
        assert rec == {"on": True, "source": "solar", "code": "solar"}

    def test_the_reason_text_never_rides_along(self):
        rec = intent_record(LoadIntent(True, 3000.0, "cheap_grid",
                                       "a long sentence " * 20, RC.LOAD_COMFORT_GOAL))
        assert len(json.dumps(rec)) < 80
        assert "sentence" not in json.dumps(rec)

    def test_a_step_down_says_so(self):
        rec = intent_record(LoadIntent(True, 900.0, "solar", "x", RC.LOAD_STEP_DOWN_PRICE,
                                       step_down=True))
        assert rec["step_down"] is True


@pytest.mark.asyncio
class TestEveryCycleSaysWhatEachLoadIsToDo:
    async def test_there_is_none_before_the_first_cycle(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        assert sc.load_intent("boiler") is None

    async def test_a_cold_tank_with_no_block_is_off_and_says_why(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        await sc.update(0.0, price_level="normal", is_night=True)
        assert sc.load_intent("boiler") == {"on": False, "source": None, "code": RC.LOAD_NO_SOURCE}

    async def test_the_record_is_replaced_not_appended(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass, grid=True))
        await sc.update(0.0, price_level="normal", is_night=True)
        await sc.update(0.0, price_level="normal", is_night=True, plan_windows=BLOCK)
        assert sc.load_intent("boiler") == {
            "on": True, "source": "cheap_grid", "code": RC.LOAD_COMFORT_GOAL}
        assert list(sc._intent_roster) == ["boiler"]

    async def test_a_removed_load_leaves_the_roster(self):
        hass = _Hass()
        other = SwitchDevice(hass, "pump", "Pump", rated_power=500.0, entity_id="switch.pump")
        other.control_mode = DeviceControlMode.SURPLUS
        hass.set("switch.pump", "off")
        sc = _controller(hass, _boiler(hass), other)
        await sc.update(0.0, price_level="normal", is_night=True)
        assert set(sc._intent_roster) == {"boiler", "pump"}
        sc.unregister_device("pump")
        await sc.update(0.0, price_level="normal", is_night=True)
        assert set(sc._intent_roster) == {"boiler"}
        assert sc.load_intent("pump") is None

    async def test_observer_mode_says_the_same_as_a_real_install(self):
        said = []
        for observer in (False, True):
            hass = _Hass()
            sc = _controller(hass, _boiler(hass, grid=True))
            await sc.update(0.0, price_level="normal", is_night=True,
                            plan_windows=BLOCK, observer=observer)
            said.append(sc.load_intent("boiler"))
            assert bool(hass.calls("turn_on")) is (not observer)
        assert said[0] == said[1]

    async def test_the_caller_gets_a_copy(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        await sc.update(0.0, price_level="normal", is_night=True)
        sc.load_intent("boiler")["code"] = "changed"
        assert sc.load_intent("boiler")["code"] == RC.LOAD_NO_SOURCE


@pytest.mark.asyncio
class TestTheDeviceRowCarriesIt:
    async def test_the_intent_rides_beside_the_goals(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        await sc.update(0.0, price_level="normal", is_night=True)
        row = _registry(sc)._goal_payload("boiler")
        assert row["intent"] == {"on": False, "source": None, "code": RC.LOAD_NO_SOURCE}

    async def test_no_cycle_yet_publishes_no_intent(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        assert "intent" not in _registry(sc)._goal_payload("boiler")

    async def test_the_band_lines_are_the_engines_own(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = _controller(hass, dev)
        c = _registry(sc)._goal_payload("boiler")["comfort"]
        assert c["reading_c"] == pytest.approx(45.8)
        assert (c["keep_c"], c["max_c"], c["limit_c"]) == (52.0, 56.0, 36.0)
        # the line a planned run starts under is the device's own gap
        assert c["start_c"] == pytest.approx(52.0 - dev.comfort_goal_start_gap_c())
        assert c["own_run"] is False
        assert c["state"] == "willing" and c["hvac"] == "heat"

    async def test_a_narrow_band_publishes_its_narrower_gap(self):
        hass = _Hass()
        dev = _boiler(hass)
        dev.comfort_limit = 51.0            # band of 1 °C → gap 0.5 °C
        sc = _controller(hass, dev)
        assert _registry(sc)._goal_payload("boiler")["comfort"]["start_c"] == pytest.approx(51.5)

    async def test_a_load_without_a_band_has_no_lines(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass, band=False))
        c = _registry(sc)._goal_payload("boiler").get("comfort", {})
        assert not ({"keep_c", "start_c", "max_c", "limit_c", "own_run"} & set(c))

    async def test_a_controller_without_the_roster_breaks_nothing(self):
        hass = _Hass()
        dev = _boiler(hass)
        ctrl = MagicMock()
        ctrl.get_device.return_value = dev
        assert "intent" not in _registry(ctrl)._goal_payload("boiler")
        ctrl.load_intent.side_effect = RuntimeError("boom")
        assert "intent" not in _registry(ctrl)._goal_payload("boiler")


@pytest.mark.unit
class TestItStaysOutOfTheRecorder:
    def test_the_devices_map_is_unrecorded(self):
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        assert "devices" in SEMSolarSensor._unrecorded_attributes

    def test_the_registry_asks_the_controller_and_writes_nothing(self):
        from .ast_contracts import calls
        assert calls(UnifiedDeviceRegistry._intent_payload, "load_intent") or \
            calls(UnifiedDeviceRegistry._intent_payload, "ask")


@pytest.mark.asyncio
class TestTheRowSaysWhetherKeepAtMayBeBought:
    """(#1102) Solar only is solar only: the card must not promise a planned
    hour to a load that buys nothing."""

    async def test_solar_only_publishes_may_buy_false(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        assert _registry(sc)._goal_payload("boiler")["comfort"]["may_buy"] is False

    async def test_grid_allowed_publishes_may_buy_true(self):
        hass = _Hass()
        dev = _boiler(hass)
        dev.top_up_policy = "cheap_hours"
        sc = _controller(hass, dev)
        assert _registry(sc)._goal_payload("boiler")["comfort"]["may_buy"] is True

    async def test_it_is_the_devices_own_rule(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = _controller(hass, dev)
        for policy in ("solar_only", "cheap_hours"):
            dev.top_up_policy = policy
            assert (_registry(sc)._goal_payload("boiler")["comfort"]["may_buy"]
                    is dev.comfort_goal_may_buy())

    async def test_a_device_without_the_rule_buys_nothing(self):
        assert UnifiedDeviceRegistry._may_buy(object()) is False


@pytest.mark.asyncio
class TestTheRowSaysWhetherTheBatteryMayReachKeepAt:
    """(#1349) "Finish overnight from: Battery" on a heater whose thermometer
    leads: the row carries the device's own answer, so the card can say
    "heats tonight from the battery"."""

    async def test_the_battery_choice_is_published(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = _controller(hass, dev)
        assert _registry(sc)._goal_payload("boiler")["comfort"]["may_use_battery"] is False
        dev.battery_eligible_overnight = True
        comfort = _registry(sc)._goal_payload("boiler")["comfort"]
        assert comfort["may_use_battery"] is True
        # the battery is not buying: the grid rule stays its own answer
        assert comfort["may_buy"] is False

    async def test_a_device_without_the_rule_takes_nothing(self):
        assert UnifiedDeviceRegistry._may_use_battery(object()) is False


@pytest.mark.asyncio
class TestTheRowSaysWhenTheBandRidesTheUnitsOwnSetpoint:
    """(#705/#1349) A climate unit's band is anchored on its live setpoint:
    typed Keep 23 / limit 27 with the thermostat at 24 means SEM uses 24 / 28.
    The row carries the lines SEM uses and says they are anchored, so the
    card shows those and not the typed numbers."""

    def _unit(self, hass, setpoint):
        from custom_components.solar_energy_management.devices.base import ClimateDevice
        attrs = {"hvac_modes": ["off", "cool"], "current_temperature": 26.0}
        if setpoint is not None:
            attrs["temperature"] = setpoint
        hass.set("climate.ac", "off", **attrs)
        dev = ClimateDevice(hass, "ac", "AC", rated_power=1000.0,
                            entity_id="climate.ac", hvac_mode="cool")
        dev.control_mode = DeviceControlMode.SURPLUS
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 23.0, 2.0, 27.0
        return dev

    async def test_an_anchored_unit_publishes_the_lines_sem_uses(self):
        hass = _Hass()
        sc = _controller(hass, self._unit(hass, 24.0))
        c = _registry(sc)._goal_payload("ac")["comfort"]
        assert c["anchored"] is True
        assert (c["keep_c"], c["limit_c"], c["max_c"], c["start_c"]) == (24.0, 28.0, 22.0, 25.0)

    async def test_without_a_live_setpoint_the_typed_values_are_the_lines(self):
        hass = _Hass()
        sc = _controller(hass, self._unit(hass, None))
        c = _registry(sc)._goal_payload("ac")["comfort"]
        assert c["anchored"] is False
        assert (c["keep_c"], c["limit_c"], c["max_c"]) == (23.0, 27.0, 21.0)

    async def test_a_plain_heater_is_never_anchored(self):
        hass = _Hass()
        sc = _controller(hass, _boiler(hass))
        assert _registry(sc)._goal_payload("boiler")["comfort"]["anchored"] is False
