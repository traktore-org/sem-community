"""#638 day horizon — the day expressed as ledger slots.

One mind, no second engine (Guido: "even with dayplanner"): the DAY is
translated into the ``LedgerSlot`` shape the night packer already
understands, and ``build_night_ledger`` + ``pack_night`` run unchanged
over it. Two slot flavours:

* **surplus hours** — expected solar exceeds the expected home draw by
  more than the margin. The sun is free but finite: ``price 0``,
  ``level_cheap True``, ``cap_override_w = surplus`` (the slot's whole
  grant budget is the surplus power), ``home_w 0`` — the house runs on
  the same sun, so it must not also drain the ledger's battery walk.
* **deficit hours** — the house draws the difference. The slot prices at
  the SAME tariff provider the night packer reads (never a parallel price
  path — the second-channel sin), the NET home draw rides the normal
  battery-then-meter walk, and the grid cap derives from the peak limit
  exactly as at night.

The hourly solar curve is synthesized from the scalar day total with the
sine-shape model ``forecast_tracker`` already trusts (low mornings, noon
peak, integral == the day total) — the forecast integrations publish day
totals, not curves.

Pure: no clock reads, no I/O, no Home Assistant imports. Every world
input arrives as a value or a callable.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from .overnight_planner import LedgerSlot

# Below this computed surplus a "free window" is forecast noise, not a
# plannable window — mirrors the delta-guard instinct on the EV side.
DEFAULT_SURPLUS_MARGIN_W = 200.0


def _curve_fraction(t: datetime, sunrise: datetime, sunset: datetime) -> float:
    """Fraction of the day's solar produced by ``t`` — the sine integral
    (1 − cos(π·x/T))/2, the same shape ``forecast_tracker`` uses."""
    daylight_s = (sunset - sunrise).total_seconds()
    if daylight_s <= 0:
        return 0.0
    x = (t - sunrise).total_seconds()
    if x <= 0:
        return 0.0
    if x >= daylight_s:
        return 1.0
    return (1 - math.cos(math.pi * x / daylight_s)) / 2


def expected_solar_kwh_between(t0: datetime, t1: datetime, *, day_kwh: float,
                               sunrise: datetime, sunset: datetime) -> float:
    """Expected solar energy in ``[t0, t1)`` from the day total and the
    sine shape. Zero outside daylight, integral over the whole day equals
    ``day_kwh``."""
    if day_kwh <= 0 or t1 <= t0:
        return 0.0
    return day_kwh * (_curve_fraction(t1, sunrise, sunset)
                      - _curve_fraction(t0, sunrise, sunset))


def build_day_slots(*, start: datetime, end: datetime, day_kwh: float,
                    sunrise: datetime, sunset: datetime,
                    home_w_at, price_at, level_cheap_at,
                    surplus_margin_w: float = DEFAULT_SURPLUS_MARGIN_W,
                    step_s: int = 3600) -> list:
    """Tile ``[start, end)`` into day-shaped ``LedgerSlot``s.

    ``home_w_at(t)`` — expected home draw (the predictor's hourly profile
    with the flat fallback, same as the night collector). ``price_at(t)``
    / ``level_cheap_at(t)`` — the SAME tariff accessors the night slots
    are built from; a raising provider degrades to an honestly unpriced
    slot, exactly like the night path.
    """
    slots = []
    t = start
    while t < end:
        slot_end = min(t + timedelta(seconds=step_s), end)
        hours = (slot_end - t).total_seconds() / 3600.0
        if hours <= 0:
            break
        solar_w = (expected_solar_kwh_between(
            t, slot_end, day_kwh=day_kwh, sunrise=sunrise, sunset=sunset)
            * 1000.0 / hours)
        try:
            home_w = max(0.0, float(home_w_at(t)))
        except Exception:  # noqa: BLE001 — a broken profile is a flat 0
            home_w = 0.0
        surplus_w = solar_w - home_w
        if surplus_w >= surplus_margin_w:
            slots.append(LedgerSlot(
                start=t, end=slot_end,
                price=0.0, level_cheap=True, home_w=0.0,
                cap_override_w=surplus_w,
            ))
        else:
            price = None
            try:
                p = price_at(t)
                price = float(p) if p is not None else None
            except Exception:  # noqa: BLE001 — unpriced, honestly
                price = None
            try:
                cheap = bool(level_cheap_at(t))
            except Exception:  # noqa: BLE001 — no level is not cheap
                cheap = False
            slots.append(LedgerSlot(
                start=t, end=slot_end,
                price=price, level_cheap=cheap,
                home_w=max(0.0, home_w - solar_w),
            ))
        t = slot_end
    return slots
