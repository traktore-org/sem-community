"""#847 on the dispatch path PROD actually runs (2.1 coverage-audit finding 1).

`SurplusController._use_desired_state` is hardcoded False, so every real
install takes the LEGACY imperative path through `update()` — not the
`compute_load_intent`/`reconcile_load` path the #847 test files drive. The
legacy path carries its own copy of the commanded/adopted split (the
force-expiry pass), and until this file nothing proved it: the one test that
reaches `update()` uses a bare MagicMock, where
`getattr(device, "_sem_commanded", False)` auto-vivifies TRUTHY — it cannot
tell a commanded load from an adopted one at all.

These doubles carry real booleans. What must hold, per #847:

* Mode=Off on a load SEM STARTED (commanded): stopped exactly once, never
  stranded running.
* Mode=Off on a load SEM merely ADOPTED: released — ownership and force
  markers cleared — with ZERO writes (hoyte's case: Off means hands off).
* Mode=Off on the user's OWN load (never owned): untouched entirely.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _device(*, owned: bool, commanded: bool, active: bool = True):
    d = MagicMock()
    d.device_id = "load_1"
    d.name = "Load 1"
    d.priority = 5
    d.min_power_threshold = 800
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = active
    d.device_type = MagicMock(value="switch")

    async def _deactivate():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deactivate)
    d.activate = AsyncMock(return_value=800)
    d.adjust_power = AsyncMock(return_value=800)
    d.get_current_consumption = MagicMock(return_value=800.0 if active else 0.0)
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.control_mode = DeviceControlMode.OFF
    # REAL booleans — the whole point of this file. On the production
    # classes `_sem_commanded` is a property (`_commanded_claim AND
    # _sem_owned`), so commanded implies owned.
    d._sem_owned = owned
    d._sem_commanded = commanded and owned
    d.is_deadline_approaching = False
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d.needs_offpeak_activation = False
    d.remaining_daily_runtime_sec = 0
    d.daily_min_runtime_sec = 0
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.top_up_policy = "solar_only"
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = False
    d.stop_entity = ""
    d.stop_at = 0
    return d


@pytest.mark.asyncio
class TestModeOffOnTheLivePath:
    async def test_commanded_load_is_stopped_exactly_once(self, mock_hass):
        sc = SurplusController(mock_hass)
        assert sc._use_desired_state is False, (
            "this file exists to test the LEGACY path; if the default "
            "flipped, re-point these tests at whichever path is live"
        )
        d = _device(owned=True, commanded=True)
        sc.register_device(d)
        await sc.update(0.0)
        assert d.deactivate.await_count == 1, (
            "a SEM-started run must END on Mode=Off — not strand running"
        )
        d.record_deactivated.assert_called_once()

    async def test_adopted_load_is_released_with_zero_writes(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _device(owned=True, commanded=False)
        sc.register_device(d)
        await sc.update(0.0)
        d.deactivate.assert_not_awaited()
        d.activate.assert_not_awaited()
        d.adjust_power.assert_not_awaited()
        assert d._sem_owned is False, "the claim must be released"
        assert d.is_active is True, (
            "hoyte's case: the load the user has running stays running"
        )

    async def test_users_own_load_is_untouched(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _device(owned=False, commanded=False)
        sc.register_device(d)
        await sc.update(0.0)
        d.deactivate.assert_not_awaited()
        d.activate.assert_not_awaited()
        assert d._sem_owned is False

    async def test_second_cycle_after_release_does_nothing(self, mock_hass):
        """The release is one-shot: the next cycle sees an un-owned OFF
        device and has no business with it."""
        sc = SurplusController(mock_hass)
        d = _device(owned=True, commanded=False)
        sc.register_device(d)
        await sc.update(0.0)
        await sc.update(0.0)
        d.deactivate.assert_not_awaited()
        assert d.is_active is True


@pytest.mark.asyncio
class TestChargersAreOutsideThisLoop:
    """Audit F2: EV chargers inherit the commanded/adopted machinery AND run
    their own stop logic in ev_control.py — two mechanisms that must never
    both drive the same device. The design answer is `managed_externally`:
    every real charger creation site sets it True, and `get_devices_sorted`
    filters those out of the legacy loop entirely. This pins the filter, so
    the only way a charger gets double-driven is deleting the flag — which
    now fails here."""

    async def test_managed_externally_device_is_invisible_to_update(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _device(owned=True, commanded=True)
        d.managed_externally = True          # what both charger sites set
        sc.register_device(d)
        await sc.update(0.0)
        d.deactivate.assert_not_awaited()
        d.activate.assert_not_awaited()
        assert d._sem_owned is True, (
            "the surplus loop must not even RELEASE a charger — "
            "ev_control.py owns its whole lifecycle"
        )
