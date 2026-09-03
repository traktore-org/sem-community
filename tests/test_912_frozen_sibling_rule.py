"""#912 — a flat value from a LIVE integration is honest, not frozen.

jrx-code's FoxESS (``foxess_modbus``) never stops polling; it simply does not
write an unchanged value, so ``last_reported`` stops advancing for any entity
whose value is flat — at any hour, in any domain. One simultaneous sample:

    sensor.foxess_modbus_grid_consumption_r   1.311   15 s      (live)
    sensor.foxess_modbus_feed_in_r            0       3 h 30 m  (export, importing)
    sensor.foxess_modbus_battery_charge       0       3 h 34 m  (battery idle)

#851's predicate (solar + ~0 + sun down) covers none of these. The rule is
now the reporter's: a sensor is frozen only if its OWN integration has gone
quiet — if any sibling entity of the same config entry reported within the
threshold, the integration is alive and the flat reading is honest. A real
modbus/cloud stall silences every entity of the entry, so nothing
corroborates and the warning stands. #851 is kept for the integration that
genuinely powers down at dusk (Growatt cloud): the whole entry is quiet
there, and the sun predicate is what explains it.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, Mock

import homeassistant.util.dt as dt_util
from homeassistant.helpers import entity_registry as er

from custom_components.solar_energy_management.coordinator import (
    repair_issues,
    sensor_reader as sr_mod,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

ENTRY = "foxess-entry-1"


def _state(value, age_s: float, unit: str = "W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "FoxESS"}
    now = dt_util.utcnow()
    s.last_updated = now - timedelta(seconds=age_s)
    s.last_reported = now - timedelta(seconds=age_s)
    return s


class _Rig:
    """A reader wired to a state table + a fake entity registry."""

    def __init__(self, monkeypatch, states: dict, registry: dict, sun="above_horizon"):
        hass = MagicMock()
        hass.states = MagicMock()
        self.r = SensorReader(hass, {})
        self.states = states
        self.registry = registry          # entity_id -> config_entry_id
        self.sun = sun
        self.scans = 0
        hass.states.get = self._get
        reg = Mock()
        reg.async_get = lambda eid: (
            Mock(config_entry_id=registry[eid]) if eid in registry else None
        )
        monkeypatch.setattr(er, "async_get", lambda h: reg)

        def entries(_reg, cid):
            self.scans += 1
            return [Mock(entity_id=e) for e, c in registry.items() if c == cid]
        monkeypatch.setattr(er, "async_entries_for_config_entry", entries)
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


def _foxess(monkeypatch, sibling_age_s=15.0, sun="above_horizon"):
    states = {
        "sensor.foxess_grid_consumption_r": _state(1311, sibling_age_s),
        "sensor.foxess_feed_in_r": _state(0, 3 * 3600 + 1800),
        "sensor.foxess_battery_charge": _state(0, 3 * 3600 + 2040),
        "sensor.foxess_pv1_power": _state(0, 46 * 60),
    }
    registry = {e: ENTRY for e in states}
    return _Rig(monkeypatch, states, registry, sun=sun)


class TestTheReportedTable:
    def test_export_flat_all_afternoon_with_a_live_sibling_is_not_frozen(self, monkeypatch):
        rig = _foxess(monkeypatch)
        val = rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert val == 0.0
        assert "sensor.foxess_feed_in_r" not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_battery_idle_for_hours_with_a_live_sibling_is_not_frozen(self, monkeypatch):
        rig = _foxess(monkeypatch)
        rig.r._read_sensor("sensor.foxess_battery_charge", "battery")
        assert "sensor.foxess_battery_charge" not in rig.r._frozen_sensors
        assert rig.raised == []

    def test_solar_flat_in_daylight_with_a_live_sibling_is_not_frozen(self, monkeypatch):
        """pv1 at 0.0 for 46 min at 17:21 UTC — an evening value the
        integration simply did not rewrite. #851 would not cover this
        (sun still up); the sibling rule does."""
        rig = _foxess(monkeypatch, sun="above_horizon")
        rig.r._read_sensor("sensor.foxess_pv1_power", "solar")
        assert "sensor.foxess_pv1_power" not in rig.r._frozen_sensors


class TestARealStallStillWarns:
    def test_the_whole_entry_quiet_is_frozen(self, monkeypatch):
        """The thing the check exists to catch: modbus died, every entity of
        the entry is silent, nothing corroborates."""
        rig = _foxess(monkeypatch, sibling_age_s=3 * 3600)
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert "sensor.foxess_feed_in_r" in rig.r._frozen_sensors
        assert rig.raised == ["sensor.foxess_feed_in_r"]

    def test_a_sibling_just_past_the_threshold_does_not_vouch(self, monkeypatch):
        rig = _foxess(monkeypatch, sibling_age_s=601.0)
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert "sensor.foxess_feed_in_r" in rig.r._frozen_sensors

    def test_no_registry_entry_keeps_the_old_behaviour(self, monkeypatch):
        """Missing information must not silence a warning."""
        states = {"sensor.orphan_grid": _state(0, 7200),
                  "sensor.other_live": _state(500, 10)}
        rig = _Rig(monkeypatch, states, registry={"sensor.other_live": "e2"})
        rig.r._read_sensor("sensor.orphan_grid", "grid")
        assert "sensor.orphan_grid" in rig.r._frozen_sensors

    def test_a_live_entity_of_another_entry_does_not_vouch(self, monkeypatch):
        states = {"sensor.fox_grid": _state(0, 7200),
                  "sensor.huawei_live": _state(500, 10)}
        rig = _Rig(monkeypatch, states,
                   registry={"sensor.fox_grid": "fox", "sensor.huawei_live": "huawei"})
        rig.r._read_sensor("sensor.fox_grid", "grid")
        assert "sensor.fox_grid" in rig.r._frozen_sensors


class TestItComposesWith851:
    def test_solar_asleep_at_night_with_the_whole_entry_quiet_stays_quiet(self, monkeypatch):
        """Growatt cloud powers down at dusk: no sibling vouches, and the
        sun predicate is what explains the silence — unchanged."""
        rig = _foxess(monkeypatch, sibling_age_s=3 * 3600, sun="below_horizon")
        rig.r._read_sensor("sensor.foxess_pv1_power", "solar")
        assert "sensor.foxess_pv1_power" not in rig.r._frozen_sensors

    def test_export_at_night_with_the_whole_entry_quiet_still_warns(self, monkeypatch):
        """#851 is solar-only; the sibling rule adds nothing when nobody
        reports — a non-solar sensor in a dead entry warns, as before."""
        rig = _foxess(monkeypatch, sibling_age_s=3 * 3600, sun="below_horizon")
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert "sensor.foxess_feed_in_r" in rig.r._frozen_sensors


class TestRecoveryAndCost:
    def test_a_repair_raised_during_a_stall_clears_when_the_entry_reports_again(self, monkeypatch):
        rig = _foxess(monkeypatch, sibling_age_s=3 * 3600)
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert rig.raised == ["sensor.foxess_feed_in_r"]
        # modbus is back: the consumption sensor reports, the export value
        # is still flat (the house still imports) — that is not a freeze
        rig.states["sensor.foxess_grid_consumption_r"] = _state(1311, 5)
        rig.r._entry_alive_cache.clear()
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert "sensor.foxess_feed_in_r" not in rig.r._frozen_sensors
        assert rig.cleared == ["sensor.foxess_feed_in_r"]

    def test_the_registry_is_scanned_once_per_entry_per_cycle(self, monkeypatch):
        rig = _foxess(monkeypatch)
        rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        rig.r._read_sensor("sensor.foxess_battery_charge", "battery")
        rig.r._read_sensor("sensor.foxess_pv1_power", "solar")
        assert rig.scans == 1

    def test_a_registry_error_never_breaks_the_read(self, monkeypatch):
        rig = _foxess(monkeypatch)
        monkeypatch.setattr(er, "async_get", lambda h: (_ for _ in ()).throw(RuntimeError("boom")))
        val = rig.r._read_sensor("sensor.foxess_feed_in_r", "grid_export")
        assert val == 0.0
        # and with the registry unreachable the old rule stands: frozen
        assert "sensor.foxess_feed_in_r" in rig.r._frozen_sensors


def test_the_rule_is_one_place():
    """Guard: no new per-domain excuse joins #851's; the sibling rule is
    the general answer."""
    import inspect
    src = inspect.getsource(sr_mod.SensorReader._audit_sensor_freshness)
    assert "_integration_is_reporting" in src
    assert src.count("_stillness_is_expected") == 1
