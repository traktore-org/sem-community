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


#: The static reserve assumed when an install has never set one.
#:
#: Not a taste call — it is the value the config default documents, and it must
#: apply to installs that never touched the setting. That is exactly where it
#: was NOT applying: ``config.get("battery_reserve_soc", 20)`` returns None when
#: the key exists holding null (how PROD is configured), the None reached this
#: function, and the floor resolved to 0.0 — no backstop at all, on the one
#: install with a real battery.
#:
#: An explicit 0 remains a choice and is honoured. None is an absence, and the
#: two must not collapse into each other.
DEFAULT_STATIC_FLOOR_PCT: float = 20.0

#: The forecast-pessimism multiplier assumed when an install has never set one.
#:
#: Same shape as the floor above, found by sweeping for siblings: the old code
#: resolved a missing pessimism to 1.0 — NO margin — while its own signature
#: documented 1.2. An install carrying a null in options quietly spent ~9% more
#: than one that had never been configured at all.
DEFAULT_PESSIMISM: float = 1.2

#: Discharge efficiency assumed when unset. Already handled correctly before
#: the sweep; named here so all three live in one place and the next reader
#: does not have to work out which of them are safe.
DEFAULT_DISCHARGE_EFFICIENCY: float = 0.95


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
    static_floor_pct=DEFAULT_STATIC_FLOOR_PCT,
    pessimism: float = 1.2,
    discharge_efficiency: float = 0.95,
) -> SpendableBudget:
    """How many kWh of this battery are genuinely surplus tonight.

    ``overnight_need_kwh`` is the forecast house draw until PV meaningfully
    resumes. ``pessimism`` (>= 1) inflates the reserve — the user's own margin
    against a forecast that disappoints.

    ``expected_refill_kwh`` is **NOT tomorrow's raw solar forecast.** Guido
    pinned this on #778 before anyone built it: *"will it refill" is not a
    scalar forecast question — the morning solar is also claimed by tomorrow's
    packed EV blocks and loads, and the day ledger is the only component that
    already does that subtraction.* Wiring this to ``forecast_tomorrow_kwh``
    would systematically over-promise: a 40 kWh day already owes 12 kWh to the
    house and whatever the car has booked. Pass the ledger's expected refill
    AFTER tomorrow's claims, capped by the learner's verified envelope:

        spendable = min(learner-safe envelope,
                        ledger refill after tomorrow's packed claims) - reserve

    A corollary worth exploiting later: where the ledger expects surplus beyond
    capacity + demands (clipping), tonight's spend is **provably free** — that
    is the strongest case this budget can make, and it comes from the ledger,
    never from a scalar.
    """
    soc = _num(soc_pct)
    cap = _num(usable_capacity_kwh)
    need = _num(overnight_need_kwh)
    refill = _num(expected_refill_kwh)
    floor_pct = _num(static_floor_pct)
    if floor_pct is None:
        # Silence means "nobody said", not "spend to empty".
        floor_pct = DEFAULT_STATIC_FLOOR_PCT

    # Rule 4 — a dark input is not permission.
    missing = [n for n, v in (("battery SOC", soc), ("battery capacity", cap),
                              ("overnight forecast", need),
                              ("tomorrow's solar forecast", refill)) if v is None]
    if missing:
        return SpendableBudget(0.0, None, f"unknown {missing[0]} — spending nothing")
    if cap <= 0:
        return SpendableBudget(0.0, None, "no usable battery capacity configured")

    eff = _num(discharge_efficiency)
    eff = DEFAULT_DISCHARGE_EFFICIENCY if eff is None else eff
    eff = min(max(eff, 0.05), 1.0)
    pess = _num(pessimism)
    # Silence is the documented default, not "no margin" — the floor bug's
    # sibling, in the same unsafe direction.
    pess = DEFAULT_PESSIMISM if pess is None else max(pess, 1.0)

    stored = max(0.0, soc) / 100.0 * cap

    # Rule 2 — what the night itself demands, in STORED terms.
    night_reserve = max(0.0, need) / eff * pess
    # Rule 1 — the emergency floor, which is where the pack must be AT DAWN.
    static_reserve = max(0.0, min(floor_pct, 100.0)) / 100.0 * cap
    # ADDITIVE, not max(): the floor is the level the night must END on, so the
    # night's own draw sits on top of it. #778's worked example is exactly this
    # — 28.5 stored − 7 overnight − 2 reserve = 19.5 spendable. Taking the
    # larger of the two instead would let the pack reach the emergency floor
    # before sunrise, which is the one thing the floor exists to prevent.
    reserve = night_reserve + static_reserve

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

    # The floor a user actually experiences is where the pack lands, which the
    # refill cap can lift above the reserve: #778's "minimum SOC 30 % tonight
    # because tomorrow is sunny, 70 % because it is cloudy" is this number, not
    # the reserve alone.
    effective_floor_kwh = stored - spendable
    return SpendableBudget(
        round(spendable, 2), round(effective_floor_kwh / cap * 100.0, 1), reason,
    )
