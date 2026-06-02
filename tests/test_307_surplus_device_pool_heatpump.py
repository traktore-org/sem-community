"""Pins the #307 surplus-controlled non-EV device contract.

The original request (#307, closed as supported):

> I want to heat my swimming only when there is surplus solar.
> Functionality like the EV part, but more simple (there is no soc),
> but I know the power usage and can switch my heatpump and pool
> pump (which needs to be on when heating)

SEM already supports this via ``SurplusController`` +
``SwitchDevice`` (basic on/off pool pump) +
``HeatPumpController`` (setpoint-driven heat pump with SG-Ready).
This file pins the *contract* — surplus dispatch to a non-EV
device must:

  1. Activate when surplus >= min_power_threshold (and device is in
     SURPLUS control mode).
  2. Deactivate when surplus drops below min_power_threshold +
     anti-flicker windows allow.
  3. Respect priority order — a higher-priority EV charger gets
     budget first; the heat pump only sees the remainder.
  4. Stay OFF when control_mode = OFF (user explicitly disabled it).
  5. Stay OFF in PEAK_ONLY mode (never proactively activate; only
     respond to peak-shaving demands from the load manager).

This is the regression guard for #307. If a future arch change
silently routes the surplus differently, or if SurplusController
forgets non-EV devices, the tests fail.

(Note: the dependency-on/depends_on feature for pool-pump-must-be-
on-before-heat-pump is tested separately in
``tests/test_devices.py::TestDependsOn``. This file pins the
single-device contract.)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    SwitchDevice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass() -> MagicMock:
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    return h


def _heat_pump(
    hass,
    *,
    name: str = "Pool Heat Pump",
    rated_power: float = 3000,
    min_threshold: float = 2500,
    priority: int = 5,
    min_on_time: int = 0,
    min_off_time: int = 0,
    control_mode: DeviceControlMode = DeviceControlMode.SURPLUS,
) -> SwitchDevice:
    """A pool heat pump as a basic SwitchDevice.

    Real installs would use ``HeatPumpController`` for SG-Ready / setpoint
    control; the surplus dispatch contract is the same — what we're
    pinning here is that ANY ``ControllableDevice`` participates in
    the surplus cascade.
    """
    dev = SwitchDevice(
        hass=hass,
        device_id="pool_heat_pump",
        name=name,
        rated_power=rated_power,
        priority=priority,
        min_power_threshold=min_threshold,
        entity_id="switch.pool_heat_pump",
        min_on_time=min_on_time,
        min_off_time=min_off_time,
    )
    dev.control_mode = control_mode
    return dev


# ---------------------------------------------------------------------------
# Activation contract
# ---------------------------------------------------------------------------


class Test307HeatPumpActivation:
    @pytest.mark.asyncio
    async def test_activates_when_surplus_clears_threshold(self) -> None:
        """Surplus 3500 W; heat pump min threshold 2500 W; activates."""
        hass = _make_hass()
        controller = SurplusController(hass)
        pump = _heat_pump(hass)
        controller.register_device(pump)

        # First call seeds the EMA at the input value.
        await controller.update(available_power_w=3500)
        assert pump.is_active is True
        # turn_on service called on the heat pump's entity.
        call_args = hass.services.async_call.call_args
        assert call_args.args[0] == "homeassistant"
        assert call_args.args[1] == "turn_on"
        assert call_args.args[2] == {"entity_id": "switch.pool_heat_pump"}

    @pytest.mark.asyncio
    async def test_does_not_activate_below_threshold(self) -> None:
        """Surplus 1500 W; heat pump min threshold 2500 W; stays idle."""
        hass = _make_hass()
        controller = SurplusController(hass)
        pump = _heat_pump(hass)
        controller.register_device(pump)

        await controller.update(available_power_w=1500)
        assert pump.is_active is False
        # No turn_on call.
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_activate_when_control_mode_off(self) -> None:
        """User explicitly disabled this device — even abundant surplus
        must not turn it on."""
        hass = _make_hass()
        controller = SurplusController(hass)
        pump = _heat_pump(hass, control_mode=DeviceControlMode.OFF)
        controller.register_device(pump)

        await controller.update(available_power_w=5000)
        assert pump.is_active is False
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_activate_in_peak_only_mode(self) -> None:
        """PEAK_ONLY devices respond to peak shaving but never proactive
        surplus activation (the "load-shed only" intent)."""
        hass = _make_hass()
        controller = SurplusController(hass)
        pump = _heat_pump(hass, control_mode=DeviceControlMode.PEAK_ONLY)
        controller.register_device(pump)

        await controller.update(available_power_w=5000)
        assert pump.is_active is False


# ---------------------------------------------------------------------------
# Deactivation contract
# ---------------------------------------------------------------------------


class Test307HeatPumpDeactivation:
    @pytest.mark.asyncio
    async def test_deactivates_when_surplus_disappears(self) -> None:
        """Already active heat pump + surplus goes negative (cloud
        rolls in) → deactivate. Anti-flicker windows set to 0 for
        the test."""
        hass = _make_hass()
        controller = SurplusController(hass)
        pump = _heat_pump(hass, min_on_time=0, min_off_time=0)
        controller.register_device(pump)

        # Step 1: surplus, activate
        await controller.update(available_power_w=4000)
        assert pump.is_active is True

        # Step 2: surplus drops sharply; EMA smooths slowly so we
        # need multiple cycles for the controller to "see" the drop.
        # Drive it past the threshold over a few cycles.
        for _ in range(20):
            await controller.update(available_power_w=-3000)
        assert pump.is_active is False


# ---------------------------------------------------------------------------
# Priority cascade
# ---------------------------------------------------------------------------


class Test307PriorityCascade:
    @pytest.mark.asyncio
    async def test_higher_priority_eats_budget_first(self) -> None:
        """Two surplus devices; the lower-priority one only gets the
        cascade remainder. Pins the contract that the heat pump
        respects an existing higher-priority load."""
        hass = _make_hass()
        controller = SurplusController(hass)
        # Hot water (priority 2 = higher), 2 kW, threshold 1.5 kW
        hot_water = SwitchDevice(
            hass=hass, device_id="hot_water", name="Hot Water",
            rated_power=2000, priority=2,
            min_power_threshold=1500,
            entity_id="switch.hot_water",
            min_on_time=0, min_off_time=0,
        )
        hot_water.control_mode = DeviceControlMode.SURPLUS
        # Heat pump (priority 5 = lower), 3 kW, threshold 2.5 kW
        pump = _heat_pump(hass)
        controller.register_device(hot_water)
        controller.register_device(pump)

        # Surplus 3000 W: hot water claims 2000 → 1000 W left → pump
        # below its 2500 threshold → pump stays idle.
        await controller.update(available_power_w=3000)
        assert hot_water.is_active is True
        assert pump.is_active is False

    @pytest.mark.asyncio
    async def test_both_activate_when_budget_exceeds_both_thresholds(self) -> None:
        """Big surplus → both devices fit, both activate."""
        hass = _make_hass()
        controller = SurplusController(hass)
        hot_water = SwitchDevice(
            hass=hass, device_id="hot_water", name="Hot Water",
            rated_power=2000, priority=2,
            min_power_threshold=1500,
            entity_id="switch.hot_water",
            min_on_time=0, min_off_time=0,
        )
        hot_water.control_mode = DeviceControlMode.SURPLUS
        pump = _heat_pump(hass)
        controller.register_device(hot_water)
        controller.register_device(pump)

        # Surplus 6000 W: hot water 2000 + pump 3000 = 5000 → both fit.
        await controller.update(available_power_w=6000)
        assert hot_water.is_active is True
        assert pump.is_active is True
