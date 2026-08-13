"""Pure-dispatch actuate_battery(decision, adapter) (Group B Step 4).

Mirrors :func:`actuate` for chargers. Each :class:`BatteryIntent`
maps to exactly one :class:`BatteryControlAdapter` method. No
branches on brand — the adapter does that.

Idempotency: the adapter's ``last_intent`` field lets callers
short-circuit duplicate calls. The actuator itself always
dispatches; the adapter de-dups (e.g. consecutive same-watts
LIMIT_DISCHARGE calls become one HA service call).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .charger_types import BatteryIntent
from .power_control import prepare_power_setpoint
from ..utils.log_gate import log_on_change

if TYPE_CHECKING:  # pragma: no cover
    from .battery_adapters.base import BatteryControlAdapter
    from .charger_types import BatteryDecision

_LOGGER = logging.getLogger(__name__)


async def actuate_battery(
    decision: "BatteryDecision",
    adapter: "BatteryControlAdapter",
) -> None:
    """Apply a per-battery decision through the adapter.

    Args:
        decision: The output of ``decide_battery(view)`` this cycle.
        adapter: The brand-specific adapter wrapping this battery.
    """
    if decision.intent is BatteryIntent.OFF:
        await adapter.command_off()
        log_on_change(   # (#762) transition-gated
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): OFF (hands-off) — %s",
            decision.battery_id, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.NORMAL:
        await adapter.command_normal()
        log_on_change(   # (#762) 1424 identical lines/day on .175
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): NORMAL — %s",
            decision.battery_id, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.LIMIT_DISCHARGE:
        await adapter.command_limit_discharge(decision.discharge_limit_w)
        log_on_change(   # (#762) the watts wobble; the gate strips digits
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): LIMIT_DISCHARGE %.0f W — %s",
            decision.battery_id, decision.discharge_limit_w, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.FORCE_CHARGE:
        if not adapter.supports_forced_charge:
            log_on_change(   # (#762) once per episode, not per cycle
                _LOGGER, f"actuate:{decision.battery_id}", logging.WARNING,
                "actuate_battery(%s): adapter does not support forced "
                "charge — decision dropped (%s)",
                decision.battery_id, decision.reason,
            )
            return
        await adapter.command_force_charge(
            decision.target_soc,
            decision.charge_power_w,
            decision.duration_min,
        )
        _LOGGER.debug(
            "actuate_battery(%s): FORCE_CHARGE target_soc=%.0f%% "
            "power=%.0f W duration=%dm — %s",
            decision.battery_id, decision.target_soc,
            decision.charge_power_w, decision.duration_min,
            decision.reason,
        )
        return

    if decision.intent is BatteryIntent.STOP_FORCE_CHARGE:
        await adapter.command_stop_force_charge()
        _LOGGER.debug(
            "actuate_battery(%s): STOP_FORCE_CHARGE — %s",
            decision.battery_id, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.FORCE_DISCHARGE:
        if not adapter.supports_forced_discharge:
            _LOGGER.warning(
                "actuate_battery(%s): adapter does not support forced "
                "discharge — arbitrage decision dropped (%s)",
                decision.battery_id, decision.reason,
            )
            return
        await adapter.command_force_discharge(
            decision.discharge_power_w, decision.floor_soc,
        )
        _LOGGER.info(
            "actuate_battery(%s): FORCE_DISCHARGE %.0f W (floor %.0f%%) — %s",
            decision.battery_id, decision.discharge_power_w,
            decision.floor_soc, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.STOP_FORCE_DISCHARGE:
        await adapter.command_stop_force_discharge()
        _LOGGER.debug(
            "actuate_battery(%s): STOP_FORCE_DISCHARGE — %s",
            decision.battery_id, decision.reason,
        )
        return

    _LOGGER.error(
        "actuate_battery(%s): unknown intent %r",
        decision.battery_id, decision.intent,
    )


async def restore_discharge_limit_on_startup(hass, config: dict) -> None:
    """Startup-only: push the configured max discharge limit.

    (#624 — relocated from the deleted ``BatteryProtectionMixin``.)
    After a restart the adapter's ``last_discharge_limit_w`` hysteresis
    is empty, so a stale limit left behind by a previous run could leak
    past ``decide_battery``'s NORMAL intent. This unconditionally pushes
    the configured max on startup.
    """
    # Observer mode is a hard read-only boundary. Startup restoration used to
    # bypass the normal per-cycle observer gate and could therefore write to
    # hardware before the observer switch had been synchronised.
    if config.get("observer_mode", False):
        _LOGGER.info(
            "Startup: observer mode active — battery discharge restore skipped"
        )
        return

    max_discharge = config.get("battery_max_discharge_power", 5000)

    # #691 — a multi-battery install carries PER-battery control entities
    # (``battery_discharge_control_entities``, #523); restoring only the
    # global key left each unit's stale limit in place across a restart.
    # Restore every configured surface, de-duplicated (all units of one
    # inverter bank may share a single entity).
    entities: list[str] = []
    global_ent = config.get("battery_discharge_control_entity", "")
    if global_ent:
        entities.append(global_ent)
    per_battery = config.get("battery_discharge_control_entities")
    if isinstance(per_battery, list):
        entities.extend(e for e in per_battery if e)

    for control_entity in dict.fromkeys(entities):
        prepared = prepare_power_setpoint(hass, control_entity, max_discharge)
        if prepared is None:
            continue

        if prepared.current_value < prepared.value:
            await hass.services.async_call(
                prepared.domain, "set_value",
                {"entity_id": control_entity, "value": prepared.value},
                blocking=True,
            )
            _LOGGER.info(
                "Startup: restored battery discharge limit on %s from %.3f%s "
                "to %.3f%s",
                control_entity,
                prepared.current_value,
                prepared.unit,
                prepared.value,
                prepared.unit,
            )


def active_discharge_limit(adapters) -> "float | None":
    """(#625 phase 4, extracted) The tightest ACTIVE discharge limit across
    the per-battery adapter fleet, for the discharge-limit sensor (#375).

    The protection gate fires fleet-wide on EV night charging, so in
    practice every adapter reports the same value — ``min()`` is defensive.
    ``None`` when no adapter is currently in LIMIT_DISCHARGE.
    """
    limits = [
        a._last_discharge_limit_w for a in (adapters or {}).values()
        if a.last_intent is BatteryIntent.LIMIT_DISCHARGE
        and a._last_discharge_limit_w is not None
    ]
    return min(limits) if limits else None
