"""(#778) Replay past nights through the budget and count how often it erred.

The backfill gives an install enough evidence to START the budget. It also
gives it enough to CHECK the budget, which is the more valuable half: every
past night is a scenario with a known answer. The pack was at some SOC at dusk,
the house drew a measured amount overnight, and we know how it ended.

Until this existed, "the budget is right" rested on unit tests against the
issue's own worked examples — a test that the code does what I decided, not
that what I decided was correct.

**The failure being hunted is asymmetric, and the scoring reflects that.**
Spending too little costs a little export revenue and nobody notices. Spending
too much strands the house at its floor before dawn, on a night nobody can
un-spend. So the headline number is not average accuracy: it is how many nights
would have breached the floor *because of the budget*, and the worst margin.

That attribution matters. A night where the house drew more than the whole pack
holds breaches whatever the budget said, and counting it as the budget's fault
would make an innocent feature look reckless — and, worse, would hide the
nights it really did cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional


def _f(value: Any) -> Optional[float]:
    """Finite float or None. Never raises."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


@dataclass(frozen=True)
class NightOutcome:
    """What one historical night would have done under the budget."""

    date: str
    scorable: bool
    spendable_kwh: float = 0.0
    actual_drain_kwh: float = 0.0
    margin_kwh: float = 0.0
    """kWh still above the static floor at dawn. Negative means the floor was
    breached — the house ran out of the reserve it was promised."""
    breached: bool = False
    caused_by_budget: bool = False
    """True only when the night would have survived on zero spend AND the pack
    still had room above its floor. Otherwise the night was lost regardless, or
    the hardware floor would have refused to go lower anyway."""

    floor_limited: bool = False
    """The pack reached its floor and stopped there. The budget cannot deepen
    such a night — the battery refuses — so this is not a breach. What the
    spend does instead is bring exhaustion FORWARD, and the house imports for
    longer. A cost to weigh, not a safety failure; conflating the two both
    slanders the budget and drowns out the nights it really did use up."""

    shortened_kwh: float = 0.0
    """On a floor-limited night, how much battery support the spend removed."""


@dataclass(frozen=True)
class BacktestReport:
    nights: int
    breaches_caused: int
    breaches_total: int
    floor_limited_nights: int
    breach_rate: Optional[float]
    worst_margin_kwh: Optional[float]
    verdict: str


def replay_night(
    *,
    date: str,
    capacity_kwh: Any,
    soc_start_pct: Any,
    spendable_kwh: Any,
    actual_drain_kwh: Any,
    static_floor_pct: Any = 20.0,
    soc_low_pct: Any = None,
) -> NightOutcome:
    """Score one night. Unscorable when any term is missing.

    Unscorable is deliberately distinct from "clean": a night we cannot judge
    must not quietly count as a night the budget got right.
    """
    capacity = _f(capacity_kwh)
    soc = _f(soc_start_pct)
    spend = _f(spendable_kwh)
    drain = _f(actual_drain_kwh)
    floor_pct = _f(static_floor_pct)

    if capacity is None or soc is None or drain is None or capacity <= 0:
        return NightOutcome(date=str(date), scorable=False)
    if spend is None:
        spend = 0.0
    if floor_pct is None:
        floor_pct = 0.0

    stored = capacity * max(0.0, min(100.0, soc)) / 100.0
    floor_kwh = capacity * max(0.0, min(100.0, floor_pct)) / 100.0

    margin = stored - spend - drain - floor_kwh
    breached = margin < 0

    # Would it have survived doing nothing? If not, the night was lost before
    # the budget spoke.
    margin_unspent = stored - drain - floor_kwh
    caused = bool(breached and margin_unspent >= 0)

    # Did the pack stop AT its floor? Then the hardware, not the budget, set
    # the depth of the discharge, and the spend could only have moved the
    # moment of exhaustion earlier.
    low = _f(soc_low_pct)
    floor_limited = bool(low is not None and low <= floor_pct + 0.5)
    if floor_limited:
        caused = False

    return NightOutcome(
        date=str(date), scorable=True, spendable_kwh=spend,
        actual_drain_kwh=drain, margin_kwh=margin, breached=breached,
        caused_by_budget=caused, floor_limited=floor_limited,
        shortened_kwh=(spend if floor_limited else 0.0),
    )


def backtest(outcomes: Iterable[NightOutcome]) -> BacktestReport:
    """Aggregate scored nights into a verdict.

    An empty run reports ``no evidence`` rather than a clean bill: a backtest
    over nothing has proven nothing, and reading zero breaches out of zero
    nights as a pass is exactly the self-deception this module exists to avoid.
    """
    scored: List[NightOutcome] = [o for o in (outcomes or []) if o.scorable]
    n = len(scored)
    if n == 0:
        return BacktestReport(0, 0, 0, 0, None, None, "no evidence")

    caused = sum(1 for o in scored if o.caused_by_budget)
    total = sum(1 for o in scored if o.breached)
    limited = sum(1 for o in scored if o.floor_limited)
    worst = min(o.margin_kwh for o in scored)
    return BacktestReport(
        nights=n,
        breaches_caused=caused,
        breaches_total=total,
        floor_limited_nights=limited,
        breach_rate=caused / n,
        worst_margin_kwh=worst,
        verdict="breached" if caused else "no breach",
    )
