"""Internal force-charge actuation per brand (#624).

Moved from ``coordinator/battery_charge_adapter.py``: these classes are
NOT a public adapter surface any more — they are the brand-specific
force-charge implementation composed by the ``BatteryControlAdapter``
subclasses in this package (see huawei.py / goodwe.py / generic.py).
No **production** module outside ``battery_adapters/`` may import them — that
is what the arch test in test_battery_charge_scheduler.py enforces, and it
scans production packages only. Tests import them directly on purpose.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

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

    # ``should_stop(current_soc)`` lived here until #659. Nothing called it.
    # The live target-reached decision is the scheduler's, made against the
    # coordinator's SOC reading (``battery_charge_scheduler.py``, "Already at
    # target SOC"). This was a second statement of the same rule, on an object
    # the scheduler doesn't consult, kept alive only by its own unit tests.
    #
    # NOTE for the next sweep: ``get_status()`` below is in the same position
    # — abstract, implemented three times, zero production callers, and it
    # computes TARGET_REACHED that nobody reads. It is out of #659's scope
    # (still UNTRIAGED in tests/test_653_orphan_methods.py) but it is the same
    # finding, not a live consumer of these fields.


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
        """Stop forced charge via huawei_solar.stop_forcible_charge.

        Deliberately unconditional (no ``_active`` short-circuit): after a
        restart the in-memory ``_active`` is False while the inverter may still
        be force-charging (an orphan from the prior lifetime), so the first
        stop MUST reach the hardware. The #757 per-cycle flood is closed one
        layer up, at ``command_stop_force_charge``'s ``_last_intent`` guard —
        which only ever calls this once, on the transition.
        """
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
        """Restore normal work mode.

        Unconditional by design — this restore is GoodWe's only boot-orphan
        clear (no persistent snapshot, no status-sensor reconcile), so after a
        restart it must fire even though the in-memory ``_active`` is False.
        The #757 per-cycle flood is closed by the ``_last_intent`` guard in
        ``command_stop_force_charge``, which calls this only on the transition.
        """
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
        """Disable forced charge switch.

        Unconditional by design — this ``turn_off`` is the generic adapter's
        only boot-orphan clear (no persistent snapshot, no status reconcile),
        so after a restart it must fire even though the in-memory ``_active``
        is False. The #757 per-cycle flood is closed by the ``_last_intent``
        guard in ``command_stop_force_charge`` (called only on the transition).
        """
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


# ``create_charge_adapter`` (and its ``_has_integration`` helper) lived here
# until #659. It was a second brand-selection factory — same platform key,
# same auto-detect order — running in parallel with the live one,
# ``battery_adapters.adapter_for`` (called from coordinator.py). Nothing in
# production ever called this copy; only its own unit tests did, which is
# what kept it looking healthy.
#
# The classes above are NOT dead: each brand adapter (huawei.py, goodwe.py,
# generic.py) constructs its matching *ChargeAdapter directly to implement
# ``command_force_charge``. It is only the selection of which one to build
# that had two implementations, and this was the invisible one — the #651
# shape. Brand selection belongs in ``adapter_for``; add new platforms there.
