# Known Limitations

## Energy Dashboard dependency

SEM reads solar, grid, and battery sensors from the **HA Energy Dashboard** configuration (`.storage/energy`). The Energy Dashboard must be configured with at least solar and grid sensors before SEM can be set up.

## Single instance only

Only one SEM config entry is supported per Home Assistant instance. Creating a second entry will be rejected during the config flow.

## EV charger requirements

The EV charger must be controllable via a supported HA integration (KEBA, Easee, go-eCharger, Wallbox, Zaptec, ChargePoint, Heidelberg, OpenWB, OCPP-compatible, Ohme, Peblar, V2C Trydan, Alfen Eve, Blue Current, OpenEVSE) or through a generic `number` entity for current control. Manual configuration of entity IDs is required if the charger is not auto-detected.

## Battery discharge protection

Battery discharge protection requires a Huawei Solar inverter (or compatible) that exposes a `number` entity for the battery discharge power limit. Other inverters without this entity cannot have their discharge actively clamped.

## Solar Gate (battery → EV assist)

The **Solar Gate** (`battery_assist_min_surplus`, default 1200 W) decides how much *real solar surplus* must exist before the home battery is allowed to assist EV charging, in any mode (set 0 W to allow battery support everywhere, including overnight). Notes:
- The configurable range is **0–5000 W**, so on a very large PV array you cannot require *more* than 5 kW of surplus before the battery assists.
- The discharge clamp it drives is a hard limit only on inverters that expose a discharge-power `number` entity (see above); on others the gate still governs SEM's *requested* amps but cannot physically cap the inverter's discharge.

## Battery → grid export arbitrage (disabled in this stable)

Battery → grid export arbitrage (selling stored energy to the grid when the dynamic export price beats the recharge cost) is implemented but **deactivated in v1.7.3 stable** pending more review and soak (#533; still deactivated as of v1.7.5 — re-evaluation planned for a later v1.7.x release). The per-battery modes and code remain, but the arbitrage opt-in is hidden in the UI.

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

SEM supports SG-Ready heat pump control via two relay entities (Shelly, ESPHome, etc.). Configure relay 1 and relay 2 in the options flow under "Heat Pump (SG-Ready)". The heat pump is managed by the surplus controller — when solar surplus exceeds the heat pump's rated power, SEM switches to BOOST mode (SG-Ready state 3) and optionally raises the temperature setpoint. With very high surplus (configurable threshold, default 5000W), SEM switches to FORCE_ON mode (state 4).

**Requirements:** Two switch entities controlling the SG-Ready relay pins. Optionally a climate entity for temperature boost and a power sensor for consumption tracking.

## EV Intelligence

- **Virtual SOC accuracy** — depends on taper detection or car API calibration for the initial anchor. Without either, the SOC estimate drifts over time based solely on energy tracking and predicted consumption.
- **Consumption predictor cold start** — needs at least 3 days of data before per-weekday predictions are useful. During the first 3 days, a conservative default is used.
- **Temperature correction** — requires an outdoor temperature sensor (auto-detected from a `weather.*` entity). Without it, temperature correction is disabled and predictions assume 20°C.
- **Battery health tracking** — requires multiple charge sessions over weeks/months to produce meaningful estimates. Short-term values may fluctuate.

## One vehicle per charger

By design, SEM models **one car per charger** — the charger *is* the vehicle. All
vehicle-specific settings (SOC sensor, battery capacity, efficiency, and the SOC/% charge
targets) and the virtual-SOC estimate are stored per charger. Multiple chargers (one car
each) are fully supported; **two different cars sharing a single charger are not**.

If two cars share one charger, the SOC-based features (% target, virtual SOC, derived range)
will be inaccurate because the per-charger state can't represent two vehicles. The
**car-agnostic** features still work correctly for either car: use a **kWh** charge target
(not %), and taper detection still stops charging when the battery is full regardless of
which car is plugged in.

## Multi-device aggregation

SEM supports multiple solar inverters, battery units, and grid tariff entries from the HA Energy Dashboard (v1.3.0+). Limitations:
- **Battery SOC** is averaged across units — if batteries have very different capacities, the average may not reflect the true combined state accurately.
- **Grid power sensors** — if multiple grid power sensors exist, they are summed. Ensure they don't overlap (e.g., don't add both a sub-meter and a main meter).

## Multi-phase EV charging

SEM assumes 3-phase charging at 230V per phase by default. Single-phase or 2-phase configurations must be set via the integration options. Incorrect phase configuration will result in inaccurate current calculations.

## Charger plug-sensor reliability across HA restart (KEBA P30 confirmed)

SEM reads the upstream charger integration's plug sensor (e.g.
`binary_sensor.keba_p30_plug`) to know when the car is connected.
On a KEBA P30, that sensor has been observed reporting `off` for
extended periods (60+ minutes on 2026-05-29 PROD) across an HA
restart with a car continuously plugged in and actively charging.
This appears to be an upstream HA-integration / KEBA-firmware
interaction — the sensor lies; SEM trusts it.

Since v1.6.0, SEM applies a **physics defence**: if `ev_charging`
is True or `ev_power > 100 W`, SEM infers `ev_connected = True`
regardless of what the plug sensor says (current cannot flow
without a connection). A WARNING line in the log records each
inference so the underlying upstream issue stays visible. The
defence applies to every charger integration, not just KEBA.

If you see SEM logging `ev_connected inferred from physics: plug
sensor reported off but ev_power=XW`, the defence is active and
your charger integration's plug sensor is unreliable. The defence
is fully safe — if you DO unplug the car, both `ev_power` and
`ev_charging` will drop and SEM will correctly transition to
disconnected.

## Charger self-resume on plug-in (KEBA P30 confirmed)

KEBA P30 firmware remembers its last current setpoint across power
cycles. When an EV plugs in — or after certain internal events SEM
cannot observe — KEBA **self-starts** at the stored setpoint
completely independently of SEM. This was confirmed on a 2026-05-31
PROD soak where Charge mode was set to **Off** and the EV plugged in:
KEBA pulled 4.1 kW on its own while SEM correctly reported
"Solar mode - System ready" with 0 A commanded.

Since v1.6.5, SEM **mitigates** this by re-asserting the per-brand
disable service (e.g. `keba.disable`) every coordinator cycle (~10 s)
whenever the user-intent strategy is `"disabled"` (mode=Off) AND THIS
charger is drawing more than 500 W (handshake idle is 100–200 W; real
charging starts at 4140 W). The mitigation is **per-charger correct**
in multi-charger setups — only the off charger gets the disable
re-asserted; sibling chargers with active modes are untouched.

Worst-case unwanted draw is **bounded by the coordinator cycle period
(~10 s)**: KEBA can self-start, ramp for one cycle, then SEM catches
it on the next cycle and calls `keba.disable`. A WARNING line in the
log records each self-resume episode so the upstream behaviour stays
visible:

```
Charger <name> self-resumed while mode=off (drawing 4140W). Calling
stop_session() — will re-assert every cycle until ev_power drops
below 500W. (#315)
```

If you're concerned about even the bounded 10-s window — e.g. your
electricity tariff penalises any grid draw — simply **unplug** the EV
when not actively charging. Mitigation only fires when both Charge
mode is Off and the charger is plugged in; unplugged cables can't
self-start.

Other chargers (Wallbox, Easee, go-eCharger, OpenEVSE, …) generally
treat 0 A as "stop" rather than "minimum hold" and don't exhibit this
behaviour; SEM's `_set_current(0)` call is sufficient on those.
However, the v1.6.5 fix applies universally — if any charger
integration reports power draw > 500 W with Charge mode = Off, the
per-brand `stop_session()` mechanism fires regardless of firmware
specifics.

## Battery-assist mode may transiently attribute a small grid flow to the EV

When the EV is charging in `battery_assist` mode (Zone 4, home battery ≥ `battery_auto_start_soc`), SEM offers the EV a budget that includes the expected battery discharge contribution (up to `battery_assist_max_power`, default 4500 W). The EV's onboard charger ramps to that current effectively instantly, but the home battery — an LFP pack managed by the inverter's BMS — takes several seconds to ramp its discharge from 0 W to the requested level. During that ramp window, the grid backfills the gap.

SEM's proportional flow attribution (`coordinator/flow_calculator.py: calculate_power_flows`) splits the actual grid flow across EV and home loads by demand share, so during the battery-discharge ramp you may briefly see `sensor.sem_flow_grid_to_ev_power` rise to a few hundred watts even though SEM itself never asked the EV to pull from grid. **This is the physics of the ramp, not a bug**: it lasts a handful of cycles (≤ 30 s typically), and the daily integrated grid-to-EV figure usually stays under 5 % of the session total. The live sentinel `tests/live/test_solar_only_no_grid.sh` correctly only checks the strict grid-floor invariant for `solar_only` (where the canonical promise is "no grid at all"), and treats `battery_assist` grid flow as informational.

If you want strict no-grid-ever behaviour, choose `Self-consumption` or `PV` charging mode instead of `Auto`, or lower `battery_buffer_soc` so the assist band ends higher (the former `battery_assist_floor_soc` option was removed — assist potential is already 0 below the buffer).
