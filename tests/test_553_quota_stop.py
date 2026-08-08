"""#553/#545/#740 — the quota-stop: the box's own language for "no".

Live-proven on the real P30 (2026-08-08, ~22:30, observer-on windows):

* ``keba.disable`` invites the war — the box auto-starts, the car begs,
  SEM kills, every ~90 s, all night. The #553 guard (set_energy AFTER
  disable) never landed: the register read 0.0 all evening — writes to
  a disabled session don't persist. A silent no-op since it shipped.
* A quota BELOW the session counter is rejected (register cleared).
* A quota just ABOVE the session, written before enable (Guido's own
  script order: set_energy → enable), terminates at the target and
  HOLDS — ten unpoliced minutes of silence, the evening's first.

So the KEBA-shape stop becomes the quota-hold: park the current at the
viable minimum (the Zoe cuts out below it — the #545 floor, box-side),
write ``session + 0.3`` (never below the 1 kWh library floor), enable.
The box charges the small remainder, suspends itself, and refuses the
car natively. Legacy disable+guard remains the fallback when the box's
session register is undiscoverable.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    QUOTA_STOP_MARGIN_KWH,
    CurrentControlDevice,
)


def _keba(session_kwh=9.9):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    dev = CurrentControlDevice(
        hass, "keba1", "Keba",
        charger_service="keba.set_current",
        min_current=10, max_current=16,
    )
    if session_kwh is not None:
        dev._session_energy_sensor_cache = "sensor.keba_p30_session_energy"
        st = MagicMock()
        st.state = str(session_kwh)
        hass.states.get = MagicMock(return_value=st)
    else:
        hass.states.get = MagicMock(return_value=None)
    return dev, hass


def _calls(hass, service):
    return [c.args[2] for c in hass.services.async_call.call_args_list
            if c.args[1] == service]


@pytest.mark.asyncio
class TestQuotaStop:
    async def test_the_stop_is_quota_then_enable_not_disable(self):
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        assert _calls(hass, "set_energy")[-1]["energy"] == pytest.approx(
            9.9 + QUOTA_STOP_MARGIN_KWH, abs=0.01)
        assert _calls(hass, "enable"), "the quota only governs an enabled box"
        assert not _calls(hass, "disable"), (
            "disable is the war — the quota-hold replaces it")

    async def test_the_current_parks_at_the_viable_minimum(self):
        """The box's stored 8 A fed the Zoe-cutout churn all evening —
        any remainder charge runs at a current the car can hold."""
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        currents = _calls(hass, "set_current")
        assert currents and currents[-1]["current"] == 10

    async def test_a_tiny_session_still_respects_the_library_floor(self):
        dev, hass = _keba(session_kwh=0.2)
        await dev.stop_session()
        assert _calls(hass, "set_energy")[-1]["energy"] == 1.0

    async def test_an_unreadable_register_falls_back_to_legacy(self):
        dev, hass = _keba(session_kwh=None)
        await dev.stop_session()
        assert _calls(hass, "disable"), "no session read → the old stop"

    async def test_the_dead_mans_off_still_arms(self):
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        fs = [c for c in _calls(hass, "set_failsafe")
              if c.get("failsafe_fallback") == 0]
        assert fs, "the masterless guard rides every stop path (#740)"
