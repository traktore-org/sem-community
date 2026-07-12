# Reading a SEM Trace (debugging with the layered trace)

*Added in 1.7.5. Design: `docs/superpowers/specs/2026-07-11-sem-layered-trace-observability-design.md`.*

SEM records, every control cycle, the **three-layer chain** for each subsystem
— the **EV** charger(s), the **battery**, each **surplus load** (`load:<name>`),
and the **heat pump**. When something misbehaves, this answers "what is SEM doing
and **why**?" in one lookup instead of piecing it together from raw sensors.

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

Each subsystem defines `match` in terms of the reality that matters for *it*, so
a legitimate zero never reads as a fault:

| Subsystem | `match` is False when… | `null` (not checked) when… |
|---|---|---|
| **EV** | commanded amps > 0 but observed draw < 30 % of it | not charging / car unplugged |
| **battery** | `force_charge` but not charging (or `force_discharge` but not discharging) | no explicit command (normal / idle) |
| **heat pump** | boost commanded but the SG-Ready relay didn't reach BOOST/FORCE_ON | not boosting |
| **load** (`load:<name>`) | SEM turned it on but the **relay** is still off | SEM isn't driving it, or it's unobservable |

The load check reads the **relay / mode**, not power — a thermostat-satisfied
heater is legitimately *on at 0 W* and must not alarm. The battery check ignores
the ramp: a freshly-commanded charge reads False for a cycle or two while the
inverter spins up, and the health debounce (≥ 3 consecutive cycles) absorbs it.

## Guarantees

- **Read-only.** The trace only *reads* values SEM already computed; it can never
  change a decision.
- **Recorder-safe.** In-memory ring buffer + on-demand dump only — it is never
  written to the HA recorder database (respects the 1.7.4 recorder fix).
