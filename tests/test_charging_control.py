"""Tests for coordinator/charging_control.py."""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingStateMachine,
    ChargingContext,
)
from custom_components.solar_energy_management.const import ChargingState


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def hass():
    """Return a mocked Home Assistant instance."""
    h = MagicMock()
    h.states = MagicMock()
    h.states.is_state = MagicMock(return_value=True)  # night charging enabled by default
    return h


@pytest.fixture
def time_manager():
    """Return a mocked TimeManager."""
    tm = MagicMock()
    tm.is_night_mode.return_value = False  # Daytime by default
    return tm


@pytest.fixture
def config():
    """Return a default charging config."""
    return {
        "battery_priority_soc": 30,
        "current_delta": 1,
    }


@pytest.fixture
def sm(hass, config, time_manager):
    """Return a ChargingStateMachine."""
    return ChargingStateMachine(hass, config, time_manager)


def _ctx(**kwargs):
    """Create a ChargingContext with specified overrides."""
    defaults = dict(
        ev_connected=True,
        ev_charging=False,
        battery_soc=80.0,
        battery_too_low=False,
        battery_needs_priority=False,
        calculated_current=0.0,
        excess_solar=0.0,
        available_power=0.0,
        daily_target_reached=False,
        daily_ev_energy=0.0,
        remaining_ev_energy=10.0,
        charging_strategy="solar_only",
        night_target_kwh=10.0,
    )
    defaults.update(kwargs)
    return ChargingContext(**defaults)


# ──────────────────────────────────────────────
# Solar state machine tests
# ──────────────────────────────────────────────

def test_idle_to_solar_active(sm):
    """Test transition from idle to solar charging active when surplus available."""
    # First let battery priority pass
    sm._battery_initial_check_done = True
    sm._ev_session_allowed = True

    ctx = _ctx(
        ev_connected=True,
        calculated_current=10.0,
        battery_soc=80.0,
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_CHARGING_ACTIVE


def test_solar_active_to_pause_low_battery(sm):
    """Test transition to pause when battery is too low."""
    ctx = _ctx(
        ev_connected=True,
        battery_too_low=True,
        battery_soc=20.0,
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_PAUSE_LOW_BATTERY


def test_solar_idle_when_ev_disconnected(sm):
    """Test solar idle when EV is not connected."""
    ctx = _ctx(ev_connected=False)
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_IDLE


def test_solar_waiting_battery_priority(sm):
    """Test waiting for battery priority when SOC is below threshold."""
    ctx = _ctx(
        ev_connected=True,
        battery_soc=20.0,  # Below default priority of 30
        charging_strategy="solar_only",
        calculated_current=10.0,
    )
    # Battery initial check not done, SOC below priority
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_WAITING_BATTERY_PRIORITY


def test_solar_target_reached(sm):
    """Test solar target reached state."""
    sm._battery_initial_check_done = True
    sm._ev_session_allowed = True

    ctx = _ctx(
        ev_connected=True,
        daily_target_reached=True,
        calculated_current=0.0,
        charging_strategy="solar_only",
    )
    state = sm.update_state(ctx)
    # With no current and session allowed, should be SOLAR_CHARGING_ALLOWED
    assert state == ChargingState.SOLAR_CHARGING_ALLOWED


def test_min_pv_mode(sm):
    """Test Min+PV mode returns SOLAR_MIN_PV state."""
    ctx = _ctx(
        ev_connected=True,
        charging_strategy="min_pv",
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_MIN_PV


def test_battery_assist_mode(sm):
    """Test battery assist strategy returns SOLAR_SUPER_CHARGING."""
    ctx = _ctx(
        ev_connected=True,
        charging_strategy="battery_assist",
        calculated_current=10.0,
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_SUPER_CHARGING


def test_now_mode(sm):
    """Test 'now' strategy uses SOLAR_MIN_PV path."""
    ctx = _ctx(
        ev_connected=True,
        charging_strategy="now",
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.SOLAR_MIN_PV


# ──────────────────────────────────────────────
# Night state machine tests
# ──────────────────────────────────────────────

def test_night_charging_active(sm, time_manager):
    """Test night charging active when night mode and target not reached."""
    time_manager.is_night_mode.return_value = True

    ctx = _ctx(
        ev_connected=True,
        night_target_kwh=5.0,
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.NIGHT_CHARGING_ACTIVE


def test_night_target_reached(sm, time_manager):
    """Test night target reached state."""
    time_manager.is_night_mode.return_value = True

    ctx = _ctx(
        ev_connected=True,
        night_target_kwh=0.0,  # No more needed
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.NIGHT_TARGET_REACHED


def test_night_idle_ev_disconnected(sm, time_manager):
    """Test night idle when EV is not connected."""
    time_manager.is_night_mode.return_value = True

    ctx = _ctx(ev_connected=False)
    state = sm.update_state(ctx)
    assert state == ChargingState.NIGHT_IDLE


def test_night_disabled(sm, time_manager, hass):
    """Test night disabled when night charging switch is off."""
    time_manager.is_night_mode.return_value = True
    hass.states.is_state.return_value = False  # Night charging disabled

    ctx = _ctx(
        ev_connected=True,
        night_target_kwh=5.0,
    )
    state = sm.update_state(ctx)
    assert state == ChargingState.NIGHT_DISABLED


# ──────────────────────────────────────────────
# State transitions
# ──────────────────────────────────────────────

def test_state_change_logged(sm):
    """Test that state changes update current_state property."""
    sm._battery_initial_check_done = True
    sm._ev_session_allowed = True

    ctx_active = _ctx(ev_connected=True, calculated_current=10.0)
    sm.update_state(ctx_active)
    assert sm.current_state == ChargingState.SOLAR_CHARGING_ACTIVE

    ctx_idle = _ctx(ev_connected=False)
    sm.update_state(ctx_idle)
    assert sm.current_state == ChargingState.SOLAR_IDLE


def test_reset_session(sm):
    """Test session reset clears state tracking."""
    sm._battery_initial_check_done = True
    sm._ev_session_allowed = True
    sm._current_state = ChargingState.SOLAR_CHARGING_ACTIVE

    sm.reset_session()

    assert sm._battery_initial_check_done is False
    assert sm._ev_session_allowed is False
    assert sm._current_state == ChargingState.IDLE
