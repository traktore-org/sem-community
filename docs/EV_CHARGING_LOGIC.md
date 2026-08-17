# EV Charging Logic — How SEM decides

![New EV card (v1.6.3) — single Charge mode selector replaces the legacy night/smart-night/tariff switches](images/sem_ev_tab.png)

> This is the **current** reference (rewritten 2026-07 for the v1.6.3+
> single-selector model, #618). If you're migrating automations off the
> pre-v1.6.3 toggles, see the
> [archived legacy reference](archive/EV_CHARGING_LOGIC_LEGACY.md) —
> it includes the old→new mode mapping.

> **Updated for v1.7.3** — two reliability changes on top of the model above:
> - **Charger state reconciler** (#392): SEM no longer re-issues a hardware command
>   every cycle. A desired-vs-observed reconciler (`coordinator/charger_reconciler.py`)
>   issues the minimum commands to converge and then leaves the charger alone — this
>   ends the KEBA "drops to 6 A" / `keba.disable` spam and adds enable-switch
>   reconciliation + backoff for switch-driven chargers (Wallbox, #536).
> - **Solar Gate** (#537): in **every** mode, the home battery only assists EV
>   charging when the *real* solar surplus is at least `battery_assist_min_surplus`
>   (default 1200 W; set 0 W to allow battery support everywhere, incl. overnight).
>   Below the gate the battery is reserved for the house and the car draws from
>   grid + solar. Distinct from *Min solar power* (the total-PV noise floor).

---

## The five charge modes

One per-charger selector — `select.sem_charger_<id>_charge_mode` — carries the
whole intent (the pre-v1.6.3 toggle collection is retired; see the
[archived legacy reference](archive/EV_CHARGING_LOGIC_LEGACY.md) if you're
migrating old automations):

| Mode | Grid use | What it does |
|---|---|---|
| **Solar only** | Never, unless *you* set a floor | Pure surplus charging; the home battery may assist above the Buffer SoC (Solar Gate permitting). Idles at night. |
| **Solar + cheapest hours** | Only in cheap tariff windows | Surplus by day; grid only when the dynamic price is cheap. Hidden without a price source. |
| **Min + Solar** *(default)* | Up to the Min guarantee | Guarantees *At least X kWh* by the *Charge by* deadline (night top-up when needed); solar adds up to Max on top. |
| **Always (max)** | Whatever it takes | Charge at maximum immediately. Explicit override — ignores solar, tariff and night logic. |
| **Off** | Never | No charging; SEM keeps the charger idle. |

The per-mode detail lives in the same card: **Charge target** (Min / Max kWh),
**Charge by** deadline, **Min / Max current**, and **Set as default**.

> **Solar only and the overnight floor (#679).** The mode is the *daytime* axis; the
> *At least X* floor is a separate guarantee that can apply in any mode. Under **Solar
> only** that guarantee is strictly opt-in: it counts only when you set it **on that
> charger**, in the unit that charger targets (kWh target → *At least X kWh*; % target →
> *Minimum SoC*). Leave it alone and Solar only idles at night, which is the documented
> promise. A global default value in Setup does **not** opt a Solar-only charger in — it
> can't, because setup fills that box in for you, so it carries no intent. The other
> night-capable modes do follow the global, since for them the overnight top-up is the
> mode's whole purpose.

> **Turning overnight charging off — set the floor to 0 (#680).** The *At least* floor is
> the single control for night charging: SEM tops up the gap between surplus and that
> target, so **a floor of 0 means no overnight charge** (in any mode). There is **no
> separate toggle** — the target you already set is the switch. This now works in both
> units: the kWh target always reached 0, and the **% target (*Minimum SoC*) now spans
> 0–100 %** on both the *At least* and *At most* handles (it was previously pinned at a
> 50 % minimum, so a %-targeted Solar-only charger couldn't be told "never grid
> overnight" and topped up to ≥ 50 % from the grid every night). To make a charger charge
> from **solar only, never grid/battery at night**, set **At least = 0 %** and **At most =
> 100 %** — daytime surplus charges up to the ceiling, and nothing tops up overnight. The
> runtime clamps the effective ceiling ≥ the floor, so a Max below the Min is harmless.

## The control surface (per charger)

| Entity | Role |
|---|---|
| `select.sem_charger_<id>_charge_mode` | The mode — the single intent input |
| `number.sem_charger_<id>_daily_ev_target` / `_max` | *At least X kWh* floor / *Up to* ceiling (kWh target); both **0–200** — floor 0 = no overnight charge |
| `number.sem_charger_<id>_target_soc` / `_max` | *Minimum SoC* floor / *Up to* ceiling (% target); both **0–100 %** (#680) — floor 0 = no overnight charge |
| *(picker)* `ev_start_stop_entity` | The `switch`/`button` SEM uses to open the contactor — set on the config card or the Add/Edit-charger dialog (#627). Without it, a `number.*`-only charger may be un-stoppable |
| `time.sem_charger_<id>_target_time` | *Charge by* deadline (earlier than window end = forcing) |
| `number.sem_charger_<id>_minimum_current` / `_maximum_current` | The current **range** SEM may offer — floor (most cars need ≥ 6 A) and ceiling (**6–80 A**, #746). Both on the Config tab's charger block; see below |
| `sensor.sem_charging_strategy` | The live reason string — every decision explains itself here |

## How a decision becomes amps

Each 10 s cycle, per charger: a **pure decision** (`decide()`) computes the
intent from this charger's own view → the **stability filter** applies
median smoothing, enable/disable delays, the start-kick ladder (auto-raises
a gentle 6 A offer until a fussy car latches) and the full-car backoff
(#610: after 3 declined ladders, 20 min quiet) → the **reconciler** issues
the minimum hardware commands to converge and then leaves the charger alone.
The strategy sensor narrates every step.

**Where the ceiling comes from.** Two things, and the lower one wins:

1. **Max Amps** (`number.sem_charger_<id>_maximum_current`, 6–80 A) — what you
   set. Use it to declare what the wallbox is actually rated for, or to throttle
   it below that when it shares a supply.
2. **The charger's own limit** (`max_current_a`, which for an entity-controlled
   box already folds in the control number's own maximum, #536). The adapter
   clamps every command to it, so the box's rating is the hard limit whatever
   you set above.

SEM decides against `min(hardware, Max Amps)` — a configured value can ask for
*less* than the hardware allows, never for more, because deciding above the
clamp is drift between what SEM plans and what it can command (#627).

Before **#746** there was no Max Amps at all. The ceiling came from
`max_charging_current`, a config key that no setup step and no entity ever
wrote — the dashboard's *add charger* button minted it as a literal `32`. Every
EVSE on every install was therefore capped at 32 A with nothing in the UI to
explain it, which is two thirds of a 48 A box. Upgrading installs keep the value
they had: the new slider seeds from the old key.

**#789** was the other half of the same defect. The planner's arithmetic runs
before any hardware is consulted and falls back to 32 A; that fallback used to
be written out by hand at thirteen places and five of them said 16 A, so the
night-charge planner sized the night at half the energy a 32 A charger delivers
— it started earlier and booked more cheap hours than it needed. The hardware
was never at risk; the plan was just wrong about it. Both halves now resolve
through one function (`devices.base.resolve_max_current`) and one constant.

---

## Battery assist & cheapest hours

### Battery-assist

The home battery can feed the EV when solar isn't enough.

Since **#545 ("max out till self-consumption")**, when the battery is in the
assist band (SoC ≥ the **Buffer SoC**) and there's real solar surplus past the
**Solar Gate**, SEM offers the **full** assist potential — it raises the offered
amps so the car draws more and the inverter discharges the battery **into the
car, down to the Buffer SoC** (the self-consumption floor). Below the Buffer the
battery is off-limits to the EV, and the assist tapers as SoC falls toward it, so
the battery is never drained past the floor. This replaces the older behaviour
(#501) that only topped the car up to the charger minimum and left a full battery
idle while the EV grid-charged.

| Setting | Effect |
|---|---|
| **Battery buffer SoC** (e.g. 70 %) | Floor of the assist band — the battery only assists the EV above this, and discharge into the car stops here (self-consumption reserve). |
| **Battery assist min surplus** (Solar Gate, #537) | Real solar surplus (solar − home) required before the battery assists, in every mode. |
| **Battery assist max power** | Discharge cap when assisting. |

> The separate *Battery assist floor SoC* knob was removed (folded into the
> Buffer SoC) — see CHANGELOG v1.7.3-beta.59.

Active in **Solar only** and **Min + Solar** (gated by the Solar Gate + Buffer SoC in both). Not in **Always (max)** — that mode takes everything from anywhere by definition. Pure amps — SEM issues no battery command; the inverter's own self-consumption does the discharge.

### Cheapest hours (tariff-aware charging)

The cheapest-hours behaviour (built into the **Solar + cheapest hours** mode, and available to *Min + Solar* via the per-charger *Cheapest hours* option) changes behaviour in **three** places — not just at night:

| Time | Charging Mode | What the cheapest-hours behaviour does |
|---|---|---|
| Night | tariff-aware modes | Waits for the [energy plan's](ENERGY_PLANNER.md) charge block — the cheapest hours that also fit under your peak limit and priority order (subject to Min reachability) |
| Daytime | Min + Solar | **Drops the Min grid guarantee on EXPENSIVE / VERY_EXPENSIVE hours.** Falls back to surplus-only; resumes on price drop or sufficient solar |
| Daytime | Solar only | No effect (never uses grid anyway) |
| Anytime | Always (max) / Off | No effect (explicit override) |

`Cheap price threshold` (e.g. 0.15) and `Expensive price threshold` (e.g. 0.35) define the boundaries when no dynamic provider gives level labels.

---

## The night-charge planner, step by step

Every 10 s during the night window, for each charger:

```
1. Min already reached?  → idle (only top up to "Up to Full" from surplus).

2. Compute deadline_amps = ceil( remaining_kWh / hours_left / watts_per_amp )
                          clamped to [Min current, Max current].

3. Compute effective_rate = Max current            if forcing deadline (deadline earlier than window end)
                            peak_managed_amps      otherwise   ← peak-aware (#274/C1)
   where peak_managed_amps = (peak_limit − avg_energy_plan_home_W) / watts_per_amp.

4. Reachable? = (remaining_kWh / effective_rate) ≤ hours_left.

5. Ask the energy plan (#638) whether this charger is COVERED tonight:
     a. Covered and inside its block?   → charge.
     b. Covered and outside its block?  → WAIT (state = tariff_waiting_for_cheap,
                                          card shows the block's start time).
     c. UNCOVERED (no fresh plan)?      → charge at deadline / top-up amps.
                                          Fail-open: the Min floor is a guarantee,
                                          so a missing plan never costs you the car.
                                          The card says "reactive — no plan yet".

6. Apply current = max(deadline_amps, gentle_ramp_amps).
   If shared peak budget exceeded (multi-charger), throttle proportionally (#274/H1).
```

> **Changed in v2.0 (#638).** Step 5 used to be the charger's *own*
> cheapest-hours arithmetic — sum the cheap hours before the deadline, wait if
> they cover the need. That private picker is deleted. The night window now
> comes from the joint plan, which weighs this charger against the battery, the
> deferrable loads and the comfort bands under one peak limit and one price
> curve — so a wait is no longer "these hours are cheap" but "this is your slot".
> Everything else in the list (the deadline, the Min floor, reachability, the
> peak-managed rate, the gentle ramp) is unchanged and still reactive.

---

## Worked examples

### Example A — Single charger, default everything

- Mode *Min + Solar*, 8.5 kWh Min, deadline 07:00 (= window end), cheapest-hours off, smart-night off
- Plug in at 22:00, SoC at 30 %, remaining_to_min = 8.5 kWh
- Solar tomorrow's forecast irrelevant (smart-night off)
- Hours to deadline = 9
- Required rate = 8.5 / 9 = 0.94 kW = ~1.4 A at 3-φ
- Below the 6 A minimum → ramps to 6 A and finishes ~02:00, idles to 07:00.

### Example B — Tariff-optimized, the plan finds room in the cheap hours

- Same setup but with **cheapest-hours behaviour on** (Solar + cheapest hours mode, or the Cheapest hours option)
- Cheapest hours of the night are 01:00–05:00; effective_rate ≈ 4.1 kW at 6 A peak headroom
- The plan packs 8.5 kWh into 01:00–03:00 — it fits under the peak limit alongside whatever else is scheduled
- SEM idles from 22:00, status = `tariff_waiting_for_cheap`, "Next: 01:00" shown on the card
- At 01:00 it charges; finishes ~03:00; idles to 07:00
- The Energy Plan card shows the block and its reason: *planned — cheapest hours*

### Example C — The night is too short to be picky

- 30 kWh Min (almost full charge), deadline 07:00, cheapest-hours on
- The cheapest hours alone can't deliver 30 kWh before 07:00 at the peak-limited rate
- The plan therefore places the block **from 22:00**, not in the cheap valley — it schedules the hours it actually needs, cheapest-first, until the ask is covered
- SEM **does not wait**. Charges from 22:00 onward; status = `night_charging`
- If a plan never arrives at all, the same thing happens for a different reason: uncovered EV demand falls back to deadline amps and the card says *reactive — no plan yet*. The Min floor is a guarantee either way.

### Example D — Forcing deadline

- 8.5 kWh Min, deadline = **03:00** (earlier than window end), cheapest-hours off
- Hours to deadline = 5
- Required rate = 8.5 / 5 = 1.7 kW ≈ 2.5 A → clamped to 6 A floor anyway
- BUT: deadline is "forcing" so SEM **bypasses the peak-managed rate**. If peak limit would normally throttle to 4.1 kW, the deadline-floor pushes through.
- Status: `night_charging`, `deadline_active = true`. If this would breach the peak limit, the user has explicitly accepted that trade-off by setting an early deadline.

### Example E — Daytime tariff pause

- *Min + Solar* mode with cheapest-hours on, midday cloudy day
- The Min guarantee would normally pull from grid to maintain the 6 A floor
- Price hits `EXPENSIVE` level at 12:00
- SEM drops to surplus-only: if solar < 6 A worth, the charger pauses. Resumes when price drops back to normal or solar covers it.

---

## When does the daily target counter reset?

Each charger has its own daily energy bucket (`daily_ev` for that charger). The bucket rolls over at the charger's own **`Charge by`** time (defaults to the night window end, e.g. 07:00).

**Why not at sunrise?** Sunrise can be *earlier* than the night-window end on short summer nights (sunrise 05:30, window end 07:00). A sunrise-based reset would wipe the bucket after Min was met (~03:00) but before the night window closes — making SEM see `remaining = daily_target` again and **re-fire night charging until 07:00**, double-billing the user. The deadline-based boundary closes that window: the bucket only rolls over once today's commitment is done. (#280)

**Multi-charger:** each charger's bucket resets at *its own* deadline. Car A at 07:00 and Car B at 08:00 reset independently — Car B isn't disturbed when Car A's day rolls over. The **fleet total** (`sensor.sem_daily_ev_energy`) uses the shared deadline while every charger agrees on one; the moment their *Charge by* times differ there is no fleet deadline to roll on, so the fleet total resets at **midnight** — the only boundary all chargers share (#724). Moving a *Charge by* time never re-keys the day already accumulating; the new boundary applies from the next rollover. Note the shape of a *later* move: the running day is extended once (it does **not** reset at the old time — a midday 07:00 → 23:00 move makes that one EV day up to ~40 h long), then normal rhythm resumes.

**Solar between sunrise and the deadline:** still counted into yesterday's bucket. Harmless, since Min was already hit.

---

## Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| EV idle overnight despite plugged in | *At least* floor is 0, or Min already reached | Raise the *At least* target above 0 — a floor of 0 means "never grid/battery-charge overnight" by design (#680). Check `sensor.sem_charger_*_session_energy` |
| Solar-only charger still grids/battery-charges at night | % target floor was ≥ 50 % (pre-beta.26 it couldn't be set lower) | Update to v1.7.5-beta.26+, then set *At least* = 0 % (and *At most* = your solar cap). #627/#680 |
| Tariff "waiting" all night, never charges | Cheap window past midnight didn't open, OR price provider went stale | EV card → `Cheapest hours` hint shows "Next: HH:MM"; check `sensor.sem_tariff_current_import_rate` attributes |
| Charging at high current even when no solar | Forcing deadline set earlier than window end | EV card → `Charge by` time. Set it to window end (e.g. 07:00) to disable forcing. |
| "Can't reach target in time" notification | Min too high for the time left at max current | Lower Min, set an earlier deadline, raise Max current, or accept the notification (charges to whatever is possible at max) |
| Multi-charger: one stays idle | Shared peak budget allocated to higher-priority charger first | Surplus priority + `daily_ev_target` per charger; check coordinator logs for peak-budget allocation |
| Daytime Min+PV not pulling grid on cloudy day | Cheapest hours ON + price = EXPENSIVE | Either accept the pause or turn Cheapest hours OFF |
| Daily target counter shows yesterday's number into the morning | Working as intended — bucket only resets at *Charge by* time | `sensor.sem_charger_*_daily_energy`. Pre-#280 reset at sunrise; now at deadline to prevent double-charge race. Note: the FLEET total (`sensor.sem_daily_ev_energy`) behaves this way only while all chargers share one deadline — with differing deadlines it resets at midnight (#724) |
| EV plugged in, SEM says *"Charging active"*, but real draw is ~0 W with `commanded_current > 0` | **Fixed in #446 (v1.7.1-beta.16+).** Pre-#446 if you had `ev_target_type="soc"` saved without a vehicle SOC sensor, SEM substituted an estimated SOC into the kWh budget which could go to 0 and idle the charger. The v10 → v11 migration auto-resets these to `"kwh"` on first restart after upgrade. If you're seeing this on an OLDER version, manually set `ev_target_type` back to `"kwh"` in the Configuration tab, or upgrade. | Configuration tab → EV chargers → Target type (the SOC option is now disabled when no vehicle SOC sensor is configured) |
| Heat pump section in dashboard says "No heat pump configured" even though `heat_pump_relay1_entity` / `heat_pump_relay2_entity` are filled | **v1.7.1-beta.17+ exposes the diagnostic surface.** Check `sensor.sem_heat_pump_registration_status` — its state + attributes tell you which of the six possible failure modes applies (`partial_sg_ready_only_relay1`, `entity_missing`, `unavailable`, etc.). When a configured relay entity stays `unavailable` for 5+ minutes a Repair issue files at **Settings → System → Repairs** naming the specific entity. For users wiring SG-Ready via Nibe Modbus rather than physical relays, see "Heat pump — two valid wiring paths" below. | Configuration tab → Heat pump section → status sensor; Settings → System → Repairs |
| Strategy sensor says *"full-car backoff — car declined N start ladders; next offer in X min"* | **Working as intended (#610).** The car is plugged in with surplus available, but its BMS declined several complete start-offer ladders (gentle 6 A start, auto-raised to ~10 A, held 90 s) without drawing — typically a full battery. Instead of re-offering every few minutes all afternoon, SEM waits ~20 min between offers. The backoff ends instantly when the car draws (e.g. after cabin preconditioning frees headroom), when you unplug/re-plug, or when you change the charge mode. | `sensor.sem_charging_strategy` reason text; nothing to configure |

---

## Heat pump — two valid wiring paths for SG-Ready

SEM doesn't bundle device drivers — it operates on HA entities that other integrations expose (see [ARCHITECTURE.md → "SEM is not an integration"](ARCHITECTURE.md#architectural-principle--sem-is-not-an-integration)). For heat pumps with SG-Ready inputs there are two equally valid wiring paths, and SEM treats both the same way: as two `switch` entities that flip between `on` and `off`.

### Path A — Physical relays wired to AUX inputs

For Nibe units without Modbus, or any heat pump whose only SG-Ready interface is a hardware-relay pair:

1. Wire two physical relays (e.g. Shelly 1 Mini × 2, an ESP relay board, or any HA-supported `switch`) to the heat pump's AUX1 / AUX2 inputs.
2. In HA: confirm both switches appear under Developer Tools → States and toggle correctly.
3. In SEM: open Configuration tab → Heat pump section → set `heat_pump_relay1_entity` and `heat_pump_relay2_entity` to those two switches.

SEM commands the SG-Ready four states by driving the two switches to the contact
pairs the standard defines, exactly as a hardware utility-signal box would — see
[the relay table in SETUP_GUIDE.md](SETUP_GUIDE.md#what-is-sg-ready). It is **not**
a plain 2-bit count: BLOCKED is `1:0`, NORMAL is `0:0`. If your contacts are wired
normally-closed, flip *Invert SG-Ready* rather than rewiring.

### Path B — Software SG-Ready via Modbus / vendor integration

For Nibe S-Series (firmware ≥ 4.7.5) and any heat pump that supports SG-Ready via a Modbus register or vendor cloud API, no hardware is required:

1. Install the relevant HA integration — HA's `nibe` integration, the generic `modbus` integration with manual register mapping, or the vendor's official integration.
2. Configure the integration to expose / write the SG-Ready register (e.g. Nibe holding register 3032 enables Modbus-driven SG-Ready; subsequent writes drive the state).
3. Create two HA `template switch` entities. Each writes one bit of the SG-Ready state to the appropriate register when toggled, and reads back the current bit for its state.
4. In SEM: same as Path A — point `heat_pump_relay1_entity` / `heat_pump_relay2_entity` at the template switches.

SEM never knows or cares that it's Modbus underneath. It sees two switches and toggles them. The HA integration owns the protocol.

### Why this design?

Some HEMS tools bundle vendor-specific Modbus templates that write directly to inverter/charger registers. SEM intentionally takes a different shape — it stays in HA's entity-and-services world so it doesn't have to ship a protocol library for every brand, doesn't have to track every firmware revision, and doesn't replace HA integrations the user already trusts. See [ARCHITECTURE.md](ARCHITECTURE.md#architectural-principle--sem-is-not-an-integration) for the full principle.

### How to tell which path you're on

* `sensor.sem_heat_pump_registration_status` shows the active mode: `registered_sg_ready` (relays only), `registered_climate_only` (no relays, climate-entity boost only), or `registered_sg_ready_and_climate` (both).
* Click Settings → SEM → ⋮ → Download Diagnostics → the `heat_pump` block in the JSON shows the resolved entity ids + their live states.

---

## The curtailment probe — harvesting solar an export limit hides

Some inverters cap their grid export — permanently (a regulatory limit) or
dynamically (dropping to **0 W when the electricity selling price is
negative**). With the limit active, the inverter reduces production to match
local consumption, so SEM's measured surplus honestly reads ~0 while the
array could deliver kilowatts more. Reading harder cannot fix this — raising
consumption is the only instrument that reveals the hidden power.

**Options → EV Settings → "Curtailment probe"** (default **off**) turns on
exactly that instrument:

1. **Suspicion** — the solar forecast says far more than the array delivers,
   export is pinned at ~0, and production ≈ consumption (the curtailment
   signature; a merely cloudy day fails the forecast term). Brands that
   publish their export limit sharpen this: SEM auto-detects the limit
   entity (Huawei active power control, GoodWe grid export limit, SolaX
   export control, Victron max feed-in, …) — "limit active" fast-tracks the
   probe, "no limit" suppresses it entirely. The **"Export-limit entity"**
   field overrides the autodetect for exotic setups.
2. **Probe** — SEM starts the EV at minimum amps. If production rises to
   follow within ~2 minutes, the curtailment was real; if not, the probe
   backs off and won't retry for 15 minutes. A failed probe costs about two
   minutes of minimum-amps draw — that is the price of asking, and why the
   feature is opt-in.
3. **Harvest** — the risen production makes the normal surplus loop
   self-sustaining. The probe keeps offering one ladder step of headroom so
   charging climbs toward the forecast — and every step must be followed by
   production within its window, or the climb stops where the array's real
   potential ends. No step is ever taken on faith.

A forecast integration (Solcast, Forecast.Solar or Open-Meteo) is required —
without a "power now" forecast there is nothing to suspect against.

## Related docs

- [README — Recent Improvements](../README.md#recent-improvements) — release notes for each version
- [USER_GUIDE — Configuration Options](USER_GUIDE.md#configuration-options) — full settings reference
- [MULTI_DEVICE_GUIDE](MULTI_DEVICE_GUIDE.md) — multi-charger setup
- [DASHBOARD_GUIDE](DASHBOARD_GUIDE.md) — card-by-card UI reference
- [TROUBLESHOOTING](TROUBLESHOOTING.md) — general issues
