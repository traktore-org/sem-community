"""#912 (round 3) — the owner of an entity the entity registry never saw.

bekovan is STILL getting the frozen-sensor Repair on ``v2.1.0-beta.17``
(2026-09-12) for ``sensor.inverted_power_plugin_solar`` — the same Template
sensor as round 2, but declared in ``configuration.yaml`` rather than created
as a UI helper.

Round 2 asks the ENTITY REGISTRY which integration owns the entity, and the
registry is a register of entities that have a ``unique_id``. A YAML template
sensor without one is not in it at all, so the lookup returns ``None``, the
platform is unknown, the derived-source rule is never reached, and the reader
falls straight through to "a polled sensor whose entry has gone quiet" —
the false Repair, for the third beta running.

Home Assistant records the owning integration for EVERY entity an entity
platform adds, registered or not, in ``homeassistant.helpers.entity``'s
``entity_sources()`` (``{"domain": "template", "config_entry": ...}``). That
is the question the rule wants answered, and it answers it for the entities
the registry cannot see.

Pins: the registry's silence about an entity is not evidence about its
integration; a source-map answer of "template" gets the derived treatment; an
unregistered sibling of a live config entry can vouch; and an entity NO
platform owns is still fail-closed (missing information must not silence a
warning).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, Mock

import homeassistant.util.dt as dt_util
from homeassistant.helpers import entity as ha_entity
from homeassistant.helpers import entity_registry as er

from custom_components.solar_energy_management.coordinator import repair_issues
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

TMPL = "sensor.inverted_power_plugin_solar"      # bekovan's YAML template
PLUG = "sensor.shelly_plug_power"                # what it negates


def _state(value, age_s: float, unit: str = "W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "reported"}
    now = dt_util.utcnow()
    s.last_updated = now - timedelta(seconds=age_s)
    s.last_reported = now - timedelta(seconds=age_s)
    return s


class _RegEntry:
    def __init__(self, entity_id, config_entry_id, platform):
        self.entity_id = entity_id
        self.config_entry_id = config_entry_id
        self.platform = platform


class _Rig:
    """A reader wired to a state table, an entity registry that knows only
    SOME of those entities, and HA's ``entity_sources()`` map that knows them
    all."""

    def __init__(self, monkeypatch, states, reg_entries, sources,
                 sun="above_horizon"):
        hass = MagicMock()
        hass.states = MagicMock()
        self.states = states
        self.sun = sun
        hass.states.get = self._get
        hass.config_entries.async_get_entry = lambda cid: None
        self.r = SensorReader(hass, {})

        reg = Mock()
        reg.async_get = lambda eid: reg_entries.get(eid)
        monkeypatch.setattr(er, "async_get", lambda h: reg)

        by_cid: dict = {}
        for e in reg_entries.values():
            by_cid.setdefault(e.config_entry_id, []).append(e)
        self.scans = 0

        def entries(_reg, cid):
            self.scans += 1
            return by_cid.get(cid, [])
        monkeypatch.setattr(er, "async_entries_for_config_entry", entries)

        self.sources = sources
        monkeypatch.setattr(ha_entity, "entity_sources", lambda h: self.sources)

        self.raised, self.cleared = [], []
        monkeypatch.setattr(repair_issues, "raise_sensor_stale",
                            lambda h, eid, **kw: self.raised.append(eid))
        monkeypatch.setattr(repair_issues, "clear_sensor_stale",
                            lambda h, eid: self.cleared.append(eid))

    def _get(self, eid):
        if eid == "sun.sun":
            s = Mock(); s.state = self.sun; s.attributes = {}
            return s
        return self.states.get(eid)


def _yaml_template(monkeypatch, *, sun="above_horizon"):
    """bekovan's install: a YAML template sensor (flat 15 min, NOT in the
    entity registry) negating a Shelly plug that is itself flat."""
    states = {TMPL: _state(-500, 900), PLUG: _state(500, 900)}
    reg_entries = {PLUG: _RegEntry(PLUG, "shelly1", "shelly")}
    sources = {
        TMPL: {"domain": "template", "custom_component": False},
        PLUG: {"domain": "shelly", "custom_component": False,
               "config_entry": "shelly1"},
    }
    return _Rig(monkeypatch, states, reg_entries, sources, sun=sun)


class TestTheReportedYamlTemplate:
    def test_a_yaml_template_sensor_is_not_a_frozen_sensor(self, monkeypatch):
        """The reported case. No registry entry — but the source map names the
        owning integration as ``template``, a platform with no poll loop, so a
        flat value is a change signal, not a stall."""
        rig = _yaml_template(monkeypatch)
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_the_repair_left_by_an_earlier_beta_clears(self, monkeypatch):
        """bekovan already carries the Repair beta.17 raised: the first read
        that finds the entity honest must clear it, not just stop re-raising
        (#933's reconcile, reached through the source-map verdict)."""
        rig = _yaml_template(monkeypatch)
        rig.r._read_sensor(TMPL, "solar")
        assert rig.cleared == [TMPL]

    def test_the_value_is_returned_unchanged(self, monkeypatch):
        """Observe-only: the freshness verdict never alters the reading."""
        rig = _yaml_template(monkeypatch)
        assert rig.r._read_sensor(TMPL, "solar") == -500.0


class TestDetectionIsPreserved:
    def test_an_unregistered_polled_sensor_with_a_quiet_entry_still_warns(
            self, monkeypatch):
        """An integration entity with no unique_id (so no registry entry) but a
        config entry the source map names: the whole entry is quiet → a genuine
        stall, and the warning stands."""
        eid = "sensor.modbus_grid_power"
        states = {eid: _state(0, 900), "sensor.modbus_voltage": _state(230, 900)}
        sources = {
            eid: {"domain": "modbus", "custom_component": False,
                  "config_entry": "modbus1"},
            "sensor.modbus_voltage": {"domain": "modbus", "custom_component": False,
                                      "config_entry": "modbus1"},
        }
        rig = _Rig(monkeypatch, states, reg_entries={}, sources=sources)
        rig.r._read_sensor(eid, "grid")
        assert eid in rig.r._frozen_sensors
        assert rig.raised == [eid]

    def test_an_entity_no_platform_owns_still_warns(self, monkeypatch):
        """Neither the registry nor the source map knows it (a raw
        ``states.set`` entity): unknown ownership is missing information, and
        missing information must not silence a warning."""
        eid = "sensor.appdaemon_grid_power"
        rig = _Rig(monkeypatch, {eid: _state(0, 900)}, reg_entries={}, sources={})
        rig.r._read_sensor(eid, "grid")
        assert eid in rig.r._frozen_sensors
        assert rig.raised == [eid]

    def test_an_unregistered_entity_of_a_non_derived_platform_still_warns(
            self, monkeypatch):
        """The source map names a polled integration and gives no config entry
        to corroborate with (a YAML modbus sensor): nothing vouches, so the
        warning stands."""
        eid = "sensor.yaml_modbus_grid_power"
        sources = {eid: {"domain": "modbus", "custom_component": False}}
        rig = _Rig(monkeypatch, {eid: _state(0, 900)}, reg_entries={},
                   sources=sources)
        rig.r._read_sensor(eid, "grid")
        assert eid in rig.r._frozen_sensors
        assert rig.raised == [eid]


FILT = "sensor.filtered_grid_power"
METER = "sensor.modbus_grid_power"


def _yaml_filter(monkeypatch, *, source_age):
    """A legacy YAML ``filter`` sensor (no unique_id, no config entry)
    smoothing a modbus grid meter. A filter publishes its source in its own
    attributes (``entity_id``), which is the only way to trace a helper that
    has no config entry to read."""
    filt = _state(2500, 900)
    filt.attributes = {"unit_of_measurement": "W", "friendly_name": "filtered",
                       "entity_id": METER}
    states = {FILT: filt, METER: _state(2500, source_age)}
    sources = {
        FILT: {"domain": "filter", "custom_component": False},
        METER: {"domain": "modbus", "custom_component": False},
    }
    return _Rig(monkeypatch, states, reg_entries={}, sources=sources)


class TestTheFailOpenIsBounded:
    """A YAML helper is not handed the honest verdict for free: where it
    publishes its source, the source is what decides."""

    def test_a_yaml_filter_over_a_dead_meter_still_warns(self, monkeypatch):
        """The stall W3 exists for, behind a legacy YAML wrapper: the modbus
        meter has been silent for 15 min and the filter holds 2500 W into the
        energy balance. Traced through the filter's own ``entity_id``
        attribute — a blanket 'derived platforms are honest' rule would lose
        this."""
        rig = _yaml_filter(monkeypatch, source_age=900)
        rig.r._read_sensor(FILT, "grid")
        assert FILT in rig.r._frozen_sensors
        assert rig.raised == [FILT]

    def test_a_yaml_filter_over_a_live_meter_is_honest(self, monkeypatch):
        """The same wrapper with the meter reporting at 5 s: flat, honest,
        quiet."""
        rig = _yaml_filter(monkeypatch, source_age=5)
        rig.r._read_sensor(FILT, "grid")
        assert FILT not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_a_helper_that_publishes_no_source_is_honest(self, monkeypatch):
        """The residual, pinned deliberately: a Template publishes no source
        anywhere — not in a config entry, not in its attributes — and its
        ``last_reported`` is a change signal, not a poll. Nothing can be
        proved about it, and accusing it is what broke three betas. Contrast
        with the filter above: the trade-off is the absence of a source, not
        the platform being derived."""
        rig = _yaml_template(monkeypatch)          # the Shelly is dead too
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors
        assert rig.raised == []


class TestTheSiblingHalf:
    def test_an_unregistered_sibling_of_a_live_entry_vouches(self, monkeypatch):
        """The sibling rule enumerates an entry's entities from the registry,
        which again sees only the ones with a unique_id. A live sibling the
        registry does not list is still the integration reporting."""
        eid = "sensor.foxess_feed_in_r"
        states = {eid: _state(0, 900),
                  "sensor.foxess_grid_consumption_r": _state(1311, 5)}
        reg_entries = {eid: _RegEntry(eid, "foxess1", "foxess_modbus")}
        sources = {
            eid: {"domain": "foxess_modbus", "custom_component": True,
                  "config_entry": "foxess1"},
            "sensor.foxess_grid_consumption_r": {
                "domain": "foxess_modbus", "custom_component": True,
                "config_entry": "foxess1"},
        }
        rig = _Rig(monkeypatch, states, reg_entries, sources)
        rig.r._read_sensor(eid, "grid_export")
        assert eid not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_the_entry_is_still_scanned_once_per_cycle(self, monkeypatch):
        """Cost guard: consulting the source map must not re-scan per read."""
        states = {
            "sensor.foxess_feed_in_r": _state(0, 900),
            "sensor.foxess_battery_charge": _state(0, 900),
            "sensor.foxess_grid_consumption_r": _state(1311, 5),
        }
        reg_entries = {
            "sensor.foxess_feed_in_r": _RegEntry(
                "sensor.foxess_feed_in_r", "foxess1", "foxess_modbus"),
            "sensor.foxess_battery_charge": _RegEntry(
                "sensor.foxess_battery_charge", "foxess1", "foxess_modbus"),
        }
        sources = {"sensor.foxess_grid_consumption_r": {
            "domain": "foxess_modbus", "custom_component": True,
            "config_entry": "foxess1"}}
        rig = _Rig(monkeypatch, states, reg_entries, sources)
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        rig.r._read_sensor("sensor.foxess_battery_charge", "battery")
        assert rig.scans == 1


class TestNeverBreaksARead:
    def test_a_source_map_error_leaves_the_old_rule_standing(self, monkeypatch):
        """If ``entity_sources`` raises, the read still returns its value and
        the registry-only verdict stands (fail closed, never a crash)."""
        rig = _yaml_template(monkeypatch)
        monkeypatch.setattr(
            ha_entity, "entity_sources",
            lambda h: (_ for _ in ()).throw(RuntimeError("boom")))
        assert rig.r._read_sensor(TMPL, "solar") == -500.0
        assert TMPL in rig.r._frozen_sensors

    def test_a_non_dict_source_map_is_ignored(self, monkeypatch):
        """A core that answers with something unexpected (or a test double)
        must not be read as an answer."""
        rig = _yaml_template(monkeypatch)
        monkeypatch.setattr(ha_entity, "entity_sources", lambda h: MagicMock())
        assert rig.r._read_sensor(TMPL, "solar") == -500.0
        assert TMPL in rig.r._frozen_sensors


def test_ownership_is_asked_in_one_place():
    """Structural guard (bug class 87): the two liveness rules must not read
    ``platform`` / ``config_entry_id`` off an entity-registry entry themselves
    — that register cannot see an entity without a ``unique_id``, and its
    silence is not an answer. Both ask ``_entity_owner``, which knows the
    registry AND HA's source map, so a future rule cannot re-acquire the blind
    spot by copying the lookup."""
    import inspect
    import re

    from custom_components.solar_energy_management.coordinator import (
        sensor_reader as sr_mod,
    )

    for fn in (sr_mod.SensorReader._source_is_alive,
               sr_mod.SensorReader._integration_is_reporting):
        # the docstrings name _entity_owner too — assert on the CODE
        body = inspect.getsource(fn).split('"""')[-1]
        assert "self._entity_owner(" in body, fn.__name__
        assert "config_entry_id" not in body, fn.__name__
        assert ".platform" not in body, fn.__name__
        # any registry call left in these two may only fetch the HANDLE —
        # never look an entity up and read a verdict off the result
        for call in re.findall(r"\.async_get\(([^)]*)\)", body):
            assert call.strip() == "self.hass", (fn.__name__, call)

    owner = inspect.getsource(sr_mod.SensorReader._entity_owner)
    assert "_entity_source_info" in owner
