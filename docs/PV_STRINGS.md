# Per-PV-string visibility (v1.7.x)

Closes [#312](https://github.com/traktore-org/sem-community/issues/312).
Shipped in three phases — v1.7.0 (data) → v1.7.1 (cards) → v1.7.2
(docs + release polish).

## What you get

When your inverter exposes per-string sensors and the entity-registry
auto-discovery finds **≥ 2 strings**, SEM creates two new entities per
string:

```
sensor.sem_pv_string_pv1_power         # W,  MEASUREMENT
sensor.sem_pv_string_pv1_daily_energy  # kWh, TOTAL, daily-reset

sensor.sem_pv_string_pv2_power
sensor.sem_pv_string_pv2_daily_energy
                  …                    # up to pv4 (discovery cap)
```

Plot them in Lovelace, alert on them, or watch them on SEM's own
flow-style cards — when ≥ 2 strings are present the three flow
cards (`sem-flow-card`, `sem-solar-card`,
`sem-system-diagram-card`) auto-render a per-string chip strip:

```
[ PV1  5.20 kW ]  [ PV2  3.10 kW ]      ← chips above the main card content
   existing card body unchanged
```

Single-string installs are pixel-identical to v1.6.x — no new
entities, no card changes.

## Supported inverter brands

Auto-discovery is in `hardware_detection.discover_pv_strings_from_registry`
and recognises these entity naming patterns:

| Brand | Pattern matched |
|---|---|
| Huawei SUN2000 | `*_pv1_power`, `*_pv2_power`, … |
| GoodWe | `*_pv1_power`, … |
| Growatt | `*_pv1_power`, … |
| Kostal Plenticore | `*_pv1_power` and `*_dc1_power` (handles either layout) |
| Sungrow | `*_mppt1_power`, `*_mppt2_power`, … |
| Fronius | `*_dc_power_1`, `*_dc_power_2`, … |
| SolarEdge | `*_dc_power_1`, `*_dc_power_2`, … |
| Victron | `*_tracker_1_power`, `*_tracker_2_power`, … |
| Generic | `*_string_1_power`, `*_string_2_power`, … |

If your brand isn't on the list but uses one of those patterns,
discovery already works — no SEM code change needed. If it uses
a different pattern, file a [GitHub
issue](https://github.com/traktore-org/sem-community/issues) with
your entity IDs and we'll add the regex.

## V+I synthesis fallback

Some integrations expose per-string voltage and current but not
power directly — typically Modbus-based drivers. The most common
case in the SEM user base is **Huawei Solar Modbus** which
publishes `sensor.inverter_pv_1_spannung` (V) and
`sensor.inverter_pv_1_strom` (A) per string but no `pv_1_power`.

SEM handles this automatically. After the direct-power discovery
runs, a parallel `hardware_detection.discover_pv_string_vi_pairs`
walks the same registry looking for sibling V+I pairs matching:

| Quantity | Patterns matched |
|---|---|
| Voltage | `*_pvN_voltage`, `*_pvN_spannung`, `*_pvN_volt`, `*_mpptN_voltage`, `*_stringN_voltage` (and German equivalents) |
| Current | `*_pvN_current`, `*_pvN_strom`, `*_pvN_amp`, `*_mpptN_current`, `*_stringN_current` (and German equivalents) |

When a complete V+I pair is found for slot N, SEM multiplies
V × I at read time to synthesise the per-string watts.
Downstream consumers (cards, energy accumulator, sum invariant)
don't know which way the value was sourced.

**Conflict resolution**: when the same slot has BOTH a direct
power sensor AND a V+I pair, the direct power sensor wins.
It's a real measurement; the V+I synthesis is a computed
fallback, slightly less accurate because it doesn't include
the inverter's own MPPT-efficiency math.

## How discovery works

1. Discovery runs once at integration setup
   (`SEMCoordinator.async_initialize_energy_dashboard`).
2. The **seed entity** is your solar power source from the HA Energy
   Dashboard config (`energy_dashboard.solar_power`).
3. SEM walks the entity registry for sibling sensors — same
   `platform` (e.g. `huawei_solar`) and same `config_entry_id`
   as the seed.
4. Each sibling is matched against the inverter-brand regexes above.
5. Up to 4 matches are kept (the discovery cap matches the K-Flow
   card's slot count and covers every multi-string inverter we
   know about).

## What if I don't see my strings?

Check, in order:

1. **The seed exists** — does your HA Energy Dashboard configure a
   solar source? Discovery seeds from there. Settings →
   Dashboards → Energy → Solar production.
2. **The strings are in the same integration as the seed** — if
   you have e.g. a Huawei inverter as your solar source and a
   separate `sensor.solar_string_1_power` exposed by a manual
   template, the platform won't match and discovery skips.
3. **The pattern matches** — your entity ID should contain
   something like `pv1_power`, `mppt1_power`, `dc_power_1`,
   `tracker_1_power`, or `string_1_power`. Check the actual
   entity ID in HA's Developer Tools → States.
4. **You have at least 2** — `len < 2` is gated; a single-string
   install creates no per-string sensors.
5. **Discovery ran** — search `home-assistant.log` for
   `Per-PV-string discovery found N strings`. If you don't see
   the line, either the seed is missing or the Energy Dashboard
   integration loaded after SEM.

## Internals

| Component | Purpose | File |
|---|---|---|
| `PowerReadings.solar_power_per_string` | Per-cycle raw W from each string | `coordinator/types.py` |
| `EnergyFlows.per_string` | Daily kWh per string (integrated) | `coordinator/types.py` |
| `PowerFlows.solar_per_string` | Pass-through carrier readings → integrator | `coordinator/types.py` |
| `StringEnergy` dataclass | One field: `energy_kwh` | `coordinator/types.py` |
| `SensorReader.set_pv_strings` | Receives the discovery map at setup | `coordinator/sensor_reader.py` |
| `FlowCalculator._per_string_accumulators` | kWh accumulator + day rollover + snapshot | `coordinator/flow_calculator.py` |
| `discover_pv_strings_from_registry` | The actual entity-registry walk | `hardware_detection.py` |
| `semDiscoverPVStrings` | Card-side helper, reads SEM sensors | `dashboard/card/src/base/sem-shared.js` |

Sum invariant pinned in `tests/test_per_string_energy.py`:
`sum(solar_power_per_string.values()) ≈ solar_power` within rounding.

## Idle-string semantic

Once a string appears in the accumulator it **stays surfaced**
until day rollover (local midnight). A cloud shading one panel
array mid-day doesn't regress the user-visible counter to 0 —
the same semantic SEM uses for per-charger flows.

## What's NOT in scope (yet)

- Per-string-to-destination attribution
  ("PV1 → home, PV2 → battery") — strings are sources, the
  proportional split would be useful but the user only asked for
  per-string **visibility**. File an issue if you'd find this
  useful.
- Per-string cost / savings — SEM tracks fleet-level savings;
  per-string ROI would require per-string cost basis
  (panels-on-this-string × price). Out of scope.
- Per-string Solcast forecast — Solcast accepts multiple sites
  but SEM's forecast consumer would need to map planes to
  strings. Separate feature.

See [`MULTI_CHARGER.md`](MULTI_CHARGER.md) for the symmetric
destination-side pattern (per-EV-charger flow attribution).
