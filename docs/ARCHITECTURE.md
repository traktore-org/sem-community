# Architecture

This document covers the internal architecture of Solar Energy Management (SEM) for developers and contributors.

---

## Coordinator Module Structure

```
coordinator/
├── coordinator.py          — SEMCoordinator (DataUpdateCoordinator, 10s loop)
├── sensor_reader.py        — SensorReader (reads HA sensors → PowerReadings)
├── energy_calculator.py    — EnergyCalculator (power → energy integration)
├── flow_calculator.py      — FlowCalculator (power/energy flow distribution)
├── charging_control.py     — ChargingStateMachine (solar/night/Min+PV FSM)
├── ev_taper_detector.py    — EVTaperDetector (taper detection, virtual SOC, skip logic)
├── surplus_controller.py   — SurplusController (multi-device surplus routing)
├── forecast_reader.py      — ForecastReader (Solcast / Forecast.Solar)
├── notifications.py        — NotificationManager (KEBA display + mobile)
├── storage.py              — SEMStorage (persistent state)
└── types.py                — All dataclasses (PowerReadings, SessionData, SEMData, etc.)
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
- **Supported chargers (auto-detected):** KEBA, Easee, Wallbox, go-eCharger (HTTP + MQTT), Zaptec, ChargePoint, Heidelberg, OpenWB 2.x, OCPP-compatible, Ohme, Peblar, V2C Trydan, Alfen Eve, Blue Current, OpenEVSE
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

## Hardware Compatibility Testing

SEM includes a comprehensive hardware compatibility test suite (v1.2.3) that verifies every supported inverter + charger combination works correctly end-to-end.

### Test Structure

The suite runs 110 end-to-end tests, each executing a 10-step verification sequence per hardware combination:

1. **Sensor discovery** — auto-detect inverter and charger entities
2. **Sign convention detection** — verify grid and battery sign auto-detection
3. **Power reading** — read solar, grid, battery, and EV power sensors
4. **Energy integration** — validate energy accumulation from power readings
5. **Flow calculation** — verify power flow distribution (solar-to-home, solar-to-EV, etc.)
6. **Charging control** — test EV charging state machine transitions
7. **Battery zone logic** — validate SOC zone strategy decisions
8. **Surplus distribution** — verify multi-device surplus allocation
9. **Service calls** — confirm charger service calls use correct parameters
10. **Round-trip validation** — end-to-end cycle from sensor read to hardware command

### Tested Combinations (11)

| Inverter | Charger |
|----------|---------|
| Huawei SUN2000 | KEBA P30 |
| Huawei SUN2000 | Wallbox Pulsar |
| Huawei SUN2000 | go-eCharger |
| SolarEdge | KEBA P30 |
| SolarEdge | Easee |
| Fronius | KEBA P30 |
| Fronius | go-eCharger |
| Growatt | Wallbox Pulsar |
| SolaX | go-eCharger |
| DEYE/Sunsynk | Zaptec |
| GoodWe | ChargePoint |

All 11 combinations are run in CI on every pull request and release. If your inverter and charger are in this list, SEM has been automatically verified against that exact pairing.

---

## EV Intelligence

The `EVTaperDetector` (coordinator/ev_taper_detector.py, ~590 lines) provides six capabilities integrated into the coordinator's 10-second update loop via `_update_ev_intelligence()`:

### Data Flow

```
SEMCoordinator._update_ev_intelligence()
  ├── EVTaperDetector.update_power_buffer(ev_power, setpoint)
  ├── EVTaperDetector.detect_taper() → EVTaperData
  ├── EVTaperDetector.update_virtual_soc(energy, vehicle_soc) → float
  ├── ConsumptionPredictor.update() / predict() → float
  ├── EVTaperDetector.should_skip_night_charge(...) → (bool, str)
  └── EVTaperDetector.update_battery_health(session) → float
```

### Key Dataclasses (coordinator/types.py)

```python
@dataclass
class EVTaperData:
    trend: str              # "declining", "stable", "rising", "unknown"
    taper_ratio_pct: float  # Current power / session peak × 100
    slope_w_per_min: float  # Linear regression slope
    minutes_to_full: float  # ETA to completion
    ev_full_detected: bool  # Taper reached 0W

@dataclass
class EVIntelligenceData:
    taper: EVTaperData
    estimated_soc_pct: float
    last_full_charge: Optional[str]       # ISO timestamp
    energy_since_full_kwh: float
    predicted_daily_ev_kwh: float
    nights_until_charge: int
    charge_needed: bool
    ev_battery_health_pct: float
    charge_skip_reason: str               # Human-readable explanation
```

### Taper Detection

Uses a 20-minute circular power buffer. Linear regression on the buffer detects a declining trend. BMS-initiated reductions are discriminated from SEM setpoint changes via a settling window (samples after a SEM command are excluded). When power reaches 0W during a declining trend, `ev_full_detected` is set.

### Virtual SOC

Tracks cumulative energy since last known full charge. Calibrates from:
1. Taper detection (resets to 100%)
2. Vehicle SOC entity (proportional calibration)
3. Session bootstrapping (initial estimate from first session)

### Skip Logic

```
required_soc = predicted_daily_kwh × temp_correction × 1.3 (safety margin)
available_soc = estimated_soc - daily_decay
solar_credit  = forecast_tomorrow × 0.3
charge_needed = (available_soc - solar_credit) < required_soc
```

Consecutive skip counter enforces a 3-skip safety net.

### State Persistence

EV intelligence state (SOC estimate, last full charge, consumption history, skip counter) is persisted via `SEMStorage.set/get_ev_intelligence_state()` and restored on HA restart.

---

## Multi-Device Aggregation

SEM reads **all** energy sources from the HA Energy Dashboard instead of only the first entry. This is handled in `ha_energy_reader.py` and `coordinator/sensor_reader.py`.

### Energy Dashboard Config Fields

```python
# List fields (new in v1.3.0)
solar_power_list: list[str]              # Multiple inverter power sensors
solar_energy_list: list[str]             # Multiple inverter energy sensors
battery_power_list: list[str]            # Multiple battery power sensors
battery_charge_energy_list: list[str]    # Multiple battery charge sensors
battery_discharge_energy_list: list[str] # Multiple battery discharge sensors
grid_import_energy_list: list[str]       # Multiple grid import tariffs
grid_export_energy_list: list[str]       # Multiple grid export tariffs
grid_power_list: list[str]              # Multiple grid power sensors
```

### Aggregation Logic

- `SensorReader._read_sensors_sum(entity_list)` — sums numeric values from multiple sensors; skips unavailable/unknown
- `SensorReader._read_battery_soc_average()` — averages SOC across multiple battery units
- Primary (single) fields are set from the first source for backward compatibility

### Backward Compatibility

Single-device setups are unaffected. The list fields contain exactly one entry, and the primary field points to the same sensor. No configuration changes needed.

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
