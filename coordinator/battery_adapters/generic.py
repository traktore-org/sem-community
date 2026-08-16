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
from ..power_control import async_write_power_setpoint
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
        # #523 (Rien, beta.42): map each per-battery MODE to the right Sessy
        # power strategy. ``eco`` is NOT self-consumption — ``nom`` (zero-on-
        # meter) is — so Auto / Self-consumption must set ``nom``, and ``Off``
        # must idle the battery, not leave it in ``eco``. Force charge/discharge
        # keep using ``_strategy_active`` (api). All configurable for other
        # AC-coupled brands.
        self._strategy_self_consume = config.get(
            "battery_strategy_self_consume_value", "nom")
        self._strategy_off = config.get("battery_strategy_off_value", "idle")
        self._last_strategy = None
        # #523: AC-coupled batteries (Sessy, …) expose ONE bidirectional power
        # setpoint — the same ``battery_force_discharge_control_entity`` that
        # SEM writes a positive value to for discharge takes a NEGATIVE value
        # to charge. There is no separate force-charge switch, so the
        # switch-based GenericChargeAdapter can't drive them. When this flag is
        # set, force-charge writes ``-power`` to that same setpoint (gated by
        # strategy → active), mirroring force-discharge's ``+power``.
        self._setpoint_bidirectional = bool(
            config.get("battery_setpoint_bidirectional", False),
        )
        # #523: the user's own strategy before SEM took control (e.g. a Sessy
        # running ``nom``/``roi`` for self-consumption). Captured when SEM
        # switches to the active value and restored when SEM releases — so we
        # don't clobber their normal mode with the ``eco`` fallback.
        self._restore_strategy: "Optional[str]" = None
        # True once SEM has switched the strategy to the active/API value this
        # episode. Distinguishes "SEM took control → must hand it back" from
        # "SEM never touched it → leave the user's mode alone" (#523).
        self._took_control: bool = False
        # Lazy import for delegate
        try:
            from .force_charge import GenericChargeAdapter
            self._charge_adapter = GenericChargeAdapter(hass, config)
        except Exception:  # noqa: BLE001
            self._charge_adapter = None
        # #531: adopt a stranded API strategy left by a prior instance.
        self._detect_stranded_strategy()

    def _detect_stranded_strategy(self) -> None:
        """Detect a strategy left in the active/API value across a reload.

        If SEM is reloaded mid-discharge/arbitrage episode, a fresh adapter
        starts ``_took_control=False`` and would never hand the strategy
        back — stranding an AC-coupled battery in API (setpoint-controlled)
        instead of self-consumption. If the strategy entity is already at the
        active value at construction, the previous instance left it there:
        adopt control so the next NORMAL/STOP restores cleanly. The user's
        true prior mode is unrecoverable across the reload, so release falls
        to the idle default (the documented unreadable-prior fallback).
        """
        if not self._strategy_entity:
            return
        try:
            st = self._hass.states.get(self._strategy_entity)
        except Exception:  # noqa: BLE001
            return
        cur = getattr(st, "state", None)
        if isinstance(cur, str) and cur == self._strategy_active:
            self._took_control = True
            self._last_strategy = cur
            _LOGGER.info(
                "Generic battery: adopting stranded '%s' strategy on %s "
                "(reload mid-episode) — will restore idle on release",
                cur, self._strategy_entity,
            )

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

    async def _enter_active_strategy(self) -> None:
        """Capture the user's current strategy (once), mark that SEM has taken
        control, then switch to the active (API) value so the setpoint takes
        effect."""
        if self._strategy_entity and not self._took_control:
            st = self._hass.states.get(self._strategy_entity)
            cur = getattr(st, "state", None)
            # Only remember a real, restorable option — never the active value
            # itself, and not a MagicMock/unknown/unavailable.
            if (isinstance(cur, str)
                    and cur not in (self._strategy_active, "unknown",
                                    "unavailable", "")):
                self._restore_strategy = cur
            self._took_control = True
        await self._set_strategy(self._strategy_active)

    async def _release_strategy(self) -> None:
        """Hand strategy control back. Only restore a strategy SEM actually
        CHANGED (captured the user's prior value when it switched to the
        active/API value). If SEM never took control, leave the user's
        strategy alone — forcing the configured idle default (e.g. ``eco``)
        would clobber their self-consumption mode (e.g. Sessy ``nom`` =
        zero-on-meter), which stops the battery charging from solar surplus
        (#523: battery sat idle at 20 % SOC while 1 kW of surplus exported).

        When SEM DID take control, hand it back to the captured prior mode —
        or the configured idle fallback if the prior was unreadable (never
        leave the battery stranded in API)."""
        if not self._took_control:
            return
        await self._set_strategy(self._restore_strategy or self._strategy_idle)
        self._restore_strategy = None
        self._took_control = False

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        # Switch to the active (API) strategy BEFORE writing the setpoint —
        # an AC-coupled battery ignores the setpoint in eco/self-consumption.
        await self._enter_active_strategy()
        await super().command_force_discharge(power_w, floor_soc)

    @property
    def max_charge_power_w(self) -> float:
        return float(self._config.get("battery_max_charge_power", 5000))

    @property
    def max_discharge_power_w(self) -> float:
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        # A bidirectional setpoint can charge via a negative value on the
        # same entity — no charge switch needed (#523, Sessy).
        if self._setpoint_bidirectional and self._force_discharge_entity:
            return True
        return bool(self._force_charge_switch and self._target_soc_entity)

    async def command_normal(self) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        # AC-coupled (Sessy): self-consumption is its OWN power strategy
        # (``nom`` = zero-on-meter), NOT the setpoint. Actively set it so a
        # battery left in eco/api/idle by a prior mode returns to self-
        # consuming — #523 (Rien): Auto / Self-consumption used to leave the
        # Sessy stuck in ``eco`` (which doesn't self-consume). De-dup'd, so a
        # battery already in ``nom`` isn't re-written.
        await self._set_strategy(self._strategy_self_consume)
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_off(self) -> None:
        """#523 (Rien): a Sessy in 'Off' should sit IDLE (no charge/discharge),
        not self-consume and not stay in ``eco``. Set the idle power strategy
        and zero the setpoint, then stay silent (one-shot like the base). A
        non-AC-coupled battery (no strategy entity) has no native idle — defer
        to the base hands-off behaviour."""
        if self._last_intent is BatteryIntent.OFF:
            return
        if not self._strategy_entity:
            await super().command_off()
            return
        await self._write_force_discharge(0.0)
        await self._set_strategy(self._strategy_off)
        self._last_intent = BatteryIntent.OFF

    async def command_limit_discharge(self, watts: float) -> None:
        await self._write_force_discharge(0.0)  # #523 mutual exclusion
        await self._set_strategy(self._strategy_self_consume)
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
        # #523 AC-coupled bidirectional setpoint (Sessy): charge = NEGATIVE
        # power on the same setpoint entity. Set the active strategy first
        # (the setpoint is ignored in self-consumption mode) then write the
        # negative value — the mirror of command_force_discharge.
        if self._setpoint_bidirectional and self._force_discharge_entity:
            await self._enter_active_strategy()
            watts = max(0.0, min(float(charge_power_w), self.max_charge_power_w))
            ok = await self._write_force_discharge(-watts)
            if ok:
                self._last_error = None
                self._last_intent = BatteryIntent.FORCE_CHARGE
            else:
                self._last_error = "bidirectional charge write failed"
                # _last_intent intentionally NOT updated — retry next cycle (#589)
            return
        ok_zero = await self._write_force_discharge(0.0)  # #523 mutual exclusion
        if not ok_zero:
            self._last_error = "mutual-exclusion zero-write failed"
            return
        if self._charge_adapter is None:
            _LOGGER.warning(
                "GenericBatteryAdapter: no forced-charge backend — "
                "command_force_charge ignored",
            )
            return
        from .force_charge import ChargeCommand, ChargeCommandStatus
        cmd = ChargeCommand(
            target_soc=target_soc,
            max_power_w=charge_power_w,
            duration_minutes=duration_min,
        )
        status = await self._charge_adapter.start_forced_charge(cmd)
        if status.status is ChargeCommandStatus.FAILED:
            self._last_error = f"start_forced_charge failed: {status.message}"
            # _last_intent intentionally NOT updated — retry next cycle (#589)
        else:
            self._last_error = None
            self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        if self._force_charge_already_stopped():
            return  # (#757) already stopped — a repeat is noise, not a command
        ok = await self._write_force_discharge(0.0)  # #523 mutual exclusion
        # Back to self-consumption (nom), not the old eco/idle release.
        await self._set_strategy(self._strategy_self_consume)
        if self._charge_adapter is not None:
            from .force_charge import ChargeCommandStatus
            status = await self._charge_adapter.stop_forced_charge()
            # #757 honest retry: a failed stop must not record the intent, or
            # the guard above would suppress the retry (#589 class 4).
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
            context="Generic battery discharge limit",
        ):
            self._last_discharge_limit_w = watts
