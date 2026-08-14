"""#744 — lights are filtered out at the Energy Dashboard import.

Guido, 14.08: "What is the use case for lights in SEM?" — there is none.
Lighting is not shiftable, not a surplus sink, and shedding a 30 W dimmer
is hostility for savings that round to zero. Lights only ever arrived as
a side effect of Energy-Dashboard consumption monitoring, and then showed
wrong on/off state (Matter dimmers reading On while off) because a light
is exactly the shape the power heuristic cannot judge.

So auto-import skips them at the door: an ED individual device whose HA
device carries ``light.*`` entities and NO switch is a light fixture —
HA's own dashboard keeps monitoring it; SEM has no business with it. A
metering smart plug feeding a lamp keeps its row (the plug is a real
control), and the explicit ``register_surplus_device`` path is untouched
for the rare relay-exposed-as-light case.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.load_device_discovery import (
    LoadDeviceDiscovery,
)
from custom_components.solar_energy_management.features import (
    load_device_discovery as ldd,
)


class _Entry:
    def __init__(self, entity_id, device_id, domain=None, disabled_by=None):
        self.entity_id = entity_id
        self.device_id = device_id
        self.domain = domain or entity_id.split(".", 1)[0]
        self.disabled_by = disabled_by


class _Registry:
    def __init__(self, entries):
        self._by_id = {e.entity_id: e for e in entries}
        self._entries = entries

    def async_get(self, entity_id):
        return self._by_id.get(entity_id)


def _wire(monkeypatch, entries):
    reg = _Registry(entries)
    monkeypatch.setattr(ldd.entity_registry, "async_get", lambda hass: reg)
    monkeypatch.setattr(
        ldd.entity_registry, "async_entries_for_device",
        lambda registry, device_id, include_disabled_entities=False: [
            e for e in reg._entries
            if e.device_id == device_id
            and (include_disabled_entities or e.disabled_by is None)
        ],
    )
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    disc = LoadDeviceDiscovery.__new__(LoadDeviceDiscovery)
    disc.hass = hass
    disc._entity_registry = reg
    return disc


@pytest.mark.unit
class TestLightFixtureFilter:

    def test_a_matter_dimmer_is_a_light_fixture(self, monkeypatch):
        """Azlinon's exact shape: light entity + energy sensor + a pile of
        disabled Matter junk, no switch."""
        disc = _wire(monkeypatch, [
            _Entry("sensor.office_floods_energy", "dev1"),
            _Entry("light.office_floods", "dev1"),
            _Entry("button.office_floods_identify", "dev1", disabled_by="integration"),
            _Entry("update.office_floods_firmware", "dev1", disabled_by="integration"),
        ])
        assert disc._is_light_fixture("sensor.office_floods_energy") is True

    def test_a_metering_plug_feeding_a_lamp_is_kept(self, monkeypatch):
        """The plug is a real control surface — SEM may manage it."""
        disc = _wire(monkeypatch, [
            _Entry("sensor.lamp_plug_energy", "dev2"),
            _Entry("switch.lamp_plug", "dev2"),
            _Entry("light.lamp", "dev2"),
        ])
        assert disc._is_light_fixture("sensor.lamp_plug_energy") is False

    def test_a_plain_power_only_load_is_kept(self, monkeypatch):
        """No light anywhere: today's monitoring-only row stays."""
        disc = _wire(monkeypatch, [
            _Entry("sensor.boiler_energy", "dev3"),
        ])
        assert disc._is_light_fixture("sensor.boiler_energy") is False

    def test_no_registry_entry_is_kept_not_guessed(self, monkeypatch):
        disc = _wire(monkeypatch, [])
        assert disc._is_light_fixture("sensor.orphan_energy") is False
