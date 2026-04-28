"""Battery forced charge adapter — abstracts inverter-specific force-charge commands.

Provides a unified interface for commanding grid-to-battery charging across
different inverter platforms (Huawei, SolarEdge, GoodWe, Fronius, SolAX, DEYE).

Each platform has its own service call or entity to trigger forced charging.
The adapter auto-detects the platform from config and dispatches accordingly.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ChargeCommandStatus(Enum):
    """Status of a forced charge command."""

    IDLE = "idle"
    CHARGING = "charging"
    TARGET_REACHED = "target_reached"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass
class ChargeCommand:
    """Parameters for a forced grid-to-battery charge command."""

    target_soc: float  # 0-100%
    max_power_w: float  # Max charge power in watts
    duration_minutes: int = 480  # Safety timeout (default 8h)


@dataclass
class ChargeStatus:
    """Current status of the battery charge adapter."""

    status: ChargeCommandStatus
    current_soc: float = 0.0
    target_soc: float = 0.0
    charge_power_w: float = 0.0
    message: str = ""


class BatteryChargeAdapter(ABC):
    """Abstract base class for inverter-specific forced charge control."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.config = config
        self._active = False
        self._target_soc: float = 0.0

    @property
    def is_active(self) -> bool:
        """Whether a forced charge session is currently active."""
        return self._active

    @abstractmethod
    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Start forced grid-to-battery charging.

        Returns status indicating success or failure.
        """

    @abstractmethod
    async def stop_forced_charge(self) -> ChargeStatus:
        """Stop forced charging and restore normal operation."""

    @abstractmethod
    async def get_status(self) -> ChargeStatus:
        """Get current charge status (SOC, power, active state)."""

    def should_stop(self, current_soc: float) -> bool:
        """Check if target SOC has been reached."""
        if not self._active:
            return False
        return current_soc >= self._target_soc


class HuaweiChargeAdapter(BatteryChargeAdapter):
    """Huawei SUN2000 + LUNA2000 forced charge via huawei_solar integration.

    Uses the `huawei_solar.forcible_charge_soc` service which sets:
    - Target SOC
    - Charge power (limited by AC coupling, typically 2.5-5 kW)
    - Duration (max 1440 min)
    """

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Start forced charge via huawei_solar.forcible_charge_soc."""
        device_id = self.config.get("inverter_device_id", "")
        if not device_id:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message="No inverter_device_id configured",
            )

        try:
            await self.hass.services.async_call(
                "huawei_solar",
                "forcible_charge_soc",
                {
                    "device_id": device_id,
                    "target_soc": int(command.target_soc),
                    "power": int(command.max_power_w),
                    "duration": command.duration_minutes,
                },
            )
            self._active = True
            self._target_soc = command.target_soc
            _LOGGER.info(
                "Huawei forced charge started: target=%d%%, power=%dW, duration=%dmin",
                command.target_soc,
                command.max_power_w,
                command.duration_minutes,
            )
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING,
                target_soc=command.target_soc,
                charge_power_w=command.max_power_w,
                message="Forced charge active",
            )
        except Exception as exc:
            _LOGGER.error("Failed to start Huawei forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Service call failed: {exc}",
            )

    async def stop_forced_charge(self) -> ChargeStatus:
        """Stop forced charge via huawei_solar.stop_forcible_charge."""
        device_id = self.config.get("inverter_device_id", "")
        if not device_id:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message="No inverter_device_id configured",
            )

        try:
            await self.hass.services.async_call(
                "huawei_solar",
                "stop_forcible_charge",
                {"device_id": device_id},
            )
            self._active = False
            self._target_soc = 0.0
            _LOGGER.info("Huawei forced charge stopped")
            return ChargeStatus(
                status=ChargeCommandStatus.IDLE,
                message="Forced charge stopped",
            )
        except Exception as exc:
            _LOGGER.error("Failed to stop Huawei forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Stop failed: {exc}",
            )

    async def get_status(self) -> ChargeStatus:
        """Read current SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        if not soc_entity:
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
                message="No SOC entity configured",
            )

        state = self.hass.states.get(soc_entity)
        current_soc = 0.0
        if state and state.state not in ("unknown", "unavailable"):
            try:
                current_soc = float(state.state)
            except (ValueError, TypeError):
                pass

        if self._active and current_soc >= self._target_soc:
            return ChargeStatus(
                status=ChargeCommandStatus.TARGET_REACHED,
                current_soc=current_soc,
                target_soc=self._target_soc,
                message=f"Target SOC {self._target_soc}% reached",
            )

        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
            current_soc=current_soc,
            target_soc=self._target_soc,
        )


class GoodWeChargeAdapter(BatteryChargeAdapter):
    """GoodWe inverter forced charge via work mode entity.

    GoodWe uses a select entity to switch between work modes.
    Forced charge = "Eco Charge" or "General" mode with SOC target.
    """

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Start forced charge by setting work mode and SOC target."""
        work_mode_entity = self.config.get("inverter_work_mode_entity", "")
        soc_target_entity = self.config.get("battery_target_soc_entity", "")

        if not work_mode_entity:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message="No inverter_work_mode_entity configured",
            )

        try:
            if soc_target_entity:
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": soc_target_entity, "value": int(command.target_soc)},
                )

            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": work_mode_entity, "option": "Eco Charge"},
            )

            self._active = True
            self._target_soc = command.target_soc
            _LOGGER.info("GoodWe forced charge started: target=%d%%", command.target_soc)
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING,
                target_soc=command.target_soc,
                message="Eco Charge mode active",
            )
        except Exception as exc:
            _LOGGER.error("Failed to start GoodWe forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Service call failed: {exc}",
            )

    async def stop_forced_charge(self) -> ChargeStatus:
        """Restore normal work mode."""
        work_mode_entity = self.config.get("inverter_work_mode_entity", "")
        normal_mode = self.config.get("inverter_normal_work_mode", "General")

        try:
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": work_mode_entity, "option": normal_mode},
            )
            self._active = False
            self._target_soc = 0.0
            return ChargeStatus(
                status=ChargeCommandStatus.IDLE,
                message=f"Restored {normal_mode} mode",
            )
        except Exception as exc:
            _LOGGER.error("Failed to stop GoodWe forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Stop failed: {exc}",
            )

    async def get_status(self) -> ChargeStatus:
        """Read SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        current_soc = 0.0

        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    current_soc = float(state.state)
                except (ValueError, TypeError):
                    pass

        if self._active and current_soc >= self._target_soc:
            return ChargeStatus(
                status=ChargeCommandStatus.TARGET_REACHED,
                current_soc=current_soc,
                target_soc=self._target_soc,
            )

        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
            current_soc=current_soc,
            target_soc=self._target_soc,
        )


class GenericChargeAdapter(BatteryChargeAdapter):
    """Generic adapter for inverters with a simple charge switch + SOC target.

    Works with any inverter that exposes:
    - A switch entity to enable/disable forced charging
    - A number entity for target SOC
    """

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Enable forced charge switch and set SOC target."""
        charge_switch = self.config.get("battery_force_charge_switch", "")
        soc_target_entity = self.config.get("battery_target_soc_entity", "")

        if not charge_switch:
            return ChargeStatus(
                status=ChargeCommandStatus.UNSUPPORTED,
                message="No battery_force_charge_switch configured",
            )

        try:
            if soc_target_entity:
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": soc_target_entity, "value": int(command.target_soc)},
                )

            await self.hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": charge_switch},
            )

            self._active = True
            self._target_soc = command.target_soc
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING,
                target_soc=command.target_soc,
                message="Force charge switch enabled",
            )
        except Exception as exc:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Failed: {exc}",
            )

    async def stop_forced_charge(self) -> ChargeStatus:
        """Disable forced charge switch."""
        charge_switch = self.config.get("battery_force_charge_switch", "")

        try:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": charge_switch},
            )
            self._active = False
            self._target_soc = 0.0
            return ChargeStatus(
                status=ChargeCommandStatus.IDLE,
                message="Force charge switch disabled",
            )
        except Exception as exc:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Stop failed: {exc}",
            )

    async def get_status(self) -> ChargeStatus:
        """Read SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        current_soc = 0.0

        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    current_soc = float(state.state)
                except (ValueError, TypeError):
                    pass

        if self._active and current_soc >= self._target_soc:
            return ChargeStatus(
                status=ChargeCommandStatus.TARGET_REACHED,
                current_soc=current_soc,
                target_soc=self._target_soc,
            )

        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
            current_soc=current_soc,
            target_soc=self._target_soc,
        )


def create_charge_adapter(
    hass: HomeAssistant, config: dict
) -> BatteryChargeAdapter:
    """Factory: create the appropriate charge adapter based on config/platform.

    Detection order:
    1. Explicit config key 'battery_charge_platform'
    2. Auto-detect from available integrations
    """
    platform = config.get("battery_charge_platform", "auto")

    if platform == "huawei" or (
        platform == "auto" and _has_integration(hass, "huawei_solar")
    ):
        return HuaweiChargeAdapter(hass, config)

    if platform == "goodwe" or (
        platform == "auto" and _has_integration(hass, "goodwe")
    ):
        return GoodWeChargeAdapter(hass, config)

    # Fallback to generic switch-based adapter
    return GenericChargeAdapter(hass, config)


def _has_integration(hass: HomeAssistant, domain: str) -> bool:
    """Check if a HA integration is loaded."""
    try:
        return domain in hass.config.components
    except AttributeError:
        return False
