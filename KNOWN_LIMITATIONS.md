# Known Limitations

## Energy Dashboard dependency

SEM reads solar, grid, and battery sensors from the **HA Energy Dashboard** configuration (`.storage/energy`). The Energy Dashboard must be configured with at least solar and grid sensors before SEM can be set up.

## Single instance only

Only one SEM config entry is supported per Home Assistant instance. Creating a second entry will be rejected during the config flow.

## EV charger requirements

The EV charger must be controllable via a supported HA integration (KEBA, Easee, go-eCharger, Wallbox, OpenWB) or through a generic `number` entity for current control. Manual configuration of entity IDs is required if the charger is not auto-detected.

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

## Multi-phase EV charging

SEM assumes 3-phase charging at 230V per phase by default. Single-phase or 2-phase configurations must be set via the integration options. Incorrect phase configuration will result in inaccurate current calculations.
