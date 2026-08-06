"""The planning layer's verdict for one device, for one cycle (#638).

SEM has two layers that decide whether a device runs. The REACTIVE layer
answers "can it run right now" from live sensors — surplus, SOC, peak
headroom, deadlines. The PLANNING layer answers "when should it run"
across a horizon it can see ahead: tonight's price slots, tomorrow's
forecast. This type is what the second says to the first.

Day/night agnostic on purpose. Night is where planning is currently
mandatory — the price blocks are known hours ahead and the overnight
planner places each device's energy in them. A daytime planner (forecast
windows, surplus placement) says the same thing in the same shape: *not
now, later, and here is why*. It must populate THIS field rather than
grow a second channel, because a second channel is exactly how the night
verdict got lost: it travelled as ``config["_tariff_wait"]``, an untyped
key that one of three night modes happened to know about, and on
2026-08-06 the car finished its charge half an hour before its own
planned window opened.

Pure — dataclasses and stdlib only, no Home Assistant imports — so the
EV decision layer (``decide.py``) and the load intent layer
(``surplus_controller.compute_load_intent``) can both depend on it
without either depending on the other.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PlanVerdict:
    """What the planner has decided about this device, this cycle.

    The default instance means "no opinion", and every consumer must
    treat it as though no planner existed at all. That is the fail-open
    contract the actuation arc was built on: an install without the
    planner, a stale plan, a plan whose switch is off, and a planner that
    crashed all land on the same safe value.
    """

    hold: bool = False
    # True = the plan placed this device's energy in a later window and
    # has already PROVEN the later windows can still deliver what is owed
    # (see overnight_actuation.ev_overlay). It is never a bare preference:
    # a verdict that cannot guarantee the need is met must not hold.

    until: Optional[datetime] = None
    # When the hold is expected to lift, for the reason text. Advisory —
    # consumers must not treat it as a schedule of their own; the plan is
    # re-evaluated every cycle and the verdict replaced.

    reason: str = ""
    # Why, in the planner's own words, for the published state. Carried
    # so the card and the decision quote ONE source instead of composing
    # two stories that can disagree.


NO_OPINION = PlanVerdict()
"""The absence of a plan. Distinct from ``PlanVerdict(hold=False)`` only
in intent — a planner that ran and said "go" versus no planner at all —
and deliberately identical in effect, so no consumer can accidentally
make "unplanned" mean "forbidden"."""


def verdict_from_night_plan(plan: object) -> PlanVerdict:
    """Translate tonight's ``NightChargePlan`` into the verdict.

    The single point where the night planner's private shape becomes the
    layer-crossing one. SEM computes that plan at TWO sites — once for the
    primary charger in ``_build_charging_context``, once per charger in the
    multi-charger loop — and those two drifting apart is a named, recurring
    class (#683/#684). One function so a field added here (Stage 2's
    ``until``) arrives at both sites in the same commit.

    Duck-typed on purpose: importing ``NightChargePlan`` would drag Home
    Assistant into this module and cost the load-intent layer its ability
    to share the type.

    Args:
        plan: the plan computed for this charger THIS cycle, or ``None``
            when none was — outside the night window, or nothing owed.

    Returns:
        The verdict. Anything missing or malformed yields no opinion:
        the producing path is wrapped in a bare ``except`` precisely so a
        crash reads as "no plan", and a missing attribute must land the
        same way rather than as a silent refusal to charge.
    """
    if plan is None:
        return NO_OPINION
    return PlanVerdict(
        hold=bool(getattr(plan, "should_wait_for_cheap", False)),
        reason=str(getattr(plan, "reason", "") or ""),
    )
