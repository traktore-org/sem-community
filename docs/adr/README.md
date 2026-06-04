# Architecture Decision Records

ADRs document _why_ SEM is built the way it is — for decisions that aren't
obvious from reading the code, and that we'd lose if context goes cold.

We use the [lightweight Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):
**Context → Decision → Status → Consequences**, one page max.

## When to write an ADR

Write one when crossing a real complexity threshold:

- A new device class or platform pattern
- A new sign-convention or data-flow invariant
- A protocol / API surface change with backward-compat implications
- A new architectural fitness function (AST lint, import-linter rule)
- A significant refactor that reshapes a subsystem

**Don't** write one for routine bugfixes, dependency bumps, or feature
work that fits the existing patterns. ADRs are for _decisions_, not
_changes_.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-per-charger-context.md) | PerChargerContext per-charger swap surface | Accepted |
| [0002](0002-ev-budget-unified.md) | EVBudget unified across publish path, state machine, actuator | Accepted |
| [0003](0003-sign-convention-boundary.md) | Sign convention boundary at sensor_reader | Accepted |
| [0004](0004-home-consumption-clamp.md) | home_consumption_power is clamped to zero | Accepted |
| [0005](0005-pipeline-test-per-brand.md) | Pipeline test per supported brand is mandatory | Accepted |
| [0006](0006-fleet-cycle-state.md) | FleetCycleState as single source of truth for fleet-level coordinator inputs | Accepted |
| [0007](0007-real-hass-test-framework.md) | Real-hass test framework adoption and test-layer choice rule | Accepted |
| [0008](0008-fleet-ev-power-newtype.md) | FleetEvPower newtype as type-system enforcement of fleet-vs-per-charger reads | Accepted |
| [0009](0009-ev-budget-multi-charger-distribution.md) | Multi-charger EV power distribution is a priority cascade with 60 s hysteresis | Accepted |
