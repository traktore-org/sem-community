# The Joint Energy Planner — how SEM plans the energy day (#638)

> **Status: actuation on by default.** The planner computes *the plan for
> the whole energy day* — daylight and the coming night in one ledger — and
> the plan's windows drive the *existing* night signals: see
> [Actuation](#actuation-g4) and [Where to see it](#where-to-see-it).
> `switch.sem_energy_plan_actuation` is the kill-switch: turn it **off** and
> the planner goes back to pure shadow, every real decision made by SEM's
> reactive layer, exactly as before this build.
>
> Upgrading from an older SEM? The upgrade writes that choice down for you
> (it is on) and posts one notification saying so — nothing switches on
> silently, and an install that had already turned it off keeps it off.

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

## Guidance vs. accounting

Two clocks run in SEM, and keeping them apart is what makes the design
easy to reason about:

- **The arbiter** (the reactive layer — surplus controller, EV decide
  chain, battery pipeline, peak manager) runs on the **now-clock**: every
  ten seconds it divides what is actually flowing — who gets this watt,
  who sheds for the peak. The energy-flow chart on the dashboard (the
  Sankey) is the arbiter's outcome.
- **The planner** runs on the **day-clock**: it moves the *flexible*
  needs (EV floors, load runtimes, comfort banking, battery pre-charge)
  to the right place in time, so that when the arbiter does its
  ten-second triage, the cheap or free source happens to be there.

Inside the planner, three parts with one-word jobs: the **ledger** (the
books — an honest hour-by-hour model of prices, home draw, sun, the
battery's trajectory, peak headroom), the **plan** (a timetable derived
by packing demands into the books), and the **verdict** (the small,
fail-open signals the arbiter consults — the only part that touches
behavior). In one line each: *the Sankey is what happened, the ledger is
what we expect, the plan is what we intend, the verdict is what we dare
enforce.*

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
ENERGY-PLAN (shadow): battery carries home until 03:00 — the grid takes over from there
ENERGY-PLAN (shadow): ev:ev_charger:  fits — 8.0 kWh planned, est 2.70
ENERGY-PLAN (shadow): load:pump:      fits — 3.0 kWh planned, est 0.31
ENERGY-PLAN (shadow): load:heizband:  YIELDS 1.1 kWh — 2.0/3.1 kWh fits above the floor
```

**A yield is a report, not a decision.** The planner only ever moves *when*
a floor is filled and *how fast* — never *whether*. Every guarantee (the
EV's deadline forcing, the battery reserve gates, anti-cycling) stays with
SEM's reactive layer, which keeps making all real decisions. A wrong plan
can cost accuracy in the report; it cannot cost a cold car or a drained
battery.

## When it runs

```
  once per ENERGY DAY (night-end to night-end) — retried until the
  world is ready (devices registered AND the battery SOC reporting):
        │
        ▼
  build the ledger (day + night)  →  pack  →  log + stash + publish
        │
        ▼
  re-plan whenever the ASK or the SUPPLY honestly changes:
    EV plug/unplug · a charge target, deadline or mode ·
    a load's runtime deficit · a comfort ask appearing or moving ·
    the day-ahead price curve landing · the solar forecast revising
```

One plan per energy day survives restarts and midnight: a restart at
00:48 still owes the rest of the horizon a plan and gets one. Every
re-plan says why it exists — the sensor's `replan_cause` attribute reads
`initial` for the day's first answer and `ask changed` for a re-stamp.
Jitter deliberately does **not** re-plan: targets are compared in
0.1-kWh steps, load deficits in 6-minute steps, comfort asks in
0.5-kWh/30-minute steps, and prices to the cent — a thermometer drifting
is time passing, not the ask changing.

The solar side is compared as **what the plan actually spends**: the hours
still ahead today, and tomorrow's day (the sunrise floor, and the room
arbitrage may buy into). Each is anchored with a 3-kWh deadband, and the
day burning down is explained by your **measured production** — as long as
the remaining forecast falls at roughly the rate the panels deliver, it is
the day going to plan and the night is not re-planned. Clouds arriving, or
the provider revising the curve, opens a gap against that expectation and
re-plans once. A retrospective correction — the dampening re-pricing hours
that have already been produced — deliberately changes nothing: those
hours are spent, and the plan never reads them.

An **unplug counts only once it is confirmed**. A UDP-polled charger drops a
poll now and then and reads "no car" for one cycle with the cable still in;
that is a missed poll, not a departure, and it must not re-plan the night —
so a disconnect is believed only after three consecutive cycles say so, and
never during the first two minutes after a restart, when a sensor that has
not spoken yet is not a sensor saying "no". A **plug-in**, by contrast, is
acted on immediately: connecting a car re-stamps within the cycle.

That confirmation happens **once per cycle, where the plug is read** — not
in each place that asks. The plan, the charging state, each charger's own
decision, the session counters and SEM's own `connected` entities are all
answered from the same confirmed reading, so they cannot contradict each
other about the same car in the same update. It is why a blip can no longer
drop the car from the night's plan, end a running session, or flip the
charging state to *System ready* with the cable plugged in.

## The energy-day horizon

The plan always covers **now → the coming night's end** (the
sunrise-bounded night end you configure — the same boundary every night
source runs on). Stamped during the day, it plans the afternoon *and*
the night jointly; sunrise opens the next period. Everything is
sun-anchored, so seasons need no configuration: a December day simply
contributes a few short daylight hours and the night dominates.

Daylight hours enter the ledger in two honest shapes:

- **expected-surplus hours** — the solar forecast (shaped over the real
  day length) exceeds the expected home draw. These are **free but
  finite**: price 0, capped at the expected surplus power. The house
  runs on the same sun, so it costs the ledger nothing there.
- **deficit hours** — the house draws the difference, priced by the
  *same* tariff provider the night uses (there is deliberately no
  second price path), and walked through the normal
  battery-then-meter trajectory.

With no solar forecast installed the day degrades to plain priced
hours — the horizon still spans, nothing free is invented.

## Comfort banking

A room with a [comfort band](#actuation-g4) (the #705 goal fields on a
climate or heater device) is thermal mass — a battery made of air. The
planner learns two rates from readings SEM already takes: how fast the
room drifts toward its limit while the device is **off**, and how fast
it recovers while **on**. Together they turn comfort into a
deadline-shaped demand, exactly like tonight's EV floor:

> *"the room hits its limit at 17:20 — banking back to target costs
> 0.6 kWh — place that run into a free window before then."*

The band rides the thermostat's **own live setpoint** where one exists:
your schedule, presence logic or the unit's native pre-cool moves the
whole band, and the values you typed contribute only their offsets.

Two guarantees: a comfort run in the plan packs **only into free-sun or
cheap-level hours** — banking is opportunism, never plain-rate paid
power (a real breach is served immediately by the band's FORCED tier,
on your own source-axis terms); and every doubt (no drift model yet, a
silent thermometer, a contradictory reading) produces **no demand**
rather than a guessed one.

## The arbitrage advisor

The advisor answers one question on every plan: *would buying cheap
energy into the battery and delivering it in an expensive hour actually
pay?* It reads the **same books** as everything else — the price curve
across both horizons, the battery's room, the charge/discharge caps,
the home's hour-by-hour grid draw, tomorrow's forecast — and publishes
its verdict **with the numbers** on the plan card and the sensor's
`arbitrage` attribute.

The honesty rules, each one a test:

- the spread must survive the **round trip and the wear**
  (`η·sell − buy − wear` per bought kWh, using your configured
  round-trip efficiency);
- energy never flows backwards in time — deliver only after buying;
- avoided import needs an import to avoid: delivery counts only in
  hours where the house would actually draw from the grid;
- **never grid-charge what tomorrow's sun fills free** — the forecast
  caps the buying room;
- a free surplus hour is the sun banking itself, not a buy;
- unpriced hours are not a market.

**Advice only.** The advisor commands nothing — the battery's command
wire stays exactly as configured, and a typical answer on a healthy
sunny-season system is the honest *"best spread does not pay"*. Its
deeper job is auditing: it is the one reader of *every* page of the
ledger, so if the books are wrong anywhere, an economically absurd
advice is the first visible symptom.

## Where to see it

- **On the dashboard** — the **Energy Plan** card on the *Control* tab
  (`custom:sem-energy-plan-card`; the pre-rename
  `custom:sem-overnight-plan-card` tag still works as an alias until the
  next `generate_dashboard` rewrites the YAML). One row per demand over a shared hour
  axis: where each block is planned, which hours are cheap, and the battery's
  own row shading teal while it covers the house and steel-blue after the
  **takeover**. A `shadow` chip and a footer line say plainly that SEM is not
  acting on it yet — with actuation switched on they turn into a green
  `active` chip and an "the plan's windows steer tonight" footer. The card
  **self-hides** until a plan has been stamped, so it costs nothing during
  the day.
  Comfort banking runs appear as their own teal thermometer rows; an
  arbitrage line under the strip carries the advisor's verdict with its
  numbers — hover any row or the line for the full story, and the small
  book icons deep-link straight into this document.
- **As an entity** — `sensor.sem_energy_plan` (diagnostic; renamed from
  `sensor.sem_energy_plan` when the horizon grew past the night — the
  old entity is cleaned from the registry automatically on restart). Its state is
  the verdict word `fits` / `yields` / `idle` / `pending`; the plan itself
  rides as attributes (`demands`, `slots`, `blocks`, `takeover`,
  `total_cost`, `computed_at`, `replan_cause`, `arbitrage`), which is what
  the card reads. Useful for
  your own template sensors or an automation that pings you when a night
  does *not* fit. Those attributes are a *projection*: the log prose and the
  ledger's internal columns stay out, and back-to-back allocations are merged
  into runs, so the payload stays under the recorder's 16 KiB attribute limit
  (above it HA stores **no** attributes at all). On an exceptionally large
  night the timeline alone is dropped — `timeline_omitted: true`, the card
  falls back to the demand list and says so. `diagnose` always has the full
  detail.
- **Logs** — `ENERGY-PLAN (shadow)` lines (`(active)` while actuation is
  on): the summary at INFO, one line per allocation at DEBUG. Never silent:
  even "no overnight demands tonight" is logged, with the counts that
  explain it.
- **On demand** — the `solar_energy_management.diagnose` service response
  carries `energy_plan_shadow`: the timestamp, fits/yields summary, the
  takeover hour, and every allocation line of the most recent plan.

## What accuracy depends on

The plan is only as good as its inputs — all of which SEM maintains anyway:

- a load's power is its **calibrated** rated draw (learned from the real
  consumption, not the configured guess);
- the home curve is the learned weekday-hour profile, falling back to the
  rolling average while training;
- deviations don't break anything — they trigger a re-plan, and the
  reactive layer never depended on the plan in the first place.

## Actuation (G4)

Actuation does **not** add a control path — it feeds the plan's windows
into the two signal families the reactive layer already consumes
(`coordinator/energy_plan_actuation.py`):

- **EV** — inside one of its planned blocks, the charger gets an amps
  *floor* derived from the block's planned power (threaded through the
  existing `deadline_amps` signal, so the peak governor and the charger's
  own [min, max] still apply on top). Outside its blocks it *waits*
  (the existing tariff-wait state) — but **only while the remaining blocks
  can still deliver the remaining floor**.
- **Loads** — the cheap-hours and Tier-2 overnight starts get one extra
  AND-gate: don't start now if the plan placed this load's blocks
  elsewhere tonight. The gate never *creates* a run — the deficit, the
  price level, the reserve SOC and the anti-cycle timers keep deciding
  *whether*; the plan only narrows *when*.

The trust rule, per demand, fail-open to pre-G4 behaviour: the switch is
on, tonight's plan is stamped and fresh, `now` is inside the plan's own
night span, and **this demand's verdict is `fits`**. A `yields`/`partial`
demand, a stale stamp, a malformed block — any doubt at all — and that
demand behaves exactly as if the planner did not exist. The reactive
guarantees stay senior even when covered: a forcing deadline or an
unreachable floor is never gated, and a peak shed still wins over any
planned window.

Flip it with `switch.sem_energy_plan_actuation` (Config category on the SEM
device; persisted across restarts, default **on** since the one-gate build —
see the next section). The card's chip, the sensor's `actuation` attribute
and the log tag all reflect the live state.

## The one gate (the unification)

Since the one-gate build there is **no second window-picker anywhere**:

- the EV's private cheap-window selection (`find_cheapest_hours` inside
  `ev_control`) is deleted — the plan's blocks are the only WHEN for the
  night, and a CI ratchet (`tests/test_638_one_selector.py`) fails on any
  new caller;
- the battery scheduler keeps the WHAT (deficit, break-even economics,
  target SOC, charge power) and the plan owns the WHEN — `decide_battery`
  force-charges only inside the plan's `battery` block;
- comfort banking actuates through the same gate (`comfort:` demands merge
  with `load:` demands per device);
- the arbitrage sell blocks actuate through the same trust rules — wired,
  but every default keeps that path dormant.

**Fail-open directions, per family** (each deliberate, each named in the
`#638 coverage` log line and on the card's "reactive" chip):

| Demand | Plan does not cover → | Why this direction |
|---|---|---|
| EV | **charge** at the deadline/top-up floor | the floor is a guarantee; an expensive night is a visible bug, a missed floor is a stranded car |
| Battery pre-charge | **no force-charge** | pre-charge is optimization, not guarantee |
| Loads | their own reactive rules | deficit/price/reserve gates keep deciding whether |
| Comfort banking | **no banking run** | banking has no reactive run reason — it exists only as a planned block |
| Arbitrage sell | **no sell** | selling is opt-in twice (mode + toggle) and plan-timed |

Reactive gates that are NOT window selection stay live and senior:
the solar_plus_cheap daytime price pause, the battery's negative-price
override, peak shed, reserve SOC, anti-cycle timers, deadline forcing.

## How to read tonight's plan

The **Energy Plan** card (Control tab) is the one answer:

- **A row per demand** — the window strip shows *when*, the tooltip shows
  the blocks with power and price (*why this window: it was the cheapest
  the constraints allowed*), and the kWh cell shows *how much* of the need
  fits. A yielding row says why in the packer's own words.
- **Chips** — while actuation is on, each row carries its live state:
  steering now, waiting for its block, done — or **"reactive — why"**
  when the plan does not cover the demand right now (no plan yet, plan
  outdated, could not fit it, nothing to schedule tonight, actuation off).
  Reactive is visible, never silent.
- **A quiet night says so.** When nothing needs the night — battery full,
  EV at target, no load asking — the plan is stamped with an empty
  *schedule* on purpose and every row reads *nothing to schedule tonight*.
  That is an answer, not a failure; "plan unreadable" is reserved for a
  plan that really did break trust (a malformed block, an unparsable
  payload). Everything that is not scheduling still appears: the hour
  strip with tonight's prices, the battery's expected trajectory, the
  self-consumption share and the arbitrage verdict. A night with nothing
  to do is exactly the night those numbers are worth reading.
- **"Not scheduled tonight"** — every device the collector deliberately
  left out, with its why. Chargers: the charge mode excludes night
  charging, no car is connected, the car is already full. Loads: the
  device's mode excludes surplus control, no runtime is left to make up,
  it is already at its target, it is a daytime-only device, or SEM has no
  measured power for it yet. An absent row is never a mystery.
- **"Already full" needs two witnesses.** A car counts as full only when
  SEM's own charge accounting says so *and* the charger's meter agrees —
  a car drawing more than its charger's handshake current is never
  answered as full, whatever the accounting says mid-charge. Both the
  demand list and the re-plan trigger ask the same accessor, so the night
  cannot flip between a plan with the car and one without it.
- **The kill-switch** — `switch.sem_energy_plan_actuation` turns the plan's
  authority off entirely; every device then runs on its reactive rules
  and the card says so. Every row flips to *actuation off* within one
  cycle: the chips are evaluated fresh on each publish through the same
  single evaluator the log line uses, so the card can never show a
  leftover verdict from before the switch was flipped.

## What the record shows (#755)

A plan that is never checked is a guess with a chart. So every night the
planner writes down a third number beside the two it already had:

| The number | Where it comes from |
|---|---|
| **asked** | what the device said it needed |
| **planned** | what the packer promised it |
| **actual** | what it really drew, integrated across the night |

The night is one unit — the recorder accumulates straight through midnight
and lives in the durable store, so a reboot at 02:00 does not halve it. It
also keeps the two splits that answer *"did the plan actually drive this?"*:
energy **inside** the planned block vs. outside, and time **covered** by the
gate vs. uncovered.

**Only measured nights teach.** If any sample was an estimate rather than a
reading, the night is marked untrainable. A demand with no samples at all is
not "zero" — it is silence. A hole in the record (restart, a sensor that went
away) is refused, never integrated across. A guessed number must never end up
teaching a model that later makes decisions.

**Reading the morning line.** The card's *What the record shows* section says
one thing per demand:

- *still learning — N clean nights so far* — not enough evidence yet. It says
  so instead of guessing.
- *the ask matches what it uses* — nothing to change.
- *usually needs about X kWh of the Y kWh asked* — the demand consistently
  stops short of its ask. Lowering the ask frees the night for something else.
- *uses the full ask every night — it may need more* — it never got to stop on
  its own, so the true need is unknown but at least this much.

The last two are the whole trick. A night may only *lower* an ask if the
demand got its **full** grant and stopped by itself; a night that was cut
short by the plan (or that ran its ask dry) can only push a **floor** upward.
The suggestion is a high percentile of the teaching nights, not an average —
interruptions only ever push a night's energy down, so an average would drift
low forever.

**SEM never applies these itself.** They are recommendations; you change the
target, or you don't.

**The solar line** compares the share of your own solar the plan predicted
you would keep against what you actually kept — the reason the ledger now
prices a surplus hour at what feeding it in would have earned, instead of at
zero. Free-by-definition solar always won; priced solar has to win on the
numbers, which lets a genuinely cheaper night hour beat it. Without a feed-in
tariff the rate is zero and the sun really is free.

## The road ahead (the verification ladder)

1. **Baseline** — nightly measurements of the unchanged reactive system:
   grid energy, cost, every floor met. *(done — the number to beat)*
2. **Corpus** — the pure packing scenarios in
   `tests/test_638_energy_planner.py`. *(done)*
3. **Shadow** — the plan computed and logged next to reality
   every night, compared each morning. *(done — six findings fixed)*
4. **Actuation** *(current)* — the plan's output feeds the *existing*
   signals (the EV's night amps, the loads' window gates), behind
   `switch.sem_energy_plan_actuation`, on by default since the one-gate
   build (with the selectors retired, off would mean *no* cheap-window
   timing at all). The reconcilers do not change. Soaking: shadow-verify
   nights with the switch off, then flip it and compare the same nights
   acted.
