"""(#1083) A recorded 10-s day → the simulation's 24 hours (``HourlyDay``).

The Simulation tab reads an install's hourly long-term statistics; the
replay corpus holds 10-s readings. This adapter adds the corpus up into
the same shape, so the dev tool and the shipped model run on one input.
``tools/`` imports ``analytics/``; ``analytics/`` never imports ``tools/``.

* Flows: each cycle's power × ``cycle_s`` → kWh, split by SEM's signs
  (grid − import / + export, battery − discharge / + charge). Home is
  SEM's balance, clamped at 0, as SEM computes it.
* Means: SOC and import price are the hour's time-weighted mean, as the
  recorder's ``mean`` is. The corpus has no export price: the caller's
  flat rate stands in.
* A dark solar or grid reading in an hour marks that hour missing (it
  counts 0 W, as the reader hands it on, #925). A role the day does not
  carry at all (no battery, no car) is 0, not missing.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from custom_components.solar_energy_management.analytics.simulation.balance import (
    cost_hour,
)
from custom_components.solar_energy_management.analytics.simulation.hourly_day import (
    HOURS,
    HourlyDay,
)

from .recorded_day import RecordedDay

#: dark here makes the hour missing
CORE_INPUTS = ("solar_power", "grid_power")


def _hour_index(day: RecordedDay, t: float) -> int:
    return min(HOURS - 1, int(day.local_hour(t)))


def _mean(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _cycle_flows(c, step_s: float) -> dict:
    """One cycle's seven flows in kWh."""
    k = step_s / 3_600_000.0
    solar = max(0.0, c.get("solar_power", 0.0) or 0.0)
    grid = c.get("grid_power", 0.0) or 0.0
    batt = c.get("battery_power", 0.0) or 0.0
    ev = max(0.0, c.get("ev_power", 0.0) or 0.0)
    imp, exp = max(0.0, -grid), max(0.0, grid)
    dis, chg = max(0.0, -batt), max(0.0, batt)
    home = max(0.0, solar + imp + dis - ev - exp - chg)
    return {"solar": solar * k, "grid_import": imp * k, "grid_export": exp * k,
            "battery_charge": chg * k, "battery_discharge": dis * k,
            "ev": ev * k, "home": home * k}


def _morning_forecast(day: RecordedDay) -> Optional[float]:
    fc = sorted(v for t, v in day.series.get("forecast_today_kwh", [])
                if v and 5.0 <= day.local_hour(t) < 10.0)
    return fc[len(fc) // 2] if fc else None


def recorded_day_to_hourly(day: RecordedDay,
                           tags: Optional[Iterable[str]] = None) -> HourlyDay:
    """Add one corpus day up into 24 hours. ``tags`` default to the day's
    own tags."""
    if tags is None:
        tags = (day.tags or {}).get("tags") or []
    flows = {r: [0.0] * HOURS for r in ("solar", "grid_import", "grid_export",
                                        "battery_charge", "battery_discharge",
                                        "ev", "home")}
    soc: List[List[float]] = [[] for _ in range(HOURS)]
    price: List[List[float]] = [[] for _ in range(HOURS)]
    seen = set()
    missing = set()
    have_core = [r for r in CORE_INPUTS if day.series.get(r)]
    if len(have_core) < len(CORE_INPUTS):
        missing.update(range(HOURS))
    for c in day.cycles():
        h = _hour_index(day, c.t)
        seen.add(h)
        if any(c.dark(r) for r in have_core):
            missing.add(h)
        for role, kwh in _cycle_flows(c, day.cycle_s).items():
            flows[role][h] += kwh
        if c.values.get("battery_soc") is not None:
            soc[h].append(c.values["battery_soc"])
        if c.values.get("import_price") is not None:
            price[h].append(c.values["import_price"])
    missing.update(h for h in range(HOURS) if h not in seen)
    return HourlyDay(
        date=day.date, tags=list(tags),
        soc_pct=[_mean(v) for v in soc],
        import_rate=[_mean(v) for v in price],
        export_rate=[None] * HOURS,
        forecast_kwh=_morning_forecast(day),
        missing_hours=sorted(missing),
        **flows,
    )


def day_costs(day: RecordedDay, *, export_rate: float = 0.0
              ) -> Optional[Tuple[float, float]]:
    """The day's net cost twice: priced every 10-s cycle at that cycle's
    import price (what the meter saw), and re-priced hour by hour from
    the ``HourlyDay`` through the shipped model (``cost_hour``). ``None``
    when the day recorded no import price.

    A cycle with no price (before the first one) is priced at its hour's
    mean, the same rate the hourly side uses, so only the in-hour price
    shape can tell the two apart."""
    if not day.series.get("import_price"):
        return None
    hourly = recorded_day_to_hourly(day)
    fine = 0.0
    for c in day.cycles():
        h = _hour_index(day, c.t)
        rate = c.values.get("import_price")
        if rate is None:
            rate = hourly.import_rate[h]
        if rate is None:
            continue
        f = _cycle_flows(c, day.cycle_s)
        fine += f["grid_import"] * rate - f["grid_export"] * export_rate
    coarse = 0.0
    for h in range(HOURS):
        rate = hourly.import_rate[h]
        if rate is None:
            continue
        coarse += cost_hour(hourly.grid_import[h], hourly.grid_export[h],
                            rate, export_rate=export_rate).net_cost
    return fine, coarse
