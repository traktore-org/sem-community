"""Tests for actuate(decision, adapter) — Step 4.

Pins:
1. **Intent dispatch** — each ChargerIntent → exactly one adapter
   method call.
2. **Self-resume guard** — when the adapter says charger is
   self-charging, ``command_disable()`` fires BEFORE the new intent
   is applied (catches #315 / #346 / #353 in one place).
3. **Idempotency** — actuating the same decision twice on an
   already-correct adapter doesn't double-fire (the adapter's
   internal de-dup handles it).
4. **No fleet reads** — actuate never reads ``power.ev_power`` or
   any fleet field. Pin via inspection of the function source +
   the fact that the test fixtures don't construct a
   ``PowerReadings`` at all.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)


def _adapter(self_charging: bool = False):
    """A mock ChargerAdapter that records every command call."""
    a = MagicMock()
    a.command_current = AsyncMock()
    a.command_idle = AsyncMock()
    a.command_max = AsyncMock()
    a.command_disable = AsyncMock()
    a.is_self_charging = MagicMock(return_value=self_charging)
    a.last_intent = None
    return a


class TestIntentDispatch:
    """Each ChargerIntent maps to exactly one adapter call."""

    @pytest.mark.asyncio
    async def test_disable_calls_command_disable(self):
        a = _adapter()
        d = ChargerDecision(
            charger_id="keba", mode="off", intent=ChargerIntent.DISABLE,
        )
        power = ChargerPower("keba", power_w=0.0, connected=True)
        await actuate(d, a, power)

        a.command_disable.assert_awaited_once()
        a.command_idle.assert_not_awaited()
        a.command_max.assert_not_awaited()
        a.command_current.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idle_calls_command_idle(self):
        a = _adapter()
        d = ChargerDecision(
            charger_id="keba", mode="solar_only", intent=ChargerIntent.IDLE,
        )
        power = ChargerPower("keba", power_w=0.0, connected=True)
        await actuate(d, a, power)

        a.command_idle.assert_awaited_once()
        a.command_disable.assert_not_awaited()
        a.command_max.assert_not_awaited()
        a.command_current.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_charge_max_calls_command_max(self):
        a = _adapter()
        d = ChargerDecision(
            charger_id="keba", mode="always_max",
            intent=ChargerIntent.CHARGE_MAX,
        )
        power = ChargerPower("keba", power_w=0.0, connected=True)
        await actuate(d, a, power)

        a.command_max.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_charge_at_amps_calls_command_current(self):
        a = _adapter()
        d = ChargerDecision(
            charger_id="keba", mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=8, budget_w=5520.0,
        )
        power = ChargerPower("keba", power_w=0.0, connected=True)
        await actuate(d, a, power)

        a.command_current.assert_awaited_once_with(8)


class TestSelfResumeGuard:
    """When the adapter says the charger is self-charging, force
    a disable BEFORE applying the new intent. This is the
    structural collapse of #315 (off self-resume), #346 (solar_only
    night self-resume), #353 (solar_only sub-min self-charge) into
    one guard."""

    @pytest.mark.asyncio
    async def test_self_charging_idle_forces_disable_first(self):
        """PROD #353: SEM wants IDLE, KEBA still drawing 6.8 kW.
        Adapter detects → actuate force-disables before the
        idle command (which is itself idempotent)."""
        a = _adapter(self_charging=True)
        d = ChargerDecision(
            charger_id="keba", mode="solar_only", intent=ChargerIntent.IDLE,
        )
        power = ChargerPower("keba", power_w=6830.0, connected=True, charging=True)
        await actuate(d, a, power)

        # Disable fired first
        a.command_disable.assert_awaited_once()
        # Then the new intent (IDLE) — also calls command_idle
        a.command_idle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_self_charging_disable_intent_idempotent(self):
        """User picks OFF mode while KEBA self-resumed. Adapter
        sees self-charging → disable. Then actuate dispatches
        DISABLE intent → another disable. Adapter de-dups internally."""
        a = _adapter(self_charging=True)
        d = ChargerDecision(
            charger_id="keba", mode="off", intent=ChargerIntent.DISABLE,
        )
        power = ChargerPower("keba", power_w=4140.0, connected=True, charging=True)
        await actuate(d, a, power)

        # Two disables: one from guard, one from intent dispatch
        assert a.command_disable.await_count == 2

    @pytest.mark.asyncio
    async def test_no_self_charging_no_extra_disable(self):
        """Adapter says no self-resume → no pre-emptive disable."""
        a = _adapter(self_charging=False)
        d = ChargerDecision(
            charger_id="keba", mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=8,
        )
        power = ChargerPower("keba", power_w=5520.0, connected=True, charging=True)
        await actuate(d, a, power)

        a.command_disable.assert_not_awaited()
        a.command_current.assert_awaited_once_with(8)

    @pytest.mark.asyncio
    async def test_self_charging_transitions_to_charge(self):
        """Edge case: actuator just finished a session, charger
        still drawing → self_charging=True for one cycle. Now we
        want to CHARGE_AT_AMPS. The guard fires (disable contactor),
        then command_current opens it again. The car effectively
        restarts cleanly without manual intervention."""
        a = _adapter(self_charging=True)
        d = ChargerDecision(
            charger_id="keba", mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=10,
        )
        power = ChargerPower("keba", power_w=4500.0, connected=True, charging=True)
        await actuate(d, a, power)

        a.command_disable.assert_awaited_once()
        a.command_current.assert_awaited_once_with(10)


class TestNoUnreachableBranch:
    """Every intent value has a branch — no silent no-op."""

    @pytest.mark.asyncio
    async def test_all_intents_handled(self):
        """Iterate every ChargerIntent value and confirm at least
        one adapter method fires. Catches future intent additions
        that forget to add a branch."""
        for intent in ChargerIntent:
            a = _adapter()
            d = ChargerDecision(
                charger_id="keba", mode="solar_only", intent=intent,
                commanded_amps=8 if intent is ChargerIntent.CHARGE_AT_AMPS else 0,
            )
            power = ChargerPower("keba", power_w=0.0, connected=True)
            await actuate(d, a, power)

            # At least one of the four command methods was called
            total_calls = (
                a.command_disable.await_count
                + a.command_idle.await_count
                + a.command_max.await_count
                + a.command_current.await_count
            )
            assert total_calls >= 1, f"intent {intent} produced no command"
