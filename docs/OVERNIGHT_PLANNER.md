# The Overnight Joint Planner (#638)

> **Status: shadow mode.** The planner computes and logs *tonight's plan* next
> to the reactive system every night, but does not actuate anything yet. Look
> for `OVERNIGHT-PLAN (shadow)` lines at the battery scheduler's evaluation
> (21:00 and on replans).

"All charged by morning" is a **joint** problem: several must-haves (the EV's
*At least* floor with its *Charge by* deadline, each load's minimum daily
runtime, the home battery's pre-charge), one price curve, one peak cap, one
priority order. The reactive planners each grab "the cheapest hours" on their
own — they all collide on the same slot and the peak posture sheds the loser.
The joint planner packs them **together** instead, and can answer at 22:00:
*everything fits* — or *X yields, by this much*.

It is deliberately a **greedy priority-packer, not an optimizer**: pure,
deterministic, every allocation explainable in one log line.

## Priority: the one drag list

The packer uses **exactly the device order you drag on the Control tab**
(the one priority list, #576) — the same order the daytime surplus walk and
peak shedding use. No separate knob:

- a charger's slot comes from the same accessor `decide()` uses (a drag
  takes effect immediately),
- a load uses its list position,
- the home battery uses its drag-set slot in the same list.

The highest-priority device packs first and therefore gets the cheapest
eligible hours; everyone else packs into what remains.

## Where the energy comes from matters: grid vs. battery

A demand is constrained by **its source**, not by a global rule:

| Source | Peak cap | Price curve | Constraint |
|---|---|---|---|
| **Grid** (EV floor, cheap-hours loads, battery pre-charge) | counts against the slot's grid headroom | pays the slot price | `peak_limit − expected overnight home draw` per slot |
| **Battery** (Tier-2 "finish overnight from battery" loads) | none — no grid meter involved | free in the plan (the stored energy was paid for when it was charged) | the shared **battery budget**: usable kWh above the reserve SOC |

Standing rule: the **EV never charges from the home battery** — EV floors are
always grid demands.

Battery-sourced loads pack into the *earliest* eligible hours (time-ordered —
price is irrelevant to them); grid demands pack into the *cheapest*.

## Accuracy: the plan is as good as the power model

- A load's demand uses its **calibrated rated power** — SEM learns the real
  draw from the power sensor and snaps the rated value to it. A pool pump
  configured at 1 kW but drawing 600 W plans at 600 W after calibration.
- The EV demand uses the charger's configured min/max amps × phases ×
  voltage; a car that draws less simply finishes a bit later.
- **Deviations replan** — the planner recomputes on the scheduler's replan
  triggers (price update, floor change, big deviation), so a wrong estimate
  degrades to a slightly different next plan, never a stuck one.

## Worked examples

Six-hour night, hourly prices, one 4-kW EV floor (min 1.4 kW), a 2-kWh
cheap-hours heater (2 kW, binary), a 3-kWh battery pre-charge.

### With a peak cap (6 kW limit, ~500 W home → 5.5 kW usable per hour)

```
prices  22h:0.28  23h:0.24  00h:0.11  01h:0.10  02h:0.13  03h:0.26

ev:      4000 W 01:00–02:00 @ 0.10  (slot #1 cheapest, cap left 1500 W)
ev:      4000 W 00:00–01:00 @ 0.11  (slot #2 cheapest, cap left 1500 W)
heater:  — skips 00h/01h: only 1.5 kW cap left, below its 2 kW floor —
heater:  2000 W 02:00–03:00 @ 0.13  (slot #3 cheapest, cap left 3500 W)
battery: 1500 W 01:00–02:00 @ 0.10  (fills the remaining cap)
battery: 1500 W 00:00–01:00 @ 0.11  …
```

The EV (highest priority) owns the two cheapest hours. The heater cannot
squeeze into the 1.5 kW remainder (a binary load is all-or-nothing), so it
takes the third-cheapest hour — **and still fits**, where the reactive
planners would have collided at 01:00 and shed it. The battery, continuous
from 0 W, soaks up the leftover cap in the cheap hours.

### Without a peak cap (`peak_limit` unset)

There is no per-slot competition: every grid demand simply takes its
cheapest eligible hours, overlapping freely —

```
ev:      4000 W 01:00 + 00:00      (cheapest two)
heater:  2000 W 01:00              (same hour — no cap to share)
battery: 3000 W 01:00              (same hour)
```

That is exactly what the reactive planners already do today ("everyone at
02:00") — without a cap it is also *correct*, since nothing constrains
simultaneous draw. The plan's value here is the **report**: deadlines are
still checked, and an EV floor that cannot finish before *Charge by* even
using every remaining hour is flagged as yielding at 22:00 instead of being
discovered at 06:30.

### A Tier-2 battery load rides along free

Add a towel heater set to *Finish overnight from: Battery* (1 kWh left,
battery at 80% with a 30% reserve → ~5 kWh budget):

```
load:towel: 800 W 22:00–23:15 from battery (budget left 4.0 kWh)
```

It takes the **earliest** hour (price-blind), consumes **no grid cap** — the
EV/heater/battery packing above is completely unchanged — and spends the
battery budget, which is what actually limits it.

### The 22:00 answer

Every plan ends in one summary line per demand:

```
ev:ev_charger: fits — 8.0 kWh planned, est 0.86
heater:       fits — 2.0 kWh planned, est 0.26
battery:      YIELDS 1.2 kWh — only 1.8/3.0 kWh fits under the peak cap before its deadline
```

A *yield* is a **report, not a decision**: floors stay guarantees (the
reactive deadline forcing still runs), the planner only says out loud what
tonight cannot deliver under the cap — the part no other system ships.

## Verification ladder

1. **G1 — reactive baseline**: the unchanged system's night, logged.
2. **G2 — pure corpus**: `tests/test_638_overnight_planner.py` (packing,
   competition, yields, source axis, determinism).
3. **G3 — shadow** *(current)*: plan computed + logged next to the baseline
   every night; `tests/test_638_shadow_mode.py` pins that it can never break
   the cycle.
4. **G4 — actuation**: thread the plan into the existing signals
   (`deadline_amps` for the EV, window gating for loads) — reconcilers
   untouched. Gated on explicit sign-off after the shadow proves itself.
