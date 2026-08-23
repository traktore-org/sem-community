"""#778 — what is a percent of this battery actually worth?

Guido, 23.08: *"Does the battery SOC = energy also get a ledger, to have it all
there — or would that be too complicated?"*

Not complicated, and it needs **no new recording**. Every sealed night from
#800 already carries ``drain_kwh``, ``soc_start``, ``soc_morning``,
``outdoor_temp_c`` and a ``trainable`` quality flag, so kWh-per-percent is
arithmetic over records SEM already writes. This is a READER, not a fourth
ledger.

Why it matters more than the forecast ledger: the spendable budget's
``usable_capacity_kwh`` is a configured **nameplate**. If a 30 kWh pack really
delivers 0.24 kWh/% against a nominal 0.30, every spendable number is 20 % too
generous — and it fails in the dangerous direction, selling energy the pack did
not have. Measuring it also tracks degradation for free: an ageing pack simply
reports fewer kWh per percent and the budget tightens itself.

Same shape as the forecast ledger and the night recorder, deliberately —
median over quality-gated samples, ``None`` until there is evidence, never a
confident default. One pattern, three quantities: how good is the forecast,
how much does the night need, how much is a percent actually worth.

The gates exist because of how the inputs really behave:

* SOC is usually integer-resolution, so a small span is noise rather than a
  measurement — hence ``MIN_SOC_SPAN_PCT``;
* the curve is not linear at the extremes (top-balancing, BMS reserve);
* a night that did not discharge measures nothing at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

#: A span below this cannot be measured through integer-resolution SOC.
MIN_SOC_SPAN_PCT: float = 15.0

#: Nights needed before a figure is offered. Fewer than the forecast ledger's
#: seven: capacity is a physical property of the pack, not a property of the
#: weather, so it does not need a week of conditions to be representative.
MIN_SAMPLES: int = 5


@dataclass(frozen=True)
class MeasuredCapacity:
    """What the pack has actually been delivering, per percent of SOC."""

    kwh_per_pct: float
    usable_kwh: float
    """``kwh_per_pct × 100`` — the implied usable capacity, for comparison
    against the configured nameplate."""
    samples: int
    reason: str

    def drift_vs(self, nameplate_kwh) -> Optional[float]:
        """Fractional difference from the configured capacity.

        Negative means the pack delivers less than its nameplate — the case
        that makes a budget overspend.
        """
        try:
            nameplate = float(nameplate_kwh)
        except (TypeError, ValueError):
            return None
        if nameplate <= 0:
            return None
        return (self.usable_kwh - nameplate) / nameplate


def _f(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def measured_capacity(records: Optional[Iterable[dict]]) -> Optional[MeasuredCapacity]:
    """kWh per SOC-percent, from #800's sealed night records.

    Returns ``None`` while the evidence is thin — deliberately, so a caller
    can tell "measured" from "assumed" and stay conservative until it knows.
    """
    if not records:
        return None

    ratios = []
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("trainable"):
            continue
        start = _f(rec.get("soc_start"))
        morning = _f(rec.get("soc_morning"))
        drain = _f(rec.get("drain_kwh"))
        if start is None or morning is None or drain is None:
            continue
        span = start - morning
        if span < MIN_SOC_SPAN_PCT:      # also rejects a rising SOC (negative)
            continue
        if drain <= 0:
            continue
        ratios.append(drain / span)

    if len(ratios) < MIN_SAMPLES:
        return None

    ratios.sort()
    mid = len(ratios) // 2
    median = (ratios[mid] if len(ratios) % 2
              else (ratios[mid - 1] + ratios[mid]) / 2.0)

    return MeasuredCapacity(
        kwh_per_pct=round(median, 4),
        usable_kwh=round(median * 100.0, 2),
        samples=len(ratios),
        reason=(f"median of {len(ratios)} night(s) with at least "
                f"{MIN_SOC_SPAN_PCT:.0f}% SOC span"),
    )
