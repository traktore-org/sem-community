"""#653 — the appliance scheduler's lifecycle half is wired to the cycle.

``schedule_appliance`` registered a ``ScheduleDevice`` with the surplus
controller and the deadline force-start worked. ``update_schedules`` — the
half that moves a run scheduled → running → completed and calls
``clear_schedule`` — had **zero production callers**. Its docstring said
"called during coordinator update"; nothing called it.

That is not a cosmetic status bug. ``ScheduleDevice`` deliberately refuses to
``deactivate()`` while ``_started`` (an appliance mid-cycle must not be cut),
and ``adjust_power`` returns ``rated_power`` unconditionally while
``_started``. With nothing ever clearing the flag, a dishwasher that finished
at 15:00 held its full rated allocation against every lower-priority load for
the rest of the day — and LIFO shed and peak shed could not take it back
either. Only a restart cleared it.

Meta-class: **spec-vs-reality gap** (designed-but-unwired half-feature) from
``docs/BUG_CLASSES.md``. The #426 telemetry shipped to observe transitions
that were unreachable, and its tests passed by calling ``update_schedules``
directly — proving the method works, never that anything runs it.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.appliance_scheduler import (
    ApplianceScheduler,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states.get.return_value = None
    return h


def _scheduled(hass, runtime_minutes: int = 60):
    """A registered, scheduled dishwasher."""
    s = ApplianceScheduler(hass)
    device = s.register_appliance(
        "dishwasher", "Dishwasher", 2000.0, "switch.dishwasher",
    )
    s.schedule_appliance(
        "dishwasher",
        datetime.now() + timedelta(hours=4),
        estimated_runtime_minutes=runtime_minutes,
    )
    return s, device


@pytest.mark.unit
class TestTheCycleTicksTheScheduler653:
    """The wiring itself — the part that was missing."""

    def test_the_coordinator_calls_update_schedules(self):
        """Static guard on the call site.

        Written as a source assertion on purpose: the behavioural tests
        below can all pass while nothing runs the tick, which is precisely
        the state this issue found. Something has to assert the EDGE.
        """
        src = (_ROOT / "coordinator" / "coordinator.py").read_text()
        assert "self._tick_appliance_scheduler()" in src, (
            "the appliance scheduler tick is no longer called from the "
            "coordinator cycle — #653 regressed"
        )
        assert "scheduler.update_schedules()" in src

    def test_the_tick_runs_before_allocation(self):
        """Order matters: a run that completed this cycle must have
        released its claim before the surplus controller allocates, or the
        phantom allocation survives one more cycle every time."""
        src = (_ROOT / "coordinator" / "coordinator.py").read_text()
        tick = src.index("self._tick_appliance_scheduler()")
        allocate = src.index("allocation = await self._surplus_controller.update(")
        assert tick < allocate

    def test_the_tick_is_a_noop_without_a_scheduler(self):
        """The scheduler is lazily created by the service, so on almost
        every install this must cost one getattr and do nothing."""
        from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E501
            SEMCoordinator,
        )

        coord = MagicMock(spec=SEMCoordinator)
        # No ``_appliance_scheduler`` attribute at all.
        del coord._appliance_scheduler
        SEMCoordinator._tick_appliance_scheduler(coord)  # must not raise

    def test_a_scheduler_fault_does_not_kill_the_cycle(self):
        """This cycle also publishes every sensor in the integration."""
        from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E501
            SEMCoordinator,
        )

        coord = MagicMock()
        coord._appliance_scheduler.update_schedules.side_effect = RuntimeError("boom")
        SEMCoordinator._tick_appliance_scheduler(coord)  # must not raise


@pytest.mark.unit
class TestAFinishedApplianceReleasesItsClaim653:
    """The user-visible consequence of the missing tick."""

    @pytest.mark.asyncio
    async def test_a_completed_run_stops_allocating_rated_power(self, hass):
        s, device = _scheduled(hass, runtime_minutes=10)

        await device.activate(2000.0)
        assert device._started
        # Mid-run it holds its allocation — correct, don't cut a dishwasher.
        assert await device.adjust_power(0.0) == 2000.0

        # Run it past its estimated runtime, then tick once.
        s._schedules["dishwasher"].status = "running"
        s._schedules["dishwasher"].started_at = datetime.now() - timedelta(minutes=15)
        device.get_current_consumption = MagicMock(return_value=0.0)
        s.update_schedules()

        assert s._last_transitions["dishwasher"].startswith("running_completed")
        assert device._started is False, "clear_schedule did not run"
        assert await device.adjust_power(0.0) == 0.0, (
            "finished appliance is still claiming its rated power"
        )

    @pytest.mark.asyncio
    async def test_a_completed_run_can_be_deactivated_again(self, hass):
        """``deactivate`` is a no-op while ``_started``. Without the tick
        that flag never cleared, so LIFO shed and peak shed could not
        reclaim the appliance's slot either."""
        s, device = _scheduled(hass, runtime_minutes=10)
        await device.activate(2000.0)

        await device.deactivate()
        assert device._status.allocated_power_w == 2000.0, "still running — correct"

        s._schedules["dishwasher"].status = "running"
        s._schedules["dishwasher"].started_at = datetime.now() - timedelta(minutes=15)
        device.get_current_consumption = MagicMock(return_value=0.0)
        s.update_schedules()

        await device.deactivate()
        assert device._status.allocated_power_w == 0.0

    def test_a_missed_deadline_also_releases_the_device(self, hass):
        s, device = _scheduled(hass)
        s._schedules["dishwasher"].deadline = datetime.now() - timedelta(minutes=1)
        device.deadline = s._schedules["dishwasher"].deadline

        s.update_schedules()

        assert s._last_transitions["dishwasher"] == "scheduled_to_missed"
        assert device.deadline is None
        assert not s.get_pending_schedules()

    def test_the_run_lands_in_history_exactly_once(self, hass):
        """A completed run is deleted from ``_schedules``, so a second tick
        must not append it again."""
        s, device = _scheduled(hass, runtime_minutes=10)
        s._schedules["dishwasher"].status = "running"
        s._schedules["dishwasher"].started_at = datetime.now() - timedelta(minutes=15)
        device.get_current_consumption = MagicMock(return_value=0.0)

        s.update_schedules()
        s.update_schedules()

        assert len(s._history) == 1


@pytest.mark.unit
class TestTheSchedulerIsReachable653:
    """``cancel_schedule`` and ``get_schedule_summary`` had no caller either."""

    def test_cancel_is_exposed_as_a_service(self):
        src = (_ROOT / "__init__.py").read_text()
        assert '"cancel_appliance_schedule"' in src
        assert "scheduler.cancel_schedule(device_id)" in src

    def test_the_cancel_service_is_documented_and_torn_down(self):
        services = (_ROOT / "services.yaml").read_text()
        assert "cancel_appliance_schedule:" in services
        # Must also be removed on unload, or a reload leaves a service
        # bound to a dead coordinator.
        src = (_ROOT / "__init__.py").read_text()
        unload = src.split("hass.services.async_remove(DOMAIN, service_name)", 1)[0]
        assert '"cancel_appliance_schedule",' in unload

    def test_cancel_clears_the_device_schedule(self, hass):
        s, device = _scheduled(hass)
        assert s.cancel_schedule("dishwasher") is True
        assert device.deadline is None
        assert not s.get_pending_schedules()

    def test_the_summary_is_published(self):
        """``get_schedule_summary`` carries the #426 transition telemetry
        and nothing read it — the observability shipped unobservable."""
        src = (_ROOT / "coordinator" / "publish_diag.py").read_text()
        assert "get_schedule_summary()" in src
        assert "diag_appliance_schedules" in src

    def test_the_summary_is_absent_on_installs_that_never_scheduled(self):
        """Conditional, not a permanent empty block: the scheduler only
        exists after the service has been called at least once."""
        tree = ast.parse((_ROOT / "coordinator" / "publish_diag.py").read_text())
        guarded = any(
            isinstance(n, ast.If)
            and "get_schedule_summary" in ast.unparse(n)
            for n in ast.walk(tree)
        )
        assert guarded

    def test_the_published_summary_has_a_reader(self):
        """Review catch. Publishing ``diag_appliance_schedules`` onto
        ``coordinator.data`` with nothing consuming it would be the exact
        defect #653 is about — telemetry that ships unobservable. The
        config-entry diagnostics dump is the reader."""
        src = (_ROOT / "diagnostics.py").read_text()
        assert 'data.get("diag_appliance_schedules")' in src


@pytest.mark.unit
class TestTheNowLiveTickCannotThrow653:
    """The tick was dead code. Making it run every ~10 s turns latent
    faults in ``update_schedules`` into live, repeating ones."""

    def test_a_template_deadline_does_not_break_the_tick(self, hass):
        """``{{ today_at('18:00') }}`` — the obvious way to write a deadline
        in an automation — is timezone-AWARE. ``update_schedules`` compares
        it against naive ``datetime.now()``, which raises TypeError. Every
        cycle. The appliance would then never complete and never release
        its allocation: #653, reinstated."""
        from homeassistant.util import dt as dt_util

        s = ApplianceScheduler(hass)
        s.register_appliance("dw", "Dishwasher", 2000.0, "switch.dw")

        aware = dt_util.now() + timedelta(hours=3)
        assert aware.tzinfo is not None, "fixture must be aware to be a test"
        # The service handler normalises before the scheduler ever sees it.
        normalised = dt_util.as_local(aware).replace(tzinfo=None)
        s.schedule_appliance("dw", normalised)

        s.update_schedules()  # must not raise
        assert s._last_transitions.get("dw") != "device_missing"

    def test_the_service_normalises_an_aware_deadline(self):
        src = (_ROOT / "__init__.py").read_text()
        assert "if deadline.tzinfo is not None:" in src
        assert "dt_util.as_local(deadline).replace(tzinfo=None)" in src

    def test_history_stays_bounded(self, hass):
        """``get_schedule_summary`` scans the whole history twice and now
        runs every cycle. Only today's entries are readable, so unbounded
        growth buys nothing and costs a growing per-cycle scan."""
        from custom_components.solar_energy_management.devices import (
            appliance_scheduler as mod,
        )

        s = ApplianceScheduler(hass)
        entry = s.register_appliance("dw", "Dishwasher", 2000.0, "switch.dw")
        assert entry is not None
        for _ in range(mod._HISTORY_LIMIT + 50):
            s._record_history(
                mod.ApplianceScheduleEntry(
                    appliance_id="dw", appliance_name="Dishwasher",
                    deadline=datetime.now(), estimated_runtime_minutes=60,
                    estimated_energy_kwh=1.0, status="completed",
                    completed_at=datetime.now(),
                )
            )
        assert len(s._history) == mod._HISTORY_LIMIT
        # Trimmed from the FRONT — today's runs must survive.
        assert s.get_schedule_summary()["completed_today"] == mod._HISTORY_LIMIT

    def test_cancelling_a_known_device_without_a_schedule_is_not_an_error(self):
        """``cancel_schedule`` clears the device's deadline and THEN returns
        False when there was no pending entry — a real state change reported
        as a failure, on exactly the path used to unstick a device."""
        src = (_ROOT / "__init__.py").read_text()
        assert "if not cancelled and not known:" in src
        assert "device_id in scheduler._devices" in src
