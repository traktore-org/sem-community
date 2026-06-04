"""#427 — telemetry surface for UtilitySignalMonitor.

Locks the ``update_path`` / ``block_path`` / ``signal_read_path``
strings published via ``UtilitySignalData.to_dict``. Mirrors the
established #359/#416/#420/etc precedents.

Biggest silent-failure surface: ``signal_read_path = no_entity_configured``.
When no entity is configured, SEM treats utility-signal as permanently
inactive — users with a configuration mistake never see any blocking
behavior. The telemetry attribute exposes the state.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.utility_signals import (
    UtilitySignalMonitor,
)


@pytest.fixture
def mock_hass():
    h = MagicMock()
    h.states = MagicMock()
    return h


def _state(state_val):
    s = MagicMock()
    s.state = str(state_val)
    return s


# ──────────────────────────────────────────────
# signal_read_path
# ──────────────────────────────────────────────


def test_signal_read_path_no_entity_configured(mock_hass):
    """Silent-failure surface — no entity configured, signal always inactive."""
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id=None)
    assert m.is_signal_active is False
    assert m.signal_data.to_dict()["utility_signal_read_path"] == "no_entity_configured"


def test_signal_read_path_entity_missing(mock_hass):
    mock_hass.states.get = MagicMock(return_value=None)
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    assert m.is_signal_active is False
    assert m.signal_data.to_dict()["utility_signal_read_path"] == "entity_missing"


def test_signal_read_path_active(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("on"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    assert m.is_signal_active is True
    assert m.signal_data.to_dict()["utility_signal_read_path"] == "active"


def test_signal_read_path_inactive(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("off"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    assert m.is_signal_active is False
    assert m.signal_data.to_dict()["utility_signal_read_path"] == "inactive"


# ──────────────────────────────────────────────
# update_path
# ──────────────────────────────────────────────


def test_update_path_signal_started(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("on"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    m.update()
    assert m.signal_data.to_dict()["utility_update_path"] == "signal_started"


def test_update_path_signal_continues_active(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("on"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    m.update()  # signal_started
    m.update()  # continues_active
    assert m.signal_data.to_dict()["utility_update_path"] == "signal_continues_active"


def test_update_path_signal_ended(mock_hass):
    seq = iter([_state("on"), _state("on"), _state("off")])
    mock_hass.states.get = MagicMock(side_effect=lambda eid: next(seq))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    m.update()  # started
    m.update()  # continues
    m.update()  # ended
    assert m.signal_data.to_dict()["utility_update_path"] == "signal_ended"


def test_update_path_signal_continues_inactive(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("off"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    m.update()
    m.update()
    assert m.signal_data.to_dict()["utility_update_path"] == "signal_continues_inactive"


# ──────────────────────────────────────────────
# block_path
# ──────────────────────────────────────────────


def test_block_path_signal_inactive_no_block(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("off"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    result = m.get_devices_to_block(["dev1", "dev2"], [])
    assert result == []
    assert m.signal_data.to_dict()["utility_block_path"] == "signal_inactive_no_block"


def test_block_path_all_blocked(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("on"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple", solar_loads_exempt=False)
    result = m.get_devices_to_block(["dev1", "dev2"], ["dev1"])
    assert result == ["dev1", "dev2"]
    assert m.signal_data.to_dict()["utility_block_path"] == "all_blocked"


def test_block_path_solar_exempt_partial(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("on"))
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple", solar_loads_exempt=True)
    result = m.get_devices_to_block(["ev_charger", "boiler", "heat_pump"], ["ev_charger"])
    # ev_charger is solar-powered → exempt, others blocked
    assert result == ["boiler", "heat_pump"]
    assert m.signal_data.to_dict()["utility_block_path"] == "solar_exempt_partial:1"
