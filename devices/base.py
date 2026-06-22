"""Controllable device base classes for surplus-based energy management.

Uniform device abstraction where ALL consumers
are managed through a priority queue with minimum power thresholds.

Device Types:
- SwitchDevice: on/off (hot water relay, smart plugs)
- CurrentControlDevice: variable current (EV chargers)
- SetpointDevice: numerical target (heat pump temp, battery)
- ScheduleDevice: start signal with deadline (dishwasher, washer)
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

# #392: KEBA's failsafe watchdog (and similar device-side timers on other
# chargers) requires periodic *writes* to refresh — reads alone don't
# count. SEM's _set_current dedup used to suppress writes when the
# commanded value hadn't changed, which silently starved the watchdog
# during steady-state charging until the device dropped to fallback and
# charging halted. A same-value re-write at the refresh interval keeps it fed.
#
# The interval is a DEVICE capability, not a global constant: the failsafe
# timeout varies per brand and per user config. The generic default below
# assumed a 300 s KEBA failsafe (heartbeat at 1/5 of it). PROD showed a KEBA
# P30 whose failsafe trips near ~60 s — so a 60 s heartbeat RACES it
# (max_current oscillating 6↔12 A every ~60 s while SEM held 12 A, exporting
# the unused surplus). ``watchdog_refresh_interval_s`` resolves the real
# interval per charger, set comfortably under the shortest common failsafe.
DEFAULT_WRITE_HEARTBEAT_INTERVAL_S = 60.0
# Back-compat alias (older imports / tests reference this name).
WRITE_HEARTBEAT_INTERVAL_S = DEFAULT_WRITE_HEARTBEAT_INTERVAL_S
# Brands whose device-side failsafe can trip under the generic 60 s heartbeat.
# Refresh below the shortest common failsafe timeout so a steady-state command
# can't starve it. KEBA is set BELOW the ~10 s coordinator cycle so a steady
# command is re-asserted EVERY cycle — PROD showed a KEBA P30 reverting to its
# 6 A failsafe current in well under 30 s (offered current oscillating 6↔9/12 A,
# pausing the car to ~120 W), so 30 s still raced it. Per-cycle re-writes outrun
# any failsafe with a timeout ≥ ~1 cycle; a box that reverts sub-cycle is a
# device-side failsafe-config problem SEM cannot out-write.
_BRAND_WATCHDOG_REFRESH_S = {
    "keba": 5.0,
}

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class DeviceState(Enum):
    """Device operational state."""
    IDLE = "idle"
    ACTIVE = "active"
    BLOCKED = "blocked"
    ERROR = "error"
    SCHEDULED = "scheduled"


class DeviceType(Enum):
    """Device control type."""
    SWITCH = "switch"
    CURRENT_CONTROL = "current_control"
    SETPOINT = "setpoint"
    SCHEDULE = "schedule"


class DeviceControlMode(Enum):
    """How SEM is allowed to control this device (#49).

    Hierarchy: off < peak_only < surplus
    Each level adds capability on top of the previous.

    - off:            SEM monitors but never controls this device
    - peak_only:      SEM can shed (turn off) to protect peak limit,
                      restores to pre-shed state. Never proactively turns on.
    - surplus:        SEM activates when surplus available, deactivates when
                      surplus drops. Also includes peak protection (shedding).

    Stopping surplus charging at a target (kWh or SOC %) is handled separately
    by the per-charger Max ceiling (``*_max``) of the charge-target range (#245),
    not by a control mode.
    """
    OFF = "off"
    PEAK_ONLY = "peak_only"
    SURPLUS = "surplus"


@dataclass
class DeviceStatus:
    """Current status of a controllable device."""
    state: DeviceState = DeviceState.IDLE
    current_consumption_w: float = 0.0
    allocated_power_w: float = 0.0
    last_activated: Optional[datetime] = None
    last_deactivated: Optional[datetime] = None
    error_message: Optional[str] = None
    activation_count: int = 0


class ControllableDevice(ABC):
    """Base class for all controllable devices in the surplus management system.

    Each device has a priority (1=highest, 10=lowest) and a minimum power
    threshold that must be met before the device is activated.

    The surplus controller iterates devices by priority, allocating surplus
    to each device that meets its minimum threshold.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
    ):
        self.hass = hass
        self.device_id = device_id
        self.name = name
        self.priority = max(1, min(10, priority))
        self.min_power_threshold = min_power_threshold
        self.entity_id = entity_id
        self.power_entity_id = power_entity_id
        self._status = DeviceStatus()
        self._enabled = True
        self._managed_externally = False
        self.control_mode = DeviceControlMode.PEAK_ONLY  # Default: peak protection only (#49)

        # Power-change cooldown
        self._min_power_change_interval: float = 0.0  # seconds, 0 = disabled
        self._last_power_change_time: Optional[datetime] = None

        # Anti-cycling: minimum on/off duration (protects compressors, relays)
        self.min_on_seconds: int = 0   # 0 = disabled. E.g., 300 for heat pump
        self.min_off_seconds: int = 0  # 0 = disabled. E.g., 180 for heat pump
        self._last_activated: Optional[datetime] = None
        self._last_deactivated: Optional[datetime] = None

        # Sustained surplus: require surplus for N seconds before activation
        self.activation_delay_seconds: int = 0  # 0 = activate immediately
        self._surplus_since: Optional[datetime] = None

        # Daily runtime tracking (Feature 2)
        self.daily_min_runtime_sec: int = 0  # 0 = disabled
        self._daily_runtime_accumulated_sec: float = 0.0
        self._daily_runtime_last_check: Optional[datetime] = None
        self._daily_runtime_meter_day: Optional[date] = None
        self._offpeak_forced: bool = False

        # Appliance dependencies (#122): device only activates when dependencies are met
        self.depends_on: List[str] = []  # device_ids that must be active
        self.dependency_mode: str = "must_active"  # must_active | must_inactive
        self._controller = None  # set by SurplusController after registration

    @property
    def device_type(self) -> DeviceType:
        """Return the device type."""
        raise NotImplementedError

    @property
    def is_active(self) -> bool:
        """Return True if device is currently consuming power."""
        return self._status.state == DeviceState.ACTIVE

    def _brand_key(self) -> str:
        """Best-effort charger brand token from the configured service /
        entities (e.g. ``keba`` from ``keba.set_current``). Empty when
        unknown."""
        svc = (getattr(self, "charger_service", "") or "").strip().lower()
        if "." in svc:
            brand = svc.split(".", 1)[0]
            if brand:
                return brand
        # Fallback: sniff entity ids / device name for a known brand token.
        blob = " ".join(
            x for x in (
                (getattr(self, "current_entity_id", "") or "").lower(),
                (getattr(self, "charger_service_entity_id", "") or "").lower(),
                (getattr(self, "name", "") or "").lower(),
            ) if x
        )
        for token in _BRAND_WATCHDOG_REFRESH_S:
            if token in blob:
                return token
        return ""

    @property
    def watchdog_refresh_interval_s(self) -> float:
        """Max seconds between identical writes before the charger's
        device-side failsafe watchdog may trip. ``_set_current`` re-writes the
        same value at this cadence to keep the watchdog fed (#392). Brand-aware:
        KEBA's failsafe needs a faster refresh than the generic default.
        ``_watchdog_refresh_override_s`` (set from config when present) wins, for
        unusual failsafe settings."""
        override = getattr(self, "_watchdog_refresh_override_s", None)
        if override:
            try:
                val = float(override)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
        return _BRAND_WATCHDOG_REFRESH_S.get(
            self._brand_key(), DEFAULT_WRITE_HEARTBEAT_INTERVAL_S,
        )

    @property
    def is_enabled(self) -> bool:
        """Return True if device is enabled for surplus control."""
        return self._enabled

    @property
    def managed_externally(self) -> bool:
        """When True, SurplusController skips this device (managed by coordinator directly)."""
        return self._managed_externally

    @managed_externally.setter
    def managed_externally(self, value: bool) -> None:
        self._managed_externally = value

    @property
    def status(self) -> DeviceStatus:
        """Return current device status."""
        return self._status

    # --- Power-change cooldown helpers ---

    def _is_power_change_allowed(self) -> bool:
        """Check if enough time has passed since last power change."""
        if self._min_power_change_interval <= 0:
            return True
        if self._last_power_change_time is None:
            return True
        elapsed = (datetime.now() - self._last_power_change_time).total_seconds()
        return elapsed >= self._min_power_change_interval

    def _record_power_change(self) -> None:
        """Record that a power change just occurred."""
        self._last_power_change_time = datetime.now()

    # --- Daily runtime tracking helpers ---

    def update_daily_runtime(self, meter_day: date) -> None:
        """Accumulate runtime if device is active. Called every coordinator cycle."""
        now = datetime.now()

        # Reset on meter day rollover
        if self._daily_runtime_meter_day is not None and meter_day != self._daily_runtime_meter_day:
            _LOGGER.debug(
                "%s: daily runtime reset (%.0fs) on meter day rollover",
                self.name, self._daily_runtime_accumulated_sec,
            )
            self._daily_runtime_accumulated_sec = 0.0
            self._daily_runtime_last_check = now
        self._daily_runtime_meter_day = meter_day

        if self._daily_runtime_last_check is not None and self.is_active:
            elapsed = (now - self._daily_runtime_last_check).total_seconds()
            if 0 < elapsed <= 120:  # ignore jumps > 120s (restart recovery)
                self._daily_runtime_accumulated_sec += elapsed

        self._daily_runtime_last_check = now

    @property
    def remaining_daily_runtime_sec(self) -> float:
        """Seconds of runtime still needed to meet daily target."""
        return max(0, self.daily_min_runtime_sec - self._daily_runtime_accumulated_sec)

    @property
    def needs_offpeak_activation(self) -> bool:
        """True if device has a runtime deficit, is enabled, and not already active."""
        if self.daily_min_runtime_sec <= 0:
            return False
        if not self._enabled:
            return False
        if self.is_active:
            return False
        return self.remaining_daily_runtime_sec > 0

    @property
    def daily_energy_budget_kwh(self) -> float:
        """Energy budget implied by rated power and runtime target."""
        rated = getattr(self, "rated_power", 0)
        return rated * self.daily_min_runtime_sec / 3_600_000

    def enable(self) -> None:
        """Enable device for surplus control."""
        self._enabled = True

    def disable(self) -> None:
        """Disable device from surplus control."""
        self._enabled = False

    @abstractmethod
    async def activate(self, available_watts: float) -> float:
        """Activate device with available surplus power.

        Args:
            available_watts: Power available for this device.

        Returns:
            Actual power consumed by the device (W).
        """

    @abstractmethod
    async def deactivate(self) -> None:
        """Deactivate the device."""

    @abstractmethod
    async def adjust_power(self, available_watts: float) -> float:
        """Adjust device power level (for variable-power devices).

        Args:
            available_watts: New power available for this device.

        Returns:
            Actual power consumed after adjustment (W).
        """

    def can_activate(self) -> bool:
        """Check if device can be activated (respects dependencies, min_off, activation_delay)."""
        # Dependency check (#122): all depends_on devices must be in required state
        if not self._check_dependencies():
            return False
        if self.min_off_seconds > 0 and self._last_deactivated:
            elapsed = (datetime.now() - self._last_deactivated).total_seconds()
            if elapsed < self.min_off_seconds:
                return False
        # Sustained surplus check: surplus must persist for activation_delay_seconds
        if self.activation_delay_seconds > 0:
            if self._surplus_since is None:
                self._surplus_since = datetime.now()
                return False
            elapsed = (datetime.now() - self._surplus_since).total_seconds()
            if elapsed < self.activation_delay_seconds:
                return False
        return True

    def _check_dependencies(self) -> bool:
        """Check if all dependency constraints are satisfied (#122)."""
        if not self.depends_on or not self._controller:
            return True
        for dep_id in self.depends_on:
            dep_device = self._controller.get_device(dep_id)
            if dep_device is None:
                continue  # Unknown device — don't block
            dep_active = dep_device.status.state == DeviceState.ACTIVE
            if self.dependency_mode == "must_active" and not dep_active:
                return False
            if self.dependency_mode == "must_inactive" and dep_active:
                return False
        return True

    @property
    def blocked_by_dependency(self) -> Optional[str]:
        """Return the device_id blocking this device, or None if not blocked."""
        if not self.depends_on or not self._controller:
            return None
        for dep_id in self.depends_on:
            dep_device = self._controller.get_device(dep_id)
            if dep_device is None:
                continue
            dep_active = dep_device.status.state == DeviceState.ACTIVE
            if self.dependency_mode == "must_active" and not dep_active:
                return dep_id
            if self.dependency_mode == "must_inactive" and dep_active:
                return dep_id
        return None

    def reset_surplus_timer(self) -> None:
        """Reset surplus timer when surplus drops below device threshold."""
        self._surplus_since = None

    def can_deactivate(self) -> bool:
        """Check if device can be deactivated (respects min_on_seconds)."""
        if self.min_on_seconds > 0 and self._last_activated:
            elapsed = (datetime.now() - self._last_activated).total_seconds()
            if elapsed < self.min_on_seconds:
                return False
        return True

    def record_activated(self) -> None:
        """Record activation timestamp for anti-cycling."""
        self._last_activated = datetime.now()

    def record_deactivated(self) -> None:
        """Record deactivation timestamp for anti-cycling."""
        self._last_deactivated = datetime.now()

    def get_current_consumption(self) -> float:
        """Get current power consumption from HA entity or estimate."""
        if self.power_entity_id:
            state = self.hass.states.get(self.power_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        return self._status.current_consumption_w

    def to_dict(self) -> Dict[str, Any]:
        """Serialize device info for sensors/diagnostics."""
        d = {
            "device_id": self.device_id,
            "name": self.name,
            "type": self.device_type.value,
            "priority": self.priority,
            "min_power_threshold": self.min_power_threshold,
            "state": self._status.state.value,
            "current_consumption_w": self._status.current_consumption_w,
            "allocated_power_w": self._status.allocated_power_w,
            "enabled": self._enabled,
            "activation_count": self._status.activation_count,
        }
        if self.daily_min_runtime_sec > 0:
            d.update({
                "daily_min_runtime_sec": self.daily_min_runtime_sec,
                "daily_runtime_accumulated_sec": round(self._daily_runtime_accumulated_sec, 1),
                "remaining_daily_runtime_sec": round(self.remaining_daily_runtime_sec, 1),
                "daily_energy_budget_kwh": round(self.daily_energy_budget_kwh, 3),
                "offpeak_forced": self._offpeak_forced,
            })
        # Dependency info (#122)
        if self.depends_on:
            d["depends_on"] = self.depends_on
            d["dependency_mode"] = self.dependency_mode
            blocked = self.blocked_by_dependency
            d["blocked_by"] = blocked
        return d


class SwitchDevice(ControllableDevice):
    """On/off device (hot water relay, smart plugs, etc.).

    When surplus >= min_power_threshold, the switch is turned on.
    When surplus drops, the switch is turned off.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        min_on_time: int = 300,
        min_off_time: int = 60,
        daily_min_runtime_sec: int = 0,
    ):
        super().__init__(
            hass, device_id, name, priority,
            min_power_threshold or rated_power,
            entity_id, power_entity_id,
        )
        self.rated_power = rated_power
        self.min_on_time = min_on_time
        self.min_off_time = min_off_time
        self.daily_min_runtime_sec = daily_min_runtime_sec

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SWITCH

    async def activate(self, available_watts: float) -> float:
        if not self.entity_id:
            return 0.0

        # Anti-flicker: check minimum off time
        if self._status.last_deactivated:
            elapsed = (datetime.now() - self._status.last_deactivated).total_seconds()
            if elapsed < self.min_off_time:
                return 0.0

        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_on",
                {"entity_id": self.entity_id},
                blocking=True,
            )
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            self._status.last_activated = datetime.now()
            self._status.activation_count += 1
            _LOGGER.info("Activated switch device %s (%dW)", self.name, self.rated_power)
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to activate %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

    async def deactivate(self) -> None:
        if not self.entity_id:
            return

        # Anti-flicker: check minimum on time
        if self._status.last_activated:
            elapsed = (datetime.now() - self._status.last_activated).total_seconds()
            if elapsed < self.min_on_time:
                return

        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_off",
                {"entity_id": self.entity_id},
                blocking=True,
            )
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._status.allocated_power_w = 0.0
            self._status.last_deactivated = datetime.now()
            _LOGGER.info("Deactivated switch device %s", self.name)
        except Exception as e:
            _LOGGER.error("Failed to deactivate %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)

    async def adjust_power(self, available_watts: float) -> float:
        # Switch devices are on/off only - no adjustment possible
        if self.is_active:
            return self.rated_power
        return 0.0


class CurrentControlDevice(ControllableDevice):
    """Variable-current device (EV chargers).

    Power is proportionally adjusted based on available surplus.
    Supports multi-phase charging with configurable current limits.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        priority: int = 5,
        min_current: float = 6.0,
        max_current: float = 32.0,
        phases: int = 3,
        voltage: float = 230.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        current_entity_id: Optional[str] = None,
        charger_service: Optional[str] = None,
        charger_service_entity_id: Optional[str] = None,
        min_power_change_interval: float = 30.0,
    ):
        min_power = min_current * phases * voltage
        super().__init__(
            hass, device_id, name, priority, min_power,
            entity_id, power_entity_id,
        )
        self.min_current = min_current
        self.max_current = max_current
        self.phases = phases
        self.voltage = voltage
        self.current_entity_id = current_entity_id
        # #523 (RienduPre): a valid HA service is always ``domain.service``.
        # A junk value with no dot (his Wallbox config carried a stray
        # ``charger_service='0'`` — a leftover that even propagated to a
        # sibling whose own config was None) used to reach the service
        # branch and crash ``domain, service = charger_service.split('.', 1)``
        # with "not enough values to unpack" on EVERY 10 s cycle, blocking
        # current control even though a perfectly good ``current_entity_id``
        # number was configured. Treat a dot-less service as absent so
        # control correctly falls through to the number entity. Guards all
        # three split sites (set_current / start / stop) at once.
        if isinstance(charger_service, str) and "." not in charger_service:
            if charger_service.strip():
                _LOGGER.warning(
                    "%s: ignoring invalid charger_service %r (not a "
                    "'domain.service') — using entity control instead",
                    name, charger_service,
                )
            charger_service = None
        self.charger_service = charger_service
        self.charger_service_entity_id = charger_service_entity_id
        self.service_param_name: str = "current"  # Overridden per integration (#82)
        self.service_device_id: Optional[str] = None  # For Easee/Zaptec device_id
        self.needs_pilot_cycle: bool = False  # True = disable/enable cycle for session start
        self.global_services: bool = True  # True = services don't need entity_id (KEBA-style)
        # Start/stop control — per-integration (#82)
        # Entities: switch/button/select entity_ids for start/stop
        self.start_stop_entity: Optional[str] = None  # switch or button entity
        self.charge_mode_entity: Optional[str] = None  # select entity (go-e, OpenWB)
        self.charge_mode_start: Optional[str] = None  # select option for "start"
        self.charge_mode_stop: Optional[str] = None  # select option for "stop"
        # Service-based start/stop (Easee action_command)
        self.start_service: Optional[str] = None  # e.g. "easee.action_command"
        self.start_service_data: Optional[Dict] = None  # e.g. {"action_command": "resume"}
        self.stop_service: Optional[str] = None
        self.stop_service_data: Optional[Dict] = None
        # Phase switching (1p/3p)
        self.min_phases: int = 1
        self.max_phases: int = phases
        self.phase_switch_entity: Optional[str] = None  # Entity to call for switching
        self._phase_switch_hysteresis_up: float = 500  # W above 3p threshold to switch up
        self._phase_switch_hysteresis_down: float = 200  # W below 3p threshold to switch down
        self._current_setpoint: float = 0.0
        # #392: monotonic timestamp of the last successful write to the
        # device's current-control surface. Used by _set_current to decide
        # whether to skip a same-value write (recent) or force a heartbeat
        # refresh (interval elapsed).
        self._last_write_at: float = 0.0
        # #462 follow-up: consecutive set-current failures → Repair issue
        # at 3 (cleared on the next successful write).
        self._actuation_failures: int = 0
        self._actuation_repair_raised: bool = False
        # #485 H5: whether this instance has cleared a possible STALE
        # persistent Repair left by a previous device instance.
        self._stale_repair_checked: bool = False
        self._session_active: bool = False
        self._min_power_change_interval = min_power_change_interval

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.CURRENT_CONTROL

    async def check_phase_switch(self, available_watts: float) -> None:
        """Switch between 1-phase and 3-phase based on available surplus.

        1-phase min = 6A × 230V = 1380W (usable with small surplus)
        3-phase min = 6A × 3 × 230V = 4140W (needs large surplus)

        Switches down when surplus drops below 3-phase minimum.
        Switches up when surplus exceeds 3-phase minimum + hysteresis.
        """
        if not self.phase_switch_entity or self.min_phases == self.max_phases:
            return

        three_phase_min = self.min_current * self.max_phases * self.voltage

        if self.phases == self.max_phases and available_watts < three_phase_min - self._phase_switch_hysteresis_down:
            # Switch down to 1-phase
            await self._set_phases(self.min_phases)
            _LOGGER.info("Phase switch: %dp → %dp (surplus %.0fW < %.0fW)",
                         self.max_phases, self.min_phases, available_watts, three_phase_min)

        elif self.phases == self.min_phases and available_watts > three_phase_min + self._phase_switch_hysteresis_up:
            # Switch up to 3-phase
            await self._set_phases(self.max_phases)
            _LOGGER.info("Phase switch: %dp → %dp (surplus %.0fW > %.0fW)",
                         self.min_phases, self.max_phases, available_watts, three_phase_min)

    async def _set_phases(self, phases: int) -> None:
        """Set charging phases via entity or service."""
        self.phases = phases
        self.min_power_threshold = self.min_current * phases * self.voltage
        if self.phase_switch_entity:
            try:
                # Support switch entity (relay) or number entity
                domain = self.phase_switch_entity.split(".")[0]
                if domain == "switch":
                    action = "turn_on" if phases == self.max_phases else "turn_off"
                    await self.hass.services.async_call(
                        "switch", action,
                        {"entity_id": self.phase_switch_entity},
                        blocking=True,
                    )
                elif domain == "number":
                    await self.hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": self.phase_switch_entity, "value": phases},
                        blocking=True,
                    )
            except Exception as e:
                _LOGGER.warning("Phase switch failed: %s", e)

    def watts_to_current(self, watts: float) -> float:
        """Convert watts to amperes."""
        return watts / (self.phases * self.voltage)

    def current_to_watts(self, current: float) -> float:
        """Convert amperes to watts."""
        return current * self.phases * self.voltage

    async def activate(self, available_watts: float) -> float:
        target_current = min(
            self.max_current,
            max(self.min_current, self.watts_to_current(available_watts))
        )
        return await self._set_current(target_current)

    async def deactivate(self) -> None:
        await self._set_current(0)
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0
        self._current_setpoint = 0.0
        self._last_write_at = 0.0  # #392: reset heartbeat tracker on full stop

    async def adjust_power(self, available_watts: float) -> float:
        if not self.is_active:
            return 0.0
        # Cooldown: skip adjustment if interval hasn't elapsed
        if not self._is_power_change_allowed():
            return self._status.current_consumption_w
        target_current = min(
            self.max_current,
            max(self.min_current, self.watts_to_current(available_watts))
        )
        return await self._set_current(target_current)

    def _bound_to_entity_range(
        self, entity_id: str, current: float,
    ) -> tuple:
        """Bound a current command to the target number entity's range.

        Returns ``(bounded_current, skip_write)``. ``skip_write`` is
        True for a stop intent (``current <= 0``) on an entity whose
        minimum is above 0 — the write would be rejected by HA core's
        range validation before reaching the charger (#487), so the
        caller must rely on the adapter's stop mechanism instead.
        Unreadable entities/attributes leave the command untouched.
        """
        state = self.hass.states.get(entity_id) if entity_id else None
        attrs = getattr(state, "attributes", None)
        if not isinstance(attrs, dict):
            return current, False

        def _as_float(value):
            # Real numerics/strings only — duck-typed mocks support
            # __float__ and would fabricate bounds.
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    return None
            return None

        ent_min = _as_float(attrs.get("min"))
        ent_max = _as_float(attrs.get("max"))

        if current <= 0:
            return current, bool(ent_min is not None and ent_min > 0)
        if ent_max is not None and current > ent_max:
            current = ent_max
        if ent_min is not None and current < ent_min:
            current = ent_min
        return current, False

    def effective_max_current(self) -> float:
        """Highest current SEM can ACTUALLY command — the configured
        ``max_current`` clamped to the control number entity's own max.

        A charger configured at 32 A whose ``number.*_max_charging_current``
        entity caps at 16 A can only be driven to 16 A. Resolving CHARGE_MAX
        to the hardware 32 A made the reconciler command 32, the device clamp
        to 16, and the two never converge → a perpetual false 'drift' that
        spammed ``WRITE 32A`` + ``clamping 32 A → 16 A`` every cycle (#536
        logs). Service-controlled chargers (KEBA) have no current entity, so
        this returns the configured max unchanged.
        """
        eff = float(self.max_current)
        ent = self.current_entity_id
        if not ent:
            return eff
        attrs = getattr(self.hass.states.get(ent), "attributes", None)
        if isinstance(attrs, dict):
            ent_max = attrs.get("max")
            if ent_max is not None and not isinstance(ent_max, bool):
                try:
                    eff = min(eff, float(ent_max))
                except (TypeError, ValueError):
                    pass
        return eff

    async def _set_current(self, current: float) -> float:
        """Set charging current via entity or service."""
        current = round(current, 0)

        # #392 heartbeat dedup: skip the write only when the value didn't
        # change AND we've written recently. Without the time guard, a long
        # steady-state period (always_max holding 16 A, solar plateau) would
        # silently starve KEBA's failsafe watchdog → device drops to fallback
        # current → SEM still thinks it commanded 16 A and never re-writes.
        # Forcing a same-value re-write at WRITE_HEARTBEAT_INTERVAL_S keeps
        # the device watchdog refreshed and re-converges state after any
        # silent device-side reset (replug, KEBA reboot, failsafe trip).
        now = time.monotonic()
        if (
            abs(current - self._current_setpoint) < 1.0
            and self.is_active
            and (now - self._last_write_at) < self.watchdog_refresh_interval_s
        ):
            return self._status.current_consumption_w

        # Entity-platform services have strict schemas — sending the
        # per-integration param name produced "extra keys not allowed"
        # on EVERY command (#462, RienduPre, for number.set_value).
        # Generalized to the whole misconfigured-but-recoverable shape
        # (#485 K1): input_number.set_value and select.select_option
        # configured as the charger service bounced identically.
        _svc = (self.charger_service or "").strip().lower()
        _entity_svc_domain = _svc.split(".", 1)[0] if "." in _svc else ""

        # #487: HA core validates number writes against the ENTITY's
        # min/max BEFORE anything reaches the charger. Wallbox exposes
        # min=6 (IEC 61851), so writing 0 A to stop is structurally
        # impossible — it raised out_of_range every idle cycle (167×
        # in RienduPre's log) and, since the actuation Repair landed,
        # would false-trip it. Likewise a configured max above the
        # entity's max (Links: 6-16 A) bounced every ramp-up command.
        # Bound the write to the entity's range; a 0 A stop intent
        # skips the write entirely — the actual stop is the adapter's
        # job (pause switch / stop_session), and the number entity
        # cannot express it.
        _entity_target = None
        if _entity_svc_domain in ("number", "input_number"):
            _entity_target = self.current_entity_id or self.charger_service_entity_id
        elif not self.charger_service and self.current_entity_id:
            _entity_target = self.current_entity_id
        skip_entity_write = False
        if _entity_target:
            bounded, skip_entity_write = self._bound_to_entity_range(
                _entity_target, current,
            )
            if not skip_entity_write and bounded != current:
                _LOGGER.debug(
                    "%s: clamping commanded %.0f A into %s's range → %.0f A",
                    self.name, current, _entity_target, bounded,
                )
                current = bounded

        try:
            if skip_entity_write:
                # Stop intent on a number entity that can't express 0 A.
                _LOGGER.debug(
                    "%s: 0 A stop not writable to %s (entity min > 0) — "
                    "relying on the adapter stop path (pause switch / "
                    "stop_session) (#487)",
                    self.name, _entity_target,
                )
            elif _entity_svc_domain in ("number", "input_number"):
                # Map it to the entity write it was meant to be.
                target = self.current_entity_id or self.charger_service_entity_id
                await self.hass.services.async_call(
                    _entity_svc_domain, "set_value",
                    {"entity_id": target, "value": current},
                    blocking=True,
                )
            elif _entity_svc_domain == "select":
                # Amps exposed as a select: options are amp strings.
                target = self.current_entity_id or self.charger_service_entity_id
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": target, "option": str(int(current))},
                    blocking=True,
                )
            elif self.charger_service:
                # Service-based control — param name varies per integration (#82)
                domain, service = self.charger_service.split(".", 1)
                service_data = {self.service_param_name: current}
                # Some integrations need device_id (Easee, Zaptec)
                if self.service_device_id:
                    service_data["device_id"] = self.service_device_id
                # Pass entity_id only if service requires it (non-global services)
                elif self.charger_service_entity_id and not self.global_services:
                    service_data["entity_id"] = self.charger_service_entity_id
                await self.hass.services.async_call(
                    domain, service,
                    service_data,
                    blocking=True,
                )
            elif self.current_entity_id:
                # Number entity control
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self.current_entity_id, "value": current},
                    blocking=True,
                )

            self._clear_actuation_failure()

            self._current_setpoint = current
            self._last_write_at = now  # #392: heartbeat tracker
            self._record_power_change()
            consumed = self.current_to_watts(current) if current >= self.min_current else 0.0
            self._status.current_consumption_w = consumed
            self._status.allocated_power_w = consumed
            if current >= self.min_current:
                if not self.is_active:
                    self._status.activation_count += 1
                    self._status.last_activated = datetime.now()
                self._status.state = DeviceState.ACTIVE
            else:
                self._status.state = DeviceState.IDLE
                self._status.last_deactivated = datetime.now()
            return consumed

        except Exception as e:
            _LOGGER.error("Failed to set current on %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            self._record_actuation_failure(e)
            return self._status.current_consumption_w

    def _record_actuation_failure(self, error: Exception) -> None:
        """Track consecutive set-current failures; raise a Repair at 3.

        RienduPre's #462 install failed EVERY current command for days
        with the evidence buried in per-cycle ERROR log lines — the user
        saw "SEM doesn't react" with no actionable surface. Three
        consecutive failures now raise a user-visible Repair naming the
        device and the error; it clears on the next successful write.
        """
        self._actuation_failures += 1
        if self._actuation_failures < 3 or self._actuation_repair_raised:
            return
        self._actuation_repair_raised = True
        try:
            from ..coordinator import repair_issues as _ri
            _ri.raise_charger_actuation_failed(
                self.hass, self.device_id,
                name=self.name, error=str(error),
            )
        except Exception as exc:  # noqa: BLE001 — never fail the cycle over a repair
            _LOGGER.debug("actuation-failure repair raise failed: %s", exc)

    def _clear_actuation_failure(self) -> None:
        """Reset the failure streak; clear the Repair after a good write."""
        if self._actuation_failures == 0 and not self._actuation_repair_raised:
            # #485 H5: the Repair is persistent (survives restart) but
            # these flags are instance state. After the reload that
            # fixing the config causes, the new instance's successful
            # writes hit this early-return and the stale ERROR Repair
            # stayed in the UI forever. Delete it once per instance —
            # async_delete_issue is a no-op when no issue exists.
            if not self._stale_repair_checked:
                self._stale_repair_checked = True
                try:
                    from ..coordinator import repair_issues as _ri
                    _ri.clear_charger_actuation_failed(self.hass, self.device_id)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug("stale actuation-repair clear failed: %s", exc)
            return
        self._actuation_failures = 0
        if not self._actuation_repair_raised:
            return
        self._actuation_repair_raised = False
        try:
            from ..coordinator import repair_issues as _ri
            _ri.clear_charger_actuation_failed(self.hass, self.device_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("actuation-failure repair clear failed: %s", exc)

    async def arm_failsafe(self) -> None:
        """Set a benign device failsafe (timeout 30 s, fallback = charging
        floor) so a controller-death keeps the car at the floor instead of
        pausing, and per-cycle writes keep it from ever tripping (#392).

        KEBA failsafe rationale: the HA keba.set_failsafe service has
        failsafe_timeout min=1 (no 0/disable) and failsafe_fallback min=6 —
        so the old ``timeout=0`` raised a validation error, the call failed,
        and the box was LEFT with its existing failsafe (a 6 A fallback that
        tripped mid-charge and paused the car to ~120 W, the 6↔9 A
        oscillation the user saw). Instead set a real failsafe that can't
        bite: a generous timeout the per-cycle ``curr`` writes (#392) keep
        resetting so it never trips in normal operation, and a fallback at
        the CHARGING FLOOR (the configured min, not 6 A) so a trip on
        genuine controller-death keeps the car charging at the floor instead
        of pausing."""
        domain = (self.charger_service or "").split(".", 1)[0]
        if not domain or not self.hass.services.has_service(domain, "set_failsafe"):
            return
        try:
            fallback_a = max(6, int(round(self.min_current)))
            await self.hass.services.async_call(
                domain, "set_failsafe",
                {"failsafe_timeout": 30, "failsafe_fallback": fallback_a,
                 "failsafe_persist": 0},
                blocking=True,
            )
            _LOGGER.info("%s: KEBA failsafe set benign (timeout=30s, fallback=%dA)",
                         self.name, fallback_a)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to set charger failsafe: %s", e)

    async def start_session(self, energy_target_kwh: float = 0) -> None:
        """Start a charging session.

        Uses the charger profile to determine the correct start method (#82):
        - KEBA: service enable + optional failsafe/energy target
        - Easee: action_command service with "resume"
        - Wallbox/Heidelberg: switch entity turn_on
        - Zaptec/ChargePoint: button entity press
        - go-eCharger/OpenWB: select entity set mode
        - Fallback: probe for domain.enable service (KEBA pattern)
        """
        try:
            # 1. Profile-based start (preferred)
            if self.start_service:
                domain, service = self.start_service.split(".", 1)
                data = dict(self.start_service_data or {})
                if self.service_device_id:
                    data["device_id"] = self.service_device_id
                await self.hass.services.async_call(domain, service, data, blocking=True)
            elif self.charge_mode_entity and self.charge_mode_start:
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": self.charge_mode_entity, "option": self.charge_mode_start},
                    blocking=True,
                )
            elif self.start_stop_entity:
                domain = self.start_stop_entity.split(".")[0]
                if domain in ("switch", "input_boolean"):
                    await self.hass.services.async_call(
                        domain, "turn_on",
                        {"entity_id": self.start_stop_entity}, blocking=True,
                    )
                elif domain == "button":
                    await self.hass.services.async_call(
                        "button", "press",
                        {"entity_id": self.start_stop_entity}, blocking=True,
                    )
            elif self.charger_service:
                # 2. KEBA-style fallback: probe for enable/disable services
                domain = self.charger_service.split(".", 1)[0]

                # Arm a benign failsafe so a controller-death keeps the car
                # charging at the floor instead of pausing (#392).
                await self.arm_failsafe()

                # Set energy target if supported (KEBA)
                if energy_target_kwh > 0 and self.hass.services.has_service(domain, "set_energy"):
                    await self.hass.services.async_call(
                        domain, "set_energy", {"energy": energy_target_kwh}, blocking=True,
                    )

                # Pilot cycle: disable/enable for cars that need fresh signal
                if self.needs_pilot_cycle and self.hass.services.has_service(domain, "disable"):
                    await self.hass.services.async_call(domain, "disable", {}, blocking=True)
                    await asyncio.sleep(3)

                # Enable charger. The historically-working sequence
                # (v1.5.0–v1.6.x) is: set_failsafe → set_energy →
                # (optional pilot cycle) → enable. ``keba.authorize`` is
                # NOT in this sequence — it's an RFID-flow primitive for
                # installs that require per-session card auth, and adding
                # it speculatively risks toggling KEBA into an
                # auth-rejected state. The auth-rejected behaviour we
                # observed on PROD 2026-06-02 15:08 UTC is mitigated
                # structurally by ``ChargerAdapter.attempt_idle()`` (the
                # IDLE-debounce — see ``actuate.py``), which prevents
                # ``keba.disable`` from firing on transient solar dips.
                if self.hass.services.has_service(domain, "enable"):
                    await self.hass.services.async_call(domain, "enable", {}, blocking=True)

            self._session_active = True
            _LOGGER.info("Charging session started for %s", self.name)
        except Exception as e:
            _LOGGER.error("Failed to start session on %s: %s", self.name, e)

    async def stop_session(self) -> None:
        """Stop the charging session.

        Uses the charger profile to determine the correct stop method (#82).

        Logs which mechanism fired and warns if none did (which means we're
        relying on ``_set_current(0)`` alone to stop charging — that works
        on chargers where 0 A == pause, but NOT on KEBA where 0 A is
        documented as "minimum" and the contactor stays closed without an
        explicit ``keba.disable`` call (v1.6.3 PROD soak regression).
        """
        stop_method = None
        try:
            if self.stop_service:
                domain, service = self.stop_service.split(".", 1)
                data = dict(self.stop_service_data or {})
                if self.service_device_id:
                    data["device_id"] = self.service_device_id
                await self.hass.services.async_call(domain, service, data, blocking=True)
                stop_method = f"stop_service={self.stop_service}"
            elif self.charge_mode_entity and self.charge_mode_stop:
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": self.charge_mode_entity, "option": self.charge_mode_stop},
                    blocking=True,
                )
                stop_method = f"charge_mode={self.charge_mode_stop}"
            elif self.start_stop_entity:
                domain = self.start_stop_entity.split(".")[0]
                if domain in ("switch", "input_boolean"):
                    await self.hass.services.async_call(
                        domain, "turn_off",
                        {"entity_id": self.start_stop_entity}, blocking=True,
                    )
                    stop_method = f"{domain}.turn_off={self.start_stop_entity}"
                elif domain == "button":
                    # Stop buttons have different entity_ids than start buttons
                    # The stop entity is typically named *_stop_charging*
                    stop_entity = self.start_stop_entity.replace("resume", "stop").replace("start", "stop")
                    if "_charging" not in stop_entity:
                        stop_entity = stop_entity.replace("_stop", "_stop_charging")
                    await self.hass.services.async_call(
                        "button", "press",
                        {"entity_id": stop_entity}, blocking=True,
                    )
                    stop_method = f"button.press={stop_entity}"
            elif self.charger_service:
                # KEBA-style fallback
                domain = self.charger_service.split(".", 1)[0]
                if self.hass.services.has_service(domain, "disable"):
                    await self.hass.services.async_call(domain, "disable", {}, blocking=True)
                    stop_method = f"{domain}.disable"
                else:
                    _LOGGER.warning(
                        "stop_session(%s): charger_service=%s configured but "
                        "%s.disable service is not registered — falling back to "
                        "_set_current(0) which does NOT stop KEBA-style contactors. "
                        "Check that the underlying charger integration is loaded.",
                        self.name, self.charger_service, domain,
                    )

            await self._set_current(0)
            self._session_active = False
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._current_setpoint = 0.0
            self._last_write_at = 0.0  # #392: reset heartbeat tracker on session stop

            if stop_method is None:
                # No brand-specific stop fired — relying on _set_current(0) alone.
                # That works on Wallbox / Easee / go-e / OpenEVSE (firmware treats
                # 0 A as pause) but NOT on KEBA (0 A is "minimum", contactor stays
                # closed; needs keba.disable). Warning so this case is visible in
                # PROD logs the next time the bug class re-emerges.
                _LOGGER.warning(
                    "stop_session(%s): no brand-specific stop mechanism "
                    "configured (stop_service=None, charge_mode_entity=None, "
                    "start_stop_entity=None, charger_service=None). Relying on "
                    "_set_current(0) alone — confirm your charger firmware "
                    "treats 0 A as a stop signal, not as a minimum hold.",
                    self.name,
                )
            else:
                _LOGGER.info(
                    "Charging session stopped for %s via %s",
                    self.name, stop_method,
                )
        except Exception as e:
            _LOGGER.error("Failed to stop session on %s: %s", self.name, e)

    async def update_energy_target(self, remaining_kwh: float) -> None:
        """Update KEBA energy target mid-session (for accurate auto-stop)."""
        if not self._session_active:
            return
        try:
            if self.charger_service and "keba" in (self.charger_service or ""):
                domain = self.charger_service.split(".", 1)[0]
                await self.hass.services.async_call(
                    domain, "set_energy",
                    {"energy": max(0, remaining_kwh)},
                    blocking=True,
                )
        except Exception as e:
            _LOGGER.debug("Failed to update energy target on %s: %s", self.name, e)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "min_current": self.min_current,
            "max_current": self.max_current,
            "phases": self.phases,
            "current_setpoint": self._current_setpoint,
            "session_active": self._session_active,
            "managed_externally": self._managed_externally,
        })
        return d


class SetpointDevice(ControllableDevice):
    """Numerical setpoint device (heat pump temperature, battery charge).

    When surplus is available, the setpoint is boosted (e.g., +2C for heat pump).
    When surplus drops, the setpoint returns to normal.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        climate_entity_id: Optional[str] = None,
        min_setpoint: float = 18.0,
        max_setpoint: float = 55.0,
        normal_setpoint: float = 21.0,
        boost_offset: float = 2.0,
        min_power_change_interval: float = 300.0,
    ):
        super().__init__(
            hass, device_id, name, priority,
            min_power_threshold or rated_power,
            entity_id, power_entity_id,
        )
        self.rated_power = rated_power
        self.climate_entity_id = climate_entity_id
        self.min_setpoint = min_setpoint
        self.max_setpoint = max_setpoint
        self.normal_setpoint = normal_setpoint
        self.boost_offset = boost_offset
        self._boosted = False
        self._min_power_change_interval = min_power_change_interval

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SETPOINT

    async def activate(self, available_watts: float) -> float:
        if not self.climate_entity_id:
            return 0.0

        target = min(self.max_setpoint, self.normal_setpoint + self.boost_offset)
        try:
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self.climate_entity_id, "temperature": target},
                blocking=True,
            )
            self._boosted = True
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            self._status.last_activated = datetime.now()
            self._status.activation_count += 1
            _LOGGER.info("Boosted %s setpoint to %.1f", self.name, target)
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to boost %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

    async def deactivate(self) -> None:
        if not self.climate_entity_id or not self._boosted:
            return

        try:
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self.climate_entity_id, "temperature": self.normal_setpoint},
                blocking=True,
            )
            self._boosted = False
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._status.allocated_power_w = 0.0
            self._status.last_deactivated = datetime.now()
            _LOGGER.info("Restored %s setpoint to %.1f", self.name, self.normal_setpoint)
        except Exception as e:
            _LOGGER.error("Failed to restore %s setpoint: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)

    async def adjust_power(self, available_watts: float) -> float:
        # Setpoint devices are either boosted or not
        if not self._is_power_change_allowed():
            return self._status.current_consumption_w
        if self.is_active:
            return self.rated_power
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "normal_setpoint": self.normal_setpoint,
            "boost_offset": self.boost_offset,
            "boosted": self._boosted,
        })
        return d


class ScheduleDevice(ControllableDevice):
    """Deadline-scheduled device (dishwasher, washing machine).

    User sets a deadline and estimated runtime/energy. The scheduler
    monitors surplus and starts the appliance when sufficient solar is
    available. If the deadline approaches without enough solar, it
    starts anyway using grid power.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        deadline: Optional[datetime] = None,
        estimated_runtime_minutes: int = 120,
        estimated_energy_kwh: float = 1.0,
    ):
        super().__init__(
            hass, device_id, name, priority,
            rated_power * 0.8,  # Start when 80% of rated power available
            entity_id, power_entity_id,
        )
        self.rated_power = rated_power
        self.deadline = deadline
        self.estimated_runtime_minutes = estimated_runtime_minutes
        self.estimated_energy_kwh = estimated_energy_kwh
        self._started = False
        self._start_time: Optional[datetime] = None

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SCHEDULE

    @property
    def must_start_by(self) -> Optional[datetime]:
        """Calculate latest start time to meet deadline."""
        if not self.deadline:
            return None
        return self.deadline - timedelta(minutes=self.estimated_runtime_minutes)

    @property
    def is_deadline_approaching(self) -> bool:
        """Check if we must start now to meet deadline."""
        latest = self.must_start_by
        if not latest:
            return False
        return datetime.now() >= latest

    def schedule(
        self,
        deadline: datetime,
        estimated_runtime_minutes: int = 120,
        estimated_energy_kwh: float = 1.0,
    ) -> None:
        """Set or update the schedule."""
        self.deadline = deadline
        self.estimated_runtime_minutes = estimated_runtime_minutes
        self.estimated_energy_kwh = estimated_energy_kwh
        self._started = False
        self._start_time = None
        self._status.state = DeviceState.SCHEDULED
        _LOGGER.info(
            "Scheduled %s: deadline=%s, runtime=%dmin, energy=%.1fkWh",
            self.name, deadline, estimated_runtime_minutes, estimated_energy_kwh,
        )

    async def activate(self, available_watts: float) -> float:
        if not self.entity_id or self._started:
            return 0.0

        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_on",
                {"entity_id": self.entity_id},
                blocking=True,
            )
            self._started = True
            self._start_time = datetime.now()
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            self._status.last_activated = datetime.now()
            self._status.activation_count += 1
            _LOGGER.info("Started scheduled device %s", self.name)
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to start %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

    async def deactivate(self) -> None:
        # Scheduled devices generally should not be interrupted once started
        # Only deactivate if not yet started
        if self._started:
            _LOGGER.debug("Not deactivating %s - already running", self.name)
            return

        self._status.state = DeviceState.SCHEDULED if self.deadline else DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0

    async def adjust_power(self, available_watts: float) -> float:
        if self._started:
            return self.rated_power
        return 0.0

    def clear_schedule(self) -> None:
        """Clear the current schedule."""
        self.deadline = None
        self._started = False
        self._start_time = None
        self._status.state = DeviceState.IDLE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "estimated_runtime_minutes": self.estimated_runtime_minutes,
            "estimated_energy_kwh": self.estimated_energy_kwh,
            "started": self._started,
            "must_start_by": self.must_start_by.isoformat() if self.must_start_by else None,
            "is_deadline_approaching": self.is_deadline_approaching,
        })
        return d
