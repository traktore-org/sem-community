"""#638 — the overnight joint planner: one pure schedule for every floor.

'All charged by morning' is a JOINT problem: N demands (EV floors by their
Charge-by deadlines #634, load min-runtimes #620, home-battery pre-charge),
one price curve, one peak cap, one priority order (#576). Today each planner
greedily picks 'the cheapest slots' on its own — they all fire at 02:00 and
the peak posture sheds the collision by priority (#652). Convergent and safe,
but the second-cheapest hours go unused, and nobody can say at 22:00
"not everything fits — X will yield".

This module is the closure: a greedy PRIORITY-PACKER over price-sorted slots.
Deliberately NOT an optimizer — no LP, no search. Pure, deterministic,
~200 lines, every allocation explainable in one line.

Disciplines (from the issue, agreed 2026-07-25):
* Floors stay guarantees: the packer moves WHEN and HOW FAST, never WHETHER.
  A floor that does not fit under the peak cap is REPORTED as yielding —
  the reactive deadline forcing still guarantees it downstream.
* The output is the same signal shapes the system already consumes
  (deadline/top-up amps for the EV, activation windows for loads);
  the reconcilers do not change.
* Shadow first (G3): compute + log alongside the reactive system.

Pure: no clock reads, no I/O, no Home Assistant imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# A demand's floor counts as met when planned energy reaches this share of the
# ask — guards float drift, never a real shortfall (0.1% of a 10 kWh floor
# is 10 Wh, far below meter resolution).
_FIT_EPS = 0.999


@dataclass(frozen=True)
class Demand:
    """One 'must-have by morning' — EV floor, load min-runtime, battery top-up.

    ``min_power_w`` is the device's hard floor per slot: an EV cannot charge
    below its min-amps (~1.4 kW single-phase, ~4.1 kW three-phase); a switch
    load is binary, so its min == max == rated; a battery is continuous from 0.
    ``priority`` is the one-list position (#576) — LOWER packs first.

    ``source`` is WHERE the energy comes from at night:

    * ``'grid'`` — draws through the meter: consumes the slot's peak cap and
      pays the slot price. The EV floor (never-from-battery rule), cheap-hours
      loads, and the battery's own pre-charge are grid demands.
    * ``'battery'`` — a Tier-2 overnight load running off the home battery:
      it does NOT touch the grid meter, so it consumes no peak cap and is
      indifferent to the price curve; it draws from the shared
      ``battery_budget_kwh`` instead (SOC above the reserve). Its planned
      cost is 0 here — the stored energy was paid for when it was charged.

    ``max_power_w`` / ``energy_kwh`` are only as good as the device's power
    model: for loads SEM uses the CALIBRATED rated power (learned from the
    real draw), and a deviation at night is a replan trigger, not a plan
    failure.
    """
    id: str
    kind: str                      # 'ev' | 'load' | 'battery'
    energy_kwh: float              # remaining need by the deadline
    max_power_w: float
    min_power_w: float = 0.0
    deadline: Optional[datetime] = None   # None = end of the night window
    priority: int = 0
    source: str = "grid"           # 'grid' | 'battery'


@dataclass(frozen=True)
class PriceSlot:
    """One slot of the night's price curve with its peak headroom.

    ``cap_w`` is what the caller says may be drawn from the grid in this slot
    on top of expected home load (peak_limit − expected_home). float('inf')
    when no peak limit is configured.
    """
    start: datetime
    end: datetime
    price: float                   # cost per kWh
    cap_w: float

    @property
    def hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


@dataclass(frozen=True)
class Allocation:
    demand_id: str
    start: datetime
    end: datetime
    power_w: float
    price: float
    reason: str                    # the one-line explanation

    @property
    def energy_kwh(self) -> float:
        return self.power_w / 1000.0 * max(
            0.0, (self.end - self.start).total_seconds() / 3600.0)


@dataclass(frozen=True)
class DemandResult:
    demand_id: str
    status: str                    # 'fits' | 'partial' | 'yields'
    planned_kwh: float
    needed_kwh: float
    est_cost: float


@dataclass(frozen=True)
class OvernightPlan:
    allocations: tuple                     # tuple[Allocation, ...]
    results: tuple                         # tuple[DemandResult, ...]
    total_cost: float
    fits: bool                             # every demand fully packed

    def summary_lines(self) -> list:
        """The 22:00 answer, one line per demand — the surface nobody ships."""
        out = []
        for r in self.results:
            if r.status == "fits":
                out.append(f"{r.demand_id}: fits — {r.planned_kwh:.1f} kWh "
                           f"planned, est {r.est_cost:.2f}")
            elif r.status == "partial":
                out.append(f"{r.demand_id}: YIELDS {r.needed_kwh - r.planned_kwh:.1f} "
                           f"kWh — only {r.planned_kwh:.1f}/{r.needed_kwh:.1f} kWh "
                           f"fits under the peak cap before its deadline")
            else:
                out.append(f"{r.demand_id}: YIELDS — nothing fits under the "
                           f"peak cap before its deadline")
        return out


def plan_overnight(demands, slots, battery_budget_kwh=float("inf")) -> OvernightPlan:
    """Pack every demand into the cheapest eligible slots, priority first.

    Greedy by the one-list: the highest-priority demand takes the cheapest
    slots it can use; each next demand packs into what remains. Deterministic:
    ties break on (price, start, demand priority, id) — same inputs, same plan.

    Grid demands compete for each slot's peak cap and pay the slot price.
    Battery-sourced demands (``source='battery'``) bypass both — no meter, no
    cap, price-indifferent — and instead share ``battery_budget_kwh`` (the
    usable energy above the battery reserve); they pack into the EARLIEST
    eligible slots (time, not price, orders them) and cost 0 in the plan.
    """
    remaining_cap = {i: float(s.cap_w) for i, s in enumerate(slots)}
    remaining_budget = float(battery_budget_kwh)
    # Price-sorted view of the night; rank is for the reason lines.
    order = sorted(range(len(slots)), key=lambda i: (slots[i].price, slots[i].start))
    time_order = sorted(range(len(slots)), key=lambda i: slots[i].start)
    rank = {i: n + 1 for n, i in enumerate(order)}

    allocations = []
    results = []

    for d in sorted(demands, key=lambda d: (d.priority, d.id)):
        need = max(0.0, float(d.energy_kwh))
        planned = 0.0
        cost = 0.0
        from_battery = d.source == "battery"
        for i in (time_order if from_battery else order):
            if need - planned <= 1e-9:
                break
            s = slots[i]
            if d.deadline is not None and s.end > d.deadline:
                continue                      # slot ends after the must-be-done
            hours = s.hours
            if hours <= 0:
                continue
            if from_battery:
                # No grid meter involved: the constraint is the shared battery
                # energy budget, not the slot's peak cap or price.
                if remaining_budget <= 1e-9:
                    break
                grant = float(d.max_power_w)
            else:
                grant = min(float(d.max_power_w), remaining_cap[i])
            if grant < max(1.0, float(d.min_power_w)):
                continue                      # below the device's hard floor
            # Shorten the last slot instead of over-delivering: run at the
            # lowest legal power, and if even that overshoots, end early.
            want_kwh = need - planned
            if from_battery:
                want_kwh = min(want_kwh, remaining_budget)
            power = min(grant, max(float(d.min_power_w), want_kwh / hours * 1000.0))
            run_h = min(hours, want_kwh / (power / 1000.0))
            if run_h <= 0:
                continue
            end = s.start + (s.end - s.start) * (run_h / hours)
            price = 0.0 if from_battery else s.price
            alloc = Allocation(
                demand_id=d.id, start=s.start, end=end, power_w=power,
                price=price,
                reason=(f"{d.id}: {power:.0f} W {s.start:%H:%M}–{end:%H:%M} "
                        + (f"from battery (budget left "
                           f"{remaining_budget - power / 1000.0 * run_h:.1f} kWh)"
                           if from_battery else
                           f"@ {s.price:.3f} (slot #{rank[i]} cheapest, "
                           f"cap left {remaining_cap[i] - power:.0f} W)")),
            )
            allocations.append(alloc)
            if from_battery:
                remaining_budget -= alloc.energy_kwh
            else:
                remaining_cap[i] -= power
            planned += alloc.energy_kwh
            cost += alloc.energy_kwh * price
        status = ("fits" if planned >= need * _FIT_EPS or need <= 1e-9
                  else "partial" if planned > 0 else "yields")
        results.append(DemandResult(
            demand_id=d.id, status=status, planned_kwh=round(planned, 3),
            needed_kwh=round(need, 3), est_cost=round(cost, 4),
        ))

    allocations.sort(key=lambda a: (a.start, a.demand_id))
    return OvernightPlan(
        allocations=tuple(allocations),
        results=tuple(results),
        total_cost=round(sum(a.energy_kwh * a.price for a in allocations), 4),
        fits=all(r.status == "fits" for r in results),
    )
