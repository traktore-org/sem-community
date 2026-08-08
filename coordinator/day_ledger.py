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


def _merge_windows(slots) -> list:
    """Adjacent qualifying slots become one window — the card draws bands,
    not slivers."""
    out = []
    for s in sorted(slots, key=lambda s: s.start):
        if out and out[-1]["end"] == s.start.isoformat():
            out[-1]["end"] = s.end.isoformat()
        else:
            out.append({"start": s.start.isoformat(),
                        "end": s.end.isoformat()})
    return out


def tomorrow_preview(*, day_start, day_end, day_kwh, sunrise, sunset,
                     home_w_at, price_at, level_cheap_at, stamps_at) -> dict:
    """(#638 consolidation / #722) The NEXT energy day's books, previewed.

    tintinz's Today|Tomorrow idea (#722), adopted onto the one data path:
    the preview is built by the SAME slot machinery and the SAME tariff
    accessors as the plan itself, anchored to the target day — which is
    what makes it time-invariant (the #722 review's open MEDIUM was a
    tomorrow view composed from today-anchored values, whose rows
    changed with the hour you looked at it).

    ``prices``: ``final`` when the provider prices tomorrow midday,
    ``preliminary`` while the day-ahead is unpublished — a static/ToU
    schedule is always known, so it always reads final. No demands, no
    verdicts: the plan for that day honestly does not exist until it
    stamps at ``stamps_at``.
    """
    slots = build_day_slots(
        start=day_start, end=day_end, day_kwh=day_kwh,
        sunrise=sunrise, sunset=sunset, home_w_at=home_w_at,
        price_at=price_at, level_cheap_at=level_cheap_at,
    )
    probe = day_start + (day_end - day_start) / 2
    try:
        p = price_at(probe)
    except Exception:  # noqa: BLE001 — unpriced, honestly
        p = None
    return {
        "forecast_kwh": round(float(day_kwh), 1),
        "prices": "final" if p is not None else "preliminary",
        "surplus_windows": _merge_windows(
            [s for s in slots if s.cap_override_w is not None]),
        "cheap_windows": _merge_windows(
            [s for s in slots
             if s.cap_override_w is None and s.level_cheap]),
        "night_open": day_end.isoformat(),
        "stamps_at": stamps_at.isoformat(),
    }


def tariff_price_at(prov, ts):
    """The ONE price accessor every planner surface reads (#638) — night
    slots, day slots, the tomorrow preview. None = honestly unpriced.
    Pure duck-typing over the provider so fakes and all three provider
    kinds answer alike; a second copy of this logic is how a parallel
    price path starts — add consumers, not copies."""
    if hasattr(prov, "get_price_at"):
        try:
            p = prov.get_price_at(ts)
            return float(p) if p is not None else None
        except Exception:  # noqa: BLE001 — unpriced, honestly
            return None
    return None


def tariff_cheap_at(prov, ts):
    """The ONE cheap-level accessor (#638) — the same gate execution's
    cheap-hours loads fire on."""
    if hasattr(prov, "get_price_level_at"):
        try:
            lvl = prov.get_price_level_at(ts)
        except Exception:  # noqa: BLE001 — no level is not cheap
            return False
        name = str(getattr(lvl, "value", lvl) or "").lower()
        return name in ("cheap", "very_cheap", "negative")
    return False


def provisional_soc_curve(ledger, *, capacity_kwh: float,
                          max_charge_w: float) -> list:
    """(Guido, 08-08: "we can also predict the battery level") — the
    battery's likely path through a walked day ledger.

    The trajectory walk models the DISCHARGE side (home draws battery to
    the floor); through a surplus day the leftover sun CHARGES it. The
    curve is the walk's per-slot soc plus cumulative leftover-surplus
    charging — leftover meaning the slot's surplus budget minus what the
    pack already granted to devices (``grid_committed_w``) — bounded by
    the charge power cap and the pack's capacity. An approximation by
    design (charging feeds back into later coverage only via the base
    walk), published under a preview that says *provisional* out loud.
    """
    if capacity_kwh <= 0 or not ledger:
        return []
    pts = []
    charged = 0.0
    for s in ledger:
        soc = min(capacity_kwh, s.soc_kwh + charged)
        pts.append({"t": s.start.isoformat(), "kwh": round(soc, 2)})
        leftover_w = 0.0
        if s.cap_override_w is not None:
            leftover_w = max(0.0, s.cap_override_w - s.grid_committed_w)
        room = max(0.0, capacity_kwh - soc)
        charged += min(min(leftover_w, max_charge_w) * s.hours / 1000.0,
                       room)
    last = ledger[-1]
    end = min(capacity_kwh,
              max(0.0, last.soc_kwh - last.home_batt_kwh) + charged)
    pts.append({"t": last.end.isoformat(), "kwh": round(end, 2)})
    return pts
