"""#638 — the rename from "overnight planner" to "energy planner" has two
pieces that are BEHAVIOUR, not text.

The subsystem plans the day and the night, so it was misnamed. Renaming a
symbol is free; renaming a *recorded decision* is not. Two names outlived
the code that wrote them:

1. The config option ``overnight_actuation``, written by the v17 migration
   into an upgrading user's entry. A user who turned actuation OFF recorded
   that under the old name. Read the new name only, and their recorded "no"
   becomes silence, and silence defaults back to ON — SEM starts driving
   their hardware again because we renamed a variable.

2. The storage key ``overnight_plan``, holding the plan that is steering
   TONIGHT. Read the new name only and a user who upgrades at 23:50 loses
   the stamp mid-night, which is precisely the reboot-reshuffle this state
   was persisted to prevent.

Both are one-way: read the legacy name, write the new one, never look back.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestActuationChoiceSurvivesTheRename:
    """An explicit answer under the old key is still the user's answer."""

    def _entry(self, options: dict, data: dict | None = None, version: int = 17):
        entry = MagicMock()
        entry.version = version
        entry.minor_version = 1
        entry.data = data if data is not None else {}
        entry.options = options
        entry.entry_id = "test_entry"
        return entry

    async def _migrate(self, entry):
        """Run the real migration and return the (data, options) it wrote."""
        from custom_components.solar_energy_management import (
            async_migrate_entry,
        )

        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        written: dict = {}

        def _update(target, **kwargs):
            written.update(kwargs)
            if "data" in kwargs:
                target.data = kwargs["data"]
            if "options" in kwargs:
                target.options = kwargs["options"]
            if "version" in kwargs:
                target.version = kwargs["version"]
            return True

        hass.config_entries.async_update_entry = MagicMock(side_effect=_update)
        ok = await async_migrate_entry(hass, entry)
        assert ok, "the migration must not fail the entry"
        return written

    @pytest.mark.asyncio
    async def test_an_explicit_no_is_carried_across(self):
        """OFF under the old key stays OFF under the new one.

        This is the whole reason the migration exists: the default is True,
        so a dropped False does not error — it silently turns the hardware
        back on.
        """
        entry = self._entry({"overnight_actuation": False})
        await self._migrate(entry)
        assert entry.options.get("energy_plan_actuation") is False
        assert "overnight_actuation" not in entry.options, (
            "the legacy key must not linger — two keys for one decision is "
            "the next bug"
        )

    @pytest.mark.asyncio
    async def test_an_explicit_yes_is_carried_across(self):
        entry = self._entry({"overnight_actuation": True})
        await self._migrate(entry)
        assert entry.options.get("energy_plan_actuation") is True
        assert "overnight_actuation" not in entry.options

    @pytest.mark.asyncio
    async def test_the_install_time_answer_in_data_is_carried_too(self):
        """``_configured`` reads options THEN data — so data must move too."""
        entry = self._entry({}, data={"overnight_actuation": False})
        await self._migrate(entry)
        assert entry.data.get("energy_plan_actuation") is False
        assert "overnight_actuation" not in entry.data

    @pytest.mark.asyncio
    async def test_options_outrank_data_when_both_carry_a_name(self):
        """A runtime flip is newer than the install-time choice."""
        entry = self._entry({"overnight_actuation": False},
                            data={"overnight_actuation": True})
        await self._migrate(entry)
        assert entry.options.get("energy_plan_actuation") is False

    @pytest.mark.asyncio
    async def test_a_silent_entry_is_left_silent(self):
        """No recorded answer under either name → nothing invented here.

        v17 already writes the default for entries that pass through it;
        v18's job is only to carry a name across, not to re-decide.
        """
        entry = self._entry({"other": 1}, data={"x": 2}, version=17)
        await self._migrate(entry)
        assert "energy_plan_actuation" not in entry.options
        assert "energy_plan_actuation" not in entry.data

    @pytest.mark.asyncio
    async def test_the_switch_reads_what_the_migration_wrote(self):
        """The seam, end to end: migration writes it, the switch reads it.

        Two halves of one contract — a test that pins only the migration
        would pass while the switch still asked for the old name.
        """
        from custom_components.solar_energy_management.switch import (
            SEMSolarSwitch,
        )

        entry = self._entry({"overnight_actuation": False})
        await self._migrate(entry)

        switch = SEMSolarSwitch.__new__(SEMSolarSwitch)
        switch.coordinator = MagicMock()
        switch.coordinator.config_entry = entry
        switch.coordinator.config = dict(entry.data)
        assert switch._configured("energy_plan_actuation") is False


class TestTonightsPlanSurvivesTheRename:
    """A stamped plan is live state — an upgrade must not drop it."""

    def _store(self, energy_data: dict):
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )

        store = SEMStorage.__new__(SEMStorage)
        store._energy_data = energy_data
        return store

    def test_a_plan_stamped_under_the_old_key_is_still_read(self):
        store = self._store({"overnight_plan": {"stamp": "23:40",
                                                "demands": ["ev:keba"]}})
        assert store.get_energy_plan_state()["stamp"] == "23:40"

    def test_the_new_key_wins_when_both_exist(self):
        """One upgrade, one re-stamp: the fresh plan is the new key's."""
        store = self._store({"overnight_plan": {"stamp": "old"},
                             "energy_plan": {"stamp": "new"}})
        assert store.get_energy_plan_state()["stamp"] == "new"

    def test_writing_never_revives_the_old_key(self):
        data = {"overnight_plan": {"stamp": "old"}}
        store = self._store(data)
        store.set_energy_plan_state({"stamp": "new"})
        assert data["energy_plan"] == {"stamp": "new"}
        assert "overnight_plan" not in data, (
            "the legacy key is read once and retired; leaving it behind "
            "means the next reboot can read a stale night"
        )

    def test_no_plan_at_all_is_still_an_empty_dict(self):
        assert self._store({}).get_energy_plan_state() == {}


class TestTheSwitchEntityIsCarriedNotAbandoned:
    """The kill-switch's identity changes — the entity must follow it.

    ``unique_id`` is ``sem_{key}``, so the rename mints a NEW identity.
    Left alone, HA registers a second switch and the old registry entry
    lingers forever as an unavailable orphan: the user sees two
    kill-switches, one of which does nothing, and their recorded history
    stops. Rename the registry entry instead — one entity, one history.
    """

    def _registry_with(self, unique_id: str, entity_id: str):
        entries = {}

        class _Entry:
            def __init__(self, uid, eid):
                self.unique_id = uid
                self.entity_id = eid
                self.domain = eid.split(".")[0]
                self.platform = "solar_energy_management"

        class _Registry:
            def __init__(self):
                self.updates = []

            def async_get_entity_id(self, domain, platform, uid):
                for e in entries.values():
                    if e.unique_id == uid and e.domain == domain:
                        return e.entity_id
                return None

            def async_update_entity(self, eid, **kw):
                self.updates.append((eid, kw))
                e = entries.pop(eid)
                if "new_unique_id" in kw:
                    e.unique_id = kw["new_unique_id"]
                if "new_entity_id" in kw:
                    e.entity_id = kw["new_entity_id"]
                entries[e.entity_id] = e
                return e

        entries[entity_id] = _Entry(unique_id, entity_id)
        return _Registry(), entries

    def _rename(self, registry):
        from custom_components.solar_energy_management import (
            _async_rename_actuation_switch,
        )

        _async_rename_actuation_switch(registry)

    def test_the_old_switch_is_renamed_not_duplicated(self):
        registry, entries = self._registry_with(
            "sem_overnight_actuation", "switch.sem_overnight_actuation")
        self._rename(registry)
        assert list(entries) == ["switch.sem_energy_plan_actuation"], (
            "one entity in, one entity out — a duplicate is the bug"
        )
        assert entries["switch.sem_energy_plan_actuation"].unique_id == (
            "sem_energy_plan_actuation")

    def test_a_user_renamed_entity_id_keeps_its_name(self):
        """Only the identity is ours; the entity_id may be the user's.

        Someone who renamed the switch to fit their own scheme chose that
        name. Carry the unique_id so the entity survives; leave a name we
        did not pick alone.
        """
        registry, entries = self._registry_with(
            "sem_overnight_actuation", "switch.night_boss")
        self._rename(registry)
        assert list(entries) == ["switch.night_boss"]
        assert entries["switch.night_boss"].unique_id == (
            "sem_energy_plan_actuation")

    def test_an_already_renamed_install_is_untouched(self):
        """Idempotent — this runs on every setup, not once."""
        registry, entries = self._registry_with(
            "sem_energy_plan_actuation", "switch.sem_energy_plan_actuation")
        self._rename(registry)
        assert registry.updates == []

    def test_a_fresh_install_has_nothing_to_rename(self):
        registry, entries = self._registry_with("sem_observer_mode",
                                                "switch.sem_observer_mode")
        self._rename(registry)
        assert registry.updates == []
