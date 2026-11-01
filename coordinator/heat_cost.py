"""#1081 Slice A — what a kWh of HEAT costs, not what a kWh of electricity
costs. A heat pump's COP (coefficient of performance) means one kWh of
electricity makes ``COP`` kWh of heat, so heat's real price is
``price / COP`` — cheaper on a mild day (COP 4) than a cold one (COP 2)
even at the same electricity price. Pure, hass-free, mirrors
``curtailment.py``'s own contract.
"""
from __future__ import annotations

from typing import Optional


def cost_of_heat(price: Optional[float], cop: Optional[float]) -> Optional[float]:
    """``price / cop``, or ``None`` when either is missing or ``cop`` is
    not a real, positive number — never guess a cost from a broken input."""
    if price is None or cop is None:
        return None
    try:
        cop = float(cop)
    except (TypeError, ValueError):
        return None
    if cop <= 0:
        return None
    return float(price) / cop
