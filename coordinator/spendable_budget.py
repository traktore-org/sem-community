"""#778 — how much of the battery is genuinely surplus tonight?

The reporter's case: a 30 kWh pack, 5–10 kWh of overnight house load in
summer, and a battery sitting full at sunset for no reason. He wants the
excess sold into the best export window — **but only when tomorrow's sun can
put it back**.

This answers the first question of the budget triangle only: HOW MUCH is
spendable. It decides nothing about *when* to sell or *who* receives it — the
export path (#533) and the evening EV assist are the sinks and already exist.
The number in the middle was what was missing.

Deliberately a pure function with no Home Assistant imports: it can be read,
tested and argued with on its own, and its output is published before it is
ever allowed to move a watt (SEM's land-it-asleep habit — arbitrage #533, the
curtailment probe #743, the night recorder #800 all shipped that way).

Rules, in priority order:

1. **The static floor is not negotiable.** A reserve SOC is a promise about
   blackouts and pack health; no forecast may spend through it.
2. **Keep the night.** Reserve the forecast overnight need, divided by
   discharge efficiency — you must *store* more than you *draw* — and inflated
   by the user's pessimism factor.
3. **Only spend what tomorrow puts back.** Selling energy the sun will not
   replace merely moves the purchase to a worse hour.
4. **An unknown input spends nothing.** #818's rule generalised: a dark input
   is not permission.
5. **Say why.** Every result carries its binding constraint, because a number
   the user cannot explain is one they will not trust (#830).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SpendableBudget:
    """What the battery may give up tonight, and why that much."""

    spendable_kwh: float
    """Energy that may be sold or diverted. 0.0 whenever anything is unknown."""

    floor_pct: Optional[float]
    """The dynamic minimum SOC this implies — the static floor, or the level
    the night's own need demands, whichever is higher. ``None`` when it cannot
    be computed."""

    reason: str
    """The binding constraint, in words a user can check against reality."""


def _num(value) -> Optional[float]:
    """A float, or None for anything that is not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def spendable_budget(
    soc_pct,
    usable_capacity_kwh,
    overnight_need_kwh,
    expected_refill_kwh,
    static_floor_pct=20.0,
    pessimism: float = 1.2,
    discharge_efficiency: float = 0.95,
) -> SpendableBudget:
    """How many kWh of this battery are genuinely surplus tonight.

    ``overnight_need_kwh`` is the forecast house draw until PV meaningfully
    resumes; ``expected_refill_kwh`` the surplus tomorrow is expected to
    return to the pack. ``pessimism`` (>= 1) inflates the reserve — the
    user's own margin against a forecast that disappoints.
    """
    soc = _num(soc_pct)
    cap = _num(usable_capacity_kwh)
    need = _num(overnight_need_kwh)
    refill = _num(expected_refill_kwh)
    floor_pct = _num(static_floor_pct)
    if floor_pct is None:
        floor_pct = 0.0

    # Rule 4 — a dark input is not permission.
    missing = [n for n, v in (("battery SOC", soc), ("battery capacity", cap),
                              ("overnight forecast", need),
                              ("tomorrow's solar forecast", refill)) if v is None]
    if missing:
        return SpendableBudget(0.0, None, f"unknown {missing[0]} — spending nothing")
    if cap <= 0:
        return SpendableBudget(0.0, None, "no usable battery capacity configured")

    eff = _num(discharge_efficiency) or 0.95
    eff = min(max(eff, 0.05), 1.0)
    pess = _num(pessimism)
    pess = 1.0 if pess is None else max(pess, 1.0)

    stored = max(0.0, soc) / 100.0 * cap

    # Rule 2 — what the night itself demands, in STORED terms.
    night_reserve = max(0.0, need) / eff * pess
    # Rule 1 — and never below the promise.
    static_reserve = max(0.0, min(floor_pct, 100.0)) / 100.0 * cap
    reserve = max(night_reserve, static_reserve)

    headroom = stored - reserve
    if headroom <= 0:
        binding = ("the reserve floor" if static_reserve >= night_reserve
                   else "tonight's own load")
        return SpendableBudget(
            0.0, round(reserve / cap * 100.0, 1),
            f"nothing spendable — {binding} needs all {stored:.1f} kWh stored",
        )

    # Rule 3 — only what tomorrow puts back.
    spendable = min(headroom, max(0.0, refill))

    if spendable <= 0:
        return SpendableBudget(
            0.0, round(reserve / cap * 100.0, 1),
            "nothing spendable — tomorrow's forecast refills nothing",
        )

    if spendable < headroom:
        reason = (f"limited by tomorrow's refill: {refill:.1f} kWh expected back "
                  f"(pack could otherwise spare {headroom:.1f} kWh)")
    else:
        binding = ("the reserve floor" if static_reserve >= night_reserve
                   else f"tonight's need {need:.1f} kWh")
        reason = (f"{spendable:.1f} kWh above what the night requires — "
                  f"holding {reserve:.1f} kWh for {binding}")

    return SpendableBudget(
        round(spendable, 2), round(reserve / cap * 100.0, 1), reason,
    )
