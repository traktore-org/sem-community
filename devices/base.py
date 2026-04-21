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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

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

    - off:       SEM monitors but never controls this device
    - peak_only: SEM can shed (turn off) to protect peak limit,
                 restores to pre-shed state. Never proactively turns on.
    - surplus:   SEM activates when surplus available, deactivates when
                 surplus drops. Also includes peak protection (shedding).
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

    @property
    def device_type(self) -> DeviceType:
        """Return the device type."""
        raise NotImplementedError

    @property
    def is_active(self) -> bool:
        """Return True if device is currently consuming power."""
        return self._status.state == DeviceState.ACTIVE

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
        """Check if device can be activated (respects min_off_seconds + activation_delay)."""
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
        self.charger_service = charger_service
        self.charger_service_entity_id = charger_service_entity_id
        self.service_param_name: str = "current"  # Overridden per integration (#82)
        self.service_device_id: Optional[str] = None  # For Easee/Zaptec device_id
        self.needs_pilot_cycle: bool = False  # True = disable/enable cycle for session start
        self.global_services: bool = True  # True = services don't need entity_id (KEBA-style)
        # Phase switching (1p/3p)
        self.min_phases: int = 1
        self.max_phases: int = phases
        self.phase_switch_entity: Optional[str] = None  # Entity to call for switching
        self._phase_switch_hysteresis_up: float = 500  # W above 3p threshold to switch up
        self._phase_switch_hysteresis_down: float = 200  # W below 3p threshold to switch down
        self._current_setpoint: float = 0.0
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

    async def _set_current(self, current: float) -> float:
        """Set charging current via entity or service."""
        current = round(current, 0)

        # Skip if no change
        if abs(current - self._current_setpoint) < 1.0 and self.is_active:
            return self._status.current_consumption_w

        try:
            if self.charger_service:
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

            self._current_setpoint = current
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
            return self._status.current_consumption_w

    async def start_session(self, energy_target_kwh: float = 0) -> None:
        """Start a charging session.

        For night charging: pass energy_target_kwh > 0 to set KEBA auto-stop.
        For solar charging: pass 0 (no auto-stop, charge as long as surplus).
        """
        try:
            if self.charger_service:
                domain = self.charger_service.split(".", 1)[0]

                # KEBA-specific: disable failsafe mode
                if self.hass.services.has_service(domain, "set_failsafe"):
                    try:
                        await self.hass.services.async_call(
                            domain, "set_failsafe",
                            {"failsafe_timeout": 0, "failsafe_fallback": 6, "failsafe_persist": False},
                            blocking=True,
                        )
                        _LOGGER.info("Charger failsafe disabled for %s", self.name)
                    except Exception as e:
                        _LOGGER.warning("Failed to disable charger failsafe: %s", e)

                # Set energy target if supported and requested
                if energy_target_kwh > 0 and self.hass.services.has_service(domain, "set_energy"):
                    await self.hass.services.async_call(
                        domain, "set_energy",
                        {"energy": energy_target_kwh},
                        blocking=True,
                    )
                    _LOGGER.info("Charger session: energy target %.1f kWh", energy_target_kwh)

                # Pilot cycle: disable/enable for cars that need fresh signal
                if self.needs_pilot_cycle and self.hass.services.has_service(domain, "disable"):
                    await self.hass.services.async_call(
                        domain, "disable", {}, blocking=True,
                    )
                    await asyncio.sleep(3)

                # Enable charger
                if self.hass.services.has_service(domain, "enable"):
                    await self.hass.services.async_call(
                        domain, "enable", {}, blocking=True,
                    )
            self._session_active = True
            _LOGGER.info("Charging session started for %s", self.name)
        except Exception as e:
            _LOGGER.error("Failed to start session on %s: %s", self.name, e)

    async def stop_session(self) -> None:
        """Stop the charging session."""
        try:
            if self.charger_service:
                domain = self.charger_service.split(".", 1)[0]
                if self.hass.services.has_service(domain, "disable"):
                    await self.hass.services.async_call(
                        domain, "disable", {}, blocking=True,
                    )
            await self._set_current(0)
            self._session_active = False
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._current_setpoint = 0.0
            _LOGGER.info("Charging session stopped for %s", self.name)
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
