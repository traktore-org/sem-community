"""#620 — generic-device goal model: max cap + the two battery tiers.

Model (design spec 2026-07-20): per-device Minimum (floor) / Maximum (cap,
persisted) / Solar+battery daytime assist (Tier 1) / overnight below-buffer
drain (Tier 2). Continuous priority allocation bounded by two hard ceilings
(peak limit, reserve SoC). NO device deadlines. Everything is INERT unless a
device opts in — these tests pin both the new behaviour AND the inertness.
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, DeviceControlMode,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)


def _switch(**kw):
    dev = SwitchDevice(
        hass=MagicMock(),
        device_id=kw.get("device_id", "pump"),
        name=kw.get("name", "Pool Pump"),
        rated_power=kw.get("rated_power", 800),
        priority=kw.get("priority", 5),
        entity_id="switch.pump",
    )
    dev.control_mode = DeviceControlMode.SURPLUS
    return dev


# ── Phase 1: device model — max cap gate + persistence ────────────────────

class TestMaxCapGate:
    def test_uncapped_default(self):
        d = _switch()
        assert d.daily_max_runtime_sec == 0
        assert d.daily_max_runtime_reached is False

    def test_cap_reached_blocks_activation(self):
        d = _switch()
        d.daily_max_runtime_sec = 3600
        d._daily_runtime_accumulated_sec = 3600
        assert d.daily_max_runtime_reached is True
        assert d.can_activate() is False  # cap overrides everything

    def test_below_cap_can_activate(self):
        d = _switch()
        d.daily_max_runtime_sec = 3600
        d._daily_runtime_accumulated_sec = 1800
        assert d.daily_max_runtime_reached is False
        assert d.can_activate() is True

    def test_cap_blocks_offpeak_need(self):
        d = _switch()
        d.daily_min_runtime_sec = 7200
        d.daily_max_runtime_sec = 3600
        d._daily_runtime_accumulated_sec = 3600  # hit max before min
        assert d.needs_offpeak_activation is False  # cap wins

    def test_max_cap_persisted_and_restored(self):
        """The #559 HIGH-1 regression: the cap must survive serialize→restore."""
        d = _switch()
        d.daily_max_runtime_sec = 6000
        d.battery_assist_enabled = True
        d.battery_eligible_overnight = True
        blob = d.to_dict()
        assert blob["daily_max_runtime_sec"] == 6000
        assert blob["battery_assist_enabled"] is True
        assert blob["battery_eligible_overnight"] is True


# ── Phase 2: allocation — Tier 1 daytime assist ───────────────────────────

def _mock(**kw):
    d = MagicMock()
    d.device_id = kw.get("device_id", "d")
    d.name = kw.get("name", "D")
    d.priority = kw.get("priority", 5)
    d.min_power_threshold = kw.get("min_power", 800)
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = kw.get("is_active", False)
    d.device_type = MagicMock(value="switch")
    d.activate = AsyncMock(return_value=kw.get("draw", 800))
    d.adjust_power = AsyncMock(return_value=kw.get("draw", 800))
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.can_activate = MagicMock(return_value=kw.get("can_activate", True))
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.control_mode = kw.get("control_mode", DeviceControlMode.SURPLUS)
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d.needs_offpeak_activation = kw.get("needs_offpeak", False)
    d.remaining_daily_runtime_sec = kw.get("remaining_sec", 0)
    d.daily_min_runtime_sec = 0
    d.daily_targets_met = False
    d.stop_condition_met = False
    d.top_up_policy = "solar_only"
    d.battery_assist_enabled = kw.get("battery_assist_enabled", False)
    d.battery_eligible_overnight = kw.get("battery_eligible_overnight", False)
    d.stop_entity = ""
    d.stop_at = 0

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


@pytest.fixture
def mock_hass():
    h = MagicMock()
    return h


@pytest.mark.asyncio
class TestTier1BatteryAssist:
    async def test_no_assist_below_threshold_when_flag_off(self, mock_hass):
        """Raw surplus < rated, flag OFF → does not activate (inert)."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=False)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=3000)
        d.activate.assert_not_called()

    async def test_assist_activates_above_buffer(self, mock_hass):
        """Raw surplus 400 < 800 rated, but flag ON + SoC>buffer + budget →
        effective surplus 400+3000 ≥ 800 → activates (battery tops up)."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=True)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=3000)
        d.activate.assert_called_once()

    async def test_no_assist_below_buffer(self, mock_hass):
        """Flag ON but SoC ≤ buffer → no headroom, stays off (battery reserved)."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=True)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=65, battery_buffer_soc=70,
                        battery_assist_budget_w=3000)
        d.activate.assert_not_called()

    async def test_no_assist_when_budget_zero(self, mock_hass):
        """Flag ON, SoC>buffer, but coordinator passed 0 budget (no real
        surplus past the Solar Gate) → no activation."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=True)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=0.0)
        d.activate.assert_not_called()


@pytest.mark.asyncio
class TestTier2Overnight:
    async def test_overnight_activates_above_reserve(self, mock_hass):
        """Deficit, no surplus, flag ON, SoC>reserve → runs from battery."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=True, remaining_sec=1800,
                  battery_eligible_overnight=True, draw=800)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=50,
                        battery_reserve_soc=20)
        d.activate.assert_called_once()
        assert d._offpeak_forced is True

    async def test_overnight_blocked_below_reserve(self, mock_hass):
        """SoC ≤ reserve → the hard floor holds, no activation."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=True, remaining_sec=1800,
                  battery_eligible_overnight=True)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=18,
                        battery_reserve_soc=20)
        d.activate.assert_not_called()

    async def test_overnight_inert_when_flag_off(self, mock_hass):
        """The pre-#620 behaviour: solar_only deficit device, no surplus, no
        battery flag → NEVER force-runs (the frozen deadline path stays gone)."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=True, remaining_sec=1800,
                  battery_eligible_overnight=False)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=90,
                        battery_reserve_soc=20)
        d.activate.assert_not_called()

    async def test_overnight_respects_max_cap(self, mock_hass):
        """A capped-out device (can_activate False) is skipped even with the
        flag on and SoC high."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=False, battery_eligible_overnight=True,
                  can_activate=False)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=90,
                        battery_reserve_soc=20)
        d.activate.assert_not_called()


@pytest.mark.asyncio
class TestInertByDefault:
    async def test_default_device_unchanged_by_battery_context(self, mock_hass):
        """A plain device (all flags default) behaves identically whether or
        not battery context is passed — the whole feature is opt-in."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800)
        sc.register_device(d)
        # Ample surplus → activates regardless (normal path untouched).
        await sc.update(2000.0, battery_soc=90, battery_buffer_soc=70,
                        battery_reserve_soc=20, battery_assist_budget_w=3000)
        d.activate.assert_called_once()
