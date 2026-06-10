# Changelog

All notable changes to SEM are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> From v1.7.0-beta.14 onward, release entries follow the
> [music-assistant addon](https://github.com/music-assistant/home-assistant-addon)
> style: DD.MM.YYYY dates, emoji-prefixed sections, one-liner bullets with
> `(by @author in #PR)` attribution. Older entries (≤ beta.13) stay in the
> prose-paragraph style they were written in.

# [1.7.3-beta.6] - 10.06.2026

## 🩹 2026-06-10 review fixes — P1 batch

Top findings from the full-codebase review (the unfixed remainder is tracked in #475 / #476):

### 🛠️ Bug fixes

- **#461 root cause: split-grid pick stability** — any-device split-grid discovery re-ran every cycle and adopted the result unconditionally, so a flicker in HA's state-list iteration order could swap which sensor plays import vs export, inverting the computed `grid_power` sign ("sometimes works, sometimes inverted", Growatt). New adoption gate: held picks win unless there's no pick yet, the new match is a same-device upgrade, or a held pick went unavailable. Late-loading DSMR discovery (#166) preserved
- **`time.py` per-charger writer hardened** — the deadline writer was missed by the #469 patch round: it still clobbered `ev_chargers` to `[]` when options lacked the key, and silently no-op'd on a partial list. Now identical to the select.py / number.py contract (data fallback + recovery-append + WARNING)
- **`sem-chart-card` empty-state crash (second instance of the #457 class)** — the card lit-bound `${this._t('loading')}` AND overwrote the same node via `.textContent` in `_showEmpty()`, destroying lit's text part so the next `requestUpdate()` threw and froze the card. Empty-state and canvas visibility are now fully lit-rendered (bundle rebuilt)

### 🧪 Tests

- `TestSplitGridPickStability` (4 tests): flipped re-discovery is not adopted; same-device upgrade is; unavailable pick reopens adoption; late-loading meter still discovered
- `time.py` recovery + data-fallback contract tests in `test_ev_chargers_storage_heal.py`

---

# [1.7.3-beta.5] - 10.06.2026

## 🩹 Storage heal for poisoned `options.ev_chargers` (#462/#464 follow-up #3)

The writer fixes shipped in beta.1–beta.4 (#467/#468/#469 + the smart-merge
fall-through) stopped **new** corruption of the options-side charger list, but
none of them repaired storage that the v1.7.2 .. v1.7.3-beta.3 builds had
already corrupted. Once `entry.options.ev_chargers` is a *partial* list
(e.g. charger 1 only — the auto-discovery reseed plants exactly that shape
after a `[]` clobber), the `{**data, **options}` merge hides the data-side
sibling forever and every per-charger write targeting the missing id
silently no-ops: the persistent "changing charger 2 does nothing at all"
report on #462/#464 that survived all three betas. The #469 `or`-fallback
only fires for missing/empty lists, not partial ones.

### 🛠️ Bug fixes

- **Setup-time storage heal** — `async_setup_entry` reconciles a poisoned `options.ev_chargers` against `entry.data` by id-union (options fields win per charger, data-only siblings restored, id-less ghost entries dropped). Idempotent: one healing write, then quiet. Logs a WARNING naming the before/after ids so support can see it happened
- **Per-charger writers never silently no-op** — `SEMPerChargerSelect.async_select_option` / `SEMPerChargerNumber.async_set_native_value` recover a charger missing from the stored list out of `entry.data` (full dict, or a minimal `{"id": ...}` stub) and append it, with a WARNING — instead of dropping the write on the floor
- **`_merge_ev_chargers_by_id` drops id-less entries** — they're untargetable by every write path and at registration get assigned a positional `ev_charger_<idx>` id that can collide with a real sibling (ghost charger)
- **Config card stamps the charger `id`** — the nested per-charger editors (`sem-config-card.js`) now always carry `id` on the entries they submit, so a partial submit can never produce an id-less ghost

### 🔍 Diagnostics

- `diagnose` payload for the `ev_chargers` (and `all`) section now includes `ev_chargers_storage_split` — the per-side `entry.data` vs `entry.options` charger lists (id / name / charge_mode). The merged `config` block hid exactly the fact that mattered during the #462/#464 triage

### 🧪 Tests

- `tests/test_ev_chargers_storage_heal.py` — heal contract, writer recovery (select + number), ghost-drop contract
- `tests/test_services_real.py::test_setup_heals_poisoned_options_ev_chargers` — real-HA boot with RienduPre-shaped poisoned storage: asserts the options list heals, charger 2 registers, and a charger-2 mode flip lands

---

# [1.7.3-beta.4] - 09.06.2026

## 🧪 Framework tests + caught third instance of #469 fall-through

While writing the real-HA integration tests for the `set_option` service path, the test against `sem_multi_wallbox_config_entry` (a fresh-install fixture with chargers only in `entry.data`) caught the **same `entry.options.get("ev_chargers", [])` fall-through pattern** PR #469 fixed for the per-charger setters — but this time in the `__init__.py` smart-merge itself. A fresh-install multi-charger user opening the Config card for the first time and editing one charger's field would hit it: the merge appends the partial submit as a stray entry (no matching id in the empty existing list) and the next reload clobbers `entry.data.ev_chargers` with the partial-options-side list. Same symptom as #464 but on the fresh-install path — patched in the same PR as the test that caught it.

### 🛠️ Bug fix

- **#464 follow-up #2** `set_option` smart-merge falls back to `entry.data.ev_chargers` when `entry.options` doesn't have the key. Latent since v1.7.2-beta.2 (`set_option` rework). Affected: fresh-install multi-charger users editing per-charger fields via the Config card before any prior write had populated `entry.options.ev_chargers` (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))

### 🧪 Test infrastructure

- `tests/test_services_real.py` — four real-HA integration tests that drive `solar_energy_management.set_option` through the service registry and assert on `hass.states.get(...).state`. The test layer that would have caught the v1.7.3-beta.1 number-entity staleness regression (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))
- `sem_multi_wallbox_config_entry` fixture — seeded from RienduPre's diagnose dump, reusable for any multi-charger contract test (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))
- `sem_config_entry` fixture bumped from schema v7 → v12.1 (stale since the #135 v11→v12 migration) (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))
- `tests/scenarios/2026-06-09_rienduPre_dual_wallbox.yaml` — YAML scenario replay of RienduPre's dual-Wallbox setup running through the existing scenario harness; locks the `solar_plus_cheap`-outside-cheap-window mode-isolation contract (by @traktore-org in [#472](https://github.com/traktore-org/sem-community/pull/472))

### 🩹 Process retirement

The `[live-test-before-deploy]` policy memo from earlier today is now backed by a mechanical CI gate via `test_services_real.py`. Future PRs touching `__init__.py` / `select.py` / `number.py` set_option paths have the same green-or-red signal pytest already gives for pure-helper bugs.

---

# [1.7.3-beta.3] - 09.06.2026

## 🛠️ Per-charger options-fallback fix (#464 follow-up)

Follow-up to v1.7.3-beta.2 for the **asymmetric multi-charger symptom** RienduPre reported under #464 — *"change on charger 1 works, change on charger 2 does nothing"*. Investigation of his diagnostic dump traced the asymmetry to a latent bug in **both** per-charger setters:

```python
# select.py:async_select_option  and  number.py:async_set_native_value
new_options = {**self._entry.options}
ev_chargers = [dict(c) for c in new_options.get("ev_chargers", [])]   # ← [] when missing
for charger in ev_chargers:                                            # ← iterates nothing
    if charger.get("id") == self._charger_id:
        charger[self._config_key] = value
        break
new_options["ev_chargers"] = ev_chargers                               # ← writes [] back
```

When `entry.options.ev_chargers` doesn't exist (fresh install where the user has never opened the Config card), the setter writes `entry.options["ev_chargers"] = []`. On the next reload, the merge `{**entry.data, **entry.options}` overrides the data-side chargers with the empty options-side list — **every charger disappears**, all per-charger entities go unavailable. Latent since the multi-charger arc landed.

### 🛠️ Bug fix

- **#464 follow-up** Per-charger select + number setters now fall back to `entry.data.ev_chargers` when `entry.options` doesn't have the key (by @traktore-org in [#469](https://github.com/traktore-org/sem-community/pull/469))

### 🙏 Thanks

- **@RienduPre** for the full diagnose dump on v1.7.3-beta.1 — without it the asymmetric pattern would have stayed buried.

---

# [1.7.3-beta.2] - 09.06.2026

## 🩺 RienduPre v1.7.2 bug-response release

> v1.7.3-beta.1 was tagged and immediately retracted today — live HA-TEST verification (post-merge, pre-soak) caught that the skip-reload optimization left number entities stale at their old value after `set_option`. The full pytest suite was green but mocks don't model HA's entity lifecycle. Hotfix in [#468](https://github.com/traktore-org/sem-community/pull/468) routes tunable changes through each entity's own write path, which updates `_attr_native_value` + writes state synchronously. The post-incident `[live-test-before-deploy]` memory was added so backend changes touching HA's config-entry / entity-state pipeline now require live entity-state verification BEFORE merge, not just pytest.

Four bug reports landed on v1.7.2 within five hours this morning ([#460](https://github.com/traktore-org/sem-community/issues/460), [#461](https://github.com/traktore-org/sem-community/issues/461), [#462](https://github.com/traktore-org/sem-community/issues/462), [#464](https://github.com/traktore-org/sem-community/issues/464)) — all from the same reporter on the same install. Root-cause analysis traced the three logic bugs to a single change in v1.7.2-beta.2: the `set_option` service was switched to always-reload the integration so heat-pump entity rewires (#448) would take effect. Side effect was that every Config-card tunable tweak destroyed the SensorReader's split-grid discovery state and the per-charger context across the multi-charger loop — the candidate root cause for all three logic bugs. The fix scopes the reload to structural keys only, routes tunables through their matching entity's write path, and adds smart-merge for `ev_chargers` to prevent partial submits from dropping sibling chargers.

Also unblocks #453 by structurally fixing #457 in the same release: the diagram card was the one card in the bundle that mixed Lit declarative bindings with imperative DOM mutation on the same node, crashing `requestUpdate()` whenever late translations triggered a re-render. Pure-reactive rewrite brings it in line with the other 21 bundled cards.

### 🛠️ Bug fixes

- **#457** Diagram card pure-reactive rewrite — eliminates the lit-html `TypeError: Cannot set properties of null` crash on `requestUpdate()`. Source -202 LOC, zero imperative writes on lit-bound nodes (by @traktore-org in [#459](https://github.com/traktore-org/sem-community/pull/459))
- **#453** Single-channel sem-localize delivery — drops the dual-channel `add_extra_js_url` hack that masked #457 (by @traktore-org in [#463](https://github.com/traktore-org/sem-community/pull/463))
- **#460** Clipboard copy works on plain-HTTP installs — execCommand fallback for `navigator.clipboard` (which requires HTTPS / localhost), pattern mirrors `sem-system-card._writeClipboard` from #285 (by @traktore-org in [#465](https://github.com/traktore-org/sem-community/pull/465))
- **#462 / #464** `set_option` service: smart-merge `ev_chargers` by id (so a partial Config-card submit can never drop sibling chargers) + scope reload to structural entity-wiring keys only + route tunable changes through each entity's own write path (`number.set_value` / `switch.turn_on/off` / `select.select_option`), so the entity state refreshes synchronously without reloading the integration. Pure-function helpers extracted to module scope with 20 contract tests. Strong candidate fix for #461 too (eliminates the reload-driven split-grid re-discovery) (by @traktore-org in [#467](https://github.com/traktore-org/sem-community/pull/467) + hotfix [#468](https://github.com/traktore-org/sem-community/pull/468))

### 🩺 Defensive instrumentation

- Charger entity-id validation at registration — logs WARNING when configured `ev_charging_power_sensor` / `ev_current_control_entity` / `ev_charger_service_entity_id` / `ev_start_stop_entity` / `ev_charge_mode_entity` no longer exist in HA's state registry. Catches the historical bug class (#315 KEBA, #357 Wallbox) where HA-integration upgrades silently rename entities (by @traktore-org in [#466](https://github.com/traktore-org/sem-community/pull/466))
- Wallbox pause-switch discovery surfaces a WARNING when no `switch.*pause_resume` is found on the device — explains the exact consequence (generic `set_current(0)` fallback, which some Wallbox firmware latches per #357) and the workaround (by @traktore-org in [#466](https://github.com/traktore-org/sem-community/pull/466))
- Split-grid sensor change-detection logs WARNING with before→after IDs when the discovered import/export sensors change between cycles. Surfaces the "any-device" confidence flip behind #461 (by @traktore-org in [#466](https://github.com/traktore-org/sem-community/pull/466))

### 🌐 i18n

- Dutch translation update for the new configuration strings, contributed by the affected reporter (by @RienduPre in [#458](https://github.com/traktore-org/sem-community/pull/458))

### 🙏 Thanks

- **@RienduPre** for the four detailed bug reports with video evidence and for the Dutch translation contribution while we were debugging his install.

---

# [1.7.2] - 08.06.2026

## 🎉 Stable Release

_Consolidates [1.7.2-beta.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.2-beta.1) through [1.7.2-beta.7](https://github.com/traktore-org/sem-community/releases/tag/v1.7.2-beta.7). 19 commits since [1.7.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1). 24 hours of HA-PROD soak with zero errors._

### 🔥 New: Hot Water boiler control (#454)

The `HotWaterController` class existed from day one but was never instantiated — setting `hot_water_entity` in the Config tab Hot Water section did nothing at runtime. This release closes that gap end-to-end:

- Registration in setup mirrors the heat-pump pattern (entity + temp sensor + targets + Legionella interval + priority).
- Live runtime state (`hot_water_current_temperature`, `hours_since_legionella`, the 5 `_last_*_path` audit recorders from #420) populated every cycle into `coordinator.data`.
- Live-status block on the Hot Water section shows current temp, Legionella tracking, and decision paths when the controller is registered.
- Two Repair issues fire when configured entities go unavailable: `hot_water_entity_unavailable` (boiler control) and `hot_water_temperature_sensor_unavailable` (with #420 fail-safe semantics — boiler is NOT activated on surplus when the temp sensor is broken).
- Orphan-repair sweep handles user reconfiguring the boiler entity.
- Diagnose modal surfaces the full state via `_DIAGNOSE_HOT_WATER_STATE`.
- 7 new wire-up tests + 7 new repair tests. (by @traktore-org in #454)

### 🔥 New: Tariff price + 15-min provider support (Discussion #432)

The bottom-of-dashboard "Today's Schedule" tariff timeline was lying. Saturday on Tibber NL showed a solid "Goedkoop" bar for all 24 hours when the current price card next to it correctly showed "Normaal" at 0.31 EUR/kWh. Two unrelated code paths; one was misleading.

- **JS fallback no longer lies on weekends.** Mirrors the current `tariff_price_level` across the day with a dashed/translucent indicator showing "best-effort, not real per-hour data".
- **Parser accepts 15-min ENTSO-E + Tibber Pulse shapes.** Added `prices` (singular) attribute key + `time` / `hour` timestamp keys to the parser vocabulary. NL ENTSO-E users now get correct per-hour data SEM-side.
- **New diagnostic fields** on the Tariff diagnose surface: `tariff_parsed_attribute`, `tariff_parsed_count`, `tariff_parsed_interval_seconds`, `tariff_today_level_counts`, `tariff_today_first_price`, `tariff_today_last_price`. One Diagnose paste tells us in one read which failure mode hit (no parser match / timezone filter / genuinely-all-cheap / percentile-fallback). (by @traktore-org)

### 🩺 Heat-pump UX + diagnostics

- **Configuration tab subtitle now reflects actual registration state** — was reading `sensor.sem_heat_pump_registered` (doesn't exist) instead of `binary_sensor.sem_heat_pump_registered`. New `_bin()` helper fixes 3 use sites. RienduPre #448. (by @traktore-org)
- **Orphan heat-pump Repair issues now auto-clear** — repairs from a prior config (e.g. user switched from ESP relays to Modbus template switches) used to stay in the registry indefinitely. New sweep enumerates `heat_pump_relay{1,2}_unavailable_*` issues and clears any whose entity is no longer in current config. RienduPre #448. (by @traktore-org)
- **Heat-pump runtime path telemetry now visible** — the #421 audit shipped `_last_*_path` recorders in `v1.7.0-beta.24` but never wired them through to a user-visible surface. All 5 paths + current temperature now publish through `coordinator.data` into the Diagnose slicer.
- **Repair issues survive reload** — replaced in-memory `_raised` flag with idempotent always-raise/always-clear pattern. The flag was per-coordinator-instance, so reloads reset it, and stuck repairs never auto-cleared. Reported by RienduPre + caught in live testing.

### 🩺 Forecast write-time-weather fix (#416)

PROD telemetry on 2026-06-05 showed 42% of forecast records had `weather_category=unknown`. Root cause: weather was captured at day-rollover post-sunset when the entity is unreliable.

- **Eager weather snapshot** in `update()` — any daylight cycle with a non-unknown weather value updates the snapshot. The existing `blended_live` capture still wins on confident mid-day cycles.
- **Unknown-guard on the `blended_live` capture** — a transient `unknown` at noon no longer locks the day's record to unknown.
- **Defensive log formatting** — the day-record info log no longer crashes on `None` dampening factor.
- 3 new tests pin the gap-closing paths. (by @traktore-org in #416)

### 🩺 Hot-water fail-safe (#420)

`is_temperature_safe()` returned `True` whenever `get_current_temperature()` returned `None`. That conflated "no sensor configured" (trust thermostat) with "sensor configured but broken" (silent failure).

- Split the two paths via `_last_temperature_reading_path`: `no_source_configured` → `no_sensor_configured` → `True`; everything else → `configured_sensor_broken` → `False` (fail-safe). (by @traktore-org)
- 5 new tests pin the fixed branches. Closes #420.

### 🌐 Mobile sem-localize.js delivery

Beta.1 moved `sem-localize.js` from Lovelace resources onto `add_extra_js_url` only. Desktop browsers load both reliably; mobile Companion app does NOT. RienduPre #448: almost every translation key rendering raw on iOS.

- **Dual-channel registration**: now registered as BOTH an `add_extra_js_url` URL AND a Lovelace resource. Same hash-suffixed URL on both channels — browser fetches once. (by @traktore-org)
- **IIFE guard** in `sem-localize.js`: `(function() { if (window.semLocalize) return; ... })()` — defensive second load is a clean no-op.
- Follow-up architectural cleanup tracked in #453 (drop `add_extra_js_url` once `sem-localize-ready` event ergonomics are verified).

### 🩺 Per-section Diagnose surface

- Heat pump diagnose now exposes `heat_pump_activation_path`, `heat_pump_deactivation_path`, `heat_pump_relay_path`, `heat_pump_temperature_reading_path`, `heat_pump_offpeak_path`, `heat_pump_current_temperature`.
- Hot water diagnose now exposes 14 keys covering config + live state + #420 telemetry.
- Tariff diagnose now exposes parser-shape + per-hour distribution counts + first/last price (see Tariff section above).
- Modal opacity fix (beta.2) — was rendering at 6% opacity with cards bleeding through; now solid `--ha-card-background` with `backdrop-filter: blur(6px)`.

### 🐛 Other fixes

- `set_option` service now always reloads (was being swallowed by the skip-reload optimization for runtime stepper tweaks).
- KEBA session_energy pass-through (#449) — new `sensor.sem_charger_<id>_session_energy_external` surfaces the charger's own session counter alongside SEM's internal integration.
- Chart "Today" window now uses HA's timezone (#450) — was browser-local-midnight, drifted on TZ mismatch.
- 3 missing translation keys added (`charger_status`, `forecast_source`, `load_management_status`).
- Dutch translations for 5 new Repair issues (cherry-picked from RienduPre's PR #446 contribution).

### 📚 Docs

- `docs/SETUP_GUIDE.md` section 10 now has a dedicated "Hot water boiler (separate from heat pump)" subsection: config table, two operating modes (with/without temp sensor), fail-safe behaviour, Repair surfaces, and Diagnose troubleshooting.
- `docs/ARCHITECTURE.md` "SEM is not an integration" principle.

### Contributors

Thanks to **@RienduPre** for the persistent reporting on #448 + Discussion #432 — most of the fixes in this release came from his diagnose dumps + Dutch translation contribution.

### Verification

- **3273 tests pass**, 0 fail.
- 24h HA-PROD soak on `1.7.2-beta.7` — zero SEM errors, zero warnings, zero stuck Repairs.
- Live-tested every fix on HA-TEST: heat pump partial-SG-Ready scenario, hot water configure-and-clear flow, tariff parser with synthetic 15-min ENTSO-E sensor, orphan repair sweep with injected stale entry.

# [1.7.2-beta.7] - 08.06.2026

## 🧪 Beta Release

_#454 Phase 2-4: Hot water Repair issues + live-status block + translations + docs._

### 🩺 Hot water Repair issues

Two new self-diagnostic surfaces in Settings → System → Repairs:

- **`hot_water_entity_unavailable`** — fires when the configured boiler-control entity has been `unavailable` / `unknown` / missing for >5 min. SEM stops issuing on/off commands (they'd silently no-op anyway); the Repair surfaces the broken state with a clear "check the upstream integration" message. (by @traktore-org)
- **`hot_water_temperature_sensor_unavailable`** — distinct from the boiler Repair because the safety semantics differ. When a configured temp sensor breaks, `is_temperature_safe()` returns False (post-#420 fail-safe), which means SEM stops activating the boiler entirely. This Repair makes that visible to the user.

Both auto-clear when the entity recovers. Both use the idempotent always-raise/always-clear pattern (no in-memory flags — lesson from beta.2/5).

**Orphan sweep** (new function `clear_orphan_hot_water_repairs`): runs once per coordinator instance, enumerates all `hot_water_*_unavailable_*` issues in the registry, clears any whose entity is no longer in current config. Mirror of beta.5's heat-pump orphan sweep — handles the "user reconfigured the boiler entity, old Repair stuck forever" case.

7 new tests pin: per-Repair raise + clear, distinct issue ids, registry-error defensiveness, orphan sweep with reconfigured entity, orphan sweep with no config at all.

### 🩺 Live-status block on Config tab Hot Water section

Pre-wire-up the Hot Water section was config-only (entity pickers + sliders). Now when the controller IS registered, the section also shows live state:

- Current temperature (formatted to 1 decimal)
- Solar target
- Hours since the last Legionella cycle (or "Never run" / "Cycle running")
- `temperature_reading_path` (which source the controller is reading from: `separate_sensor`, `entity_attribute`, `no_source_configured`, etc.)
- `temperature_safety_path` (when something interesting — initial `uninitialized` hidden)
- `activation_path` (when SEM has actually activated the boiler at least once)

The path attributes surface the #420 audit's runtime telemetry directly in the UI — users can see WHY the boiler activated or didn't on the last cycle without opening the Diagnose modal.

### 🌍 Translations

- 7 new dashboard translation keys for the live-status labels (EN + DE polished; 13 other languages with EN fallback).
- 2 new Repair-issue translation keys in `strings.json` + propagated to all 15 language files. EN polished, DE + NL polished (NL credited to RienduPre's prior translation work).

### 📚 Docs

`docs/SETUP_GUIDE.md` section 10 now has a dedicated "Hot water boiler (separate from heat pump)" subsection covering:

- Config field reference table
- The two operating modes (with vs without temp sensor)
- What happens when the temp sensor breaks (fail-safe behaviour)
- What happens when the boiler-control entity breaks (Repair surfaces it)
- How to use the Diagnose surface for troubleshooting

3273 tests pass. **#454 closes with this release** — all 4 phases shipped:
1. Controller wire-up (beta.6)
2. Repair issues (beta.7)
3. Live-status block (beta.7)
4. Translations + docs (beta.7)

# [1.7.2-beta.6] - 08.06.2026

## 🧪 Beta Release

_Two follow-ups on top of beta.5: the Config tab subtitle bug from #448 + the HotWaterController wire-up (#454)._

### 🐛 Config tab subtitle bug (#448 follow-up)

Looking at RienduPre's diagnose dump, his heat pump IS registered (`registered_sg_ready` + `heat_pump_registered: true`). But the Config tab Heat Pump section subtitle showed "Not configured". Bug class: every card method that read `binary_sensor.sem_heat_pump_registered` was actually doing `_val('heat_pump_registered')` which prepends `sensor.sem_` — the lookup always returned an empty string because the entity is a *binary* sensor.

- New `_bin(suffix)` helper on `sem-config-card.js` reads from `binary_sensor.sem_<suffix>`. (by @traktore-org)
- Converted 3 prior `_val('heat_pump_registered') === 'on'` use sites: subtitle, overview chips bar, Setup overview body.
- Heat Pump section subtitle now correctly reads "configured" when the controller is registered.

### 🔥 HotWaterController is now actually instantiated in setup (#454)

The class existed in `devices/hot_water_controller.py` with full unit-test coverage, the Config tab Hot Water section collected settings, and the dashboard expected the live state — but **the controller was never instantiated**. Setting `hot_water_entity` did nothing at runtime; the boiler was never controlled.

This release closes that loop:

- **`__init__.py` registration block** mirrors the heat-pump pattern. When `hot_water_entity` is set, SEM instantiates `HotWaterController` with the saved options (entity, temp sensor, solar target, max temp, Legionella target/interval, min temp, priority, optional power sensor) and registers it with the `SurplusController`. (by @traktore-org)
- **`HotWaterSensorData`** new dataclass in `coordinator/types.py` with 14 fields covering registration state, current temperature, Legionella tracking, and all 5 `_last_*_path` telemetry recorders from the #420 audit.
- **`coordinator.py:_update_analytics_phases`** populates `hot_water_data` from the registered controller — `get_current_temperature()`, `hours_since_legionella`, the `_legionella_cycle_active` flag, and the runtime decision-branch paths.
- **`CoordinatorSensorData.to_dict()`** publishes all 14 keys into `coordinator.data` so the Diagnose modal + future UI surfaces can read them.
- **`_DIAGNOSE_HOT_WATER_STATE`** in the diagnose slicer now lists actual runtime keys instead of the prior placeholder. Hitting the 🩺 Diagnose button on the Hot Water section returns a payload with concrete state.
- 7 new tests pin: lazy-import presence, `register_device` call, gate keyed on `hot_water_entity`, dataclass field surface, default-unregistered state, `to_dict()` plumbing, diagnose slicer coverage.

**Live-tested on HA-TEST** with `input_boolean` boiler + temp-sensor stand-in: registration fired, temperature read OK (`temperature_reading_path: "separate_sensor"` per #420), all config + state surfaces populated in the diagnose dump.

3266 tests pass.

### What's still pending under #454

- **Repair issues** for boiler entity unavailable / temp sensor unavailable (mirror the heat-pump repair pattern). Not blocking the wire-up but improves the diagnostic surface.
- **Live-status block** on the Hot Water section in `sem-config-card.js` (currently only the intro shows when not configured; needs a registered-state body showing live temp + Legionella status).
- **Translations** for the new hot_water_* state keys + helper labels.
- **Docs**: `docs/USER_GUIDE.md` section + README "Supported devices".

These ship in follow-up betas — #454 stays open until they all land.

# [1.7.2-beta.5] - 08.06.2026

## 🧪 Beta Release

_Hotfix for stuck heat-pump Repair issues from prior config (RienduPre, #448)._

### 🐛 Orphan heat-pump relay repairs now auto-clear (#448)

RienduPre reported (2026-06-08, post-beta.4 upgrade): 2 stuck Repair issues for OLD entity names (`switch.zolder_comfoair_*`) that he'd long since replaced with new ones (`switch.bijkeuken_nibe_sg_ready_*`). The new entities work correctly + the heat pump IS registered (`registered_sg_ready` per his diagnose dump), but the old repairs stayed in the registry indefinitely.

Root cause: beta.2's per-cycle clear path only addresses CURRENTLY-configured entities. Repairs from prior config — whose entity_ids are no longer in `heat_pump_relay1_entity` / `heat_pump_relay2_entity` — were never enumerated, so they sat orphaned.

- **New `clear_orphan_heat_pump_relay_repairs()` sweep** in `coordinator/repair_issues.py`. Enumerates all `heat_pump_relay1_unavailable_*` and `heat_pump_relay2_unavailable_*` issues in the registry and clears any whose entity_id is NOT in the currently-configured set. (by @traktore-org)
- **One-time per coordinator instance** — runs in the heat-pump repair tracking block, guarded by `_heat_pump_orphan_sweep_done` so it doesn't repeat every 10 s. Re-runs after each reload (which creates a fresh coordinator).
- **Idempotent** — safe to invoke against an empty config (sweeps ALL relay repairs), safe to invoke with no orphans (no-op), defensive against issue-registry exceptions.

4 new tests cover the orphan sweep, empty-config sweep, no-orphan idempotency, and registry-error defensiveness. 3259 tests pass.

# [1.7.2-beta.4] - 08.06.2026

## 🧪 Beta Release

_Mobile-only hotfix: translations were rendering as raw keys on the Companion app._

### 🐛 sem-localize.js now loads on mobile (#448 follow-up)

RienduPre reported (2026-06-08, iOS Companion app): almost every translation key on the dashboard rendering as the raw key (`today_plan_title`, `home_sub`, `plan_now`, etc.), not just the new beta-introduced ones. Root cause: beta.1 moved `sem-localize.js` off the Lovelace-resource channel onto `add_extra_js_url`-only. Desktop browsers load both channels reliably; mobile Companion app does NOT pick up `add_extra_js_url` scripts in many cases.

- **Dual-channel registration**: `sem-localize.js` is now registered as BOTH an `add_extra_js_url` (desktop-friendly, loads before Lovelace modules) AND a Lovelace resource (mobile-friendly). Same hash-suffixed URL on both channels — browser fetches once. (by @traktore-org)
- **IIFE guard**: `sem-localize.js` is now wrapped in `(function(){ if (window.semLocalize) return; ... })()` so a defensive second load is a clean no-op. Without the guard, a second `<script>` execution would throw on the second `const _semTranslations = {...}` declaration.
- **Generator updated**: `scripts/regenerate_localize.py` produces the guarded output. The IIFE shape is now self-documenting in the generated file's header.

After upgrade + restart, **clear the Companion app cache** (Settings → App Configuration → Reset frontend cache). The new Lovelace resource registration causes a fresh fetch, and the IIFE-guarded file works whether one or both channels load it.

3255 tests pass.

# [1.7.2-beta.3] - 07.06.2026

## 🧪 Beta Release

_Hotfix on top of [1.7.2-beta.2](https://github.com/traktore-org/sem-community/releases/tag/v1.7.2-beta.2). Tariff timeline + 15-min provider support + diagnostic surface._

### 🐛 Tariff timeline no longer lies on weekends with missing schedule (Discussion #432)

RienduPre reported (2026-06-06, Saturday, Tibber NL dynamic): the bottom "Schema vandaag" timeline showed a solid "Goedkoop" bar for all 24 hours — but the current-classifier card above it correctly showed "Normaal" with 0.3142 EUR/kWh between the configured 0.1/0.3 thresholds. Two code paths, one was lying.

Root cause: `_getTariffSchedule()` in `sem-schedule-card.js` had a hardcoded fallback when `schedule_today` wasn't published:
- Weekday → `[NT 0-7, HT 7-20, NT 20-24]` (CH-shape, wrong for NL)
- Weekend → `[{0..24h, cheap}]` (just labels the whole day cheap)

That weekend branch is exactly what RienduPre's Saturday screenshot showed.

- **New JS fallback**: when `schedule_today` is unavailable, mirror the current `tariff_price_level` across the day instead of pretending we know per-hour data.
- **Visual fallback indicator**: fallback blocks now render at reduced opacity (35%) with a dashed border — users can see at a glance the chart is showing best-effort, not real data. (by @traktore-org)
- Tooltip changes to `<level> (no per-hour data — showing current level)` so the lie is structurally impossible.

### 🌍 Parser now accepts 15-min ENTSO-E + Tibber Pulse shapes (Discussion #432)

RienduPre's prompt — *"his tariff changes every 15 min"* — sent us deep into the parser. Two real gaps:

1. **ENTSO-E attribute shape**: Day Ahead Prices integration uses `prices` (singular) array with `time` + `price` fields. The old parser only checked `prices_today` / `prices_tomorrow` / `today` / `tomorrow` with `start` / `startsAt`. Now adds `prices` + `time` + `hour` to the attribute / timestamp vocabulary.
2. **15-min granularity gap detection**: the parser now records the detected sample interval. Tibber Pulse 15-min API + ENTSO-E 15-min zones (NL, DE) both produce 96 entries/day; the diagnostic surface now reports `tariff_parsed_interval_seconds: 900` so a 15-min vs hourly mismatch is visible at a glance.

5 new tests pin these shapes — Tibber Pulse 96-entry, ENTSO-E `prices` array, `hour` key for template sensors, empty-attribute zero-diag verification, 15-min block-collapsing into chart blocks.

### 🩺 New tariff diagnose fields (#448 follow-up)

The `tariff` diagnose section now exposes WHAT THE PARSER ACTUALLY SAW:

- `tariff_parsed_attribute` — which attribute key matched (e.g. `today`, `prices`, `raw_today`). `null` if nothing matched.
- `tariff_parsed_count` — total PricePoints parsed from the entity.
- `tariff_parsed_interval_seconds` — 900 for 15-min, 3600 for hourly, etc.
- `tariff_today_prices_count` — points for today specifically (after timezone filtering).
- `tariff_today_level_counts` — distribution: `{"cheap": 25, "normal": 50, "expensive": 21}`.
- `tariff_today_first_price` / `tariff_today_last_price` — sanity-check the parsed values.

For RienduPre / anyone hitting "all day cheap": hit the 🩺 Diagnose button on Tariff & pricing, paste the JSON. The fields tell us in one read whether (a) parser didn't recognise the attribute shape, (b) shape matched but timestamps in wrong timezone, (c) shape matched and prices are genuinely all cheap, or (d) percentile mode hit a flat-distribution fallback.

### Research that informed the fix

- [Home Assistant Tibber integration](https://www.home-assistant.io/integrations/tibber/) — official `today` / `tomorrow` with `startsAt` + `total`. 15-min native as of HA 2025.10.0.
- [JaccoR/hass-entso-e](https://github.com/JaccoR/hass-entso-e) — uses `prices` (singular) + `time` + `price`. 15-min for NL/DE zones.
- [jpawlowski/hass.tibber_prices](https://github.com/jpawlowski/hass.tibber_prices) — 100+ sensors, quarter-hourly precision.
- [OdynBrouwer/HomeAssistantTibber](https://github.com/OdynBrouwer/HomeAssistantTibber) — Advanced fork with quarter-hourly + NL solar support.

3255 tests pass, 0 fail.

# [1.7.2-beta.2] - 07.06.2026

## 🧪 Beta Release

_Second beta on top of [1.7.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1) stable. Two structural bug fixes found during live testing on HA-TEST, plus newly-wired telemetry surfaces for heat-pump + hot-water diagnostics._

### 🐛 `set_option` service must always reload (live-test finding)

Configuring `heat_pump_relay2_entity` via `solar_energy_management.set_option` updated the saved options but did NOT re-register the heat-pump controller. The `async_update_options` listener has a skip-reload optimization for runtime number/switch tweaks (intentional, ~1 s downtime saved per slider click) which was accidentally swallowing the `set_option` write too. Result: status sensor showed `not_configured` despite both relay entities being saved, until the next full HA restart. (by @traktore-org)

- `set_option` now explicitly calls `async_reload` after `async_update_entry` so the new config is always picked up. The merge skip stays (no reload when nothing actually changed).
- Caller's next read sees the new state immediately — service awaits the reload.

### 🐛 Repair issues now auto-clear across reloads (also caught live + RienduPre)

`heat_pump_partial_sg_ready` and `heat_pump_relay_unavailable` Repair issues used an in-memory `_raised` flag to track "have we raised this already?" That flag is per-coordinator-instance — reset on every reload. So the moment a user fixed their config (e.g. added the second SG-Ready relay), the new coordinator's flag was False, the `clear_*` call never fired, and the stale Repair stuck in the registry indefinitely. RienduPre also reported the symptom on #432 / #448. (by @traktore-org)

- Removed both in-memory flags. Now always calls `raise_*` / `clear_*` based on current state — both `async_create_issue` and `async_delete_issue` are idempotent so the duplicate calls are harmless.
- Clears any prior issue when a slot's entity is removed from config (was only clearing when the entity was present-but-broken-then-fixed).
- Result: Repair issues correctly mirror live config state across any number of reloads.

### 🩺 Heat-pump runtime path telemetry now visible (#421 follow-up)

The #421 audit shipped `_last_activation_path` / `_last_deactivation_path` / `_last_relay_path` / `_last_temperature_reading_path` / `_last_offpeak_path` recorders on `HeatPumpController` in `v1.7.0-beta.24` (`494fdf9`) — but never wired them through to a user-visible surface. The audit was effectively half-done; the recordings were just internal Python attributes nothing read.

- All 5 path recorders now publish through `coordinator.data` into the diagnose slicer for `heat_pump`. (by @traktore-org)
- New `heat_pump_current_temperature` published too — the live reading the controller uses for safety decisions.
- Diagnose modal on the Heat Pump section now shows every branch the controller took on the last cycle. Concrete vocabulary: `force_on`, `boost`, `boost+climate`, `normal`, `blocked`, `parent_declines`, `already_warm_skip`, etc.

### 🩺 New Hot Water section + diagnose surface

Configuration tab now has a dedicated Hot Water section with entity pickers (boiler control + temperature sensor) and the existing Solar / Max temperature steppers. New `hot_water` diagnose slicer exposes the config so support can see what's set. (by @traktore-org)

- Hot Water section + diagnose button live on every install. (No runtime status block yet — the `HotWaterController` isn't wired into the production surplus loop; that's the next beta.)
- 20 new translation keys (EN + DE polished, 13 other languages with EN fallback).

### Notes for testers

- After upgrade, re-check any stuck Repair issues in HA → Settings → Repairs. They'll auto-clear on the next coordinator cycle if the underlying condition is no longer true. Pre-fix orphaned issues may need a one-time manual dismiss.
- The `set_option` reload fix means structural option changes (entity pickers, mode selects) take effect in ~3 s instead of "next restart" — much better for the Configuration tab editing flow.

# [1.7.2-beta.1] - 07.06.2026

## 🧪 Beta Release

_First beta on top of [1.7.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1) stable._

### 🐛 EV session-energy pass-through + stale-global cleanup (#449)

User report on PROD 2026-06-07: KEBA's `sensor.keba_p30_session_energy` showed **14.61 kWh** but the SEM-published `sensor.sem_charger_ev_charger_session_energy` showed only **0.97 kWh**. Structural disagreement — SEM integrates its own session counter internally (load-bearing for solar-share / cost calcs) while KEBA's is a hardware truth that survives reloads + midnight rollovers.

- **New `sensor.sem_charger_<id>_session_energy_external`** sensor per charger. Passes through the charger's own `ev_session_energy_sensor` (e.g. KEBA's session counter) directly to the dashboard. Auto-converts Wh → kWh based on the source unit. Surfaces the charger's truth alongside SEM's internal integration so users see both numbers and can interpret the difference. (by @traktore-org in #135)
- **v11 → v12 schema migration.** Drops the stale top-level `ev_session_energy_sensor` key left over from the v2 → v3 multi-charger migration. The per-charger value in `ev_chargers[].ev_session_energy_sensor` has been canonical since v3; the top-level copy was harmless but on PROD it pointed at the wrong sensor (`keba_p30_energy_target` — a user setpoint, always 0) and confused diagnostics. Defensive: only drops the top-level when at least one charger has its own value. (by @traktore-org in #135)
- **`config_flow.py` `VERSION` bumped 11 → 12.**

### 🌍 Chart "Today" window now uses HA's timezone (#450)

`sem-chart-card.js:_setDefaultPeriod` previously used `new Date(now.getFullYear(), now.getMonth(), now.getDate())` to compute "Today's midnight" — but that's the **browser's** local midnight, not HA's. When the browser timezone differs from the HA server's (Companion app on a phone roaming across timezones, desktop on a different DST schedule), the "Today" window shifted by 1+ hours. User-reported as the chart timing being "off like an hour or so".

- **New `_startOfDayInHaTz(now)` helper.** Uses `hass.config.time_zone` + `Intl.DateTimeFormat` to compute the absolute Date pointing at HA-local-midnight, regardless of browser TZ. Falls back to browser-local-midnight when `hass.config.time_zone` is unavailable. (by @traktore-org in #136)
- Both call sites in `_setDefaultPeriod` (the `wantToday` start + the `week` Monday-of-week start) updated to use the helper.

### 🩺 Per-section Diagnose slicers (#432 polish)

Beta.17 wired Diagnose buttons into every Configuration tab section but only **Overview** and **Heat Pump** had dedicated key slicers; the other 8 sections used a generic prefix-match. This release adds curated state + option slicers per section so the JSON payload RienduPre (or anyone) pastes back is signal-rich, not noisy. (by @traktore-org in #432)

Dedicated slicers landed for: **EV chargers** (per-charger nested entries via prefix-match on `charger_<id>_*`), **Tariff** (classifier_path + percentile breaks + price curves), **Battery zones** (zone settings + live SOC + health), **Battery scheduler** (capacity / efficiency / pessimism), **Load management** (peak levels + shedding status), **Forecast** (today/tomorrow kWh + source + dampening factor), **Notifications** (toggles + service), **Advanced** (deltas + observer mode).

### 🧪 Tests

- **`tests/test_config_flow_migration.py`** — 2 new v11 → v12 cases: (a) stale top-level dropped when per-charger value exists; (b) defensive — top-level preserved when no per-charger value (don't silently drop a sensor mapping the user may rely on). Existing migration tests updated for the new v12 target.
- **`tests/test_per_charger_seed_migration.py`** + **`tests/test_277_charge_mode_phase_a.py`** + **`tests/test_277_charge_mode_phase_b.py`** — version assertions bumped 11 → 12 (chain still ends at the latest version).
- Full suite: **3 241 pass, 9 skipped, 0 fail** (was 3 239 at 1.7.1).

### 📦 Schema migration

- **v11 → v12** (#449) — drops stale top-level `ev_session_energy_sensor` when at least one charger has its own value. No data loss; per-charger value remains canonical.

# [1.7.1] - 07.06.2026

## 🎉 Stable Release

_Consolidates the 1.7.1-beta.1 through 1.7.1-beta.17 chain into a single stable cut. Soaked overnight on HA-PROD on real hardware (Huawei SUN2000 + LUNA2000 + KEBA P30); no regression vs 1.7.0._

> **Note — issue-reference correction (2026-06-07):** the entry below cites `#446` for the EV `ev_target_type` / estimated_soc fix, but that number is actually an open issue titled "Extra Dutch translations" (unrelated). The retroactive issue for the fix is [#451](https://github.com/traktore-org/sem-community/issues/451). Same applies for the `#135` / `#136` references that originally appeared in the 1.7.2-beta.1 entry — corrected to [#449](https://github.com/traktore-org/sem-community/issues/449) and [#450](https://github.com/traktore-org/sem-community/issues/450). Going forward, GitHub issues are filed BEFORE the fix lands so commit messages cite real numbers.

### 🚀 Headline features

* **Slim install flow** (#442) — 3 steps → 2. EV charger is moved off the install path entirely; users without an EV configured can now finish setup without lying or quitting.
* **In-dashboard Configuration tab** (#442) — every OptionsFlow setting is now editable inline. 10 accordion sections (Setup overview, EV chargers, Battery zones, Tariff, Heat pump, Battery scheduler, Load management, Forecast, Notifications, Advanced), `(?)` help-toggle pattern on every field, auto-save via `solar_energy_management.set_option` + read-back via `solar_energy_management.get_config`.
* **Per-section Diagnose buttons** (#432) — every Configuration tab section gets a 🩺 button that opens a focused JSON modal with **Copy to clipboard**. The user pastes on the discussion → maintainer gets a signal-rich payload instead of the 5 MB full diagnostics dump.
* **One-time onboarding banner** (`sem-onboarding-banner`) — points existing users at the new Configuration tab; localStorage-gated, never shown to new installs.

### 🐛 Stable-quality bug fixes

* **EV charging logic now strictly honours per-charger `ev_target_type`** (#446) — no silent fallback to `estimated_soc` when the SOC sensor isn't configured. v10 → v11 migration auto-resets bad-state entries on first restart; Configuration tab GUI gate prevents new ones. AST lint pins the invariant. Fixes the PROD 2026-06-06 IDLE-stuck-at-120W stall.
* **Reliable home consumption — two-tier hold** (#444) — `_smooth_home_consumption` now uses a 10-cycle transient hold (was 2) plus a separate 30-cycle inconsistency hold triggered when the raw balance goes strongly negative (i.e. physically impossible → guaranteed sensor staleness). Measured on PROD: zero-clamp rate drops from 37 % → 3 % during active charging at variable solar.
* **Bulletproof EV solar-path stability** (#443) — evcc-style stability layer around `_set_current` on the daytime `min_plus_solar` Zone 3/4 path: rolling-median smoothing on `budget_w`, delta guard, time debounce, heartbeat. Stops the KEBA-side current oscillation that aborted EV sessions for Huawei+KEBA users on cloudy days.
* **HA Repairs — graceful unavailability** (#440 / beta.10) — persistent sensor / forecast / recorder problems now surface in Settings → System → Repairs instead of growing the log. Transient sub-5-minute flaps stay completely silent.

### 🔍 Heat-pump observability (#432)

Discussion #432 surfaced a class of bug we couldn't reproduce on our hardware: heat-pump-controller registration silently fails for users with non-standard SG-Ready wiring. **1.7.1 ships the observability tools so users can self-diagnose remotely:**

* **`sensor.sem_heat_pump_registration_status`** — six-string diagnostic sensor + attributes exposing the resolved entity ids + their live HA state (including `entity_missing` when the entity id is set but doesn't exist).
* **Two new Repair issues** — `heat_pump_relay_unavailable_<slot>_<entity_id>` (per-relay, 5 min threshold) + `heat_pump_partial_sg_ready` (singleton, half-config detection).
* **`heat_pump` block in the diagnostics dump.**
* **Failure-path log promoted DEBUG → INFO** at `__init__.py:1137` so users see it in standard HA logs without enabling SEM debug logging.

### 📐 Architectural principle codified (`docs/ARCHITECTURE.md`)

**SEM is not an integration. SEM is an energy-management layer that sits on top of HA integrations.** Kills the temptation to add brand-specific drivers inside SEM. For Nibe SG-Ready specifically, `docs/EV_CHARGING_LOGIC.md §12` now documents both valid wiring paths (physical relays vs HA Modbus template switches) — SEM treats both the same way.

### 🧪 Tests

* **3 239 pass, 9 skipped, 0 fail** (was 3 186 at 1.7.0 — net **+53 tests** across the 1.7.1 betas).
* AST lints locking key invariants: `decide.py` never reads SOC fields (#446), `_calculate_remaining_need` never touches `estimated_soc` (#446), heat-pump failure log stays at INFO (#432).
* New scenario YAML `2026-06-06_target_soc_no_sensor_must_use_kwh` replays the PROD 2026-06-06 setup through the scenario harness.

### 🌍 Translations

* `dashboard/translations.json`: **1 007 keys × 15 languages** (EN + DE polished, others EN fallback).
* `strings.json` + 15 `translations/*.json`: every new OptionsFlow field, Repair issue, and entity name covered.

### 📦 Schema migration

* **v10 → v11** (#446) — entries with `ev_target_type="soc"` on a charger lacking `vehicle_soc_entity` are reset to `"kwh"`. No data loss; existing `target_soc` values sit idle in `entry.options` for users who later wire up a real SOC sensor.

### 🙏 Thanks

Massive thanks to @RienduPre for the persistent #432 reports — they directly drove the observability investment that lets us debug heat-pump issues remotely from now on.

# [1.7.1-beta.17] - 07.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.16](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.16)_

### 🔍 Heat-pump observability — diagnose silent registration failures remotely (#432)

Discussion #432 surfaced a class of bug we couldn't reproduce on our hardware: heat-pump-controller registration silently fails for users with non-standard SG-Ready wiring (ESP relay boards, Shellies, Modbus-bridged template switches for Nibe S-Series). Pre-#432 the user saw "No heat pump configured" on the dashboard with no clue why. The maintainer was guessing at fixes each round-trip. **Beta.17 ships observability tools so users can diagnose remotely — the maintainer reads one screenshot or one diagnostics dump and knows exactly which condition is failing.**

#### What's new

- **`sensor.sem_heat_pump_registration_status`** — diagnostic sensor publishing one of six strings (`registered_sg_ready`, `registered_climate_only`, `registered_sg_ready_and_climate`, `not_configured`, `partial_sg_ready_only_relay1`, `partial_sg_ready_only_relay2`). Attributes expose the resolved entity ids + their live HA state (including `entity_missing` when the entity id is set but doesn't exist in `hass.states`). One screenshot tells the maintainer if the gate logic is wrong OR the entity wiring is broken. (by @traktore-org in #432)
- **Two new Repair issues** at Settings → System → Repairs:
  - `heat_pump_relay_unavailable_<slot>_<entity_id>` — fires when a configured relay entity has been unavailable/unknown/missing for 5+ minutes, naming the specific relay (1 or 2) and entity id. Auto-clears on recovery. Mirrors the `sensor_unavailable` pattern from beta.10.
  - `heat_pump_partial_sg_ready` — fires when exactly one of `(relay1, relay2)` is set without a climate fallback. The SG-Ready protocol encodes its four states as a 2-bit binary across BOTH relays; a single relay can't drive it. Singleton issue (one fix per misconfig), auto-clears when the config becomes valid. (by @traktore-org in #432)
- **`heat_pump` block in the diagnostics dump.** Settings → SEM → ⋮ → Download Diagnostics now includes a `heat_pump` block with `registered`, `registration_status`, `mode`, `sg_ready_state`, `solar_boost`, plus nested `config` (entity ids) and `live` (their HA states). One-click payload for sharing on the discussion. (by @traktore-org in #432)
- **Failure-path log promoted from DEBUG to INFO** at `__init__.py:1137`. Pre-#432 the "Heat pump not configured" line was DEBUG-only, so users never saw it in their normal HA log view. Now it's INFO and includes the actual `relay1` / `relay2` / `climate` config values, symmetric with the success-path INFO. If the user expects registration but sees `None` values, the problem is in the config-flow save; if they see real entity ids, the problem is the entities themselves. (by @traktore-org in #432)

### 🩺 Per-section Diagnose buttons in the Configuration tab (#432)

Built on top of the heat-pump observability above. Every section of the Configuration tab gets a **Diagnose** button next to the section title. Click it → a modal opens with a focused JSON payload (the section's config + live state + last ~20 SEM log lines matching the section's keywords) + a **Copy to clipboard** button. The user pastes the result on the discussion or issue tracker; the maintainer gets a signal-rich payload instead of having to ask for a full 5 MB diagnostics dump.

- **`solar_energy_management.diagnose` service** (`__init__.py`, `supports_response=ONLY`). Takes an optional `section` parameter (defaults to `all`). Returns `{section, payload: {version, entry_id, entry_version, config, state, recent_logs}}`. Phase 1 has dedicated slicers for `all` (Overview) and `heat_pump`; the other 8 sections use a generic prefix-match slice (per-section slicers land in a follow-up beta — the button shell + modal + copy flow are wired everywhere so the user surface is consistent). (by @traktore-org in #432)
- **`<sem-diagnose-button>` Lit element** (`dashboard/card/src/cards/sem-diagnose-button.js`). Self-contained: button + modal + clipboard-write + busy/error states. Pluggable via `section` + `label` props. The Configuration tab's `_renderSectionHeader` mounts one per section with `@click.stop` so opening the modal doesn't toggle the accordion. (by @traktore-org in #432)
- **Architectural design note for follow-up betas:** generic prefix-match slicers stay; we'll add dedicated slicers for the high-value sections (EV chargers, tariff, battery zones) in 1.7.2-beta.1. Each new section just needs a one-liner key set added to `__init__.py`'s slicer map — no extra UI work.

#### Architectural principle codified (`docs/ARCHITECTURE.md`)

**SEM is not an integration. SEM is an energy-management layer that sits on top of HA integrations.** evcc and similar tools bundle brand-specific device drivers (e.g. evcc's `nibe-s-series` template speaks Modbus directly to register 3032). SEM intentionally takes a different shape: it stays in HA's entity-and-services world. The user runs HA's `nibe` / `modbus` / `keba` integration (which owns the protocol), then plugs the resulting entities into SEM via entity pickers.

For Nibe SG-Ready specifically, `docs/EV_CHARGING_LOGIC.md` now documents both valid paths (Path A: physical relays wired to AUX inputs; Path B: HA `template switch` entities backed by Modbus registers via the user's `nibe`/`modbus` integration). SEM treats both the same way — as two `switch` entities — so no protocol code lands in SEM regardless of which the user picks. (by @traktore-org in #432)

### 🧪 Tests

- `tests/test_heat_pump_registration_status_sensor.py` (new, 8 tests) — pins the 6-string state machine plus attribute behaviour for entity-missing and unavailable cases.
- `tests/test_heat_pump_repair_issues.py` (new, 7 tests) — verifies the two new repair types fire with the right issue ids + translation placeholders, are idempotent across relay slots, and swallow registry exceptions without crashing cycles.
- `tests/test_diagnostics_dump_heat_pump.py` (new, 4 tests) — AST-walks `diagnostics.py` to lock the `heat_pump` block + nested `config` / `live` subblocks. Cross-checks `coordinator/types.py` emits the diagnostic fields the dump reads.
- `tests/test_heat_pump_failure_log_is_info.py` (new, 1 test) — AST lint on `__init__.py` to assert the NOT-registered branch logs INFO, not DEBUG. Pins the regression boundary.

Full suite: **3239 pass, 9 skipped, 0 fail** (was 3217 — net +22 after the heat-pump tests).

### 🌍 Translations

- 70 new entries (5 keys × 14 languages): the `heat_pump_registration_status` entity name + the two new Repair issue title/description pairs. EN + DE polished, other 13 languages on EN fallback per the existing convention.

# [1.7.1-beta.16] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.15](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.15)_

### 🐛 EV charging logic strictly honours `ev_target_type` per charger (#446)

**PROD report 2026-06-06:** EV connected, SEM showing *"Charging active"* with `commanded_current = 9 A`, but real KEBA draw stalled at **120 W** with no progress against the day's kWh counter. The user (correctly) called this out as a charging-logic bug rather than a GUI / display problem.

**Root cause traced to `coordinator/coordinator.py:_calculate_remaining_need` (the kWh budget feeding `decide.py:369`).** Pre-#446 logic:

```python
if ev_target_type == "soc" and vehicle_soc is None:          # ← rescue path
    if detector and detector._soc_anchored:
        vehicle_soc = detector.get_virtual_soc(None)         # ← leaks estimated_soc

use_soc = ev_target_type == "soc" and vehicle_soc is not None
if use_soc:
    return max(0, (target_soc - vehicle_soc) / 100 * ev_capacity)   # → view.target_kwh
```

PROD had `ev_target_type="soc"` saved but no `vehicle_soc_entity` configured (a combination the Configuration tab let users save before this release). The rescue path silently substituted the taper detector's `estimated_soc = 89.6 %` into the kWh budget. With `target_soc = 80 %`, `(80 − 89.6) / 100 × 40 kWh` clamped to **0 kWh** → `decide.py:369` returned `IDLE` → KEBA got pilot-off → real draw collapsed to ~120 W. The user's daily kWh counter still had 3 kWh of headroom, but SEM didn't know it.

**Three-part fix per the user's architectural rule "if SOC, then SOC; if kWh, then kWh — no mixing":**

1. **Runtime trusts the saved config (no override).** `_calculate_remaining_need` is now a clean `if ev_target_type == "soc": … else: kwh …` branch. The rescue path is gone — `estimated_soc` never enters the budget. If a real `vehicle_soc` reading is momentarily `None` while in SOC mode, the SOC branch returns the full capacity so SEM keeps charging until taper detection trips (taper is the hard "full" stop). (by @traktore-org in #446)
2. **v10 → v11 schema migration cleans existing bad state.** On the first restart after upgrade, any entry that has `ev_target_type="soc"` (or the legacy `ev_target_mode` field) on a charger without a `vehicle_soc_entity` gets reset to `"kwh"`. Logged via `_LOGGER.info` with a count of fields scrubbed. Bad combinations on disk become structurally impossible. (by @traktore-org in #446)
3. **Configuration tab GUI gate prevents future bad state.** A new "Target type" select widget per charger. The "Vehicle SOC %" option is `disabled` when `vehicle_soc_entity` is empty; help text says *"requires SOC sensor"*. Users with a real sensor can pick either kWh or SOC; users without a sensor can only see kWh. (by @traktore-org in #446)

### 🧪 Tests

- **`tests/test_calculate_remaining_need_no_estimated_soc.py`** (new) — AST lint over `_calculate_remaining_need`. Banned names: `_estimated_soc`, `estimated_soc`, `get_virtual_soc`, `_ev_taper_detector`, `_ev_taper_detectors`. Any future refactor that reintroduces a SOC leak fails CI. (by @traktore-org in #446)
- **`tests/test_decide_no_soc_reads.py`** (new) — AST lint over `coordinator/decide.py`. Banned attribute reads: `target_soc`, `estimated_soc`, `vehicle_soc`. The "decision logic is pure kWh" invariant has been true since #440 but was unpinned; now it's locked. (by @traktore-org in #446)
- **`tests/test_config_flow_migration.py`** — added 3 v10 → v11 cases: per-charger bad-combo reset, legacy `ev_target_mode` cleanup, and the kWh-mode-preserved noop case. Updated 7 existing intermediate-hop assertions to expect version 11 (the new target). (by @traktore-org in #446)
- **`tests/test_minmax_targets.py`** + **`tests/test_ev_target_ux.py`** — deleted 3 tests that pinned the removed rescue-path behaviour; added 2 replacement tests for the new "real sensor + unavailable reading = full capacity" SOC-branch contract. (by @traktore-org in #446)
- **`tests/scenarios/2026-06-06_target_soc_no_sensor_must_use_kwh.yaml`** (new) — replays the PROD 2026-06-06 setup through the scenario harness. Asserts `canonical_strategy` is `battery_assist` (not `idle`) when `ev_target_type="soc"` + no SOC sensor + kWh headroom. (by @traktore-org in #446)
- **Full unit suite: 3217 pass, 9 skipped, 0 fail** (was 3214 — net +5 after the test cleanup).

### 📐 Why this is safe to deploy

- The runtime change is a code-path simplification, not a behaviour change for any user with a sensible config. Installs in pure kWh mode (the default) are unaffected. Installs with a real SOC sensor + SOC mode are unaffected — the SOC math is unchanged.
- The migration is idempotent. v11 entries are noops; v10 entries with kWh mode are noops; only the PROD-2026-06-06-class bad state gets cleaned.
- The GUI gate is purely a UX guardrail. Saved values are still honoured by the runtime; the migration handles legacy data.

### 🌍 Translations

- 5 new dashboard keys for the Configuration tab Target-type select (`config_ev_target_type`, `config_ev_target_type_kwh`, `config_ev_target_type_soc`, `config_ev_target_type_requires_sensor`, `config_help_ev_target_type`). EN + DE polished; other 13 languages on EN fallback. `sem-localize.js` regenerated: 1003 keys × 15 languages.

# [1.7.1-beta.15] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.14](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.14)_

### 🐛 Reliable home consumption — two-tier hold against sensor-staleness skew (#444)

**PROD report:** the system-diagram + energy panels occasionally show `Home = 0 W` for a single-cycle blip during active EV charging, then snap back to a real value. Recorded the behavior live on PROD on 2026-06-06: **16 % of cycles** clamped home consumption to 0 during a 10-min `min_plus_solar` charging window at ~4.25 kW with variable solar (clouds).

Root cause confirmed from the recording: the Huawei modbus inverter + grid meter update every ~13 s (p95 30 s), but the LUNA2000 battery sensor and the KEBA P30 EV sensor both have p95 staleness over **60 s** (max 82 s and 86 s respectively). When solar drops while grid hasn't yet caught up, the raw energy balance briefly goes physically negative (e.g. solar 4 348 W − stale grid_export 4 901 W − stale EV 120 W = **−700 W**). The existing 2-cycle hold (`HOME_HOLD_MAX_CYCLES = 2`) covered ~20 s of these gaps; the slower KEBA + LUNA2000 push gaps blew right past it.

**Fix.** Two-tier hold in `_smooth_home_consumption` (`coordinator/coordinator.py`):

  * **Inconsistency hold (~5 min):** when the raw balance is strongly negative (below the new `SENSOR_INCONSISTENCY_THRESHOLD_W = −100 W` gate), the inputs are guaranteed inconsistent — energy can't actually flow out faster than in. Hold the last positive value for up to `HOME_HOLD_INCONSISTENT_MAX = 30` cycles (~5 min @ 10 s coordinator cycle) while the slow sensor catches up.
  * **Transient hold (~100 s):** when the raw balance is at or near zero (sensor noise around a real low load), keep a shorter hold via the existing `HOME_HOLD_MAX_CYCLES` knob, now bumped from `2` to `10`. A genuinely sustained zero past that window is still reported as real.

Simulated against the 2026-06-06 PROD recording (200 samples × 3 s = 600 s wall, with all four raw upstream sensors + their `last_changed` timestamps captured): drops the zero-clamp rate from **37 %** (single-tier 2-cycle baseline replay) → **3 %** with the two-tier defaults. By @traktore-org in #444

### 🧪 Tests

- `tests/test_home_consumption_smoothing.py` extended to 9 tests (was 5). New coverage: strongly-negative raw balance triggers the inconsistency tier (`test_strongly_negative_raw_balance_uses_inconsistent_hold`), inconsistency tier eventually releases at the cap (`test_inconsistent_hold_eventually_releases`), mild negative raw balance stays on the transient tier (`test_mild_negative_raw_balance_uses_transient_hold`), and recovery resets the counter when sensors agree again (`test_inconsistency_tier_recovers_when_balance_returns_to_zero`). All 5 pre-existing tests still pass with no behavior change for raw-balance ≈ 0 cases. (by @traktore-org in #444)
- Full unit suite: **3214 pass, 9 skipped, 0 fail** (was 3186 — net +28 tests across the recent beta cluster).

### 📐 Why this is safe

The inconsistency tier only fires when the raw balance is strongly negative — a physically impossible state that can only come from sensor disagreement. It does NOT mask real sustained-zero states (no one home, all loads off): those keep `raw_balance` ≈ 0 W, which falls under the transient tier, which still releases the zero after 10 cycles. Equally important, **`HOME_HOLD_INCONSISTENT_MAX` is finite** — even an integration-level outage that holds the raw balance pathologically negative is accepted as real after 5 minutes, so the energy total doesn't get permanently inflated.

# [1.7.1-beta.14] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.13](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.13)_

### 🐛 Stop KEBA solar-path current oscillation that aborts EV sessions

**PROD report (HA-PROD, Huawei SUN2000 + KEBA P30):** EV charging current "goes up and down" so often the car closes the session and stops charging. Worked fine "a few changes ago, like last week". Traced to commit `c30a140` (the #438 commit-then-measure fix): the `min_plus_solar` Zone 3/4 day path was tightened to unconditionally command `max(min_amps, surplus_amps)` every cycle. Correct intent (the EV must draw min to bootstrap battery-assist), but the solar-path `_set_current` call at `coordinator/ev_control.py:519` had no delta or time guard (unlike the night-path call at `:440`). Huawei modbus jitter on PROD (`8 kW → 0 W → 8 kW` across cycles) propagated straight into a new `set_current` value every 10 s — KEBA P30 couldn't handshake fast enough and the car aborted.

This release adds an evcc-style stability layer around the solar-path `_set_current` call. (by @traktore-org in #443)

- **Layer 1 — rolling-median smoothing on `budget_w`.** Window 3 cycles (~30 s), tunable via `ev_surplus_smooth_window`. Drops single-cycle inverter flickers before they reach the amps calculation. Median (not mean) so the outlier is dropped, not averaged in.
- **Layer 2 — delta guard.** Skip `_set_current` when `|target - last_setpoint| < ev_min_change_amps` (default 1 A). The missing parity with the night-path guard at `ev_control.py:440`.
- **Layer 3 — time debounce.** Skip when less than `ev_min_change_interval_sec` (default 30 s) has elapsed since the last issued call. evcc's `guardduration` discipline, applied per-loadpoint.
- **Layer 5 — heartbeat.** After `ev_state_refresh_sec` (default 300 s) of no commands, force a re-send even if Layers 2 / 3 would suppress. Defends against lost commands on transient network blips and stale per-charger state across restarts.
- **Bypass.** `cold_start`, `mode_switch`, `stop`, `stall_recovery`, `deadline` always go through regardless of guards. Safety-critical transitions are never debounced.
- **Audit trail.** Every suppressed call logs a structured `solar set_current suppressed layer=... charger=... target=... last=... dt_since_last_set=... reason=...` line at INFO, so PROD soak can verify the guards are firing with sensible counts.
- **Multi-charger safe.** State lives on `PerChargerContext` (`last_set_amps_ts` + `budget_history` swap surface) so a fleet of N chargers keeps independent guards per loadpoint — `docs/MULTI_CHARGER.md` invariants preserved.

Layer 4 (threshold-time-windows on enable/disable transitions) is the pre-existing `ev_enable_delay_seconds` (60 s) and `ev_disable_delay_seconds` (300 s) at `ev_control.py:495-496` — kept as-is.

### 🧪 Tests

- **`tests/test_ev_solar_stability.py` — 23 new tests** covering: Huawei flicker smoothed (5), delta guard suppress/pass-through (3), debounce window suppress/pass-through (3), heartbeat re-send + reset (2), every bypass reason (4), multi-charger swap correctness (1), audit logging (3), regression guards for #438 + the PROD pattern (2). (by @traktore-org in #443)
- Existing EV-control tests untouched and green: `test_ev_control_fleet_reads`, `test_canonical_ev_budget`, `test_ev_stall_gate_commanded_amps`, `test_multi_charger_canonical_budget` (35/35). The FLEET-READ AST lint still passes.

### 📊 Tunables (config defaults; can be overridden via `ConfigEntry.options` in current beta — a Configuration-tab UI is planned for a follow-up beta)

| Key | Default | Why |
|---|---|---|
| `ev_min_change_amps` | `1` | Matches the night-path floor at `ev_control.py:440`. |
| `ev_min_change_interval_sec` | `30` | evcc-equivalent of guardduration, scaled to per-cycle adjusts. |
| `ev_surplus_smooth_window` | `3` | ~30 s rolling median; drops single-cycle modbus flickers. |
| `ev_state_refresh_sec` | `300` | Heartbeat floor; never let a charger sit without a fresh command for longer. |

### ✅ HA-PROD verification — Configuration tab save pipeline (beta.13 fix)

8/8 fields persisted on PROD via SSH-tunneled service calls (`solar_energy_management.set_option` writes, `solar_energy_management.get_config` reads back). Confirms beta.13's fix for the silent-reject bug in beta.12 holds on real hardware:

| Section | Field | Type | Before | After | Result |
|---|---|---|---|---|---|
| tariff | electricity_export_rate | number | 0.075 | 0.087 | ✓ |
| tariff | tariff_mode | select | static | static | ✓ |
| heat_pump | heat_pump_priority | slider | 4.0 | 5 | ✓ |
| battery_scheduler | battery_capacity_kwh | number | 15.0 | 12.5 | ✓ |
| battery_scheduler | battery_force_charge_negative_price | toggle | True | False | ✓ |
| load_management | warning_peak_level | slider | 4.5 | 4.0 | ✓ |
| load_management | critical_device_protection | toggle | True | False | ✓ |
| notifications | enable_charger_notifications | toggle | (default) | False | ✓ |

All values reverted to their original state after the test. PROD is clean.

### ✅ HA-PROD verification — EV charge-mode walk

Walked every available charge mode on PROD (target raised from 2 kWh → 10 kWh because the daily counter was already at 1.93 kWh, leaving SEM with no headroom; with 10 kWh target the modes had room to actually pull current):

| Mode | Commanded | EV power | State | Verdict |
|---|---:|---:|---|---|
| off | 0 A | 0 W | Solar mode – Charging allowed | ✓ |
| solar_only | 0 A | 0 W | Solar mode – Charging allowed | ⚠ |
| min_plus_solar | 9 A | 3 330 W | Solar mode – Charging active | ✓ |
| always_max | 32 A | 10 480 W | Solar mode – Charging active | ✓ |

3/4 green on real PROD hardware (Huawei SUN2000 + LUNA2000 + KEBA P30). The `solar_only` row is the open question: SEM showed `Charging allowed` but commanded 0 A even with ~6.5 kW solar and battery at 100 %. Most likely the rapid `off → solar_only` transition hit a stall-cooldown window before SEM had a clean surplus reading — `min_plus_solar` (forced 6 A floor) immediately afterward pulled 3.3 kW and `always_max` pulled the full 10.5 kW (32 A × 3 phase). Worth digging into in a follow-up but not a blocker for either the save-pipeline fix or the #443 KEBA stability work.

`solar_plus_cheap` is correctly hidden on PROD because no dynamic tariff is configured.

# [1.7.1-beta.13] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.12](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.12)_

### 🐛 Configuration tab save pipeline — actually works now (#442)

Beta.12 wired up inline editors for every OptionsFlow field, but the underlying `config_entries/update` WebSocket call **silently rejected every option write**: HA reserves the `options` field on that endpoint exclusively for OptionsFlow walks. The UI flashed "✓ Saved" because the client believed the write succeeded; in reality `voluptuous` rejected the payload server-side with `extra keys not allowed @ data['options']` and the value never landed in `entry.options`. None of the inline editors in beta.12 actually persisted anything.

Two new services close the loop:

- **`solar_energy_management.set_option`** (`__init__.py`) — accepts an `options` dict, merges it into the SEM ConfigEntry's `entry.options`, and lets HA's `update_listener` decide whether to reload (the same path the OptionsFlow takes). The Configuration tab now calls this service instead of `config_entries/update`. (by @traktore-org in #442)
- **`solar_energy_management.get_config`** (`supports_response=ONLY`) — returns the merged `data + options` dict the OptionsFlow uses internally. HA's public `config_entries/get` strips `data` and `options` for security, leaving the dashboard with no way to display current values for option-only fields. The card now reads via this service and displays the actual saved values, not just defaults. (by @traktore-org in #442)

### 🧪 Save round-trip harness — 8/8 green

New Playwright harness writes a value to one field per section, asserts:
- save status flashes from "saving" → "✓ Saved" within 400 ms
- new value is readable via `get_config` within 1 s
- revert restores the original value cleanly

Sections covered: tariff (export rate + mode select), heat pump (priority slider), battery scheduler (capacity number + force-charge toggle), load management (warning peak slider + critical-protection toggle), notifications (charger toggle). **8/8 GREEN, zero console errors.**

### 🧪 Unit tests

3186 pass, 9 skipped, 0 fail (unchanged from beta.12).

# [1.7.1-beta.12] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.11](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.11)_

### ✨ Every OptionsFlow step now inline in the Configuration tab (#442)

Beta.11 shipped the Configuration tab framework; beta.12 finishes the migration. **Every field from every OptionsFlow step is now editable directly in the dashboard** — entity pickers, sliders, toggles, selects, text/number inputs. No more page-by-page wizard for any setup task.

- **Heat pump inline setup.** 4 `<ha-entity-picker>` widgets (SG-Ready relays, climate entity, power sensor) + 3 sliders (boost offset, max setpoint, priority). Auto-saves on each change via `config_entries/update` → SEM's `update_listener` reloads the coordinator → `binary_sensor.sem_heat_pump_registered` flips on within ~1s once relays (or just climate) are set. Live status block (mode + SG-ready state) appears above the form once registered. (by @traktore-org in #442)
- **Tariff & pricing inline setup.** Tariff mode select (static/dynamic/calendar) + classification mode select (percentile/static) + 3 dynamic-provider pickers (price/forecast/feedin entity, conditionally rendered only when mode=dynamic) + 4 currency-aware number inputs (import/off-peak/export/demand-charge) + 2 grid-sensor pickers (override the Energy-Dashboard auto-pick) + 2 threshold steppers backed by runtime entities. Single source of truth: `entry.options`. (by @traktore-org in #442)
- **Battery scheduler inline setup.** All 10 fields: enable toggle, capacity number input, max charge power number input, roundtrip efficiency slider, cycle cost number input, pre-charge trigger hour slider, max target SOC slider, min deficit number input, pessimism weight slider, force-charge-on-negative-price toggle. (by @traktore-org in #442)
- **Load management inline setup.** Enable toggle + 3 peak-level sliders (target/warning/emergency) + critical-device-protection toggle + max grid import stepper. (by @traktore-org in #442)
- **Notifications inline setup.** 2 toggles (per-charger + mobile push) + notification-service dropdown built from `hass.services.notify` / `hass.services.rest_command`. (by @traktore-org in #442)
- **Per-charger inline setup.** Each existing EV charger now exposes 4 inline entity pickers (connected sensor, charging power sensor, current control entity, vehicle SOC sensor) plus the existing min/start/capacity steppers. Writes use the nested-list path `ev_chargers[index][key]` via `config_entries/update`. Add/remove a charger still deep-links to HA settings — schema migration on first-charger setup is too nuanced for inline-add in v1. (by @traktore-org in #442)
- **Auto-fetched ConfigEntry id.** Card runs one `config_entries/get` WebSocket call on connect to find the SEM entry; no need to pass `entry_id` via the dashboard YAML config. Caches `entry.data + entry.options` (the same merge the OptionsFlow uses) and re-renders on every save. (by @traktore-org in #442)
- **Save status flash.** Every editable field shows a "Saving…" → "✓ Saved" flash on write, or an error string if `config_entries/update` rejects. Errors stick until cleared. (by @traktore-org in #442)
- **New primitives.** `_renderPicker`, `_renderPickerNested`, `_renderOptionToggle`, `_renderOptionSelect`, `_renderOptionNumberInput`, `_renderOptionSlider` — six small render helpers that any future card can reuse for option-only fields. (by @traktore-org in #442)

### 🌍 Translations

- **73 new dashboard translation keys** for the inline form labels + help text (config_tariff_*, config_bs_*, config_lm_*, config_notif_*, config_ev_*, config_hp_*, config_help_*). EN + DE polished, other 13 languages on EN fallback. `sem-localize.js` regenerated: **998 keys × 15 languages**. (by @traktore-org in #442)

### 🧪 Tests

- Per-section verification harness (Playwright) walks the dashboard, expands every section, counts pickers/sliders/toggles/selects/number-inputs per section, asserts zero JS errors during traversal. Result: 10/10 sections render clean. (by @traktore-org in #442)
- Unit suite: **3186 pass, 9 skipped, 0 fail** (no change from beta.11). (by @traktore-org in #442)

# [1.7.1-beta.11] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.10](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.10)_

### ✨ Slim install flow + new in-dashboard Configuration tab (#442)

Fresh installs now take **2 forms instead of 3**, and every later tweak lives **inside the dashboard** — no more digging through Settings → Devices & Services → SEM → Configure.

- **Install flow stripped to 2 steps.** `async_step_user` (welcome + observer toggle) → `async_step_hardware` (peak limit + diagram style + install dashboard). The EV-charger step is gone from the install path entirely — most users don't have an EV configured on day one and were forced to lie or quit. EV setup now happens **after** SEM is up and running, via the new Configuration tab or HA settings. `_install_defaults()` seeds an empty `ev_chargers: []` list so downstream code is identical. (by @traktore-org in #442)
- **New "Configuration" tab** (`mdi:cog-outline`) sits between Control and Costs. Single `sem-config-card` with 10 accordion sections: Setup overview, EV chargers, Battery zones, Tariff & pricing, Heat pump, Battery scheduler, Load management, Forecast, Notifications, Advanced. Same look + (?) help-toggle pattern as the Control card from beta.7 — every setting carries a one-line explanation that toggles on with one click. (by @traktore-org in #442)
- **Inline edits for everything backed by a runtime entity.** Battery-zone steppers, tariff thresholds, observer-mode toggle, per-charger min/start amps, heat pump boost offset — all live-write to `number.sem_*` / `switch.sem_*` / `select.sem_*` so the change is immediate, no entry reload required. Sections that need entity-pickers (vehicle SOC sensor, tariff entity, heat pump relays, etc.) carry a one-click deep-link to the legacy OptionsFlow as a v1 fallback while the new `<sem-entity-picker>` rolls in. (by @traktore-org in #442)
- **`<sem-entity-picker>` Lit element** (`dashboard/card/src/elements/sem-entity-picker.js`). Thin wrapper around HA's stable `<ha-entity-picker>` that writes selections back via the public `config_entries/update` WebSocket command. Supports both flat options keys and nested `ev_chargers[index][key]` paths. Used by the Configuration tab; ready for power-user cards to compose against. (by @traktore-org in #442)
- **One-time welcome banner** (`sem-onboarding-banner`) shows up on the Home tab for existing users on first dashboard open after the update. Dismissable, persisted via `localStorage` (`sem-config-tab-introduced-v1`), points one click at the new Configuration tab. New installs never see it. (by @traktore-org in #442)
- **OptionsFlow stays intact for power users.** All 9 steps still register so the legacy "Settings → SEM → Configure" path keeps working for anyone who prefers it — and the Configuration tab's "Open in HA settings" buttons deep-link straight to it. (by @traktore-org in #442)

### 🌍 Translations

- **52 new dashboard translation keys** for the Configuration tab + onboarding banner (config_tab_title, config_section_*, config_help_*, onboarding_banner_*). EN + DE polished; other 13 languages use EN as placeholder pending native-speaker review (same convention as beta.6/7/10). `dashboard/translations.json` regenerated to `sem-localize.js`: **910 keys × 15 languages**. (by @traktore-org in #442)
- Install-flow `strings.json` user-step description rewritten across all 15 languages to mention the new Configuration tab instead of "next two steps". (by @traktore-org in #442)

### 🧪 Tests

- New `tests/test_config_flow_slim_install.py` pins (a) the install flow is exactly 2 steps, (b) `_install_defaults()` seeds an empty ev_chargers list, (c) all 9 OptionsFlow power-user steps stay registered so Configuration-tab deep-links never 404. (by @traktore-org in #442)
- `tests/test_dashboard_generator.py` updated for the new tab count (7 → 8) + Configuration path. Full suite: **3186 pass, 9 skipped, 0 fail** (was 3182). (by @traktore-org in #442)

# [1.7.1-beta.10] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.9](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.9)_

### 🚀 HA Repairs — graceful unavailability channel

Honors the HA quality-check feedback "should handle unavailability gracefully instead of spamming". Persistent problems now surface in **Settings → System → Repairs** instead of growing the log.

- **Persistent sensor unavailable** (`coordinator/sensor_reader.py`). New `_sensor_unavailable_since: dict[str, float]` tracks per-entity outage start in monotonic time. After `UNAVAILABLE_REPAIR_THRESHOLD_S = 300` seconds (5 min) the outage stops being "transient flap" territory and a Repair issue files — one entry per sensor in Settings → System → Repairs, severity WARNING, auto-cleared on first successful read. Transient sub-5 min flaps (Huawei modbus over WiFi commonly bouncing every 10-30 s) stay completely silent. (by @traktore-org)
- **No forecast integration** (`coordinator/forecast_reader.py`). Pre-fix, `detect_source()` logged INFO every cycle (~10 s) when no Forecast.Solar / Solcast / custom forecast was detected — log spam. Now: INFO logs once per outage, plus a Repair issue files after **1 hour** of continuous detection failure (gives a legitimate first-boot config window). Both clear automatically when SEM detects a forecast integration. (by @traktore-org)
- **Recorder integration unavailable** (`coordinator/ev_taper_detector.py:async_seed_from_history`). When the HA recorder isn't available, EV intelligence can't warm-start from history. Files a one-time Repair so the user has something actionable in the UI; auto-clears on next successful recorder read. (by @traktore-org)

### 🌍 Translations

- 3 new `issues.*` blocks (sensor_unavailable / no_forecast_integration / no_recorder) added to `strings.json` + 15 language translation files. EN + DE polished; other 13 use EN as placeholder until native-speaker review. (by @traktore-org)

### 🧪 Tests

- New `tests/test_repair_issues.py` (8 tests): threshold gate, recovery clears Repair, idempotent helper exceptions, forecast log-once-per-outage, forecast Repair-after-1h-threshold latching. (by @traktore-org)

# [1.7.1-beta.9] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.8](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.8)_

### 🐛 Bugfix — quiet sensor-recovery log spam (HA quality-check feedback)

- **`Sensor X recovered — now reading Y` demoted from INFO to DEBUG** in `coordinator/sensor_reader.py:1028`. When the upstream hardware flaps (Huawei modbus over WiFi commonly bounces every 10-30 s), the per-sensor recovery line previously fired at INFO for each of the 6+ tracked sensors on every cycle that recovered, spamming the HA log. Now symmetric with the existing DEBUG-level "Sensor X unavailable" log a few lines above — recovery is not user-actionable. Honors community feedback "should handle the unavailability gracefully instead of spamming". No behaviour change: the `_sensor_unavailable` transition tracking still fires, only the log channel changed. (by @traktore-org)

# [1.7.1-beta.8] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.7](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.7)_

### 🐛 Bugfix — #416 forecast records the wrong weather category

- **Mid-day weather snapshot for day-rollover writes** (`coordinator/forecast_tracker.py`). Pre-fix, `_save_day_record()` wrote `self._weather_today` into history at calendar rollover — which fires post-midnight when the HA weather entity reports `clear-night` / `unknown`, not the day's actual weather. Live PROD telemetry on 2026-06-05 confirmed **42 % of forecast records had `weather_category=unknown`**, so the correction cascade kept falling through from `weather × month` → `weather only` → `month only` → `weather=unknown bucket` (last resort). Fix mirrors the existing `_dampening_snapshot` pattern: capture `_weather_today` inside the `_calculate_dampening_factor` confident `blended_live` branch (snapshot taken during the day's actual daylight cycles), then have `_save_day_record()` prefer the snapshot over the live value. Backward-compat: if the day never entered the confident branch (forecast always below `MIN_FORECAST_KWH`, or HA restarted late), falls through to the live value as before. 4 new regression tests in `tests/test_forecast_tracker.py` (`test_416_*`) lock the snapshot + fallback paths. (by @traktore-org, fixes #416 write-time-weather)

# [1.7.1-beta.7] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.6](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.6)_

### 🎨 Inline help toggles — one mechanism across three cards

Discoverable `?` icon on cards where settings benefit from a one-line explanation. Off by default keeps the surface clean; tap to reveal italic descriptions next to each setting.

- **SOC Zones card** (`sem-battery-zones-card.js`) — (?) in the section header. Reveals one-line descriptions for Auto-start / Buffer / Assist Floor / Priority SOC, each with a color-coded left stripe matching its zone marker dot. (by @traktore-org)
- **EV charger card** (`sem-ev-status-card.js`) — (?) in the bottom settings row. Toggles two things together: (1) the 3-line Surplus/Overnight/House-battery mode hint that previously was always visible, (2) per-tile descriptions for Vehicle Start Amps / Min Amps / Vehicle Min Amps / Capacity / kWh-per-100km. Off = compact (selector + deadline + plan strip only). The "Next cheap window" timing line stays visible regardless when in `solar_plus_cheap` (operational info). (by @traktore-org)
- **Control card** (`sem-control-card.js`) — (?) at the top right. Globally toggles inline help for the two eligible sections: Battery Management (Priority / Min / Resume SOC) and Tariff & Pricing (Cheap / Expensive threshold). Other sections unchanged for now. (by @traktore-org)

### 🌍 Translations

- 15 new help strings × 15 languages = **225 entries**. EN + DE polished, other 13 follow the same template (native-speaker review welcome).

# [1.7.1-beta.6] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.5](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.5)_

### 🌍 Translations

- **Heat pump dashboard keys filled in for 14 languages**. `heat_pump_title`, `heat_pump_mode`, `heat_pump_sg_ready_state`, `heat_pump_boost_offset`, and `heat_pump_not_configured` were authored in English in beta.1 but never propagated to the other languages. Users on de/nl/fr/es/it/pt/pl/sv/cs/da/fi/hu/ro/no saw raw translation keys ("heat_pump_title", "heat_pump_not_configured") in the Control tab's Heat Pump section. 70 entries added (5 keys × 14 languages). Native-speaker review welcome. (by @traktore-org)

### 🎨 Polish — Control tab consistency with the EV card

- **Color-accent stripe on expanded sections.** Each Control-card section now shows an inset color-coded left stripe when expanded, matching the section icon (orange = surplus/solar/peak, teal = battery/heat_pump, pink = hot_water, blue = tariff/system). Ties the multi-section settings hub to the EV card's hint-row aesthetic. (by @traktore-org)
- **Typography bumped to match the EV / Battery card tier.** Section titles 14→15px with 0.1px letter-spacing; subtitles 12→13px; body labels (steppers, toggles, select rows) 13→14px; stepper/readonly values 13→14px. Tighter visual rhythm; readable at arm's length on phones. (by @traktore-org)
- **Surrounding cards bumped to the same tier** so the Control tab feels coherent: `sem-load-priority-card.js` (em-based sizes scaled from 0.75-0.9em up to 0.9-1em), `sem-grid-card.js`, `sem-price-card.js`, `sem-costs-card.js`, `sem-energy-impact-card.js`, `sem-battery-zones-card.js` (10→11px and 11→12px label sizes). Same pattern as the solar-card font-polish in beta.5. (by @traktore-org)

# [1.7.1-beta.5] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.4](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.4)_

### 🚀 Renames + polish

- **`night_initial_current` renamed to `initial_current` ("Vehicle Start Amps")** (#441). The "night" prefix on the per-charger session-start ramp current was misleading — the value is applied whenever a charging session begins, not strictly at nighttime. Renamed config key `ev_night_initial_current` → `initial_current` (top-level + per-charger), entity key `number.sem_charger_<id>_night_initial_current` → `number.sem_charger_<id>_initial_current`, display name "Start Amps" → "Vehicle Start Amps" (groups with the new "Vehicle Min Amps" tile from beta.4). Schema migration v9 → v10 renames the field on existing entries; the old number entity is auto-removed by `number.py:_cleanup_stale_entities` on next setup. New `number.py` icon `mdi:car-clock`. Translation strings updated across 15 languages. (by @traktore-org)
- **Solar card font sizes bumped to match other cards** — the PV1/PV2 / Solar Flows Today / Per String / Forecast & Performance card was rendering at 10-11px labels and 11-12px values vs the battery card's 12-13px. Section titles, flow labels, flow values, metric labels/values, and chip labels/values all bumped one tier up for readability. (by @traktore-org)

# [1.7.1-beta.4] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.3](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.3)_

### 🚀 Architectural — charge mode is the sole authority on charging (BREAKING)

- **EV intelligence no longer overrides charge mode.** Pre-#440, `coordinator/ev_control.py:_calculate_forecast_night_target` had two override paths that could zero the user's Min target: a SOC-based skip (`estimated_soc > target_soc → return 0`) and a solar-forecast-based reduction. The mode + Min slider therefore did NOT decide whether to charge — EV intelligence did. Post-#440 the function is a thin pass-through (`max(0, daily_target - daily_delivered)`); the user's mode + sliders are the sole authority. The `%` (SOC) target type is already structurally gated on a real `vehicle_soc_entity` in `select.py:63-65`, so estimated SOC never enters the decision. **Behaviour change**: users in `min_plus_solar` with a sunny forecast tomorrow will now charge the full Min target tonight, where pre-#440 SEM would have skipped some/all of it. (by @traktore-org, fixes #440)
- **Skip-decision wiring deleted.** `calculate_nights_until_charge`, `record_skip`, `reset_skips`, `_consecutive_skips`, the `_skip_recorded_tonight_per_charger` latch, the `notify_ev_charge_skip` / `notify_ev_charge_recommended` notification methods, the `nights_until_charge` / `charge_needed` / `charge_skip_reason` sensor entities (both global and per-charger), and the corresponding "Charge Tonight" / "Nights Until Charge" rows on the EV card are all gone. Existing user automations referencing these entities will break — `binary_sensor.sem_charger_<id>_charge_tonight` and `sensor.sem_charger_<id>_nights_until_charge` become unavailable. The features were never reliable in the absence of a real vehicle SOC; removing is honest. The `EVTaperDetector` now serves display only: `estimated_soc`, `last_full_timestamp`, `energy_since_full`, taper trend, `battery_health_pct`. (by @traktore-org, refs #440)
- **Per-vehicle minimum current** (ADR 0010 pattern 3). New optional per-charger `vehicle_min_current` field captures the car's handshake-floor minimum (e.g. Renault Zoe ~9 A). Effective floor at the decision layer is `max(ev_min_current, vehicle_min_current or 0)` via the new `decide.effective_min_amps()` helper, applied to all `MinPlusSolarMode` / `SolarOnlyMode` branches plus `ev_control._night_initial_amps`. Config-flow charger-edit step gains a slider; the EV card gains a "Vehicle Min Amps" tile in the bottom settings row. Schema migration v8→v9 seeds the field to `None` (= "use the loadpoint `ev_min_current`") for existing entries. (by @traktore-org, refs ADR 0010 #3)

### 🐛 Bugfixes (already on this branch from earlier work)

- **#438 false-full taper anchor.** Pre-fix, an 11-minute handshake-floor oscillation totalling 0.19 kWh satisfied `peak > 3 kW + 3 low samples → _full_detected=True`, anchoring SOC=100 % until physical unplug. Fix: trapezoidal energy integration in `EVTaperDetector.update()` plus a per-vehicle session-energy floor `min(1.0 kWh, capacity × 0.025)` — a 24 kWh LEAF arriving at 99 % SOC can still anchor full (~0.6 kWh threshold); a 0.19 kWh oscillation never can. 6 new regression tests in `TestPerVehicleEnergyFloor` (by @traktore-org, fixes #438)
- **#439 daytime `min_plus_solar` idled instead of supplementing.** Pre-fix, `MinPlusSolarMode._decide_day` gated Zone 3/4 charging on `budget_w < min_w → IDLE`. The budget read `battery_assist_budget_w() = surplus + battery_discharge_w`, but `battery_discharge_w` is the inverter's *currently-flowing* discharge — zero when no EV demand has been commanded yet. Chicken-and-egg deadlock. Fix: commit-then-measure pattern from evcc — drop the gate, offer `min_amps` unconditionally, let the next cycle's sensor readings reflect the actual battery/grid split. `coordinator/decide.py` Zone 3/4 branch now matches the `min_plus_solar` UI promise verbatim. (by @traktore-org, fixes #439)

### 🌍 i18n — structured 3-line mode hints

- **`charge_mode_hint_*` rewritten to 3 structured rows per mode.** The old single-line `charge_mode_hint_solar_only` / `min_plus_solar` / etc. shipped one short clause each — users couldn't tell what a mode actually did for solar, the house battery, and overnight charging. Replaced with `charge_mode_hint_<mode>_surplus` / `_overnight` / `_battery` (15 new keys per language × 15 languages = 225 strings) plus 3 row labels (`hint_label_surplus` / `_overnight` / `_battery`). The battery row substitutes `{buffer}` and `{priority}` placeholders with the user's actual SOC zone values (read from `number.sem_battery_buffer_soc` / `number.sem_battery_priority_soc`) so the hint reads "Drains for EV when home battery SOC ≥ 70 % (buffer). Below 70 % … Below 30 % (priority floor) …" — concrete, not abstract. EN + DE polished manually; other 13 languages follow the same template structure with native-speaker review welcome. Card rendering moves to `.ct-hint-row` flex layout in `sem-ev-status-card.js`. (by @traktore-org)

### 📝 Documentation

- **ADR 0010 — evcc pattern adoption.** Records the architectural choice informing #438, #439, and the per-vehicle min-current pattern. Three patterns adopted in order: commit-then-measure for `min_plus_solar` budget (the #439 fix), pilot-state-gated session lifecycle with a session-energy floor for taper-to-full (the #438 fix), per-vehicle minimum current with three-way max (the new feature this beta). Cites the exact evcc source locations for each. (by @traktore-org)

# [1.7.1-beta.3] - 05.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.2](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.2)_

### 🐛 Bugfixes

- **`binary_sensor.sem_heat_pump_registered` was always `off`** — pre-fix, `coordinator/coordinator.py` populated `heat_pump_registered` via `any(getattr(d, "device_id", "") == "heat_pump" for d in self._surplus_controller._devices)`. `_devices` is a `Dict[str, ControllableDevice]` keyed by device_id, so iterating it yields **keys (strings)**, never devices — and `getattr(string, "device_id", "")` always returns `""`. The check was wired to always be False, so the v1.7.1-beta.1 dashboard auto-hide kept the Heat Pump section hidden even on correctly registered climate-only installs (the exact path RienduPre would have hit). Replaced with the trivial `"heat_pump" in self._devices` dict-membership check. 4 new regression cases in `tests/test_437_heat_pump_climate_only.py` lock the new code and pin the old buggy expression as a counter-example (by @traktore-org, fixes the v1.7.1-beta.1 follow-up surfaced while reproducing discussion #432)

### 📝 Documentation

- **Nibe SG-Ready misconfig demo screenshots** — `docs/screenshots/nibe-sim/` adds 4 reproducible screenshots for discussion #432: config flow heat pump step + Control tab dashboard, under both Path 3 (the broken Nibe enable-flag-switches-as-relays config the other Claude recommended) and Path A (the v1.7.1-beta.1 climate-only config). Reproducible via `/config/packages/sem_sim_nibe.yaml` on HA-TEST (template switches mirroring `switch.sg_ready_heating_48282` / `switch.sg_ready_hot_water_48284` / `climate.vvm_320_heating_circuit` so the demo doesn't need real Nibe hardware) (by @traktore-org, refs #432)

# [1.7.1-beta.2] - 05.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.1)_

### 🐛 Bugfixes

- **Multi-charger Load Priority collision** — pre-fix, `LoadManagementCoordinator.register_ev_charger()` hardcoded `device_id = "load_device_ev_charger"`. The per-charger loop in `__init__.py` called it N times for N chargers — each call overwrote the previous entry in `self._devices`, so the Control tab's Load Priority card showed only ONE EV row even with multiple chargers configured, and peak-shedding only acted on the LAST registered charger. `register_ev_charger()` now accepts `charger_id` + `charger_name` kwargs (defaults preserve single-charger backward compat: `load_device_ev_charger` key unchanged for `ev_chargers[0].id == "ev_charger"`); device dict gains a `charger_id` field for downstream mapping. Reviewer-caught: `features/device_registry.py:_populate_load_manager()` had a hardcoded `!= "load_device_ev_charger"` exclusion that would have silently pruned the new `load_device_ev_charger_1` entries on every registry sync — widened to `startswith("load_device_")`. 7 new tests in `tests/test_436_multi_charger_load_priority.py` covering single-charger legacy key preservation, multi-charger distinct entries, friendly-name fallback chain, idempotent re-registration, and the device_registry prune-survival regression (by @traktore-org, fixes #436)

# [1.7.1-beta.1] - 05.06.2026

## 🧪 Beta Release — first v1.7.1 beta

_Changes since [1.7.0](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0)_

First feature release on top of v1.7.0 stable. Closes the heat pump integration gap surfaced by discussion #432.

### 🚀 Features and enhancements

- **Heat pump climate-only registration** — `__init__.py` registration gate widened from `(relay1 AND relay2)` to `(relay1 AND relay2) OR climate_entity`. Nibe, Mitsubishi, Daikin, and any HA-controlled heat pump that exposes a `climate.*` entity but no SG-Ready relays can now configure SEM's heat pump boost automation. The `HeatPumpController` itself already supported the climate-only path internally (the #421 audit telemetry's `relay_path = no_relays_configured` branch was the proof). Config flow gains explicit two-path description (SG-Ready relays vs climate-only setpoint boost) plus form validation that rejects half-configured SG-Ready (one relay without the other AND no climate fallback). New `error.heat_pump_partial_relays` translation key. Reported by @RienduPre in discussion #432 (by @traktore-org, fixes #437)
- **Heat pump dashboard section** — `sem-control-card` gets a new "Heat Pump" section with mode (SG-Ready+climate / SG-Ready only / climate-only), current SG-Ready state, and the boost offset stepper. Auto-hides when no heat pump is registered using a new `binary_sensor.sem_heat_pump_registered` presence flag (needed because `heat_pump_sg_ready_state` defaults to `2 (NORMAL)` even when no controller exists). New translation keys: `heat_pump_title`, `heat_pump_mode`, `heat_pump_sg_ready_state`, `heat_pump_boost_offset`, `heat_pump_not_configured` (by @traktore-org, refs #437)

# [1.7.0] - 04.06.2026

## 🚀 Stable Release

First stable cut of the 1.7 line. Consolidates the work from 26 beta
releases since [v1.6.17](https://github.com/traktore-org/sem-community/releases/tag/v1.6.17).
Each beta's release notes remain below for the per-fix detail; this
block summarises the themes.

### 🏗️ Architecture

- **FleetCycleState refactor** (beta.7) — single source of truth for fleet-level coordinator inputs; eliminates an entire class of fleet-vs-per-charger read bugs that produced four hotfixes between v1.6.0 and v1.6.6
- **9 Architecture Decision Records** committed under `docs/adr/` (PerChargerContext, EVBudget, sign-convention boundary, home_consumption clamp, per-brand pipeline test, FleetCycleState, real-hass test framework, FleetEvPower newtype, multi-charger priority cascade)
- **`v7 → v8` config schema migration** (#359) — auto-flips stored `tariff_classification_mode` from legacy `static` to `percentile` for dynamic-tariff users on first restart after upgrade

### 🔍 Audit telemetry surfaces — 10 modules instrumented

Following the `classifier_path` pattern introduced in #359, **10 stale modules** now publish decision-path enums as sensor attributes so users can self-diagnose without us reading a debug log. Modules covered: `forecast_tracker` (#416), `hot_water_controller` (#420), `heat_pump_controller` (#421), `pv_performance` (#422), `time_manager` (#424), `consumption_predictor` (#425), `appliance_scheduler` (#426), `utility_signals` (#427), `load_management` (#433), `forecast_reader` (#434). Plus 4 modules audited and closed as no-change (pure data registries + stateless helpers: #423 #428 #429 #430 #431). Pure additive observability — zero behavior change in any of the published numeric outputs. Full framework lives in `docs/AUDIT_PLAYBOOK.md` and `tools/audit_candidates.py`. v1.7.1 then opens for the algorithmic improvements step once 2–4 weeks of real-world PROD telemetry accumulates.

### 🐛 User-reported fixes

- **#359** `tariff_classification_mode` stuck on `static` for dynamic-tariff users → v7→v8 schema migration (beta.21)
- **#384** missing `vehicle_range_entity` + `ev_kwh_per_100km` fields in the Add/Edit Charger flow (beta.21)
- **#404** per-battery power sign + SOC ring readability (beta.18-20)
- **#417** `cheap_price_threshold` / `expensive_price_threshold` max bumped 1.0 → 5.0 to cover high-priced markets (beta.21)
- **#356** ghost charger discovery (per-charger `_flow_` sensors matched as chargers) (beta.10)
- **#378** PV strings i18n fix (beta.8)
- **#383** per-charger `vehicle_soc` sensor (beta.19)
- **#392** KEBA failsafe watchdog heartbeat (beta.14)
- **#400** native `ev_current_control_entity` translations for 12 languages (beta.16, beta.20)
- **#405** battery session hysteresis (1-hour discharge → 2-min bug) (beta.16)

### 🎨 UX

- **Slim config flow** (#397) — 5 essential fields at install; advanced options moved to OptionsFlow. ~30 second setup
- **First-run welcome notification** (beta.15)
- **Per-battery sensors + fleet/per-battery card** (#404)
- **KEBA flicker debounce** (beta.8) — eliminates the on/off oscillation on edge-of-surplus
- **Multi-charger SOC clobber fix** (#383) — per-charger SOC sensor surfaces independent values

### 🙇 Thanks to our contributors

- @RienduPre for the precise `classifier_path` diagnosis on #359, the Add/Edit charger flow gap on #384, the multi-battery sign issue on #404, and weeks of high-signal beta reports
- @zlakes01 for the high-tariff-market signal on #417 and the multi-Easee dashboard report on #415 (under continued investigation)
- Everyone else who filed an issue this cycle — the user reports are what made the audit telemetry necessary AND useful

---

> **Per-beta detail follows. The notes for each `1.7.0-beta.N` below remain unchanged and may be consulted for the granular per-fix changes that rolled up into this stable.**

# [1.7.0-beta.26] - 04.06.2026

## 🧪 Beta Release — v1.7.1 audit batch 4

_Changes since [1.7.0-beta.25](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.25)_

Two more modules audited beyond the original Top-12, picked up by widening the staleness cutoff from 30 days to 2 weeks. Big-module focus on highest-leverage decisions, medium-module full coverage.

### 🔍 Diagnostics

- **#433 `LoadManagementCoordinator`** (1056 LOC, 118 branches — biggest module on the backlog) — **focused** telemetry on the highest-leverage decision points rather than exhaustive attribution. Four new keys on `sensor.sem_load_management_status`: `state_decision_path` (`emergency` / `above_target_shedding` / `warning_zone_keep_shedding` / `warning_zone_clean` / `below_restore_threshold_normal` / `in_hysteresis_band_with_shed_devices_restore` / `in_hysteresis_band_clean_normal`), `process_path` (`disabled_skip` / `state_changed:<old>_to_<new>` / `state_stable:<state>` / `error_caught`), `action_path` (`emergency_shedding` / `progressive_shedding` / `restore` / `no_action:<state>`), plus `last_error` (truncated catch-all exception message — previously this was log-only with no sensor surface) (by @traktore-org, refs #433)
- **#434 `ForecastReader`** — new `get_diagnostics()` method exposing: `source_detection_path` (`custom` / `solcast` / `forecast_solar` / **`none_available`** silent-failure surface — no forecast integration detected), `read_path` (`cold_detect` / `cached_source_valid` / `cached_source_lost_redetected` / `no_source_after_detect` / `read_complete`), `recommendation_path` (`target_reached` / `no_forecast` / `solar_only` / `solar_plus_cheap` / `immediate`), plus `unit_conversion_count` — counts how many of the 3 Solcast kW→W magic-number conversions fired this cycle (by @traktore-org, refs #434)

### 📁 Audit findings

- **Dead-code branch surfaced**: the `in_hysteresis_band_with_shed_devices_restore` path in `_determine_load_management_state` is **unreachable with default config** (target=5.0, hysteresis=0.3, warning=4.5 → restore_threshold=4.7 > warning_level=4.5). Inline comment documents this; future audit can fix the inverted-band config or remove the branch (reviewer-flagged on #433)

# [1.7.0-beta.25] - 04.06.2026

## 🧪 Beta Release — v1.7.1 audit batch 3

_Changes since [1.7.0-beta.24](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.24)_

Third batch of v1.7.1 audit telemetry. Closes the rest of the Top-12 backlog: two modules get telemetry surfaces, four close as no-change (pure data registries + a stateless translation helper that doesn't fit the path-attribute pattern). Pure additive observability, zero behavior change.

### 🔍 Diagnostics

- **#426 `ApplianceScheduler`** — `update_schedules()` now records per-device transition paths on `self._last_transitions[device_id]`, surfaced via `get_schedule_summary()["appliance_transitions"]`. Branches: `no_op` / `device_missing` / `scheduled_to_running` / `running_completed_by_runtime` / `running_completed_by_low_consumption` / **`running_too_short_skip`** (silent-failure surface — fast-cycle appliance under 5 min is treated as transient blip and skipped) / `scheduled_to_missed`. The `scheduled_to_running` branch is preserved when both it and `running_too_short_skip` could fire in the same cycle (caught in testing — `elif not fired` gate). New summary key `appliance_missed_today` (by @traktore-org, refs #426)
- **#427 `UtilitySignalMonitor`** — three new path strings on `UtilitySignalData.to_dict`: `utility_signal_read_path` (**`no_entity_configured`** silent-failure surface — when no entity is configured SEM treats utility-signal as permanently inactive / `entity_missing` / `active` / `inactive`), `utility_update_path` (`signal_started` / `signal_ended` / `signal_continues_active` / `signal_continues_inactive`), `utility_block_path` (`signal_inactive_no_block` / `solar_exempt_partial:N` / `all_blocked`) (by @traktore-org, refs #427)

### 📁 Audit framework

- Closed #428 (`utils/translate.py`) as no-change — pure stateless translation function. The `_load_translations` exception path already logs; the language-fallback and format-error paths are silent-but-benign. Same audit pattern as #423 helpers (by @traktore-org, closes #428)
- Closed #429 (`consts/devices.py`), #430 (`consts/labels.py`), #431 (`consts/sensors.py`) as no-change — pure data registries with 0 decision branches. No behavior to instrument; the audit's structural value for data registries is the data review itself, no findings. Top-12 backlog complete (by @traktore-org, closes #429 #430 #431)

# [1.7.0-beta.24] - 04.06.2026

## 🧪 Beta Release — v1.7.1 audit batch 2

_Changes since [1.7.0-beta.23](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.23)_

Second batch of v1.7.1 audit telemetry — four modules in one beta because they don't share state. Pure additive observability, zero behavior change in published return values.

### 🔍 Diagnostics

- **#421 `HeatPumpController`** — five decision-path attributes on `to_dict` → surfaces via `sensor.sem_load_management_status.devices.<heat_pump_id>`: `activation_path` (boost / force_on, with `+climate` suffix when climate boost composes), `deactivation_path` (normal / blocked / unblocked, with `+climate` suffix), `relay_path` (both_relays / relay1_only / relay2_only / **no_relays_configured** / relay1_failed / relay2_failed — the no_relays_configured branch is the audit's biggest silent-failure surface: SG-Ready state mutates internally but no physical relay actuates), `temperature_reading_path` (sensor / sensor_unavailable / sensor_invalid / sensor_missing / no_sensor_configured), `offpeak_path` (parent_declines / already_warm_skip / activate) (by @traktore-org, refs #421)
- **#422 `PVPerformanceAnalyzer`** — five decision-path fields on `PVPerformanceData.to_dict`: `pv_yield_path` (**no_system_size_configured** silent-failure surface — yield = 0 because size not configured, not because production was zero / computed_with_annual_projection / computed_no_annual), `pv_performance_path` (computed / no_forecast), `pv_clipping_path` (idle / clipping_active / post_clipping_idle), `pv_degradation_path` (insufficient_history / normal / warning / critical), `pv_system_age_path` (computed / no_install_date / install_date_invalid) (by @traktore-org, refs #422)
- **#425 `ConsumptionPredictor`** — new `get_diagnostics()` method exposing five prediction-path enums: `consumption_prediction_path` and `solar_prediction_path` (cold_start_empty / trained_full / trained_with_fallback:N / trained_all_fallback), `surplus_window_path` (no_data / no_surplus / found_window / no_contiguous_window), `ev_prediction_path` (no_data / weekday_match / hour_fallback), `observation_path` (recorded / deduplicated). Plus training-status and sample-count counters (by @traktore-org, refs #425)
- **#424 `TimeManager`** — new `get_diagnostics()` method exposing seven time-of-day paths: `sunrise_source` and `sunset_source` (sun_integration / fallback_default — silent-failure surface when sun.sun is unavailable and TimeManager falls back to hardcoded 06:00/20:30), `sunrise_correction` (none / **next_rising_was_tomorrow** — same class of bug as #416 forecast_tracker, tracking how often it fires / fallback_default_06_00), `night_window_path` (pre_midnight_in_night / post_midnight_in_night / outside_night_window), `night_hours_path` (crosses_midnight / same_day / **parse_failed_fallback_8h**), `meter_day_path`, `offset_parse_path` (by @traktore-org, refs #424)

### 📁 Audit framework

- Closed #423 (`utils/helpers.py`) as no-change. Pure stateless utility functions are an appropriate exception to the telemetry-first rule. The audit playbook explicitly recognizes "current behavior is correct, telemetry surface is sufficient" as a valid audit outcome (Step 7). Future audits of similar pure-helper modules can follow the same default (by @traktore-org, closes #423)

# [1.7.0-beta.23] - 04.06.2026

## 🧪 Beta Release — first v1.7.1 audit

_Changes since [1.7.0-beta.22](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.22)_

First behavioral audit of the v1.7.1 stabilization program (umbrella #419). Pure additive observability on `HotWaterController` — zero behavior change.

### 🔍 Diagnostics

- `HotWaterController` now publishes five decision-path strings on every call, all surfaced via `sensor.sem_load_management_status.devices.<hot_water_id>` — mirrors the #359 / #416 `classifier_path` pattern. New attributes per device: `legionella_path` (idle / natural_achievement / hold_reached_target / hold_in_progress / hold_complete / heating_to_target / overdue_start / overdue_no_sensor), `temperature_safety_path` (no_sensor_assume_safe / in_legionella_cycle_below_target / in_legionella_cycle_at_target / normal_below_solar_target / normal_at_solar_target), `temperature_reading_path` (entity_attribute / entity_attribute_invalid / separate_sensor / separate_sensor_invalid / separate_sensor_unavailable / separate_sensor_missing / no_source_configured), `activation_path` (blocked_unsafe / water_heater / climate / switch_fallback), `deactivation_path` (water_heater / climate / switch_fallback). The biggest silent-failure surface the audit identified — temperature sensor breaks → SEM keeps heating, relying only on the device's internal thermostat — is now visible as `temperature_safety_path = no_sensor_assume_safe` (by @traktore-org, refs #420)
- New `legionella_hold_elapsed_minutes` property — surfaces `5/30 min` style progress against the legionella hold target rather than a binary `legionella_cycle_active` flag. `None` when no hold is in progress (by @traktore-org, refs #420)
- New `hours_since_legionella_or_none` property — disambiguates the existing `999.0` sentinel (which means "never run") from a genuinely very-stale reading. Returns `None` cleanly when no legionella cycle has been recorded yet (by @traktore-org, refs #420)

# [1.7.0-beta.22] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.21](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.21)_

### 🔍 Diagnostics

- Forecast correction and dampening pipeline now publish their decision path as sensor attributes — mirrors the #359 `classifier_path` pattern. `sensor.sem_forecast_dampening_factor` carries `dampening_path` (one of `outside_daylight` / `no_forecast` / `early_morning_floor` / `blended_live`, with `+clamped_high` / `+clamped_low` suffix when the bound fires) plus `confidence`, `live_ratio`, `normalized_ratio`, `pre_clamp`, and `correction_factor_historical`. `sensor.sem_forecast_correction_factor` carries `correction_path` (one of `no_history` / `weather_month_bucket` / `weather_only_bucket` / `month_only_bucket` / `rolling_7d_fallback`, with the same clamp suffix) plus `bucket_size`, `weather_category`, and `history_days`. Lets installs hitting an unexpected ceiling self-diagnose without a maintainer reading the debug log. PROD telemetry on 2026-06-04 showed 35 % of historical correction factors pinned at the post-shrinkage ceiling with no visible signal — this attribute is the signal (by @traktore-org, refs #416)
- Daily history records now persist `dampening_factor`, `confidence`, and `live_ratio` alongside the existing `forecast / actual / weather / factor` fields, captured during the last confident mid-day cycle of each day. Pre-beta.22 records that lack these fields restore as `None` so downstream consumers can distinguish "never recorded" from "recorded as zero" (by @traktore-org, refs #416)

### 🧹 Code hygiene

- Replaced the misleading `Decay toward neutral: 25 % per day — converges in ~7 days` comment with accurate one-shot-shrinkage prose. The historical correction factor is recomputed fresh each ~10 s coordinator cycle — there is no recursive state to decay; the 0.75 weight is a one-shot ridge-regression pull toward neutral 1.0 so noisy short histories don't publish a wild correction. Numeric behaviour unchanged; constant renamed `DECAY` → `SHRINKAGE` (by @traktore-org, refs #416)

# [1.7.0-beta.21] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.20](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.20)_

### 🐛 Bugfixes

- Auto-migrate stored `tariff_classification_mode` from `static` → `percentile` for dynamic-tariff users on schema bump v7 → v8. Percentile became the install default in beta.12 (#373), but entries created before that still carried `static` in storage and silently fired the static-CHF-cutoff branch — visible symptom: `sensor.sem_tariff_price_level` attribute reading `classifier_path=static_fixed_cutoffs` while the live price sat well outside any reasonable static band. Calendar / explicit-static users are untouched (migration gated on `tariff_mode == "dynamic"`). Reported by @RienduPre (by @traktore-org, fixes #359)
- Cheap and expensive price-threshold number entities now accept values up to `5.00` (was `1.00`) to cover high-priced markets — Slovak prices around 1.69 €/kWh were rejected by the upper bound. Reported by @zlakes01 (by @traktore-org, fixes #417)
- Add the missing `vehicle_range_entity` and `ev_kwh_per_100km` fields to the Add Charger and Edit Charger options-flow steps. Both fields existed on the primary `ev_charger` step but were never carried over to the per-charger Add/Edit forms when #397 split the install flow in beta.16 — secondary chargers couldn't configure their own range sensor or vehicle consumption. Reported by @RienduPre (by @traktore-org, fixes #384)

## :bow: Thanks to our contributors

- @RienduPre for the precise `classifier_path` diagnosis on #359 and the Add/Edit charger flow gap on #384
- @zlakes01 for the high-tariff-market signal on #417

# [1.7.0-beta.20] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.19](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.19)_

### 🐛 Bugfixes

- Per-battery power tile no longer strips the sign via `Math.abs()`. The fleet tile shows `−65 W` (signed) while the per-battery tile was showing `65 W` (unsigned magnitude) — same direction badge but contradictory numbers. The underlying `power_w` values agreed (beta.19's per-battery autodetect is doing its job); the display layer was the inconsistency. Now both tiles render the raw signed value end-to-end (by @traktore-org in commit `ad198f1`, refs #404)
- Per-battery SOC ring text was `fill="white"` against the white per-battery section background → invisible on light themes. Now uses the battery accent color with a subtle dark stroke for legibility on both light and dark themes. Reported by @RienduPre (by @traktore-org in commit `ad198f1`, refs #404)

### 🚀 Features and enhancements

- Native `ev_current_control_entity` translations for the 12 remaining languages: fr, es, it, pt, pl, cs, da, fi, hu, ro, sv, no. Closes the last #400 gap — every translation file now carries the field in its own language, joining de + nl from beta.16 (by @traktore-org in #414, closes #400)

## :bow: Thanks to our contributors

- @RienduPre for catching both card-render quirks immediately after the beta.19 deploy — the sign mismatch and the unreadable SOC ring

# [1.7.0-beta.19] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.18](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.18)_

### 🐛 Bugfixes

- Per-battery sign autodetect: when ≥ 2 batteries are configured, each battery now runs the sign-convention detection independently using its own `battery_charge_energy_list[i]` / `discharge_energy_list[i]` counters from the Energy Dashboard. Fleet `battery_power` is rebuilt as the sum of corrected per-battery values, guaranteeing fleet ↔ per-battery agreement by construction. Supersedes the same-flip-for-all approach from #408 which would have broken dual-brand installs (e.g., Sessy + Huawei) where each battery needs an independent flip decision. Single-battery / combined-sensor installs fall back to the legacy fleet-level path via a `_FLEET_BID` sentinel — behaviour identical to today (by @traktore-org in #413, closes #404)

### 🧰 Maintenance and dependency bumps

- 7 new tests in `TestPerBatterySignAutoDetect404` covering independent per-battery state, dual-brand asymmetric flip, both-invert, neither-inverts, fallback without counters, voting threshold, and fleet/per-battery isolation. 4 existing pipeline-test monkeypatches in `test_split_grid_integration.py` updated to use the new dict-keyed state shape (by @traktore-org in #413)

## :bow: Thanks to our contributors

- @RienduPre for the careful diagnostic screenshots that exposed the fleet-vs-per-battery sign asymmetry on his Sessy install

# [1.7.0-beta.18] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.17](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.17)_

### ⏪ Reverts

- Revert PR #408 from beta.17. The fix was based on the assumption that SEM's `_detect_battery_sign` autodetect was flipping the fleet field but leaving the per-battery dict un-flipped — RienduPre's diagnostic screenshots on #404 show the opposite: per-battery is already canonical (`Battery b1 Power = +712 W` → charging ✓) while the fleet sensor (`Batterijvermogen = −712 W`) is the one being wrongly negated. PR #408 would have broken the already-correct per-battery tiles on Sessy installs. Re-investigating the actual root cause as a follow-up (by @traktore-org in #411, refs #404)

### 🚀 Features and enhancements

- Carries forward the temperature-row hide on multi-battery (#409) and the `classifier_path` diagnostic attribute (#410) from beta.17 — both unaffected by the #408 revert

## Known limitation

The #404 per-battery direction bug on Sessy installs is **not fixed yet** in this build — beta.18 only undoes the wrong-direction fix from beta.17. A properly-targeted fix is in flight; see [#404](https://github.com/traktore-org/sem-community/issues/404).

## :bow: Thanks to our contributors

- @RienduPre for the careful screenshots that made the revert obvious

# [1.7.0-beta.17] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.16](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.16)_

### 🐛 Bugfixes

- Battery card top tile no longer shows the temperature of one arbitrary battery on multi-battery installs — temperature row only renders when exactly one battery is configured. The per-battery list below already shows the correct values; the top-tile temperature was confusing because it was a fleet `max()`. Reported by @RienduPre with a 2-Sessy-battery install where the top tile temperature stayed pinned at one battery's reading (by @traktore-org in #409, closes #404)
- Battery-sign autodetect now flips each battery in the per-battery `PowerReadings.batteries` dict, not just the fleet-summed `battery_power` field — fixes a 2-Sessy regression where the per-battery list showed the wrong charge/discharge direction even though the fleet sensor was correct. Brand-agnostic fix in `sensor_reader.py` (by @traktore-org in #408, closes #404)

### 🚀 Features and enhancements

- New `classifier_path` attribute on `sensor.sem_tariff_price_level` documents WHICH branch of the tariff classifier produced the current `price_level`. Path string is one of: `percentile_active(p10=..,p25=..,p75=..,p90=..,n=..)` (happy path), `percentile_fallback_cache_empty`, `percentile_fallback_too_few_prices(n=..)`, `percentile_fallback_flat_day(spread=..)`, `static_fixed_cutoffs`, `static_ht_nt`, `calendar_schedule`, or `negative_price_shortcircuit`. Lets users in cold-start / wrong-attribute-shape / derivative-template setups self-diagnose why their level stays on `normal` (by @traktore-org in #410, refs #359)

### 🧰 Maintenance and dependency bumps

- 4 regression-lock tests in `test_per_battery_loop_375.py::TestPerBatteryDirectionStatus404` pin down the per-battery direction/status logic in `coordinator/types.py:1077-1087` (by @traktore-org in #407, refs #404)
- 4 regression-lock tests in `test_battery_sign_detect.py::TestPerBatteryDictGetsAutodetectFlip404` prove the per-battery dict gets flipped alongside the fleet field on negate-detected installs (by @traktore-org in #408, refs #404)
- 10 new tests in `test_tariff_percentile_359.py::TestClassifierPathDiagnostic` cover all 9 classifier-path strings + the end-to-end TariffData → coordinator → sensor round-trip (by @traktore-org in #410, refs #359)

## :bow: Thanks to our contributors

- @RienduPre for the multi-battery temperature-row report (#404) — exactly the kind of "looks wrong on 2 batteries" feedback that's hard to catch on a 1-battery test install

# [1.7.0-beta.16] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.15](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.15)_

### 🐛 Bugfixes

- Percentile tariff classifier no longer silently falls back to the CHF-calibrated static cutoffs (`< €0.15 = cheap`, `> €0.35 = expensive`) when today's price array is empty (cold start), too small (< 4 prices), or perfectly flat — returns `NORMAL` instead. RienduPre's Tibber NL install was reporting €0.30 as `normal` for hours after restart because €0.30 < €0.35 in the silent fallback. Validated via the synthetic-data reproduction script (`/tmp/sem-359-repro.py`, 5 scenarios) (by @traktore-org in #403, closes #359)
- Battery session hysteresis: a 1-hour continuous discharge no longer rolls over to a fresh 2-minute session every time the inverter rebalances. `POWER_THRESHOLD` 50 W → 200 W (dead-band wider than inverter idle drift); `IDLE_CYCLES_TO_END` 3 → 18 cycles (~3 min — covers cloud transits and sunset transitions); single-cycle opposite-direction blips no longer end the session (requires 3 consecutive opposite cycles) (by @traktore-org in #406, closes #405)
- `de.json` ev_charger config-flow step translated to native German end-to-end — title, description, 8 labels, 8 descriptions. Closes the PR #388 "out of scope" deferred sweep (by @traktore-org in #402, refs #400)
- `nl.json` `ev_current_control_entity` label + description translated to native Dutch — closes the PR #390 English-placeholder gap that hit RienduPre's Wallbox setup directly (by @traktore-org in #402, refs #400)

### 🚀 Features and enhancements

- Slim config-flow screenshots embedded in `docs/SETUP_GUIDE.md` step 1 / 2 / 3, plus a new "First-run welcome notification" subsection documenting the `_welcome_notification_fired` one-shot behaviour from #397 (by @traktore-org in #401)
- `docs/SETUP_GUIDE.md` gains a "Price classification" subsection under Tariff and Pricing settings — explains percentile vs static modes + the cold-start NORMAL behaviour so users on non-CHF tariffs see the documented behaviour first instead of filing #359 again (by @traktore-org in #403)

### 🧰 Maintenance and dependency bumps

- 7 tests in `tests/test_tariff_provider.py` updated to pass `classification_mode="static"` explicitly — they were asserting the static-cutoff bucketing but constructing a percentile-default provider, only passing because of the silent CHF fallback we just removed (by @traktore-org in #403)

## Known follow-ups under #400

13 other languages (fr, es, it, pt, pl, cs, da, fi, hu, no, ro, sv) still carry English placeholders for `ev_current_control_entity`. Native translations welcome on a per-language basis.

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org, @RienduPre (for the diagnostic-data thread that exposed the percentile classifier's cold-start path)

# [1.7.0-beta.15] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.14](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.14)_

### 🐛 Bugfixes

- Config flow step 2 (EV charger) slimmed from 16 fields back to 5: 8 per-charger tunables from PR #390 reverted to OptionsFlow where they belong by design. `ev_current_control_entity` stays for Wallbox-style chargers (by @traktore-org in #398, closes #397)

### 🚀 Features and enhancements

- First-run persistent notification with dashboard deep-link + 3-item checklist; gated to one-shot per install via `_welcome_notification_fired` options flag; skipped on `observer_mode` (by @traktore-org in #398, refs #397)
- ADR 0002 split into 0002 (data-model: `EVBudget` unification) + 0009 (distribution: multi-charger allocation) — each ADR now accurate to its scope (by @traktore-org in `aca2a00`)
- ADRs 0006-0008 added: real-hass test framework, dashboard bundle architecture, and the architecture-record meta-decision (by @traktore-org in #396)
- `CONTRIBUTING.md` test pyramid updated from 3 layers to 4 (unit / scenario / **real-hass** / live), referencing ADR 0007 (by @traktore-org in `aca2a00`)

### 🧰 Maintenance and dependency bumps

- ADR code-link drift fixed in 0002 + 0004 — references the actual function/file anchors now (by @traktore-org in #396)
- First 5 ADRs (0001-0005) added in `docs/adr/` — PerChargerContext, EVBudget unification, sign convention boundary, home_consumption_power clamp, pipeline-test-per-brand mandate (by @traktore-org in #394, kept in #395)

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org

# [1.7.0-beta.14] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.13](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.13)_

### 🐛 Bugfixes

- KEBA failsafe watchdog drop after steady-state charging: same-value `set_current` writes now refresh past a 60 s heartbeat window so the device watchdog stays alive. Generalised to all current-controlled chargers (by @traktore-org in #393, closes #392)
- Same-value heartbeat write also re-converges device-side and SEM-side state after silent device resets (replug fallback, KEBA reboot, failsafe trip) — no more "SEM thinks 16 A, KEBA at 6 A, stuck forever" mode (by @traktore-org in #393)

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org

## [1.7.0-beta.13] — 2026-06-03

The **#359 percentile classifier follow-up**.

### Fixed

- **#359** (PR #391) — RienduPre reopened #359 with screenshots showing
  €0.30 still labelled `normal` / `cheap` after the percentile fix
  shipped in beta.3. Root cause: `_get_percentile_breaks` and
  `get_tariff_data` filtered today's prices with a bare
  `p.timestamp.date()`. Providers differ on the tz they emit — Tibber
  is local, Nordpool-class integrations (incl. several Dutch dynamic-
  tariff implementations) are often UTC. On +02:00 (Europe/Amsterdam
  summer), a UTC-tagged price at 22:00 UTC = 00:00 local-next-day,
  and a bare `.date()` returns the UTC date. Today's filtered array
  dropped below the 4-point minimum, percentile breaks returned
  `None`, and the classifier silently fell back to the static
  €0.15 / €0.35 cutoffs — where €0.30 < 0.35 = `normal`. Exactly the
  symptom.

  Fix: new `_local_date(timestamp)` helper converts via
  `dt_util.as_local` for tz-aware datetimes and passes naive
  datetimes through unchanged (keeps the existing tariff tests, which
  mock `dt_util` and build naive clocks, green without modification).

### Added

- **Tariff diagnostics** (PR #391) — three DEBUG log lines under the
  `tariff/#359` tag so a repro is now trivial:
  - `percentile fallback — today's price array has X/Y points` when
    the array drops below the 4-point minimum (the typical failure
    mode pre-fix).
  - `degenerate distribution — p90-p10=X` when the M1 flat-day guard
    trips.
  - `percentile breaks for <date> — p10/p25/p75/p90` on the happy
    path so users can sanity-check the math against their tariff.

## [1.7.0-beta.12] — 2026-06-03

Per-charger refinements + EV config-flow parity. Bundles the
undocumented beta.11 (#355 affordance) so the changelog is complete from
beta.10 to beta.12.

### Fixed

- **#383** (PR #385) — In multi-charger installs every per-charger card
  showed the same vehicle SOC. The coordinator was overwriting one
  shared `_cycle_vehicle_soc` from each charger's `vehicle_soc_entity`
  inside the per-charger loop; the global sensor reported whichever
  charger ran last, and the card's `_val('charger_<id>_vehicle_soc') ??
  _val('vehicle_soc')` lookup chain always fell through to the global.
  Now publishes per-charger SOC via `charger_<cid>_vehicle_soc`, with
  the unconfigured case returning `None` (not a fabricated zero).

- **#384** Part 1 (PR #388) — The "Add EV Charger" options-flow step had
  translation coverage for only two fields (Solar charge limit kWh /
  SOC%); the rest of the form fell back to the raw key on non-English
  installs. Mirrored `ev_charger_edit` `data` / `data_description` into
  `ev_charger_add` for all 15 languages.

- **#384** Part 2 (PR #390) — The initial setup flow couldn't configure
  Wallbox-style chargers (number entity for current control) because it
  lacked `ev_current_control_entity`. The user had to finish setup with
  a partial config and then drop into Options → Edit. Initial flow now
  exposes the full per-charger override set: `ev_current_control_entity`,
  `ev_surplus_priority`, `daily_ev_target` + `_max`,
  `ev_night_initial_current`, `ev_min_current`, `ev_target_soc` + `_max`,
  `ev_battery_capacity_kwh`. `_EV_KEYS` bridge extended so they migrate
  into `ev_chargers[0]`. `vehicle_soc_entity` deliberately stays in
  OptionsFlow only — asking on install creates a dead input for users
  without a vehicle SOC sensor.

- **EV stall detector** (PR #389) — Detector was anchoring SOC=100% even
  in cycles where SEM had never commanded charge, producing false-stall
  alerts when the EV was simply sitting fully-charged with the cable
  plugged in. The anchor now requires a SEM-issued charge command.

### Added

- **Per-battery sensors + fleet/per-battery card** (PR #386 — Phase A + B)
  — first cut of a multi-battery model. Adds per-battery state, energy
  and power sensors, plus a dashboard card that shows fleet totals and
  per-battery detail.

- **Battery card session duration** (PR #387) — sessions over 90 minutes
  are shown as hours (`2h 15m`) instead of `135m`, matching how users
  think about long battery discharges.

- **#355 split affordance on stacked range handles** (PR #380) — a
  tappable split (↔) icon appears whenever the Min/Max handles of the
  EV target range slider visually overlap (within 2 % of the slider
  span). One tap drops Min by 2 % so the stacked handles become
  individually grabbable. Works in kWh and SOC % modes.

- **`per_charger: true` on `sem-chart-card` EV preset** — optional
  per-charger color breakdown driven by discovered
  `sensor.sem_charger_<id>_power` entities.

### Changed

- **EV chart "today" period** (in PR #380) — was rolling 24h, which
  painted yesterday-evening charges as a phantom second event. Now
  anchored at local midnight to match `daily_ev_energy`.

### Removed

- Per-charger **"Set target as default"** button (PR #380). HA's
  number-entity state restoration already persists slider values across
  restarts; the button's "copy to global defaults" workflow was niche on
  installs that grow new chargers later. Existing entries are
  auto-cleaned on the next setup.

## [1.7.0-beta.10] — 2026-06-02

The **#356 ghost-charger** fix.

### Fixed

* **#356** — EV / charger status cards rendered ghost sections per real
  charger, appearing as duplicate cards titled `<Charger Name> Solar → EV`,
  `<Charger Name> Grid → EV`, `<Charger Name> Battery → EV`. Each ghost
  duplicated the SOC gauge, charge target slider, mode dropdown and
  `Klaar om` timer — only the power value differed, matching the per-flow
  attribution.

  Root cause: the charger auto-discovery regex in both
  `dashboard/card/src/cards/sem-ev-status-card.js` and
  `sem-charger-status-card.js` was greedy:

  ```javascript
  const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
  ```

  It matched both real charger sensors (`sensor.sem_charger_<id>_power`)
  AND the per-charger flow sensors
  (`sensor.sem_charger_<id>_flow_solar_to_ev_power` etc.). The flow
  sensors were added in v1.6.9 (`feature/169-per-charger-flows`) for the
  flow card — they were never meant to register as chargers. Every
  multi-charger install where `sensor.py:1633-1695` emits flow sensors
  (gated on `len(ev_chargers) > 1`) got 3 ghost sections per real charger.

  Fix: `if (eid.includes('_flow_')) continue;` guard before the regex
  match in both card files. Bundle rebuilt — content-hashed resource URL
  invalidates browser cache on upgrade.

  Earlier #356 fixes (`e733212` PR #371 hero-collapse, `68cee34` M3
  bottom-bar gate) targeted a different (real but smaller) duplication
  pattern inside one card; they couldn't address the ghost-section
  cascade because the source was upstream in the discovery loop.

### Tests

`tests/test_356_charger_discovery_filter.py` — source-level lint
asserting both card files contain the `_flow_` guard inside the
discovery window, plus a property-style test feeding sample entity IDs
through the regex+guard combination to confirm flow sensors are rejected
and real charger IDs (including those with legitimate underscores like
`laadpaal_links`, `ev_charger`, `keba_p30`) still resolve correctly.

**Total suite: 2904 passed, 0 failed, 0 xfailed.**

## [1.7.0-beta.9] — 2026-06-02

**Hotfix on top of beta.8.** No SEM logic changes — purely a dashboard
card render bug + a missing translation. Users who installed beta.8 saw
an invisible `sem-solar-card` (the bug below) and a raw key
`PV_STRINGS_TODAY` in the per-string section.

### Fixed

* **sem-solar-card was rendering as a 0x0 element on every viewport.**
  The `html\`...\`` Lit template at `sem-solar-card.js:406` contained
  literal backticks (markdown-quoted `nothing`). JavaScript read those
  as terminating the outer template literal — Lit's minified `html` tag
  threw `H(...) is not a function` at parse time. HA's lovelace renderer
  swallowed the console error and left an empty shadowRoot, so the card
  was conspicuously missing on mobile.
* **Missing `pv_strings_today` translation.** The per-PV-string section
  title rendered as the raw key `PV_STRINGS_TODAY` (CSS upper-casing the
  missing key) instead of the translated string. Added to all 15
  supported languages.

Both fixes target the bundled card (`dashboard/card/dist/sem-cards.js`
was rebuilt) — they take effect after the next browser cache-bust on
upgrade.

## [1.7.0-beta.8] — 2026-06-02

The **disagreement-audit close-out + KEBA solar-flicker resilience** release.
Lands every remaining item from the post-#349 umbrella audit (#351 — 13/13
closed), the KEBA actuator IDLE debounce that prevents transient solar-sensor
dropouts from cascading into "authorization rejected", and a multi-inverter
PV-strings discovery fix surfaced by @RienduPre's #378 dump.

### Fixed

* **#351 H1** — Per-charger `_calculate_remaining_need` now reads
  `self._daily_ev_per_charger.get(cid, energy.daily_ev)` when `charger_cfg`
  is set. Pre-fix charger B's "target reached" check was polluted by
  charger A's energy.
* **#351 H2** — Forecast night-target reduction applied per-charger inside
  the multi-charger loop, gated on `_mode_uses_smart_night(cfg)`. Secondary
  chargers no longer ignore the "tomorrow is sunny → skip tonight" decision.
* **#351 M1** — Cost accumulators (daily / monthly / yearly) now round-trip
  through `Storage.export_energy_calculator_state`. Pre-fix `daily_savings`
  silently reset to 0 mid-day after every HA restart while
  `daily_solar` resumed from disk.
* **#351 M2** — `CostData.daily_total_savings` (+ monthly / yearly variants)
  now computed as the headline number spanning solar + battery savings.
  Pre-fix `daily_savings` (solar-only) was the only surfaced number and
  understated savings on battery-assist days.
* **#351 M3** — Per-charger session reads `power_flows.per_charger[cid]`
  directly when populated, preserving the priority-correct attribution.
  Pre-fix the proportional re-split discarded the priority signal that the
  flow calculator just computed.
* **#351 M4** — Per-charger effective states surface as
  `charger_<id>_charging_state` on `coord.data` and as the
  `per_charger_states` dict on the `sem_charging_state` sensor. Mixed-mode
  fleets now show the disagreement explicitly instead of hiding behind the
  fleet headline.
* **#351 M5** — `SurplusController.distribute_ev_budget` accepts an
  `excluded_charger_ids` set; chargers in `charge_mode=off` get 0 W
  allocation (dashboard still sees the entry).
* **#351 M6** — `notify_ev_nearly_full` gates on this charger's
  `power.ev_power_per_charger.get(cid)` instead of the fleet `ev_charging`
  flag.
* **#351 M7** — Per-charger session-end falls back to
  `power.ev_connected_per_charger.get(cid)` when no per-charger plug
  sensor is configured. Pre-fix per-charger sessions could never end while
  another charger was plugged in.
* **#351 M8** — `_skip_recorded_tonight` converted to
  `Dict[str, bool]` keyed by charger_id; per-charger intel builder
  records skips per-charger so charger A's skip no longer masks
  charger B's independent counter.
* **#351 M9** — Eliminated mutable-attr-read pattern in
  `_build_charging_context` and the per-charger loop. Both call sites
  now capture `self._cycle_vehicle_soc` into a local before the two
  `_calculate_remaining_need` calls.
* **#351 M10** — `SOLAR_PAUSE_STATES` clears `_ev_charge_started_at`.
  Pre-fix the disable-delay timer was consumed during a battery-priority
  pause and the very next cycle's terminal branch fired stop_session
  even though we just resumed.
* **#351 M11** — Night-skip notification gates on
  `_mode_allows_night_charging(cfg)`. Modes `off` / `solar_only` no longer
  get spurious "skipped night charge" pushes.
* **#351 L1** — `_update_battery_session_tracking` integrates against
  `self.update_interval.total_seconds()` (the actual cycle time) not
  `config["update_interval"]` (the requested one). Under HA load the two
  diverge and the battery-session counter drifted.
* **#351 L2** — `FlowCalculator.calculate_energy_flows` emits
  `DeprecationWarning` from the body. The proportional-allocation path is
  un-canonical; `integrate_energy_flows` is the timing-aware production
  path.
* **#378** — `discover_pv_strings_from_registry` now honours the explicit
  `solar_power_list` from the HA Energy Dashboard when it has ≥2 entries.
  Pre-fix the discoverer scoped sibling-scan to the seed's `config_entry`,
  silently dropping cross-inverter MPPTs and leaking entities not in the
  user's dashboard. @RienduPre's multi-inverter setup (3 entries in
  `solar_power_list`) now surfaces all 3 as `pv1`/`pv2`/`pv3`.

### Added — KEBA solar-flicker resilience

* **IDLE debounce in the actuator** (`coordinator/actuate.py` +
  `ChargerAdapter.attempt_idle` + `reset_idle_debounce`). When a transient
  solar-sensor reading triggers a 1-cycle `intent=idle`, the actuator
  holds the previous setpoint instead of immediately calling `keba.disable`.
  Default threshold = 4 cycles (~40 s grace). Catches the pattern observed
  live on PROD 2026-06-02: Huawei sensor flicker 8 kW → 0 W → 8 kW within
  10 s → `keba.disable` → KEBA stuck in "authorization rejected" until
  physical replug. Real cloud passes (>40 s) still cross the threshold and
  `command_idle` fires normally.
* Debounce state lives on `ChargerAdapter` (per-charger, not a module-level
  dict) so multi-charger fleets count independently per charger.
* INFO-level log on both branches:
  `actuate(<cid>): IDLE — count=N/4 — <reason>` (fired) or
  `actuate(<cid>): IDLE DEBOUNCED — count=N/4, holding previous setpoint`
  (absorbed).

### Tests

* `test_351_umbrella_regression.py` — 23 tests covering every umbrella
  item (per-fix assertions + structural anchor lint).
* `test_379_growatt_pv_strings.py` — 3 new tests for #378 (multi-inverter
  list wins, single-entry falls through, empty list preserves legacy).
* 3 new edge-case scenarios + harness extensions for per-cycle
  `tariff_level` and the negative `strategy_not_substring` assertion.

**Total suite: 2900 passed, 0 failed, 0 xfailed.**

### Known not-fixed

* **#356** — duplicate tiles in the EV dashboard. @RienduPre confirms the
  symptom persists on beta.6 (which has the hero-collapse + bottom-bar
  fixes). Needs a UI screenshot to identify the remaining duplication
  source — replied on the issue asking for one. Target beta.9.
* **Solar sensor flicker root cause** — the actuator debounce is a
  band-aid. The Huawei inverter's intermittent 0 W readings should be
  EMA-smoothed in `coordinator/sensor_reader.py`. Separate issue worth
  filing.

## [1.7.0-beta.7] — 2026-06-02

The v1.7 arch capstone — the **FleetCycleState refactor** that
structurally retires the gap class behind the three production fixes
shipped in beta.5 (SOLAR_ONLY redirect, tariff_level, night-plan
ordering). Plus 4 more transition-class scenarios.

### Production refactor — FleetCycleState as single source of truth

The three beta.5 production fixes were tactical patches for one
structural smell: `build_charger_view` had each call site
re-resolving fleet-level inputs (forecast, tariff, is_night, etc.)
independently. The primary view in `_build_charging_context` and
the multi-charger loop each handled this differently — and any
new fleet input added would land in only one of them.

The fix: **`FleetCycleState`** — an immutable per-cycle struct
holding every fleet-level input that any charger's `decide()` could
need. Built ONCE per cycle by
`coordinator._build_fleet_cycle_state`. `build_charger_view` now
takes it as the first positional arg and derives the per-view
`FleetContext` from it. Per-charger overrides (`target_kwh`,
`deadline_amps`, `tariff_wait`, `solar_committed_w`) stay as direct
kwargs because they legitimately vary across chargers in the same
cycle.

What this eliminates:

* The 3 separate inline blocks resolving forecast/tariff/is_night
  per call site
* The asymmetry where multi-charger loop saw `tariff_level` but
  primary didn't (and similar for other fields)
* The "did I remember to plumb the new field?" mental load every
  PR that touches fleet state

The structural guarantee: any future fleet-level input is a
**one-place change** (add the field to `FleetCycleState`).

### Enforcement — AST lint as a CI gate

`tests/test_fleet_state_completeness.py` walks `coordinator/` AST
and fails CI if any `build_charger_view` caller:

  * Forgets the `fleet_state` positional, OR
  * Passes any of the deprecated fleet-level kwargs (`power_reading`,
    `is_night`, `config`, `tariff_level`, `forecast_remaining_kwh`)

Catches the regression class on PR review, not at runtime. Same
shape as the existing FLEET-READ AST lint at
`tests/test_ev_control_fleet_reads.py`.

### Invariant tests

`tests/test_fleet_cycle_state.py` pins the behavioural contract:

  * `FleetCycleState` is frozen — instances cannot mutate
  * Equal inputs produce equal instances (value-type semantics)
  * Two views built from the same `FleetCycleState` in the same
    cycle agree on every fleet-level field (only
    `solar_committed_w` differs per view, by design)

### Transition-class scenarios

Four new YAML scenarios in `tests/scenarios/` covering state
transitions that steady-state scenarios miss:

* `sunset_transition` — solar drops + `is_night` flips false→true.
  solar_only must IDLE on the night-mode flip.
* `sunrise_transition` — mirror: `is_night` true→false + solar
  rising. min_plus_solar transitions cleanly out of MIN_PV.
* `multi_charger_plug_events` — two solar_only chargers, one
  unplugs mid-timeline. Pins per-charger budget conservation
  under plug-state changes.
* `full_day_replay` — 24h walkthrough on 10-min cycles (144
  cycles, runs <1s). Catches daily-integrator drift, state
  machine blips on zone boundaries.

Plus two harness extensions enabling these:
`ev_connected_per_charger` / `ev_charging_per_charger` (per-charger
plug state) and a per-row `is_night` override (for sunset/sunrise
walks).

### Verification

2879 tests passing, 7 skipped, 0 failed, 0 xfailed (~35s runtime).
+16 tests since beta.6 (4 scenarios + 7 FleetCycleState contract
tests + 4 misc + the AST lint's 3).

22 scenarios total now.

---

## [1.7.0-beta.6] — 2026-06-02

Diagnostic surface expansion for two more reported issues — same
pattern as beta.5's `per_source_lists` (one-shot triage from the
diagnostics dump alone).

### Diagnostics

- **#379 — PV string discovery state.** New
  `pv_strings_discovery` top-level block surfaces what the
  `_sensor_reader` resolved from both the direct-power-pattern
  scan and the V+I synthesis pair scan. Lets a "PV2 is empty"
  report be triaged in one shot: empty dict → discovery missed
  entirely; partial dict → one pattern matched but others didn't;
  full dict → bug is downstream in the card rendering.

- **#357 — Per-charger adapter state.** New `charger_adapters`
  top-level block surfaces the resolved adapter class +
  brand-specific discovery state per charger. For `WallboxAdapter`
  specifically:
  `wallbox.pause_switch_searched`, `pause_switch_entity`,
  `pause_switch_discovered`. Lets a "Wallbox keeps charging
  despite mode=off" report point at the failing step on the
  first dump: false → the discovery couldn't find a
  `switch.*pause_resume` entity for this Wallbox model;
  true → adapter wired right, problem is downstream.

### Verification

2863 tests passing, 7 skipped, 0 failed, 0 xfailed (~35s runtime).
4 new tests in ``tests/test_357_wallbox_diagnostics.py``.

---

## [1.7.0-beta.5] — 2026-06-02

Testing-framework adoption + three structural arch fixes + diagnostic
surface for fleet-aggregation bug triage. Built on top of beta.4.

### Production fixes (post-#358 arch follow-up)

- **`SOLAR_ONLY` forecast-aware battery redirect restored.** Post-arch
  `decide.py::SolarOnlyMode` was checking bare surplus against the
  charger min (4140W), returning IDLE, and the canonical strategy
  chain collapsed to IDLE — so the redirect branch in
  `flow_calculator.calculate_canonical_ev_budget` was unreachable.
  Fix: extracted `battery_redirect_w` as a module-level helper,
  plumbed `forecast_remaining_kwh` through `FleetContext` +
  `build_charger_view`, made `SolarOnlyMode.decide()` add redirect
  to its surplus calculation BEFORE the min check. Caught by
  scenario `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`.

- **`tariff_level` plumbed into primary view.**
  `SolarPlusCheapMode.decide()` reads `view.fleet.tariff_level` for
  the expensive-window pause (#247), but the primary view was being
  built without it (was `None`). Fix: pull `current_level` from
  `_tariff_provider` and pass to `build_charger_view`.

- **Night-plan ordering — hoisted before primary view.**
  `_compute_night_plan` was computed AFTER the primary view's
  `decide()` ran, so `tariff_wait` (#247) and `deadline_amps`
  (#246) didn't reach `SolarPlusCheapMode` / `MinPlusSolarMode`
  for the primary charger. Fix: hoisted the plan to before the
  primary view in `_build_charging_context`.

All three are the same class — info the legacy
`_determine_charging_strategy` had access to wasn't fully plumbed
into the new `decide.py` path. A structural refactor to eliminate
the gap class (single `FleetCycleState` builder + AST lint) is
planned for v1.8.

### Diagnostics — #378 triage support

- `diagnostics.py` now captures `energy_dashboard.per_source_lists`
  (`solar_power_list` / `battery_power_list` / `grid_power_list`
  from the Energy Dashboard config) AND
  `energy_dashboard.per_source_readings` (each entity's current
  state, or `{"state": "missing"}` if it disappeared from
  `hass.states`). For multi-inverter / multi-battery / multi-grid
  setups, this makes "fleet sensor underreports" reports one-shot
  triagable from the diagnostics dump alone.

  Triage flow: open `per_source_lists.battery_power_list`, compare
  against what the user reports they have. If the list is missing
  an entity → bug is in discovery / HA Energy Dashboard config. If
  the list has the entity but reading is `"missing"` or
  `"unavailable"` → bug is in the sensor source itself.

### Testing framework adoption

Adopted `pytest-homeassistant-custom-component==0.13.205` (the
official HA test framework — used by HACS itself, ~30 of Frenck's
integrations, required by Quality Scale Silver+). SEM is already
declared `quality_scale: platinum`; this work validates that claim
structurally.

- Real `HomeAssistant` fixture for config-flow, services, migrations,
  and the scenario harness — replaces dict-mock approach where it
  matters for end-to-end correctness.
- Legacy `hass` fixture renamed to `mock_hass` via AST-aware libcst
  rewrite (35 files, 419 test signatures). No behaviour change in
  existing tests; the framework's `hass` fixture is now usable.
- Migration chain (`async_migrate_entry` v1→v7) now has 8 real-hass
  tests covering every hop + the full chain composition.

### Scenario suite — wired into CI for the first time

The 5 scenario YAMLs in `tests/scenarios/` had been silently broken
since PR #358: the harness called the deleted
`_determine_charging_strategy` inside a bare `try/except: pass`, so
every cycle produced `strategy=None`, `budget=0`, `amps=0` — and the
scenarios "passed" on the null outputs. The harness now drives the
real production decision path (`coord._build_charging_context`),
raises loudly on `AttributeError`, and is wired into pytest
discovery via `tests/test_scenarios.py`.

Eight new YAML scenarios mined from closed bug issues — one per
EV-charge-mode × regime cell:

- `solar_only/night_must_idle` (#346)
- `solar_only/zone3_day_redirect` (#282)
- `min_plus_solar/zone3_day_battery_assist` (#282)
- `min_plus_solar/night_top_up_at_min` (#268)
- `min_plus_solar/night_deadline_floor` (#246)
- `solar_plus_cheap/day_normal_tariff` (#247)
- `solar_plus_cheap/night_cheap_window_charges` (#247)
- `always_max/ignores_zone_and_tariff`
- `multi_charger/priority_cascade_with_mixed_modes`

Plus `tests/test_scenario_coverage.py` — a matrix test that fails
listing missing cells with their issue hints. New EV-charge modes or
regimes that land without scenario coverage fail CI with a clear
to-do.

### Property-based invariants

`tests/test_budget_invariants.py` — 10 `hypothesis`-driven tests over
the canonical EV budget math. Invariants: `net_w >= 0` and finite
across all 6 strategies, IDLE always zero, NOW returns override,
`SELF_CONSUMPTION` never includes redirect, `SOLAR_ONLY net_w ==
solar_surplus + battery_redirect`, amps floored not rounded.

### User-reported regression guards

- **#378** (multi-battery aggregation) — 6 tests pinning
  `PowerReadings` + `fleet_battery_w` so future arch changes can't
  silently drop a battery from the sum.
- **#379** (Growatt PV-string discovery) — 5 tests pinning Growatt
  naming patterns + the "missing entity" diagnostic path.
- **#307** (pool heat pump as surplus device) — 7 tests verifying
  `SurplusController` dispatch to non-EV devices.
- **#49** (surplus controller restart safety) — 5 tests pinning that
  `ControllableDevice` defaults to `PEAK_ONLY` (so SEM never
  proactively activates a device the user didn't opt into).
- **#353** (KEBA 0A self-charge) — 19 adapter-unit tests pinning that
  `command_current(<6A)` always routes to `command_idle()` (=
  `keba.disable`), never `set_current(0)`.

### Internal

- 2859 tests passing, 7 skipped, 0 failed, 0 xfailed (~34s runtime).
- Release workflow now installs from `tests/requirements_test.txt`
  (was a hardcoded list missing `pytest-homeassistant-custom-component`).

---

## [1.7.0-beta.4] — 2026-06-02

Private beta (not published to HACS) — bundles the multi-device
architecture follow-up on top of beta.3 for an internal PROD soak.

### Fixed
- **#375** — True per-battery control loop. `_battery_adapter`
  (singular) → `_battery_adapters: Dict[str, BatteryControlAdapter]`;
  `_run_battery_pipeline` iterates `power.batteries`, dispatching
  `decide_battery` / `actuate_battery` per battery with its own
  cached adapter. Closes the architectural gap the v1.7.0 rebuild
  left behind for 2× same-brand installs (2× Huawei LUNA2000,
  2× GoodWe). Single-battery installs see zero behavioural change
  (PR #376).

## [1.7.0-beta.3] — 2026-06-01

Beta batch addressing 5 open user-reported issues + dead-code cleanup
from #351's audit deferred list.

### Fixed
- **#352** — Manual `grid_sign_invert` config option for Enphase and
  other inverters where the energy-counter auto-detect can't
  stabilise on the grid power polarity (PR #370).
- **#355** — Bumped EV target slider max from 100 to 200 kWh so the
  Min and Max handles have drag-room when both sit at the previous
  cap (PR #368).
- **#356** — Collapsed the duplicated hero metrics on the EV status
  card when per-charger sections render — the gate was `> 1`
  instead of `>= 1`, so 1-charger installs saw both layers. Hero
  now shows only Status + Power when ≥1 charger sections will
  render below (PR #371).
- **#357** — New dedicated `WallboxAdapter` that auto-discovers the
  Wallbox `pause_resume` switch from the HA entity registry and
  toggles it explicitly on `command_idle` / `command_disable` in
  addition to `_set_current(0)` + `stop_session()`. Closes the
  v1.6.17 reporter's bug where mode=off didn't stop the Pulsar
  (PR #372).
- **#359** — Percentile-based tariff price classification (default
  for dynamic tariffs). The legacy static 0.15/0.35 CHF cutoffs
  mis-bucketed everything on Tibber/Octopus/Amber/Nordpool where
  daily ranges span €0.05–€0.80. Buckets now compute relative to
  today's 24h distribution. Static mode preserved as opt-out
  (PR #373).

### Removed
- `coordinator._execute_battery_charge_scheduler` (91 LOC) and
  `coordinator.BatteryProtectionMixin._apply_battery_discharge_protection`
  (66 LOC) — both retired by the v1.7.0 per-device-primary
  rebuild; zero live callers since the `_run_battery_pipeline`
  flip. `BatteryProtectionMixin` survives this release with only
  `_restore_battery_discharge_limit_on_startup` (planned full
  retirement in v1.7.1) (PR #369).

## [1.7.0] — 2026-06-01

Major release. Two headline themes:

1. **Multi-device architecture rebuild** — every multi-device data
   point in SEM (chargers, inverters, batteries, PV strings) now
   flows through the same per-device-primary pattern: `Dict[str, X]`
   is the source of truth, fleet aggregates are `@property` views.
   Brand hardware quirks (KEBA's 6 A minimum, set_current(0)
   rejection, self-resume detection, Huawei/GoodWe battery force-
   charge) are encapsulated in dedicated adapter modules. EV
   control flows through one pure `decide(view) → ChargerDecision`
   → `actuate(decision, adapter)` pipeline; batteries get the same
   `decide_battery / actuate_battery / BatteryControlAdapter`
   treatment. The strategy/state-machine disagreement class that
   produced the 14-bug cluster between v1.6.0 and v1.6.17
   (#243, #284, #289, #290, #291, #308, #315, #316, #318, #344,
   #345, #346, #349, #353) is **structurally retired** — those
   disagreements cannot exist by construction because there's only
   one decision authority per device per cycle.

2. **Per-PV-string visibility (#312)** — Sunsynk-style per-string
   display on three SEM cards, plus V+I synthesis for inverters
   that expose voltage and current but no per-string power.

The architecture work shipped as four PRs into develop (#358 EV
rebuild, #360 inverter+battery PowerReadings dicts, #361 battery
decide/actuate/adapter, #362 EnergyTotals @property views, #363
93 surplus-charging scenario tests). The per-PV-string work
shipped as three PRs (#337 data layer, #338 cards, #339 docs).
All consolidated under one release tag.

### Architecture rebuild — what changed structurally

**Per-charger primary** (PR #358, 8 steps):
- New frozen types in `coordinator/charger_types.py`: `ChargerPower`,
  `ChargerEnergy`, `ChargerIntent`, `ChargerDecision`, `ChargerView`,
  `FleetContext`, `FleetView`, plus the symmetric inverter/battery
  types (PR #360/#361).
- `ChargerAdapter` ABC + `KebaAdapter` + `GenericAdapter` in
  `coordinator/charger_adapters/`. Every KEBA quirk that bit
  production (6 A min, set_current(0) rejection, self-resume on
  plug-in, charging_state lag, 500 W handshake cutoff) is one
  method on this protocol. New brands subclass; the actuator never
  changes.
- Pure `decide(view) → ChargerDecision` in `coordinator/decide.py`
  with one `ModeStrategy` class per charge mode (`off`,
  `solar_only`, `min_plus_solar`, `always_max`, `solar_plus_cheap`).
  No `self`, no HA calls — same input always produces the same
  output.
- `actuate(decision, adapter)` in `coordinator/actuate.py` — pure
  intent dispatch. One branch per `ChargerIntent`. The
  #315/#346/#353 self-resume guards collapse into one
  `adapter.is_self_charging()` check before the new intent is
  applied.
- Coordinator `_per_charger: Dict[str, ChargerRuntime]` consolidates
  what used to be 8 parallel `_*_per_charger` dicts.
- The legacy `_determine_charging_strategy`,
  `_self_consumption_strategy`, `_zone_based_strategy`,
  `_canonical_strategy_from_legacy`, and the `_raw_zone`/`_get_zone`/
  `_debounce_zone` helpers — **deleted** (−354 lines in
  `coordinator.py`). The new pipeline is the only control path.
- Per-charger native priority flow attribution in
  `flow_calculator.py`: when multiple chargers consume from the
  same surplus, the priority allocator splits sources in order
  (higher-priority chargers get first claim on solar, fall back to
  battery, fall back to grid). Replaces the pre-#349 proportional
  fraction-of-fleet split.

**Per-inverter + per-battery primary** (PR #360, #361, #362):
- `PowerReadings.inverters: Dict[str, InverterPower]` and
  `PowerReadings.batteries: Dict[str, BatteryPower]` — populated by
  `sensor_reader` for multi-device installs (`len(...list) > 1`).
- `@property fleet_solar_w`, `fleet_battery_w`, `fleet_battery_soc`
  on `PowerReadings` — sum / capacity-weighted-average from the
  dicts. Empty dict on single-device installs → falls back to the
  legacy `solar_power` / `battery_power` / `battery_soc` fields.
  Zero churn for existing consumers.
- `EnergyTotals.per_inverter` / `per_battery` dicts plus
  `daily_solar_view` / `daily_battery_charge_view` /
  `daily_battery_discharge_view` `@property` accessors. Same
  fallback discipline.
- New `coordinator/battery_adapters/` module unifies what used to
  live in two separate places: discharge limiting (the legacy
  `BatteryProtectionMixin`) and forced charging (the legacy
  `BatteryChargeAdapter`). `BatteryControlAdapter` is one ABC with
  four methods (`command_normal`, `command_limit_discharge`,
  `command_force_charge`, `command_stop_force_charge`); each maps
  1:1 to a `BatteryIntent`. Huawei, GoodWe, and Generic adapter
  implementations wrap the existing brand-specific service calls.
- `decide_battery(view) → BatteryDecision` and
  `actuate_battery(decision, adapter)` — same pure-pipeline shape
  as the EV side. Replaces the dual-axis legacy split
  (`BatteryProtectionMixin._apply_battery_discharge_protection` +
  `BatteryChargeScheduler.update`).
- The pure planner `BatteryChargeScheduler.evaluate()` is preserved
  verbatim — it produces a `SchedulerDecision` that feeds
  `BatteryView.scheduler_decision`. Only the dispatch path changed.

**Invariant test suite** (PR #358 + #363):
- `tests/test_step8_invariants.py` — **233 architectural contracts**
  parametrised across `(mode × solar × battery_soc × home ×
  is_night × num_chargers)`. Each invariant pins one property the
  architecture is supposed to guarantee by construction. A breaking
  change in any module surfaces immediately at CI time, not in
  production.
- `tests/test_surplus_charging_scenarios.py` — **93 behavioural
  scenarios** walking every (mode × battery SOC zone × time-of-day
  × solar level) combination through `decide → actuate → adapter`.
  Includes a full-day timeline (`dawn → morning → noon → afternoon
  → evening → dusk`) with realistic numbers.
- `tests/test_inverter_battery_arch.py` — **27 tests** pinning the
  inverter/battery types, adapter dispatch, hysteresis, factory
  selection.
- `tests/test_multi_inverter_battery_primary.py` — **23 tests** for
  the PowerReadings dicts + fleet `@property` accessors.

Full suite: **2733 passed**, 7 skipped (was 2337 at v1.6.14
baseline → **+396 new tests**). The simulation-driven verification
approach replaces the previous "deploy and watch logs" cycle —
hardware test windows are scarce; deterministic CI scenarios run
in under a second and gate every PR.

### Compatibility notes

- **Zero user-visible behaviour change for single-device installs.**
  The fleet `solar_power` / `battery_power` / `ev_power` fields stay
  populated as cached sums; every existing sensor and dashboard
  card continues to read them unchanged. The new `@property` views
  are additive.
- **Multi-device installs see better-quality flow attribution.**
  A two-charger setup where one is in `solar_only` and the other in
  `min_plus_solar` previously got a proportional split that
  attributed grid to the solar-only charger; now the priority
  allocator correctly routes solar to the higher-priority charger
  first.
- **`charge_mode = solar_only` no longer charges from grid at night.**
  Fixed in v1.6.17 (#346) and structurally retired by the new
  decide-time mode gate in v1.7.0.
- **Storage format: backward-compatible.** Pre-v1.7.0 snapshots
  restore unchanged (no new keys present → empty dicts → fallback
  to legacy fields).
- **Legacy code paths retired:** `_determine_charging_strategy`,
  `_self_consumption_strategy`, `_zone_based_strategy`,
  `_canonical_strategy_from_legacy`, `_raw_zone`, `_get_zone`,
  `_debounce_zone`. `BatteryProtectionMixin` and the per-brand
  `BatteryChargeAdapter` subclasses (`HuaweiChargeAdapter`,
  `GoodWeChargeAdapter`, `GenericChargeAdapter`) are still in the
  tree as backward-compat shells — the new `BatteryControlAdapter`
  wraps them internally. They can be deleted in v1.7.1 after the
  PROD soak window.

### What's queued for v1.7.1

- Per-inverter / per-battery dashboard sensors (gated on
  `len(...) >= 2`).
- Per-inverter / per-battery flow attribution in `flow_calculator`
  (the destination-side view of "which inverter's solar fed where").
- `sensor_reader` migration to populate
  `EnergyTotals.per_inverter` / `per_battery` each cycle (so
  `daily_solar_view` becomes authoritative on multi-inverter
  installs).
- Delete `BatteryProtectionMixin` + `BatteryChargeAdapter` shells
  after PROD soak proves the new pipeline.
- Per-string-to-destination attribution (#312 originally deferred —
  now buildable on top of the per-inverter flow work).

---

### Per-PV-string visibility (#312)

Closes the long-standing @MRAK96 request for Sunsynk-style per-string
display: SEM had the auto-discovery (`hardware_detection.discover_pv_strings_from_registry`,
8 inverter brands) for the optional HACS K-Flow card since v1.5.x
but never promoted per-string to SEM's own surface. v1.7.0 ships
the full stack: data layer, sensor entities, card rendering, and
user docs — internally implemented as three discrete phases so
each piece could be reviewed and tested independently on HA-TEST,
but published as one user-visible release.

### Added

- **Per-PV-string power + daily-energy sensors** (gated on
  `len(strings) >= 2`):
  - `sensor.sem_pv_string_<slot>_power` (W, MEASUREMENT)
  - `sensor.sem_pv_string_<slot>_daily_energy` (kWh, TOTAL,
    daily-reset)
  where `<slot>` is the normalised label `pv1`, `pv2`, … (max 4
  per discovery's slot cap). Single-string installs see no
  change.
- `PowerReadings.solar_power_per_string: Dict[str, float]` — the
  source-side mirror of v1.6.9's `ev_power_per_charger`. Sum
  invariant: `sum(values) ≈ solar_power` within rounding.
- `EnergyFlows.per_string: Dict[str, StringEnergy]` — daily kWh
  per string, integrated by `FlowCalculator.integrate_energy_flows`
  alongside the fleet and per-charger accumulators.
- `PowerFlows.solar_per_string: Dict[str, float]` — pass-through
  carrier from readings to the integrator (strings are sources,
  no destination attribution math required).
- `StringEnergy` dataclass (1 field: `energy_kwh`).
- `SensorReader.set_pv_strings(...)` registers the discovered
  per-string sensors; the per-cycle read loops in both the
  Energy-Dashboard and legacy paths populate
  `readings.solar_power_per_string` when the gate trips.
- Auto-discovery wired through coordinator: the existing
  `hardware_detection.discover_pv_strings_from_registry`
  (Huawei / GoodWe / Growatt / Kostal / Sungrow / Fronius /
  SolarEdge / Victron) now also feeds SEM's own sensors.
- **V+I synthesis fallback**
  `hardware_detection.discover_pv_string_vi_pairs` — when an
  inverter exposes per-string voltage + current but no
  per-string power sensor (Huawei Solar Modbus, generic
  Modbus drivers, Solarman bridges), SEM detects sibling
  `pv_N_voltage` + `pv_N_current` pairs and multiplies V × I
  at read time to synthesise the per-string watts. Surfaces
  the same `sensor.sem_pv_string_<slot>_power` entities as
  the direct-power path; downstream consumers (cards, energy
  accumulator, sum invariant) don't know which way the value
  was sourced. Voltage / current patterns accept English
  (`voltage` / `current` / `volt` / `amp`) and German
  (`spannung` / `strom`) suffixes. When the same slot has
  BOTH a direct power sensor AND a V+I pair, the direct
  sensor wins (slightly more accurate — accounts for the
  inverter's MPPT efficiency math). Confirmed on HA-PROD
  2026-06-01: Huawei `inverter_pv_1_spannung` +
  `..._strom` pair now feeds `sensor.sem_pv_string_pv1_power`
  via this path.
- **Per-PV-string chip strip** on three cards, auto-shown when
  ≥ 2 strings are present. Each chip shows `PVn N.NN kW` and
  links to the underlying sensor entity on tap.
  - `sem-flow-card`: chips above the SVG flow diagram.
  - `sem-solar-card`: chips above the hero arc ring.
  - `sem-system-diagram-card`: chips above the illustrated
    diagram as a compact HUD.
- `semDiscoverPVStrings(hass, prefix)` shared card helper —
  reads `sensor.{prefix}pv_string_pv1_power` … `pv4_power`,
  returns `[]` when fewer than 2 present so callers can pass
  the result straight to a Lit `html` template.
- `semPVStringsCSS` shared style block.
- **New user reference doc**
  [`docs/PV_STRINGS.md`](docs/PV_STRINGS.md) — what sensors get
  created, supported inverter brands with regex pattern table,
  how discovery works, "what if I don't see my strings"
  troubleshooting flow, internals pointer table, and the
  out-of-scope list (per-string-to-destination attribution,
  per-string cost, Solcast multi-plane — file-an-issue links).

### Fixed

- **Flow attribution: priority-based instead of proportional (#349)** —
  HA-PROD 2026-06-01 dashboard showed `flow_grid_to_ev_energy =
  6.633 kWh` on a day when the actuator's `session_solar_share` said
  the car was 91 % solar. Root cause: SEM split every source across
  every destination by demand percentage, attributing grid to the EV
  whenever the home battery was simultaneously charging (the battery
  was actually the grid-paid consumer; EV was on solar). The model
  also overshot destinations when supply ≠ demand exactly.

  New model: sources drain in priority `solar → battery_discharge →
  grid_import`; destinations served in priority `home → ev →
  battery_charge → grid_export`. Each watt is attributed to exactly
  one (source, destination) pair. The conservation invariants hold:
  for each destination, sum of (source→destination) flows = demand;
  for each source, sum of (source→destination) flows = supply. 14
  new tests in `tests/test_349_flow_priority_attribution.py` pin
  both. The previously misleading `flow_grid_to_ev` should now match
  user intent — solar covers EV first when there's enough.

- **EV charges overnight in `charge_mode=solar_only` (#346)** —
  also shipped as the v1.6.17 hotfix. `_determine_charging_strategy`
  returned `"night_grid"` unconditionally when `is_night_mode()` was
  True, ignoring the per-charger `charge_mode`. Strategy now consults
  `MODE_NIGHT_ALLOWED` first: `solar_only` at night → `idle`; `off` →
  `disabled`; other modes unchanged. Defence in depth: actuator self-
  resume guard extended from `{"disabled"}` to `{"disabled", "idle"}`
  so future strategy disagreements land safely.
- **Autarky reported 0% when battery overnight-charged from grid
  (#344, #345)** — fleet-summed `daily_grid_import` was treated as
  unconditional autarky penalty, including the grid-to-battery slice
  that doesn't displace home consumption. Then a second pass (#345)
  switched the formula to fully flow-attributed accumulators
  (`solar_to_home + solar_to_ev + battery_to_home + battery_to_ev`
  over total consumption) so the temporal mismatch between sunrise-
  reset `daily_ev` and calendar-reset `flow_grid_to_ev` no longer
  drowns the numerator.

### Changed

- Day rollover in `FlowCalculator.integrate_energy_flows` now
  also clears `_per_string_accumulators` alongside fleet and
  per-charger.
- Snapshot persistence (`get_flow_accumulator_state` /
  `restore_flow_accumulator_state`) gains a `per_string` key,
  emitted only when non-empty. Pre-v1.7.0 snapshots restore
  bit-for-bit identical (no `per_string` key → no per-string
  state).

### Tests (18 new)

`tests/test_per_string_energy.py`:
- Back-compat: empty per_string dict in single-string setups.
- Sum invariant: 2-string and 4-string splits.
- Multi-cycle accumulation.
- Day rollover clears per-string accumulator.
- Persistence round-trip (4 tests, incl. legacy snapshot
  back-compat).
- Bad-snapshot defence (3 tests: non-dict per_string, non-dict
  per-slot entry, non-numeric values).
- Idle-string preservation (clouded string keeps its surfaced
  kWh — no regression to 0 on the user-visible counter).
- `SEMData.to_dict` emission (key present when populated,
  omitted when empty).
- `SensorReader` gate (1 string → no pollution; ≥2 → populated).

Full suite 2281 green on Python 3.12 (2263 v1.6.14 baseline +
18 new). Bundle (`dist/sem-cards.js`) rebuilt with the chip
strip rendering for all three cards.

### Phase trail (internal)

Implementation shipped to develop as three feature PRs for
focused review, then consolidated to one user-visible v1.7.0
release per maintainer policy:
- PR #337 — data layer (sensors, types, sensor reader,
  flow calculator persistence).
- PR #338 — card rendering (3 cards, shared helper, bundle).
- PR #339 — user reference doc.

Manifest stays at 1.7.0.

## [1.6.14] — 2026-05-31

Multi-charger debt closeout. Bundles four pieces of work into one
release (the maintainer-set rule "no v1.7 until every multi-charger
follow-up is closed" pulled deferred ``v1.7+`` items back into
v1.6.x; this is them, packaged as one release rather than four
separate HACS bumps).

### Fixed

- **Surplus tracker jump-from-0 spike (#8)** —
  ``_apply_ramp_limit`` used to short-circuit on ``current < 1`` and
  return ``target_current`` directly, so a cold-start cycle handed
  KEBA a 14 A command from 0 A. KEBA's ~30 s physical actuator lag
  then caused a ~4.4 kW grid-import overshoot during the ramp
  (confirmed live on PROD 2026-05-31 at 10:43). Cold start now hands
  KEBA ``min_current`` (typically 6 A ≈ 4140 W on 3-phase EU);
  subsequent cycles climb via the existing ``±ramp_rate`` clamp at
  the user-configured ``ev_ramp_rate_amps`` (default 2 A/cycle, so
  target reached in ~4 cycles for a 14 A request). The stop-fast
  branch is preserved: ``target_current < 1`` still returns 0
  immediately so explicit-off / disable stays snappy. 13 new unit
  tests in ``tests/test_ramp_limit_8.py`` pin every branch.

### Changed

- **``effective_state`` and ``charger_name`` migrated onto
  ``PerChargerContext``** instead of writing the parallel
  ``_effective_states_per_charger`` dict from inside the loop body.
  The loop body assigns ``pcc.effective_state = …``; ``__exit__``
  persists ``(state, name)`` into the coordinator's dict so the
  post-loop ``_send_notifications`` dispatcher continues reading
  from a single map. The dict is the storage; pcc is the write
  path. Lets a future AST lint enforce field access at type level
  (no callsite outside the loop touches the dict directly).
- **``this_power_w`` precomputed in ``PerChargerContext.__enter__``**
  via ``coord._this_charger_power(ev_dev, power)`` and exposed as a
  typed field. The coordinator stashes the active pcc on
  ``coord._current_pcc``; ``_this_charger_power`` becomes a cache
  shim — when invoked with the same ``ev_dev`` it returns
  ``pcc.this_power_w`` instead of re-reading HA state. Replaces
  the three per-method ``this_power_w = self._this_charger_power(…)``
  local-var caches in ``coordinator/ev_control.py`` without
  changing the callsites. Helper exceptions in the precompute fall
  through to the legacy read path so a transient HA-state issue
  can't half-apply the swap.

### Added

- ``PerChargerContext.power``, ``this_power_w``, ``effective_state``,
  ``charger_name`` dataclass fields.
- ``SEMCoordinator._current_pcc`` short-lived pointer to the active
  context (``None`` outside any per-charger iteration).
- ``# FLEET-READ:`` annotation on the documented multi-charger
  fallback in ``_this_charger_power`` (only reached when a charger
  config omits ``ev_charging_power_sensor`` — rare).
- 47 new tests across three areas (13 ramp-limit + 14 pcc-field +
  20 per-charger flow):
  - ``tests/test_ramp_limit_8.py``: cold-start, near-zero,
    steady-state ramp, stop-fast, custom ``min_current``,
    end-to-end multi-cycle climb.
  - ``tests/test_per_charger_context.py``: effective_state
    persistence, this_power_w precompute, current-pcc-pointer
    lifecycle.
  - ``tests/test_this_charger_power_cache.py``: cache HIT, three
    MISS variants, kW→W conversion regression from #315.
  - ``tests/test_per_charger_energy_flows.py``: sum invariant,
    multi-cycle accumulation, day rollover, persistence
    round-trip (incl. legacy snapshot back-compat), edge cases
    (charger appears mid-day, charger idle in cycle,
    zero-interval), bad-snapshot defence, sensor-description
    generation gate.

- **Per-charger flow sensors (gated on ``len(ev_chargers) > 1``)**:
  ``sensor.sem_charger_<id>_flow_solar_to_ev_power``,
  ``..._grid_to_ev_power``, ``..._battery_to_ev_power`` (W,
  MEASUREMENT) plus matching ``..._energy`` (kWh, TOTAL, daily-
  reset). The Sankey card + HA Energy dashboard can now show
  per-charger EV sourcing instead of a fleet-proportional split —
  closes the @RienduPre observation on #316. Single-charger setups
  unchanged (fleet ``sensor.sem_flow_*_to_ev_*`` is authoritative).
  - ``ChargerEnergyFlows`` dataclass + ``EnergyFlows.per_charger``
    field.
  - ``FlowCalculator._per_charger_accumulators`` (kWh) integrated
    over time alongside the fleet accumulator; sum invariant
    pinned in tests.
  - Day rollover clears both fleet AND per-charger accumulators.
  - Snapshot persistence round-trip: new ``per_charger`` key
    under the existing snapshot dict; pre-v1.6.15 snapshots
    (without the key) restore bit-for-bit identical.
  - Accumulator semantic: once a charger appears, its kWh stays
    surfaced until the day rollover, even on cycles where the
    charger is idle (the user-visible counter must not regress
    to 0 just because the car unplugs).

- **``FleetEvPower`` newtype + global AST lint (v1.6.16 work)**.
  ``PowerReadings.ev_power`` is now typed as ``FleetEvPower`` — a
  ``float`` subclass that exposes ``.as_fleet_total(reason: str)``.
  Two equivalent ways to acknowledge a fleet read:
  - Comment form (v1.6.8 idiom, still valid):
    ``# FLEET-READ: <reason>`` on the same line or up to 5 lines
    above (walking back through ``#``-comment lines only).
  - Method form (preferred for new code):
    ``power.ev_power.as_fleet_total("<reason>")`` — the reason
    rides in the bytecode (mypy / IDE hover / ``git blame``)
    instead of an adjacent comment.

  Lint expanded to every module under ``coordinator/`` (was
  ``ev_control.py`` only). Exempt files: ``types.py`` (defines the
  field) and ``per_charger_context.py`` (docstrings only). The
  ~15 legitimate fleet reads got explicit ``# FLEET-READ:``
  reasons; one ``coordinator.py:3459`` stall-detection site
  migrated to the new method form as the in-tree demo.

  Sensor reader (the only writer) constructs ``FleetEvPower``
  instances at the assignment sites. Single-charger setups
  unchanged — ``FleetEvPower(value)`` reduces to a tagged float.

  12 new tests in ``tests/test_fleet_ev_power_reads_global.py``:
  - ``TestGlobalFleetEvPowerLint`` (6): every read acknowledged
    across coordinator/; exempt-list minimality; synthetic-code
    sanity (method form detected, bare read flagged, comment
    form still accepted).
  - ``TestFleetEvPowerNewtype`` (6): is float subclass,
    arithmetic works (no migration cost), ``.as_fleet_total``
    returns plain float, reason arg is documentation-only,
    default ``PowerReadings.ev_power`` is the newtype, repr
    includes class name.

### Why

Senior reviewer on the v1.6.7→v1.6.10 arc flagged ``effective_state``
and ``this_power_w`` as "works correctly; not on the context object."
Both shipped working — but the docs claimed "pcc is the single source
of truth for per-charger data" while these two lived in a parallel
dict and method-local vars. This release makes the doc honest.

The ``#8`` surplus-tracker spike fix bundled in here was confirmed
live on PROD 2026-05-31 during the v1.6.3 soak — held with the
refactor rather than shipped standalone so PROD users get one
soak window instead of four staggered HACS updates.

@RienduPre's #316 observation ("Sankey shows charger 2 sourcing
from grid even in solar_only") was the user-visible gap behind the
flow-sensor work. v1.6.9 fixed the underlying data (proportional
W-level split was honest); v1.6.15 ships the entity surface so the
dashboard + Energy dashboard actually render the per-charger split.

### Polish (HA-TEST soak findings folded into v1.6.14)

- **PR #333** — initialise ``SEMCoordinator._current_charger_budget``.
  Missed in the v1.6.7 PerChargerContext refactor; ``__enter__``
  snapshotted the attribute but ``__init__`` never set it, so every
  multi-charger setup blew up its first cycle with
  ``AttributeError``. Single-charger setups (HA-PROD) never tripped
  it; HA-TEST today was the first multi-charger clean install since
  v1.6.7. New regression test ``test_coordinator_swap_attrs_initialized.py``
  AST-walks ``SEMCoordinator.__init__`` to assert every attribute
  ``PerChargerContext.__enter__`` snapshots is initialised.

- **PR #334** — per-charger notification ``NoneType`` coerce + flow
  sensor zero-fill. ``intel.get(k, default)`` returns the default
  only when the KEY is missing — mock chargers without upstream
  data have the key set to ``None``, so ``est_soc > 0`` raised
  ``TypeError`` every cycle (DEBUG noise). Fix: ``intel.get(k) or 0``.
  Plus: ``flow_calculator`` now zero-fills per-charger flows when
  the fleet is idle so the v1.6.15 flow sensors stay AVAILABLE at
  0 W instead of going ``unavailable`` whenever no charger draws.

- **PR #335** — upgrade-notification helper. After a HACS update +
  HA restart, the browser's loaded frontend bootstrap still
  references the OLD ``sem-localize.js`` URL until hard-refreshed
  — soft reload serves the cached bootstrap → loads stale
  translations → raw keys like ``today_plan_title`` /
  ``plan_strip_idle`` appear in cards. HA-TEST 2026-05-31 confirmed.
  New ``_maybe_emit_upgrade_notification`` helper detects a SEM
  version change at setup (via a per-entry
  ``hass.helpers.storage.Store``) and fires a one-shot
  ``persistent_notification`` instructing users to hard-refresh
  (Ctrl+Shift+R / Cmd+Shift+R). First install is silent. Failure
  is non-fatal. 5 new tests pin the contract (first-install,
  same-version, upgrade, per-version notification-id, per-entry
  storage key).

2263 tests pass on Python 3.12 (2210 v1.6.12 baseline + 13 #8 +
14 v1.6.14 + 20 v1.6.15 + 12 v1.6.16 + 2 v1.6.14-hotfix +
5 v1.6.14-polish = 66 new tests in this release). Manifest at 1.6.14.

## [1.6.12] — 2026-05-31

Closes the last open senior-reviewer item on the v1.6.7 → v1.6.11
multi-charger cleanup arc — the missing end-to-end scenario covering
``charger A = off + charger B = solar_only`` mixed-mode. No
behaviour change for any user.

### Added

- **New scenario test** ``tests/scenarios/2026-05-31_off_plus_solar_only.yaml``
  exercises the senior-reviewer-flagged hole in coverage:
  - **Per-charger effective state isolation** (v1.6.4
    ``_apply_per_charger_off_override``). Charger ``off`` mode →
    ``SOLAR_IDLE`` (terminate); sibling ``solar_only`` →
    ``SOLAR_CHARGING_ACTIVE`` (untouched). Pins the #315 mitigation
    at the unit-pipeline level — would have mechanically caught the
    v1.6.3 regression at PR-review time.
  - **Per-charger flow attribution** (v1.6.9
    ``PowerFlows.per_charger``). With per-charger draw set to
    ``{left: 4000, right: 0}``, the per-charger split must give
    ``right`` zero EV-side flow — the user-visible attribution
    @RienduPre asked for in #316.
  - **Distribution sum invariant** (Phase B.5 / #284) re-asserted on
    top of the mixed-mode case.

- **Scenario harness extensions** in ``tests/scenario_harness.py``:
  - ``TIMELINE_FIELDS`` accepts ``ev_power_per_charger: {cid: watts}``
    so multi-charger flow attribution can be driven from YAML.
  - Cycle results now include ``per_charger_effective_states`` and
    ``per_charger_flows`` when the scenario has 2+ chargers.
  - Two new ``expect.multi_charger`` assertion blocks:
    ``per_charger_effective_states`` (exact match or
    ``{cid}_contains: substring``) and ``per_charger_flow_max`` for
    per-charger upper-bound caps.

### Docs

- ``docs/MULTI_CHARGER.md`` roadmap updated: the off + solar_only
  scenario gap is now closed (was a senior-reviewer FIX-BEFORE-MERGE
  on the v1.6.7-v1.6.10 arc).
- CHANGELOG entry per the
  ``feedback_docs_per_release`` rule — docs are part of every
  release, not a follow-up.

## [1.6.11] — 2026-05-31

Diagnostics improvement + doc polish closing the senior-engineer
review NITs on the v1.6.7 → v1.6.10 multi-charger cleanup arc. No
behaviour change.

### Added

- **Recent SEM log lines in the Copy diagnostics dump** —
  ``diagnostics.py::_get_recent_sem_logs`` reads the last 2 MB of
  ``home-assistant.log``, filters for
  ``solar_energy_management`` mentions, and includes up to 80 matching
  lines as ``recent_logs`` in the diagnostics output. Bug reports now
  come pre-loaded with the surrounding log context so we don't have
  to ask reporters for a separate ``ha core logs`` dump. Supervisor
  installs (no flat log file, journald-based) get a one-line
  placeholder explaining how to attach logs manually.

### Docs

- ``CLAUDE.md`` — new "Multi-charger correctness" pointer to
  [``docs/MULTI_CHARGER.md``](docs/MULTI_CHARGER.md) so future AI
  sessions can find the invariant doc without needing to grep.
- ``docs/MULTI_CHARGER.md`` — updated the roadmap to reflect what
  **actually shipped** vs what was planned. Specifically: the original
  v1.6.7 design proposed migrating ``effective_state``,
  ``this_power_w``, ``night_plan`` onto ``PerChargerContext`` in
  v1.6.8/v1.6.9 — none of those landed. The current dataclass has
  ``cid`` / ``ev_dev`` / ``charger_cfg`` / ``budget_w`` /
  ``skipped_for_night`` only. Per-charger flow **sensors** (data is on
  ``PowerFlows.per_charger`` but no top-level HA entities yet) were
  also descoped. Both are deferred to v1.7+ in the roadmap so the doc
  no longer oversells the abstraction.

## [1.6.10] — 2026-05-31

Code-quality cleanup release. Closes the three follow-up issues filed
during the v1.6.4 → v1.6.6 review cycle (#308, #309, #310). **Zero
behaviour change** for any user.

### Refactored

- **#308 — dead ``now`` / ``min_pv`` consumer branches dropped from
  ``coordinator/charging_control.py``.** Post-#305 the strategy
  producer ``_determine_charging_strategy`` only emits ``solar_only`` /
  ``battery_assist`` / ``night_grid`` / ``idle`` / ``disabled`` —
  neither ``"now"`` nor ``"min_pv"`` was reachable in production. The
  unreachable branches are gone; ``ChargingState.SOLAR_MIN_PV`` is
  still alive via the ``night_grid`` → ``EVBudgetStrategy.MIN_PV``
  producer mapping. The two synthetic-context tests
  (``test_min_pv_mode``, ``test_now_mode``) that exercised the dead
  branches are removed.

- **#309 — global-select cleanup block in ``select.py`` folded into
  the registry-key sweep added by #304.** The 12-line explicit
  ``async_remove`` block for ``{entry_id}_ev_target_type``,
  ``{entry_id}_ev_target_mode``, ``{entry_id}_ev_charging_mode`` was
  redundant with the sweep at the bottom of ``async_setup_entry``:
  each of those unique IDs has the ``{entry_id}_`` prefix and a key
  that's not in ``valid_keys``, so the sweep removes them just as
  cleanly. Per-charger values were seeded from the globals by the
  v3→v4 migration; no data is lost.

- **#310 — gravestone comments in ``tests/test_soc_zone_strategy.py``
  consolidated** into a single ``Removed tests`` block at the top of
  the module. Three multi-line tombstones (one each from #277 Phase C,
  Phase D.2 / #282, and #305) collapsed to a three-bullet list with
  ``git log -S`` as the pointer for full history.

## [1.6.9] — 2026-05-31

Third and final of the multi-charger cleanup arc (v1.6.7 → v1.6.9).
Adds per-charger flow attribution and per-charger notification flap
suppression so multi-charger users finally get correct downstream
visibility — closes the @RienduPre #316 family of complaints. **Zero
behaviour change** for single-charger users.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md).

### Added

- **Per-charger flow attribution** in
  [`coordinator/flow_calculator.py`](coordinator/flow_calculator.py).
  When ``PowerReadings.ev_power_per_charger`` is populated (multi-charger
  installs), ``calculate_power_flows`` now also produces
  ``PowerFlows.per_charger[cid] = ChargerFlows(solar_to_ev, grid_to_ev,
  battery_to_ev)``. Sum invariant: ``sum(per_charger[c].solar_to_ev) ==
  solar_to_ev`` (within < 0.1 W from float rounding). Closes the
  long-standing @RienduPre #284 / #316 complaint family — the dashboard
  can now show which charger drank from grid vs solar instead of the
  fleet-aggregated proportional split.

- **``PowerReadings.ev_power_per_charger``** populated by
  ``sensor_reader`` for multi-charger installs (each charger's
  ``ev_charging_power_sensor`` value, keyed by charger id).
  Single-charger installs leave the dict empty.

- **Per-charger notification flap suppression** in
  [`coordinator/notifications.py`](coordinator/notifications.py).
  ``notify_state_change`` accepts new ``charger_id`` + ``charger_name``
  kwargs; the flap-suppression ``_last_notified_state`` /
  ``_pending_state`` / ``_pending_state_since`` storage is now
  per-charger, keyed by ``charger_id`` (or the ``"_fleet"`` sentinel
  for back-compat). A state change on charger A no longer suppresses
  one on charger B. Mobile messages get a ``[Charger Name]`` prefix
  when ``charger_name`` is provided. The HA event payload now carries
  ``charger_id`` and ``charger_name`` keys so automations can route
  per charger.

### Back-compat

- v1.6.8 callers that read ``_last_notified_state``,
  ``_pending_state``, or ``_pending_state_since`` as scalars continue
  to work via property shims that target the ``"_fleet"`` sentinel
  slot.
- Single-charger setups behave identically to v1.6.8 — the
  per-charger split skips when no per-charger data is provided.

## [1.6.8] — 2026-05-31

Second of the three-release multi-charger cleanup arc (v1.6.7 → v1.6.9).
**Zero behaviour change** for single-charger users; multi-charger users
get correctness fixes for 12 fleet-power-sum reads that were silently
returning the wrong value inside per-charger code paths. Sets up the
structural enforcement that makes the bug class impossible to
re-introduce.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Fixed

- **12 fleet-power-sum reads swept in
  [`coordinator/ev_control.py`](coordinator/ev_control.py)** — every
  ``power.ev_power`` read inside the per-charger code path (8 in
  ``_execute_ev_control``, 3 in ``_should_reenable_charger``, 1 in
  ``_update_session_tracking``) now uses
  ``self._this_charger_power(ev, power)`` cached as
  ``this_power_w`` at the top of the method. In multi-charger setups
  these reads were returning the fleet sum — exactly the bug class
  that caused #284, #289, #315 (terminator) and #318 (SOC isolation).
  Each fix was reactive; this sweep closes them all.

### Added

- **AST lint test** ([`tests/test_ev_control_fleet_reads.py`](tests/test_ev_control_fleet_reads.py))
  — walks the AST of ``ev_control.py`` on every CI run and fails if
  any ``power.ev_power`` read is missing a ``# FLEET-READ:`` annotation
  (outside the sanctioned ``_this_charger_power`` helper). Catches the
  bug class on PR review, not after release.

- **``# FLEET-READ: <reason>`` annotation convention** — documented in
  ``docs/MULTI_CHARGER.md``. Same-line or previous-line comment opts
  a deliberate fleet-level read out of the lint with a required
  human-readable reason.

## [1.6.7] — 2026-05-31

First of a three-release multi-charger cleanup arc dedicated to v1.6.x.
**Zero user-visible behaviour change** for single-charger users; multi-charger
users see the same outputs but with the underlying swap mechanism now
typed and unit-tested.

The cleanup arc addresses a recurring bug class found in v1.6.0–v1.6.6
(#284, #289, #315, #318): per-charger context swaps with fleet-level
reads leaking through. This release lifts the swap mechanism; v1.6.8
sweeps the fleet-power reads in `ev_control.py` and adds per-charger
strategy; v1.6.9 adds per-charger flow attribution + notifications
(closes the #316 family).

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Refactored

- **`PerChargerContext`** — new
  [`coordinator/per_charger_context.py`](coordinator/per_charger_context.py)
  module that owns the per-charger swap lifecycle. The ad-hoc
  ``saved = {...}`` dict at `coordinator.py:1136-1258` that swapped
  eight coordinator attributes per iteration (and was easy to miss
  when adding new per-charger fields) is now a typed context manager
  with unit tests pinning every swap invariant. Adding a new
  per-charger field is now one place to edit instead of three.

### Docs

- **New `docs/MULTI_CHARGER.md`** — developer-facing invariant doc
  covering the bug class, the `PerChargerContext` contract, how to
  add new per-charger fields, and the v1.6.7-v1.6.9 roadmap.
- **`CONTRIBUTING.md`** — new "Multi-charger correctness" section
  pointing future contributors at the invariant.

## [1.6.6] — 2026-05-31

Same-day hotfix for v1.6.5 — the per-charger power read at
``_this_charger_power`` did a unit-naive ``float(state.state)`` and
compared a kW value to a 500 W threshold. KEBA's native
``sensor.keba_p30_charging_power`` reports in kW; the comparison
``4.14 < 500`` was always False so the v1.6.5 off-mode stop never
fired on KEBA, even when the firmware self-resumed. Confirmed live
on PROD 2026-05-31 15:26 — KEBA self-resumed and ran uncontrolled
for ~2 min until a manual ``keba.disable`` stopped it.

### Fixed

- **Unit-aware per-charger power reading** — ``_this_charger_power``
  now reads the sensor's ``unit_of_measurement`` attribute and
  converts kW → W before the 500 W threshold check. Tests pin both
  KEBA-style (kW) and Wallbox-style (W) sensors so the next charger
  integration doesn't introduce the same trap.

- **Per-charger SOC isolation in multi-charger setups** (#318) —
  ``_update_ev_intelligence`` was only calling ``update_energy()`` on
  the PRIMARY taper detector at line ~3326; every per-charger detector
  in ``_ev_taper_detectors`` stayed at ``_energy_since_full=0``,
  giving every charger the same default SOC. Confirmed by @RienduPre
  on a multi-charger Wallbox Pulsar + Growatt setup. Fix: also call
  ``update_energy(per_increment, per_hw_total)`` inside the
  per-charger loop, using each charger's own ``ev_total_energy_sensor``
  hardware counter for drift-free tracking when configured.

## [1.6.5] — 2026-05-31

Same-day follow-up to v1.6.4. Closes the second half of the off-mode
problem: KEBA P30 self-resumes from a stored setpoint on plug-in events
or after internal firmware events, completely independent of SEM. The
v1.6.4 fix only stopped SEM-owned sessions; if SEM never started the
session (because mode was already off when the EV plugged in, or KEBA
restarted on its own), the contactor stayed closed and KEBA drew power
SEM never knew about.

### Fixed

- **off-mode now stops charger-initiated charging** (#315) — the
  actuator's terminal-state branch in ``ev_control.py`` now also calls
  ``stop_session()`` when ``charging_strategy == "disabled"`` and
  ``ev_power > 500W``, regardless of ``ev._session_active``. Every
  coordinator cycle (10 s) re-asserts the per-brand disable (e.g.
  ``keba.disable``) until ev_power drops below the 500 W threshold.
  Idempotent — safe to call on an already-disabled charger.

  Threshold rationale: KEBA's handshake idle draws 100–200 W
  continuously while plugged in (control-pilot duty cycle). Real
  charging starts at 4140 W minimum (3 phases × 6 A × 230 V). The
  500 W cutoff cleanly separates "actually pulling current" from
  "plugged in, parked" so SEM doesn't spam stop_session every cycle
  while the car is idle at the charger.

## [1.6.4] — 2026-05-31

Hotfix on top of v1.6.3 plus the cleanup follow-ups #304/#305 that
shipped to develop the same day.

### Fixed

- **`charge_mode=off` did not stop EV charging** — surfaced during the
  v1.6.3 PROD soak. Setting the per-charger Charge mode to ``Off`` while
  the EV was actively charging left the KEBA contactor closed; SEM
  reported "Charging allowed" with budget 0 but the charger kept drawing
  power, requiring a manual ``keba.disable`` call to stop. The state
  machine fell through to ``SOLAR_CHARGING_ALLOWED`` instead of a
  terminal stop, so ``stop_session()`` was never invoked.

  Fix: introduce a distinct ``"disabled"`` strategy string for explicit-off
  (separate from transient ``"idle"``). The state machine routes it to
  ``SOLAR_IDLE``, which the actuator treats as terminal → calls
  ``stop_session()`` → ``keba.disable``. The canonical EV budget enum
  collapses ``"disabled"`` back to ``IDLE`` (same 0 W shape, distinct
  upstream).

  Multi-charger correctness: a static helper
  ``_apply_per_charger_off_override`` runs in the dispatch loop so a
  primary charger's ``off`` cannot bleed its terminate into siblings
  with active ``solar_only``/``min_plus_solar`` modes.

### Cleanup (from develop merge)

- **#304** — ``select.py`` orphan removal now uses a registry-key sweep
  matching ``switch.py``. Catches stale entries from previously-removed
  chargers (rather than only those currently in the config).
- **#305** — drop dead ``_auto_mode_strategy`` and the unreachable
  ``min_pv`` branch in ``_canonical_strategy_from_legacy``. Both were
  Phase C leftovers documented as deferred.

## [1.6.3] — 2026-05-30

The **EV charge UX consolidation** release (#277). Replaces the
four-toggle soup (``ev_charging_mode`` × ``night_charging`` ×
``smart_night_charging`` × ``tariff_optimized``) with one named
per-charger ``Charge mode`` selector. Three-phase arc shipped across
five PRs (A + B + B.2 + C + #298 today-plan ETAs).

### New

- **Per-charger ``Charge mode`` selector** with five modes:
  ``Solar only`` / ``Solar + cheapest hours`` / ``Min + Solar``
  (default) / ``Always (max)`` / ``Off``. ``Solar + cheapest hours``
  is dynamically hidden when no dynamic tariff is configured.
- **Per-mode help line** in the EV card explains what each mode
  actually does — cuts the toggle-soup mystery the #247 review
  flagged.
- **Today's plan timeline** gains three ETA rows (#298): "Battery
  full at HH:MM" while charging, "Battery reaches floor at HH:MM"
  while discharging, "EV reaches target at HH:MM" while a charging
  session is in progress.

### ⚠️ Behavioural change — explicit-``minpv`` legacy users

A small population of users explicitly set the legacy
``ev_charging_mode`` to ``minpv`` (the "force Min from grid + solar
to Max" mode). The Phase A migration mapped them to
``min_plus_solar``, which in v1.6.x kept their daytime behaviour
unchanged (the strategy machine still read the legacy field). v1.6.3
Phase C makes ``min_plus_solar`` **zone-adaptive during the day** —
the Min guarantee now comes from NIGHT charging top-up only, not
from forced grid pull at noon. The Min target itself is unchanged;
the daytime path now matches what most installs (``pv + night=on``)
were always doing.

If you want strict "Min from grid at all times" behaviour, pick
``always_max`` from the new selector — it charges at maximum
regardless of source. Otherwise the new ``min_plus_solar`` default
adapts to your battery SOC zone (battery priority when low, surplus
when high, battery-assist in Zone 4) — generally more efficient
than forced grid pull.

### Migrations (automatic on first load post-upgrade)

- **v4 → v5** (Phase A): Each charger gets a ``charge_mode`` derived
  from its existing toggle state. The legacy fields stay in place.
- **v5 → v6** (Phase B fix-up): Re-derives ``charge_mode`` for
  installs whose Phase A derivation silently lost the
  ``tariff_optimized`` signal (``pv/auto/self_consumption + tariff_on``
  → ``solar_plus_cheap``).
- **v6 → v7** (Phase C): Drops the now-dead ``ev_charging_mode`` per-
  charger config key. The legacy ``select.sem_charger_<id>_ev_charging_mode``
  entity is removed from the registry automatically.

### Removed

- **Per-charger switches** ``switch.sem_charger_<id>_night_charging``,
  ``...smart_night_charging``, ``...tariff_optimized`` — the named
  ``charge_mode`` selector carries all three intents now. Existing
  automations that read these switches will need to read the
  ``charge_mode`` select state instead.
- **Per-charger select** ``select.sem_charger_<id>_ev_charging_mode``
  — superseded by the new ``charge_mode`` selector.
- **Global switches** ``switch.sem_night_charging`` and
  ``switch.sem_smart_night_charging`` — same; ``observer_mode`` is
  the only remaining global switch.
- **Config-flow toggle** ``smart_night_charging`` — the named modes
  carry the intent.
- **Strategy machine legacy reads**: ``ev_charging_mode`` is no
  longer consulted anywhere; ``_tariff_optimized_for`` derives from
  the named mode.

### Fixed

- **Stale Lovelace cache-bust on sem-localize.js (#301)** — the legacy
  ``generate_dashboard`` service path used ``int(time.time())`` as the
  ``?v=`` for card resources, so a plain rsync deploy that rewrote
  ``sem-localize.js`` left the registered URL unchanged and browsers
  served the cached pre-Phase-B.2 file. Symptom on first install of
  this release: the new charge-mode selector renders raw translation
  keys (``charge_mode``, ``charge_mode_min_plus_so…``,
  ``charge_mode_hint_min_plus_solar``) instead of localized labels.
  Fix: per-file ``{version}-{sha1(content)[:8]}`` cache-bust, matching
  the format ``_async_register_frontend_resources`` already uses for
  the Lit bundle. Both paths now produce identical URLs for the same
  file content; any deploy that changes content auto-flips the URL on
  the next ``generate_dashboard`` call and the browser cache-misses
  through to the fresh copy.

### Internal

- New ``consts/ev_charge_modes.py`` — shared constants
  (``EV_CHARGE_MODES``, ``MODE_NIGHT_ALLOWED``, ``MODE_USES_TARIFF``,
  ``MODE_USES_SMART_NIGHT``, ``MODE_TO_LEGACY_CHARGING_MODE``,
  ``DEFAULT_EV_CHARGE_MODE``) and the ``effective_charge_mode_for``
  resolver. Single source of truth for the mode taxonomy across
  ``SEMCoordinator``, ``ChargingStateMachine``, ``EVControlMixin``,
  the dashboard cards.
- ``async_migrate_entry`` accumulator refactor — each step reads
  from / writes back to threaded ``accumulated_{data,options}``
  accumulators. Fixes a pre-existing bug exposed by chaining 4
  migration steps (each was re-reading the original entry options on
  test harnesses).
- New module-level ``_content_hash_cache_bust`` helper — extracted
  from the legacy ``generate_dashboard`` registration path so the
  cache-bust behaviour is directly unit-testable. Replaces a closure
  buried inside ``async_generate_dashboard_service``.
- 15-language translations updated; legacy entries cleaned from
  ``strings.json`` + 15 per-language files.
- Suite: 2136 / 2136 tests passing (6 new regression tests guard
  the #301 cache-bust contract).

### Issues addressed

- Closes #277 (EV charge UX consolidation arc)
- Closes #298 (Today's plan battery / EV ETA rows)
- Closes #301 (Stale Lovelace cache-bust on sem-localize.js)

---

## [1.6.2] — 2026-05-30

The **Phase D.2 cleanup + EV-power realtime** patch.

Two changes ship together:

1. **Phase D.2 architectural cleanup (#282)** — completes the EV-budget
   unification arc by removing the legacy fallbacks that the v1.6.0
   canonical path left side-by-side as a safety net. Carrying two budget
   formulas alive was exactly the duplication that produced the
   disagreement bug class in the first place; with three weeks of clean
   v1.6.0/v1.6.1 PROD soak the fallbacks are dead code, and keeping them
   invited the next regression.

2. **#289** — `sensor.sem_ev_power` now updates within one HA dispatch
   of the upstream KEBA / Wallbox sensor instead of waiting up to 10 s
   for the next coordinator cycle. The dashboard reads at 1 s
   resolution and observably benefits; the energy-balance derivations
   (`home_consumption_power`, sankey flows) stay on cycle granularity
   and self-heal on the next tick.

No behavioural changes outside the named removals + the sub-cycle
passthrough. Same upgrade path as any 1.6.x.

### Removed

- **`flow_calculator.calculate_ev_budget`** — superseded by
  `calculate_canonical_ev_budget` since v1.6.0 (Phase A). Zero
  production callers as of v1.6.1.
- **`flow_calculator.calculate_available_power`** — superseded by the
  canonical EVBudget's per-strategy resolution. Zero production
  callers as of v1.6.1.
- **`flow_calculator.calculate_charging_current`** — both production
  call sites (night charge sizing + actuator ramp) now go through
  `EVControlMixin._watts_to_amps` which carries the per-charger
  watts-per-amp + round-down policy directly.
- **`EVControlMixin._calculate_solar_ev_budget`** — 74-line legacy
  fallback that the actuator used when `_cycle_ev_budget` wasn't
  populated. Removed; the path now logs an error and emits 0 W
  (fail-safe = no charge) if the invariant is ever violated. This
  catches coordinator init bugs loudly instead of silently masking
  them with a divergent budget formula.
- **Multi-charger distribution legacy fallback** in
  `coordinator.py` — same fail-safe pattern applied: missing
  `_cycle_ev_budget` → log error + distribute 0 W.
- **`sensor._format_charging_state` demotion guard** — the cosmetic
  SOLAR_CHARGING_ACTIVE → SOLAR_CHARGING_ALLOWED downgrade (commit
  `1a9b3c9`) that papered over the pre-D.2 budget disagreement. The
  canonical unification eliminated the disagreement by construction,
  so the guard is now dead code — verified across daytime
  battery_assist and nighttime MIN_PV soak in v1.6.0/v1.6.1.

### Added

- **#289 — sub-cycle `sem_ev_power` passthrough** — the `ev_power`
  sensor now subscribes to its upstream EV-power entities via
  `async_track_state_change_event` (single-charger: top-level
  `ev_power_sensor`; multi-charger: every charger's
  `ev_charging_power_sensor`). On any upstream change SEM re-sums and
  pushes the new value immediately. Eliminates the 1-cycle gap that
  showed up live on PROD 2026-05-29 as a 4.7 kW dashboard
  discrepancy. 11 unit tests + the resolution / callback / cleanup
  invariants.

### Internal

- **Test sweep** — removed the unit tests that pinned the deleted
  primitives directly (`TestAvailablePower`, `TestEvBudget`,
  `TestAvailablePowerIncludesBatteryDischarge`, `TestEVBudgetSemantics`,
  `TestAvailablePowerInvariants`, `TestCalculateSolarEvBudget`, the
  budget/current rows from `TestEVControlInvariants`). Their physical
  invariants (non-negative budget, 16 A clamp, battery-discharge
  inclusion, Zone-3 proportional ramp, measured-discharge override)
  are now exercised against `calculate_canonical_ev_budget` and the
  scenario harness (`tests/scenarios/2026-05-29_*`).
- **Scenario harness rewired** — `tests/scenario_harness.py` was
  calling the deleted `calculate_ev_budget` / `calculate_charging_current`
  inside a bare `except Exception: pass`. Caught in review before
  deploy: every scenario was vacuously passing (`calculated_current`
  fell silently to 0). Rewrote to compute the canonical EVBudget
  directly and read `EVBudget.net_w` + `EVBudget.current_a`, so
  scenario regressions now fail loudly. 4 / 4 scenarios still pass
  with real values.
- **`test_multi_charger_canonical_budget.py` rewrite** — the test
  mirrored the pre-D.2 production branch with the legacy fallback;
  post-D.2 the branch logs an error and distributes 0 W instead.
  New `test_missing_cycle_budget_fails_safe_to_zero` pins the fail-
  safe; `test_legacy_method_attribute_does_not_exist_post_d2`
  prevents accidental re-introduction.
- **16 A clamp coverage gap closed** —
  `TestEVControlInvariants.test_canonical_budget_current_a_clamped_to_16`
  sweeps extreme solar / battery inputs across every non-IDLE
  strategy (including `BATTERY_ASSIST` which can blow past the
  surplus ceiling by design) and verifies `EVBudget.current_a`
  stays in [0, 16].
- **Docstring rot** — `ChargingContext.available_power` docstring
  was still referencing `FlowCalculator.calculate_ev_budget()`;
  updated to point at `calculate_canonical_ev_budget().net_w`.

**Suite is 2054 / 2054 green** (was 2042 in v1.6.1 — 12 new tests).

---

## [1.6.1] — 2026-05-30

Patch release with fixes driven by the v1.6.0 PROD soak. No behavioural
changes outside the named fixes — same upgrade path as any 1.6.x.

### Fixed

- **#288** — Night peak management formula switched from the
  sensor-lag-sensitive derived `home_consumption_power` to
  `sensor.sem_consecutive_peak_15min` (the same 15-min rolling
  grid-import average most demand-charge tariffs bill on).
  Self-balancing: as EV ramps the rolling rises and headroom shrinks
  naturally; settles at the equilibrium where rolling ≈ peak limit.
  Falls back to the legacy formula during the cold-start window when
  the load manager hasn't accumulated samples yet, so peak protection
  is never absent. Caught live on PROD 2026-05-29 with a 7.9 kW grid
  spike during EV ramp because `sem_ev_power` lagged by ~5 kW for
  several seconds, deflating the derived home value toward 0 and
  giving the EV the full peak limit as headroom. 6 unit tests +
  forever live sentinel.
- **#290** — Night state machine no longer blips through
  `NIGHT_DISABLED` for one cycle during config slider writes.
  Observed live on PROD 2026-05-29: a per-charger Number slider
  write triggered a race in `hass.states.is_state` for the per-charger
  night switch, returning False for one ~10 s cycle before
  recovering. SEM now requires 2 consecutive cycles of disagreement
  before flipping the cached state — trades 10 s of responsiveness
  for race immunity. 7 unit tests covering first-call commit, blip
  suppression, sustained change, and pending-counter reset.

### Internal

- **Test infra** — fixed the pre-existing flaky
  `test_lookahead_uncapped_when_no_deadline_resolvable` that had been
  intermittently red since the defensive `night_end` fallback at
  `ev_control.py:119-122` was added. The test now patches
  `DEFAULT_EV_TARGET_TIME` to None so the original "no deadline
  resolvable" path it was written to guard is actually exercised.
  Suite is now 2091 / 2091 fully green — first time this release.
- **Live test layer** — new sentinel `tests/live/test_night_peak_rolling.sh`
  pins the #288 fix as a regression guard.
- **Documentation** — design plan for #277 (EV Charge mode
  consolidation) committed at `docs/plans/2026-05-30_ev_charge_mode_consolidation.md`.
  No code yet; awaiting maintainer decisions on the four design
  questions listed there before any implementation. Tracked for v1.7.0.

---

## [1.6.0] — 2026-05-30

The **EV-budget unification** release. SEM historically had three separate
"how many watts can the EV draw right now" calculations — one for the
published dashboard sensors, one for the state machine's decision, and one
for the actuator. Under certain conditions they disagreed: the dashboard
could read *"Charging active"* while the car drew 0 W, or surplus-only
mode could let grid backfill the EV's draw without telling the user.

v1.6.0 collapses all three into one canonical `EVBudget` value computed
once per cycle. Every consumer now reads from the same dataclass — the
dashboard, the state machine, the actuator, and the multi-charger
distribution all see the same number, by construction.

### ⚠️ Behavioural change — published sensors

`sensor.sem_available_power` and `sensor.sem_calculated_current` now
publish the **canonical** EV budget instead of the raw solar surplus.
The canonical value is strategy-aware (includes battery-redirect on
`solar_only`, includes the battery-assist contribution on
`battery_assist`, applies the floor on `min_pv`) — it's the more
accurate number and matches what the state machine actually decides
with.

If you have automations or template sensors that read either of these
two values directly, you may see different numbers than under
1.5.x. The canonical value is the honest one; the pre-1.6.0 value
could be misleadingly low when battery redirect was active.

### Added

- **Canonical `EVBudget` dataclass and `EVBudgetStrategy` enum** in
  `coordinator/flow_calculator.py`. Six strategies are first-class:
  `IDLE`, `SELF_CONSUMPTION`, `SOLAR_ONLY`, `BATTERY_ASSIST`, `MIN_PV`,
  `NOW`. Each has a single well-defined formula; the dispatcher raises
  `ValueError` on unknown strategies (no silent fallthrough, which was
  the #282 disagreement root). See [ARCHITECTURE.md → EV Budget
  Calculation](docs/ARCHITECTURE.md#ev-budget-calculation).
- **Live test layer** under `tests/live/` — seven bash scripts that
  exercise SEM against a real Home Assistant instance:
  `test_budget_agreement.sh`, `test_charging_state_consistency.sh`,
  `test_solar_only_no_grid.sh`, `test_overnight_window.sh`,
  `test_deadline_reset.sh`, `test_per_charger_slider.sh`,
  `test_bundle_integrity.sh`, `test_surplus_charging.sh`.
- **Scenario harness scenarios** locking the canonical math through
  the coordinator pipeline:
  `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`,
  `tests/scenarios/2026-05-29_budget_unify_battery_assist.yaml`,
  `tests/scenarios/2026-05-29_multi_charger_split.yaml`.
- 17 unit tests for the canonical method covering every strategy plus
  the regimes that historically disagreed.
- 4 unit tests for the multi-charger Phase B.5 distribution path.
- 4 unit tests for the YAML-mode Lovelace guard.
- `copy_failed` translation key across all 15 languages.

### Changed

- `coordinator.async_update_config` now mutates `self.config` in place
  rather than rebinding to a new dict. Multiple components
  (`TimeManager`, `EnergyCalculator`, `ChargingStateMachine`,
  `BatteryChargeAdapter`) hold references to the original dict; the
  pre-fix rebind left them stale, so the next slider change reached
  `coordinator.config` but never propagated. Caught by
  `tests/live/test_overnight_window.sh`.
- The multi-charger distribution at `coordinator.py:966` now reads the
  canonical `EVBudget.net_w` instead of calling the legacy
  `_calculate_solar_ev_budget`. Same #282 disagreement mode, just for
  fleets of 2+ chargers (Phase B.5).
- The `sem-system-card` "Copy diagnostics" button now uses a
  cross-context clipboard helper that falls back to
  `document.execCommand('copy')` on HTTP installs where the modern
  Clipboard API is blocked. Always shows user feedback — success or
  failure — so the button is never silent again.
- Deploy scripts (`~/bin/deploy-test.sh`, `~/bin/deploy-prod.sh`) now
  strip `__pycache__` before `ha core restart`. `ha core restart` does
  not clear the bytecode cache, so signature changes in committed
  code could still execute the cached `.pyc` and produce confusing
  `NameError`s. (Operational; not in the integration itself.)

### Fixed

- **#279** — Global `daily_ev_energy` counter resets at the configured
  `Charge by` time, not at sunrise. The summer-sunrise race condition
  (sunrise earlier than the deadline → counter wiped while night
  charging still in progress → double-charge) is closed.
- **#283** — Dashboard no longer fails to register on YAML-mode
  Lovelace installs. The integration feature-detects the mutating
  resource-collection methods; when YAML mode is detected, it logs a
  single actionable warning with the exact `lovelace.resources:` YAML
  the user has to paste, instead of an unhelpful "Could not register"
  warning. Storage-mode users see no behavioural change.
- **#284** — Multi-charger setups (e.g. dual Wallbox Pulsar) no longer
  pull from grid while strategy reports `solar_only`. The distribution
  path now reads from the canonical `EVBudget`.
- **#285** — "Copy diagnostics" button in the System Information card
  now works on HTTP installs. Reported on macOS Chrome.
- **Charger plug-sensor physics defence** — caught live on PROD
  2026-05-29 with a KEBA P30. Across an HA restart with a connected
  car, `binary_sensor.keba_p30_plug` reported "off" for 67 minutes
  while `binary_sensor.keba_p30_charging_state` cycled on/off through
  15 transitions and `sensor.keba_p30_charging_power` peaked at 8 kW.
  SEM correctly trusted the lying plug sensor, returned "EV
  disconnected", and stopped supervising the car. The KEBA kept its
  last commanded current; the car drew ~6 kWh past the configured
  Max ceiling because SEM wasn't watching. The root cause is upstream
  (the charger integration's plug sensor), but SEM now defends
  against it: if `ev_charging` is True OR `ev_power > 100 W`,
  `ev_connected` is inferred True regardless of what the plug sensor
  says. Current cannot flow without a connection. Locked in by
  `tests/test_ev_connected_physics_defence.py` (5 truth-table corners)
  and `tests/live/test_ev_connected_physics.sh` (forever sentinel).
- Display-honesty guard at `sensor.py:_format_charging_state` is now
  redundant after the unification (canonical is the single source of
  truth) but kept as defence-in-depth for one release; will be removed
  in v1.7.0.

### Internal

- `coordinator/coordinator.py` — `_build_charging_context`'s
  `available_power` and `calculated_current` parameters dropped (dead
  since Phase B). Step 6's bare-variable computation removed (also dead
  since Phase B).
- New `_canonical_strategy_from_legacy` helper in `coordinator.py`
  maps the legacy strategy-string returns of `_determine_charging_strategy`
  to canonical `EVBudgetStrategy` constants.

### Community contributions

Thanks to **@RienduPre** for [PR #286](https://github.com/traktore-org/sem-community/pull/286)
— two native-speaker Dutch translation polishes (`notif_low_forecast`
grammar; `notif_daily_summary` replaces the loanword "autarkie" with the
idiomatic "zelfvoorzienend").

---

## [1.5.15] — 2026-05-27

Single hotfix release for a SolaX-pattern cold-start regression.

### Fixed

- **#274** — Inverter / battery / grid readings no longer stay at 0
  after an HA restart on SolaX-pattern installs (Pattern E: split
  grid). Forced a sensor-reader reinitialization on coordinator
  restart instead of relying on the lazy first-cycle path.

---

## [1.5.14] — 2026-05-27

Documentation, sensor-naming hardening, and the #255 per-charger
config cleanup.

### Added

- Per-charger night charging gate (`switch.sem_charger_<id>_night_charging`,
  default ON) — multi-charger fleets can now schedule night charging
  per car.

### Changed

- Removed the redundant global EV configuration entities — per-charger
  entities are the canonical source of truth after #255. The integration
  migrates existing setups transparently.
- Energy Dashboard config summary on the System tab now lists actual
  entity names instead of the compact "X sources, Y units" string (#250).

### Fixed

- **#245** — Surplus EV charging now stops at the Max ceiling
  (`daily_ev_target_max`) instead of running until the per-cycle
  remaining-need flips negative. The Min target gates night charging;
  Max gates day surplus. Both are honored independently.
- **#256** — Zero-config installs no longer adopt the global target as
  the per-charger night floor without the user's explicit consent.
- **#259** — Vehicle SOC reads that come back as `unknown` or
  `unavailable` no longer crash the strategy decision.

---

## [1.5.13] — 2026-05-25

Beta-only iterations; release notes consolidated into the next stable.

---

## [1.5.12] — 2026-05-25

### Fixed

- Dashboard regenerate ("Generate Dashboard" service) no longer
  triggers an HA core restart. Live-reload via the storage API
  replaces the legacy "write + restart" pattern.
- Removed a stray top-level `sem-cards.js` left over from a botched
  manual deploy that was shadowing the real `dist/sem-cards.js`
  bundle and breaking every dashboard card (#219 regression class).

---

## [1.5.11] — 2026-05-25

### Changed

- All ~23 dashboard cards now ship as a single Lit bundle at
  `dashboard/card/dist/sem-cards.js`. The legacy top-level vanilla
  `sem-*-card.js` files were removed.
- Lovelace resource URLs now include `?v={version}-{sha1[:8]}` for
  cache busting; plain `rsync + restart` deploys now bust the browser
  service-worker cache without a manifest bump (#240).

---

For the full pre-1.5.11 history, see the [git tag log](https://github.com/traktore-org/sem-community/tags).

[1.6.0]: https://github.com/traktore-org/sem-community/releases/tag/v1.6.0
[1.5.15]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.15
[1.5.14]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.14
[1.5.13]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.13
[1.5.12]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.12
[1.5.11]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.11
