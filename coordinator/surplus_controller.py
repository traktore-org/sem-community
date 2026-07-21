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
from __future__ import annotations

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
        # (#620) battery context, refreshed each update(); inert defaults so a
        # helper called before the first update() is a no-op.
        self._batt_soc: Optional[float] = None
        self._batt_buffer_soc: float = 100.0
        self._batt_reserve_soc: float = 100.0
        self._batt_assist_budget_w: float = 0.0
        self._tier1_budget_left: float = 0.0
        # (arc Phase 4) last raw surplus samples for the median-of-3 pre-filter
        self._surplus_samples: List[float] = []
        # EV Intelligence: anticipated surplus from taper detection (#106)
        self._anticipated_surplus_w: float = 0.0
        self._anticipated_deadline: Optional[float] = None

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

    def set_anticipated_surplus(self, watts: float, minutes: float) -> None:
        """Hint that watts will free up when EV taper completes (#106).

        The surplus controller will factor this in 2 min before the
        deadline to pre-warm devices.
        """
        import time as _time
        self._anticipated_surplus_w = watts
        self._anticipated_deadline = _time.monotonic() + minutes * 60
        _LOGGER.debug("Anticipated surplus: %.0fW in %.0f min", watts, minutes)

    def distribute_ev_budget(
        self,
        budget_w: float,
        ev_devices: Dict[str, "ControllableDevice"],
        excluded_charger_ids: Optional[set[str]] = None,
    ) -> Dict[str, float]:
        """Distribute EV charging budget across multiple chargers by priority.

        Priority-based cascade: highest priority (lowest number) gets power
        first, up to its max. Remainder cascades to next charger if it meets
        the minimum threshold. 60s hysteresis between reallocations.

        Args:
            budget_w: Total watts available for EV charging.
            ev_devices: Dict of charger_id → CurrentControlDevice.
            excluded_charger_ids: Charger IDs that must NOT receive any
                allocation regardless of priority (e.g. ``charge_mode=off``).
                Returned in the output dict with ``0`` so dashboards still
                see the entry. The actuator's #346 mode guard is the
                last-line defence; this gate stops the dashboard from
                misreporting allocated W on disabled chargers. #351 M5.

        Returns:
            Dict of charger_id → allocated watts.
        """
        if not ev_devices:
            return {}

        excluded = excluded_charger_ids or set()

        import time as _time

        # Sort by priority (lower = higher priority); excluded chargers
        # are still iterated so they appear in the output with 0 W —
        # but they're filtered out of the budget cascade.
        sorted_chargers = sorted(ev_devices.items(), key=lambda x: x[1].priority)

        # Hysteresis: don't reallocate more than once per 60s
        now = _time.monotonic()
        last_realloc = getattr(self, "_ev_last_realloc_time", 0.0)
        prev_alloc = getattr(self, "_ev_prev_allocation", {})

        # Check if budget changed significantly (>500W) since last reallocation
        prev_total = sum(prev_alloc.values()) if prev_alloc else 0
        budget_changed = abs(budget_w - prev_total) > 500

        if not budget_changed and (now - last_realloc) < 60:
            # Within hysteresis window and no significant change → keep previous
            return prev_alloc

        allocations: Dict[str, float] = {}
        remaining = budget_w

        for charger_id, device in sorted_chargers:
            if charger_id in excluded:
                # Mode-disabled chargers (#351 M5) — appear in the output
                # with 0 W so dashboards see the entry, but don't consume
                # any of the budget cascade.
                allocations[charger_id] = 0
                continue
            if remaining <= 0:
                allocations[charger_id] = 0
                continue

            max_power = device.max_current * device.phases * device.voltage
            min_threshold = device.min_power_threshold

            if remaining >= min_threshold:
                alloc = min(remaining, max_power)
                allocations[charger_id] = alloc
                remaining -= alloc
            else:
                allocations[charger_id] = 0

        self._ev_last_realloc_time = now
        self._ev_prev_allocation = allocations

        if len(ev_devices) > 1:
            alloc_summary = ", ".join(
                f"{cid}={w:.0f}W" for cid, w in allocations.items() if w > 0
            )
            _LOGGER.debug(
                "EV budget distribution: %.0fW → %s (remaining=%.0fW)",
                budget_w, alloc_summary or "none", remaining,
            )

        return allocations

    def register_device(self, device: ControllableDevice) -> None:
        """Register a device for surplus control."""
        self._devices[device.device_id] = device
        device._controller = self  # Allow device to look up dependencies (#122)
        depends = getattr(device, 'depends_on', None) or "none"
        _LOGGER.info(
            "Registered device: %s (priority=%d, min=%dW, type=%s, depends_on=%s)",
            device.name, device.priority, device.min_power_threshold,
            device.device_type.value, depends,
        )

    def get_dependents(self, device_id: str) -> list:
        """Get all devices that depend on the given device (#122)."""
        return [d for d in self._devices.values()
                if device_id in getattr(d, 'depends_on', [])]

    def validate_dependencies(self) -> list:
        """Check for circular dependencies. Returns list of errors."""
        errors = []
        for device in self._devices.values():
            dep_list = getattr(device, 'depends_on', None)
            if not dep_list:
                continue
            visited = set()
            current = device.device_id
            chain = [current]
            while True:
                deps = self._devices.get(current)
                dep_list = getattr(deps, 'depends_on', None) if deps else None
                if not deps or not dep_list:
                    break
                next_dep = dep_list[0]  # Check first dependency for cycles
                if next_dep in visited:
                    errors.append(f"Circular dependency: {' → '.join(chain + [next_dep])}")
                    break
                visited.add(next_dep)
                chain.append(next_dep)
                current = next_dep
        return errors

    def unregister_device(self, device_id: str) -> None:
        """Remove a device from surplus control."""
        if device_id in self._devices:
            del self._devices[device_id]
            _LOGGER.info("Unregistered device: %s", device_id)

    def clear_devices(self) -> None:
        """Drop every registered device.

        Called from ``async_unload_entry`` so a HA-side reload doesn't
        leak the prior cycle's device registrations into the next setup.
        Pre-fix, reloads left the registered EV charger / heat pump /
        switch devices in ``self._devices`` — the new setup re-registered
        them on top, causing each reload to grow the dispatch list.
        """
        if self._devices:
            count = len(self._devices)
            self._devices.clear()
            _LOGGER.info("Cleared %d registered devices on unload", count)

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

    def active_surplus_draw_w(self) -> float:
        """Sum the current draw of the surplus devices this controller
        has activated (#508 W7).

        The coordinator builds a *feedback-free* true house surplus as
        ``grid_export + active_surplus_draw_w()``. Without the addback,
        every device the controller turns on shrinks the grid export it
        reads next cycle, so the surplus signal would chase its own tail
        and the device would oscillate. Adding back the controller's own
        active draw makes the input the surplus that WOULD exist if its
        devices were off — the stable quantity to allocate from.

        Externally-managed devices (the EV, driven by the decide/actuate
        path) are excluded — their draw is already reflected in grid
        export and must not be re-credited here.
        """
        return sum(
            d.get_current_consumption()
            for d in self.get_devices_sorted()
            if d.is_active
        )

    def observe_only(
        self,
        available_power_w: float,
        reclaim_w: float = 0.0,
    ) -> SurplusAllocationData:
        """Read-only surplus allocation for OBSERVER MODE — reports the surplus
        figures and CURRENTLY-active devices WITHOUT commanding anything.

        No ``reconcile_all``, no ``activate`` / ``deactivate`` / ``adjust_power``
        — this method physically cannot issue a device command. The coordinator
        calls it INSTEAD of :meth:`update` when ``_observer_mode`` is on, so
        observation mode cuts every surplus command (loads / heat pump / hot
        water / climate) the same way the battery pipeline and EV control are
        already cut. The trace's integration layer then reports "observer mode
        — not commanding".
        """
        total = float(available_power_w) + max(0.0, float(reclaim_w))
        active = [d for d in self._devices.values()
                  if getattr(d, "is_active", False)]
        allocated = sum(
            float(d.get_current_consumption() or 0.0) for d in active
        )
        data = SurplusAllocationData()
        data.total_surplus_w = total
        data.distributable_surplus_w = max(0.0, total - self.regulation_offset)
        data.regulation_offset_w = self.regulation_offset
        data.allocated_w = allocated
        data.unallocated_w = max(0.0, total - allocated)
        data.active_devices = len(active)
        data.total_devices = len(self._devices)
        return data

    async def update(
        self,
        available_power_w: float,
        price_level: Optional[str] = None,
        peak_state: Optional[str] = None,
        reclaim_w: float = 0.0,
        battery_priority: Optional[int] = None,
        # (#620) battery context for the two device battery tiers. Defaults
        # make the whole feature INERT: with no battery data and both
        # per-device flags off (their default), _tier1/_tier2 are no-ops and
        # allocation is byte-identical to pre-#620.
        battery_soc: Optional[float] = None,
        battery_buffer_soc: float = 100.0,
        battery_reserve_soc: float = 100.0,
        battery_assist_budget_w: float = 0.0,
    ) -> SurplusAllocationData:
        """Run the surplus allocation algorithm.

        This is called every coordinator update cycle (~10s).

        Args:
            available_power_w: Total available surplus power. Since #508 W7
                the coordinator passes the feedback-free TRUE house surplus
                (grid export + this controller's own active draw), not the
                EV charging budget — heat pump / hot water boost on what the
                house is actually exporting after the EV and battery take
                their share.
            price_level: Current price level (cheap/normal/expensive) for price-responsive mode.
            peak_state: Current ``LoadManagementState`` (#508 W2). When the
                grid-import peak is at risk (WARNING / SHEDDING / EMERGENCY)
                the controller stops ADDING discretionary load, and on
                SHEDDING / EMERGENCY proactively backs its own active
                devices off by reverse priority — so it complements the
                load manager instead of re-activating, next cycle, whatever
                the load manager just shed. ``None`` = no peak awareness
                (legacy behaviour).

        Returns:
            SurplusAllocationData with allocation results.
        """
        # (arc) Reconcile belief vs observed reality BEFORE allocating, so a
        # load that silently dropped off (failed turn_on) or was toggled by the
        # user isn't counted as active / credited runtime this cycle, and SEM
        # doesn't immediately re-fight a manual off. Scoped to on/off loads
        # (switch + climate); EV / heat-pump / setpoint keep their own handling.
        from ..devices.base import DeviceType
        from .device_reconciler import reconcile_all
        reconcile_all([
            d for d in self._devices.values()
            if getattr(d, "device_type", None) in (DeviceType.SWITCH, DeviceType.CLIMATE)
        ])

        # #508 W2 — peak posture. WARNING freezes new activation (don't add
        # load while the peak is climbing); SHEDDING/EMERGENCY additionally
        # sheds the controller's own discretionary devices. EMERGENCY sheds
        # all of them at once; SHEDDING sheds gently (one per cycle) so the
        # combined load-manager + surplus back-off doesn't overshoot.
        from ..const import LoadManagementState
        # (#620) stash the battery context for the tier helpers this cycle.
        self._batt_soc = battery_soc
        self._batt_buffer_soc = battery_buffer_soc
        self._batt_reserve_soc = battery_reserve_soc
        self._batt_assist_budget_w = max(0.0, float(battery_assist_budget_w or 0.0))
        peak_freeze = peak_state in (
            LoadManagementState.WARNING,
            LoadManagementState.SHEDDING,
            LoadManagementState.EMERGENCY,
        )
        peak_shed = peak_state in (
            LoadManagementState.SHEDDING,
            LoadManagementState.EMERGENCY,
        )
        peak_shed_all = peak_state == LoadManagementState.EMERGENCY
        # (arc Phase 4) Median-of-3 pre-filter: a SINGLE-cycle spike/dropout
        # (inverter glitch, sensor blip) still moves the EMA below by 30% of its
        # magnitude — enough to flap a marginal load. The median passes only
        # values seen in ≥2 of the last 3 cycles, so one bad sample never
        # reaches the EMA at all. Real trends (2+ consistent cycles) pass with
        # one cycle of extra latency, which the EMA's own inertia already dwarfs.
        self._surplus_samples.append(available_power_w)
        if len(self._surplus_samples) > 3:
            self._surplus_samples.pop(0)
        if len(self._surplus_samples) == 3:
            filtered_w = sorted(self._surplus_samples)[1]
        else:
            filtered_w = available_power_w  # warm-up (first 2 cycles): raw

        # EMA smoothing to reduce oscillation from cloud transients
        if self._smoothed_surplus is None:
            self._smoothed_surplus = filtered_w
        else:
            self._smoothed_surplus = 0.3 * filtered_w + 0.7 * self._smoothed_surplus

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
        # (#576) The home battery sits at ``battery_priority`` in this walk.
        # ``reclaim_w`` (the power that would charge it) is offered at the TOP;
        # when the walk crosses the battery's slot it is handed back to the
        # battery, so loads ABOVE the battery reclaim it and loads BELOW see
        # only the export surplus. ``max(0, …)`` yields exactly the export
        # surplus the higher-priority loads left unconsumed (see #576 tests).
        remaining_surplus = distributable + max(0.0, reclaim_w)
        _reclaim_handed_back = False
        active_count = 0
        # (#620) Tier-1 running budget — the battery can only supply its assist
        # budget ONCE, not once per device. Decremented as each battery-assist
        # load draws from it, so N loads can't each claim the full budget.
        self._tier1_budget_left = self._batt_assist_budget_w

        # Force expiry: a cheap-hours force ends with its reason (#559 review) —
        # the tariff left the cheap window, OR the day rolled over (the deficit
        # it served was YESTERDAY's — without the date check a device forced
        # into a cheap midnight window would re-fill the NEW day's target from
        # grid all night).
        from homeassistant.util import dt as dt_util
        today_local = dt_util.now().date()
        for device in devices:
            if not device.is_active:
                continue
            reason = None
            if device._offpeak_forced:
                stale = (
                    device._offpeak_forced_date is not None
                    and device._offpeak_forced_date != today_local
                )
                if stale:
                    reason = "cheap-hours force expired (day rollover)"
                elif price_level not in ("cheap", "very_cheap", "negative"):
                    reason = f"tariff now {price_level}"
            # (#620) Tier-2 overnight battery force expiry — its OWN terms: the
            # Reserve floor was crossed (battery must be protected) or the day
            # rolled over. NOT expired by tariff (it isn't tariff-driven). The
            # daily-target-met stop is handled by the goal gate below.
            if reason is None and getattr(device, "_batt_overnight_forced", False):
                soc = self._batt_soc
                _bo_date = getattr(device, "_batt_overnight_forced_date", None)
                if (_bo_date is not None and _bo_date != today_local):
                    reason = "overnight battery force expired (day rollover)"
                elif soc is not None and soc <= self._batt_reserve_soc:
                    reason = "overnight battery force ended (reserve SoC reached)"
            if reason:
                await device.deactivate()
                if not device.is_active:
                    device._offpeak_forced = False
                    device._offpeak_forced_date = None
                    device._batt_overnight_forced = False
                    device._batt_overnight_forced_date = None
                    _LOGGER.info(
                        "Force ended for %s (%s)", device.name, reason,
                    )
                else:
                    _LOGGER.debug(
                        "Force-end of %s blocked by anti-flicker", device.name,
                    )

        # Import control mode enum
        from ..devices.base import DeviceControlMode

        # Activation pass: iterate by priority, activate eligible devices
        # Only devices in "surplus" mode are candidates for activation (#49).
        # Devices in "peak_only" mode are tracked but never proactively turned on.
        # Devices in "off" mode are skipped entirely.
        for device in devices:
            # (#576) Cross the home battery's slot: hand the reclaim back so
            # every load from here down (lower priority than the battery) sees
            # only the export surplus and the battery charges first.
            if (not _reclaim_handed_back and battery_priority is not None
                    and reclaim_w > 0 and device.priority >= battery_priority):
                remaining_surplus = max(0.0, remaining_surplus - reclaim_w)
                _reclaim_handed_back = True
            # Skip devices in "off" mode — SEM never touches these
            if device.control_mode == DeviceControlMode.OFF:
                continue

            # (#559) Goal gates — a device that is DONE for the day (its
            # daily runtime target met, or the external stop condition like
            # the car's SOC target) is stopped and stays off until the day
            # rolls over. Only SURPLUS-mode devices: peak_only devices are
            # user-managed, SEM never proactively stops them.
            if device.control_mode == DeviceControlMode.SURPLUS:
                done_reason = None
                if device.daily_max_runtime_reached:
                    # (#620) the hard cap must STOP a running device, not just
                    # block re-activation — otherwise a load already on when it
                    # crosses the cap keeps running past it (caught live on the
                    # Heizband PROD test). The cap overrides the min deficit.
                    done_reason = "daily max runtime cap reached"
                elif device.daily_targets_met:
                    done_reason = "daily target met"
                elif device.stop_condition_met:
                    done_reason = (
                        f"stop condition met ({device.stop_entity} >= "
                        f"{device.stop_at:g})"
                    )
                if done_reason:
                    if device.is_active and device.can_deactivate():
                        await device.deactivate()
                        if not device.is_active:
                            device.record_deactivated()
                            device._offpeak_forced = False
                            device._offpeak_forced_date = None
                            # (#620) done-for-the-day also ends any Tier-2
                            # overnight force — otherwise the marker leaks until
                            # day rollover and the LIFO exemption keeps shielding
                            # an already-finished device.
                            device._batt_overnight_forced = False
                            device._batt_overnight_forced_date = None
                            _LOGGER.info(
                                "%s: %s — deactivated for the rest of the day",
                                device.name, done_reason,
                            )
                    elif device.is_active:
                        _LOGGER.debug(
                            "%s: %s — deactivation waiting for anti-flicker",
                            device.name, done_reason,
                        )
                    allocations.append(SurplusAllocation(
                        device_id=device.device_id,
                        device_name=device.name,
                        priority=device.priority,
                        allocated_watts=0.0,
                        actual_consumption_watts=device.get_current_consumption() if device.is_active else 0.0,
                        state=DeviceState.ACTIVE.value if device.is_active else DeviceState.IDLE.value,
                    ))
                    continue

            # (#620) Tier 1 — daytime battery assist. A "Solar + battery"
            # device (battery_assist_enabled) sees the raw surplus PLUS the
            # battery-assist budget, but ONLY while the battery is above the
            # Buffer SoC — mirrors the EV Solar Gate (#537/#545): the battery
            # tops the device up out of the surplus-above-buffer it would
            # otherwise export, never below the buffer. Off-flag / below-buffer
            # → headroom is 0 and this is identical to pre-#620.
            effective_surplus = remaining_surplus + self._tier1_headroom_w(device)
            if effective_surplus >= device.min_power_threshold and not device.is_active:
                # Only activate if device is in "surplus" mode
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue  # peak_only: never proactively turn on
                if peak_freeze:
                    continue  # #508 W2: don't add load while peak is at risk
                if device.can_activate():
                    consumed = await device.activate(remaining_surplus)
                    if consumed > 0:
                        device.record_activated()
                        device.reset_surplus_timer()
                        # (#620) if the battery covered a shortfall for this
                        # assist device, subtract that from the running budget.
                        if getattr(device, "battery_assist_enabled", False):
                            batt_covered = max(0.0, consumed - max(0.0, remaining_surplus))
                            self._tier1_budget_left = max(
                                0.0, self._tier1_budget_left - batt_covered)
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
                # (#559) off-peak-forced devices run WITHOUT surplus by
                # design — the force-expiry section and the peak shed pass
                # own their lifecycle; the deficit LIFO must not flap them off.
                # (#620) same for a Tier-2 overnight-battery forced device: it
                # runs off the battery by design and is only ended by its OWN
                # terms (reserve SoC / day rollover), never by the deficit LIFO.
                if device._offpeak_forced or getattr(
                        device, "_batt_overnight_forced", False):
                    continue
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
                        # Cascade: deactivate dependents (#122)
                        for dep in self.get_dependents(device.device_id):
                            if dep.is_active and dep.can_deactivate():
                                dep_consumption = dep.get_current_consumption()
                                await dep.deactivate()
                                if not dep.is_active:
                                    dep.record_deactivated()
                                    remaining_surplus += dep_consumption
                                    active_count -= 1
                                    _LOGGER.info(
                                        "Cascade deactivated %s (depends on %s)",
                                        dep.name, device.name,
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

        # #508 W2 — peak shed pass. On SHEDDING/EMERGENCY, back the
        # controller's own active discretionary (SURPLUS-mode) devices off
        # by reverse priority. EMERGENCY sheds every one this cycle;
        # SHEDDING sheds one per cycle so the load-manager + surplus
        # back-off don't overshoot together. Externally-managed devices
        # (the EV) are already excluded by ``get_devices_sorted``; the load
        # manager owns the EV's peak shedding via ``shed_priority`` (#470).
        # (#620) A Tier-2 overnight-battery device is NOT exempt here: the peak
        # limit is a HARD grid ceiling that overrides the battery tiers. Shedding
        # it relieves grid import; once peak clears the Tier-2 pass re-activates
        # it. We clear its force marker so the shed device carries no stale state.
        if peak_shed:
            for device in reversed(devices):
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                if not device.is_active or not device.can_deactivate():
                    continue
                consumption = device.get_current_consumption()
                await device.deactivate()
                if not device.is_active:
                    device.record_deactivated()
                    device._batt_overnight_forced = False
                    device._batt_overnight_forced_date = None
                    active_count = max(0, active_count - 1)
                    remaining_surplus += consumption
                    _LOGGER.info(
                        "Peak %s: shed %s (priority %d) to relieve %.0fW",
                        peak_state, device.name, device.priority, consumption,
                    )
                    for a in allocations:
                        if a.device_id == device.device_id:
                            a.allocated_watts = 0.0
                            a.actual_consumption_watts = 0.0
                            a.state = DeviceState.IDLE.value
                    if not peak_shed_all:
                        break  # SHEDDING: gentle, one device per cycle
                else:
                    _LOGGER.debug(
                        "Peak shed of %s blocked by anti-flicker", device.name,
                    )

        # Check for scheduled devices that must start (deadline approaching).
        # #508 W2: deliberately NOT gated on peak_freeze — a deadline is a
        # hard commitment that must run regardless of peak posture (like a
        # critical device), and the one-cycle import is bounded by
        # rated_power. Do not add a peak gate here.
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
        # Only for "surplus" mode devices — off-peak is a form of proactive activation (#49).
        # #508 W2: suppressed while the peak is at risk — a cheap-tariff
        # runtime deficit must not push grid import over the limit.
        if price_level in ("cheap", "very_cheap", "negative") and not peak_freeze:
            for device in devices:
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                # (#559) solar_only devices NEVER grid-force — they accept
                # missing the target on a dark day (logged once per day).
                if device.top_up_policy == "solar_only":
                    continue
                if device.stop_condition_met:
                    continue
                # (arc) Respect can_activate() here too — otherwise a cheap-hours
                # top-up would re-activate a load the user just turned off,
                # bypassing the reconciler's user-respect cooldown (and the
                # device min_off anti-flicker).
                if device.needs_offpeak_activation and device.can_activate():
                    consumed = await device.activate(device.min_power_threshold)
                    if consumed > 0:
                        device._offpeak_forced = True
                        device._offpeak_forced_date = today_local
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

        # (#620) Tier 2 — overnight battery pass. A device that opted into
        # "Use battery overnight" and still has a runtime deficit may run from
        # the home battery when there is no surplus, PRIORITY-ORDERED, while
        # the battery is above the hard Reserve SoC. Distinct from the cheap-
        # hours off-peak pass (grid-sourced): this spends stored house energy,
        # so it is gated on the explicit opt-in + the Reserve floor, not price.
        # Suppressed under peak risk (same as the off-peak pass). can_activate()
        # enforces the max cap + anti-cycle, so a capped or recently-toggled
        # device is skipped. Inert for every device with the flag off (default).
        if not peak_freeze:
            for device in devices:
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                if device.is_active or device.stop_condition_met:
                    continue
                if not device.needs_offpeak_activation:  # deficit + not capped
                    continue
                if not self._tier2_overnight_eligible(device):
                    continue
                if not device.can_activate():
                    continue
                consumed = await device.activate(device.min_power_threshold)
                if consumed > 0:
                    device._batt_overnight_forced = True  # (#620) own marker
                    device._batt_overnight_forced_date = today_local
                    active_count += 1
                    for a in allocations:
                        if a.device_id == device.device_id:
                            a.allocated_watts = consumed
                            a.actual_consumption_watts = consumed
                            a.state = DeviceState.ACTIVE.value
                            break
                    else:
                        allocations.append(SurplusAllocation(
                            device_id=device.device_id,
                            device_name=device.name,
                            priority=device.priority,
                            allocated_watts=consumed,
                            actual_consumption_watts=consumed,
                            state=DeviceState.ACTIVE.value,
                        ))
                    _LOGGER.info(
                        "#620 Tier 2: %s on battery (%.0fW, deficit %.0fs, "
                        "SoC %.0f%% > reserve %.0f%%)",
                        device.name, consumed, device.remaining_daily_runtime_sec,
                        self._batt_soc or 0.0, self._batt_reserve_soc,
                    )

        # (#559 beta.19) The deadline-critical pass was removed: it grid/
        # battery-forced with no SOC gate (HIGH-2) to hit a per-device
        # deadline. solar_only (the switch-load default) never grid-forces;
        # cheap_hours devices still top up via the off-peak pass above.

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

    def _tier1_headroom_w(self, device) -> float:
        """(#620) Tier 1 daytime battery-assist headroom for one device (W).

        Non-zero ONLY when the device opted into ``battery_assist_enabled``
        (the "Solar + battery" mode) AND the battery is above the Buffer SoC.
        Returns the assist budget the coordinator passed (the same
        surplus-above-buffer budget the EV assist uses, #537/#545) — so the
        device may activate on surplus + battery down to the buffer, never
        below it. Everything else → 0 (inert)."""
        if not getattr(device, "battery_assist_enabled", False):
            return 0.0
        soc = self._batt_soc
        if soc is None or soc <= self._batt_buffer_soc:
            return 0.0
        # Running budget: shrinks as earlier (higher-priority) battery-assist
        # loads claim it this cycle, so the battery isn't multi-spent.
        return max(0.0, min(self._batt_assist_budget_w, self._tier1_budget_left))

    def _tier2_overnight_eligible(self, device) -> bool:
        """(#620) Tier 2 — may this device draw the battery BELOW the buffer,
        down to the Reserve SoC, to meet its runtime floor when there is no
        surplus? Opt-in flag + battery strictly above the hard Reserve SoC.
        The Reserve is never crossed."""
        if not getattr(device, "battery_eligible_overnight", False):
            return False
        soc = self._batt_soc
        return soc is not None and soc > self._batt_reserve_soc

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
