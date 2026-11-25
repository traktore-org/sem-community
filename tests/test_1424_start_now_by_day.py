"""(#1424) "Start now" by day ran a Sun charger at full power until morning.

The report: a BMW on a go-e charger in "Only Solar" charged at 15 A while
the sun gave about 4.2 kW; the house battery (no discharge limit SEM can
write) covered the rest. A current set by hand went back to 15 A. The
diagnostics held a one-off plan override ``force`` on that charger "until
06:59": what the 2.3.0-beta.27 Plan card's "Start now" set — full power
until the plan's end, the next morning. A force runs ``always_max``, which
outranks the saved mode, and the charger card still showed "Only Solar".

#1381 made it one Now: it ends at THIS car's next plan block, else after two
hours (never at the plan's end or another device's block); the charger's
mode shows Now while it runs; picking another mode ends it. These tests run
the reporter's case through the real select and the real coordinator
methods, so a return to "until the plan ends" fails here.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.select import SelectEntityDescription
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.select import SEMPerChargerSelect

BMW = "goecharger_api2_d97c7a8d4f"      # the reporter's charger id
CUPRA = "ev_charger"                     # the second charger, other mode


def _coordinator(plan_hours: float = 17.0) -> SEMCoordinator:
    """The reporter's home: two chargers, BMW on Only Solar, a plan with
    hourly slots up to the next morning and no block (a Sun charger takes no
    grid hours, so the planner leaves it out)."""
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": [
        {"id": BMW, "name": "Go-e Charger BMW", "charge_mode": "solar_only"},
        {"id": CUPRA, "name": "Go-e Charger Cupra", "charge_mode": "min_plus_solar"},
    ]}
    c._plan_overrides = {}
    c._storage = None
    c._known_battery_ids = set()
    c._battery_ids_read = True
    now = dt_util.utcnow().replace(second=0, microsecond=0)
    end = now + timedelta(hours=plan_hours)
    slots, t = [], now
    while t < end:
        nxt = min(end, t + timedelta(hours=1))
        slots.append({"start": t.isoformat(), "end": nxt.isoformat()})
        t = nxt
    c._energy_plan_shadow = {
        "slots": slots, "blocks": [],
        "not_scheduled": [{"id": f"ev:{BMW}", "why": "mode"}],
    }
    c.async_request_refresh = AsyncMock()
    c._plan_end = end
    return c


def _select(coord: SEMCoordinator) -> SEMPerChargerSelect:
    sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
    sel.coordinator = coord
    sel.entity_description = SelectEntityDescription(
        key=f"charger_{BMW}_charge_mode", options=["sun", "sun_tariff", "now", "off"])
    sel._charger_id = BMW
    sel._config_key = "charge_mode"
    sel._value = "sun"
    sel.hass = None
    sel._entry = None
    return sel


def _mode(coord, cid, at):
    stored = next(c["charge_mode"] for c in coord.config["ev_chargers"] if c["id"] == cid)
    return po.charger_mode_for(coord._plan_overrides, cid, stored, at)


async def _pick(sel, option):
    with patch.object(sel, "async_write_ha_state"), \
            patch("custom_components.solar_energy_management.persist_per_charger_option") as w:
        await sel.async_select_option(option)
    return w


@pytest.mark.asyncio
async def test_charge_now_by_day_ends_after_two_hours_not_at_the_plans_end():
    """The Plan card's Charge now picks Now on the charger. By day, on a Sun
    charger with no block of its own, Now runs two hours — not the 17 hours
    to the plan's end the old Start now ran."""
    coord = _coordinator()
    sel = _select(coord)
    await _pick(sel, "now")
    # the next cycle sees the car in (the reporter's car drew 10 kW)
    coord._now_follow_car(BMW, False)
    now = dt_util.utcnow()
    rec = coord._plan_overrides[BMW]
    assert rec.action == "force" and rec.user_now
    left_min = (rec.expires_at - now).total_seconds() / 60
    assert 118 <= left_min <= 121, left_min
    assert rec.expires_at < coord._plan_end - timedelta(hours=10)
    # full power now, the saved Only Solar again after the two hours
    assert _mode(coord, BMW, now + timedelta(minutes=60)) == "always_max"
    assert _mode(coord, BMW, now + timedelta(minutes=125)) == "solar_only"
    # the other charger is not touched
    assert CUPRA not in coord._plan_overrides
    assert _mode(coord, CUPRA, now) == "min_plus_solar"


@pytest.mark.asyncio
async def test_the_charger_shows_now_while_it_runs_and_sun_ends_it():
    """The report's card showed "Only Solar" while the full-power override
    ran. The mode now reads Now with its end, and picking Sun ends it at
    once, with the saved Only Solar running again."""
    coord = _coordinator()
    sel = _select(coord)
    await _pick(sel, "now")
    coord._now_follow_car(BMW, False)
    assert sel._shown_mode("solar_only") == "now"
    until = sel.extra_state_attributes["now_until"]
    assert until == coord._plan_overrides[BMW].expires_at.isoformat()

    w = await _pick(sel, "sun")
    assert BMW not in coord._plan_overrides
    assert w.call_args.args[-1] == "sun"
    assert sel._shown_mode("solar_only") == "sun"
    assert _mode(coord, BMW, dt_util.utcnow()) == "solar_only"


@pytest.mark.asyncio
async def test_a_start_now_saved_by_the_old_card_shows_as_now_and_sun_ends_it():
    """The reporter's override was saved by beta.27 (no ``user_now``,
    ``started`` or ``minutes`` keys) and lasts until 06:59. After the update
    it must not hide behind "Sun": the mode reads Now until that time, and
    picking Sun ends it."""
    coord = _coordinator()
    now = dt_util.utcnow().replace(microsecond=0)
    old = {BMW: {"action": "force",
                 "expires_at": (now + timedelta(hours=16, minutes=35)).isoformat(),
                 "value": None,
                 "set_at": (now - timedelta(hours=1)).isoformat()}}
    coord._plan_overrides = po.deserialize(old)
    sel = _select(coord)
    assert _mode(coord, BMW, now) == "always_max"     # it still runs: end it
    assert sel._shown_mode("solar_only") == "now"
    assert sel.extra_state_attributes["now_until"] == \
        coord._plan_overrides[BMW].expires_at.isoformat()

    await _pick(sel, "sun")
    assert BMW not in coord._plan_overrides
    assert _mode(coord, BMW, now) == "solar_only"


def test_a_skip_is_no_full_power():
    """A one-off skip (the Plan card's other button) never shows as Now and
    never gives full power."""
    coord = _coordinator()
    now = dt_util.utcnow()
    coord.set_plan_override(BMW, "skip", 60)
    sel = _select(coord)
    assert sel._shown_mode("solar_only") == "sun"
    assert _mode(coord, BMW, now) == "solar_only"
