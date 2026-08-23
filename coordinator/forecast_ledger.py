"""#778 — a forecast ledger with a HORIZON, so day-2 can be trusted by evidence.

Guido, 23.08: *"Are we creating a ledger for the forecast as well so we can
plan today with the forecast of tomorrow or the day after tomorrow?"*

SEM already records forecast-vs-actual for **today** (``DailyForecastRecord``,
which feeds the dampening factor). That answers "how wrong are we usually" for
a single horizon. The spendable-battery budget needs to look two days out, and
a two-day-out forecast is materially less reliable than a one-day-out one —
**by how much is an empirical question nobody has measured.** So this measures
it instead of assuming.

The shape: *on day D we said day D+h would produce X; on day D+h it actually
produced Y.* Accuracy is reported PER HORIZON, so the budget can scale its
confidence in the day after tomorrow separately from tomorrow.

The rule that keeps it honest: **too few samples is `None`, not `1.0`.** A
default that looks confident before any evidence exists is worse than an
admission of ignorance — a caller can be conservative with "unknown", but it
cannot detect a comfortable lie. Same reasoning as #818: a dark input must not
read as permission.

Pure: no Home Assistant imports, so it can be tested and argued with on its
own, and serialised into SEM's existing store.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

#: Below this many settled days a horizon reports UNKNOWN rather than a ratio.
#: Seven is a week of weather — enough that one freak day cannot set policy.
MIN_SAMPLES_FOR_TRUST: int = 7

#: Which percentile of observed accuracy to spend against.
#:
#: The mirror image of ``measured_capacity.NEED_PERCENTILE``, and for the same
#: reason. That one takes a HIGH percentile of what the house draws overnight,
#: because reserving for the typical night leaves the pack short on half of
#: them. This one takes a LOW percentile of what the sun actually delivers,
#: because planning against the typical day spends the battery on energy that
#: does not arrive on half of them.
#:
#: Measured, not chosen by taste: .175's own 139 settled days have a mean ratio
#: of 1.050 — an UNBIASED forecast — with p10 0.514 and p90 1.502. Trusting the
#: mean (capped at 1.0) would have spent against the full forecast on days that
#: under-delivered **58 times out of 139 (42%)**. At p20 that is 28 of 139
#: (20%) — which is what "p20" means, chosen deliberately rather than suffered.
REFILL_TRUST_PERCENTILE: float = 0.2

#: Days kept before the oldest are pruned. A season is the useful window for a
#: seasonal quantity; beyond that the sun has moved.
DEFAULT_MAX_DAYS: int = 120


@dataclass(frozen=True)
class HorizonAccuracy:
    """How a given horizon has actually performed."""

    horizon_days: int
    samples: int
    mean_ratio: float
    """actual / forecast, averaged over settled days. < 1 means the forecast
    habitually over-promises at this horizon."""


class ForecastLedger:
    """Forecasts made for a day, at each horizon, and what the day delivered."""

    def __init__(self, max_days: int = DEFAULT_MAX_DAYS) -> None:
        self._max_days = max(1, int(max_days))
        # date -> {"actual": float|None, "f": {horizon:int -> kwh:float}}
        self._days: Dict[str, dict] = {}

    # ── writing ──────────────────────────────────────────────────────────
    def record(self, target_date: str, horizon_days: int, forecast_kwh) -> None:
        """Note that today we expect ``target_date`` to produce this much."""
        try:
            kwh = float(forecast_kwh)
            h = int(horizon_days)
        except (TypeError, ValueError):
            return
        if kwh != kwh or h < 0:          # NaN / nonsense horizon
            return
        day = self._days.setdefault(str(target_date), {"actual": None, "f": {}})
        day["f"][h] = kwh
        self._prune()

    def settle(self, target_date: str, actual_kwh) -> None:
        """Record what the day actually produced."""
        try:
            actual = float(actual_kwh)
        except (TypeError, ValueError):
            return
        if actual != actual:
            return
        day = self._days.setdefault(str(target_date), {"actual": None, "f": {}})
        day["actual"] = actual
        self._prune()

    # ── reading ──────────────────────────────────────────────────────────
    def forecast_for(self, target_date: str, horizon_days: int) -> Optional[float]:
        return (self._days.get(str(target_date), {}).get("f", {})
                .get(int(horizon_days)))

    def actual_for(self, target_date: str) -> Optional[float]:
        return self._days.get(str(target_date), {}).get("actual")

    def days(self) -> list:
        return sorted(self._days)

    def _ratios(self, horizon_days) -> list:
        """Every settled actual/forecast ratio at this horizon.

        One extractor for accuracy, trust and the sample count, so the number a
        user is shown as progress and the evidence a decision is made from can
        never be counted differently.
        """
        try:
            h = int(horizon_days)
        except (TypeError, ValueError):
            return []
        ratios = []
        for rec in self._days.values():
            actual = rec.get("actual")
            fc = rec.get("f", {}).get(h)
            if actual is None or fc is None or fc <= 0:
                continue
            ratios.append(actual / fc)
        return ratios

    def accuracy(self, horizon_days: int) -> Optional[HorizonAccuracy]:
        """How this horizon has performed on AVERAGE, or None while evidence
        is thin.

        Diagnostic: the mean answers "is this forecast biased", which is a real
        question and worth showing. It is deliberately NOT what decides
        spending — see ``trust``.
        """
        ratios = self._ratios(horizon_days)
        if len(ratios) < MIN_SAMPLES_FOR_TRUST:
            return None
        return HorizonAccuracy(int(horizon_days), len(ratios),
                               sum(ratios) / len(ratios))

    def settled_samples(self, horizon_days) -> int:
        """How many settled forecast/actual pairs this horizon has.

        The numerator of the "N of 7" a card shows while trust is still being
        earned. It counts exactly what ``accuracy`` counts — including the
        ``fc <= 0`` skip — so the progress a user watches and the evidence the
        trust is actually built from can never disagree.
        """
        return len(self._ratios(horizon_days))

    def has_horizon(self, horizon_days) -> bool:
        """Whether anything has ever published a forecast at this horizon.

        ``trust`` answers None for two unrelated reasons — too few days yet,
        and no source at all. Only the first one resolves by waiting, so a
        user staring at an empty day-2 figure needs to be told which they are
        looking at (live on .175: Forecast.Solar publishes d2 only as
        per-string entities, so this horizon never fills there).
        """
        try:
            h = int(horizon_days)
        except (TypeError, ValueError):
            return False
        return any(h in (rec.get("f") or {}) for rec in self._days.values())

    def trust(self, horizon_days: int) -> Optional[float]:
        """A factor to scale a forecast at this horizon, or None if unknown.

        A LOW percentile of observed accuracy, not the average — see
        ``REFILL_TRUST_PERCENTILE``. An unbiased forecast with a wide spread
        must not read as fully trustworthy: the average day is not the day
        that hurts.

        Capped at 1.0: a forecast that habitually UNDER-promises does not
        license spending more than it predicts. Optimism is capped; pessimism
        is respected in full.
        """
        ratios = self._ratios(horizon_days)
        if len(ratios) < MIN_SAMPLES_FOR_TRUST:
            return None
        ratios.sort()
        # Nearest-rank, rounding DOWN: with few samples the index errs toward
        # the worse day, which is the direction that cannot hurt.
        idx = int(REFILL_TRUST_PERCENTILE * (len(ratios) - 1))
        return min(1.0, max(0.0, ratios[idx]))

    def backfill(self, pairs, horizon: int) -> int:
        """Merge reconstructed forecast/actual pairs; return how many landed.

        A day the coordinator already recorded LIVE is never overwritten. The
        live record is what SEM actually saw at the moment it decided; the
        backfill is a reconstruction from hourly buckets, and where the two
        disagree the one that was there wins.
        """
        added = 0
        for target, (forecast_kwh, actual_kwh) in (pairs or {}).items():
            date = target.isoformat() if hasattr(target, "isoformat") else str(target)
            rec = self._days.get(date)
            if rec is not None and rec.get("f", {}).get(int(horizon)) is not None:
                continue  # live evidence already stands for this day
            self.record(date, horizon, forecast_kwh)
            self.settle(date, actual_kwh)
            added += 1
        if added:
            self._prune()
        return added

    # ── persistence ──────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "max_days": self._max_days,
            "days": {d: {"actual": r.get("actual"),
                         "f": {str(k): v for k, v in r.get("f", {}).items()}}
                     for d, r in self._days.items()},
        }

    @classmethod
    def from_dict(cls, raw) -> "ForecastLedger":
        led = cls(max_days=(raw or {}).get("max_days", DEFAULT_MAX_DAYS))
        for d, r in ((raw or {}).get("days") or {}).items():
            fc = {}
            for k, v in (r.get("f") or {}).items():
                try:
                    fc[int(k)] = float(v)
                except (TypeError, ValueError):
                    continue
            led._days[str(d)] = {"actual": r.get("actual"), "f": fc}
        led._prune()
        return led

    # ── internals ────────────────────────────────────────────────────────
    def _prune(self) -> None:
        if len(self._days) <= self._max_days:
            return
        for stale in sorted(self._days)[: len(self._days) - self._max_days]:
            self._days.pop(stale, None)
