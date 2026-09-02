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


def _observe(decision: "BatteryDecision", controller=None) -> None:
    """OBSERVER mode = the layer-3 intercept for batteries, in one place.

    ``decide_battery`` already ran live; this seam records and logs the
    command it WOULD dispatch and calls no adapter method. The watts are
    read off the field the intent actually uses, so the shadow says what
    the inverter would have been told.
    """
    watts = {
        BatteryIntent.FORCE_CHARGE: decision.charge_power_w,
        BatteryIntent.FORCE_DISCHARGE: decision.discharge_power_w,
        BatteryIntent.LIMIT_DISCHARGE: decision.discharge_limit_w,
    }.get(decision.intent, 0.0)
    if controller is not None:
        try:
            controller.publish_observer_decision(
                key=f"battery:{decision.battery_id}",
                name=str(decision.battery_id),
                action=decision.intent.value,
                power_w=float(watts or 0.0),
                reason=decision.reason,
                kind="battery",
            )
        except Exception:  # noqa: BLE001 — the surface must never break the seam
            pass
    log_on_change(   # (#762) transition-gated
        _LOGGER, f"observer:battery:{decision.battery_id}", logging.INFO,
        "OBSERVER · WOULD %s %s @ %.0fW — %s",
        decision.intent.value.upper(), decision.battery_id,
        float(watts or 0.0), decision.reason,
    )


# (#818) The two intents that are decided from POWER numbers — the EV
# protection clamp and its release. Everything else here is decided
# from SOC, the plan, a schedule or the user's own mode, none of which
# a blipping power sensor can move.
_POWER_DERIVED_INTENTS = frozenset({
    BatteryIntent.LIMIT_DISCHARGE, BatteryIntent.NORMAL,
})


# (#900) The discharge limit follows the load's TREND, not its noise.
# Under LIMIT_DISCHARGE the value written is the live house load, re-decided
# every cycle; the adapters' 100 W hysteresis was narrower than a fridge, so
# a Huawei register was rewritten all day (koen71, and HA-PROD). One rule for
# every adapter: round UP to the step (coverage first — a limit below the
# house load imports from grid), raise the moment the house exceeds the
# current limit, and lower only once the load has fallen a full step plus
# the leak allowance below it. A ±150 W wobble around any level is then one
# write, not one per cycle.
DISCHARGE_LIMIT_STEP_W: float = 250.0
DISCHARGE_LIMIT_LEAK_W: float = 50.0
# Raise fast, lower slow: a drop must persist this many consecutive cycles
# before the limit follows it down. A fridge that cycles 1100 ↔ 1300 W is
# then ONE write (the first exceedance), not a write per cycle; a load that
# really fell is followed within a minute.
DISCHARGE_LIMIT_LOWER_DWELL_CYCLES: int = 6


def quantise_discharge_limit_w(raw_w: float, last_w: float) -> float:
    """The discharge limit to command for a house load of ``raw_w``.

    ``last_w`` is the limit the adapter last commanded (``-1`` when none).
    """
    import math
    raw = max(0.0, float(raw_w or 0.0))
    candidate = math.ceil(raw / DISCHARGE_LIMIT_STEP_W) * DISCHARGE_LIMIT_STEP_W
    if last_w is None or last_w < 0:
        return candidate
    if raw > last_w:
        return candidate                      # coverage first
    if last_w - raw >= DISCHARGE_LIMIT_STEP_W + DISCHARGE_LIMIT_LEAK_W:
        return candidate                      # the load really fell
    return float(last_w)                      # noise — hold


async def actuate_battery(
    decision: "BatteryDecision",
    adapter: "BatteryControlAdapter",
    *,
    observer: bool = False,
    controller=None,
    inputs_degraded: bool = False,
) -> None:
    """Apply a per-battery decision through the adapter.

    Args:
        decision: The output of ``decide_battery(view)`` this cycle.
        adapter: The brand-specific adapter wrapping this battery.
        observer: Observer mode — cut the trigger. The decision still ran
            for real; this seam only records what it WOULD command
            (see :func:`_observe`).
        controller: The :class:`SurplusController` that owns the shared
            ``observer_decisions`` surface. Optional.
    """
    if observer:
        _observe(decision, controller=controller)
        return

    # (#818) A cycle that cannot see must not flip the EV protection
    # clamp. LIMIT_DISCHARGE engages when solar surplus sits below the
    # assist gate — so on a Huawei modbus install the fabricated 0 W
    # engaged it, the source recovered 30 s later and it released, ~50
    # times a day. Each flip is a real modbus write, which is the churn
    # #538 had to make idempotent in the first place.
    #
    # Narrow on purpose: ONLY the power-derived pair, and only a CHANGE
    # between them. Force charge/discharge, OFF, arbitrage and the
    # scheduler are decided from SOC, the plan or the user's own mode,
    # and pass through a dark cycle untouched.
    if (
        inputs_degraded
        and decision.intent in _POWER_DERIVED_INTENTS
        and getattr(adapter, "last_intent", None) in _POWER_DERIVED_INTENTS
        and decision.intent is not adapter.last_intent
    ):
        log_on_change(
            _LOGGER, f"degraded:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): inputs degraded — holding %s, not "
            "flipping to %s on a blind cycle",
            decision.battery_id, adapter.last_intent, decision.intent,
        )
        return

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
        # (#900) quantised against what the adapter last commanded, so the
        # register follows the load's trend and not the fridge.
        last_w = float(getattr(adapter, "last_discharge_limit_w", -1.0) or -1.0)
        limit_w = quantise_discharge_limit_w(decision.discharge_limit_w, last_w)
        # Lowering waits for the drop to persist; raising never waits.
        streak = int(getattr(adapter, "_limit_lower_streak", 0) or 0)
        if last_w >= 0 and limit_w < last_w:
            streak += 1
            if streak < DISCHARGE_LIMIT_LOWER_DWELL_CYCLES:
                limit_w = last_w
        else:
            streak = 0
        try:
            adapter._limit_lower_streak = streak
        except Exception:  # noqa: BLE001 — a read-only stub is not a failure
            pass
        await adapter.command_limit_discharge(limit_w)
        log_on_change(   # (#762) the watts wobble; the gate strips digits
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): LIMIT_DISCHARGE %.0f W (raw %.0f W) — %s",
            decision.battery_id, limit_w, decision.discharge_limit_w, decision.reason,
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
