"""#745 — a device that is ON reads "Off" in the Device priority list.

Split from #744 (the sub-kW detection/formatting enhancement); this half is a
plain defect. Load-management's on/off for the CARD PAYLOAD
(``UnifiedDeviceRegistry.get_devices_for_sensor``) was inferred from POWER ALONE::

    current_power = float(state.state)
    is_on = current_power > 0

so a switch-controlled load whose own power sensor idles below its reporting
floor (a Shelly PM / a Powercalc-backed ``light.*`` drawing under a watt
publishes ``0 W``) rendered "Off" while ``switch.x`` / ``light.x`` said ``on``.

The control layer already reads the switch authoritatively
(``LoadDeviceDiscovery.get_device_current_state`` — used by load_management),
but the display payload had DIVERGED to a power-only copy: the two on/off
predicates drifted (BUG_CLASSES "Duplicated mechanism", display-vs-control
variant). The fix routes the payload through the shared, switch-aware
``resolve_load_is_on`` so the device's OWN control entity is authoritative, with
a power fallback only when there is no readable on/off entity.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
    UnifiedDevice,
)
from custom_components.solar_energy_management.features.load_device_discovery import (
    LoadDeviceDiscovery,
    resolve_load_is_on,
)


class _SurplusController:
    """Minimal SurplusController: no live devices, so ED rows keep their own
    power/on-off (no direct-registration row shadows them)."""

    _devices: dict = {}

    def get_device(self, did):
        return None


def _st(state):
    """A HA state stub carrying just what the read paths touch."""
    return SimpleNamespace(state=state, last_updated=None, attributes={})


def _reg(states):
    """A registry whose ``hass.states.get`` is backed by ``states`` (a dict of
    entity_id → state string; a missing key reads as no state)."""
    r = UnifiedDeviceRegistry(MagicMock(), _SurplusController(), MagicMock(),
                              MagicMock())
    r._has_battery = False
    r._devices = []
    r.hass.states.get = MagicMock(
        side_effect=lambda eid: _st(states[eid]) if eid in states else None)
    return r


def _ed(control_entity=None):
    """An Energy-Dashboard individual-device row with a discovered/mapped
    control entity (``switch.foo`` etc.), a power sensor, and a stable id."""
    ctrl = {"entity": control_entity} if control_entity else None
    return UnifiedDevice(
        energy_sensor="sensor.foo_energy",
        power_sensor="sensor.foo_power",
        name="Foo",
        priority=5,
        control=ctrl,
    )


def _is_on(states, control_entity="switch.foo"):
    dev = _ed(control_entity)
    reg = _reg(states)
    reg._devices = [dev]
    row = reg.get_devices_for_sensor()[dev.device_id]
    return row["is_on"]


@pytest.mark.unit
class TestCardPayloadPrefersSwitchState:
    """The exact defect: ``get_devices_for_sensor`` must report on/off from the
    device's own control entity, not from power alone."""

    def test_switch_on_power_below_floor_reads_on(self):
        # THE BUG (path 1). switch = on, sensor idling at 0 W below its floor.
        # Pre-fix: is_on = (0 > 0) = False → card showed "Off".
        assert _is_on({"switch.foo": "on", "sensor.foo_power": "0"}) is True

    def test_switch_on_tiny_draw_under_10w_reads_on(self):
        # THE BUG (path 2). Real draw, but under the card's own 10 W override —
        # only an authoritative is_on clears it.
        assert _is_on({"switch.foo": "on", "sensor.foo_power": "5"}) is True

    def test_switch_off_reads_off(self):
        assert _is_on({"switch.foo": "off", "sensor.foo_power": "0"}) is False

    def test_switch_off_wins_over_stray_power(self):
        # Prefer the device's OWN state: the switch says off, so it's off even
        # if the shared/mislabelled power sensor still reads a draw. Matches the
        # control layer (get_device_current_state), which trusts the switch.
        assert _is_on({"switch.foo": "off", "sensor.foo_power": "500"}) is False

    def test_light_control_on_at_zero_watts(self):
        # A Powercalc-backed light under a watt — the reporter's other path.
        assert _is_on({"light.foo": "on", "sensor.foo_power": "0"},
                      control_entity="light.foo") is True

    def test_input_boolean_control_on_at_zero_watts(self):
        assert _is_on({"input_boolean.foo": "on", "sensor.foo_power": "0"},
                      control_entity="input_boolean.foo") is True


@pytest.mark.unit
class TestFallsBackToPowerWhenNoReadableState:
    """No on/off-semantic control entity, or an unreadable one → power decides,
    so a device that is plainly drawing is never hidden."""

    def test_number_current_control_uses_power(self):
        # A ``number.*`` amperage control has no on/off state ("16.0"): fall
        # back to power rather than reading the number as off.
        assert _is_on({"number.foo_current": "16.0", "sensor.foo_power": "20"},
                      control_entity="number.foo_current") is True
        assert _is_on({"number.foo_current": "16.0", "sensor.foo_power": "0"},
                      control_entity="number.foo_current") is False

    def test_service_control_uses_power(self):
        # An integration service control (control.service, e.g. keba.set_current)
        # is not an entity with a state → power decides.
        assert _is_on({"sensor.foo_power": "20"},
                      control_entity="keba.set_current") is True

    def test_unavailable_switch_falls_back_to_power(self):
        # A switch offline while the load plainly draws must NOT read Off (that
        # would re-hide the drawing device). This is where the display predicate
        # is intentionally more lenient than the control one.
        assert _is_on({"switch.foo": "unavailable", "sensor.foo_power": "2000"}) is True
        assert _is_on({"switch.foo": "unknown", "sensor.foo_power": "0"}) is False

    def test_no_control_entity_uses_power(self):
        assert _is_on({"sensor.foo_power": "30"}, control_entity=None) is True
        assert _is_on({"sensor.foo_power": "0"}, control_entity=None) is False


@pytest.mark.unit
class TestResolveLoadIsOnHelper:
    """Direct unit coverage of the shared predicate — pins the behaviour the
    payload delegates to, so it can't be gutted without a red test."""

    def test_prefers_on_domain_state_over_power(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=_st("on"))
        assert resolve_load_is_on(hass, "switch.x", 0.0) is True
        hass.states.get = MagicMock(return_value=_st("off"))
        assert resolve_load_is_on(hass, "switch.x", 999.0) is False

    def test_power_fallback_shapes(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        # no entity → power
        assert resolve_load_is_on(hass, None, 5.0) is True
        assert resolve_load_is_on(hass, None, 0.0) is False
        # non-onoff domain → power (state ignored)
        hass.states.get = MagicMock(return_value=_st("16.0"))
        assert resolve_load_is_on(hass, "number.x", 5.0) is True
        assert resolve_load_is_on(hass, "number.x", 0.0) is False

    @pytest.mark.parametrize("value,expected", [
        ("on", True), ("ON", True), ("true", True), ("1", True),
        (" on ", True), ("off", False), ("unavailable", False),
        ("unknown", False),
    ])
    def test_state_string_mapping(self, value, expected):
        # unavailable/unknown map to the power fallback (0 here) → False.
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=_st(value))
        assert resolve_load_is_on(hass, "switch.x", 0.0) is expected


@pytest.mark.unit
class TestDisplayAgreesWithControlOnReadableSwitch:
    """The display predicate and the control predicate
    (get_device_current_state) must not drift on the case that matters — a
    readable switch. Pin that they return the same on/off there."""

    def _control_is_on(self, states, switch, power):
        disc = object.__new__(LoadDeviceDiscovery)  # skip entity-registry setup
        disc.hass = MagicMock()
        disc.hass.states.get = MagicMock(
            side_effect=lambda eid: _st(states[eid]) if eid in states else None)
        return disc.get_device_current_state(
            {"switch_entity": switch, "power_entity": power})["is_on"]

    @pytest.mark.parametrize("switch_state,power", [
        ("on", "0"), ("on", "5"), ("off", "0"), ("off", "500"),
    ])
    def test_same_verdict_for_readable_switch(self, switch_state, power):
        states = {"switch.foo": switch_state, "sensor.foo_power": power}
        display = resolve_load_is_on(
            _reg(states).hass, "switch.foo",
            float(power))
        control = self._control_is_on(states, "switch.foo", "sensor.foo_power")
        assert display is control
