"""#814 — the hardware support matrix, as DATA.

One source of truth for what SEM supports, how, and how sure we are.
``scripts/generate_hardware_doc.py`` renders docs/SUPPORTED_HARDWARE.md
from this table, and ``tests/test_814_hardware_matrix.py`` pins:
the rendered doc matches a regeneration (no drift), every README-claimed
brand has a row, and the pipeline-test coverage gap can only shrink.

STATUS is a claim with evidence rules:
  * ``tested-live``  — confirmed on real hardware by a reporter or on
                        our own PROD/rig. Cite the issue/source in
                        ``evidence`` — no citation, no claim
                        (the #530 lesson: web-research "support" is
                        a false positive generator).
  * ``implemented``  — code + CI tests exist; no live confirmation yet.
  * ``requested``    — an open issue asks for it; nothing shipped.

PATTERN is the grid/battery sign convention family from
tests/test_split_grid_integration.py (A-F); ``ED`` = handled generically
through the HA Energy Dashboard mapping with sign auto-detection.
"""

INVERTERS = [
    {"brand": "Huawei Solar", "integration": "huawei_solar", "pattern": "A",
     "discharge_control": True, "status": "tested-live",
     "evidence": "SEM production system (SUN2000 + LUNA2000), daily"},
    {"brand": "SMA", "integration": "sma", "pattern": "A",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Victron", "integration": "victron / venus", "pattern": "A",
     "discharge_control": True, "status": "implemented",
     "evidence": "Multiplus-II BESS variant requested in #809"},
    {"brand": "Sungrow", "integration": "sungrow", "pattern": "A",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Fronius", "integration": "fronius", "pattern": "B",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#551 two-sensor battery power reporter"},
    {"brand": "Enphase", "integration": "enphase_envoy", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Tesla Powerwall", "integration": "powerwall", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Kostal Plenticore", "integration": "kostal_plenticore", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "SolarEdge", "integration": "solaredge-modbus-multi", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "GoodWe", "integration": "goodwe", "pattern": "C",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Sonnen", "integration": "sonnenbatterie", "pattern": "C",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "SolaX", "integration": "solax-modbus", "pattern": "D",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#274 cold-start fix confirmed by reporter"},
    {"brand": "Growatt", "integration": "growatt_server / grott", "pattern": "E",
     "discharge_control": True, "status": "tested-live",
     "evidence": "force-discharge arc (v1.7.3-beta.18-22) with reporter"},
    {"brand": "DEYE / Sunsynk", "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#807 program-slot reporter; Deye restore latch (#706-#709)"},
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
     "evidence": "#523/#528 arcs with reporter RienduPre"},
    {"brand": "EG4 / Flexboss", "integration": "eg4 (tbd)", "pattern": "-",
     "discharge_control": False, "status": "requested",
     "evidence": "#689, #810 (entity export pending)"},
    {"brand": "Victron Multiplus II BESS", "integration": "victron (tbd)", "pattern": "-",
     "discharge_control": False, "status": "requested", "evidence": "#809"},
]

CHARGERS = [
    {"brand": "KEBA P30/P40", "control": "service: keba.set_current",
     "status": "tested-live", "evidence": "SEM production wallbox, daily"},
    {"brand": "Wallbox Pulsar", "control": "number entity",
     "status": "tested-live", "evidence": "#548 status-lag fix confirmed by reporter"},
    {"brand": "go-eCharger (HTTP)", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "go-eCharger (MQTT)", "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Easee", "control": "service-based",
     "status": "implemented", "evidence": ""},
    {"brand": "Zaptec", "control": "service-based",
     "status": "implemented", "evidence": ""},
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
     "status": "implemented", "evidence": "the documented manual-config path"},
    {"brand": "Fronius / go-e Wattpilot", "control": "number entity",
     "status": "tested-live",
     "evidence": "#802 (HorizonKane, ha-wattpilot fork — confirmed working)"},
    {"brand": "ABL eMH1", "control": "Modbus ASCII (quirk: '>' start symbol)",
     "status": "requested", "evidence": "#808 (interface spec attached)"},
]
