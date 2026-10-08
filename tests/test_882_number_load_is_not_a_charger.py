"""#882 — a watt-native load must not be registered as an EV charger.

@florianhadersbeck, 31.08, on 2.0.0 with no EV charger: a my-PV AC-THOR 9s
water heater configured as a variable surplus load, and SEM never wrote it a
setpoint. He ruled his own integration out by reproducing with a plain Home
Assistant Number Helper, and confirmed a manual ``number.set_value`` works.

His diagnostics line names the fault:

    SEM 2.0.0 | Grid: combined | Chargers: 1 (number) | Battery: 4.5kWh

**His water heater is counted as an EV charger.** ``control_type == "current"``
maps a load onto ``CurrentControlDevice`` — the charger class, which thinks in
AMPERES and defaults to ``min 6 / max 32`` — pointed at an entity whose range
is 0–9000 **watts**. Nothing sensible could ever have been written, and
nothing was: no error, no log, ``Allocated surplus: 0 W`` forever.

The missing capability (a watt-modulating device class) was an ENHANCEMENT,
#880 — SEM was never designed for it. This was the narrower defect: SEM offers
that control type in a picker and silently produces something inert. #799's
rule is that a silent no-op is not an answer.

**Superseded in part by #880.** The class exists now, so a power entity under
"current" control is no longer refused with a repair — it is ROUTED to
``PowerSetpointDevice``, which writes watts. What #882 established and what
still holds is the invariant below: a 0-9000 W entity is never driven as a
6-32 A charger. The repair is cleared on the same path, because the user's
configuration now works as they meant it.

SEM already knows how to ask "is this entity a power setpoint?" —
``native_power_scale`` in ``coordinator/power_control.py``, built generic for
#749. One rule, reused, rather than a second and laxer one.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _registry(entity_unit):
    """A registry with one 'current'-controlled load whose entity carries
    ``entity_unit`` as its unit_of_measurement."""
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry,
    )
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg._built_from_store = {}          # (#1067)
    hass = MagicMock()
    st = MagicMock()
    st.state = "0"
    st.attributes = {"unit_of_measurement": entity_unit,
                     "min": 0, "max": 9000, "step": 1}
    hass.states.get.return_value = st
    reg.hass = hass
    reg._surplus_controller = MagicMock()
    reg._surplus_controller.register_device = MagicMock()
    reg._load_manager = None
    reg._initial_rated_power = MagicMock(return_value=9000.0)
    return reg


def _device():
    d = MagicMock()
    d.device_id = "energy_dashboard_ac_thor"
    d.name = "AC-THOR 9s"
    d.priority = 1
    d.power_sensor = "sensor.ac_thor_power"
    return d


def _register(reg, unit):
    """Drive the one branch under test with a control dict."""
    control = {"type": "current", "entity": "number.mypv_ac_thor_9s_power_ac9",
               "min_value": 0, "max_value": 9000}
    reg._register_current_control(_device(), control)


class TestAWattNativeEntityIsNeverACharger:
    def _registered(self, reg):
        assert reg._surplus_controller.register_device.called
        return reg._surplus_controller.register_device.call_args.args[0]

    def test_it_is_not_registered_as_a_charger(self):
        from custom_components.solar_energy_management.devices.base import (
            CurrentControlDevice,
        )
        reg = _registry("W")
        _register(reg, "W")
        assert not isinstance(self._registered(reg), CurrentControlDevice), (
            "a 0-9000 W water heater was registered as a 6-32 A EV charger — "
            "it shows up in diagnostics as 'Chargers: 1' and can never be "
            "written a value that means anything"
        )

    def test_it_is_driven_as_a_watt_setpoint_instead(self):
        """(#880) The capability #882 was missing. His configuration was
        never wrong about the ENTITY — only about the class behind it."""
        from custom_components.solar_energy_management.devices.power_setpoint import (
            PowerSetpointDevice,
        )
        reg = _registry("W")
        _register(reg, "W")
        dev = self._registered(reg)
        assert isinstance(dev, PowerSetpointDevice)
        assert dev.entity_id == "number.mypv_ac_thor_9s_power_ac9"

    def test_a_kilowatt_entity_takes_the_same_route(self):
        from custom_components.solar_energy_management.devices.power_setpoint import (
            PowerSetpointDevice,
        )
        reg = _registry("kW")
        _register(reg, "kW")
        assert isinstance(self._registered(reg), PowerSetpointDevice)

    def test_the_repair_is_cleared_because_it_now_works(self):
        """#799 — a silent no-op is not an answer, and neither is a standing
        repair for something SEM has since learned to do."""
        reg = _registry("W")
        with patch(
            "custom_components.solar_energy_management.coordinator.repair_issues"
            ".clear_load_current_control_wrong_unit"
        ) as m:
            _register(reg, "W")
        assert m.called, "the repair outlived the defect it described"


class TestGenuineCurrentControlIsUntouched:
    """Today's behaviour for real amp-controlled devices must be preserved
    exactly — this refuses power entities, not current control."""

    def test_an_ampere_entity_still_registers(self):
        reg = _registry("A")
        _register(reg, "A")
        assert reg._surplus_controller.register_device.called

    def test_an_entity_with_no_unit_still_registers(self):
        """Plenty of charger integrations publish a bare number. Refusing
        those would break working installs to fix a different fault."""
        reg = _registry(None)
        _register(reg, None)
        assert reg._surplus_controller.register_device.called

    def test_an_unreadable_entity_still_registers(self):
        """Unavailable at setup is not evidence of the wrong unit, and a
        device that vanishes for a cycle must not be de-registered."""
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._built_from_store = {}          # (#1067)
        hass = MagicMock()
        hass.states.get.return_value = None
        reg.hass = hass
        reg._surplus_controller = MagicMock()
        reg._load_manager = None
        _register(reg, None)
        assert reg._surplus_controller.register_device.called


class TestTheRepairFollowsTheMapping:
    """The repair says "cleared once the device is reconfigured" — and on
    the 02.09 live proof it was not. ``remove_device_control_mapping``
    put the towel heater back on its switch, and the persistent repair for
    the watt entity it no longer pointed at stayed. The clear lived inside
    the current-control branch only, so every other way of reconfiguring
    the device — removing the mapping, mapping it as a switch, taking it
    out of SEM's hands — never reached it."""

    def _sync_registry(self, device):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._built_from_store = {}          # (#1067)
        reg.hass = MagicMock()
        reg._surplus_controller = MagicMock()
        reg._surplus_controller._devices = {}
        reg._load_manager = None
        reg._devices = [device]
        reg._service_registrations = {}
        reg._dependency_overrides = {}
        reg._configured_charger_entities = MagicMock(return_value=set())
        reg._is_charger_duplicate = MagicMock(return_value=False)
        reg._initial_rated_power = MagicMock(return_value=1144.0)
        reg.control_mode_for = MagicMock(return_value="off")
        reg._apply_goals = MagicMock()
        return reg

    def _load(self, control, controllable=True):
        d = _device()
        d.is_ev = False
        d.is_controllable = controllable
        d.control = control
        d.energy_sensor = "sensor.ac_thor_energy"
        return d

    def test_mapping_removed_clears_the_repair(self):
        """Back on its discovered switch → the watt repair is gone."""
        d = self._load({"type": "switch", "entity": "switch.ac_thor"})
        reg = self._sync_registry(d)
        with patch(
            # (#880) the registry no longer names a class here — it asks
            # ``device_class_for_control`` which one the entity needs.
            "custom_components.solar_energy_management.features.device_registry"
            ".device_class_for_control"
        ), patch(
            "custom_components.solar_energy_management.coordinator.repair_issues"
            ".clear_load_current_control_wrong_unit"
        ) as clear:
            reg._sync_to_surplus_controller()
        assert clear.called, (
            "the device is a switch load again and the repair still says its "
            "watt entity is under current control"
        )
        assert clear.call_args.args[1] == "energy_dashboard_ac_thor"

    def test_taken_out_of_sems_hands_clears_the_repair(self):
        """'Controllable' switched off is a reconfiguration too — SEM will
        never write that entity, so there is nothing to repair."""
        d = self._load({"type": "current", "entity": "number.ac_thor"},
                       controllable=False)
        reg = self._sync_registry(d)
        with patch(
            "custom_components.solar_energy_management.coordinator.repair_issues"
            ".clear_load_current_control_wrong_unit"
        ) as clear:
            reg._sync_to_surplus_controller()
        assert clear.called

    def test_a_watt_mapping_clears_its_repair_and_runs(self):
        """(#880) The mapping that used to be unfixable now works, so the
        repair must go — a standing repair for a working device is the same
        silent lie in the other direction."""
        from custom_components.solar_energy_management.devices.power_setpoint import (
            PowerSetpointDevice,
        )
        d = self._load({"type": "current", "entity": "number.ac_thor",
                        "min_value": 0, "max_value": 9000})
        reg = self._sync_registry(d)
        st = MagicMock(); st.state = "0"
        st.attributes = {"unit_of_measurement": "W", "min": 0, "max": 9000}
        reg.hass.states.get.return_value = st
        with patch(
            "custom_components.solar_energy_management.coordinator.repair_issues"
            ".clear_load_current_control_wrong_unit"
        ) as clear:
            reg._sync_to_surplus_controller()
        assert clear.called
        registered = reg._surplus_controller.register_device.call_args.args[0]
        assert isinstance(registered, PowerSetpointDevice)
