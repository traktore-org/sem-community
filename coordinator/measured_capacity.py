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


def _qualifying_ratios(records: Optional[Iterable[dict]]) -> list:
    """kWh-per-percent of every night that passes the quality gates —
    trainable, ≥ ``MIN_SOC_SPAN_PCT`` of SOC span, positive drain — one
    record per date. The verdict and the progress count read the SAME list,
    so the surface can never say "0 nights" while four already qualify
    (PROD 26.08, #778)."""
    ratios = []
    for rec in distinct_nights(records or []):
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
    return ratios


def capacity_progress(records: Optional[Iterable[dict]]) -> int:
    """How many nights already qualify toward the verdict — the honest
    "N / MIN_SAMPLES" a person watches while the evidence accrues."""
    return len(_qualifying_ratios(records))


def measured_capacity(records: Optional[Iterable[dict]]) -> Optional[MeasuredCapacity]:
    """kWh per SOC-percent, from #800's sealed night records.

    Returns ``None`` while the evidence is thin — deliberately, so a caller
    can tell "measured" from "assumed" and stay conservative until it knows.
    """
    if not records:
        return None

    ratios = _qualifying_ratios(records)
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


def distinct_nights(records: Optional[Iterable[dict]]) -> list:
    """One record per night — the most complete one.

    The seal path can emit more than one record for a date: a restart
    mid-night seals what it has, and the night seals again later. Both readers
    below make a claim about NIGHTS ("five nights of evidence"), so counting
    records over-states it, and — worse — a partial night's drain is smaller
    than the whole night's, which drags the need percentile in the unsafe
    direction. Live example on .175: two records for 2026-08-21, one of them
    a 994-second-gap fragment.

    Ranking within a date: a trainable record beats an untrainable one, and
    among equals the larger drain wins — that record saw more of the night.

    Records with no date are each kept: an unknown date is not evidence that
    two records describe the same night, and collapsing them would silently
    discard real evidence.
    """
    if not records:
        return []
    best: dict = {}
    undated: list = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        date = rec.get("date")
        if not date:
            undated.append(rec)
            continue
        rank = (bool(rec.get("trainable")), _f(rec.get("drain_kwh")) or 0.0)
        prev = best.get(date)
        if prev is None or rank > prev[0]:
            best[date] = (rank, rec)
    return [entry[1] for entry in best.values()] + undated


def usable_nights(records: Optional[Iterable[dict]]) -> int:
    """How many nights the envelope can actually learn from.

    The number a card shows as progress. It must count exactly what
    ``expected_overnight_need`` counts — one record per date, trainable only —
    because a user reading "3 of 5" and a gate seeing 1 is a promise the
    feature cannot keep, and they wait days for something that needs longer.
    """
    return sum(1 for rec in distinct_nights(records)
               if isinstance(rec, dict) and rec.get("trainable"))


#: Nights needed before an overnight-need figure is offered.
MIN_NEED_SAMPLES: int = 5

#: Which percentile of observed drains to reserve for. Guido's framing on #778
#: is the "learner-safe envelope" — a HIGH percentile, not an average. Reserving
#: the typical night leaves the pack short on half of them, and being short is
#: not symmetric with being generous: one costs a little export revenue, the
#: other strands the house at its floor before dawn.
#:
#: The DIRECTION was judgement; the VALUE is measured. Backtesting 211 real
#: nights (scripts/backtest_budget.py) priced every candidate:
#:
#:     pctile  spending nights  total spent  breaches  worst breach
#:     p70     103              74.0 kWh     3 (3%)    -0.48 kWh
#:     p80      97              63.6 kWh     3 (3%)    -0.40 kWh
#:     p85      90              53.5 kWh     2 (2%)    -0.12 kWh
#:     p90      68              30.0 kWh     1 (1%)    -0.05 kWh
#:     p95       5               0.3 kWh     0         -
#:
#: p85 is the knee: the worst floor violation drops 70% while 84% of the energy
#: survives. p90 costs half the value for a further 70 Wh; p95 is a cliff where
#: the feature simply stops working. One install's data, so this is a default
#: and not a law — the sweep ships so any install can price its own.
NEED_PERCENTILE: float = 0.85


def expected_overnight_need(
    records: Optional[Iterable[dict]],
) -> Optional[float]:
    """kWh the house has actually drawn from the pack overnight, high-percentile.

    Uses the same quality gate as the capacity reader — ``trainable`` nights
    only — and returns ``None`` while the evidence is thin, so a caller can
    tell measured from assumed and stay conservative until it knows.
    """
    if not records:
        return None
    drains = []
    for rec in distinct_nights(records):
        if not isinstance(rec, dict) or not rec.get("trainable"):
            continue
        d = _f(rec.get("drain_kwh"))
        if d is None or d < 0:
            continue
        # (#778) A night the GRID finished is censored DOWNWARD: the battery
        # hit reserve, the house kept drawing, and ``drain_kwh`` records only
        # the battery's share. battery_night.py's docstring says so outright
        # — "the budget's consumer must treat such drains as floors" — and
        # this consumer did not, so exactly the nights that needed the most
        # recorded the smallest and dragged the p85 threshold DOWN. The
        # percentile meant to protect the biggest nights was being lowered
        # by them.
        #
        # No special case is needed: ``drain_kwh`` integrates
        # battery_to_home_w and ``night_grid_kwh`` integrates grid_to_home_w,
        # both home-directed with the EV excluded, so their sum is the
        # house's actual overnight need on EVERY night. On an uncensored
        # night the grid term is ~0 and this is the drain, unchanged.
        # Records written before the field existed simply contribute 0.
        g = _f(rec.get("night_grid_kwh"))
        if g is not None and g > 0:
            d += g
        drains.append(d)
    if len(drains) < MIN_NEED_SAMPLES:
        return None
    drains.sort()
    idx = min(len(drains) - 1, int(round(NEED_PERCENTILE * (len(drains) - 1))))
    return round(drains[idx], 2)
