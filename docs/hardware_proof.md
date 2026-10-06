# Hardware proof — the matrix rows no owner has confirmed yet

`consts/hardware_matrix.py` has 35 rows marked `implemented`: SEM has a
path for them, but no owner has confirmed it on real hardware
(`tested-live`). On 01.10.2026 every one of them was put through the
crawler rig (`tests/integrations_rig`) where its integration could be
loaded: the integration's real output was replayed into a test Home
Assistant and SEM's crawler was run on it.

Nothing here changes a row's status. `tested-live` stays the word for real
hardware. A row that passes the rig could later carry a new status,
`rig-proven`; that is a proposal, not done.

**Verdicts:** `proven-by-rig` — the crawler finds the device and wires the
right entities. `gap` — it does not, or wires a wrong one. `cannot load` —
the integration could not be run offline; the reason is given.

## Chargers

| brand | integration | how loaded | pin | what the crawler found | verdict |
|---|---|---|---|---|---|
| Ohme | `ohme` (core) | core snapshot | HA 2026.8.2 | charger: charge-mode select `Max charge` / `Paused`, power `sensor.…_power`, status sensor for connected | **proven-by-rig** |
| Peblar Rocksolid | `peblar` (core) | core snapshot | HA 2026.8.2 | charger, but start/stop = `switch.…_force_single_phase` (not `switch.…_charge`), power = `sensor.…_power_phase_3` (one phase, not `sensor.…_power`) | **gap** |
| V2C Trydan | `v2c` (core) | core snapshot | HA 2026.8.2 | charger, but current = `number.…_min_intensity` (not `…_intensity`), power = `sensor.…_photovoltaic_power` (the PV, not `…_charge_power`) | **gap** |
| NRGkick | `nrgkick` (core) | core snapshot | HA 2026.8.2 | the brand path matches none of the real entities → near miss. The roster offer uses `…_l1_active_power` (one phase); the new role offer is complete with `…_total_active_power` + `…_charging_current` | **gap** (released path); role offer fixes it |
| OpenEVSE | `openevse` (core) | core snapshot | HA 2026.8.2 | the brand path matches none of the real entities → near miss; roster and role offer both complete (`…_charge_rate`, `…_charging_power`, `…_vehicle_connected`) | **gap** (released path); role offer fixes it |
| Zaptec | `zaptec` (HACS) | declared from source | `ba502a99` (2026-08-26) | the brand path's `zaptec_*` patterns never match (entity ids follow the device name) → both devices are near misses, the #1032 report. Role offer: start/stop buttons, installation's `available_current` when present, installation folded in as companion | **gap** (released path); role offer fixes it |
| Blue Current | `blue_current` (core) | core snapshot (buttons only) | HA 2026.8.2 | core snapshots only its three buttons; near miss with nothing to offer | **cannot judge** — core has no snapshot of its sensors |
| go-eCharger (HTTP) | `goecharger` (HACS) | declared from source | cathiele 1d28e0f5 | power `p_all` (kW, by unit), plug + charging `car_status` (by state), start/stop `allow_charging`, current `goecharger.set_max_current` with the box's name, session + lifetime meters | **proven by rig** (weakest: from source) |
| go-eCharger (MQTT) | `goecharger_api2` / MQTT | — | — | — | **cannot load** — MQTT names are the user's |
| ChargePoint | `chargepoint` (HACS) | — | — | — | **cannot load** — cloud, no offline data |
| Heidelberg Energy Control | HACS (Modbus) | — | — | — | **cannot load** — no offline data |
| OpenWB 2.x | HACS / MQTT | — | — | — | **cannot load** — no offline data |
| OCPP-compatible | `ocpp` (HACS) | — | — | — | **cannot load** — its tests need a charge-point simulator; not built in this wave |
| Alfen Eve | `alfen_wallbox` (HACS) | — | — | — | **cannot load** — conftest only, no data |
| Wallbox (MQTT bridge) | MQTT | — | — | — | **cannot load** — MQTT names are the user's |
| ABL eMH1 | Modbus (HACS) | — | — | — | **cannot load** — Modbus names are the user's |
| Generic / manual | — | — | — | — | not a crawler path (the user picks every entity) |

## Vehicles

| brand | integration | how loaded | pin | what the crawler found | verdict |
|---|---|---|---|---|---|
| Tesla | `tesla_fleet`, `teslemetry`, `tessie` (core) | core snapshot | HA 2026.8.2 | new role R3: the car's `number.…_charge_current` + `switch.…_charge` + `sensor.…_charger_power` offered as its charge control; R4: a Wall Connector (live load) is driven through the one car | **proven-by-rig** for the car integrations. The row's own path (the car's BLE amp number over MQTT/ESPHome, #752) **cannot load** — those names are the user's |
| Kia Ceed PHEV | `kia_uvo` (HACS) | — | — | — | **cannot load** — cloud, no offline data |

## Inverters, batteries and other devices

The rig in this wave covers chargers and cars (the role reader). Inverter
and battery detection is a different crawler path and was not run.

| brand | integration | verdict |
|---|---|---|
| Victron, Victron Multiplus II BESS | `victron` / GX / MQTT (HACS) | not run this wave |
| Sungrow | `sungrow` (HACS) | not run this wave |
| Tesla Powerwall | `powerwall` (core) | not run — core has no entity snapshots for it |
| Kostal Plenticore | `kostal_plenticore` (core) | not run — core has no entity snapshots for it |
| Sofar, Solis, KSTAR | `solarman` (HACS, YAML profiles) | not run this wave |
| E3DC, GivEnergy, Fox ESS, Alpha ESS, Senec, RCT Power | HACS | not run this wave |
| EG4 / Flexboss | `eg4_web_monitor` (HACS) | not run — has offline fixtures; waits for the #810 inverter (R7) |
| Viessmann Vitocal | `vicare` (core) | core snapshot loaded; the crawler correctly finds no charger. Heat-pump mapping is not a crawler path |
| Buderus | `ems-esp` (HACS) | not run |
| Echelon meter | custom | not run |
| BYD Battery-Box | generic patterns | not run |

## Counts

| verdict | rows |
|---|---|
| proven-by-rig | 2 (Ohme; Tesla for the car integrations) |
| gap | 5 (Peblar, V2C, NRGkick, OpenEVSE, Zaptec) |
| cannot judge / cannot load | 13 |
| not run this wave (inverters, batteries, other) | 15 |

## Gaps in released detection (the autopilot's lane)

These are bugs in code that already ships. They are listed here, not fixed
on this branch, except where a role built in this wave covers them anyway.

1. **V2C** binds the MINIMUM current (`min_intensity`) as the control and
   the PV power as the charging power.
2. **Peblar** binds the force-single-phase switch as start/stop and one
   phase's power as the charging power.
3. **Easee** with an Equalizer reports the Equalizer as a second charger,
   with the grid import power as its charging power.
4. **NRGkick** — the brand path matches none of core's real entities.
5. **OpenEVSE** — the brand path matches none of core's real entities.
6. **Zaptec** — the `zaptec_*` name patterns never match a current install
   (#1032). The role offer covers it.
