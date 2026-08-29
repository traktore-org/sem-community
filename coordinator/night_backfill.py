"""(#815) Recover the battery's night history from statistics already on disk.

#778's need envelope wants five trainable nights before it offers a figure.
Live recording produces one per day, so a fresh install waits a working week
to learn something its own database can usually already prove — the same waste
of the user's time that ``ledger_backfill`` removed for the forecast half.

**A backfilled night is not merely faster, it is sounder.** Live recording
integrates battery POWER over time, so a dropped sample destroys that energy
permanently — the failure mode behind #837. A cumulative energy counter is a
different kind of measurement: the inverter keeps counting while nobody is
looking, so a night's discharge is ``counter(dawn) - counter(dusk)`` and
missing hours in between change nothing at all. The gap problem cannot exist
here, which is why this reaches back further AND lands cleaner.

**What it cannot know, stated on the record.** The counter reports the pack's
TOTAL discharge; ``drain_kwh`` means the part that reached the house. Total
also carries EV assist and battery export, and statistics cannot separate
them, so a backfilled drain is an UPPER BOUND. That is the safe direction and
chosen deliberately: a larger drain means a larger reserve and less spending,
and of the two ways to be wrong that is the one that cannot strand anyone —
the same reasoning ``battery_night._bridge_hole`` already uses. Every record
carries ``source: "backfill"`` so a reader can be stricter.

Pure: series in, records out. The recorder query and the store write live at
the service seam, so every rule here is testable without a database.
"""

from __future__ import annotations

import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Set

#: A night must be bounded by a reading at each end. Statistics are hourly, so
#: allow the endpoint to be found within this many hours of the boundary — a
#: provider that missed the 21:00 row but has 22:00 still describes the night.
ENDPOINT_TOLERANCE_H: int = 2

#: A single night cannot discharge more than this multiple of the pack. Above
#: it the delta is a counter reset, a unit swap, or a units mix-up, never a
#: night. Deliberately generous: two full cycles is implausible but not
#: impossible, three is not a night.
MAX_NIGHT_CYCLES: float = 2.0

#: SOC at or below ``reserve + this`` counts as having hit the floor. Mirrors
#: ``battery_night.RESERVE_EPS`` — one number, two readers, same meaning.
RESERVE_EPS: float = 1.0


def _window(day: datetime.date, start_h: int, end_h: int):
    """The night that STARTS on ``day``.

    The live recorder keys a night by the date it opened
    (``tr.start(str(opened_at.date()))``), so an evening-to-morning night
    belongs to its evening. Matching that exactly is what lets backfilled and
    live records share one list without a reader having to know which is which.
    """
    start = datetime.datetime.combine(day, datetime.time(hour=start_h))
    end_day = day + datetime.timedelta(days=1) if end_h <= start_h else day
    end = datetime.datetime.combine(end_day, datetime.time(hour=end_h))
    return start, end


def _nearest(series: Mapping[datetime.datetime, float],
             target: datetime.datetime, tolerance_h: int):
    """The reading closest to ``target`` within tolerance, or ``None``."""
    best = None
    for hours in range(tolerance_h + 1):
        for delta in ((0,) if hours == 0 else (hours, -hours)):
            value = series.get(target + datetime.timedelta(hours=delta))
            if value is not None:
                return value, target + datetime.timedelta(hours=delta)
    return best


def _decreased_within(series: Mapping[datetime.datetime, float],
                      start: datetime.datetime, end: datetime.datetime) -> bool:
    """Did the counter ever go backwards inside the window?

    A cumulative counter that decreases has been reset, replaced or swapped for
    a differently-scaled one. The endpoint delta is then a fiction — and a
    plausible-looking one — so the night is refused rather than booked.
    """
    inside = sorted((t, v) for t, v in series.items() if start <= t <= end)
    return any(b[1] < a[1] - 1e-9 for a, b in zip(inside, inside[1:], strict=False))


def nights_from_statistics(
    discharge: Optional[Mapping[datetime.datetime, float]],
    soc: Optional[Mapping[datetime.datetime, float]] = None,
    *,
    night_start_hour: int,
    night_end_hour: int,
    reserve_soc: Optional[float] = None,
    capacity_kwh: Optional[float] = None,
    known_dates: Optional[Set[str]] = None,
) -> List[Dict]:
    """Reconstruct sealed-night records from a cumulative discharge counter.

    ``known_dates`` are nights SEM already recorded live; they are skipped
    entirely. Live measurement separates house drain from EV assist and export
    and this cannot, so a live record is always the better one — the backfill
    fills gaps, it never overwrites evidence.
    """
    if not discharge:
        return []

    known = known_dates or set()
    days = sorted({t.date() for t in discharge})
    out: List[Dict] = []

    for day in days:
        key = str(day)
        if key in known:
            continue
        start, end = _window(day, night_start_hour, night_end_hour)

        first = _nearest(discharge, start, ENDPOINT_TOLERANCE_H)
        last = _nearest(discharge, end, ENDPOINT_TOLERANCE_H)
        if first is None or last is None:
            continue                       # no endpoints, no night

        drain = last[0] - first[0]
        trainable = True
        if drain < 0 or _decreased_within(discharge, first[1], last[1]):
            trainable = False              # counter reset — the delta is fiction
            drain = max(0.0, drain)
        if capacity_kwh and drain > float(capacity_kwh) * MAX_NIGHT_CYCLES:
            trainable = False

        reserve_hit = False
        if soc and reserve_soc is not None:
            lows = [v for t, v in soc.items() if first[1] <= t <= last[1]]
            if lows:
                reserve_hit = min(lows) <= float(reserve_soc) + RESERVE_EPS

        out.append({
            "date": key,
            "drain_kwh": round(drain, 3),
            "trainable": trainable,
            "reserve_hit": reserve_hit,
            # Provenance, so a stricter reader can tell this from live
            # evidence — and so "why does it already know?" has an answer.
            "source": "backfill",
        })
    return out


def merge_nights(existing: Optional[Iterable[Dict]],
                 recovered: Iterable[Dict],
                 *, max_nights: int) -> List[Dict]:
    """Live records first, recovered ones filling the gaps, newest kept.

    Sorted by date so the window ``max_nights`` prunes to is the most recent
    history rather than whatever order the two sources happened to arrive in.
    """
    live = [r for r in (existing or []) if isinstance(r, dict)]
    have = {r.get("date") for r in live if r.get("date")}
    merged = live + [r for r in recovered if r.get("date") not in have]
    merged.sort(key=lambda r: str(r.get("date") or ""))
    return merged[-int(max_nights):] if max_nights else merged


async def run_backfill(hass, tracker, config, *, days: int = 365) -> dict:
    """Fill ``tracker``'s sealed nights from this install's own history.

    The seam: everything that needs a database or a config lives here, so the
    rules above stay testable without either.

    Reads the battery's cumulative DISCHARGE counter — the same statistic the
    Energy Dashboard is built on — plus SOC for the reserve flag. Both survive
    the recorder's purge and SEM's own status retention, which act on state
    rows, so this reaches history the ``history`` API has long dropped.
    """
    from .ledger_backfill import clamp_lookback_days, read_statistics

    # The bound services.yaml declares (14-730), enforced where it is USED: a
    # selector is only a UI hint, and a script or the Developer Tools YAML
    # editor reaches this with any number at all.
    days = clamp_lookback_days(days)

    discharge_id = (config.get("battery_discharge_energy_sensor")
                    or config.get("battery_energy_discharged_sensor"))
    if not discharge_id:
        return {"error": "no battery discharge energy sensor configured",
                "added": 0}

    soc_id = config.get("battery_soc_sensor")
    wanted = [discharge_id] + ([soc_id] if soc_id else [])
    series = await read_statistics(hass, wanted, days)

    discharge = series.get(discharge_id) or {}
    if not discharge:
        return {"error": f"no statistics for {discharge_id}", "added": 0}

    existing = list(tracker.sealed())
    recovered = nights_from_statistics(
        discharge,
        series.get(soc_id) if soc_id else None,
        night_start_hour=int(config.get("night_start_hour", 21) or 21),
        night_end_hour=int(config.get("night_end_hour", 6) or 6),
        reserve_soc=config.get("battery_reserve_soc"),
        capacity_kwh=config.get("battery_capacity_kwh"),
        known_dates={r.get("date") for r in existing if r.get("date")},
    )
    merged = merge_nights(existing, recovered,
                          max_nights=getattr(tracker, "max_nights", 60))
    tracker.replace_sealed(merged)

    usable = sum(1 for r in merged if r.get("trainable"))
    return {
        "statistic": discharge_id,
        "days_of_history": len(discharge),
        "recovered": len(recovered),
        "trainable_recovered": sum(1 for r in recovered if r.get("trainable")),
        "nights_total": len(merged),
        "usable_total": usable,
        "added": len(merged) - len(existing),
    }
