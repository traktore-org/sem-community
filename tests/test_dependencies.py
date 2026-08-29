"""Tests for appliance dependency system (#122).

Tests activation gate, deactivation cascade, circular detection,
and multi-level dependency chains.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, DeviceState,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)


def _make_switch(mock_hass, device_id, name, priority=5, depends_on=None):
    """Create a mock switch device."""
    device = SwitchDevice(
        hass=mock_hass, device_id=device_id, name=name,
        priority=priority, entity_id=f"switch.{device_id}",
        power_entity_id=f"sensor.{device_id}_power",
        rated_power=1000,
    )
    if depends_on:
        device.depends_on = depends_on
    return device


def _make_controller(mock_hass):
    """Create a surplus controller."""
    controller = SurplusController(mock_hass, {})
    return controller


@pytest.fixture
def mock_hass():
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

    def test_no_dependencies_can_activate(self, mock_hass):
        """Device without dependencies can always activate."""
        device = _make_switch(mock_hass, "heater", "Heater")
        controller = _make_controller(mock_hass)
        controller.register_device(device)
        assert device.can_activate() is True

    def test_blocked_when_dependency_inactive(self, mock_hass):
        """Device blocked when depends_on device is not active."""
        pump = _make_switch(mock_hass, "pump", "Pool Pump", priority=1)
        heater = _make_switch(mock_hass, "heater", "Pool Heater", priority=2, depends_on=["pump"])

        controller = _make_controller(mock_hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Pump is idle — heater should be blocked
        assert heater.can_activate() is False
        assert heater.blocked_by_dependency == "pump"

    def test_allowed_when_dependency_active(self, mock_hass):
        """Device can activate when depends_on device is active."""
        pump = _make_switch(mock_hass, "pump", "Pool Pump", priority=1)
        heater = _make_switch(mock_hass, "heater", "Pool Heater", priority=2, depends_on=["pump"])

        controller = _make_controller(mock_hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Activate pump
        pump._status.state = DeviceState.ACTIVE

        assert heater.can_activate() is True
        assert heater.blocked_by_dependency is None

    def test_must_inactive_mode(self, mock_hass):
        """Device with must_inactive blocks when dependency IS active."""
        main = _make_switch(mock_hass, "main", "Main Heater", priority=1)
        backup = _make_switch(mock_hass, "backup", "Backup Heater", priority=2, depends_on=["main"])
        backup.dependency_mode = "must_inactive"

        controller = _make_controller(mock_hass)
        controller.register_device(main)
        controller.register_device(backup)

        # Main is active — backup should be blocked
        main._status.state = DeviceState.ACTIVE
        assert backup.can_activate() is False

        # Main is idle — backup can activate
        main._status.state = DeviceState.IDLE
        assert backup.can_activate() is True

    def test_multiple_dependencies(self, mock_hass):
        """Device with multiple dependencies needs ALL satisfied."""
        pump = _make_switch(mock_hass, "pump", "Pump", priority=1)
        valve = _make_switch(mock_hass, "valve", "Valve", priority=2)
        heater = _make_switch(mock_hass, "heater", "Heater", priority=3, depends_on=["pump", "valve"])

        controller = _make_controller(mock_hass)
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

    def test_get_dependents(self, mock_hass):
        """get_dependents returns all devices that depend on given ID."""
        pump = _make_switch(mock_hass, "pump", "Pump")
        heater = _make_switch(mock_hass, "heater", "Heater", depends_on=["pump"])
        fan = _make_switch(mock_hass, "fan", "Fan", depends_on=["pump"])
        light = _make_switch(mock_hass, "light", "Light")  # No dependency

        controller = _make_controller(mock_hass)
        for d in [pump, heater, fan, light]:
            controller.register_device(d)

        deps = controller.get_dependents("pump")
        dep_ids = [d.device_id for d in deps]
        assert "heater" in dep_ids
        assert "fan" in dep_ids
        assert "light" not in dep_ids

    def test_no_dependents(self, mock_hass):
        """Device with no dependents returns empty list."""
        pump = _make_switch(mock_hass, "pump", "Pump")
        controller = _make_controller(mock_hass)
        controller.register_device(pump)

        assert controller.get_dependents("pump") == []


# ════════════════════════════════════════════
# Circular Detection
# ════════════════════════════════════════════

class TestCircularDetection:
    """Circular dependencies are PREVENTED at the write path (#662).

    This class used to call ``SurplusController.validate_dependencies``.
    That method is deleted: it had no production caller (so no install
    ever saw its report, clean or otherwise) and its walk hard-coded
    ``dep_list[0]`` — a device requiring ``[a, b]`` with the loop through
    ``b`` was reported clean. These tests were green against it the whole
    time because they only ever built single-parent graphs: the one shape
    the ``[0]``-walk could see.

    Detection-after-the-fact is now prevention-at-the-write.
    ``DeviceRegistry._dependency_would_cycle`` walks ALL parents across
    both persisted stores and rejects the edge; its tests are
    ``tests/test_576_load_priority_battery.py::TestDependencyGraphGuards``
    plus the #662 additions there.
    """

    def test_validator_stays_deleted(self):
        """The half-blind orphan must not come back.

        Re-adding a ``validate_dependencies`` report means re-adding a
        second implementation of a concept the registry already owns —
        and, on past form, one nothing calls.
        """
        assert not hasattr(SurplusController, "validate_dependencies"), (
            "SurplusController.validate_dependencies was deleted in #662 "
            "(no production caller + dep_list[0]-only walk). Cycles are "
            "rejected by DeviceRegistry._dependency_would_cycle at the "
            "write path. Do not reintroduce a reporting-only validator."
        )

    def test_runtime_gate_walks_all_deps_not_just_the_first(self, mock_hass):
        """The runtime gate has no ``[0]``-walk twin.

        This is the sibling that would have made the bug user-visible, so
        pin it: a device requiring two parents stays blocked while EITHER
        is inactive — i.e. the second dependency is really consulted.
        """
        a = _make_switch(mock_hass, "a", "A")
        b = _make_switch(mock_hass, "b", "B")
        c = _make_switch(mock_hass, "c", "C", depends_on=["a", "b"])

        controller = _make_controller(mock_hass)
        for d in [a, b, c]:
            controller.register_device(d)

        a._status.state = DeviceState.ACTIVE
        assert c.can_activate() is False, (
            "second dependency ignored — a [0]-only walk would pass here"
        )
        b._status.state = DeviceState.ACTIVE
        assert c.can_activate() is True


# ════════════════════════════════════════════
# to_dict includes dependency info
# ════════════════════════════════════════════

class TestSerialization:
    """Dependency info appears in device serialization."""

    def test_to_dict_with_dependencies(self, mock_hass):
        """to_dict includes depends_on and blocked_by."""
        pump = _make_switch(mock_hass, "pump", "Pump")
        heater = _make_switch(mock_hass, "heater", "Heater", depends_on=["pump"])

        controller = _make_controller(mock_hass)
        controller.register_device(pump)
        controller.register_device(heater)

        d = heater.to_dict()
        assert d["depends_on"] == ["pump"]
        assert d["blocked_by"] == "pump"

    def test_to_dict_without_dependencies(self, mock_hass):
        """to_dict omits dependency fields when not configured."""
        pump = _make_switch(mock_hass, "pump", "Pump")
        controller = _make_controller(mock_hass)
        controller.register_device(pump)

        d = pump.to_dict()
        assert "depends_on" not in d


# ════════════════════════════════════════════
# Dependency lifecycle (set, release, reorder)
# ════════════════════════════════════════════

class TestDependencyLifecycle:
    """Test setting and releasing dependencies at runtime."""

    def test_set_dependency_runtime(self, mock_hass):
        """Setting depends_on at runtime blocks activation."""
        pump = _make_switch(mock_hass, "pump", "Pump", priority=1)
        heater = _make_switch(mock_hass, "heater", "Heater", priority=2)

        controller = _make_controller(mock_hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Initially no dependency — heater can activate
        assert heater.can_activate() is True

        # Set dependency at runtime
        heater.depends_on = ["pump"]
        assert heater.can_activate() is False

        # Activate pump — heater unblocked
        pump._status.state = DeviceState.ACTIVE
        assert heater.can_activate() is True

    def test_release_dependency(self, mock_hass):
        """Clearing depends_on releases the device."""
        pump = _make_switch(mock_hass, "pump", "Pump", priority=1)
        heater = _make_switch(mock_hass, "heater", "Heater", priority=2, depends_on=["pump"])

        controller = _make_controller(mock_hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Blocked
        assert heater.can_activate() is False

        # Release
        heater.depends_on = []
        assert heater.can_activate() is True
        assert heater.blocked_by_dependency is None

    def test_unknown_dependency_does_not_block(self, mock_hass):
        """Depending on a non-existent device does not block."""
        heater = _make_switch(mock_hass, "heater", "Heater", depends_on=["nonexistent"])

        controller = _make_controller(mock_hass)
        controller.register_device(heater)

        # Unknown device — don't block
        assert heater.can_activate() is True

    def test_parent_below_child_priority(self, mock_hass):
        """Even if parent has lower priority (higher number), dependency still works."""
        pump = _make_switch(mock_hass, "pump", "Pump", priority=5)
        heater = _make_switch(mock_hass, "heater", "Heater", priority=1, depends_on=["pump"])

        controller = _make_controller(mock_hass)
        controller.register_device(pump)
        controller.register_device(heater)

        # Heater has higher priority but depends on pump
        assert heater.can_activate() is False

        pump._status.state = DeviceState.ACTIVE
        assert heater.can_activate() is True

    def test_chain_dependency(self, mock_hass):
        """A→B→C: C can only activate when both A and B are active."""
        a = _make_switch(mock_hass, "a", "A", priority=1)
        b = _make_switch(mock_hass, "b", "B", priority=2, depends_on=["a"])
        c = _make_switch(mock_hass, "c", "C", priority=3, depends_on=["b"])

        controller = _make_controller(mock_hass)
        for d in [a, b, c]:
            controller.register_device(d)

        # Nothing active
        assert c.can_activate() is False
        assert b.can_activate() is False

        # Only A active — B can activate, C still blocked
        a._status.state = DeviceState.ACTIVE
        assert b.can_activate() is True
        assert c.can_activate() is False

        # A + B active — C can activate
        b._status.state = DeviceState.ACTIVE
        assert c.can_activate() is True


# ════════════════════════════════════════════
# Sibling + cascade + edge cases
# ════════════════════════════════════════════

class TestSiblingDependencies:
    """B and C both depend on A — independent of each other."""

    def test_siblings_both_blocked(self, mock_hass):
        """Both siblings blocked when parent inactive."""
        parent = _make_switch(mock_hass, "hp", "Heat Pump", priority=1)
        circ = _make_switch(mock_hass, "circ", "Circulation", priority=2, depends_on=["hp"])
        valve = _make_switch(mock_hass, "valve", "Valve", priority=3, depends_on=["hp"])

        controller = _make_controller(mock_hass)
        for d in [parent, circ, valve]:
            controller.register_device(d)

        assert circ.can_activate() is False
        assert valve.can_activate() is False

    def test_siblings_both_unblocked(self, mock_hass):
        """Both siblings can activate when parent active."""
        parent = _make_switch(mock_hass, "hp", "Heat Pump", priority=1)
        circ = _make_switch(mock_hass, "circ", "Circulation", priority=2, depends_on=["hp"])
        valve = _make_switch(mock_hass, "valve", "Valve", priority=3, depends_on=["hp"])

        controller = _make_controller(mock_hass)
        for d in [parent, circ, valve]:
            controller.register_device(d)

        parent._status.state = DeviceState.ACTIVE
        assert circ.can_activate() is True
        assert valve.can_activate() is True

    def test_sibling_independence(self, mock_hass):
        """Deactivating one sibling doesn't affect the other."""
        parent = _make_switch(mock_hass, "hp", "Heat Pump", priority=1)
        circ = _make_switch(mock_hass, "circ", "Circulation", priority=2, depends_on=["hp"])
        valve = _make_switch(mock_hass, "valve", "Valve", priority=3, depends_on=["hp"])

        controller = _make_controller(mock_hass)
        for d in [parent, circ, valve]:
            controller.register_device(d)

        parent._status.state = DeviceState.ACTIVE
        circ._status.state = DeviceState.ACTIVE
        valve._status.state = DeviceState.ACTIVE

        # Deactivate circ — valve stays active (independent)
        circ._status.state = DeviceState.IDLE
        assert valve.can_activate() is True

    def test_get_dependents_siblings(self, mock_hass):
        """get_dependents returns all siblings."""
        parent = _make_switch(mock_hass, "hp", "Heat Pump")
        circ = _make_switch(mock_hass, "circ", "Circulation", depends_on=["hp"])
        valve = _make_switch(mock_hass, "valve", "Valve", depends_on=["hp"])
        other = _make_switch(mock_hass, "other", "Other")

        controller = _make_controller(mock_hass)
        for d in [parent, circ, valve, other]:
            controller.register_device(d)

        deps = controller.get_dependents("hp")
        dep_ids = [d.device_id for d in deps]
        assert len(dep_ids) == 2
        assert "circ" in dep_ids
        assert "valve" in dep_ids
        assert "other" not in dep_ids


class TestEdgeCases:
    """Edge cases that should be handled gracefully."""

    def test_self_dependency_deadlocks_at_runtime(self, mock_hass):
        """A self-requiring device can never start — which is why the
        write path refuses to create one (#662).

        The old assertion here read ``validate_dependencies() > 0``: it
        checked that a report *nothing consumed* mentioned the problem,
        while the device sat deadlocked either way. Pin the consequence
        instead — this is what the write-path guard exists to prevent.
        """
        device = _make_switch(mock_hass, "a", "A", depends_on=["a"])
        controller = _make_controller(mock_hass)
        controller.register_device(device)

        # It waits on itself to be ACTIVE before it may become ACTIVE.
        assert device.can_activate() is False
        assert device.blocked_by_dependency == "a"

    def test_remove_parent_unblocks_child(self, mock_hass):
        """Unregistering parent should not crash children."""
        parent = _make_switch(mock_hass, "pump", "Pump")
        child = _make_switch(mock_hass, "heater", "Heater", depends_on=["pump"])

        controller = _make_controller(mock_hass)
        controller.register_device(parent)
        controller.register_device(child)

        assert child.can_activate() is False

        # Remove parent
        controller.unregister_device("pump")

        # Child should now be able to activate (unknown dep = don't block)
        assert child.can_activate() is True

    def test_empty_depends_on(self, mock_hass):
        """Empty depends_on list should not block."""
        device = _make_switch(mock_hass, "a", "A")
        device.depends_on = []

        controller = _make_controller(mock_hass)
        controller.register_device(device)

        assert device.can_activate() is True
        assert device.blocked_by_dependency is None

    def test_dependency_with_no_controller(self, mock_hass):
        """Device with depends_on but no controller reference."""
        device = _make_switch(mock_hass, "a", "A", depends_on=["b"])
        # Don't register — no controller reference
        assert device.can_activate() is True  # No controller = can't check = allow
