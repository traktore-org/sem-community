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
    async def test_the_stop_disables_with_a_deadman_and_never_enables(self):
        """SUPERSEDED BY #854 — this pinned "quota then enable, not
        disable" because in #553's day a bare disable did not hold: the
        firmware retried and the car got back in, so the quota-hold was
        the only "no" that stuck.

        #740 then built the dead-man OFF (fallback 0 A, persisted), which
        makes the box enforce off through exactly those retries — and the
        stop path was never revisited, so SEM kept ENABLING the charger in
        order to stop it. On a box that was already idle that is a start,
        and it granted the firmware's 1 kWh floor on every plug-in against
        a zero ask (Guido's report, 28.08). Measured the same evening:
        plugged in and disabled with the dead-man armed, the box drew
        nothing for 28 minutes."""
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        assert _calls(hass, "disable")
        assert not _calls(hass, "enable"), (
            "a stop that enables is a start — this is the whole of #854")

    async def test_the_stop_writes_no_current_at_all(self):
        """SUPERSEDED BY #854. The old path parked the current at the
        viable minimum because the box was about to charge a remainder.
        Nothing charges now: the stop is a bare disable, exactly the
        automation that has run this hardware for two years."""
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        assert not _calls(hass, "set_current")

    async def test_no_energy_target_is_written_at_all(self):
        """SUPERSEDED BY #854. This pinned the library floor: a tiny
        session still wrote 1.0 kWh, because the firmware rounds any
        non-zero target up (measured 0.3 → 1.0). That floor is real — and
        it is exactly why SEM must not write a target to STOP something.
        The 1 kWh sat in the register as an allowance for the next enable
        to spend, which is what the reporter was seeing."""
        dev, hass = _keba(session_kwh=0.2)
        await dev.stop_session()
        assert not _calls(hass, "set_energy")

    async def test_an_unreadable_register_falls_back_to_legacy(self):
        dev, hass = _keba(session_kwh=None)
        await dev.stop_session()
        assert _calls(hass, "disable"), "no session read → the old stop"

    async def test_the_disable_stop_sends_nothing_else(self):
        """SUPERSEDED BY #854 (was: the dead-man still arms).

        The dead-man OFF and the 0 A write stay for brands whose stop IS a
        current write. On KEBA the disable is the stop, and Guido's
        two-year-old automation sends nothing else — every addition SEM
        made around it cost energy or started a fight with itself."""
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        assert _calls(hass, "disable")
        for never in ("enable", "set_energy", "set_current", "set_failsafe"):
            assert not _calls(hass, never), f"stop sent {never}"


class TestTheQuotaIsNotATreadmill:
    """HISTORY, kept deliberately. Live PROD 21.08: the reconciler
    re-asserts a standing stop every 60 s, and each re-assert rewrote
    ``quota = session + 0.3`` — so the finish line moved ahead of the car
    forever (quota-hold 1.8 → 2.0 → 3.7 → 3.8 …) and the "stop" charged
    unbounded until the #763 ceasefire silenced the rewrites.

    #829 fixed that with a one-quota rule. #854 removed the quota
    entirely: SEM's stop is now a bare ``keba.disable``, so there is no
    number to walk and the whole class of bug is structurally impossible.
    The tests below assert that absence rather than the old arithmetic.
    """

    async def test_no_quota_exists_to_walk(self):
        dev, hass = _keba(session_kwh=3.5)
        for session in ("3.6", "3.9", "4.4"):        # the car drinks on
            await dev.stop_session()
        assert not _calls(hass, "set_energy"), (
            "a stop wrote an energy target — the treadmill needs one to "
            "walk, and #854 removed the last writer"
        )

    async def test_every_re_assert_is_the_same_single_call(self):
        dev, hass = _keba(session_kwh=3.5)
        await dev.stop_session()
        await dev.stop_session()
        await dev.stop_session()
        assert len(_calls(hass, "disable")) == 3
        assert not _calls(hass, "enable")
