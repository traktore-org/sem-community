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

from . import reason_codes as RC
from .charger_types import BatteryIntent, rewrite
from .decision_log import log_of, record_battery
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


def held_on_blind_cycle(decision, adapter, inputs_degraded: bool) -> bool:
    """(#818) Does this cycle send nothing for ``decision``? A flip between
    the power-derived pair on a cycle that cannot see is held. (#1178) The
    shared-limit rule asks it too, so a held battery counts as its last
    command, not as one it will not send."""
    return bool(
        inputs_degraded
        and decision.intent in _POWER_DERIVED_INTENTS
        and getattr(adapter, "last_intent", None) in _POWER_DERIVED_INTENTS
        and decision.intent is not adapter.last_intent
    )


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

# (#1173) …but "raise fast" made every burst two writes: up at once, down a
# minute later. PROD, 15.–23.10: 48–143 writes a night, from a kettle or a
# hob for 10–60 s, a house hovering 700–800 W across the 750 W step, and
# the house figure's own jump right after SEM moved the pack. A limit that
# follows the house (``BatteryDecision.follows_load``) now RISES only to a
# level the house has held: for the last ~1 min when that is two steps or
# more above the limit, for the last ~5 min when it is one step. While it
# waits the grid covers the rest of the house, so the pack still never
# feeds the car. Lowering is the side that keeps the pack out of the car,
# so it keeps the rule above. A target (a peak cover, the hold, the blind
# release, the cars' share) still rises at once.
DISCHARGE_LIMIT_FOLLOW_DWELL_CYCLES: int = 6
DISCHARGE_LIMIT_ONE_STEP_DWELL_CYCLES: int = 30

#: (#1069 review) A forced charge capped by the room under the grid limit
#: is RAISED only after the bigger room held this many cycles (~1 min).
#: Lowering never waits: the limit must never be exceeded. Without it a
#: room wobbling across a 250 W step re-wrote the inverter every cycle —
#: the #538 transaction-ID churn.
FORCED_CHARGE_RAISE_DWELL_CYCLES: int = 6
#: …and after a stop for no room, charging restarts only with this many
#: steps of room: one step of room would stop and start it every cycle.
FORCED_CHARGE_RESTART_STEPS: int = 2


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


def _settled_rise_w(raw_w: float, last_w: float, adapter) -> float:
    """(#1173) The limit for a ``follows_load`` decision whose house is above
    the limit in force (``last_w``).

    Keeps the houses of this rise on the adapter: the cycles in a row above
    ``last_w``, at most ``DISCHARGE_LIMIT_ONE_STEP_DWELL_CYCLES`` of them.
    After a rise only the cycles still above the new limit stay in it, and
    a write that failed leaves it whole, so the next cycle tries again at
    once. The limit rises to the level the house held over the last short
    wait if that is two steps or more, else to the level it held over the
    long wait; until then it stays ``last_w``.
    """
    import math
    raw = max(0.0, float(raw_w or 0.0))
    kept = getattr(adapter, "_limit_rise", None)
    houses: list = []
    for h in reversed(kept if isinstance(kept, tuple) else ()):
        if not h > last_w:
            break
        houses.insert(0, h)
    houses = (houses + [raw])[-DISCHARGE_LIMIT_ONE_STEP_DWELL_CYCLES:]
    _set(adapter, "_limit_rise", tuple(houses))
    step = DISCHARGE_LIMIT_STEP_W
    if len(houses) >= DISCHARGE_LIMIT_FOLLOW_DWELL_CYCLES:
        held = math.ceil(
            min(houses[-DISCHARGE_LIMIT_FOLLOW_DWELL_CYCLES:]) / step) * step
        if held - last_w >= 2 * step:
            return float(held)
    if len(houses) >= DISCHARGE_LIMIT_ONE_STEP_DWELL_CYCLES:
        return float(math.ceil(min(houses) / step) * step)
    return last_w


def _note_forced_op(adapter, attr: str, ret, landed_intent, value: bool) -> None:
    """(#1066) Record, per direction, that a forced op started or stopped.

    Only on evidence it LANDED: the adapter recorded the intent (every brand
    does on success, #589), or the command answered ``True`` (Deye's sell
    and its stop return a bool and record no intent — review). A command
    that failed leaves the flag as it was, so a stop is retried and a start
    that never happened stops nothing.

    ``decide_battery`` reads these through ``forced_ops``: the scheduler's
    stop verdict wins only while its direction is not known stopped, and a
    ``True`` is stopped before anything else. A stop routed as the OTHER
    direction (an arbitrage stop after a night charge) leaves this one
    ``True`` here — unless the stop's own NORMAL ended the charge too
    (#1181, ``BatteryControlAdapter._stop_own_charge``).
    """
    landed = ret is True or getattr(adapter, "last_intent", None) is landed_intent
    if landed:
        _set(adapter, attr, value)
    if value is False:
        # A stop: count the cycles it has not landed (#1066 review round 2 —
        # decide_battery lets protection through every other cycle after a
        # few, so a stop that can never land does not starve it for good).
        _set(adapter, "_sem_stop_misses", 0 if landed else
             int(getattr(adapter, "_sem_stop_misses", 0) or 0) + 1)
    else:
        _set(adapter, "_sem_stop_misses", 0)


async def _settle_charge_target(adapter) -> None:
    """(#1180) A charge-target value SEM has to put back and has not seen
    land is checked — and sent again when due — on a cycle that sends no
    forced charge, never by re-sending the stop. Never raises."""
    from .battery_adapters.charge_target import ChargeTargetHold
    hold = getattr(getattr(adapter, "_charge_adapter", None), "target_hold", None)
    if not isinstance(hold, ChargeTargetHold):
        return
    try:
        await hold.settle()
    except Exception:  # noqa: BLE001 — a put-back never costs a cycle
        _LOGGER.debug("charge target put-back failed", exc_info=True)


def _set(adapter, attr: str, value) -> None:
    try:
        setattr(adapter, attr, value)
    except Exception:  # noqa: BLE001 — a read-only stub is not a failure
        pass


def _note_protection_cycle(adapter) -> None:
    """(#1066) NORMAL / LIMIT_DISCHARGE went out while a forced op SEM started
    is still not seen to stop — decide_battery yielded to protection this
    cycle. Advance the count so the next cycle tries the stop again."""
    if (getattr(adapter, "_sem_forced_charge", None) is True
            or getattr(adapter, "_sem_forced_discharge", None) is True):
        _set(adapter, "_sem_stop_misses",
             int(getattr(adapter, "_sem_stop_misses", 0) or 0) + 1)


def _calm_capped_charge(decision, adapter):
    """(#1069 review) The forced charge under the limit, without churn.

    Lower at once; raise only after the bigger room held for
    ``FORCED_CHARGE_RAISE_DWELL_CYCLES``; after a no-room stop, restart only
    with ``FORCED_CHARGE_RESTART_STEPS`` steps of room. ``None`` = hold the
    stop, write nothing. A charge not shaped by the room passes unchanged."""
    from .decide_battery import FORCED_CHARGE_STEP_W
    if not decision.room_capped:
        _set(adapter, "_capped_charge_w", None)
        _set(adapter, "_capped_raise_streak", 0)
        _set(adapter, "_room_stopped", False)
        return decision
    want_w = float(decision.charge_power_w)
    if getattr(adapter, "_room_stopped", False):
        if want_w < FORCED_CHARGE_RESTART_STEPS * FORCED_CHARGE_STEP_W:
            return None
        _set(adapter, "_room_stopped", False)
        _set(adapter, "_capped_charge_w", None)
    last_w = getattr(adapter, "_capped_charge_w", None)
    streak = 0
    _charging = getattr(adapter, "last_intent", None) is BatteryIntent.FORCE_CHARGE
    if last_w is not None and want_w > last_w and _charging:
        streak = int(getattr(adapter, "_capped_raise_streak", 0) or 0) + 1
        if streak < FORCED_CHARGE_RAISE_DWELL_CYCLES:
            want_w = last_w
        else:
            streak = 0
    _set(adapter, "_capped_raise_streak", streak)
    _set(adapter, "_capped_charge_w", want_w)
    if want_w != float(decision.charge_power_w):
        # (#1174) the raise waits for the room to hold: the battery charges
        # more slowly than asked, and the row says so
        decision = rewrite(decision, charge_power_w=want_w,
                           reason_code=RC.BATTERY_CHARGE_SLOWED)
    return decision


async def actuate_battery(
    decision: "BatteryDecision",
    adapter: "BatteryControlAdapter",
    *,
    observer: bool = False,
    controller=None,
    inputs_degraded: bool = False,
    yielded: bool = False,
) -> None:
    """Apply a per-battery decision through the adapter (see
    :func:`_dispatch_battery`), then, on a cycle that sends no forced
    charge, settle a charge target SEM still has to put back (#1180). After
    the command, so a stop turns the switch off before the value goes back.
    Never in observer mode."""
    await _dispatch_battery(decision, adapter, observer=observer,
                            controller=controller,
                            inputs_degraded=inputs_degraded,
                            yielded=yielded)
    if (not observer and not yielded
            and decision.intent is not BatteryIntent.FORCE_CHARGE):
        await _settle_charge_target(adapter)


async def _dispatch_battery(
    decision: "BatteryDecision",
    adapter: "BatteryControlAdapter",
    *,
    observer: bool = False,
    controller=None,
    inputs_degraded: bool = False,
    yielded: bool = False,
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
    # (#1084) The decision log's battery seam. Each branch below notes the
    # command at the point it really leaves (after the holds that send
    # nothing), with the watts it sends. Recording only.
    _log = log_of(controller)
    # (#1164) What this battery was asked to charge at, as SENT: the FORCE_CHARGE
    # branch below sets it once its command goes out. Every other path — a
    # stop, a held stop after no room, observer, another intent — asks for
    # none, so a pack SEM did not ask to charge is never read as full.
    _set(adapter, "_sem_charge_asked_w", 0.0)
    # (#1165) …and the same for a sale, set by the FORCE_DISCHARGE branch.
    _set(adapter, "_sem_discharge_asked_w", 0.0)
    if yielded:
        # (#1079) Another party steers this battery and the user said SEM
        # yields: no adapter method runs, so nothing is written. Observer
        # mode, when on, still wins above — it withholds the same way.
        if not observer:
            log_on_change(
                _LOGGER, f"yield:battery:{decision.battery_id}", logging.INFO,
                "YIELD · %s is steered by another party, SEM withholds %s",
                decision.battery_id, decision.intent.value,
            )
            return
    if observer:
        _set(adapter, "_limit_rise", None)   # (#1173) a wait is for real cycles
        _would_w = {
            BatteryIntent.FORCE_CHARGE: decision.charge_power_w,
            BatteryIntent.FORCE_DISCHARGE: decision.discharge_power_w,
            BatteryIntent.LIMIT_DISCHARGE: quantise_discharge_limit_w(
                decision.discharge_limit_w, -1.0),
        }.get(decision.intent)
        record_battery(_log, decision, value_w=_would_w, observer=True)
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
    if held_on_blind_cycle(decision, adapter, inputs_degraded):
        log_on_change(
            _LOGGER, f"degraded:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): inputs degraded — holding %s, not "
            "flipping to %s on a blind cycle",
            decision.battery_id, adapter.last_intent, decision.intent,
        )
        return

    if decision.intent is BatteryIntent.OFF:
        record_battery(_log, decision)
        await adapter.command_off()
        log_on_change(   # (#762) transition-gated
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): OFF (hands-off) — %s",
            decision.battery_id, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.NORMAL:
        record_battery(_log, decision)
        await adapter.command_normal()
        _note_protection_cycle(adapter)
        log_on_change(   # (#762) 1424 identical lines/day on .175
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): NORMAL — %s",
            decision.battery_id, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.LIMIT_DISCHARGE:
        # (#900) quantised against what the adapter last commanded, so the
        # register follows the load's trend and not the fridge.
        # (#1173) A 0 W limit is a limit: ``or -1.0`` read it as none, so
        # the next one went out at once whatever it was (class 105).
        _last = getattr(adapter, "last_discharge_limit_w", None)
        last_w = -1.0 if _last is None else float(_last)
        limit_w = quantise_discharge_limit_w(decision.discharge_limit_w, last_w)
        # Lowering waits for the drop to persist; raising never waits.
        # (#1066) …and the wait is for a limit already in force. Coming from
        # NORMAL the anchor is the pack's MAX, so the first cap read as a
        # "lowering" and the pack fed a newly plugged-in car for six cycles.
        streak = int(getattr(adapter, "_limit_lower_streak", 0) or 0)
        _in_force = getattr(adapter, "last_intent", None) is BatteryIntent.LIMIT_DISCHARGE
        # (#1173) …except a limit that follows the house: it rises only to
        # a level the house has held — when the limit in force is one too.
        # Out of a target (the 0 W hold, a cover) the clamp lands at once.
        _following = getattr(adapter, "_limit_follows", None) is True
        if (decision.follows_load is True and _following and _in_force
                and last_w >= 0 and limit_w > last_w):
            limit_w = _settled_rise_w(decision.discharge_limit_w, last_w, adapter)
            streak = 0
        elif last_w >= 0 and limit_w < last_w and _in_force:
            _set(adapter, "_limit_rise", None)
            streak += 1
            if streak < DISCHARGE_LIMIT_LOWER_DWELL_CYCLES:
                limit_w = last_w
        else:
            _set(adapter, "_limit_rise", None)
            streak = 0
        try:
            adapter._limit_lower_streak = streak
        except Exception:  # noqa: BLE001 — a read-only stub is not a failure
            pass
        record_battery(_log, decision, value_w=limit_w)
        await adapter.command_limit_discharge(limit_w)
        # (#1173) what the limit in force is; a write that did not land
        # leaves the old one, which this cannot vouch for
        _set(adapter, "_limit_follows", decision.follows_load is True and getattr(
            adapter, "last_discharge_limit_w", None) == limit_w)
        _note_protection_cycle(adapter)
        log_on_change(   # (#762) the watts wobble; the gate strips digits
            _LOGGER, f"actuate:{decision.battery_id}", logging.DEBUG,
            "actuate_battery(%s): LIMIT_DISCHARGE %.0f W (raw %.0f W) — %s",
            decision.battery_id, limit_w, decision.discharge_limit_w, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.FORCE_CHARGE:
        decision = _calm_capped_charge(decision, adapter)
        if decision is None:
            await _settle_charge_target(adapter)   # (#1180) nothing goes out
            return
        if not adapter.supports_forced_charge:
            log_on_change(   # (#762) once per episode, not per cycle
                _LOGGER, f"actuate:{decision.battery_id}", logging.WARNING,
                "actuate_battery(%s): adapter does not support forced "
                "charge — decision dropped (%s)",
                decision.battery_id, decision.reason,
            )
            return
        record_battery(_log, decision, value_w=decision.charge_power_w)
        ret = await adapter.command_force_charge(
            decision.target_soc,
            decision.charge_power_w,
            decision.duration_min,
        )
        _note_forced_op(adapter, "_sem_forced_charge", ret,
                        BatteryIntent.FORCE_CHARGE, True)
        # (#1164 review) Asked only if it went out: a withheld setpoint
        # (#978) or a failed start leaves ``last_error`` set.
        if (getattr(adapter, "last_error", None) is None
                and getattr(adapter, "last_intent", None)
                is BatteryIntent.FORCE_CHARGE):
            _set(adapter, "_sem_charge_asked_w", float(decision.charge_power_w))
        _LOGGER.debug(
            "actuate_battery(%s): FORCE_CHARGE target_soc=%.0f%% "
            "power=%.0f W duration=%dm — %s",
            decision.battery_id, decision.target_soc,
            decision.charge_power_w, decision.duration_min,
            decision.reason,
        )
        return

    if decision.intent is BatteryIntent.STOP_FORCE_CHARGE:
        if decision.room_capped:
            # (#1069 review) stopped for no room: once is enough. The
            # scheduler keeps asking every cycle; the stop is not re-sent.
            if (getattr(adapter, "_room_stopped", False)
                    and getattr(adapter, "last_intent", None)
                    is BatteryIntent.STOP_FORCE_CHARGE):
                return
            _set(adapter, "_room_stopped", True)
        _set(adapter, "_capped_charge_w", None)
        _set(adapter, "_capped_raise_streak", 0)
        record_battery(_log, decision)
        ret = await adapter.command_stop_force_charge()
        _note_forced_op(adapter, "_sem_forced_charge", ret,
                        BatteryIntent.STOP_FORCE_CHARGE, False)
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
        record_battery(_log, decision, value_w=decision.discharge_power_w)
        ret = await adapter.command_force_discharge(
            decision.discharge_power_w, decision.floor_soc,
        )
        _note_forced_op(adapter, "_sem_forced_discharge", ret,
                        BatteryIntent.FORCE_DISCHARGE, True)
        # (#1165) Asked only if it went out. Deye answers True and records
        # no intent; the other brands record the intent and clear
        # ``last_error``, and a withheld setpoint (#978) sets it.
        if ret is True or (
                getattr(adapter, "last_error", None) is None
                and getattr(adapter, "last_intent", None)
                is BatteryIntent.FORCE_DISCHARGE):
            _set(adapter, "_sem_discharge_asked_w",
                 float(decision.discharge_power_w))
        _LOGGER.info(
            "actuate_battery(%s): FORCE_DISCHARGE %.0f W (floor %.0f%%) — %s",
            decision.battery_id, decision.discharge_power_w,
            decision.floor_soc, decision.reason,
        )
        return

    if decision.intent is BatteryIntent.STOP_FORCE_DISCHARGE:
        record_battery(_log, decision)
        ret = await adapter.command_stop_force_discharge()
        _note_forced_op(adapter, "_sem_forced_discharge", ret,
                        BatteryIntent.STOP_FORCE_DISCHARGE, False)
        _LOGGER.debug(
            "actuate_battery(%s): STOP_FORCE_DISCHARGE — %s",
            decision.battery_id, decision.reason,
        )
        return

    _LOGGER.error(
        "actuate_battery(%s): unknown intent %r",
        decision.battery_id, decision.intent,
    )


async def restore_discharge_limit_on_startup(
    hass, config: dict, yielded: bool = False,
) -> None:
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
    # (#1079 review) A restart is exactly the moment this must not clobber
    # another party's own limit — the one case the yield feature exists for.
    if yielded:
        _LOGGER.info(
            "Startup: battery yielded to another party — discharge restore "
            "skipped (#1079)"
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
        # (#1066) -1 is "no limit written" — an adapter with no limit entity
        # is asked to limit and cannot; it holds no cap to show.
        and a._last_discharge_limit_w >= 0
    ]
    return min(limits) if limits else None
