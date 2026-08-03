"""#594 — Vacation/Holiday mode.

While vacation is active (external ``vacation_mode_entity`` OR SEM's own
``switch.sem_vacation_mode``):

- HeatPumpController and HotWaterController receive NO comfort-driven
  activation (no SG-Ready boost/force-on, no climate setpoint boost, no
  DHW solar-target boost, no cheap-tariff off-peak forcing).
- Controllers that are ACTIVE when vacation starts are deactivated cleanly
  once (heat pump returns to SG-Ready NORMAL — never BLOCKED).
- Legionella cycles are PAUSED but ``hours_since_legionella`` keeps
  accumulating, so a cycle that falls due while away runs promptly on
  return (run-on-return).
- Opt-in ``vacation_dhw_surplus`` lets the boiler still soak up surplus,
  capped at ``min_temperature`` instead of the solar comfort target.
- EV / battery / load-priority devices are untouched.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import (
    SEMData, SurplusControlData,
)
from custom_components.solar_energy_management.devices.base import DeviceState
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController, SGReadyState,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)


def _hass(states=None):
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    states = states or {}
    h.states.get = MagicMock(
        side_effect=lambda eid: states.get(eid)
    )
    return h


def _state(value, attributes=None):
    s = MagicMock()
    s.state = str(value)
    s.attributes = attributes or {}
    return s


# ════════════════════════════════════════════════════════════════════
# Heat pump — vacation gates
# ════════════════════════════════════════════════════════════════════

class TestHeatPumpVacation:

    @pytest.mark.asyncio
    async def test_activate_blocked_during_vacation(self):
        hass = _hass()
        hp = HeatPumpController(
            hass=hass, rated_power=2000,
            relay1_entity_id="switch.r1", relay2_entity_id="switch.r2",
        )
        hp.vacation = True
        consumed = await hp.activate(6000)  # would be FORCE_ON otherwise
        assert consumed == 0.0
        assert hp._last_activation_path == "vacation_blocked"
        assert hp._status.state != DeviceState.ACTIVE
        # No relay writes — SEM did not touch the SG-Ready contacts.
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_activate_normal_when_vacation_off(self):
        """Regression guard: vacation off → behavior identical to before."""
        hass = _hass()
        hp = HeatPumpController(
            hass=hass, rated_power=2000,
            relay1_entity_id="switch.r1", relay2_entity_id="switch.r2",
        )
        assert hp.vacation is False  # default
        consumed = await hp.activate(3000)
        assert consumed == 2000
        assert hp._last_activation_path == "boost"
        assert hp._status.state == DeviceState.ACTIVE

    def test_offpeak_forcing_blocked_during_vacation(self):
        hp = HeatPumpController(
            hass=_hass(), relay1_entity_id="switch.r1",
            relay2_entity_id="switch.r2", daily_min_runtime_sec=3600,
        )
        hp.vacation = True
        assert hp.needs_offpeak_activation is False
        assert hp._last_offpeak_path == "vacation_blocked"

    @pytest.mark.asyncio
    async def test_vacation_deactivation_goes_to_normal_not_blocked(self):
        """SEM only stops encouraging — deactivate emits SG NORMAL (2),
        never the utility-block state 1."""
        hass = _hass()
        hp = HeatPumpController(
            hass=hass, relay1_entity_id="switch.r1",
            relay2_entity_id="switch.r2",
        )
        await hp.activate(3000)
        hp.vacation = True
        await hp.deactivate()
        assert hp._hp_status.sg_ready_state == SGReadyState.NORMAL
        assert hp._status.state == DeviceState.IDLE


# ════════════════════════════════════════════════════════════════════
# Hot water — vacation gates + optional surplus dump
# ════════════════════════════════════════════════════════════════════

def _boiler(hass, temp=45.0, dump=False, vacation=True, **kw):
    """A water_heater boiler with a separate temp sensor reading ``temp``."""
    states = {"sensor.tank_temp": _state(temp)}
    hass.states.get = MagicMock(side_effect=lambda eid: states.get(eid))
    hw = HotWaterController(
        hass=hass, entity_id="water_heater.dhw",
        temperature_entity_id="sensor.tank_temp",
        rated_power=2500, solar_target_temp=50.0, min_temperature=40.0,
        min_on_time=0, min_off_time=0, **kw,
    )
    hw.vacation = vacation
    hw.vacation_dhw_surplus = dump
    return hw


class TestHotWaterVacation:

    @pytest.mark.asyncio
    async def test_activate_blocked_during_vacation_dump_off(self):
        hass = _hass()
        hw = _boiler(hass, temp=35.0, dump=False)  # tank cold — would heat
        consumed = await hw.activate(3000)
        assert consumed == 0.0
        assert hw._last_activation_path == "vacation_blocked"
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_activate_normal_when_vacation_off(self):
        """Regression guard: vacation off → solar target as before."""
        hass = _hass()
        hw = _boiler(hass, temp=45.0, vacation=False)
        consumed = await hw.activate(3000)
        assert consumed == 2500
        # set_temperature was called with the SOLAR target (50), not min.
        temps = [
            c.args[2]["temperature"]
            for c in hass.services.async_call.call_args_list
            if c.args[1] == "set_temperature"
        ]
        assert temps == [50.0]

    @pytest.mark.asyncio
    async def test_vacation_dump_activates_at_minimum_target(self):
        """vacation_dhw_surplus=True → heats, but targets min_temperature."""
        hass = _hass()
        hw = _boiler(hass, temp=35.0, dump=True)  # below min → may dump
        consumed = await hw.activate(3000)
        assert consumed == 2500
        temps = [
            c.args[2]["temperature"]
            for c in hass.services.async_call.call_args_list
            if c.args[1] == "set_temperature"
        ]
        assert temps == [40.0], "surplus dump must target min, not solar"

    @pytest.mark.asyncio
    async def test_vacation_dump_capped_at_minimum(self):
        """At/above min temp the dump does NOT keep heating to solar target."""
        hass = _hass()
        hw = _boiler(hass, temp=41.0, dump=True)  # above min, below solar
        consumed = await hw.activate(3000)
        assert consumed == 0.0
        assert hw._last_activation_path == "blocked_unsafe"
        assert hw._last_temperature_safety_path == "vacation_at_min_target"

    def test_vacation_dump_temperature_safety_paths(self):
        hass = _hass()
        hw = _boiler(hass, temp=35.0, dump=True)
        assert hw.is_temperature_safe() is True
        assert hw._last_temperature_safety_path == "vacation_below_min_target"

    def test_offpeak_forcing_blocked_during_vacation(self):
        hass = _hass()
        hw = _boiler(hass, temp=35.0, dump=True, daily_min_runtime_sec=3600)
        assert hw.needs_offpeak_activation is False


# ════════════════════════════════════════════════════════════════════
# Legionella — paused during vacation, run-on-return
# ════════════════════════════════════════════════════════════════════

class TestLegionellaVacation:

    @pytest.mark.asyncio
    async def test_no_cycle_starts_during_vacation(self):
        hass = _hass()
        hw = _boiler(hass, temp=45.0, dump=False, legionella_interval_hours=72)
        hw.record_legionella_cycle(dt_util.now() - timedelta(hours=100))
        assert hw.legionella_overdue
        result = await hw.check_legionella_cycle()
        assert result == "legionella_vacation_paused"
        assert hw._legionella_cycle_active is False
        assert hw._last_legionella_path == "vacation_paused"
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_hours_keep_accumulating_during_vacation(self):
        """The pause must NOT reset/cap the timer — the interval keeps
        aging while away."""
        hass = _hass()
        hw = _boiler(hass, temp=45.0, legionella_interval_hours=72)
        stamp = dt_util.now() - timedelta(hours=100)
        hw.record_legionella_cycle(stamp)
        await hw.check_legionella_cycle()
        assert hw._last_legionella_time == stamp, "timer must not be touched"
        assert hw.hours_since_legionella > 72

    @pytest.mark.asyncio
    async def test_inflight_cycle_aborted_once(self):
        hass = _hass()
        hw = _boiler(hass, temp=55.0, legionella_interval_hours=72)
        hw._legionella_cycle_active = True
        hw._status.state = DeviceState.ACTIVE
        result = await hw.check_legionella_cycle()
        assert result == "legionella_vacation_paused"
        assert hw._legionella_cycle_active is False
        assert hw._legionella_hold_start is None
        assert hw._last_legionella_path == "vacation_aborted"
        # deactivate() went through the water_heater turn_off path
        assert any(
            c.args[1] == "turn_off"
            for c in hass.services.async_call.call_args_list
        )

    @pytest.mark.asyncio
    async def test_run_on_return(self):
        """Interval elapsed during vacation → cycle starts promptly on the
        first post-vacation check."""
        hass = _hass()
        hw = _boiler(hass, temp=45.0, legionella_interval_hours=72)
        hw.record_legionella_cycle(dt_util.now() - timedelta(hours=100))

        # While away: paused, nothing heats.
        assert await hw.check_legionella_cycle() == "legionella_vacation_paused"
        hass.services.async_call.assert_not_called()

        # Return home: vacation ends → the due cycle fires immediately.
        hw.vacation = False
        result = await hw.check_legionella_cycle()
        assert result == "legionella_started"
        assert hw._legionella_cycle_active is True
        assert hw._last_legionella_path == "overdue_start"
        # Forced activation targeted the legionella temperature.
        temps = [
            c.args[2]["temperature"]
            for c in hass.services.async_call.call_args_list
            if c.args[1] == "set_temperature"
        ]
        assert temps == [hw.legionella_target_temp]

    @pytest.mark.asyncio
    async def test_natural_achievement_still_recorded_during_vacation(self):
        """A tank that hit >=60°C anyway IS disinfected — record it even
        while on vacation."""
        hass = _hass()
        hw = _boiler(hass, temp=61.0, legionella_interval_hours=72)
        hw.record_legionella_cycle(dt_util.now() - timedelta(hours=100))
        result = await hw.check_legionella_cycle()
        assert result is None
        assert hw._last_legionella_path == "natural_achievement"
        assert hw.hours_since_legionella < 1

    @pytest.mark.asyncio
    async def test_regression_cycle_runs_normally_without_vacation(self):
        hass = _hass()
        hw = _boiler(hass, temp=45.0, vacation=False,
                     legionella_interval_hours=72)
        hw.record_legionella_cycle(dt_util.now() - timedelta(hours=100))
        result = await hw.check_legionella_cycle()
        assert result == "legionella_started"
        assert hw._legionella_cycle_active is True


# ════════════════════════════════════════════════════════════════════
# Coordinator — activation sources + apply/deactivate-once + publish
# ════════════════════════════════════════════════════════════════════

class _FakeCoordinator:
    """Stub carrying only what the vacation methods read; the methods under
    test are the REAL SEMCoordinator functions (bound via class attrs)."""

    _sync_vacation_mode_from_switch = SEMCoordinator._sync_vacation_mode_from_switch
    _compute_vacation_active = SEMCoordinator._compute_vacation_active
    _apply_vacation_mode = SEMCoordinator._apply_vacation_mode

    def __init__(self, hass, config=None, devices=None, observer=False):
        self.hass = hass
        self.config = config or {}
        self._vacation_switch_on = False
        self._vacation_active = False
        self._observer_mode = observer
        self._surplus_controller = SimpleNamespace(_devices=devices or {})


class TestVacationActivationSources:

    def _coord(self, states, config=None):
        return _FakeCoordinator(_hass(states), config=config)

    def test_own_switch_activates(self):
        c = self._coord({"switch.sem_vacation_mode": _state("on")})
        assert c._compute_vacation_active() is True

    def test_own_switch_off_and_no_entity_inactive(self):
        c = self._coord({"switch.sem_vacation_mode": _state("off")})
        assert c._compute_vacation_active() is False

    def test_switch_unavailable_holds_last_known(self):
        c = self._coord({"switch.sem_vacation_mode": _state("unavailable")})
        c._vacation_switch_on = True
        assert c._compute_vacation_active() is True, (
            "transient unavailability must not clobber the pushed value"
        )

    @pytest.mark.parametrize("entity", [
        "binary_sensor.away", "input_boolean.vacation",
        "switch.holiday", "calendar.vacations",
    ])
    def test_external_entity_on_activates(self, entity):
        c = self._coord(
            {entity: _state("on")},
            config={"vacation_mode_entity": entity},
        )
        assert c._compute_vacation_active() is True

    def test_calendar_no_ongoing_event_inactive(self):
        c = self._coord(
            {"calendar.vacations": _state("off")},
            config={"vacation_mode_entity": "calendar.vacations"},
        )
        assert c._compute_vacation_active() is False

    def test_external_entity_missing_inactive(self):
        c = self._coord(
            {}, config={"vacation_mode_entity": "binary_sensor.gone"},
        )
        assert c._compute_vacation_active() is False

    def test_either_source_suffices(self):
        # external off, own switch on → still active
        c = self._coord(
            {
                "binary_sensor.away": _state("off"),
                "switch.sem_vacation_mode": _state("on"),
            },
            config={"vacation_mode_entity": "binary_sensor.away"},
        )
        assert c._compute_vacation_active() is True


class TestApplyVacationMode:

    def _hp(self, hass):
        return HeatPumpController(
            hass=hass, relay1_entity_id="switch.r1",
            relay2_entity_id="switch.r2",
        )

    def _hw(self, hass, temp=35.0):
        states = {"sensor.tank_temp": _state(temp)}
        prev = hass.states.get.side_effect

        def _get(eid):
            if eid in states:
                return states[eid]
            return prev(eid) if prev else None

        hass.states.get = MagicMock(side_effect=_get)
        return HotWaterController(
            hass=hass, entity_id="switch.boiler",
            temperature_entity_id="sensor.tank_temp",
            min_on_time=0, min_off_time=0,
        )

    @pytest.mark.asyncio
    async def test_flags_set_and_active_controllers_deactivated(self):
        hass = _hass({"switch.sem_vacation_mode": _state("on")})
        hp, hw = self._hp(hass), self._hw(hass)
        await hp.activate(3000)
        await hw.activate(3000)
        assert hp.is_active and hw.is_active
        c = _FakeCoordinator(
            hass, devices={"heat_pump": hp, "hot_water": hw},
        )
        result = await c._apply_vacation_mode()
        assert result is True
        assert c._vacation_active is True
        assert hp.vacation is True and hw.vacation is True
        assert not hp.is_active, "active heat pump must be deactivated once"
        assert not hw.is_active, "active boiler must be deactivated once"
        assert hp._hp_status.sg_ready_state == SGReadyState.NORMAL

    @pytest.mark.asyncio
    async def test_dump_config_propagated_and_dump_survives_steady_state(self):
        hass = _hass({"switch.sem_vacation_mode": _state("on")})
        hw = self._hw(hass)
        c = _FakeCoordinator(
            hass, config={"vacation_dhw_surplus": True},
            devices={"hot_water": hw},
        )
        # Cycle 1 (rising edge): flags set.
        await c._apply_vacation_mode()
        assert hw.vacation_dhw_surplus is True
        # Boiler re-activates via the (gated) surplus path at min target.
        assert await hw.activate(3000) > 0
        # Cycle 2 (steady state): the dump is allowed to stay active.
        await c._apply_vacation_mode()
        assert hw.is_active, "surplus dump must not be re-deactivated"

    @pytest.mark.asyncio
    async def test_observer_mode_sets_flags_but_never_actuates(self):
        hass = _hass({"switch.sem_vacation_mode": _state("on")})
        hp = self._hp(hass)
        await hp.activate(3000)
        hass.services.async_call.reset_mock()
        c = _FakeCoordinator(
            hass, devices={"heat_pump": hp}, observer=True,
        )
        await c._apply_vacation_mode()
        assert hp.vacation is True
        assert hp.is_active, "observer mode must not actuate hardware"
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_vacation_off_regression_devices_untouched(self):
        hass = _hass({"switch.sem_vacation_mode": _state("off")})
        hp, hw = self._hp(hass), self._hw(hass)
        await hp.activate(3000)
        c = _FakeCoordinator(
            hass, devices={"heat_pump": hp, "hot_water": hw},
        )
        result = await c._apply_vacation_mode()
        assert result is False
        assert hp.vacation is False and hw.vacation is False
        assert hp.is_active, "vacation off → nothing deactivated"

    @pytest.mark.asyncio
    async def test_other_devices_untouched(self):
        """EV / battery / other surplus loads are not the vacation gate's
        business — only heat_pump + hot_water are touched."""
        hass = _hass({"switch.sem_vacation_mode": _state("on")})
        pool = MagicMock()
        pool.deactivate = AsyncMock()
        c = _FakeCoordinator(hass, devices={"pool_pump": pool})
        await c._apply_vacation_mode()
        pool.deactivate.assert_not_called()


class TestVacationPublished:

    def test_vacation_active_in_coordinator_data(self):
        d = SEMData().to_dict()
        assert d["vacation_active"] is False
        d2 = SEMData(
            surplus_control=SurplusControlData(vacation_active=True)
        ).to_dict()
        assert d2["vacation_active"] is True
