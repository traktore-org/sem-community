"""GoodWeBatteryAdapter — GoodWe inverters.

GoodWe uses mode-based forced charge ("Eco Charge" mode) rather than
a direct service call. Discharge limit still uses ``number.set_value``
where supported.
"""
from __future__ import annotations

import logging

from ..charger_types import BatteryIntent
from ..power_control import async_write_power_setpoint
from .base import BatteryControlAdapter

_LOGGER = logging.getLogger(__name__)


class GoodWeBatteryAdapter(BatteryControlAdapter):
    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._discharge_control_entity = config.get(
            "battery_discharge_control_entity", "",
        )
        self._max_discharge_w = float(
            config.get("battery_max_discharge_power", 5000),
        )
        # Lazy import the existing forced-charge adapter
        from .force_charge import GoodWeChargeAdapter
        self._charge_adapter = GoodWeChargeAdapter(hass, config)

    @property
    def max_charge_power_w(self) -> float:
        return float(self._config.get("battery_max_charge_power", 5000))

    @property
    def max_discharge_power_w(self) -> float:
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        return True

    async def command_normal(self) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, watts: float) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        watts = max(0.0, min(watts, self._max_discharge_w))
        if (self._last_discharge_limit_w >= 0
                and abs(watts - self._last_discharge_limit_w) < 100.0):
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
        await self._apply_discharge_limit(watts)
        self._last_intent = BatteryIntent.LIMIT_DISCHARGE

    async def command_force_charge(
        self, target_soc: float, charge_power_w: float, duration_min: int,
    ) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        from .force_charge import ChargeCommand, ChargeCommandStatus
        cmd = ChargeCommand(
            target_soc=target_soc,
            max_power_w=charge_power_w,
            duration_minutes=duration_min,
        )
        # #589 3b (honest result): record FORCE_CHARGE only when the delegate
        # didn't FAIL — a failed charge must retry next cycle, not masquerade
        # as charging. Mirrors the huawei/generic adapters.
        status = await self._charge_adapter.start_forced_charge(cmd)
        if getattr(status, "status", None) is ChargeCommandStatus.FAILED:
            self._last_error = "start_forced_charge failed"
        else:
            self._last_error = None
            self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        # Already stopped — stay silent (#757, command_off pattern base.py:187):
        # re-issuing the work-mode restore every idle cycle floods the link
        # (the #538 failure, one layer up). Stop on the transition, then no-op.
        if self._last_intent is BatteryIntent.STOP_FORCE_CHARGE:
            return
        ok = await self._write_force_discharge(0.0)  # #523 mutual exclusion
        from .force_charge import ChargeCommandStatus
        status = await self._charge_adapter.stop_forced_charge()
        # #757 honest retry: a failed stop must not record the intent, or the
        # guard above would suppress the retry (#589 class 4).
        if status.status is ChargeCommandStatus.FAILED:
            self._last_error = f"stop_forced_charge failed: {status.message}"
            return
        if not ok:
            self._last_error = "mutual-exclusion zero-write failed on stop"
            return
        self._last_error = None
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE

    async def _apply_discharge_limit(self, watts: float) -> None:
        if not self._discharge_control_entity:
            self._last_discharge_limit_w = watts
            return
        if await async_write_power_setpoint(
            self._hass,
            self._discharge_control_entity,
            watts,
            context="GoodWe battery discharge limit",
        ):
            self._last_discharge_limit_w = watts
