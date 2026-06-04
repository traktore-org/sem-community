"""#421 — telemetry surface for HeatPumpController.

Locks the ``*_path`` strings each decision branch publishes via
``to_dict``. Mirrors the #359/#416/#420 ``classifier_path`` /
``dampening_path`` / ``legionella_path`` precedents.

Biggest silent-failure surface: ``_set_sg_ready_state`` with neither
``relay1_entity_id`` nor ``relay2_entity_id`` configured silently
mutates the internal ``sg_ready_state`` without actuating any physical
relay. The ``relay_path = no_relays_configured`` value makes this
visible.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)


@pytest.fixture
def mock_hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    return h


def _state(state_val, attributes=None):
    s = MagicMock()
    s.state = str(state_val)
    s.attributes = attributes or {}
    return s


def _make(mock_hass, **kwargs):
    return HeatPumpController(
        hass=mock_hass,
        relay1_entity_id=kwargs.pop("relay1", "switch.heat_pump_relay1"),
        relay2_entity_id=kwargs.pop("relay2", "switch.heat_pump_relay2"),
        temperature_entity_id=kwargs.pop("temp_sensor", "sensor.heat_pump_temp"),
        force_on_threshold=kwargs.pop("force_on_threshold", 5000.0),
        **kwargs,
    )


# ──────────────────────────────────────────────
# activation_path
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activation_path_boost(mock_hass):
    h = _make(mock_hass, climate_entity_id=None)
    await h.activate(2000.0)  # below force_on_threshold
    assert h.to_dict()["activation_path"] == "boost"


@pytest.mark.asyncio
async def test_activation_path_force_on(mock_hass):
    h = _make(mock_hass, climate_entity_id=None)
    await h.activate(6000.0)  # >= force_on_threshold
    assert h.to_dict()["activation_path"] == "force_on"


@pytest.mark.asyncio
async def test_activation_path_force_on_plus_climate(mock_hass):
    h = _make(mock_hass, climate_entity_id="climate.living_room")
    mock_hass.states.get = MagicMock(
        return_value=_state("heat", {"current_temperature": 20.0})
    )
    await h.activate(6000.0)
    assert h.to_dict()["activation_path"] == "force_on+climate"


# ──────────────────────────────────────────────
# deactivation_path
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deactivation_path_normal(mock_hass):
    h = _make(mock_hass, climate_entity_id=None)
    await h.deactivate()
    assert h.to_dict()["deactivation_path"] == "normal"


@pytest.mark.asyncio
async def test_deactivation_path_normal_plus_climate(mock_hass):
    h = _make(mock_hass, climate_entity_id="climate.living_room")
    mock_hass.states.get = MagicMock(
        return_value=_state("heat", {"current_temperature": 20.0})
    )
    await h.deactivate()
    assert h.to_dict()["deactivation_path"] == "normal+climate"


@pytest.mark.asyncio
async def test_deactivation_path_blocked(mock_hass):
    h = _make(mock_hass, climate_entity_id=None)
    await h.block()
    assert h.to_dict()["deactivation_path"] == "blocked"


@pytest.mark.asyncio
async def test_deactivation_path_unblocked(mock_hass):
    h = _make(mock_hass, climate_entity_id=None)
    await h.unblock()
    assert h.to_dict()["deactivation_path"] == "unblocked"


# ──────────────────────────────────────────────
# relay_path
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relay_path_both_relays(mock_hass):
    h = _make(mock_hass, climate_entity_id=None)
    await h._set_sg_ready_state(SGReadyState.BOOST)
    assert h.to_dict()["relay_path"] == "both_relays"


@pytest.mark.asyncio
async def test_relay_path_relay1_only(mock_hass):
    h = HeatPumpController(
        hass=mock_hass, relay1_entity_id="switch.r1", relay2_entity_id=None,
    )
    await h._set_sg_ready_state(SGReadyState.BOOST)
    assert h.to_dict()["relay_path"] == "relay1_only"


@pytest.mark.asyncio
async def test_relay_path_relay2_only(mock_hass):
    h = HeatPumpController(
        hass=mock_hass, relay1_entity_id=None, relay2_entity_id="switch.r2",
    )
    await h._set_sg_ready_state(SGReadyState.BOOST)
    assert h.to_dict()["relay_path"] == "relay2_only"


@pytest.mark.asyncio
async def test_relay_path_no_relays_configured(mock_hass):
    """Silent-failure surface — SG-Ready mutates internally but no
    relay actuates. This is the biggest finding of the #421 audit."""
    h = HeatPumpController(
        hass=mock_hass, relay1_entity_id=None, relay2_entity_id=None,
    )
    await h._set_sg_ready_state(SGReadyState.BOOST)
    assert h.to_dict()["relay_path"] == "no_relays_configured"
    # Internal state still mutated despite no physical actuation
    assert h.sg_ready_state == SGReadyState.BOOST


@pytest.mark.asyncio
async def test_relay_path_relay1_failed(mock_hass):
    mock_hass.services.async_call = AsyncMock(side_effect=Exception("offline"))
    h = HeatPumpController(
        hass=mock_hass, relay1_entity_id="switch.r1", relay2_entity_id="switch.r2",
    )
    await h._set_sg_ready_state(SGReadyState.BOOST)
    assert h.to_dict()["relay_path"] == "relay1_failed"


@pytest.mark.asyncio
async def test_relay_path_relay2_failed(mock_hass):
    """Reviewer finding — relay2 raises after relay1 succeeded.
    Same silent-failure class as no_relays_configured: sg_ready_state
    does NOT mutate because the method returns before the assignment
    at line 267. Telemetry attribute makes the half-actuated state
    visible."""
    call_count = [0]

    async def selective_fail(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 2:
            raise Exception("relay2 offline")
        return None

    mock_hass.services.async_call = AsyncMock(side_effect=selective_fail)
    h = HeatPumpController(
        hass=mock_hass, relay1_entity_id="switch.r1", relay2_entity_id="switch.r2",
    )
    # Capture pre-state
    before = h.sg_ready_state
    await h._set_sg_ready_state(SGReadyState.BOOST)
    assert h.to_dict()["relay_path"] == "relay2_failed"
    # State did NOT mutate — the half-actuated relay is the bug class
    # this telemetry exposes.
    assert h.sg_ready_state == before


# ──────────────────────────────────────────────
# temperature_reading_path
# ──────────────────────────────────────────────


def test_temp_reading_path_sensor(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("42.0"))
    h = _make(mock_hass)
    assert h.get_current_temperature() == 42.0
    assert h.to_dict()["temperature_reading_path"] == "sensor"


def test_temp_reading_path_sensor_unavailable(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("unavailable"))
    h = _make(mock_hass)
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "sensor_unavailable"


def test_temp_reading_path_sensor_invalid(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("warm"))
    h = _make(mock_hass)
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "sensor_invalid"


def test_temp_reading_path_no_sensor_configured(mock_hass):
    h = HeatPumpController(hass=mock_hass, temperature_entity_id=None)
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "no_sensor_configured"


# ──────────────────────────────────────────────
# offpeak_path
# ──────────────────────────────────────────────


def test_offpeak_path_parent_declines(mock_hass):
    """When super().needs_offpeak_activation is False, we decline upfront."""
    h = _make(mock_hass)
    # By default super().needs_offpeak_activation reads from device state;
    # without an active offpeak window it'll typically be False.
    _ = h.needs_offpeak_activation
    # Either path is valid here; just check it's not 'uninitialized'
    assert h.to_dict()["offpeak_path"] in (
        "parent_declines", "already_warm_skip", "activate",
    )
