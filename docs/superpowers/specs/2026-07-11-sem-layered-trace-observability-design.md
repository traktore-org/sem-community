# SEM Layered Trace / Observability Arc — Design Spec

**Status:** Approved design (brainstormed with Guido 2026-07-11) — build target 1.7.5/1.8.0, sequenced **after HA-TEST isolation, before #576**.
**Motivation:** the 2026-07-10 EV flap took ~5 hours to root-cause because "what is SEM deciding vs commanding vs observing" is scattered across three places that don't link. See [[project_ev_flap_udp_blip]], [[feedback_diagnose_before_touching_live]].

---

## 1. Problem

SEM already has three implicit layers, but each emits status in a *different place* and none link to each other, so following one decision end-to-end means archaeology across modules and raw hardware sensors. The EV flap is the canonical case: the process-layer `reason` said "charge 16 A", but there was no coherent view showing that the **integration layer commanded 16 A while the observed power was 0 W** — the mismatch that localises the bug. We inferred it from raw KEBA power over hours.

**Goal:** make the three layers explicit and observable as one linked, per-cycle **trace**, so any "why is SEM doing X / not doing Y?" is answered top-down in one lookup — and so layer-*boundary* bugs (the whole flap class) are caught automatically.

**Non-goal:** restructuring the control logic. This is an **observability layer over** the existing, battle-tested `decide` / `stability` / `reconciler` code. No behaviour change.

## 2. The three layers (Guido's model → SEM modules)

| Layer | Responsibility ("…") | SEM modules | Status emitted today |
|---|---|---|---|
| **Management** | prios, timeline, sun, tariff, goals, forecast — *what should happen* | `utils/time_manager` (sun/night), `coordinator/tariff_provider`, `coordinator/ev_tariff_planner`, `coordinator/battery_charge_scheduler`, `features/device_registry` (priorities), `coordinator/forecast_reader`, mode selects | scattered: mode select, zone, tariff-level, forecast sensors |
| **Process** | decide + cross-check — *what to do & why* | `coordinator/decide.py` (`ChargerDecision`+`reason`), `coordinator/charge_stability.py`, `coordinator/surplus_controller.py`, `coordinator/decide_battery.py`, `coordinator/flow_calculator.py` | partial: the `reason` strings (`charging_strategy_reason`, `battery_scheduler_reason`) |
| **Integration** | control devices, write data, observe — *act & confirm* | `coordinator/charger_reconciler.py` + `coordinator/charger_adapters/*`, `devices/*`, `sensor.py` (writes), `coordinator/sensor_reader.py` (reads) | fragmented: reconciler actions, #548 "actuation truth", adapter `last_intent` |

The layering exists; the **link between layers, and a status vocabulary shared across them, do not.**

## 3. The trace record

One `CycleTrace` per coordinator cycle, holding one `SubsystemTrace` per controlled subsystem (`ev` per charger, `battery`, `loads`, `heat_pump`, `hot_water`). Each subsystem carries the three-layer chain:

```
CycleTrace
  seq: int                 # monotonically increasing cycle counter
  wall_iso: str            # timestamp (stamped by coordinator, not in pure code)
  subsystems: dict[str, SubsystemTrace]

SubsystemTrace
  management: LayerRecord   # what policy wants
  process:    LayerRecord   # what SEM decided + why
  integration:LayerRecord   # what SEM commanded + what it observed

LayerRecord
  status:  LayerStatus      # see §4
  detail:  str              # human one-liner (the existing `reason` fits here)
  data:    dict             # the few key numbers for THIS layer (small, flat)
```

Per-layer `data` (kept SMALL — the numbers that explain the decision, not a dump):
- **management.data:** `mode, soc_zone, sun_up, tariff_level, target_kwh, priority, night`
- **process.data:** `intent, commanded_amps|watts, budget_w, surplus_w, min_w`
- **integration.data:** `action, params, command_ok, observed_w, observed_state, match`

`integration.match` (bool|null) is the linchpin: *did the observed reality match what we commanded?* `false` = a layer-boundary fault (the flap).

## 4. Status vocabulary (shared across all three layers)

```
ok        — layer did its job, nothing notable
idle      — deliberately not acting (e.g. surplus < min, EV disconnected)
blocked   — cannot act; detail says why (below reserve, not-cheap window, enable-switch locked)
degraded  — acting on stale/partial input (sensor unavailable, held last-good)
error     — an exception/command failure; detail carries it
```

This is what makes "why isn't SEM charging?" answerable top-down:
`management: blocked (battery below reserve)` → done. Or `management: ok · process: idle (surplus 2.3k < min 5.5k)` → done. Or `process: ok (charge 16A) · integration: degraded (observed 0W, mismatch 3 cycles)` → look at the charger link.

## 5. Exposure (diagnostic — NEVER a recorder row)

We just fixed the recorder bloat (#581); the trace must not re-introduce it. Three surfaces, all recorder-safe:

1. **`diagnose` service (primary).** Extend the existing diagnostics dump with `recent_traces`: the last **N cycles** (ring buffer, default 30) of `CycleTrace`. On-demand, zero recorder impact. This is the "pull the last 30 cycles and read the chain" tool.
2. **Debug log toggle.** A config/service flag `debug_trace` that, while on, logs each cycle's compact trace at INFO for live `tail -f` during an incident. Off by default.
3. **Self-diagnosing health signal (the automatic win).** A `binary_sensor.sem_layer_mismatch` (+ a `sensor.sem_health` summary) that flips **on** when any subsystem shows a persistent layer-boundary fault — e.g. `process=CHARGE` but `integration.match=false` for ≥ K cycles, or `integration.status=error`. This would have *alerted on the flap immediately* instead of us discovering it by eye. Attributes are `_unrecorded_attributes`; only the binary state (rare changes) records.

## 6. Design principles (hard constraints)

1. **Observe, don't restructure.** The trace is *assembled by the coordinator* from values the layers already compute each cycle (decisions, `reason`s, reconciler actions, observed power). It threads nothing new through `decide`/`stability`/`reconciler`. No control-path behaviour changes — pinned by a "decisions identical with tracing on/off" test.
2. **Diagnostic, not recorded.** Ring buffer in memory + `diagnose` dump + `_unrecorded_attributes`. Never a per-cycle recorded state row (#581).
3. **Small, flat `data`.** A handful of numbers per layer, not a payload dump — keeps it readable and cheap.
4. **Resist framework-itis.** Three dataclasses + a ring buffer + a collector in the coordinator. No plugin system, no per-module registration ceremony.

## 7. Architecture — where the trace is filled

The coordinator already computes, each cycle: the fleet/management state, the per-charger `ChargerDecision` (+reason), the reconciler actions, and the observed power. The trace is a **collector** that captures those at the points they already exist:

- `coordinator/cycle_trace.py` (**new**): `CycleTrace`, `SubsystemTrace`, `LayerRecord`, `LayerStatus`, and a `TraceCollector` holding the ring buffer (`deque(maxlen=30)`).
- In `_async_update_data`: `trace = self._trace.begin(seq)` at cycle top; the management/process/integration values already computed are written via `trace.ev(cid).management(...)`, `.process(decision)`, `.integration(action, result, observed)`.
- Most writes are **one line each** next to where the value is already produced (e.g. right after `decide()` returns, right after `reconcile_and_apply`).
- `features/*` diagnose service reads `self._trace.recent()`.

Invasiveness budget: ~1 new file + ~1 line per capture point (≈ a dozen) + the diagnose extension + the health sensor. No edits inside `decide.py`/`charge_stability.py`/`charger_reconciler.py` logic — only the coordinator reads their outputs.

## 8. Worked example — the flap, traced

```
seq 4412  ev[keba]
  management  ok       mode=min_plus_solar zone=4 sun=up tariff=normal target=…
  process     ok       CHARGE @16A   budget=11293W (surplus=6345 + assist=4948)
  integration DEGRADED action=set_current(16A) command_ok=true observed=0W match=FALSE
seq 4413  ev[keba]
  process     idle     budget=0W below 8A min          ← surplus crashed (the ev-lag)
  integration ok       action=DISABLE observed=0W match=true
```
Two cycles of `diagnose` output and the story is complete: process flips CHARGE↔idle because budget collapses, integration faithfully disables — **and `sensor.sem_layer_mismatch` would have been on since seq 4412.** Minutes, not hours.

## 9. Build phases

- **Phase 1 — the trace + `diagnose` dump.** `cycle_trace.py`, the collector, the ~dozen capture lines, `recent_traces` in `diagnose`. Delivers the manual "pull last 30 cycles" tool. Low risk, immediately useful.
- **Phase 2 — the health signal.** `binary_sensor.sem_layer_mismatch` + `sensor.sem_health` (top-down status roll-up). The automatic "SEM tells you when a layer disagrees" win.
- **Phase 3 — debug-log toggle** + docs (a "how to read a SEM trace" section in the troubleshooting guide).

Each phase is shippable alone; Phase 1 is the bulk of the value.

## 10. Testing

- **Behaviour-invariance:** decisions/commands byte-identical with tracing on vs off (the control path must not move).
- **Collector:** ring buffer caps at N; a synthetic cycle produces a well-formed `CycleTrace` with the three layers populated.
- **Health signal:** a scripted process=CHARGE / observed=0 sequence flips `sem_layer_mismatch` after K cycles and clears on recovery; a normal charge never trips it.
- **Recorder safety:** the trace attributes are in `_unrecorded_attributes`; a test asserts no per-cycle trace row hits the recorder (guards #581).
- **The flap as a fixture:** feed the beta.35 flap sequence and assert the trace shows the `process idle ↔ integration disable` pattern + the mismatch flag — turning this week's incident into a permanent regression narrative.

## 11. Risks & out of scope

- **R1 — surface creep.** Mitigation: the four principles in §6; keep it three dataclasses + a collector.
- **R2 — recorder regression.** Mitigation: `_unrecorded_attributes` + the §10 recorder-safety test.
- **Out of scope:** changing any control logic; a UI/dashboard trace viewer (the `diagnose` dump is enough for v1); tracing non-controlled read-only sensors.

## 12. Why now

The flap cost 5 hours precisely because this didn't exist. #576 is a large control change landing next — we will *want* the per-layer trace to verify it safely on the (soon-isolated) HA-TEST rig. Sequencing: **HA-TEST isolation → this trace → #576.**
