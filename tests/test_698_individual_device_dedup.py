"""#698 — one physical device must yield ONE load-management row.

@Azlinon's JuiceBox (via JuiceBoxProxy/MQTT) exposes BOTH an ``…_energy_lifetime``
and an ``…_energy_session`` sensor — both ``total_increasing``, same HA device.
HA's Energy Dashboard picks both up as individual devices, and SEM then built a
load row per ENERGY SENSOR, so every EVSE appeared twice under Load Management.

Fix: ``get_all_individual_devices`` folds same-measurement variants — entries
whose object_ids differ only by a trailing variant token (lifetime / session /
total / today / daily) — preferring the monotonic lifetime/total counter.
Distinct loads that merely share a device (e.g. a Shelly 2PM's two channels)
have different stems and are never folded; when the entity registry can prove
two stems-alike sensors live on DIFFERENT devices, the fold is vetoed.
"""
from unittest.mock import MagicMock

from custom_components.solar_energy_management.ha_energy_reader import (
    get_all_individual_devices,
)


def _config(*consumptions):
    cfg = MagicMock()
    cfg.device_consumption = [
        {"stat_consumption": c, "name": "", "stat_rate": None} for c in consumptions
    ]
    return cfg


class TestVariantFolding:
    def test_juicebox_lifetime_and_session_fold_to_one(self):
        devices = get_all_individual_devices(_config(
            "sensor.juicebox_abc123_energy_lifetime",
            "sensor.juicebox_abc123_energy_session",
        ))
        assert len(devices) == 1
        # the monotonic lifetime counter wins over the per-charge session one
        assert devices[0]["energy_sensor"] == "sensor.juicebox_abc123_energy_lifetime"

    def test_two_chargers_stay_two_devices(self):
        devices = get_all_individual_devices(_config(
            "sensor.juicebox_abc123_energy_lifetime",
            "sensor.juicebox_abc123_energy_session",
            "sensor.juicebox_def456_energy_lifetime",
            "sensor.juicebox_def456_energy_session",
        ))
        assert len(devices) == 2
        sensors = {d["energy_sensor"] for d in devices}
        assert sensors == {
            "sensor.juicebox_abc123_energy_lifetime",
            "sensor.juicebox_def456_energy_lifetime",
        }

    def test_total_beats_daily(self):
        devices = get_all_individual_devices(_config(
            "sensor.heatpump_energy_daily",
            "sensor.heatpump_energy_total",
        ))
        assert len(devices) == 1
        assert devices[0]["energy_sensor"] == "sensor.heatpump_energy_total"

    def test_shelly_channels_are_distinct_loads(self):
        # channel object_ids don't end in a variant token → different stems →
        # two real loads, never folded
        devices = get_all_individual_devices(_config(
            "sensor.shelly_2pm_channel_a_energy",
            "sensor.shelly_2pm_channel_b_energy",
        ))
        assert len(devices) == 2

    def test_plain_sensors_unaffected(self):
        devices = get_all_individual_devices(_config(
            "sensor.dishwasher_energy",
            "sensor.dryer_energy",
        ))
        assert len(devices) == 2

    def test_fold_keeps_power_sensor_and_is_ev(self):
        cfg = MagicMock()
        cfg.device_consumption = [
            {"stat_consumption": "sensor.wallbox_energy_session", "name": "",
             "stat_rate": "sensor.wallbox_power"},
            {"stat_consumption": "sensor.wallbox_energy_lifetime", "name": ""},
        ]
        devices = get_all_individual_devices(cfg)
        assert len(devices) == 1
        d = devices[0]
        assert d["energy_sensor"] == "sensor.wallbox_energy_lifetime"
        # the folded sibling's power sensor is kept, and so is the EV marker
        assert d["power_sensor"] == "sensor.wallbox_power"
        assert d["is_ev"] is True

    def test_registry_veto_keeps_devices_apart(self, monkeypatch):
        """Same stem but the entity registry proves two DIFFERENT devices →
        the fold is vetoed and both loads survive. No registry info → fold."""
        import custom_components.solar_energy_management.ha_energy_reader as har

        # two same-stem sensors that the registry places on different devices
        monkeypatch.setattr(
            har, "_registry_device_id",
            lambda hass, e: ("dev_a" if "_total" in e else "dev_b")
            if hass is not None else None,
        )
        devices = get_all_individual_devices(_config(
            "sensor.plug_abc_energy_total",
            "sensor.plug_abc_energy_daily",
        ), hass=MagicMock())
        assert len(devices) == 2              # registry veto — kept apart

        devices = get_all_individual_devices(_config(
            "sensor.plug_abc_energy_total",
            "sensor.plug_abc_energy_daily",
        ), hass=None)
        assert len(devices) == 1              # no registry info → stems fold
