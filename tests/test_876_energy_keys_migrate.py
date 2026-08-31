"""#876 — an old entry never gets the Energy-Dashboard sensor keys.

`config_flow.py:469` merges `EnergyDashboardConfig.to_dict()` into the entry
**when the entry is created**. Nothing does it afterwards, and
`async_migrate_entry` carried entries from v1 to v18 without ever adding
them.

The rigs hide it: `deploy-test.sh` re-creates the entry on every clean
install, so `.175` and `.46` always have the keys. PROD's entry was created
2025-11-10 and has never been re-installed — 35 data keys against `.175`'s
40, the difference being exactly these five, on identical hardware with
`energy_source_auto = True` on both.

The one consumer that matters reads the entry, not the live dashboard:

    coordinator/night_backfill.py:182
    discharge_id = (config.get("battery_discharge_energy_sensor")
                    or config.get("battery_energy_discharged_sensor"))

so `backfill_battery_nights` answers "no battery discharge energy sensor
configured" and writes nothing — on precisely the oldest installs, the ones
whose history is worth recovering. Nine months of PROD's nights sat
unreachable behind a missing dictionary key.

The migration is additive by construction: it fills only what is ABSENT, so a
user's own explicit pick is never overwritten, and a missing or unreadable
Energy Dashboard leaves the entry exactly as it was rather than failing setup.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


ENERGY_KEYS = (
    "solar_energy_sensor",
    "grid_import_energy_sensor",
    "grid_export_energy_sensor",
    "battery_charge_energy_sensor",
    "battery_discharge_energy_sensor",
)


def _entry(data=None, options=None, version=18, minor=1):
    e = MagicMock()
    e.version = version
    e.minor_version = minor
    e.data = dict(data or {})
    e.options = dict(options or {})
    return e


def _hass():
    hass = MagicMock()
    updates = {}

    def _update(entry, **kw):
        updates.update(kw)
        if "data" in kw:
            entry.data = kw["data"]
        if "options" in kw:
            entry.options = kw["options"]
        if "version" in kw:
            entry.version = kw["version"]
        if "minor_version" in kw:
            entry.minor_version = kw["minor_version"]
        return True

    hass.config_entries.async_update_entry = MagicMock(side_effect=_update)
    return hass, updates


def _dashboard(**over):
    """A dashboard config shaped like the real reader's output."""
    cfg = MagicMock()
    cfg.to_dict.return_value = {
        "solar_energy_sensor": "sensor.inverter_gesamtenergieertrag",
        "grid_import_energy_sensor": "sensor.power_meter_verbrauch",
        "grid_export_energy_sensor": "sensor.power_meter_einspeisung",
        "battery_charge_energy_sensor": "sensor.battery_1_gesamtladung",
        "battery_discharge_energy_sensor": "sensor.battery_1_gesamtentladung",
        "solar_power_sensor": "sensor.inverter_eingangsleistung",
        "has_battery": True,
        **over,
    }
    return cfg


async def _migrate(hass, entry):
    from custom_components.solar_energy_management import async_migrate_entry
    return await async_migrate_entry(hass, entry)


@pytest.mark.asyncio
class TestAnOldEntryGetsTheKeys:
    async def test_the_backfills_key_is_filled_in(self):
        """The whole point: night_backfill.py:182 can find its sensor."""
        hass, _ = _hass()
        entry = _entry(data={"battery_capacity_kwh": 12.6})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(return_value=_dashboard()),
        ):
            assert await _migrate(hass, entry) is True
        merged = {**entry.data, **entry.options}
        assert merged.get("battery_discharge_energy_sensor") == \
            "sensor.battery_1_gesamtentladung", (
            "the one key backfill_battery_nights reads is still missing — "
            "the service answers 'no battery discharge energy sensor "
            "configured' on every pre-existing install"
        )

    async def test_every_energy_key_is_filled_in(self):
        hass, _ = _hass()
        entry = _entry(data={})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(return_value=_dashboard()),
        ):
            await _migrate(hass, entry)
        merged = {**entry.data, **entry.options}
        missing = [k for k in ENERGY_KEYS if not merged.get(k)]
        assert not missing, f"still absent after migration: {missing}"

    async def test_it_only_carries_energy_keys(self):
        """to_dict() also carries power sensors and has_* flags. The entry's
        own detection owns those; this migration is about the counters the
        backfill needs, and a migration that quietly rewrites the live
        steering inputs is a much bigger promise than the one being made."""
        hass, _ = _hass()
        entry = _entry(data={})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(return_value=_dashboard()),
        ):
            await _migrate(hass, entry)
        merged = {**entry.data, **entry.options}
        assert "solar_power_sensor" not in merged
        assert "has_battery" not in merged


@pytest.mark.asyncio
class TestItNeverOverwritesAChoice:
    async def test_an_existing_key_is_left_alone(self):
        """A user who picked their own counter keeps it."""
        hass, _ = _hass()
        entry = _entry(data={
            "battery_discharge_energy_sensor": "sensor.my_own_pick"})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(return_value=_dashboard()),
        ):
            await _migrate(hass, entry)
        merged = {**entry.data, **entry.options}
        assert merged["battery_discharge_energy_sensor"] == "sensor.my_own_pick"

    async def test_a_key_set_in_options_is_left_alone(self):
        """options shadow data — a migration must read the same merged view
        the coordinator does, or it 'fills' a key that was never missing."""
        hass, _ = _hass()
        entry = _entry(data={}, options={
            "battery_discharge_energy_sensor": "sensor.chosen_in_options"})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(return_value=_dashboard()),
        ):
            await _migrate(hass, entry)
        merged = {**entry.data, **entry.options}
        assert merged["battery_discharge_energy_sensor"] == \
            "sensor.chosen_in_options"
        assert "battery_discharge_energy_sensor" not in entry.data, (
            "wrote a duplicate into data that now shadows nothing but will "
            "confuse the next reader"
        )


@pytest.mark.asyncio
class TestItNeverCostsTheUserTheirSetup:
    async def test_no_energy_dashboard_is_not_a_failure(self):
        """A solar-only install with no Energy Dashboard must still load."""
        hass, _ = _hass()
        entry = _entry(data={"battery_capacity_kwh": 12.6})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(return_value=None),
        ):
            assert await _migrate(hass, entry) is True
        assert entry.data.get("battery_capacity_kwh") == 12.6

    async def test_a_raising_reader_is_not_a_failure(self):
        hass, _ = _hass()
        entry = _entry(data={"battery_capacity_kwh": 12.6})
        with patch(
            "custom_components.solar_energy_management.ha_energy_reader"
            ".read_energy_dashboard_config",
            new=AsyncMock(side_effect=Exception("recorder is not up yet")),
        ):
            assert await _migrate(hass, entry) is True
        assert entry.data.get("battery_capacity_kwh") == 12.6
