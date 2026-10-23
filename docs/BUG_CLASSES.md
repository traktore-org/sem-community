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
sign the control layers cohere past. Refs #352 #461 #476 #588 #589 #590 #1194 #1208 #1193
(each battery judged by its own counters, class 167) #1215 (no lock
negates a pair, class 173) #1210 (the audit follows the read, class 174).
**Watch:** battery has no *physical* anchor (grid has solar) — a swapped-counter battery relies on
the counter detector + the perception audit + the manual flip.
**HA's own sign, read the wrong way (#1194, found while fixing #1171):** HA's battery sign is + while discharging (`BatterySourceType.stat_rate`), so a sensor the user marks "Inverted" in HA's battery dialog reads + while charging, which is SEM's sign. #551 took HA's sign for + while charging and flipped such a sensor, on the one-battery read only. Each battery of a fleet and the grid were read as they are. So a one-battery home read charge as discharge until the sign check learned a lock on the flipped value, and the brand seed, which describes the sensor as it reads, pointed the wrong way. The issue was filed the other way round (the fleet path looked wrong). **Fixed:** every combined sensor is read as it is (`_read_from_energy_dashboard`). What a store without `battery_basis` saved was judged against the flipped value, so `_move_lock_learned_on_flip` changes it once: a fleet lock is turned over; with no lock but "Fix battery sign" on, the old read's sign is locked (its brand seed, which the old check asked only with both energy counters set, else none), because that flip corrected the flipped read. That lock stops the counters from learning; Reset sign detection learns again. Either way the battery reads as before the update. A fleet lock waits while the home reads per battery; anything else is settled on the first Energy Dashboard read. Only HA's grid and battery sources take an Inverted option; the grid and two-sensor pairs were right. **Guard:** `tests/test_1194_inverted_battery_read_as_is.py` — HA's stored prefs shape (HA's own `_inverted` sensor beside the user's); one and two batteries read a sensor the same; a saved lock reads the same after the update, is moved once, and still moves after a restart before the first read; a lock kept from one-battery days waits through per-battery reads and moves on the return to one; a flip with no lock reads the same, with and without a brand seed and energy counters, also after a restart; locks the flip never touched stay (new or later store, Standard, SEM's own pick, per battery); no lock is made after a reset (flip on or off), without a flip, without an old store, or for a flip on a home that read per battery; an AST check that only the lock move reads `battery_power_inverted`, and its twin finds the old flip. 26 of its 38 tests fail on the old code. Going back to an older build and forward again changed a sign this code learned, and a home without an Energy Dashboard never saved the mark (#1208, **fixed**: class 168 round 2). **Left open:** SEM does not take HA's declared sign as its first guess for a Standard sensor, grid or battery; the brand seed and the counters decide, as before (a choice).

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
possible (fixed one at #589 EV W2/W3). **Battery side (#1167):** the same shape with a FLAG, not a
sum. The Force charge end check (#1164) asked "was the power read?" with one fleet flag, so one
dark power sensor on battery 2 stopped battery 1's check too, and battery 1 bought the next 1 %
from the grid. Its level flag was the fleet's SOC flag too: one dark unit moves the fleet average,
and the #902 step hold then darkens every unit. Closure: `BatteryPower.power_read`, set by the
reader per unit (both sides of a pair; an impossible value is no reading), and the pipeline hands
`_finish_manual_battery_modes` one power and one level flag per battery id; the check takes a map
and nothing else (a bool reads as no reading). One battery keeps the fleet flags: they are its own.
Guard: `tests/test_1167_own_power_read.py` — the reader, the pipeline from a real read, the check
on a real config entry, and AST guards: the per-battery branch reads no fleet power flag, what goes
into each unit's two flags names no fleet flag (a copy into a local first counts too), and the check
gets those two maps by name. Left open: the sell gates still read the fleet SOC flag on every unit
(#932: a sale waits), and a dark unit's SOC is averaged into the fleet level as 0 % (#1169). One shared mode select still waits for every pack it drives, so a dark pack
keeps the other's Force charge on there (#1131 by design); a fleet of two-sensor pairs got only that
shared select, because the per-battery controls counted combined sensors only (#1171, fixed: class 162). A unit's 0 %
blink is now one level read; the three reads in a row are what guard it. Refs v1.6.0–6.6, #589, #1167.

### 4. Strand-across-restart (a force op left running on the real inverter) — GUARDED
**Symptom:** a reload mid-force-op leaves the battery force-charging/discharging autonomously; a
swallowed command reports success while nothing moved. **Where it lives:** `battery_adapters/*`,
`async_unload_entry`. **Closure:** honest command results (record intent only on success → retry),
boot reconcile + unload cleanup across *all* intents/brands (not just Huawei discharge).
**Guard:** command-honesty tests. Refs #532 #535 #589.
**Round 2 (#1181) — a switch charge the hand-back did not stop:** GoodWe and the generic switch setup start a grid charge by setting the work mode or turning a switch on, and only the stop turns it back. Three paths sent no stop. Off and the unload release both hand the pack back through `command_normal`, which zeroed the setpoint and lifted the limit but left the switch on. A restart lost SEM's knowledge that it had started the charge, so with night charging turned off by then nothing stopped it. The pack charged from the grid with nothing watching it, and the #1180 target stayed. **Where it lives:** `goodwe.py` and `generic.py` `command_normal`, and generic `command_off` with a strategy select (**fixed**: `BatteryControlAdapter._stop_own_charge` stops a charge SEM started first. A failed stop records no NORMAL or OFF, so the next cycle tries again, but the zero, the strategy and the limit still go out: an unload has no next cycle, and the #1066 protection cycle must still write its limit (review)); the base sale stop, which runs `command_normal` (**fixed**: it ends the charge too, one cycle sooner than the charge stop did, and keeps the charge stop's error when that failed); the restart (**fixed**: `battery_adapters/charge_record.py` `ForcedChargeRecord`, persisted as `sem.forced_charge.{entry_id}` and removed with the entry. It names each switch or mode select SEM turned on and the batteries whose charge did it: the switch key is not per battery, and a pack in Off must not stop a charge its sibling started (review). The name is saved before the start's write, and a save that raises means no start; HA's own store logs a disk error and returns, so disk trouble does not hold a charge back. It is dropped when a stop lands, or when the entity reads that no charge runs, also after a start that raised (review: kept, it named a switch the user turned on later). The pipeline calls `async_adopt_running_charge` before each battery decision, in observer mode too because it only reads. A named battery whose actuator still reads a charge is marked active with `_sem_forced_charge` True, so the next NORMAL or limit decision sends the stop unless the plan still wants the charge. An actuator HA has not loaded yet is asked again next cycle: a stop sent to it would be dropped without a word); `unload_release_reason` (**fixed**: a forced flag still True, or a setpoint SEM wrote that is not 0 W, is a reason too. A lifetime whose first command was a sale wrote no limit, and that sale went on after the unload. An unload whose stop failed now says "release incomplete"). GoodWe's failed stop logs once, not every cycle. Huawei's `command_normal` already stopped its charge, and its status sensor clears a boot orphan; Deye restores its snapshot (assessed). A damaged or unreadable record names nothing, so SEM stops no charge it cannot show is its own (#936); the next start writes over it. **Guard:** `tests/test_1181_switch_charge_stops.py` — Off, an unload and a restart (then no scheduler, Off, or an unload) on both adapters set the actuator and the target back; back to Auto sends no second stop; a failed stop records no Off, keeps the name, still hands the limit back, and is tried again (both adapters, with and without a strategy select); an unload whose stop fails says so; a sale stop keeps that error; a plan that still wants the charge keeps it; an actuator that reads no charge, or is not loaded yet, is not adopted (the second is once it reads); an Off or a stop sent before the actuator loaded still stops the charge once it reads (second review: an adopted charge clears an Off or stop recorded before it, and a stop to an entity that could not be read keeps the name); the twins: a switch the user turned on is left alone by every path, a charge stopped before the restart is not adopted, a pack in Off leaves its sibling's charge, an observer unload sends nothing; the name is saved before the switch goes on; no record, no start; damaged or unreadable records adopt nothing; a failed start keeps the name only while the switch reads on; two packs on one select; an AST check that the pipeline adopts before `forced_ops`, inside the battery loop, never only outside observer mode. Two reviews: of 25 mutants, the four that lived are now covered, and 10 more in the second were all killed. **Left open (assessed, not bugs):** a charge started by a version before this one is not in the record, so that one upgrade mid-charge with night charging off is not stopped. Two packs on one work mode select: Off on one cannot hold the mode while the other's plan charges, because one inverter has one mode. GoodWe's forced charge cannot be set up today (class 116), so its paths are covered by tests only. A failed stop under Off is tried every cycle, like Huawei's (a dropped Modbus write is the common case).
Refs #1181 #1180 #936.

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
(audit W6; the lifetime seed's half closed by #1043, see class 52) — one dark unit of N (**closed by
#1186**, class 58 round 3: each unit keeps its own last read for the grace in the published total and
the rows, and home holds the house); the flow figures still integrate the dark cycle's raw inputs
(the daily rows hold them for the grace — #1177, class 58);
the steering home itself still reads a dark battery as idle (safe for the EV budget — the meter
answers — but the discharge limit home/n is wide for the gap; holding it needs the battery charge
held beside it); an EV power dropout is not in the dark tally at all (its own #910 hold + the 2-cycle
spike guard, whose count the dip hold can spend first). Refs #274 #461 #589 #611 #1047 #1065.

### 6. Multi-unit over-command (N× / partial split) — PARTIAL
**Symptom:** a fleet-level power target handed to *each* of N units → N× the intended
grid export/charge. **Where it lives:** `decide_battery.py` (arbitrage vs LIMIT_DISCHARGE).
**Closure:** `LIMIT_DISCHARGE` splits `home/n`. **Open sibling:** the (dormant) arbitrage
`FORCE_DISCHARGE` path does NOT split — a guard note + re-enable checklist is in place (#533).
**#1182:** the plan's sale (arbitrage and the forecast spend) was split by discharge limit
entities: two batteries on one sale power entity each got half (one writer sent half), two on
their own sale entities with one limit each got the whole (twice the plan). Now
`decide_battery.sale_surface_count`: a built adapter's `sale_surface()` (the sale entity, the
Huawei device, the Deye work mode select), a battery that cannot sell (no entity, withdrawn,
#840) gets no share, `mode=off` none; before the adapter is built, the config's sale entity,
else the limit entity as before. Guard: `tests/test_1182_one_sale_power_one_writer.py`
(the count, the pipeline share, an AST check that both splits use it). Left open: a battery
that may not sell by mode or permission still takes a share (as before, #1277); so does one at its floor (known only once it decides).
Refs #531 #533 #1182.

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
back on (since #1103 the grid has one: the Config card's Grid power pick). The device+`device_class=power` scoping keeps it from being a pure "match anything" rule, so
the list must actually name each brand's slug (EN **and** localized). **Where it lives:**
`ha_energy_reader.py::_POWER_DERIVE_RULES` — the `solar`, `grid` **and** `battery` include lists (same
shape as the multilingual `_DISCHARGE_CONTROL_PATTERNS` in `hardware_detection.py`). **Closure:**
multilingual keyword coverage per brand — #597 added Huawei's `charge_discharge_power` (EN) /
`lade_entladeleistung` (DE) to the battery list. **Guard:** the brand-naming table test
(`test_battery_power_derives_for_huawei_naming`) makes an un-covered brand slug fail CI.
**Open siblings:** the `solar` list (`pv_power`/`solar_power`/`production_power`) and `grid` list are
still English-shaped — Huawei's `inverter_input_power` / German PV slugs are *not* covered; sweep them
if a Huawei/localized user reports solar or grid reading 0 (grid already matches via `power_meter`).
**Instance (#1172, @mrietdijk80-jpg, HomeWizard P1, Dutch HA) — a name with no word in it:** the
Sankey drew no line in or out of the Grid node while the Grid total was right. Grid power read 0 W
all day: the Energy Dashboard's grid entry had counters and no power sensor, and HomeWizard names the
meter's net power by its device class alone (`sensor.p1_meter_power` EN, `sensor.p1_meter_vermogen`
NL) — no keyword can fit a name that is just the word "power" in the user's language, and the
split-grid search finds no pair on a one-sensor meter. **Closure:** a second tier, asked FIRST — a
rule's `declared` map `{integration: (entity key, …)}`, matched on the registry's unique_id /
translation_key through the one roster matcher `hardware_detection._entry_matches_declared`, never on
the entity_id. Scoped to the counter's device like the keywords, and to the integration that declares
the key. Before the meter's integration has loaded, the registry's own device class answers (the grid
has no cold-start retry: `power_resolution_incomplete` leaves it out). **Swept:** grid, battery and the
service-device load rule (`devices/base.py`) take HomeWizard's net power `active_power_w`; solar takes `active_production_power_w` (the meter's
power × −1, positive while producing — the plain one would read solar negative, and solar has no sign
check). **Guard:** `tests/test_1172_declared_power_key.py` — six languages, phase/average/peak twins
on the same device, cold start, wrong integration, the reporter's night end to end with a control that
reads 0 without the tier. **Sign:** a derived grid meter now gets the brand seed too
(`_grid_seed_entity` → `_grid_brand_seed`, `homewizard: True`), so its import is not read as export
while the counters vote. HomeWizard is seeded for its P1 meter only (`PLATFORM_GRID_SIGN_MODELS`,
device `model_id` `HWE-P1`): a kWh meter reads the way it was wired, so its counters still decide.
The sign report names the meter the seed asked (`grid_seed_sensor`). **Still open:** other brands
that name power by device class alone get the same tier only by adding their key. A home where
nothing is found now gets a Repair, not only a log line (#1188, class 170).
**Instance (#1189) — the split pair:** a Dutch or German DSMR meter (`sensor.electricity_meter_energieverbruik`,
`…_stromverbrauch`) was found by the English words `power_consumption`/`power_production` only, so the
grid read 0 W. **Closure:** the lexicon maps core dsmr's own keys `current_electricity_usage` /
`current_electricity_delivery`; the rebuilt roster carries them, and the declared tier (asked first)
finds the pair by unique_id / translation_key as `declared`. **Guard:** `tests/test_1189_dsmr_any_language.py`
(EN/NL/DE names read from HA's own translation files, kW, a control that loses the meter without the
key); the roles baseline holds the dsmr pair. **Review:** the declared tier now skips a disabled or
only-restored row (a dead DSMR entry hid the meter that works), a `declared` pair replaces a held name
guess, and the Config card counts the grid pair SEM reads as in use (no "Use" buttons for it). An
English DSMR with phase sensors on had its import read from phase L3; the key reads the total. **Still open:** P1 Monitor's keys are common words a
heat pump also uses, so they need a one-brand rule (#1222, fixed); the crawler reads `ram_` in DSMR Reader's
`telegram_timestamp` as an appliance and drops its pair (#1223); the card saves a split pair one
half per click, and half a pair reads export as 0 W (#1224).
**Instance (#1223) — the pair the roster never got:** DSMR Reader declares `current_power_usage` /
`current_power_return`, and the lexicon knew both, but the crawler called it an appliance (class 67,
`ram_` in `telegram_timestamp`) and then "other" (no anchor word). It now has a roster row, and the
declared tier finds the pair. Its rows have no device, so the pair is `declared-elsewhere` and proves
itself against the counters first.
**Instance (#1225) — a pair named by firmware:** a SlimmeLezer P1 reader (ESPHome `dsmr`) names its pair
`power_consumed`/`power_produced`, so the grid read 0 W. ESPHome is an opaque platform: the names come
from the device, and there is no key to declare. The same words name Sinapsi Alfa's SOLAR output and
P1 Monitor's phase rows. **Closure:** `PLATFORM_SPLIT_GRID_NAMES` asks the words on `esphome` only, and only
as the whole name the firmware gave (`original_name`, or the object id at the end of the unique_id), so
"Solar Power Produced" and "Power Consumed 3" stay out and a renamed entity_id is still found. **Swept:**
on the counters' own device the name search kept the LAST match, so a phase row (`grid_import_power_l2`,
`…_power_consumption_phase_l3`) beat the whole meter and was trusted. A whole-meter row now wins
(`_PHASE_ROW`); a phase row still picked is `any-device`, so the counters check it. **Guard:**
`tests/test_1225_slimmelezer_pair.py` (the firmware's rows in kW with phases, a control without the words,
other brands and other ESPHome names left out, EG4/DSMR phase twins). Setup still says "no grid power
sensor" for a pair the reader finds later (#1237).
**Instance (#1222) — words that are a meter in one brand only:** P1 Monitor names its pair
`power_consumption`/`power_production` (NL "Stroomverbruik", DE "Stromverbrauch"), so a Dutch or German
meter read 0 W. A heat pump, a car and a solar inverter declare the same keys, so no lexicon rule could
take them for every brand, and the crawler gave `p1_monitor` no keys and called it "other". **Closure:**
a rule's `brand_any` maps one integration to more `^key$` words; the crawler (`_match_role`, with the
domain through `classify_kind`, `_declares_a_whole_pair` and `roles_from_vocabulary`) and `role_for` read
them through `rule_any`. The rebuilt roster carries the pair, and the declared tier finds it as `declared`.
**Swept:** a Tibber Pulse has the same shape (`power`/`power_production`, DE "Energie"); English found
the export half only. `power` is `exact_only` beside `average_power`. **Guard:**
`tests/test_1222_p1_monitor_pair.py` (names read from HA's own translation files, a control without the
keys, a heat pump with the same keys, every `brand_any` word anchored, reaching the roster, and read only
through `rule_any`).
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
derivation leak into a *control* decision? Refs #250 #274 #597 #600 #744 #1172 #1189 #1222 #1225.

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
no-op and the legionella timestamp is lost on restart (**open sibling — temperature-safety, needs a decision**).
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
it writes? **Open guard:** an AST lint that a flow step writing \`ev_chargers[i]\`
on submit must source its form defaults from that same charger dict, not the flat config.
**Sibling closed (#1127, 15.10.2026) — each car's estimator read the flat copy:** every
\`EVTaperDetector\` was built with the flat config and read \`ev_battery_capacity_kwh\`/
\`ev_target_soc\` flat, so car 2's estimated level, the #708 stop cap and the daily drop used
car 1's pack. Capacity is not even in the primary mirror, so a card edit reached no estimator.
**Closure:** the detector takes \`charger_id\` and reads car settings through one resolver,
\`EVTaperDetector.car_setting\` (own \`ev_chargers\` entry, else flat, looked up on every read);
the decay fallback, the self-heal and the estimate-stop capacity read the detector's own value.
\`ev_charger_efficiency\` stays home-wide (no per-charger field). **Guard:**
\`tests/test_1127_each_car_its_own_pack.py\` — two cars, 40/80 kWh, through the real card write
path; AST: every package \`EVTaperDetector(\` names \`charger_id\` (None only for the primary
default), and the detector reads \`self._config\` only through \`car_setting\` (efficiency
excepted). **Left open:** the daily drop's prediction is the
whole home's EV use, given to every car (#1132, class 3).
**Fourth instance (#1071, 08.10.2026) — two rules pick the owner:** a battery's mode/reserve
is stored twice — the scalar \`battery_mode\`/\`battery_reserve_soc\` (the one global
\`select.sem_battery_mode\`/\`number.sem_battery_reserve_soc\`) and the idx-aligned
\`battery_modes\`/\`battery_reserve_socs\` lists (the per-battery controls). The platforms
picked the control by the slugs found at setup; \`_per_battery_config\` picked the store by
"is a list slot set?" plus the LIVE count. A one-battery install with a leftover list (.175:
\`['auto','auto']\`) showed the global select and the list shadowed every write — select
\`force_charge\`, SEM \`auto\`. The same split hid two more: per-battery controls on a
one-battery cycle (cold-start ED, #274) read the stale global key (#531's hazard), and a global
select (two-sensor batteries, #553, got no per-battery controls until #1171, class 162) did nothing once two were
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
\`async_config_entry_first_refresh\` and no second discovery. **Open siblings:**
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
**Instance (#1103) — read on one of two reader paths:** the Config card's Grid power pick (`grid_power_sensor`) was read by `_read_from_legacy_config` only; `_read_from_energy_dashboard` never looked, so on every home with an Energy Dashboard the pick did nothing. Pinned in `tests/test_1103_own_sensor_is_no_input.py::TestTheGridPickIsRead` (see class 136).

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
**Left open:** (1) a Sessy has no discharge-limit setting, so SEM still cannot keep its NOM loop
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

**Instance — #1125, a hand-off list, not a persist boundary.** A charger found after start-up (`_retry_ev_device_setup`) handed its sensors to the reader through a literal `key_map` typed beside the reader's start-up parse (`SensorReader._parse_config`). The map had plug and charging, a dead `ev_total_energy_sensor` (no such reader field), and no power sensor, so `ev_power` read 0 W and the car counted as house load. **Closure:** first `SensorReader.adopt_late_charger` ran the found keys through `_parse_config`; since #1136 the find is saved and setup reads it like any saved charger, so there is no hand-over at all. **Guard:** `tests/test_1125_late_charger_power.py` — every key both discovery writes and the parse reads is taken; no production code outside `sensor_reader.py` writes the reader's config.

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
without anyone naming the route. **Open, named not closed:** the veto is judged on the
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
`dashboard/card/test/calendar-setup.test.js`. **#1089 (10.10.2026):** `_per_battery_config` gave
each battery its own slot of `battery_discharge_control_entities` since #523, but no screen wrote the
list — Config tab and Configure showed the one shared entity. Two Sessys, one picked: SEM limited the
first and the second discharged into the car. Closed by one row per battery on the Config tab (one
generic `_renderBatteryListPicker` for all three per-battery lists) and one Configure page per
battery (`settings_battery_limit`, one field, so any count fits); guard
`tests/test_1089_per_battery_discharge_limit.py::TestEveryPerBatteryListHasARow` (every
control-entity list `_per_battery_config` overlays has a Config-tab row) and
`dashboard/card/test/battery-discharge-limit.test.js`. Review: the lists now drive a battery only
while more than one battery runs (the live count), so a slot left from two batteries cannot hide the
shared field on a home down to one. Not the captured slugs: they can be stale after a removal, or
empty on a cold boot while two run — and a Sessy b2 without its strategy select is built as the
inverter's battery (#531).
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
**Third half (#1214, 29.10.2026):** a field whose `default=` is the saved value cannot be emptied either. HA's frontend does not send an emptied field, and voluptuous fills a missing `vol.Optional` with its default, so the saved value comes back before any merge can see the gap. `ev_charger_service` on all five pages, `mobile_notification_service` ("None" is the empty value) on two and the PV string names all did this; @bekovan could not erase an old integration's entity from the service field. The Reconfigure page also saved `user_input` as it came (an emptied field was never written) and into `entry.data` only, while the page shows `{**data, **options}`: once a Configure save had put the key in the options, every Reconfigure change came back (class 19). **Closure:** a saved value on a field a user can empty is a `suggested_value`; Reconfigure merges with `_merge_form_input` (a field never set is not written as `None`) and writes each key the options hold there too. An emptied service keeps its box name: an Easee's start and stop services are sent to it too (review). **Guard:** `tests/test_1214_fields_can_be_emptied.py` — an AST scan fails on any `vol.Optional` with a non-empty default on a text or entity field, or on a select that offers the empty value; real Home Assistant Reconfigure and Configure walks with the browser's rule (an emptied field is not sent). **Left open:** the Reconfigure page edits the flat keys only, and the builder reads the first charger's card first, so its charger fields change what SEM runs only where the card has no value (#1247). The first charger's Configure page keeps the old service's field name when the service changes (#1249).
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
class-33 mislabel — but their INGEST assumes °C, which is the deferred sibling below. The
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
left open (larger/riskier — control + safety path):** the heat-pump / hot-water controllers'
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
  decision, not by building it** (decision 2026-07-26: SEM does not support Sperrzeiten): the
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
collector pins are RED against the pre-fix gate. **Left open:** (1) on a kWh target the gate
still consults the anchor and the N2 meter rule is memoryless, so any false anchor still makes the
car-full term follow the draw there. Closing it means letting post-full energy refute a
`_full_detected` anchor (exempt by design today —
`test_a_detected_full_charge_is_never_refuted_by_its_own_trickle`; #939's car took 23 kWh
"post-taper") and making `get_virtual_soc` recalibrate when it re-arms on an unchanged reading. (2) A
SOC car that finishes mid-night by taper (Min 100 %, or the car's own limit) no longer restamps the
plan through this term — the SOC need is not a signature term, so its blocks stay stamped until
another trigger.
**Known-open sibling (#744, needs a decision) — the authoritative read is UNREACHABLE for lights.**
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
load-shed *policy* change, not a display fix — it needs a decision before it ships.
**Third catch (#820, @ArneGollin1987, 16.09):** the mirror image. `charge_pacing.paced_charge_cap_w`
solved the pace from surplus hours only — deficit hours counted as zero — while the *authoritative*
model the user sees, `provisional_soc_curve`, walks the house drawing the pack DOWN in exactly those
hours. Two models of one day, and the one that ACTS was the weaker. An afternoon cloud or a midday
EV session grew the need by a kWh the cap never saw, and the evening "could not reach the pacing
watts". Same file, same fix shape: the solver reads the drain the curve already knows (`_drain_kwh`).
The cousin defect beside it — a cap solved to land full in the LAST slot exactly, no margin, against a
docstring that promised "sunset − margin" — is class 46 (b), a discarded field: `end_margin_slots`
existed, defaulted to no margin, and no caller set it.
**Fourth catch (#1221, 28.10.2026) — a card figure, not a decision.** The Energy Impact card
printed its own "CO2 today": (solar → home + solar → EV) × 128 g/kWh. `sensor.sem_daily_co2_avoided`
counts all solar used on site, also into the battery, and adds the live grid value when that is on.
On a day the battery charged from the sun, the card showed less than the sensor. The card already
watched the sensor and never read it. **Closure:** the card prints the sensor's state ("—" when it is
out). The line under it shows two new attributes the sensor publishes, `solar_used_kwh` and
`co2_kg_per_kwh_today` (the day's average once the live value counts; the rate now while the kWh
shows 0.0), at the precision the card shows. They are unrecorded, the card draws again when they
change (class 127), and the figures take the sensor's own unit (class 33). The sensor's `co2_fallback_kg_per_kwh` read a `0.128`
literal and now reads `GRID_CO2_KG_PER_KWH` (class 46). **Guard:**
`dashboard/card/test/energy-impact-co2.test.js` — the real card: the hero is the sensor, not the flows;
the detail line at the fixed and the live rate; the dash when out; a redraw on an attribute-only
change; a source check for no `128` and no `flow_solar_to` read. `tests/test_1221_energy_impact_co2.py`
— solar into the battery is in the kWh, kWh × rate gives the figure (also on a day at two rates), the
rate with no solar yet, and the sensor publishes both. All fail on the old code. **Checked and right:**
the Home card and the tab header read the CO2 sensors; the Costs card's "avoided" subtotal adds the
two savings sensors, the same sum `daily_total_savings` makes; the Grid card's net has no sensor.

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
**Open sibling — the mirror-image FORCE_CHARGE flood (needs a decision):** `command_force_charge`
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
**Second instance — #1142, a charger's state sensor.** Setup bound a Zaptec Go's main binary sensor, "Charger", as "a car is charging": "charg" is in its own name. Its class is `connectivity` — on while the box is online — so SEM saw a charge all day. The real state, "Charger mode" (`charger_operation_mode`, an enum), was never bound. On the integration's newer layout the main sensor is "active", so no state was bound at all, the brand rule refused the Go, and setup fell through to the near-miss offer with the installation's site limit as its control (#1141). Once the brand rule ran there, a third pick showed: its name fallback took `total_charge_power_session` (kWh) as the power. **Where it lives:** every name rule for `ev_charging_sensor` on a `binary_sensor` — Zaptec, go-e, Wallbox, openWB, V2C, the ChargePoint and Heidelberg rows ("active" too). The class-driven paths (roles, near-miss shape walk) ask for `power`/`running`/`battery_charging` and were never open. **Closure:** `says_a_link(entry)` — a `connectivity` binary sensor. Every name rule for the charge skips one (the rules keep the LAST match, so a link sensor after a real charging sensor would otherwise replace it), and `_reject_link_as_charging` at `apply_charger_discovery_guards` drops one any path still binds (with none SEM reads the charge from the power, as before). Zaptec binds "Charger mode" by its unique-id key as both state sensors; a build with its own plug and charging binaries keeps them. Its power rule refuses a sensor whose class or unit says something else (`_roles_dc`). A save setup made before the fix (no plug sensor, a link sensor as the charge) gets detection's state sensors at startup, or loses the link sensor even when a control does not match (`_holds_a_link_as_charging` in `_fill_state_sensors_of_own_save`). Not for the plug: a car's "charge cable" sensor (Tesla) is `connectivity` too. **Guard:** `tests/test_1142_zaptec_online_sensor.py` — the v0.8.7 layout and the pinned upstream one, the bound sensor read by the coordinator's reader, every platform in `_EV_CHARGER_PLATFORMS` with a link sensor named "charger" first and last (and its no-class twin, which the name rules do bind), a real charging sensor beside the link kept in either order, the guard alone, and the heal (fills, runs once, removes on a control mismatch, swaps a control, leaves a form save, another sensor and a user's charger). The rig's Zaptec pins now expect the brand rule; the near-miss pins run on a Go with "Charger mode" switched off. Ten mutants of the fix are killed. **Left open:** (1) the near-miss offer still picks the site limit when the brand rule cannot map a Go (#1141; closed, see class 71). (2) A Zaptec set up through the wizard before the fix had the online sensor prefilled as the charge; that save is the user's and keeps it (#1143; closed, below). (3) The plug side: openWB, V2C and the ChargePoint and Heidelberg rows bind any binary with "connect" in its name as the plug, a link sensor too. No such sensor is known on those brands, and a car's charge-cable sensor uses the class, so the plug is not guarded. Refs #1142 #1139 #1141 #1126.
**#1143, the wizard's save.** The heal above changed only setup's own save (no plug sensor). The wizard asked for both sensors, so its save counted as the user's and kept the link sensor three ways: as the user's own value in the device reference (`overrides`, since it differs from today's "Charger mode"), in the crawler's last answer (`found`) of a reference made before #1142 when "Charger mode" is off, and in the wizard's flat keys, which the reader and the builder read when the card has none. **Closure:** the class-71 rule, one more question: `hardware_detection.link_as_charging` joins `site_limit_controls` in `async_reconcile`'s refuse, so every start takes a link sensor out of the charge role whoever saved it — the crawler's answer, `found`, `overrides`, and the flat keys of `entry.data` and `entry.options`. A card with a plug sensor (the wizard's) then reads the charge the crawler finds today. A card with none is setup's own save: the charge role is `cleared`, so it has neither sensor and the #1142 heal (which runs after the refs step) still decides, with its control check (#1134); the next start folds what it gave. Un-clearing the plug instead would show the car through a stale control (the review caught it). `drop_refused` un-clears the current roles only when a current control goes, no longer on any drop. Sibling swept: the builder read a second charger's status sensor through `_cfg`, so a card left without one read the FIRST charger's car; it reads its own card now (`_own`, since #1149 `_cfg`, class 147). **Guard:** `tests/test_1143_wizard_link_sensor.py` — the v0.8.7 layout through the real setup step (a 2.1 store and a 2.2 reference, flat keys included, runs once), "Charger mode" off, a link as the plug kept, the real setup down to the adapter's status class, setup's own save in setup's order (both sensors, a stale control swapped, a missing control keeps them away), the drop with and without a plug, and a second charger with no status sensor. Seven mutants are killed. **Left open:** the builder still fell back to the primary's flat keys for a second charger's power, current control and current service (#1149, closed: class 147); a charger with no state sensor of its own read the fleet's in `build_charger_view` (#1150, closed: class 149); setup's own save that the refs give a plug (`refresh_found`) skipped the heal's control check (#1151, closed: class 72 third instance); a "cleared" charge role hides a later crawler answer until the user picks one (SEM reads the charge from the power: kept); the forms still offer a link sensor, and a pick is dropped at the next start with a log line, as #1144 does. With the refs step down nothing asks the question again: a wrong status read, not a write. Refs #1143 #1142 #1144.

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
`status_enum.py`, unless they are only on/off. **Left open:** the shared list still lacks words
core really stores — Blue Current `vehicle_detected`/`standby`, NRGkick `standby`, Tesla Wall
Connector `waiting_car`, the ABL pilot codes — so a Blue Current `vehicle_status` is still refused
except at `ready` (one that saved at `ready` is refused on a later reconfigure), and the reader
reads a car at `vehicle_detected` as gone. Each needs its meaning checked at the source before it
is mapped. Older and separate, closed by #1126 (class 145): `_discover_peblar` and
`_discover_easee` took a status sensor only with no device class, but core's Peblar `cp_state` is
`enum`, so registry discovery never bound it.
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
**Left open:** the dynamic fallback price (`fallback_price`, `default=0.30`, two sites) and the
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
**Second catch (#1026, PROD HA 2026.8, 28.09.2026) — caught at the WARNING stage, before
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
fix is to correct the picker, never to loosen the validator). **Second instance (#1032):** the charger start/stop
field offers `button` and the actuator presses it, but #824's control-entity check refused the domain
and filed an ERROR Repair on a healthy Wattpilot. Here the CHECK was wrong, not the picker — the
runtime accepts a button — so the check widened (`START_STOP_DOMAINS`). Guard:
`tests/test_1032_device_says_not_now.py::test_what_the_setup_offers_the_check_accepts`. **Sweep question:** for every entity
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
every-platform oracle with `min_`/`max_charging_current` first and last. **Left open:** a V2C
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
**Round 2 — the daily rows (#1177, PROD 23.10):** the energy integrator booked a dark read as 0 W. The
modbus inverter was dark 26 % of a noon hour; the solar row lost that share (9.86 kWh against 14.78 kWh
of held power that day). The battery and grid rows follow their meters, so they kept it, and home — the
balance — went DOWN in 23 hours on 15 days (0.5–2.4 kWh). The hybrid's AC yield counter could not fix
solar (it trails PV while the pack charges, class 28). **Closure:** `EnergyCalculator._integral_watts` —
a dark solar, grid or battery input (`*_unavailable`, every read dark) books its last live read for
`SENSOR_DARK_READ_GRACE_S`, the window its entity shows it, aged in UTC from the live read (a local
clock goes back an hour in autumn: the review measured a whole hour of import held); home books the
house SEM shows (`home_shown_w`, #1047); a held battery keeps its live flow shares
(`_battery_flows`), or a held sale is paid twice (#776). Steering never reads these. **Guard:**
`tests/test_1177_dark_read_integral.py` — each input, the grace edge, no renewal, a live 0, never-read,
the clock change, the cost, the battery's shares, the PROD hour (home never goes down; solar is the
PV), the real reader's flags, and an AST pin that `calculate_energy` reads none of the six fields off
`power`. **Left open:** past the grace a dark input still books 0 W (what it read is not known); the
daily flows and the solar savings built on them (**closed in round 4**); one dark unit of N, and one
dark half of a split grid pair (class 5 W6, **closed in round 3**).
**Round 3 — one dark unit of N (#1186, #1203):** with two inverters, two batteries or a grid meter
split into import and export sensors, the hold above ran only when EVERY read was dark. One dark unit
was 0 W in the published total and in the daily rows, while its own entity held its value (class 163),
so for the grace the unit and the total did not add up. A dark string's daily energy booked 0 W the
same way. **Closure:** `SensorReader._hold_dark_units` — each unit of a total read from two or more
sensors keeps its own last live read for the grace, on its own clock. `PowerReadings.held_w` is what
the held units add, in SEM's sign: a side is kept as read and turned with its total (`_negate_total`,
the one place a grid or battery total is turned over); each battery of a fleet is taken after its own
sign check, and a pair unit with one dark side puts back its last net in place of the live side, not on
top of it. An input with every read dark is left to its flag. `to_dict` and `_integral_watts` read it
through `shown_w`; `_hold_shown_home` holds the house while a unit is held (#1047's rule); a partly held
input counts as held for its flow shares. Each string keeps its last read for its daily energy
(`solar_power_per_string_held`); `calculate_power_flows` passes the strings on BEFORE its all-idle
return, because with every input dark each reads 0 W and the held strings were dropped there (the
one-Modbus-link home, #1177's PROD shape). Steering keeps the 0 W (#988, #1047). The #988 solar gate
and the #902 battery gate refute a TOTAL, but took away one read: with two inverters, or a two-sensor
battery, the refuted value was published as a reading; now every read goes unless a battery unit is
still read. Review (#1203): an input its flag holds stamps no unit, so a value a gate threw out is
never a last read; only a finite read is stamped; a held unit that adds under 1 W holds nothing (the
shown home froze for it); while the battery is held, the per-battery charge split takes the last live
shares (`_charging_units`), as its flow shares do.
**Guard:** `tests/test_1186_dark_unit_of_a_total.py` — every shape through the real reader (two
inverters, two batteries, a pair inside a fleet, one battery with two sensors, declared, manual,
config-path and discovered grid pairs, two grid meters): the grace edge, no renewal, never-read, a live
0, not a number, the unit's return, every unit dark, an unproven guess holds nothing, the sign after a
grid invert and a battery flip; `to_dict`; the rows; the shown home; the strings; both gates; and AST
pins that every total is turned over by `_negate_total` and every grid side read is a unit (each with a
probe); strings that ARE the dashboard's solar sources add up to the solar row through the real reader,
flow and energy calculators (one dark, past the grace, every unit dark); and the review edges (a value
either gate threw out, "nan"/"inf", a 0 W unit, the charge share). **Left open:** past the grace a dark
unit books 0 W; the strings read low for up to one more grace when a partly held input goes all dark,
or when the #988 gate refutes a 0 W total the strings also read (#1261).
**Round 4 — the splits by source (#1185):** the rows booked the held watts, but the flows were still
built from the reader's 0 W. So the daily flows (solar to home, to the battery, …), the solar savings
built on them, the car's daily split (#1046), a charge's origin with its source dark (#770), an
own-tariff device's grid share (#812), the EV and battery session splits, the flow entities and the
night audit's solar (#755) all lost the dark share; on the one-Modbus-link home every input reads 0 W
and the cycle's flows are empty. **Closure:** `EnergyCalculator._book_flows` — while an input is held
(`_integral_held`), the same allocator (`FlowCalculator.calculate_power_flows`, now static) runs again
on a copy of the readings with the booked watts in (the held input's and the shown house); the copy's
held units are in its totals, so it holds none of its own. With no input held, the cycle's own flows
are used as they are — also while the house alone is shown held (#1105 battery stop): a held house
beside live sources left live import in no flow (review). `calculate_energy` splits only by these;
the coordinator hands `book_flows` to the flow rows, both session splits, the flow entities and the
night audit, and `book_power` to the night audit and the battery session (its total and its split
come from the same read, and a dark blip is no idle cycle inside the grace). The health check and the
battery-night recorder (its own hold, #800) keep the raw flows: each checks them against the raw
power. Steering never read the flows. **Guard:** `tests/test_1185_dark_read_flows.py` — savings, flow
rows, every input dark, one unit of two, the grace edge, nothing held, a shown house alone, the copy's
units, steering keeps 0, the car's split, the charge origin, the tariff share (the held import over the
held house), the night audit, the battery session (one dark battery of two; a dark blip), the real
reader through the flow rows (they add up to the solar row), and AST pins: in `calculate_energy` the
first read of `power_flows` is `_book_flows`, bound back; in the cycle the raw flows go only to the
books, the health check and the night recorder (each with a probe). **Left open:** past the grace a
dark input still books 0 W; a held solar that went stale beside a live battery discharge still covers
the house in the split, so the discharge falls back to full savings and the house is paid twice for
up to the grace (#1269).

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
**Third instance — #1223, the crawler's kind markers.** `classify_kind` counted its markers with a
bare `in` over the whole vocabulary. The appliance marker `ram_` (computer memory) hit DSMR Reader's
`telegram_timestamp`, so a grid meter with 1380 installs was an appliance and its pair never reached
the roster. The same four letters hid EDL21 (a meter), a Stiebel Eltron heat pump and OpenTherm
(`program_`); `p1_` hit Qvantum's `gp1_pump_speed`, `ess_` hit `wireless_`.
**Closure:** one test for every marker list, `role_lexicon.says`: a marker that ENDS in `_` names a
whole segment and must also begin one. A stem (`inverter`, `purifier`) still finds a compound
(`pvinverter`, `airpurifier`) — the corpus is full of those, so a word rule for every marker was
measured and refused. `grid_` no longer finds `offgrid_`/`microgrid_` (no brand moved). Swept: the crawler (kind, electrical, vehicle and battery context) and the two
runtime tests in `hardware_detection.py` (`_speaks_vehicle`, the generator check on a charger).
DSMR Reader also declares no anchor word: a whole PAIRED_ROLES pair, named by the lexicon's own read
rules, is now an energy anchor (`_declares_a_whole_pair`). Measured on the offline corpus: DSMR
Reader gains its pair, EDL21 is no longer an appliance, OpenTherm and Stiebel Eltron gain name-only
rows; no brand loses a role. The Config card's one-click pair (#1224) needed both halves on one
device; a row with no device now belongs to its config entry. **Guard:**
`tests/test_1223_dsmr_reader_pair.py` — an oracle over every `word_` marker in every list, and an
AST lint that outside the lexicon a marker list is only ever an argument of `says_any`/`count_said`.
Refs #1223.

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
**Second instance — #1141, a site limit offered as one charger's control.** #804 drew the line for
Zaptec: the installation's `available_current` limits every charger on the site, and the owner sets
it to protect the main fuse (3x25 A on the reporting install). SEM never writes it, and the brand rule
`_discover_zaptec` refused it by name. The role reader did not. Two ways reached it when the brand
rule could not map a Go (its "Charger mode" sensor turned off): R1 in `_roles_pass` let the
companion's "live" current number replace the Go's stored setting — a companion is the site device,
so its current is always the site's — and the `ev_current_control` word list matched
`^available_current$`, so the roster ranked it FIRST for Zaptec and `charger_from_near_miss` wired it
on any device that held it (the #915 simulator fixture and its live GUI test pinned exactly that).
Setup and the add-charger step prefill from discovery, so one confirm saved it. **Closure:** R1 keeps
folding a companion into its charger and no longer takes any of its numbers; `available_current` moved
from the word list's `any` to its `not` (also as a suffix: `inst1_available_current`), and the Zaptec
roster row lost the key. An offline regeneration gave that row and the roles baseline; the only other
row it produced was cache drift and was left out. The hardware matrix, MULTI_CHARGER.md,
hardware_proof.md and the simulator's unmapped fixture (now the charger's own power and max current,
the installation as companion) say the same. **Guard:** `tests/test_1141_site_limit_never_control.py`
— the real Zaptec capture with "Charger mode" off through the report and discovery (no site limit
anywhere, start/stop offer, same controls with or without the limit); R1 for any brand (the
installation's number renamed to the plain control word `maximum_current`, under a domain no brand
knows); no offer names an entity on its own companion, entity ids inside JSON values included, on
the three shapes that have one (every capture as captured too, though none has a companion today);
the roster, the report's proposals and the word list; the old and new simulator shapes. Seven of
seven mutants (R1 back, word list back, roster back, each alone and together) are killed. **Left open:** the near-miss offer still skips the Go's own `charger_max_current`
(a config-category setting, #1032) while the brand rule drives it (#804); the offer starts and stops
instead — the two rules are kept apart on purpose until that is decided. Refs #1141 #804 #915 #1032.
**Third instance — #1144, the site limit kept in a save.** #1141 fixed the offer, not what it had
saved. A charger is stored as a device reference, and the reference keeps the crawler's last answer
(`found`) when a start cannot ask, so a role the crawler stopped giving is never forgotten: every start
resolved the site limit again. The same number also reached setup as the user's own value (a card
stored as a reference after #1141, a pick by hand), as the old Zaptec rule's `zaptec.limit_current`
service (before 25.08), and through the primary's old flat keys, which the builder reads when the card
has none. **Closure:** one question, `hardware_detection.site_limit_controls` (a number whose key,
unique id or id says `available_current` — `role_lexicon.SITE_CURRENT_KEY`, the word list's own
pattern — or a service whose current field is `available_current`, or whose target is such a number;
an entity platform's service is judged by its target only), asked at every layer:
`charger_refs.reconcile` drops the keys from the crawler's answer and from every ref — the card it
resolves to, and `found` and `overrides` alone, so a value a `cleared` role hides cannot come back; a
part keeps a value the card does not use; when the card's own control goes its current roles are
un-cleared so what the crawler finds today shows through, and a ref left half can be replaced (#1054);
a site limit does not vote for a card's device. `async_reconcile` drops the flat keys; the charger
builder refuses them before its gate; `wire_current_entity` refuses the number for any device (a load
too); the discovery choke point drops them from any offer, and the Zaptec rule's id fallback skips the
site limit and takes the next number. **Guard:** `tests/test_1144_saved_site_limit.py` — the old
offer's save (captured by the crawler at 3989b7eb, before #1141) through the real setup step and the
real setup on the Zaptec capture, down to what a start and a stop send; a user's pick, the old service
(stale value behind a clear included), the flat keys; the builder with the refs step down; PROD's and
HA-TEST's saved lists untouched. Fourteen mutants (each layer and each review fix removed) are killed.
**Left open:** `found` still keeps any role the crawler stopped giving, so each fix that removes a role
needs its own drop (#1147, closed: class 150 forgets it on a device seen whole); a charger with no current control logged an error at every start and its
load-management row kept an old control (#1148, fixed: class 153). Refs #1144 #1141 #804 #1054.

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

**Third instance — #1151, a plug sensor added past the control check.** The startup heal
(`_fill_state_sensors_of_own_save`, class 145) gives setup's own save a plug and charging sensor only
when its power and controls are what detection finds today (#1134): seeing the car puts them to work,
and a save from an older detection can hold the wrong ones (a Peblar's single-phase switch as
start/stop, #1035). The charger reference (#1054) is a second path to the same keys: every start merges
the crawler's answer into `found`, so when the crawler learned to read a plug (Peblar #1126, Zaptec
"Charger mode" #1142) the save got one with no check, and the heal skips a save that has a plug.
**Where it lives:** `charger_refs.reconcile` — the first start (a half card is completed by the
crawler), a writer's new card, and every later start (`refresh_found`); all three are covered by one
step. The builder's flat-key reads were assessed: a flat plug sensor is the wizard's, which the user
confirmed. **Closure:** `hold_new_state`, the last step of `reconcile`. When the card a charger ran on
before this start read no car (no state sensor, or only a link as the charge), a state sensor shows
only when every `STATE_MUST_MATCH` key of the card equals today's crawler answer — not `found`, which
keeps a control the crawler stopped giving. Otherwise the sensors go in the ref's own `held` list, the
card reads no car, and the heal decides; its fill is folded at the next start. `held` is asked again
every start, so a start that saw part of the device, or a control the user set right, lets go. A charger
that read the car (the forms ask for both sensors) is never held. The heal and the step read one list.
The #1143 link rule asks about the plug without the hold, so a hold never turns into a lasting clear.
**Guard:** `tests/test_1151_ref_plug_control_check.py` — the Zaptec capture through the real setup step
and the real heal (the cable lock swapped before the car is seen, a missing control keeps the sensors
away, matching controls get the plug at once); the issue's Peblar through core's test data and the
heal; a random check over two chargers, three starts, writers' edits and no legacy copy; an AST check
that the step is the last word on `refs`. Thirteen mutants are killed. **Left open:** a ref that already
got its plug at a start before this fix (2.2.0-beta.20) is not asked again: the store no longer shows
the plug was added (#1152, closed: class 151 asks setup's own save once).

**Fourth instance — #1224, half a grid pair one click away.** The #915 pair rule (`PAIRED_ROLES`)
withheld the button from a half whose partner the device lacks. When the device had both halves,
each row still had its own *Use this* button, and a click saved only that key. On a home whose
dashboard declares the pair (`stat_rate_from`/`to`), the saved half then outranked it on the
reader's ED path, so export read 0 W with one log line. A half whose partner was present but could
not take a button (not loaded, wrong unit) kept its own button too: the rule counted presence. The
review found two more: the card asks once per DOMAIN, so "this device" held two Tibber homes and one
click could pair home A's import with home B's export; and each runner-up had a button the unit and
load gate never judged. **Where it lives:** `hardware_detection.propose_roles_from_roster` (the pair
check, the gate), the card's Detected-hardware rows (`sem-config-card.js` `proposalRow`, first choice
and each runner-up), and `coordinator/sensor_reader.py::_read_from_energy_dashboard` (a half beside a
whole answer; the #589 sign check and `diag_grid_mode` asked the saved keys, not what was read).
The install form (`propose_energy_sources` rung 1) took each half's own first choice, so two meters
of one integration could fill it with two halves of two meters. Checked: the install step refuses
half a pair; the Sensor sources pickers and the options flow save
one key on purpose (a home that never exports sets import alone); the legacy reader already ignores
a half. **Closure:** `pair` maps each usable choice of a half to the other half's usable choices on
the SAME `device_id` (no device proves no pair). A first choice with none there gives the lead to the
first runner-up that has one, else the row is `pair_incomplete`. The install form fills a half only
with its partner from `pair`.
The card's `proposalWrite` saves the clicked entity plus the other half (the saved one when it is
one of those, else the first) in one `set_option` call. A row counts as "in use" only when the whole
write is saved, so a half saved by an older card is offered whole again. One half unusable → the
other gets `pair_blocked` and no button. Each runner-up takes `_gate_proposal`; a refused one keeps
its reason and gets no button. The reader sets a half aside when the Grid power pick, the dashboard's
pair, its meter sum or its combined sensor measures both directions, and reads the dashboard as if
the half were not saved; the sign check and the mode follow the source read this cycle. **Guard:**
`tests/test_1224_half_grid_pair.py` (the pair on each half, runner-ups, two meters of one domain, no
device, blocked partners, gated runner-ups, a saved half, the reader's ranks, the sign check, the
mode) and `dashboard/card/test/pair-write.test.js` (the write, the saved-partner rule, two meters,
"in use", and a source check that every button asks `proposalWrite`). **Left open:** a half saved by
an older card on a home with no whole dashboard answer is still read alone, export 0 W, and only the
log says so (#1238). The rows name roles by their ids (`grid_export_power`), as the whole
Detected-hardware view does.

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
(the held value is above the floor by construction for that long) needs a decision, not this
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
`unallocated_w`, which excludes the reclaim. **Open sibling:** the EV's *forecast
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
(`DISCHARGE_LIMIT_LOWER_DWELL_CYCLES`: *raise fast, lower slow*. First judged "not this class",
because the 250 W + 50 W band seemed to bound the up/down cycle. PROD showed it does not (#1173):
the band is 50 W wide at a step edge and a raise waited for nothing, so every burst of the house
was a write pair — **fixed**, see round 2 below),
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
**Round 2 (#1173) — the battery discharge limit.** PROD, 15.–23.10.2026: 48–143 limit writes a
night, mostly 750 ↔ 1000 W, one or two minutes apart. Under the EV clamp the limit is the house
load, and the house has bursts: a kettle or a hob for 10–60 s, a base load hovering 690–800 W across
the 750 W step, and the house figure's own one-cycle jump after SEM moved the pack (the grid meter
sees the change at once, the pack's power sensor a poll later). Up at once and down a minute later
made each burst two writes. **Closure:** `BatteryDecision.follows_load` marks a limit whose watts
ARE the house: the EV clamp and the #620 grid-funded clamp, unless the meter is at its peak limit
(`meter_wants_the_rise_now`: the house's import plus what the chargers were offered is over the
allowance, or the house figure is no measurement — asked of the meter itself, because with no
grid-funded load the house figure already equals the #1003 cover and nothing reads as "raised", and
the cover's own reserve gate says no where the clamp still rises) or the #1130 cars' share is in it.
For those, `_settled_rise_w` RAISES the limit only to a level the house has held: over the last
`DISCHARGE_LIMIT_FOLLOW_DWELL_CYCLES` (6, ~1 min) when that is two steps or more above, over the
last `DISCHARGE_LIMIT_ONE_STEP_DWELL_CYCLES` (30, ~5 min) when it is one step (the run's lowest
house, so a spike at the end does not set it). While it waits the grid covers the rest of the
house; the pack gets no more room than before. Lowering keeps #900's rule for every limit: it is the
side that keeps the pack out of the car (review: a first cut that also made falls wait let the pack
give up to 900 W more than the house for five minutes). A target (the #879 hold, its cover, the
#1120 blind release, a cover owed, the cars' share) rises at once (class 59 — a limit is not a
preference). The first clamp after NORMAL still goes out at once (#1066), and so does the first
one out of a target: the wait applies only while the limit in force is a house clamp too
(`_limit_follows`, set only when the write landed). The cycles of a rise
survive a failed write (tried again next cycle) and, after a rise, only the cycles still above the
new limit stay in it. A 0 W limit is a limit: `or -1.0` had read it as none (class 105). The real
actuator, run offline over six PROD nights' house figure (15.–22.10): 23–45 writes a night,
against 93–143 for the old rule on the same figure.
**Guard:** `tests/test_1173_house_limit_waits.py` — a one-cycle kettle writes nothing and was two
writes before; a burst shorter than the wait and a run broken by one cycle write nothing; a big
rise lands after the short wait at the held level, a small first cycle does not delay it, a second
rise counts the cycles already above it, a failed write is tried again the next cycle; a one-step
rise and a hover across the step wait the long one; a fall lands after the same six cycles as
before, also when it starts one step down; targets, a 0 W limit's target, the first clamp and the
first clamp out of the hold or a cover rise at once (also after a failed write), a burst over a 0 W
clamp waits; observer cycles count for nothing; the decider sets the flag on exactly the house
clamps (not with the meter over — 0, 500 and 3000 W allowances under a 3.8 kW house, the cars'
offer, a figure that is no measurement, a pack at its reserve, the grid-funded clamp over but not
raised — nor the cars' share, the hold, its cover or the blind release), a retried stop keeps it,
and a 3.8 kW house over a 0 W allowance is covered on the first cycle end to end; over a synthetic
ten-hour night at most a third of the old rule's writes, and an oracle that no rise or fall is later
than its wait (a frozen limit fails it). Mutants: ignoring the flag fails 15 tests, dropping the
meter check 8, treating every limit in force as a house clamp 4. Swept: the export
guard (#955) already holds both ways (120 s / 300 s); charge pacing (#820) has a deadband both ways
and a cap from the plan, not the house; the forced charge under the meter limit (#1069) must lower
at once (class 59), so its raise wait is the only one it can have (assessed).
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
**Left open:** (1) the clocks are in-memory on the per-charger reconciler, so an HA restart
or an options reload costs one free contactor operation — the #461 stability epochs ARE persisted
(class 7) and these are not. (2) The floors are module constants: a user with a contactor rated
for faster switching cannot lower them, and a KEBA install acquires them (its `enable`/`disable`
IS a relay) with no opt-out. (3) The hold is published — `charger_<id>_anticycle_hold` /
`_hold_s`, `per_charger_anticycle` on the charging-state sensor, `anticycle` in the diagnostics
war snapshot — but no CARD renders it yet; the "holding on for another 2 min — anti-cycle" line
#940 asks for needs a card change plus its translation keys. (4) Whether a switch-only charger
should be offered the amp-shaped modes at all is still open. (5) Observer mode stamps the clocks
for commands `ControllableDevice.send` withholds — the same pre-existing shape as `_last_disable_at`,
so an observer rig's holds are real while its writes are not. (6) (#1173) A pack at its own
lowest level cannot discharge, yet its limit still follows the house (rarer now, not gone): SEM does
not know the inverter's own floor, and its reserve is not always that number (#1179).
Refs #940 #939 #763 #536 #627 #688 #392 #804 #1173 #1179 #900.

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
warning in `reconcile_and_apply` — log-only, and a real sibling (see Left open).
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
**Left open:** (1) The #548 stop-not-taking sibling: a box that ignores SEM's stop *without an
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
install-wide clear was class 84 (4), closed by #1124: a kept write clears only the entity it proved. **Left open:** (1) a refused cap is
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
**Left open (found in #940's review, all pre-existing, none a gate on it):**
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
**Left open:** the stall-to-full path in `_update_ev_intelligence` ("0 W for 3 min under a
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
**Left open:** (1) #823 charger failsafe-suspected: its clear is an `ActionKind` emitted only
while `_failsafe_reported` (in memory) and a learned interval hold, so a fresh reconciler can never
produce it. What proves the box healthy without the learned interval is a decision, not a sweep —
and an action-mediated clear is invisible to the AST guard. (2) A Repair keyed on an entity the new
config no longer writes (a platform switch, a renamed entity) has no owner left to clear it at all:
the orphan sweep the heat-pump and hot-water Repairs have, not generalized.
**Closed for chargers by #1139:** a removed charger's "control entity is not working" Repair stayed
in Settings forever (@OddmarDam; HA had renamed its ids under it). Setup now runs
`clear_orphan_charger_repairs` once the chargers are registered: a control-entity Repair outside the
listed `(charger, entity)` pairs, and every other per-charger Repair of an unlisted charger, goes.
`charger_actuation_failed` stays out — a load driven by current files it under its own id, and the
sweep knows no load ids. Guard: `tests/test_1139_orphan_charger_repairs.py` files each Repair of
`PER_CHARGER_REPAIRS` through its real raiser; each one must be swept for a removed charger and kept
for a listed one, or sit in `NOT_SWEPT` with its reason. A call-site test pins the setup call in the
registration block, outside any `if`. The late-found primary `ev_charger` is kept while the retry
can still build it.
**Closed for the rest by #1140:** change the grid sensor, and the old one's "unavailable" Repair
stayed for good. `sensor_unavailable`, `sensor_stale`, `battery_control_write_not_taken`,
`battery_force_discharge_unsupported` and `charger_actuation_failed` — plus the non-persistent #845
and #827 battery watches, which an options reload keeps — are swept by
`SEMCoordinator._sweep_orphan_repairs` → `clear_orphan_repairs`. It runs in the cycle, not at setup,
because only the reader knows what it reads (Energy Dashboard picks are found at run time) and loads
are found 35 s after setup: the first sweep waits for HA running, the Energy Dashboard sensors found,
and 300 s of reads, then repeats hourly for an owner that leaves mid-run. The owners: every entity
`_read_sensor` was asked for in the window (`SensorReader.entities_read`), plus a battery SOC sensor
detection found but could not read (it is the one SEM reads once it answers); every battery entity the
config names or an adapter holds; every device registered for control, every saved charger, and the
late-found primary. The sensor kind is left alone when the window had fewer than 3 reads or the Energy
Dashboard could not be read (SEM then reads its fallback keys). After a sweep the reader drops its
outage memos for what it cleared (`forget_unread`), so a sensor put back while still down is filed
again. Sibling: a dropped split-grid pick now takes its `sensor_unavailable` Repair with it, not only
`sensor_stale` (`_forget_split_grid_picks`); a rediscovery, which mostly picks the same meters, and a
declared pair that names the guessed meters keep it. Guard: `tests/test_1140_orphan_repairs.py` scans
every `raise_*` whose issue id is built from its own parameter (keyword or positional, direct or
through a local, sync or async — a twin pins each form) and requires a `KEYED` answer to "what clears
it once that thing leaves?"; each #1140 answer is filed through its real raiser and must go for an
unused owner and stay for a used one; a call-site test pins the sweep beside the cycle's first
`read_power`, outside any `if`. (3) The #845 mode watch
is built on the first cycle, before any battery adapter exists, so on an auto-detected platform it
has no expectation and stays publish-only for its whole life: the #845 Repair is dormant everywhere
but an explicit `huawei` platform (the #919 shape — a question asked before the thing it asks about
exists). Turning it on raises a new Repair on live installs: a decision, not a sweep. (4) #915's
clear is install-wide within the primary adapter: any reflected write clears every raised write
Repair, including one for another entity that still ignores writes (class 83's shape; pre-existing).
**Closed by #1124** (class 146): a kept write clears only the entity it proved; the select's verdict
carries its own entity, and a sent flip that lands proves the select in a fresh lifetime.
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
**Left open:** (1) A climate-only heat pump (the `SetpointDevice` climate boost, normal +
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
**Left open:** (0) This surface shares ONE issue id with the write path (#462), which is why the
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
from the same sun authority `is_night_mode` uses. **Open residual (a product call, not a sweep):** the window is
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
captures of `feature/hardware-wave` only V2C's answer changes. **Left open:** Blue Current's
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
satisfies it. **Open:** the guard that would end this class is a coverage rule, not a
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
**Left open:** the HA config-entry `options` API returns only one charger's flat `ev_*`
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
**Left open:** (1) the #878 arm `_assist_blocked_why` still does not carry. `battery_assist_
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
time, not inferring it from storage — left open.

**The guard is flow-scoped — say so.** The AST lint parses `config_flow.py` only, and matches
`X.get("K") or Y.get("K")` with constant keys and inline receivers. It does not see variable keys,
subscripts, a receiver hoisted into a local, or any other file. Three known live siblings outside
its reach, **left open**: `coordinator.py:5155`/`:8932` read `_cfg.get("daily_ev_target") or
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
**Left open:** (1) `ev_phases` has no **provenance** — class 40's own prescribed closure. SEM
cannot tell "the owner said 3" from "nobody said, so 3", so the Repair words itself around the
difference instead of stating it. (2) The verdict is a notice, not an action: SEM keeps converting
with the refuted nameplate until a human changes the setting. Auto-adopting downward is arguably
safe and upward certainly is not, so the asymmetry needs a decision, not a patch. (3) The refusal
evidence does not decay, so reverting a corrected `ev_phases` re-accuses from the stored samples
the same cycle — right, but worth a deliberate look. (4) No orphan sweep: deleting a charger row
leaves its Repair until restart, which every per-charger repair in SEM shares. **Closed by #1139**
(class 84): setup clears the Repairs of a charger it no longer lists. (5) `implausible`
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
**Open residuals, all one shape — the floor is promised and may not be delivered, and
nothing says so at runtime:** (1) `#900`'s `DISCHARGE_LIMIT_LOWER_DWELL_CYCLES` makes LOWERING wait
six cycles and resets the streak on every raise, so an input that blips once a minute (the #818
motivation names 8-15 % of cycles on a Huawei modbus) pins the limit at the release value and the
#879 hold never comes back. Safe direction, dead feature; the seam that would fix it is a
`follows_load` flag on `BatteryDecision` read by `actuate_battery` — a change to the actuator's
contract, so it is a call, not a sweep. (#1173 added that flag for the house clamps, whose rises now
wait; the hold is a target and still lowers after six cycles, so this residual stands.) (2) The #531 fleet split divides the cover by the battery
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
**Open residuals.** (1) `HuaweiChargeAdapter.start_forced_charge` answers the SAME
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
**Open residual.** The grid-funded `CHARGE_AT_AMPS` decisions carry the same `0.0`, so the
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
**Open residual.** The stable channel now offers v2.0.0 — a month and 41 betas old. This
keeps it reachable; only cutting 2.1.0 makes it current. Nothing already watched reports a
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
**Open residuals:** (1) `_session_stops` is incremented at exactly ONE site, and it is not
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
A test install (#1027, v2.1.0) watched a KEBA that a second SEM controls; removal sent
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
**Left open:** (1) **The records the bug already wrote.** An observing rig booked a park on
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
needs a decision, not a sweep.
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
**Left open:** (1) No evidence, no drop: an Equalizer beside an Easee whose status AND session
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
**Left open:** (1) a charger SAVED before this fix keeps its binding — detection re-runs only
while no charger is configured. A Peblar set up earlier keeps the single-phase switch; an OCPP
charge point left at the default name "charger" may hold `switch.charger_availability` as its
start/stop, which stops a charge by taking the connector out of service. (2) A unit whose own
names match no rule at all is no longer a charger: if openWB's loadpoint publishes German entity
names under an English "Chargepoint" device name, it matched only through "charg" before (with a
guessed status sensor) and is now left to the prober and the near-miss offer. (3) Peblar's state
sensor is `device_class: enum` and `_discover_peblar` asked for none, so no connected/charging
sensor was bound — class 145, closed by #1126. (4) The inverter-side `_DISCHARGE_CONTROL_PATTERNS` read whole
ids too, some by brand name on purpose. (5) The glob matrix (`EV_INTEGRATION_PATTERNS`) is a
config-flow prefill and was not changed. (6) An owner who renamed the TOTAL power sensor leaves
the phase leg bound: the sum is found by name. (7) Ids in other languages: a German or Dutch
Peblar gets no start/stop (its switch is not called "charge"; before, it got the single-phase
switch), and a phase named `fase_3`/`fas_3` is not seen as one phase. Reading Peblar's unique-id
keys (`…_charge`, `…_power_total`) would fix both — brand code, so not here. (8) Seen on HA's own
entity names, older than this class: Wallbox binds `…_maximum_icp_current`, the site's grid limit,
as its current control; V2C was #1034 (classes 56 and 89, closed). Class 114's residual (2) loses its `carport` case:
go-e MQTT's `car` now reads the own name.
**Second instance — the runtime, not the setup (#976, 02.10):** `charger_adapters/wallbox.py::_looks_like_wallbox` chose the ADAPTER by `"wallbox" in entity_id`. "Wallbox" is what German owners call any wall charger; @bgthb's Huawei on OCPP is a charge point named "wallbox", so its `switch.wallbox_charge_control` made it a Wallbox. That adapter turns its pause switch on before every current write; on OCPP that turn_on is a RemoteStartTransaction, so every write sent a start the charging box refused ("Rejected", one notification each). Alfen (`alfen_wallbox`) and GARO (`garo_wallbox`) carry the word too. Closure: the adapter asks the registry PLATFORM (or the service domain), never the id. Guard: `tests/test_976_named_wallbox.py` — the reporter's charger through the reconciler, every other charger platform under a device named "wallbox", a Wallbox renamed "Garage", and an AST check that no module in `charger_adapters/` tests a brand word with `in` (a literal word only; `any(…)`, `.find()` or a regex would pass it). Left open: `_looks_like_wallbox` and `_discover_pause_switch` read `charger_current_entity`, a name the real device does not have (it is `current_entity_id`), so a Wallbox configured with its current number alone still gets the generic adapter — unchanged here on purpose, since the Wallbox adapter then turns the pause switch on (a cloud call) before every write. Outside the charger path: `features/load_device_discovery.py` (keba / go-e / easee in ids), `utils/helpers.py` ("keba" picks kW), `coordinator/repair_issues.py` ("keba" + "failsafe"). Decided here: Wallbox hardware behind another integration (the MQTT bridge of #984/#985, Modbus) now runs the generic adapter. With its start/stop switch configured, `stop_session` turns it off on every stop and ENABLE turns it on when off; the Wallbox adapter only added a turn_on before every write.
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
**Left open:** (1) GoodWe forced charge (`GoodWeChargeAdapter`) writes "Eco Charge" and
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
**Left open:** (1) the #536 ENABLE fires on `off`, which on OCPP is also a box that REFUSES a start (Finishing after SEM's own RemoteStop, Preparing while it waits for authorisation): 5 refused starts, then one per 300 s — about 12 notices an hour while SEM wants to charge. Tied to the open question whether a RemoteStop is the right OCPP pause. (2) `WallboxAdapter.command_current` / `command_max` still turn the pause switch on before every write (a cloud resume call per write on a real Wallbox), and `command_idle` / `command_disable` turn it off a second time after `stop_session` did (the #894 shape). (3) ~~`_discover_v2c` adopts V2C's `paused` switch as start/stop, where on means paused~~ — closed by class 118 (#1042): the "already on" read is now "already running", which is `off` on that switch.
Refs #976 #536 #804.

### 118. A switch read by its state, not by what its name says "on" means — GUARDED
**Symptom:** V2C Trydan: on a box given its session pause as start/stop, every start SEM sent paused it and every stop resumed it (#1042); on one given the modulation pause (below), SEM's stop never stopped the charge. Home Assistant's V2C session switch is "Pause session" (key `paused`), on while paused; core's `turn_on` calls `evse.pause()`. Nothing errors: the switch takes each command.
**Root shape:** every start/stop write spelled `turn_on` to start and `turn_off` to stop, and every read took `on` as running. That holds for a switch named for the charge ("Charging enabled", "Charge control", Wallbox's "Pause/resume", on while it charges), not for one named for the pause. Second shape in the same rule: `_discover_v2c` took the LAST switch with "pause" in its name, and HA registers "Pause dynamic control modulation" (key `pause_dynamic`, which pauses the box's solar modulation, not the charge) after the session pause — so the old rule most likely saved that one on every V2C.
**Where it lives:** `CurrentControlDevice.start_session`, `stop_session`, `park_off`, `release_to_user`, `_start_switch_reads_running` (was `_start_switch_reads_on`); `ChargerAdapter.enable_state`, `ensure_enabled`; `WallboxAdapter._toggle_pause_switch`; `_discover_v2c`; the saved bindings no detection fix reaches.
**Closure:** one rule, `consts/devices.names_a_charge_pause`: "pause"/"paused" as a whole word and no word but session/charge/charger/charging/ev/evse/car — so `pause_resume`, `pause_dynamic`, `not_paused` and a device name in front are not one. `utils/switch_sense.on_means_paused` applies it to the name the INTEGRATION gave the switch: HA's translation key (the same in every language; a German V2C's id says `vorgang_pausieren`, its key `paused`), else `original_name` when `has_entity_name` says it is the entity's own. A template switch or helper the owner made keeps "on = start". Every write asks `switch_service(run=…)`, every read `reads_running`; the sense is read at run time, so no saved config changes. `_discover_v2c` binds on the same name by the same rule (`_pauses_the_charge`), so a switch the run time cannot read is not bound and the #627 Repair says so. The builders' `wire_current_entity` swaps a saved switch that pauses something else (`names_another_pause`, never a pause/resume toggle) for the one pause of the charge on the same device (`charge_pause_twin`; keys only, no guess between two) and logs it. The diagnostics dump shows `start_stop_on_means_paused`.
**Guard:** `tests/test_1042_pause_switch.py` — a fake Trydan whose switch pauses on `turn_on`, through start, stop, park, hand-back, the adapter and the reconciler; Wallbox, NRGkick and OCPP switches and an owner's template unchanged; detection over every order of HA's five V2C switches, German ids, rows without keys, and the old rule run on the same rows; the saved modulation pause swapped, and kept when there is no twin, two, or only one on another device; an AST check that no function naming the start/stop switch (attribute, variable, parameter, or the config key fetched) spells `turn_on`/`turn_off`/`on`/`off`/`STATE_ON`/`SERVICE_TURN_ON` itself, which catches the pre-fix shapes. Thirteen mutants of the fix are killed. **Sweep question:** when SEM writes on or off to a switch, does the switch's name say on is the thing SEM wants?
**Left open:** (1) the swap is at run time; the saved config still names the modulation pause, and the config screen shows it. (2) An integration with no translation key and no own name, or one whose names are not English (`…_pausieren`), is read as on-while-charging. (3) OpenEVSE's "Sleep mode" switch is on while stopped too, under a word that is not "pause"; SEM does not detect it as start/stop. (4) The Repair text "enable switch will not stay on" is wrong in words for a pause switch (it will not stay off). (5) Load switches (`features/load_management.py`) are not read through this rule. (6) A V2C healed by the swap may still have its modulation paused from SEM's old "start"; SEM no longer touches that switch, also not on removal. (7) No test pins that the builders set the saved start/stop before `wire_current_entity` (the Wattpilot wiring relies on the same order). (8) The AST guard misses a switch passed to a helper under another name, a fetch through a call other than `.get`, and the `toggle` service.
Refs #1042 #976 #1034 #1035.

### 119. A ratio whose top counts part of what its bottom counts — GUARDED
**Symptom:** `sensor.sem_battery_measured_capacity_kwh` read 7.89 kWh on a 10 kWh pack, drift −21.1 % over 33 nights (#1045). The pack was fine. Nothing errors; the figure looks like wear.
**Root shape:** kWh per percent is energy over SOC span. The SOC span counts everything that left the pack (house, car, grid) and is net of any charge taken in the same night. The energy was `drain_kwh`, the house's share only, and gross. A night with EV assist or battery export read LOW; a night that also charged read HIGH, which sizes every budget against a pack that is not there. Each side is right for its own reader: `drain_kwh` is exactly what the overnight need wants.
**Where it lives:** `measured_capacity._qualifying_ratios` (the instance); `battery_night.BatteryNightTracker` (now records `charge_kwh`, including a charge seen only as an SOC rise across a restart hole; a hole that ends after dawn now ends the SOC span too, where before its energy joined the night and its SOC did not); `night_backfill` records carry no SOC, so they never reach the ratio. Any other "energy per percent" figure: `ev_taper_detector.on_session_end` (left below).
**Closure:** the energy is drain + assist + export − charge, the same flows the span counts. A night whose charge is more than 10 % of what left (`MAX_NIGHT_CHARGE_SHARE`, with a 0.25 kWh noise floor) is not used: its net is a small difference of two lossy conversions. A record sealed before the charge was counted (`charge_kwh` absent or None, also the night in flight at upgrade) does not know its charge: it is read as before, house share only, and not used when assist + export are more than 10 % of what left. `expected_overnight_need` keeps the house's share.
**Guard:** `tests/test_1045_capacity_counts_every_outflow.py` — assist, export, both, EV-only and mostly-assist nights read the real pack; a small charge and short-night noise are subtracted, a large charge refuses the night; old-format records with and without assist, including an export night that charged back; a charge hidden in a restart hole; a hole that ends after dawn; noise larger than a tiny night; a night restored from an old store says unknown; the need is pinned to the house's share; real nights through the real recorder into the real reader; the coordinator hands the pack's charge power to the recorder. Thirteen mutants of the fix are killed.
**Sweep question:** for every ratio SEM computes, does the top count the same flows, over the same window, as the bottom?
**Left open:** (1) `ev_taper_detector.on_session_end`, display-only (per-charger `battery_health`): the full-cycle method sets the estimate to the session's energy for any session that tapers to full, so a 50→100 % session reports half the pack; the partial-cycle method takes `_session_start_soc` from the first SOC reading after the last reset, and `get_virtual_soc` runs while the car is away, so the SOC side can start at unplug while the energy side starts at plug-in; it also divides wall (AC) energy by the car's SOC, about 10 % high. Not verified on a live install. (2) Energy and charge bridged across a restart hole are made from the configured nameplate, so a wrong nameplate skews that night's ratio. (3) The budget uses a measured size above the nameplate as is; a pack does not grow, so a cap at the nameplate would be a second guard. A product call. (4) Switch-over: an old record's charge is unknown. Old nights that drained and then took a grid top-up read high, on develop too; old assist nights used to read low and could hide them, and are now skipped. Until new nights fill the window, an install with many night top-ups can read higher than develop did (review: 15 vs 10 kWh in one mix). Not using old records at all removes that, but resets every install's figure for five nights and needs the old-shape fixtures in 15 tests changed.
Refs #1045 #778 #800.

**Round 2 (#1046) — a flow over a meter, and over another day.** The EV card's daily "Solar Share" (`energy_ev_solar_percentage`) read 49 % on PROD for a day the session record called 89 % (6.3 kWh). It was `solar_to_ev` (a flow) over `daily_ev` (the charger's metered kWh). The flow allocator leaves a cycle's draw unassigned when the inverter reads dark, so the meter counts cycles no flow does. #1024 had fixed the session record (it scales the flow split to the meter); the day's share was a second reader that never asked. The window was off too: `daily_ev` rolls at the Charge-by time (default 07:00; midnight when chargers disagree), the flow layer's totals at midnight. The first cut took the split of the calendar flows; review caught that a night charge on grid then pulls the share down until midnight (31 % beside "Today 5 kWh" all on sun).
**Where it lives:** `EnergyAssistant.analyze` (the instance), the "mostly from grid" tip and the optimization score (same ratio, **swept**), the battery charge session's `solar_share_pct` — `solar_to_battery` over the measured charge (**swept**), and the battery card's "% solar" under "Charge today" — `flow_solar_to_battery_energy` over `daily_battery_charge_energy` (**swept**, `sem-battery-card.js`). Already right: the EV session and the lifetime shares (totals scaled from the same split), the card's month totals (weighted by those sessions), autarky (flows over flows), `_file_battery_charge_origin` and the discharge savings (flow split onto the increment).
**Closure:** `utils.helpers.solar_share_pct(solar, *others)` and its card twin `util/solar-share.js` — solar over the sum of the flows into the same thing; None when they hold nothing (the sensor reads 0 as before, the tip does not fire, the score gives no EV points). The car's flows are also kept on the EV day: `EnergyCalculator` books `solar_to_ev`/`grid_to_ev`/`battery_to_ev` into daily rows keyed by the same `ev_day` as `daily_ev` (`ev_flow_*`; the `ev_` prefix keeps them through the midnight sweep; persisted with the daily rows), and `ev_day_flows()` reads them on the key `daily_ev` was read from this cycle. The EV day the rows were first booked on began before them, so `ev_day_flows()` says None for it (`ev_flow_since`, persisted in `CALCULATOR_STATE_KEYS`) and the coordinator reads the calendar flows for that one day instead of 0 % (review 2). `battery_to_ev` now reaches the assistant, so a battery-fed car is not read as all solar.
**Guard:** `tests/test_1046_ev_daily_solar_share.py` — the PROD shape (sun, dark, grid) through the real allocator, integrator and `session_energy.step`: the card equals the session (88.2 %, was 47.6 %); a night (battery at 23:30, grid at 02:00) then a day (sun, then dark) through the real `EnergyCalculator`: the night's rows survive midnight, the day reads 100 % (calendar split 45 %, old 50 %), the rows survive a restart; a read after 07:00 keeps the day `daily_ev` was read on; the upgrade day says None and the marker survives a restart; the real cycle publishes the EV day's split, and on the upgrade day the calendar split; the tip and score on the same split; the battery session through the real allocator (75 %, was 42.9 %; a dark cycle keeps the share). An AST lint over the package: a `/` or `/=` with solar on top and a metered total below (`daily_ev`, `ev_kwh`, `energy_kwh`, `total`, `charge`, `metered`) fails unless the function is on a three-entry list whose totals are themselves the scaled split, each pinned to one such division. It cannot see a value renamed first, or a multiply by a reciprocal. `dashboard/card/test/solar-share.test.js` pins the card helper; a line lint over `dashboard/card/src` fails on `solar… / …daily|charge|total…` (shown to catch the old battery card line).
**Left open:** (1) The battery session's `energy_kwh` and `cost` still use the measured charge and the unscaled grid flow; only its share changed. (2) The battery card's share is still the calendar day; so is `daily_battery_charge_energy` beside it, so the window matches. (3) Per-charger daily share does not exist; a multi-charger card shows the fleet share on each tile. (4) On the upgrade day the share is the calendar split (round 1's number), so a night charge before the Charge-by time still counts in it that day.
Refs #1046 #1024.

### 120. A part taken away from a whole that never held it — who is inside the total, decided by each reader — GUARDED
**Symptom:** `sensor.sem_daily_true_baseload_energy` read −49.69 kWh against 6.29 kWh of home after a 49 kWh night charge, and `true_baseload_power` fell by the charging power while the car charged (#1044, RienduPre, 2.1, Growatt + Wallbox Pulsar). Nothing errors; the number is negative by the size of the car.
**Root shape:** `home` is solar + import + discharge − ev − export − charge, so the car is already out of it. SEM's chargers are also devices in the surplus controller, and the baseload took away every device in it — the car a second time. #872 had hit the same rule for the partition check and fixed it there alone, by device TYPE (`current_control`); the baseload (#773) was a second reader that never asked. The type rule was also wrong: a load the user put under current control is a `CurrentControlDevice` too, and its draw is not in `ev`.
**Where it lives:** every reader that adds devices up against `home`: the filing seam's controlled-loads mirror (`_file_device_energy`, the instance), the W twin in the cycle (the instance), `home_member_totals` for the partition check (#872, **swept** — so a current-controlled load is a member again), and the baseload drift check, which named a charger as the day's suspect and judged days sealed under the old rule (**swept**).
**Closure:** the sensor reader says what `ev_power` was read from (`PowerReadings.ev_power_entities`, the per-charger sensors summed, or `ev_power_fleet_entity`, one fleet sensor that stands for every charger). `health_check.chargers_outside_home` keeps SEM's chargers (`sem_ev_chargers`: the dict and the late-found `_ev_device`) that this read covers; `home_members(devices, chargers)` leaves exactly those out, by identity. A charger the reader never read — a second box with no sensor of its own, a late-found box whose sensor was not handed over — is still inside `home` and is still taken away once (the review's catch: identity alone would have left its car inside the baseload). The charger keeps its ledger row. A sealed day carries `home_members_only` when its whole day was booked under the rule (`_home_members_since`, persisted and in `CALCULATOR_STATE_KEYS`; the upgrade day is not). On an install with a charger outside `home`, a day without it is a gap, and such a charger is never named as the mover.
**Guard:** `tests/test_1044_ev_not_subtracted_twice.py` — real `CurrentControlDevice` chargers and a current-controlled load through the real seam into a real calculator (his day, the late-found shape, a charger never read, an estimated charger), the real cycle with a charger drawing 7 kW for the W twin (through the fleet sensor and through the per-charger sum), each with a twin that shows the old number; the reader's record of what it summed; the drift check's suspect and gaps; the stamp across an upgrade, a restart and junk; AST checks that every coordinator function that books the mirror, writes the W twin or calls `home_member_totals` asks both `chargers_outside_home` and `home_members`, and that every `readings.ev_power` write in `sensor_reader` says what it read. Eleven mutants of the fix are killed.
**Sweep question:** for every total SEM takes something away from, does the total hold the thing taken away? And is that decided in one place?
**Left open:** (1) **Fixed (#1125):** the late-found charger (`_retry_ev_device_setup`) handed its sensors to the reader through a hand-typed `key_map` with no power sensor, so without a fleet sensor `ev_power` missed its draw and the car counted as house load. It now hands them through the reader's own start-up parse (`SensorReader.adopt_late_charger`, class 24); guard `tests/test_1125_late_charger_power.py`. **Fixed (#1136):** the late builder is gone. The retry saves the find as setup saves its own; the reload builds it with setup's one builder, so the gate, load management and the energy counter are the same. (2) The upgrade day keeps the old number until midnight: the mirror already holds the kWh the charger booked that morning. (3) A downgrade and a later re-upgrade keep the old start day, so the re-upgrade day is sealed clean. (4) While a late-found charger is not yet registered, or after a charger is removed, old days count again and can raise one false drift warning. (5) The "dict plus `_ev_device`" walk is still written out in four other places in `coordinator.py`. (6) The rule asks what `ev_power` read; the daily home row, when it follows the meters, takes out the calendar-day EV row, which EV energy counters can raise. A charger whose counter is in that list but whose power `ev_power` does not read (an Energy Dashboard EV device with no power sensor; case 1 is fixed) is then out of daily home and still booked in the mirror: the kWh baseload can go negative again there. The counter model itself says it assumes `ev_power` already holds every charger (`configure_ev_counters`). (7) The Energy Dashboard fleet sensor is the first device whose name looks like a charger (`_extract_ev_from_devices`); it is taken to stand for every charger.
Refs #1044 #872 #773 #1045 #1125.

**Round 2 (#1191) — a battery sale taken away from solar.** Self-consumption fell to 0 % when the battery sold to the grid, and the health check then said the formula was wrong (found while fixing #1172). The rate was (solar − export) ÷ solar. The rate is meant to count solar into the home, the car or the pack as used on site; only solar sent straight to the grid is solar's export. The export also holds the pack's sale: a morning with 1 kW of sun and a 4 kW sale read −350 %, the clamp held 0 % and its record fed the #660 check.
**Where it lives:** `EnergyCalculator.calculate_performance` (the instance). Swept, all **fixed**: CO2 avoided for the day, year and lifetime (`calculate_costs`); the live-intensity correction per cycle (#1088); the day-end snapshot that feeds the ROI (`_snapshot_daily_costs`); the assistant's "% of solar exported" tip and its score (`EnergyAssistant.analyze`); the night audit of the plan's solar share (`_record_demand_outcomes` → `observe_totals`, #755); and a second copy of the rate in `sensor.py`, from live watts, which the cycle never left empty (**removed**).
**Closure:** each cycle books the battery's part of its export beside `grid_export`, never instead of it: `grid_export_battery`, the `battery_to_grid` flow, never more than the export (`utils.helpers.battery_export_part`). The allocator serves solar first, so export the flows left unassigned stays solar's, as before. A dark pack uses its held flows and a dark meter the split of its last live read (#1177). When the export meter corrects its row (#628), the battery row keeps its share (`_ROWS_BESIDE`): the flows give the split, the meter the size. A correction is split as what was added since the last one (`beside_mark`, set with the meter's anchor), so an afternoon's drift does not move the morning's sale. Every reader takes `utils.helpers.solar_export(export, battery part)` away from solar. With no flows, or no sale, every number is as before. Diagnostics show the part (`grid_export_battery_kwh`).
**Guard:** `tests/test_1191_battery_sale_self_consumption.py` — the reported morning through the real allocator and calculator (50 %, was 0 % with the clamp engaged), with a twin on the old rule; no sale, no flows, unassigned export, a charging pack and the two-argument path read as before; a dark pack and a dark meter, held and past its grace; a meter 10 % ahead and 10 % behind, in every period; an afternoon's drift leaves the morning's sale; a counter reset starts a new window; a skipped cycle's read keeps its part; every period, a gap cycle and the lifetime row; each swept reader with its old-rule twin; the coordinator hands the battery part to the assistant and the flows to the night audit. An AST check over the package: a `solar − export` subtraction or an `export ÷ solar` division that does not go through `solar_export` fails, except four named sites, each pinned to one; a line check over `dashboard/card/src`. The #666 key probe now counts 13 rows and feeds the sale. 24 mutants of the fix are killed.
**Sweep question:** when a row follows its meter, does every row booked beside it follow too?
**Left open:** readers of recorded history hold no split of who exported, so a sale there still counts as solar's: the "actual" self-consumption in the battery simulation (`simulation_job.energy_totals`) and the estimate of months before SEM kept costs (`_estimate_month_cost`, `_seed_yearly_cost_estimate`, #1216): **fixed**, round 3. A lifetime figure seeded from counters takes away only the sales SEM saw. Two old bugs next to the meter correction, not touched here: the charge-origin rows (`battery_charge_solar` / `battery_charge_grid`) do not follow a battery counter's correction (#1217), and with the battery's daily cap the correction adds to the month, year and lifetime rows on every cycle (#1218): **fixed**, class 172.
Refs #1191 #1172 #776 #660 #755 #1088 #628.

**Round 3 (#1216) — recorded history held no split of who exported.** The readers of recorded history still took all export away from solar. A day in the battery simulation with a 4 kWh morning sale and 14 kWh of sun read 0 % self-consumption, not 25 %. The estimate of months before SEM kept costs did the same, and also paid a sold kWh as an avoided import beside its export revenue (#776's shape).
**Where it lives:** the simulation's "actual" side (`energy_totals`, the instance) and its "simulated" side, when the what-if pack sells (`_dispatch`, force discharge); the month estimate (`_estimate_month_cost`: solar savings and battery savings); the whole-year fallback (`_seed_yearly_cost_estimate`); and the yearly energy seed, which set the year's export from the recorder and left `grid_export_battery` beside it at what SEM saw live (this round's sweep question, for a seed). All **fixed**.
**Closure:** SEM's own `flow_battery_to_grid_energy` sensor (#776, a daily TOTAL) is the history of the split: `utils.helpers.BATTERY_SALE_SENSOR_KEY`, found by unique id. The simulation reads it as a part role (`HourlyDay.grid_export_battery`, not a flow of the balance, no missing hour) and books it, never more than the export (`HourlyDay.sale`); the simulated pack books its own sale (`_Flow.battery_export`), but only on a day where the actual side can split too (`HourlyDay.sale_known`: the sensor has rows, or the pack never discharged). Splitting one side only made the what-if look better (review). The month query loads it as a series; the yearly seed sets the battery row beside the seeded export, never more than it, and keeps the live row where there is no history. Every reader goes through `solar_export`. A period before SEM published the sensor reads as before.
**Guard:** `tests/test_1216_history_battery_sale.py` — the sale through the real `from_statistics`, `simulate_day` and `energy_totals` (25 %, twin 0 %), the job asking the recorder for a renamed sale entity, a force-discharge what-if, the month estimate, the month query by unique id, the seed end to end with recorded and estimated months, the yearly fallback and the yearly seed (clamp, no history, export not seeded), a day before the sensor compared on one rule, each with an as-before twin. The #1191 AST check now names one site only (`demand_outcome.self_consumed_kwh`, fed solar's export). 20 mutants of the fix are killed.
**Left open:** the yearly seed runs once, and the lifetime seed reads hardware counters, not the recorder. So on an install already running, the year, month and lifetime battery rows hold only the sales SEM booked live since #1191; the sensor's history since #776 is not read back into them (#1245). The replay tool's day (`tools/replay/hourly.py`) carries no sale: its corpus records no flow sensor.
Refs #1216 #1191 #776 #794.

### 121. A word made for the code, shown to a person — PARTIAL
**Symptom:** a Dutch dashboard read "Netmodus: manual", "Netteken (auto): normal", "custom · Normaal", "normal · 2", "2 (number)", a chart legend "actual", and "ev_charger_1" / "battery" as names in the energy plan (#1053, RienduPre, 2.2.0-beta.10). Nothing errors; the user cannot tell what the word means and cannot find it in the translation file, because it is not there.
**Root shape:** a sensor publishes a closed set of words SEM chose for its own code, and a card puts the state on screen as it is. Where a card did map the words, the map was written once and the backend grew: the System card knew `combined` and `split`, then #461 added `manual` and #947 three `split-*` words, and those printed raw. A demand id (`ev:<charger id>`) is the same shape: the card printed the part after the colon as the name.
**Where it lives:** `sem-system-card.js` (grid mode in the header and the info row, charger control, the English "solar" in the health header), `sem-control-card.js` (grid sign, heat pump mode and the SG-Ready number in the header, tariff source, load-management status), `sem-config-card.js` (tariff source, heat pump mode, grid and battery sign, load-management status), `sem-grid-card.js` and `sem-load-priority-card.js` (load-management status), `sem-chart-card.js` (the forecast preset's `actual` series and title key), `sem-energy-plan-card.js` (not-scheduled rows, last night's review rows, tomorrow's asks). All **swept**.
**Closure:** `dashboard/card/src/util/state-label.js` — one table per sensor (backend word → translation key; tariff brands by name), read through one method, `_valLabel()` in `sem-lit-base.js`. A word with no row is shown as it is, never blank. The energy plan: `coordinator/demand_labels.py` gives each charger row and each review row the name the user gave (`ev_not_scheduled`, `labelled_review`, looked up when published); the card's `_demandName()` (`util/demand-name.js`) falls back to the demand's kind in the user's language, never the id; tomorrow's asks send no name rather than the device id or the English "EV". Nine new keys in all 16 languages.
**Guard:** `tests/test_1053_machine_words.py` — reads each word from the code that writes it (`publish_diag` by AST, `SGReadyState`, `LoadManagementState`, every `_provider_name`/`provider=` in `tariff/`, `format_battery_sign_diag` run on four shapes, the dataclass defaults) and fails when the card table has no row for it or a row's key is missing in a language (a value the scan cannot read, such as a variable, fails too); a line lint fails on `_val('<one of these sensors>')` in any card outside the copied support text; every chart preset word is a key; the plan card never splits an id; the real planner, the real publish step and tomorrow's asks carry names. `dashboard/card/test/state-label.test.js` and `demand-name.test.js` pin the two helpers. Five mutants of the fix are killed.
**Sweep question:** for every sensor state a card shows — is it a number, a name a person gave, or a word SEM made? If SEM made it, which table translates it, and who adds the row when the backend adds a word?
**Left open:** (1) the heat pump and hot water are named in English by SEM ("Heat Pump", "Hot Water", `heat_pump_name` has no setting), and the name reaches the Today plan, the load list and the flow tiles — the #587 decision on SEM's own device names. (2) The System card's collapsed Diagnose block is English prose with raw states (`charging_state`, `grid_status`); it is support text, so it was left. (3) The lint sees `_val`/`_valStr`/`_valNum` reads only; a card that reads `hass.states[...]` of one of these sensors directly is not seen. (4) The charger default name "EV Charger" (config flow) is English too. (5) Not seen live: a saved battery id `__fleet__` would show in the battery sign as it is (`format_battery_sign_diag`).
Refs #1053 #461 #947 #744 #587.

### 122. A setting published through a part that can be off — with it off, the sensor shows the built-in default — GUARDED
**Symptom:** the Control tab read "5.00 kW" while the install was set to no grid limit, and any number the user saved went back to 5 kW after a page refresh (#1055, lostcontrol, Fronius, no charger, load management off). The Config tab showed the saved value; the EV sizing used the saved value. Only the sensor was wrong.
**Root shape:** the grid limit is a setting, but `_build_load_management_data` copied it from the load manager only. With load management off there is no load manager (#897), so the `LoadManagementData` defaults (5.0 kW, limited) went out on `sensor.sem_target_peak_limit` as if the user had chosen them. `_get_peak_limit_w` had its own fallback to the saved option, so what SEM showed and what SEM did were two different limits.
**Where it lives:** `_build_load_management_data` — `target_peak_limit`, `peak_limit_unlimited`, and the two numbers made from them, `peak_margin` and `current_vs_peak_percentage` (**swept**; with no limit the percent is 0, not a percent of the saved number). Cards that print the limit, a percent of it or a margin and skip the "no limit" flag: the Control-tab header, the Control card's peak section and the Home card (**swept**); the load list card was already right. The diagnostics now carry the flag. "Uncapped" was English in 12 languages (**translated**).
**Closure:** one reader, `ev_control._target_peak_limit_kw()` (load manager first, then the saved option; a saved value that is not a number keeps the default limit) with `_peak_limit_unlimited()`, used by both the EV sizing and the publish. Cards ask `util/peak-slot.js::isUncapped` and print the limit through `peakLimitText`.
**Guard:** `tests/test_1055_peak_limit_published.py` — with load management off, the saved limit, the saved "no limit" and a slider write reach the published data; zero config gives the defaults; a bad saved value keeps a limit; no limit reads 0 %; a live load manager still wins; a test that the published limit equals the limit the EV sizing uses, with and without a load manager; an AST check that the builder reads neither key from the load manager's dict. `dashboard/card/test/peak-limit-text.test.js` pins the card helpers and that the three cards use them.
**Sweep question:** for every value a sensor publishes — is it a setting or a measurement? If a setting, is it read from where it is saved, or only through a part the user can turn off?
**Left open:** (1) the 15-minute slot guard (`_compute_peak_slot_allowance`) reads the limit from the load manager only, so with load management off there is no slot guard while the EV sizing still keeps the limit — a control change, not a display fix. (2) `consecutive_peak_15min` and `monthly_consecutive_peak` are measured by the load manager only; with it off they read 0.0, not "unknown". (3) `sem-grid-card.js` (not on the default dashboard) prints the limit, margin and peaks — all kW sensors — through `semFormatPower`, which takes watts, so 5 kW shows as "5 W"; it also skips the "no limit" flag. (4) `dashboard/basic_template.yaml` prints the bare number too; it is used only when the main template is missing.
Refs #1055 #716 #897 #913.

### 123. A part built once, freed when the card leaves the page — HA puts the same card back — GUARDED
**Symptom:** the Energy tab drew both charts on the first visit. Go to another tab and come back: both were empty until a page reload (#1058, lostcontrol, 2.2.0-beta.11, video). Nothing in the log. Every SEM chart (Home, Battery, EV, Costs) had the same fault.
**Root shape:** Home Assistant keeps each view it has shown. Leaving a tab takes its cards off the page (`disconnectedCallback`); coming back puts the SAME card objects back (`connectedCallback`). Lit runs `firstUpdated()` once per object, does not render a card that comes back, and hass does not change if nothing changed while you were away. The chart card destroyed its Chart.js chart in `disconnectedCallback` and drew it again only when the period changed, the app came back to the front, or a 5-minute timer fired — so the canvas stayed empty. Its 5-minute roll also missed the power, battery and forecast charts: it worked out the opening window with its own rule, read them as "this week", and never moved them to now.
**Where it lives:** `sem-chart-card.js` (the chart; the instance), `sem-flow-card.js` (size and visibility watchers, the app-resume listener), `sem-system-diagram-card.js` (size and visibility watchers, a number count stopped half way), `sem-title-card.js` (a template subtitle stopped following its template; an answer that came after the card left was not dropped), `sem-ev-status-card.js` (the pause countdown is started in `updated()`, which did not run on return), `sem-config-card.js` and `sem-diagnose-button.js` (a ✓ or "Copied" whose clear-timer stopped on leave stayed on screen). All **swept**. Checked and right: `sem-price-card`, `sem-weather-card`, `sem-tab-header` (built in `connectedCallback`), the load list's drag listeners (end with the drag).
**Closure:** `SEMLitBase.connectedCallback()` asks for a render when `this.hasUpdated` (the card is back, not new), so `updated()` runs on every return. Each card builds again in `connectedCallback()`: the chart card's `_redraw()` whenever it has a window (its own window moved to now, a range the user picked kept), `_observe()` in the flow card and the diagram (not when the first update runs off the page), `_subscribeTemplate()` in the title card (only while on the page; a late answer is closed or dropped). A chart fetch that answers after the card left, or after a newer fetch, draws nothing (`_fetchSeq`). One `_defaultKey()` answers "which window does this card open on" for opening and for the roll, so the power, battery and forecast charts now move to now every 5 minutes, like the others.
**Guard:** `dashboard/card/test/reconnect.test.js` — (1) the real card code with a stub in place of Lit that runs Lit's update order, driven through leave-and-return: both chart presets fetch and draw again, the window ends now, a picked range is kept, a late answer draws nothing, a card off the page asks for no data, the roll moves the power chart to now, every card renders again, the EV countdown restarts, the ✓ and "Copied" clear, the flow and diagram watchers come back (and none start off the page), the title card subscribes again, opens nothing off the page and drops late answers; (2) a source check over every card: what `disconnectedCallback()` frees (`.disconnect()`, `.destroy()`, `clearInterval`, a removed listener, an unsubscribe) must be built in `connectedCallback()`, in `updated()` (cards on `SEMLitBase` only), or in a method they call — not from `setInterval` or a stored listener; a card whose `disconnectedCallback()` it cannot read fails it. Red on the old cards; 18 mutants of the fix fail it. Seen in a real browser with the built bundle: the old one leaves the canvas empty on return. `tests/test_1058_card_reconnect.py` checks the bundle was rebuilt.
**Sweep question:** for every part a card builds — a chart, a watcher, a timer, a subscription — what builds it again when HA puts the same card back on the page?
**Left open:** (1) a range picked in the period selector (Costs tab) is worked out once, at the click; on return, and while you stay, the chart shows that window, so "Today" picked yesterday still shows yesterday. A fix moves the selector's period maths into one helper the chart can roll. (2) Redrawing rebuilds the chart: a series hidden in the legend shows again and a hover tooltip drops (now every 5 minutes for power, battery and forecast too). `chart.update()` in place would keep them. (3) The source check knows the ways cards free a part today; it does not see `clearTimeout`, `cancelAnimationFrame` or observers held in a list, and it counts a call inside a `setTimeout` or `.then` as made on return.
Refs #1058 #541 #476 #457.

### 124. A battery shown because nothing said it was missing — a saved size and an empty meter taken as proof — GUARDED
**Symptom:** on a home with no battery the Energy Plan card drew one (#1063, lostcontrol, 2.2.0-beta.11, Fronius). Today: the sunny hours wore the "battery covers home" colour. Tomorrow: a "Battery" row filled from 0.0 to 7.4 kWh. Load planning was right; only what the card showed was wrong.
**Root shape:** two claims that a battery exists, neither from a fact about a battery. (a) A size: `battery_capacity_kwh` answered the built-in 15 kWh, and the settings step saves a size on every install, so "has a size" was true everywhere. The tomorrow preview walked that pack. (b) A colour by elimination: the card painted a slot "battery" when the meter carried none of the house. A sun slot carries none either (the ledger sets its net draw to 0), so every home's sunny hours read as battery — the battery-less home only made it plain.
**Where it lives:** the capacity property (tomorrow's battery row, the plan's battery flag, `forecast_surplus_kwh`, which took a 15 kWh empty battery's need off a battery-less home's surplus — **swept by the source**); the plan card's Home row colour, icon, hand-over time and legend; tomorrow's "battery charging" key; the battery-night recorder, which sealed nights of zeros on a battery-less home and could put "drained 0.0 kWh overnight — the promised refill never came" on the card (**swept**: no battery, no record; the backfill service now says so); `battery_redirect_w`, where a size of 0 read as "full" and gave the car the whole charge of a battery added since the last reload (**swept**: no size, no redirect; a saved size is at least 1 kWh, so only the ABSENT answer is 0).
**Closure:** a battery is claimed only from a fact about one. The property returns 0 when the battery module is ABSENT (#923); UNKNOWN keeps the old answer, so a slow boot never hides a real battery. The plan marks a slot `batt` only where its walk drew the battery for the house, and says `has_battery`; the entity carries the marks as index runs (`batt_runs` — a flag per slot pushed a 15-minute day over the recorder budget). The card colours each slot grid / battery / sun through `util/plan-cover.js` and shows no battery icon, hand-over time or battery legend without them. A plan stamped before the fix has no runs (`None`, not `[]`) and keeps the old colours until the next stamp, so a battery home's night is not drawn as sun after the update.
**Guard:** `tests/test_1063_plan_card_no_battery.py` — the property over ABSENT / UNKNOWN / PRESENT; a real plan stamped at 14:00 with and without a battery (no `batt` anywhere without one; sunny hours never `batt` with one; every evening hour the battery covers is marked); the quiet night carries the flag; the entity carries the runs and the flag, an old plan carries neither, and the runs cost a 96-slot day at most 12 bytes; tomorrow has no curve without a battery and keeps one with it; a saved 15 kWh on a battery-less home walks no battery today or tomorrow; the ready check still decides when plans run exactly as before; a battery-less night alone earns a review row, and the recorder records nothing when the battery is ABSENT; a size of 0 redirects nothing. (The backfill service's log line has no test: there is no harness for the service handlers.) `dashboard/card/test/plan-cover.test.js` pins the colour rule, the runs, the old-plan rule and the card's use of them. Four mutants of the fix fail the Python file.
**Round 2 (08.10.2026, lostcontrol again, 2.2.0-beta.12):** the battery was back as soon as something was planned. His module was not ABSENT but UNKNOWN, and the closure above stopped at ABSENT: UNKNOWN "kept the old answer" — the 15 kWh default — so the plan walked a pack nobody had, the sun filled it by day and it "covered the house" in the plan's colours; tomorrow charged it again. The same shape, one step further out: a could-not-ask read as a yes. Now one question, `coordinator.battery_unseen`, serves the size, the plan, the preview, the night recorder and the backfill: ABSENT is no, PRESENT is yes, UNKNOWN is no unless SEM is reading a SOC or detected a pack on a device. The quiet night says `battery_unseen` on the card ("no battery found, so none was planned"); the full plan's log says "none found" or "module absent". A slow boot keeps its battery: a wired one is PRESENT, a declared one is PRESENT once the Energy Dashboard is read, and a read one is seen. Guarded by the same file: the predicate over every verdict, UNKNOWN with nothing read walks no pack today or tomorrow and records no night, UNKNOWN with a reading keeps its curve and its nights, the why word in 16 languages.
**Sweep question:** for every place that shows a part — is it shown because something says the part is there, or because nothing says it is not? And when the answer is "could not ask": is that read as a no, or quietly as a yes?
**Left open:** (0) the plan's ready check (`_energy_plan_tick`) still asks the saved key: on a battery-less home the SOC reads "unavailable" every cycle, so one that saved the Settings step (15 kWh) never stamps a plan — the card stays "pending" and nothing is planned. Asking the module verdict there would start plans (and plan actuation) on those homes: a control change, not part of a display fix. (1) closed in round 2: UNKNOWN walks a pack only while one is read or detected. Battery CONTROL (`_run_battery_pipeline`) still runs on UNKNOWN as before — a brand adapter auto-detected from a loaded inverter integration may act on a battery SEM cannot see; a control change, left open. (2) Other readers of the saved key keep their own defaults (`build_view.py` 15, `energy_calculator.py` 15, the battery scheduler 10, the battery ETA 15.0, the battery runtime 0): on an ABSENT home they sit in battery paths that do not run or show nothing, so they were left. One of them pairs with the property: `decide.py` sizes the redirect from `build_view.py`'s saved key while the EV budget reads the property, so in the minutes between adding a battery and the reload (still ABSENT) the two disagree (15 vs 0). They already disagreed whenever the size was auto-detected; one source for both is the fix. (3) A slot with no house draw and no sun (a house profile of 0 W at night) is drawn as sun.
Refs #1063 #923 #925 #857.

### 125. A field on the screen that no decision reads — the value stops at a log line — GUARDED
**Symptom:** Configuration tab → Hot water showed "Max temperature" ("SEM never activates above this") and "Minimum temperature" ("below this, SEM force-heats from any source"). Neither did anything. With Solar target 70 °C and Max 60 °C the tank heated to 70 °C, and only the Control tab's "Run now past" forced heating, so users set one thing in two places and could not tell which counted (#1062, lostcontrol, #1059).
**Root shape:** #92 made the solar target the ceiling on purpose and dropped the separate maximum. 1.7.2-beta.2 put both fields back on the card "config-only for now", with help text for what they should do. #454 then wired the controller and gave a decision only to the solar target and Legionella. The max value reached `HotWaterController.max_temperature` and stopped at a log line, `to_dict` and a published `HotWaterSensorData` field. `tests/test_knob_wiring.py` passed, because it asks whether the config key is read — and it was, into an attribute nothing decides on.
**Where it lives:** hot water `max_temperature` (number entity, card row, published value) — **removed**, and the stale-entity sweep drops the entity on the next load. The `hot_water_minimum_temperature` card row — **removed**; the key stays for its two real uses. `needs_heating()` (diagnostics only) — **removed**. The Control-tab comfort band on a boiler said "device's own thermometer" but read nothing unless one was picked, so "Run now past" never forced a boiler — **swept** (`HotWaterController._comfort_fallback_reading`, in °C). Vacation now turns the band off (#594: no comfort heating while away), so the newly working band cannot plan a grid block or force a run while away. A scan of every device constructor value found one more with no reader, `SetpointDevice.min_setpoint`; nothing sets it and no screen shows it, so it is allowed with that reason.
**Closure:** remove the dead fields and their surface (the #830 option list only shrinks), so each meaning has one place. Configuration: boiler, sensor, solar target, Legionella. Control: mode, priority, the stop ("Keep at" + "Bank by") and the force ("Run now past").
**Guard:** `tests/test_1062_hot_water_fields.py::TestEveryDeviceSettingReachesADecision` — AST: every `self.<x> = <a parameter>` in a device `__init__` (plain, annotated or tuple assignment) needs a reader in the logic layer that is not inside a log call (`_LOGGER.*`, `log_on_change`), `to_dict` or a `*SensorData(...)` field; an allowance needs a reason and fails once it is no longer needed. It fails on the old code with `max_temperature`. It counts any `.<name>` read as a decision, so a same-named attribute elsewhere can hide a dead one — a floor, not proof. Behaviour pins in the same file: the switch-boiler stop through the real surplus pass, the Legionella cycle not cut by SEM's own stops (a user's stop entity still ends it), the band's fallback thermometer (°F included), vacation turning the band off, zero config unchanged, the card's option list without the minimum.
**Sweep question:** for every field a screen shows, follow the value past the attribute it lands in. Which decision changes when it changes? A log line, a diagnostic and a published copy are not decisions.
**Left open:** (1) `min_temperature` keeps two narrow uses with no card field: the vacation surplus cap (its switch `vacation_dhw_surplus` has no surface either) and the setpoint a water_heater is left at when `turn_off` fails. Both belong with #914's open "release to the minimum setpoint" decision. (2) SEM does not stop a water_heater or climate tank at the target; its setpoint does. A target changed while it runs is not re-written. (3) A switch boiler whose sensor breaks while it runs is not stopped, because no reading is not proof of a hot tank; the start is still refused. (4) No gap between the stop (at the target) and the next start (below it): with a sensor near the element, the boiler can cycle at the anti-cycle limit (10 min on, 5 min off). (5) °F installs: `get_current_temperature` returns the raw reading and compares it with °C targets (older than this fix) — SEM never starts the boiler, and now also stops a switch boiler someone else turned on. `natural_achievement` and the written setpoints have the same fault. (6) Tanks no longer overshoot to 60 °C on sun, so forced Legionella runs come more often, at whatever hour they fall due; a solar target ≥ 60 °C still covers it. (7) The #638 comfort-banking pass runs a "willing" band on cheap grid whatever `top_up_policy` says, for every band device; it now reaches boilers whose band was set but read nothing. (8) Those banking and forced runs carry `_offpeak_forced`; a Legionella cycle that falls due during one is cut by force-expiry or the plan hold, which do not check `_legionella_cycle_active` — the older #914 "Legionella vs LIFO" stall, now reachable from a band.
Refs #1062 #1059 #92 #454 #705 #830.

### 126. A change waits in a second store that the section's "unsaved" count does not read — GUARDED
**Symptom:** Config tab → Tariff, Calendar mode: a user picked a Schedule helper as "Peak-time schedule" and read "no price difference" at the off-peak price (#1040, @mdscgan, 2.2.0-beta.11). The helper was never saved. The field had a small dot, but its section showed no unsaved count and no Apply button; the only Apply sat in a bar at the top of the card. Our own reply sent the user to the section's "Apply changes", which did not appear.
**Root shape:** the card has two places an edit can wait. `_staged` (#605) holds numbers, toggles and selects; the section counts it and its footer applies it. `_pending` (#528) holds entity pickers and toggles that reload the entry; only the top bar reads it. Each store is right on its own. The section's count read one of the two, so "nothing unsaved" was true of `_staged` and false of the section.
**Where it lives:** every structural picker (`_renderPicker`) and structural toggle (`_renderOptionToggle`) — Tariff (the schedule, the battery control entities, the bidirectional flag), Sensor sources, Battery zones (`battery_discharge_protection_enabled`, on the default view), Heat pump and Hot water entities. All **swept** by one change: both renderers bind their pending edit to the section (`_regPending`).
**Closure:** the section owns every edit made in it, whichever store holds it. `_sectionUnsaved` counts both stores; the section's Apply sends staged and pending keys in one `set_option` call (one reload); Revert drops both. Picking another tariff mode drops the unsaved edits of the fields that mode hides (`_pickTariffMode`), so Apply never saves a field of a mode the user left. A row hidden by the view (Advanced off, a closed fold) keeps its edit on the count, as #605 did — a first try that unbound every hidden row held such edits back with no number anywhere (review). The top bar stays for edits in several sections; the two Apply buttons wait for each other.
**Guard:** `dashboard/card/test/calendar-setup.test.js` — the real card: a picked schedule counts in its section, the section's Apply sends it with the staged mode and rate in one call, a failed Apply keeps it, Revert drops it, another section's edit stays waiting, a structural toggle binds too, a mode picked and left again sends nothing, an Advanced-hidden edit still counts, the two Apply buttons wait for each other.
**Sweep question:** for every "unsaved" count or "dirty" flag — list every store an edit can wait in, and ask whether the count reads all of them.
**Left open:** (1) per-charger pickers (`_renderPickerNested`) save at once and have no unsaved state at all — a third way; so do the Dynamic pickers, which now show (and save) as soon as Dynamic is picked, before its Apply. (2) With a structural edit waiting, the section footer and the top bar now both offer Apply; the top bar could go. (3) `_renderTextOption` saves `battery_setpoint_model` and the direction values at once on blur, though they are structural keys — each edit reloads the entry.
Refs #1040 #528 #605.

### 127. A card draws again only when a listed input changes — it shows one the list leaves out — GUARDED
**Symptom:** the grid limit was right on the Control tab after #1055, until you changed it on the Configuration tab. Back on the Control tab the slider and its value showed the old limit until a browser reload (#1055 follow-up, lostcontrol, 2.2.0-beta.12, load management off). Saving it on the Configuration tab also restarted the whole integration.
**Root shape:** HA sets `hass` on every card for every state change in the house, so each card compares a few inputs and draws only when one changed. The list of inputs is written by hand beside the code that reads them, and the two drift. The load list card compared `controllable_devices_count`, `consecutive_peak_15min` and `load_management_status` — not `target_peak_limit`. With load management off all three never change (0, 0.0, "idle"), so it read the limit once and never again — and the device rows (on, off, power, shed) stood still too. `SEMLitBase` compares `.state` only; "no grid limit" is an attribute (`peak_limit_unlimited`), and the Control card did not list the limit sensor at all. Kin of class 24 (a hand list next to a structure that grows). The reload: `set_option` sent `target_peak_limit` live only through the load manager; with none it fell to the unrouted path (entry write + reload). `peak_limit_unlimited` took that path on every home. #913 took the same reload out of the Control slider.
**Where it lives:** `sem-load-priority-card.js` (the instance), `SEMLitBase.set hass`, the Control card (`target_peak_limit` and `diag_grid_sign` read, not watched; the flag), the Home card (the flag). All **swept**. `__init__.py::async_set_option` for `target_peak_limit`, `warning_peak_level`, `emergency_peak_level` and `peak_limit_unlimited` (**swept**). Checked and right: the tab header's flag; its own hand-made key missed the EV tab's session, the Config tab's SOC and charger count, and the currency, and asked the heat pump under the wrong id (**swept** in #1198: the key is the text the header shows). Also right: the Config card's options (read again each time you return to the tab).
**Closure:** the load list compares the state objects of `LOAD_PRIORITY_READS` — every SEM sensor `_updateDeviceData()` reads — and HA gives a new object only when the state or an attribute changed. A slider value is kept until the sensor has it (15 s at most, dropped when the write is refused), so a push from before the save cannot move it back. `SEMLitBase` takes `watchedAttributes` (`{ entity: [attribute] }`) and compares them with the state. `set_option` writes the grid keys live: through the load manager when there is one (the flag too, with the saved or sent limit), else with `persist_global_option`, the same write `update_target_peak` uses. A level that is not a number is refused before anything in the save is written.
**Guard:** `dashboard/card/test/redraw-gate.test.js` — the real cards: the load list reads a new limit and a flag-only change with the other sensors still; one push after returning to the tab is enough; an unrelated push does not draw; the slider hold, its end, its time limit, a refused write, and a refused older drag that must not drop a newer hold; the Control and Home cards draw on a flag-only change. A source check: every SEM sensor the load list reads is in `LOAD_PRIORITY_READS`; every card on the base gate watches each sensor it reads with `_val*()` or `${this._prefix}`, and a card that shows "no grid limit" watches the flag (an unwatched read needs a named reason). On the old cards all fail but the one that an unrelated push does not draw. `tests/test_1055_config_save_no_reload.py` — real HA: the limit, the flag (also as the word "false") and a level save keep the same coordinator and reach the published sensor, with and without a load manager; with both keys in one save the flag is written with the sent limit; a level that is not a number (also "nan") is refused and nothing is written.
**Sweep question:** for every card that skips a draw — list what it shows, list what it compares, and ask which one is longer.
**Left open:** (1) cards with their own hand-made key — charger status, EV status, energy plan, price, flow, grid, battery, energy impact, solar, solar summary, schedule, today plan — are not read by the source check. (2) The source check sees `_val*('x')` and `${this._prefix}x` reads only: a quoted `'sensor.sem_x'` read and attributes other than the grid flag are not checked (the System card shows `diag_ed_config` attributes). (3) A device's live power on the load list moves at SEM's cycle, not on each power-sensor change — on purpose, so a push from before a device edit lands cannot undo it. (4) Without a load manager a saved warning or emergency level is stored without the #813 order repair, as before; only the reload went away. (5) The Config card's Hot water live block reads seven entities SEM does not create (`hot_water_registered` and six sensors), so it never shows; the source check allows those reads by name. (6) A device edit on the load list (toggle, mode, goal) has no hold: a cycle that was already running can show the old value for one cycle. Homes with load management on always had this; homes without it now do too, because their rows now move.
Refs #1055 #913 #897 #716 #668.

### 128. A reconcile that only moves one way, on a belief the hardware disproves — the error in the other direction is kept — GUARDED
**Symptom:** on 4 Oct the calendar-day car row said 19.56 kWh while both wallbox counters said 10.99 (#1049, RienduPre, 2× Wallbox Pulsar behind the MQTT bridge, 2.2.0-beta.9). Home is the meters minus that row, so home read 8.49 kWh against 17.28 of to-home flows, true baseload went negative, and the controlled-loads check blamed a "renamed or removed id". Every counter was set up, live and right.
**Root shape:** the EV rows took the counters UP only (#658), on the belief that a charger counter "can only ever reveal energy the integrator missed". That holds for downtime; it fails when the power sensor reads high (the bridge's open issue #110: 7.6 kW on one phase at 16 A), and the one-way rule keeps every kWh of it. The grid and battery rows already moved both ways (#628), so home was built from meters on one side and an unchecked integral on the other. Kin of class 28's note (one-way passes keep errors instead of cancelling them) and class 40 (a guard defending the wrong number).
**Where it lives:** `EnergyCalculator._reconcile_ev_bucket` — the EV-day row and the calendar-day copy home subtracts (**fixed**); the per-charger rows `coordinator._daily_ev_per_charger`, which had no counter at all (**fixed** — left alone, the members would sum above a fleet row that moved down and the #771 check would fire). Checked and kept one way: `_reconcile_solar_energy` (on a hybrid the counter is AC yield and trails PV all day — down would be wrong). `_reconcile_metered_energy` already moves both ways.
**Closure:** the counters own an EV row when every charger has a counter of its own (`complete` and `owners`, from `_ev_counters_cover_fleet` / `_ev_counter_owners`; a shared or fallback counter does not count), every counter reads, and the anchor was taken with this same complete set (`whole` — a restore runs after setup, so a changed set must be caught here, not only in `configure_ev_counters`). An owned row follows the counters up at once, and down only once every box has stopped charging (`EV_ACTIVE_CHARGE_FLOOR_W`) and its counter has reported since (`_track_ev_pending`, `_ev_settled`): a counter can publish a value minutes old, and one that reports late or never must not pull a row under what the box drew. What a box drew before an anchor and its counter had not reported is `owed`: that counter's next move pays it first, so a late report after midnight or Charge-by is not booked on the new day. A drop within `EV_COUNTER_DIP_KWH` / `EV_COUNTER_DIP_SHARE` of the last reading is a dip and holds it (class 43); a larger drop is a reset. Each charger's row follows its own counter the same way (`follow_charger_counter`, only on a complete fleet, one box's ceiling; a box with flat keys is `ev_charger`).
**Guard:** `tests/test_1049_ev_counter_owns_the_day.py` — the reporter's shape (5.0 by power, 3.0 on the meter → 3.0 on both rows and in month/year/lifetime once the box stops); a late counter, a report from before the stop, and a counter that never moves never pull down; standby is not charging; upward recovery runs at once; dips (also on a day's first read) are not booked, real resets (also to more than half) are; a late report after midnight or after a charger's Charge-by is not booked twice; a partial set, an owner-less counter, a dark counter, a counter first seen after the anchor, a counter swapped since the store, and a set that became complete never pull down; the owed draw and the per-charger baselines survive the store, a damaged one re-anchors; home gets its kWh back; the wiring is checked with `ast_contracts`. Switching off each guard fails its tests (settled 12, drawing 8, owed 2, dip window 3, day-start dip 1, set check 3, `complete` at the anchor 1).
**Sweep question:** for every `if target > current: adopt`, ask what would make the integral read HIGH, and whether the counter could then be trusted to say so.
**Left open:** (1) the 2–4 kWh steps at each charge start are in the power read (the counters show none); the cause is in the bridge or the box, not found here. (2) While a car charges, an owned row still holds the power read (down only after the stop), so a session across midnight or Charge-by keeps its high read on the closed day, and kWh Charge-by targets see the high read mid-session as before. (3) `_update_ev_intelligence` integrates each charger with the nominal `update_interval`, not the time since its last run — a charger with no counter of its own keeps that error. (4) A box whose own draw SEM cannot read (an id-less entry, no power sensor of its own) is charged the fleet's draw, so on a fleet the rows wait for every box. (5) A correction of an EV day that began last month lands in this month's key (clamped at 0).
Refs #1049 #658 #628 #771 #1044 #782.

### 129. One reading taken as what a load draws — an up-only rule keeps the start peak for life — GUARDED
**Symptom:** a dehumidifier that draws ~200 W showed "~1.4 kW" on the Control card, and SEM never switched it on (#1067, lostcontrol, Fronius, 2.2.0-beta.12). The rating is also the surplus SEM waits for before it starts the load.
**Root shape:** a compressor or motor start reads several times the running draw for a few seconds. Every path that learns a load's rating took the highest single reading it was shown, and every path that keeps it only moves up: a real measurement, the wrong statistic. Kin of class 40 (an up-only guard defending the wrong number) and class 128 (a one-way rule keeps the error in the other direction).
**Where it lives:** `ControllableDevice.calibrate_rated_power` (every device type; adopted any live reading above the rating — **fixed**); `UnifiedDeviceRegistry._history_max_power` (the largest value in 7 days, also read with no unit, so a kW sensor seeded 2 kW as 2 W — **fixed**, now `_history_held_power`); `_initial_rated_power` (a load running at build time got its instant reading as a measured rating, both ED build sites — **fixed**); `_capture_calibrated_ratings` (saves up only — kept, and only shown held levels now). Checked and right: `WattsPerAmp` (a median per bucket). Display only, left: `_rated_power_for`'s live fallback for a row with no device, and `LoadDeviceDiscovery._get_device_power_rating` (no decision reads it while the registry is active).
**Closure:** a rating is the highest level the sensor HELD for `RATED_POWER_HOLD_S` (120 s). Live: `devices/held_power.py::HeldPower` keeps one unbroken run of readings and returns their lowest once the run covers the hold, counting the reading in force when the hold began; the load going off, or a gap over `RATED_POWER_SAMPLE_GAP_S` (90 s, above the longest 60 s update interval), starts it again. History: `held_power_w` takes the same level over the state changes, each held until the next, in the executor; a value above `_MAX_PLAUSIBLE_LOAD_W` breaks a run (a W→kW unit change inside the week, for loads above 100 W). Saved ratings carry `rated_power_rule`; a store without it marks every saved rating for one re-check (`rated_power_recheck`, persisted). The re-check reads history first and then decides in one pass with no await (a rebuild may swap the device objects during the read). Until history answers, a marked rating is applied only over the 1 kW placeholder (class 40); it is replaced by the held level only if that level is at least 1/`RATED_POWER_START_PEAK_RATIO` (20) of it — a load left on but idle is not a start peak — and the device itself moves down only if this sync built it from that saved number (`_built_from_store`, cleared each sync). A rating a device was given (heat pump, hot water) is never lowered, nor raised to a marked number. The rule check is `<`, so a store from a later rule is left alone.
**Guard:** `tests/test_1067_held_rating.py` — the reporter's start peak then 200 W learns 200 W, live and from history; a peak does not raise a learned rating; a level held long enough still does; a noisy run learns its floor; a gap, an off load, a 60 s interval, and a peak held 90 s at a 30 s cycle; a kW history read in watts, a missing sensor, a unit change in the week; the build takes no reading; an old store is marked, the marks and the rule survive a restart, a damaged mark list loses nothing else; history moves the old peak down (also one 15 times the run), an idle week does not, no history changes nothing, a placeholder still gets the saved number; a given rating is neither lowered nor raised to an old peak; a live level is not overwritten; a rebuild during the read keeps the answer; a failed history job is no level. Removing each part of the fix fails a test (19 checked).
**Sweep question:** for every value learned by "keep the highest": would one short spike be enough to set it, and could anything ever bring it down?
**Left open:** (1) a marked rating whose load did not run in the 7 days before a restart keeps its old number until a restart after a run (the check runs once per start). (2) A sensor that reports every 2 minutes or slower can hold a caught start reading for the whole hold, live and in history. (3) A load whose draw changes faster than the hold (fan and compressor switching, a thermostat clicking) learns its lowest level, or nothing and keeps the 1 kW placeholder. (4) Energy Dashboard loads are unregistered before a rebuild, so `_VOLATILE_CONTROL_FIELDS` (the hold and every older field) never carries over for them; a rebuild (setup, the 35 s rediscovery, an edit) starts the hold again. (5) A rating learned live is saved only on the next rebuild (as before). (6) There is still no field to set a load's power by hand (the reporter asked for one). (7) The 1/20 rule is a trade: a saved heating-phase rating whose week held only a lower mode (a cold wash) moves down until its next heating run; a start peak more than 20 times the run is kept. (8) A W→kW unit change on a load under 100 W is not caught (60 W reads 60 kW, under the cap). (9) Older, not from this fix: the #888 early save in `_load_storage` runs before the ratings, service registrations and goals are read, so it writes them empty until the next save.
Refs #1067 #744 #576 #641.

### 130. A limit every device answers to — except the ones that were never handed it — GUARDED
**Symptom:** a review before building the grid operator's limit (#1021) found the house limit was honoured by the car and the shed loads but not by the battery, and not by the bill (#1069, review 08.10.2026). A 4.2 kW limit, the car offered 4.0 kW and a 3 kW planned battery block put 7 kW on the meter while every sensor read "under the limit".
**Root shape:** "the peak guard sits above every mode of every device" was true where the slot allowance had been threaded, and nowhere else. Each gap was a device or a reader that never received the one number, or kept a copy of it. Kin of class 93 (two producers of one context) and class 40 (a guard defending the wrong number).
**Where it lives:** `decide_battery` — every FORCE_CHARGE (planned block, negative price, manual) charged at full power (**fixed**: `_cap_forced_charge`, room = allowance + sun − house − what the chargers were offered, 250 W steps, stop below one); `peak_cover_floor_w` raised the discharge limit at any SOC (**fixed**: `reserve_stops_peak_cover`); `SchedulerConfig.peak_limit_w` / `max_grid_import_w` — a setup copy nothing read (**deleted**); `LoadManagementCoordinator._update_peak_tracking` booked the monthly peak from a sliding window (**fixed**: `record_closed_slot` from `PeakSlotTracker.pop_closed`); `PeakSlotTracker` started each restart at zero (**fixed**: `to_state` / `tracker_from_state`); `clamp_to_peak_slot` floored at 6 A, so a car over a limit near its minimum flipped every cycle (**fixed**: a `peak_paused` IDLE through the stability delays, restart with minimum + hysteresis); the tomorrow preview packed against the raw cap (**fixed**). The car's clamp counts SEM's own forced battery charge as room (`battery_forced_grid_w`), so the car comes first.
**Guard:** `tests/test_1069_peak_foundation.py` — one class per finding, each from the reviewer's scenario; the stability rule runs with the user's own delays in a surplus mode, `always_max` and a night floor.
**Sweep question:** for every device SEM can make draw from the grid, which line hands it the slot allowance — and does anything keep a copy?
**Left open:** (1) loads (the surplus controller) still see the car's and the battery's new offers only next cycle, through the meter. (2) The rolling 15-minute average stays as the shed states' trigger; only the bill moved to clock slots. (3) A paused car holds 6 A for the disable delay while the meter is over the limit; #747's emergency still stops it at once.
Refs #1069 #864 #1003 #693 #905 #747.

### 131. A page every home must pass asks for a part only some homes own — GUARDED
**Symptom:** a home with no charger opened Configure and met only the EV charger page; nothing could be filled and Submit did nothing, so a second heat pump, and every later setting, was out of reach (#990 round 2, @damiano75, 2.1.0).
**Root shape:** the options dialog is one chain, and its first page (the primary charger) had three required fields. #442 made the charger optional at install; the pages kept treating it as a precondition. HA's frontend will not submit a page with an empty required field, so one optional part closed the whole dialog. An optional entity picker with `default=""` closes a page the same way: HA validates the default, and "" is not an entity id. Kin of class 30 (a key with no editable surface) and class 124 (a part assumed present because nothing said it was missing).
**Where it lives:** `OptionsFlowHandler.async_step_init` opened on the charger page (**fixed**: no charger, by `has_managed_charger`, opens the charger menu; the skipped page's saved values are kept in `_unshown`, apart from the draft, and merged at save, so the save changes nothing, #690, and a saved `None` never becomes a later page's default, #73). `async_step_reconfigure` (**fixed**: `_charger_field` makes the three optional without a charger, all three checked once one is filled; `ev_charger_service_entity_id` and `ev_total_energy_sensor` take a suggestion instead of `default=""`, which had made the page unsaveable for every home without both). The menu offered "Add another EV charger" for the first one (**fixed**: `flow_add_first_charger`). Found on the way, class 101's sequel: `ev_charger_add` minted ids from the list position, so remove charger 2 of 3 and add one gave two chargers one id (**fixed**: the next number unused in the draft and both saved lists). Checked and right: every other required field in the options chain has a default.
**Guard:** `tests/test_990_no_charger_dialog.py` walks the whole dialog through HA's flow manager the way the browser does (the serialised schema, what each page pre-fills plus what the user types) and fails on any page with an empty required field: the plain walk, and one that adds a charger and a heat pump. Also: charger homes (list and flat keys) still open on their page; the skipped page changes nothing saved; a saved `None` does not break the add page; Reconfigure saved through the real flow manager with no charger, with a flat-key charger, and half-filled; charger ids after a remove.
**Sweep question:** for every required field on a page every home passes, what does a home without that part enter?
**Left open:** (1) the heat pump menu says "Your primary heat pump is configured" and counts it (`1 + len(heat_pumps)`) even when none is set up. (2) A first charger added from the menu gets id `ev_charger_0` and no flat keys, unlike one made on the old first page (`ev_charger` plus the flat mirror); the runtime reads the list, so both work. (3) Charger ids: a config saved before this fix may already hold two chargers with one id, and nothing renames them (heat pumps have `_heat_pump_rows`); and an id removed in an EARLIER save can still be minted again, because nothing records ids once used. (4) Reconfigure writes the charger sensors as flat keys into `entry.data` only. An options value still covers them, and a single charger's readers (`sensor_reader`, the charger power sensor) prefer them over the list, so an edit there splits the charger (class 19). So a list-only charger still meets three empty required fields on Reconfigure, on purpose; the real fix is to write the list too. (5) A legacy config holding only a flat `ev_connected_sensor` (no power sensor, no list) now skips the charger page; `unmanaged_charger_repair` counts that key, `has_managed_charger` does not.
Refs #990 #442 #690 #685 #73.

### 132. A thing that lives in two stores is removed from one; a thing one reader found is reported by another — GUARDED
**Symptom:** after the go-e roles shipped (#1054, @weindler, beta.13): the charger SEM now drove still sat on the Detected-hardware page as "entities present, no role matched" with a "create this charger entry" button; each click made another copy (`<id>_1`, `<id>_2`); the old, incomplete charger came back after every remove ("Healed ev_chargers options list: stored ids [] -> healed ids [...]"); `sensor.…_p_all` (kW, no device class) was missing from the power sensor pickers; `entry.data.has_ev` read `False`.
**Root shape:** four small asymmetries, one shape. (a) A charger lives in `entry.data` (setup) and `entry.options` (the user's changes); `remove_charger` and the dialog's remove step took it out of options only, and the start-up heal (#462/#464) unions the two by id — so a remove was undone at the next reload. (b) The detection report had no notion of "configured": the brand walk re-reported a unit SEM already drove as a near miss with an offer, the census counted its platform as "matched nothing" beside a complete offer, and the card minted a new id for every click instead of asking whether the box was there. (c) The power pickers (card and flow) filtered on `device_class=power` while the crawler reads a unit in W/kW as power — the very rule that found the box. (d) `has_ev` is what the Energy Dashboard said at setup, read by nothing at runtime; shown beside a configured charger it reads as a lie. Kin of class 19 (one value, two places) and class 124 (a part assumed from nothing).
**Where it lives:** `remove_charger` and `OptionsFlowHandler._prune_removed_chargers_from_data` (**fixed**: a remove leaves both stores; `chargers_without` is the pure helper). `build_detection_report(configured_chargers=…)` (**fixed**: a unit a configured charger points at is a `chargers` row with `configured: True`, skipped by the brand walk and the role pass; a complete offer counts as a matched platform in the census; a brand mapping with no charger sign is left to the roles, the config path's #1054 rule). `_merge_ev_chargers_by_id(fold_same_box=True)`, the set_option path only (**fixed**: an incoming charger under a new id that is a COPY of an existing one — the same entity set, or the old card's `<id>_n` with overlap — folds into it; `CHARGER_ENTITY_KEYS` / `charger_entity_ids` is the fingerprint the flow's "already installed" check uses, now in `hardware_detection`. The review caught the first cut: any one shared entity folded, so two chargers behind one meter would have lost the second at every start through the heal, which runs the same merge — the heal never folds). `_power_sensor_selector` and the card's `isPowerEntity` (**fixed**: device_class power OR unit W/kW, `power_sensor_ids`). The card's `chargerAddPlan` (**fixed**: an existing id is "there", never a copy) and `detectRowLabelKey` (a complete offer reads "charger found — one click to add").
**Guard:** `tests/test_1054_goe_followup.py` — a configured unit is a charger row and not a near miss, with the rig's real go-e capture too; a remove survives a reload through the real service; the same box under a new id folds into the existing charger; a kW sensor with no class is offered; every flow power selector goes through the one helper (AST); nothing at runtime reads the stored `has_ev`. `dashboard/card/test/detect-rows.test.js` for the card side.
**Sweep question:** for every value that lives in two stores, does every writer touch both? For every "found" the user sees, does the page know what is already configured?
**Left open:** (1) `entry.data.has_ev` / `has_battery` / `has_solar` / `has_grid` are setup-time provenance with no reader; dropping them from `entry.data` needs a migration and changes nothing SEM does. (2) A brand-found but unconfigured charger row carries no one-click offer; the flow's "Add charger" does that. (3) An install that removed a charger BEFORE this fix still holds it in `entry.data`; the next remove takes it out of both.
Refs #1054 #462 #464 #990 #915 #1032.

**Round 3 (#1054, 11.10.2026, beta.15):** the order of the stores is a fact too. A half-filled card from an older detection sat FIRST, so it was the primary: the Configure dialog's remove never offered it (only the working go-e), and because it named one go-e entity the report counted the box as configured and hid the offer that could rebuild it. Guards: `charger_is_complete` (hardware_detection) — a half card never claims its box and is removable even as primary; the create path's merge (`device_of`) lets a complete charger replace the half cards of its own device in their place, and writes the same list to `entry.data`, because the heal unions the stores in data's order; the coordinator drops per-charger state of ids no longer configured. Tests: `tests/test_1054_charger_lost.py`.

### 133. A test that reads the wall clock — the hour it runs at is part of its input — GUARDED
**Symptom:** `test_586_runtime_survives_restart` failed once on CI with "accrued daily runtime reset to 0 after restart (#586)", then passed on re-run and three times locally (#1076, CI run 37932357281, 09.10.2026). A red test blocks the daily beta.
**Root shape:** a real-HA test ran on the real clock in phacc's zone (US/Pacific). The test `hass` has no `sun.sun`, so SEM's load day starts at the 06:00 fallback. The test stamped its device day at 05:59:35; two 35 s `async_block_till_done` waits put the first tick after the reload at 06:00:05. The device saw a new day and reset its runtime, which is right for SEM and wrong for the test. Shifting only the clock reproduces it: start the run at 05:59:00 Pacific and it fails, at 05:58:00 it passes.
**Where it lives:** every test that uses phacc's real `hass` (40 files today), all on the wall clock, many 35–140 s long (**fixed**: `tests/conftest.py::_real_hass_starts_at_noon`). Tests without a real `hass`: one full-suite run with the clock started at 02:30 UTC, between midnight and the 06:00 fallback, where SEM's day and the date differ, failed nothing that depends on the hour (**sampled**, one hour only). Three files fail under any frozen clock: `test_915_write_verification`, `test_945_restart_enable_warmup` and `test_933_first_verdict_of_a_lifetime` patch `time.monotonic` to 1e9, which is in the past once the monotonic clock is epoch seconds. That does not depend on the hour, and the guard does not touch them.
**Closure:** an autouse fixture starts every test that uses a real `hass` at 12:00 today in phacc's zone, with the clock running (`freezegun`, `tick=True`), so it is six hours from the sunrise fallback and twelve from midnight. The date stays today's. HA's loop reads `time.monotonic` through phacc's `patch_time`, so timers and sleeps run as before. A test that asks for `freezer` (pytest-freezer adds it to every `freeze_time` marker) is left alone. `test_586` also checks that its day did not move, so a boundary inside the run says "the clock crossed a day boundary", not "#586".
**Guard:** `tests/test_1076_real_hass_clock.py` — a real-HA test starts within a minute of noon and SEM's day is the date; the clock still runs (wall and loop); a test with a `freeze_time` marker, and one that asks for `freezer`, keep their own time; a test without a real `hass` keeps the real clock. Removing the fixture, its `freezer` check, its `hass` check or `tick=True` each fails one of these. Started at 05:59:00 Pacific, `test_586` fails without the fixture and passes with it.
**Sweep question:** for every test that saves something stamped with a day and reads it back later: what happens if a day boundary falls between the two?
**Left open:** (1) the real-HA tests are slow because `async_block_till_done` waits for the 35 s delayed re-discovery; a reload test takes 70–140 s. (2) The fixture fixes the hour, not the date, so a run on a DST day or a month's last day still differs from other days; noon is hours from both changes. (3) A test that wants night must now say so with `freeze_time(..., tick=True)`; without `tick=True` a test that sets SEM up never ends (SEM's 35 s sleep). (4) In executor threads freezegun gives the real `time.time()` and `time.monotonic()`, while `datetime.now()` stays on the test clock; nothing in SEM compares the two today.
Refs #1076 #586 #704 #645.

### 134. One clamp for two moments — a guard right at dawn kept at noon — GUARDED (soak flag)
**Symptom:** PROD 08.10.2026: the forecast said 18.3 kWh, the day made 4.3. The day plan was built at 09:02 and still showed "no grid needed 10:00–17:00" in the evening while the house bought about 1 kW every hour (#1068).
**Root shape:** three readers, each right alone. (1) The live correction has a 0.5 floor, there to stop dawn noise (a tiny expected share turns a cloud into a huge ratio). At noon with full confidence the measured ratio is evidence, and the floor hid half the miss (true 0.23, published 0.5). (2) The plan's day slots read the provider's raw remaining, not the corrected one. (3) A replan whose decision is unchanged keeps the old plan whole (#775), slots included, so the old sky stayed on the card.
**Where it lives:** `coordinator/forecast_tracker.py::corrected_factor`, `coordinator/coordinator.py::plan_day_remaining_kwh`, `keep_decision_take_trajectory`.
**Closure:** the floor falls to 0.1 only once confidence is 1.0 and at least 2 kWh were expected so far; dawn keeps 0.5. One producer, `corrected_remaining_kwh`, feeds the day slots, the replan signature and the surplus outlook. An unchanged decision keeps its stamp and takes the new trajectory (`trajectory_at`). All behind the soak flag `intraday_forecast`; the published dampening factor is unchanged.
**Guard:** `tests/test_1068_intraday_forecast.py` — PROD's day at noon corrects below half; dawn keeps the floor; the published factor stays 0.5; both day readers go through the one helper (AST); the #775 restore is unchanged without the flag.
**Sweep question:** for every clamp, ask at which moment it was right, and whether a later moment reads it too.
**Left open:** the flag flips on after the PROD soak; a grey morning followed by a sunny afternoon must recover (watch that day shape).
**Second catch (#1104, 13.10.2026):** the CEILING had the same shape. PROD 13.10 10:00: a clear morning against a sine curve that expects ~11 % by then read as a 1.64× day; the plan saw 28.5 kWh to come, the day made 14.2 in total (09.10: 22.4 → 29.1, real 20.9). The plan's correction (`corrected_factor`) is capped at `max(1.0, learned historical correction)`: a sunny morning never raises it above what the history proved, and a provider that always forecasts low keeps its learned boost (review). Guard: `tests/test_1104_sunny_morning_no_overshoot.py` (both PROD mornings, grey day still lowers, published factor unchanged).
Refs #1068 #1104 #775 #598 #416.

### 135. A word inside a word — a name read for meaning — GUARDED
**Symptom:** rdehuyss's first install (2.2.0-beta.15, 11.10.2026): no car, yet setup showed an EV with `sensor.bedverwarming_device_power` — a bed-heating smart plug (#1051).
**Root shape:** the Energy Dashboard's individual devices were scanned for the letters `ev`, `charger`, `wallbox` … anywhere in the entity id. "device" holds "ev". A name says what someone typed, not what a thing is.
**Where it lives:** `ha_energy_reader.py::_extract_ev_from_devices` (**fixed**). Same report: a tip whose words held live numbers rewrote a sensor state every cycle (**fixed**, `analytics/energy_assistant.py`); a price slot's `all_in` was not a price key (**fixed**, `tariff/tariff_provider.py::SLOT_PRICE_KEYS`).
**Closure:** an Energy Dashboard device is the EV only when the entity registry says its integration is one the crawler knows as a charger (`known_charger_domains`). No registry, no EV.
**Guard:** `tests/test_1051_first_install.py` — his plug is not the EV; a KEBA device still is; names alone never are; a tip holds its words between rotations; >100 % export gives no tip; `all_in` is the slot price.
**Sweep question:** where else does SEM read a substring of an entity id as a fact about what the entity is?
Refs #1051 #829.

### 136. SEM finds its own sensor while it looks for the house's — its result read back as the meter — GUARDED
**Symptom:** @LightBridge16 (SolarEdge + Enphase Envoy, 2.2.0-beta, 12.10.2026): a Repair named `sensor.sem_grid_import_power` as the guessed grid IMPORT meter — SEM's own result, worked out from the meter it now stood in for (#1103).
**Root shape:** a scan for "a sensor whose name or shape says X" walks every state, and SEM publishes sensors with exactly that name and shape. Nothing asked who owns the entity. The charger prober had the rule (`platform != "solar_energy_management"`); the grid, SOC and capacity scans did not.
**Where it lives:** `coordinator/sensor_reader.py::_discover_split_grid_power` (**fixed**); `_auto_detect_battery_soc` strategy 3 (`sensor.sem_battery_soc` made every real SOC sensor one of two, so none — **fixed**); `auto_detect_battery_capacity_kwh` (`sensor.sem_diag_battery_capacity` is the SAVED size, read back as a found battery — the class 124 path — **fixed**); the config-dialog suggestions and `_spec_from_registry`, phase-current discovery, price autodetect, the unmanaged-charger scan and the power picker list (**fixed**, none were seen live). A pick made BY HAND — the card's pickers list SEM's own sensors — is ignored with a warning (`SensorReader._not_own_pick`).
**Closure:** one predicate, `utils/own_entity.py::is_sem_entity` — the entity registry's `platform`, never the id. No registry entry is no answer.
**Guard:** `tests/test_1103_own_sensor_is_no_input.py` — the reporter's scan, the SOC and capacity siblings, a hand pick, and an AST walk: every function with an `async_all(` over a domain SEM publishes calls the predicate or names its reason in `_EXEMPT`. The walk does not see `registry.entities.values()` or `async_entity_ids()` scans; those were swept by hand.
**Same report, class 19:** the Config card's **Sensor sources → Grid power** (`grid_power_sensor`) was read on the legacy path only; on a home with an Energy Dashboard it did nothing (**fixed**). Read now, it met a saved grid sign lock with no source: a pick in HA convention read import as export. The lock is saved with its source and dropped when a learned source (combined, sum) differs; a pair keeps its lock and is never negated, or the brand seed would invert it (`_check_restored_grid_lock`, as #971 did for the flip). The Repair's way out named "Configure → Sensors", a page that does not exist (**fixed**: it names the card's sections, in each language, behind **Advanced**).
**Sweep question:** where does SEM look for an input by name or shape — and could the answer be one of SEM's own entities?
Refs #1103 #911 #947 #1063.
### 137. A signed figure cut to its plus side, then a credit added back — the minus side is lost — GUARDED
**Symptom:** a "Solar only" 3 kW boiler stayed on for more than 20 minutes while the house bought up to 3 kW from the grid (#1102, lostcontrol, Fronius, no battery, 2.2.0-beta.15). The sun stayed above 3 kW the whole time.
**Root shape:** the loads' pool is "what would be spare if SEM's loads were off": the grid figure plus the loads' own draw (#508 W7). That holds only for the signed grid. The coordinator passed `grid_export_power` (`max(0, grid)`), so an import read 0 W and the draw came back whole: 2 kW import with the 3 kW boiler on read as 3 kW spare, not 1 kW. After the boiler's own debit the walk sat at −50 W, inside the −100 W stop band. Only the sun cap (#620) could stop it, and only once the sun fell below the draw. `solar_bounded_surplus` already took a signed figure (its own test passes −500); the call site cut it. The walk cut it a second time at the battery's slot: `max(0, remaining − reclaim)` wiped a deficit the loads above the battery had made, so the stop pass never saw it. Two more credits in the same walk had the same shape: the add-back summed loads the walk never debits (mode Off — a user's washer the belief sync sees running — and relay-locked loads, #1021), and a running variable load was offered `remaining + own draw`, written for the export-only pool of v1.0, though the pool holds the draw already (class 120's question, the other way round). With the import seen, a watt setpoint ramped to its maximum, imported, and was stopped — a cycle.
**Where it lives:** the pool build in `coordinator.py` (the instance); `active_surplus_draw_w` (**swept**); the active branch of `SurplusController.update` (the double count, **swept**); the battery-slot hand-back (`reclaim_handed_back`, **swept**, both paths); a load whose stop is pending, credited but skipped by the walk (**swept**); paid-source loads in the same walk (**swept**, see Closure); the battery's discharge half (left, below). Already signed: the EV's surplus (`solar − home`), `reclaimable_battery_w` (`charge − import`), the peak guard (reads the import).
**Closure:** `solar_bounded_surplus(..., grid_import_w=, ev_draw_w=)` takes off the import of the last two minutes, as a MEAN (`sustained_import`): the live reading let a kettle's 20 s stop a 3 kW boiler, which then cycled at its minimum on/off times (third review). While a car may charge it is the LOWEST reading of the two minutes, against the car's HIGHEST draw of the same two minutes (`sustained_car_draw`), because a charger's power sensor can trail the meter by a minute at a start, a ramp or a stop (KEBA, cloud boxes) and that import is the car's. Paired with the live draw, a ramp from 11 to 4 kW booked the meter's lagging 7 kW to the house (third review). "May charge" is `car_may_be_charging`: for three minutes after a CHANGE — a car plugged in or out, SEM's offer moving (`_last_commanded_amps_fleet`), or the car's draw falling below the 500 W floor of #739 (a stop lags like a start: a 30 s meter stopped the boiler at every car stop, third review) — and while the car really draws above that floor. Not the reader's `ev_charging`: #739 holds it False until the power reads 500 W, so it opened the window with the lagging sensor, a minute too late (found in review). Not a STATE such as "plugged" or "offered": a full car left plugged in, or a 6 A offer it does not take, lasts all afternoon and held the window open, and the reporter's own square wave was never counted (found in the second review). Not a 100 W floor: KEBA's standby is 110–140 W and held the window open all day. Without a car the mean counts, so a house load that cycles every two minutes still does, at its average. A dark meter gives `None` and takes nothing off (a blink holds, it does not act; running loads hold, nothing new starts); it adds no reading and keeps the ones before it, so a blink does not buy the house two more uncounted minutes (class 58). Only an empty window (start-up, a gap longer than two minutes) starts over. Less two shares that are not the loads': what the chargers' draw explains (a charger leaves a running load above it its sun, #885; past that its Min floor or Now draw is its own grid) and `IMPORT_DEADBAND_W` = 100 W (a zero-export inverter holds a small import on purpose — Victron ESS +50 W — and the stop band leaves 50 W past the export offset). The #938 reclaim takes off only what this side could not (`import_absorbed_by_loads_w` → `reclaimable_battery_w(absorbed_w=)`): a load below a grid-charging pack pays the whole import, and a load above a sun-charging pack beside a steady import pays it once, running or not — paying it twice once running made it cycle. So `surplus + reclaim = draw + export + charge − import`, bounded by 0 and the sun. The add-back counts only loads the walk debits. The active branch offers `remaining` (plus the Tier-1 headroom) alone, and steers only Surplus-mode loads that are not on a paid run (peak_only is the user's; a paid run holds the power its force pass set — offered the sun's ~0 W at night, a watt setpoint was written to its floor every other cycle). A load on a paid source (cheap-hours grid, Tier-2) debits at most the sun that is left: its grid share is its own, and the LIFO, which skips it, would otherwise stop a funded solar load ahead of it. The desired-state twin already debits it nothing. The stop pass (deficit LIFO) keeps develop's order: lowest first, and the next one up when the lowest cannot stop. A first cut stopped only loads the sun did not cover at their turn; develop stopped a covered pump through the sun cap while a started appliance run below it imported, and that cut kept the pump on for the whole run (third review). The battery's slot takes back what is left of the reclaim and never more (`reclaim_handed_back`), so a deficit above it stays a deficit. A load whose stop condition or daily cap is met but which is still on (anti-flicker) is debited like any running load (a paid one at most the sun that is left). The stop pass gives back exactly what the walk took from each load (`_walk_spend`; `_walk_charge_w`, the read draw less the battery's Tier-1 share, only for a load the walk did not reach), not the full draw, and skips a load the walk took nothing from — the battery covers it in full, stopping it recovers nothing, and crediting its full draw ended the pass before the load that made the deficit. Giving back the READ draw skipped an idle switch (on, thermostat off, 0 W read, debited its rating) and kept every load below it off for hours (third review). The loads trace publishes `loads_deficit_w`.
**Guard:** `tests/test_1102_import_counts_against_loads.py` — the reporter's afternoon into the real `SurplusController`; a 4 kW house load two minutes on, one off, still stops the boiler (the old call shape is shown to keep the boiler on); a car start with a minute of sensor lag stops nothing when the plug opens the window, and does stop it when the reader's charging flag opens it, or with no window; a charger's standby does not open it, nor does a full car left plugged in with or without an offer (an open window is shown to hide the square wave); a battery-covered load below the battery is not stopped for an overdrawing one above it; a meter blink keeps the history, a gap longer than the window starts over; a lower load that cannot stop (a started appliance run, a minimum run) makes the pass stop the pump above it (develop's order; see residual 8); an idle switch (0 W read) is stopped and the pump below it runs (giving back the read draw is shown to keep the pump off); a 1.2 kW appliance's 20 s with 500 W to spare does not stop the boiler (the live reading is shown to) and an import that lasts does; a car stop and a ramp-down with a 30–60 s meter stop nothing (the live car draw is shown to stop it at a ramp-down); an unplug, a falling offer and a falling draw each open the window; a load above the battery that overdraws is stopped (the old clamp hid it); a load waiting to stop is debited; a grid sweep of the two addends against the whole balance; the pool reads the same with a load above a charging pack off and on; a load below a grid-charging pack pays the import; a car's floor import and a 50 W setpoint stop nothing; a user's washer in mode Off is not spare sun (crediting it is shown to start the pump); a real `PowerSetpointDevice` settles on the spare power, not its maximum, a peak_only one is left alone, and a paid run is not steered; a paid load does not stop a funded solar load ahead of it, and does take the sun before one behind it; AST: every coordinator `solar_bounded_surplus` and `import_absorbed_by_loads_w` call carries the `sustained_import` of the live import (driven by the reader's dark flag, its window opened by `car_may_be_charging` of the plug and SEM's offer, never `ev_charging`) and the chargers' draw from `sustained_car_draw` on the same car signal, `reclaimable_battery_w` gets `absorbed_w`, and `adjust_power` is never handed `old_consumption`.
**Sweep question:** for every sum that adds a credit back to a measured figure — is the figure signed, or was it cut to one side first? Is everything credited also debited? And is the one side of a split read at the same moment as the other?
**Left open:** (1) The battery's DISCHARGE half is still dropped: in a battery home a Solar-only load can run on the pack while the sun stays above its draw (same shape). Taking discharge off needs the EV battery assist (#885) kept out of it — that discharge is the car's, and a load above the car would yield to it. (2) A load ranked BELOW a charger does not yield to the car's floor import (pre-existing; the import is booked to the car); neither does one beside an unmanaged charger summed into `ev_power`, or a stale-high charger reading after a stop. Strict order would hand the car's grid share back at the charger's slot, as the #576 reclaim is. (3) A watt setpoint offered ≤ 0 W is written to its floor and its belief released the next cycle — a stop without the minimum-run check (harmless for a heater; its restart needs the full threshold). (4) The peak- and phase-shed passes credit a shed paid load's full draw back after it debited less; nothing reads `remaining_surplus` after them today. (5) The desired-state twin (`reconcile_load`) writes a variable load its rated power, and its `surplus_unallocated_w` still counts mode-Off loads as allocated (observer only; off by default). (6) While a car charges (it draws over 500 W) and for three minutes after a car change, only an import that lasted two minutes counts: a shorter one, or a long one that pauses once every two minutes, is not counted, and one that lasts stops loads about two and a half minutes in. A box whose plug sensor lags with its power sensor, and that SEM did not start, still books the car's first minute to the house. (8) A load is stopped for a lower one that cannot stop (develop's order). Develop did this only through the sun cap; now from about 150 W of import, so a pump above a started appliance run or a minimum run cycles on its minimum on/off times while that load runs: it restarts on the lower load's draw (fourth review). Fix: hold back the draw of loads that cannot stop before offering power to the loads above them. (9) `IMPORT_DEADBAND_W` is 100 W: a zero-export inverter that holds more (a Victron ESS grid setpoint of 200 W) stops a running load, and the inverter's import does not change. (11) The mean thins a short import only with room to spare: a 2 kW kettle for 20 s still stops a 3 kW boiler with 100 W or less to spare, 3 kW for 30 s with 400 W (right after a start, or near a cloud). (12) While a car draws, a car whose draw moves by as much as the house import inside two minutes hides that import for as long as it moves (the peak or phase guard, the box's own load balancing, a one-cycle spike in its power sensor); pairing import and car draw sample by sample outside the three minutes after a change would close it. (10) SEM's start ladder for a car that does not draw (6 → 8 → 10 A every 20 s) and each backoff expiry move the offer, so the window reopens for about 10 min after a plug-in and 5 min after each backoff. (7) A paid run by day (a late cheap hour, comfort banking) holds its minimum power and leaves the rest of the sun unused; a Tier-1 assist load can draw up to its battery headroom from the grid when the pack is held (the discharge half again).
Refs #1102 #508 #620 #688 #938 #880 #885 #1021.
### 138. A device's "not now" read as "broken" — an entity's availability taken as its health — GUARDED
**Symptom:** @OddmarDam (Zaptec Go, 2.2.0-beta.9): the ERROR Repair "EV charger control entity is not working" every time the car was unplugged, naming `switch.garage_zaptec_ev_charger_charging` as `unavailable` (#1032).
**Root shape:** some integrations publish a control as `unavailable` while its command does not apply. Zaptec's "Charging" switch is available only while resume or stop is valid (`is_command_valid`): not in mode Unknown, with no car, a full car, or a car waiting for current. HA core's Wallbox pause switch is unavailable while DISCONNECTED / READY / LOCKED / LOCKED_CAR_CONNECTED / UPDATING / ERROR / UNKNOWN. #824's pre-flight read every `unavailable` as "renamed, removed or never loaded" — the device's answer about its state, read as a fault of the entity.
**Where it lives:** `SEMCoordinator._check_charger_control_entities` (the instance, **fixed** for the start/stop entity). The enable path (`ChargerAdapter.enable_state` → `REPORT_ENABLE_BLOCKED` → #945's Repair) reads the same switch, but only while SEM asks it to charge (left, below). *Assessed and left:* the current entity (below); the SG-Ready relay and hot-water entity Repairs (no "not now" state on a relay or a water heater); `sensor_reader`'s `sensor_unavailable` (a missing reading is missing data, whatever the reason); #915's battery write Repair needs a write that was not reflected; #814's phase-switch check asks only whether the entity exists. **Same report, class 49:** the start/stop field offers `button` in the config flow and the card, and SEM presses it (#804, Wattpilot's "Laden erzwingen"), but the check refused the domain and filed this Repair as `wrong_domain` on a healthy charger (**fixed**: `START_STOP_DOMAINS` — switch, input_boolean, button, the domains SEM acts on, so a `select` start/stop now files; a button never pressed reads `unknown`, which is fine).
**Closure:** `control_entity.device_says_not_now` — an `unavailable` start/stop entity is valid (`not_offered_now`) when the entity is not `restored`, another entity of the SAME config entry on its device holds a real reading, and no connectivity sensor of that entry reads `off`. Only the control's own integration may answer: a router's tracker merged onto the device by MAC, or a helper linked to it, stays live while the charger is offline (found in review). It is asked only while the charger's power is at most `EV_ACTIVE_CHARGE_FLOOR_W` either way: while a charge runs, the stop must be there. The CURRENT entity is never excused: HA skips a write to an unavailable entity without an error, so this check is its only witness, and "while drawing" cannot help — a dead current number may be why the car does not draw (found in review). Missing, wrong domain, `restored` (#824's template number, a restart's warm-up), a device with nothing live of its own integration and an entity with no device all file as before.
**Guard:** `tests/test_1032_device_says_not_now.py` — the rule, pure; the reporter's unplug through the real registries and issue registry (the device's answer withheld files, so the pin is not a quiet clock); the Zaptec modes from the integration's own table; Wallbox with no car; a Wattpilot button; what still files (drawing, feeding back, the floor, restored, nothing live, connectivity off, no device, another integration's tracker on the device, an unavailable current entity); a standing Repair cleared; SEM's real refresh at 0 W and at 7 kW; AST pins that every `validate_control_entity` call passes a real `not_now=` and `domains=`, that every domain the config flow and the card offer for both fields is one the check accepts (each picker counted), and that each start/stop domain is one `ensure_enabled` acts on. Eleven mutants are killed.
**Sweep question:** when an entity reads `unavailable`, is that the entity failing — or the device saying the command does not apply now? Ask the device beside it, and only its own integration.
**Left open:** (1) The enable path: on a Zaptec whose car is full or waiting for current, the switch is unavailable while SEM may want to charge, so the reconciler sends `REPORT_ENABLE_BLOCKED` alone (no current write) and #945's Repair can file after the hold. Availability cannot tell this from Wallbox's LOCKED (#548, a real fault); the brand's status class can. (2) A Wallbox that is idle and LOCKED / LOCKED_CAR_CONNECTED / ERROR / UPDATING no longer files this pre-flight Repair; the enable path reports it only when SEM wants to charge. (5) A saved RESTART button as start/stop now reads valid here; the runtime still refuses it (`names_a_reboot`, #804) with a warning and #627's Repair, but this check does not say so. The check also reads the SAVED key, while the runtime may act on another entity (OCPP's adopted switch, the #1042 pause twin, the Wattpilot heal). (3) A charger power read from a meter faster than the box's own poll can file at a charge start if the switch lags the meter by more than the 300 s hold (existed before). (4) Class 86 residual (2) — two Repairs for one start/stop switch — is now only the drawing and offline cases.
Refs #1032 #824 #945 #548 #804 #807 #912 #1036.
### 139. The crawler and setup answer the same question with two rules — GUARDED
**Symptom:** the #1092 lifecycle suite, 11.10.2026: the crawler offered myenergi and Ohme (a charge-mode select only) and a Zaptec without current rights (start/stop only); setup dropped all three ("missing power sensor or control method") and SEM ran nothing (#1095). A plain `number.<box>_charging_current` was not read as the current control (#1096). A service keyed by `device_id` was offered without the id, so the created charger called it for no box (#1097).
**Root shape:** "what makes a charger" and "which box" were answered twice. Setup kept its own control list (a current service or a current entity) beside the crawler's (`_offer_missing`: a power reading and any way to act). The lexicon said the charger-only names (`amp`, `charge_rate`) count "for kind=charger and nowhere else", but the reader applied them on every device — so adding `charging_current` there would have read an inverter's battery limit as an EV control (#809's trap). The offer filled a box NAME field (`charger_name`) but not the registry id a `device_id` field wants. Kin of class 132 (one fact, two readers).
**Where it lives:** `__init__.py` charger setup (**fixed**: asks `charger_is_complete`, the crawler's rule). `hardware_detection._current_number_role` (**fixed**: charger-only names count on a device the roster calls a charger or that carries a plug or charging reading; a charger's companion kept them until #1141, when R1 stopped reading a companion's current at all). `read_charger_roles` and `charger_from_near_miss` (**fixed**: a current service whose fields include `device_id` sets `ev_service_device_id`, the key the device already sends).
**Guard:** `tests/test_integrations_lifecycle.py` has no known gaps left (the strict xfails flipped); `tests/test_1095_mode_or_switch_only_charger.py` (such a charger starts and stops through its one control, no current write invented); `tests/test_1096_plain_charging_current.py` (the plain names on a charger yes, on an inverter no — `amp`/`charge_rate` failed the second half before).
**Sweep question:** for every "is this a charger / which box" answer, is there exactly one function that gives it?
Refs #1095 #1096 #1097 #1092 #809.


### 140. A reading older than its neighbours counts twice — GUARDED
**Symptom:** PROD 13.10.2026 19:29 UTC: the battery stopped at its reserve; the meter showed the 1.6 kW import at once, the Huawei battery register still said −1450 W and polls slower. The next cycle read both: home 3064 W instead of ~1550 for one cycle (#1105).
**Root shape:** home is the remainder of a balance whose inputs are read at different ages. Every input was live, so the dark-input hold (#1047) could not see it, and the step (1527 W) sat under the 2 kW spike guard. Home Assistant cannot tell a stale register from a steady one: Huawei reports only changed values (`last_reported == last_changed`).
**Where it lives:** `coordinator/coordinator.py::_hold_shown_home` → `_battery_stop_not_reported`.
**Closure:** a grid-import step that matches the battery's still-reported discharge (±30 %), while that discharge did not fall, holds the SHOWN home until the battery reports again, at most 90 s. The steering figure is untouched; a real load of that size is shown when the window ends.
**Guard:** `tests/test_1105_battery_stop_before_its_register.py` — PROD's exact readings, a real same-size load released after the window, a different step shown at once, no battery no hold.
**Sweep question:** which other inputs poll slower than the meter (EV session power, a Modbus battery, a cloud inverter), and does a stop of theirs show up twice?
Refs #1105 #1047 #237 #444.

### 141. The first data set is published before its producer exists — GUARDED
**Symptom:** PROD 12.10 18:32, 13.10 10:10 and 14:15: right after each restart the monthly peak read 0.0 kW for one cycle (~10 s), then its real 2.629 kW (#1106).
**Root shape:** `async_setup_entry` ran the coordinator's first refresh before load management was set up. The first data set is what every entity shows until the next cycle; without a load manager the peak took its dataclass default, 0.0 — a billed peak nobody measured.
**Where it lives:** `__init__.py::async_setup_entry` (order of the first refresh and `async_initialize_load_management`).
**Closure:** load management (it only loads its saved state and schedules discovery) starts before the first refresh; the later call is a no-op.
**Guard:** `tests/test_1106_monthly_peak_after_restart.py` — real HA setup with a saved peak: the load manager holds it when the first refresh runs, and the first data carries it.
**Sweep question:** which other producers start after the first refresh (setup steps between `async_config_entry_first_refresh` and the platform forward), and what does their key read as in that first data set?
Refs #1106 #1069.

### 142. A counter step booked into the window it arrived in, though SEM watched that window idle — GUARDED
**Symptom:** 12 Oct 2026, 03:00:40: a Wallbox counter sat at 5170.12 kWh for six hours with the box idle, then rose 11.18 kWh in one report as a session began (#1101, RienduPre, 2× Wallbox Pulsar behind the MQTT bridge, 2.2.0-beta.16). SEM booked it as the night's charging: car row 24.14 kWh against the box's own session 11.68, home 0.54 kWh for ten hours, true baseload −8.5 kWh.
**Root shape:** a delta model books `value − last` as energy drawn between the two reads. A register that catches up reports kWh from outside that window. The EV rows had no bound on a step but a whole day's fleet ceiling (`_max_daily_ev_kwh`); class 43's bound (100 kW over the time since the value last changed) lives on device counters only, and six hours would hold 600 kWh by it. Only SEM's own watch disproves the step: the box's power sensor read 0 W every cycle.
**Where it lives:** `EnergyCalculator._ev_counter_target` — the fleet EV-day row, the calendar-day copy home subtracts, and each charger's own row (`follow_charger_counter`) (**fixed**); a session's total from the lifetime counter, `session_energy._lifetime_meter` via `ev_control` (**fixed**); a counter no one box owns — the legacy daily EV sensor, the Energy Dashboard EV counter, a counter two chargers name (**fixed**, #1157); what a row owes a counter from before its day began (`owed`), on all three rows (**fixed**, #1159); a report split by the day's start, on all three rows (**fixed**, #1160).
**Closure:** per counter, `_track_ev_pending` keeps `room`: the most its box could have drawn since the counter last moved, in time SEM did not see it idle — charging or a power read that is dark or not the box's own (`EV_COUNTER_BOX_MAX_KW` × time), SEM down or a skipped cycle (`watched_at`, persisted), a live read under the floor (3 × the read, one phase of three). It also keeps `unreported`: kWh SEM saw the box draw that the counter has not shown yet, across moves (a late counter reports in several steps), dropped after `EV_COUNTER_LATE_REPORT_H` seen idle since the box last charged (a dark read or a skipped cycle pauses that count; persisted). A step above `room` + `unreported` + one cycle + the dip window books only `unreported` and this cycle's draw (`_judge_ev_step` → `_ev_counter_foreign`); every baseline moves with the rest. A rise the judge has not seen yet (`calculate_energy` skipped the cycle) is held at the last judged reading (`ev_counter_judged_kwh`), so each reader takes the step out once. The watch starts at a counter's first move; no record (an upgrade, a new install): that move is booked as it stands. Round 2 (18 Oct 2026, beta.21, reopened 19 Oct: the counter sat flat for a day, then rose 19.85 kWh at a plug-in; booked, nothing logged): `room` never let go of unseen time while the counter stayed flat, so every restart and dark read since its last move added up at 44 kW. Now `room` keeps its unseen part apart (`unseen_kwh`: SEM down, a skipped cycle, a dark or foreign power read), and the same wait spends it: once SEM has watched the box for `EV_COUNTER_LATE_REPORT_H` since it last could not see it (`quiet_h`; charging counts as watched), the unseen part leaves `room`. What SEM saw — a charge, a trickle — stays. A move clears it; no record starts the watch after the wait; a store from before treats all of `room` as unseen. After the wait `room` never drops under the draw SEM saw since the counter last moved (`pending`). Round 3 (#1157): the check knew only a box's own counter, so a fallback counter's jump was booked while every box read 0 W. Now each counter carries the boxes it counts (`_ev_counter_boxes`, from the coordinator's `_ev_counter_boxes`): its owner, the chargers that name it, or the whole fleet for a fallback. Their draws add up (a read below zero counts as 0), standby is left out box by box, and `room` grows at `EV_COUNTER_BOX_MAX_KW` × the number of boxes. A box with no power read of its own, or a dark one, leaves the counter unwatched. The one fleet sensor stands in only for a counter of one box, as before: the Energy Dashboard's power and counter are its first EV device, so that sensor cannot say other boxes are idle. Over several boxes `pending` adds up all of them, so only a counter of one box seeds `owed` at the anchor. Round 4 (#1159): `owed` never ran out. A counter showed part of a session after the day began, then the rest in one jump after the wait: judged foreign, not booked, and not paid, so what was owed took the next real charge that day (16.8 of 18 kWh). Now what a step books pays first, oldest first, as before; then the part of it judged foreign pays the rest: the base already took that out of the row, and nothing else did. A rest that comes in a step the check books (with the next session, after a restart, after a dark read) is paid as before. A first fix dropped `owed` after the wait, and the review showed those three rests then booked twice; paying from the foreign part first booked a rest twice when one step held both. And a counter of several boxes got nothing owed, so its late report was booked on both days. Now a counter owes whenever `pending` is its own boxes' draw (`_ev_counter_owes`): its boxes are known, and this cycle read each on its own power sensor (`_ev_counter_own_read`), or the home has one box. The coordinator ties a fallback to the one charger whose device holds it, or whose own power sensor the Energy Dashboard pairs with it (`_ev_counter_charger`); one it cannot tie keeps the whole fleet and is marked `guessed`, which owes nothing. Swept: a one-box counter whose box is not read on its own on a home of several boxes took the fleet's draw as `pending` — other boxes', not its own — and owed it, so another box's draw took its real moves; it owes nothing now. A damaged negative `owed` no longer books kWh no box drew. Round 5 (#1160): a counter showed part of an evening session before the day's start and the rest after it. At the anchor only `pending` was owed, which is nothing once the counter has moved, so the rest was booked on the new day too, while the old row still held the session's power read: on a row that moves up only. Now each row keeps the value it ends each cycle with (`row`, stored). At the day's start (the day right after the stored one) `_ev_row_held` compares it with what the counters showed (`anchor` + each counter's move), and adds what the closing row still owed: that is what it holds above them (without the second part a counter flat for a whole day had its report booked again, review round 6). A new row that moves up only then owes a counter whose boxes read idle (`_ev_counter_seen_idle`) `unreported`, or `pending` if more; all counters together owe no more than the closing row held above them plus the new row's anchor (`_ev_owed_at_anchor`): `pending` whole first, then the late parts share what is left by size (sharing all of it by size handed one counter's `pending` to another's high read, review round 7). A row that followed its counters down or up holds none, so the new day books the rest (before, a counter that had not moved when the row rose to the others was owed and booked on neither day). The part above `pending` (`late`) can be a power read above the meter, which the counter never shows; seven reviews found ways it took real kWh the power read missed, so it is held to what can only be a late report. `pending` is paid first, as before. `late` is paid only by the part of a move that SEM watched every box for since the counter last moved (nothing `unseen`, no gap), with none charging now, above what it saw them draw since (`_ev_counter_late_step`, from `_track_ev_pending`). It is owed only in an anchor cycle SEM watched, and lives only while SEM keeps watching the boxes idle: at a charge, a dark power read, a gap, or after `EV_COUNTER_LATE_REPORT_H` (as `unreported`), what is left goes before any payment, also in a cycle no counter reads. A row the counters own, and a box still charging at the anchor, owe `pending` only. No `row` (a store from before, a damaged one), a stored day that is not the day before, and any other anchor (a counter that went back) owe `pending` as before.
**Guard:** `tests/test_1101_ev_counter_catch_up.py` — the reporter's night books 0 (60 s and 10 s cycles) and the session after it in full; with the judge off it books 11.18; a restart two minutes long and a skipped energy cycle do not hide it; owed kWh are paid, not doubled; a cloud report while charging, a report after the stop, a late report in two steps, one a little above the power read, a counter 10 min late every 5, a dark power read, a box without its own power sensor, two hours down, a skipped cycle, a first step before the power read rises, a trickle, an upgrade and a store from before #1049 are all booked; a high power read's rest is dropped after the wait, also with a dark read now and then; counters switched off are not held; room, watch, unreported and the idle count survive the store. Round 2: the reporter's day (30 min down, hours idle, then 19.85 kWh) books 0 with a full and a partial counter set; inside the wait the unseen time still counts, a restart or a dark read late in a wait starts it again, a trickle read and a charge SEM saw (reported 125 min late) stay, also with no record and after an upgrade from an older store, watched charging counts toward the wait, a move clears the unseen part, no record starts the watch after the wait, a damaged watch time starts the wait again; the wait and the unseen part survive the store, an older store spends all of `room`, damaged or negative values are dropped. Switching off each part fails its tests. `tests/test_1157_shared_ev_counter.py`: a jump in the legacy daily sensor, the Energy Dashboard counter and a counter two chargers name books 0 with every box at 0 W, or both in standby (300 W each); with the check off it books in full; a rise not checked yet is held; charging on either box, both at once, two dark boxes (twice the room of one), a box without its own power read, a dark box, two boxes on one fleet sensor and a trickle beside a read below zero are booked; another box's draw is not owed, and one box's late report is owed, not booked twice; every counter the coordinator hands over gets its boxes, and every call passes them. Six mutants of the fix are killed. `tests/test_1159_late_report_owed.py`: the jump judged foreign pays what is owed and the next session is booked in full (16.8 before); a foreign step pays no more than is owed; a foreign step that also holds the rest, and a catch-up with the late report in one step, book it once; a report three hours late with the counter flat, two steps inside the wait, a rest with the next session, after a restart, after a dark read and while the next session runs are all paid once; a rest never reported comes out of the next charge (pinned); the Charge-by row and the charger's own row let go too; damaged and negative owed values; a counter two chargers name, a fallback tied to one box, and both boxes late are owed (11.0 before); a guessed fallback owes nothing; several boxes must each read their own power; a box SEM does not read owes nothing; the coordinator ties by device, by the service device and by the Energy Dashboard's power, and not for two chargers on one device, a power and a device that disagree, a charger with no power sensor or no id, or no answer; every call passes `guessed`. A foreign step that does not pay, a foreign part that pays first, and a one-box counter owed without its own read, each fail tests. `tests/test_1160_split_report_owed.py`: 0.6 shown before the day's start and 1.2 after it books 0 on the new day on a row that moves up only (1.2 before), at midnight and at Charge-by; across a restart the rest is owed; a row the counters own that dropped to them (also in its last minute, also with a new row that moves up only) or rose to them books the rest; a power read 80 % above the meter takes nothing from the new day on the calendar row, the EV-day row and the charger's own row; on a row that moves up only a charge SEM missed later keeps every kWh: SEM down soon after or after the wait, a counter dark for a cycle or stale for two after a restart, a charger cloud dark two hours, a power read dark, a counter dark through the wait, a seen session in between (shown as it runs or after), a session past the start, a charge shown hours later after a seen one, a counter dark through a charge; a counter flat for a whole day is still owed (also across a restart); nothing late is owed right after SEM was down; `late` goes at a charge, a dark read and a restart; `pending` is paid first (an hourly counter: 9.78, as before); `pending` is kept whole and the late parts are shared by size, held by both anchors, `pending` counts when more, a box still charging owes `pending`; a store from before, a damaged `row`, `late` or baseline, a stored day that is not the day before, and a counter that goes back mid-day owe `pending` as before; `row` and `late` survive the store. Pinned, left open: a charge across the start and a rest shown while the next session runs (#1161), and a rest shown after a restart, are booked twice, as before. Owing `unreported` on every row, while charging, or never; no cap or a cap without either anchor; rows compared at every anchor or after a missed day; `late` paid while charging, after unseen time, never, or kept through a charge, a dark read or a gap; and the fleet `row` kept before an adoption, each fail tests.
**Sweep question:** for every counter delta booked as energy, ask whether SEM watched the window the delta claims, and what it saw there.
**Left open:** (1) `night_backfill` books recorder statistics of the same counter; history has no watch to compare with. (2) Solar counters by day (`_reconcile_solar_energy`): a catch-up while PV reads live is still booked; at night #681 already absorbs it. (3) A box whose live power sensor reads 0 W while it charges (stuck, not dark), with a counter that reports in large steps, now books only what that sensor saw. (4) Unseen time counts at 44 kW until SEM has watched the box for the wait: within two hours of a restart or a dark read, about 15 minutes of it lets an 11 kWh catch-up through. So does a catch-up within `EV_COUNTER_LATE_REPORT_H` of a session whose power read was high, up to that rest. The other way round, a counter that reports what the box drew unseen more than `EV_COUNTER_LATE_REPORT_H` after SEM could see it again is no longer booked (#658's recovery now has the wait `unreported` has). With no record yet (a new install, a new charger, an older store), a seen charge reported after the wait keeps only the draw SEM saw (`pending`) plus one cycle: a counter that reads more than that above the power sensor is refused. (5) Power dark while charging, then late steps after the box is seen idle: steps above `unreported` are not booked. (6) Why the register caught up is in the bridge or the box, not found here. (7) With no power sensor per box, a counter of several boxes is not watched (#1157): the one fleet sensor may read one box only. On such a home of several boxes no counter owes (#1159): the fleet sensor may have put a box's draw into the old day, and its late report is then booked on both days (the row errs high, not low). (8) A fallback SEM cannot tie to one charger (a template sum, a helper with no device, two chargers on one device, a charger with no power sensor of its own) is still given the whole fleet and owes nothing: its late report of charging from before the day's start is booked on both days. Only a setting saying which boxes it counts could answer that (#1159, design). (9) A rest the counter never shows (a power read above the meter) stays owed for that row's day and comes out of the next charge: the two days together match the counter. Dropping it after a wait books a rest that does come twice, and a cap at what SEM saw drawn books it twice when the power reads high (both tried for #1159, design). (10) A counter that showed part of a session before the day's start and the rest after it owed nothing (only `pending` was owed), so the rest was booked on both days: **fixed** on rows that move up only, for a session that ended before the start, with a move SEM watched (#1160, round 5). After time SEM did not watch (a restart, a dark read) a move may be a charge it missed, so a rest shown then is still booked on both days, as before (design). Where the closing row holds more above its counters than they still owe (another charger with no counter of its own), the cap is loose; where it holds less, owed is cut by size across counters, not per box. Inside the late-report wait, a watched idle move pays `late` first, so the last minutes' report of a session SEM saw, from a counter a few minutes late, can pay part of a high power read; it is kWh the row's power read still holds. (11) While a box charges, SEM cannot tell its counter's late report from the new charge, so a car charging across the day's start was booked on both days. **Fixed** by a decision (#1161): the counter decides the total. Each counter owes what its day drew above what it showed; its next moves pay it, whatever the box does; a rest rolls over one more day start, then goes. The #1160 `late` rules are gone. Trade-off: a power read above the meter is taken off the next day, which can then show less than it charged.
Refs #1101 #1049 #782 #658 #681 #1024 #1146 #1157 #1159 #1160 #1161.

### 143. A key filled with the English text passes every key-presence test — GUARDED
**Symptom:** the Configuration tab mixed English labels into French, Czech, Polish … (210 per language), and the setup screens had ~165 English texts per language (#1129). Nothing errors.
**Root shape:** the parity tests (`test_dashboard_translations.py`, `test_674`) check that every language HAS each key. A new key is added in English and the same text is copied into the 15 others, which satisfies them. #675 fixed the same drift once by hand and added no check, so it came back.
**Where it lives:** `dashboard/translations.json` (card labels, `config_*` help) and `translations/*.json` (setup steps, Repairs). Both **swept**: ~7,300 texts in 15 languages.
**Closure:** translated; texts that name a card label (#1040 help, #1103 Repairs) now use the label of that language.
**Guard:** `tests/test_1129_untranslated_prose.py` — a value with three or more plain English words that equals English fails. Hyphenated or dotted names (`Open-Meteo`) and codes are not words, so no exception list.
**Second instance — #1227.** The two grid-guess Repairs (#1188) were English in 14 languages, but each named the settings in its own language (`**Netzleistung**`), so no text equalled English and the guard passed. The sweep found two more shapes it missed: an English paragraph left after a translated one (the "SEM believes this one is its own fault" close of three Repairs, a setup step, an options step), and an older English text that English has since changed (the setup's last step, the off-peak rate, two grid power labels, four Configuration help texts). The review found English menu paths and zone names kept in bold in three Hungarian and Romanian Repairs, and one help text in 14 languages that still said the forecast switch stops all spending (English: it stops only the sale). ~170 texts in 15 languages, all **translated**. **Guard:** the test now compares with names, codes, placeholders and quoted names taken out; fails a value that holds a sentence of its English text (four or more words) or keeps one of its bold names of three or more words; and fails any sentence of three or more words with a word only English uses (`the`, `your`, `when` …). `are` (Romanian), `have` (Danish) and `been` (Dutch) are words of other languages and are not on that list. Each rule fails on the files before the fix; the old rule passed them.
**Left open:** a value of one or two words (`Battery`, `Charge Tonight`) copied from English is not caught. A translated text that English later changed keeps the old meaning, and no rule can see that; the help texts found this way (German, Dutch, Chinese, and the forecast switch) were brought up to date. A bold English name of one or two words (`**Auto-start**`) is not caught.
Refs #1129 #675 #674 #1227.

### 144. A card reads a member it never defines — JavaScript answers `undefined`, not an error — GUARDED
**Symptom:** the load list's minimum run and pause fields took any value (#1128). The Solar card's per-string rows showed a hand cursor, and a click did nothing. Nothing in the log.
**Root shape:** a card reads `this.x`, and no line in the card or `SEMLitBase` sets or defines `x`. JavaScript gives `undefined` for a missing member, so `${this._prefix}name` becomes `undefinedname` and finds no entity, and `this._fireMoreInfo?.()` calls nothing. Two names for one thing invite it: every card kept its entity prefix in `_prefix` (which `SEMLitBase._valLabel` reads), the load list in `entityPrefix`, and one line copied from another card used the other name. Close to the unbound name in class 31, but with no error at all.
**Where it lives:** `sem-load-priority-card.js` (`_antiCycleBounds` read `_prefix`), `sem-solar-card.js` (`_fireMoreInfo`, defined only in the flow and system diagram cards), `sem-control-card.js` (`_showHelp`, whose toggle was removed in June: dead, no effect), `sem-ev-progress-card.js` (`_prefix` was a method, so a base read would get the function text; it read nothing through the base yet). All **swept**.
**Closure:** the load list and the EV progress card keep the prefix in a `_prefix` field, like every card. `_fireMoreInfo` lives once, in `SEMLitBase`. The dead help line is gone. A typed anti-cycle value is limited to the published range (`antiCycleValue` in `util/load-sections.js`, called by `_onAntiCycleChange`): an input's min/max limit its arrows, not typing. The arrows stop at 1, because 0 turns anti-cycling off.
**Guard:** `dashboard/card/test/member-defined.test.js` — loads every card with Lit replaced by a stub and fails when the source reads `this.<name>` that the class chain, a real instance, a write in the card (or in `SEMLitBase` for its cards), a declared property, or a short list of browser element members does not define. Every card keeps the prefix in a `_prefix` field, never a method. The real load list finds the published range, and its change handler sends the end of the range for 500, nothing for an empty field or 0, and puts back what the device holds. All of these fail on the old source. `anti-cycle-row.test.js` pins the value rule.
**Sweep question:** for every `this.x` a card reads — which line sets it, and is that line in this card or its base?
**Left open:** reads by bracket (`this[key]`) and members of other objects (`dev.x`, `config.x`) are not checked. The check reads text, not a parse: a ` //` or a regex holding `/*` inside a template can hide a read after it on that line.
Refs #1128 #914 #1053.

### 145. A status sensor asked for by a missing device class — HA's `enum` class fails the test — GUARDED
**Symptom:** on Home Assistant's own Peblar test data (HA 2026.8.2) a Peblar found through the device list got no plug and no charging sensor (#1126). SEM read "no car" all the time and never started a charge. Nothing errors: the charger has power, control and start/stop.
**Root shape:** a brand rule meant "a text sensor, not a reading" and wrote "no device class". Home Assistant gives a sensor with a fixed list of states the class `enum` — what a status sensor is — and integrations move to it. Every one that did fell out of the rule. Close to class 42 (a shape asked where HA says the role), but the other way: the rule refuses what it wants.
**Where it lives:** `_discover_peblar` and `_discover_easee` in `hardware_detection.py` — the only two brand functions that tested a class for a status sensor. Both **fixed**. A zero-config Peblar save from before the fix had neither sensor — **healed** at startup (`_fill_state_sensors_of_own_save`). Not here: the generic roles path (`read_charger_roles`) reads a status sensor by its options and never asked for a class.
**Closure:** `_is_state_text(entry)` — no device class or `enum` — is the one test. Peblar also reads its translation key `cp_state`: the id is built in the install's language (de `…_zustand`, nl `…_status`), the key is not. The heal fills only SEM's own save (the id setup gives that box, from a brand path) with neither sensor, and only when its power and controls are what detection finds today: a Peblar saved before #1035 can hold one phase as its power and the single-phase switch as start/stop, and seeing the car would put those to work (the review of this fix). A charger the user set up keeps what they chose; the forms require both sensors.
**Guard:** `tests/test_1126_enum_status_sensor.py` — core's Peblar in both orders, through the brand rule, registry discovery and the report; a Peblar in four other languages; the bound states read as the coordinator reads them; Easee with and without the class; the heal (fills both, runs once, leaves alone a user's charger, a half-set one, a pre-#1035 save and a charger only the roles found; runs before the charger list is read; the real saved option sets stay as they are); an AST check that no `_discover_*` function asks for a missing class (`is None`, `== None`, `== ""`, `not dc`, `in (None, …)`), with a probe for each shape, and that no `_BRAND_HINTS` row asks for none. The rig's Peblar pin (`test_rig_correct_picks.py`) and golden file now carry both sensors.
**Sweep question:** for every device-class test in discovery, is "no class" standing in for a kind of sensor that HA has a class for?
**Left open:** a Peblar the user set up by hand with another sensor keeps it. A zero-config Peblar save from before #1035 with wrong power or start/stop gets no state sensor (warning in the log; set it up again).
Refs #1126 #1038 #1035.

### 146. A check every unit must pass, asked of the first unit only — GUARDED
**Symptom:** on a two-battery home the second battery could ignore every write SEM sent, and only the log said so (#1124, found in #978's note: two Sessys). No Repair, no verdict on the card. The first battery got both.
**Root shape:** one accessor answers "the battery" — `_primary_battery_adapter()`, the first in the list — and a check that every battery must pass was routed through it. The accessor came from class 74's fix: three dead `self._battery_adapter` reads were brought back to life through it, and so came back for the first battery only. Close to class 52 (a fleet read as one), but these are SEM's own adapters, and what is lost is a warning, not a reading.
**Where it lives:** `coordinator.py` — the #915 write read-back and its Repair (**fixed**: `_verify_battery_writes` asks every battery of the last cycle, `_live_battery_adapters`; the card gets False when any battery's write was not kept, and the highest strike count); the #827 Deye rate note (**fixed**: `_battery_discharge_rate_caveat`, any battery). Asking every battery broke the Repair's clear: any kept write cleared every raised Repair (class 84 left open (4)), so the first battery's kept writes took down the second one's, and it was filed again on its next miss. **Fixed** (class 83): a kept write clears only the entity it proved. A Repair two batteries share on one entity (#531 warns) stays while the other battery has three strikes and its last miss was there. Scoping the clear showed two gaps in `battery_adapters/generic.py` that the old clear hid (review): the select's held verdict named whatever entity the limit verdict had just proved (**fixed**: the verdict carries its entity), and a select proved itself only after a miss in the same lifetime, so its Repair from before a restart stayed (**fixed**: a flip SEM sent that lands is proof). A synthetic `primary` left in the adapter cache once b1/b2 exist is not asked. Assessed and kept: `_run_battery_pipeline` (#845 mode watch — one install-wide entity; its expected modes from the first battery's brand are class 84 left open (3)) and `_export_control_adapter` (the last fallback after holder and capability, #955).
**Closure:** a check every battery must pass loops over the batteries; `_primary_battery_adapter()` is for questions with one answer for the house.
**Guard:** `tests/test_1124_every_battery_is_asked.py` — real generic adapters on one fake HA through the real per-cycle method: the second Sessy's refused mode change and a second battery's ignored limit each file one Repair; the first battery's kept writes after it clear nothing of the second's; a shared entity files once and clears when the other battery stops writing; a select that lands in the cycle the limit is judged is cleared; a fresh lifetime's first landing clears the select's old Repair; a stale `primary` holds nothing; the card verdict over every battery in either order; a Deye second in the list has its note. An AST check lists every `_primary_battery_adapter()` caller with why the first battery is enough (a new caller fails until declared, a stale one too), with a twin that fires on the old #1124 code.
**Sweep question:** for every check or warning about "the battery" (or "the charger"), would a second one need the same check — and is it asked?
**Left open:** the discharge-limit de-dup keyed on the SENT value is class 97, not this class (#1138).
Refs #1124 #978 #915 #827 #933.

### 147. A fallback to the first unit's store, read for every unit — PARTIAL
**Symptom:** a second charger with no current control of its own was given the first charger's current number, its current service with the service's device id and fields, its power sensor and its current sensor — and SEM set the first charger's current whenever it drove the second (#1149). The config card's "Add charger" saves exactly such a card (an id, a name, a minimum current, a priority), and the card says it stays inert until it is wired; a Zaptec Go offered with start/stop only (#1141) or a card whose site limit was taken out (#1144) has no current control either. Earlier instances of the same read: the second charger's start/stop switch, charge mode and start/stop services (#1095), and its status sensor (#1143).
**Root shape:** a charger lives in two stores — its card in `ev_chargers` and the old flat top-level keys, which hold the FIRST charger's wiring (the setup wizard writes both; the v2→v3 migration made card 0 from them). One resolver, "the card, else the flat key", was used for every card. That is right for the first charger (a legacy card can lack what its flat mirror holds) and wrong for every other one: for them the flat value always names another box. Each fix so far moved a few keys to a second, card-only helper (`_own`), so every key not yet moved kept the old read. Kin of class 2 (charger[0] leaks into charger[1]), but through config, not runtime state.
**Where it lives:** `__init__.py` charger builder (**fixed**: one helper, `_cfg`, takes no key in `hardware_detection.CHARGER_WIRING_KEYS` from the flat store for a charger after the first; `_own` is gone, so the gate and the wiring cannot read two rules again; a card that ran only on the first charger's keys is now skipped with a WARNING; limits, phases, priority and the KEBA/pilot-cycle flags are settings and still fall back). Checked and already right: `coordinator/ev_control.py` `_charger_meter_entity`, `_collect_ev_counter_entities`, `_own_ev_counters`, `_update_per_charger_detector_energy` (flat only for the first charger); `sensor.py` `_subscribe_ev_power_upstreams` and `sensor_reader.py`'s house flags (flat only with one charger); heat pump rows (each extra row reads its own row only); battery control lists (the global entity is the one inverter's, on purpose). **Open:** `coordinator/ev_availability.py` `plan_connectivity` read the flat plug key for any charger (#1150, closed: class 149 — `has_plug_sensor` counts the flat keys only with one charger); removing the first charger left its flat keys to the next one, which then read them as the first (#1154, closed: below).
**Closure:** every key that names a box or how SEM talks to it is listed once (`CHARGER_WIRING_KEYS` = the report row's keys plus the service's device id); a charger after the first reads those from its card only.
**Guard:** `tests/test_1149_second_charger_own_wiring.py` — the real setup with the wizard's flat mirror of a fully wired first charger (every value marked): a start/stop-only second charger holds none of it in any attribute, and driving it through `_set_current` and its adapter sends nothing to the first charger's box (on the old code it sent the first charger's service with its device id); the config card's new charger is not built; a second charger's own current number is written with no service on top; the first charger still reads the flat keys; settings still fall back. An AST check sorts every key the builder names in a `_cfg` call into wiring or a listed setting, so a new key fails until sorted (keys `resolve_max_current` reads through the passed `_cfg` are checked by name).
**Sweep question:** where SEM keeps N units as a list plus an old flat copy of the first one, does any per-unit read fall back to the flat copy for a unit that is not the first?
Refs #1149 #1095 #1143 #1141 #1144 #1150 #1154.
**Second instance — #1154, the first charger removed.** **Symptom:** removing the first charger (the config card's ✕, `remove_charger`) made the next one first, and the removed charger's power sensor, current control, current service and start/stop switch stayed in the flat keys. The builder lets the first charger fill a gap in its card from there, so the new first charger read the removed charger's power and SEM set the removed charger's current for it; the config card's new charger, made first, was built on the removed box outright. **Root shape:** the flat keys are the first charger's only while it stays first. #1149 keyed the rule on the position ("the first may borrow"), and no remove asked whose the flat keys were: a remove changed the list, never the flat copy. **Where it lives:** every path that removes the first charger — `remove_charger` in `__init__.py`, the Configure dialog's remove (`config_flow.py`, saved in `async_step_settings`), and the repairs at start that drop a charger (the refs folding a half card into a complete one, `_drop_meters_saved_as_chargers` #1036); and every reader of the flat keys on the first charger's behalf (the builder's `_cfg`, the sensor reader, the energy counters, `plan_connectivity`). **Closure:** one question, `charger_refs.flat_wiring_is_of(card, flat, device_of)`: the flat keys are this card's when it holds one of their entities (or the service's device id) or sits on their HA device; they are another box's when both name a role with different entities, when the card names no entity, or when the card has no power sensor and takes the flat one (the wizard always saved one). An old save that split one box between card and flat keys, each naming other roles, stays the card's (the #1095 pins). The device only says yes: a site limit sits on the site's device, and the builder must still see it to refuse it (#1144). `_drop_flat_wiring_of_a_removed_first` clears `CHARGER_WIRING_KEYS` from both `entry.data` and `entry.options` (a key left in one shows through the merge) when the answer is no: `remove_charger` and the dialog's save ask it when the first charger's id changed, and setup asks it every start after the repairs and before `full_config`, so every reader sees the same answer and a save the old remove left is cleared once, with a WARNING. Settings (limits, phases, priority) stay. The builder asks it once more: `_cfg` gives the first charger no wiring key from the flat store unless they are its own. A pre-migration save (no charger list, no refs) is its flat keys and keeps them; once refs exist, an empty list after the last remove clears them. **Guard:** `tests/test_1154_removed_first_charger_flat_keys.py` — the real setup with #1149's marked flat mirror: the card's ✕ on the first charger (the service's own write checked with the reload held back, then the reload: the next charger holds none of it), on a second charger (kept), on the last one (cleared); the dialog's save on its own and walked end to end with a half first card; a save the old remove left, cleared at setup with a WARNING; a start repair (#1036) dropping the first charger; the builder's check alone with the setup clear switched off (a start/stop-only first charger takes nothing, the card's new charger is not built); and the ownership rule: a shared entity, the service's device id, one device (yes only), a shared service name that is not an identity, a split old save, a card with no power sensor, a pre-migration save. **Sweep question:** when a list loses its first unit, does every store that mirrored that unit lose it too? **Left open:** the flat keys are cleared, not re-mirrored from the new first card; nothing reads them for it that its card does not hold. Refs #1154 #1149 #1036 #1054.

### 148. A missing answer read as "no" — unknown taken for gone — GUARDED
**Symptom:** a charger with no plug sensor of its own was never started again once it stopped drawing (#1153). It shows a car only while it draws more than 500 W (the physics defence, #285+1). Three cycles after the draw stopped the plug confirmation read "no car", two cycles later the reconciler parked the box off, and from then every mode answered "EV disconnected": the car waiting on the cable never got another offer.
**Root shape:** a boolean with no room for "I cannot tell". The reader publishes `ev_connected=False` from an empty sensor id, and every consumer read that False as an answer. The plan layer had already learned the difference (#638 night 3: `plan_connectivity` returns `None` for such a charger), the control loop had not. Kin of class 138 (a "not now" read as "broken") and of #875 (a never-read SOC is not a 0 % pack).
**Where it lives:** `coordinator/decide.py` — the "EV disconnected" idle of every mode and the #548 ceiling guard (**fixed**: they read `ChargerPower.car_absent`, which is `not connected and plug_known`); `coordinator/charge_stability.py` — the out-of-scope reset on a disconnect, which also ended the #610 give-up streak and backoff and the #975 interruption budget (**fixed**: reset on `car_absent`; a stop of an offer to a charger whose car is not known spends no interruption); `coordinator/charger_reconciler.py` `observe` — PARK_OFF and the stop-war end on a disconnect (**fixed**: an unknown plug is "a charger that cannot say", the field's existing default); `coordinator/ev_control.py` `_update_session_tracking` — the session ended on the confirmed "no" (**fixed**: the loop passes `plug_known`, and an unknown is not an unplug). `coordinator/build_view.py` sets `plug_known` from `ev_availability.has_plug_sensor`, the test `plan_connectivity` already used, factored into one helper so the plan and the control loop cannot disagree. Checked and already right: the "charging started" notification gate (#584) and the stall re-enable (`_should_reenable_charger`) read the confirmed `connected`, which a sensor-less charger only has while it draws, so neither speaks before a draw; a SessionData starts only on a draw over 50 W; the phase planner (#1008) asks no power question without a known car.
**Closure:** "no car" is an answer only from a charger that can say. Without a plug sensor the car is unknown unless the charger draws, modes run their normal logic, and the offers to a charger that may be empty are bounded by the existing ChargeStability machinery: a start ladder, a give-up after `START_KICK_GIVEUP_S` at the ceiling, and after `FULL_CAR_GIVEUP_STREAK` give-ups a backoff of `FULL_CAR_BACKOFF_S`, doubling to its cap — ended at once by a real draw.
**Guard:** `tests/test_1153_sensorless_charger_restart.py` replays the chain (confirm, view, decide, stability, reconciler) cycle by cycle: a draw, then hours at 0 W with surplus — a start offer, no "disconnected", no PARK_OFF in every surplus mode and always_max, a bounded count of give-ups over eight empty hours, a draw ending the backoff; a charger with a plug sensor still idles and parks; the session survives an unknown and ends on a reported unplug. Extended: `test_610_full_car_backoff.py` (the backoff and streak survive an unknown plug; no interruption spent), `test_park_on_disconnect.py` (observe; no park), `test_638_plug_confirmation.py` (a confirmed "no" without a sensor is unknown), `test_638_night3_findings.py` (one helper for the plan and the view), `test_584_per_charger_connected.py` (no notification on a start offer), `test_ev_connected_physics_defence.py` (the reader and the view at rest and drawing). The scenario harness declares a plug sensor, since its timeline's `ev_connected` is one's answer. Five mutants of the fix are killed.
**Sweep question:** where a boolean is filled from a sensor that may not exist, does any consumer read the fallback False as the sensor saying no?
**Left open:** (1) a sensor-less charger's session is no longer ended when its draw stops: nothing can say the car left, so it runs on across pauses and later charges. (2) A new car plugged into a sensor-less charger during a backoff waits for the backoff to end (at most 80 minutes); the box's own auto-start, where it has one, is not held. (3) In a multi-charger home a charger with no sensor of its own still took the fleet value in `build_charger_view` (#1150, closed: class 149). (4) always_max is outside the stability layer: an empty sensor-less charger in that mode holds one standing offer at its maximum (one start, no ladder, no repeats).
Refs #1153 #638 #285 #610 #975 #1011 #584.

### 149. A fleet OR read as one unit's answer — a sibling's car is this charger's — GUARDED
**Symptom:** in a multi-charger home a charger with no plug or charging sensor of its own counted as connected and charging whenever another charger was (#1150). The redirect veto struck it for a draw it never made and vetoed its redirect for the plug-in (#899), the phase planner and sequencer were told it charged (#804/#1008), the pack consent counted its mode for a car it did not have (#1130), and "charging started" could be pushed for it (#584).
**Root shape:** the reader publishes a per-charger map only for chargers with their own sensor, and a fleet flag that is the OR of them. Every consumer fell back to the fleet flag for a charger missing from the map. With one charger that fallback is right — the flag is its own; with more it is the OR of the others. Kin of class 2 (charger[0] leaks into charger[1]) and class 147 (the flat store read for every unit), here through the cycle's readings.
**Where it lives:** `coordinator/build_view.py` `build_charger_view` (**fixed**); the per-charger session swap and the notification gate in `coordinator/coordinator.py` (**fixed**); `_ev_pack_modes` (#1130, **fixed** — its docstring already said the fleet flag is for a single charger only, the code fell back for every one); the #740 night-gate policing in `coordinator/ev_control.py` `_police_opted_out_charger` (**fixed**, and it now carries `plug_known` too, the class-148 sibling the #1153 sweep missed); `ev_availability.has_plug_sensor`, which read the flat plug keys — the first charger's — for every charger (**fixed**, class 147's open item). Checked and already right: the reader's per-charger maps and physics defence (`sensor_reader`), the hints' idle-car list (names only mapped chargers; with no map it speaks of "EV", not of a charger), the plan fingerprint (fleet flag only without any map).
**Closure:** one resolver, `ev_availability.charger_state(cid, power, config, field)`: this charger's own map entry; else the fleet flag only when the fleet is one charger (`fleet_flag_is_own`); else its own draw over the 500 W floor. Its car is then unknown at rest (`plug_known`, class 148), so it is still offered current, and its charging state comes from its own power only.
**Guard:** `tests/test_1150_sensorless_charger_own_state.py` — two chargers, the left with its own sensors charging: the right reads neither connected nor charging, its car unknown not gone; its own draw (not standby) makes it both; no own power reading is no charge; a single charger still takes the fleet value; the redirect strikes stay at zero; the notification gate notifies the left only; the pack consent follows each charger's own car; the flat plug keys count for one charger only and the plan asks no fleet flag for the right; the session swap and the night gate use the same resolver. Five mutants of the fix are killed.
**Sweep question:** where a per-unit read falls back to a fleet aggregate, is the fallback limited to a fleet of one?
**Left open:** (1) a multi-charger home whose plug sensor is only in the flat keys (no card has one) now reads every charger's car as unknown; the flat keys are the first charger's mirror (class 147), and SEM still offers and starts on a draw. (2) A charger with no own power reading in a fleet takes the fleet power as its draw in `build_charger_view` (documented as unreachable there: every charger in a fleet has a power entry); its charging state no longer follows it.
Refs #1150 #1153 #584 #899 #804 #1008 #1130 #740 #1149.
**Second instance — #1183, the battery's brand.** **Symptom:** in a home with a Huawei (or GoodWe) inverter, every other battery without a strategy select or setpoint of its own was built as a Huawei battery. Its charge, sale and stop went to the Huawei battery device (`forcible_charge_soc`, `forcible_discharge_soc`, `stop_forcible_charge`), so a second battery with its own discharge limit would have force-charged through the real inverter (seen on the test server). **Root shape:** `adapter_for` asked one fact of the install — is a brand integration loaded? — and used it as each battery's brand. With one battery that answer is its own; with more it can be another battery's. The #531 gate excluded only batteries with an AC-coupled control of their own. **Where it lives:** `coordinator/battery_adapters/__init__.py` — the auto-detect (**fixed**), the Huawei/GoodWe pins (**fixed**: a pin counts only for a battery whose own entities are that brand's), the #900 pin Repair `pinned_generic_brand` and its #933 "still loading" answer `pinned_generic_pending` (**fixed**: they ask the same rule); `coordinator.py` — the startup self-heal, which rebuilt any generic battery once a brand loaded (**fixed**: it asks `auto_brand`, and only on Auto). The export cut pick `_export_control_adapter` (**fixed**, review): it took the first adapter that overrides the export verb, and the generic adapter overrides it with no number to write. A non-Huawei first battery had cut the inverter's export only because it was wrongly built as Huawei; once generic it took every cut and refused it. The pick now asks `export_control_wired` (a brand's own way, or the generic adapter's set number). Checked and already right: the Huawei adapter's own orphan check (asks about its own integration); the Huawei battery device (the combined `connected_energy_storage` device, the one inverter's). A real pack whose own sensors are all helpers (template power, utility-meter counters) is now generic in a home of more batteries; a log line names its entities, and its slot of the discharge limit list can name the brand's number. **Closure:** one rule, `_own_brand_domains`: in a home of one battery every brand, as before; in a home of more, only the brand that the battery's own entities belong to in the entity registry — its Energy Dashboard sensor or pair, its own energy counters, and its slot of each per-battery control list (`_battery_own_entities`, passed in the adapter context with the battery count). No brand, two brands, or no registry answer: the generic adapter, which sends nothing to a brand's inverter. **Guard:** `tests/test_1183_battery_own_brand.py` — a real HA with the registry and a loaded `huawei_solar` entry: the second battery is generic and its charge and sale send no `huawei_solar` call through the real `_run_battery_pipeline` (on the old code both went to the Huawei device), the Huawei battery still charges through it, the self-heal upgrades only the brand's battery, the GoodWe twin, the pins, the pin Repair, one battery as before, the export pick. Two AST checks: a brand adapter is built only in `adapter_for`, and a brand's load state is asked only where the battery's own brands are asked first. **Left open:** a `deye` pin still drives every battery of a home as the Deye battery (Deye has no one integration to match; actuation is opt-in; #1273). Found beside it, not this class: a restart hands the export cut's saved restore value to the adapters before any exists, so it is lost (#1274).
Refs #1183 #531 #900 #933.

### 150. A memory that only learns — a fact the source stopped giving is kept for ever — GUARDED
**Symptom:** a Zaptec Go saved before the online-sensor fix (#1142) with "Charger mode" turned off kept the online sensor as its charging sensor: detection gave none any more, but the save remembered the old answer, so SEM read "online" as "charging" (#1147). The site limit (#1144) was the first instance and needed a drop of its own.
**Root shape:** a cache kept so a blind read still works (the charger reference's `found`, the crawler's last answer) was updated by merging only (`refresh_found`: `{**found, **live}`). A merge can add and change, never remove, so every role a detection fix takes away lives on. Replacing the cache whole is the other trap: a start during boot reads no states and an integration still loading shows part of its device, so roles would come and go.
**Where it lives:** `charger_refs.reconcile` (**fixed**: `forget_stale`, after `drop_refused`, before the #1151 check). The answer's confidence is `charger_refs.sure_devices` (`async_reconcile` passes it).
**Closure:** a role leaves `found` only when the crawler saw the whole device and its answer does not hold the role: Home Assistant is `CoreState.running` (not just `is_running`, which is true while starting), every config entry of the device is loaded, and each of its enabled entities has a state. Any doubt keeps `found`. `overrides` (the user's) and `cleared` are never touched; a ref left incomplete is no longer marked complete, so a new card for the box can replace it (#1054, as in `drop_refused`).
**Guard:** `tests/test_1147_ref_forgets_stale_role.py` — the old merge as premise; a device seen whole forgets, one not seen whole or not answered for keeps; boot, reload, boot (gone for good); the user's role and clear stay; a device-less charger is not touched; `sure_devices` on real Home Assistant (integration not loaded, HA starting, an entity without a state, a disabled entity, an unknown device); the Zaptec capture with "Charger mode" turned off through the real setup step, loaded and not. Removing the drop or its `sure` gate fails four tests each; ignoring the loaded state fails two.
**Sweep question:** for every store that keeps "what we saw last" so a blind read still works, how does a value leave it — and does that need a read we can trust?
**Left open:** SEM's setup during a Home Assistant restart runs before `CoreState.running`, so only a start after that (a reload, an options save, SEM added later) forgets. A role the user set (`overrides`) that the crawler stopped giving stays: it is theirs.
**Second instance (#1214, 29.10.2026) — the device a ref names:** set once, when the ref is made, and never asked again. @bekovan moved his ABB Terra to his own integration and picked its entities; the ref still named the old integration's device, so once he removed it a Repair said "its device is gone" about a charger that ran, and the old device's `found` filled each role he had not set. **Closure:** `charger_refs.follow_device`, at every start right after the legacy edit is folded: when no entity of the card sits on the ref's device and they sit on another one that holds one of the card's controls, the ref is made again from the card for that device (`card_to_ref`). Only when that device is seen whole (`sure`, this class): then a role it offers that the card lacks is `cleared`, and the card resolves to the same values at every later start — the review showed a move on a partial answer let a later answer add a start/stop switch. `sure` now also asks the devices the saved chargers' entities sit on: a user's own integration gives the crawler no answer. The user's `cleared` and `held` stay; a device another ref names takes a second only when both carry `connector`. A card with no entity on any device keeps its device (the Repair is then true). **Guard:** `tests/test_1214_ref_follows_device.py` — his store as premise; the move, the next start, a start still booting (no move), a later answer with a new role (the card does not change), an entity still on the old device, no device at all, a power meter, a device another charger names, twin connectors, a held role, a user's clear, the plug check flag, a reinstalled integration; the real setup step clears his Repair and names the one old entity he never picked again. **Left open:** SEM's setup during a Home Assistant restart runs before `CoreState.running`, so the move waits for a reload or a Configure save. A charger moved onto entities with no device (template helpers) keeps the Repair (#1248).
Refs #1147 #1144 #1142 #1054 #1214.

### 151. A one-time check keyed on a state an earlier build already changed — GUARDED
**Symptom:** on 2.2.0-beta.20 every start gave a charger SEM saved by itself the plug sensor detection now finds (Zaptec "Charger mode", #1142), with no check of its controls. The #1151 fix checks a charger that read no car before the start; one that got its plug on beta.20 reads one now, so it was never checked, and a Zaptec saved before 2.2.0-beta.5 could hold a switch that does not start a charge, driven once SEM saw the car (#1152).
**Root shape:** the fix's trigger ("the card read no car") is the state the bug itself changed. Every install the bug already reached no longer matches the trigger, and the store no longer says where the plug came from. Kin of class 72 (a gate one path skips), here in time: the path that skipped it was the previous build.
**Where it lives:** `charger_refs.reconcile` (**fixed**: `check_saved_plugs`, right before `hold_new_state`). "Setup's own save" is one helper, `__init__._own_saves` — the startup heal (`_fill_state_sensors_of_own_save`) and the check read the same rule.
**Closure:** a ref not yet marked `plug_checked` is asked once: when it is setup's own save (its id is one setup gives a box the crawler finds) and every state sensor its card reads came from the crawler (none in `overrides`) and is what the crawler finds today, the card it ran on counts as one that read no car. `hold_new_state` then holds the sensors unless its controls are today's, and the heal decides, as for a save that never had a plug; once held, the #1151 check asks every start. The ref is marked once asked, or when it is not setup's own save on a device seen whole (class 150's `sure_devices`), or when it was made at this start (#1151 covers it). No answer for setup's own saves: nothing is marked. A card with the forms' id (`ev_charger…`) or a plug of the user's own is never asked, so nothing the user chose is undone.
**Guard:** `tests/test_1152_beta20_plug_checked_once.py` — the beta.20 start replayed (the merge with no hold) as premise; the Zaptec capture through the real setup step and the real heal (the cable lock replaced before the car is seen, then stable; a missing control keeps the plug away every start; matching controls keep it); the same card under the forms' id is never changed and is marked once the Zaptec is loaded; a marked ref is not asked again; no own-save answer marks nothing; the pure step on core's Peblar (held, the hold lasts, a matching save, not setup's own, the user's plug, a plug detection no longer gives, a blind start, a new ref, a device-less charger, a link as the charge). Removing the check, the own-save test, the override test or the marking each fails tests.
**Sweep question:** when a fix's trigger is a state, could an earlier build already have changed that state — and what tells those installs apart now?
**Left open:** setup's own save to which the user later added by hand the same plug the crawler gives looks the same as a beta.20 plug and is asked once; its controls are replaced only when the heal can match each to detection, as for any own save (#1134).
Refs #1152 #1151 #1134 #1142.

### 153. One way to act taken as the only way — a unit without it is refused, and its saved row stays — GUARDED
**Symptom:** a charger SEM only starts and stops (switch, button, start/stop service or charge mode, no current control) logged `ERROR EV charger registration requires either current_control_entity or charger_service` at every start (#1148). Its load-management row was not written, so a row saved before kept its old control — on a Zaptec, the site's Available current (#1144). Nothing was sent (an `ev_charger` row is never shed by load management), but the row still named the site limit.
**Root shape:** the builder's gate asks "any way to act" (`charger_is_complete`, #1095: current, service, start/stop switch or button, start/stop service, charge mode), but a later consumer still asked the older question, "has a current control", and refused the rest. A refusal that returns early is also a refusal to update: the stale row from an earlier save stays as the truth. Kin of class 71 (the site limit as control) as its residual, and of class 86 (an absence spent as config) in reverse: here an absence was refused instead of written.
**Where it lives:** `features/load_management.py` `register_ev_charger` (**fixed**: a charger with start/stop only is registered with `control_type` `"start_stop"`, no `switch_entity` and no `charger_service`; the row is replaced whole, so a stale control goes; a charger with no way to act at all is still refused, with a WARNING). `__init__.py` charger builder (**fixed**: also hands over the start/stop service and the charge-mode select, so a service- or mode-only charger is not refused). Checked: `_shed_device` and `_restore_device` (guarded by `_peak_managed_elsewhere` for every `ev_charger` row; behind the guard the legacy fallback now writes nothing for a `"start_stop"` row and does not throw its switch, and restore marks it restored); `_shed_plan` and `_phase_candidates` skip `ev_charger` rows; `_get_devices_for_shedding` skips them; `_charger_claimed_entities` reads the stop switch from the row (kept); the coordinator's per-cycle priority write, the dashboard generator and the card's registry row read priority and power only; `_warn_missing_charger_entities` raises its ERROR only for a configured current entity that is missing.
**Closure:** a consumer of a unit asks the same "can SEM act on it" question as the gate that admitted it; when it registers the unit, it writes the row whole, with what the unit lacks written as absent.
**Guard:** `tests/test_1148_start_stop_charger_row.py` — a switch, button, service or charge-mode charger registers with no ERROR and a row with no current control; a saved site-limit row is cleared (also from the claimed entities); the shed writes nothing, and with the #461-peak guard removed neither the shed nor the restore writes a current or throws the switch (killed by removing the `"start_stop"` branch); a current-controlled charger is unchanged; the real setup with a start/stop-only second charger logs no refusal and gets a `"start_stop"` row.
**Sweep question:** where a gate admits a unit on "any way to act", does every later consumer accept the same set — and when it refuses, does an old saved row survive the refusal?
**Left open:** the card's charger row (`device_registry` `_charger_row`) still says `control: {"type": "current"}` for every charger; it is display only.
Refs #1148 #1144 #1141 #1095 #461.

### 154. A "daily" row published from a bucket that rolls at another hour — GUARDED
**Symptom:** with two Wallbox Pulsars, `sensor.sem_charger_<id>_daily_energy` did not reset at midnight while `sensor.sem_daily_ev_energy` did (#1146). The rows carried 15-10's 0.75 and 9.72 kWh into 16-10, kept counting on top of them through the night sessions, and fell to 0 at 08:00 and 11:00 — a different hour per charger, neither midnight nor the night window's end. Then they read 0.0 for the rest of the day, although the cars had charged about 35 and 15 kWh since midnight (the fleet row was right at 50.8 kWh).
**Root shape:** one accumulator, two questions with different days. `_daily_ev_per_charger` rolls at each charger's own Charge-by time on purpose (#280): the night charge must not see its target again between reaching it and the deadline, or it bills the same kWh twice. The sensors published that bucket as the charger's "daily" kWh, whose day is the calendar day the fleet row and the HA Energy Dashboard use. So the row ran past midnight and dropped at Charge-by. The drop also took the night's kWh with it, which is why it then read 0 all day: the cars were done charging by 06:00. Kin of class 55 (two windows on either side of a comparison) and of #645 (four day boundaries, all on purpose): here the window was right for one reader and wrong for the next one.
**Where it lives:** `coordinator/coordinator.py` (**fixed**). `_per_charger_daily_report` (the sensors) and the health check's per-charger-vs-fleet partition (#771) now read `_per_charger_daily_calendar`, a calendar-day view of the bucket. Decisions still read the EV-day bucket through `_charger_daily_kwh` (night remaining, ETA, deadline plan, the car's learned day in #1132). A single charger was never affected: its row reports the fleet's `daily_ev`.
**Closure:** per charger, a calendar slot `{date, offset}` (`_daily_ev_per_charger_cal`); the row is `max(0, bucket + offset)`. At the first cycle of a new local date (`_charger_calendar_day_roll`, before the EV-day check) the offset becomes `−bucket`, so a session across midnight is split at 00:00 on the same cycle the fleet row splits. When the bucket rolls at Charge-by (`_charger_calendar_day_carry`, before the zeroing), the offset takes the day's kWh so far, so the row keeps them. Because the view follows the bucket, the counter follow-up (#1049) carries over unchanged. The slots go into the daily store beside the buckets (`_per_charger_daily_blob` / `_restore_per_charger_daily`). A slot dated before today rolls on the first cycle after a restart, and a store from before the fix has no slots, so the first cycle keeps the bucket as today's. The removed-charger sweep (#1054) drops the slot too.
**Guard:** `tests/test_1146_per_charger_daily_midnight.py` — the reporter's night through the real `_update_ev_intelligence` loop, 5-minute cycles in Europe/Amsterdam, Charge-by 11:00 and 08:00: the rows carry on before midnight; both reset at 00:00; a 23:30–00:30 session is split 1.8/1.8 kWh; no drop at 08:00 or 11:00; at 12:55 the rows hold 35.0 and 16.2 kWh and sum to a midnight-rolled fleet total on every cycle of the day; decisions still see the EV-day bucket (27.72 kWh at 05:30). Restart: mid-day keeps the day; saved 23:55 and up at 00:20 starts at the new day; a store with no slots keeps its reading until midnight. The sweep drops a removed charger's slot.
**Sweep question:** where a row says "daily", "today" or "this month", does it publish an accumulator that rolls at that boundary, or one kept for a decision on another day?
**Left open:** (1) A counter correction that pulls the bucket below its midnight value (pre-midnight kWh adopted down after 00:00) holds the row at 0 until the bucket climbs back; the row does not go negative. (2) Booking is per cycle, so the cycle that crosses midnight lands whole on the new day, as the fleet row does. (3) Decisions and the row now differ on purpose between midnight and Charge-by: the night plan counts last evening's solar kWh, and the card shows today's.
Refs #1146 #280 #1049 #1054 #771 #1132.

### 155. A two-way verdict on a three-way state — "no offer" read as "nothing matched" — GUARDED
**Symptom:** a Tesla Wall Connector with no Tesla car integration showed on the Configuration tab as "entities present, no role matched", with a "Report this hardware" button that opened a prefilled issue titled "no role matched" (#1137). The roles had matched: power, plug, charging and session energy. The box has no control at all, so SEM has nothing to drive.
**Root shape:** the crawler hands the card three cases — an offer SEM can add, a charger found with no control (`charger_roles` set, `missing == ["control"]`), and a device where no role matched — and the card asked one question, "is there an offer?". Every "no" got the third case's words and its report button. The data to tell the second case apart (`charger_roles`, `missing`) was already in each near miss.
**Where it lives:** `dashboard/card/src/util/detect-rows.js` `detectRowLabelKey` (**fixed**) and the near-miss rows in `sem-config-card.js` `_renderDetectedHardware` with `_reportNearMissUrl` (**fixed**). Backend checked and right: `hardware_detection._roles_pass` and the brand walk both fill `charger_roles` and `missing`; R4 (one car with its own charge control) still turns the row into an offer, two cars still set `choose_vehicle`. No new driving: SEM drives nothing it did not drive before.
**Closure:** `nearMissAction(miss)` is the one verdict — `add`, `watch` (roles found, only the control missing) or `report`. A `watch` row says "charger found (roles) — no control SEM can drive" and, under it, that SEM can read it but not start, stop or set it, and that one car integration with its own charge control would let SEM drive it through the car (with two such cars: add it by hand with that car's controls). No report link; `_reportNearMissUrl` returns nothing for it. A device with no roles, or one missing its power reading too, keeps "no role matched" and the report.
**Guard:** `dashboard/card/test/detect-rows.test.js` — the Wall Connector as the rig reports it is `watch`, two cars pick the choice text, no roles or a missing power reading is still `report`, a car-driven offer is `add`; every language has the three texts, the label names `{roles}`, the English never says "no role matched" or "please report"; the card's report URL refuses a `watch` row. `tests/test_1137_watch_only_charger.py` — the rig's Wall Connector alone carries the fields the card reads, with one car it becomes an offer (vacuity twin), with two it carries `choose_vehicle`.
**Sweep question:** where a card turns a report into words, does each state the backend can produce get its own words — or does "not the good case" fall into the worst one?
**Left open:** the diagnostics download keeps the brand walk's note "entities present, no role matched" for every brand near miss, roles or not; the card does not show it.
Refs #1137 #915 #1032 #1054.

### 156. An average whose energy runs one interval ahead of its time — GUARDED
**Symptom:** `sensor.sem_battery_session_avg_power` read 548,700,000 W on the first update of every battery session on a ~5.5 kW GoodWe, then 11000, 8250, 7340 … — exactly P × (n+1)/n (#1155). As a `measurement` sensor every spike went into the recorder's long-term statistics.
**Root shape:** a session started at `now()`, and the same cycle booked a whole update interval of energy. The duration (`now() − start`) was microseconds on the first update and n intervals on the n-th, while the energy covered n+1; the average divided the one by the other.
**Where it lives:** `coordinator/coordinator.py` `_update_battery_session_tracking` (**fixed**: the session starts one update interval back, so duration and energy span the same time).
**Closure:** a session that books the cycle's interval of energy on its first cycle starts that interval earlier; average = energy over a duration that covers exactly the booked intervals.
**Guard:** `tests/test_1155_battery_session_avg_power.py` — the reporter's session at 10 s and at 30 s cycles: the first and every later average equal the battery power within 1 %, one minute holds 0.1 kWh at 6 kW, the start sits one interval before the first update and stays put. All seven fail on the old code.
**Sweep question:** where an average is energy over elapsed wall-clock time, does the elapsed time start where the first booked energy starts?
**Left open:** the EV session average (`coordinator/ev_control.py` `_update_session_tracking`) derives its duration the same way; its energy comes from the charger's meter and its duration is rounded to 0.1 min, so it shows no first-update spike, but it was not reworked here.
Refs #1155 #351.

### 157. A margin taken from what is left, re-applied on every re-plan — the headroom shrinks to nothing — GUARDED
**Symptom:** with charge pacing on, a clear day with sun until 18:15 predicted the pack full at 18:10 (#820, @ArneGollin1987, 18.10). The 10 % headroom was meant to make the pack full well before the end of sun. The owner saw why: every few seconds SEM planned again for a full battery in the last sunny hour.
**Root shape:** a safety margin expressed relative to the REMAINING quantity, inside a loop that re-solves on the remaining quantity. `paced_charge_cap_w` solved the smallest cap that lands the remaining need in the last remaining slot and opened it by 10 %. The pack then ran a little ahead, the next re-solve saw a smaller need over a shorter day and opened THAT by 10 %, so the margin shrank with the need and the finish slid back to the last slot. In the reporter's words: "10 % fast in the last hour slot of the day and not 10 % faster over the whole loading of the day." A predicted time printed at the end of its hourly slot (18:00, not 17:13) hid how close it was. Kin of class 55 (a window that moves with the reader).
**Where it lives:** `coordinator/charge_pacing.py` `paced_charge_cap_w` (**fixed**), `pacing_finish_by`, `_full_time`; `coordinator/coordinator.py` `_run_charge_pacing` passes `day_start` from `_pacing_day_start` (sunrise). The cap margin (×1.10) is kept for callers that give no sunrise.
**Closure:** the margin is also TIME, anchored to the day: `finish_by = end of sun − 10 % × (end of sun − sunrise)`. Both ends are fixed for the day, so every re-plan aims at the same time. The cap is at least the smallest one that is full by `finish_by` (same bisection, ledger cut at `finish_by`). Past `finish_by` and still short, that bisection ends at the hardware maximum: the pack is never starved. `weak_day`, the buffer floor, trust, clipping and the drain are unchanged. `full_at` is now interpolated inside the slot, and the sensor publishes `finish_by`.
**Guard:** `tests/test_820_headroom_holds_across_replans.py` — a clear October day (sun 08:00–18:15, 10 kWh to charge) replayed with a re-plan every 2 minutes through the real `today_remaining_slots`/`build_day_slots`: every paced plan carries the same `finish_by` (17:13:30) and predicts full by it; the pack is full by 17:10, not by noon. On the old code the first plan already predicts 18:00 and the pack never fills. A 30 % dimmer afternoon on a stale bright forecast still fills before sunset, at full power past `finish_by`; a forecast that cannot fill the pack caps nothing.
**Sweep question:** where a margin is applied to a quantity that a loop re-solves, is the margin anchored to something the loop does not shrink (the start of the window, the whole day, the original need)?
**Left open:** (1) the model averages each hour, so the last partial slot reads a little dimmer than the plan assumed and the predicted time can drift up to a minute past `finish_by` near the end. (2) A stale forecast that is more than about a third too high all afternoon can still leave the pack a fraction short at sunset; the headroom is one hour, not a forecast correction. (3) Evening deficit hours after `finish_by` still count in the drain, so the plan lands a little earlier than `finish_by` on such days.
Refs #820 #926 #830.

### 158. A replayed decision whose size scales with the what-if, fed inputs the live system never sees — a bigger pack buys a night charge — GUARDED
**Symptom:** a Simulation run (#1083: 339 days, own pack 15 kWh, what-if 115 kWh, recorded prices, self-consumption only) put sunny days at +21.08 — dearer with a bigger pack. One day carried most of it: 24.04.2026, actual −0.80, simulated 25.14, about 94 kWh bought. Days right after a gap were 4–5 dearer too.
**Root shape:** a replay gives a live decision inputs the live system never has, and the decision's size grows with the parameter under test. Four instances, one cause. (1) `HourlyDay.from_statistics` checked and closed a day on the meters only when no hour was missing. 24.04 had a missing hour and a counter jump at 14:00 (144.27 kWh solar, 238.51 kWh car); the hour stayed open and the model bought the 94.24 kWh between them. (2) `plan_night` asked the scheduler once with the evening's price for the whole night. A negative price there is SEM's `price_forced` override, which targets `max_target_soc` × the usable capacity — 95 % of 115 kWh — and bypasses the plan gate, so every night hour charged at positive prices. Live SEM re-evaluates every 30 minutes and charges only while the price IS negative. (3) A day read back from history has no stored forecast; the scheduler's no-forecast tier plans the whole house from the grid, even on a sunny day. (4) The deficit (`consumption − forecast`) has no pack size in it, but the target it feeds is capped by the pack: a 15 kWh pack hides an oversized deficit at `max_target_soc`, a 115 kWh pack charges all of it. And the night ran to the first solar hour, with no 07:00 ceiling. Beside these, a bigger reserve started empty after every gap: 23 kWh of reserve in a 115 kWh pack filled from the day's sun.
**Where it lives:** `analytics/simulation/hourly_day.py` `from_statistics` (**fixed**: every day is checked and closed); `analytics/simulation/battery_sim.py` `plan_night`, `negative_price_decision`, `cap_deficit`, `day_need_kwh`, `night_end`, `stretch_start_kwh`, `PeriodChain` (**fixed**).
**Closure:** the negative-price charge is asked hour by hour with that hour's price; the main plan uses `max(0, price)`. A day without a forecast plans with its own solar (perfect foresight, said in the day's notes). The deficit is cut to what the day needs: the deepest the house draws below the midnight level before the sun refills it, less what the pack holds above its reserve. The night ends at `min(sunrise, night_latest_end)`, as `time_manager` has it. A stretch starts with a bigger reserve filled, and the stored energy compares what each pack gained, so that start is neither a gain nor a loss. A gap of up to two days is bridged with the real pack's change.
**Guard:** `tests/test_1083_sim_invariants.py` — the 24.04 day rebuilt from statistics rows (missing 03:00, the jump at 14:00) buys under 10 kWh with 15 and 115 kWh (before: 85.6 and 90.9 kWh, +23.3 and +26.2). A negative 21:00 price charges nothing at positive prices; a negative 02:00 hour charges only in that hour. A day without a forecast does not grid-charge on a sunny day. The night charge does not grow from 30 to 115 kWh. Over synthetic stretches (sunny, grey, sunny then grey, negative prices, no forecast, gaps; with and without night charging) a bigger pack never makes the period dearer with the stored energy counted, and a sunny day never buys more unless a night charge does. 14 of these fail on the old code.
**Sweep question:** when a replay drives a live decision, does every input it hands over exist in the live system at that moment — and does the decision's size depend on the parameter the what-if changes?
**Left open:** (1) The deficit cap uses the day's own hours, so the replayed night plan can be a little better than live SEM's, which rests on a learned house use. (2) A day's plain difference still moves value between days: a sunny day that fills a bigger pack shows dearer and the grey days after it cheaper. The per-day "incl. what the pack gained" column and the net headline say so; the plain column stays. (3) A bridged gap follows the real pack, not what a bigger pack would have done on the missing days.
Refs #1083.

### 159. A job kept as a standing mode — once done, the next drift starts it again — GUARDED
**Symptom:** Force charge stayed on when the battery was full (#1131). The house took 1 % and SEM bought it back from the grid at once, for as long as nobody changed the mode. Force discharge did the same at the reserve: the next day's sun went into the pack and was sold down to the reserve again, though the guide said it "returns to normal use".
**Root shape:** a one-time action (charge to full, sell to the reserve) stored as a mode that stays selected. The decision only asks "is the target reached right now?", so the action stops at the target and starts again on the first step back from it. Nothing records that the job was done, so the mode never ends.
**Where it lives:** `consts/battery_modes.py` `force_charge` / `force_discharge`; `coordinator/decide_battery.py` (the manual branches); `coordinator/coordinator.py` `_run_battery_pipeline`; `select.py` `SEMPerBatterySelect`, which only changed on the user's own pick, so a mode written anywhere else was never shown (the set_option service too).
**Closure:** `decide_battery.manual_mode_done` says when the job is done: at the charge's own target (`MANUAL_CHARGE_TARGET_SOC`, 100 %) for a charge, at or under the reserve for a sale, never on a level SEM cannot read. `_finish_manual_battery_modes` then writes Auto into the store the battery's control writes, before the VPP override is laid over the user's mode and before the cycle decides. One control ends its job only when every battery it drives is done (one shared select on two batteries: b1 full must not stop b2 at 60 %), and the done state must hold `BATTERY_SOC_STEP_CONFIRM_READS` cycles in a row, so a unit's one-cycle 0 % read ends nothing. The next decision is Auto's, which stops the forced op SEM started (#1066). The select adopts its stored mode on every update, like the charger mode select (#980). Round 2 (#1164): a pack whose inverter stops the charge below 100 % (a Huawei set to 95 %) never reached the target. A charge is now also done when the pack takes no more: `charge_stall_read` asks, per battery and on its own power read, for a level at or above `MANUAL_CHARGE_STALL_SOC` (90 %, the bottom of Huawei's end-of-charge range), at most `MANUAL_CHARGE_STALL_W` in or out, SEM's forced charge landed and not stopped (`forced_ops`), and the last command SENT asking for at least one charge step (`_sem_charge_asked_w`, set by `actuate_battery` once a start went out, `last_error` clear: a failed or withheld start, a stop, a held stop after no room, observer and every other intent ask for none). The power must be a reading (`PowerReadings.battery_power_read` for one battery; with more, each unit's own `BatteryPower.power_read`, #1167): a battery wired by SOC alone reads 0.0 with nothing dark, and a state that is no number is no read (`_input_reads` now counts after the parse) (review). `charge_stall_step` keeps the window: `MANUAL_CHARGE_STALL_S` (15 min, on its own clock); a rising level, or a gap over `MANUAL_CHARGE_STALL_GAP_S` between two checks, starts it again; any cycle without such a read ends it (a dark power read, observer, a cold start). Then the same three reads end the mode. Round 3 (#1165): a sale has the same shape, an inverter that stops it at its own lower level (30 % while SEM's reserve is 20 %). `sale_stall_read` asks for the charge's window on the sale (`_sem_discharge_asked_w`, set by `actuate_battery` once a sale went out: Deye's `True`, or the intent with `last_error` clear; `forced_ops`' discharge flag), plus the home: at least `MANUAL_SALE_STALL_IMPORT_W` bought from the grid with at most `MANUAL_SALE_STALL_SUN_W` of sun, handed over by `_run_battery_pipeline` as `site` only when `house_load_is_measured`. An export limit holds back only what goes out, and a home that buys sends nothing out; a hybrid inverter full with sun has no room for the pack. So neither can end a sale. `sale_stall_step` is the same window, but a FALLING level starts it again. The sale's window is kept apart from the charge's (`_manual_sale_stalls`), so a mode change starts it at the pick.
**Guard:** `tests/test_1131_manual_mode_finishes.py` — the rule (100 %, the reserve, a held or never-read level, the standing modes never finish, the charge ends where `decide_battery` aims it and the sale where it stops selling); the write on one battery and on two (per-battery selects: only the finished one moves and the stale scalar is not touched; one shared select: only when both are done), through the real select platform, which then shows Auto; three reads in a row, so one bad read ends nothing; a cold start on one synthetic battery ends no unit; a VPP force charge never moves the select (the real override bound); the pipeline hands every battery with its own level to the check before the override and the decision. `tests/test_docs_contracts_battery.py` holds the two guide rows. `tests/test_1164_force_charge_stall.py`: the reporter's pack at 95 % and 0 W ends after 15 min plus three reads, not at 14; it stays while charging, below 90 %, with nothing or less than a step asked, a charge never landed or stopped, no adapter, in observer, on a dark power or level read; a dark read, a gap, a cold start or a slow rise start the window again; the window is time, not cycles; one shared control waits for the other pack; per-battery controls move only the stalled one, each on its own power and flag; Force discharge is not ended by an idle pack; the actuator records only a charge it sent (not a failed start, a held stop, observer or another intent); the reader says a SOC-only battery, a dark, an impossible and a non-numeric power are no reading, on the legacy and the Energy Dashboard path. Twelve mutants of the fix are killed. `tests/test_1167_own_power_read.py`: with two batteries each pack's check runs on its own power and level read, so a dark sensor on one pack stops only its own (class 3). `tests/test_1165_sale_stall.py`: the pack at 30 % and 0 W, the home buying at night, ends after 15 min plus three reads; it stays while selling, when the sun feeds the home (an export limit may hold the pack), when the home buys with sun up, with no measurement, nothing or less than a step asked, a sale never landed or stopped, no adapter, in observer, on a dark power or level read; one sunny cycle or a slow fall starts the window again; shared and per-battery controls; a cold start; a charge window is no sale window; the actuator records only a sale it sent (Deye's answer too); the pipeline hands the site only when it is a measurement. Nineteen mutants of the fix are killed.
**Sweep question:** for every mode a person picks, is it a way to run or a job to do? A job needs an end that changes the mode, not only a target the decision stops at. And can the device stop before that end on its own?
**Left open:** (1) a pack whose inverter stops charging below 100 % never reaches the target, so its Force charge never ends: **fixed** at 90 % or above (#1164). A pack set to stop lower still never ends; only its inverter's own setting could say where it stops (#1166). At 90 % or above a pack that takes nothing for another reason (grid charging off on the inverter at night, a cold pack, a write it ignored) also goes back to Auto; it was not charging. A pack whose inverter stops a sale above SEM's reserve never ended Force discharge the same way: **fixed** (#1165), when it sends nothing while the home buys with no sun. A pack that stops by day ends that evening. At night a pack that sends nothing for another reason (a write it ignored) also goes back to Auto; it was not selling. With a per-battery select, a pack whose neighbour feeds the home waits until the home buys from the grid. One dark battery power sensor stopped the check for every pack that cycle (the flag was the fleet's): **fixed**, each pack on its own power and level read (#1167, class 3). (2) Picking Force charge at 100 %, or Force discharge at the reserve, goes back to Auto within a few cycles: the job is already done. (3) The Simulation's battery mode is a what-if for every hour, so a simulated Force charge still charges all period (a choice for the simulation, not a bug). EV *Always Max* is a mode to run, as documented: a full car takes no power.
Refs #1131 #1164 #1165 #1166 #1167 #1116 #1112 #980 #1066.

### 160. A register one command writes, written back by only some of the commands after it — GUARDED
**Symptom:** SEM capped a pack's discharge at 0 W (the cheap-hour hold, the EV clamp at night). A sale that came next (Force discharge, a planned sale) sent only the sale power, and the 0 W stayed. On a brand where that limit also caps a forced discharge, the sale sent nothing (#1175, found while fixing #1165).
**Root shape:** each command writes the registers it needs and leaves the others as they are. A register one command set for its own purpose is then in force under the next command too, unless that command writes it again. #523 found this shape once, the other way round: the sale power stayed under every other mode, and each mode now writes it to 0 (`_zero_setpoint`). The discharge limit had no such rule: only NORMAL wrote it back.
**Where it lives:** `coordinator/battery_adapters/base.py` `command_force_discharge` (generic and GoodWe use it) (**fixed**); `huawei.py` `command_force_discharge`, service and number paths (**fixed**, as the cycle's only command: the LUNA2000 takes one write per cycle, so the sale goes out on the next cycle); `generic.py` `command_off` for a pack with a strategy select, which set the pack idle and left SEM's limit (**fixed**); `deye.py` writes no discharge limit, so it has none to leave (assessed). A forced charge is not held back by a discharge limit, and the NORMAL or limit command after it writes the limit again (assessed).
**Closure:** `BatteryControlAdapter._hand_back_own_limit` puts the pack's max back when the last limit SEM wrote (`last_discharge_limit_w`, `_own_limit_held`) is below it. Every sale calls it before the sale power. A limit SEM did not write (−1) is left as it is (#936). The write skips the same-value check (`force=True` on `async_write_power_setpoint[_verbose]` and each `_apply_discharge_limit`): right after SEM's own 0 W write the entity can still show the old max until the integration reads it again, and the skip would have recorded a hand-back that never happened (review). A failed write leaves the record low, so the next sale cycle asks again. On Huawei a try spends one cycle, and the next cycle sends the sale whether the write landed or not, so a register that refuses it never holds the sale back. One entity named for both the limit and the sale power is the sale's own register: no hand-back there. When the write lands and the last command was the limit, the last command is cleared: left as LIMIT_DISCHARGE at the max, it read as a limit in force, and a hold that came back the next cycle waited out the 6-cycle lowering dwell (second review).
**Guard:** `tests/test_1175_sale_lifts_own_limit.py` — after a 0 W hold, the sale writes the max once and then the sale power, on generic, a pack with a strategy select and GoodWe; Huawei sends only the limit on the first cycle and only the sale on the next, on both paths; a failed write still lets the sale out (Huawei, both paths: try, sale, try, then quiet) and keeps the limit as the last command; a hold after a hand-back with no sale goes back that cycle; the write goes out while the entity still reads the max; the #915 read-back judges it; one entity for both is left; a user's own limit is not touched; Off on a pack with a strategy select gives the limit back; the actuator's hold then sale; observer writes nothing; Deye writes no limit. Every concrete adapter class must be listed with its test, and a class that overrides the sale and writes a limit must call the hand-back (AST check). Six mutants of the fix are killed.
**Sweep question:** for each register a command writes, which commands after it need the old value gone — and do they write it?
**Left open:** (1) two batteries on one limit entity: a sibling's NORMAL, and now its sale, writes the max over a battery's own hold, and the held battery never writes again (#1178, from before this fix): **fixed**, class 161. (2) The export cut (#955/#1090) also holds back a sale, but only at a low feed-in price, where selling is what the cut is there to stop (a choice, not a bug). (3) Off on a pack with a strategy select tries the hand-back once, like the base Off, because Off sends nothing after its first cycle. If that write fails, the limit stays while the pack sits idle in Off; the next mode or an unload writes it again (assessed, not a bug).
**Round 2 (#1180) — a value no command after it writes back:** a grid charge on GoodWe or the generic switch setup wrote SEM's target (60 %) into `battery_target_soc_entity`, and the stop only turned the switch or mode back. That number is often the pack's own upper limit (`soc_upper_limit`, `battery_max_charge_soc`), so the pack stopped at 60 % on every sunny day after. Here no later command writes it at all, and its right value is not a fixed max but whatever the user had. **Closure:** `coordinator/battery_adapters/charge_target.py` `ChargeTargetHold`, charge pacing's rules (#949): the value is saved before SEM's first write and persisted (`sem.charge_target.{entry_id}`, adopted by the next lifetime, removed with the entry); the stop turns the switch or mode back, then writes it back (`blocking`, bounded). A number that cannot be read is never written, and neither is one whose record cannot be read or saved. Every value SEM wrote is kept until a read shows the put-back landed, so a read of any of them is SEM's echo, never the user's (class 95: a target that rose 60 → 70, two packs asking two values, an inverter that rounds to its step). Until then it is pending: checked on each cycle with no forced charge (`actuate_battery` → `settle`, after the command, never in observer mode) and sent again at most 3 times, 5 min apart (class 108); a value that is neither SEM's nor the saved one is the user's and ends it. A start that failed after the target went out gives it back 5 min later. ONE hold per entry, keyed by the number: there is no per-battery target list, so packs behind one inverter share it. The self-heal rebuild now gets the same runtime context. **Guard:** `tests/test_1180_charge_target_put_back.py` — 60 then 100 on both adapters, switch first; a restart mid-charge and the boot stop; the record written before the number; the vacuity twins (no record, one hold per pack: 60 stays); unreadable, damaged or unsaved records write nothing; the echo cases above; a dropped, raising or unreadable put-back; a failed start, also beside a NORMAL pack; observer writes nothing; an AST check that every battery adapter is built from `_battery_adapter_context`. **Siblings (assessed):** Huawei's `forcible_charge_soc` carries its target in the call, no standing register; Deye restores its program values from its own snapshot (#709); pacing (#949) and the export cut (#955) already put their value back; the discharge limit goes back to the max by design (#936); GoodWe's work mode goes back to a fixed mode, but its forced charge cannot be set up today (class 116). **Left open:** Off, a disable or removal, and a restart with night charging then turned off never send the stop on GoodWe or the generic switch, so the switch stays on and the target is not put back (#1181): **fixed**, class 4 round 2. A limit the user changes during a charge is written over each cycle and the old value goes back (a choice: during the charge the number is SEM's).
Refs #1175 #1165 #1178 #523 #936 #879 #1180 #1181.

### 161. One register, two writers — each keeps its own record of what the register holds — GUARDED
**Symptom:** two batteries share one discharge limit entity (one register for the whole inverter). Battery A held 0 W, because it may not feed the car. Battery B was NORMAL in the same cycle and wrote the max into the same entity. A's own record still said 0 W, so A never wrote again: the pack fed the car, and the discharge limit sensor showed 0 W (#1178, found while fixing #1175). The #915 read-back then judged A's 0 W against B's max: a "not kept" strike on a working entity.
**Root shape:** a same-value skip keyed on what THIS writer last sent, on a register another writer also sends to. Each writer's record is true for its own writes and false for the register. With two wishes and no rule for which one the register holds, the last writer wins each cycle, and the skip makes the loser stop trying. #691 already counted such batteries as one consumer of the house budget; the commands were still sent per battery.
**Where it lives:** `coordinator/coordinator.py` `_run_battery_pipeline` (**fixed**: every battery decides, then `battery_shared_limit.actuate_batteries` sends the commands); `battery_adapters/generic.py`, `goodwe.py`, `huawei.py` `_apply_discharge_limit`, the only writers of the limit entity (**fixed**: each asks `_limit_not_mine()` first); `actuate_battery.active_discharge_limit`, the sensor (**fixed** by the shared record); `_warn_battery_entity_collision`, which called a shared limit a fight (**fixed**: the limit is left out; the sale power and the strategy select still warn); `huawei.py` stops (**fixed**: `_issue_stop` and the forced charge stop set `_sent_stop`). `restore_discharge_limit_on_startup` already wrote each entity once, and the #1180 charge target already has one hold per entity (assessed).
**Closure:** one writer per entity per cycle (`battery_shared_limit`): a sale wins (its hand-back lifts the limit, #1175; a sale beats the car limit by choice, #533), then the lowest LIMIT_DISCHARGE (a battery that may not feed the car is kept from it), then NORMAL or the sale's stop (the max), then Off's one hand-back. Ties go to fleet order. Each battery counts by what its command will really write (`wish_of`): a forced charge and its stop write no limit, an Off that has already spoken writes nothing, and a flip the actuator holds on a blind cycle counts as the command still in force (`actuate_battery.held_on_blind_cycle`, #818). A sale that did not go out this cycle (`_sale_sent`, reset each cycle: `last_intent` outlives a sale that stopped; no sale entity, withdrawn after refusals, a strategy select that has not switched; #840, #978) gives the limit to the next battery in line, which sends the write it held back (`_limit_withheld`). The others still send their own commands; only their limit write is held back (`_limit_writer`, set only while the cycle's commands run; the unload hand-back clears it too). They go first and the writer last, and on a cycle where another battery on the entity sent a stop (`_sent_stop`, Huawei, only when a stop really went out) the writer writes nothing: that inverter takes no write right after a stop. A hold whose write was held back, with another value in the entity, is no limit in force (`_drop_unsent_hold`), so it lands without the lowering dwell once it can. After the cycle each takes the writer's record (`follow_writer`), so the same-value skip, the sale's hand-back, the sensor and the actuator's dwell read the entity. With no limit of SEM's in force (the writer sold or wrote the max) a recorded LIMIT_DISCHARGE is cleared, so the hold after a sale lands at once (the #1175 review rule). A write still waiting for its #915 verdict goes to the writer when it holds the same value, else it is dropped; a #1138 extra send owed goes to a writer that holds. Observer sends nothing and shares nothing. Each battery's diagnostics row says `limit_written_by`.
**Guard:** `tests/test_1178_one_limit_one_writer.py` — through the real pipeline and real adapters: a hold beside NORMAL stays in either fleet order (one write, sensor 0 W, no false strike); the lowest limit wins and the next lands at once; a sale lifts it once and the hold comes back on the next cycle; Off beside a hold hands nothing back, and two Offs hand the max back; a forced charge beside a hold; a sale that cannot go out (no entity, withdrawn, a select that never switches), or stops going out after it sold, leaves the hold; a blind cycle moves nothing; two Huawei packs on one inverter never get a limit write in the cycle of a stop, and a hold from before the sale lands once it is quiet, with no dwell; a charge stop that sends nothing leaves no quiet cycle; a missed hold is sent again by the next writer; own entities each write their own (the twin); observer writes nothing; the mark is gone after the cycle, after a command that raises, and for an unload during a cycle; a write the next writer replaced is not judged, and one the next writer still holds is judged by it. The rule alone. AST checks: every adapter method that writes `_discharge_control_entity` asks `_limit_not_mine` (with a twin that bites), and `_run_battery_pipeline` sends every command through `actuate_batteries`. 23 mutants of the fix are killed.
**Sweep question:** when two units write one register, whose value should it hold — and does every writer's "already sent" skip read the register's record, or only its own?
**Left open:** the sale power setpoint (`battery_force_discharge_control_entity`) has the same shape: on one shared setpoint a sibling's NORMAL zeroes a sale on the first cycle, and the seller's own record then skips every later write (#1182): **fixed**, round 2 below. A shared strategy select is two Sessys set up wrong: each has its own, and SEM warns.
**Round 2 (#1182) — the sale power entity:** battery A sold 3000 W, battery B was NORMAL and wrote 0 W into the same entity (every mode zeroes it, #523). A's record still said 3000 W, so A never wrote again: A showed a sale while the entity read 0 W. **Where it lives:** `base._write_force_discharge`, the only writer of the entity (**fixed**: it asks `_setpoint_writer` first and holds the write back); `battery_shared_limit.actuate_batteries` (**fixed**: one writer per entity per cycle); Huawei's number stop `_issue_stop` (**fixed**: a held-back zero is no stop, so no quiet cycle, unless it goes out later); `_warn_battery_entity_collision` (**fixed**: a shared sale entity is no longer a fight). Huawei with a device id and Deye never write the number (`sale_setpoint_entity()` is empty), so they are not grouped. **Closure:** a sale wins, then a charge on a bidirectional setpoint, then every other command (all write 0 W); among those a battery ending a sale of its own goes first, so its stop goes out with its own command and the shared limit's writer gets its quiet cycle; other ties go to fleet order. A writer that did not leave its value in the entity (`_setpoint_spoke`: nothing written, #757, #978, #818, or a refused write, #840) gives it to the next battery that held a write back, until one lands; the same-value skip then reads the entity's record from before the commands (`sp_before`), because a stop can record 0 W without a write. After the cycle each takes the writer's record; diagnostics say `sale_power_written_by`. The sale split is class 6 (below). **Guard:** `tests/test_1182_one_sale_power_one_writer.py` — through the real pipeline and adapters: a sale beside NORMAL stays in either fleet order with one write; it ends with one 0 W; a stop beside a seller leaves the sale; two sellers write once; a refused writer, two refused in a row, a stop with nothing to stop and a sale waiting for its select all let the next write out; a sale beats a setpoint charge; Huawei on a number: a sibling's stop and its retries leave the sale, the battery ending its sale writes the stop with no limit write next to it, a stop sent late is still a stop; own entities each write their own; observer writes nothing; the mark is gone after the cycle, after a raise and for an unload; the rule alone; an AST check that only `_write_force_discharge` writes the entity (with a twin that bites). 16 mutants of the fix are killed. **Left open:** two Huawei packs on one huawei_solar device: one pack's stop ends the device sale and the other's record skips every later sale call (#1275). A refused Huawei number stop is recorded as 0 W, so its retries are skipped, one battery too (#1276, class 4 shape). A seller whose write fails once lets the sibling's 0 W stop a running sale for that cycle (a choice: when in doubt, do not sell). With a withdrawn battery that is not first in line, its own probe never runs, so it stays withdrawn until a restart, as its Repair says.
Refs #1178 #1182 #1175 #691 #533 #915 #1138 #936 #1275 #1276.

### 162. A unit count taken from one of the two lists that hold the units — GUARDED
**Symptom:** a home whose batteries use HA's "Two sensors" option (one charge and one discharge power sensor, no combined one) got no `sensor.sem_battery_b<N>_*` and no per-battery Mode select or reserve. One shared select drove both batteries, so Force charge on one waited for the other (#1171, found while fixing #1167). A home with one combined and one two-sensor battery was hit the same way.
**Root shape:** a battery is a combined sensor (`battery_power_list`) or a two-sensor pair (`battery_power_pairs`, #551/#553). The reader counted both and published `b1`, `b2` for every kind, but the sensor platform and the control discovery each counted `len(battery_power_list)`. Each site restated the count (class 46) from the list it knew, and the two-sensor kind came later. Nothing failed: one shared control is the right answer for a one-battery home, so the wrong count looked like that home.
**Where it lives:** `sensor.py` per-battery sensors (**fixed**); `coordinator/battery_controls.py::discover_battery_control_slugs`, which select.py, number.py and `_per_battery_config` all follow (**fixed**); `config_flow.py` `_battery_label_source` (the per-battery limit page named a two-sensor battery by SEM's own sensor, **fixed**) and the setup summary (counted and listed combined sensors only, **fixed**); `coordinator.py::_configured_entity_ids` (a pair's two sensors were not "in use", so the Config card could propose them, **fixed**); `diagnostics.py` per-source lists (pairs not dumped, **fixed**); the reader's own counts and SOC average (correct, now read the same list); the ED read log (**fixed**). Kept on the combined list on purpose: sign detection, its #647 audit and the sign payload, because a pair's sign is declared by the user and never checked.
**Closure:** one list, `ha_energy_reader.battery_units(ed)`: one entity per battery in slug order, combined sensors first, then each pair by its charge sensor (the reader's own order and name). Every battery count and slug list reads it. The update itself moves such a home from one shared select to one per battery, and empty slots run Auto at the default reserve: a shared Off (SEM hands off) would have become Auto, and a list left from an older layout would drive again (#531, review). So `battery_controls.adopt_shared_battery_settings` runs once, right after the capture and before the first refresh: when the registry still holds the shared select and no per-battery one, the shared mode and reserve are copied into every slot, and a WARNING says the shared select is gone (automations that set it need the new ones). A home that grows to two batteries gets the same handover. The handover made a cold start more costly (second review): a start that misses the Energy Dashboard sweeps the per-battery sensors, the registry fallback read only those sensors, so a second such start fell back to the shared select and the next normal start wrote the shared mode over every battery's own. The fallback now counts this entry's per-battery Mode selects too, and knows a sensor by its unique id (a renamed one counts).
**Guard:** `tests/test_1171_two_sensor_battery_controls.py` — the list from HA's real prefs layout (two pairs; a pair listed before a combined sensor, so the order is checked); the reader publishes exactly those batteries with those names; SEM's real setup on a real registry builds four sensors, a Mode select and a reserve per battery and no shared select, each power sensor shows its battery's own net, and Force charge on b2 drives b2 only; the twin: one two-sensor battery keeps the one shared select; with the old shared select in the registry (Off, 50 %, a leftover Force discharge list) each battery starts on Off at 50 %, once, and a home without it is left alone; unset shared values stay unset and only the two slot lists are written; the fallback finds this entry's selects (not another entry's) and a renamed sensor; an AST check puts the handover between the capture and the first refresh. An AST check lists every function that reads `battery_power_list` with why the combined list alone is right there; a new reader fails until declared, and a twin shows the two #1171 counts would fail it. The setup tests fail on the old code.
**Sweep question:** where one kind of unit lives in two lists, does every count and every slug list ask both?
**Left open:** the per-battery sign check matched a combined battery to energy counters by list position, but the counter lists follow the Energy Dashboard order and hold the two-sensor batteries too, so a mixed home could check one battery against another's counters (#1193, **fixed**: class 167). A combined sensor the user marked "Inverted" in HA is read as it is once a home has two batteries (#1194, **fixed** the other way round: that read was right, the one-battery flip was wrong). Both are class 1. The slots were kept by position, and the reader numbers combined sensors first, so a battery added later could move another battery's saved entities onto it (#1195, **fixed**: class 166). The AST check works per function, so a new count inside a declared function is not caught. A home growing from two per-battery controls to three gets no handover; a slot left from an older, longer list no longer drives the new third battery (class 166). The removed shared select is told by a log line, not a Repair (a choice).
Refs #1171 #1167 #553 #551 #1071 #1089 #531 #1193 #1194 #1195.

### 163. A rule the fleet total keeps, missing on each unit's own entity — a dark unit shows the reader's 0 W — GUARDED
**Symptom:** with two batteries, `sensor.sem_battery_b2_power` showed 0 W while battery 2's own power sensor was unavailable, and `sensor.sem_battery_b2_status` said Idle (#1170, found while fixing #1167). An idle pack reads 0 W too, so the two looked the same. The SOC entity beside it already said unknown (#694).
**Root shape:** the reader's fallback for a dark read is 0.0, and only the FLEET total was taught to say so: `battery_power_all_unavailable` (every read dark) makes `to_dict` publish None, and the entity holds its last value for `SENSOR_DARK_READ_GRACE_S` before it shows unavailable (#818/#875, 03.09). Each unit's key was published from the same 0.0 with no flag asked. #1167 gave each unit its own `BatteryPower.power_read`; nothing published by it. The fleet's flag cannot stand in: while one unit still answers, the total is published, and the dark unit's own number is still the fallback.
**Where it lives:** `coordinator/types.py` `SEMData.to_dict`, per-battery block — power and status (**fixed**: None when `power_read` is not True, which also covers one dark side of a two-sensor pair); `sensor.py` `SEMSolarSensor`, whose grace held numbers only (**fixed**: a unit's status, `_HELD_TEXT_KEY`, is held on the same clock as its power, so a blink does not flip it to unavailable and the #1084 decision attributes stay); the battery card's per-battery row and fleet power cell, which read an unavailable power as 0 and an empty status as idle (**fixed**: "— W", and the dash as status when neither is known). Per-battery SOC already had its rule (#694); capacity is a size, not a reading. Per-PV-string power (#1196, **fixed**: `_read_pv_strings` sets `solar_power_per_string_read` per string, a V+I pair needs both halves; `to_dict` publishes None while it is not set; `semDiscoverPVStrings` keeps a dark string with no watts, skips a registry-only `restored` entity, and the solar, flow and diagram cards print "— kW" through `semPVStringKW`). **Open:** the fleet `battery_status` said Idle while every battery sensor was dark (#1197, **fixed**: the status and `grid_status` are None while their fleet power is dark, held on its clock, then unknown; the card that stopped drawing on it is class 165); the tab header printed 0 for every unavailable figure (#1198, fixed: class 164). The fleet total and home counted the dark unit as 0 W (class 5, W6), so for the grace the held unit row and the total did not add up; a dark string's daily energy booked 0 W too (#1203), as a dark inverter of two did (#1186) — both **fixed** (class 58 round 3). Per-charger power has no fleet rule to copy (its #910 hold, class 5).
**Closure:** a unit's key is a reading only when the unit's own flag says it was read; the entity layer, not `to_dict`, owns the hold, so a unit's power and status hold and blank on the fleet's clock.
**Guard:** `tests/test_1170_dark_battery_unit_power.py` — through the real reader: a dark, unknown, not-a-number and impossible (#902) unit and a half-dark two-sensor pair publish None for power and status while the live unit and the fleet total stay numbers; a real 0 W still reads 0 W and idle (the twin); the user sign flip leaves the dark unit None; a unit never marked read publishes none. Through the real `SEMSolarSensor`: the dark unit's power and status hold their last value with `stale_s`, blank together after the grace, and never show 0 W or idle; never-read is unavailable; another text sensor is not held (the twin). A declared list of every per-battery and per-PV-string key `to_dict` publishes, each with its dark rule or its filed issue: a new key of these units fails until declared, and the fixture must publish every declared key. `dashboard/card/test/battery-dark-power.test.js` — the real card: "— W" and a dash status cell for the dark row, the live row unchanged, a real 0 W idle pack, a power with no status, the fleet cell. 14 of the 18 Python tests and 2 of the 5 card tests fail on the old code. `tests/test_1196_dark_pv_string_power.py` — the same for a string through the real reader on both paths (dark, unknown, not a number, missing, half a V+I pair; a live 0 W and a string asleep at night still 0 W) and the real `SEMSolarSensor`; the declared list now names the string rule. `dashboard/card/test/pv-string-dark.test.js` — discovery keeps the dark string, the three cards print "— kW" and a real 0 W as before, a source scan that every `.watts` read goes through a formatter that knows null, and the config card counts strings by the same rule. 13 of its 18 Python and 12 of 18 card tests fail on the old code.
**Sweep question:** for every per-unit entity beside a fleet total, does the unit keep the rule the total keeps when its own source is dark — or does it publish the reader's fallback?
Refs #1170 #1167 #818 #875 #694 #902 #1084 #1196 #1197 #1198 #1186 #1203.

### 164. A card prints its reader's fallback for a sensor that is out — 0 W looks like a reading — GUARDED
**Symptom:** the figures at the top of each dashboard tab printed 0 when their sensor was unavailable (#1198, found while fixing #1170). On the Battery tab a power sensor that was out read "0 W" and the SOC "0%", the same as an idle, empty pack; battery health read "100%". A state that was not a number printed "NaN".
**Root shape:** each card has its own small reader, `_val(suffix, fallback = 0)` or `_getState(...)`, that returns the fallback for an unavailable, unknown or missing state. The fallback is there for sums, and the card prints the same value. `parseFloat(x) ?? fallback` lets NaN through, because `??` only catches null and undefined. The same shape was fixed one card at a time: the System tab (PROD 30.08), the SOC on three cards (#903), the Home chips (#925), the battery card's power (#1170).
**Where it lives:** `sem-tab-header.js` (**fixed**: `_getState` takes no fallback and returns null; each figure prints through `fig`, so null is the dash; the SOC goes through `socDisplay`; the Home hero shows the dash; the Home tab's four unused figures are gone; the Config tab's heat pump was read as `sensor.sem_heat_pump_registered`, which does not exist, so it always said Off — it now reads the binary sensor, and the dash when that is out). Round 2 (#1200, **fixed**): about 15 cards kept a `_val(suffix, fallback = 0)` reader, and the base `_state` had the same default. Every card's reader (`_val`, `_state`, `_valNum`, `_numVal`, `_entityVal`, the flow card's `_getState`) now goes through `readNumber` and defaults to null: the EV, charger, battery, zones, Home, solar, solar summary, solar KPI, grid, costs, costs detail, control, system, gauge, load list, EV progress, flow and diagram cards. A total made of two sensors (grid net, allocated surplus, avoided cost, the diagram's and flow card's Home) is "—" when a part is out; a part SEM never makes on this home (battery savings with no battery) is 0. A load's own power entity that is out reads "— W" in the load list, the flow card and the diagram. Left as they were: a setting shown with the card's own default when its number entity is not there (the EV card's 40 kWh, 6 A); the Solar card's vs-forecast, degradation and specific yield print "—" for a real 0 (0 % of forecast is no sun yet, a choice).
**Closure:** a figure is a number only when its sensor gave one. The display reader returns null, and one formatter turns null into "—" (`util/missing-value.js`: `isMissing`, `MISSING`, `readNumber`, `fmtValue`, `fmtNum`, `socDisplay`). A sum or a check that wants 0 says so (`?? 0`, or an explicit 0 fallback).
**Guard:** `dashboard/card/test/tab-header-missing.test.js` — the real header card on every tab: an unavailable, unknown, not-a-number and missing sensor prints "—" for each figure; the Battery tab's "0 W", "0%" and "100%"; a real 0 still prints 0; real readings print as before; every `_getState` figure draws the card again when it changes or goes out, and so do the heat pump, the "no grid limit" flag and the currency (class 127); the heat pump is On, Off, Off with no entity, and the dash when out; a source check that `_getState` takes no fallback and that every sensor it reads through `_getState` is tested (a read past `_getState` is not seen). 32 of its 35 tests fail on the old code. `dashboard/card/test/sensor-out-figures.test.js` (#1200) — every card in `src/cards` is drawn with every SEM sensor "unavailable", "unknown", "n/a", "nan", empty and missing, and may print only the numbers listed for it (settings, counts, labels), never NaN, null or undefined; with every sensor reading, it may print no extra dash; a new card fails until it is listed. A source scan fails on a reader whose default is a number, or on `parseFloat(x) ??`. Sums: the EV header with one charger out, a battery session, a load's power, grid net and allocated, the avoided total with and without a battery, the diagram's Home, the flow card after a real 0 goes out. 38 of its 84 tests fail on the old cards.
**Sweep question:** for every number a card prints, what does it print when the sensor is out — the dash, or the fallback the card keeps for its sums?
Refs #1198 #1170 #903 #925 #1200.

### 165. A card asks one entity whether SEM is out — that entity is out on its own, and the card stops drawing — GUARDED
**Symptom:** `sensor.sem_battery_status` said Idle while every battery power sensor was dark (#1197, found while fixing #1170). Publishing no status there was not enough: the battery card skipped every redraw while that one entity was unavailable, so it kept the last figures and they looked live. The Home card and the system diagram did the same on `solar_power`, so they stopped drawing while the inverter was dark.
**Root shape:** a card skips a redraw while SEM is out (a reload or a failed cycle makes every SEM entity unavailable), so it does not flash zeros. To ask "is SEM out?" it read ONE entity, picked because it was always published. A later fix taught that entity to go out on its own when its source is dark (the dark-read rule, #818, class 163), and the card took "this sensor is out" for "SEM is out". The status beside it was built from a power that reads 0.0 when dark, so with the skip removed it said Idle.
**Where it lives:** `coordinator.py` `_build_system_status` (**fixed**: `battery_status` None while `battery_power_all_unavailable`, `grid_status` None while `grid_power_unavailable`); `sensor.py` `_HELD_TEXT_KEY` (**fixed**: both held on their power's clock, then unknown, not unavailable, so the #1084 decision attributes the Why card reads stay; the per-battery status too); the cards' skip — `sem-lit-base.js` (`watchedEntities[0]`: the Home card's solar power), `sem-battery-card.js` (the status), `sem-system-diagram-card.js` (solar power; entities mode reads the user's own entities and now never skips), `sem-charger-status-card.js` (the first charger) (**fixed**: `allOut`); the battery card hero and the grid card worked the status out from 0-by-fallback powers (**fixed**: the dash when neither status nor power is known); the Control and Configuration subtitles printed "SOC 0%" beside it (**fixed**, class 164). The `battery_charging`, `battery_discharging`, `grid_export_active`, `solar_active` binary sensors read Off while their power was dark, and binary sensors had no grace hold (#1201, **fixed**: round 2 below). With one unit of two dark (#1186), the shown power keeps that unit's last read for the grace (`shown_w`), but the status and the flags read the reader's 0 W, so "Idle" stood beside 900 W (**fixed**, found in #1201). A state that is no number ("none") was neither dark nor read, so the fleet power read 0 W and the status Idle (#1202, **fixed**: class 176).
**Closure:** "SEM is out" is every entity the card reads being out (`util/missing-value.js` `allOut`), never one of them. A status is None while the power it is built from is dark, and holds on that power's clock. Round 2 (#1201): the four on/off flags take the same rule; `binary_sensor.py` `HELD_FLAG_KEYS` holds them through `SENSOR_DARK_READ_GRACE_S` with `stale_s`, then unknown, as `SEMSolarSensor` does; every status word and flag is built from the power SEM shows (`shown_w`), not the reader's 0 W.
**Guard:** `tests/test_1201_dark_flags.py` — through the real reader and `_build_system_status`: each dark shape ("unavailable", "unknown", "none", "nan") of the battery, meter and inverter gives no flag; a real 0 W is Off; a meter-only home is Off. Every #1186 shape with one dark unit keeps the words it had while live (five shapes tell old from new). The real `SEMSolarBinarySensor`: held with `stale_s` on the power entity's clock, then unknown; a blink never flips it; never read is unknown; the first write after setup shows the first cycle; HA's update path holds before the write; `ev_connected` is not held (the twin). A guard: with every power dark, every `SystemStatus` field is None unless declared not built from a power, and every such binary sensor is in `HELD_FLAG_KEYS`. The cycle trace says what a held unit adds (`held_w`), as its word now reads it. 34 of 54 tests fail on the old status builder, and the 7 hold tests on the old binary sensor. `tests/test_1197_dark_status.py` — through the real reader and `_build_system_status`: a dark or unknown battery power and a dark meter give no status; a real 0 W is idle; selling, charging, discharging, import and export still show; one battery of two dark keeps the fleet status; a battery-less home is idle. Through the real `SEMSolarSensor`: held with `stale_s`, then unknown with the power unavailable; never read is unknown; the battery decisions stay after an hour dark; the real trace reads no word. `dashboard/card/test/status-dark.test.js` — `allOut`; the battery, Home, diagram and charger cards draw again when one entity is out and still skip when every one is; the battery and grid cards print the dash, a real idle still says Idle; entities mode never skips; a source scan of every `set hass` (25 found) fails on an `'unavailable'`, `'unknown'` or `isMissing(` check. 11 of 18 Python and 11 of 16 card tests fail on the old code.
**Sweep question:** when a card asks "is SEM out?", could the entity it asks be out while SEM is fine?
Refs #1197 #1170 #818 #1084 #1200 #1201 #1202 #1186.

### 166. A unit's saved settings kept by its place in a list the user can change — GUARDED
**Symptom:** a combined battery added to a home of two two-sensor batteries became b1 and took the first pair's saved discharge entity, mode and reserve. SEM wrote that pair's entity when it decided for the new battery (#1195, found while fixing #1171). A battery removed from the Energy Dashboard moved every battery after it the same way, and a list left from an older home of three batteries gave its third slot to the next third battery.
**Root shape:** the per-battery settings are lists, and slot N is battery bN's. bN is a place in `battery_units` (combined sensors first, then pairs, each in Energy Dashboard order), not a battery. Nothing recorded which battery a slot was saved for, so when the list of batteries changed, every slot stayed where it was and the batteries moved under it. Each battery's adapter was also built once with its slot's entities, so a change while SEM ran kept the old ones until a restart.
**Where it lives:** the six lists in `battery_controls.PER_BATTERY_LIST_KEYS` (**fixed**), read by `_per_battery_config`, the Mode selects, the reserve numbers, the Configure dialog's limit pages and the Config card rows; the adapters cached per bid (**fixed**: a loaded entry whose battery list changed reloads once). The Config card and an open Configure dialog saved a whole list from the copy they read, so a change while they were open put the old order back (#1204, **fixed**: round 3 below). The sign lock SEM saves for each battery was kept by bid too, so a battery removed in front of another handed its lock to it (#1205, **fixed**: round 2 below). The per-battery entity ids (`sensor.sem_battery_b1_power`, `select.sem_battery_b1_mode`) are places on purpose: they show whichever battery is at that place (a choice). A battery whose Energy Dashboard sensor changes is a new battery here and starts on its defaults (a choice: the sensor is the only name the dashboard gives it).
**Closure:** `battery_slot_units` records which battery each slot is for (its `battery_units` entry). Every Energy Dashboard read (`async_initialize_energy_dashboard`: setup, the #923 edit listener, the #274 retry) calls `align_battery_slots`: each battery takes its own slot back at its new place, a new battery starts unset, a removed battery's slots go (as a removed charger's card does). A new battery's slots are unset, so it uses the shared entities as any unset slot does (#1089; the shared entity is the one inverter's, class 147). With no record yet the slots are taken as they stand and a slot past the last battery is dropped. At setup this runs before the controls are captured and before the first command; a removed battery's discharge limit is handed to the start-up restore, so SEM's last cap on it is lifted. A loaded entry reloads once when the list of batteries changed, so adapters, selects and numbers are built for the new places, and until then the battery pipeline sends nothing and ends no manual mode (`_battery_reload_pending`; the cycle's readings may still be in the old order). A first record alone is written with the no-reload snapshot. `_per_battery_config` reads its lists from the same constant. A read with a gap (an empty name) is no answer.
**Guard:** `tests/test_1195_battery_slots_follow_their_battery.py` — the rule on its own (a combined battery added before two pairs, a removed battery, the first record and the old third slot, no change, an empty read, damaged values, one sensor named twice); SEM's real setup after the dashboard grew: b1 has none of the pairs' entities, b2 and b3 keep theirs in the config SEM decides from, in what each adapter is built from and on the Mode select; the same edit while SEM runs moves the settings and reloads once, and the next read writes nothing; the no-reload snapshot for a record alone; a cycle with the reload due sends no command and ends no manual mode (the twin: both run without it); the start-up restore gets a removed battery's limit (not a kept or shared one). A source scan finds every per-battery list key in the package and the Config card and fails on one the alignment does not move; an AST check that `_per_battery_config` names no list of its own and that the alignment follows the reader's new config. Both real-setup tests fail with the alignment off (b1 took `number.verto1_sell`).
**Sweep question:** when a unit's saved settings are found by its place in a list, what moves them when the list changes?
**Round 2 (#1205):** the battery sign locks were saved by bid (`sign_state` `battery_detected` / `battery_inverted`), so the batteries after a removed one took its sign. A battery whose sensor reads + while discharging saves "negate", and the next battery then read discharge as charge. The one-battery lock (`__fleet__`) had the same shape: it was kept when the one battery is read from another sensor (a battery replaced, or the second of two left), as the grid's was before #1103. **Closure:** `sign_state` saves `battery_learned_on`, the sensor each saved lock was learned on. `SensorReader._signs_follow_their_battery` runs on every Energy Dashboard read, before the #1194 move and the #1193 check. Every per-battery record (`_BID_STATE`: sign, evidence, baselines, brand seed, the #647 audit, the #1193 marks) moves to its sensor's new place; a sensor that is gone drops them. A store with no record (an older build, or a round trip through one) is taken where it stands, as before. A read with no combined battery, or with a gap, moves nothing. The one-battery lock is about the sensor read alone (SEM's pick, else the dashboard's): another sensor drops it and re-arms the brand seed, as the grid does; while no sensor is read alone it waits. A review found three more: (1) "Fix battery sign" is not bound to a sensor and was set against what the saved lock read, so a lock learned again under it was turned over; the one-battery lock now waits while the flip is on, as the #1193 check does. (2) The #647 prune in `set_energy_dashboard_config` ran before the move and dropped audits by count; it now drops only an audit whose recorded sensor is gone. (3) A two-sensor battery's id is a place too, so another pair at the same id took the last pair's #661 votes; an exclusivity audit now starts again when its two sensors change. Ids are read strictly (`_bid_place`): a damaged `b²` or `b01` in the store is left alone, also in the sign payload. A second review found the flip case per battery too: a sign whose sensor SEM no longer finds (renamed, or the battery replaced) was learned again under the flip. While the flip is on, such a sign now stays at its own place if no saved battery claims it, and keeps its old sensor in the record, so it is learned again once the flip is off. Only a lock or a kept sign waits; with none, the record follows the sensor read. **Guard:** `tests/test_1205_sign_follows_its_battery.py` — through `read_power` and the store: a battery removed, added in front, two swapped, no change, a change while SEM runs, an older store, no answer, a gap, a damaged record, reset; the one-battery lock on another sensor, the same one, through a two-battery home, through the pick, from an older store, beside a pair. A source scan finds every `self._battery_*` record read or written by battery id in `SensorReader` and fails on one the move does not carry. The real integration starts from a store saved before a battery was removed. 14 of its first 25 tests fail with the move off; the review's tests fail on the first cut. **Left open (round 2):** the Deye snapshot store is keyed by bid too, so a moved Deye battery does not find its own saved settings (#1257; another battery's are refused by the entity check). A read without a dashboard applies a saved one-battery lock without checking its sensor, as the grid's does (a choice, #1192). A store from a build since #1195 has no record; `battery_slot_units` holds the list it was saved by, but the alignment rewrites it before the restore, so a battery removed during that one upgrade restart moves signs as before (a choice: once, at the upgrade). Checked and right: the battery cost pools (`battery_provenance`) are keyed by bid but read only as a fleet total; the per-battery entity ids are places (a choice, above).
**Round 3 (#1204):** every writer that holds a per-battery list holds it in the battery order it read, and saved it by place. The Config card sent a whole list from the copy it read when it opened, and a copy that failed to read emptied every other slot. The Configure dialog copied the two limit lists into its draft and saved them at the end. A Mode select or reserve number writes its slot number, a place in the order it was built for, until the reload rebuilds it; a change during the first refresh moved the lists after that order was taken. **Closure:** a writer says which order it read, and one rule (`battery_controls.slot_today`) finds that battery's place today. The card sends one battery's edit with the order of its copy (`battery_slot_edits` in `set_option`): it lands on that battery's slot, every other slot stays as saved, and a battery that is gone is refused (`battery_list_changed`); then the card reads its copy again, and a read with no config keeps the copy. The dialog reads its lists and the order together; after each page and at the save its draft follows a change (`lists_in_current_order`), the pages start again from the first battery, a battery the pages never showed keeps its own slots, and the pages stop at the batteries the record holds. The controls write through `put_battery_slot` with `battery_control_units`, taken at setup and moved by a change before the platforms are built (`_battery_controls_built`); SEM's own mode write is in today's order. The Mode select shows its own battery until the reload. **Guard:** `tests/test_1204_battery_writers_follow_the_order.py` — the rule (added, removed, damaged, a sensor twice), the edit and its refusals, the select and number before the reload, the controls' order at setup and on a first record, the dialog with a change after the pages, between pages and a removal; the card's save through `set_option` on the real integration after the dashboard grew and shrank. A source scan lists every function that writes one of the six lists by name, with the reason it cannot put an old order back, and fails on a new one; a twin shows it catches one. `dashboard/card/test/battery-slot-edit.test.js` pins the card's payload. The behaviour tests fail on the old code. **Left open:** a browser tab left open across the update runs the old card until it reloads; its whole list is taken as today's order, as a script's is (a choice: once, at the update).
Refs #1195 #1171 #523 #1089 #1071 #923 #274 #1204 #1205 #1257.

### 167. Two lists joined by place, filled by different rules — entry N of one is not unit N of the other — GUARDED
**Symptom:** on a home with a two-sensor battery listed first in the Energy Dashboard, SEM judged the sign of combined battery b1 by the two-sensor battery's energy counters. When one charged while the other discharged, SEM flipped b1, and its charge read as discharge (#1193, found while fixing #1171). A one-battery home with a battery that has no power sensor listed first was judged by that other battery's counters the same way.
**Root shape:** the parser fills `battery_charge_energy_list` / `battery_discharge_energy_list` with every battery that has a counter, in dashboard order. bN counts combined power sensors first (`battery_units`), and skips a battery with no power sensor. The sign check took entry N of the counter lists for bN, and the one-battery check took the first counters. Both joins are right only while every battery is combined and has its own power sensor, which is the only home the code was written for. Kin of class 162 (one kind of unit in two lists) and class 166 (a place taken for a unit), but here two lists built at the same moment disagree on who is entry N.
**Where it lives:** `coordinator/sensor_reader.py` — the per-battery loop in `read_power`, `_detect_battery_sign` (one battery), `_audit_battery_sign_lock` (#647, both shapes) and the sign payload (**fixed**); `config_flow.py` setup summary (numbered counters by list place, **fixed**); saved sign locks learned on the old join (**fixed**: `_drop_locks_on_other_counters`). Checked and right: `battery_soc_list` is never read per battery; no other per-source list is joined by index. Kept on the first counters on purpose: the raw "first source" fields in `coordinator.py` `battery_info` / `_build_ed_config_summary` and `diagnostics.py` `energy_sensors` (they describe the dashboard, they decide nothing).
**Closure:** the parser records each battery's own counters by its `battery_units` entry (`battery_unit_counters`; a derived sensor gets the counters it was found from), and every reader asks `unit_energy_counters`. The one-battery read is judged by the counters of the battery it reads: setup saves the dashboard's sensor as `battery_power_sensor`, so a pick the dashboard knows is that battery. A store without `battery_counters` has each restored lock checked once, on the first read that uses it; a lock whose old counters were not its own is judged again with its sign kept as the start value (after the #1194 move, saved as `battery_sign_kept` across a restart, never moved by a brand seed), so nothing reads differently before new evidence. While "Fix battery sign" is on, the check waits.
**Guard:** `tests/test_1193_own_battery_counters.py` — the parser from HA's prefs layout (pair first, no power sensor, Inverted, derived, one sensor twice); the real `read_power` on the mixed and the one-battery homes, also through the setup-saved pick; the #647 audit both ways; the saved locks: judged again, kept when their old counters were their own, waiting while the home reads the other way or the user flip is on, a restart before the check and before the new lock, a brand default that must not move the kept sign, the #1194 order. An AST check lists every function that reads the counter lists with why; a new reader fails until declared, and a twin fires on the old pairing. 24 of its 35 tests fail on the old reader.
**Sweep question:** where two lists describe the same units, were they filled by the same rule — and if not, what ties entry N of one to entry N of the other?
**Left open:** a stale one-battery lock on a home that now has two batteries stopped the per-battery #647 audit (#1210, **fixed**, class 174). A lock saved by place moved to another battery when one is removed (#1205, **fixed**: class 166 round 2).
Refs #1193 #1171 #647 #589 #1194 #1195 #1205 #1210.

### 168. One empty value for "nothing to save" and "saved by an older build" — the reader takes the older build's rule — GUARDED
**Symptom:** a "Fix grid sign" tap made while SEM read no grid meter flipped the meter SEM found later: import read as export (#1192, found while fixing #1172). A user whose grid reads 0 W is the one who taps the button.
**Root shape:** #971 saved the tap with the grid source in use, and read a flip with no source as one from before the binding, which applies to every auto-found meter. With no meter, the new build saved the tap with no source too (None). One stored value then meant two things, and the reader took the wider rule. Kin of class 105 (None doing two jobs) and class 54 (a key present holding None).
**Where it lives:** `coordinator/sensor_reader.py` `user_flip_options` / `user_flip_applies` and the flip service's no-reader save in `__init__.py` (**fixed**). Swept: `_read_from_legacy_config` named no source, so every tap without an Energy Dashboard was a no-meter tap and was never applied (**fixed**: each branch names its source; its saved lock still waits for a dashboard read, `_check_restored_grid_lock`); `grid_sign_user_override` read the saved flag, so a flip about no meter or another meter stood the balance self-heal down (**fixed**: a flip that applies); the service toggled the saved flag, so the tap the log asks for only cleared a flip that did not apply (**fixed**). Checked and right: the saved lock's `grid_source` (a saved None is compared, not skipped); `battery_counters`, `unseen_kwh`, `rated_power_rule` and the #1146 `calendar` slots are always written with a real value. **Round 2 (#1208):** `battery_basis` was not. The reader left it out while the #1194 move waited, and only an Energy Dashboard read settled the move, so a home without one never saved it; a dashboard added later moved this build's lock, or locked a sign against its flip (**fixed**: `_read_from_legacy_config` settles the move with nothing to change once the dashboard read answered "none", `set_dashboard_answered`; a dashboard SEM could not read still waits, and so does a saved fleet lock, because no build learns one without a dashboard: it came from an older build's dashboard read, maybe the flipped one). And an older build writes `sign_state` again from the keys it knows, so going back and forward again moved a lock this build learned (**fixed**: `export_battery_basis` saves the fleet lock and the flip as the top-level energy-store key `battery_sign_basis`, which every build since 1.7.6 keeps because it saves `{**self._energy_data}`; a store without the mark whose fleet lock and flip still match its three keys is this build's and is not moved; a lock or flip the older build changed is moved as before; Reset sign detection writes the record with the reset state). Swept for the same round trip: `battery_counters` and `grid_source` drop too, which only re-checks a lock or trusts it as the older build did (right: the older build may have learned on the old pairing or source); `rated_power_rule` drops, which re-reads the rating from history once. The device store is saved from a fixed key list, so an older build drops `legacy_flags_adopted` and `control_modes_user`, and the #888 migration then clears the user's own hands-off marks (#1253, open: needs a copy in a store the older build keeps).
**Closure:** a tap is bound to the source this cycle read with a live value (`_grid_read_source`); with none, or only a dark meter, it is saved as `NO_GRID_SOURCE` and applies to no meter. A saved None reads the same; only a store without the key is a flip from before the binding, and that applies on the dashboard read only (the read without one has not applied it since #971). The read without a dashboard saves and checks its lock as before (`_lock_source`). A second tap with no meter turns the flip off (`user_flip_on_for_tap`).
**Guard:** `tests/test_1192_flip_with_no_grid_source.py` — the reported case through `read_power`; a None or empty saved source; every auto source refuses a no-meter flip; a tap while the meter is dark or no branch reads it; a read that raises keeps the lock's source; flips from before and taps on the meter unchanged; the diagnostics and the log; both reads tag every grid branch (AST); the read without a dashboard binds, keeps old flips off and keeps its lock, also into a dashboard read of a pair; the self-heal; the real service handler. 19 of its 40 tests fail on the old code; a review killed 13 mutants.
**Sweep question:** when a new field's absence means "an older build", can the new build ever write that same empty value? Can an older build write it back after the new one ran (going back a version and forward again)?
**Guard (round 2):** `tests/test_1208_sign_record_beside_the_store.py` — a lock and a flip this build saved survive an older build's save (both signs, both read directions); a lock or flip the older build changed is still moved; no or a damaged record moves as before; a brand default is not a lock in the record; the record waits with the move; a home without a dashboard saves the mark (with and without SEM's own pick), keeps its flip and lock when a dashboard is added, and settles nothing when the dashboard read got no answer; the store key sits beside `sign_state`; a saved fleet lock waits through reads without a dashboard and moves on the next dashboard read; a record with more keys still counts; the real integration restores from the record, saves it, settles a home without a dashboard, and Reset sign detection writes the record at once. 12 mutants of the fix are killed. A review found the first cut settled a saved lock without a dashboard.
**Left open (round 2):** a store from 2.2.0-beta.28 or beta.29 has the mark but no record; going back an older version and forward again moves its lock as before (nothing records it). The battery flip is not bound to a sensor, so a flip set on SEM's own pick and kept after the pick is removed judges another read (a choice, as before).
**Left open:** a tap during a dark cycle says "flipped" but binds to no meter; the diagnostics show it (`grid_read_source`). The balance self-heal could negate a declared pair (#1215, **fixed**: class 173).
Refs #1192 #971 #1172 #690 #1215 #1208 #1194 #1253.

### 169. A view that lists by hand what the data publishes — a new row is counted but never drawn — GUARDED
**Symptom:** the Energy tab Sankey had no Battery → Grid line. A battery sale was in the Export total, but no line led to it (#1190, found while fixing #1172).
**Root shape:** #776 added the `battery_to_grid` flow and its sensors. The Sankey lists each flow by hand in the template, and nothing tied that list to the flows SEM publishes, so the new flow was never added there. Kin of class 66 (keys written that nothing reads).
**Where it lives:** `dashboard/sem_dashboard_template.yaml`, the `custom:sankey-chart` card (**fixed**: the Battery node's child and a `Bat>Grid` node into Export, its label in all 16 tables of `dashboard/translations.json`). Swept: `icons.json` had no icon for `flow_battery_to_grid_power` / `_energy`, and the Sankey shows entity icons (**fixed**); `scripts/verify_translations.py` lists the Sankey labels by hand (**fixed**). Found beside it: the Czech "Export" label read "Přeток", with three Cyrillic letters (**fixed**, guarded). Checked and right: the system diagram draws node power, not flows; the solar card lists all four solar flows; the EV chart lists all three EV sources; the battery card shows the two charge sources; the native `energy-sankey` fallback is fed by HA's Energy dashboard, not SEM's flows.
**Closure:** the Sankey draws every `flow_<from>_to_<to>_energy` sensor: a child of its source total, and a middle node that leads to its target total. A battery-less home loses the new line with the other battery entities (#923).
**Guard:** `tests/test_1190_sankey_every_flow.py` — reads the flow keys from `SENSOR_TYPES`, so a flow added later fails until the Sankey draws it; the label in every language; the prune for a home without a battery; the German name through the real translation step; no Cyrillic letter in any translation table. A flow end of two words (`heat_pump`) still matches. Four of its first five tests fail on the old template.
**Sweep question:** when SEM publishes a new row, which hand-written lists in views should hold it too?
**Left open:** the Energy Impact card computes its own CO2 figure from two flows instead of reading `sensor.sem_daily_co2_avoided` (a second copy of a formula, not this shape; #1221).
Refs #1190 #776 #1172 #923 #1221.

### 170. A source SEM cannot find reads 0 W — and only the log says why — GUARDED
**Symptom:** the Energy Dashboard's grid entry had kWh counters and no power sensor, and SEM found none on the meter. Grid read 0 W: no Grid lines in the Sankey, wrong flows, wrong surplus. One log line, `No grid power sensor found`, was the only trace (#1188, found while fixing #1172).
**Root shape:** the dashboard proves the source exists (it counts its kWh), SEM finds no power sensor for it, and 0 W is read. 0 W looks like a reading, so nothing a user looks at points to the cause. #799's rule — a log line is not a surface — had reached the half-found grid pair (`split_grid_rejected`) and the name guess (`split_grid_guessed`), not the case where nothing was found.
**Where it lives:** `coordinator/sensor_reader.py::_read_from_energy_dashboard`, the last branch of each source's read: grid (split search found nothing, or an export counter alone matched no branch), solar and battery (no power sensor, and the #274 retry in `coordinator.py::_retry_energy_dashboard_resolution` gives up with one log line). All three **fixed**. Checked: the legacy path has no counters, so nothing says a source exists; a charger with no power sensor is a config-flow field, not a search.
**Closure:** the read records each source it counts but reads from nothing (`_unsourced_power`); `report_unsourced_power`, called by the cycle after the read, files `power_sensor_not_found_<source>` (one text, the counter as placeholder) once HA runs, the dashboard retry is over and `UNAVAILABLE_REPAIR_THRESHOLD_S` has passed (class 86). It clears the cycle a sensor or a Config card pick is found, or the dashboard stops counting the source. Each source's first "found" of a reader clears an options-reload leftover once, also when it is found only after the first cycle (class 84; the review caught a single flag that missed that). A cycle that did not read the dashboard changes nothing. A failed raise is tried again. Non-persistent; the text says a home with no power sensor at all may ignore it.
**Guard:** `tests/test_1188_no_power_sensor_repair.py` — each source parametrized over `POWER_SOURCES`, the reporter's P1 home, start-up, the retry, a late meter, the picks, half a grid pair, clears, raised once, every other read path (declared pair, sum, manual pair, two inverters, two batteries, battery pair) left alone, the export counter alone, the reload leftover found late, a failed raise, the cycle's call site, the placeholder in all 17 files, and an AST check that every source in `POWER_SOURCES` is recorded by the read.
**Sweep question:** for every input SEM reads as 0 W because it found nothing, who is told, and where?
**Left open:** a second inverter or battery with kWh and no power sensor was never searched for, so SEM summed only the units it had (#1226, **fixed**: round 2 below); the two grid-guess Repairs were English in 14 languages, and the class 143 test missed it (#1227, fixed). Not filed: a split-grid scan that throws (#259) reads as "nothing found" here — the Repair's advice still fixes it, and the log says the scan failed.
Refs #1188 #1172 #799 #947 #911 #274 #1226 #1227.

**Round 2 (#1226) — every unit, not the first.** A home with two inverters (or two batteries), one with kWh counters and no power sensor, read solar (or battery) as the other unit alone, and no Repair said so. The derive (`ha_energy_reader._derive_missing_power_sensors`, `_derive_battery_power_if_unrepresented`) looked for a power sensor only when the scalar `solar_power` / `battery_power` was empty, and those hold the first unit. #761's battery guard asked the same of the house: one two-sensor battery stopped the search for every other battery. The reader recorded a source as missing only in the branch where no unit read. Kin of class 52 round 2 (the scalar is the first source) and class 146 (a check every unit needs, asked of the first).
**Closure:** the parser keeps each source with counters and no power (`solar_energy_only`, `battery_energy_only`), and `_derive_unit_power` asks each one on its own device. A sensor found joins the unit list the reader sums (`derived_units` says which; `derived_power` names a type only when its scalar was found). A battery keeps its own counters (class 167). A source with nothing found is kept in `unsourced_counters`; the reader names all of them in the same Repair, and `power_resolution_incomplete` keeps the #274 retry going for them. When other units of the source read, the Repair has its own text (`power_sensor_not_found_unit`): it sends the user to the Energy Dashboard only, since the Config card pick stands for the whole source and would drop the units that read. A source whose counter sits on a device a unit of its type already reads (its power sensor or its counter) is left alone and not named: that device's sensor may hold it too (an inverter's string rows, a fleet sensor beside a pack's own), and a second one would count the same watts twice. The review found three more: (1) a found battery depended on its integration having loaded, so a slow start dropped it and its saved slots (class 166); a sensor with no state is now judged by the registry (`_registered_as_power`, as #1172 does for declared keys), so the list is the same on every start. (2) A first slot record (no `battery_slot_units` yet) took the slots as they stand, so a battery found beside a two-sensor one took the pair's slot and its control entities; `battery_units_before_derive` gives the old numbering for that first record, and the found battery starts unset. (3) Setup saves the dashboard's first battery sensor as the battery pick (`to_dict`), and the reader took that as a pick for the whole battery; a pick that is one unit's own sensor no longer hides the Repair (solar the same, for a pick set by hand). A second review found two more: (4) a row linked to a site total (a site meter on another device, a template) already holds the other rows, and adding a found sensor read 7000 W for 5000 W; a link not on its own counter's device now stops the search for its type (`_derive_unit_power` `links`), and nothing is named. (5) A pick for the whole source (the #1226 work-around) lost to a found sensor once two units were listed (#623 sums first); `yield_found_units_to_picks` takes the found units out before the reader and the platforms read the config, while at most one linked unit is left. Checked and right: grid counters are tariffs of one meter, and a split meter is found in the reader; per-unit SOC and sign follow the unit list; the PV string slots show inverter totals once two inverters read, as for two linked ones.
**Guard:** `tests/test_1226_every_unit_power.py` — real registry, real parser and reader: a second inverter (either order) and a second battery are found and summed, with their own counters; a battery beside a two-sensor one; nothing found: the Repair names the counter (two named together), clears when a late integration registers, uses the per-unit text while others read and the #1188 text when none do; never twice: a string row on a read inverter, a counter beside a template link, two rows of one device, a pack beside a fleet sensor; the picks, also the saved first sensor; a site total or a template total on one row is not added to; a whole-source pick beats found units, beside two linked units it changes nothing, and the dashboard read applies it before the hand-out (AST); a cold start with no states finds the same batteries; a registered non-power sensor is not taken; the first record keeps the pair's slot, at the real call site; the per-unit text in all 17 files; diagnostics. An oracle builds every home of one to three solar sources and one to three batteries (linked, found, nothing on the device): each source is read or named. 13 of its first 18 tests fail on the old code; eight mutants of the review fixes each fail a test.
**Left open:** a second row on a device SEM already reads, or beside a link SEM cannot place (a template, a Riemann sum of the inverter's own sensor), is neither read nor named: a Shelly 2PM channel or a Deye BAT2 with only the other one linked (#1236). A found battery is numbered before two-sensor batteries, so on a home with those their `b<N>` entities move by one (settings follow, class 166; automations on the old numbers do not), and SEM starts to steer the found battery like a linked one. The diagnostics summary line still says `pwr=stat_rate` when a second unit was found (the per-source lists say it). A counter with no device keeps the #274 retry going though nothing can be found (a few minutes; a choice).

### 171. A rule for the moment of a read, used for a step that covers hours SEM did not see — GUARDED
**Symptom:** HA was down from 02:30 to 20:00 on 12.10.2026 (PROD). The inverter's yield counter rose 30.38 kWh in one step, read after sunset. Daily solar stayed 0 kWh while the meter rows took their whole steps (20.42 kWh export, 8.79 kWh into the battery), so home, their balance, fell from 1.62 to 0 kWh (#1187, found while fixing #1177).
**Root shape:** a delta model books `value − last` and judges it by what holds at the read: the sun gate (#681) drops a step read in the dark. A step is one cycle while SEM runs, so the read's moment is the step's own. Across an outage one step covers night and day, and the read's moment says nothing of most of it. Kin of class 142 (there the step is booked into the window it arrived in).
**Where it lives:** `EnergyCalculator._reconcile_solar_energy`: a read after dark dropped the day (**fixed**); a read in daylight after a night start booked the night's battery output as solar (**fixed**). A solar counter dark across sunset while SEM runs now takes the same path, through the upward-only target, so the integral is not counted twice. Checked: the meter rows (`_reconcile_metered_energy`) have no gate on the moment, and their cost moves at the day's average rate (#795); the EV rows judge unseen time (class 142). Round 2 (#1228): an own-tariff device meter shared its step over an outage against one cycle's import and share (`EnergyCalculator._import_cost`). The 2 kWh a heat pump used in an hour HA was down were dropped, and the house cost took them at the house price (**fixed**). The grid meter's correction priced the outage at the day's average, which held the devices' own prices (**fixed**).
**Closure:** each read keeps a record (`span`: time, the sun's next rising or setting, each bound counter's reading, the solar row, the counters read). A step older than `MAX_INTEGRATION_GAP_SECONDS` that passed that sun event is credited less the batteries' output and the grid import over the same span (`SOLAR_GAP_BOUND_CATEGORIES`): in the dark a hybrid's counter moves only by those (#681). It goes through the old upward-only target, anchored at the row of the last read. A bound counter not read yet waits up to `SOLAR_GAP_WAIT_S` once HA runs (the solar row is not counter-backed meanwhile). All of the step is held back, as before, when nothing proves the bound: a battery with no discharge counter, a counter that went back, a set that changed, no reading before the gap, a counter HA computes (Riemann sum, a `source` attribute, SEM's own). No record (a store from before, a new day, no `sun.sun` times): judged at the read, as before. Round 2: a device meter step whose last booked read is older than `MAX_INTEGRATION_GAP_SECONDS` is held (`device_meter_gaps`, stored) and booked at the end of a cycle against the house rows over the same span (`_settle_meter_gaps`). Each booked read keeps the day's import and its cost, what the house, the batteries and the car used, what own-tariff devices took, and the time this run integrated. Grid kWh = step × import ÷ used over the span, at most the import no device took. They leave the house cost at the rate the house booked them, at the device's day average (else its price at the read, else the house's). The rows cover the span when SEM integrated all of it, or when every configured counter, solar and the home balance are read this cycle: a counter still loading reads as no flow. A house that has made solar but has no solar counter needs the sun down at both ends with the same next sunrise. Steps settled in one cycle share the least free import in proportion. It waits up to `SOLAR_GAP_WAIT_S` once HA runs; each run starts the wait again. Dropped and logged with no grid import counter (the house lost that import too), PV with no counter and the sun maybe up, a new day, no rows at the start, a device no longer on its own meter, or after the wait. The grid meter's correction prices at the house's own average, without the kWh devices took at their price.
**Guard:** `tests/test_1187_restart_after_dark.py` — the PROD day books 24.71 kWh and home 2.79 instead of 0; the night after it, a read in daylight after a night start, a watched morning then down into the night, gaps inside one night, before sunrise and inside one day, one cycle across sunset, two batteries and two inverters, more output than the step, the wait (loading counters, the clock, its end), what the integral added while waiting, a night charge from the grid, every unknown bound, damaged and missing records, the store round trip, and the cycle's own time. Each part of the fix fails a test when removed. `tests/test_1228_own_meter_outage.py`: the hour down books 2.0 kWh at the pump's price (0.03 before) and the house cost holds each kWh once; a battery carrying half the hour halves it; a battery counter still loading is waited for; no import books nothing; two meters never take more than was imported; with no grid counter it is dropped and the next cycle stays the house's; a meter dark while SEM runs is booked from the rows; the wait, its end, no clock while HA starts; a new day and a store from before drop it; an unreadable price moves no money; the house average leaves the pump's price out; the pump's kWh leave at the rate the house booked, not today's; its hour is priced at its day's average; two meters share in proportion; PV with no solar counter: a span the sun may have lit and a night to the next night are dropped, a night with no sunrise inside is booked; each restart starts the wait again; a step of a meter that is gone is dropped; a held step survives a restart; damaged entries are dropped. Fourteen mutants of the fix each fail a test (one more is the same code).
**Sweep question:** for every rule a counter step is judged by (sun, tariff, a live flow), does it hold for the whole span the step covers, or only for the moment it was read?
**Left open:** the bound reads low: a string inverter with an AC battery loses the gap's discharge and import, a hybrid the PV it put into the battery (a choice: never high). A battery with no discharge counter still loses a gap read after dark (nothing bounds it). A daytime gap on a hybrid is compared with the whole day, so the integral's lead takes part of it (class 28; the yield counter trails PV by day). A gap across midnight starts the new day at first sight, for every row alike (documented in the reconcilers). Round 2: a meter that moves in steps bigger than one cycle's use is still shared against one cycle's import (#1230: 0.01 kWh steps booked 1.27 of 2.0 kWh). Over a span the share is the grid's part of all that was used, not SEM's live flow order (grid to battery or car counts in). A few minutes of live time while it waits count in the share. A battery with no counter whose row is still 0 reads as no flow over the span. A short restart whose import sits inside the meter rows' dead band (`METER_RECONCILIATION_THRESHOLD`) is booked against the rows without it; the house takes it later at its own rate (a few Wh).
Refs #1187 #681 #1177 #556 #628 #1228 #812 #1230.

### 172. A cap writes the day alone, after a correction moved every period — the next cycle books the same step again — PARTIAL
**Symptom:** a battery counter step above the daily cap (3 × the battery size) made the month, year and lifetime grow on every cycle. A 100 kWh step on a 10 kWh battery left the day at 30 kWh and the lifetime at 2,130 kWh after 30 cycles; the day's battery savings reached 4.9e16 (#1218, found while fixing #1191).
**Root shape:** one row, two writers, two ceilings. The counter correction moves the day and every longer period by its step, and checked only the 1,000 kWh unit trap. The cap after it writes the day alone. The correction measures its next step from the day, so it books the step the cap took away again, each cycle. Its cost moves too, at the day's own rate, which the step had raised: the savings grew without end.
**Where it lives:** `EnergyCalculator._reconcile_metered_energy` on `battery_charge` / `battery_discharge` (**fixed**). `_reconcile_solar_energy` already refused a target above `kWp × 16`, with the figure written out a second time (**now reads the same helper**). EV: `_reconcile_ev_bucket` and `follow_charger_counter` refuse above `_max_daily_ev_kwh`, and no cap writes after them (assessed). Grid and home rows have no cap (assessed).
**Closure:** `_daily_ceiling(category)` is the one figure for a row: the cap in `calculate_energy` reads it, and each counter correction refuses a target above it (the battery rows warn once a day, solar each cycle as before). A refused row is not counter-backed, so the home balance does not build on it. A counter that comes back below is followed again from a new baseline; one that stays above leaves the row to the power sensor for the day.
**Guard:** `tests/test_1218_daily_cap_counter.py` — the reported shape on both battery rows (month, year and lifetime hold the day, the day is the power's, the savings stay bounded); a step inside the ceiling is still followed; a spike that goes away is followed again; one warning a day; a refused battery or solar row is not counter-backed; an oracle that steps every counter at once (battery, grid, solar, with a sale beside the export), inside and above each ceiling, and checks that all four periods hold the day; an AST check that the cap and both corrections read `_daily_ceiling`. The old rule fails nine tests on behaviour; removing the counter-backed change fails two.
**Sweep question:** for every row a cap writes, does each writer before it refuse what the cap would cut — and does the cap move the periods those writers moved?
**Left open:** the cap still writes the day alone when the power sensor alone takes the day past it, or a followed counter sits inside the 0.05 kWh dead band under it; the month then keeps what the day lost (#1243: which figure wins when the set battery size is too low is a choice). A day already at the cap when its counter is first read refuses that counter for the day: the anchor holds the cap. The charge-split rows still do not follow a battery counter (#1217).
Refs #1218 #1243 #1191 #628 #556 #1217.

### 173. A rule kept where one writer sets a flag, not where the flag is read — the other writers break it — GUARDED
**Symptom:** a house with an import/export pair as grid meter exported 2000 W, and SEM read 2000 W of import. Solar read low (the real fault), the energy balance was negative for 3 minutes, and the balance self-heal flipped the grid sign. The flip cleared the balance, so it was kept and saved (#1215, found while fixing #1192).
**Root shape:** "a pair is never negated" (#1103) was kept in one writer of the grid lock, the restore check. The read applied the lock to every grid source. Three other paths write the lock: the balance self-heal, the solar override and the brand seed (which reaches a found pair before the counters prove it). Each could negate a pair. Kin of class 29 (a guard in one branch) and class 161 (one register, two writers).
**Where it lives:** `SensorReader._detect_grid_sign` and `SEMCoordinator._check_sign_flip` (**fixed**). Swept: the solar override and the brand seed on a pair (**fixed** by the same read); a lock the bug saved with the pair's own source, which the restore check kept (no longer applied); the read without a dashboard, whose manual pair took a lock saved with no source (**fixed**); one battery read as a two-sensor pair, which took the fleet lock from a saved store or the brand seed on its charge counter (`_detect_battery_sign`, **fixed**); `sensor.sem_diag_grid_sign` / `_battery_sign` showed the lock, not what it does to the read (**fixed**); the restore check (#1103) cleared a lock carried onto a pair, so a move back to the meter read the wrong sign (**fixed**: kept, second review). The #166 wait in the self-heal for a low-confidence found pair could no longer run (a found pair is a pair once read, and reads 0 W before), so it is gone. Checked and right: the pairs of a battery fleet join the total as they are (#553); the user's flip and `grid_sign_invert` still apply to a pair (a user choice).
**Closure:** one predicate, `SensorReader.grid_read_is_pair()` (`_PAIR_GRID_SOURCES`: manual, ed_pair, discovered). On a pair the read runs no detector and applies no lock; a lock set to negate is said once in the log. The lock is not written: it is about the source it was learned on, and a home that goes back to that meter needs it (the first draft cleared it; the review found the way back read the wrong sign). The self-heal stands down on a pair before it counts. The battery read marks a one-battery pair (`_battery_read_is_pair`, per cycle), and the fleet lock is handled the same way. The diagnostics say whether the read is a pair.
**Guard:** `tests/test_1215_pair_sign_never_negated.py` — the reported balance through `read_power` and the self-heal for all five pair reads (manual, dashboard pair, found on the meter's device, found and proven, no dashboard); nothing saved; a lock the bug saved; a lock set between reads; the solar override; the brand seed before the proof; meter → pair → meter (also across a restart) and one sensor → pair → one sensor keep the lock; a one-sensor meter is still healed; the user flip and `grid_sign_invert` still apply; the card's sign lines; an AST check that every grid source the reads name is a pair or a learned source, and one that the self-heal asks the reader. 37 of its 42 tests fail on the old code. `tests/test_split_grid_integration.py`: a found pair at either confidence is left alone.
**Sweep question:** when a rule says "this flag never holds X for Y", is it kept where the flag is read, or only in one of the places that write it?
**Left open:** on a one-sensor meter the self-heal still blames the grid when the fault is elsewhere and the flip clears the balance (#690); the solar check turns it back when the sun moves, and the self-heal then stops for good. A pair whose sensors are set the wrong way round, or a found pick of the wrong role, is no longer turned by the self-heal or the solar check; the counter audit says so (not on the read without a dashboard), and "Fix grid sign" corrects it (a choice: SEM does not override a pair). A lock the bug saved stays in the store; it applies to no pair, and a later move to another meter learns the sign again (#1103), except on the read without a dashboard, whose lock has no source.
Refs #1215 #1192 #1103 #971 #690 #553 #166 #947.

### 174. A check picked by which lock is saved, not by how the home reads now — the old lock is checked, the new ones never — GUARDED
**Symptom:** a home that started with one battery and added a second kept its one-battery sign lock in storage. The read signed each battery with its own lock (b1, b2), but the #647 audit saw the old lock, judged the sum and returned. A wrong b1 or b2 sign was never flagged: one battery read wrong and one right sum to about 0 W, which the audit skips as idle (#1210, found while fixing #1193).
**Root shape:** two places answer "does this read sign each battery on its own?". The read asked the battery count; the audit asked whether the one-battery lock was saved. Both answers agree only on a home that never changed its batteries. Kin of class 139 (one question, two rules) and class 151 (a check keyed on a state an earlier build left).
**Where it lives:** `coordinator/sensor_reader.py` `_audit_battery_sign_lock` (**fixed**: asks `_reads_per_battery`, the read's own rule). Swept: an audit of the other way of reading was never fed again, so its raised flag stayed on — a one-battery flag after a second battery, and b1's flag after going back to one (the setter's prune keeps b1); **fixed**: the audit drops every audit this read does not run (the lock stays saved). A one-battery two-sensor pair takes no lock (#1215) but was still audited on an old lock, and the warning said to reset a lock that does nothing (**fixed**: not audited, as each pair of a fleet). `sensor.sem_diag_battery_sign` listed the saved locks, so a two-battery home showed `__fleet__: negated` beside b1 and b2, and a removed battery's or a two-sensor battery's id kept its lock on show (**fixed**: the locks the last read applied; the full store before the first read). Checked and right: `_move_lock_learned_on_flip` and `_drop_locks_on_other_counters` take the read's own `per_battery`; `_detect_battery_sign` runs only on the one-battery read; the grid audit's `_grid_sign_detected` gate is set by every grid read, pairs too; `battery_sign_diagnostics()` lists every saved lock per bid on purpose.
**Closure:** one rule, `SensorReader._reads_per_battery(ed, readings)`, for the read and its audit, and one list of the locks a read applies, `_battery_lock_bids`, for the audit and the diagnostics (`_battery_read_locks`, kept by the read).
**Guard:** `tests/test_1210_stale_lock_audit.py` — the real `read_power` on homes parsed from HA's prefs: a wrong b1 caught beside an old one-battery lock; right signs beside a wrong old lock stay quiet and get no one-battery audit; the one-battery home still checks its lock; a flag from the other way of reading dropped both ways (the lock kept); a one-battery pair not audited; a dark battery does not reset the other battery's count; the diagnostics sensor; an AST check that the read and the audit both call `_reads_per_battery` and that no top-level branch of the audit asks a saved lock. 8 of its 11 tests fail on the old code.
**Sweep question:** when a branch picks how to check something, does it ask how the system works now, or what an earlier run saved?
**Left open:** a battery read as a two-sensor pair is not checked against its counters, one battery or several (#647 chose this for a fleet), while a grid pair is. A pair with its sensors swapped is not flagged; "Fix battery sign" corrects it. A choice, not filed.
Refs #1210 #1193 #647 #589 #1215 #404.

### 175. A change queued to be saved later, then a reload reads the file — the new lifetime starts from the old state — GUARDED
**Symptom:** "Reset sign detection" with a "Fix sign" flip on reloads SEM. SEM came back with the signs it had before the reset, and its next save wrote them again. The flip was gone, so a sign the user had corrected read the wrong way (#1209, found in review while fixing #1194).
**Root shape:** the reset cleared the signs in memory and queued the write with HA's delayed save (`async_delay_save`, 60 s). That save waits for 60 s with no new call, and SEM calls it every cycle, so it lands only when SEM stops. A reload builds a new store that reads the file, and the file still held the old signs. Every reload had this (an options change, `set_option`, "Fix sign", a removed charger): the new lifetime read the energy store as it was at its last real write. The old store also went on: its queued write and its HA-stop listener, never removed, wrote the old lifetime's data over the new one's, and put back the files of a removed SEM. Kin of class 84 (what a lifetime holds dies with it) and of the note in `storage.py` that a queued save lands only at a clean stop (#645, #800).
**Where it lives:** `async_reset_sign_detection` (**fixed**: writes at once). Swept: every reload path — the options listener, `set_option`, `flip_grid_sign`, `flip_battery_sign`, `remove_charger` and the reset itself (**fixed** by one close on unload); a disable (**fixed**, same close); a removal, where the queued write and the stop listener brought `_energy` and `_daily` back (**fixed**); the stop listener each reload left behind, which kept every old store in memory and wrote it at HA stop (**fixed**: removed at the close); a setup that fails after the first cycle loaded the store, which HA retries with a new store and never unloads (**fixed**: both `ConfigEntryNotReady` branches end the store, review); a Simulation run still going at unload, whose cancelled record the on-unload hook put in the store after the close (**fixed**: cancelled before the flush, review). Checked and right: SEM's other stores (load management, device registry, pacing, export cut, charge target, park record, Deye snapshots) write at once and have no stop listener; the Simulation run's own write on unload (#1083) stays, and the close now covers it too. Not covered: an unload whose platforms refuse to unload leaves SEM running, store and all.
**Closure:** `SEMStorage.async_close()`, through `_async_end_store`: last in `async_unload_entry`, and in each failed-setup branch. It ends the store first, so a cycle still running cannot queue a write in the wait; then it removes the stop listener and writes both stores at once (only if they were loaded). From then on every write of that store is skipped (`_ended`, said in the log except for the cycle's own queued save). The reset writes at once (`async_save_energy_now`), so a restart before the next real write keeps it too.
**Guard:** `tests/test_1209_reload_reads_saved_state.py` — real HA, with HA's storage mock as the disk: the reset with either flip on stays reset after its reload; the reset without a flip is on the file at once; a sign and a hint queued by the cycle's save survive a plain reload; after a reload the old store writes nothing (queued write, late task) and the stop listener count does not grow; a removed SEM's files stay gone past the queued write and HA stop; a setup that fails in the first cycle or in the platforms leaves no store listening; a write asked for while the close writes arms nothing. Source checks: only `storage.py` queues a write; each SEMStorage writer asks `_ended` first, and the one that does not is called only by `async_save_all` and the close; the unload and every `ConfigEntryNotReady` branch after the first cycle end the store. 11 of its 12 tests fail on the old code.
**Sweep question:** when a lifetime ends, is what it means to keep already on the file — and can anything it left behind still write?
**Left open:** a home without a battery writes the energy store only at a clean stop and once a day, so a power cut loses what it got that day (finished EV sessions, learned signs, hints) — filed as #1252.
Refs #1209 #1194 #645 #800 #935 #1083 #1252.

### 176. "Dark" decided by two words, not by "gives a number" — any other state reads 0 W as if measured — GUARDED
**Symptom:** a power sensor whose state was text ("none") read 0 W: `sensor.sem_battery_power` showed 0 W, `sensor.sem_battery_status` said Idle, and `inputs_degraded` stayed off, so SEM steered on a 0 W it never read (#1202, found while fixing #1197). "nan" was worse: `float("nan")` does not fail, so NaN went into the sums as a reading (found while fixing #1196).
**Root shape:** two tests answered "is this a reading?". The dark branch asked for two words ("unknown", "unavailable"); the parse asked `float()`. A state between them took the parse `except`, which returned the dark branch's 0.0 without the dark marks (`_input_dark`, `_battery_power_missing`, the Repair clock). And `float()` says yes to "nan" and "inf". Kin of class 100 (a failure that looks like a reading) and class 148 (a missing answer read as "no").
**Where it lives:** `coordinator/sensor_reader.py` `_read_sensor`, the one door for every power input, battery unit, PV string and SOC (**fixed**: dark is `power_state_to_watts(state) is None`); `coordinator/units.py` `_convert` and `temperature_state_to_celsius`, which let NaN and inf through (**fixed**: `state_number`, finite only; a caller that passes its own bare `float()` as `default=` still gets NaN back, #1262); `SensorReader._read_battery_soc_average`, which read a dark unit as 0 % — 60 % and "unavailable" averaged to 30 %, covering 2 of 2 (**fixed**: `allow_none=True`, found in review); `EnergyCalculator._energy_state_kwh`, which read a counter with no number as 0 kWh, so the next read booked the whole register into the day (**fixed**: None, each caller skips it; found in review); `ForecastReader._sum_power_w` and `_read_power_w`, gated on a bare `float()` (**fixed**: `power_state_to_watts`); `sensor.py` `_handle_ev_power_change`, the live EV power sum, which added "nan" and a kW sensor's raw number (**fixed**: `power_state_to_watts`); `devices/held_power.py` `held_power_from_states` (**fixed**: the same rule; "-inf" passed its check); `SensorReader.sensors_ready` (**fixed**). **Open:** about 50 other bare `float(state.state)` parses (car SOC, EV counters, forecast, tariff, load devices, config flow) take "nan" as a number (#1262).
**Closure:** one rule, `units.state_number`: a reading is a finite number, and everything else is dark exactly as "unavailable" is. A sensor stuck on text now also gets the "Sensor unavailable" Repair after the same wait, since SEM cannot use it.
**Guard:** `tests/test_1202_no_number_is_dark.py` — for every power input name and each no-number shape, `_read_sensor` leaves the same value, tallies and Repair clock as "unavailable"; a whole home (legacy config, and an Energy-Dashboard home with two inverters, a split grid pair, two batteries and two PV strings) read with each shape on each sensor gives the same `read_power()` and `to_dict()` as with "unavailable" (NaN never equals itself, so a NaN let through anywhere fails); the SOC average leaves a dark unit out; a meter counter with no number leaves the day and its baselines as "unavailable" does; the forecast reads. 211 of the first 253 cases fail on the old reader, and 12 of the 16 review cases on the code before the review.
**Sweep question:** where SEM asks "did this sensor give a reading?", is the test "it is a finite number", or a list of the words a failure might use?
**Left open:** with one battery's SOC dark, the fleet SOC is the average of the units read (the #638 coverage rule; only the night plan waits for every unit), so it reads high when the dark unit is the emptier one. Before, the dark unit counted as 0 % and it read low. A choice, not filed. The forecast kWh sums (`_sum_floats`, `_read_float`) still parse with a bare `float()` (#1262).
**Round 2 — 0 % read as dark (#1169):** the report itself (95 % and a dark unit gave 47.5 % after the three-read step check) was the SOC average fixed above. The same question had a second wrong answer the other way round. `_read_battery_soc_average` returned 0.0 when no unit gave a number, so its caller in `_read_from_energy_dashboard` wrote `or None`, and that also ate a real 0 %. Two empty packs, or one empty pack beside a dark one, published no SOC: SEM held an old level, or after a restart called the fleet never read. One battery at 0 % never had this. **Closure:** the average returns None when no unit gave a number and 0.0 only for 0 %; the caller takes it as it is. Found by the guard below in review: one battery took a level below 0 % as a reading, while the fleet average and each battery's own SOC left it out; `_accept_battery_soc`, the one door both SOC paths use, now reads it as no reading. **Guard:** `tests/test_1169_fleet_soc_dark_or_zero.py` — the report through `read_power` for five reads and each dark shape; 0 % fleets after a restart and after a drain; and a fleet whose units all read the same thing (0, 37.5, 100, -5 or each dark shape) gives the same SOC, dark flag and "ever read" flag as one battery reading it — on both one-battery paths, on the first read and read by read from a held 60 %. 18 of its 63 tests fail on the code before; 26 fail with #1202's `allow_none` taken back out too. **Sweep:** no other SOC value is tested by truth (`or None`, `if soc:`); the per-battery SOC reads already used `allow_none`. **Left open:** the step check needs a last level, so the first read after a restart is taken unchecked, a false 0 % too. One battery always had this; a fleet got it with this fix (#1284).
Refs #1202 #1197 #1196 #988 #818 #1262 #1169 #1284.

### 177. A "same decision?" check that leaves out a field the controls act on — the act changes and the plan says nothing changed — GUARDED
**Symptom:** a rebuild of the day plan that reached the same decision kept the old plan and its time (#775). With the intraday flag on it still copied in the new build's battery sale blocks, so a forecast swing could move or resize the sale with no new plan time and no log line. With the flag off the new sale was dropped without a word (#1184; 24.10.2026 had 6 rebuilds in one morning).
**Root shape:** `plan_decision_core` lists by hand what "the decision" is. The forecast sale (#778) was added to the plan later and never to that list; #1068 then put it with the forecast-only keys a kept plan takes from the new build. What a gate acts on and what the check compares were two lists that nothing kept in step. Kin of class 169 (a view that lists by hand what the data publishes).
**Where it lives:** `coordinator/coordinator.py` `plan_decision_core` and `TRAJECTORY_KEYS`; the readers are the three gates in `coordinator/energy_plan_actuation.py`. `forecast_sell_gate` (**fixed**: the sale blocks are compared, times to the minute, kWh to 0.1, and no longer copied into a kept plan; `coordinator/forecast_sell.py` `forecast_sell_blocks` **fixed** for a running sale, see Closure); `arbitrage_sell_gate` (**fixed**: each sale block's kWh, the rate it sells at, was not compared); `plan_gate` (checked: every field it acts on is compared; `slots` is read only for its span, and every build of one period ends it at the same night end).
**Closure:** every field a gate acts on is in the check, and none of them is copied into a kept plan. A moved sale now gives a new plan time, `replan_cause` "ask changed" and the INFO line "replanning". Found in review: a rebuild while the sale runs sizes the block from what is left, so its start lands at about "now" and often just after it; the gate closed and the sale stopped until the clock caught up. Such restamps are now more common, so `forecast_sell_blocks(selling=…)` keeps a running sale's block open from "now" (same kWh, the rate eases to end at the night start).
**Guard:** `tests/test_1184_sale_block_is_the_decision.py` — for each field each gate reads, a change that alters what SEM does (checked every 5 minutes over the period) must change the check's answer; a change below the check's step that still alters a rate leaves a kept plan acting exactly as the plan whose time it keeps; each `TRAJECTORY_KEYS` entry has a case that changes no act; AST: every key a gate reads (`.get` or `[...]`) has a case, and `plan_gate` reads `slots` only at [0] and [-1]; through the tick, a moved sale gives a new plan time and a few seconds' change keeps both the time and the old blocks, flag on and off; a running sale's rebuilt block stays open, and the plan passes the live sale flag to the builder (AST). 19 of its 35 tests fail on the old code; each part of the fix, put back alone, fails at least one.
**Sweep question:** when a check says "nothing changed", does it compare everything the next step acts on — and does a new field have to join both lists?
**Left open:** a sale start near a minute's edge can give a new plan time for a few seconds' change: a time that is new, never a change that is hidden. The arbitrage kWh is compared even when arbitrage selling is off, so a dynamic-tariff home can get a few more new plan times (its total kWh was already compared). Both are choices, not filed.
Refs #1184 #775 #1068 #778.
