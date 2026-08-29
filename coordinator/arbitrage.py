"""#638 — the shadow arbitrage advisor (the one-mind's last string).

Buy in the cheap slots, deliver into the expensive ones — advice only.
The advisor is the single client that reads EVERY page of the books:
the price curve (both horizons), the SOC room, the charge/discharge
power caps, the home's hour-by-hour grid draw, and tomorrow's forecast.
That reach is exactly why it exists during the BUILD phase: it is the
sharpest test instrument the ledger can have — if the books lie
anywhere, an economically-absurd advice is the first symptom.

Honesty rules, each one a test:

* the spread must survive the ROUND TRIP and the WEAR
  (η·p_sell − p_buy − wear > 0, per bought kWh);
* energy cannot flow backwards in time (deliver only after buying);
* avoided import needs an import to avoid — discharge value exists
  only where the home actually draws from the grid that hour;
* never grid-charge what tomorrow's sun fills free (the forecast caps
  the room);
* a price-0 day-surplus slot is the sun banking itself — normal solar
  charging, not an arbitrage buy;
* unpriced slots are not a market.

SHADOW-ONLY: nothing here actuates. The battery command wire stays in
its #533 deactivated state; the live proof of the mode is post-1.8 on
Guido's explicit call. Pure module — no clock reads, no I/O, no Home
Assistant imports (house contract, same as energy_planner).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Below this total the "opportunity" is float dust, not a plan.
_MIN_CYCLE_KWH = 0.05


@dataclass(frozen=True)
class ArbitrageAdvice:
    """The advisor's answer — a verdict with its numbers, never a bare
    boolean. ``charge_kwh`` is in BOUGHT kWh (the meter's view); the
    delivered side is η × that."""

    opportunity: bool
    charge_kwh: float
    est_profit: float
    reason: str
    charge_blocks: List[dict] = field(default_factory=list)
    discharge_blocks: List[dict] = field(default_factory=list)


def _no(reason: str) -> ArbitrageAdvice:
    return ArbitrageAdvice(opportunity=False, charge_kwh=0.0,
                           est_profit=0.0, reason=reason)


def arbitrage_advice(slots, *, soc_kwh: float, capacity_kwh: float,
                     max_charge_w: float, max_discharge_w: float,
                     round_trip_efficiency: float,
                     cycle_cost_per_kwh: float,
                     tomorrow_free_kwh: float = 0.0,
                     min_margin: float = 0.0) -> ArbitrageAdvice:
    """Greedy, deterministic, explainable — the house discipline.

    Pair the most valuable discharge hours with the cheapest EARLIER
    buy hours while the per-kWh margin clears η, wear and ``min_margin``;
    volumes are bounded by the battery's room (forecast-capped), the
    slot power caps, and the home's actual grid draw in the delivery
    hour. No optimizer: with ≤ ~30 slots a double loop is exact enough
    and every allocation can say why it exists.
    """
    eta = max(0.01, min(1.0, float(round_trip_efficiency)))
    wear = max(0.0, float(cycle_cost_per_kwh))

    # A surplus slot (cap_override marks it) is the sun banking itself —
    # excluded from BOTH sides: not a buy, and its home draw is 0 anyway.
    market = [s for s in slots
              if s.price is not None and s.cap_override_w is None]
    if not market:
        return _no("no priced market in the horizon")

    room = max(0.0, float(capacity_kwh) - float(soc_kwh)
               - max(0.0, float(tomorrow_free_kwh)))
    if room < _MIN_CYCLE_KWH:
        return _no(
            f"no room to buy into: battery {soc_kwh:.1f}/{capacity_kwh:.1f} "
            f"kWh full, tomorrow's sun expected to add "
            f"{tomorrow_free_kwh:.1f} kWh free")

    # Per-slot budgets, mutated as pairs consume them.
    buy_left = {id(s): max_charge_w * s.hours / 1000.0 for s in market}
    # Delivered kWh a slot can absorb = what the home would otherwise
    # import there, bounded by the discharge power cap.
    deliver_left = {
        id(s): min(max(0.0, s.home_grid_w) * s.hours / 1000.0,
                   max_discharge_w * s.hours / 1000.0)
        for s in market
    }

    sells = sorted((s for s in market if deliver_left[id(s)] > 0),
                   key=lambda s: (-s.price, s.start))
    buys_by_price = sorted(market, key=lambda s: (s.price, s.start))

    charge: dict = {}
    discharge: dict = {}
    total_buy = 0.0
    profit = 0.0
    best_net = None
    for d in sells:
        for c in buys_by_price:
            if c.end > d.start:
                continue                    # deliver only after buying
            net = eta * d.price - c.price - wear
            if best_net is None or net > best_net:
                best_net = net
            if net <= min_margin:
                continue
            vol = min(room - total_buy, buy_left[id(c)],
                      deliver_left[id(d)] / eta)
            if vol <= 0:
                continue
            buy_left[id(c)] -= vol
            deliver_left[id(d)] -= vol * eta
            total_buy += vol
            profit += vol * net
            charge[id(c)] = (c, charge.get(id(c), (c, 0.0))[1] + vol)
            discharge[id(d)] = (
                d, discharge.get(id(d), (d, 0.0))[1] + vol * eta)
            if room - total_buy <= 0:
                break
        if room - total_buy <= 0:
            break

    if total_buy < _MIN_CYCLE_KWH:
        if best_net is None:
            return _no("no delivery hour with a grid draw to displace")
        return _no(
            f"best spread does not pay: η×sell − buy − wear = "
            f"{best_net:+.3f}/kWh")

    def _rows(alloc):
        return [{"start": s.start, "end": s.end,
                 "kwh": round(kwh, 3), "price": s.price}
                for s, kwh in sorted(alloc.values(),
                                     key=lambda x: x[0].start)]

    c_rows, d_rows = _rows(charge), _rows(discharge)
    avg_buy = sum(r["kwh"] * r["price"] for r in c_rows) / total_buy
    delivered = sum(r["kwh"] for r in d_rows)
    avg_sell = (sum(r["kwh"] * r["price"] for r in d_rows) / delivered
                if delivered else 0.0)
    return ArbitrageAdvice(
        opportunity=True,
        charge_kwh=round(total_buy, 3),
        est_profit=round(profit, 3),
        reason=(f"buy {total_buy:.1f} kWh @ ~{avg_buy:.2f}, deliver "
                f"{delivered:.1f} kWh @ ~{avg_sell:.2f} — "
                f"est {profit:+.2f}"),
        charge_blocks=c_rows,
        discharge_blocks=d_rows,
    )
