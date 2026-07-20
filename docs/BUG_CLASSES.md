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

### 12. Duplicate device row (authoritative registration vs ED auto-discovery, deduped by id) — GUARDED
**Symptom:** one physical appliance appears **twice** in the overview / priority list — once under
the user's Energy-Dashboard friendly name, once under SEM's control label (#615: "warmtepomp" AND
"heatpump" side by side). **Root shape:** the same device is registered from *two* sources — an
authoritative direct/service/charger registration keyed by a **control id** (`heat_pump`,
`hot_water`, the charger's control id, a `register_surplus_device` id) *and* an Energy-Dashboard
individual-device auto-discovery keyed `energy_dashboard_<slug>` (derived from its energy sensor).
`get_devices_for_sensor`'s dedup keys on the **id**, so the two ids never collide and both rows
emit. **Where it lives:** `features/device_registry.py::get_devices_for_sensor` — every path that
suppresses an ED row in favour of an authoritative one. **Closure:** dedup on the **shared entity**,
not the id — suppress the ED row when its power/energy/control entity is claimed by an authoritative
registration. Three sibling suppressions now exist: service (`service_entities`, #559), charger
(`_configured_charger_entities`, #576 P2.1), and direct heat-pump/hot-water/climate
(`_direct_registration_entities`, #615 — covers *all* non-ED, non-EV, non-service direct
registrations structurally, not per-device). **Guard:** `tests/test_615_hp_ed_duplicate.py` (an ED
row sharing the HP/HW power/energy/switch entity yields ONE row; a distinct ED device is untouched).
Refs #559 #576 #615.
**Watch:** all three suppressions live inline in one method — if a *fourth* authoritative source is
added (e.g. a new appliance controller family), reserve its entities the same way or it re-opens the
class. The dedup matches on `energy_sensor`/`power_sensor`/`control_entity`; a device that shares
none of these (e.g. a climate-only HP with a separately-named ED energy counter) can still slip
through — but ED individual devices are *defined by* their energy sensor, so that overlap is the
realistic one.

### 13. Single-charger-in-list read as legacy (`len(ev_chargers) > 1` guard) — GUARDED
**Symptom:** a lone EV charger configured through the config-flow (its sensors stored in
`ev_chargers[0]`, NOT the flat top-level keys) has a fleet-level quantity silently read from the
*empty* legacy top-level sensor — `ev_power=0` (false home spike → surplus-budget flap), per-charger
flows blank, and (#616) `ev_connected=False` while `charger_<id>_connected=True`, so the EV policy
reports "min_plus_solar but EV disconnected" and commands **0 A forever** even though the plug sensor
reads ON. **Root shape:** a `len(ev_chargers) > 1` guard used as a proxy for "is this a multi-charger
fleet" — but a *single* config-flow charger also lives in the list, so the `else` branch (legacy
top-level flat keys) is wrong for it whenever those keys are unset. **Where it lives:**
`coordinator/sensor_reader.py` — every place that chooses between per-charger `ev_chargers[i]` sensors
and the flat top-level config: `ev_power` (fixed → `any(c.get("ev_charging_power_sensor"))`),
`ev_connected`/`ev_charging` (#616 → `_read_ev_connection_status`, now shared by BOTH read paths),
per-charger flow attribution (v1.6.15 fleet-sum, `test_split_grid_integration.py`). **Closure:** gate
on `any(c.get("<the_sensor>") for c in ev_chargers)`, not the list length; read the per-charger sensor
and fall back to the top-level key *per signal*. #616 also unified the two duplicated
connection-status blocks (`_read_from_energy_dashboard` + `_read_from_legacy_config`) into one helper
so the guard can no longer drift between the read paths — which is exactly how the `ev_power` fix
missed the `ev_connected` sibling. **Guard:**
`test_per_charger_entities.py::test_single_charger_connected_sensor_in_list_sets_fleet_connected` +
`test_ev_power_single_charger_unchanged`. **Watch:** entity-creation dedup guards (`sensor.py`
per-charger flow *entities*, ~line 1618) legitimately keep `len > 1` — they suppress duplicate
registry entities, they don't read config; do NOT "fix" those. Refs #536 #616.

### 14. One-shot restore vs a late/rebuilt device (accrued per-device state resets) — PARTIAL
**Symptom:** a load's accrued daily progress ("X/Y h on solar today", the runtime toward its
minimum-runtime goal) resets to 0 on every HA restart and the load re-runs its whole daily target —
even though a persist+restore for it exists. **Root shape:** per-device state that lives in the
coordinator's daily store (NOT the registry's override store) is restored **once**, at a fixed point
in setup. Anything the registry re-applies *during* `_sync_to_surplus_controller` on every rebuild
(rated_power #576, control_mode, dependencies #122, goals #559 via `_apply_goals`) survives a late or
rebuilt device for free; the one-shot-restored state does not. An auto-discovered load whose backing
entity isn't ready at setup is created only by the 35 s delayed re-discovery — *after* the one-shot
restore already ran and found no device — and the rebuild's runtime restore reads only an **in-memory**
snapshot (`_restore_accrued_runtimes`), which is empty for a device never populated from storage
(alexmc1510's pool pump, #622). #586 was the same shape one ordering earlier (restore ran before the
registry existed at all). **Where it lives:** `coordinator/coordinator.py::_restore_device_runtimes`
(daily runtime — closed #622) and the sibling one-shot restores in the first-refresh block that key off
a device by id: `record_legionella_cycle` / `get_legionella_time` (#508, coordinator.py ~1927) — the
`hot_water` device is registered *after* first-refresh (`__init__.py` ~1902), so that restore is a
no-op and the legionella timestamp is lost on restart (**open sibling — temperature-safety, Guido**).
**Closure (#622):** make `_restore_device_runtimes` idempotent (fill only a device whose live accrued
is 0 — never clobber a live value) and have the registry re-invoke it via `_runtime_restore_hook` after
**every** `async_refresh_devices` rebuild, so a late device is filled from storage. **Guard:**
`test_622_late_device_runtime_restore.py` (idempotent fill + never-clobber + the hook fires after the
in-memory restore on every rebuild). **Watch:** any NEW per-device state persisted to the daily store
and restored one-shot in the first-refresh/setup block is a fresh sibling — restore it on the rebuild
path (registry store or the runtime hook), not once at a fixed setup point. Refs #508 #586 #622.

### 15. Card action re-resolves a row by a non-unique key (energySensor collision) — GUARDED
**Symptom:** a per-device dashboard action opens against the WRONG device — the config card for one
load shows a *sibling's* control entity (#621: the "car socket" configure dialog showed the "pool
pump" switch), while the underlying data/behaviour is correct (a pure UI mismatch). **Root shape:** a
card row already carries a guaranteed-unique `id` (the `get_devices_for_sensor` dict key), but a
button's handler throws it away and re-resolves the row by a *secondary* attribute that is **not
unique** — `energySensor`, which is `null`→`''` for every device without an Energy-Dashboard energy
counter (service-registered loads, direct heat-pump/hot-water, the battery row). `devices.find(d =>
d.energySensor === '')` then returns the FIRST empty-key row, so all such rows collapse onto one.
**Where it lives:** `dashboard/card/src/cards/sem-load-priority-card.js` — `_showConfigureModal` was
the one offender; every sibling action (`controllable`, `move`, `combined_mode`, `depends_on`,
`_moveDevice`) already resolves by `d.id === deviceId`. **Closure:** the configure button emits
`data-device="${device.id}"` like every other action and the modal resolves via
`findDeviceForConfig(devices, id)` (find by unique id); the mapping service's `energy_sensor` key is
then read off the *resolved* row, not passed as the lookup key. **Guard:**
`dashboard/card/test/load-config-modal.test.js::findDeviceForConfig resolves by id even when
energySensors collide` (two empty-energySensor rows → each id resolves to its own control).
**Watch:** any NEW per-row card action must resolve by `d.id` — never by `energySensor`,
`switch_entity`, `power_entity` or `name`, all of which are null/blank/duplicable for some device
family. Refs #621.

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
