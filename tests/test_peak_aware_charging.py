"""Test peak-aware night charging functionality.

These tests target the planned _calculate_peak_aware_night_current() method
which is not yet implemented. Skip the entire module until the feature lands.
"""
import sys
import pytest

pytest.importorskip(
    "custom_components.solar_energy_management.coordinator",
    reason="Peak-aware night charging not yet implemented",
)

# Guard: skip if the method doesn't exist yet
from custom_components.solar_energy_management.coordinator import SEMCoordinator
if not hasattr(SEMCoordinator, "_calculate_peak_aware_night_current"):
    pytest.skip(
        "SEMCoordinator._calculate_peak_aware_night_current not yet implemented",
        allow_module_level=True,
    )

from unittest.mock import Mock, AsyncMock, patch
from freezegun import freeze_time
from custom_components.solar_energy_management.const import (
    ChargingState,
    DEFAULT_TARGET_PEAK_LIMIT,
    DEFAULT_MIN_CHARGING_CURRENT,
    DEFAULT_MAX_CHARGING_CURRENT,
)


@pytest.mark.asyncio
class TestPeakAwareNightCharging:
    """Test peak-aware night charging calculations and limits."""

    async def test_calculates_safe_current_with_low_home_load(self, coordinator, mock_hass):
        """Test peak-aware current calculation with low home consumption."""
        # Setup load manager
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,  # 5kW target
            warning_level=4.5,
            emergency_level=6.0
        )

        # Setup values
        values = {
            "home_consumption_power": 750,    # 0.75kW home load
            "ev_charging_power": 0,           # Not charging yet
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        # Calculate safe current
        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # With 0.75kW home + 0.3kW buffer, we have ~4.0kW available for EV
        # 4000W / (3 phases * 230V * 0.95 PF) = ~6.1A
        # Should return 6A (minimum)
        assert safe_current == 6  # Minimum charging current

    async def test_calculates_safe_current_with_high_home_load(self, coordinator, mock_hass):
        """Test that charging pauses when home load too high."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        values = {
            "home_consumption_power": 4500,   # 4.5kW home load (high!)
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # With 4.5kW home + 0.3kW buffer, only 0.2kW available
        # Not enough for 6A minimum (4.1kW required)
        # Should pause charging
        assert safe_current == 0

    async def test_accounts_for_current_ev_charging(self, coordinator, mock_hass):
        """Test that current EV charging power is subtracted from home load."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        values = {
            "home_consumption_power": 5000,   # 5kW total (includes EV)
            "ev_charging_power": 4100,        # 4.1kW EV charging
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # Base load = 5.0 - 4.1 = 0.9kW
        # Available = 5.0 - 0.9 - 0.3 = 3.8kW
        # Current = 3800 / 655.5 = ~5.8A → rounds to 6A
        assert safe_current == 6

    async def test_returns_zero_when_not_night_charging(self, coordinator, mock_hass):
        """Test that function returns 0 when not in night charging mode."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        values = {
            "home_consumption_power": 1000,
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.IDLE  # Not night charging!
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)
        assert safe_current == 0

    async def test_returns_max_when_load_management_disabled(self, coordinator, mock_hass):
        """Test that max current is returned when load management is disabled."""
        # No load manager (disabled)
        coordinator._load_manager = None

        values = {
            "home_consumption_power": 1000,
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # Should return maximum current when load management disabled
        assert safe_current == DEFAULT_MAX_CHARGING_CURRENT  # 16A

    async def test_clamps_to_maximum_current(self, coordinator, mock_hass):
        """Test that calculated current is clamped to maximum (16A for KEBA)."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=15.0,  # Very high limit
            warning_level=12.0,
            emergency_level=18.0
        )

        values = {
            "home_consumption_power": 500,    # Very low home load
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # With 15kW limit, calculated current would be ~22A
        # But KEBA max is 16A, so should clamp
        assert safe_current == DEFAULT_MAX_CHARGING_CURRENT  # 16A

    async def test_buffer_prevents_oscillation(self, coordinator, mock_hass):
        """Test that 0.3kW buffer prevents rapid on/off cycling."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        # Just at the edge: 5.0 - 0.3 buffer = 4.7kW effective limit
        values = {
            "home_consumption_power": 4700,   # Right at buffer threshold
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # Available = 5.0 - 4.7 - 0.3 = 0kW
        # Should pause (not enough for minimum)
        assert safe_current == 0

    async def test_applies_current_to_charger_via_service(self, coordinator, mock_hass):
        """Test that calculated current is applied to KEBA charger via service."""
        # Mock service call
        mock_hass.services.async_call = AsyncMock()

        # Configure EV charger service
        coordinator.config["ev_charger_service"] = "keba.set_current"
        coordinator.config["ev_charger_service_entity_id"] = "binary_sensor.keba_p30_plug"

        values = {
            "ev_connected": True,
            "ev_charging": True,
        }

        # Call the apply function
        await coordinator._apply_ev_charging_current(
            ChargingState.NIGHT_CHARGING_ACTIVE,
            target_current=8,  # 8A target
            values=values
        )

        # Verify service was called
        mock_hass.services.async_call.assert_called_once()
        call_args = mock_hass.services.async_call.call_args

        # Check service call details
        assert call_args[0][0] == "keba"  # Domain
        assert call_args[0][1] == "set_current"  # Service
        assert call_args[1]["entity_id"] == "binary_sensor.keba_p30_plug"
        assert call_args[1]["current"] == 8

    async def test_skips_apply_when_ev_not_connected(self, coordinator, mock_hass):
        """Test that current is not applied when EV is not connected."""
        mock_hass.services.async_call = AsyncMock()

        coordinator.config["ev_charger_service"] = "keba.set_current"
        coordinator.config["ev_charger_service_entity_id"] = "binary_sensor.keba_p30_plug"

        values = {
            "ev_connected": False,  # EV not connected!
            "ev_charging": False,
        }

        await coordinator._apply_ev_charging_current(
            ChargingState.NIGHT_CHARGING_ACTIVE,
            target_current=8,
            values=values
        )

        # Service should NOT be called
        mock_hass.services.async_call.assert_not_called()

    async def test_skips_apply_when_not_night_charging(self, coordinator, mock_hass):
        """Test that current is not applied when not in night charging mode."""
        mock_hass.services.async_call = AsyncMock()

        coordinator.config["ev_charger_service"] = "keba.set_current"
        coordinator.config["ev_charger_service_entity_id"] = "binary_sensor.keba_p30_plug"

        values = {
            "ev_connected": True,
            "ev_charging": True,
        }

        await coordinator._apply_ev_charging_current(
            ChargingState.IDLE,  # Not night charging
            target_current=8,
            values=values
        )

        # Service should NOT be called
        mock_hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
class TestPeakAwareEdgeCases:
    """Test edge cases in peak-aware charging."""

    async def test_handles_negative_home_power(self, coordinator, mock_hass):
        """Test handling of negative home power (shouldn't happen but be safe)."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        values = {
            "home_consumption_power": -500,   # Negative (invalid)
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        # Should not crash
        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # Should treat as 0 and allow full charging
        assert safe_current >= 0

    async def test_handles_missing_home_power_value(self, coordinator, mock_hass):
        """Test handling of missing home_consumption_power key."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        values = {
            # Missing home_consumption_power!
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        # Should use default 0
        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # Should not crash
        assert safe_current >= 0

    async def test_handles_very_high_peak_limit(self, coordinator, mock_hass):
        """Test with unrealistically high peak limit (commercial installation)."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=100.0,  # 100kW!
            warning_level=90.0,
            emergency_level=110.0
        )

        values = {
            "home_consumption_power": 5000,
            "ev_charging_power": 0,
        }

        calc = {
            "charging_state": ChargingState.NIGHT_CHARGING_ACTIVE
        }

        safe_current = coordinator._calculate_peak_aware_night_current(calc, values)

        # Should clamp to max charger capability (16A), not exceed it
        assert safe_current == DEFAULT_MAX_CHARGING_CURRENT

    async def test_battery_protection_during_night_charging(self, coordinator, mock_hass):
        """Test that battery discharge is limited during night charging."""
        # Mock battery discharge control entity
        mock_hass.states.get = Mock(return_value=Mock(state="5000"))
        mock_hass.services.async_call = AsyncMock()

        coordinator.config["battery_discharge_protection_enabled"] = True
        coordinator.config["battery_discharge_control_entity"] = "number.battery_max_discharge"
        coordinator.config["battery_max_discharge_power"] = 5000

        values = {
            "home_consumption_power": 1500,
            "battery_power": -3000,  # Discharging 3kW
            "ev_charging_power": 9000,  # Charging 9kW
            "grid_power": -10500,  # Importing
            "ev_charging": True,
        }

        # Apply battery protection
        await coordinator._apply_battery_discharge_protection(
            ChargingState.NIGHT_CHARGING_ACTIVE,
            values
        )

        # Battery discharge should be limited to home consumption (1.5kW)
        mock_hass.services.async_call.assert_called()
        call_args = mock_hass.services.async_call.call_args

        # Check that discharge limit was set to home consumption
        assert call_args[1]["value"] == 1500  # Limited to home load

    async def test_integrates_with_load_management_sensors(self, coordinator, mock_hass):
        """Test that peak-aware charging updates load management sensors."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        # Process peak update
        await coordinator._load_manager.process_peak_update(
            current_peak=4.8,  # Current 15-min peak
            monthly_peak=6.2    # Monthly peak
        )

        # Load manager should track these values
        assert coordinator._load_manager._current_peak == 4.8
        assert coordinator._load_manager._monthly_peak == 6.2


@pytest.mark.asyncio
class TestPeakAwareRealWorldScenarios:
    """Test real-world scenarios for peak-aware charging."""

    async def test_scenario_washing_machine_starts_during_charging(self, coordinator, mock_hass):
        """Test that charging current reduces when washing machine starts."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        # Before: Low home load, EV charging at 10A
        values_before = {
            "home_consumption_power": 800,
            "ev_charging_power": 6800,  # 10A
        }
        calc = {"charging_state": ChargingState.NIGHT_CHARGING_ACTIVE}

        current_before = coordinator._calculate_peak_aware_night_current(calc, values_before)
        assert current_before >= 10  # Can charge at 10A

        # After: Washing machine starts (adds 2kW)
        values_after = {
            "home_consumption_power": 2800,  # +2kW from washing machine
            "ev_charging_power": 6800,
        }

        current_after = coordinator._calculate_peak_aware_night_current(calc, values_after)

        # Current should reduce to stay under 5kW limit
        assert current_after < current_before
        # Should likely pause (< 6A minimum)
        assert current_after == 0

    async def test_scenario_gradual_home_load_increase(self, coordinator, mock_hass):
        """Test gradual reduction in charging current as home load increases."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        calc = {"charging_state": ChargingState.NIGHT_CHARGING_ACTIVE}

        # Test increasing home loads
        test_cases = [
            (500, 6),   # Very low → 6A (min)
            (1000, 6),  # Low → 6A
            (2000, 6),  # Medium → 6A (still enough)
            (4000, 0),  # High → 0A (pause)
            (4500, 0),  # Very high → 0A
        ]

        for home_power, expected_min_current in test_cases:
            values = {
                "home_consumption_power": home_power,
                "ev_charging_power": 0,
            }

            current = coordinator._calculate_peak_aware_night_current(calc, values)

            if expected_min_current == 0:
                assert current == 0, f"At {home_power}W home, should pause charging"
            else:
                assert current >= expected_min_current, (
                    f"At {home_power}W home, should allow at least {expected_min_current}A"
                )

    async def test_scenario_overnight_charging_with_variable_load(self, coordinator, mock_hass):
        """Simulate overnight charging with realistic load variations."""
        from custom_components.solar_energy_management.load_management import LoadManager
        coordinator._load_manager = LoadManager(
            hass=mock_hass,
            target_peak_limit=5.0,
            warning_level=4.5,
            emergency_level=6.0
        )

        calc = {"charging_state": ChargingState.NIGHT_CHARGING_ACTIVE}

        # Simulate hourly home load variations overnight
        overnight_loads = [
            ("22:00", 1500),  # Evening devices
            ("23:00", 1200),  # Winding down
            ("00:00", 800),   # Night minimum
            ("01:00", 750),   # Lowest
            ("02:00", 800),   # Stable
            ("03:00", 900),   # Fridge cycles
            ("04:00", 850),   # Stable
            ("05:00", 1100),  # Water heater
            ("06:00", 1800),  # Morning devices
        ]

        charging_log = []

        for time, home_load in overnight_loads:
            with freeze_time(f"2025-11-12 {time}:00"):
                values = {
                    "home_consumption_power": home_load,
                    "ev_charging_power": 0,  # Will be set by calculation
                }

                current = coordinator._calculate_peak_aware_night_current(calc, values)
                charging_log.append((time, home_load, current))

                # All should allow at least minimum current (6A)
                # except possibly the last one at 06:00 with 1800W load
                if home_load < 4000:
                    assert current == 6, f"At {time} with {home_load}W, should charge at 6A"

        # Verify overnight charging was mostly continuous
        charging_hours = sum(1 for _, _, current in charging_log if current > 0)
        assert charging_hours >= 7, "Should charge for most of the night"
