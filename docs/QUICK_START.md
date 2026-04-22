<p align="center">
  <img src="../brand/icon@2x.png" alt="SEM Logo" width="120">
</p>

# Installation Guide

Get Solar Energy Management (SEM) running in 5 minutes.

---

## Prerequisites

Before installing SEM, make sure you have:

- **Home Assistant 2024.1.0** or newer
- **HA Energy Dashboard configured** — SEM reads your solar, grid, and battery sensors from it
  - Go to **Settings > Dashboards > Energy** and verify solar + grid sensors are set up
- **EV charger integration** installed (KEBA, Wallbox, go-eCharger, Easee, Zaptec, ChargePoint, Heidelberg, OpenWB 2.x, etc.)
- **5 HACS frontend cards** installed (see [Step 4](#step-4-install-dashboard-cards))

---

## Step 1: Install SEM

### Option A: Via HACS (Recommended)

1. Open **HACS** > **Integrations**
2. Click the 3-dot menu > **Custom repositories**
3. Add URL: `https://github.com/traktore-org/sem-community`
4. Set category: **Integration** > Click **Add**
5. Search for **Solar Energy Management** > Click **Download**
6. **Restart Home Assistant**

### Option B: Manual Install

1. Download the [latest release](https://github.com/traktore-org/sem-community/releases)
2. Copy the `solar_energy_management/` folder to `config/custom_components/`
3. **Restart Home Assistant**

---

## Step 2: Run the Setup Wizard

Go to **Settings** > **Devices & Services** > **Add Integration** > Search **Solar Energy Management**.

![SEM Integration Page](images/sem_integration.png)

The wizard has **3 simple steps**:

### Step 2a: Energy Dashboard Detection

SEM automatically reads your HA Energy Dashboard configuration and shows a summary of detected sensors:

```
Solar
  • Power: sensor.inverter_power
  • Energy: sensor.inverter_total_energy

Grid
  • Power: sensor.grid_power
  • Import: sensor.grid_import_energy
  • Export: sensor.grid_export_energy

Battery
  • Power: sensor.battery_power
  • Charge: sensor.battery_charge_energy
  • Discharge: sensor.battery_discharge_energy
```

Toggle **Observer Mode** if you want SEM to monitor only (no hardware control). Click **Submit**.

### Step 2b: EV Charger

Select your EV charger sensors:

| Field | Description | Example |
|-------|-------------|---------|
| **Connected sensor** | Binary sensor: is the car plugged in? | `binary_sensor.keba_p30_plug` |
| **Charging sensor** | Binary sensor: is charging active? | `binary_sensor.keba_p30_charging_state` |
| **Power sensor** | Current charging power (W) | `sensor.keba_p30_charging_power` |

Optional fields (auto-detected for most chargers):
- Charger service — HA service to set current (e.g. `keba.set_current`)
- Current sensor, total energy sensor

> **Tip:** Not sure which entities? Go to **Developer Tools > States** and filter for your charger brand.

Click **Submit**.

### Step 2c: Hardware

| Field | Default | Description |
|-------|---------|-------------|
| **Battery capacity** | 10 kWh | Your home battery size |
| **Target peak limit** | 5 kW | Grid peak limit for demand charge management |
| **Generate dashboard** | ON | Auto-create the 7-tab SEM dashboard |

SEM auto-detects your inverter's battery discharge control entity (shown in the description).

Click **Submit** — done!

---

## Step 3: Restart Home Assistant

After installation, restart HA once so the dashboard URL is registered:

**Settings** > **System** > **Restart**

After restart, **Solar Energy Management** appears in the sidebar.

---

## Step 4: Install Dashboard Cards

The SEM dashboard needs **5 HACS frontend cards**. Install via **HACS > Frontend > Explore & download**:

| Card | Why |
|------|-----|
| **mushroom** | Chips, entity, template cards — used everywhere |
| **card-mod** | Glass card styling — **without this, all tabs are blank** |
| **apexcharts-card** | All charts (power, energy, costs, trends) |
| **sankey-chart** | Energy flow diagram on the Energy tab |
| **fold-entity-row** | Collapsible welcome intro on Home tab |

After installing, **hard-refresh** your browser: `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac).

> **Note:** The animated system diagram, solar summary, weather card, chart card, period selector, and load priority card are **bundled with SEM** — no extra install needed.

---

## Step 5: Verify

Open the **Solar Energy Management** dashboard from the sidebar:

![SEM Dashboard Home](images/sem_dashboard_overview.png)

You should see:

| What to check | Expected |
|---------------|----------|
| System diagram | Animated power flow with solar, grid, battery, home nodes |
| Solar summary | Current production, yield, forecast, self-use, costs |
| Status chips | Solar power, battery SOC, autarky rate, EV status |
| 7-day chart | Bar chart with daily solar, home, grid |
| Weather card | Clock, temperature, 5-day forecast |

Check **Developer Tools > States** and filter for `sem_` — you should see **200+ entities** (sensors, switches, numbers).

---

The Energy tab shows flows, charts, and environmental impact:

![Energy Tab](images/sem_energy_flows.png)

The Costs tab tracks daily, monthly, and yearly financials:

![Costs Tab](images/sem_costs_tab.png)

---

## What SEM Does Automatically

Once installed, SEM works without any manual intervention:

| Time | What happens |
|------|-------------|
| **Sunrise** | SEM starts monitoring solar production |
| **Solar surplus** | EV charging current adjusts automatically (6–32A) to match surplus |
| **Clouds** | Charging pauses, resumes when surplus returns |
| **Battery full** | Battery-assist mode helps EV charging through cloudy moments |
| **Evening** | Solar charging stops, system monitors overnight |
| **Night** | If night charging is ON, grid-charges the EV to the daily target |
| **Smart forecast** | If forecast reduction is ON, tomorrow's sunny forecast reduces tonight's grid charging |

### The 3 Switches

These are the only controls you need:

| Switch | Default | Purpose |
|--------|---------|---------|
| `switch.sem_night_charging` | ON | Grid-charge EV overnight to daily target |
| `switch.sem_observer_mode` | OFF | Read-only mode — monitors but doesn't control |
| `switch.sem_forecast_night_reduction` | OFF | Reduce night target when tomorrow is sunny |

Everything else — solar charging, battery protection, peak management, surplus distribution — is fully automatic.

---

## Tuning (Optional)

All defaults work out of the box. If you want to fine-tune, go to:

**Settings > Devices & Services > Solar Energy Management > Configure** (gear icon)

The configuration is organized in 6 focused steps:

### Step 1: EV Charger

| Setting | Description |
|---------|-------------|
| Connected sensor | Binary sensor for plug status |
| Charging sensor | Binary sensor for charging activity |
| Power sensor | Current charging power (W) |
| Charger service | HA service to control current (e.g. `keba.set_current`) |
| Current sensor | Entity for current reading (A) |
| Total energy sensor | Lifetime energy counter |

### Step 2: SOC Zone Strategy

Controls how the battery and EV share solar energy:

| Setting | Default | Description |
|---------|---------|-------------|
| Priority SOC | 80% | Battery charges to this level before EV gets solar |
| Buffer SOC | 70% | Below this, battery-assist for EV is disabled |
| Auto-start SOC | 30% | Below this, EV charging pauses to protect battery |
| Assist Floor SOC | 20% | Absolute minimum — battery never discharges below this |
| Battery capacity | 15 kWh | Your home battery size |

### Step 3: EV Charging

| Setting | Default | Description |
|---------|---------|-------------|
| Daily EV target | 10 kWh | Night charging stops at this amount |
| Minimum current | 6 A | Minimum EV charging current |
| Night initial current | 10 A | Starting current for night charging |
| EV phases | 3 | Number of phases (1 or 3) |
| Stall cooldown | 120 s | Wait time after EV stalls before retrying |

### Step 4: Tariff & Advanced

| Setting | Default | Description |
|---------|---------|-------------|
| Import rate | 0.34 CHF/kWh | Grid electricity price |
| NT rate | 0.34 CHF/kWh | Off-peak rate |
| Export rate | 0.075 CHF/kWh | Feed-in tariff |
| Demand charge | 4.32 CHF/kW/month | Peak demand charge rate |
| Update interval | 10 s | How often SEM reads sensors |
| Power delta | 200 W | Minimum power change to adjust current |
| Current delta | 2 A | Minimum current change to send to charger |
| SOC delta | 5% | SOC change threshold for strategy recalculation |

### Step 5: Load Management

| Setting | Default | Description |
|---------|---------|-------------|
| Load management enabled | ON | Enable peak load shedding |
| Target peak limit | 6 kW | 15-min rolling peak target |
| Peak margin | 0.5 kW | Safety margin before shedding |

### Step 6: Notifications

| Setting | Default | Description |
|---------|---------|-------------|
| KEBA display | ON | Show charging info on KEBA P30 display |
| Mobile notifications | OFF | Push notifications for charging events |
| Mobile service | — | HA notify service (e.g. `notify.mobile_app_phone`) |

> **Quick alternative:** Most settings are also adjustable directly on the **Control tab** of the dashboard using number sliders and toggles.

---

## Next Steps

- [Dashboard Guide](DASHBOARD_GUIDE.md) — all 7 tabs explained with screenshots
- [User Guide](../USER_GUIDE.md) — detailed feature reference
- [Troubleshooting](../TROUBLESHOOTING.md) — common issues and fixes

---

## Uninstall

1. **Settings > Devices & Services > Solar Energy Management** > 3-dot menu > **Delete**
2. Remove `custom_components/solar_energy_management/` from your config directory
3. Restart Home Assistant
