"""(#1394) A device's draw as it stood when the house reading was taken.

The live base load is ``home - sum(device draws)``. ``home`` comes from the
grid, solar and battery meters; a grid meter read over modbus may report
only every 15-20 s.
A smart plug reports every second. When a plug's load switches on between
two grid reports, the plug already shows it and ``home`` does not yet:
19.11 05:18:29, house 647 W (grid read 05:18:21), coffee machine 1334 W,
base load -687 W. A negative base load is meant to show a real double
count, so these false ones hid real ones.

So each device's draw is taken at the time ``home`` was complete: the value
the device held then, from a short history of its own state changes. When
that time is unknown, or the device has not changed since, the live value
stands — exactly as before.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional, Tuple

#: How far back a device's value may be taken. A meter that has not
#: reported for longer says nothing about lag, only that it is flat.
MAX_SHIFT = timedelta(seconds=60)
#: Samples kept per device: one per change seen, at a 10 s cycle well over
#: ``MAX_SHIFT`` of history for any plug.
DEPTH = 12


class DrawHistory:
    """Per device: ``(changed_at, watts)`` as SEM saw them, oldest first."""

    def __init__(self) -> None:
        self._seen: Dict[str, Deque[Tuple[datetime, float]]] = {}

    def as_of(self, key: str, watts: float, changed_at: Optional[datetime],
              when: Optional[datetime]) -> float:
        """Note the live sample, then return the draw at ``when``.

        ``changed_at`` is the device state's ``last_updated`` (when its value
        last changed); ``when`` is the time the house reading was complete.
        """
        if changed_at is None:
            return watts
        try:
            hist = self._seen.setdefault(key, deque(maxlen=DEPTH))
            if not hist or hist[-1][0] != changed_at:
                hist.append((changed_at, watts))
            if when is None or changed_at <= when or changed_at - when > MAX_SHIFT:
                return watts
            # The device changed after the house reading: use what it held then.
            for t, w in reversed(hist):
                if t <= when:
                    return w
        except TypeError:            # a naive next to an aware stamp
            self._seen.pop(key, None)
        return watts                 # nothing older seen yet: as before


def house_complete_at(reports: Dict[str, datetime],
                      now: datetime) -> Optional[datetime]:
    """The time the house balance was complete: the OLDEST recent report
    among the meters it is made of (the reader leaves out meters at 0 W).
    A report older than ``MAX_SHIFT`` is a flat sensor an integration does
    not re-send, not a slow one, and is left out; with none left the answer
    is None (no alignment)."""
    try:
        recent = [t for t in reports.values() if now - t <= MAX_SHIFT]
        return min(recent) if recent else None
    except TypeError:                # a naive next to an aware stamp
        return None
