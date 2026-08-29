"""(#778) The spend TRIGGER — the arc's last leg.

The verdict side ships and is live (spendable budget, dynamic floor,
phase = ``spending``). The actuation side ships too: ``decide_battery``
sells on a DISCHARGING_ARBITRAGE verdict, budget-capped, floor-guarded,
permission-bound. But the only thing that OPENS a sell today is the
arbitrage engine — profitability math that requires a dynamic import
forecast and never fires on a fixed export price. Guido's install and the
reporter's both have fixed prices: a budget with no trigger.

This module is the missing WHETHER + the plan's WHEN for forecast-led
spending:

* ``forecast_sell_blocks`` — the plan side. One just-in-time block ending
  at the night window's start: latest-possible selling keeps options open
  and lands after the solar tail by construction, sized so the budget is
  spent exactly when the night takes over. (With a fixed export price
  there is no better slot to hunt for; when a real export-price FORECAST
  source exists one day, picking the richest slots belongs here.)
* ``evaluate_forecast_sell`` — the live side. Fires only inside the
  plan's open block, mirrors ``evaluate_arbitrage``'s verdict shape so
  the entire downstream discipline (mode/permission gate, three floors,
  budget cap, fleet split, #758 kill switch) applies unchanged.

Every default keeps it shut: the arc's master switch
(``forecast_spending_enabled``) is OFF, and without it neither the block
nor the verdict exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from .battery_charge_scheduler import SchedulerDecision, SchedulerState

#: Below this there is nothing worth a discharge cycle.
MIN_SPEND_KWH: float = 0.2
#: A block never runs shorter than this — a 4-minute sell is contactor
#: churn, not a plan.
MIN_BLOCK_MIN: int = 15
#: …and never longer than this. A budget too big for 6 h at the configured
#: rate sells 6 h worth; the rest stays in the pack for the night.
MAX_BLOCK_H: float = 6.0


def forecast_sell_blocks(
    now: datetime,
    night_start: Optional[datetime],
    spendable_kwh: float,
    max_discharge_w: float,
) -> List[dict]:
    """The plan's WHEN: one JIT block ``[night_start − duration, night_start)``.

    Returns ``[]`` whenever there is nothing to say — no budget, no night
    boundary, a rate that cannot move energy, or a night that has already
    begun (the night owns the battery from its first minute).
    """
    try:
        kwh = float(spendable_kwh or 0.0)
        w = float(max_discharge_w or 0.0)
    except (TypeError, ValueError):
        return []
    if night_start is None or kwh < MIN_SPEND_KWH or w <= 0:
        return []
    if now >= night_start:
        return []
    hours = min(MAX_BLOCK_H, kwh / (w / 1000.0))
    hours = max(hours, MIN_BLOCK_MIN / 60.0)
    start = max(now, night_start - timedelta(hours=hours))
    span_h = (night_start - start).total_seconds() / 3600.0
    if span_h * 60.0 < MIN_BLOCK_MIN:
        return []
    # kwh trimmed to what the window can actually carry at the cap —
    # the gate derives the rate as kwh/hours, and an over-stuffed block
    # would imply a rate above the inverter's own limit.
    kwh = min(kwh, span_h * w / 1000.0)
    return [{"start": start, "end": night_start, "kwh": round(kwh, 2)}]


def evaluate_forecast_sell(
    now: datetime,
    *,
    enabled: bool,
    in_block: bool,
    block_w: float,
    spendable_kwh: float,
    max_discharge_w: float,
    dynamic_floor_pct: Optional[float],
    reserve_pct: float,
) -> SchedulerDecision:
    """The live WHETHER, in ``evaluate_arbitrage``'s verdict shape.

    ``from_arbitrage=True`` so a non-firing verdict routes to
    STOP_FORCE_DISCHARGE (never the night scheduler's stop), plus
    ``from_forecast_spend=True`` so ``decide_battery`` checks the SPEND
    gate and the SPEND switch instead of arbitrage's."""
    def _v(**kw) -> SchedulerDecision:
        return SchedulerDecision(
            from_arbitrage=True, from_forecast_spend=True,
            evaluated_at=now, **kw)

    if not enabled:
        return _v(state=SchedulerState.IDLE, reason="forecast spending off")
    kwh = float(spendable_kwh or 0.0)
    if kwh < MIN_SPEND_KWH:
        return _v(state=SchedulerState.NOT_NEEDED,
                  reason=f"nothing spendable ({kwh:.1f} kWh)")
    if not in_block:
        return _v(state=SchedulerState.IDLE,
                  reason="outside the plan's spend window")
    sell_w = float(block_w or 0.0)
    if sell_w <= 0:
        sell_w = float(max_discharge_w or 0.0)
    if sell_w <= 0:
        return _v(state=SchedulerState.IDLE, reason="no discharge rate")
    # The floor decide_battery enforces is max(reserve, sched.floor_soc,
    # dynamic) — hand it the strongest one we know so a mis-plumbed view
    # still cannot sell into the night's reserve.
    floor = float(reserve_pct or 0.0)
    if dynamic_floor_pct is not None:
        try:
            floor = max(floor, float(dynamic_floor_pct))
        except (TypeError, ValueError):
            pass
    return _v(
        state=SchedulerState.DISCHARGING_ARBITRAGE,
        discharge_power_w=sell_w,
        floor_soc=floor,
        reason=(f"forecast spend: {kwh:.1f} kWh above tonight's need — "
                f"selling before the night at {sell_w:.0f} W"),
    )
