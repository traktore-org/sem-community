# Changelog

All notable changes to SEM are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> From v1.7.0-beta.14 onward, release entries follow the
> [music-assistant addon](https://github.com/music-assistant/home-assistant-addon)
> style: DD.MM.YYYY dates, emoji-prefixed sections, one-liner bullets with
> `(by @author in #PR)` attribution. Older entries (≤ beta.13) stay in the
> prose-paragraph style they were written in.

# [1.7.0-beta.15] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.14](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.14)_

### 🐛 Bugfixes

- Config flow step 2 (EV charger) slimmed from 16 fields back to 5: 8 per-charger tunables from PR #390 reverted to OptionsFlow where they belong by design. `ev_current_control_entity` stays for Wallbox-style chargers (by @traktore-org in #398, closes #397)

### 🚀 Features and enhancements

- First-run persistent notification with dashboard deep-link + 3-item checklist; gated to one-shot per install via `_welcome_notification_fired` options flag; skipped on `observer_mode` (by @traktore-org in #398, refs #397)
- ADR 0002 split into 0002 (data-model: `EVBudget` unification) + 0009 (distribution: multi-charger allocation) — each ADR now accurate to its scope (by @traktore-org in `aca2a00`)
- ADRs 0006-0008 added: real-hass test framework, dashboard bundle architecture, and the architecture-record meta-decision (by @traktore-org in #396)
- `CONTRIBUTING.md` test pyramid updated from 3 layers to 4 (unit / scenario / **real-hass** / live), referencing ADR 0007 (by @traktore-org in `aca2a00`)

### 🧰 Maintenance and dependency bumps

- ADR code-link drift fixed in 0002 + 0004 — references the actual function/file anchors now (by @traktore-org in #396)
- First 5 ADRs (0001-0005) added in `docs/adr/` — PerChargerContext, EVBudget unification, sign convention boundary, home_consumption_power clamp, pipeline-test-per-brand mandate (by @traktore-org in #394, kept in #395)

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org

# [1.7.0-beta.14] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.13](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.13)_

### 🐛 Bugfixes

- KEBA failsafe watchdog drop after steady-state charging: same-value `set_current` writes now refresh past a 60 s heartbeat window so the device watchdog stays alive. Generalised to all current-controlled chargers (by @traktore-org in #393, closes #392)
- Same-value heartbeat write also re-converges device-side and SEM-side state after silent device resets (replug fallback, KEBA reboot, failsafe trip) — no more "SEM thinks 16 A, KEBA at 6 A, stuck forever" mode (by @traktore-org in #393)

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org

## [1.7.0-beta.13] — 2026-06-03

The **#359 percentile classifier follow-up**.

### Fixed

- **#359** (PR #391) — RienduPre reopened #359 with screenshots showing
  €0.30 still labelled `normal` / `cheap` after the percentile fix
  shipped in beta.3. Root cause: `_get_percentile_breaks` and
  `get_tariff_data` filtered today's prices with a bare
  `p.timestamp.date()`. Providers differ on the tz they emit — Tibber
  is local, Nordpool-class integrations (incl. several Dutch dynamic-
  tariff implementations) are often UTC. On +02:00 (Europe/Amsterdam
  summer), a UTC-tagged price at 22:00 UTC = 00:00 local-next-day,
  and a bare `.date()` returns the UTC date. Today's filtered array
  dropped below the 4-point minimum, percentile breaks returned
  `None`, and the classifier silently fell back to the static
  €0.15 / €0.35 cutoffs — where €0.30 < 0.35 = `normal`. Exactly the
  symptom.

  Fix: new `_local_date(timestamp)` helper converts via
  `dt_util.as_local` for tz-aware datetimes and passes naive
  datetimes through unchanged (keeps the existing tariff tests, which
  mock `dt_util` and build naive clocks, green without modification).

### Added

- **Tariff diagnostics** (PR #391) — three DEBUG log lines under the
  `tariff/#359` tag so a repro is now trivial:
  - `percentile fallback — today's price array has X/Y points` when
    the array drops below the 4-point minimum (the typical failure
    mode pre-fix).
  - `degenerate distribution — p90-p10=X` when the M1 flat-day guard
    trips.
  - `percentile breaks for <date> — p10/p25/p75/p90` on the happy
    path so users can sanity-check the math against their tariff.

## [1.7.0-beta.12] — 2026-06-03

Per-charger refinements + EV config-flow parity. Bundles the
undocumented beta.11 (#355 affordance) so the changelog is complete from
beta.10 to beta.12.

### Fixed

- **#383** (PR #385) — In multi-charger installs every per-charger card
  showed the same vehicle SOC. The coordinator was overwriting one
  shared `_cycle_vehicle_soc` from each charger's `vehicle_soc_entity`
  inside the per-charger loop; the global sensor reported whichever
  charger ran last, and the card's `_val('charger_<id>_vehicle_soc') ??
  _val('vehicle_soc')` lookup chain always fell through to the global.
  Now publishes per-charger SOC via `charger_<cid>_vehicle_soc`, with
  the unconfigured case returning `None` (not a fabricated zero).

- **#384** Part 1 (PR #388) — The "Add EV Charger" options-flow step had
  translation coverage for only two fields (Solar charge limit kWh /
  SOC%); the rest of the form fell back to the raw key on non-English
  installs. Mirrored `ev_charger_edit` `data` / `data_description` into
  `ev_charger_add` for all 15 languages.

- **#384** Part 2 (PR #390) — The initial setup flow couldn't configure
  Wallbox-style chargers (number entity for current control) because it
  lacked `ev_current_control_entity`. The user had to finish setup with
  a partial config and then drop into Options → Edit. Initial flow now
  exposes the full per-charger override set: `ev_current_control_entity`,
  `ev_surplus_priority`, `daily_ev_target` + `_max`,
  `ev_night_initial_current`, `ev_min_current`, `ev_target_soc` + `_max`,
  `ev_battery_capacity_kwh`. `_EV_KEYS` bridge extended so they migrate
  into `ev_chargers[0]`. `vehicle_soc_entity` deliberately stays in
  OptionsFlow only — asking on install creates a dead input for users
  without a vehicle SOC sensor.

- **EV stall detector** (PR #389) — Detector was anchoring SOC=100% even
  in cycles where SEM had never commanded charge, producing false-stall
  alerts when the EV was simply sitting fully-charged with the cable
  plugged in. The anchor now requires a SEM-issued charge command.

### Added

- **Per-battery sensors + fleet/per-battery card** (PR #386 — Phase A + B)
  — first cut of a multi-battery model. Adds per-battery state, energy
  and power sensors, plus a dashboard card that shows fleet totals and
  per-battery detail.

- **Battery card session duration** (PR #387) — sessions over 90 minutes
  are shown as hours (`2h 15m`) instead of `135m`, matching how users
  think about long battery discharges.

- **#355 split affordance on stacked range handles** (PR #380) — a
  tappable split (↔) icon appears whenever the Min/Max handles of the
  EV target range slider visually overlap (within 2 % of the slider
  span). One tap drops Min by 2 % so the stacked handles become
  individually grabbable. Works in kWh and SOC % modes.

- **`per_charger: true` on `sem-chart-card` EV preset** — optional
  per-charger color breakdown driven by discovered
  `sensor.sem_charger_<id>_power` entities.

### Changed

- **EV chart "today" period** (in PR #380) — was rolling 24h, which
  painted yesterday-evening charges as a phantom second event. Now
  anchored at local midnight to match `daily_ev_energy`.

### Removed

- Per-charger **"Set target as default"** button (PR #380). HA's
  number-entity state restoration already persists slider values across
  restarts; the button's "copy to global defaults" workflow was niche on
  installs that grow new chargers later. Existing entries are
  auto-cleaned on the next setup.

## [1.7.0-beta.10] — 2026-06-02

The **#356 ghost-charger** fix.

### Fixed

* **#356** — EV / charger status cards rendered ghost sections per real
  charger, appearing as duplicate cards titled `<Charger Name> Solar → EV`,
  `<Charger Name> Grid → EV`, `<Charger Name> Battery → EV`. Each ghost
  duplicated the SOC gauge, charge target slider, mode dropdown and
  `Klaar om` timer — only the power value differed, matching the per-flow
  attribution.

  Root cause: the charger auto-discovery regex in both
  `dashboard/card/src/cards/sem-ev-status-card.js` and
  `sem-charger-status-card.js` was greedy:

  ```javascript
  const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
  ```

  It matched both real charger sensors (`sensor.sem_charger_<id>_power`)
  AND the per-charger flow sensors
  (`sensor.sem_charger_<id>_flow_solar_to_ev_power` etc.). The flow
  sensors were added in v1.6.9 (`feature/169-per-charger-flows`) for the
  flow card — they were never meant to register as chargers. Every
  multi-charger install where `sensor.py:1633-1695` emits flow sensors
  (gated on `len(ev_chargers) > 1`) got 3 ghost sections per real charger.

  Fix: `if (eid.includes('_flow_')) continue;` guard before the regex
  match in both card files. Bundle rebuilt — content-hashed resource URL
  invalidates browser cache on upgrade.

  Earlier #356 fixes (`e733212` PR #371 hero-collapse, `68cee34` M3
  bottom-bar gate) targeted a different (real but smaller) duplication
  pattern inside one card; they couldn't address the ghost-section
  cascade because the source was upstream in the discovery loop.

### Tests

`tests/test_356_charger_discovery_filter.py` — source-level lint
asserting both card files contain the `_flow_` guard inside the
discovery window, plus a property-style test feeding sample entity IDs
through the regex+guard combination to confirm flow sensors are rejected
and real charger IDs (including those with legitimate underscores like
`laadpaal_links`, `ev_charger`, `keba_p30`) still resolve correctly.

**Total suite: 2904 passed, 0 failed, 0 xfailed.**

## [1.7.0-beta.9] — 2026-06-02

**Hotfix on top of beta.8.** No SEM logic changes — purely a dashboard
card render bug + a missing translation. Users who installed beta.8 saw
an invisible `sem-solar-card` (the bug below) and a raw key
`PV_STRINGS_TODAY` in the per-string section.

### Fixed

* **sem-solar-card was rendering as a 0x0 element on every viewport.**
  The `html\`...\`` Lit template at `sem-solar-card.js:406` contained
  literal backticks (markdown-quoted `nothing`). JavaScript read those
  as terminating the outer template literal — Lit's minified `html` tag
  threw `H(...) is not a function` at parse time. HA's lovelace renderer
  swallowed the console error and left an empty shadowRoot, so the card
  was conspicuously missing on mobile.
* **Missing `pv_strings_today` translation.** The per-PV-string section
  title rendered as the raw key `PV_STRINGS_TODAY` (CSS upper-casing the
  missing key) instead of the translated string. Added to all 15
  supported languages.

Both fixes target the bundled card (`dashboard/card/dist/sem-cards.js`
was rebuilt) — they take effect after the next browser cache-bust on
upgrade.

## [1.7.0-beta.8] — 2026-06-02

The **disagreement-audit close-out + KEBA solar-flicker resilience** release.
Lands every remaining item from the post-#349 umbrella audit (#351 — 13/13
closed), the KEBA actuator IDLE debounce that prevents transient solar-sensor
dropouts from cascading into "authorization rejected", and a multi-inverter
PV-strings discovery fix surfaced by @RienduPre's #378 dump.

### Fixed

* **#351 H1** — Per-charger `_calculate_remaining_need` now reads
  `self._daily_ev_per_charger.get(cid, energy.daily_ev)` when `charger_cfg`
  is set. Pre-fix charger B's "target reached" check was polluted by
  charger A's energy.
* **#351 H2** — Forecast night-target reduction applied per-charger inside
  the multi-charger loop, gated on `_mode_uses_smart_night(cfg)`. Secondary
  chargers no longer ignore the "tomorrow is sunny → skip tonight" decision.
* **#351 M1** — Cost accumulators (daily / monthly / yearly) now round-trip
  through `Storage.export_energy_calculator_state`. Pre-fix `daily_savings`
  silently reset to 0 mid-day after every HA restart while
  `daily_solar` resumed from disk.
* **#351 M2** — `CostData.daily_total_savings` (+ monthly / yearly variants)
  now computed as the headline number spanning solar + battery savings.
  Pre-fix `daily_savings` (solar-only) was the only surfaced number and
  understated savings on battery-assist days.
* **#351 M3** — Per-charger session reads `power_flows.per_charger[cid]`
  directly when populated, preserving the priority-correct attribution.
  Pre-fix the proportional re-split discarded the priority signal that the
  flow calculator just computed.
* **#351 M4** — Per-charger effective states surface as
  `charger_<id>_charging_state` on `coord.data` and as the
  `per_charger_states` dict on the `sem_charging_state` sensor. Mixed-mode
  fleets now show the disagreement explicitly instead of hiding behind the
  fleet headline.
* **#351 M5** — `SurplusController.distribute_ev_budget` accepts an
  `excluded_charger_ids` set; chargers in `charge_mode=off` get 0 W
  allocation (dashboard still sees the entry).
* **#351 M6** — `notify_ev_nearly_full` gates on this charger's
  `power.ev_power_per_charger.get(cid)` instead of the fleet `ev_charging`
  flag.
* **#351 M7** — Per-charger session-end falls back to
  `power.ev_connected_per_charger.get(cid)` when no per-charger plug
  sensor is configured. Pre-fix per-charger sessions could never end while
  another charger was plugged in.
* **#351 M8** — `_skip_recorded_tonight` converted to
  `Dict[str, bool]` keyed by charger_id; per-charger intel builder
  records skips per-charger so charger A's skip no longer masks
  charger B's independent counter.
* **#351 M9** — Eliminated mutable-attr-read pattern in
  `_build_charging_context` and the per-charger loop. Both call sites
  now capture `self._cycle_vehicle_soc` into a local before the two
  `_calculate_remaining_need` calls.
* **#351 M10** — `SOLAR_PAUSE_STATES` clears `_ev_charge_started_at`.
  Pre-fix the disable-delay timer was consumed during a battery-priority
  pause and the very next cycle's terminal branch fired stop_session
  even though we just resumed.
* **#351 M11** — Night-skip notification gates on
  `_mode_allows_night_charging(cfg)`. Modes `off` / `solar_only` no longer
  get spurious "skipped night charge" pushes.
* **#351 L1** — `_update_battery_session_tracking` integrates against
  `self.update_interval.total_seconds()` (the actual cycle time) not
  `config["update_interval"]` (the requested one). Under HA load the two
  diverge and the battery-session counter drifted.
* **#351 L2** — `FlowCalculator.calculate_energy_flows` emits
  `DeprecationWarning` from the body. The proportional-allocation path is
  un-canonical; `integrate_energy_flows` is the timing-aware production
  path.
* **#378** — `discover_pv_strings_from_registry` now honours the explicit
  `solar_power_list` from the HA Energy Dashboard when it has ≥2 entries.
  Pre-fix the discoverer scoped sibling-scan to the seed's `config_entry`,
  silently dropping cross-inverter MPPTs and leaking entities not in the
  user's dashboard. @RienduPre's multi-inverter setup (3 entries in
  `solar_power_list`) now surfaces all 3 as `pv1`/`pv2`/`pv3`.

### Added — KEBA solar-flicker resilience

* **IDLE debounce in the actuator** (`coordinator/actuate.py` +
  `ChargerAdapter.attempt_idle` + `reset_idle_debounce`). When a transient
  solar-sensor reading triggers a 1-cycle `intent=idle`, the actuator
  holds the previous setpoint instead of immediately calling `keba.disable`.
  Default threshold = 4 cycles (~40 s grace). Catches the pattern observed
  live on PROD 2026-06-02: Huawei sensor flicker 8 kW → 0 W → 8 kW within
  10 s → `keba.disable` → KEBA stuck in "authorization rejected" until
  physical replug. Real cloud passes (>40 s) still cross the threshold and
  `command_idle` fires normally.
* Debounce state lives on `ChargerAdapter` (per-charger, not a module-level
  dict) so multi-charger fleets count independently per charger.
* INFO-level log on both branches:
  `actuate(<cid>): IDLE — count=N/4 — <reason>` (fired) or
  `actuate(<cid>): IDLE DEBOUNCED — count=N/4, holding previous setpoint`
  (absorbed).

### Tests

* `test_351_umbrella_regression.py` — 23 tests covering every umbrella
  item (per-fix assertions + structural anchor lint).
* `test_379_growatt_pv_strings.py` — 3 new tests for #378 (multi-inverter
  list wins, single-entry falls through, empty list preserves legacy).
* 3 new edge-case scenarios + harness extensions for per-cycle
  `tariff_level` and the negative `strategy_not_substring` assertion.

**Total suite: 2900 passed, 0 failed, 0 xfailed.**

### Known not-fixed

* **#356** — duplicate tiles in the EV dashboard. @RienduPre confirms the
  symptom persists on beta.6 (which has the hero-collapse + bottom-bar
  fixes). Needs a UI screenshot to identify the remaining duplication
  source — replied on the issue asking for one. Target beta.9.
* **Solar sensor flicker root cause** — the actuator debounce is a
  band-aid. The Huawei inverter's intermittent 0 W readings should be
  EMA-smoothed in `coordinator/sensor_reader.py`. Separate issue worth
  filing.

## [1.7.0-beta.7] — 2026-06-02

The v1.7 arch capstone — the **FleetCycleState refactor** that
structurally retires the gap class behind the three production fixes
shipped in beta.5 (SOLAR_ONLY redirect, tariff_level, night-plan
ordering). Plus 4 more transition-class scenarios.

### Production refactor — FleetCycleState as single source of truth

The three beta.5 production fixes were tactical patches for one
structural smell: `build_charger_view` had each call site
re-resolving fleet-level inputs (forecast, tariff, is_night, etc.)
independently. The primary view in `_build_charging_context` and
the multi-charger loop each handled this differently — and any
new fleet input added would land in only one of them.

The fix: **`FleetCycleState`** — an immutable per-cycle struct
holding every fleet-level input that any charger's `decide()` could
need. Built ONCE per cycle by
`coordinator._build_fleet_cycle_state`. `build_charger_view` now
takes it as the first positional arg and derives the per-view
`FleetContext` from it. Per-charger overrides (`target_kwh`,
`deadline_amps`, `tariff_wait`, `solar_committed_w`) stay as direct
kwargs because they legitimately vary across chargers in the same
cycle.

What this eliminates:

* The 3 separate inline blocks resolving forecast/tariff/is_night
  per call site
* The asymmetry where multi-charger loop saw `tariff_level` but
  primary didn't (and similar for other fields)
* The "did I remember to plumb the new field?" mental load every
  PR that touches fleet state

The structural guarantee: any future fleet-level input is a
**one-place change** (add the field to `FleetCycleState`).

### Enforcement — AST lint as a CI gate

`tests/test_fleet_state_completeness.py` walks `coordinator/` AST
and fails CI if any `build_charger_view` caller:

  * Forgets the `fleet_state` positional, OR
  * Passes any of the deprecated fleet-level kwargs (`power_reading`,
    `is_night`, `config`, `tariff_level`, `forecast_remaining_kwh`)

Catches the regression class on PR review, not at runtime. Same
shape as the existing FLEET-READ AST lint at
`tests/test_ev_control_fleet_reads.py`.

### Invariant tests

`tests/test_fleet_cycle_state.py` pins the behavioural contract:

  * `FleetCycleState` is frozen — instances cannot mutate
  * Equal inputs produce equal instances (value-type semantics)
  * Two views built from the same `FleetCycleState` in the same
    cycle agree on every fleet-level field (only
    `solar_committed_w` differs per view, by design)

### Transition-class scenarios

Four new YAML scenarios in `tests/scenarios/` covering state
transitions that steady-state scenarios miss:

* `sunset_transition` — solar drops + `is_night` flips false→true.
  solar_only must IDLE on the night-mode flip.
* `sunrise_transition` — mirror: `is_night` true→false + solar
  rising. min_plus_solar transitions cleanly out of MIN_PV.
* `multi_charger_plug_events` — two solar_only chargers, one
  unplugs mid-timeline. Pins per-charger budget conservation
  under plug-state changes.
* `full_day_replay` — 24h walkthrough on 10-min cycles (144
  cycles, runs <1s). Catches daily-integrator drift, state
  machine blips on zone boundaries.

Plus two harness extensions enabling these:
`ev_connected_per_charger` / `ev_charging_per_charger` (per-charger
plug state) and a per-row `is_night` override (for sunset/sunrise
walks).

### Verification

2879 tests passing, 7 skipped, 0 failed, 0 xfailed (~35s runtime).
+16 tests since beta.6 (4 scenarios + 7 FleetCycleState contract
tests + 4 misc + the AST lint's 3).

22 scenarios total now.

---

## [1.7.0-beta.6] — 2026-06-02

Diagnostic surface expansion for two more reported issues — same
pattern as beta.5's `per_source_lists` (one-shot triage from the
diagnostics dump alone).

### Diagnostics

- **#379 — PV string discovery state.** New
  `pv_strings_discovery` top-level block surfaces what the
  `_sensor_reader` resolved from both the direct-power-pattern
  scan and the V+I synthesis pair scan. Lets a "PV2 is empty"
  report be triaged in one shot: empty dict → discovery missed
  entirely; partial dict → one pattern matched but others didn't;
  full dict → bug is downstream in the card rendering.

- **#357 — Per-charger adapter state.** New `charger_adapters`
  top-level block surfaces the resolved adapter class +
  brand-specific discovery state per charger. For `WallboxAdapter`
  specifically:
  `wallbox.pause_switch_searched`, `pause_switch_entity`,
  `pause_switch_discovered`. Lets a "Wallbox keeps charging
  despite mode=off" report point at the failing step on the
  first dump: false → the discovery couldn't find a
  `switch.*pause_resume` entity for this Wallbox model;
  true → adapter wired right, problem is downstream.

### Verification

2863 tests passing, 7 skipped, 0 failed, 0 xfailed (~35s runtime).
4 new tests in ``tests/test_357_wallbox_diagnostics.py``.

---

## [1.7.0-beta.5] — 2026-06-02

Testing-framework adoption + three structural arch fixes + diagnostic
surface for fleet-aggregation bug triage. Built on top of beta.4.

### Production fixes (post-#358 arch follow-up)

- **`SOLAR_ONLY` forecast-aware battery redirect restored.** Post-arch
  `decide.py::SolarOnlyMode` was checking bare surplus against the
  charger min (4140W), returning IDLE, and the canonical strategy
  chain collapsed to IDLE — so the redirect branch in
  `flow_calculator.calculate_canonical_ev_budget` was unreachable.
  Fix: extracted `battery_redirect_w` as a module-level helper,
  plumbed `forecast_remaining_kwh` through `FleetContext` +
  `build_charger_view`, made `SolarOnlyMode.decide()` add redirect
  to its surplus calculation BEFORE the min check. Caught by
  scenario `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`.

- **`tariff_level` plumbed into primary view.**
  `SolarPlusCheapMode.decide()` reads `view.fleet.tariff_level` for
  the expensive-window pause (#247), but the primary view was being
  built without it (was `None`). Fix: pull `current_level` from
  `_tariff_provider` and pass to `build_charger_view`.

- **Night-plan ordering — hoisted before primary view.**
  `_compute_night_plan` was computed AFTER the primary view's
  `decide()` ran, so `tariff_wait` (#247) and `deadline_amps`
  (#246) didn't reach `SolarPlusCheapMode` / `MinPlusSolarMode`
  for the primary charger. Fix: hoisted the plan to before the
  primary view in `_build_charging_context`.

All three are the same class — info the legacy
`_determine_charging_strategy` had access to wasn't fully plumbed
into the new `decide.py` path. A structural refactor to eliminate
the gap class (single `FleetCycleState` builder + AST lint) is
planned for v1.8.

### Diagnostics — #378 triage support

- `diagnostics.py` now captures `energy_dashboard.per_source_lists`
  (`solar_power_list` / `battery_power_list` / `grid_power_list`
  from the Energy Dashboard config) AND
  `energy_dashboard.per_source_readings` (each entity's current
  state, or `{"state": "missing"}` if it disappeared from
  `hass.states`). For multi-inverter / multi-battery / multi-grid
  setups, this makes "fleet sensor underreports" reports one-shot
  triagable from the diagnostics dump alone.

  Triage flow: open `per_source_lists.battery_power_list`, compare
  against what the user reports they have. If the list is missing
  an entity → bug is in discovery / HA Energy Dashboard config. If
  the list has the entity but reading is `"missing"` or
  `"unavailable"` → bug is in the sensor source itself.

### Testing framework adoption

Adopted `pytest-homeassistant-custom-component==0.13.205` (the
official HA test framework — used by HACS itself, ~30 of Frenck's
integrations, required by Quality Scale Silver+). SEM is already
declared `quality_scale: platinum`; this work validates that claim
structurally.

- Real `HomeAssistant` fixture for config-flow, services, migrations,
  and the scenario harness — replaces dict-mock approach where it
  matters for end-to-end correctness.
- Legacy `hass` fixture renamed to `mock_hass` via AST-aware libcst
  rewrite (35 files, 419 test signatures). No behaviour change in
  existing tests; the framework's `hass` fixture is now usable.
- Migration chain (`async_migrate_entry` v1→v7) now has 8 real-hass
  tests covering every hop + the full chain composition.

### Scenario suite — wired into CI for the first time

The 5 scenario YAMLs in `tests/scenarios/` had been silently broken
since PR #358: the harness called the deleted
`_determine_charging_strategy` inside a bare `try/except: pass`, so
every cycle produced `strategy=None`, `budget=0`, `amps=0` — and the
scenarios "passed" on the null outputs. The harness now drives the
real production decision path (`coord._build_charging_context`),
raises loudly on `AttributeError`, and is wired into pytest
discovery via `tests/test_scenarios.py`.

Eight new YAML scenarios mined from closed bug issues — one per
EV-charge-mode × regime cell:

- `solar_only/night_must_idle` (#346)
- `solar_only/zone3_day_redirect` (#282)
- `min_plus_solar/zone3_day_battery_assist` (#282)
- `min_plus_solar/night_top_up_at_min` (#268)
- `min_plus_solar/night_deadline_floor` (#246)
- `solar_plus_cheap/day_normal_tariff` (#247)
- `solar_plus_cheap/night_cheap_window_charges` (#247)
- `always_max/ignores_zone_and_tariff`
- `multi_charger/priority_cascade_with_mixed_modes`

Plus `tests/test_scenario_coverage.py` — a matrix test that fails
listing missing cells with their issue hints. New EV-charge modes or
regimes that land without scenario coverage fail CI with a clear
to-do.

### Property-based invariants

`tests/test_budget_invariants.py` — 10 `hypothesis`-driven tests over
the canonical EV budget math. Invariants: `net_w >= 0` and finite
across all 6 strategies, IDLE always zero, NOW returns override,
`SELF_CONSUMPTION` never includes redirect, `SOLAR_ONLY net_w ==
solar_surplus + battery_redirect`, amps floored not rounded.

### User-reported regression guards

- **#378** (multi-battery aggregation) — 6 tests pinning
  `PowerReadings` + `fleet_battery_w` so future arch changes can't
  silently drop a battery from the sum.
- **#379** (Growatt PV-string discovery) — 5 tests pinning Growatt
  naming patterns + the "missing entity" diagnostic path.
- **#307** (pool heat pump as surplus device) — 7 tests verifying
  `SurplusController` dispatch to non-EV devices.
- **#49** (surplus controller restart safety) — 5 tests pinning that
  `ControllableDevice` defaults to `PEAK_ONLY` (so SEM never
  proactively activates a device the user didn't opt into).
- **#353** (KEBA 0A self-charge) — 19 adapter-unit tests pinning that
  `command_current(<6A)` always routes to `command_idle()` (=
  `keba.disable`), never `set_current(0)`.

### Internal

- 2859 tests passing, 7 skipped, 0 failed, 0 xfailed (~34s runtime).
- Release workflow now installs from `tests/requirements_test.txt`
  (was a hardcoded list missing `pytest-homeassistant-custom-component`).

---

## [1.7.0-beta.4] — 2026-06-02

Private beta (not published to HACS) — bundles the multi-device
architecture follow-up on top of beta.3 for an internal PROD soak.

### Fixed
- **#375** — True per-battery control loop. `_battery_adapter`
  (singular) → `_battery_adapters: Dict[str, BatteryControlAdapter]`;
  `_run_battery_pipeline` iterates `power.batteries`, dispatching
  `decide_battery` / `actuate_battery` per battery with its own
  cached adapter. Closes the architectural gap the v1.7.0 rebuild
  left behind for 2× same-brand installs (2× Huawei LUNA2000,
  2× GoodWe). Single-battery installs see zero behavioural change
  (PR #376).

## [1.7.0-beta.3] — 2026-06-01

Beta batch addressing 5 open user-reported issues + dead-code cleanup
from #351's audit deferred list.

### Fixed
- **#352** — Manual `grid_sign_invert` config option for Enphase and
  other inverters where the energy-counter auto-detect can't
  stabilise on the grid power polarity (PR #370).
- **#355** — Bumped EV target slider max from 100 to 200 kWh so the
  Min and Max handles have drag-room when both sit at the previous
  cap (PR #368).
- **#356** — Collapsed the duplicated hero metrics on the EV status
  card when per-charger sections render — the gate was `> 1`
  instead of `>= 1`, so 1-charger installs saw both layers. Hero
  now shows only Status + Power when ≥1 charger sections will
  render below (PR #371).
- **#357** — New dedicated `WallboxAdapter` that auto-discovers the
  Wallbox `pause_resume` switch from the HA entity registry and
  toggles it explicitly on `command_idle` / `command_disable` in
  addition to `_set_current(0)` + `stop_session()`. Closes the
  v1.6.17 reporter's bug where mode=off didn't stop the Pulsar
  (PR #372).
- **#359** — Percentile-based tariff price classification (default
  for dynamic tariffs). The legacy static 0.15/0.35 CHF cutoffs
  mis-bucketed everything on Tibber/Octopus/Amber/Nordpool where
  daily ranges span €0.05–€0.80. Buckets now compute relative to
  today's 24h distribution. Static mode preserved as opt-out
  (PR #373).

### Removed
- `coordinator._execute_battery_charge_scheduler` (91 LOC) and
  `coordinator.BatteryProtectionMixin._apply_battery_discharge_protection`
  (66 LOC) — both retired by the v1.7.0 per-device-primary
  rebuild; zero live callers since the `_run_battery_pipeline`
  flip. `BatteryProtectionMixin` survives this release with only
  `_restore_battery_discharge_limit_on_startup` (planned full
  retirement in v1.7.1) (PR #369).

## [1.7.0] — 2026-06-01

Major release. Two headline themes:

1. **Multi-device architecture rebuild** — every multi-device data
   point in SEM (chargers, inverters, batteries, PV strings) now
   flows through the same per-device-primary pattern: `Dict[str, X]`
   is the source of truth, fleet aggregates are `@property` views.
   Brand hardware quirks (KEBA's 6 A minimum, set_current(0)
   rejection, self-resume detection, Huawei/GoodWe battery force-
   charge) are encapsulated in dedicated adapter modules. EV
   control flows through one pure `decide(view) → ChargerDecision`
   → `actuate(decision, adapter)` pipeline; batteries get the same
   `decide_battery / actuate_battery / BatteryControlAdapter`
   treatment. The strategy/state-machine disagreement class that
   produced the 14-bug cluster between v1.6.0 and v1.6.17
   (#243, #284, #289, #290, #291, #308, #315, #316, #318, #344,
   #345, #346, #349, #353) is **structurally retired** — those
   disagreements cannot exist by construction because there's only
   one decision authority per device per cycle.

2. **Per-PV-string visibility (#312)** — Sunsynk-style per-string
   display on three SEM cards, plus V+I synthesis for inverters
   that expose voltage and current but no per-string power.

The architecture work shipped as four PRs into develop (#358 EV
rebuild, #360 inverter+battery PowerReadings dicts, #361 battery
decide/actuate/adapter, #362 EnergyTotals @property views, #363
93 surplus-charging scenario tests). The per-PV-string work
shipped as three PRs (#337 data layer, #338 cards, #339 docs).
All consolidated under one release tag.

### Architecture rebuild — what changed structurally

**Per-charger primary** (PR #358, 8 steps):
- New frozen types in `coordinator/charger_types.py`: `ChargerPower`,
  `ChargerEnergy`, `ChargerIntent`, `ChargerDecision`, `ChargerView`,
  `FleetContext`, `FleetView`, plus the symmetric inverter/battery
  types (PR #360/#361).
- `ChargerAdapter` ABC + `KebaAdapter` + `GenericAdapter` in
  `coordinator/charger_adapters/`. Every KEBA quirk that bit
  production (6 A min, set_current(0) rejection, self-resume on
  plug-in, charging_state lag, 500 W handshake cutoff) is one
  method on this protocol. New brands subclass; the actuator never
  changes.
- Pure `decide(view) → ChargerDecision` in `coordinator/decide.py`
  with one `ModeStrategy` class per charge mode (`off`,
  `solar_only`, `min_plus_solar`, `always_max`, `solar_plus_cheap`).
  No `self`, no HA calls — same input always produces the same
  output.
- `actuate(decision, adapter)` in `coordinator/actuate.py` — pure
  intent dispatch. One branch per `ChargerIntent`. The
  #315/#346/#353 self-resume guards collapse into one
  `adapter.is_self_charging()` check before the new intent is
  applied.
- Coordinator `_per_charger: Dict[str, ChargerRuntime]` consolidates
  what used to be 8 parallel `_*_per_charger` dicts.
- The legacy `_determine_charging_strategy`,
  `_self_consumption_strategy`, `_zone_based_strategy`,
  `_canonical_strategy_from_legacy`, and the `_raw_zone`/`_get_zone`/
  `_debounce_zone` helpers — **deleted** (−354 lines in
  `coordinator.py`). The new pipeline is the only control path.
- Per-charger native priority flow attribution in
  `flow_calculator.py`: when multiple chargers consume from the
  same surplus, the priority allocator splits sources in order
  (higher-priority chargers get first claim on solar, fall back to
  battery, fall back to grid). Replaces the pre-#349 proportional
  fraction-of-fleet split.

**Per-inverter + per-battery primary** (PR #360, #361, #362):
- `PowerReadings.inverters: Dict[str, InverterPower]` and
  `PowerReadings.batteries: Dict[str, BatteryPower]` — populated by
  `sensor_reader` for multi-device installs (`len(...list) > 1`).
- `@property fleet_solar_w`, `fleet_battery_w`, `fleet_battery_soc`
  on `PowerReadings` — sum / capacity-weighted-average from the
  dicts. Empty dict on single-device installs → falls back to the
  legacy `solar_power` / `battery_power` / `battery_soc` fields.
  Zero churn for existing consumers.
- `EnergyTotals.per_inverter` / `per_battery` dicts plus
  `daily_solar_view` / `daily_battery_charge_view` /
  `daily_battery_discharge_view` `@property` accessors. Same
  fallback discipline.
- New `coordinator/battery_adapters/` module unifies what used to
  live in two separate places: discharge limiting (the legacy
  `BatteryProtectionMixin`) and forced charging (the legacy
  `BatteryChargeAdapter`). `BatteryControlAdapter` is one ABC with
  four methods (`command_normal`, `command_limit_discharge`,
  `command_force_charge`, `command_stop_force_charge`); each maps
  1:1 to a `BatteryIntent`. Huawei, GoodWe, and Generic adapter
  implementations wrap the existing brand-specific service calls.
- `decide_battery(view) → BatteryDecision` and
  `actuate_battery(decision, adapter)` — same pure-pipeline shape
  as the EV side. Replaces the dual-axis legacy split
  (`BatteryProtectionMixin._apply_battery_discharge_protection` +
  `BatteryChargeScheduler.update`).
- The pure planner `BatteryChargeScheduler.evaluate()` is preserved
  verbatim — it produces a `SchedulerDecision` that feeds
  `BatteryView.scheduler_decision`. Only the dispatch path changed.

**Invariant test suite** (PR #358 + #363):
- `tests/test_step8_invariants.py` — **233 architectural contracts**
  parametrised across `(mode × solar × battery_soc × home ×
  is_night × num_chargers)`. Each invariant pins one property the
  architecture is supposed to guarantee by construction. A breaking
  change in any module surfaces immediately at CI time, not in
  production.
- `tests/test_surplus_charging_scenarios.py` — **93 behavioural
  scenarios** walking every (mode × battery SOC zone × time-of-day
  × solar level) combination through `decide → actuate → adapter`.
  Includes a full-day timeline (`dawn → morning → noon → afternoon
  → evening → dusk`) with realistic numbers.
- `tests/test_inverter_battery_arch.py` — **27 tests** pinning the
  inverter/battery types, adapter dispatch, hysteresis, factory
  selection.
- `tests/test_multi_inverter_battery_primary.py` — **23 tests** for
  the PowerReadings dicts + fleet `@property` accessors.

Full suite: **2733 passed**, 7 skipped (was 2337 at v1.6.14
baseline → **+396 new tests**). The simulation-driven verification
approach replaces the previous "deploy and watch logs" cycle —
hardware test windows are scarce; deterministic CI scenarios run
in under a second and gate every PR.

### Compatibility notes

- **Zero user-visible behaviour change for single-device installs.**
  The fleet `solar_power` / `battery_power` / `ev_power` fields stay
  populated as cached sums; every existing sensor and dashboard
  card continues to read them unchanged. The new `@property` views
  are additive.
- **Multi-device installs see better-quality flow attribution.**
  A two-charger setup where one is in `solar_only` and the other in
  `min_plus_solar` previously got a proportional split that
  attributed grid to the solar-only charger; now the priority
  allocator correctly routes solar to the higher-priority charger
  first.
- **`charge_mode = solar_only` no longer charges from grid at night.**
  Fixed in v1.6.17 (#346) and structurally retired by the new
  decide-time mode gate in v1.7.0.
- **Storage format: backward-compatible.** Pre-v1.7.0 snapshots
  restore unchanged (no new keys present → empty dicts → fallback
  to legacy fields).
- **Legacy code paths retired:** `_determine_charging_strategy`,
  `_self_consumption_strategy`, `_zone_based_strategy`,
  `_canonical_strategy_from_legacy`, `_raw_zone`, `_get_zone`,
  `_debounce_zone`. `BatteryProtectionMixin` and the per-brand
  `BatteryChargeAdapter` subclasses (`HuaweiChargeAdapter`,
  `GoodWeChargeAdapter`, `GenericChargeAdapter`) are still in the
  tree as backward-compat shells — the new `BatteryControlAdapter`
  wraps them internally. They can be deleted in v1.7.1 after the
  PROD soak window.

### What's queued for v1.7.1

- Per-inverter / per-battery dashboard sensors (gated on
  `len(...) >= 2`).
- Per-inverter / per-battery flow attribution in `flow_calculator`
  (the destination-side view of "which inverter's solar fed where").
- `sensor_reader` migration to populate
  `EnergyTotals.per_inverter` / `per_battery` each cycle (so
  `daily_solar_view` becomes authoritative on multi-inverter
  installs).
- Delete `BatteryProtectionMixin` + `BatteryChargeAdapter` shells
  after PROD soak proves the new pipeline.
- Per-string-to-destination attribution (#312 originally deferred —
  now buildable on top of the per-inverter flow work).

---

### Per-PV-string visibility (#312)

Closes the long-standing @MRAK96 request for Sunsynk-style per-string
display: SEM had the auto-discovery (`hardware_detection.discover_pv_strings_from_registry`,
8 inverter brands) for the optional HACS K-Flow card since v1.5.x
but never promoted per-string to SEM's own surface. v1.7.0 ships
the full stack: data layer, sensor entities, card rendering, and
user docs — internally implemented as three discrete phases so
each piece could be reviewed and tested independently on HA-TEST,
but published as one user-visible release.

### Added

- **Per-PV-string power + daily-energy sensors** (gated on
  `len(strings) >= 2`):
  - `sensor.sem_pv_string_<slot>_power` (W, MEASUREMENT)
  - `sensor.sem_pv_string_<slot>_daily_energy` (kWh, TOTAL,
    daily-reset)
  where `<slot>` is the normalised label `pv1`, `pv2`, … (max 4
  per discovery's slot cap). Single-string installs see no
  change.
- `PowerReadings.solar_power_per_string: Dict[str, float]` — the
  source-side mirror of v1.6.9's `ev_power_per_charger`. Sum
  invariant: `sum(values) ≈ solar_power` within rounding.
- `EnergyFlows.per_string: Dict[str, StringEnergy]` — daily kWh
  per string, integrated by `FlowCalculator.integrate_energy_flows`
  alongside the fleet and per-charger accumulators.
- `PowerFlows.solar_per_string: Dict[str, float]` — pass-through
  carrier from readings to the integrator (strings are sources,
  no destination attribution math required).
- `StringEnergy` dataclass (1 field: `energy_kwh`).
- `SensorReader.set_pv_strings(...)` registers the discovered
  per-string sensors; the per-cycle read loops in both the
  Energy-Dashboard and legacy paths populate
  `readings.solar_power_per_string` when the gate trips.
- Auto-discovery wired through coordinator: the existing
  `hardware_detection.discover_pv_strings_from_registry`
  (Huawei / GoodWe / Growatt / Kostal / Sungrow / Fronius /
  SolarEdge / Victron) now also feeds SEM's own sensors.
- **V+I synthesis fallback**
  `hardware_detection.discover_pv_string_vi_pairs` — when an
  inverter exposes per-string voltage + current but no
  per-string power sensor (Huawei Solar Modbus, generic
  Modbus drivers, Solarman bridges), SEM detects sibling
  `pv_N_voltage` + `pv_N_current` pairs and multiplies V × I
  at read time to synthesise the per-string watts. Surfaces
  the same `sensor.sem_pv_string_<slot>_power` entities as
  the direct-power path; downstream consumers (cards, energy
  accumulator, sum invariant) don't know which way the value
  was sourced. Voltage / current patterns accept English
  (`voltage` / `current` / `volt` / `amp`) and German
  (`spannung` / `strom`) suffixes. When the same slot has
  BOTH a direct power sensor AND a V+I pair, the direct
  sensor wins (slightly more accurate — accounts for the
  inverter's MPPT efficiency math). Confirmed on HA-PROD
  2026-06-01: Huawei `inverter_pv_1_spannung` +
  `..._strom` pair now feeds `sensor.sem_pv_string_pv1_power`
  via this path.
- **Per-PV-string chip strip** on three cards, auto-shown when
  ≥ 2 strings are present. Each chip shows `PVn N.NN kW` and
  links to the underlying sensor entity on tap.
  - `sem-flow-card`: chips above the SVG flow diagram.
  - `sem-solar-card`: chips above the hero arc ring.
  - `sem-system-diagram-card`: chips above the illustrated
    diagram as a compact HUD.
- `semDiscoverPVStrings(hass, prefix)` shared card helper —
  reads `sensor.{prefix}pv_string_pv1_power` … `pv4_power`,
  returns `[]` when fewer than 2 present so callers can pass
  the result straight to a Lit `html` template.
- `semPVStringsCSS` shared style block.
- **New user reference doc**
  [`docs/PV_STRINGS.md`](docs/PV_STRINGS.md) — what sensors get
  created, supported inverter brands with regex pattern table,
  how discovery works, "what if I don't see my strings"
  troubleshooting flow, internals pointer table, and the
  out-of-scope list (per-string-to-destination attribution,
  per-string cost, Solcast multi-plane — file-an-issue links).

### Fixed

- **Flow attribution: priority-based instead of proportional (#349)** —
  HA-PROD 2026-06-01 dashboard showed `flow_grid_to_ev_energy =
  6.633 kWh` on a day when the actuator's `session_solar_share` said
  the car was 91 % solar. Root cause: SEM split every source across
  every destination by demand percentage, attributing grid to the EV
  whenever the home battery was simultaneously charging (the battery
  was actually the grid-paid consumer; EV was on solar). The model
  also overshot destinations when supply ≠ demand exactly.

  New model: sources drain in priority `solar → battery_discharge →
  grid_import`; destinations served in priority `home → ev →
  battery_charge → grid_export`. Each watt is attributed to exactly
  one (source, destination) pair. The conservation invariants hold:
  for each destination, sum of (source→destination) flows = demand;
  for each source, sum of (source→destination) flows = supply. 14
  new tests in `tests/test_349_flow_priority_attribution.py` pin
  both. The previously misleading `flow_grid_to_ev` should now match
  user intent — solar covers EV first when there's enough.

- **EV charges overnight in `charge_mode=solar_only` (#346)** —
  also shipped as the v1.6.17 hotfix. `_determine_charging_strategy`
  returned `"night_grid"` unconditionally when `is_night_mode()` was
  True, ignoring the per-charger `charge_mode`. Strategy now consults
  `MODE_NIGHT_ALLOWED` first: `solar_only` at night → `idle`; `off` →
  `disabled`; other modes unchanged. Defence in depth: actuator self-
  resume guard extended from `{"disabled"}` to `{"disabled", "idle"}`
  so future strategy disagreements land safely.
- **Autarky reported 0% when battery overnight-charged from grid
  (#344, #345)** — fleet-summed `daily_grid_import` was treated as
  unconditional autarky penalty, including the grid-to-battery slice
  that doesn't displace home consumption. Then a second pass (#345)
  switched the formula to fully flow-attributed accumulators
  (`solar_to_home + solar_to_ev + battery_to_home + battery_to_ev`
  over total consumption) so the temporal mismatch between sunrise-
  reset `daily_ev` and calendar-reset `flow_grid_to_ev` no longer
  drowns the numerator.

### Changed

- Day rollover in `FlowCalculator.integrate_energy_flows` now
  also clears `_per_string_accumulators` alongside fleet and
  per-charger.
- Snapshot persistence (`get_flow_accumulator_state` /
  `restore_flow_accumulator_state`) gains a `per_string` key,
  emitted only when non-empty. Pre-v1.7.0 snapshots restore
  bit-for-bit identical (no `per_string` key → no per-string
  state).

### Tests (18 new)

`tests/test_per_string_energy.py`:
- Back-compat: empty per_string dict in single-string setups.
- Sum invariant: 2-string and 4-string splits.
- Multi-cycle accumulation.
- Day rollover clears per-string accumulator.
- Persistence round-trip (4 tests, incl. legacy snapshot
  back-compat).
- Bad-snapshot defence (3 tests: non-dict per_string, non-dict
  per-slot entry, non-numeric values).
- Idle-string preservation (clouded string keeps its surfaced
  kWh — no regression to 0 on the user-visible counter).
- `SEMData.to_dict` emission (key present when populated,
  omitted when empty).
- `SensorReader` gate (1 string → no pollution; ≥2 → populated).

Full suite 2281 green on Python 3.12 (2263 v1.6.14 baseline +
18 new). Bundle (`dist/sem-cards.js`) rebuilt with the chip
strip rendering for all three cards.

### Phase trail (internal)

Implementation shipped to develop as three feature PRs for
focused review, then consolidated to one user-visible v1.7.0
release per maintainer policy:
- PR #337 — data layer (sensors, types, sensor reader,
  flow calculator persistence).
- PR #338 — card rendering (3 cards, shared helper, bundle).
- PR #339 — user reference doc.

Manifest stays at 1.7.0.

## [1.6.14] — 2026-05-31

Multi-charger debt closeout. Bundles four pieces of work into one
release (the maintainer-set rule "no v1.7 until every multi-charger
follow-up is closed" pulled deferred ``v1.7+`` items back into
v1.6.x; this is them, packaged as one release rather than four
separate HACS bumps).

### Fixed

- **Surplus tracker jump-from-0 spike (#8)** —
  ``_apply_ramp_limit`` used to short-circuit on ``current < 1`` and
  return ``target_current`` directly, so a cold-start cycle handed
  KEBA a 14 A command from 0 A. KEBA's ~30 s physical actuator lag
  then caused a ~4.4 kW grid-import overshoot during the ramp
  (confirmed live on PROD 2026-05-31 at 10:43). Cold start now hands
  KEBA ``min_current`` (typically 6 A ≈ 4140 W on 3-phase EU);
  subsequent cycles climb via the existing ``±ramp_rate`` clamp at
  the user-configured ``ev_ramp_rate_amps`` (default 2 A/cycle, so
  target reached in ~4 cycles for a 14 A request). The stop-fast
  branch is preserved: ``target_current < 1`` still returns 0
  immediately so explicit-off / disable stays snappy. 13 new unit
  tests in ``tests/test_ramp_limit_8.py`` pin every branch.

### Changed

- **``effective_state`` and ``charger_name`` migrated onto
  ``PerChargerContext``** instead of writing the parallel
  ``_effective_states_per_charger`` dict from inside the loop body.
  The loop body assigns ``pcc.effective_state = …``; ``__exit__``
  persists ``(state, name)`` into the coordinator's dict so the
  post-loop ``_send_notifications`` dispatcher continues reading
  from a single map. The dict is the storage; pcc is the write
  path. Lets a future AST lint enforce field access at type level
  (no callsite outside the loop touches the dict directly).
- **``this_power_w`` precomputed in ``PerChargerContext.__enter__``**
  via ``coord._this_charger_power(ev_dev, power)`` and exposed as a
  typed field. The coordinator stashes the active pcc on
  ``coord._current_pcc``; ``_this_charger_power`` becomes a cache
  shim — when invoked with the same ``ev_dev`` it returns
  ``pcc.this_power_w`` instead of re-reading HA state. Replaces
  the three per-method ``this_power_w = self._this_charger_power(…)``
  local-var caches in ``coordinator/ev_control.py`` without
  changing the callsites. Helper exceptions in the precompute fall
  through to the legacy read path so a transient HA-state issue
  can't half-apply the swap.

### Added

- ``PerChargerContext.power``, ``this_power_w``, ``effective_state``,
  ``charger_name`` dataclass fields.
- ``SEMCoordinator._current_pcc`` short-lived pointer to the active
  context (``None`` outside any per-charger iteration).
- ``# FLEET-READ:`` annotation on the documented multi-charger
  fallback in ``_this_charger_power`` (only reached when a charger
  config omits ``ev_charging_power_sensor`` — rare).
- 47 new tests across three areas (13 ramp-limit + 14 pcc-field +
  20 per-charger flow):
  - ``tests/test_ramp_limit_8.py``: cold-start, near-zero,
    steady-state ramp, stop-fast, custom ``min_current``,
    end-to-end multi-cycle climb.
  - ``tests/test_per_charger_context.py``: effective_state
    persistence, this_power_w precompute, current-pcc-pointer
    lifecycle.
  - ``tests/test_this_charger_power_cache.py``: cache HIT, three
    MISS variants, kW→W conversion regression from #315.
  - ``tests/test_per_charger_energy_flows.py``: sum invariant,
    multi-cycle accumulation, day rollover, persistence
    round-trip (incl. legacy snapshot back-compat), edge cases
    (charger appears mid-day, charger idle in cycle,
    zero-interval), bad-snapshot defence, sensor-description
    generation gate.

- **Per-charger flow sensors (gated on ``len(ev_chargers) > 1``)**:
  ``sensor.sem_charger_<id>_flow_solar_to_ev_power``,
  ``..._grid_to_ev_power``, ``..._battery_to_ev_power`` (W,
  MEASUREMENT) plus matching ``..._energy`` (kWh, TOTAL, daily-
  reset). The Sankey card + HA Energy dashboard can now show
  per-charger EV sourcing instead of a fleet-proportional split —
  closes the @RienduPre observation on #316. Single-charger setups
  unchanged (fleet ``sensor.sem_flow_*_to_ev_*`` is authoritative).
  - ``ChargerEnergyFlows`` dataclass + ``EnergyFlows.per_charger``
    field.
  - ``FlowCalculator._per_charger_accumulators`` (kWh) integrated
    over time alongside the fleet accumulator; sum invariant
    pinned in tests.
  - Day rollover clears both fleet AND per-charger accumulators.
  - Snapshot persistence round-trip: new ``per_charger`` key
    under the existing snapshot dict; pre-v1.6.15 snapshots
    (without the key) restore bit-for-bit identical.
  - Accumulator semantic: once a charger appears, its kWh stays
    surfaced until the day rollover, even on cycles where the
    charger is idle (the user-visible counter must not regress
    to 0 just because the car unplugs).

- **``FleetEvPower`` newtype + global AST lint (v1.6.16 work)**.
  ``PowerReadings.ev_power`` is now typed as ``FleetEvPower`` — a
  ``float`` subclass that exposes ``.as_fleet_total(reason: str)``.
  Two equivalent ways to acknowledge a fleet read:
  - Comment form (v1.6.8 idiom, still valid):
    ``# FLEET-READ: <reason>`` on the same line or up to 5 lines
    above (walking back through ``#``-comment lines only).
  - Method form (preferred for new code):
    ``power.ev_power.as_fleet_total("<reason>")`` — the reason
    rides in the bytecode (mypy / IDE hover / ``git blame``)
    instead of an adjacent comment.

  Lint expanded to every module under ``coordinator/`` (was
  ``ev_control.py`` only). Exempt files: ``types.py`` (defines the
  field) and ``per_charger_context.py`` (docstrings only). The
  ~15 legitimate fleet reads got explicit ``# FLEET-READ:``
  reasons; one ``coordinator.py:3459`` stall-detection site
  migrated to the new method form as the in-tree demo.

  Sensor reader (the only writer) constructs ``FleetEvPower``
  instances at the assignment sites. Single-charger setups
  unchanged — ``FleetEvPower(value)`` reduces to a tagged float.

  12 new tests in ``tests/test_fleet_ev_power_reads_global.py``:
  - ``TestGlobalFleetEvPowerLint`` (6): every read acknowledged
    across coordinator/; exempt-list minimality; synthetic-code
    sanity (method form detected, bare read flagged, comment
    form still accepted).
  - ``TestFleetEvPowerNewtype`` (6): is float subclass,
    arithmetic works (no migration cost), ``.as_fleet_total``
    returns plain float, reason arg is documentation-only,
    default ``PowerReadings.ev_power`` is the newtype, repr
    includes class name.

### Why

Senior reviewer on the v1.6.7→v1.6.10 arc flagged ``effective_state``
and ``this_power_w`` as "works correctly; not on the context object."
Both shipped working — but the docs claimed "pcc is the single source
of truth for per-charger data" while these two lived in a parallel
dict and method-local vars. This release makes the doc honest.

The ``#8`` surplus-tracker spike fix bundled in here was confirmed
live on PROD 2026-05-31 during the v1.6.3 soak — held with the
refactor rather than shipped standalone so PROD users get one
soak window instead of four staggered HACS updates.

@RienduPre's #316 observation ("Sankey shows charger 2 sourcing
from grid even in solar_only") was the user-visible gap behind the
flow-sensor work. v1.6.9 fixed the underlying data (proportional
W-level split was honest); v1.6.15 ships the entity surface so the
dashboard + Energy dashboard actually render the per-charger split.

### Polish (HA-TEST soak findings folded into v1.6.14)

- **PR #333** — initialise ``SEMCoordinator._current_charger_budget``.
  Missed in the v1.6.7 PerChargerContext refactor; ``__enter__``
  snapshotted the attribute but ``__init__`` never set it, so every
  multi-charger setup blew up its first cycle with
  ``AttributeError``. Single-charger setups (HA-PROD) never tripped
  it; HA-TEST today was the first multi-charger clean install since
  v1.6.7. New regression test ``test_coordinator_swap_attrs_initialized.py``
  AST-walks ``SEMCoordinator.__init__`` to assert every attribute
  ``PerChargerContext.__enter__`` snapshots is initialised.

- **PR #334** — per-charger notification ``NoneType`` coerce + flow
  sensor zero-fill. ``intel.get(k, default)`` returns the default
  only when the KEY is missing — mock chargers without upstream
  data have the key set to ``None``, so ``est_soc > 0`` raised
  ``TypeError`` every cycle (DEBUG noise). Fix: ``intel.get(k) or 0``.
  Plus: ``flow_calculator`` now zero-fills per-charger flows when
  the fleet is idle so the v1.6.15 flow sensors stay AVAILABLE at
  0 W instead of going ``unavailable`` whenever no charger draws.

- **PR #335** — upgrade-notification helper. After a HACS update +
  HA restart, the browser's loaded frontend bootstrap still
  references the OLD ``sem-localize.js`` URL until hard-refreshed
  — soft reload serves the cached bootstrap → loads stale
  translations → raw keys like ``today_plan_title`` /
  ``plan_strip_idle`` appear in cards. HA-TEST 2026-05-31 confirmed.
  New ``_maybe_emit_upgrade_notification`` helper detects a SEM
  version change at setup (via a per-entry
  ``hass.helpers.storage.Store``) and fires a one-shot
  ``persistent_notification`` instructing users to hard-refresh
  (Ctrl+Shift+R / Cmd+Shift+R). First install is silent. Failure
  is non-fatal. 5 new tests pin the contract (first-install,
  same-version, upgrade, per-version notification-id, per-entry
  storage key).

2263 tests pass on Python 3.12 (2210 v1.6.12 baseline + 13 #8 +
14 v1.6.14 + 20 v1.6.15 + 12 v1.6.16 + 2 v1.6.14-hotfix +
5 v1.6.14-polish = 66 new tests in this release). Manifest at 1.6.14.

## [1.6.12] — 2026-05-31

Closes the last open senior-reviewer item on the v1.6.7 → v1.6.11
multi-charger cleanup arc — the missing end-to-end scenario covering
``charger A = off + charger B = solar_only`` mixed-mode. No
behaviour change for any user.

### Added

- **New scenario test** ``tests/scenarios/2026-05-31_off_plus_solar_only.yaml``
  exercises the senior-reviewer-flagged hole in coverage:
  - **Per-charger effective state isolation** (v1.6.4
    ``_apply_per_charger_off_override``). Charger ``off`` mode →
    ``SOLAR_IDLE`` (terminate); sibling ``solar_only`` →
    ``SOLAR_CHARGING_ACTIVE`` (untouched). Pins the #315 mitigation
    at the unit-pipeline level — would have mechanically caught the
    v1.6.3 regression at PR-review time.
  - **Per-charger flow attribution** (v1.6.9
    ``PowerFlows.per_charger``). With per-charger draw set to
    ``{left: 4000, right: 0}``, the per-charger split must give
    ``right`` zero EV-side flow — the user-visible attribution
    @RienduPre asked for in #316.
  - **Distribution sum invariant** (Phase B.5 / #284) re-asserted on
    top of the mixed-mode case.

- **Scenario harness extensions** in ``tests/scenario_harness.py``:
  - ``TIMELINE_FIELDS`` accepts ``ev_power_per_charger: {cid: watts}``
    so multi-charger flow attribution can be driven from YAML.
  - Cycle results now include ``per_charger_effective_states`` and
    ``per_charger_flows`` when the scenario has 2+ chargers.
  - Two new ``expect.multi_charger`` assertion blocks:
    ``per_charger_effective_states`` (exact match or
    ``{cid}_contains: substring``) and ``per_charger_flow_max`` for
    per-charger upper-bound caps.

### Docs

- ``docs/MULTI_CHARGER.md`` roadmap updated: the off + solar_only
  scenario gap is now closed (was a senior-reviewer FIX-BEFORE-MERGE
  on the v1.6.7-v1.6.10 arc).
- CHANGELOG entry per the
  ``feedback_docs_per_release`` rule — docs are part of every
  release, not a follow-up.

## [1.6.11] — 2026-05-31

Diagnostics improvement + doc polish closing the senior-engineer
review NITs on the v1.6.7 → v1.6.10 multi-charger cleanup arc. No
behaviour change.

### Added

- **Recent SEM log lines in the Copy diagnostics dump** —
  ``diagnostics.py::_get_recent_sem_logs`` reads the last 2 MB of
  ``home-assistant.log``, filters for
  ``solar_energy_management`` mentions, and includes up to 80 matching
  lines as ``recent_logs`` in the diagnostics output. Bug reports now
  come pre-loaded with the surrounding log context so we don't have
  to ask reporters for a separate ``ha core logs`` dump. Supervisor
  installs (no flat log file, journald-based) get a one-line
  placeholder explaining how to attach logs manually.

### Docs

- ``CLAUDE.md`` — new "Multi-charger correctness" pointer to
  [``docs/MULTI_CHARGER.md``](docs/MULTI_CHARGER.md) so future AI
  sessions can find the invariant doc without needing to grep.
- ``docs/MULTI_CHARGER.md`` — updated the roadmap to reflect what
  **actually shipped** vs what was planned. Specifically: the original
  v1.6.7 design proposed migrating ``effective_state``,
  ``this_power_w``, ``night_plan`` onto ``PerChargerContext`` in
  v1.6.8/v1.6.9 — none of those landed. The current dataclass has
  ``cid`` / ``ev_dev`` / ``charger_cfg`` / ``budget_w`` /
  ``skipped_for_night`` only. Per-charger flow **sensors** (data is on
  ``PowerFlows.per_charger`` but no top-level HA entities yet) were
  also descoped. Both are deferred to v1.7+ in the roadmap so the doc
  no longer oversells the abstraction.

## [1.6.10] — 2026-05-31

Code-quality cleanup release. Closes the three follow-up issues filed
during the v1.6.4 → v1.6.6 review cycle (#308, #309, #310). **Zero
behaviour change** for any user.

### Refactored

- **#308 — dead ``now`` / ``min_pv`` consumer branches dropped from
  ``coordinator/charging_control.py``.** Post-#305 the strategy
  producer ``_determine_charging_strategy`` only emits ``solar_only`` /
  ``battery_assist`` / ``night_grid`` / ``idle`` / ``disabled`` —
  neither ``"now"`` nor ``"min_pv"`` was reachable in production. The
  unreachable branches are gone; ``ChargingState.SOLAR_MIN_PV`` is
  still alive via the ``night_grid`` → ``EVBudgetStrategy.MIN_PV``
  producer mapping. The two synthetic-context tests
  (``test_min_pv_mode``, ``test_now_mode``) that exercised the dead
  branches are removed.

- **#309 — global-select cleanup block in ``select.py`` folded into
  the registry-key sweep added by #304.** The 12-line explicit
  ``async_remove`` block for ``{entry_id}_ev_target_type``,
  ``{entry_id}_ev_target_mode``, ``{entry_id}_ev_charging_mode`` was
  redundant with the sweep at the bottom of ``async_setup_entry``:
  each of those unique IDs has the ``{entry_id}_`` prefix and a key
  that's not in ``valid_keys``, so the sweep removes them just as
  cleanly. Per-charger values were seeded from the globals by the
  v3→v4 migration; no data is lost.

- **#310 — gravestone comments in ``tests/test_soc_zone_strategy.py``
  consolidated** into a single ``Removed tests`` block at the top of
  the module. Three multi-line tombstones (one each from #277 Phase C,
  Phase D.2 / #282, and #305) collapsed to a three-bullet list with
  ``git log -S`` as the pointer for full history.

## [1.6.9] — 2026-05-31

Third and final of the multi-charger cleanup arc (v1.6.7 → v1.6.9).
Adds per-charger flow attribution and per-charger notification flap
suppression so multi-charger users finally get correct downstream
visibility — closes the @RienduPre #316 family of complaints. **Zero
behaviour change** for single-charger users.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md).

### Added

- **Per-charger flow attribution** in
  [`coordinator/flow_calculator.py`](coordinator/flow_calculator.py).
  When ``PowerReadings.ev_power_per_charger`` is populated (multi-charger
  installs), ``calculate_power_flows`` now also produces
  ``PowerFlows.per_charger[cid] = ChargerFlows(solar_to_ev, grid_to_ev,
  battery_to_ev)``. Sum invariant: ``sum(per_charger[c].solar_to_ev) ==
  solar_to_ev`` (within < 0.1 W from float rounding). Closes the
  long-standing @RienduPre #284 / #316 complaint family — the dashboard
  can now show which charger drank from grid vs solar instead of the
  fleet-aggregated proportional split.

- **``PowerReadings.ev_power_per_charger``** populated by
  ``sensor_reader`` for multi-charger installs (each charger's
  ``ev_charging_power_sensor`` value, keyed by charger id).
  Single-charger installs leave the dict empty.

- **Per-charger notification flap suppression** in
  [`coordinator/notifications.py`](coordinator/notifications.py).
  ``notify_state_change`` accepts new ``charger_id`` + ``charger_name``
  kwargs; the flap-suppression ``_last_notified_state`` /
  ``_pending_state`` / ``_pending_state_since`` storage is now
  per-charger, keyed by ``charger_id`` (or the ``"_fleet"`` sentinel
  for back-compat). A state change on charger A no longer suppresses
  one on charger B. Mobile messages get a ``[Charger Name]`` prefix
  when ``charger_name`` is provided. The HA event payload now carries
  ``charger_id`` and ``charger_name`` keys so automations can route
  per charger.

### Back-compat

- v1.6.8 callers that read ``_last_notified_state``,
  ``_pending_state``, or ``_pending_state_since`` as scalars continue
  to work via property shims that target the ``"_fleet"`` sentinel
  slot.
- Single-charger setups behave identically to v1.6.8 — the
  per-charger split skips when no per-charger data is provided.

## [1.6.8] — 2026-05-31

Second of the three-release multi-charger cleanup arc (v1.6.7 → v1.6.9).
**Zero behaviour change** for single-charger users; multi-charger users
get correctness fixes for 12 fleet-power-sum reads that were silently
returning the wrong value inside per-charger code paths. Sets up the
structural enforcement that makes the bug class impossible to
re-introduce.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Fixed

- **12 fleet-power-sum reads swept in
  [`coordinator/ev_control.py`](coordinator/ev_control.py)** — every
  ``power.ev_power`` read inside the per-charger code path (8 in
  ``_execute_ev_control``, 3 in ``_should_reenable_charger``, 1 in
  ``_update_session_tracking``) now uses
  ``self._this_charger_power(ev, power)`` cached as
  ``this_power_w`` at the top of the method. In multi-charger setups
  these reads were returning the fleet sum — exactly the bug class
  that caused #284, #289, #315 (terminator) and #318 (SOC isolation).
  Each fix was reactive; this sweep closes them all.

### Added

- **AST lint test** ([`tests/test_ev_control_fleet_reads.py`](tests/test_ev_control_fleet_reads.py))
  — walks the AST of ``ev_control.py`` on every CI run and fails if
  any ``power.ev_power`` read is missing a ``# FLEET-READ:`` annotation
  (outside the sanctioned ``_this_charger_power`` helper). Catches the
  bug class on PR review, not after release.

- **``# FLEET-READ: <reason>`` annotation convention** — documented in
  ``docs/MULTI_CHARGER.md``. Same-line or previous-line comment opts
  a deliberate fleet-level read out of the lint with a required
  human-readable reason.

## [1.6.7] — 2026-05-31

First of a three-release multi-charger cleanup arc dedicated to v1.6.x.
**Zero user-visible behaviour change** for single-charger users; multi-charger
users see the same outputs but with the underlying swap mechanism now
typed and unit-tested.

The cleanup arc addresses a recurring bug class found in v1.6.0–v1.6.6
(#284, #289, #315, #318): per-charger context swaps with fleet-level
reads leaking through. This release lifts the swap mechanism; v1.6.8
sweeps the fleet-power reads in `ev_control.py` and adds per-charger
strategy; v1.6.9 adds per-charger flow attribution + notifications
(closes the #316 family).

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Refactored

- **`PerChargerContext`** — new
  [`coordinator/per_charger_context.py`](coordinator/per_charger_context.py)
  module that owns the per-charger swap lifecycle. The ad-hoc
  ``saved = {...}`` dict at `coordinator.py:1136-1258` that swapped
  eight coordinator attributes per iteration (and was easy to miss
  when adding new per-charger fields) is now a typed context manager
  with unit tests pinning every swap invariant. Adding a new
  per-charger field is now one place to edit instead of three.

### Docs

- **New `docs/MULTI_CHARGER.md`** — developer-facing invariant doc
  covering the bug class, the `PerChargerContext` contract, how to
  add new per-charger fields, and the v1.6.7-v1.6.9 roadmap.
- **`CONTRIBUTING.md`** — new "Multi-charger correctness" section
  pointing future contributors at the invariant.

## [1.6.6] — 2026-05-31

Same-day hotfix for v1.6.5 — the per-charger power read at
``_this_charger_power`` did a unit-naive ``float(state.state)`` and
compared a kW value to a 500 W threshold. KEBA's native
``sensor.keba_p30_charging_power`` reports in kW; the comparison
``4.14 < 500`` was always False so the v1.6.5 off-mode stop never
fired on KEBA, even when the firmware self-resumed. Confirmed live
on PROD 2026-05-31 15:26 — KEBA self-resumed and ran uncontrolled
for ~2 min until a manual ``keba.disable`` stopped it.

### Fixed

- **Unit-aware per-charger power reading** — ``_this_charger_power``
  now reads the sensor's ``unit_of_measurement`` attribute and
  converts kW → W before the 500 W threshold check. Tests pin both
  KEBA-style (kW) and Wallbox-style (W) sensors so the next charger
  integration doesn't introduce the same trap.

- **Per-charger SOC isolation in multi-charger setups** (#318) —
  ``_update_ev_intelligence`` was only calling ``update_energy()`` on
  the PRIMARY taper detector at line ~3326; every per-charger detector
  in ``_ev_taper_detectors`` stayed at ``_energy_since_full=0``,
  giving every charger the same default SOC. Confirmed by @RienduPre
  on a multi-charger Wallbox Pulsar + Growatt setup. Fix: also call
  ``update_energy(per_increment, per_hw_total)`` inside the
  per-charger loop, using each charger's own ``ev_total_energy_sensor``
  hardware counter for drift-free tracking when configured.

## [1.6.5] — 2026-05-31

Same-day follow-up to v1.6.4. Closes the second half of the off-mode
problem: KEBA P30 self-resumes from a stored setpoint on plug-in events
or after internal firmware events, completely independent of SEM. The
v1.6.4 fix only stopped SEM-owned sessions; if SEM never started the
session (because mode was already off when the EV plugged in, or KEBA
restarted on its own), the contactor stayed closed and KEBA drew power
SEM never knew about.

### Fixed

- **off-mode now stops charger-initiated charging** (#315) — the
  actuator's terminal-state branch in ``ev_control.py`` now also calls
  ``stop_session()`` when ``charging_strategy == "disabled"`` and
  ``ev_power > 500W``, regardless of ``ev._session_active``. Every
  coordinator cycle (10 s) re-asserts the per-brand disable (e.g.
  ``keba.disable``) until ev_power drops below the 500 W threshold.
  Idempotent — safe to call on an already-disabled charger.

  Threshold rationale: KEBA's handshake idle draws 100–200 W
  continuously while plugged in (control-pilot duty cycle). Real
  charging starts at 4140 W minimum (3 phases × 6 A × 230 V). The
  500 W cutoff cleanly separates "actually pulling current" from
  "plugged in, parked" so SEM doesn't spam stop_session every cycle
  while the car is idle at the charger.

## [1.6.4] — 2026-05-31

Hotfix on top of v1.6.3 plus the cleanup follow-ups #304/#305 that
shipped to develop the same day.

### Fixed

- **`charge_mode=off` did not stop EV charging** — surfaced during the
  v1.6.3 PROD soak. Setting the per-charger Charge mode to ``Off`` while
  the EV was actively charging left the KEBA contactor closed; SEM
  reported "Charging allowed" with budget 0 but the charger kept drawing
  power, requiring a manual ``keba.disable`` call to stop. The state
  machine fell through to ``SOLAR_CHARGING_ALLOWED`` instead of a
  terminal stop, so ``stop_session()`` was never invoked.

  Fix: introduce a distinct ``"disabled"`` strategy string for explicit-off
  (separate from transient ``"idle"``). The state machine routes it to
  ``SOLAR_IDLE``, which the actuator treats as terminal → calls
  ``stop_session()`` → ``keba.disable``. The canonical EV budget enum
  collapses ``"disabled"`` back to ``IDLE`` (same 0 W shape, distinct
  upstream).

  Multi-charger correctness: a static helper
  ``_apply_per_charger_off_override`` runs in the dispatch loop so a
  primary charger's ``off`` cannot bleed its terminate into siblings
  with active ``solar_only``/``min_plus_solar`` modes.

### Cleanup (from develop merge)

- **#304** — ``select.py`` orphan removal now uses a registry-key sweep
  matching ``switch.py``. Catches stale entries from previously-removed
  chargers (rather than only those currently in the config).
- **#305** — drop dead ``_auto_mode_strategy`` and the unreachable
  ``min_pv`` branch in ``_canonical_strategy_from_legacy``. Both were
  Phase C leftovers documented as deferred.

## [1.6.3] — 2026-05-30

The **EV charge UX consolidation** release (#277). Replaces the
four-toggle soup (``ev_charging_mode`` × ``night_charging`` ×
``smart_night_charging`` × ``tariff_optimized``) with one named
per-charger ``Charge mode`` selector. Three-phase arc shipped across
five PRs (A + B + B.2 + C + #298 today-plan ETAs).

### New

- **Per-charger ``Charge mode`` selector** with five modes:
  ``Solar only`` / ``Solar + cheapest hours`` / ``Min + Solar``
  (default) / ``Always (max)`` / ``Off``. ``Solar + cheapest hours``
  is dynamically hidden when no dynamic tariff is configured.
- **Per-mode help line** in the EV card explains what each mode
  actually does — cuts the toggle-soup mystery the #247 review
  flagged.
- **Today's plan timeline** gains three ETA rows (#298): "Battery
  full at HH:MM" while charging, "Battery reaches floor at HH:MM"
  while discharging, "EV reaches target at HH:MM" while a charging
  session is in progress.

### ⚠️ Behavioural change — explicit-``minpv`` legacy users

A small population of users explicitly set the legacy
``ev_charging_mode`` to ``minpv`` (the "force Min from grid + solar
to Max" mode). The Phase A migration mapped them to
``min_plus_solar``, which in v1.6.x kept their daytime behaviour
unchanged (the strategy machine still read the legacy field). v1.6.3
Phase C makes ``min_plus_solar`` **zone-adaptive during the day** —
the Min guarantee now comes from NIGHT charging top-up only, not
from forced grid pull at noon. The Min target itself is unchanged;
the daytime path now matches what most installs (``pv + night=on``)
were always doing.

If you want strict "Min from grid at all times" behaviour, pick
``always_max`` from the new selector — it charges at maximum
regardless of source. Otherwise the new ``min_plus_solar`` default
adapts to your battery SOC zone (battery priority when low, surplus
when high, battery-assist in Zone 4) — generally more efficient
than forced grid pull.

### Migrations (automatic on first load post-upgrade)

- **v4 → v5** (Phase A): Each charger gets a ``charge_mode`` derived
  from its existing toggle state. The legacy fields stay in place.
- **v5 → v6** (Phase B fix-up): Re-derives ``charge_mode`` for
  installs whose Phase A derivation silently lost the
  ``tariff_optimized`` signal (``pv/auto/self_consumption + tariff_on``
  → ``solar_plus_cheap``).
- **v6 → v7** (Phase C): Drops the now-dead ``ev_charging_mode`` per-
  charger config key. The legacy ``select.sem_charger_<id>_ev_charging_mode``
  entity is removed from the registry automatically.

### Removed

- **Per-charger switches** ``switch.sem_charger_<id>_night_charging``,
  ``...smart_night_charging``, ``...tariff_optimized`` — the named
  ``charge_mode`` selector carries all three intents now. Existing
  automations that read these switches will need to read the
  ``charge_mode`` select state instead.
- **Per-charger select** ``select.sem_charger_<id>_ev_charging_mode``
  — superseded by the new ``charge_mode`` selector.
- **Global switches** ``switch.sem_night_charging`` and
  ``switch.sem_smart_night_charging`` — same; ``observer_mode`` is
  the only remaining global switch.
- **Config-flow toggle** ``smart_night_charging`` — the named modes
  carry the intent.
- **Strategy machine legacy reads**: ``ev_charging_mode`` is no
  longer consulted anywhere; ``_tariff_optimized_for`` derives from
  the named mode.

### Fixed

- **Stale Lovelace cache-bust on sem-localize.js (#301)** — the legacy
  ``generate_dashboard`` service path used ``int(time.time())`` as the
  ``?v=`` for card resources, so a plain rsync deploy that rewrote
  ``sem-localize.js`` left the registered URL unchanged and browsers
  served the cached pre-Phase-B.2 file. Symptom on first install of
  this release: the new charge-mode selector renders raw translation
  keys (``charge_mode``, ``charge_mode_min_plus_so…``,
  ``charge_mode_hint_min_plus_solar``) instead of localized labels.
  Fix: per-file ``{version}-{sha1(content)[:8]}`` cache-bust, matching
  the format ``_async_register_frontend_resources`` already uses for
  the Lit bundle. Both paths now produce identical URLs for the same
  file content; any deploy that changes content auto-flips the URL on
  the next ``generate_dashboard`` call and the browser cache-misses
  through to the fresh copy.

### Internal

- New ``consts/ev_charge_modes.py`` — shared constants
  (``EV_CHARGE_MODES``, ``MODE_NIGHT_ALLOWED``, ``MODE_USES_TARIFF``,
  ``MODE_USES_SMART_NIGHT``, ``MODE_TO_LEGACY_CHARGING_MODE``,
  ``DEFAULT_EV_CHARGE_MODE``) and the ``effective_charge_mode_for``
  resolver. Single source of truth for the mode taxonomy across
  ``SEMCoordinator``, ``ChargingStateMachine``, ``EVControlMixin``,
  the dashboard cards.
- ``async_migrate_entry`` accumulator refactor — each step reads
  from / writes back to threaded ``accumulated_{data,options}``
  accumulators. Fixes a pre-existing bug exposed by chaining 4
  migration steps (each was re-reading the original entry options on
  test harnesses).
- New module-level ``_content_hash_cache_bust`` helper — extracted
  from the legacy ``generate_dashboard`` registration path so the
  cache-bust behaviour is directly unit-testable. Replaces a closure
  buried inside ``async_generate_dashboard_service``.
- 15-language translations updated; legacy entries cleaned from
  ``strings.json`` + 15 per-language files.
- Suite: 2136 / 2136 tests passing (6 new regression tests guard
  the #301 cache-bust contract).

### Issues addressed

- Closes #277 (EV charge UX consolidation arc)
- Closes #298 (Today's plan battery / EV ETA rows)
- Closes #301 (Stale Lovelace cache-bust on sem-localize.js)

---

## [1.6.2] — 2026-05-30

The **Phase D.2 cleanup + EV-power realtime** patch.

Two changes ship together:

1. **Phase D.2 architectural cleanup (#282)** — completes the EV-budget
   unification arc by removing the legacy fallbacks that the v1.6.0
   canonical path left side-by-side as a safety net. Carrying two budget
   formulas alive was exactly the duplication that produced the
   disagreement bug class in the first place; with three weeks of clean
   v1.6.0/v1.6.1 PROD soak the fallbacks are dead code, and keeping them
   invited the next regression.

2. **#289** — `sensor.sem_ev_power` now updates within one HA dispatch
   of the upstream KEBA / Wallbox sensor instead of waiting up to 10 s
   for the next coordinator cycle. The dashboard reads at 1 s
   resolution and observably benefits; the energy-balance derivations
   (`home_consumption_power`, sankey flows) stay on cycle granularity
   and self-heal on the next tick.

No behavioural changes outside the named removals + the sub-cycle
passthrough. Same upgrade path as any 1.6.x.

### Removed

- **`flow_calculator.calculate_ev_budget`** — superseded by
  `calculate_canonical_ev_budget` since v1.6.0 (Phase A). Zero
  production callers as of v1.6.1.
- **`flow_calculator.calculate_available_power`** — superseded by the
  canonical EVBudget's per-strategy resolution. Zero production
  callers as of v1.6.1.
- **`flow_calculator.calculate_charging_current`** — both production
  call sites (night charge sizing + actuator ramp) now go through
  `EVControlMixin._watts_to_amps` which carries the per-charger
  watts-per-amp + round-down policy directly.
- **`EVControlMixin._calculate_solar_ev_budget`** — 74-line legacy
  fallback that the actuator used when `_cycle_ev_budget` wasn't
  populated. Removed; the path now logs an error and emits 0 W
  (fail-safe = no charge) if the invariant is ever violated. This
  catches coordinator init bugs loudly instead of silently masking
  them with a divergent budget formula.
- **Multi-charger distribution legacy fallback** in
  `coordinator.py` — same fail-safe pattern applied: missing
  `_cycle_ev_budget` → log error + distribute 0 W.
- **`sensor._format_charging_state` demotion guard** — the cosmetic
  SOLAR_CHARGING_ACTIVE → SOLAR_CHARGING_ALLOWED downgrade (commit
  `1a9b3c9`) that papered over the pre-D.2 budget disagreement. The
  canonical unification eliminated the disagreement by construction,
  so the guard is now dead code — verified across daytime
  battery_assist and nighttime MIN_PV soak in v1.6.0/v1.6.1.

### Added

- **#289 — sub-cycle `sem_ev_power` passthrough** — the `ev_power`
  sensor now subscribes to its upstream EV-power entities via
  `async_track_state_change_event` (single-charger: top-level
  `ev_power_sensor`; multi-charger: every charger's
  `ev_charging_power_sensor`). On any upstream change SEM re-sums and
  pushes the new value immediately. Eliminates the 1-cycle gap that
  showed up live on PROD 2026-05-29 as a 4.7 kW dashboard
  discrepancy. 11 unit tests + the resolution / callback / cleanup
  invariants.

### Internal

- **Test sweep** — removed the unit tests that pinned the deleted
  primitives directly (`TestAvailablePower`, `TestEvBudget`,
  `TestAvailablePowerIncludesBatteryDischarge`, `TestEVBudgetSemantics`,
  `TestAvailablePowerInvariants`, `TestCalculateSolarEvBudget`, the
  budget/current rows from `TestEVControlInvariants`). Their physical
  invariants (non-negative budget, 16 A clamp, battery-discharge
  inclusion, Zone-3 proportional ramp, measured-discharge override)
  are now exercised against `calculate_canonical_ev_budget` and the
  scenario harness (`tests/scenarios/2026-05-29_*`).
- **Scenario harness rewired** — `tests/scenario_harness.py` was
  calling the deleted `calculate_ev_budget` / `calculate_charging_current`
  inside a bare `except Exception: pass`. Caught in review before
  deploy: every scenario was vacuously passing (`calculated_current`
  fell silently to 0). Rewrote to compute the canonical EVBudget
  directly and read `EVBudget.net_w` + `EVBudget.current_a`, so
  scenario regressions now fail loudly. 4 / 4 scenarios still pass
  with real values.
- **`test_multi_charger_canonical_budget.py` rewrite** — the test
  mirrored the pre-D.2 production branch with the legacy fallback;
  post-D.2 the branch logs an error and distributes 0 W instead.
  New `test_missing_cycle_budget_fails_safe_to_zero` pins the fail-
  safe; `test_legacy_method_attribute_does_not_exist_post_d2`
  prevents accidental re-introduction.
- **16 A clamp coverage gap closed** —
  `TestEVControlInvariants.test_canonical_budget_current_a_clamped_to_16`
  sweeps extreme solar / battery inputs across every non-IDLE
  strategy (including `BATTERY_ASSIST` which can blow past the
  surplus ceiling by design) and verifies `EVBudget.current_a`
  stays in [0, 16].
- **Docstring rot** — `ChargingContext.available_power` docstring
  was still referencing `FlowCalculator.calculate_ev_budget()`;
  updated to point at `calculate_canonical_ev_budget().net_w`.

**Suite is 2054 / 2054 green** (was 2042 in v1.6.1 — 12 new tests).

---

## [1.6.1] — 2026-05-30

Patch release with fixes driven by the v1.6.0 PROD soak. No behavioural
changes outside the named fixes — same upgrade path as any 1.6.x.

### Fixed

- **#288** — Night peak management formula switched from the
  sensor-lag-sensitive derived `home_consumption_power` to
  `sensor.sem_consecutive_peak_15min` (the same 15-min rolling
  grid-import average most demand-charge tariffs bill on).
  Self-balancing: as EV ramps the rolling rises and headroom shrinks
  naturally; settles at the equilibrium where rolling ≈ peak limit.
  Falls back to the legacy formula during the cold-start window when
  the load manager hasn't accumulated samples yet, so peak protection
  is never absent. Caught live on PROD 2026-05-29 with a 7.9 kW grid
  spike during EV ramp because `sem_ev_power` lagged by ~5 kW for
  several seconds, deflating the derived home value toward 0 and
  giving the EV the full peak limit as headroom. 6 unit tests +
  forever live sentinel.
- **#290** — Night state machine no longer blips through
  `NIGHT_DISABLED` for one cycle during config slider writes.
  Observed live on PROD 2026-05-29: a per-charger Number slider
  write triggered a race in `hass.states.is_state` for the per-charger
  night switch, returning False for one ~10 s cycle before
  recovering. SEM now requires 2 consecutive cycles of disagreement
  before flipping the cached state — trades 10 s of responsiveness
  for race immunity. 7 unit tests covering first-call commit, blip
  suppression, sustained change, and pending-counter reset.

### Internal

- **Test infra** — fixed the pre-existing flaky
  `test_lookahead_uncapped_when_no_deadline_resolvable` that had been
  intermittently red since the defensive `night_end` fallback at
  `ev_control.py:119-122` was added. The test now patches
  `DEFAULT_EV_TARGET_TIME` to None so the original "no deadline
  resolvable" path it was written to guard is actually exercised.
  Suite is now 2091 / 2091 fully green — first time this release.
- **Live test layer** — new sentinel `tests/live/test_night_peak_rolling.sh`
  pins the #288 fix as a regression guard.
- **Documentation** — design plan for #277 (EV Charge mode
  consolidation) committed at `docs/plans/2026-05-30_ev_charge_mode_consolidation.md`.
  No code yet; awaiting maintainer decisions on the four design
  questions listed there before any implementation. Tracked for v1.7.0.

---

## [1.6.0] — 2026-05-30

The **EV-budget unification** release. SEM historically had three separate
"how many watts can the EV draw right now" calculations — one for the
published dashboard sensors, one for the state machine's decision, and one
for the actuator. Under certain conditions they disagreed: the dashboard
could read *"Charging active"* while the car drew 0 W, or surplus-only
mode could let grid backfill the EV's draw without telling the user.

v1.6.0 collapses all three into one canonical `EVBudget` value computed
once per cycle. Every consumer now reads from the same dataclass — the
dashboard, the state machine, the actuator, and the multi-charger
distribution all see the same number, by construction.

### ⚠️ Behavioural change — published sensors

`sensor.sem_available_power` and `sensor.sem_calculated_current` now
publish the **canonical** EV budget instead of the raw solar surplus.
The canonical value is strategy-aware (includes battery-redirect on
`solar_only`, includes the battery-assist contribution on
`battery_assist`, applies the floor on `min_pv`) — it's the more
accurate number and matches what the state machine actually decides
with.

If you have automations or template sensors that read either of these
two values directly, you may see different numbers than under
1.5.x. The canonical value is the honest one; the pre-1.6.0 value
could be misleadingly low when battery redirect was active.

### Added

- **Canonical `EVBudget` dataclass and `EVBudgetStrategy` enum** in
  `coordinator/flow_calculator.py`. Six strategies are first-class:
  `IDLE`, `SELF_CONSUMPTION`, `SOLAR_ONLY`, `BATTERY_ASSIST`, `MIN_PV`,
  `NOW`. Each has a single well-defined formula; the dispatcher raises
  `ValueError` on unknown strategies (no silent fallthrough, which was
  the #282 disagreement root). See [ARCHITECTURE.md → EV Budget
  Calculation](docs/ARCHITECTURE.md#ev-budget-calculation).
- **Live test layer** under `tests/live/` — seven bash scripts that
  exercise SEM against a real Home Assistant instance:
  `test_budget_agreement.sh`, `test_charging_state_consistency.sh`,
  `test_solar_only_no_grid.sh`, `test_overnight_window.sh`,
  `test_deadline_reset.sh`, `test_per_charger_slider.sh`,
  `test_bundle_integrity.sh`, `test_surplus_charging.sh`.
- **Scenario harness scenarios** locking the canonical math through
  the coordinator pipeline:
  `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`,
  `tests/scenarios/2026-05-29_budget_unify_battery_assist.yaml`,
  `tests/scenarios/2026-05-29_multi_charger_split.yaml`.
- 17 unit tests for the canonical method covering every strategy plus
  the regimes that historically disagreed.
- 4 unit tests for the multi-charger Phase B.5 distribution path.
- 4 unit tests for the YAML-mode Lovelace guard.
- `copy_failed` translation key across all 15 languages.

### Changed

- `coordinator.async_update_config` now mutates `self.config` in place
  rather than rebinding to a new dict. Multiple components
  (`TimeManager`, `EnergyCalculator`, `ChargingStateMachine`,
  `BatteryChargeAdapter`) hold references to the original dict; the
  pre-fix rebind left them stale, so the next slider change reached
  `coordinator.config` but never propagated. Caught by
  `tests/live/test_overnight_window.sh`.
- The multi-charger distribution at `coordinator.py:966` now reads the
  canonical `EVBudget.net_w` instead of calling the legacy
  `_calculate_solar_ev_budget`. Same #282 disagreement mode, just for
  fleets of 2+ chargers (Phase B.5).
- The `sem-system-card` "Copy diagnostics" button now uses a
  cross-context clipboard helper that falls back to
  `document.execCommand('copy')` on HTTP installs where the modern
  Clipboard API is blocked. Always shows user feedback — success or
  failure — so the button is never silent again.
- Deploy scripts (`~/bin/deploy-test.sh`, `~/bin/deploy-prod.sh`) now
  strip `__pycache__` before `ha core restart`. `ha core restart` does
  not clear the bytecode cache, so signature changes in committed
  code could still execute the cached `.pyc` and produce confusing
  `NameError`s. (Operational; not in the integration itself.)

### Fixed

- **#279** — Global `daily_ev_energy` counter resets at the configured
  `Charge by` time, not at sunrise. The summer-sunrise race condition
  (sunrise earlier than the deadline → counter wiped while night
  charging still in progress → double-charge) is closed.
- **#283** — Dashboard no longer fails to register on YAML-mode
  Lovelace installs. The integration feature-detects the mutating
  resource-collection methods; when YAML mode is detected, it logs a
  single actionable warning with the exact `lovelace.resources:` YAML
  the user has to paste, instead of an unhelpful "Could not register"
  warning. Storage-mode users see no behavioural change.
- **#284** — Multi-charger setups (e.g. dual Wallbox Pulsar) no longer
  pull from grid while strategy reports `solar_only`. The distribution
  path now reads from the canonical `EVBudget`.
- **#285** — "Copy diagnostics" button in the System Information card
  now works on HTTP installs. Reported on macOS Chrome.
- **Charger plug-sensor physics defence** — caught live on PROD
  2026-05-29 with a KEBA P30. Across an HA restart with a connected
  car, `binary_sensor.keba_p30_plug` reported "off" for 67 minutes
  while `binary_sensor.keba_p30_charging_state` cycled on/off through
  15 transitions and `sensor.keba_p30_charging_power` peaked at 8 kW.
  SEM correctly trusted the lying plug sensor, returned "EV
  disconnected", and stopped supervising the car. The KEBA kept its
  last commanded current; the car drew ~6 kWh past the configured
  Max ceiling because SEM wasn't watching. The root cause is upstream
  (the charger integration's plug sensor), but SEM now defends
  against it: if `ev_charging` is True OR `ev_power > 100 W`,
  `ev_connected` is inferred True regardless of what the plug sensor
  says. Current cannot flow without a connection. Locked in by
  `tests/test_ev_connected_physics_defence.py` (5 truth-table corners)
  and `tests/live/test_ev_connected_physics.sh` (forever sentinel).
- Display-honesty guard at `sensor.py:_format_charging_state` is now
  redundant after the unification (canonical is the single source of
  truth) but kept as defence-in-depth for one release; will be removed
  in v1.7.0.

### Internal

- `coordinator/coordinator.py` — `_build_charging_context`'s
  `available_power` and `calculated_current` parameters dropped (dead
  since Phase B). Step 6's bare-variable computation removed (also dead
  since Phase B).
- New `_canonical_strategy_from_legacy` helper in `coordinator.py`
  maps the legacy strategy-string returns of `_determine_charging_strategy`
  to canonical `EVBudgetStrategy` constants.

### Community contributions

Thanks to **@RienduPre** for [PR #286](https://github.com/traktore-org/sem-community/pull/286)
— two native-speaker Dutch translation polishes (`notif_low_forecast`
grammar; `notif_daily_summary` replaces the loanword "autarkie" with the
idiomatic "zelfvoorzienend").

---

## [1.5.15] — 2026-05-27

Single hotfix release for a SolaX-pattern cold-start regression.

### Fixed

- **#274** — Inverter / battery / grid readings no longer stay at 0
  after an HA restart on SolaX-pattern installs (Pattern E: split
  grid). Forced a sensor-reader reinitialization on coordinator
  restart instead of relying on the lazy first-cycle path.

---

## [1.5.14] — 2026-05-27

Documentation, sensor-naming hardening, and the #255 per-charger
config cleanup.

### Added

- Per-charger night charging gate (`switch.sem_charger_<id>_night_charging`,
  default ON) — multi-charger fleets can now schedule night charging
  per car.

### Changed

- Removed the redundant global EV configuration entities — per-charger
  entities are the canonical source of truth after #255. The integration
  migrates existing setups transparently.
- Energy Dashboard config summary on the System tab now lists actual
  entity names instead of the compact "X sources, Y units" string (#250).

### Fixed

- **#245** — Surplus EV charging now stops at the Max ceiling
  (`daily_ev_target_max`) instead of running until the per-cycle
  remaining-need flips negative. The Min target gates night charging;
  Max gates day surplus. Both are honored independently.
- **#256** — Zero-config installs no longer adopt the global target as
  the per-charger night floor without the user's explicit consent.
- **#259** — Vehicle SOC reads that come back as `unknown` or
  `unavailable` no longer crash the strategy decision.

---

## [1.5.13] — 2026-05-25

Beta-only iterations; release notes consolidated into the next stable.

---

## [1.5.12] — 2026-05-25

### Fixed

- Dashboard regenerate ("Generate Dashboard" service) no longer
  triggers an HA core restart. Live-reload via the storage API
  replaces the legacy "write + restart" pattern.
- Removed a stray top-level `sem-cards.js` left over from a botched
  manual deploy that was shadowing the real `dist/sem-cards.js`
  bundle and breaking every dashboard card (#219 regression class).

---

## [1.5.11] — 2026-05-25

### Changed

- All ~23 dashboard cards now ship as a single Lit bundle at
  `dashboard/card/dist/sem-cards.js`. The legacy top-level vanilla
  `sem-*-card.js` files were removed.
- Lovelace resource URLs now include `?v={version}-{sha1[:8]}` for
  cache busting; plain `rsync + restart` deploys now bust the browser
  service-worker cache without a manifest bump (#240).

---

For the full pre-1.5.11 history, see the [git tag log](https://github.com/traktore-org/sem-community/tags).

[1.6.0]: https://github.com/traktore-org/sem-community/releases/tag/v1.6.0
[1.5.15]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.15
[1.5.14]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.14
[1.5.13]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.13
[1.5.12]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.12
[1.5.11]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.11
