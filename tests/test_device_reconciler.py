"""Tests for the generic-device reconciler (arc) — belief-vs-observed sync."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    DeviceState, SwitchDevice,
)
from custom_components.solar_energy_management.coordinator.device_reconciler import (
    reconcile_device, reconcile_all, OFF_GRACE_S, EXTERNAL_OFF_COOLDOWN_S,
)


def _hass(states=None):
    h = MagicMock()
    st = states or {}
    h.states.get = lambda e: st.get(e)
    h.services.async_call = AsyncMock()
    return h


def _switch(state, power_state=None):
    states = {"switch.x": SimpleNamespace(state=state, attributes={})}
    if power_state is not None:
        states["sensor.x_power"] = SimpleNamespace(state=power_state, attributes={})
    dev = SwitchDevice(
        hass=_hass(states), device_id="d1", name="Pump", rated_power=1000.0,
        entity_id="switch.x", power_entity_id="sensor.x_power",
    )
    return dev


# ── observed_on() ──

def test_observed_on_reads_state():
    assert _switch("on").observed_on() is True
    assert _switch("off").observed_on() is False
    assert _switch("unavailable").observed_on() is None
    assert _switch("unknown").observed_on() is None


def test_observed_on_no_entity_is_none():
    dev = SwitchDevice(hass=_hass(), device_id="d", name="d", rated_power=1, entity_id=None)
    assert dev.observed_on() is None


# ── ownership on activate/deactivate ──

def test_record_activated_sets_owned():
    dev = _switch("on")
    assert dev._sem_owned is False
    dev.record_activated()
    assert dev._sem_owned is True
    dev.record_deactivated()
    assert dev._sem_owned is False


# ── reconcile: converged / unobservable ──

def test_unobservable_leaves_belief():
    dev = _switch("unavailable")
    dev._status.state = DeviceState.ACTIVE
    r = reconcile_device(dev)
    assert r.action == "unobservable"
    assert dev.is_active  # untouched


def test_converged_active_on():
    dev = _switch("on")
    dev._status.state = DeviceState.ACTIVE
    dev.record_activated()
    r = reconcile_device(dev)
    assert r.action == "none"
    assert dev.is_active


# ── reconcile: belief ON, entity OFF → grace then correct ──

def test_off_grace_holds_then_corrects():
    dev = _switch("off")
    dev._status.state = DeviceState.ACTIVE
    dev.record_activated()
    t0 = 1000.0
    # first sighting → grace started, belief unchanged
    r = reconcile_device(dev, now_mono=t0)
    assert r.action == "none" and dev.is_active
    # within grace → still holds
    r = reconcile_device(dev, now_mono=t0 + OFF_GRACE_S - 1)
    assert r.action == "none" and dev.is_active
    # past grace → corrected
    now_wall = datetime(2026, 7, 7, 12, 0, 0)
    r = reconcile_device(dev, now_mono=t0 + OFF_GRACE_S + 1, now_wall=now_wall)
    assert r.action == "corrected_off"
    assert not dev.is_active
    assert dev._sem_owned is False
    assert dev._external_off_until == now_wall + timedelta(seconds=EXTERNAL_OFF_COOLDOWN_S)


def test_transient_off_then_back_on_does_not_correct():
    dev = _switch("off")
    dev._status.state = DeviceState.ACTIVE
    dev.record_activated()
    reconcile_device(dev, now_mono=1000.0)          # grace started
    # entity comes back on before grace elapses
    dev.hass.states.get = lambda e: SimpleNamespace(state="on", attributes={})
    r = reconcile_device(dev, now_mono=1000.0 + 5)
    assert r.action == "none"
    assert dev.is_active
    assert dev._observed_off_since is None           # anchor cleared


# ── reconcile: belief IDLE, entity ON → external ──

def test_external_on_not_owned_not_fought():
    dev = _switch("on")
    dev._status.state = DeviceState.IDLE
    r = reconcile_device(dev)
    assert r.action == "external_on"
    assert dev._sem_owned is False
    assert not dev.is_active   # control untouched — SEM does not adopt/fight


# ── respect-user-off cooldown gates can_activate ──

def test_external_off_cooldown_blocks_activation():
    dev = _switch("off")
    dev._external_off_until = datetime.now() + timedelta(seconds=60)
    assert dev.can_activate() is False
    dev._external_off_until = datetime.now() - timedelta(seconds=1)  # elapsed
    assert dev.can_activate() is True


# ── reconcile_all tolerates a bad device ──

def test_reconcile_all_isolates_errors():
    good = _switch("on")
    good._status.state = DeviceState.ACTIVE
    bad = SimpleNamespace(device_id="bad")  # no observed_on → raises inside
    results = reconcile_all([good, bad])
    # good device produced a result; bad one was skipped, not fatal
    assert any(r.device_id == "d1" for r in results)


# ── integration: SurplusController.update() runs the reconcile pass ──

@pytest.mark.asyncio
async def test_update_runs_reconcile_pass():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    dev = _switch("off")               # entity reads OFF
    dev._status.state = DeviceState.ACTIVE  # but SEM believes it's ON
    sc = SurplusController(dev.hass)
    sc.register_device(dev)
    await sc.update(2000.0)
    # the reconcile pass at the top of update() saw belief-on / entity-off and
    # started the drift-grace anchor
    assert dev._observed_off_since is not None
