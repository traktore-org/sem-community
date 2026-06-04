# ADR 0009 — Multi-charger EV power distribution is a priority cascade with 60-second reallocation hysteresis

**Status:** Accepted (v1.4.0, refined v1.6.0+) · depends on [ADR 0002](0002-ev-budget-unified.md)

## Context

[ADR 0002](0002-ev-budget-unified.md) makes `EVBudget` the canonical
single-cycle EV power decision. SEM has supported multiple EV
chargers per install since v1.4.0; when more than one charger is
configured, the fleet-level budget needs to be split across them.

Three things the split has to get right:

1. **Determinism** — the same fleet budget + the same charger config
   must produce the same per-charger allocation. Otherwise the
   per-charger dashboard sensors and the actuator commands drift
   out of sync.
2. **No oscillation** — a small budget jitter (a passing cloud, a
   100 W sensor wobble) must not bounce the allocation across
   chargers every cycle, because the chargers' own minimum-amps
   floors mean reallocating costs charging time.
3. **Mode-disabled chargers stay visible** — a charger in
   `charge_mode=off` must NOT consume any of the budget cascade, but
   it MUST still appear in the per-charger dashboard sensors with
   `0 W` so the dashboard doesn't look broken.

## Decision

**A priority cascade allocates a fleet watts budget to per-charger
watts, with 60-second hysteresis on reallocation.**

Implemented in `coordinator/surplus_controller.py:distribute_ev_budget`
(line 132). The shape:

- Chargers are sorted by `priority` (lower number = higher priority,
  from the config flow).
- Highest priority gets up to its max; the remainder cascades to the
  next charger if it can meet its minimum-amps threshold.
- Reallocation is suppressed for 60 s after the last change UNLESS
  the fleet budget moves by more than 500 W (the threshold that
  signals a real demand change vs sensor noise).
- Chargers in `excluded_charger_ids` (today: `charge_mode=off` per
  #351 M5) receive `0` in the output dict but are skipped in the
  cascade. The output keying every configured charger keeps the
  dashboard sensors accurate.

The distributor returns `Dict[charger_id, watts]`, NOT
`Dict[charger_id, EVBudget]`. The per-charger `PerChargerContext`
(see [ADR 0001](0001-per-charger-context.md)) wraps the watts value
with the per-charger state at consumption time.

## Consequences

**Good.** Per-charger dashboard sensors match what each actuator
commands. Multi-charger installs are deterministic for a given config
order. Cloud-driven budget jitter doesn't oscillate the allocation.
The mode-disabled gate (#351 M5) means a charger turned off in the
options flow visibly stays off without breaking the dashboard.

**Open.**

- The distributor consumes raw watts, not `EVBudget`. A future change
  could make it accept the canonical `EVBudget` and produce per-charger
  `EVBudget` slices — which would let intent, amps, and watts flow
  through the distribution layer in a single typed value instead of
  three. Not in scope today; tracking for v1.8.
- Priority is fixed at config-order. Alternative allocation policies
  (round-robin, proportional-to-SOC, deadline-aware) would land as
  new distributor implementations, not as schema changes.
- 60 s hysteresis + 500 W threshold are constants. If a fleet ever
  hits a regime where these are wrong, they become config.

See `coordinator/surplus_controller.py:distribute_ev_budget` for the
allocator and `coordinator/per_charger_context.py` for the per-charger
view's lifecycle.
