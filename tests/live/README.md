# Live integration tests (HA-TEST)

The third layer of the SEM test pyramid. Bash + `curl` against a real
Home Assistant instance, exercising the full coordinator → sensor →
dashboard round-trip. They catch the bug class that unit tests and
the YAML scenario harness can't.

## When to use which layer

| Layer | Catches | Where it lives | Cost |
|---|---|---|---|
| **Unit tests** | Pure calculation bugs | `tests/test_*.py` | Fast (seconds) |
| **Scenario harness** | Decision-vs-enforcement drift, replay of real traces | `tests/scenarios/*.yaml` + `tests/scenario_harness.py` | Medium (sub-second per scenario) |
| **Live tests** ← *you are here* | Time-boundary effects, entity reactivity, persistence across restart, real coordinator update path | `tests/live/*.sh` | Slow (minutes per test) |

Each is necessary; none is sufficient. The #279 follow-up bug — global
`daily_ev_energy` counter wiping at sunrise instead of the configured
07:00 deadline — was invisible to the first two layers because it
needs real wall-clock time to cross a boundary against a real sensor
that the dashboard actually reads.

## When to run

- **Before tagging a release** — manual pre-release ritual against
  HA-TEST. Not in CI.
- **After any change touching:** time/date handling, persistence,
  entity registration, the coordinator's update loop, or any service
  call that affects state.
- **After a HA-TEST bug report you can't reproduce in unit tests** —
  capture the repro as a live test, fix until it passes.

Never run against HA-PROD. `lib.sh` refuses mutating helpers against
the PROD host (`10.10.20.150`) unless `TESTS_LIVE_ALLOW_PROD=1` is
set explicitly.

## Running

```bash
# All tests, sequentially
for t in tests/live/test_*.sh; do
    bash "$t" || { echo "FAILED: $t"; exit 1; }
done

# One specific test
bash tests/live/test_deadline_reset.sh
```

Requirements on your machine:
- `~/.config/sem/tokens.env` with `HA_TEST_TOKEN=...`
- ssh config aliases for `ha-test` (10.10.20.46) — used by helpers that
  read HA's local clock to compute relative times correctly.
- HA-TEST reachable on its admin port.

## Writing a new test

Copy `test_deadline_reset.sh` as a template. The shape is:

```bash
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_my_thing"

# 1. SNAPSHOT — record baseline state
baseline=$(get_state sensor.sem_X)

# 2. APPLY — mutate the input
set_state_time time.sem_Y "06:40:00"

# 3. POLL — watch state until expected change or timeout
poll_until_value sensor.sem_X "0.0" 180 15

# 4. ASSERT — fail loudly with detail
assert_equals "$(get_state sensor.sem_X)" "0.0" "sensor.sem_X after boundary"

# 5. CLEAN UP — restore the baseline
restore_state_time time.sem_Y "07:00:00"

live_end
```

Use `_log "message"` for progress output; it prefixes with the test
name so a multi-test run is grep-able.

## Available helpers (`lib.sh`)

| Helper | What it does |
|---|---|
| `live_init` | Load token, verify HA responding. Must be called first. |
| `live_begin "name"` / `live_end` | Pretty banner + PASS marker |
| `get_state ENTITY` | Echo state string |
| `get_attr ENTITY ATTR` | Echo named attribute |
| `set_state_time ENTITY HH:MM:SS` | Set a `time.*` entity. PROD-blocked. |
| `restore_state_time` | Alias for readability in cleanup blocks |
| `call_service DOMAIN SVC JSON` | Generic service call. PROD-blocked. |
| `ha_local_time [alias]` | HH:MM:SS of HA's local clock |
| `ha_local_time_plus N [alias]` | HH:MM N minutes from HA's local clock |
| `poll_until_value ENTITY VAL SECONDS [INTERVAL]` | Poll, return 0 on match, 1 on timeout |
| `assert_equals A B [LABEL]` | Equal-or-exit |
| `assert_numeric_gt A T [LABEL]` | A > T or exit |

## Convention: one bug → one test

When a bug bites in the wild, the live test is the regression. Capture
the exact sequence that reproduces it. If the bug ever quietly comes
back (the #282 system-card / select / EV-card class did exactly this
across releases), the test catches it before the next plug-in.

## Existing tests

| File | What it locks in |
|---|---|
| [`test_deadline_reset.sh`](test_deadline_reset.sh) | EV daily counter resets at `Charge by` time, not at sunrise (#279 follow-up; verified live 2026-05-29 06:40) |
| [`test_surplus_charging.sh`](test_surplus_charging.sh) | `ev_charging_mode` select exposes auto/minpv/now/off; switching mode propagates to coordinator and the strategy decision flips accordingly (#282 SEMPerChargerSelect class) |
| [`test_overnight_window.sh`](test_overnight_window.sh) | Moving the `night_latest_end` slider at runtime updates `sensor.sem_night_end_time` on the next cycle. **Caught a real bug live**: `async_update_config` rebound `self.config` to a new dict, leaving `TimeManager._config` pointing at the stale one. Fix: mutate in place. (2026-05-29) |
| [`test_charging_state_consistency.sh`](test_charging_state_consistency.sh) | When SEM is commanding `0 A` and EV power is below the 500 W idle floor, `sensor.sem_charging_state` must NOT read "Solar mode - Charging active". **Caught a real bug live** (user-reported on PROD): state machine and actuator use *different* budget calculations — the state machine sees `ev_budget` (includes battery redirect) and returned `SOLAR_CHARGING_ACTIVE`, but the actuator's own budget computation gave 0 A. The dashboard label lied. Fix: sensor-level demotion when actuator state contradicts "active". The deeper three-way budget disagreement (`bare available_power` vs `_build_charging_context.ev_budget` vs `_execute_ev_control.budget_w`) is filed for a later unification. (2026-05-29) |
| [`test_solar_only_no_grid.sh`](test_solar_only_no_grid.sh) | Passive invariant: when `charging_strategy == "solar_only"`, `sensor.sem_flow_grid_to_ev_power` must stay below 200 W. Locks in the surplus-leak fix from commit `591956f` (#282) — historically, `calculate_ev_budget(solar_only=True)` was inheriting the legacy base of `ev_power + grid_export`, so once the car had ramped, SEM never asked it to ramp DOWN when surplus dropped, silently letting grid backfill the gap. (2026-05-29) |
| [`test_per_charger_slider.sh`](test_per_charger_slider.sh) | Bumping a per-charger Number entity (`number.sem_charger_<id>_daily_ev_target`) must persist on the entity AND the integration must not log any errors during the next cycle. Locks in the per-charger config-update path (analog of `async_update_config` for `ev_chargers[i]`). The same stale-dict-reference bug class that hit globals in commit `bea4ecc` could land on per-charger state. (2026-05-29) |
| [`test_bundle_integrity.sh`](test_bundle_integrity.sh) | The dashboard card bundle at `dist/sem-cards.js` MUST exist (≥1 kB), MUST register custom elements, and NO stray top-level `sem-cards.js` may shadow it. Locks in the #219 regression family — a shadowing top-level file breaks every dashboard card on every install. Runs over SSH against the deployed copy. (2026-05-29) |

## Future tests worth adding

These cover the bug families that hit us this week and were not
caught by unit tests:

- Session counter survives HA restart mid-charge (plug → restart → assert session_energy non-zero after restart)
- Dashboard regenerate doesn't trigger an HA restart (call `generate_dashboard`, watch HA stays up)
- Strategy reason must be non-empty when strategy is not "idle" (caught empty `strategy_reason` field earlier this session)
- Sentinel for the three-way budget disagreement — assert `coordinator.data.calculated_current` matches what the actuator would compute (will be retired once the budget unification plan ships)

Each becomes a 30–50 line script when its turn comes up.
