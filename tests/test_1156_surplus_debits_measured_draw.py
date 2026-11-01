"""#1156 — surplus allocation debits the measured draw, not rated_power.

An active surplus load with a readable power sensor was still charged at
``rated_power`` while running. When the appliance throttles itself
(thermostat, internal controller) the meter reads less, but the walk kept
reserving the full rating — so a lower-priority load never saw the freed
surplus and it was exported instead.

Fixed at the four ``compute_load_intent`` return sites that keep an
already-active device on an existing source, and at the matching
``adjust_power`` branch on every ``ControllableDevice`` subclass that only
starts/stops (switch, climate, setpoint, schedule) — a currently-active
device now reports ``get_current_consumption()``; a fresh start still
claims the full ``rated_power``, since there is nothing to measure yet.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
)


def _load(*, active, rated=2000.0, measured=None):
    """A plain surplus load, gated through every early clause so the walk
    reaches the "solar" run reason (compute_load_intent's clause 4)."""
    d = MagicMock()
    d.control_mode = DeviceControlMode.SURPLUS
    d.is_active = active
    d.rated_power = rated
    d.min_power_threshold = rated
    d.get_current_consumption = MagicMock(
        return_value=measured if measured is not None else rated)
    d.locked_by_operator = False
    d.is_shed_target = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.runs_without_surplus = False
    d.is_deadline_approaching = False
    d.daily_targets_met = False
    d.has_runtime_deficit = False
    d.battery_eligible_overnight = False
    d.top_up_policy = "solar_only"
    d.comfort_state = ""
    d.start_reserve_w = 0.0
    d._batt_overnight_forced = False
    d._offpeak_forced = False
    return d


@pytest.mark.unit
class TestAnActiveLoadClaimsWhatItDraws:
    def test_self_throttled_load_frees_the_difference(self):
        """The appliance's own thermostat cut its draw to 500 W; the walk
        must debit 500 W, not the 2000 W rating, so the next load sees the
        freed 1500 W as real surplus."""
        dev = _load(active=True, rated=2000.0, measured=500.0)
        intent = compute_load_intent(
            dev, remaining_surplus_w=2500.0, is_night=False)
        assert intent.on is True
        assert intent.power_w == 500.0

    def test_full_draw_is_unchanged(self):
        dev = _load(active=True, rated=2000.0, measured=2000.0)
        intent = compute_load_intent(
            dev, remaining_surplus_w=2500.0, is_night=False)
        assert intent.power_w == 2000.0

    def test_unmetered_load_still_claims_the_rating(self):
        """No power sensor: get_current_consumption() falls back to the
        seeded rated_power (devices/base.py activate()), so this is
        byte-identical to before the fix."""
        dev = _load(active=True, rated=2000.0, measured=None)
        intent = compute_load_intent(
            dev, remaining_surplus_w=2500.0, is_night=False)
        assert intent.power_w == 2000.0


@pytest.mark.unit
class TestAFreshStartStillClaimsTheRating:
    def test_a_device_not_yet_running_reserves_its_full_rating(self):
        """Nothing to measure yet — a fresh start must reserve the whole
        rating, not 0 W, or it would never clear the start bar."""
        dev = _load(active=False, rated=2000.0)
        intent = compute_load_intent(
            dev, remaining_surplus_w=2500.0, is_night=False)
        assert intent.on is True
        assert intent.power_w == 2000.0
