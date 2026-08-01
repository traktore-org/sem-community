"""Regression for stale legacy EV sensors without a registered charger device."""
from custom_components.solar_energy_management.coordinator.ev_availability import (
    operational_ev_connected,
    operational_night_target,
)


def test_legacy_connected_sensor_is_ignored_without_registered_device():
    assert operational_ev_connected({}, True) is False
    assert operational_night_target({}, 42.0) == 0.0


def test_registered_device_preserves_connected_state_and_night_target():
    devices = {"zaptec_garage": object()}
    assert operational_ev_connected(devices, True) is True
    assert operational_ev_connected(devices, False) is False
    assert operational_night_target(devices, 42.0) == 42.0
