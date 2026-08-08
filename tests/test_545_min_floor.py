"""#545 (reopened) — Min is a floor, enforced at the ONE emit seam.

PROD 2026-08-08 evening: the start ladder offered 6/8/9 A below the
configured minimum of 10, the stability hold froze 8 A, and the Zoe's
onboard charger cut to 0 W and stayed there — an active mode, a hungry
car, and a command the vehicle physically cannot use. The box mirrored
every command faithfully; the violation was ours.

The contract: a nonzero command is never below the configured minimum —
commanded ∈ {0} ∪ [min_current, max_current] — clamped in
``_set_current`` itself so the ladder, the zones and the stability hold
can never put a floor-violating value on the wire.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


def _dev(min_current=10):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    dev = CurrentControlDevice(
        hass, "keba1", "Keba",
        charger_service="keba.set_current",
        min_current=min_current, max_current=16,
    )
    return dev, hass


def _current_writes(hass):
    return [c.args[2] for c in hass.services.async_call.call_args_list
            if c.args[1] == "set_current"]


@pytest.mark.asyncio
class TestMinIsAFloor:
    async def test_a_below_floor_command_is_lifted_to_the_floor(self):
        dev, hass = _dev(min_current=10)
        await dev._set_current(8)
        writes = _current_writes(hass)
        assert writes and writes[-1]["current"] == 10

    async def test_the_ladder_values_all_land_on_the_floor(self):
        dev, hass = _dev(min_current=10)
        for offer in (9, 6, 8):
            dev._last_write_at = 0.0     # defeat the heartbeat dedup
            dev._current_setpoint = 99.0
            await dev._set_current(offer)
        assert all(w["current"] == 10 for w in _current_writes(hass))

    async def test_zero_still_means_stop(self):
        dev, hass = _dev(min_current=10)
        await dev._set_current(0)
        writes = _current_writes(hass)
        # 0 must never be lifted — it is the stop intent, not a current.
        assert all(w["current"] == 0 for w in writes) or not writes

    async def test_a_charger_whose_floor_is_low_passes_through(self):
        dev, hass = _dev(min_current=6)
        await dev._set_current(8)
        writes = _current_writes(hass)
        assert writes and writes[-1]["current"] == 8

    async def test_above_floor_untouched(self):
        dev, hass = _dev(min_current=10)
        await dev._set_current(12)
        writes = _current_writes(hass)
        assert writes and writes[-1]["current"] == 12
