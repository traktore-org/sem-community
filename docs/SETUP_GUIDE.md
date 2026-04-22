# SEM Setup Guide

A beginner-friendly, step-by-step guide to installing and configuring
Solar Energy Management (SEM) in Home Assistant.

If you have never installed a custom integration before, this guide is for you.

---

## Before You Start -- Checklist

Make sure you have the following ready before you begin:

- [ ] **Home Assistant 2024.1.0 or newer** running and accessible
- [ ] **HACS installed** -- the Home Assistant Community Store.
      If you do not have HACS yet, follow the official instructions at
      <https://hacs.xyz/docs/use/>
- [ ] **At least one solar inverter** connected to HA with power sensors
      (Huawei, SolarEdge, Fronius, Growatt, or any brand that exposes
      watt-level sensors in HA)
- [ ] **A grid power or energy sensor** visible in HA (often provided by
      the same inverter integration or a smart meter like Shelly EM)
- [ ] **The HA Energy Dashboard configured** with at least a solar
      production sensor and a grid consumption sensor
      (Settings > Dashboards > Energy)
- [ ] *(Optional)* A battery with SOC and power sensors
- [ ] *(Optional)* An EV charger controllable via HA (KEBA, Wallbox,
      go-eCharger, Easee, Zaptec, ChargePoint, Heidelberg, OpenWB 2.x, etc.)
- [ ] *(Optional)* A solar forecast integration -- Solcast or Forecast.Solar

> **Note:** Easee's power sensor is disabled by default in HA. Enable it in **Settings > Devices > Easee** before installing SEM.

If you are unsure whether your Energy Dashboard is set up, go to
**Settings > Dashboards > Energy**. You should see at least "Solar panels"
and "Grid consumption" sections with sensors assigned.

---

## Step 1 -- Install SEM via HACS

1. Open Home Assistant in your browser.
2. In the sidebar, click **HACS**.
3. Click the **Integrations** tab.
4. Click the three-dot menu (top right) and select **Custom repositories**.
5. Paste the repository URL:
   `https://github.com/traktore-org/sem-community`
6. Set the category to **Integration** and click **Add**.
7. Close the dialog. Search for **Solar Energy Management** in the
   HACS integrations list.
8. Click the result, then click **Download** (bottom right).
9. **Restart Home Assistant** -- go to **Settings > System > Restart**
   and confirm. Wait about 30-60 seconds for HA to come back.

After the restart, SEM is installed but not yet configured.

---

## Step 2 -- Add the Integration

1. Go to **Settings > Devices & Services**.
2. Click **+ Add Integration** (bottom right).
3. Search for **Solar Energy Management** and select it.

This starts the configuration wizard (called the "config flow").

---

## Step 3 -- Walk Through the Config Flow

The wizard has several steps. You do not need to fill in everything --
most settings have sensible defaults. Here is what each step asks for:

### 3a. Energy Dashboard Detection

SEM automatically reads your solar, grid, and battery sensors from the
HA Energy Dashboard. If it finds them, it shows a confirmation screen.

If it cannot find them, it will ask you to configure the Energy Dashboard
first. Go to **Settings > Dashboards > Energy**, add your sensors there,
then come back and try adding SEM again.

### 3b. EV Charger (Optional)

If you have an EV charger, select the following sensors:

- **Connected sensor** -- a binary sensor that shows "on" when the car
  is plugged in
- **Charging sensor** -- a binary sensor that shows "on" during active
  charging
- **Charging power sensor** -- a power sensor in watts
- **Charger service** -- the HA service that sets current (for example,
  `keba.set_current`)

If you do not have an EV charger, skip this step. You can add one later
via **Configure** on the integration page.

### 3c. Notifications (Optional)

- **KEBA display** -- shows charging status on the charger's screen
- **Mobile push** -- sends alerts via the HA Companion App

### 3d. Optimization Settings

These control how SEM manages your energy. The defaults work well for
most systems:

| Setting | Default | What it means |
|---------|---------|---------------|
| Update interval | 10 seconds | How often SEM checks sensors and adjusts |
| Daily EV target | 10 kWh | How much to charge the EV overnight |
| Battery priority SOC | 30% | Below this, all solar goes to the battery |
| Min solar power | 500 W | Minimum surplus before solar EV charging starts |

You can change any of these later without reinstalling.

### 3e. Dashboard Generation

The final step asks whether to generate the SEM dashboard. Leave this
**enabled** (it is on by default). The dashboard appears in your sidebar
within a few seconds.

Click **Submit** to finish.

---

## Step 4 -- Verify the Energy Dashboard Setup

After adding SEM, go to **Settings > Dashboards > Energy** and confirm
that SEM has detected your sensors correctly:

1. Open **Developer Tools > States** in the sidebar.
2. Search for `sensor.sem_solar_power` -- it should show a numeric value
   (in watts).
3. Search for `sensor.sem_grid_power` -- also a numeric value.
4. If either shows "unavailable", check that your inverter integration
   is online and the Energy Dashboard has the correct sensors assigned.

SEM automatically detects your grid and battery sensor sign conventions
(whether positive means import/export or charge/discharge). No manual
configuration is needed — this works with all inverter brands.

---

## Step 5 -- View Your Dashboard

1. Look in the sidebar for the **SEM** dashboard (or "Solar Energy
   Management").
2. Click it. You should see the **Home** tab with an animated system
   diagram showing your current solar production, grid, battery, and
   home consumption.

If the dashboard is missing, go to **Developer Tools > Actions**, search
for `solar_energy_management.generate_dashboard`, and run it.

If cards show "Custom element doesn't exist", you are missing some HACS
frontend cards. See the [Dashboard Guide](DASHBOARD_GUIDE.md) for the
full list of required cards (the most common missing ones are `card-mod`,
`mushroom`, and `bar-card`).

---

## Step 6 -- Install Required Dashboard Cards (if needed)

The SEM dashboard uses several community cards. Install these via HACS
if they are not already present:

1. Open **HACS > Frontend**.
2. Search for and install each of the following:
   - `card-mod`
   - `Mushroom`
   - `apexcharts-card`
   - `mini-graph-card`
   - `bar-card`
   - `sankey-chart`
   - `bubble-card`
3. Hard-refresh your browser after installing (Ctrl+Shift+R or
   Cmd+Shift+R on Mac).

---

## Understanding Device Control Modes

Every device SEM discovers gets a **control mode**. This tells SEM what
it is allowed to do with that device. There are three modes:

### Off

SEM watches the device but never touches it. Use this for devices you
want to monitor (like lights or a coffee machine) but never want SEM to
turn on or off.

### Peak Only (default)

SEM will **never turn the device on**, but it **can turn it off** if
your total power consumption approaches your grid peak limit. Think of
it as a safety net -- the device runs normally under your control, but
SEM can shed it to avoid a peak charge on your electricity bill.

### Surplus

SEM **actively controls** the device. It turns the device on when there
is enough solar surplus and turns it off when surplus drops. Use this
for devices like a hot water heater or pool pump that you want to run
on free solar power whenever possible.

**In short:**
- `off` = hands off
- `peak_only` = SEM can only turn it off in emergencies
- `surplus` = SEM fully manages on/off based on solar

You can change a device's mode at any time via the
`solar_energy_management.update_device_config` service. See the
[User Guide](../USER_GUIDE.md#device-control-modes) for details.

---

## Understanding the Predictor

SEM includes a built-in **consumption and solar predictor**. It learns
your household's energy patterns automatically -- no configuration
needed.

### What it does

- Learns your typical hourly consumption (separately for weekdays and
  weekends)
- Learns your typical hourly solar production
- Predicts next-hour consumption and solar power
- Estimates your total daily consumption
- Identifies the best surplus window ("run your dishwasher between
  11:00 and 14:00")

### How long until it is useful

The predictor uses an averaging algorithm that improves with data:

- **Day 1-2:** Predictions are rough estimates based on defaults. The
  "Smart Recommendations" on the Home tab may not be very accurate yet.
- **Day 3-7:** The predictor has seen enough patterns to give reasonable
  hourly predictions. Surplus window recommendations become useful.
- **After 2 weeks:** Predictions are well-calibrated to your household.
  Weekday and weekend patterns are distinct.

You do not need to do anything -- the predictor trains itself in the
background every update cycle. There is no "reset" button; it
continuously adapts to changes in your consumption habits.

---

## What Happens Next

Once SEM is running, it works automatically:

- **During the day**, it monitors solar production and distributes
  surplus to your devices by priority.
- **In the evening**, it can charge your EV from the grid at a managed
  rate (if night charging is enabled).
- **All day**, it tracks energy flows, costs, savings, and performance
  metrics across 60+ sensors.

The three switches you might want to adjust:

| Switch | Default | Purpose |
|--------|---------|---------|
| `switch.sem_night_charging` | ON | Enable/disable overnight EV charging |
| `switch.sem_observer_mode` | OFF | Read-only mode (no hardware control) |
| `switch.sem_forecast_night_reduction` | OFF | Reduce night charging based on tomorrow's forecast |

Everything else is automatic.

---

## FAQ

**Q: Do I need a battery to use SEM?**
No. SEM works with solar and grid only. A battery adds more optimization
options (like battery-assisted EV charging), but it is not required.

**Q: Do I need an EV charger?**
No. Without an EV charger, SEM still tracks your energy production,
consumption, flows, costs, and provides the full dashboard. EV features
are simply inactive.

**Q: My sensors show "unavailable" after installing SEM.**
Check that your Energy Dashboard is configured (Settings > Dashboards >
Energy) and that your inverter integration is online. SEM reads its
source sensors from the Energy Dashboard -- if those are down, SEM
sensors will also be unavailable. See [Troubleshooting](../TROUBLESHOOTING.md)
for more details.

**Q: Can I change settings after the initial setup?**
Yes. Go to **Settings > Devices & Services > Solar Energy Management**,
click **Configure**, and change any setting. No reinstall needed.

**Q: SEM is controlling a device I do not want it to touch.**
Change that device's control mode to `off`. See the "Device Control
Modes" section above.

**Q: I have two HA instances (production and test). Is that safe?**
Enable **Observer Mode** on the test instance so it does not send
commands to your hardware. Both instances can read sensors safely.

**Q: How does SEM know which direction grid power flows?**
SEM compares your grid power sensor's sign against the import/export
energy counters from the Energy Dashboard. It detects the convention
automatically after startup, so it works with all inverter brands.

**Q: Will SEM drain my battery to charge the EV?**
Only if the battery SOC is above the buffer threshold (default 70%).
Below that, the EV gets only pure solar surplus. Below 30%, all solar
goes to the battery and the EV waits entirely. See the
[User Guide -- SOC Zones](../USER_GUIDE.md#soc-zone-strategy) for the
full explanation.

**Q: Why do daily energy values reset at sunrise instead of midnight?**
So that overnight EV charging sessions (for example, 22:00 to 06:00)
stay in a single daily bucket. This gives more accurate daily totals.

**Q: Where can I learn about advanced features?**
See the [User Guide](../USER_GUIDE.md) for the complete reference on
all settings, charging modes, SOC zones, tariff integration, surplus
distribution, and more.

---

## Getting Help

- Check the [Troubleshooting Guide](../TROUBLESHOOTING.md) for common
  issues and fixes
- Enable debug logging by adding this to your `configuration.yaml`:
  ```yaml
  logger:
    logs:
      custom_components.solar_energy_management: debug
  ```
- Review HA logs at **Settings > System > Logs** and filter for
  `solar_energy_management`
