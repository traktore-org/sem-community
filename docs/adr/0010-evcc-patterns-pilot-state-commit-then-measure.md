# ADR 0010 — EV control trusts the EVSE pilot state machine and commits before measuring

**Status:** Proposed (2026-06-05) · informs issues #438, #439, and a new per-vehicle min-current issue

## Context

On 2026-06-05 we hit three EV-charging bugs in a single PROD session, all
filed the same day:

1. **#438** — a car whose handshake floor is 9 A oscillated at SEM's 6 A
   offer (cycling 4.24 / 1.57 / 0 kW); the `EVTaperDetector` saw the
   "peak > 3 kW declining to 0 W" pattern and anchored
   `_full_detected=True` after only 0.19 kWh of session energy. The car
   was then locked out of further charging until physical unplug.
2. **#439** — daytime `min_plus_solar` idled when solar was below the
   min-current floor and the home battery was available but not yet
   discharging. `battery_assist_budget_w` adds *currently-flowing*
   battery discharge to the budget, not *potential* — chicken-and-egg.
3. **min-current floor mis-config** — `number.sem_charger_ev_<id>_minimum_current`
   silently reset from 9 A to 6 A. With a per-car handshake floor of
   9 A, the 6 A offer never engaged. (Separate from #438 / #439 but
   the trigger for both.)

Looking at how [evcc](https://github.com/evcc-io/evcc) solves these
revealed that all three share a single architectural theme: SEM
*infers* lifecycle from power; evcc *trusts the EVSE state machine
and the meters* and only commits-then-measures.

## Decision

**EV control adopts three evcc patterns, in priority order:**

1. **Commit-then-measure for `min_plus_solar` budget.** Offer
   `effective_min_current` unconditionally; trust the next cycle's
   sensor readings to reflect the actual battery + grid split. Drop
   the "battery is currently discharging" gate in
   `battery_assist_budget_w`. Reference:
   [`evcc/core/loadpoint.go:1527`](https://github.com/evcc-io/evcc/blob/master/core/loadpoint.go#L1527) —
   `if (mode == ModeMinPV) && targetCurrent < minCurrent { return minCurrent }`.
   Fixes #439.

2. **Pilot-state-gated session lifecycle.** When the charger exposes
   a pilot state sensor (KEBA: `sensor.keba_p30_plug` /
   `binary_sensor.keba_p30_charging_state`), end-of-session is the
   C→B transition, not a power-heuristic on the BMS curve. The taper
   detector becomes a fallback for chargers without pilot state, AND
   gates `_full_detected` on a session-energy floor (≥ 1 kWh —
   anything smaller is below the noise floor for "full" claims).
   Reference:
   [`evcc/core/loadpoint.go:993-1002`](https://github.com/evcc-io/evcc/blob/master/core/loadpoint.go#L993). Fixes #438.

3. **Per-vehicle minimum current with three-way max.**
   `effective_min_current = max(loadpoint_min, charger_min, vehicle_min)`.
   Vehicle config gets a `min_current` field that survives migrations
   and config-flow round-trips, with the existing global setting as
   the default. Reference:
   [`evcc/core/loadpoint_effective.go:147-172`](https://github.com/evcc-io/evcc/blob/master/core/loadpoint_effective.go#L147)
   and the per-vehicle `ActionConfig` at
   [`evcc/api/actionconfig.go:14`](https://github.com/evcc-io/evcc/blob/master/api/actionconfig.go#L14).
   Fixes the silent-reset and gives users a place to record per-car
   handshake floors. A new issue will be filed for this; not in #438 or #439.

A fourth pattern — evcc's **Resurrector / WakeUp loop** (CP-interrupt
pilot cycle, 30 s × ≤ 6 attempts) — is a useful belt-and-braces fallback
but is *not* part of this ADR. It's recovery, not prevention; the three
patterns above eliminate the failure rather than recover from it. If
post-fix telemetry still shows car-side stalls, we'll reconsider.

## Consequences

**Good.** All three bugs become structural impossibilities, not
threshold-tuned heuristics. The mode-decision and session-lifecycle
code paths get *smaller*, not larger. The taper detector — the most
complex piece of EV logic in the codebase — moves from primary signal
to fallback. Per-vehicle config gives users an obvious place to record
hardware quirks they currently have nowhere to put.

**Bad / unknown.** The commit-then-measure pattern in `min_plus_solar`
will cause one cycle of grid import when the battery is slow to
respond — that's a real but acceptable cost; users opt into
`min_plus_solar` already expecting some grid usage. Pilot-state gating
depends on the charger integration exposing the C→B transition
reliably; KEBA does, but other chargers in the supported brand matrix
need verification before the fallback can be removed (see
[ADR 0005](0005-pipeline-test-per-brand.md)).

**Migration.** The pre-#438/#439 taper detector stays in place under
the new gate, so already-deployed users see no behavior change for
existing charge sessions. Per-vehicle `min_current` defaults to the
existing global value on first read, so existing configs are
unaffected until users edit them.

## Validation

Two failing TDD fixtures pin the bugs before the fix lands (commit
`a2ea596` on `test/438-439-bug-reproductions`):

- `tests/test_ev_taper_detector.py::TestFalseFullOnMinCurrentOscillation`
  — three xfail tests reproducing the #438 false-full anchor
- `tests/scenarios/2026-06-05_min_plus_solar_zone4_battery_chicken_egg.yaml`
  — xfail scenario reproducing the #439 budget gap

Each fix flips its corresponding xfail to a normal-passing test as
the structural change lands.
