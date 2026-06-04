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

- [0001 — PerChargerContext per-charger swap surface](0001-per-charger-context.md)
- [0002 — EVBudget unified across publish path, state machine, actuator](0002-ev-budget-unified.md)
- [0003 — Sign convention boundary at sensor_reader](0003-sign-convention-boundary.md)
- [0004 — home_consumption_power is clamped to zero](0004-home-consumption-clamp.md)
- [0005 — Pipeline test per supported brand is mandatory](0005-pipeline-test-per-brand.md)
