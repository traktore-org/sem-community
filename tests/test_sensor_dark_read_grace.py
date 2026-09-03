"""A 30-second modbus blink is not a state change — the SEM sensor holds.

Guido, 03.09: *"The card is not good, whatever we changed in the past it made
it very unreliable, it was very stable before."* Measured on PROD the same
afternoon (14:00–18:00): ``sensor.sem_solar_power`` / ``sem_grid_power`` /
``sem_battery_power`` / ``sem_battery_soc`` were ``unavailable`` 52–55 times
each — 13–15 % of the time, one blink every ~4.5 minutes, longest 238 s. Since
#818/#875 an unread source publishes ``None`` and the entity goes unavailable
on the spot, so every Huawei dropout blanks the Home diagram, the chips and
every history graph. Before, the last value was held silently — stable to
look at, and the source of the "0 %" and stale-reading bugs.

The middle: the entity keeps its LAST GOOD value for a bounded grace while
the source is dark, says so (``stale_s``), and only a sustained outage blanks
it. The coordinator's own honesty is untouched — ``inputs_degraded`` and the
``*_unavailable`` flags still drive every decision; this is the surface.
"""
from __future__ import annotations

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor


def _sensor(mock_coordinator, key="solar_power", device_class=SensorDeviceClass.POWER):
    mock_coordinator.data = {"last_update": "x"}
    mock_coordinator.last_update_success = True
    desc = SensorEntityDescription(key=key, name="x", device_class=device_class)
    return SEMSolarSensor(coordinator=mock_coordinator, description=desc, entry_id="e")


def _feed(s, value, t):
    s.coordinator.data = {**s.coordinator.data, s.entity_description.key: value}
    s._now_monotonic = lambda: t
    s._update_from_coordinator()


@pytest.mark.unit
class TestADarkReadHoldsTheLastGoodValue:

    def test_grace_is_longer_than_a_prod_blink(self):
        # p99 of PROD's dropouts is 114 s (36 h census, 24.08); 238 s was the
        # longest seen on 03.09. The grace must swallow the ordinary blink
        # and still give up on a real outage.
        assert 120 <= SENSOR_DARK_READ_GRACE_S <= 300

    def test_a_blink_keeps_the_value_and_says_stale(self, mock_coordinator):
        s = _sensor(mock_coordinator)
        _feed(s, 4200.0, 1000.0)
        assert s.native_value == 4200.0 and s._attr_available is True
        _feed(s, None, 1030.0)          # 30 s dark
        assert s._attr_available is True
        assert s.native_value == 4200.0
        assert s.extra_state_attributes.get("stale_s") == 30

    def test_a_sustained_outage_blanks_after_the_grace(self, mock_coordinator):
        s = _sensor(mock_coordinator)
        _feed(s, 4200.0, 1000.0)
        _feed(s, None, 1000.0 + SENSOR_DARK_READ_GRACE_S - 1)
        assert s._attr_available is True
        _feed(s, None, 1000.0 + SENSOR_DARK_READ_GRACE_S + 1)
        assert s._attr_available is False
        assert s.native_value is None

    def test_a_fresh_read_clears_the_hold(self, mock_coordinator):
        s = _sensor(mock_coordinator)
        _feed(s, 4200.0, 1000.0)
        _feed(s, None, 1040.0)
        _feed(s, 3100.0, 1050.0)
        assert s.native_value == 3100.0 and s._attr_available is True
        assert "stale_s" not in s.extra_state_attributes
        # a new blink counts from the LAST good read, not the first
        _feed(s, None, 1050.0 + SENSOR_DARK_READ_GRACE_S - 5)
        assert s._attr_available is True and s.native_value == 3100.0

    def test_never_read_is_unknown_not_held(self, mock_coordinator):
        # (#875) nothing to hold: the entity stays unavailable, never 0.
        s = _sensor(mock_coordinator, key="battery_soc", device_class=SensorDeviceClass.BATTERY)
        _feed(s, None, 1000.0)
        assert s._attr_available is False and s.native_value is None

    def test_soc_holds_like_power(self, mock_coordinator):
        s = _sensor(mock_coordinator, key="battery_soc", device_class=SensorDeviceClass.BATTERY)
        _feed(s, 89.0, 1000.0)
        _feed(s, None, 1045.0)
        assert s.native_value == 89.0 and s.extra_state_attributes.get("stale_s") == 45

    def test_strings_and_timestamps_are_not_held(self, mock_coordinator):
        s = _sensor(mock_coordinator, key="charging_strategy", device_class=None)
        _feed(s, "solar_only: idle", 1000.0)
        _feed(s, None, 1010.0)
        assert s._attr_available is False
