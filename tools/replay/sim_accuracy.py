"""(#1083) How close is the Simulation tab to what really happened?

Runs the simulation with the install's OWN settings over recorded days and
compares each day's simulated net cost with the cost SEM recorded that day
(``sensor.sem_daily_costs`` − ``sensor.sem_daily_export_revenue``). If the
own settings do not give back the real bill, no what-if can be trusted.

The fixture is a read-only export of hourly long-term statistics (numbers
only, never in git)::

    {"tz": "Europe/Zurich",
     "config": {...SEM config...},              # optional, or --config
     "rows": {"solar": [{"start": ISO, "change": kWh}, ...], ...,
              "cost": [...], "revenue": [...]}}

Roles: the simulation's (``hourly_day.ROLES``) plus ``cost`` and
``revenue`` (the day's recorded money, hourly ``change``).

The error measure. A day's net cost is often near 0 (a sunny day can be
−0.05 CHF), so a share of the net cost explodes on the days that matter
least. The error is a share of the money that moved — the recorded import
cost + export revenue — over the same days::

    error % = |Σ simulated net − Σ actual net| / Σ (import cost + revenue)

The gate: the whole period within ``GATE_TOTAL_PCT`` and no day type (sky,
car, month) worse than ``GATE_TYPE_PCT``.

Run::

    python -m custom_components.solar_energy_management.tools.replay.sim_accuracy \\
        FIXTURE.json [--model decisions|balance] [--days N] [--config CFG.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from ...analytics.day_tags import clear_sky_envelope, tag_day
from ...analytics.simulation.battery_sim import (
    MODEL_BALANCE,
    MODEL_DECISIONS,
    PeriodChain,
    SimParams,
)
from ...analytics.simulation.hourly_day import CORE_ROLES, ROLES, HourlyDay

GATE_TOTAL_PCT = 5.0
GATE_TYPE_PCT = 10.0
#: a day whose recorded bill and recorded meter disagree by more than this
#: (CHF, or this share of the money moved) cannot judge the simulation —
#: the simulation can only give back the meter
TRUTH_TOL_ABS = 0.05
TRUTH_TOL_SHARE = 0.02
TRUTH_ROLES = ("cost", "revenue")


@dataclass
class TruthDay:
    day: HourlyDay
    cost: float
    revenue: float

    @property
    def net(self) -> float:
        return self.cost - self.revenue

    @property
    def moved(self) -> float:
        return abs(self.cost) + abs(self.revenue)


def _day_of(start: Any, tz) -> Optional[str]:
    if isinstance(start, (int, float)):
        t = start / 1000.0 if start > 1e11 else float(start)
        return datetime.fromtimestamp(t, tz).date().isoformat()
    try:
        return datetime.fromisoformat(str(start)).astimezone(tz).date().isoformat()
    except ValueError:
        return None


def split_by_day(rows: Mapping[str, Iterable[Mapping[str, Any]]], tz
                 ) -> Dict[str, Dict[str, List[Mapping[str, Any]]]]:
    """``{date: {role: rows}}``."""
    out: Dict[str, Dict[str, List[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list))
    for role, lst in rows.items():
        for row in lst or []:
            d = _day_of(row.get("start"), tz)
            if d:
                out[d][role].append(row)
    return out


def tag_hourly(day: HourlyDay, envelope: Optional[float]) -> List[str]:
    """The backfill's hourly rule (sky, car), as the day-tag store tags a
    day older than the recorder's raw states."""
    solar = [(float(h), day.solar[h] * 1000.0) for h in range(24)]
    tags = tag_day(date=day.date, solar=solar, actual_kwh=day.total("solar"),
                   session_kwh=[day.total("ev")], hourly=True,
                   envelope_kwh=envelope)
    return tags.tags


def load_days(fixture: Mapping[str, Any], *, last: Optional[int] = None
              ) -> List[TruthDay]:
    """Every whole day of the fixture, oldest first. A day without all
    core roles, the money or a full 24 hours is left out — it cannot be
    compared."""
    tz = ZoneInfo(fixture.get("tz") or "UTC")
    by_day = split_by_day(fixture["rows"], tz)
    whole = []
    for d in sorted(by_day):
        roles = by_day[d]
        if any(not roles.get(r) for r in CORE_ROLES + TRUTH_ROLES):
            continue
        day = HourlyDay.from_statistics(
            {r: roles.get(r) or [] for r in ROLES}, date=d, tz=tz)
        if day.missing_hours:
            continue
        cost = sum(float(r.get("change") or 0.0) for r in roles["cost"])
        rev = sum(float(r.get("change") or 0.0) for r in roles["revenue"])
        whole.append(TruthDay(day=day, cost=cost, revenue=rev))
    if last:
        whole = whole[-int(last):]
    yields = {t.day.date: t.day.total("solar") for t in whole}
    for t in whole:
        t.day.tags = tag_hourly(t.day, clear_sky_envelope(yields, t.day.date))
    return whole


@dataclass
class Bucket:
    days: int = 0
    actual: float = 0.0
    simulated: float = 0.0
    moved: float = 0.0
    import_kwh_actual: float = 0.0
    import_kwh_sim: float = 0.0
    export_kwh_actual: float = 0.0
    export_kwh_sim: float = 0.0

    def add(self, t: TruthDay, res) -> None:
        self.days += 1
        self.actual += t.net
        self.simulated += float(res.simulated_cost)
        self.moved += t.moved
        self.import_kwh_actual += t.day.total("grid_import")
        self.import_kwh_sim += res.simulated["grid_import"]
        self.export_kwh_actual += t.day.total("grid_export")
        self.export_kwh_sim += res.simulated["grid_export"]

    @property
    def error_pct(self) -> float:
        if self.moved <= 0:
            return 0.0
        return 100.0 * abs(self.simulated - self.actual) / self.moved

    def as_dict(self) -> dict:
        return {"days": self.days, "actual": round(self.actual, 2),
                "simulated": round(self.simulated, 2),
                "moved": round(self.moved, 2),
                "error_pct": round(self.error_pct, 1),
                "import_kwh": [round(self.import_kwh_actual, 1),
                               round(self.import_kwh_sim, 1)],
                "export_kwh": [round(self.export_kwh_actual, 1),
                               round(self.export_kwh_sim, 1)]}


@dataclass
class Report:
    model: str
    total: Bucket = field(default_factory=Bucket)
    by_type: Dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_month: Dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    rows: List[dict] = field(default_factory=list)
    stored_energy_value: float = 0.0
    stored_energy_kwh: float = 0.0
    #: days left out of the error: their bill disagrees with their meter
    excluded: List[dict] = field(default_factory=list)

    @property
    def worst_type(self) -> float:
        return max((b.error_pct for b in self.by_type.values()), default=0.0)

    @property
    def gate_met(self) -> bool:
        return (self.total.error_pct <= GATE_TOTAL_PCT
                and self.worst_type <= GATE_TYPE_PCT)

    def as_dict(self) -> dict:
        return {"model": self.model, "gate_met": self.gate_met,
                "total": self.total.as_dict(),
                "stored_energy_value": round(self.stored_energy_value, 2),
                "stored_energy_kwh": round(self.stored_energy_kwh, 2),
                "excluded": len(self.excluded),
                "by_type": {k: v.as_dict() for k, v in sorted(self.by_type.items())},
                "by_month": {k: v.as_dict() for k, v in sorted(self.by_month.items())}}


def day_types(tags: Iterable[str]) -> List[str]:
    tags = list(tags)
    out = [t for t in ("sunny", "mixed", "grey") if t in tags]
    out.append("car" if "car" in tags else "no car")
    return out


def measure(days: List[TruthDay], cfg: Mapping[str, Any],
            model: str = MODEL_DECISIONS,
            params: Optional[SimParams] = None) -> Report:
    """Run the own settings (or ``params``) over ``days`` as one chained
    run and compare every day with what it really cost."""
    params = params or SimParams.from_config(cfg)
    chain = PeriodChain(params, cfg, model)
    rep = Report(model=model)
    for t in days:
        res = chain.add(t.day)          # the pack walks every day
        off = float(res.actual_cost) - t.net
        if abs(off) > max(TRUTH_TOL_ABS, TRUTH_TOL_SHARE * t.moved):
            rep.excluded.append({"date": t.day.date, "why": "bill ≠ meter",
                                 "bill": round(t.net, 2),
                                 "meter": round(float(res.actual_cost), 2)})
            continue
        if t.day.counters_disagree:
            rep.excluded.append({"date": t.day.date,
                                 "why": "a counter jumped"})
            continue
        rep.total.add(t, res)
        for typ in day_types(t.day.tags):
            rep.by_type[typ].add(t, res)
        rep.by_month[t.day.date[:7]].add(t, res)
        rep.rows.append({
            "date": t.day.date, "tags": list(t.day.tags),
            "actual": round(t.net, 2), "simulated": round(res.simulated_cost, 2),
            "diff": round(res.simulated_cost - t.net, 2),
            "reprice": round(res.actual_cost - t.net, 2),
            "end_soc_pct": res.end_soc_pct,
        })
    rep.stored_energy_value = chain.finish()
    rep.stored_energy_kwh = chain.stored_energy_kwh
    return rep


def _fmt(name: str, b: Bucket) -> str:
    return (f"{name:<10} {b.days:>4}  actual {b.actual:>8.2f}  sim "
            f"{b.simulated:>8.2f}  moved {b.moved:>8.2f}  err "
            f"{b.error_pct:>5.1f} %  import {b.import_kwh_actual:>7.1f}→"
            f"{b.import_kwh_sim:<7.1f} export {b.export_kwh_actual:>7.1f}→"
            f"{b.export_kwh_sim:<7.1f}")


def print_report(rep: Report, per_day: bool = False, out=sys.stdout) -> None:
    if per_day:
        for r in rep.rows:
            print(f"{r['date']} {','.join(r['tags']):<16} actual "
                  f"{r['actual']:>6.2f} sim {r['simulated']:>6.2f} diff "
                  f"{r['diff']:>6.2f} reprice {r['reprice']:>5.2f} soc "
                  f"{r['end_soc_pct']}", file=out)
    print(f"model: {rep.model}", file=out)
    print(_fmt("TOTAL", rep.total), file=out)
    for k, b in sorted(rep.by_type.items()):
        print(_fmt(k, b), file=out)
    for k, b in sorted(rep.by_month.items()):
        print(_fmt(k, b), file=out)
    if rep.excluded:
        why = defaultdict(int)
        for e in rep.excluded:
            why[e["why"]] += 1
        print("left out: " + ", ".join(f"{n} day(s) {w}"
                                       for w, n in sorted(why.items())),
              file=out)
    print(f"stored energy at the end: {rep.stored_energy_kwh:+.2f} kWh = "
          f"{rep.stored_energy_value:+.2f} (not in the error)", file=out)
    print(f"gate (total ≤ {GATE_TOTAL_PCT} %, every type ≤ {GATE_TYPE_PCT} %): "
          f"{'MET' if rep.gate_met else 'NOT MET'} — total "
          f"{rep.total.error_pct:.1f} %, worst type {rep.worst_type:.1f} %",
          file=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("fixture")
    ap.add_argument("--config")
    ap.add_argument("--model", default=MODEL_DECISIONS,
                    choices=(MODEL_DECISIONS, MODEL_BALANCE, "both"))
    ap.add_argument("--days", type=int)
    ap.add_argument("--per-day", action="store_true")
    ap.add_argument("--capacity", type=float)
    ap.add_argument("--battery-mode")
    ap.add_argument("--ev-mode")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    with open(args.fixture, encoding="utf-8") as fh:
        fixture = json.load(fh)
    cfg = dict(fixture.get("config") or {})
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    days = load_days(fixture, last=args.days)
    models = ((MODEL_DECISIONS, MODEL_BALANCE) if args.model == "both"
              else (args.model,))
    ok = True
    for model in models:
        params = SimParams.from_config(cfg)
        changes = {}
        if args.capacity:
            changes["capacity_kwh"] = args.capacity
        if args.battery_mode:
            changes["battery_mode"] = args.battery_mode
        if args.ev_mode:
            changes["ev_mode"] = args.ev_mode
        if changes:
            params = replace(params, **changes)
        rep = measure(days, cfg, model, params)
        if args.json:
            print(json.dumps(rep.as_dict()))
        else:
            print_report(rep, per_day=args.per_day)
        ok = ok and rep.gate_met
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


