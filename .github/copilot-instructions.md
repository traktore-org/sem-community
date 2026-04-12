# AI Agent Guidelines for Solar Energy Management (SEM)

## Project Overview
Solar Energy Management (SEM) is a Home Assistant integration for optimizing solar power, battery storage, and EV charging. It maximizes solar self-consumption while protecting battery levels and managing peak load.

## Key Architecture Components

### Core System (`const.py`, `coordinator.py`)
- Energy flow management through dual state machine design
- Sensor naming convention using `sensor.sem_*` prefix
- Priority-based energy distribution (Home → Battery → EV → Grid)
- Database protection with configurable update intervals

### Sensor Framework
```python
# Example sensor structure from const.py
SEM_SENSORS = {
    "solar_power": "sensor.sem_solar_power",
    "grid_power": "sensor.sem_grid_power",
    "battery_power": "sensor.sem_battery_power"
    # ...
}
```

### Device Discovery (`hardware_detection.py`)
- Pattern-based auto-discovery of solar, battery, and EV components
- Confidence scoring system for hardware detection
- Manufacturer-specific sensor patterns in `HARDWARE_MANUFACTURERS`

## Critical Workflows

### 1. Test & Deploy
- Always run test suite before changes: `./run_tests.sh`
- Key test files: `test_flow_accumulation.py`, `test_coordinator.py`
- CI/CD pipeline via n8n deploys to TEST (10.10.0.45) then PROD (10.10.0.150)

### 2. Energy Flow Changes
- Use `replace_string_in_file` carefully - include 3 lines of context
- Test flow accumulation after changes to prevent bugs
- Verify energy balance equation holds: Solar = Home + Battery + EV + Grid

### 3. UI Updates
- Dashboard generation via `dashboard_generator.py`
- Required HACS cards: mushroom-cards, apexcharts-card, etc.
- Label-based entity organization using `SEM_LABELS`

## Project Conventions

### Database Protection
```python
# Use these update intervals (const.py)
DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes
DEFAULT_POWER_DELTA = 1000    # Watts threshold
DEFAULT_SOC_DELTA = 10        # Battery % threshold
```

Protection levels for high-load environments:
- MINIMAL: All sensors enabled, normal updates
- BALANCED: Reduced flow sensors, longer delays
- AGGRESSIVE: Essential sensors only, max delays

### Sensor Names
- Hardware sensors mapped to standardized names
- Flow sensors follow `flow_source_to_destination` pattern
- Energy sensors use `daily_` or `monthly_` prefix
- Always use constants from `const.py`

### State Machine States
```python
class ChargingState:
    SOLAR_IDLE = "solar_idle"
    SOLAR_CHARGING_ACTIVE = "solar_charging_active"
    NIGHT_CHARGING_ACTIVE = "night_charging_active"
    # ...
```

## Integration Points

### Hardware Integration
- Support for Huawei, SolarEdge, Fronius, Enphase
- EV chargers: KEBA, Wallbox, go-eCharger
- Pattern-based sensor discovery in `hardware_scanner.py` with confidence scoring
- Example hardware detection pattern:
```python
# From hardware_detection.py
HARDWARE_PATTERNS = {
    "solar_production": [
        ("sensor.huawei_solar_active_power", "Huawei Solar Power"),
        ("sensor.huawei_solar_*_active_power*", "Huawei Solar Multi Power"),
        # Generic fallbacks
        ("sensor.*solar*power*", "Generic Solar Power"),
        ("sensor.*pv*power*", "Generic PV Power")
    ]
}
```

### Home Assistant Services
1. `solar_energy_management.recreate_energy_dashboard`
2. `solar_energy_management.generate_dashboard`
3. KEBA services via `keba.set_current`, etc.

### Data Flows
```
Solar Power → Home Priority → Battery Management → EV Charging → Grid Export
```

## Common Patterns

### Flow Energy Calculation
- Use accumulation guards to prevent duplicate counting
- Reset daily totals at configured time (default 00:00)
- Always validate against total energy sensors

### Peak Load Management
- Priority levels 1-10 for devices (1=Critical, never shed, 10=First to shed)
- Hysteresis to prevent rapid switching with configurable thresholds
- Critical device protection enabled by default
- Controlled tariff support (<3kW for reduced demand charge)
- Example load management configuration:
```python
# From const.py
DEFAULT_TARGET_PEAK_LIMIT = 5.0  # kW - Main target to never exceed
DEFAULT_WARNING_PEAK_LEVEL = 4.5  # kW - Early warning level
DEFAULT_EMERGENCY_PEAK_LEVEL = 6.0  # kW - Hard emergency limit
DEFAULT_PEAK_HYSTERESIS = 0.2  # kW - Prevent rapid cycling

# Anti-flicker protection
DEFAULT_MIN_ON_DURATION = 300  # seconds - Minimum time device stays on
DEFAULT_MIN_OFF_DURATION = 60   # seconds - Minimum time device stays off
```

### Battery Management
```python
# Key thresholds (const.py)
DEFAULT_BATTERY_PRIORITY_SOC = 90  # Battery first
DEFAULT_BATTERY_MINIMUM_SOC = 30   # Stop EV charging
DEFAULT_BATTERY_RESUME_SOC = 50    # Resume charging
```

## Debugging Tips

### Common Issues
1. Flow energy accumulation bugs - use `test_flow_accumulation.py` 
2. Database locks - adjust update intervals
3. Missing energy data - run backfill service from `migration/backfill_sem_statistics.py`
4. Energy balance mismatch - check flow calculations in `coordinator.py`
5. Sensor pattern mismatches - verify against `HARDWARE_PATTERNS` in `hardware_detection.py`

### Verification Tools
1. SEM Debug Template dashboard
2. Energy balance check sensor
3. Performance ratio monitoring

## Documentation
- User Guide: `USER_GUIDE.md`
- Technical docs in `docs/technical/`
- Dashboard guides in `dashboard/docs/`
- Migration guides in `docs/migration/`