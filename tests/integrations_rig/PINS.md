# The crawler rig — what each capture is

A capture is one integration's output at a pin: the entities it registered
(with the metadata SEM's crawler reads), their states, its services.
`tests/test_integrations_rig.py` replays each one into a real Home Assistant
test instance and runs SEM's crawler on it. The crawler's view is kept in
`crawler/<name>.json`; a change shows up as a failing test with a diff.

Nothing here ships: `tests/` is left out of the release zip
(`scripts/build_release_zip.sh`, checked by `scripts/verify_release_zip.py`).

## Three kinds, strongest first

| kind | what it is |
|---|---|
| `core-snapshot` | Home Assistant core's OWN test output for the integration (`tests/components/<domain>/snapshots/*.ambr`) at the tag. No SEM-written data. The snapshot does not record devices; they are rebuilt from `unique_id`. |
| `live-load` | The real integration set up in a Home Assistant test instance, its client patched with test data (its own fixtures where it has them). |
| `live-install` | The registry rows and states of a real device on a SEM test install, plus the integration's services at the tag. |
| `declared` | Read from the integration's own entity descriptions at a commit, for cloud-only integrations that cannot run offline. Keys, device classes and units are the integration's; which entities an account gets, and the entity ids, are built the way it builds them, not observed. The weakest kind — said so in the capture. |

## Pins

| capture | kind | source | pin |
|---|---|---|---|
| `tesla_fleet` | core-snapshot | home-assistant/core | 2026.8.2 |
| `teslemetry` | core-snapshot | home-assistant/core | 2026.8.2 |
| `tessie` | core-snapshot | home-assistant/core | 2026.8.2 |
| `nrgkick` | core-snapshot | home-assistant/core | 2026.8.2 |
| `ohme` | core-snapshot | home-assistant/core | 2026.8.2 |
| `peblar` | core-snapshot | home-assistant/core | 2026.8.2 |
| `v2c` | core-snapshot | home-assistant/core | 2026.8.2 |
| `openevse` | core-snapshot | home-assistant/core | 2026.8.2 |
| `vicare` | core-snapshot | home-assistant/core | 2026.8.2 |
| `blue_current` | core-snapshot | home-assistant/core | 2026.8.2 (core snapshots only its buttons) |
| `tesla_wall_connector` | live-load | home-assistant/core 2026.8.2, client `tesla-wall-connector==1.2.0` | values from core's own `conftest.py` |
| `myenergi` | live-load | CJNE/ha-myenergi | `ce5aca11dfe87b1644d73962d38d5797a21bcde4` (2026-07-22), client `pymyenergi==0.2.3`, its own `tests/fixtures` |
| `zaptec`, `zaptec_no_limit` | declared | custom-components/zaptec | `ba502a9971355e60b84b0356650a50e6ab403d11` (2026-08-26); `zaptec_no_limit` is an account without the right to set the current (#1032) |
| `keba` | live-install | the real KEBA P30 on .175 (02.10.2026), services from core 2026.8.2 | a device-less, service-driven charger |
| `easee` | declared | nordicopen/easee_hass | `ea85bb5fa9f093594a50606a786ee9fd03d6a662` (2026-09-22) |
| `goecharger` | declared | cathiele/homeassistant-goecharger (HACS, v0.27.0) + goecharger 0.0.16 | 1d28e0f582e0a99354b520d26e1d867948e5d58c |
| `entsoe`, `entsoe_named_15m` | live-load | JaccoR/hass-entso-e | v0.7.5, `cbdf67ac0e73fd685a02e27ad7b6bef2c5af7ca6` (2026-02-16); the API's answer is its own `test/datasets` (DE-LU hourly; BE 15-minute with an entity name), 6 October 2024 14:07 local (#1051) |
| `helios_forecast` | live-load | ReikanYsora/Helios-Forecast | 2026.9.6, `da8fa3e7218aaedf47e50518c21df74b9aef70e0` (2026-09-08); weather from its own `tests/ha/_weather.py`, one 10 kWp line, Zurich, 21 June 2026 12:00 local. Sensors it ships disabled stay disabled (#1050) |

## Refresh one

    cd tests/integrations_rig/capture_tools
    # core snapshot (run with the test venv's python, so services.yaml is the pinned one)
    ~/.venvs/sem-314/bin/python snapshot_to_capture.py tesla_fleet --device-split -
    # declared (Zaptec)
    ~/.venvs/sem-314/bin/python declared_capture.py <zaptec checkout>/custom_components/zaptec \
        --domain zaptec --repo custom-components/zaptec --out zaptec.json \
        --device "INSTALLATION_ENTITIES=installation:Abbastova:inst1" \
        --device "CHARGER_ENTITIES=charger:Zaptec Go2 ZAP012345:chg1"

The live captures carry their own run instructions in
`capture_tools/live_*.py`. Then regenerate the crawler's view and read the
diff before committing it:

    SEM_RIG_UPDATE=1 SEM_SRC=<tree> ~/bin/semtest tests/test_integrations_rig.py

## Not loaded, and why

- **Easee, Zaptec live:** cloud-only; their own tests need an account
  (Zaptec) or have no offline data (easee_hass). Declared instead.
- **EG4 / Luxpower:** not captured in this wave; R7 waits for the #810
  inverter.
- **HACS charger integrations in the matrix** (go-e, openWB, OCPP, Alfen,
  Heidelberg, ChargePoint, ABL, Wallbox MQTT): no offline test data in their
  repos; see `docs/hardware_proof.md`.
