# #1083 — the Simulation tab (what-if on recorded days)

## Context

@RienduPre asked (#1083) for a what-if: replay the last 30–90 days with other settings and see the € difference. Branch C (`feature/1083-replay`, CI green, reviewed) built the first half: day tags and a developer replay tool. That tool lives in `tools/`, never ships, and replays only two pieces of SEM (home-power hold, solar forecast). Guido now wants the user-facing half: **an extra dashboard tab "Simulation"**, switched on by the user, where they pick recorded days by tag, change a few parameters, run the replay in the background on their own Home Assistant, and get € per day and per day type — every simulated number marked as estimated.

Decisions already made by Guido (14.10.2026): the mockup (`~/claude-jobs/mockups/1083-simulation-tab.png`) is approved as shown; history comes from **hourly long-term statistics, 90 days**; the simulated battery **runs SEM's real battery decisions**; downloads are **xlsx, for the simulation and for the EV session history** (no CSV); **build with Opus** after approval.

Branch: `feature/1083-simulation-tab` on top of `feature/1083-replay` (worktree `/home/sem/sem-1083` → new worktree `/home/sem/sem-sim`). Lands asleep (switch off by default), soaks on PROD before develop.

## Design (fixed)

| Point | Decision |
|---|---|
| History | One `statistics_during_period(hour, {"change","mean"})` call per day on the recorder executor (wrapper shape: `coordinator/energy_calculator.py:1942-1972`). Flows from SEM's own `TOTAL` sensors with midnight `last_reset` → hourly `change` = gross kWh: `daily_solar_energy`, `daily_grid_import_energy`, `daily_grid_export_energy`, `daily_battery_charge_energy`, `daily_battery_discharge_energy`, `daily_ev_energy`, `daily_home_energy`. `MEASUREMENT` → hourly `mean`: `battery_soc`, `tariff_current_import_rate`, `tariff_current_export_rate` ("as recorded" prices). Entity ids via the registry as `day_tag_store._entity_id` does. Limit stated on the tab: hourly averages flatten 15-min prices and peaks. |
| Battery | **SEM's real decisions, hour by hour.** Each hour builds a synthetic `BatteryView` (`coordinator/charger_types.py` ~754) and calls `decide_battery(view)` (`coordinator/decide_battery.py:335`, pure); the energy balance consumes the `BatteryDecision` (intent, `charge_power_w`, `discharge_limit_w`, `floor_soc`). Night/cheap-hour charging: `BatteryChargeScheduler.evaluate()` fed the hourly price slots and the recorded forecast when the user's config has it on; `build_night_ledger`/`pack_night` (`coordinator/energy_planner.py:116/:218`) with `LedgerSlot(start,end,price,level_cheap,home_w)` for the sunrise-floor walk. Peak: `peak_guard.slot_allowed_import_w` in hourly form. EV and loads stay **as recorded** (stated limit). |
| Tab on/off | A switch `simulation_enabled` (default OFF). `_prune_sleeping_tabs` beside `features/dashboard_generator.py:_prune_absent_modules` (:261) drops `path: simulation` when off; the switch's turn handlers call `generate_dashboard` (the call at `__init__.py:3228`) and raise a persistent notification "reload the page". Tab header entry in `dashboard/card/src/cards/sem-tab-header.js:71-80,166-193`. |
| One switch | Turning it on also turns day tagging on (`day_tag_store.day_tags_on()` = `day_tags OR simulation_enabled`) and backfills 90 days of tags from hourly statistics in the background (older days can never be "sunny": no intra-hour variability → `backfilled: true`). |
| Transport | Websocket commands `solar_energy_management/simulation/{days,start,status,result,cancel,xlsx}` (pattern `session_history.py:118-141`, registered from `__init__.py:3147`). Card polls `status` every 2 s while running. Results in the daily Store key `simulation_runs`, last 3 runs, saved once at completion (`storage.async_save_daily`); never entity attributes (16 KB cap). |
| Job | `coordinator/simulation_job.py`: one task per coordinator, refuses a second start, one day resident, `await asyncio.sleep(0)` between days, max 90 days, `cancel()` wired into `cancel_pending_recorder_work` (`coordinator.py:7907`) and `entry.async_on_unload`. |
| xlsx | `utils/xlsx.py`, stdlib only (`zipfile` + hand-written OOXML: `[Content_Types].xml`, `_rels/.rels`, `xl/workbook.xml`, `xl/_rels/workbook.xml.rels`, `xl/worksheets/sheet1.xml`, `xl/styles.xml` with a date style). Numbers typed, dates as serial + style, strings inline. Base64 over websocket → `Blob` (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`) → `a.download`, as `sem-ev-status-card.js:109-119` does for CSV. The EV card's session download switches to it; `export_session_history` keeps returning `rows`/`csv` for automations. |
| Code home | Pure model in `analytics/simulation/` (ships). `tools/replay` imports it; never the reverse. |
| Options | +1 switch (baseline 199→200 after branch A; reason in the commit: an opt-in modelling job on the user's recorder; the what-if values are form fields, not options). |

### Synthetic `BatteryView` per hour (what the real decisions need)

| Field | Source in the simulation |
|---|---|
| `runtime` (`BatteryRuntime`: id, soc, capacity) | simulated SOC, the what-if capacity |
| `config` | the install's battery config with what-if overrides: `battery_capacity_kwh`, `battery_reserve_soc`, `battery_mode` as configured, max charge/discharge W as configured, `battery_roundtrip_efficiency` (default 0.92) |
| `fleet` / `ev_charging` / `ev_connected` | `ev_charging` = recorded EV kWh in the hour > 0; `ev_connected` unknown → False (stated) |
| `charging_state` | `night_charging_active` while the scheduler says charge, else the idle state |
| `home_consumption_w` | hour home kWh × 1000 |
| `scheduler_decision` | `BatteryChargeScheduler.evaluate()` on the hourly prices + recorded forecast when night charging is configured; else `None` |
| `battery_spendable_kwh`, `forecast_spending_enabled`, `dynamic_floor_pct`, `battery_permissions`, `plan_gate`, `arbitrage_sell`, `forecast_sell`, `sink_verdicts`, `grid_funded_load_w` | defaults (today's behaviour); forecast spending OFF in v1 — stated |

**Balance per hour** from the decision: `OFF`/`NORMAL` → self-consumption dispatch within limits; `LIMIT_DISCHARGE` → discharge ≤ `discharge_limit_w`; `FORCE_CHARGE` → grid charge at `charge_power_w`; `STOP_*` → no forced charge; any other intent → treated as `NORMAL` and the hour marked `indicative`. Then `home = solar + import + discharge − ev − export − charge` closes the hour; SOC walks with √0.92 each way, clamped to [reserve, capacity]; import above the peak allowance is reported as "kWh over the limit", never dropped. Pricing = SEM's rule (`energy_calculator.py:730-754`): import × rate − export × rate, negative export separate, on baseline and what-if with the same prices. A day is `indicative` when a price or SOC hour is missing or the day carries the gap tag.

## Tasks (one commit each, `#1083`, no co-author; TDD)

1. **Pure model** — new `analytics/simulation/{hourly_day.py, battery_sim.py, cost.py, result.py}`: `HourlyDay` (24 rows), `from_statistics()`, `simulate_day(day, params, config)` driving `decide_battery` + scheduler/ledger as above, `price()`, `aggregate()` per day and per tag. Tests `tests/test_1083_sim_model.py`: balance closes every hour; SOC within [reserve, capacity]; efficiency applied; peak clamp reported; negative export priced separately; flat vs recorded price identity; **baseline reprice equals the recorded day's cost**; a `LIMIT_DISCHARGE` hour obeys the limit; a `FORCE_CHARGE` hour draws from the grid; indicative marking.
2. **xlsx writer** — new `utils/xlsx.py`; ws `session_history/xlsx` beside `session_history.py:118`; EV card download → xlsx. Tests `tests/test_xlsx_writer.py`: zip opens, sheet XML parses (`xml.etree`), round-trip typed cells and dates, formula-looking strings stay text.
3. **Job** — new `coordinator/simulation_job.py` (entity ids via registry, one day per query, yield between days, max 90, single task, cancel on unload, progress dict, result stored). Tests: fake statistics, cancel mid-run, busy refusal, one day resident.
4. **Switch + tags** — `switch.py` description (CONFIG category, `mdi:flask-outline`), `persisted_flags.py` default False, turn handlers regenerate + notify; `day_tags_on()` OR; 90-day tag backfill; `strings.json` + 16 `translations/*.json`; `python3 scripts/audit_options.py --baseline` with the reason; config-card toggle under Advanced.
5. **Dashboard** — the view in `dashboard/sem_dashboard_template.yaml`, `_prune_sleeping_tabs`, tab-header entry, `dashboard/translations.json` keys (`simulation`, `simulation_sub`, form labels, `estimated`), regenerate localize. Tests: prune by switch (style of `tests/test_923_*`), regeneration on flip.
6. **Websocket** — new `simulation_ws.py`, registered at `__init__.py:3147`; every result carries `modelled: true`. Tests with a fake connection.
7. **Card** — new `dashboard/card/src/cards/sem-simulation-card.js` + `src/util/simulation-format.js`, exactly the approved mockup (day chips by tag, quick picks, gap days unselectable, what-if form "current → new", run/progress/stop, per-day table with `est.` badges, totals per day type, xlsx download, legend); `semDefineCard` with `documentationURL` → heading `sem-simulation-card` in `docs/DASHBOARD_GUIDE.md`; no backtick in lit `html`; `npm run build`; node tests for the util.
8. **Dev tool + docs** — `tools/replay` adapter `RecordedDay → HourlyDay` and invariant `cost_identity`; `docs/USER_GUIDE.md`, `docs/KNOWN_LIMITATIONS.md` (hourly averages; EV and loads as recorded; forecast spending off in v1); CHANGELOG ≤25 words: "Simulation tab (off by default): replay recorded days with another battery, reserve, peak limit or price; estimated € per day type (#1083)".
9. **Gates** — full suite (two at a time max), ruff, card tests, CI both rungs; ruflo review (`~/claude-jobs/challenge-feature-1083-simulation-tab.md`, claims: inert when off; real `decide_battery` drives every hour; baseline reprice = recorded cost; one day resident; cancel on unload; xlsx has no personal data beyond the user's own numbers); `sem-replay` gate 2c on the branch.

## Execution

Build with **Opus** agents (`model: opus`), one fresh agent per task, a review between tasks, worktree `/home/sem/sem-sim`. Memory for every helper: fewest words, common words, "you" in any user text.

## Verification

- Unit: the tests above; `tests/test_830_option_surface_ratchet.py` with the new baseline; `tests/test_card_registry_metadata.py`.
- `.175` (observer on): switch on → tab appears after reload; 90-day run finishes; HA memory stable; no recorder-busy warnings; stop mid-run; switch off → tab gone; xlsx opens in LibreOffice with a `;` locale with typed numbers.
- PROD soak (switch on, Guido's own days): the baseline € per day equals the Costs tab for the same days; a what-if run completes; no SEM errors; tags match Guido's memory of sunny/grey days.
- Merge to develop only after the soak and Guido's word (`SEM_FEAT_OK`).

## Risks

- Hourly averages under-model 15-min price swings and short peaks (stated on the tab).
- Installs with little long-term statistics (new SEM) get few days — the `days` command says so.
- `generate_dashboard` on a switch flip overwrites a user-edited dashboard, as the service does today.
- The real decisions need inputs an hour cannot give (plan gate, spending); v1 uses defaults and says so; forecast-led spending and EV shifting are v2.
