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


#: (#915) ``domain_token`` is the HA integration domain SEM DETECTS for a
#: charger row, and ``also_domains`` lists the brand's other integrations
#: (go-e ships three; openWB's 1.x is archived but still installed). Together
#: they must equal ``hardware_detection._EV_CHARGER_PLATFORMS``, both ways —
#: before this, one row in twenty-one carried a token, so the brand table and
#: the detection list could drift apart with nothing noticing. A row with no
#: token is a path rather than an integration: the generic matcher, or a
#: brand that is only a request.
UNTOKENED_CHARGER_ROWS: tuple = ("Generic / manual", "ABL eMH1")

#: (#915) The same idea for the other three tables: ``domains`` is the HA
#: integration domain (or domains — one brand, several integrations) a row is
#: reached through. It is what lets a test ask whether SEM can still NAME the
#: hardware it claims to support. Rows without it are reached some other way
#: and say so here: through the Energy Dashboard generically, through MQTT
#: discovery with no domain of its own, or through a car integration that no
#: public index carries.
ROWS_WITH_NO_DOMAIN: dict = {
    "FENECON Home": "read generically through the HA Energy Dashboard",
    "Buderus heat pump": "ems-esp publishes over MQTT discovery, no domain",
    "Echelon meter": "a custom local integration, no published domain",
    "Mini Cooper SE": "MINI connected — not in HACS's store index or core",
    "Mercedes EV": "Mercedes me — not in HACS's store index or core",
    "Chevrolet Blazer EV (2024)": "OnStar over MQTT",
    "Tesla": "tesla_ble over ESPHome, amps behind an Easee",
}


def charger_watchdog_refresh_map() -> dict:
    """token -> seconds, from every charger row that declares the quirk
    (#855 stage 4). This is how ``devices/base.py`` learns which brands
    need a faster write heartbeat — a new brand adds a ROW here, never a
    line in the generic layer."""
    return {
        r["domain_token"]: float(r["watchdog_refresh_s"])
        for r in CHARGERS
        if r.get("domain_token") and r.get("watchdog_refresh_s")
    }

INVERTERS = [
    {"brand": "Huawei Solar", "domains": ['huawei_solar'],
     "integration": "huawei_solar", "pattern": "A",
     "discharge_control": True, "status": "tested-live",
     "evidence": "SEM production system (SUN2000 + LUNA2000) daily; three "
                 "independent installs: #529, #588, #597"},
    {"brand": "SMA", "domains": ['sma', 'pysmaplus'],
     "integration": "sma / pysmaplus", "pattern": "A",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#761 (jappish84) 8 kW hybrid + Home Manager, cross-checked "
                 "against the SMA app; #628 same install, pysmaplus"},
    {"brand": "Victron", "domains": ['victron', 'victron_gx', 'victron_mqtt'],
     "integration": "victron / venus", "pattern": "A",
     "discharge_control": True, "status": "implemented",
     "evidence": "#621/#622 load-management fixes confirmed by a Victron GX "
                 "owner, but no Victron entity ever traced; BESS ask in #809"},
    {"brand": "Sungrow", "domains": ['sungrow'],
     "integration": "sungrow", "pattern": "A",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Fronius", "domains": ['fronius'],
     "integration": "fronius", "pattern": "B",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#551-#613 (ebnerjoh) Verto 15.0 Plus + Fronius storage + "
                 "Smart Meter TS 65A-3, a multi-issue live arc"},
    {"brand": "Enphase", "domains": ['enphase_envoy'],
     "integration": "enphase_envoy", "pattern": "B",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#352 (markmacseventynine) 3-phase Envoy grid polarity; "
                 "#583 (nicoziptous) IQ 5P battery temperature"},
    {"brand": "Tesla Powerwall", "domains": ['powerwall'],
     "integration": "powerwall", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Kostal Plenticore", "domains": ['kostal_plenticore'],
     "integration": "kostal_plenticore", "pattern": "B",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "SolarEdge", "domains": ['solaredge_modbus_multi', 'solaredge'],
     "integration": "solaredge-modbus-multi", "pattern": "B",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#691 (onkelfu) Modbus + two SolarEdge batteries — the "
                 "discharge clamp was fixed and confirmed there; #763 same "
                 "install, charge sessions on 2.0.0-beta.7"},
    {"brand": "GoodWe", "domains": ['goodwe'],
     "integration": "goodwe", "pattern": "C",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#174 (MRAK96) ESA + battery stack, SOC fix confirmed live; "
                 "#68/#283 (Brkie) GoodWe + Easee install"},
    {"brand": "Sonnen", "domains": ['sonnenbatterie'],
     "integration": "sonnenbatterie", "pattern": "C",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#592/#593 (tlinnet) Sonnenbatterie 10 — cycle count "
                 "reconciled with my.sonnen.de, confirmed live"},
    {"brand": "SolaX", "domains": ['solax_modbus', 'solax'],
     "integration": "solax-modbus", "pattern": "D",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#274 cold-start fix confirmed by the reporter; disc. 103 "
                 "(zlakes01) X3 G4 10 kW + 12 kWh battery"},
    {"brand": "Growatt", "domains": ['growatt_server', 'grott'],
     "integration": "growatt_server / grott", "pattern": "E",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#378 / disc. 103 (RienduPre) MOD9000TL3-X + MIC2500TL-X; "
                 "#732 (bjpo-abelco) Growatt grid+battery with SMA strings"},
    {"brand": "DEYE / Sunsynk", "domains": ['solarman'],
     "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#554/#573 (hrdilshan) Deye Cloud 5 kW; #749 / disc. 103 "
                 "(praun) Sun12k over ESPHome Modbus; #807 Deye 12 kW"},
    {"brand": "FENECON Home", "integration": "HA Energy Dashboard", "pattern": "ED",
     "discharge_control": False, "status": "tested-live",
     "evidence": "#802 (HorizonKane) Home 11 read through the Energy "
                 "Dashboard mapping — values reconciled, install confirmed"},
    {"brand": "Sofar", "domains": ['solarman'],
     "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "Solis", "domains": ['solarman'],
     "integration": "ha-solarman", "pattern": "ED",
     "discharge_control": True, "status": "implemented", "evidence": ""},
    {"brand": "E3DC", "domains": ['e3dc_rscp'],
     "integration": "e3dc_rscp", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "GivEnergy", "domains": ['givenergy_local'],
     "integration": "givenergy_local", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Fox ESS", "domains": ['foxess'],
     "integration": "foxess", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Alpha ESS", "domains": ['alphaess'],
     "integration": "alphaess", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Senec", "domains": ['senec'],
     "integration": "senec", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "RCT Power", "domains": ['rct_power'],
     "integration": "rct_power", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "KSTAR", "domains": ['solarman'],
     "integration": "ha-solarman (KSTAR YAML profiles)", "pattern": "ED",
     "discharge_control": False, "status": "implemented", "evidence": ""},
    {"brand": "Sessy (battery)", "domains": ['sessy'],
     "integration": "sessy", "pattern": "ED",
     "discharge_control": True, "status": "tested-live",
     "evidence": "#378/#523 (RienduPre) multi-battery and force-charge arcs; "
                 "2 x 5 kWh under SEM with a P1 dongle (disc. 103)"},
    {"brand": "EG4 / Flexboss", "domains": ['eg4_web_monitor'],
     "integration": "eg4 (tbd)", "pattern": "-",
     "discharge_control": False, "status": "requested",
     "evidence": "#810 native EG4 Web Monitor; #689/#727 (Azlinon) a "
                 "FlexBOSS 21 + 2 Wallmount pair already runs via Solar "
                 "Assistant MQTT — its battery-temp misread was fixed live"},
    {"brand": "Victron Multiplus II BESS", "domains": ['victron', 'victron_gx', 'victron_mqtt'],
     "integration": "victron (tbd)", "pattern": "-",
     "discharge_control": False, "status": "requested", "evidence": "#809"},
]

CHARGERS = [
    {"brand": "KEBA P30/P40", "control": "service: keba.set_current",
     # Operational quirk (#855 stage 4): the P30's device-side failsafe can
     # trip under the generic 60 s write heartbeat — PROD showed it reverting
     # to its 6 A failsafe current in well under 30 s (the 6<->9 A flap), so
     # steady-state commands are re-asserted every coordinator cycle. The
     # generic device layer READS this from the row; it hardcodes no brand.
     "domain_token": "keba", "watchdog_refresh_s": 5.0,
     "status": "tested-live",
     "evidence": "SEM production wallbox, daily; #616/#763 (onkelfu) two "
                 "P30 C driven over plain Modbus, not the KEBA integration"},
    {"brand": "Wallbox Pulsar", "domain_token": "wallbox",
     "control": "number entity",
     "status": "tested-live",
     "evidence": "#548 status-lag fix confirmed by the reporter; two Pulsar "
                 "Plus charging under SEM (disc. 103, RienduPre)"},
    {"brand": "Easee", "domain_token": "easee",
     "control": "service-based",
     "status": "tested-live",
     "evidence": "#68/#283 (Brkie) with GoodWe; #415 (zlakes01) two boxes on "
                 "one install; disc. 103 (praun) beside a Deye Sun12k"},
    {"brand": "GARO", "domain_token": "garo_wallbox",
     "control": "switch + 6 A-floor current entity",
     "status": "tested-live",
     "evidence": "#700/#748 (jappish84) switch.garo_laddbox — its 6 A floor "
                 "drove the fix, confirmed on v1.7.6-beta.14; brand-detected "
                 "with the floor carried since #816"},
    {"brand": "JuiceBox 48", "domain_token": "mqtt",
     "control": "number entity (JuiceBoxProxy - MQTT)",
     "status": "tested-live",
     "evidence": "#683/#698 (Azlinon) two JuiceBox 48 over JuiceBoxProxy/MQTT "
                 "— SOC mix-up and double-detection fixed, confirmed live; "
                 "brand-detected since #816"},
    {"brand": "Fronius / go-e Wattpilot", "domain_token": "wattpilot",
     "control": "number entity",
     "status": "tested-live",
     "evidence": "#802 (HorizonKane, ha-wattpilot fork — confirmed working)"},
    {"brand": "go-eCharger (HTTP)", "domain_token": "goecharger",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "go-eCharger (MQTT)", "domain_token": "goecharger_mqtt",
     # go-e ships THREE HA integrations for the same hardware; APIv2 shares
     # the MQTT entity model, which is why detection points both at the same
     # discover function.
     "also_domains": ["goecharger_api2"],
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Zaptec", "domain_token": "zaptec",
     "control": "service-based",
     "status": "implemented",
     "evidence": "disc. 103 (coppe218) reports a Zaptec Go2 under test; no "
                 "entities or values shown yet"},
    {"brand": "ChargePoint", "domain_token": "chargepoint",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Heidelberg Energy Control", "domain_token": "heidelberg_energy_control",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "OpenWB 2.x", "domain_token": "openwb2mqtt",
     # the archived 1.x integration is still installed on real systems and is
     # still detected (#79).
     "also_domains": ["openwbmqtt"],
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "OCPP-compatible (ABB Terra, Vestel, Grizzl-E, …)",
     "domain_token": "ocpp",
     "control": "number entity", "status": "implemented", "evidence": ""},
    {"brand": "Ohme", "domain_token": "ohme",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Peblar Rocksolid", "domain_token": "peblar",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "V2C Trydan", "domain_token": "v2c",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Alfen Eve", "domain_token": "alfen_wallbox",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "Blue Current", "domain_token": "blue_current",
     "control": "number entity",
     "status": "implemented", "evidence": ""},
    {"brand": "OpenEVSE", "domain_token": "openevse",
     "control": "number entity",
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
    {"brand": "Renault Zoe", "domains": ['renault'],
     "soc_source": "Renault (native HA integration)",
     "status": "tested-live",
     "evidence": "SEM production EV — the #804 phase-switching sessions "
                 "(20.08) were driven on it"},
    {"brand": "Audi e-tron / Q8 e-tron", "domains": ['audiconnect'],
     "soc_source": "audi connect",
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
    {"brand": "Kia Ceed PHEV", "domains": ['kia_uvo'],
     "soc_source": "kia_uvo",
     "status": "implemented",
     "evidence": "#559 (alexmc1510) SOC read from the Kia integration, car on "
                 "a plain 230 V socket; recipe given, no confirm"},
]

# Everything else SEM reads or switches: heat pumps and hot water (the
# SG-Ready / comfort path), metered loads, and the meter that supplies the
# grid signal when it does not come from the inverter.
OTHER_DEVICES = [
    {"brand": "NIBE heat pump", "domains": ['nibe_heatpump'],
     "role": "heat pump (SG-Ready)",
     "integration": "nibe_heatpump + SG relays", "status": "tested-live",
     "evidence": "#448/#570 (RienduPre) SEM drives the SG1/SG2 relays on a "
                 "VVM 320 — 'It works'; entities in disc. 432"},
    {"brand": "Ecobee (geothermal)", "domains": ['homekit_controller'],
     "role": "heat pump",
     "integration": "homekit_controller", "status": "tested-live",
     "evidence": "#685 (Azlinon) two geothermal units on climate entities, "
                 "one configured in SEM — the second is the open ask"},
    {"brand": "Viessmann Vitocal 250-A / 252-A", "domains": ['vicare'],
     "role": "heat pump / hot water",
     "integration": "vicare", "status": "implemented",
     "evidence": "#600 / disc. 599 (tlinnet) ViCare sensors mapped into SEM's "
                 "fields; no actuation confirmed yet"},
    {"brand": "Buderus heat pump", "role": "heat pump (SG-Ready)",
     "integration": "ems-esp", "status": "requested",
     "evidence": "#801 (HorizonKane) SG-Ready needs a command sent to "
                 "EMS-ESP, not a relay flip"},
    {"brand": "SwitchBot relay", "domains": ['switchbot'],
     "role": "hot water",
     "integration": "switchbot", "status": "tested-live",
     "evidence": "#560 (covuser) the hot-water entity picker was fixed on that "
                 "relay and confirmed"},
    {"brand": "Shelly (EM / PM / Plug)", "domains": ['shelly'],
     "role": "metered load, CT meter",
     "integration": "shelly", "status": "tested-live",
     "evidence": "#744 (Azlinon) small metered loads, #745 plug hardware state "
                 "confirmed there; #685 an EM CT clamp meters a heat pump"},
    {"brand": "HomeWizard Wi-Fi P1", "domains": ['homewizard'],
     "role": "grid meter",
     "integration": "homewizard", "status": "tested-live",
     "evidence": "#628 (jappish84) sensor.p1_meter_effekt is that install's "
                 "configured SEM grid sensor"},
    {"brand": "Sessy P1 dongle", "domains": ['sessy'],
     "role": "grid meter",
     "integration": "sessy", "status": "tested-live",
     "evidence": "#461 / disc. 103 (RienduPre) sensor.sessy_p1_power supplies "
                 "grid power on a battery-only install"},
    {"brand": "DSMR / P1 smart meter", "domains": ['dsmr'],
     "role": "grid meter",
     "integration": "dsmr", "status": "tested-live",
     "evidence": "#378/#461 (RienduPre) import/export counters; the split-grid "
                 "pipeline test is modelled on it"},
    {"brand": "Tibber Pulse", "domains": ['tibber'],
     "role": "grid meter + price feed",
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
