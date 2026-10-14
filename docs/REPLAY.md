# Replay — proving a change on real recorded days (#1083)

Replay runs a branch's real code on days PROD really had, and compares it
with develop on the same days. It replaced the compressed sun simulation
as the proof for **logic** changes; .175 live keeps everything replay
cannot see.

## One command

```
sem-replay --branch /home/sem/sem-1104 --report ~/claude-jobs/replay-fix-1104-proof-findings.json
```

- `--base` (default: the develop checkout) is replayed on the same days.
- `--since 30` days back; the **pinned** days always run.
- `--tags sunny` / `--tags grey,car` picks days by tag; gap days are
  skipped unless `--include-gap` or `--tags gap`.
- Exit 0 = pass, 1 = refused, 2 = no matching day (nothing proven).

`~/bin/sem-ready.sh` gate **2c** refuses a branch that changes
`coordinator/`, `analytics/`, `features/` or `devices/` without a report
newer than its last commit (or an `NA:` file with the reason). The
autopilot runs it before merging a bug fix (step 3b).

## The corpus

- `~/sem-replay-corpus/` — one file per local day, refreshed Sundays 06:07
  by `~/bin/sem-export-days --host prod --days 90` (cron). READ-ONLY on
  PROD: REST history, attribute-free. **Never in git** — it is the house's
  data.
- `~/sem-replay-corpus/pinned/` — days that once showed a bug, kept after
  they age out: 08.10 (grey, #1068), 12.10 (frozen inverter, gap),
  13.10 (tagged mixed: a clear morning #1104, clouds after noon, battery stop at 21:30 #1105).
- Anonymised by construction: SEM's own entities are stored by **role**
  (`solar_power`, `grid_power`, …); any other entity is dropped
  (`tools/replay/recorded_day.py` `ROLES`).
- CI fixtures (`tests/fixtures/replay/`) are two short windows of a real
  day, moved to another date.

## Day tags

Each day carries tags from one set of rules (`analytics/day_tags.py`):
`sunny` / `mixed` / `grey`, `snow`, `car`, `negative` / `cheap`, `gap`.
On an install the nightly tagger (`coordinator/day_tag_store.py`, 00:15)
writes them to SEM's daily store when the `day_tags` soak flag is on
(`set_option`, no GUI control); diagnostics shows the last 7.

## What runs

Production code from the tree under test, inputs and clock from the day
(`tools/replay/engine.py`):

| Path | Code | Cadence |
|---|---|---|
| Shown home | `SEMCoordinator._hold_shown_home` (#1047, #1105) | every 10 s |
| The plan's rest-of-day solar | `ForecastTracker.update` + `corrected_remaining_kwh` (#1068, #1104) | every 5 min |

## Checks

| Check | Kind | Fails when |
|---|---|---|
| `forecast_overshoot` | exact | before noon, corrected remaining solar is above the provider's raw remainder |
| `home_spike` | relative | the branch shows a one-cycle home spike develop did not show |
| `no_writes` | exact | the replayed code made a service call |

| `cost_identity` | modelled | the day re-priced hourly by the Simulation tab's model is more than 0.01 off its 10-s cost |

Only `exact` and `relative` checks block, and only on a non-gap day. An
exact check that fails on develop too is **inherited** — reported, never
blamed on the branch. A check that cannot fail is a bug: each one has a
test that makes it fail on a real recorded fault.

## The Simulation tab's model

The user-facing Simulation tab and this tool share one model,
`analytics/simulation/` (it ships; `tools/` imports it, never the other
way). The tab reads 24 hourly rows per day from Home Assistant's
statistics; `tools/replay/hourly.py` adds a 10-s corpus day up into the
same `HourlyDay`. `cost_identity` re-prices that day through the model's
`balance.cost_hour`: on prices flat inside each hour it matches; a 15-min
price curve pulls it apart, so it is reported and never blocks. A tree
without the model (develop before #1083) skips it.

## Limits — said plainly

- Replay sees what SEM **saw**. When a branch decides differently, the
  house would have answered differently; replay does not model that answer
  (no counterfactual yet). So it proves what a branch **computes** from real
  inputs, not what the house would have done.
- Only the paths in the table above are replayed today. EV, battery and
  load decisions are not — they need the forecast and tariff the scenario
  harness still stubs, and the counterfactual.
- The forecast tracker starts each replayed day with no history: its
  long-run correction factor is 1.0, where an install has its own. The
  intraday part — what #1068 and #1104 change — is the same code either way.
- Sunrise and sunset come from the day's own first and last real sun
  (above 50 W): the corpus holds no location.
- SEM's entities are recorded on change, each on its own timing; replay
  rebuilds the balance from them. A spike that exists only because two
  entities were written at different moments shows on develop too, so it
  is shared, never blamed.

## What stays on .175 live

HA setup and config/options flows, entity creation and names, restarts and
restore (#1106), real actuation and charger wiring (#1095–#1097), Repairs,
the UI and cards.
