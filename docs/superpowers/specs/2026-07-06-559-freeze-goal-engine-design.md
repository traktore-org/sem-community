# #559 — Freeze the surplus-load goal engine to its grounded core

**Date:** 2026-07-06
**Issue:** [#559](https://github.com/traktore-org/sem-community/issues/559) — "Load management" (alexmc1510)
**Branch:** `fix/559-freeze-to-core`
**Status:** design approved (backend + card mockup), pending spec review → implementation plan

## Problem

Issue #559 came from a self-described non-technical user asking for two concrete
things: (1) run a pool pump ≥4 h/day on solar surplus, and (2) charge a PHEV via
a plain on/off 230 V socket on solar excess (stop at Kia SOC). In response we
shipped (beta.11→beta.18, now on PROD) a full "goal engine": a 3-mode ladder plus
per-device energy-kWh targets, daily-max caps, `cheap_hours`/`always` top-up
policies, a deadline ramp, and a per-device UI with a dual-handle unit-picker
slider — ~1,900 lines / 13 files.

A three-lens review (product, UX, engineering) converged: the **model is right and
the grounded core is exactly right**, but ~1,400 lines of unrequested surface was
built on top, and that surface carries the only two serious correctness bugs and
all the UX debt:

- **HIGH-1:** `daily_max_runtime_sec` accumulator is not persisted → the safety cap
  resets to 0 on every HA restart (a 2 h cap becomes 2 h × restart-count/day).
- **HIGH-2:** `cheap_hours`/`always` deadline-force has no battery-SOC gate
  (`battery_too_low` is wired only into the EV path) → it drains the house battery
  at night to hit a deadline.

The grounded core (`solar_only`) was verified to **never pull grid**.

## Decision

**Delete the speculative surface** rather than hide it. Deleting the code paths
removes both HIGH bugs with the dead code — nothing left to fix on paths nobody
uses. If a real user later needs deadlines/energy targets, we rebuild from a spec.

## Scope

### Survives (grounded, tested, safe)
- Mode ladder `off < peak_only < surplus`
- `daily_min_runtime_sec` — the "run at least N hours today" target
- `solar_only` behavior (never imports)
- `stop_entity` / `stop_at` — external completion (alex named Kia SOC)
- `SurplusAvailability` binary_sensor + bus event
- Persisted service registrations, entity-id dedupe, `adopt_if_running` boot re-ownership

### Deleted (speculative; carries both HIGH bugs + UX debt)
| Item | Location | Note |
|---|---|---|
| `daily_target_energy_kwh` | `base.py:171` | no user asked; metered-target |
| `daily_max_energy_kwh` | `base.py:172` | energy cap |
| `daily_max_runtime_sec` | `base.py:170` | **HIGH-1 dies here** |
| `target_deadline` + `deadline_pressure()` | `base.py:174,377,398` + deadline-force pass in `surplus_controller.py` | **HIGH-2 dies here** |
| `top_up_policy` values `cheap_hours`/`always` | `base.py:175` + cheap/deadline force passes | collapses to `solar_only`-only → field drops off the surface |

With `cheap_hours`/`always`/deadline gone there is **no grid-forcing path left** —
matching the honest story already given to alex ("solar-only, accept a miss on
cloudy days").

## Footgun fix (affects even the core path)

Unknown `rated_power` defaults to 1000 W, and `min_power_threshold = rated_power`
(`base.py:591`), so a 2.3 kW socket left at default switches on at ~1 kW surplus
and pulls the rest from grid — the exact hazard.

**Fix — auto-calibrate:** when a surplus `SwitchDevice` has a `power_entity_id`
(auto-discovered devices do — they come from the Energy Dashboard's individual
devices), learn the real draw from the first observed ON reading and use it as the
threshold basis thereafter. Self-healing; fixes alex's auto-discovered socket with
zero config. Fallback (no power sensor): keep the configured value and log a clear
one-line warning that an unconfigured switch may import until `rated_power` is set.

## Card redesign (mockup approved)

Mockup: `/tmp/sem-559-mockup.html` (EV reference · before · after). Match the EV
charger card per `docs/UI_PATTERNS.md`.

- **Mode picker moved to the top of the goal panel**, `control_mode` decomposed in
  the card (backend API stays stable). Goal editor renders **only when mode =
  surplus** (true mode-gated disclosure).
- **Single "at least" slider, labelled in hours** ("Run at least 4 h today",
  `0 = no target`, default max 12 h). Removed: the dual-handle "up to" ceiling and
  the `min`/`kWh` unit picker.
- **Stop when** row = entity picker + numeric value (`Kia SOC ≥ 80%`). Removed: the
  raw entity-id text field and the `sensor.car_soc` placeholder (an EV copy-paste
  leftover). Visible by default (per approval).
- **Progress bar** (green `#8DC892`) — "2.1 h / 4 h on solar today" when a target
  is set; hidden otherwise.
- **Per-mode help** under the `?` toggle (Off / Peak only / Surplus), reusing the
  EV `hint_label_*` pattern.
- All remaining strings via `semLocalize`, localized ×15 (fix the hardcoded
  `min`/`kwh` literals); rebuild `dist/sem-cards.js`.

Net: 2 primary controls (mode + hours) vs 7 today.

## Migration / persistence

Goal keys live in per-device registry storage, **not** the config-entry schema —
no `config_flow` VERSION bump. Requirement: the device-registry load path must
**ignore unknown stored keys** so devices persisted under beta.18 (which may carry
`daily_max_*`, `target_deadline`, etc.) load cleanly after the deletion. Add a
defensive regression test.

## Tests

- Delete tests covering removed paths (energy target, max caps, deadline force,
  cheap_hours/always) in `tests/test_559_goal_engine.py`.
- Keep: `solar_only`-never-grids, min-runtime, persistence, dedupe, adopt-if-running.
- Add: (a) `rated_power` auto-calibrate from observed ON draw; (b) stored goal with
  unknown/removed keys loads without error.
- Full suite via the `/tmp/ha-config` layout must stay green.

## Deploy

Branch `fix/559-freeze-to-core` → `ruflo-core:reviewer` → HA-TEST live-verify of
alex's exact auto-discovered flow (register/adopt socket, solar_only, stop-at-SOC,
threshold auto-calibrate) → PROD as **v1.7.4-beta.19** (this replaces the on-PROD
beta.18 goal engine). CHANGELOG + docs (`MULTI_DEVICE_GUIDE.md`, `UI_PATTERNS.md`)
updated with the release, per repo policy. Reporter reply on #559 after PROD is up.

## Out of scope (explicitly, YAGNI)

Deadlines, energy-kWh daily targets, daily-max caps, and `cheap_hours`/`always`
grid top-up. Re-introduce only on a real, named request — with its own spec and a
battery-SOC gate designed in from the start.
