"""GenericBatteryAdapter — brand-agnostic fallback.

Works with any inverter that exposes:
- A number entity for the battery discharge limit
- (optionally) A switch entity to force charge + a number entity
  for the SOC target

If forced-charge entities aren't configured, the adapter still
serves NORMAL / LIMIT_DISCHARGE (the reactive protection only).
"""
from __future__ import annotations

import logging

from ..charger_types import BatteryIntent
from .base import BatteryControlAdapter

_LOGGER = logging.getLogger(__name__)


class GenericBatteryAdapter(BatteryControlAdapter):
    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._discharge_control_entity = config.get(
            "battery_discharge_control_entity", "",
        )
        self._max_discharge_w = float(
            config.get("battery_max_discharge_power", 5000),
        )
        self._force_charge_switch = config.get(
            "battery_force_charge_switch", "",
        )
        self._target_soc_entity = config.get("battery_target_soc_entity", "")
        # Lazy import for delegate
        try:
            from ..battery_charge_adapter import GenericChargeAdapter
            self._charge_adapter = GenericChargeAdapter(hass, config)
        except Exception:  # noqa: BLE001
            self._charge_adapter = None

    @property
    def max_charge_power_w(self) -> float:
        return float(self._config.get("battery_max_charge_power", 5000))

    @property
    def max_discharge_power_w(self) -> float:
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        return bool(self._force_charge_switch and self._target_soc_entity)

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
        if self._charge_adapter is None:
            _LOGGER.warning(
                "GenericBatteryAdapter: no forced-charge backend — "
                "command_force_charge ignored",
            )
            return
        from ..battery_charge_adapter import ChargeCommand
        cmd = ChargeCommand(
            target_soc=target_soc,
            charge_power_w=charge_power_w,
            duration_min=duration_min,
        )
        await self._charge_adapter.start_forced_charge(cmd)
        self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        if self._charge_adapter is not None:
            await self._charge_adapter.stop_forced_charge()
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE

    async def _apply_discharge_limit(self, watts: float) -> None:
        if not self._discharge_control_entity:
            self._last_discharge_limit_w = watts
            return
        try:
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": self._discharge_control_entity, "value": watts},
                blocking=True,
            )
            self._last_discharge_limit_w = watts
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Generic battery: failed to set discharge limit: %s", e,
            )
