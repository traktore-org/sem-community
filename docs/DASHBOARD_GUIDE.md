<p align="center">
  <img src="../brand/icon@2x.png" alt="SEM Logo" width="120">
</p>

# Solar Energy Management - Dashboard Guide

Complete guide for the SEM dashboard — a 7-tab glassmorphism interface with animated system diagram, real-time energy flows, cost tracking, and environmental impact.

![Dashboard Home](images/sem_dashboard_overview.png)

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [Dashboard Tabs](#dashboard-tabs)
3. [Required HACS Cards](#required-hacs-cards)
4. [Bundled SEM Cards](#bundled-sem-cards)
5. [Visual Style](#visual-style)
6. [Troubleshooting](#troubleshooting)

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

![Home Tab](images/sem_dashboard_overview.png)

| Card | Description |
|------|-------------|
| **Status Chips** | Solar power, battery SOC, autarky rate, EV status, optimization score |
| **System Diagram** | Animated SVG with hub-spoke layout, glow rings, flow dots, individual device nodes |
| **Solar Summary** | Production metrics with animated glow ring, yield, forecast, self-use, costs, savings |
| **7-Day Chart** | Bar chart showing daily solar, home, and grid import over the last week |
| **Smart Recommendation** | AI-powered energy tip based on forecast, pricing, and current conditions |
| **Peak Load + Energy Tip** | Current 15-min peak vs limit, actionable energy tip |
| **Quick Controls** | Forecast reduction and observer mode toggles |
| **EV Status** | Conditional — shows charging state, current, power, session progress when EV is connected |
| **Weather** | Live clock, temperature, weather conditions, 5-day forecast with temperature bars |

### Energy

Deep dive into energy production, consumption, and environmental impact.

![Energy Tab](images/sem_energy_flows.png)

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
| **SOC Gauge** | Radial gauge showing current battery state of charge |
| **Power Status** | Current charge/discharge power and daily energy totals |
| **24h Battery Chart** | Charge/discharge power + SOC line over 24 hours |
| **SOC Zone Config** | Sliders for priority, buffer, auto-start, and assist floor SOC levels |

### EV

EV charging session tracking and statistics.

![EV Tab](images/sem_ev_tab.png)

| Card | Description |
|------|-------------|
| **Charging Status** | Current mode, power, session energy, solar share |
| **Session Gauges** | Daily energy vs target, solar share percentage |
| **Charging Power Chart** | 24h EV power curve |
| **Charging Settings** | Night charging, forecast reduction, target, amps, wait conditions |
| **Lifetime Statistics** | Total energy, cost, sessions, solar share over all time |

### Control

All settings and device management in one place.

![Control Tab](images/sem_control_panel.png)

| Card | Description |
|------|-------------|
| **EV Charging** | Night charging toggle, forecast reduction, target, current settings |
| **Surplus Control** | Surplus available indicator, regulation offset |
| **Battery Management** | Priority/minimum/resume SOC, capacity |
| **Heat Pump & Hot Water** | Boost offset, hot water max temperature |
| **Solar & Power** | Min solar power, max grid import |
| **Tariff & Pricing** | Current rates, cheap/expensive thresholds |
| **Load Priority** | Drag-and-drop device ordering with real-time power, controllable/critical toggles |
| **Peak & Load Management** | Target peak limit, peak margin, sheddable devices |
| **Observer Mode** | Read-only toggle for safe monitoring |

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
| **Load Management** | Active devices, shedding status |

---

## Required HACS Cards

Install these via HACS > Frontend before the dashboard will render:

| Card | HACS Repository | Purpose |
|------|-----------------|---------|
| `mushroom` | `piitaya/lovelace-mushroom` | Chips, entity, template, number, title cards (~96 uses) |
| `card-mod` | `thomasloven/lovelace-card-mod` | Glass card styling via `*glass_card` anchor. **Missing = blank tabs.** |
| `apexcharts-card` | `RomRider/apexcharts-card` | All trend, power, and cost charts |
| `sankey-chart` | `MindFreeze/sankey-chart` | Energy flow diagram on Energy tab |
| `fold-entity-row` | `thomasloven/lovelace-fold-entity-row` | Collapsible "Welcome to SEM" intro |

**4 required HACS cards** (mushroom, card-mod, apexcharts-card, sankey-chart) + **1 optional** (fold-entity-row).

---

## Bundled SEM Cards

These ship with the integration — no HACS installation needed:

| Card | Purpose |
|------|---------|
| `sem-flow-card` | Animated SVG power flow with daily energy, autarky gauge, visual config editor, tap actions, up to 6 individual devices |
| `sem-system-diagram-card` | Legacy animated power flow (kept for backward compatibility) |
| `sem-solar-summary-card` | Solar production metrics with animated glow ring and forecast |
| `sem-weather-card` | Live clock, weather conditions, colored temperature forecast bars |
| `sem-chart-card` | Chart.js-powered charts with 6 presets (costs, savings, energy, power, battery, EV) |
| `sem-period-selector-card` | Date range picker controlling all chart cards |
| `sem-load-priority-card` | Drag-and-drop device priority with real-time power display, touch support |

Resource URLs include `?v={version}` for automatic cache busting.

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

## Troubleshooting

### Dashboard not appearing
1. Call `solar_energy_management.generate_dashboard` from Developer Tools > Services
2. Hard-refresh your browser (Ctrl+Shift+R)

### Cards showing "Custom element doesn't exist"
A required HACS card is missing. Check the browser console for the card name, install it via HACS, and hard-refresh.

### Blank Home tab
Missing `card-mod` — the `*glass_card` styling anchor requires it. Install via HACS.

### Entity not found errors
The dashboard references SEM sensors that may not exist yet. Wait for the first coordinator cycle (10 seconds after restart) and refresh.

### Cards not updating after SEM update
SEM includes `?v={version}` cache busting on all card URLs. If cards still show old behavior, hard-refresh (Ctrl+Shift+R) to force reload.
