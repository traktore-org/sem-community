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


def test_mark_reconciled_off_stamps_both_deactivation_clocks():
    """The device-level min_off anti-flicker reads _status.last_deactivated;
    the reconcile-off path must stamp it too, not just the base clock."""
    dev = _switch("off")
    dev._status.state = DeviceState.ACTIVE
    dev.mark_reconciled_off()
    assert dev._status.last_deactivated is not None
    assert dev._last_deactivated is not None
    assert not dev.is_active


@pytest.mark.asyncio
async def test_climate_observed_on_matches_configured_mode():
    from custom_components.solar_energy_management.devices.base import ClimateDevice
    states = {"climate.ac": SimpleNamespace(state="cool", attributes={})}
    dev = ClimateDevice(hass=_hass(states), device_id="ac", name="AC",
                        rated_power=1500.0, entity_id="climate.ac", hvac_mode="cool")
    assert dev.observed_on() is True                     # in SEM's mode
    states["climate.ac"] = SimpleNamespace(state="heat", attributes={})
    assert dev.observed_on() is False                    # user switched mode
    states["climate.ac"] = SimpleNamespace(state="off", attributes={})
    assert dev.observed_on() is False
    states["climate.ac"] = SimpleNamespace(state="unavailable", attributes={})
    assert dev.observed_on() is None


# ── Phase 4: runtime credit on OBSERVED draw ──

def test_runtime_not_credited_when_entity_reads_off():
    """Belief ACTIVE but entity OFF (drift not yet corrected) → no runtime
    credit. Before Phase 4 the goal engine credited belief."""
    from datetime import date, timedelta as td
    dev = _switch("off")
    dev._status.state = DeviceState.ACTIVE
    dev.daily_min_runtime_sec = 3600
    dev._daily_runtime_last_check = datetime.now() - td(seconds=30)
    dev._daily_runtime_meter_day = date.today()
    dev.update_daily_runtime(date.today())
    assert dev._daily_runtime_accumulated_sec == 0.0


def test_runtime_credited_when_entity_reads_on():
    from datetime import date, timedelta as td
    dev = _switch("on")
    dev._status.state = DeviceState.ACTIVE
    dev.daily_min_runtime_sec = 3600
    dev._daily_runtime_last_check = datetime.now() - td(seconds=30)
    dev._daily_runtime_meter_day = date.today()
    dev.update_daily_runtime(date.today())
    assert 29 <= dev._daily_runtime_accumulated_sec <= 31


def test_runtime_credited_when_unobservable():
    """No readable entity (None) → behave exactly as before (belief)."""
    from datetime import date, timedelta as td
    dev = _switch("unavailable")
    dev._status.state = DeviceState.ACTIVE
    dev.daily_min_runtime_sec = 3600
    dev._daily_runtime_last_check = datetime.now() - td(seconds=30)
    dev._daily_runtime_meter_day = date.today()
    dev.update_daily_runtime(date.today())
    assert 29 <= dev._daily_runtime_accumulated_sec <= 31


# ── Phase 4: median-of-3 surplus pre-filter ──

@pytest.mark.asyncio
async def test_median_filter_rejects_single_cycle_spike():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    sc = SurplusController(_hass())
    # steady 0 W, then one 8 kW spike, then 0 W again
    await sc.update(0.0)
    await sc.update(0.0)
    ema_before = sc._smoothed_surplus
    await sc.update(8000.0)          # single-cycle spike
    # median of [0, 0, 8000] = 0 → the spike never reaches the EMA
    assert sc._smoothed_surplus == ema_before
    await sc.update(0.0)
    assert sc._smoothed_surplus == ema_before


@pytest.mark.asyncio
async def test_median_filter_passes_real_trend():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    sc = SurplusController(_hass())
    await sc.update(0.0)
    await sc.update(0.0)
    await sc.update(3000.0)
    await sc.update(3000.0)          # 2nd consistent sample → median passes it
    assert sc._smoothed_surplus > 800   # EMA moving toward 3000


# ── Phase 3: desired-state + ownership observability ──

def test_desired_state_model():
    from custom_components.solar_energy_management.devices.base import (
        DeviceControlMode,
    )
    dev = _switch("on")
    assert dev.desired_state == "idle"           # idle, not owned
    dev._status.state = DeviceState.ACTIVE
    dev.record_activated()
    assert dev.desired_state == "on"             # SEM drives it
    dev.control_mode = DeviceControlMode.OFF
    assert dev.desired_state == "off"            # SEM hands off entirely


def test_to_dict_exposes_arc_fields():
    dev = _switch("on")
    dev._status.state = DeviceState.ACTIVE
    dev.record_activated()
    d = dev.to_dict()
    assert d["desired_state"] == "on"
    assert d["observed_on"] is True
    assert d["sem_owned"] is True


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
