"""#740 — the dead-man's OFF: a stopped KEBA locks itself to 0 A.

The #546 live test proved the P30's failsafe watchdog cannot be turned
off over UDP — so SEM neutralised it for CHARGING (long timeout,
fallback at the charging floor, so a dead controller mid-charge lands
the car on the floor, not on a 6 A flap). But that same persisted
fallback is a CHARGING current, which is exactly why an Off-mode box
kept feeding the car in ~3 kW bites through a SEM restart (PROD,
2026-08-08): masterless, the watchdog re-authorised the floor.

The inversion: the HA keba integration documents ``failsafe_fallback:
0`` as "disables the running charging process completely". On every
SEM-initiated stop the failsafe re-arms as a dead-man's OFF —
``timeout=10 s, fallback=0 A, persisted`` — so a masterless / rebooting
/ disable-defeating box locks itself off within 10 seconds and stays
off until SEM explicitly starts a session (whose existing start
sequence re-arms the charging failsafe first). The wallbox itself now
enforces "off means off" between sessions.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    FAILSAFE_OFF_TIMEOUT_S,
    CurrentControlDevice,
)


def _keba(hass=None, **kw):
    hass = hass or MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    dev = CurrentControlDevice(
        hass, "keba1", "Keba",
        charger_service="keba.set_current",
        min_current=10, max_current=16, **kw,
    )
    return dev, hass


def _failsafe_calls(hass):
    return [c.args[2] for c in hass.services.async_call.call_args_list
            if c.args[0] == "keba" and c.args[1] == "set_failsafe"]


@pytest.mark.asyncio
class TestDeadMansOff:
    async def test_stop_arms_the_zero_fallback(self):
        dev, hass = _keba()
        await dev.arm_failsafe_off()
        calls = _failsafe_calls(hass)
        assert calls, "expected a set_failsafe call"
        fs = calls[-1]
        assert fs["failsafe_fallback"] == 0
        assert fs["failsafe_timeout"] == FAILSAFE_OFF_TIMEOUT_S
        assert fs["failsafe_persist"] == 1

    async def test_the_charging_arm_still_uses_the_floor(self):
        """The mid-charge contract is untouched: a dead controller lands
        the car on the charging floor, never on 0."""
        dev, hass = _keba()
        await dev.arm_failsafe()
        fs = _failsafe_calls(hass)[-1]
        assert fs["failsafe_fallback"] == 10
        assert fs["failsafe_timeout"] == 600

    async def test_the_user_opt_out_covers_both_arms(self):
        dev, hass = _keba()
        dev.arm_failsafe_enabled = False
        await dev.arm_failsafe_off()
        assert not _failsafe_calls(hass)

    async def test_a_charger_without_the_service_is_skipped_silently(self):
        dev, hass = _keba()
        hass.services.has_service = MagicMock(return_value=False)
        await dev.arm_failsafe_off()
        assert not _failsafe_calls(hass)

    async def test_stop_session_arms_it(self):
        """The wire: every SEM-initiated stop leaves the box holding a
        standing no — the masterless window has no teeth."""
        dev, hass = _keba()
        await dev.stop_session()
        calls = _failsafe_calls(hass)
        assert calls and calls[-1]["failsafe_fallback"] == 0
