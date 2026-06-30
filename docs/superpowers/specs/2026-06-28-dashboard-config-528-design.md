# Dashboard-first configuration (#528) — design

**Status:** approved (Approach A), 2026-06-28
**Issue:** #528 — Move post-setup configuration onto the SEM dashboard (knobs + entity pickers)

## Goal

Make the **permanent Configuration tab** (`sem-config-card`) the primary surface
for all post-setup configuration — behaviour knobs *and* entity/sensor wiring —
so users rarely touch HA's Settings → Devices → Integration → Configure flow
(which is fiddly and feels unreliable). The configuration controls must look and
feel like the **colorful battery-card design language** that was consolidated
away during the Control/Config de-dup (`1aa7010`) — accent-tinted sections,
chips, accent-filled sliders, mode pills — not plain accordion form rows.

## Decisions (locked)

1. **One permanent Config tab, enhanced.** No temporary dashboard, no
   hide-after-setup. Configuration is recurring (add a charger, swap a sensor,
   retune months later), so the surface stays.
2. **Approach A — restore the color in place.** Keep the accordion structure +
   the working `set_option`/`get_config`/`ha-entity-picker` infra; rebuild the
   *controls inside each section* in the battery-card style; add a first-run
   completeness banner. (Rejected: B wizard+settings = the "double surface"
   problem we just removed; C full rewrite = discards working infra.)

## Lifecycle (no change to init — already correct)

The native flow is already minimal-and-safe (#442 slim install):

- It auto-detects core solar/grid/battery sensors from the **HA Energy
  Dashboard** and **aborts if they're absent** → an entry is only ever created
  with valid core wiring. Two steps (confirm sensors + `observer_mode` toggle).
- `async_setup_entry` then runs fully and immediately: registers all services
  (`set_option`, `get_config`, `generate_dashboard`, …), builds the coordinator
  + SensorReader, creates entities, registers the frontend bundle, and
  **auto-generates the dashboard one-shot** (Config tab appears; guarded by
  `_install_dashboard_generated`).
- From cycle 1 SEM computes the energy balance from the guaranteed core sensors.
  Optional subsystems (EV, heat pump, tariff) are **inert until wired** — no
  device ⇒ no control action ⇒ nothing to mis-actuate. Missing optional sensors
  degrade gracefully (entities unavailable, reads 0/None, home clamp ≥0).

**Therefore SEM does NOT wait and needs no "setup-complete" gate.** #528 changes
only the *editing surface*, not the init lifecycle.

**Restart-avoidance (best-UX sub-goal):** today the install's one-shot dashboard
generation schedules an HA restart — a chunk of the "stubborn" feeling.
Investigate dropping it: resource URLs already carry a content-hash cache-bust
(`?v={version}-{sha1}`), so a `lovelace_updated` event may suffice to surface the
Config tab without a full restart. If confirmed, remove the scheduled restart.

## Save model

- **Tunables** (sliders, toggles, selects, numbers) → `set_option` applies
  **live** (the coordinator's `refresh_runtime_config()` / number-entity path).
- **Structural** (entity wiring) → `set_option` of a key in
  `_SET_OPTION_STRUCTURAL_KEYS` **reloads the entry**. To avoid reload thrash,
  structural edits are **staged locally and committed behind an explicit
  "Apply changes" button** per section (one reload for a batch). A section shows
  an "Applying…" state while the entry reloads.
- Every migrated entity key MUST be registered in `_SET_OPTION_STRUCTURAL_KEYS`
  (`__init__.py:192`) so its change reloads the entry.

## Components

All in `dashboard/card/src/cards/sem-config-card.js` (+ bundle rebuild). Reuse
the existing `_saveOption` / `_refreshOptions` / `_ensureEntryId` plumbing.

### Shared colorful control helpers (Phase 0)
Declarative, accent-aware renderers so each section is data-driven and themed to
its section color:
- `_renderKnob(key, labelKey, {min,max,step,unit,accent}, helpKey)` — slider with
  an accent-filled track + live value chip; saves live.
- `_renderToggle(key, labelKey, accent, helpKey)` — colored pill toggle; live.
- `_renderSelect(key, labelKey, options, accent, helpKey)` — live.
- `_renderModePills(key, options, accent)` — the battery-style mode selector
  (hex pills, selected = accent fill). Live.
- `_renderEntityPicker(key, {domain, deviceClass, structural})` — wraps
  `ha-entity-picker` in a card-styled row; if `structural`, writes to the
  staged-changes buffer (Apply) instead of saving immediately.
- `_renderApplyBar(sectionId)` — shows pending structural count + Apply button +
  Applying… state.
- (Optional, battery sections) `_renderSocStrip(...)` — SOC-zone visual.

### First-run completeness banner
Top-of-card banner: per-domain "configured / not configured" derived from
`get_config` + the binary `*_registered` sensors. Each unconfigured domain links
to its section; turns green and recedes when complete. No second surface.

### i18n
All labels via `translations.json` / `semLocalize` across 15 languages.

## Data flow

```
sem-config-card  ──get_config──▶  merged options dict (cached _options)
   │  user edits
   ├─ tunable   ──set_option(key,val)──▶ live (refresh_runtime_config / number)
   └─ structural ─stage─▶ Apply ─set_option(keys…)─▶ entry reload ─▶ coordinator re-reads
```

## Phasing

- **Phase 0** — shared colorful control helpers + Apply-bar + completeness banner
  scaffolding. Tests for the helpers.
- **Phase 1 (proof slice)** — **Heat Pump** section fully migrated in the colorful
  style: relay1/relay2 + climate + power-sensor pickers (structural, Apply),
  boost-offset/max-setpoint/priority knobs+pills, Invert-SG-Ready toggle. Register
  any not-yet-structural keys. Card-render test + structural-key `set_option`
  test + **HA-TEST live verify**. This validates the whole pattern.
- **Phase 2** — tariff (finish), load_management, settings, settings_ev.
- **Phase 3** — notifications, battery_scheduler.
- **Phase 4** — EV charger add/edit/remove (hardest; preserve per-charger
  smart-merge / isolation #464 — list edits must not drop siblings).
- **Phase 5** — trim native OptionsFlow per migrated domain to avoid
  dual-canonical drift. **Open decision (defer to Phase 5):** fully stub the
  OptionsFlow vs keep a thin mirror for headless/no-dashboard admin — leaning
  **thin mirror**.

## Testing (per phase)

- Card-render test (section renders, controls present).
- Structural-key test: changing each migrated entity key round-trips through
  `set_option` and is registered structural (reload).
- Tunable test: live keys apply without reload.
- i18n: 15-language labels present (parity guard).
- HA-TEST live verify (the mock rig + real entities); full suite green.

## Risks

- **Reload thrash** → explicit Apply for structural fields (designed in).
- **Dual-canonical drift** → trim native step as each domain migrates (Phase 5).
- **Discoverability** → pointer from the native flow to the dashboard; keep
  critical settings reachable both ways during migration.
- **Bundle**: editing `src/` requires `npm run build` before deploy (cards ship
  as the Lit bundle `dist/sem-cards.js`).

## Acceptance (per phase)

Every setting in the migrated domain is editable on the Config tab and
round-trips through `set_option` (live for tunables, reload for entities);
`ha-entity-picker` fields validate domain/existence; 15-language labels; controls
in the colorful battery design language; tests green + HA-TEST verified.
