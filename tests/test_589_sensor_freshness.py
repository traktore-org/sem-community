"""#589 W3 — frozen (available-but-not-updating) fast-power-sensor detector.

A Huawei modbus stall / Growatt cloud freeze keeps the entity 'available' with a
stale value that silently poisons the energy balance + sign detection. This is
OBSERVE-ONLY: the reading is unchanged; we warn ONCE so the freeze is visible in
the log (the #461/#462 triage blind spot). Only fast power sensors are checked,
with a generous threshold, so a legitimately slow sensor never false-positives.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, Mock

import homeassistant.util.dt as dt_util

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _reader():
    hass = MagicMock()
    hass.states = MagicMock()
    return SensorReader(hass, {})


def _state(value, age_s: float, unit: str = "W", reported_age_s=None):
    """Mock a State.

    ``age_s`` is how long ago the *value* last changed (``last_updated``).
    ``reported_age_s`` is how long ago the entity last *reported* to the state
    machine (``last_reported``); defaults to ``age_s``. The freshness audit keys
    off ``last_reported`` — a sensor holding a constant value still reports every
    poll, so ``last_reported`` stays fresh while ``last_updated`` ages (#611).
    """
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "X"}
    now = dt_util.utcnow()
    s.last_updated = now - timedelta(seconds=age_s)
    s.last_reported = now - timedelta(
        seconds=age_s if reported_age_s is None else reported_age_s
    )
    return s


class TestSensorFreshnessW3:
    def test_frozen_fast_power_flagged_value_unchanged(self):
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=700)  # > 600s threshold
        val = r._read_sensor("sensor.solar", "solar")
        assert val == 4000.0, "observe-only: the reading must NOT change"
        assert "sensor.solar" in r._frozen_sensors

    def test_warn_once_no_double_flag(self):
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=800)
        r._read_sensor("sensor.solar", "solar")
        r._read_sensor("sensor.solar", "solar")
        assert r._frozen_sensors == {"sensor.solar"}  # still one entry, warned once

    def test_fresh_fast_power_not_flagged(self):
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=5)
        r._read_sensor("sensor.solar", "solar")
        assert "sensor.solar" not in r._frozen_sensors

    def test_slow_non_power_sensor_never_checked(self):
        r = _reader()
        # a very stale reading, but name is NOT a fast power sensor
        r.hass.states.get = lambda eid: _state(12.5, age_s=99999)
        r._read_sensor("sensor.energy", "daily_solar")
        assert r._frozen_sensors == set()

    def test_recovery_clears_frozen(self):
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=700)
        r._read_sensor("sensor.grid", "grid")
        assert "sensor.grid" in r._frozen_sensors
        r.hass.states.get = lambda eid: _state(4000, age_s=2)
        r._read_sensor("sensor.grid", "grid")
        assert "sensor.grid" not in r._frozen_sensors  # re-armed

    def test_constant_value_but_still_reporting_not_frozen(self):
        """#611 — a split discharge-power sensor sits at a constant 0 W while the
        battery charges: ``last_updated`` ages past the 10-min threshold, but the
        entity keeps *reporting* every poll, so it is NOT frozen."""
        r = _reader()
        # value unchanged for 20 min, but reported 3 s ago
        r.hass.states.get = lambda eid: _state(0, age_s=1200, reported_age_s=3)
        val = r._read_sensor("sensor.fronius_discharging_power", "battery")
        assert val == 0.0
        assert "sensor.fronius_discharging_power" not in r._frozen_sensors, (
            "a constant-value sensor that is still reporting must not be flagged frozen"
        )

    def test_truly_stalled_reporting_also_frozen(self):
        """#611 — a genuine upstream stall freezes ``last_reported`` too → frozen."""
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=1200, reported_age_s=1200)
        r._read_sensor("sensor.solar", "solar")
        assert "sensor.solar" in r._frozen_sensors

    def test_missing_last_reported_falls_back_to_last_updated(self):
        """Pre-2024.4 HA (no ``last_reported``) still uses ``last_updated``."""
        r = _reader()

        def _no_reported(eid):
            s = _state(4000, age_s=700)
            s.last_reported = None  # simulate older HA / absent field
            return s

        r.hass.states.get = _no_reported
        r._read_sensor("sensor.grid", "grid")
        assert "sensor.grid" in r._frozen_sensors

    def test_all_fast_power_names_covered(self):
        r = _reader()
        for name, eid in (("solar", "s"), ("grid", "g"), ("grid_import", "gi"),
                          ("grid_export", "ge"), ("battery", "b")):
            r.hass.states.get = lambda eid, _s=_state(1000, age_s=700): _s
            r._read_sensor(f"sensor.{eid}", name)
            assert f"sensor.{eid}" in r._frozen_sensors, f"{name} not checked"


class TestFrozenSensorRepair:
    """The freeze also surfaces as an HA Repair (not just a log), cleared on recovery."""

    def test_freeze_raises_repair(self):
        from unittest.mock import patch
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=700)
        with patch(
            "custom_components.solar_energy_management.coordinator.repair_issues.raise_sensor_stale"
        ) as raise_stale:
            r._read_sensor("sensor.solar", "solar")
        raise_stale.assert_called_once()
        assert raise_stale.call_args.args[1] == "sensor.solar"

    def test_recovery_clears_repair(self):
        from unittest.mock import patch
        r = _reader()
        r.hass.states.get = lambda eid: _state(4000, age_s=700)
        r._read_sensor("sensor.grid", "grid")   # freeze
        r.hass.states.get = lambda eid: _state(4000, age_s=2)  # recovered
        with patch(
            "custom_components.solar_energy_management.coordinator.repair_issues.clear_sensor_stale"
        ) as clear_stale:
            r._read_sensor("sensor.grid", "grid")
        clear_stale.assert_called_once()
