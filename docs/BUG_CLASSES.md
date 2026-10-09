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
+ the missing-`last_reported` fallback test. **Home figure (#1047, PROD 04.10 15:26):** home is the
remainder of the balance, so an input whose EVERY read is dark entered it as the reader's 0.0 while
the input's own entity kept its last value — a battery charging 3.9 kW went dark and the SHOWN home
read the whole 4.7 kW of solar for 20 s. The #237/#444 hold catches a dip only; its 2-cycle spike
guard had been spent by the dip hold first. **Closure:** `SEMCoordinator._hold_shown_home` sets
`PowerReadings.home_shown_w` — the last home shown — while any input's entity is still holding: dark
now and read live within `SENSOR_DARK_READ_GRACE_S` (same `<=`), each input on its OWN clock (review
2: one clock from the last fully-live cycle released home mid-way through blinks that overlap in
turn, and an inverter dark all night blocked every later hold); the held value itself expires after
two graces, so a chain of blinks cannot freeze home for good (review 3). `to_dict` publishes it, the #891
house-meter gap compares it, and the #699 snapshot treats it as incoherent (the cards keep the last
set that added up). It holds the HOUSE, not
the dark input, and `home_consumption_power` is left alone. **Why not hold the input inside the sum
(challenge record, #1047):** the first cut did, and the review measured it. Home STEERS — the EV budget
is `solar − home − battery_charge`, and a held home beside the raw 0 W battery charge was a 3.9 kW
surplus that was not there (a start after the 60 s delay); a held grid beside a live EV ramp loosened
the #906 blind-meter peak guard by the ramp; a held battery beside falling solar drove home to 0 W. A
balancing term moves with everything else, the house does not. The import/export and charge/discharge
halves blank with their input (the `grid_active_power` rule). **Guard:**
`tests/test_1047_home_holds_a_dark_input.py` — the PROD replay through the real reader, smoothing,
hold, publish and snapshot; steering untouched (no phantom surplus); the grace edge; overlapping
blinks; an input dark all night; never-read; a cycle-order pin; and an AST pin that every
`*_unavailable` flag `to_dict` blanks a power input on is a flag the hold listens to. **Asleep at
night (#1065, RienduPre, Grott/Growatt):** an inverter that powers down at dusk stops sending and its
entity holds the last value — 8.1 W, published as solar (total, flow, per-string) all night. #851's
predicate already called that reading asleep, but only the WARNING asked it; the value path never
did. **Closure:** one predicate (`SensorReader._near_zero_at_night`) for both sides, and
`_asleep_at_night` reads 0 W when every entity behind a solar reading stopped reporting for the frozen
threshold, ≤ 25 W, sun below the horizon. The verdict belongs to the REPORT: it holds until the
entity's state is written again, so sunrise (no new data) does not turn the dusk report back into
production;
the W3 warning does not share the hold, because a report that never comes in daylight is the fault
it exists for. The value rule does not ask `_source_is_alive` (class 63): every MQTT device shares
the broker's config entry, so any live MQTT entity would vouch for a sleeping inverter. Every
fleet/per-inverter solar read goes through `_read_solar_power`, every per-string read (direct or
V+I) through `_read_pv_string_source`. **Guard:** `tests/test_1065_asleep_solar_reads_zero.py` — the
reporter's night through `read_power`, sunrise before the inverter wakes (V+I: both halves), every
solar read path, the kept cases (a stall first seen in daylight, > 25 W, fresh, no sun, one live V+I
half, unreadable stamps), one threshold for warning and value, and an AST pin over the whole package
that no `_read_sensor`/`_read_sensors_sum` solar or `pv_…` read — literal, keyword, f-string or
variable label — lives outside the two doors (a probe proves the walker catches each; aliases and
`getattr` are not seen). **Open siblings:** the frozen value still *feeds* the
balance when what it should be is not knowable (daylight, grid, battery, solar above 25 W: warned,
not changed); the #1065 hold lives in memory, so a restart between sunrise and the inverter waking
shows the dusk value again, and the W3 Repair text at dawn still says the stale value is used while
a held report reads 0 W; multi-unit partial-availability sums silently under-report
(audit W6; the lifetime seed's half closed by #1043, see class 52) — one dark unit of N is still 0 W
in home AND in the published total; the flow figures and the daily home energy still integrate the
dark cycle's raw home (they share the steering figure; the #771 partition check ties them together);
the steering home itself still reads a dark battery as idle (safe for the EV budget — the meter
answers — but the discharge limit home/n is wide for the gap; holding it needs the battery charge
held beside it); an EV power dropout is not in the dark tally at all (its own #910 hold + the 2-cycle
spike guard, whose count the dip hold can spend first). Refs #274 #461 #589 #611 #1047 #1065.

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

**Instance 8 — a temperature gate on the start only (#1062).** `HotWaterController.activate` refused a start at the solar target, but nothing stopped a boiler already running: a relay switched on at 50 °C heated past a 55 °C target for as long as the surplus lasted. A water_heater or climate tank was safe only because its own thermostat holds the setpoint SEM wrote. **Fixed:** the switch boiler's `stop_condition_met` is true once a real reading reaches the active target (solar target, or the minimum in the vacation surplus dump), so the stop block and `compute_load_intent` clause 3 end the run. SEM's own stops skip a Legionella cycle: this target and a banked comfort band both sit below the disinfection target, and `check_legionella_cycle` never starts a cut run again (the review caught the band case — the class 125 fix gave the band a thermometer). A stop entity the user set still ends the cycle, as before. **Guard:** `tests/test_1062_hot_water_fields.py::TestTheSurplusPassStopsIt` (real `SurplusController.update`, the Legionella cases included).

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
**Fourth instance (#1071, 08.10.2026) — two rules pick the owner:** a battery's mode/reserve
is stored twice — the scalar \`battery_mode\`/\`battery_reserve_soc\` (the one global
\`select.sem_battery_mode\`/\`number.sem_battery_reserve_soc\`) and the idx-aligned
\`battery_modes\`/\`battery_reserve_socs\` lists (the per-battery controls). The platforms
picked the control by the slugs found at setup; \`_per_battery_config\` picked the store by
"is a list slot set?" plus the LIVE count. A one-battery install with a leftover list (.175:
\`['auto','auto']\`) showed the global select and the list shadowed every write — select
\`force_charge\`, SEM \`auto\`. The same split hid two more: per-battery controls on a
one-battery cycle (cold-start ED, #274) read the stale global key (#531's hazard), and a global
select (two-sensor batteries, #553, never get per-battery controls) did nothing once two were
live. And an UNSET reserve showed 20 % (\`DEFAULT_BATTERY_RESERVE_SOC\`) while the runtime sold
to 0 %. **Closure:** ONE decision — \`coordinator/battery_controls.py::discover_battery_control_slugs\`
(registry fallback scoped to the entry), captured as \`coordinator.battery_control_slugs\` in
\`async_setup_entry\` right after the Energy Dashboard read, BEFORE the first refresh (which
already commands batteries); select.py and number.py build from it, \`_per_battery_config\`
reads the store of the controls built, and an unset reserve is the shown default in both
layouts (\`consts/battery_modes.py::reserve_soc_of\`, read by \`decide_battery\`, its #1069 peak cover and
the VPP merge; an explicit 0 still wins). **Guard:** \`tests/test_1071_battery_mode_follows_its_control.py\` — an oracle over
layout × live count × list × scalar: every control's shown value equals what drives each battery
it covers, through the real platform setup; AST checks pin one capture before
\`async_config_entry_first_refresh\` and no second discovery. **Open siblings (for Guido):**
(a) fleet readers still read the scalar on per-battery installs —
\`build_view._battery_may_assist_ev(self.config)\`, the permission-switch seed (\`switch.py\`
\`_seed_state\`), and \`self.config.get("battery_reserve_soc")\` for the spendable floor / forecast
sell / night backfill; (b) the battery card picks its layout from per-battery SENSORS, not from
which mode select exists; (c) \`sensor.py\` sweeps \`sensor.sem_battery_b*_power\` on a boot whose
ED list reads ≤ 1, which removes the registry fallback's evidence for the next boot;
(d) the scalar readers turn an explicit 0 into 20 (\`reserve_pct=…or 20.0\` for the forecast sell,
\`BatteryNightTracker(…or 20)\`) — they should call \`reserve_soc_of\`; (e) a #274 cold start whose
ED resolves inside the first refresh now gets the global controls for that one boot (screen and
runtime still agree).

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
**Live catch 2 (#1066, @RienduPre, 2× Sessy, 07.10.2026):** \`decide_battery\` answered the night
scheduler's stop verdicts (idle, not needed, target reached, not profitable, outside or without a
plan block) before every protection branch. The scheduler is never without a verdict once it is on,
so on those installs the EV clamp, the #620 grid-funded clamp, the #879 house hold and the #892/#1025
window and boost never ran, on any brand. The diagnose line read \`intent=stop_force_charge\` while
2.3 kW went from the packs into the car. The module docstring already said the stop wins only "while
the adapter is still in FORCE_CHARGE intent"; nothing asked the adapter. **Fix:** the adapter keeps one
flag per direction (\`_sem_forced_charge\` / \`_sem_forced_discharge\`: unknown / started / stopped), set by
\`actuate_battery\` only on evidence the command LANDED (the recorded intent, or Deye's \`True\`). A stop
verdict wins only while ITS direction is not known stopped; a forced op SEM started and has not seen stop
is stopped before any NORMAL or LIMIT_DISCHARGE (\`_stop_what_sem_started\`; both open take turns,
discharge first; a stop that has not landed in three cycles lets protection out every other cycle, since
develop's LIMIT wrote the cap even when its zero-write failed — review round 2). The first cut used one
"may anything run" answer from the last intent, and review found two ways it let a forced op run on: an
arbitrage stop (a DISCHARGE stop) after a night charge left a switch-based charge on, and a Deye sale
records no intent at all. Under observer nothing lands, so the view gets "stopped" and the shadow shows
the armed steady state. The #900 lowering wait now applies only to a limit already in force — from NORMAL
the anchor is the pack's max, so a newly plugged-in car was fed for six cycles. Two faults sat under it in
the same report: the battery-side clamp never read \`may_assist_ev\` (class 88), and with no
discharge-limit entity the generic, GoodWe and Huawei writers recorded the asked watts as a limit in
force (class 97's sibling — no call at all, still recorded). Both fixed: the permission holds the clamp
in every arm, and \`_discharge_limit_unwritable\` records no limit and says so in \`last_error\`.
**Guard (this instance):** \`tests/test_1066_scheduler_stop_starves_the_clamp.py\` — an isolation check:
every stop verdict × a 384-case protection grid, with both directions stopped, gives exactly the decision
of an install without the scheduler (intent, watts, reason); each verdict still stops while its direction
may run and is silent once it is stopped; real adapters across cycles: the cap is written, held and
released when the car leaves; a car plugged in after NORMAL is capped at once; a failed stop keeps the
stop first; an arbitrage stop after a switch-based night charge still ends the charge; a real Deye sale
is ended when nothing asks for it; a sale whose stop is refused still gets the cap out; a failed start
notes nothing. Nine mutants (stop always wins, no stop-first, flags never noted, Deye's \`True\` ignored,
dwell on entry, permission unread, adapters pretend, never yields, yield cycle not counted) each fail it.
**Left for Guido:** (1) a Sessy has no discharge-limit setting, so SEM still cannot keep its NOM loop
out of the car — it now says so. Using the power setpoint as a cap (\`api\` + house/N, tracked each
cycle, released to \`nom\`) is a new control mode. (2) The #879 hold's blind release (LIMIT at max)
sits above the EV clamp, so a blind cycle in a held hour lets the pack feed a plugged-in car. (3) The
per-charger \`ev_battery_may_assist\` is read on the charger side only; the battery clamp cannot tell
which car it feeds. (4) OFF is not stopped first: the generic \`command_off\` hand-off zeroes the
setpoint but does not turn a forced-charge switch off (older than this fix). (5) Huawei's
\`command_force_charge\` records FORCE_CHARGE on its orphan-clear and stop-a-sale early returns without
starting a charge, so the flag reads "started" and the clamp comes ~2 cycles late after such a cycle.

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
**Re-opened by a new branch — #804 (@HorizonKane).** The closure holds only while the probe mirrors
the dispatch, and #804 B4a added a branch to `stop_session` without adding it to the probe: a
`button.` start/stop entity stops "through the current write", while
`_discrete_contactor_surfaces` kept answering "this entity can open the contactor" for any
start/stop entity at all. On a go-e — a start button beside a current number whose own minimum is
6 A — the button claimed the stop, the current write was skipped, nothing opened, and the #627
repair that exists to say so stayed silent because the capability said all was well. The park debt
was recorded too, for a stop that sent nothing. **Closure:** a button CLOSES a contactor and does
not open one — `can_close` only, so the probe falls through to the 0 A writability question it was
built on; and the button branch of `stop_session` names a stop method only when that write can
land. #940's anti-cycle floor is unaffected: it reads both sides. **Guard:**
`tests/test_804_no_commands.py::TestAButtonOnlyCloses`. **Sweep question for this class:** when a
dispatch chain grows a branch, does the capability that mirrors it grow the same branch — and does
the new branch ACT, or does it defer? Refs #487 #627 #804.

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
**Third instance (#899 round 2, 23.09.2026) — the branch the guard skipped was the DEFAULT one.**
The home battery's charging watts reach an EV budget by two routes: the forecast redirect, and the
#576 position rule, which simply stops subtracting them once the car outranks the pack. #899 gave
the redirect a meter check — three cycles of grid import with pack watts in the budget and they
stop being counted for the plug-in — and wrote it into the redirect branch of
`decide.SolarOnlyMode`. The position branch handed the same watts through untouched, and recorded
`redirect_w=0`, so the strike rule (`redirect_w > 0`) could not arm on it *at all*. Priority seeds
decide which branch an install takes: a charger seeds at 3 (5 from the config flow), the pack at
100, so the unguarded branch is the one a stock install takes every sunny day. Ten months of a
check that could only fire on the rarer route; koen71's Huawei pack kept its 2700 W, the meter
bought them, no strike ever landed. Reproduced on develop at beta.37 with his own numbers: `bare=2700W
+ redirect=0W → 11A`, ten importing cycles, zero strikes. **Closure, same as both earlier times:**
the gate moved above the split, into `_ev_reclaims` — every caller of it and of
`self_consumption_surplus_w` now honours the veto, including the three modes that delegate their
day path to `solar_only` and the stability bridge's own surplus read. The DECLARING half had the
same shape and the same sweep: `MinPlusSolarMode._decide_day` Zone 3/4 (and `solar_plus_battery`
through it) reach the reclaim via `_battery_assist_split`, spent the pack's watts and stamped
`redirect_w=0`; caught by the review, fixed in the same change. The Min-floor branch beside it
stays at 0 deliberately and says so — that branch BUYS grid on purpose, so import there is not
evidence about the pack. Two more one-branch guards in the same function fell out: an unread SOC
turned the position reclaim off and sent the cycle to the forecast redirect, which credited 1350 W
off the reader's 0.0 SOC fallback (#875's rule, honoured by one door); and observer mode struck on
commands it never sent. **Guard:** `tests/test_899_reclaim_is_metered_too.py` — an oracle, not a
case list: run the cycle twice, once as it is and once with the pack's charge power moved into the
house, and the budget a CHARGE gained over that counterfactual must equal the watts it declared,
over every mode as well as every shape. A new route that spends pack watts and stays quiet fails it
without anyone naming the route. **Open for Guido, named not closed:** the veto is judged on the
FLEET meter (`view.fleet.grid_import_w`) against a PER-CHARGER credit, so a sibling charger's
deliberate grid draw can veto a charger whose pack is yielding perfectly — class 3, pre-existing,
but round 1 could not reach it on a stock install and round 2 can. It also latches until the car is
physically unplugged, and an install with no grid sensor reads 0.0 for ever, so the check is a
silent no-op there. `diagnostics.charger_adapters[cid].battery_reclaim` now carries `vetoed` and
`strikes` so a dump can at least say it happened. Refs #899 #576 #938 #925 #875.

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
pump short-cycled and the user could neither see the window nor lengthen it); **#1040** (Calendar
tariff mode sat in the Tariff menu since #120, and the setup guide promised a calendar field, but
nothing ever wrote the schedule the provider reads — the mode ran at the off-peak price all day.
Closed by `tariff_schedule_entity`, a Schedule-helper field the page refuses Calendar without, on
the options page and the config card; guard `tests/test_1040_calendar_schedule_field.py`). **#1040 second round (07.10.2026):** the default view showed
Calendar with one of its two prices. The off-peak rate sat behind Advanced, so a helper alone gave
"no price difference". Closed by `ESSENTIAL_IN_MODE` (the off-peak rate is essential in Calendar
mode only) and by showing the picked mode's fields before Apply; guard
`dashboard/card/test/calendar-setup.test.js`.
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

### 91. A fail-open fallback layer blind to a dimension the primary layer honours — GUARDED
**Symptom:** a *Solar + cheapest hours* charger with a 06:00 deadline starts grid-charging at
20:36 — the night-window open — in the most expensive band of a Spanish 2.0TD tariff, with nine
cheaper hours still ahead of the deadline and nothing forcing it (#967, @alexmc1510). The
Energy Plan card is calm, the coverage chip names a doubt, and the reactive layer reports
"night charging" as if nothing were wrong — because for that layer nothing is: it has no notion
of price at all.
**Root shape:** two layers answer one question — WHEN to charge tonight — with the primary
(the joint plan, #638) honouring a dimension (the tariff) the fallback (the reactive night
charge) does not know exists. The fail-open direction is right: an UNCOVERED verdict must never
strand a floor. But the fallback was written before the primary existed and then had its own
tariff opinion *retired* when the primary took the WHEN (#638 C3), on the assumption the primary
would always speak. It does not: a `yields` verdict (a 6 A minimum wider than a 3.5 kW peak
headroom — the reporter's exact install), a stale stamp, a car the plan never saw. Every one of
those hands the night to a layer that starts at the window open. The tell: the fallback's own
docstring said "an uncovered night fails open to CHARGING at the deadline/top-up floor" and
nobody asked *in which hour*.
**Where it lives:** `ev_tariff_planner.plan_night_charge` (the reactive night plan);
`energy_plan_actuation.ev_overlay` (returns "nothing changes" on UNCOVERED); the composer's
daytime preview (`coordinator.py`, the `_np_c is None` branch) — the same blindness one surface
up, and a second producer of the need on top (class 37/46: `daily_ev_target` at a literal
4.1 kW where `build_night_target_map` already answered 19.8).
**Closure:** the fallback keeps the primary's dimension — `affordable_start` walks the tariff's
own levels (`get_price_level_at`, the classification `price_is_cheap` fires on) and a cheap-hours
mode holds through an EXPENSIVE hour while the non-expensive hours before the deadline still
deliver the floor at the peak-managed rate; a forcing deadline or an unreachable floor is never
held. The preview is drawn from the one producer of the need and says it is an estimate until
the plan has spoken. The card paints "wait" until a start that sits at the open.
**Guard:** `tests/test_967_plan_band_strip.py` — the reporter's night rebuilt from his numbers
through the same pure functions in the same order (ledger → packer → stamped dict → gate →
overlay → reactive plan → composer → the card's segment rule), reproducing the 20:36–21:41 bar
before the fix and pinning the wait after it; plus the structural contracts that the preview has
one call site, reads the one producer, and that the planner is wired with the tariff's levels.
`dashboard/card/test/ev-strip.test.js` pins the card's rule.
**Sweep question:** for every fail-open fallback in SEM — *which dimensions does the primary
honour that the fallback cannot see?* Price is one; the peak slot (#864), a departure time
(#892), a closed meter (arc #921) are the next candidates. A fallback that fails open into a
dimension it is blind to is not "safe", it is merely quiet.
Refs #967 #966 #939 #638 #282 #742 #464.

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
**Second catch (#939, 09.09.2026) — a plan gate, not a card.** `_plan_car_full` answered "is this
car full?" from the taper/stall anchor for every charger, while a SOC-target charger's night need
(`build_night_target_map` → `_calculate_remaining_need`) and the reactive layer both answer it from
the car's own SOC sensor. A false anchor over a Tesla reading 71 % dropped the car from the plan
while the reactive layer charged it for the deadline; the N2 meter rule then made the gate follow
the charger's own draw, and the two layers fought 60 s on / 20 s off all evening. **Closure:** for a
SOC-target charger the gate returns None, keyed on the target TYPE: the need is car-derived either
way (the sensor, else the anchored virtual SOC `_resolve_charger_soc` falls back to — the anchor's
own answer, so #756's skip still arrives through `kwh <= 0.05`), and a gate keyed on "the sensor
reads this cycle" restamped the night on every blink (caught in review). The type expression is
shared with `build_night_target_map` (`ev_night_targets.charger_target_type`); the plan's "no
overnight demands" line now names `car_full`, whose absence hid the anchor. **Guard:**
`tests/test_939_plan_defers_to_the_car.py` — the accessor, a signature that must not move with the
draw or a sensor blink (the `ev` term asserted present, so a raising accessor cannot pass it), the
dark-sensor need reading nothing owed, and the collector keeping the car; the at-rest, signature and
collector pins are RED against the pre-fix gate. **Left for Guido:** (1) on a kWh target the gate
still consults the anchor and the N2 meter rule is memoryless, so any false anchor still makes the
car-full term follow the draw there. Closing it means letting post-full energy refute a
`_full_detected` anchor (exempt by design today —
`test_a_detected_full_charge_is_never_refuted_by_its_own_trickle`; #939's car took 23 kWh
"post-taper") and making `get_virtual_soc` recalibrate when it re-arms on an unchanged reading. (2) A
SOC car that finishes mid-night by taper (Min 100 %, or the car's own limit) no longer restamps the
plan through this term — the SOC need is not a signature term, so its blocks stay stamped until
another trigger.
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
**Third catch (#820, @ArneGollin1987, 16.09):** the mirror image. `charge_pacing.paced_charge_cap_w`
solved the pace from surplus hours only — deficit hours counted as zero — while the *authoritative*
model the user sees, `provisional_soc_curve`, walks the house drawing the pack DOWN in exactly those
hours. Two models of one day, and the one that ACTS was the weaker. An afternoon cloud or a midday
EV session grew the need by a kWh the cap never saw, and the evening "could not reach the pacing
watts". Same file, same fix shape: the solver reads the drain the curve already knows (`_drain_kwh`).
The cousin defect beside it — a cap solved to land full in the LAST slot exactly, no margin, against a
docstring that promised "sunset − margin" — is class 46 (b), a discarded field: `end_margin_slots`
existed, defaulted to no margin, and no caller set it.

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
**Live catch (#1038), shape (c) again — the copy #833 did not look for:** the setup wizard's check
(`EVChargerDetector._validate_entity`) kept a third copy of the status words, and
`validate_ev_configuration` is a hard gate on the setup and reconfigure forms. On Home Assistant's
own Ohme test data (HA 2026.8.2) the status sensor stores `plugged_in`, `finished`,
`pending_approval`; the reader knew all three, the wizard's copy had `"plugged in"` — the label HA
shows, not the state it stores (class 116, read side) — so the form refused the sensor while the
car sat plugged in. The same copy spelled Peblar `"no ev connected"`; core stores
`no_ev_connected`, and `suspended` for a car plugged in and paused, which no list knew, so the
reader also read that car as gone. **Closure:** the copy is deleted; the wizard asks
`status_enum.knows_status` — the words the reader maps, plus a `_FAULT` set (`error`, `faulted`,
`fault`) that the reader still reads as unknown, so a plain OCPP or Wallbox sensor caught in a
fault still saves. Numbers stay `0`/`1` only: the reader reads any number > 0 as on, so a voltage
picked by mistake would show a car plugged in all the time. An ENUM sensor in any other state
passes when its `options` let the reader answer yes AND no for the role; one known word is not
enough. Peblar's two words and Tesla Wall Connector's `not_connected` joined the shared list. The
bare IEC pilot codes (`a`, `b1` … `f`) stay accepted in an `_IEC_PILOT` set, still unknown to the
reader: ABL eMH1 (#808) may store them. Dropped with the copy, because no integration is known to
store them and the reader never mapped them (each reads as "no"): `true`/`false`, `idle`,
`no ev connected` on a plain sensor. A fourth copy, in the coordinator's per-charger loop (`== "on"`, so Ohme
`charging` read as not charging; nothing read the result), now takes the reader's per-charger
answer. **Guard:** `tests/test_1038_wizard_reads_the_shared_words.py` — core's option lists for
Ohme, Peblar, NRGkick, Blue Current and Tesla Wall Connector through the wizard's check (Ohme and
Peblar through the whole form); every word the reader knows passes it; an AST lint over the
package for any tuple, list, set or dict keys with two or more status words outside
`status_enum.py`, unless they are only on/off. **Left for Guido:** the shared list still lacks words
core really stores — Blue Current `vehicle_detected`/`standby`, NRGkick `standby`, Tesla Wall
Connector `waiting_car`, the ABL pilot codes — so a Blue Current `vehicle_status` is still refused
except at `ready` (one that saved at `ready` is refused on a later reconfigure), and the reader
reads a car at `vehicle_detected` as gone. Each needs its meaning checked at the source before it
is mapped. Older and separate: `_discover_peblar` and
`_discover_easee` take a status sensor only with no device class, but core's Peblar `cp_state` is
`enum`, so registry discovery never binds it (the glob prefill does, on an English install).
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
**Live catch (#1040), shape (a):** Calendar mode built its provider with 0.35/0.22 for an unsaved
rate, while the card, the Tariff page and Static used 0.3387 for both. A Calendar user who never
saved a rate saw two equal prices and SEM priced hours at a spread nobody entered. Review found the
worse half: a fixed off-peak default is wrong for anyone who saved only an import rate. With 0.25
saved, Static (its 0.3387 fallback dates from #485) and the first fix priced nights at 0.3387 and
still called them cheap.
And the live refresh kept the old off-peak rate when the import rate moved. Closed by one reader,
`_cfg_tariff_rates`: an unsaved off-peak rate IS the import rate (one price), for both providers
and the refresh; the Tariff page and the card show that same default. `DEFAULT_ELECTRICITY_IMPORT_RATE`
replaces the literal in the providers' construction, the Tariff page, the import-rate number and the
cost calculator (the card's JS and `StaticTariffProvider`'s own parameter defaults still say 0.3387);
the unused `DEFAULT_ELECTRICITY_NT_RATE` is gone. The Tariff page's off-peak default was `_c(...) or 0.3387`, so
a saved 0 (a free night) showed 0.3387 and Submit wrote it back — also fixed. Guard:
`tests/test_1040_calendar_schedule_field.py::TestAnUnsavedRateIsTheShownRate`.
**Left for Guido:** the dynamic fallback price (`fallback_price`, `default=0.30`, two sites) and the
battery break-even fallback (`0.22` off-peak, `0.30` peak in `_maybe_run_scheduler_evaluation`) still
restate their own numbers; changing them moves battery and dynamic-tariff decisions. And the Tariff
page saves every field it shows: change the import rate there and leave the off-peak rate, and the
old import rate is saved as the off-peak rate — a spread from one edit (older than #1040).
Refs #789 #788 #716 #746 #685 #678 #833 #1038.

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
**Second catch (#1026, Guido, PROD HA 2026.8, 28.09.2026) — caught at the WARNING stage, before
the removal.** HA 2026.8 logged *"uses `device_registry.devices` as a mapping ... will stop working
in Home Assistant 2027.9.0"* at every start. Four sites, all in
`coordinator/battery_adapters/huawei.py`: the inverter resolver behind the feed-in cut
(`reg.devices.get` twice, then a walk of every device in the house) and the zero-config battery
autodetect (a second walk). The class shape is the same as #799 and the damage would have been
worse: both resolvers return `None` inside a broad `except` — *"resolution never breaks a cycle"*,
*"detection must never break setup"* — so on 2027.9 the raise would have read as **"there is no
Huawei inverter on this install"**, and forcible charge, forcible discharge and the export cut
would all have gone quiet on working hardware with nothing in the log. **Closure:** `reg.async_get(
device_id)` for the two lookups, and `device_registry.async_entries_for_config_entry(reg, entry_id)`
over the `huawei_solar` config entries for the two walks — the helpers HA's own message names, and
both read the registry's real containers (`_device_data`, `_devices`) rather than the deprecation
view, so the log line goes away instead of moving to another line. That was checked against HA's own
source, not assumed: `devices` is now a `_DeprecatedDeviceRegistryItemsView` property whose `get`,
`values`, `__getitem__`, string `__contains__` and proxied methods each report, and
`async_entries_for_config_entry` deliberately bypasses it. The per-entry question is also the
narrower one (only a `huawei_solar` device could ever match, so the fleet walk was never needed),
both resolvers now WARN instead of reporting an empty house, and the per-entry order is sorted
because HA re-indexes a device on every update — unsorted, "the first battery" would move to another
battery after the inverter reported new firmware. Note SEM cannot use the message's other suggestion,
iterating `reg.devices`: it yields device entries on 2026.8 and dict KEYS on the older versions SEM
still supports. One accepted narrowing: a device carrying a `("huawei_solar", …)` identifier that is
attached to some OTHER integration's config entry is now invisible. Only `huawei_solar` mints those
identifiers.
**Where else it lives:** every call into a HA host API with a removal schedule wrapped in a broad
`except` — `hass.components.*`, `async_get_registry`, the singular `async_forward_entry_setup`,
`async_add_job`. Swept 2026-08-18: `register_static_path` was the only *removed* API still called
(one site); `async_forward_entry_setups` (plural, current) is already in use. Swept again 2026-09-29
(#1026): the device registry was the only deprecated form still read; `hass.async_create_task` is
current. **Watch:** the entity registry's `reg.entities.values()` is the same shape and SEM reads it
at 17 production sites (`hardware_detection.py`, `config_flow.py`, `select.py`, `cleanup.py`,
`__init__.py`, `huawei.py`). HA has NOT scheduled it — 2026.8 warns about the device registry only,
and HA publishes no "every entity" helper to replace it — so it is a watch item, not a sweep.
**Guard:** `tests/test_frontend_resources.py::TestStaticPathServedViaAsyncApi` — a source lint that
the removed `register_static_path(` call form never returns (mentioning the name in a comment is
fine), plus a runtime assertion that the dashboard dir is actually served through
`async_register_static_paths` with the right `/local` url_path. Plus (#1026)
`ast_contracts.host_registry_mapping_reads()`, pinned by
`tests/test_1026_device_registry_is_asked_not_read.py`: no production file may read `devices` or
`deleted_devices` off anything holding a host registry. It follows the binding through assignment,
the walrus, tuple unpacking, `for`/`with` targets, a rename chain, `self._reg` across methods, the
inline `dr.async_get(hass).devices` form, `getattr(reg, "devices")`, and a parameter named `reg` /
`registry` inside the function that declares it — nine shapes, each pinned by its own case, so the
list is measured rather than claimed. Scoping the parameter rule to its own function is what keeps
SEM's own `UnifiedDeviceRegistry.devices` readable. Its blind spots, stated rather than implied: a
registry pulled out of `hass.data` by hand, a parameter under some other name, and a file that names
the `device_registry` module nowhere. **Sweep question:** for
every host API we call inside a `try/except`, has HA scheduled it for removal — and can the `except`
clause tell "already done" apart from "this method no longer exists"? A comment on an `except` that
names the one way it fires is a claim to verify, not a fact. Refs #799 #1026 #283 #785 #55.

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

**Round 2 (#1043, 2.1) — SEM's own Energy Dashboard config, not an integration.** The reader keeps
every source in `<category>_energy_list` and the FIRST one in the scalar `<category>_energy`. The
lifetime seed read the scalar for grid and battery, so a dual-tariff meter seeded tariff 1 alone
(RienduPre: lifetime CO2 261 kg against 610 kg for one year); the yearly seed and
`_query_monthly_energy` read the scalar for all five categories. The read had a warm-up twin (class
86): a counter still loading read 0, so a three-inverter sum was the first inverter and looked
complete — and against a good stored value it fired #551's downward heal, shrinking it.
**Closure:** one resolver, `ha_energy_reader.energy_counters(ed, category)` (the list, else the
scalar), used by all three seeds and by the coordinator's counter wiring. The lifetime seed sums only
when every listed counter gives a reading — no state, unknown/unavailable, NaN and 0 are not one.
Each counter has its own wait, which starts only once HA runs (class 86) and lasts
`UNAVAILABLE_REPAIR_THRESHOLD_S`; then the counter is left out (a gone ED row must not hold the seed
for ever; an external `source:id` statistic is left out at once). A sum with a counter left out is a
FLOOR: that category is only ever raised, and #551's downward heal does not fire on it. The seed
records the counters it summed (`lifetime_seed_counters`, persisted); when the set changes — or, with
no record, when any list is longer than one — each total is RAISED to its counter sum, never lowered.
The same holds for the old below-half and 90 % re-seeds (review, two rounds: a swapped inverter, a
removed row or a second charger reads less than the history SEM holds, and a full overwrite triggered
by ANOTHER category lowered it); only #551's unit heal still sets values outright. `lifetime_home`
moves by the raised amounts. So every install seeded before the fix heals on its next restart, not
only those below half of the hardware. The battery wait now applies only to a battery
counter that gave a reading: a battery-less install read 0 + 0 there and never seeded at all.
**Guard:** `tests/test_1043_lifetime_seed_all_counters.py` — the reporter's numbers, a tariff-1 seed
above half heals, a re-seed never lowers history (swapped inverter, removed row, gone or dark
counter, a below-half category beside a lower counter, a night restart, a floor never starting the
unit heal), per-counter waits that start when HA runs, battery-less, the record round-trips, yearly
and monthly sums, and an AST check that `energy_calculator.py` names no scalar `*_energy` field.
**Named, not swept:** the EV part of both seeds takes the FIRST `device_consumption` entry whose id
CONTAINS a keyword (`"ev"` — class 67), so a two-charger install seeds one charger, and summing would
sum every false match too. `coordinator/night_backfill.py` reads the `*_energy_sensor` config keys
(#876 copied the scalars there), so a night's grid and battery legs are the first tariff and the
first battery. A yearly total seeded from tariff 1 before this fix stays low until 1 January (the
yearly seed runs once per install). `sensor_reader.battery_sign_diagnostics` lists the scalar
first (diagnostics only); `_grid_counter_entities` restates list-else-scalar (correct today).


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
**Second instance — #1034, one end of a range:** HA's own V2C Trydan test data publishes three
current numbers: `intensity` (the set-point), `min_intensity` and `max_intensity`. The V2C rule kept
the last one named "intensity", so registry order bound the FLOOR: every SEM write would move the
minimum and leave the charge alone. The qualifier is a RANGE END, not a mode. `_reject_range_end_current_control`
runs at the same choke point, right after the offline guard: a control whose own name or translation
key says `min`/`minimum`/`max`/`maximum` swaps to its set-point twin (the number named like it
without that word, same device class and unit; the key is compared too, so a German or renamed id
still finds it; only the side that holds the word is compared; two twins are a choice it does not
make). With no set-point a CEILING stays — on Alfen, Wallbox, Zaptec and OCPP the "max current"
number is the only one and IS the control — so a FLOOR goes to its ceiling twin (else the order of
the pair would decide), and a floor with neither is dropped (this class's actuation rule). Where
`_own_names` takes nothing off (mqtt, a small unit with one id renamed), the leading words more than
half the unit's ids share are the device's (`_what_it_is`): "Min JuiceBox" (Swedish "my") is not a
floor, but its `…_min_current` still is. Guard: `tests/test_1034_range_and_circuit.py` — HA's V2C
in all 144 orders of its numbers and power sensors, the brand rule's raw answer spelled out, and an
every-platform oracle with `min_`/`max_charging_current` first and last. **Left for Guido:** a V2C
SAVED before this fix keeps `min_intensity` (detection re-runs only with no charger configured; the
#886 heal swaps only `offline`).

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
sun explains it). **Derived-source completion (#912 round 2, bekovan, 2026-09-06).** The sibling
rule read the SOURCE as "my own config-entry siblings" — right for a directly-polled sensor, but a
DERIVED input (a Template negating a Shelly plug; a utility_meter; a Riemann integral) writes only
when its rendered value changes AND is the sole entity of its helper config entry, so it has no
sibling to vouch and false-warned on beta.7. Its liveness is its actual source's: a derived-platform
entity now follows the source entities it draws from (scanned generically from its helper config
entry's options/data — the template string, a ``source``/``entity_id``/``entity_ids`` key), honest
if any source or a source's integration is alive; an untraceable helper (YAML, no config entry) is
honest because a flat derived value is a change signal, not a poll stall; a genuinely dead source
still warns through the helper. **Guard:** `tests/test_912_frozen_sibling_rule.py` pins the rule is
one place; `tests/test_912_frozen_derived_source.py` pins source-following for derived inputs.
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

### 65. One anchor for discovery, and it belongs to somebody else — GUARDED
**Symptom:** an install ends with *"your Energy Dashboard is missing Solar — set it up and start
again"*; a supported inverter is discovered and SEM stands down because a different page is
unconfigured. **Root shape:** every source SEM reads was resolved from HA's Energy Dashboard, so
SEM's onboarding inherited another feature's completeness as a precondition — and that feature maps
kWh counters while SEM steers on watts, names only solar/grid/battery, and gives one entity where a
two-inverter house has two. There was no second way in, because until the census (#848) SEM could
not ask what was installed. **Closure (#915):** a second anchor pointing the other way — which
energy integrations are installed, and what does each call the three sensors SEM needs, from its
own declared vocabulary, then from entity shape. The dashboard becomes the preferred answer rather
than the only one; discovery offers the install instead of standing down. **Guard:**
`tests/test_915_roster_at_runtime.py::TestTheSecondAnchor` (including a German-named Huawei install
where no entity id contains "solar", "grid" or "battery"), plus the config-flow tests that now
assert a FORM where they asserted an ABORT. **Sweep question:** which of SEM's preconditions are
really *another feature's* completeness, and what would SEM ask if that feature did not exist?
Refs #915 #848 #274.

### 66. A config-flow step that writes keys nothing reads — GUARDED
**Symptom:** an install completes cleanly, every entity appears, and SEM reads **0 W from a 4.2 kW
inverter**. **Root shape:** the new `sources` step wrote `solar_power_sensor` /
`grid_import_power_sensor` — the names the Energy Dashboard produces — but an install that *takes*
that step has no dashboard config by definition, so `SensorReader` falls to its legacy path, which
reads `solar_production_sensor` / `grid_power_sensor`. Two vocabularies for the same three sensors,
and the flow wrote the wrong one. **Every unit test passed**, because none of them followed the
config from the step that writes it to the reader that consumes it — the halves were tested, the
seam was not. **Live catch (#915, .46 fresh install with the grid source removed from the Energy
Dashboard).** **Closure:** write both key sets, and a test that extracts the dict the step actually
writes (by AST, so it cannot drift from the flow) and asserts `SensorReader` resolves every sensor
from it. **Guard:**
`tests/test_915_roster_at_runtime.py::TestTheSourcesStepWritesKeysTheReaderConsumes`.
**Sweep question:** for every config key a flow writes, which code reads it — and is there a test
that starts at the writer and ends at the reader? Refs #915 #274.

### 67. A substring is not a word — GUARDED
**Symptom:** SEM offered SENEC's switchable **wall sockets** as the house battery's charge target
(`sockets_1_upper_limit`, and its `sockets_1_time_limit` schedule with it), and SENEC's live
production sensor as the system's nameplate size. **Root shape:** a matching rule written as
`soc.*(limit|target)` matches the letters s-o-c inside "**soc**kets"; `rated_power` matches the
tail of "solar_gene**rated_power**". A translation key is a sequence of **segments**, and a rule
that forgets it silently claims the brands that happen to own that word — the two above were the
only ones in 171 rows, which is exactly why nothing looked wrong. **Closure:** anchor the token
(`(?:^|_)soc(?:_|$)`); `\b` does not help, because `_` is a word character. **Guard:**
`tests/test_915_roster_at_runtime.py::TestSemDoesNotOfferToWriteTheseRegisters::test_a_substring_is_not_a_word`.
**Sweep question:** every regex over an identifier — does it anchor to segment boundaries, and
which real key would it match by accident? Refs #915 #810.
**Second instance — #804 (@HorizonKane), the EV brand rows.** The closure above was applied to the
battery lexicon's regexes and not to the OTHER matcher over identifiers: `_discover_from_hints`
tests a brand's name hints with a plain `in`. The Wattpilot row hints `("start", "resume")` for the
charging button, and the reporter's go-e publishes `button.carport_wattpilot_91114903_neustart` —
the German RESTART button. SEM adopted a device reboot as the charger's start/stop control, so
every enable power-cycled the box and every stop wrote nothing. Every language ships one of these
words and every one of them contains "start": restart, neustart, herstart, genstart, omstart.
**Closure:** a hit must BEGIN a segment (`_name_hit`) — the rows hint prefixes ("charg" for
charging, "amp" for amperage), so the anchor is the start of a word, not both ends — plus
`_reject_reboot_control` at `apply_charger_discovery_guards`, the choke point every registry path
funnels through, so the hand-written brands and the generic prober are covered too. A SAVED config
is reached by the `start_stop_entity` property setter, which refuses a reboot from any caller.
**Guard:** `tests/test_804_no_commands.py::TestASubstringIsNotAWord` — the reporter's own entity id,
the segment rule, and an oracle that feeds EVERY brand in `_EV_CHARGER_PLATFORMS` a device whose
only button is a reboot and asserts no role takes it. Refs #804 #915.

### 68. A protection floor read as a target — the knob is not missed, it is INVERTED — GUARDED
**Symptom:** five brands (Growatt, Sigen, Solis, Sungrow, Sunsynk) declare both halves of the SOC
range under names one word apart — `battery_charge_soc_limit` beside
`battery_discharge_soc_limit_on_grid`, `soc_upper_limit` beside `soc_lower_limit`. SEM proposed
either as `battery_target_soc_entity`. **Root shape:** "charge to 80 %" written into "never
discharge below" does not miss the target — it stops the pack discharging at 80 %, the opposite of
the request, and it looks like a working configuration. The same shape put a **car's** state of
charge (Wallbox `state_of_charge`, V2C `battery_power`) into the HOUSE battery reads that feed the
energy balance every ten seconds. **Closure:** the lexicon excludes floors from the target role,
and a charger contributes EV + vehicle roles only — SEM's own `_EV_CHARGER_PLATFORMS` list decides
what a charger is, with vocabulary markers for brands nobody has listed yet. **Guard:**
`::test_a_protection_floor_is_never_a_target`, `tests/test_915_coverage_ratchet.py::TestAChargerIsNotAHouse`.
**Sweep question:** for every value SEM writes, what is the OPPOSITE register called on that
brand — and would the matching rule tell them apart? Refs #915 #810.

### 69. One incidental word decides a whole device — GUARDED
**Symptom, in both directions on the same afternoon.** Victron's GX declares `ev_odometer` for the
car plugged into its EV charger — **one key out of 465** — and that single word classified the whole
system controller as "a vehicle", discarding 464 keys of inverter and battery vocabulary (its ESS
charge limit, force-charge, mode select and grid power). Midea's cloud declares `inverter` — an
inverter *air conditioner* — among **1095 keys** of fridges, dryers and ice makers, and that single
word classified the marketplace as a house and offered its `work_mode` as a battery strategy.
**Root shape:** a classifier that returns on the FIRST marker it finds asks "does this word appear?"
when the question is "what is this mostly?". On a large vocabulary an incidental word always appears.
**Closure:** count distinct markers per kind and let the largest win, with a tie going to the house
(`camera`, `pedal` and `lightbar` are gadget words a CAR also has, and they tied 3-3 with `grid_`,
`inverter` and `_grid_` on a Tesla integration). Plus the level below: a `battery_*` role needs a
battery somewhere in the vocabulary at all — no key-level pattern can separate an air conditioner's
`work_mode` from a battery's, because they are the same string. **Guard:**
`tests/test_915_coverage_ratchet.py::TestOneWordDoesNotDecideADevice`. **Sweep question:** every
`any(...)` over a set of markers — is the answer a *property* of the whole thing, or just proof that
one member exists? Refs #915 #869.

### 70. The index nests, and the loop was flat — GUARDED
**Symptom:** Tesla Powerwall — a brand in SEM's own sign-convention table, 1994 installs — was
absent from the integration roster, and so was Tesla Wall Connector (6555 installs, more than KEBA,
Zaptec and Wallbox). **Root shape:** Home Assistant's `generated/integrations.json` groups
sub-integrations under their BRAND (`tesla` carries `powerwall`, `tesla_wall_connector` and
`tesla_fleet` in a nested `integrations` dict and appears at the top level as a name only). The
crawler iterated the top level and called it the core index — **241 integrations were never even
looked at**, and nothing failed, because a source you do not read produces no error. Found by
checking the roster against the CLOSED hardware-support issues (#75-#81), where seven human verdicts
had already named the integrations SEM should have been able to name. **Closure:** flatten brand
groups before filtering, and let the install floor buy a QUESTION for core integrations the way it
always had for HACS ones — "Wall Connector" contains no energy word, so it was never asked what it
declares. **Guard:**
`tests/test_915_coverage_ratchet.py::TestTheClosedHardwareIssuesAgree`. **Sweep question:** for every
external source, what is its shape — and does the count of what you read match the count it claims?
Refs #915 #75 #816.

### 71. A catalogue role that spans the write boundary — GUARDED
**Symptom:** the roster's `battery_strategy` role matched Sessy's power-strategy select — which the
generic adapter switches every cycle (`_set_strategy`) — AND Huawei's working mode, Victron's ESS
mode, Deye's work mode, GoodWe's operation mode. #845 had drawn the line for those: *"nothing in
SEM may ever WRITE a policy selector, that boundary is the user's."* The card would have offered a
one-click bind of Victron's `system_ess_mode` to the key the adapter writes, and every cycle SEM
would have sent `select_option("nom")` to the inverter's operating policy. **Root shape:** a role
is a *reading* — "this is the mode select" — but a config key is a *permission to write*, and the
mapping role → key silently granted the permission to every reading that matched the regex. The
regex cannot see the boundary; only the key's consumer knows whether it writes. **Closure:** two
roles. The writable one (`battery_power_strategy`) matches only the keys the adapter was written
for; the policy one (`battery_strategy`) is `OBSERVE_ONLY` and carries no key at all — the card
says *SEM reads it and never writes it*. A writable strategy is additionally offered only when the
select lists every value SEM would send (#751 was that mismatch, silent). **Guard:**
`tests/test_915_roster_rediscovery.py::test_a_policy_selector_is_never_the_writable_strategy`,
`tests/test_915_roster_at_runtime.py::TestAPolicySelectorGetsNoButton`. **Sweep question:** for
every role → config-key mapping, does the key's CONSUMER write — and does every key the role matches
deserve to be written? Refs #915 #845 #751.

### 72. A gate on the discovery path, bypassed by the button — GUARDED
**Symptom:** `discover_inverter_from_registry_verbose` refuses a discharge control without an
explicit power unit (`require_explicit_unit=True`). The Config card's *Use this* button writes
`battery_discharge_control_entity` directly, so a number named like a power limit and measured in
amps — or with no unit at all — got a button, and the first write would have gone into it at scale
1.0. The write path's own check catches `%`/A at write time but only with a log line, and a log
line is not a surface (#799). **Root shape:** a safety check that lives on ONE path to a config
key, when the key has two. The second path was added later and inherited none of it. **Closure:**
the check moves to proposal time, where every path that can offer the button runs — the live
entity's unit and existence are read, and each refusal carries a reason the card renders. **Guard:**
`tests/test_915_roster_at_runtime.py::TestTheButtonIsOfferedOnlyWhenTheEntityCanTakeIt`.
**Sweep question:** for every config key, how many code paths can SET it — and does each of them
run the same gate? Refs #915 #824 #882.

**Second instance, one day later, in the fix itself (06.09 audit).** The segment-bounded,
exact-only-aware matcher was written for the card's proposal path. The discovery rung that
AUTO-BINDS `battery_discharge_control_entity` at install — the actuation path, the one the whole
gate exists for — kept `roster_role_keys()` (exact-only stripped) and a bare `endswith`, and on a
Marstek bound the fleet ceiling for the per-unit key it ends with. Three consumers of the same
data, three matchers; now one `_entry_matches_declared`. The sweep question above applies to
MATCHERS as much as to gates: how many places compare a declared key, and is it the same code?

### 73. A success that is not an event re-arms the clock — GUARDED
**Symptom:** the #915 write read-back never produced a verdict on PROD: `write_verified` stayed
`None` all day while the discharge limit was written every cycle. **Root shape:** the idempotent
same-value skip (#900/#538) returns `True` — correct for "did the setpoint end up right" — and the
read-back took that `True` as "a write went out" and re-noted the pending write, resetting its
grace timer every ten seconds. A timer that measures "time since the last write" was being fed
"time since the last *success*", and in the default state every cycle succeeds. The feature was
inert precisely when the register it exists to watch was being written. **Closure:** the write
helper returns `(ok, wrote)`; only `wrote` notes a pending write; an identical pending write is
never re-armed; and the default state (`command_normal` with a register stuck at 0) is tested to
reach a `False` verdict within cycles. **Guard:**
`tests/test_915_write_verification.py::TestTheDefaultStateReachesAVerdict`. **Sweep question:**
for every timer or counter armed "on write", "on send", "on refresh" — is it armed by the EVENT or
by the RESULT, and does the result ever succeed without the event? Refs #915 #900 #538.

### 74. `getattr(self, "name", None)` on an attribute that was renamed — the feature is dead and nothing says so — GUARDED
**Symptom:** three separate features published nothing and raised nothing: #827's discharge-rate
caveat, #845's expected-operating-mode seed, and #915's battery write read-back with its Repair.
All three read `self._battery_adapter` — **singular** — and nothing has assigned that name since
#375 moved the per-battery loop to `self._battery_adapters` (plural, keyed by battery_id).
**Root shape:** `getattr(obj, "name", None)` is written to survive a missing attribute, and it does
exactly that — forever, silently, for a name that will never exist again. A rename that a plain
`self._battery_adapter` would have turned into an `AttributeError` on the first cycle instead
produced a `None`, a `callable(None)` that is False, and a feature that never ran. Each of the
three was unit-tested and each test passed, because every one called the helper directly with a
hand-built `self` — the tests proved the logic and never the WIRING. Found by a re-audit that was
asked to verify a fix rather than trust it. **Closure:** one accessor,
`SEMCoordinator._primary_battery_adapter()`, reading the plural dict; an AST guard that fails on
any `self._battery_adapter` attribute access anywhere in the tree; and a test that drives the
verdict through the real per-cycle shape rather than a hand-built one. **Guard:**
`tests/test_915_roster_at_runtime.py::TestTheReadBackIsActuallyWired`. **Sweep question:** for
every `getattr(self, "_x", None)` — is `_x` ever assigned? And does any test exercise the path
through the REAL object rather than a stand-in? Refs #915 #827 #845 #375.

### 75. One knob, two features, and the knob shows only one of them — GUARDED
**Symptom:** `switch.sem_battery_may_export` read **off** on PROD while SEM opened a 5 kW sell block
("selling before the night at 5000 W"). Nothing sold, and only because that battery happened to be
pinned to an adapter with no forced-discharge path — on a correctly detected Huawei it would have
sold the pack to the grid under a switch that said no. **Root shape:** TWO features can sell —
#533's arbitrage under `battery_grid_arbitrage_enabled` and #778's forecast spend under
`forecast_spending_enabled` — and each correctly asks `may_export` with its OWN flag. The switch
asked with only the arbitrage one, so it answered *"may the arbitrage feature sell?"* while wearing
the label *"Battery may sell to grid"*. Neither side was wrong; the switch answered a narrower
question than its label. `tests/test_knob_wiring.py` guarded that the permission is READ — not that
the two readers AGREE. **Closure:** the display is defined AS the decision (`battery_may_export_display`
= the OR over every path that can sell), so the two cannot disagree because there is only one of
them; plus a combination guard over mode × permission × both master switches. **That guard then found
a second, worse case nobody had asked about:** on the legacy `allow_arbitrage` mode an EXPLICIT
revocation was ignored — switch off, both features off, and SEM still sold. The code knew ("the two
functions genuinely disagree… worth settling deliberately, not here", August) and it was never
settled; a mode value chosen once does not outrank a permission revoked deliberately, so the newer,
more specific *no* now wins, with UNSET still short-circuiting so no existing install moves.
**Guard:** `tests/test_920_switch_agrees_with_the_decision.py` (parametrised over every combination,
with the decision model pinned to the real call site so it cannot go stale). **Sweep question:** for
every switch a user can see — how many code paths act on the thing it names, and does the switch
consult ALL of them? Refs #920 #778 #533.

### 76. A source-inspection guard names the ONE function it was written for — GUARDED
**Symptom:** Tomorrow's card showed a plan the night would not execute: the same forecast, the same
tariff and the same battery produced one answer in the preview and another in the stamped plan.
**Root shape:** `day_ledger.build_day_slots` prices a surplus slot at `export_rate` — what a kWh
earns if it leaves, and therefore what consuming it here costs (#755) — and the parameter **defaults
to `0.0`**, the free sun the packer prefers by fiat. Four production sites build day slots; #755
passed the rate at **one**. Two of the three silent ones read no price and were merely a loaded gun;
the third, `_compose_tomorrow_preview`, runs the real `build_night_ledger` + `pack_night`, so it
packed tomorrow against a sun that cost nothing for a month. **Why it survived:** #755 shipped a
guard, and the guard was `inspect.getsource(SEMCoordinator._shadow_energy_plan)` — a substring check
over ONE named function. A source-inspection guard can prove a fact about the site it names and
about nothing else; siblings are invisible to it on the day it is written and stay invisible to
every commit after. It is the same failure as a keyword search that only knows the word you thought
of. **Closure:** the rate is threaded through all four; one reader (`_configured_export_rate`) holds
#755's reason; and the guard is an AST lint that names no function — it derives the set of *pricing
surfaces* (every module-level function in the package declaring an `export_rate` parameter) and
requires every production call to one of them, including a `builder=` handoff, to pass the rate or
carry an explicit `# UNPRICED: <reason>`. A new wrapper is covered the day it is written.
**Guard:** `tests/test_924_every_day_builder_is_priced.py` (the coverage rule) plus
`tests/test_924_tomorrow_preview_prices_the_sun.py` (the behaviour: at a feed-in richer than the
grid price the preview must move the load off the sun, which unpriced it cannot). **Sweep question:**
for every guard written as `inspect.getsource(<one thing>)` or `assert "x" in src` — does the
invariant it protects have exactly one site, and how would anyone notice when it grows a second?
Refs #924 #871 #755.

### 77. A store's own derived output, read back as the user's testimony — GUARDED
**Symptom:** storacm's pool pump — the switch correctly identified, and the Control card saying
**"Off — SEM won't act"** whatever Mode was picked. Permanent, surviving every restart, and
clearable from no surface at all. **Root shape:** `UnifiedDevice.is_controllable` is DERIVED —
`has_control_handle and not user_hands_off`, the two axes mixed under a name that reads as one.
`_sync_to_load_manager` writes that derived value into the LoadManagement row for EVERY
Energy-Dashboard device, so a device whose switch was not discovered yet writes `False` as
ARITHMETIC. `_adopt_legacy_device_flags` then read that `False` back as proof the user had opted
out, on the written premise that *"the registry always derives those rows WITH a handle"* — which
`_sync_to_load_manager` makes false. A fabricated preference, indistinguishable on disk from a real
one, about a decision nobody had made. **Why it was unrecoverable:** the toggle that could clear it
died in the LitElement migration (14.05.2026) leaving only a dead handler; `hands_off` was accepted
by the service HANDLER but absent from its `vol.In` list, so voluptuous refused the call before it
arrived; and `bool(value)` on a `cv.string` made `"false"` mean true. An axis with a reader, a
store and a handler, and no way in. **The tell it was already known:** `features/device_axes.py`
refuses this fallback in terms — *"reading it here too would count the same bit twice and, worse,
would re-mix the axes this module exists to separate"* — and #650's own test docstring describes
the identical hazard for the re-enable direction, solved there with a one-shot latch. #888 is that
hazard on the fresh-install path, where the latch is deliberately not yet set. **Closure:** adoption
asks `device_axes.user_hands_off`; a one-shot marked migration clears the fabricated flags (safe,
not a guess — the store was created 25.07.2026, its only writer died 14.05.2026, so no value in it
can be a surviving click); and the axis gets an honest writer back in both directions.
**Guard:** `tests/test_888_hands_off_is_the_users_word.py` (structural: adoption calls
`user_hands_off` and performs no `.get("is_controllable")` read; the latch is persisted AND
consulted; a two-store round-trip is reproduced in-process). **Addendum, found live on .175 (08.09):**
the echo lived in a SECOND store. The load-manager persists its own `user_hands_off` per row —
SEM's previous-run output — and adoption, latched only in memory, re-adopted it 35 s after the
registry's copy was cleared. The fix is not to chase echoes but to latch adoption in the store, for
good; and the latch key must distinguish ABSENT (pre-fix store, migrate) from FALSE (post-fix store,
adoption not yet run) — the first draft of that wiped a genuine opt-out on a fresh install's first
restart. **Sweep question:** for every value one component writes and another reads as evidence —
is it a MEASUREMENT of the world, or this system's own conclusion coming back around? And how many
stores does that conclusion live in? Refs #888 #780 #650 #779.

### 78. A `None` guard on a field the producer never sets to None — GUARDED
**Symptom:** arbitrage's "don't sell blind" guard was `if soc is not None and soc > floor`, and it
never held: a sell already under way continued through a SOC dropout for as long as the link was
down, on setpoint batteries with no hardware reserve-stop behind it (found by the ruflo audit of
arbitrage mode, 08.09.2026, before it was ever switched on). **Root shape:** `BatteryRuntime
.last_known_soc` is a `float` defaulting to `0.0`, built as `float(... or 0.0)` — it is NEVER None.
The reader HOLDS the last valid SOC through a dropout and reports the darkness on a twin flag
(`battery_soc_unavailable` → `runtime.available`), which the decision never read; the multi-battery
runtime hardcoded `available=True` with the comment "populated → it reported this cycle", which a
held value also is. The guard tested the wrong axis. **Why the suite was green:** three tests
"proved" the hold by hand-building `last_known_soc=None` — an input the pipeline cannot produce
once a reading has ever succeeded. Same vacuity as class 76's cousin the same afternoon (a test that
hand-fills the dicts a fix sums): the test exercised the arithmetic of a branch the product cannot
reach. **Closure:** both sell gates ask `rt.available`; the multi-battery runtime fills it from the
per-unit or fleet flag; the tests build the HELD-nonzero shape production actually makes, and keep
the `None` variant as a harmless extra. **Guard:** `tests/test_battery_arbitrage_523.py::
test_force_discharge_holds_on_a_HELD_soc_the_shape_production_makes` and siblings, `tests/
test_638_c6_arbitrage_sell.py::test_a_HELD_soc_holds_not_sells`. **Sweep question:** for every
`x is not None` guard on a dataclass field — what is the field's default, and can the producer
actually assign None to it? If not, the guard is decoration and the real "absent" signal lives
somewhere else. Refs #932 #531 #875 #925.


### 79. A boolean "dark this cycle" flag read as "let go" by a LIMIT writer — a blink becomes a write pair — GUARDED
**Symptom:** charge pacing (#820) restored the inverter's charge-limit register on every SOC
blink and re-engaged it the next cycle: two `number.set_value` writes per modbus dropout, ~500 a
day on PROD's Huawei link (250 blinks/day, 10.8 % of wall time, measured 08.09), a cap that flaps
between "restored to 5000 W" and the pace every few minutes, and the #538 collision class one layer
up on the single serial link. **Root shape:** `_hold_battery_soc` holds the last accepted SOC
through a dark cycle and raises `battery_soc_unavailable` on EVERY such cycle — the flag is boolean
and cannot tell a one-cycle blink from a sustained outage. `_run_charge_pacing` read it as "no SOC"
(`soc=None` → no decision → `cap=None` → the writer's disengage-and-restore), so an actuator whose
side effect is a LIMIT — safe to hold through a blink, a cap is not an action — behaved like one
whose side effect is an ACTION (the #932 sell, where acting on a held SOC IS the danger). Same
family as class 58 (which DIRECTION does the fallback err in?) and class 62 (a filter sized for a
one-sample fault): the honest fallback for a limit is zero-order hold with a bound on how long.
**Live catch (#934, PROD/.46 08.09, while setting up the #820 real-day proof).** **Closure:** the
hold carries its age — `PowerReadings.battery_soc_stale_s`, seconds since the last ACCEPTED read
(None when read this cycle and before any read; a dark reading that carries NO age is not a hold a
limit may ride — fail-closed for any producer that raises the flag without stamping it); the pacer decides on the held SOC while `battery_soc_known` and the age is within `SENSOR_DARK_READ_GRACE_S` (the grace the entity layer already uses
for dark reads), and disengages — restoring ONCE — only past it; `charge_pacing.soc_stale_s`
publishes the age so a blink shows as a small number under an unchanged cap, and an expired hold
carries its own token (`soc_expired`, age still counting) so a sustained outage is never read as a
restart's never-read window. The rule is ONE module, `coordinator/soc_grace.py`
(`soc_for_a_limit` + `soc_hold_expired`, one boundary) — the sanctioned path for every limit that
reads a SOC. Action-type gates (#932 sell, VPP force-discharge, the #925 spend budget's rule 4)
keep the boolean: they must stop blind — and each pays the SAME blink cost this class names, on
the action side: the sell gates (`decide_battery` manual force_discharge + the #533/#778 sell) and
the VPP export force op return NORMAL for the dark cycle and FORCE_DISCHARGE the next, a
stop/start pair on the forcible-discharge register per blink while a sell runs (Huawei:
`_stop_forcible` then `command_force_discharge`; ~30 pairs over a 3 h evening sell on PROD's
link); the spend budget's rule 4 zeroes one cycle's `battery_spendable_kwh`, which closes the #537
EV gate for that cycle at night (whether the charger reconciler absorbs a single-cycle drop was
not measured). The sell-side pair is absorbed by nothing: the #818 hold covers power-derived
intents only, and the SOC is not a degradable input. Bounding an ACTION by the same 180 s grace
(the held value is above the floor by construction for that long) is Guido's call, not this
fix's — the bound exists so that decision can be taken. **Guard:**
`tests/test_934_pacing_holds_through_a_blink.py` — the reader stamps the age (dark AND
#902-rejected holds, counted from the last accepted read), a blink is `held` with the wire silent,
the boundary is the grace constant, a sustained outage restores exactly once; and
`tests/test_934_dark_soc_reads_declare_themselves.py` — the FLEET-READ pattern: every direct read
of `battery_soc_unavailable` in `coordinator.py` must carry `# DARK-SOC: <display|record|plan|
action> — <why a one-cycle edge is acceptable>`, the pacer has none and calls `soc_for_a_limit`,
so the next limit-type consumer cannot read the boolean without declaring itself. **Sweep question:**
for every actuator that maps an `*_unavailable` flag to "no decision", is its side effect a LIMIT
(hold it through a blink, bounded by the grace) or an ACTION (stop blind)? And for every held
value, can its consumer read HOW LONG it has been held? Refs #934 #820 #932 #902 #875 #818.

### 80. A physical bound on ONE addend of a pool; a second addend joins the sum below it — GUARDED
**Symptom:** a "Solar only" load runs at night, for hours, with the sun at 0 W — and the very
invariant written to make that impossible is provably in force: the export surplus reads 0.0
every cycle. The load's progress bar books the run as "on solar". **Root shape:** an allocation
pool is a SUM (`surplus + reclaim`, `bare + redirect`, `distributable + virtual`), the invariant
("you cannot have more solar surplus than the sun produces", #620) is enforced on the first term
where it was first needed, and a later feature adds a second term that enters the pool AFTER the
bound. Each term is individually justified; the sum is what the actuator sees. The second term is
usually a *measured* quantity re-labelled as solar on an unstated assumption — here "the power
charging the battery would otherwise be solar surplus" (#576), which holds for an inverter left
alone and fails the moment the pack is filled from the grid by something SEM did not command (an
inverter TOU window, an external EMS; the U6 "commanded battery is honoured" gate only sees SEM's
own commands). **Live catch (#938, alexmc1510, 09.09.2026):** Solar-only pool pump,
4 h/day target, on at 01:29, on again 01:45 after a manual off, off 06:03 when the charge ended
— "4.3/4 h on solar today"; reproduced on 2.0 and 2.1.0-beta.9. The EV side of the same shape was
#899 (the redirect credited to the car while a TOU window kept the pack charging from the meter).
**Closure:** bound the SUM at the point where it is assembled, and make the second term physical.
`reclaimable_battery_w(grid_import_w=…)` returns only the solar-funded share of the charge
(`charge − import` — before any load commits this is exactly `solar − house − ev`);
`solar_bounded_reclaim(reclaim, surplus_w, solar_w)` in `surplus_controller.py` enforces
`surplus + reclaim ≤ solar` on the pool the coordinator hands to `update()`. Two independent
ceilings, each fail-closed in its own way: the sun ceiling reads a dark solar sensor as 0 W (the
reader's fallback) and reclaims nothing on a missing reading; the import ceiling rides on the
last readable meter value through a dark cycle (`held_grid_import`, the #934 held-value shape —
the reader's 0.0 fallback would otherwise credit the whole charge for one blink, the #925 rule
that a dark meter is no evidence either way) and reclaims nothing until the meter has been read
once. What rules the *marked* passes (Tier-2 battery, cheap-hours grid) out for this report is
the run length itself: a marked run is ended by the #688 goal gate the cycle `daily_targets_met`
turns true, and this one ran 4.3 h past a 4 h floor — only an unmarked "solar" run does that.
The cycle trace (battery management + loads process records) publishes `reclaim_raw_w` beside
`reclaim_w`, and `import_held_s`, so a night with 3000 → 0 reads as "grid charge, not surplus".
**Guard:** `tests/test_938_night_reclaim_solar_bound.py` — the reporter's
night through the two-line pipeline into a real `SurplusController.update()` walk (the unbounded
pool is shown to START the pump first, so the pass is not vacuous), a sweep asserting
`surplus + reclaim ≤ solar` over the grid, and an AST guard that the `reclaim_w=` handed to
`update()` is assigned from `solar_bounded_reclaim()` in that function and that
`reclaimable_battery_w()` is called with `grid_import_w=` — the reclaim cannot reach the walk
unbounded whichever way the block is refactored, and that the import it subtracts comes from
`held_grid_import` fed by the reader's `grid_power_unavailable` flag. **Siblings swept:** the
EV's bare surplus (`decide.self_consumption_surplus_w`) is `solar − home` and therefore
sun-bounded by construction — the loads' export-plus-raw-charge pool was the odd one out, and
`charge − import` is exactly that same quantity; Tier-1 assist headroom (`_tier1_headroom_w`) is
an opt-in PAID source bounded by its own budget, not a sun credit — not this class; the
`max_export_w` excess is derived from the already-bounded surplus — fine; `_desired_intents`
consumes the same bounded `reclaim_w`; the surplus-available binary sensor reads
`unallocated_w`, which excludes the reclaim. **Open sibling (for Guido):** the EV's *forecast
redirect* fallback (`flow_calculator.battery_redirect_w`, used when the car does NOT reclaim by
position) is neither sun- nor import-bounded — at night `forecast_remaining_kwh` is 0 and the
SoC ≥ 80 % branch redirects the whole grid charge to a `solar_only` car; #899's
commit-then-measure veto is REACTIVE (three contradicting cycles ≈ 30 s, per plug-in, counter
reset by any agreeing cycle), so wherever the #193 night gate is not in force (dusk/dawn) a
nightly plug-in can get a start/stop burst — the #893 stop-rate residual. The preventive twin
is the same `charge − import` share before the credit. **The residual, CLOSED in #953:** `_apply_price_adjustment` added +3 kW
(cheap) / +10 kW (negative) of *virtual* surplus to the same pool for every dynamic-tariff
install (`tariff_mode == "dynamic"`), with no per-device policy gate — a documented feature
(USER_GUIDE "Price-responsive mode") that predated #559's per-device "Finish overnight from:
Grid" and contradicted its "solar_only never grid-forces" contract. Left here as a product call
about which contract wins; #953 made it, on the evidence that the fabricated term breaks
everything the real cheap-hours pass gets right (per-device opt-in, deficit bound, #864
peak-slot guard, a marker the expiry pass and the deficit LIFO can act on) and labels the result
`source="solar"` on the "h on solar today" bar. `price_damped_pool` now clamps to its own input:
a price signal may lower the pool or leave it alone, never raise it. **Sweep
question:** for
every allocation pool that is a sum, *which term carries the invariant, and does every later term
pass through it?* And for every measured quantity re-labelled as a source ("that charge would have
been solar", "that import is cheap"), *what has to be true of the hardware for the label to hold,
and who checks it?* Refs #938 #899 #576 #620 #559.

### 81. A rate limit on the REPEAT of one command, read as a limit on the CYCLE — GUARDED
**Symptom:** the pacing provably works — the log shows exactly one `DISABLE` per minute, as
designed — and the hardware toggles anyway. alexmc1510's switch-controlled charger
(`switch.cargador_coche_carga_de_ve`, 09.09.2026, 22:13–22:19) ran 60 s on / 20 s off for at
least six minutes: the 60 s is `STOP_REASSERT_DWELL_S`, the 20 s is two coordinator cycles, and
nothing at all sat between "SEM wants CHARGE again" and `ChargerAdapter.ensure_enabled` closing
the relay. SEM's own card read `CHARGING (6 A) · 1.8 kW` while the box was off two seconds later.
**Root shape:** a two-direction actuator (open/close, engage/disengage, start/stop) acquires a
minimum interval on ONE direction, written for a *different* problem — de-duplicating a standing
command the box keeps ignoring (#763's re-assert, #392's spam fix). It reads like an anti-cycle
floor, it is named like one, and it bounds only same-command repeats. The cycle rate — the thing
that wears a relay and aborts a car's handshake — stays unbounded, and the faster the opposite
decision arrives, the *less* the limiter has to say. Neighbouring machinery makes it harder to
see: SEM had four steadiness mechanisms on this path (the 4-cycle idle grace, #910's blink hold,
#545's current floor, #763's ceasefire) and not one of them was on this seam.
**Where it lives:** any actuator with a wear budget and two opposite commands —
`charger_reconciler` (the instance), `ev_phase_sequencer` (`MIN_SWITCH_GAP_S` /
`AUTO_MIN_INTERVAL_S`: symmetric, already closed), `actuate_battery`
(`DISCHARGE_LIMIT_LOWER_DWELL_CYCLES`: deliberately asymmetric — *raise fast, lower slow* — but it
is a LIMIT with a 250 W + 50 W hysteresis band, so its up/down cycle IS bounded; not this class),
`device_reconciler` (`EXTERNAL_OFF_COOLDOWN_S`, whose opposite direction is the load's own
`min_on`), and the LOAD side, which is the closed example: `SwitchDevice` / `ClimateDevice` /
`load_management` all carry **both** `min_on` and `min_off`. The charger inherited
`ControllableDevice`'s `min_on_seconds = 0` and no path ever read it.
**Closure:** a floor on the CYCLE, at the one place that emits contactor actions —
`ChargerReconciler.reconcile`. Five decisions carry the fix, and four of them are the interesting
part:
(a) **In `reconcile`, not in `send`/`start_session`.** #940's own fix direction named
`start_session`/`stop_session` — but on the reporter's charger `start_session` selects a mode on a
`select.` entity and the RELAY is closed by `ensure_enabled`, a different branch (class 29 again).
A floor below the reconciler is also a *swallowed* command: the #536 enable backoff would spend an
attempt per cycle on writes that never went out, give up after five, and raise "enable switch
unavailable/locked" on a switch that is fine. A refusal must be visible to the layer that would
retry.
(b) **The clocks arm on a believed TRANSITION, never on a re-assert** — this class's own closure
came within one review of committing **class 73** ("a success that is not an event re-arms the
clock"). `START_AND_WRITE` is re-emitted on every CHARGE cycle once an IDLE cycle has cleared
`_charging_intent_active`, and `DISABLE` once per reassert dwell while a stop is not taking.
Stamping either refreshes the floor from SEM's own idempotent repeats, and under a flapping
decision the minimum ON then **never expires**: measured on the real reconciler, a 20 s flap
produced *zero* stops over 100 minutes — SEM losing the stop entirely, strictly worse than the bug
(class 17). The belief follows a readable enable switch in BOTH directions and stamps nothing when
it does: a relay the box opened has no minimum ON left to protect, and a stop that did NOT take
leaves the relay closed — where holding the close side would also hold the heartbeat current
write that feeds a device failsafe watchdog. A move SEM did not make earns neither the protection
nor the penalty.
(c) **The two floors are not the same number, because they do not cost the same.** The CLOSE floor
is what bounds the cycle (`CONTACTOR_MIN_OFF_S = 300`, `SwitchDevice`'s own default, #688):
delaying a START is always safe, so it needs no exemption and gets the long number. The OPEN floor
(`CONTACTOR_MIN_ON_S = 120`, matching `ev_phase_sequencer.MIN_SWITCH_GAP_S`, this codebase's
existing "minimum gap between contactor operations") only stops SEM opening a relay it just
closed, and every second it holds is a second the car charges against SEM's own judgement — off
the grid or out of the house battery. 120 s bounds that at ~0.05 kWh at 6 A, ~0.37 kWh at 11 kW,
while still exceeding the 40 s idle grace and the 60 s reassert dwell.
(d) **The exemption is structural, not a list.** The OPEN floor delays a DISCRETIONARY stop only —
`DesiredState.IDLE`, "SEM would rather not charge just now". `DesiredState.OFF` never waits,
because every producer of `ChargerIntent.DISABLE` in the tree is a *demand*: the #804 phase switch
(never switch under load), `active_phase_guard`'s conductor protection, the VPP export pause. OFF
already gets no flicker grace on that same reasoning. Mode Off is `RELEASE` and bypasses on its
own row (a swallowed one-shot strands the session — class 17), as does `PARK_OFF` on a real
disconnect. Exactly one demand arrives as an IDLE — the peak EMERGENCY shed — and it says so, via
`ChargerDecision.safety_stop`. Enumerating a safety *list* is how the first cut missed the phase
guard entirely; deriving it from the intent cannot.
(e) **Scoped by `CurrentControlDevice.contactor_surface`** — a charger whose only control surface
is the current number stops by writing 0 A, which is a pilot-signal pause and not a relay cycle;
holding ITS restart for five minutes would cost surplus for no wear saved. That property and
`can_stop_charging` (#627) read ONE extracted dispatch list, `_discrete_contactor_surfaces()`, so
a new brand cannot teach one of them about a mechanism and not the other. The #627 row itself
deliberately does NOT arm the clock: `stop_controllable=False` means that `DISABLE` moves no
relay, and arming a five-minute close floor off a doomed command would lock the CHARGE rows — and
every current correction with them — out while the car keeps drawing.
**Guard:** `tests/test_940_contactor_anticycle.py` — an **invariant oracle**, not a row test:
4000 cycles of randomised desired states against a *coherent simulated relay* (SEM's own commands
move it, plus a 2 %/cycle external flip, and `observed.enabled` reports it), asserting that no
route through `reconcile()` closes the relay inside the minimum OFF or makes a discretionary open
inside the minimum ON — so a NEW row fails here whatever it is called. Around it: the vacuity twin
(the same fuzz with no relay surface must produce violations in both directions — a guard that
cannot fire is class 8), the reporter's own flap replayed against a simulated relay with an
`assert len(history) >= 4` so that "SEM stopped acting" can never read as "SEM stopped cycling",
an explicit class-73 pin that a re-assert does not re-arm either clock, a pin that the heartbeat
write survives a stop that did not take, a pin that the hold does not spend the #536 enable
budget, and an AST pin (not a source substring) that the peak-EMERGENCY clamp carries
`safety_stop=True`.
**Sweep question:** for every minimum interval on an actuator, ask *which* thing it limits — the
repeat of one command, or the transition between opposite ones? If a decision that flips every
cycle can still reach the hardware every cycle, it is the first, and the second does not exist.
Then ask class 73's question of whatever you add: is the clock armed by the EVENT or by the
RESULT? And: is the limited thing's opposite even *in the same function*, or does it arrive by a
route (`ensure_enabled`, a re-assert, a recovery path) whose author never met the limiter?
**Left for Guido:** (1) the clocks are in-memory on the per-charger reconciler, so an HA restart
or an options reload costs one free contactor operation — the #461 stability epochs ARE persisted
(class 7) and these are not. (2) The floors are module constants: a user with a contactor rated
for faster switching cannot lower them, and a KEBA install acquires them (its `enable`/`disable`
IS a relay) with no opt-out. (3) The hold is published — `charger_<id>_anticycle_hold` /
`_hold_s`, `per_charger_anticycle` on the charging-state sensor, `anticycle` in the diagnostics
war snapshot — but no CARD renders it yet; the "holding on for another 2 min — anti-cycle" line
#940 asks for needs a card change plus its translation keys. (4) Whether a switch-only charger
should be offered the amp-shaped modes at all is still open. (5) Observer mode stamps the clocks
for commands `ControllableDevice.send` withholds — the same pre-existing shape as `_last_disable_at`,
so an observer rig's holds are real while its writes are not.
Refs #940 #939 #763 #536 #627 #688 #392 #804.

### 82. A deliberate stand-down announced only in the log — GUARDED
**Symptom:** a backoff makes exactly the right call — stop acting, because acting harder does
damage — and says so with one `_LOGGER.warning`. From outside, "SEM has given up" and "everything
is fine" look identical, while the thing SEM stopped policing keeps running. #944 (PROD
10.09.2026): the KEBA auto-restarted every ~10 min and every stop SEM sent took; then the #763
ceasefire stood down, and the car charged from the house battery and the grid from 18:29 to 19:49.
The owner found out from the battery.
**Root shape:** the reconciler's `REPORT_*` actions are the moments SEM tells the user it cannot or
will not do what it was asked. Three of four reached a surface — #536 `REPORT_ENABLE_BLOCKED` (the
actuation-failure Repair), #627 `REPORT_STOP_UNENFORCEABLE`, #823 `REPORT_FAILSAFE_SUSPECTED` —
and `REPORT_STOP_WAR` reached the log only. A stand-down is not an error, so nobody filed it as
something to *report*; yet it is the one report with a live, unattended draw attached. #799's "a
log line is not a surface" had been applied to refusals and failures, never to a deliberate
decision.
**Where it lives:** every `ActionKind.REPORT_*` (now all surfaced), and every deliberate "stop
trying" path: #536's enable backoff (surfaced), the #940 anti-cycle hold (published — a decision,
not a fault), `charge_stability`'s full-car give-up (the car is NOT drawing; nothing runs
unattended), the grid-sign auto-correction's stand-down in `coordinator.py` (log-only, but a
diagnosis with no unattended draw), and the #548 "commanded STOP N× but charger still drawing"
warning in `reconcile_and_apply` — log-only, and a real sibling (see Left for Guido).
**Closure:** while the ceasefire holds AND the box draws, `_apply_actions` raises a Repair of its own
(`charger_stop_war_stand_down` — not #627's key, which says no mechanism exists; here one works and
the box undoes it), sends one charger notification through `_send_charger_notification` behind
`enable_charger_notifications`, and publishes `charger_<id>_stop_war_stand_down` (+ `_s`, `_w`) →
`per_charger_stop_war` on the charging-state sensor → the EV card's status reads "Charging — SEM
stood down". The Repair and the state follow the CONDITION: raised on the edge, cleared the cycle
it stops being true (the draw stopped, the war ended, or the window closed and SEM is stopping
again). The warning and the notification are once per CEASEFIRE, keyed on a never-reset serial: the
old "re-arm on any other action" flag missed a second ceasefire entered straight from a pause and
double-pushed across a #823 clear. The draw stopping *inside* the window retires after the 2-cycle
debounce a disconnect gets — a draw flapping at the threshold would otherwise delete and re-create
the Repair (and the user's "ignore") every other cycle. The Repair is updated in place when what it
says goes stale: a new ceasefire that began without the draw ever stopping (a longer window), or a
status-only onset read at 0 W once the watts arrive. Every charger — including the late-discovered legacy `_ev_device`, which
the per-charger loop never linked — gets its `_coordinator` link in the every-cycle both-shapes
walk (`_push_observer_mode_to_devices`), so the push cannot die on the branch that skipped it
(class 29). The Repair is non-persistent (the ceasefire lives in memory)
and a fresh reconciler clears once (an options reload rebuilds it mid-stand-down). Observer mode
keeps the Repair but not the display message — an observer rig may share the physical box. The
warning also names the real window (30/60/120/240 min), not always 30.
**Guard:** `tests/test_944_stand_down_surface.py::TestEveryReportReachesASurface` — an oracle
parametrized over every `ActionKind.REPORT_*` member, driving the real `_apply_actions` and
requiring a non-log surface (an issue-registry write or an adapter `report_*` hook): a new report
that only logs fails CI whatever it is called. Its vacuity twin strips #944's surface and must see
the oracle fire. Around it: the stand-down driven through `reconcile_and_apply` (one Repair and one
notification across 30 drawing cycles; cleared by each of the three war endings; re-raised without
a second push after a pause), observer mode, the user's switch, the doubled window, the sensor
attribute, the node test on the card's status key, and the adversarial review's catches — a
ceasefire entered from a pause is announced, a #823 clear is not a second push, a flapping draw
does not churn the Repair, a 0 W onset is corrected, the legacy charger is linked
(`TestOncePerCeasefire`, `TestTheSurfaceHoldsSteady`, `TestEveryChargerCanReachTheNotifier`).
**Sweep question:** for every place SEM decides to STOP acting — a backoff, a ceasefire, a give-up,
a hold — what is still running while it holds back, and who can see that it is holding back?
**Left for Guido:** (1) The #548 stop-not-taking sibling: a box that ignores SEM's stop *without an
error* never settles, so no war round counts, and it is warned at 3/12/60 cycles in the log and
nowhere else. A Repair there needs field evidence first — cloud-polled chargers (Zaptec) can show
power for minutes after a stop that did take, so a naive threshold would cry wolf. (2)
`_send_charger_notification` resolves ONE notify service for the whole fleet, so on a two-charger
install the display message can land on the other box — pre-existing for every charging-state
message. (3) The not-drawing row's quiet reset clears the war's rounds after an hour of quiet but
not a 4×/8× ceasefire's window, so a box that returns 1–3 h later can still meet a standing
ceasefire with zero rounds — pre-existing, surfaced now, unchanged (fighting harder is out of
scope).
Refs #944 #763 #627 #823 #536 #548 #799 #942 #940.

### 83. A latch scoped wider than the evidence that set it — GUARDED
**Symptom:** a one-shot verdict fires where its evidence never was. A charge SEM itself just
re-started is "complete" 30 s later at 71 %; an announcement meant to fire once per charge
alternates with its opposite several times a minute. Each latch is set correctly — the bug is
where it is still believed.
**Root shape:** a latch is SET by evidence about one key — one offer, one bound, one regime — and
READ or CLEARED at a scope wider than that key: the session, the charger, "any bound". Nothing asks
whether the reader's key is the setter's, because the latch is a bare flag and carries no key.
Two ways it breaks: it is *consumed* under a key it was never earned under (the decline of the
charge before, scored against the silence after SEM's own re-offer), or it is *released* under a
key whose condition is true for unrelated reasons (stopped at Min, released by Max) — and then set
and clear can both hold on the same inputs, so it ping-pongs every cycle.
**Live catches (#939, 09.–10.09.2026, Victron EVCS + Tesla):** (1) `EVTaperDetector.update` — the
#708 withdrawal guard paused the full-confirm while SEM's offer was withdrawn but left
`_declining_phase`, and the samples that latched it, standing; the 20:45 re-offer went unanswered
for 70 min and three samples later the pack was anchored full. (2) The #708 estimate-stop
announcement — `_estimate_stop_active` was one bool for the Min/Max loop; Min's stop set it, Max's
resume released it, Min set it again. An earlier member, before the class had a name: the #708
recovery clear (`TestADeclineDoesNotOutliveTheRecovery`) — the same decline latch outliving the
recovery that refuted it.
**Live catch (#940, 14.09.2026, alexmc1510's charger — select start + enable switch):**
`_session_active` — the flag `GenericAdapter.command_current` reads to decide whether to call
`start_session` at all — was set by `ChargerAdapter.ensure_enabled` (#536) on the strength of a
`switch.turn_on`. Its evidence is about the ENABLE surface; its readers are about the brand's
SESSION START, and `start_session` is an elif chain in which exactly one of four mechanisms fires.
Where the start is a charge-mode select or a brand service the two keys are different entities, so
the claim was never earned — and because the reconciler prepends its ENABLE on exactly the cycle
where the enable switch is off (the transition out of a stop, which SEM's own stop caused), the
brand start was suppressed on the ONE cycle that needed it, on every charge, forever. The box stayed
on its own mode, dropped the switch, and five re-asserts later SEM filed
`charger_actuation_failed` ("enable switch will not stay on") against healthy hardware — while the
relay cycled once per coordinator cycle from UNDERNEATH #940's anti-cycle floor, whose clocks arm
only on SEM's own operations and so never saw the box's opens.
**Live catch (#820, 05.10.2026, ArneGollin1987's Sungrow — mkaiser template number):**
`ChargePacingWriter._taken` — the verdict on ONE write (`last_written_w`) — was what `apply`
published as the pacing action. One lost write (a Modbus error, a template script still running)
left `write_refused` on the Battery tab while the register sat at exactly the cap SEM wanted: the
re-solve came back to the register's value, nothing was left to write, and the old verdict was all
the action could say. The same shape on the first cycle after a restart: a cap from disk that is not
on the register was rewritten even when the register already held the wish — a write equal to the
register never reads as taken, so a healthy inverter was "refusing" 90 s later. Closure: a register
inside the writer's own deadband of the CURRENT cap is `held`. The verdict itself is kept — the
02.10 rule that a refused cap is not sent again is keyed to it, and a register at the wish says
nothing about whether it takes writes (review 2: retiring it re-sent refused caps every 5 minutes
on a register that never takes one). Only the first cycle after adoption, where no write of this
lifetime was judged, takes the register's value as the cap (`_take_register`, no write). A
register away from the wish still says `write_refused`. Guard:
`tests/test_820_refusal_belongs_to_its_write.py` — over seeded days of random caps and lost writes,
`write_refused` never appears on a cycle where the register holds the wish, with liveness twins
(refusals do happen, and a refused verdict does meet a register at the wish); the refused cap is
still not re-sent; the restart case writes nothing.
Siblings assessed: the battery adapters' `write_not_taken_strikes` (#915) raise a Repair keyed to
the entity, and a same-value skip is no evidence either way, so the raise stays as it is — its
install-wide clear is the known residual, class 84 (4). **Left for Guido:** (1) a refused cap is
never sent again while the wish stays near it (the 02.10 rule, pinned by
`test_a_refused_cap_is_not_retried_with_a_slightly_different_value`) — one lost Modbus write keeps
the old cap until the wish moves; a single retry after `PACING_MIN_WRITE_INTERVAL_S` would close
it, a policy call. (2) `coordinator/export_guard.py::report_refused` — one transient
`export control failed` holds `refused` for the whole closed-meter window with no retry: one
write's verdict standing for the window.
**Where it lives:** `coordinator/charge_pacing.py::ChargePacingWriter.apply` (`_taken` vs the
current cap), `coordinator/ev_taper_detector.py` (`_declining_phase`, `_full_confirm_count`,
`_estimate_stop_bound`), `coordinator/ev_soc_need.py::estimate_stop_step`,
`coordinator.py::_announce_estimate_stop`, `coordinator/charger_adapters/base.py::ensure_enabled`
with `devices/base.py::CurrentControlDevice._session_active`. Sibling assessed and safe: the
notification manager's stop/resume flags release each other, keyed by charger id — harmless once the
latch upstream is keyed; `notify_ev_nearly_full` sets and clears on one predicate, one key. Swept
with #940: `release_to_user` (#935) re-derived the same start chain by hand and now reads the one
resolver (a derived AST lint, not a list, holds every future dispatcher to it);
`ChargerReconciler._stamp_close` stamps SEM's OWN command history and is corrected by the
belief-follow, so its key is its evidence.
**Closure:** the latch carries its key, and every reader and clearer is restricted to it. A fresh
offer (setpoint 0 → > 0) clears the decline latch, the confirm count and the trend buffer — the new
charge re-earns it from its own samples; absence of an offer (observer mode) never crosses the edge.
The estimate latch holds the bound it was set at (`_estimate_stop_bound`; `_estimate_stop_active` is
derived from it); only that bound's effective need re-opening resumes, naming the first re-opened
bound (a reading back under Min is a top-up to Min). When the sensor itself reaches the latched
bound the latch releases silently and frees the notification manager's stop flag, so the next
estimate stop (Max, the next day) is still announced — the old bogus resume had done that by
accident (liveness, caught in review).
**Guard:** `tests/test_939_estimate_latch.py::TestIdenticalInputsNeverAnnounceTwice` — over a grid
of sensor / cap / Min / Max, a clear latch announces at most once across 30 identical cycles and no
latch more than twice (safety), and a stop that falls due once the latched bound's sensor has caught
up is announced within two cycles (liveness); the vacuity twin runs the old bare-flag rule through
the safety property and must fail on the live numbers. `tests/test_939_reoffer_is_not_a_taper.py` —
the live evening (decline under a withdrawn offer, 6 A re-offer, 70 min of silence) on a simulated
10-second clock must not anchor, with the latch pinned as set beforehand so it cannot pass on a
detector that never latched. `tests/test_940_enable_is_not_a_session.py` — the #940 half: over the
cross-product of every session-start mechanism × every enable surface, a transition out of a stop
driven through the REAL reconciler + adapter + device must dispatch that charger's OWN session start
exactly once; the vacuity twin restores the #536 rule and must FAIL on precisely the shapes whose
start is not the enable entity. `CurrentControlDevice.session_start_mechanism()` names the branch
once, so the chain and its three readers cannot drift.
**Sweep question:** for every latch — what KEY was its evidence about (which offer, bound, device,
window)? Is every site that reads or clears it restricted to that key, and can its set and clear
conditions both be true on the same inputs?
**Left for Guido (found in #940's review, all pre-existing, none a gate on it):**
(1) `devices/base.py::park_off`'s stop chain is not merely ordered differently from `stop_session`'s
— it is INCOMPLETE: it knows `<domain>.disable` and a `start_stop_entity` switch, and consults
neither `stop_service` nor `charge_mode_stop`. An Easee or a go-e with no start/stop switch gets
NOTHING on the car-left edge, `_parked_it` stays False, the park is never remembered, and the box is
left enabled for the next plug-in to auto-start — the one thing park-on-disconnect exists to
prevent. The start side now has a resolver; the stop side wants the same one, but it is a real
behaviour change on two brands' disconnect path and needs its own issue.
(2) `coordinator/charger_adapters/wallbox.py` — `_toggle_pause_switch` flips a real relay on every
`command_current`/`command_idle`, while `contactor_surface` reads only the CONFIGURED dispatch list
and answers False for a registry-discovered pause switch. #940's anti-cycle floor is therefore off
on exactly the surface that is cycling — this class's #940 catch arriving through a door #940's own
predicate cannot see. `_looks_like_wallbox` also never inspects `current_entity_id`, so the typical
Wallbox config (a bare `number.wallbox_*_charging_current`) gets `GenericAdapter` and #357's fix is
off; and `charger_current_entity`, read three times there, is assigned nowhere in production (class
74). (3) `ensure_enabled`'s `button.` branch is unreachable from the reconciler — `enable_state()`
answers `(None, True)` for a stateless surface, so ENABLE is never emitted for one and #804's press
arrives via `start_session` instead. Not a regression, but #804's resume surface is not the live
path its tests imply.
**Left for Guido:** the stall-to-full path in `_update_ev_intelligence` ("0 W for 3 min under a
≥ 6 A command → SOC 100 %") reads an unanswered offer as a full pack — this class's inference with
no latch in between. Its comment says legacy-only, but the code runs on every install and writes
into the primary per-charger detector through the computed `_ev_taper_detector`; on #939's evening
it would have anchored full at ~20:48 had the taper not got there first. #756 N1 ("a car that had
declined six start ladders") may lean on it, so it is not a cheap sweep. The re-offer clear has a
cost of its own: a car whose last taper was cut short by a withdrawal and that stays silent after the
re-offer is never taper-anchored. The primary charger has the stall path behind it; a non-primary
kWh charger has nothing, which widens #756 N1's existing gap there (a car that arrives full is
already never anchored on a non-primary).
Refs #939 #708 #774 #756 #940 #536 #935.

### 84. A memo that dies before the thing it reconciles — the first verdict of a lifetime is swallowed — GUARDED
**Symptom:** a Repair outlives its own remedy. The user does exactly what it says, the log confirms
the change took, and the Repair is still in Settings → Repairs forty minutes later — and after every
restart since.
**Root shape:** HA's issue registry keeps a persistent Repair across restarts, and a config-entry
reload never touches the registry at all — but the flag that decides whether to clear is an instance
attribute, reset by every restart and every options reload. Two spellings: (a) *act on change*
against a memo whose empty value is also a verdict — `seen.get(id) == pinned` starts at None, "not
pinned" is None, so a fresh owner's first verdict equals the empty memo and is dropped; (b) *clear
only if raised* — `if eid in self._raised: clear` — so a Repair a predecessor raised is never in this
lifetime's set. Either way the fresh owner that most needs to reconcile — the reload a remedy
triggers (`set_option` → `async_reload`), the restart after a fix — is the one that cannot. #485 H5
(actuation failure) and #944 (`_retire_stand_down` from None) had each closed one instance by hand;
the shape had no name, so the next Repair repeated it.
**Live catch (#933, PROD 08.09.2026, Huawei SUN2000 + LUNA2000):** the #919 "Battery platform pinned
to Generic" Repair. `battery_charge_platform` → auto via `set_option`, the adapter came back as
Huawei, the Repair stayed.
**Where it lives:** every memo-gated Repair clear. Fixed here: the pin check (#900/#919), charger
control entity (#824), battery write-back (#915), sensor unavailable and sensor stale
(`sensor_reader`), load-shed futile (#896), no forecast integration, force-discharge refused (#840),
the operating-mode watch (#845 — non-persistent, but it survives an options reload), and the
split-grid guess (#911) — its text tells the user to set the pair in SEM's options and promises "this
notice clears on the next read", but that write reloads SEM onto the manual path, which never touched
it, and the unconditional clear in `invalidate_split_grid_cache` hangs off
`EVENT_HOMEASSISTANT_STARTED`, which a reload never fires. Assessed and already safe: SOC-zone order
(#870 — its verdict is a bool, so the None memo never matches), actuation failure (#485 H5),
stop-war stand-down (#944), and the heat-pump / hot-water / KEBA / SOC-cap / wrong-unit / backfill /
no-recorder / Deye Repairs, which clear on every current verdict.
**Closure:** the first healthy verdict of a fresh owner clears once. Each owner keeps a "reconciled"
memo (or starts its verdict memo at *unseen*, never at a value the verdict can take) and treats its
first healthy verdict as an edge. "Healthy" means evidence this lifetime saw: a reflected write names
the entity it proved; a stale sensor clears only once this reader has SEEN its report stamp move — a
restored state looks fresh for ten minutes after a restart and proves nothing (its source reporting
while it holds still does, #912); an accepted 0 W write proves nothing about discharge. A first
verdict is only a verdict when the question could have been answered: "not pinned" while a
Huawei/GoodWe entry is still loading (HA is `is_running` from `starting` on; SETUP_RETRY) is "not
yet", not "no" — acting on it would delete the Repair, and the user's "ignore", only to re-raise
it. One Repair id for
several units is one verdict: the pin Repair is decided for the install once every battery has
answered, because a first-verdict clear per battery would let a healthy second battery take down the
first one's Repair.
**Guard:** `tests/test_933_memo_gated_clear_registry.py` — an AST detector over all production code.
A Repair clear (direct, or through a thin wrapper) is *memo-gated* when a condition guarding it — an
enclosing `if`/`while`/`for`, or an earlier early exit — reads instance state the same function
writes. Every memo-gated function is declared with its answer to "who clears the Repair a previous
lifetime left?"; a new one fails CI until answered, and a stale declaration fails too. The
detector's twin fires on the #933, #824, #915 and #840 shapes and not on a reading or an
unconditional clear; a floor on the site count stops a walker that parses nothing. It cannot see
a memo on a helper object built elsewhere, a raised-set mutated only through a helper method, a memo
in `hass.data`, or a clear delivered as an action (#823) — the registry makes each new site ask the
question; the behaviour tests prove the fixes. Behaviour:
`tests/test_933_first_verdict_of_a_lifetime.py` drives each owner the way a reload does — fresh
owner, healthy first verdict, the clear exactly once — with every verdict formed by production code
(the real `pinned_generic_brand`, the real generic adapter's read-back, the real sensor reader).
**Sweep question:** for every durable effect SEM reconciles — a Repair, a persisted flag, a register
it wrote — does the memo that decides "already done" live at least as long as the effect? If not,
what does a fresh owner's first verdict do?
**Left for Guido:** (1) #823 charger failsafe-suspected: its clear is an `ActionKind` emitted only
while `_failsafe_reported` (in memory) and a learned interval hold, so a fresh reconciler can never
produce it. What proves the box healthy without the learned interval is a decision, not a sweep —
and an action-mediated clear is invisible to the AST guard. (2) A Repair keyed on an entity the new
config no longer writes (a platform switch, a renamed entity) has no owner left to clear it at all:
the orphan sweep the heat-pump and hot-water Repairs have, not generalized. (3) The #845 mode watch
is built on the first cycle, before any battery adapter exists, so on an auto-detected platform it
has no expectation and stays publish-only for its whole life: the #845 Repair is dormant everywhere
but an explicit `huawei` platform (the #919 shape — a question asked before the thing it asks about
exists). Turning it on raises a new Repair on live installs: a decision, not a sweep. (4) #915's
clear is install-wide within the primary adapter: any reflected write clears every raised write
Repair, including one for another entity that still ignores writes (class 83's shape; pre-existing).
(5) The pin verdict's first cycle is SEM's battery set at that moment: a synthetic `primary` that
later becomes b1/b2 with a different per-battery platform can clear once and re-raise.
Refs #933 #919 #900 #824 #915 #840 #845 #896 #911 #485 #944.

### 85. A restart re-adopter reads an axis the device is not commanded on — or none is called — GUARDED
**Symptom:** after a reload or an HA restart, a boost SEM wrote stays in force on the device while
SEM believes the load idle. A hot-water tank keeps SEM's 50 °C setpoint and its own thermostat
reheats to it at three in the morning; an SG-Ready heat pump stays in BOOST all night. Nothing ever
releases it — the belief says idle, so no stop path visits the load.
**Root shape:** #656 decided that a reload and an HA restart leave loads exactly as they are and
rely on SEM re-adopting them when it comes back (`adopt_if_running`, #559). The re-adoption can be
silently absent two ways: (a) the registration site never calls an adopter — the direct controllers
in `async_setup_entry` (hot water, every heat pump) were registered bare while the registry's two
sites did call it; (b) the adopter a device inherits reads the wrong axis — `SwitchDevice` asks
`state == "on"`, but a water_heater's state is its operation mode ("heat_pump", "eco"), a climate's
its hvac mode, and an SG-Ready pump's truth is a relay PAIR. The per-cycle nets miss them too: the
#766 belief sync is switch-domain only, the reconciler files a setpoint tank as `external_on` and
deliberately won't fight it, and SETPOINT devices reach neither.
**Live catch (#914, hoyte, 2.0.0, monoblock heat pump behind a water_heater DHW entity):** "SEM has
kept the state on with a setpoint of 50 during the night … when the tank dropped below its
hysteresis it activated in the night."
**Where it lives:** `__init__.py::async_setup_entry` (the direct registrations);
`SwitchDevice.adopt_if_running` / `_adoptable_now` (the predicate); `HotWaterController`
(water_heater / climate — the setpoint); `HeatPumpController` (the relay pair through the #523
NC-inverted truth table, or a #801 service pump's state entity).
**Closure:** the adoption and its gated claim stay one body; the predicate is per device and reads
the axis SEM writes. A setpoint tank is adopted only while it holds one of SEM's OWN boost setpoints
(solar or legionella target, ±0.5 K); a setpoint SEM never writes is never claimed (#847/#908:
release what SEM commanded, nothing more), while one that EQUALS SEM's boost cannot be told apart
from it and is — the claim #766 already makes for a switch turned on in Solar mode. A climate tank
is adopted only in SEM's `heat` mode (the `ClimateDevice` line); an SG-Ready pump only in BOOST /
FORCE_ON. One decision per lifetime (a reload is a new one), on the first READABLE observation
within ten minutes of registration: an entity whose integration is still loading on an HA restart
keeps the window open and the per-cycle belief sync retries it; after that — or once the window
closes unread — SEM never claims a boost it sees start.
**Guard:** `tests/test_914_boost_survives_restart.py` — an AST check that every non-EV
`register_device(x)` in `async_setup_entry` is preceded by `x.adopt_if_running()` (with a floor
naming `hw_device` and `hp_extra`, so it cannot pass vacuously); the per-domain adoption family
(adopted / left alone / unreadable → pending); and the end-to-end night — adopted after a restart,
a no-surplus cycle releases the tank and returns the pump to NORMAL.
**Sweep question:** for every command SEM leaves on a device — a setpoint, a relay pattern, a mode,
a register — what does the NEXT lifetime read to learn it is SEM's, and does that read look at the
axis the command was written on?
**Left for Guido:** (1) A climate-only heat pump (the `SetpointDevice` climate boost, normal +
offset): its boost is a thermostat setpoint the user also owns and cannot be told apart from their
own choice — not adopted, still strands across a restart; `SetpointDevice.deactivate` also returns
early on `_boosted = False`, so an adopted one would not be restored either. (2) A #801 service pump
without `sg_ready_state_entity` is unobservable — not adopted. (3) The hot-water release is
`turn_off` first, which leaves SEM's boost setpoint armed on the tank for whatever turns it back
on; the reporter's ask — release to the minimum setpoint and leave the tank on — is the product
decision that settles both (enhancement). (4) A direct device's control mode (Off / Peak-only) set on
the card is persisted but never re-applied after a restart — `refresh_direct_device_overrides`
carries priority and goals, not the mode. Re-applying it naively would flip every direct device the
#805 upgrade froze at `peak_only` (it pins every id in `priority_overrides` / `device_goals`): a
decision, not a sweep. (5) The tank predicate recognises SEM's boost by VALUE: a setpoint set by
hand that equals SEM's target (50 °C by default) is claimed after a reload, and a solar target
changed in the options between the boost and the reload is no longer recognised. Persisting the
commanded setpoint (entity + value, set on activation, cleared on release) would make the claim
exact — storage plumbing and a decision, pinned as-is by `TestTheClaimIsByValue`. (6) Pre-existing,
found in this change's review by reading (not reproduced): a legionella cycle has no exemption from
the deficit LIFO. `check_legionella_cycle` starts it with a bare `activate()` (no ownership, no
clock); the next no-surplus cycle sheds it, and the cycle then sits in `heating_to_target` without
ever re-heating. A tank adopted at 65 °C after a restart is released the same way.
Refs #914 #559 #656 #766 #779 #847 #908 #523 #801.

### 86. Absence of evidence spent as evidence — a warm-up read taken for a fact — GUARDED
**Symptom:** a Repair appears seconds after every HA restart, names a device that is fine, and
describes something that never happened. alexmc1510 (#945, 2.1.0-beta.14) got "SEM's last 3+ current
commands to EV Charger were rejected … The charger is NOT under SEM control right now" on a restart —
no current command had been sent at all.
**Root shape:** a counter built for POSITIVE evidence (a command that RAISED, a write the entity
CONTRADICTED) is reused as a convenient debounce for an observation that is merely ABSENT —
`hass.states.get()` returns None for every entity whose integration has not finished loading, and
`unavailable` is what the rest report meanwhile. The counter's threshold is expressed in CYCLES, so
its real patience is whatever the coordinator interval happens to be (3 × 10 s = **30 seconds**),
while a restart makes every integration absent for minutes. At the counter the two inputs are
indistinguishable, so the Repair then describes the wrong one — and being persistent and ERROR, it
outlives the warm-up that caused it.
**Where it lives:** any surface that feeds "I cannot read or command X" into the evidence counter for
"X refused me". `ChargerAdapterBase.report_enable_blocked` → `CurrentControlDevice.
_record_actuation_failure` (the instance); `write_not_taken_strikes` → #915's
`battery_control_write_not_taken`, which raised on a healthy battery about three cycles into a
restart (**swept here**, at the *raise* site rather than the verdict: `verify_pending_write` reports
a vanished entity as "reads missing" deliberately — that string is the evidence the Repair shows the
owner, pinned by `test_an_entity_that_vanished_counts_as_not_reflected` — so the adapter's verdict is
untouched and `_raise_or_clear_battery_write_repair` holds a SILENT entity for the wall-clock window
while a contradicted one still files at once). *Assessed and already safe:* `sensor_reader`'s unavailable/stale
Repairs and #824's control-entity pre-flight — both wall-clock `UNAVAILABLE_REPAIR_THRESHOLD_S`, and
the precedent this row generalises; #840's unsupported-capability count (three RAISED refusals — real
evidence); #627 `can_stop_charging`, whose input is config, not a live read (`_bound_to_entity_range`
answers "unknown → don't cry wolf" on an unreadable entity). *And the second consumer* (round 3):
any SETUP-time read that spends an absence on CONFIGURATION rather than on a verdict —
`register_ev_charger` nulling the configured current entity (#991, the instance) and
`_warn_missing_charger_entities` (#763, already deferred 120 s). `wire_current_entity` (#976) reads
the entity REGISTRY, which is persisted across restarts, so it is class 87's question, not this one;
`_check_charger_control_entities` (#824) is not on this half at all — it runs per-cycle off
`_async_update_data` and spends its absence on a verdict, which is the half above.
`ast_contracts.absence_spent_as_config` is the standing sweep of the config half.
**Closure:** an entity-absence verdict is held on the WALL CLOCK, never on a cycle count, and the hold
is the one constant `UNAVAILABLE_REPAIR_THRESHOLD_S` (#611's warm-up) rather than a fresh literal
(class 46). Evidence counters stay for evidence: a command that raised keeps its three-strike
contract (#462, framework-tier), and the absence path neither increments that counter nor is cleared
by it — they share one issue id, so the write side owns the Repair whenever it has spoken. The
clock's OTHER half must be retired by the CONDITION ending, and the condition is "is SEM asserting
this surface and not getting it?" — asked of the emitted actions, never of "can I read the entity?".
Both halves of this fix got that wrong first and the error is instructive: a switch that is READABLE
but stuck `off` (#536 Eco-Smart, the re-assert budget spent) is `enable_controllable=True` and blocked
at the same time, so a hold retired on readability resets every cycle, never elapses, and makes that
Repair unfileable — strictly worse than the bug, because the retire also deletes one a previous
lifetime raised. Likewise a *write* is evidence about the entity it was written to and no other:
zeroing the hold on a successful current write let a 0 A stop (one per 60 s reassert dwell, on every
non-KEBA stop) starve a 300 s window forever.

**Round 2 (#945, 2.1.0-beta.25) — the exemption was the bug.** Round one concluded from the above
that only silence waits and that the readable-but-`off` switch keeps its three-CYCLE speed, being
"evidence: SEM wrote `turn_on` five times and watched it come back off". alexmc1510 restarted onto
beta.22 and got the identical Repair with the other sentence in it. Two things were wrong. First, the
three cycles that FILE it are cycles on which SEM sends nothing at all — the reconciler returns
`REPORT_ENABLE_BLOCKED` *alone*, so a successful write cannot flap the notice — so the verdict was
three observations wearing the #462 counter whose Repair says "your last 3+ current commands were
rejected". Second, a restart reaches that branch: the entity appears partway through the warm-up
still reading `off`, because its integration has not reached the box yet, and 5 re-asserts + 3 reports
is 80 s. **The episode is the unit, not the sub-case.** "SEM is asserting this switch and it is not
holding" opens ONE wall clock spanning both the unreadable stretch and the re-asserts, retired only
by a cycle that emits neither `ENABLE` nor `REPORT_ENABLE_BLOCKED` — the re-asserts ARE the episode,
and treating them as quiet cycles also DELETED a standing Repair once per switch drop and re-raised
it five cycles later (the write side's churn, one layer up). Each sub-case keeps its own sentence
(`repair_issues.ENABLE_UNREADABLE` / `ENABLE_WILL_NOT_HOLD`, spelled once — class 46), and a charger
whose `enable_state()` answers `(None, True)` — KEBA, a service, a button: no readable switch AT ALL
— files nothing, because there is no surface here to be blocked and the id belongs to the write path
as well. The generalisation: a verdict's patience must not be restarted by SEM's own retries, and
"evidence" means a command that was SENT and refused, never an observation on a silent cycle.

**And forgiveness must cost what accusation costs.** The first cut of round 2 retired the episode on
any cycle that asserted nothing — which is exactly what an OSCILLATING switch looks like between
drops, and the #536 Eco-Smart/Autostart fault this surface exists for IS an oscillation (the box lets
the relay go, SEM re-asserts, it reads `on` for one cycle, it is off again). Measured against
`develop`: a switch stuck off but reading `on` one cycle in ten went from *reported* to **never
reported at all** — a fail-open strictly worse than the false alarm being cured — and a standing
notice churned raise/delete/raise once per blip. The same break came from SEM's own decision leaving
CHARGE for a cycle. So good time pays the fault down one second per second — a
leaky bucket, not a timestamp.

That correction needed a correction of its own, and it is the sharper lesson. Holding the FAULT on a
plain "since" timestamp while holding only the GOOD run on a window makes the verdict "300 s have
passed since the first bad cycle and no clean 300 s fitted inside" — which is not a statement about
the fault at all. One bad cycle per 299 s, a **3 % duty cycle**, reached the ERROR Repair at exactly
the speed of a permanently dead switch, and could never clear. A cloud charger whose entity goes
`unavailable` for one poll every few minutes is ordinary hardware (#893), so this was class 86
re-entered through the accumulation door: good time spent as evidence. Only BAD time may buy a
verdict, so the fault is an integral — filled while SEM is asserting and not getting it, drained
one-for-one while the surface is fine, raised at the hold, retired at empty. The level is CAPPED at
the hold, because guilt that is unbounded makes recovery unbounded: a day of a dead switch would
otherwise need a day of good operation to pay off and the notice would outlive the repair. A charger the owner has actually fixed clears in the time
its fault had earned, at most one hold; a Repair a previous
LIFETIME left behind is still retired at once by #485 H5's first-good-write clear, which is real
evidence and needs no hold. Two more asymmetries fell out of the same review: a fault that CHANGES
under a standing notice (an absent switch that comes back and then refuses to hold) re-files with the
truth instead of keeping the first diagnosis forever, and **observer mode files nothing at all** —
`send()` withheld every `turn_on`, so there is no refusal to report (class-86 residual (6), closed).
**Guard:** `tests/test_945_restart_enable_warmup.py` — the restart replayed through the real device
and the real adapter (30 s of blocked cycles raise nothing; the threshold raises once, and only
once), the vacuity twin (the command counter is untouched by a non-command, and #462's three rejected
writes still raise with no time passing at all), the recovery edge driven through the real
`observe()`, a pin that a switch recovering does NOT delete a Repair the write side raised, and the
sibling pin that a missing battery entity spends no strike. Round 2 adds the reporter's whole restart
through the real `reconcile_and_apply` — the entity absent, then appearing `off`, then recovering —
with the pin that makes it non-vacuous (the #536 budget really does run out here, and the cycles that
used to file the Repair really do send NOTHING), plus the STRUCTURAL guard the class asked for:
`ast_contracts.invented_evidence_call_sites` fails the build if any production call to
`_record_actuation_failure` passes an exception SEM constructed rather than one an enclosing
`except … as e` caught — positional OR keyword, with a rebound handler name, an `except*` group, and
a closure written inside a handler (where Python has already deleted the name) all decided correctly,
each self-tested against a probe. That contract alone was NOT enough, and the way it failed is the
lesson: the bug called the counter as `getattr(dev, "_record_actuation_failure", None)` and then
invoked the local, which is this codebase's dominant idiom for such hooks and which every
callee-NAME contract is blind to. So the load-bearing guard asks who may even MENTION the symbol —
`symbol_reference_files`, counting attribute accesses, defs and `getattr` string literals — and
requires every reference to live under `devices/`. Indirection cannot dodge that question. Re-injecting
the verbatim pre-fix body is caught; six further mutants (immediate retire, one sentence for both
faults, observer mode accusing hardware, never re-filing a changed fault, a third switch state read
as `off`, and a clock armed only by the report) each fail at least one pin.
**Sweep question:** for every counter that turns repeated observations into a user-visible verdict —
is each observation EVIDENCE (a command was SENT and refused) or SILENCE (nothing could be read, or
nothing was sent at all)? And is its patience measured in cycles or in seconds? A cycle-counted
threshold on a silent input is a promise about the coordinator's interval, not about the fault. Then
ask round 2's question: does SEM's own RETRY restart that patience — and if the verdict holds a
Repair, does the retry also retire it?
**Left for Guido:** (0) This surface shares ONE issue id with the write path (#462), which is why the
unblocked-cycle clear must not fire for a predecessor's Repair (class 84's usual answer): on a
KEBA/service/button charger there is no switch at all, so a first-of-lifetime clear there would
delete a genuine "every command rejected" notice on the evidence of an entity that does not exist.
The predecessor's copy is retired by #485 H5's first-good-write clear instead. Splitting the id would
let each condition own its own lifecycle — and is what a new translation key (item 1) would want
anyway. (1) The Repair TEXT is still the write path's, and round 2 makes this the
sharpest residual: past the hold BOTH enable faults are reported as "SEM's last 3+ current commands
to **{name}** were rejected" — the sentence alexmc1510 quoted back twice as evidence SEM was
confused, and one that is false for this surface by construction, since the cycles that file it send
nothing. Saying it properly needs a new `charger_enable_blocked` key with its own `fix_flow` in
`strings.json` + all 16 translations, and it wants item (0)'s id split first (a persistent Repair
already raised under the shared id has to be migrated). A product decision, not a sweep. (2) Past
the hold a missing start/stop entity now raises TWO ERROR Repairs for one fact — this one and #824's
`charger_control_entity_broken`, which watches the same `ev_start_stop_entity` on the same threshold.
Deduping them means deciding which surface owns an uncommandable control entity. (3) The hold starts
at the first blocked observation, so an integration that takes longer than five minutes to load (a
cloud charger re-authenticating) still cries wolf; anchoring it on `CoreState.running` would need the
`is_running`-is-true-from-`starting` trap of class 84 handled at every site. (4) The battery sweep
tests SILENCE by re-reading the entity on the cycle the third strike lands, not by asking what the
verdict actually saw: a register that contradicted three writes but happens to read `unavailable` on
that cycle is pushed into the 300 s hold while `last_unverified_seen` still carries the contradicting
number. A five-minute delay on a real #915 fault, never a false negative — the verdict would have to
carry its own "was this silence?" flag to be exact. ~~(5)~~ **CLOSED in round 2.** The hold used to
accumulate only across CONSECUTIVE reporting cycles, where the old cycle counter accumulated across
gaps, so an app-locked charger on a fluctuating-surplus day restarted its window on every
idle-and-not-drawing cycle and #548 could surface well after five minutes. The symmetric good-run
hold answers "what counts as the same episode": a gap shorter than the hold itself is not the end of
one. ~~(6)~~ **CLOSED in round 2.** In OBSERVER mode `send` withholds and returns False, so
`ensure_enabled` can never close the switch — an observer install whose switch read `off` walked the
re-assert budget and filed this ERROR Repair in ~70 s, claiming commands were rejected in the one
mode that promises to send nothing. The episode no longer even opens while `observer_mode` is set, so
leaving observer mode cannot file a verdict about cycles SEM sat out either. (7) New, from round 2's
own review: `_apply_actions` defaults `now` to `getattr(self, "_last_apply_at", 0.0)`, so a bare
reconciler instance would stamp the episode at `0.0` and the next real `time.monotonic()` files
instantly. Unreachable in production (`actuate.py` always passes `now`) and reached today only by
tests built on bare instances, but it is a zero-valued clock in a tree that measures wall time.
(8) Round 3's ERROR names the CURRENT entity only, because that is the one surface whose fallbacks
SEM can enumerate (`charger_service`, minus the entity-platform services that write THROUGH the
missing entity). A charger whose start/stop entity is the thing that vanished, with no stop service
either, is equally uncommandable and still gets only the generic WARNING — saying it properly means
enumerating every capability's fallbacks, which is #824's `_CONTROL_CAPABILITIES` table, one layer up
from a log line. (9) `_shed_device`'s `control_type == "current"` branch is the
fallback-with-nowhere-to-fall at WRITE time, and it is unreachable today: `_peak_managed_elsewhere`
excludes every `ev_charger` row from the load manager's shedding (#461-peak), so the branch that
would notice cannot run. Left as-is rather than given a log line no test could reach non-vacuously.
That unreachability is also the honest bound on #991's impact, worth stating plainly because the
issue text does not: NOTHING actuates off this row. Its `switch_entity` is read by the Load Priority
card and by #748's claimed-entity set — and the claimed set could not have mattered either, since
`LOAD_MANAGEMENT_DEVICE_PATTERNS` globs only `switch.*` and the entity dropped is a `number.*`. What
the bug cost was a WARNING that told its reader the opposite of the truth, on the one read most
likely to be wrong, plus a card row missing its entity. Worth fixing for exactly the reason #763 was:
the log is a diagnostic instrument, and a false reading in it costs days. (10) That round-3 ERROR
fires once, from inside the 120 s one-shot `async_call_later`, and nothing retracts it — an
integration that publishes at 121 s leaves a permanent ERROR with no recovery line. The CARD
self-corrects (#824 republishes `charger_<cid>_ev_current_control_entity_valid` every cycle and
clears its Repair), so only the log is stuck. Giving it a recovery line means giving the deferred
check a second life, which is a scheduler question, not a log question.

**Round 3 (#991, 2.1.0-beta.34) — the other consumer: the absence spent on CONFIGURATION.** Rounds 1
and 2 asked the question of evidence COUNTERS, whose cost is a false accusation. The same empty read
has a second buyer, and it is quieter. alexmc1510 again, same charger, `features/load_management.py`
`register_ev_charger`: `if current_control_entity and not self.hass.states.get(...)` → warn, then
`current_control_entity = None  # Fall back to service`. Registration runs *inside* SEM's setup,
where `states.get()` returns None for every entity whose own integration has not finished loading, so
the Victron EVCS's `number.*` current entity was "not found" for exactly as long as Victron took to
load — and the fallback it took had nowhere to fall (a `number`-driven brand has no charge service).
Entity ids are STRUCTURAL: `refresh_runtime_config` re-derives cached scalars, never ids, so the row
carried `switch_entity: None` for the whole session and only a reload put it back. No Repair, no
ERROR, one WARNING that told the reader the opposite of the truth. See residual (9) for what that
did and did not cost — the row drives no actuator, and overstating it would be its own defect.

The sharpest part is the sweep that was there and stopped one function short. Two checks ask this
charger "are your entities there?", and #763 had already moved the first — the
`_warn_missing_charger_entities` roll-up — 120 s past warm-up, after a registration-time read
declared onkelfu's healthy wallbox switch missing. The second ran a few lines later in the same setup
loop, still at setup, and was the only one that also DISCARDED something — so an instance-local fix
had left the class's worst site untouched because that site did not look like a Repair. **The
consumer, not the verdict, is what makes an absence expensive.** A verdict is loud and gets reported;
a discarded capability is silent and survives.

Closure for this half: an absence is not spent at SETUP at all. The question moves to where an answer
may be wrong for one cycle and right for the next — `CurrentControlDevice._set_current` re-reads
`current_entity_id` on every write and falls back to `charger_service` there, and #824's per-cycle
pre-flight owns the Repair once the absence outlives warm-up — so registration only notes it at
DEBUG. And a fallback that has nowhere to fall is an ERROR, said in the one place the absence is a
fact rather than an artefact: past warm-up, in #763's deferred check, which now takes the charger's
`charger_service` so it can tell "one of several handles is missing" from "there is no handle at
all". *Having* a service is not the same question as having a FALLBACK: an entity-platform service
(`number.set_value` and its `input_number` / `select` twins, #462 / #485 K1) writes THROUGH
`ev_current_control_entity or ev_charger_service_entity_id`, current entity first, so when the
current entity is what vanished it falls exactly where the entity did and must not buy silence.

**Guard:** `tests/test_991_warmup_absence_not_spent.py` — the reporter's boot driven through the real
`register_ev_charger` with the entity absent, read back through the card payload
`get_load_management_data`, the surface a user actually sees; the vacuity twin (the published entity
registers identically, so the pin cannot pass on a registration that never stores one); a positive
control on the log pin (a registration that dies inside its own `except` emits no warning either, and
would otherwise satisfy an absence-only assertion); and the config-shaped absence that IS an answer
(neither entity nor service still refuses). No pin claims an INDEPENDENT consumer, because there is
none — every reader of this row reads this row, which is residual (9)'s point.

The structural guard is `ast_contracts.absence_spent_as_config`: any condition asking whether a
`…states.get()` came back EMPTY, and any `= None` it reaches. Its first cut was the shape the bug
happened to wear — a top-level `Assign` to a `Name` in an `if` body — and that is the mistake round 2
already named once, when `invented_evidence_call_sites` turned out blind to `getattr`: a guard
written to the instance's spelling waves through the class's next one. So the question is asked of
every spelling a handle is actually written in — a local, an attribute, a DICT SLOT
(`row["switch_entity"] = None`, the natural form in a tree that keeps device rows in dicts, and so
the likeliest re-acquisition *in the very file this fixes*), a tuple unpack, an annotated assignment,
the conditional-expression form that carries its own test, `elif`, and any depth of `try` / `for` /
`with` / closure nesting inside the branch. Eight bug spellings are caught by probe, the verbatim
pre-fix body among them; a POSITIVE reading acted on is not caught (that is evidence) and neither is
a plain `dict.get`. The remaining limit is named and pinned rather than left to be discovered: test
and assignment must be syntactically connected, so the two-step dataflow form (`st = states.get(e)` …
`if st is None: e = None`) and a helper predicate (`if self._dead(e): e = None`) are invisible without
dataflow — which is why the behavioural pin exists.

**Sweep question, round 3:** for every `states.get()` absence, ask not only "is this evidence or
silence?" but **"what does this absence BUY, and for how long?"** A verdict is bought for a cycle; a
nulled entity id is bought until the next reload. Anything read at SETUP and kept is the expensive
kind, and setup is precisely when the read is least trustworthy.
Refs #945 #611 #824 #915 #462 #536 #548 #840 #627 #991 #763 #461 #485.

### 87. A register that lists only half the world, asked a yes/no question — GUARDED
**Symptom:** a reporter is still getting the same false Repair three betas after it was "fixed"
twice. bekovan (#912, 2.1.0-beta.17, 2026-09-12) kept the frozen-sensor Repair for
`sensor.inverted_power_plugin_solar` after the sibling rule (beta.7) AND the derived-source rule
(beta.9) — both of which were the right rules, and neither of which could ever run for their entity.
**Root shape:** the code asks *the entity registry* which integration owns an entity. The entity
registry is a register of entities that have a `unique_id`; an entity declared in
`configuration.yaml` without one is not in it at all. So the lookup returns `None` — and `None` is
read as an ANSWER ("no platform → not a helper → a polled sensor whose entry has gone quiet") rather
than as *this register cannot see this entity*. Every later rule then reasons from a verdict the
register never gave. Home Assistant does keep the fact, for every entity an entity platform adds,
registered or not: `homeassistant.helpers.entity.entity_sources()` →
`{"domain": "template", "config_entry": ...}`.
**Where it lives:** any registry lookup whose `None` branch decides something ABOUT the entity
instead of declining to derive from it. **Swept here**, all in `coordinator/sensor_reader.py`:
`_source_is_alive` (the platform question) and `_integration_is_reporting` (the config-entry
question) now share one `_entity_owner` (registry first, source map second); the entry's MEMBERSHIP
too (an integration's entities without a `unique_id` were invisible as vouching siblings —
`_unregistered_entry_entity_ids`, walked only when no registered sibling already answered); the two
brand sign SEEDS (`_seed_grid_sign_from_platform` / `_seed_battery_sign_from_platform`, where a
YAML-declared brand sensor got no deterministic seed at all for no better reason than a missing
`unique_id`); and the two sign DIAGNOSTICS payloads, which reported `"grid_platform": null` for
exactly the reporter's entity — the triage surface that could have named "template" in round 1.
*Assessed and correct as-is:* `ha_energy_reader`'s device-sibling derivations and `__init__`'s
offline-twin heal ask for a `device_id`, which an unregistered entity genuinely does not have — "no
derivation" is the true answer there, not a verdict. *Named, not swept:* `hardware_detection` both
looks a seed up (`no_registry_entry` for a YAML-declared seed) and ENUMERATES `reg.entities.values()`
in a dozen places, so an unregistered fleet is invisible to discovery — a detection gap (no false
claim), and its own round. `coordinator/dual_phase_guard.py` is the same FAMILY from the other side
(class 63): it fails a safety gate closed on a flat `last_reported`, which an integration that skips
identical writes (#912's foxess) produces on a genuinely quiet phase — a safety path, so a liveness
fallback there is a decision, not a sweep. Class 63's liveness UNIT (one config entry = one
connection) is false for a shared broker: an MQTT hallway light vouches for a dead P1 meter on the
same entry. True before this round for registered entities and now for YAML ones too; narrowing it
means picking a different unit (the device), which the FoxESS case constrains.
**Closure:** ownership is resolved in ONE place that knows both registers, and only an entity no
entity platform owns at all (a raw `states.set`) returns "unknown" — which stays fail-closed,
because that is the one case where the information really is missing. The derived fail-open is
bounded wherever the helper publishes a source: a helper with no config entry is followed through
the source attribute it declares, read BY KEY (`filter`/`group` → `entity_id`,
`derivative`/`integration`/`compensation` → `source`, `min_max` min/max/last → the winning entity),
so a legacy YAML `filter` over a dead meter still warns. Never by scanning all attribute VALUES, and
never for a Template: its attributes are user prose, and one that merely names another entity
("mirrors sensor.nordpool_…") would be adopted as its source and the sensor declared frozen when
that entity goes quiet — this issue's own false positive, one layer down. The residual is therefore
every helper that publishes no source — a Template, a `statistics` or `min_max` mean, a
`utility_meter` (which publishes `status`/`last_period`, not its source) — and it is deliberate:
a flat derived value is a change signal, so nothing can be proved about it, and accusing it is the
bug this class is about.
**Guard:** `tests/test_912_frozen_unregistered_owner.py` — the reported YAML template goes quiet, an
unregistered sibling can vouch, an unregistered polled sensor in a dead entry still warns, an
unowned entity still warns, a YAML `filter` over a DEAD meter still warns (the fail-open is bounded
where a source is published) while the same wrapper over a live one is honest, a Template attribute
that merely names another entity is not read as a source and a decorative attribute cannot overrule
a published one, and a source-inspection test pins
that the two liveness rules ask `_entity_owner` — no `platform`, no `config_entry_id`, and no
registry call that looks up anything but the handle.
**Sweep question:** for every index this code treats as authoritative — the entity registry, the
device registry, the Energy Dashboard, the roster (#915) — which entities is it *structurally
incapable* of listing, and does absence from it read as "no" or as "I don't know"? Refs #912 #851
#611 #86.

### 88. One control, two backend axes — the qualifier in its label binds only one of them — GUARDED
**Symptom:** a load configured to run on surplus runs from the meter in broad morning daylight,
at a timestamp that is nobody's round number: **07:52:39**, sunrise to the second. The card still
reads "Solar only", the progress bar still says "0.5/4 h on solar today", and the setting the user
actually turned on says **overnight** on its face. **Root shape:** one user-facing control fans out
to TWO independent backend flags, and the qualifying word in the control's own label ("overnight",
"solar", "at night") is enforced in one implementation and forgotten in the other. Each half is
written and tested on its own terms, so neither looks wrong; the contradiction only exists at the
control, which nothing tests. The display twin of this is class 75 (one knob, two features, and
the knob SHOWS only one of them); this is the behaviour twin — the knob COMMANDS only one of them.
**Live catch (#953, alexmc1510, 13.09.2026):** the "Finish overnight from" picker writes
`battery_eligible_overnight` (Tier-2) and `top_up_policy=cheap_hours` (grid). The battery half has
been gated to the night window since #633 — *"'Finish overnight from: Battery' must not fire in
daytime (caught live at 09:10 in full sun)"* — and the grid half had no window at all, only the
tariff level. So the cycle the sunrise-held meter day rolls (#703/#704) and yesterday's met target
becomes a fresh 4 h deficit, the first cheap slot of the morning bought the whole day's target from
the meter, with 12.6 h of sun and a 37 kWh forecast still ahead; the pump was still running at
08:24 on 78 W of sun with the pack discharging 857 W. **Closure:** the qualifier becomes ONE
predicate both axes read. `sun_can_still_finish(deficit, daylight_remaining_s, is_night)` — while
today's remaining daylight is at least as long as what is still owed, the sun can deliver it and
the meter waits; at night it is trivially open, and that arm reads `is_night` alone, so the
promised overnight behaviour never depends on a sunset reading. Deliberately about the free
window's LENGTH, not about cloud: a dark day is what the top-up exists for, and #559's contract is
that free comes first. It cannot flap — running, the deficit and the daylight shrink at the same
one second per second, so their difference is constant; idle, only the daylight shrinks — so it
opens once a day and stays open. Three things the first cut got wrong and review caught, each a
class of its own: the daylight is measured from `max(now, sunrise)`, because the night window ends
at `min(sunrise, 07:00)` and a winter 07:00→08:03 gap would otherwise be booked as sun;
`_daylight_remaining_s_now` returns **None** unless `TimeManager._last_sunset_source` says the sun
integration answered, because `get_sunset_plus_10_time()` fabricates 20:30 on any failure and
hands it back like a reading (class 40) — which also makes a one-cycle `sun.sun` blink harmless
instead of a four-hour jump in believed daylight that would stop a running top-up; and the single
entry point `grid_top_up_defers_to_sun(device, …)` exempts a device whose COMFORT band is speaking
(`forced` = a cold room now, `willing` = a block the #638 joint plan placed), neither of which is
the daily runtime floor this window is about — the same reason `ComfortBandMixin.daily_targets_met`
already refuses to stand the paid sources down on a forced band. **Where it lives:** every control that fans out to more than one
backend flag. `_setOvernightSource` (battery / grid — this instance); `_applyMergedMode`
(`control_mode` + `battery_assist_enabled`, whose "Solar only" hint promises "never imports from
grid"); the EV charge-mode select, where `consts/ev_charge_modes.py` already does this RIGHT and is
the precedent — *"(#885) solar_plus_battery inherits solar_only's night contract wholesale"* — and
`mode_allows_night_charging` exists precisely because two hand-copied twins were drifting.
`may_assist_ev` (#1066): the charger side asks it before any window or boost; the battery-side clamp,
which is what keeps the inverter from covering the car on the meter, never did — **swept**, it now holds
the clamp in every arm (surplus, spend consent, window, boost, protection switch off).
**Guard:** `tests/test_953_cheap_hours_finish_window.py` — the reporter's morning through a real
`SurplusController.update()` walk (the ungated pass is shown to START the pump first, so the pass
is not vacuous), the overnight promise and the short-winter-day tail both still topping up, the
class-17 stop twin ending a night run at dawn, a monotonicity sweep pinning that the gate cannot
flap, desired-state parity on `compute_load_intent`, and AST guards that BOTH halves of the
imperative pass and the intent path call `sun_can_still_finish` and that the coordinator feeds it
from the same sun authority `is_night_mode` uses. **Open residual (for Guido — a product call, not a sweep):** the window is
about TIME, never about energy. A user whose only cheap window is midday (a Tibber/Amber negative
midday block) on an overcast day is now deferred through that window — the daylight is long enough
on the clock, the sun never delivers, and the target is missed until the night window, which may
not be cheap. Pre-#953 that user was served, by the ungated pass or by the virtual pool. The
energy-aware form of the same gate is `forecast_remaining_today_kwh` vs `deficit × rated_power`,
which needs a decision about how much a forecast is trusted to keep the meter out (a wrong
forecast the other way buys grid in full sun). Deliberately not guessed at here. **Sweep
question:** for every control a user can
see — list the backend flags it writes, then read its LABEL as a specification and ask of each flag
*"does this one honour every word of it?"* Refs #953 #633 #938 #620 #559 #885.

### 89. A read role bound among measurand siblings — the capability outranks the measurement — GUARDED
**Symptom:** SEM reports an EV charger drawing its full nameplate power, continuously, with no car
plugged in — and then infers a connected, charging vehicle from that power (`sensor_reader`:
current cannot flow without a plug), so the EV budget, the charging determination and the house
balance residual are all wrong while the charger sits idle. Nothing errors: the sensor is real,
correctly united, plausible and monotonic-free. It is simply about a different thing.
**Root shape:** an integration that names its entities after PROTOCOL MEASURANDS publishes a whole
family under one `device_class`, and SEM's brand matchers bind the read roles
(`ev_charging_power_sensor`, `ev_total_energy_sensor`, `ev_session_energy_sensor`) on that device
class ALONE, keeping the first or the last entity the loop happened to see. The only thing that
separates a measurement from a capability the box ADVERTISES, or from the opposite direction, or
from a window delta, is a segment of the entity id that nothing reads — so registry ORDER decides.
The read twin of class 56 (a mode-qualified fallback register bound as the live control surface):
there a mis-bind actuates, here it poisons every decision downstream of the read, and unlike a
mis-bound control it never announces itself by failing to write. Cousin of class 28 — a sensor
trusted for the slot it sits in rather than for what it measures — except that here SEM chose the
slot itself, so there is no user to have known better.
**Live catch (#962, @bgthb, 2.0.0, Huawei SCharger 22-KT over lbbrhzn/ocpp):** one charge point
publishes `Power.Active.Import`, `Power.Offered` and `Power.Active.Export` all as
`device_class: power`, and four `Energy.Active.{Import,Export}.{Register,Interval}` counters as
`device_class: energy`. `_discover_ocpp`'s last-wins bound `sensor.wallbox_power_offered` — the
22 kW the box advertises it *could* give, reported whether or not a car is there — and its
first-wins bound `sensor.wallbox_energy_active_export_interval`, wrong in both direction (V2G) and
window (a delta, not a register).
**Where it lives:** every read-role matcher in `hardware_detection.py` — the hand-written brand
functions (KEBA, Easee, go-e, Wallbox, Zaptec, OCPP, Ohme, Peblar, V2C, Alfen, OpenEVSE, Blue
Current, OpenWB), the `_BRAND_HINTS` rows (ChargePoint, GARO, JuiceBox, Wattpilot, Heidelberg),
`probe_charger_candidates`, `charger_from_near_miss`, and the glob matrix's
`get_best_match` — all of which take `device_class == "power"` / `"energy"` as the whole question.
**Closure:** one brand-agnostic guard, `_reject_capability_sensor`, inside the single
`apply_charger_discovery_guards` choke point all four REGISTRY discovery paths now funnel through
(the same shape #886 used for the control half): when a bound read role names a capability
(`offered`, `limit`, `max`, `rated`, `nominal`, `capacity`, `available`, `setpoint`, `target`,
`allowed`) or the wrong quantity (`export`, `reactive`), swap it for the sibling that measures —
chosen by a stable rank over the entity id, never by registry order. Every rule reads id SEGMENTS,
not substrings (class 67: `rated` lives inside `solar_generated_power`). The replacement must be
COMMENSURABLE — same device class *and* same unit family — because a brand that omits
`device_class` (Zaptec's custom builds) otherwise makes the family "every sensor without one", and
the search hands back a status string; polyphase legs are excluded outright (a third of the truth
is not a fallback for the truth) and so is an entity already holding another role (#698: the total
and session counters must not collapse onto one). **SWAP ONLY, never drop** — and that is the
non-obvious half. Removing the role *looks* like the fail-closed move and is not one in this tree:
the charger is still registered (`_retry_ev_device_setup` gates on the service, not the sensor),
KEBA's adapter decides `actual_charging` from power alone so it reads "never charging", the
18-cycle `ev_power < 50` rule anchors its SoC at 100 %, and in a multi-charger install the missing
per-charger key falls back to the FLEET sum (class 3) — while the only notice is a DEBUG line and a
Repair that `unmanaged_charger_repair` suppresses. So a name SEM merely finds suspicious can never
cost a user their charger; a capability-only family keeps the pre-#962 binding. The segment
vocabulary being English-only is a coverage gap of the same fail-open kind (a German
`nennleistung` is one word), not a claim. `_discover_ocpp` additionally asks for its measurands by
name, because the OCPP vocabulary is fixed by the protocol and SEM can be exact. The glob matrix
(`get_best_match`) is a FIFTH path and deliberately does not funnel through the choke point: it
produces a config-flow prefill the user confirms, so it applies the same predicate as a demotion.
**Guard:** `tests/test_962_measurand_family.py` — the reporter's own family in his own order (with
the pre-fix rule spelled out, so the pins cannot pass vacuously); an order-independence oracle over
EVERY platform in `_EV_CHARGER_PLATFORMS`, forward and reversed; an invariant that no brand, hinted
or hand-written, binds a capability-named entity to a read role, mirrored on the prober and the
diagnostics report; the swap-only rule through a KEBA on a device its owner named **Max**; the
commensurability, phase-leg, collapse and window pins; and a LITERAL list of capability names, so
shrinking the segment set fails the test rather than shrinking it too. Ten mutants — including
dropping the entity-id tie-break, flattening the window weights and reverting each of the five call
sites — are killed by these pins.
**Sweep question:** for every entity a detector binds to a READ role, can the integration publish a
second entity of the same domain and device_class that measures something adjacent — a capability,
the other direction, another window, one phase — and does the matcher separate them, or pick by
ordering? And before making a guard fail-closed: *trace what the missing value actually does
downstream*, because "drop it" is only safe where absence is handled.
**Second instance — #1035, one phase:** Peblar's brand rule kept the LAST power sensor, and the
three per-phase sensors come after the total, so SEM read `…_power_phase_3` — a third of a
three-phase charge. The guard swapped a capability but let a phase leg stand. `_reject_capability_sensor`
now swaps a bound phase leg too, swap only and ONLY for the sum of the legs — the sibling named like
it without the phase (`_without_phase`), so a device's grid, solar or battery power is never taken
for it. `_is_phase_leg` reads the entity's own name (class 115) and wants the number AFTER the word:
`phase_3` is a leg, `3_phase_power` is the sum.
Guard: `tests/test_1035_own_name.py::TestOnePhaseIsSwappedForTheTotal`.
**Third instance — #1034, another circuit:** a box with its own clamps meters more than the car.
HA's V2C publishes `charge_power`, `house_power`, `photovoltaic_power` (key `fv_power`) and
`battery_power`, all `device_class: power`; its rule kept the last, the solar output. The guard now
also swaps a read role whose own name or translation key names another circuit
(`_OTHER_CIRCUIT_SEGMENTS`: photovoltaic, pv, fv, solar, house, home, household, grid, battery,
inverter, mains, utility, evu, akku, ess, shaper), and `_measured_twin` never offers one; among
equal ranks a candidate naming the car (`charge`, `ev`, `car`, `vehicle`) beats the alphabet. Swap
only, like the rest of this class. `_what_it_is` keeps a device called "Solar Carport" or an mqtt
"Home JuiceBox" from flagging its own charge (the review found the latter undid #1035's phase
swap); the key keeps a German `…_photovoltaik_leistung`
visible. The word list is English plus the keys: an unlisted word (`consumption`) is not seen —
fail-open, like the capability list. The glob prefill is unchanged: it reads whole ids, so a device
name would demote a real reading. Guard: `tests/test_1034_range_and_circuit.py`; on the 16 rig
captures of `feature/hardware-wave` only V2C's answer changes. **Left for Guido:** Blue Current's
`ev_current_sensor` is `setdefault` on `avg_current`, which `grid_avg_current` also holds; that role
is outside this guard.
**Residual, CLOSED in #964 (class 90):** the sibling search this class installs is only as
honest as the bucket it searches — and two of the three discovery sites grouped device-less
entities into ONE bucket per platform, so the best-ranked sibling could belong to the other
charger.
Refs #962 #886 #947 #814 #816 #964.

### 90. An optional identity used as a grouping key — "no id" becomes one unit — GUARDED
**Symptom:** a user with two chargers of one brand is offered ONE charger whose entities come from
both boxes — the power sensor of the garage box, the plug of the carport box. Nothing errors: each
entity is real, correctly classed and on the right platform; SEM simply believes there is one box.
Downstream, every per-charger decision (budget, connected, charging, the SoC anchor) is made about
a machine that does not exist, and the second charger is never offered at all.
**Root shape:** the registry's `device_id` is the answer to "which box is this" — and it is
OPTIONAL. An integration may register no device at all (KEBA's UDP integration, manually configured
MQTT entities, YAML platforms). Code that groups with `devices.setdefault(e.device_id, [])` turns
the ABSENCE of an identity into an identity: every device-less entity of a platform hashes to the
same `None` key and lands in one bucket. The collapse is invisible because a bucket of two boxes
looks exactly like a bucket of one — and the role pick that reads it cannot tell, whether it takes
the first match, the last, or (since #962) the best-ranked sibling in the whole list. The
per-charger twin of class 3 one layer earlier: class 3 reads the fleet where it wanted one charger;
here the fleet IS one charger, by construction, before anything is read.
**Live catch (#964, found by the adversarial review of #962):** `discover_all_ev_chargers_from_registry`
(config) and `build_detection_report` (diagnostics) both keyed on `device_id` with no fallback,
while `probe_charger_candidates` — the third site — already knew better and sub-grouped device-less
entities by entity-id prefix. Two of three paths, one mechanism.
**Where it lives:** every walk that turns registry entries into "devices" — the three EV discovery
sites in `hardware_detection.py`, and the same question for any future per-unit walk (PV strings and
battery siblings already group on `config_entry_id`, which is why they never had it).
**Closure:** one shared `group_entities_by_unit`, three callers. `device_id` wins wherever it
exists. For the device-less remainder there is no identity left, only NAMES — the entity-id prefix
at three widths, the name up to and including its first numeric TOKEN (HA disambiguates a second box
either by suffixing every entity — `..._2` — or by its device name, which puts the digit in the
middle where no fixed-width prefix can see it), and that trailing `_<n>` itself — the two numeric
axes adopting only on HA's OWN numbering shape, every numbered name being an unnumbered name of the
same set plus its number, starting at 2, because a platform that numbers its own sub-structure
(`wb_garage_phase_1`…`_3`) is not two boxes and on a plugless platform the plug rule cannot say so; each tried against
`config_entry_id` first and then without it (one box can span several entries: a rig's template
helpers are one entry per entity). Finest first. **A name axis becomes a boundary only on evidence:
at least TWO of its groups must show the charger shape on their own** — a power reading plus a plug
binary, or, only on a platform that publishes no plug at all (a JuiceBox over plain MQTT), plus a
current control. Insisting on the PLUG wherever one exists is the second thing the review of this
fix had to teach it: a current control is not unique to a box *within* one box, so three per-phase
`number.*_current` legs beside three per-phase power sensors each passed the loose rule and split
one wallbox into three chargers, shedding the single `binary_sensor.wb_plug` they share. A phase
leg, a site total and a sub-meter never carry a plug. That threshold is the whole safety argument, and the first draft of this fix got
it wrong: adopting a split that finds ONE box separates nothing, it only sheds the entities it left
behind — a KEBA called "Keba" whose `sensor.keba_charging_power` and `number.keba_charging_current`
share the prefix `keba_charging` would have been "split" from its own `binary_sensor.keba_plug`,
handing its owner a charger with no plug and a `keba.set_current` with no target; a YAML-MQTT
JuiceBox beside a YAML-MQTT heat pump would have been deleted in favour of the heat pump. With the
two-box threshold, an install with one box is grouped byte-identically to pre-#964, so the charger
COUNT cannot move — which is why this could ride a release with no live device-less box to prove it
on. When two boxes ARE found, a group showing no shape is first offered BACK to the
box it belongs to, by longest shared leading name tokens and only where exactly one box is closest
— because two boxes can shatter the SAME way at the axis that separated them (`<box>_charging_power`
with `<box>_charging_current` under one name, `<box>_plug_connected` under another), and shedding
that costs BOTH owners the plug binary and the `keba.set_current` target it is. What stays equally
close to every box is what "belongs to neither" actually looks like — openWB's `openwb_global_*`
site totals sit one token from each loadpoint — and only that is dropped, because a brand function
fed one box's leftovers invents a second, partial charger. `build_detection_report` lists the drops
under `unattributed`, which the diagnostics download carries, so the drop is visible, never silent.
And a leftover that carries a MARK — a plug or a current control — refuses the axis outright rather
than being dropped: a mark left over is one box's own steering, so the axis cut through a box. A
leftover that shows the charger shape ON ITS OWN is never attached at all: it is a box this axis
could not place (a third, plugless wallbox beside two plug-bearing ones), and name distance would
have folded it into whichever neighbour it happened to share a token with.
The unproven case splits per CALLER, because the two directions cost different things: the paths
that BIND merge (a split nobody proved must never shed a box's entities), while the prober keeps its
name split (it binds nothing, and merging a rig's template platform into "one device" is what handed
a mock charger an SG-Ready switch for start/stop, #814) — with a FLOOR, since an adopted axis can be
wider than the two-token prefix the prober has split on since #814, and a one-token axis offered a
garage door as a charger's start/stop. The report's prober-vs-brand comparison pairs the two
findings by the ENTITIES each claims, the way `config_flow._charger_already_installed` fingerprints
a charger: the device id cannot do it (two device-less boxes both report `None`) and neither can the
grouping key, since the two sides group an unproven split differently ON PURPOSE — keying on it
reported a disagreement on every device-less install SEM has, which is the exact population #814's
comparison window is watching.
**Known limits, all fail-closed to the pre-#964 behaviour:** two device-less boxes of a brand that
shows neither a plug binary nor a current `number` (Easee's status is a plain `sensor`, its control
a service) still collapse; so do two boxes one of whose plugs the user has disabled — a disabled
entity is filtered before grouping, so the evidence is judged on what is live — and so do two boxes
whose names no axis separates (`box` beside `box_garage`, with no digit anywhere), and two boxes
sharing their first token where a finer axis was refused — the ladder then falls to the coarser one,
which is still no worse than the single bucket #964 found. A site-level current `number` on a
plugless multi-box platform (openWB's `openwb_global_max_current`) strands a mark and so keeps its
loadpoints collapsed: the same stranded-mark rule that stops a JuiceBox's `limit_current` from
splitting ONE box into two, and the fail-closed direction is the one we keep. The one shape
that could still split a single box is a PLUGLESS platform publishing a separate current `number`
per phase; no brand SEM knows does that, and the stranded-mark rule catches it wherever the phases
leave anything behind.
**Guard:** `tests/test_964_charger_unit_grouping.py` — an AST lint over the package that flags any
`setdefault(…)`/`[…].append()` keyed on a registry entry's `device_id`, attribute, `getattr` or
one-line temp alike (the class recurs by someone writing that line in the next discovery path), with
a self-check on the shapes it must catch and must not; a reflection pin that all three sites funnel
through the grouping; two-box separation and one-box no-shatter in BOTH directions with the pre-fix
rule spelled out so they cannot pass vacuously; the unproven-split cases the review of this fix
found (the KEBA with a current number, the JuiceBox beside a heat pump, a disabled mark, the rig's
template platform); the config-entry, numeric-suffix, mid-name-number and three-token axes each
pinned by a case only that axis can separate; two boxes that shatter the same way, each keeping its
own plug and service target, and a leftover meter that finds its own box; one box's three phase legs
and its total, each pinned as ONE charger with the loose shape spelled out so the pin cannot pass
vacuously; the leftover drop pinned exactly at the tie (a mutant that reports every entity as
unattributed fails, and so does one that hands the site total to a loadpoint); a quiet
prober-vs-brand comparison on the device-less install, beside a prober-only finding that must still
be reported; and role-binding order-independence over permutations, a registry-place pin on the
re-attached leftovers and a pin on WHICH box is primary. Fourteen mutants — reverting to
`device_id`-only, lowering the threshold to one shaped group, removing each of the four name axes or
the config entry, dropping the plug requirement, dropping the stranded-mark refusal, dropping the
leftovers instead of re-attaching them, attaching them on a tie, appending them out of registry
order, trying the axes coarsest-first, merging in the prober or flooring an axis already finer than
its prefix, adopting a numeric axis on numbered sub-structure, attaching a leftover that is a box of
its own, and pairing the report's two findings many-to-many or on the grouping key — are each
killed.
**Sweep question:** for every key this codebase groups by, is it OPTIONAL in its source of truth —
and if it is absent, does the code get one bucket per missing value, or one bucket for *all* of
them? A key that can be `None` is not an identity until the `None` case has its own answer. And when
the fallback is a heuristic: what does adopting it COST when it is wrong, and is that cost paid by
the user who has one of the thing, or only by the user who has two?
Refs #964 #962 #886 #814 #3.

### 92. A new control decides in the orchestrator instead of the decide layer — two producers of one decision — GUARDED
**Symptom:** on the rig, a feature whose whole promise is *"I am holding the meter shut"* is
invisible. The observer surface shows the battery's own verdict where the export cut should be, or
shows the cut for exactly one cycle and then nothing. Nothing errors, the cut is genuinely applied,
and every unit test passes — the two decisions simply overwrite each other under one key, so the
one surface a person judges the feature by (#855: a case is judged on what would hit the wire)
cannot show both.
**Root shape:** a new control axis is built where it is easiest to reach the inputs — inside the
coordinator's cycle — rather than in the layer that already decides. The tracker ticks, decides and
writes in one method, so the codebase gains a SECOND producer of a decision type and a second call
site for a seam built to be the only one. The collision on the observer key is the visible tip; the
cause is that the axis never entered the decide layer. Everything downstream inherits it: the cut
loops every adapter because no decider chose one (a house-level quantity riding a per-device path,
so a two-battery single-inverter install issues the same service call twice — de-duplication at the
brand hides it, cf. class 38); the hand-back asks the adapter *"could you undo a cut"* instead of
*"are you holding one"*, which on a mixed fleet (#531) resets a limit the OWNER set; and the
decision cannot be unit-tested without building a whole coordinator, which is how the same arc
shipped a guard that released a cut it never made.
**Why it survives review:** the layering is obeyed *downward* — there IS an adapter per brand and
there IS a seam — so the diff looks like the neighbouring feature it claims to mirror. Only the
question "where is the decision made?" separates them, and that question is invisible in a diff
that adds files rather than changing them. The tell in SEM's own history: `#864`'s peak guard puts
its tracker's value on the fleet state and clamps in `decide.py`; the export guard put nothing on
the fleet state at all.
**Cure:** the tracker leaves a VALUE on the cycle state; a pure function turns it into an intent;
one seam writes it; one adapter is chosen by capability, not by insertion order. Three named
methods instead of one long one, each exercisable alone.
**Guard:** `tests/test_921_one_track.py` — one producing file per decision type, exactly one
production call site per seam, the seam's observer key named nowhere else (counting IMPORTS: the
first version of that pin missed `from .actuate_export import OBSERVER_KEY` and was vacuous), every
decider free of hass/adapter/await/service-call, and the tick proven to run after the verdicts it
reads. Every pin was mutated to confirm it fails.
**A second reading, from the same arc (16.09):** the observer surface
`observer_decisions` is a ROSTER, swept every cycle by
`retire_unpublished_observer_decisions` — *whoever published this cycle stays;
everyone else is dropped.* Its docstring's promise that the map "always carries
the CURRENT would-state" is true BECAUSE every decider re-publishes, not because
entries persist. Reading that as persistence and removing the per-cycle publish
made a HELD export cut disappear from the surface while it was still being held —
the state was right everywhere except the one place a person looks. Cousin of
#744 from the other side: there an append-only map described history where the
present tense was needed; here a present-tense roster was mistaken for a ledger.
Before deleting a "redundant" re-publish, ask what SWEEPS the surface.

**Sweep question:** for any control that writes to hardware — *which file constructs its decision,
and is anything else allowed to?* Then: does its tracker put a value on the cycle state, or keep it
in a method? A control whose decision type is built in exactly one place cannot grow a second track.
**Scope note:** SEM does NOT have a universal "every write goes through a decide layer" rule —
`charge_pacing` and `load_management` call services directly, and a review refuted that broader
framing. The class is about a control gaining a second producer of a decision that already has one.
Refs #955 #921 #864 #855 #908 #936 #531 #538.

### 93. Two producers of one context — a field threaded through one and pinned there — GUARDED
**Symptom:** the arc's new axis is wired, tested and pinned; the tracker engages, the surface says
"engaged", and the hardware never changes. No error, no refusal, no log line, no store row.
Found live on .175 with observer OFF (17.09): the guard had never written, on any rig, since its
first proof two days earlier.
**Root shape:** a context object is constructed in more than one place (`FleetContext` in
`build_view.build_charger_view` for the chargers and again inside `_run_battery_pipeline` for the
batteries). The new fields are threaded through the producer the author was looking at and an AST
pin is written against THAT call site — while the consumer (`_apply_export_decision`) is handed the
other one, which still carries the dataclass defaults (`None`, `False`). Every unit test passes
because each layer is tested with a context it builds itself. Sibling of 92 (two producers of a
decision) and of the #358 "plumbing asymmetry" the fleet state was invented to end — the state
ended it for the chargers and the batteries kept their own copy.
**Cure:** one source — both producers read the cycle's `FleetCycleState`; the battery pipeline's
context no longer re-derives anything the state already holds.
**Guard:** `tests/test_955_dispatch_reads_the_fleet.py` — `call_sites("FleetContext")` must show
EVERY production producer passing `export_command`, `export_guard_enabled`, `sink_verdicts` (the
#924 sibling question, asked over the whole package), plus a cycle-level test that runs the real
pipeline with the guard's command on the fleet state and asserts the adapter was awaited — RED on
the pre-fix coordinator (5 of 8).
**Sweep question:** for any field added to a context dataclass — *how many call sites construct
that class, and did the field reach all of them?* `call_sites(ClassName)` answers it in one line.
**Second instance (#1003, 22.09.2026):** the peak axis — `peak_slot_allowed_w`, and the #818
`inputs_degraded` / `dark_inputs` pair beside it — reached `build_view`'s charger context from #864
on and never `_run_battery_pipeline`'s. The battery decider read the dataclass defaults, so the
#879 house hold could not have seen a limit if it had asked. Same class, same two producers, a
different axis: the #955 guard pinned the export fields BY NAME, and naming the fields is what let
the next axis through. `tests/test_1003_the_hold_yields_to_the_peak.py` pins the peak three the
same way, and the same way is still name-level — a producer passing `peak_slot_allowed_w=None`
satisfies it. **Open for Guido:** the guard that would end this class is a coverage rule, not a
field list — every field of `FleetContext` that any decider READS must be passed by every producer,
derived from the dataclass rather than enumerated. Refs #955 #921 #358 #924 #1003.

### 94. An observer surface that cannot tell "decided to write" from "still holding" — GUARDED
**Symptom:** the rig shows a perfect `limit_export` row with the right service and the right device
every cycle, and the code path that would have produced it as a COMMAND has never run. The
standing re-publish (#764, the roster) names the same key, the same action and — once the dry-run
surface existed — the same service. Two rigs, two days, one live proof written up from that row.
**Root shape:** a surface designed to answer "what would hit the wire" is fed by two branches —
the command on the cycle it fires, and the roster's re-publish on every quiet cycle — and the two
emit indistinguishable rows. The re-publish is CORRECT (it exists so a held cut stays visible) and
it masks the absence of the command completely. Nothing on the surface is false; the missing
event is simply not representable.
**Cure:** the row says which branch made it (`standing: true|false`), the roster reason is the
standing text and the command row carries the decision's own reason, and the LOG is the witness:
the seam's `OBSERVER · WOULD …` / `export limit_export …` lines exist only on the command branch.
**Guard:** `tests/test_955_dispatch_reads_the_fleet.py::TestObserverTellsACommandFromTheStandingRow`
— the command cycle yields `standing: false` with the decision's reason; a quiet engaged cycle
yields `standing: true` with the holding text.
**Sweep question:** for any "would" surface — *if the real command never fired, would this surface
look any different?* If not, the surface proves holding, not acting; go find the log line.
Refs #955 #764 #855.

### 95. A lagging readback trusted as the baseline — the echo latch — GUARDED
**Symptom:** the second cut of the day restores the meter SHUT. SEM believes it has let go; the
house never exports again until someone resets the inverter by hand.
**Root shape:** the adapter captures "the mode I found" by reading a sensor whose integration polls
the register on its own slow schedule (Huawei's configuration coordinator: 8–15 minutes behind a
write, measured 17.09). The capture is cleared on release, so the next cut re-reads — and inside
the poll window the sensor still echoes SEM's OWN `Zero Power`. The echo is recorded as the
baseline and faithfully restored. Cousin of #538 (a register read seconds after a write is not the
register) and of the restart case the arc already handled with `_adopted_recipe`.
**Cure:** the prior is captured once and KEPT across a release — an operator's mode is a standing
configuration, not a per-cycle value — so a lagging read is never consulted as ground truth again
within a lifetime; the restart half of the same rule adopts the persisted recipe.
**Guard:** `tests/test_955_huawei_export_device.py::TestASecondCutDoesNotAdoptTheFirstOne` — cut,
release, readback now echoing `Zero Power`, cut, release → the restore is still the first prior;
the pin was reverted against the old line and failed.
**Sweep question:** for any "capture before write, restore after" pair — *how stale can the
capture's source be, and is the write's own echo excluded from it?*
Refs #955 #908 #538.

### 96. A hand-back that asks the hardware for a mode it will not take — GUARDED
**Symptom:** the release "succeeds" (HTTP 200, no exception) and the register lands somewhere the
call never wrote. Three attempts from two starting modes; the inverter chose `DI Active Scheduling`
every time. The integration's own service — `reset_maximum_feed_grid_power`, documented as *"Set
Active Power Control to Unlimited"* — was the adapter's last resort.
**Root shape:** a default chosen for its name ("the integration's own reset — it can only ever
ALLOW more export") rather than measured. Mode 0 is refused by the reference SUN2000 while modes
1, 5 and 7 are accepted; 100 % of nominal is the same intent in a dialect that lands. The same
family as the readback that read `unavailable` as "free": a verb's contract was inferred from its
label instead of from the hardware's answer, and nothing in SEM reads the hardware's answer back.
**Cure:** the last-resort hand-back is `set_maximum_feed_grid_power_percent 100`; a prior READ as
`Unlimited` still gets the plain reset (that is what the inverter itself reported); the mode read
is three-state and the cut refuses on *unread*.
**Guard:** `tests/test_955_huawei_export_device.py` (the uncapped recipe; the three states; the
refusal on `unavailable`) and `tests/test_921_handback.py::TestRecipes`; the measurement itself is
recorded in the arc's challenge record and in `docs/KNOWN_LIMITATIONS.md`.
**Sweep question:** for any brand verb SEM relies on — *has this exact call been seen to land on
the hardware, and what does the register read afterwards?* A service that returns cleanly is not
a service that worked.
Refs #955 #921.

### 97. A write cached as done because the call did not raise — the de-dup then locks the retry out — GUARDED
**Symptom:** battery-to-grid never engages on an AC-coupled battery, and after three refused
setpoints SEM withdraws it for good, blaming the setpoint entity. The reporter flips the strategy
select to `api` by hand and the same setpoint lands at once (@RienduPre, 2× Sessy, #978).
**Root shape:** `_set_strategy` recorded `_last_strategy = value` on the line after the service
call — "nothing raised" read as "it landed". HA answers a `select_option` it cannot deliver
(*"Referenced entities … are missing or not currently available"*) with a WARNING and a normal
return, so the first dropped flip was cached, and the de-dup — `value == _last_strategy → return`
— then blocked every later attempt for the life of the process, the 600 s probes included. A
guard built to stop churn became the mechanism of a permanent self-disable. Class 96's sibling
from the other side: there the register landed somewhere else, here it did not move at all; in
both, nothing read the answer back. Differs from #824/#915 (a register that ignores a write) in
that the *memory* of the write was the fault, not the register.
**Cure:** believe the entity. Nothing is sent when the select already reads the value; a flip is
cached only once the select reads it; one that has not landed after `STRATEGY_RETRY_S` is a MISS
on the #915 read-back ledger (entity, wanted, seen — the same Repair after three), said once and
re-sent; the setpoint is WITHHELD, with no strike against the device, until the strategy reads
active. Unreadable is its own state, not "did not land" (#925).
**Guard:** `tests/test_978_strategy_readback.py` — the dropped flip is not cached; the reporter's
night (four sends in 200 s, three misses, one warning, three `False` verdicts, no setpoint write,
strikes on the device 0, `supports_forced_discharge` still True); a laggy select costs one cycle
and no noise; a landing after misses clears the ledger. The `_hass()` fake in
`tests/test_battery_arbitrage_523.py` now REFLECTS `select_option` — a fake that swallows the
flip models the very dropped write the fix refuses.
**Sweep question:** wherever SEM keeps a "last written" value for de-dup — *is it assigned from
the entity's answer, or from the call's return?* A de-dup keyed on what was SENT turns one dropped
write into a permanent one. (#1066) The degenerate case: no entity, no call, and the limit was still
recorded — generic, GoodWe and Huawei **swept** (`_discharge_limit_unwritable`).
Refs #978 #915 #925 #1066.


### 98. An observer surface that spends less than it holds — GUARDED
**Symptom:** three faults on one install (RienduPre, #979, 2.1.0-beta.29), each of which cost the
reporter a session on a wrong hypothesis before the real cause turned up. `Sensor
charger_ev_charger_1_flow_solar_to_ev_power is unavailable` at WARNING, ~11 lines per charger per
flap, on two wallboxes that were merely idle. `Health check violation: Home consumption residual
clamped by 2887W` — the aggregate, and not one of the six readings it is computed from. `State
attributes for sensor.sem_diag_charger_control exceed maximum size of 16384 bytes`, every cycle,
which means that entity was never recorded at all.
**Root shape:** a diagnostic is written for the moment it is *emitted*, not for the reader who has
to act on it, and the information that would have made it actionable is already in the same scope.
Three ways it goes wrong, all present here: (a) a normal state is spent as a FAULT — `available`
had no notion of a state where "unavailable" is the correct answer (class 86's shape, one layer
out: absence as evidence), so it called the idle case a fault at a level reserved for faults, and
the noise is what buries the one warning that matters; (b) an AGGREGATE is reported and its terms
dropped — `health_check` names `clamped by 2887W` with `power.solar_power`, `grid_import_power`,
`battery_discharge_power`, `ev_power`, `grid_export_power` and `battery_charge_power` all in hand,
so the owner must reverse-engineer SEM's residual before they can even pick a sensor to suspect;
(c) a payload is published on a channel with a HARD CAP nobody measured against — HA's recorder
refuses an entity whose recorded attributes exceed 16 KB and then stores *nothing*, not just the
oversize key, so the observer's own surface disappears from history precisely on the installs big
enough to need it.
**Where it lives:** (a) every entity `available` property — `sensor.py` (the instance) and
`switch.py` (**swept**); the other five platforms never logged. (b) every message that reports a
disagreement about a quantity it computed: the residual clamp and the energy-balance branch beside
it (**swept** — both now carry the six terms, the clamp also names the largest demand term as the
first suspect), `check_flows`' per-string over-count (**swept** — it had the per-string map and
printed only its sum), `_reconcile_partition`'s member list (**swept** — each home member now
carries its source sensor and that sensor's raw reading, which is the line that identifies
RienduPre's `heat_pump=1906.00kWh`: a LIFETIME counter read as a day). `check_baseload_drift`
already named its largest mover — the precedent this row generalises. (c) every
`extra_state_attributes` whose payload grows with the install: #814's `detection_report` (the
instance — its sibling `control_entities` on the same entity had been declared unrecorded and it
had not, class 24), #638's plan timeline (`_PLAN_ATTR_BUDGET_BYTES`, which solved it once locally
in #758 and restated HA's 16 KiB as a literal — class 46, **rebased** on the shared constant), and
the observer switch's `would_decisions` / `withheld_commands`, on a platform that had no
`_unrecorded_attributes` at all (**swept**).
**Closure:** (a) unavailability is a STATE: `_update_from_coordinator` records WHY it took the
branch it took (`no cycle yet` / `nothing to compute` / `read empty past the dark-read grace`) and
the line says the reason at DEBUG. The faults that are real keep their own instruments — the
coordinator logs its own failed update once for the whole integration rather than once per entity,
and a source that genuinely died raises `inputs_degraded` and a Repair. (b) `power_terms` and
`largest_demand_term` are spelled once in `health_check` and used by every site that reports a
disagreement about the residual; the suspect is named as a suspect, never as a verdict (a house
charging a car legitimately has `ev` on top). (c) `RECORDER_MAX_STATE_ATTRS_BYTES` is the one
spelling of HA's cap, and `utils/attr_budget.fit_state_attributes` is the single exit gate on the
sensor and switch platforms: it measures the RECORDED subset the way
`recorder.db_schema.shared_attrs_bytes_from_event` does (unrecorded attributes are exempt *before*
the measurement, which is the whole mechanism), drops the largest recorded non-scalars until the
set fits, and leaves `attributes_trimmed` naming them. A future author who forgets the exemption
loses one attribute's history instead of the entity's.
**Guard:** `tests/test_979_observer_surface.py`. An AST lint over all seven entity platforms
(`_availability_faults`) fails CI on any `_LOGGER.warning/error/critical/exception` inside an
`available` property, with the #979 source as its vacuity twin; the recorder oracle builds a
detection report the size real hardware produces, computes the recorded subset HA measures, and
asserts it fits — its twin drops the exemption and shows the same payload blowing the cap; the
cap constant is asserted equal to `recorder.db_schema.MAX_STATE_ATTRS_BYTES`, so a host that moves
it fails loudly rather than silently. Around them: the reason for each of the three unavailable
branches, the six terms in both balance branches, the named strings, and the member evidence with
a twin showing the message without it.
**Measured the wrong side (challenge record):** the first cut budgeted against the raw 16 384-byte
cap. The recorder measures the entity's WHOLE attribute set — HA lays `friendly_name`, unit, device
class, state class and icon over `extra_state_attributes` first and excludes only `attribution` /
`restored` / `supported_features` — so a gate at the raw cap leaves an entity within ~150 bytes of it
reproducing the symptom. The budget is the cap minus that headroom (`RECORDER_ATTR_BUDGET_BYTES`,
15 000 bytes), the same figure the plan sensor had used since #581; and that plan figure also decides
what the LIVE state carries, so a "90 % of the cap" rounding rule that moved it by 255 bytes was a
behaviour change wearing a tidy-up's face. Trade-off kept on purpose: an internal, coordinator-computed
key that a future bug silently stops publishing now reports at debug like an idle charger's analytics;
the per-entity WARNING was that class's only instrument and also the noise — the cycle rig is the
right home for that guard (follow-up).
**Sweep question:** for every line SEM emits about something being wrong — what does the reader
have to do next, and is everything they need to do it already in this scope? And for anything
published on a host surface: what is that surface's limit, and who measured against it?
**Left for Guido:** the HA config-entry `options` API returns only one charger's flat `ev_*`
fields while the Configuration dashboard shows both (the `ev_chargers` list is canonical and the
flat keys mirror charger[0]). That is the legacy mirror working as designed, and it is what first
convinced the reporter that a second charger was unconfigured — a discoverability question, not a
fault, and not touched here.
Refs #979 #958 #814 #824 #758 #638 #581 #660 #771 #773 #872 #915.

### 99. A verdict that names a cause its own scope refutes — GUARDED
**Symptom:** SEM explains itself with a sentence that is false in the very state it was computed
from, so the reader debugs the wrong thing. RienduPre, #983, 2.1.0-beta.29, 18.09.2026: 5.8 kW
exporting for four and a half hours, and both lines SEM gave him were wrong. `no battery assist
(SoC 98% < buffer 70%)` — 98 % is not below 70 %, and the real cause was his own
`may_assist_ev: False` permission, a switch he could have flipped in a minute. `stability:
full-car backoff — car declined 5 start ladders` — on an Audi e-tron his dashboard showed at 54 %
against an 80 % target. The CONTROL was right in both cases (the pack was full, the car really was
declining, all fifteen surplus devices were on `control_mode: off`); only the account was wrong,
which is exactly why it became an issue instead of a self-diagnosis.
**Root shape:** a gate grows disjuncts; its sentence does not. `_idle_bridgeable`'s
"battery cannot assist" was one comparison in 2026-06, gained the #875 never-read arm and the
#893/#778 permission arm, and kept quoting the comparison — so two of three causes reported as the
third. The second half is the same defect without arithmetic: a branch names a cause it has no
instrument for. `charge_stability`'s give-up printed `full/refusing` from *no draw after
escalation*, and can never have had the evidence — a car at its ceiling is stopped by #548 inside
`decide` and never reaches the ladder at all, so **every** give-up that said "full" was guessing.
Distinct from class 98 (a surface that says less than it holds): this one says MORE — it spends
evidence it never had. Adjacent to class 47 (one word, two axes) and class 77 (a derived output
read back as testimony).
**Where it lives:** every reason/`why` string built beside a multi-disjunct gate, and every one
that states a relation rather than a reading. Swept: `decide._idle_bridgeable` (the instance — the
gate is now `_assist_blocked_why`, one resolver that IS the boolean, so the sentence and the
decision cannot drift), `decide_battery`'s EV discharge clamp (**swept** — it printed
`battery SoC unknown < buffer 70%`, a relation nobody evaluated, on the one input that was
missing), `charge_stability`'s start give-up and #610 backoff (**swept** — both now report the
offer and the draw), `ev_control`'s stall detector (**swept** — the give-up's own comment hands
the refusal to it, and it printed `car likely full` off the same setpoint-and-a-zero),
`decide`'s Zone 1 line (**swept** — it named `priority` when #870's sorting may have used a
different threshold, so the relation stayed true while the knob it named did nothing) and
`battery_charge_scheduler`'s at-target line (**swept** — a 1 % tolerance in the gate that the
sentence did not carry, so 79 % printed as `>= 80%`). Assessed and already true:
`_idle_bridgeable`'s "sun gone", `solar_only`'s surplus-below-minimum, `battery_charge_scheduler`'s
export-below-floor, `surplus_controller`'s stop condition, `charging_control`'s battery-priority
wait — each a single condition whose operands are its own.
**Closure:** where a gate has more than one reason to fire, ONE resolver returns the reason that
fired and its emptiness IS the gate (`_assist_blocked_why`); a further arm reaches every reader at
once. Where a gate carries slack or sorts its thresholds, the sentence names the boundary actually
used, not the knob it was written for. Where SEM has no instrument for the cause, the line reports the OBSERVATION
(`no draw at 10A after escalation — the car did not accept the start`) and hands the diagnosis to
the party that owns it (`check its own charge limit / departure timer`). And — class 82's sweep
question, answered for a stand-down whose cost is a LOSS rather than an unattended draw — the
backoff line carries what it is holding back — `SEM is withholding the 7500W it had sized for this
car`, worded as the OFFER and never as its funding. The first cut called it "surplus going to the
grid" and the reviewer refuted it in one line: `budget_w` is grid headroom under a night peak clamp
and solar-plus-pack in Zone 3/4, so the fix would have committed its own class.
**Guard:** `tests/test_983_reason_names_its_cause.py`, in two halves because the class has two.
(1) `failing_claims`, a contradiction detector for the arithmetic half: it strips thousands
separators and INERT brackets (those holding no operator — `(bare=9000W + redirect=0W)` is a
decoration, `(SoC 98% < buffer 70%)` is the claim), splits on the concatenation seams (` — `, `;`,
` + `) so no clause borrows the next one's numbers, then adjudicates every `< <= > >=` against the
operands beside it, allowing the display rounding (`_cw`'s 100 W, whole percents/amps) and skipping
mismatched units rather than inventing a conversion. A missing operand fails too — `SoC unknown <
buffer 70%` is the same defect wearing a word. It runs over the full `decide` matrix (6 modes × 5
pack states × 3 solar shapes × 3 tariffs; 120 of the 270 cases carry an operator, 217 adjudicated
comparisons). (2) `uninstrumented`, a vocabulary lint for the half with NO arithmetic in it — which
is the half #983 was reported for, and which the first cut left guarded by two hand-written
substring asserts. The EV path may report the setpoint SEM wrote and the watts it measured; it may
conclude nothing about the car from them, so `full` / `refusing` / `asleep` / `faulty` fail CI as
WHOLE WORDS in a give-up, a backoff, or any message in `charge_stability` / `ev_control` — an AST
lint over every `_LOGGER` call and every `reason=` in those two modules (including an f-string's
literal parts), not a source-text search, so it holds the whole module and does not add to #925's
shrink-only ledger. Vacuity twins: the pre-fix
`_assist_blocked_why` (31 failures), the reported line, the word-operand line, the decapitated
aside, an ASCII `->`, a thousands separator, `Wh` against `W`, and a rounding case that must NOT
fire. Around them: the permission/never-read/below-buffer instances, the gate-matrix equivalence
(`bool(resolver) == the old disjunction`, brute-forced over 2 700 combinations in review), the
withheld-offer clause pinned to the backoff gate with a zero-budget and a non-finite twin, and both
halves of why "full" was never supported: where SEM has the instrument (`soc_ceiling_reached`) it
idles in `decide` before the ladder exists, and where it has none (#610's own kWh-target,
no-SOC-sensor PROD case) there was never anything to read.
**Sweep question:** this sentence names a cause — which line of code checked it, and would the
same state have produced the same sentence for a different reason?
**Left for Guido:** (1) the #878 arm `_assist_blocked_why` still does not carry. `battery_assist_
potential_w` zeroes assist below `max(buffer_soc, dynamic_floor_pct)`, so a pack at 75 % with a 70 %
buffer and an 80 % overnight floor delivers nothing while the resolver — like the `or`-chain it
replaced — answers "it may assist", and `_idle_bridgeable` holds the contactor on grid watts (the
PROD 2026-06-27 case the clause exists to prevent). Pre-existing on both sides of this fix, and
adding the arm changes CONTROL rather than text, so it is named here rather than smuggled into a
wording change. (2) the class-82 sibling this exposes. `charge_stability`'s give-up was assessed in
#944 and dismissed on the axis of an unattended DRAW ("the car is NOT drawing; nothing runs
unattended") — but a stand-down's cost can be an unattended LOSS, and here it was 5.8 kW for four
and a half hours with nothing but a strategy-sensor substring to say so. A real surface (the
`charger_stop_war_stand_down` Repair + notification + card-status pattern, mirrored for a declined
start) is a product call and 16 translation files, so it is named here rather than guessed at.
Also unfixed and not SEM's: RienduPre's home-consumption residual swings ~5 kW cycle to cycle
(662 health violations), which is what made the surplus read 0–3000 W for the quarter-hour before
the ladder ran.
**SWEPT 19.09.2026 (#992) — and the first audit had cleared an instance of itself.** Three reviewers
over disjoint scopes found NINE more: four on surfaces that send someone to do something (the futile-shed
Repair telling people to add a charger SEM already manages; the force-discharge Repair asserting the
firmware lacks a register when all SEM ruled out was a flaky entity; the failsafe Repair naming a
charger-side fallback without offering the second controller its own sibling always offers; the
load-priority card labelling every EMERGENCY shed "peak protection" through a case mismatch), and five in
the decision surfaces (`export cut refused — holding the meter shut`; `sun gone` at 828 W of production
while the house exported; `SOC 80% (held from a dark read) ≤ reserve 70%`; `Deye force charge blocked: ok`;
`Min+PV grid pauses` on installs with no EV). **The lesson is in the miss:** when this class was written,
`decide.py`'s `sun gone` was assessed and CLEARED — the check confirmed the quoted comparison was the real
gate (true) and never asked whether the WORD survived the values in scope (false). A user hit it the next
day. The sweep question is literal: *can the reader's own state contradict this sentence?* — not "is the
quoted number the right one".
Refs #983 #979 #944 #893 #875 #778 #885 #610 #548 #461 #440.

### 100. A sensor's failure wearing the costume of a valid reading — GUARDED
**Symptom:** the energy balance needs a clamp to stay non-negative, repeatedly, on a healthy house —
`residual clamped by 1274W — solar=0W grid_import=0W battery_discharge=0W | battery_charge=1267W`
(#988, PROD 19.09 08:24). A house does not charge its battery from nothing.
**Root shape:** the input has TWO failure shapes and only one of them is recognisable as failure.
`unavailable` is bridged by the dark-read grace — 151 min of it over 24 h cost the published sensor
2 — while the same dropping inverter's hard `0 W` is indistinguishable from night, so it is accepted
as a measurement, enters the balance, and reaches `decide()`, where a 29-second false zero reads as
"no surplus" and can end a charge structurally (#461). The clamp is why it survived so long: it
repaired the SYMPTOM, so the house-consumption figure looked sane while its inputs were not.
**Cure:** refute the reading from the rest of the balance, not from a threshold on the sensor. What
LEAVES the house (battery charge + export) minus what enters it other than the sun (import +
discharge) is energy only the sun can have supplied; past a margin, a zero is a dark read — counted
exactly like an unavailable one (#902/#818), so the cycle does not steer on it and the entity
publishes unavailable instead of a zero it cannot stand behind. One-directional by construction: it
refuses a zero, never invents a value, because what the input WAS during the gap is not knowable here.
**Guard:** `tests/test_988_solar_zero_is_not_a_reading.py` — the reporter's morning, the three
EXPLAINED zeros (night, charging from the grid, exporting from the battery), the margin, the
untouched non-zero read, and a structural pin that the gate is called beside the battery gate it
mirrors. Vacuity: neutralising the physics turns five red.
**Where the check runs is part of the check (challenge record, #988).** The first cut put this gate
beside the battery gate at the top of ``read_power`` — and there ``grid_power`` and ``battery_power``
are still in the SENSOR's convention. Every sign correction happens further down: the manual
``grid_sign_invert``, the counter auto-detect, the one-tap user flips, the per-battery detection. On
a Pattern-B combined meter (SolarEdge, Fronius, Enphase, Powerwall, Kostal) a 2.5 kW night IMPORT
reads as EXPORT up there, so the gate would have marked solar dark on every night cycle of every
such install — a physics check reasoning from terms that did not yet mean what they say. The unit
tests could not see it: they hand the gate readings already in SEM's convention. The ORDER is now
pinned structurally (the gate's line must follow every sign-correcting call), and that pin turns red
on the refuted version.
**And a refutation needs a subject:** only a reading that WAS a number can have stopped being one.
Without that, a house with a producer SEM cannot see — a second array, a generator, an AC-coupled
battery behind its own meter — has its honest zero refuted every time that producer charges the
pack. The window is the dark-read grace already used everywhere else in the file.
**Sweep question:** for every input SEM trusts — *what does this sensor look like when it fails?* If
one of its failure shapes is a value inside the valid range, nothing downstream can tell it from
data, and the first sign will be a clamp, a hold or a guard firing for no visible reason.
Refs #988 #902 #818 #461.

### 101. An emptied collection read as an unanswered one — the delete that will not take — GUARDED
**Symptom:** a Remove row that is offered, accepted, logged — and changes nothing. "Cannot remove
second heatpump using config flow UI" (#990, @RienduPre): pick *Remove: Heat Pump 2*, the menu
re-renders with the pump still on it. Press it again, same. Add a pump afterwards and the deleted
one comes back as a phantom sibling, so the install now has **two**.
**Root shape:** a two-layer resolver written as `draft.get(K) or saved.get(K) or EMPTY`. `or` sorts
by truthiness, and an empty collection is falsy — so *"this dialog has not touched the list"* and
*"the user just emptied the list"* are the same value, and the resolver picks the saved copy for
both. That collapses precisely the one state removal exists to produce. It is silent because it
fails only on the LAST row: with two pumps configured, removing one leaves a truthy list and the
delete sticks; the bug is reachable only by the user who wanted none.
**The distinction that matters:** key PRESENCE, not value truth. Same line class 54 draws between
`None` ("nobody said") and `0` ("spend it all"), and the same line `_merge_form_input` draws between
a field left alone and a field emptied (class 30's second half) — one level up, on the container.
Silence and emptiness are different answers; `or` has no vocabulary for the difference.
**Cure:** one resolver, `config_flow._draft_list(flow, key)`, that asks `key in flow._data` and
falls back only on absence — never on emptiness. Its scalar twin `_suggest_discovered` does the same
for auto-detection.
**Where it lives — and the sweep was RUN, 19.09.2026.** Four sites carried the shape, and the AST
lint written to close it found three MORE that reading had not:

| site | key | verdict |
|---|---|---|
| `config_flow.py` heat-pump menu ×2 + unit editor | `heat_pumps` | **HAZARD** — #990's instance, fixed |
| `config_flow.py:1559` EV seed | `ev_chargers` | latent — remove never reaches 0 (primary is unremovable), fixed anyway |
| `config_flow.py` phase-guard page ×3 | `phase_guard_grid_l{1,2,3}_current_entity` | **HAZARD** — found by the lint, fixed |
| `config_flow.py` pv-naming | `pv_string_names` | safe — already writes `{}` explicitly and carries forward with `setdefault` |
| `config_flow.py` deye | `deye_program_groups` | safe — always exactly six rows, no empty state |
| `__init__.py:889` v2→v3 migration | flat `ev_*` | safe — options-over-data IS the documented #690 semantics, not a draft |

The phase-guard three are the class pointing OUTWARD, at discovery instead of at storage: clearing a
mis-detected current sensor stores an explicit `None` (#690), the `or` read that deletion as
silence, `discover_grid_phase_current_entities` re-offered the sensor, HA pre-filled the field with
the suggestion, and the next Submit re-adopted what the user had just taken out. Reachable exactly
when all three are cleared — which is the gesture of someone who means it.
**Why tests miss it:** the #685 removal test seeded the pump into `_data` and left `options` empty,
so the fallback had nothing stale to find and the delete "worked". A real install has the list in
`options` — the draft is empty at exactly the moment the fallback fires. *A fixture that never
saves cannot see a bug about what was saved.*
**Guard:** `tests/test_990_heat_pump_removal.py` — the reporter's gesture, the phantom-sibling
consequence, the surviving fallback, the phase-guard trio, and an AST lint over `config_flow.py`
that rejects ANY `or` chain reading one constant key from two different stores. That is the
structural half: the shape is now unrepresentable in the flow, so the next list — loads, batteries,
tariff rows — cannot re-learn it. Vacuity: reverting either fix turns four red.
**The sequel the fix creates, and must carry (#990):** making removal work breaks every id minted
from a list POSITION, because positional ids are unique only while a list is append-only. Remove
"Heat Pump 2" from `[2, 3]` and the next Add mints `heat_pump_3` a second time; `register_device`
keys on `device_id`, so the collision does not fail — the second unit replaces the first, inherits
its volatile state through the #847 transplant, and one physical pump is never driven again while
the log still reports two. Ids are now taken from the lowest free number, and `_heat_pump_rows`
renames a stored duplicate rather than dropping it, because configs written before this already
carry collisions. *Whenever a delete starts working, ask what was counting on it never working.*

**Aliasing is part of this class, not separate from it.** `list(stored)` copies the list and shares
the ROWS. `entry.options` is a read-only mapping at the top level and wide open one level down, and
`full_config = {**entry.data, **entry.options}` hands the LIVE coordinator the same row objects — so
merging a form into `rows[0]` edited the running charger with no save at all, and a dialog the user
abandoned still changed the install until the next restart. `_draft_list` copies rows.

**Known trade-off, deliberate (#990).** `_suggest_discovered` cannot tell a field the user CLEARED
from one that was empty when the page happened to be submitted — `_merge_form_input` writes `None`
for both. So an install that enabled phase guard *before* its current sensors existed will not be
offered them by discovery afterwards and must pick them by hand. That is the cheap failure; the
other direction re-adopts a sensor the user deleted on the next unrelated Configure save (the
options flow is one linear chain, so every save walks this page), and a wrong current sensor on a
grid-protection feature is not cheap. Closing it properly means recording the REFUSAL at submit
time, not inferring it from storage — left for Guido.

**The guard is flow-scoped — say so.** The AST lint parses `config_flow.py` only, and matches
`X.get("K") or Y.get("K")` with constant keys and inline receivers. It does not see variable keys,
subscripts, a receiver hoisted into a local, or any other file. Three known live siblings outside
its reach, **for Guido**: `coordinator.py:5155`/`:8932` read `_cfg.get("daily_ev_target") or
self.config.get("daily_ev_target", 0)` where `0` is a legal per-charger slider value, so a charger
told to want nothing is handed the global target instead; `__init__.py:626`/`:5274`/`:5464` carry
the same shape on `ev_chargers` (documented as deliberate, and `:626` hoists its second store into a
local, which is exactly the form the lint cannot match); `__init__.py:889`'s v2→v3 migration is safe
for strings but `or`-merges the bools and ints in `_EV_FLAT_KEYS`, so a stored `False` loses to a
stale `True`. Lifting the lint into `tests/ast_contracts.py` with an allowlist for the legitimate
per-charger→global idiom is the real closure.
**Sweep question:** for every collection or optional the user can shrink — *name the value that
means "empty on purpose", and show the read that can tell it from "not set yet".* If the read is an
`or`, there is no such value.
Refs #990 #685 #690 #627 #847.
### 102. A word borrowed without its reference — GUARDED
**Symptom:** a label that reads as an instruction is produced by something that never made the
comparison the word implies. A flat 0.36/0.36 tariff published `cheap`; the house sink read it as
"a better hour is coming", and the battery sat at a 0 W discharge limit overnight while the house
imported 3.66 kWh (#994).
**Root shape:** SEM's `PriceLevel` is Tibber's vocabulary, which is defined against a **3-day
moving average** and carries a "missing data" state. SEM kept the five words and dropped both the
reference and the absence. A CLOCK was then free to produce them — `StaticTariffProvider` answering
from "not 07:00–20:00 on a weekday" without ever comparing its two rates, `CalendarTariffProvider`
answering CHEAP unconditionally because the coordinator hardcoded an empty schedule — and eighteen
consumers across six chains could not tell an asserted level from a measured one. The history is
the proof that this is structural: #359 took six waves in four days, #728 two, and #524, #953 and
#879 each rediscovered the trap on first contact with the same word.
**Cure:** restore what the word lost. A level exists only when a comparison stands behind it
(rates that differ, on a day that contains both; a curve with spread); otherwise the answer is
`unknown`, and every consumer that would have waited acts now — the rule `sink_verdicts` already
followed for export. One vocabulary in one module, so a seventh consumer cannot invent a seventh
opinion. And the flat test is RELATIVE to the day's own mean, because an absolute cutoff in one
currency is the #359 defect itself (re-fixed at 1.69/kWh in #417 and in LKR in #549).
**Guard:** `tests/test_994_a_level_needs_a_reference.py` — the vocabulary, a model matrix on the
real providers (flat · HT/NT weekday · HT/NT weekend · empty calendar · dynamic fallbacks), and one
pin per comparative chain naming the harm it prevents. `tests/test_tariff_provider.py` was asserting
the defect as spec and was rewritten.
**Sweep question:** for any label SEM publishes or acts on — **what two numbers were compared to
produce this word, and what does it say when nobody compared any?** If the second answer is "the
same word", the label is decoration and something downstream is spending it.
Refs #994 #359 #728 #524 #953 #879 #925.

### 103. A diagnostic written as a side-effect and read back later — it describes whichever call ran last — GUARDED
**Symptom:** the one attribute a user reads to learn WHY a value came out that way names a
different input entirely. On the .175 rig `sensor.sem_tariff_price_level` published `normal`
beside `classifier_path: negative_price_shortcircuit`, on a current price of +0.00001 (#994).
**Root shape:** `_classify_price` set `self._last_classifier_path` as a SIDE-EFFECT and every
caller read the attribute back off the instance some time after the call. Two things then made
the string belong to somebody else: reading the price curve classifies all 96 slots on every
read, so the last slot wins; and `_get_percentile_breaks` returned early from its per-slot cache
*without* re-stating the path, so a cache hit left whatever was there. The diagnostic was merely
misleading until #994 made it **load-bearing** — `get_price_level` answered `None` when the path
began with `percentile_fallback_` — at which point a stale fallback string could erase a level
that real breakpoints had produced, and a stale negative string could dress a percentile answer
as a sign check. A tri-state answer may never rest on a value a different question wrote.
**Cure:** return the reason WITH the value from one call (`_classify_price_with_path` →
`(level, path)`), decide the tri-state from that return, and publish both from the same answer
(`_current_level_and_path`). Where a cache short-circuits the computation, cache the diagnostic
beside the result and re-state it on the hit. Sweep question: *if two different questions can
write this field, which one does a reader get?*
**Guard:** `tests/test_994_a_level_needs_a_reference.py::TestThePathDescribesTheLevelItShipsWith`
— a cache hit still names its own path; a stale fallback string cannot erase a real level; the
published path and level come from one answer; and an hour the classifier could not compare reads
`unknown` on the hour-wise accessor too, not a confident `normal`.

Refs #994 #359 #728 #925.

### 104. A rule table asked whether something exists, not whether it can happen TODAY — GUARDED
**Symptom:** the refusal a fix installs holds everywhere except the one day it was meant for.
`CalendarTariffProvider` answered CHEAP on a Sunday under the shipped EKZ preset, whose rules
cover Mon–Fri plus Saturday morning — reproducing #994's own incident through the calendar after
#994 had fixed it in the clock-based provider (#994, found by review).
**Root shape:** the sibling provider had the question right — `_both_rates_occur(when)` asks
whether THIS DAY contains both rates — and the second implementation asked a weaker one:
`any(rule is HT for rule in the whole week)`. A weekly table is a statement about the week; a
verdict is about a moment. The two differ on exactly the days a schedule leaves uncovered, and
three of five shipped presets have such days. Worse, `get_price_level_at(when)` received the day
and dropped it, and `get_tariff_data` used the same blind check — so `today_min`/`today_max`
carried the full spread and the SECOND gate (`variation_known`, which reads those two fields) was
fooled too. Going through the sanctioned accessor did not save a consumer, because the defect was
inside the reference itself.
**Cure:** when a sibling already answers a question correctly, port the QUESTION, not the shape of
the answer. Thread the moment through every accessor that takes one, and make the published
reference agree with the verdict — a `None` level beside a min/max that still spans two rates is
two answers to one question. Sweep question: *this guard says something is possible — possible
WHEN, and did anyone pass in the moment?*
**Guard:** `tests/test_994_a_level_needs_a_reference.py::TestTheCalendarKnowsWhatDayItIs` — every
shipped preset on a Sunday and on a Monday, Saturday morning under EKZ (a real comparison), the
NT-carved-out-of-HT-default mirror case, and the published min/max agreeing with the refusal.
**Second instance (#1040):** the Schedule-helper branch dropped the moment too. `_get_tariff_at(when)`
answered every hour with the helper's state NOW, and `_ht_can_occur` took the helper's existence as
a peak hour on every day. Harmless while no field could set a helper; once #1040 added one, the day
strip, the next change and the battery break-even at 02:00/14:00 would all have read the current
tariff. Cure: read the helper's week (`schedule.get_schedule`) and ask it about the hour given.
Guard: `tests/test_1040_calendar_schedule_field.py::TestTheHelpersWeekAnswersEveryHour`.
Refs #994 #638 #1040.

### 105. A sentinel given a name — every "is it missing?" test silently flips — GUARDED
**Symptom:** a fix that makes absence legible breaks the code that was already handling absence
correctly. #994 replaced a `None` price level with the words `flat` and `no_prices` so users could
tell a flat contract from an unreadable one; `decide.py`'s daytime grid-charge gate read
`tariff_level is not None and tariff_level not in {normal, expensive, very_expensive}`, and a
truthy string passed BOTH halves — so on a flat tariff SEM would have charged the car from the
grid believing the hour cheap. The issue's own disease, reintroduced by its own fix, one commit
later.
**Root shape:** `None` was carrying two jobs — "no value" and "no comparative signal" — and the
second job was being read by an `is not None` test standing in for a predicate nobody had written.
Naming the sentinel is right; it is what lets a user tell two situations apart. But every existing
test of the form "is this missing?" was implicitly a test of the form "is this a real answer?",
and only one of those two meanings survives the rename. Membership tests (`x in CHEAP_LEVELS`)
survive it untouched, which is why the sweep looks clean until you grep for the identity tests
specifically.
**Cure:** when a sentinel gains a name, grep for every `is None` / `is not None` / truthiness test
on that field IN THE SAME CHANGE, and replace each with the predicate it was standing in for —
here `is_cheap_name` / `is_expensive_name`, which the vocabulary already published. Then pin the
predicate over the full value set, sentinels included, so a seventh value cannot slip through.
Sweep question: *this field just gained a new possible value — which existing comparison was
relying on it NOT existing?*
**Guard:** `tests/test_994_a_level_needs_a_reference.py::TestAnAbsenceIsNotACheapHour` —
`is_cheap_name` parametrized over all nine values a level can take, plus an AST contract that no
`is None` test on `tariff_level` returns to the decide layer.
Refs #994.

### 106. A plausibility filter is the only witness that the CONFIG is wrong — and it only ever discards — GUARDED
**Symptom:** a device performs at a fixed fraction (or multiple) of what SEM believes it can,
session after session, and nothing in the system moves. No error, no unavailable entity, no Repair,
nothing in the diagnostics download; every guard reads as correct when inspected alone. #967
(@alexmc1510, Victron EVCS, Madrid): his car took a third of the watts SEM thought it was handing
it, all night, and the fault had to be inferred from a screenshot and a multiplication because the
one block holding the answer was in neither the card nor the file.
**Root shape:** a learner defends itself from implausible input with a band around a **configured**
nameplate — right, and necessary. But when the *configuration* is the wrong thing, every honest
measurement lands outside that band, so the filter accumulates, cycle after cycle, the one fact
nobody else in the system can derive — *the belief is wrong, and here is the count that fits* — and
spends it as a rejection. The model then falls back to the very nameplate the meter has refuted,
and cannot correct itself, because correcting itself is what the band forbids. The tell is a
**refusal reason whose name is a hypothesis about the config** (`phase_belief`, `wrong_unit`,
`sign_flip`, `prober_only`) with no consumer: the code had already worked out the diagnosis and
filed it under "no".
**Where it lives:** every plausibility gate that compares a measurement against a configured
constant. `watts_per_amp.record` — `phase_belief` (fixed here) and its sibling `implausible`
(deliberately left mute: a dead sensor and a car at 10 % of the offer produce it too, and guessing
from it is the cry-wolf this class must not become); `estimate_active_phases`'s 1..3 clamp;
`detection.disagreements` (`prober_only` rows, diagnostics-only); the battery sign detector's
`evidence` / `confidence` pair; the grid-sign auto-correction's log-only stand-down (already named
in class 82). **Sweep question: for every gate that throws a reading away as impossible — what
would have to be wrong for that reading to be RIGHT, and who is told when the gate keeps saying so?**
**Relation to its neighbours:** class 40 is the same collision seen from the value's side (an
invention defended by a ratchet built for measurements); class 82 is the same silence seen from the
decision's side (a deliberate stand-down announced only in the log). This row is the *detector*
view: the filter is not merely mute, it is the only witness there is.
**Closure:** the filter answers a question instead of only dropping a sample.
`WattsPerAmpLearner.phase_verdict` returns the alternative count, the setpoints behind it, how many
held samples support it, and the W/A the owner can check against their own meter — or `None`.
**The physics is asymmetric and the answer has to be too**, which is the part the first draft of
this fix got wrong and an adversarial review caught. A draw ABOVE what the belief allows refutes it
outright at any single setpoint (one phase carries at most `amps × voltage`), and that is the
direction that commands 3× the watts SEM thinks it bought, through a peak limit. A draw BELOW it
proves nothing alone: a car taking a third of the offer and a car on one of three phases are
identical at one setpoint — PROD's Zoe read "1 phase" at 10.15 kW on a 32 A offer, impossible at
7.36 kW per phase (#804). Nearest-fit would have convicted a correctly wired 3-phase wallbox whose
car caps at 3.7 kW, and the Repair would then have told the owner to set 1 — after which the capped
draw is *inside* the band, the learner adopts it as a trusted measurement, and 7 kW goes through
the peak guard with the learner's own table defending it. **What separates the two stories is the
LADDER:** a fixed power cap gives `W/A ∝ 1/amps`, a phase count gives the same W/A at every
setpoint. So the low direction needs two commanded setpoints at least 1.4× apart whose implied
counts agree within 0.25, and where SEM never moved the setpoint it says nothing — the honest
answer, not a guess that costs 7 kW. Two further bars: `PHASE_VERDICT_REFUSALS` (20, far above
`MIN_SAMPLES`) steady non-tapering cycles, and **no bucket under this belief ever having earned
trust** (a belief that explains real draw is not on trial). From there the verdict reaches a Repair
naming the value to set (`charger_phase_count_mismatch`, docs-side: the fix is one setting), the
charging-state sensor's `per_charger_phases` block beside the #804 estimate, and the diagnostics
download — which now carries `ev_watts_per_amp` and `charger_adapters.<id>.phases` at all, the gap
that made #967 unanswerable from the file. It follows the CONDITION (#944's rule) but is filed once
per (believed, measured) pair, because `async_create_issue` fires a registry event whenever a
placeholder moves and the sample count moves every cycle. It stays silent in observer mode (SEM is
not commanding the setpoint), on a phase-SWITCHING charger (the belief there is the sequencer's, so
the Repair would name a field that changes nothing — that is #804's not-taking question), and with
no car on the plug (#708: an idle box has nothing to be wrong about this cycle; a standing notice
is held, not re-argued).
**Guard:** `tests/test_967_phase_belief_surface.py` — the reporter's ladder convicted, a 3.7 kW and
a 2.5 kW capped car NOT convicted, a single setpoint declining to answer, two setpoints too close
declining, both over-command cases caught including the partial draw that nearest-fit called
`implausible`, the trusted-bucket and 20-cycle bars, restart survival with per-entry repair, the
quoted evidence bounded to what is still held, the Repair's raise/clear/once/disconnected/observer/
switching paths, the placeholder set rendered from the real raiser against all 17 string files, the
docs anchor, a `call_sites` contract that the cycle actually asks (deleting the one call site left
every other test in the file green), and a vacuity twin (class 8).
**Left for Guido:** (1) `ev_phases` has no **provenance** — class 40's own prescribed closure. SEM
cannot tell "the owner said 3" from "nobody said, so 3", so the Repair words itself around the
difference instead of stating it. (2) The verdict is a notice, not an action: SEM keeps converting
with the refuted nameplate until a human changes the setting. Auto-adopting downward is arguably
safe and upward certainly is not, so the asymmetry needs a decision, not a patch. (3) The refusal
evidence does not decay, so reverting a corrected `ev_phases` re-accuses from the stored samples
the same cycle — right, but worth a deliberate look. (4) No orphan sweep: deleting a charger row
leaves its Repair until restart, which every per-charger repair in SEM shares. (5) `implausible`
stays mute — a Repair there needs field evidence about what actually produces it.
Refs #967 #966 #939 #846 #804 #744 #944.

### 107. A saving that spends someone else's limit — a hold that hands the meter a bill — GUARDED
**Symptom:** a feature that is *supposed* to import does, on purpose, and the month's capacity
charge goes up. Nothing in the logs is wrong: the hold engaged in the hour it was built for, the
saving it names is real, and the peak layer — which is *senior to every mode of every device*
(#864, 29.08) — was never asked, because the new layer does not command an import, it merely
declines to prevent one. **Root shape:** SEM's peak defence bounds every command that *creates*
import: the EV offer (`decide.clamp_to_peak_slot`), the cheap-hours top-up
(`surplus_controller` → `clamp_import_command`), the battery's own night charge (its
`peak_limit_w`). A saving-shaped feature creates import from the other side — by removing a cover
that was already there — and that side had no clamp. The economics make the omission look safe
("we only pay the spot price for an hour we chose"), and the cost is invisible for up to a month:
a capacity tariff bills the WORST 15-minute slot, so one bad quarter hour costs more than the
feature saves in a season. **Where it lives:** every `LIMIT_DISCHARGE` that lowers the pack's cover
on purpose — the #879 house sink (`decide_battery`, the reported instance), the #620 grid-funded
clamp beside it, and the EV protection clamp's own `- gf_w` subtraction; the #926 battery-headroom
hold (assessed: it holds CHARGE headroom, which lowers import, so it is not this class); anything
future that answers "keep the energy where it is". **Live catch (#1003, found by review of the
peak layers, not from a report — `battery_house_sink_enabled` is off by default, so no install was
exposed).** **Closure:** one floor under every such limit — `decide_battery.peak_cover_floor_w`,
over `peak_guard.cover_for_peak_w`, the mirror of `clamp_import_command`: what a command may ADD
and what a hold must GIVE BACK read one slot budget.
**The trigger is the HOUSE'S OWN import (`home − solar`), never the meter's total**, and an
adversarial review is what separated them. Sized from the total, a 9 kW car and a 400 W house
under a 6 kW limit tell the pack to cover its whole house load for a breach that is entirely the
car's — and the charger's clamp, which computes its own headroom as `allowance − (meter − own
draw)`, then reads the lowered meter as room and takes exactly the watts the pack freed. Two
layers sized against one allowance from the same total is a *free fixed point*: total import
unchanged, peak unchanged, pack drained into the car in the cheap hour the user asked to keep it
(the #545 shape, class 80's "which term carries the invariant" asked about a meter). The house's
own draw is the one quantity with nobody else to answer for it; the car, the pack's own charging
and the cheap-hours loads each already have a clamp of their own against the same number.
Bounded by `home_consumption_w` (which excludes the car), split across the fleet like the limit it
floors, never lowering one. A cycle that cannot see does not hold at all: `home_consumption_w` IS
the energy balance's residual, so any dark read moves it (#818), and the release is issued as
`LIMIT_DISCHARGE` at the house cover rather than `NORMAL` — `actuate_battery` refuses a FLIP
between those two on a degraded cycle, so a release spelled `NORMAL` is never written and the 0 W
stands through exactly the blindness that released it. **Guard:**
`tests/test_1003_the_hold_yields_to_the_peak.py` — the reported case through the real decider, the
pre-fix 0 W pinned so the plumbing cannot rot back quietly, the car-alone case, the sun-first
subtraction, the fleet split, the dark house figure built by the REAL `calculate_derived` (not
hand-fed) and the release proven to reach the adapter through `actuate_battery`'s own degraded
guard, the clamped balance, both sibling clamps, and `call_sites("FleetContext")` over the peak
axis. **Sweep question:** for every feature whose
benefit is a price — *what does it make the meter buy, and who bounds that?* And for every layer
sized against a shared allowance — *does it subtract the draws that answer for themselves, or the
whole meter?* A layer that never issues an import command can still be the reason for one.
**Residuals (for Guido), all one shape — the floor is promised and may not be delivered, and
nothing says so at runtime:** (1) `#900`'s `DISCHARGE_LIMIT_LOWER_DWELL_CYCLES` makes LOWERING wait
six cycles and resets the streak on every raise, so an input that blips once a minute (the #818
motivation names 8-15 % of cycles on a Huawei modbus) pins the limit at the release value and the
#879 hold never comes back. Safe direction, dead feature; the seam that would fix it is a
`follows_load` flag on `BatteryDecision` read by `actuate_battery` — a change to the actuator's
contract, so it is a call, not a sweep. (2) The #531 fleet split divides the cover by the battery
count, so an empty or unreachable pack silently under-covers — the split's failure mode is
over-injection, and on a floor it is a breached limit. (3) The cover is not bounded by
`battery_max_discharge_power`: a 12 kW house under a 3 kW allowance asks 9 kW of a 5 kW pack, the
adapter clips it, and the reason still says the pack covers 9 kW. (4) `battery_adapters/deye.py`
records "discharge limiting is not implemented", so on Deye this whole floor is a no-op —
pre-existing, but this is the first feature where that silence is a billed peak rather than a
missed saving. (5) A fresh `PeakSlotTracker` after a restart reports `imported_kwh=0, elapsed_s=0`
mid-slot and grants the full target as the remaining average, so the cover under-sizes for up to
15 minutes after every restart — #864's own shape, which #1003 now leans a billed guarantee on.
**Neighbour:** class 93 is the other half of this instance — the peak numbers had ridden
`build_view`'s charger context since #864 and never the battery pipeline's own, so the decider read
`None` and could not have asked. Refs #1003 #879 #620 #864 #818 #545 #955.

### 108. A permanent fault answered by a transient-fault retry policy — honest retry becomes endless retry — GUARDED
**Symptom:** a command the user never issued runs on every cycle for the life of the install, and
the one line of diagnostics that could explain it says the opposite of what is wrong. @RienduPre's
2× Sessy, 28 h after a restart: `last_error: "stop_forced_charge failed: Stop failed: expected
'all' or 'none' at 'entity_id'"` and `setpoint.device_refusals: 165` per unit — on a battery that
had never force-charged, could not force-charge (no switch configured), and was not being asked to.
**Root shape:** two correct rules, composed. (1) A per-cycle decision (`decide_battery` returns
STOP_FORCE_CHARGE on every cycle outside the plan block) is made quiet by a de-dup that keys on
what the hardware was LAST TOLD (class 38 / #757). (2) That marker may only be set on a command
that LANDED, so a dropped write is retried rather than remembered as a success (class 4 / #589
honest retry). Both hold only while failure is TRANSIENT. Feed the same policy a fault that can
never clear — a config gap, an actuator that does not exist, a register the device refuses in its
current mode — and the de-dup can never arm: the retry is not a retry, it is the steady state. The
flood the first rule closed comes back through the second rule's door, and nothing looks wrong at
either end. **Live catches (#1005):** (a) `GenericChargeAdapter.stop_forced_charge` sent
`switch.turn_off` with an empty `entity_id` when no force-charge switch was configured — rejected
by HA's service schema, reported FAILED, retried for ever; `start_forced_charge` had the guard, the
stop did not. Same in `GoodWeChargeAdapter` (`select_option` with no work-mode entity) and
`HuaweiChargeAdapter` (FAILED with no `inverter_device_id`).
(b) One layer up, the #523 mutual-exclusion zero wrote the power setpoint of an AC-coupled battery
sitting in `nom`, which #978 measured that this hardware REFUSES: a refusal per cycle, and three
withdraw battery-to-grid (#840). #978's rule — never write a setpoint the strategy select says is
ignored — had been applied to the two force paths and not to NORMAL / OFF / LIMIT_DISCHARGE / the
two stops. **Closure:** an unsatisfiable command is DONE, not FAILED. `_nothing_to_stop()` in
`force_charge.py` returns IDLE and sends nothing when the actuator the matching `start` refuses to
run without is absent — nothing could be running, so nothing needs stopping and the intent is
recorded. `BatteryControlAdapter._zero_setpoint()` is now the one door for the #523 zero (Huawei's
number-entity stop included) and skips it when `_setpoint_is_inert()`; the generic adapter
overrides that to ask the strategy select. A skip also FORGETS `_last_force_discharge_w`: that
marker is the de-dup's only evidence the register holds a value, and SEM may claim it only for a
write it made — review's repro was one dropped zero on the hand-back cycle, after which the next
force op at the same power was de-dup'd away and SEM reported a sale that never happened.
**Fail-safe direction matters and is not the same question as #978's:** `_strategy_is_active` asks
"will a write land?" and says no when the select is unreadable; `_setpoint_is_inert` asks "is the
register already controlling nothing?" and an unreadable select cannot say so (#925), so an unread
select still gets the zero — a zero can only ever stop a battery, never start one. And "not the
active value" is not an answer either: `battery_strategy_active_value` is user-editable and the
roster rewrites the whole vocabulary per brand, so only the modes SEM sets ITSELF on release
(self-consume / idle / off) count as inert. Review's repro for the first cut: a battery really in
its API mode exporting 1700 W, with the active value misconfigured, was read as "the register is
dead" and SEM reported NORMAL while it kept selling.
**Where it lives:** every `command_*` that returns early on a delegate's FAILED without recording
intent (`battery_adapters/{generic,goodwe,huawei,deye}.py`), and the same shape on the EV side
wherever a brand call reports failure for a missing entity rather than for a refusal. `deye.py` is the model for the case it covers — no snapshot to
restore → record the intent and be quiet — but not free of the class: it also returns without
recording when `_observer_mode or not _actuation_enabled`, states that never clear by themselves.
**Guard:** `tests/test_1005_stop_with_nothing_to_stop.py` — the reporter's night through the real
adapter (the setpoint never written into `nom`, no strikes spent, silence after the first cycle),
a real hardware refusal still FAILED, a configured actuator still cleared on a fresh post-restart
adapter, an unreadable select still written, and two oracles: every delegate discovered in
`force_charge.py` must answer an empty config without FAILED and without a service call, and every
adapter discovered in `battery_adapters/` must fall silent after one stop. Both walk the
package's modules with `pkgutil`, not `__init__.py`'s exports — an oracle that can only see today's
exports is a hand-maintained list wearing discovery's clothes — and the adapter walk asserts it
found at least four, because a discovery that finds nothing passes everything. The fake `hass` REFUSES
an empty `entity_id` and REFLECTS `select_option` — the #757 tests mocked `stop_forced_charge` with
a fake that always succeeded, which is why they could not see this. **Sweep question:** for every
"failed → do not record, retry next cycle", ask *what makes this failure go away, and can it?* If
the answer is "a config change" or "a different device mode", the retry is a permanent per-cycle
write and the error message will name the symptom, never the cause. Report the two apart: a
refusal by hardware is FAILED; an absent actuator is nothing to do.
**Residuals (for Guido).** (1) `HuaweiChargeAdapter.start_forced_charge` answers the SAME
permanent gap with FAILED, retried every in-window cycle — and nothing in production ever writes
`inverter_device_id` into the config the delegate holds (`HuaweiBatteryAdapter` autodetects it into
its own `_inverter_device_id` and does not pass it down), so on Huawei that is every install and
grid charging cannot work at all. Closing it switches grid charging ON for every Huawei install at
once, which is a call, not a sweep. (2) a setpoint that the device refuses while the strategy READS
active is
still honest-retried for ever by `command_stop_force_charge`'s `if not ok: return` — #840 throttles
the wire to one silent probe per 600 s and raises the Repair, but the intent is never recorded and
the stop path re-enters every cycle. Closing it means deciding what a withdrawn register means for
the state machine (record the stop that cannot be sent, or keep the flood), which is a contract
call, not a mechanical guard. Refs #1005 #757 #589 #978 #840 #925.
**The wait-shaped twin — #804 (@HorizonKane).** The same composition without a retry: a HOLD whose
exit condition a permanent fault can never meet. The phase sequencer stops the charger before it
switches (never switch under load) and waited for the draw to reach zero with no bound. On a box
SEM could not actually stop, that wait never ended — and the hold replaces every charge command
with DISABLE, so the charger was never commanded again for the rest of the session: "SEM sends no
commands". **Closure:** `STOP_WAIT_S = 120 s` (a Zaptec opens in 3-15 s, measured), then the switch
is given up and the target marked not-taking, which a new target or a replug clears. **Guard:**
`tests/test_804_no_commands.py::TestTheHoldGivesUp`, including the end-to-end pass through the real
control path. **Sweep question:** for every wait on hardware, what makes it end if the hardware
never answers — and what is held hostage while it waits? Refs #804 #1005.

### 109. A field that means "not applicable" carries a number, and a new reader takes the number — GUARDED
**Symptom:** a mode that says *unlimited* behaves as if it had nothing. coppe218's Zaptec on
Always (max) with Phase mode Auto charged at 16 A on ONE phase (~3.3 kW) all session and never
asked for three; the same planner would have scaled a three-phase session DOWN ten minutes in.
**Root shape:** `ChargerDecision.budget_w` answers "how much SOLAR did `decide` size for this
car". `AlwaysMaxMode` has no such number, so it writes `0.0` with the comment *not
budget-limited* — a sentinel that happens to be a valid quantity. Every established reader asks
the INTENT first (`solar_commitment_w`, `commanded_power_w`, `active_phase_guard`, all of which
special-case `CHARGE_MAX`); the #804 phase auto planner was written later, read the field raw,
and got the pessimistic answer. Nothing failed, nothing logged — the planner simply never had a
reason to act.
**The tell:** a field whose docstring names ONE intent, read by code that runs for all of them.
Grep the field, list its readers, and ask each one *what does this mean when the other intent is
in force?* A sentinel inside the value's own range cannot answer that question for you — this is
class 105's disease (`None` doing two jobs) with the sentinel hidden inside the number line
instead of beside it.
**Where it lives:** `ChargerDecision.budget_w` (0.0 under `CHARGE_MAX`, and 0.0 on every
grid-funded `CHARGE_AT_AMPS` — the night floor, the deadline current and the cheap-hours top-up
all command amps the grid pays for and size no solar budget); `BatteryDecision.discharge_limit_w`
outside `LIMIT_DISCHARGE`; `ChargerDecision.commanded_amps` under `CHARGE_MAX`, where the adapter
resolves the real current and the 0 already bit the #804 belief once. Swept and left alone: the
two fleet readers of `commanded_amps` — the stall-means-full detector gates on `>= 6`
(`coordinator.py:12599`) and the W/A learner on `>= 1` with a 400 W floor
(`coordinator.py:1073`) — so `CHARGE_MAX` reading 0 only ever makes them do less.
**Closure:** `ev_control._power_on_offer_w` — one function that answers "watts this charger may
draw", branching on the intent like its siblings. Under `CHARGE_MAX` that is the charger's own
ceiling (from `resolve_max_current`, #746) priced at three phases, so a ceiling equal to the
three-phase minimum correctly shows no headroom.
**Two hazards the first cut of that fix opened, both found in review.** (1) *An idle decision is
not a starved one.* `AlwaysMaxMode` also returns `budget_w = 0.0` on IDLE when the car is
unplugged, and the tick runs every cycle, so a parked three-phase charger was scaled back down
ten minutes after each unplug and the next session started on one phase — two contactor
sequences per plug cycle, forever. The planner is now asked only while the car is connected, and
`PhaseAutoPlanner.new_session` clears the sustain clocks so the last car's window is not spent on
this one. (2) *A constant offer never falls.* Under `CHARGE_MAX` the offer always clears the
threshold, so the up-clock could not reset and a box that does not really switch would be stopped
and retried for every switch the session cap allows. The #804 give-up (two contradicted switches
→ leave the target alone) was manual-mode only; the auto branch reset it every cycle. It now
applies to both.
**Peak safety is real but conditional.** When the slot guard or a shed order bites, the decision
is no longer `CHARGE_MAX` and the planner reads the clamp's real budget. When it does NOT bite,
the guard is priced with the CONFIGURED phase count, so on a charger configured 1-phase a 16 A
ceiling prices at 3680 W, the guard passes it, and three phases would then draw 11 kW inside that
slot. The slot allowance is therefore passed in and caps the offer: never ask for three phases
the meter cannot pay for.
**Guard:** `tests/test_1008_always_max_phases.py` — the reporter's session end to end (one phase
→ switch to three), a three-phase session that is not scaled back down, a parked charger left
alone, a replug that starts the window over, a box that gets two tries and no more, a peak-clamped
Always (max) and a slot too small to pay, plus two pins on the wiring: `_phase_switch_tick` calls
`_power_on_offer_w`, and it never reads `decision.budget_w` again. Seven of the eighteen fail
when the fix is reverted.
**Residual (for Guido).** The grid-funded `CHARGE_AT_AMPS` decisions carry the same `0.0`, so the
auto planner is equally blind at night: a three-phase overnight floor still scales down after ten
minutes. Feeding it the commanded watts instead would also let a one-phase 32 A floor switch UP,
and the night rate, the deadline current and the peak slot guard are all computed from the
`ev_phases` CONFIG — changing the phase count under them changes arithmetic they own. That is a
contract call across three layers, not a mechanical sweep. Refs #1008 #804 #105.

### 110. A feed we append to, read through a fixed window — the one item the reader needs scrolls out — GUARDED
**Symptom:** nobody could install SEM. HACS answered `404` on
`releases/download/45438ef/solar_energy_management.zip` — a download from a commit sha, where no
release can exist. Nine days, and it took a reporter to tell us (#1012).
**Root shape:** HACS asks GitHub for ONE page of releases — thirty — and skips every pre-release
unless the user ticked "show beta versions". We cut a beta per fix. Once thirty betas stood above
v2.0.0 the newest full release had fallen off that page, so HACS had no version to offer: it fell
back to the branch head's short commit sha, and `hacs.json`'s `zip_release` turned that into a
request for a release ASSET at a sha. Both halves are ours — the cadence that fills the window,
and nobody watching the window. 41 betas stood above the full release when it was reported.
**The tell:** we append to something a reader consumes through a fixed window (a page, a
`--limit`, "the newest N"), and something older than the window still has to be reachable. Ask
what the reader must still see, and how fast we push it down.
**Where it lives:** GitHub releases read by HACS at a page of 30 — the instance, and the only one
with a user-facing cost. Swept: `scripts/mutation_audit.py` asked for the newest 60 closed bugs
`--since` a date and reported as if that were all of them — widened, and it now says when the
window filled. `enhancement-sponsor.yml` paginates, so its "note already posted?" check reads
every comment. No other repo script decides anything from a windowed read.
**The trap this fix walked into first, and the reason the tell is worth memorising.** The first cut
read the releases with ONE `per_page=100` call. A token with write access sees drafts, so every
beta the fix retired kept its slot in the fix's OWN view: at the measured rate (42 betas in 26
days) that read would have filled up in about five weeks, reported "no full release at all",
retired nothing, and let the live index climb past 30 again — #1012 rebuilt inside the fix for
#1012, with a diagnostic saying the opposite of the truth. Found in review. It now reads every
page and refuses to decide from a partial list.
**Closure:** `scripts/hacs_release_window.py --retire` — the betas with the oldest `created_at`
standing above the newest full release go back to draft until it sits at index 10, twenty slots
inside the page (about twelve days of warning if a run ever fails; #1012 went unseen for nine).
Picking by date, not by listed position, is deliberate: GitHub's order is its own, and two
releases here are listed against their creation order — by date the release just published is
provably the last one the picker could ever reach. A draft keeps its tag and its notes, and one
`gh release edit <tag> --draft=false` puts it back; it does NOT keep its download, so anyone
pinned to a retired beta must move to a live one. A full release is never touched, and betas-only
retires nothing — it cannot conjure a release to save. Hung off `release: published`, which covers
all three publishers, plus inline in `create-release.yml` — the GITHUB_TOKEN path fires no event,
the same exception the download zip has.
**Guard:** `tests/test_1012_hacs_release_window.py` — the reporter's state end to end through
`main()` (retire, then re-read, and green only because a plain install works afterwards), the page
edge at 29 and 30, oldest-by-date first whatever GitHub listed, a draft takes no slot, both release
paths call the retire, and the two refusals before the only destructive call: a full release, and a
tag already retired. Ten mutations of the picker, the exit code, the fetch and the refusals each
fail a test.
**Residual (for Guido).** The stable channel now offers v2.0.0 — a month and 41 betas old. This
keeps it reachable; only cutting 2.1.0 makes it current. Nothing Guido already watches reports a
failed run: the autopilot follows branch CI and the release asset, not this job. Refs #1012 #834.

### 111. Work of unknown length awaited inside setup — the host cancels it and NOTHING loads — GUARDED
**Symptom:** the integration does not start. One line in the log, and no SEM at all:
`Setup of config entry 'Solar Energy Management' ... cancelled` /
`asyncio.exceptions.CancelledError: Global task timeout: Bootstrap stage 2 timeout` (#967,
@alexmc1510). The trigger was adding one more power sensor to the Energy Dashboard.
**Root shape:** Home Assistant gives all integrations one shared budget to start in, and
`async_setup_entry` is inside it. SEM awaited the recorder there — 60 days of EV power history for
the taper detector, 7 days per load for the rated-power seed, a `LIKE '%solar%'` statistics scan
for the install date, another for the yearly totals — each a database read whose cost is the
user's history, not ours. Every one of them was *called* "best effort, never blocks setup" in its
own comment, and each was awaited. Two things make this class bite harder than a slow start:
a cancel arrives as `CancelledError`, which is **not** an `Exception`, so every `except Exception`
"this must never cost us the setup" handler on the way up passes it straight through; and the cost
grows with the install, so it passes every test and every small system and fails on the big one.
**The tell:** an await inside setup whose duration is set by data we do not own — a database, a
network call, a device that answers when it feels like it. Ask what the biggest install costs,
not the test one. A comment saying "never blocks setup" next to an `await` is the same tell.
**Where it lives:** every recorder read. Swept in one change: `features/device_registry.py`
(`_history_max_power`, the reported one), `coordinator/ev_taper_detector.py`
(`async_seed_from_history`, 60 days), `energy_calculator.async_detect_install_date` and
`seed_yearly_from_statistics` (both reached through the first update cycle, which setup awaits),
and `wpa_replay` (already a task, now also held until after start so it does not compete with the
boot). The backfill services are user-triggered and were never on this path.
**Closure:** `coordinator/recorder_history.py` — one door. `run_after_start()` is how a caller asks
for recorder work: it waits for `EVENT_HOMEASSISTANT_STARTED`, or puts the work on a task when HA
is already running (a reload, where the started event never comes again). The work is never in
setup's await chain, which is the whole property — on a reload it may still finish before setup
returns, and that is fine, there is no start-up budget outside a boot. It hands back an unsubscribe
and every caller keeps it: a fresh install reloads itself during the boot (the welcome notification
writes an option), so a coordinator that forgets leaves a dead twin waiting to do the work as well.
`read_states()` is the only entity-history query, and it is the cheap shape — the attributes stay
in the database, and the window is never longer than the recorder keeps. That clamp reads
`auto_purge` first: `keep_days` is what the purge deletes past, so on an install that purges by
hand it says nothing about what the database holds. Nothing is dropped, only deferred: a load
skipped during setup is not marked as tried, so the seed happens one pass later.
**Guard:** `tests/test_967_no_recorder_during_setup.py` — a real Home Assistant, set to *starting*
the way a boot is, with every door to the recorder wired to a list: setup must read it zero times.
Both halves are pinned, because the cheap way to pass the first is to delete the work: a second
test fires the started event and fails unless the reads happen AND both deferred seeds were handed
their turn by name. Each half was verified by breaking it — remove the two gates and the first goes
red, remove the hand-over and the second does. Plus: the four history APIs are read in one place
only, and the query shape, the keep-days clamp and the hand-purged install each have a test.
Statistics and the install-date sqlite read are not behind the door — they stay off the setup path
by their caller's gate — but the oracle catches them anyway, because it patches the recorder's own
entry points rather than SEM's. Refs #967.

### 112. Every guard bounds the RATE; the thing the peer counts is the COUNT — GUARDED
**Symptom:** the pacing is provably right and the hardware refuses anyway. @hoyte's Zaptec Go 2
(#975, 2.1.0-beta.20, solar+battery on a cloudy day) puts up *"Charging has been stopped too many
times. Please reconnect the vehicle"* and stops charging for the rest of the plug-in. Nothing in
SEM's log is wrong: every stop cleared the rolling median, the 2 A deadband, the 30 s cadence, the
180 s disable delay and the post-stop settle, and each one was the correct answer to the surplus at
that moment. **Root shape:** SEM's guards are all *rate*-shaped — a minimum interval, a dwell, a
delay, a cycles-per-hour floor. The peer's consumable is *count*-shaped and scoped to a session:
spent, never refilled, until the car is unplugged. A rate bounds an average over a window, so a
long enough window spends any budget: no value of any delay bounds a count. That is why the fix for
this class is never a bigger number — tuning the delay changes how long the afternoon takes to
spend the budget, not whether it does. Measured on SEM's own loop: a six-hour afternoon whose surplus
flickers every five minutes spends one interruption per cloud — **36** — against **6** once the
widening is in. The 36 is the scenario's own cloud count, not an emergent number; what was emergent
before the fix is that nothing in SEM counted them at all. The neighbouring
machinery hides it exactly as in class 81, and not all of it even bounds speed: the rolling median
and the 2 A deadband bound the signal's AMPLITUDE, the cadence and the disable delay bound the
rate, and the post-stop settle clears on the car's own draw rather than on a clock. Five
mechanisms, three shapes, and not one of them a number of stops. `_stop_war_rounds` *does* count —
the BOX's restarts, not SEM's stops. **Where it lives:** any peer with a finite per-session or lifetime operation budget.
The **closed precedent** is `ev_phase_sequencer`, which already carries both shapes —
`AUTO_MIN_INTERVAL_S` for the rate and `AUTO_MAX_PER_SESSION` against `_session_switches`, reset by
`new_session()` on a plug-cycle — so the stop path was the one actuator that had the rate half and
not the count half. Assessed and **not** this class: the battery adapters' `_last_discharge_limit_w`
hysteresis (a 100 W band, so the DISCHARGE-LIMIT register's write count follows the decision rather
than the cycle — `_zero_setpoint()` and `_set_strategy()` run before that return, so the claim is
about that one register); #536's enable backoff (already count-shaped — five attempts, then it stops and reports);
`SwitchDevice`/`ClimateDevice` `min_on`/`min_off` (a rate over a relay's lifetime count, with no
per-session latch on the other side that we know of).
**Closure:** the hysteresis GROWS with the churn it has already caused, in `charge_stability` —
`SESSION_STOP_BUDGET = 4` interruptions per plug-in are free, then each further stop MULTIPLIES *both*
the enable delay and the TRANSIENT bridge by a factor that grows `SESSION_CHURN_PER_STOP` per stop,
to a dimensionless `SESSION_CHURN_MAX = 4.0` — so the 180 s bridge reaches 720 s, not 4 s. The charger that flaps twice an hour never notices; the one being interrupted
every few minutes ends up bridging through the clouds instead, which is what the reporter asked
for. Three scoping decisions carry it: only a **disconnect** refunds the budget (a mode change or a
restart must not — the charge point's own counter does not reset for either, so `session_stops`
round-trips through `snapshot_timers`/`restore_timers` with a bounds check); the **structural** stop
(#461) is excluded, because with the sun gone there is nothing to bridge to and the hold would
import grid to keep a contactor closed — slack is for flicker, never for nightfall; and the widening
is applied to the *delays*, not to a refusal, so nothing is swallowed and no retry budget is spent
on a command that never went out (class 81(a)).
**Guard:** `tests/test_975_session_interruption_budget.py` — the factor and both delays pinned, the
two things that must not move (a structural idle still stops inside 120 s at maximum churn; a fresh
plug-in starts a fresh budget), the restart round-trip and a corrupt blob. Around them a **count
oracle**, the only pin written in the units the charge point actually uses: a six-hour flicker
driven through the real `ChargeStability`, counting what one plug-in spends. Each count is asserted
as a PAIR against the same afternoon with the widening neutralised, because a bound on its own is
also satisfied by a run that stopped nothing — so each pair carries a floor (the free stops ARE
spent; the unbudgeted day really does churn past them) as well as a ceiling, and `_flicker` raises
if SEM never took the session (#552), the ownership regression that would otherwise report zero and
pass. Be honest about what this buys: the count is a closed form in the constants, so it is not
proof against a retune — it is proof that the factor is still WIRED to the real filter and that the
increment site is still reached.
**Sweep question:** for every limiter SEM owns, ask *what the peer is counting* — and whether our
guard is written in the same units. If ours is "not more often than every N seconds" and theirs is
"not more than K per session", the two do not constrain each other at all, and ours will look
healthy in the log at the moment theirs runs out. Then ask where the count is spent: is the counter
incremented at *every* site that makes the peer count, or only at the one the fix was written for?
**Residuals (for Guido):** (1) `_session_stops` is incremented at exactly ONE site, and it is not
only the discretionary stop: it sits above the `stop_for_short` branch, so it counts the structural
stop (#461) and the peak EMERGENCY shed (`decide.py`, `bridgeable=False`) as well. Only the
WIDENING excludes those; the COUNT includes them, which is the right way round. What the count
misses is every session SEM ends from outside this filter — the #804 phase switch
(`ev_control`, `reason="phase switch: … (#804)"`), the conductor-protection stop
(`active_phase_guard._disable_decision`) and the VPP export pause (`vpp_dispatch`) are three
separate producers, and none of them spends the budget. Assuming the charge point counts those as
interruptions too — likely, and NOT verified against Zaptec's firmware — SEM's number is lower than
the box's, which is the wrong direction for a budget. These are demands that must not be delayed
(class 81(d)), so the answer is probably to *count* them without widening for them. (2) The budget is
brand-blind and the 4 is a module constant: the Go 2's real limit is not documented and not
configurable, so a charge point with a tighter one is still a report waiting to happen — and the
budget's own size was never fitted to a measured device limit, only to the churn. (3) Class
81(e) switches the anti-cycle floor off for a current-number-only surface on the premise that "a
0 A write is a pilot-signal pause, not a relay cycle" — true about the relay, false about the
SESSION, which is what this class counts; the budget now covers that surface at the stability
layer, but 81(e)'s own reasoning still reads as though a pause were free.
**Neighbour:** class 81 asked which thing a minimum interval limits, the repeat or the cycle; this
is the next question in that line — a limit on the cycle is still not a limit on the count.
Refs #975 #940 #893 #461 #552 #804.

### 113. A claim read back from disk outlives the mode that forbids making one — GUARDED
**Symptom:** removing a SEM that has Observer mode ON sends a real command to real hardware.
Guido's test install (#1027, v2.1.0) watched a KEBA that a second SEM controls; removal sent
`keba.enable` and put the box's failsafe back on its charging fallback. No car was plugged in, so
nothing happened that day. The log said `handed back on integration removed — keba.enable,
failsafe → charging fallback` for a lifetime that had never written to that box.
**Root shape:** #855 moved the observer gate DOWN to the single hardware seam: `send` withholds the
command and returns False. The layers above it were never taught to read that answer. Three of them
in one mechanism: (a) `park_off` read *"the call did not raise"* as *"the box was parked"* and wrote
the park debt to disk — on every disconnect edge, for a box it had never touched; (b) the next
setup ADOPTED that record, so a lifetime that commands nothing believed it had parked a wallbox;
(c) removal hands back every box SEM parked, and that gate saw the adopted flag and said yes. The
debt crosses lifetimes on purpose (#935: `PARK_OFF` fires on an edge, and an already-empty box at
boot is a steady state the reconciler cannot re-derive) — which is exactly why the adopter has to
ask whether THIS lifetime may command at all. Distinct from class 97, where the memory of a write
was a de-dup cache and the cost was a locked-out retry: here the memory is a DUTY, and paying it is
the first real command of the lifetime.
**Where it lives:** every claim SEM keeps across a restart, in any mode that promises to send
nothing. Already closed, and the precedent: the battery adapters (`unload_release_reason(adapter,
was_observer)` — *"observer commands nothing, including on the way out"*, #936), the export cut
(`export_release_recipes` and `async_release_export_guard`, #955), the charge pacer (#949, the only
one that closed BOTH ends — it never adopts, *"consuming the record of a real engagement is a side
effect, and an observer has none"*, and it re-adopts on the first commanding cycle). The charger
park was the one left. Assessed and NOT this class: the load boost (#914 `adopt_if_running`) — it
claims belief and ownership but never `_sem_commanded`, and every release path is gated on that
(#908), so an adopted load is left alone; `SwitchDevice.activate` is unreachable while observing
(`compute_load_intent` returns one layer up).
**Closure:** one rule, three doors, each asked separately — an observing lifetime TAKES no park
debt, ADOPTS none, and PAYS none. `_remember_parked` returns early in both directions (the record
belongs to the lifetime that really parked the box and is left as it is), `adopt_park_state` does
not claim, `release_to_user` writes nothing and keeps the record. `park_off` now takes the claim
FROM `send`'s return, not from the absence of an exception. Two gates are asked of the LIFETIME
rather than of the device, because a device learns its mode on a cycle and the documented default is
*"a device nobody told is a device that acts"*: the setup adopter, which runs before the first
cycle, and the unload stash, which decides whether a removal hands hardware back. That second one
reads a variable captured at the TOP of `async_unload_entry`, not the live flag:
`async_release_batteries_on_unload` sets observer mode ON part way down the same function (#936),
so a gate reading it live would answer "watching" for every install the day someone moved the block
— silently, with no log. Setup now tells every device its mode once, before anything can claim,
closing the window between setup and the first cycle. The record is not stranded:
`_readopt_on_leaving_observer` adopts it on the cycle the switch goes off, so a rig watched for an
hour does not then take control of a box it does not know is parked. What a watching REMOVAL leaves
behind is said rather than fixed (`_async_say_the_park_is_unpaid`): the box may be another SEM's, so
SEM must not touch it, but the record can still name a box an earlier commanding lifetime really
parked — and a removal deletes SEM's own files, so this is the last moment anything can say so.
**Guard:** `tests/test_1027_observer_takes_no_park_debt.py` — the three doors with a commanding
FLOOR beside each (a park IS recorded, a park IS adopted, a box IS handed back, or the observer
assertions pass on a device that simply cannot park); the store untouched through a whole watching
lifetime; the switch going off adopting once and a steady lifetime never re-reading. Two pins come
from mutation testing this change, because the first cut of the guard passed with either of them
reverted: `park_off`'s claim is asked the other way round — a send that goes nowhere while the
device believes it commands, so the gate one layer down cannot answer for it — and the production
hook wiring is pinned by `assigns_attribute`, since every behaviour test injects its own hook and
would stay green with the one real assignment deleted. Be honest about the third kind: the
`reads_flag` pins (which accept `getattr(self, "observer_mode", False)`, the house style for a flag
a bare stub may not have) are rename tripwires, not behavioural gates — they prove the door still
names the question, not that it acts on the answer. The behaviour tests are what prove that. The
unload ORDER has its own pin: the flag may be read exactly once in `async_unload_entry`.
**Sweep question:** for every fact SEM writes to disk and reads back in a later lifetime — who is
allowed to WRITE it, and does the reader ask whether this lifetime may act on it? A record is
evidence about the hardware; a mode is a rule about this process. Reading the first without asking
the second is how a watcher acquires a duty.
**Left for Guido:** (1) **The records the bug already wrote.** An observing rig booked a park on
every disconnect edge, so #1027's own install has bogus entries in `sem.parked.<entry>` right now.
Nothing in this change purges them, and nothing can tell a bogus one from a real one by reading it:
the cure is either provenance (a marker only a commanding lifetime writes, unmarked records dropped
once) or believing the entity (ask the box whether it is actually disabled — class 97's cure, and
what #935's docstring says the reconciler cannot do from the connect edge alone). A blanket purge
was deliberately NOT shipped: it would drop the legitimate records on every commanding install with
an EV to protect the few rigs, trading a rare wrong write for a rare stranded charger, and that is a
product call. The exposure is smaller than before this change, and different in kind: the bug needed
no switch flip at all, whereas what is left needs the switch OFF — and with it off SEM commands that
charger by definition, so a hand-back it never earned costs one `keba.enable` on a box it is
actively driving, not a command from a lifetime that promised to send nothing. The first charge
clears the record either way, through `start_session`. (2) `_export_guard_adopt`
still adopts a cut while observing and sets `_applied` — harmless today (every write below it is
gated, twice), and gating it naively would STRAND the cut when the switch goes off, since it only
ever runs on a lifetime's first tick. It wants the pacer's shape, not a gate. (3) `stop_session`
records the debt from `stop_method is not None` — which mechanism was CHOSEN, not whether it
landed. The `_remember_parked` gate covers the observer case, but a stop whose send fails for any
other reason still books a park, `_stopped_by_disable` still skips the 0 A write, and the "no
mechanism opened the contactor" warning is still suppressed. `park_off` was taught to read `send`'s
return; `stop_session`, three lines of the same shape, was not — the asymmetry is the thing to fix.
(4) `release_to_user` appends to its `did` list without reading `send`'s return, so its sentence is
only true because the observer door is shut in front of it — and it still reports
`failsafe → charging fallback` when `arm_failsafe_enabled=False` makes that call a no-op.
(5) `SEMCoordinator.__init__` resolves `config.get("observer_mode", False)` while
`DEFAULT_OBSERVER_MODE` and `PERSISTED_FLAG_DEFAULTS` both say True. `promote_persisted_flags`
(#777) closes this for every install that ever recorded the flag anywhere, so what is left is the
install where nobody ever said — which now boots "I act" and, since this change, tells every device
so. One word fixes it and the blast radius is an install that currently commands going quiet, which
is Guido's call, not a sweep.
Refs #1027 #935 #936 #949 #955 #855 #908 #914 #740.

### 114. A device judged alone when the device beside it is the evidence — GUARDED
**Symptom:** an Easee install with an Equalizer shows TWO chargers. The second is the Equalizer, a
grid meter, with the house's grid import as its charging power. Its entities come first in the
registry, so it is also the FIRST charger: the one zero-config setup SAVES into `ev_chargers`, the
config flow's first step suggests, and the late setup (`_retry_ev_device_setup`) builds and drives.
**Root shape:** the discovery walks map one unit at a time and ask each unit "are you a charger?"
alone. Most brand functions say yes to a power reading alone, so any meter an integration ships
beside its charger passes. The unit cannot answer the question by itself; its sibling can — the
same integration publishes car-present, charging, session and control roles for its chargers, and
the meter has none of them. A second walk asked a related question the same way: the report's near
miss checked "has this brand a charger?" against the chargers mapped SO FAR, so a site device listed
before its charger still read as "almost supported". And a wrong answer that setup SAVED is never
asked again: detection re-runs only while no charger is configured (the #886 shape).
**Where it lives:** every walk that turns registry units into chargers —
`discover_all_ev_chargers_from_registry` (and through it `discover_ev_charger_from_registry`, the
zero-config save in `async_setup_entry`, the config flow and the late setup) and
`build_detection_report`. Not the prober: it needs a plug or a current control, which a meter does
not have. The pre-fix walk admitted a meter beside a box on 17 of the 22 brand platforms.
**Closure:** `meters_beside_chargers`, asked by both walks after every unit of the platform is
mapped. A unit is a meter when its guarded mapping binds no role in `_CHARGER_ONLY_ROLES`, AND a
sibling unit binds one. Only a bound role makes a unit the evidence. No sibling, no drop: a box
whose status sensor is disabled keeps its only charger. Two things keep a unit the roles alone would
call a meter, each looked for on the WHOLE device, disabled entities included: a charger mark, or an
entity with the same translation key as one the evidence bound to a charger role. The review of this
fix found the second one: a second Easee with its status disabled, or renamed (the brand function
reads ids), mapped exactly like the Equalizer and was dropped. That check needs the keys, so where
the evidence's charger roles carry none, nothing is dropped: SEM cannot tell a meter from a box whose
roles are off, and the heal below acts on this answer (the second review). Transports (`mqtt`) are skipped:
devices on one transport are not neighbours. The report lists the meter under `meters`, and the
diagnostics download carries it. The near miss now waits for the whole platform (transports keep
the old per-device answer). `_drop_meters_saved_as_chargers` removes, at setup and before the
charger list is read, the one thing SEM itself saved wrong: a charger that binds no charger role,
whose power sensor is still the meter's, and whose id is the stable id setup gave that meter (or,
saved before v1.7.5, whose stored `_device_id` is the meter's). A list it empties sends the same
setup back to discovery. A side effect, pinned: the config path now reads the GUARDED mapping like the report,
so a unit whose only role a guard removed is no longer returned as a charger with no roles.
**Guard:** `tests/test_1036_meter_beside_charger.py` — the Equalizer's real entities, translation
keys and disabled flags, with the pre-fix rule spelled out; config path, primary pick and report,
in both registry orders; the "next to" pins (alone, a disabled status, two chargers, a second box
with its roles disabled or renamed, a live or disabled mark, a transport); an oracle that puts one
meter beside one box on every brand platform and must cover a literal list of 16 brands; an AST pin
that both walks call the helper; the near-miss order in both directions; the diagnostics download;
the no-keys case; the heal (SEM's save removed, a pre-v1.7.5 save removed, the user's charger, a
role or a power sensor the user set, and a real charger kept, no registry walk on a normal install,
and an AST pin that setup heals before it reads the list). Eighteen mutants are killed. No test runs
a whole `async_setup_entry` through the heal; the order pin and a trace stand in for it.
**Sweep question:** for every per-unit "is this an X?" — can the unit answer alone, or is the
answer in the unit next to it? And if the wrong answer was saved, what makes SEM ask again?
**Left for Guido:** (1) No evidence, no drop: an Equalizer beside an Easee whose status AND session
are both disabled or missing, an integration that gives its entities no translation keys, or an
Easee account with only an Equalizer, still offers the meter — first. (2) A meter whose entity ids hit a loose name rule binds a charger role and is kept: openWB
and V2C bind any id with `connect`, go-e MQTT any id with `car` (`carport`). (3) A second box that
maps to nothing (all its state sensors disabled) beside a detected charger is no longer a near miss
in either order; before, it was one only when listed first. (4) The report decides meters before the
roster can turn a sensors-only charger into a near miss, so the report can list a meter with no
charger row of that brand; the config path is not affected. (5) The Equalizer is a real grid meter;
offering it as SEM's grid source is a feature. (6) A Repair keyed by the removed charger's id is not
cleared — the same leftover the `remove_charger` service has.
Refs #1036 #886 #964 #915 #814.

### 115. A word in the device's name read as a word about the entity — GUARDED
**Symptom:** on Home Assistant's own Peblar test data (HA 2026.8.2) SEM bound
`switch.peblar_ev_charger_force_single_phase` as start/stop — it would switch the box to one phase
to "stop" a charge — and `sensor.peblar_ev_charger_power_phase_3`, one phase, as the charging power
(#1035). No error: both entities are real and of the right kind.
**Root shape:** Home Assistant builds an entity id from the DEVICE name and the entity's own name.
A brand rule that tests a word against the whole id therefore matches every entity of a device
whose name holds the word, and the loop's last (or first) match — registry order — decides. The
Peblar's default device name is "Peblar EV Charger": "charge" is in all 24 of its ids. "Charger",
"Chargepoint" and "Carport" are what owners call these boxes, so `charg`, `charge` and `car` — the
words half the rules ask for — sit in the device part. Not class 67: the word is a real word, it
just belongs to the device. The power half is class 89's second instance (one phase, below).
**Where it lives:** every hand-written brand function in `hardware_detection.py` (14), the hint
matcher `_discover_from_hints` (every `_BRAND_HINTS` row), `charger_from_near_miss`, and the #976
manual path `ocpp_charge_control_switch`. On a device named "EV Charger" or "Carport Charger" the
pre-fix rules bound a role-free entity (a child lock, an LED number, an "online" binary) on 11
platforms: Peblar, OCPP, ChargePoint, go-e (HTTP and both MQTT domains), Heidelberg, openWB (both
domains), V2C, Wallbox, Zaptec.
**Closure:** `_own_names` — each id without the device's words (`_device_words`): the leading
words every id of the unit carries, or, on a unit of eight or more ids, all but a quarter, so one
id its owner renamed does not switch the rule off for the device (the review of this fix found
that one rename brought #1035 back). A renamed id keeps its whole name. An id that is the device
name alone, or that plus HA's `_2`, is the device's MAIN entity and keeps the device name as its
own (GARO's start/stop is `switch.garo_laddbox`; a second box is `switch.garo_laddbox_2`). One
entity alone and the transports (`mqtt`, where the device name is the only mark of the brand) are
left whole. Every brand name test reads it. A control or a status that only the device name
matched is no longer bound; a measurand READ role is the exception (`_discover_unit`): left empty
by the own names, it keeps the whole-id answer unless another role holds that entity — class 89's
swap-only rule. So does the current control when HA itself says what it is: the unit's only
`number` of `device_class: current`. Ids are built in the install's language, so a German
Peblar's limit is `…_ladestrombegrenzung` and the device name was its only English word; without
this the second review found SEM set up no German or Dutch Peblar at all. The fallback only fills a charger the own names found: a unit that only its
device name made a charger (a Zaptec installation called "Carport Charger") stays out.
`_discover_ocpp` also skips the availability switch, as the #976 manual path already did, for the
installs where no device name can be seen. **Guard:** `tests/test_1035_own_name.py` — HA's own
Peblar entities in both orders, config path and report, with the old rule spelled out and with one
id renamed; GARO's main entity, its second box and a box named "Laddbox Garage"; an oracle that
gives every platform in `_EV_CHARGER_PLATFORMS` a device named "EV Charger" and "Carport Charger"
with role-free entities first and last; an AST check that no brand function tests anything
against `eid`/`eid_lower`/`entity_id` (plain, `str()`, `.lower()`), runs a regex over it or calls
`_name_hit(eid, …)`, and that it catches each of those shapes; the read-role fallback and its
limits, a German and a Dutch Peblar. Nineteen mutants of the fix are killed. **Sweep question:** for every word test over an
entity id — does it read the part the integration wrote for that entity, or the part the owner
wrote for the device?
**Left for Guido:** (1) a charger SAVED before this fix keeps its binding — detection re-runs only
while no charger is configured. A Peblar set up earlier keeps the single-phase switch; an OCPP
charge point left at the default name "charger" may hold `switch.charger_availability` as its
start/stop, which stops a charge by taking the connector out of service. (2) A unit whose own
names match no rule at all is no longer a charger: if openWB's loadpoint publishes German entity
names under an English "Chargepoint" device name, it matched only through "charg" before (with a
guessed status sensor) and is now left to the prober and the near-miss offer. (3) Peblar's state
sensor is `device_class: enum` and `_discover_peblar` asks for none, so no connected/charging
sensor is bound (a different shape). (4) The inverter-side `_DISCHARGE_CONTROL_PATTERNS` read whole
ids too, some by brand name on purpose. (5) The glob matrix (`EV_INTEGRATION_PATTERNS`) is a
config-flow prefill and was not changed. (6) An owner who renamed the TOTAL power sensor leaves
the phase leg bound: the sum is found by name. (7) Ids in other languages: a German or Dutch
Peblar gets no start/stop (its switch is not called "charge"; before, it got the single-phase
switch), and a phase named `fase_3`/`fas_3` is not seen as one phase. Reading Peblar's unique-id
keys (`…_charge`, `…_power_total`) would fix both — brand code, so not here. (8) Seen on HA's own
entity names, older than this class: Wallbox binds `…_maximum_icp_current`, the site's grid limit,
as its current control; V2C was #1034 (classes 56 and 89, closed). Class 114's residual (2) loses its `carport` case:
go-e MQTT's `car` now reads the own name.
**Second instance — the runtime, not the setup (#976, 02.10):** `charger_adapters/wallbox.py::_looks_like_wallbox` chose the ADAPTER by `"wallbox" in entity_id`. "Wallbox" is what German owners call any wall charger; @bgthb's Huawei on OCPP is a charge point named "wallbox", so its `switch.wallbox_charge_control` made it a Wallbox. That adapter turns its pause switch on before every current write; on OCPP that turn_on is a RemoteStartTransaction, so every write sent a start the charging box refused ("Rejected", one notification each). Alfen (`alfen_wallbox`) and GARO (`garo_wallbox`) carry the word too. Closure: the adapter asks the registry PLATFORM (or the service domain), never the id. Guard: `tests/test_976_named_wallbox.py` — the reporter's charger through the reconciler, every other charger platform under a device named "wallbox", a Wallbox renamed "Garage", and an AST check that no module in `charger_adapters/` tests a brand word with `in` (a literal word only; `any(…)`, `.find()` or a regex would pass it). Left for Guido: `_looks_like_wallbox` and `_discover_pause_switch` read `charger_current_entity`, a name the real device does not have (it is `current_entity_id`), so a Wallbox configured with its current number alone still gets the generic adapter — unchanged here on purpose, since the Wallbox adapter then turns the pause switch on (a cloud call) before every write. Outside the charger path: `features/load_device_discovery.py` (keba / go-e / easee in ids), `utils/helpers.py` ("keba" picks kW), `coordinator/repair_issues.py` ("keba" + "failsafe"). Decided here: Wallbox hardware behind another integration (the MQTT bridge of #984/#985, Modbus) now runs the generic adapter. With its start/stop switch configured, `stop_session` turns it off on every stop and ENABLE turns it on when off; the Wallbox adapter only added a turn_on before every write.
Refs #1035 #962 #976 #804 #1036.

### 116. A select written with the label a person sees, not the option it lists — PARTIAL
**Symptom:** on Home Assistant's own Ohme test data (HA 2026.8.2) SEM set the charge mode to
"Max charge" and "Paused"; the select lists `max_charge` and `paused`, so HA refused every write
and the charger never changed mode (#1039). Nothing else looks wrong: the entity is right, the
call is made, and the error is one log line per start or stop.
**Root shape:** HA's `select.select_option` takes an option exactly as the entity lists it in its
`options` attribute. What the UI shows is the option's LABEL, translated through the
integration's `translation_key`. A string typed from the UI — by a developer into a brand rule, or
by a user into a config field — is the label, and the select refuses it. A compare against the
select's state fails the same way, so a read-back waits for a value the select can never read.
**Where it lives:** every select SEM writes: the charger's charge-mode start/stop, the hand-back
and the amps-as-select current (all through `ControllableDevice.send`); the phase-switch select
(`ev_phases.phase_switch_command`, `hass` now required); the battery direction select
(`_direction_ready`) and power-strategy select (`GenericBatteryAdapter`, write and every compare);
SG-Ready select contacts (`_contact_service`, `_contact_is_on`); the `set_option` service on SEM's
own selects; the detection card's strategy check (`_gate_proposal`), which must judge a value as
the runtime writes it. NOT closed: GoodWe forced charge and Deye's `_write_and_verify` (below).
**Closure:** `utils/select_option.listed_option(hass, entity_id, value)` — a value the select lists
is kept; otherwise the ONE listed option whose label (HA's translation cache: the user's language,
then English) or whose own spelling is the same words; otherwise the value unchanged, for HA to
refuse with its own error. "The same words" ignores case and treats a space, `_` or `-` between two
letters or digits as one separator, nothing else; a `-` before a digit is a sign: `-5` is not `5`,
`Offset -1` and `Offset - 1` are not `Offset 1`, `Solar+` is not `Solar`. A looser match would turn a refused write
into an accepted one with another meaning. Never a guess between two. The charger seam maps every
select write, so observer mode records the option it would really send. Ohme detection now saves
`max_charge`/`paused`; a config saved with the labels is mapped at write time, so it needs no
migration.
**Guard:** `tests/test_1039_listed_option.py` — a fake HA whose selects refuse unlisted options,
for Ohme (start, stop, hand-back, observer, through the reconciler), the direction and strategy
selects, SG-Ready, the phase switch and the card's check; real HA labels from core's GoodWe
translations in German and English; signs and symbols that must not match; an AST check that
every `select_option` in the package is in a function that calls `listed_option`, goes through the
charger seam, or is on a short list with its reason, and a second one for every function that
writes through the `CONTACT_VALUE_SERVICES` table.
The read side is the same shape: an ENUM sensor's state is the option key too, so a word list
typed from the UI never matches it (#1038: Ohme `plugged_in`, Peblar `no_ev_connected`).
**Sweep question:** where SEM writes or compares a string against an entity with a fixed list —
did the string come from that list, or from what a person saw? And before mapping one: what
happens on the hardware once a write that was always refused starts to LAND?
**Left for Guido:** (1) GoodWe forced charge (`GoodWeChargeAdapter`) writes "Eco Charge" and
"General"; core lists `general`, `eco`, `peak_shaving`, … and — built without the library's
emulated modes — no `eco_charge` at all, so forced charge cannot work on core this way. The start
call is not blocking, so SEM reports CHARGING anyway (class 97). Mapping was tried and pulled in
review: a `general` that lands moves a user's eco or peak shaving on every restart, and handing
back `eco` leaves the library's 24/7 charge slot active. Needs a GoodWe design. (2) Deye's
`_write_and_verify` is not mapped: the force paths check each option against the list first, but
`command_stop_force_discharge`, `command_limit_export` and `command_release_export` do not, and
their "nothing to do" checks compare the raw config value, so a mapped write would land on every
cycle. Older and a different shape: the two export paths compare the HA State OBJECT with an option
string, so the prior mode is never saved and the release restores nothing — a Deye cut to Zero
Export To Load stays there. (3) OpenWB detection saves "Instant Charging"/"Stop" and go-e "2"/"1";
not checked against their integrations' options — the mapping covers a label either way. (4) The
config flow's start/stop fields are free text; a dropdown of the chosen select's options would stop
a wrong value at entry. (5) Class 97, older: `_direction_ready` never re-sends a write that did not
fail but did not land. (6) Older and separate: both charger builders (`__init__` setup and
`_retry_ev_device_setup`) skip a charger with no current control and no charger service, and a
stock Ohme has only the mode select — so SEM builds no device for it and #1039's write is reached
only on an Ohme the user gave a current entity or service. Supporting a start/stop-only charger is
a feature. (7) Once it is built: the hand-back (`release_to_user`) writes the START mode, which for
Ohme is `max_charge` — a full-power charge over the user's `smart_charge` — and with no current
entity an IDLE decision after a restart cannot stop a box left in `max_charge`.
Refs #1039 #1032 #955 #1038.

### 117. A start sent to a session the box already runs — PARTIAL
**Symptom:** when SEM started a session the charger had already started itself (or from its app), the OCPP integration posted "Start transaction failed with response Rejected" (#976, 02.10) — one per session start. Charging went on. (The flood in the same report, one per current write, was class 115.)
**Root shape:** `start_session` turned the start/stop switch on without reading it, on the belief that a switch's turn_on is idempotent. On OCPP it is not: `charge_control` is on while a transaction runs, and its turn_on is a NEW RemoteStartTransaction, which the box refuses. The reconciler's #536 ENABLE already read the switch first; the session start did not.
**Where it lives:** `CurrentControlDevice.start_session` (the start/stop-entity branch) and `release_to_user` (same branch, on removal). `ensure_enabled` is only reached when the switch reads off. A `button.` start cannot be read and is unchanged (#804).
**Closure:** `_start_switch_reads_running()` (was `_reads_on`) — a definite running state (`on`; `off` on a pause of the charge, class 118) from a switch without `assumed_state` means the session runs: no start, the session is claimed. Unreadable or optimistic still sends.
**Guard:** `tests/test_976_named_wallbox.py::TestNoStartIntoARunningSession` plus the end-to-end run through the reconciler. **Sweep question:** before SEM repeats a command it calls safe to repeat — what does the device do when it gets it twice?
**Left for Guido:** (1) the #536 ENABLE fires on `off`, which on OCPP is also a box that REFUSES a start (Finishing after SEM's own RemoteStop, Preparing while it waits for authorisation): 5 refused starts, then one per 300 s — about 12 notices an hour while SEM wants to charge. Tied to the open question whether a RemoteStop is the right OCPP pause. (2) `WallboxAdapter.command_current` / `command_max` still turn the pause switch on before every write (a cloud resume call per write on a real Wallbox), and `command_idle` / `command_disable` turn it off a second time after `stop_session` did (the #894 shape). (3) ~~`_discover_v2c` adopts V2C's `paused` switch as start/stop, where on means paused~~ — closed by class 118 (#1042): the "already on" read is now "already running", which is `off` on that switch.
Refs #976 #536 #804.

### 118. A switch read by its state, not by what its name says "on" means — GUARDED
**Symptom:** V2C Trydan: on a box given its session pause as start/stop, every start SEM sent paused it and every stop resumed it (#1042); on one given the modulation pause (below), SEM's stop never stopped the charge. Home Assistant's V2C session switch is "Pause session" (key `paused`), on while paused; core's `turn_on` calls `evse.pause()`. Nothing errors: the switch takes each command.
**Root shape:** every start/stop write spelled `turn_on` to start and `turn_off` to stop, and every read took `on` as running. That holds for a switch named for the charge ("Charging enabled", "Charge control", Wallbox's "Pause/resume", on while it charges), not for one named for the pause. Second shape in the same rule: `_discover_v2c` took the LAST switch with "pause" in its name, and HA registers "Pause dynamic control modulation" (key `pause_dynamic`, which pauses the box's solar modulation, not the charge) after the session pause — so the old rule most likely saved that one on every V2C.
**Where it lives:** `CurrentControlDevice.start_session`, `stop_session`, `park_off`, `release_to_user`, `_start_switch_reads_running` (was `_start_switch_reads_on`); `ChargerAdapter.enable_state`, `ensure_enabled`; `WallboxAdapter._toggle_pause_switch`; `_discover_v2c`; the saved bindings no detection fix reaches.
**Closure:** one rule, `consts/devices.names_a_charge_pause`: "pause"/"paused" as a whole word and no word but session/charge/charger/charging/ev/evse/car — so `pause_resume`, `pause_dynamic`, `not_paused` and a device name in front are not one. `utils/switch_sense.on_means_paused` applies it to the name the INTEGRATION gave the switch: HA's translation key (the same in every language; a German V2C's id says `vorgang_pausieren`, its key `paused`), else `original_name` when `has_entity_name` says it is the entity's own. A template switch or helper the owner made keeps "on = start". Every write asks `switch_service(run=…)`, every read `reads_running`; the sense is read at run time, so no saved config changes. `_discover_v2c` binds on the same name by the same rule (`_pauses_the_charge`), so a switch the run time cannot read is not bound and the #627 Repair says so. The builders' `wire_current_entity` swaps a saved switch that pauses something else (`names_another_pause`, never a pause/resume toggle) for the one pause of the charge on the same device (`charge_pause_twin`; keys only, no guess between two) and logs it. The diagnostics dump shows `start_stop_on_means_paused`.
**Guard:** `tests/test_1042_pause_switch.py` — a fake Trydan whose switch pauses on `turn_on`, through start, stop, park, hand-back, the adapter and the reconciler; Wallbox, NRGkick and OCPP switches and an owner's template unchanged; detection over every order of HA's five V2C switches, German ids, rows without keys, and the old rule run on the same rows; the saved modulation pause swapped, and kept when there is no twin, two, or only one on another device; an AST check that no function naming the start/stop switch (attribute, variable, parameter, or the config key fetched) spells `turn_on`/`turn_off`/`on`/`off`/`STATE_ON`/`SERVICE_TURN_ON` itself, which catches the pre-fix shapes. Thirteen mutants of the fix are killed. **Sweep question:** when SEM writes on or off to a switch, does the switch's name say on is the thing SEM wants?
**Left for Guido:** (1) the swap is at run time; the saved config still names the modulation pause, and the config screen shows it. (2) An integration with no translation key and no own name, or one whose names are not English (`…_pausieren`), is read as on-while-charging. (3) OpenEVSE's "Sleep mode" switch is on while stopped too, under a word that is not "pause"; SEM does not detect it as start/stop. (4) The Repair text "enable switch will not stay on" is wrong in words for a pause switch (it will not stay off). (5) Load switches (`features/load_management.py`) are not read through this rule. (6) A V2C healed by the swap may still have its modulation paused from SEM's old "start"; SEM no longer touches that switch, also not on removal. (7) No test pins that the builders set the saved start/stop before `wire_current_entity` (the Wattpilot wiring relies on the same order). (8) The AST guard misses a switch passed to a helper under another name, a fetch through a call other than `.get`, and the `toggle` service.
Refs #1042 #976 #1034 #1035.

### 119. A ratio whose top counts part of what its bottom counts — GUARDED
**Symptom:** `sensor.sem_battery_measured_capacity_kwh` read 7.89 kWh on a 10 kWh pack, drift −21.1 % over 33 nights (#1045). The pack was fine. Nothing errors; the figure looks like wear.
**Root shape:** kWh per percent is energy over SOC span. The SOC span counts everything that left the pack (house, car, grid) and is net of any charge taken in the same night. The energy was `drain_kwh`, the house's share only, and gross. A night with EV assist or battery export read LOW; a night that also charged read HIGH, which sizes every budget against a pack that is not there. Each side is right for its own reader: `drain_kwh` is exactly what the overnight need wants.
**Where it lives:** `measured_capacity._qualifying_ratios` (the instance); `battery_night.BatteryNightTracker` (now records `charge_kwh`, including a charge seen only as an SOC rise across a restart hole; a hole that ends after dawn now ends the SOC span too, where before its energy joined the night and its SOC did not); `night_backfill` records carry no SOC, so they never reach the ratio. Any other "energy per percent" figure: `ev_taper_detector.on_session_end` (left below).
**Closure:** the energy is drain + assist + export − charge, the same flows the span counts. A night whose charge is more than 10 % of what left (`MAX_NIGHT_CHARGE_SHARE`, with a 0.25 kWh noise floor) is not used: its net is a small difference of two lossy conversions. A record sealed before the charge was counted (`charge_kwh` absent or None, also the night in flight at upgrade) does not know its charge: it is read as before, house share only, and not used when assist + export are more than 10 % of what left. `expected_overnight_need` keeps the house's share.
**Guard:** `tests/test_1045_capacity_counts_every_outflow.py` — assist, export, both, EV-only and mostly-assist nights read the real pack; a small charge and short-night noise are subtracted, a large charge refuses the night; old-format records with and without assist, including an export night that charged back; a charge hidden in a restart hole; a hole that ends after dawn; noise larger than a tiny night; a night restored from an old store says unknown; the need is pinned to the house's share; real nights through the real recorder into the real reader; the coordinator hands the pack's charge power to the recorder. Thirteen mutants of the fix are killed.
**Sweep question:** for every ratio SEM computes, does the top count the same flows, over the same window, as the bottom?
**Left for Guido:** (1) `ev_taper_detector.on_session_end`, display-only (per-charger `battery_health`): the full-cycle method sets the estimate to the session's energy for any session that tapers to full, so a 50→100 % session reports half the pack; the partial-cycle method takes `_session_start_soc` from the first SOC reading after the last reset, and `get_virtual_soc` runs while the car is away, so the SOC side can start at unplug while the energy side starts at plug-in; it also divides wall (AC) energy by the car's SOC, about 10 % high. Not verified on a live install. (2) Energy and charge bridged across a restart hole are made from the configured nameplate, so a wrong nameplate skews that night's ratio. (3) The budget uses a measured size above the nameplate as is; a pack does not grow, so a cap at the nameplate would be a second guard. A product call. (4) Switch-over: an old record's charge is unknown. Old nights that drained and then took a grid top-up read high, on develop too; old assist nights used to read low and could hide them, and are now skipped. Until new nights fill the window, an install with many night top-ups can read higher than develop did (review: 15 vs 10 kWh in one mix). Not using old records at all removes that, but resets every install's figure for five nights and needs the old-shape fixtures in 15 tests changed.
Refs #1045 #778 #800.

**Round 2 (#1046) — a flow over a meter, and over another day.** The EV card's daily "Solar Share" (`energy_ev_solar_percentage`) read 49 % on PROD for a day the session record called 89 % (6.3 kWh). It was `solar_to_ev` (a flow) over `daily_ev` (the charger's metered kWh). The flow allocator leaves a cycle's draw unassigned when the inverter reads dark, so the meter counts cycles no flow does. #1024 had fixed the session record (it scales the flow split to the meter); the day's share was a second reader that never asked. The window was off too: `daily_ev` rolls at the Charge-by time (default 07:00; midnight when chargers disagree), the flow layer's totals at midnight. The first cut took the split of the calendar flows; review caught that a night charge on grid then pulls the share down until midnight (31 % beside "Today 5 kWh" all on sun).
**Where it lives:** `EnergyAssistant.analyze` (the instance), the "mostly from grid" tip and the optimization score (same ratio, **swept**), the battery charge session's `solar_share_pct` — `solar_to_battery` over the measured charge (**swept**), and the battery card's "% solar" under "Charge today" — `flow_solar_to_battery_energy` over `daily_battery_charge_energy` (**swept**, `sem-battery-card.js`). Already right: the EV session and the lifetime shares (totals scaled from the same split), the card's month totals (weighted by those sessions), autarky (flows over flows), `_file_battery_charge_origin` and the discharge savings (flow split onto the increment).
**Closure:** `utils.helpers.solar_share_pct(solar, *others)` and its card twin `util/solar-share.js` — solar over the sum of the flows into the same thing; None when they hold nothing (the sensor reads 0 as before, the tip does not fire, the score gives no EV points). The car's flows are also kept on the EV day: `EnergyCalculator` books `solar_to_ev`/`grid_to_ev`/`battery_to_ev` into daily rows keyed by the same `ev_day` as `daily_ev` (`ev_flow_*`; the `ev_` prefix keeps them through the midnight sweep; persisted with the daily rows), and `ev_day_flows()` reads them on the key `daily_ev` was read from this cycle. The EV day the rows were first booked on began before them, so `ev_day_flows()` says None for it (`ev_flow_since`, persisted in `CALCULATOR_STATE_KEYS`) and the coordinator reads the calendar flows for that one day instead of 0 % (review 2). `battery_to_ev` now reaches the assistant, so a battery-fed car is not read as all solar.
**Guard:** `tests/test_1046_ev_daily_solar_share.py` — the PROD shape (sun, dark, grid) through the real allocator, integrator and `session_energy.step`: the card equals the session (88.2 %, was 47.6 %); a night (battery at 23:30, grid at 02:00) then a day (sun, then dark) through the real `EnergyCalculator`: the night's rows survive midnight, the day reads 100 % (calendar split 45 %, old 50 %), the rows survive a restart; a read after 07:00 keeps the day `daily_ev` was read on; the upgrade day says None and the marker survives a restart; the real cycle publishes the EV day's split, and on the upgrade day the calendar split; the tip and score on the same split; the battery session through the real allocator (75 %, was 42.9 %; a dark cycle keeps the share). An AST lint over the package: a `/` or `/=` with solar on top and a metered total below (`daily_ev`, `ev_kwh`, `energy_kwh`, `total`, `charge`, `metered`) fails unless the function is on a three-entry list whose totals are themselves the scaled split, each pinned to one such division. It cannot see a value renamed first, or a multiply by a reciprocal. `dashboard/card/test/solar-share.test.js` pins the card helper; a line lint over `dashboard/card/src` fails on `solar… / …daily|charge|total…` (shown to catch the old battery card line).
**Left for Guido:** (1) The battery session's `energy_kwh` and `cost` still use the measured charge and the unscaled grid flow; only its share changed. (2) The battery card's share is still the calendar day; so is `daily_battery_charge_energy` beside it, so the window matches. (3) Per-charger daily share does not exist; a multi-charger card shows the fleet share on each tile. (4) On the upgrade day the share is the calendar split (round 1's number), so a night charge before the Charge-by time still counts in it that day.
Refs #1046 #1024.

### 120. A part taken away from a whole that never held it — who is inside the total, decided by each reader — GUARDED
**Symptom:** `sensor.sem_daily_true_baseload_energy` read −49.69 kWh against 6.29 kWh of home after a 49 kWh night charge, and `true_baseload_power` fell by the charging power while the car charged (#1044, RienduPre, 2.1, Growatt + Wallbox Pulsar). Nothing errors; the number is negative by the size of the car.
**Root shape:** `home` is solar + import + discharge − ev − export − charge, so the car is already out of it. SEM's chargers are also devices in the surplus controller, and the baseload took away every device in it — the car a second time. #872 had hit the same rule for the partition check and fixed it there alone, by device TYPE (`current_control`); the baseload (#773) was a second reader that never asked. The type rule was also wrong: a load the user put under current control is a `CurrentControlDevice` too, and its draw is not in `ev`.
**Where it lives:** every reader that adds devices up against `home`: the filing seam's controlled-loads mirror (`_file_device_energy`, the instance), the W twin in the cycle (the instance), `home_member_totals` for the partition check (#872, **swept** — so a current-controlled load is a member again), and the baseload drift check, which named a charger as the day's suspect and judged days sealed under the old rule (**swept**).
**Closure:** the sensor reader says what `ev_power` was read from (`PowerReadings.ev_power_entities`, the per-charger sensors summed, or `ev_power_fleet_entity`, one fleet sensor that stands for every charger). `health_check.chargers_outside_home` keeps SEM's chargers (`sem_ev_chargers`: the dict and the late-found `_ev_device`) that this read covers; `home_members(devices, chargers)` leaves exactly those out, by identity. A charger the reader never read — a second box with no sensor of its own, a late-found box whose sensor was not handed over — is still inside `home` and is still taken away once (the review's catch: identity alone would have left its car inside the baseload). The charger keeps its ledger row. A sealed day carries `home_members_only` when its whole day was booked under the rule (`_home_members_since`, persisted and in `CALCULATOR_STATE_KEYS`; the upgrade day is not). On an install with a charger outside `home`, a day without it is a gap, and such a charger is never named as the mover.
**Guard:** `tests/test_1044_ev_not_subtracted_twice.py` — real `CurrentControlDevice` chargers and a current-controlled load through the real seam into a real calculator (his day, the late-found shape, a charger never read, an estimated charger), the real cycle with a charger drawing 7 kW for the W twin (through the fleet sensor and through the per-charger sum), each with a twin that shows the old number; the reader's record of what it summed; the drift check's suspect and gaps; the stamp across an upgrade, a restart and junk; AST checks that every coordinator function that books the mirror, writes the W twin or calls `home_member_totals` asks both `chargers_outside_home` and `home_members`, and that every `readings.ev_power` write in `sensor_reader` says what it read. Eleven mutants of the fix are killed.
**Sweep question:** for every total SEM takes something away from, does the total hold the thing taken away? And is that decided in one place?
**Left for Guido:** (1) the late-found charger (`_retry_ev_device_setup`) does not hand its power sensor to the sensor reader (`key_map` maps plug, charging and total energy only), so without a fleet sensor `ev_power` misses its draw and the car counts as house load everywhere, not only here. Not checked on a live install. (2) The upgrade day keeps the old number until midnight: the mirror already holds the kWh the charger booked that morning. (3) A downgrade and a later re-upgrade keep the old start day, so the re-upgrade day is sealed clean. (4) While a late-found charger is not yet registered, or after a charger is removed, old days count again and can raise one false drift warning. (5) The "dict plus `_ev_device`" walk is still written out in four other places in `coordinator.py`. (6) The rule asks what `ev_power` read; the daily home row, when it follows the meters, takes out the calendar-day EV row, which EV energy counters can raise. A charger whose counter is in that list but whose power `ev_power` does not read (case 1, or an Energy Dashboard EV device with no power sensor) is then out of daily home and still booked in the mirror: the kWh baseload can go negative again there. The counter model itself says it assumes `ev_power` already holds every charger (`configure_ev_counters`); (1) is the real fix. (7) The Energy Dashboard fleet sensor is the first device whose name looks like a charger (`_extract_ev_from_devices`); it is taken to stand for every charger.
Refs #1044 #872 #773 #1045.

### 121. A word made for the code, shown to a person — PARTIAL
**Symptom:** a Dutch dashboard read "Netmodus: manual", "Netteken (auto): normal", "custom · Normaal", "normal · 2", "2 (number)", a chart legend "actual", and "ev_charger_1" / "battery" as names in the energy plan (#1053, RienduPre, 2.2.0-beta.10). Nothing errors; the user cannot tell what the word means and cannot find it in the translation file, because it is not there.
**Root shape:** a sensor publishes a closed set of words SEM chose for its own code, and a card puts the state on screen as it is. Where a card did map the words, the map was written once and the backend grew: the System card knew `combined` and `split`, then #461 added `manual` and #947 three `split-*` words, and those printed raw. A demand id (`ev:<charger id>`) is the same shape: the card printed the part after the colon as the name.
**Where it lives:** `sem-system-card.js` (grid mode in the header and the info row, charger control, the English "solar" in the health header), `sem-control-card.js` (grid sign, heat pump mode and the SG-Ready number in the header, tariff source, load-management status), `sem-config-card.js` (tariff source, heat pump mode, grid and battery sign, load-management status), `sem-grid-card.js` and `sem-load-priority-card.js` (load-management status), `sem-chart-card.js` (the forecast preset's `actual` series and title key), `sem-energy-plan-card.js` (not-scheduled rows, last night's review rows, tomorrow's asks). All **swept**.
**Closure:** `dashboard/card/src/util/state-label.js` — one table per sensor (backend word → translation key; tariff brands by name), read through one method, `_valLabel()` in `sem-lit-base.js`. A word with no row is shown as it is, never blank. The energy plan: `coordinator/demand_labels.py` gives each charger row and each review row the name the user gave (`ev_not_scheduled`, `labelled_review`, looked up when published); the card's `_demandName()` (`util/demand-name.js`) falls back to the demand's kind in the user's language, never the id; tomorrow's asks send no name rather than the device id or the English "EV". Nine new keys in all 16 languages.
**Guard:** `tests/test_1053_machine_words.py` — reads each word from the code that writes it (`publish_diag` by AST, `SGReadyState`, `LoadManagementState`, every `_provider_name`/`provider=` in `tariff/`, `format_battery_sign_diag` run on four shapes, the dataclass defaults) and fails when the card table has no row for it or a row's key is missing in a language (a value the scan cannot read, such as a variable, fails too); a line lint fails on `_val('<one of these sensors>')` in any card outside the copied support text; every chart preset word is a key; the plan card never splits an id; the real planner, the real publish step and tomorrow's asks carry names. `dashboard/card/test/state-label.test.js` and `demand-name.test.js` pin the two helpers. Five mutants of the fix are killed.
**Sweep question:** for every sensor state a card shows — is it a number, a name a person gave, or a word SEM made? If SEM made it, which table translates it, and who adds the row when the backend adds a word?
**Left for Guido:** (1) the heat pump and hot water are named in English by SEM ("Heat Pump", "Hot Water", `heat_pump_name` has no setting), and the name reaches the Today plan, the load list and the flow tiles — the #587 decision on SEM's own device names. (2) The System card's collapsed Diagnose block is English prose with raw states (`charging_state`, `grid_status`); it is support text, so it was left. (3) The lint sees `_val`/`_valStr`/`_valNum` reads only; a card that reads `hass.states[...]` of one of these sensors directly is not seen. (4) The charger default name "EV Charger" (config flow) is English too. (5) Not seen live: a saved battery id `__fleet__` would show in the battery sign as it is (`format_battery_sign_diag`).
Refs #1053 #461 #947 #744 #587.

### 122. A setting published through a part that can be off — with it off, the sensor shows the built-in default — GUARDED
**Symptom:** the Control tab read "5.00 kW" while the install was set to no grid limit, and any number the user saved went back to 5 kW after a page refresh (#1055, lostcontrol, Fronius, no charger, load management off). The Config tab showed the saved value; the EV sizing used the saved value. Only the sensor was wrong.
**Root shape:** the grid limit is a setting, but `_build_load_management_data` copied it from the load manager only. With load management off there is no load manager (#897), so the `LoadManagementData` defaults (5.0 kW, limited) went out on `sensor.sem_target_peak_limit` as if the user had chosen them. `_get_peak_limit_w` had its own fallback to the saved option, so what SEM showed and what SEM did were two different limits.
**Where it lives:** `_build_load_management_data` — `target_peak_limit`, `peak_limit_unlimited`, and the two numbers made from them, `peak_margin` and `current_vs_peak_percentage` (**swept**; with no limit the percent is 0, not a percent of the saved number). Cards that print the limit, a percent of it or a margin and skip the "no limit" flag: the Control-tab header, the Control card's peak section and the Home card (**swept**); the load list card was already right. The diagnostics now carry the flag. "Uncapped" was English in 12 languages (**translated**).
**Closure:** one reader, `ev_control._target_peak_limit_kw()` (load manager first, then the saved option; a saved value that is not a number keeps the default limit) with `_peak_limit_unlimited()`, used by both the EV sizing and the publish. Cards ask `util/peak-slot.js::isUncapped` and print the limit through `peakLimitText`.
**Guard:** `tests/test_1055_peak_limit_published.py` — with load management off, the saved limit, the saved "no limit" and a slider write reach the published data; zero config gives the defaults; a bad saved value keeps a limit; no limit reads 0 %; a live load manager still wins; a test that the published limit equals the limit the EV sizing uses, with and without a load manager; an AST check that the builder reads neither key from the load manager's dict. `dashboard/card/test/peak-limit-text.test.js` pins the card helpers and that the three cards use them.
**Sweep question:** for every value a sensor publishes — is it a setting or a measurement? If a setting, is it read from where it is saved, or only through a part the user can turn off?
**Left for Guido:** (1) the 15-minute slot guard (`_compute_peak_slot_allowance`) reads the limit from the load manager only, so with load management off there is no slot guard while the EV sizing still keeps the limit — a control change, not a display fix. (2) `consecutive_peak_15min` and `monthly_consecutive_peak` are measured by the load manager only; with it off they read 0.0, not "unknown". (3) `sem-grid-card.js` (not on the default dashboard) prints the limit, margin and peaks — all kW sensors — through `semFormatPower`, which takes watts, so 5 kW shows as "5 W"; it also skips the "no limit" flag. (4) `dashboard/basic_template.yaml` prints the bare number too; it is used only when the main template is missing.
Refs #1055 #716 #897 #913.

### 123. A part built once, freed when the card leaves the page — HA puts the same card back — GUARDED
**Symptom:** the Energy tab drew both charts on the first visit. Go to another tab and come back: both were empty until a page reload (#1058, lostcontrol, 2.2.0-beta.11, video). Nothing in the log. Every SEM chart (Home, Battery, EV, Costs) had the same fault.
**Root shape:** Home Assistant keeps each view it has shown. Leaving a tab takes its cards off the page (`disconnectedCallback`); coming back puts the SAME card objects back (`connectedCallback`). Lit runs `firstUpdated()` once per object, does not render a card that comes back, and hass does not change if nothing changed while you were away. The chart card destroyed its Chart.js chart in `disconnectedCallback` and drew it again only when the period changed, the app came back to the front, or a 5-minute timer fired — so the canvas stayed empty. Its 5-minute roll also missed the power, battery and forecast charts: it worked out the opening window with its own rule, read them as "this week", and never moved them to now.
**Where it lives:** `sem-chart-card.js` (the chart; the instance), `sem-flow-card.js` (size and visibility watchers, the app-resume listener), `sem-system-diagram-card.js` (size and visibility watchers, a number count stopped half way), `sem-title-card.js` (a template subtitle stopped following its template; an answer that came after the card left was not dropped), `sem-ev-status-card.js` (the pause countdown is started in `updated()`, which did not run on return), `sem-config-card.js` and `sem-diagnose-button.js` (a ✓ or "Copied" whose clear-timer stopped on leave stayed on screen). All **swept**. Checked and right: `sem-price-card`, `sem-weather-card`, `sem-tab-header` (built in `connectedCallback`), the load list's drag listeners (end with the drag).
**Closure:** `SEMLitBase.connectedCallback()` asks for a render when `this.hasUpdated` (the card is back, not new), so `updated()` runs on every return. Each card builds again in `connectedCallback()`: the chart card's `_redraw()` whenever it has a window (its own window moved to now, a range the user picked kept), `_observe()` in the flow card and the diagram (not when the first update runs off the page), `_subscribeTemplate()` in the title card (only while on the page; a late answer is closed or dropped). A chart fetch that answers after the card left, or after a newer fetch, draws nothing (`_fetchSeq`). One `_defaultKey()` answers "which window does this card open on" for opening and for the roll, so the power, battery and forecast charts now move to now every 5 minutes, like the others.
**Guard:** `dashboard/card/test/reconnect.test.js` — (1) the real card code with a stub in place of Lit that runs Lit's update order, driven through leave-and-return: both chart presets fetch and draw again, the window ends now, a picked range is kept, a late answer draws nothing, a card off the page asks for no data, the roll moves the power chart to now, every card renders again, the EV countdown restarts, the ✓ and "Copied" clear, the flow and diagram watchers come back (and none start off the page), the title card subscribes again, opens nothing off the page and drops late answers; (2) a source check over every card: what `disconnectedCallback()` frees (`.disconnect()`, `.destroy()`, `clearInterval`, a removed listener, an unsubscribe) must be built in `connectedCallback()`, in `updated()` (cards on `SEMLitBase` only), or in a method they call — not from `setInterval` or a stored listener; a card whose `disconnectedCallback()` it cannot read fails it. Red on the old cards; 18 mutants of the fix fail it. Seen in a real browser with the built bundle: the old one leaves the canvas empty on return. `tests/test_1058_card_reconnect.py` checks the bundle was rebuilt.
**Sweep question:** for every part a card builds — a chart, a watcher, a timer, a subscription — what builds it again when HA puts the same card back on the page?
**Left for Guido:** (1) a range picked in the period selector (Costs tab) is worked out once, at the click; on return, and while you stay, the chart shows that window, so "Today" picked yesterday still shows yesterday. A fix moves the selector's period maths into one helper the chart can roll. (2) Redrawing rebuilds the chart: a series hidden in the legend shows again and a hover tooltip drops (now every 5 minutes for power, battery and forecast too). `chart.update()` in place would keep them. (3) The source check knows the ways cards free a part today; it does not see `clearTimeout`, `cancelAnimationFrame` or observers held in a list, and it counts a call inside a `setTimeout` or `.then` as made on return.
Refs #1058 #541 #476 #457.

### 124. A battery shown because nothing said it was missing — a saved size and an empty meter taken as proof — GUARDED
**Symptom:** on a home with no battery the Energy Plan card drew one (#1063, lostcontrol, 2.2.0-beta.11, Fronius). Today: the sunny hours wore the "battery covers home" colour. Tomorrow: a "Battery" row filled from 0.0 to 7.4 kWh. Load planning was right; only what the card showed was wrong.
**Root shape:** two claims that a battery exists, neither from a fact about a battery. (a) A size: `battery_capacity_kwh` answered the built-in 15 kWh, and the settings step saves a size on every install, so "has a size" was true everywhere. The tomorrow preview walked that pack. (b) A colour by elimination: the card painted a slot "battery" when the meter carried none of the house. A sun slot carries none either (the ledger sets its net draw to 0), so every home's sunny hours read as battery — the battery-less home only made it plain.
**Where it lives:** the capacity property (tomorrow's battery row, the plan's battery flag, `forecast_surplus_kwh`, which took a 15 kWh empty battery's need off a battery-less home's surplus — **swept by the source**); the plan card's Home row colour, icon, hand-over time and legend; tomorrow's "battery charging" key; the battery-night recorder, which sealed nights of zeros on a battery-less home and could put "drained 0.0 kWh overnight — the promised refill never came" on the card (**swept**: no battery, no record; the backfill service now says so); `battery_redirect_w`, where a size of 0 read as "full" and gave the car the whole charge of a battery added since the last reload (**swept**: no size, no redirect; a saved size is at least 1 kWh, so only the ABSENT answer is 0).
**Closure:** a battery is claimed only from a fact about one. The property returns 0 when the battery module is ABSENT (#923); UNKNOWN keeps the old answer, so a slow boot never hides a real battery. The plan marks a slot `batt` only where its walk drew the battery for the house, and says `has_battery`; the entity carries the marks as index runs (`batt_runs` — a flag per slot pushed a 15-minute day over the recorder budget). The card colours each slot grid / battery / sun through `util/plan-cover.js` and shows no battery icon, hand-over time or battery legend without them. A plan stamped before the fix has no runs (`None`, not `[]`) and keeps the old colours until the next stamp, so a battery home's night is not drawn as sun after the update.
**Guard:** `tests/test_1063_plan_card_no_battery.py` — the property over ABSENT / UNKNOWN / PRESENT; a real plan stamped at 14:00 with and without a battery (no `batt` anywhere without one; sunny hours never `batt` with one; every evening hour the battery covers is marked); the quiet night carries the flag; the entity carries the runs and the flag, an old plan carries neither, and the runs cost a 96-slot day at most 12 bytes; tomorrow has no curve without a battery and keeps one with it; a saved 15 kWh on a battery-less home walks no battery today or tomorrow; the ready check still decides when plans run exactly as before; a battery-less night alone earns a review row, and the recorder records nothing when the battery is ABSENT; a size of 0 redirects nothing. (The backfill service's log line has no test: there is no harness for the service handlers.) `dashboard/card/test/plan-cover.test.js` pins the colour rule, the runs, the old-plan rule and the card's use of them. Four mutants of the fix fail the Python file.
**Sweep question:** for every place that shows a part — is it shown because something says the part is there, or because nothing says it is not?
**Left for Guido:** (0) the plan's ready check (`_energy_plan_tick`) still asks the saved key: on a battery-less home the SOC reads "unavailable" every cycle, so one that saved the Settings step (15 kWh) never stamps a plan — the card stays "pending" and nothing is planned. Asking the module verdict there would start plans (and plan actuation) on those homes: a control change, not part of a display fix. (1) an install whose Energy Dashboard could not be read is UNKNOWN and still walks the 15 kWh default — by design (#925). (2) Other readers of the saved key keep their own defaults (`build_view.py` 15, `energy_calculator.py` 15, the battery scheduler 10, the battery ETA 15.0, the battery runtime 0): on an ABSENT home they sit in battery paths that do not run or show nothing, so they were left. One of them pairs with the property: `decide.py` sizes the redirect from `build_view.py`'s saved key while the EV budget reads the property, so in the minutes between adding a battery and the reload (still ABSENT) the two disagree (15 vs 0). They already disagreed whenever the size was auto-detected; one source for both is the fix. (3) A slot with no house draw and no sun (a house profile of 0 W at night) is drawn as sun.
Refs #1063 #923 #925 #857.

### 125. A field on the screen that no decision reads — the value stops at a log line — GUARDED
**Symptom:** Configuration tab → Hot water showed "Max temperature" ("SEM never activates above this") and "Minimum temperature" ("below this, SEM force-heats from any source"). Neither did anything. With Solar target 70 °C and Max 60 °C the tank heated to 70 °C, and only the Control tab's "Run now past" forced heating, so users set one thing in two places and could not tell which counted (#1062, lostcontrol, #1059).
**Root shape:** #92 made the solar target the ceiling on purpose and dropped the separate maximum. 1.7.2-beta.2 put both fields back on the card "config-only for now", with help text for what they should do. #454 then wired the controller and gave a decision only to the solar target and Legionella. The max value reached `HotWaterController.max_temperature` and stopped at a log line, `to_dict` and a published `HotWaterSensorData` field. `tests/test_knob_wiring.py` passed, because it asks whether the config key is read — and it was, into an attribute nothing decides on.
**Where it lives:** hot water `max_temperature` (number entity, card row, published value) — **removed**, and the stale-entity sweep drops the entity on the next load. The `hot_water_minimum_temperature` card row — **removed**; the key stays for its two real uses. `needs_heating()` (diagnostics only) — **removed**. The Control-tab comfort band on a boiler said "device's own thermometer" but read nothing unless one was picked, so "Run now past" never forced a boiler — **swept** (`HotWaterController._comfort_fallback_reading`, in °C). Vacation now turns the band off (#594: no comfort heating while away), so the newly working band cannot plan a grid block or force a run while away. A scan of every device constructor value found one more with no reader, `SetpointDevice.min_setpoint`; nothing sets it and no screen shows it, so it is allowed with that reason.
**Closure:** remove the dead fields and their surface (the #830 option list only shrinks), so each meaning has one place. Configuration: boiler, sensor, solar target, Legionella. Control: mode, priority, the stop ("Keep at" + "Bank by") and the force ("Run now past").
**Guard:** `tests/test_1062_hot_water_fields.py::TestEveryDeviceSettingReachesADecision` — AST: every `self.<x> = <a parameter>` in a device `__init__` (plain, annotated or tuple assignment) needs a reader in the logic layer that is not inside a log call (`_LOGGER.*`, `log_on_change`), `to_dict` or a `*SensorData(...)` field; an allowance needs a reason and fails once it is no longer needed. It fails on the old code with `max_temperature`. It counts any `.<name>` read as a decision, so a same-named attribute elsewhere can hide a dead one — a floor, not proof. Behaviour pins in the same file: the switch-boiler stop through the real surplus pass, the Legionella cycle not cut by SEM's own stops (a user's stop entity still ends it), the band's fallback thermometer (°F included), vacation turning the band off, zero config unchanged, the card's option list without the minimum.
**Sweep question:** for every field a screen shows, follow the value past the attribute it lands in. Which decision changes when it changes? A log line, a diagnostic and a published copy are not decisions.
**Left for Guido:** (1) `min_temperature` keeps two narrow uses with no card field: the vacation surplus cap (its switch `vacation_dhw_surplus` has no surface either) and the setpoint a water_heater is left at when `turn_off` fails. Both belong with #914's open "release to the minimum setpoint" decision. (2) SEM does not stop a water_heater or climate tank at the target; its setpoint does. A target changed while it runs is not re-written. (3) A switch boiler whose sensor breaks while it runs is not stopped, because no reading is not proof of a hot tank; the start is still refused. (4) No gap between the stop (at the target) and the next start (below it): with a sensor near the element, the boiler can cycle at the anti-cycle limit (10 min on, 5 min off). (5) °F installs: `get_current_temperature` returns the raw reading and compares it with °C targets (older than this fix) — SEM never starts the boiler, and now also stops a switch boiler someone else turned on. `natural_achievement` and the written setpoints have the same fault. (6) Tanks no longer overshoot to 60 °C on sun, so forced Legionella runs come more often, at whatever hour they fall due; a solar target ≥ 60 °C still covers it. (7) The #638 comfort-banking pass runs a "willing" band on cheap grid whatever `top_up_policy` says, for every band device; it now reaches boilers whose band was set but read nothing. (8) Those banking and forced runs carry `_offpeak_forced`; a Legionella cycle that falls due during one is cut by force-expiry or the plan hold, which do not check `_legionella_cycle_active` — the older #914 "Legionella vs LIFO" stall, now reachable from a band.
Refs #1062 #1059 #92 #454 #705 #830.

### 126. A change waits in a second store that the section's "unsaved" count does not read — GUARDED
**Symptom:** Config tab → Tariff, Calendar mode: a user picked a Schedule helper as "Peak-time schedule" and read "no price difference" at the off-peak price (#1040, @mdscgan, 2.2.0-beta.11). The helper was never saved. The field had a small dot, but its section showed no unsaved count and no Apply button; the only Apply sat in a bar at the top of the card. Our own reply sent the user to the section's "Apply changes", which did not appear.
**Root shape:** the card has two places an edit can wait. `_staged` (#605) holds numbers, toggles and selects; the section counts it and its footer applies it. `_pending` (#528) holds entity pickers and toggles that reload the entry; only the top bar reads it. Each store is right on its own. The section's count read one of the two, so "nothing unsaved" was true of `_staged` and false of the section.
**Where it lives:** every structural picker (`_renderPicker`) and structural toggle (`_renderOptionToggle`) — Tariff (the schedule, the battery control entities, the bidirectional flag), Sensor sources, Battery zones (`battery_discharge_protection_enabled`, on the default view), Heat pump and Hot water entities. All **swept** by one change: both renderers bind their pending edit to the section (`_regPending`).
**Closure:** the section owns every edit made in it, whichever store holds it. `_sectionUnsaved` counts both stores; the section's Apply sends staged and pending keys in one `set_option` call (one reload); Revert drops both. Picking another tariff mode drops the unsaved edits of the fields that mode hides (`_pickTariffMode`), so Apply never saves a field of a mode the user left. A row hidden by the view (Advanced off, a closed fold) keeps its edit on the count, as #605 did — a first try that unbound every hidden row held such edits back with no number anywhere (review). The top bar stays for edits in several sections; the two Apply buttons wait for each other.
**Guard:** `dashboard/card/test/calendar-setup.test.js` — the real card: a picked schedule counts in its section, the section's Apply sends it with the staged mode and rate in one call, a failed Apply keeps it, Revert drops it, another section's edit stays waiting, a structural toggle binds too, a mode picked and left again sends nothing, an Advanced-hidden edit still counts, the two Apply buttons wait for each other.
**Sweep question:** for every "unsaved" count or "dirty" flag — list every store an edit can wait in, and ask whether the count reads all of them.
**Left for Guido:** (1) per-charger pickers (`_renderPickerNested`) save at once and have no unsaved state at all — a third way; so do the Dynamic pickers, which now show (and save) as soon as Dynamic is picked, before its Apply. (2) With a structural edit waiting, the section footer and the top bar now both offer Apply; the top bar could go. (3) `_renderTextOption` saves `battery_setpoint_model` and the direction values at once on blur, though they are structural keys — each edit reloads the entry.
Refs #1040 #528 #605.

### 127. A card draws again only when a listed input changes — it shows one the list leaves out — GUARDED
**Symptom:** the grid limit was right on the Control tab after #1055, until you changed it on the Configuration tab. Back on the Control tab the slider and its value showed the old limit until a browser reload (#1055 follow-up, lostcontrol, 2.2.0-beta.12, load management off). Saving it on the Configuration tab also restarted the whole integration.
**Root shape:** HA sets `hass` on every card for every state change in the house, so each card compares a few inputs and draws only when one changed. The list of inputs is written by hand beside the code that reads them, and the two drift. The load list card compared `controllable_devices_count`, `consecutive_peak_15min` and `load_management_status` — not `target_peak_limit`. With load management off all three never change (0, 0.0, "idle"), so it read the limit once and never again — and the device rows (on, off, power, shed) stood still too. `SEMLitBase` compares `.state` only; "no grid limit" is an attribute (`peak_limit_unlimited`), and the Control card did not list the limit sensor at all. Kin of class 24 (a hand list next to a structure that grows). The reload: `set_option` sent `target_peak_limit` live only through the load manager; with none it fell to the unrouted path (entry write + reload). `peak_limit_unlimited` took that path on every home. #913 took the same reload out of the Control slider.
**Where it lives:** `sem-load-priority-card.js` (the instance), `SEMLitBase.set hass`, the Control card (`target_peak_limit` and `diag_grid_sign` read, not watched; the flag), the Home card (the flag). All **swept**. `__init__.py::async_set_option` for `target_peak_limit`, `warning_peak_level`, `emergency_peak_level` and `peak_limit_unlimited` (**swept**). Checked and right: the tab header (its key has the flag), the Config card's options (read again each time you return to the tab).
**Closure:** the load list compares the state objects of `LOAD_PRIORITY_READS` — every SEM sensor `_updateDeviceData()` reads — and HA gives a new object only when the state or an attribute changed. A slider value is kept until the sensor has it (15 s at most, dropped when the write is refused), so a push from before the save cannot move it back. `SEMLitBase` takes `watchedAttributes` (`{ entity: [attribute] }`) and compares them with the state. `set_option` writes the grid keys live: through the load manager when there is one (the flag too, with the saved or sent limit), else with `persist_global_option`, the same write `update_target_peak` uses. A level that is not a number is refused before anything in the save is written.
**Guard:** `dashboard/card/test/redraw-gate.test.js` — the real cards: the load list reads a new limit and a flag-only change with the other sensors still; one push after returning to the tab is enough; an unrelated push does not draw; the slider hold, its end, its time limit, a refused write, and a refused older drag that must not drop a newer hold; the Control and Home cards draw on a flag-only change. A source check: every SEM sensor the load list reads is in `LOAD_PRIORITY_READS`; every card on the base gate watches each sensor it reads with `_val*()` or `${this._prefix}`, and a card that shows "no grid limit" watches the flag (an unwatched read needs a named reason). On the old cards all fail but the one that an unrelated push does not draw. `tests/test_1055_config_save_no_reload.py` — real HA: the limit, the flag (also as the word "false") and a level save keep the same coordinator and reach the published sensor, with and without a load manager; with both keys in one save the flag is written with the sent limit; a level that is not a number (also "nan") is refused and nothing is written.
**Sweep question:** for every card that skips a draw — list what it shows, list what it compares, and ask which one is longer.
**Left for Guido:** (1) cards with their own hand-made key — charger status, EV status, energy plan, price, flow, grid, battery, energy impact, solar, solar summary, schedule, today plan — are not read by the source check. (2) The source check sees `_val*('x')` and `${this._prefix}x` reads only: a quoted `'sensor.sem_x'` read and attributes other than the grid flag are not checked (the System card shows `diag_ed_config` attributes). (3) A device's live power on the load list moves at SEM's cycle, not on each power-sensor change — on purpose, so a push from before a device edit lands cannot undo it. (4) Without a load manager a saved warning or emergency level is stored without the #813 order repair, as before; only the reload went away. (5) The Config card's Hot water live block reads seven entities SEM does not create (`hot_water_registered` and six sensors), so it never shows; the source check allows those reads by name. (6) A device edit on the load list (toggle, mode, goal) has no hold: a cycle that was already running can show the old value for one cycle. Homes with load management on always had this; homes without it now do too, because their rows now move.
Refs #1055 #913 #897 #716 #668.

### 128. A reconcile that only moves one way, on a belief the hardware disproves — the error in the other direction is kept — GUARDED
**Symptom:** on 4 Oct the calendar-day car row said 19.56 kWh while both wallbox counters said 10.99 (#1049, RienduPre, 2× Wallbox Pulsar behind the MQTT bridge, 2.2.0-beta.9). Home is the meters minus that row, so home read 8.49 kWh against 17.28 of to-home flows, true baseload went negative, and the controlled-loads check blamed a "renamed or removed id". Every counter was set up, live and right.
**Root shape:** the EV rows took the counters UP only (#658), on the belief that a charger counter "can only ever reveal energy the integrator missed". That holds for downtime; it fails when the power sensor reads high (the bridge's open issue #110: 7.6 kW on one phase at 16 A), and the one-way rule keeps every kWh of it. The grid and battery rows already moved both ways (#628), so home was built from meters on one side and an unchecked integral on the other. Kin of class 28's note (one-way passes keep errors instead of cancelling them) and class 40 (a guard defending the wrong number).
**Where it lives:** `EnergyCalculator._reconcile_ev_bucket` — the EV-day row and the calendar-day copy home subtracts (**fixed**); the per-charger rows `coordinator._daily_ev_per_charger`, which had no counter at all (**fixed** — left alone, the members would sum above a fleet row that moved down and the #771 check would fire). Checked and kept one way: `_reconcile_solar_energy` (on a hybrid the counter is AC yield and trails PV all day — down would be wrong). `_reconcile_metered_energy` already moves both ways.
**Closure:** the counters own an EV row when every charger has a counter of its own (`complete` and `owners`, from `_ev_counters_cover_fleet` / `_ev_counter_owners`; a shared or fallback counter does not count), every counter reads, and the anchor was taken with this same complete set (`whole` — a restore runs after setup, so a changed set must be caught here, not only in `configure_ev_counters`). An owned row follows the counters up at once, and down only once every box has stopped charging (`EV_ACTIVE_CHARGE_FLOOR_W`) and its counter has reported since (`_track_ev_pending`, `_ev_settled`): a counter can publish a value minutes old, and one that reports late or never must not pull a row under what the box drew. What a box drew before an anchor and its counter had not reported is `owed`: that counter's next move pays it first, so a late report after midnight or Charge-by is not booked on the new day. A drop within `EV_COUNTER_DIP_KWH` / `EV_COUNTER_DIP_SHARE` of the last reading is a dip and holds it (class 43); a larger drop is a reset. Each charger's row follows its own counter the same way (`follow_charger_counter`, only on a complete fleet, one box's ceiling; a box with flat keys is `ev_charger`).
**Guard:** `tests/test_1049_ev_counter_owns_the_day.py` — the reporter's shape (5.0 by power, 3.0 on the meter → 3.0 on both rows and in month/year/lifetime once the box stops); a late counter, a report from before the stop, and a counter that never moves never pull down; standby is not charging; upward recovery runs at once; dips (also on a day's first read) are not booked, real resets (also to more than half) are; a late report after midnight or after a charger's Charge-by is not booked twice; a partial set, an owner-less counter, a dark counter, a counter first seen after the anchor, a counter swapped since the store, and a set that became complete never pull down; the owed draw and the per-charger baselines survive the store, a damaged one re-anchors; home gets its kWh back; the wiring is checked with `ast_contracts`. Switching off each guard fails its tests (settled 12, drawing 8, owed 2, dip window 3, day-start dip 1, set check 3, `complete` at the anchor 1).
**Sweep question:** for every `if target > current: adopt`, ask what would make the integral read HIGH, and whether the counter could then be trusted to say so.
**Left for Guido:** (1) the 2–4 kWh steps at each charge start are in the power read (the counters show none); the cause is in the bridge or the box, not found here. (2) While a car charges, an owned row still holds the power read (down only after the stop), so a session across midnight or Charge-by keeps its high read on the closed day, and kWh Charge-by targets see the high read mid-session as before. (3) `_update_ev_intelligence` integrates each charger with the nominal `update_interval`, not the time since its last run — a charger with no counter of its own keeps that error. (4) A box whose own draw SEM cannot read (an id-less entry, no power sensor of its own) is charged the fleet's draw, so on a fleet the rows wait for every box. (5) A correction of an EV day that began last month lands in this month's key (clamped at 0).
Refs #1049 #658 #628 #771 #1044 #782.

### 129. One reading taken as what a load draws — an up-only rule keeps the start peak for life — GUARDED
**Symptom:** a dehumidifier that draws ~200 W showed "~1.4 kW" on the Control card, and SEM never switched it on (#1067, lostcontrol, Fronius, 2.2.0-beta.12). The rating is also the surplus SEM waits for before it starts the load.
**Root shape:** a compressor or motor start reads several times the running draw for a few seconds. Every path that learns a load's rating took the highest single reading it was shown, and every path that keeps it only moves up: a real measurement, the wrong statistic. Kin of class 40 (an up-only guard defending the wrong number) and class 128 (a one-way rule keeps the error in the other direction).
**Where it lives:** `ControllableDevice.calibrate_rated_power` (every device type; adopted any live reading above the rating — **fixed**); `UnifiedDeviceRegistry._history_max_power` (the largest value in 7 days, also read with no unit, so a kW sensor seeded 2 kW as 2 W — **fixed**, now `_history_held_power`); `_initial_rated_power` (a load running at build time got its instant reading as a measured rating, both ED build sites — **fixed**); `_capture_calibrated_ratings` (saves up only — kept, and only shown held levels now). Checked and right: `WattsPerAmp` (a median per bucket). Display only, left: `_rated_power_for`'s live fallback for a row with no device, and `LoadDeviceDiscovery._get_device_power_rating` (no decision reads it while the registry is active).
**Closure:** a rating is the highest level the sensor HELD for `RATED_POWER_HOLD_S` (120 s). Live: `devices/held_power.py::HeldPower` keeps one unbroken run of readings and returns their lowest once the run covers the hold, counting the reading in force when the hold began; the load going off, or a gap over `RATED_POWER_SAMPLE_GAP_S` (90 s, above the longest 60 s update interval), starts it again. History: `held_power_w` takes the same level over the state changes, each held until the next, in the executor; a value above `_MAX_PLAUSIBLE_LOAD_W` breaks a run (a W→kW unit change inside the week, for loads above 100 W). Saved ratings carry `rated_power_rule`; a store without it marks every saved rating for one re-check (`rated_power_recheck`, persisted). The re-check reads history first and then decides in one pass with no await (a rebuild may swap the device objects during the read). Until history answers, a marked rating is applied only over the 1 kW placeholder (class 40); it is replaced by the held level only if that level is at least 1/`RATED_POWER_START_PEAK_RATIO` (20) of it — a load left on but idle is not a start peak — and the device itself moves down only if this sync built it from that saved number (`_built_from_store`, cleared each sync). A rating a device was given (heat pump, hot water) is never lowered, nor raised to a marked number. The rule check is `<`, so a store from a later rule is left alone.
**Guard:** `tests/test_1067_held_rating.py` — the reporter's start peak then 200 W learns 200 W, live and from history; a peak does not raise a learned rating; a level held long enough still does; a noisy run learns its floor; a gap, an off load, a 60 s interval, and a peak held 90 s at a 30 s cycle; a kW history read in watts, a missing sensor, a unit change in the week; the build takes no reading; an old store is marked, the marks and the rule survive a restart, a damaged mark list loses nothing else; history moves the old peak down (also one 15 times the run), an idle week does not, no history changes nothing, a placeholder still gets the saved number; a given rating is neither lowered nor raised to an old peak; a live level is not overwritten; a rebuild during the read keeps the answer; a failed history job is no level. Removing each part of the fix fails a test (19 checked).
**Sweep question:** for every value learned by "keep the highest": would one short spike be enough to set it, and could anything ever bring it down?
**Left for Guido:** (1) a marked rating whose load did not run in the 7 days before a restart keeps its old number until a restart after a run (the check runs once per start). (2) A sensor that reports every 2 minutes or slower can hold a caught start reading for the whole hold, live and in history. (3) A load whose draw changes faster than the hold (fan and compressor switching, a thermostat clicking) learns its lowest level, or nothing and keeps the 1 kW placeholder. (4) Energy Dashboard loads are unregistered before a rebuild, so `_VOLATILE_CONTROL_FIELDS` (the hold and every older field) never carries over for them; a rebuild (setup, the 35 s rediscovery, an edit) starts the hold again. (5) A rating learned live is saved only on the next rebuild (as before). (6) There is still no field to set a load's power by hand (the reporter asked for one). (7) The 1/20 rule is a trade: a saved heating-phase rating whose week held only a lower mode (a cold wash) moves down until its next heating run; a start peak more than 20 times the run is kept. (8) A W→kW unit change on a load under 100 W is not caught (60 W reads 60 kW, under the cap). (9) Older, not from this fix: the #888 early save in `_load_storage` runs before the ratings, service registrations and goals are read, so it writes them empty until the next save.
Refs #1067 #744 #576 #641.

### 130. A limit every device answers to — except the ones that were never handed it — GUARDED
**Symptom:** a review before building the grid operator's limit (#1021) found the house limit was honoured by the car and the shed loads but not by the battery, and not by the bill (#1069, review 08.10.2026). A 4.2 kW limit, the car offered 4.0 kW and a 3 kW planned battery block put 7 kW on the meter while every sensor read "under the limit".
**Root shape:** "the peak guard sits above every mode of every device" was true where the slot allowance had been threaded, and nowhere else. Each gap was a device or a reader that never received the one number, or kept a copy of it. Kin of class 93 (two producers of one context) and class 40 (a guard defending the wrong number).
**Where it lives:** `decide_battery` — every FORCE_CHARGE (planned block, negative price, manual) charged at full power (**fixed**: `_cap_forced_charge`, room = allowance + sun − house − what the chargers were offered, 250 W steps, stop below one); `peak_cover_floor_w` raised the discharge limit at any SOC (**fixed**: `reserve_stops_peak_cover`); `SchedulerConfig.peak_limit_w` / `max_grid_import_w` — a setup copy nothing read (**deleted**); `LoadManagementCoordinator._update_peak_tracking` booked the monthly peak from a sliding window (**fixed**: `record_closed_slot` from `PeakSlotTracker.pop_closed`); `PeakSlotTracker` started each restart at zero (**fixed**: `to_state` / `tracker_from_state`); `clamp_to_peak_slot` floored at 6 A, so a car over a limit near its minimum flipped every cycle (**fixed**: a `peak_paused` IDLE through the stability delays, restart with minimum + hysteresis); the tomorrow preview packed against the raw cap (**fixed**). The car's clamp counts SEM's own forced battery charge as room (`battery_forced_grid_w`), so the car comes first.
**Guard:** `tests/test_1069_peak_foundation.py` — one class per finding, each from the reviewer's scenario; the stability rule runs with the user's own delays in a surplus mode, `always_max` and a night floor.
**Sweep question:** for every device SEM can make draw from the grid, which line hands it the slot allowance — and does anything keep a copy?
**Left for Guido:** (1) loads (the surplus controller) still see the car's and the battery's new offers only next cycle, through the meter. (2) The rolling 15-minute average stays as the shed states' trigger; only the bill moved to clock slots. (3) A paused car holds 6 A for the disable delay while the meter is over the limit; #747's emergency still stops it at once.
Refs #1069 #864 #1003 #693 #905 #747.

### 131. A page every home must pass asks for a part only some homes own — GUARDED
**Symptom:** a home with no charger opened Configure and met only the EV charger page; nothing could be filled and Submit did nothing, so a second heat pump, and every later setting, was out of reach (#990 round 2, @damiano75, 2.1.0).
**Root shape:** the options dialog is one chain, and its first page (the primary charger) had three required fields. #442 made the charger optional at install; the pages kept treating it as a precondition. HA's frontend will not submit a page with an empty required field, so one optional part closed the whole dialog. An optional entity picker with `default=""` closes a page the same way: HA validates the default, and "" is not an entity id. Kin of class 30 (a key with no editable surface) and class 124 (a part assumed present because nothing said it was missing).
**Where it lives:** `OptionsFlowHandler.async_step_init` opened on the charger page (**fixed**: no charger, by `has_managed_charger`, opens the charger menu; the skipped page's saved values are kept in `_unshown`, apart from the draft, and merged at save, so the save changes nothing, #690, and a saved `None` never becomes a later page's default, #73). `async_step_reconfigure` (**fixed**: `_charger_field` makes the three optional without a charger, all three checked once one is filled; `ev_charger_service_entity_id` and `ev_total_energy_sensor` take a suggestion instead of `default=""`, which had made the page unsaveable for every home without both). The menu offered "Add another EV charger" for the first one (**fixed**: `flow_add_first_charger`). Found on the way, class 101's sequel: `ev_charger_add` minted ids from the list position, so remove charger 2 of 3 and add one gave two chargers one id (**fixed**: the next number unused in the draft and both saved lists). Checked and right: every other required field in the options chain has a default.
**Guard:** `tests/test_990_no_charger_dialog.py` walks the whole dialog through HA's flow manager the way the browser does (the serialised schema, what each page pre-fills plus what the user types) and fails on any page with an empty required field: the plain walk, and one that adds a charger and a heat pump. Also: charger homes (list and flat keys) still open on their page; the skipped page changes nothing saved; a saved `None` does not break the add page; Reconfigure saved through the real flow manager with no charger, with a flat-key charger, and half-filled; charger ids after a remove.
**Sweep question:** for every required field on a page every home passes, what does a home without that part enter?
**Left for Guido:** (1) the heat pump menu says "Your primary heat pump is configured" and counts it (`1 + len(heat_pumps)`) even when none is set up. (2) A first charger added from the menu gets id `ev_charger_0` and no flat keys, unlike one made on the old first page (`ev_charger` plus the flat mirror); the runtime reads the list, so both work. (3) Charger ids: a config saved before this fix may already hold two chargers with one id, and nothing renames them (heat pumps have `_heat_pump_rows`); and an id removed in an EARLIER save can still be minted again, because nothing records ids once used. (4) Reconfigure writes the charger sensors as flat keys into `entry.data` only. An options value still covers them, and a single charger's readers (`sensor_reader`, the charger power sensor) prefer them over the list, so an edit there splits the charger (class 19). So a list-only charger still meets three empty required fields on Reconfigure, on purpose; the real fix is to write the list too. (5) A legacy config holding only a flat `ev_connected_sensor` (no power sensor, no list) now skips the charger page; `unmanaged_charger_repair` counts that key, `has_managed_charger` does not.
Refs #990 #442 #690 #685 #73.
