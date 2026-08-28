"""Tests for ChargerAdapter + KebaAdapter (Step 2 of the
arch/multi-charger-primary migration).

Each test pins ONE KEBA quirk that previously bit production:

- ``test_set_current_below_6a_routes_to_idle`` — #353
- ``test_command_idle_calls_stop_session_not_set_current_zero`` — #315
- ``test_actual_charging_ignores_binary_sensor_lag`` — #289
- ``test_is_self_charging_after_idle_intent`` — #315 / #346 / #353
  (the unified detection that replaces three separate guards)
- ``test_command_disable_distinct_from_idle`` — pins the intent
  tagging that makes the self-resume guard work after user OFF

The adapter does not yet replace any production code path — these
tests stand alone and exercise the adapter against a mocked
``CurrentControlDevice``. Step 4 of the migration wires the adapter
into the actuator.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    KebaAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
    ChargerPower,
)


def _make_device(max_current=32, phases=3, voltage=230, session_active=False):
    dev = MagicMock()
    dev.max_current = max_current
    dev.phases = phases
    dev.voltage = voltage
    dev._session_active = session_active
    dev._set_current = AsyncMock()
    dev.start_session = AsyncMock()
    dev.stop_session = AsyncMock()
    dev.park_off = AsyncMock()  # (#853)
    return dev


class TestKebaAdapterCapabilities:
    """The 6 A minimum + handshake_power_w + can_command_zero are
    KEBA firmware constants exposed via the adapter."""

    def test_min_current_is_6a(self):
        a = KebaAdapter(_make_device())
        assert a.min_current_a == 6

    def test_handshake_power_is_500w(self):
        """The 500 W cutoff that #315/#346/#353 all use. Pinned
        on the adapter so it's one constant, not three."""
        a = KebaAdapter(_make_device())
        assert a.handshake_power_w == 500.0

    def test_can_command_zero_is_false(self):
        """KEBA rejects ``set_current(0)``. The adapter advertises
        this so the actuator (or a lint) cannot misuse the
        command_current path with 0."""
        a = KebaAdapter(_make_device())
        assert a.can_command_zero is False

    def test_watts_for_amps_3phase_230v(self):
        a = KebaAdapter(_make_device(phases=3, voltage=230))
        assert a.watts_for_amps(6) == 4140
        assert a.watts_for_amps(10) == 6900
        assert a.watts_for_amps(32) == 22080

    def test_amps_for_watts_rounds_down(self):
        a = KebaAdapter(_make_device(phases=3, voltage=230))
        assert a.amps_for_watts(5000) == 7   # 5000 / 690 = 7.24
        assert a.amps_for_watts(4140) == 6
        assert a.amps_for_watts(3000) == 4   # below min, no clamp here


class TestCommandCurrentBelowMinimum:
    """#353 — set_current below 6 A is rejected by KEBA firmware,
    silently retaining the last valid setpoint. Adapter routes
    these calls to ``command_idle`` automatically."""

    @pytest.mark.asyncio
    async def test_amps_below_6_routes_to_idle(self):
        dev = _make_device()
        a = KebaAdapter(dev)
        await a.command_current(4)

        # Should NOT have called _set_current with 4
        for call in dev._set_current.await_args_list:
            assert call.args[0] != 4, "command_current(4) leaked through to _set_current"

        # Should have called stop_session (KEBA's only real "off")
        dev.stop_session.assert_awaited()
        assert a.last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    async def test_amps_zero_routes_to_idle(self):
        dev = _make_device()
        a = KebaAdapter(dev)
        await a.command_current(0)
        dev.stop_session.assert_awaited()
        assert a.last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    async def test_amps_6_passes_through(self):
        """Exactly 6 A is the minimum valid — passes through to
        _set_current, no stop_session."""
        dev = _make_device(session_active=True)
        a = KebaAdapter(dev)
        await a.command_current(6)
        dev._set_current.assert_awaited_with(6)
        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_amps_above_max_clamped(self):
        dev = _make_device(max_current=16, session_active=True)
        a = KebaAdapter(dev)
        await a.command_current(32)
        # Clamped to hardware max
        dev._set_current.assert_awaited_with(16)


class TestCommandIdleSemantics:
    """#315 / #346 / #353 — ``command_idle`` MUST invoke the brand
    disable, not just set_current(0). On KEBA that means
    ``stop_session()`` (which calls ``keba.disable``)."""

    @pytest.mark.asyncio
    async def test_command_idle_calls_stop_session(self):
        dev = _make_device()
        a = KebaAdapter(dev)
        await a.command_idle()
        dev.stop_session.assert_awaited()
        assert a.last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    async def test_command_disable_distinct_from_idle(self):
        """(#853) DISABLE parks the box (zero allowance); IDLE
        quota-holds (a pause that expects to resume). Distinct intent
        tags stay load-bearing: The tag matters because
        ``is_self_charging`` consults it — a self-resume after
        DISABLE is still wrong, even hours later."""
        dev = _make_device()
        a = KebaAdapter(dev)

        await a.command_disable()
        dev.park_off.assert_awaited()          # (#853) hard no parks
        dev.stop_session.assert_not_awaited()  # …and grants no quota
        assert a.last_intent is ChargerIntent.DISABLE

        # IDLE call updates the tag
        await a.command_idle()
        assert a.last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    async def test_command_max_uses_max_current(self):
        dev = _make_device(max_current=32, session_active=True)
        a = KebaAdapter(dev)
        await a.command_max()
        dev._set_current.assert_awaited_with(32)
        assert a.last_intent is ChargerIntent.CHARGE_MAX


class TestIsSelfCharging:
    """The unified self-resume detection that replaces #315 / #346 /
    #353's three separate guards. KEBA is "self-charging" when:

    1. It's drawing real power (>500 W), AND
    2. The actuator's last commanded intent was IDLE or DISABLE.

    The first cycle (no prior intent) treats high power as
    self-charging (cold start, KEBA self-resumed on plug-in)."""

    def test_idle_intent_high_power_is_self_charging(self):
        """The #353 PROD scenario: SEM commanded IDLE, KEBA still
        drawing 6.8 kW because firmware rejected the 0 A."""
        dev = _make_device()
        a = KebaAdapter(dev)
        a._last_intent = ChargerIntent.IDLE
        power = ChargerPower("keba", power_w=6830.0, connected=True, charging=True)
        assert a.is_self_charging(power) is True

    def test_disable_intent_high_power_is_self_charging(self):
        """The #315 PROD scenario: user picked OFF mode, KEBA
        self-resumed on plug-in."""
        dev = _make_device()
        a = KebaAdapter(dev)
        a._last_intent = ChargerIntent.DISABLE
        power = ChargerPower("keba", power_w=4140.0, connected=True, charging=True)
        assert a.is_self_charging(power) is True

    def test_charging_intent_high_power_is_NOT_self_charging(self):
        """We told KEBA to charge; it's charging. Not a bug."""
        dev = _make_device()
        a = KebaAdapter(dev)
        a._last_intent = ChargerIntent.CHARGE_AT_AMPS
        power = ChargerPower("keba", power_w=6830.0, connected=True, charging=True)
        assert a.is_self_charging(power) is False

    def test_idle_intent_handshake_power_is_NOT_self_charging(self):
        """Plugged in idle at handshake (~110 W) doesn't trigger.
        Below the 500 W cutoff."""
        dev = _make_device()
        a = KebaAdapter(dev)
        a._last_intent = ChargerIntent.IDLE
        power = ChargerPower("keba", power_w=110.0, connected=True, charging=False)
        assert a.is_self_charging(power) is False

    def test_cold_start_high_power_is_self_charging(self):
        """Coordinator just started up, KEBA already drawing power
        because it self-resumed during the HA restart. No prior
        intent recorded — treat as self-charging so the actuator
        force-disables on the first cycle."""
        dev = _make_device()
        a = KebaAdapter(dev)
        # _last_intent default = None
        power = ChargerPower("keba", power_w=4140.0, connected=True, charging=True)
        assert a.is_self_charging(power) is True


class TestActualCharging:
    """#289 — ``binary_sensor.keba_p30_charging_state`` lags real
    draw by 5+ seconds. The adapter prefers ``power_w`` over the
    boolean. ``actual_charging`` is the authoritative read."""

    def test_high_power_actual_charging_true_even_if_sensor_off(self):
        """power_w=4140 but binary sensor still says 'off' (stale).
        Adapter trusts the watts."""
        dev = _make_device()
        a = KebaAdapter(dev)
        power = ChargerPower(
            "keba", power_w=4140.0, connected=True, charging=False,
        )
        assert a.actual_charging(power) is True

    def test_handshake_power_actual_charging_false_even_if_sensor_on(self):
        """power_w=110 (handshake) but binary sensor still says 'on'
        (stale from prior session). Adapter trusts the watts."""
        dev = _make_device()
        a = KebaAdapter(dev)
        power = ChargerPower(
            "keba", power_w=110.0, connected=True, charging=True,
        )
        assert a.actual_charging(power) is False

    def test_zero_power_actual_charging_false(self):
        dev = _make_device()
        a = KebaAdapter(dev)
        power = ChargerPower("keba", power_w=0.0, connected=False, charging=False)
        assert a.actual_charging(power) is False
