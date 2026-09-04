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
**Fourth instance (#676, 2026-07-26) — the budgeted variant:**
`test_no_orphaned_translations` failed only above ten orphans ("Allow some orphans (keys used by
other systems) but warn if there are many"). There were **exactly ten**, and nothing was using any
of them — the allowance had been sized to the debt, so a full load passed indefinitely. This is the
subtlest form in the class: the check *can* fire in principle, which is why it survives review, but
its threshold was set by measuring the current state rather than by stating a rule. Note that the
comment did the concealing work — it supplied a plausible reason ("keys used by other systems")
that nobody verified, and once written it read as a decision rather than a guess. **Closure:**
threshold to zero, and every genuine exception named individually with its reason
(`_DYNAMIC_TRANSLATION_KEYS`, two entries, each checked against the code — both turned out to be
live keys a static scan cannot see, so the naive delete-them-all fix would have broken real
entities), plus an assertion that the exception list stays small so it cannot regrow into the
tolerance that was just removed. **Sweep question (thresholds):** for every `> N`, `at least N%` or
"allow some" in a correctness check — where did N come from? If it came from running the check and
picking a number just above the result, it is not a threshold, it is a snapshot of the debt.
*Swept 2026-07-26 across every lint/meta test:* the only other count comparisons are **vacuity
floors** (`len(scan) > 30` / `>= 16` / `> 50_000`, "the scan broke") — the inverse shape, requiring
at least N rather than tolerating up to N, which is this class's own closure pattern. #676 was the
sole instance.
**Open:** any other self-referential check; audit for them in
`/coherence-audit`. **Sweep question:** for every check, can you name an input that makes it fire —
and can that input survive the transforms between where it is produced and where it is checked?
Refs #589, #651, #661, #676.

### 9. Engine-specific SVG/SMIL form (renders on Blink/Gecko, silent on WebKit) — GUARDED
**Symptom:** a dashboard-card visual works on desktop Chrome/Firefox and Android but is dead on
*every* iOS browser (Safari, Chrome, HA Companion app — all WebKit) with no error. **Root shape:**
the card emits an SVG/SMIL construct that WebKit resolves more strictly than Blink/Gecko — the flow
dots used `<animateMotion><mpath href="#id"/></animateMotion>`, but WebKit only matches the
XLink-namespaced `xlink:href` on `<mpath>`, so the plain `href` never bound and the dot had no path
(#591). Lenient engines accept the plain `href`, so it passes every desktop/Android check — the gap
is invisible until an iOS user reports it. **Where it lives:** all animated SVG in the dashboard
cards — `dashboard/card/src/cards/*.js` (sem-flow-card, sem-system-diagram-card), built into
`dist/sem-cards.js`. **Closure:** drop the
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
**Missing-wiring sibling (#744, @Azlinon, 2026-08-11) — the derivation existed but was never called
for LOADS.** The keyword gap above is one facet; the sharper one is a source where the whole
derivation is *absent*. The Energy Dashboard's individual-device UI collects only the kWh energy
sensor, so a load's `stat_rate`/`stat_power` is virtually always empty → `UnifiedDevice.power_sensor`
is `None` → the Load-Management priority payload (`get_devices_for_sensor`) reads 0 W, so a power-only
load with no discoverable on/off entity (a Shelly PM mini at 400 W, a furnace blower at 250 W) renders
"Off" and shows the 1 kW rated placeholder. solar/grid/battery recovered this in
`_derive_missing_power_sensors` and the SurplusController's device factory did in #600
(`surplus_device_from_spec`), but the registry/DISPLAY path that feeds the payload, the surplus sync
AND the load-manager sync never derived. **Closure:** a load-tuned `_find_load_power_sensor(hass,
energy_sensor)` (same device-scoped `device_class=power` scan) called in BOTH ED consumers
(`device_registry.async_refresh_devices`, `load_device_discovery.discover_from_energy_dashboard`)
when the ED carries no power link. Two design constraints, each learned from the adversarial review:
(a) it is called **AFTER** control discovery and does **no brand matching**, because the derived
sensor must not reach `_find_control_by_integration` (whose `power_lower` brand match would turn the
load `is_controllable` → shed-eligible — a *display* fix must never widen *control*); (b) it prefers
a candidate whose object_id shares the energy sensor's **stem** (`channel_a_energy` → `channel_a_power`,
never the sibling channel) so a multi-channel Shelly 2PM doesn't cross-wire its two loads' watts —
the plain shortest-name scan the #250 sources use has no such affinity (fine there — single-instance
sources; loads are where multi-channel devices live). **Guard:** `tests/test_744_load_power_derivation.py`
(kWh-only load derives its companion; explicit `stat_rate` still wins; stem affinity picks the right
channel; energy/reactive sensors excluded; a power-only 400 W load reads ON end-to-end in the priority
payload; and a brand-named *derived* sensor does NOT make a controlless load controllable). **Sweep
question:** for every power/energy figure a surface derives from an Energy-Dashboard entity, is the
companion power sensor *derived* when the ED has no `stat_rate`, or assumed present — and does that
derivation leak into a *control* decision? Refs #250 #274 #597 #600 #744.

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

**Fourth instance — #748 (@jappish84), and the variant worth naming: the fold was at the DISPLAY
layer, so it never de-persisted.** One Garo charger showed **three** rows: the authoritative
`load_device_ev_charger`, an ED `individual_device` ("Billaddare") whose control entity is the
charger's start/stop switch, and a `smart_switch` `load_device_garo_laddbox` that appeared the moment
the user wired up start/stop (as #700's own reply advised). Three independent faults, each in this
class's spirit but each a distinct mechanism: **(1)** `_configured_charger_entities()` knew only the
charger's *power* entity — a charger is also its `start_stop_entity`/`current_entity`/`status_entity`,
so #700's identity fold couldn't see "Billaddare" (matched by its control entity, not its power
sensor); **(2)** the `smart_switch` discovery glob is `switch.*` with **no charger exclusion**, so a
switch already claimed as a charger's stop control was rediscovered as a smart plug — which is *why
wiring up start/stop creates a row*; **(3) the decisive one:** #700's fold lived inside
`get_devices_for_sensor` (the card payload) and never removed the row from `LoadManagement._devices`,
while `_sync_to_load_manager` **spares every `load_device_*` key** (#436) — so a persisted bogus row is
immortal (survives restart, registry sync, and reappears in diagnostics + the load-management loop,
`is_controllable: true`, acting on the charger's stop switch behind the EV controller's back). **The
tell for this variant:** a suppression that reads correct because *the card* is correct, while the
same duplicate is still live one layer down. A display fold hides a row; it does not remove it. Ask of
any dedup: does it mutate the *authoritative store* (`LoadManagement._devices` / the persisted config),
or only the payload a card renders? **Closure:** widen the identity set to EVERY entity a charger
declares (plumbed through the charger rows in `_charger_priority_rows`, #748); add a **data-layer
reconcile** (`_prune_charger_duplicate_lm_rows`) that drops any `LoadManagement` row sharing a
charger's entity — except the authoritative `load_device_<charger_id>` rows — and **de-persists** it
via `_save_device_configuration`, so existing installs lose the duplicate on upgrade instead of
carrying it forever; and exclude charger-claimed entities at the point of discovery
(`discover_controllable_devices(excluded_entities=…)`, fed from `register_ev_charger`'s now-stored stop
switch + status sensor). **Guard:** `tests/test_748_charger_duplicate_depersist.py` asserts at the
`LoadManagement._devices` (data) level — the smart-switch row and the ED-control-entity row are both
gone while the authoritative charger row survives — *not* that the card happens not to render them.
Refs #628 #700 #748.

**Fifth instance — the same fix, one roster short. "The data layer" was not one place.** #748 moved
the fold from the display to the data layer and stopped there, because `LoadManagement._devices`
*read* like the data layer. The registry syncs to **two** downstream systems, and the second —
`SurplusController._devices`, populated by `_sync_to_surplus_controller` — had no charger-identity
fold at all. So the duplicate stayed registered as an independent surplus device: the daytime surplus
loop could still reach the charger's own stop switch behind the EV controller — the very hazard the
fix announced closed — and the card showed nothing, because the display fold hid the row it could not
remove. That roster is also what the #638 energy planner packs (`get_devices_sorted()`), so a
duplicate carrying a minimum-runtime goal could enter the night ledger twice. **The tell:** a fix
phrased as "display layer vs data layer" — a two-term framing for a fan-out. Ask instead: *how many
rosters are built from this source, and does the rule run in each?* Count the writers, not the layers.
**Second tell — a fold that runs only at sync time is blind at startup:** the registry syncs at
`async_initialize`, but the charger roster arrives later on the coordinator's own cycle, so on the
first pass `_configured_charger_entities()` is empty and the fold matches nothing. **Closure:** ONE
predicate (`_is_charger_duplicate`) called by every roster builder — card payload and
`_sync_to_surplus_controller` — plus `set_ev_chargers` re-checking the surplus roster when the charger
identity set *changes*, which is the moment SEM first learns the fact. **Guard:**
`tests/test_748_surplus_seam.py` asserts on `SurplusController._devices` (the raw registration dict,
not the filtered `get_devices_sorted()` view — a read-site fold would fail it) and on the planner's
roster, and pins the restart window and the every-cycle no-op. Refs #628 #700 #748 #638.

**Sixth instance — #779 (@onkelfu, 2.0.0-beta.2): the NON-charger twin, one roster short of #748.**
A device the user set to **Mode=Off** was still switched off. The dishwasher appeared twice —
`energy_dashboard_spuelmaschine` (the registry's authoritative ED row, `is_controllable`) and
`load_device_spuelmaschine` (a `smart_switch` ghost). Same immortality mechanism as #748 (the #436
spare keeps EVERY `load_device_*` key), but #748's data-layer fold matched only a **charger's**
entities — a plain smart plug shares none, so it survived. With the registry active, LoadManagement's
own `discover_controllable_devices` is guarded off, so any `load_device_<slug>` **smart-switch** row
is a pre-2.0 persisted ghost; when the same physical device is also in the Energy Dashboard the
registry re-adds it as `energy_dashboard_<slug>` — the row that carries the user's Mode
(`control_mode`). The ghost has **no `control_mode`** (so Mode=Off on the ED twin never reaches it)
and stays `is_controllable`/sheddable → the peak-shed loop actuates the appliance behind the user's
back (dishwasher, heat pump, network gear — safety-critical). **The tell:** the user's setting lives
on the id they *see* (the ED row); a second id for the SAME entity is invisible to them and
unbound. **Closure:** `_prune_ed_duplicate_lm_rows` — fold, at the data layer, any `load_device_*`
row (except `ev_charger` rows and service registrations) whose switch/control entity IS the
actuation surface a registry-owned ED device controls (dedup on the shared CONTROL entity, not the
id — class 12's own pattern). Deliberately NOT on power/energy: a load's power sensor can be derived
(#744) or shared across a multi-channel device's two loads, so matching it could fold a legitimate
neighbour; the shared control surface is the one signal that cannot false-positive. Remove it from
`_devices_shed` too, and de-persist via `_sync_to_load_manager`'s existing save. A `load_device_*`
row with no matching ED twin is the device's ONLY representation and is left untouched — which is
exactly why #748's `test_...dishwasher` (no ED device) still survives.
**Guard:** `tests/test_779_ed_duplicate_load_row.py` — the shared-entity ghost is dropped while an
unrelated no-ED-twin plug survives; and, via the REAL `LoadManagementCoordinator`, the ghost is a
live shed candidate BEFORE the fold and gone after (pins the behaviour, not the prune). **Sweep
question:** for every store that persists a device row by an id, can the SAME physical entity acquire
a SECOND id from a different discovery source — and does the user's per-device setting bind to the
entity or to one id? Refs #436 #700 #748 #779.

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
**Instance 5 — a *second* way to be un-stoppable: the gate was threaded into both spots, but
the load didn't look like SEM's.** Both release paths (`compute_load_intent` clause 1 and the
imperative force-expiry pass) are gated on `_sem_owned`, the flag that separates "SEM turned
this on" from "the user turned this on". Ownership was recorded **at the call site**, and only
2 of the 5 activation passes did it (main surplus, `reconcile_load`); the Tier-2 overnight
battery, cheap-hours grid and deadline passes did not, and no `activate()` implementation sets
it either. So Mode → Off computed the right decision and then declined to act on it. Confirmed
on real hardware (HA-PROD 2026-07-26): a towel heater started by the Tier-2 pass was still
drawing 648 W five minutes after Mode → Off, `sem_owned == false` throughout, and would have
run until the user's own 2-hour safety automation. **Fixed** by moving ownership off the call
sites into a choke point — `_activate_owned` / `_deactivate_owned` in `surplus_controller.py`,
all 12 actuation sites converted. **Guard:** `tests/test_load_ownership_choke_point.py` — an
AST guard fails CI on any raw `<device>.activate(...)`/`.deactivate()` outside the two helpers
(same shape as `# FLEET-READ` from #589), plus a reflection test asserting no `activate()`
implementation records ownership, so it can't drift back into the device layer and double-claim.
**Lesson:** "is the gate wired into both spots?" is necessary but not sufficient — also ask
"can the stop path *see* this load as ours?".
**Watch:** until the flag flips for actuation, any new "reason a load should stop" must be added
to BOTH `compute`-side (block activation) AND a force-expiry/goal-gate section (stop running) in
the imperative `update()` — AND to `compute_load_intent`'s precedence — AND to the family
guard's parametrize list. Any new *activation* path must go through `_activate_owned`.
**Instance 6 — the class crosses into chargers: a loop-level `continue` IS a gate.** The #193
night gate `continue`d `off`/`solar_only` chargers out of the per-charger loop in the two night
states — before the adapter, the reconciler, `decide()` or `actuate()` ever ran for that charger.
"Skip" silently meant "no supervision": a KEBA auto-starting masterless at night (#740, live on
PROD 08.08.2026) drew unpoliced until a day state returned, because the one component whose job
is stopping rogue sessions was gated out along with the night budget. **Fixed** (develop,
1.7.6-beta.9): `_police_opted_out_charger` runs a minimal reconcile pass (OFF for `off`, IDLE for
`solar_only` — the #552 idle-settled row makes a rogue draw an immediate DISABLE) before the
`continue`. **Guard:** `tests/test_740_night_gate_police.py`, incl. a source pin that the gate
polices before it continues. **Lesson:** audit every `continue`/early-`return` that skips a
device's iteration — each one is a gate, and the question is the class's own: *who stops the
device this branch stops watching?*

**Instance 7 — the ownership gate wired into two release paths, missing on the third (#847,
Hoyte, fresh install).** The inverse hazard to a strand: a stop path that stops a load it does
*not* own. Mode → Off releases a running load in THREE places — `compute_load_intent` (clause 1),
the imperative `update()` peak/goal pass, and the *immediate* one-shot in
`device_registry.update_device_control_mode` fired at the moment the user changes the mode. The
two loop paths both gate on `_sem_owned` ("a user-turned-on load stays untouched", the instance-5
+ #779 lesson); the immediate handler was the straggler — it fired for *any* observed-on device,
so setting a peak-management device to Mode=Off switched off loads the USER had running. The
default mode is `peak_only`, which SEM never drives *on*, so `_sem_owned` is False and there is
nothing to strand — the release was pure collateral. **Fixed** by adding the same `_sem_owned`
gate to the immediate handler. **The tell:** a per-user action (mode change) with an actuation
side-effect that exists in more than one code path — count the actuation sites, and confirm the
ownership predicate guards *every* one, not just the loop copies. A genuinely SEM-driven surplus
load is re-adopted (`_adopt_ownership`, gated on SURPLUS) post-restart before any mode change, so
the strand case (instance-5 lineage) stays covered while the user's own loads are left as-is.
**Guard:** `tests/test_559_phase0.py::test_mode_off_does_not_touch_user_driven_load` (user-on,
not owned → not actuated) + `::test_mode_off_transition_releases_running_load` (SEM-owned → still
released). Refs #559 #779 #847.

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
(\`number.sem_<key>\`) misses mapped entities (#542's CONFIG_KEY_MAP). **Third instance (#883,
2026-08-31) — the mirror clobbers back:** the EV-card Min/Max sliders persist PER-CHARGER
(\`ev_chargers[0][key]\` via \`persist_per_charger_option\`) and never touch the flat
\`ev_target_soc\`/\`ev_target_soc_max\`/\`daily_ev_target_max\`/… mirror, so the two diverge the
moment a slider moves. The primary \`async_step_ev_charger\` options step then sourced its form
defaults from the stale flat mirror (\`current_config.setdefault(k, v)\` let flat WIN over
\`ev_chargers[0]\`) AND wrote those defaults back into \`ev_chargers[0]\` on submit — so merely
opening options and browsing past the EV page reset charger 0's Min charge target to the flat
100% default. Charger 2+ were spared because \`async_step_ev_charger_edit\` reads the charger
dict directly. **Closure:** the per-charger dict OVERRIDES the flat mirror when building the
primary form (\`current_config[k] = v\`), so the one form that both reads and writes
\`ev_chargers[0]\` round-trips the authoritative store. Fixed every tunable on that page at
once (target_soc, target_soc_max, daily_ev_target_max, ev_kwh_per_100km, battery capacity,
efficiency). **Root shape (this variant):** a dual store where the SAME step both reads and
writes one copy — sourcing the read from the *other* copy makes the write self-corrupting.
**Root shape (original):** writer and reader bind to different stores/names; name-based routing
(\`number.sem_<key>\`) misses mapped entities (#542's CONFIG_KEY_MAP). **Guard:**
\`tests/test_637_live_options.py\` — every card option must declare its routing class
(LM_LIVE / LIVE_CONFIG / STRUCTURAL_RELOAD / entity-backed), and every LIVE_CONFIG key must
prove a runtime read exists; \`tests/test_883_charger_target_preserved.py\` pins the
options-form round-trip (per-charger store wins, charger 2 untouched). **Sweep question:** for
every UI control, WHERE does the write land and WHO reads that exact store at runtime? — and
for any step that BOTH reads and writes a dual-stored value, does its read come from the copy
it writes? **Open guard (for Guido):** an AST lint that a flow step writing \`ev_chargers[i]\`
on submit must source its form defaults from that same charger dict, not the flat config.
**Open sibling (for Guido, found in #883 review):** \`EVTaperDetector\` is built with the FLAT
config (\`coordinator.py\` ~10673) and reads \`ev_target_soc\`/\`ev_battery_capacity_kwh\`/
\`ev_charger_efficiency\` flat for ALL chargers — while the number entities + coordinator SOC
paths read per-charger-first. #883 keeps the two copies in sync on every options save (so this
is mitigated, not live), but a per-charger taper detector should read \`ev_chargers[i]\`.

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

### 23. Reference written to a host registry that never validates it — GUARDED
**Symptom:** we write an *identifier* into a Home Assistant registry and the API stores it
verbatim — it neither validates the reference nor creates the thing it points at. Every
inspection from our side passes, because we are reading back our own write. The direction that
was actually the point — the host resolving the reference — is dead, and reports nothing.
**Instance:** **#670** — `entity_registry.async_update_entity(labels={...})` takes label *IDs*.
SEM never called `label_registry` at all, so its 19 labels were strings on entity rows and
nothing else. `labels('sensor.sem_monthly_solar_yield_energy')` returned all four labels ✅ while
`label_entities('sem_monthly')` returned `0` and `label_id('sem_monthly')` returned `None` — and
the reverse lookup is what the entity-list filter, label-scoped automations and auto-entities all
use. It compounded with class 22 (#667): with the registry side missing, a *correct* label and a
typo'd one behaved identically, which is how 38% drift survived for years.
**Tell:** any `async_update_*(... = <id or list of ids>)` against a host registry where we never
call that registry's own `async_create` / `async_get`. Also: a feature whose verification only
ever reads back the field we wrote. **Fix pattern:** create-if-missing against the owning
registry *before* the reference is written, matched on **id** (never name), and never delete,
rename or recolour — the user owns those objects. **Guards:**
`tests/test_670_label_registration.py` asserts through `template.label_entities` — the real
consumer path — rather than through the entity registry's own index, plus idempotency across
restarts and non-clobbering of user renames. **Sweep question:** for every id we hand to HA
(labels, areas, floors, categories, devices), who *creates* it — and has anyone ever tested the
lookup in the direction the user actually uses?

### 24. Hand-maintained key whitelist mirroring a structure that grows — GUARDED
**Symptom:** a serialization boundary carries values through a *literal list of key names*
written by hand. The structure on either side of it gains a field; the list does not. The new
field is written on the way out, silently dropped in the middle, and read back on the way in
with `.get(key, default)` — so it does not raise, does not warn, and does not go missing. It
resets to the default on every restart, forever. Distinct from class 22 (there the two sides
disagree on *one* key's spelling; here they agree on spelling and one side simply doesn't list
the key at all). **Instance:** **#668** — `SEMStorage.export_energy_calculator_state()` and
`import_energy_calculator_state()` were two *separate* hand-written lists across the calculator's
save/restore boundary. `get_state()` emits 20 keys; export whitelisted 11. Nine were dropped: the
seven `accumulated_*` lifetime running totals, `rate_history`, and `yearly_cost_seeded`. Effects:
`pre_sem_*` absorbed the entire lifetime, so **Lifetime Total Savings degraded from a
rate-weighted real figure to a 7-day-average estimate** that moved on every restart; and the reset
`yearly_cost_seeded` re-ran seeding each start, **overwriting** exact live yearly accumulators
with an estimate. The pair had already drifted twice — #351 M1 added the cost accumulators to
both, and nine more were still missing after it. **Tell:** two functions on opposite sides of a
persist boundary that each contain a literal tuple/list of the *same* field names; or any
`for key in ("a", "b", ...)` copy loop. Ask what happens when someone adds field `c`. **Fix
pattern:** ONE module-level constant both directions iterate (`CALCULATOR_STATE_KEYS`), with the
deliberate exclusions named and justified *in* it (`last_update` is the save stamp, not the
integration stamp). Coerce on restore too — a value that used to be reset by the drop now
survives every restart once it actually persists. **Guards:**
`tests/test_658_ev_counter_reconcile.py::TestStorageRoundTrip658` round-trips real values rather
than comparing key *sets*, and `test_the_two_directions_cannot_drift_apart` uses `inspect
.getsource` to assert both functions reference the shared constant. **Sweep question:** for every
persist boundary, is the field list derived from the structure — or retyped beside it?

**Second instance — #673, and the variant that cannot be de-duplicated.** `services.yaml` is a
hand-maintained mirror of what `__init__.py` registers, and it had drifted to **14 of 18**:
`diagnose`, `remove_charger`, `get_config`, `set_option` were registered and undeclared. Same
silent shape — an undeclared service is still fully callable, so nothing raises. What it loses is
its UI: no description, no field pickers, no validation in Developer Tools → Actions. Worst on
`diagnose`, which `docs/SEM_TRACE.md` explicitly tells users to call with `section: trace` — they
met an action with no `section` dropdown and no hint that `trace` was one of twelve valid values.

The important difference from #668: **the #668 fix pattern does not apply here.** You cannot
derive `services.yaml` from the code, because it holds descriptions and selectors only a human can
write. When one list genuinely cannot be generated from the other, the closure is not "collapse
them into one source of truth" — it is **assert the two agree, and name every deliberate
divergence.** `tests/test_673_services_declared.py` checks both directions (a declared-but-
unregistered service is the rarer and more user-hostile half: HA offers it in the picker and it
fails on call) and additionally pins that the `section` dropdown offers every section the code
actually handles — a field with the wrong option list leaves the docs as the only place the valid
values exist, which is the bug not quite fixed.

**Sweep question, widened:** for every hand-written list mirroring a code structure — persist
whitelists, `services.yaml`, `strings.json`, `manifest.json` dependencies, platform lists — is it
derived, or merely *asserted equal*? If it is neither, it is already drifting.

**Third instance — #674, found by running that sweep question instead of writing it down and
moving on.** `strings.json` ↔ `translations/*.json` had drifted **50 keys one way and 35 the
other**, identically in all 16 languages. The trap is specific and worth naming: `strings.json` is
where a developer naturally edits — it is HA's documented source file and the one hassfest
validates — but **HA never reads it at runtime for a custom component.**
`helpers/translation.py` loads `integration.file_path / "translations" / f"{language}.json"` and
nothing else. HA *core* has a build step that copies one into the other; a custom component does
not, so the "source" file is the one with no effect. Cost: the whole Heat Pump options step
rendered with no title, no description and eight raw voluptuous keys as labels (the frontend falls
back to the key name); the `soc_cap_unenforceable` repair issue had no title or description at all.

Then the guard for it surfaced a second layer — **the two files agreeing with each other says
nothing about either agreeing with the code**: two `async_abort` reasons had no message anywhere,
so a new user installing SEM before configuring the Energy Dashboard read the literal string
`energy_dashboard_not_configured` as their entire failure message; twelve `config.error` keys were
never assigned by any code path (leftovers from validation the #397 slim-down replaced); and two
live errors named placeholders (`{entity_id}`, `{service}`) that no `description_placeholders` ever
supplies, so users read the raw token. **Fix pattern:** where the mirror *is* derivable, demand
exact parity rather than one-way containment — plus check placeholders in both directions, since an
*invented* placeholder is a `KeyError` at render time while a *dropped* one merely loses
information. **Guard:** `tests/test_674_translation_parity.py`.

**Meta-lesson:** three instances in, the class's real tell is not "a list" — it is **a file whose
only consumer is a human**. `services.yaml`, `strings.json` and the persist whitelist all fail the
same way because nothing *executes* them against their counterpart. Ask of any such file: if I
delete a line, what breaks, and when? If the answer is "nothing, until a user opens the right
screen in the right language", it needs a guard, not a review.

**Fourth instance — #677, the same drift read from the other end.** #674 was *a key with no entity*.
#677 is *an entity with no key*, and it is worth keeping both in the class because the search that
finds one will not find the other. When nine EV settings became per-charger in #255, their entity
description key started carrying the charger id — `charger_keba_target_soc` — and
`SEMPerChargerNumber` kept using `description.key` as the translation key. No `strings.json` can
declare a key containing a runtime id, so HA looked it up, missed, and fell through to
`entity_description.name`, a hardcoded English f-string. Nine sliders read English on every install
in every language, for over a year. The two per-charger *selects* had the complementary half of the
same split: they keyed on the bare config key, so they translated fine — but the name carried no
charger, so a two-charger install rendered two identically-labelled dropdowns. **One split, two
opposite losses: numbers kept the discriminator and lost the translation, selects kept the
translation and lost the discriminator.** Fix pattern for both: bare config key as the translation
key, discriminator as a `{charger}` placeholder — which HA validates, since
`Entity._substitute_name_placeholders` *raises* outside the stable channel when the name names a
placeholder the entity does not supply.

**The part worth stealing:** the guard does not list the eleven keys. It **derives** them from the
construction call sites in `number.py`/`select.py` — and that same derivation then *replaced* the
two-entry `_DYNAMIC_TRANSLATION_KEYS` exemption set #676 had added to `test_translations.py` days
earlier. That set was correct, small, and documented, and it was already the first two rows of a
hand-maintained mirror of a growing structure — this very class, in its egg. #677 would have taken
it to eleven. **Tell:** an exemption list *inside a guard for this class* is the class recurring one
level up. If you find yourself adding a third entry to one, ask whether the thing you keep listing
can be read out of the source instead. **Guard:** `tests/test_677_per_charger_names.py`
(`per_charger_translation_keys()` is the shared derivation).

**Fifth instance — #737, the mirror read from the schema end.** #674/#677 compared the two
*string* files (`strings.json` ↔ `translations/`) to each other; nothing compared either against the
**options-flow schemas**, which are the actual structure the labels mirror. So two files could agree
perfectly and still both omit a field — and they did: six steps declared 37 `vol.Optional`/`Required`
keys with no `data` label (the whole `deye` step block was absent from `strings.json`), rendering the
raw `snake_case` key. The audit that opened #737 hand-counted the fields and got 37 — but the `deye`
step builds 18 more `deye_program_N_{time,soc,charge}` keys in a comprehension, so the true count was
55. **This is the class's signature failure mode: a count.** The manual list undercounts exactly the
loop-built fields a human eye skips, which is why the closure is a *derivation* — the guard walks
each `async_step_*` schema, enumerates literal keys **and** resolves comprehension-built f-string
keys over their literal loop ranges (`range(1,7)` × `("time","soc","charge")`), and asserts each is
declared. Genuinely runtime-named fields (`pv_naming`'s `pv_name_{slot}`, keyed on discovered PV
strings) are the one thing a static file cannot declare; they are named in a one-entry
`_RUNTIME_NAMED_STEPS` set with a reason, and the guard fails if that set grows silently (the #677
tell — an exemption list is the class one level up, so this one is derived-from-unresolvable, not
"not done yet"). **Guard:** `tests/test_737_options_flow_label_coverage.py` (schema ⊆ `strings.json`);
it composes with `test_674` (`strings.json` == translations) to cover every language HA loads. Refs #737.

### 25. Mutual delegation — two layers each defer the action to the other — GUARDED
**Symptom:** the intent is right, the command is issued, the logs say it was issued, and the
thing never happens. Nothing raises, because from each layer's own point of view it behaved
correctly: it declined to act *because the other layer handles it*.
**Root shape:** two code paths that are each other's fallback. Layer A skips its own attempt
and documents that B is responsible; layer B, finding nothing of its own to do, falls back to
A. Neither is wrong in isolation — the defect only exists in the *composition*, which is why
reviewing either file alone reads as correct. The tell is a pair of comments that point at
each other; both were present here, in different files, and both were accurate.
**Live catch (#627, reported by @onkelfu):** `_set_current(0)` skips the write when the control
number's `min` is above 0 A ("the actual stop is the adapter's job", #487), and
`stop_session()` — finding no stop service, charge-mode select, start/stop entity or
`<domain>.disable` — warns that it is "relying on `_set_current(0)` alone". On a charger
configured with only a current `number.*` entity, nothing stopped the car at all: 130
consecutive commanded stops, 4.1 kW drawn against them, 3.5 kW of it out of the house
batteries, at night, with the charger set to *off*.
**Why the observability missed it:** #548 had already added `_stop_commanded_while_drawing`,
which counted the failures correctly and warned at 3, 12 and 60 — then went quiet by design,
while the condition ran for hours. A counter of a *symptom* answers "is it working?" with
"I have seen it fail N times", which decays into background noise. The capability question
("*can* this ever work?") is answerable up front and doesn't decay.
**Closure:** don't assert the capability — compute it, from the same fields the action
dispatches on, and let the consumer surface it. `CurrentControlDevice.can_stop_charging()`
mirrors `stop_session()`'s dispatch chain and ends at `_bound_to_entity_range(entity, 0)` —
the exact predicate that made the write unreachable — so the two cannot drift without the
guard noticing. The reconciler carries it as `ObservedState.stop_controllable` and files a
repair naming the charger, the power still flowing and the missing entity.
**The trap that was avoided, and why it's part of the class:** the obvious home for the signal
was the existing `enable_controllable`. It gates the CHARGE rows — reusing it would have
short-circuited every number-entity-only charger to REPORT and cost it surplus charging
entirely, trading a reporting gap for a functional loss. When a new capability signal *looks*
like an existing one, check what the existing one gates before reusing it.
**Sweep (done):** the other capability-shaped claims on this path were checked — `ensure_enabled`
/ `command_enable` (no mutual-fallback pair: a missing switch is a no-op with no second layer
claiming it), and the phase-switch path (deleted dead in #659).
**Guard:** `tests/test_627_stop_unenforceable.py` — pins the probe per mechanism, its
propagation through `observe()`, the reconciler row, the repair raise/clear, **and** that the
CHARGE rows stay untouched when `stop_controllable=False`. Refs #487 #548 #627.
**Watch:** any new "SEM couldn't actually do X" should be a *computed capability on the device*,
not a counter of failed attempts in the caller.

### 26. Config key every test injects and production never writes — GUARDED
**Symptom:** none, for years. The code reads `cfg.get("some_key", <literal>)`, every test
constructs a config dict containing `some_key`, and the tests pass. On a real install the key
is absent from every entry, so the literal is what actually runs — a value nobody chose, in a
branch everybody believes is covered.
**Root shape:** a default argument turns "missing" into "plausible". A missing key that raised
would be found in the first minute; a missing key that falls back reads as configuration. The
test fixture is written from the *reader's* expectations rather than from a real stored entry,
so the fixture documents the schema the reader wishes existed. Nothing in CI compares that to
the schema the config flow actually writes.
**Live catch (#678, found by #665's new coverage):** `decide()` reads `ev_max_current`,
`ev_min_current`, `ev_phases` and `ev_voltage` off the per-charger entry. There is no
config-flow field for max-current or voltage at all, and `_SEED_KEYS` covers only min-current
and phases, only for entries migrated from schema v3 — so on a normally-installed entry all
four read `None` (verified live against real `.storage`, top-level config included) and decide
used 32 A / 6 A / 3 / 230 V. Hardware was never at risk: the adapters clamp every command to
the charger's real ceiling, which is *why* it survived — the only visible effect was in the
multi-charger priority cascade, where a 16 A charger commanded at 32 claims 22 kW of solar it
cannot draw and that phantom claim is subtracted from what the next charger may see.
**Why the type system didn't help:** the key is read from a `Mapping[str, Any]`, so there is no
declaration anywhere that says "these four keys exist". The dict is the schema, and the schema
is whatever the last writer happened to put in it.
**Closure:** fill the keys at the one place that composes the view (`build_charger_view`), from
the fleet config, and then clamp to the value the *hardware* enforces — `adapter.max_current_a`,
the same number the adapter clamps every command to. Config may ask for less than the hardware
allows, never more, so the computation ends at the ceiling the action is dispatched against.
Same principle as class 25's `can_stop_charging`.
**Sweep question:** for each `cfg.get("k", <literal>)` on a per-unit dict — *who writes `k` into
that dict on a fresh install?* If the answer is "the tests", the literal is the live behaviour.
**Guard:** `tests/test_665_allocator_coverage.py::TestHardwareMaxReachesDecide` — pins the
absent-key case (the live shape) explicitly, plus fleet fallback, per-charger override,
config-below-hardware, config-above-hardware, and no-information-at-all. Refs #678 #665 #536.
**Watch:** a fixture that is hand-built rather than captured from a real entry. When adding a
per-unit config read, add the absent-key test *first* — it is the case production runs.

### 27. Seeded default makes the safe state unreachable (opt-out that is opt-in) — GUARDED
**Symptom:** a documented default never happens. The code has a correct gate — "no floor set →
never do the risky thing" — and a green contract test proving it. On every real install the
risky thing happens anyway, because the config flow *seeds* the key the gate reads, so the
"unset" branch the safety depends on is a state no install is ever in.
**Root shape:** the exact inverse of class 26. There, production never writes the key and the
literal default is the live behaviour. Here, production *always* writes it, so the value can no
longer distinguish **"the user asked for this"** from **"the installer filled the box in"**. A
value used as a *signal of intent* must have a state that means "no intent expressed", and a
seeded default destroys that state. The test passes because it hand-builds `{"key": 0}` — the
#256 zero-config-defaults shape: the fixture is the config the reader wishes existed, not the
one the flow writes.
**Live catch (#679, from @onkelfu's #627 install):** #634 settled the EV axis — the *mode* is the
daytime axis, the "At least X" floor is the overnight guarantee, and `floor 0 = never grids at
night` is how the #346 "solar_only never charges from the grid" contract survives as the default.
But `config_flow._install_defaults()` persists `daily_ev_target: 10` on every install, and an
absent `ev_target_soc` resolves to `80` at read time — so the gate's global fallback returned
"night charging allowed" for *every* `solar_only` charger ever installed. That made `solar_only`
behaviourally identical to `min_plus_solar`: not a distinct mode at all. Compounded by a basis
bug — the gate read `daily_ev_target` regardless of `ev_target_type`, so an SOC-targeted charger
was opted in by a kWh key it does not use.
**Closure:** for the mode whose whole point is *not* doing the thing, the opt-in must carry
intent: set **on this charger**, in **the basis this charger targets**. A global default is not
an opt-in. The other night modes keep the global fallback — there the overnight top-up *is* the
mode, so reading a defaulted floor is correct. One shared gate
(`consts/ev_charge_modes.mode_allows_night_charging`) replaces two hand-copied twins whose
docstrings each said "keep in sync".
**Sweep question:** for each safety gate of the form `if not cfg.get(k): <safe path>` — *does
`_install_defaults()` (or any migration) write `k`?* If yes, the safe path is dead code.
**Guard:** `tests/test_679_solar_only_night_default.py` — every case is built from
`_install_defaults()`, never hand-constructed, plus a premise pin that fails loudly if the
installer ever stops seeding the global, and a parametrized twin-agreement test. Refs #679 #634
#346 #627 #256.
**Watch:** any new "leave it blank and SEM won't" contract. Write the test against the *installed*
entry first — a hand-built fixture cannot see this class.

### 28. A sensor is trusted for the slot it is wired into, not for what it measures — GUARDED
**Symptom:** an external counter is configured in a slot named for a quantity ("solar production
energy"), and every consumer reads it as that quantity. On some hardware it measures something
adjacent, so the numbers are wrong in a way no unit check, no range check and no balance check can
see — the value is plausible, monotonic, correctly-united, and simply about a different thing.
**Root shape:** a config slot expresses *where a number comes from*, never *what it is*. The
integration's own semantics get attached to it silently at the read site. Compounding factor: when
the reconciliation that consumes it is **one-directional** (adopt only if higher, only if lower),
a source whose errors would otherwise cancel over a full cycle gets ratcheted — the pass keeps the
excursion in the favoured direction and discards the one that would have paid it back.
**Live catch (#681, our own PROD hardware):** on a DC-coupled hybrid, the inverter's "total yield"
counter measures **AC output**, so it climbs all night while the battery serves the house, and
lags all day because PV routed DC→battery never leaves as AC. Wired into
`solar_energy_sensor`, `_reconcile_solar_energy` credited the night climb as production: a live
Huawei SUN2000 + LUNA2000 counted **3.06 kWh of solar before sunrise** (+0.01 kWh every ~70 s,
356 consecutive points, PV power 0 W throughout). Upward-only adoption banked the night inflation
while integration was ~0 and discarded the compensating daytime shortfall, so it never washed out
— daily solar ~15% high, propagated to monthly/yearly/lifetime, self-consumption, autarky, savings
and ROI.
**Closure:** cross-check the source against a **physical invariant that does not come from the same
sensor**. Here: no PV production exists while the sun is below the horizon, so counter movement in
darkness is absorbed into the baseline rather than credited. The invariant must fail *open* — a
missing `sun.sun` keeps the pre-fix behaviour rather than silently disabling reconciliation.
**Sweep question:** for each externally-configured counter — *what would it read on hardware where
the slot's quantity and the sensor's quantity diverge (hybrid vs string inverter, AC- vs
DC-coupled, gross vs net metering)?* And: *is the pass that consumes it one-directional?* If yes,
errors ratchet instead of cancelling.
**Cheap detector:** integrate the counter's own `stat_rate` power sensor over the same window and
take the ratio. ≈1.0 is trustworthy; the PROD solar counter scored **0.48** over 4 h of midday.
**Guard:** `tests/test_681_night_solar_counter.py` — the PROD night trace replayed, plus a
#556-still-works pin and fail-open cases. Refs #681 #556 #628.
**Watch:** any new `*_energy_sensor` / counter slot, and any `if new > old: adopt` reconciliation.

---

### 29. A guard sits inside one branch of a split; the other branch passes the input through unguarded — GUARDED
**Symptom:** a suppression that provably works — you can watch it fire, cycle after cycle, in the
log — and yet the suppressed action still reaches the hardware, occasionally, with no trace of the
guard in its reason string. The guard is not broken; control simply arrives at the actuator by a
route that never passes it.
**Root shape:** a function branches (`if wanted: … else: …`), the guard is written into the branch
where the interesting work happens, and one or more `return input` passthroughs on the other side
hand the *caller's un-rewritten decision* onward. Every passthrough is individually justified — "out
of scope", "not our session", "the planner owns this" — which is exactly why they don't look like
actuation paths. Worse when the branch predicate is **derived** (a median, a debounce, a cached
flag) and so can disagree with the raw input on the very cycle the raw input is dangerous.
**Live catch (#610, twice, same guard):** the full-car backoff has now moved twice for this shape.
(1) First placed on the fresh-start path only — but `adapter.last_intent` stays `CHARGE_AT_AMPS`
across a give-up (the IDLE actuation is debounced), so the *ladder* block re-entered with reset
state and climbed again; PROD 2026-07-19, armed 11:10:12, ladder restarted 11:10:42. (2) Then
placed inside `if charge_wanted:` — where `charge_wanted` is the **median** of the last
`smooth_window` decided amps and therefore lags the raw decision. After a few collapsed-budget
cycles the median reads below the floor while *this* cycle's decision is a real CHARGE, so control
took the NOT-wanted branch and fell to one of three `return decision` passthroughs (night /
post-stop / #552 ownership). PROD 2026-07-26, one 20-minute armed window: **five raw offers
escaped** (17:41:54 12 A, 17:49:36 12 A, 17:50:37 12 A, 17:52:37 11 A, 17:52:47 11 A), with a
confirmed `keba_p30_max_current` write. Trigger was the Huawei grid meter's single-sample dropouts
oscillating the budget.
**Closure:** evaluate the guard on the **raw** state (armed + not drawing), above the split, so no
route from entry to actuation can skip it. Placement, not logic, is the fix both times.
**Sweep question:** for each guard — *list every `return` between it and the actuator. Which of
them returns the caller's object rather than a rewritten one?* And: *is the branch predicate the
same value the guard is protecting against, or a smoothed/derived proxy of it?*

### 30. Backend-honoured config key with no editable surface — GUARDED
**Symptom:** a setting the runtime genuinely reads and acts on, which the user can never see or
change. It works perfectly for whoever's install-time guess happened to be right, and is a dead
end for everyone else — including, at its worst, a repair flow that names the key it wants you to
set on a screen where no such field exists.
**Root shape:** the key enters config by a path that is not the editing path — an install-time
step that never runs again, a `hardware_detection` auto-fill, or a plain code default — while the
config card and the options flow only ever write the subset someone remembered to add. Nothing is
broken, so nothing fails; the surface simply was never built, and the asymmetry is invisible from
either side. A silent default is the same bug with the guess baked into the source.
**Live catches:** **#684** and **#627** (`ev_start_stop_entity` — read off per-charger config since
v1.0, auto-filled for some brands, never writable, and beta.25's new repair pointed straight at
it); **#688 part 1** (`min_off_time_sec` defaulted to a twitchy 1 min with no surface, so a pool
pump short-cycled and the user could neither see the window nor lengthen it).
**Second half (16.08.2026):** a field you can type into is not yet a surface you can *correct* —
the class also lives in what a form does with the value you did **not** type. HA drops a cleared
optional field out of `user_input` entirely, so `update(user_input)` cannot tell "left alone" from
"emptied": **41 fields on 8 pages** were re-pointable but not erasable (`phase_guard_*` ×12, the
tariff entities, the heat-pump relays, `battery_discharge_control_entity`, the per-charger
entities). And a *suggestion* that clones an installed device is the same asymmetry pointing
outward: the add-charger page deduped discoveries on `_device_id`, which is written onto a
discovery and never onto the stored charger, so charger #2 was pre-filled with charger #1 — one
box, two configs, the second never moves.
**Closure:** every per-charger/per-load key the runtime honours is settable *after* install, on
the same fields it was set with; detection results become suggestions the user can override, not
silent commitments; a cleared field is recorded as an explicit `None` (deleting the key merely
un-covers what `entry.data` holds, #690); devices are recognised by the entities they point at,
which is what actually gets stored. Guarded by `tests/test_627_charger_config_surface.py`,
`tests/test_ev_charger_post_install_surface.py` (AST: no step may merge a form by hand; the
charger fingerprint must cover every entity `hardware_detection` reports) and
`tests/test_688_load_anti_cycling.py`.
**Sweep question:** for each key the runtime reads out of config — *name the screen that writes
it, and the gesture that empties it.* If the answer is "the install-time step" or "hardware
detection", it has no surface; if there is no answer to the second half, it has no way back.

### 31. `except` narrower than what its own body can raise — a "never raises" helper that does — PARTIAL
**Symptom:** a best-effort helper whose docstring promises it can't break the caller, and which is
green in every test, throws on a branch nobody exercises. The `try` around the fragile line looks
diligent; it just doesn't name the exception that line can actually produce.
**Root shape:** the handler is written for the *expected* failure of the operation (a parse →
`ValueError`/`TypeError`) while the statement can also fail *structurally* — an unbound name, a
missing attribute, a `KeyError` from a dict that moved. Unbound names are the sharpest version:
they survive `python -c "import ast; ast.parse(...)"`, `node --check`-style syntax gates, import,
and the whole suite, because **annotations and never-taken branches are never evaluated**. Same
family as the lit-template backtick trap (gotcha 6): syntactically valid, CI-green, throws only
at the moment it runs.
**Live catch (#688):** `coordinator/coordinator.py::_device_run_rows` — "Best-effort: never raises
(the caller's cycle must not break on a plan detail)" — called `datetime.fromisoformat` while the
module imports only `date` and `timedelta`. `except (ValueError, TypeError)` does not catch
`NameError`. Hidden because `forecast_reader` normally reformats `peak_time_today` to `"HH:MM"`,
which takes the *other* branch; only its raw-passthrough fallback (unparseable-but-ISO state)
reaches the dead line. Found by a test written for an unrelated display fix, not by the suite.
**Closure so far:** instance fixed (function-local import). The class is only PARTIAL because the
structural guard is missing: **CI runs no linter at all** (`.github/workflows/` has tests,
hassfest and HACS validation — no ruff/flake8/pyflakes). A pyflakes `F821` gate would have caught
this at authoring time for free.
**Sweep done (2026-07-29):** pyflakes over all non-test production files → 25 undefined-name hits,
**all of them annotations** (`List`, `Tuple`, `Optional`, and quoted forward refs), which Python
never evaluates inside a function body. The `datetime` case was the **only instance in executable
code**. So the instance sweep is clean and the remaining work is purely the guard.
**Guard follow-up:** import the ~9 missing typing names so the file is F821-clean, then add
pyflakes to `tests.yml`. Until then this class can silently return.
**Sweep question:** for each `except` clause — *can the guarded body raise something outside this
tuple?* Specifically: is every name it references bound on **every** path, and does a docstring
anywhere promise "never raises" without a bare `except Exception` to back it?
**Cheap detector:** the escaping decisions are visible in the log by **absence** — their reason has
no `stability:` prefix, because nothing in the filter rewrote them. Any layer that annotates what
it touched makes this class greppable: `grep 'intent=charge' | grep -v '<layer-prefix>'`.
**Guard:** `tests/test_610_full_car_backoff.py::test_median_lag_cannot_smuggle_a_charge_past_the_backoff`
— drags the median under the floor with low cycles, then feeds one raw CHARGE. Both new cases fail
against the pre-fix source with the live signature. Refs #610 #552 #461.
**Watch:** any new early `return decision` / `return state` added to a filter or reconciler, and
any guard written *inside* a branch whose predicate is smoothed, debounced or cached.

### 32. A view composes a multi-entity state set non-atomically — GUARDED
**Symptom:** a card that draws the system as a connected balance (diagram, flow) shows books
that don't add up: ~5 kW grid import against an EV tile reading 0, home unchanged. Transient
(seconds to minutes), unreproducible on demand, and every individual sensor is "correct".
**Root shape:** the view's inputs are published as N separate entities; each commits to HA's
state machine on its own, and *the pipeline itself sometimes publishes an inconsistent set by
design* — the #237/#444 home hold substitutes home while grid/EV carry raw skewed reads, so
for 1-2 cycles (dip tier: up to 5 min) the published set violates its own equation. Fixing one
MEMBER of the set (the held home entity was the first fix for this class) protects that value
and its downstream consumers but ships the inconsistency to every view that composes the set.
**Where it lives:** `coordinator/coordinator.py::_build_power_snapshot` (the closure),
`_smooth_home_consumption` (the intentional incoherence source), `sensor.py`
(`power_snapshot` attr on home, unrecorded), `src/cards/sem-system-diagram-card.js` +
`src/cards/sem-flow-card.js` (snapshot-first readers).
**Second-order instance (#784):** the diagram card's snapshot reads were written into the
*standalone vanilla* copy of the card, which never rendered — the bundled Lit version won the
`semDefineCard` first-wins race. The fix was live in the repo and dead in the browser for the
whole time both copies existed. Fixing the copy you can find is not the same as fixing the copy
that runs; when a tag has two definitions, the pin has to name the one the resource loader
reaches first.
**Closure:** ONE atomic per-cycle snapshot of the whole set, and — the part that makes it more
than plumbing — *the snapshot is the last self-consistent set*: when the cycle is
known-incoherent (`_home_hold_active`, or the residual exceeds tolerance — residual is ~0 by
construction in a clean cycle since home is computed from the other terms), the previous
coherent set ships flagged `held`, with only the non-balance-coupled SOC overlaid fresh.
**Guard:** `tests/test_699_power_snapshot.py` — the exact PROD chimera cycle must ship the
prior coherent set; residual violation without the flag (zero-clamp) too.
**Watch:** any new "hold"/"smooth"/"clamp" applied to ONE member of a published set that a view
renders as an equation; any new card that draws 2+ balance values as connected flows must read
`power_snapshot`, not entities. Third-party cards (k-flow) read raw entities and stay exposed —
by choice: freezing real telemetry entities to protect a view would corrupt genuine data.
Refs #699 #237 #444 #289.

### 33. A card hardcodes a unit HA already converted (display-unit mislabel) — GUARDED
**Symptom:** a reading shown on a card is labelled with a unit that does not match the number
beside it, but only for users on a non-default unit system. #727: a US install's Home view showed
the inverter node at **"118°C"** — a plausible-looking but nonsensical value — because the real
reading was 118 °F. Metric users never saw it, so it survived until a US user reported it.
**Root shape:** SEM publishes a reading as a device-class sensor in a fixed NATIVE unit (temperature
is `°C`-native), and Home Assistant then converts that sensor to the user's unit system for display —
so the value the card reads from `.state` is already in the user's unit (°F on a US install), and its
`attributes.unit_of_measurement` is that unit too. A card that concatenates a **hardcoded** unit
literal (`` `${v.toFixed(0)}°C` ``) onto that already-converted value mislabels it. The number is
right for the user's locale; only the suffix is a lie. This is the DISPLAY-side twin of class 21
(that one is the ingest-side magnitude decision). Compounding factor here: the *ingest* also assumed
°C (class 21 extended to temperature — `sensor_reader._read_*_temperature` read `float(state.state)`
ignoring the source's `°F` unit), so a mislabeled bridge (SolarAssistant reporting the C value with a
°F label) produced the doubly-wrong 118.
**Where it lives:** every dashboard card that renders a device-class sensor (temperature today;
any future unit-converted class — energy, power, volume, pressure, monetary) with a literal unit.
`dashboard/card/src/cards/sem-system-diagram-card.js` (inverter temp) and `sem-battery-card.js`
(battery temp) were the two temperature sites. **Not** instances: the config-card HP/HW setpoint
sliders + legionella stepper are SEM's own `°C` control *inputs*; the config-card HP/HW
current-temperature *displays* (`sem-config-card.js` ~1109/1113) are plain `coordinator.data`
attributes, NOT device-class sensors, so HA never unit-converts them and a `°C` label is not a
class-33 mislabel — but their INGEST assumes °C, which is the deferred Guido sibling below. The
weather card already did it right (`attrs.temperature_unit || '°C'`), the reference pattern.
**Closure:** read the unit HA attached to the entity (`_unitOf`/`_unitStr`, or the
`temperatureUnit`/`formatTemperatureLabel` helpers in `dashboard/card/src/util/temperature.js`) and
label with that, falling back to the native unit only when HA attached none. Ingest side: route
`_read_*_temperature` through `units.temperature_state_to_celsius` so a °F/K source is converted to
`°C` native before republish (class 21's one-place-decides-magnitude rule, now covering temperature).
**Guard:** `dashboard/card/test/temperature-unit.test.js` (a °F entity can only ever be labelled °F);
`tests/test_564_battery_temperature.py` (F→C on ingest, °C passthrough, unitless→°C);
`tests/test_641_units.py` (the `temperature_state_to_celsius` behaviour **and** the AST lint widened
to ban a `unit == "°C"/"°F"` comparison outside `units.py`, so a future inline temperature-unit check
is unrepresentable). Refs #727 #564 #641.
**Watch:** the JS guard tests the pure helpers, not the card render — a NEW card that draws a
converted sensor with a hardcoded unit isn't caught until it routes through the helpers. Any new
device-class reading on a card must label from `unit_of_measurement`, never a literal. **Sibling
left for Guido (larger/riskier — control + safety path):** the heat-pump / hot-water controllers'
`get_current_temperature` (`devices/heat_pump_controller.py`, `devices/hot_water_controller.py`,
incl. the climate `current_temperature` attribute path) still read `float(state.state)` assuming °C
and compare against °C setpoints — a US user with a °F sensor gets wrong control decisions
(legionella safety). Same class as the ingest side; route through `temperature_state_to_celsius`,
but the climate-attribute unit semantics + control/safety tests need care, so it is flagged not
auto-shipped.

### 34. Recognised field NAME, silently rejected element SHAPE (parser shape gap) — GUARDED
**Symptom:** a parser advertises a set of accepted attribute/field NAMES, an input arrives under one
of exactly those names carrying valid data, and it is dropped without a word — often while a
diagnostic *names the very attribute it just rejected*, sending the user to fix the name (which was
never wrong). The inverse of class 10 (there the NAME isn't in the include list; here the name is
recognised but the value's SHAPE isn't). **Root shape:** the accept-check is split — one list gates
the *name*, an inner `isinstance`/key-shape guard gates the *element form* — and only the name list
is advertised. Every provider whose payload takes the un-handled shape is invisible; the scalar/other
paths keep working, so the failure reads as "half of it works, must be a config issue".
**Live catch (#732, @bjpo-abelco, Growatt/DK):** `tariff_provider._read_prices_list` iterated each
day-keyed attribute (`prices_today` / `today` / `raw_today` / …) but parsed only items that were
`dict` (`{start, value}`-style). A **flat float list** — `today: [0.25, 0.30, …]`, which is
Nordpool's *own* `today`/`tomorrow` shape and the one nearly every template/derivative sensor copies
— has `float` items, so the whole 24/96-element array was skipped: `tariff_parsed_count: 0`,
percentile classification degraded to NORMAL-only, cheap-window planning off. The #359 warning fired
listing the names, none of which was the problem. Reproduced across three independent DK sensors.
**Where it lives:** `tariff/tariff_provider.py` — the day-keyed loop (`DAY_KEYED_PRICE_ATTRS`) is now
flat-aware; the two former dict-only loops (generic + Nordpool `raw_*`) were **merged** into one so
the shape logic can't drift between them. **Assessed and left dict-only, correctly:** the
`forecasts`/`rates` loop (Amber/Octopus objects — genuinely dict-shaped, no day anchor for a bare
list) and the `nordpool.get_prices_for_date` service parser (a structured `{start,end,price}` API
response). **Closure:** accept both shapes at every day-keyed site — a flat numeric list is anchored
at the day's local midnight, granularity read from list length (24→hourly, 48→30-min, 96→15-min),
`None` gap-padding skipped by index so surviving slots stay aligned; ambiguous keys (bare `prices`,
no day reference) still reject the flat shape rather than guess a day, and a flat list longer than 96
(the finest single-day granularity) is refused rather than silently packing multiple days into one —
both cases where the length→granularity heuristic can't disambiguate, so it declines to guess. **Guard:**
`tests/test_732_flat_price_array.py` — the parity test parametrizes a flat-list case over
`DAY_KEYED_PRICE_ATTRS` *derived from the parser* (per class 24: the list is read from the source,
not retyped), so re-narrowing any recognised key to dict-only fails CI; plus a vacuity floor and a
bool-isn't-a-price case. Refs #732 #359.
**Sweep question:** for every parser that advertises accepted names — does it accept the *shape* a
user would most naturally put under each name, or only the one shape the first provider happened to
use? And: does the "unrecognised" diagnostic distinguish *name* from *shape*, or blame the name for a
shape gap?

### 35. Signed accumulator whose direction is carried by a name, not asserted anywhere — GUARDED
**Symptom:** one field holds a signed physical quantity (a deficit, a balance, a remaining amount)
and several sites write it. Most agree on the convention; one books its input with the opposite
sign. Nothing raises, nothing goes unavailable — the number simply walks the wrong way, and only in
the state where the *other* writers aren't there to overwrite it. Because that state is a corner
(sensor offline, session that stops short), the bug can ship for a year. **Root shape:** the field's
meaning lives in its NAME, and the name is ambiguous. `_energy_since_full` reads equally well as
"energy *consumed* since full" (a deficit, which charging repays) and "energy *delivered* since
full" (throughput, which charging grows). Each writer silently picks whichever reading fits its
local source; no single call site looks wrong.
**Live catch (#708, @Azlinon, 85 kWh Blazer EV / JuiceBox / OnStar):** `EVTaperDetector.update_energy` —
the one path that runs *every cycle while charging* — **added** the delivered kWh to the deficit. Seven
other sites treat the field as a deficit (day-rollover decay adds driving, the sensor calibration
sets `(100−soc)/100 × capacity`, the taper/stall anchor zeroes it at 100 %, `on_session_end`
*subtracts* a session, every display divides it out of 100). The reporter stopped his SOC
integration mid-charge and watched "SOC (EST.)" walk from 32 % down to 25 % while 11.5 kWh went
into the pack: `11.5 / 85 × 0.92 ≈ 12.4 %`, "almost exactly the amount of *decrease* I'm seeing".
The `#715` energy-accounted *ceiling*, added to the same file weeks earlier, had the sign right; the
reporter noticed the two disagreed on his own dashboard.
**Why it survived a year — the cancelling pair.** The wrong-sign writer had a partner: `update_energy`
added the delivered kWh during the session, then at disconnect `on_session_end` **subtracted** the
session total. Two errors in opposite directions, so the value at disconnect landed back near the
truth and only the *live* number was inverted. It takes a charge that stops short **and** a
vehicle-SOC sensor that goes quiet to leave the wrong value visible at rest. **This is the trap in
the fix, not just in the bug:** correcting one half alone converts a hidden error into a loud one of
the same magnitude in the other direction (here: 5 kWh into a 40 kWh pack at 50 % would have read
73 % instead of 61.5 %). When a signed accumulator has two writers that disagree, find the *pair*
before editing either.
**How the suite defended it:** six call sites across four tests in `test_ev_taper_detector.py` passed
`update_energy(8.0)` and asserted SOC *fell*, commented "Simulate 8 kWh consumed" — while both
production call sites pass `ev_power × interval_hours / 1000`, i.e. energy **delivered**. The tests
encoded the misreading and went green on it. A test that assumes something about its caller is only
as good as the last time someone checked the caller.
**The counter branch was the same error, wearing a unit.** Alongside the `+=` fallback sat a
"reconcile from the hardware counter" branch (#174): `deficit = hw_total − hw_total_at_full`, i.e.
*energy put back in since the pack was last full* assigned to *how far below full it is*. Those are
opposites. It is reachable across sessions — `reset_session` clears `_full_detected` but the taper's
`_hw_total_at_full` survives — so on a charger exposing a lifetime total it OVERRIDES a fresh real
SOC reading: a pack a sensor just put at 38 % reads 94 %, then walks down as it charges. Same
symptom, immune to any per-cycle fix.
**Where it lives:** `coordinator/ev_taper_detector.py`. **Closure:** charging subtracts, with the
charge efficiency; `on_session_end` keeps only its *bootstrap* branch (the sole way an install with
no SOC sensor ever gets anchored) and no longer re-books the session; the deficit is booked from the
power integral alone. The hardware counter is still tracked for the taper anchor but no longer feeds
the deficit in any form. Its per-cycle *delta* looked like the obvious salvage and is not: a counter
that goes unavailable and returns re-books the gap the integral already covered, and nothing
normalizes its unit, so a charger publishing Wh delivers ~4 Wh cycles as the bare number `4.0` —
under any plausible sanity bound, and enough to fill the pack in seconds.
**Second-order trap — a new guard can freeze what it was protecting.** Booking now returns early
while `not _soc_anchored` (writing `_estimated_soc = 100` into a PERSISTED field for an install with
no reference was its own bug). That early return silently changed two coordinator sites that reach
past every method and set the detector's privates directly: the stall→full anchor sets
`_soc_anchored` and is fine; the SOC **self-heal** set only the deficit and the estimate, so after
the gate its healed value stops moving for the rest of the charge — worse than the wrong-but-moving
number it replaced. **Tell:** a gate added inside a class changes the contract for everyone who
mutates that class from outside, and those callers are invisible to the class's own tests.
**Assessed and left as-is:** the recorder-history cold-start seed in `async_seed_from_history` sets
the field from summed post-full session energy — the same conflation, but a one-shot boot heuristic
with no better information available; flipping it there yields "SOC 100 % forever" (#245). Marked in
place so nobody "corrects" it to match. **Guard:**
`tests/test_708_estimate_falls_while_charging.py` — a monotonicity pin (*the estimate may never fall
while the charger delivers*, checked every cycle), the reporter's own arithmetic as the expected
value, a disconnect pin that fails on the double-count, a taper-anchored-counter pin (verified RED
against the restored branch: 94 % vs 38 %), a Wh-shaped counter pin, a #245-unanchored pin on the
*persisted* `_estimated_soc` (not just the deficit — a display gate hides a bad value, it does not
stop it being written), and an AST pin over the coordinator's self-heal block asserting it anchors
what it writes. Refs #708 #715 #174 #245.
**Sweep question:** for every field that accumulates a signed physical quantity — is its direction
asserted by a test that would fail if one writer flipped, or is it only implied by the field's name?
And: which writer runs in a state where no other writer will overwrite it? That one is unguarded by
construction. Once you find a wrong sign: **is there a second writer whose opposite error has been
cancelling it?** And before shipping the guard: **who mutates this object's fields from outside the
class, and does the new precondition hold for them?**

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
  *Sub-shape — parked with a reason that outlived it (#658):* EV counter reconciliation was built,
  found wrong for a real reason (it compared a midnight-resetting counter's *absolute* value
  against a bucket that rolls at the charge deadline), and disabled with a comment stating that
  reason plus a reassurance — "SEM's own power integration (10s cycles) is reliable enough" — that
  was true only in the case the feature did not cover. Its six tests were then `@skip`ped with the
  same sentence, so a full green suite reported nothing missing, for years. The objection was
  fixable in an afternoon (deltas instead of absolutes: a counter reset is just a reset); nobody
  re-read it because a comment explaining a decision reads like a closed question.
  **Tell:** a disable comment that argues rather than states; `@pytest.mark.skip(reason=...)` where
  the reason is a *design* objection rather than an environment one; a setter with no caller
  (the orphan scan of #653 is what surfaced this one). **Sweep:** for every skipped test and every
  "disabled because" comment — is the stated obstacle still true, and was it ever unfixable?
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
  monitor said only what it did, which is observe. **#664 then closed the whole surface by
  decision, not by building it** (Guido, 2026-07-26: SEM does not support Sperrzeiten): the
  module, its three always-dead entities, `HeatPumpController.block()`/`unblock()` and the
  orphan-baseline entry are gone, and `config_flow` no longer advertises a 4th SG-Ready
  state SEM cannot drive. **The lesson is the sequencing.** #654 kept the orphans because
  the config flow advertised them — an advertisement is a real constraint, so the honest
  options were *build it* or *retract the advertisement*, never *delete quietly*. Asking
  the owner whether the feature is wanted at all cost one sentence and settled a design
  question (solar-exempt semantics) that no amount of code reading could have.
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

**Structural guard — EXTENDED to data (#669, 2026-07-26).** The orphan-method guard sees a
missing *edge between functions*. It is blind to a **dangling data reference**: a string
literal naming an entity that no platform declares. `consts/sensors.py` carried a 64-entry
`SEM_SENSORS` map to `sensor.sem_*` ids, **45% of them dead**, with zero production readers
— and it was still accreting rot right up to deletion (`ev_max_current_available` was added
*after* the 45% was measured). It was deleted, not repaired: a map nothing reads is not an
API, and a plausible map to ids that mostly do not exist is worse than no map, because
anyone reaching for it gets `sensor.sem_home_consumption`, which never existed.

The new rule (`tests/test_667_label_registry.py::TestConstsRegistriesDoNotRot669`) is scoped
to the **reference**, not the container: every `<platform>.sem_<key>` literal under
`consts/` must resolve to a key a platform file actually declares (`SEMSensor` builds
`sensor.sem_{description.key}`, sensor.py:1942). Banning the map *shape* would have flagged
three healthy named constants (`ENTITY_SOLAR_POWER` and siblings, live and used) and taught
the next person to route around the rule.

Two lessons worth carrying: (1) the registry kept rotting while it was already known-rotten,
so a one-time repair could not have closed it — only a rule that fires on the next entry;
(2) dead code that nothing asserts is merely waste, but **dead code with a green test that
cannot fail is *claimed coverage*, and that is what keeps it alive for years.** The
`SEM_SENSORS` test asserted a dict literal against itself.

### 36. Idle/lagging EV signal read as an active charge — the 500 W floor bypassed at a surface — GUARDED
**Symptom:** a user-facing "Charging" surface (badge, inference, notification) is on while the
box idles at standby draw (~110–140 W on KEBA) with the charger disabled. **Root shape:** the
codebase's own canon says the brand charging boolean is informational (`keba.py:
handshake_power_w = 500`, it lags ~5 s per #289; `charger_types.py`: "prefer `power_w > 500`")
— but a surface reads the raw boolean or uses a sub-standby power threshold, bypassing the
floor the adapters all apply. Two instances shipped side by side (#739, live on PROD
08.08.2026): the published `binary_sensor.sem_ev_charging` was the raw boolean (a numeric idle
state code reads truthy through the `float(s) > 0` fallback), and the #285+1 plug-lying physics
inference used `> 100 W` — *below* the box's own standby draw, so idle power inferred a phantom
connection. **Closure:** ONE constant (`sensor_reader.EV_ACTIVE_CHARGE_FLOOR_W = 500`) feeds
both the badge gate (`_gate_ev_charging_on_power` — applied whenever a power source is
configured; boolean-only installs keep the raw signal) and all physics-inference sites; the
inference's boolean leg reads the *gated* badge. A real ≥6 A charge is ≥1.38 kW, so the floor
can never suppress a genuine charge. **Guard:** `tests/test_739_charging_badge_floor.py` +
the phantom-standby corner in `test_ev_connected_physics_defence.py`. **Watch:** any NEW
surface that answers "is the car charging?" must derive from the gated badge or compare power
against `EV_ACTIVE_CHARGE_FLOOR_W` — never the raw brand boolean, never an ad-hoc threshold.

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

---

### 37. Display/derived surface recomputes an authoritative decision from a weaker signal — GUARDED
**Symptom:** a card shows the *opposite* of what a device's own entity says — a switch reads
`on`, the priority list renders the row "Off". The control layer behaves correctly; only the
surface lies, so it reads as a UI glitch rather than a logic bug. **Root shape:** an
authoritative predicate exists (SEM already knows and stores the device's control entity, and
the control path reads it), but a *display/derived* path recomputes the same decision **inline
from a weaker proxy** instead of reading the authoritative source — and the two drift. The
proxy is lossy in a corner the author didn't picture: here on/off was inferred from
`power > 0`, but a switch-controlled load idling below its power sensor's reporting floor (a
Shelly PM, a Powercalc-backed `light.*` under a watt) publishes `0 W`, so power alone reads ON
as OFF. A cousin of class 11 (there a *corrected* value leaks onto a raw display field; here a
*weaker* value is recomputed in place of the authoritative one) and of the "Duplicated
mechanism" meta-class (two copies of one predicate). **Live catch (#745, @Azlinon, split from
#744):** `features/device_registry.py::get_devices_for_sensor` (the `sem_controllable_devices_count`
card payload) computed `is_on = current_power > 0` for every Energy-Dashboard row, ignoring
`device.control_entity` entirely — while `load_management` reads the switch authoritatively via
`LoadDeviceDiscovery.get_device_current_state`. **Where it lives:** the ED-row builder in
`get_devices_for_sensor`. **Assessed and left as-is (correctly):** the service / surplus-direct /
EV-charger rows there derive `is_on` from the controller's own `is_active` / charger state (the
authoritative belief), and the battery row from charge power (a passive sink with no switch) —
none is a power-only recompute of a known switch. **Closure:** one shared switch-aware predicate,
`resolve_load_is_on(hass, control_entity, power)` — the device's own on/off-domain control entity
(`switch`/`light`/`input_boolean`/…) is authoritative, power is the fallback only when there is no
readable on/off entity (a `number.*` amperage control, an integration service, an unavailable
switch). It is the display twin of `get_device_current_state`; both read the switch first and
differ only in the fallback for an *unreadable* switch — control fails safe to OFF (never assume a
device runs), display falls back to observed power (never hide a drawing device), documented at
both sites so the difference reads as a decision, not drift. **Guard:**
`tests/test_745_load_on_off_from_state.py` — the reporter's `switch=on / 0 W` case reads ON in the
payload (RED against the pre-fix `power > 0`), the fallback shapes, and a parity test pinning that
the display and control predicates return the *same* verdict for a readable switch (so they cannot
silently diverge again). Refs #744 #745.
**Sweep question:** for every card/attribute/derived field that answers a yes/no or state question
the *control* layer also answers — does it read the authoritative source (the entity, the
controller's belief), or recompute it from a proxy (power, a name, a threshold)? If recomputed,
name the corner where the proxy and the truth disagree.
**Known-open sibling (#744, flagged for Guido) — the authoritative read is UNREACHABLE for lights.**
`resolve_load_is_on` prefers the control entity for the whole `_ONOFF_CONTROL_DOMAINS`
(`switch`/`light`/`input_boolean`/`fan`/`humidifier`/`siren`/`remote`), but control *discovery*
(`load_device_discovery._find_control_in_device` / `_find_control_by_name`) only ever populates
`switch`/`number`/`input_boolean` — never `light.*` etc. So a `light`-controlled ED load keeps
`control_entity=None` and falls back to power; the #745 light-awareness is inert. The #744 power
derivation (class #10) makes such a load read ON *via measured watts* (the reporter's floods draw
real power), which covers the reported case — but a light genuinely "on" below its power floor would
still read Off. Closing it means discovering `light.*` (and the other on/off domains) as control
entities, which ALSO makes them `is_controllable` → **auto-shed-eligible fleet-wide**
(`load_management._get_devices_for_shedding` sheds any controllable, non-critical device). That is a
load-shed *policy* change, not a display fix — Guido's call before it ships.

---

### 38. A command's CALL SITE changes shape and turns a transition into a per-cycle repeat — GUARDED
**Symptom:** nothing visibly breaks. The device does the right thing; the bus underneath it does
not. On a shared serial link the tell is second-hand — read timeouts, "invalid response", a
coordinator that goes unavailable for a cycle — and it is attributed to the link, not to us.
**Root shape:** a write is correct *as a transition* ("stop forcing") and was authored where a
transition is what happens — one edge, one write. Later, a **different layer** changes the shape
of the decision that produces it: the caller stops asking "did this change?" and starts asking
"what should be true now?", every cycle. The write itself was never guarded, because at the time
it was written there was nothing to guard against. Nobody edits the command; the *frequency* is a
property of the caller, and the caller is a file away. Distinct from plain missing idempotency:
the code was fine until an unrelated refactor moved the caller from edge-triggered to
level-triggered. **Live catches:** #538 — `command_normal` rewrote the same 5000 W discharge limit
every cycle, colliding with `huawei_solar`'s read coordinator on the one Modbus transaction ID.
#757 (second occurrence, caught in the branch audit before ship) — the #638 one-gate build made
`decide_battery` return `STOP_FORCE_CHARGE` on *every* cycle a SCHEDULED battery sits outside its
plan block, so a 21:00 verdict with an 02:00 window asked the inverter ~1800 times to stop a charge
it was not doing. **Closure:** the command is a no-op when the hardware is already in the commanded
state, decided from `_last_intent` — the record of what the hardware was **last told**, which may
only be set on a write that actually landed, so a failed write leaves it alone and the next cycle
retries (honest-retry discipline). Belt-and-braces: never stay silent while we *believe* the thing
is running (`_forcible_charging`). **Where it lives:** every `command_*` on the battery adapters
(`battery_adapters/huawei.py` · `generic.py` · `goodwe.py` · `deye.py`) and the
`ChargeController.stop_forced_charge` layer they delegate to (`force_charge.py`); the same shape is
latent in any per-cycle actuator write. Distinct from class 4 (that is a *swallowed* command
reporting false success); here the command lands fine, just far too often — but the honest-retry
half is shared with class 4.
**Where the guard may NOT go — two placements that look equivalent and are not.** (a) Not at the
`stop_forced_charge` *source* layer: an `if not _active` guard there strands a boot orphan — after a
restart the in-memory `_active` is False while the inverter may still be force-charging, and for
GoodWe/Generic that unconditional stop is the *only* boot-orphan clear (no snapshot, no status
reconcile like Huawei's `_maybe_clear_startup_orphan` / Deye's persistent snapshot). The guard must
key on the recorded *intent*, which honest-retry keeps truthful, not on a flag that lies across
restarts. (b) Not at the *top* of `command_stop_force_charge` on Huawei: the two real edges
(`_maybe_clear_startup_orphan`, `_stop_forcible`) run first, and a top-of-function return would skip
them — re-opening #532, the LUNA2000 left selling to grid after a restart. The predicate belongs
*after* the edges and must carry the `_forcible_charging` belt-and-braces so we never stay silent
while we believe a force is running. (Both placements were authored independently for #757 — on the
release branch and on develop — and the difference only showed up at the merge. `deye.py` was
already safe: snapshot cleared after restore + write-and-verify.)
**Guard:** `tests/test_757_stop_force_charge_idempotency.py` + `test_757_stop_force_charge_idempotent.py`
— per adapter: the repeat is silent (zero real HA service calls on a second stop), the FIRST stop on
a fresh post-restart adapter still reaches the inverter, a stop-while-believed-charging still writes,
and a failed write is not recorded so the next cycle retries.
**Sweep question:** for every hardware write, ask *who calls it and how often* — not whether the
write is correct. If the caller is a per-cycle decision function (a reconciler, a `decide_*`, a
"desired state" pass), the write must be idempotent at its own door; a write that is only safe
because its historical caller was edge-triggered is one refactor away from a storm. And: does the
"already in this state" signal survive a restart, or does it lie about the hardware on a fresh
adapter?
**Open sibling — the mirror-image FORCE_CHARGE flood (flagged for Guido):** `command_force_charge`
has the same shape on the paired command — the scheduler emits FORCE_CHARGE every *in-window* cycle
(`decide_battery.py`), and `start_forced_charge` re-issues `forcible_charge_soc` /
`select_option "Eco Charge"` / `switch.turn_on` each time with no transition guard. Left unfixed
here because the Huawei `forcible_charge_soc` carries a `duration` — a per-cycle re-issue may be
*load-bearing* (refreshing the duration so the charge isn't cut off mid-window when
`duration_min` < window). Closing it safely needs the duration semantics resolved first (does the
scheduler set duration to the full remaining window, or rely on re-issue?), so it is a design call,
not a mechanical guard.
Refs #538 #757.

### 39. A safety flag whose truth lives in a store its reader cannot see — GUARDED
**Symptom:** a promise about hardware silently does not hold for a window after every restart. The
UI is correct — the switch shows the right state — and the flag is genuinely honoured *once the
entity attaches*, so every point-in-time check passes. Only the interval between component setup
and platform attach is wrong, it is invisible in a steady-state inspection, and on a busy start it
is minutes long. **Root shape:** the value has more than one place it can be recorded, and two
readers cover different subsets. Here: `observer_mode` / `vacation_mode` /
`energy_plan_actuation` live in `entry.options` (runtime flip), `entry.data` (install flow) **or**
— on an install predating the persisted toggles — only in HA's restore store, which is the switch
*entity's* record and structurally invisible to `async_setup_entry`. The switch read all three; setup
read two and fell back to the per-key default. The default is the armed direction, so a missing
record read as "act". **Second-order:** the restore store expires (`STATE_EXPIRATION`, 7 days), so
the one reader that *was* right also loses the answer on any install left off for a fortnight —
a read-only fix would have lapsed silently. **Live catch:** 16.08.2026, HA-TEST — a box wired to a
real KEBA and LUNA2000, believed hands-off, would have run armed for the length of every start;
found while inspecting `core.config_entries` before a deploy, not by any test or log.
**Closure:** one resolver (`persisted_flags.py`) reading all three sources in one order, called by
setup *before* the coordinator is constructed, and PROMOTING what only the restore store knows into
`entry.options` — so the ambiguity is resolved once and permanently instead of re-derived (and
eventually lost) every boot. The switch shares the default table by reference, so "what silence
means" cannot drift between the two readers. Silence resolves to `None`, never `False`: "never
recorded" and "recorded off" are different facts, and collapsing them is what let the armed default
win. **Where it lives:** any flag with an entity-owned record *and* a config-entry record; the
options write is safe at that point in setup only because `add_update_listener` attaches later.
**Guard:** `tests/test_persisted_flag_promotion.py` — precedence, junk restore states are not a
record, promotion writes through, an explicit config is left untouched (no write, no reload churn),
all three flags, and an ordering assertion that the promotion happens before `SEMCoordinator(`.
**Sweep question:** for every flag that gates hardware, list *every* place it can be recorded and
*every* reader — then ask whether the reader that runs EARLIEST can see the source that is written
LAST. If not, the gap is a window, and the direction of the default decides whether that window is
merely wrong or actively dangerous. Distinct from class 7 (that re-arms a *timer* across restart);
this one never had the value at all. Refs #777.

### 40. A fabricated default defended by a ratchet built for measurements — GUARDED
**Symptom:** a whole population of devices reports the *same* suspiciously round number, forever,
and no amount of live data moves it. Nothing errors, nothing is unavailable, and every individual
guard reads as sound when you inspect it alone.
**Root shape:** two ingredients that are each defensible and lethal together. (a) A code path
**invents** a value when it has none — a floor, a default, a "saner than zero" placeholder — and
stores it in the same field a real measurement would occupy. (b) Some *other* path defends that
field one-directionally (`if observed > current: adopt`, `if x > FLOOR: persist`), because for a
measured peak that is exactly right. The defence cannot tell what it is defending: the invention
now has the standing of evidence, and the ratchet's job becomes protecting the guess **from** the
measurement. The tell is a literal appearing in a *comparison* rather than only in an assignment —
`> DEFAULT_X` is code asking "is this real?" using a number as a proxy for provenance.
**Live catch (#744, @Azlinon, 47 loads):** a discovered load is constructed from its power sensor,
which reads **0 W for the whole time the load is off** — so `SwitchDevice.__init__` supplied the
1 kW default to nearly every load at nearly every rebuild. From there: `calibrate_rated_power`
refused 8 W as "not an improvement"; `_capture_calibrated_ratings` persisted only `rated >
_DEFAULT_RATED_POWER`; `_seed_and_apply_ratings` seeded 7-day history only if `hist_max >
_DEFAULT_RATED_POWER`, and otherwise only ever raised the device. Three independent up-only guards,
each correct against a measurement, jointly pinning **every load under 1 kW at exactly 1 kW for
life**: a 6.4 W shower light on a Shelly PM read "~1.0 kW" on the card, its `min_power_threshold`
demanded a kilowatt of surplus before SEM would offer it any, and the planner sized a house of small
loads at tens of kW of demand that does not exist. Two further spellings of the same invention on the
service path — `stored["rated_power"] = spec.get(..., 1000)`, the guess written to **disk** where it
returns as fact, and a card row reading that spec instead of the live calibrated rating.
**Closure:** make provenance a **first-class attribute of the value**, not something inferred from
its magnitude. `ControllableDevice.rated_power_measured` (the question `_daily_energy_source` already
asks for energy, one attribute further along): the class that invents the placeholder labels it, and
every consumer branches on the label instead of on `1000`. While unmeasured, the first real reading
REPLACES the value in **either** direction; after that the up-only ratchet applies unchanged. The
placeholder itself stays — a load with no power sensor still needs a saner floor than 0 W (#576), and
it is still forbidden to learn from the energy-deriver's estimate (#744's earlier half,
`test_744_rated_ratchet`). This is the mirror of #755 contract 1: *an estimate must never teach the
model* has a twin — **an estimate must never out-rank the model's first real lesson.**
**Where else it lives:** any `DEFAULT_*` / `or 1000` / `max(x, FLOOR)` whose result lands in a field
later compared against fresh data. Sweep when touched: `spec.get(k, <literal>)` at any *storage*
write, EV rated-power / amp assumptions, forecast and tariff fallbacks. **And one spelling that
hides a level up: a schema default.** `vol.Optional(k, default=1000)` is *always* filled in by
validation, so every call arrives carrying the guess and nothing downstream can ever observe that
the caller named no rating — the absence is unrepresentable, which left a correct fix one layer down
inert for every real service call. A key that is genuinely optional must carry **no** default.
**Guard:** `tests/test_744_measured_rating.py` — the guess is labelled at every build site
(constructor, spec factory, service registration), the first measurement replaces it downward, the
ratchet resumes afterwards, a rating we were given is never overwritten downward, a sensor-less load
keeps the placeholder, and a small rating survives persist + rebuild + history seed.
**Sweep question:** for every default your code supplies for a value it will later *learn* — *can a
reader tell the default from a learned value without comparing it to the default?* If the only way to
ask "is this real?" is `x != DEFAULT` or `x > DEFAULT`, the answer is no, and every one-directional
guard downstream is now protecting the invention. Refs #744 #576 #755.

### 41. An observation writes a flag that records agency — GUARDED
**Symptom:** SEM actuates a device the user configured "hands off", reproducibly, within seconds of
a restart — and every gate you inspect is present and correct. The user turns it back on; SEM takes
it away again.
**Root shape:** a flag answers a question about **who acted** (`_sem_owned` — "did SEM start this
load?"), and some path assigns it from what it can **see** (the switch is on). Observing a switch
cannot answer a question about agency, so the write is a fabrication wearing the shape of a fact.
It hides because the fabricating path and the path that *acts* on the flag are far apart and each is
right alone: adopting a running load is right (#559/#766 — otherwise it runs forever, unbelieved
and unstoppable), and releasing a load whose mode moved to Off *while SEM was driving it* is right
(class 17, PROD 2026-07-23). Only the pair is wrong. The tell is a boolean whose name is a
past-tense claim about the system's own behaviour, assigned in a function whose inputs are all
present-tense observations.
**Amplifier — the gate lives at the CALL SITE, not at the write.** `adopt_if_running` was safe only
because both of its callers in `device_registry.py` checked `control_mode == SURPLUS` first. When
#766 added `sync_belief_to_observation`, the per-cycle twin modelled on it, it inherited the body
and not the gate — because the gate was never part of the body. Class 38's neighbour: policy that
lives in the caller is policy the next caller has to remember, and eventually one doesn't.
**Live catch (#779, @onkelfu, v2.0.0-beta.3):** dishwasher, heat pump and network gear all
configured **Mode: Off**, all switched off by SEM seconds after an HA restart. After a restart the
belief starts IDLE while the switch is already ON, so the very first cycle adopts it, claims it, and
`compute_load_intent`'s class-17 release — reading a flag that now says SEM was driving it — stops
the user's dishwasher. A previous beta had retired a duplicate device row he was pointed at; the
switch-off survived that, because the duplicate was never the mechanism.
**Closure:** one writer holds the gate. `ControllableDevice._adopt_ownership()` — every path that
adopts an *observed* ON routes through it, the mode check is inside it, and the two call-site gates
are **deleted**, because duplicated policy is exactly what drifted. `record_activated` remains a
second writer and is the one sanctioned ungated claim: SEM issued the command, so it owns the result
by construction — there is no observation to second-guess. The BELIEF still follows the switch at
every mode: Off is monitoring, and monitoring means the books stay honest (runtime accrues, the
#755 recorder can say `measured`).
**The asymmetry, stated once so the guard can encode it:** *releasing* ownership (`= False`) needs no
justification and stays free — the reconciler and `mark_reconciled_off` do it directly. *Claiming* is
the direction that needs a reason. *Carrying* a claim already made (`= other._sem_owned`, the
rebuild transplant in `SurplusController.register_device`) is neither, and stays free too — gating it
would remove the class-17 release that is the backstop for that path.
**Where else it lives:** any flag named for a past action of SEM's — `sem_owned`, `surplus_managed`,
`session_owner`, `*_forced`, `*_by_sem` — assigned anywhere other than where SEM took that action.
Also: whenever a one-shot grows a per-cycle twin, diff the CALLERS, not just the bodies.
**Guard:** `tests/test_779_mode_off_ownership.py` — an AST lint over `devices/base.py` and over the
whole component: a `_sem_owned` assignment that is neither `False` nor a copy of another
`_sem_owned` may appear only in `record_activated` / `_adopt_ownership`; plus behavioural pins on
both adoption paths, on the registry no longer carrying a duplicate gate, and the must-not-move
class-17 release.
**Sweep question:** for every boolean that records *what SEM did*, ask — could this be assigned by a
function that only knows what the world *looks like*? If yes it is not a record, it is a guess, and
something downstream is treating it as testimony. Refs #779 #766 #559 #576.

---

### 42. Discovery admits on SHAPE when the registry already answers on ROLE — GUARDED
**Symptom:** the device list fills with rows that are not devices — a load per *setting* of one
appliance, all `is_controllable`, all `W = 0`. Nothing errors; the fleet just quietly grows a
population SEM will try to manage.
**Root shape:** the admission test asks a **structural** question ("is this a `switch.*` I can pair
with a power sensor?") about a question that is **semantic** ("is this the device's control surface,
or one of its knobs?"). Home Assistant already answers the semantic one — `entity_category` =
`config`/`diagnostic` means *explicitly not the primary control* — and the entity_id cannot be made
to answer it (`switch.wled_treppe_umkehren` is shaped exactly like `switch.dishwasher`). The same
registry-driven shape as the #744 light filter, and the same failure to consult it.
**Amplifier — a fuzzy pairing turns one admission into N.** `_names_match`'s last resort strips
every digit, so one `sensor.wled_treppe_power` matches every sibling switch of that strip, and
`shelly_kanal_1` matches `shelly_kanal_2`'s meter. A structural admission plus a lossy match is a
fan-out: one wrong yes becomes twenty-four rows, and two real channels swap watts.
**Live catch (#781, @onkelfu, v2.0.0-beta.4):** 24 of 50 Load-Management rows were
`load_device_wled_*` — *umkehren*, *einfrieren*, *nachtlicht*, *sync senden/empfangen* — every one a
WLED setting, every one `peak_only` + controllable, so a peak event could flip a stair light into
reverse hunting for watts that never existed. The strip's CONFIG switches also defeated the #744
light filter: `_is_light_fixture` tested the bare sibling **domains**, saw `switch` present, and
concluded "metering plug, keep".
**Closure:** one predicate, `LoadDeviceDiscovery.is_config_surface`, consulted at **all five** places
the class lives — pattern discovery; `_find_control_in_device` (an appliance's child-lock is not its
actuator; the filter is *deliberately* strict, because "this device has no primary control, use the
categorized one" is precisely the harm); `_find_control_by_name`, whose partial match accepts any
`switch.*` merely *containing* the base name; the Shelly/ESPHome branches of
`_find_control_by_integration` (a Shelly auto-off timer, an ESPHome `restart` switch — every node
publishes one); and `_is_light_fixture` (count only primary switches). It reads the two **named**
values (`config`/`diagnostic`) rather than truthiness, so an unrecognised category keeps the load —
the filter may only act on a positive, known answer. Charger brand paths (KEBA/go-e/Easee) are out
of scope by construction: a charger's control can legitimately be categorized, and charger rows are
authoritative.
`_find_corresponding_power_sensor` now prefers an exact base-name match and keeps the fuzzy hit only
as a fallback. Absence of a registry entry filters **nothing** (a template switch / YAML helper has
no category to read — the #744 rule).
**The amplifier's control half — and why its rule is STRICTER than the meter's.** Fixing the
power-sensor direction left the same lossy match on the three *control* paths, where each loop
returned the **first** loose hit: `_find_control_by_name`'s partial match and the Shelly/ESPHome
branches of `_find_control_by_integration`. Both loose rules discard exactly the character that
names the channel — `_names_match` strips every digit (`shelly_kanal_1` ≡ `shelly_kanal_2`), and a
bare substring test fails one character later (`shelly_kanal_1` is inside `shelly_kanal_10`). The
harm is not symmetric with the meter's: a misbound sensor reports the wrong watts, a misbound
control **actuates the wrong circuit** — SEM shedding the freezer believing it is the towel heater.
So `_control_name_matches` requires the digits intact — the same base name, or the same name
extended at an `_` boundary (`_relay` names the channel, it does not renumber it) — and ranks exact
above boundary instead of taking the first hit. A looser candidate is refused **outright**, not
accepted as second best: "no control found", i.e. monitoring only, is the honest answer, the same
reasoning as `_find_control_in_device`'s strict filter. General rule: **the acceptable
false-positive rate of a name match is set by what happens when it is wrong** — read paths may
guess, actuation paths may not.
**The retirement half — a discovery filter is inert on an install that already ran.** Two facts
compose: `LoadManagement._discover_devices` early-returns once `_unified_registry_active`, so
pattern discovery never runs again on a live install; and `_sync_to_load_manager`'s #436 prune
**spares every `load_device_*` key**. The rows are immortal — a filter alone would have changed
nothing for the reporter. Hence `_prune_config_surface_lm_rows`, the third member of the prune
house pattern (charger-duplicate, ED-duplicate, config-surface): it deletes from `lm._devices` and
`_devices_shed`, spares authoritative charger rows and explicit `_service_registrations`, and
returns a bool so the sync **persists** the removal (the #744 lesson — a drop that isn't written
back is undone by the next restart).
**Where else it lives:** every discovery predicate that reads an entity_id, a domain or a state and
not the registry — control discovery, power-sensor pairing, sensor-role inference, the ED import.
Ask of each: does HA already record this as metadata?
**Guard:** `tests/test_781_config_switch_discovery.py` — the WLED shape refused, the diagnostic
switch refused, a plain metering plug still discovered, an unregistered switch still kept, the
control pick refusing a setting on the name path and on both brand paths (with the real relay still
found), channel 1 bound to channel 1's meter, and six retirement pins (drop, survive, charger,
service registration, ED-row out of scope, persisted by the sync).
**Sweep question:** for every "is this a candidate?" test in discovery — is the question being asked
structural while the question that matters is semantic? If HA carries the answer as metadata, a
name-shaped guess is not a heuristic, it is a wrong answer with a fallback. Refs #781 #744 #745 #436.

---

### 43. A re-baseline that forgets what it dropped FROM — GUARDED
**Symptom:** one member of an energy ledger reports an absurd figure — a heat pump at 15,508 kWh
*today* against a house total of 33 — and every other member is right. The balance check fires; the
device's own guard "worked".
**Root shape:** a monotonic counter that goes backwards is correctly recognised as a reset and
re-based, and there the guard's memory ends. The **next** reading is the lifetime total measured
against a baseline of zero: a positive delta, structurally indistinguishable from consumption, and
booked. The bug is not in the branch that fires; it is that the branch **discards the one number**
(the pre-reset high-water mark) that makes the next reading interpretable. A guard that handles an
event without recording it has moved the failure one cycle later, where it no longer looks like the
same event.
**Live catch (#782, @onkelfu, v2.0.0-beta.4):** `energy_dashboard_warmepumpe_energy_gesamt_2` booked
15,508.51 kWh in one ~10 s cycle — 5.6 GW — after its counter reset to 0 and returned.
**Closure:** two additions, deliberately separate. (1) A **physics** bound on any single delta:
`_MAX_PLAUSIBLE_LOAD_W = 100 kW` against the window the delta actually spans. This is explicitly
**not** class 40's error — `rated_power` is an *estimate about this device* and must never overrule
its meter; a house-circuit ceiling set far above every real appliance can only ever catch counter
pathology. (2) `_energy_counter_pre_reset_kwh` — the drop remembers its mark, so a recovered counter
books `now − mark`, the genuine consumption across the outage, instead of everything or nothing.
**The window is the crux.** Measured per-cycle it would refuse honest data: a 20 kW pump on an
hourly utility meter delivers 20 kWh in one 10 s cycle (7.2 MW by that arithmetic). So the window is
the time since the counter's **value last changed** — which also puts a #755-contract-1 blind
stretch *inside* the window (the value can't change while it's unreadable), and makes the outage
length available for free when a reset recovers. An **unknown** window (`None` — the baseline came
back from storage across a restart) never refuses: `_restore_device_energy` restores the baseline
without a timestamp, and booking that gap is the design.
**Where else it lives:** every re-baseline of a monotonic source — per-charger session energy,
lifetime solar counters, grid import/export statistics, the #755 recorder's own counters. Ask of
each: after the re-base, is the pre-reset value still reachable?
**Guard:** `tests/test_782_counter_recovery.py` — the reporter's exact sequence books 0.0; a genuine
0.5 kWh across a 30-minute outage is kept; a truly replaced meter counts from zero; an implausible
jump is refused, counted **blind** (not zero), and re-based so the next delta is trusted; and the
honest deltas — ordinary, and one spanning a 30-minute blind gap — are untouched.
**Sweep question:** for every guard that recognises "this reading is not a delta", ask what the
guard *keeps*. If it only re-bases, the next reading is the same event wearing a plausible sign.
Refs #782 #774 #768 #755.

### 44. Two implementations answer to one name; load order picks the winner — GUARDED
**Symptom:** a fix is written, reviewed, tested and shipped, and the behaviour on screen never
changes. The test is green because it pins the file that was edited. The user is looking at a
different file that answers to the same name.
**Root shape:** a first-wins registry (`customElements.define`, `semDefineCard`, a service
registration, a dispatch table keyed by string) reached from **two** shipped artefacts. Neither
errors: the loser's registration call hits the "already defined" guard and returns quietly. Which
one wins is decided by evaluation order, which for Lovelace resources is not ours to control — and
because it is *stable in practice*, the losing copy can go on collecting maintenance for months
without a single symptom. The bug is not the duplication itself; it is that duplication under a
first-wins registry converts an ordinary edit into a coin flip nobody sees land.
**Live catch (#784, 2.0 doc/release audit):** `sem-system-diagram-card` was defined by a 983-line
vanilla standalone *and* the 1814-line Lit version in `dist/sem-cards.js`, both registered as
Lovelace resources. The bundle always won — it defines at module evaluation, the standalone deferred
its whole body behind a `semReady` queue — so the vanilla copy had not rendered for anyone in a long
time. #699's atomic `power_snapshot` reads had been written into it, and only into it, together with
a test file pinning that copy: a shipped, reviewed, "guarded" fix that never reached a screen.
**Closure:** delete the loser, do not gate it. One tag, one implementation, and the retired URLs go
into `_legacy_bases` so an install that already registered them drops them instead of carrying a 404
forever. Then port whatever was stranded in the dead copy — and check what it *conflicts* with in
the survivor (#699's snapshot deliberately refuses to hold `battery_soc`; the Lit card carries the
#455/#488 60 s flicker hold the vanilla one never had, so the battery term is gated on SOC liveness
rather than taken outright).
**Where else it lives:** any name resolved by a first-wins registry — card tags, HA service names,
`semDefineCard` aliases, the brand→adapter tables, a strategy keyed by string. Ask: can two files in
this repo claim this key, and if they do, does anything *say so*?
**Guard:** `tests/test_card_registry_metadata.py::test_no_tag_is_defined_by_more_than_one_file` (one
tag, one file) and `::test_retired_top_level_resources_are_cleaned_up_on_upgrade` (a deleted file
must also lose its resource).
**Sweep question:** when a fix "doesn't take", stop debugging the fix and ask what else answers to
that name. A green test proves the edited file behaves; it does not prove the edited file runs.
Refs #784 #699 #455 #488 #219.

### 45. A guard whose boundary is lexical while the runtime's is reachability — GUARDED
**Symptom:** the lint is green, CI is green, and production logs the exact violation the lint exists
to prevent — naming a line the lint has read and cleared.
**Root shape:** the runtime rule is about *what executes where*. The guard was written about *what is
written where*. Calling a function runs its body at the call site, so "on the event loop" propagates
through calls without limit; the guard stopped at the enclosing `async def`. The gap is not an
oversight in the rule — it is the wrong boundary, and it widens exactly where the code is best
factored, because every helper extraction moves a call one hop further from the coroutine that
reaches it.
**Live catch (#785, campaign rig, 2.0):** after two blocking calls in `generate_dashboard` were
moved to the executor and the lint went green, HA still logged `Detected blocking call to open …
inside the event loop … at __init__.py, line 64` on every generation — the per-file cache-bust hash,
in a module-level helper the coroutine reached through a nested `def`. Two hops, both on the loop.
**Closure:** seed the guard on the coroutines and close over **direct calls** (`f()` and
`self.f()`), not on lexical nesting. The distinction that matters: a plain `def` is exempt when it
is *passed as a value* (`async_add_executor_job(_read)` — the fix we recommend) and on the loop when
it is *called by name*. Against the whole component that finds the one real call and nothing else —
a guard that floods gets muted, and a muted guard catches nothing.
**Where else it lives:** every AST guard in `tests/` that scores a call by where it is written —
`test_ev_control_fleet_reads.py` (fleet reads), `test_589_percharger_astguard.py`, the
`find_cheapest_hours` ratchet. Each is sound for a call written in the annotated function and blind
to the same call one helper away. Ask of each: is the property it guards *lexical*, or does it
propagate through calls?
**Guard:** `tests/test_no_blocking_open_in_event_loop.py` — three self-checks that the lint can fail:
a bare `open()` in a coroutine, a helper reached through a nested `def`, and `self._helper()` from an
async method; plus the negative, that the executor pattern is not flagged.
**Sweep question:** for every rule expressed as "not inside X", ask what the runtime's X actually is.
If X is a *state* (on the loop, holding a lock, inside a transaction), the guard must follow calls.
Refs #785 #783.

### 46. A value with one source of truth is restated as a literal at the site that uses it — GUARDED
**Symptom:** the same quantity reads differently depending on which function you ask, and the
constant that was supposed to settle it sits in `consts/` with almost no importers. Nothing raises:
each site is individually plausible, and the disagreement only shows as arithmetic that does not
reconcile — a plan that books more hours than it needs, a card that draws the wrong glyph.
**Root shape:** a value has an owner (a constant, a stored spec, a normaliser) and a call site
restates it instead of reading it. Restating is cheap and locally correct, so it spreads; the copies
then age independently. The tell is that fixing "the bug" at one site leaves the tree still wrong,
because the defect was never at a site — it is the *count* of sites. Two shapes seen so far:
**(a) the duplicated default** — `cfg.get(k, 32)` written thirteen times, six of them 32 and five
16; **(b) the discarded field** — a payload branch that hardcodes what its sibling branch derives.
**Live catch (#789):** `ev_max_current` has no config-flow field — nothing writes it (`build_view.py`
says so, verified live) — so *every* read is a read of its default, and the defaults disagreed.
`ev_control.py` disagreed with itself forty lines apart: `_compute_night_plan` planned the ceiling at
32 A while `_night_deliverable_kwh` sized the night's capacity at 16 A. On a 32 A charger the night
looked half as deliverable as it is, so SEM started earlier and booked more cheap slots than it
needed. `DEFAULT_MAX_CHARGING_CURRENT = 32` had been in `consts/core.py` since the initial release
commit with two importers. No over-current reached hardware — adapters clamp at `max_current_a` —
which is why it survived: the class hides *because* a downstream guarantee absorbs it.
**Live catch (#788), shape (b):** the service-registration branch of `get_devices_for_sensor` wrote
`"device_type": "service_device"` as a literal, discarding the kind the caller passed and
`async_register_service_device` had already normalised into the stored spec. The sibling branch for
directly-registered devices (`_surplus_device_row`) reads the real type. The card's icon map knows
`climate` and `heat_pump` but not `service_device`, so a correctly registered, correctly controlled
second heat pump rendered as a generic plug — and read to its owner as "it was not added" (#685).
**Live catch (#833), shape (c) — the duplicated *vocabulary*:** the owner need not be a scalar.
`charger_adapters/status_enum.py` is the single cross-brand map from a charger's status string to a
control class, built for #548 precisely so no brand needs its own reader. `sensor_reader.
_read_binary_sensor` nonetheless carried two private tuples of the same brand strings — 14 for
`ev_plug`, 2 for `ev_charging` — and they aged apart. The plug tuple never learned `paused` or
`locked`, so a Wallbox Commander 2 whose only cable signal is its status sensor read **not
connected** at its normal idle and its must-unlock state: SEM decided there was no car and never
started a session (discussion #821). The `ev_charging` tuple knew `charging` and `charging power on`
while the owner knew nine strings across five brands. Note the shape-(a) trap in the obvious fix:
adding two strings to the tuple would have satisfied the reporter and *preserved the count of
sites*. Note also that delegation is not free — `_NOT_CHARGING` deliberately holds both
cable-present idle states and cable-ABSENT ones, so cable presence had to become its own
enumerated axis (`_CABLE_ABSENT` + `is_cable_present`) rather than be inferred as
"anything not disconnected", which would have read an empty bay as occupied on OCPP, go-e and Ohme.
**Closure:** import the owner and delete the literal, at **every** site in one pass — and where a
literal is not a default at all, say so in the code rather than in a comment: `charge_stability`'s
`or 0` was a sentinel meaning "config is silent, ask the adapter", and became a conditional so the
only number left is the constant. #716 is the cautionary precedent: it fixed a hardcoded 230 V in
`_compute_night_plan` and left the identical literal in `_night_deliverable_kwh` forty lines below,
so the same issue had to be reopened as this one.
**Where else it lives:** every `consts/core.py` default with fewer importers than the key has
readers. `ev_phases` (3) and `ev_voltage` (230) are each restated ~15 times — they happen to agree
today, which is luck, not structure. Also every `_row`/`_payload` builder with more than one branch.
**Guard:** `tests/test_789_max_current_default.py` — an AST lint over the package for a max-current
key pinned to a bare number, in **both** syntactic shapes (trailing `.get(k, N)` argument and
`.get(k) or N`), plus a positive probe that the lint can fail on each shape and a negative that the
fixed form satisfies it. The two-shape point is load-bearing: the first draft understood only the
argument form and would have passed while three of the five 16s were still in the tree.
**Sweep question:** for a config key, grep the *readers* and compare their defaults before reading
any logic — if they disagree, that is the bug, whatever the issue says it is about. And when a key
has no write path, its default is not a fallback, it is the value.
Refs #789 #788 #716 #746 #685 #678 #833.

### 47. One word names two axes, so every reader picks the axis it expected — GUARDED
**Symptom:** a flag reads as an answer to a question it does not answer. Nothing misbehaves; the
cost is paid in diagnosis, by whoever reads the flag next — including us. It surfaces as a report
that quotes the flag back at you as evidence for a bug that isn't there, and as fixes aimed at the
wrong subsystem.
**Root shape:** two independent properties of the same row get folded into one boolean because at
the moment of writing they were always read together. The name can then only be honest about one of
them, and the other becomes invisible — but still decisive. Every later reader resolves the
ambiguity in favour of whichever axis their own question was about. The tell is a comment that has
to explain why the flag is *not* symmetric (`True` doesn't mean the opposite of `False`), which is
what a mixed axis looks like from inside.
**Live catch (#780):** `is_controllable` on a load row meant "a control handle was discovered
(**capability**) AND the user hasn't opted this load out (**permission**)", under a name that reads
as pure permission — while the actual permission the shed loop enforced was a *different* field,
`control_mode`. In #779 the reporter's diagnostics printed `is_controllable: true` for a device he
had set to **Mode: Off** while SEM was switching it off. Capability true, permission off, both
correct — and indistinguishable from the bug we were chasing. It cost real diagnosis time on both
sides, and the reporter drew the same wrong conclusion from it. #650 is the earlier scar: it had to
write a paragraph explaining why `controllable_override=True` is not the symmetric case of `False`.
The mixing also hid a real over-report: the "how much can we shed?" counters asked the mixed flag
and never the mode, so loads the user had set to Off were counted as sheddable capacity.
**Where else it lives:** any boolean whose name is an adjective about a device rather than an
answer to one question — `is_available` (reachable? or enabled?), `is_active` (running? or
permitted to run?), `enabled` on a controller (configured? or currently allowed?). Also every place
a user preference is AND-ed into a discovery fact "so callers don't have to".
**Closure:** split the axes into one accessor per question in a module that says what each one
means (`features/device_axes.py`: `has_control_handle` / `user_hands_off` / `may_actuate`), derive
the mixed key from them for one release so no outward reader loses its answer, and make the
diagnostics row print *both* axes plus the verdict — so the line that misled #779 answers its own
question. Write the axes at the point that knows them: discovery states capability, the user's
toggle states permission, and neither overwrites the other.
**Guard:** `tests/test_780_capability_vs_permission.py` — a source lint that the shed loop asks
`device_axes` and never the mixed key again, plus a parametrized equivalence test that a
legacy-only row reaches exactly the verdict the old expression produced (the migration must not
move a decision), plus a pin that the diagnostics row carries capability, mode, opt-out and verdict.
**Sweep question:** for any boolean on a device row, ask "which single question does this answer?"
If the honest answer needs an "and", it is two fields.
Refs #780 #779 #650.

### 48. A removed host API called past its removal, its failure swallowed as a benign case — GUARDED
**Symptom:** a feature that has always worked goes dead for users on a *newer Home Assistant* than
the one the integration was last tested against, with no error in our logs. It works in CI and on
the maintainer's box (older HA) and is invisible until a user on the new version reports it.
**Root shape:** HA deprecates a host API on a published schedule (`frame.report_usage(...,
breaks_in_ha_version="X")`) and later *removes* it. The integration keeps calling the removed form;
the call is wrapped in a defensive `try/except Exception: pass` written for ONE expected failure
(here "already registered from a previous load"), so the `AttributeError` from the now-missing
method is caught by the same broad clause and read as the benign case. The swallow converts a fatal
break into silence — the comment on the `except` actively misleads, asserting the only reason it can
fire. Two independent faults compound: calling a scheduled-for-removal API, and an `except` too
broad to tell "already done" from "gone". Distinct from class 31 (there the `except` is *narrower*
than the body can raise; here it is *broader*, and hides the fatal one).
**Live catch (#799, @HorizonKane, HA 2026.8.2, fresh 1.7.5 install):**
`_async_register_frontend_resources` served the component's dashboard dir with
`hass.http.register_static_path` — sync, blocking, **removed in HA 2025.7** (deprecated 2024.7). On
2025.7+ it raised `AttributeError`, the bare `except: pass` swallowed it as "already registered", the
static route was never created, the `sem-cards.js` Lovelace-resource URL 404'd, and *every* sem-*
custom element failed to define — the whole dashboard was nothing but "Custom element doesn't exist"
tiles. The www-copy fallback (`_async_install_card_assets`) is gated on the dashboard already being
generated, so it did not cover the fresh-install first view. **Closure:** migrate to the current
`async_register_static_paths([StaticPathConfig(url, path, cache)])`, and split the handler — the
reload-duplicate (`RuntimeError`/`ValueError`) logs at debug, anything else logs at WARNING and
continues (never swallowed silently, never blocking the resource registration below).
**Where else it lives:** every call into a HA host API with a removal schedule wrapped in a broad
`except` — `hass.components.*`, `async_get_registry`, the singular `async_forward_entry_setup`,
`async_add_job`. Swept 2026-08-18: `register_static_path` was the only *removed* API still called
(one site); `async_forward_entry_setups` (plural, current) is already in use. **Guard:**
`tests/test_frontend_resources.py::TestStaticPathServedViaAsyncApi` — a source lint that the
removed `register_static_path(` call form never returns (mentioning the name in a comment is fine),
plus a runtime assertion that the dashboard dir is actually served through
`async_register_static_paths` with the right `/local` url_path. **Sweep question:** for every host
API we call inside a `try/except`, has HA scheduled it for removal — and can the `except` clause tell
"already done" apart from "this method no longer exists"? A comment on an `except` that names the one
way it fires is a claim to verify, not a fact. Refs #799 #283 #785 #55.

### 49. Config-flow entity picker offers a domain the runtime validator rejects — GUARDED
**Symptom:** a field in the setup UI cannot be configured to a working value at all — the entity
picker only offers entities of one domain, while the code that consumes the choice hard-rejects
that domain and demands another. Both halves look correct in isolation; together they are a closed
loop the user cannot exit. Distinct from class 30 (there a key the runtime honours has *no* editable
surface; here the surface exists but its type filter excludes every value the runtime will accept),
and from class 34 (there a parser accepts a NAME but rejects a value SHAPE; here a UI selector offers
a DOMAIN the validator refuses). **Root shape:** the accepted-domain contract for an entity is stated
*twice* — once as the config-flow `EntitySelectorConfig(domain=…)` filter, once as the adapter's
runtime `entity_id.split(".",1)[0]` check (and the service it writes through) — and the two drift.
**Live catch (#807, @ab-elco-clal, Deye/2.0.0-beta.10):** the six `deye_program_<n>_time` slot fields
offered `domain="select"`, but `DeyeBatteryAdapter._validate_slot` rejects anything but `time.*`
("time entity must be time.*") and actuates via `time.set_value` — so no entity could satisfy both,
and the docstring + all 16 translation labels ("time-slot **select** entity") pointed the same wrong
way (class 24's mirror-drift, one layer out). A **second, paired fault:** save normalised the numbered
form fields into the `deye_program_groups` *list* and never persisted the flat `deye_program_<n>_<kind>`
keys, yet the reopen form re-populated each field from those flat keys — so every slot came back blank
(the class-19/save-restore-asymmetry twin: the write shape and the re-read shape disagree).
**Where it lives:** every `config_flow.py` `EntitySelector` whose value an adapter/reader later
validates by domain — the Deye slot fields (fixed: time→`time`), and by audit the rest of the Deye
step + `battery_discharge_control_entity` (all already `⊆` what the runtime accepts; charge/discharge
selectors offer a permissive subset, never a contradiction). **Closure:** the picker's offered
domain(s) must be a **subset** of the domains the runtime validator accepts, for every field — so the
UI can never advertise a value the backend refuses; and a form must re-read on reopen from the SAME
store its save writes (list-shape here, with the numbered keys as documented fallback, mirroring the
adapter's own `_program_slots` resolution order). **Guard:**
`tests/test_deye_config_flow.py::TestDeye807TimeSlotContract` — asserts every slot picker's offered
domains `⊆` `_validate_slot`'s accepted set (time→`{"time"}`, soc→`_NUMERIC_DOMAINS`,
charge→`_SELECT_DOMAINS`), that reopening repopulates each slot from the saved groups (and from the
numbered-key fallback), and pins the runtime contract (a `select.*` time entity IS rejected — so the
fix is to correct the picker, never to loosen the validator). **Sweep question:** for every entity
field in the config flow, is the domain the picker offers a subset of the domain the runtime accepts —
and does the form re-read on reopen from the exact store its save wrote? Refs #807.

### 50. A field narrower than the thing it describes — OPEN
**Symptom:** a form refuses a value the user's hardware (or SEM itself) considers legitimate —
"Value 150.0 is too large" — with no way to raise the limit. Often the page rejects a value **SEM
already stored**, so a working install cannot re-save its own configuration.
**Root shape:** every tunable's range is declared **twice** — a `NumberSelectorConfig(min,max)` in
`config_flow.py` and a `native_min_value/native_max_value` in `number.py` — with nothing deriving
one from the other. Agreement is a coincidence maintained by hand; drift is the default. A second
variant needs no entity at all: two *fields* that constrain each other (SEM's write ceiling ≤ the
BMS ceiling; emergency peak > target peak) with the relationship written down nowhere.
**Where it lives:** `config_flow.py` (45 number fields) × `number.py` (38 number entities); every
brand page with hardware limits — Deye currents, EV targets, peak ladder, charger min/max amps.
**Instances:** #717 (peak sliders capped at 15 kW on an 80 kW service) · #746 (every EVSE
ceilinged at 32 A; two runtime fallbacks disagreeing 16 vs 32) · #813 (options pages rejecting
their own stored values, twice) · #826 (Deye write ceiling 100 A against its own 200 A BMS field).
Four reporters, one shape.
**Closure (proposed, #828):** declare each range ONCE in a `consts/bounds.py` table keyed by config
key, with `at_most` / `at_least` for field-to-field constraints; `config_flow.py` and `number.py`
both build from it, so page/entity drift becomes impossible by construction rather than policed.
**Guard:** `tests/test_813_options_round_trip.py` exists but **covers 5 distinct settings out of 45 (11 %)**
— it can only pair fields that have an entity twin (40 have none), its entity parse reads 10 of 38
definitions, and its no-vacuous-pass floor (`>= 5`) is satisfied by duplicate matches of those same
5 keys, so it cannot detect that it has gone blind. Re-measure coverage with
`scripts/audit_bounds.py` before trusting it. **Sweep question:** for every number a user can set,
is its range stated in exactly one place — and where two fields constrain each other, is that
relationship written down anywhere a test can read? **Found by the audit, not by a reporter:** `battery_capacity_kwh` was declared on two pages with different minimums AND steps (min 5/step 1 vs min 1/step 0.5) — a 3 kWh pack saved on one was refused by the other; reconciled to the wider. Still open: `vehicle_min_current` page (1–32) is WIDER than its entity (6–32), the inverse drift — entangled with #752's request for sub-6 A when the control entity is the vehicle, so it needs a decision rather than a widening. Refs #717, #746, #813, #826, #828.

### 51. A value published at precision no human reads, or published twice where the later writer wins — GUARDED
**Symptom:** an entity rewrites itself every coordinator cycle while nothing a user could see has
changed. Costs recorder rows (SEM was **25 % of all state writes with 13 % of the entities**), and
reads as instability: a system visibly changing its mind for no reason.
**Root shape:** two variants of one mistake — publishing more than the thing means.
 * *Precision:* `surplus_distributable_w = 5965.464021148`, a deadline countdown at 2 dp (moves
   every ~36 s), session durations in tenths of a minute, a plan row stamped with
   `datetime.now()` to the microsecond, a currency figure at 17 digits. A watt is a watt.
 * *Two publishers:* the same key emitted by `SEMData.to_dict()` **and** by something merged in
   via `result.update(...)`. The later writer wins silently, so a unit test asserting the first
   one passes while the entity shows the other value.
**Why tests miss it:** a unit test asserts the losing publisher, and once `_unrecorded_attributes`
stabilises the stored blob the **database looks quiet too** — the state object still churns.
Every instance on 22.08.2026 was found by diffing LIVE attributes across cycles on a running
instance, never by the suite (7,700+ tests) and never by the recorder.
**Instances (#829):** session tickers · flow energies · energy-tip rotation · device map ·
`surplus_distributable_w`/`surplus_unallocated_w`/`battery_session_savings` · the forecast
dampening + correction factors (the two-publisher case) · plan-row `when` stamps · the EV
deadline countdown. Result: SEM's share of recorder rows **25 % → 6.1 %**.
**Guard:** `tests/test_829_single_publisher.py` — any key emitted by both `to_dict` and a
`result.update(...)` source must be in a SHRINK-ONLY allowlist (the #828 ratchet), and a new
merge source must be registered or the test fails. Proven to bite on an injected regression.
**Instrument:** `scripts/audit_live_churn.py` — samples a running instance N times and reports
attribute paths that churn while the state is unchanged, plus numeric precision above 2 dp. This
is the only thing that finds the precision half; run it after any change to what SEM publishes.

### 52. External integration's per-unit siblings collapsed to the first match (fleet read as one) — GUARDED
**Symptom:** a fleet quantity sourced from an EXTERNAL integration reads as a single unit's value —
a multi-string solar install's forecast is far too low because only one string is counted (#838,
@HorizonKane: "I have one Forecast set up per String. SEM seems to only use one of them instead of
summarising all strings"). No error: the one value it does read is valid, just partial.
**Root shape:** SEM resolves ONE entity per role from an integration that models a fleet as N
sibling entities, then reads that one as the whole. Forecast.Solar and Open-Meteo register **one
config entry per plane**, each emitting its own `energy_production_*` sensor whose unique_id ends in
the same suffix (`{entry_id}_{key}`, entity_id disambiguated `_2`/`_3`); the registry scan kept only
the first (`role not in resolved`), so the fleet forecast = one plane. Distinct from class 16 (that
one is SEM's OWN per-unit sensors suppressed by a fleet-override branch); this is an *external*
source's per-unit entities dropped at the resolution boundary. Cousin of class 5's open
"multi-unit partial-availability sums silently under-report" sibling. **Where it lives:**
`coordinator/forecast_reader.py` — the suffix-matched platforms (`forecast_solar`, `open_meteo`,
which share the `else` branch of the registry scan). **Watch:** Solcast is the deliberate
exception — it is matched on an EXACT unique_id that is already the site/account total (per-site
Solcast sensors are intentionally not matched), so it must stay single; summing it would double-count.
**Closure:** the registry scan returns `{role: [entity_id, ...]}` (`_registry_entity_groups`) — the
suffix branch collects EVERY plane, the exact-match Solcast branch stays single-element — and the read
path SUMS a role across its planes (`_read_role_energy`/`_read_role_power_w`) while `_entities` keeps
the representative first entity (byte-for-byte the pre-fix value) for peak-time parsing. The FIRST-match
shape lived in detection too — `_locate_integration` and the cached-source validity check keyed off the
representative plane alone, so a dark FIRST string would drop the whole array — so both were made
plane-aware (a source is usable while ANY plane's `forecast_today` is available). A partially-available
multi-plane install therefore sums the available planes rather than zeroing, whichever plane is dark
(matches the single-entity default contract). **Guard:**
`tests/test_838_forecast_multi_string.py` — two Forecast.Solar strings sum (today/tomorrow/remaining/
power_now), the Open-Meteo sibling sums, a single plane is unchanged, a Solcast total is read once
(not doubled), a non-representative dark plane still sums the rest (three planes → discriminating,
fails on revert), and a dark FIRST plane does not hide a live sibling. **Sweep question:** for every
quantity SEM reads from an external integration, does the integration model that quantity as ONE
entity or as N siblings that must be aggregated — and does the resolver (read AND detection) take the
first, or all of them? Refs #562 #687 #819 #838.


### 52. A summary statistic chosen without asking which tail hurts — GUARDED

**Root shape:** a distribution reduced to its mean when the decision is asymmetric. The mean
answers "what happens typically"; a decision that is cheap in one direction and expensive in the
other needs a percentile, and *which* percentile is set by which tail hurts.

**Instance (#778):** `ForecastLedger.trust()` returned `min(1.0, mean_ratio)` — how the forecast
performs on average. Backfilling .175's own five months of history produced **139 settled
forecast/actual pairs** and showed the mean was 1.050: an *unbiased* forecast. The spread was
p10 0.514 / p90 1.502. Under the mean rule SEM would plan against the full forecast and the day
would deliver less on **58 of 139 days (42 %)** — each one a battery sold against energy that
never arrived. Now p20, with `accuracy()` keeping the mean as the bias diagnostic it actually is.

**What makes it hard to see:** the mean is not *wrong*. It is a correct answer to a question
nobody asked. Every unit test passed, the number looked reasonable, and the codebase already
contained the correct argument for the OTHER side of the same ledger —
`measured_capacity.NEED_PERCENTILE` takes a high percentile of overnight draw, with a comment
explaining that "being short is not symmetric with being generous". The mirror image was simply
never written.

**Why tests miss it:** a test that asserts `trust(uniform_ratios) == expected_mean` passes for
both rules. Only a REAL distribution — wide, unbiased, skewed — separates them, and the suite had
no reason to contain one.

**Guard:** `tests/test_778_trust_is_conservative.py` — an unbiased-but-volatile sample must not
yield full trust, a reliable one must, and the measured .175 shape is pinned as a regression case
with its own mean asserted so the counter-example cannot silently stop being one.

**Where else to look:** anywhere SEM averages a series to make a spending or safety decision —
tariff level classification, the dampening factor, EV session estimates, load calibration. The
question to ask each one is not "is the average right" but *"which direction is expensive, and
does this statistic protect it?"*

### 53. An arithmetic identity nothing ever checks — GUARDED

**Root shape:** two quantities SEM publishes that are related by physics or definition, with no
assertion anywhere that the relation holds. Both look plausible alone; only together are they
impossible.

**Instance (#778):** the battery cannot send out more energy than it discharged, yet .175
published `daily_battery_discharge_energy = 4.06` alongside outbound flows of
`9.39 + 0.19 + 4.38 = 13.96` — **3.4× conservation**. PROD, on identical code, read 3.04 ≤ 4.04.
So the violation was environmental, and *nothing in SEM noticed in either direction*. The damage
path was silent: #800's night recorder integrates `battery_to_home_w` into `drain_kwh`, #778
builds its overnight-need envelope from those drains, so an inflated flow inflates what SEM
believes the house needs, the budget stays at zero, and the card reports **"holding"** — a
sentence that reads as a considered decision rather than a broken input.

**The fix shape — gate, do not clamp:** a violating night is recorded, is visible, and is not
`trainable`. Repairing the number would hide a real misconfiguration; the same treatment the
sampling-gap tolerance already gives an unreliable night.

**Guard:** `coordinator/flow_invariant.py` + `tests/test_778_flow_invariant.py`, with the live
PROD and .175 readings pinned as the balanced and violating cases.

**Where else to look:** every published identity SEM never asserts — `home = solar + import +
discharge − ev − export − charge` (the balance the `max(0, …)` clamp hides), per-charger draw
summing to `ev_power`, daily energies summing to their monthly, flow energies summing to their
source counter.

### 54. A dict default defeated by a key that exists holding null — GUARDED

**Root shape:** `config.get("key", SAFE_DEFAULT)` returns the default only when the key is
**absent**. A key that is present holding `None` returns `None`, and the safe default never fires —
on precisely the installs that never configured the setting, which is the population the default
exists to protect.

**Instances (#778):** PROD carries `battery_reserve_soc: None`. So
`config.get("battery_reserve_soc", 20)` handed `spendable_budget` a `None`, which resolved the
static floor to **0.0** — the user's "never below this, ever" backstop silently absent, on the one
install with a real battery. Sweeping for siblings found `forecast_pessimism` doing the same in the
same unsafe direction: missing resolved to `1.0` (no margin) against a documented `1.2`, so an
install with a null in options quietly spent ~9 % more than one never configured at all.
`battery_discharge_efficiency` was already correct (`_num(x) or 0.95`) — which is half the value of
a sweep: *"already correct" is only knowable by looking.*

**Why tests miss it:** every unit test constructs its config explicitly, so the key is either
present-with-a-value or absent — never present-holding-null. That third state is created by the
options flow and by `set_option`, i.e. only ever by a real install. The function's own signature
default (`static_floor_pct=20.0`) reads as protection and provides none, because the caller passes
an explicit `None` straight past it.

**The distinction that matters:** an explicit `0` is a CHOICE ("spend it all"); `None` is an
ABSENCE ("nobody said"). Collapsing the second into the first is the whole bug. The fix names what
silence means, once, in the function — never at each call site, which is how the two drifted apart.

**Found by:** backtesting against a real install's config, not by reading code. The suite was green
throughout.

**Guard:** `tests/test_778_spendable_budget.py::TestSilenceMeansTheDocumentedDefaultEverywhere` —
every tunable arriving null must not out-spend an install carrying none of them.

**Where else to look — and the sweep was RUN, 23.08.2026.** The exposure is checkable against real
data rather than by reading: take a live config entry, list every key holding `None`, and
cross-reference against every `config.get(k, default)` in the codebase. PROD carries **12 null
keys**; exactly **4** call sites rely on a default for one of them:

| site | key | verdict |
|---|---|---|
| `coordinator.py` (spendable budget) | `battery_reserve_soc` | **HAZARD** — fixed |
| `coordinator.py` (spendable budget) | `forecast_pessimism` | **HAZARD** — fixed |
| `coordinator.py:2785` | `vehicle_soc_entity` | safe — default `""`, consumed as `if entity:`, and `None` is equally falsy |
| `coordinator.py:4237` | `vehicle_range_entity` | safe — same shape |

So the class has **two** live instances and both are closed. The pattern that made the last two
safe is worth copying: a default that is only ever tested for truthiness cannot be defeated by a
null, because both fall the same way. The dangerous shape is a default that carries a NUMBER the
arithmetic then uses.

**Instrument:** `scripts/audit_null_defaults.py --host … --key …` reads a live install's null keys,
cross-references every `config.get(k, default)` in the tree, and exits non-zero on any hazard — so
it can gate CI against a reference config. Against PROD on 23.08 it reports **0 hazards, 2 safe**.

Re-run it against any install's config before trusting the table above on a different deployment:
the null set is per-install, and a key null on one machine may be set on another. That is also why
this is an instrument rather than a static test — the hazard lives in the CONFIG, not in the code.

### 55. Two measurements compared across different reset windows — GUARDED

**Root shape:** an invariant compares quantity A against quantity B, and the two accumulate over
different windows. Both are individually correct; the comparison is meaningless. Worse, it usually
fails in the direction that looks like caution, so the code appears to be working.

**Instance (#778/#800):** `flow_invariant` checked that the night's attributed flows fit inside the
battery's discharge. The flows accumulated from dusk in `BatteryNightTracker` with **no midnight
reset**; `daily_battery_discharge` is keyed `f"{category}_{today}"` with `today = now.date()` —
`energy_calculator.py`'s own comment says *"Midnight-based reset — matches HA Energy Dashboard."*
Every real night spans midnight. From 00:00 the counter restarts near zero while the tracker keeps
climbing, so the two diverge by however much discharged before midnight, and a 15 % tolerance trips.

**Why it was invisible:** it **failed safe.** `flows_balanced` latches → `trainable` false →
`expected_overnight_need` and `measured_capacity` refuse the night → the #778 budget stays at zero
and the card says *"holding"*. Nothing breaks, nothing errors, no user is harmed today — the
feature simply never activates, and the sentence it shows while not activating reads like a
considered decision. A gate written to reject the occasional impossible night would have rejected
**almost every night**, forever, on real hardware.

**Why tests missed it:** every test passed a **constant** `battery_discharge_kwh`. A constant has no
reset window, so the mismatch cannot exist in the fixture. The bug lives entirely in the
*relationship between two clocks*, and a unit test that supplies both sides as literals has quietly
removed the only thing under test. Live evidence pointed at it (.175 read 4.06 vs 13.96) and was
misattributed to a mock battery — which was ALSO real, so the arithmetic confirmed a partial
explanation and the search stopped.

**The fix shape — compare instantaneous, not cumulative.** Power against power, per sample: there is
no window, so there is nothing to mismatch. The price is a duration tolerance (two sensors read
microseconds apart disagree constantly, and one bad sample must not condemn a ten-hour night), and
the gain is strictly more sensitivity when it does fire — a sustained impossible flow appears in
every sample rather than being averaged into a daily total.

**Guard:** `tests/test_800_flow_invariant_window.py` — a ten-hour simulated night at steady,
legitimate discharge must stay balanced (the regression), a sustained impossible flow must still be
rejected (not softened into uselessness), and a single bad sample must not condemn a night.

**Where else to look — anywhere SEM compares an accumulator to another accumulator.** The reset
windows in this codebase are genuinely different and genuinely undocumented at the comparison sites:
midnight (`daily_*`), sunset→sunrise (the night tracker), per-charger deadline (`daily_ev_energy`,
#279), monthly, lifetime (inverter counters), and "since SEM started" (session totals). Any
assertion, diagnostic or Repair that puts two of those on opposite sides of an inequality is
suspect. The question to ask is not "are both numbers right" but *"do these two zero at the same
moment?"*

### 56. A mode-qualified fallback register bound as the live control surface — GUARDED
**Symptom:** SEM drives a charger through a register the hardware only honours when it is
DISCONNECTED — a limited-write "offline" fallback — instead of the live "online" limit, so every
current command lands on a knob not meant for frequent writes (and on some firmware is ignored until
the box loses its server). No error: the offline register is a real, writable `number.*`, correctly
united, and the charger accepts the write — it simply governs the wrong connection MODE.
**Live catch (#886, @Azlinon, 2.1.0-beta.3):** JuiceBox over JuiceBoxProxy/MQTT exposes TWO
current-limit numbers — `number.juicebox_max_current_online_wanted` and `..._offline_wanted`. The
`ev_current_control_entity` brand-hint matched every `number.juicebox*` and took the LAST match
(`_discover_from_hints` is last-wins), so entity ORDERING decided which mode SEM drove; the
reporter's install bound the offline one.
**Root shape:** a detection matcher resolves an ACTUATION entity by a name/shape test too loose to
separate two siblings that differ only by a MODE qualifier (`online`/`offline`, `boot`, `failsafe`),
then picks by ordering (first-/last-wins). Cousin of class 42's control half — *the acceptable
false-positive rate of a name match is set by what happens when it is wrong, and a mis-bound control
actuates*; here it actuates the disconnected-mode fallback. Cousin of class 47 — one register name
carries two axes (which limit AND which connection mode) and the matcher reads the axis it expected.
**Where it lives:** every `ev_current_control_entity` resolver in `hardware_detection.py` — the
`_BRAND_HINTS` rows (juicebox, garo, wattpilot, heidelberg) AND the hand-written brand functions
(go-e, OpenWB, OCPP, Wallbox, Peblar, …), all of which pick a `number.*` on a loose `current`/`amp`
substring; any integration that also publishes an offline/failsafe limit is exposed.
**Closure:** one brand-agnostic guard, `_reject_offline_current_control`, at the single choke point
every brand's config flows through (`discover_all_ev_chargers_from_registry`), mirrored on the
diagnostics report path and the generic prober: if the bound current control names an `offline`
fallback, swap it to the `online` twin among the same device's numbers, else DROP the binding —
monitor-only beats driving the wrong knob (fail-closed, the actuation-path rule). The JuiceBox hint
also now requires the number to name a current (`current`/`amp`), so a non-current juicebox number
can never be bound as the control. Because the guard is at the choke point and knows nothing about
JuiceBox, the whole class is closed for every current matcher, hand-written or hinted, and for the
next brand. **Guard:** `tests/test_886_offline_current_control.py` — the reporter's two-number
JuiceBox binds `online` regardless of registry order; an offline-only charger drops the binding
rather than actuating it; a plain single `max_current` is untouched (no #816 regression); and the
guard holds for a hand-written brand shape too, so the closure is at the class level, not the
instance. **Sweep question:** for every entity a detector binds to an actuation role, can the
integration expose a SECOND entity that fits the same shape but governs a different mode/state — and
does the matcher separate them, or pick by ordering? Refs #886 #816 #683 #698.

### 57. Belt-and-suspenders actuation — a wrapper does the action AND delegates to a layer that does it again — GUARDED
**Symptom:** one logical actuation reaches the hardware TWICE, a few milliseconds apart. No error, no
wrong value — the SAME correct command, sent twice. It surfaces only where a downstream watcher is
edge-sensitive: an HA automation that stops the car on SEM's 0 A write fires twice, and the second
fire (or SEM's own duplicate-detection) produces a burst of warnings. **Root shape:** the exact
MIRROR of class 25 (mutual delegation → *neither* layer acts). Here a wrapper performs the primitive
itself AND then calls a higher-level method that performs the same primitive as its own universal
fallback — so *both* fire. Each is individually defensible ("set 0 A to stop" / "stop_session tidies
up the session"), and reviewing either in isolation reads as correct; the defect is in the
composition. A same-value de-dup that *looks* like it would collapse the second write can be silently
inert — here `_set_current`'s heartbeat de-dup is gated on `is_active` (`_status.state == ACTIVE`),
which the EV reconciler path never sets, so the guard was always False during a stop. Relying on that
de-dup would itself be a workaround; the fix removes the redundant call so ONE layer owns the action.
**Live catch (#894, @DigitalOptics, Fronius / "Other" charger, 2.0.0):** with no start/stop entity,
`GenericAdapter.command_disable` / `command_idle` wrote `_set_current(0)` directly AND called
`stop_session()`, which — finding no brand stop mechanism — falls back to `_set_current(0)` itself.
Two 0 A dispatches per stop. `KebaAdapter` was always correct: it delegates to `stop_session()` alone.
**Where it lives:** the charger adapters' stop paths (`coordinator/charger_adapters/generic.py`
`command_idle`/`command_disable`, inherited by `WallboxAdapter`); the same shape is latent anywhere a
`command_*` wrapper both actuates and calls a session/teardown method that re-actuates. **Closure:**
`stop_session()` is the single owner of the stop — `command_disable` delegates to it outright (like
KEBA), and `command_idle` delegates when a session is open, writing 0 A directly ONLY when there is no
session to tear down (the two are mutually exclusive, never sequential). **Guard:**
`tests/test_894_stop_sent_once.py` — one stop call → exactly one 0 A dispatch, asserted end-to-end
through the REAL `command_disable`→`stop_session` composition (spying `_set_current`), for generic AND
KEBA, plus a branch-safe AST check that `command_disable` never calls `_set_current` directly.
**Sweep question:** for every actuation wrapper, does it perform the hardware action itself *and* call
a method (`stop_session`, `park_off`, a teardown/cleanup) that performs the same action — and if a
de-dup is supposed to save you, is its gating predicate ever actually true on this path? Refs #894 #25 #315 #487 #627.

### 58. A blind input read as zero in the OPTIMISTIC direction — GUARDED
**Symptom:** a security layer relaxes precisely when it is blind. The peak slot tracker integrated an
`unavailable` grid sensor as 0 W (`float(x or 0.0)`), so two modbus dropouts inside a slot averaging
8 kW *manufactured* headroom and the guard released at 5.9 of 6.0 kW; the same reader's 0.0 made the
guard's "grid minus this charger" credit read the whole house as absent. **Root shape:** classes 12/
#875/#902 already say "unread is not zero"; this class is the sub-case where zero is not merely
wrong but *permissive* — the fallback lands on the side that lets the defended limit be breached.
A hold ("keep doing what you were doing") is the honest fallback for a steering read; for an
INTEGRAL the honest fallback is zero-order hold of the last valid sample plus a tighter cap while
blind, never zero. **Live catch (#906, PROD 02.09):** slot 20:45–21:00, month peak 1.11 → 6.59 kW.
**Closure:** `PeakSlotTracker.update(now, None)` holds `_last_w` across the gap and flags `blind`;
`slot_allowed_import_w(..., blind=True)` caps at the target; `FleetContext.grid_import_known` lets
the guard charge the house's held draw against the allowance. **Guard:**
`tests/test_906_blind_meter_slot_guard.py`. **Sweep question:** for every fallback value, ask which
DIRECTION it errs in — does the default open a gate, widen a budget, or lower a floor? Refs #906 #875
#902 #818.

### 59. A limit smoothed like a preference — GUARDED
**Symptom:** the guard says 10 A, the wire carries 14 → 12 → 12 → 10 over two minutes. **Root
shape:** offer-steadiness (median window, 2 A ramp, 30 s debounce, dropout hold) is applied to every
setpoint change regardless of *why* it changed. Steadiness protects the car from budget wobble; a
limit-driven DOWNWARD move (slot guard cap, shed order) is billed for every cycle it is late, and the
smoothing turned a one-cycle clamp into a two-minute overrun that set the month's peak. **Live catch
(#905, PROD 02.09).** **Closure:** `ChargerDecision.capped_by_limit`, stamped by `clamp_to_peak_slot`
and the shedding clamp; `ChargeStability` writes a capped downward target in the same cycle (no
median, no ramp, no debounce, never held above it by the blind-cycle hold); the ramp governs only the
way back up. **Guard:** `tests/test_905_limit_clamp_lands_now.py`. **Sweep question:** wherever a
smoother sits between a decision and an actuator, can it tell a *preference* from a *limit* — and
does it let the limit through? Refs #905 #864 #747.

### 60. One number for a per-setpoint quantity — GUARDED
**Symptom:** the plan asks 14 A for a 5.3 kW block on a car whose own measured table says 14 A buys
8.7 kW. **Root shape:** #846 established that a car's W/A is a function of the SETPOINT (8 A → 394,
16 A → 389 on a tapering car), and built a per-bucket ladder with `amps_that_fit`. One consumer
(`ev_overlay`) kept converting with a single W/A lifted from the max-amps bucket — `ceil(watts /
wpa)` — so a low bucket at 16 A produced an over-ask the table itself contradicted. The slot guard
used the ladder; the plan floor did not; the guard then had to undo the plan's arithmetic every
cycle. **Live catch (#904, PROD 02.09).** **Closure:** `ev_overlay(..., wpa_table, nominal_wpa)`
walks the ladder (largest setpoint whose predicted draw fits the block); nameplate ceil remains the
no-table fallback. **Guard:** `tests/test_904_overlay_walks_the_ladder.py` + the #846 structural
test now counts the overlay sites. **Sweep question:** for every `x / watts_per_amp` or
`amps × wpa`, is the W/A the bucket for THOSE amps, or one number standing in for the curve? Refs
#904 #846 #716.

### 61. A hold that cannot tell a steering read from a verdict — GUARDED
**Symptom:** target reached, decide says idle, and "inputs degraded — holding 8A" re-issues the charge
on every dropout; the reconciler's 4-consecutive-idle grace never completes; the car charges past
its target from the grid in a mode that never grid-charges at night. **Root shape:** the #818 hold
("a cycle that cannot see must not steer") assumed every decision it overrides was DERIVED from the
blind inputs. A night verdict is derived from the charger's own energy counter and the planner; the
hold rewrote it anyway, and the median smoother delayed the idle by half a window on top. **Live
catch (#907, PROD 02.09).** **Closure:** the hold is a day-only device (`and not night`); at night
the planner's raw verdict bypasses the median — the same rule the deficit bridge already followed.
**Guard:** `tests/test_907_night_idle_survives_a_blind_cycle.py`. **Sweep question:** for every
"hold the last value" fallback, which decisions can reach it that do NOT depend on the missing
input — and are they exempt? Refs #907 #818 #552.

### 62. A window filter sized for a one-sample fault, blind to the sensor's own sibling — GUARDED
**Symptom:** the diagram shows EV 120 W under a car drawing 5 kW; `home_consumption` jumps by the
missing 5 kW for a cycle; every consumer of the balance (redirect strikes, shedder, day model,
taper detector) sees a phantom house spike. **Root shape:** the median-of-3 was built for the KEBA's
ONE-read UDP blip; a report-timing blink that spans two SEM reads defeats it, and the median's own
lag then repeats the low for a second cycle. Meanwhile the box's status sensor said `charging` the
whole time and nobody asked it — a sibling reading that names the sample as impossible. **Live
catch (#910, PROD 03.09, two samples).** **Closure:** a status-gated hold above the median: while the
charger's own status says charging and the read collapses below 5 % of the last accepted value,
hold it for at most two cycles and mark the readings; the hold lives on the STATUS (a flip ends it
at once), never on the clock, and no status sensor means no hold. **Guard:**
`tests/test_910_keba_blink.py`. **Sweep question:** for every smoothing window, what is the longest
fault it was sized for, and which sibling sensor could have vetoed the sample outright? Refs #910
#902 #818.


### 63. A per-domain excuse for silence where the source's liveness was the question — GUARDED
**Symptom:** the frozen-sensor Repair fires for an export sensor at 0 W in the afternoon and for an
idle battery — on an integration that polls every 15 s. **Root shape:** the detector reads
``last_reported``, assumes every integration writes every poll, and when that broke (#851, Growatt
asleep at dusk) the fix was a predicate for that domain (solar + ~0 + sun down). The next case was
export + importing, then battery + idle: a predicate per domain, each an excuse for one kind of
silence, none asking the actual question — is the SOURCE alive? **Live catch (#912, FoxESS).**
**Closure:** one rule — a sensor is frozen only if its own integration has gone quiet; a sibling
entity of the same config entry reporting within the threshold vouches for the reading. The domain
predicate survives only for the integration that genuinely powers down (the whole entry quiet, the
sun explains it). **Guard:** `tests/test_912_frozen_sibling_rule.py` pins the rule is one place.
**Sweep question:** wherever a heuristic explains away a signal per domain, what single property of
the SOURCE would answer all of them? Refs #912 #851 #611.

### 64. A hand-maintained vocabulary where the source publishes its own — GUARDED
**Symptom:** every brand SEM can name was typed by hand after a user filed an issue; a near-miss
integration detects nothing instead of something reviewable, and `_suggest_select_with_options`'s
"identify the entity by its options" trick works for exactly the two brands whose option lists
somebody transcribed. **Root shape:** detection matched the *user's* entity ids with regexes while
Home Assistant already records the *author's* semantic label — `translation_key` — and every
integration publishes that label in its own repository. The vocabulary existed upstream all along;
SEM was re-deriving it one live install at a time. **Closure (#915):** an offline crawl mines each
energy-shaped integration's declared entity keys into a generated roster, and every runtime use is
an INTERSECTION with the local registry — it can name a domain, propose a role for an entity the
user already has, and ask the registry the semantic question before regexing a name. It can never
invent an entity, and it structurally cannot carry a status, an evidence string or a sign
convention. **Guard:** `tests/test_915_roster_is_not_a_claim.py` (a support claim is
unrepresentable), `tests/test_915_roster_rediscovery.py` (the miner re-derives four facts SEM
learned from four live installs, and invents nothing for a brand that exposes nothing).
**Sweep question:** where else is SEM maintaining by hand a fact its source already publishes —
and would reading the source be a hypothesis or a claim? Refs #915 #848 #814 #530.
