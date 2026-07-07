# Generic-Device Control Arc — design

**Date:** 2026-07-07
**Motivation:** #559 exposed that generic surplus devices (switches, climate, hot
water, pumps) lack the robustness "arc" the EV charger has. Bugs like the
rated-power collision are symptoms of a thin, organically-grown layer. Bring the
generic path toward the EV charger's proven architecture — **incrementally**, no
big-bang rewrite (these control real loads on PROD).

## Reference — the EV charger arc (what we mirror)

- **`charger_reconciler.py`** — a *desired-vs-observed* reconciler. Each cycle it
  reads the charger's **observed** state (actual power draw, last setpoint, enable
  state) and compares it to the **desired** state (OFF/IDLE/CHARGE), emitting only
  the minimal idempotent actions to converge (never re-issues a command that's
  already satisfied). A `reconcile()` pure decision function + a
  `reconcile_and_apply()` effectful wrapper.
- **`per_charger_context.py`** — a typed context object that owns the per-charger
  "swap surface": on `__enter__` it swaps this charger's state into the working
  slots, on `__exit__` it persists updates back. State lives in one place, keyed
  by charger id.
- **`charge_stability.py`** — a smoothing/hysteresis layer (5-cycle median, delta
  guard, time debounce, enable/disable delays) between the surplus signal and the
  actuator, so a one-cycle inverter flicker never reaches the hardware.

## The generic path today — the gaps

1. **Three overlapping device collections** that can disagree:
   `UnifiedDeviceRegistry._devices` (auto-discovered, rebuilt each sync),
   `._service_registrations` (explicit, persisted), and
   `SurplusController._devices` (live device objects). The #559 collision (an
   auto-discovered row shadowing an explicit registration for the same switch)
   is a direct symptom.
2. **No desired-vs-observed reconciliation.** `SurplusController` calls
   `device.activate()`/`deactivate()` directly and trusts `_status.state`; it
   never reads back the real switch/power state, so silent actuation failures or
   external toggles cause undetected drift.
3. **Two registration paths, no unified ownership** — auto-discovery vs explicit
   registration dedup reactively, not by construction.
4. **No per-device context** — state is scattered across `_status`, anti-flicker
   timers, daily-runtime attrs, surplus timers, dependency attrs on each device.
5. **No smoothing** for generic devices — instantaneous surplus drives
   activate/deactivate, so solar flicker can flap a load.
6. **No desired-state model** (user-OFF vs SEM-paused vs SEM-ON) — SEM can't tell
   a user's manual switch-on from its own, and fights it on the next surplus drop.
7. **Goal feedback trusts belief** — daily-runtime accrues on `is_active` (our
   belief), so a load that failed to actuate still gets runtime credit.

## Design — the generic-device arc

Mirror the three EV pieces, adapted to on/off (and climate) loads:

### Component 1 — `DeviceReconciler` (desired-vs-observed)
A per-device reconciler analogous to `charger_reconciler`:

- **Desired state**: `OFF` (user/control_mode=off — SEM never drives it),
  `IDLE` (SEM is not allocating surplus this cycle → should be off unless a goal
  force applies), `ON` (SEM wants it drawing).
- **Observed state**: the control entity's actual state (`switch` on/off, or
  `climate` hvac_mode) **and** the power-sensor draw.
- **Pure `reconcile(desired, observed)`** → minimal action list
  (`TURN_ON`/`TURN_OFF`/`NONE`), idempotent: emit nothing when observed already
  matches desired; re-assert only on genuine drift. Honors the existing
  anti-flicker (min_on/min_off) as *reconciler* gates, not blind pre-checks.
- **`reconcile_and_apply(device, desired, observed)`** actuates via the device's
  existing `activate()`/`deactivate()` (which become the low-level actuators the
  reconciler calls, not the decision point).

Fixes gaps **2, 8** (drift detection + read-back → goal credit on observed draw).

### Component 2 — `PerDeviceContext`
A typed context object (mirror `PerChargerContext`) that, for one device's cycle,
holds: `device_id`, the live device, its `this_power_w` (observed draw), desired
state, goal/runtime snapshot, and the anti-flicker timers — computed once per
cycle and persisted back on exit. Collapses the scattered instance attrs into an
explicit swap surface.

Fixes gaps **4, 6-partial** (one place for per-device cycle state).

### Component 3 — Unified device model (single source of truth)
Collapse the three collections into **one authoritative device list** with a clear
ownership rule: **an explicit registration always wins over auto-discovery for the
same control entity**, resolved *by construction* (at registration + sync time),
not reactively at query time. `get_devices_for_sensor` reads from the one model.

Fixes gaps **1, 3** (the whole #559 collision class, at the root).

### Component 4 — Surplus smoothing + desired-state
- A small smoothing layer (median + delta guard + enable/disable delay), reusing
  the `charge_stability` ideas, between the surplus signal and the reconciler.
- Desired-state tracking: distinguish **user-OFF** (control_mode=off, or the user
  toggled the switch) from **SEM-paused** (IDLE) — so SEM adopts a user's manual
  on/off instead of fighting it; and re-adopts correctly on restart.

Fixes gaps **5, 6, 7**.

## Phasing (each phase = independently shippable + testable beta)

- **Phase 1 — Unify the device model (Component 3).** Highest value / lowest risk.
  Collapses the three collections, makes explicit-registration-wins structural,
  dedups by construction. This is the *root* fix for the #559 class (the current
  #559 commit is a targeted symptom patch that ships meanwhile). Pure
  representation/ownership change — no actuation change, so low blast radius.
- **Phase 2 — `DeviceReconciler` (Components 1).** Introduce desired-vs-observed
  reconciliation; `SurplusController` calls the reconciler instead of
  activate/deactivate directly. Adds read-back + drift correction + idempotent
  actuation. Medium risk (actuation path) — gated behind thorough tests + a live
  soak, one device type at a time (SwitchDevice first, then Climate).
- **Phase 3 — `PerDeviceContext` + desired-state (Components 2, 4-partial).**
  Collapse scattered per-device state; add user-OFF vs SEM-paused tracking +
  restart adoption. Medium.
- **Phase 4 — Smoothing + goal feedback (Component 4).** Median smoothing for
  generic loads; runtime credited on observed draw. Low-medium.

Each phase: TDD, full suite, ruflo review, live-verify on HA-TEST, one beta, PROD
soak before the next phase.

## Design refinement (2026-07-07, during Phase 2 implementation)

**The reconciler is ADDITIVE, not a replacement for the allocation loop.** The
original Phase 2 framing ("`SurplusController` calls the reconciler instead of
activate/deactivate directly") implied rewriting the allocation loop. On close
reading that loop is battle-tested and tuned (goal gates, cheap-hours force
expiry, LIFO deficit shedding, peak-shed, dependency cascade, anti-flicker, and
it *already* EMA-smooths surplus). Rewriting it — especially unsupervised — is
disproportionate risk for the value.

Revised Phase 2: `DeviceReconciler` runs **alongside** the loop each cycle and
delivers the desired-vs-observed value additively:
- **Ownership** (`_sem_owned` on the device) — set when SEM activates, cleared
  when an external actor changes the physical state.
- **Belief↔observed reconciliation** — SEM-believed-ON but entity-reads-OFF
  (past a grace window) → correct the belief (accurate runtime accounting; stop
  crediting a load that isn't drawing). Entity-reads-ON but SEM-believed-IDLE →
  mark not-owned (external/user on) without fighting it.
- **Respect a manual OFF** — an `_external_off_until` cooldown (wired into
  `can_activate`) stops SEM re-activating a load the user just turned off.

The tuned allocation loop is untouched; the reconciler only keeps belief in sync
with reality and adds ownership-awareness. Phases 3–4 (context object, smoothing)
remain optional refinements on top.

## Non-goals / guardrails
- **No big-bang rewrite.** Each phase preserves current behavior for loads that
  already work; the arc is added underneath.
- **Don't over-engineer simple switches.** A reliable `switch.turn_on` mostly
  works; the arc's value is drift-correction, clean ownership, and parity for the
  growing device-type set (climate, hot water, multi-device) — not ceremony.
- The EV charger keeps its own (more specialized) arc; this is the *generic*
  device arc. Shared ideas, separate code (an EV isn't an on/off load).

## Open questions (resolve before Phase 2)
- Does `SwitchDevice.activate/deactivate` stay the low-level actuator the
  reconciler calls, or do we introduce a thin adapter (like `charger_adapters`)
  per device type? Leaning: keep activate/deactivate as actuators for now; add
  adapters only if a device type needs non-trivial observe/command logic
  (climate already does hvac_mode read-back).
- Observed-power source per device: the configured/auto-detected power sensor.
  When absent, fall back to the control entity's on/off state alone (no drift
  detection on power, only on state).

## Status (2026-07-08)

- **Phase 1** — root-collapse of the three device collections: NOT done as a
  structural rewrite; the #559 explicit-registration-wins fix (beta.28) resolves
  the collision class at the query layer. A full single-collection refactor was
  judged disproportionate risk unsupervised; revisit only if the class recurs.
- **Phase 2** — DeviceReconciler: **SHIPPED v1.7.4-beta.29** (additive, live-verified).
- **Phase 3** — desired-state model + ownership observability (`desired_state`,
  `observed_on`, `sem_owned` in to_dict + Control payload): **SHIPPED v1.7.4-beta.30**.
  A full PerDeviceContext object was deliberately skipped — the device object
  already holds per-device state; the missing piece was the model + observability.
- **Phase 4** — observed runtime credit + median-of-3 surplus pre-filter:
  **SHIPPED v1.7.4-beta.30** (live-verified on HA-TEST).
