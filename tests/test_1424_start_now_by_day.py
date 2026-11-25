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
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator, _now_car_gone,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.select import SEMPerChargerSelect

BMW = "goecharger_api2_d97c7a8d4f"      # the reporter's charger id
CUPRA = "ev_charger"                     # the second charger, other mode


def _coordinator(plan_hours: float = 17.0) -> SEMCoordinator:
    """The reporter's home: two chargers, BMW on Only Solar, a plan with
    hourly slots up to the next morning and no block (a Sun charger takes no
    grid hours, so the planner leaves it out)."""
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": [
        {"id": BMW, "name": "Go-e Charger BMW", "charge_mode": "solar_only",
         "ev_connected_sensor": "binary_sensor.goe_417144_car_0"},
        {"id": CUPRA, "name": "Go-e Charger Cupra", "charge_mode": "min_plus_solar",
         "ev_connected_sensor": "binary_sensor.goe_417761_car_0"},
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


def _power(bmw_in: bool, cupra_in: bool, bmw_w: float = 0.0) -> PowerReadings:
    """One cycle's readings: the fleet flag is the OR of the chargers, each
    charger's own answer is in the reader's map (for the BMW, the reader's
    physics answer when its plug sensor reads off while it draws)."""
    p = PowerReadings()
    p.ev_connected = bool(bmw_in or cupra_in)
    p.ev_connected_per_charger = {BMW: bmw_in, CUPRA: cupra_in}
    p.ev_power_per_charger = {BMW: bmw_w, CUPRA: 0.0}
    return p


def _cfg(coord, cid):
    return next(c for c in coord.config["ev_chargers"] if c["id"] == cid)


def _cycle(coord, power):
    """What the per-charger loop does for the BMW each cycle."""
    coord._now_follow_car(BMW, _now_car_gone(coord, power, _cfg(coord, BMW), BMW))


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
    # the next cycle sees the car in: the reporter's car drew 10 kW
    _cycle(coord, _power(True, False, bmw_w=10426.0))
    assert coord._plan_overrides[BMW].started
    now = dt_util.utcnow()
    rec = coord._plan_overrides[BMW]
    assert rec.action == "force" and rec.user_now
    left_min = (rec.expires_at - now).total_seconds() / 60
    assert 118 <= left_min <= 121, left_min
    # full power now, the saved Only Solar again after the two hours
    assert _mode(coord, BMW, now + timedelta(minutes=60)) == "always_max"
    assert _mode(coord, BMW, now + timedelta(minutes=125)) == "solar_only"


@pytest.mark.asyncio
async def test_the_charger_shows_now_while_it_runs_and_sun_ends_it():
    """The report's card showed "Only Solar" while the full-power override
    ran. The mode now reads Now with its end, and picking Sun ends it at
    once, with the saved Only Solar running again."""
    coord = _coordinator()
    sel = _select(coord)
    await _pick(sel, "now")
    _cycle(coord, _power(True, False, bmw_w=10426.0))
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


# ── (#1424, review) Now follows THIS charger's car, not the fleet's ─────
# The reporter has two chargers. The fleet ``ev_connected`` is true when
# either has a car; ``_now_car_gone`` read it, so the BMW's Now could not
# see its own car leave while the Cupra's car was in.

@pytest.mark.asyncio
async def test_unplugging_this_car_ends_now_while_the_other_car_stays():
    coord = _coordinator()
    sel = _select(coord)
    await _pick(sel, "now")
    _cycle(coord, _power(True, True, bmw_w=10426.0))
    assert coord._plan_overrides[BMW].started
    # the BMW leaves; the Cupra's car stays in (fleet flag still True)
    _cycle(coord, _power(False, True))
    assert BMW not in coord._plan_overrides
    assert _mode(coord, BMW, dt_util.utcnow()) == "solar_only"


@pytest.mark.asyncio
async def test_a_now_picked_with_this_car_away_waits_while_the_other_car_is_in():
    coord = _coordinator()
    sel = _select(coord)
    await _pick(sel, "now")
    _cycle(coord, _power(False, True))
    rec = coord._plan_overrides[BMW]
    assert not rec.started          # waits for its own car
    # …and starts, with its two hours, when the BMW is plugged in
    _cycle(coord, _power(True, True))
    rec = coord._plan_overrides[BMW]
    assert rec.started
    left_min = (rec.expires_at - dt_util.utcnow()).total_seconds() / 60
    assert 118 <= left_min <= 121, left_min


def test_a_charger_with_no_plug_sensor_in_a_fleet_ends_nothing_at_rest():
    """(#1153) Without its own plug sensor, a charger at rest has no known
    car: no unplug, so nothing ends — even with the other car in."""
    coord = _coordinator()
    _cfg(coord, BMW).pop("ev_connected_sensor")
    p = _power(False, True)
    del p.ev_connected_per_charger[BMW]
    assert _now_car_gone(coord, p, _cfg(coord, BMW), BMW) is None
    # drawing over the floor it is in
    p.ev_power_per_charger[BMW] = 4200.0
    assert _now_car_gone(coord, p, _cfg(coord, BMW), BMW) is False


def test_one_charger_reads_its_fleet_flag():
    """One charger set up with flat keys: the fleet flag is its own."""
    coord = _coordinator()
    coord.config = {"ev_chargers": [], "ev_connected_sensor": "binary_sensor.plug"}
    p = PowerReadings()
    p.ev_connected = False
    assert _now_car_gone(coord, p, {}, "ev_charger") is True
    p.ev_connected = True
    assert _now_car_gone(coord, p, {}, "ev_charger") is False


def test_the_unplug_check_asks_this_charger_and_no_fleet_flag():
    """AST pin: ``_now_car_gone`` asks ``charger_state`` (the rule
    ``build_charger_view`` uses) and reads no ``ev_connected`` itself —
    not as an attribute, not through ``getattr``."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(_now_car_gone))
    calls = {getattr(n.func, "id", getattr(n.func, "attr", None))
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "charger_state" in calls
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "ev_connected" not in attrs
    strings = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "ev_connected" not in strings


def test_both_charger_paths_pass_their_charger_id():
    """AST pin: the fleet loop and the one-charger branch both hand
    ``_now_car_gone`` the charger id. A call without it raises inside the
    loop's ``try`` and the Now is silently not applied."""
    import ast
    from pathlib import Path

    import custom_components.solar_energy_management.coordinator.coordinator as mod
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_now_car_gone"]
    assert len(calls) == 2, len(calls)
    for call in calls:
        assert len(call.args) == 4, ast.unparse(call)
        assert ast.unparse(call.args[3]) == "cid", ast.unparse(call)
