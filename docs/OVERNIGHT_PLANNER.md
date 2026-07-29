# The Overnight Joint Planner — how SEM plans the night (#638)

> **Status: shadow mode.** The planner computes and logs *tonight's plan*
> every night, but does not actuate anything yet. Every real decision is
> still made by SEM's reactive layer. See [Where to see it](#where-to-see-it).

## The problem in one picture

"All charged by morning" is a **joint** problem. Before the planner, four
independent parts of SEM each decided the night alone, each with a private
view of it:

```
  EV tariff planner ──── "cheapest hours for MY charge floor"     ─┐
  battery scheduler ──── "cheapest hours for MY pre-charge"        ├─ all pick the same
  cheap-hours loads ──── "run when the price level says cheap"     │  cheap hour, collide,
  Tier-2 loads ────────── "run off the battery at night"          ─┘  peak shed picks a loser
```

None of them knew what the *others* were taking. None of them knew what the
**house itself** would take from the battery overnight. And nothing could
answer the question that matters at bedtime: *does everything fit tonight —
and if not, what gives?*

The joint planner closes that with one shared structure — the **Night
Ledger** — and one deliberately simple rule set. It is a greedy
priority-packer, **not an optimizer**: pure, deterministic, and every
allocation explains itself in one line.

## Step 1 — Build the Night Ledger

One table, one row per market slot (hourly on a static HT/NT tariff, 15-min
where the market is 15-min — slots follow the tariff). Every column comes
from data SEM already has:

```
        │ price   │ level  │ home draw  │ battery SOC │ grid headroom
  slot  │ (tariff │ (cheap │ (learned   │ (trajectory,│ (peak limit − home-on-
        │  curve) │  gate) │  weekday-  │  see step 2)│  grid − already
        │         │        │  hour      │             │  committed draws)
        │         │        │  profile)  │             │
  ──────┼─────────┼────────┼────────────┼─────────────┼───────────────
  22:00 │  0.36   │  no    │   450 W    │  11.6 kWh   │   6000 W
  23:00 │  0.22   │  YES   │   420 W    │  11.1 kWh   │   6000 W
  00:00 │  0.22   │  YES   │   400 W    │  10.7 kWh   │   6000 W
   ...  │   ...   │  ...   │    ...     │     ...     │    ...
  06:00 │  0.22   │  YES   │   500 W    │   8.3 kWh   │   6000 W
```

- **price** — the tariff provider's curve. Slots the day-ahead market has
  not published yet are honestly *unpriced*: price-driven demands pack
  around them, and the plan re-derives the moment the series lands.
- **level** — whether the provider classifies that hour as *cheap*. This is
  the same gate that decides whether a cheap-hours load actually runs, so
  the plan can never schedule a run that execution would refuse.
- **home draw** — the learned consumption profile: one bin per (weekday,
  hour), trained from this house's own history, with sane fallbacks while
  it is still learning.
- **battery SOC / grid headroom** — computed by the trajectory walk, next.

## Step 2 — The trajectory walk (the house comes first)

The home is the battery's first customer, and nobody schedules it — the
hybrid inverter's self-consumption serves the house from the battery
automatically. So the planner **simulates** it, hour by hour:

```
  battery
  energy      11.6 ●
  (kWh)             ●───●              home draws ~0.4 kWh each hour
                          ●───●
              floor ─────────────●━━━━━━━━━━━  ← max( reserve SOC,
                                  ▲              the scheduler's sunrise target )
                                  │
                        THE TAKEOVER HOUR: the battery reaches its floor here.
                        From this hour on the house draws from the GRID METER —
                        so this hour's (and every later hour's) grid headroom
                        shrinks by the home draw.
```

Two hardware limits guard the walk, both from the Battery section of the
configuration card:

- **Battery total discharge limit** — a *shared, instantaneous* bottleneck:
  the home's battery draw plus every planned battery-fed load must never
  sum past it at any moment. 500 W house + a 1 kW pump + a second 1 kW pump
  is 2.5 kW *while they overlap* — the planner packs the second pump into a
  later hour, or reports that it doesn't fit.
- **The sunrise floor** — whatever tomorrow morning needs (the reserve SOC,
  or the battery scheduler's target if that is higher) is untouchable. The
  plan never spends the morning's energy tonight.

If the battery comfortably outlasts the night (plenty above the floor, a
modest house), the takeover never happens — the plan says so.

## Step 3 — Pack the demands, in the drag order

Every "must-have by morning" becomes a **demand**. There are four kinds,
and each carries its own rules:

```
  DEMAND                                SOURCE     RULES
  ───────────────────────────────────   ────────   ──────────────────────────────
  battery pre-charge (the scheduler's)  GRID       cheapest priced slots
  EV floor  "at least X by Charge-by"   GRID       cheapest priced slots BEFORE
                                                   the deadline; never below the
                                                   charger's min amps; NEVER from
                                                   the home battery
  cheap-hours load (runtime deficit)    GRID       only LEVEL-cheap slots; blocks
                                                   respect the anti-cycle minimum
                                                   run / minimum pause
  Tier-2 load ("finish overnight from   BATTERY    earliest slots, price-blind,
  battery", runtime deficit)                       free — spends only what the
                                                   trajectory leaves above the
                                                   floor AFTER the house
```

They pack **in the priority order of the Control-tab list** — the same one
drag list that governs the daytime surplus walk and peak shedding. The
highest-priority demand takes the cheapest eligible hours; every next
demand packs into what remains. Devices in *Off* or *Peak-only* mode are
never planned — the plan mirrors exactly what execution would do.

The coupling is the heart of it: **every allocation changes the world the
next allocation sees.** A grid demand consumes that slot's headroom. A
battery-fed load drains the trajectory — which is re-walked, possibly
pulling the takeover hour earlier and shrinking the grid headroom of every
later hour.

```
  22:00  23:00  00:00  01:00  02:00  03:00  04:00  05:00  06:00
  ───────────────────────────────────────────────────────────────
  home    ████████ on battery ████████████████░░░░░░░░░░░░░░░░░░  ░ = on grid
  EV                    ▓▓▓▓▓▓▓▓▓▓▓▓▓                             (after takeover)
  pump                                ▒▒▒▒▒▒
  heizb.  ░░░░░░ (from battery, earliest, free)

  In every column: grid draws sum ≤ the peak limit,
                   battery draws sum ≤ the discharge limit.
```

## Step 4 — The answer

The output is a **report**, one line per demand — the thing you can read at
22:00 instead of discovering at 06:30:

```
OVERNIGHT-PLAN (shadow): battery carries home until 03:00 — the grid takes over from there
OVERNIGHT-PLAN (shadow): ev:ev_charger:  fits — 8.0 kWh planned, est 2.70
OVERNIGHT-PLAN (shadow): load:pump:      fits — 3.0 kWh planned, est 0.31
OVERNIGHT-PLAN (shadow): load:heizband:  YIELDS 1.1 kWh — 2.0/3.1 kWh fits above the floor
```

**A yield is a report, not a decision.** The planner only ever moves *when*
a floor is filled and *how fast* — never *whether*. Every guarantee (the
EV's deadline forcing, the battery reserve gates, anti-cycling) stays with
SEM's reactive layer, which keeps making all real decisions. A wrong plan
can cost accuracy in the report; it cannot cost a cold car or a drained
battery.

## When it runs

```
  once per NIGHT — the first cycle inside the night window,
  retried until the world is ready (devices registered AND
  the battery SOC actually reporting):
        │
        ▼
  build the ledger  →  pack  →  log the answer + stash it
        │
        ▼
  re-plan triggers: day-ahead price update · SOC drift ±5% · EV plug/unplug
```

"Once per night" survives restarts and midnight: a restart at 00:48 still
owes the rest of the night a plan and gets one.

## Where to see it

- **Logs** — `OVERNIGHT-PLAN (shadow)` lines: the summary at INFO, one line
  per allocation at DEBUG. Never silent: even "no overnight demands
  tonight" is logged, with the counts that explain it.
- **On demand** — the `solar_energy_management.diagnose` service response
  carries `overnight_plan_shadow`: the timestamp, fits/yields summary, the
  takeover hour, and every allocation line of the most recent plan.

## What accuracy depends on

The plan is only as good as its inputs — all of which SEM maintains anyway:

- a load's power is its **calibrated** rated draw (learned from the real
  consumption, not the configured guess);
- the home curve is the learned weekday-hour profile, falling back to the
  rolling average while training;
- deviations don't break anything — they trigger a re-plan, and the
  reactive layer never depended on the plan in the first place.

## The road ahead (the verification ladder)

1. **Baseline** — nightly measurements of the unchanged reactive system:
   grid energy, cost, every floor met.
2. **Corpus** — the pure packing scenarios in
   `tests/test_638_overnight_planner.py`.
3. **Shadow** *(current)* — the plan computed and logged next to reality
   every night, compared each morning.
4. **Actuation** — only after the shadow proves itself, the plan's output
   feeds the *existing* signals (the EV's night amps, the loads' window
   gates). The reconcilers do not change.
