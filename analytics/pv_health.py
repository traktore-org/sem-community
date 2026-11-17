"""(#1022) PV health — does the plant do what the forecast said?

One colour from seven settled days of yield against forecast, the minutes
the solar input was dark today, how long since a full-yield day, and a
snow flag. Pure: no Home Assistant, no clock. The coordinator feeds it
from the forecast ledger and the sensor reader.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

#: colour, lowest ratio (yield ÷ forecast) that earns it. Below the last
#: one is red.
THRESHOLDS: Tuple[Tuple[str, float], ...] = (
    ("green", 0.85),
    ("yellow", 0.65),
    ("orange", 0.40),
)
#: a day at this ratio or above counts as a full-yield day
FULL_YIELD_RATIO = 0.90
#: (#1022) a full-yield day this recent (0 = the last settled day) proves
#: the plant delivers: a low week is then the forecast's error (fog, grey
#: winter days overshot), not a fault, and the colour stops at yellow. A
#: real fault (a dead string, a tripped inverter) takes the full-yield days
#: away, so it still turns orange or red — at most this many days later.
RECENT_FULL_DAYS = 2
#: fewer settled days than this → no verdict (state None)
MIN_SETTLED_DAYS = 3
#: the window the ratio is taken over
WINDOW_DAYS = 7
#: snow: the forecast says at least this much now …
SNOW_EXPECT_W = 500.0
#: … the plant delivers less than this share of it …
SNOW_YIELD_SHARE = 0.05
#: … for at least this long
SNOW_HOLD_S = 2 * 3600


@dataclass(frozen=True)
class PvHealth:
    state: Optional[str]            # green | yellow | orange | red | None
    ratio_7d: Optional[float]
    settled_days: int
    downtime_min_today: int
    days_since_full_yield: Optional[int]
    snow: bool

    def as_attributes(self) -> dict:
        return {
            "ratio_7d": self.ratio_7d,
            "settled_days": self.settled_days,
            "downtime_min_today": self.downtime_min_today,
            "days_since_full_yield": self.days_since_full_yield,
            "snow": self.snow,
        }


def _settled(days: Iterable) -> list:
    """(forecast, actual) pairs with both numbers, oldest first, last
    ``WINDOW_DAYS`` only."""
    out = []
    for pair in days:
        try:
            forecast, actual = pair
            forecast = float(forecast)
            actual = float(actual)
        except (TypeError, ValueError):
            continue
        if forecast <= 0 or actual < 0:
            continue
        out.append((forecast, actual))
    return out[-WINDOW_DAYS:]


def _colour(ratio: float) -> str:
    for name, floor in THRESHOLDS:
        if ratio >= floor:
            return name
    return "red"


def pv_health(
    days: Iterable,
    downtime_min_today: float,
    freezing: Optional[bool],
    expect_w_now: float,
    solar_w_now: float,
    low_since_s: Optional[float],
) -> PvHealth:
    """The verdict. A low ratio with a full-yield day in the last
    ``RECENT_FULL_DAYS`` settled days is at most yellow.

    ``days``: (forecast_kwh, actual_kwh) per day, oldest first; a pair with
    a missing number is skipped. ``freezing``: None when there is no
    temperature source — then snow is never claimed. ``low_since_s``: how
    long the plant has delivered under ``SNOW_YIELD_SHARE`` of the forecast,
    None when it is not low now.
    """
    settled = _settled(days)
    n = len(settled)
    ratio = None
    state = None
    if n >= MIN_SETTLED_DAYS:
        total_forecast = sum(f for f, _ in settled)
        total_actual = sum(a for _, a in settled)
        ratio = round(total_actual / total_forecast, 3) if total_forecast > 0 else 0.0
        state = _colour(ratio)

    since_full: Optional[int] = None
    for back, (forecast, actual) in enumerate(reversed(settled)):
        if actual / forecast >= FULL_YIELD_RATIO:
            since_full = back
            break

    # (#1022) a plant that just delivered a full day is not broken
    if state in ("orange", "red") and since_full is not None and since_full <= RECENT_FULL_DAYS:
        state = "yellow"

    snow = bool(
        freezing is True
        and float(expect_w_now or 0.0) >= SNOW_EXPECT_W
        and float(solar_w_now or 0.0) < SNOW_YIELD_SHARE * float(expect_w_now or 0.0)
        and low_since_s is not None
        and float(low_since_s) >= SNOW_HOLD_S
    )

    return PvHealth(
        state=state,
        ratio_7d=ratio,
        settled_days=n,
        downtime_min_today=int(round(float(downtime_min_today or 0.0))),
        days_since_full_yield=since_full,
        snow=snow,
    )
