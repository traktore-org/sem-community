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
        soc_limit_active=False,
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


# ──────────────────────────────────────────────
# Issue #215: SOC target / ev_limit_surplus tests
# ──────────────────────────────────────────────

class TestSOCTargetCharging:
    """Tests for the four user profiles described in issue #215."""

    def test_user_a_no_soc_unlimited_surplus(self, sm):
        """User A: no car SOC, surplus never stops (default)."""
        sm._battery_initial_check_done = True
        sm._ev_session_allowed = True

        ctx = _ctx(
            calculated_current=10.0,
            daily_target_reached=True,  # kWh target reached
            soc_limit_active=False,     # toggle off (default)
        )
        state = sm.update_state(ctx)
        assert state == ChargingState.SOLAR_CHARGING_ACTIVE

    def test_user_b_soc_limits_surplus(self, sm):
        """User B: has SOC, surplus stops when SOC target reached."""
        sm._battery_initial_check_done = True
        sm._ev_session_allowed = True

        ctx = _ctx(
            calculated_current=10.0,
            daily_target_reached=True,
            soc_limit_active=True,  # toggle on + target reached
        )
        state = sm.update_state(ctx)
        assert state == ChargingState.SOLAR_TARGET_REACHED

    def test_soc_limit_lower_priority_than_battery_too_low(self, sm):
        """Battery-too-low check takes priority over SOC limit."""
        ctx = _ctx(
            battery_too_low=True,
            soc_limit_active=True,
            daily_target_reached=True,
        )
        state = sm.update_state(ctx)
        assert state == ChargingState.SOLAR_PAUSE_LOW_BATTERY

    def test_user_d_no_soc_kwh_limits_surplus(self, sm):
        """User D: no car SOC, but wants surplus to stop at kWh target."""
        sm._battery_initial_check_done = True
        sm._ev_session_allowed = True

        ctx = _ctx(
            calculated_current=10.0,
            daily_target_reached=True,  # kWh target reached
            soc_limit_active=True,      # toggle on
        )
        state = sm.update_state(ctx)
        assert state == ChargingState.SOLAR_TARGET_REACHED

    def test_surplus_continues_when_target_not_reached(self, sm):
        """With toggle on but target not reached, surplus charging continues."""
        sm._battery_initial_check_done = True
        sm._ev_session_allowed = True

        ctx = _ctx(
            calculated_current=10.0,
            daily_target_reached=False,
            soc_limit_active=False,  # toggle on but target not reached → False
        )
        state = sm.update_state(ctx)
        assert state == ChargingState.SOLAR_CHARGING_ACTIVE

    def test_night_stops_at_remaining_zero(self, sm):
        """Night charging stops when remaining need is 0 (SOC or kWh based)."""
        ctx = _ctx(
            ev_connected=True,
            night_target_kwh=0.0,  # remaining = 0, target reached
        )
        sm.time_manager.is_night_mode.return_value = True
        state = sm.update_state(ctx)
        assert state == ChargingState.NIGHT_TARGET_REACHED

    def test_night_charges_when_remaining_positive(self, sm):
        """Night charging continues when remaining need > 0."""
        ctx = _ctx(
            ev_connected=True,
            night_target_kwh=5.0,
        )
        sm.time_manager.is_night_mode.return_value = True
        state = sm.update_state(ctx)
        assert state == ChargingState.NIGHT_CHARGING_ACTIVE

class TestCalculateRemainingNeed:
    """Tests for the unified _calculate_remaining_need() helper."""

    def _make_coordinator(self, config=None):
        """Create a minimal coordinator for remaining need tests."""
        from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = config or {
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
            "daily_ev_target": 10,
        }
        return coord

    def _make_energy(self, daily_ev=0.0):
        energy = MagicMock()
        energy.daily_ev = daily_ev
        return energy

    def test_soc_based_remaining(self):
        """With vehicle SOC and target_mode=soc, remaining is based on SOC gap × capacity."""
        coord = self._make_coordinator({"ev_target_soc": 80, "ev_battery_capacity_kwh": 40, "daily_ev_target": 10, "ev_target_mode": "soc"})
        energy = self._make_energy()
        # 75% current, 80% target, 40 kWh capacity → 5% × 40 = 2.0 kWh
        remaining = coord._calculate_remaining_need(energy, vehicle_soc=75.0)
        assert remaining == pytest.approx(2.0)

    def test_soc_target_reached(self):
        """When vehicle SOC >= target and target_mode=soc, remaining is 0."""
        coord = self._make_coordinator({"ev_target_soc": 80, "ev_battery_capacity_kwh": 40, "daily_ev_target": 10, "ev_target_mode": "soc"})
        energy = self._make_energy()
        remaining = coord._calculate_remaining_need(energy, vehicle_soc=82.0)
        assert remaining == 0.0

    def test_kwh_fallback_no_soc(self):
        """Without vehicle SOC, remaining is kWh target minus daily energy."""
        coord = self._make_coordinator()
        energy = self._make_energy(daily_ev=3.0)
        remaining = coord._calculate_remaining_need(energy, vehicle_soc=None)
        assert remaining == pytest.approx(7.0)

    def test_kwh_target_reached(self):
        """When daily energy >= target, remaining is 0."""
        coord = self._make_coordinator()
        energy = self._make_energy(daily_ev=12.0)
        remaining = coord._calculate_remaining_need(energy, vehicle_soc=None)
        assert remaining == 0.0

    def test_per_charger_config_override(self):
        """Per-charger config overrides global config."""
        coord = self._make_coordinator({"ev_target_soc": 80, "ev_battery_capacity_kwh": 40, "daily_ev_target": 10, "ev_target_mode": "soc"})
        energy = self._make_energy()
        charger_cfg = {"ev_target_soc": 90, "ev_battery_capacity_kwh": 60, "ev_target_mode": "soc"}
        # 75% current, 90% target, 60 kWh → 15% × 60 = 9.0 kWh
        remaining = coord._calculate_remaining_need(energy, vehicle_soc=75.0, charger_cfg=charger_cfg)
        assert remaining == pytest.approx(9.0)

    def test_never_negative(self):
        """Remaining need is always >= 0."""
        coord = self._make_coordinator()
        energy = self._make_energy(daily_ev=20.0)
        assert coord._calculate_remaining_need(energy, vehicle_soc=95.0) == 0.0
        assert coord._calculate_remaining_need(energy, vehicle_soc=None) == 0.0
