"""#778 — a forecast ledger with a HORIZON, so day-2 can be trusted by evidence.

Asked 23.08: *"Are we creating a ledger for the forecast as well so we can
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

#: (#1022) Daylight minutes the solar input may be unreadable and the day
#: still count. The reader's dark counter only runs while the sun is up (an
#: inverter asleep at night reads 0 W, not dark), so this is daylight time.
#: A blip or a short integration reload is under it; a missing midday is not.
DARK_DAY_MAX_MIN: float = 30.0


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

    def settle_day(self, target_date: str, actual_kwh, dark_min) -> bool:
        """(#1022) THE rule: a day's actual counts only when the solar input
        was readable for nearly all of its daylight. Past the limit the day
        is marked dark, any earlier value is cleared and later settles are
        refused, so a gap is never learned as a 0 kWh day. Returns True when
        the day was newly marked (the caller persists). A snow day with a
        readable input has no dark minutes and still settles as 0."""
        key = str(target_date)
        try:
            dark = float(dark_min or 0.0)
        except (TypeError, ValueError):
            dark = 0.0
        if dark > DARK_DAY_MAX_MIN or self.is_dark(key):
            newly = not self.is_dark(key)
            day = self._days.setdefault(key, {"actual": None, "f": {}})
            day["actual"] = None
            day["dark"] = True
            self._prune()
            return newly
        self.settle(key, actual_kwh)
        return False

    def is_dark(self, target_date: str) -> bool:
        return bool(self._days.get(str(target_date), {}).get("dark"))

    # ── reading ──────────────────────────────────────────────────────────
    def forecast_for(self, target_date: str, horizon_days: int) -> Optional[float]:
        return (self._days.get(str(target_date), {}).get("f", {})
                .get(int(horizon_days)))

    def actual_for(self, target_date: str) -> Optional[float]:
        return self._days.get(str(target_date), {}).get("actual")

    def days(self) -> list:
        return sorted(self._days)

    def settled_pairs(self, horizon_days) -> Dict[str, tuple]:
        """``{date: (forecast, actual)}`` for every settled day at a horizon.

        The one extractor behind accuracy, trust, the sample count and the
        source recommendation (#822), so what a user is shown and what a
        decision is made from can never be counted differently. A day with
        no forecast, no actual or a forecast of 0 is not a sample.
        """
        try:
            h = int(horizon_days)
        except (TypeError, ValueError):
            return {}
        pairs = {}
        for date, rec in self._days.items():
            actual = rec.get("actual")
            fc = rec.get("f", {}).get(h)
            if actual is None or fc is None or fc <= 0:
                continue
            pairs[date] = (fc, actual)
        return pairs

    def _ratios(self, horizon_days) -> list:
        """Every settled actual/forecast ratio at this horizon."""
        return [a / fc for fc, a in self.settled_pairs(horizon_days).values()]

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

    def horizon_state(self, horizon_days) -> str:
        """(#884) ``learning`` | ``present`` | ``unsupported``.

        ``has_horizon`` answers a boolean to a question with three answers,
        and the card rendered the harshest one: a brand-new install, which
        has no records at ANY horizon yet, was told its provider does not
        publish this one. @ArneGollin1987 saw that on all three integrations
        at once — two of which do publish it.

        An empty ledger is evidence of nothing. Only once days have been
        recorded WITHOUT this horizon appearing is "the source does not
        supply it" a claim the ledger can support.
        """
        try:
            h = int(horizon_days)
        except (TypeError, ValueError):
            return "unsupported"
        if not self._days:
            return "learning"
        if any(h in (rec.get("f") or {}) for rec in self._days.values()):
            return "present"
        return "unsupported"

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
            "days": {d: self._day_dict(r) for d, r in self._days.items()},
        }

    @staticmethod
    def _day_dict(r: dict) -> dict:
        out = {"actual": r.get("actual"),
               "f": {str(k): v for k, v in r.get("f", {}).items()}}
        if r.get("dark"):
            out["dark"] = True
        return out

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
            if r.get("dark"):
                led._days[str(d)]["dark"] = True
                led._days[str(d)]["actual"] = None
        led._prune()
        return led

    # ── internals ────────────────────────────────────────────────────────
    def _prune(self) -> None:
        if len(self._days) <= self._max_days:
            return
        for stale in sorted(self._days)[: len(self._days) - self._max_days]:
            self._days.pop(stale, None)


# ── (#822) option 2: recommend the source that has been closest ───────────

#: A challenger must have at least this much LESS scaled error than
#: the source in use. Under it, two sources are one weather apart, not two
#: skills apart, and a hint would flip back and forth.
RECOMMEND_MARGIN: float = 0.15

#: Shared settled days before a source may be recommended. Two weeks: both
#: a clear and a grey spell, so one freak day cannot decide.
RECOMMEND_MIN_DAYS: int = 14


def _loo_scaled_error(pairs, days) -> Optional[float]:
    """Mean leave-one-out scaled error (kWh) of one source over ``days``.

    SEM scales a forecast by its own learned factor, so a source is judged on
    how well it follows the day-to-day SHAPE after scaling, not on its raw
    size (#822: an 8 kWp source on a 16 kWp roof looked 38 % better only
    because its wrong size cancelled another source's overshoot). Per day d:
    k = sum(actual, other days) / sum(forecast, other days), error =
    |k * forecast_d - actual_d|. Leaving d out keeps the day from tuning its
    own scale.
    """
    tot_f = sum(pairs[d][0] for d in days)
    tot_a = sum(pairs[d][1] for d in days)
    errs = []
    for d in days:
        fc, act = pairs[d]
        rest_f = tot_f - fc
        if rest_f <= 0:
            return None
        errs.append(abs((tot_a - act) / rest_f * fc - act))
    return sum(errs) / len(errs)


def _shared_mae(a: "ForecastLedger", b: "ForecastLedger", horizon: int,
                skip: Optional[str]):
    """Scaled error of each ledger over the SAME settled days.

    Like with like: a day only counts when BOTH had a forecast and the actual
    is known, so a source that was down on a bad day is not rewarded for it.
    ``skip`` is today, whose actual is still growing.
    """
    pa, pb = a.settled_pairs(horizon), b.settled_pairs(horizon)
    days = [d for d in pa if d in pb and d != skip]
    if len(days) < 2:
        return None, len(days)
    ea, eb = _loo_scaled_error(pa, days), _loo_scaled_error(pb, days)
    if ea is None or eb is None:
        return None, len(days)
    return (ea, eb), len(days)


def _less_error_pct(current_ledger, other_ledger, horizon, skip):
    """(percent less error, days) of ``other`` vs ``current``, or (None, n)."""
    errs, n = _shared_mae(current_ledger, other_ledger, horizon, skip)
    if errs is None or errs[0] <= 0:
        return None, n
    return (1.0 - errs[1] / errs[0]) * 100.0, n


def recommend_source(ledgers, current, min_days: int = RECOMMEND_MIN_DAYS,
                     margin: float = RECOMMEND_MARGIN,
                     today: Optional[str] = None) -> Optional[dict]:
    """The source that has clearly been closest for THIS roof, or None.

    None means "no hint": the source in use is already best, the lead is
    inside the margin, the shared evidence is under ``min_days``, or there is
    nothing to compare with. It never switches anything (#822: the correction
    factor learns on the source in use, so only the user may move it).

    Measure: leave-one-out scaled error against the day's real production at
    today's horizon (h=0), on days both sources have settled. Tomorrow's horizon
    (h=1) rides along as ``tomorrow_by_pct`` when both have enough days.
    """
    cur = (ledgers or {}).get(current)
    if cur is None:
        return None
    best = None
    for name, led in ledgers.items():
        if name == current:
            continue
        pct, days = _less_error_pct(cur, led, 0, today)
        if pct is None or days < min_days or pct < margin * 100.0:
            continue
        if best is None or pct > best["by_pct"]:
            best = {"source": name, "by_pct": round(pct, 1), "days": days}
    if best is None:
        return None
    t_pct, t_days = _less_error_pct(cur, ledgers[best["source"]], 1, today)
    best["tomorrow_by_pct"] = (round(t_pct, 1)
                               if t_pct is not None and t_days >= min_days
                               else None)
    return best
