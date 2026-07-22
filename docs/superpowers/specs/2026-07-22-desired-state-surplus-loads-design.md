# Declarative desired-state for surplus loads — design

*2026-07-22. Scope: the surplus-controller's generic loads (switch / climate /
heat-pump / hot-water). NOT the EV charger (its own decide/actuate path stays).*

## Why (the problem, in the three-layer frame)

SEM's device control should split cleanly into three layers:

| Layer | Owns | Should answer |
|---|---|---|
| **Management** | policy / decision | *what state should this device be in?* |
| **Integration** | truth from sensors + state | *what is actually true right now?* (surplus, observed on/off) |
| **Execution** | hardware actuation | *make reality match the decision* |

Today, for loads, **management and execution are fused**. `SurplusController.update()`
is imperative: **7 passes** each reach straight into the hardware, for **9
`activate()` / `deactivate()` / `adjust_power()` call sites**:

1. **Force-expiry** — ends a cheap-hours (`_offpeak_forced`) or Tier-2
   (`_batt_overnight_forced`) run when its reason lapses → `deactivate`.
2. **Activation pass** — reclaim handoff at the battery slot, goal gates
   (done-for-the-day → `deactivate`), Tier-1 headroom, `activate` / `adjust_power`.
3. **Deactivation LIFO** — surplus went negative → `deactivate` lowest priority.
4. **Peak-shed** — SHEDDING/EMERGENCY → `deactivate`.
5. **Scheduled devices** — deadline → `activate`.
6. **Off-peak pass** — cheap-hours → `activate` + set `_offpeak_forced`.
7. **Tier-2 pass** — overnight battery → `activate` + set `_batt_overnight_forced`.

### The bug class this fusion manufactures

Because a device's on/off decision is *scattered* across those passes, **a new
gate must be threaded into two places** — the "don't turn on" spot **and** the
"stop if already running" spot. Miss the second and you ship:

> **"a gate blocks activation but nothing stops a device already running."**

In #620 this class recurred **four times** in one feature: the daily-max cap,
the battery-overnight toggle, and the overnight-source picker's off-Battery and
off-Grid paths. Each fix was the *same* fix — add the condition to a
force-expiry section — applied to a different pass. Plus a family of
marker-leak bugs (`_batt_overnight_forced` / `_offpeak_forced` set in one pass,
must be manually cleared in several others).

More tests don't cure this — they test *instances*. The architecture invites the
miss. (Contrast the integration layer: the phantom-surplus fix was **one
function, one invariant** — `solar_bounded_surplus`, `surplus ≤ solar` — and
docked cleanly. That's what a load-management fix should also look like.)

## Goal

Make the class **unrepresentable**: management computes **one** authoritative
`desired_state` per load; execution is **one** reconcile step. A gate becomes a
*term* in a pure function, so a gate that yields OFF stops a running device **by
construction** — there is no separate deactivation path to forget.

## Non-goals

- The **EV charger** (separate decide/actuate + charge_stability; untouched).
- The **integration layer** surplus math (`solar_bounded_surplus`, reclaim,
  medians) — already clean; this spec consumes it, doesn't change it.
- Adding features. This is a behavior-preserving refactor.

## Design

### 1. The intent (management output)

```python
@dataclass(frozen=True)
class LoadIntent:
    on: bool                 # desired power state
    power_w: float           # desired draw (rated for switches; modulated for others)
    source: str              # 'solar' | 'tier1_battery' | 'tier2_battery' | 'cheap_grid' | None
    reason: str              # human/trace string, e.g. "cap reached", "surplus 1.4kW ≥ 800W"
```

`source` **derives** the old forced markers instead of hand-setting them:
`_batt_overnight_forced == (source == 'tier2_battery')`,
`_offpeak_forced == (source == 'cheap_grid')`. Marker leaks disappear — the
markers are a *view* of the current intent, recomputed each cycle.

### 2. `compute_desired(device, ctx) -> LoadIntent` (pure)

A single precedence walk. `ctx` carries the cycle's shared truth (remaining
surplus after the priority walk to this device, battery SoC/buffer/reserve/assist
budget, price level, peak state). **Precedence, highest first — the first match
wins:**

1. **Not SEM-driven** — mode `off` / `peak_only` → `LoadIntent(on=<observed>, source=None)`
   (SEM never proactively drives it; peak-shed for peak_only is handled in ctx as
   a shed request, see risks).
2. **Done for the day** — `daily_max_runtime_reached` OR `daily_targets_met` OR
   `stop_condition_met` → **OFF**.
3. **Peak shed** — ctx says this load is the shed target this cycle → **OFF**.
4. **A source can power it** (in order): solar surplus ≥ threshold →
   `source='solar'`; else Tier-1 headroom lifts it over threshold + SoC>buffer →
   `'tier1_battery'`; else overnight picker = Battery + deficit + SoC>reserve →
   `'tier2_battery'`; else overnight picker = Grid + deficit + cheap window →
   `'cheap_grid'`. → **ON** at `power_w`.
5. **Otherwise** → **OFF**.

Every gate from the 7 passes is now a clause here. Notably, the **force-expiry
sections vanish**: a source that stops being eligible (tariff left cheap, SoC hit
reserve, user flipped the picker, cap reached) simply fails its clause → intent
flips OFF → execution stops it. No compensating "expiry" code.

### 3. `reconcile(device, intent)` (execution — the only actuator)

The **sole** place that calls `activate/deactivate/adjust_power`:

```
if intent.on and not device.is_active and can_activate(intent):   activate(intent.power_w)
elif not intent.on and device.is_active and can_deactivate(intent): deactivate()
elif intent.on and device.is_active:                               adjust_power(intent.power_w)
```

- **Anti-cycle lives here, uniformly.** `can_activate` / `can_deactivate` own
  `min_on` / `min_off`. This is also where the deferred **"user intent uses the
  EV's disable-delay, not the flat 5-min min_on"** decision plugs in — one place,
  not per-pass.
- Reconcile is idempotent and order-free: run `compute_desired` for every load,
  then `reconcile` every load. No pass ordering, no LIFO, no cross-pass state.

### 4. Where the current passes fold

| Old pass | Folds into |
|---|---|
| Force-expiry (off-peak + Tier-2) | **deleted** — source clauses in `compute_desired` handle eligibility; reconcile stops on OFF |
| Activation pass | clause 4 (sources) + reconcile |
| Goal gates (done-for-day) | clause 2 |
| Deactivation LIFO | clause 4 fails (no surplus) → OFF; reconcile stops. Priority order preserved by the ctx surplus-walk that fills `remaining_surplus` per device |
| Peak-shed | clause 3 (ctx marks the shed target) |
| Off-peak pass | clause 4 `'cheap_grid'` |
| Tier-2 pass | clause 4 `'tier2_battery'` |
| Scheduled devices (deadline) | out of scope for loads (ScheduleDevice) — keep as-is initially |

## Migration (parity-gated, reversible)

1. **Extract, don't rewrite.** Write `compute_desired` + `reconcile` as pure
   functions beside the existing `update()`. Feature-flag `use_desired_state`
   (default off).
2. **Golden parity harness.** Replay a corpus of cycle inputs (the existing
   `test_508` / `test_559` / `test_620` scenarios + recorded PROD cycles) through
   BOTH paths; assert identical activate/deactivate/adjust decisions. This is the
   safety net — no behavior drift ships.
3. **Flip the flag** once parity is green across the corpus; delete the 7 passes
   and the force-expiry/marker-clear code.
4. **Bounded blast radius:** loads only. EV, battery pipeline, integration math
   untouched.

## Test strategy (the guard that makes the class un-shippable)

- **Family invariant (the point):** one parametrized test enumerating **every**
  clause-2/clause-3 gate — cap, target-met, stop-sensor, overnight-off,
  grid-off, reserve-crossed, peak-shed — asserting each yields `intent.on ==
  False` **and** that `reconcile` stops a running device. Add a new gate → add a
  row, or the test fails. The class cannot regress.
- **Property tests:** `compute_desired` is pure (no I/O, deterministic);
  `source` and the derived markers agree; `intent.on == False` ⇒ a running load
  reconciles OFF (modulo anti-cycle).
- **Parity corpus** (migration gate, above).
- Keep the integration-layer `solar_bounded_surplus` tests as-is.

## Bug classes this closes (docs/BUG_CLASSES.md)

- **"Gate blocks activation but doesn't stop a running device"** — becomes
  unrepresentable (one desired-state, one reconcile).
- **"Forced-marker set in one pass, leaks because another pass didn't clear it"**
  — markers become derived views of `source`, recomputed each cycle.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Behavior drift | Golden parity corpus gates the flag flip |
| Anti-cycle relocation changes flap timing | `can_activate/can_deactivate` unchanged; only their call site moves |
| Peak-shed "one per cycle" semantics | ctx computes the shed target(s) before the per-load walk; clause 3 reads it |
| Reclaim / battery-priority (#576) handoff | ctx fills `remaining_surplus` per load via the same priority walk; clause 4 reads it — the walk stays, only the *actuation* moves out |
| Scope creep into the EV | explicit non-goal; EV path untouched |

## Rollout

One `feature/desired-state-loads` branch, parity-gated, soaked on PROD (real
hardware) exactly like #620. Merge + tag only after the parity corpus is green
and a live soak confirms identical behavior.
