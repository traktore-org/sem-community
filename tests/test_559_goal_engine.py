"""#559 — the goal engine for generic surplus loads (grounded core).

After the beta.19 freeze the surface is: mode ladder off<peak_only<surplus,
a daily runtime target (daily_min_runtime_sec), top_up_policy solar_only|cheap_hours
(cheap_hours = HW/HP off-peak pass), and an external stop condition. The
speculative surface (energy targets, daily-max caps, target_deadline, always
policy, the deadline-force pass) was DELETED — it carried both HIGH bugs.
"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, DeviceControlMode, DeviceState,
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

    def test_no_target_never_met(self):
        dev = _switch()
        assert dev.daily_targets_met is False

    def test_off_mode_does_not_accumulate_runtime(self):
        # #559 (alex Issue 6): a device switched to Off must NOT keep counting
        # its daily solar budget, even if physically still active.
        from datetime import datetime, timedelta
        dev = _switch()
        dev._status.state = DeviceState.ACTIVE
        dev._daily_runtime_meter_day = TODAY
        dev._daily_runtime_last_check = datetime.now() - timedelta(seconds=60)
        dev.control_mode = DeviceControlMode.OFF
        dev.update_daily_runtime(TODAY)
        assert dev._daily_runtime_accumulated_sec == 0.0
        # in Surplus it WOULD accumulate
        dev.control_mode = DeviceControlMode.SURPLUS
        dev._daily_runtime_last_check = datetime.now() - timedelta(seconds=60)
        dev.update_daily_runtime(TODAY)
        assert dev._daily_runtime_accumulated_sec > 0

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

    def test_speculative_surface_removed(self):
        """Freeze guard: the ENERGY / deadline surface stays deleted. The
        runtime max cap (``daily_max_runtime_sec``) was legitimately restored
        in #620 — correctly this time (persisted) — so it's excluded here and
        covered by test_620_device_goal_model.py instead."""
        dev = _switch()
        for attr in (
            "daily_target_energy_kwh",
            "daily_max_energy_kwh", "_daily_energy_accumulated_kwh",
            "daily_max_energy_reached",
            "deadline_pressure", "target_deadline", "_deadline_forced",
            "daily_energy_budget_kwh", "_seconds_until_deadline",
        ):
            assert not hasattr(dev, attr), f"{attr} should be deleted"


# ---------------------------------------------------------------------------
# rated_power auto-calibration (footgun fix)
# ---------------------------------------------------------------------------

def test_rated_power_autocalibrates_from_observed_draw():
    hass = MagicMock()
    hass.states.get = lambda e: SimpleNamespace(state="2300", attributes={}) if e == "sensor.pool_w" else None
    dev = SwitchDevice(
        hass=hass, device_id="pool", name="Pool", rated_power=1000,
        entity_id="switch.pool", power_entity_id="sensor.pool_w",
    )
    # default: threshold seeded from rated_power (1000W)
    assert dev.min_power_threshold == 1000
    dev._status.state = DeviceState.ACTIVE
    dev.calibrate_rated_power()
    assert dev.rated_power == 2300
    assert dev.min_power_threshold == 2300


def test_calibrate_noop_when_off_or_no_sensor():
    hass = MagicMock()
    hass.states.get = lambda e: SimpleNamespace(state="2300", attributes={})
    # no power_entity_id → no-op
    dev = SwitchDevice(hass=hass, device_id="p", name="P", rated_power=1000,
                       entity_id="switch.p")
    dev._status.state = DeviceState.ACTIVE
    dev.calibrate_rated_power()
    assert dev.rated_power == 1000
    # has sensor but device OFF → no-op
    dev2 = SwitchDevice(hass=hass, device_id="p2", name="P2", rated_power=1000,
                        entity_id="switch.p2", power_entity_id="sensor.p2_w")
    dev2.calibrate_rated_power()
    assert dev2.rated_power == 1000


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
    device._batt_overnight_forced = False
    device._batt_overnight_forced_date = None
    device.battery_assist_enabled = False
    device.battery_eligible_overnight = False
    device.needs_offpeak_activation = kw.get("needs_offpeak", False)
    device.remaining_daily_runtime_sec = kw.get("remaining_sec", 0)
    device.daily_min_runtime_sec = 0
    device.daily_targets_met = kw.get("targets_met", False)
    device.daily_max_runtime_reached = kw.get("max_reached", False)
    device.stop_condition_met = kw.get("stop_met", False)
    device.top_up_policy = kw.get("policy", "solar_only")
    device._offpeak_forced_date = None
    device.stop_entity = "sensor.x"
    device.stop_at = 80
    device.__class__ = MagicMock

    async def _deactivate():
        device.is_active = False
    device.deactivate = AsyncMock(side_effect=_deactivate)
    return device


@pytest.mark.asyncio
class TestControllerGoalGates:

    async def test_target_met_device_keeps_free_surplus(self, mock_hass):
        """(#688, was test_target_met_device_deactivated) The daily minimum is
        a FLOOR, not a stop — with 5 kW of sun the load runs on toward its Max
        cap. Reaching the floor only ends the PAID sources; the full contract
        is pinned in test_688_runtime_floor_ceiling.py."""
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, targets_met=True, consumption=800)
        sc.register_device(dev)
        await sc.update(5000.0)
        dev.deactivate.assert_not_awaited()

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

    async def test_no_deadline_force_at_normal_tariff(self, mock_hass):
        # The deadline-critical pass is gone: a surplus device with a runtime
        # deficit and NO surplus is NEVER grid-forced at normal tariff.
        sc = SurplusController(mock_hass)
        dev = _mock_device(needs_offpeak=True, remaining_sec=3600, policy="solar_only")
        sc.register_device(dev)
        await sc.update(0.0, price_level="normal")
        dev.activate.assert_not_called()


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

    dev = registry._surplus_controller.get_device("pump")
    assert dev.daily_min_runtime_sec == 240 * 60
    assert dev.top_up_policy == "cheap_hours"
    assert registry._device_goals["pump"]["daily_min_runtime_min"] == 240


@pytest.mark.asyncio
async def test_concurrent_goal_writes_dont_clobber(registry):
    """Two goal props written concurrently (the card writes stop_entity +
    stop_at as separate calls) must BOTH persist. Reproduces the live Heizband
    race: _save_storage snapshots the dict across an await, and a stale snapshot
    reload dropped one value back to 0. The _goal_write_lock serializes them."""
    import asyncio as _aio
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })

    async def _clobbering_save():
        # snapshot at call time, yield, then reassign — exactly the
        # reload-from-storage clobber the lock must prevent.
        snap = {k: dict(v) for k, v in registry._device_goals.items()}
        await _aio.sleep(0)
        registry._device_goals = snap

    registry._save_storage = _clobbering_save
    await _aio.gather(
        registry.async_update_device_goal("pump", "stop_entity", "sensor.t"),
        registry.async_update_device_goal("pump", "stop_at", "88"),
    )
    g = registry._device_goals["pump"]
    assert g.get("stop_entity") == "sensor.t"
    assert g.get("stop_at") == "88"   # not dropped/clobbered


@pytest.mark.asyncio
async def test_goals_survive_reregistration(registry):
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    await registry.async_update_device_goal("pump", "daily_min_runtime_min", 180)
    # simulate boot
    registry._surplus_controller._devices.clear()
    registry._register_service_devices()
    dev = registry._surplus_controller.get_device("pump")
    assert dev.daily_min_runtime_sec == 180 * 60


@pytest.mark.asyncio
async def test_unknown_goal_property_raises(registry):
    with pytest.raises(ValueError):
        await registry.async_update_device_goal("pump", "nonsense", 1)


@pytest.mark.asyncio
async def test_removed_goal_property_raises(registry):
    """A key deleted in the freeze is no longer settable via the service."""
    with pytest.raises(ValueError):
        await registry.async_update_device_goal("pump", "target_deadline", "21:00")


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
        "daily_min_runtime_min": 240, "top_up_policy": "cheap_hours",
    }
    payload = registry._goal_payload("pump")
    assert payload["goals"]["daily_min_runtime_min"] == 240
    assert payload["goals"]["top_up_policy"] == "cheap_hours"
    assert payload["progress"]["runtime_today_min"] == 0
    # deleted keys are gone from the payload
    assert "target_deadline" not in payload["goals"]
    assert "daily_target_energy_kwh" not in payload["goals"]
    # (#620) daily_max_runtime_min + battery flags are live keys again
    assert payload["goals"]["daily_max_runtime_min"] == 0
    assert payload["goals"]["battery_assist_enabled"] is False
    assert payload["goals"]["battery_eligible_overnight"] is False


@pytest.mark.asyncio
async def test_loads_goal_with_removed_keys(registry):
    """A beta.18-persisted goal dict carrying deleted keys applies cleanly."""
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    registry._device_goals["pump"] = {
        "daily_min_runtime_min": 240, "top_up_policy": "solar_only",
        "daily_max_runtime_min": 120, "target_deadline": "21:00",
        "daily_target_energy_kwh": 5.0, "stop_entity": "", "stop_at": 0,
    }
    dev = registry._surplus_controller.get_device("pump")
    registry._apply_goals(dev)  # must not raise on the extra keys
    assert dev.daily_min_runtime_sec == 240 * 60
    assert dev.top_up_policy == "solar_only"
    # (#620) daily_max_runtime_min is now a LIVE key again — applied to the
    # restored device (the energy/deadline keys are still ignored).
    assert dev.daily_max_runtime_sec == 120 * 60


# ---------------------------------------------------------------------------
# Force-expiry semantics — cheap-hours off-peak (HW/HP path, kept)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForceExpiry:

    async def test_cheap_force_expires_on_day_rollover_in_cheap_window(self, mock_hass):
        # (#703) "day rollover" = the load's METER day moved on (sunrise
        # boundary), not the calendar flip at midnight. Force stamped for the
        # OLD meter day + meter day now advanced → stale → stop, and the
        # re-force stamps the CURRENT meter day.
        from datetime import date as _date
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, policy="cheap_hours",
                           needs_offpeak=True, remaining_sec=3600)
        dev._offpeak_forced = True
        dev._offpeak_forced_date = _date(2020, 1, 1)      # the OLD meter day
        dev._daily_runtime_meter_day = _date(2020, 1, 2)  # sunrise rolled over
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.deactivate.assert_awaited()
        assert dev._offpeak_forced_date == _date(2020, 1, 2)

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
        # (#703) same METER day (even if the calendar flipped at midnight —
        # the sunrise-held day is the boundary that matters) → NOT stale.
        from datetime import date as _date
        sc = SurplusController(mock_hass)
        dev = _mock_device(is_active=True, policy="cheap_hours")
        dev._offpeak_forced = True
        dev._offpeak_forced_date = _date(2020, 1, 1)
        dev._daily_runtime_meter_day = _date(2020, 1, 1)
        sc.register_device(dev)
        await sc.update(0.0, price_level="cheap")
        dev.deactivate.assert_not_called()


# ---------------------------------------------------------------------------
# Boot re-ownership (#559 — orphaned-ON risk)
# ---------------------------------------------------------------------------

class TestAdoptIfRunning:

    def _hass(self, state):
        hass = MagicMock()
        hass.states.get = lambda e: SimpleNamespace(state=state, attributes={}) if e == "switch.pump" else None
        return hass

    def test_adopts_on_switch(self):
        dev = _switch(hass=self._hass("on"))
        dev.entity_id = "switch.pump"
        assert dev.is_active is False
        assert dev.adopt_if_running() is True
        assert dev.is_active is True

    def test_off_switch_not_adopted(self):
        dev = _switch(hass=self._hass("off"))
        dev.entity_id = "switch.pump"
        assert dev.adopt_if_running() is False
        assert dev.is_active is False

    def test_already_active_noop(self):
        dev = _switch(hass=self._hass("on"))
        dev.entity_id = "switch.pump"
        dev.adopt_if_running()
        assert dev.adopt_if_running() is False


@pytest.mark.asyncio
async def test_boot_reregister_adopts_running_surplus_device(registry):
    hass = MagicMock()
    hass.states.get = lambda e: SimpleNamespace(state="on", attributes={}) if e == "switch.pump" else None
    registry.hass = hass
    registry._service_registrations = {"pump": {
        "entity_id": "switch.pump", "name": "Pump", "priority": 5,
        "rated_power": 800, "power_entity_id": None, "control_mode": "surplus",
    }}
    registry._register_service_devices()
    dev = registry._surplus_controller.get_device("pump")
    assert dev.is_active is True  # re-owned — the goal gates govern it again


@pytest.mark.asyncio
async def test_boot_reregister_never_adopts_peak_only(registry):
    hass = MagicMock()
    hass.states.get = lambda e: SimpleNamespace(state="on", attributes={})
    registry.hass = hass
    registry._service_registrations = {"pump": {
        "entity_id": "switch.pump", "name": "Pump", "priority": 5,
        "rated_power": 800, "power_entity_id": None, "control_mode": "peak_only",
    }}
    registry._register_service_devices()
    dev = registry._surplus_controller.get_device("pump")
    assert dev.is_active is False  # user-managed — never adopted
