"""(#1083) Replay one recorded day through SEM's REAL code.

What runs is production code, unchanged, imported from the tree under
test; only its INPUTS come from the recorded day and its CLOCK is the
day's own (never the wall clock — bug class 133):

* **shown home** — ``SEMCoordinator._hold_shown_home``: every 10-s cycle
  the recorded solar / grid / battery / EV readings (a dark reading is 0 W
  with its dark flag set, exactly as the reader hands it on, #818) go
  through ``PowerReadings.calculate_derived`` and the hold. The figure the
  user would have SEEN comes out (#1047, #1105).
* **the plan's rest-of-day solar** — the real ``ForecastTracker``:
  ``update(forecast, actual)`` every 5 minutes with the day's recorded
  morning forecast and recorded running yield, then
  ``corrected_remaining_kwh(recorded raw remainder)`` — the number the
  plan books (#1068, #1104).

Honest limits (``docs/KNOWN_LIMITATIONS.md``): the recorded readings are
what SEM SAW, so a decision the branch makes differently does not move
them. This engine replays what a branch COMPUTES from real inputs; it does
not model how a different decision would have changed the house. The
sunrise/sunset come from the day's own first and last real sun (above
50 W), not from ``sun.sun`` (the corpus holds no location).

One day in memory at a time; nothing writes: the coordinator is built
without Home Assistant, and any service call is caught and counted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from .recorded_day import RecordedDay

#: forecast tracker cadence (the plan reads it every cycle; 5 min is
#: enough for its smoothing and keeps a day under a second)
FORECAST_STEP_S = 300


@dataclass
class DayRun:
    """What the branch computed over one recorded day."""

    date: str
    tags: List[str]
    #: (epoch_s, shown home W, recorded home W, any input dark)
    home: List[Tuple[float, float, Optional[float], bool]] = field(default_factory=list)
    #: (epoch_s, local hour, raw remaining kWh, corrected remaining kWh)
    forecast: List[Tuple[float, float, float, float]] = field(default_factory=list)
    #: service calls the replayed code tried to make (must stay 0)
    writes: int = 0
    notes: List[str] = field(default_factory=list)


def _daylight(day: RecordedDay) -> Optional[Tuple[float, float]]:
    lit = [day.local_hour(t) for t, v in day.series.get("solar_power", [])
           if v is not None and v > 50.0]
    return (min(lit), max(lit)) if lit else None


def _coordinator():
    """A coordinator with no Home Assistant behind it — the shown-home path
    needs only its own state. ``hass.services.async_call`` is a counter."""
    from custom_components.solar_energy_management.coordinator import SEMCoordinator
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.config = {}
    return coord


def _readings(c):
    """PowerReadings from one cycle, the way the reader hands them on: a
    dark input reads 0 W and carries its dark flag (#818, #925)."""
    from custom_components.solar_energy_management.coordinator.types import PowerReadings
    pr = PowerReadings(
        solar_power=float(c.get("solar_power", 0.0) or 0.0),
        grid_power=float(c.get("grid_power", 0.0) or 0.0),
        battery_power=float(c.get("battery_power", 0.0) or 0.0),
        ev_power=float(c.get("ev_power", 0.0) or 0.0),
        battery_soc=float(c.get("battery_soc", 50.0) or 50.0),
        solar_power_unavailable=c.dark("solar_power"),
        grid_power_unavailable=c.dark("grid_power"),
        battery_power_all_unavailable=c.dark("battery_power"),
    )
    pr.calculate_derived()
    return pr


def replay_home(day: RecordedDay, run: DayRun,
                window: Optional[Tuple[float, float]] = None) -> None:
    coord = _coordinator()
    clock = {"t": 0.0}
    coord._shown_home_clock = lambda: clock["t"]
    lo, hi = window or day.bounds()
    have = {r for r in ("solar_power", "grid_power", "battery_power") if day.series.get(r)}
    for c in day.cycles(lo, hi):
        if not any(c.values.get(r) is not None for r in have):
            continue                      # before the first reading of the day
        clock["t"] = c.t
        pr = _readings(c)
        coord._hold_shown_home(pr)
        shown = pr.home_shown_w if getattr(pr, "home_shown_w", None) is not None \
            else pr.home_consumption_power
        dark = any(c.dark(r) for r in have)
        run.home.append((c.t, float(shown or 0.0), c.values.get("home_power"), dark))
    run.writes += coord.hass.services.async_call.await_count


def replay_forecast(day: RecordedDay, run: DayRun) -> None:
    from custom_components.solar_energy_management.coordinator import forecast_tracker as ft
    sun = _daylight(day)
    if sun is None:
        run.notes.append("forecast: no sun recorded — skipped")
        return
    fc = sorted(v for t, v in day.series.get("forecast_today_kwh", [])
                if v and 5.0 <= day.local_hour(t) < 10.0)
    if not fc:
        run.notes.append("forecast: no morning forecast recorded — skipped")
        return
    forecast = fc[len(fc) // 2]
    tracker = ft.ForecastTracker()
    tracker._get_sun_hours = lambda: sun
    zi = ZoneInfo(day.tz)
    for c in day.cycles(cycle_s=FORECAST_STEP_S):
        h = day.local_hour(c.t)
        if h < 0.5:
            continue                      # yesterday's total still showing
        actual = c.get("daily_solar_kwh")
        raw = c.get("forecast_remaining_kwh")
        if actual is None or raw is None:
            continue
        now = datetime.fromtimestamp(c.t, zi).replace(tzinfo=None)
        with patch.object(ft.dt_util, "now", return_value=now):
            tracker.update(forecast, actual)
            corrected = tracker.corrected_remaining_kwh(raw)
        run.forecast.append((c.t, h, float(raw), float(corrected)))


def replay_day(day: RecordedDay, *, home_window: Optional[Tuple[float, float]] = None) -> DayRun:
    """Every replayed path over one day."""
    run = DayRun(date=day.date, tags=list((day.tags or {}).get("tags") or []))
    replay_home(day, run, home_window)
    replay_forecast(day, run)
    return run
