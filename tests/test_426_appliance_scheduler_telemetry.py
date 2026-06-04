"""#426 — telemetry surface for ApplianceScheduler.

Locks the per-device transition strings recorded on
``ApplianceScheduler._last_transitions[device_id]`` and surfaced via
``get_schedule_summary()['appliance_transitions']``. Mirrors the
#359/#416/#420/#421/#422/#424/#425 path-attribute precedents.

Silent-failure surface this captures: a fast-cycle appliance that
runs for less than 5 minutes is treated as a transient blip and
skipped. Without telemetry, the run never closes; with telemetry the
``running_too_short_skip`` path is visible.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.devices.appliance_scheduler import (
    ApplianceScheduler,
)


@pytest.fixture
def mock_hass():
    h = MagicMock()
    return h


def _seed_device(scheduler, device_id="dishwasher", power=1500.0):
    scheduler.register_appliance(
        device_id=device_id,
        name="Dishwasher",
        rated_power=power,
        entity_id=f"switch.{device_id}",
    )
    return scheduler._devices[device_id]


# ──────────────────────────────────────────────
# no_op — nothing to transition
# ──────────────────────────────────────────────


def test_transition_no_op_for_unstarted_scheduled(mock_hass):
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device._started = False
    deadline = datetime.now() + timedelta(hours=2)
    s.schedule_appliance("dishwasher", deadline)
    s.update_schedules()
    assert s.get_schedule_summary()["appliance_transitions"]["dishwasher"] == "no_op"


# ──────────────────────────────────────────────
# scheduled_to_running
# ──────────────────────────────────────────────


def test_transition_scheduled_to_running(mock_hass):
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    deadline = datetime.now() + timedelta(hours=2)
    s.schedule_appliance("dishwasher", deadline)
    # Simulate device started
    device._started = True
    s.update_schedules()
    assert s.get_schedule_summary()["appliance_transitions"]["dishwasher"] == "scheduled_to_running"
    assert s._schedules["dishwasher"].status == "running"


# ──────────────────────────────────────────────
# scheduled_to_missed
# ──────────────────────────────────────────────


def test_transition_scheduled_to_missed(mock_hass):
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device._started = False
    past_deadline = datetime.now() - timedelta(minutes=5)
    s.schedule_appliance("dishwasher", past_deadline)
    s.update_schedules()
    assert s.get_schedule_summary()["appliance_transitions"]["dishwasher"] == "scheduled_to_missed"


# ──────────────────────────────────────────────
# running_completed_by_runtime
# ──────────────────────────────────────────────


def test_transition_running_completed_by_runtime(mock_hass):
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device.get_current_consumption = MagicMock(return_value=1500.0)  # still drawing
    deadline = datetime.now() + timedelta(hours=2)
    s.schedule_appliance("dishwasher", deadline, estimated_runtime_minutes=10)
    # Mark as already running for > runtime_minutes
    schedule = s._schedules["dishwasher"]
    schedule.status = "running"
    schedule.started_at = datetime.now() - timedelta(minutes=15)
    device._started = True
    s.update_schedules()
    assert s._last_transitions["dishwasher"] == "running_completed_by_runtime"


# ──────────────────────────────────────────────
# running_completed_by_low_consumption
# ──────────────────────────────────────────────


def test_transition_completion_precedence_runtime_over_low_consumption(mock_hass):
    """Reviewer finding — when both runtime_reached AND low_consumption
    are simultaneously true, ``runtime`` wins (the primary signal).
    Lock the precedence so a future refactor can't quietly flip it."""
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device.get_current_consumption = MagicMock(return_value=2.0)  # low
    deadline = datetime.now() + timedelta(hours=2)
    s.schedule_appliance("dishwasher", deadline, estimated_runtime_minutes=10)
    schedule = s._schedules["dishwasher"]
    schedule.status = "running"
    schedule.started_at = datetime.now() - timedelta(minutes=15)  # > 10 min
    device._started = True
    s.update_schedules()
    assert s._last_transitions["dishwasher"] == "running_completed_by_runtime"


def test_transition_running_completed_by_low_consumption(mock_hass):
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device.get_current_consumption = MagicMock(return_value=2.0)  # < 10W → idle
    deadline = datetime.now() + timedelta(hours=2)
    s.schedule_appliance("dishwasher", deadline, estimated_runtime_minutes=120)
    schedule = s._schedules["dishwasher"]
    schedule.status = "running"
    schedule.started_at = datetime.now() - timedelta(minutes=8)  # > 5 min minimum
    device._started = True
    s.update_schedules()
    assert s._last_transitions["dishwasher"] == "running_completed_by_low_consumption"


# ──────────────────────────────────────────────
# running_too_short_skip — silent-failure surface
# ──────────────────────────────────────────────


def test_transition_running_too_short_skip(mock_hass):
    """Appliance ran < 5 min → completion is SKIPPED. Without telemetry
    a fast-cycle appliance would never close. The path makes it visible."""
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device.get_current_consumption = MagicMock(return_value=2.0)  # low consumption
    deadline = datetime.now() + timedelta(hours=2)
    s.schedule_appliance("dishwasher", deadline, estimated_runtime_minutes=120)
    schedule = s._schedules["dishwasher"]
    schedule.status = "running"
    schedule.started_at = datetime.now() - timedelta(minutes=2)  # < 5 min
    device._started = True
    s.update_schedules()
    assert s._last_transitions["dishwasher"] == "running_too_short_skip"
    # Schedule still exists — was not closed
    assert "dishwasher" in s._schedules


# ──────────────────────────────────────────────
# get_schedule_summary surfaces the transitions
# ──────────────────────────────────────────────


def test_summary_includes_transitions_and_missed_count(mock_hass):
    s = ApplianceScheduler(mock_hass)
    device = _seed_device(s)
    device._started = False
    past_deadline = datetime.now() - timedelta(minutes=5)
    s.schedule_appliance("dishwasher", past_deadline)
    s.update_schedules()
    summary = s.get_schedule_summary()
    assert "appliance_transitions" in summary
    assert summary["appliance_transitions"]["dishwasher"] == "scheduled_to_missed"
    assert summary["appliance_missed_today"] == 1
