#!/usr/bin/env python3
"""(#778) Replay an install's real nights through the spendable budget.

The forecast backfill gives an install enough evidence to START the budget.
This is the other half: enough to CHECK it. Every past night is a scenario
whose answer is already known — the pack was at some SOC at dusk, its own trace
says how low it went, and the sun either delivered the next day or did not. So
the budget can be asked what it WOULD have spent, and scored against what
actually happened.

    python3 scripts/backtest_budget.py --host root@10.10.20.150 \
        --key ~/.ssh/ha-prod.key --capacity 15 --floor 20

The headline is NOT average accuracy. Spending too little costs a little export
revenue and nobody notices; spending too much strands the house at its floor
before dawn on a night nobody can un-spend. So what is reported is how many
nights would have breached the floor BECAUSE of the budget.

Two modelling points that took a wrong answer each to find:

* the night's depletion comes from the pack's own SOC trace, never from
  integrated battery-to-home flow. A battery recharged mid-night moves more
  energy to the house than it ever held, so flow and depletion are different
  quantities and only one of them can breach a floor;
* every night is judged using ONLY evidence that existed before it. Scoring a
  night with knowledge of itself is a backtest that cannot fail.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

REMOTE = r'''
import sqlite3, datetime, json
db = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True, timeout=60)
c = db.cursor()

def series(sid, prefer_sum=False, prefer_min=False):
    c.execute('SELECT id FROM statistics_meta WHERE statistic_id=?', (sid,))
    r = c.fetchone()
    if not r:
        return {}
    c.execute('SELECT start_ts, state, mean, max, sum, min FROM statistics '
              'WHERE metadata_id=? ORDER BY start_ts', (r[0],))
    out = {}
    for t, st, mn, mx, sm, lo in c.fetchall():
        if prefer_sum and sm is not None:
            v = sm
        elif prefer_min and lo is not None:
            v = lo
        else:
            v = st if st is not None else (mn if mn is not None else mx)
        if v is None or t is None:
            continue
        try:
            ts = float(t)
        except (TypeError, ValueError):
            continue
        loc = (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
               + datetime.timedelta(hours=OFFSET)).replace(tzinfo=None)
        out[loc.isoformat()] = float(v)
    return out

print(json.dumps({k: series(v, prefer_sum=(k in SUM_KEYS), prefer_min=(k in MIN_KEYS))
                  for k, v in WANTED.items()}))
'''


def fetch(host, key, offset, wanted, sum_keys, min_keys):
    script = ("OFFSET = %d\nWANTED = %s\nSUM_KEYS = %s\nMIN_KEYS = %s\n"
              % (offset, json.dumps(wanted), json.dumps(sum_keys),
                 json.dumps(min_keys))) + REMOTE
    out = subprocess.run(
        ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=30", host, "python3 -"],
        input=script, capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise SystemExit("remote read failed: %s" % out.stderr[-400:])
    return json.loads(out.stdout)


def _parse(d):
    return {dt.datetime.fromisoformat(k): v for k, v in d.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--capacity", type=float, required=True)
    ap.add_argument("--floor", type=float, default=20.0)
    ap.add_argument("--tz-offset", type=int, default=2)
    ap.add_argument("--night-start", type=int, default=20)
    ap.add_argument("--night-end", type=int, default=7)
    ap.add_argument("--prefix", default="sensor.sem_")
    ap.add_argument("--need-pctile", type=float, default=None,
                    help="override the need-envelope percentile for this run")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    p = args.prefix
    data = fetch(args.host, args.key, args.tz_offset, {
        "soc": p + "battery_soc",
        "soc_min": p + "battery_soc",
        "drain": p + "flow_battery_to_home_energy",
        "fc": p + "forecast_tomorrow_kwh",
        "actual": p + "daily_solar_energy",
    }, sum_keys=["drain"], min_keys=["soc_min"])

    from custom_components.solar_energy_management.coordinator import (
        measured_capacity as mc,
    )
    from custom_components.solar_energy_management.coordinator.budget_backtest import (
        backtest, replay_night,
    )
    from custom_components.solar_energy_management.coordinator.forecast_ledger import (
        ForecastLedger,
    )
    from custom_components.solar_energy_management.coordinator.refill_estimate import (
        estimate_refill,
    )
    from custom_components.solar_energy_management.coordinator.spendable_budget import (
        spendable_budget,
    )

    if args.need_pctile is not None:
        mc.NEED_PERCENTILE = args.need_pctile

    soc = _parse(data.get("soc") or {})
    drain = _parse(data.get("drain") or {})
    soc_lo = _parse(data.get("soc_min") or {})
    fc = _parse(data.get("fc") or {})
    actual = _parse(data.get("actual") or {})

    def night_of(ts):
        if ts.hour >= args.night_start:
            return ts.date()
        if ts.hour < args.night_end:
            return ts.date() - dt.timedelta(days=1)
        return None

    nights = {}
    for ts, v in drain.items():
        n = night_of(ts)
        if n is not None:
            nights.setdefault(str(n), []).append((ts, v))

    low = {}
    for ts, v in soc_lo.items():
        n = night_of(ts)
        if n is None:
            continue
        k = str(n)
        if k not in low or v < low[k]:
            low[k] = v

    dusk = {str(ts.date()): v for ts, v in soc.items()
            if ts.hour == args.night_start - 1}

    actual_by_day = {}
    for ts, v in actual.items():
        d = str(ts.date())
        if d not in actual_by_day or v > actual_by_day[d]:
            actual_by_day[d] = v

    fc_by_night = {}
    for ts, v in fc.items():
        if ts.hour < args.night_start - 2:
            continue
        d = str(ts.date())
        if d not in fc_by_night or ts > fc_by_night[d][0]:
            fc_by_night[d] = (ts, v)

    seen, ledger, outcomes = [], ForecastLedger(), []
    skipped = {"no_drain": 0, "no_soc": 0, "short": 0}

    for night in sorted(nights):
        pts = sorted(nights[night])
        if len(pts) < 2:
            skipped["short"] += 1
            continue
        flow = pts[-1][1] - pts[0][1]
        soc_start = dusk.get(night)
        soc_low = low.get(night)
        if flow is None or flow <= 0:
            skipped["no_drain"] += 1
            continue
        if soc_start is None or soc_start <= 0 or soc_low is None:
            skipped["no_soc"] += 1
            continue

        need = mc.expected_overnight_need(seen)
        stored = args.capacity * soc_start / 100.0
        refill = estimate_refill(
            (fc_by_night.get(night) or (None, None))[1],
            house_tomorrow_kwh=need, committed_demand_kwh=0.0,
            pack_headroom_kwh=max(0.0, args.capacity - stored),
            trust=ledger.trust(1),
        )
        budget = spendable_budget(
            soc_pct=soc_start, usable_capacity_kwh=args.capacity,
            overnight_need_kwh=need, expected_refill_kwh=refill.refill_kwh,
            static_floor_pct=args.floor,
        )
        outcomes.append(replay_night(
            date=night, capacity_kwh=args.capacity, soc_start_pct=soc_start,
            spendable_kwh=budget.spendable_kwh,
            actual_drain_kwh=args.capacity * max(0.0, soc_start - soc_low) / 100.0,
            static_floor_pct=args.floor, soc_low_pct=soc_low,
        ))
        seen.append({"date": night, "drain_kwh": flow, "soc_start": soc_start,
                     "soc_morning": soc_low, "trainable": True})
        nxt = str(dt.date.fromisoformat(night) + dt.timedelta(days=1))
        f = (fc_by_night.get(night) or (None, None))[1]
        if f and nxt in actual_by_day:
            ledger.record(nxt, 1, f)
            ledger.settle(nxt, actual_by_day[nxt])

    rep = backtest(outcomes)
    spent = [o for o in outcomes if o.scorable and o.spendable_kwh > 0]
    rate = (100.0 * rep.breaches_caused / len(spent)) if spent else 0.0

    if args.quiet:
        print("  p%-4d nights=%-4d budget_nights=%-4d mean_spend=%.2f "
              "breaches=%-3d (%.0f%% of spending nights)"
              % ((args.need_pctile or mc.NEED_PERCENTILE) * 100, rep.nights,
                 len(spent), (sum(o.spendable_kwh for o in spent) / len(spent))
                 if spent else 0.0, rep.breaches_caused, rate))
        return 0

    print()
    print("  skipped: %d no drain, %d no SOC, %d too few readings"
          % (skipped["no_drain"], skipped["no_soc"], skipped["short"]))
    print("  nights scored        %s" % rep.nights)
    print("  verdict              %s" % rep.verdict)
    if rep.nights:
        print("  nights with a budget %d  (mean spend %.2f kWh)"
              % (len(spent), (sum(o.spendable_kwh for o in spent) / len(spent))
                 if spent else 0.0))
        print("  breaches CAUSED      %d  (%.0f%% of spending nights)"
              % (rep.breaches_caused, rate))
        print("  breaches (any cause) %d  — nights the pack went below the "
              "floor regardless" % rep.breaches_total)
        print("  floor-limited        %d  — the pack stopped AT its floor; the "
              "spend could only" % rep.floor_limited_nights)
        print("                          bring exhaustion forward, not deepen it")
        print()
        worst = sorted((o for o in outcomes if o.scorable and o.caused_by_budget),
                       key=lambda o: o.margin_kwh)[:5]
        if worst:
            print("  worst budget-caused breaches:")
            for o in worst:
                print("    %s  spend %5.2f  depletion %5.2f  margin %+6.2f"
                      % (o.date, o.spendable_kwh, o.actual_drain_kwh, o.margin_kwh))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
