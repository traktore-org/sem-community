# Reading a SEM Trace (debugging with the layered trace)

*Added in 1.7.5. Design: `docs/superpowers/specs/2026-07-11-sem-layered-trace-observability-design.md`.*

SEM records, every control cycle, the **three-layer chain** for each subsystem
(EV, battery). When something misbehaves, this answers "what is SEM doing and
**why**?" in one lookup instead of piecing it together from raw sensors.

## The three layers

| Layer | Answers | Example |
|---|---|---|
| **management** | *What should happen?* — policy inputs | `soc=100 connected=true night=false` |
| **process** | *What did SEM decide, and why?* | `ok · "min_plus_solar Zone 4 → 16A" · budget_w=11000` |
| **integration** | *What did it command, and what happened?* | `degraded · commanded 16A · observed 0W · match=false` |

Each layer has a **status**: `ok` (acting) · `idle` (deliberately not acting) ·
`blocked` (can't act — detail says why) · `degraded` (acting on stale/partial
input) · `error` (a failure).

## How to pull it

Call the `solar_energy_management.diagnose` service with `section: trace`
(Developer Tools → Actions):

```yaml
action: solar_energy_management.diagnose
data:
  section: trace
```

The response's `payload.trace` has:
- **`health`** — `{ok: true}` normally; `{ok: false, subsystem, cycles}` when a
  layer boundary has disagreed for ≥ 3 consecutive cycles.
- **`mismatch`** — the current layer-boundary fault, if any.
- **`recent`** — the last 30 cycles of the full chain (newest last).

**From the dashboard:** the **Diagnose** buttons carry this too — every section's
output includes a `trace_health` summary (is any layer disagreeing?), and the
**EV** Diagnose button includes the full `trace` (the 30-cycle chain). So you can
answer "why is the charger doing this?" straight from the EV Diagnose button
without calling the service by hand.

## Reading a mismatch (the EV-flap example)

```
seq 4412  ev
  management  ok        soc=100 connected=true night=false
  process     ok        "min_plus_solar Zone 4 → 16A"   budget_w=11000
  integration degraded  commanded 16A  observed 0W  match=FALSE   ← the fault
```

The story is immediate: **process wanted 16 A, integration commanded it, but the
car drew 0 W** — the bug is at the integration/observation boundary (a dropped
session / a laggy charger reading), not in the decision. If the next cycle shows
`process: idle "budget=0W below 8A min"`, you can see the budget collapsed and
SEM correctly idled — pointing upstream at the surplus/measurement input.

The **`match` field** is the linchpin: `true` = observed matches the command,
`false` = a layer-boundary fault, `null` = not applicable (idle / disconnected).

## Guarantees

- **Read-only.** The trace only *reads* values SEM already computed; it can never
  change a decision.
- **Recorder-safe.** In-memory ring buffer + on-demand dump only — it is never
  written to the HA recorder database (respects the 1.7.4 recorder fix).
