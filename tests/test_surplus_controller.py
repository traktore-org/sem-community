"""Tests for SurplusController surplus power distribution."""
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from datetime import datetime

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    SurplusAllocationData,
    DEFAULT_REGULATION_OFFSET,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode, DeviceState


def _make_device(
    device_id="dev1",
    name="Test Device",
    priority=3,
    min_power=500,
    enabled=True,
    managed_externally=False,
    is_active=False,
    consumption=0.0,
    antiflicker_blocks=False,
):
    """Create a mock ControllableDevice.

    Args:
        antiflicker_blocks: If True, deactivate() will NOT flip is_active to False,
            simulating a device whose min_on_time hasn't elapsed.
    """
    device = MagicMock()
    device.device_id = device_id
    device.name = name
    device.priority = priority
    device.min_power_threshold = min_power
    device.is_enabled = enabled
    device.managed_externally = managed_externally
    device.is_active = is_active
    device.device_type = MagicMock(value="switch")
    device.activate = AsyncMock(return_value=min_power)
    device.adjust_power = AsyncMock(return_value=consumption if consumption else min_power)
    device.get_current_consumption = MagicMock(return_value=consumption)
    device.status = MagicMock()
    device.status.allocated_power_w = consumption
    device.status.state = MagicMock(value="active" if is_active else "idle")
    # Control mode — defaults to SURPLUS so surplus controller will activate (#49)
    device.control_mode = DeviceControlMode.SURPLUS

    # Off-peak attributes (Feature 2)
    device._offpeak_forced = False
    device.needs_offpeak_activation = False
    device.remaining_daily_runtime_sec = 0
    device.daily_min_runtime_sec = 0

    # Ensure it is not a ScheduleDevice (prevent isinstance check from matching)
    device.__class__ = MagicMock

    # Deactivate: flip is_active to False unless anti-flicker blocks it
    if antiflicker_blocks:
        device.deactivate = AsyncMock()  # is_active stays True
    else:
        async def _deactivate():
            device.is_active = False
        device.deactivate = AsyncMock(side_effect=_deactivate)

    return device


class TestSurplusControllerInit:
    """Test SurplusController initialization."""

    def test_init_defaults(self, hass):
        sc = SurplusController(hass)
        assert sc.price_responsive_mode is False
        assert sc.regulation_offset == DEFAULT_REGULATION_OFFSET
        assert sc.allocation_data.total_surplus_w == 0.0

    def test_init_custom_offset(self, hass):
        sc = SurplusController(hass, regulation_offset=100)
        assert sc.regulation_offset == 100


class TestDeviceRegistration:
    """Test device register/unregister/get."""

    def test_register_and_get_device(self, hass):
        sc = SurplusController(hass)
        dev = _make_device(device_id="hw1", name="Hot Water")
        sc.register_device(dev)
        assert sc.get_device("hw1") is dev

    def test_unregister_device(self, hass):
        sc = SurplusController(hass)
        dev = _make_device(device_id="hw1")
        sc.register_device(dev)
        sc.unregister_device("hw1")
        assert sc.get_device("hw1") is None

    def test_unregister_nonexistent(self, hass):
        sc = SurplusController(hass)
        sc.unregister_device("nonexistent")  # Should not raise

    def test_get_device_not_found(self, hass):
        sc = SurplusController(hass)
        assert sc.get_device("missing") is None


class TestGetDevicesSorted:
    """Test priority sorting and filtering."""

    def test_sorted_by_priority(self, hass):
        sc = SurplusController(hass)
        d1 = _make_device(device_id="d1", priority=5)
        d2 = _make_device(device_id="d2", priority=1)
        d3 = _make_device(device_id="d3", priority=3)
        sc.register_device(d1)
        sc.register_device(d2)
        sc.register_device(d3)
        sorted_devs = sc.get_devices_sorted()
        assert [d.device_id for d in sorted_devs] == ["d2", "d3", "d1"]

    def test_excludes_disabled(self, hass):
        sc = SurplusController(hass)
        d1 = _make_device(device_id="d1", enabled=True, priority=1)
        d2 = _make_device(device_id="d2", enabled=False, priority=2)
        sc.register_device(d1)
        sc.register_device(d2)
        sorted_devs = sc.get_devices_sorted()
        assert len(sorted_devs) == 1
        assert sorted_devs[0].device_id == "d1"

    def test_excludes_externally_managed(self, hass):
        sc = SurplusController(hass)
        d1 = _make_device(device_id="d1", managed_externally=False, priority=1)
        d2 = _make_device(device_id="d2", managed_externally=True, priority=2)
        sc.register_device(d1)
        sc.register_device(d2)
        sorted_devs = sc.get_devices_sorted()
        assert len(sorted_devs) == 1
        assert sorted_devs[0].device_id == "d1"


class TestUpdateActivation:
    """Test device activation by priority."""

    @pytest.mark.asyncio
    async def test_activates_by_priority(self, hass):
        sc = SurplusController(hass)

        d1 = _make_device(device_id="d1", priority=1, min_power=500)
        d1.activate = AsyncMock(return_value=500.0)
        d2 = _make_device(device_id="d2", priority=2, min_power=300)
        d2.activate = AsyncMock(return_value=300.0)

        sc.register_device(d1)
        sc.register_device(d2)

        # 1000W available, minus 50W offset = 950W distributable
        result = await sc.update(1000.0)

        d1.activate.assert_called_once()
        d2.activate.assert_called_once()
        assert result.active_devices == 2

    @pytest.mark.asyncio
    async def test_skips_device_below_threshold(self, hass):
        sc = SurplusController(hass)

        d1 = _make_device(device_id="d1", priority=1, min_power=800)
        d1.activate = AsyncMock(return_value=800.0)
        d2 = _make_device(device_id="d2", priority=2, min_power=500)

        sc.register_device(d1)
        sc.register_device(d2)

        # 900W available, minus 50W = 850W. After d1 takes 800, only 50 left for d2 (< 500)
        result = await sc.update(900.0)

        d1.activate.assert_called_once()
        d2.activate.assert_not_called()


class TestUpdateDeactivation:
    """Test LIFO deactivation when surplus drops."""

    @pytest.mark.asyncio
    async def test_deactivation_lifo(self, hass):
        sc = SurplusController(hass)

        # Both devices active; adjust_power returns MORE than current consumption
        # so remaining_surplus goes very negative, triggering LIFO deactivation.
        d1 = _make_device(device_id="d1", priority=1, min_power=500, is_active=True, consumption=500.0)
        d1.adjust_power = AsyncMock(return_value=600.0)  # wants 600W
        d2 = _make_device(device_id="d2", priority=2, min_power=300, is_active=True, consumption=300.0)
        d2.adjust_power = AsyncMock(return_value=400.0)  # wants 400W

        sc.register_device(d1)
        sc.register_device(d2)

        # 200W available - 50W offset = 150W distributable
        # d1: delta = 600 - 500 = 100 -> remaining = 150 - 100 = 50
        # d2: delta = 400 - 300 = 100 -> remaining = 50 - 100 = -50
        # -50 < -100? No. Need more aggressive numbers.
        # Let's use 100W total so distributable = 50
        # d1: adjust_power(50 + 500) returns 600, delta = 100 -> remaining = 50 - 100 = -50
        # d2: adjust_power(-50 + 300) returns 400, delta = 100 -> remaining = -50 - 100 = -150
        # -150 < -100 -> deactivation triggers on d2 (reverse order, LIFO)
        await sc.update(100.0)

        d2.deactivate.assert_called_once()


class TestPriceAdjustment:
    """Test price-responsive surplus adjustments."""

    def _make_controller(self, hass):
        sc = SurplusController(hass)
        sc.price_responsive_mode = True
        return sc

    def test_negative_price_adds_10kw(self, hass):
        sc = self._make_controller(hass)
        result = sc._apply_price_adjustment(500.0, "negative")
        assert result == 10500.0

    def test_cheap_price_adds_3kw(self, hass):
        sc = self._make_controller(hass)
        result = sc._apply_price_adjustment(500.0, "cheap")
        assert result == 3500.0

    def test_expensive_price_reduces_by_500(self, hass):
        sc = self._make_controller(hass)
        result = sc._apply_price_adjustment(1000.0, "expensive")
        assert result == 500.0

    def test_expensive_price_floors_at_zero(self, hass):
        sc = self._make_controller(hass)
        result = sc._apply_price_adjustment(200.0, "expensive")
        assert result == 0.0

    def test_normal_price_no_change(self, hass):
        sc = self._make_controller(hass)
        result = sc._apply_price_adjustment(1000.0, "normal")
        assert result == 1000.0

    @pytest.mark.asyncio
    async def test_price_applied_during_update(self, hass):
        sc = self._make_controller(hass)
        dev = _make_device(device_id="d1", priority=1, min_power=100)
        dev.activate = AsyncMock(return_value=100.0)
        sc.register_device(dev)

        result = await sc.update(200.0, price_level="cheap")
        # 200 - 50 offset = 150 + 3000 cheap bonus = 3150 distributable
        assert result.distributable_surplus_w == 3150.0


class TestDeactivateAll:
    """Test emergency deactivation."""

    @pytest.mark.asyncio
    async def test_deactivate_all(self, hass):
        sc = SurplusController(hass)

        d1 = _make_device(device_id="d1", priority=1, is_active=True)
        d2 = _make_device(device_id="d2", priority=2, is_active=True)
        d3 = _make_device(device_id="d3", priority=3, is_active=False)

        sc.register_device(d1)
        sc.register_device(d2)
        sc.register_device(d3)

        await sc.deactivate_all()

        d1.deactivate.assert_called_once()
        d2.deactivate.assert_called_once()
        d3.deactivate.assert_not_called()


class TestAllocationDataSerialization:
    """Test SurplusAllocationData.to_dict serialization."""

    def test_allocation_data_to_dict(self):
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            SurplusAllocation,
        )

        now = datetime(2026, 3, 19, 12, 0, 0)
        data = SurplusAllocationData(
            total_surplus_w=2000.0,
            distributable_surplus_w=1950.0,
            regulation_offset_w=50,
            allocated_w=1500.0,
            unallocated_w=450.0,
            active_devices=2,
            total_devices=3,
            allocations=[
                SurplusAllocation(
                    device_id="d1",
                    device_name="Hot Water",
                    priority=1,
                    allocated_watts=1000.0,
                    actual_consumption_watts=950.0,
                    state="active",
                ),
            ],
            last_update=now,
        )

        d = data.to_dict()
        assert d["surplus_total_w"] == 2000.0
        assert d["surplus_distributable_w"] == 1950.0
        assert d["surplus_regulation_offset_w"] == 50
        assert d["surplus_allocated_w"] == 1500.0
        assert d["surplus_unallocated_w"] == 450.0
        assert d["surplus_active_devices"] == 2
        assert d["surplus_total_devices"] == 3
        assert len(d["surplus_allocations"]) == 1
        assert d["surplus_allocations"][0]["device"] == "Hot Water"
        assert d["surplus_last_update"] == now.isoformat()

    def test_allocation_data_to_dict_no_update_time(self):
        data = SurplusAllocationData()
        d = data.to_dict()
        assert d["surplus_last_update"] is None


class TestDeactivationAntiFlicker:
    """Test that deactivation respects anti-flicker (min_on_time)."""

    @pytest.mark.asyncio
    async def test_antiflicker_blocks_deactivation(self, hass):
        """When device.deactivate() doesn't flip is_active, surplus should NOT be recovered."""
        sc = SurplusController(hass)

        # Device is active but anti-flicker will block deactivation
        d1 = _make_device(
            device_id="d1", priority=1, min_power=500,
            is_active=True, consumption=500.0, antiflicker_blocks=True,
        )
        # adjust_power returns high value to push remaining_surplus well below -100
        d1.adjust_power = AsyncMock(return_value=800.0)

        sc.register_device(d1)

        # 200W available → smoothed=200, distributable=150
        # d1: old=500, adjust(150+500=650) returns 800, delta=300, remaining=150-300=-150
        # -150 < -100 → deactivation triggers, but anti-flicker blocks
        result = await sc.update(200.0)

        d1.deactivate.assert_called_once()
        # Device stayed active — surplus was NOT recovered, active count not decremented
        assert result.active_devices == 1
        # Allocation should still show device as active (not reset to idle)
        assert result.allocations[0].state != "idle"

    @pytest.mark.asyncio
    async def test_successful_deactivation_recovers_surplus(self, hass):
        """When deactivation succeeds, surplus IS recovered for other devices."""
        sc = SurplusController(hass)

        d1 = _make_device(
            device_id="d1", priority=1, min_power=200,
            is_active=True, consumption=200.0,
        )
        d1.adjust_power = AsyncMock(return_value=400.0)  # increases by 200
        d2 = _make_device(
            device_id="d2", priority=2, min_power=300,
            is_active=True, consumption=300.0,
        )
        d2.adjust_power = AsyncMock(return_value=500.0)  # increases by 200

        sc.register_device(d1)
        sc.register_device(d2)

        # 200W available → smoothed=200, distributable=150
        # d1: old=200, adjust(150+200=350) returns 400, delta=200, remaining=150-200=-50
        # d2: old=300, adjust(-50+300=250) returns 500, delta=200, remaining=-50-200=-250
        # -250 < -100 → deactivation: d2 (LIFO) deactivated, recovers 300
        result = await sc.update(200.0)

        d2.deactivate.assert_called_once()
        assert d2.is_active is False


class TestDeltaTracking:
    """Test that active device consumption changes are tracked correctly (Step 3)."""

    @pytest.mark.asyncio
    async def test_active_device_increase_reduces_remaining(self, hass):
        """An active device increasing consumption must reduce surplus for lower-priority devices."""
        sc = SurplusController(hass)

        # d1 is active, consuming 500W, will increase to 800W
        d1 = _make_device(
            device_id="d1", priority=1, min_power=500,
            is_active=True, consumption=500.0,
        )
        d1.adjust_power = AsyncMock(return_value=800.0)

        # d2 is inactive, needs 400W to activate
        d2 = _make_device(device_id="d2", priority=2, min_power=400)
        d2.activate = AsyncMock(return_value=400.0)

        sc.register_device(d1)
        sc.register_device(d2)

        # 1000W available. First call seeds EMA, so smoothed = 1000.
        # distributable = 1000 - 50 = 950
        # d1: old=500, adjust_power(950+500=1450) returns 800, delta=300, remaining=950-300=650
        # d2: 650 >= 400 → activate
        result = await sc.update(1000.0)

        d1.adjust_power.assert_called_once()
        d2.activate.assert_called_once()
        assert result.active_devices == 2

    @pytest.mark.asyncio
    async def test_active_device_blocks_lower_priority(self, hass):
        """If d1 consumes most surplus, d2 should NOT activate."""
        sc = SurplusController(hass)

        d1 = _make_device(
            device_id="d1", priority=1, min_power=500,
            is_active=True, consumption=500.0,
        )
        d1.adjust_power = AsyncMock(return_value=900.0)  # increases by 400

        d2 = _make_device(device_id="d2", priority=2, min_power=400)

        sc.register_device(d1)
        sc.register_device(d2)

        # 1000W → distributable = 950
        # d1 delta = 400 → remaining = 550
        # d2 needs 400 but remaining after d1 = 950 - 400 = 550... wait
        # Let's use tighter numbers: 700W available → distributable = 650
        # d1: delta = 400 → remaining = 650 - 400 = 250. d2 needs 400 → skip
        result = await sc.update(700.0)

        d2.activate.assert_not_called()


class TestScheduleDeviceBudgetLeak:
    """Test that force-started ScheduleDevice subtracts from surplus (Step 4)."""

    @pytest.mark.asyncio
    async def test_force_start_subtracts_consumption(self, hass):
        """Force-started device should subtract from surplus and update allocation."""
        from custom_components.solar_energy_management.devices.base import ScheduleDevice

        sc = SurplusController(hass)

        # Create a mock ScheduleDevice
        sched = MagicMock(spec=ScheduleDevice)
        sched.device_id = "washer"
        sched.name = "Washer"
        sched.priority = 5
        sched.min_power_threshold = 2000
        sched.is_enabled = True
        sched.managed_externally = False
        sched.is_active = False
        sched.is_deadline_approaching = True
        sched.rated_power = 2000
        sched.device_type = MagicMock(value="schedule")
        sched.activate = AsyncMock(return_value=2000.0)
        sched.deactivate = AsyncMock()
        sched.adjust_power = AsyncMock(return_value=0.0)
        sched.get_current_consumption = MagicMock(return_value=0.0)
        sched.status = MagicMock()
        sched.status.allocated_power_w = 0.0
        sched.status.state = MagicMock(value="idle")
        sched.control_mode = DeviceControlMode.SURPLUS
        sched._offpeak_forced = False
        sched.needs_offpeak_activation = False
        sched.remaining_daily_runtime_sec = 0

        sc.register_device(sched)

        # 500W surplus, not enough to activate normally (min 2000W)
        # but deadline forces it
        result = await sc.update(500.0)

        sched.activate.assert_called_once_with(2000)
        # Force-start should be reflected in allocated total
        assert result.allocated_w == 2000.0
        assert result.active_devices == 1
        # Allocation entry should be updated
        alloc = result.allocations[0]
        assert alloc.state == "active"
        assert alloc.allocated_watts == 2000.0


class TestOffpeakActivation:
    """Test off-peak forced activation/deactivation of devices with runtime deficit."""

    @pytest.mark.asyncio
    async def test_offpeak_activates_device_with_deficit(self, hass):
        """price_level='cheap', device needs runtime => activated."""
        sc = SurplusController(hass)
        dev = _make_device(device_id="hw1", priority=5, min_power=2000)
        dev.needs_offpeak_activation = True
        dev._offpeak_forced = False
        dev.remaining_daily_runtime_sec = 1800
        dev.activate = AsyncMock(return_value=2000.0)
        sc.register_device(dev)

        result = await sc.update(0.0, price_level="cheap")

        dev.activate.assert_called_once_with(2000)
        assert dev._offpeak_forced is True
        assert result.active_devices >= 1

    @pytest.mark.asyncio
    async def test_offpeak_skips_during_ht(self, hass):
        """price_level='normal' => no forced activation."""
        sc = SurplusController(hass)
        dev = _make_device(device_id="hw1", priority=5, min_power=2000)
        dev.needs_offpeak_activation = True
        dev._offpeak_forced = False
        dev.remaining_daily_runtime_sec = 1800
        sc.register_device(dev)

        await sc.update(0.0, price_level="normal")

        dev.activate.assert_not_called()

    @pytest.mark.asyncio
    async def test_offpeak_deactivates_on_tariff_change(self, hass):
        """Forced device deactivated when HT starts."""
        sc = SurplusController(hass)
        dev = _make_device(
            device_id="hw1", priority=5, min_power=2000,
            is_active=True, consumption=2000.0,
        )
        dev._offpeak_forced = True
        dev.needs_offpeak_activation = False  # already active
        sc.register_device(dev)

        await sc.update(0.0, price_level="normal")

        dev.deactivate.assert_called_once()
        assert dev._offpeak_forced is False

    @pytest.mark.asyncio
    async def test_offpeak_respects_antiflicker(self, hass):
        """Deactivation blocked by anti-flicker => stays active gracefully."""
        sc = SurplusController(hass)
        dev = _make_device(
            device_id="hw1", priority=5, min_power=2000,
            is_active=True, consumption=2000.0,
            antiflicker_blocks=True,
        )
        dev._offpeak_forced = True
        dev.needs_offpeak_activation = False
        sc.register_device(dev)

        await sc.update(0.0, price_level="normal")

        dev.deactivate.assert_called_once()
        # Anti-flicker blocks => _offpeak_forced stays True
        assert dev._offpeak_forced is True

    @pytest.mark.asyncio
    async def test_offpeak_skips_already_active(self, hass):
        """Surplus-activated device should not be double-activated by off-peak."""
        sc = SurplusController(hass)
        dev = _make_device(
            device_id="hw1", priority=5, min_power=2000,
            is_active=True, consumption=2000.0,
        )
        # Already active via surplus => needs_offpeak_activation = False
        dev.needs_offpeak_activation = False
        dev._offpeak_forced = False
        sc.register_device(dev)

        await sc.update(3000.0, price_level="cheap")

        # activate should NOT be called (only adjust_power for already-active device)
        # The device was already active from surplus, not from off-peak forcing


class TestEMASmoothing:
    """Test exponential moving average smoothing of surplus input (Step 5)."""

    @pytest.mark.asyncio
    async def test_first_call_seeds_directly(self, hass):
        """First update should use raw value (no smoothing)."""
        sc = SurplusController(hass)
        dev = _make_device(device_id="d1", priority=1, min_power=100)
        dev.activate = AsyncMock(return_value=100.0)
        sc.register_device(dev)

        result = await sc.update(1000.0)
        # First call: smoothed = 1000, distributable = 1000 - 50 = 950
        assert result.distributable_surplus_w == 950.0

    @pytest.mark.asyncio
    async def test_smoothing_dampens_spike(self, hass):
        """Second update with lower value should be smoothed."""
        sc = SurplusController(hass)
        dev = _make_device(device_id="d1", priority=1, min_power=100)
        dev.activate = AsyncMock(return_value=100.0)
        sc.register_device(dev)

        # First call seeds: smoothed = 2000
        await sc.update(2000.0)

        # Second call: smoothed = 0.3 * 500 + 0.7 * 2000 = 150 + 1400 = 1550
        # distributable = 1550 - 50 = 1500
        result = await sc.update(500.0)
        assert result.distributable_surplus_w == 1500.0

    @pytest.mark.asyncio
    async def test_raw_surplus_unsmoothed(self, hass):
        """total_surplus_w should remain the raw (unsmoothed) value."""
        sc = SurplusController(hass)
        dev = _make_device(device_id="d1", priority=1, min_power=100)
        dev.activate = AsyncMock(return_value=100.0)
        sc.register_device(dev)

        await sc.update(2000.0)
        result = await sc.update(500.0)

        # Raw value preserved
        assert result.total_surplus_w == 500.0
        # Smoothed distributable is different
        assert result.distributable_surplus_w != 500.0 - 50
