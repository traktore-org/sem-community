# ADR 0006 — FleetCycleState is the single source of truth for fleet-level coordinator inputs

**Status:** Accepted (v1.7.0-beta.7) · ratifies `coordinator/charger_types.py:FleetCycleState`

## Context

Post-v1.6.7 the per-charger swap surface was closed by `PerChargerContext` (ADR
0001). A symmetric plumbing problem remained on the fleet side: call sites for
`build_charger_view` each passed fleet-level inputs as direct kwargs — `tariff_level`,
`forecast_remaining_kwh`, night-plan signals, and similar. There was no structural
guarantee that every call site passed the same fleet inputs, so a caller could
silently omit a kwarg that a later `decide()` relied on. Issue `#358` surfaced the
resulting asymmetry: some chargers in a multi-charger cycle saw a tariff level;
others saw `None` from a call site that predated the tariff feature.

## Decision

**Fleet-level cycle inputs are collected once per cycle into a `FleetCycleState`
object and passed as a single positional argument to every `build_charger_view`
call.**

- `FleetCycleState` is a frozen dataclass — immutable for the cycle's lifetime.
- Both the primary view (constructed inside `coordinator._build_charging_context`)
  and the multi-charger loop's per-charger views derive from the SAME
  `FleetCycleState` object.
- Per-charger overrides (`target_kwh`, `deadline_amps`, `tariff_wait`,
  `solar_committed_w`) stay as direct kwargs — they legitimately differ across
  chargers within the same cycle and are not fleet state.
- When a new fleet input is needed, it lands as a field on `FleetCycleState`.
- The AST lint at `tests/test_fleet_state_completeness.py` fails CI if any
  `build_charger_view` call site bypasses `FleetCycleState` and passes a
  fleet-level field as a direct kwarg. This is the fleet-side mirror of the
  `FLEET-READ` annotation lint from ADR 0001.

Shipped in v1.7.0-beta.7 (commit `44d28a8`).

## Consequences

**Good.** The plumbing-asymmetry class is closed structurally: every charger in
the cycle is guaranteed to receive identical fleet state. Adding a new fleet
input requires one field on `FleetCycleState`; the AST lint enforces it
everywhere without manual audit. The per-charger and fleet sides of the loop now
have symmetric structural guards (ADR 0001 for per-charger, this ADR for fleet).

**Open.** The test at `tests/test_fleet_state_completeness.py` identifies
forbidden kwargs by a static allowlist; if a kwarg is misclassified as
per-charger when it should be fleet state, the lint won't catch it. Review the
allowlist when adding a new kwarg to `build_charger_view`.

See `coordinator/charger_types.py:FleetCycleState` (line 541) and
`coordinator/_build_fleet_cycle_state` for construction.
