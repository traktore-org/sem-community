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
        # AC-coupled batteries (Sessy, …) gate the power setpoint behind a
        # "power strategy" mode select — the setpoint is IGNORED unless the
        # strategy is the active/API value (in eco/NOM the battery just self-
        # consumes). SEM switches it to the active value before forcing a
        # discharge and back to the idle/self-consumption value when done.
        self._strategy_entity = config.get("battery_strategy_control_entity", "")
        self._strategy_active = config.get("battery_strategy_active_value", "api")
        self._strategy_idle = config.get("battery_strategy_idle_value", "eco")
        self._last_strategy = None
        # Lazy import for delegate
        try:
            from ..battery_charge_adapter import GenericChargeAdapter
            self._charge_adapter = GenericChargeAdapter(hass, config)
        except Exception:  # noqa: BLE001
            self._charge_adapter = None

    async def _set_strategy(self, value: str) -> None:
        """Switch the battery's power-strategy mode (no-op without a strategy
        entity, de-dup'd on the last value)."""
        if not self._strategy_entity or value == self._last_strategy:
            return
        # Domain-aware: real batteries expose a ``select.*`` strategy; a user
        # may also point it at an ``input_select.*`` helper. Both have
        # ``select_option``.
        domain = self._strategy_entity.split(".", 1)[0]
        if domain not in ("select", "input_select"):
            domain = "select"
        try:
            await self._hass.services.async_call(
                domain, "select_option",
                {"entity_id": self._strategy_entity, "option": value},
                blocking=True,
            )
            self._last_strategy = value
            _LOGGER.info(
                "Generic battery: power strategy → %s (%s)",
                value, self._strategy_entity,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Generic battery: failed to set strategy: %s", e)

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        # Switch to the active (API) strategy BEFORE writing the setpoint —
        # an AC-coupled battery ignores the setpoint in eco/self-consumption.
        await self._set_strategy(self._strategy_active)
        await super().command_force_discharge(power_w, floor_soc)

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
        # Hand control back to the battery's own self-consumption (eco) — for
        # an AC-coupled battery this is what makes "Self-consumption only" work.
        await self._set_strategy(self._strategy_idle)
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, watts: float) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        await self._set_strategy(self._strategy_idle)
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
        await self._set_strategy(self._strategy_idle)
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
