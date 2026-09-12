"""#935 — SEM hands the house back as it found it and takes its own files.

@markusschloesser ran Spook after removing SEM (#908) and found 119 leftover
long-term statistics. The statistics turned out to be the smallest part:
removal deleted a config entry and released the loads SEM had started, and
left behind every store it had written, its version marker, its Repairs, the
Lovelace resources pointing at files that were about to vanish, and a wallbox
SEM had parked — holding "no" with nothing left on the system to say "yes".

The three rules under test: hand the hardware back (and ONLY what SEM
commanded), take SEM's own files, and merely OFFER what is the user's.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management import cleanup

ENTRY = "01ABCDEFGHIJKLMNOPQRSTUVWX"
OTHER = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"


def _run(coro):
    return asyncio.run(coro)


def _hass_with_storage(tmp_path, names=()):
    storage = tmp_path / ".storage"
    storage.mkdir(exist_ok=True)
    for n in names:
        (storage / n).write_text("{}")
    return SimpleNamespace(
        config=SimpleNamespace(config_dir=str(tmp_path)),
        services=SimpleNamespace(async_call=AsyncMock()),
    )


class TestTheInventoryKnowsWhatThisEntryOwns:
    def test_every_per_entry_store_is_named(self):
        keys = cleanup.per_entry_store_keys(ENTRY)
        assert f"solar_energy_management_{ENTRY}_energy" in keys
        assert f"solar_energy_management_{ENTRY}_daily" in keys
        assert f"sem_seen_version_{ENTRY}" in keys
        assert f"sem.pacing.{ENTRY}" in keys, "#949's record is SEM's too"

    def test_the_second_scoped_stores_are_prefixes(self):
        pre = cleanup.per_entry_store_prefixes(ENTRY)
        assert f"sem.deye.snapshot.{ENTRY}." in pre
        assert f"sem.deye.unsafe.{ENTRY}." in pre

    def test_an_empty_entry_id_owns_nothing(self):
        """A degenerate id would prefix-match every entry's stores — the
        #709 scope rule, on the delete side where it costs more."""
        assert cleanup.per_entry_store_keys("") == []
        assert cleanup.per_entry_store_prefixes("") == []

    def test_install_wide_stores_are_separate(self):
        wide = cleanup.install_wide_store_keys()
        assert "sem_device_mappings" in wide
        assert "solar_energy_management_load_management_devices" in wide
        # the retired names, still live on PROD
        assert "solar_energy_management_daily_storage" in wide
        assert "solar_energy_management_energy_totals" in wide

    def test_no_per_entry_key_is_also_install_wide(self):
        assert not (set(cleanup.per_entry_store_keys(ENTRY))
                    & set(cleanup.install_wide_store_keys()))


class TestTheOrphanSweep:
    def test_a_removed_entrys_stores_are_orphans(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            f"solar_energy_management_{ENTRY}_energy",
            f"solar_energy_management_{ENTRY}_daily",
            f"sem_seen_version_{ENTRY}",
            f"solar_energy_management_{OTHER}_energy",
            f"sem_seen_version_{OTHER}",
        ])
        orphans = cleanup.orphan_store_keys(hass, [ENTRY])
        assert sorted(orphans) == sorted([
            f"solar_energy_management_{OTHER}_energy",
            f"sem_seen_version_{OTHER}",
        ])

    def test_a_live_entrys_stores_are_never_orphans(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            f"solar_energy_management_{ENTRY}_daily",
            f"sem.pacing.{ENTRY}",
            f"sem.deye.snapshot.{ENTRY}.battery_1",
        ])
        assert cleanup.orphan_store_keys(hass, [ENTRY]) == []

    def test_install_wide_stores_survive_the_sweep(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            "sem_device_mappings",
            "solar_energy_management_load_management_devices",
            "solar_energy_management_daily_storage",
        ])
        assert cleanup.orphan_store_keys(hass, [ENTRY]) == []

    def test_a_store_nobody_taught_it_about_is_left_alone(self, tmp_path):
        """Deleting an unrecognised file is how a cleanup becomes the problem
        it was written to solve."""
        hass = _hass_with_storage(tmp_path, ["sem_something_new_entirely"])
        assert cleanup.orphan_store_keys(hass, [ENTRY]) == []

    def test_backups_are_not_swept(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            f"solar_energy_management_{OTHER}_energy.bak.1780495914",
            f"solar_energy_management_{OTHER}_energy.bak",
        ])
        assert cleanup.orphan_store_keys(hass, [ENTRY]) == []

    def test_no_storage_directory_is_not_a_crash(self):
        hass = SimpleNamespace(config=SimpleNamespace(config_dir="/nope/nope"))
        assert cleanup.existing_store_files(hass) == []
        assert cleanup.orphan_store_keys(hass, [ENTRY]) == []


class TestRepairsGoWithTheIntegration:
    def _registry(self, keys):
        return SimpleNamespace(issues={k: object() for k in keys})

    def test_every_sem_issue_is_deleted_and_nothing_else(self, monkeypatch):
        deleted = []
        reg = self._registry([
            ("solar_energy_management", "split_grid_guessed"),
            ("solar_energy_management", "soc_zones_out_of_order"),
            ("some_other_integration", "not_ours"),
        ])
        monkeypatch.setattr(
            "homeassistant.helpers.issue_registry.async_get",
            lambda hass: reg)
        monkeypatch.setattr(
            "homeassistant.helpers.issue_registry.async_delete_issue",
            lambda hass, domain, issue_id: deleted.append((domain, issue_id)))
        n = cleanup.delete_repairs(SimpleNamespace())
        assert n == 2
        assert ("some_other_integration", "not_ours") not in deleted
        assert sorted(i for _, i in deleted) == [
            "soc_zones_out_of_order", "split_grid_guessed"]

    def test_an_unreadable_registry_reports_zero_not_a_crash(self, monkeypatch):
        monkeypatch.setattr(
            "homeassistant.helpers.issue_registry.async_get",
            MagicMock(side_effect=RuntimeError("no registry")))
        assert cleanup.delete_repairs(SimpleNamespace()) == 0


class TestTheFrontendResources:
    def test_sems_own_resources_are_recognised(self):
        assert cleanup._is_sem_resource(
            "/solar_energy_management/dashboard/card/dist/sem-cards.js?v=2.1.0-abc")
        assert cleanup._is_sem_resource(
            "/solar_energy_management/dashboard/card/sem-localize.js")

    def test_someone_elses_resource_is_not(self):
        assert not cleanup._is_sem_resource("/hacsfiles/mushroom/mushroom.js")
        assert not cleanup._is_sem_resource("/local/my-own/sem-cards.js")
        assert not cleanup._is_sem_resource("")
        assert not cleanup._is_sem_resource(None)


class TestStatisticsAreTheUsersUntilTheySaySo:
    def test_clearing_asks_the_recorder_with_sems_own_ids(self):
        hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        n = _run(cleanup.async_clear_statistics(
            hass, ["sensor.sem_solar_power", "sensor.sem_battery_soc"]))
        assert n == 2
        call = hass.services.async_call.await_args
        assert call.args[0] == "recorder" and call.args[1] == "clear_statistics"
        assert call.args[2]["statistic_ids"] == [
            "sensor.sem_solar_power", "sensor.sem_battery_soc"]

    def test_nothing_to_clear_calls_nothing(self):
        hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        assert _run(cleanup.async_clear_statistics(hass, [])) == 0
        assert hass.services.async_call.await_count == 0

    def test_a_missing_recorder_is_reported_not_raised(self):
        hass = SimpleNamespace(services=SimpleNamespace(
            async_call=AsyncMock(side_effect=RuntimeError("no recorder"))))
        assert _run(cleanup.async_clear_statistics(hass, ["sensor.x"])) == 0


class TestTheDashboardIsOfferedNeverTaken:
    def test_both_halves_go_together(self, monkeypatch):
        """The view config and the sidebar row are separate files; leaving
        either behind gives a broken sidebar entry or an invisible orphan."""
        removed_keys = []
        saved = {}

        class FakeStore:
            def __init__(self, hass, version, key):
                self.key = key

            async def async_remove(self):
                removed_keys.append(self.key)

            async def async_load(self):
                return {"items": [{"id": "sem-dashboard"}, {"id": "mine"}]}

            async def async_save(self, data):
                saved.update(data)

        monkeypatch.setattr("homeassistant.helpers.storage.Store", FakeStore)
        assert _run(cleanup.async_remove_dashboard(SimpleNamespace())) is True
        assert "lovelace.sem-dashboard" in removed_keys
        assert [i["id"] for i in saved["items"]] == ["mine"], (
            "someone else's dashboard must survive")

    def test_it_is_not_part_of_the_automatic_teardown(self):
        """Nothing in the removal path may call it — a year of solar yield is
        not SEM's to throw away because a config entry is being deleted."""
        import inspect

        from custom_components import solar_energy_management as sem

        src = inspect.getsource(sem._async_take_sems_own_files)
        assert "async_remove_dashboard" not in src
        assert "async_clear_statistics" not in src
