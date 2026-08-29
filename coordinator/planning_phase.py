"""(#778 phase 6) Which of three states the forecast budget is in.

The budget's own reason strings are prose written for a person to read, and
they are translated into sixteen languages. A card that decided what to render
by matching on their contents would break the first time one was reworded, and
would render the wrong thing in fifteen languages immediately. So the state is
published as a stable token beside the prose, and the card switches on the
token while displaying the prose.

Three states, because a user needs to tell them apart and today cannot:

``learning``
    The evidence needed to answer is not in yet. Every fresh install spends
    at least five nights here. Published as ``0.0``/``None`` today, which HA
    renders identically to a dead integration.

``holding``
    The question is answerable and the answer is genuinely nothing — a long
    winter night against a weak forecast. Numerically the same zero as
    ``learning``, and a completely different statement.

``spending``
    There is a budget tonight.
"""

from __future__ import annotations

from typing import Any, Optional

PHASE_LEARNING = "learning"
PHASE_HOLDING = "holding"
PHASE_SPENDING = "spending"


def _f(value: Any) -> Optional[float]:
    """Coerce to a finite float, or None. Never raises."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return out


def planning_phase(
    *,
    nights_sealed: Any,
    nights_required: Any,
    overnight_need_kwh: Any,
    usable_capacity_kwh: Any,
    spendable_kwh: Any,
) -> str:
    """Classify the budget's state for display.

    ``learning`` wins whenever any term the answer depends on is missing —
    including when a budget somehow appeared without the evidence to justify
    it. That case is an upstream bug, and rendering a confident "Spending"
    card would hide it behind exactly the surface a user would use to notice.
    """
    nights = _f(nights_sealed)
    required = _f(nights_required)
    need = _f(overnight_need_kwh)
    capacity = _f(usable_capacity_kwh)
    spendable = _f(spendable_kwh)

    evidence_complete = (
        nights is not None
        and required is not None
        and nights >= required
        and need is not None
        and capacity is not None
    )
    if not evidence_complete:
        return PHASE_LEARNING
    if spendable is not None and spendable > 0.0:
        return PHASE_SPENDING
    return PHASE_HOLDING
