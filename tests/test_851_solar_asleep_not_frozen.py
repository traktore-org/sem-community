"""#851 — a solar sensor that stops reporting at night is asleep, not frozen.

RienduPre's Growatt raises the W3 frozen-sensor warning + Repair every night
for three solar sensors. The detector keys off ``last_reported``, which
normally advances on every poll even when the value is unchanged (#611) — but
a cloud/inverter-side integration that POWERS DOWN at dusk stops reporting
altogether. The entity stays 'available' holding its last value, and the
stall is real; it is simply expected.

The fix is a predicate, not an exclusion list: the warning is suppressed only
when the sensor's own domain explains the stillness — a SOLAR sensor, reading
~0, while the sun is below the horizon. Everything the check exists to catch
still warns: solar frozen in daylight, solar frozen at a NON-zero value (that
is a stuck reading, not an inverter asleep), and any non-solar sensor.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, Mock

import homeassistant.util.dt as dt_util

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _reader(sun: str | None = "below_horizon"):
    hass = MagicMock()
    hass.states = MagicMock()
    return SensorReader(hass, {}), sun


def _state(value, age_s: float, unit: str = "W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "PV"}
    now = dt_util.utcnow()
    s.last_updated = now - timedelta(seconds=age_s)
    s.last_reported = now - timedelta(seconds=age_s)
    return s


def _wire(r, sun: str | None, sensor_state):
    """Route sun.sun to a sun state and everything else to ``sensor_state``."""
    def get(eid):
        if eid == "sun.sun":
            if sun is None:
                return None
            s = Mock()
            s.state = sun
            s.attributes = {}
            return s
        return sensor_state
    r.hass.states.get = get


class TestSolarAsleepAtNight:
    def test_solar_zero_at_night_is_not_frozen(self):
        """The reported case: Growatt PV at 0 W, not reporting, sun down."""
        r, sun = _reader("below_horizon")
        _wire(r, sun, _state(0, age_s=7200))
        val = r._read_sensor("sensor.pv_power", "solar")
        assert val == 0.0
        assert "sensor.pv_power" not in r._frozen_sensors, (
            "a solar sensor at 0 W with the sun down is asleep, not frozen"
        )

    def test_solar_zero_in_daylight_still_warns(self):
        """The fault the check exists to catch must survive the fix."""
        r, sun = _reader("above_horizon")
        _wire(r, sun, _state(0, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")
        assert "sensor.pv_power" in r._frozen_sensors

    def test_solar_stuck_nonzero_at_night_still_warns(self):
        """4 kW of 'solar' at midnight is a stuck reading, not an asleep inverter."""
        r, sun = _reader("below_horizon")
        _wire(r, sun, _state(4000, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")
        assert "sensor.pv_power" in r._frozen_sensors

    def test_grid_frozen_at_night_still_warns(self):
        """Only solar sleeps with the sun — the meter should keep reporting."""
        r, sun = _reader("below_horizon")
        _wire(r, sun, _state(0, age_s=7200))
        r._read_sensor("sensor.grid", "grid")
        assert "sensor.grid" in r._frozen_sensors

    def test_no_sun_entity_falls_back_to_warning(self):
        """Never suppress on missing information — unknown sun means warn."""
        r, sun = _reader(None)
        _wire(r, sun, _state(0, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")
        assert "sensor.pv_power" in r._frozen_sensors

    def test_recovery_still_clears_after_night_suppression(self):
        """A suppressed night must not leave state that blocks the next warning."""
        r, sun = _reader("below_horizon")
        _wire(r, sun, _state(0, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")          # night: silent
        _wire(r, "above_horizon", _state(0, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")          # dawn: still frozen
        assert "sensor.pv_power" in r._frozen_sensors


class TestTheAsleepThresholdItself:
    """Audit F5: with only 0 and 4000 W exercised, the 25 W threshold could
    drift an order of magnitude (or flip its comparison) unnoticed — and a
    genuinely stuck night-time sensor near the line would silently stop
    being flagged. These pin the boundary on both sides."""

    def test_standby_draw_at_the_threshold_is_asleep(self):
        r, sun = _reader("below_horizon")
        _wire(r, sun, _state(25, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")
        assert "sensor.pv_power" not in r._frozen_sensors, (
            "an inverter idling at its standby draw is asleep, not frozen"
        )

    def test_just_above_the_threshold_still_warns(self):
        r, sun = _reader("below_horizon")
        _wire(r, sun, _state(26, age_s=7200))
        r._read_sensor("sensor.pv_power", "solar")
        assert "sensor.pv_power" in r._frozen_sensors, (
            "26 W at midnight is a reading, not standby — a stuck value "
            "near the line must still be flagged"
        )

    def test_the_constant_is_what_the_docs_say(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        assert SensorReader._SOLAR_ASLEEP_W == 25.0
