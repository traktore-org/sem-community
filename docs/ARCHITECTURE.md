# Architecture

This document covers the internal architecture of Solar Energy Management (SEM) for developers and contributors.

---

## Coordinator Module Structure

```
coordinator/
├── coordinator.py        — SEMCoordinator (DataUpdateCoordinator, 10s loop)
├── sensor_reader.py      — SensorReader (reads HA sensors → PowerReadings)
├── energy_calculator.py  — EnergyCalculator (power → energy integration)
├── flow_calculator.py    — FlowCalculator (power/energy flow distribution)
├── charging_control.py   — ChargingStateMachine (solar/night/Min+PV FSM)
├── surplus_controller.py — SurplusController (multi-device surplus routing)
├── forecast_reader.py    — ForecastReader (Solcast / Forecast.Solar)
├── notifications.py      — NotificationManager (KEBA display + mobile)
├── storage.py            — SEMStorage (persistent state)
└── types.py              — All dataclasses (PowerReadings, SessionData, SEMData, etc.)
```

The `SEMCoordinator` is a Home Assistant `DataUpdateCoordinator` that runs a 10-second update loop. Each cycle:

1. Reads sensors (`SensorReader`)
2. Calculates energy integration (`EnergyCalculator`)
3. Calculates costs & performance
4. Calculates power flows (`FlowCalculator`)
5. Updates session tracking
6. Calculates energy flows (daily Sankey totals)
7. Builds charging context and updates charging state machine
8. Executes EV control (night / solar / Min+PV)
9. Applies battery discharge protection
10. Runs load management
11. Reads forecast, tariff, surplus, PV analytics, energy assistant, utility signals
12. Builds `SEMData`, sends notifications, persists to storage

---

## Device Hierarchy

```
ControllableDevice (abstract base)
├── SwitchDevice           — on/off (hot water, smart plugs)
├── CurrentControlDevice   — variable current (EV chargers)
├── SetpointDevice         — numerical target (heat pump temp boost)
│   └── HeatPumpController — SG-Ready 4-state control
└── ScheduleDevice         — deadline-based (appliances)
```

---

## Surplus Distribution Algorithm

1. Read available surplus (solar - home - battery charge)
2. Subtract regulation offset (default 50W export buffer)
3. Iterate devices by priority (1=highest, 10=lowest)
4. Activate if surplus >= device minimum power threshold
5. Variable-power devices get proportional current allocation
6. When surplus drops: LIFO deactivation (lowest priority first)

The surplus controller is always-on and runs every coordinator update (~10s). Price-responsive mode is automatic when `tariff_mode == "dynamic"`.

---

## SOC Zone Strategy

SEM uses a four-zone model (inspired by [evcc](https://evcc.io)) to decide how the battery and EV share solar energy:

```
SOC 100% ─────────────────────────────
         │  Zone 4: FULL ASSIST       │  Battery assist always on
SOC 90%  ─── battery_auto_start_soc ──
         │  Zone 3: DISCHARGE ASSIST  │  Proportional battery assist
SOC 70%  ─── battery_buffer_soc ──────
         │  Zone 2: SURPLUS ONLY      │  EV gets pure solar surplus only
SOC 30%  ─── battery_priority_soc ────
         │  Zone 1: BATTERY PRIORITY  │  All solar → battery, EV blocked
SOC  0%  ─────────────────────────────
```

**Zone 1 — Battery Priority** (SOC < 30%): All solar goes to battery. EV blocked.

**Zone 2 — Surplus Only** (SOC 30-70%): EV gets only pure solar surplus (power that would be exported). Battery is not discharged.

**Zone 3 — Discharge Assist** (SOC 70-90%): Battery supplements solar for EV. Assist ramps from 50% at SOC 70% to 100% at SOC 90%.

**Zone 4 — Full Assist** (SOC >= 90%): Full battery assist (default 4500W). EV starts even without surplus.

**Hysteresis**: Once battery-assist activates (Zone 3/4), it stays active down to `battery_assist_floor_soc` (default 60%) to prevent cycling.

### SOC Zone Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `battery_priority_soc` | 30% | Below: all solar to battery, EV blocked |
| `battery_buffer_soc` | 70% | Above: battery can discharge for EV |
| `battery_auto_start_soc` | 90% | Above: start EV without surplus |
| `battery_assist_floor_soc` | 60% | Hysteresis floor for battery assist |
| `battery_assist_max_power` | 4500W | Max battery discharge for EV |

---

## EV Control Flow

The coordinator owns all EV control (`ev.managed_externally = True`). The EV is never managed by the SurplusController due to unique requirements (session lifecycle, minimum 4140W cliff, charger-specific service calls).

### Night Charging
- Starts at 10A when night mode activates (after sunset+10min / 20:30)
- Dynamic peak-managed current each cycle (+-2A ramp, min 8A floor)
- W/A ratio calculated from actual readings (fallback 475 W/A)
- Stall detection with 120s cooldown re-enables charger
- Stops when daily EV target reached (sunrise-based tracking)

### Solar Charging
- Sets current with ramp limiting (+-2A/cycle)
- evcc-style enable/disable delays
- Budget from `FlowCalculator.calculate_ev_budget()` + optional battery assist

### Min+PV Mode
- Budget floored to `ev.min_power_threshold`
- Enable delay = 0 (guaranteed minimum from grid)

### Pause States
- Zero current, keep session alive (no stop/start cycling)

---

## EV Budget Calculation

`FlowCalculator.calculate_ev_budget()` provides a forecast-aware EV power budget:

- **Source 1**: Grid export power (always redirectable)
- **Source 2**: Redirectable battery charge via forecast-based calculation
- When EV is already charging, budget includes current EV power + grid export

`SEMCoordinator._calculate_solar_ev_budget()` wraps this and adds proportional battery discharge for super-charging mode based on SOC zones.

---

## Energy Tracking — Sunrise-Based Meter Day

`EnergyCalculator` uses sunrise-based daily buckets, not midnight. Before sunrise = still "yesterday". This keeps night charging sessions (22:00-06:00) in a single bucket.

---

## Key Defaults

| Constant | Value | Location |
|----------|-------|----------|
| `DEFAULT_DAILY_EV_TARGET` | 10 kWh | `const.py` |
| `DEFAULT_EV_RAMP_RATE_AMPS` | 2 | config |
| `DEFAULT_EV_CHARGING_MODE` | `"pv"` | config |
| Update interval | 10s | coordinator |
| Regulation offset | 50W | surplus controller |
| Peak limit | 6 kW | load management |

---

## Other Key Modules

```
tariff/tariff_provider.py       — StaticTariffProvider, DynamicTariffProvider
analytics/pv_performance.py     — PVPerformanceAnalyzer
analytics/energy_assistant.py   — EnergyAssistant (tips, optimization score)
utility_signals.py              — UtilitySignalMonitor (ripple control signal)
utils/time_manager.py           — TimeManager (sunrise, night mode/end, meter day)
utils/helpers.py                — safe_float, safe_format, convert_power_to_watts
ha_energy_reader.py             — Read HA Energy Dashboard config
load_management.py              — LoadManagementCoordinator (peak tracking)
hardware_detection.py           — Auto-discover inverter/battery/charger
```
