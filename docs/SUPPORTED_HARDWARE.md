# Supported Hardware

> **Generated** from `consts/hardware_matrix.py` by `scripts/generate_hardware_doc.py` — edit the matrix, not this file. CI enforces it (#814, asked for in #806).

**What the status means:** ✅ *tested live* = confirmed on real hardware by a reporter or on the maintainers' own systems (the evidence column cites the source). 🧩 *implemented* = code and CI tests exist, or someone names the device without a confirmation we can point at — no live proof yet. 📥 *requested* = an open issue asks for it.

**Reading the evidence column:** `#NNN` is a GitHub issue, `disc. NNN` a Discussion, and the name in brackets is the person whose system it ran on — thank you, all of you. Everything marked ✅ traces back to one of those threads.

**Sign patterns** (grid × battery conventions) are the families verified in `tests/test_split_grid_integration.py`; `ED` rows are handled generically through the HA Energy Dashboard mapping with automatic sign detection.


## Solar inverters / battery systems

| Brand | Integration | Pattern | Discharge control | Status | Evidence |
|---|---|---|---|---|---|
| DEYE / Sunsynk | `ha-solarman` | ED | yes | ✅ tested live | #554/#573 (hrdilshan) Deye Cloud 5 kW; #749 / disc. 103 (praun) Sun12k over ESPHome Modbus; #807 Deye 12 kW |
| Enphase | `enphase_envoy` | B | yes | ✅ tested live | #352 (markmacseventynine) 3-phase Envoy grid polarity; #583 (nicoziptous) IQ 5P battery temperature |
| FENECON Home | `HA Energy Dashboard` | ED | — | ✅ tested live | #802 (HorizonKane) Home 11 read through the Energy Dashboard mapping — values reconciled, install confirmed |
| Fronius | `fronius` | B | — | ✅ tested live | #551-#613 (ebnerjoh) Verto 15.0 Plus + Fronius storage + Smart Meter TS 65A-3, a multi-issue live arc |
| GoodWe | `goodwe` | C | yes | ✅ tested live | #174 (MRAK96) ESA + battery stack, SOC fix confirmed live; #68/#283 (Brkie) GoodWe + Easee install |
| Growatt | `growatt_server / grott` | E | yes | ✅ tested live | #378 / disc. 103 (RienduPre) MOD9000TL3-X + MIC2500TL-X; #732 (bjpo-abelco) Growatt grid+battery with SMA strings |
| Huawei Solar | `huawei_solar` | A | yes | ✅ tested live | SEM production system (SUN2000 + LUNA2000) daily; three independent installs: #529, #588, #597 |
| Sessy (battery) | `sessy` | ED | yes | ✅ tested live | #378/#523 (RienduPre) multi-battery and force-charge arcs; 2 x 5 kWh under SEM with a P1 dongle (disc. 103) |
| SMA | `sma / pysmaplus` | A | — | ✅ tested live | #761 (jappish84) 8 kW hybrid + Home Manager, cross-checked against the SMA app; #628 same install, pysmaplus |
| SolarEdge | `solaredge-modbus-multi` | B | yes | ✅ tested live | #691 (onkelfu) Modbus + two SolarEdge batteries — the discharge clamp was fixed and confirmed there; #763 same install, charge sessions on 2.0.0-beta.7 |
| SolaX | `solax-modbus` | D | yes | ✅ tested live | #274 cold-start fix confirmed by the reporter; disc. 103 (zlakes01) X3 G4 10 kW + 12 kWh battery |
| Sonnen | `sonnenbatterie` | C | — | ✅ tested live | #592/#593 (tlinnet) Sonnenbatterie 10 — cycle count reconciled with my.sonnen.de, confirmed live |
| Alpha ESS | `alphaess` | ED | — | 🧩 implemented | — |
| E3DC | `e3dc_rscp` | ED | — | 🧩 implemented | — |
| Fox ESS | `foxess` | ED | — | 🧩 implemented | — |
| GivEnergy | `givenergy_local` | ED | — | 🧩 implemented | — |
| Kostal Plenticore | `kostal_plenticore` | B | yes | 🧩 implemented | — |
| KSTAR | `ha-solarman (KSTAR YAML profiles)` | ED | — | 🧩 implemented | — |
| RCT Power | `rct_power` | ED | — | 🧩 implemented | — |
| Senec | `senec` | ED | — | 🧩 implemented | — |
| Sofar | `ha-solarman` | ED | yes | 🧩 implemented | — |
| Solis | `ha-solarman` | ED | yes | 🧩 implemented | — |
| Sungrow | `sungrow` | A | yes | 🧩 implemented | — |
| Tesla Powerwall | `powerwall` | B | yes | 🧩 implemented | — |
| Victron | `victron / venus` | A | yes | 🧩 implemented | #621/#622 load-management fixes confirmed by a Victron GX owner, but no Victron entity ever traced; BESS ask in #809 |
| EG4 / Flexboss | `eg4 (tbd)` | - | — | 📥 requested | #810 native EG4 Web Monitor; #689/#727 (Azlinon) a FlexBOSS 21 + 2 Wallmount pair already runs via Solar Assistant MQTT — its battery-temp misread was fixed live |
| Victron Multiplus II BESS | `victron (tbd)` | - | — | 📥 requested | #809 |

## EV chargers

| Brand | Control method | Status | Evidence |
|---|---|---|---|
| Easee | service-based | ✅ tested live | #68/#283 (Brkie) with GoodWe; #415 (zlakes01) two boxes on one install; disc. 103 (praun) beside a Deye Sun12k |
| Fronius / go-e Wattpilot | number entity | ✅ tested live | #802 (HorizonKane, ha-wattpilot fork — confirmed working) |
| GARO | switch + 6 A-floor current entity | ✅ tested live | #700/#748 (jappish84) switch.garo_laddbox — its 6 A floor drove the fix, confirmed on v1.7.6-beta.14; brand-detected with the floor carried since #816 |
| JuiceBox 48 | number entity (JuiceBoxProxy - MQTT) | ✅ tested live | #683/#698 (Azlinon) two JuiceBox 48 over JuiceBoxProxy/MQTT — SOC mix-up and double-detection fixed, confirmed live; brand-detected since #816 |
| KEBA P30/P40 | service: keba.set_current | ✅ tested live | SEM production wallbox, daily; #616/#763 (onkelfu) two P30 C driven over plain Modbus, not the KEBA integration |
| Wallbox Pulsar | number entity | ✅ tested live | #548 status-lag fix confirmed by the reporter; two Pulsar Plus charging under SEM (disc. 103, RienduPre) |
| Alfen Eve | number entity | 🧩 implemented | — |
| Blue Current | number entity | 🧩 implemented | — |
| ChargePoint | number entity | 🧩 implemented | — |
| Generic / manual | any power+connected+charging sensors | 🧩 implemented | the documented manual-config path; #752 (praun) uses it to steer a Tesla's own BLE amp number behind an Easee |
| go-eCharger (HTTP) | number entity | 🧩 implemented | — |
| go-eCharger (MQTT) | number entity | 🧩 implemented | — |
| Heidelberg Energy Control | number entity | 🧩 implemented | — |
| OCPP-compatible (ABB Terra, Vestel, Grizzl-E, …) | number entity | 🧩 implemented | — |
| Ohme | number entity | 🧩 implemented | — |
| OpenEVSE | number entity | 🧩 implemented | — |
| OpenWB 2.x | number entity | 🧩 implemented | — |
| Peblar Rocksolid | number entity | 🧩 implemented | — |
| V2C Trydan | number entity | 🧩 implemented | — |
| Zaptec | service-based | 🧩 implemented | disc. 103 (coppe218) reports a Zaptec Go2 under test; no entities or values shown yet |
| ABL eMH1 | Modbus ASCII (quirk: '>' start symbol) | 📥 requested | #808 (interface spec attached) |

## Vehicles

SEM does not talk to the car — it charges *towards* the car's state of charge. A row here means that vehicle's HA integration has been wired in as SEM's SOC/range source on a real install.

| Vehicle | SOC / range source | Status | Evidence |
|---|---|---|---|
| Audi e-tron / Q8 e-tron | audi connect | ✅ tested live | #461/#523 (RienduPre) SOC + range wired as SEM's vehicle source in a two-charger fleet |
| Chevrolet Blazer EV (2024) | OnStar - MQTT | ✅ tested live | #683/#708 (Azlinon) a real session stopped at 67 % against a 60 % target — the overshoot that fixed the SOC path |
| Mercedes EV | Mercedes me | ✅ tested live | #763/#779 (onkelfu) the charge-fault ceasefire traces were recorded with it plugged in |
| Mini Cooper SE | MINI connected | ✅ tested live | #523 / disc. 103 (RienduPre) the short-range half of that same two-car fleet |
| Renault Zoe | Renault (native HA integration) | ✅ tested live | SEM production EV — the #804 phase-switching sessions (20.08) were driven on it |
| Kia Ceed PHEV | kia_uvo | 🧩 implemented | #559 (alexmc1510) SOC read from the Kia integration, car on a plain 230 V socket; recipe given, no confirm |
| Tesla | tesla_ble (ESPHome) amps behind an Easee | 🧩 implemented | #752 (praun) SEM steers the car's own BLE amp number behind an Easee; the open ask there is amps below 6 A |

## Heat pumps, hot water, loads and meters

Everything else SEM reads or switches: the SG-Ready and hot-water path, metered loads, and the meter that supplies the grid signal when it does not come from the inverter.

| Device | Role | Integration | Status | Evidence |
|---|---|---|---|---|
| DSMR / P1 smart meter | grid meter | `dsmr` | ✅ tested live | #378/#461 (RienduPre) import/export counters; the split-grid pipeline test is modelled on it |
| Ecobee (geothermal) | heat pump | `homekit_controller` | ✅ tested live | #685 (Azlinon) two geothermal units on climate entities, one configured in SEM — the second is the open ask |
| HomeWizard Wi-Fi P1 | grid meter | `homewizard` | ✅ tested live | #628 (jappish84) sensor.p1_meter_effekt is that install's configured SEM grid sensor |
| NIBE heat pump | heat pump (SG-Ready) | `nibe_heatpump + SG relays` | ✅ tested live | #448/#570 (RienduPre) SEM drives the SG1/SG2 relays on a VVM 320 — 'It works'; entities in disc. 432 |
| Sessy P1 dongle | grid meter | `sessy` | ✅ tested live | #461 / disc. 103 (RienduPre) sensor.sessy_p1_power supplies grid power on a battery-only install |
| Shelly (EM / PM / Plug) | metered load, CT meter | `shelly` | ✅ tested live | #744 (Azlinon) small metered loads, #745 plug hardware state confirmed there; #685 an EM CT clamp meters a heat pump |
| SwitchBot relay | hot water | `switchbot` | ✅ tested live | #560 (covuser) the hot-water entity picker was fixed on that relay and confirmed |
| Tibber Pulse | grid meter + price feed | `tibber` | ✅ tested live | #120/#491 (RienduPre) the tibber_pulse price and consumption sensors on a running install |
| Echelon meter | grid meter | `custom` | 🧩 implemented | #807 (ab-elco-clal) import/export entities appear in a live diagnostics dump; nothing confirmed about them |
| Viessmann Vitocal 250-A / 252-A | heat pump / hot water | `vicare` | 🧩 implemented | #600 / disc. 599 (tlinnet) ViCare sensors mapped into SEM's fields; no actuation confirmed yet |
| Buderus heat pump | heat pump (SG-Ready) | `ems-esp` | 📥 requested | #801 (HorizonKane) SG-Ready needs a command sent to EMS-ESP, not a relay flip |

## Upgrading a row to *tested live*

Run SEM with your hardware and tell us what happened — an issue with your brand, the config-flow result and a note that the first cycles worked is enough. Every confirmation is cited here.

