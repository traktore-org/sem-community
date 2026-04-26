# Known Limitations

## Energy Dashboard dependency

SEM reads solar, grid, and battery sensors from the **HA Energy Dashboard** configuration (`.storage/energy`). The Energy Dashboard must be configured with at least solar and grid sensors before SEM can be set up.

## Single instance only

Only one SEM config entry is supported per Home Assistant instance. Creating a second entry will be rejected during the config flow.

## EV charger requirements

The EV charger must be controllable via a supported HA integration (KEBA, Easee, go-eCharger, Wallbox, Zaptec, ChargePoint, Heidelberg, OpenWB, OCPP-compatible, Ohme, Peblar, V2C Trydan, Alfen Eve, Blue Current, OpenEVSE) or through a generic `number` entity for current control. Manual configuration of entity IDs is required if the charger is not auto-detected.

## Battery discharge protection

Battery discharge protection during night charging requires a Huawei Solar inverter (or compatible) that exposes a `number` entity for the battery discharge power limit. Other inverters without this entity cannot use this feature.

## Sunrise-based meter day

Daily energy totals reset at **sunrise**, not at midnight. This is intentional — it keeps night charging sessions (22:00-06:00) in a single daily bucket. However, it means daily totals may not align with utility billing periods that reset at midnight.

## Financial tracking

Cost tracking uses either statically configured rates (HT/NT) or a dynamic tariff entity (Tibber, Nordpool, aWATTar). There is no automatic rate detection from utility providers. Export (feed-in) rates must be manually configured.

## Solar forecast

Forecast-based features (charging recommendations, battery-assist decisions) require **Solcast PV Solar** (HACS) or **Forecast.Solar** (built-in) to be installed and configured separately. Without a forecast integration, these features are disabled.

## Peak load management

Peak load management requires controllable devices with switch entities for shedding. Devices without a discoverable switch entity must be configured manually. The 15-minute rolling average calculation starts fresh after each HA restart.

## Charger Limitations

Some EV chargers have limitations that prevent full SEM control:

- **Tesla Wall Connector** — monitoring-only. The Wall Connector does not expose a power sensor or current control entity in Home Assistant. SEM can read voltage/current but cannot control charging.
- **Myenergi Zappi** — the Zappi has built-in solar diversion logic that conflicts with external surplus control. SEM can monitor the Zappi but cannot control charging current — the Zappi manages surplus charging internally.
- **KSTAR inverters** — no dedicated HA integration exists. Use [ha-solarman](https://github.com/davidrapan/ha-solarman) with KSTAR YAML profiles for inverter/battery support.
- **Easee** — the power sensor is disabled by default in the HA Easee integration. It must be manually enabled in **Settings > Devices > Easee** before SEM can detect and configure the charger.

## Heat pump SG-Ready control

The `HeatPumpController` device class exists in the codebase and supports SG-Ready 4-state control, but it is **not yet wired up** as a registered device controller. The corresponding dashboard cards have been removed from the dashboard template. The controller logic is functional but not instantiated or registered with the surplus controller. This will be connected in a future release.

## EV Intelligence

- **Virtual SOC accuracy** — depends on taper detection or car API calibration for the initial anchor. Without either, the SOC estimate drifts over time based solely on energy tracking and predicted consumption.
- **Consumption predictor cold start** — needs at least 3 days of data before per-weekday predictions are useful. During the first 3 days, a conservative default is used.
- **Temperature correction** — requires an outdoor temperature sensor (auto-detected from a `weather.*` entity). Without it, temperature correction is disabled and predictions assume 20°C.
- **Battery health tracking** — requires multiple charge sessions over weeks/months to produce meaningful estimates. Short-term values may fluctuate.

## Multi-device aggregation

SEM supports multiple solar inverters, battery units, and grid tariff entries from the HA Energy Dashboard (v1.3.0+). Limitations:
- **Battery SOC** is averaged across units — if batteries have very different capacities, the average may not reflect the true combined state accurately.
- **Grid power sensors** — if multiple grid power sensors exist, they are summed. Ensure they don't overlap (e.g., don't add both a sub-meter and a main meter).

## Multi-phase EV charging

SEM assumes 3-phase charging at 230V per phase by default. Single-phase or 2-phase configurations must be set via the integration options. Incorrect phase configuration will result in inaccurate current calculations.
