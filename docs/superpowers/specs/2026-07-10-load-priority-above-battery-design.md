# Load Priority Above Battery Charging (#576) — Design Spec

**Status:** Approved design — parked for build after the next stable (v1.7.4) cut.
**Issue:** [#576](https://github.com/traktore-org/sem-community/issues/576) (from @alexmc1510's #559 testing feedback).
**Date:** 2026-07-10.

---

## 1. Problem

SEM's discretionary consumers (surplus loads, EV) are fed the **true house surplus** —
`grid_export + own active draw` (`coordinator.py:3016`, #508 W7). Home-battery charging
absorbs solar *before* it becomes export, so the battery **silently outranks every
load**. @alexmc1510 (Victron): *"surplus should be power excess **not including** the
battery charge … some loads have more priority than the battery. It is the way Victron
works."*

Two concrete cases we're solving:

- **Generic loads** (reporter): a pool pump at priority 1 should consume solar that
  would otherwise charge the battery; a low-priority load should keep yielding to it.
- **EV** (Guido, live): 4 kW solar, home 1.75 kW, battery charging 2.4 kW at 85 % SOC,
  car connected drawing **0 W** — the battery eats the ~2.3 kW that could charge the car.

## 2. The model — one priority walk

Redefine the allocatable pool as **pre-battery surplus** and share it top-down by
priority. Each device declares a **minimum**; the battery's minimum is **0**, so it is
the natural **sink at the bottom**:

```
surplus = solar − home            (the pool, BEFORE the battery takes its cut)
walk devices by priority:
    give each device its share IF remaining surplus ≥ that device's minimum
    else skip it, flow down
battery = min 0 → absorbs whatever is left  (emergent: the inverter self-consumes it)
```

Three device shapes, one walk:

| Device kind | "Minimum" means | Consumes |
|---|---|---|
| **Heater / switch** (discrete) | rated power — all-or-nothing | exactly rated, or nothing |
| **EV** (modulating) | start current (per-charger, known) | min → max |
| **Battery** (continuous sink) | 0 | the residual |

**Reserve floor = the existing `battery_priority_soc` zone (default 30 %).**
- SOC **below** the zone → battery fills first (pool = today's export-only surplus).
- SOC **at/above** the zone → loads/EV get the **pre-battery** surplus and can pull power
  that would otherwise charge the battery.

Nothing is force-commanded on the battery: on self-consumption inverters (Huawei et al.)
the battery physically charges from leftover solar, so "battery as sink" is emergent —
we only change how much the *loads/EV* are willing to consume.

## 3. Use cases / acceptance scenarios

Each is a test case. EV min ≈ 5.5 kW assumed (KEBA 3φ, 8 A); reserve zone
`battery_priority_soc` = 30 %.

| # | Situation | Expected | Rationale |
|---|---|---|---|
| **U1** | 4 kW solar, home 1.75 kW, SOC 85 %, car connected. Pool ≈ 2.3 kW < EV min | Car stays off, **battery charges** the 2.3 kW | too low to run the car → don't dribble; battery is the sink. Matches today. |
| **U2** | 7 kW solar, home 1.5 kW, SOC 85 %, car connected. Pool ≈ 5.5 kW ≥ EV min | **Car charges**, battery takes the residual | above reserve + enough for EV min → car outranks battery charging. **The core win.** |
| **U3** | 3.5 kW solar, home 0 kW, SOC 85 %, two surplus heaters (1 kW each, prio 2 & 3) | Both heaters ON (2 kW), **battery gets 1.5 kW** | discrete loads switch on in priority order; battery absorbs residual. |
| **U4** | Any solar, SOC **below** `battery_priority_soc` (e.g. 25 %) | **Battery fills first**; loads/EV get export-leftover only (today's behavior) | reserve floor protects the evening; unchanged below the zone. |
| **U5** | 0.8 kW pool, one 1 kW heater (prio 2) | Heater stays **off** (0.8 < 1.0), 0.8 kW → battery | discrete load can't switch on below its rated power → flows to sink. |
| **U6** | User `force_charge` battery, or scheduled/arbitrage charge active | **No reclaim** — battery charging is honored | explicit/scheduled battery commands always win over the priority rule. |

## 4. Config surface (minimal — reuse, don't invent)

- **Reserve floor:** reuse existing **`battery_priority_soc`** (default 30). No new SOC knob.
- **Opt-in:** one new toggle, default **OFF** (same cautious pattern as arbitrage) —
  e.g. `load_priority_above_battery` ("Loads & EV charge before battery, above the
  reserve zone"). Off → today's behavior exactly.
- **Per-device participation:** a surplus device already has its priority + `surplus`
  mode. Loads in `peak_only` are untouched (they never participate in surplus). To use
  this, a device is set to `surplus` mode — no new per-device flag needed for the MVP.
- **UI:** the toggle lives in Config → Battery (or Config → EV). Mockup-first per the
  working agreement before building the card change.

## 5. Architecture — where it lives

The whole feature is essentially **one input-figure change + one SOC gate**, applied on
two paths:

**Path A — generic surplus loads (low risk).**
- `coordinator.py:~3016` builds `true_surplus_w = grid_export + active_surplus_draw_w`.
  Add, gated on the toggle AND `soc ≥ battery_priority_soc` AND battery not
  force/scheduled-charging:
  `available = true_surplus_w + max(0, battery_charge_power)`.
- Feed that to the existing `SurplusController.update(available_power_w)` — its
  priority walk, discrete-load thresholds, LIFO shed and anti-flicker are already
  battle-tested and unchanged.

> **Build note (2026-07-11, ruflo review):** Path B as originally sketched
> (add reclaim to `excess_solar`) is a **no-op** — `excess_solar` only feeds a
> debug log; the real EV surplus is `decide.py:self_consumption_surplus_w`,
> which **already** stops subtracting `battery_charge_w` above `auto_start_soc`
> (90 %) AND, in `solar_only`, adds `flow_calculator.battery_redirect_w` (a
> forecast/SOC-scaled reclaim of battery charge) on top. So the EV *already*
> reclaims battery charge — just gated at `auto_start_soc` and scaled by
> forecast, not the `battery_priority_soc` reserve zone. **#576-for-EV is
> therefore: lower/raise that existing `battery_redirect_w` gate to full above
> the reserve zone when the toggle is on — a careful modification of the
> battle-tested redirect, not a second parallel reclaim** (which would
> double-count). Deferred to a separate specced pass. **Phase 1 (generic loads)
> ships independently** and is unaffected — the loads path genuinely lacked any
> reclaim (it reads export-only), which is exactly what the reporter asked for.

**Path B — EV (careful, but NOT a merge).**
- The EV keeps its **entire own control stack** — state machine
  (`charging_control.py`), per-charger context / multi-charger distribution
  (`ev_control.py`), `EVBudget`, reconciler (`charger_reconciler.py`), taper, session
  isolation. **None of it moves into `SurplusController`.** The EV stays
  `managed_externally` and excluded from the device list (`surplus_controller.py:289`).
- The ONLY change: the EV budget's **input surplus figure**. Above the zone it reads
  the same **pre-battery** surplus (export + reclaimable battery-charge) instead of
  export-only, min-gated by the charger's known start current. Below the zone,
  unchanged. A few lines in the EV budget calc — the heavy machinery is untouched.

**We keep TWO parallel control paths — exactly as today.** The EV path and
`SurplusController` already run independently and each consume a surplus figure; we do
**not** unify the allocators. The single shared artifact is the pre-battery surplus
*number*, computed once and fed to both.

**Coordination (the one real care-point — not a merge):** if both paths independently
added the full `battery_charge_power`, they could *double-count* the same reclaimable
watts within a cycle → a transient grid-import blip until the next cycle's measurements
settle. Resolve by **ordering**: evaluate the EV first, then offer `SurplusController`
the reclaimable power **net of the EV's just-taken share** (the live
`grid_export`/`battery_charge` it reads already reflects the EV once the charger ramps —
same cross-cycle convergence that governs export today; the ordering just tightens the
transient). This is a small, well-scoped guard, not a structural change.

**Untouched:** `decide_battery.py` (no battery command added), the inverter's
self-consumption charging (absorbs residual automatically), home/peak paths, and the
entire EV state-machine/budget/reconciler stack.

## 6. Feature-interaction map

| Feature | Interaction | Resolution |
|---|---|---|
| **Battery reserve/zone** (`battery_priority_soc`, `battery_buffer_soc`) | the floor | below zone battery wins; above zone loads/EV win. The single real interaction. |
| **Battery-assist / Solar Gate (#537)** — battery *discharges* to help EV | opposite direction + **redesign** | This feature only redirects power that would **charge** the battery; it never triggers discharge (two distinct switches). AND: the brittle surplus-threshold Solar Gate is **retired** in favour of `is_night` + `min_solar_w` + SOC floor — see **§6.5**. |
| **Force-charge / force-discharge / scheduled / arbitrage** | explicit command | **no reclaim** while active (U6). Gate the reclaim on "battery in normal self-consumption charging". |
| **Night charge scheduler** (cheap-grid) | none | night, grid-sourced; this is a daytime solar rule. |
| **EV modes** (solar_only / min_plus_solar) | integration, not collision | modes keep their meaning; only the EV's surplus input grows above the zone. |
| Home consumption, peak shedding | none | home always first; peak shed is a separate path. |

## 6.5 Retire the battery-assist Solar Gate (`battery_assist_min_surplus_w`)

**Motivation (Guido, 2026-07-10):** the v1.7.4-beta.35 EV flap traced to the
battery-assist **Solar Gate** — `battery_assist_min_surplus_w` (default 1200 W)
in `decide.py:battery_assist_budget_w`. Its *intent* is sound: "only let the
battery discharge into the EV when the sun is actually producing — never drain
the home battery into the car on a sunless evening." Its *mechanism* is brittle
in two ways that caused the flap:

1. **It's a cliff.** `surplus ≥ 1200 W` → the FULL battery potential (~11 kW) is
   offered; `surplus < 1200 W` → **zero**. A one-cycle dip flips the entire
   budget → IDLE → contactor drop.
2. **It reads a self-referential, noisy signal.** It gates on
   `surplus = solar − home`, and `home` is contaminated by the EV's own
   (UDP-laggy) draw. So the gate asks "is the sun out?" using a number that
   swings with the car — the beta.35 root cause.

**Replacement — reuse signals SEM already trusts (no new machinery):**

| Concern the gate served | Brittle today | Robust replacement (already in SEM) |
|---|---|---|
| Don't drain battery at night | `surplus < 1200 W` (cliff, noisy) | **`is_night`** — sunrise/sunset via astral (`utils/time_manager.py:is_night_mode`), the SAME signal overnight charging uses |
| Only assist when sun is producing | same surplus threshold | **`solar_w ≥ min_solar_w`** — RAW solar (feedback-free; `decide.py:410` already uses it in `solar_only`) |
| Protect the evening reserve | (not really handled) | **SOC reserve floor** (`battery_priority_soc`, §2) |
| Size the assist | surplus (swings with the car) | **feedback-stable surplus** (§7) |

**Outcome:** `battery_assist_min_surplus_w` is **retired**. Battery-assist gates
on `not is_night AND solar_w ≥ min_solar_w AND soc ≥ reserve` — all
noise-free, feedback-free, and (critically) making the battery-assist day/night
definition **consistent with overnight charging** instead of a second, separate
threshold. No cliff, no car-contaminated input, nothing to blip.

**Note:** the beta.35 `ev_power` median-of-3 fix removes the *trigger* (sensor
noise) and is the correct standalone fix; this section removes the *brittle
mechanism* the trigger exploited. Ship order: beta.35 first (done), this
redesign folds into the #576 build.

## 7. Anti-oscillation

The issue's stated worry — *"a load stealing charge power lowers battery charging, which
raises apparent surplus…"* — does **not** arise here. Because the pool is
`solar − home` (invariant to how we allocate *out of* it — a device's own draw is added
back via `active_surplus_draw_w`), consuming from the pool shrinks it by exactly what
was consumed and converges. The existing **median-of-3 pre-filter + EMA** (arc Phase 4)
and **LIFO/anti-flicker** guard the residual jitter. No new anti-oscillation machinery.

## 8. Build order (two phases, natural boundary)

- **Phase 1 — generic loads (low risk):** the input-figure change on Path A + the toggle
  + the `battery_priority_soc` gate + the force/scheduled-charge guard. Delivers
  U3/U4/U5/U6 and the reporter's generic-loads ask. Almost entirely reuse.
- **Phase 2 — EV (careful, NOT a merge):** feed the same pre-battery surplus figure into
  the EV budget's input above the zone, min-gated, plus the EV-first ordering guard
  (§5). The EV's own control stack is untouched. Delivers U1/U2 and Guido's car case.

Phase 1 is shippable on its own; Phase 2 reuses the exact same pool quantity and adds
**no coupling between the two control paths** — only a shared input number + an ordering
rule. The parallel EV/loads control we have today is preserved, not unified.

## 9. Testing

- **Pipeline/unit:** the U1–U6 acceptance scenarios as explicit tests.
- **Reserve floor:** below `battery_priority_soc` → behavior byte-identical to today
  (regression guard — toggle OFF and below-zone must both be no-ops).
- **Guard:** force-charge / scheduled / arbitrage active → no reclaim.
- **Anti-oscillation:** a step change settles within the existing filter window; a load
  at its threshold does not flap.
- **Mode parity:** solar_only / min_plus_solar semantics unchanged.
- **Live HA-TEST:** reproduce U2 (force solar high + SOC above zone + car connected →
  car charges, battery residual) and U4 (SOC below zone → battery first) before merge,
  per the live-test-before-deploy rule.

## 10. Risks & open questions

- **R1 (Phase 2):** the EV decide path is battle-tested; folding the pre-battery pool in
  must not regress solar_only/min_plus_solar. Mitigation: wrap + full scenario suite +
  live verify.
- **R2:** non-self-consumption inverters that require SEM to *command* battery charging
  would need the battery-as-explicit-device variant (command charge-limit down to free
  power). Out of scope for MVP; revisit if a reporter needs it.
- **Q1:** default priority of the battery relative to unranked surplus loads — is the
  battery strictly below all `surplus` loads above the zone, or is there a configurable
  battery slot? MVP: battery is strictly the sink above the zone (simplest, matches
  Victron). Revisit only if requested.

## 11. Out of scope (explicit)

- Grid-assist to force a load/EV to its minimum (that's what `min_plus_solar` already is).
- Dynamic phase switching (3φ↔1φ) to lower the EV minimum — hardware-dependent.
- Re-enabling export arbitrage (#533, separately gated).
- Cross-load *shedding* to feed a higher-priority load (a different feature from
  battery-vs-load priority; not requested).
