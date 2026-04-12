<p align="center">
  <img src="../brand/icon@2x.png" alt="SEM Logo" width="120">
</p>

# Dashboard Guide — Community Edition

The SEM community dashboard provides a 5-tab interface for monitoring your solar system.

---

## Quick Start

The dashboard is generated automatically on first install. If you need to regenerate:

1. Go to **Developer Tools** > **Services**
2. Search for `solar_energy_management.generate_dashboard`
3. Click **Call Service**
4. Hard-refresh your browser (Ctrl+Shift+R)

---

## Required HACS Cards

Install via **HACS > Frontend > Explore & download**:

| Card | Why |
|------|-----|
| **mushroom** | Status chips, entity cards, template cards |
| **apexcharts-card** | Power and energy charts |

Only **2 HACS cards** required.

---

## Dashboard Tabs

### Home
| Card | Description |
|------|-------------|
| Status Chips | Solar power, battery SOC, autarky, EV status |
| Power Gauges | Solar, home consumption, battery SOC |
| Today's Energy | Daily totals for solar, home, grid, export |
| Charging Status | Current mode, strategy, EV energy today |
| Quick Controls | Night charging, forecast reduction, observer mode |

### Energy
| Card | Description |
|------|-------------|
| Gauges | Self-consumption rate, autarky rate |
| 24h Power | Solar, home, battery, grid over 24 hours |
| 7-Day Chart | Daily solar and home consumption |

### Costs
| Card | Description |
|------|-------------|
| Today | Costs, savings, export revenue, net cost |
| This Month | Monthly aggregated financials |
| Peak Load | Current peak, monthly peak, limit |

### Battery
| Card | Description |
|------|-------------|
| SOC Gauge | Current state of charge |
| Power Status | Charging/discharging with daily totals |
| 24h Chart | Charge and discharge power over 24 hours |
| SOC Zones | Priority, buffer, minimum SOC settings |

### EV
| Card | Description |
|------|-------------|
| Charging Status | State, strategy, power, daily progress |
| Daily Progress | Gauge showing energy vs target |
| Session Info | Energy, solar share, duration (when connected) |
| Controls | Night charging, forecast reduction toggles |
| 24h Chart | EV power over 24 hours |

---

## Troubleshooting

### Dashboard not appearing
1. Call `solar_energy_management.generate_dashboard` from Developer Tools > Services
2. Restart Home Assistant
3. Hard-refresh your browser (Ctrl+Shift+R)

### Cards not rendering
Install `mushroom` and `apexcharts-card` via HACS > Frontend, then hard-refresh.

