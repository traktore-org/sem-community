"""#570 — SG-Ready mode / state sensors were frozen at NORMAL.

RienduPre (Nibe SG-Ready, Growatt) reported the heat-pump Mode sensor
always read "normal · 2" even though SEM was flipping the SG-Ready
relays (relay2 physically closed → BOOST) and ``activation_path`` read
``boost``.

Root cause: ``coordinator.py`` built ``HeatPumpSensorData`` but never
copied the registered ``HeatPumpController``'s live ``sg_ready_state`` /
``is_solar_boosted`` into it — the "will override below" the pipeline
comment promised was never implemented. So ``heat_pump_mode`` /
``heat_pump_sg_ready_state`` / ``heat_pump_solar_boost`` stayed at their
dataclass defaults (normal / 2 / False) forever.

This file pins the extraction helper
``SEMCoordinator._heat_pump_sensor_state`` that now feeds those fields.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)


@pytest.fixture
def mock_hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    return h


def _controller(mock_hass) -> HeatPumpController:
    return HeatPumpController(
        hass=mock_hass,
        relay1_entity_id="switch.sg_ready_a",
        relay2_entity_id="switch.sg_ready_b",
    )


# ── the helper reflects each SG-Ready state ─────────────────────────


def test_no_controller_returns_normal_defaults():
    """When no HeatPumpController is registered, the helper returns the
    same defaults HeatPumpSensorData carries — so the sensor reads
    NORMAL / 2 / not-boosted, unchanged from before #570."""
    assert SEMCoordinator._heat_pump_sensor_state(None) == ("normal", 2, False)


@pytest.mark.asyncio
async def test_boost_state_is_reflected(mock_hass):
    """RienduPre's exact scenario: surplus < force_on_threshold drives
    the controller to BOOST (relay2 closed). The sensor must now read
    boost / 3 / solar-boosted — NOT the frozen normal / 2 / False."""
    hp = _controller(mock_hass)
    await hp.activate(3000.0)  # below force_on_threshold (5000) → BOOST
    assert hp.sg_ready_state == SGReadyState.BOOST  # pre-condition

    mode, sg_value, solar_boost = SEMCoordinator._heat_pump_sensor_state(hp)
    assert mode == "boost"
    assert sg_value == 3
    assert solar_boost is True


@pytest.mark.asyncio
async def test_force_on_state_is_reflected(mock_hass):
    hp = _controller(mock_hass)
    await hp.activate(6000.0)  # >= force_on_threshold → FORCE_ON
    assert hp.sg_ready_state == SGReadyState.FORCE_ON

    mode, sg_value, solar_boost = SEMCoordinator._heat_pump_sensor_state(hp)
    assert mode == "force_on"
    assert sg_value == 4
    assert solar_boost is True


@pytest.mark.asyncio
async def test_blocked_state_is_reflected(mock_hass):
    """State 1 still renders, even though SEM never commands it (#664).

    ``block()`` was deleted with the ripple-control surface, so the state is
    set directly here. The sensor mapping is total over the enum on purpose:
    dropping the arm would leave the sensor blank if state 1 ever arrives.
    """
    hp = _controller(mock_hass)
    await hp._set_sg_ready_state(SGReadyState.BLOCKED)
    assert hp.sg_ready_state == SGReadyState.BLOCKED

    mode, sg_value, _ = SEMCoordinator._heat_pump_sensor_state(hp)
    assert mode == "blocked"
    assert sg_value == 1


@pytest.mark.asyncio
async def test_deactivate_returns_to_normal(mock_hass):
    hp = _controller(mock_hass)
    await hp.activate(3000.0)
    await hp.deactivate()
    assert hp.sg_ready_state == SGReadyState.NORMAL

    mode, sg_value, solar_boost = SEMCoordinator._heat_pump_sensor_state(hp)
    assert mode == "normal"
    assert sg_value == 2
    assert solar_boost is False


def test_mode_strings_have_translation_keys():
    """The card renders ``heat_pump_mode`` via ``_t(mode.toLowerCase())``.
    Every possible mode string the helper can emit must be an EN
    translation key so it never surfaces the raw token."""
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    en = json.loads(
        (repo / "dashboard" / "translations.json").read_text(encoding="utf-8")
    )["en"]
    for state in SGReadyState:
        assert state.name.lower() in en, f"missing translation for {state.name}"
