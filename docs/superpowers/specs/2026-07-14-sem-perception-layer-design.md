# SEM Perception Layer — Trace Integration & Sign/Balance Integrity — Design Spec

**Status:** Proposed design (grounded 2026-07-14, from the #589 reliability-arc discussion with Guido). Build target 1.8.0. **Sequenced after** the SignDetector/CounterAudit dedup (see §9) — that dedup is a clean prerequisite that halves the surface this spec plugs into.
**Motivation:** the layered trace (2026-07-11 spec) validates the *control* chain (Management → Process → Integration) but assumes its *inputs* are trustworthy. It structurally **cannot catch a sign error**: flip the battery sign and all three layers cohere on the wrong-signed input — every `layer_match` is green while the whole cycle is wrong. Separately, the #589 sign-contradiction audit hand-rolled its **own** debounce→flag→sensor mechanism, duplicating the trace's `streak → health → binary_sensor.sem_layer_mismatch` engine. This spec closes both: it adds the missing foundation layer and retires the duplicate.

---

## 1. Problem

The three-layer trace answers *"given what I perceived, did I manage → decide → act coherently, and did reality confirm?"* It does **not** answer *"did I perceive reality correctly in the first place?"* — and that's the class the #352/#461/#588 sign bugs live in. The tautological-balance finding is the same gap from the other side: `home = max(0, in − out)` and the balance check tests `in ≈ home + out`, which is `0 = 0` whenever the clamp didn't fire, so the balance can never police a sign error that keeps the residual positive.

We already built the independent check — the counter-vs-power contradiction audits (`_audit_battery_sign_lock`, `_audit_autodetect_grid_sign`) — but they live **beside** the trace as standalone `diag_*_sign_contradiction` sensors with a **parallel** debounce (`_..._votes >= 5`), not through the trace's health engine.

**Goal:** make **Perception** a first-class layer of the observability arc, so a sign/balance contradiction surfaces through the *same* `sem_layer_mismatch` health signal as every control fault — and the trace can no longer show "all green" on a mis-perceived cycle.

**Non-goal:** changing sign detection/correction. Brand-seed, counter voter, and `flip_*`/`reset` services stay exactly where they are in `sensor_reader.py`. This is observability only — the same hard constraint as the parent trace spec.

## 2. The insight — Perception is Layer 0, and "balance integrity" is not a separate check

Two realisations drive the design:

1. **Perception sits *beneath* Management.** The arc is really **Perception → Management → Process → Integration**. Perception asks "do my sign-corrected readings agree with ground truth (the energy counters)?" If not, everything above executes coherently on garbage.
2. **The "balance invariant" is the *aggregate* of the per-signal sign checks — not a new thing.** Policing each signal's sign against its own counter (grid import/export, battery charge/discharge) *is* policing the balance's sign integrity. So we do **not** build a separate balance-residual subsystem; we surface the per-signal perception checks and the balance integrity falls out for free.

## 3. The trace record — a `cross_check`, NOT a forced three-layer subsystem

A perception check is a **two-view** check (my corrected read vs the counter ground truth) with **no actuation** — it does not fit `Management → Process → Integration` ("act & confirm"). Forcing it into the triple would stretch "Integration = act & confirm" to mean "observe", which is dishonest to the model.

Instead, add a sibling record type to `CycleTrace` for two-view checks:

```
CrossCheck                       # a Perception-layer reality check for one signal
  signal:   str                  # "grid_sign" | "battery_sign" (per bid: "battery_sign:b2")
  status:   LayerStatus          # reuse the SAME vocab (§4 of the parent spec)
  detail:   str                  # "corrected grid_power=+/− vs import counter rising"
  data:     dict                 # {expected, observed, agree: bool|null, power_w, deltas}

CycleTrace  (extended)
  seq, wall_iso, subsystems      # unchanged
  cross_checks: dict[str, CrossCheck]   # NEW — keyed by signal
```

`data["agree"]` is the linchpin, mirroring `integration.data["match"]`:
- `True` — corrected reading agrees with the counters.
- `False` — **a perception fault** (the sign is wrong, or the counters are swapped).
- `None` — nothing to judge this cycle (`|power| < 100`, counters unavailable, counter reset).

`LayerStatus` maps cleanly: `idle` when nothing to judge, `ok` when agreeing, `degraded`/`error` on unavailable/exception. No new vocabulary.

## 4. Reusing the fault → streak → health engine (the merge)

`TraceCollector` already turns per-subsystem faults into a debounced, surfaced signal:
`has_mismatch → _streak[k] → health(threshold) → binary_sensor.sem_layer_mismatch`.

Generalise `has_mismatch`/streak to also fold in cross-checks:

- Extend `commit()` so the mismatched-key set includes `f"perception:{signal}"` for any `CrossCheck` with `data["agree"] is False` **and** `status` acting (not idle) — identical shape to `SubsystemTrace.has_mismatch`.
- The existing `_streak` / `health()` / `latest_mismatch()` need **no change** beyond keying: a persistent perception contradiction (≥ threshold cycles) trips the **same** `sem_layer_mismatch` sensor, tagged `subsystem="perception:battery_sign"`.

**What this retires:**
- The parallel debounce in `sensor_reader.py` (`_battery_sign_contradiction_votes` / `_grid_sign_lock_contradiction_votes` and their `_warned` bookkeeping) → replaced by the collector's streak.
- The two standalone `diag_battery_sign_contradiction` / `diag_grid_sign_contradiction` sensors → deprecated (kept one release as thin reads off `health()`/the trace, then removed), because the one `sem_layer_mismatch` + the `diagnose` cross-check dump now carry it.

The audit *logic* (the counter-vs-power comparison) stays in `sensor_reader` and simply **returns** a `CrossCheck` verdict per cycle instead of mutating its own vote/flag state.

## 5. Design principles (hard constraints — inherit the parent spec's)

1. **Observe, don't restructure.** Detection/correction logic is untouched; `sensor_reader` returns a per-cycle verdict, the coordinator files it into the trace. Pinned by the existing "decisions identical with tracing on/off" test.
2. **Don't force the triple.** Perception is a `CrossCheck` (two-view), a peer of the three-layer subsystems — not a fake `SubsystemTrace`. Honesty over uniformity.
3. **One debounce, one health signal.** No new parallel vote counters or diag sensors; everything rides the `TraceCollector` streak + `sem_layer_mismatch`.
4. **Diagnostic, not recorded.** Cross-checks live in `_unrecorded_attributes` + the `diagnose` dump, same as the trace (#581 safety).

## 6. Architecture — where it's filled

- `coordinator/cycle_trace.py`: add the `CrossCheck` dataclass + `CycleTrace.cross_checks` + fold cross-checks into `commit()`'s mismatch set. ~30 lines, no change to the streak/health/latest_mismatch bodies.
- `coordinator/sensor_reader.py`: the two audit methods return `Optional[CrossCheck]` (verdict for this cycle) instead of mutating `_..._votes/_contradiction/_warned`. Drop that state.
- `coordinator/coordinator.py`: in `_async_update_data`, right after `read_power()` (where the sign is final), `trace.cross_checks[sig] = reader.perception_verdicts()` — one capture point, next to where the values already exist.
- `diagnose` service: include `cross_checks` alongside `recent_traces`.
- `sensor.py`: deprecate the two `diag_*_sign_contradiction` descriptions (phase out per §8).

Invasiveness budget: ~30 lines in `cycle_trace.py`, the audit methods change return type (net −~40 lines of vote/flag state), ~1 capture line, the diagnose extension. Net **negative** LOC.

## 7. Worked example — the flipped sign, now caught

```
seq 5120  battery
  management  ok    mode=auto soc=74 → sink at list position 3
  process     ok    NORMAL (charging from surplus)
  integration ok    action=none observed=+222W match=true      ← all green…
  cross_check battery_sign  FAULT  expected=+charge observed=discharge-counter-rising agree=FALSE (7 cycles)
```
Every control layer is green — the battery *looks* like it's charging as intended — but the perception cross-check says the corrected reading disagrees with which counter is climbing. `sensor.sem_layer_mismatch` is **on**, tagged `perception:battery_sign`. Today that cycle reads as perfectly healthy; with this, the sign fault is the one red line.

## 8. Build phases

- **Phase 1 — the `CrossCheck` record + `diagnose` dump.** Add the type, have the audits return verdicts, capture into the trace, surface in `diagnose`. The manual "pull last 30 cycles, read perception" tool. Sign detection behaviour unchanged.
- **Phase 2 — fold into the health signal.** Extend `commit()`'s mismatch set; a persistent perception fault trips `sem_layer_mismatch`. Retire the parallel debounce in `sensor_reader`.
- **Phase 3 — deprecate the two diag sensors** (one release as thin reads, then delete) + a "reading a perception fault" note in the trace troubleshooting doc.

Each phase ships alone; Phase 1 is most of the value.

## 9. Relationship to the SignDetector / CounterAudit dedup (do that first)

A separate finding: the grid and battery sign paths are **near-duplicated** — `_detect_grid_sign` vs `_detect_battery_sign_for` are the same magnitude-weighted accumulator (the battery docstring says *"mirrors the grid path from #461"*), and the three audit methods (`_audit_manual_grid_sign` / `_audit_autodetect_grid_sign` / `_audit_battery_sign_lock`) are provably-identical siblings (~225 lines). Extracting a `SignDetector` object and a `CounterCorrelationAudit` object (grid = one instance, battery = one per `bid`) retires ~350 duplicated lines **and** guarantees a fix to the lock/confidence logic can't land on grid and be forgotten on battery — the exact drift that made battery lag grid from #461 to #588.

**Sequence: dedup first, then this spec.** After the dedup, "the audit returns a `CrossCheck`" is a one-line change on a *single* `CounterCorrelationAudit.verdict()` instead of three parallel edits. The two efforts compound.

## 10. Testing

- **Behaviour-invariance:** sign detection/correction byte-identical with the trace on vs off; the `flip_*`/`reset` services unchanged.
- **CrossCheck:** a scripted "corrected grid_power positive while import counter climbs" sequence yields `agree=False`; an agreeing sequence yields `True`; low-flow yields `None`.
- **Health fold-in:** a persistent perception fault trips `sem_layer_mismatch` after `threshold` cycles and clears on recovery; a healthy install never trips it (PROD baseline: `agree` always True).
- **The #588 case as a fixture:** feed a reversed-Huawei counter stream and assert the perception cross-check goes red while all three control layers stay green — turning that reporter case into a permanent regression narrative.
- **Recorder safety:** cross-checks are `_unrecorded_attributes`; assert no per-cycle cross-check row hits the recorder (#581).

## 11. Risks & out of scope

- **R1 — model creep.** Mitigation: `CrossCheck` is *one* dataclass + a dict on `CycleTrace`; it is explicitly NOT a `SubsystemTrace`, and we add no new debounce/health code (reuse the collector).
- **R2 — losing the dedicated sensor.** Some users may key automations on `diag_battery_sign_contradiction`. Mitigation: keep it one release as a thin read off the trace before removal; call it out in the changelog.
- **Out of scope:** changing sign detection; a balance-residual subsystem (it's the aggregate of these checks, §2); tracing read-only sensors that have no ground-truth counter to check against.

## 12. Why now

The #589 reliability arc surfaced the tautological-balance blind spot and, in fixing it, quietly duplicated the trace's health engine. Folding perception into the trace both (a) closes the blind spot *inside the observability layer* — `sem_layer_mismatch` becomes a true "is SEM's whole view of reality sound?" signal — and (b) removes the duplication before it ossifies. Do the SignDetector dedup first (it's a clean, high-ROI win on its own), and this becomes a small, net-negative-LOC follow-on.
