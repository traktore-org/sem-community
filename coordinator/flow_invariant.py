"""(#778) Conservation of energy, as an evidence-quality gate.

A battery cannot send out more power than it is discharging. The attributed
flows — to home, to the car, to the grid — are bounded above by the pack's own
discharge, and an install where they are not has a misconfiguration somewhere
upstream of SEM's arithmetic.

Why this matters beyond tidiness: #800's night recorder integrates
``battery_to_home_w`` into ``drain_kwh``, and #778 builds its overnight-need
envelope out of those drains. An inflated flow therefore inflates what SEM
believes the house needs overnight, the spendable budget stays at zero forever,
and the card reports "holding" — which reads as a considered decision rather
than a broken input.

**Compared as POWER, per sample.** The first version compared the night
tracker's cumulative flows, accumulated from dusk with no midnight reset,
against ``daily_battery_discharge``, which resets at midnight. Every real night
spans midnight, so from 00:00 the counter restarted while the tracker kept
climbing and the check tripped on perfectly ordinary nights — a gate meant to
reject the occasional impossible night would have rejected almost every one,
and silently, because it fails safe. Comparing power removes the window from
the question entirely.

That demands a duration tolerance in exchange: two sensors read microseconds
apart disagree constantly, and one bad sample must not condemn a ten-hour
night. See ``VIOLATION_TOLERANCE_S``.

The gate does NOT repair the number. Clamping would hide the cause, and the
cause is real and worth finding. A violating night is recorded, is visible, and
is simply not trainable — the same treatment a night with too large a sampling
gap already gets.
"""

from __future__ import annotations

from typing import Any, Optional

#: How far over the discharge the attributed flows may sit before a sample
#: counts as violating. Sampling skew and rounding put the two sides a few
#: percent apart routinely; this gate exists for the 3x case.
TOLERANCE_FRACTION: float = 0.15

#: How long violations must persist before the night is refused. A single
#: sample is thirty seconds of a ten-hour night and proves nothing; five
#: minutes of sustained impossible flow is a real misconfiguration.
VIOLATION_TOLERANCE_S: float = 300.0

#: Below this, "more out than in" is metering noise around zero rather than a
#: conservation failure — a battery idling at 3 W does not need policing.
NOISE_FLOOR_W: float = 50.0


def _f(value: Any) -> Optional[float]:
    """Finite float or None. Never raises — this runs on live sensor values."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def flows_balance(
    *,
    discharge_w: Any,
    to_home: Any = 0.0,
    to_ev: Any = 0.0,
    to_grid: Any = 0.0,
) -> bool:
    """Whether this sample's attributed flows fit inside the pack's discharge.

    Returns True when the books balance AND when there is nothing to check: an
    install that publishes no battery power is unverifiable, not guilty, and
    failing those nights closed would throw away evidence on hardware that
    simply reports less.
    """
    discharge = _f(discharge_w)
    if discharge is None:
        return True

    out = sum(v for v in (_f(to_home), _f(to_ev), _f(to_grid)) if v is not None)
    if out <= NOISE_FLOOR_W:
        return True
    return out <= max(0.0, discharge) * (1.0 + TOLERANCE_FRACTION)
