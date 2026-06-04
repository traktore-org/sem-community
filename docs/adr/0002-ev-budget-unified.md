# ADR 0002 — EVBudget is the single source of truth across publish, state machine, actuator, and multi-charger distribution

**Status:** Accepted (v1.6.0)

## Context

Pre-v1.6, EV budgeting was computed independently in three places:

1. The publish path that exposed `sensor.sem_ev_budget`
2. The state machine that decided which mode to be in
3. The actuator that translated mode → amps for the charger

Plus a fourth, layered on top in multi-charger configs: a distribution
step that split the global budget across chargers by priority. Each
path had its own slightly different rounding, clamping, and minimum-
amps handling. When the four diverged — as they always did — the
sensor on the dashboard didn't match what the actuator commanded, the
state machine flipped between modes the user didn't trigger, and
multi-charger installs got unpredictable splits.

## Decision

**Canonical `EVBudget` dataclass is the single source of truth across
all four paths.**

Defined in `coordinator/ev_budget.py`. Computed once per coordinator
cycle, consumed by:

- the publish path (sensor reports exactly what's in the dataclass)
- the state machine (modes branch off `EVBudget.intent`, not their own
  recompute)
- the actuator (amps come from `EVBudget.amps`, no second rounding)
- the multi-charger distributor (operates on the same `EVBudget`,
  produces per-charger `EVBudget` slices that follow the same shape)

## Consequences

**Good.** The dashboard's `sensor.sem_ev_budget` is by construction
what the actuator will command. Mode transitions are deterministic
from the dataclass. Multi-charger splits compose cleanly because the
per-charger budget is the same type as the global one.

**Open.** Phase D.2 cleanup (legacy `_calculate_ev_budget` method
removal, demotion-guard removal) deferred to v1.7.0 after sustained
soak — completed in v1.6.2 (PR #282). The unification phases
A + B + B.5 + C + D.1 shipped in v1.6.0.

See `coordinator/ev_budget.py` for the dataclass shape and helper
predicates.
