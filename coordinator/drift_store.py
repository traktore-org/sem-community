"""(#1081) Drift samples kept across restarts — RECORD ONLY.

How fast a room or tank cools while its device is off lives in memory for
4 h (``comfort_drift.learn_drift``) and was lost at every restart. This keeps
one row per free-running clock hour for 14 days, so a rate can be learned
over weeks. NOTHING decides from it yet: the planner's deadline and drift
use stay on the 4 h buffers. A later version reads ``summarize(...)`` here
(``rate_c_per_h`` at an outdoor temperature) in
``BandMixin.comfort_plan_demand`` instead of the 4 h off-samples.

Row: ``[hour_id, slope_c_per_h, mean_c, outdoor_c | None, samples]`` where
``hour_id`` = whole hours since the epoch. Pure, stdlib only.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

#: how long a row is kept
KEEP_HOURS = 14 * 24
#: free-running hours needed before a rate is shown
MIN_HOURS = 12
#: the outdoor temperature a learned rate is quoted at
REFERENCE_OUTDOOR_C = 5.0
#: outdoor spread (K) needed to fit the rate against temperature
MIN_OUTDOOR_SPREAD_K = 3.0
LEARNING = "learning"
LEARNED = "learned"


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def sanitize(raw: Any, now_hour: int) -> List[list]:
    """Rows from a stored value; anything damaged is dropped, never
    guessed. Sorted, unique per hour, pruned to ``KEEP_HOURS``."""
    rows: Dict[int, list] = {}
    for item in (raw.get("hours") if isinstance(raw, dict) else None) or []:
        try:
            h, slope, mean, out, n = item
        except (TypeError, ValueError):
            continue
        h, slope, mean, n = _finite(h), _finite(slope), _finite(mean), _finite(n)
        if None in (h, slope, mean, n) or n < 1:
            continue
        if not now_hour - KEEP_HOURS <= h <= now_hour:
            continue
        rows[int(h)] = [int(h), round(slope, 4), round(mean, 2),
                        None if _finite(out) is None else round(float(out), 1),
                        int(n)]
    return [rows[h] for h in sorted(rows)]


def prune(rows: List[list], now_hour: int) -> List[list]:
    return [r for r in rows if r[0] >= now_hour - KEEP_HOURS]


def make_row(hour: int, slope: float, mean_c: float,
             outdoor_c: Optional[float], n: int) -> list:
    out = _finite(outdoor_c)
    return [int(hour), round(float(slope), 4), round(float(mean_c), 2),
            None if out is None else round(out, 1), int(n)]


def _fit(points: List[tuple]) -> Optional[tuple]:
    """Least squares ``y = a + b x`` over ``(x, y)``; None if flat in x."""
    n = float(len(points))
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    if den <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in points) / den
    return my - b * mx, b


def summarize(rows: Iterable[list]) -> Optional[Dict[str, Any]]:
    """The Diagnose summary, or None with no rows. ``learning`` until
    ``MIN_HOURS`` hours; then ``learned`` with ``rate_c_per_h`` (negative =
    cooling) at ``REFERENCE_OUTDOOR_C`` when the rows span enough outdoor
    temperature to say, else the plain mean at the outdoor mean."""
    rows = list(rows)
    if not rows:
        return None
    out: Dict[str, Any] = {
        "state": LEARNING, "samples": sum(r[4] for r in rows),
        "hours": len(rows),
        "days": round((rows[-1][0] - rows[0][0]) / 24.0, 1)}
    if len(rows) < MIN_HOURS:
        return out
    pts = [(r[3], r[1]) for r in rows if r[3] is not None]
    fit = _fit(pts) if len(pts) >= MIN_HOURS and (
        max(x for x, _ in pts) - min(x for x, _ in pts)
        >= MIN_OUTDOOR_SPREAD_K) else None
    if fit is not None:
        rate, ref = fit[0] + fit[1] * REFERENCE_OUTDOOR_C, REFERENCE_OUTDOOR_C
    else:
        rate = sum(r[1] for r in rows) / len(rows)
        ref = (round(sum(x for x, _ in pts) / len(pts), 1) if pts else None)
    out.update(state=LEARNED, rate_c_per_h=round(rate, 3), ref_outdoor_c=ref)
    return out
