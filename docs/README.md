# SEM Documentation Index

All SEM documentation lives in this directory. Start here.

## Getting started (users)

| Doc | What it covers |
|-----|----------------|
| [QUICK_START.md](QUICK_START.md) | Install → configure → dashboard in 15 minutes |
| [SETUP_GUIDE.md](SETUP_GUIDE.md) | Every setting explained — the backend for the in-dashboard help links |
| [USER_GUIDE.md](USER_GUIDE.md) | Day-to-day usage and the full configuration-options reference |
| [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) | The 8-tab dashboard: cards, languages, customization |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and their fixes |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | What SEM deliberately does not do (and why) |

## Feature guides (users)

| Doc | What it covers |
|-----|----------------|
| [EV_CHARGING_LOGIC.md](EV_CHARGING_LOGIC.md) | How the five charge modes decide — the canonical EV reference |
| [MULTI_DEVICE_GUIDE.md](MULTI_DEVICE_GUIDE.md) | Multiple chargers, inverters and batteries |
| [LOAD_PRIORITY.md](LOAD_PRIORITY.md) | The single device-priority list (loads, chargers, battery) |
| [HARDWARE_SENSORS.md](HARDWARE_SENSORS.md) | Wiring sensors: power, energy counters, per-brand notes |
| [PV_STRINGS.md](PV_STRINGS.md) | Per-string PV monitoring |
| [GRID_VPP.md](GRID_VPP.md) | Grid/VPP event dispatch (observer-first) |
| [BATTERY_EXPORT_ARBITRAGE.md](BATTERY_EXPORT_ARBITRAGE.md) | Selling stored energy on price peaks (currently deactivated) |
| [KEBA_FAILSAFE.md](KEBA_FAILSAFE.md) | KEBA-specific failsafe behavior |

## Developer / internals

| Doc | What it covers |
|-----|----------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Coordinator pipeline, module map, design decisions |
| [MULTI_CHARGER.md](MULTI_CHARGER.md) | Per-charger correctness: the retired swap surface, adapters, status classification |
| [BUG_CLASSES.md](BUG_CLASSES.md) | The recurring-bug-class ledger and its guards |
| [SEM_TRACE.md](SEM_TRACE.md) | The cycle-trace / perception observability layer |
| [UI_PATTERNS.md](UI_PATTERNS.md) | Card design language (the EV card is the reference) |
| [AUDIT_PLAYBOOK.md](AUDIT_PLAYBOOK.md) / [AUDIT_BACKLOG.md](AUDIT_BACKLOG.md) | Audit program process + backlog |
| [adr/](adr/) | Architecture decision records |

PDFs: `SEM_Manual_EN/DE.pdf`, `SEM_Brochure_EN/DE.pdf` (marketing/manual exports).
