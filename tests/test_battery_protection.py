"""Tests for coordinator/battery_protection.py."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.solar_energy_management.coordinator.battery_protection import (
    BatteryProtectionMixin,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.const import ChargingState


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

class FakeCoordinator(BatteryProtectionMixin):
    """Minimal coordinator stub to host the mixin."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self._battery_protection_active = False
        self._last_discharge_limit = None


@pytest.fixture
def hass():
    """Return a mocked Home Assistant instance."""
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    # Default: control entity exists with state 5000
    state = MagicMock()
    state.state = "5000"
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=state)
    return h


@pytest.fixture
def config():
    """Return a default config for battery protection."""
    return {
        "battery_discharge_protection_enabled": True,
        "battery_discharge_control_entity": "number.battery_discharge_limit",
        "battery_max_discharge_power": 5000,
        "battery_hold_solar_ev": False,
    }


@pytest.fixture
def coordinator(hass, config):
    """Return a FakeCoordinator with battery protection mixin."""
    return FakeCoordinator(hass, config)


def _make_power(home=1000, ev_charging=True):
    """Create a PowerReadings for testing."""
    p = PowerReadings(
        home_consumption_power=home,
        ev_power=3000 if ev_charging else 0,
        ev_charging=ev_charging,
    )
    return p


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_protection_activates_during_night_charging(coordinator):
    """Test that protection activates during night charging when EV is charging."""
    power = _make_power(home=1200, ev_charging=True)

    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.NIGHT_CHARGING_ACTIVE, power
    )

    # Should have set discharge limit to home consumption
    assert result is not None
    assert result == 1200
    assert coordinator._battery_protection_active is True
    coordinator.hass.services.async_call.assert_called()

    # Verify the service call
    call_args = coordinator.hass.services.async_call.call_args
    assert call_args[0][0] == "number"
    assert call_args[0][1] == "set_value"
    assert call_args[0][2]["value"] == 1200


@pytest.mark.asyncio
async def test_protection_limits_discharge_to_home(coordinator):
    """Test that discharge limit matches home consumption power."""
    power = _make_power(home=800, ev_charging=True)

    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.NIGHT_CHARGING_ACTIVE, power
    )

    assert result == 800


@pytest.mark.asyncio
async def test_protection_deactivates_when_not_night(coordinator):
    """Test that protection deactivates when not in night charging."""
    # First activate protection
    coordinator._battery_protection_active = True
    coordinator._last_discharge_limit = 1000

    power = _make_power(home=1000, ev_charging=False)

    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.SOLAR_CHARGING_ACTIVE, power
    )

    assert result is None
    assert coordinator._battery_protection_active is False
    assert coordinator._last_discharge_limit is None

    # Should have restored max discharge
    call_args = coordinator.hass.services.async_call.call_args
    assert call_args[0][2]["value"] == 5000


@pytest.mark.asyncio
async def test_protection_not_active_when_disabled(coordinator):
    """Test that protection does not activate when disabled in config."""
    coordinator.config["battery_discharge_protection_enabled"] = False
    power = _make_power(home=1000, ev_charging=True)

    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.NIGHT_CHARGING_ACTIVE, power
    )

    assert result is None
    coordinator.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_startup_restore_clears_stale_limit(coordinator):
    """Test that startup restore resets discharge limit to max if below max."""
    # Simulate a stale limit from previous run
    state = MagicMock()
    state.state = "1500"  # Below max of 5000
    coordinator.hass.states.get = MagicMock(return_value=state)

    await coordinator._restore_battery_discharge_limit_on_startup()

    # Should restore to max
    call_args = coordinator.hass.services.async_call.call_args
    assert call_args[0][2]["value"] == 5000


@pytest.mark.asyncio
async def test_startup_restore_no_action_at_max(coordinator):
    """Test that startup restore does nothing when already at max."""
    state = MagicMock()
    state.state = "5000"  # Already at max
    coordinator.hass.states.get = MagicMock(return_value=state)

    await coordinator._restore_battery_discharge_limit_on_startup()

    coordinator.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_max_discharge_power_cap(coordinator):
    """Test that discharge limit is capped at max_discharge_power."""
    # Home consumption higher than max discharge
    power = _make_power(home=8000, ev_charging=True)

    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.NIGHT_CHARGING_ACTIVE, power
    )

    # Should be capped at 5000
    assert result == 5000


@pytest.mark.asyncio
async def test_protection_no_control_entity(coordinator):
    """Test graceful handling when no control entity configured."""
    coordinator.config["battery_discharge_control_entity"] = ""
    power = _make_power(home=1000, ev_charging=True)

    # Should not raise, should return None since no entity to control
    # but protection_active logic still evaluates
    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.NIGHT_CHARGING_ACTIVE, power
    )
    # With empty control_entity, the if guard skips the service call
    # The method still sets _last_discharge_limit
    assert coordinator._last_discharge_limit is not None


@pytest.mark.asyncio
async def test_protection_solar_ev_with_battery_hold(coordinator):
    """Test protection activates during solar EV charging when battery_hold_solar_ev is True."""
    coordinator.config["battery_hold_solar_ev"] = True
    power = _make_power(home=1000, ev_charging=True)

    result = await coordinator._apply_battery_discharge_protection(
        ChargingState.SOLAR_CHARGING_ACTIVE, power
    )

    assert result is not None
    assert coordinator._battery_protection_active is True
