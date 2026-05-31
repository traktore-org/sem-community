# Multi-Charger Correctness — Developer Guide

This document is the source of truth for **developers** working on SEM's
multi-charger code paths. For end-user setup with multiple chargers, see
[`MULTI_DEVICE_GUIDE.md`](MULTI_DEVICE_GUIDE.md).

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

> **Inside a `with PerChargerContext.for_charger(...)` block, never read
> `power.ev_power` directly. Use `pcc.this_power_w` (added in v1.6.8) or
> tag the read explicitly with `# FLEET-READ: <reason>`.**

Likewise: never read `self._ev_*` directly; the context owns them and
they reflect THIS charger only during the block. Reading them from
outside the block returns the primary charger's view (the legacy
"fleet" semantic for backward compat).

To add a new per-charger field, edit `PerChargerContext` only —
don't add new ad-hoc swap dicts.

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

## Roadmap (v1.6.x cleanup)

| Release | Theme | Status |
|---|---|---|
| v1.6.7 | Lift swap dict into `PerChargerContext` | **In progress** |
| v1.6.8 | Per-charger strategy + `ev_control.py` fleet-read sweep + AST lint test | Planned |
| v1.6.9 | Per-charger flow attribution + notifications (closes #316 family) | Planned |
| v1.7 | New features — **only after** v1.6.9 lands clean on PROD | Blocked on above |

See [`/home/sem/.claude/plans/greedy-whistling-nebula.md`](../../.claude/plans/greedy-whistling-nebula.md)
for the full plan.

---

## Tests that pin the invariant

- `tests/test_per_charger_context.py` — unit tests for the swap mechanism.
- `tests/scenarios/2026-05-29_multi_charger_split.yaml` — Phase B.5
  multi-charger budget distribution (RienduPre's Growatt + Wallbox setup).
- v1.6.8 will add `tests/test_ev_control_fleet_reads.py` — AST walk that
  fails CI if any `power.ev_power` read inside a per-charger loop is
  missing the `# FLEET-READ:` annotation.

---

## See also

- [`MULTI_DEVICE_GUIDE.md`](MULTI_DEVICE_GUIDE.md) — end-user setup for
  multi-charger / multi-inverter installs.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — overall coordinator design.
- [`EV_CHARGING_LOGIC.md`](EV_CHARGING_LOGIC.md) — Charge mode + budget
  priority cascade.
