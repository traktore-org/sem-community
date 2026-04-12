"""Tests for Solar Energy Management dual state machine implementation."""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from custom_components.solar_energy_management.coordinator import (
    ChargingStateMachine,
    ChargingContext,
)
from custom_components.solar_energy_management.const import ChargingState, DEFAULT_DAILY_EV_TARGET
from custom_components.solar_energy_management.utils import TimeManager


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"
    hass.states = Mock()
    hass.states.is_state = Mock(return_value=False)
    hass.states.get = Mock(return_value=None)
    return hass


@pytest.fixture
def config():
    """Create a test configuration."""
    return {
        "daily_ev_target": 7.0,
        "battery_priority_soc": 90,
        "battery_minimum_soc": 30,
        "minimum_solar_power": 2400,
        "maximum_grid_import": 300,
        "current_delta": 1,
    }


@pytest.fixture
def time_manager(mock_hass):
    """Create a TimeManager instance."""
    return TimeManager(mock_hass)


@pytest.fixture
def state_machine(mock_hass, config, time_manager):
    """Create a ChargingStateMachine for testing."""
    return ChargingStateMachine(mock_hass, config, time_manager)


@pytest.fixture
def charging_controller(mock_hass, config, time_manager):
    """Create a ChargingStateMachine for testing (legacy name kept for test compat)."""
    return ChargingStateMachine(mock_hass, config, time_manager)


@pytest.fixture
def mock_time_night(time_manager):
    """Mock time to be in night mode (22:00)."""
    with patch.object(time_manager, 'is_night_mode', return_value=True), \
         patch.object(time_manager, 'get_sunrise_time', return_value="06:30"), \
         patch.object(time_manager, 'get_sunset_plus_10_time', return_value="19:55"):
        yield


@pytest.fixture
def mock_time_day(time_manager):
    """Mock time to be in day mode (12:00)."""
    with patch.object(time_manager, 'is_night_mode', return_value=False), \
         patch.object(time_manager, 'get_sunrise_time', return_value="06:30"), \
         patch.object(time_manager, 'get_sunset_plus_10_time', return_value="19:55"):
        yield


class TestDualStateMachine:
    """Test the dual state machine implementation."""

    def test_time_based_routing_night_mode(self, time_manager, mock_time_night):
        """Test that night time correctly routes to night mode."""
        assert time_manager.is_night_mode() is True

    def test_time_based_routing_day_mode(self, time_manager, mock_time_day):
        """Test that day time correctly routes to day mode."""
        assert time_manager.is_night_mode() is False

    def test_summer_late_sunset_handling(self, time_manager):
        """Test that summer late sunsets are handled correctly."""
        # Summer scenario: sunset at 21:20 + 10min = 21:30 start
        with patch('homeassistant.util.dt.now') as mock_now, \
             patch.object(time_manager, 'get_sunrise_time', return_value="05:30"), \
             patch.object(time_manager, 'get_sunset_plus_10_time', return_value="21:30"):

            # 21:00 - should still be day mode (before 21:30)
            mock_now.return_value = datetime(2025, 7, 15, 21, 0, 0)
            assert time_manager.is_night_mode() is False

            # 21:35 - should be night mode
            mock_now.return_value = datetime(2025, 7, 15, 21, 35, 0)
            assert time_manager.is_night_mode() is True

    def test_winter_early_sunset_handling(self, time_manager):
        """Test that winter early sunsets use minimum 20:30 start."""
        # Winter scenario: sunset at 16:45 + 10min = 16:55, but minimum is 20:30
        with patch('homeassistant.util.dt.now') as mock_now, \
             patch.object(time_manager, 'get_sunrise_time', return_value="08:00"), \
             patch.object(time_manager, 'get_sunset_plus_10_time', return_value="16:55"):

            # 17:00 - should still be day mode (before 20:30 minimum)
            mock_now.return_value = datetime(2025, 12, 15, 17, 0, 0)
            assert time_manager.is_night_mode() is False

            # 20:35 - should be night mode
            mock_now.return_value = datetime(2025, 12, 15, 20, 35, 0)
            assert time_manager.is_night_mode() is True

    def test_night_charging_active_state(self, state_machine, mock_hass, mock_time_night):
        """Test night charging active state logic."""
        ctx = ChargingContext(
            ev_connected=True,
            daily_ev_energy=4.0,
            daily_ev_energy_offset=4.0,
            night_target_kwh=6.0,
        )

        # Mock night switch ON
        mock_hass.states.is_state = Mock(return_value=True)

        state = state_machine._night_state_machine(ctx)
        assert state == ChargingState.NIGHT_CHARGING_ACTIVE

    def test_night_charging_target_reached(self, state_machine, mock_hass, mock_time_night):
        """Test night charging when target is already reached."""
        ctx = ChargingContext(
            ev_connected=True,
            daily_ev_energy=7.2,  # Target exceeded
            daily_ev_energy_offset=7.2,
        )

        # Mock night switch ON
        mock_hass.states.is_state = Mock(return_value=True)

        state = state_machine._night_state_machine(ctx)
        assert state == ChargingState.NIGHT_TARGET_REACHED

    def test_night_charging_disabled(self, state_machine, mock_hass, mock_time_night):
        """Test night charging when switch is off."""
        ctx = ChargingContext(
            ev_connected=True,
            daily_ev_energy=4.0,
        )

        # Mock night switch OFF
        mock_hass.states.is_state = Mock(return_value=False)

        state = state_machine._night_state_machine(ctx)
        assert state == ChargingState.NIGHT_DISABLED

    def test_night_charging_no_ev(self, state_machine, mock_time_night):
        """Test night charging when EV is not connected."""
        ctx = ChargingContext(
            ev_connected=False,
            daily_ev_energy=4.0,
        )

        state = state_machine._night_state_machine(ctx)
        assert state == ChargingState.NIGHT_IDLE

    def test_solar_charging_battery_priority(self, state_machine, mock_time_day):
        """Test solar charging blocked by battery priority."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=75,  # Below 90% priority
            battery_too_low=False,
            daily_target_reached=False,
            charging_strategy="solar_only",
            calculated_current=10,
        )

        state = state_machine._solar_state_machine(ctx)
        assert state == ChargingState.SOLAR_WAITING_BATTERY_PRIORITY

    def test_solar_charging_active(self, state_machine, mock_time_day):
        """Test solar charging in active state."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=95,  # Above 90% priority
            battery_too_low=False,
            battery_needs_priority=False,
            daily_target_reached=False,
            charging_strategy="solar_only",
            calculated_current=12,
        )

        # Set session as allowed
        state_machine._battery_initial_check_done = True
        state_machine._ev_session_allowed = True

        state = state_machine._solar_state_machine(ctx)
        assert state == ChargingState.SOLAR_CHARGING_ACTIVE

    def test_solar_charging_super_mode(self, state_machine, mock_time_day):
        """Test solar charging in super charger mode."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=95,
            battery_too_low=False,
            battery_needs_priority=False,
            daily_target_reached=False,
            charging_strategy="battery_assist",
            calculated_current=16,
        )

        state_machine._battery_initial_check_done = True
        state_machine._ev_session_allowed = True

        state = state_machine._solar_state_machine(ctx)
        assert state == ChargingState.SOLAR_SUPER_CHARGING

    def test_sunrise_sunset_integration_fallback(self, time_manager, mock_hass):
        """Test sunrise/sunset integration with fallbacks."""
        # Test when sun integration is unavailable
        mock_hass.states.get = Mock(return_value=None)

        sunrise = time_manager.get_sunrise_time()
        sunset = time_manager.get_sunset_plus_10_time()

        assert sunrise == "06:00"  # Default fallback
        assert sunset == "20:30"  # Default fallback

    def test_update_state_routes_to_night(self, state_machine, mock_hass, time_manager):
        """Test that update_state routes to night state machine in night mode."""
        ctx = ChargingContext(
            ev_connected=True,
            daily_ev_energy=4.0,
            daily_ev_energy_offset=4.0,
            night_target_kwh=6.0,
        )

        # Mock night switch ON
        mock_hass.states.is_state = Mock(return_value=True)

        with patch.object(time_manager, 'is_night_mode', return_value=True):
            state = state_machine.update_state(ctx)
            assert state == ChargingState.NIGHT_CHARGING_ACTIVE

    def test_update_state_routes_to_solar(self, state_machine, time_manager):
        """Test that update_state routes to solar state machine in day mode."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=75,  # Below priority threshold
            battery_too_low=False,
        )

        with patch.object(time_manager, 'is_night_mode', return_value=False):
            state = state_machine.update_state(ctx)
            assert state == ChargingState.SOLAR_WAITING_BATTERY_PRIORITY


class TestChargingController:
    """Test the ChargingStateMachine class (formerly ChargingController)."""

    def test_update_returns_state(self, charging_controller, time_manager):
        """Test that update_state returns the new charging state."""
        ctx = ChargingContext(
            ev_connected=False,
        )

        with patch.object(time_manager, 'is_night_mode', return_value=False):
            state = charging_controller.update_state(ctx)
            assert state == ChargingState.SOLAR_IDLE

    def test_current_state_property(self, charging_controller):
        """Test the current_state property."""
        assert charging_controller.current_state == ChargingState.IDLE

    def test_reset_session(self, charging_controller):
        """Test reset_session clears session tracking."""
        charging_controller._battery_initial_check_done = True
        charging_controller._ev_session_allowed = True

        charging_controller.reset_session()

        assert charging_controller._battery_initial_check_done is False
        assert charging_controller._ev_session_allowed is False


class TestChargingContext:
    """Test ChargingContext dataclass."""

    def test_default_values(self):
        """Test default context values."""
        ctx = ChargingContext()

        assert ctx.ev_connected is False
        assert ctx.ev_charging is False
        assert ctx.battery_soc == 0.0
        assert ctx.battery_too_low is False
        assert ctx.battery_needs_priority is False
        assert ctx.calculated_current == 0.0
        assert ctx.excess_solar == 0.0
        assert ctx.available_power == 0.0
        assert ctx.daily_target_reached is False
        assert ctx.daily_ev_energy == 0.0
        assert ctx.remaining_ev_energy == 0.0
        assert ctx.charging_strategy == "idle"

    def test_custom_values(self):
        """Test context with custom values."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=85.5,
            calculated_current=12.0,
            daily_ev_energy=5.5,
        )

        assert ctx.ev_connected is True
        assert ctx.battery_soc == 85.5
        assert ctx.calculated_current == 12.0
        assert ctx.daily_ev_energy == 5.5


class TestSolarStateMachineEdgeCases:
    """Test edge cases in solar state machine."""

    def test_battery_too_low_overrides_all(self, state_machine, mock_time_day):
        """Test that battery too low state overrides everything."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=20,  # Very low
            battery_too_low=True,
            calculated_current=16,  # Would normally charge
        )

        state = state_machine._solar_state_machine(ctx)
        assert state == ChargingState.SOLAR_PAUSE_LOW_BATTERY

    def test_ev_disconnected_resets_session(self, state_machine, mock_time_day):
        """Test that EV disconnect resets session tracking."""
        state_machine._battery_initial_check_done = True
        state_machine._ev_session_allowed = True

        ctx = ChargingContext(ev_connected=False)

        state = state_machine._solar_state_machine(ctx)

        assert state == ChargingState.SOLAR_IDLE
        assert state_machine._battery_initial_check_done is False
        assert state_machine._ev_session_allowed is False

    def test_target_reached_with_excess_solar_continues(self, state_machine, mock_time_day):
        """Test that target reached allows charging with excess solar."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=95,
            battery_too_low=False,
            battery_needs_priority=False,
            daily_target_reached=True,
            excess_solar=2000,  # High excess
            calculated_current=10,
        )

        state_machine._battery_initial_check_done = True
        state_machine._ev_session_allowed = True

        # With high excess solar, should continue charging
        state = state_machine._solar_state_machine(ctx)
        assert state == ChargingState.SOLAR_CHARGING_ACTIVE

    def test_target_reached_solar_continues(self, state_machine, mock_time_day):
        """Solar keeps charging even past target — free surplus shouldn't be wasted."""
        ctx = ChargingContext(
            ev_connected=True,
            battery_soc=95,
            battery_too_low=False,
            daily_target_reached=True,
            excess_solar=500,  # Low excess but still solar
            calculated_current=10,
            charging_strategy="battery_assist",
        )

        state_machine._battery_initial_check_done = True
        state_machine._ev_session_allowed = True

        state = state_machine._solar_state_machine(ctx)
        # Solar continues — target only limits night charging
        assert state == ChargingState.SOLAR_SUPER_CHARGING


class TestNightStateMachineEdgeCases:
    """Test edge cases in night state machine."""

    def test_night_charging_uses_offset_energy(self, state_machine, mock_hass, mock_time_night):
        """Test that night charging uses offset energy when available."""
        ctx = ChargingContext(
            ev_connected=True,
            daily_ev_energy=3.0,  # Would show not enough
            daily_ev_energy_offset=6.5,  # Close to target but not within 0.1 threshold
            night_target_kwh=0.5,  # Remaining after offset
        )

        mock_hass.states.is_state = Mock(return_value=True)

        state = state_machine._night_state_machine(ctx)

        # Should still be charging (0.5 remaining, above 0.1 threshold)
        assert state == ChargingState.NIGHT_CHARGING_ACTIVE

    def test_night_charging_exactly_at_target(self, state_machine, mock_hass, mock_time_night):
        """Test night charging behavior when exactly at target."""
        ctx = ChargingContext(
            ev_connected=True,
            daily_ev_energy=7.0,
            daily_ev_energy_offset=7.0,
        )

        mock_hass.states.is_state = Mock(return_value=True)

        state = state_machine._night_state_machine(ctx)
        assert state == ChargingState.NIGHT_TARGET_REACHED


if __name__ == "__main__":
    pytest.main([__file__])
