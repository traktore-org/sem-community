# ADR 0008 — FleetEvPower newtype as type-system enforcement of fleet-vs-per-charger reads

**Status:** Accepted (v1.6.16) · ratifies `coordinator/types.py:FleetEvPower`

## Context

ADR 0001 closed the per-charger context swap surface structurally
(`PerChargerContext`) and added an AST lint scoped to `ev_control.py`. That lint
caught unannotated `power.ev_power` reads in the per-charger loop body but had
two gaps: it was scoped to one file, and it was comment-based (`# FLEET-READ:`),
so the annotation was invisible to type checkers, IDEs, and `ast.dump`.

Issues `#284`, `#289`, `#315`, and `#318` were each a different file repeating
the same shape — code inside a per-charger context reading the fleet-summed
`PowerReadings.ev_power` without acknowledging it. The v1.6.8 lint was
file-scoped; the rest of `coordinator/` was unguarded.

## Decision

**`FleetEvPower` is a `float` subclass (not a `typing.NewType`, not a `TypeVar`)
that wraps `PowerReadings.ev_power`.**

- Subclassing `float` means every existing arithmetic and comparison expression
  that reads `ev_power` continues to work without migration — the type is a
  transparent wrapper at runtime.
- The `.as_fleet_total(reason: str)` accessor returns the underlying watts and
  takes a mandatory `reason` argument. The argument has no runtime effect but
  documents intent at the call site in a form that appears in code review,
  `git blame`, `ast.dump`, and IDE hover — stronger than a comment.
- The expanded AST lint (`tests/test_fleet_ev_power_reads_global.py`) treats
  `.as_fleet_total(...)` as equivalent to the `# FLEET-READ:` comment and
  accepts either. Unannotated bare reads of `ev_power` in any module under
  `coordinator/` fail CI.

`typing.NewType` was rejected: it aliases at the type-checker level but is
transparent at runtime, so arithmetic on a `NewType` alias produces a plain
`float` — meaning the next assignment would silently lose the newtype. Subclassing
preserves the type through arithmetic because Python's `float.__add__` returns a
`float`, not the subclass, but the wrapper is re-applied at the one construction
site (`sensor_reader`), which is where enforcement is needed.

Shipped in v1.6.16 (commit `30317b6`, PR `#332`).

## Consequences

**Good.** The fleet-vs-per-charger read bug class is now statically enforceable
across all of `coordinator/`, not just `ev_control.py`. New files automatically
inherit the coverage without opt-in. The `.as_fleet_total()` method appears in
any language-server hover, making the intent explicit to future contributors.

**Open.** As noted in `coordinator/charger_types.py:FleetView`, the `FleetView`
aggregate type (introduced post-v1.6.16) now centralises fleet reads for the
actuator, reducing the number of legitimate `as_fleet_total()` call sites.
When the actuator migration is complete, the newtype's primary remaining role
is the energy-balance equation in `PowerReadings.calculate_derived`. Track for
v1.8: whether the lint and newtype can be simplified once call-site count drops.

See `coordinator/types.py:34` for the class definition and
`tests/test_fleet_ev_power_reads_global.py` for the fitness function.
