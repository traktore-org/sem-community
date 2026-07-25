"""#427 — telemetry surface for UtilitySignalMonitor.

Locks the ``update_path`` / ``signal_read_path`` strings published via
``UtilitySignalData.to_dict``. Mirrors the established #359/#416/#420/etc
precedents. (``block_path`` was the third key here until #654 deleted it —
see the comment block further down for why.)

Biggest silent-failure surface: ``signal_read_path = no_entity_configured``.
When no entity is configured, SEM treats utility-signal as permanently
inactive — a user with a configuration mistake sees no sign of it.

Standing caveat, and the reason #654 happened: ``to_dict()`` itself has no
consumer. The coordinator reads ``signal_active`` / ``signal_source`` /
``signal_count_today`` off the object by attribute; nothing calls
``to_dict()``, so none of these strings currently reach a sensor, the
diagnostics dump, or a card. They are pinned here so the wiring in #664
inherits a known-good contract — not because a user can see them today.
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
# block_path — REMOVED in #654
#
# Three tests pinned ``block_path`` to signal_inactive_no_block /
# all_blocked / solar_exempt_partial:N. Every one of them reached the
# field by calling ``get_devices_to_block`` directly, and nothing in
# production ever did. So in a shipped install the field could only ever
# hold "uninitialized" — these tests were pinning values the sensor was
# structurally incapable of publishing.
#
# That is the shape of the #427 audit's own blind spot, worth stating
# plainly: telemetry added to observe a code path cannot tell you the path
# is dead, because the test that exercises it IS the caller. The guard that
# catches this is the orphan-method lint (tests/test_653_orphan_methods.py),
# not more telemetry.
#
# #664 re-adds the field with the wiring that makes it reachable.
# ──────────────────────────────────────────────


def test_block_path_is_gone(mock_hass):
    m = UtilitySignalMonitor(hass=mock_hass, signal_entity_id="binary_sensor.ripple")
    assert "utility_block_path" not in m.signal_data.to_dict()
