"""#815 follow-up: the backfill button repairs a derived entity_id on upgrade.

``SEMButton.__init__`` forces ``button.sem_backfill_battery_nights`` — but
``self.entity_id`` is only a *suggestion* HA honours at FIRST registration.
An install that registered the button before that line existed keeps the
id HA derived from device + translated name
(``button.garden_sem_rebuild_battery_night_history`` on the .175 rig,
01.09.2026), and every card, doc and automation addressing the stable id
finds "Entity not found". switch/number/sensor all run a registry repair
at setup for exactly this; the button platform did not.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.button import async_setup_entry

STABLE = "button.sem_backfill_battery_nights"
DERIVED = "button.garden_sem_rebuild_battery_night_history"
UID = "sem_backfill_battery_nights"


class _Registry:
    def __init__(self, entries):
        self.entries = {e.entity_id: e for e in entries}
        self.renames: list[tuple[str, str]] = []

    def async_get(self, entity_id):
        return self.entries.get(entity_id)

    def async_update_entity(self, entity_id, **changes):
        self.renames.append((entity_id, changes.get("new_entity_id")))


def _entry(entity_id, unique_id=UID, domain="button"):
    return SimpleNamespace(entity_id=entity_id, unique_id=unique_id, domain=domain)


async def _setup(monkeypatch, registry):
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(er, "async_get", lambda hass: registry)
    monkeypatch.setattr(
        er, "async_entries_for_config_entry",
        lambda reg, entry_id: list(reg.entries.values()),
    )
    entry = MagicMock()
    entry.entry_id = "entry_815"
    coordinator = MagicMock()
    hass = MagicMock()
    hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    await async_setup_entry(hass, entry, lambda ents: list(ents))


@pytest.mark.unit
class TestButtonEntityIdRepair815:

    async def test_derived_id_is_renamed_to_the_stable_one(self, monkeypatch):
        reg = _Registry([_entry(DERIVED)])
        await _setup(monkeypatch, reg)
        assert reg.renames == [(DERIVED, STABLE)], (
            "the button kept the id HA derived at first registration — "
            "button.sem_backfill_battery_nights stays 'Entity not found' "
            "on every install that predates the #815 id line"
        )

    async def test_stable_id_is_left_alone(self, monkeypatch):
        reg = _Registry([_entry(STABLE)])
        await _setup(monkeypatch, reg)
        assert reg.renames == []

    async def test_no_rename_when_the_stable_id_is_taken(self, monkeypatch):
        reg = _Registry([_entry(DERIVED), _entry(STABLE, unique_id="someone_else")])
        await _setup(monkeypatch, reg)
        assert reg.renames == [], "must never clobber a foreign entity"

    async def test_other_platforms_are_not_touched(self, monkeypatch):
        reg = _Registry([_entry("sensor.garden_sem_thing", domain="sensor")])
        await _setup(monkeypatch, reg)
        assert reg.renames == []
