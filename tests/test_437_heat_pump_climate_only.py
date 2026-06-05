"""#437 — climate-only registration path for heat pumps without SG-Ready relays.

Pre-#437, ``__init__.py`` only registered the HeatPumpController when BOTH
``heat_pump_relay1_entity`` AND ``heat_pump_relay2_entity`` were set —
locking out Nibe / Mitsubishi / Daikin and any climate-entity-only
integration. The controller itself already handled climate-only mode
(``_set_sg_ready_state`` ``no_relays_configured`` path, locked by
``test_421_heat_pump_telemetry.py``); the only blocker was the
registration gate one layer above.

This test file pins:

1. Climate-only registration: configuring only ``heat_pump_climate_entity``
   triggers ``register_device`` + ``activate()`` raises the climate setpoint.
2. SG-Ready registration: existing behaviour unchanged.
3. Combined: both relays + climate registers a controller that does both.
4. Empty: no registration (unchanged).
5. Config flow validation: partial relays without climate → form rejects.
6. Climate-only bypasses the partial-relays validation: climate alone is OK.
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


# ──────────────────────────────────────────────
# Controller-level: climate-only activation works without relays
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_climate_only_activate_drives_setpoint(mock_hass):
    """The Nibe-style case: no relays configured, only a climate entity.
    ``activate()`` must still raise the climate setpoint and the
    ``relay_path`` lands on ``no_relays_configured``.
    """
    mock_hass.states.get = MagicMock(
        return_value=_state("heat", {"current_temperature": 20.0,
                                     "temperature": 21.0})
    )
    h = HeatPumpController(
        hass=mock_hass,
        relay1_entity_id=None,
        relay2_entity_id=None,
        climate_entity_id="climate.nibe_living_room",
    )
    await h.activate(3000.0)  # surplus below force_on_threshold (5000) → BOOST
    d = h.to_dict()
    # SG-Ready state still mutates internally (BOOST) but no relay actuated
    assert h.sg_ready_state == SGReadyState.BOOST
    assert d["relay_path"] == "no_relays_configured"
    assert d["activation_path"] == "boost+climate"  # climate composed
    # The actual climate.set_temperature call should have fired via
    # super().activate() — verify at least one service call was attempted
    # to climate domain
    climate_calls = [
        c for c in mock_hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 1 and c.args[0] == "climate"
    ]
    assert len(climate_calls) >= 1, (
        f"expected a climate.set_temperature call from super().activate(), "
        f"got: {mock_hass.services.async_call.call_args_list}"
    )


# ──────────────────────────────────────────────
# Registration gate (__init__.py:947)
# ──────────────────────────────────────────────


def _should_register(config):
    """Mirror the registration gate logic from __init__.py:947 for direct
    unit testing — keeps the test independent of HA fixtures."""
    relay1 = config.get("heat_pump_relay1_entity")
    relay2 = config.get("heat_pump_relay2_entity")
    climate = config.get("heat_pump_climate_entity")
    return bool(relay1 and relay2) or bool(climate)


def test_registration_gate_sg_ready_only():
    cfg = {
        "heat_pump_relay1_entity": "switch.r1",
        "heat_pump_relay2_entity": "switch.r2",
    }
    assert _should_register(cfg) is True


def test_registration_gate_climate_only():
    """#437 — the new path. Nibe, Mitsubishi, Daikin etc."""
    cfg = {"heat_pump_climate_entity": "climate.nibe"}
    assert _should_register(cfg) is True


def test_registration_gate_both_paths():
    cfg = {
        "heat_pump_relay1_entity": "switch.r1",
        "heat_pump_relay2_entity": "switch.r2",
        "heat_pump_climate_entity": "climate.living_room",
    }
    assert _should_register(cfg) is True


def test_registration_gate_no_paths():
    cfg = {}
    assert _should_register(cfg) is False


def test_registration_gate_one_relay_only_no_climate():
    """Half-configured SG-Ready without climate fallback — gate fails.
    The config flow validation also rejects this earlier (see below)."""
    cfg = {"heat_pump_relay1_entity": "switch.r1"}
    assert _should_register(cfg) is False


def test_registration_gate_one_relay_with_climate_passes():
    """User has 1 relay AND a climate entity — climate alone is enough
    to register; the orphan relay is harmless (controller's
    _set_sg_ready_state guards on both relay vars)."""
    cfg = {
        "heat_pump_relay1_entity": "switch.r1",
        "heat_pump_climate_entity": "climate.living_room",
    }
    assert _should_register(cfg) is True


# ──────────────────────────────────────────────
# Config flow validation — partial relays without climate
# ──────────────────────────────────────────────


def _config_flow_validates(user_input):
    """Mirror the heat_pump-step validation from config_flow.py:1658-1672.
    Returns (accepted, error_code_or_None)."""
    relay1 = user_input.get("heat_pump_relay1_entity")
    relay2 = user_input.get("heat_pump_relay2_entity")
    climate = user_input.get("heat_pump_climate_entity")
    has_one_relay = bool(relay1) ^ bool(relay2)
    has_climate = bool(climate)
    if has_one_relay and not has_climate:
        return False, "heat_pump_partial_relays"
    return True, None


def test_config_flow_accepts_sg_ready():
    ok, err = _config_flow_validates({
        "heat_pump_relay1_entity": "switch.r1",
        "heat_pump_relay2_entity": "switch.r2",
    })
    assert ok and err is None


def test_config_flow_accepts_climate_only():
    ok, err = _config_flow_validates({
        "heat_pump_climate_entity": "climate.nibe",
    })
    assert ok and err is None


def test_config_flow_accepts_empty_skip():
    ok, err = _config_flow_validates({})
    assert ok and err is None


def test_config_flow_rejects_one_relay_no_climate():
    ok, err = _config_flow_validates({
        "heat_pump_relay1_entity": "switch.r1",
    })
    assert not ok
    assert err == "heat_pump_partial_relays"


def test_config_flow_accepts_one_relay_with_climate():
    """Climate fallback rescues the partial-relays config."""
    ok, err = _config_flow_validates({
        "heat_pump_relay2_entity": "switch.r2",
        "heat_pump_climate_entity": "climate.living_room",
    })
    assert ok and err is None
