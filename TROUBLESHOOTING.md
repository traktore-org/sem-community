# Troubleshooting

## Sensors showing "unavailable"

**Cause:** SEM reads sensors from the HA Energy Dashboard. If those sensors are unavailable, SEM sensors will also be unavailable.

**Fix:**
1. Go to **Settings > Dashboards > Energy** and verify solar and grid sensors are configured
2. Check that the underlying hardware integration (Huawei Solar, SolarEdge, etc.) is online
3. Verify entity IDs haven't changed (e.g., after re-adding an integration)
4. Check **Developer Tools > States** and search for the sensor entity — if it shows "unavailable", fix the source integration first

---

## EV charging not starting

**Cause:** SEM needs to detect the EV charger's connected and charging binary sensors.

**Fix:**
1. Check that the EV charger integration (KEBA, Easee, go-eCharger, Wallbox) is installed and working
2. Verify the connected sensor shows "on" in **Developer Tools > States** when the car is plugged in
3. Go to **Settings > Devices & Services > Solar Energy Management > Configure** and check the EV sensor configuration
4. For solar charging: verify surplus power exceeds the **hardware minimum** of your charger:
   - 1-phase chargers: ~1380 W (6 A × 230 V)
   - 3-phase chargers: ~4140 W (6 A × 3 × 230 V)

   The `min_solar_power` setting (default 500 W in the Optimization Settings step) is the surplus *floor* below which SEM won't even attempt to start the charger — keep it well **below** the hardware minimum so SEM has headroom to ramp up before the cliff.
5. For night charging: check that `switch.sem_night_charging` is enabled and it's within the night window

---

## Energy values not updating

**Cause:** Energy integration runs every 10 seconds using trapezoidal integration. Values only change when source power sensors change.

**Fix:**
1. Confirm the coordinator is running: `sensor.sem_charging_state` should NOT be `unavailable`. If it is, the integration failed to start — see HA logs.
2. Verify power sensors have numeric values (not "unknown" or "unavailable")
3. Check HA logs for SEM errors: **Settings > System > Logs**, filter for `solar_energy_management`
4. Daily energy values reset at **sunrise** (not midnight) — this is by design for accurate night charging tracking

---

## Dashboard not appearing

The SEM dashboard is generated automatically on first install (the
"Generate dashboard" toggle in the final setup step is **on by default**).
It should appear in the sidebar within a few seconds of finishing the
config flow. If it doesn't:

**Recovery:**
1. Call the `solar_energy_management.generate_dashboard` service from
   **Developer Tools > Actions** (search for "Solar Energy Management").
2. The dashboard appears immediately under **Dashboards** in the sidebar
   — no HA restart required.
3. Hard-refresh your browser (Ctrl+Shift+R) so newly-installed custom
   cards from `/config/www/` are picked up.

**If the dashboard appears but cards show "Custom element doesn't exist":**
some HACS frontend cards are missing. See [Dashboard Guide → Required
Custom Cards](docs/DASHBOARD_GUIDE.md#required-custom-cards) for the full
list — `card-mod`, `bar-card` and `mushroom` are the most commonly missing.

---

## Grid import/export values are swapped

**Symptom:** SEM shows grid import when the house is actually exporting (or vice versa). The `sensor.sem_grid_power` sign is the opposite of the hardware power meter.

**How SEM detects grid direction:** SEM reads the grid power sensor from your HA Energy Dashboard configuration. It then compares the power sensor's sign against the import/export energy counters (also from the Energy Dashboard) to automatically detect the sign convention. This works because the energy counters always increase in the correct direction — if the import counter is growing while the power sensor is positive, SEM knows positive means import and will correct accordingly.

**Requirements:**
- HA Energy Dashboard must be configured with grid import AND export energy sensors
- Both energy sensors must be available (not "unknown" or "unavailable")
- Grid power must exceed 100W for detection to activate

**Fix:**
1. Verify your Energy Dashboard has both `flow_from` (import) and `flow_to` (export) energy sensors configured under **Settings > Dashboards > Energy > Grid**
2. Restart HA — the detection runs automatically after startup
3. Check logs: `ha core logs | grep "Grid sign"` — you should see "Grid sign confirmed/detected"
4. If no log appears, the power may be too low (<100W) or energy counters may be unavailable

**Sign conventions by inverter brand:**
| Brand | Power sensor convention | SEM correction |
|-------|------------------------|----------------|
| Huawei SUN2000 | - = import, + = export | None needed |
| SolarEdge | + = import, - = export | Auto-negated |
| Fronius | + = import, - = export | Auto-negated |
| Template sensor (HA convention) | + = import, - = export | Auto-negated |

---

## Battery charge/discharge values are swapped

**Symptom:** SEM shows battery charging when it's actually discharging (or vice versa). The `sensor.sem_battery_power` sign is opposite of what the hardware reports.

**How SEM detects battery direction:** SEM compares the battery power sensor's sign against the charge/discharge energy counters from the Energy Dashboard. If the discharge counter is growing while battery power is positive, SEM knows positive means discharge (opposite of SEM convention) and auto-corrects.

**Requirements:**
- HA Energy Dashboard must be configured with battery charge AND discharge energy sensors
- Both energy sensors must be available (not "unknown" or "unavailable")
- Battery power must exceed 100W for detection to activate

**Fix:**
1. Verify your Energy Dashboard has battery charge and discharge energy sensors configured under **Settings > Dashboards > Energy > Battery**
2. Restart HA — detection runs automatically after startup
3. Check logs: `ha core logs | grep "Battery sign"` — you should see "Battery sign confirmed/detected"

**Sign conventions by inverter brand:**
| Brand | Battery power convention | SEM correction |
|-------|------------------------|----------------|
| Huawei SUN2000 | + = charge, - = discharge | None needed |
| Fronius | + = charge, - = discharge | None needed |
| SolarEdge | + = charge, - = discharge | None needed |
| Enphase | + = discharge, - = charge | Auto-negated |
| GoodWe | + = discharge, - = charge | Auto-negated |
| Tesla Powerwall | + = discharge, - = charge | Auto-negated |
| Sunsynk (kellerza) | + = discharge, - = charge | Auto-negated |

---

## Peak load management not working

**Cause:** Load management must be explicitly enabled and configured with a target peak limit.

**Fix:**
1. Go to **Settings > Devices & Services > Solar Energy Management > Configure**
2. Verify `load_management_enabled` is checked
3. Set a realistic `target_peak_limit` (e.g., 5.0 kW for a typical household)
4. Check that controllable devices have been discovered: `sensor.sem_controllable_devices_count` should be > 0
5. The 15-minute rolling average (`sensor.sem_consecutive_peak_15min`) must exceed the target before shedding activates

---

## Costs or savings showing incorrect values

**Cause:** SEM uses configured tariff rates for cost calculations.

**Fix:**
1. Check import/export rates in the integration configuration
2. For dynamic tariffs (Tibber/Nordpool/aWATTar): verify the price sensor entity exists and has a numeric state
3. Currency is read from HA settings: **Settings > General > Currency**
4. Cost sensors reset daily at sunrise — partial-day values are expected

---

## Two HA instances controlling the same hardware

**Cause:** Running both a production and test HA instance with SEM against the same physical devices (KEBA, inverter, Shelly switches) causes conflicting commands.

**Fix:**
Enable **Observer Mode** on the test instance:
1. Go to **Settings > Devices & Services > Solar Energy Management > Configure**
2. Navigate to **Optimization Settings**
3. Enable **Observer Mode (Read-Only)**
4. Restart — confirm the log shows `Observer mode: hardware control disabled`

In observer mode, SEM reads all sensors and calculates everything normally but does not send any service calls to hardware. This is safe to run alongside a production instance.

---

## Options flow shows "Unknown error occurred"

**Cause:** Fixed in v1.2.0. The root cause was a `NumberSelector` with `step=0.0001` below the HA 2026.4 minimum allowed step value, combined with `null` config defaults that caused the options flow to crash.

**Fix:**
Update to SEM v1.2.0 or newer. This issue does not occur on v1.2.0+.

---

## Easee charger not detected

**Cause:** Easee's power sensor is disabled by default in the HA Easee integration. SEM cannot detect the charger without an active power sensor.

**Fix:**
1. Go to **Settings > Devices & Services > Easee**
2. Click on the Easee device
3. Find the power sensor entity (it will be listed as disabled)
4. Click the entity, then click **Enable** and confirm
5. Wait for the entity to become available, then re-configure SEM

---

## Tesla Wall Connector can't control charging

**Cause:** The Tesla Wall Connector does not expose a power sensor or current control entity in Home Assistant. This is a hardware/integration limitation — the Wall Connector's API does not support external current control.

**Status:** Monitoring-only. SEM can read voltage and current values if available, but cannot start/stop charging or adjust the charging current.

---

## Debug logging

To enable detailed logging for SEM, add this to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.solar_energy_management: debug
```

Restart Home Assistant after adding this. Debug logs will appear in **Settings > System > Logs**.

To enable logging for a specific module only:

```yaml
logger:
  logs:
    custom_components.solar_energy_management.coordinator.coordinator: debug
    custom_components.solar_energy_management.coordinator.charging_control: debug
    custom_components.solar_energy_management.coordinator.surplus_controller: debug
```
