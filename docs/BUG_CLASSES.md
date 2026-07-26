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
balance can't. **Second instance (#661, 2026-07-25):** `health_check` flagged "grid import AND
export both > 10 W" (and the battery twin) — but `calculate_derived` re-derives all four fields from
ONE signed scalar via `max(0, ±x)`, so both-active is *unrepresentable*. The netting happens on
split-sensor installs too, which are exactly the installs the check existed for. Its test passed
only by hand-setting the fields on a `MagicMock`, bypassing the derivation — that bypass is the tell
for this whole class. **Closure pattern:** move the check UPSTREAM to where the raw evidence still
exists (each netting site in `SensorReader`, via `SplitSensorExclusivityAudit`), and DELETE the
downstream copy rather than leaving it as decoration. A check that cannot fire is worse than no
check: it reads as coverage. **Third instance (#651, 2026-07-25) — the test-side twin:**
`test_multi_charger_canonical_budget.py` defined a local
`_select_multi_charger_total_budget()` that, in its own docstring, "inline[d] the relevant lines
verbatim" from the coordinator — then asserted against that copy. A hand-copy of the code under
test cannot fail when the original is wrong, and it stayed green when #651 deleted the original
outright. Same file, a scenario-harness key named `priority_order` whose loop body was a bare
`pass` under the comment "can't reliably check from this side" — a named, documented, YAML-selected
assertion with no teeth, referenced by 1 scenario. **Sweep question (test side):** does this test
call production code, or a local restatement of it? If you deleted the production function, would
this test go red? **Guard:** `tests/scenario_harness.py` now rejects unknown `expect.multi_charger`
keys, so a silently-ignored expectation fails instead of passing.
**Open:** any other self-referential check; audit for them in
`/coherence-audit`. **Sweep question:** for every check, can you name an input that makes it fire —
and can that input survive the transforms between where it is produced and where it is checked?
Refs #589, #651, #661.

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
**New instance (2026-07-24, #635):** the per-charger EV-intelligence restore read
``ev_intelligence.chargers.<cid>`` that NO save path ever wrote, and the primary save
REPLACED the whole dict each cycle (also wiping session_history) — estimated SOC blanked on
every restart. The save/restore ASYMMETRY variant: audit every restore reader for a matching
writer and vice versa.
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

### 16. Per-unit surface suppressed by a higher-precedence fleet override — GUARDED
**Symptom:** a multi-unit install's INDIVIDUAL sensors all go `unavailable` while
the fleet total keeps working — #623: RienduPre's 2×Sessy fleet lost every
`sensor.sem_battery_b1_/b2_*` ("lost my individual battery information somewhere
during the 1.7.5 betas") the moment they also set the combined
`battery_power_sensor` override. **Root shape:** the per-UNIT population
(`readings.batteries` / `readings.inverters`) lives *inside* the same `if/elif`
chain that selects the *fleet scalar*. A newer, higher-precedence fleet-override
branch added to the TOP of that chain (`if self.config.battery_power_sensor:` #597;
`if self.config.solar_power_sensor:` #592) short-circuits *before* the per-unit
loop runs, so the per-unit dict is silently never filled and every per-unit sensor
reads unavailable — the fleet scalar is unaffected, so the regression is invisible
until a multi-unit user reports it. **Where it lives:**
`coordinator/sensor_reader.py::_read_from_energy_dashboard` — the solar (per-inverter)
and battery (per-battery) blocks. The per-battery **SOC** path and the
per-**PV-string** surface were already decoupled (population in its own
`if len(...) >= 2:` block, independent of the fleet-scalar precedence) and were
never hit. **Closure:** decouple per-unit population from fleet-scalar selection —
populate `readings.batteries`/`readings.inverters` whenever the ED exposes ≥2 units,
then let the per-unit *sum* own the fleet scalar (so `fleet == sum(per-unit)` /
`solar_power == fleet_solar_w` holds by construction, #404/#589); the explicit
override applies ONLY when there is no ≥2 breakdown to sum (single/combined installs,
energy-only ED — the exact #597/#592 case). **Guard:**
`tests/test_623_per_battery_override.py` — a combined battery override with a
2-unit ED list still yields `{b1,b2}`; a solar override with a 2-inverter ED list
still fills `readings.inverters`; the energy-only override cases (#597/#592) keep
the fleet scalar with no per-unit surface. Refs #592 #597 #623.
**Watch:** any FUTURE fleet-scalar branch (a new source override, a new aggregation
mode) must be added to the *fleet-scalar precedence* block only — never above the
per-unit population loop. Grep `_read_from_energy_dashboard` for any `readings.<x>[` 
population nested under a `self.config.*_sensor` override branch.

### 17. Gate blocks activation but doesn't stop a running device — PARTIAL
**Symptom:** a new gate/mode/toggle correctly prevents a load from *starting*, but a load
already *running* keeps running past it (until some unrelated timeout). **Root shape:** the
management + execution layers are *fused* — `SurplusController.update()` decides on/off
imperatively across ~7 passes with 9 scattered `activate/deactivate` calls, so every gate
must be threaded into BOTH the "don't turn on" spot AND a "stop if running" spot; the second
is easy to forget. **Where it lives:** `coordinator/surplus_controller.py::update()` — the
activation pass, the goal gates, the cheap-hours + Tier-2 force-expiry sections, the deficit
LIFO, the peak-shed pass. Recurred **4× in #620 alone** (daily-max cap; battery-overnight
toggle; overnight-picker off-Battery and off-Grid). **Closure (planned):** authoritative
`desired_state` — management computes ONE pure `LoadIntent(on, power, source, reason)` per
load, execution is ONE reconcile step, so a gate is just a *term* and OFF stops a running load
by construction (spec: `docs/superpowers/specs/2026-07-22-desired-state-surplus-loads-design.md`).
**Guard (now):** `tests/test_620_device_goal_model.py::TestGateStopsRunningLoad` — a parametrized
family test enumerating EVERY stop gate (cap / target-met / stop-sensor / overnight-off /
grid-off / reserve / peak) and asserting each deactivates a *running* load. Add a new gate →
add a row, or CI fails. Refs #559 #620.
**Built (not yet default):** the `desired_state` path — `compute_load_intent` (layer 1) +
`_desired_intents` (layer 2) + `reconcile_load` (layer 3, the single actuator) — is implemented
and is now the path **observer mode always runs** (HA-TEST). In it, OFF *is* the intent, so a
gate stops a running load by construction; markers derive from `intent.source` (closes #18).
Full closure = flip `_use_desired_state` for PROD actuation and delete the 7 imperative passes
(gated on the 2 LIFO parity xfails in `test_desired_state.py`).
**Watch:** until the flag flips for actuation, any new "reason a load should stop" must be added
to BOTH `compute`-side (block activation) AND a force-expiry/goal-gate section (stop running) in
the imperative `update()` — AND to `compute_load_intent`'s precedence — AND to the family
guard's parametrize list.

### 18. Forced-marker set in one pass, leaks because another pass didn't clear it — PARTIAL
**Symptom:** a transient control marker (`_offpeak_forced`, `_batt_overnight_forced`) set when
one pass activates a load stays `True` after the load stops, so later cycles mis-treat an
idle/finished load as still "forced" (skipped by the LIFO, shielded from expiry). **Root
shape:** a marker set in the pass that *activates* must be cleared in every pass that
*deactivates* — a manual bookkeeping obligation spread across passes. **Where it lives:**
`surplus_controller.py` — every `deactivate` site currently hand-clears the markers (goal
gate, force-expiry, peak-shed). **Closure (planned):** in the `desired_state` model the markers
become *derived views* of `LoadIntent.source` (`_batt_overnight_forced == source=='tier2_battery'`),
recomputed each cycle — never manually set/cleared, so they can't leak. Same spec as class 17.
**Built (not yet default):** `_apply_source_markers` / `_clear_source_markers` in the
`desired_state` path derive the markers from `intent.source` — live in observer mode, and behind
the flag for actuation. Full closure = the flag flip that retires the hand-clearing passes.
**Guard (now):** the family test (class 17) also asserts the markers are `False` after a
gate-driven stop; `test_desired_state.py::test_reconcile_markers_derive_from_source` pins the
derivation. Refs #620.

### 19. UI write path never reaches the runtime reader (unrouted option / dual storage) — GUARDED
**Symptom:** a card control writes somewhere (entry option, entity) that the running consumer
never reads — silently no-op until a reload/restart, or forever (dual storage aligned only by
coincidence of defaults). **Live catches (2026-07-24/25):** the config-card peak slider
(unrouted \`set_option\` key → reload-or-nothing, #636); the legionella target (Control card
wrote the entity, the coordinator read the config option — equal only because both sat at the
default). **Root shape:** writer and reader bind to different stores/names; name-based routing
(\`number.sem_<key>\`) misses mapped entities (#542's CONFIG_KEY_MAP). **Guard:**
\`tests/test_637_live_options.py\` — every card option must declare its routing class
(LM_LIVE / LIVE_CONFIG / STRUCTURAL_RELOAD / entity-backed), and every LIVE_CONFIG key must
prove a runtime read exists. **Sweep question:** for every UI control, WHERE does the write
land and WHO reads that exact store at runtime?

### 20. Shadowed decision branch (an always-true earlier branch starves a newer one) — PARTIAL
**Symptom:** a new decision branch is added, tested in isolation, and never executes in
production because an earlier branch in the same function is effectively always true on real
inputs. **Live catch (2026-07-24):** #630's peak-managed night rate — \`deadline_amps\` is
always >0 once a night window resolves, so the deadline branch clamped everything to Min and
\`top_up_amps\` was never consulted; the feature shipped inert and only reasoning over live
logs exposed it. **Fix pattern:** merge the branches' authorities explicitly
(\`max(deadline, top_up)\`) rather than ordering them. **Guard (partial):** precedence pins in
\`test_629_ev_orchestration.py\`. **Sweep question:** for every decision function with ordered
branches, can the LATER branches actually be reached under production-shaped inputs? (A
reachability/coverage check against scenario corpora catches this class.)

---

### 21. Per-site unit normalization with divergent match rules — GUARDED
**Symptom:** the "sensor state → watts (or kWh)" conversion is a copy-pasted inline block, and
each copy picked its own unit-match rule, so the SAME physical sensor is read at DIFFERENT
magnitudes by different subsystems in the same cycle — with no error anywhere, because every
copy is individually correct-looking. A cousin of class 10 (that one is a keyword gap for entity
*resolution*; this is a unit-string gap for value *conversion*). **Instances (#641, 2026-07-25):**
five live rules across eight sites — exact-case `== "kW"` (`ev_control._this_charger_power`,
which `per_charger_context` funnels the whole multi-charger loop through), lowercase `== "kw"`
with no strip (`sensor_reader._read_sensor`, `coordinator._charger_power_w`),
strip+lower+long-form synonyms (`forecast_reader`, added by #575 — a prior bug in this same
family), Wh+MWh (`energy_calculator._energy_state_kwh`, added by #551 — Fronius Gen24 lifetime
counters really do report Wh), and **no check at all** (`devices/base.observed_power_w` /
`get_current_consumption`, where a kW heat-pump sensor taught `calibrate_rated_power` a ~3 W
rated power and collapsed the activation threshold). **Fix pattern:** ONE
`power_state_to_watts()` / `energy_state_to_kwh()` pair in `coordinator/units.py`, adopting the
union of the strictest copies; every site routes through it, including the ones that had no
conversion. Unit *predicates* (`is_power_unit`/`is_energy_unit`) live there too, so a detection
site can't drift from a conversion site. **Guard:** AST lint in `tests/test_641_units.py` — any
`unit_of_measurement`-derived name compared against a power/energy literal outside `units.py`
fails CI, making a sixth copy unrepresentable. **Sweep question:** for any value read off a HA
state, is there exactly ONE place that decides its magnitude?

### 22. String-keyed store where the write site and a read site disagree — GUARDED
**Symptom:** a value is written into a dict under a key built from a category string, and read
back somewhere else with the category spelled out *again* at the call site. Nothing joins the
two. A disagreement raises nothing, logs nothing and leaves no missing entity — the reader just
gets the default (`0.0`, or `set()`) forever. Distinct from class 19 (that one is a *write path*
that never reaches the runtime reader; here both paths work perfectly, on different keys).
**Instances:** **#666** — EV energy accumulated under `ev_daily_sun` while four independent sites
(both yearly reads, the recorder year-seeding, the reconcile's monthly write) had each
independently guessed the obvious `ev`; yearly and lifetime EV were frozen at zero for the life
of the feature, self-healing for one cycle after every restart (the recorder re-seed) and then
freezing again, which is why nobody reported it. **#667** — `SENSOR_LABEL_MAPPING.get(key, set())`:
44 of 116 label keys (38%) named no entity, including *every* `sem_monthly` one, so filtering HA's
entity list by that label returned nothing while all six sensors existed and held data.
**Tell:** a category/name string that is a *literal* at more than one site. Also: any period or
sibling of a group sitting at exactly `0` while its siblings move — one `_accumulate` writes
daily, monthly, yearly and lifetime in the *same call*, so a lone zero is arithmetically
impossible without a key mismatch. **Fix pattern:** promote the string to ONE constant
(`EV_CATEGORY`), migrate stored keys in place (sum on collision — both halves are real data),
and prefer putting qualifiers (a day boundary, a scope) in the *key* rather than the *namespace*:
`ev_daily_sun` claimed "daily" while writing four periods. **Guards:**
`tests/test_666_ev_accumulator_keys.py` runs one real integration cycle and asserts
daily/monthly/yearly move together for every category *derived from the dataclass* (not a list to
keep in sync — that is this same class one level up); `tests/test_667_label_registry.py` is a
shrink-only ratchet over label keys with no entity. **Sweep question:** for every string-keyed
store, is the key built in exactly one place — and if a lookup misses, does anything at all say so?

---

## Meta-classes (the coherence audit hunts these too)

- **Duplicated mechanism** — the same debounce/retry/reconcile/swap built in 2+ places (e.g. the
  sign-audit debounce vs the trace streak; the CounterCorrelationAudit dedup). Unify into one.
- **Parallel systems that are one concept** — two things modeled separately that should be one
  (e.g. arbitrage folded INTO the scheduler; the canonical `EVBudget`; the ONE priority list).
  *Sub-shape — one of the two is invisible (#651):* SEM had two EV-surplus allocators. The visible
  one (`SurplusController.distribute_ev_budget`, a priority cascade with its own 60 s / 500 W
  hysteresis) had a caller, tests, scenario coverage, a `#284` issue history and three rounds of
  refactoring — and terminated in `pcc.budget_w`, which no consumer read. The live one is
  `decide.self_consumption_surplus_w`, subtracting `_solar_committed_w_per_cycle` accumulated from
  each charger's *actual* decision. Nobody was choosing between them; the loud one was simply not
  connected. **Tell:** a value with many producers and no reader. **Sweep:** for each allocator /
  budget / plan object, grep its output field for *reads*, not writes. Tests and dashboards writing
  it don't count.
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

---

## 2026-07-25 coherence sweep — confirmed instances (adversarially verified)

The full-repo sweep (34 agents, refute-first verification) confirmed 16 findings.
Fixed same-day: **#639** (class 3, taper double-feed), **#640** (class 14, legionella
restore no-op), **#644** (duplicated-mechanism, dual anti-cycle clocks). Filed open:

- **#645** — duplicated-mechanism, day-boundary variant: nine independent day-rollover
  checks, each re-deriving "is it a new day?" from its own stored date. **CLOSED — but
  the filed closure was wrong.** The audit's proposed fix ("compute the day key ONCE and
  pass it to every consumer") would have *broken* the system: SEM has **four genuinely
  distinct and intentional day boundaries** — calendar midnight (energy/flows, to match
  the HA Energy Dashboard), EV deadline-based (#279), sunrise for the EV bucket
  (`ev_daily_sun`), and sunrise-gated for the load day (#620). They are not accidental
  duplication. What the sweep *did* find, underneath the false premise, is one real bug:
  the EV virtual-SOC decay rode on `_tracker_date`, which `__init__` re-initialises to
  today on purpose ("so restarts don't re-apply daily decay") — a deliberate trade-off
  that conflated *never decay twice* with *never decay after a restart*, so a restart
  spanning midnight skipped the day's decay entirely and the night-charge planner could
  read a stale "still nearly full" virtual SOC. Fixed by persisting the date the decay
  **last ran**, separately from the hour-bucket tracker.
  **Lesson: repetition is not duplication.** Nine sites computing the same-looking thing
  can be nine correct answers to nine different questions. The tell that separates them
  is not the shape of the code — it's whether the *stored dates diverge on purpose*.
  A comment explaining a trade-off ("initialize to today so…") is the highest-value
  artifact in a sweep like this: it names the property that must survive the fix.
  Sibling assessed and rejected: `surplus_controller`'s `_offpeak_forced_date` /
  `_batt_overnight_forced_date` are per-device runtime flags that default False on
  restart, so no stale force survives — not an instance.
  **A second, cleaner class fell out of the sweep: *the OS clock is not the HA clock*.**
  Four production sites named a calendar day with `date.today()` / `datetime.now().date()`,
  which read the container's timezone — routinely UTC while `hass.config.time_zone` is the
  user's, so near midnight they name different days (energy-assistant daily trend key and
  its wall-clock "run appliances at HH:00" tips, the PV month-to-date divisor, the
  appliance completed/missed-today counters). Unlike the day-boundary question this one
  has a mechanical rule with no allowlist, so it is enforced absolutely.
  Guard: `tests/test_645_day_boundary_registry.py` — **rule 1** bans naming a day off the
  OS clock outright (duration arithmetic on `datetime.now()` stays allowed: both ends use
  the same clock, so it was never wrong); **rule 2** is a ratchet over the remaining
  `dt_util.now().date()` sites, each declared with which of the four boundaries it serves
  and whether its memo survives a restart *across* that boundary. The registry is the
  deliverable — you cannot dedupe boundaries that are deliberately different, but you can
  make them declared, and the declaration forces the question that made this expensive.
  Guard-design note: rule 1 ships with a test that the regex can actually fire (and does
  not fire on the legitimate duration uses) — the #660 no-vacuous-check discipline applied
  to a new guard at birth rather than years later.
- **#647** — class 1: the battery perception audit gates on the `__fleet__` lock that
  per-battery mode never sets → the ledger's battery guard is DEAD on multi-battery
  installs (and fleet-summed comparison is cancellation-blind).
- **#648** — class 3: `apply_daily_decay` + the fleet `ev_connected` gate reach only the
  primary taper detector; secondary chargers' virtual SOC never decays.
- **#649** — the #461-peak single-writer class, unswept to loads: LM shed/restore AND
  the surplus controller both own surplus-mode devices; LM's restore re-starts a load
  against surplus intent (then class-17: nobody stops it).
- **#650** — class 14: `critical`/`controllable` land in the LM dict only; every registry
  rebuild wholesale-replaces them with defaults (no override store, the pre-#122 shape).
- **#651** — parallel-systems: zombie `distribute_ev_budget` cascade runs every solar
  cycle, output (`pcc.budget_w`) has zero readers, docstring claims it's the single source.
- **#652** — parallel-systems: the battery scheduler's peak-limit split uses its own
  phantom EV night model; the real EV stack (tariff planner + night targets) never agrees.
  Structural closure = #638.
- **#653** — spec-vs-reality: `ApplianceScheduler.update_schedules` has zero callers; a
  scheduled appliance force-starts then allocates phantom rated power forever.
- **#654** — spec-vs-reality: ripple-control shedding is observe-only; the WARNING log
  claims shedding that never happens. **Closed by amputation**: the log, both docstrings,
  `get_devices_to_block`, and the `block_path` / `loads_blocked` telemetry are gone; the
  monitor now says only what it does, which is observe. Wiring is #664, where the open
  question is whether a load running on own PV is covered by the block — contract- and
  operator-dependent, not inferable. `HeatPumpController.block()`/`unblock()` were
  **kept** despite being orphans: they implement SG-Ready state 1, which `config_flow.py`
  advertises to the user as part of the "standard 4-state protocol", so deleting them
  would make an advertised promise permanently unfulfillable. They sit in the orphan
  baseline pointing at #664.
- **#655** — spec-vs-reality (docs): SETUP_GUIDE's SG-Ready relay table still documents
  the pre-#523 mapping the code explicitly calls a bug. **FIXED.** Worth keeping in the
  ledger as the sharpest example of a sub-class the other entries don't cover: *the docs
  are part of the control path when the user is the actuator.* Nothing in the code was
  wrong. The user reads the table, sees SEM's (correct) output disagree with it, and
  reaches for the one toggle that "fixes" the disagreement — `invert_sg_ready` — thereby
  hand-installing the exact regression #523 removed. No test of the code could have caught
  it, because the code was right. Guard: `tests/test_655_sg_ready_doc_table.py` parses the
  shipped Markdown table and diffs it against `SG_READY_RELAY_MAP`. Generalisable rule —
  **when a doc states a value the code also states, the doc needs a test.** Same shape as
  the #618 anchor guard.

Re-verified dormant (no new issue): the arbitrage FORCE_DISCHARGE fleet-split (class 6
open sibling) stays triple-fenced (migration v14 forces the toggle off, no UI path,
`_any_allow_arb` hardcode); the in-code re-enable checklist at `decide_battery.py:160-180`
MUST become code+test before any re-enable. The VPP export force_discharge is NOT an
instance (per-battery max is the intended semantics, reporter-confirmed).

**Structural guard — BUILT** (`tests/test_653_orphan_methods.py`, shipped with #653): a
public method in `coordinator/`/`devices/`/`features/` with no production call site fails
CI. It is a **ratchet**, not a clean-room rule — the orphans that existed when it was
written are listed in `_BASELINE` with a reason, and the assertion is that the set must
not GROW; a second test fails if a baseline entry gains a caller and is not removed, so
the list cannot rot into noise. Detection is deliberately generous (attribute access
*and* string literals across Python/JS/YAML, because SEM dispatches via
`getattr(obj, "method", None)` in the charger adapters), which means it under-reports
rather than blocking CI on reachable code.

It found a real orphan on its first run — `set_ev_daily_energy_sensor`, filed as #663 and
closed as a duplicate of #658, which the sweep had already found. That is the honest
statement of what this guard is worth: it independently rediscovered a verified finding,
and it could **not** see the part that makes #658 hard (the sunrise/midnight key mismatch
that makes naive wiring corrupt data). It tells you an edge is missing, not whether the
node at the far end is safe to connect.

It would have caught #651/#653/#654.

### Second pass — the 8 findings the session-limit interrupted (verified 2026-07-25)

The sweep was resumed (cached prefix, live tail) and confirmed 8 more. **#642 + #643**
were fixed same-day (class 3 + class 13: the legacy EV read path smoothed the fleet SUM
and never filled the per-charger map, so every charger read the whole fleet's draw; the
two read paths now share `_read_ev_fleet_power`, and coordinator-side consumers go through
the sanctioned `_charger_power_w` accessor). Filed open:

- **#656** — class 4, the LOAD-side sibling of the battery strand closed in #589:
  `deactivate_all()` has zero callers, so removing SEM leaves a boosted HP/HW/switch
  latched ON forever. The reconciler does NOT heal it — it classifies the leftover as
  `external_on`, disowns it, and refuses to fight it, so the strand survives reloads too.
  Note: the hook must go in `async_unload_entry` BEFORE `clear_devices()` — HA runs
  unload before remove, so an `async_remove_entry` hook would iterate nothing.
- **#657** — spec-vs-reality (the #590 mechanism, sensor-attribute variant, ×8):
  attributes read `coordinator.data` keys no code has ever written. The EV
  "why am I blocked" surface (`battery_too_low` / `battery_needs_priority` /
  `solar_sufficient`) is null on every install. **The suite masks it** — `conftest.py`
  injects those exact keys into the mocked data (the #610 harness-fidelity lesson again).
- **#658** — spec-vs-reality, sibling-asymmetry: `_reconcile_ev_energy` is dead on two
  axes while `_reconcile_solar_energy` is wired. ⚠️ It was parked DELIBERATELY and the
  method is buggy (accumulates on the sunrise day key, reconciles on the midnight key →
  would corrupt the overnight window; also fleet-reads one charger's counter). Wiring it
  as-is re-enables the corruption. Depends on #645 (day-key unification).
- **#659** — spec-vs-reality, unreachable feature branch: 1p/3p `check_phase_switch` is
  dead on two axes (no caller since `561e28a`, and `phase_switch_entity` has no config
  surface). Delete-or-wire, with 4 same-shape siblings listed (`set_anticipated_surplus`,
  `validate_dependencies`, `force_charge.should_stop`, `create_charge_adapter`).
  **CLOSED — deleted, all of them** (`validate_dependencies` went in #662). Docs never
  promised any of it; the only mentions of 3φ↔1φ are two design docs listing it as
  *future work*. Each deletion leaves a tombstone naming what replaced it, because the
  danger here isn't the dead code, it's the next contributor finding working-looking
  code and shipping a config key on top of it. Two lessons worth keeping:
  1. **"Complete implementation" is the tell, not the reassurance.** All four read as
     finished features — hysteresis, entity actuation, auto-detect order, docstrings
     describing behaviour ("will factor this in 2 min before the deadline") that no
     code anywhere implemented. Nothing about the *code* said dead; only the call
     graph did.
  2. **The sweep found a fifth.** `force_charge.get_status()` is in exactly the
     position `should_stop` was — abstract, implemented 3×, zero production callers,
     computing a `TARGET_REACHED` nobody reads (the live verdict is the scheduler's
     own SOC comparison). Deliberately *not* deleted: removing an adapter's read-back
     surface is an interface decision, not a cleanup. Moved from UNTRIAGED to
     **triaged-but-kept** in the allowlist, so it reads as a decision, not a gap.
  Guard: no new mechanism. The issue proposed an `# ENTRY-POINT:` annotation, but
  `tests/test_653_orphan_methods.py` is already that ratchet and is *stricter* — an
  annotation is an escape hatch a contributor can add in the same commit as the dead
  method, whereas the allowlist must be edited deliberately and shrinks on every sweep
  (three names removed here). A second mechanism would have been the #612 mistake:
  new code for a guarantee that already exists.
- **#660** — class 8 ×2: `check_metrics`/`check_costs`/`non_negative_fields` validate
  ranges their producers already clamped (`max(0, min(100, …))`), and `check_flows`
  validates the greedy allocator's output against the allocator's own inputs —
  conservation is a theorem there, not an observation. The documented 2026-06-01 PROD
  autarky bug (0 % vs 98 % self-consumption) passed with 0 violations. Closure: check
  CLAMP ENGAGEMENT (pre-clamp) and the per-charger↔fleet sum invariant `check_flows`
  never looks at. Guard: a **no-vacuous-health-check meta-test** — every check must be
  demonstrably fireable or CI fails.
- **#661** — class 8 whose closure is a real class-1 detector: the both-directions-active
  check runs on fields netted from ONE signed scalar, so it is unfireable — and it stays
  unfireable on the split-sensor installs it was written for (Growatt Pattern E, #553
  pairs, two-sensor batteries all net BEFORE `calculate_derived`). The crossed-sensor
  evidence is destroyed upstream of the check. Move it into `sensor_reader` on the raw
  sides, reusing the `CounterCorrelationAudit` 5-vote pattern.
- **#662** — class 8 inside an orphan: `validate_dependencies` walks only `dep_list[0]`,
  AND has zero production callers. **CLOSED — but not as filed.** The premise that
  `async_set_dependency` had no cycle guard was stale (one landed in beta.3); the audit
  read the orphan and inferred the live path from it. What the fix actually found:
  (1) the live guard walked only ONE of the two stores dependency edges persist in, so a
  loop spanning `_dependency_overrides` and `_service_registrations` was invisible;
  (2) `register_surplus_device` — the only MULTI-dependency write path — had no guard at
  all; (3) a stale loop in storage *poisons the guard*, falsely rejecting the innocent
  direction on re-registration. Closure was prevention at every write path plus a
  load-time sanitize of both stores; the orphan was deleted, not repaired.
  **Lesson: an orphan is not evidence about the live path.** Reading it as a spec for
  what production does gave a correct verdict on the dead code and a wrong one on
  everything around it — the same trap as #651, where a dead allocator's tests and
  refactoring history read as proof it mattered.

Cross-cutting lesson from this pass: **class 8 is under-counted in the ledger.** Five of
the eight are checks that cannot fail, and each one was previously read as evidence of
health. The meta-test in #660 ("every check must be demonstrably fireable") is the
structural close for the whole class — prefer it over fixing the instances one at a time.
