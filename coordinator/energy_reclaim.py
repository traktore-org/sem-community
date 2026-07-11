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
