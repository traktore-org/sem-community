"""#853 — on KEBA the quota-hold is the ONLY stop that holds. Do not "fix" it.

Twice now the quota-hold has looked like a bug worth removing: it grants
the car up to 1 kWh on a plug-in against a zero ask, which reads as "Min
= 0 doesn't mean 0". Both halves of that reasoning were tested on the
real P30 on 28.08.2026 and both were wrong:

1. **The 1 kWh is the BOX's floor, not SEM's.** Writing the register
   directly on PROD: 0.3 → reads 1.0, 0.5 → reads 1.0, 2.5 → reads 2.5,
   0 → reads 0.0 (0 means "no limit"). Any non-zero target below 1 kWh is
   rounded up by the firmware. ``max(1.0, …)`` is describing hardware.

2. **Replacing it with ``keba.disable`` costs MORE.** Shipped as the
   original #853 fix and live on PROD for ~40 minutes: the box auto-started
   ~60 s after every park, SEM parked it again, and after 4 round-trips the
   #763 ceasefire correctly stood SEM down for 30 minutes — during which the
   car drew ~10 kW unopposed. A 1 kWh bounded cost became a multi-kWh
   unbounded one, plus contactor cycling. The pre-existing comment
   ("``disable`` invites the war: the box auto-starts, the car begs, SEM
   kills, every ~90 s all night") was right.

So: a KEBA that is plugged in and asking can only be told "no" by a
SATISFIED ENERGY TARGET, and the smallest one the box accepts is 1 kWh.
``park_off`` (disable + dead-man) stays correct for a DISCONNECTED box —
no car, nothing to beg, no war (#846).

The real remedy for the 1 kWh is charger-side: disable the box's own
auto-start/authorization, which is what the stop-war warning tells the
user to do.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters.keba import (
    KebaAdapter,
)


def _adapter():
    dev = MagicMock()
    dev.stop_session = AsyncMock()
    dev.park_off = AsyncMock()
    a = KebaAdapter.__new__(KebaAdapter)
    a._device = dev
    a._last_intent = None
    return a, dev


@pytest.mark.asyncio
async def test_disable_uses_the_quota_hold_not_a_bare_disable():
    """The regression guard. ``park_off`` here reopens the stop-war."""
    a, dev = _adapter()
    await a.command_disable()
    dev.stop_session.assert_awaited_once()
    dev.park_off.assert_not_awaited(), (
        "a bare disable on a CONNECTED box starts the #763 stop-war — "
        "measured on PROD 28.08: 4 round-trips, 30-minute ceasefire, "
        "~10 kW drawn unopposed"
    )


@pytest.mark.asyncio
async def test_idle_uses_the_quota_hold_too():
    a, dev = _adapter()
    await a.command_idle()
    dev.stop_session.assert_awaited_once()
    dev.park_off.assert_not_awaited()


def test_the_quota_floor_matches_the_firmware():
    """1.0 is the box's rounding floor, measured — not a SEM choice."""
    from custom_components.solar_energy_management.devices.base import (
        QUOTA_STOP_MARGIN_KWH,
    )
    for session in (0.0, 0.05, 0.5):
        quota = max(1.0, round(session + QUOTA_STOP_MARGIN_KWH, 1))
        assert quota == 1.0, (
            "below 1 kWh the P30 rounds any target up to 1.0 (measured), so "
            "asking for less silently becomes 1.0 anyway"
        )
    assert max(1.0, round(2.0 + QUOTA_STOP_MARGIN_KWH, 1)) == 2.3
