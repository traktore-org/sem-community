"""#553 — KEBA box-level RUNAWAY CAP via the session-energy register.

KEBA firmware auto-restarts a session at its stored setpoint when the car
retries (~every 10 min, #315) — even after ``keba.disable``. While SEM is
alive its policing (#552) kills each rogue start within a cycle; this guard
bounds the damage when SEM is NOT policing (down/restarting). 1 kWh is the
keba library MINIMUM (0 < energy < 1 is rejected — live-verified on a real
P30: 0.001 was a silent no-op).

The counterpart invariant: EVERY SEM start must release the guard —
``start_session()`` always writes the session-energy register (the real
target, or 0 = no limit). Without that, a real session would die at 1 Wh.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.consts.core import (
    KEBA_IDLE_GUARD_KWH,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    return hass


@pytest.fixture
def keba(mock_hass):
    return CurrentControlDevice(
        hass=mock_hass,
        device_id="ev_charger",
        name="EV Charger",
        priority=5,
        min_current=6.0,
        max_current=32.0,
        phases=3,
        voltage=230.0,
        current_entity_id=None,
        charger_service="keba.set_current",
        charger_service_entity_id=None,
    )


def _calls(mock_hass, service):
    return [
        c.args for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 2 and c.args[1] == service
    ]


@pytest.mark.asyncio
async def test_stop_session_arms_idle_guard(keba, mock_hass):
    await keba.stop_session()
    se = _calls(mock_hass, "set_energy")
    assert se, "stop_session must arm the set_energy idle-guard"
    # the guard value rides in the data dict (3rd positional arg)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": KEBA_IDLE_GUARD_KWH}]
    # and the disable still fired first
    assert _calls(mock_hass, "disable")


@pytest.mark.asyncio
async def test_start_session_releases_guard_without_target(keba, mock_hass):
    """No SEM target → start writes 0 (no limit), releasing the guard."""
    await keba.start_session(energy_target_kwh=0)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 0}]


@pytest.mark.asyncio
async def test_start_session_writes_real_target(keba, mock_hass):
    await keba.start_session(energy_target_kwh=7.5)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 7.5}]


@pytest.mark.asyncio
async def test_stop_then_start_cycle_releases_guard(keba, mock_hass):
    """The full loop: stop arms ~1 Wh, next start releases it — a real
    session can never inherit the guard."""
    await keba.stop_session()
    mock_hass.services.async_call.reset_mock()
    await keba.start_session(energy_target_kwh=0)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 0}]


@pytest.mark.asyncio
async def test_no_guard_when_set_energy_unsupported(keba, mock_hass):
    """Non-KEBA service sets (no set_energy) skip the guard cleanly."""
    mock_hass.services.has_service = MagicMock(
        side_effect=lambda d, s: s != "set_energy"
    )
    await keba.stop_session()
    assert not _calls(mock_hass, "set_energy")
    assert _calls(mock_hass, "disable")


# ─── #553 follow-up: verify-and-reassert (lost UDP release) ──────────
# PROD 2026-07-17: start_session's one-shot ``set_energy 0`` release was
# lost (KEBA is UDP) — the box kept its armed 1 kWh target and terminated
# every session within seconds (session_energy 9.1 ≥ target 1.0) while SEM
# wrote currents into sessions the box kept killing. The guard register
# must be RECONCILED on every charge command, not trusted from one write.


def _et_state(value):
    st = MagicMock()
    st.state = str(value)
    return st


@pytest.mark.asyncio
async def test_guard_release_reasserted_when_flag_armed(keba, mock_hass):
    keba._idle_guard_armed = True   # SEM believes armed (release lost)
    await keba.ensure_energy_guard_released()
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 0}]
    assert keba._idle_guard_armed is False


@pytest.mark.asyncio
async def test_guard_release_reasserted_when_box_sensor_says_armed(keba, mock_hass):
    """SEM's flag is clear (start_session ran) but the BOX still reports an
    armed target — the exact lost-datagram shape. The sensor is the truth."""
    keba._idle_guard_armed = False
    keba._energy_target_sensor_cache = "sensor.keba_p30_energy_target"
    mock_hass.states.get = MagicMock(return_value=_et_state(1.0))
    await keba.ensure_energy_guard_released()
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 0}]


@pytest.mark.asyncio
async def test_guard_release_noop_when_clear(keba, mock_hass):
    """Common case: flag clear + box target 0 → no service call at all."""
    keba._idle_guard_armed = False
    keba._energy_target_sensor_cache = "sensor.keba_p30_energy_target"
    mock_hass.states.get = MagicMock(return_value=_et_state(0.0))
    await keba.ensure_energy_guard_released()
    assert not _calls(mock_hass, "set_energy")


@pytest.mark.asyncio
async def test_adapter_charge_command_reconciles_guard(keba, mock_hass):
    """KebaAdapter.command_current must run the guard reconcile even on a
    session it believes is already open (_session_active True) — that was
    the burst-loop window: WRITEs only, no start, guard never re-released."""
    from custom_components.solar_energy_management.coordinator.charger_adapters import (
        adapter_for,
    )
    keba._session_active = True     # reconciler in WRITE-only mode
    keba._idle_guard_armed = True   # box still armed
    adapter = adapter_for(keba)
    await adapter.command_current(10)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert {"energy": 0} in data, "charge command must release a stale guard"


@pytest.mark.asyncio
async def test_guard_sensor_discovery_retries_after_early_failure(keba, mock_hass, monkeypatch):
    """PROD 2026-07-18: the first discovery ran before the entity registry
    was ready, and the None result was cached FOREVER — the sensor backstop
    (the only reload-durable guard detector) went permanently dark and the
    box sat armed at 1 kWh through a whole flap. Negative results must NOT
    cache; a later successful discovery must work."""
    calls = {"n": 0}
    def _fail_then_find(self):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # registry not ready at boot
        self._energy_target_sensor_cache = "sensor.keba_p30_energy_target"
        return "sensor.keba_p30_energy_target"
    monkeypatch.setattr(type(keba), "_energy_target_sensor_id", _fail_then_find)
    keba._idle_guard_armed = False
    mock_hass.states.get = MagicMock(return_value=_et_state(1.0))
    # first call: discovery fails → no release possible
    await keba.ensure_energy_guard_released()
    assert not _calls(mock_hass, "set_energy")
    # second call: discovery succeeds → armed target detected → release sent
    await keba.ensure_energy_guard_released()
    data = [c.args[2] for c in mock_hass.services.async_call.call_args_list
            if len(c.args) >= 3 and c.args[1] == "set_energy"]
    assert data == [{"energy": 0}]
