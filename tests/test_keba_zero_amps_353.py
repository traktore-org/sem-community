"""KEBA adapter quirk #353 — commanding < 6A must route to command_idle().

The bug:

> Solar mode: KEBA self-charges when commanded 0 A (ignores <6A
> out-of-range)

KEBA's IEC 61851 firmware silently RETAINS the last valid setpoint
when commanded a current below the 6A minimum — including 0A. This
means SEM thinks "I told the charger to stop" (it called
``keba.set_current(0)``) but KEBA keeps drawing at whatever it was
last set to. The fix (commit referenced by #353) routes any
sub-min request through ``command_idle()`` which calls
``keba.disable`` to physically open the contactor.

This file pins that contract structurally:
  1. ``command_current(0)`` MUST call ``stop_session()``, not
     ``set_current(0)``.
  2. Any sub-min ``command_current(N)`` (1..5 A) does the same.
  3. At or above 6A, ``command_current(N)`` calls ``set_current(N)``
     and DOES NOT call ``stop_session``.
  4. ``command_max()`` honours the device's ``max_current``.
  5. ``can_command_zero`` returns False (capability advertisement
     — consumers should never bypass the adapter).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters.keba import (
    KebaAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)


def _device(*, max_current: int = 16) -> MagicMock:
    """Build a mock CurrentControlDevice the KebaAdapter can drive."""
    d = MagicMock()
    d.max_current = max_current
    d.phases = 3
    d.voltage = 230
    d._session_active = True   # session already open — skip start_session
    d._set_current = AsyncMock()
    d.start_session = AsyncMock()
    d.stop_session = AsyncMock()
    return d


# ---------------------------------------------------------------------------
# #353 — sub-min currents MUST NOT pass through set_current
# ---------------------------------------------------------------------------


class Test353SubMinRoutesToIdle:
    """The headline #353 contract: KEBA never sees ``set_current(0..5)``."""

    @pytest.mark.asyncio
    async def test_command_current_zero_calls_stop_session(self) -> None:
        device = _device()
        adapter = KebaAdapter(device)

        await adapter.command_current(0)

        # The whole point: stop_session was called, set_current was NOT.
        device.stop_session.assert_awaited_once()
        device._set_current.assert_not_called()
        # Intent recorded as IDLE.
        assert adapter._last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sub_min", [1, 2, 3, 4, 5])
    async def test_command_current_below_6a_calls_stop_session(
        self, sub_min: int
    ) -> None:
        """Any value < 6A routes through command_idle. KEBA's
        IEC 61851 minimum is 6A; anything below is silently rejected
        by the firmware → self-charge regression."""
        device = _device()
        adapter = KebaAdapter(device)

        await adapter.command_current(sub_min)

        device.stop_session.assert_awaited_once()
        device._set_current.assert_not_called()
        assert adapter._last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    async def test_command_current_exactly_6a_uses_set_current(self) -> None:
        """At the IEC 61851 minimum the adapter sends a real command."""
        device = _device()
        adapter = KebaAdapter(device)

        await adapter.command_current(6)

        device._set_current.assert_awaited_once_with(6)
        device.stop_session.assert_not_called()
        assert adapter._last_intent is ChargerIntent.CHARGE_AT_AMPS

    @pytest.mark.asyncio
    @pytest.mark.parametrize("amps", [6, 7, 10, 14, 16])
    async def test_command_current_at_or_above_min_passes_through(
        self, amps: int
    ) -> None:
        device = _device()
        adapter = KebaAdapter(device)

        await adapter.command_current(amps)

        device._set_current.assert_awaited_once_with(amps)
        device.stop_session.assert_not_called()


# ---------------------------------------------------------------------------
# command_max + can_command_zero
# ---------------------------------------------------------------------------


class Test353CapabilityAndMax:
    @pytest.mark.asyncio
    async def test_command_max_clamps_to_device_max_current(self) -> None:
        device = _device(max_current=16)
        adapter = KebaAdapter(device)

        await adapter.command_max()

        # 16 is at device max → set_current(16); intent is CHARGE_MAX
        device._set_current.assert_awaited_once_with(16)
        assert adapter._last_intent is ChargerIntent.CHARGE_MAX

    @pytest.mark.asyncio
    async def test_command_current_above_max_clamps(self) -> None:
        """A request above max_current should clamp, not error."""
        device = _device(max_current=16)
        adapter = KebaAdapter(device)

        await adapter.command_current(32)

        device._set_current.assert_awaited_once_with(16)

    def test_can_command_zero_is_false(self) -> None:
        """Capability advertisement: KEBA cannot accept 0A directly.
        Consumers reading this property should always go through the
        adapter, never ``hass.services.async_call('keba', 'set_current')``
        with 0 directly — the regression class #353 exists."""
        device = _device()
        adapter = KebaAdapter(device)
        assert adapter.can_command_zero is False


# ---------------------------------------------------------------------------
# is_self_charging — the post-mortem signal
# ---------------------------------------------------------------------------


class Test353IsSelfCharging:
    """After commanding IDLE / DISABLE, if KEBA keeps drawing power,
    that's the #353/#315 self-charge regression class. The adapter
    surfaces it via ``is_self_charging``."""

    def test_returns_true_when_idle_intent_but_drawing(self) -> None:
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerPower,
        )
        device = _device()
        adapter = KebaAdapter(device)
        adapter._last_intent = ChargerIntent.IDLE

        # power_w > handshake (default >100W) but intent was IDLE → self-charge
        power = ChargerPower(
            charger_id="ev_charger", power_w=4000, connected=True,
        )
        assert adapter.is_self_charging(power) is True

    def test_returns_false_when_charge_intent(self) -> None:
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerPower,
        )
        device = _device()
        adapter = KebaAdapter(device)
        adapter._last_intent = ChargerIntent.CHARGE_AT_AMPS

        power = ChargerPower(
            charger_id="ev_charger", power_w=4000, connected=True,
        )
        assert adapter.is_self_charging(power) is False

    def test_returns_true_on_cold_start_with_high_power(self) -> None:
        """The #315 cold-start case: SEM just woke up, no command
        issued yet, but KEBA is already drawing → it self-resumed
        from a previous session."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerPower,
        )
        device = _device()
        adapter = KebaAdapter(device)
        # _last_intent is None — cold start
        assert adapter._last_intent is None

        power = ChargerPower(
            charger_id="ev_charger", power_w=4000, connected=True,
        )
        assert adapter.is_self_charging(power) is True

    def test_returns_false_when_no_power_drawn(self) -> None:
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerPower,
        )
        device = _device()
        adapter = KebaAdapter(device)
        adapter._last_intent = ChargerIntent.IDLE

        # Power below handshake threshold → not self-charging
        power = ChargerPower(
            charger_id="ev_charger", power_w=0, connected=True,
        )
        assert adapter.is_self_charging(power) is False
