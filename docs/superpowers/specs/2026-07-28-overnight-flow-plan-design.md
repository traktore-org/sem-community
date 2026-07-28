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
