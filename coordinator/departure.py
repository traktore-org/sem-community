"""(#1023) When a charger's car leaves: one answer for every reader.

The charge-by time was read in seven places, and for a charger WITHOUT a time
of its own they did not agree. The card, the night plan and the EV-day
boundary fell back to the global time (the primary charger's, mirrored there
by #255) or 07:00. The energy plan's demand and the night-deliverable window
fell back to the end of the night window instead, so a car the card said was
due at 07:00 was planned to 09:00 on a night window ending then. The plan's
change signature saw an empty string.

Every reader now asks here. ``departure_hhmm`` is the time of day,
``departure_for`` the next such moment after now — the one a night plan
started at 22:00 means.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from ..consts.core import DEFAULT_EV_TARGET_TIME
from .ev_tariff_planner import resolve_deadline


def _usable(value: Any) -> bool:
    """An ``HH:MM`` that resolves: what the ``Charge by`` entity writes."""
    try:
        return resolve_deadline(datetime(2000, 1, 1), value) is not None
    except ValueError:  # "25:00" splits, and then is no hour of a day
        return False


def departure_hhmm(charger_cfg: Optional[Mapping[str, Any]],
                   config: Optional[Mapping[str, Any]]) -> str:
    """The charger's departure time of day: its own ``ev_target_time``, else
    the global one, else 07:00. A blank or unreadable value is not a time and
    passes to the next."""
    for source in (charger_cfg or {}, config or {}):
        value = source.get("ev_target_time")
        if _usable(value):
            return str(value)
    return DEFAULT_EV_TARGET_TIME


def departure_for(charger_cfg: Optional[Mapping[str, Any]], now: datetime,
                  config: Optional[Mapping[str, Any]]) -> datetime:
    """The charger's next departure after ``now``."""
    return resolve_deadline(now, departure_hhmm(charger_cfg, config))
