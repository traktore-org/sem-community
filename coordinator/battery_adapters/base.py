"""BatteryControlAdapter protocol — battery's only command contract.

Every brand-specific service call SEM makes for batteries flows
through one method on this protocol. The actuator
(:func:`actuate_battery`) says ``await adapter.command_force_charge(...)``;
the adapter dispatches to the brand-specific HA service.

Pre-v1.7.0 the battery command surface was split across:

- ``coordinator/battery_protection.py`` (BatteryProtectionMixin) —
  discharge limiting via ``number.set_value``
- ``coordinator/battery_charge_adapter.py`` (BatteryChargeAdapter
  + brand subclasses) — forced charge via brand services

This protocol unifies both axes. New brand support: subclass
``BatteryControlAdapter``, implement the four ``command_*`` methods,
register in ``adapter_for()``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover — type-only
    from ..charger_types import BatteryIntent


class BatteryControlAdapter(ABC):
    """One adapter per battery brand. Mirrors
    :class:`ChargerAdapter` on the EV side.

    Each method maps 1:1 to a :class:`BatteryIntent`:

        NORMAL              → command_normal()
        LIMIT_DISCHARGE     → command_limit_discharge(watts)
        FORCE_CHARGE        → command_force_charge(target_soc, power_w, duration_min)
        STOP_FORCE_CHARGE   → command_stop_force_charge()

    The actuator never branches on brand; the adapter does.
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass = hass
        self._config = config
        self._last_intent: "Optional[BatteryIntent]" = None
        self._last_discharge_limit_w: float = -1.0
        """Last applied discharge limit — used by command_limit_discharge
        to de-dup consecutive same-value writes. Mirrors today's
        100 W hysteresis in BatteryProtectionMixin
        (battery_protection.py:106-109)."""

    # ─── Capability ────────────────────────────────────────────

    @property
    @abstractmethod
    def max_charge_power_w(self) -> float:
        """Brand-reported max charge power."""

    @property
    @abstractmethod
    def max_discharge_power_w(self) -> float:
        """Brand-reported max discharge power. Returned to NORMAL."""

    @property
    @abstractmethod
    def supports_forced_charge(self) -> bool:
        """True if this brand has a forced-charge service.
        ``Sonnen`` would return False — protection-only adapter."""

    @property
    def supports_forced_discharge(self) -> bool:
        """True if this brand can be commanded to discharge to the
        grid for arbitrage (#523). Default False — only brands that
        override (Huawei LUNA) actuate ``FORCE_DISCHARGE``; everyone
        else has the decision dropped by the actuator."""
        return False

    @property
    def last_intent(self) -> "Optional[BatteryIntent]":
        return self._last_intent

    # ─── Commands ──────────────────────────────────────────────

    @abstractmethod
    async def command_normal(self) -> None:
        """Restore default discharge limit (max_discharge_power_w)."""

    @abstractmethod
    async def command_limit_discharge(self, watts: float) -> None:
        """Hold discharge to ``watts``. Implementations apply
        hysteresis — if ``watts`` is within ±100 W of the last
        applied value, skip the HA service call."""

    @abstractmethod
    async def command_force_charge(
        self,
        target_soc: float,
        charge_power_w: float,
        duration_min: int,
    ) -> None:
        """Start a forced grid → battery charge."""

    @abstractmethod
    async def command_stop_force_charge(self) -> None:
        """Cancel an active forced charge."""

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        """Start a forced battery → grid discharge for arbitrage (#523).

        Default no-op: brands without forced-discharge support never
        reach here (the actuator gates on ``supports_forced_discharge``).
        Huawei overrides this.
        """
        return None

    async def command_stop_force_discharge(self) -> None:
        """End a forced discharge, restoring the brand default.
        Default delegates to ``command_normal``."""
        await self.command_normal()
