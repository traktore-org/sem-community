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

import logging
from abc import ABC, abstractmethod
from typing import Optional

from ..charger_types import BatteryIntent

_LOGGER = logging.getLogger(__name__)


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
        # #523 export arbitrage — the number entity that sets the battery's
        # forcible discharge-to-grid power. Brand-agnostic: any battery whose
        # integration exposes such a number (Huawei LUNA "Forcible discharge
        # power", a Sessy/Growatt setpoint, a template/script-backed number)
        # can sell to grid. Empty → ``supports_forced_discharge`` is False
        # and the actuator drops FORCE_DISCHARGE.
        self._force_discharge_entity: str = config.get(
            "battery_force_discharge_control_entity", "",
        )
        # de-dup writes. None = never written (so the first write of any sign
        # always goes through; a plain -1.0 sentinel would alias a real
        # negative charge setpoint on a bidirectional entity, #523).
        self._last_force_discharge_w: Optional[float] = None

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
        """True when a forcible-discharge control entity is configured
        (#523) — brand-agnostic battery→grid arbitrage. No entity → the
        actuator drops FORCE_DISCHARGE."""
        return bool(self._force_discharge_entity)

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
        """Sell to grid: set the configured forcible-discharge power
        (#523), clamped to the brand's max discharge. Brand-agnostic —
        any battery with a discharge-power number entity can use it."""
        watts = max(0.0, min(float(power_w), self.max_discharge_power_w))
        await self._write_force_discharge(watts)
        self._last_intent = BatteryIntent.FORCE_DISCHARGE

    async def command_stop_force_discharge(self) -> None:
        """Stop selling — zero the forcible-discharge power and restore
        the brand default discharge limit."""
        await self._write_force_discharge(0.0)
        await self.command_normal()
        self._last_intent = BatteryIntent.STOP_FORCE_DISCHARGE

    async def _write_force_discharge(self, watts: float) -> None:
        """De-dup'd write of the battery power setpoint. ``watts`` is a
        SIGNED setpoint on a bidirectional control entity: ``> 0`` =
        discharge to grid (the #523 arbitrage path), ``< 0`` = charge from
        grid (AC-coupled Sessy-style bidirectional setpoint), ``0`` = idle.
        Mutual exclusion is the callers' job: ``command_normal`` /
        ``command_limit_discharge`` / ``command_force_charge`` /
        ``command_stop_force_charge`` zero this so the battery can't keep
        selling once SEM moves to any other mode."""
        if not self._force_discharge_entity:
            return
        # Skip when within 100 W of the last applied value — the 0→0 case
        # (the common NORMAL cycle) must not spam the bus.
        if (self._last_force_discharge_w is not None
                and abs(watts - self._last_force_discharge_w) < 100.0):
            return
        try:
            # Domain-aware: real-hardware setpoints are ``number.*`` (Huawei
            # forcible-discharge, Growatt/Sessy power numbers), but a user may
            # also wire an ``input_number.*`` helper. Both expose ``set_value``;
            # route to the control entity's own domain so either works.
            domain = self._force_discharge_entity.split(".", 1)[0]
            if domain not in ("number", "input_number"):
                domain = "number"
            await self._hass.services.async_call(
                domain, "set_value",
                {"entity_id": self._force_discharge_entity, "value": watts},
                blocking=True,
            )
            self._last_force_discharge_w = watts
            if watts > 0:
                _LOGGER.info(
                    "Battery: forcible-discharge %.0f W → %s (arbitrage)",
                    watts, self._force_discharge_entity,
                )
            elif watts < 0:
                _LOGGER.info(
                    "Battery: forcible-charge %.0f W → %s "
                    "(bidirectional setpoint)",
                    -watts, self._force_discharge_entity,
                )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Battery: failed to set forcible discharge: %s", e,
            )
