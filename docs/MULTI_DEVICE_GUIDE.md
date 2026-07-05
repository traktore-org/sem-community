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
- **Troubleshooting**: Check the System tab on the SEM dashboard for sensor diagnostics

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

### Per-Charger Settings (v1.5.2+; consolidated in v1.6.3)

Each charger gets its own EV charging configuration:

| Entity | Description |
|--------|-------------|
| `number.sem_charger_{id}_daily_ev_target` | Night charging target (kWh) per charger |
| `number.sem_charger_{id}_daily_ev_target_max` | Solar-surplus ceiling (kWh) per charger |
| `number.sem_charger_{id}_minimum_current` | Minimum charging current (A) |
| `select.sem_charger_{id}_charge_mode` | Per-charger Charge mode (Solar only / Solar + cheapest hours / Min + Solar / Always (max) / Off). v1.6.3 replacement for the legacy `night_charging`, `smart_night_charging`, `tariff_optimized` switches. |

You can set different modes and targets per car — e.g., *Min + Solar* with 15 kWh Min for a daily commuter, *Solar only* with 8 kWh Max for a plug-in hybrid. These settings are also editable in the config flow (Settings → Integrations → SEM → Configure → Edit charger).

### Per-Charger Sensors

Each configured charger creates its own sensor entities:

| Entity | Description |
|--------|-------------|
| `sensor.sem_charger_{id}_power` | Real-time charging power (W) |
| `sensor.sem_charger_{id}_session_energy` | Current session energy (kWh) |
| `sensor.sem_charger_{id}_session_solar_share` | Solar percentage of session (%) |
| `sensor.sem_charger_{id}_taper_trend` | BMS taper detection (stable/declining) |
| `sensor.sem_charger_{id}_taper_ratio` | Taper ratio (%) |
| `sensor.sem_charger_{id}_estimated_soc` | EV battery SOC estimate (%) |
| `sensor.sem_charger_{id}_taper_minutes_to_full` | Estimated minutes to full charge |
| `sensor.sem_charger_{id}_daily_energy` | Energy delivered today by this charger (kWh) |

### Surplus Priority

Set a priority per charger (1 = highest). The highest-priority charger gets surplus power first. When it's full or at minimum power, remaining surplus flows to the next charger.

### Night Charging

Each charger charges independently at night:
- Each charger uses its own `daily_ev_target` — no equal splitting
- Night charging can be toggled on/off per charger
- Start amps and minimum current are configurable per charger
- If both chargers are connected and have capacity, both charge simultaneously

### Dashboard

The `sem-ev-status-card` on the EV tab automatically shows per-charger sections when chargers are configured:
- **Connected status** — per-charger CONNECTED/DISCONNECTED indicator (reads each charger's plug sensor independently)
- **Battery SOC gauge** — shows real vehicle SOC when `vehicle_soc_entity` is configured per charger, otherwise estimated SOC from taper detection
- **Per-charger metrics** — power, session energy, solar share
- **Charge Tonight** — per-charger indicator (Yes/No)
- **Nights Until Charge** — per-charger estimate using the charger's own vehicle SOC
- **Inline settings** — night charging toggle, target kWh, start/min amps (tap to edit)

When multiple chargers are configured, the global status row is hidden to avoid redundancy with per-charger sections.

Regenerate the dashboard after adding a charger: **Developer Tools → Services → solar_energy_management.generate_dashboard**. The new per-charger sections show up immediately — no HA restart needed (v1.5.16+); hard-refresh the browser if cards look stale.

![EV Tab Multi-Charger](screenshots/ev-tab-multi-charger.png)

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

## Generic Surplus Loads (switches, sockets, pumps)

Any switchable load — pool pump, heater rod, a dumb EV socket — can be
driven by SEM. One service call is enough; the registration **persists
across restarts** and returns a summary response:

```yaml
service: solar_energy_management.register_surplus_device
data:
  device_id: kia_socket
  entity_id: switch.kia_socket
  name: Kia Socket
  rated_power: 2300        # W the load draws when on
  priority: 5              # lower = gets surplus first
```

SEM then switches the load ON when the solar surplus covers its rated
power and OFF when the surplus is gone (anti-flicker: min 5 min on /
1 min off). Remove it again with
`solar_energy_management.unregister_surplus_device`.

### The mode ladder — who is in charge, and how far SEM goes

Every device row on the Control tab has **one mode picker** — a 5-step
ladder where each step adds capability:

| Mode (UI) | Behavior |
|---|---|
| **Off** | SEM monitors only, never switches the device |
| **Peak only** | **Your own automations** run the device; SEM only sheds it to protect the grid peak and restores it afterwards (catch the surplus via the event interface below) |
| **Surplus — solar only** | SEM runs the device on solar surplus; **never grid power** — on a dark day the daily target is missed (logged once) |
| **Surplus + cheap top-up** | …and while behind the daily target, cheap tariff windows complete it from grid |
| **Surplus + finish by deadline** | …and if the remaining target no longer fits before the deadline, SEM force-runs the device in time — regardless of price |

(Services and automations see this as two fields: `control_mode` =
`off`/`peak_only`/`surplus`, plus `top_up_policy` =
`solar_only`/`cheap_hours`/`always` for the three surplus steps.)

Devices auto-discovered from the Energy Dashboard default to
`peak_only`; devices you register via the service default to
`surplus` with `solar_only` — that's what you register them for.

### Catching the surplus in your own automations (`peak_only`)

If you prefer to keep your own schedules (e.g. a 3×/day pump
automation) and just want them to land on solar surplus, subscribe to
SEM's surplus signal:

- **`binary_sensor.sem_surplus_available`** — ON once the unallocated
  surplus has stayed above the threshold
  (`number.sem_surplus_event_threshold`, default 1500 W) for 60 s; OFF
  once it has stayed below 80 % of the threshold for 120 s. The
  debounce means clouds can not flap your automations.
- **`solar_energy_management_surplus` event** — fired on every
  transition with `available`, `surplus_w`, `unallocated_w`,
  `threshold_w` in the payload.

```yaml
automation:
  - alias: Pump on solar surplus
    triggers:
      - trigger: state
        entity_id: binary_sensor.sem_surplus_available
        to: "on"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.pool_pump }
```

### Daily targets — the goal engine

A surplus-mode device can be given a **daily goal**. On the Control tab
each device row has a target 🞋 button opening the **Daily Target**
panel — the same look as the EV charger's Charge Target:

- A **dual-handle slider**: the green **At least** handle is the daily
  target, the orange **Up to** handle is the safety cap. Parking Up-to
  at the far right means **no cap** (shown as ∞).
- A **min ↔ kWh unit picker** (top right): the slider sets a *runtime*
  target for dumb loads (pool pump: at least 240 min) or an *energy*
  target for metered loads (at least 5 kWh). Default unit is min.
- **Finish by** — the time the target should be met (empty = end of day).
- **Stop when** — an external completion condition: a sensor and a
  value (e.g. the car's SOC sensor ≥ 80) that ends the device's day
  early once reached.
- A **progress bar** under the row (e.g. `10/25 min → 21:00 ✓`) —
  progress survives restarts.

The same goal can be set in the registration call or per field via
`update_device_config`:

```yaml
service: solar_energy_management.register_surplus_device
data:
  device_id: pool_pump
  entity_id: switch.pool_pump
  rated_power: 800
  daily_min_runtime_min: 240      # ≥ 4h/day…
  target_deadline: "21:00"        # …finished by 9pm
  top_up_policy: cheap_hours      # = mode "Surplus + cheap top-up"
```

| Field | Meaning |
|---|---|
| `daily_min_runtime_min` | Runtime target (the green At-least handle, min unit) |
| `daily_max_runtime_min` | Runtime safety cap (the orange Up-to handle; 0 = no cap) |
| `daily_target_energy_kwh` | Energy target (At-least handle, kWh unit) |
| `daily_max_energy_kwh` | Energy safety cap (Up-to handle, kWh unit; 0 = no cap) |
| `target_deadline` | HH:MM by which the target should be met (default: end of day) |
| `top_up_policy` | The surplus mode step: `solar_only` / `cheap_hours` / `always` |
| `stop_entity` + `stop_at` | External completion condition |

#### What happens when the target is NOT reached?

Worked example — 25 min target, 10 min done from surplus, sun gone:

- **Surplus — solar only:** nothing is forced. The target is missed,
  SEM logs one line, progress resets at midnight for a fresh attempt.
  This mode never draws grid power.
- **Surplus + cheap top-up:** the next *cheap* tariff window
  force-starts the device from grid until the remaining 15 min are
  done. No cheap window before midnight → missed like solar-only.
- **Surplus + finish by deadline:** SEM continuously compares
  remaining target vs time until the deadline. With "Finish by" empty
  (= 23:59), at 23:44 the remaining 15 min no longer fit — the device
  force-starts regardless of price and stops when the target is met.
  A deadline that passes unmet (HA down, peak block) still force-runs
  afterwards until met, giving up at the day rollover.

In every mode: **peak protection outranks the goal** (a device chasing
its target still sheds for a grid peak, and forces are suppressed while
the peak is at risk), the anti-flicker minimums (5 min on / 1 min off)
shape the switching, and once the target or a cap is reached the device
is done for the day. A restart never orphans a device SEM switched on —
running surplus devices are re-owned at boot.

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
