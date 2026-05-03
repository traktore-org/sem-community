"""Tests for appliance dependency system (#122).

Tests activation gate, deactivation cascade, circular detection,
and multi-level dependency chains.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from custom_components.solar_energy_management.devices.base import (
    ControllableDevice, SwitchDevice, DeviceState,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)


def _make_switch(hass, device_id, name, priority=5, depends_on=None):
    """Create a mock switch device."""
    device = SwitchDevice(
        hass=hass, device_id=device_id, name=name,
        priority=priority, entity_id=f"switch.{device_id}",
        power_entity_id=f"sensor.{device_id}_power",
        rated_power=1000,
    )
    if depends_on:
        device.depends_on = depends_on
    return device


def _make_controller(hass):
    """Create a surplus controller."""
    controller = SurplusController(hass, {})
    return controller


@pytest.fixture
def hass():
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    return h


# ════════════════════════════════════════════
# Activation Gate
# ════════════════════════════════════════════

class TestActivationGate:
    """Device cannot activate unless all dependencies are met."""

    def test_no_dependencies_can_activate(self, hass):
        """Device without dependencies can always activate."""
        device = _make_switch(hass, "heater", "Heater")
        controller = _make_controller(hass)
        controller.register_device(device)
        assert device.can_activate() is True

    def test_blocked_when_dependency_inactive(self, hass):
        """Device blocked when depends_on device is not active."""
        pump = _make_switch(hass, "pump", "Pool Pump", priority=1)
        heater = _make_switch(hass, "heater", "Pool Heater", priority=2, depends_on=["pump"])

        controller = _make_controller(hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Pump is idle — heater should be blocked
        assert heater.can_activate() is False
        assert heater.blocked_by_dependency == "pump"

    def test_allowed_when_dependency_active(self, hass):
        """Device can activate when depends_on device is active."""
        pump = _make_switch(hass, "pump", "Pool Pump", priority=1)
        heater = _make_switch(hass, "heater", "Pool Heater", priority=2, depends_on=["pump"])

        controller = _make_controller(hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Activate pump
        pump._status.state = DeviceState.ACTIVE

        assert heater.can_activate() is True
        assert heater.blocked_by_dependency is None

    def test_must_inactive_mode(self, hass):
        """Device with must_inactive blocks when dependency IS active."""
        main = _make_switch(hass, "main", "Main Heater", priority=1)
        backup = _make_switch(hass, "backup", "Backup Heater", priority=2, depends_on=["main"])
        backup.dependency_mode = "must_inactive"

        controller = _make_controller(hass)
        controller.register_device(main)
        controller.register_device(backup)

        # Main is active — backup should be blocked
        main._status.state = DeviceState.ACTIVE
        assert backup.can_activate() is False

        # Main is idle — backup can activate
        main._status.state = DeviceState.IDLE
        assert backup.can_activate() is True

    def test_multiple_dependencies(self, hass):
        """Device with multiple dependencies needs ALL satisfied."""
        pump = _make_switch(hass, "pump", "Pump", priority=1)
        valve = _make_switch(hass, "valve", "Valve", priority=2)
        heater = _make_switch(hass, "heater", "Heater", priority=3, depends_on=["pump", "valve"])

        controller = _make_controller(hass)
        controller.register_device(pump)
        controller.register_device(valve)
        controller.register_device(heater)

        # Only pump active — heater still blocked
        pump._status.state = DeviceState.ACTIVE
        assert heater.can_activate() is False

        # Both active — heater can go
        valve._status.state = DeviceState.ACTIVE
        assert heater.can_activate() is True


# ════════════════════════════════════════════
# Deactivation Cascade
# ════════════════════════════════════════════

class TestDeactivationCascade:
    """Deactivating a device should cascade to its dependents."""

    def test_get_dependents(self, hass):
        """get_dependents returns all devices that depend on given ID."""
        pump = _make_switch(hass, "pump", "Pump")
        heater = _make_switch(hass, "heater", "Heater", depends_on=["pump"])
        fan = _make_switch(hass, "fan", "Fan", depends_on=["pump"])
        light = _make_switch(hass, "light", "Light")  # No dependency

        controller = _make_controller(hass)
        for d in [pump, heater, fan, light]:
            controller.register_device(d)

        deps = controller.get_dependents("pump")
        dep_ids = [d.device_id for d in deps]
        assert "heater" in dep_ids
        assert "fan" in dep_ids
        assert "light" not in dep_ids

    def test_no_dependents(self, hass):
        """Device with no dependents returns empty list."""
        pump = _make_switch(hass, "pump", "Pump")
        controller = _make_controller(hass)
        controller.register_device(pump)

        assert controller.get_dependents("pump") == []


# ════════════════════════════════════════════
# Circular Detection
# ════════════════════════════════════════════

class TestCircularDetection:
    """Circular dependencies should be detected."""

    def test_no_circular(self, hass):
        """Linear chain has no circular dependencies."""
        a = _make_switch(hass, "a", "A")
        b = _make_switch(hass, "b", "B", depends_on=["a"])
        c = _make_switch(hass, "c", "C", depends_on=["b"])

        controller = _make_controller(hass)
        for d in [a, b, c]:
            controller.register_device(d)

        errors = controller.validate_dependencies()
        assert len(errors) == 0

    def test_direct_circular(self, hass):
        """A→B→A is circular."""
        a = _make_switch(hass, "a", "A", depends_on=["b"])
        b = _make_switch(hass, "b", "B", depends_on=["a"])

        controller = _make_controller(hass)
        controller.register_device(a)
        controller.register_device(b)

        errors = controller.validate_dependencies()
        assert len(errors) > 0
        assert "Circular" in errors[0]

    def test_indirect_circular(self, hass):
        """A→B→C→A is circular."""
        a = _make_switch(hass, "a", "A", depends_on=["c"])
        b = _make_switch(hass, "b", "B", depends_on=["a"])
        c = _make_switch(hass, "c", "C", depends_on=["b"])

        controller = _make_controller(hass)
        for d in [a, b, c]:
            controller.register_device(d)

        errors = controller.validate_dependencies()
        assert len(errors) > 0


# ════════════════════════════════════════════
# to_dict includes dependency info
# ════════════════════════════════════════════

class TestSerialization:
    """Dependency info appears in device serialization."""

    def test_to_dict_with_dependencies(self, hass):
        """to_dict includes depends_on and blocked_by."""
        pump = _make_switch(hass, "pump", "Pump")
        heater = _make_switch(hass, "heater", "Heater", depends_on=["pump"])

        controller = _make_controller(hass)
        controller.register_device(pump)
        controller.register_device(heater)

        d = heater.to_dict()
        assert d["depends_on"] == ["pump"]
        assert d["blocked_by"] == "pump"

    def test_to_dict_without_dependencies(self, hass):
        """to_dict omits dependency fields when not configured."""
        pump = _make_switch(hass, "pump", "Pump")
        controller = _make_controller(hass)
        controller.register_device(pump)

        d = pump.to_dict()
        assert "depends_on" not in d
