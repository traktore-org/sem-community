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

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features.load_device_discovery import (
    LoadDeviceDiscovery,
)
from custom_components.solar_energy_management.features import (
    load_device_discovery as ldd,
)
from custom_components.solar_energy_management.features import (
    device_registry as dr,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
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


# ── the path that actually runs ────────────────────────────────────────────
class _SurplusController:
    """Enough of SurplusController for _sync_to_surplus_controller."""

    def __init__(self, devices=None):
        self._devices = dict(devices or {})

    def register_device(self, device):
        self._devices[device.device_id] = device

    def unregister_device(self, did):
        self._devices.pop(did, None)

    def get_device(self, did):
        return self._devices.get(did)


class _FakeLoadManager:
    def __init__(self, devices=None):
        self._devices = dict(devices or {})
        self._save_device_configuration = AsyncMock()


LIGHT_ENTRIES = [
    _Entry("sensor.garage_carport_licht_energy", "dev_light"),
    _Entry("light.garage_carport_licht", "dev_light"),
    _Entry("sensor.boiler_energy", "dev_boiler"),
    _Entry("switch.boiler", "dev_boiler"),
]

ED_ROWS = [
    {"energy_sensor": "sensor.garage_carport_licht_energy", "power_sensor": None,
     "name": "Garage / Carport Licht", "is_ev": False},
    {"energy_sensor": "sensor.boiler_energy", "power_sensor": None,
     "name": "Boiler", "is_ev": False},
]


def _registry(monkeypatch, ed_rows, entries, lm_devices=None,
              surplus_devices=None):
    """A UnifiedDeviceRegistry whose ED read is controlled and whose light
    rule is the REAL one — everything else about the refresh (ratings,
    runtime snapshots, storage) is out of scope here."""
    disc = _wire(monkeypatch, entries)
    monkeypatch.setattr(dr, "read_energy_dashboard_config",
                        AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(dr, "get_all_individual_devices",
                        lambda cfg, hass: list(ed_rows))
    monkeypatch.setattr(dr, "_find_load_power_sensor", lambda hass, es: None)

    lm = _FakeLoadManager(lm_devices)
    reg = UnifiedDeviceRegistry(
        MagicMock(), _SurplusController(surplus_devices), lm, disc)
    reg._has_battery = False
    reg.hass.states.get = MagicMock(return_value=None)
    reg.set_ev_chargers([])
    # Control discovery finds the light's own on/off entity — which is exactly
    # why a light row reached the surplus roster (and the planner's card) in
    # the first place. Anything else in these fixtures is uncontrollable.
    reg._discovery.discover_control_for_energy_device = MagicMock(
        side_effect=lambda es, ps=None: (
            {"type": "switch", "entity": "light.garage_carport_licht",
             "discovery_method": "same_device"}
            if es == "sensor.garage_carport_licht_energy" else None
        ))
    reg._adopt_legacy_device_flags = AsyncMock()
    reg._capture_calibrated_ratings = MagicMock(return_value=False)
    reg._capture_accrued_runtimes = MagicMock(return_value={})
    reg._restore_accrued_runtimes = MagicMock()
    reg._seed_and_apply_ratings = AsyncMock(return_value=False)
    reg._save_storage = AsyncMock()
    return reg, lm


@pytest.mark.unit
class TestTheAuthoritativePathAppliesTheRule:
    """The rule above was added to ``LoadDeviceDiscovery`` — a path that no
    live install reaches.

    ``LoadManagement._discover_devices`` (its only caller) early-returns the
    moment ``_unified_registry_active`` is set, and ``__init__.py`` sets that
    on every setup right after ``UnifiedDeviceRegistry.async_initialize()``.
    The registry re-derives the roster straight from
    ``get_all_individual_devices`` on every refresh — startup, the 35 s
    re-discovery, every drag — and never learned the rule. So the filter ran
    once, on the legacy pass, and the registry put the lights straight back:
    Guido's PROD roster still carried ``Garage / Carport Licht`` and
    ``Girlande`` on beta.1, which read as "the filter is import-time only"
    and is really "the filter is on the dead path".

    The fix belongs at the one authoritative boundary. Because that boundary
    re-derives, an already-imported light retires itself on the next refresh —
    no sweep, no deletion pass, nothing to get wrong.
    """

    async def test_the_registry_does_not_import_a_light_fixture(self, monkeypatch):
        reg, _ = _registry(monkeypatch, ED_ROWS, LIGHT_ENTRIES)
        await reg.async_refresh_devices()
        assert [d.name for d in reg.devices] == ["Boiler"]

    async def test_an_already_imported_light_retires_from_the_surplus_roster(
            self, monkeypatch):
        """The roster the #638 planner packs (``get_devices_sorted``) and the
        daytime surplus loop drives. This is the whole "retirement": the sync
        unregisters every ``energy_dashboard_*`` device and re-adds only what
        the registry still knows."""
        reg, _ = _registry(
            monkeypatch, ED_ROWS, LIGHT_ENTRIES,
            surplus_devices={"energy_dashboard_garage_carport_licht": MagicMock()},
        )
        await reg.async_refresh_devices()
        assert "energy_dashboard_garage_carport_licht" \
            not in reg._surplus_controller._devices

    async def test_an_already_imported_light_row_leaves_load_management(
            self, monkeypatch):
        """LoadManagement keeps its OWN store and reloads it at init, and the
        sync's prune deliberately SPARES every ``energy_dashboard_*`` key — so
        a row the registry no longer knows was immortal there (the #748
        lesson, same shape). It must go, and the removal must be persisted."""
        reg, lm = _registry(
            monkeypatch, ED_ROWS, LIGHT_ENTRIES,
            lm_devices={
                "energy_dashboard_garage_carport_licht": {"friendly_name": "Licht"},
                "energy_dashboard_boiler": {"friendly_name": "Boiler"},
            },
        )
        await reg.async_refresh_devices()
        assert "energy_dashboard_garage_carport_licht" not in lm._devices
        assert "energy_dashboard_boiler" in lm._devices
        lm._save_device_configuration.assert_awaited()

    async def test_a_metering_plug_row_survives_the_authoritative_path(
            self, monkeypatch):
        """The keep case, on the path that runs: the plug is a real control
        surface, so its row stays whatever it feeds."""
        entries = [
            _Entry("sensor.lamp_plug_energy", "dev_plug"),
            _Entry("switch.lamp_plug", "dev_plug"),
            _Entry("light.lamp", "dev_plug"),
        ]
        rows = [{"energy_sensor": "sensor.lamp_plug_energy", "power_sensor": None,
                 "name": "Lamp Plug", "is_ev": False}]
        reg, _ = _registry(monkeypatch, rows, entries)
        await reg.async_refresh_devices()
        assert [d.name for d in reg.devices] == ["Lamp Plug"]

    async def test_a_service_registered_row_is_never_pruned(self, monkeypatch):
        """The documented escape hatch: a relay exposed as ``light.*`` that the
        user registered explicitly is a decision, not a discovery guess. The
        prune must not reach it even though the registry doesn't list it."""
        reg, lm = _registry(
            monkeypatch, ED_ROWS, LIGHT_ENTRIES,
            lm_devices={"energy_dashboard_stage_relay": {"friendly_name": "Relay"}},
        )
        reg._service_registrations = {
            "energy_dashboard_stage_relay": {"entity_id": "light.stage_relay"}}
        await reg.async_refresh_devices()
        assert "energy_dashboard_stage_relay" in lm._devices
