"""(#778) Conservation of energy, as an evidence-quality gate.

A battery cannot send more energy out than it discharged. The sum of the
attributed flows — to home, to the car, to the grid — is bounded above by the
battery's own discharge counter, and any install where it is not has a
misconfiguration somewhere upstream of SEM's arithmetic.

Live on 23.08: .175 reported a 4.06 kWh discharge alongside 13.96 kWh of
outbound flow, 3.4x over. PROD, on identical code, read 3.04 against 4.04 and
balanced. So the violation was environmental — and nothing in SEM noticed it in
either direction, which is the actual defect being fixed here.

Why it matters beyond tidiness: #800's night recorder integrates
``battery_to_home_w`` into ``drain_kwh``, and #778 builds its overnight-need
envelope out of exactly those drains. An inflated flow therefore inflates what
SEM believes the house needs overnight, the spendable budget stays at zero
forever, and the card reports "holding" — which reads as a considered decision
rather than a broken input. The user is told their house needs 13 kWh a night
when it needs 5, and nothing anywhere says otherwise.

The gate does NOT repair the number. Clamping would hide the cause, and the
cause is real and worth finding. A violating night is recorded, is visible, and
is simply not trainable — the same treatment a night with too large a sampling
gap already gets.
"""

from __future__ import annotations

from typing import Any, Optional

#: How far over the discharge the attributed flows may sit before the night is
#: rejected. Sampling, rounding and counter granularity put the two sides a few
#: percent apart routinely; this gate exists for the 3x case.
TOLERANCE_FRACTION: float = 0.15


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
    discharge_kwh: Any,
    to_home: Any = 0.0,
    to_ev: Any = 0.0,
    to_grid: Any = 0.0,
) -> bool:
    """Whether the attributed flows fit inside what the battery discharged.

    Returns True when the books balance AND when there is nothing to check:
    an install that publishes no discharge counter is unverifiable, not
    guilty, and failing those nights closed would throw away evidence on
    hardware that simply reports less.
    """
    discharge = _f(discharge_kwh)
    if discharge is None or discharge <= 0:
        return True

    out = sum(v for v in (_f(to_home), _f(to_ev), _f(to_grid)) if v is not None)
    return out <= discharge * (1.0 + TOLERANCE_FRACTION)
