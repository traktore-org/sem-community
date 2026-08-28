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

    async def test_the_current_is_parked_at_zero_not_a_charging_floor(self):
        """The old path parked at the viable MINIMUM because the box was
        about to charge a remainder. Nothing charges now, so the setpoint
        goes to 0 — a stored charging current is what fed an Off-mode car
        in ~3 kW bites through a restart (#740)."""
        dev, hass = _keba(session_kwh=9.9)
        await dev.stop_session()
        currents = _calls(hass, "set_current")
        assert currents and currents[-1]["current"] == 0

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


@pytest.mark.asyncio
class TestTheQuotaIsNotATreadmill:
    """Live, PROD, 21.08 evening: the reconciler re-asserts a standing stop
    every 60 s while the box still draws — correct for a `disable`, and
    self-defeating for a quota. Each re-assert rewrote
    ``quota = session + 0.3``, so the finish line moved ahead of the car
    forever (log: quota-hold 1.8 → 2.0 → 3.7 → 3.8 …). A car drawing less
    than 18 kW can NEVER consume the 0.3 kWh margin inside one 60 s dwell,
    so the "stop" charges unbounded. The thing that ended it tonight was the
    #763 ceasefire — it silenced the rewrites, and the box then reached the
    LAST quota and suspended natively, which is the quota doing exactly what
    it was designed to do the moment SEM stopped moving it.

    The rule: ONE stop, one quota. While the box still holds an unmet quota
    of ours, a re-asserted stop is already in force — leave the register
    alone and let the box arrive. Rewrite only when the box's target reads
    cleared (a lost write, or the box defied us), which is what the
    re-assert exists for.
    """

    def _with_target(self, dev, hass, session_kwh, target_kwh):
        """Wire the box's session AND energy-target registers."""
        session = MagicMock(); session.state = str(session_kwh)
        target = MagicMock(); target.state = str(target_kwh)
        dev._session_energy_sensor_cache = "sensor.keba_p30_session_energy"
        dev._energy_target_sensor_cache = "sensor.keba_p30_energy_target"

        def get(eid):
            if "session" in eid:
                return session
            if "target" in eid:
                return target
            return None
        hass.states.get = MagicMock(side_effect=get)
        return session, target

    async def test_the_treadmill_is_structurally_impossible_now(self):
        """(#854) The treadmill needed a SESSION-DERIVED quota to walk:
        each 60 s re-assert rewrote ``session + 0.3`` and the finish line
        outran the car. SEM no longer writes one — a stop disables and arms
        the dead-man, and the only target left is the #553 idle guard, a
        CONSTANT. A constant cannot walk, however often it is re-asserted."""
        dev, hass = _keba(session_kwh=None)
        session, target = self._with_target(dev, hass, 3.5, 0.0)

        await dev.stop_session()
        session.state = "3.6"             # the car drinks on
        await dev.stop_session()
        session.state = "3.9"
        await dev.stop_session()

        energies = {c["energy"] for c in _calls(hass, "set_energy")}
        assert len(energies) <= 1, (
            f"a stop wrote more than one distinct target ({energies}) — "
            "that is the treadmill returning by another door"
        )
        assert not _calls(hass, "enable")

    async def test_a_cleared_register_is_rewritten(self):
        """The re-assert's real job: the box lost or defied the write."""
        dev, hass = _keba(session_kwh=None)
        session, target = self._with_target(dev, hass, 3.5, 0.0)

        await dev.stop_session()
        assert len(_calls(hass, "set_energy")) == 1

        # Box register reads 0 — the quota is GONE (lost write / defiance).
        target.state = "0.0"
        session.state = "3.6"
        await dev.stop_session()
        assert len(_calls(hass, "set_energy")) == 2, (
            "a cleared register means the box holds no quota — the re-assert "
            "must restore it or the box charges unbounded"
        )

    async def test_a_met_quota_left_behind_is_rewritten(self):
        """A stale target BELOW the session bounds nothing (KEBA rejects or
        has already consumed it) — a fresh stop must write a fresh quota."""
        dev, hass = _keba(session_kwh=None)
        session, target = self._with_target(dev, hass, 5.0, 4.0)

        await dev.stop_session()
        assert len(_calls(hass, "set_energy")) == 1

    async def test_no_target_sensor_keeps_todays_behaviour(self):
        """A box whose integration exposes no energy-target register cannot
        be checked — rewriting is then the safe default, exactly as today."""
        dev, hass = _keba(session_kwh=3.5)
        await dev.stop_session()
        await dev.stop_session()
        assert len(_calls(hass, "set_energy")) == 2
