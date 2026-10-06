"""(#1023) When a charger's car leaves: one answer for every reader.

The charge-by time was read in seven places, and for a charger WITHOUT a time
of its own they did not agree. The card, the night plan and the EV-day
boundary fell back to the global time (the primary charger's, mirrored there
by #255) or 07:00. The energy plan's demand and the night-deliverable window
fell back to the end of the night window instead, so a car the card said was
due at 07:00 was planned to 09:00 on a night window ending then. The plan's
change signature saw an empty string.

Every reader now asks here. ``departure_hhmm`` is the charger's own time of
day — the default its weekdays fall back to, and the boundary its EV day
rolls at. ``departure_for`` is the next departure after now, weekday
included (A1): a charger may leave at a different time on each day of the
week (``ev_departure_by_weekday``, ``mon`` … ``sun`` → ``HH:MM`` or empty),
and a day left empty leaves at the default.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional

from ..consts.core import DEFAULT_EV_TARGET_TIME
from .ev_tariff_planner import resolve_deadline

#: ``datetime.weekday()`` order.
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_KEY = "ev_departure_by_weekday"


def _hm(value: Any) -> Optional[tuple]:
    """``(hour, minute)`` of an ``HH:MM`` that names a time of day, else
    None. What the ``Charge by`` entity writes; "25:00" is no time."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parts = str(value).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def departure_hhmm(charger_cfg: Optional[Mapping[str, Any]],
                   config: Optional[Mapping[str, Any]]) -> str:
    """The charger's departure time of day: its own ``ev_target_time``, else
    the global one, else 07:00. A blank or unreadable value is not a time and
    passes to the next."""
    for source in (charger_cfg or {}, config or {}):
        value = source.get("ev_target_time")
        if _hm(value) is not None:
            return str(value)
    return DEFAULT_EV_TARGET_TIME


def weekday_departures(charger_cfg: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """The days that leave at a time of their own, ``{"mon": "06:15"}``.
    Empty, unreadable or unknown entries are left out — those days leave at
    the default."""
    raw = (charger_cfg or {}).get(WEEKDAY_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {day: str(raw[day]) for day in WEEKDAYS
            if day in raw and _hm(raw[day]) is not None}


def departure_signature(charger_cfg: Optional[Mapping[str, Any]],
                        config: Optional[Mapping[str, Any]]) -> tuple:
    """What the departure is configured to: changes when the user edits a
    time, not as the clock passes one."""
    return (departure_hhmm(charger_cfg, config),
            tuple(sorted(weekday_departures(charger_cfg).items())))


def departure_for(charger_cfg: Optional[Mapping[str, Any]], now: datetime,
                  config: Optional[Mapping[str, Any]]) -> datetime:
    """The charger's next departure after ``now``: today's, if it is still
    ahead, else tomorrow's — each day at its weekday's time, or the default.
    So a night plan made on Sunday evening plans for Monday morning.

    Wall-clock arithmetic on a zone-aware ``now``, like ``resolve_deadline``
    (#274/M2): the departure gets the offset of its own wall time across a
    DST change."""
    default = departure_hhmm(charger_cfg, config)
    by_day = weekday_departures(charger_cfg)
    for offset in (0, 1):
        day = now + timedelta(days=offset)
        h, m = _hm(by_day.get(WEEKDAYS[day.weekday()], default))
        candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate > now:
            return candidate
    # Tomorrow's departure is always after now; kept for the type checker.
    return resolve_deadline(now, default)
