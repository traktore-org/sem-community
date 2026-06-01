"""Regression tests for #353 — solar mode must stop a self-charging KEBA.

PROD 2026-06-01 ~17:30 UTC: in ``charge_mode=solar_only`` with declining
afternoon sun, SEM correctly determined surplus dropped below the 6 A
min threshold and commanded 0 A on the KEBA. KEBA P30 firmware rejects
``set_current`` values below its 6 A IEC 61851 minimum and silently
retains the last valid setpoint (10 A). The car kept drawing 6830 W
from grid + battery while SEM's commanded_current sensor reported 0.

The #315/#346 self-resume guard at the actuator's TERMINAL branch
only fires for ``charging_strategy ∈ {"disabled","idle"}``. Solar
mode with sub-threshold surplus is a different strategy state but
the same physical outcome — KEBA self-charging while SEM thinks it
stopped.

Fix mirrors the #315/#346 logic in the solar-charging "disable delay
expired" branch: if ``this_power_w > 500`` (past handshake idle band)
after commanding 0 A, call ``stop_session()`` to invoke the brand-
specific disable (``keba.disable``).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.consts.states import (
    ChargingState,
)
from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingContext,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


def _make_device(session_active=False, current_setpoint=10):
    dev = MagicMock()
    dev.device_id = "keba"
    dev.name = "EV Charger"
    dev.max_current = 32
    dev.min_current = 6
    dev.phases = 3
    dev.voltage = 230
    dev._session_active = session_active
    dev._current_setpoint = current_setpoint
    dev.min_power_threshold = 4140  # 6A × 3 × 230V
    dev.managed_externally = False
    dev._set_current = AsyncMock()
    dev.start_session = AsyncMock()
    dev.stop_session = AsyncMock()
    dev.check_phase_switch = AsyncMock()
    return dev


def _build_coordinator(charge_mode="solar_only"):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {
        "ev_chargers": [{
            "id": "keba", "ev_min_current": 6,
            "charge_mode": charge_mode,
        }],
        "ev_max_current": 32,
        "ev_enable_delay_seconds": 60,
        "ev_disable_delay_seconds": 300,
        "ev_ramp_rate_amps": 2,
        "target_peak_limit": 6.0,
    }
    coord._load_manager = None
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=False)
    coord.hass = MagicMock()
    coord._ev_enable_surplus_since = None
    coord._ev_charge_started_at = None
    coord._ev_last_change_time = None
    coord._current_charger_budget = None
    coord._cycle_ev_budget = MagicMock(net_w=2000.0)  # below 4140 W threshold
    coord._this_charger_power = MagicMock()
    coord._this_charger_drawing_power = MagicMock()
    coord._apply_ramp_limit = lambda x: x
    coord._should_reenable_charger = MagicMock(return_value=False)
    coord._off_mode_stop_logged_for = None
    return coord


class TestSolarModeKebaSelfCharge:
    """When KEBA ignores the 0 A command and keeps drawing power in
    solar mode, the actuator must call stop_session() to disable the
    contactor — same pattern as #315/#346 for the terminal branch."""

    @pytest.mark.asyncio
    async def test_solar_mode_self_charge_calls_stop_session(self):
        """The #353 PROD scenario: solar surplus below threshold,
        KEBA still drawing 6.8 kW. SEM commanded 0 A but firmware
        kept the last 10 A setpoint."""
        coord = _build_coordinator()
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        # Charger is drawing 6.8 kW despite SEM's intent
        coord._this_charger_power = MagicMock(return_value=6830.0)
        coord._this_charger_drawing_power = MagicMock(return_value=True)
        # _ev_charge_started_at is past disable_delay — old enough
        # that the time-based "hold at min" branch is skipped
        from homeassistant.util import dt as dt_util
        now = dt_util.now().timestamp()
        coord._ev_charge_started_at = now - 400  # > 300s disable_delay

        ctx = ChargingContext(
            ev_connected=True, charging_strategy="solar_only",
            charging_strategy_reason="solar mode active",
        )
        power = PowerReadings(
            ev_connected=True, ev_power=6830.0,
            solar_power=4414.0, home_consumption_power=1090.0,
        )

        await coord._execute_ev_control(
            ChargingState.SOLAR_CHARGING_ACTIVE, power, MagicMock(), ctx,
        )

        # SEM commanded 0 A
        assert dev._set_current.await_args_list
        last_set_current_args = dev._set_current.await_args_list[-1].args
        assert last_set_current_args[0] == 0

        # …AND called stop_session() because the charger is still
        # drawing real power (>500 W).
        dev.stop_session.assert_awaited()

    @pytest.mark.asyncio
    async def test_solar_mode_handshake_only_no_stop(self):
        """KEBA at handshake idle (110 W, no real charging) doesn't
        trigger the override — the 500 W threshold matches the
        existing #315/#346 cutoff so we don't spam stop_session
        every cycle when the EV is plugged but parked."""
        coord = _build_coordinator()
        dev = _make_device(session_active=False, current_setpoint=0)
        coord._ev_device = dev
        coord._this_charger_power = MagicMock(return_value=110.0)
        from homeassistant.util import dt as dt_util
        now = dt_util.now().timestamp()
        coord._ev_charge_started_at = now - 400

        ctx = ChargingContext(
            ev_connected=True, charging_strategy="solar_only",
        )
        power = PowerReadings(ev_connected=True, ev_power=110.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_CHARGING_ACTIVE, power, MagicMock(), ctx,
        )

        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_solar_mode_disable_delay_active_holds_min(self):
        """Within the disable_delay window, the actuator holds at
        min_current — does NOT call stop_session yet. Pin the
        existing behaviour so the #353 guard only fires after the
        delay expires."""
        coord = _build_coordinator()
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        coord._this_charger_power = MagicMock(return_value=6830.0)
        from homeassistant.util import dt as dt_util
        now = dt_util.now().timestamp()
        # Started 100 s ago — well within 300 s disable_delay
        coord._ev_charge_started_at = now - 100

        ctx = ChargingContext(
            ev_connected=True, charging_strategy="solar_only",
        )
        power = PowerReadings(ev_connected=True, ev_power=6830.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_CHARGING_ACTIVE, power, MagicMock(), ctx,
        )

        # Held at min_current (6 A), not 0.
        dev._set_current.assert_awaited_with(6)
        # No stop_session — still within the disable_delay
        dev.stop_session.assert_not_awaited()
