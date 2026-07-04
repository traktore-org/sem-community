"""#559 Phases 1-3 — the goal engine for generic surplus loads.

Daily targets (runtime and/or energy) with deadline + top-up policy on
SURPLUS-mode devices; max-runtime safety cap; external stop condition.
Peak veto outranks the goal ramp everywhere.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, DeviceControlMode,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

TODAY = date(2026, 7, 4)


def _switch(hass=None, **kw):
    dev = SwitchDevice(
        hass=hass or MagicMock(),
        device_id=kw.get("device_id", "pump"),
        name=kw.get("name", "Pool Pump"),
        rated_power=kw.get("rated_power", 800),
        priority=kw.get("priority", 5),
        entity_id="switch.pump",
    )
    dev.control_mode = DeviceControlMode.SURPLUS
    return dev


# ---------------------------------------------------------------------------
# Device-level goal properties
# ---------------------------------------------------------------------------

class TestGoalProperties:

    def test_runtime_target_met(self):
        dev = _switch()
        dev.daily_min_runtime_sec = 3600
        assert dev.daily_targets_met is False
        dev._daily_runtime_accumulated_sec = 3600
        assert dev.daily_targets_met is True

    def test_energy_target_met(self):
        dev = _switch()
        dev.daily_target_energy_kwh = 2.0
        dev._daily_energy_accumulated_kwh = 1.9
        assert dev.daily_targets_met is False
        dev._daily_energy_accumulated_kwh = 2.0
        assert dev.daily_targets_met is True

    def test_both_targets_must_be_met(self):
        dev = _switch()
        dev.daily_min_runtime_sec = 3600
        dev.daily_target_energy_kwh = 2.0
        dev._daily_runtime_accumulated_sec = 3600
        dev._daily_energy_accumulated_kwh = 0.5
        assert dev.daily_targets_met is False

    def test_no_target_never_met(self):
        dev = _switch()
        assert dev.daily_targets_met is False

    def test_max_runtime_cap(self):
        dev = _switch()
        dev.daily_max_runtime_sec = 1800
        dev._daily_runtime_accumulated_sec = 1801
        assert dev.daily_max_runtime_reached is True

    def test_stop_condition(self):
        hass = MagicMock()
        hass.states.get = lambda e: SimpleNamespace(state="82", attributes={}) if e == "sensor.car_soc" else None
        dev = _switch(hass=hass)
        dev.stop_entity = "sensor.car_soc"
        dev.stop_at = 80
        assert dev.stop_condition_met is True
        dev.stop_at = 90
        assert dev.stop_condition_met is False

    def test_stop_condition_unavailable_not_met(self):
        hass = MagicMock()
        hass.states.get = lambda e: SimpleNamespace(state="unavailable", attributes={})
        dev = _switch(hass=hass)
        dev.stop_entity = "sensor.car_soc"
        dev.stop_at = 80
        assert dev.stop_condition_met is False

    def test_deadline_pressure_runtime(self):
        dev = _switch()
        dev.daily_min_runtime_sec = 2 * 3600  # 2h open
        now = datetime.now()
        # deadline 1h away → 2h no longer fit
        dl = (now + timedelta(hours=1)).strftime("%H:%M")
        dev.target_deadline = dl
        assert dev.deadline_pressure is True
        # deadline 4h away (same day) → still fits
        if now.hour <= 19:
            dev.target_deadline = (now + timedelta(hours=4)).strftime("%H:%M")
            assert dev.deadline_pressure is False

    def test_deadline_pressure_energy_converts_via_rated_power(self):
        dev = _switch(rated_power=1000)
        dev.daily_target_energy_kwh = 2.0  # needs 2h at 1kW
        dev.target_deadline = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
        assert dev.deadline_pressure is True

    def test_energy_accumulates_while_active(self):
        dev = _switch()
        dev.get_current_consumption = MagicMock(return_value=800.0)
        dev.status.state = MagicMock()
        dev._daily_runtime_meter_day = TODAY
        dev._daily_runtime_last_check = datetime.now() - timedelta(seconds=60)
        with patch.object(type(dev), "is_active", property(lambda self: True)):
            dev.update_daily_runtime(TODAY)
        assert dev._daily_energy_accumulated_kwh == pytest.approx(800 * 60 / 3_600_000, rel=0.1)


# ---------------------------------------------------------------------------
# Controller goal gates + passes (mocked devices)
# ---------------------------------------------------------------------------

def _mock_device(**kw):
    device = MagicMock()
    device.device_id = kw.get("device_id", "dev1")
    device.name = kw.get("name", "Dev")
    device.priority = kw.get("priority", 5)
    device.min_power_threshold = kw.get("min_power", 500)
    device.is_enabled = True
    device.managed_externally = False
    device.is_active = kw.get("is_active", False)
    device.device_type = MagicMock(value="switch")
    device.activate = AsyncMock(return_value=kw.get("min_power", 500))
    device.adjust_power = AsyncMock(return_value=kw.get("min_power", 500))
    device.get_current_consumption = MagicMock(return_value=kw.get("consumption", 0.0))
    device.can_activate = MagicMock(return_value=True)
    device.can_deactivate = MagicMock(return_value=True)
    device.record_activated = MagicMock()
    device.record_deactivated = MagicMock()
    device.reset_surplus_timer = MagicMock()
    device.status = MagicMock()
    device.control_mode = kw.get("control_mode", DeviceControlMode.SURPLUS)
    device._offpeak_forced = False
    device.needs_offpeak_activation = kw.get("needs_offpeak", False)
    device.remaining_daily_runtime_sec = kw.get("remaining_sec", 0)
    device.daily_min_runtime_sec = 0
    device.daily_max_runtime_reached = kw.get("cap_reached", False)
    device.daily_targets_met = kw.get("targets_met", False)
    device.stop_condition_met = kw.get("stop_met", False)
    device.deadline_pressure = kw.get("pressure", False)
    device.top_up_policy = kw.get("policy", "solar_only")
    device._solar_only_miss_logged = kw.get("miss_logged", True)
    device._deadline_forced = False
    device._offpeak_forced_date = None
    device.stop_entity = "sensor.x"
    device.stop_at = 80
    device.target_deadline = "21:00"
    device.__class__ = MagicMock

    async def _deactivate():
        device.is_active = False
    device.deactivate = AsyncMock(side_effect=_deactivate)
    return device


@pytest.mark.asyncio
class TestControllerGoalGates:

    async def test_target_met_device_deactivated(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, targets_met=True, consumption=800)
        sc.register_device(dev)
        await sc.update(5000.0)
        dev.deactivate.assert_awaited()

    async def test_cap_reached_device_not_activated(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(cap_reached=True)
        sc.register_device(dev)
        await sc.update(5000.0)
        dev.activate.assert_not_called()

    async def test_stop_condition_deactivates(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, stop_met=True, consumption=800)
        sc.register_device(dev)
        await sc.update(5000.0)
        dev.deactivate.assert_awaited()

    async def test_peak_only_device_untouched_by_goal_gate(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, targets_met=True, consumption=800,
                           control_mode=DeviceControlMode.PEAK_ONLY)
        sc.register_device(dev)
        await sc.update(5000.0)
        dev.deactivate.assert_not_called()

    async def test_solar_only_never_cheap_forced(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(needs_offpeak=True, remaining_sec=1800, policy="solar_only")
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.activate.assert_not_called()

    async def test_cheap_hours_policy_forces_on_cheap(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(needs_offpeak=True, remaining_sec=1800, policy="cheap_hours")
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.activate.assert_called_once()

    async def test_always_policy_deadline_forces_regardless_of_price(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(pressure=True, policy="always")
        sc.register_device(dev)
        await sc.update(0.0, price_level="expensive")
        dev.activate.assert_called_once()

    async def test_deadline_force_suppressed_by_peak(self, mock_hass):
        from custom_components.solar_energy_management.const import LoadManagementState
        sc = SurplusController(mock_hass)
        dev = _mock_device(pressure=True, policy="always")
        sc.register_device(dev)
        await sc.update(0.0, price_level="expensive",
                        peak_state=LoadManagementState.WARNING)
        dev.activate.assert_not_called()

    async def test_solar_only_deadline_miss_logged_not_forced(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _mock_device(pressure=True, policy="solar_only", miss_logged=False)
        sc.register_device(dev)
        await sc.update(0.0)
        dev.activate.assert_not_called()
        assert dev._solar_only_miss_logged is True


# ---------------------------------------------------------------------------
# Registry goal persistence
# ---------------------------------------------------------------------------

class _FakeController:
    def __init__(self):
        self._devices = {}
    def register_device(self, d): self._devices[d.device_id] = d
    def unregister_device(self, did): self._devices.pop(did, None)
    def get_device(self, did): return self._devices.get(did)


@pytest.fixture
def registry():
    reg = UnifiedDeviceRegistry(MagicMock(), _FakeController(), MagicMock(), MagicMock())
    reg._store = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    return reg


@pytest.mark.asyncio
async def test_goal_update_persists_and_applies(registry):
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    await registry.async_update_device_goal("pump", "daily_min_runtime_min", 240)
    await registry.async_update_device_goal("pump", "top_up_policy", "cheap_hours")
    await registry.async_update_device_goal("pump", "target_deadline", "21:00")

    dev = registry._surplus_controller.get_device("pump")
    assert dev.daily_min_runtime_sec == 240 * 60
    assert dev.top_up_policy == "cheap_hours"
    assert dev.target_deadline == "21:00"
    assert registry._device_goals["pump"]["daily_min_runtime_min"] == 240


@pytest.mark.asyncio
async def test_goals_survive_reregistration(registry):
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    await registry.async_update_device_goal("pump", "daily_target_energy_kwh", 3.5)
    # simulate boot
    registry._surplus_controller._devices.clear()
    registry._register_service_devices()
    dev = registry._surplus_controller.get_device("pump")
    assert dev.daily_target_energy_kwh == 3.5


@pytest.mark.asyncio
async def test_unknown_goal_property_raises(registry):
    with pytest.raises(ValueError):
        await registry.async_update_device_goal("pump", "nonsense", 1)


@pytest.mark.asyncio
async def test_unregister_drops_goals(registry):
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    await registry.async_update_device_goal("pump", "daily_min_runtime_min", 60)
    await registry.async_unregister_service_device("pump")
    assert "pump" not in registry._device_goals


def test_goal_payload_shape(registry):
    registry._device_goals["pump"] = {
        "daily_min_runtime_min": 240, "top_up_policy": "always",
    }
    payload = registry._goal_payload("pump")
    assert payload["goals"]["daily_min_runtime_min"] == 240
    assert payload["goals"]["top_up_policy"] == "always"
    assert payload["progress"]["runtime_today_min"] == 0


# ---------------------------------------------------------------------------
# Force-expiry semantics (review HIGH — night runaway)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForceExpiry:

    async def test_deadline_force_survives_expensive_tariff(self, mock_hass):
        # An always-policy deadline force must NOT be killed by the
        # HT-tariff deactivation (that would flap force/kill every cycle)
        sc = SurplusController(mock_hass)
        dev = _mock_device(pressure=True, policy="always")
        sc.register_device(dev)
        await sc.update(0.0, price_level="expensive")
        dev.activate.assert_called_once()
        assert dev._deadline_forced is True
        dev.is_active = True
        await sc.update(0.0, price_level="expensive")
        dev.deactivate.assert_not_called()  # pressure still on → keeps running

    async def test_deadline_force_expires_when_pressure_gone(self, mock_hass):
        # Day rollover resets progress → pressure false → force ends
        # (pre-fix the device re-filled the NEW day's target from grid)
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, policy="always", pressure=False)
        dev._deadline_forced = True
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.deactivate.assert_awaited()
        assert dev._deadline_forced is False

    async def test_cheap_force_expires_on_day_rollover_in_cheap_window(self, mock_hass):
        from datetime import date as _date
        from homeassistant.util import dt as dt_util
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, policy="cheap_hours",
                           needs_offpeak=True, remaining_sec=3600)
        dev._offpeak_forced = True
        dev._offpeak_forced_date = _date(2020, 1, 1)  # forced YESTERDAY
        sc.register_device(dev)
        # tariff still cheap — the stale force ends; the cheap pass may then
        # legitimately re-force for the NEW day's deficit (stamped today),
        # bounded by the goal gate once the new target is met.
        await sc.update(0.0, price_level="cheap")
        dev.deactivate.assert_awaited()
        assert dev._offpeak_forced_date == dt_util.now().date()

    async def test_cheap_force_rollover_without_new_deficit_stays_off(self, mock_hass):
        from datetime import date as _date
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, policy="cheap_hours",
                           needs_offpeak=False)
        dev._offpeak_forced = True
        dev._offpeak_forced_date = _date(2020, 1, 1)
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.deactivate.assert_awaited()
        assert dev._offpeak_forced is False
        dev.activate.assert_not_called()

    async def test_cheap_force_holds_same_day_in_cheap_window(self, mock_hass):
        from homeassistant.util import dt as dt_util
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, policy="cheap_hours")
        dev._offpeak_forced = True
        dev._offpeak_forced_date = dt_util.now().date()
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.deactivate.assert_not_called()
