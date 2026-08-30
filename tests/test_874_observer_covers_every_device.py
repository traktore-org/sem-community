"""Observer mode must cover EVERY device that can be commanded, not chargers.

Found by an independent review of the v2.0.0..develop diff (30.08.2026),
CONFIRMED high severity, and it is the kind of gap that matters most on
THIS project: `.46` and `.175` run observer mode ON while wired to real
hardware, so "observer is on" is the entire basis for trusting that a test
rig cannot touch somebody's house.

Two separate defects in one handler, both in `update_device_control_mode`
(features/device_registry.py), which a live HA service can reach:

1. **The observer flag never reaches non-EV devices.** `deactivate()` writes
   through `ControllableDevice.send()`, which withholds only when
   `self.observer_mode` is True — and the only two places in the entire
   package that set it (`coordinator._push_observer_mode_to_devices` and
   `actuate._observe`) walk EV chargers alone. A SwitchDevice, ClimateDevice
   or heat-pump controller keeps the documented default of False, so setting
   its Mode to Off on an observer rig switches off REAL hardware. The
   per-cycle path is protected one layer up by `reconcile_load(observer=...)`;
   this one-shot handler skips that layer and lands straight on the seam.

2. **The anti-flicker release clears the wrong attribute.** The handler sets
   `_status.last_activated = None`, while `SwitchDevice.deactivate()` and
   `ClimateDevice.deactivate()` gate on `self._last_activated` — the "#644
   unified clock", a different attribute entirely. The comment says "a
   deliberate command beats flicker protection"; the code does not do that,
   so a Mode→Off inside `min_on_seconds` (default 300 s) returns silently and
   the load stays on, with no error and no log.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.devices.base import SwitchDevice


def _switch(**kw):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    defaults = dict(hass=hass, device_id="pool_pump", name="Pool Pump",
                    entity_id="switch.pool_pump", rated_power=1500.0)
    defaults.update(kw)
    return SwitchDevice(**defaults)


class TestTheFlagReachesEveryDevice:
    """The push is what makes ``send()`` withhold. A device it skips is a
    device that acts."""

    def test_a_load_is_told_about_observer_mode(self):
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._observer_mode = True
        coord._ev_devices = {}
        coord._ev_device = None
        load = _switch()
        coord._surplus_controller = SimpleNamespace(_devices={"pool_pump": load})

        SEMCoordinator._push_observer_mode_to_devices(coord)

        assert load.observer_mode is True, (
            "a non-EV load never learns observer mode is on, so its deactivate "
            "writes straight through to real hardware on a rig that believes "
            "it is only watching"
        )

    def test_turning_observer_off_reaches_them_too(self):
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._observer_mode = False
        coord._ev_devices = {}
        coord._ev_device = None
        load = _switch()
        load.observer_mode = True
        coord._surplus_controller = SimpleNamespace(_devices={"pool_pump": load})

        SEMCoordinator._push_observer_mode_to_devices(coord)
        assert load.observer_mode is False, "a stale True would mute a live install"

    def test_chargers_are_still_covered(self):
        """The original behaviour must survive the widening."""
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._observer_mode = True
        charger = _switch(device_id="keba", entity_id="switch.keba")
        coord._ev_devices = {"keba": charger}
        coord._ev_device = None
        coord._surplus_controller = None
        SEMCoordinator._push_observer_mode_to_devices(coord)
        assert charger.observer_mode is True

    def test_a_missing_surplus_controller_is_survivable(self):
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._observer_mode = True
        coord._ev_devices = {}
        coord._ev_device = None
        # no _surplus_controller attribute at all
        SEMCoordinator._push_observer_mode_to_devices(coord)


class TestObserverActuallyWithholdsALoadStop:
    @pytest.mark.asyncio
    async def test_a_watched_load_is_not_switched_off(self):
        load = _switch()
        load.observer_mode = True
        load.withheld_commands = []
        await load.deactivate()
        load.hass.services.async_call.assert_not_awaited(), (
            "observer mode let a real turn_off reach the house"
        )
        assert load.withheld_commands, "…and it must say what it withheld"

    @pytest.mark.asyncio
    async def test_a_live_load_is_switched_off(self):
        load = _switch()
        load.observer_mode = False
        await load.deactivate()
        load.hass.services.async_call.assert_awaited()


class TestADeliberateOffBeatsFlickerProtection:
    """The handler's own comment, made true."""

    @pytest.mark.asyncio
    async def test_clearing_the_unified_clock_lets_the_stop_through(self):
        load = _switch()
        load.min_on_seconds = 300
        load.observer_mode = False
        load._last_activated = datetime.now() - timedelta(seconds=10)

        await load.deactivate()
        load.hass.services.async_call.assert_not_awaited(), (
            "precondition: inside min_on_seconds the flicker guard holds"
        )

        # what the Mode→Off handler must clear
        load._last_activated = None
        await load.deactivate()
        load.hass.services.async_call.assert_awaited(), (
            "clearing the clock the gate actually reads must release the stop"
        )

    @pytest.mark.asyncio
    async def test_clearing_the_status_field_alone_does_nothing(self):
        """The bug, pinned: this is what the handler used to clear."""
        load = _switch()
        load.min_on_seconds = 300
        load.observer_mode = False
        load._last_activated = datetime.now() - timedelta(seconds=10)
        load._status.last_activated = None

        await load.deactivate()
        load.hass.services.async_call.assert_not_awaited(), (
            "_status.last_activated is not the attribute deactivate() gates "
            "on — clearing it leaves the load stranded ON, silently"
        )
