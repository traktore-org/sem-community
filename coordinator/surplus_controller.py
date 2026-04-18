"""Surplus controller for Solar Energy Management.

SEM surplus control algorithm:
1. 10s control loop - evaluates surplus every coordinator update
2. Sequential priority activation - Priority 1 first, cascade down
3. Minimum power threshold per device
4. Regulation offset (default 50W) - always export small buffer to grid
5. Dynamic add/remove - LIFO deactivation on surplus decrease
6. Variable-power devices get proportional control
7. Manual loads reduce available surplus automatically

This replaces the EV-only surplus routing with a generic multi-device
surplus distribution system.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

from ..devices.base import ControllableDevice, DeviceState

_LOGGER = logging.getLogger(__name__)

# Defaults
DEFAULT_REGULATION_OFFSET = 50  # Watts - always keep small export
DEFAULT_MIN_SURPLUS_CHANGE = 100  # Watts - suppress adjustments below this


@dataclass
class SurplusAllocation:
    """Allocation result for a single device."""
    device_id: str
    device_name: str
    priority: int
    allocated_watts: float
    actual_consumption_watts: float
    state: str


@dataclass
class SurplusAllocationData:
    """Complete surplus allocation state."""
    total_surplus_w: float = 0.0
    distributable_surplus_w: float = 0.0
    regulation_offset_w: float = DEFAULT_REGULATION_OFFSET
    allocated_w: float = 0.0
    unallocated_w: float = 0.0
    active_devices: int = 0
    total_devices: int = 0
    allocations: List[SurplusAllocation] = field(default_factory=list)
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surplus_total_w": round(self.total_surplus_w, 1),
            "surplus_distributable_w": round(self.distributable_surplus_w, 1),
            "surplus_regulation_offset_w": self.regulation_offset_w,
            "surplus_allocated_w": round(self.allocated_w, 1),
            "surplus_unallocated_w": round(self.unallocated_w, 1),
            "surplus_active_devices": self.active_devices,
            "surplus_total_devices": self.total_devices,
            "surplus_allocations": [
                {
                    "device": a.device_name,
                    "priority": a.priority,
                    "allocated_w": round(a.allocated_watts, 1),
                    "consuming_w": round(a.actual_consumption_watts, 1),
                    "state": a.state,
                }
                for a in self.allocations
            ],
            "surplus_last_update": self.last_update.isoformat() if self.last_update else None,
        }


class SurplusController:
    """Controls surplus power distribution across multiple devices.

    Implements priority-based surplus routing:
    - Devices are sorted by priority (1=highest)
    - Each device has a minimum power threshold
    - Variable-power devices get proportional surplus
    - On/off devices get their full rated power or nothing
    - LIFO deactivation when surplus drops
    """

    def __init__(
        self,
        hass: HomeAssistant,
        regulation_offset: float = DEFAULT_REGULATION_OFFSET,
    ):
        self.hass = hass
        self.regulation_offset = regulation_offset
        self.max_export_w: float = 0  # 0 = no limit. E.g., 10000 for 10kW export limit
        self._devices: Dict[str, ControllableDevice] = {}
        self._allocation_data = SurplusAllocationData()
        self._price_responsive_mode = False
        self._last_surplus = 0.0
        self._smoothed_surplus: Optional[float] = None

    @property
    def allocation_data(self) -> SurplusAllocationData:
        """Return current allocation state."""
        return self._allocation_data

    @property
    def price_responsive_mode(self) -> bool:
        return self._price_responsive_mode

    @price_responsive_mode.setter
    def price_responsive_mode(self, value: bool) -> None:
        self._price_responsive_mode = value

    def register_device(self, device: ControllableDevice) -> None:
        """Register a device for surplus control."""
        self._devices[device.device_id] = device
        _LOGGER.info(
            "Registered device: %s (priority=%d, min=%dW, type=%s)",
            device.name, device.priority, device.min_power_threshold,
            device.device_type.value,
        )

    def unregister_device(self, device_id: str) -> None:
        """Remove a device from surplus control."""
        if device_id in self._devices:
            del self._devices[device_id]
            _LOGGER.info("Unregistered device: %s", device_id)

    def get_device(self, device_id: str) -> Optional[ControllableDevice]:
        """Get a registered device by ID."""
        return self._devices.get(device_id)

    def get_devices_sorted(self) -> List[ControllableDevice]:
        """Get all devices sorted by priority (1=highest).

        Devices with managed_externally=True are excluded (e.g., EV charger
        during night mode when the coordinator manages it directly).
        """
        return sorted(
            [d for d in self._devices.values()
             if d.is_enabled and not d.managed_externally],
            key=lambda d: d.priority,
        )

    async def update(
        self,
        available_power_w: float,
        price_level: Optional[str] = None,
    ) -> SurplusAllocationData:
        """Run the surplus allocation algorithm.

        This is called every coordinator update cycle (~10s).

        Args:
            available_power_w: Total available surplus power (from FlowCalculator).
            price_level: Current price level (cheap/normal/expensive) for price-responsive mode.

        Returns:
            SurplusAllocationData with allocation results.
        """
        # EMA smoothing to reduce oscillation from cloud transients
        if self._smoothed_surplus is None:
            self._smoothed_surplus = available_power_w
        else:
            self._smoothed_surplus = 0.3 * available_power_w + 0.7 * self._smoothed_surplus

        # Apply regulation offset
        distributable = self._smoothed_surplus - self.regulation_offset
        self._last_surplus = distributable

        # Feed-in/export limitation: add virtual surplus when approaching limit
        if self.max_export_w > 0 and self._smoothed_surplus > self.max_export_w:
            excess_export = self._smoothed_surplus - self.max_export_w
            distributable += excess_export  # Force-route excess to devices

        # Price-responsive adjustments
        if self._price_responsive_mode and price_level:
            distributable = self._apply_price_adjustment(distributable, price_level)

        devices = self.get_devices_sorted()
        allocations: List[SurplusAllocation] = []
        remaining_surplus = distributable
        active_count = 0

        # Off-peak deactivation: turn off forced devices when tariff switches to HT
        if price_level not in ("cheap", "very_cheap", "negative"):
            for device in devices:
                if device._offpeak_forced and device.is_active:
                    await device.deactivate()
                    if not device.is_active:
                        device._offpeak_forced = False
                        _LOGGER.info(
                            "Off-peak deactivated %s (tariff now %s)",
                            device.name, price_level,
                        )
                    else:
                        _LOGGER.debug(
                            "Off-peak deactivation of %s blocked by anti-flicker",
                            device.name,
                        )

        # Import control mode enum
        from ..devices.base import DeviceControlMode

        # Activation pass: iterate by priority, activate eligible devices
        # Only devices in "surplus" mode are candidates for activation (#49).
        # Devices in "peak_only" mode are tracked but never proactively turned on.
        # Devices in "off" mode are skipped entirely.
        for device in devices:
            # Skip devices in "off" mode — SEM never touches these
            if device.control_mode == DeviceControlMode.OFF:
                continue

            if remaining_surplus >= device.min_power_threshold and not device.is_active:
                # Only activate if device is in "surplus" mode
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue  # peak_only: never proactively turn on
                if device.can_activate():
                    consumed = await device.activate(remaining_surplus)
                    if consumed > 0:
                        device.record_activated()
                        device.reset_surplus_timer()
                    remaining_surplus -= consumed
                    if consumed > 0:
                        active_count += 1

            elif not device.is_active and remaining_surplus < device.min_power_threshold:
                device.reset_surplus_timer()

            elif device.is_active:
                # Already active — adjust power level (applies to all modes)
                old_consumption = device.get_current_consumption()
                consumed = await device.adjust_power(remaining_surplus + old_consumption)
                delta = consumed - old_consumption
                remaining_surplus -= max(0, delta)
                active_count += 1

            allocations.append(SurplusAllocation(
                device_id=device.device_id,
                device_name=device.name,
                priority=device.priority,
                allocated_watts=device.status.allocated_power_w,
                actual_consumption_watts=device.get_current_consumption(),
                state=device.status.state.value,
            ))

        # Deactivation pass (reverse priority — LIFO): if surplus is negative,
        # deactivate lowest-priority active devices first
        if remaining_surplus < -DEFAULT_MIN_SURPLUS_CHANGE:
            for device in reversed(devices):
                if remaining_surplus >= 0:
                    break
                if device.is_active and device.can_deactivate():
                    consumption = device.get_current_consumption()
                    await device.deactivate()
                    if not device.is_active:
                        device.record_deactivated()
                        remaining_surplus += consumption
                        active_count -= 1
                        _LOGGER.info(
                            "Deactivated %s (priority %d) to recover %.0fW",
                            device.name, device.priority, consumption,
                        )
                        # Update allocation
                        for a in allocations:
                            if a.device_id == device.device_id:
                                a.allocated_watts = 0.0
                                a.actual_consumption_watts = 0.0
                                a.state = DeviceState.IDLE.value
                    else:
                        _LOGGER.debug(
                            "Deactivation of %s blocked by anti-flicker",
                            device.name,
                        )

        # Check for scheduled devices that must start (deadline approaching)
        from ..devices.base import ScheduleDevice
        for device in devices:
            if isinstance(device, ScheduleDevice) and device.is_deadline_approaching and not device.is_active:
                consumed = await device.activate(device.rated_power)
                if consumed > 0:
                    active_count += 1
                    remaining_surplus -= consumed
                    for a in allocations:
                        if a.device_id == device.device_id:
                            a.allocated_watts = consumed
                            a.actual_consumption_watts = consumed
                            a.state = DeviceState.ACTIVE.value
                _LOGGER.warning(
                    "Force-starting %s due to deadline (%.0fW)",
                    device.name, consumed,
                )

        # Off-peak activation pass: force-activate devices with runtime deficit
        # Only for "surplus" mode devices — off-peak is a form of proactive activation (#49)
        if price_level in ("cheap", "very_cheap", "negative"):
            for device in devices:
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                if device.needs_offpeak_activation:
                    consumed = await device.activate(device.min_power_threshold)
                    if consumed > 0:
                        device._offpeak_forced = True
                        active_count += 1
                        remaining_surplus -= consumed
                        # Update or add allocation entry
                        found = False
                        for a in allocations:
                            if a.device_id == device.device_id:
                                a.allocated_watts = consumed
                                a.actual_consumption_watts = consumed
                                a.state = DeviceState.ACTIVE.value
                                found = True
                                break
                        if not found:
                            allocations.append(SurplusAllocation(
                                device_id=device.device_id,
                                device_name=device.name,
                                priority=device.priority,
                                allocated_watts=consumed,
                                actual_consumption_watts=consumed,
                                state=DeviceState.ACTIVE.value,
                            ))
                        _LOGGER.info(
                            "Off-peak forced %s (%.0fW, deficit %.0fs)",
                            device.name, consumed, device.remaining_daily_runtime_sec,
                        )

        # Build allocation data
        total_allocated = sum(a.actual_consumption_watts for a in allocations)
        self._allocation_data = SurplusAllocationData(
            total_surplus_w=available_power_w,
            distributable_surplus_w=distributable,
            regulation_offset_w=self.regulation_offset,
            allocated_w=total_allocated,
            unallocated_w=max(0, distributable - total_allocated),
            active_devices=active_count,
            total_devices=len(self._devices),
            allocations=allocations,
            last_update=datetime.now(),
        )

        return self._allocation_data

    def _apply_price_adjustment(self, distributable: float, price_level: str) -> float:
        """Adjust distributable surplus based on electricity price level.

        - cheap: Add virtual surplus to encourage consumption
        - expensive: Reduce surplus to minimize consumption
        - negative: Maximize consumption (add large virtual surplus)
        """
        if price_level == "negative":
            # Negative price — consume as much as possible
            return distributable + 10000  # Virtual 10kW surplus
        elif price_level == "cheap":
            # Cheap — encourage consumption even from grid
            return distributable + 3000  # Virtual 3kW surplus
        elif price_level == "expensive":
            # Expensive — only use real solar surplus, reduce buffer
            return max(0, distributable - 500)
        return distributable

    async def deactivate_all(self) -> None:
        """Deactivate all devices (emergency or shutdown)."""
        for device in reversed(self.get_devices_sorted()):
            if device.is_active:
                await device.deactivate()
        _LOGGER.info("Deactivated all surplus-controlled devices")
