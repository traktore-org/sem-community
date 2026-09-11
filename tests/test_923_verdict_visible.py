"""#923 — "where is my battery tab?" is answered on the install itself: the
verdict rides on sensor.sem_diag_ed_config and in the diagnostics download."""
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor


def _diag_sensor(presence):
    coord = MagicMock()
    coord.data = {"last_update": "x"}
    coord.last_update_success = True
    coord.get_ed_config_detail.return_value = {}
    coord.setup_presence = presence
    return SEMSolarSensor(
        coordinator=coord,
        description=SensorEntityDescription(key="diag_ed_config", name="x"),
        entry_id="e",
    )


def test_the_diagnostic_sensor_carries_the_verdict():
    s = _diag_sensor({m: Presence.ABSENT for m in Module} | {Module.EV: Presence.PRESENT})
    assert s.extra_state_attributes["install_modules"] == {
        "battery": "absent", "ev": "present", "heat_pump": "absent", "hot_water": "absent"}


def test_no_verdict_no_attribute():
    s = _diag_sensor(None)
    assert "install_modules" not in s.extra_state_attributes
