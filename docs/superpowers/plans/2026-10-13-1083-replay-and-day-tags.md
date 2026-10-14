# #1083 Replay and day tags — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay real recorded days through SEM's real decision cycle, picked by day tags (sunny / grey / car / cheap / data gap), first as our standard proof step for branches, later as the user's what-if with € differences.

**Architecture:** Three layers. (1) A nightly **day tagger** writes one small record per day into SEM's own storage. (2) A **replay engine** turns a recorded day (HA recorder states of the sensors SEM reads) into a timeline and drives the REAL `SEMCoordinator` update cycle with no Home Assistant side effects — the same mechanism `tests/scenario_harness.py` already uses, extended to feed the REAL forecast tracker and tariff from recorded data instead of stubs. (3) A **test tool** replays a branch against a local corpus of tagged PROD days and reports pass/fail per invariant per day; `~/bin/sem-ready.sh` reads that report. The user what-if (4) reuses (2) and comes last, mockup first.

**Tech Stack:** Python 3.13/3.14, Home Assistant recorder (`coordinator/recorder_history.py` is the one reader), pytest + `tests/scenario_harness.py`, SEM storage (`coordinator/storage.py`, `homeassistant.helpers.storage.Store`).

**Origin:** @RienduPre's #1083 ("replay the last 30–90 days with different settings"). Guido, 13.10: build the engine first as our test tool; tag days by weather and events; "we can integrate this in our testing pipeline instead of the compressed sun simulation."

---

## What exists (read before building)

| Piece | Where | What it gives |
|---|---|---|
| Real-cycle replay of a timeline | `tests/scenario_harness.py` (`run_scenario`, `_build_coordinator`, `_capture_actuator_calls`, sticky timeline rows, 144-cycle full day in < 1 s) | The engine core. **Stubs** the forecast (`forecast_remaining_today_kwh = 25.0`, `dampening_factor = 1.0`) and the tariff (`tariff_level` per row) — replay must replace both stubs with recorded data. |
| One recorder reader | `coordinator/recorder_history.py` (`read_states`, `run_after_start`, `_window_days`) | Cheap, attribute-free state reads; never charged to HA's start-up budget (#967). |
| Forecast vs actual per day | `coordinator/forecast_tracker.py` (`DailyForecastRecord`, hourly tracking, `corrected_remaining_kwh`) and `coordinator/forecast_ledger.py` (`ForecastLedger`, per-horizon accuracy) | The "yield vs forecast" ratio per day, and the code path #1104 changes. |
| PV health | `analytics/pv_health.py` (`pv_health`, `FULL_YIELD_RATIO 0.90`, snow flag) | Snow and full-yield day rules to reuse — not a second copy. |
| Sessions | `session_history.py` (`history_for`, `select_sessions`) | "Car charged that day". |
| Dropouts | `coordinator/sensor_reader.py` (`_sensor_unavailable_since`, dropout handling ~1711, ~2796, ~2881) | Live only — the tagger reads dropouts from the recorder instead (`unavailable` states). |
| Day slots / sun curve | `coordinator/day_ledger.py` (`_curve_fraction`, `expected_solar_kwh_between`) | The sine-shape clear-sky curve for "sunny" and for intra-hour variability. |
| Daily store | `coordinator/storage.py` (`{DOMAIN}_{entry_id}_daily`, throttled saves, a year of sessions well under budget) | Where day tags live (new key, same store). |
| Merge gate | `~/bin/sem-ready.sh` (gates 1 green, 2 documented, 2b challenged …) | Gets a replay gate. |

## Honest limits (say them in the docs, test against them)

Replay feeds **recorded** inputs. It cannot see the **feedback of SEM's own new actions**: if the branch would have charged the car at 3 kW where the recorded day did not, the recorded grid and battery readings do not move. So:

- **Decisions** are replayed exactly (the real cycle, real modes, real guards).
- **Flows that follow from different decisions** are recomputed with a simple, documented energy balance per cycle (`home = solar + import + discharge − ev − export − charge`, battery SOC walked from capacity and efficiency, grid = the balance) — the counterfactual. Invariants that depend on it are marked *modelled*, the rest *exact*.
- Not modelled: inverter clipping, battery BMS limits beyond the configured max, the car's own taper, a charger refusing a start (#1011). Days where these matter are tagged by the tagger where it can see them, and their modelled invariants are reported as *indicative*.

What replay **cannot prove at all** stays on .175 live with the compressed sun simulation (Task 8): HA setup and config flows, entity creation and names, restarts and restore, real actuation and charger wiring, Repairs, the UI and cards.

---

## File structure

| File | Responsibility |
|---|---|
| `analytics/day_tags.py` (new, pure) | `DayTags` dataclass and `tag_day(samples, forecast_kwh, clear_sky_kwh, sessions, prices, gaps) -> DayTags`. No HA. |
| `coordinator/day_tag_store.py` (new) | Nightly job (00:15 local, `run_after_start`, after `recorder_history`) that reads yesterday, calls `tag_day`, writes into the daily store under `day_tags` (bounded: 400 days). |
| `replay/recorded_day.py` (new, dev tool, not loaded by HA) | Recorder export → `RecordedDay` (resampled to the coordinator cycle, sticky rows, recorded `unavailable` kept as a dark input, prices, forecast-at-the-time). |
| `replay/engine.py` (new) | `replay_day(day, config, branch_tree) -> DayRun`: builds the coordinator the way `scenario_harness` does, but with the real `ForecastTracker` fed from the recorded forecast and a recorded-price tariff provider; captures decisions; walks the counterfactual balance. One day in memory at a time. |
| `replay/invariants.py` (new) | Named invariants → pass/fail per day (`exact` or `modelled`). |
| `scripts/sem_replay.py` (new CLI) | `sem-replay --corpus DIR --tags sunny --since 60d --branch TREE --invariants grid_limit,reserve,forecast_overshoot --report out.json`. |
| `~/bin/sem-export-days` (new, outside repo) | Read-only PROD export → local corpus, anonymised. |
| `tests/test_1083_*.py` | Unit tests per layer, plus 2–3 anonymised fixture days. |
| `~/bin/sem-ready.sh` | New gate 3b "replayed". |

Release zip: `replay/` and `scripts/` stay out of the HACS zip (`scripts/build_release_zip.sh`, `scripts/verify_release_zip.py` — add `replay/` to the exclude and the verify list).

---

### Task 1: Day tagger — pure rules

**Files:** Create `analytics/day_tags.py`, `tests/test_1083_day_tags.py`

Rules (each a pure function, each with a test from a real day shape):
- `sky`: `sunny` if yield ≥ `FULL_YIELD_RATIO` × clear-sky (from `day_ledger` curve and the plant's best day of the last 30) **and** intra-hour variability (std of 5-min solar ÷ mean, 10:00–15:00) < 0.15; `grey` if yield < 0.35 × forecast; else `mixed`. Reuse `pv_health`'s ratio code — import, do not copy.
- `snow`: `pv_health`'s snow flag for that day.
- `car`: ≥ 1 finished session (`select_sessions`) that day, with kWh.
- `prices`: `negative` if any slot < 0, `cheap` if the day's min ≤ the cheap threshold the tariff provider uses; nothing on a flat tariff (#994: flat is no comparison).
- `gap`: any source sensor `unavailable` > 15 min in daylight, a restart (HA start event or SEM's own start mark), or a **frozen counter** — the lifetime solar counter flat while the forecast said > 2 kWh (PROD 12.10 shape).
- [ ] Write failing tests: PROD 13.10 (sunny morning, 14.2 kWh) → `sunny` or `mixed` per the variability rule; PROD 08.10 (4.3 kWh vs 18.3 forecast) → `grey`; PROD 12.10 (counter flat 23 832.86 all day) → `gap`.
- [ ] Implement, run, commit `feat(#1083): tag a day by sky, car, prices and data gaps`.

### Task 2: Day tags stored nightly (asleep)

**Files:** Create `coordinator/day_tag_store.py`; modify `coordinator/storage.py` (new `day_tags` key, bounded 400), `coordinator/coordinator.py` (schedule), `tests/test_1083_day_tag_store.py`
- [ ] Nightly at 00:15 local via `run_after_start` + `async_track_time_change`; reads yesterday through `recorder_history.read_states` (attribute-free, window clipped by `_window_days`); never in `async_setup_entry`'s await path (#967).
- [ ] Soak flag `day_tags` (default **off**, `set_option`, no GUI control — it only records). Diagnostics shows the last 7 tags.
- [ ] Tests: round-trip storage, the 400-day bound, a recorder `None` (could not answer) stores nothing — never a fake `grey`.
- [ ] Commit `feat(#1083): store a tag per day, nightly, asleep`.

### Task 3: Recorded day — export and anonymise (outside HA)

**Files:** Create `replay/recorded_day.py`, `~/bin/sem-export-days`, `tests/test_1083_recorded_day.py`
- [ ] `sem-export-days --host prod --days 60 --out ~/sem-replay-corpus/` — READ-ONLY: `/api/history/period` with `minimal_response&no_attributes` for exactly the entities SEM reads (taken from PROD's SEM diagnostics / `sensor_reader` resolved ids), the forecast entities, the price entity, and the day tags; one file per day (`YYYY-MM-DD.json.gz`), so replay holds one day in memory.
- [ ] Anonymise on export: entity ids → role names (`solar_power`, `grid_power`, `battery_soc`, `ev:<n>:power` …), device and charger names → `box_1…`, location → none, timestamps kept (the day shape matters). Reuse the #1092 redactor (`tests/integrations_rig/capture_tools/diag_to_capture.py` box-name redaction) — one redactor.
- [ ] The corpus lives in `~/sem-replay-corpus/` — **never in git** (`.gitignore` the path pattern anyway); a weekly cron refreshes it (Sunday 06:00, keep 90 days).
- [ ] `RecordedDay.timeline(cycle_s)` resamples to the coordinator cycle with sticky values; an `unavailable` stretch stays a dark input (that is what #1105 needs).
- [ ] Tests: resampling, sticky rows, dark stretches kept, the redactor leaves no source name (a test fails on any original entity id or box name in the output).
- [ ] Commit `feat(#1083): export real days read-only and anonymised`.

### Task 4: Replay engine — the real cycle with real forecast and tariff

**Files:** Create `replay/engine.py`, `tests/test_1083_engine.py`; refactor `tests/scenario_harness.py` so both share one coordinator builder (`replay/build.py`) — no second copy.
- [ ] Build the coordinator exactly as `_build_coordinator` does (observer on: no writes; actuator calls captured by `_capture_actuator_calls`).
- [ ] Replace the forecast stub with the REAL `ForecastTracker`, fed the recorded forecast for that day and the recorded actuals cycle by cycle (so `corrected_remaining_kwh` is the code under test).
- [ ] Replace the tariff stub with a provider that reads the recorded price series (same interface as `tariff_price_at` / `tariff_cheap_at` in `day_ledger`).
- [ ] Clock: advance HA's time per cycle the way the harness does (frozen clock, no wall clock — bug class 133).
- [ ] Counterfactual balance per cycle (see *Honest limits*); every flow carries `exact` or `modelled`.
- [ ] Memory: one day, one coordinator, released after the day; assert peak RSS < 400 MB on a 288-cycle day in a test marked `slow`.
- [ ] Tests: a fixture day replays to the same decisions the harness gives for the equivalent YAML; the forecast path is the real one (a deliberately wrong tracker breaks the test).
- [ ] Commit `feat(#1083): replay a recorded day through the real cycle`.

### Task 5: Invariants and the report

**Files:** Create `replay/invariants.py`, `scripts/sem_replay.py`, `tests/test_1083_invariants.py`

Starting set (each: name, exact/modelled, rule):
- `grid_limit` (modelled): import never above the active limit for more than one 15-min slot (#1069).
- `reserve` (modelled): battery never below its reserve by SEM's own discharge (#1069 finding 2).
- `no_flapping` (exact): no charger start/stop more often than the user's enable/disable delays allow (#1069 finding 6).
- `forecast_overshoot` (exact): with intraday correction on, corrected remaining solar before 12:00 never above the raw forecast remainder × 1.0 (the #1104 rule as decided there).
- `home_steady_on_dropout` (exact): home power does not jump > 50 % within one cycle while a battery input is dark (#1105).
- `no_write_in_observer` (exact): zero captured writes when the recorded day had observer on.
- [ ] CLI selects days by tag, skips `gap` days unless asked, runs one day at a time, writes `report.json` + a 10-line text summary: per invariant, days passed / failed / indicative, worst day with its numbers.
- [ ] Tests: a failing invariant on a fixture day is reported as failed (no vacuous pass — bug class: a check that cannot fail); a modelled invariant on a day with clipping is `indicative`, not pass.
- [ ] Commit `feat(#1083): invariants and a per-day replay report`.

### Task 6: The standard proof step for branches (replaces the sun simulation for logic)

**Files:** Modify `~/bin/sem-ready.sh` (gate 3b), `~/bin/sem-autopilot.sh` (prompt + ship check), `~/bin/AUTOPILOT.md`, CLAUDE.md "Working rules"/"Testing" lines.
- [ ] **(a) One command** both the branch workflow and the autopilot run before merge: `sem-replay --corpus ~/sem-replay-corpus --since 30d --branch $TREE --invariants default --report ~/claude-jobs/replay-<branch>.json`. Offline, one day at a time, fits the 4 GB box next to one test suite (check `pgrep -af pytest` and wait like the suites do).
- [ ] **(b) The corpus**: a fixed set of tagged real PROD days, anonymised, refreshed weekly (Task 3 cron), never in git. A *pinned* subset (`~/sem-replay-corpus/pinned/`) keeps the days that once showed a bug (13.10 sunny morning, 13.10 19:30 dropout, 08.10 grey, 12.10 frozen) so a fix stays proven after they age out.
- [ ] **(c) The gate**: `sem-ready.sh` gate 3b reads the report: any `exact` invariant failed on a non-gap day = refuse; `modelled` failures listed for the human. The autopilot's ship step refuses `.ship` without a green report for logic changes (files under `coordinator/`, `analytics/`, `features/`).
- [ ] **(d) CI**: 2–3 anonymised days as fixtures in `tests/fixtures/replay/` (after the Task 3 redactor test passes on them), replayed by a normal pytest — so CI also runs real days, small enough for both rungs.
- [ ] **What stays live on .175 with the compressed sun simulation** (and only this): HA setup and config/options flows, entity creation and names, restarts and restore, real actuation and charger wiring (KEBA, multi-charger, service vs number control), Repairs, the UI and cards.
- [ ] **Which current issues each path would have proven:** #1104 → replay (13.10 sunny morning, `forecast_overshoot`); #1105 → replay with the recorded dropout (13.10 19:30, `home_steady_on_dropout`); #1069 battery/peak → replay (`grid_limit`, `reserve`, `no_flapping`) instead of waiting for a real event on PROD; #1106 (peak 0 for 10 s after restart) and #1095/#1096/#1097 (setup, wiring, the crawler on a live registry) → **live on .175**.
- [ ] Commit `docs(#1083): replay is the proof step for logic; .175 keeps setup, restart, wiring and UI`.

### Task 7: Diagnostics and docs

- [ ] Diagnostics: last 7 day tags (no personal data).
- [ ] `docs/ARCHITECTURE.md` (replay layer, limits), `docs/KNOWN_LIMITATIONS.md` (what replay models), CHANGELOG ≤ 25 words, `sem-wordcheck`.
- [ ] Commit `docs(#1083): day tags and replay`.

### Task 8: Prove it, soak

- [ ] Full suite once (4 GB box: wait for any other run), ruff, CI both rungs.
- [ ] ruflo review (`~/claude-jobs/challenge-feature-1083-replay.md`), claims: "replay runs the real cycle with the real forecast and tariff; no write path; one day in memory; the report cannot pass a failed exact invariant; the corpus holds no personal data".
- [ ] Replay #1104's and #1105's branches against the pinned days — the first real use.
- [ ] Day tags soak on PROD (flag on) one week; compare tags with Guido's own memory of those days.

### Task 9 (LATER, separate stop): the user what-if

- [ ] **Mockup first, stop for Guido's OK**: a card section "What if…" — pick a change (battery size, a tariff, a mode) and a day type; shows € and kWh per day type over the last 30–90 days, with *modelled* clearly marked.
- [ ] Settings in the GUI; option surface only shrinks — what-if inputs are a one-off form, not stored options.
- [ ] Soak on PROD before develop.

---

## Open decisions for Guido (my default in brackets)

1. **Where replay code lives** — in the repo but out of the HACS zip (`replay/`, `scripts/`) so CI can run fixture days. [yes]
2. **Day tags on PROD**: record nightly behind a soak flag, no GUI control (it only records). [yes]
3. **Corpus window**: 90 days rolling + pinned bug days, weekly refresh. [yes]
4. **Gate strictness**: an `exact` invariant failing on a non-gap day blocks the merge; `modelled` ones are shown, not blocking. [yes]
5. **#1104 rule** for the `forecast_overshoot` invariant: before 12:00 never above the raw forecast remainder. [take whatever #1104's fix decides; the invariant follows it]
6. **What-if (Task 9)** waits until the test tool has run for two weeks. [yes]

## Biggest risk

The counterfactual: replay sees SEM's decisions exactly, but when a branch decides differently from the recorded day, every flow after that point is modelled, not measured. If the modelled balance is trusted like a measurement, a wrong battery or grid model passes or fails branches for the wrong reason. Hence `exact` vs `modelled` on every invariant, `indicative` on days the model cannot cover, and only `exact` invariants may block a merge.
