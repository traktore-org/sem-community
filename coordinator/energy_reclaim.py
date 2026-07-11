"""#576 — reclaimable battery-charge power.

The single gated quantity behind "loads/EV charge before the battery".
Above the reserve zone, power that would otherwise charge the battery is
made available to higher-priority consumers. Pure function so both control
paths (SurplusController, EV budget) share ONE definition and it is fully
unit-testable without a coordinator.
"""
from __future__ import annotations


def reclaimable_battery_w(
    *,
    battery_charge_power: float,
    soc: float,
    priority_soc: float,
    enabled: bool,
    battery_commanded: bool,
) -> float:
    """Watts currently charging the battery that a higher-priority load may
    take instead.

    Returns 0.0 (today's behavior) unless ALL hold:
      - the opt-in toggle is on,
      - SOC is at/above the reserve zone (``battery_priority_soc``),
      - the battery is NOT under an explicit/scheduled command
        (force-charge / scheduled / arbitrage — those are honored),
      - the battery is actually charging (positive power).
    """
    if not enabled or battery_commanded:
        return 0.0
    if soc < priority_soc:
        return 0.0
    return max(0.0, float(battery_charge_power))
