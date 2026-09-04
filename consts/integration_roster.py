"""GENERATED — do not edit. #915

    python3 scripts/crawl_integration_roster.py --refresh --write

This is a ROSTER, not a support matrix. A row means exactly one thing: an
integration with this domain exists upstream, it looks energy-shaped, and —
when ``kind_from`` is ``vocabulary`` — here is what its own repository says it
calls things.

It is NOT a claim that SEM supports the brand, has ever seen it, or knows its
sign convention. Support claims live in ``consts/hardware_matrix.py`` and need
a citation (the #530 rule: web-research "support" is a false-positive
generator). Nothing here may carry a status, an evidence string or a sign
pattern; ``tests/test_915_roster_is_not_a_claim.py`` enforces that
structurally rather than by convention.

Every runtime use is an INTERSECTION with the local entity registry: a key
here can only ever select an entity the user's own install already has, and
the role it suggests is a proposal the user confirms — never a binding.

Sources: HACS (data-v2.hacs.xyz), Home Assistant analytics
(analytics.home-assistant.io) and the Home Assistant core + website indexes.
Vocabulary is read from each integration's own repository.
"""

from __future__ import annotations

from typing import Any, Dict, Final

SCHEMA: Final = 1


ROSTER_META: Final[Dict[str, Any]] = {'generated_at': '2026-09-04T08:20:28Z', 'sources': {'core_analytics': 'https://analytics.home-assistant.io/data.json', 'core_index': 'https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/generated/integrations.json', 'custom_installs': 'https://analytics.home-assistant.io/custom_integrations.json', 'hacs': 'https://data-v2.hacs.xyz/integration/data.json', 'website': 'https://www.home-assistant.io/integrations.json'}, 'install_floor': 50, 'candidates': 768, 'kept': 112, 'with_roles': 37, 'roles_mined': 68}

#: domain -> what the ecosystem says this integration is.
ROSTER: Final[Dict[str, Dict[str, Any]]] = {
    'alphaess': {'name': 'AlphaESS Energy Storage System', 'repo': 'CharlesGillanders/homeassistant-alphaESS', 'origin': 'hacs', 'installs': 940, 'kind': 'energy', 'kind_from': 'keyword'},
    'anker_solix': {'name': 'Anker Solix', 'repo': 'thomluther/ha-anker-solix', 'origin': 'hacs', 'installs': 5705, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'audiconnect': {'name': 'Audi connect', 'repo': 'audiconnect/audi_connect_ha', 'origin': 'hacs', 'installs': 1887, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'aurora_abb_powerone': {'name': 'Aurora ABB PowerOne Solar PV', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 51, 'kind': 'energy', 'kind_from': 'keyword'},
    'chargepoint': {'name': 'ChargePoint', 'repo': 'mbillow/ha-chargepoint', 'origin': 'hacs', 'installs': 791, 'kind': 'energy', 'kind_from': 'keyword'},
    'dessmonitor': {'name': 'DessMonitor Solar System Integration', 'repo': 'andreas-glaser/ha-dessmonitor', 'origin': 'hacs', 'installs': 240, 'kind': 'energy', 'kind_from': 'keyword'},
    'dsmr': {'name': 'DSMR Smart Meter', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 5699, 'kind': 'energy', 'kind_from': 'keyword'},
    'easee': {'name': 'Easee EV Charger', 'repo': 'nordicopen/easee_hass', 'origin': 'hacs', 'installs': 3533, 'kind': 'energy', 'kind_from': 'keyword'},
    'eg4_web_monitor': {'name': 'EG4 Web Monitor', 'repo': 'joyfulhouse/eg4_web_monitor', 'origin': 'hacs', 'installs': 241, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'energy_meter': {'name': 'Energy meter', 'repo': 'zeronounours/HA-custom-component-energy-meter', 'origin': 'hacs', 'installs': 65, 'kind': 'energy', 'kind_from': 'keyword'},
    'energyzero': {'name': 'EnergyZero', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 2132, 'kind': 'energy', 'kind_from': 'keyword'},
    'enpal_webparser': {'name': 'Enpal Solar', 'repo': 'derolli1976/enpal', 'origin': 'hacs', 'installs': 432, 'kind': 'energy', 'kind_from': 'keyword'},
    'enphase_envoy': {'name': 'Enphase Envoy', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 10259, 'kind': 'energy', 'kind_from': 'keyword'},
    'enphase_ev': {'name': 'Enphase Energy', 'repo': 'barneyonline/ha-enphase-energy', 'origin': 'hacs', 'installs': 323, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'entsoe': {'name': 'ENTSO-e Transparency Platform', 'repo': 'JaccoR/hass-entso-e', 'origin': 'hacs', 'installs': 1476, 'kind': 'energy', 'kind_from': 'keyword'},
    'envertech_solar': {'name': 'Envertech Solar', 'repo': 'jimmybonesde/envertech_solar', 'origin': 'hacs', 'installs': 167, 'kind': 'energy', 'kind_from': 'keyword'},
    'epex_spot': {'name': 'EPEX Spot', 'repo': 'mampfes/ha_epex_spot', 'origin': 'hacs', 'installs': 3638, 'kind': 'energy', 'kind_from': 'keyword'},
    'evcc_intg': {'name': 'evcc☀️🚘- Solar Charging', 'repo': 'marq24/ha-evcc', 'origin': 'hacs', 'installs': 4277, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'forecast_solar': {'name': 'Forecast.Solar', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 64218, 'kind': 'energy', 'kind_from': 'keyword'},
    'foxess': {'name': 'FoxESS Cloud', 'repo': 'macxq/foxess-ha', 'origin': 'hacs', 'installs': 1427, 'kind': 'energy', 'kind_from': 'keyword'},
    'fronius': {'name': 'Fronius', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 9704, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'fusion_solar': {'name': 'Fusion Solar', 'repo': 'tijsverkoyen/HomeAssistant-FusionSolar', 'origin': 'hacs', 'installs': 2815, 'kind': 'energy', 'kind_from': 'keyword'},
    'garo_wallbox': {'name': 'Garo Wallbox', 'repo': 'sockless-coding/garo_wallbox', 'origin': 'hacs', 'installs': 104, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'geo_home': {'name': 'Geo Home Smart Meter Integration', 'repo': 'mmillmor/geo_home', 'origin': 'hacs', 'installs': 124, 'kind': 'energy', 'kind_from': 'keyword'},
    'givenergy_local': {'name': 'GivEnergy Local', 'repo': 'dewet22/givenergy-hass', 'origin': 'hacs', 'installs': 174, 'kind': 'energy', 'kind_from': 'keyword'},
    'goecharger': {'name': 'go-eCharger', 'repo': 'cathiele/homeassistant-goecharger', 'origin': 'hacs', 'installs': 501, 'kind': 'energy', 'kind_from': 'keyword'},
    'goecharger_api2': {'name': 'go-e APIv2 Connect', 'repo': 'marq24/ha-goecharger-api2', 'origin': 'hacs', 'installs': 1377, 'kind': 'energy', 'kind_from': 'keyword'},
    'goecharger_mqtt': {'name': 'go-eCharger integration for Home Assistant using the MQTT AP', 'repo': 'syssi/homeassistant-goecharger-mqtt', 'origin': 'hacs', 'installs': 990, 'kind': 'energy', 'kind_from': 'keyword'},
    'goodwe': {'name': 'GoodWe Inverter (experimental)', 'repo': 'mletenay/home-assistant-goodwe-inverter', 'origin': 'hacs', 'installs': 3399, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'grizzl_e': {'name': 'Grizzl-E EV Charger', 'repo': 'mclare/grizzl_e-for-HA', 'origin': 'hacs', 'installs': 81, 'kind': 'energy', 'kind_from': 'keyword'},
    'growatt_server': {'name': 'growatt_server', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 4399, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'ha_kia_hyundai': {'name': 'Kia/Hyundai/Genesis (USA)', 'repo': 'MarcusTaz/ha_kia_hyundai_USA', 'origin': 'hacs', 'installs': 321, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'homewizard': {'name': 'HomeWizard', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 18805, 'kind': 'energy', 'kind_from': 'keyword'},
    'huawei_solar': {'name': 'Huawei Solar', 'repo': 'wlcrs/huawei_solar', 'origin': 'hacs', 'installs': 5962, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'idm_heatpump': {'name': 'IDM Heatpump', 'repo': 'Xerolux/idm-heatpump-hass', 'origin': 'hacs', 'installs': 175, 'kind': 'energy', 'kind_from': 'keyword'},
    'keba': {'name': 'Keba Charging Station', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 415, 'kind': 'energy', 'kind_from': 'keyword'},
    'kia_uvo': {'name': 'Kia Uvo / Hyundai Bluelink', 'repo': 'Hyundai-Kia-Connect/kia_uvo', 'origin': 'hacs', 'installs': 5779, 'kind': 'appliance', 'kind_from': 'keyword'},
    'kostal_plenticore': {'name': 'Kostal Plenticore Solar Inverter', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 2241, 'kind': 'energy', 'kind_from': 'keyword'},
    'lambda_heat_pumps': {'name': 'Lambda Heat Pumps', 'repo': 'GuidoJeuken-6512/lambda_heat_pumps', 'origin': 'hacs', 'installs': 262, 'kind': 'energy', 'kind_from': 'keyword'},
    'lektrico': {'name': 'Lektrico Charging Station', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 159, 'kind': 'other', 'kind_from': 'keyword'},
    'lxp_modbus': {'name': 'Luxpower Inverter (Modbus)', 'repo': 'ant0nkr/luxpower-ha-integration', 'origin': 'hacs', 'installs': 355, 'kind': 'energy', 'kind_from': 'keyword'},
    'marstek_venus_energy_manager': {'name': 'Marstek Venus Energy Manager', 'repo': 'ffunes/Marstek-Venus-Energy-Manager', 'origin': 'hacs', 'installs': 99, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'must_inverter': {'name': 'Must Inverter', 'repo': 'mukaschultze/ha-must-inverter', 'origin': 'hacs', 'installs': 120, 'kind': 'energy', 'kind_from': 'keyword'},
    'myskoda': {'name': 'MySkoda', 'repo': 'skodaconnect/homeassistant-myskoda', 'origin': 'hacs', 'installs': 4382, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'nibe_heatpump': {'name': 'Nibe Heat Pump', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 1010, 'kind': 'energy', 'kind_from': 'keyword'},
    'nordpool': {'name': 'nordpool', 'repo': 'custom-components/nordpool', 'origin': 'hacs', 'installs': 8288, 'kind': 'energy', 'kind_from': 'keyword'},
    'ocpp': {'name': 'Open Charge Point Protocol (OCPP)', 'repo': 'lbbrhzn/ocpp', 'origin': 'hacs', 'installs': 2336, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'octopus_energy': {'name': 'Octopus Energy', 'repo': 'BottlecapDave/HomeAssistant-OctopusEnergy', 'origin': 'hacs', 'installs': 9944, 'kind': 'energy', 'kind_from': 'keyword'},
    'ohme': {'name': 'Ohme', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 1183, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'omie': {'name': 'OMIE - Spain and Portugal electricity prices', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 269, 'kind': 'other', 'kind_from': 'keyword'},
    'omnik_inverter': {'name': 'Omnik Inverter Solar Sensor (No Cloud)', 'repo': 'robbinjanssen/home-assistant-omnik-inverter', 'origin': 'hacs', 'installs': 333, 'kind': 'energy', 'kind_from': 'keyword'},
    'open_meteo_solar_forecast': {'name': 'Open-Meteo Solar Forecast', 'repo': 'rany2/ha-open-meteo-solar-forecast', 'origin': 'hacs', 'installs': 2414, 'kind': 'energy', 'kind_from': 'keyword'},
    'openevse': {'name': 'OpenEVSE', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 359, 'kind': 'energy', 'kind_from': 'keyword'},
    'peblar': {'name': 'Peblar', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 707, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'polestar_api': {'name': 'Polestar API', 'repo': 'pypolestar/polestar_api', 'origin': 'hacs', 'installs': 1021, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'porscheconnect': {'name': 'Porsche Connect', 'repo': 'CJNE/ha-porscheconnect', 'origin': 'hacs', 'installs': 369, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'pv_management': {'name': 'PV Energy Management Spot', 'repo': 'hoizi89/pv_management', 'origin': 'hacs', 'installs': 64, 'kind': 'energy', 'kind_from': 'keyword'},
    'pv_management_fix': {'name': 'PV Energy Management+', 'repo': 'hoizi89/pv_management_fix', 'origin': 'hacs', 'installs': 52, 'kind': 'energy', 'kind_from': 'keyword'},
    'pysmaplus': {'name': 'SMA Devices Plus', 'repo': 'littleyoda/ha-pysmaplus', 'origin': 'hacs', 'installs': 1112, 'kind': 'energy', 'kind_from': 'keyword'},
    'rct_power': {'name': 'RCT Power', 'repo': 'weltenwort/home-assistant-rct-power-integration', 'origin': 'hacs', 'installs': 446, 'kind': 'energy', 'kind_from': 'keyword'},
    'renault': {'name': 'Renault', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 4096, 'kind': 'vehicle', 'kind_from': 'keyword'},
    'renogy': {'name': 'Renogy', 'repo': 'IAmTheMitchell/renogy-ha', 'origin': 'hacs', 'installs': 148, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'saj': {'name': 'SAJ Solar Inverter', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 206, 'kind': 'other', 'kind_from': 'keyword'},
    'saj_h2_modbus': {'name': 'SAJ H2 Inverter Modbus', 'repo': 'stanus74/home-assistant-saj-h2-modbus', 'origin': 'hacs', 'installs': 208, 'kind': 'energy', 'kind_from': 'keyword'},
    'saj_modbus': {'name': 'SAJ R5 Inverter Modbus', 'repo': 'wimb0/home-assistant-saj-r5-modbus', 'origin': 'hacs', 'installs': 100, 'kind': 'energy', 'kind_from': 'keyword'},
    'sax_battery': {'name': 'SAX Power Home battery management', 'repo': 'matfroh/sax_battery_ha', 'origin': 'hacs', 'installs': 63, 'kind': 'other', 'kind_from': 'keyword'},
    'senec': {'name': 'SENEC.Home V2.x/V3/V4 Systems', 'repo': 'marq24/ha-senec-v3', 'origin': 'hacs', 'installs': 1029, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'sessy': {'name': 'Sessy', 'repo': 'PimDoos/ha-sessy', 'origin': 'hacs', 'installs': 216, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'shelly': {'name': 'ShellyForHass (Shelly integration)', 'repo': 'StyraHem/ShellyForHASS', 'origin': 'hacs', 'installs': 134576, 'kind': 'energy', 'kind_from': 'keyword'},
    'sigen': {'name': 'Sigenergy ESS', 'repo': 'TypQxQ/Sigenergy-Local-Modbus', 'origin': 'hacs', 'installs': 2255, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'silla_prism': {'name': 'Silla Prism Solar wallbox integration', 'repo': 'persuader72/silla-prism-integration', 'origin': 'hacs', 'installs': 76, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'sma': {'name': 'SMA Solar', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 4738, 'kind': 'energy', 'kind_from': 'keyword'},
    'smaev': {'name': 'SMA EV Charger', 'repo': 'alengwenus/ha-sma-ev-charger', 'origin': 'hacs', 'installs': 348, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'smart_meter_texas': {'name': 'Smart Meter Texas', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 666, 'kind': 'energy', 'kind_from': 'keyword'},
    'solar_optimizer': {'name': 'Solar Optimizer', 'repo': 'jmcollin78/solar_optimizer', 'origin': 'hacs', 'installs': 282, 'kind': 'energy', 'kind_from': 'keyword'},
    'solaredge': {'name': 'SolarEdge', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 9182, 'kind': 'energy', 'kind_from': 'keyword'},
    'solaredge_forecast': {'name': 'Solaredge Forecast integration', 'repo': 'nelbs/solaredge-forecast', 'origin': 'hacs', 'installs': 132, 'kind': 'energy', 'kind_from': 'keyword'},
    'solaredge_modbus': {'name': 'Solaredge Modbus', 'repo': 'binsentsu/home-assistant-solaredge-modbus', 'origin': 'hacs', 'installs': 1810, 'kind': 'energy', 'kind_from': 'keyword'},
    'solaredge_modbus_multi': {'name': 'SolarEdge Modbus Multi', 'repo': 'WillCodeForCats/solaredge-modbus-multi', 'origin': 'hacs', 'installs': 2848, 'kind': 'energy', 'kind_from': 'keyword'},
    'solaredgeoptimizers': {'name': 'SolarEdge Optimizers Data', 'repo': 'ProudElm/solaredgeoptimizers', 'origin': 'hacs', 'installs': 636, 'kind': 'energy', 'kind_from': 'keyword'},
    'solarfocus': {'name': 'Solarfocus eco manager-touch', 'repo': 'LavermanJJ/home-assistant-solarfocus', 'origin': 'hacs', 'installs': 68, 'kind': 'energy', 'kind_from': 'keyword'},
    'solarlog': {'name': 'Solar-Log', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 426, 'kind': 'energy', 'kind_from': 'keyword'},
    'solarman': {'name': 'Solarman Integration', 'repo': 'StephanJoubert/home_assistant_solarman', 'origin': 'hacs', 'installs': 9875, 'kind': 'energy', 'kind_from': 'keyword'},
    'solarwatt_manager': {'name': 'SOLARWATT Manager', 'repo': 'thokaro/solarwatt-manager-homeassistant', 'origin': 'hacs', 'installs': 59, 'kind': 'other', 'kind_from': 'keyword'},
    'solax': {'name': 'SolaX Power', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 751, 'kind': 'energy', 'kind_from': 'keyword'},
    'solax_cloud_api': {'name': 'Solax Cloud API for Single and Multi Inverter Systems', 'repo': 'NoUsername10/Solax-Cloud-API-for-Home-assistant', 'origin': 'hacs', 'installs': 259, 'kind': 'energy', 'kind_from': 'keyword'},
    'solax_modbus': {'name': 'SolaX Inverter Modbus', 'repo': 'wills106/homeassistant-solax-modbus', 'origin': 'hacs', 'installs': 2816, 'kind': 'energy', 'kind_from': 'keyword'},
    'solcast_solar': {'name': 'Solcast PV Forecast', 'repo': 'BJReplay/ha-solcast-solar', 'origin': 'hacs', 'installs': 11771, 'kind': 'energy', 'kind_from': 'keyword'},
    'solis': {'name': 'SolisCloud portal integration', 'repo': 'hultenvp/solis-sensor', 'origin': 'hacs', 'installs': 1704, 'kind': 'energy', 'kind_from': 'keyword'},
    'solis_cloud_control': {'name': 'Solis Cloud Control Integration', 'repo': 'mkuthan/solis-cloud-control', 'origin': 'hacs', 'installs': 462, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'solis_modbus': {'name': 'Solis Modbus Integration', 'repo': 'Pho3niX90/solis_modbus', 'origin': 'hacs', 'installs': 608, 'kind': 'energy', 'kind_from': 'keyword'},
    'solplanet': {'name': 'Solplanet inverters', 'repo': 'zbigniewmotyka/home-assistant-solplanet', 'origin': 'hacs', 'installs': 340, 'kind': 'energy', 'kind_from': 'keyword'},
    'stromligning': {'name': 'Strømligning', 'repo': 'MTrab/stromligning', 'origin': 'hacs', 'installs': 562, 'kind': 'energy', 'kind_from': 'keyword'},
    'sungrow': {'name': 'Sungrow iSolarCloud', 'repo': 'KRoperUK/sungrow-hass', 'origin': 'hacs', 'installs': 508, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'sunlit': {'name': 'SunEnergyXT (previously Sunlit Solar)', 'repo': 'cedricziel/ha-sunlit', 'origin': 'hacs', 'installs': 105, 'kind': 'other', 'kind_from': 'keyword'},
    'sunsynk': {'name': 'SunSynk HA Integration', 'repo': 'MarcinG81/SunSynk_HA_Integration', 'origin': 'hacs', 'installs': 59, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'switchbot': {'name': 'SwitchBot', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 23438, 'kind': 'energy', 'kind_from': 'keyword'},
    'thermia': {'name': 'Thermia Heat Pump', 'repo': 'klejejs/ha-thermia-heat-pump-integration', 'origin': 'hacs', 'installs': 246, 'kind': 'energy', 'kind_from': 'keyword'},
    'tibber': {'name': 'Tibber', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 10713, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'toyota': {'name': 'Toyota EU community integration', 'repo': 'pytoyoda/ha_toyota', 'origin': 'hacs', 'installs': 1334, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'tuya_heat_pump': {'name': 'Tuya Heat Pump', 'repo': 'Korkuttum/tuya_heat_pump', 'origin': 'hacs', 'installs': 87, 'kind': 'other', 'kind_from': 'keyword'},
    'uconnect': {'name': 'Uconnect', 'repo': 'hass-uconnect/hass-uconnect', 'origin': 'hacs', 'installs': 697, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'v2c': {'name': 'V2C', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 773, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'v2c_cloud': {'name': 'V2C Cloud', 'repo': 'samuelebistoletti/HomeAssistant-V2C-Cloud', 'origin': 'hacs', 'installs': 105, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'vicare': {'name': 'Viessmann ViCare', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 5930, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'victron': {'name': 'Victron GX modbus TCP', 'repo': 'sfstar/hass-victron', 'origin': 'hacs', 'installs': 1987, 'kind': 'energy', 'kind_from': 'keyword'},
    'victron_mqtt': {'name': 'Victron MQTT Integration', 'repo': 'tomer-w/ha-victron-mqtt', 'origin': 'hacs', 'installs': 1634, 'kind': 'vehicle', 'kind_from': 'vocabulary'},
    'wallbox': {'name': 'Wallbox', 'repo': 'home-assistant/core', 'origin': 'core', 'installs': 2668, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'waterkotte_heatpump': {'name': 'Waterkotte Heatpump [+2020]', 'repo': 'marq24/ha-waterkotte', 'origin': 'hacs', 'installs': 118, 'kind': 'energy', 'kind_from': 'keyword'},
    'wibeee': {'name': 'Wibeee (and Mirubee) energy monitor', 'repo': 'luuuis/hass_wibeee', 'origin': 'hacs', 'installs': 91, 'kind': 'energy', 'kind_from': 'keyword'},
    'zaptec': {'name': 'Zaptec EV charger', 'repo': 'custom-components/zaptec', 'origin': 'hacs', 'installs': 1970, 'kind': 'energy', 'kind_from': 'vocabulary'},
    'zonneplan_one': {'name': 'Zonneplan', 'repo': 'fsaris/home-assistant-zonneplan-one', 'origin': 'hacs', 'installs': 2002, 'kind': 'energy', 'kind_from': 'vocabulary'},
}

#: domain -> role -> the keys that integration DECLARES for it.
#: Only domains whose vocabulary was actually read appear here.
ROLE_VOCAB: Final[Dict[str, Dict[str, Dict[str, Any]]]] = {
    'anker_solix': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('ac_max_charging_power',), 'options': ()},
        'ev_charge_mode': {'platform': 'select', 'keys': ('charger_mode', 'ev_charger_mode'), 'options': ('normal', 'reverse', 'unknown', 'boost_charge', 'skip_delay', 'start_charge', 'stop_charge', 'wait_plug', 'wait_start')},
        'ev_current_control': {'platform': 'number', 'keys': ('max_evcharge_current',), 'options': ()},
    },
    'audiconnect': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('hybrid_range', 'primary_engine_range', 'range', 'secondary_engine_range'), 'options': ()},
        'vehicle_soc': {'platform': 'sensor', 'keys': ('state_of_charge',), 'options': ()},
    },
    'eg4_web_monitor': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('ac_charge_power',), 'options': ()},
        'battery_force_charge': {'platform': 'switch', 'keys': ('quick_charge',), 'options': ()},
        'battery_strategy': {'platform': 'select', 'keys': ('operating_mode',), 'options': ('normal', 'standby')},
        'battery_target_soc': {'platform': 'number', 'keys': ('ac_charge_soc_limit', 'ac_couple_end_soc', 'smart_load_end_soc', 'soc_cutoff', 'system_charge_soc_limit'), 'options': ()},
    },
    'enphase_ev': {
        'ev_charge_mode': {'platform': 'select', 'keys': ('charge_mode',), 'options': ()},
    },
    'evcc_intg': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('configvehicle_range', 'vehiclerange'), 'options': ()},
    },
    'fronius': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('battery_charge_power_limit',), 'options': ()},
        'battery_discharge_limit': {'platform': 'number', 'keys': ('battery_discharge_power_limit',), 'options': ()},
    },
    'garo_wallbox': {
        'ev_current_control': {'platform': 'number', 'keys': ('current_limit',), 'options': ()},
    },
    'goodwe': {
        'battery_strategy': {'platform': 'select', 'keys': ('operation_mode',), 'options': ('backup', 'eco', 'eco_charge', 'eco_discharge', 'general', 'off_grid', 'peak_shaving')},
        'battery_target_soc': {'platform': 'number', 'keys': ('soc_upper_limit',), 'options': ()},
    },
    'growatt_server': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('battery_charge_power_limit',), 'options': ()},
        'battery_discharge_limit': {'platform': 'number', 'keys': ('battery_discharge_power_limit',), 'options': ()},
        'battery_force_charge': {'platform': 'switch', 'keys': ('ac_charge',), 'options': ()},
        'battery_target_soc': {'platform': 'number', 'keys': ('battery_charge_soc_limit', 'battery_discharge_soc_limit_off_grid', 'battery_discharge_soc_limit_on_grid'), 'options': ()},
    },
    'ha_kia_hyundai': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('ev_remaining_range_value', 'total_remaining_range_value'), 'options': ()},
        'vehicle_soc': {'platform': 'sensor', 'keys': ('ev_battery_level',), 'options': ()},
    },
    'huawei_solar': {
        'battery_capacity_spec': {'platform': 'sensor', 'keys': ('rated_ess_capacity', 'storage_rated_capacity'), 'options': ()},
        'battery_charge_limit': {'platform': 'number', 'keys': ('storage_maximum_charging_power',), 'options': ()},
        'battery_discharge_limit': {'platform': 'number', 'keys': ('storage_maximum_discharging_power',), 'options': ()},
        'battery_strategy': {'platform': 'select', 'keys': ('storage_working_mode_settings',), 'options': ('adaptive', 'fixed_charge_discharge', 'fully_fed_to_grid', 'maximise_self_consumption', 'time_of_use_lg', 'time_of_use_luna2000')},
        'battery_target_soc': {'platform': 'number', 'keys': ('storage_capacity_control_soc_peak_shaving',), 'options': ()},
        'system_size_spec': {'platform': 'sensor', 'keys': ('charger_rated_power', 'inverter_rated_power', 'rated_power'), 'options': ()},
    },
    'marstek_venus_energy_manager': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('max_charge_power', 'system_max_charge_power'), 'options': ()},
        'battery_discharge_limit': {'platform': 'number', 'keys': ('max_discharge_power', 'system_max_discharge_power'), 'options': ()},
        'battery_strategy': {'platform': 'select', 'keys': ('user_work_mode',), 'options': ('anti_feed', 'manual', 'trade_mode')},
        'battery_target_soc': {'platform': 'number', 'keys': ('charge_to_soc',), 'options': ()},
    },
    'myskoda': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('adblue_range', 'combustion_range', 'electric_range', 'range'), 'options': ()},
    },
    'ocpp': {
        'ev_current_control': {'platform': 'number', 'keys': ('maximum_current',), 'options': ()},
    },
    'ohme': {
        'ev_charge_mode': {'platform': 'select', 'keys': ('charge_mode',), 'options': ('max_charge', 'paused', 'smart_charge')},
    },
    'peblar': {
        'ev_current_control': {'platform': 'number', 'keys': ('charge_current_limit',), 'options': ()},
    },
    'polestar_api': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('polestar_estimated_full_charge_range', 'polestar_estimated_range'), 'options': ()},
    },
    'porscheconnect': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('remaining_range', 'remaining_range_electric'), 'options': ()},
        'vehicle_soc': {'platform': 'sensor', 'keys': ('state_of_charge',), 'options': ()},
    },
    'renogy': {
        'ev_current_control': {'platform': 'number', 'keys': ('inverter_ac_input_current_limit', 'inverter_charge_current'), 'options': ()},
    },
    'senec': {
        'battery_target_soc': {'platform': 'number', 'keys': ('sockets_1_lower_limit', 'sockets_1_time_limit', 'sockets_1_upper_limit', 'sockets_2_lower_limit', 'sockets_2_time_limit', 'sockets_2_upper_limit'), 'options': ()},
        'system_size_spec': {'platform': 'sensor', 'keys': ('solar_generated_power',), 'options': ()},
    },
    'sessy': {
        'battery_strategy': {'platform': 'select', 'keys': ('battery_strategy',), 'options': ('api', 'eco', 'idle', 'nom', 'roi', 'sessy_connect')},
    },
    'sigen': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('dc_charger_max_charging_power_limit',), 'options': ()},
        'battery_discharge_limit': {'platform': 'number', 'keys': ('dc_charger_max_discharging_power_limit',), 'options': ()},
        'battery_target_soc': {'platform': 'number', 'keys': ('plant_charge_cut_off_soc', 'plant_discharge_cut_off_soc'), 'options': ()},
    },
    'silla_prism': {
        'ev_current_control': {'platform': 'number', 'keys': ('set_current_limit',), 'options': ()},
    },
    'smaev': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('charge_power_limit',), 'options': ()},
        'battery_strategy': {'platform': 'select', 'keys': ('operating_mode_of_charge_session',), 'options': ('boost_charging', 'charge_stop', 'optimized_charging', 'setpoint_charging')},
        'ev_current_control': {'platform': 'number', 'keys': ('charge_current_limit',), 'options': ()},
    },
    'solis_cloud_control': {
        'battery_target_soc': {'platform': 'number', 'keys': ('battery_force_charge_soc', 'battery_max_charge_soc', 'battery_over_discharge_soc'), 'options': ()},
        'ev_current_control': {'platform': 'number', 'keys': ('battery_max_charge_current', 'battery_max_discharge_current'), 'options': ()},
    },
    'sungrow': {
        'battery_target_soc': {'platform': 'number', 'keys': ('forced_charging_target_soc_1', 'forced_charging_target_soc_2', 'soc_lower_limit', 'soc_upper_limit'), 'options': ()},
    },
    'sunsynk': {
        'battery_target_soc': {'platform': 'number', 'keys': ('discharge_min_soc', 'target_soc'), 'options': ()},
        'ev_current_control': {'platform': 'number', 'keys': ('cheap_charge_current', 'normal_charge_current', 'normal_discharge_current', 'peak_discharge_current', 'setting_charge_current', 'setting_discharge_current', 'setting_grid_charge_current'), 'options': ()},
    },
    'tibber': {
        'battery_capacity_spec': {'platform': 'sensor', 'keys': ('storage_rated_capacity',), 'options': ()},
        'system_size_spec': {'platform': 'sensor', 'keys': ('storage_rated_power',), 'options': ()},
    },
    'toyota': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('battery_range', 'total_range'), 'options': ()},
    },
    'uconnect': {
        'vehicle_range': {'platform': 'sensor', 'keys': ('range_total',), 'options': ()},
        'vehicle_soc': {'platform': 'sensor', 'keys': ('battery_state_of_charge', 'state_of_charge'), 'options': ()},
    },
    'v2c': {
        'ev_charge_mode': {'platform': 'select', 'keys': ('charge_mode',), 'options': ('mixed', 'monophasic', 'threephasic')},
    },
    'v2c_cloud': {
        'ev_charge_mode': {'platform': 'select', 'keys': ('charge_mode',), 'options': ()},
    },
    'vicare': {
        'battery_strategy': {'platform': 'select', 'keys': ('dhw_operating_mode',), 'options': ('efficient', 'efficient_with_min_comfort', 'off')},
    },
    'victron_mqtt': {
        'vehicle_soc': {'platform': 'sensor', 'keys': ('ev_soc',), 'options': ()},
    },
    'wallbox': {
        'ev_current_control': {'platform': 'number', 'keys': ('maximum_charging_current',), 'options': ()},
    },
    'zaptec': {
        'ev_current_control': {'platform': 'number', 'keys': ('available_current', 'charger_max_current'), 'options': ()},
    },
    'zonneplan_one': {
        'battery_charge_limit': {'platform': 'number', 'keys': ('max_charge_power',), 'options': ()},
        'battery_discharge_limit': {'platform': 'number', 'keys': ('max_discharge_power',), 'options': ()},
    },
}
