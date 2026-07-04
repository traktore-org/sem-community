# Changelog

All notable changes to SEM are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> From v1.7.0-beta.14 onward, release entries follow the
> [music-assistant addon](https://github.com/music-assistant/home-assistant-addon)
> style: DD.MM.YYYY dates, emoji-prefixed sections, one-liner bullets with
> `(by @author in #PR)` attribution. Older entries (≤ beta.13) stay in the
> prose-paragraph style they were written in.

# [1.7.4-beta.16] — 04.07.2026

> **Pre-release.** Config-picker fixes, friendly missing-card notice, typed
> investment input, unambiguous Net labels.

### 🛠️ Configuration pickers (#560)
- 🐛 **Hot-water switch (and several other entities) could not be selected** —
  the dashboard Config card's entity pickers passed a broken domain filter
  that excluded *every* entity when no domain was set. The hot-water picker
  now accepts `switch`, `input_boolean`, `water_heater` and `climate`
  entities. (reported by @covuser)
- 🐛 Heat-pump relay 1/2 pickers (Config card **and** the native config flow)
  only accepted `switch` — SG-Ready setups bridged through `input_boolean`
  helpers couldn't be configured. Both now accept `input_boolean` too.

### 🧩 Dashboard — friendly missing-card notice (#555, #558)
- 🩹 A missing optional HACS card (e.g. `sankey-chart`) no longer shows a red
  "Configuration Error" banner — a new wrapper renders a friendly, translated
  notice naming the missing card and how to install it, and renders the real
  card as soon as it's available. (reported by @hrdilshan and @ebnerjoh)

### 💰 Costs — typed System Investment Cost (#557)
- ✨ The System Investment Cost stepper now accepts **direct numeric entry**
  (keyboard input next to the ± buttons), and the accepted range is wide
  enough for any real installation. (requested by @hrdilshan)

### ☀️ Forecast — Solcast no longer misses the bus (#562)
- 🐛 **SEM latched onto Forecast.Solar even when Solcast was installed** — if
  the Solcast integration finished loading after SEM's first source
  detection, the cache stuck until the next restart. SEM now upgrades to
  Solcast (its preferred source) as soon as the Solcast entities appear.
  (reported by @ebnerjoh)

### 📊 Grid card — Net direction spelled out (#561 follow-up)
- 🐛 The grid card's "Net" row showed `|import − export|` with the direction
  conveyed only by color. The label now states it: **Net import** /
  **Net export** — translated in all 15 languages. (follow-up to @ebnerjoh's
  report)

# [1.7.4-beta.15] — 04.07.2026

> **Pre-release.** Deye grid direction out-of-the-box.

### ⚡ Grid — Deye brand sign seed (#554)
- 🎯 **Deye installs (hass-deyecloud) get the correct grid import/export
  direction from the first cycle** — the platform is now in SEM's brand sign
  map (`totalgridpower` reports +=import, verified from reporter diagnostics),
  so no Fix-grid-sign button or detection wait is needed. (thanks @hrdilshan)

# [1.7.4-beta.14] — 04.07.2026

> **Pre-release.** Feedback-round fixes: Wh counters + consistent Net display.

### 🔋 Energy statistics — unit-aware hardware counters (#551)
- 🐛 **Fronius (and any Wh-reporting) lifetime counters inflated the lifetime
  statistics ×1000** — a 2-day-old install showed 21,350 battery "cycles" and
  a health score pinned at 70% (real value: ~21). Counter reads are now
  unit-aware (Wh/kWh/MWh), covering lifetime seeding and the EV daily-energy
  reconciliation. (reported by @ebnerjoh)
- 🩹 **Self-healing**: installs that already seeded the inflated values are
  detected and re-seeded from the corrected counters automatically on the
  first restart after updating — no manual cleanup.

### 💰 Costs — consistent Net framing (#554)
- 🐛 The Costs hero said "+1.71 net saving" while the Today/Month/Year rows
  printed "−1.71" — the same cost-signed value in two contradictory framings.
  All Costs surfaces now use the savings-positive framing ('+' and green when
  earning; plain pink when a net cost). The math was always consistent:
  Net = import cost − export revenue. (reported by @hrdilshan)

# [1.7.4-beta.13] — 04.07.2026

> **Pre-release.** Observability + contract-test pass (#553 wrap-up).

### 🔎 Diagnostics & guardrails
- 🧭 The `diagnose` action's `ev_actuation` block now reports
  **`idle_guard_armed`** — SEM's belief that the KEBA runaway-cap energy
  target is armed (stop arms, start releases). One service call to triage.
- 🧪 **Silent-no-op contract extended to switches and selects**: the wiring
  test that already guards number knobs now covers switch/select entities —
  including a source-scan that fails CI when a new dynamic per-charger /
  per-battery key isn't covered. (No dead knobs found today.)
- 📖 Audit playbook: hardware-facing values require one live device
  round-trip before tagging (the 1 Wh-vs-1 kWh KEBA lesson).

# [1.7.4-beta.12] — 03.07.2026

> **Pre-release.** KEBA guard correction — beta.11's tagged build carried a
> silent no-op guard value.

### 🔌 KEBA — runaway cap corrected (#553)
- 🐛 beta.11 tagged the guard at ~1 Wh, which the KEBA library **rejects**
  (minimum 1 kWh; the error is swallowed as a log line) — caught by a live
  layer-check on a real P30. The guard now arms **1 kWh**: a runaway cap that
  bounds a firmware auto-start session when SEM is down or restarting
  (previously unbounded). Per-retry policing while SEM is alive is #552's job
  and unchanged. Authorization-based approaches are explicitly out of scope.

# [1.7.4-beta.11] — 03.07.2026

> **Pre-release.** Improvement batch (#553): KEBA idle-guard, full grid schema, cleanup.

### 🔌 KEBA — box-level runaway cap (#315)
- 🛡️ **A KEBA auto-start that SEM isn't policing now stops itself at the box
  after 1 kWh.** The firmware retries a stored session every ~10 min when a
  hungry car is plugged; SEM kills each within a cycle (#552) — this guard
  bounds the damage when SEM is down or restarting (previously unbounded).
  SEM arms a 1 kWh session-energy target on every stop and releases it on
  every start. (1 kWh is the KEBA library minimum — live-verified on the
  real P30; the originally announced ~1 Wh value is rejected by the library.)

### ⚡ Grid — full Energy-Dashboard schema (#551 sibling)
- 🐛 Grid sources support the same `power_config` modes as batteries; the
  Two-sensor mode is now consumed correctly as import/export split
  (review-caught: the first draft read the import side as a combined sensor —
  permanent phantom export). Inverted combined sensors defer to the #461
  sign-detection stack.
- 🔋 **Multiple two-sensor batteries** are now summed per-battery (previously
  only the first pair fed real-time power).

### 🧹 Cleanup & clarity
- 🚀 A draw found at boot while SEM wants idle is disabled on the first cycle
  (no wind-down grace for a session SEM never commanded).
- 🏷️ **"Assist Max" → "Battery → EV assist limit"**, **"Max discharge power" →
  "Battery total discharge limit"** — new help text explains the containment
  (assist is a sub-limit of the total), 15 languages.
- 🪦 Retired: the write-only "Vehicle Start Amps" knob (the start-kick
  auto-discovers the latch current since beta.57), three dead legacy consts
  maps, and the unused mid-session energy-target updater.

# [1.7.4-beta.10] — 03.07.2026

> **Pre-release.** Battery readings for every Energy-Dashboard battery mode.

### 🔋 Battery — full Energy-Dashboard schema support (#551)
- 🐛 **Batteries configured with HA's "Two sensors" power mode showed
  "sensor unavailable" and SOC 0%** (reported with a Fronius Verto 15.0 Plus).
  SEM only read the top-level `stat_rate` — which HA writes only for the
  Standard mode — and never read the dialog's SOC field at all.
- ✅ SEM now parses the complete battery `power_config` (**Standard /
  Inverted / Two sensors**) and the explicit **`stat_soc`** state-of-charge
  entity: real-time power is computed as charge − discharge for two-sensor
  setups, inverted sensors are flipped on read, and SOC comes deterministically
  from what you configured in HA — the auto-detect heuristics remain only as
  fallback. No SEM-side reconfiguration needed. (reported by @ebnerjoh)
- 🧪 Live-verified with the reporter's exact configuration shape; 9 new
  regression tests including the full Fronius pipeline; 4016 tests green.

# [1.7.4-beta.9] — 02.07.2026

> **Pre-release.** Root-cause fix: SEM never starts or holds a charge it didn't command.

### 🔋 EV charging — session ownership (#552)
- 🐛 **`solar_only` no longer drains the home battery at night.** When a KEBA
  auto-started at its stored setpoint (car retry, #315), the charge-stability
  deficit-hold engaged for the un-owned draw — rewriting decide()'s correct
  IDLE into a 10 A charge command and formally STARTing a session nobody
  decided, pulling ~4.9 kW from the battery in 90 s–4 min bursts every ~10
  minutes after sunset (~2 kWh per evening, observed on PROD 01.+02.07).
- 🛡️ **Fix = session ownership**: the stability layer only bridges/holds
  sessions it started itself, and the reconciler's idle grace applies only
  while winding down SEM's own stop — a draw appearing after idle has settled
  is disabled immediately, every cycle it persists.
- ✅ **Live-verified on PROD**: 30-min watch, two box auto-starts on the old
  cadence, both killed in ≤10 s with zero SEM starts (was 90–240 s each).
  ruflo-reviewed (0 blocker/0 high); 10 new regression tests; 4007 tests green.

# [1.7.4-beta.8] — 02.07.2026

> **Pre-release.** Documentation overhaul — no code changes.

### 📚 Documentation
- 🏬 **README reworked for the HACS default store** — the competitor comparison
  is gone (SEM speaks for itself), install instructions reflect the default
  store with an "Open in HACS" button.
- 📸 **All 8 dashboard tab screenshots recaptured** chrome-free (no side panel,
  no header) — including the previously missing **Configuration tab** shot.
- 🧹 **fold-entity-row retired from the required HACS cards** (zero uses since
  the onboarding banner became a bundled card) — required set is now card-mod,
  mushroom, apexcharts-card, sankey-chart.
- 🛠️ **Repo-wide accuracy pass, every fix verified against code**: the KEBA
  failsafe doc had its default inverted (managed-neutralize IS the default);
  retired battery knobs removed from the User Guide; EV-intelligence sensor
  list rewritten to the real per-charger entities; stale entity names,
  defaults, ADR field names and broken links fixed across 14 files.

# [1.7.4-beta.7] — 01.07.2026

> **Pre-release.** Dashboard config reachability + dormant arbitrage hardening.

### ⚙️ Configuration on the dashboard (#550)
- 🔋 **Battery SOC sensor picker** on the Config tab — if SEM didn't auto-detect
  your battery state-of-charge (e.g. Deye + Seplos: SOC is in the Energy
  Dashboard but shows unavailable), you can now point SEM at the SOC entity
  directly. No device-class filter, so any sensor is selectable. (reported by @praun)
- 🔌 **Heat-pump temperature-sensor picker** and **Invert SG-Ready toggle** added
  to the Config tab — both were structural settings with no UI (the toggle was
  reachable only via the native options flow).
- 🧭 **Structural toggles now batch through the Apply bar** like the entity
  pickers, so flipping one no longer fires its own reload and discards a staged
  edit. Full 15-language labels + help. ruflo-reviewed.

### 🔧 Internal — battery→grid arbitrage hardening (#533, still DEACTIVATED)
- 🛡️ The dormant arbitrage path was hardened ahead of a future v1.7.4 activation
  (view-plumbed market signals, a peak-aware export cap, and a clean cross-brand
  `STOP_FORCE_DISCHARGE` stop). **No behaviour change** — three gates keep it off
  (`_any_allow_arb=False`, migration v14 forces the toggle off, `allow_arbitrage`
  out of the selector). ruflo-reviewed; re-enable checklist documented.

# [1.7.4-beta.6] — 30.06.2026

> **Pre-release.** Completes the dashboard-first configuration work (#528).

### ⚙️ Configuration on the dashboard — completion (#528)
- 🔋 **Battery discharge-protection settings** now on the Config tab (Battery
  zones): protection toggle, max-discharge-power knob, and the discharge-limit
  entity picker — no more options-flow trip for these.
- 🔌 **Add / remove EV chargers from the dashboard.** A "+ Add charger" button
  appends a new charger (then wire it with the per-charger pickers), and each
  charger has a "✕" with an inline confirm (new `remove_charger` service,
  preserves siblings). The main reason to open the native flow is gone.
- 🧭 The native options flow stays as a headless fallback and now **points to
  the dashboard Config tab** (translated, 15 languages).
- ruflo-reviewed; full suite green; add/remove live-verified on HA-TEST.

# [1.7.4-beta.5] — 30.06.2026

> **Pre-release.** Currency fix for high-denomination currencies.

### 💱 Tariff — currency-agnostic price bounds (#549)
- 🐛 **Price entities were unusable for high-denomination currencies.** With HA
  currency set to LKR (or IDR/VND/JPY/…), the import/export rate, cheap/expensive
  threshold and demand-charge entities showed the right unit (`LKR/kWh`) but kept
  EUR/CHF-scale caps (export max 0.5), so a real 22 LKR/kWh tariff couldn't be
  entered. The ceilings are now currency-agnostic (rates/thresholds 10000,
  demand 100000) across all three surfaces — number entities, the Config-tab
  inputs, and the OptionsFlow selectors. Fine steps kept, so decimal currencies
  (CHF/EUR) are unchanged. (by @hrdilshan in #549)

# [1.7.4-beta.4] — 30.06.2026

> **Pre-release.** Dashboard-first configuration — the Config tab, made colorful and easy (#528).

### ⚙️ Configuration on the dashboard (#528)
- 🎨 **The Config tab is now the home for post-setup configuration, in the colorful
  battery-card design language** — accent sliders with value chips, an SOC-zone
  strip, and per-section accent theming across every section (no more flat
  stepper rows). You rarely need HA's Settings → Devices → Configure flow.
- 🔌 **Batched Apply for entity wiring** — entity pickers that reload the entry
  now stage their edits and commit in **one** reload via a sticky Apply bar,
  instead of a reload per field. Tunables still save live.
- 🧭 **First-run completeness guide** — the Setup overview shows a progress bar +
  "Set up →" chips that jump to the unconfigured section, and recedes to a green
  "All set up" when done.
- 🌍 Full **15-language** translations for the new UI; added the missing
  hot-water power-sensor picker. ruflo-reviewed.

# [1.7.4-beta.3] — 28.06.2026

> **Pre-release.** Adds per-charger actuation diagnostics for the "SEM says stop but the box keeps charging" class (#548).

### 🔌 EV — actuation diagnostics + stop-not-taking signal (#548)
- 🔍 **The Diagnose button now shows the actuation truth.** A new per-charger
  `ev_actuation` block reports the adapter, the status sensor's raw value +
  classification, the enable-switch entity + state, whether SEM can drive it
  (`enable_state`), the `actual_charging`/`is_self_charging` verdicts, the
  believed setpoint vs live power, and the reconciler's last desired state +
  actions + a `stop_commanded_while_drawing` counter. One screenshot now tells
  "SEM never issued the stop" apart from "SEM issued it but the box ignored it"
  — no more multi-round triage.
- ⚠️ The reconciler now **logs a warning** ("commanded STOP N× but charger still
  drawing") when a stop isn't taking, so an ignored stop is no longer silent.
- Note: the decision/stop arc itself is verified sound — a max-SOC ceiling stops
  promptly on a responsive charger (HA-TEST mock: 6 A → 0 A in ~20 s). When a
  real charger keeps drawing, the cause is downstream of SEM (HA↔charger link or
  the charger ignoring the stop), which this diagnostic now pinpoints.

# [1.7.4-beta.2] — 27.06.2026

> **Pre-release.** Generalises the Wallbox status-enum fix to every charger brand.

### 🔌 EV — cross-brand status-enum classifier (#548)
- ✨ **Every charger brand now uses its STATUS enum (authoritative) instead of the
  cloud-lagged power reading** to decide "is it charging?" and "can SEM stop it?".
  The Wallbox #548 fix is generalised into one shared classifier
  (`coordinator/charger_adapters/status_enum.py`) mapping each brand's real
  HA-integration status strings — Easee, Zaptec, go-e, Ohme, OCPP, Alfen,
  Heidelberg, Wallbox — to charging / not_charging / locked. `GenericAdapter`
  reads it over the already-configured status sensor; KEBA stays power-based.
  Strictly additive: no status sensor / unrecognised string → unchanged
  power-based behaviour. App/cloud-locked states (Eco-Smart, Easee smart-start,
  Ohme pending-approval, Alfen in-operative) now surface "can't stop — leave
  eco-smart" instead of spinning silently.
- 📝 `docs/MULTI_CHARGER.md` gains a per-brand reference table (verified against
  each HA integration source) + actuation caveats (Easee/Zaptec/go-e set-0≠stop;
  Ohme is on/off only; Heidelberg reg-261 reboot revert).
- ✅ Verified: per-brand classifier tests, every-mode KEBA parity, control-pattern
  coverage, and a live HA-TEST mock walk (Zaptec/Alfen charging strings detected
  over 0 W; Eco-Smart lock surfaced). Full suite 3986 green.

# [1.7.4-beta.1] — 27.06.2026

> **Pre-release.** Opens the 1.7.4 line. Headline: Wallbox now stops reliably in
> OFF mode (and every other mode reacts exactly as KEBA does). Battery→grid
> arbitrage remains **deactivated** (still tracked for 1.7.4 stable in #533).

### 🔌 EV — Wallbox status-enum adapter (#548)
- 🐛 **Wallbox kept charging in OFF mode.** The reconciler judged "still drawing?"
  from the power reading, but Wallbox power arrives over a ~90 s cloud poll — so
  OFF mode read "already stopped" on the first cycle and quit re-issuing the stop
  while the box kept charging. The firmware **status enum** is now authoritative
  for the Wallbox (evcc-connector concept, no cloud transport needed):
  `actual_charging` trusts `Charging`/`Paused`/… over the lagging power, and
  app-locked states (Eco-Smart / Scheduled / Power-Sharing / Locked) surface a
  clear "can't stop — leave eco-smart" repair instead of spinning silently.
  Strictly additive: no status sensor ⇒ unchanged power-based behaviour; KEBA
  untouched.
- ✅ **Parity:** all four charge modes (off / solar_only / min_plus_solar /
  always_max) now react on the Wallbox exactly as they do on KEBA — verified by
  `tests/test_548_mode_parity.py` and a live HA-TEST mock-Wallbox walk.
- 📝 `docs/MULTI_CHARGER.md` documents the status-enum road for the next brands
  to migrate (Easee / go-e / OCPP / Ohme / Alfen).

# [1.7.3] — 27.06.2026

> **Stable release.** Consolidates the 1.7.3 beta line (beta.1 → beta.65, detailed
> below) plus the final hardening below. Headline: a big EV-charging reliability
> pass (steady offer, clean stops, max-SOC ceiling, battery-assist), the
> single-source EV decision architecture, multi-battery + per-battery modes,
> grid-sign auto-detection, the audit-telemetry program, and a large census /
> dead-code cleanup. Battery→grid arbitrage remains **deactivated** (tracked for
> v1.7.4 in #533).

### 🔌 EV — single-source stability bridge (#461)
- 🐛 **The EV could grid-hold at low battery SoC and never settle.** The anti-flap
  "disable bridge" re-derived solar/surplus/SoC/tariff and held minimum current
  after `decide()` had already structurally idled, then re-engaged in a loop —
  importing grid indefinitely (PROD-confirmed via the strategy-sensor history).
  `decide()` is now the single source of truth: it classifies each IDLE as
  transient (hold) vs structural (stop) on `ChargerDecision.bridgeable`, and the
  stability layer simply honours the flag — no re-derivation — plus a durable
  stop and a post-stop settle so a winding-down car can't re-open the hold.
  (by @guidoeberle in #461)

### ⚙️ Config — knobs apply without a reload (#547)
- ✨ **Changing a setting now takes effect live.** Scalars cached on a controller
  at construction (regulation offset, heat-pump / hot-water tunables, per-charger
  EV priority + min/max current + shed priority, tariff rates) used to need a full
  integration reload. `refresh_runtime_config()` now pushes them into the live
  controllers on every config change — a refresh, not a rebuild, so timers, cost
  accumulators and smoothing windows are preserved. (by @guidoeberle in #547)

### 🔌 EV / Load management — single-writer peak control (#461)
- 🐛 **Load management could fight the EV controller (or silently fail to shed it).**
  The EV is now removed from load-management's per-cycle device shedding entirely:
  daytime EV charging is solar-driven (no grid peak) and the night grid top-up is
  already peak-managed by the night planner — both through the single
  `decide()`/reconciler writer. The old side-channel (`number.set_value 0` /
  `keba.set_current 0`) fought the reconciler heartbeat on KEBA and mis-read
  number-entity Wallbox chargers, so it could only flap or fail. (by @guidoeberle in #461)

# [1.7.3-beta.65] — 26.06.2026

> Hardens the battery-protection limit against an EV-ramp sensor-lag spike.

### 🔋 Battery — spike-proof the discharge-protection limit (#536)
- 🐛 **A fast EV load ramp could briefly over-allow battery discharge.** When the car ramps hard (e.g. `always_max` to 10 kW), the grid meter registers the import a cycle before the KEBA `ev_power` sensor reports the draw, so the energy-balance `home_consumption_power` transiently inflates by ~the car's draw (seen on PROD: spiked to 9213 W). Since the discharge-protection clamp limits the battery to the home load, that spike briefly raised the limit and let the inverter feed a little battery into the car below the buffer. `_smooth_home_consumption` now has a **symmetric upward-spike guard** (it already held the *dip* direction): a one-cycle jump above the last value + 2 kW is treated as the EV/grid sensor lag and the last good value is held for up to 2 cycles; a genuine, persistent rise (an appliance) is accepted once the short window expires. (by @guidoeberle in #536)

# [1.7.3-beta.64] — 26.06.2026

> The battery now stops feeding the EV at the buffer SoC floor — cleanly.

### 🔋 Battery — enforce the buffer SoC floor (#536 follow-up to #545)
- 🐛 **The battery drained into the EV below the buffer SoC.** With #545's aggressive assist, a high house load kept surplus just above the gate while SoC fell below the buffer (PROD: 83% with an 85% buffer), and the discharge clamp — which keyed only on `surplus < gate`, never on SoC — let the inverter keep feeding the car well below the user's reserve. The clamp now also fires when **`SoC < buffer_soc`**, so below the buffer the battery is reserved for the house **in every zone, regardless of surplus**. Above the buffer the #545 assist is unchanged. (A zone-by-zone audit confirmed the EV engine was already correct in all four zones — the gap was isolated to the battery clamp.) (by @guidoeberle in #536)
- 🐛 **The EV stop-bridge never fired with a bursty car.** The disable-bridge stop timer only accumulated while the car drew continuously, and the draw-latch was wiped every deficit cycle — so a Renault Zoe blipping between pulses reset the timer each cycle (170→99→20 s, never reaching 180 s) and the contactor never opened. The latch now persists through the bridge (refreshed on each real draw, cleared only on a genuine stop), so the car stops cleanly instead of grid-charging indefinitely. (by @guidoeberle in #536)

# [1.7.3-beta.63] — 26.06.2026

> Cleanup: retire the EV-charging diagnostic instrumentation now that #545/#546 are fixed.

### 🧹 Instrumentation retired (#545 / #546)
- 🧹 The `EV-OFFER-PROBE` reconciler log is **downgraded to DEBUG** (and gated on DEBUG, so it does no per-cycle work on a normal INFO PROD) — it served its purpose pinning the KEBA 6↔9 A flap (#546, fixed). Re-enable with debug logging if a future flap needs re-diagnosing.
- 🗑️ Removed the observe-only **`sensor.sem_diag_ev_assist_headroom`** diagnostic and its per-cycle computation — instrumentation for the #545 chicken-and-egg, now fixed and closed. (Swept the sensor description + population + strings/15 translations.)

# [1.7.3-beta.62] — 26.06.2026

> The home battery now empties into the EV at high SoC instead of sitting idle.

### 🔋 EV — max out the battery into the car (#545)
- ⚡ **"Max out till self-consumption":** when the home battery is in the assist band (SoC ≥ the Buffer SoC) and there's real solar surplus past the Solar Gate, SEM now offers the **full** battery-assist potential — it raises the offered amps so the inverter discharges the battery **into the car, down to the Buffer SoC** (the self-consumption reserve floor), instead of only topping the car up to the charger minimum. This fixes the chicken-and-egg where a **full battery sat idle while the EV grid-charged** (observed live: at 100% SoC, SEM offered only ~8 A, the car drew ~3 kW from solar, the battery never assisted, and a grid night-charge was still needed). The assist self-tapers as SoC falls toward the Buffer and is off-limits below it, so the battery is never drained past the floor. Solar-gated; pure amps — SEM commands no battery directly, the inverter's self-consumption does the discharge. Aligned across both budget layers (`decide.battery_assist_budget_w` + the canonical `calculate_canonical_ev_budget`) so they agree (#282). Docs updated (EV_CHARGING_LOGIC, ARCHITECTURE). (by @guidoeberle in #545)

# [1.7.3-beta.61] — 26.06.2026

> Fixes EV charging running past the configured max SOC during solar charging.

### 🔌 EV — stop at max SOC (#548)
- 🐛 **The EV charged past its configured max SOC** in solar/surplus charging (reported by @RienduPre, Wallbox Pulsar Plus). The max-SOC ceiling (`soc_limit_active`) only reached the retired ChargingStateMachine (→ `SOLAR_TARGET_REACHED`), and that state was then **overwritten by the per-charger decision** — while the `decide()` day path has no max-SOC check of its own, charging whenever surplus ≥ min. So nothing actually stopped the charge at the ceiling. Now the ceiling is plumbed into `ChargerView.soc_ceiling_reached` (from the value the coordinator already computes) and **guarded in `decide()` before mode dispatch**, so **every** mode (`solar_only`/`min_plus_solar`/`always_max`/`solar_plus_cheap`) stops at the max SOC. kWh-target users are unaffected (their max is effectively unlimited). The stop now reads as **"Target reached"**. (by @guidoeberle in #548)

# [1.7.3-beta.60] — 26.06.2026

> Census cleanup, continued: removed dead published sensors and added a CI guard
> so the dead-surface class can't regrow. Each removal re-verified live (3 of 19
> candidates turned out to have a consumer and were kept).

### 🧹 Dead sensors removed (#544)
- 🗑️ **Removed 16 orphan sensors** — published, enabled-by-default, but read by no card, generator, or decision (pure entity clutter): the fleet EV-intelligence cluster (`ev_taper_ratio`, `ev_taper_minutes_to_full`, `ev_estimated_soc`, `ev_last_full_charge`, `ev_energy_since_full`, `ev_predicted_daily_consumption`, `ev_battery_health`), the forecast-accuracy cluster (`forecast_accuracy_today`, `forecast_accuracy_7d`, `forecast_deviation_kwh`, `forecast_corrected_tomorrow`, `forecast_power_now_w`, `forecast_power_next_hour_w`), and the predictor outputs (`predicted_consumption_next_hour`, `predicted_consumption_today_kwh`, `predicted_solar_next_hour`). Swept descriptions + population + metadata across `strings.json`/`icons.json`/15 translations. **Breaking** for any custom dashboard/automation that referenced these. Kept (verified live): `ev_taper_trend` (diagnostic), `forecast_correction_factor` & `forecast_history_days` (read by the dampening/correction sensor attributes). (by @guidoeberle in #544)

### 🔒 Census cleanup closed (#543)
- ✅ With #544 done, the census cleanup (#543) is complete — the knob-reader contract lint (`tests/test_knob_wiring.py`) was already in place from the 2026-06-25 chunk and confirms all 26 NUMBER knobs are wired. The one remaining item (knobs read only at controller construction don't apply until reload) is a behavioral fix, split to #547.

# [1.7.3-beta.59] — 26.06.2026

> EV-decision coherence: the overnight battery-drain root cause is fixed, and a
> verify-first audit retired/clarified the confusing knobs around it. Live-confirmed
> on PROD (KEBA P30 + Renault Zoe) across all four charging modes.

### 🔋 Battery — overnight drain root cause (#536)
- 🐛 **The home battery drained overnight to feed the EV** (PROD 93→41 %). The discharge-protection clamp gated on the *instantaneous* draw flag (`ev_charging`), which a bursty car (Renault Zoe) toggles on/off every few seconds — so the clamp dropped in the gaps, the battery discharged freely, and that energy fed the next pull. The clamp now gates on **`ev_connected`** (vehicle plugged in), so it **holds steady** through the car's pulses. Live-verified: `battery→ev = 0 W` in every solar mode all afternoon. (by @guidoeberle in #536)

### 🧹 Config — verify-first knob cleanup (#536)
- 🧹 **Removed three dead/redundant battery knobs** after auditing each live (two of the original four turned out to be live and were handled, not blindly cut): `battery_minimum_soc` (labelled "hard stop" but never gated discharge — its only live use, the empty-ETA, now references the real floor `battery_priority_soc`), `battery_assist_floor_soc` (shadowed by `buffer_soc` — folded in as the single assist floor), and the comment-only `battery_hold_solar_ev`. (by @guidoeberle in #536)
- 🐛 **Fixed the `minimum_solar_power` default inconsistency** — a legacy config missing the key silently used 200 W while a fresh install seeded 1000 W; the fallback now matches the seeded default. (by @guidoeberle in #536)
- 📝 **Corrected the misleading "Surplus floor" help text** — `minimum_solar_power` gates **raw PV production** ("is the sun up"), distinct from `battery_assist_min_surplus` (export surplus); clarified in English + 15 translations. The two were *not* collapsed — they measure different quantities and both feed the #461 deep-deficit logic. (by @guidoeberle in #536)

### 🗑️ Internal — legacy retirement, stage 1 (#536)
- 🗑️ Removed the deprecated proportional `FlowCalculator.calculate_energy_flows` (zero production callers since #282; the timing-aware `integrate_energy_flows` is canonical). (by @guidoeberle in #536)

**Thanks** to @guidoeberle for the PROD live-testing across all four charging modes.

# [1.7.3-beta.58] — 26.06.2026

> Steady EV charging — live-confirmed on a real KEBA P30 + Renault Zoe: the
> offered current went from **366 changes/evening** (6↔9 A sawtooth, car in
> standby) to **0 changes in 25 min** (rock-steady 8 A, car drawing ~3.1 kW).

### 🔌 EV charging — steady offer (neutralize the failsafe, then track like evcc)
- 🐛 **The offered current flapped 6↔9 A every few seconds**, so a steady-needing car (Renault Zoe) sat in standby. Root cause: the KEBA reverts to its built-in **6 A failsafe** between SEM's writes and SEM re-wrote 9 A every 5 s — a sawtooth the car can't charge through. Live testing on a real P30 showed the failsafe **can't be disabled** over UDP (the box keeps it — likely a safety design). So SEM now **neutralizes** it: it arms a **long (10-min) non-tripping, persisted** failsafe with the fallback at your **charging floor** — it overwrites the box's short built-in one, the per-cycle writes keep it from ever tripping, and a genuine controller-death lands the car on the floor (not 6 A). No more flap. (#546)
- ⚡ With the offer steady, the current tracks surplus **evcc-style** — a ≈30 s cadence with a 2 A deadband (not a multi-minute freeze), with evcc-aligned **1 min start / 3 min stop** delays (disable delay 300→180 s). (#546)
- ⚙️ `keba_arm_failsafe` (default **on** = managed-neutralize). Set it **off** for boxes that *can* disable the failsafe at the charger (evcc-style); SEM then leaves it alone and raises a **Repair** (Settings → Repairs) guiding you to disable it, with a step-by-step link. (#546)
- 🔭 The `EV-OFFER-PROBE` diagnostic now reads the **live** offered-current sensor (`ev_current_sensor`) instead of the static config cap, so it can actually show hardware drift. (#546)

### 🛡️ Observer mode / wiring
- 🐛 **The observer-mode switch was a silent no-op.** Its entity-id constant held the `domain.object` form and the coordinator re-prefixed it (`f"switch.{…}"`) into a dead three-segment id, so the lookup always returned `None` and toggling the switch never made SEM hands-off. On a test bench that shares the *same physical* inverter/battery as production, this meant the test instance kept driving the real hardware while the switch showed "on". Fixed the lookup, made the switch push its state straight onto the coordinator, and guarded the per-cycle pull so a transient `unavailable` switch state can't clobber it back on. Two follow-on bugs surfaced once the switch finally engaged — most notably the read-only setpoint-zeroing iterated the multi-charger **dict keys** (crashing the whole update cycle) — and are fixed. Contract tests lock the class: every entity-id constant must be a valid 2-segment id, the coordinator must not re-prefix one, and observer mode must hold across transient unavailability. (#542)

### 💰 Costs
- 🐛 **Monthly and Yearly costs were identical.** The yearly seeding backfilled the year's *energy* from the recorder but never the *cost* accumulators, so yearly cost only held the live (this-month) portion and equalled the monthly figure. Now the yearly cost is seeded from the seeded yearly energy × the average rate — and an already-seeded install (where only the cost was missing) is backfilled too. The pre-tracking backfill is an **estimate** on a dynamic tariff (the recorder has historical energy, not historical hourly prices); the live portion stays exact. Confirmed the live per-cycle cost is already tariff-correct (static/dynamic/calendar all priced at the current rate each cycle). (#536)

# [1.7.3-beta.57] — 25.06.2026

> Stable (1.7.3) stays **on hold** — the EV-charging rework below needs PROD soak.

### 🔌 EV charging — steady, unified, honest
- 🚗 **Rock-steady charging.** A Renault Zoe R that oscillated 5 kW↔0 now holds a flat 5 kW. Four root causes: single-charger **draw-detection** bug (`build_view` now falls back to the fleet `ev_power`, so SEM actually sees the car drawing); **latch hysteresis** (hold the current through transient 0 W dips instead of re-starting); **steadier guards** (90 s change interval / 2 A deadband / 5-cycle median); and the config insight that this Zoe's *sustain* floor is **~10 A, not 6** (it drops at 6 A). The oscillation was SEM *changing* the current, not the level. (#536)
- ☀️🌙 **Day + night unified.** One charging behaviour (latch → hold → auto-escalate) across solar and night, with a **bounded** start-escalation (caps at `max(target, 10 A)`, gives up after 90 s on a refusing car — no more climbing to 32 A). (#536)
- 🔢 **Night-target counter fix.** The planner over-charged past the target after restarts (it used a restart-volatile per-charger integrator); it now uses the persisted `daily_ev` — the figure the dashboard shows. (#536)
- 🛑 **Observer mode now hands-off for the EV too.** Zeroes the published commanded current so an external bridge automation or a second SEM instance can't drive the charger while observing. (#536)

### 📊 Dashboard
- ⚡ EV card shows the **commanded current** next to CHARGING (e.g. `CHARGING (8 A)`) — what SEM transmitted vs the car's real draw. (#536)
- 🩹 Header and EV-card power/state no longer contradict (both derive from the same per-charger power). (#536)

### 🧹 Cleanup
- Removed dead Advanced settings `current_delta` / `power_delta` / `soc_delta` and the dead `ev_stall_cooldown` entity, plus the orphaned solar-stability layer. (#536)

> **Known / open:** a self-starting KEBA still auto-tops a not-full car past the kWh target (proper fix: `keba.set_energy` so the box enforces its own stop); a test instance must never point at production hardware.

# [1.7.3] — STABLE

> Rolls up the 1.7.3 beta line (beta.2 → beta.56 + stable prep). The dated
> `beta.*` sections below are the detailed per-build history; this is the headline
> summary of what changed since **1.7.2**. The biggest themes: EV charging is
> reliable in every mode, the home battery is protected from feeding the car
> without sun, and multi-battery + grid-sign + dashboard all got a major pass.

## ⚡ EV charging — rock-solid in every mode
- **Charger state reconciler (#392).** The per-cycle imperative actuator (which
  spammed `keba.disable` 391× and dropped KEBA to 6 A) is replaced by a
  desired-vs-observed reconciler: it issues the *minimum* commands to converge and
  then leaves the charger alone. Idempotent idle, heartbeat re-writes, failsafe
  armed once per session.
- **Enable-switch reconciliation + backoff (#536).** For switch-driven chargers
  (Wallbox etc.) SEM reconciles the enable switch and backs off (stops fighting +
  surfaces a repair) if something keeps toggling it.
- **No more expensive-grid / dead-solar charging (#461, #524).** The EV no longer
  drains the battery to hold a dead solar session, and stops pulling from grid after
  a cheap window ends.
- **Charge modes:** `solar_only`, `min_plus_solar`, `solar_plus_cheap`,
  `always_max`, `off` — each with a one-line dashboard hint.
- **EV target type:** daily **kWh** target or **vehicle SOC %** (when a vehicle SOC
  sensor is configured). Per-vehicle minimum current (#440), independent **surplus
  vs shed** priority per charger (#470).

## 🔋 Battery protection & control
- **Solar Gate (#537).** The home battery only assists the EV when there's real
  solar surplus ≥ a configurable gate (default **1200 W**) — in *any* mode. Set it
  to **0 W** to allow battery support everywhere, including overnight. Fixes the
  overnight battery-drain-into-the-car class of bug.
- **Multi-battery control + per-battery modes (#523).** Per-battery control entities
  and five modes — `auto`, `self-consumption`, `force-charge`, `force-discharge`,
  `off` — plus zero-config Huawei forcible discharge and a corrected SG-Ready relay
  map for heat pumps.
- **Idempotent Huawei discharge-limit write (#538).** Stopped re-writing the
  unchanged discharge limit every cycle, which had been flooding the serial Modbus.
- **Battery → grid export arbitrage (#523)** shipped in beta but is **deactivated in
  this stable** pending more soak (#533, re-enable targeted v1.7.4).

## 🧭 Grid sign, heat pump, tariffs
- **Robust grid-sign autodetection + one-tap fix (#461).** Solar-anchored detector
  with a `Fix grid sign` / `Reset` button and a `flip_grid_sign` service; locks
  survive restarts (#476).
- **Heat pump / hot water (#508).** Surplus activation fires, boosts on the *true*
  house surplus, stands down under peak; relay-failure safety.
- **Tibber Grid Reward price arrays (#491)** + forecast dampening with the correct
  sun window (#416).

## 🖥️ Dashboard & i18n
- **Solar Gate** stepper, per-charger **plan strip**, price card, config-card
  cleanups; system-diagram and 7-day-chart fixes.
- **Time labels render in HA's home timezone**, DST-aware, not the viewer's browser
  (#539).
- **Time charts roll the day boundary** (#541) — a long-open app no longer shows
  *yesterday's* data in *today's* chart; the relative window auto-refreshes on a
  timer and on app resume / tab focus.
- **EV Power chart no longer magnifies standby noise** (#541) — a plugged-in idle
  car's ~130 W standby used to auto-scale to fill the whole chart and read like a
  real charge; the axis now has a 2 kW floor so standby renders flat near zero while
  real charges still scale up.
- **Full 15-locale dashboard translations** — every runtime card string is now
  translated (previously ~35 keys fell back to English outside en/de/nl), guarded by
  a new parity test.

## 🔍 Stability & review
- Pre-stable review batches (#485, #531, #535) — forced-charge restored, per-battery
  edge cases, robustness; cold-start/restart hardening (#532). Final ruflo pass:
  today-plan HA-tz day classification, chart tz try/catch, `decide_battery` /
  `#538` comments, and a default-gate test.

# [1.7.3-beta.56] - 23.06.2026

## 🕐 Time labels show HA's timezone, not the browser's (#539)

Every time label on the dashboard rendered in the **viewer's browser timezone**.
A browser/OS stuck on standard time (CET) showed summer-time data **one hour
early** (a 12:00 CEST chart bucket displayed as 11:00). Fixed across the board —
all now format via HA's configured home timezone (`hass.config.time_zone`, IANA
zone → DST-aware), correct regardless of the viewing device. Display-only; the
underlying data timestamps were already right.

- **Time-series charts** (`sem-chart-card`: EV power, solar, battery, flows…) —
  x-axis labels **and** tooltip times.
- **Shared `semFormatTime`** helper → fixes the today-plan times and the system
  diagram's sunrise/sunset.
- **Price card** tariff-window times, **EV status card** (axis ticks + next-cheap
  window), **weather card** clock + forecast days.

# [1.7.3-beta.55] - 23.06.2026

## ⚡ Idempotent Huawei discharge-limit write (#538)

PROD modbus was throwing read **timeouts and out-of-order responses** because
SEM rewrote the Huawei battery discharge limit (`5000 W`, the unclamped NORMAL
default) **every coordinator cycle** even though it never changed — a redundant
write that collided with the huawei_solar read coordinators on the single serial
connection and ballooned cycle times to 13–28 s.

- `HuaweiBatteryAdapter._apply_discharge_limit` now **skips the write when the
  control entity is already at the target** (compared against the live entity
  state, so an external change is still re-asserted; writes when the state is
  unknown/unavailable). The per-cycle NORMAL spam is gone.

*(PROD-side, separate from the release: the `Huawei … Abfrage` polling
automation was slowed 10 s → 15 s to further cut modbus read pressure — the
native huawei_solar update interval is hardcoded at 30 s and not configurable.)*

# [1.7.3-beta.54] - 23.06.2026

## 🧹 UI polish

- **Removed all `evcc` references** from the dashboard help texts and the code —
  the surplus enable/disable delays are now described in plain terms (hysteresis
  enable/disable timers, deficit-persistence) without the external project name.
- **Added the missing help text** for **Regulation Offset** in the Advanced section
  (a small power buffer kept as grid export so SEM doesn't risk importing while
  regulating surplus charging).

# [1.7.3-beta.53] - 23.06.2026

## 🔋 Battery only assists the EV when the sun is out (#537)

The home battery was draining into the car overnight in `min_plus_solar` (PROD,
~6.5 kWh in one evening) — and in `always_max` — because battery-assist ran on a
sunset clock, not on actual solar. A single **Solar Gate** now governs it, in
**every** charging mode:

- **New "Solar Gate" knob** (`battery_assist_min_surplus`, default **1200 W**) on
  the Control tab and in the integration options. Below this much real solar
  surplus the battery is reserved for the house and the car draws from grid + solar.
- **Set it to 0 W** to let the battery support the EV everywhere, including
  overnight (opt-in — the previous behaviour).
- Enforced in two places so it can't leak: the EV budget (`min_plus_solar` /
  canonical battery-assist) and the battery discharge clamp (`decide_battery`),
  which now protects the battery in **any** mode incl. `always_max` and replaces
  the old night-only / `hold_solar` protection (gate = 0 restores it everywhere).

Verified on HA-TEST (deployed decision table correct incl. `always_max`); full
suite 3797 green.

# [1.7.3-beta.52] - 22.06.2026

## 🔌 EV charger reliability hardening (#536) — verified live on HA-TEST

A focused pass on the EV charger control, all confirmed live against a KEBA and a
switch-controlled Wallbox sim on HA-TEST:

- **Enable-switch backoff.** When a charger keeps flipping its *own* enable switch
  back off (Wallbox Eco-Smart / Autostart, or a conflicting integration), SEM no
  longer fights it forever — it re-asserts a few times, then **stops and surfaces a
  repair** ("charger auto-pausing — disable Autostart/eco-smart"), probing again
  periodically. This kills the start/stop oscillation.
- **`input_boolean` start/stop entities** are now driven like `switch.*` ones, so
  `off`/`idle` reliably open the contactor (previously enable worked but disable
  didn't).
- **No more `CHARGE_MAX` clamp-drift.** `always_max` resolves to the charger's
  *effective* max (config max clamped to the control entity's max) instead of the
  hardware max, so it stops spamming `WRITE 32A` + `clamping 32 A → 16 A` every
  cycle and converges cleanly.
- **Honest charger state.** When SEM is commanding a charge but the car isn't
  actually drawing (full / not ready), the dashboard now reads **"ready"** instead
  of "charging at 0 W" (power-based, debounced — never changes the command).

KEBA is unaffected by all of the above (no enable switch). The #392 idempotency
(no `keba.disable` spam) and the battery "discharge clamped to home load during EV
charging" protection were both re-verified live.

## 🧹 Internal: charger reconciler is now the sole actuation path

Removed the dead legacy EV-control code (`_execute_ev_control`, the legacy
`actuate()` body, the unused adapter idle-debounce) now that the desired-vs-observed
**reconciler** owns all charger actuation — net **−1073 lines**, with the self-resume
behavior moved to reconciler-native test coverage. No behavior change.

# [1.7.3-beta.51] - 22.06.2026

## 🔌 Wallbox "commanded but 0 W" — SEM now reconciles the enable switch (#536)

A Wallbox (and any charger controlled by a current **number** + a separate
**enable switch**) could sit at *Connected, Always-max, commanded 16 A, **0 W***
and never start, in any mode. Cause: SEM turned the enable switch on **once** at
session start and then never checked it again — if the switch later went off
(Wallbox auto-pause, locked, eco-smart mode, or an external toggle), SEM kept
writing the current to a charger whose contactor was open.

The charger reconciler (from beta.50) now treats the **enable switch as observed
state**: every cycle it reads the switch's *actual* state and re-asserts it when
charging is wanted and it's off — idempotent, and keyed on the switch state (not
power) so a full-but-plugged car never causes switch churn. A switch that's
**unavailable/locked** (e.g. eco-smart mode) is now surfaced as a repair instead
of silently swallowing every charge command.

> This was **not** the `ev_charger_service: "0"` value some configs show — that's
> been harmless since beta.43 (it's normalised to "use the number entity"). The
> real gap was the un-reconciled enable switch.

# [1.7.3-beta.50] - 21.06.2026

## ⚡ EV charging is now rock-solid in every mode — charger state reconciler

The KEBA kept dropping to 6 A / pausing, and we'd shipped five separate patches
chasing it. They all treated symptoms of one root cause: **SEM re-issued a
hardware command to the charger every ~10 s cycle**, whether or not anything had
changed. PROD logs caught it doing `keba.disable` **391 times in a row** on an
already-open contactor.

This replaces the per-cycle imperative actuator with a **desired-vs-observed
reconciler** that issues the *minimum* commands needed to converge, then leaves
the charger alone:

- **Idle / off issue zero redundant commands** — the contactor is opened once,
  not re-disabled every cycle (the 391× spam is gone).
- **Holds your commanded current** like a fixed-current charge, but solar-aware.
- **Drift correction** — if the box silently reverts to its 6 A failsafe floor,
  SEM re-asserts your target on the next cycle.
- **Failsafe armed once per charge episode** (not re-armed every cycle), kept fed
  by the per-cycle write heartbeat.
- **Same convergence path for all modes** (off / always_max / min_plus_solar /
  solar / solar_plus_cheap) — no mode-specific surprises.

Live-verified on HA-TEST across charge and off; full suite 3791 green. (#392)

> Note: a fixed-3-phase KEBA P30 still can't physically charge below ~4.1 kW, so
> in solar modes it will still *pause* when surplus is genuinely below the
> 3-phase floor — but now it pauses cleanly and predictably instead of bouncing.

# [1.7.3-beta.49] - 21.06.2026

## 📊 EV charging-power chart: no more phantom 11 kW peaks

The "EV Charging Power" chart (solar + battery + grid → EV, stacked) showed
impossible peaks — an ~11 kW "grid" spike while the EV only ever drew ~4.4 kW.
Cause: the chart plotted each source's per-hour **maximum** and then stacked
them. The three sources are complementary (when solar peaks, grid is 0), so
their maxes occur at different moments and stacking them triple-counts — the
stacked maxes far exceed the real instantaneous total. (There was never a real
11 kW; the grid genuinely peaked at ~4.9 kW, so peak management was unaffected.)

Stacked power charts now plot the per-bucket **mean**, so the components sum to
the real total and the area integrates to real energy. Non-stacked charts keep
the max so peaks stay visible.


# [1.7.3-beta.48] - 21.06.2026

## 🔧 Restore the second EV minimum + fix the solar-power config key

- **"Vehicle Min Amps" is back as a tile** (beta.47 hid it when equal to "Min
  Amps"). A charger legitimately has TWO minimums and both should be visible:
  **Min Amps** is your own floor (lowest current SEM bothers charging at);
  **Vehicle Min Amps** is your car's floor (some cars won't charge below ~8–9 A).
  The effective floor is the higher of the two. Only the genuinely-dead "Vehicle
  Start Amps" tile stays hidden.
- **Solar-power config key aligned.** The setup/options flow wrote `min_solar_power`
  while the runtime slider and the decision read `minimum_solar_power` — so a value
  set during setup never reached the runtime. The flow now writes the same key;
  existing `min_solar_power` values are still honoured.


# [1.7.3-beta.47] - 21.06.2026

## 🧹 EV current knobs cleaned up + two correctness fixes

Following the KEBA failsafe fix, a review of the EV current path (the user's
"three values, such a mess") and two confirmed bugs:

- **Removed the dead "Vehicle Start Amps" tile.** `initial_current` (10 A) is
  not read by the live charging path — the start ramp uses the Min Amps floor —
  so it was a settable tile that did nothing but confuse. Hidden from the card.
- **"Vehicle Min Amps" only shows when it differs from "Min Amps."** It defaults
  equal to the min, so it was a redundant second 9 A; now it only appears once
  you actually raise it to override a car that ignores the min (or in help mode).
- **The "Minimum Solar Power" slider now works.** Its value (`minimum_solar_power`)
  was never wired into the decision — the solar floor / deep-deficit guard always
  saw the 200 W default regardless of the slider. Now honoured (200 W fallback
  when unset).
- **1-phase chargers: amps↔watts floor fixed.** The MIN_PV / BATTERY_ASSIST / NOW
  power floors hardcoded 3 phases × 230 V, so a 1-phase charger's floor was 3× too
  high. Now uses the configured `ev_phases` / `ev_voltage` (3-phase unchanged).

Plus a recorded `min_plus_solar` steady-hold scenario pinning that the commanded
current doesn't flicker on steady surplus.


# [1.7.3-beta.46] - 21.06.2026

## ⚡ The real fix: KEBA stops reverting to 6 A (failsafe was misconfigured by SEM)

Root cause of the 6 A drops (car pausing to ~120 W mid-charge): on session start
SEM called `keba.set_failsafe(timeout=0, fallback=6)` to "disable" the failsafe —
but the HA service rejects `timeout=0` (its minimum is 1), so the call **failed
silently** and the box kept an active failsafe with a **6 A fallback** that
tripped during charging. SEM was, in effect, arming the gun it thought it had
unloaded (confirmed against evcc's KEBA handling — evcc never sets a 6 A
fallback).

SEM now sets a **benign** failsafe instead: a valid 30 s timeout that the
per-cycle `curr` writes keep resetting (so it never trips in normal operation),
and a fallback at the **charging floor** (your configured min, not 6 A) — so even
a genuine controller-death trip keeps the car charging at the floor instead of
pausing. Combined with the per-cycle refresh (beta.45), the offered current now
holds at the commanded value.


# [1.7.3-beta.45] - 21.06.2026

## ⚡ KEBA watchdog refresh — now per-cycle (beta.44 follow-up)

beta.44 cut the KEBA refresh to 30 s, but a PROD box still reverted to its 6 A
failsafe in under 30 s (offered current oscillating 6↔9 A, pausing the car to
~120 W). The KEBA refresh interval is now set **below the ~10 s coordinator
cycle**, so a steady command is re-asserted **every cycle** — outrunning any
failsafe with a timeout of at least one cycle. A box that reverts sub-cycle is a
device-side failsafe-config problem (disable failsafe or lengthen its timeout in
the KEBA app) that no write rate can out-run.

# [1.7.3-beta.44] - 21.06.2026

## ⚡ KEBA stops dropping to 6 A mid-solar-charge (watchdog refresh)

On a steady solar surplus a KEBA could oscillate its offered current between
~6 A and the commanded value about once a minute — charging at ~3.5 kW while
several kW exported to the grid. Cause: SEM holds a steady command and refreshes
the charger every **60 s**, but a KEBA's failsafe watchdog can trip near 60 s, so
the refresh *raced* the watchdog — the box kept falling back to its failsafe
current between refreshes.

The refresh interval is now a **per-charger device capability** instead of a
single global constant: a KEBA refreshes every **30 s** (comfortably under its
failsafe), while chargers without a short failsafe keep the 60 s default. An
explicit `_watchdog_refresh_override_s` wins for unusual failsafe settings. SEM's
command logic is unchanged — only the keep-alive cadence — so a steady command
now actually holds and the full surplus goes to the car.

# [1.7.3-beta.43] - 20.06.2026

## 🔋 Battery modes now map to the right Sessy strategy (#523)

RienduPre's beta.42 testing showed that on a Sessy (AC-coupled) every non-force
mode left the battery in `eco` — which isn't self-consumption — so `Auto` /
`Self-consumption` "didn't charge or discharge" and `Off` sat in `eco` too.
Each per-battery mode now drives the correct power strategy:

- **Auto / Self-consumption** → `nom` (zero-on-meter self-consumption), so the
  battery actually charges from surplus and powers the house — not `eco`.
- **Off** → `idle` (battery does nothing), with the setpoint zeroed.
- **Force charge / Force discharge** → `api` (SEM setpoint control) — unchanged.

After a force op ends (or the battery hits its reserve), it returns to `nom`
self-consumption instead of `eco`. The strategy values are configurable for
other AC-coupled brands (`battery_strategy_self_consume_value` /
`battery_strategy_off_value`). Huawei/DC batteries are unaffected (no strategy
select).

# [1.7.3-beta.42] - 20.06.2026

## 🐛 Pre-stable review fixes — forced charge restored (#535)

A full ruflo-core review of the battery subsystem ahead of stable 1.7.3 found a
blocker and three high-severity issues, all confirmed from code and now fixed:

- **Forced charging was silently broken on every brand.** The battery adapters
  built the internal charge command with the wrong field names
  (`charge_power_w`/`duration_min` vs the dataclass's
  `max_power_w`/`duration_minutes`), which raised a `TypeError` that the outer
  handler swallowed — so the **`Force charge` mode and the night-charge
  scheduler did nothing**. Fixed on Huawei, GoodWe, and the generic adapter, and
  the scheduler now carries a real charge power (it would otherwise have charged
  at 0 W). **(BLOCKER)**
- **Scheduled charging no longer fires at the wrong time.** A planned night
  charge used to start at *evaluation* time (e.g. 21:00) instead of inside the
  cheapest slot, because the schedule had no "is it active now?" check. It now
  respects the real slot boundaries.
- **Restart orphan-stop hardening (#532):** if the cancel command doesn't land
  (flaky Modbus) SEM now retries instead of giving up, and a multi-battery
  fleet sharing one inverter issues a single stop per device instead of two
  back-to-back (which the inverter would block).

# [1.7.3-beta.41] - 20.06.2026

## ⏸️ "Allow arbitrage" mode removed from the selector for stable 1.7.3 (#533)

- Automatic battery→grid arbitrage is fully deactivated for the stable release.
  On top of the global toggle being off (beta.40), the **`Allow arbitrage`
  per-battery mode is removed from the mode selector**, and the coordinator no
  longer evaluates arbitrage for a per-battery `allow_arbitrage` opt-in — a
  stale config goes dormant (behaves like `Auto`, no selling) instead of
  quietly selling to grid.
- **Kept** (tested, safe): `Auto`, `Self-consumption only`, `Force charge`,
  `Force discharge`, `Off`. Automatic arbitrage returns in **v1.7.4** after
  review + soak (#533).

# [1.7.3-beta.40] - 20.06.2026

## ⏸️ Battery→grid arbitrage deactivated for the stable release (#533)

- After the incident below, the **selling-to-grid feature is held back** for a
  stable release. The global arbitrage toggle is **forced off on upgrade**
  (config migration v13→v14) and its **section is hidden from the dashboard
  config card**, so it can't be enabled from the UI. The decision code and the
  per-battery modes stay intact — arbitrage returns in a later release once it
  has been reviewed and soaked (tracked in #533).

## 🛡️ A SEM restart no longer strands a Huawei battery force-discharge (#532)

- **Critical fix.** Huawei battery→grid arbitrage uses the
  `huawei_solar.forcible_discharge_soc` service, which the inverter then runs
  **autonomously until its target SOC**. A SEM restart or config reload while a
  discharge was in flight gave the fresh adapter no record of it, so SEM never
  sent the stop — the inverter kept discharging the battery to the reserve floor
  **unsupervised** (a dev/observer test drained a real LUNA2000 from 80% to 20%,
  exporting to the grid for ~1h40m before it self-terminated at the floor).
- SEM now detects an active forcible op via the integration's status sensor on
  the first cycle after startup and issues one `stop_forcible_charge` to cancel
  anything it didn't start — waiting for the integration to load and for the
  sensor to report a real value (no false stops, no missed ops). Resuming
  arbitrage after a restart re-asserts the sell instead of stopping it.

# [1.7.3-beta.39] - 19.06.2026

## 🔋 New battery mode: "Off (SEM hands-off)" (#523)

- **A sixth per-battery mode, `Off`, that tells SEM to leave a battery completely
  alone.** Requested by @RienduPre. On the transition into `Off`, SEM does a
  one-time clean handoff (clears any force command, releases the power strategy
  it took, un-limits the discharge) so the battery isn't stranded in a
  SEM-imposed state — then issues **nothing** further: no protection, no
  scheduler, no arbitrage. The inverter runs the battery on its own. Highest
  precedence, so it overrides every other decision branch. Available in the
  per-battery mode selector and translated in all 15 languages.

# [1.7.3-beta.38] - 19.06.2026

## 🔋 Battery arbitrage / per-battery review batch (#531)

A holistic review of the arbitrage / per-battery / AC-coupled (Sessy) subsystem
after a string of reactive #523 fixes. Three independent reviewers, every finding
confirmed from code, fixed and tested as **one batch**.

- **Charge-first: never sell stored energy while free solar surplus could charge
  the battery.** Storing surplus avoids a future import (~full retail price),
  worth far more than the export price — SEM now suppresses the sell verdict
  while storable surplus exists and the battery isn't full. (#531)
- **Arbitrage break-even now uses the all-in import rate, not raw spot.** The
  upcoming-price curve is raw spot for Nord Pool / ENTSO-E but all-in for Tibber;
  selling against raw spot lost money for spot-tariff users. SEM scales the
  forecast minimum up to the live all-in rate (no-op for all-in providers). (#531)
- **SOC unavailable → SEM holds instead of selling blind.** A setpoint battery
  (Sessy) has no hardware reserve-stop, so an unavailable SOC could drain it past
  the backup reserve. When in doubt, hold — the live SOC self-heals next cycle. (#531)
- **A stale global battery mode no longer bleeds into a multi-battery fleet.**
  After a single→multi upgrade the UI showed `auto` while a leftover global
  `force_discharge` drove every battery; multi-battery slots now default to
  `auto` and only the single-battery selector reads the global key. (#531)
- **EV-night protection splits the home budget across the fleet.** Two batteries
  each told to inject the *full* home load over-injected 2× and leaked surplus to
  the EV — each now gets `home / N`. (#531)
- **Strategy no longer stranded in API after a reload.** If SEM restarts
  mid-episode with the strategy already in API, the fresh adapter adopts control
  so the next idle cycle hands it back instead of leaving the battery
  setpoint-controlled forever. (#531)
- **Mixed-brand fleets: an AC-coupled battery stays on the generic adapter.** A
  Sessy in a Huawei fleet is no longer promoted to the Huawei adapter (whose
  service calls would never reach it) just because the Huawei integration is
  loaded for a sibling. (#531)
- **Arbitrage exit is explicit.** A non-firing arbitrage verdict now propagates a
  clean STOP rather than falling back to a possibly-stale night-charge decision —
  without ever overriding an active or planned charge. (#531)

## 🛟 Robustness (#531)

- The discharge-limit write is domain-aware (`input_number` helpers work, not
  just `number`), matching the force-discharge path.
- A setpoint clamped to the control entity's range now logs a WARNING instead of
  silently capping — surfacing a fleet-power-vs-unit-rating mismatch.
- Two batteries accidentally sharing one control entity now log a collision
  warning instead of silently fighting over the setpoint.

# [1.7.3-beta.37] - 19.06.2026

## 🔋 Battery charges from surplus again — SEM stops clobbering the power strategy (#523)

- **The battery no longer sits idle while solar surplus is exported.** SEM's
  strategy-release path forced the configured idle value (`eco`) onto the
  battery's power-strategy select **even when SEM had never taken control** —
  clobbering the user's self-consumption mode (e.g. Sessy `nom` = zero-on-meter)
  and stopping the battery charging from surplus (RienduPre: battery idle at
  20 % SOC while ~1 kW of surplus exported to grid). SEM now **only restores a
  strategy it actually changed**; if it never switched to API it leaves the
  user's mode alone. When it *did* take control it restores the captured prior
  mode (or the idle fallback if unreadable — never stranded in API).

## 💶 Battery arbitrage holds without an import-price forecast (#523)

- **No more selling on the export floor alone.** When there's no upcoming
  import-price forecast, SEM can't prove that selling now beats buying back
  later, so it **no longer fires** (the break-even check was previously skipped,
  making it sell too eagerly). Conservative default; pairs with the export floor.

## 🔧 A repair when a %-SOC charge cap can't be enforced (#526)

- **No more silent overshoot past the SOC limit.** A `%` charge target needs a
  readable vehicle SOC to stop at the cap; when the car isn't reporting SOC
  (asleep / no real sensor), SEM keeps charging until the car tapers — which
  surprised users ("car went past 80 %"). SEM now files a **repair**
  (Settings → Repairs) explaining the cap can't be enforced and how to fix it
  (wire a real vehicle SOC sensor); the dashboard's *estimated* SOC is
  deliberately ignored for the hard limit. Clears automatically when a real SOC
  reading returns.

# [1.7.3-beta.36] - 19.06.2026

## 🔋 Battery setpoint is clamped to the control entity's range (#523)

- **Force-charge / force-discharge no longer get rejected for being
  out-of-range.** SEM wrote the raw charge/discharge power to the setpoint
  number — but a Sessy unit's setpoint maxes at ~±2200 W, so a fleet
  `battery_max_charge_power_w` of 4400 W written to a single 2200 W unit was
  **−4400 W**, which Home Assistant rejects as out of range. The write failed
  silently and the setpoint stayed at **0**, so the battery never charged
  (RienduPre: strategy flipped to API, setpoint stuck at 0). SEM now **clamps
  the setpoint to the entity's `min`/`max`** before writing (mirrors the EV
  #487 fix) — −4400 → −2200, and it charges.

# [1.7.3-beta.35] - 19.06.2026

## 🔋 Battery control config is reachable without enabling arbitrage (#523)

- **The force-discharge entity, power-strategy entity, and "Bidirectional
  setpoint" toggle now appear in a "Battery control" section whenever a battery
  exists** — previously they were hidden behind the *battery arbitrage* toggle
  (itself only on a dynamic tariff). A user who wants `force_charge` or
  per-battery modes (not arbitrage) couldn't find them, so `supports_forced_charge`
  stayed False and the decision was dropped every cycle (RienduPre). Now they're
  always available, and a **new power-strategy entity picker** lets you wire the
  Sessy `select.*_power_strategy` from the UI (was config-only before).
- **Battery SOC autodetect also matches by signature** (`device_class: battery`
  + `%`), so a localized name like the Dutch `sensor.*_batterijpercentage` is
  found even without an English SOC keyword (#529, DavidVM1982).

# [1.7.3-beta.34] - 18.06.2026

## 🔋 Battery SOC: reachable when it lives off the power sensor's device (#529)

- **A battery SOC sensor that autodetect couldn't reach is now found.** Some
  installs (e.g. a Huawei Luna with a generic `sensor.battery_state_of_charge`,
  or a template helper) expose the SOC on a *different* device than the battery
  power sensor — so neither the name-prefix nor the same-device scan could find
  it, and SEM showed no SOC even though the HA Energy Dashboard read it fine. A
  **guarded global last-resort scan** now finds the lone home-battery SOC sensor
  (a SOC-keyword name + `%` unit, excluding EV/phone batteries) — only when
  **exactly one** unambiguous candidate exists, never a guess (#529).
- **Manual override:** `battery_soc_sensor` is now a settable option (structural
  → reloads), so when autodetect still can't decide, you can point SEM at the
  right sensor explicitly via the `set_option` service.

# [1.7.3-beta.33] - 18.06.2026

## 🔋 AC-coupled batteries (Sessy) can now force-CHARGE (#523)

- **SEM can now force-charge a Sessy-style battery.** These batteries have no
  charge *switch* — they charge by writing a **negative** value to the same
  bidirectional power setpoint that discharge writes a positive value to. SEM's
  switch-based charge path couldn't drive them, so `force_charge` (and scheduled
  night charging) silently did nothing. New opt-in **"Bidirectional setpoint"**
  toggle (Configuration → Battery, next to the forcible-discharge entity): when
  on, force-charge writes `-power` to the setpoint, gated by the power-strategy
  → API switch. Verified live on HA-TEST (force_charge → −2200 W setpoint +
  strategy `api`; release → 0 W).
- **SEM restores the battery's prior power-strategy instead of forcing `eco`.**
  Researching the ha-sessy integration showed the real strategy options are
  lowercase `api`/`nom`/`roi`/`idle`/`eco`. SEM now **captures** the user's
  strategy (e.g. `nom`/`roi` self-consumption) before taking control and
  **restores** it on release — so it no longer clobbers their normal mode.
- **Fixed force-charge commanding 0 W** when `battery_max_charge_power_w` is
  present-as-`None` (a `.get(key, default)` returns `None`, not the default).
  The charge power now falls through `battery_max_charge_power_w` →
  `battery_max_charge_power` → 5000 W. Harmless before (the charge switch
  ignored power); surfaced by the new bidirectional setpoint path.

# [1.7.3-beta.32] - 18.06.2026

## 🔥 Heat pump: restore the SG-Ready invert toggle (#523)

- **Brought back the opt-in "Invert SG-Ready contacts" toggle** (Configuration →
  Heat Pump) that beta.31 removed. It's inert by default and costs nothing, but
  it's the one-click safety net for an install wired normally-closed (NC) — so a
  pump that boosts-as-block can be corrected without a second release round-trip.
  The corrected standard map remains the default.

# [1.7.3-beta.31] - 17.06.2026

## 🔥 Heat pump: drop the speculative invert toggle (#523)

- The SG-Ready truth table is **universal across EMS vendors** (verified against
  alpha innotec / gridX / SMA / SolarEdge), so the corrected map from beta.30 is
  right for everyone. The opt-in "Invert SG-Ready contacts" toggle was a
  speculative knob for a normally-closed-wiring case no one has actually
  reported — removed to keep the config surface lean. It can come back later if
  a real inverted-wiring install turns up. The corrected standard map stays.

# [1.7.3-beta.30] - 17.06.2026

## 🔥 Heat pump: SG-Ready relay map corrected to the standard (#523)

- **Fixes "the heat pump never got turned on" on SG-Ready pumps (RienduPre,
  Nibe).** SEM's `SG_READY_RELAY_MAP` was a plain 2-bit count, not the SG-Ready
  standard truth table — so when SEM wanted to **boost** the pump on surplus it
  drove `(relay1=on, relay2=off)`, which a standard pump (Nibe et al.) reads as
  **EVU-block** and turns *off* instead of on. Corrected to the SG-Ready
  standard: BLOCKED `1:0`, NORMAL `0:0`, BOOST `0:1`, FORCE_ON `1:1`.
- **New opt-in "Invert SG-Ready contacts" toggle** (Configuration → Heat Pump)
  for installs whose contacts are wired **normally-closed (NC)** — it flips both
  relays so the standard map still drives the right physical state. Default off
  (NO wiring, the common case).
- The Control-tab "not configured" label for a correctly-registered heat pump
  was already fixed in beta.19 — update past beta.19 to clear it.

# [1.7.3-beta.29] - 17.06.2026

## 🩹 Wallbox: a junk `charger_service` no longer blocks current control (#523)

- **Fixes "Failed to set current … not enough values to unpack" spamming
  every 10 s on both Wallboxes (RienduPre).** A leftover `charger_service='0'`
  (no `domain.service` shape — and it even propagated to a sibling charger whose
  own config was empty) hit the service branch and crashed the
  `charger_service.split(".", 1)` unpack, so SEM could never set the charge
  current — even though both chargers had a valid
  `number.wallbox_*_max_charging_current` control entity. SEM now **treats any
  `charger_service` that isn't a real `domain.service` as absent** and falls
  through to the number entity. Guards all three actuation paths (set-current /
  start / stop) at once.

# [1.7.3-beta.28] - 17.06.2026

## 🔋 AC-coupled batteries (Sessy) honour the power setpoint (#523)

- **A generic AC-coupled battery (e.g. Sessy) now actually force-discharges and
  sells.** These batteries ignore their power setpoint unless their *power
  strategy* select (`select.sessy_*_power_strategy`) is in the API/active mode —
  in eco/NOM they just self-consume. SEM now **switches the strategy to the
  active value before writing a force/arbitrage setpoint** and **back to the idle
  (self-consumption) value** when returning to NORMAL / limit / stop. Configure
  it per battery via the new `battery_strategy_entities` (or the single-battery
  `battery_strategy_control_entity`); active/idle values default to `api`/`eco`
  and are overridable. Inert on batteries without a strategy select (Huawei,
  GoodWe) — no behaviour change there.

## 🔌 Huawei battery: zero-config forcible discharge (#523)

- **A Huawei battery's force / arbitrage modes now work with no manual
  config.** The `huawei_solar.forcible_discharge_soc` service targets the
  battery *device*; previously you had to set `inverter_device_id` by hand or
  the command was dropped. SEM now **auto-detects the Huawei battery device**
  from the device registry (the `connected_energy_storage` device), so
  `supports_forced_discharge` is true out of the box. A manually-set
  `inverter_device_id` still wins.

# [1.7.3-beta.26] - 17.06.2026

## 🔧 Battery adapter self-heals a startup race (#523)

- **A Huawei/GoodWe battery no longer gets stuck on the Generic adapter.** If
  the brand integration (e.g. `huawei_solar`) finishes loading *after* SEM's
  first battery cycle on boot, SEM used to cache a Generic fallback for the
  whole session — so brand-specific control (Huawei forcible discharge) silently
  never engaged. SEM now **re-detects once the brand integration is loaded** and
  upgrades the adapter in place. Surfaced by the new beta.25 `battery_control`
  diagnostics, which showed a real Huawei battery reporting `GenericBatteryAdapter`.

# [1.7.3-beta.25] - 17.06.2026

## 🩺 Battery + surplus observability in diagnostics (#523)

The one-click **Download Diagnostics** now answers the two questions that
previously needed a back-and-forth (or a DB dump):

- **`battery_control`** — is the battery controllable at all (adapter class,
  `supports_forced_charge` / `supports_forced_discharge`, the wired control
  entities + whether an inverter device is set), what **mode + reserve** it's
  in, and the **last per-battery decision + reason** — so *"is the EV draining
  the battery?"* is a single readable line (`LIMIT_DISCHARGE — ev_charging →
  1200 W`).
- **`surplus`** — the live surplus allocation snapshot (distributable surplus,
  who won it, active vs total devices) — which, with the existing `heat_pump`
  block, explains *"why didn't the heat pump turn on?"* (not enough surplus,
  lost priority, or not wired).

No new data collection or DB dump needed — it's all in the existing
diagnostics payload.

# [1.7.3-beta.24] - 17.06.2026

## 🔋 Battery mode selector on single-battery installs (#523)

- **The Battery card mode selector now appears on single-battery installs too.**
  beta.23 only created the per-battery Mode + Reserve-SOC controls for
  multi-battery setups, so a single-battery install (the common case) had no way
  to pick **Auto / Self-consumption / Allow arbitrage / Force charge / Force
  discharge**. There's now a global `select.sem_battery_mode` +
  `number.sem_battery_reserve_soc`, shown on the battery hero card.

# [1.7.3-beta.23] - 16.06.2026

## 🔋🎛️ Per-battery control + Huawei forcible-discharge fix (#523)

Multi-battery installs (e.g. Growatt + Sessy, or two LUNA2000s) can now be
controlled **per battery**, and battery → grid arbitrage actually works on a
real Huawei battery — verified live on a Huawei SUN2000 + LUNA2000.

- **Per-battery Mode selector on the Battery card** — each battery gets its
  own mode: **Auto** (today's behaviour), **Self-consumption only** (never
  sells to grid), **Allow arbitrage** (sell when export beats recharge cost,
  even with the global toggle off), **Force charge**, **Force discharge**
  (manual sell to grid). Plus a per-battery **Reserve SOC** floor — a battery
  never discharges below it, on every mode. One battery can sell while its
  sibling holds, gated purely by mode. (`select.sem_battery_<id>_mode` +
  `number.sem_battery_<id>_reserve_soc`, live — no reload.)
- **EV-card-style battery tiles** — each battery now shows the filled battery
  glyph with SOC %, a flow-coloured status badge, power, and (when capacity is
  known) stored energy + time-to-full/empty, matching the EV charger card.
- **Per-battery force-discharge entity pickers** in Configuration → Tariff, so
  each battery's sell setpoint is wired from the dashboard, not YAML.
- **Huawei forcible discharge now actually works.** Huawei has no
  forcible-discharge *number* entity — it's the `huawei_solar.forcible_discharge_soc`
  *service*. SEM previously wrote to a non-existent number, so battery → grid
  selling silently did nothing on every real Huawei (including the beta.22
  arbitrage feature). It now drives the service (discharge to the reserve SOC,
  which self-terminates there as a safety floor). Force-discharge writes are
  also domain-aware (real `number.*` setpoints **and** `input_number.*` helpers).
- **Anti-block hardening.** The LUNA2000 locks up if it gets `stop_forcible_charge`
  plus another Modbus write back-to-back in one cycle. The Huawei adapter is now
  a clean state machine — exactly one command per transition, the rest deferred
  to the next cycle — and a dropped stop self-heals by re-issuing on the next
  cycles. Battery-brand detection also no longer misses a modern `huawei_solar`
  install (config-entry check, not just `hass.data`).
- **Per-battery SOC fix** — on multi-battery installs the per-battery tiles
  could read 0 % because SOC auto-detect only matched 2-part sensor names; it
  now matches indexed devices (e.g. `…battery_2_soc`).
- Removed the dead legacy `BatteryChargeScheduler.update()` path.

# [1.7.3-beta.22] - 16.06.2026

## 🔋💶 Dynamic export-price optimisation — sell the battery when export is high (#523)

- **Signed export price.** On an EPEX/Tibber/Nord Pool dynamic contract the export price *is* the spot price and is regularly negative (you pay to export). SEM no longer `abs()`-es the feed-in price, so a negative export is correctly a cost — fixing export revenue/ROI and unlocking export-aware decisions. (Auto-detected Amber keeps its sign-inverted convention.)
- **Battery → grid arbitrage, built into the charge scheduler.** Discharge-to-grid is the mirror of the scheduler's charge-on-cheap logic, so it lives **inside `BatteryChargeScheduler`** and reuses the same economics (round-trip efficiency + cycle cost): SEM sells stored energy to the grid only when the export price beats the cost of recharging it later (cheapest upcoming import ÷ efficiency + degradation). Opt-in (**default off**), never sells below a configurable reserve SOC, and never runs while a charge is planned. Flip the toggle off mid-sale and the next cycle stops it cleanly.
- **Works across battery brands.** The forcible-discharge command is brand-agnostic (base adapter), driven by a configurable discharge-power entity — Huawei LUNA, GoodWe, and the generic catch-all (Victron / SolaX / Growatt / Sessy / Powerwall / …). A battery without a discharge-power entity safely has the decision dropped.
- **"Selling to grid" on the Battery card** — a distinct gold state with the live export price while SEM is exporting the battery.
- **New Configuration → Tariff settings** (dynamic mode): *Sell battery to grid on high export*, *Min export price to sell*, *Arbitrage reserve SOC*, and the *Forcible-discharge power entity*.

# [1.7.3-beta.21] - 16.06.2026

## 🎨 Dashboard polish — battery glyph + EV status spacing

- **System diagram: the charging bolt no longer sits on top of the SOC number** — when the battery was charging, the ⚡ was drawn centred over the "58%", making it hard to read. The bolt now sits in the upper part of the battery and the percentage drops just below it, so both are clearly legible.
- **Battery card now shows the filled battery glyph** — the small icon in the SOC ring was a flat outline; it is now a filled, SOC-level battery (tinted with the charge/discharge colour, with a charging bolt) matching the system diagram.
- **EV card: "Status" label and value no longer touch** — in the centred hero the row shrink-wrapped so it read "StatusDisconnected"; a minimum gap keeps the label and value apart.

# [1.7.3-beta.20] - 15.06.2026

## 🔌 EV no longer keeps charging from expensive grid after the cheap window (#524)

- **Tariff awareness restored to the EV decision layer** — the fleet cycle read a non-existent `provider.current_level` attribute, so `tariff_level` was *always* `None`. Every tariff-aware EV decision was silently dead: `solar_plus_cheap` / `min_plus_solar` never saw their expensive windows, so the daytime "pause on expensive tariff" never engaged. Now read via `provider.get_price_level()` (by @RienduPre in #524)
- **The charge-stability bridge no longer imports expensive grid** — when solar surplus dips below the minimum, the layer holds minimum current for up to 5 minutes to ride out a passing cloud. In a **not-cheap** tariff window that meant importing expensive grid for the whole bridge. It now stops on the short (~45 s) grace during normal/expensive/very-expensive windows, while cheap / very-cheap (and static tariffs) keep the full cloud-bridge (by @RienduPre in #524)

## 💶 Clearer export-rate / feed-in help for dynamic tariffs (#523)

- Export-rate and Feed-in-entity help text now explains how to value exports on a dynamic/spot contract (a flat average, or a live feed-in sensor) — so export revenue and ROI populate instead of staying at 0 (by @RienduPre in #523)

# [1.7.3-beta.19] - 15.06.2026

## 🔧 Control-tab heat-pump card + Home 7-day chart fixes (#523)

- **Heat pump no longer shows "not configured" while clearly configured** — the Control-tab Heat Pump section read the `heat_pump_registered` *binary* sensor through a helper that only resolves `sensor.sem_*` entities, so it always evaluated false and showed the "not configured" notice, while the section header still rendered "normal · 2" (sg-ready state defaults to 2). Both the body and the header now read the binary sensor correctly, so the card is consistent (by @RienduPre in #523)
- **Home "Last 7 days" chart no longer collapses to a single bar on Mondays** — the energy summary used a "this week" (Monday→now) window, which on Mondays is a single day and rendered as one stray bar, contradicting the card's "Last 7 days" title. It now uses a rolling 7-day window (always 7 day-buckets) (by @RienduPre in #523)

# [1.7.3-beta.18] - 14.06.2026

## 🏷️ Deterministic grid-sign by meter brand (#461)

- **Known meter integrations now seed the grid sign instantly** — for well-tested brands (Huawei, SMA, Fronius, Enphase, SolarEdge, Kostal, Powerwall, GoodWe, SolaX) SEM reads the grid-power sensor's own integration and applies that brand's known import/export convention immediately, so a fresh install is correct from the first cycle without waiting for solar swings or counter deltas. A separate P1/CT meter (unknown integration) simply falls through to the solar/counter detectors, and the solar co-movement signal can still override a brand seed if it ever disagrees (#461)

# [1.7.3-beta.17] - 14.06.2026

## 🧭 Robust grid-sign autodetection + one-tap fix (#461)

- **Solar-anchored detection is now the authoritative primary** — solar production has no sign ambiguity, so SEM now learns the grid import/export convention from how the raw grid reading *co-moves with solar* (grid rises with solar → `+export` meter; grid falls as solar rises → `+import` meter). This is completely independent of the Energy-Dashboard import/export counters, so a mis-mapped or swapped counter (the root cause of the Sessy-P1 wrong lock) can no longer corrupt the result. It can also self-heal a wrong existing lock once it is highly confident and sustained — and because a correctly-signed install computes the *same* sign it already has, a working install is never disturbed (#461)
- **Counter-correlation hardened** — the fallback path (grid-only installs, no solar) replaced the old "3 consecutive votes" lock, which a mixed/transient counter burst could slip through, with magnitude-weighted evidence scored by *confidence*: it only locks when the dominant direction holds ≥75% of all accumulated evidence, so an inconsistent meter stays in passthrough instead of locking the wrong sign (#461)
- **One-tap "Fix grid sign" button in Configuration → Advanced** — flips the convention instantly (via the new `flip_grid_sign` service) and copies a ready-to-paste diagnostics report (raw meter value, configured counters, both correlation streams) to the clipboard for a GitHub issue. The neighbouring "Reset sign detection" re-learns from scratch and now also clears a prior manual flip so the re-learn starts clean (#461)

# [1.7.3-beta.16] - 14.06.2026

## 🌍 More Dutch translations on the diagnostic dashboard (#515)

- Expanded `nl` coverage across the diagnostic dashboard (by @RienduPre in #515)

## 💶 A configured dynamic price sensor no longer silently flips to Nord Pool (#518)

- **Your chosen price entity stays the source, even on a momentary blip** — when a user configures a dynamic price sensor (`dynamic_tariff_entity`, e.g. a Tibber sensor with VAT/fees), SEM used to *fall through* to auto-detecting another integration whenever that sensor read `unavailable`/`unknown` for a cycle. With the Nord Pool integration also installed, the provider silently switched to `nordpool_official` — a different source with different (tax-free spot) prices and percentile levels, so the schedules/price-levels appeared to flip back and forth (RienduPre, #518). A user-configured price entity is now authoritative: the provider stays `custom` and the cached curve / fallback price covers a transient gap. Auto-detection only runs when no price entity is configured (#518)

## 🌤️ Weather tile no longer shows "?" / "—°C" when the picked entity has no data (#516)

- **The weather tile now finds a weather entity that actually has current data** — RienduPre's tile showed a "?" condition and "—°C / — % / — km/h" because the dashboard generator picked a `weather.*` entity that carried no `temperature` (a `weather.forecast_*` subentity, or one that was unavailable when the dashboard was generated). The generator now prefers a non-forecast entity that actually has a current temperature, and the card falls back at render time to any usable `weather.*` entity if its configured one is missing / unavailable / data-less — so the tile self-heals without regenerating the dashboard (#516)

## 🔢 Per-charger "today" energy now resets at midnight even when idle (#517)

- **A charger that didn't draw power all day no longer carries yesterday's energy forward** — RienduPre (dual Wallbox) saw "Vandaag" (today) = 81.5 kWh on a charger that wasn't even connected, while the fleet total correctly showed 0. The per-charger daily *rollover/reset* was nested inside the `if charger_power > 0` accumulation guard, so an idle/unplugged charger never executed it and its counter grew across idle days. The reset now runs every cycle for every charger (only the increment stays gated on power); a stored stale value self-heals on the next cycle after update. Single-charger installs were unaffected (they report the correctly-resetting fleet total) (#517)

# [1.7.3-beta.15] - 14.06.2026

## 🏷️ Config-tab label audit + clearer forecast/EV-priority controls (#514)

- **The EV charger "Min Amps" stepper was mislabelled "Minimum SOC"** — the Config tab's per-charger minimum-current control (in Amps) showed the battery-SOC label. Fixed to "Min Amps". The battery section's legitimate "Minimum SOC" is untouched (#514)
- **Surplus Priority + Shed Priority steppers now appear on each EV charger** in the Config tab, alongside Min Amps / Start current / Capacity (matching how Hot water and Heat pump show "Priority"). The #470 entities existed but weren't surfaced on the card (#514)
- **Raw translation keys no longer leak onto the dashboard** — Hot water's "Max temperature" row and the Max-Grid-Import help text rendered their raw keys (`hot_water_max_temperature`, `tile_help_max_grid_import`); both now show proper labels (#514)
- **Forecast source shows its brand name** — the Config tab showed the raw id (`forecast_solar` / `FORECAST_SOLAR`) while the Home hero already showed "Forecast.Solar". Both now share one base helper so they agree and can't drift (#514)

## 📊 EV "Today's plan" strip no longer renders empty when the next charge is >12h away (#512)

- **The 12h plan strip now shows a full "nothing scheduled" idle bar instead of blanking** — when the next EV charging event was beyond the strip's 12h window (e.g. a morning view with night charging set for 21:35), the segment builder advanced its cursor past the window end and skipped the idle-fill, producing zero segments and an empty strip (title/axis/legend showed, but no timeline). Each transition is now clamped to the horizon so the visible time is always painted. Not mobile-specific — desktop blanked in the same state too (#512)

## ☀️ Heat pump / hot water boost on the TRUE house surplus, and stand down under peak (#508 phase 2)

- **They now see real spare solar, not the EV's budget (W7)** — the surplus controller was fed the EV charging *budget*, so heat pump / hot water effectively competed for the EV's allocation. It now receives the true house surplus: `grid_export + its own active device draw`. The add-back is what makes it stable — without it, every device the controller switches on shrinks the grid export it reads next cycle, so the signal would chase its own tail and the device would flap. With it, the input is the surplus that *would* exist if its devices were off — the right quantity to allocate from. Net effect: discretionary loads boost only on genuine spare solar, after the EV and battery have taken their share (#508)
- **They back off when the grid-import peak is at risk (W2)** — the load manager and the surplus controller used to fight: the load manager would shed a heat pump to protect the 15-minute peak, then the surplus controller (running later in the same cycle) would see surplus and switch it straight back on. The surplus controller now receives the load manager's peak posture — on `WARNING` it stops *adding* discretionary load; on `SHEDDING` it backs its own devices off one per cycle (gentlest first by reverse priority); on `EMERGENCY` it sheds them all at once. The EV stays owned by the load manager's shed path (#508)

## 🔀 Independent surplus vs shed priority per EV charger (#470)

- **`ev_shed_priority` splits off from `ev_surplus_priority`** — a single number used to drive two unrelated decisions: who gets solar surplus first (cooperative, every cycle) and who gets throttled first when grid import nears the peak limit (emergency). A mixed fleet can't express both — e.g. a long-range EV should charge *first* on surplus (big battery soaks watts) yet shed *first* under peak (range cushion absorbs a throttle). Surplus order stays on `ev_surplus_priority`; shed order moves to the new per-charger `ev_shed_priority`, exposed in the options flow, the setup flow, and as a per-charger number entity. A v12→v13 migration seeds `ev_shed_priority = ev_surplus_priority` for every existing charger, so the decoupling is behaviour-neutral until you deliberately diverge them (#470)
## 🔌 EV no longer drains the battery to hold a dead solar session (#461)

- **The disable hold now distinguishes a transient dip from genuine darkness** — the 300 s disable delay exists to BRIDGE a passing cloud (solar drops 8 kW → 3 kW for a minute while the car wants 4) by holding minimum current instead of cycling the contactor. But when solar is genuinely ~0 W — dusk, heavy overcast, or the `is_night` flag not yet flipped — there is nothing to bridge *to*: that held minimum current is pulled entirely from the home battery and the grid. RienduPre's PROD logs caught it live: solar = 0 W, the hold commanding 9 A, the car flapping 4.35 kW ↔ 0.12 kW while the battery drained at 5 kW and the grid imported 1.7 kW — every 300 s window. A deficit while solar is below `min_solar_w` (the same "no meaningful solar" threshold `solar_only` idles on) is now a **deep deficit** and stops after a short grace (`ev_deep_deficit_grace_sec`, default 45 s) instead of the full window. A genuine transient dip — solar still meaningful — keeps the full bridge unchanged. The grace rides out a single-cycle inverter flicker to 0 W so a momentary zero never ends a real daytime session (#461)

## 🔥 Heat pump / hot water: surplus activation actually fires + relay-failure safety (#508)

First phase of wiring the dedicated heat-pump and hot-water controllers into the surplus pipeline they were bypassing.

- **They actually activate on solar surplus now** — both controllers defaulted to `PEAK_ONLY`, and the surplus controller never proactively turns on a non-`SURPLUS` device, so surplus boosting was silently inert. Both now default to `SURPLUS` (still overridable via `set_device_control_mapping`) (#508)
- **A failed SG-Ready relay write no longer credits phantom power** — the heat pump used to mark itself `ACTIVE` and deduct `rated_power` from the surplus pool even when the relay call failed, starving the EV/battery of watts that weren't being drawn. It now returns 0 W and reports `ERROR`; a partial (relay2) failure restores relay1 to its prior state instead of leaving a stray curtail signal (#508)
- **Legionella prevention runs** — `check_legionella_cycle()` had no production caller (the disinfection cycle never ran, `hours_since_legionella` was pinned at 999). It's now driven every cycle, and the last-cycle timestamp persists across restarts so a reboot doesn't force a disinfection run (#508)
- **Heat-pump compressor anti-cycling** — `min_on`/`min_off` guards (10 min run / 5 min rest) so a 10 s coordinator cycle can't short-cycle the compressor (#508)
- Follow-up phase (tracked in #508): route them through the load-manager dual-sync for peak shedding, and feed the true house surplus rather than the EV budget

# [1.7.3-beta.14] - 13.06.2026

## 🏠 System-diagram Home no longer flickers to 0 W while the EV charges (#506)

- **The diagram card reads the published `home_consumption_power` sensor instead of re-deriving it client-side** — Home was recomputed from the raw source sensors, which update on wildly different cadences (Huawei inverter ~17–30 s modbus vs KEBA EV ~2 s). With the EV charging hard, a fresh EV reading paired with a stale solar reading drove the residual briefly negative → clamped Home to 0, on and off. The coordinator's #237/#444 hold already rides out that skew (the sensor itself never flickers); the card now uses it, with the residual kept only as a fallback when the sensor is unavailable (#506)


# [1.7.3-beta.13] - 13.06.2026

## 🔮 Forecast dampening: morning jitter smoothed + correct sun window (#416)

Closes the two remaining sub-findings of the #416 forecast-correction audit (the other three — shrinkage naming, telemetry surface, write-time weather snapshot — shipped earlier and are soak-verified on PROD).

- **The live dampening signal is EMA-smoothed (τ ≈ 5 min)** — at 7–9 AM the expected-production fraction is tiny, so the normalized live ratio amplified the actual-sensor noise floor (cloud transits, inverter sampling) into large cycle-to-cycle swings of `forecast_dampening_factor`. The blend now consumes a time-based EMA of the ratio; genuine weather trends still pass with little lag. Raw and smoothed values are both on the sensor's diagnostic attributes (`normalized_ratio` / `smoothed_ratio`) (#416)
- **`_get_sun_hours` no longer mixes tomorrow's sunrise with today's sunset** — `next_rising`/`next_setting` are NEXT events; tomorrow-dated ones now roll back a day, fixing the skewed daylight window (~1 min average, worse near solstices/high latitudes) (#416)

## 🧭 Sign-detection locks survive restarts (#476)

The grid/battery sign autodetect locks were RAM-only — every reload re-learned the sign from possibly ambiguous low-power samples, and three bad votes right after a reboot could lock the WRONG sign until the next reload (the 2026-06-11 PROD flip).

- **Locked signs now persist** in SEM's storage and restore at setup — the warmup/vote machinery runs once per install, not once per restart; only LOCKED state persists (votes and half-learned guesses never do), and a restored lock survives the Energy Dashboard being reconfigured away (#476)
- **Manual `grid_sign_invert` still wins** — it short-circuits before the autodetect, so a restored lock can never fight a manual override
- **New `solar_energy_management.reset_sign_detection` service** — the escape hatch: forgets all sign locks (RAM + storage) and re-learns from scratch, since a wrong lock no longer clears itself on restart
- Closes the last open item of the #476 robustness batch — items 1–4 and 6–9 already landed across the #485/#486/#487 review batches


## 🖼️ System diagram card: explicit `entities:` config (#455)

- **`sem-system-diagram-card` now accepts the same `entities:` map as `sem-flow-card`** — point the illustrated diagram at any HA install's sensors (combined or split battery/grid sensors, `reverse`/`invert` flags, optional explicit home sensor instead of the derived balance). `entity_prefix` stays the default and wins when both are set, so existing dashboards are untouched (#455)
- In entities mode, intentionally unmapped nodes (e.g. no EV) no longer count toward the "sensor unavailable" warning
- Schema documented for both cards in `DASHBOARD_GUIDE.md`

## ☀️ `min_plus_solar` daytime is self-consumption-maximizing again (#501)

Daytime `min_plus_solar` in battery Zone 3/4 was draining the home battery into the EV and importing from the grid when it should maximize self-consumption — a cloudy afternoon at 70–90% SOC got ground into the car.

- **The daytime min-current floor is now need-gated** — it engages only when the remaining daily Min can no longer be delivered by tonight's charging window (new per-charger `night_deliverable_kwh`). Otherwise daytime is pure surplus + capped battery assist, and idles below the charger minimum. Restores the documented "Min comes from the night top-up, not a forced grid pull at noon" promise; `always_max` stays the "just charge" escape hatch (#501)
- **One shared, capped battery-assist formula** — `decide` and `flow_calculator` had diverged (ADR 0002 regression); both now use the same SOC-based *potential* (capped by `battery_assist_max_power`, zeroed below the assist-floor SOC, bounded to the surplus→min gap). No more measured-discharge branch, so a home-load spike can't ratchet the EV current upward, and #439's chicken-and-egg stays structurally fixed (#501)
- Amends ADR 0010 pattern 1; `EV_CHARGING_LOGIC.md` mode table corrected

## 🙏 Contributors

Backlog sweep after the beta.12 retest round — four audited issues (#416, #455, #476, #501) closed end-to-end. Thanks to @RienduPre for the reports and reviews that surfaced the charging and dashboard gaps.

# [1.7.3-beta.12] - 12.06.2026

## 🎨 Plan-strip legend always-visible + tariff colours (#464 follow-up)

- **The full plan-strip legend is now always shown** — no need to open the `?` help. The four bar states (idle / waiting / charging / done) plus the two tariff-window colours (cheap / peak), which previously were only explained behind `?`, are all labelled inline; swatches enlarged and text contrast raised (reported by @RienduPre in #464)
- **Cheap-tariff colour split from the charging green** — the cheap-tariff overlay used the same `#8DC892` as the "charging" segment; it's now a distinct deeper green and the tariff entries render as thin lines, mirroring how they appear on the strip's top edge (reported by @RienduPre in #464)

# [1.7.3-beta.11] - 12.06.2026

## ⚡ Surplus start/stop flapping: enable/disable delays reconnected (#461)

The v1.7 `decide() → actuate()` rewrite silently orphaned the v1.7.1-beta.14 stability layer: `ev_enable_delay_seconds` / `ev_disable_delay_seconds` still existed as config keys but were only read by the legacy `_execute_ev_control` path the new pipeline no longer calls. Result in RienduPre's beta.10 logs: solar hovering around the 6 A minimum cycled the contactor every ~20 s (±4.5 kW demand swings between consecutive health-check lines).

- **The delays are enforced again** — a new `charge_stability` filter sits between `decide()` and `actuate()` in both pipeline branches: a surplus charge only **starts** after the surplus has held for `ev_enable_delay_seconds` (default 60 s), and only **stops** after the deficit has persisted `ev_disable_delay_seconds` (default 300 s), holding minimum current meanwhile. Applied before state display, so the strategy sensor names the active hold instead of contradicting the measured power
- **Stop semantics upgraded to evcc's deficit-persistence** ([evcc-io/evcc](https://github.com/evcc-io/evcc) `enable.delay`/`disable.delay`) — the legacy implementation measured from session start (a minimum-run-time), so a session older than the window still died on a single-cycle cloud dip. The deficit timer protects the contactor for the whole session
- **Night floors, `always_max`, OFF/DISABLE and unplugs are never delayed** — safety and user-intent transitions bypass the filter; timers are independent per charger
- **Both settings are now real entities** (`number.sem_ev_enable_delay_seconds` / `number.sem_ev_disable_delay_seconds`) on the Config tab's **Advanced** section with ?-help texts — previously they were raw config keys with no UI surface
- **Mid-session setpoint smoothing restored too** — the same rewrite orphaned Layers 1-3 + the ramp limiter, so the commanded current bounced cycle-by-cycle until some cars declared the supply unreliable and ended the session themselves. The filter now median-smooths the target stream (`ev_surplus_smooth_window`, 3 cycles — a 1-cycle inverter flicker never reaches the car), moves at most `ev_ramp_rate_amps` (2 A) per change, suppresses sub-`ev_min_change_amps` changes, allows one change per `ev_min_change_interval_sec` (30 s), starts sessions gently at minimum current (the 2026-05-31 grid-overshoot fix), and ramps down to minimum instead of jumping during the disable hold

## 🗓️ Per-charger plan strip + help text (#464)

RienduPre's follow-up: "why is this bar the same for both chargers, and what is it for?" The bar is the 12-hour plan strip (#282) — and it was identical because only one fleet-level plan existed, composed from the primary charger's night plan/target/deadline, then rendered inside every charger section.

- **Each charger now gets its own plan** — `today_plan` is composed per charger from ITS night plan, target, deadline, charge mode and live-session ETA; surfaced as `per_charger_plans` on `sensor.sem_charging_state` (fleet `today_plan` stays the primary's plan for the Today-plan card and as the card-side fallback) (reported by @RienduPre in #464)
- **Stale night plans can no longer leak into day plans** — the per-charger night-plan map was write-only and never cleared; it now resets every cycle
- **The strip explains itself** — it has a title ("Today's plan · next 12 h") and, with the card's ?-help toggle on, a legend explanation (grey = idle, purple = waiting for a cheaper hour, green = charging, teal = target reached; the thin top line marks cheap/expensive tariff windows). Translated in all 15 languages; bar slightly taller and the legend more legible
- **Waiting-for-cheap is read per charger** — the strip derives the wait state from its own charger's plan rows instead of the primary-scoped `ev_tariff_waiting` attribute

## 🧪 Health-check & strategy-label triage from the #461 beta.10 dump

RienduPre's 2026-06-12 dump showed the flows finally coherent, but 69 "Energy balance" violations and a `charging_strategy` claiming `solar_only` on chargers configured `solar_plus_cheap`.

- **Energy-balance "violations" during the home-consumption hold are demoted to debug** — `home_consumption_power` is derived as the residual of the other readings, so supply≈demand is an identity; a gap can only appear when the residual went negative (one input sensor stale, e.g. a Growatt solar reading frozen for ~5 min) and the #237/#444 hold bridged it. Those cycles re-reported a known, already-handled inconsistency every 10 s and inflated `diag_health_violations`. A gap that *outlives* the hold window still warns, now naming the likely cause (stale power sensor) (reported by @RienduPre in #461)
- **Delegated day strategies keep their configured mode label** — `solar_plus_cheap` (day, normal/cheap tariff) and `min_plus_solar` (day, Zone 2) delegate to the solar_only math but no longer report `mode="solar_only"`/`"solar_only: …"` verbatim; the strategy string now reads `solar_plus_cheap day: tariff=normal — solar_only: …`, so the Config card's mode and the live strategy can't appear to contradict each other (reported by @RienduPre in #461)

## 🎨 Dashboard typography, spacing & mobile fixes (#498)

- **Minimum text size raised across all cards** — 11px floor for regular text, 10px for uppercase micro-labels (was down to 9px); fractional sizes normalized; em-based charger labels 0.7/0.75em → 0.8em, hierarchy preserved (by @traktore-org in #500)
- **Hero card padding aligned** — system, home-status and solar-summary now share the same `16px 20px` container padding as the other hero cards; cramped metric-row paddings normalized (by @traktore-org in #500)
- **Mobile fixes from viewport testing** — `sem-tab-header` wraps instead of crushing the title to zero width on phones; `sem-battery-zones-card` clamps zone markers to 0–100% so an out-of-range sensor can't stretch the card; `sem-schedule-card` SVG labels bumped for legibility (by @traktore-org in #500)

## 💶 Cost/ROI: battery savings + volume-weighted tariff history (#499)

- **Battery discharge savings now count toward lifetime ROI** — the midnight snapshot accumulates `cost_batt_savings` into a persisted `_accumulated_battery_savings` folded into `lifetime_total_savings`; the pre-SEM solar-through-battery share already inside `lifetime_self_consumed` is deliberately not re-estimated (no double-count, pinned by a regression test) (by @traktore-org in #500)
- **Dynamic-tariff rate history is volume-weighted** — snapshots store the day's `cost ÷ kWh` instead of the midnight rate (systematically among the cheapest spot hours), removing the low bias in the 7-day average used for the pre-SEM ROI estimate; falls back to the current rate on days without positive cost data (by @traktore-org in #500)
- **Negative-price consistency** — battery savings clamped `max(0, …)` at daily/monthly/yearly read, matching solar savings (by @traktore-org in #500)

---

# [1.7.3-beta.10] - 11.06.2026

## 💶 Tibber Grid Reward price arrays (#491)

Tibber Pulse accounts where the core Tibber integration provisions no `electricity_price` forecast sensor (upstream core#153312) get their only day-ahead curve from the HACS [tibber_grid_reward](https://github.com/JohNan/homeassistant-tibber_grid_rewards) `sensor.current_price`.

- **`today_raw` / `tomorrow_raw` price arrays are now parsed** — the `{time, price}` item keys were already known; only the two attribute names were missing. Configure the sensor via *Tariff settings → Dynamic tariff entity*; its id is too generic to auto-detect (reported by @RienduPre in #491, fixed in #495)
- The Grid Reward sensor's `today`/`tomorrow` attributes are comma-joined *strings* — skipped by the list guard, so the curve is never double-counted

## 🔋 Battery scheduler crash with saved options (#493)

- **Scheduler evaluation no longer dies on every cycle for users who ever saved the battery-scheduler options page** — the options-flow slider stores the trigger hour as a float (`21.0`) and `datetime.replace(hour=21.0)` raised `TypeError`, killing nightly planning entirely; trigger hour/minute are now coerced (`int(float(...))`, surviving string-shaped storage too). Untouched configs keep the int default, which is why soaks missed it (reported by @RienduPre on #487, fixed in #496)

---

# [1.7.3-beta.9] - 11.06.2026

## 🔌 Wallbox actuation: entity-range bounds + working stop path (#487)

RienduPre's error log exposed the real "keeps charging in off mode" mechanism: SEM wrote 0 A (stop) and >entity-max amps to the Wallbox max-current number entity — HA core rejects both with `out_of_range` **before anything reaches the charger** (167× per charger in the log).

- **Current writes are bounded into the target entity's own min/max** — a charger whose entity allows 6–16 A gets 16 A when SEM wants 32, instead of a rejected command (by @traktore-org in #490)
- **0 A stop intents skip the structurally impossible number write** — the stop goes through the adapter's pause-switch / stop_session path (Wallbox min=6 A, IEC 61851)
- **`ev_start_stop_entity` is now actually honored** as the Wallbox pause/resume switch — the adapter's own WARNING recommended it as the workaround but never read the field (RienduPre's #462 finding)
- **Health-check violation WARNINGs are rate-limited** — after 6 consecutive violating cycles they drop to debug until they clear (413 identical lines flooded the log + the diagnose ring buffer)

## 🧭 Grid-sign restart hardening (live PROD flip, #487 follow-up)

A restart locked `grid_sign_inverted=True` on a Huawei install whose convention needs NO correction — 3 sign votes cast while HA's recorder was still replaying counter states (#476 items 5/6 gap, observed live 2026-06-11).

- **Sign votes are ignored for the first 12 cycles after startup** (~2 min) — baselines stay fresh, nothing locks
- **The sign-lock log line now names the voting counter entities**, so a wrong lock is diagnosable after the fact

## 🖼️ Diagram card blank on Home tab (#488)

- **Backticks inside a lit-template HTML comment terminated the template literal** — the remainder re-parsed as a tagged-template chain: syntactically valid JS (rollup/CI green) that threw at render time, blanking the system diagram. Fixed + a lint test forbidding backticks in card-template comments (by @traktore-org in #489)

## 🔍 Pre-stable review batch (#485)

A full 7-angle review of everything on develop since v1.7.2 surfaced 23 verified findings — two of them stable-release blockers in this release's headline features. All fixed in one batch.

### 🚨 Blockers

- **Rolling-horizon scheduler no longer ratchets the charge target** — `evaluate()` re-anchored the target on the live SOC every 30-min re-plan, stacking the deficit on top of charging progress until the battery grid-charged to ~95% every profitable night. The target is now anchored on the SOC at the first evaluation of the night's window, and a mid-charge re-evaluation that lands on NOT_NEEDED/NOT_PROFITABLE stops the active forced charge (by @traktore-org in #485)
- **`set_option` on construction-time keys reloads again** — keys like `tariff_mode` and the `battery_*` scheduler params persisted + mirrored into a config dict nothing re-reads, so the live Config-card select "succeeded" while the constructed provider/scheduler kept the old value until restart (the #462 silent-no-op class) (by @traktore-org in #485)

### 🛠️ Fixes

- **Re-plan trigger fires once per price update** — day-ahead prices publishing ~13:00 used to log two INFO lines every ~10 s cycle until the 21:00 window opened (thousands/day), evicting everything useful from the 300-line diagnose ring buffer built for #461/#462 triage
- **15-min markets: slot length comes from the provider** — gap inference over *selected* slots booked 2–4× oversized slots for scattered selections, corrupting the night plan's energy accounting
- **`battery_cycle_cost` runtime default back to 0.0** — the silent 0.0→0.02 flip tightened the break-even on upgrade and stopped thin-margin night charging with no config change; 0.02 stays as the *visible* form default for new configs
- **Nord Pool fetch failure backoff** — an API outage used to trigger two blocking service calls every cycle (~17k/day); failures now back off 5 minutes
- **`_merge_ev_chargers_by_id` preserves charger order** — a partial submit (or the setup heal) could reorder the fleet, silently swapping the index-0 primary and default surplus priorities
- **set_option mixed payloads are atomic** — tunables route through entities first, then ONE direct write + ONE reload (the structural write used to fire a listener reload racing the still-running tunable calls, dropping values mid-payload)
- **set_option switch routing coerces YAML strings** — `"off"`/`"false"`/`"0"` were truthy and turned the switch ON
- **Split-grid: a late-loading export sensor now completes a one-sided pick** — including the same-device case that blocked re-discovery until restart; the held import side is never re-rolled
- **Dual-tariff auto sign vote** — `_detect_grid_sign` sums the NL DSMR tarief-1/2 counter lists (beta.8 fixed only the manual-audit path)
- **Deterministic split-grid discovery** — candidates scan sorted by entity_id, so import/export roles can't re-roll across restarts
- **Stale actuation Repair clears after a reload** — the persistent ERROR Repair raised before a config fix stayed in the UI forever because the new device instance's flags started fresh
- **Canonical primary-charger id** — the fleet-strategy gate's `"ev_charger"` fallback disagreed with registration's `"ev_charger_0"` for id-less chargers, freezing the strategy sensor on exactly the corrupted configs this release hardens against
- **Entity-domain charger services generalized** — `input_number.set_value` / `select.select_option` configured as the charger service bounced off their schemas exactly like the beta.8 `number.set_value` case
- **Configured 0.0 electricity rates are respected** — `config.get(...) or 0.30` treated a real zero rate as missing
- **Reload-skip snapshots expire after 60 s** — a lingering snapshot could swallow a legitimate reload on a future data/title-only entry update

### ⚡ Performance

- **Price curve parse memoized** — the full parse (isoformat + classify + sort + dedupe) ran 3–5× per coordinator cycle; now keyed on entity-state identity + service-fetch timestamp + percentile slot epoch
- **Split-grid sensor scan throttled** — with healthy two-sided picks held, the full `hass.states` scan runs every 30 cycles instead of per cycle with the result discarded; the per-cycle INFO log only fires when the result changes

### 🧹 Cleanup

- `persist_per_charger_option()` — single write path replaces the ~30-line copies in select/number/time (the time.py copy was the writer #469 missed); `_saveChargerField` dedups the config-card's nested editors; `semFormatTime` unifies the dashboard's two clashing time formats; tariff auto-detect shares the provider's candidate matcher (the flow missed Octopus/Amber); dead `_set_option_needs_reload` helper removed; shared `_counter_deltas` reset guard for the three sign voters

### 🧪 Tests

- ~60 new tests: target-SOC anchor + mid-charge stop, replan one-shot, slot-hours hint, fetch backoff, parse memo, falsy-zero rates, merge order contract, switch coercion, unrouted-key reload (real-hass), late-export adoption, scan throttle, dual-tariff vote, deterministic discovery, entity-domain service routing, stale-Repair clear, primary-charger id contract

---

# [1.7.3-beta.8] - 10.06.2026

## 🔌 Actuation hardening + triage surfaces (#462 follow-up batch)

RienduPre's attached error log revealed the final #462 mechanism: with `ev_charger_service: number.set_value`, SEM sent `{current: X}` through the service path — `number.set_value` only accepts `value`, so **every current command on both chargers failed** (`extra keys not allowed @ data['current']`), including the 0 A for off-mode, with the evidence buried in per-cycle ERROR log lines.

### 🛠️ Fixes

- **`number.set_value` as charger service is now mapped to the number-entity write it was meant to be** (`value` + entity_id) — the misconfigured-but-recoverable shape can no longer leave a charger silently uncontrollable
- **Repair issue on repeated actuation failure**: 3 consecutive rejected set-current commands raise a user-visible Repair naming the charger and the error (severity ERROR, translated EN/NL/DE + EN fallback for the rest); clears automatically on the next successful write
- **Registration WARNING** when `ev_charger_service=number.set_value` has no `number.*` target entity
- **Fleet `charging_strategy` / `charging_strategy_reason` are now consistent** — the per-charger loop let the *last* charger overwrite `charging_strategy` while `charging_strategy_reason` kept the primary's value ("always_max …" next to "off mode …" in the same dump); only the primary charger writes both now (per-charger detail lives in `charger_<id>_charging_state`)

### 🔍 Triage surfaces

- **In-memory SEM log ring buffer** — the diagnose payload's `recent_logs` now carries the last ~300 INFO+ SEM log lines on EVERY install type; Supervisor installs (journald, no flat log file) previously got a "please run `ha core logs`" placeholder, which left the whole #461/#462 triage blind
- **Manual-grid audit is dual-tariff aware** — the sign cross-check sums the import/export counter *lists*, so NL DSMR tarief-1/2 splits no longer blind it during one tariff's hours
- **Blocking `open()` calls removed from the event loop** ("Detected blocking call" in RienduPre's log): translations and the manifest version are warmed off-loop at setup and cached (`diag_version` no longer re-opens manifest.json every cycle)
- TROUBLESHOOTING: manual grid entity checklist (import vs export roles, power-not-energy, both-or-neither) + Dutch dual-tariff Energy-Dashboard guidance

### 🧪 Tests

- New framework tier `tests/test_actuation_real.py`: real-HA schema-strict `number.set_value` shape test + the failure → Repair → recovery → clear cycle through the real issue registry
- `test_services_real.py`: diagnose `recent_logs` served from the ring buffer (Supervisor parity) + cached version
- Unit: actuation routing/param contracts, Repair threshold/idempotence/intermittent-flap behavior, log-buffer capture/capacity/idempotence, dual-tariff audit summing

---

# [1.7.3-beta.7] - 10.06.2026

## 🔎 Manual grid override validation + sign audit (#461 follow-up)

v1.7.3-beta.6's pick-stability fix addressed the auto-discovery path — but an install with `grid_import_power_entity` / `grid_export_power_entity` set explicitly bypasses ALL sign machinery, so a swapped, one-sided, or wrong-kind (energy counter as power sensor) configuration produces a statically inverted grid with zero feedback. Exactly the verified #461 shape: explicit entities configured, no discovery log lines, grid shows export while importing, house consumption 0, surplus invisible to every controller.

### 🛠️ Fixes

- **Manual grid config validation** (warn-once): an ENERGY counter (kWh) configured in a POWER field; only one side configured while the Energy Dashboard tracks both flows (the missing side reads a hard 0 W — "always exporting")
- **Observe-only sign audit**: the manual-computed grid sign is cross-checked against the Energy Dashboard import/export counters every cycle; 5 consecutive contradictions log a WARNING naming both configured entities ("most likely SWAPPED") and set `diag_grid_manual_mismatch` in the diagnostics — SEM never silently overrides manual config, it makes the misconfiguration loud
- Counter-reset and ambiguous-delta cycles are excluded from the audit (same guards as the autodetect path)

## 🧰 Robustness batch (#476, part 1)

Soundness/stability items from the 2026-06-10 review. No behavior changes on the happy path.

### 🛠️ Fixes

- **Back-to-back runtime writes no longer trigger a spurious reload** — the options-update listener consumed the `_skip_options_reload` snapshot on first match, so the second of two quick entity writes found no snapshot and reloaded the integration. Snapshot is now kept on match and cleared on mismatch — provably leak-free (HA only fires the listener when options actually change)
- **Energy-counter reset guard** — Growatt-style daily counters can reset at midnight in *different* update cycles; the surviving side's increment could cast a wrong grid/battery sign vote. Negative delta on either side now re-baselines and skips the vote (grid + per-battery variants)
- **`set_option` mixed payloads** — the skip snapshot is no longer armed when structural keys force a reload anyway (stale state on a discarded coordinator)
- **Charger-id sanity at registration** — WARNING on id-less entries (positional fallback can collide with a real sibling) and on duplicate ids (writes target only the first match)
- **Config card**: per-charger rows with no resolvable id are skipped instead of rendering `…_undefined_…` entity lookups; save-status timers cancelled on disconnect (same for the diagnose button's copy timer)

### 📝 Notes

- Heal-vs-auto-discovery ordering documented as intentionally heal-first (prevents the reseed from firing on heal-able installs)
- Deliberately deferred from #476: sign-state persistence (persisting a wrongly-locked sign would make bad locks permanent — needs a validation design first) and vote-threshold changes (3-vote lock-in is pinned as contract by the #352 test suite; the dominant reset windows are already closed)

---

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
