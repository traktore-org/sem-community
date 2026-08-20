# Supported Hardware

> **Generated** from `consts/hardware_matrix.py` by `scripts/generate_hardware_doc.py` — edit the matrix, not this file. CI enforces it (#814, asked for in #806).

**What the status means:** ✅ *tested live* = confirmed on real hardware by a reporter or on the maintainers' own systems (the evidence column cites the source). 🧩 *implemented* = code and CI tests exist, no live confirmation yet — reports welcome, they upgrade the row. 📥 *requested* = an open issue asks for it.

**Sign patterns** (grid × battery conventions) are the families verified in `tests/test_split_grid_integration.py`; `ED` rows are handled generically through the HA Energy Dashboard mapping with automatic sign detection.


## Solar inverters / battery systems

| Brand | Integration | Pattern | Discharge control | Status | Evidence |
|---|---|---|---|---|---|
| DEYE / Sunsynk | `ha-solarman` | ED | yes | ✅ tested live | #807 program-slot reporter; Deye restore latch (#706-#709) |
| Fronius | `fronius` | B | — | ✅ tested live | #551 two-sensor battery power reporter |
| Growatt | `growatt_server / grott` | E | yes | ✅ tested live | force-discharge arc (v1.7.3-beta.18-22) with reporter |
| Huawei Solar | `huawei_solar` | A | yes | ✅ tested live | SEM production system (SUN2000 + LUNA2000), daily |
| Sessy (battery) | `sessy` | ED | yes | ✅ tested live | #523/#528 arcs with reporter RienduPre |
| SolaX | `solax-modbus` | D | yes | ✅ tested live | #274 cold-start fix confirmed by reporter |
| Alpha ESS | `alphaess` | ED | — | 🧩 implemented | — |
| E3DC | `e3dc_rscp` | ED | — | 🧩 implemented | — |
| Enphase | `enphase_envoy` | B | yes | 🧩 implemented | — |
| Fox ESS | `foxess` | ED | — | 🧩 implemented | — |
| GivEnergy | `givenergy_local` | ED | — | 🧩 implemented | — |
| GoodWe | `goodwe` | C | yes | 🧩 implemented | — |
| Kostal Plenticore | `kostal_plenticore` | B | yes | 🧩 implemented | — |
| KSTAR | `ha-solarman (KSTAR YAML profiles)` | ED | — | 🧩 implemented | — |
| RCT Power | `rct_power` | ED | — | 🧩 implemented | — |
| Senec | `senec` | ED | — | 🧩 implemented | — |
| SMA | `sma` | A | — | 🧩 implemented | — |
| Sofar | `ha-solarman` | ED | yes | 🧩 implemented | — |
| SolarEdge | `solaredge-modbus-multi` | B | yes | 🧩 implemented | — |
| Solis | `ha-solarman` | ED | yes | 🧩 implemented | — |
| Sonnen | `sonnenbatterie` | C | — | 🧩 implemented | — |
| Sungrow | `sungrow` | A | yes | 🧩 implemented | — |
| Tesla Powerwall | `powerwall` | B | yes | 🧩 implemented | — |
| Victron | `victron / venus` | A | yes | 🧩 implemented | Multiplus-II BESS variant requested in #809 |
| EG4 / Flexboss | `eg4 (tbd)` | - | — | 📥 requested | #689, #810 (entity export pending) |
| Victron Multiplus II BESS | `victron (tbd)` | - | — | 📥 requested | #809 |

## EV chargers

| Brand | Control method | Status | Evidence |
|---|---|---|---|
| KEBA P30/P40 | service: keba.set_current | ✅ tested live | SEM production wallbox, daily |
| Wallbox Pulsar | number entity | ✅ tested live | #548 status-lag fix confirmed by reporter |
| Alfen Eve | number entity | 🧩 implemented | — |
| Blue Current | number entity | 🧩 implemented | — |
| ChargePoint | number entity | 🧩 implemented | — |
| Easee | service-based | 🧩 implemented | — |
| Generic / manual | any power+connected+charging sensors | 🧩 implemented | the documented manual-config path |
| go-eCharger (HTTP) | number entity | 🧩 implemented | — |
| go-eCharger (MQTT) | number entity | 🧩 implemented | — |
| Heidelberg Energy Control | number entity | 🧩 implemented | — |
| OCPP-compatible (ABB Terra, Vestel, Grizzl-E, …) | number entity | 🧩 implemented | — |
| Ohme | number entity | 🧩 implemented | — |
| OpenEVSE | number entity | 🧩 implemented | — |
| OpenWB 2.x | number entity | 🧩 implemented | — |
| Peblar Rocksolid | number entity | 🧩 implemented | — |
| V2C Trydan | number entity | 🧩 implemented | — |
| Zaptec | service-based | 🧩 implemented | — |
| ABL eMH1 | Modbus ASCII (quirk: '>' start symbol) | 📥 requested | #808 (interface spec attached) |

## Upgrading a row to *tested live*

Run SEM with your hardware and tell us what happened — an issue with your brand, the config-flow result and a note that the first cycles worked is enough. Every confirmation is cited here.

