# Multi-Device Setup Guide

This guide covers setting up SEM with different hardware combinations. SEM auto-detects most configuration from the HA Energy Dashboard, but some setups need extra attention.

---

## Supported Combinations

| Inverter | EV Charger | Battery | Status |
|----------|-----------|---------|--------|
| Huawei SUN2000 | KEBA P30 | Huawei LUNA | Fully tested (reference setup) |
| Growatt (SPH/TLX/MIX) | Wallbox Pulsar | Growatt battery | Tested by community |
| SolarEdge | Easee | BYD | Expected to work |
| Fronius | go-eCharger | Fronius battery | Expected to work |
| GoodWe | Zaptec | Any | Expected to work |
| Enphase | Any OCPP | Tesla Powerwall | Expected to work |
| SMA | Any | Sonnen | Expected to work |
| Victron | OpenEVSE | Victron battery | Expected to work |

> **Your combination not listed?** SEM works with any inverter/charger/battery that has sensors in Home Assistant. Open an issue if you need help.

---

## Per-Brand Setup Notes

### Huawei SUN2000 + LUNA (Reference)

- **Grid sensor**: Combined `sensor.power_meter_wirkleistung` (negative=import, positive=export) — matches SEM convention
- **Battery**: `sensor.battery_1_lade_entladeleistung` (positive=charge, negative=discharge) — matches SEM convention
- **Charger control**: `keba.set_current` service
- **Auto-detection**: Fully automatic via Energy Dashboard
- **Sign correction**: None needed

### Growatt (SPH / TLX / MIX)

- **Grid sensor**: Growatt provides **separate** import and export power sensors (both always positive):
  - `sensor.*_import_from_grid` (import power in W)
  - `sensor.*_export_to_grid` (export power in W)
- **SEM handling**: Auto-discovers split sensors and calculates `grid_power = export - import`
- **Charger control**: Wallbox uses a `number.*` entity — select it as "Current Control Entity" in the charger config
- **Important**: Ensure both grid import AND export energy sensors are configured in the Energy Dashboard

### SolarEdge

- **Grid sensor**: Combined sensor, usually positive=import (HA convention)
- **SEM handling**: Auto-detects sign from Energy Dashboard counters and negates if needed
- **Battery**: BYD batteries typically use positive=charge, negative=discharge

### Fronius

- **Grid sensor**: Combined sensor, varies by model
- **SEM handling**: Auto-detects sign convention
- **Note**: Some Fronius models report grid power in kW — SEM auto-converts

### GoodWe

- **Grid sensor**: Combined or split depending on model
- **SEM handling**: Auto-detection via Energy Dashboard
- **Troubleshooting**: See the [GoodWe troubleshooting section](../TROUBLESHOOTING.md)

---

## Multi-Charger Setup

### Adding a Second Charger

1. Go to **Settings → Devices & Services → Solar Energy Management → Configure**
2. Select **EV Chargers** → **Add another EV charger**
3. Configure the sensors for your second charger

### Current Control Methods

| Method | Chargers | Config Field |
|--------|----------|-------------|
| **Number entity** | Wallbox, go-eCharger, OpenEVSE | "Current Control Entity" — select the `number.*` entity |
| **Service call** | KEBA, Easee | "Set-Current Service" — enter the service name (e.g. `keba.set_current`) |

> **Important**: Use EITHER the number entity OR the service. Leave the other blank.

### Per-Charger Entities

Each configured charger creates its own sensor entities:

| Entity | Description |
|--------|-------------|
| `sensor.sem_charger_{id}_power` | Real-time charging power (W) |
| `sensor.sem_charger_{id}_session_energy` | Current session energy (kWh) |
| `sensor.sem_charger_{id}_session_solar_share` | Solar percentage of session (%) |
| `sensor.sem_charger_{id}_taper_trend` | BMS taper detection (stable/declining) |
| `sensor.sem_charger_{id}_taper_ratio` | Taper ratio (%) |

### Surplus Priority

Set a priority per charger (1 = highest). The highest-priority charger gets surplus power first. When it's full or at minimum power, remaining surplus flows to the next charger.

### Dashboard

When more than 1 charger is configured, the EV tab shows:
- Per-charger power cards
- A status table with power, session energy, solar share, and taper status per charger

Regenerate the dashboard after adding a charger: **Developer Tools → Services → solar_energy_management.generate_dashboard**

---

## Grid Sign Convention

SEM uses this convention:
- **Grid power**: negative = import, positive = export
- **Battery power**: positive = charge, negative = discharge

### How SEM Auto-Detects

1. **Combined sensor** (Huawei, SolarEdge, Fronius): SEM correlates the power sensor sign against Energy Dashboard import/export energy counter changes
2. **Split sensors** (Growatt): SEM discovers `*_import_from_grid` and `*_export_to_grid` entities automatically — no sign correction needed
3. **Self-healing**: If the energy balance is consistently negative (wrong sign), SEM auto-corrects

### Checking Your Setup

On the **System tab** of the dashboard, the Diagnostics section shows:
- **Grid mode**: `combined` or `split`
- **Grid sign**: `normal` or `negated`
- **Sensors unavailable**: Number of sensors currently offline

---

## Troubleshooting

### Import/export values seem swapped
- Check the **System tab → Diagnostics** for grid mode and sign
- Verify your Energy Dashboard has BOTH import and export energy sensors configured
- For Growatt: ensure `*_import_from_grid` and `*_export_to_grid` power sensors exist

### Home consumption shows 0 or very high
- This usually means the grid sign is wrong
- SEM should auto-correct within 3 minutes
- If it persists, check the HA logs for "grid sign" messages

### Charger not responding to current changes
- Verify the control method: number entity vs service
- Check Developer Tools → Services → test the service/number manually
- For Wallbox: use the "Current Control Entity" field, not the service field

### Second charger shows no data
- Update to latest beta, then regenerate dashboard
- Check that per-charger entities appear: `sensor.sem_charger_{id}_*`
- Verify the charger's power sensor is configured correctly

---

## Appliance Dependencies

Devices can declare dependencies so they only activate when other devices are already running. This prevents wasted energy or equipment damage.

### Use Cases

| Dependent | Depends On | Why |
|---|---|---|
| Pool heater | Pool pump | Heater without pump = equipment damage |
| Circulation pump | Heat pump | Pump alone = wasted energy |
| Heating element 2 | Heating element 1 | Stage 2 only when stage 1 is saturated |
| Hot water boost | Battery SOC > 80% | Only boost when battery is sufficiently charged |

### Configuration

When registering a surplus device, set the `depends_on` field to the device ID(s) that must be active:

```yaml
# Via service call:
service: solar_energy_management.register_surplus_device
data:
  device_id: pool_heater
  entity_id: switch.pool_heater
  name: Pool Heater
  priority: 6
  depends_on:
    - pool_pump
```

### Dependency Modes

| Mode | Behavior |
|---|---|
| `must_active` (default) | Dependent only activates when dependency IS running |
| `must_inactive` | Dependent only activates when dependency is NOT running (backup/fallback) |

### Setting Dependencies from the Dashboard

1. Go to the **Control** tab on the SEM dashboard
2. Find the device you want to make dependent
3. In the **Requires** dropdown, select the parent device
4. The child device automatically indents under the parent
5. To release: set **Requires** back to **None** — the device becomes independent

### Dependency Patterns

**Chain (A → B → C):**
```
≡  Pool Pump                    Requires: None
  ↳  Pool Heater                Requires: Pool Pump
    ↳  Pool Lights              Requires: Pool Heater
```
- Pump must be on before heater can start
- Heater must be on before lights can start
- Shutting down pump → cascades to heater → cascades to lights

**Siblings (A with B and C):**
```
≡  Heat Pump                    Requires: None
  ↳  Circulation Pump           Requires: Heat Pump
  ↳  Buffer Valve               Requires: Heat Pump
```
- Heat pump must be on before either can start
- Circulation and valve are independent of each other
- Shutting down heat pump → both children shut down

### How It Works

1. **Activation gate**: when SEM has surplus and tries to activate a device, it first checks all `depends_on` devices are in the required state
2. **Deactivation cascade**: when a device is deactivated (surplus dropped), all devices that depend on it are also deactivated
3. **Surplus mode**: child only turns on when parent is already running AND surplus is available
4. **Peak mode**: when shedding load, shutting down the parent also shuts down all children
5. **Dashboard**: blocked devices show "⏳ Waiting for: {device}" and are visually indented
6. **Drag protection**: children can't be dragged — they stay locked under their parent. Only parents can be reordered
7. **Persistence**: dependency settings survive HA restarts
8. **Circular detection**: SEM validates that dependencies don't form circular chains (A→B→A)
