"""#688 (the remaining half) — the start reserve: begin only with margin.

onkelfu's ask: a 600 W pool pump should start only when ~800 W is
available, so the start itself (plus the next passing cloud) doesn't
immediately flip the surplus negative and cycle the pump. min-on/min-off
already shipped via the packer's quantization; this is the START gate:

* ``start_reserve_w`` — extra watts required ON TOP of the device's
  threshold, for STARTS only. A running load keeps the plain threshold
  (the reserve must never stop a healthy run — that would CREATE the
  cycling it exists to prevent).
* settable through the same goal surface as every #620 knob
  (update_device_config / register), default 0 = today's behaviour.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
)


def _dev(*, active=False, reserve=200.0):
    dev = MagicMock()
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.is_active = active
    dev.get_current_consumption = MagicMock(return_value=600.0 if active else 0.0)
    dev.rated_power = 600.0
    dev.min_power_threshold = 600.0
    dev.start_reserve_w = reserve
    dev.has_runtime_deficit = False
    dev.daily_max_runtime_reached = False
    dev.stop_condition_met = False
    dev.is_deadline_approaching = False
    dev.daily_targets_met = False
    dev.battery_eligible_overnight = False
    dev.top_up_policy = "solar_only"
    dev.comfort_state = "disengaged"
    return dev


@pytest.mark.unit
class TestTheStartReserve:
    def test_a_start_needs_threshold_plus_reserve(self):
        intent = compute_load_intent(
            _dev(), remaining_surplus_w=700.0, is_night=False)
        assert intent.on is False  # 700 < 600 + 200

    def test_enough_margin_starts(self):
        intent = compute_load_intent(
            _dev(), remaining_surplus_w=850.0, is_night=False)
        assert intent.on is True

    def test_a_running_load_keeps_the_plain_threshold(self):
        """The reserve gates STARTS only — stopping a healthy 620 W run
        because it lacks 200 W of headroom would CREATE cycling."""
        intent = compute_load_intent(
            _dev(active=True), remaining_surplus_w=620.0, is_night=False)
        assert intent.on is True

    def test_zero_reserve_is_todays_behaviour(self):
        intent = compute_load_intent(
            _dev(reserve=0.0), remaining_surplus_w=650.0, is_night=False)
        assert intent.on is True


@pytest.mark.unit
class TestTheGoalSurfaceCarriesIt:
    def test_start_reserve_is_a_settable_goal(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        assert "start_reserve_w" in UnifiedDeviceRegistry.GOAL_PROPERTIES
