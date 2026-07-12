"""#576 — reclaimable battery-charge power.

The single quantity behind "loads charge before the battery": above the
reserve zone, power that would otherwise charge the home battery is added
to the surplus pool, so the surplus loads (walked by their own priority)
consume it first and the battery is the sink at the bottom. Pure function
so it is fully unit-testable without a coordinator.

There is **no opt-in toggle** — this is simply how device priority relates
to battery charging. The reserve floor (``battery_priority_soc``) protects
the evening: below it, the battery still fills first.
"""
from __future__ import annotations

from typing import Optional


def ev_reclaims_battery_charge(
    *,
    soc: float,
    priority_soc: float,
    ev_priority: int,
    battery_priority: Optional[int],
    battery_commanded: bool,
) -> bool:
    """Whether the EV may reclaim battery-charge power on its surplus path
    (#576 P2.2).

    The EV path stops subtracting ``battery_charge_w`` from its surplus — i.e.
    the EV charges *before* the battery — iff ALL hold:

    * the battery is NOT under an explicit command (force/scheduled/arbitrage
      charge is honored — the battery keeps its power),
    * a battery exists in the priority list (``battery_priority`` is not None),
    * SOC is at/above the reserve floor (``battery_priority_soc``),
    * the EV sits **above** the battery in the one list
      (``ev_priority < battery_priority``).

    This is the same rule the loads use (see the hand-back in
    ``SurplusController.update``), applied on the EV path — the position-based
    reclaim that replaces the old fixed ``auto_start_soc`` (90 %) gate. Below
    the floor, below the battery, or while the battery is commanded → the
    battery keeps its charge (today's behaviour).
    """
    if battery_commanded:
        return False
    if battery_priority is None:
        return False
    if soc < priority_soc:
        return False
    return ev_priority < battery_priority


def reclaimable_battery_w(
    *,
    battery_charge_power: float,
    soc: float,
    priority_soc: float,
    battery_commanded: bool,
) -> float:
    """Watts currently charging the battery that a higher-priority load may
    take instead.

    Returns 0.0 (battery keeps the charge) unless ALL hold:
      - SOC is at/above the reserve zone (``battery_priority_soc``),
      - the battery is NOT under an explicit/scheduled command
        (force-charge / scheduled / arbitrage — those are honored),
      - the battery is actually charging (positive power).
    """
    if battery_commanded:
        return 0.0
    if soc < priority_soc:
        return 0.0
    return max(0.0, float(battery_charge_power))
