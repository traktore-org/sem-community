"""#688 — the daily MINIMUM is a floor, not a stop.

onkelfu's pool pump (Min 8 h / Max 11.5 h / Solar only) stopped dead at 8 h with
sun still on the roof. The card had promised **"at least 8 h … up to 11.5 h"**
(``_renderGoalSlider``) and the engine could never traverse that range:
``daily_targets_met`` goes true AT the minimum and was a hard stop that
deactivated the load and ``continue``-ed it past every allocation pass. So
whenever Min > 0, **Max > Min was unreachable by construction** — dead
configuration behind a live slider.

The EV has had the right contract since #245 (``tests/test_minmax_targets.py``):

    Min = the FLOOR the PAID sources top up to (night grid / battery).
    Max = the CEILING FREE surplus may run to; unset = full = "take the sun".

The load slider was built to *mirror the EV charge-target range* — the comment
on ``_renderGoalSlider`` says so — but the backend never mirrored the semantics.
These tests pin both families to the same contract:

* reaching Min ends the **paid** sources (Tier-1 assist, Tier-2 overnight
  battery, cheap-hours grid) — it must never keep spending to overshoot a floor;
* free solar surplus carries the load on **up to Max**;
* ``daily_max_runtime_reached`` stays the hard stop (#620, live-proven on the
  Heizband) and still stops a RUNNING load (bug-class 17).
"""
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController, compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode, SwitchDevice,
)

from .test_620_device_goal_model import _mock


@pytest.fixture
def mock_hass():
    return MagicMock()


def _intent_dev(**kw):
    """Plain stub for the pure decision function (no MagicMock truthiness)."""
    d = MagicMock()
    d.control_mode = DeviceControlMode.SURPLUS
    d.is_active = kw.get("is_active", False)
    d.get_current_consumption = MagicMock(return_value=kw.get("draw", 0.0))
    d.rated_power = kw.get("rated_power", 800.0)
    d.min_power_threshold = kw.get("min_power", 800.0)
    d.daily_max_runtime_reached = kw.get("max_reached", False)
    d.daily_targets_met = kw.get("targets_met", False)
    d.stop_condition_met = False
    d.is_deadline_approaching = False
    d.has_runtime_deficit = kw.get("deficit", False)
    d.battery_eligible_overnight = kw.get("overnight", False)
    d.top_up_policy = kw.get("top_up_policy", "solar_only")
    d._sem_owned = True
    return d


# ── the property itself is honest — it means "floor reached", nothing more ──

class TestFloorSignal:
    def test_targets_met_at_the_minimum(self):
        d = SwitchDevice(hass=MagicMock(), device_id="pump", name="Pool Pump",
                         rated_power=800, priority=5, entity_id="switch.pump")
        d.daily_min_runtime_sec = 8 * 3600
        d._daily_runtime_accumulated_sec = 8 * 3600
        assert d.daily_targets_met is True
        # …and the load is NOT capped — the ceiling is still 3.5 h away.
        d.daily_max_runtime_sec = int(11.5 * 3600)
        assert d.daily_max_runtime_reached is False
        assert d.can_activate() is True


# ── the pure decision function (desired-state path) ────────────────────────

class TestIntentFloorCeiling:
    def test_free_surplus_carries_past_the_floor(self):
        """onkelfu's 17:00: Min met, sun still there, Max not reached → RUN."""
        i = compute_load_intent(_intent_dev(targets_met=True),
                                remaining_surplus_w=5000.0)
        assert i.on is True
        assert i.source == "solar"

    def test_running_load_is_not_stopped_at_the_floor(self):
        i = compute_load_intent(_intent_dev(targets_met=True, is_active=True,
                                            draw=800.0),
                                remaining_surplus_w=5000.0)
        assert i.on is True

    def test_ceiling_is_the_hard_stop(self):
        i = compute_load_intent(_intent_dev(targets_met=True, max_reached=True,
                                            is_active=True, draw=800.0),
                                remaining_surplus_w=5000.0)
        assert i.on is False
        assert "cap" in i.reason

    def test_battery_assist_stands_down_at_the_floor(self):
        """Tier-1 assist is the battery paying to run the load. Past the floor
        there is nothing left to guarantee — free surplus only."""
        i = compute_load_intent(_intent_dev(targets_met=True),
                                remaining_surplus_w=100.0,
                                tier1_headroom_w=3000.0)
        assert i.on is False, "battery must not push a load past its own floor"

    def test_battery_assist_still_works_below_the_floor(self):
        """Inertness guard — the #620 behaviour below the floor is untouched."""
        i = compute_load_intent(_intent_dev(targets_met=False),
                                remaining_surplus_w=100.0,
                                tier1_headroom_w=3000.0)
        assert i.on is True
        assert i.source == "tier1_battery"

    def test_no_surplus_past_the_floor_means_off(self):
        i = compute_load_intent(_intent_dev(targets_met=True),
                                remaining_surplus_w=0.0)
        assert i.on is False

    @pytest.mark.parametrize("kw,label", [
        ({"overnight": True}, "tier2 overnight battery"),
        ({"top_up_policy": "cheap_hours"}, "cheap-hours grid"),
    ])
    def test_paid_night_sources_stand_down_at_the_floor(self, kw, label):
        """No deficit past the floor → the paid night sources have nothing to
        finish. Pinned explicitly so a later refactor can't reopen them."""
        i = compute_load_intent(
            _intent_dev(targets_met=True, deficit=False, **kw),
            remaining_surplus_w=0.0, price_is_cheap=True,
            soc_above_reserve=True, is_night=True)
        assert i.on is False, f"{label} must not run past the floor"


# ── the live controller (imperative path) ─────────────────────────────────

@pytest.mark.asyncio
class TestControllerFloorCeiling:
    async def test_min_met_keeps_running_on_surplus(self, mock_hass):
        """THE #688 REGRESSION: 5 kW of sun and the pump gets switched off."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True)
        d.get_current_consumption = MagicMock(return_value=800.0)
        d.daily_targets_met = True
        sc.register_device(d)
        await sc.update(available_power_w=5000.0)
        d.deactivate.assert_not_awaited()

    async def test_min_met_may_restart_on_surplus(self, mock_hass):
        """A cloud stopped it at 8 h; the sun comes back before Max."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=False)
        d.daily_targets_met = True
        sc.register_device(d)
        await sc.update(available_power_w=5000.0)
        d.activate.assert_called_once()
        d.deactivate.assert_not_awaited()

    async def test_max_cap_still_stops_a_running_load(self, mock_hass):
        """#620 regression guard — the ceiling keeps its teeth."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True)
        d.get_current_consumption = MagicMock(return_value=800.0)
        d.daily_targets_met = True
        d.daily_max_runtime_reached = True
        sc.register_device(d)
        await sc.update(available_power_w=5000.0)
        d.deactivate.assert_awaited()

    async def test_min_met_zeroes_tier1_headroom(self, mock_hass):
        sc = SurplusController(mock_hass)
        sc._batt_soc = 90
        sc._batt_buffer_soc = 70
        sc._batt_assist_budget_w = 3000.0
        sc._tier1_budget_left = 3000.0
        d = _mock(battery_assist_enabled=True)
        d.daily_targets_met = True
        assert sc._tier1_headroom_w(d) == 0.0
        d.daily_targets_met = False
        assert sc._tier1_headroom_w(d) == 3000.0

    async def test_min_met_ends_the_overnight_battery_run(self, mock_hass):
        """Tier-2 is EXEMPT from the deficit LIFO (it runs without surplus by
        design), so reaching the floor must end it explicitly — otherwise the
        load drains the battery past its own target all night (class 18)."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, battery_eligible_overnight=True,
                  _batt_overnight_forced=True)
        d.get_current_consumption = MagicMock(return_value=800.0)
        d.daily_targets_met = True
        sc.register_device(d)
        await sc.update(available_power_w=0.0, price_level="normal",
                        battery_soc=90, battery_reserve_soc=20)
        d.deactivate.assert_awaited()
        assert d._batt_overnight_forced is False

    async def test_min_met_ends_the_cheap_grid_run(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True)
        d.get_current_consumption = MagicMock(return_value=800.0)
        d.top_up_policy = "cheap_hours"
        d._offpeak_forced = True
        d.daily_targets_met = True
        sc.register_device(d)
        await sc.update(available_power_w=0.0, price_level="cheap")
        d.deactivate.assert_awaited()
        assert d._offpeak_forced is False


@pytest.mark.unit
class TestTodaysPlanHonesty:
    """(#688) The plan row must not call a still-running load "done".

    ``_device_run_rows`` used ``daily_targets_met`` as its whole definition of
    done-for-the-day. That was true when the floor WAS the stop; now a load can
    be past its Min and audibly running on surplus, so "done" needs the ceiling
    (or a floor met with the load already off).
    """

    def _coord(self, *devices):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c._surplus_controller = MagicMock()
        c._surplus_controller.get_devices_sorted = MagicMock(return_value=list(devices))
        return c

    def _dev(self, **kw):
        d = MagicMock()
        d.name = "Pool pump"
        d.is_ev = False
        d.control_mode = DeviceControlMode.SURPLUS
        d.daily_targets_met = False
        d.daily_max_runtime_reached = False
        d.stop_condition_met = False
        d.is_active = False
        for k, v in kw.items():
            setattr(d, k, v)
        return d

    def test_past_floor_and_still_running_is_not_done(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 7, 29, 14, 0)
        coord = self._coord(self._dev(daily_targets_met=True, is_active=True))
        rows = coord._device_run_rows(now, (now + timedelta(hours=2)).isoformat())
        assert len(rows) == 1
        assert rows[0]["done"] is False, (
            "the pump is running on surplus between Min and Max — Today's Plan "
            "must not say it's done (#688)")
        assert rows[0]["when"] == now

    def test_cap_reached_is_done(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 7, 29, 14, 0)
        coord = self._coord(self._dev(daily_max_runtime_reached=True))
        rows = coord._device_run_rows(now, (now + timedelta(hours=2)).isoformat())
        assert rows[0]["done"] is True

    def test_floor_met_and_off_is_done(self):
        """No cap set, load already off — it accrued its target and stopped."""
        from datetime import datetime, timedelta
        now = datetime(2026, 7, 29, 14, 0)
        coord = self._coord(self._dev(daily_targets_met=True, is_active=False))
        rows = coord._device_run_rows(now, (now + timedelta(hours=2)).isoformat())
        assert rows[0]["done"] is True
