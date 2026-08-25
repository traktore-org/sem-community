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

   The `min_solar_power` setting (default 1000 W in the Optimization Settings step) is the surplus *floor* below which SEM won't even attempt to start the charger — keep it well **below** the hardware minimum so SEM has headroom to ramp up before the cliff.
5. For night charging: check this charger's `select.sem_charger_<id>_charge_mode`. `Min + Solar` (the default), `Solar + cheapest hours` and `Always (max)` charge overnight; `Solar only` does not unless you set an "At least" floor on that charger. Also make sure it's within the night window.

---

## EV keeps charging when Charge mode is set to "Off"

**Symptom:** You set `select.sem_charger_<id>_charge_mode` to **Off**, the SEM
dashboard shows "Solar mode - System ready" with 0 A commanded, but the EV
charger still draws power.

**Cause (pre-v1.6.4):** A regression in the v1.6.3 consolidated Charge mode
selector. The state machine fell through to `SOLAR_CHARGING_ALLOWED` instead
of `SOLAR_IDLE`, and the actuator's stop path was never reached.

**Cause (post-v1.6.4 on KEBA):** KEBA P30's firmware remembers its last
current setpoint across power cycles. When an EV plugs in (or KEBA hits
certain internal events), the charger **self-starts** at the stored
setpoint independently of SEM. Because SEM never started an owned
session, its `_session_active` flag was False and the disable path
silently skipped.

**Fix (v1.6.5+):** Upgrade to v1.6.5 or later. Since v1.7.3-beta.50 (#392)
the **charger reconciler** owns this: every coordinator cycle it compares the
desired state against what the box is actually doing, and re-issues the
per-brand disable (e.g. `keba.disable`) whenever Charge mode is **Off** and
the charger has self-resumed. It is idempotent — the command only goes out
while the observation still disagrees — and KEBA-firmware-safe. Logs show:

```
reconcile(ev_charger): DISABLE — <reason>
```

at INFO level (`coordinator.charger_reconciler`) each time it re-asserts.

**Workaround if you're on v1.6.4 or earlier:**

1. Manually call the `keba.disable` service (or your charger's
   equivalent) from **Developer Tools > Services**.
2. Or simply **unplug** the EV — KEBA can't self-start on an unplugged
   cable.

The v1.6.5 fix has a worst-case 10-second window where KEBA can draw
power before SEM catches the self-resume; if you observe sustained
draw beyond that, file an issue with the SEM log line and the KEBA
`max_current` setpoint reported at the moment of the resume.

**Cause (entity service configured as charger service, v1.7.3+):** If
`ev_charger_service` is set to an entity service like `number.set_value`,
`input_number.set_value` or `select.select_option`, SEM maps the command
to the matching entity write automatically (v1.7.3-beta.8 for
`number.set_value`, generalized in beta.9). It needs a matching target:
set `ev_current_control_entity` to the charger's max-current
`number.*` / `input_number.*` / `select.*` entity. A wrong-domain target
logs a registration WARNING naming the charger. After 3 consecutive
rejected commands SEM raises a Repair ("EV charger not accepting
commands") — it clears automatically on the next successful write, and
since beta.9 a stale Repair left over from before a config fix is also
cleared on the first good write after the reload.

**Cause (no stop mechanism configured at all, v1.7.5+ surfaces it):** the
most common shape of this on non-KEBA hardware, and the hardest to spot,
because *everything looks right*: the mode is Off, SEM's intent is OFF, and
SEM issues the stop every single cycle. It just can't land. If the only
control you gave SEM is a current `number.*` entity whose **minimum is 6 A**
(most Wallbox/Heidelberg/generic setups), then:

- writing 0 A is impossible — Home Assistant rejects an out-of-range write
  before it reaches the charger, so SEM skips it (#487); and
- there is no other mechanism — no stop service, no charge-mode select, no
  start/stop switch, no `<brand>.disable` — to fall back to.

Net: nothing opens the contactor. On a house-battery install that is not a
cosmetic problem — the car will happily pull several kW out of your battery,
overnight, in "Solar only" or "Off" (#627).

Since **v1.7.5** SEM detects this up front rather than counting failed stops,
and raises a Repair — *"EV charger cannot be stopped"* — naming the charger,
the power still flowing and the entity it is stuck with.

**Fix:** give the charger a real stop mechanism in the SEM options — in
order of preference:

1. `ev_start_stop_entity` — a `switch.*` (or `input_boolean.*`) that opens
   the contactor. Best option; most integrations expose one
   (`switch.<charger>_charging`, `…_enable`, `…_pause`).
2. A charge-mode `select.*` plus its "stop"/"off" option
   (go-eCharger, OpenWB).
3. A brand stop service (`ev_stop_service`).

If your charger's current `number.*` entity can actually express **0 A**,
that alone is also enough — SEM will use it. Check the entity's `min`
attribute in **Developer Tools → States**.

The Repair clears by itself as soon as the charger stops drawing.

---

## Car charged overnight when I only wanted solar surplus

**Cause:** The charger's **Charge mode** allows grid-assisted night charging, and it had a charge target (a daily kWh target or a target SOC %) the car hadn't reached — so SEM topped it up from the grid overnight. The default mode on a fresh install is **`Min + Solar`**, which charges overnight by design.

**Fix:** To make a charger surplus-only, set its `select.sem_charger_<id>_charge_mode` to **`Solar only`** *and* leave its **"At least" floor at 0** (kWh mode) / its **Target SOC at its current level** (SOC mode).

Both halves matter: `Solar only` with a non-zero floor still tops that floor up from the grid by the Charge-by time — that floor is how you ask for an overnight guarantee without leaving the solar-first mode (#634/#679). With the floor at zero, the charger only ever draws solar surplus.

---

## Energy values not updating

**Cause:** Energy integration runs every 10 seconds using trapezoidal integration. Values only change when source power sensors change.

**Fix:**
1. Confirm the coordinator is running: `sensor.sem_charging_state` should NOT be `unavailable`. If it is, the integration failed to start — see HA logs.
2. Verify power sensors have numeric values (not "unknown" or "unavailable")
3. Check HA logs for SEM errors: **Settings > System > Logs**, filter for `solar_energy_management`
4. Daily ENERGY values (solar / home / grid / battery) reset at **midnight** — matching HA's Energy Dashboard. Two deliberate exceptions: the EV daily counter rolls at the **Charge-by deadline** (default 07:00, so an overnight charge stays in one bucket; on multi-charger installs only while all chargers share one deadline — otherwise the fleet total rolls at midnight, #724), and load **runtime targets** roll at **sunrise** (see MULTI_DEVICE_GUIDE)

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
as of v1.7.5 (#617) the dashboard has **zero required HACS cards** — every SEM
card ships in the bundled `sem-cards.js` and the rest is native HA. This error
after an update is almost always a stale browser cache: hard-refresh
(Ctrl+Shift+R) or clear the companion-app cache. Optional extras
(`sankey-chart`, `k-flow-card`) are auto-detected when installed — see
[Dashboard Guide → Required HACS Cards](DASHBOARD_GUIDE.md#required-hacs-cards).

---

## Dashboard blank, log says "ResourceYAMLCollection has no attribute async_create_item"

**Symptom:** the dashboard loads with no cards (or only the title), and the
HA log shows:

```
WARNING ... solar_energy_management: SEM detected YAML-mode Lovelace; SEM
card resources cannot be registered automatically. Add the following to
configuration.yaml under `lovelace.resources` and restart:
  - url: /local/custom_components/solar_energy_management/dashboard/card/dist/sem-cards.js
    type: module
  - url: /local/custom_components/solar_energy_management/dashboard/card/sem-localize.js
    type: module
```

**Cause:** you're running **YAML-mode Lovelace** (you have `lovelace: mode:
yaml` in `configuration.yaml`). In YAML mode the resource list is read-only
— SEM cannot register its bundle programmatically, so the cards aren't
loaded and the dashboard comes up blank. (Reported as
[#283](https://github.com/traktore-org/sem-community/issues/283); fixed in
v1.6.0 to produce the actionable warning above instead of an unhelpful
"Could not register" error.)

**Two ways to fix:**

### Option A — switch to storage-mode Lovelace (easiest)
Settings → Dashboards → ⋮ → "Take control" on the main dashboard. This is
the default for new HA installs and is what SEM is built around. The
auto-registration will then work on the next restart.

### Option B — stay on YAML mode, register manually
Add the two resources from the warning to your `configuration.yaml` under
`lovelace.resources`:

```yaml
lovelace:
  mode: yaml
  resources:
    - url: /local/custom_components/solar_energy_management/dashboard/card/dist/sem-cards.js
      type: module
    - url: /local/custom_components/solar_energy_management/dashboard/card/sem-localize.js
      type: module
    # plus the HACS cards SEM needs:
    - url: /hacsfiles/lovelace-card-mod/card-mod.js
      type: module
    - url: /hacsfiles/lovelace-mushroom/mushroom.js
      type: module
    # ... and apexcharts-card, sankey-chart as installed.
```

Restart HA. The warning will still log once per startup (YAML mode is
read-only by design — SEM can't suppress it), but the cards will load.

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

**If you configured the grid entities manually** (`grid_import_power_entity` / `grid_export_power_entity` in the SEM options): SEM uses exactly what you configured and does NOT auto-correct the sign — manual config is treated as explicit intent. Since v1.7.3-beta.7 SEM cross-checks your manual entities against the Energy Dashboard counters and logs a WARNING (`Manual grid power entities CONTRADICT…`) plus sets `diag_grid_manual_mismatch: true` in the diagnose dump when the two fields appear swapped. Checklist for the manual fields:

- The **import** field takes the sensor that is non-zero while you draw from the grid; the **export** field the one that is non-zero while you feed in. When unsure, watch both in Developer Tools → States at a moment of known heavy import (e.g. EV charging at night).
- Both fields must be **power** sensors (W/kW) — an energy counter (kWh) in either field is flagged with a WARNING and produces garbage values.
- Configure **both** fields or neither. With only one side set, the other reads a hard 0 W and that flow direction can never show ("always exporting").

**Dutch dual-tariff (DSMR) meters:** your meter splits each direction into *tarief 1* and *tarief 2* counters (`…verbruik_tarief_1/2`, `…productie_tarief_1/2`). Configure **all four** in the HA Energy Dashboard (Settings → Dashboards → Energy → Grid — you can add multiple flows per direction). With only one tariff's counters configured, SEM's grid energy statistics undercount during the other tariff's hours and the sign cross-check is blind in those windows.

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
2. Verify `load_management_enabled` is checked, and that **No grid limit**
   (`peak_limit_unlimited`) is **off** — it hides the kW fields and disables
   peak management entirely, including the ceiling the EV charger sizes against
3. Set a realistic `target_peak_limit` — your grid connection ceiling, from the
   supply contract or main breaker (e.g. 5.0 kW for a typical European household,
   about 38 kW for a 200 A North-American service). The field accepts 1–80 kW.
4. Check that controllable devices have been discovered: `sensor.sem_controllable_devices_count` should be > 0
5. The 15-minute rolling average (`sensor.sem_consecutive_peak_15min`) must exceed the target before shedding activates

---

## "Why did SEM touch that device?" — reading a load row in diagnostics

Every load in the diagnostics download (**Settings → Devices & Services → Solar
Energy Management → ⋮ → Download diagnostics**) carries two *independent*
answers, and mixing them up is the single most common misreading:

| Field | Question it answers | Comes from |
|---|---|---|
| `has_control_handle` | **Can** SEM control it? A switch / number entity / service call was discovered for this appliance. | Discovery. Nothing you set changes it. |
| `control_mode` | **May** SEM control it, and how? `off` / `peak_only` / `surplus` / `manual`. | The mode dropdown on the Load Priority card. |
| `user_hands_off` | **May** SEM control it? `true` = you toggled "never touch this load". | The controllable toggle on the Load Priority card. |
| `may_actuate` | The verdict: **would** SEM act on it right now? | All three above. |

So `has_control_handle: true` on a device you set to **Mode: Off** is correct
and expected — it says a switch exists, not that SEM is allowed to use it.
Read `may_actuate` for "would SEM touch this"; if that says `false` and SEM
still acted, that's a bug worth reporting (#780).

Before v2.0 these were a single field named `is_controllable`, which read like
permission but meant capability-and-a-bit-of-permission. It is still present,
derived, so older tooling keeps working.

---

## Costs or savings showing incorrect values

**Cause:** SEM uses configured tariff rates for cost calculations.

**Fix:**
1. Check import/export rates in the integration configuration
2. For dynamic tariffs (Tibber/Nordpool/aWATTar): verify the price sensor entity exists and has a numeric state
3. Currency is read from HA settings: **Settings > General > Currency**
4. Cost sensors reset daily at midnight (with the energy counters) — partial-day values are expected

---

## Dynamic tariff: prices parse as empty / classification stuck on "normal"

**Cause:** The configured price sensor doesn't expose a price array in a shape SEM recognises. SEM parses `prices_today`/`prices_tomorrow`, `today`/`tomorrow` (Tibber core), `prices`, `today_raw`/`tomorrow_raw` (Tibber Grid Reward), `raw_today`/`raw_tomorrow` (Nordpool), and `forecasts`/`rates` (Amber/Octopus).

**Diagnose:** Run the `solar_energy_management.diagnose` action with `section: tariff`. `tariff_parsed_attribute` names the attribute that matched (or `null` if none), `tariff_parsed_count` the number of price points, and `tariff_parsed_interval_seconds` the detected granularity (3600 hourly / 900 for 15-min markets).

**Fix:**
1. Point **Dynamic tariff entity** at the provider's *native* sensor that carries the arrays — not a template/derivative sensor that only mirrors the current price
2. **Tibber Pulse without a forecast sensor**: the core Tibber integration sometimes provisions no `electricity_price` sensor (upstream issue). Install the HACS *Tibber Grid Reward* integration and use its `sensor.current_price` (supported since v1.7.3-beta.10)
3. If your provider's shape isn't listed, pass the array through a template sensor attribute named `prices_today`, or open an issue with the sensor's attribute dump

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

## Hot water not heating

**Cause:** SEM only heats hot water when solar surplus is available (normal mode) or when a Legionella disinfection cycle is due (forced mode). If neither condition is met, the heater stays idle.

**Fix:**
1. Verify the hot water entity is configured in SEM: check **Settings > Devices & Services > Solar Energy Management > Configure**
2. Confirm the entity exists and is available in **Developer Tools > States** — search for your `water_heater.*`, `climate.*`, or `switch.*` entity
3. Check that the device control mode is set to `surplus` (not `peak_only` or `off`) — SEM will not activate devices in `peak_only` or `off` mode
4. Verify sufficient solar surplus: `sensor.sem_surplus_available` should exceed the heater's minimum power threshold
5. If using a `water_heater` or `climate` entity, check that the current temperature sensor is reporting correctly — SEM needs accurate temperature readings to decide when to heat

---

## Legionella cycle not running

**Cause:** The Legionella disinfection cycle triggers only when the configured interval (default 72 hours) has elapsed since the water last reached the disinfection target temperature (default 65°C).

**Fix:**
1. Check how long since the last disinfection: look at the hot water sensor attributes or SEM debug logs for the hours-since-last-60C counter
2. Verify the disinfection interval setting — if set to 168 hours (maximum), cycles will be infrequent
3. Confirm the temperature sensor is accurate — if the sensor falsely reports temperatures above 60°C, SEM will reset the counter and skip the cycle
4. Check that the hot water entity is available and controllable — SEM cannot force heating if the entity is unavailable or in an error state
5. Enable debug logging (see below) and search for `legionella` or `hot_water` in the logs to trace the cycle state

---

## GoodWe inverter — no values after setup

**Symptom:** SEM installs successfully with a GoodWe inverter, but all sensors show "unknown" or 0.

**Cause:** GoodWe works with SEM, but the HA Energy Dashboard must be configured with the correct GoodWe energy sensors first. SEM reads its source sensors from the Energy Dashboard — if those aren't set up, SEM has nothing to read.

**Fix:**
1. Go to **Settings > Dashboards > Energy**
2. Under **Solar panels**, add your GoodWe solar energy sensor (e.g., `sensor.goodwe_total_energy` or `sensor.goodwe_e_day`)
3. Under **Grid consumption**, add your grid import/export energy sensors
4. If you have a GoodWe battery (ES/EM/ET series), add battery charge/discharge energy sensors
5. Restart Home Assistant, then reconfigure SEM

**GoodWe sign conventions:** SEM auto-detects the sign convention by comparing power sensors against energy counters. GoodWe typically uses positive=export for grid and positive=charge for battery — SEM handles this automatically.

**GoodWe + Easee charger:** If using an Easee charger with GoodWe, the Easee power sensor is disabled by default in HA. Enable it at **Settings > Devices > Easee > Entities** before configuring SEM.

---

## Most values show 0 (SolaX and other energy-only setups)

**Symptom:** SEM installs, but the majority of entities (solar/grid/battery power and everything derived from them) stay at **0**. Reported for SolaX via the *SolaX Inverter Modbus* (`solax-modbus`) integration (#250).

**Cause:** SEM reads real-time power from the HA Energy Dashboard's **power** links (the `stat_rate` field added in HA 2025.12). Those are configured separately from the energy (kWh) sensors and are often missing — many integrations, including SolaX, only get their *energy* sensors wired into the dashboard. With no power link, SEM has no live power to read.

**Fix (automatic):** As of v1.5.13, SEM **auto-derives** the missing power sensor from the same device as the configured energy sensor — e.g. for SolaX it finds `sensor.solax_pv_power_total` (solar), `sensor.solax_measured_power` (grid), and `sensor.solax_battery_power_charge` (battery) on its own. The SolaX SOC sensor (named *Battery Capacity*, `sensor.solax_battery_capacity`) is now detected via its `device_class: battery` + `%` unit. Just update and restart — no manual steps needed in most cases.

**If values are still 0:** add the power sensors to the Energy Dashboard manually:
1. Go to **Settings > Dashboards > Energy**.
2. Open each source (Solar / Grid / Battery) and, alongside the energy sensor, add its **power** sensor (W or kW, `state_class: measurement`).
3. Restart Home Assistant.

**Confirm what SEM resolved (quickest):** on the dashboard **System** tab, expand **Diagnostics** and press **Copy diagnostics**. The copied text includes a `Config:` line, e.g. `solar:pwr=derived,energy=ok | grid:pwr=stat_rate,imp=ok,exp=ok | batt:pwr=none,chg=ok,dis=ok`. `pwr=none` or `energy=MISSING` shows exactly which source isn't wired up; `pwr=stat_rate` means HA provided the power link, `pwr=derived` means SEM recovered it from the device. Paste this when reporting an issue.

**Full detail:** download diagnostics at **Settings > Devices & Services > Solar Energy Management > ⋮ > Download diagnostics** and check `energy_dashboard.power_sensors` / `power_source` / `energy_sensors` for the exact entity IDs.

**Sign convention:** SolaX uses positive=import for grid (Pattern D) — SEM auto-detects and corrects this from the energy counters; no template sensor needed.

---

## Values are 0 after an HA restart, but fine after reloading the integration (#274)

**Symptom:** After restarting Home Assistant (soft or hard) the SEM readings stay at **0** / blank. Reloading the SEM integration (**Settings > Devices & Services > Solar Energy Management > ⋮ > Reload**) brings them right back. Reported for SolaX (`solax-modbus`).

**Cause:** SEM derives its real-time power sensors from the source integration's *device* (see the section above). On a cold start, SEM can finish loading **before** the source integration (e.g. solax-modbus) has registered its entities, so that derivation finds nothing — leaving power at 0. A manual reload works because by then the source is fully loaded.

**Fix (automatic):** As of v1.5.15, SEM keeps **re-deriving the power sensors on each update cycle** until they resolve, so the readings start on their own within a cycle or two of the source integration coming up — no manual reload needed. You'll see `Energy Dashboard power sensors resolved on attempt N — readings starting (#274)` in the log once it recovers. The retry is bounded, so an energy-only setup with no power sensor at all simply stops trying instead of looping.

---

## Debug logging

**The easiest way** is Home Assistant's built-in flow — no YAML, no restart:

1. **Settings → Devices & Services → Solar Energy Management → Enable debug logging**
2. Reproduce the problem.
3. Click **Disable debug logging** — Home Assistant downloads a log excerpt
   you can attach to a bug report.

At the normal log level SEM is quiet by design: a healthy install adds
essentially nothing to your Home Assistant log. Debug logs are
**transition-based** — SEM logs when a decision *changes* (charging intent,
battery command, a sensor going silent or coming back), not the same
unchanged state every cycle. A quiet debug log therefore means the system
is steady, not that logging is broken.

Alternatively, via `configuration.yaml` (persists across restarts):

```yaml
logger:
  default: warning
  logs:
    custom_components.solar_energy_management: debug
```

To enable logging for a specific module only:

```yaml
logger:
  logs:
    custom_components.solar_energy_management.coordinator.coordinator: debug
    custom_components.solar_energy_management.coordinator.charging_control: debug
    custom_components.solar_energy_management.coordinator.surplus_controller: debug
```

Levels can also be changed at runtime without a restart via
**Developer tools → Actions → `logger.set_level`**.

---

## Daily solar is higher than my PV strings / my inverter says (hybrid inverters)

**Cause:** SEM cross-checks daily solar against the production counter configured in your Energy
Dashboard, so a cloud-polled power sensor that drops to 0 between polls doesn't undercount the day.
On a **DC-coupled hybrid** that counter is often the inverter's *total yield*, which measures the
inverter's **AC output** — not PV. At night that output is your **battery** discharging to serve the
house, so the counter keeps climbing in the dark and SEM used to book it as solar production. On our
own Huawei SUN2000 + LUNA2000 that added **3.06 kWh of "solar" before sunrise** (#681).

**Fixed in v1.7.5-beta.25:** counter movement is ignored while the sun is below the horizon. Nothing
changes for daytime recovery — the case this feature exists for still works.

**How to check whether you were affected:** on a completed day, compare `sensor.sem_daily_solar_energy`
against the sum of your `sensor.sem_pv_string_*_daily_energy` sensors. They should agree within a few
percent. If solar reads high, home consumption reads high too — it's computed from the energy balance,
so inflated solar inflates it 1:1.

**Note:** the day the fix lands, the affected day's figures are already banked. Daily values are
correct from the following midnight; monthly/yearly/lifetime keep the historic inflation.

## "Home" in SEM is much lower than "Home" in the HA Energy Dashboard

**This is usually not a bug — the two numbers answer different questions.**

| Entity | Includes the EV? |
|---|---|
| `sensor.sem_daily_home_energy` | **No.** The house *without* the car. SEM keeps the EV separate because every charging decision it makes depends on telling the two apart. |
| `sensor.sem_daily_total_consumption` | **Yes.** House + car — **this is the one that matches the Energy Dashboard's "Home" figure.** |

HA's Energy Dashboard shows total consumption and draws individually-tracked devices as a *slice*
of it, not a subtraction from it. So on any day you charge a car, HA's number is larger than SEM's
`daily_home_energy` by roughly the car's energy, and both are correct.

**The check**, for a completed day:

```jinja
{{ states('sensor.sem_daily_total_consumption') }}   {# compare THIS to the Energy Dashboard #}
{{ states('sensor.sem_daily_home_energy') }}         {# house only, excludes the car #}
```

If `daily_total_consumption` matches your Energy Dashboard and `daily_home_energy` does not, nothing
is wrong. If the *total* is also off, that is a real divergence — see the section below.

## Daily home consumption doesn't match my meter (or the other daily rows)

**Cause (fixed in v1.7.5):** home is the one row nothing meters — it is by definition what is left
when the metered rows are subtracted from each other. SEM used to evaluate that balance
*instantaneously* (in watts, every cycle) and integrate the result. Because home is a small
difference of large terms, every sensor's tiny error lands on the home row magnified: installs
whose solar/grid/battery rows each matched their meters to ≤0.5 % still saw daily home off by
−8 % to +15 %, in both directions.

**Since v1.7.5** the daily home row is derived from the day's *reconciled* counters
(`solar + import − export + discharge − charge − EV`), the same way lifetime and yearly home were
already computed. The practical consequence: SEM's seven daily numbers now add up — home is the
exact residual of the six rows published beside it.

**Notes:**
- **The day you upgrade**, the home row keeps the old behaviour for one calendar day (the internal
  midnight EV mirror needs a full day of history before it can enter the balance). It derives from
  the following midnight.
- The balance only takes over when every flowing term is backed by a hardware counter from your
  Energy Dashboard; otherwise the old integrator keeps the row. If home still drifts, check that
  solar, grid and battery counters are configured in **Settings → Dashboards → Energy**.
- The *instantaneous* `sensor.sem_home_consumption_power` is unchanged (see ADR 0004) — only the
  daily energy row moved to the balance.

## Charging stopped before my car app showed the target (slow SOC sensors)

**This is intentional (v1.7.6, #708).** Some car integrations (OnStar and similar) poll the
vehicle SOC as rarely as every 30 minutes. Steering on such a stale value used to overshoot the
target by *sensor lag × charge power* — a 60 % target could land at 67 %. SEM now also tracks the
energy it actually delivered during the session: when *last reading + delivered energy* says the
target is reached, charging stops even though the car sensor still shows the old value.

- The charger card shows the reasoning live: `Car: 55 % (28 min ago) · est. now ~59 %`, and
  "Target reached — ~60 % estimated" after the stop. A mobile notification explains it too.
- When the sensor finally updates: if it confirms the target, nothing happens. If it lands
  **below** the target, SEM automatically resumes for the difference — you may see one or two
  short top-ups spaced by the sensor's polling interval. That is the feature keeping your
  "at least X %" promise, not flapping.
- The battery gauge always shows exactly what your car reports — the estimate only ever appears
  in the info line, and only while the sensor is stale during a session.

## Energy values spiked after integration update or restart

**Cause:** When a hardware integration (e.g. Huawei Solar) restarts or updates, its sensors go `unavailable` briefly. When they come back, SEM's energy integrator could multiply the returned power value by the entire gap duration, producing unrealistic energy spikes (e.g. 40+ kWh battery discharge on a 15 kWh battery).

**Protection (v1.4.1+):** SEM automatically skips energy accumulation when the time gap between updates exceeds 120 seconds. Look for this log message:

```
Energy integration gap: XXXs > 120s limit — skipping cycle to prevent accumulator spike
```

**If values already spiked:**
1. The daily accumulators reset at midnight — wait for the next day
2. For immediate correction: compare SEM values against hardware daily counters (e.g. `sensor.batteries_tagesentladung`) and adjust storage if needed
3. Restart the integration after corrections: **Settings > Devices & Services > Solar Energy Management > Reload**

## One device's energy today is absurd (thousands of kWh)

**Cause (fixed in 2.0.0):** the device's energy counter reset to zero — a
firmware update, a re-paired device, a replaced meter — and then climbed back
to its old reading. SEM caught the drop but not the return, so the lifetime
total was booked as one cycle's consumption. The tell is the energy-balance
health check: the members sum to far more than the house total, and exactly
one member is responsible.

**Now:** SEM remembers the reading the counter fell from and books only what
it gained over that mark — the real consumption across the outage. A delta no
window could physically deliver (over 100 kW for a single load) is refused,
recorded as *blind* rather than as zero, and the meter is trusted again from
where it now stands. Look for:

```
energy counter sensor.X recovered to N kWh after a reset from M — booking … kWh consumed across the … s outage, not the whole reading
```

A figure booked before the upgrade clears at the next day rollover (sunrise).

## Devices & Services shows dozens of loads that are settings, not devices

**Cause (fixed in 2.0.0):** load discovery admitted any `switch.*` it could
pair with a power sensor. A lot of hardware publishes its own knobs as
switches — a WLED strip's *reverse* / *freeze* / *night light*, a washing
machine's child lock, a router's status LED — and one `sensor.*_power` pairs
with all of a device's siblings, so one strip could contribute a dozen rows,
each controllable at 0 W.

**Now:** Home Assistant marks those entities **configuration** or
**diagnostic**, and SEM reads that mark — they are not discovered, not chosen
as a device's control surface, and rows an older version wrote retire
themselves on the next refresh (logged as `#781 dropped load row …`). Entities
your registry doesn't know (template switches, YAML helpers) are still kept,
as is anything you registered yourself with `register_surplus_device`.

---

# Repairs explained — what each notice means and what fixes it

Every SEM repair notice links here (or, where SEM itself is the likely
culprit, to a prefilled bug report). Each section says what the notice means,
why SEM raised it, and the fix — in that order.

## A configured sensor is unavailable

SEM reads a sensor you named during setup and Home Assistant reports it
`unavailable`. SEM keeps running on the last usable pipeline but any decision
that needs this value is degraded. **Fix:** check the integration that
provides the sensor (Settings → Devices & Services) — restart it if it shows
an error; if you renamed or removed the entity, point SEM at the replacement
in the Configuration tab. The notice clears itself when the sensor returns.

## A sensor stopped updating (stale)

The sensor exists and has a state, but it has not changed for far longer than
its normal cadence — a frozen value is worse than a missing one, because
every downstream number silently keeps computing on it. **Fix:** the usual
culprit is the device's connection (Modbus/WiFi/cloud), not Home Assistant.
Power-cycle or reload the source integration. SEM clears the notice on the
first fresh update.

## No solar forecast integration found

SEM plans night charging and battery budgets against tomorrow's solar
forecast, and no supported forecast integration is installed. Everything
reactive still works; everything *forecast-led* is off. **Fix:** install one
of Forecast.Solar (no account needed), Open-Meteo Solar Forecast, or Solcast,
then reload SEM. The Configuration tab's Solar forecast section shows what
SEM detected.

## The recorder is not available

Home Assistant's recorder (its history database) is disabled or broken, and
SEM uses it to seed yearly statistics and to learn from history. **Fix:**
re-enable the default `recorder:` in `configuration.yaml` (or repair the
database it points at). SEM works without it, but learning features start
from zero.

## Heat pump SG-Ready relay unavailable

The switch entity SEM drives for an SG-Ready signal is unavailable, so heat
pump boosting cannot be actuated. **Fix:** check the relay's integration
(often a Shelly or similar); if the entity was renamed, re-select it in the
heat pump settings.

## Heat pump: only one SG-Ready relay

SG-Ready encodes four operating states on TWO relays; with one relay SEM can
only toggle between two states and says so rather than pretending. **Fix:**
wire and configure the second relay if your heat pump supports the full
four-state scheme; otherwise this notice is informational and can be
dismissed.

## Hot water switch unavailable

The switch that starts your hot-water boost is unavailable — SEM cannot run
its hot-water program. **Fix:** as with any relay: check the providing
integration, re-select the entity if it changed.

## Hot water temperature sensor unavailable

Without the temperature, SEM cannot tell whether a boost is needed or done,
so the hot-water program is on hold. **Fix:** restore the sensor (or pick a
different one in the settings); the program resumes on the next reading.

## A charger control entity is broken

A number/switch SEM uses to command your wallbox exists in the registry but
rejects writes or reports unavailable — commonly after the charger's
integration was reinstalled and entity ids changed. **Fix:** open the
charger's settings in SEM's Configuration tab and re-select the current
control entity. The repair names the exact entity it means.

## KEBA failsafe is fighting SEM

Your KEBA's failsafe (`Curr FS` / `Tmo FS`) re-applies a fallback current
whenever SEM goes quiet, undoing SEM's control. SEM normally arms a
non-tripping failsafe itself; this notice means it could not. **Fix:** in the
KEBA's web interface or DIP configuration, set the failsafe fallback current
to `0` (meaning: a quiet controller = stay off), or let SEM manage it by
granting the needed permissions in the charger settings.

## Your wallbox undoes SEM's stop on a timer

The box re-enabled itself a fixed number of seconds after SEM's stop, at
least twice, with no command in between — the signature of a charger-side
failsafe/controller-timeout fallback (any brand, not only KEBA; common on
Modbus-driven boxes). SEM deliberately does not fight it — re-stopping faster
would strobe the contactor and the box wins anyway. **Fix:** find the
failsafe/fallback-current setting on the wallbox and set the fallback current
to `0`. The notice retires itself once a stop holds.

## The inverter refuses forced discharge

SEM asked your inverter/battery to force-discharge (battery-to-grid export)
three times and the write was refused each time — this hardware or its
integration does not support it. SEM stops asking and re-probes quietly every
ten minutes, so a firmware update recovers on its own. **Fix:** if you never
intended battery export, clear the forcible-discharge entity in SEM's battery
settings and the notice disappears; if you do want it, check whether your
inverter's firmware/integration version exposes a working discharge control.
