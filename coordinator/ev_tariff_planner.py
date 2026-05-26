"""Night EV charge planning: target-time deadline + tariff-optimized timing.

Pure, side-effect-free helpers shared by the coordinator. Kept out of
``coordinator.py`` so the deadline-scaling (#246) and tariff-cheap-window
(#247) logic can be unit-tested in isolation with plain primitives — no
HomeAssistant, no tariff provider, no coordinator instance required.

Two concerns, one decision per cycle (``plan_night_charge``):

* **Deadline (#246, Phase 2)** — "reach Min by HH:MM". From the remaining
  energy to the Min floor and the hours left to the deadline, compute the
  average current needed and clamp it to the charger's [min, max]. This is a
  *floor* the night controller applies on top of its peak-managed current; it
  also detects physically-impossible deadlines so the caller can warn.

* **Tariff (#247, Phase 3)** — when tariff-optimized is on, defer charging to
  the cheapest price window *as long as the Min floor can still be met by the
  deadline using only those cheap hours*. The Min floor is always guaranteed:
  if waiting for cheap hours would miss the deadline (or there is no price
  data), the planner charges now regardless of price.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class NightChargePlan:
    """Per-charger night-charging decision for one control cycle.

    Attributes:
        should_wait_for_cheap: Tariff mode wants to idle now and charge during a
            cheaper upcoming window (Min can still be met by the deadline).
        deadline_amps: Current floor (A) needed to reach Min by the deadline,
            clamped to [min_amps, max_amps]. 0 when nothing is owed.
        deadline_active: True when a finite deadline is driving ``deadline_amps``
            above the charger minimum (i.e. the gentle ramp should be overridden).
        reachable: False when Min cannot be reached by the deadline even at max
            current — caller should warn the user.
        next_cheap_start: Start of the next cheap window (for the card / status).
        deadline_dt: Resolved deadline as an absolute datetime.
        hours_to_deadline: Hours from ``now`` to the deadline (>= 0).
        reason: Short human-readable explanation (logging / status).
    """

    should_wait_for_cheap: bool = False
    deadline_amps: int = 0
    deadline_active: bool = False
    reachable: bool = True
    next_cheap_start: Optional[datetime] = None
    deadline_dt: Optional[datetime] = None
    hours_to_deadline: Optional[float] = None
    remaining_kwh: float = 0.0
    reason: str = ""


def resolve_deadline(now: datetime, target_time: Optional[str]) -> Optional[datetime]:
    """Resolve an ``HH:MM`` deadline to the next absolute datetime at/after now.

    Night charging spans midnight, so a 07:00 deadline set at 22:00 means 07:00
    *tomorrow*. If the time has already passed today, roll to tomorrow. Returns
    ``None`` for blank / malformed input (caller falls back to the night-end).
    """
    if not target_time:
        return None
    try:
        parts = str(target_time).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, AttributeError, IndexError):
        return None
    candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _is_within_slot(now: datetime, slot_starts: List[datetime], slot_hours: float = 1.0) -> bool:
    """True when ``now`` falls inside one of the (hour-long) cheap slots."""
    span = timedelta(hours=slot_hours)
    return any(s <= now < s + span for s in slot_starts)


def plan_night_charge(
    *,
    now: datetime,
    remaining_to_min_kwh: float,
    min_amps: int,
    max_amps: int,
    watts_per_amp: float,
    target_time: Optional[str] = None,
    night_end: Optional[str] = None,
    tariff_optimized: bool = False,
    cheap_slots: Optional[List[datetime]] = None,
    slot_hours: float = 1.0,
) -> NightChargePlan:
    """Decide this cycle's night-charging action for one charger.

    Args:
        now: Current local time.
        remaining_to_min_kwh: Energy still owed to reach the Min floor.
        min_amps / max_amps: Charger current limits.
        watts_per_amp: Effective W per A (phases x voltage, or measured).
        target_time: ``HH:MM`` user deadline ("reach Min by"), or None.
        night_end: ``HH:MM`` night-window end, used as the deadline when no
            explicit ``target_time`` is set.
        tariff_optimized: Whether tariff-optimized timing is enabled.
        cheap_slots: Sorted hour-start datetimes selected as the cheapest block
            (from the tariff provider). Empty/None disables tariff gating.
        slot_hours: Length of each price slot (1.0 = hourly, 0.5 = half-hourly).

    Returns:
        A populated :class:`NightChargePlan`.
    """
    plan = NightChargePlan()
    plan.remaining_kwh = max(0.0, remaining_to_min_kwh)
    watts_per_amp = max(1.0, watts_per_amp)

    explicit_deadline = resolve_deadline(now, target_time)
    night_end_dt = resolve_deadline(now, night_end)
    deadline = explicit_deadline or night_end_dt
    plan.deadline_dt = deadline

    # A deadline only *forces* current (overriding the gentle ramp / peak limit)
    # and warns when the user set one TIGHTER than the night-window end. A
    # deadline at/after the window end adds no constraint over normal
    # peak-managed night charging — so the default (charge-by == window end)
    # leaves existing behaviour completely unchanged (#246 review: no surprise
    # peak overshoot for users who never set a deadline).
    is_forcing = bool(
        explicit_deadline is not None
        and night_end_dt is not None
        and explicit_deadline < night_end_dt - timedelta(minutes=5)
    )

    # Nothing owed → no deadline pressure, no tariff wait.
    if remaining_to_min_kwh <= 0.1:
        plan.reason = "min floor already met"
        return plan

    hours_left = None
    if deadline is not None:
        hours_left = max(0.0, (deadline - now).total_seconds() / 3600.0)
        plan.hours_to_deadline = round(hours_left, 2)

    max_rate_kw = max_amps * watts_per_amp / 1000.0

    # --- Deadline scaling (#246) ---------------------------------------------
    if hours_left is not None and hours_left > 0:
        required_w = remaining_to_min_kwh * 1000.0 / hours_left
        required_amps = math.ceil(required_w / watts_per_amp)
        plan.deadline_amps = max(min_amps, min(max_amps, required_amps))
        plan.deadline_active = is_forcing and required_amps > min_amps
        # Reachable only if even max current finishes in the time left — but
        # only flag (and warn) for an explicit, forcing deadline.
        if is_forcing and max_rate_kw > 0:
            plan.reachable = (remaining_to_min_kwh / max_rate_kw) <= hours_left + 1e-6
        else:
            plan.reachable = True
        if not plan.reachable:
            plan.reason = (
                f"deadline unreachable: need {remaining_to_min_kwh:.1f}kWh in "
                f"{hours_left:.1f}h, max {max_rate_kw:.1f}kW"
            )
    elif is_forcing and hours_left is not None and hours_left <= 0:
        # Explicit deadline has arrived/passed and Min not met — charge hard now.
        plan.deadline_amps = max_amps
        plan.deadline_active = True
        plan.reachable = False
        plan.reason = "deadline reached, min not met — charging at max"
    else:
        plan.deadline_amps = 0  # no forcing deadline configured

    # --- Tariff gating (#247) ------------------------------------------------
    cheap_slots = sorted(cheap_slots) if cheap_slots else []
    if cheap_slots:
        plan.next_cheap_start = next((s for s in cheap_slots if s + timedelta(hours=slot_hours) > now), cheap_slots[0])

    if tariff_optimized and cheap_slots:
        now_is_cheap = _is_within_slot(now, cheap_slots, slot_hours)
        if now_is_cheap:
            plan.reason = "tariff: in cheap window — charging"
        elif not plan.reachable:
            # Can't make the deadline anyway — don't also wait for cheap.
            plan.reason = "tariff: deadline at risk — charging despite price"
        else:
            # Can we still hit Min using only the cheap slots before the deadline?
            limit = deadline if deadline is not None else (now + timedelta(hours=24))
            cheap_before_deadline = [s for s in cheap_slots if s < limit and s >= now]
            deliverable_kwh = len(cheap_before_deadline) * slot_hours * max_rate_kw
            if deliverable_kwh + 1e-6 >= remaining_to_min_kwh:
                plan.should_wait_for_cheap = True
                nxt = plan.next_cheap_start
                when = nxt.strftime("%H:%M") if nxt else "?"
                plan.reason = f"tariff: waiting for cheap window (next {when})"
            else:
                plan.reason = (
                    "tariff: not enough cheap hours before deadline — "
                    "charging to guarantee min"
                )

    if not plan.reason:
        plan.reason = "night charging"
    return plan
