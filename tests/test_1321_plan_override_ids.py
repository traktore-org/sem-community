"""#1321 — plan_override names a charger, a battery or a load, nothing else.

An unknown id was stored and did nothing, and the dashboard showed the
button press as done. Loads act since #1321 (tests/test_1321_load_override.py).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.devices.base import DeviceControlMode


def _coord():
    return SimpleNamespace(
        config={"ev_chargers": [{"id": "keba"}]},
        _known_battery_ids={"b1", "b2"},
        _battery_ids_read=True,
        _plan_overrides={},
        _storage=MagicMock(),
        _surplus_controller=SimpleNamespace(_devices={
            "boiler": SimpleNamespace(control_mode=DeviceControlMode.SURPLUS)}),
    )


@pytest.mark.parametrize("device_id", ["keba", "b2", "primary", "boiler"])
def test_a_charger_or_a_battery_is_taken(device_id):
    c = _coord()
    SEMCoordinator.set_plan_override(c, device_id, "skip", 60)
    assert device_id in c._plan_overrides


@pytest.mark.parametrize("device_id", ["load:boiler", "heater", "ev:keba", ""])
def test_any_other_id_is_refused_and_nothing_is_stored(device_id):
    c = _coord()
    with pytest.raises(ValueError, match="not a charger, a battery or a load"):
        SEMCoordinator.set_plan_override(c, device_id, "force", 60)
    assert c._plan_overrides == {}
    c._storage.set_plan_overrides.assert_not_called()


def test_a_charger_without_an_id_and_a_flat_key_charger_are_taken():
    c = _coord()
    c.config = {"ev_chargers": [{"name": "box"}]}
    SEMCoordinator.set_plan_override(c, "ev_charger_0", "skip", 60)
    c = _coord()
    c.config = {}
    SEMCoordinator.set_plan_override(c, "ev_charger", "force", 60)
    assert "ev_charger" in c._plan_overrides


def test_before_the_first_cycle_a_battery_id_is_taken():
    c = _coord()
    c._known_battery_ids = set()
    c._battery_ids_read = False
    SEMCoordinator.set_plan_override(c, "b3", "force", 60)
    assert "b3" in c._plan_overrides


def test_after_the_first_cycle_a_no_battery_install_refuses_an_unknown_id():
    c = _coord()
    c._known_battery_ids = set()
    c._battery_ids_read = True
    with pytest.raises(ValueError, match="not a charger, a battery or a load"):
        SEMCoordinator.set_plan_override(c, "nonsense", "force", 60)
    assert c._plan_overrides == {}


@pytest.mark.asyncio
async def test_the_service_turns_a_refusal_into_a_validation_error(
        mock_hass, mock_coordinator):
    from homeassistant.exceptions import ServiceValidationError
    from custom_components.solar_energy_management import _async_register_services
    handlers = {}
    mock_hass.services.has_service = MagicMock(return_value=False)
    mock_hass.services.async_register = MagicMock(
        side_effect=lambda d, n, h, **k: handlers.__setitem__(n, h))
    mock_coordinator.set_plan_override = MagicMock(
        side_effect=ValueError("not a charger, a battery or a load: 'x'"))
    await _async_register_services(mock_hass, mock_coordinator)
    call = SimpleNamespace(data={"device_id": "x", "action": "skip", "minutes": 30})
    with pytest.raises(ServiceValidationError, match="not a charger"):
        await handlers["plan_override"](call)
