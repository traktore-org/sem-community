"""#1135 — SG-Ready keeps its minimum run and pause, and the user sets both.

The report (#801, a Buderus over EMS-ESP): SG-Ready on 10 min, off 5 min,
again and again. Those are exactly the pump's windows (600 s / 300 s), so
the surplus path honours them — pinned below through the real controllers.
The two times are already on the card: the heat pump row's "Minimum run
time" / "Minimum pause time" (goals ``min_on_time_min`` /
``min_off_time_min``), applied to the live pump.

One stop pass skipped the run window: the end of a cheap-hours or battery
run called ``deactivate()`` without ``can_deactivate()``, trusting the
device to hold its own minimum run as a switch does. The heat pump's
SG-Ready stand-down does not, so the compressor stopped inside its run.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)


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


def _age(hp, *, on_s=None, off_s=None):
    if on_s is not None:
        hp._last_activated = datetime.now() - timedelta(seconds=on_s)
        hp._status.last_activated = hp._last_activated
    if off_s is not None:
        hp._last_deactivated = datetime.now() - timedelta(seconds=off_s)
        hp._status.last_deactivated = hp._last_deactivated


async def _cloud(sc, n=6):
    for _ in range(n):
        await sc.update(-3000.0)


async def _sun(sc, n=6):
    for _ in range(n):
        await sc.update(6000.0)


@pytest.mark.asyncio
class TestTheSurplusPathHoldsTheWindow:

    async def test_run_then_pause(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _sun(sc, 1)
        assert hp.is_active and hp.sg_ready_state is not SGReadyState.NORMAL
        _age(hp, on_s=540)                       # 9 min in
        await _cloud(sc)
        assert hp.is_active, "stopped inside the 10 min run"
        _age(hp, on_s=610)
        await _cloud(sc)
        assert not hp.is_active
        assert hp.sg_ready_state is SGReadyState.NORMAL
        _age(hp, off_s=240)                      # 4 min rest
        await _sun(sc)
        assert not hp.is_active, "started inside the 5 min pause"
        _age(hp, off_s=310)
        await _sun(sc, 1)
        assert hp.is_active

    async def test_the_users_times_reach_the_pump(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"heat_pump": {"min_on_time_min": 30,
                                           "min_off_time_min": 20}}
        reg._priority_overrides = {}
        reg._service_registrations = {}
        reg._control_mode_overrides = {}
        reg._user_control_modes = set()
        reg._surplus_controller = sc
        reg.priority_for = lambda did, seed=5: seed
        reg.refresh_direct_device_overrides()
        assert (hp.min_on_seconds, hp.min_off_seconds) == (1800, 1200)
        await _sun(sc, 1)
        _age(hp, on_s=25 * 60)
        await _cloud(sc)
        assert hp.is_active, "the 30 min run the user set did not hold"
        _age(hp, on_s=31 * 60)
        await _cloud(sc)
        assert not hp.is_active
        _age(hp, off_s=15 * 60)
        await _sun(sc)
        assert not hp.is_active, "the 20 min pause the user set did not hold"


@pytest.mark.asyncio
class TestEveryStopHoldsTheRun:

    async def _cheap_run(self, hass):
        sc, hp = _pump(hass)
        hp.top_up_policy = "cheap_hours"
        await _sun(sc, 1)
        assert hp.is_active
        hp._offpeak_forced = True
        hp._offpeak_forced_date = None
        hp.top_up_policy = "solar_only"   # the user turns cheap hours off
        return sc, hp

    async def test_the_end_of_a_cheap_run_waits_for_the_minimum_run(self):
        hass = _Hass()
        sc, hp = await self._cheap_run(hass)
        _age(hp, on_s=120)
        await sc.update(-3000.0, price_level="expensive")
        assert hp.is_active, "a cheap-hours end stopped the compressor 2 min in"
        assert hp.sg_ready_state is not SGReadyState.NORMAL

    async def test_and_ends_it_after(self):
        hass = _Hass()
        sc, hp = await self._cheap_run(hass)
        _age(hp, on_s=700)
        await sc.update(-3000.0, price_level="expensive")
        assert not hp.is_active
        assert hp.sg_ready_state is SGReadyState.NORMAL

    async def test_mode_off_still_stops_at_once(self):
        """The user's own Off beats the window, as on every other load."""
        hass = _Hass()
        sc, hp = _pump(hass)
        await _sun(sc, 1)
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
        assert hp.control_mode is DeviceControlMode.OFF
        # (#1335) the handler sets the mode; the refresh it asks for runs the
        # engine, whose layer 3 lets the user's Off beat the 10 min run
        assert hp.is_active
        await sc.update(6000.0)
        assert not hp.is_active
        assert hp.sg_ready_state is SGReadyState.NORMAL
