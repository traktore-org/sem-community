"""#814 — the hardware support matrix, as DATA.

One source of truth for what SEM supports, how, and how sure we are.
``scripts/generate_hardware_doc.py`` renders docs/SUPPORTED_HARDWARE.md
from this table, and ``tests/test_814_hardware_matrix.py`` pins:
the rendered doc matches a regeneration (no drift), every README-claimed
brand has a row, every row obeys the evidence rules, and the
pipeline-test coverage gap can only shrink.

STATUS is a claim with evidence rules:
  * ``tested-live``  — confirmed on real hardware by a reporter or on
                        our own PROD/rig. Cite the issue/discussion in
                        ``evidence`` — no citation, no claim
                        (the #530 lesson: web-research "support" is
                        a false positive generator).
  * ``implemented``  — code + CI tests exist, or a reporter names the
                        device without a confirmation we can point at;
                        no live proof yet.
  * ``requested``    — an open issue asks for it; nothing shipped.

Citations: ``#NNN`` is a GitHub issue, ``disc. NNN`` a Discussion, and
the handle in brackets is the reporter whose system it ran on. The
tested-live rows were harvested from a full sweep of the issue and
discussion corpus (21.08.2026) — before that sweep the column mostly
held the maintainer's own hardware, which undersold what users had
already proven.

PATTERN is the grid/battery sign convention family from
tests/test_split_grid_integration.py (A-F); ``ED`` = handled generically
through the HA Energy Dashboard mapping with sign auto-detection.
"""

INVERTERS = [
    {"brand": "Huawei Solar", "integration": "huawei_solar", "pattern": "A",
     "discharge_control": True, "status": "tested-live",
     "evidence": "SEM production system (SUN2000 + LUNA2000) daily; three "
                 "independent installs: #529, #588, #597"},
    {"brand": "SMA", "integration": "sma / pysmaplus", "pattern": "A",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#761 (jappish84) 8 kW hybrid + Home Manager, cross-checked "
                 "against the SMA app; #628 same install, pysmaplus"},
    {"brand": "Victron", "integration": "victron / venus", "pattern": "A",
     "discharge_control": True, "status": "implemented",
     "evidence": "#621/#622 load-management fixes confirmed by a Victron GX "
                 "owner, but no Victron entity ever traced; BESS ask in #809"},
    {"brand": "Sungrow", "integration": "sungrow", "pattern": "A",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Fronius", "integration": "fronius", "pattern": "B",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#551-#613 (ebnerjoh) Verto 15.0 Plus + Fronius storage + "
                 "Smart Meter TS 65A-3, a multi-issue live arc"},
    {"brand": "Enphase", "integration": "enphase_envoy", "pattern": "B",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#352 (markmacseventynine) 3-phase Envoy grid polarity; "
                 "#583 (nicoziptous) IQ 5P battery temperature"},
    {"brand": "Tesla Powerwall", "integration": "powerwall", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Kostal Plenticore", "integration": "kostal_plenticore", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "SolarEdge", "integration": "solaredge-modbus-multi", "pattern": "B",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#691 (onkelfu) Modbus + two SolarEdge batteries — the "
                 "discharge clamp was fixed and confirmed there; #763 same "
                 "install, charge sessions on 2.0.0-beta.7"},
    {"brand": "GoodWe", "integration": "goodwe", "pattern": "C",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#174 (MRAK96) ESA + battery stack, SOC fix confirmed live; "
                 "#68/#283 (Brkie) GoodWe + Easee install"},
    {"brand": "Sonnen", "integration": "sonnenbatterie", "pattern": "C",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#592/#593 (tlinnet) Sonnenbatterie 10 — cycle count "
                 "reconciled with my.sonnen.de, confirmed live"},
    {"brand": "SolaX", "integration": "solax-modbus", "pattern": "D",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#274 cold-start fix confirmed by the reporter; disc. 103 "
                 "(zlakes01) X3 G4 10 kW + 12 kWh battery"},
    {"brand": "Growatt", "integration": "growatt_server / grott", "pattern": "E",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#378 / disc. 103 (RienduPre) MOD9000TL3-X + MIC2500TL-X; "
                 "#732 (bjpo-abelco) Growatt grid+battery with SMA strings"},
    {"brand": "DEYE / Sunsynk", "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#554/#573 (hrdilshan) Deye Cloud 5 kW; #749 / disc. 103 "
                 "(praun) Sun12k over ESPHome Modbus; #807 Deye 12 kW"},
    {"brand": "FENECON Home", "integration": "HA Energy Dashboard", "pattern": "ED",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#802 (HorizonKane) Home 11 read through the Energy "
                 "Dashboard mapping — values reconciled, install confirmed"},
    {"brand": "Sofar", "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Solis", "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "E3DC", "integration": "e3dc_rscp", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "GivEnergy", "integration": "givenergy_local", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Fox ESS", "integration": "foxess", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Alpha ESS", "integration": "alphaess", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Senec", "integration": "senec", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "RCT Power", "integration": "rct_power", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "KSTAR", "integration": "ha-solarman (KSTAR YAML profiles)", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Sessy (battery)", "integration": "sessy", "pattern": "ED",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#378/#523 (RienduPre) multi-battery and force-charge arcs; "
                 "2 x 5 kWh under SEM with a P1 dongle (disc. 103)"},
    {"brand": "EG4 / Flexboss", "integration": "eg4 (tbd)", "pattern": "-",
     "discharge_control": False, "status": "requested",
     "evidence": "#810 native EG4 Web Monitor; #689/#727 (Azlinon) a "
                 "FlexBOSS 21 + 2 Wallmount pair already runs via Solar "
                 "Assistant MQTT — its battery-temp misread was fixed live"},
    {"brand": "Victron Multiplus II BESS", "integration": "victron (tbd)", "pattern": "-",
     "discharge_control": False, "status": "requested", "evidence": "#809"},
]

CHARGERS = [
    {"brand": "KEBA P30/P40", "control": "service: keba.set_current",
     "status": "tested-live",
     "evidence": "SEM production wallbox, daily; #616/#763 (onkelfu) two "
                 "P30 C driven over plain Modbus, not the KEBA integration"},
    {"brand": "Wallbox Pulsar", "control": "number entity",
     "status": "tested-live",
     "evidence": "#548 status-lag fix confirmed by the reporter; two Pulsar "
                 "Plus charging under SEM (disc. 103, RienduPre)"},
    {"brand": "Easee", "control": "service-based",
     "status": "tested-live",
     "evidence": "#68/#283 (Brkie) with GoodWe; #415 (zlakes01) two boxes on "
                 "one install; disc. 103 (praun) beside a Deye Sun12k"},
    {"brand": "GARO", "control": "switch + 6 A-floor current entity",
     "status": "tested-live",
     "evidence": "#700/#748 (jappish84) switch.garo_laddbox — its 6 A floor "
                 "drove the fix, confirmed on v1.7.6-beta.14; brand-detected "
                 "with the floor carried since #816"},
    {"brand": "JuiceBox 48", "control": "number entity (JuiceBoxProxy - MQTT)",
     "status": "tested-live",
     "evidence": "#683/#698 (Azlinon) two JuiceBox 48 over JuiceBoxProxy/MQTT "
                 "— SOC mix-up and double-detection fixed, confirmed live; "
                 "brand-detected since #816"},
    {"brand": "Fronius / go-e Wattpilot", "control": "number entity",
     "status": "tested-live",
     "evidence": "#802 (HorizonKane, ha-wattpilot fork — confirmed working)"},
    {"brand": "go-eCharger (HTTP)", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "go-eCharger (MQTT)", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Zaptec", "control": "service-based",
     "status": "implemented",
     "evidence": "disc. 103 (coppe218) reports a Zaptec Go2 under test; no "
                 "entities or values shown yet"},
    {"brand": "ChargePoint", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Heidelberg Energy Control", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "OpenWB 2.x", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "OCPP-compatible (ABB Terra, Vestel, Grizzl-E, …)",
     "control": "number entity", "status": "implemented", "evidence": ""},
    {"brand": "Ohme", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Peblar Rocksolid", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "V2C Trydan", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Alfen Eve", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Blue Current", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "OpenEVSE", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Generic / manual", "control": "any power+connected+charging sensors",
     "status": "implemented",
     "evidence": "the documented manual-config path; #752 (praun) uses it to "
                 "steer a Tesla's own BLE amp number behind an Easee"},
    {"brand": "ABL eMH1", "control": "Modbus ASCII (quirk: '>' start symbol)",
     "status": "requested", "evidence": "#808 (interface spec attached)"},
]

# Vehicles are not controlled by SEM directly — they matter because their
# SOC/range entity is what SEM charges TOWARDS (target SOC, reachability,
# night deadline). A vehicle row says: this car's HA integration has been
# wired into SEM as that source on a real install.
VEHICLES = [
    {"brand": "Renault Zoe", "soc_source": "Renault (native HA integration)",
     "status": "tested-live",
     "evidence": "SEM production EV — the #804 phase-switching sessions "
                 "(20.08) were driven on it"},
    {"brand": "Audi e-tron / Q8 e-tron", "soc_source": "audi connect",
     "status": "tested-live",
     "evidence": "#461/#523 (RienduPre) SOC + range wired as SEM's vehicle "
                 "source in a two-charger fleet"},
    {"brand": "Mini Cooper SE", "soc_source": "MINI connected",
     "status": "tested-live",
     "evidence": "#523 / disc. 103 (RienduPre) the short-range half of that "
                 "same two-car fleet"},
    {"brand": "Chevrolet Blazer EV (2024)", "soc_source": "OnStar - MQTT",
     "status": "tested-live",
     "evidence": "#683/#708 (Azlinon) a real session stopped at 67 % against "
                 "a 60 % target — the overshoot that fixed the SOC path"},
    {"brand": "Mercedes EV", "soc_source": "Mercedes me",
     "status": "tested-live",
     "evidence": "#763/#779 (onkelfu) the charge-fault ceasefire traces were "
                 "recorded with it plugged in"},
    {"brand": "Tesla", "soc_source": "tesla_ble (ESPHome) amps behind an Easee",
     "status": "implemented",
     "evidence": "#752 (praun) SEM steers the car's own BLE amp number behind "
                 "an Easee; the open ask there is amps below 6 A"},
    {"brand": "Kia Ceed PHEV", "soc_source": "kia_uvo",
     "status": "implemented",
     "evidence": "#559 (alexmc1510) SOC read from the Kia integration, car on "
                 "a plain 230 V socket; recipe given, no confirm"},
]

# Everything else SEM reads or switches: heat pumps and hot water (the
# SG-Ready / comfort path), metered loads, and the meter that supplies the
# grid signal when it does not come from the inverter.
OTHER_DEVICES = [
    {"brand": "NIBE heat pump", "role": "heat pump (SG-Ready)",
     "integration": "nibe_heatpump + SG relays", "status": "tested-live",
     "evidence": "#448/#570 (RienduPre) SEM drives the SG1/SG2 relays on a "
                 "VVM 320 — 'It works'; entities in disc. 432"},
    {"brand": "Ecobee (geothermal)", "role": "heat pump",
     "integration": "homekit_controller", "status": "tested-live",
     "evidence": "#685 (Azlinon) two geothermal units on climate entities, "
                 "one configured in SEM — the second is the open ask"},
    {"brand": "Viessmann Vitocal 250-A / 252-A", "role": "heat pump / hot water",
     "integration": "vicare", "status": "implemented",
     "evidence": "#600 / disc. 599 (tlinnet) ViCare sensors mapped into SEM's "
                 "fields; no actuation confirmed yet"},
    {"brand": "Buderus heat pump", "role": "heat pump (SG-Ready)",
     "integration": "ems-esp", "status": "requested",
     "evidence": "#801 (HorizonKane) SG-Ready needs a command sent to "
                 "EMS-ESP, not a relay flip"},
    {"brand": "SwitchBot relay", "role": "hot water",
     "integration": "switchbot", "status": "tested-live",
     "evidence": "#560 (covuser) the hot-water entity picker was fixed on that "
                 "relay and confirmed"},
    {"brand": "Shelly (EM / PM / Plug)", "role": "metered load, CT meter",
     "integration": "shelly", "status": "tested-live",
     "evidence": "#744 (Azlinon) small metered loads, #745 plug hardware state "
                 "confirmed there; #685 an EM CT clamp meters a heat pump"},
    {"brand": "HomeWizard Wi-Fi P1", "role": "grid meter",
     "integration": "homewizard", "status": "tested-live",
     "evidence": "#628 (jappish84) sensor.p1_meter_effekt is that install's "
                 "configured SEM grid sensor"},
    {"brand": "Sessy P1 dongle", "role": "grid meter",
     "integration": "sessy", "status": "tested-live",
     "evidence": "#461 / disc. 103 (RienduPre) sensor.sessy_p1_power supplies "
                 "grid power on a battery-only install"},
    {"brand": "DSMR / P1 smart meter", "role": "grid meter",
     "integration": "dsmr", "status": "tested-live",
     "evidence": "#378/#461 (RienduPre) import/export counters; the split-grid "
                 "pipeline test is modelled on it"},
    {"brand": "Tibber Pulse", "role": "grid meter + price feed",
     "integration": "tibber", "status": "tested-live",
     "evidence": "#120/#491 (RienduPre) the tibber_pulse price and consumption "
                 "sensors on a running install"},
    {"brand": "Echelon meter", "role": "grid meter",
     "integration": "custom", "status": "implemented",
     "evidence": "#807 (ab-elco-clal) import/export entities appear in a live "
                 "diagnostics dump; nothing confirmed about them"},
]

TABLES = {
    "INVERTERS": INVERTERS,
    "CHARGERS": CHARGERS,
    "VEHICLES": VEHICLES,
    "OTHER_DEVICES": OTHER_DEVICES,
}

ALL_ROWS = [row for rows in TABLES.values() for row in rows]
