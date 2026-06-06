# EV Charging Logic — How SEM decides

![New EV card (v1.6.3) — single Charge mode selector replaces the legacy night/smart-night/tariff switches](images/sem_ev_tab.png)

> **⚠️ Updated for v1.6.3 — the toggle-soup is gone.**
>
> v1.6.3 (#277) replaces the four-switch architecture this guide
> describes (``ev_charging_mode`` × ``night_charging`` ×
> ``smart_night_charging`` × ``tariff_optimized``) with one named
> per-charger ``Charge mode`` selector. The five modes are:
>
> | Mode | What it does | When to pick |
> |---|---|---|
> | **Solar only** | Pure surplus, never grid | Solar maximalist |
> | **Solar + cheapest hours** | Surplus by day, grid only in the cheapest tariff windows (hidden if no dynamic tariff configured) | Dynamic-tariff users |
> | **Min + Solar** (default) | Guarantee Min from grid/night top-up, solar adds up to Max. Zone-adaptive during the day — Min comes from night charging, not forced grid pull at noon. | Daily commuter needing a baseline |
> | **Always (max)** | Charge at maximum regardless of source | "Just charge the car" / strict legacy-``minpv`` behaviour |
> | **Off** | No charging | Disabled |
>
> Plus the existing **Charge Target range** (Min / Max), **Charge by HH:MM** deadline, and **Set as default** button as the per-mode detail. The old standalone switches (``night_charging``, ``smart_night_charging``, ``tariff_optimized``, ``ev_charging_mode``) are **removed** — automations that read them must read the new ``select.sem_charger_<id>_charge_mode`` instead.
>
> The behavioural-priority cascade below (Min ▷ Charge by ▷ Cheapest hours ▷ Smart night ▷ Mode ▷ Surplus) still applies — the **intent** moved into the mode selector. A full rewrite of this guide tracking the new model is tracked separately; the historical detail below remains accurate for the pre-v1.6.3 toggle layout but the entity names have changed.

---

## Legacy reference (pre-v1.6.3)

The sections below describe the toggle architecture that v1.6.3 consolidated. Kept for now so existing dashboards and automations migrating off the old switches have a reference; will be rewritten in a follow-up release to describe only the new mode selector.

SEM's EV controller takes input from up to **6 user controls** plus solar, battery, grid, and (optionally) tariff prices. This guide is the canonical reference for how those inputs interact.

> **TL;DR — the priority cascade:**
> **Min ▷ Charge by ▷ Cheapest hours ▷ Smart night ▷ Charging Mode ▷ Surplus opportunism**
>
> *Min always wins. Tariff and smart-skip only fire when they don't risk Min. "Up to Full" is opportunistic — never forces grid.*

---

## 1. The control surface

SEM splits EV charging into **two time domains** and **three layers**:

```
                  Daytime (solar hours)        Night window (e.g. 20:30 – 07:00)
                  ──────────────────────       ─────────────────────────────────
Layer A — Mode    Charging Mode (select)        (night logic always applies)
Layer B — Toggles Cheapest hours                Overnight grid charging
                                                Smart night charging
                                                Cheapest hours
Layer C — Floors  At least X kWh                At least X kWh
                  Up to Full                    Charge by HH:MM
                  Min / Max current             Min / Max current
```

Layer A and Layer B are **independent**: turn them on or off in any combination. Layer C is always in force.

---

## 2. Daytime — `Charging Mode` (mutually exclusive)

| Mode | Grid use | Solar use | When to pick |
|---|---|---|---|
| **Auto** (default) | Forecast-aware. Sunny tomorrow → no grid today; cloudy → falls back to Min+PV | Surplus first | Set & forget |
| **PV** | None (battery may assist if above floor SoC) | Surplus + battery-assist | Solar maximalist |
| **Self-consumption** | None ever | Pure surplus, battery untouched | Battery-cycle-averse |
| **Min+PV** | Up to Min current always, plus surplus on top | Min floor + solar bonus | Daily commuter needing a baseline |
| **Now** | Max immediately | Whatever's there | "Just charge the car" |
| **Off** | None | None | Disabled |

> **Now** and **Off** ignore all night and tariff logic — explicit user override wins.

---

## 3. Night-window controls (per charger)

| Card label | Internal entity | Default | Effect |
|---|---|---|---|
| **Overnight grid charging** | `switch.sem_charger_<id>_night_charging` | ON | Master switch for the night window. OFF = no grid charging overnight regardless of other settings. |
| **Smart night charging** | `switch.sem_charger_<id>_smart_night_charging` | OFF | Skips tonight if Solcast forecast covers Min tomorrow. SoC-aware so a low car never gets skipped. |
| **Cheapest hours (tariff)** | `switch.sem_charger_<id>_tariff_optimized` | OFF | Defer night charging to the cheapest *contiguous* price window. Min still guaranteed. |
| **Charge by HH:MM** | `time.sem_charger_<id>_target_time` | window end | Deadline for hitting Min. Earlier than window end = forcing floor that **overrides peak limit**. |
| **Set as default** | `button.sem_charger_<id>_set_default_target` | — | Copy this charger's Min/Max/deadline to global defaults for new chargers. |

---

## 4. Floors & ceilings (always in effect)

| Card label | Role |
|---|---|
| **At least X kWh** | **Hard floor** — guaranteed by *Charge by* time. Cannot be overridden by tariff or smart-skip. |
| **Up to Full** | **Opportunistic ceiling** — surplus and cheap-hour bonus only; never forces grid. |
| **Min current** (e.g. 6 A) | Lowest current the charger runs at (most cars won't accept charge below this). |
| **Max current / Initial night A** | Upper bound. Also the rate a forcing deadline can ramp to. |
| **Phases** (1 or 3) | Determines watts-per-amp (~230 W/A 1-φ, ~690 W/A 3-φ). |

---

## 5. Cross-cutting: battery-assist & tariff

### Battery-assist

The home battery can feed the EV when solar isn't enough.

| Setting | Effect |
|---|---|
| **Battery assist floor SoC** (e.g. 60 %) | Battery only assists EV above this SoC |
| **Battery assist max power** | Discharge cap when assisting |

Active in **Auto** and **PV** modes. Not in **Self-consumption** (by design) or **Now** (which takes everything).

### Cheapest hours (tariff)

The opt-in `tariff_optimized` switch changes behaviour in **three** places — not just at night:

| Time | Charging Mode | What tariff_optimized does |
|---|---|---|
| Night | any | Waits for cheapest contiguous window before charging (subject to Min reachability) |
| Daytime | Min+PV | **Drops the Min+PV grid guarantee on EXPENSIVE / VERY_EXPENSIVE hours.** Falls back to surplus-only; resumes on price drop or sufficient solar |
| Daytime | PV / Self-consumption / Auto | No effect (these modes don't use grid anyway) |
| Anytime | Now / Off | No effect (explicit override) |

`Cheap price threshold` (e.g. 0.15) and `Expensive price threshold` (e.g. 0.35) define the boundaries when no dynamic provider gives level labels.

---

## 6. The scenario matrix

The complete decision space, in one table. Use this as the lookup when reasoning about a specific situation.

| # | Time | Charging Mode | Overnight | Cheapest | Other | What SEM does | Status sensor |
|---|---|---|---|---|---|---|---|
| 1 | Day | Auto | — | — | Surplus available | Charge from surplus; current ramps with PV | `solar_only` |
| 2 | Day | Auto | — | — | Sunny tomorrow forecast | Skip today — wait for tomorrow | `idle` |
| 3 | Day | Auto | — | — | Cloudy forecast, surplus low | Fall through to Min+PV (grid Min + PV bonus) | `min_pv` |
| 4 | Day | PV | — | — | Battery SoC > floor, solar < EV need | Battery assists, tops up to EV minimum | `battery_assist` |
| 5 | Day | PV | — | — | Battery SoC < floor | Idle (no grid, battery off-limits) | `idle` |
| 6 | Day | Self-consumption | — | — | Surplus available | Surplus only; battery untouched | `solar_only` |
| 7 | Day | Min+PV | — | OFF | any price | Min current + PV bonus, always | `min_pv` |
| 8 | Day | Min+PV | — | ON | Price = normal/cheap | Min current + PV bonus | `min_pv` |
| 9 | Day | Min+PV | — | **ON** | **Price = expensive** | **Pause grid; surplus-only until price drops** | `solar_only` |
| 10 | Day | Now | — | — | any | Max current immediately (overrides everything) | `now` |
| 11 | Day | Off | — | — | any | Idle | `idle` |
| 12 | Night | any | **OFF** | any | any | Idle — overnight grid charging disabled | `night_disabled` |
| 13 | Night | any | ON | OFF | Smart night ON, sunny forecast, SoC OK | Skip tonight + notification "forecast covers Min" | `night_skipped` |
| 14 | Night | any | ON | OFF | Deadline = window end | Gentle ramp, peak-managed (legacy 1.5.x behaviour) | `night_charging` |
| 15 | Night | any | ON | OFF | **Deadline earlier than window end** | **Forcing**: scales current up to hit Min; can overshoot peak | `night_charging` (deadline_active) |
| 16 | Night | any | ON | **ON** | Cheap window covers Min at peak-rate | `Waiting for cheap hours` until window opens | `tariff_waiting_for_cheap` |
| 17 | Night | any | ON | **ON** | **Cheap window too short at peak-rate** | **Override tariff; charge now** ("not enough cheap hours") | `night_charging` |
| 18 | Night | any | ON | ON | No price data (provider down) | Override tariff; charge now | `night_charging` |
| 19 | Night | any | ON | any | Deadline physically impossible | Charge at max + push notification "can't reach Min in time" | `night_charging` (reachable=false) |
| 20 | Night | any | ON | any | Min already met | Idle — only top up to *Up to Full* from surplus if it arrives | `night_target` |

---

## 7. The night-charge planner step-by-step

Every 10 s during the night window, for each charger:

```
1. Min already reached?  → idle (only top up to "Up to Full" from surplus).

2. Compute deadline_amps = ceil( remaining_kWh / hours_left / watts_per_amp )
                          clamped to [Min current, Max current].

3. Compute effective_rate = Max current            if forcing deadline (deadline earlier than window end)
                            peak_managed_amps      otherwise   ← peak-aware (#274/C1)
   where peak_managed_amps = (peak_limit − avg_overnight_home_W) / watts_per_amp.

4. Reachable? = (remaining_kWh / effective_rate) ≤ hours_left.

5. If Cheapest hours ON:
     a. Now is cheap?            → charge.
     b. Not reachable anyway?    → charge (don't add tariff penalty on top of an already-failing deadline).
     c. Sum cheap hours BEFORE deadline × effective_rate ≥ remaining_kWh?
           yes → WAIT (state = tariff_waiting_for_cheap)
           no  → charge now ("not enough cheap hours at peak-limited rate")

6. Apply current = max(deadline_amps, gentle_ramp_amps).
   If shared peak budget exceeded (multi-charger), throttle proportionally (#274/H1).
```

---

## 8. Worked examples

### Example A — Single charger, default everything

- 8.5 kWh Min, deadline 07:00 (= window end), tariff OFF, smart-night OFF
- Plug in at 22:00, SoC at 30 %, remaining_to_min = 8.5 kWh
- Solar tomorrow's forecast irrelevant (smart-night off)
- Hours to deadline = 9
- Required rate = 8.5 / 9 = 0.94 kW = ~1.4 A at 3-φ
- Below the 6 A minimum → ramps to 6 A and finishes ~02:00, idles to 07:00.

### Example B — Tariff-optimized, cheap window comfortably covers Min

- Same setup but **Cheapest hours ON**
- Cheap window 01:00–05:00 (4 h)
- effective_rate = peak_managed_amps × 690 W/A ≈ 4.1 kW (assuming 6 A peak headroom)
- Deliverable in cheap window = 4 × 4.1 = 16.4 kWh > 8.5 kWh ✓
- SEM idles from 22:00, status = `tariff_waiting_for_cheap`, "Next: 01:00" shown on card
- At 01:00 it charges; finishes ~03:00; idles to 07:00.

### Example C — Tariff override (the case that worried you)

- 30 kWh Min (almost full charge), deadline 07:00, Cheapest hours ON
- Cheap window 01:00–04:00 (only 3 h)
- effective_rate = 4.1 kW
- Deliverable = 3 × 4.1 = 12.3 kWh < 30 kWh ✗
- SEM **does not wait**. Charges immediately from 22:00 onward; status = `night_charging`.
- Card reason: *"tariff: not enough cheap hours at the peak-limited rate — charging now to guarantee Min"*

### Example D — Forcing deadline

- 8.5 kWh Min, deadline = **03:00** (earlier than window end), tariff OFF
- Hours to deadline = 5
- Required rate = 8.5 / 5 = 1.7 kW ≈ 2.5 A → clamped to 6 A floor anyway
- BUT: deadline is "forcing" so SEM **bypasses the peak-managed rate**. If peak limit would normally throttle to 4.1 kW, the deadline-floor pushes through.
- Status: `night_charging`, `deadline_active = true`. If this would breach the peak limit, the user has explicitly accepted that trade-off by setting an early deadline.

### Example E — Daytime tariff pause

- Min+PV mode, Cheapest hours ON, midday cloudy day
- Min current would normally pull from grid to maintain 6 A floor
- Price hits `EXPENSIVE` level at 12:00
- SEM drops to surplus-only: if solar < 6 A worth, the charger pauses. Resumes when price drops back to normal or solar covers it.

---

## 9. When does the daily target counter reset?

Each charger has its own daily energy bucket (`daily_ev` for that charger). The bucket rolls over at the charger's own **`Charge by`** time (defaults to the night window end, e.g. 07:00).

**Why not at sunrise?** Sunrise can be *earlier* than the night-window end on short summer nights (sunrise 05:30, window end 07:00). A sunrise-based reset would wipe the bucket after Min was met (~03:00) but before the night window closes — making SEM see `remaining = daily_target` again and **re-fire night charging until 07:00**, double-billing the user. The deadline-based boundary closes that window: the bucket only rolls over once today's commitment is done. (#280)

**Multi-charger:** each charger's bucket resets at *its own* deadline. Car A at 07:00 and Car B at 08:00 reset independently — Car B isn't disturbed when Car A's day rolls over.

**Solar between sunrise and the deadline:** still counted into yesterday's bucket. Harmless, since Min was already hit.

---

## 10. What changes between releases?

- **1.5.x and earlier**: only `night_charging` + `smart_night_charging` existed. No deadline, no tariff-aware night. Daily bucket reset at sunrise (had the double-charge race condition above).
- **1.5.16 (unreleased)**:
  - **`Charge by`** time picker (#246) — per-charger deadline with forcing behaviour.
  - **`Cheapest hours (tariff)`** opt-in switch (#247) — night defer + daytime Min+PV pause.
  - Reachability uses **peak_managed_amps**, not nameplate max (#274/C1) — prevents tariff-wait → miss-Min.
  - Multi-charger night runs on a **shared peak budget** (#274/H1).
  - DST-correct hour subtraction (#274/M2).
  - **"Set as default"** button (#246) — propagate per-charger settings to global defaults.
  - **Daily bucket reset moved from sunrise to per-charger deadline** (#280) — kills the summer double-charge race.

---

## 11. Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| EV idle overnight despite plugged in | Overnight grid charging OFF, or Min already reached | EV card → `Overnight grid charging` toggle; check `sensor.sem_charger_*_session_energy` |
| Tariff "waiting" all night, never charges | Cheap window past midnight didn't open, OR price provider went stale | EV card → `Cheapest hours` hint shows "Next: HH:MM"; check `sensor.sem_tariff_current_import_rate` attributes |
| Charging at high current even when no solar | Forcing deadline set earlier than window end | EV card → `Charge by` time. Set it to window end (e.g. 07:00) to disable forcing. |
| "Can't reach target in time" notification | Min too high for the time left at max current | Lower Min, set an earlier deadline, raise Max current, or accept the notification (charges to whatever is possible at max) |
| Multi-charger: one stays idle | Shared peak budget allocated to higher-priority charger first | Surplus priority + `daily_ev_target` per charger; check coordinator logs for peak-budget allocation |
| Daytime Min+PV not pulling grid on cloudy day | Cheapest hours ON + price = EXPENSIVE | Either accept the pause or turn Cheapest hours OFF |
| Daily target counter shows yesterday's number into the morning | Working as intended — bucket only resets at *Charge by* time | `sensor.sem_charger_*_daily_ev`. Pre-#280 reset at sunrise; now at deadline to prevent double-charge race |
| EV plugged in, SEM says *"Charging active"*, but real draw is ~0 W with `commanded_current > 0` | **Fixed in #446 (v1.7.1-beta.16+).** Pre-#446 if you had `ev_target_type="soc"` saved without a vehicle SOC sensor, SEM substituted an estimated SOC into the kWh budget which could go to 0 and idle the charger. The v10 → v11 migration auto-resets these to `"kwh"` on first restart after upgrade. If you're seeing this on an OLDER version, manually set `ev_target_type` back to `"kwh"` in the Configuration tab, or upgrade. | Configuration tab → EV chargers → Target type (the SOC option is now disabled when no vehicle SOC sensor is configured) |

---

## 12. Related docs

- [README — Recent Improvements](../README.md#recent-improvements-v15x) — release notes for each version
- [USER_GUIDE — Configuration Options](../USER_GUIDE.md#configuration-options) — full settings reference
- [MULTI_DEVICE_GUIDE](MULTI_DEVICE_GUIDE.md) — multi-charger setup
- [DASHBOARD_GUIDE](DASHBOARD_GUIDE.md) — card-by-card UI reference
- [TROUBLESHOOTING](../TROUBLESHOOTING.md) — general issues
