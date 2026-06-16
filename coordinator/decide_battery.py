"""Pure ``decide_battery(view) → BatteryDecision`` (Group B Step 3).

One pure function per cycle per battery. Replaces the branching
in :class:`BatteryProtectionMixin` + :meth:`BatteryChargeScheduler.update`
that pre-v1.7.0 spread across two modules.

Pure: no ``self``, no HA calls. Input :class:`BatteryView`, output
:class:`BatteryDecision`.

Decision tree (precedence top-down):

1. FORCE_CHARGE — scheduler decided SCHEDULED and we're in the
   charge window.
2. STOP_FORCE_CHARGE — scheduler decided TARGET_REACHED / NOT_NEEDED /
   IDLE but the adapter is still in FORCE_CHARGE intent.
3. LIMIT_DISCHARGE — night-charging an EV; clamp battery to home
   consumption (1:1 protection).
4. NORMAL — default.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .charger_types import BatteryDecision, BatteryIntent

if TYPE_CHECKING:  # pragma: no cover
    from .charger_types import BatteryView

_LOGGER = logging.getLogger(__name__)


# Charging-state strings that trip LIMIT_DISCHARGE (matches today's
# BatteryProtectionMixin gate). Compared as strings so the constant
# doesn't need to import ChargingState.
_NIGHT_CHARGING_ACTIVE = "night_charging_active"
_SOLAR_CHARGING_ACTIVE = "solar_charging_active"


def decide_battery(view: "BatteryView") -> BatteryDecision:
    """Compute this battery's per-cycle decision.

    Pure function — same input → same output.
    """
    rt = view.runtime
    cfg = view.config

    # ─── FORCE_CHARGE / STOP_FORCE_CHARGE branch ───
    # The pre-computed scheduler_decision tells us whether to be in
    # a forced-charge window. Pure read of its state field — the
    # scheduler's evaluate() did the work in BatteryChargeScheduler.
    sched = view.scheduler_decision
    if sched is not None:
        state = getattr(sched, "state", None)
        state_value = getattr(state, "value", state) if state is not None else None

        if state_value == "scheduled":
            in_window = _now_in_window(view)
            if in_window:
                return BatteryDecision(
                    battery_id=rt.battery_id,
                    intent=BatteryIntent.FORCE_CHARGE,
                    target_soc=getattr(sched, "target_soc", 0.0),
                    charge_power_w=getattr(sched, "charge_power_w", 0.0),
                    duration_min=getattr(sched, "duration_min", 60),
                    reason=f"scheduler SCHEDULED → force charge in window",
                )

        # Export arbitrage — the scheduler decided to SELL to the grid
        # this cycle (#523). Pure actuation of the scheduler's verdict, the
        # mirror of the SCHEDULED → FORCE_CHARGE path above.
        if state_value == "discharging_arbitrage":
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.FORCE_DISCHARGE,
                discharge_power_w=getattr(sched, "discharge_power_w", 0.0),
                floor_soc=getattr(sched, "floor_soc", 0.0),
                reason=getattr(sched, "reason", "export arbitrage"),
            )

        # Target reached or no longer needed — stop a running charge.
        if state_value in ("target_reached", "not_needed", "idle", "not_profitable"):
            # Only emit STOP if we actually started; otherwise NORMAL is fine.
            # The decision doesn't know the adapter's last intent — it returns
            # the intent that fits the world state; the actuator may no-op if
            # already in that state (adapter idempotency).
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.STOP_FORCE_CHARGE,
                reason=f"scheduler {state_value} → ensure not force-charging",
            )

    # ─── LIMIT_DISCHARGE branch ───
    # The reactive protection that today's BatteryProtectionMixin
    # applies. Active iff:
    #   * SEM's global ChargingState is night-charging-active
    #   * an EV is actually drawing current
    # OR (opt-in) solar-mode hold during EV charging:
    #   * battery_hold_solar_ev=true
    #   * ChargingState is solar-charging-active + ev_charging
    hold_solar = bool(cfg.get("battery_hold_solar_ev", False))
    protection_enabled = bool(cfg.get("battery_discharge_protection_enabled", True))
    state = (view.charging_state or "").lower()

    if protection_enabled and view.ev_charging:
        is_night_active = state == _NIGHT_CHARGING_ACTIVE
        is_solar_active = state == _SOLAR_CHARGING_ACTIVE
        if is_night_active or (hold_solar and is_solar_active):
            home_w = max(0.0, view.home_consumption_w)
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=home_w,
                reason=(
                    f"{state} + ev_charging → discharge limit "
                    f"{home_w:.0f} W (home consumption 1:1)"
                ),
            )

    # ─── NORMAL ───
    return BatteryDecision(
        battery_id=rt.battery_id,
        intent=BatteryIntent.NORMAL,
        reason="no protection / no force-charge — default discharge",
    )


def _now_in_window(view: "BatteryView") -> bool:
    """Whether the current time falls inside a SCHEDULED window.

    Pure: reads ``view.scheduler_decision.schedule`` if populated.
    The schedule's TimeSlot list is the per-cycle truth — if the
    scheduler decided SCHEDULED but the time isn't yet inside a
    slot, we DON'T force-charge yet (this happens in the gap
    between evaluation at 21:00 and the first charge slot).
    """
    sched = view.scheduler_decision
    if sched is None:
        return False
    schedule = getattr(sched, "schedule", None)
    if schedule is None:
        # Decision is SCHEDULED but no time-slot data — treat as
        # "charge whenever scheduler says scheduled" (back-compat
        # with pre-time-slot scheduler version).
        return True
    slots = getattr(schedule, "slots", None) or []
    if not slots:
        return True
    # Pure check: any slot's start <= now <= start + duration?
    # ``now`` should come from view.fleet, but for simplicity defer
    # to the schedule's own helper if it has one.
    helper = getattr(schedule, "is_active_now", None)
    if callable(helper):
        try:
            return bool(helper())
        except Exception:
            return False
    return True
