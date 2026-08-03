# PerChargerContext Consolidation — Design Spec

**Status:** Proposed design (grounded 2026-07-14, from the #589 architecture hunt). Build target 1.8.0. **Requires the live two-charger HA-TEST rig** (`project_hatest_two_charger_rig`) to verify — this is the one item in the reliability arc that must not ship on unit tests alone.
**Motivation:** the multi-charger "per-charger code reads the fleet/primary value instead of THIS charger's" bug class (#284/#289/#315/#318, four hotfixes v1.6.0–6.6) was structurally closed with `PerChargerContext` + `_this_charger_power` + the FleetEvPower AST lint. But the *state-swap* half of that apparatus is **still leaky**: there are **two** independent per-charger swap surfaces plus a third done right, and a new per-charger field lands in whichever the author happened to be near — silently re-opening the exact class the context exists to prevent.

---

## 1. Problem — three ways to hold per-charger state, only one safe

**Surface A — `PerChargerContext._saved` (the swap dict).** `__enter__` snapshots ~10 coordinator *primary scalars* into `_saved`, copies this charger's value out of a parallel `_ev_*_per_charger` dict into the primary scalar, and `__exit__` restores. Eight scalar/dict pairs (`coordinator/coordinator.py:256-272`, `coordinator/per_charger_context.py:245-361`):

| primary scalar (`self._ev_*`) | parallel dict (`self._ev_*_per_charger`) |
|---|---|
| `_ev_stalled_since` | `_ev_stalled_since_per_charger` |
| `_ev_enable_surplus_since` | `_ev_enable_surplus_per_charger` |
| `_ev_charge_started_at` | `_ev_charge_started_per_charger` |
| `_ev_last_change_time` | `_ev_last_change_per_charger` |
| `_ev_reenable_attempts` | `_ev_reenable_attempts_per_charger` |
| `_ev_charge_refused` | `_ev_charge_refused_per_charger` |
| `_ev_last_set_amps_ts` | `_ev_last_set_amps_ts_per_charger` |
| `_ev_budget_history` | `_ev_budget_history_per_charger` |

Adding a per-charger field is a **three-site edit** (dict decl in `__init__`, snapshot+swap in `__enter__`, write-back in `__exit__`). Miss the write-back and charger[0]'s value bleeds into charger[1] — the #315 class. The context's own comment (`per_charger_context.py:66-71`) admits `effective_state`/`this_power_w` were leaks pulled in during v1.6.14; the eight pairs above are the *same* leak, unfixed.

**Surface B — the taper-detector swap.** `_ev_taper_detector` (singular, `coordinator.py:405`) is reassigned to `_ev_taper_detectors[primary_id]` (`coordinator.py:5767`) — a **completely separate** per-charger swap at a different call site that never touches `PerChargerContext`. (The #589 EV W2/W3 fix already removed one fleet-read here, but the swap mechanism remains.)

**Surface C — the one done right.** `_charge_no_draw_since` (`coordinator.py:2402`) is a plain `Dict[cid → value]`, read/written **directly by cid**, never swapped into a primary scalar. No snapshot, no restore, no leak-by-omission possible. **This is the target shape.**

## 2. The bug class, precisely

Any per-charger scalar read/written on `self._ev_*` inside the per-charger loop that is forgotten from either the `_saved` snapshot or the `__exit__` write-back **silently bleeds one charger's state into the next**. The FleetEvPower lint catches *fleet* reads; it does **not** catch a *missing swap-back* — that's invisible until a two-charger user reports "charger 2 behaves like charger 1". This is the residue CLAUDE.md flags: *"`effective_state` and `this_power_w` are still local variables / parallel dicts rather than fields on PerChargerContext. The lint is a stopgap."*

## 3. Target model — per-charger state as context fields, no primary-scalar swap

Follow Surface C everywhere. `PerChargerContext` holds the per-charger fields **as its own dataclass fields**, sourced once from a single per-cid store on the coordinator and written back on exit — the primary `self._ev_*` scalars are **retired** from the per-charger loop.

```
# coordinator: ONE per-cid store (replaces the 8 parallel dicts)
self._pcc_store: Dict[str, PerChargerState] = {}   # cid → dataclass

@dataclass
class PerChargerState:          # was: 8 _ev_*_per_charger dicts
    stalled_since: Optional[float] = None
    enable_surplus_since: Optional[float] = None
    charge_started_at: Optional[float] = None
    last_change_time: Any = None
    reenable_attempts: int = 0
    charge_refused: bool = False
    last_set_amps_ts: Optional[float] = None
    budget_history: list = field(default_factory=list)
    # + effective_state, this_power_w (retire the parallel local vars / dicts)
    # + the taper detector reference (retire Surface B)

# per-charger loop body reads pcc.state.stalled_since, NOT self._ev_stalled_since
with PerChargerContext(coord, cid, ...) as pcc:
    ... pcc.state.stalled_since ...      # no self._ev_* swap at all
# __exit__ just persists pcc.state back into coord._pcc_store[cid] — nothing to "restore"
```

Adding a per-charger field becomes a **one-site edit** (a field on `PerChargerState`) that *cannot* leak — there is no snapshot/restore to forget.

## 4. Migration — incremental, rig-verified, behavior-identical

Big-bang is too risky on this code. Sequence, each step behavior-identical (full suite + the two-charger rig green before the next):

1. **Retire Surface B into the context (small, self-contained).** Move the taper-detector reference onto `PerChargerContext`/`PerChargerState`; delete the `_ev_taper_detector = _ev_taper_detectors[primary_id]` swap. Isolated, proves the pattern.
2. **Introduce `PerChargerState` + `_pcc_store`** alongside the existing 8 dicts (dual-write), so nothing moves yet.
3. **Migrate the 8 pairs field-by-field.** For each: point reads at `pcc.state.<field>`, drop the primary scalar + its `_saved` entry + the parallel dict. One field per commit, full suite + rig after each. Miss-a-swap-back regressions surface immediately on the two-charger rig (charger 2 inheriting charger 1's timer).
4. **Fold in `effective_state` / `this_power_w`** (the acknowledged leaks) as the last fields.
5. **Delete `_saved` and the swap machinery** once no primary scalars remain — `__enter__`/`__exit__` become "load `_pcc_store[cid]` → yield → store back".

## 5. The structural guard (replaces the lint's blind spot)

Add a test/lint that **fails CI if any `self._ev_*` primary scalar is read inside the per-charger loop body** (the loop is delimited; AST-walk it for `Attribute` reads on the retired names). Once the primary scalars are gone, this makes the leak *unrepresentable* — the FleetEvPower lint catches fleet reads; this catches missing-swap reads. Together they close both halves of the multi-charger class structurally, not by convention.

## 6. Testing

- **Behaviour-invariance:** single-charger decisions byte-identical before/after each step.
- **The two-charger rig (mandatory):** run the `project_hatest_two_charger_rig` scenario after every migration step — charger A stalling/ramping must NOT move charger B's timers/attempts/refused flags. This is the only reliable detector for a missed swap-back.
- **Leak-guard test:** a per-charger field added to `PerChargerState` is exercised on both chargers with divergent values; assert no cross-contamination.
- **The CI guard (§5):** a deliberately-introduced `self._ev_stalled_since` read in the loop fails the guard test.

## 7. Risks & out of scope

- **R1 — a missed swap-back during migration** is the exact bug we're removing. Mitigation: field-by-field + the two-charger rig gate after each; never batch.
- **R2 — cost.** ~30-40 `ev_control.py` read-sites touched. Mitigation: mechanical, one field per commit, each independently revertable.
- **Out of scope:** the FleetEvPower newtype-as-type-error (dead end — the repo runs no type checker; the AST lint IS the enforcement); merging the two reconcilers (Procrustean — they diverge fundamentally, `device_reconciler` observe-only vs `charger_reconciler` a decision table).

## 8. Why now / why separate from the rest of #589

This is the one reliability item that must be **rig-verified, not unit-verified** — a missed swap-back passes every unit test and only shows on two live chargers. It's deliberately kept out of the A1/B soak batch: those are safe refactors/additions; this is a live-behaviour-sensitive migration that earns its own focused session with the two-charger rig. Do it after the A1/B soak confirms clean.
