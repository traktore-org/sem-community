"""HuaweiBatteryAdapter — Huawei SUN2000 + LUNA2000.

Wraps:
- Today's HuaweiChargeAdapter (forcible_charge_soc service) for
  command_force_charge / command_stop_force_charge
- The number.set_value path that BatteryProtectionMixin used for
  command_limit_discharge / command_normal

Brand quirks:
- LUNA2000 supports power-based forced charge (not just SOC ramp)
- Discharge limit entity is brand-specific (typically
  ``number.batteries_maximale_entladeleistung``)
- Force-charge service requires target_soc + power + duration
"""
from __future__ import annotations

import logging

from ..charger_types import BatteryIntent
from .base import BatteryControlAdapter

_LOGGER = logging.getLogger(__name__)


class HuaweiBatteryAdapter(BatteryControlAdapter):
    """Huawei battery control. Delegates forced charge to the
    existing :class:`HuaweiChargeAdapter` for backward compat."""

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        # Lazy import the existing forced-charge adapter so this
        # module's imports stay lightweight + the legacy adapter
        # can be deleted later without breaking the structural
        # plan.
        from ..battery_charge_adapter import HuaweiChargeAdapter
        self._charge_adapter = HuaweiChargeAdapter(hass, config)
        # Config keys for discharge limit
        self._discharge_control_entity = config.get(
            "battery_discharge_control_entity", "",
        )
        self._max_discharge_w = float(
            config.get("battery_max_discharge_power", 5000),
        )
        # Forced battery→grid discharge (#523) is provided by the base
        # adapter, driven by ``battery_force_discharge_control_entity``
        # (huawei_solar "Forcible discharge power"). The commands below
        # zero it so other modes can't leave the battery selling.

    # ─── Capability ────────────────────────────────────────────

    @property
    def max_charge_power_w(self) -> float:
        return float(self._config.get("battery_max_charge_power", 5000))

    @property
    def max_discharge_power_w(self) -> float:
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        return True

    # supports_forced_discharge + command_force_discharge/stop are provided
    # by the base adapter (entity-driven, brand-agnostic).

    # ─── Commands ──────────────────────────────────────────────

    async def command_normal(self) -> None:
        """Restore discharge to max — undoes any LIMIT_DISCHARGE
        in effect. Idempotent: only writes if the limit differs.
        Also zeroes any active forced discharge (#523) so NORMAL is a
        true default state, not a silent continued battery→grid sale."""
        await self._write_force_discharge(0.0)
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, watts: float) -> None:
        """Apply the 1:1 home-consumption protection limit.
        Honours 100 W hysteresis to avoid log spam."""
        # Forced discharge is mutually exclusive with limiting it (#523).
        await self._write_force_discharge(0.0)
        # Clamp to [0, max]
        watts = max(0.0, min(watts, self._max_discharge_w))
        # Hysteresis (matches battery_protection.py:106-109)
        if (self._last_discharge_limit_w >= 0
                and abs(watts - self._last_discharge_limit_w) < 100.0):
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
        await self._apply_discharge_limit(watts)
        self._last_intent = BatteryIntent.LIMIT_DISCHARGE

    async def command_force_charge(
        self, target_soc: float, charge_power_w: float, duration_min: int,
    ) -> None:
        """Delegate to HuaweiChargeAdapter.start_forced_charge."""
        # Can't force-charge and force-discharge at once (#523).
        await self._write_force_discharge(0.0)
        from ..battery_charge_adapter import ChargeCommand
        cmd = ChargeCommand(
            target_soc=target_soc,
            charge_power_w=charge_power_w,
            duration_min=duration_min,
        )
        await self._charge_adapter.start_forced_charge(cmd)
        self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        # STOP any forced op — also clears an arbitrage discharge (#523),
        # so the scheduler's idle/target-reached verdict can't leave the
        # battery silently selling to grid.
        await self._write_force_discharge(0.0)
        await self._charge_adapter.stop_forced_charge()
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE

    # ─── Helpers ───────────────────────────────────────────────

    async def _apply_discharge_limit(self, watts: float) -> None:
        if not self._discharge_control_entity:
            _LOGGER.debug(
                "HuaweiBatteryAdapter: no battery_discharge_control_entity "
                "configured — skipping limit %.0f W", watts,
            )
            self._last_discharge_limit_w = watts
            return
        try:
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": self._discharge_control_entity, "value": watts},
                blocking=True,
            )
            self._last_discharge_limit_w = watts
            _LOGGER.debug(
                "Huawei battery: discharge limit %.0f W → %s",
                watts, self._discharge_control_entity,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Huawei battery: failed to set discharge limit: %s", e,
            )
