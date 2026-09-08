"""#934 — which SOC a consumer may use on a dark cycle: one rule, one place.

The reader holds the last accepted SOC through a dropout and says so on
``battery_soc_unavailable`` — on EVERY dark cycle — and, since #934, says
HOW LONG on ``battery_soc_stale_s`` (seconds since the last accepted read).
Consumers split by what they do with the number:

* a LIMIT (the #820 charge-power cap) is safe to hold through a short blink:
  releasing it is the permissive direction, and the writer's restore +
  re-engage pair cost a modbus write pair per dropout on a link that blinks
  ~250 times a day. A limit reads the SOC through ``soc_for_a_limit``.
* an ACTION on the pack (a sell, a VPP discharge, tonight's spend budget)
  may not ride a held reading at all (#932): those keep asking the flag,
  and say so at the read (``# DARK-SOC:``, linted by
  ``tests/test_934_dark_soc_reads_declare_themselves.py``).

The grace is the entity layer's dark-read grace (``SENSOR_DARK_READ_GRACE_S``,
inclusive at the boundary, exactly as the entity applies it): one constant
for "a blink", wherever a blink is forgiven.
"""
from __future__ import annotations

from typing import Optional

from ..consts.core import SENSOR_DARK_READ_GRACE_S


def soc_hold_age_s(power) -> int:
    """Seconds the reading's SOC has been held from the last accepted read:
    0 when it was read this cycle, and 0 before any read."""
    try:
        return max(0, int(getattr(power, "battery_soc_stale_s", 0) or 0))
    except (TypeError, ValueError):
        return 0


def soc_for_a_limit(power, *, grace_s: float = SENSOR_DARK_READ_GRACE_S
                    ) -> Optional[float]:
    """The SOC a LIMIT may be held on this cycle, or None.

    The fresh read; or the reader's held value while it is a measurement
    (``battery_soc_known``) and the hold is inside ``grace_s``. None before
    the first read (#875: the 0.0 there is not an empty pack), once an
    outage outlives the grace, and for a reading that carries no number.
    """
    if power is None:
        return None
    if not bool(getattr(power, "battery_soc_known", True)):
        return None
    if (bool(getattr(power, "battery_soc_unavailable", False))
            and soc_hold_age_s(power) > grace_s):
        return None
    raw = getattr(power, "battery_soc", None)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
