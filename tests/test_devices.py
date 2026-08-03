"""Tests for device classes in devices/ module."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.devices.base import (
    ClimateDevice,
    ControllableDevice,
    CurrentControlDevice,
    DeviceState,
    DeviceType,
    ScheduleDevice,
    SetpointDevice,
    SwitchDevice,
    surplus_device_from_spec,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
    SG_READY_RELAY_MAP,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.devices.appliance_scheduler import (
    ApplianceScheduler,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def mock_hass():
    """Return a mocked Home Assistant instance."""
    h = MagicMock()
    h.config = MagicMock()
    h.config.config_dir = "/config"
    h.states = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states.is_state = MagicMock(return_value=False)
    h.data = {}
    return h


@pytest.fixture
def switch_device(mock_hass):
    return SwitchDevice(
        hass=mock_hass,
        device_id="hot_water",
        name="Hot Water",
        rated_power=2000.0,
        priority=5,
        entity_id="switch.hot_water",
        power_entity_id="sensor.hot_water_power",
        min_on_time=300,
        min_off_time=60,
    )


@pytest.fixture
def current_device(mock_hass):
    return CurrentControlDevice(
        hass=mock_hass,
        device_id="ev_charger",
        name="EV Charger",
        priority=5,
        min_current=6.0,
        max_current=32.0,
        phases=3,
        voltage=230.0,
        current_entity_id="number.keba_current",
        charger_service="keba.set_current",
        charger_service_entity_id="sensor.keba",
    )


@pytest.fixture
def setpoint_device(mock_hass):
    return SetpointDevice(
        hass=mock_hass,
        device_id="heat_pump",
        name="Heat Pump",
        rated_power=2000.0,
        priority=4,
        climate_entity_id="climate.heat_pump",
        normal_setpoint=21.0,
        boost_offset=2.0,
        max_setpoint=55.0,
    )


@pytest.fixture
def climate_device(mock_hass):
    return ClimateDevice(
        hass=mock_hass,
        device_id="ac_living",
        name="Living Room AC",
        rated_power=1800.0,
        priority=6,
        entity_id="climate.living_room_ac",
        power_entity_id="sensor.ac_power",
        hvac_mode="cool",
        target_temperature=22.0,
        min_on_time=300,
        min_off_time=60,
    )


@pytest.fixture
def schedule_device(mock_hass):
    return ScheduleDevice(
        hass=mock_hass,
        device_id="dishwasher",
        name="Dishwasher",
        rated_power=1500.0,
        priority=7,
        entity_id="switch.dishwasher",
    )


@pytest.fixture
def heat_pump(mock_hass):
    return HeatPumpController(
        hass=mock_hass,
        device_id="heat_pump",
        name="Heat Pump",
        rated_power=2000.0,
        priority=4,
        min_power_threshold=2000.0,
        relay1_entity_id="switch.sg_relay1",
        relay2_entity_id="switch.sg_relay2",
        climate_entity_id="climate.heat_pump",
        temperature_entity_id="sensor.heat_pump_temp",
        normal_setpoint=21.0,
        boost_offset=2.0,
        max_setpoint=55.0,
        force_on_threshold=5000.0,
    )


@pytest.fixture
def hot_water(mock_hass):
    return HotWaterController(
        hass=mock_hass,
        device_id="hot_water",
        name="Hot Water",
        rated_power=2000.0,
        priority=6,
        entity_id="switch.hot_water_relay",
        temperature_entity_id="sensor.hot_water_temp",
        max_temperature=60.0,
        min_temperature=40.0,
    )


@pytest.fixture
def scheduler(mock_hass):
    return ApplianceScheduler(mock_hass)


# ──────────────────────────────────────────────
# SwitchDevice tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_switch_device_activate(switch_device):
    """Test switch activation turns on entity and returns rated power."""
    result = await switch_device.activate(3000.0)
    assert result == 2000.0
    assert switch_device.is_active
    assert switch_device._status.activation_count == 1
    switch_device.hass.services.async_call.assert_called_once_with(
        "homeassistant", "turn_on",
        {"entity_id": "switch.hot_water"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_switch_device_activate_no_entity(mock_hass):
    """Test switch with no entity_id returns 0."""
    dev = SwitchDevice(hass=mock_hass, device_id="test", name="Test", rated_power=1000.0, entity_id=None)
    result = await dev.activate(2000.0)
    assert result == 0.0
    mock_hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_switch_device_anti_flicker_off(switch_device):
    """Test activate respects min_off_time (anti-flicker)."""
    # Simulate recent deactivation
    switch_device._last_deactivated = datetime.now()  # (#644) unified clock
    result = await switch_device.activate(3000.0)
    assert result == 0.0


@pytest.mark.asyncio
async def test_switch_device_deactivate_anti_flicker_on(switch_device):
    """Test deactivate respects min_on_time (anti-flicker)."""
    # Activate first
    await switch_device.activate(3000.0)
    # Immediately try to deactivate — should be blocked by min_on_time
    await switch_device.deactivate()
    assert switch_device.is_active  # still active


@pytest.mark.asyncio
async def test_switch_device_deactivate_after_min_on_time(switch_device):
    """Test deactivate works after min_on_time has elapsed."""
    await switch_device.activate(3000.0)
    # Fake that activation happened long ago
    switch_device._last_activated = datetime.now() - timedelta(seconds=400)  # (#644) unified clock
    await switch_device.deactivate()
    assert not switch_device.is_active
    assert switch_device._status.state == DeviceState.IDLE


@pytest.mark.asyncio
async def test_switch_device_adjust_power(switch_device):
    """Test adjust_power returns rated_power when active, 0 when idle."""
    result = await switch_device.adjust_power(5000.0)
    assert result == 0.0
    await switch_device.activate(3000.0)
    result = await switch_device.adjust_power(5000.0)
    assert result == 2000.0


@pytest.mark.asyncio
async def test_switch_device_error_handling(switch_device):
    """Test service call failure sets ERROR state."""
    switch_device.hass.services.async_call = AsyncMock(side_effect=Exception("Service failed"))
    result = await switch_device.activate(3000.0)
    assert result == 0.0
    assert switch_device._status.state == DeviceState.ERROR
    assert switch_device._status.error_message == "Service failed"


# ──────────────────────────────────────────────
# ClimateDevice tests (#569)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_climate_device_activate(climate_device):
    """Activation sets the configured hvac_mode + target temperature."""
    result = await climate_device.activate(3000.0)
    assert result == 1800.0
    assert climate_device.is_active
    assert climate_device._status.activation_count == 1
    calls = climate_device.hass.services.async_call.await_args_list
    assert ("climate", "set_hvac_mode",
            {"entity_id": "climate.living_room_ac", "hvac_mode": "cool"}) == calls[0].args
    assert calls[0].kwargs == {"blocking": True}
    assert ("climate", "set_temperature",
            {"entity_id": "climate.living_room_ac", "temperature": 22.0}) == calls[1].args
    assert calls[1].kwargs == {"blocking": True}


@pytest.mark.asyncio
async def test_climate_device_set_temperature_failure_stays_active(climate_device):
    """B1: set_hvac_mode succeeds, set_temperature raises → the unit is ON,
    so the device must stay ACTIVE (not ERROR/idle, which would re-activate
    every cycle and run the AC uncontrolled)."""
    async def _fail_on_temp(domain, service, data, **kw):
        if service == "set_temperature":
            raise Exception("temperature out of range")
    climate_device.hass.services.async_call = AsyncMock(side_effect=_fail_on_temp)
    result = await climate_device.activate(3000.0)
    assert result == 1800.0
    assert climate_device.is_active
    assert climate_device._status.state == DeviceState.ACTIVE


@pytest.mark.asyncio
async def test_climate_device_device_type(climate_device):
    assert climate_device.device_type == DeviceType.CLIMATE


@pytest.mark.asyncio
async def test_climate_device_no_target_temp_skips_set_temperature(mock_hass):
    """With no target temperature, only hvac_mode is set."""
    dev = ClimateDevice(
        hass=mock_hass, device_id="ac", name="AC", rated_power=1500.0,
        entity_id="climate.ac", hvac_mode="heat_cool", target_temperature=None,
    )
    await dev.activate(3000.0)
    calls = mock_hass.services.async_call.await_args_list
    assert len(calls) == 1
    assert calls[0].args[1] == "set_hvac_mode"
    assert calls[0].args[2]["hvac_mode"] == "heat_cool"


@pytest.mark.asyncio
async def test_climate_device_activate_no_entity(mock_hass):
    dev = ClimateDevice(hass=mock_hass, device_id="ac", name="AC",
                        rated_power=1500.0, entity_id=None)
    result = await dev.activate(2000.0)
    assert result == 0.0
    mock_hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_climate_device_anti_flicker_off(climate_device):
    """Activate respects min_off_time."""
    climate_device._last_deactivated = datetime.now()  # (#644) unified clock
    result = await climate_device.activate(3000.0)
    assert result == 0.0


@pytest.mark.asyncio
async def test_climate_device_deactivate_sets_off(climate_device):
    """Deactivate turns the unit off via hvac_mode: off."""
    await climate_device.activate(3000.0)
    climate_device.hass.services.async_call.reset_mock()
    climate_device._last_activated = datetime.now() - timedelta(seconds=400)  # (#644) unified clock
    await climate_device.deactivate()
    assert not climate_device.is_active
    assert climate_device._status.state == DeviceState.IDLE
    climate_device.hass.services.async_call.assert_called_once_with(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.living_room_ac", "hvac_mode": "off"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_climate_device_deactivate_anti_flicker_on(climate_device):
    """Deactivate respects min_on_time."""
    await climate_device.activate(3000.0)
    await climate_device.deactivate()  # immediate — blocked
    assert climate_device.is_active


@pytest.mark.asyncio
async def test_climate_device_adjust_power(climate_device):
    result = await climate_device.adjust_power(5000.0)
    assert result == 0.0
    await climate_device.activate(3000.0)
    result = await climate_device.adjust_power(5000.0)
    assert result == 1800.0


@pytest.mark.asyncio
async def test_climate_device_error_handling(climate_device):
    climate_device.hass.services.async_call = AsyncMock(
        side_effect=Exception("Service failed"))
    result = await climate_device.activate(3000.0)
    assert result == 0.0
    assert climate_device._status.state == DeviceState.ERROR
    assert climate_device._status.error_message == "Service failed"


@pytest.mark.asyncio
async def test_climate_device_adopt_if_running(climate_device):
    """After restart, a climate entity in a non-off state is re-owned."""
    state = MagicMock()
    state.state = "cool"
    climate_device.hass.states.get = MagicMock(return_value=state)
    assert climate_device.adopt_if_running() is True
    assert climate_device.is_active


@pytest.mark.asyncio
async def test_climate_device_adopt_skips_when_off(climate_device):
    state = MagicMock()
    state.state = "off"
    climate_device.hass.states.get = MagicMock(return_value=state)
    assert climate_device.adopt_if_running() is False
    assert not climate_device.is_active


@pytest.mark.asyncio
async def test_climate_device_adopt_skips_when_different_mode(climate_device):
    """H1: a unit the user manually put into a different mode (heat while we
    manage cool) must NOT be adopted — else deactivate() would turn off the
    user's manual run."""
    state = MagicMock()
    state.state = "heat"  # climate_device.hvac_mode == "cool"
    climate_device.hass.states.get = MagicMock(return_value=state)
    assert climate_device.adopt_if_running() is False
    assert not climate_device.is_active


# ──────────────────────────────────────────────
# surplus_device_from_spec factory (#569)
# ──────────────────────────────────────────────

def test_factory_builds_switch_by_default(mock_hass):
    dev = surplus_device_from_spec(mock_hass, "d1", {
        "entity_id": "switch.plug", "name": "Plug", "rated_power": 1000,
        "priority": 5,
    })
    assert isinstance(dev, SwitchDevice)


def test_factory_builds_climate(mock_hass):
    dev = surplus_device_from_spec(mock_hass, "ac1", {
        "device_type": "climate", "entity_id": "climate.ac", "name": "AC",
        "rated_power": 1800, "priority": 6, "hvac_mode": "cool",
        "target_temperature": 22.0,
    })
    assert isinstance(dev, ClimateDevice)
    assert dev.hvac_mode == "cool"
    assert dev.target_temperature == 22.0
    assert dev.entity_id == "climate.ac"


def test_switch_device_type(switch_device):
    """Test device_type is SWITCH."""
    assert switch_device.device_type == DeviceType.SWITCH


# ──────────────────────────────────────────────
# CurrentControlDevice tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_current_control_device_activate(current_device):
    """Test activate calculates current and calls service."""
    # 10000W / (3 * 230) = 14.49A -> clamped between 6 and 32
    result = await current_device.activate(10000.0)
    assert result > 0
    assert current_device.is_active


def test_current_control_watts_to_current(current_device):
    """Test watts to current conversion."""
    # 6900W / (3 * 230) = 10A
    assert current_device.watts_to_current(6900.0) == 10.0


def test_current_control_current_to_watts(current_device):
    """Test current to watts conversion."""
    # 10A * 3 * 230 = 6900W
    assert current_device.current_to_watts(10.0) == 6900.0


@pytest.mark.asyncio
async def test_current_control_min_max_clamp(current_device):
    """Test current is clamped to min/max."""
    # Very low watts -> clamped to min_current (6A)
    result = await current_device.activate(500.0)
    expected = current_device.current_to_watts(6.0)
    assert result == expected

    # Reset for next test
    current_device._current_setpoint = 0.0
    current_device._status.state = DeviceState.IDLE

    # Very high watts -> clamped to max_current (32A)
    result = await current_device.activate(50000.0)
    expected = current_device.current_to_watts(32.0)
    assert result == expected


@pytest.mark.asyncio
async def test_current_control_start_stop_session(current_device):
    """Test KEBA session management (with the managed failsafe opted in)."""
    # #546 — SEM no longer arms the failsafe by default (evcc-style); opt in to
    # exercise the full arming sequence here.
    current_device.arm_failsafe_enabled = True
    await current_device.start_session(energy_target_kwh=10.0)
    assert current_device._session_active is True
    # Should have called set_failsafe, set_energy, and enable (no disable
    # — needs_pilot_cycle=False). This is the historically-working
    # sequence shipped since v1.5.0. ``keba.authorize`` was tried briefly
    # on 2026-06-02 as a speculative fix for an auth-rejected cascade —
    # reverted same day after confirming git history shows authorize was
    # never in the sequence; the real fix is the IDLE flicker-hold, now
    # owned by ``ChargerReconciler`` (its consecutive-idle threshold).
    assert current_device.hass.services.async_call.call_count == 3

    # The KEBA failsafe must be set BENIGN, not "disabled" with an invalid
    # timeout=0 (the HA service rejects 0 → the old call failed and the box
    # kept a 6 A failsafe that paused the car). Valid timeout + fallback at the
    # charging floor (≥6 A).
    fs_calls = [
        c for c in current_device.hass.services.async_call.await_args_list
        if len(c.args) >= 2 and c.args[1] == "set_failsafe"
    ]
    assert fs_calls, "start_session must set the KEBA failsafe"
    fs = fs_calls[0].args[2]
    assert fs["failsafe_timeout"] >= 1, "timeout must be valid (service min=1)"
    assert fs["failsafe_fallback"] >= 6, "fallback at/above the IEC floor"
    # #546 — steady mode (default) PERSISTS the benign failsafe so it overwrites
    # the box's built-in 6 A (the 6↔9 A flap source). persist=1 by default.
    assert fs["failsafe_persist"] == 1, "steady mode must persist (overwrite box 6A)"

    current_device.hass.services.async_call.reset_mock()
    await current_device.stop_session()
    assert current_device._session_active is False
    assert current_device._status.state == DeviceState.IDLE


@pytest.mark.asyncio
async def test_failsafe_managed_nontripping_by_default(current_device):
    """#546 managed-neutralize default: SEM arms a LONG non-tripping persisted
    failsafe (overwrites the box's short built-in one, which a real P30 won't
    let us disable over UDP)."""
    from custom_components.solar_energy_management.devices.base import (
        FAILSAFE_TIMEOUT_S,
    )
    assert current_device.arm_failsafe_enabled is True  # default = managed
    current_device.hass.services.async_call.reset_mock()
    await current_device.arm_failsafe()
    fs = [c for c in current_device.hass.services.async_call.await_args_list
          if len(c.args) >= 2 and c.args[1] == "set_failsafe"][0].args[2]
    assert fs["failsafe_timeout"] == FAILSAFE_TIMEOUT_S == 600  # never trips
    assert fs["failsafe_persist"] == 1                          # overwrite the box
    assert fs["failsafe_fallback"] >= 6                         # at the floor


@pytest.mark.asyncio
async def test_failsafe_not_armed_when_disabled(current_device):
    """#546 — keba_arm_failsafe off (don't-arm, evcc-style): SEM doesn't touch
    the failsafe (a Repair guides the user to disable it at the box)."""
    current_device.arm_failsafe_enabled = False
    current_device.hass.services.async_call.reset_mock()
    await current_device.arm_failsafe()
    fs = [c for c in current_device.hass.services.async_call.await_args_list
          if len(c.args) >= 2 and c.args[1] == "set_failsafe"]
    assert not fs, "don't-arm mode must NOT call set_failsafe"


@pytest.mark.asyncio
async def test_current_control_deactivate(current_device):
    """Test deactivate sets current to 0."""
    await current_device.activate(10000.0)
    current_device.hass.services.async_call.reset_mock()
    await current_device.deactivate()
    assert current_device._status.state == DeviceState.IDLE
    assert current_device._status.current_consumption_w == 0.0
    assert current_device._current_setpoint == 0.0


def test_current_control_device_type(current_device):
    """Test device_type is CURRENT_CONTROL."""
    assert current_device.device_type == DeviceType.CURRENT_CONTROL


# ──────────────────────────────────────────────
# SetpointDevice tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setpoint_device_activate(setpoint_device):
    """Test boost temperature via climate service."""
    result = await setpoint_device.activate(3000.0)
    assert result == 2000.0
    assert setpoint_device.is_active
    assert setpoint_device._boosted is True
    setpoint_device.hass.services.async_call.assert_called_once_with(
        "climate", "set_temperature",
        {"entity_id": "climate.heat_pump", "temperature": 23.0},  # 21 + 2
        blocking=True,
    )


@pytest.mark.asyncio
async def test_setpoint_device_deactivate(setpoint_device):
    """Test restore normal temperature."""
    await setpoint_device.activate(3000.0)
    setpoint_device.hass.services.async_call.reset_mock()
    await setpoint_device.deactivate()
    assert not setpoint_device.is_active
    assert setpoint_device._boosted is False
    setpoint_device.hass.services.async_call.assert_called_once_with(
        "climate", "set_temperature",
        {"entity_id": "climate.heat_pump", "temperature": 21.0},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_setpoint_device_no_climate(mock_hass):
    """Test returns 0 without climate entity."""
    dev = SetpointDevice(
        hass=mock_hass, device_id="test", name="Test",
        rated_power=2000.0, climate_entity_id=None,
    )
    result = await dev.activate(3000.0)
    assert result == 0.0


def test_setpoint_device_type(setpoint_device):
    """Test device_type is SETPOINT."""
    assert setpoint_device.device_type == DeviceType.SETPOINT


# ──────────────────────────────────────────────
# ScheduleDevice tests
# ──────────────────────────────────────────────

def test_schedule_device_schedule(schedule_device):
    """Test setting a schedule."""
    deadline = datetime.now() + timedelta(hours=4)
    schedule_device.schedule(deadline, estimated_runtime_minutes=120, estimated_energy_kwh=1.5)
    assert schedule_device.deadline == deadline
    assert schedule_device.estimated_runtime_minutes == 120
    assert schedule_device.estimated_energy_kwh == 1.5
    assert schedule_device._status.state == DeviceState.SCHEDULED


def test_schedule_device_must_start_by(schedule_device):
    """Test must_start_by calculates deadline minus runtime."""
    deadline = datetime(2026, 3, 19, 18, 0, 0)
    schedule_device.schedule(deadline, estimated_runtime_minutes=120)
    expected = datetime(2026, 3, 19, 16, 0, 0)
    assert schedule_device.must_start_by == expected


def test_schedule_device_must_start_by_no_deadline(schedule_device):
    """Test must_start_by returns None without deadline."""
    assert schedule_device.must_start_by is None


def test_schedule_device_is_deadline_approaching(schedule_device):
    """Test is_deadline_approaching when past must_start_by."""
    # Deadline in 30 minutes, runtime 120 minutes -> must_start_by was 90 minutes ago
    deadline = datetime.now() + timedelta(minutes=30)
    schedule_device.schedule(deadline, estimated_runtime_minutes=120)
    assert schedule_device.is_deadline_approaching is True


def test_schedule_device_is_deadline_not_approaching(schedule_device):
    """Test is_deadline_approaching when plenty of time."""
    deadline = datetime.now() + timedelta(hours=6)
    schedule_device.schedule(deadline, estimated_runtime_minutes=120)
    assert schedule_device.is_deadline_approaching is False


@pytest.mark.asyncio
async def test_schedule_device_activate(schedule_device):
    """Test activate starts device."""
    result = await schedule_device.activate(2000.0)
    assert result == 1500.0
    assert schedule_device._started is True
    assert schedule_device.is_active


@pytest.mark.asyncio
async def test_schedule_device_activate_already_started(schedule_device):
    """Test activate returns 0 if already started."""
    await schedule_device.activate(2000.0)
    schedule_device.hass.services.async_call.reset_mock()
    result = await schedule_device.activate(2000.0)
    assert result == 0.0
    schedule_device.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_device_deactivate_while_running(schedule_device):
    """Test deactivate is no-op when already running."""
    await schedule_device.activate(2000.0)
    await schedule_device.deactivate()
    # Should still be active (not interrupted)
    assert schedule_device._started is True


@pytest.mark.asyncio
async def test_schedule_device_deactivate_not_started(schedule_device):
    """Test deactivate before start changes state appropriately."""
    deadline = datetime.now() + timedelta(hours=4)
    schedule_device.schedule(deadline)
    await schedule_device.deactivate()
    assert schedule_device._status.state == DeviceState.SCHEDULED


def test_schedule_device_clear_schedule(schedule_device):
    """Test clear_schedule resets state."""
    deadline = datetime.now() + timedelta(hours=4)
    schedule_device.schedule(deadline)
    schedule_device.clear_schedule()
    assert schedule_device.deadline is None
    assert schedule_device._started is False
    assert schedule_device._status.state == DeviceState.IDLE


def test_schedule_device_type(schedule_device):
    """Test device_type is SCHEDULE."""
    assert schedule_device.device_type == DeviceType.SCHEDULE


# ──────────────────────────────────────────────
# HeatPumpController tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heat_pump_activate_boost(heat_pump):
    """Test below force_on_threshold sets BOOST mode."""
    result = await heat_pump.activate(3000.0)
    assert result == 2000.0
    assert heat_pump.sg_ready_state == SGReadyState.BOOST
    assert heat_pump.is_active
    assert heat_pump.hp_status.is_solar_boosted is True


@pytest.mark.asyncio
async def test_heat_pump_activate_force_on(heat_pump):
    """Test above force_on_threshold sets FORCE_ON mode."""
    result = await heat_pump.activate(6000.0)
    assert result == 2000.0
    assert heat_pump.sg_ready_state == SGReadyState.FORCE_ON


@pytest.mark.asyncio
async def test_heat_pump_deactivate(heat_pump):
    """Test deactivate returns to NORMAL."""
    await heat_pump.activate(3000.0)
    heat_pump.hass.services.async_call.reset_mock()
    await heat_pump.deactivate()
    assert heat_pump.sg_ready_state == SGReadyState.NORMAL
    assert heat_pump._status.state == DeviceState.IDLE
    assert heat_pump.hp_status.is_solar_boosted is False


@pytest.mark.asyncio
async def test_heat_pump_has_no_block_actuator(heat_pump):
    """(#664) SEM does not implement ripple control / Sperrzeiten.

    ``block``/``unblock`` were SG-Ready state 1 with no caller — the
    ripple-control surface that would have called them was amputated in
    #654 and #664 closed by deciding not to build it. The methods are gone;
    this pins that they do not quietly come back without a caller.
    """
    assert not hasattr(heat_pump, "block")
    assert not hasattr(heat_pump, "unblock")


@pytest.mark.asyncio
async def test_heat_pump_relay_control(heat_pump):
    """Test relay service calls match SG-Ready mapping."""
    await heat_pump.activate(3000.0)  # Should be BOOST
    calls = heat_pump.hass.services.async_call.call_args_list

    # Find the relay calls (first two before climate call)
    relay_calls = [c for c in calls if c[0][1] in ("turn_on", "turn_off")]
    # #523: BOOST is the SG-Ready standard 0:1 -> relay1=turn_off, relay2=turn_on
    relay1_call = [c for c in relay_calls if "sg_relay1" in str(c)]
    relay2_call = [c for c in relay_calls if "sg_relay2" in str(c)]
    assert len(relay1_call) >= 1
    assert len(relay2_call) >= 1
    assert relay1_call[0][0][1] == "turn_off"
    assert relay2_call[0][0][1] == "turn_on"


def test_heat_pump_get_current_temperature(heat_pump):
    """Test reading temperature from sensor."""
    mock_state = MagicMock()
    mock_state.state = "45.5"
    heat_pump.hass.states.get = MagicMock(return_value=mock_state)
    assert heat_pump.get_current_temperature() == 45.5


def test_heat_pump_get_current_temperature_unavailable(heat_pump):
    """Test returns None when sensor unavailable."""
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    heat_pump.hass.states.get = MagicMock(return_value=mock_state)
    assert heat_pump.get_current_temperature() is None


# ──────────────────────────────────────────────
# HotWaterController tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hot_water_activate_safe(hot_water):
    """Test activates when temperature is below max."""
    mock_state = MagicMock()
    mock_state.state = "45.0"
    hot_water.hass.states.get = MagicMock(return_value=mock_state)
    result = await hot_water.activate(3000.0)
    assert result == 2000.0
    assert hot_water.is_active


@pytest.mark.asyncio
async def test_hot_water_activate_unsafe(hot_water):
    """Test skips activation when temperature >= max."""
    mock_state = MagicMock()
    mock_state.state = "62.0"
    hot_water.hass.states.get = MagicMock(return_value=mock_state)
    result = await hot_water.activate(3000.0)
    assert result == 0.0
    assert not hot_water.is_active


def test_hot_water_needs_heating(hot_water):
    """Test needs_heating when temp < min."""
    mock_state = MagicMock()
    mock_state.state = "35.0"
    hot_water.hass.states.get = MagicMock(return_value=mock_state)
    assert hot_water.needs_heating() is True


def test_hot_water_does_not_need_heating(hot_water):
    """Test needs_heating returns False when temp >= min."""
    mock_state = MagicMock()
    mock_state.state = "50.0"
    hot_water.hass.states.get = MagicMock(return_value=mock_state)
    assert hot_water.needs_heating() is False


def test_hot_water_no_temp_sensor(mock_hass):
    """Test is_temperature_safe returns True when no sensor configured."""
    hw = HotWaterController(hass=mock_hass, device_id="hw", name="HW", rated_power=2000.0)
    assert hw.is_temperature_safe() is True
    assert hw.needs_heating() is True  # No sensor -> assume needs heating


def test_hot_water_get_current_temperature(hot_water):
    """Test reading water temperature."""
    mock_state = MagicMock()
    mock_state.state = "52.3"
    hot_water.hass.states.get = MagicMock(return_value=mock_state)
    assert hot_water.get_current_temperature() == 52.3


def test_hot_water_get_current_temperature_no_sensor(mock_hass):
    """Test returns None when no temperature sensor."""
    hw = HotWaterController(hass=mock_hass, device_id="hw", name="HW", rated_power=2000.0)
    assert hw.get_current_temperature() is None


# ──────────────────────────────────────────────
# ApplianceScheduler tests
# ──────────────────────────────────────────────

def test_appliance_scheduler_register(scheduler):
    """Test registering an appliance."""
    device = scheduler.register_appliance(
        "dishwasher", "Dishwasher", 1500.0, "switch.dishwasher", priority=7,
    )
    assert device.device_id == "dishwasher"
    assert device.name == "Dishwasher"
    assert "dishwasher" in scheduler._devices


def test_appliance_scheduler_schedule(scheduler):
    """Test scheduling an appliance."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    deadline = datetime.now() + timedelta(hours=4)
    result = scheduler.schedule_appliance("dishwasher", deadline, 120, 1.5)
    assert result is True
    assert "dishwasher" in scheduler._schedules
    assert scheduler._schedules["dishwasher"].status == "scheduled"


def test_appliance_scheduler_schedule_unknown(scheduler):
    """Test scheduling unknown appliance returns False."""
    result = scheduler.schedule_appliance("nonexistent", datetime.now(), 60, 0.5)
    assert result is False


def test_appliance_scheduler_cancel(scheduler):
    """Test cancelling a schedule."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    deadline = datetime.now() + timedelta(hours=4)
    scheduler.schedule_appliance("dishwasher", deadline)
    result = scheduler.cancel_schedule("dishwasher")
    assert result is True
    assert "dishwasher" not in scheduler._schedules


def test_appliance_scheduler_cancel_nonexistent(scheduler):
    """Test cancelling nonexistent schedule returns False."""
    result = scheduler.cancel_schedule("nonexistent")
    assert result is False


def test_appliance_scheduler_update_completed(scheduler):
    """Test detecting completed appliance."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    deadline = datetime.now() + timedelta(hours=4)
    scheduler.schedule_appliance("dishwasher", deadline, estimated_runtime_minutes=60)

    device = scheduler._devices["dishwasher"]
    # Simulate device started running
    device._started = True
    device._start_time = datetime.now() - timedelta(minutes=70)
    # Low consumption signals completion
    device._status.current_consumption_w = 5.0

    # First call transitions from "scheduled" to "running" and sets started_at
    scheduler.update_schedules()
    assert scheduler._schedules["dishwasher"].status == "running"

    # Backdate started_at so elapsed time triggers completion check
    scheduler._schedules["dishwasher"].started_at = datetime.now() - timedelta(minutes=70)

    # Second call detects completion (elapsed >= runtime, consumption < 10, elapsed >= 5)
    scheduler.update_schedules()
    assert "dishwasher" not in scheduler._schedules
    assert len(scheduler._history) == 1
    assert scheduler._history[0].status == "completed"


def test_appliance_scheduler_update_missed(scheduler):
    """Test detecting missed deadline."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    deadline = datetime.now() - timedelta(hours=1)  # Past deadline
    scheduler.schedule_appliance("dishwasher", deadline)

    scheduler.update_schedules()
    assert "dishwasher" not in scheduler._schedules
    assert len(scheduler._history) == 1
    assert scheduler._history[0].status == "missed"


def test_appliance_scheduler_get_pending(scheduler):
    """Test get_pending_schedules."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    scheduler.register_appliance("washer", "Washer", 1200.0, "switch.washer")
    scheduler.schedule_appliance("dishwasher", datetime.now() + timedelta(hours=4))
    scheduler.schedule_appliance("washer", datetime.now() + timedelta(hours=6))
    pending = scheduler.get_pending_schedules()
    assert len(pending) == 2


def test_appliance_scheduler_get_next(scheduler):
    """Test get_next_scheduled returns earliest deadline."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    scheduler.register_appliance("washer", "Washer", 1200.0, "switch.washer")
    early = datetime.now() + timedelta(hours=2)
    later = datetime.now() + timedelta(hours=6)
    scheduler.schedule_appliance("dishwasher", early)
    scheduler.schedule_appliance("washer", later)
    nxt = scheduler.get_next_scheduled()
    assert nxt.appliance_id == "dishwasher"


def test_appliance_scheduler_get_next_empty(scheduler):
    """Test get_next_scheduled returns None when empty."""
    assert scheduler.get_next_scheduled() is None


def test_appliance_scheduler_summary(scheduler):
    """Test get_schedule_summary format."""
    scheduler.register_appliance("dishwasher", "Dishwasher", 1500.0, "switch.dishwasher")
    scheduler.schedule_appliance("dishwasher", datetime.now() + timedelta(hours=4), 120, 1.5)
    summary = scheduler.get_schedule_summary()
    assert summary["scheduled_appliances"] == 1
    assert len(summary["schedules"]) == 1
    assert summary["next_appliance"] == "Dishwasher"
    assert "completed_today" in summary


# ──────────────────────────────────────────────
# Serialization / misc tests
# ──────────────────────────────────────────────

def test_device_to_dict_switch(switch_device):
    """Test SwitchDevice serialization."""
    d = switch_device.to_dict()
    assert d["device_id"] == "hot_water"
    assert d["type"] == "switch"
    assert d["priority"] == 5
    assert d["state"] == "idle"
    assert d["enabled"] is True


def test_device_to_dict_current_control(current_device):
    """Test CurrentControlDevice serialization."""
    d = current_device.to_dict()
    assert d["type"] == "current_control"
    assert d["min_current"] == 6.0
    assert d["max_current"] == 32.0
    assert d["phases"] == 3
    assert "session_active" in d


def test_device_to_dict_setpoint(setpoint_device):
    """Test SetpointDevice serialization."""
    d = setpoint_device.to_dict()
    assert d["type"] == "setpoint"
    assert d["normal_setpoint"] == 21.0
    assert d["boost_offset"] == 2.0
    assert d["boosted"] is False


def test_device_to_dict_schedule(schedule_device):
    """Test ScheduleDevice serialization."""
    deadline = datetime(2026, 3, 19, 18, 0, 0)
    schedule_device.schedule(deadline, 120, 1.5)
    d = schedule_device.to_dict()
    assert d["type"] == "schedule"
    assert d["deadline"] == deadline.isoformat()
    assert d["estimated_runtime_minutes"] == 120
    assert d["started"] is False
    assert d["must_start_by"] is not None


def test_device_to_dict_heat_pump(heat_pump):
    """Test HeatPumpController serialization."""
    d = heat_pump.to_dict()
    assert d["sg_ready_state"] == "NORMAL"
    assert d["force_on_threshold"] == 5000.0
    assert "is_solar_boosted" in d


def test_device_to_dict_hot_water(hot_water):
    """Test HotWaterController serialization."""
    hot_water.hass.states.get = MagicMock(return_value=None)
    d = hot_water.to_dict()
    assert d["max_temperature"] == 60.0
    assert d["min_temperature"] == 40.0
    assert "temperature_safe" in d
    assert "needs_heating" in d


def test_device_enable_disable(switch_device):
    """Test enable/disable toggle."""
    assert switch_device.is_enabled is True
    switch_device.disable()
    assert switch_device.is_enabled is False
    switch_device.enable()
    assert switch_device.is_enabled is True


def test_device_managed_externally(current_device):
    """Test externally managed flag."""
    assert current_device.managed_externally is False
    current_device.managed_externally = True
    assert current_device.managed_externally is True


def test_get_current_consumption_from_entity(switch_device):
    """Test reading consumption from power entity."""
    mock_state = MagicMock()
    mock_state.state = "1850.5"
    switch_device.hass.states.get = MagicMock(return_value=mock_state)
    result = switch_device.get_current_consumption()
    assert result == 1850.5


def test_get_current_consumption_unavailable(switch_device):
    """Test fallback when power entity unavailable."""
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    switch_device.hass.states.get = MagicMock(return_value=mock_state)
    assert switch_device.get_current_consumption() == switch_device._status.current_consumption_w


def test_get_current_consumption_no_entity(mock_hass):
    """Test fallback when no power entity configured."""
    dev = SwitchDevice(hass=mock_hass, device_id="test", name="Test", rated_power=1000.0)
    dev._status.current_consumption_w = 750.0
    assert dev.get_current_consumption() == 750.0


def test_priority_clamp():
    """Test priority is clamped between 1 and 10."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    dev = SwitchDevice(hass=hass, device_id="t", name="T", rated_power=100, priority=0)
    assert dev.priority == 1
    dev2 = SwitchDevice(hass=hass, device_id="t2", name="T2", rated_power=100, priority=15)
    assert dev2.priority == 10
