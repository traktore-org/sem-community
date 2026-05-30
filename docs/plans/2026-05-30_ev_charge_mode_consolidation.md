# Plan — EV charge UX consolidation (#277)

## Context

The EV charge UX currently exposes **four orthogonal per-charger
controls** that compose correctly but are hard to reason about:

1. `select.sem_charger_<id>_ev_charging_mode` — `auto` / `minpv` / `now` / `off` (daytime solar strategy)
2. `switch.sem_charger_<id>_night_charging` — overnight grid top-up to Min
3. `switch.sem_charger_<id>_smart_night_charging` — forecast-aware skip / size-down at night
4. `switch.sem_charger_<id>_tariff_optimized` — defer to cheapest contiguous price window (#247)

Raised in the #247 review: *"is it correct to activate all? are night
+ tariff the same?"* PR #276 applied a lightweight fix (rename + nest
tariff under grid charging), but the real fix is **consolidation into
one named Charge mode selector** — the Solarmanager-style UX reference
in #239.

## Proposal — Charge mode selector

Replace the four toggles with **one** `select.sem_charger_<id>_charge_mode`
entity with five options, plus the unchanged Min/Max range and
Charge-by deadline:

| Mode | Daytime behaviour | Night behaviour | Replaces toggle combo |
|---|---|---|---|
| **`solar_only`** | Surplus only (no grid backfill) | No charging | `mode=auto/pv/self_consumption` + night=off + tariff=off |
| **`solar_plus_cheap`** | Surplus by day, grid in cheapest tariff windows | Charge in cheapest windows up to Min | `mode=auto` + tariff=on + night=on |
| **`min_plus_solar`** (default) | Min from grid + solar to Max | Top up to Min from grid | `mode=minpv` (any night state — minpv always pulls Min from grid) |
| **`always_max`** | Charge at max regardless | Charge at max regardless | `mode=now` |
| **`off`** | No charging | No charging | `mode=off` (or night=off + mode=off) |

`smart_night_charging` becomes implicit: ON for `min_plus_solar` and
`solar_plus_cheap` (forecast-aware sizing helps both), N/A for
`solar_only` and `off`, OFF for `always_max`. Surfaced via the
mode's published `charging_strategy_reason` so users can see what's
driving each decision.

## Mapping today's strategy values onto the new modes

The existing strategy decision in `_determine_charging_strategy`
already returns one of `solar_only` / `self_consumption` / `battery_assist`
/ `min_pv` / `now` / `idle`. The new Charge mode selector is a
**user-intent layer** that constrains which strategy decisions can
fire. The underlying state machine and canonical `EVBudget` stay
exactly the same.

| New mode → | `solar_only` | `solar_plus_cheap` | `min_plus_solar` | `always_max` | `off` |
|---|---|---|---|---|---|
| Allowed strategies | `solar_only`, `self_consumption`, `idle` | `solar_only`, `self_consumption`, `night_grid` (tariff-windowed), `idle` | All except `now` | `now` only | `idle` only |
| Battery assist (Z4) allowed? | No | No | Yes (subject to floor SOC) | N/A | No |
| Night charging fires? | No | When tariff-cheap | Yes (subject to Min) | Always | Never |

## Migration

One-shot migration in `async_migrate_entry`:

```python
def _derive_charge_mode(charger_cfg) -> str:
    mode = charger_cfg.get("ev_charging_mode", "pv")
    night = charger_cfg.get("night_charging_enabled", True)
    tariff = charger_cfg.get("tariff_optimized", False)

    if mode == "now":
        return "always_max"
    if mode == "off":
        return "off"
    if mode == "auto" and tariff:
        return "solar_plus_cheap"
    if mode in ("pv", "auto", "self_consumption") and not night:
        return "solar_only"
    return "min_plus_solar"  # the catch-all default — covers minpv (always grid-Min)
```

For HACS upgrade users, the migration:
1. Reads the existing toggle states per charger
2. Writes the derived `charge_mode` into `coordinator.config['ev_chargers'][i]`
3. Removes the deprecated `night_charging_enabled` and `tariff_optimized` fields *only after one full cycle* — old config keys are kept for rollback safety
4. Logs an INFO line per charger naming the migration choice

Deprecated entities (`switch.sem_charger_<id>_night_charging`,
`...tariff_optimized`, `...smart_night_charging`) are kept registered
but hidden, so user automations that read their state don't break;
they become read-only mirrors of the new mode.

## Phases

### Phase A — Add the new selector (no behaviour change)
- `select.py`: register `select.sem_charger_<id>_charge_mode` per charger
- `translations.json`: 5 mode labels × 15 languages
- Coordinator reads the new field; if absent (pre-migration), falls
  through to the legacy switches. Both paths produce identical
  strategy decisions.
- Migration writes the derived `charge_mode` to existing setups on
  first load.
- 15+ unit tests covering all five modes' strategy outputs against
  daytime / night / Z4 / forecast-cheap scenarios.

### Phase B — Use the new field as authoritative
- Coordinator switches: read `charge_mode`, fall back to legacy
  switches only if `charge_mode` is missing (covers users who
  somehow skip migration).
- Deprecated switches become read-only mirrors.
- Card update: replace the four toggle/select widgets with the new
  selector + a help line under each mode.

### Phase C — Remove the deprecated toggles
- After one full release cycle of Phase B (so users have ample
  rollback chance), drop the legacy switches from `switch.py`.
- The fallback path in the coordinator goes away.

## Resolved design questions (2026-05-30)

Maintainer answered before Phase A started:

1. **`solar_plus_cheap` semantics for non-tariff users:** **Hide the
   option entirely** when no dynamic tariff is configured. The mode
   appears in the selector only when a tariff is present. Cleanest
   UX — no ghost modes; "why isn't it charging at night?" cannot
   arise. Selector population is dynamic (recomputed on tariff add /
   remove).
2. **Battery assist in `min_plus_solar`:** **Always available** when
   SOC ≥ floor. No new toggle. Matches today's Auto+Z4 behaviour;
   no re-introduction of the toggle-soup.
3. **Smart night being implicit:** **Hide the toggle.** Forecast-
   aware skip / size-down is strictly better than dumb-on-at-
   midnight; no value in user disablement. Smart is implicitly ON
   for `min_plus_solar` and `solar_plus_cheap`, N/A for the others.
   The existing `smart_night_charging` switch becomes hidden + dead
   (kept registered for automation backward-compat, but read-only).
4. **Default for new installs:** **`min_plus_solar`** — matches the
   current factory defaults (`pv` + night=on + smart=on + tariff=
   off). Zero behaviour change for new installs.

## Why this lands cleanly on top of v1.6.0

- The canonical `EVBudget` arc shipped in v1.6.0 means the underlying
  strategy → budget machinery is now stable and unified. The Charge
  mode selector is a thin layer of user intent on top, with no
  budget-formula changes.
- The strategy enum (`EVBudgetStrategy.*`) is already first-class —
  the mapping in this plan is direct.
- Migration is opt-in via `async_migrate_entry`; no risk to existing
  setups that don't trigger migration.

## Not in scope

- No changes to the canonical EVBudget formula.
- No changes to Min/Max target semantics (#245).
- No changes to `Charge by` deadline behaviour (#246) or tariff
  window selection (#247).
- The taper detector, EV intelligence, and battery assist all
  remain unchanged — only their *enablement gating* moves under the
  Charge mode selector.

## Estimated effort

- Phase A: ~6–8 hours (selector, translations, migration, tests)
- Phase B: ~4–6 hours (coordinator switchover, card UI rewrite)
- Phase C: ~1 hour (removal)

Realistic ship target: **v1.7.0** in a focused 2–3 day window after
v1.6.0 has soaked.

## Decisions confirmed

- Five-mode taxonomy: confirmed.
- Open questions 1–4: resolved (see "Resolved design questions" above).
- `v1.7.0` ship target: confirmed.

Phase A in progress on branch `feature/277-charge-mode-phase-a`.
