# ADR 0002 — EVBudget is the single source of truth across publish, state machine, and actuator

**Status:** Accepted (v1.6.0)

## Context

Pre-v1.6, EV budgeting was computed independently in three places:

1. The publish path that exposed `sensor.sem_ev_budget`
2. The state machine that decided which mode to be in
3. The actuator that translated mode → amps for the charger

Each path had its own slightly different rounding, clamping, and
minimum-amps handling. When they diverged — as they always did — the
sensor on the dashboard didn't match what the actuator commanded, and
the state machine flipped between modes the user didn't trigger.

## Decision

**Canonical `EVBudget` dataclass is the single source of truth across
all three paths.**

Defined in `coordinator/flow_calculator.py` (line 95). Computed once per coordinator
cycle, consumed by:

- the publish path (sensor reports exactly what's in the dataclass)
- the state machine (modes branch off `EVBudget.intent`, not their own
  recompute)
- the actuator (amps come from `EVBudget.amps`, no second rounding)

Multi-charger power allocation is a separate decision — see
[ADR 0009](0009-ev-budget-multi-charger-distribution.md). Today the
distributor operates on raw watts, not on `EVBudget` instances; a
future unification could make it produce per-charger `EVBudget`
slices, but that change is intentionally not in scope of this ADR.

## Consequences

**Good.** The dashboard's `sensor.sem_ev_budget` is by construction
what the actuator will command. Mode transitions are deterministic
from the dataclass.

**Open.** Phase D.2 cleanup (legacy `_calculate_ev_budget` method
removal, demotion-guard removal) deferred to v1.7.0 after sustained
soak — completed in v1.6.2 (PR #282). The unification phases
A + B + B.5 + C + D.1 shipped in v1.6.0.

See `coordinator/flow_calculator.py` for the dataclass shape and helper
predicates.
