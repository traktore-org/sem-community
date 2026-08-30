"""#855 — observer mode must RUN the brand path, not cut above it.

Found live on .46 on 30.08.2026 during the 2.1 pre-release campaign, and
fixed at Guido's word ("Please fix withheld_commands"). Observer mode was
ON, a charger's ``would_decisions`` entry said ``charge_at_amps 13A``
against a hardware reading of 32 A — and ``withheld_commands`` was ``{}``.

The seam in ``ControllableDevice.send`` was correct and its docstring
stated the intent plainly:

    "With the cut HERE, observer mode runs the whole decision and brand
     path and withholds only the send — recording exactly what it withheld."

But ``actuate()`` still returned on ``observer`` BEFORE
``reconcile_and_apply``, so no adapter command was ever issued, nothing
reached ``send``, and the withheld list stayed empty. The coordinator's own
comment named it: "masked today by actuate()'s older decision-level gate,
which is exactly the gate #855 wants to retire." It had not been retired.

The consequence is the exact blindness #855 was filed to remove: a brand
"stop" that is really a current write + an energy target + an ENABLE
(#854) is invisible while the cut sits above the adapter. The WOULD
surface reported the DECISION and never the COMMANDS.

Two things must hold together, and the second is why the gate could not
simply be deleted:

1. the brand path runs and every service call it would make is recorded;
2. SEM must still publish "not commanding" — ``_current_setpoint`` stays
   0 in observer mode (#536: HA-TEST's KEBA bridge automation drove the
   REAL charger off a stale setpoint). A withheld send is not a write, so
   it may not claim a setpoint or refresh the #392 write heartbeat.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _observer_device(**kwargs):
    """A REAL device, constructed — a bare ``__new__`` stub grows an
    attribute per code path and stops testing the thing under test."""
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    defaults = dict(hass=hass, device_id="ev_charger", name="EV Charger",
                    min_current=6.0, max_current=32.0, phases=3)
    defaults.update(kwargs)
    d = CurrentControlDevice(**defaults)
    d.observer_mode = True
    d.withheld_commands = []
    return d


class TestActuateReachesTheSeam:
    @pytest.mark.asyncio
    async def test_observer_does_not_short_circuit_before_the_reconciler(self):
        """The gate the coordinator comment says #855 wants retired."""
        from custom_components.solar_energy_management.coordinator import actuate as _act

        reconciler = MagicMock()
        reconciler.reconcile_and_apply = AsyncMock()
        adapter = MagicMock()
        adapter.phases, adapter.voltage, adapter.max_current_a = 3, 230.0, 32
        decision = MagicMock()
        decision.charger_id = "keba_1"
        decision.intent.value = "charge_at_amps"
        decision.commanded_amps = 13
        decision.mode = "always_max"
        decision.reason = "always_max mode"
        power = MagicMock()

        await _act.actuate(decision, adapter, power, reconciler,
                           observer=True, controller=None)

        reconciler.reconcile_and_apply.assert_awaited(), (
            "observer mode must run the brand path — the seam in "
            "ControllableDevice.send is what withholds, not an early "
            "return in actuate(). Otherwise withheld_commands is always "
            "empty and #854's hidden enable stays invisible."
        )


class TestAWithheldSendIsNotAWrite:
    @pytest.mark.asyncio
    async def test_the_command_is_recorded(self):
        d = _observer_device()
        sent = await d.send("number", "set_value",
                            {"entity_id": "number.charger", "value": 13})
        assert sent is False
        assert d.withheld_commands == [
            {"service": "number.set_value",
             "data": {"entity_id": "number.charger", "value": 13},
             "why": "-"}
        ]
        d.hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_observer_never_claims_a_setpoint(self):
        """#536: an external bridge automation reads commanded_current.
        In observer mode SEM commanded nothing, so the setpoint stays 0 —
        the coordinator zeroes it early in the cycle and the charger loop
        must not put it back."""
        d = _observer_device(current_entity_id="number.charger")
        d._current_setpoint = 0.0
        d._last_write_at = 0.0

        await d._set_current(13)

        assert d._current_setpoint == 0.0, (
            "a withheld send is not a write — publishing the WOULD value as "
            "commanded_current is exactly the stale-setpoint path that drove "
            "the real KEBA in #536"
        )
        assert d._last_write_at == 0.0, (
            "the #392 write heartbeat must not advance on a command that "
            "never left the process"
        )
        assert d.withheld_commands, "…but the command must still be recorded"
