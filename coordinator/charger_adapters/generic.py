"""GenericAdapter — covers Wallbox, Easee, go-eCharger, OCPP, etc.

Brands whose firmware handles ``set_current(0)`` as "stop charging"
(unlike KEBA which silently keeps the last setpoint). These adapters
are simpler: ``command_idle`` just sets current to 0; the contactor
opens because the firmware says so.

If a future user reports the KEBA quirks on a different brand
(eg. some OCPP firmware also rejects below-min), file an issue —
the answer is a dedicated adapter subclass, not a flag on this one.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..charger_types import ChargerIntent, ChargerPower
from .base import ChargerAdapter

if TYPE_CHECKING:  # pragma: no cover
    from ...devices.base import CurrentControlDevice

_LOGGER = logging.getLogger(__name__)

# Generic firmware: 6 A IEC 61851 minimum, ~0 W handshake idle.
# Brand-specific values can be overridden by subclasses.
_GENERIC_MIN_CURRENT_A = 6
_GENERIC_HANDSHAKE_POWER_W = 500.0
"""500 W keeps the same handshake threshold as KEBA — any brand
drawing more than this without an SEM command is a self-resume
anomaly regardless of brand."""


class GenericAdapter(ChargerAdapter):
    """Brand-agnostic adapter for chargers whose ``set_current(0)``
    actually stops the contactor."""

    def __init__(self, device: "CurrentControlDevice") -> None:
        super().__init__()
        self._device = device
        self._last_intent: Optional[ChargerIntent] = None

    @property
    def min_current_a(self) -> int:
        return int(getattr(self._device, "min_current", _GENERIC_MIN_CURRENT_A))

    @property
    def max_current_a(self) -> int:
        # Effective max = config max clamped to the control entity's own max,
        # so CHARGE_MAX resolves to a value the device can actually hold
        # (no perpetual clamp-drift; #536). Falls back to config max — the
        # ``isinstance`` guard keeps it robust to mock devices in tests
        # (a MagicMock attr is callable but returns a non-numeric mock).
        eff = getattr(self._device, "effective_max_current", None)
        if callable(eff):
            try:
                v = eff()
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return int(v)
            except (TypeError, ValueError):
                pass
        return int(getattr(self._device, "max_current", 32))

    @property
    def phases(self) -> int:
        return int(getattr(self._device, "phases", 3))

    @property
    def voltage(self) -> int:
        return int(getattr(self._device, "voltage", 230))

    @property
    def handshake_power_w(self) -> float:
        return _GENERIC_HANDSHAKE_POWER_W

    @property
    def can_command_zero(self) -> bool:
        # Generic brands accept set_current(0) as a stop signal.
        return True

    async def command_current(self, amps: int) -> None:
        if amps < self.min_current_a:
            await self.command_idle()
            return
        amps = min(amps, self.max_current_a)
        if not getattr(self._device, "_session_active", False):
            await self._device.start_session(energy_target_kwh=0)
        await self._device._set_current(amps)
        self._last_intent = ChargerIntent.CHARGE_AT_AMPS

    async def command_idle(self) -> None:
        # Generic: setting current to 0 is the canonical stop.
        # Also call stop_session() so any session-level cleanup runs.
        await self._device._set_current(0)
        if getattr(self._device, "_session_active", False):
            await self._device.stop_session()
        self._last_intent = ChargerIntent.IDLE

    async def command_max(self) -> None:
        await self.command_current(self.max_current_a)
        self._last_intent = ChargerIntent.CHARGE_MAX

    async def command_disable(self) -> None:
        await self._device._set_current(0)
        await self._device.stop_session()
        self._last_intent = ChargerIntent.DISABLE

    def is_self_charging(self, power: ChargerPower) -> bool:
        if power.power_w <= self.handshake_power_w:
            return False
        if self._last_intent is None:
            return True  # cold start: any power = self-resume
        return self._last_intent in (ChargerIntent.IDLE, ChargerIntent.DISABLE)

    def actual_charging(self, power: ChargerPower) -> bool:
        return power.power_w > self.handshake_power_w

    @property
    def last_intent(self) -> Optional[ChargerIntent]:
        return self._last_intent
