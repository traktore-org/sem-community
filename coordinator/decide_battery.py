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
3. LIMIT_DISCHARGE — EV charging with solar surplus below the
   ``battery_assist_min_surplus`` gate (any mode/time); clamp battery
   to home consumption (1:1 protection) so grid+solar fund the car.
4. NORMAL — default.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .charger_types import BatteryDecision, BatteryIntent
from ..consts.battery_modes import arbitrage_allowed_for_mode

if TYPE_CHECKING:  # pragma: no cover
    from .charger_types import BatteryView

_LOGGER = logging.getLogger(__name__)


def decide_battery(view: "BatteryView") -> BatteryDecision:
    """Compute this battery's per-cycle decision.

    Pure function — same input → same output.
    """
    rt = view.runtime
    cfg = view.config

    # ─── Per-battery MODE override (#523) ───
    # Highest precedence: a user-chosen manual mode wins over the
    # scheduler / protection logic for THIS battery. ``auto`` (the
    # default, and the value for every single-battery install that never
    # sets a mode) falls straight through to today's behaviour.
    mode = str(cfg.get("battery_mode", "auto") or "auto").lower()
    reserve = cfg.get("battery_reserve_soc")
    reserve = float(reserve) if reserve is not None else 0.0

    if mode == "off":
        # #523 (RienduPre): SEM is fully hands-off this battery. Highest
        # precedence — short-circuit BEFORE the scheduler / arbitrage /
        # protection branches so none of them can issue a command. The
        # adapter's command_off() does a one-time clean handoff on entry
        # then stays silent; the inverter runs the battery on its own.
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.OFF,
            reason="mode=off (SEM hands-off — inverter self-manages)",
        )

    if mode == "force_discharge":
        # Respect the reserve floor even for a manual sell — never drain the
        # battery below its backup reserve. At/under the floor we fall through
        # to NORMAL so command_normal() zeroes the forcible-discharge setpoint.
        #
        # #531: when the SOC is UNAVAILABLE, do NOT sell. A setpoint battery
        # (Sessy) has no hardware reserve-stop — only the live SOC gates it —
        # so discharging "blind" could drain it past the backup reserve. When
        # in doubt, hold (the live SOC self-heals next cycle).
        soc = rt.last_known_soc
        if soc is not None and soc > reserve:
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.FORCE_DISCHARGE,
                discharge_power_w=float(cfg.get("battery_max_discharge_power", 5000.0) or 0.0),
                floor_soc=reserve,
                reason="mode=force_discharge (manual sell to grid)",
            )
        _soc_txt = f"{soc:.0f}%" if soc is not None else "unavailable"
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.NORMAL,
            reason=f"mode=force_discharge but SOC {_soc_txt} ≤ reserve {reserve:.0f}% — hold",
        )
    if mode == "force_charge":
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.FORCE_CHARGE,
            target_soc=100.0,
            # #523: fall through the two charge-power keys before the 5000 W
            # default. ``battery_max_charge_power_w`` is often present-as-None
            # (so a ``.get(key, 5000)`` returns None, not the default) — with the
            # bidirectional-setpoint charge path that yielded a 0 W setpoint and
            # the battery never charged. ``or`` chains past None/0 to a real value.
            charge_power_w=float(
                cfg.get("battery_max_charge_power_w")
                or cfg.get("battery_max_charge_power")
                or 5000.0
            ),
            duration_min=240,
            reason="mode=force_charge (manual charge to full)",
        )

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
        # mirror of the SCHEDULED → FORCE_CHARGE path above. Gated PER
        # BATTERY by its mode (self_consumption never sells; allow_arbitrage
        # always may; auto follows the global toggle) and its OWN reserve
        # SOC — so a self-consumption battery keeps its charge while its
        # sibling sells, on the same shared verdict.
        if state_value == "discharging_arbitrage":
            global_arb = bool(cfg.get("battery_grid_arbitrage_enabled", False))
            if arbitrage_allowed_for_mode(mode, global_arb):
                floor = reserve if reserve > 0 else getattr(sched, "floor_soc", 0.0)
                soc = rt.last_known_soc
                # #531: don't sell blind — a setpoint battery has no hardware
                # reserve-stop, so an unavailable SOC must hold, not discharge.
                if soc is not None and soc > floor:
                    return BatteryDecision(
                        battery_id=rt.battery_id,
                        intent=BatteryIntent.FORCE_DISCHARGE,
                        discharge_power_w=getattr(sched, "discharge_power_w", 0.0),
                        floor_soc=floor,
                        reason=getattr(sched, "reason", "export arbitrage"),
                    )
            # Not allowed for this battery (self_consumption / auto-with-
            # global-off) or already at/under its reserve → fall through to
            # the normal decision (don't sell this unit).

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

    # ─── LIMIT_DISCHARGE branch (unified solar gate) ───
    # The home battery must NEVER be drained to charge the EV when there
    # isn't enough real solar surplus — in ANY charging mode
    # (min_plus_solar, solar_only, solar_plus_cheap, always_max) and at
    # any time of day/night. One knob governs it: when the EV is drawing
    # and the pure solar surplus (solar − home) is below
    # ``battery_assist_min_surplus_w`` (default 1200 W), clamp battery
    # discharge to the home load so grid+solar fund the car, never the
    # battery.
    #
    # Setting the gate to 0 W lets the battery support the EV everywhere
    # — including overnight — because surplus ≥ 0 always clears a 0
    # threshold (the user opt-in path).
    #
    # This UNIFIES (supersedes) the old night-only / hold_solar triggers:
    # at the default the overnight case is unchanged (no solar → surplus
    # 0 < 1200 → clamp). ``battery_hold_solar_ev`` is now subsumed by the
    # gate (cloudy solar below the gate clamps regardless) and is no
    # longer read here — kept as an ignored config key for now.
    #
    # GATE ON ev_connected (plugged in), NOT ev_charging (drawing now):
    # a bursty car (e.g. Renault Zoe) toggles ev_charging on/off every
    # few seconds. Keying the clamp on ev_charging means it drops in the
    # gaps → the battery discharges freely → that energy feeds the next
    # pull → the battery drains overnight (PROD 2026-06-24, 93→41 %).
    # While a car is plugged in and surplus is below the gate, the
    # protection must HOLD regardless of the instantaneous draw. Fall
    # back to ev_charging so older views (no ev_connected) still gate.
    protection_enabled = bool(cfg.get("battery_discharge_protection_enabled", True))

    if protection_enabled and (view.ev_connected or view.ev_charging):
        f = view.fleet
        # Pure solar-vs-house surplus. Intentionally does NOT subtract
        # battery_charge_w (unlike decide.self_consumption_surplus_w): the
        # battery view's FleetContext doesn't populate it, and a battery
        # that is charging cannot simultaneously discharge — so the simpler
        # formula is safe here (slightly more permissive at worst).
        surplus_w = max(0.0, float(f.solar_w) - float(f.home_w))
        gate_w = float(getattr(f, "battery_assist_min_surplus_w", 1200.0))
        if surplus_w < gate_w:
            # #531: split the home budget across the fleet — N batteries each
            # told to inject the FULL home load over-injects N× and leaks the
            # surplus to the EV, defeating the protection. Each gets home/N.
            n = max(1, int(getattr(f, "battery_count", 1) or 1))
            home_w = max(0.0, view.home_consumption_w) / n
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=home_w,
                reason=(
                    f"ev plugged in + solar surplus {surplus_w:.0f}W < gate "
                    f"{gate_w:.0f}W → discharge limit "
                    f"{home_w:.0f} W (home/{n} across fleet)"
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
