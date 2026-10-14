"""(#1083) Tag a day by its sky, the car, its prices and its data gaps.

Pure: no Home Assistant, no clock. The nightly job
(``coordinator/day_tag_store.py``) and the replay tool
(``tools/replay``) both feed it what one day recorded and get one
``DayTags`` back. The tags let a replay pick "every sunny day of the last
60" or "a grey day with a car", and let it skip a day whose data cannot be
trusted (a gap) instead of failing a branch on it.

Rules (each one plain, each one pinned by a test from a real day):

* **sky** — ``sunny`` when the day made at least ``FULL_YIELD_RATIO`` (the
  same 0.90 PV health uses for a full-yield day) of a clear-sky day AND the
  midday solar was steady (variability of the 5-minute readings 10:00–15:00
  under ``SUNNY_MAX_VARIABILITY``); ``grey`` when it made under
  ``GREY_MAX_SHARE`` of its forecast; else ``mixed``. The clear-sky day is
  the plant's best day of the last 30 — what this roof really makes under a
  clear sky in this season, not a guess about panels and angles.
* **sky from hourly statistics** (the backfill, days older than the
  recorder keeps) — an hour hides a passing cloud, so steadiness is read
  from the shape of the hourly curve instead: ``sunny`` when the day made
  at least ``HOURLY_SUNNY_SHARE`` of its clear-sky envelope (the best day
  within ``ENVELOPE_HALF_WIDTH`` days of it, see ``clear_sky_envelope``),
  the curve has no dip (``hourly_smooth``) and the forecast rule does not
  call it grey; ``grey`` under ``GREY_MAX_SHARE`` of the envelope or of its
  forecast; else ``mixed``.
* **snow** — PV health's own snow flag for the day, passed in, never
  recomputed here (one rule, one place).
* **car** — at least one finished charging session that day.
* **prices** — ``negative`` if any slot was below 0, ``cheap`` if the
  day's cheapest slot reached the cheap threshold. Nothing on a flat
  tariff: a flat tariff has no comparison to make (#994).
* **gap** — any source reading dark for more than ``GAP_DARK_MIN`` minutes
  in daylight, a restart, or a frozen counter: the lifetime solar counter
  flat all day while the forecast promised more than ``FROZEN_MIN_KWH``
  (PROD 12.10.2026: the Huawei counter sat at 23 832.86 kWh all day).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from .pv_health import FULL_YIELD_RATIO

#: midday steadiness: std ÷ mean of the 5-minute solar readings 10:00–15:00
SUNNY_MAX_VARIABILITY = 0.15
#: a day that made under this share of its forecast is grey
GREY_MAX_SHARE = 0.35
#: a source dark for longer than this in daylight makes the day a gap day
GAP_DARK_MIN = 15.0
#: a counter flat all day is frozen only if the forecast promised this much
FROZEN_MIN_KWH = 2.0
#: midday window for the steadiness check (local hours)
MIDDAY = (10.0, 15.0)
#: hourly sunny: share of the envelope — a bit under FULL_YIELD_RATIO
#: because the envelope is the BEST day of a month, not a typical clear one
HOURLY_SUNNY_SHARE = 0.85
#: envelope: days either side whose best yield stands for a clear sky —
#: a month is short enough that the sun's height barely moves
ENVELOPE_HALF_WIDTH = 15
#: hourly curve: hours below this share of the peak hour are dawn or dusk
HOURLY_LIT_SHARE = 0.10
#: hourly curve: an hour under this share of its neighbours' mean is a dip
#: (a cloud bank that stayed most of an hour)
HOURLY_DIP_SHARE = 0.6

SKY_SUNNY = "sunny"
SKY_MIXED = "mixed"
SKY_GREY = "grey"


@dataclass
class DayTags:
    """One day's tags. ``tags`` is the flat set a replay selects on."""

    date: str
    sky: Optional[str] = None             # sunny / mixed / grey / None
    snow: bool = False
    car: bool = False
    car_kwh: float = 0.0
    prices: Optional[str] = None          # negative / cheap / None
    gap: bool = False
    gap_why: List[str] = field(default_factory=list)
    actual_kwh: Optional[float] = None
    forecast_kwh: Optional[float] = None
    variability: Optional[float] = None

    @property
    def tags(self) -> List[str]:
        out = [t for t in (self.sky, self.prices) if t]
        if self.snow:
            out.append("snow")
        if self.car:
            out.append("car")
        if self.gap:
            out.append("gap")
        return out

    def as_dict(self) -> dict:
        return {
            "date": self.date, "tags": self.tags, "sky": self.sky,
            "snow": self.snow, "car": self.car,
            "car_kwh": round(self.car_kwh, 2), "prices": self.prices,
            "gap": self.gap, "gap_why": list(self.gap_why),
            "actual_kwh": None if self.actual_kwh is None else round(self.actual_kwh, 2),
            "forecast_kwh": None if self.forecast_kwh is None else round(self.forecast_kwh, 2),
            "variability": None if self.variability is None else round(self.variability, 3),
        }


def midday_variability(solar: Sequence[Tuple[float, Optional[float]]]) -> Optional[float]:
    """std ÷ mean of the readings inside ``MIDDAY``. ``solar`` is
    ``(local_hour, watts)``; a dark reading (``None``) is left out, not
    counted as 0 W. ``None`` when there is nothing to judge."""
    vals = [float(w) for h, w in solar
            if w is not None and MIDDAY[0] <= float(h) < MIDDAY[1]]
    if len(vals) < 6:
        return None
    mean = sum(vals) / len(vals)
    if mean <= 50.0:          # a dark midday is not "steady"
        return None
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return math.sqrt(var) / mean


def tag_sky(actual_kwh: Optional[float], forecast_kwh: Optional[float],
            clear_sky_kwh: Optional[float],
            variability: Optional[float],
            hourly: bool = False) -> Optional[str]:
    """sunny / mixed / grey — or ``None`` when the day cannot be judged.

    ``hourly``: the day comes from hourly statistics (the backfill). An hour
    hides a passing cloud, so steadiness cannot be shown and the day is
    never "sunny" — at best "mixed"."""
    if actual_kwh is None:
        return None
    if (not hourly and clear_sky_kwh and clear_sky_kwh > 0
            and actual_kwh >= FULL_YIELD_RATIO * clear_sky_kwh
            and variability is not None
            and variability < SUNNY_MAX_VARIABILITY):
        return SKY_SUNNY
    if forecast_kwh and forecast_kwh > 0 and actual_kwh < GREY_MAX_SHARE * forecast_kwh:
        return SKY_GREY
    if not forecast_kwh and not clear_sky_kwh:
        return None
    return SKY_MIXED


def clear_sky_envelope(yields: Mapping[str, float], day: str,
                       half_width: int = ENVELOPE_HALF_WIDTH) -> Optional[float]:
    """The best daily yield among the days of ``yields`` (ISO date -> kWh)
    within ``half_width`` days of ``day``; the day itself counts. Only the
    days passed in count — the caller decides the window. ``None`` when
    no day is there."""
    try:
        d0 = _date.fromisoformat(str(day))
    except ValueError:
        return None
    near = []
    for iso, kwh in yields.items():
        try:
            gap = abs((_date.fromisoformat(str(iso)) - d0).days)
        except ValueError:
            continue
        if gap <= half_width and kwh is not None:
            near.append(float(kwh))
    return max(near) if near else None


def hourly_smooth(hours: Mapping[int, Optional[float]]) -> bool:
    """Is the hourly solar curve free of dips? Between the first and the
    last hour with ``HOURLY_LIT_SHARE`` of the peak hour, every hour must
    reach ``HOURLY_DIP_SHARE`` of the mean of its two neighbours. A missing
    hour counts as 0: a dark hour cannot prove a clear sky."""
    vals = {int(h): float(v) for h, v in hours.items() if v is not None}
    peak = max(vals.values(), default=0.0)
    if peak <= 0:
        return False
    lit = [h for h, v in vals.items() if v >= HOURLY_LIT_SHARE * peak]
    for h in range(min(lit) + 1, max(lit)):
        mean = (vals.get(h - 1, 0.0) + vals.get(h + 1, 0.0)) / 2.0
        if vals.get(h, 0.0) < HOURLY_DIP_SHARE * mean:
            return False
    return True


def tag_sky_hourly(yield_kwh: Optional[float], envelope_kwh: Optional[float],
                   hours: Mapping[int, Optional[float]],
                   actual_kwh: Optional[float],
                   forecast_kwh: Optional[float]) -> Optional[str]:
    """sunny / mixed / grey for a day known only from hourly statistics.

    ``yield_kwh`` is the sum of ``hours``; ``actual_kwh`` and
    ``forecast_kwh`` feed the forecast rule exactly as ``tag_sky`` uses it.
    Without an envelope this falls back to ``tag_sky(hourly=True)``."""
    if yield_kwh is None:
        return None
    forecast_grey = bool(
        forecast_kwh and forecast_kwh > 0 and actual_kwh is not None
        and actual_kwh < GREY_MAX_SHARE * forecast_kwh)
    if not envelope_kwh or envelope_kwh <= 0:
        return tag_sky(actual_kwh if actual_kwh is not None else yield_kwh,
                       forecast_kwh, None, None, hourly=True)
    if (yield_kwh >= HOURLY_SUNNY_SHARE * envelope_kwh
            and hourly_smooth(hours) and not forecast_grey):
        return SKY_SUNNY
    if yield_kwh < GREY_MAX_SHARE * envelope_kwh or forecast_grey:
        return SKY_GREY
    return SKY_MIXED


def tag_prices(prices: Optional[Iterable[Optional[float]]],
               cheap_threshold: Optional[float]) -> Optional[str]:
    """negative / cheap / None. Flat or missing prices say nothing (#994)."""
    vals = [float(p) for p in (prices or []) if p is not None]
    if not vals or max(vals) - min(vals) < 1e-4:
        return None
    if min(vals) < 0:
        return "negative"
    if cheap_threshold is not None and min(vals) <= float(cheap_threshold):
        return "cheap"
    return None


def tag_gap(*, dark_daylight_min: float = 0.0, restarted: bool = False,
            counter_flat: bool = False,
            forecast_kwh: Optional[float] = None) -> List[str]:
    """Why the day's data cannot be trusted; empty when it can."""
    why = []
    if float(dark_daylight_min or 0.0) > GAP_DARK_MIN:
        why.append(f"a reading dark {int(round(dark_daylight_min))} min in daylight")
    if restarted:
        why.append("a restart")
    if counter_flat and (forecast_kwh or 0.0) > FROZEN_MIN_KWH:
        why.append("the solar counter did not move")
    return why


def tag_day(*, date: str,
            solar: Sequence[Tuple[float, Optional[float]]] = (),
            actual_kwh: Optional[float] = None,
            forecast_kwh: Optional[float] = None,
            clear_sky_kwh: Optional[float] = None,
            snow: bool = False,
            session_kwh: Iterable[float] = (),
            prices: Optional[Iterable[Optional[float]]] = None,
            cheap_threshold: Optional[float] = None,
            dark_daylight_min: float = 0.0,
            restarted: bool = False,
            counter_flat: bool = False,
            hourly: bool = False,
            envelope_kwh: Optional[float] = None) -> DayTags:
    """All tags for one day. Every input is optional: a missing input
    leaves its tag out rather than inventing one. ``hourly``: ``solar`` is
    one reading per hour (watts = the hour's Wh) and the sky comes from
    ``tag_sky_hourly`` against ``envelope_kwh``."""
    var = None if hourly else midday_variability(solar)
    if hourly:
        hours = {int(h): (None if w is None else float(w) / 1000.0)
                 for h, w in solar}
        lit = [v for v in hours.values() if v is not None]
        sky = tag_sky_hourly(sum(lit) if lit else None, envelope_kwh, hours,
                             actual_kwh, forecast_kwh)
    else:
        sky = tag_sky(actual_kwh, forecast_kwh, clear_sky_kwh, var)
    sessions = [float(k) for k in session_kwh if k and float(k) > 0]
    why = tag_gap(dark_daylight_min=dark_daylight_min, restarted=restarted,
                  counter_flat=counter_flat, forecast_kwh=forecast_kwh)
    return DayTags(
        date=str(date),
        sky=sky,
        snow=bool(snow),
        car=bool(sessions),
        car_kwh=sum(sessions),
        prices=tag_prices(prices, cheap_threshold),
        gap=bool(why),
        gap_why=why,
        actual_kwh=actual_kwh,
        forecast_kwh=forecast_kwh,
        variability=var,
    )
