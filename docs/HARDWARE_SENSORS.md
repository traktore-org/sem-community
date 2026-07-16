# Hardware sensors — what SEM expects, and how to help it

SEM is **autodetect-first**: for most hardware it finds the right sensors on its own from
your Home Assistant **Energy Dashboard** and the device registry. This guide is for the rest —
so if a value reads `0`, `unavailable`, or looks wrong, you can see **what SEM expects** and
**which override to set**. Every override lives on the **dashboard** (SEM Config card /
`solar_energy_management.set_option`) — there is no config-flow field to hunt for.

## The resolution order (every signal)

1. **Autodetect** — brand/name keywords + a scan of the sensor's device for a companion sensor.
2. **Derive** — compute power from an energy (kWh) counter when no power sensor exists.
3. **Manual override** — the escape hatch below, when 1–2 miss.

If you find yourself setting an override, that's a signal our autodetect missed your hardware —
tell us the brand + the sensor's `entity_id` on the issue tracker and we'll add it to the
autodetect map so the next person gets it for free.

## What SEM needs per signal

| Signal | Unit / convention | Autodetect | Manual override (dashboard) |
|---|---|---|---|
| **Solar power** | W, ≥ 0 | Energy-Dashboard solar power; else a `pv_power`/`solar_power`/`production_power` sensor on the solar device | **Solar power sensor** (`solar_production_sensor`) |
| **Grid power** | W, − = import, + = export | Energy-Dashboard grid power; split import/export supported | **Grid import / export** sensors |
| **Battery power** | W, − = discharge, + = charge | `battery_power` / `charge_discharge_power` / `lade_entladeleistung` (EN+DE) on the battery device | **Battery power sensor** (`battery_power_sensor`) |
| **Battery SOC** | %, 0–100 | `soc` / `state_of_charge` / `batterieladung`, or device_class `battery` + `%` | **Battery SOC sensor** (`battery_soc_sensor`) |
| **Battery cycles** | count | `cycles` / `zyklen` / `ladezyklen` / `full_cycles` on the battery device | **Battery cycles sensor** (`battery_cycles_sensor`) — else SEM estimates from throughput |
| **Load device power** (heat pump / hot water / switch) | W, ≥ 0 | a companion power sensor on the device | **…power sensor**, or a **kWh energy sensor** (SEM derives power) |

## Notes per hardware

- **Huawei (SUN2000 / LUNA2000):** fully autodetected. The combined battery power sensor is
  named `…_charge_discharge_power` (EN) or `…_lade_entladeleistung` (DE). LUNA2000 exposes no
  lifetime-cycle sensor, so SEM uses its throughput estimate for cycles.
- **SolarEdge + energy-only setups:** if your Energy Dashboard has solar/battery **energy**
  (kWh) but no **power** (W) sensor, live power reads 0 and Home consumption clamps to 0. Set
  the **Solar power sensor** (and **Battery power sensor**) to your real power entities.
- **Sonnenbatterie:** SEM autodetects the battery power/SOC. For the true lifetime cycle count
  (the value on `my.sonnen.de`), set the **Battery cycles sensor** to the `…_cycles` entity from
  the `ha_sonnenbatterie` integration — SEM then shows it instead of its estimate.
- **Fronius / SolaX / GoodWe / Growatt / SMA / Victron / Powerwall / Kostal / Enphase / Sessy:**
  autodetected via the Energy Dashboard; see the split-grid / two-sensor battery patterns in the
  README supported-hardware list. If a battery power sign looks inverted, use **Fix battery sign**.
- **Viessmann ViCare (Vitocal heat pump / DHW):** the per-device meters are often cumulative
  **kWh** counters ("DHW/heating energy this year") with no power sensor. Point the heat pump /
  hot water device at its **energy sensor (kWh)** — SEM autodetects a companion power sensor if
  one exists, otherwise derives a smooth live-power signal from the counter (it divides each step
  by the real elapsed time, so a slow yearly counter never spikes).

## Still stuck?

Open a GitHub issue with: your inverter/battery brand, the sensor `entity_id`s you expect SEM to
use, and a **System Diagnostics** dump (`diag_ed_config` shows what SEM currently reads). That's
the input we extend the autodetect keyword-maps from.
