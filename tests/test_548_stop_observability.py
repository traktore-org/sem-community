"""#548 — reconciler actuation observability (stop-not-taking signal).

When SEM commands a stop but the charger keeps drawing, the reconciler must
record it (``_stop_commanded_while_drawing``) and remember its last desired
state + actions, so the diagnose service can show "SEM issued the stop but the
box ignored it" without another triage round.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ChargerReconciler,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)


def _adapter(power_w):
    dev = MagicMock()
    dev.start_stop_entity = "switch.wallbox_links_charging_enable"
    dev.charging_status_entity = "sensor.wallbox_links_status"
    dev._current_setpoint = 0
    a = MagicMock()
    a._device = dev
    a.actual_charging = MagicMock(return_value=power_w > 500)
    a.is_self_charging = MagicMock(return_value=False)
    a.enable_state = MagicMock(return_value=(True, True))
    a.max_current_a = 16
    a.command_disable = AsyncMock()
    a.command_current = AsyncMock()
    a.command_idle = AsyncMock()
    a.command_max = AsyncMock()
    a.arm_failsafe = AsyncMock()
    a.ensure_enabled = AsyncMock()
    return a


def _off():
    return ChargerDecision(charger_id="wb", mode="off", intent=ChargerIntent.DISABLE,
                           commanded_amps=0, reason="off", budget_w=0.0)


class TestStopNotTaking:
    @pytest.mark.asyncio
    async def test_counter_increments_while_drawing_against_stop(self):
        rec = ChargerReconciler(charger_id="wb", heartbeat_s=5.0)
        a = _adapter(power_w=4500)  # still drawing 4.5 kW
        for i in range(1, 4):
            await rec.reconcile_and_apply(_off(), a, ChargerPower(charger_id="wb", power_w=4500), now=float(i))
        assert rec._stop_commanded_while_drawing == 3
        assert rec._last_desired == "OFF"
        assert "DISABLE" in rec._last_actions
        a.command_disable.assert_awaited()  # SEM IS issuing the stop

    @pytest.mark.asyncio
    async def test_counter_resets_when_charger_stops(self):
        rec = ChargerReconciler(charger_id="wb", heartbeat_s=5.0)
        a = _adapter(power_w=4500)
        await rec.reconcile_and_apply(_off(), a, ChargerPower(charger_id="wb", power_w=4500), now=1.0)
        assert rec._stop_commanded_while_drawing == 1
        # charger finally stops drawing
        a.actual_charging = MagicMock(return_value=False)
        await rec.reconcile_and_apply(_off(), a, ChargerPower(charger_id="wb", power_w=0), now=2.0)
        assert rec._stop_commanded_while_drawing == 0
        assert rec._last_actions == ["NONE"]
