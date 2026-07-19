# Multi-Charger Correctness — Developer Guide

This document is the source of truth for **developers** working on SEM's
multi-charger code paths. For end-user setup with multiple chargers, see
[`MULTI_DEVICE_GUIDE.md`](MULTI_DEVICE_GUIDE.md).

> **v1.7.3** — actuation is now done by the **charger state reconciler**
> (`coordinator/charger_reconciler.py`, #392), one instance per charger held across
> cycles. Each charger has its own desired state (from per-charger `decide()`), its
> own observed state (contactor / enable switch / setpoint), and converges
> idempotently — eliminating the per-cycle command spam the old imperative actuator
> produced. The **enable switch** is treated as observed state and re-asserted with
> backoff (#536). The per-charger correctness discipline below (fleet-read
> annotations, `PerChargerContext`) still applies — the reconciler consumes the
> per-charger `EVBudget`/decision, it does not change how the budget is split.

---

## v1.7.0: The bug class is structurally retired

The per-device-primary architecture rebuild (PR #358 + #360 + #361 + #362)
**eliminates the bug class this document describes** by construction.
What used to be a discipline ("don't read `power.ev_power` inside the
per-charger loop") is now a structural property of the data model.

The new pipeline:

```
PowerReadings.ev_power_per_charger: Dict[str, ChargerPower]   ← PRIMARY
PowerReadings.ev_power: FleetEvPower                          ← cached sum

for each charger in coord._per_charger:
    view = build_charger_view(charger, power_readings, ...)
    decision = decide(view)                                   ← pure
    await actuate(decision, adapter, view.power)              ← brand-aware
```

Key invariants now enforced by the type system:

- **`decide(view)` is pure** — no `self`, no HA calls, no shared state.
  Same `ChargerView` always produces the same `ChargerDecision`.
- **`ChargerView.power` is a single charger's slice**, not the fleet
  sum. There is no way for `decide` to accidentally read fleet state.
- **One `ChargerDecision` per charger per cycle.** The strategy/state-
  machine disagreement class (#346) cannot exist — there is no second
  decision authority.
- **Brand quirks live in `ChargerAdapter` subclasses.** KEBA's 6 A
  minimum, `set_current(0)` rejection, and self-resume detection (the
  #315/#346/#353 cluster) are encapsulated in `KebaAdapter`; the
  actuator says `adapter.command_idle()` without knowing why KEBA
  needs `keba.disable` instead of `set_current(0)`.
- **Per-charger flow attribution uses priority allocation, not
  fraction-of-fleet.** A `solar_only` charger in a two-charger fleet
  no longer gets falsely attributed grid imports that the
  `min_plus_solar` sibling actually consumed.

The verification floor is the **simulation-driven test suite**:

- `tests/test_step8_invariants.py` — 233 architectural invariants
  parametrised across the full operating envelope.
- `tests/test_surplus_charging_scenarios.py` — 93 behavioural
  scenarios walking every (mode × battery zone × time × solar)
  combination through `decide → actuate → adapter`.

Any future change that violates an invariant fails CI before reaching
HA-TEST. The "deploy and watch logs" cycle that pre-v1.7.0 was the
only way to catch these bugs is no longer the safety net — the
invariant suite is.

The rest of this document describes the **historical bug class** and
the v1.6.x band-aids that preceded the rebuild. Kept for context and
as a reference for anyone hunting similar shapes in unrelated code.

---

## The bug class we keep finding

Between v1.6.0 and v1.6.6 SEM shipped four hotfixes for variants of the
same bug — each one a "per-charger context swap with fleet-level reads
still leaking through":

| Release | Issue | Fix shape |
|---|---|---|
| v1.6.0 | #284 | Distributor used the legacy `_calculate_solar_ev_budget` formula instead of the canonical `EVBudget.net_w` |
| v1.6.5 | #289 | Fleet aggregation on the 10 s cycle hid sub-cycle KEBA spikes |
| v1.6.5 | #315 | `_this_charger_power` helper introduced because the off-mode terminator read `power.ev_power` (fleet sum) |
| v1.6.6 | #318 | `_update_per_charger_detector_energy` helper introduced because `update_energy()` was only called on the primary detector |

Each was a separate band-aid. The v1.6.7 cleanup
([`PerChargerContext`](../coordinator/per_charger_context.py)) lifts the
swap mechanism into a typed context manager so that the **invariant** —
"inside a per-charger iteration, read this charger's view, not the
fleet's" — can be enforced structurally rather than by memory.

---

## The invariant

> **Inside a `with PerChargerContext.for_charger(...)` block — including
> any method called from inside that block, transitively — never read
> `power.ev_power` directly. Use `self._this_charger_power(ev, power)`
> (cached as `this_power_w` at the top of the method) or tag the read
> explicitly with `# FLEET-READ: <reason>`.**

Likewise: never read `self._ev_*` directly; the context owns them and
they reflect THIS charger only during the block. Reading them from
outside the block returns the primary charger's view (the legacy
"fleet" semantic for backward compat).

To add a new per-charger field, edit `PerChargerContext` only —
don't add new ad-hoc swap dicts.

### `# FLEET-READ:` annotation

The lint test at `tests/test_ev_control_fleet_reads.py` parses
`coordinator/ev_control.py` and fails CI on any `power.ev_power` read
that is **not** either (a) inside the sanctioned `_this_charger_power`
helper or (b) annotated with `# FLEET-READ: <reason>` on the same line
or the immediately preceding line. The reason text is required and
shows up in code review — keep it short and concrete:

```python
# Bad — would fail the lint
if power.ev_power > 100:
    ...

# Good (per-charger; the right answer 99% of the time)
this_power_w = self._this_charger_power(ev, power)
if this_power_w > 100:
    ...

# Good (rare: genuinely fleet-level, e.g. a fleet-aggregating sensor)
# FLEET-READ: aggregating total EV draw for the dashboard fleet card
fleet_ev_w = power.ev_power
```

The lint is intentionally cheap (AST walk, no runtime) so it runs on
every PR. If you find yourself reaching for the annotation, ask
yourself: is this code actually inside the per-charger loop? If yes,
you almost certainly want `this_power_w`. If no, you don't need the
annotation at all — the lint only flags reads inside `ev_control.py`.

---

## What the context manager owns (post-#589: NO swap remains)

`coordinator/per_charger_context.py` ([source](../coordinator/per_charger_context.py)):

The #589 swap retirement (v1.7.5) **deleted the snapshot/restore
mechanism entirely.** Per-charger state now lives in exactly two places:

1. **Durable fields** — on `PerChargerState`, one instance per charger in
   `coord._pcc_store[cid]`, held by the active context **by reference**:
   `stalled_since`, `enable_surplus_since`, `charge_started_at`,
   `last_change_time`, `reenable_attempts`, `charge_refused`,
   `last_set_amps_ts`.
2. **Cycle-scoped fields** — on the `PerChargerContext` object itself:
   `budget_w`, `vehicle_soc`, `this_power_w`, `effective_state`,
   `charger_name`.

The coordinator's legacy attribute names (`self._ev_stalled_since`,
`self._cycle_vehicle_soc`, `self._ev_device`, …) are **properties** that
dispatch on `coord._current_pcc`: inside the per-charger loop they
resolve to the active context's values, outside it to the
primary/default backing. `__enter__` = bind store object + seed SOC +
set the pointer; `__exit__` = persist `effective_state` + clear the
pointer. There is no snapshot and no restore, so a forgotten write-back
(the #284/#315/#318 leak) is **unrepresentable**.

Retired outright as dead state during the retirement:
`_ev_budget_history` (+ its `_per_charger` dict; consumer removed in
#536) and `_current_charger_budget` (budget flows through
`pcc.budget_w → build_charger_view`).

---

## How to add a new per-charger field

1. **Durable across cycles?** Add a field on `PerChargerState`. If
   legacy code reads it as `self._ev_<x>`, add a coordinator property
   pair dispatching on `_current_pcc` (mirror `_ev_stalled_since`).
2. **Cycle-scoped?** Add a field on the `PerChargerContext` dataclass
   (mirror `vehicle_soc`).
3. Add a unit test asserting cross-charger isolation: divergent values
   on two chargers, no bleed, out-of-loop reads see the default.

**Never** add a `saved = {...}` snapshot, a `coord._ev_* = …` assignment
in `__enter__`/`__exit__`, or a parallel `_<x>_per_charger` dict — the
AST guard at `tests/test_589_percharger_astguard.py` fails CI on all
three shapes.

---

## Why a `with` block instead of a function?

Because the existing code at the per-charger loop body is ~120 lines of
inline mathematics (Min/Max remaining, night plan, off-mode override,
strategy dispatch) that all mutate the shared `charging_context` object
in place. Wrapping it in a function would require either threading every
mutation through a return value (giant call site, fragile to extend) or
mutating via reference (no clearer than the current state). The `with`
form keeps the inline code identical and just owns the lifecycle of the
swap.

A future v1.7+ refactor *might* migrate the inline math onto methods on
`PerChargerContext` (e.g. `pcc.compute_remaining_to_min()`,
`pcc.effective_state`) — but that's incremental work, not a blocker for
the structural invariant.

---

## Roadmap (what shipped vs. what's deferred)

| Release | Theme | Status |
|---|---|---|
| **v1.6.7** | Lift swap dict into `PerChargerContext` (identity + budget + skip flag) | ✓ shipped |
| **v1.6.8** | `ev_control.py` fleet-read sweep + AST lint test enforcing `# FLEET-READ:` | ✓ shipped |
| **v1.6.9** | Per-charger flow attribution + per-charger notification flap suppression | ✓ shipped |
| **v1.6.10** | Code-quality cleanup (#308 / #309 / #310) | ✓ shipped |
| **v1.6.11** | Recent-logs in diagnostics + doc polish | ✓ shipped |
| **v1.6.12** | Multi-charger off + solar_only scenario test + harness `per_charger_effective_states` / `per_charger_flow_max` assertions | ✓ shipped |
| **v1.6.14 (bundled closeout)** | (a) ✓ Surplus tracker jump-from-0 fix (#8); (b) ✓ `effective_state` + `this_power_w` migrated onto `PerChargerContext` fields; (c) ✓ per-charger flow sensors (`sensor.sem_charger_<id>_flow_*_to_ev_*` gated on `len(ev_chargers) > 1`); (d) ✓ `FleetEvPower` newtype + AST lint expanded to every `coordinator/` module. Shipped as one release rather than four per-PR HACS bumps. | ✓ shipped |

### What landed under the abstraction

`PerChargerContext` owns the **swap surface** for nine coordinator
attributes (8 in `_saved` + `_cycle_vehicle_soc`). As of v1.6.14 the
dataclass also carries the computed per-charger fields:

| Field | Set by | Read by | Purpose |
|---|---|---|---|
| `cid`, `ev_dev`, `charger_cfg` | `for_charger` | loop body | identity |
| `budget_w` | `for_charger` from `distribute_ev_budget` | `_ev_control` cascade | per-charger surplus slice |
| `skipped_for_night` | `for_charger` from `_mode_allows_night_charging` | loop body | night gate |
| `power` | `for_charger` (caller passes `power`) | `__enter__` | cycle-level `PowerReadings` for the precompute |
| `this_power_w` | `__enter__` via `coord._this_charger_power(ev_dev, power)` | `_this_charger_power` cache shim | this charger's draw (W) |
| `effective_state` | loop body assignment | `__exit__` → `_effective_states_per_charger` → `_send_notifications` | post-loop per-charger notification dispatch |
| `charger_name` | `for_charger` from `charger_cfg["name"]` (fallback `cid`) | `__exit__` | display name in notifications |

### Still deferred to v1.7+

- `night_plan` — currently stored in the parallel dict
  `_night_plan_per_charger`. Mechanically similar to the
  `effective_state` migration; defer until a consumer (e.g. the
  per-charger night-progress sensors) actually needs it on `pcc`.

### v1.6.15 — Per-charger flow sensors

The data is on `PowerFlows.per_charger` (since v1.6.9) but no
top-level HA entities expose it yet. v1.6.15 adds
`sensor.sem_charger_{cid}_solar_to_ev_power`,
`_grid_to_ev_power`, `_battery_to_ev_power` + matching energy
accumulators, gated on `len(ev_chargers) > 1`. The Sankey card then
gains a per-charger split.

### v1.6.16 — `FleetEvPower` newtype

The `# FLEET-READ:` AST lint catches the bug class but is, by
construction, a stopgap: a contributor can write
`# FLEET-READ: idk` and pass. v1.6.16 replaces
`PowerReadings.ev_power: float` with a `FleetEvPower` newtype
requiring explicit unwrap via `.as_fleet_total(reason: str)`. The
lint then enforces the unwrap call instead of a comment annotation —
structurally stronger.

See [`/home/sem/.claude/plans/greedy-whistling-nebula.md`](../../.claude/plans/greedy-whistling-nebula.md)
for the original plan.

---

## Tests that pin the invariant

- `tests/test_per_charger_context.py` — unit tests for the swap mechanism.
- `tests/scenarios/2026-05-29_multi_charger_split.yaml` — Phase B.5
  multi-charger budget distribution (RienduPre's Growatt + Wallbox setup).
- v1.6.8 will add `tests/test_ev_control_fleet_reads.py` — AST walk that
  fails CI if any `power.ev_power` read inside a per-charger loop is
  missing the `# FLEET-READ:` annotation.

---

## Adapters: the STATUS enum is authoritative over the power reading (#548)

The reconciler decides "is the charger still drawing?" from
`adapter.actual_charging(power)`. A power-based answer is wrong for any
charger whose power reading **lags the contactor** — every cloud-polled brand
(Wallbox ~90 s, Easee ~60 s, Zaptec ~60–600 s, Ohme ~30 s, go-e ~20 s, OCPP
~60 s meter cadence). A lagging-to-zero reading makes the reconciler read
OFF/IDLE as "already converged" on cycle 1 and stop re-issuing the stop while
the charger keeps charging (#548); a lagging-high reading does the reverse.

**One shared classifier, not a bespoke adapter per brand.** Brand entity
*naming* is user-dependent (most are HACS integrations), but SEM already has
each charger's status sensor — the user configures `ev_charging_sensor`, which
`__init__.py` plumbs to `device.charging_status_entity`. So the only
brand-specific knowledge is the status-string → control-class **map**. That
lives in **`coordinator/charger_adapters/status_enum.py`**
(`classify_charger_status`), and `GenericAdapter` consults it in
`actual_charging` + `enable_state`. Every brand benefits at once; KEBA and
Wallbox keep their dedicated adapters only for their *actuation* quirks (KEBA
`keba.disable`, Wallbox pause switch) and inherit the shared status logic.

Rules: **exact lower-cased whole-string match** (several brands have idle
states that *contain* "charging" — go-e `charging finished, vehicle still
connected`, Alfen `Wait Vehicle Charging`, Easee `stop_charging`); **unknown →
power fallback** (strictly additive); **no string collisions** across classes.

- `charging` → `actual_charging=True` even at lagging-0 W.
- `not_charging` → False even at lagging-high W.
- `locked` (app/cloud/schedule/auth controlled — Eco-Smart, Easee smart-start,
  Ohme `pending_approval`, Alfen In-operative) → False **and**
  `enable_state()=(None,False)` so the reconciler surfaces
  `REPORT_ENABLE_BLOCKED` instead of fighting a contactor it can't drive.

KEBA stays power-based for `actual_charging` (its `charging_state` binary lags
worse than power, #289). Tests: `tests/test_status_enum_brands.py` (per-brand
strings), `tests/test_548_mode_parity.py` (every mode actuates like KEBA),
`tests/test_charger_brand_coverage.py` (every control pattern triggers).

### Per-brand reference (verified against each HA integration source)

| Brand | Integration | Lag | Current control | Stop mechanism | Status entity / key | Notes |
|---|---|---|---|---|---|---|
| KEBA | core `keba` | low | `keba.set_current` (`current`) | `keba.disable` | binary `charging_state` (power-based) | dedicated adapter; 6 A min, self-resume, 110 W handshake |
| Wallbox | core `wallbox` | ~90 s cloud | `number.*_max_charging_current` | pause switch `switch.*_charging_enable` | `sensor.*_status` | dedicated adapter (pause switch); set-current-0 ≠ stop |
| Easee | HACS `nordicopen/easee_hass` | ~60 s cloud | `easee.set_charger_dynamic_limit` (`current`, **device_id**) | `easee.action_command` `pause`/`stop` | `sensor.*_status` | **set-current-0 ≠ stop**; smart-charge/auth = locked; power in **kW** |
| Zaptec | HACS `custom-components/zaptec` | 60–600 s cloud | `number.*_available_current` (0–max) | switch / `stop_charging_final` | `sensor.*_charger_mode` | command-validity gating; power in W |
| go-eCharger | HACS `cathiele/...goecharger` | ~20 s local | `goecharger.set_max_current` (`max_current`, 6–32) | `switch.*_allow_charging` (`alw`) | `sensor.*_car_status` | **set-current-0 ≠ stop** (clamps ≥6 A); power in **kW** |
| Ohme | core `ohme` | ~30 s cloud | **none — no amp control** | `select.*_charge_mode` (`paused`) | `sensor.*_status` | **on/off only, cannot amp-modulate**; force `max_charge`; `pending_approval` lock |
| OCPP | HACS `lbbrhzn/ocpp` | ~60 s local | `number.*_maximum_current` (needs SmartCharging profile) | `switch.*_charge_control` | `sensor.*_status_connector` | optimistic slider; power unit W **or** kW (auto-detect) |
| Alfen | HACS `leeyuentuen/alfen_wallbox` | low local | `alfen.set_current_limit` / `number.*_max_station_current` | `select.*_operation_mode` = In-operative | `sensor.*_status_code_socket_1` | max license-gated (16/40 A); power in W |
| Heidelberg | HACS `Schrolli91/heidelberg_energy_control` (modbus) | low local | `number.*_virtual_current` (6–16 A) | `switch.*_virtual_enable` (writes 0 A) | `sensor.*_charging_state` (letters A–F) | reg 261 not retained across reboot — re-assert; set-0 = pause (allowed) |

**Actuation caveats the user must configure** (SEM's config model supports
each; the status classifier is independent of these):
- **Easee / Zaptec / go-e:** lowering current to 0 does **not** stop — the
  user must set the stop service/switch (`ev_stop_service` / `ev_start_stop_entity`).
- **Ohme:** has **no per-amp control** — SEM can only force-on (`max_charge`)
  or pause via the charge-mode `select`. Surplus amp-following is not possible;
  treat as on/off.
- **Heidelberg:** register 261 reverts to 0 A after a charger reboot — SEM's
  per-cycle re-assert (reconciler heartbeat) covers this.

---

## See also

- [`MULTI_DEVICE_GUIDE.md`](MULTI_DEVICE_GUIDE.md) — end-user setup for
  multi-charger / multi-inverter installs.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — overall coordinator design.
- [`EV_CHARGING_LOGIC.md`](EV_CHARGING_LOGIC.md) — Charge mode + budget
  priority cascade.
