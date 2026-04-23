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

## Hot Water Control

SEM acts as a solar boost layer for hot water — it supplements your existing heating system (boiler, heat pump) rather than replacing it. Your existing system continues its normal heating schedule. SEM only activates when solar surplus is available, heating the water further to store energy that would otherwise be exported.

Legionella prevention complies with DVGW W 551 (Germany), SIA 385/1 (Switzerland), and ÖNORM B 5019 (Austria).

### Supported Entity Types

Hot water devices are controlled through one of three HA entity types:

| Entity type | How SEM controls it |
|---|---|
| `water_heater` | Sets target temperature via `water_heater.set_temperature` |
| `climate` | Sets target temperature via `climate.set_temperature` |
| `switch` | Simple on/off — used for resistive heating elements |

### Temperature Logic

The `solar_target_temp` (Solar Boost Target) is the cutoff temperature for solar surplus heating. When the water reaches this temperature, SEM stops heating and releases surplus for other devices. There is no separate "max temperature" — the solar boost target is the ceiling for SEM-controlled heating.

If the solar boost target is set at or above 60°C, the Legionella requirement is naturally satisfied during sunny days without a forced cycle.

### Legionella Prevention Cycle

SEM tracks the number of hours since the water last reached the Legionella target temperature (60°C+). When the configured interval is exceeded, SEM forces a heating cycle regardless of solar surplus availability:

1. **Normal operation** — during solar surplus, SEM heats water to the solar boost target (e.g., 50-65°C)
2. **Legionella countdown** — a counter tracks hours since the last time the water temperature reached the Legionella target
3. **Forced disinfection** — when the interval expires (default 72 hours), SEM forces heating to the Legionella target temperature, using grid power if necessary
4. **Hold duration** — the system holds the disinfection temperature for a duration that auto-adjusts based on the actual temperature reached (shorter hold at higher temperatures, since thermal kill rate increases exponentially)

### Configuration Parameters

| Parameter | Range | Default | Where configured | Description |
|---|---|---|---|---|
| Solar Boost Target | 40-80°C | — | Dashboard slider | Solar surplus heating cutoff |
| Legionella Target | 60-80°C | 65°C | Dashboard slider | Forced heating temperature (legal minimum 60°C) |
| Disinfection interval | 24-168 h | 72 h | Options flow | Maximum hours between disinfection cycles (not on dashboard) |

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

### Charger Abstraction

SEM abstracts charger-specific differences through per-integration service profiles:

- **Service profiles** — each supported charger integration has a `service_param_name` (e.g., `current` for KEBA, `charging_current` for Wallbox) and `service_device_id` mapping, so the coordinator can call the correct HA service with the right parameters.
- **Start/stop abstraction** — chargers that require explicit start/stop commands use `start_stop_entity`, `charge_mode_entity`, and `start_service` to manage session lifecycle. Chargers that only need current=0 to pause do not use these.
- **Supported chargers (auto-detected):** KEBA, Easee, Wallbox, go-eCharger (HTTP + MQTT), Zaptec, ChargePoint, Heidelberg, OpenWB 2.x
- **Manual config:** Any charger exposing power/connected/charging sensors in HA can be configured manually via the integration options.

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
| `battery_capacity_kwh` | auto-detected from inverter, fallback to config | coordinator |
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
