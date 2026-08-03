"""#508 phase 2 — true-surplus feed (W7) + peak-aware SurplusController (W2).

Phase 1 made the heat-pump / hot-water controllers actually activate on
surplus. Phase 2 fixes WHAT surplus they see and how they behave under a
grid-import peak:

* **W7 — true house surplus.** The controller used to be fed the EV
  charging *budget*; it now receives ``grid_export + own active draw``.
  ``active_surplus_draw_w()`` is the feedback-free addback: without it,
  every device the controller turns on shrinks the export it reads next
  cycle and the device oscillates.
* **W2 — peak posture.** On WARNING the controller stops ADDING
  discretionary load; on SHEDDING/EMERGENCY it backs its own active
  devices off by reverse priority — complementing the load manager
  instead of re-activating, next cycle, whatever it just shed.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode, DeviceState,
)
from custom_components.solar_energy_management.const import LoadManagementState


def _make_device(
    device_id="dev1", name="Test Device", priority=3, min_power=500,
    enabled=True, managed_externally=False, is_active=False, consumption=0.0,
    control_mode=DeviceControlMode.SURPLUS, antiflicker_blocks=False,
):
    device = MagicMock()
    device.device_id = device_id
    device.name = name
    device.priority = priority
    device.min_power_threshold = min_power
    device.is_enabled = enabled
    device.managed_externally = managed_externally
    device.is_active = is_active
    device.device_type = MagicMock(value="switch")
    device.activate = AsyncMock(return_value=min_power)
    device.adjust_power = AsyncMock(return_value=consumption or min_power)
    device.get_current_consumption = MagicMock(return_value=consumption)
    device.can_activate = MagicMock(return_value=True)
    device.can_deactivate = MagicMock(return_value=True)
    device.record_activated = MagicMock()
    device.record_deactivated = MagicMock()
    device.reset_surplus_timer = MagicMock()
    device.status = MagicMock()
    device.status.allocated_power_w = consumption
    device.status.state = MagicMock(value="active" if is_active else "idle")
    device.control_mode = control_mode
    device._offpeak_forced = False
    device.needs_offpeak_activation = False
    device.remaining_daily_runtime_sec = 0
    device.daily_min_runtime_sec = 0
    # (#559) goal-engine fields — pin to defaults (MagicMock auto-attrs are
    # truthy and would trip the goal gates)
    device.daily_targets_met = False
    device.daily_max_runtime_reached = False
    device.stop_condition_met = False
    device.top_up_policy = "solar_only"
    device._offpeak_forced_date = None
    device._batt_overnight_forced = False
    device._batt_overnight_forced_date = None
    device.__class__ = MagicMock
    if antiflicker_blocks:
        device.deactivate = AsyncMock()  # is_active stays True
    else:
        async def _deactivate():
            device.is_active = False
        device.deactivate = AsyncMock(side_effect=_deactivate)
    return device


# ── W7 — feedback-free true-surplus addback ──────────────────────────

class TestActiveSurplusDraw:
    def test_sums_only_active_surplus_devices(self, mock_hass):
        sc = SurplusController(mock_hass)
        sc.register_device(_make_device("a", is_active=True, consumption=1200.0))
        sc.register_device(_make_device("b", is_active=False, consumption=0.0))
        sc.register_device(_make_device("c", is_active=True, consumption=800.0))
        assert sc.active_surplus_draw_w() == 2000.0

    def test_excludes_externally_managed_ev(self, mock_hass):
        # The EV is driven by the decide/actuate path; its draw is already
        # in grid export and must NOT be re-credited.
        sc = SurplusController(mock_hass)
        sc.register_device(
            _make_device("ev", is_active=True, consumption=4000.0,
                         managed_externally=True))
        sc.register_device(_make_device("hp", is_active=True, consumption=1500.0))
        assert sc.active_surplus_draw_w() == 1500.0

    def test_zero_when_nothing_active(self, mock_hass):
        sc = SurplusController(mock_hass)
        sc.register_device(_make_device("a", is_active=False))
        assert sc.active_surplus_draw_w() == 0.0


# ── W2 — peak posture ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestPeakFreezeActivation:
    async def test_warning_blocks_new_activation(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _make_device("hp", min_power=500, is_active=False)
        sc.register_device(dev)
        # Plenty of surplus, but WARNING must not add load.
        await sc.update(3000.0, peak_state=LoadManagementState.WARNING)
        dev.activate.assert_not_called()

    async def test_normal_state_activates(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _make_device("hp", min_power=500, is_active=False)
        sc.register_device(dev)
        await sc.update(3000.0, peak_state=LoadManagementState.NORMAL)
        dev.activate.assert_called_once()

    async def test_none_state_is_legacy_behaviour(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _make_device("hp", min_power=500, is_active=False)
        sc.register_device(dev)
        await sc.update(3000.0, peak_state=None)
        dev.activate.assert_called_once()

    async def test_warning_does_not_shed_existing(self, mock_hass):
        # WARNING freezes activation but must NOT proactively shed.
        sc = SurplusController(mock_hass)
        dev = _make_device("hp", min_power=500, is_active=True, consumption=1500.0)
        sc.register_device(dev)
        await sc.update(3000.0, peak_state=LoadManagementState.WARNING)
        dev.deactivate.assert_not_called()


@pytest.mark.asyncio
class TestPeakShed:
    async def test_shedding_backs_off_one_device(self, mock_hass):
        # SHEDDING sheds gently — one device per cycle, lowest priority first.
        # The pool FUNDS both loads (#688): active draws are now debited from
        # the pool, so an unfunded load at available=0 is stopped by the
        # deficit LIFO before this pass even runs — the gentle cadence is a
        # peak-posture contract for loads that still have their surplus.
        sc = SurplusController(mock_hass)
        hi = _make_device("hp", priority=1, is_active=True, consumption=1500.0)
        lo = _make_device("boiler", priority=5, is_active=True, consumption=2000.0)
        sc.register_device(hi)
        sc.register_device(lo)
        await sc.update(3650.0, peak_state=LoadManagementState.SHEDDING)
        # Lowest priority (highest number) sheds first; the other survives.
        lo.deactivate.assert_called_once()
        hi.deactivate.assert_not_called()

    async def test_emergency_sheds_all_active(self, mock_hass):
        sc = SurplusController(mock_hass)
        a = _make_device("a", priority=1, is_active=True, consumption=1500.0)
        b = _make_device("b", priority=5, is_active=True, consumption=2000.0)
        sc.register_device(a)
        sc.register_device(b)
        await sc.update(0.0, peak_state=LoadManagementState.EMERGENCY)
        a.deactivate.assert_called_once()
        b.deactivate.assert_called_once()

    async def test_shedding_skips_peak_only_devices(self, mock_hass):
        # Only SURPLUS-mode devices are the controller's to shed; a
        # peak_only device is the load manager's responsibility.
        sc = SurplusController(mock_hass)
        po = _make_device("po", priority=5, is_active=True, consumption=2000.0,
                          control_mode=DeviceControlMode.PEAK_ONLY)
        sc.register_device(po)
        await sc.update(0.0, peak_state=LoadManagementState.EMERGENCY)
        po.deactivate.assert_not_called()

    async def test_shedding_respects_antiflicker(self, mock_hass):
        sc = SurplusController(mock_hass)
        dev = _make_device("hp", priority=5, is_active=True, consumption=2000.0,
                            antiflicker_blocks=True)
        dev.can_deactivate = MagicMock(return_value=False)
        sc.register_device(dev)
        await sc.update(0.0, peak_state=LoadManagementState.EMERGENCY)
        dev.deactivate.assert_not_called()

    async def test_peak_only_active_draw_reduces_pool_but_is_never_stopped(
            self, mock_hass):
        """(#688) An active peak_only load consumes real power: its draw is
        debited from the pool (a SURPLUS sibling can't be funded by power the
        user's own load is already using), yet the load itself stays
        user-managed — neither the deficit LIFO nor anything else stops it."""
        sc = SurplusController(mock_hass)
        po = _make_device("po", priority=1, is_active=True, consumption=2000.0,
                          control_mode=DeviceControlMode.PEAK_ONLY)
        po.adjust_power = AsyncMock(return_value=2000.0)
        s = _make_device("s", priority=5, min_power=1000, is_active=False)
        sc.register_device(po)
        sc.register_device(s)
        # pool 2450 after offset; the peak_only draw leaves 450 < 1000
        await sc.update(2500.0)
        s.activate.assert_not_called()
        po.deactivate.assert_not_called()
