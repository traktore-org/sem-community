"""Multi-cycle scenarios for SurplusController load management.

The unit tests in ``tests/test_surplus_controller.py`` and
``tests/test_307_surplus_device_pool_heatpump.py`` cover
single-cycle dispatch decisions: "given surplus X and device state Y,
does the controller activate/deactivate correctly?"

What those miss is the **multi-cycle behaviour**: how the
controller's EMA smoothing, anti-flicker windows, and priority
cascade behave when surplus walks through realistic patterns
(cloud transients, ramp-up, hot-water saturating, etc.). This file
pins those time-series contracts.

Scenarios in this file (all multi-cycle):

  * **Cloud-transient survival** — surplus dips below the device
    threshold for ONE cycle, comes back. Anti-flicker (EMA + the
    device's ``min_off_time``) prevents the toggle.
  * **Priority cascade with consumption growth** — multiple
    devices, surplus grows then shrinks. Lower priority devices
    deactivate first (LIFO).
  * **Saturating load** — surplus exceeds combined max; only N
    devices activate, rest stay idle.
  * **Surplus drops below ALL device thresholds** — all
    deactivate in priority order (LIFO).

These exercise the SAME failure modes the YAML scenario harness
catches for EV strategy, but at the load-management layer.
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


def _hass() -> MagicMock:
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    return h


def _switch(
    hass, *, device_id: str, name: str, rated_power: float,
    min_threshold: float = None, priority: int = 5,
    min_on_time: int = 0, min_off_time: int = 0,
    control_mode: DeviceControlMode = DeviceControlMode.SURPLUS,
) -> SwitchDevice:
    if min_threshold is None:
        min_threshold = rated_power
    dev = SwitchDevice(
        hass=hass, device_id=device_id, name=name,
        rated_power=rated_power, priority=priority,
        min_power_threshold=min_threshold,
        entity_id=f"switch.{device_id}",
        min_on_time=min_on_time, min_off_time=min_off_time,
    )
    dev.control_mode = control_mode
    return dev


# ---------------------------------------------------------------------------
# Scenario 1 — cloud transient (one-cycle dip)
# ---------------------------------------------------------------------------


class TestCloudTransientSurvival:
    """Surplus drops below threshold for ONE cycle (a cloud passes),
    then recovers. The EMA smoothing + device anti-flicker windows
    must prevent a spurious deactivate→activate toggle.
    """

    @pytest.mark.asyncio
    async def test_one_cycle_dip_does_not_deactivate(self) -> None:
        """3 kW heat pump, threshold 2.5 kW. Surplus runs at 4 kW for
        a few cycles (heat pump on), drops to 1 kW for one cycle
        (cloud), back to 4 kW. EMA smoothing keeps the smoothed
        surplus above threshold so the device stays on through the
        dip."""
        hass = _hass()
        controller = SurplusController(hass)
        pump = _switch(hass, device_id="pool", name="Pool Pump",
                       rated_power=3000, min_threshold=2500,
                       min_on_time=120, min_off_time=60)
        controller.register_device(pump)

        # Settle in active state
        await controller.update(available_power_w=4000)
        await controller.update(available_power_w=4000)
        await controller.update(available_power_w=4000)
        assert pump.is_active, "should be active after 3 cycles of surplus"

        # One-cycle cloud transient
        await controller.update(available_power_w=1000)
        # EMA: 0.3*1000 + 0.7*<previous smoothed> — previous was
        # ≈4000 → new smoothed ≈ 0.3*1000 + 0.7*4000 = 3100W.
        # 3100 > 2500 (threshold) so anti-flicker still active.
        # Plus min_on_time=120s = at least 4 cycles before deactivate
        # can fire.
        assert pump.is_active, "one-cycle cloud must NOT toggle the device off"

    @pytest.mark.asyncio
    async def test_sustained_drop_eventually_deactivates(self) -> None:
        """The complement: if surplus stays low for many cycles, the
        EMA decays and the device DOES deactivate. Min_on_time honored."""
        hass = _hass()
        controller = SurplusController(hass)
        pump = _switch(hass, device_id="pool", name="Pool Pump",
                       rated_power=3000, min_threshold=2500,
                       min_on_time=0, min_off_time=0)
        controller.register_device(pump)

        # Activate
        await controller.update(available_power_w=4000)
        assert pump.is_active

        # Long sustained low. EMA decays geometrically toward 0.
        for _ in range(20):
            await controller.update(available_power_w=-2000)
        assert not pump.is_active, "sustained low surplus must deactivate"


# ---------------------------------------------------------------------------
# Scenario 2 — priority cascade with consumption growth
# ---------------------------------------------------------------------------


class TestPriorityCascadeWithGrowth:
    """Two devices, different priorities. Surplus grows from below
    both thresholds → above the higher one → above both → back down.
    Verifies the priority cascade respects the order."""

    @pytest.mark.asyncio
    async def test_higher_priority_activates_first(self) -> None:
        hass = _hass()
        controller = SurplusController(hass)
        hot_water = _switch(hass, device_id="hot_water",
                            name="Hot Water", rated_power=2000,
                            min_threshold=1500, priority=2,
                            min_on_time=0, min_off_time=0)
        pump = _switch(hass, device_id="pool", name="Pool Pump",
                       rated_power=3000, min_threshold=2500,
                       priority=5, min_on_time=0, min_off_time=0)
        controller.register_device(pump)
        controller.register_device(hot_water)

        # Surplus 1000W — both below threshold
        await controller.update(available_power_w=1000)
        assert not hot_water.is_active
        assert not pump.is_active

        # Surplus 3000W — well above hot_water threshold (1500) AND
        # above hot_water rated_power (2000), so activation doesn't
        # trigger immediate deactivation. Wait for EMA to settle.
        for _ in range(6):
            await controller.update(available_power_w=3000)
        assert hot_water.is_active
        assert not pump.is_active, (
            "pump threshold (2500) not met by remaining surplus (3000-2000=1000)"
        )

        # Surplus 8000W — both fit (hot water 2000 + pump 3000 = 5000)
        for _ in range(6):
            await controller.update(available_power_w=8000)
        assert hot_water.is_active
        assert pump.is_active

    @pytest.mark.asyncio
    async def test_deactivation_is_lifo_lowest_priority_first(self) -> None:
        """When surplus drops, lower-priority devices deactivate first.
        Hot water (priority 2) stays on while pump (priority 5) drops
        as the budget tightens."""
        hass = _hass()
        controller = SurplusController(hass)
        hot_water = _switch(hass, device_id="hot_water",
                            name="Hot Water", rated_power=2000,
                            min_threshold=1500, priority=2,
                            min_on_time=0, min_off_time=0)
        pump = _switch(hass, device_id="pool", name="Pool Pump",
                       rated_power=3000, min_threshold=2500,
                       priority=5, min_on_time=0, min_off_time=0)
        controller.register_device(pump)
        controller.register_device(hot_water)

        # Both active
        for _ in range(3):
            await controller.update(available_power_w=6000)
        assert hot_water.is_active and pump.is_active

        # Drop: surplus enough for hot water alone but not pump
        for _ in range(20):
            await controller.update(available_power_w=-1500)
        # After many cycles of negative surplus, both should be off
        # (the negative surplus is "consume from grid" — turn off
        # everything controllable).
        assert not pump.is_active, "pump (lower priority) deactivates"


# ---------------------------------------------------------------------------
# Scenario 3 — saturating load (more devices than surplus)
# ---------------------------------------------------------------------------


class TestSaturatingLoad:
    """Surplus enough for SOME but not ALL devices. Higher-priority
    devices claim the budget, lower-priority ones stay idle."""

    @pytest.mark.asyncio
    async def test_three_devices_only_two_fit(self) -> None:
        hass = _hass()
        controller = SurplusController(hass)
        # 3 devices, total need 6500 W, surplus only 4500 W
        d1 = _switch(hass, device_id="d1", name="Device 1",
                     rated_power=2000, min_threshold=1500, priority=1,
                     min_on_time=0, min_off_time=0)
        d2 = _switch(hass, device_id="d2", name="Device 2",
                     rated_power=2000, min_threshold=1500, priority=2,
                     min_on_time=0, min_off_time=0)
        # Priority 3 has a 5000W threshold — well above any remaining
        # surplus after d1+d2 activate. Guarantees d3 stays idle.
        d3 = _switch(hass, device_id="d3", name="Device 3",
                     rated_power=5000, min_threshold=5000, priority=3,
                     min_on_time=0, min_off_time=0)
        controller.register_device(d3)  # registration order shouldn't matter
        controller.register_device(d1)
        controller.register_device(d2)

        # Since #508 W7 the coordinator passes the FEEDBACK-FREE pool:
        # grid export PLUS the controller's own active draw (add-back), so
        # the input does NOT shrink as devices activate. Steady state here
        # is 2000W residual export + 4000W active draw = 6000W. (This test
        # used to feed the pre-W7 netted value, 2000W — the old delta-only
        # debit made the two contracts indistinguishable for running
        # switches; the #688 full debit follows the real W7 contract.)
        await controller.update(available_power_w=6000)  # d1+d2 activate
        for _ in range(6):
            await controller.update(available_power_w=6000)

        assert d1.is_active
        assert d2.is_active
        # d3 (threshold 5000): after the walk debits d1+d2's 4000W from the
        # 5950W distributable, 1950W remain → below threshold → stays idle.
        assert not d3.is_active, "priority 3 stays idle when budget exhausted"


# ---------------------------------------------------------------------------
# Scenario 4 — all-deactivate on cold spell
# ---------------------------------------------------------------------------


class TestAllDeactivateOnColdSpell:
    """Surplus drops below ALL device thresholds. Everything turns
    off, in priority order (lowest first)."""

    @pytest.mark.asyncio
    async def test_all_devices_deactivate_when_surplus_vanishes(self) -> None:
        hass = _hass()
        controller = SurplusController(hass)
        d1 = _switch(hass, device_id="d1", name="Device 1",
                     rated_power=2000, min_threshold=1500, priority=1,
                     min_on_time=0, min_off_time=0)
        d2 = _switch(hass, device_id="d2", name="Device 2",
                     rated_power=2500, min_threshold=2000, priority=2,
                     min_on_time=0, min_off_time=0)
        controller.register_device(d1)
        controller.register_device(d2)

        # Both active
        for _ in range(3):
            await controller.update(available_power_w=6000)
        assert d1.is_active and d2.is_active

        # Long cold spell — negative surplus (importing from grid)
        for _ in range(30):
            await controller.update(available_power_w=-3000)

        assert not d1.is_active and not d2.is_active, (
            "all controllable devices deactivate on sustained no-surplus"
        )
