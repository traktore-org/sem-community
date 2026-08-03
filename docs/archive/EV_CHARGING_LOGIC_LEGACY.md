# EV Charging Logic — LEGACY reference (pre-v1.6.3)

> **⚠️ ARCHIVED.** Everything below describes the pre-v1.6.3 toggle
> architecture — the entities named here (`switch.sem_charger_<id>_night_charging`,
> `..._smart_night_charging`, `..._tariff_optimized`, the 6-value
> `ev_charging_mode`) **no longer exist**; they were consolidated into the
> single `select.sem_charger_<id>_charge_mode` in v1.6.3 (#277).
>
> **Migrating an old automation?** Mapping: `Now` → `always_max` ·
> `PV`/`Self-consumption` → `solar_only` · `Auto`/`Min+PV` → `min_plus_solar`
> · tariff_optimized behaviour → `solar_plus_cheap` (or the *Cheapest hours*
> option) · `Off` → `off`. The night window, *Charge by* deadline and
> *At least X kWh* floor survive unchanged as per-charger detail settings.
>
> The current reference is [EV_CHARGING_LOGIC.md](../EV_CHARGING_LOGIC.md).

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

## 6. The scenario matrix

The complete decision space, in one table. Use this as the lookup when reasoning about a specific situation.

| # | Time | Charging Mode | Overnight | Cheapest | Other | What SEM does | Status sensor |
|---|---|---|---|---|---|---|---|
| 1 | Day | Auto | — | — | Surplus available | Charge from surplus; current ramps with PV | `solar_only` |
| 2 | Day | Auto | — | — | Sunny tomorrow forecast | Skip today — wait for tomorrow | `idle` |
| 3 | Day | Auto | — | — | Cloudy forecast, surplus low | Fall through to Min+PV (grid Min + PV bonus) | `min_pv` |
| 4 | Day | PV | — | — | Battery SoC ≥ buffer, solar < EV need | Battery assists at **full potential** — discharges into the car down to the buffer (#545) | `battery_assist` |
| 5 | Day | PV | — | — | Battery SoC < buffer | Idle (no grid, battery off-limits) | `idle` |
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

