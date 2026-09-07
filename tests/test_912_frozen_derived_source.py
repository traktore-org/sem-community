"""#912 (round 2) — a DERIVED sensor is honest when its SOURCE is alive.

bekovan (2026-09-06) still got the frozen-sensor Repair on beta.7 for
``sensor.inverted_power_plugin_solar`` — a Template helper that negates a
Shelly plug. The beta.7 sibling rule cannot clear it:

* a template writes only when its rendered value changes, so a flat value
  legitimately holds ``last_reported`` still (like foxess), AND
* a UI Template helper is the ONLY entity of its config entry, so there is no
  sibling to vouch for it — the sibling rule scans an entry of one and finds
  nothing, then fails closed and warns.

Its liveness is its SOURCE's liveness (the Shelly plug), which the sibling
rule never looked at. This pins the source-following completion of bug
class 63: a derived sensor is frozen only if the source it draws from has
gone quiet.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, Mock

import homeassistant.util.dt as dt_util
from homeassistant.helpers import entity_registry as er

from custom_components.solar_energy_management.coordinator import repair_issues
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

TMPL_STATE = "{{ states('sensor.shelly_plug_power') | float(0) * -1 }}"


def _state(value, age_s: float, unit: str = "W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "derived"}
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
    """A reader wired to a state table, an entity registry that carries
    ``platform`` + ``config_entry_id``, and helper config entries with
    options."""

    def __init__(self, monkeypatch, states, reg_entries, ce_options, sun="above_horizon"):
        hass = MagicMock()
        hass.states = MagicMock()
        self.states = states
        self.sun = sun
        hass.states.get = self._get
        self.r = SensorReader(hass, {})

        reg = Mock()
        reg.async_get = lambda eid: reg_entries.get(eid)
        monkeypatch.setattr(er, "async_get", lambda h: reg)

        # siblings grouped by config_entry_id (from the registry entries)
        by_cid: dict = {}
        for e in reg_entries.values():
            by_cid.setdefault(e.config_entry_id, []).append(e)
        self.scans = 0

        def entries(_reg, cid):
            self.scans += 1
            return by_cid.get(cid, [])
        monkeypatch.setattr(er, "async_entries_for_config_entry", entries)

        ce_by_cid = {cid: Mock(options=opts, data={}) for cid, opts in ce_options.items()}
        hass.config_entries.async_get_entry = lambda cid: ce_by_cid.get(cid)

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


TMPL = "sensor.inverted_power_plugin_solar"
SRC = "sensor.shelly_plug_power"


def _shelly_template(monkeypatch, *, source_age, temp_age, sun="above_horizon"):
    """A Template helper (flat 15 min) negating a Shelly plug. The Shelly plug
    itself is flat (``source_age``) but its temperature sibling reports at
    ``temp_age`` — the Shelly integration is alive iff that sibling is fresh."""
    states = {
        TMPL: _state(-500, 900),                       # flat 15 min → looks frozen
        SRC: _state(500, source_age),
        "sensor.shelly_plug_temperature": _state(42, temp_age),
    }
    reg_entries = {
        TMPL: _RegEntry(TMPL, "tmpl1", "template"),
        SRC: _RegEntry(SRC, "shelly1", "shelly"),
        "sensor.shelly_plug_temperature": _RegEntry(
            "sensor.shelly_plug_temperature", "shelly1", "shelly"),
    }
    ce_options = {"tmpl1": {"state": TMPL_STATE, "template_type": "sensor",
                            "name": "inverted power plugin solar"}}
    return _Rig(monkeypatch, states, reg_entries, ce_options, sun=sun)


class TestTheReportedTemplate:
    def test_template_is_honest_when_the_shelly_integration_is_alive(self, monkeypatch):
        """Plug flat, but the Shelly temperature sibling reports at 5 s — the
        source integration is alive, so the negated value is honest."""
        rig = _shelly_template(monkeypatch, source_age=900, temp_age=5)
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_template_is_honest_when_the_source_itself_reported_recently(self, monkeypatch):
        """The plug reported at 5 s directly (value happened to change) — honest
        without needing a sibling."""
        rig = _shelly_template(monkeypatch, source_age=5, temp_age=900)
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_a_dead_source_through_a_template_still_warns(self, monkeypatch):
        """The Shelly whole entry has gone quiet (plug AND temperature both
        stale): the source is genuinely dead, so the frozen warning stands even
        through the template — detection is preserved, not fail-open."""
        rig = _shelly_template(monkeypatch, source_age=900, temp_age=900)
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL in rig.r._frozen_sensors
        assert rig.raised == [TMPL]


class TestUntraceableHelpers:
    def test_a_yaml_template_with_no_config_entry_is_honest(self, monkeypatch):
        """A YAML template sensor is registered with platform ``template`` but
        no config entry to read: its flat value is a change signal, not a
        stall, so it is honest rather than a false positive."""
        states = {TMPL: _state(-500, 900)}
        reg_entries = {TMPL: _RegEntry(TMPL, None, "template")}
        rig = _Rig(monkeypatch, states, reg_entries, ce_options={})
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_object_syntax_template_resolves_its_source(self, monkeypatch):
        """A template written in object syntax (``states.sensor.x.state``) must
        still resolve to ``sensor.x`` — the plain regex would split it and miss
        the source, silently widening the honest fail-open."""
        states = {
            TMPL: _state(-500, 900),
            SRC: _state(500, 900),
            "sensor.shelly_plug_temperature": _state(42, 900),  # whole entry quiet
        }
        reg_entries = {
            TMPL: _RegEntry(TMPL, "tmpl1", "template"),
            SRC: _RegEntry(SRC, "shelly1", "shelly"),
            "sensor.shelly_plug_temperature": _RegEntry(
                "sensor.shelly_plug_temperature", "shelly1", "shelly"),
        }
        ce_options = {"tmpl1": {"state": "{{ states.sensor.shelly_plug_power.state | float * -1 }}"}}
        rig = _Rig(monkeypatch, states, reg_entries, ce_options)
        rig.r._read_sensor(TMPL, "solar")
        # source WAS resolved (object syntax) and its whole entry is quiet → a
        # genuine dead source, so the warning stands — proving resolution, not
        # a fall-through to the untraceable-honest branch.
        assert TMPL in rig.r._frozen_sensors

    def test_a_template_whose_source_is_not_a_real_entity_is_honest(self, monkeypatch):
        """The template references an entity that no longer exists: nothing to
        follow, so a flat derived value is treated as honest, not frozen."""
        states = {TMPL: _state(-500, 900)}
        reg_entries = {TMPL: _RegEntry(TMPL, "tmpl1", "template")}
        ce_options = {"tmpl1": {"state": "{{ states('sensor.gone') | float(0) }}"}}
        rig = _Rig(monkeypatch, states, reg_entries, ce_options)
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors


class TestNonTemplateHelpers:
    def test_a_utility_meter_follows_its_source_key(self, monkeypatch):
        """A non-template helper stores its source under a plain ``source`` key;
        the generic option scan finds it without special-casing utility_meter."""
        um = "sensor.grid_import_daily"
        states = {
            um: _state(3.2, 900),
            "sensor.hw_grid_power": _state(1500, 5),
        }
        reg_entries = {
            um: _RegEntry(um, "um1", "utility_meter"),
            "sensor.hw_grid_power": _RegEntry("sensor.hw_grid_power", "modbus1", "modbus"),
        }
        ce_options = {"um1": {"source": "sensor.hw_grid_power", "cycle": "daily"}}
        rig = _Rig(monkeypatch, states, reg_entries, ce_options)
        rig.r._read_sensor(um, "grid_import")
        assert um not in rig.r._frozen_sensors


class TestPolledSensorsUnchanged:
    def test_a_real_polled_sensor_with_no_live_sibling_still_warns(self, monkeypatch):
        """Regression guard: the derived exemption must not leak to a genuine
        hardware sensor. A modbus entity, flat, whole entry quiet → frozen."""
        eid = "sensor.modbus_grid_power"
        states = {eid: _state(0, 900)}
        reg_entries = {eid: _RegEntry(eid, "modbus1", "modbus")}
        rig = _Rig(monkeypatch, states, reg_entries, ce_options={})
        rig.r._read_sensor(eid, "grid")
        assert eid in rig.r._frozen_sensors
        assert rig.raised == [eid]


class TestRecovery:
    def test_a_repair_clears_when_the_source_reports_again(self, monkeypatch):
        rig = _shelly_template(monkeypatch, source_age=900, temp_age=900)
        rig.r._read_sensor(TMPL, "solar")
        assert rig.raised == [TMPL]
        # the Shelly integration is back: its temperature sibling reports again
        rig.states["sensor.shelly_plug_temperature"] = _state(42, 5)
        rig.r._entry_alive_cache.clear()
        rig.r._read_sensor(TMPL, "solar")
        assert TMPL not in rig.r._frozen_sensors
        assert rig.cleared == [TMPL]
