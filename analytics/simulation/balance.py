"""(#1083) Close one hour's energy and price it with SEM's own rules.

Pure: no Home Assistant.

* The balance is SEM's: ``home = solar + import + discharge − ev − export
  − charge``, clamped at 0 as SEM clamps it. The flows are AC-side kWh; the
  battery's losses are written out (√ of the round trip each way), never
  hidden in the house.
* The price is ``energy_calculator.py``'s: import × rate, export × rate
  (a negative export rate makes the revenue negative), and the kWh sent
  out at a negative rate counted again on their own, as ``cost_export_
  negative`` is — shown, not charged twice. Solar savings follow the
  production path: solar to the house + solar to the car (solar serves
  the house first, then the car), × import rate.

Prices are hourly means. On prices that are flat inside each hour the
re-priced recorded day matches SEM's own cost; 15-minute prices inside
an hour are averaged away, so it is then close, not exact.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

ROUNDTRIP = 0.92


def one_way(roundtrip: float = ROUNDTRIP) -> float:
    """The efficiency of one direction: √ of the round trip."""
    return math.sqrt(max(1e-9, float(roundtrip)))


@dataclass(frozen=True)
class HourBalance:
    home_kwh: float
    #: kWh that reached the cells from ``battery_charge``
    stored_kwh: float
    #: kWh taken from the cells to give ``battery_discharge``
    drawn_kwh: float
    #: battery losses this hour, both ways
    loss_kwh: float
    #: what the 0-clamp on ``home`` threw away; 0 on a closed hour
    clamped_kwh: float


def balance_hour(*, solar: float, grid_import: float, grid_export: float,
                 battery_charge: float, battery_discharge: float, ev: float,
                 roundtrip: float = ROUNDTRIP) -> HourBalance:
    """Close one hour. All inputs are AC-side kWh, all ≥ 0."""
    raw = (solar + grid_import + battery_discharge
           - ev - grid_export - battery_charge)
    eff = one_way(roundtrip)
    stored = battery_charge * eff
    drawn = battery_discharge / eff
    return HourBalance(
        home_kwh=max(0.0, raw),
        stored_kwh=stored,
        drawn_kwh=drawn,
        loss_kwh=(battery_charge - stored) + (drawn - battery_discharge),
        clamped_kwh=max(0.0, -raw),
    )


@dataclass(frozen=True)
class HourCost:
    import_cost: float
    #: export × rate — negative when the rate is negative
    export_revenue: float
    #: import cost − export revenue, as ``daily_net_cost``
    net_cost: float
    #: kWh sent out at a negative rate, and what they cost (shown apart)
    negative_export_kwh: float
    negative_export_cost: float
    solar_savings: float

    def as_dict(self) -> dict:
        return asdict(self)


def cost_hour(import_kwh: float, export_kwh: float, import_rate: float,
              export_rate: float, *, solar_kwh: float = 0.0,
              home_kwh: float = 0.0, ev_kwh: float = 0.0) -> HourCost:
    """Price one hour as ``energy_calculator.py`` does."""
    imp = max(0.0, float(import_kwh))
    exp = max(0.0, float(export_kwh))
    rate_in = float(import_rate)
    rate_out = float(export_rate)
    import_cost = imp * rate_in
    export_revenue = exp * rate_out
    neg_kwh = exp if rate_out < 0 else 0.0
    # Solar self-consumed = solar_to_home + solar_to_ev, the path
    # energy_calculator.py takes with power flows: the sun serves the
    # house first, then the car, so together that is min(solar, both).
    self_used = max(0.0, min(float(solar_kwh), home_kwh + ev_kwh))
    return HourCost(
        import_cost=import_cost,
        export_revenue=export_revenue,
        net_cost=import_cost - export_revenue,
        negative_export_kwh=neg_kwh,
        negative_export_cost=neg_kwh * abs(rate_out),
        solar_savings=self_used * rate_in,
    )


SUM_KEYS = ("solar", "grid_import", "grid_export", "battery_charge",
            "battery_discharge", "ev", "home", "loss_kwh", "over_limit_kwh",
            "import_cost", "export_revenue", "net_cost",
            "negative_export_kwh", "negative_export_cost", "solar_savings")


def summarise_day(rows: Iterable[Mapping]) -> dict:
    """Add up hour rows (flows and costs). Missing keys count 0."""
    out = {k: 0.0 for k in SUM_KEYS}
    for row in rows:
        for k in SUM_KEYS:
            out[k] += float(row.get(k, 0.0) or 0.0)
    return {k: round(v, 6) for k, v in out.items()}
