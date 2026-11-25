"""#1426 — a charge that starts while the cloud still shows SEM's own values.

A battery setting changed through a cloud integration can show its old
value for minutes after a write. SEM stops a grid charge: it puts the mode
back to the user's ``self_consumption`` and turns "allow grid charging"
off. The cloud still shows ``autonomous`` and "on" — SEM's own charge
values. The next charge starts inside that time.

Before the fix the start read those as the user's: it saved ``autonomous``
as the mode to put back and took the permit "on" as the user's, so it never
turned it on (it was really off) and never off again. When the cloud showed
the real values, the mode read "not the old one", the charge ended at once
and the plan left the battery out for 24 h.

The rule pinned here: SEM remembers what it put back. For 15 minutes, or
until the entity shows the value SEM put back, a read of SEM's own charge
value is SEM's, and the start counts from the value SEM put back. A value
that is neither is the user's.
"""
from __future__ import annotations

import json

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)

from .test_1377_cloud_read_lag import CYCLE_S, _cycles, clock  # noqa: F401
from .test_1377_powerwall_charge import (
    MODE, PERMIT, _adapter, _charge, _Hass, _stop, _Store,
)


async def _charge_then_stop(hass, rec, hold, clock):
    a = _adapter(hass, rec, hold)
    await actuate_battery(_charge(), a)
    await _cycles(a, clock, 120)
    await actuate_battery(_stop(), a)
    assert (hass.read(MODE), hass.read(PERMIT)) == ("self_consumption", "off")
    return a


def _cloud_still_shows_sem(hass):
    """The cloud has not yet shown SEM's put-back: SEM's charge values."""
    hass.put(MODE, "autonomous")
    hass.put(PERMIT, "on")


def _prior(rec, entity):
    return json.loads(rec.raw).get("prior", {}).get(entity)


class TestTheStartInsideTheWindow:
    async def test_the_user_values_are_the_ones_sem_put_back(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 120
        n = len(hass.calls)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "self_consumption", "not SEM's own mode"
        assert _prior(rec, PERMIT) == "off", "SEM turned the permit on"
        sent = [(c[1], c[2].get("option")) for c in hass.calls[n:]]
        assert ("turn_on", None) in sent, "the permit really is off"
        assert ("select_option", "autonomous") in sent

    async def test_the_real_values_showing_do_not_end_the_charge(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 120
        await actuate_battery(_charge(), a)
        # the cloud now shows SEM's put-back, then SEM's new charge values
        hass.put(MODE, "self_consumption")
        hass.put(PERMIT, "off")
        await _cycles(a, clock, 60)
        assert a.charge_refused is False, "the plan keeps the battery"
        hass.put(MODE, "autonomous")
        hass.put(PERMIT, "on")
        await _cycles(a, clock, 120)
        assert a.charge_refused is False
        await actuate_battery(_stop(), a)
        assert (hass.read(MODE), hass.read(PERMIT)) == ("self_consumption", "off")

    async def test_a_restart_inside_the_window_keeps_the_memory(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 120
        fresh = _adapter(hass, rec, hold)                  # HA restarts
        await actuate_battery(_charge(), fresh)
        assert _prior(rec, MODE) == "self_consumption"
        assert _prior(rec, PERMIT) == "off"


class TestWhatIsTheUsers:
    async def test_a_value_set_since_is_the_users(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        hass.put(MODE, "backup")                           # set by hand
        clock.t += 120
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "backup"

    async def test_after_the_window_sems_value_is_taken_as_shown(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 16 * 60                                 # past 15 minutes
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) != "self_consumption"

    async def test_the_put_back_shown_ends_the_memory(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await a.async_adopt_running_charge()  # the next cycle sees the put-back
        clock.t += 60
        _cloud_still_shows_sem(hass)                      # now a real change
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) != "self_consumption"
