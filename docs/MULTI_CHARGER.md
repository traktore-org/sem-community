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

## What the context manager owns

`coordinator/per_charger_context.py` ([source](../coordinator/per_charger_context.py)):

| Coordinator attribute | Role |
|---|---|
| `_ev_device` | The active charger's `EVDevice` instance |
| `_ev_stalled_since` | Per-charger stall detection state |
| `_ev_enable_surplus_since` | Per-charger enable-surplus timer |
| `_ev_charge_started_at` | Per-charger session start timestamp |
| `_ev_last_change_time` | Per-charger ramp-rate gate |
| `_ev_reenable_attempts` | Per-charger re-enable retry counter |
| `_ev_charge_refused` | Per-charger "charger refused" flag |
| `_current_charger_budget` | This charger's slice of `EVBudget.net_w` |
| `_cycle_vehicle_soc` | This charger's vehicle SOC (per `vehicle_soc_entity`) |
| `_current_pcc` | (v1.6.14) Pointer to the active `PerChargerContext` so `_this_charger_power` can return the cached `this_power_w` |

The corresponding `_per_charger` dicts (e.g.
`_ev_stalled_since_per_charger: Dict[str, datetime]`) are the **storage**;
the context manager pushes from them on `__enter__` and saves back on
`__exit__`.

---

## How to add a new per-charger field

1. Add it as a field on the `PerChargerContext` dataclass.
2. Add a `_<field>_per_charger: Dict[str, ...]` to `SEMCoordinator`.
3. Push/save in `__enter__`/`__exit__` — mirror the existing fields.
4. Add a unit test in `tests/test_per_charger_context.py` asserting:
   - In-context reads see this charger's value.
   - Mutations persist to the per-charger dict after exit.
   - Different chargers don't see each other's value.

That's it. **Don't** add a new `saved = {...}` dict in
`coordinator.py`; the loop body already wraps everything in a `with`
block.

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

## Adapters: prefer the STATUS enum over the power reading (#548)

**The road every brand-specific adapter should take.** The reconciler
decides "is the charger still drawing?" from `adapter.actual_charging(power)`.
The generic default is power-based (`power_w > handshake`), which is wrong for
any charger whose power reading **lags the contactor** — cloud-polled brands
(Wallbox ~90 s), or any integration where the power sensor updates slower than
SEM's cycle. A lagging-to-zero reading makes the reconciler read OFF/IDLE as
"already converged" on cycle 1 and stop re-issuing the stop while the charger
keeps charging (#548); a lagging-high reading does the reverse.

`WallboxAdapter` is the template (`coordinator/charger_adapters/wallbox.py`):
read the brand's **status enum** from `device.charging_status_entity` (plumbed
from the `ev_charging_sensor` config) and make it authoritative:

- `actual_charging` → True on the brand's charging states (even at lagging-0 W),
  False on idle/paused/locked states (even at lagging-high W), and **fall back
  to the generic power heuristic** on unknown/error/unconfigured (strictly
  additive — no status sensor ⇒ unchanged behaviour).
- `enable_state()` → return `(None, False)` (uncontrollable) when the status
  reports an **app/cloud-controlled lock** (Eco-Smart / Scheduled / queued /
  Locked) so the reconciler surfaces `REPORT_ENABLE_BLOCKED` instead of
  spinning a futile stop.

This is the evcc "connector" concept adapted to SEM (we read HA's status
sensor; evcc reads it over OCPP/cloud). **Brands to migrate next** as their
status sensors are confirmed: Easee (`status`), go-eCharger (`car`), OCPP
(`status_connector`), Ohme, Alfen, Wallbox-family clones. KEBA stays
power-based (its `charging_state` binary lags worse than power, #289). Each
migration needs the brand's exact status strings + a parity test like
`tests/test_548_mode_parity.py` (every mode's intent actuates the same as KEBA).

---

## See also

- [`MULTI_DEVICE_GUIDE.md`](MULTI_DEVICE_GUIDE.md) — end-user setup for
  multi-charger / multi-inverter installs.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — overall coordinator design.
- [`EV_CHARGING_LOGIC.md`](EV_CHARGING_LOGIC.md) — Charge mode + budget
  priority cascade.
