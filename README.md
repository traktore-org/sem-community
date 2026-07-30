<p align="center">
  <img src="https://raw.githubusercontent.com/traktore-org/sem-community/main/icon@2x.png" alt="SEM Logo" width="200">
</p>

# Solar Energy Management (SEM)

[![GitHub Release][releases-shield]][releases]
[![Tests](https://github.com/traktore-org/sem-community/actions/workflows/tests.yml/badge.svg)](https://github.com/traktore-org/sem-community/actions/workflows/tests.yml)
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]
[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/traktore-org)

**Smart orchestration for solar, battery, EV & home loads in Home Assistant** — maximize self-consumption, automate EV charging, optimize tariffs, and manage peak loads automatically.

SEM monitors your solar production, battery, grid, EV charger, and household devices every 10 seconds and distributes surplus power by priority. No cloud, no subscription — everything runs locally inside Home Assistant.

![SEM Dashboard Overview](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_home_tab.png)

<p align="center">
  <img src="https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_system_diagram_animated.gif" alt="System Diagram Animation" width="400">
</p>

---

## Features

- **Smart EV charging** — dynamic 6-32A current control based on real-time solar surplus
- **Six charging modes** — Auto (forecast-aware), Solar+Battery, Self-Consumption, Min+PV, Maximum, Off
- **Auto mode** — automatically switches between self-consumption and fast charging based on solar forecast vs EV need
- **Battery-aware** — four-zone SOC strategy decides when battery helps the EV and when it charges first
- **Min/Max charge-target range** — a per-charger dual-handle slider (kWh or SOC %): **Min** is the guaranteed amount (night/grid tops up to it), **Max** is the solar ceiling (surplus charges up to it, then stops). E.g. *Min 50% / Max 80%* — always keep 50% from the grid, let solar add up to 80% for battery longevity. Max defaults to full (charge freely from sun)
- **Charge-by deadline** — set a per-charger "be ready by HH:MM" time and SEM scales the night current to reach Min by then (overriding the gentle ramp when time is short), and warns if the target can't physically be met in time. "Set as default" copies a charger's target + deadline to the global defaults
- **Tariff-optimized charging** — opt-in per charger: defer night charging to the cheapest contiguous price window (Min still guaranteed by the deadline) and pause daytime grid top-up during expensive hours — surfaced live as the next-cheap-window on the EV card
- **Night charging with battery protection** — charges EV from grid overnight without draining home battery
- **Battery export arbitrage** — on a dynamic/spot tariff, opt-in sell the home battery to the grid when the export price beats the cost of recharging later (round-trip + wear accounted for); never below your reserve SOC, brand-agnostic, shown live as a "Selling to grid" state. See [docs/BATTERY_EXPORT_ARBITRAGE.md](docs/BATTERY_EXPORT_ARBITRAGE.md)
- **Hot water solar boost** — SEM supplements your existing heating system with solar surplus (does not replace your boiler/heat pump), with mandatory Legionella prevention cycle (DVGW W 551, SIA 385/1, ÖNORM B 5019)
- **Multi-device surplus distribution** — EV, heat pump, hot water, appliances — each gets surplus by priority, with appliance dependency chains (e.g. heater only runs when pump is active)
- **Daily runtime goals for household loads (#620)** — give any switch a **Min / Max runtime** window (e.g. *pool pump ≥ 4 h, ≤ 8 h/day*) via a dual-handle slider, a daytime **mode** (Off / Peak-only / Solar only / **Solar + battery** assist), and a **"Finish overnight from"** picker — **Off / Battery / Grid** (cheap-tariff window) — for completing the runtime when the sun runs short. Plus an optional stop condition picked with an entity search (e.g. water-temp ≥ 28 °C, car SOC ≥ 80 %). No forced grid deadlines. The load is prioritised in the one device list and exposes a surplus-event interface for your own automations. See [`docs/LOAD_PRIORITY.md`](docs/LOAD_PRIORITY.md).
- **Peak load management** — automatic device shedding to stay under your grid limit
- **Solar forecast integration** — Solcast, Forecast.Solar or Open-Meteo Solar Forecast for smart charging decisions
- **Dynamic tariff support** — Tibber, Nordpool, aWATTar, Amber Electric, Octopus Energy price-responsive charging
- **200+ sensors and entities** — power, energy, flows, costs, performance, forecasts, and more
- **Per-PV-string visibility** — auto-discovered per-string power + daily-energy sensors and a chip strip on the system diagram + flow cards (when your inverter exposes per-string data). Works on Huawei, GoodWe, Growatt, Kostal, Sungrow, Fronius, SolarEdge, SolaX, with V·I synthesis fallback for inverters that expose voltage + current separately.
- **Built-in dashboard** — theme-aware styling (works on both dark and light HA themes), animated system diagram, Sankey, and native HA energy cards
- **PV performance analytics** — specific yield, forecast accuracy, degradation tracking
- **Smart recommendations** — forecast-aware tips ("Best window for appliances: 11:00-14:00", "Low solar tomorrow — charge EV tonight")
- **Consumption/solar predictor** — learns hourly patterns (weekday/weekend), predicts next-hour power and daily consumption
- **Push notifications** — battery full, daily summary, forecast alerts, EV charging events (with Android channels and action buttons)
- **Brand icons** — native HA 2026.3+ brand support (no submission to home-assistant/brands needed)
- **EV Intelligence** — detects BMS charge tapering, estimates SOC without car API, learns daily consumption per weekday, temperature-corrected predictions, smart night charge skip
- **Smart Night Charging** — automatically skips or reduces night charges when SOC is sufficient, with solar forecast credit, daily SOC decay, and 3-skip safety net
- **EV battery health** — tracks capacity degradation from partial charge sessions over months
- **Hardware compatibility test suite** — 150+ automated tests covering all supported hardware — every inverter + charger combination verified in CI

---

## Why SEM?

**One integration, your whole energy system.** Install SEM and you get EV charging, battery strategy, multi-device surplus distribution, tariff optimization, peak-load management, cost analytics, and a full dashboard — all from a single HACS download.

- **Local-first** — everything runs inside Home Assistant. No cloud, no subscription, no account.
- **No extra moving parts** — no separate services, no Docker containers, no YAML config files, no AppDaemon.
- **Works out of the box** — SEM auto-detects your inverter, battery, grid, and charger from the Energy Dashboard, then exposes every knob on its own dashboard when you want to tune it.
- **Built for real hardware** — every supported inverter and charger combination is verified in CI, and the whole system is designed around locally-controlled devices.

If you can see it in your Home Assistant Energy Dashboard, SEM can orchestrate it.

---

## Installation

> **New to Home Assistant integrations?** See the [Step-by-Step Setup Guide](docs/SETUP_GUIDE.md) for a beginner-friendly walkthrough with checklist and FAQ.

### Via HACS (Recommended)

SEM is in the default HACS store — no custom repository needed.

[![Open your Home Assistant instance and open the SEM repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=traktore-org&repository=sem-community&category=integration)

1. Open **HACS** and search for **Solar Energy Management**
2. Click **Download**
3. **Restart Home Assistant**
4. Go to **Settings → Devices & Services → + Add Integration** and add **Solar Energy Management**

(Or click the button above to jump straight to it in HACS.)

### Beta Releases

Want to help test new features before they go stable? Enable beta updates in HACS:

1. Open **HACS** > **Integrations** > find **Solar Energy Management**
2. Click the three-dot menu > **Redownload** > enable **Show beta versions**
3. Select the latest beta and install

Beta releases are tested on real hardware before publishing but may contain rough edges. Your feedback helps us ship stable releases faster — report issues on [GitHub](https://github.com/traktore-org/sem-community/issues).

### Manual Installation

1. Download the [latest release](https://github.com/traktore-org/sem-community/releases)
2. Copy the `custom_components/solar_energy_management/` folder to your Home Assistant `config/custom_components/` directory
3. **Restart Home Assistant**

---

## Prerequisites

Before setting up SEM, make sure you have:

- **Home Assistant 2024.1.0** or newer
- **Energy Dashboard configured** — SEM reads your solar and grid sensors from the HA Energy Dashboard (Settings > Energy). You need at least:
  - A solar production sensor (W)
  - A grid consumption sensor (W)
- **Battery capacity** is auto-detected from your inverter (v1.2.1+)
- **Optional but recommended:**
  - Battery SOC (%) and power (W) sensors
  - An EV charger controllable via HA (KEBA, Wallbox, go-eCharger, Easee, Zaptec, ChargePoint, Heidelberg, etc.)
  - [Solcast PV Solar](https://github.com/oziee/ha-solcast-solar), [Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/) or [Open-Meteo Solar Forecast](https://github.com/rany2/ha-open-meteo-solar-forecast) for solar forecasts
  - Tibber, Nordpool, or aWATTar integration for dynamic tariffs

---

## Setup

### Step 1: Add the Integration

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for **Solar Energy Management**
3. Follow the setup wizard

### Step 2: Energy Dashboard Verification

SEM auto-detects your solar, grid, and battery sensors from the HA Energy Dashboard. If they are not configured yet, the wizard will ask you to set up the Energy Dashboard first.

SEM also uses the Energy Dashboard's import/export energy counters to automatically detect your grid and battery power sensor sign conventions — no manual configuration needed. This works with all inverter brands regardless of whether they use positive-for-export or positive-for-import conventions.

### Step 3: EV Charger Configuration

Select the sensors for your EV charger:

| Setting | Description |
|---------|-------------|
| Connected sensor | Binary sensor showing if the EV is plugged in |
| Charging sensor | Binary sensor showing if charging is active |
| Charging power sensor | Power sensor (W) for current charging power |
| Charger service | Service to set charging current (e.g., `keba.set_current`) |
| Total energy sensor | Cumulative energy sensor (kWh) — optional |

SEM auto-detects chargers from the entity registry: **KEBA**, **Wallbox Pulsar**, **go-eCharger** (HTTP + MQTT), **Easee**, **Zaptec**, **ChargePoint**, **Heidelberg**, **OpenWB 2.x**, **OCPP-compatible**, **Ohme**, **Peblar**, **V2C Trydan**, **Alfen Eve**, **Blue Current**, **OpenEVSE**. Any other charger that exposes power/connected/charging sensors in HA can be configured manually.

### Step 4: Notifications (Optional)

- **Charger display messages** — show charging status on the charger's built-in display (KEBA, Easee, Wallbox, etc.)
- **Notifications** — push notifications via HA Companion App (`notify.mobile_app_*`), REST webhooks (`rest_command.*`), or any `notify.*` service (Matrix, Slack, Telegram, etc.)

### Step 5: Optimization Settings

Key settings you can adjust (all have sensible defaults):

| Setting | Default | Description |
|---------|---------|-------------|
| Update interval | 10s | How often SEM reads sensors and adjusts |
| Daily EV target | 10 kWh | How much energy to charge overnight |
| Battery priority SOC | 30% | Below this, all solar goes to battery first |
| Battery buffer SOC | 70% | Above this, battery can help charge the EV |
| Battery auto-start SOC | 90% | Above this, EV starts even without solar surplus |
| Min solar power | 500W | Minimum surplus before solar EV charging starts |
| Observer mode | Off | Read-only mode for test systems (no hardware control) |

For detailed explanations of all settings, see the [Setup Guide](docs/SETUP_GUIDE.md).

### Step 6: Load Management (Optional)

Enable peak load management if your utility bills based on peak demand:

| Setting | Default | Description |
|---------|---------|-------------|
| Target peak limit | 5 kW | SEM sheds loads above this threshold |
| Warning level | — | Early warning threshold |
| Emergency level | — | All non-critical loads shed |

![SEM Integration Page](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_integration_detail.png)

---

## User Controls

SEM is designed to be mostly automatic. The controls that matter (v1.6.3 — toggle-soup replaced by a single named selector, #277):

| Entity | Default | What it does |
|--------|---------|-------------|
| `switch.sem_observer_mode` | OFF | Read-only mode — SEM monitors but doesn't control hardware (global) |
| `select.sem_charger_<id>_charge_mode` | `Min + Solar` | **Per-charger.** One named selector carries the night-charging, smart-night, and tariff-window intent that used to live on three separate switches. Options: *Solar only* / *Solar + cheapest hours* / *Min + Solar* / *Always (max)* / *Off*. |

EV charge targets, currents, phases and consumption are all **per-charger** entities too (`number.sem_charger_<id>_…`, `select.sem_charger_<id>_…`) — the global EV settings were removed in #255 (per-charger is the source of truth; globals are read-only summaries). Everything else — solar charging, surplus distribution, battery protection, peak management — is fully automatic.

---

## Charging Modes (v1.6.3)

The per-charger `Charge mode` selector replaces the four-toggle soup with five named modes. Each mode composes with the existing Charge Target range (Min / Max) and the Charge by HH:MM deadline.

### Solar only

Pure surplus, never grid. Equivalent to the legacy `self_consumption` + `night_charging=OFF`. Pick this if you only ever want to charge from sun.

### Solar + cheapest hours

Surplus by day, grid only in the cheapest contiguous tariff window at night (Min still guaranteed by the deadline). Hidden if no dynamic tariff is configured. Equivalent to `auto` + `tariff_optimized=ON`.

### Min + Solar (default)

Guarantees Min by deadline, solar adds up to Max. **Zone-adaptive during the day** — the Min guarantee comes from NIGHT charging top-up, not forced grid pull at noon. During the day the strategy machine still consults the SOC zone (battery priority when low, surplus when high, battery-assist in Zone 4). Most users want this.

### Always (max)

Charge at maximum regardless of source. Strict "Min from grid at all times" behaviour — equivalent to the legacy `minpv` mode.

### Off

No charging. SEM monitors but issues no commands to the charger.

Battery discharge protection prevents the home battery from powering the EV overnight regardless of mode.

### Battery-Assisted Charging

When the battery SOC is above the buffer threshold (default 70%), SEM supplements solar with battery power to maintain EV charging during cloudy moments. This is automatic — no switch needed.

---

## Dashboard

SEM includes a built-in dashboard with 8 views and a unified glassmorphism dark theme:

| View | Description |
|------|-------------|
| **Home** | Illustrated system diagram with SVG component drawings, spark flow animations, sun arc, solar summary, 7-day chart, weather, smart recommendations |
| **Energy** | Sankey diagram, self-consumption/autarky gauges, donut chart, 24h power, CO2 avoided, trees saved |
| **Battery** | SOC radial gauge, 24h charge/discharge chart, zone configuration |
| **EV** | Charging status, session stats, solar share gauge, lifetime totals, EV Intelligence (taper trend, virtual SOC, charge skip reasoning, battery health) |
| **Control** | Live surplus allocation, load-priority drag-and-drop, per-device control modes, today's schedule |
| **Configuration** | All post-setup configuration in one place — staged **Apply/Revert per section** (nothing saves on an accidental tap), a ⓘ on every setting with its explanation, **factory default and one-tap ↺ reset**, an **Explain settings** toggle that opens all help at once, and a 📖 link on each section header straight to the matching [docs](docs/SETUP_GUIDE.md) chapter. Rarely need HA's native config flow |
| **Costs** | Today/month/year KPIs, period selector, cost & savings charts, demand charge, tariff rates |
| **System** | Health diagnostics, sensor status, charging state, peak management |

| | |
|---|---|
| ![Energy](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_energy_tab.png) | ![Costs](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_costs_tab.png) |
| ![Battery](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_battery_tab.png) | ![EV](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_ev_tab.png) |
| ![Control](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_control_tab.png) | ![System](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_system_tab.png) |
| ![Configuration](https://raw.githubusercontent.com/traktore-org/sem-community/main/docs/images/sem_config_tab.png) | |

### Dashboard Features
- **Glassmorphism styling** — frosted glass cards with dot grid backgrounds, radial gradients, hover effects
- **Illustrated system diagram** — sem-system-diagram-card with detailed SVG illustrations (solar panels, house, battery, grid pole, EV charger), K-Flow-inspired spark flow animations, time-based sun arc with golden sine wave particles, clickable nodes, individual device display on desktop, responsive layouts. Optional K-Flow card via `diagram_style: "kflow"` config
- **Animated energy flow** — sem-flow-card with real-time power flows, daily energy totals, autarky gauge, config editor, tap/hold/double-tap actions
- **Custom SEM cards** — flow card, solar summary (glow ring), weather (clock + forecast), chart card (Chart.js), period selector
- **Drag-and-drop load priority** — reorder device shedding priorities visually
- **Environmental impact** — CO2 avoided and trees-equivalent with growing icon (sprout/tree/pine/forest)
- **Yearly KPIs** — year-to-date costs, savings, revenue on the Costs tab (auto-seeded from HA recorder on mid-year install)

For dashboard setup instructions, see the [Dashboard Guide](docs/DASHBOARD_GUIDE.md).

---

## Sensors

SEM creates 70+ sensors organized by category:

| Category | Examples |
|----------|---------|
| **Power** | Solar, grid, battery, EV, home consumption (W) |
| **Energy** | Daily/monthly totals for all sources (kWh) |
| **Flows** | Solar-to-home, solar-to-EV, grid-to-EV, battery-to-home (W and kWh) |
| **Costs** | Daily/monthly import costs, export revenue, savings |
| **Performance** | Self-consumption rate, autarky rate, solar efficiency (%) |
| **Charging** | State, strategy, available power, calculated current |
| **Surplus** | Total, distributable, allocated, active devices |
| **Forecast** | Today/tomorrow kWh, remaining today, peak time, next hour, surplus window |
| **Tariff** | Current import/export rate, price level, next cheap window |
| **PV Analytics** | Specific yield, forecast accuracy, degradation trend |
| **Smart Tips** | Optimization score, forecast-aware recommendations, best surplus window |
| **Load Mgmt** | Peak margin, 15-min average, devices shed, trend |
| **EV Intelligence** | Taper trend/ratio, virtual SOC, minutes to full, charge needed, skip reason, battery health, predicted consumption |
| **Notifications** | Battery full, high grid import, daily summary, forecast alerts |

---

## Supported Hardware

**Solar Inverters:** Huawei Solar, SolaX, DEYE/Sunsynk, Growatt, Sofar, Solis, Fronius, SMA, SolarEdge, Enphase, GoodWe, Tesla Powerwall, Kostal Plenticore, Sungrow, Victron, Sonnenbatterie, E3DC, GivEnergy, Fox ESS, Alpha ESS, Senec, RCT Power, KSTAR — or any inverter with HA sensors. SEM reads from the HA Energy Dashboard and auto-detects both grid and battery sign conventions.

**Batteries:** Any battery exposed through a supported inverter integration, plus standalone systems: Sessy (NL), Huawei LUNA2000, Tesla Powerwall, Sonnen, BYD, Pylontech, and others work automatically. Battery capacity is auto-detected from the inverter.

**Battery discharge control auto-detected for:** Huawei Solar, SolaX (solax-modbus), DEYE/Sunsynk (ha-solarman), Growatt, Sofar, Solis, GoodWe, SolarEdge (solaredge-modbus-multi), Enphase (IQ Battery), Tesla Powerwall, Victron, Kostal Plenticore, Sungrow

**EV Chargers (auto-detected):** KEBA P30, Wallbox Pulsar, go-eCharger (HTTP + MQTT), Easee, Zaptec, ChargePoint, Heidelberg Energy Control, OpenWB 2.x, OCPP-compatible (ABB Terra, Vestel, Grizzl-E, etc.), Ohme, Peblar Rocksolid, V2C Trydan, Alfen Eve, Blue Current, OpenEVSE

**EV Chargers (manual config):** Any charger exposing power/connected/charging sensors in HA.

> **Note:** KSTAR inverters are supported via the [ha-solarman](https://github.com/davidrapan/ha-solarman) integration with KSTAR YAML profiles, not via a dedicated KSTAR integration.

> **Note:** Fronius and SMA core integrations are read-only for battery control. Battery discharge protection requires the Modbus variant (e.g., `fronius_modbus`) or works without discharge limiting.

> **Note:** DSMR/P1 smart meters (NL/BE) are auto-detected for grid power. If your grid is metered by a separate smart meter (not by the inverter), SEM discovers the split import/export power sensors automatically.

**Hot Water:** Any hot water system exposed as a `water_heater`, `climate`, or `switch` entity in HA. Includes automatic Legionella prevention cycling per DVGW W 551 / SIA 385/1 / ÖNORM B 5019.

**Heat Pumps:** Any SG-Ready compatible heat pump controllable via HA

**Smart Meters:** Shelly EM/Pro, Discovergy, or any HA-compatible meter

---

## EV Intelligence

SEM learns your EV's charging behavior and makes smart decisions about when to charge. Implicit in the `Min + Solar` and `Solar + cheapest hours` Charge modes (v1.6.3); was the standalone `smart_night_charging` switch in v1.6.x.

**How it works:**

1. **Taper detection** — SEM detects the characteristic power staircase when your car's BMS reduces current near full charge (CC→CV transition). This is the most accurate SOC anchor (100% confirmed).

2. **Virtual SOC** — Tracks estimated battery level without a car API by monitoring energy in (charging) and out (predicted daily consumption). Calibrates from real `vehicle_soc_entity` when available.

3. **Daily consumption learning** — EWMA predictor learns per-weekday patterns: "Monday 8 kWh, Wednesday 0 kWh (WFH), Saturday 15 kWh". Adapts over 7 days.

4. **Temperature correction** — Adjusts consumption predictions for seasonal variation: winter (-5°C) = +72% consumption, summer (30°C) = +9%. Based on Recurrent Auto fleet data (30,000+ vehicles).

5. **Smart night charge skip** — If estimated SOC is sufficient for tomorrow's predicted consumption (with 30% safety margin and solar forecast credit), SEM skips the night charge. Max 3 consecutive skips as safety net.

6. **Session-based anchoring** — Works from day one without needing a full charge. First charge session bootstraps the SOC estimate. Taper detection and car API override with more accurate values when available.

**Sensors:** `ev_estimated_soc`, `ev_taper_trend`, `ev_nights_until_charge`, `ev_charge_needed`, `ev_predicted_daily_consumption`, `ev_battery_health`, and more.

---

## Automation Examples

### Notify when daily solar exceeds target

```yaml
automation:
  - alias: "SEM: Daily solar target reached"
    trigger:
      - platform: numeric_state
        entity_id: sensor.sem_daily_solar_energy
        above: 30  # kWh
    action:
      - service: notify.mobile_app
        data:
          title: "Solar Target Reached"
          message: >
            Daily solar production exceeded 30 kWh
            ({{ states('sensor.sem_daily_solar_energy') }} kWh)
```

### Force charge EV when electricity is cheap (v1.6.3)

```yaml
automation:
  - alias: "SEM: Cheap price EV charging"
    trigger:
      - platform: state
        entity_id: sensor.sem_tariff_price_level
        to: "cheap"
    condition:
      - condition: state
        entity_id: binary_sensor.sem_ev_connected
        state: "on"
    action:
      - service: select.select_option
        target:
          entity_id: select.sem_charger_ev_charger_charge_mode
        data:
          option: always_max
```

Switch the mode back to `min_plus_solar` when the price level leaves "cheap" to return to normal solar-prioritized behaviour.

### Alert when grid peak approaches limit

```yaml
automation:
  - alias: "SEM: Peak alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.sem_peak_margin
        below: 0.5  # kW remaining before target
    action:
      - service: notify.mobile_app
        data:
          title: "Peak Protection"
          message: >
            Grid peak approaching limit
            ({{ states('sensor.sem_peak_margin') }} kW margin)
```

---

## Use Cases

**Maximize solar self-consumption for EV charging** — Plug in during the day and SEM adjusts current to match surplus. Battery priority ensures the home battery charges first, then the EV gets the rest.

**Reduce peak load charges** — SEM monitors rolling 15-minute averages and sheds non-critical loads to stay under your target peak limit.

**Battery-assisted EV charging on cloudy days** — When forecast shows insufficient production but battery SOC is above the buffer, SEM supplements solar with battery discharge.

**Price-optimized night charging** — With dynamic tariff integration, SEM charges the EV during the cheapest overnight hours while protecting the home battery.

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Quick Start](docs/QUICK_START.md) | 5-minute setup guide |
| [Setup Guide](docs/SETUP_GUIDE.md) | Detailed configuration and tuning |
| [Dashboard Guide](docs/DASHBOARD_GUIDE.md) | Dashboard tabs, cards, and multi-language support |
| [Multi-Device Guide](docs/MULTI_DEVICE_GUIDE.md) | Multi-inverter, multi-charger, and brand-specific setup |
| [Architecture](docs/ARCHITECTURE.md) | Developer and contributor documentation |

---

## Removal

1. Go to **Settings** > **Devices & Services** > **Solar Energy Management**
2. Click the three-dot menu and select **Delete**
3. Restart Home Assistant
4. If installed via HACS: open HACS > Integrations, find SEM, click **Remove**
5. If installed manually: delete the `custom_components/solar_energy_management/` directory

All SEM entities are removed automatically. Your Energy Dashboard and hardware sensors are not affected.

---

## Recent Improvements

### v1.7.3 — Reliable EV charging + battery protection (23.06.2026)
- **EV charger state reconciler** (#392) — the per-cycle imperative actuator (which spammed `keba.disable` and dropped KEBA to 6 A) is replaced by a desired-vs-observed reconciler that issues the *minimum* commands to converge, then leaves the charger alone. Idempotent idle, heartbeat re-writes, failsafe armed once per session. Plus **enable-switch reconciliation + backoff** (#536) for switch-driven chargers (Wallbox etc.).
- **Solar Gate** (#537) — the home battery only assists the EV when there's real solar surplus ≥ a configurable gate (default **1200 W**), in *any* charging mode; set it to **0 W** to allow battery support everywhere including overnight. Closes the overnight battery-drain-into-the-car class of bug.
- **Multi-battery control + per-battery modes** (#523) — per-battery control entities and five modes (`auto`, `self-consumption`, `force-charge`, `force-discharge`, `off`), zero-config Huawei forcible discharge, corrected SG-Ready relay map.
- **Smarter EV control** — no draining the battery to hold a dead solar session, no charging from expensive grid after the cheap window ends (#461/#524); EV target by daily **kWh** *or* **vehicle SOC %**; per-charger independent surplus vs shed priority (#470).
- **Robust grid-sign autodetection + one-tap fix** (#461) — solar-anchored detector with `Fix grid sign` / `Reset` buttons and a `flip_grid_sign` service; locks survive restarts (#476).
- **Battery-sign autodetection + one-tap fix** (#588) — brand-seeded (deterministic for known inverters) + counter-correlation detector with a `Fix battery sign` button and a `flip_battery_sign` service, at parity with the grid-sign handling; per-battery on multi-battery installs, locks survive restarts.
- **Idempotent Huawei Modbus write** (#538), **dashboard time labels in the home timezone** (#539), and **full 15-locale dashboard translations** (parity-tested).
- Battery → grid export arbitrage shipped in beta but remains **deactivated** pending more review and soak (#533; re-evaluation planned for a later v1.7.x release).

### v1.7.2 — Hot Water boiler control (08.06.2026)
- **HotWaterController fully wired** (#454) — setting `hot_water_entity` now actually controls the boiler at runtime (the class existed from day one but was never instantiated). Live status block, Repair issues for unavailable temp sensor / boiler entity, fail-safe semantics (boiler is NOT activated on surplus when the temp sensor is broken), and orphan-repair sweep when the user reconfigures the boiler entity.

### v1.7.1 — Slim install + in-dashboard config (07.06.2026)
- **Slim install flow** (#442) — 3 steps → 2; users without an EV configured can now finish setup without quitting.
- **In-dashboard Configuration tab** (#442) — every OptionsFlow setting editable inline with `(?)` help, auto-save, and per-section 🩺 Diagnose buttons (#432) that copy focused JSON to the clipboard for sharing in discussions.
- **EV `ev_target_type` strictly honoured** (#451) — no silent fallback to `estimated_soc` when the SOC sensor isn't configured. Fixes the IDLE-stuck-at-120W stall reported on Huawei+KEBA in PROD.
- **Bulletproof EV solar-path stability** (#443) — hysteresis smoothing + delta-guard + heartbeat around `_set_current` on the daytime `min_plus_solar` Zone 3/4 path. Stops KEBA-side current oscillation on cloudy days.
- **HA Repairs integration** (#440) — persistent sensor / forecast / recorder issues surface in Settings → Repairs instead of growing the log; transient sub-5-min flaps stay silent.

### v1.7.0 — Audit telemetry + architecture cleanup (04.06.2026)
- **Per-PV-string visibility** (#312) — auto-discovered per-string power + daily-energy sensors plus a chip strip on the system diagram and flow cards. Works on Huawei, GoodWe, Growatt, Kostal, Sungrow, Fronius, SolarEdge, SolaX, with V·I synthesis fallback for inverters that expose voltage + current separately.
- **Audit telemetry across 10 modules** — decision-path enums published as sensor attributes (forecast_tracker, hot_water_controller, heat_pump_controller, pv_performance, time_manager, consumption_predictor, appliance_scheduler, load_management, forecast_reader) so you can self-diagnose without us reading a debug log.
- **FleetCycleState refactor** — single source of truth for fleet-level coordinator inputs; eliminates the class of fleet-vs-per-charger read bugs that produced four hotfixes between v1.6.0 and v1.6.6.
- **9 Architecture Decision Records** committed under `docs/adr/` (PerChargerContext, EVBudget, sign-convention boundary, home_consumption clamp, per-brand pipeline test, FleetCycleState, real-hass test framework, FleetEvPower newtype, multi-charger priority cascade).
- **v7 → v8 config schema migration** (#359) — auto-flips legacy `tariff_classification_mode=static` to `percentile` for dynamic-tariff users on first restart.

### v1.6.x — Multi-charger fleet, EV budget unification, named charge modes
- **v1.6.3 — Five named charge modes** (#277) replace the four-toggle soup: *Solar only* / *Solar + cheapest hours* / *Min + Solar* / *Always (max)* / *Off*. Each mode composes with the per-charger Min/Max range and the Charge-by deadline.
- **v1.6.0 — Canonical EV budget** across publish path, state machine, actuator, and multi-charger distribution. `sensor.sem_available_power` and `sensor.sem_calculated_current` now publish the same value the state machine and actuator read.
- **v1.6.4 – v1.6.17 — Multi-charger correctness sweep** — `PerChargerContext`, `FleetCycleState` foundation, AST lint pinning fleet-vs-per-charger invariants in CI.

### v1.5.15 — Cold-start readings fix
- **Readings start automatically after an HA restart** (#274) — SEM derives its real-time power sensors from the source integration's device. On a cold start it could run that derivation before the source integration (e.g. solax-modbus) had registered its entities, leaving every reading at 0 until you manually reloaded the integration. SEM now re-derives the power sensors each update cycle until they resolve, so the readings come up on their own within a cycle or two of the source loading — no reload needed. Bounded and a complete no-op for setups that already resolve normally.

### v1.5.14 — Multi-device cleanup, EV range targets & night-charge peak safety
- **Night charging respects the peak limit** (#268) — night-charge current is now sized from the house load alone, so grid import stays ≤ your configured peak limit regardless of battery behaviour. Previously battery discharge could inflate the EV current and push grid import well past the limit.
- **Per-charger is canonical** (#255) — duplicate global EV settings removed; per-charger entities (night charging, mode, phases, target, current) are the source of truth and globals become read-only summaries. Idempotent v3→v4 config migration.
- **EV Min/Max range targets** (#245) — set a guaranteed Min (grid/night) and a solar-only Max ceiling, in kWh or SoC % (SoC option appears when a vehicle SOC sensor is configured), with live driving-range display.
- **Night-charging opt-in** (#256) — night charging is per-charger opt-in; no charger charges overnight unless you enable it.
- **Surfaced silent failures** (#259) — dashboard generation, device mapping, and load-management errors now raise clear, translated messages instead of failing silently; a repair issue flags an unconfigured EV charger.
- **Per-charger daily energy** (#267) — per-charger daily kWh now persists across restarts and matches the global total.
- **SolaX derivation fix** (#250) — improved sensor derivation for the SolaX Modbus integration.
- **Translations completed** — exception/repair messages and the EV range-target help are now translated across all 15 languages.

### v1.5.7 — Illustrated System Diagram
- **System diagram rewrite** — detailed inline SVG illustrations replace abstract outlines; left-to-right desktop layout, vertical mobile layout
- **Clickable diagram nodes** — tap any component to open HA more-info statistics dialog
- **Individual device display** — top 3 devices by power consumption shown on desktop with arced connections to house
- **SEM color scheme on flows** — pink battery charge, teal discharge, purple grid export, blue import
- **Time-based sun position** — sun moves along arc from sunrise to sunset, moon + stars at night
- **K-Flow option** — `diagram_style: "kflow"` config option to use K-Flow card instead
- **Self-consumption %** added to home tab header as 4th stat

### v1.5.6 — Dynamic Tariff & Load Management
- **Dynamic tariff cost fix** (#218) — incremental cost accumulation instead of total × rate
- **Load management UX** (#219) — translations, power formatting, HA entity icons for devices
- **Enhanced diagnostics** — system info, source sensors, sign convention in diagnostic dump

### Per-Charger EV Enhancements (#193)
- **Per-charger connected status** — each charger reads its own plug sensor independently (no more all-connected when one car is plugged in)
- **Per-charger vehicle SOC** — configure `vehicle_soc_entity` per charger for real car battery percentage
- **Per-charger night charging** — independent targets, switches, start/min amps per charger
- **Per-charger notifications** — nearly full, skip, charge recommended fire per-charger with charger name
- **Per-charger dashboard** — EV status card shows connected status, SOC gauge, metrics per charger
- **Surplus distribution** — priority-based power allocation across chargers

### Translation System Expansion
- **759 translation keys** across 15 languages (was 606)
- **Cross-layer translation** — Python sensor values with `{tomorrow}` placeholders translated at card level
- **Peak management translated** — status, recommendation, and zone names
- **Chart period labels translated** — "Last 24h", "This Week" etc.
- **Grid mode translated** — "combined"/"split" in system info card

### Bug Fixes
- **Tariff rates accept zero** — import/export rates can be set to 0.00 for free electricity or net metering
- **Switchable device count** — only counts devices that are currently ON (was counting all configured)
- **Peak time formatting** — Solcast ISO timestamp converted to HH:MM local time
- **Binary sensor prefix fix** — 4 sensors (solar_active, battery_charging, etc.) were permanently False
- **Strategy text readability** — increased font size in EV card
- **Contract tests** — entity-key contract tests prevent future key mismatches

---

## Previous Improvements (v1.4.0)

### Multi-EV Charger Control (#112)
- **N charger support** — configure and control multiple EV chargers with priority-based surplus distribution
- **Priority cascade** — highest-priority charger gets power first, remainder flows to next if above minimum threshold
- **Per-charger state** — independent stall detection, enable/disable delays, session tracking, taper detection
- **Night target split** — overnight charging target distributed equally across connected chargers
- **Config flow** — add/remove chargers via options flow, auto-discovery of all charger brands
- **Dashboard** — per-charger status table when >1 charger, "(N chargers)" subtitle on flow diagram
- **Backward compatible** — single-charger configs auto-migrate with zero user effort

### EV Intelligence Notifications (#106)
- **"EV nearly full"** — push notification when taper detection shows < 5 minutes to full
- **"Night charge skipped"** — notification when SOC is sufficient, showing estimated range
- **"Charge recommended"** — notification when SOC drops below 30% during night window
- All three use deduplication (fire once per event, reset automatically)

### Heat Pump SG-Ready (#112)
- **SG-Ready 4-state control** — BLOCKED (1:0), NORMAL (0:0), BOOST (0:1), FORCE_ON (1:1) via two relay entities. (This line originally documented a plain 2-bit count, 00/01/10/11, which is not the SG-Ready standard — corrected in #523 in the code and in #655 here.)
- **Surplus-driven** — BOOST mode activates on solar surplus, FORCE_ON on high surplus (configurable threshold)
- **Temperature boost** — optionally raises climate entity setpoint during surplus periods
- **Config flow** — new Heat Pump step in options flow (relay1, relay2, climate, power sensor, priority)

### Dynamic Currency (#119)
- **All costs now use HA-configured currency** — no more hardcoded CHF
- Dashboard JS cards, YAML templates, chart presets, and sensor definitions all read from `Settings > General > Currency`

### Tariff Mode Selector (#120)
- **Three tariff modes** exposed in options flow: Static (fixed HT/NT), Dynamic (Tibber/Nordpool/aWATTar/Amber Electric/Octopus Energy), Calendar (time-based schedule)
- **Auto-detection** — SEM scans for Tibber/Nordpool/aWATTar/Amber Electric/Octopus Energy entities when dynamic mode is selected
- **Price-responsive surplus** — dynamic mode enables price-aware device activation during cheap/negative price windows

### GoodWe Support (#68)
- **Troubleshooting guide** for GoodWe + Easee setup (Energy Dashboard configuration, sign convention auto-detection)
- **Setup guide** note for GoodWe inverters

### 15 Languages
- Added: Portuguese (pt), Polish (pl), Swedish (sv), Czech (cs), Danish (da), Finnish (fi), Hungarian (hu), Romanian (ro), Norwegian (no)
- Was 6 (de, en, es, fr, it, nl), now 15

### Previous (v1.3.0)
- EV Intelligence: taper detection, virtual SOC, consumption learning, smart night charge skip, battery health
- Multi-device read aggregation: sum inverters, batteries, grid tariffs from Energy Dashboard
- Smart Night Charging rename, 1,000+ tests

### Previous (v1.1.0)
- Dashboard Lumina redesign — glassmorphism theme, SVG glow icons, battery hero card, EV status card
- Auto card installation — JS files auto-installed to `/config/www/` on restart
- Device control modes — `off`, `peak_only`, `surplus` per device
- Tariff calendar — user-defined HT/NT time windows with Swiss provider presets
- Performance, stability, usability, accessibility, and code quality improvements (see v1.0.4 changelog)

---

## Support SEM

SEM is free and open-source. If it saves you money on your energy bill, consider buying the developer a coffee:

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor_on_GitHub-%E2%9D%A4-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/traktore-org)

Your support helps keep SEM maintained, tested on real hardware, and free for everyone.

---

## Contributing

Contributions are welcome! Please fork the repository, create a feature branch, and submit a pull request.

## License

MIT License — see [LICENSE](LICENSE) for details.

---

[releases-shield]: https://img.shields.io/github/release/traktore-org/sem-community.svg?style=for-the-badge
[releases]: https://github.com/traktore-org/sem-community/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/traktore-org/sem-community.svg?style=for-the-badge
[commits]: https://github.com/traktore-org/sem-community/commits/main
[license-shield]: https://img.shields.io/github/license/traktore-org/sem-community.svg?style=for-the-badge
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[hacs]: https://github.com/custom-components/hacs
