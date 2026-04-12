<p align="center">
  <img src="../brand/icon@2x.png" alt="SEM Logo" width="120">
</p>

# Getting Started with SEM

SEM turns your solar panels, battery, and EV charger into one intelligent system. Setup takes about 5 minutes.

---

## What You Need

- **Home Assistant 2025.3+**
- **HA Energy Dashboard** configured — SEM reads your sensors from it
  - Go to **Settings > Dashboards > Energy** and add solar + grid sensors
- **EV charger** with HA integration (KEBA, Wallbox, go-eCharger, Easee)
- **HACS frontend cards**: `mushroom` and `apexcharts-card`

---

## Step 1: Install

### Via HACS (Recommended)
1. **HACS** > **Integrations** > 3-dot menu > **Custom repositories**
2. Add: `https://github.com/traktore-org/sem-community` → Category: **Integration**
3. Search **Solar Energy Management** > **Download**
4. **Restart Home Assistant**

### Manual
1. Download from [Releases](https://github.com/traktore-org/sem-community/releases)
2. Copy to `config/custom_components/solar_energy_management/`
3. **Restart Home Assistant**

---

## Step 2: Install Dashboard Cards

Install via **HACS > Frontend**:

| Card | Why |
|------|-----|
| **mushroom** | Status chips, entity cards |
| **apexcharts-card** | Power and energy charts |

Hard-refresh your browser after installing (Ctrl+Shift+R).

---

## Step 3: Setup Wizard

Go to **Settings** > **Devices & Services** > **Add Integration** > **Solar Energy Management**

### 3a: Sensor Detection
SEM reads your HA Energy Dashboard and shows a summary of detected sensors. Toggle **Observer Mode** if you want monitoring only (no hardware control). Click **Submit**.

### 3b: EV Charger
Select your charger's connected, charging, and power sensors. Click **Submit**.

### 3c: Hardware
Set your **battery capacity** (kWh) and **peak limit** (kW). Leave dashboard generation ON. Click **Submit**.

That's it — SEM starts optimizing immediately.

---

## Step 4: Restart

Restart HA once so the dashboard URL registers:

**Settings** > **System** > **Restart**

The **Solar Energy Management** dashboard appears in the sidebar.

---

## What Happens Next

Once installed, SEM works automatically:

| Time of Day | What SEM Does |
|-------------|--------------|
| **Morning** | Monitors rising solar production |
| **Midday** | Adjusts EV charging current to match solar surplus (6-32A) |
| **Clouds** | Pauses EV charging, resumes when sun returns |
| **Battery full** | Routes all surplus to EV and other devices |
| **Evening** | Solar charging stops naturally |
| **Night** | Grid-charges EV to daily target (if night charging is ON) |
| **Smart night** | Reduces night charge when tomorrow's forecast is sunny |

### Your Only Controls
| Switch | Default | Purpose |
|--------|---------|---------|
| Night Charging | ON | Grid-charge EV overnight |
| Observer Mode | OFF | Read-only (no hardware control) |
| Forecast Reduction | OFF | Smart night charge reduction |

Everything else — solar tracking, battery coordination, peak management — is fully automatic.

---

## Tuning (Optional)

SEM works with defaults. To fine-tune:

**Settings > Devices & Services > Solar Energy Management > Configure**

Key settings:
- **SOC Zones** — when battery vs EV gets priority
- **Daily EV Target** — how many kWh to charge at night
- **Peak Limit** — your grid contract limit for demand charges
- **Tariff Rates** — import/export price for accurate cost tracking

---

## Next Steps

- [Dashboard Guide](DASHBOARD_GUIDE.md) — what each tab shows
- [User Guide](../USER_GUIDE.md) — all features explained
- [Troubleshooting](../TROUBLESHOOTING.md) — common fixes
