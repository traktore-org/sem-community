"""Tests for LoadManagementCoordinator (load_management.py)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from custom_components.solar_energy_management.load_management import (
    LoadManagementCoordinator,
)
from custom_components.solar_energy_management.const import LoadManagementState


# --- Fixtures ---


@pytest.fixture
def config_entry_lm():
    """Return a config entry with load management options."""
    entry = MagicMock()
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "test_entry"
    return entry


@pytest.fixture
def config_entry_disabled():
    """Return a config entry with load management disabled."""
    entry = MagicMock()
    entry.options = {
        "load_management_enabled": False,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "test_entry"
    return entry


@pytest.fixture
def lm(hass, config_entry_lm):
    """Return a LoadManagementCoordinator with mocked dependencies."""
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ) as MockDiscovery, patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        mock_discovery = MagicMock()
        mock_discovery.discover_from_energy_dashboard = AsyncMock(return_value={})
        mock_discovery.discover_controllable_devices = MagicMock(return_value={})
        mock_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": False, "current_power": 0}
        )
        mock_discovery.turn_off_device = AsyncMock(return_value=True)
        mock_discovery.turn_on_device = AsyncMock(return_value=True)
        MockDiscovery.return_value = mock_discovery

        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_save = AsyncMock()
        MockStore.return_value = mock_store

        coordinator = LoadManagementCoordinator(hass, config_entry_lm)
        # Replace the store that was created in __init__
        coordinator._store = mock_store
        coordinator._device_discovery = mock_discovery
        yield coordinator


@pytest.fixture
def lm_disabled(hass, config_entry_disabled):
    """Return a disabled LoadManagementCoordinator."""
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ) as MockDiscovery, patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        MockDiscovery.return_value = MagicMock()
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_save = AsyncMock()
        MockStore.return_value = mock_store
        coordinator = LoadManagementCoordinator(hass, config_entry_disabled)
        coordinator._store = mock_store
        yield coordinator


def _add_device(lm_coord, device_id, priority=5, is_critical=False, is_on=True, power=1000):
    """Helper to add a device to the coordinator."""
    lm_coord._devices[device_id] = {
        "switch_entity": f"switch.{device_id}",
        "power_entity": f"sensor.{device_id}_power",
        "friendly_name": device_id.replace("_", " ").title(),
        "power_rating": power / 1000,
        "is_available": True,
        "priority": priority,
        "is_critical": is_critical,
        "is_controllable": True,
    }
    # Make the discovery mock report the device as on/off
    original_get_state = lm_coord._device_discovery.get_device_current_state

    def _get_state(device_info):
        if device_info.get("switch_entity") == f"switch.{device_id}":
            return {"is_on": is_on, "current_power": power if is_on else 0}
        return original_get_state(device_info)

    lm_coord._device_discovery.get_device_current_state = MagicMock(side_effect=_get_state)


# --- Tests ---


class TestInit:
    """Test LoadManagementCoordinator initialization."""

    def test_init(self, lm, config_entry_lm):
        """Verify defaults loaded from config_entry.options."""
        assert lm._target_peak_limit == 5.0
        assert lm._warning_level == 4.5
        assert lm._emergency_level == 6.0
        assert lm._hysteresis == 0.3
        assert lm._enabled is True
        assert lm._state == LoadManagementState.NORMAL
        assert lm._devices == {}
        assert lm._devices_shed == []

    def test_is_enabled(self, lm):
        """Returns True when enabled in config."""
        assert lm.is_enabled() is True

    def test_is_disabled(self, lm_disabled):
        """Returns False when disabled in config."""
        assert lm_disabled.is_enabled() is False


class TestDetermineState:
    """Test _determine_load_management_state method."""

    def test_determine_state_normal(self, lm):
        """Peak below warning level returns NORMAL."""
        state = lm._determine_load_management_state(3.0, 3.0)
        assert state == LoadManagementState.NORMAL

    def test_determine_state_warning(self, lm):
        """Peak between warning and target returns WARNING."""
        state = lm._determine_load_management_state(4.7, 4.7)
        assert state == LoadManagementState.WARNING

    def test_determine_state_shedding(self, lm):
        """Peak at or above target limit returns SHEDDING."""
        state = lm._determine_load_management_state(5.0, 5.0)
        assert state == LoadManagementState.SHEDDING

    def test_determine_state_shedding_above_target(self, lm):
        """Peak above target limit returns SHEDDING."""
        state = lm._determine_load_management_state(5.5, 5.5)
        assert state == LoadManagementState.SHEDDING

    def test_determine_state_emergency(self, lm):
        """Peak at or above emergency level returns EMERGENCY."""
        state = lm._determine_load_management_state(6.0, 6.0)
        assert state == LoadManagementState.EMERGENCY

    def test_determine_state_emergency_above(self, lm):
        """Peak well above emergency level returns EMERGENCY."""
        state = lm._determine_load_management_state(8.0, 8.0)
        assert state == LoadManagementState.EMERGENCY

    def test_determine_state_restore_hysteresis(self, lm):
        """Peak below target minus hysteresis returns NORMAL."""
        # target=5.0, hysteresis=0.3, restore_threshold=4.7
        # Peak at 4.5 is below warning_level (4.5)? Actually 4.5 == warning_level.
        # Let's go well below.
        state = lm._determine_load_management_state(4.0, 4.0)
        assert state == LoadManagementState.NORMAL

    def test_determine_state_with_shed_devices_below_warning(self, lm):
        """With shed devices, peak below warning returns NORMAL to allow restore."""
        lm._devices_shed = ["device_a"]
        state = lm._determine_load_management_state(3.0, 3.0)
        assert state == LoadManagementState.NORMAL

    def test_determine_state_with_shed_devices_in_warning_zone(self, lm):
        """With shed devices, peak in warning zone stays SHEDDING."""
        lm._devices_shed = ["device_a"]
        state = lm._determine_load_management_state(4.7, 4.7)
        assert state == LoadManagementState.SHEDDING


class TestProcessPeakUpdate:
    """Test process_peak_update method."""

    @pytest.mark.asyncio
    async def test_process_peak_update_disabled(self, lm_disabled):
        """Does nothing when load management is disabled."""
        initial_state = lm_disabled._state
        await lm_disabled.process_peak_update(10.0, 10.0)
        assert lm_disabled._state == initial_state

    @pytest.mark.asyncio
    async def test_process_peak_update_state_change(self, lm):
        """Transitions from NORMAL to WARNING on peak increase."""
        assert lm._state == LoadManagementState.NORMAL
        await lm.process_peak_update(4.7, 4.7)
        assert lm._state == LoadManagementState.WARNING

    @pytest.mark.asyncio
    async def test_process_peak_update_to_emergency(self, lm):
        """Transitions to EMERGENCY on very high peak."""
        await lm.process_peak_update(7.0, 7.0)
        assert lm._state == LoadManagementState.EMERGENCY

    @pytest.mark.asyncio
    async def test_process_peak_update_stays_normal(self, lm):
        """Stays NORMAL when peak is low."""
        await lm.process_peak_update(2.0, 2.0)
        assert lm._state == LoadManagementState.NORMAL


class TestRegisterEvCharger:
    """Test register_ev_charger method."""

    @pytest.mark.asyncio
    async def test_register_ev_charger(self, lm):
        """Registers EV charger device with current control entity."""
        state_mock = MagicMock()
        state_mock.state = "16"
        state_mock.attributes = {"friendly_name": "KEBA P30 Current"}
        lm.hass.states.get = MagicMock(return_value=state_mock)

        result = await lm.register_ev_charger(
            current_control_entity="number.keba_charging_current",
            power_entity="sensor.keba_charging_power",
            priority=3,
        )
        assert result is True
        assert "load_device_ev_charger" in lm._devices
        device = lm._devices["load_device_ev_charger"]
        assert device["device_type"] == "ev_charger"
        assert device["priority"] == 3
        assert device["control_type"] == "current"

    @pytest.mark.asyncio
    async def test_register_ev_charger_no_control(self, lm):
        """Returns False when no control entity or service provided."""
        result = await lm.register_ev_charger(
            current_control_entity=None,
            power_entity="sensor.keba_charging_power",
            charger_service=None,
        )
        assert result is False
        assert "load_device_ev_charger" not in lm._devices

    @pytest.mark.asyncio
    async def test_register_ev_charger_with_service(self, lm):
        """Registers EV charger with service-based control."""
        lm.hass.states.get = MagicMock(return_value=None)

        result = await lm.register_ev_charger(
            current_control_entity=None,
            power_entity="sensor.keba_charging_power",
            charger_service="keba.set_current",
        )
        assert result is True
        device = lm._devices["load_device_ev_charger"]
        assert device["charger_service"] == "keba.set_current"


class TestUpdateMethods:
    """Test update methods."""

    @pytest.mark.asyncio
    async def test_update_target_peak_limit(self, lm):
        """Updates the target peak limit."""
        await lm.update_target_peak_limit(7.5)
        assert lm._target_peak_limit == 7.5

    @pytest.mark.asyncio
    async def test_update_device_priority(self, lm):
        """Updates device priority."""
        _add_device(lm, "boiler", priority=5)
        await lm.update_device_priority("boiler", 8)
        assert lm._devices["boiler"]["priority"] == 8

    @pytest.mark.asyncio
    async def test_update_device_priority_nonexistent(self, lm):
        """Does nothing for nonexistent device."""
        await lm.update_device_priority("nonexistent", 8)
        # Should not raise

    @pytest.mark.asyncio
    async def test_update_device_critical_status(self, lm):
        """Updates critical flag on device."""
        _add_device(lm, "fridge", is_critical=False)
        await lm.update_device_critical_status("fridge", True)
        assert lm._devices["fridge"]["is_critical"] is True


class TestGetLoadManagementData:
    """Test get_load_management_data method."""

    def test_get_load_management_data(self, lm):
        """Returns correct structure with expected keys."""
        data = lm.get_load_management_data()
        assert data["state"] == LoadManagementState.NORMAL
        assert data["target_peak_limit"] == 5.0
        assert data["warning_level"] == 4.5
        assert data["emergency_level"] == 6.0
        assert data["total_devices"] == 0
        assert data["controllable_devices"] == 0
        assert data["devices_shed"] == 0
        assert data["devices_shed_list"] == []
        assert data["enabled"] is True

    def test_get_load_management_data_with_devices(self, lm):
        """Reflects device count correctly."""
        _add_device(lm, "boiler", priority=5)
        data = lm.get_load_management_data()
        assert data["total_devices"] == 1
        assert data["controllable_devices"] == 1


class TestGetPeakMargin:
    """Test get_peak_margin method."""

    def test_get_peak_margin(self, lm):
        """Calculates margin correctly."""
        margin = lm.get_peak_margin(3.0)
        assert margin == 2.0

    def test_get_peak_margin_at_limit(self, lm):
        """Returns 0 when at target limit."""
        margin = lm.get_peak_margin(5.0)
        assert margin == 0.0

    def test_get_peak_margin_over_limit(self, lm):
        """Returns 0 when above target limit."""
        margin = lm.get_peak_margin(7.0)
        assert margin == 0.0


class TestCallbacks:
    """Test callback management."""

    def test_add_remove_callback(self, lm):
        """Add and remove callbacks."""
        cb = MagicMock()
        lm.add_update_callback(cb)
        assert cb in lm._update_callbacks

        lm.remove_update_callback(cb)
        assert cb not in lm._update_callbacks

    def test_remove_nonexistent_callback(self, lm):
        """Removing a callback that was never added does not raise."""
        cb = MagicMock()
        lm.remove_update_callback(cb)  # Should not raise

    def test_trigger_callbacks(self, lm):
        """Callbacks are called when triggered."""
        cb = MagicMock()
        lm.add_update_callback(cb)
        lm._trigger_callbacks()
        cb.assert_called_once()


class TestEmergencyShedding:
    """Test emergency load shedding."""

    @pytest.mark.asyncio
    async def test_emergency_shedding(self, lm):
        """Sheds all non-critical devices in emergency."""
        # Add devices with different priorities
        lm._devices["dev_high"] = {
            "switch_entity": "switch.dev_high",
            "power_entity": "sensor.dev_high_power",
            "friendly_name": "High Priority",
            "power_rating": 2.0,
            "is_available": True,
            "priority": 8,
            "is_critical": False,
            "is_controllable": True,
        }
        lm._devices["dev_critical"] = {
            "switch_entity": "switch.dev_critical",
            "power_entity": "sensor.dev_critical_power",
            "friendly_name": "Critical Device",
            "power_rating": 1.0,
            "is_available": True,
            "priority": 1,
            "is_critical": True,
            "is_controllable": True,
        }

        # Make devices appear as "on"
        lm._device_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": True, "current_power": 2000}
        )

        await lm._emergency_load_shedding()

        # Non-critical device should be shed
        assert "dev_high" in lm._devices_shed
        # Critical device should NOT be shed
        assert "dev_critical" not in lm._devices_shed

    @pytest.mark.asyncio
    async def test_emergency_shedding_already_shed(self, lm):
        """Does not re-shed devices already in shed list."""
        lm._devices["dev_a"] = {
            "switch_entity": "switch.dev_a",
            "friendly_name": "Device A",
            "power_rating": 2.0,
            "is_available": True,
            "priority": 8,
            "is_critical": False,
            "is_controllable": True,
        }
        lm._devices_shed = ["dev_a"]

        lm._device_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": True, "current_power": 2000}
        )

        await lm._emergency_load_shedding()
        # Should still only appear once
        assert lm._devices_shed.count("dev_a") == 1


class TestProgressiveShedding:
    """Test progressive load shedding."""

    @pytest.mark.asyncio
    async def test_progressive_shedding(self, lm):
        """Sheds devices by priority until enough power is reduced."""
        # Add two devices: high priority shed first
        lm._devices["dev_low_pri"] = {
            "switch_entity": "switch.dev_low_pri",
            "power_entity": "sensor.dev_low_pri_power",
            "friendly_name": "Low Priority",
            "power_rating": 1.5,
            "is_available": True,
            "priority": 3,
            "is_critical": False,
            "is_controllable": True,
        }
        lm._devices["dev_high_pri"] = {
            "switch_entity": "switch.dev_high_pri",
            "power_entity": "sensor.dev_high_pri_power",
            "friendly_name": "High Priority",
            "power_rating": 2.0,
            "is_available": True,
            "priority": 8,
            "is_critical": False,
            "is_controllable": True,
        }

        lm._device_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": True, "current_power": 2000}
        )

        # current_peak=5.5, target=5.0, hysteresis=0.3 => need to reduce 0.8kW
        await lm._progressive_load_shedding(5.5, 5.5)

        # At least one device should be shed (the highest priority number first)
        assert len(lm._devices_shed) >= 1


class TestRestoreLoads:
    """Test load restoration."""

    @pytest.mark.asyncio
    async def test_restore_loads(self, lm):
        """Restores shed devices when state is NORMAL."""
        lm._devices["dev_a"] = {
            "switch_entity": "switch.dev_a",
            "friendly_name": "Device A",
            "power_rating": 2.0,
            "is_available": True,
            "priority": 5,
            "is_critical": False,
            "is_controllable": True,
        }
        lm._devices_shed = ["dev_a"]
        # Ensure restore delay has passed
        lm._last_restore_time = None

        # Device is currently off (shed)
        lm._device_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": False, "current_power": 0}
        )

        await lm._restore_loads()
        assert "dev_a" not in lm._devices_shed

    @pytest.mark.asyncio
    async def test_restore_loads_empty(self, lm):
        """Does nothing when no devices are shed."""
        await lm._restore_loads()
        assert lm._devices_shed == []

    @pytest.mark.asyncio
    async def test_restore_loads_respects_delay(self, lm):
        """Does not restore if restore delay has not elapsed."""
        lm._devices["dev_a"] = {
            "switch_entity": "switch.dev_a",
            "friendly_name": "Device A",
            "power_rating": 2.0,
            "is_available": True,
            "priority": 5,
            "is_critical": False,
            "is_controllable": True,
        }
        lm._devices_shed = ["dev_a"]

        # Set last restore to just now
        with patch(
            "custom_components.solar_energy_management.features.load_management.dt_util"
        ) as mock_dt:
            now = datetime(2026, 3, 19, 12, 0, 0)
            mock_dt.now.return_value = now
            lm._last_restore_time = now - timedelta(seconds=5)  # Only 5s ago

            await lm._restore_loads()
            # Device should still be shed (delay not elapsed)
            assert "dev_a" in lm._devices_shed
