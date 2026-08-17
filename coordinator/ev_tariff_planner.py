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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


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
    # (#630) Peak-managed top-up rate: the plain night top-up runs at the
    # available peak headroom instead of creeping at Min — finish early,
    # free the window for lower-priority cheap-hours loads. 0 = no info
    # (caller falls back to the Min floor, pre-#630 behaviour).
    top_up_amps: int = 0
    deadline_active: bool = False
    reachable: bool = True
    should_warn_unreachable: bool = False
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

    DST (#274/M2): ``now`` is a zoneinfo-aware ``dt_util.now()``. ``.replace(hour=)``
    keeps the zoneinfo tzinfo (not a frozen offset), so the resolved deadline gets
    the offset for *its* wall-clock time, and the caller's ``(deadline - now)``
    subtraction converts both via their own UTC offsets — yielding the true elapsed
    hours across a DST fold/gap (e.g. 7 actual hours for 01:00→07:00 on a fall-back
    night, not the 6 a naive wall-clock subtraction would give). Locked by
    test_resolve_deadline_dst_fallback_is_actual_elapsed.
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


def _hours_between(start: datetime, end: datetime) -> float:
    """Elapsed hours from ``start`` to ``end``, DST-correct (#274/M2).

    Python subtracts two aware datetimes that share the *same* tzinfo (e.g. both
    ``dt_util.now()``-zone) in wall-clock space, ignoring the UTC offset — so a
    fall-back night under-counts by the repeated hour (07:00−01:00 reads 6 h, not
    the true 7 h). Convert to UTC first when both are aware. Naive datetimes
    (unit tests) are subtracted directly.
    """
    if start.tzinfo is not None and end.tzinfo is not None:
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
    return (end - start).total_seconds() / 3600.0


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
    peak_managed_amps: Optional[int] = None,
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
        tariff_optimized: Whether the user opted into tariff-timed
            charging. Post-retirement (#638 one-gate C3) it gates ONLY the
            unreachable warning: the WHEN comes from the joint plan's
            blocks via the overlay, never from this pure function.
        peak_managed_amps: Realistic current (A) the charger can sustain under
            the peak limit given expected (average) home consumption, clamped to
            [min, max]. This is the rate non-forcing night charging actually runs
            at — the wait/reachability math uses it instead of ``max_amps`` so the
            planner doesn't wait for a cheap window it can't fill at the peak-
            limited rate and then miss Min (#274/C1). ``None`` ⇒ assume max
            (pre-#274 behaviour, no peak awareness).

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
        hours_left = max(0.0, _hours_between(now, deadline))
        plan.hours_to_deadline = round(hours_left, 2)

    # Effective charge rate (#274/C1). A forcing deadline overrides the peak
    # limit and charges at the charger max; otherwise night charging is
    # peak-managed, so the realistic sustained rate is bounded by the peak
    # headroom (peak_managed_amps, derived from average home consumption).
    # Sizing the wait/reachability math at max_amps while charging is actually
    # peak-capped is what let the planner wait for a cheap window and then miss
    # Min. peak_managed_amps is None ⇒ no peak info ⇒ assume max (pre-#274).
    max_rate_kw = max_amps * watts_per_amp / 1000.0
    pm_amps = max_amps if peak_managed_amps is None else max(min_amps, min(max_amps, int(peak_managed_amps)))
    peak_rate_kw = pm_amps * watts_per_amp / 1000.0
    # (#630) the plain top-up charges at the peak-managed headroom rate when
    # known; without peak info keep the legacy Min-floor creep (0 = unset).
    plan.top_up_amps = pm_amps if peak_managed_amps is not None else 0
    effective_rate_kw = max_rate_kw if is_forcing else peak_rate_kw

    # --- Deadline scaling (#246) ---------------------------------------------
    if hours_left is not None and hours_left > 0:
        required_w = remaining_to_min_kwh * 1000.0 / hours_left
        required_amps = math.ceil(required_w / watts_per_amp)
        plan.deadline_amps = max(min_amps, min(max_amps, required_amps))
        plan.deadline_active = is_forcing and required_amps > min_amps
        # Reachable at the rate we'll ACTUALLY charge: max when forcing (peak
        # overridden), peak-managed otherwise. Computed on both paths now so a
        # peak-limited window that can't deliver Min surfaces a warning instead
        # of silently under-charging (#274/C1).
        plan.reachable = (
            (remaining_to_min_kwh / effective_rate_kw) <= hours_left + 1e-6
            if effective_rate_kw > 0 else False
        )
    elif is_forcing and hours_left is not None and hours_left <= 0:
        # Explicit deadline has arrived/passed and Min not met — charge hard now.
        plan.deadline_amps = max_amps
        plan.deadline_active = True
        plan.reachable = False
        plan.reason = "deadline reached, min not met — charging at max"
    else:
        plan.deadline_amps = 0  # no forcing deadline configured

    if not plan.reachable and not plan.reason:
        plan.reason = (
            f"deadline unreachable: need {remaining_to_min_kwh:.1f}kWh in "
            f"{hours_left:.1f}h at {effective_rate_kw:.1f}kW"
            + ("" if is_forcing else " (peak-limited — raise peak limit or set an earlier deadline)")
        )

    # (#638 one-gate C3) The tariff-gating block is RETIRED. The pure
    # planner keeps only guarantee math; ``should_wait_for_cheap`` /
    # ``next_cheap_start`` keep their defaults (False / None) and are
    # written EXCLUSIVELY by the plan-gate overlay in the coordinator.

    # Only warn the user when they opted into deadline/tariff behaviour (#274/C1):
    # a plain default-deadline night charge that simply can't finish within the
    # window at the peak limit shouldn't nag users who never set a deadline.
    plan.should_warn_unreachable = (not plan.reachable) and (is_forcing or tariff_optimized)

    if not plan.reason:
        plan.reason = "night charging"
    return plan
