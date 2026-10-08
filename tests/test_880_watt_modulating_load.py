"""#880 — a surplus load whose control is a number entity gets the watts.

@jonasbkarlsson: "SEM correctly detects available/distributable PV surplus,
but never writes a value to the configured Number control entity. The
allocated surplus therefore remains at 0 W." Reproduced by the reporter on a
plain Home Assistant number helper, so no integration is implicated.

`SwitchDevice.activate(available_watts)` accepts the argument, documents it,
and discards it: it calls `homeassistant.turn_on` and reports `rated_power`.
Until now there was no class that writes a setpoint.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.power_setpoint import (
    PowerSetpointDevice,
)

ENTITY = "number.mypv_ac_thor_9s_power_ac9"


def _hass(current: float = 0.0, minimum: float | None = 0.0,
          maximum: float | None = 9000.0, step: float | None = 1.0):
    attrs = {}
    if minimum is not None:
        attrs["min"] = minimum
    if maximum is not None:
        attrs["max"] = maximum
    if step is not None:
        attrs["step"] = step
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=SimpleNamespace(
        state=str(current), attributes=attrs))
    hass.services.async_call = AsyncMock()
    return hass


def _device(hass, **kw):
    kw.setdefault("rated_power", 9000.0)
    return PowerSetpointDevice(
        hass=hass, device_id="ac_thor", name="AC-THOR 9s",
        entity_id=ENTITY, **kw)


def _payload(hass):
    """The service-call payload, whichever way `send` passed it."""
    call = hass.services.async_call.await_args
    if len(call.args) >= 3:
        return call.args[0], call.args[1], call.args[2]
    return call.args[0], call.args[1], call.kwargs.get("service_data", {})


@pytest.mark.unit
class TestItWritesTheWattsItWasGiven:

    @pytest.mark.asyncio
    async def test_activate_writes_the_allocation(self):
        hass = _hass()
        d = _device(hass)
        consumed = await d.activate(2500.0)
        hass.services.async_call.assert_awaited()
        domain, service, payload = _payload(hass)
        assert (domain, service) == ("number", "set_value")
        assert payload["entity_id"] == ENTITY
        assert payload["value"] == 2500.0
        assert consumed == 2500.0

    @pytest.mark.asyncio
    async def test_it_reports_the_setpoint_not_the_nameplate(self):
        """The bug's other half: a switch claims rated_power whatever it
        received, so the allocator's remaining-surplus sum was wrong even
        when the device did turn on."""
        hass = _hass()
        d = _device(hass)
        await d.activate(2500.0)
        assert d.status.current_consumption_w == 2500.0
        assert d.status.allocated_power_w == 2500.0
        assert d.rated_power == 9000.0            # nameplate unchanged


@pytest.mark.unit
class TestItFollowsTheSurplus:

    @pytest.mark.asyncio
    async def test_adjust_writes_the_new_allocation(self):
        hass = _hass()
        d = _device(hass)
        await d.activate(2500.0)
        hass.services.async_call.reset_mock()
        consumed = await d.adjust_power(1200.0)
        assert consumed == 1200.0
        assert _payload(hass)[2]["value"] == 1200.0

    @pytest.mark.asyncio
    async def test_adjust_does_nothing_when_not_running(self):
        hass = _hass()
        d = _device(hass)
        assert await d.adjust_power(1200.0) == 0.0
        hass.services.async_call.assert_not_awaited()


@pytest.mark.unit
class TestItRespectsTheEntitysOwnBounds:

    @pytest.mark.asyncio
    async def test_it_never_writes_above_the_entity_max(self):
        hass = _hass(maximum=3000.0)
        d = _device(hass)
        assert await d.activate(9000.0) == 3000.0

    @pytest.mark.asyncio
    async def test_it_quantises_to_the_entity_step(self):
        hass = _hass(step=100.0)
        d = _device(hass)
        assert await d.activate(2437.0) == 2400.0

    @pytest.mark.asyncio
    async def test_a_load_with_a_floor_stops_at_its_floor(self):
        """An AC-THOR's minimum is 0, but a load with a real floor must not
        be written below it — that is a value the hardware will refuse."""
        hass = _hass(minimum=500.0)
        d = _device(hass)
        await d.activate(2500.0)
        await d.deactivate()
        assert _payload(hass)[2]["value"] == 500.0
        assert d.status.current_consumption_w == 0.0

    @pytest.mark.asyncio
    async def test_an_entity_with_no_bounds_still_drives(self):
        """A template number need not declare min/max. Refusing to drive it
        would be worse than driving it between 0 and its nameplate."""
        hass = _hass(minimum=None, maximum=None, step=None)
        d = _device(hass)
        assert await d.activate(2500.0) == 2500.0

    @pytest.mark.asyncio
    async def test_a_nonsense_bound_is_ignored_not_fatal(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="0", attributes={"min": "nonsense", "max": None}))
        hass.services.async_call = AsyncMock()
        d = _device(hass)
        assert await d.activate(2500.0) == 2500.0


@pytest.mark.unit
class TestTheReportersCycle:
    """The AC-THOR 9s: min 0, max 9000, step 1, on a plain number helper."""

    @pytest.mark.asyncio
    async def test_surplus_arrives_rises_falls_and_ends(self):
        hass = _hass()
        d = _device(hass)
        assert await d.activate(1800.0) == 1800.0      # a cloud clears
        assert d.status.current_consumption_w == 1800.0
        assert await d.adjust_power(4200.0) == 4200.0  # midday
        assert await d.adjust_power(900.0) == 900.0    # cloud returns
        await d.deactivate()                            # sun gone
        assert d.status.current_consumption_w == 0.0
        assert _payload(hass)[2]["value"] == 0.0

    @pytest.mark.asyncio
    async def test_it_never_claims_the_nameplate(self):
        hass = _hass()
        d = _device(hass)
        await d.activate(1800.0)
        assert d.status.current_consumption_w == 1800.0
        assert d.status.current_consumption_w != d.rated_power


@pytest.mark.unit
class TestTheFactoryPicksIt:
    """The reporter configured 'Control type: Number entity' and got a
    SwitchDevice, which is why nothing was ever written."""

    def test_a_number_control_builds_a_setpoint_device(self):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        from custom_components.solar_energy_management.features.device_registry import (
            device_class_for_control,
        )
        assert device_class_for_control("number.ac_thor") is PowerSetpointDevice
        assert device_class_for_control("input_number.x") is PowerSetpointDevice
        assert device_class_for_control("switch.towel_heater") is SwitchDevice

    def test_no_entity_falls_back_to_the_switch(self):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        from custom_components.solar_energy_management.features.device_registry import (
            device_class_for_control,
        )
        assert device_class_for_control("") is SwitchDevice
        assert device_class_for_control(None) is SwitchDevice

    def test_both_classes_take_the_same_constructor(self):
        """The factory calls one or the other with identical keywords, so a
        signature drift would be a runtime TypeError on a real install."""
        import inspect

        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        shared = {"hass", "device_id", "name", "rated_power", "priority",
                  "entity_id", "power_entity_id", "energy_entity_id"}
        for cls in (SwitchDevice, PowerSetpointDevice):
            params = set(inspect.signature(cls.__init__).parameters)
            assert shared <= params, f"{cls.__name__} is missing {shared - params}"


@pytest.mark.unit
class TestTheDeclaredTypeIsAHint:
    """The second half of #880. Three writers declare `type: "switch"` for
    whatever entity the user picked, so the peak shedder called
    `switch.turn_off` on a number entity: no such service for that domain,
    nothing written, and the load ran straight through the peak event."""

    @pytest.mark.parametrize("control,expected", [
        ({"type": "switch", "entity": "number.ac_thor"}, "setpoint"),
        ({"type": "switch", "entity": "input_number.boiler_w"}, "setpoint"),
        ({"type": "switch", "entity": "switch.towel"}, "switch"),
        ({"type": "switch", "entity": "input_boolean.heater"}, "input_boolean"),
        # semantics the domain cannot express — left alone on purpose
        ({"type": "current", "entity": "number.keba_current"}, "current"),
        ({"type": "service", "service": "keba.set_current"}, "service"),
        ({"type": "surplus"}, "surplus"),
        ({"type": "none"}, "none"),
        (None, ""),
        ({}, ""),
    ])
    def test_it_resolves_against_the_entity(self, control, expected):
        from custom_components.solar_energy_management.features.load_management import (
            resolved_control_type,
        )
        assert resolved_control_type(control) == expected

    @pytest.mark.parametrize("attrs,floor", [
        ({"min": 0.0}, 0.0),
        ({"min": 500.0}, 500.0),      # cannot be driven below its own minimum
        ({}, 0.0),
        ({"min": "nonsense"}, 0.0),
        (None, 0.0),
    ])
    def test_the_shed_target_is_the_entitys_own_minimum(self, attrs, floor):
        from custom_components.solar_energy_management.features.load_management import (
            setpoint_floor,
        )
        assert setpoint_floor(attrs) == floor


def _lm(mock_hass, control, state="3200"):
    """A load manager holding one device with `control`."""
    from unittest.mock import patch

    from custom_components.solar_energy_management.load_management import (
        LoadManagementCoordinator,
    )
    entry = MagicMock()
    entry.options = {"load_management_enabled": True, "target_peak_limit": 5.0}
    entry.entry_id = "e"
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ), patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        MockStore.return_value = MagicMock(
            async_load=AsyncMock(return_value=None), async_save=AsyncMock())
        lm = LoadManagementCoordinator(mock_hass, entry)
    lm._observer_mode = False
    lm.hass.services.async_call = AsyncMock()
    lm.hass.states.get = MagicMock(return_value=SimpleNamespace(
        state=state, attributes={"min": 0.0, "max": 9000.0, "step": 1.0}))
    lm._devices["ac_thor"] = {
        "friendly_name": "AC-THOR", "power_entity": "sensor.ac_thor_power",
        "power_rating": 9000.0, "is_available": True, "priority": 5,
        "is_critical": False, "is_controllable": True,
        "device_type": "individual_device", "control_mode": "peak_only",
        "surplus_managed": False, "control": control,
    }
    return lm


@pytest.mark.unit
class TestThePeakShedderCanActuallyShedIt:

    @pytest.mark.asyncio
    async def test_it_writes_the_floor_instead_of_turning_a_switch_off(self, mock_hass):
        lm = _lm(mock_hass, {"type": "switch", "entity": ENTITY})
        assert await lm._shed_device("ac_thor", "WARNING") is True
        domain, service, data = lm.hass.services.async_call.await_args.args[:3]
        assert (domain, service) == ("number", "set_value")
        assert data == {"entity_id": ENTITY, "value": 0.0}
        assert "ac_thor" in lm._devices_shed

    @pytest.mark.asyncio
    async def test_an_input_number_is_written_in_its_own_domain(self, mock_hass):
        entity = "input_number.boiler_watts"
        lm = _lm(mock_hass, {"type": "switch", "entity": entity})
        assert await lm._shed_device("ac_thor", "WARNING") is True
        domain, service, _ = lm.hass.services.async_call.await_args.args[:3]
        assert (domain, service) == ("input_number", "set_value")

    @pytest.mark.asyncio
    async def test_restore_puts_back_the_users_own_number(self, mock_hass):
        lm = _lm(mock_hass, {"type": "switch", "entity": ENTITY}, state="3200")
        await lm._shed_device("ac_thor", "WARNING")
        assert lm._devices["ac_thor"]["_pre_shed_setpoint"] == 3200.0

        lm._last_shedding_time = None
        lm._can_restore_device = MagicMock(return_value=True)
        await lm._restore_device("ac_thor")
        domain, service, data = lm.hass.services.async_call.await_args.args[:3]
        assert (domain, service) == ("number", "set_value")
        assert data == {"entity_id": ENTITY, "value": 3200.0}
        assert "ac_thor" not in lm._devices_shed

    @pytest.mark.asyncio
    async def test_no_pre_shed_value_leaves_it_at_the_floor(self, mock_hass):
        """A guessed wattage is worse than the floor: whoever owns the load
        sets it on the next cycle. Restoring must still complete, or the
        device is stuck in `_devices_shed` forever."""
        lm = _lm(mock_hass, {"type": "switch", "entity": ENTITY})
        lm._devices_shed.append("ac_thor")
        lm._can_restore_device = MagicMock(return_value=True)
        await lm._restore_device("ac_thor")
        assert lm.hass.services.async_call.await_count == 0
        assert "ac_thor" not in lm._devices_shed

    @pytest.mark.asyncio
    async def test_an_ev_amp_knob_is_untouched_by_this(self, mock_hass):
        """`current` is also a number entity. It sheds AMPS and restores by
        handing the charger back to the EV planner — not our business."""
        entity = "number.keba_charging_current"
        lm = _lm(mock_hass, {"type": "current", "entity": entity}, state="16")
        await lm._shed_device("ac_thor", "WARNING")
        _d, _s, data = lm.hass.services.async_call.await_args.args[:3]
        assert data == {"entity_id": entity, "value": 0}
        assert lm._devices["ac_thor"]["_pre_shed_current"] == 16.0
        assert "_pre_shed_setpoint" not in lm._devices["ac_thor"]


def _sync_rig(control, unit="W"):
    """A registry holding one controllable load with `control`, ready to
    run the real `_sync_to_surplus_controller`."""
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry,
    )
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg._built_from_store = {}          # (#1067)
    reg.hass = MagicMock()
    st = MagicMock()
    st.state = "0"
    st.attributes = {"min": 0, "max": 9000, "step": 1}
    if unit is not None:
        st.attributes["unit_of_measurement"] = unit
    reg.hass.states.get.return_value = st
    reg._surplus_controller = MagicMock()
    reg._surplus_controller._devices = {}
    reg._load_manager = None
    reg._service_registrations = {}
    reg._dependency_overrides = {}
    reg._configured_charger_entities = MagicMock(return_value=set())
    reg._is_charger_duplicate = MagicMock(return_value=False)
    reg._initial_rated_power = MagicMock(return_value=9000.0)
    reg.control_mode_for = MagicMock(return_value="surplus")
    reg._apply_goals = MagicMock()

    device = MagicMock()
    device.device_id = "energy_dashboard_ac_thor"
    device.name = "AC-THOR 9s"
    device.priority = 1
    device.is_ev = False
    device.is_controllable = True
    device.power_sensor = "sensor.ac_thor_power"
    device.energy_sensor = "sensor.ac_thor_energy"
    device.control = control
    reg._devices = [device]
    return reg


@pytest.mark.unit
class TestTheSurplusSyncBuildsIt:
    """The pin that matters: the reporter's fix lives at ONE call site in
    `_sync_to_surplus_controller`, and testing the factory helper alone left
    that line free to be reverted with every test still green (bug class
    105 — a helper pinned, its caller not)."""

    def _registered(self, reg):
        reg._sync_to_surplus_controller()
        assert reg._surplus_controller.register_device.called, "nothing registered"
        return reg._surplus_controller.register_device.call_args.args[0]

    def test_a_number_control_declared_switch_still_becomes_a_setpoint(self):
        """Three writers declare `type: "switch"` for whatever entity the
        user picked — this is the shape @jonasbkarlsson's install had."""
        reg = _sync_rig({"type": "switch", "entity": ENTITY})
        assert isinstance(self._registered(reg), PowerSetpointDevice)

    def test_a_real_switch_is_still_a_switch(self):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        reg = _sync_rig({"type": "switch", "entity": "switch.towel_heater"})
        dev = self._registered(reg)
        assert isinstance(dev, SwitchDevice)
        assert not isinstance(dev, PowerSetpointDevice)

    def test_the_setpoint_device_carries_the_allocators_inputs(self):
        """A device the allocator cannot rate or read is registered but
        useless — these four are what `surplus_controller` asks of it."""
        reg = _sync_rig({"type": "switch", "entity": ENTITY})
        dev = self._registered(reg)
        assert dev.entity_id == ENTITY
        assert dev.rated_power == 9000.0
        assert dev.power_entity_id == "sensor.ac_thor_power"
        assert dev.priority == 1


@pytest.mark.unit
class TestTheBeliefFollowsTheNumber:
    """A restart leaves SEM believing the heater is idle while it draws
    3.2 kW. The allocator then offers those watts to something else — the
    #559 orphan, in the shape a setpoint takes."""

    def _dev(self, value, mode="surplus"):
        from custom_components.solar_energy_management.devices.base import (
            DeviceControlMode,
        )
        d = _device(_hass(current=value))
        d.control_mode = DeviceControlMode(mode)
        return d

    def test_a_running_setpoint_is_adopted_at_registration(self):
        d = self._dev(3200.0)
        assert d.adopt_if_running() is True
        assert d.is_active
        assert d._status.current_consumption_w == 3200.0
        assert d._sem_owned is True

    def test_at_its_floor_it_is_not_running(self):
        assert self._dev(0.0).adopt_if_running() is False

    def test_mode_off_adopts_the_belief_but_not_the_claim(self):
        """#779 — observing a number cannot answer 'did SEM set this?'."""
        d = self._dev(3200.0, mode="off")
        assert d.adopt_if_running() is True
        assert d.is_active
        assert d._sem_owned is False

    def test_an_unreadable_entity_adopts_nothing(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="unavailable", attributes={"min": 0, "max": 9000}))
        hass.services.async_call = AsyncMock()
        assert _device(hass).adopt_if_running() is False

    def test_someone_else_turning_it_up_is_seen_each_cycle(self):
        d = self._dev(0.0)
        assert d.sync_belief_to_observation() is False
        d.hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="4000", attributes={"min": 0, "max": 9000, "step": 1}))
        assert d.sync_belief_to_observation() is True
        assert d._status.current_consumption_w == 4000.0

    def test_someone_else_turning_it_down_releases_the_belief(self):
        d = self._dev(3200.0)
        d.adopt_if_running()
        d.hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="0", attributes={"min": 0, "max": 9000, "step": 1}))
        assert d.sync_belief_to_observation() is True
        assert not d.is_active
        assert d._sem_owned is False

    def test_a_kilowatt_entity_is_believed_in_watts(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="3.2", attributes={"min": 0, "max": 9, "step": 0.1,
                                     "unit_of_measurement": "kW"}))
        hass.services.async_call = AsyncMock()
        d = _device(hass)
        assert d.adopt_if_running() is True
        assert d._status.current_consumption_w == pytest.approx(3200.0)


@pytest.mark.unit
class TestEveryConstructionSite:
    """The first cut of #880 put the resolver in `device_registry` and a
    ruflo reviewer found a FOURTH factory that never called it —
    `surplus_device_from_spec`, which every service-registered device goes
    through at every restart. A helper whose purpose is "so the factory and
    the shed path cannot disagree" that one factory ignores is worse than
    none: it reads as covered."""

    def test_the_service_registration_factory_builds_a_setpoint(self):
        """`register_surplus_device` takes entity_id as a plain string —
        no domain validation — so an automation can and does pass a number."""
        from unittest.mock import MagicMock

        from custom_components.solar_energy_management.devices.base import (
            surplus_device_from_spec,
        )
        dev = surplus_device_from_spec(
            MagicMock(), "ac_thor",
            {"name": "AC-THOR", "entity_id": ENTITY, "device_type": "water_heater",
             "rated_power": 9000.0},
        )
        assert isinstance(dev, PowerSetpointDevice), (
            "a service-registered watt load got a SwitchDevice, which calls "
            "homeassistant.turn_on on a number entity: no such service, the "
            "error swallowed, the device parked in ERROR at 0 W — #880's "
            "reported symptom, on the path its first fix did not reach"
        )

    def test_that_factory_still_builds_switches_for_switches(self):
        from unittest.mock import MagicMock

        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice, surplus_device_from_spec,
        )
        dev = surplus_device_from_spec(
            MagicMock(), "towel",
            {"name": "Towel", "entity_id": "switch.towel", "rated_power": 500.0},
        )
        assert isinstance(dev, SwitchDevice)
        assert not isinstance(dev, PowerSetpointDevice)

    def test_the_resolver_has_exactly_one_home(self):
        """It must not be re-derived beside a factory that then forgets to
        call it — the shape that produced the missed site."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        defs = [
            p.relative_to(root).as_posix()
            for p in root.rglob("*.py")
            if "tests/" not in p.relative_to(root).as_posix()
            and re.search(r"^def device_class_for_control",
                          p.read_text(encoding="utf-8"), re.M)
        ]
        assert defs == ["devices/power_setpoint.py"], defs


@pytest.mark.unit
class TestTheFloorsEverySiblingApplies:
    """`_get_power_rating` returns 0 W for a load that is OFF right now —
    its own docstring says SwitchDevice turns that into the 1 kW default.
    Taking the 0 at face value made `min_power_threshold` zero, so the
    allocator 'activated' the heater into 0 W of surplus every cycle of a
    dark night, the belief never flipped ACTIVE, `calibrate_rated_power`
    could never run, and the reporter's symptom reproduced itself
    THROUGH the fix."""

    def test_an_unmeasured_rating_is_not_zero(self):
        d = _device(_hass(), rated_power=0.0)
        assert d.rated_power == 1000.0
        assert d.rated_power_measured is False

    def test_and_neither_is_the_activation_threshold(self):
        d = _device(_hass(), rated_power=0.0)
        assert d.min_power_threshold == 1000.0, (
            "the surplus walk activates when effective_surplus >= this; at "
            "0.0 that is true at midnight with no sun"
        )

    def test_a_measured_rating_is_kept_and_labelled(self):
        d = _device(_hass(), rated_power=9000.0)
        assert d.rated_power == 9000.0
        assert d.rated_power_measured is True

    def test_an_explicit_threshold_still_wins(self):
        d = _device(_hass(), rated_power=9000.0, min_power_threshold=250.0)
        assert d.min_power_threshold == 250.0


@pytest.mark.unit
class TestTheStopPathHasTheSameGate:
    """`deactivate` was the one method with no unit check — the way a 0
    lands on an ampere knob, which on OCPP persists as a 0 A profile (#976)."""

    @pytest.mark.asyncio
    async def test_it_refuses_an_entity_the_write_path_refuses(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="16", attributes={"min": 6, "max": 32,
                                    "unit_of_measurement": "A"}))
        hass.services.async_call = AsyncMock()
        d = PowerSetpointDevice(
            hass=hass, device_id="x", name="X", rated_power=9000.0,
            entity_id="number.keba_charging_current")
        await d.deactivate()
        assert hass.services.async_call.await_count == 0
