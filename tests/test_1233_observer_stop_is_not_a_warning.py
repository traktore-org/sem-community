"""#1233 — observer mode sends nothing, so a charger that keeps drawing is
not "a stop that is not taking". The warning stays for a live install."""
from __future__ import annotations

import logging
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

_LOG = "custom_components.solar_energy_management.coordinator.charger_reconciler"


def _adapter(observer):
    dev = MagicMock()
    dev.observer_mode = observer
    dev.start_stop_entity = "switch.wb_enable"
    dev.charging_status_entity = "sensor.wb_status"
    dev._current_setpoint = 16
    a = MagicMock()
    a._device = dev
    a.actual_charging = lambda p: True
    a.is_self_charging = lambda p: False
    a.enable_state = lambda: (True, True)
    for name in ("command_disable", "command_enable", "command_park_off",
                 "command_set_current", "command_start"):
        setattr(a, name, AsyncMock())
    return a


async def _drive(observer, caplog, cycles=3):
    rec = ChargerReconciler(charger_id="wb", heartbeat_s=5.0)
    adapter = _adapter(observer)
    power = ChargerPower(charger_id="wb", power_w=10400.0, connected=True, charging=True)
    decision = ChargerDecision(charger_id="wb", mode="off", intent=ChargerIntent.DISABLE, reason="no plan")
    with caplog.at_level(logging.DEBUG, logger=_LOG):
        for n in range(cycles):
            await rec.reconcile_and_apply(decision, adapter, power, 100.0 + n * 10)
    return rec


@pytest.mark.asyncio
async def test_observer_mode_does_not_warn_about_a_stop(caplog):
    rec = await _drive(True, caplog)
    assert rec._stop_commanded_while_drawing >= 3
    warned = [r for r in caplog.records
              if r.levelno >= logging.WARNING and "commanded STOP" in r.getMessage()]
    assert warned == []
    assert any("would have commanded STOP" in r.getMessage() and r.levelno == logging.DEBUG
               for r in caplog.records)


@pytest.mark.asyncio
async def test_a_live_install_still_warns(caplog):
    await _drive(False, caplog)
    assert any("the stop is not taking" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records)
