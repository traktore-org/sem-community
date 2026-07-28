"""#638 — the Night Ledger and the overnight joint packer.

One shared, pure structure over EXISTING knowledge (spec:
docs/superpowers/specs/2026-07-28-overnight-flow-plan-design.md): an
hour-by-hour (or 15-min — slots follow the market) table of the night —
price, expected home draw (weekday-aware), the battery SOC trajectory, and
the grid headroom that shrinks THE HOUR the battery empties and home lands
on the meter (the takeover). The four kinds of floors pack into the ledger
by the one priority list (#576); the output is a report + the same signal
shapes the reactive system already consumes.

Disciplines (unchanged): greedy, deterministic, explainable — no optimizer.
Floors move WHEN and HOW FAST, never WHETHER; what cannot fit is REPORTED.
Pure: no clock reads, no I/O, no Home Assistant imports.

Tariff robustness (spec §tariff): slots may be UNPRICED (day-ahead not yet
published) — price-driven demands pack only into priced slots and the
price-fingerprint replan re-derives the ledger when the series lands;
cheap-hours loads pack only into slots the provider's LEVEL marks cheap,
because that is what execution's ``price_is_cheap`` gate fires on.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_FIT_EPS = 0.999          # float-drift guard on "floor met", never a real short
_W_EPS = 1.0              # grants below 1 W are noise


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Demand:
    """One 'must-have by morning'.

    ``source`` fixes where the energy comes from (config decides, not the
    packer): 'grid' consumes headroom and pays the curve (EV floors — the
    never-from-battery rule — cheap-hours loads, battery pre-charge);
    'battery' spends the trajectory above the sunrise floor (Tier-2 loads).

    ``min_power_w``: EV min-amps floor; binary loads: == max (rated);
    battery: 0. ``needs_cheap_level``: execution gates this demand on the
    provider's price LEVEL (cheap-hours loads) — the packer must match.
    ``min_run_s``/``min_gap_s``: the #688 anti-cycle windows — an allocation
    shorter than min-run would physically run min-run anyway, so the plan
    quantizes honestly. ``priority``: one-list position, LOWER packs first
    (callers negate the drag-list number).
    """
    id: str
    kind: str                       # 'ev' | 'load' | 'battery'
    energy_kwh: float
    max_power_w: float
    min_power_w: float = 0.0
    deadline: Optional[datetime] = None
    priority: int = 0
    source: str = "grid"            # 'grid' | 'battery'
    needs_cheap_level: bool = False
    min_run_s: int = 0
    min_gap_s: int = 0


@dataclass
class LedgerSlot:
    """One market slot of the night. ``price=None`` = unpriced (not yet
    published). The trajectory fields are computed by ``build_night_ledger``
    and re-derived as packing mutates the battery's path."""
    start: datetime
    end: datetime
    price: Optional[float]
    level_cheap: bool = False
    home_w: float = 0.0
    # computed by the walk:
    soc_kwh: float = 0.0            # battery energy at slot START
    home_grid_w: float = 0.0        # home's share on the METER this slot
    home_batt_kwh: float = 0.0      # home energy the battery actually covered
    headroom_w: float = float("inf")
    # packing events, applied/preserved on every walk:
    batt_out_kwh: float = 0.0       # Tier-2 loads drawing the battery
    batt_in_kwh: float = 0.0        # pre-charge raising the trajectory (G4 hook)
    grid_committed_w: float = 0.0   # grid power already allocated here — a
                                    # re-walk must NOT resurrect spent headroom
    # explicit per-slot cap override (compat path); None = derive from peak
    cap_override_w: Optional[float] = None

    @property
    def hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

def build_night_ledger(slots, *, soc_kwh, floor_kwh, max_discharge_w,
                       peak_limit_w) -> list:
    """Walk the night once: home draws the battery down to the sunrise floor
    (bounded by discharge power), the remainder lands on the meter, and the
    grid headroom per slot follows. ``_walk`` re-runs whenever packing
    changes the battery's path — a Tier-2 draw empties it EARLIER, the
    takeover hour moves, and later grid headroom shrinks."""
    ledger = sorted(slots, key=lambda s: s.start)
    _walk(ledger, soc_kwh, floor_kwh, max_discharge_w, peak_limit_w)
    return ledger


def _walk(ledger, soc_kwh, floor_kwh, max_discharge_w, peak_limit_w) -> None:
    soc = float(soc_kwh)
    for s in ledger:
        s.soc_kwh = soc
        h = s.hours
        # Pre-charge raises the trajectory (energy arrives this slot).
        soc += s.batt_in_kwh
        # Home draws battery first — energy above the floor, power-bounded.
        home_kwh = s.home_w * h / 1000.0
        avail = max(0.0, soc - floor_kwh)
        batt_home = min(home_kwh, avail,
                        max_discharge_w * h / 1000.0 if h > 0 else 0.0)
        # Tier-2 loads booked into this slot also draw the battery.
        batt_loads = min(s.batt_out_kwh, max(0.0, avail - batt_home))
        soc -= batt_home + batt_loads
        s.home_batt_kwh = batt_home
        s.home_grid_w = (home_kwh - batt_home) / h * 1000.0 if h > 0 else 0.0
        # Re-walks must PRESERVE grid allocations already packed here
        # (grid_committed_w) — recomputing headroom from peak − home alone
        # would resurrect spent headroom and let a later demand over-
        # subscribe the cap (reviewer HIGH, 2026-07-29).
        if s.cap_override_w is not None:
            s.headroom_w = max(0.0, float(s.cap_override_w)
                               - s.grid_committed_w)
        elif peak_limit_w and peak_limit_w > 0:
            s.headroom_w = max(0.0, peak_limit_w - s.home_grid_w
                               - s.grid_committed_w)
        else:
            s.headroom_w = float("inf")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Allocation:
    demand_id: str
    start: datetime
    end: datetime
    power_w: float
    price: float
    reason: str

    @property
    def energy_kwh(self) -> float:
        return self.power_w / 1000.0 * max(
            0.0, (self.end - self.start).total_seconds() / 3600.0)


@dataclass(frozen=True)
class DemandResult:
    demand_id: str
    status: str                     # 'fits' | 'partial' | 'yields'
    planned_kwh: float
    needed_kwh: float
    est_cost: float
    note: str = ""


@dataclass(frozen=True)
class OvernightPlan:
    allocations: tuple
    results: tuple
    total_cost: float
    fits: bool
    takeover: Optional[datetime] = None   # first slot home hits the meter

    def summary_lines(self) -> list:
        """The 22:00 answer, one line per demand."""
        out = []
        for r in self.results:
            if r.status == "fits":
                out.append(f"{r.demand_id}: fits — {r.planned_kwh:.1f} kWh "
                           f"planned, est {r.est_cost:.2f}"
                           + (f" ({r.note})" if r.note else ""))
            else:
                gap = r.needed_kwh - r.planned_kwh
                out.append(f"{r.demand_id}: YIELDS {gap:.1f} kWh — "
                           f"{r.planned_kwh:.1f}/{r.needed_kwh:.1f} kWh"
                           + (f" ({r.note})" if r.note else ""))
        return out


# ---------------------------------------------------------------------------
# The packer
# ---------------------------------------------------------------------------

def pack_night(demands, ledger, *, floor_kwh=0.0, max_discharge_w=5000.0,
               peak_limit_w=0.0) -> OvernightPlan:
    """Pack every demand into the ledger, one-list priority first.

    Grid demands take the cheapest PRICED eligible slots within headroom
    (cheap-hours loads additionally require the provider's cheap LEVEL —
    execution's gate). Battery demands (Tier-2) draw the trajectory above
    the sunrise floor, earliest first, price-blind, cost 0 — every draw
    re-walks the trajectory, so a Tier-2 kWh tonight honestly moves the
    takeover hour and shrinks later headroom. Load allocations quantize to
    the anti-cycle window (#688): a run shorter than min-run is planned AT
    min-run (that is what would physically happen), and two blocks of the
    same load never sit closer than min-gap.
    """
    if not ledger:
        results = tuple(
            DemandResult(d.id, "fits" if d.energy_kwh <= 1e-9 else "yields",
                         0.0, round(max(0.0, d.energy_kwh), 3), 0.0,
                         note="no night window")
            for d in sorted(demands, key=lambda d: (d.priority, d.id)))
        return OvernightPlan((), results, 0.0,
                             all(r.status == "fits" for r in results), None)

    initial_soc = ledger[0].soc_kwh
    idx = list(range(len(ledger)))
    by_price = sorted(
        (i for i in idx if ledger[i].price is not None),
        key=lambda i: (ledger[i].price, ledger[i].start))
    rank = {i: n + 1 for n, i in enumerate(by_price)}
    unpriced = sum(1 for s in ledger if s.price is None)

    allocations = []
    results = []
    last_block_end = {}             # demand id -> datetime of its last block

    def _eligible(d, i):
        s = ledger[i]
        if d.deadline is not None and s.end > d.deadline:
            return False
        if d.needs_cheap_level and not s.level_cheap:
            return False
        prev = last_block_end.get(d.id)
        if (prev is not None and d.min_gap_s > 0 and s.start > prev
                and (s.start - prev).total_seconds() < d.min_gap_s):
            return False
        return True

    for d in sorted(demands, key=lambda d: (d.priority, d.id)):
        need = max(0.0, float(d.energy_kwh))
        planned = 0.0
        cost = 0.0
        note = ""
        order = (idx if d.source == "battery" else by_price)
        for i in order:
            if need - planned <= 1e-9:
                break
            s = ledger[i]
            h = s.hours
            if h <= 0 or not _eligible(d, i):
                continue
            if d.source == "battery":
                # From the WALKED state: what the trajectory leaves above the
                # floor after home's ACTUAL battery share this slot (clamped
                # by the walk, not the raw home ask) and draws already booked.
                avail = max(0.0, s.soc_kwh + s.batt_in_kwh - floor_kwh
                            - s.home_batt_kwh - s.batt_out_kwh)
                if avail <= 1e-9:
                    continue
                # The battery constrains ENERGY (run length), not power — a
                # binary 2 kW heater with 1 kWh above the floor runs at 2 kW
                # for 30 min. Power is bounded only by device + discharge.
                grant = min(float(d.max_power_w), max_discharge_w)
                want = min(need - planned, avail)
            else:
                grant = min(float(d.max_power_w), s.headroom_w)
                want = need - planned
            if grant < max(_W_EPS, float(d.min_power_w)):
                continue
            power = min(grant, max(float(d.min_power_w), want / h * 1000.0))
            run_h = min(h, want / (power / 1000.0))
            # (#688) anti-cycle quantization: a shorter run would be HELD to
            # min-run by can_deactivate anyway — plan the truth. A battery
            # run stays energy-capped (execution's reserve gate stops it).
            if d.min_run_s > 0:
                run_h = min(h, max(run_h, d.min_run_s / 3600.0))
                if d.source == "battery":
                    run_h = min(run_h, avail / (power / 1000.0))
            if run_h <= 0:
                continue
            end = s.start + timedelta(hours=run_h)
            price = 0.0 if d.source == "battery" else float(s.price)
            e_kwh = power / 1000.0 * run_h
            if d.source == "battery":
                s.batt_out_kwh += e_kwh
                _walk(ledger, initial_soc, floor_kwh,
                      max_discharge_w, peak_limit_w)
                why = (f"{d.id}: {power:.0f} W {s.start:%H:%M}–{end:%H:%M} "
                       f"from battery (trajectory leaves "
                       f"{max(0.0, s.soc_kwh - floor_kwh):.1f} kWh above floor)")
            else:
                s.grid_committed_w += power   # survives trajectory re-walks
                s.headroom_w -= power
                why = (f"{d.id}: {power:.0f} W {s.start:%H:%M}–{end:%H:%M} "
                       f"@ {price:.3f} (slot #{rank[i]} cheapest, "
                       f"headroom left {s.headroom_w:.0f} W)")
            allocations.append(Allocation(
                demand_id=d.id, start=s.start, end=end, power_w=power,
                price=price, reason=why))
            last_block_end[d.id] = end
            planned += e_kwh
            cost += e_kwh * price
        if (need > 1e-9 and planned < need * _FIT_EPS and unpriced
                and d.source != "battery"):
            note = (f"{unpriced} slot(s) unpriced — replans when the "
                    f"day-ahead series lands")
        elif d.needs_cheap_level and planned == 0 and need > 1e-9:
            if not any(s.level_cheap for s in ledger):
                note = "no cheap window tonight"
        status = ("fits" if planned >= need * _FIT_EPS or need <= 1e-9
                  else "partial" if planned > 0 else "yields")
        results.append(DemandResult(
            demand_id=d.id, status=status, planned_kwh=round(planned, 3),
            needed_kwh=round(need, 3), est_cost=round(cost, 4), note=note))

    takeover = next((s.start for s in ledger if s.home_grid_w > _W_EPS), None)
    allocations.sort(key=lambda a: (a.start, a.demand_id))
    return OvernightPlan(
        allocations=tuple(allocations),
        results=tuple(results),
        total_cost=round(sum(a.energy_kwh * a.price for a in allocations), 4),
        fits=all(r.status == "fits" for r in results),
        takeover=takeover,
    )


# ---------------------------------------------------------------------------
# Compat: the flat-slot API used by the (parked) shadow hook and early corpus.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    price: float
    cap_w: float

    @property
    def hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


def plan_overnight(demands, slots, battery_budget_kwh=float("inf")):
    """Thin adapter: flat slots (explicit cap, no home, no trajectory) →
    ledger. Battery-sourced demands draw a synthetic battery holding the
    given budget above a zero floor. Kept so the shadow hook and the
    original corpus semantics stay valid; new callers build a real ledger."""
    budget = (1e9 if battery_budget_kwh == float("inf")
              else float(battery_budget_kwh))
    ledger = [LedgerSlot(start=s.start, end=s.end, price=s.price,
                         level_cheap=True, home_w=0.0,
                         cap_override_w=float(s.cap_w)) for s in slots]
    ledger = build_night_ledger(
        ledger, soc_kwh=budget, floor_kwh=0.0,
        max_discharge_w=1e9, peak_limit_w=0.0)
    return pack_night(demands, ledger, floor_kwh=0.0,
                      max_discharge_w=1e9, peak_limit_w=0.0)
