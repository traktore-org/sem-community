# ADR 0001 — PerChargerContext owns the per-charger swap surface

**Status:** Accepted (v1.6.7) · ratifies `coordinator/per_charger_context.py`

## Context

Between v1.6.0 and v1.6.6 SEM shipped four hotfixes for the same bug
class: per-charger code paths reading the fleet-summed `power.ev_power`
instead of the current charger's draw. Issues `#284`, `#285`, `#287`,
`#291` were each one instance of the same shape — a parallel `saved =
{...}` dict capturing per-charger state, missing one or two fields each
time, and a `power.ev_power` read that should have been per-charger.

The class of bug was structural — not a single missed call site, but a
recurring pattern that the existing abstraction failed to prevent.

## Decision

**`PerChargerContext` is the single owner of the per-charger swap
surface.**

- All per-charger state that's swapped in/out across the loop body
  lives on `PerChargerContext`, not in parallel dicts.
- `self._this_charger_power(ev, power)` is the only sanctioned way to
  read this charger's draw inside the per-charger loop body. The
  result is cached as `this_power_w` at method top.
- `# FLEET-READ: <reason>` is the opt-out annotation. The AST lint at
  `tests/test_ev_control_fleet_reads.py` fails CI on any unannotated
  `power.ev_power` read in `coordinator/ev_control.py`.

## Consequences

**Good.** The class is closed structurally rather than reactively.
New per-charger fields go on `PerChargerContext`; reviewers don't have
to remember to update parallel dicts. The AST lint is a permanent
fitness function — adding a new fleet read without justifying it costs
zero ongoing attention; the test catches it.

**Open.** `effective_state` and `this_power_w` are still local
variables / parallel dicts rather than fields on `PerChargerContext`.
The lint is a stopgap; a `FleetEvPower` newtype would be structurally
stronger but bigger refactor. Tracked for v1.7+.

See [`docs/MULTI_CHARGER.md`](../MULTI_CHARGER.md) for the operational
playbook.
