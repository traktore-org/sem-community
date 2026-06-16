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
        # Forced battery→grid discharge (#523). Real Huawei LUNA2000 has NO
        # "forcible discharge power" NUMBER entity — it's driven by the
        # ``huawei_solar.forcible_discharge_soc`` SERVICE (device_id +
        # target_soc + power), the discharge mirror of the forced-charge
        # service this adapter already uses. We override the base number-
        # write path to call that service when an inverter device_id is
        # configured; if instead a number entity is wired
        # (``battery_force_discharge_control_entity``) the base path is used.
        self._inverter_device_id = config.get("inverter_device_id", "")
        # Target SOC (reserve floor) for the in-flight forced discharge.
        self._fd_floor_soc = 0.0
        # Whether a forcible discharge is currently active. The LUNA2000
        # BLOCKS if it gets stop_forcible_charge + another Modbus write
        # (e.g. the discharge-limit register) back-to-back in one cycle, so
        # every transition issues exactly ONE command and defers the rest to
        # the next cycle. This flag is the state that makes that possible.
        self._forcible_discharging = False
        # Stop-retry budget. Huawei Modbus writes are queued and can be
        # dropped / reordered under a flaky connection — a single
        # stop_forcible_charge sometimes doesn't land, leaving the battery
        # discharging. After exiting forcible we re-issue the (idempotent)
        # stop for a few extra cycles so it self-heals. forcible_discharge_soc
        # also self-terminates at target_soc=reserve, so this is belt-and-
        # braces over an already-bounded action.
        self._stop_retries = 0

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

    @property
    def supports_forced_discharge(self) -> bool:
        # Service-based (inverter device_id) OR a wired number entity.
        return bool(self._inverter_device_id) or bool(self._force_discharge_entity)

    # ─── Forced discharge: huawei_solar service (no number entity) ──────

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        """Sell to grid via ``huawei_solar.forcible_discharge_soc`` —
        discharge at ``power_w`` until SOC falls to ``floor_soc`` (the
        reserve). Issued ONCE; while already discharging at ~this power the
        call is a no-op (re-hammering the inverter blocks the LUNA2000)."""
        self._fd_floor_soc = floor_soc
        watts = max(0.0, min(float(power_w), self._max_discharge_w))
        if not self._inverter_device_id:
            # No service → number-entity fallback (a user who wired one).
            await super().command_force_discharge(power_w, floor_soc)
            self._forcible_discharging = bool(self._force_discharge_entity)
            return
        if self._forcible_discharging and abs(watts - self._last_force_discharge_w) < 100.0:
            self._last_intent = BatteryIntent.FORCE_DISCHARGE
            return
        try:
            await self._hass.services.async_call(
                "huawei_solar", "forcible_discharge_soc",
                {
                    "device_id": self._inverter_device_id,
                    "target_soc": int(floor_soc),
                    "power": int(watts),
                }, blocking=True,
            )
            self._forcible_discharging = True
            self._last_force_discharge_w = watts
            _LOGGER.info(
                "Huawei battery: forcible discharge %.0f W to SOC %d%% "
                "(manual sell / arbitrage)", watts, int(floor_soc),
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Huawei battery: forcible_discharge_soc failed: %s", e,
            )
        self._last_intent = BatteryIntent.FORCE_DISCHARGE

    async def command_stop_force_discharge(self) -> None:
        await self._stop_forcible()
        self._last_intent = BatteryIntent.STOP_FORCE_DISCHARGE

    async def _stop_forcible(self) -> bool:
        """Stop an active forcible discharge — ONE Modbus command, nothing
        else. Returns True if it issued a stop, so the caller does NOTHING
        else this cycle (a second write right after stop_forcible_charge
        makes the LUNA2000 ignore the stop / block). No-op when not
        currently forcing, so it's safe to call from every command."""
        if not self._forcible_discharging:
            return False
        ok = await self._issue_stop()
        if not ok and self._inverter_device_id:
            return False  # service raised — keep forcing, retry next cycle
        self._forcible_discharging = False
        self._last_force_discharge_w = 0.0
        # Re-issue the stop on the next couple of NORMAL cycles — a single
        # Modbus stop can be dropped/reordered on a flaky link.
        self._stop_retries = 2
        return True

    async def _issue_stop(self) -> bool:
        """Raw stop (service or number-entity). True on success."""
        if self._inverter_device_id:
            try:
                await self._hass.services.async_call(
                    "huawei_solar", "stop_forcible_charge",
                    {"device_id": self._inverter_device_id}, blocking=True,
                )
                _LOGGER.info("Huawei battery: stopped forcible discharge")
                return True
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Huawei battery: stop_forcible_charge failed: %s", e,
                )
                return False
        await super()._write_force_discharge(0.0)
        return True

    # ─── Commands ──────────────────────────────────────────────

    async def command_normal(self) -> None:
        """Restore discharge to max — undoes any LIMIT_DISCHARGE in effect.
        If exiting a forcible discharge, issue ONLY the stop this cycle (the
        discharge-limit write is deferred to the next cycle — back-to-back
        Modbus writes after stop_forcible_charge block the LUNA2000)."""
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.NORMAL
            return
        # Self-healing stop retries (flaky Modbus can drop a single stop).
        if self._stop_retries > 0:
            self._stop_retries -= 1
            await self._issue_stop()
            self._last_intent = BatteryIntent.NORMAL
            return
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, watts: float) -> None:
        """Apply the 1:1 home-consumption protection limit.
        Honours 100 W hysteresis to avoid log spam."""
        # Forced discharge is mutually exclusive with limiting it (#523).
        # If forcing, stop cleanly this cycle and apply the limit next cycle.
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
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
        # Can't force-charge and force-discharge at once (#523). If a forcible
        # discharge is active, STOP it this cycle and start the charge next
        # cycle — never discharge-stop + charge-start back-to-back.
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.FORCE_CHARGE
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
        # STOP any forced op — also clears an arbitrage discharge (#523),
        # so the scheduler's idle/target-reached verdict can't leave the
        # battery silently selling to grid. Forcible discharge and forced
        # charge share the same huawei stop service, so one clean stop covers
        # both; only fall through to the charge adapter when not forcing.
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
            return
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
