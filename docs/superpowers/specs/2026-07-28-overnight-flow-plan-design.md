# The Night Ledger — overnight flow plan, the simple version (#638)

**Principle (Guido, 2026-07-28): we have all the info — make it simple to work.**
Every input already exists in SEM. The only gap: the four night planners
(EV tariff, battery scheduler, cheap-hours loads, Tier-2 loads) each consult a
private model. v1 adds ONE shared structure and NOTHING else.

## The one new structure: the Night Ledger

A pure, hour-by-hour table from now to the night window end. Every column is
an EXISTING accessor:

| Column | Source (exists today) |
|---|---|
| `price[t]` | tariff provider (`get_price_at`) |
| `home[t]` | 168-bin weekday-hour profile (`ConsumptionPredictor`), fallback chain intact |
| `soc[t]` | trajectory: live SOC; home draws it while above the floor — mirroring the inverter + SEM's own discharge-limit rules |
| sunrise floor | `max(reserve SOC, scheduler.decision.target_soc)` — public accessor, defined even when the scheduler is off |
| `grid_headroom[t]` | `peak_limit − home-on-grid[t] − committed[t]` — home lands on the meter in the hour `soc[t]` hits the floor (**the takeover**) |

## Packing (the existing philosophy, against the ledger)

Order = the one drag list (#576). Per demand kind, all rules as configured today:

- **EV floors** — grid only (standing rule), price-sorted slots before the
  deadline, min-amps floor, within `grid_headroom[t]` (the #630 formula).
- **Cheap-hours loads** — grid, price-sorted, block length ≥ min-run and gaps
  ≥ min-pause (#688 anti-cycle: a 10-min allocation would physically run 30).
- **Tier-2 loads** — battery, time-ordered; budget = what the trajectory
  leaves above the sunrise floor AFTER home's remaining night draw.
- **Battery pre-charge** — grid (the scheduler's own decision), raises `soc[t]`.
- **Report** — one line per demand at 22:00: *fits* / *yields n kWh before its
  deadline*. Floors move WHEN, never WHETHER; the reactive layer stays the
  guarantee.

## Replans

The scheduler's existing triggers (price fingerprint, SOC drift ±5%, EV
connect/disconnect) re-derive the ledger. Replan hysteresis: only shift an
allocation if a floor is at risk or the saving is material (the EV delta-guard
discipline, generalized).

## The simplicity contract — deliberately NOT in v1

- No source *choice*: policies stay as configured; EV never battery-funded.
- No optimizer — greedy one-list, deterministic, explainable, ~one file.
- No new knobs, no new learning, no new actuation paths.
- Legionella, VPP events, vacation mode: stay reactive overrides; the plan
  recomputes when they fire (they are replan causes, not plan inputs).
- No hourly price archive: the baseline metric is nightly grid kWh × the
  night's mean import rate + floors-met (computable from today's counters);
  exact hourly costing is a later follow-up.

## Verification ladder — in order this time

1. **G1** — baseline nights on clean beta.27: nightly grid kWh, mean-rate
   cost, every floor met y/n. The number to beat.
2. **G2** — extend the pure packer to the ledger (corpus revised consciously;
   anti-cycle block quantization added).
3. **G3** — shadow with the scheduler-independent trigger (lesson learned),
   logged next to the same nights.
4. **G4** — thread `deadline_amps` / window gates from the plan. Only on
   explicit call.

Existing assets kept: `overnight_planner.py` (the packer core + 17-scenario
corpus) — the ledger replaces its flat `cap_w`/side-budget inputs.

## Tariff robustness (Guido's stress test, 2026-07-29)

The ledger must survive every tariff shape SEM supports — Guido's static
HT/NT, Rien's day-ahead dynamic (hourly, and 15-min as NL/EU markets
switch), the #686 fixed-hours tiered ToU, and flat. Three clauses:

1. **Slots follow the market, not the clock.** Ledger slot length = the
   provider's native granularity (the same 15/30/60-min inference
   `find_cheapest_hours` already does). Hourly sampling on a 15-min market
   would waste exactly the intra-hour cheap quarters that market exists for.
2. **Never invent a price.** When `get_price_at(t)` has no data for part of
   the window (day-ahead not yet published, series rolled off — the #612
   raw_tomorrow case), those slots are UNPRICED: price-sensitive demands
   pack only into priced slots, the 22:00 report says so, and the existing
   price-fingerprint replan re-derives the ledger the moment tomorrow's
   series lands. A flat fallback constant would silently mis-plan Rien's
   nights.
3. **Plan-packing must agree with execution-gating.** A cheap-hours load is
   EXECUTED only when the provider's price LEVEL says cheap
   (`price_is_cheap`); the ledger must therefore pack cheap-hours loads only
   into level-cheap slots — not merely the cheapest slot of the night.
   On a flat tariff nothing is level-cheap: the honest plan reports
   "no cheap window tonight — yields", matching what the reactive layer
   would do, instead of scheduling a run that execution would never fire.
   (EV floors and battery pre-charge pack by PRICE and are unaffected —
   their execution paths are price-driven, not level-driven.)

## The battery discharge limit is a shared per-slot bottleneck (Guido, 2026-07-29)

The *Battery total discharge limit* (`battery_max_discharge_power`, the same
knob as the config card's Discharge-protection slider) enters the ledger
twice: the trajectory bounds home-from-battery by it, and Tier-2 grants
consume a **shared instantaneous budget** — home's battery draw plus every
booked Tier-2 load sum against the inverter's total, peak not average
(allocations start at slot start and overlap). A second pump that would push
the concurrent sum over the limit is packed into a later slot or yields.
The *Battery → EV assist limit* is a daytime knob — night EV is never
battery-funded — and is deliberately not a night input.
