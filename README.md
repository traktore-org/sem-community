<p align="center">
  <img src="icon@2x.png" alt="SEM Logo" width="200">
</p>

# Solar Energy Management (SEM)

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

**Turn your solar panels, battery, and EV charger into one intelligent system.**

SEM automatically maximizes your solar self-consumption, dynamically controls EV charging current, coordinates battery and EV priorities, and protects you from peak demand charges — all running locally inside Home Assistant. No cloud, no subscription.

---

## What SEM Does That Home Assistant Doesn't

Home Assistant's Energy Dashboard shows you data. **SEM acts on it.**

| Problem | SEM Solution |
|---------|-------------|
| EV charges from grid even when solar is available | **Solar EV charging** — dynamically adjusts current (6-32A) to match real-time surplus |
| Battery and EV compete for solar | **4-zone SOC strategy** — battery charges first to priority level, then EV gets surplus |
| Night charging wastes money when tomorrow is sunny | **Forecast reduction** — checks tomorrow's solar forecast and reduces overnight grid charging |
| Grid demand peaks cause expensive charges | **Peak shaving** — tracks 15-min rolling average, sheds devices before exceeding limit |
| Solar surplus goes to grid at low feed-in rates | **Surplus distribution** — routes excess power to EV, heat pump, hot water by priority |
| No visibility into real savings | **Cost tracking** — daily/monthly costs, savings, export revenue in your local currency |

---

## Key Features

### Smart EV Charging
SEM reads your solar production every 10 seconds and adjusts the EV charging current between 6A and 32A to match the available surplus. When clouds pass, charging pauses. When sun returns, it resumes. No manual intervention needed.

- **Solar mode** — pure solar surplus charging during the day
- **Night mode** — grid charging during off-peak hours with configurable window
- **Battery assist** — when battery is above buffer SOC, it supplements solar through cloudy moments
- **Forecast reduction** — if tomorrow's forecast is sunny, tonight's grid charge target is reduced

### Battery-EV Coordination
The 4-zone SOC model ensures your battery and EV work together, not against each other:

| Zone | SOC Range | What Happens |
|------|-----------|-------------|
| **Priority** | 0% → 80% | Battery charges first, EV waits |
| **Buffer** | 80% → 70% | EV gets solar, battery assists through clouds |
| **Normal** | 70% → 30% | Standard solar operation |
| **Protection** | Below 20% | EV pauses to protect battery |

All thresholds are configurable.

### Peak Load Management
SEM tracks your 15-minute rolling grid import average and automatically sheds non-critical loads before you exceed your contractual limit. Drag-and-drop device priority ordering — critical devices are never shed.

### 3 Switches, Everything Else Automatic
| Switch | Default | What It Does |
|--------|---------|-------------|
| `switch.sem_night_charging` | ON | Grid-charge EV overnight to daily target |
| `switch.sem_observer_mode` | OFF | Read-only — monitors but doesn't control hardware |
| `switch.sem_forecast_night_reduction` | OFF | Reduce night target when tomorrow is sunny |

---

## Supported Hardware

| Type | Brands |
|------|--------|
| **Inverters** | Huawei SUN2000, SolarEdge, Fronius, and any with HA integration |
| **Batteries** | Huawei LUNA2000, BYD, Tesla Powerwall, and others |
| **EV Chargers** | KEBA P30, Easee, go-eCharger, Wallbox, Tesla Wall Connector |
| **Grid Meters** | Any smart meter with power and energy sensors in HA |

SEM auto-detects your hardware from the HA Energy Dashboard configuration. Grid sign convention (positive/negative for import/export) is detected automatically — works with any inverter brand.

---

## Installation (5 minutes)

### Prerequisites
- **Home Assistant 2025.3+**
- **HA Energy Dashboard** configured (solar + grid sensors)
- **EV charger integration** installed
- **HACS**: `mushroom` and `apexcharts-card` frontend cards

### Install
1. **HACS** > Integrations > Custom repositories
2. Add: `https://github.com/traktore-org/sem-community` (Integration)
3. Download **Solar Energy Management**, restart HA
4. **Settings** > Devices & Services > Add Integration > Solar Energy Management
5. 3-step wizard: auto-detects sensors → configure EV charger → set battery capacity

SEM auto-generates a 5-tab monitoring dashboard on first install.

---

## What You Get

### 150+ Sensors
| Category | What It Tracks |
|----------|---------------|
| **Power** | Solar, grid import/export, battery charge/discharge, EV, home (W) |
| **Energy** | Daily and monthly totals for all sources (kWh) |
| **Flows** | Where energy goes: solar→home, solar→EV, grid→battery, etc. |
| **Costs** | Import costs, solar savings, export revenue, net cost (CHF/EUR) |
| **Performance** | Self-consumption rate, autarky rate (%) |
| **Charging** | State, strategy, session energy, solar share |
| **Peak** | 15-min rolling peak, monthly maximum, demand charge |

### 5-Tab Dashboard
| Tab | Content |
|-----|---------|
| **Home** | Power gauges, daily summary, charging status, controls |
| **Energy** | Self-consumption/autarky, 24h power chart, 7-day trend |
| **Costs** | Daily/monthly financials, peak load status |
| **Battery** | SOC gauge, charge/discharge chart, zone configuration |
| **EV** | Charging state, session progress, controls, power chart |

### 6 Languages
English, German, French, Italian, Spanish, Dutch

---

## Configuration

All settings via **Settings > Devices & Services > Solar Energy Management > Configure**:

| Category | Settings |
|----------|----------|
| **EV Charger** | Sensors, charger service, current control |
| **SOC Zones** | Priority, buffer, auto-start, protection thresholds |
| **EV Charging** | Daily target, min/night current, phases, cooldown |
| **Tariff** | Import/export rates, demand charge, update interval |
| **Load Mgmt** | Peak limit, shedding margin, device priority |
| **Notifications** | KEBA display, mobile push alerts |

---

## Documentation

- [Installation Guide](docs/QUICK_START.md) — step-by-step setup
- [Dashboard Guide](docs/DASHBOARD_GUIDE.md) — all 5 tabs explained
- [User Guide](USER_GUIDE.md) — complete feature reference
- [Troubleshooting](TROUBLESHOOTING.md) — common issues and fixes

---

## Contributing

Contributions welcome! Fork, create a branch, submit a PR.

If you find SEM useful, consider [becoming a sponsor](https://github.com/sponsors/traktore-org).

## License

MIT — see [LICENSE](LICENSE)

---

[releases-shield]: https://img.shields.io/github/release/traktore-org/sem-community.svg?style=for-the-badge
[releases]: https://github.com/traktore-org/sem-community/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/traktore-org/sem-community.svg?style=for-the-badge
[commits]: https://github.com/traktore-org/sem-community/commits/main
[license-shield]: https://img.shields.io/github/license/traktore-org/sem-community.svg?style=for-the-badge
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[hacs]: https://github.com/custom-components/hacs
