# SEM Bug-Class Ledger

**Why this exists.** SEM's highest-value reliability work comes from one observation:
*a fix is instance-local, but the bug **class** survives in the sibling paths.* The same
mechanism breaks again in the next brand, the next charger, the next signal. This ledger
makes the recurring classes **visible** so every fix can ask "what class is this, and where
else does it live?" — and so each class gets closed *structurally*, not one instance at a time.

**How to use it.**
- **Fixing a bug?** Find (or add) its class below. Then **sweep the sibling paths** listed under
  "Where it lives" — fix them in the same change if cheap+safe, else flag them. A fix isn't done
  until the class is swept.
- **Closing a class?** Give it a **guard** that makes regression *unrepresentable* (an AST lint, an
  isolation oracle, a contradiction detector). Update the status here.
- **New recurring shape?** Add a row. One class, one structural closure, one guard.
- The `/coherence-audit` workflow cross-checks the codebase against this ledger periodically.

Status legend: **OPEN** (recurs, no structural closure) · **GUARDED** (closure + a guard that fails CI/surfaces it) · **PARTIAL** (some paths closed, siblings remain).

---

## The classes

### 1. Sign-convention mis-read (grid / battery) — GUARDED
**Symptom:** import/export or charge/discharge inverted; the whole energy balance + every derived
figure silently wrong. **Root shape:** a sensor's sign convention varies by brand/meter; SEM must
detect or be told it, and a wrong lock is *silent* because `home` is defined *by* the balance
(the balance check is tautological — it can't catch its own sign error).
**Where it lives:** `coordinator/sensor_reader.py` (grid + per-battery); every inverter brand.
**Closure:** brand seed (deterministic default) + counter-correlation detector + solar-anchored
physical override (grid) + one-tap flip service. **Guard:** the *perception cross-check*
(`_audit_*` → `binary_sensor.sem_layer_mismatch`, `perception:<signal>`) surfaces a locked-but-wrong
sign the control layers cohere past. Refs #352 #461 #476 #588 #589 #590.
**Watch:** battery has no *physical* anchor (grid has solar) — a swapped-counter battery relies on
the counter detector + the perception audit + the manual flip.

### 2. Per-charger state leak (charger[0] → charger[1]) — GUARDED
**Symptom:** in a multi-charger fleet, charger 2 behaves like charger 1 (inherits its timers/flags).
**Root shape:** per-charger state swapped through the coordinator's *primary scalars* in a
snapshot/restore; forget a write-back and it leaks. **Where it lives:** `PerChargerContext` +
`coordinator/ev_control.py`. **Closure:** durable `PerChargerState` on `_pcc_store`, held *by
reference* — no swap, no write-back to forget (Surface A+B). **Guard:** 14 cross-charger isolation
tests (real coordinator, divergent values → no leak) + the AST guard forbidding a new
`coord._ev_* =` swap. Refs #284 #289 #315 #318 #589.

### 3. Fleet-read-for-one (per-charger code reads the fleet sum) — GUARDED
**Symptom:** a per-charger decision uses `power.ev_power` (the fleet total) instead of THIS
charger's draw → false-full SOC, wrong budget. **Where it lives:** `ev_control.py`, the per-charger
loop, `_update_ev_intelligence`. **Closure:** `FleetEvPower` newtype + `_this_charger_power`.
**Guard:** the FLEET-READ AST lint (`tests/test_ev_power_reads*`). **Watch:** the lint checks a read
is *annotated*, not *correct* — a green-lint fleet read into a per-charger detector is still
possible (fixed one at #589 EV W2/W3). Refs v1.6.0–6.6, #589.

### 4. Strand-across-restart (a force op left running on the real inverter) — GUARDED
**Symptom:** a reload mid-force-op leaves the battery force-charging/discharging autonomously; a
swallowed command reports success while nothing moved. **Where it lives:** `battery_adapters/*`,
`async_unload_entry`. **Closure:** honest command results (record intent only on success → retry),
boot reconcile + unload cleanup across *all* intents/brands (not just Huawei discharge).
**Guard:** command-honesty tests. Refs #532 #535 #589.

### 5. Degenerate / frozen sensor input — PARTIAL
**Symptom:** an `unavailable` or *available-but-frozen* sensor feeds `0.0`/a stale value into the
balance + sign detection, silently distorting figures. **Where it lives:** `_read_sensor`.
**Closure:** unavailable → Repair after threshold; *frozen* fast-power sensor → warn-once + Repair
(observe-only, W3). Freshness keys off ``last_reported`` (advances on every state-machine write),
NOT ``last_updated`` (advances only when the *value* changes) — else a fast-power sensor that
legitimately holds a constant value for >10 min (a split discharge sensor at 0 W while the battery
charges — Fronius; ``grid_export`` while importing; solar overnight) false-positives as frozen
(#611). **Guard:** `test_589_sensor_freshness.py::test_constant_value_but_still_reporting_not_frozen`
+ the missing-`last_reported` fallback test. **Open siblings:** the frozen value still *feeds* the
balance (observe-only, not yet held); multi-unit partial-availability sums silently under-report
(audit W6). Refs #274 #461 #589 #611.

### 6. Multi-unit over-command (N× / partial split) — PARTIAL
**Symptom:** a fleet-level power target handed to *each* of N units → N× the intended
grid export/charge. **Where it lives:** `decide_battery.py` (arbitrage vs LIMIT_DISCHARGE).
**Closure:** `LIMIT_DISCHARGE` splits `home/n`. **Open sibling:** the (dormant) arbitrage
`FORCE_DISCHARGE` path does NOT split — a guard note + re-enable checklist is in place (#533).
Refs #531 #533.

### 7. Restart re-arms a safety timing window — GUARDED
**Symptom:** an HA restart resets a monotonic timer, re-arming a full grace window (e.g. the
deep-deficit battery-drain bridge). **Where it lives:** `charge_stability.py`. **Closure:** persist
+ rebase the stability epochs across restart (snapshot/restore). Refs #461 #589.

### 8. Tautological / can't-fail check — PARTIAL
**Symptom:** a "health check" that is algebraically incapable of firing (the energy-balance check is
`0 = 0` because `home` is defined by the balance) → a whole error class stays silent.
**Closure:** the *independent* perception cross-check (counter-vs-power) catches sign errors the
balance can't. **Open:** any other self-referential check; audit for them in `/coherence-audit`.
Refs #589.

### 9. Engine-specific SVG/SMIL form (renders on Blink/Gecko, silent on WebKit) — GUARDED
**Symptom:** a dashboard-card visual works on desktop Chrome/Firefox and Android but is dead on
*every* iOS browser (Safari, Chrome, HA Companion app — all WebKit) with no error. **Root shape:**
the card emits an SVG/SMIL construct that WebKit resolves more strictly than Blink/Gecko — the flow
dots used `<animateMotion><mpath href="#id"/></animateMotion>`, but WebKit only matches the
XLink-namespaced `xlink:href` on `<mpath>`, so the plain `href` never bound and the dot had no path
(#591). Lenient engines accept the plain `href`, so it passes every desktop/Android check — the gap
is invisible until an iOS user reports it. **Where it lives:** all animated SVG in the dashboard
cards — `dashboard/card/sem-system-diagram-card.js` (vanilla), `dashboard/card/src/cards/*.js`
(sem-flow-card, sem-system-diagram-card), built into `dist/sem-cards.js`. **Closure:** drop the
`<mpath>` indirection — inline the motion path as `<animateMotion path="M…">` (the SVG 1.1 form
supported on every engine incl. old WebKit); path data is already at each site. **Guard:** the
mpath ban + inline-path presence test (`test/mpath-webkit-guard.test.js`, in CI's `card-test` job)
makes the WebKit-broken reference form unrepresentable in card source. Refs #591.
**Watch:** the guard covers `<mpath>` specifically; other WebKit-strict forms (bare `href` on
`<use>`/`<textPath>`/gradients, `xlink:` assumptions) can still bite — sweep them if a new
"works everywhere but iOS" card bug appears, and widen the guard.

### 10. Power-derive keyword gap (brand/locale naming not in the include list) — PARTIAL
**Symptom:** a source's real-time power reads 0/null forever while its energy counters are fine
(`batt:pwr=none` in `diag_ed_config`, yet the brand's power sensor exists and is valid) — SEM never
resolves the power entity, so every derived flow for that source is silently 0. **Root shape:** when
the Energy Dashboard has no `stat_rate` power link, SEM *derives* power from the energy sensor's
device via a hardcoded English keyword substring list (`_POWER_DERIVE_RULES`); any brand/locale
whose entity_id isn't in the list is invisible, and unlike SOC there's *no manual override* to fall
back on. The device+`device_class=power` scoping keeps it from being a pure "match anything" rule, so
the list must actually name each brand's slug (EN **and** localized). **Where it lives:**
`ha_energy_reader.py::_POWER_DERIVE_RULES` — the `solar`, `grid` **and** `battery` include lists (same
shape as the multilingual `_DISCHARGE_CONTROL_PATTERNS` in `hardware_detection.py`). **Closure:**
multilingual keyword coverage per brand — #597 added Huawei's `charge_discharge_power` (EN) /
`lade_entladeleistung` (DE) to the battery list. **Guard:** the brand-naming table test
(`test_battery_power_derives_for_huawei_naming`) makes an un-covered brand slug fail CI.
**Open siblings:** the `solar` list (`pv_power`/`solar_power`/`production_power`) and `grid` list are
still English-shaped — Huawei's `inverter_input_power` / German PV slugs are *not* covered; sweep them
if a Huawei/localized user reports solar or grid reading 0 (grid already matches via `power_meter`).
Refs #250 #274 #597.

### 11. Corrected value overwrites a raw display field (paired-figure basis mismatch) — GUARDED
**Symptom:** two figures shown side by side on a card disagree in a way that reads as a
contradiction — the "Remaining" tile far below the "Forecast today" tile at *dawn*, when almost
nothing has been produced (today 70.8 kWh / remaining 35 kWh, #598). **Root shape:** a *corrected*
quantity (a dampened/adjusted planning value) is written **back onto the field that also feeds a
raw display sensor**, so one tile is raw and its sibling is corrected — different bases, same card.
The corrected value is legitimate for planning; the defect is that it *leaked* into the display
field instead of staying local. Here `forecast_remaining_today_kwh` was overwritten with
`raw_remaining × dampening_factor` (which sits near its 0.5 clamp floor in the morning) while
`forecast_today_kwh` stayed raw. **Where it lives:** `coordinator/coordinator.py::_update_analytics_phases`
(forecast display fields); any place a `* factor` / `apply_dampening()` / correction result is
assigned back to a `*_data` field that `to_data()` publishes. **Closure:** keep the corrected value
in a LOCAL variable for planning (surplus/window/control already re-derive dampening from the raw
`_cycle_forecast`); write the display field exactly once — the raw reader value — and never
re-derive it. **Guard:** `tests/test_598_display_remaining_astguard.py` — an AST lint that fails CI
if `_update_analytics_phases` assigns `forecast_data.forecast_remaining_today_kwh` more than once, or
assigns it anything other than the raw reader attribute. Refs #598.
**Watch:** the guard covers the remaining-solar field specifically; sweep the other paired display
fields if a new "these two numbers contradict each other" report appears — e.g. a corrected
`forecast_today_kwh`, or any tariff/PV figure shown raw beside a corrected sibling.

---

## Meta-classes (the coherence audit hunts these too)

- **Duplicated mechanism** — the same debounce/retry/reconcile/swap built in 2+ places (e.g. the
  sign-audit debounce vs the trace streak; the CounterCorrelationAudit dedup). Unify into one.
- **Parallel systems that are one concept** — two things modeled separately that should be one
  (e.g. arbitrage folded INTO the scheduler; the canonical `EVBudget`; the ONE priority list).
  *Sub-shape — a parallel priority/ordering knob that clobbers the unified list:* a standalone
  `*_priority` config re-set onto a device's `.priority` every cycle, killing its drag position
  (`heat_pump_priority`/`hot_water_priority` at coordinator 6439/6464 — #602/#576; the retired
  `ev_shed_priority`/#514 EV steppers were the same). **Sweep:** grep every `.priority =` — it must
  read `priority_for(id, seed=config)`, never assign the config directly. Adjacent leftovers: #604.
- **Spec-vs-reality gap** — something *designed but never wired* (e.g. the layered-trace health
  signal was a spec + a method but never an entity until #590). Verify the assumed thing *exists*.
- **Marginal refactor (do NOT force)** — a dedup that needs a shim or wide test churn for a
  maintainability-only gain (e.g. the MagnitudeVoter proxy, the debounce-primitive). Recorded so
  we don't keep re-litigating them.
