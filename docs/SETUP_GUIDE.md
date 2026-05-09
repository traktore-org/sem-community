# SEM Setup Guide

Solar Energy Management (SEM) is a Home Assistant integration that reads your
solar, grid, battery, and EV charger data and makes intelligent decisions about
how to distribute energy across your home.

This guide is the detailed companion to the
[Quick Start guide](QUICK_START.md). If you want to be up and running in five
minutes and figure out the details later, start there. Come here when you want
to understand what each setting does and why it exists.

For dashboard customization, see [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md).
For multi-inverter and multi-charger setups, see
[MULTI_DEVICE_GUIDE.md](MULTI_DEVICE_GUIDE.md).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation via HACS](#2-installation-via-hacs)
3. [Configuration: the Config Flow](#3-configuration-the-config-flow)
4. [Verification](#4-verification)
5. [Fine-tuning via the Options Flow](#5-fine-tuning-via-the-options-flow)
6. [SOC Zone Strategy](#6-soc-zone-strategy)
7. [Language Support](#7-language-support)
8. [FAQ](#8-faq)

---

## 1. Prerequisites

### Home Assistant version

SEM requires **Home Assistant 2024.1.0 or newer**. Check your version at
**Settings > System > About**.

### HACS

SEM is distributed through HACS (Home Assistant Community Store). If you do
not have HACS installed, follow the official instructions at
<https://hacs.xyz/docs/use/> before continuing.

### The Energy Dashboard — the most important prerequisite

SEM reads all its source sensors from the **HA Energy Dashboard**, not from a
manual sensor list you provide. This design means SEM works with any inverter
brand automatically — it just asks the Energy Dashboard what you have.

Before installing SEM, go to **Settings > Dashboards > Energy** and confirm:

- "Solar panels" section has at least one solar production sensor
- "Grid consumption" and "Grid return" sections have sensors assigned
- *(Optional)* "Home battery storage" has battery in/out sensors

![Energy Dashboard configuration](images/sem_energy_dashboard_config.png)

If the Energy Dashboard is blank or partially configured, SEM will detect
fewer sensors and may fail to calculate energy flows correctly. Configure it
first, then install SEM.

> **Why the Energy Dashboard?** HA's Energy Dashboard is already the
> canonical registry of energy sensors in your installation. SEM leverages
> this so you never have to map sensors manually — and so it automatically
> handles the sign conventions of different inverter brands (Huawei,
> Fronius, SolarEdge, etc. all report grid direction differently).

### Supported hardware

**Inverters (all auto-detected):** Huawei SUN2000, SMA, Victron, Sungrow,
Fronius, Enphase, Powerwall, Kostal, SolarEdge, GoodWe, Sonnen, SolaX,
Growatt, and any inverter that exposes watt-level sensors to HA.

**EV chargers:** KEBA P30 (service-based), Easee (service-based), Zaptec
(service-based), Wallbox, go-eCharger, ChargePoint, Heidelberg, OpenWB 2.x,
OCPP-compatible, Ohme, Peblar, V2C Trydan, Alfen Eve, Blue Current, OpenEVSE,
and any charger with a controllable number entity.

**Solar forecasts (optional):** Solcast, Forecast.Solar.

> **Easee note:** Easee's charging power sensor is disabled by default in HA.
> Before installing SEM, go to **Settings > Devices > Easee** and enable the
> power sensor, otherwise SEM cannot read charger power.

> **GoodWe note:** GoodWe inverters work via the HA
> [GoodWe integration](https://www.home-assistant.io/integrations/goodwe).
> Ensure your Energy Dashboard is configured with GoodWe sensors before
> installing SEM. SEM auto-detects GoodWe's sign conventions.

### Checklist

- [ ] HA 2024.1.0 or newer
- [ ] HACS installed
- [ ] Energy Dashboard configured (solar + grid sensors at minimum)
- [ ] *(Optional)* Battery sensors visible in HA
- [ ] *(Optional)* EV charger integration installed and sensors enabled

---

## 2. Installation via HACS

![SEM in the HACS integrations list](images/sem_hacs_page.png)

1. Open Home Assistant and click **HACS** in the sidebar.
2. Click **Integrations**, then the three-dot menu (top right), then
   **Custom repositories**.
3. Paste `https://github.com/traktore-org/sem-community` into the URL field,
   set category to **Integration**, and click **Add**.
4. Close the dialog and search for **Solar Energy Management** in the list.
5. Click the result, then **Download** at the bottom right.
6. When the download finishes, go to **Settings > System > Restart** and
   restart Home Assistant. Wait 30-60 seconds for it to come back.

After the restart, SEM is installed. It will not do anything until you add and
configure it in the next step.

### Dashboard frontend cards

The SEM dashboard uses several HACS frontend cards. Install these via
**HACS > Frontend** if they are not already present. The most critical ones
are `card-mod`, `Mushroom`, `apexcharts-card`, `sankey-chart`,
`power-flow-card-plus`, and `bar-card`. See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md)
for the full list and troubleshooting steps when cards show "Custom element
doesn't exist".

---

## 3. Configuration: the Config Flow

Once SEM is installed, add it via **Settings > Devices & Services >
+ Add Integration**, search for **Solar Energy Management**, and select it.

The config flow has four steps. You can always change any setting later via
the **Configure** button on the integration card.

![SEM integration detail page](images/sem_integration_detail.png)

### Step 1: Energy Dashboard detection

SEM scans your Energy Dashboard and lists the sensors it found:

- Solar production sensor(s)
- Grid import and export sensors
- Battery charge and discharge sensors (if present)

If SEM finds your sensors, it shows a confirmation screen. Review the list and
confirm. If something is wrong (for example, the wrong solar sensor was
detected), configure your Energy Dashboard first, then come back.

**Observer mode** is available on this screen. Enable it if you want SEM to
read data and provide the dashboard without sending any commands to your
hardware. Observer mode is useful for:

- Testing SEM before giving it control
- Running a second HA instance that should not interfere with the first
- Households where automation control is not wanted

You can toggle observer mode at any time via
`switch.sem_observer_mode` without reconfiguring.

### Step 2: EV charger (optional)

If you have an EV charger, this step configures how SEM controls it.

| Field | What to set |
|-------|------------|
| Connected sensor | A binary sensor that is `on` when the car is plugged in |
| Charging sensor | A binary sensor that is `on` during active charging |
| Charging power sensor | A power sensor in watts |
| Control type | Service (KEBA, Easee, Zaptec) or number entity (all others) |
| Charger service or entity | The HA service or number entity that sets current |
| Min current | Lowest usable current (typically 6A, ~4140W on 3-phase) |
| Max current | Highest safe current (typically 16A or 32A) |
| Number of phases | 1 or 3 |

**Service-based control** (KEBA, Easee, Zaptec): SEM calls an HA service like
`keba.set_current` to change the charging current. The service and its
parameters are preset per brand.

**Number entity control** (Wallbox, go-eCharger, Heidelberg, etc.): SEM writes
a value to a number entity in HA that represents the current limit. SEM
auto-detects whether the entity expects amps or kilowatts.

If you do not have an EV charger, skip this step. You can add one later via
the **Configure** button on the integration page without reinstalling.

### Step 3: Notifications (optional)

| Option | What it does |
|--------|-------------|
| KEBA display | Shows charging status messages on the KEBA charger's built-in screen |
| Mobile push | Sends alerts to the HA Companion App on your phone |

Push notifications cover: battery nearly full, daily energy summary, EV nearly
full, smart charge recommendation, and forecast-based charge alerts. All
notification text is translated to your language automatically.

### Step 4: Hardware and dashboard settings

This step sets the operational parameters and triggers dashboard generation.

| Setting | Default | Why it exists |
|---------|---------|---------------|
| Grid peak limit (W) | 0 (disabled) | Your utility's peak demand threshold. SEM sheds loads to stay under this. Set to 0 to disable peak management. |
| Update interval (s) | 10 | How often SEM reads sensors and adjusts devices. Lower values are more responsive but use more CPU. Values below 5 are not recommended. |
| Generate dashboard | On | Creates the SEM dashboard in your sidebar. Disable only if you want to build your own dashboard using SEM sensors. |
| Solar forecast integration | None | If you have Solcast or Forecast.Solar, select it here. SEM uses forecasts for smarter night charging and the "best surplus window" sensor. |

Click **Submit** to finish. SEM starts running immediately. If dashboard
generation was enabled, the SEM dashboard appears in your sidebar within a few
seconds.

---

## 4. Verification

After setup, spend two minutes confirming that SEM is reading your sensors
correctly. Problems caught early are much easier to fix.

### Check sensor values

Go to **Developer Tools > States** (the wrench icon in the sidebar).

![Developer Tools States view](images/sem_developer_tools_states.png)

Search for these sensors and confirm they show numeric values (not
"unavailable" or "unknown"):

| Sensor | Expected value |
|--------|---------------|
| `sensor.sem_solar_power` | Watts, >= 0 |
| `sensor.sem_grid_power` | Watts, positive = export, negative = import |
| `sensor.sem_home_consumption_power` | Watts, >= 0 |
| `sensor.sem_battery_power` | Watts if battery present, else unavailable |

If any sensor shows "unavailable", the most common cause is that your Energy
Dashboard does not have the corresponding sensor type assigned. Go back to
**Settings > Dashboards > Energy** and check.

### Check the dashboard

Open the **SEM** dashboard from your sidebar and look at the Home tab.

![SEM Home tab with system diagram](images/sem_home_tab.png)

The animated system diagram should show flows between the components you have
(solar, grid, battery, home, EV). If a component you have is missing, its
sensors were not detected — check the Energy Dashboard configuration.

If cards show "Custom element doesn't exist", a required HACS frontend card is
missing. See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for the full list.

### Run the services check

Go to **Developer Tools > Actions**.

![Developer Tools Actions view](images/sem_developer_tools_services.png)

Search for `solar_energy_management` to see all available SEM services. If
none appear, the integration did not load correctly — check **Settings >
System > Logs** and filter for `solar_energy_management`.

---

## 5. Fine-tuning via the Options Flow

Once SEM is running, open **Settings > Devices & Services**, find the SEM
card, and click **Configure** to adjust any setting without reinstalling.

### What each setting does

| Setting | Default | Description |
|---------|---------|-------------|
| `update_interval` | 10 s | Coordinator polling interval. Controls how quickly SEM responds to changes. |
| `peak_limit_w` | 0 | Grid peak limit in watts. SEM sheds loads (lowest priority first) to stay below this. 0 = disabled. |
| `min_solar_power_w` | 500 | Minimum solar surplus (watts) before SEM starts solar-driven EV charging. Below this, the surplus is too small to be worth using. |
| `ev_daily_target_kwh` | 10 | How much the EV should charge overnight. SEM schedules night charging to hit this target using the cheapest available hours. |
| `battery_priority_soc` | 30% | Zone 1/2 boundary. Below this, all solar goes to the battery and the EV is blocked. |
| `battery_buffer_soc` | 70% | Zone 2/3 boundary. Above this, the battery can discharge to help charge the EV. |
| `battery_auto_start_soc` | 90% | Zone 3/4 boundary. Above this, the EV starts even without solar surplus. |
| `battery_assist_floor_soc` | 60% | Hysteresis floor. Once battery assist activates, it stays active until SOC drops here. Prevents cycling. |
| `battery_assist_max_power` | 4500 W | Maximum battery discharge power available for EV charging. |
| `night_charging_enabled` | On | Enables overnight grid-to-EV charging toward the daily target. |
| `smart_night_charging` | Off | When on, SEM evaluates SOC, forecast, and battery state before scheduling night charging. It may skip or reduce the charge if tomorrow's solar looks sufficient. |
| `battery_charge_scheduler` | Off | Forecast-aware grid-to-battery charging during cheap night hours. Requires a forecast integration and a battery inverter with charging control (Huawei SUN2000, SMA, Victron). |
| `observer_mode` | Off | Read-only mode. SEM monitors and reports but sends no commands. |

### Switches you can use in automations

| Switch | Purpose |
|--------|---------|
| `switch.sem_night_charging` | Enable or disable overnight EV charging on a schedule |
| `switch.sem_observer_mode` | Toggle read-only mode without opening the config flow |
| `switch.sem_smart_night_charging` | Toggle forecast-aware night charge evaluation |

### Regenerating the dashboard

If you change hardware or reinstall, run the dashboard generator via
**Developer Tools > Actions > solar_energy_management.generate_dashboard**.
The generator rebuilds the dashboard from scratch and detects your current
hardware. It is safe to run at any time.

---

## 6. SOC Zone Strategy

When a battery is present, SEM uses a four-zone model to decide how to share
solar energy between the battery and the EV. The zones are defined by three
SOC thresholds you can adjust in the options flow.

```
SOC 100% ─────────────────────────────
         |  Zone 4: FULL ASSIST       |  Battery assist always on
SOC 90%  ─── battery_auto_start_soc ──
         |  Zone 3: DISCHARGE ASSIST  |  Proportional battery assist
SOC 70%  ─── battery_buffer_soc ──────
         |  Zone 2: SURPLUS ONLY      |  EV gets pure solar surplus only
SOC 30%  ─── battery_priority_soc ────
         |  Zone 1: BATTERY PRIORITY  |  All solar to battery, EV blocked
SOC  0%  ─────────────────────────────
```

**Zone 1 — Battery Priority** (SOC below 30%): Battery is low. All solar goes
to the battery; the EV is blocked. Protects battery longevity.

**Zone 2 — Surplus Only** (SOC 30–70%): Battery is healthy. The EV charges
from pure surplus (power that would otherwise be exported). Battery does not
discharge for EV.

**Zone 3 — Discharge Assist** (SOC 70–90%): Battery supplements solar for EV.
Assist ramps from 50% of `battery_assist_max_power` at SOC 70% to 100% at
SOC 90%. Graduated to avoid wasting battery on days solar alone is sufficient.

**Zone 4 — Full Assist** (SOC above 90%): Full battery assist active. EV
starts even without solar surplus — a nearly full battery has little to lose.

**Hysteresis**: Once assist activates, it stays on until SOC drops below
`battery_assist_floor_soc` (default 60%). Prevents rapid cycling.

### When to adjust zone thresholds

- **You want to protect the battery more**: raise `battery_priority_soc`
  (for example from 30% to 40%). The battery will fill further before the EV
  gets any solar.
- **Your battery degrades quickly**: lower `battery_buffer_soc` so the battery
  discharges less for EV.
- **You rarely have solar surplus**: lower `battery_auto_start_soc` so Zone 4
  activates sooner and the EV charges more from battery power.
- **You see rapid on/off cycling**: raise `battery_assist_floor_soc` to
  increase hysteresis.

---

## 7. Language Support

SEM supports 15 languages: English, German, Dutch, French, Spanish, Italian,
Portuguese, Polish, Swedish, Czech, Danish, Finnish, Hungarian, Romanian, and
Norwegian.

Translation works in two layers:

1. **Dashboard labels** are translated when the dashboard is generated, using
   the language configured in **Settings > General** (server language).
2. **Custom card text** (the SEM system diagram, title cards, charger status
   card, and period selector) is translated at runtime based on each user's
   own language setting, found at your user profile icon > **Language**.

This means users with different language preferences on the same HA instance
each see the SEM dashboard in their own language.

![Language setting in HA user profile](images/sem_settings_language.png)

To change the dashboard server language, change the language in
**Settings > General**, then re-run
`solar_energy_management.generate_dashboard` to rebuild the dashboard in the
new language. Custom cards update immediately without regeneration.

See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for more on the translation
architecture and how to contribute translations.

---

## 8. FAQ

**Q: Do I need a battery to use SEM?**

No. SEM works with solar and grid sensors only. A battery adds the SOC zone
strategy and battery-assisted EV charging, but the full dashboard, cost
tracking, and surplus control work without one.

**Q: Do I need an EV charger?**

No. Without an EV charger, SEM tracks energy flows, costs, savings, and
surplus — and provides the complete dashboard. EV features are inactive, but
nothing breaks. You can add a charger later via **Configure** without
reinstalling.

**Q: My sensors show "unavailable" after installing SEM.**

SEM reads source sensors from the Energy Dashboard. If the Energy Dashboard
was not configured before installing SEM, or if your inverter integration is
offline, SEM sensors will also be unavailable. Check that your inverter is
online, verify that **Settings > Dashboards > Energy** has sensors assigned,
and review logs at **Settings > System > Logs** (filter for
`solar_energy_management`).

**Q: Can I change settings after the initial setup?**

Yes. Go to **Settings > Devices & Services > Solar Energy Management**, click
**Configure**, and change any setting. No reinstall is needed and changes take
effect within one coordinator cycle (default 10 seconds).

**Q: SEM sent a command to a device I did not want it to touch.**

Change that device's control mode to `off` via
`solar_energy_management.update_device_config`. In `off` mode SEM monitors
but never activates the device. Use `peak_only` if you want SEM to shed the
device during grid peaks but never turn it on autonomously.

**Q: I have two HA instances. How do I prevent them from conflicting?**

Enable **Observer Mode** on the secondary instance. Both instances can safely
read sensors simultaneously. Toggle via `switch.sem_observer_mode` or the
**Configure** screen — no reinstall needed.

**Q: How does SEM know which direction my grid power sensor reads?**

SEM compares your grid sensor's sign against the Energy Dashboard import/export
counters at startup and applies a correction if needed. This works for all
brands — including those where positive means import (Fronius, SolarEdge) and
those where positive means export (Huawei, SMA).

**Q: Will SEM drain my battery to charge the EV?**

Only when the battery SOC is in Zone 3 (above 70%) or Zone 4 (above 90%).
Below 70%, the EV gets only pure solar surplus and the battery does not
discharge for it. Below 30%, all solar goes to the battery and the EV gets
nothing. See the [SOC Zone Strategy](#6-soc-zone-strategy) section above for
the full logic.

**Q: What is smart night charging and should I enable it?**

Smart night charging evaluates whether tonight's grid charge is necessary. If
tomorrow's solar forecast is strong and the battery is reasonably full, SEM
may skip or reduce the night charge — saving money on grid electricity.
Enable it after SEM has been running for at least a week. It is off by default
because it requires a calibrated forecast integration to work well.

**Q: How long until SEM predictions are accurate?**

- Days 1-2: rough estimates, surplus window recommendations imprecise
- Days 3-7: reasonable hourly predictions, surplus window useful
- After 2 weeks: well-calibrated to weekday and weekend patterns

No configuration needed — the predictor trains itself automatically.

**Q: Why do daily energy values reset at sunrise instead of midnight?**

Overnight EV charging sessions (for example, 22:00 to 06:00) span midnight.
Resetting at sunrise keeps the entire charging session in a single daily
bucket, giving more accurate daily totals for cost and energy tracking.

---

## Getting Help

**Logs:** Enable debug logging by adding this to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.solar_energy_management: debug
```

Then view logs at **Settings > System > Logs** and filter for
`solar_energy_management`.

**Common issues:** See [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for a
symptom-by-symptom guide to the most frequent problems.

**Dashboard problems:** See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for
card-by-card troubleshooting.

**Multi-device setups:** See [MULTI_DEVICE_GUIDE.md](MULTI_DEVICE_GUIDE.md)
for inverter summing, multi-charger priority configuration, and split-grid
setups.
