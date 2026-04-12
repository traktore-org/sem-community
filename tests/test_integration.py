"""Integration tests for Solar Energy Management.

Tests the full setup flow, coordinator lifecycle, and cross-component
interactions that unit tests don't cover.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from homeassistant.config_entries import ConfigEntry

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.switch import (
    SEMSolarSwitch,
    SWITCH_TYPES,
    async_setup_entry as switch_setup,
)
from custom_components.solar_energy_management.sensor import (
    async_setup_entry as sensor_setup,
)
from custom_components.solar_energy_management.number import (
    EMSSolarNumber,
    NUMBER_TYPES,
    async_setup_entry as number_setup,
)
from custom_components.solar_energy_management.binary_sensor import (
    async_setup_entry as binary_sensor_setup,
)


# ============================================================
# Test: Platform entity counts
# ============================================================

@pytest.mark.unit
class TestPlatformEntityCounts:
    """Verify correct number of entities per platform."""

    @pytest.mark.asyncio
    async def test_switch_count(self, hass, config_entry, mock_coordinator):
        """Should create exactly 3 switches."""
        hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()
        await switch_setup(hass, config_entry, add_entities)
        switches = add_entities.call_args[0][0]
        assert len(switches) == 3
        keys = {s.entity_description.key for s in switches}
        assert keys == {"night_charging", "observer_mode", "forecast_night_reduction"}

    @pytest.mark.asyncio
    async def test_number_count(self, hass, config_entry, mock_coordinator):
        """Should create all number entities."""
        hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()
        await number_setup(hass, config_entry, add_entities)
        numbers = add_entities.call_args[0][0]
        # Verify all NUMBER_TYPES are created
        assert len(numbers) == len(NUMBER_TYPES)

    @pytest.mark.asyncio
    async def test_sensor_count(self, hass, config_entry, mock_coordinator):
        """Should create sensors from SENSOR_TYPES."""
        hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()
        await sensor_setup(hass, config_entry, add_entities)
        sensors = add_entities.call_args[0][0]
        assert len(sensors) > 80  # We have 100+ sensor types

    @pytest.mark.asyncio
    async def test_binary_sensor_count(self, hass, config_entry, mock_coordinator):
        """Should create binary sensors."""
        hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()
        await binary_sensor_setup(hass, config_entry, add_entities)
        sensors = add_entities.call_args[0][0]
        assert len(sensors) >= 6  # ev_connected, ev_charging, battery, grid, solar, etc.


# ============================================================
# Test: Currency configuration
# ============================================================

@pytest.mark.unit
class TestCurrencyConfiguration:
    """Verify currency reads from HA config."""

    @pytest.mark.asyncio
    async def test_sensor_uses_ha_currency(self, hass, config_entry, mock_coordinator):
        """Monetary sensors should use hass.config.currency."""
        hass.config.currency = "EUR"
        hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()
        await sensor_setup(hass, config_entry, add_entities)
        sensors = add_entities.call_args[0][0]
        monetary = [s for s in sensors if hasattr(s, '_attr_native_unit_of_measurement')
                    and s._attr_native_unit_of_measurement == "EUR"]
        assert len(monetary) > 0, "No monetary sensors found with EUR"

    @pytest.mark.asyncio
    async def test_number_uses_ha_currency(self, hass, config_entry, mock_coordinator):
        """Monetary number entities should use coordinator's hass.config.currency."""
        mock_coordinator.hass.config.currency = "USD"
        hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()
        await number_setup(hass, config_entry, add_entities)
        numbers = add_entities.call_args[0][0]
        # Find demand_charge_rate which has CHF/kW/Mt
        demand = [n for n in numbers if n.entity_description.key == "demand_charge_rate"]
        assert len(demand) == 1
        assert "USD" in demand[0]._attr_native_unit_of_measurement


# ============================================================
# Test: Switch state persistence
# ============================================================

@pytest.mark.unit
class TestSwitchDefaults:
    """Verify switch default states."""

    def test_night_charging_default_on(self, mock_coordinator):
        desc = SWITCH_TYPES[0]  # night_charging
        switch = SEMSolarSwitch(mock_coordinator, desc, "test")
        assert switch._is_on is True

    def test_observer_mode_default_off(self, mock_coordinator):
        mock_coordinator.config_entry.options = {}
        desc = SWITCH_TYPES[1]  # observer_mode
        switch = SEMSolarSwitch(mock_coordinator, desc, "test")
        assert switch._is_on is False

    def test_forecast_reduction_default_off(self, mock_coordinator):
        desc = SWITCH_TYPES[2]  # forecast_night_reduction
        switch = SEMSolarSwitch(mock_coordinator, desc, "test")
        assert switch._is_on is False


# ============================================================
# Test: EV configurable parameters
# ============================================================

@pytest.mark.unit
class TestEVConfigurableParams:
    """Verify EV parameters are configurable via number entities."""

    def test_ev_number_entities_exist(self):
        """Required EV number entities should be in NUMBER_TYPES."""
        keys = {n.key for n in NUMBER_TYPES}
        assert "ev_night_initial_current" in keys
        assert "ev_minimum_current" in keys
        assert "ev_stall_cooldown" in keys
        assert "daily_ev_target" in keys
        assert "battery_assist_max_power" in keys

    def test_ev_min_current_range(self):
        """ev_minimum_current should have 6-16A range."""
        desc = next(n for n in NUMBER_TYPES if n.key == "ev_minimum_current")
        assert desc.native_min_value == 6
        assert desc.native_max_value == 16

    def test_ev_initial_current_range(self):
        """ev_night_initial_current should have 6-32A range."""
        desc = next(n for n in NUMBER_TYPES if n.key == "ev_night_initial_current")
        assert desc.native_min_value == 6
        assert desc.native_max_value == 32

    def test_ev_stall_cooldown_range(self):
        """ev_stall_cooldown should have 30-300s range."""
        desc = next(n for n in NUMBER_TYPES if n.key == "ev_stall_cooldown")
        assert desc.native_min_value == 30
        assert desc.native_max_value == 300


# ============================================================
# Test: Charger abstraction
# ============================================================

@pytest.mark.unit
class TestChargerAbstraction:
    """Verify charger control is brand-agnostic."""

    @pytest.mark.asyncio
    async def test_start_session_without_keba(self):
        """start_session should work without KEBA-specific services."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.services.has_service = MagicMock(return_value=False)  # No KEBA services

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="EV",
            charger_service="generic.set_current",
        )
        await device.start_session(energy_target_kwh=0)

        assert device._session_active is True
        # Should not have called set_failsafe or enable (services don't exist)
        calls = [c[0] for c in hass.services.async_call.call_args_list]
        service_names = [c[1] for c in calls]
        assert "set_failsafe" not in service_names
        assert "enable" not in service_names

    @pytest.mark.asyncio
    async def test_start_session_with_enable(self):
        """start_session should call enable when available."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.services.has_service = MagicMock(side_effect=lambda d, s: s == "enable")

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="EV",
            charger_service="mycharger.set_current",
        )
        await device.start_session(energy_target_kwh=0)

        assert device._session_active is True
        calls = [c[0] for c in hass.services.async_call.call_args_list]
        assert ("mycharger", "enable") in [(c[0], c[1]) for c in calls]

    @pytest.mark.asyncio
    async def test_pilot_cycle_only_when_enabled(self):
        """disable/enable cycle should only happen when needs_pilot_cycle=True."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.services.has_service = MagicMock(return_value=True)

        # Without pilot cycle
        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="EV",
            charger_service="keba.set_current",
        )
        device.needs_pilot_cycle = False
        await device.start_session(energy_target_kwh=0)
        calls = [c[0] for c in hass.services.async_call.call_args_list]
        disable_calls = [c for c in calls if c[1] == "disable"]
        assert len(disable_calls) == 0

    @pytest.mark.asyncio
    async def test_set_current_global_services(self):
        """KEBA-style global services should not pass entity_id."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="EV",
            charger_service="keba.set_current",
            charger_service_entity_id="binary_sensor.keba_plug",
        )
        device.global_services = True
        await device._set_current(10)

        call_data = hass.services.async_call.call_args[0][2]
        assert "entity_id" not in call_data
        assert call_data["current"] == 10

    @pytest.mark.asyncio
    async def test_set_current_entity_targeted(self):
        """Non-global services should pass entity_id."""
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice

        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        device = CurrentControlDevice(
            hass=hass, device_id="ev", name="EV",
            charger_service="easee.set_current",
            charger_service_entity_id="sensor.easee_charger",
        )
        device.global_services = False
        await device._set_current(10)

        call_data = hass.services.async_call.call_args[0][2]
        assert call_data["entity_id"] == "sensor.easee_charger"
        assert call_data["current"] == 10


# ============================================================
# Test: Energy calculator — sunrise vs midnight reset
# ============================================================

@pytest.mark.unit
class TestEnergyResetBehavior:
    """Verify daily_ev resets at sunrise, others at midnight."""

    def test_ev_accumulator_key_prefix(self):
        """EV accumulator should use ev_daily_sun prefix."""
        from custom_components.solar_energy_management.coordinator.energy_calculator import EnergyCalculator
        from custom_components.solar_energy_management.utils.time_manager import TimeManager

        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        tm = TimeManager(hass)
        calc = EnergyCalculator({"update_interval": 10}, tm)

        # Verify the rollover preserves ev_daily_sun keys
        today = date(2026, 4, 3)
        calc._daily_accumulators = {
            "solar_2026-04-02": 10.0,  # old — should be deleted
            "solar_2026-04-03": 5.0,   # today — keep
            "ev_daily_sun_2026-04-02": 8.0,  # yesterday EV — keep (sunrise-based)
            "ev_daily_sun_2026-04-03": 2.0,  # today EV — keep
        }

        month_key = "2026_4"
        calc._check_rollover(today, month_key)

        assert "solar_2026-04-02" not in calc._daily_accumulators
        assert "solar_2026-04-03" in calc._daily_accumulators
        assert "ev_daily_sun_2026-04-02" in calc._daily_accumulators  # Survived midnight!
        assert "ev_daily_sun_2026-04-03" in calc._daily_accumulators

    def test_old_ev_keys_cleaned_after_two_days(self):
        """EV keys older than yesterday should be cleaned."""
        from custom_components.solar_energy_management.coordinator.energy_calculator import EnergyCalculator
        from custom_components.solar_energy_management.utils.time_manager import TimeManager

        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        tm = TimeManager(hass)
        calc = EnergyCalculator({"update_interval": 10}, tm)

        today = date(2026, 4, 5)
        calc._daily_accumulators = {
            "ev_daily_sun_2026-04-03": 8.0,  # 2 days old — should be deleted
            "ev_daily_sun_2026-04-04": 5.0,  # yesterday — keep
            "ev_daily_sun_2026-04-05": 2.0,  # today — keep
        }

        calc._check_rollover(today, "2026_4")

        assert "ev_daily_sun_2026-04-03" not in calc._daily_accumulators
        assert "ev_daily_sun_2026-04-04" in calc._daily_accumulators
        assert "ev_daily_sun_2026-04-05" in calc._daily_accumulators


# ============================================================
# Test: Night charging strategy
# ============================================================

@pytest.mark.unit
class TestNightChargingStrategy:
    """Verify night charging only uses grid when target not reached."""

    def test_night_target_reached_returns_idle(self):
        """Night mode + target reached = idle (don't charge from grid)."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power, _MockEnergy
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy(daily_ev=10.0)
        )
        assert strategy == "idle"
        assert "target reached" in reason.lower()

    def test_solar_target_reached_continues(self):
        """Daytime + target reached = solar continues (free surplus)."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power, _MockEnergy
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95, solar_power=5000), _MockEnergy(daily_ev=10.0)
        )
        assert strategy != "idle"


# ============================================================
# Test: Notification filtering
# ============================================================

@pytest.mark.unit
class TestNotificationFiltering:
    """Verify mobile notifications only fire for important events."""

    def test_mobile_for_charging_start(self):
        from custom_components.solar_energy_management.coordinator.notifications import NotificationManager
        from custom_components.solar_energy_management.const import ChargingState
        nm = NotificationManager(MagicMock(), {"daily_ev_target": 10})
        msgs = nm._get_notification_messages(ChargingState.SOLAR_CHARGING_ACTIVE,
                                              {"calculated_current": 10, "available_power": 3000,
                                               "daily_ev_energy": 5, "ev_session_energy": 0})
        assert "mobile" in msgs

    def test_no_mobile_for_pause(self):
        from custom_components.solar_energy_management.coordinator.notifications import NotificationManager
        from custom_components.solar_energy_management.const import ChargingState
        nm = NotificationManager(MagicMock(), {"daily_ev_target": 10})
        msgs = nm._get_notification_messages(ChargingState.SOLAR_PAUSE_LOW_BATTERY,
                                              {"battery_soc": 25, "calculated_current": 0,
                                               "available_power": 0, "daily_ev_energy": 5,
                                               "ev_session_energy": 0})
        assert "mobile" not in msgs

    def test_no_mobile_for_night_idle(self):
        from custom_components.solar_energy_management.coordinator.notifications import NotificationManager
        from custom_components.solar_energy_management.const import ChargingState
        nm = NotificationManager(MagicMock(), {"daily_ev_target": 10})
        msgs = nm._get_notification_messages(ChargingState.NIGHT_IDLE,
                                              {"daily_ev_energy": 0, "ev_session_energy": 0})
        assert "mobile" not in msgs
