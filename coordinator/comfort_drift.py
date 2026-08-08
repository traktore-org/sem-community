"""The drift learner (#638 / #705 Phase 3) — what makes comfort plannable.

A room's temperature drifts toward ambient while its device is off. Learn
the rate from readings SEM already takes, and "the room hits the limit at
17:20" becomes a deadline-shaped demand the day planner can place into a
forecast-surplus window — the same shape as the overnight EV floor, which
is the whole point: one packer, one verdict, two horizons.

Pure — stdlib only, no Home Assistant imports, same contract as
``overnight_planner`` and ``plan_verdict``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class DriftEstimate:
    """The room's free-running temperature slope.

    Positive = warming, negative = cooling. Advisory like everything the
    planning layer says: re-learned continuously, never a schedule of its
    own.
    """

    rate_c_per_h: float


_MIN_SAMPLES = 3
_MIN_SPAN_H = 0.25


def learn_drift(samples: List[Tuple[datetime, float]]) -> Optional[DriftEstimate]:
    """Least-squares slope over (timestamp, °C) samples taken device-OFF.

    Least squares rather than endpoint-difference so a single noisy
    reading cannot flip the sign — the sign decides whether a room is
    approaching its limit at all. ``None`` when there is not enough to
    say (fewer than 3 samples, or less than 15 minutes of span): an
    unknown drift must read as "no prediction", never as "no risk".
    """
    if not samples or len(samples) < _MIN_SAMPLES:
        return None
    pts = sorted(samples, key=lambda p: p[0])
    t0 = pts[0][0]
    span_h = (pts[-1][0] - t0).total_seconds() / 3600.0
    if span_h < _MIN_SPAN_H:
        return None
    xs = [(t - t0).total_seconds() / 3600.0 for t, _ in pts]
    ys = [v for _, v in pts]
    n = float(len(pts))
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return DriftEstimate(rate_c_per_h=slope)


def time_to_limit(
    est: DriftEstimate,
    *,
    current_c: float,
    limit_c: float,
    direction: str,
    now: datetime,
) -> Optional[datetime]:
    """When the free-running room crosses its comfort limit.

    ``None`` = never on the current drift (flat, or drifting away from
    the limit) — a room that keeps itself comfortable produces no demand.
    Already past the limit answers ``now``: the demand is immediate,
    which the reactive layer is already handling via the FORCED band.
    """
    toward = limit_c - current_c
    if direction == "cool":
        if toward <= 0:
            return now
        if est.rate_c_per_h <= 0:
            return None
    else:
        if toward >= 0:
            return now
        if est.rate_c_per_h >= 0:
            return None
    hours = toward / est.rate_c_per_h
    return now + timedelta(hours=hours)


def banking_energy_kwh(
    *,
    current_c: float,
    target_c: float,
    direction: str,
    active_rate_c_per_h: float,
    rated_power_w: float,
) -> Optional[float]:
    """kWh of running needed to bring the room from ``current`` back to
    ``target`` at the learned ACTIVE rate (°C/h while the device runs —
    the same least-squares learner, fed device-ON samples).

    ``0.0`` = already banked, nothing to plan. ``None`` = the model
    cannot say — an active rate that is flat or moves the room AWAY from
    target contradicts the device's direction, and "cannot say" must
    never read as "nothing needed" (0) or become a huge phantom demand.
    """
    gap_c = (current_c - target_c if direction == "cool"
             else target_c - current_c)
    if gap_c <= 0:
        return 0.0
    toward = (-active_rate_c_per_h if direction == "cool"
              else active_rate_c_per_h)
    if toward <= 0:
        return None
    hours = gap_c / toward
    return rated_power_w * hours / 1000.0
