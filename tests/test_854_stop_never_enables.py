"""#854 — a stop must never ENABLE the charger.

Guido, 28.08.2026, watching his own box: *"the issue is sem is even
sending commands like this, not the charger."* He was right, and it
overturned two of my diagnoses in a row.

The KEBA quota-hold stopped by *enabling*: `set_current(min)` +
`set_energy(quota)` + `enable`, so the box would charge to a satisfied
target and suspend itself. Consequences, both measured on PROD that
evening:

1. On an already-idle box that sequence is a START, not a stop. It hands
   the car the firmware's 1 kWh floor (0.3 → reads 1.0, 0.5 → 1.0) that
   nobody asked for. "Min = 0 still charges 1 kWh" was SEM's own command.
2. Alternating it with a plain disable made SEM fight itself — enable,
   disable, enable — which the reconciler reported as "the charger keeps
   restarting itself against SEM's stop". The charger was innocent:
   plugged in and disabled it drew nothing for 28 minutes, and every
   start followed a SEM enable.

A disable stops a drawing box in ~3 s and holds. The #553 idle guard
still bounds a rogue session while SEM is DOWN — and it writes a target
without ever enabling, which is the distinction that matters.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _keba_device(has=("disable", "set_energy", "enable", "set_current")):
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    d = CurrentControlDevice.__new__(CurrentControlDevice)
    d.name = "EV Charger"
    d.charger_service = "keba.set_current"
    d.stop_service = None
    d.charge_mode_entity = None
    d.charge_mode_stop = None
    d.start_stop_entity = None
    d.service_device_id = None
    d.min_current = 8
    d._idle_guard_armed = False
    d._session_active = True
    d._current_setpoint = 8.0
    d.hass = MagicMock()
    d.hass.services.has_service = MagicMock(side_effect=lambda dom, svc: svc in has)
    d.hass.services.async_call = AsyncMock()
    d._set_current = AsyncMock()
    d._box_session_kwh = MagicMock(return_value=0.0)
    d._standing_quota_kwh = MagicMock(return_value=None)
    return d


def _calls(dev):
    return [(c.args[0], c.args[1]) for c in dev.hass.services.async_call.call_args_list]


@pytest.mark.asyncio
async def test_a_stop_never_calls_enable():
    """The invariant. `enable` in a stop path is how a zero ask became
    a 1 kWh charge."""
    d = _keba_device()
    await d.stop_session()
    assert ("keba", "enable") not in _calls(d), (
        "a stop that enables is a start — measured cost: the firmware's "
        "1 kWh floor on every plug-in against a zero ask"
    )


@pytest.mark.asyncio
async def test_a_stop_disables_the_box():
    d = _keba_device()
    await d.stop_session()
    assert ("keba", "disable") in _calls(d)


@pytest.mark.asyncio
async def test_the_stop_is_exactly_one_call():
    """Guido's automation is the specification:

        alias: Keba Disable
        actions: [ {action: keba.disable} ]

    No energy target — the #553 "idle guard" wrote 1.0 kWh, and because
    the firmware floors any non-zero target at 1.0 (measured), that guard
    IS an allowance waiting for the next enable to spend. No current
    write, no failsafe. One call."""
    d = _keba_device()
    await d.stop_session()
    assert _calls(d) == [("keba", "disable")], (
        f"a stop must be exactly keba.disable, got {_calls(d)}"
    )
    d._set_current.assert_not_awaited()
