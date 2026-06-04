"""Deadline-based appliance scheduler for Solar Energy Management.

Deadline scheduling approach:
- User sets when an appliance must finish (e.g., "dishwasher done by 18:00")
- System monitors surplus and starts when sufficient solar is available
- If deadline approaches without enough solar, starts anyway (grid fallback)

Supports: Home Connect (Bosch/Siemens/Neff), or generic smart plug on/off.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

from .base import ScheduleDevice, DeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass
class ApplianceScheduleEntry:
    """A scheduled appliance run."""
    appliance_id: str
    appliance_name: str
    deadline: datetime
    estimated_runtime_minutes: int
    estimated_energy_kwh: float
    status: str = "scheduled"  # scheduled, running, completed, missed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    energy_source: str = "pending"  # solar, grid, mixed


class ApplianceScheduler:
    """Manages deadline-based scheduling for household appliances.

    Each appliance is registered as a ScheduleDevice in the SurplusController.
    The scheduler maintains a list of pending schedules and tracks completion.
    """

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._schedules: Dict[str, ApplianceScheduleEntry] = {}
        self._devices: Dict[str, ScheduleDevice] = {}
        self._history: List[ApplianceScheduleEntry] = []

        # #426 — telemetry surface mirroring the established
        # classifier_path / dampening_path / legionella_path pattern.
        # Per-device transitions are silent today; this records which
        # branch of ``update_schedules`` fired for each device.
        self._last_transitions: Dict[str, str] = {}  # device_id → path string

    def register_appliance(
        self,
        device_id: str,
        name: str,
        rated_power: float,
        entity_id: str,
        priority: int = 7,
        power_entity_id: Optional[str] = None,
    ) -> ScheduleDevice:
        """Register an appliance for scheduling."""
        device = ScheduleDevice(
            hass=self.hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            entity_id=entity_id,
            power_entity_id=power_entity_id,
        )
        self._devices[device_id] = device
        _LOGGER.info("Registered appliance for scheduling: %s", name)
        return device

    def schedule_appliance(
        self,
        device_id: str,
        deadline: datetime,
        estimated_runtime_minutes: int = 120,
        estimated_energy_kwh: float = 1.0,
    ) -> bool:
        """Schedule an appliance to run before a deadline."""
        device = self._devices.get(device_id)
        if not device:
            _LOGGER.error("Unknown appliance: %s", device_id)
            return False

        # Set the schedule on the device
        device.schedule(deadline, estimated_runtime_minutes, estimated_energy_kwh)

        # Track in our schedule list
        self._schedules[device_id] = ApplianceScheduleEntry(
            appliance_id=device_id,
            appliance_name=device.name,
            deadline=deadline,
            estimated_runtime_minutes=estimated_runtime_minutes,
            estimated_energy_kwh=estimated_energy_kwh,
        )

        _LOGGER.info(
            "Scheduled %s: deadline=%s, runtime=%dmin",
            device.name, deadline, estimated_runtime_minutes,
        )
        return True

    def cancel_schedule(self, device_id: str) -> bool:
        """Cancel a pending schedule."""
        device = self._devices.get(device_id)
        if device:
            device.clear_schedule()
        if device_id in self._schedules:
            self._schedules[device_id].status = "cancelled"
            del self._schedules[device_id]
            return True
        return False

    def update_schedules(self) -> None:
        """Update schedule statuses (called during coordinator update).

        Records the transition path per device on
        ``self._last_transitions[device_id]`` (#426):
        ``no_op`` / ``scheduled_to_running`` /
        ``running_completed_by_runtime`` /
        ``running_completed_by_low_consumption`` /
        ``running_too_short_skip`` /
        ``scheduled_to_missed`` / ``device_missing``.
        """
        now = datetime.now()
        for device_id, schedule in list(self._schedules.items()):
            device = self._devices.get(device_id)
            if not device:
                self._last_transitions[device_id] = "device_missing"
                continue

            fired = False

            # Check if device started
            if device._started and schedule.status == "scheduled":
                schedule.status = "running"
                schedule.started_at = now
                _LOGGER.info("Appliance %s started running", schedule.appliance_name)
                self._last_transitions[device_id] = "scheduled_to_running"
                fired = True

            # Check if device finished (started and no longer consuming)
            if schedule.status == "running" and schedule.started_at:
                elapsed = (now - schedule.started_at).total_seconds() / 60
                consumption = device.get_current_consumption()
                runtime_reached = elapsed >= schedule.estimated_runtime_minutes
                low_consumption = consumption < 10
                if runtime_reached or low_consumption:
                    if elapsed >= 5:  # At least 5 minutes run time
                        schedule.status = "completed"
                        schedule.completed_at = now
                        self._history.append(schedule)
                        del self._schedules[device_id]
                        device.clear_schedule()
                        _LOGGER.info(
                            "Appliance %s completed (ran %.0f min)",
                            schedule.appliance_name, elapsed,
                        )
                        # Both branches can satisfy the outer if. Record
                        # the dominant signal so users can tell whether a
                        # short cycle (low_consumption) or a long one
                        # (runtime_reached) ended the run.
                        if runtime_reached:
                            self._last_transitions[device_id] = "running_completed_by_runtime"
                        else:
                            self._last_transitions[device_id] = "running_completed_by_low_consumption"
                        fired = True
                    elif not fired:
                        # Silent-failure surface — appliance "completed"
                        # after < 5 min is treated as a transient power
                        # blip and SKIPPED here. The 5-minute floor is a
                        # heuristic; on a fast-cycle appliance this
                        # branch could fire repeatedly and the run would
                        # never close. Telemetry exposes the case so
                        # users can spot it.
                        #
                        # Gated on ``not fired`` so this never overwrites
                        # an earlier ``scheduled_to_running`` from this
                        # same cycle — both transitions fire on the very
                        # first ``update_schedules`` after device start.
                        self._last_transitions[device_id] = "running_too_short_skip"
                        fired = True

            # Check for missed deadlines (not started, past deadline)
            if schedule.status == "scheduled" and now > schedule.deadline:
                schedule.status = "missed"
                self._history.append(schedule)
                del self._schedules[device_id]
                device.clear_schedule()
                _LOGGER.warning(
                    "Appliance %s missed deadline %s",
                    schedule.appliance_name, schedule.deadline,
                )
                self._last_transitions[device_id] = "scheduled_to_missed"
                fired = True

            if not fired:
                self._last_transitions[device_id] = "no_op"

    def get_pending_schedules(self) -> List[ApplianceScheduleEntry]:
        """Get all pending schedules."""
        return list(self._schedules.values())

    def get_next_scheduled(self) -> Optional[ApplianceScheduleEntry]:
        """Get the next scheduled appliance by deadline."""
        pending = self.get_pending_schedules()
        if not pending:
            return None
        return min(pending, key=lambda s: s.deadline)

    def get_schedule_summary(self) -> Dict[str, Any]:
        """Get summary for sensor attributes."""
        pending = self.get_pending_schedules()
        next_sched = self.get_next_scheduled()
        return {
            "scheduled_appliances": len(pending),
            "schedules": [
                {
                    "name": s.appliance_name,
                    "deadline": s.deadline.isoformat(),
                    "status": s.status,
                    "runtime_min": s.estimated_runtime_minutes,
                    "energy_kwh": s.estimated_energy_kwh,
                }
                for s in pending
            ],
            "next_appliance": next_sched.appliance_name if next_sched else None,
            "next_deadline": next_sched.deadline.isoformat() if next_sched else None,
            "completed_today": sum(
                1 for h in self._history
                if h.status == "completed"
                and h.completed_at
                and h.completed_at.date() == datetime.now().date()
            ),
            # #426 — per-device transition paths from the last
            # ``update_schedules`` call. Surfaces silent state changes.
            "appliance_transitions": dict(self._last_transitions),
            "appliance_missed_today": sum(
                1 for h in self._history
                if h.status == "missed"
                and h.deadline.date() == datetime.now().date()
            ),
        }
