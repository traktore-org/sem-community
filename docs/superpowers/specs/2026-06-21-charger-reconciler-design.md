# Charger State Reconciler — Design Spec

**Date:** 2026-06-21
**Status:** Approved (direction), pending spec review
**Branch:** `feature/charger-reconciler`
**Issue:** #392 (and the class it represents — see "History")

## Problem

The KEBA P30 repeatedly drops to 6 A / pauses / chatters during charging, across
multiple modes. Between v1.6.x and 1.7.3-beta.49 SEM shipped **at least five
patches** for this symptom (benign failsafe, per-cycle watchdog refresh, brand-aware
heartbeat interval, idle debounce, knob cleanup). Each treated a symptom; the
symptom keeps returning in a new shape.

### Root cause (single)

SEM's actuator is **not idempotent**: it re-issues a hardware command **every
~10 s coordinator cycle** regardless of whether anything changed.

Live PROD evidence (2026-06-21 21:06, every 10 s, `count=391/4`):

```
decide ev_charger mode=min_plus_solar → intent=idle amps=0 budget=0W ::
  budget=4000W below 9A min — staying self-consumption-only
Charging session stopped for EV Charger via keba.disable     <-- re-fired 391×
actuate(ev_charger): IDLE — count=391/4
```

`actuate.py:95-104`: once past the 4-cycle idle debounce, the IDLE path calls
`command_idle()` → `keba.disable` on **every** subsequent cycle — re-disabling an
already-open contactor hundreds of times. The same per-cycle re-command pattern is
what starves / races KEBA's device-side failsafe in the charging path.

The adapter contract already *documents* the intended behaviour
(`charger_adapters/base.py:150-153`): "Idempotent — safe to call every cycle...
Adapters should suppress duplicate service calls when last_intent == IDLE and
power_w < handshake." `KebaAdapter.command_idle()` never implemented that
suppression. The contract was written for a reconciler that was never built.

### Why other HEMS are reliable

A fixed-current charge (the user's manual approach) is rock-solid because nothing
modulates. evcc/openWB modulate but don't chatter because they (a) reconcile to a
desired state rather than re-commanding every tick, (b) use multi-minute
enable/disable hysteresis (`guardDuration`), and (c) on phase-switch hardware drop
to 1-phase to widen the band. SEM already has (b) in `charge_stability`; it lacks
(a). (c) is hardware SEM's P30 does not have.

## Goal

Make the EV charger **rock solid across all modes**: it holds whatever current it
decides on, issues zero redundant commands, and never reverts to 6 A against intent.

### Non-goals (YAGNI)

- **Phase switching** — the P30 is fixed 3-phase (CLAUDE.md: "~4140 W minimum at
  6A"). The ~4.1 kW floor is physical and stays.
- **Native UDP/Modbus transport** (Approach C) — abandons the multi-brand adapter
  model.
- **"Never idle, backfill the floor from grid/battery"** — a `decide()` mode-policy
  choice, not an actuation concern. Possible follow-up.
- Changing `decide()` mode strategies or `charge_stability` hysteresis — both work;
  they stay.

## Approach: desired-vs-observed reconciliation (Approach B)

Replace the imperative per-cycle actuator with a reconciliation loop. `decide()` +
`charge_stability` already produce a *stable target*; the reconciler makes the
hardware match it with the **minimum necessary service calls**, then leaves it
alone. Idempotency by construction, for every mode.

### Components (each independently testable)

**1. `DesiredChargerState`** — pure value object derived from `ChargerDecision`:

- `OFF` — user `charge_mode=off` (`ChargerIntent.DISABLE`)
- `IDLE` — pause: surplus below floor / target met (`ChargerIntent.IDLE`)
- `CHARGE(amps)` — `ChargerIntent.CHARGE_AT_AMPS` / `CHARGE_MAX`

Pure mapping from intent → state. No new decision logic.

**2. `ObservedChargerState`** — read from the adapter + `ChargerPower`:

- `charging: bool` — `adapter.actual_charging(power)` (power-based, not the lagging
  binary sensor)
- `setpoint_a: int` — device `_current_setpoint` (last value SEM believes is set)
- `self_charging: bool` — `adapter.is_self_charging(power)`
- `power_w: float`

**3. `ChargerReconciler`** — per charger, stateful. Pure
`reconcile(desired, observed, now) → Action`, then applies the Action via the
adapter. Holds `_last_write_at`, `_last_applied`, `_session_armed`,
`_consecutive_idle_count` (the flicker hold moves here).

### Decision table (the heart)

Rows are evaluated **top-to-bottom; first match wins** (so the OFF/IDLE-specific
rows resolve before the generic ones, and the flicker hold resolves before the
re-assert-disable).

| # | desired | observed | → Action |
|---|---|---|---|
| 1 | OFF | drawing | `DISABLE` (user-explicit OFF — open contactor immediately, no flicker grace) |
| 2 | OFF / IDLE | not drawing | **NONE** ← kills the 391× `keba.disable` spam |
| 3 | IDLE | drawing, 1st consecutive idle cycle | **NONE** (flicker hold — absorb a 1-cycle surplus dip; previous setpoint stays) |
| 4 | IDLE | drawing, 2nd+ consecutive idle cycle | `DISABLE` (confirmed real — cloud / target met / unplugged) |
| 5 | CHARGE(N) | not charging | `START_SESSION` + `ARM_FAILSAFE` + `WRITE(N)` |
| 6 | CHARGE(N) | setpoint ≠ N | `WRITE(N)` (target change / drift correction) |
| 7 | CHARGE(N) | setpoint = N, heartbeat due | `WRITE(N)` (failsafe refresh) |
| 8 | CHARGE(N) | setpoint = N, fresh | **NONE** |

Note on rows 3–4: re-asserting `DISABLE` only happens while the box is *still
drawing* against an IDLE intent. Once it stops (row 2), the action drops to NONE —
the disable is not re-issued on an already-open contactor. This is the exact spam
fix.

`Action` enum: `NONE`, `WRITE_CURRENT(a)`, `DISABLE`, `START_AND_WRITE(a)`,
`ARM_FAILSAFE`. Multiple may compose for the start transition.

This single table unifies what today is scattered across: the self-resume guard,
the idle debounce, the `_set_current` heartbeat, and the failsafe patches.

### What stays (works — do not rip out)

- **`decide()` / mode strategies** — unchanged. The 4.1 kW floor is real; idling
  below it is *correct*. The reconciler stops the *churn*, not the idle.
- **`charge_stability`** (60 s enable / 300 s disable / median smoothing /
  deep-deficit grace, #461) — stays; feeds the reconciler a stable target.
- **`_set_current`'s write-level heartbeat dedup** — stays. Clean split:
  - **Reconciler** owns *intent-level* convergence: start / stop / idle
    idempotency, self-resume, failsafe arming.
  - **Device `_set_current`** owns *write-level* refresh: while charging, refresh
    the same value at `watchdog_refresh_interval_s` to feed the device failsafe.
  - No double bookkeeping — the reconciler decides *whether* to call
    `command_current(N)`; the device decides *whether the call results in a write*.

### Failsafe — handled in the converge loop

`ARM_FAILSAFE` (benign: `failsafe_timeout=30`, `failsafe_fallback=` charging floor)
fires on the `START_SESSION` transition and re-arms whenever observed state shows a
device reset (box stopped while desired = CHARGE). No more "set it in
`start_session` and hope it took" — arming is part of reconciliation, so a missed
arm self-heals next cycle.

### Where it lives

A `ChargerReconciler` instance per charger, held in the same per-charger registry as
the adapters (sibling to `PerChargerContext`, per `docs/MULTI_CHARGER.md`).
`actuate()`'s body becomes:

```python
await reconciler.reconcile_and_apply(decision, adapter, power, now)
```

The reconciler is brand-agnostic; all brand quirks remain in adapters.

## Testing

- **Pure decision-table tests** — `reconcile(desired, observed, now) → Action` for
  every row, no HA.
- **Regression for the live bug** — `desired=IDLE` for 100 cycles, box not drawing
  → exactly **0–1** disable calls (not 100).
- **Charging idempotency** — steady `CHARGE(N)` for 100 cycles → exactly
  `⌈duration / heartbeat⌉` writes (not 100).
- **Self-resume** — `desired=OFF` + drawing → `DISABLE` each cycle until observed
  stops.
- **Failsafe arming** — `START_SESSION` arms; missed arm re-arms next cycle.
- **Drift correction** — `CHARGE(N)` but observed setpoint = floor (failsafe tripped)
  → `WRITE(N)` next cycle.
- **All existing brand pipeline tests preserved** (`test_split_grid_integration.py`,
  `test_392_keba_heartbeat.py`, `test_315_offmode_keba.py`,
  `test_multi_charger_control.py`) — the reconciler is brand-agnostic.
- **FLEET-READ lint** + no-vacuous-pass (per `sem-test` skill) still apply.

## Rollout (full path; relief first)

1. **Increment 1** — reconciler skeleton + idempotent IDLE/OFF. Stops the chatter
   on PROD. Smallest shippable slice.
2. **Increment 2** — CHARGE start-transition + failsafe arming through the
   reconciler.
3. **Increment 3** — drift detection + full decision table; retire the scattered
   guards in `actuate.py` / `KebaAdapter`.

Each increment: TEST deploy + live verify before the next (per
`feedback_live_test_before_deploy`).

## Acceptance criteria

- PROD log shows **NONE** as the dominant per-cycle action while idle/steady —
  `keba.disable` and `set_current` fire only on real transitions or the heartbeat.
- A held `CHARGE(N)` stays at N across a full session (no unexplained 6 A reverts).
- All five EV modes verified live on HA-TEST with no command spam.
- Full test suite green; new decision-table + regression tests added.

## History (the patches this replaces / subsumes)

- `f0212f9` brand-aware watchdog refresh
- `f0e6b55` per-cycle watchdog refresh
- `9accafa` benign failsafe (kept — now arming is reconciler-driven)
- beta.46 KEBA failsafe root cause
- `actuate.py` idle debounce (folded into reconciler as the flicker hold)
