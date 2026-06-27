"""#508 — heat-pump / hot-water surplus wiring + relay-failure handling.

The dedicated controllers were registered straight onto the surplus
controller and skipped the dual-sync the EV / Energy-Dashboard devices
get. Two consequences pinned here:

1. They defaulted to ``PEAK_ONLY``, so ``SurplusController.update()``
   never proactively activated them — surplus boosting was inert.
   (The old tests masked this by using generic ``SwitchDevice`` objects
   with ``control_mode = SURPLUS`` set by hand.)
2. The heat pump credited ``rated_power`` to the surplus pool even when
   the SG-Ready relay write FAILED.

Also: heat-pump compressor anti-cycling (``min_on/off_seconds``), the
relay2-failure relay1 restore, and the legionella-timestamp storage
round-trip.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode, DeviceState,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController, SGReadyState,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)


def _hass():
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    return h


# ── C2: real controllers default to SURPLUS ──────────────────────────

def test_heat_pump_defaults_to_surplus_mode():
    hp = HeatPumpController(
        hass=_hass(), relay1_entity_id="switch.r1", relay2_entity_id="switch.r2",
    )
    assert hp.control_mode == DeviceControlMode.SURPLUS, (
        "heat pump must be SURPLUS or SurplusController never activates it"
    )


def test_hot_water_defaults_to_surplus_mode():
    hw = HotWaterController(hass=_hass(), entity_id="switch.boiler")
    assert hw.control_mode == DeviceControlMode.SURPLUS


# ── W1: compressor anti-cycling on the heat pump ─────────────────────

def test_heat_pump_has_anticycling_guards():
    hp = HeatPumpController(hass=_hass(), relay1_entity_id="switch.r1",
                            relay2_entity_id="switch.r2")
    assert hp.min_on_seconds >= 300
    assert hp.min_off_seconds >= 180
    # The base can_activate/can_deactivate consult these (SetpointDevice
    # does not override them).
    assert hasattr(hp, "can_activate") and hasattr(hp, "can_deactivate")


# ── C3: relay-write failure must NOT credit rated_power ──────────────

@pytest.mark.asyncio
async def test_relay_failure_returns_zero_and_marks_error():
    hass = _hass()
    # relay1 write raises.
    hass.services.async_call = AsyncMock(side_effect=RuntimeError("relay down"))
    hp = HeatPumpController(hass=hass, rated_power=2000,
                            relay1_entity_id="switch.r1", relay2_entity_id="switch.r2")
    consumed = await hp.activate(3000)
    assert consumed == 0.0, "relay failure must credit 0 W, not rated_power"
    assert hp._status.state == DeviceState.ERROR
    assert "relay_failed" in hp._last_activation_path


@pytest.mark.asyncio
async def test_relay_success_credits_rated_power():
    hass = _hass()  # async_call succeeds
    hp = HeatPumpController(hass=hass, rated_power=2000,
                            relay1_entity_id="switch.r1", relay2_entity_id="switch.r2")
    consumed = await hp.activate(3000)
    assert consumed == 2000.0
    assert hp._status.state == DeviceState.ACTIVE


# ── I3: relay2 failure restores relay1 to its prior value ────────────

@pytest.mark.asyncio
async def test_relay2_failure_restores_relay1():
    hass = _hass()
    calls = []

    async def _call(domain, service, data, blocking=False):
        calls.append((data.get("entity_id"), service))
        # Fail only on relay2 writes.
        if data.get("entity_id") == "switch.r2":
            raise RuntimeError("relay2 down")

    hass.services.async_call = AsyncMock(side_effect=_call)
    hp = HeatPumpController(hass=hass, relay1_entity_id="switch.r1",
                            relay2_entity_id="switch.r2")
    # Prior state NORMAL = (relay1 off, relay2 on). Move to BOOST = (on, off):
    # relay1 flips on, then relay2 fails → relay1 must be restored to off.
    hp._hp_status.sg_ready_state = SGReadyState.NORMAL
    ok = await hp._set_sg_ready_state(SGReadyState.BOOST)
    assert ok is False
    assert hp._last_relay_path == "relay2_failed"
    # Last relay1 write must be the restore (turn_off back to NORMAL's off).
    r1_calls = [c for c in calls if c[0] == "switch.r1"]
    assert r1_calls[-1] == ("switch.r1", "turn_off"), (
        f"relay1 should be restored to its prior (off) value; got {r1_calls}"
    )


# ── I2: legionella timestamp storage round-trip ──────────────────────

def test_storage_legionella_time_roundtrip():
    from custom_components.solar_energy_management.coordinator.storage import (
        SEMStorage,
    )
    s = SEMStorage.__new__(SEMStorage)
    s._energy_data = {}
    assert s.get_legionella_time() is None
    s.set_legionella_time("2026-06-13T10:00:00+00:00")
    assert s.get_legionella_time() == "2026-06-13T10:00:00+00:00"
    # None is a no-op (doesn't clobber a stored value).
    s.set_legionella_time(None)
    assert s.get_legionella_time() == "2026-06-13T10:00:00+00:00"
