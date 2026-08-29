<p align="center">
  <img src="../brand/icon@2x.png" alt="SEM Logo" width="120">
</p>

# Solar Energy Management - Dashboard Guide

Complete guide for the SEM dashboard — an 8-tab glassmorphism interface with animated system diagram, real-time energy flows, cost tracking, and environmental impact.

![Dashboard Home](images/sem_home_tab.png)

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [Dashboard Tabs](#dashboard-tabs)
3. [Required HACS Cards](#required-hacs-cards)
4. [Bundled SEM Cards](#bundled-sem-cards)
5. [Visual Style](#visual-style)
6. [Multi-Language Support](#multi-language-support)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

The dashboard is generated automatically on first install. If you need to regenerate it:

1. Go to **Developer Tools** > **Services**
2. Search for `solar_energy_management.generate_dashboard`
3. Click **Call Service**
4. The dashboard appears in the sidebar — hard-refresh your browser (Ctrl+Shift+R)

---

## Dashboard Tabs

### Home

The main at-a-glance view with real-time power flows.

![Home Tab](images/sem_home_tab.png)

| Card | Description |
|------|-------------|
| **Status Chips** | Solar power, battery SOC, autarky rate, EV status, optimization score |
| **Today's Plan** | Forward-looking timeline of today's solar, tariff, night-window, and EV events — see [Today's Plan rows](#todays-plan-rows) for the row-by-row breakdown |
| **System Diagram** | Illustrated SVG with detailed component drawings (solar panels, house, battery, grid pole, EV charger), K-Flow-inspired spark flow animations, time-based sun arc, clickable nodes, individual device list (desktop) |
| **Solar Summary** | Production metrics with animated glow ring, yield, forecast, self-use, costs, savings |
| **7-Day Chart** | Bar chart showing daily solar, home, and grid import over the last week |
| **Smart Recommendation** | AI-powered energy tip based on forecast, pricing, and current conditions |
| **Peak Load + Energy Tip** | Current 15-min peak vs limit, actionable energy tip |
| **Quick Controls** | Observer mode toggle. (`Smart Night Charging` and `Night Charging` switches were removed in v1.6.3 — their intent now lives in the per-charger [Charge mode selector](#charging-mode-selector-v163) on the EV tab.) |
| **EV Status** | Conditional — shows charging state, current, power, session progress when EV is connected |
| **Weather** | Live clock, temperature, weather conditions, 5-day forecast with temperature bars |

#### Today's Plan rows

Today's Plan is the forward-looking timeline at the top of the Home tab. It collapses solar, tariff, night-window, EV-session, and home-battery events into one chronological list so you can see at a glance what SEM is planning between now and tomorrow morning. Rows appear conditionally based on what's active — an empty plan is normal during the day for a configuration without dynamic tariff or active EV session.

| Row | Meaning | When it appears |
|---|---|---|
| **Now** | Anchor row for the current moment. Everything below this is "from here." | Always |
| **Solar peak — X kWh expected today** | Forecast solar peak time + total kWh expected | When a solar forecast is available (Solcast or HA's Energy dashboard) |
| **Cheap hours open** / **Cheap hours end** | Boundaries of the cheapest contiguous price window | Dynamic tariff configured |
| **Expensive hours start** / **end** | Boundaries of the price-peak window | Dynamic tariff configured, peak window is in the future |
| **Night charging window opens** | Time SEM enters night mode (your `Night earliest start` or the dynamic dusk window). Until this opens, EV night charging stays gated off regardless of mode. | Always — even when no EV is connected, so you can see the window |
| **EV charging starts** with subtitle `gentle peak-managed ramp` *or* `tariff-optimized, waiting for cheap window` | Time SEM expects the EV to start pulling. Subtitle = how: gentle ramp within peak limit, or wait for cheap-tariff window before starting. | EV connected, mode allows night/grid charging |
| **Min reached (X kWh)** | Predicted ETA for hitting the Min target on the charger — derived from planned ramp rate, your Min current, peak headroom, and home-load forecast. If later than your `Charge by` deadline, SEM forces the rate up automatically and this row turns red. | EV session is planned or in progress |
| **EV reaches target at HH:MM** | Live ETA for hitting the Max target during an active session (v1.6.3, #298) | EV is actively charging |
| **Battery full at HH:MM** | Live ETA for the home battery reaching 100% SOC (v1.6.3, #298) | Home battery is charging at a meaningful rate (\|power\| > 200 W) |
| **Battery reaches floor at HH:MM** | Live ETA for the home battery reaching its floor SOC (v1.6.3, #298) | Home battery is discharging at a meaningful rate |
| **Charge-by deadline** | Your configured `Charge by` time. Hard end of the night plan — earlier than the window's natural end means SEM forces the ramp to guarantee Min by then (even if it briefly exceeds the peak limit). | EV has a deadline set |
| **Night charging window ends** | End of the night-mode window | Always (paired with `opens`) |

### Energy

Deep dive into energy production, consumption, and environmental impact.

![Energy Tab](images/sem_energy_tab.png)

| Card | Description |
|------|-------------|
| **Sankey Diagram** | Energy flow visualization from sources to destinations |
| **Self-Consumption + Autarky** | Gauge cards showing percentage rates |
| **Energy Distribution** | Donut chart breaking down today's energy by category |
| **24h Power Curves** | Detailed power graph with solar, home, grid, battery over 24 hours |
| **Solar Today vs Yesterday** | Side-by-side comparison chart |
| **Carbon Avoided** | Daily CO2 savings from self-consumed solar (128g/kWh Swiss grid) |
| **Trees Saved** | Yearly trees equivalent with growing icon (sprout > tree > pine > forest) |
| **Self-Consumption Trend** | 30-day line chart of self-consumption and autarky rates |
| **Solar Forecast** | Today + tomorrow forecast with percentage comparison |
| **30-Day Energy** | Monthly bar chart of daily solar and consumption |

### Battery

Battery state and configuration.

![Battery Tab](images/sem_battery_tab.png)

| Card | Description |
|------|-------------|
| **SOC Gauge** | Radial gauge showing current battery state of charge. Turns **gold with a "Selling to grid" status + live export price** when SEM is exporting the battery for arbitrage (see [Battery export arbitrage](BATTERY_EXPORT_ARBITRAGE.md) — off by default; the state only appears once you opt in) |
| **Power Status** | Current charge/discharge power and daily energy totals |
| **24h Battery Chart** | Charge/discharge power + SOC line over 24 hours |
| **SOC Zone Config** | Steppers for priority, buffer, auto-start, and assist-floor SOC levels, plus **Solar Gate** (`battery_assist_min_surplus`) and **Assist Max** — the solar surplus required before the battery helps charge the EV, and the cap on that assist |
| **Per-battery mode** | For multi-battery setups: a mode selector per battery (auto / self-consumption / force-charge / force-discharge / off) |

### EV

EV charging session tracking and statistics.

![EV Tab](images/sem_ev_tab.png)

| Card | Description |
|------|-------------|
| **Charging Status** | Current mode, power, session energy, solar share |
| **Session Gauges** | Daily energy vs target, solar share percentage |
| **Charging Power Chart** | 24h EV power curve |
| **Charging Settings** | Charge target range (Min ↔ Max), [Charge mode selector](#charging-mode-selector-v163), Charge by deadline picker, Set as default |
| **EV Intelligence** | Taper trend visualization, virtual SOC estimate, charge skip status & reasoning, battery health indicator |
| **Lifetime Statistics** | Total energy, cost, sessions, solar share over all time |

#### Charging mode selector (v1.6.3)

The per-charger `Charge mode` selector replaces the v1.6.x toggle-soup (`Overnight grid charging`, `Smart night charging`, `Cheapest hours`) with one named intent control. Five modes:

| Mode | Behaviour | Typical user |
|---|---|---|
| **Solar only** | Surplus only — never imports from grid | Solar maximalist |
| **Solar + cheapest hours** | Surplus by day, grid only in the cheapest contiguous tariff window at night (hidden if no dynamic tariff is configured) | Dynamic-tariff users |
| **Min + Solar** (default) | Guarantee Min by deadline (from night top-up), solar adds up to Max. Zone-adaptive during the day. | Daily commuter |
| **Always (max)** | Charge at max regardless of source | "Just charge the car" / strict legacy `minpv` |
| **Off** | No charging — SEM monitors but issues no commands | Disabled |

A help line under the selector explains what the currently-selected mode does. For the full decision matrix (mode × time-of-day × outcomes) and the v4 → v7 migration mapping, see **[EV_CHARGING_LOGIC.md](EV_CHARGING_LOGIC.md)**.

### Control

Live operations and device management. Since #492 this tab is a
**monitoring view** — every writable setting lives on the
[Configuration](#configuration) tab instead (both tabs read the same HA
entities, so changes made there are reflected here immediately). The
EV section moved to per-charger cards on the EV tab in v1.6.3.

![Control Tab](images/sem_control_tab.png)

| Card | Description |
|------|-------------|
| **Surplus Control** | Live surplus: available/distributable and allocated/free watts |
| **Battery Management** | SOC + status (subtitle), capacity |
| **Hot Water** | Legionella disinfection target + regulatory info (the solar-boost target is set on Configuration) |
| **Heat Pump** | Active mode and SG-Ready state (auto-hidden when no heat pump is configured) |
| **Tariff & Pricing** | Provider, price level, current import rate |
| **Peak & Load Management** | Live % of peak limit, peak margin, sheddable devices |
| **Load Priority** | Drag-and-drop device ordering with real-time power, controllable/critical toggles, per-device control mode (Off / Peak Only / Surplus), and a per-device **Configure** button (see below). EV chargers have no mode dropdown here — their charge target is set in the **Charge Target** block on the EV card |

A red observer-mode banner appears at the top whenever Observer Mode
(read-only monitoring) is enabled on the Configuration tab.

#### Configure a device's control (manual mapping)

When SEM can't auto-detect how to control a load (e.g. a Shelly Pro3EM meter whose relay lives on a separate device), use the **Configure** button on the Load Priority card to map it manually. The dialog pre-fills with the current mapping and supports all four control methods SEM can shed/restore:

| Control type | Use for | What you pick |
|---|---|---|
| **Switch** | on/off appliances, smart plugs | the `switch.*` entity |
| **Number entity** | chargers with a current/amperage number (Wallbox, go-eCharger, …) | the `number.*` / `input_number.*` entity (set to 0 to reduce) |
| **Input boolean** | automation-triggered loads | the `input_boolean.*` entity |
| **Service call** | service-driven chargers (KEBA, Easee) | the service (e.g. `keba.set_current`), parameter, and reduce/restore values |

Entity types use a searchable entity picker filtered to the right domain. **Reset to auto-detect** removes a manual mapping and reverts the device to auto-discovery (for an auto-discoverable device this re-populates the same entity; to stop SEM controlling a device entirely, set its control mode to **Off**).

### Configuration

![Configuration Tab](images/sem_config_tab.png)

The single home for **every changeable setting** (`sem-config-card`),
organized in collapsible sections: Setup overview, Sensor sources (power-source overrides for grid / solar / battery, #628), EV chargers, Battery zones, Tariff & pricing, Heat pump, Hot water, Battery scheduler, Load management, Solar forecast, PV strings (when 2+ strings are detected), Notifications, and Advanced
zones, Tariff & pricing, Heat pump, Hot water, Battery scheduler, Load
management, Solar forecast, Notifications, and Advanced (update
interval, deltas, min solar power, regulation offset, Observer Mode,
SEM status history).

##### SEM status history (Advanced)

SEM writes a lot of short-lived status rows — charging state, strategy,
diagnostics. Those carry **no long-term statistics**, so keeping them for
weeks only grows your database without giving you anything you can chart.

**"SEM status history"** sets how many days of that status history to keep
(0 = off, Home Assistant's own policy applies), and **"Clean up now"** applies
it immediately.

**Your energy history is never affected.** Home Assistant compiles *hourly
long-term statistics* for every entity that carries a `state_class` — every
energy and power sensor — and keeps them indefinitely, independently of the
raw rows. SEM's clean-up derives its list from "has no `state_class`", so a
sensor with statistics is excluded automatically, including ones added in
future versions. Nothing that appears in a chart or on the Energy Dashboard
can be removed by this setting.

If you want to shrink the database further, the bigger lever is Home
Assistant's own `purge_keep_days` in `configuration.yaml` — lowering it drops
fine-grained detail while long-term statistics survive untouched. That one is
yours to set; SEM will not touch your `configuration.yaml`.
Each section header has a **Diagnose** button that dumps that section's
live config + state via the `solar_energy_management.diagnose` action —
attach its output to bug reports. Settings written here apply
immediately; structural changes (e.g. tariff mode) reload the
integration automatically.

### Costs

Financial tracking with daily, monthly, and yearly KPIs.

![Costs Tab](images/sem_costs_tab.png)

| Card | Description |
|------|-------------|
| **Today / This Month** | Side-by-side cost, revenue, net cost, savings chips |
| **This Year** | Yearly costs, revenue, savings cards |
| **Period Selector** | Today, yesterday, this week, this month, this year buttons |
| **Cost Chart** | Import costs, export revenue, net cost over selected period |
| **Savings Chart** | Solar savings + battery savings over selected period |
| **EV Economics** | Cost per kWh, cost per 100km, solar share |
| **Demand Charge** | Monthly peak, power charge cost, demand rate |
| **Tariff Rates** | Current import/export rates, price level |

### System

Diagnostics and health monitoring.

![System Tab](images/sem_system_tab.png)

| Card | Description |
|------|-------------|
| **Sensor Status** | Availability of solar, grid, battery, EV sensors |
| **Charging State** | Current charging mode and strategy |
| **Mode Status** | Night/solar/battery priority status |
| **Configuration** | All current settings at a glance |
| **Peak Management** | Current peak, monthly peak, trend |
| **Load Management** | Active devices, switchable device count (only counts currently ON devices), shedding status |
| **System Info** | Version, grid mode (translated), battery capacity, update interval, configured charger count, unavailable sensors |

---

## Required HACS Cards

**None** (#617 — zero-prerequisite dashboard). Everything on the dashboard is
a bundled `sem-*` card or a native HA type; the glass styling is baked into the
SEM cards themselves and the charts use a locally vendored Chart.js.

Optional, auto-detected by the dashboard generator:

| Card | HACS Repository | What it adds when installed |
|------|-----------------|------------------------------|
| `sankey-chart` | `MindFreeze/ha-sankey-chart` | Richer SEM-entity energy-flow sankey on the Energy tab; HA's native `energy-sankey` card is used otherwise |
| `k-flow-card` | — | Animated flow visualization replacing the built-in system diagram (opt-in via *Diagram style*) |

History: until v1.7.5 the docs listed 4 required cards (card-mod, mushroom,
apexcharts-card, sankey-chart). A 2026-07 audit found mushroom and apexcharts
had **zero remaining uses**, card-mod styled only five SEM-owned cards (now
self-styled), and sankey gained the native fallback — so the requirement list
went to zero. Installs that already have those cards are unaffected.

---

## Bundled SEM Cards

All 31 cards ship inside the integration — no HACS installation needed. Each
one registers itself with Home Assistant's card picker carrying a name, a
description, and a **help link that lands on its section below**. If you are
looking at a card in the dashboard editor and want to know what it does, the
help link is the shortest path.

Resource URLs include `?v={version}-{sha1}` for automatic cache busting.

Most cards are placed for you by the `generate_dashboard` service. Five are
built but **not placed** on the generated dashboard — they exist for people
building their own views, and are marked *manual* below.

### Card reference

Every card has its own section. The heading is the card's element tag, so
`custom:<tag>` is what you write in YAML.

#### sem-battery-card

**SEM Battery** · *Battery tab*

The battery hero card: an SOC arc ring with charge/discharge power, today's
throughput, and the current battery state in one glance.

#### sem-battery-zones-card

**SEM Battery Zones** · *Battery tab*

The three SOC thresholds that bound every battery decision — priority,
buffer, and auto-start. Editing them here is the same as editing them in the
options flow.

#### sem-charger-status-card

**SEM Charger Status** · *manual*

One tile per EV charger for multi-charger sites: state, current draw, and
session progress side by side. Add it manually if you run more than one
charger and want them on a single row.

#### sem-chart-card

**SEM Chart** · *Home, Energy, Battery, EV, Costs, System tabs*

The chart workhorse — a period-reactive Chart.js card with built-in presets
for costs, savings, energy, power, battery, and EV. It follows whichever
[`sem-period-selector-card`](#sem-period-selector-card) is on the view.

#### sem-config-card

**SEM Configuration** · *Configuration tab*

The in-dashboard configuration surface. For most users this replaces
Settings → Devices & Services → SEM → Configure entirely; changes are batched
and applied together.

#### sem-control-card

**SEM Control** · *Control tab*

The live control panel: peak management and margin, load-shedding status and
recommendation, heat-pump SG-Ready state, and the observer-mode switch.

#### sem-costs-card

**SEM Costs** · *Costs tab*

Daily, monthly, and yearly cost and savings with return on investment — the
financial summary.

The yearly figures are the sum of that year's recorded monthly buckets, priced
at the rates that were in force at the time, so the year and the months on this
tab always agree. Months from before SEM started tracking cost — anything
predating the install — are estimated from their recorded energy at an average
rate, since no price history exists for them.

#### sem-costs-detail-card

**SEM Costs Detail** · *Costs tab*

The breakdown behind the summary: EV charging economics, investment payback,
demand-charge exposure, and the current tariff rates.

EV charging economics shows the lifetime cost per kWh and the full three-way
source split — solar, battery, and grid shares. Battery-sourced energy is
priced by provenance: the portion of the battery that was charged from the
grid carries the price that was paid for it, while solar-charged energy stays
free. Cost per kWh and the shares therefore tell one consistent story.

#### sem-energy-impact-card

**SEM Energy Impact** · *Energy tab*

CO₂ avoided and its tree-equivalent, for today, this year, and lifetime.

#### sem-energy-plan-card

**SEM Energy Plan** · *Control tab*

The joint plan for the energy day — when each demand runs, where the battery
hands over, and, for anything left out, why not. This is the single place to
see what SEM intends to do tonight. See
[Energy planner](ENERGY_PLANNER.md) for how the plan is built.

#### sem-ev-progress-card

**SEM EV Progress** · *EV tab*

Today's EV charging progress against target, plus lifetime charging totals.

#### sem-ev-status-card

**SEM EV Status** · *EV tab*

The EV hero card: per-charger state, charge mode, target and deadline, with
the intelligence readouts (taper, estimated SOC) and settings inline. This is
the reference card for SEM's UI patterns — see [UI patterns](UI_PATTERNS.md).

#### sem-flow-card

**SEM Flow** · *Home tab, when `diagram_style: flow`*

A schematic animated energy-flow diagram with a visual config editor. Unlike
the other cards it is **dual-mode**: point it at SEM entities via a prefix, or
wire it to arbitrary Home Assistant entities and use it on a non-SEM
dashboard. Holds up to six individual devices, injected automatically from
your load list.

#### sem-gauge-card

**SEM Gauge** · *Energy tab*

A styled arc gauge for any percentage entity — used for autarky and
self-consumption, reusable for anything 0–100 %.

#### sem-grid-card

**SEM Grid** · *manual*

Grid import/export with peak management, load control, tariff, and surplus in
one consolidated card. Not on the generated dashboard — the System tab is
health and diagnostics only.

#### sem-home-status-card

**SEM Home Status** · *Home tab*

The at-a-glance status strip for the Home tab: what is producing, what is
consuming, and whether anything needs attention.

#### sem-load-priority-card

**SEM Load Priority** · *Control tab*

The one device list (#576): drag and drop to set the single priority order
shared by loads, chargers, and the battery, with live power per device and a
mode picker per row. See [Load priority](LOAD_PRIORITY.md).

#### sem-onboarding-banner

**SEM Onboarding Banner** · *Home tab*

A one-time welcome banner pointing existing users at the Configuration tab.
Dismisses itself permanently once clicked.

#### sem-period-selector-card

**SEM Period Selector** · *Costs tab*

The date-range picker. Every [`sem-chart-card`](#sem-chart-card) on the same
view follows it.

#### sem-price-card

**SEM Price** · *Home and Costs tabs*

Dynamic electricity price: the current price and level, today's range, the
next cheap window, and an hourly price strip. Hides itself when no dynamic
tariff is configured.

#### sem-require

**SEM Require Wrapper** · *Energy tab*

Not a card of its own — a wrapper. It renders the card inside it only when
that card's HACS dependency is actually installed, and shows a friendly
install notice otherwise. This is what makes the dashboard
zero-prerequisite: an optional card can be referenced without breaking the
view for people who do not have it.

#### sem-schedule-card

**SEM Schedule** · *manual*

A 24-hour timeline of tariff level, night window, surplus window, and EV
charging periods on one axis.

#### sem-solar-card

**SEM Solar** · *Home tab*

Solar production with live flows, forecast, and performance metrics, wrapped
in an animated glow ring.

#### sem-solar-kpi-card

**SEM Solar KPI** · *manual*

Today's solar production as a single prominent number. Superseded on the Home
tab by [`sem-solar-card`](#sem-solar-card), kept for manual dashboards that
want the bare KPI.

#### sem-solar-summary-card

**SEM Solar Summary** · *manual*

A compact solar overview — glow ring plus production metrics, without the
flows and forecast of the full solar card.

#### sem-system-card

**SEM System** · *System tab*

Integration health and diagnostics: version, detected chargers and control
method, grid mode, battery capacity, Energy Dashboard configuration, sensor
availability, and update interval. The first place to look when something
seems wrong.

#### sem-system-diagram-card

**SEM System Diagram** · *Home tab (default `diagram_style: sem`)*

The illustrated energy diagram — drawn solar panels, house, battery, grid
pole, and EV charger with animated spark flows along each path, a time-based
sun arc, and clickable nodes. Responsive down to phone width.

#### sem-tab-header

**SEM Tab Header** · *every tab*

The header at the top of each view: glow icon, title, and live stats for that
tab.

#### sem-title-card

**SEM Title Card** · *Control tab*

A section header with a runtime-translated title and a live Jinja subtitle —
used to break long views into labelled sections in the user's own language.

#### sem-today-plan-card

**SEM Today's Plan** · *Home tab*

The forward-looking view of the rest of today: tariff, expected solar, and EV
charging on one strip. The day-shaped companion to
[`sem-energy-plan-card`](#sem-energy-plan-card).

#### sem-weather-card

**SEM Weather** · *Home tab*

Live clock, current conditions, and colour-coded temperature forecast bars.

> **Note:** `sem-overnight-plan-card` is a back-compatibility alias for
> [`sem-energy-plan-card`](#sem-energy-plan-card), kept so dashboards
> generated before the rename keep rendering. It is deliberately absent from
> the card picker. Re-run `generate_dashboard` to move to the current name.

### System Diagram Style

SEM includes a built-in illustrated system diagram on the Home tab. Users who prefer the K-Flow card can switch via config options:

| Option | `diagram_style` value | Description |
|--------|----------------------|-------------|
| SEM Diagram (default) | `sem` | Illustrated SVG with solar panels, house, battery, grid pole, EV charger, animated flows, sun arc |
| K-Flow Card | `kflow` | Third-party K-Flow card (must be installed via HACS) with PV string details, cell temps, BMS data |

To switch: Settings → Integrations → SEM → Configure → set `diagram_style` to `kflow`. The dashboard will regenerate with the K-Flow card on the Home tab.

### Pointing the flow / diagram cards at non-SEM entities

Both `sem-flow-card` and `sem-system-diagram-card` (#455) accept an explicit `entities:` map instead of the default `entity_prefix: sensor.sem_`, so they can visualize any Home Assistant install:

```yaml
type: custom:sem-system-diagram-card
entities:
  solar:
    entity: sensor.inverter_pv_power        # W; reverse: true to flip sign
    daily_energy: sensor.daily_yield
    forecast_remaining: sensor.solcast_remaining_today   # diagram card only
  battery:
    entity: sensor.battery_power            # +charge / −discharge (SEM convention)
    # OR split sensors instead of a combined one:
    # charge: sensor.batt_charge_w
    # discharge: sensor.batt_discharge_w
    state_of_charge: sensor.battery_soc
    daily_charge_energy: sensor.batt_in_today     # diagram card only
    daily_discharge_energy: sensor.batt_out_today # diagram card only
  grid:
    consumption: sensor.grid_import_w       # split sensors…
    production: sensor.grid_export_w
    # …or a single signed sensor (+import / −export; reverse: true flips):
    # entity: sensor.grid_power
    daily_import_energy: sensor.grid_in_today
    daily_export_energy: sensor.grid_out_today
  ev:
    entity: sensor.wallbox_charging_power   # invert: true to flip sign
    daily_energy: sensor.ev_today
  home:
    entity: sensor.home_consumption         # optional — derived from the balance when omitted
    daily_energy: sensor.home_today
    autarky: sensor.autarky_rate
    self_consumption: sensor.self_consumption_rate       # diagram card only
```

Keys you omit simply render as 0 / empty — an install without an EV just leaves `ev:` out (no "sensor unavailable" warning in entities mode). `entity_prefix` remains the default and takes precedence if both are set.

### Cards Removed in v1.2.0+ (replaced by SEM cards)

These HACS cards are no longer required:

| Removed | Replaced by |
|---------|-------------|
| `power-flow-card-plus` | `sem-flow-card` (was `sem-system-diagram-card`) |
| `mini-graph-card` | `apexcharts-card` |
| `solar-card` | `sem-solar-summary-card` |
| `clock-weather-card` | `sem-weather-card` |
| `bar-card` | Native HA gauge card |
| `bubble-card` | Removed |
| `button-card` | Replaced by mushroom |

---

## Visual Style

The dashboard uses a unified glassmorphism dark theme with dot grid backgrounds, radial gradients, and glow effects:

```css
ha-card {
  background:
    radial-gradient(ellipse 70% 60% at 50% 40%, rgba(200,220,240,0.07) 0%, transparent 100%),
    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.06) 0.7px, transparent 0.7px);
  background-size: 100% 100%, 50px 50px;
  backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.06);
  font-family: 'Segoe UI','Roboto',sans-serif;
}
```

### Color Palette

| Entity | Color | Hex |
|--------|-------|-----|
| Solar | Orange | `#ff9800` |
| Grid Import | Steel Blue | `#488fc2` |
| Grid Export | Purple | `#8353d1` |
| Battery Charge | Pink | `#f06292` |
| Battery Discharge | Teal | `#4db6ac` |
| Home | Cyan | `#5BC8D8` |
| EV | Soft Green | `#8DC892` |

---

## Multi-Language Support

SEM supports 16 languages: Czech, Danish, German, English, Spanish, Finnish, French, Hungarian, Italian, Dutch, Norwegian, Polish, Portuguese, Romanian, Swedish, and Simplified Chinese (`zh` — also used when Home Assistant reports `zh-Hans`).

### How Translation Works — Two Language Settings

Home Assistant has two independent language settings. SEM uses both:

| Setting | Where to change | What it affects in the dashboard |
|---------|----------------|----------------------------------|
| **System language** | Settings → General → Language | Section headers, native/optional card titles and all static YAML-based text baked in at dashboard generation |
| **User profile language** | Your profile → Language | SEM custom cards: flow card, chart card, battery card, EV status, period selector, solar summary, weather card |

#### What this means in practice

- **Same language for everyone:** If the system language is German, all generation-time text (section headers, static labels) appears in German for every user.
- **Per-user SEM cards:** If one user sets their profile to English and another to French, the SEM flow card, chart card, and other SEM cards will show each user's chosen language.
- **Mixed-language scenario:** System = German, user profile = English → generation-time text shows German, SEM cards show English. This is by design, not a bug.

#### How to ensure consistent language

For all text to appear in the same language:

1. Set the **system language** to your desired language (Settings → General)
2. Set every **user's profile language** to the same language
3. Call `solar_energy_management.generate_dashboard` to regenerate the dashboard with the new system language
4. Hard-refresh the browser (Ctrl+Shift+R)

> **No HA restart needed.** As of v1.5.16, `generate_dashboard` pushes the new config through Home Assistant's own Lovelace store — the running dashboard reloads live as soon as the service call returns. Older muscle memory ("regenerate, then restart HA") no longer applies; a hard-refresh is enough.

### Which parts translate when?

| Action | What changes |
|--------|-------------|
| Change **system language** + regenerate dashboard | Section headers, static labels, tab names (reloads live, no HA restart) |
| Change **user profile language** | SEM custom cards update immediately (no regeneration needed) |
| Add new translations to `translations.json` | Must regenerate `sem-localize.js` + redeploy + regenerate dashboard (hard-refresh after — browser-cached `sem-localize.js`) |

---

## Troubleshooting

### Dashboard not appearing
1. Call `solar_energy_management.generate_dashboard` from Developer Tools > Services
2. Hard-refresh your browser (Ctrl+Shift+R)

### Cards showing "Custom element doesn't exist"
If the element name starts with `sem-`, SEM's card bundle didn't register — restart Home Assistant and hard-refresh. Any other name means the dashboard was generated while an *optional* card (sankey-chart, k-flow) was installed and it has since been removed — re-run *generate dashboard* to regenerate with the built-in fallbacks. No card install is required since v1.7.5 (#617).

### Blank Home tab
Should not occur since v1.7.5 (styling is built into the SEM cards; card-mod is no longer used). A blank tab is almost always a stale browser/service-worker cache after an update — hard-refresh (Ctrl+Shift+R) or clear the Companion app's frontend cache.

### Entity not found errors
The dashboard references SEM sensors that may not exist yet. Wait for the first coordinator cycle (10 seconds after restart) and refresh.

### Cards not updating after SEM update
SEM includes `?v={version}` cache busting on all card URLs. If cards still show old behavior, hard-refresh (Ctrl+Shift+R) to force reload.

### Some cards in wrong language / mixed languages
This is expected if your system language and user profile language differ. See [Multi-Language Support](#multi-language-support) above. To fix: set both to the same language and regenerate the dashboard.

### Changed system language but dashboard still in old language
You must regenerate the dashboard after changing the system language. Go to Developer Tools > Services > `solar_energy_management.generate_dashboard` and call the service, then hard-refresh. The regenerated dashboard takes effect immediately — no HA restart needed (v1.5.16+).
