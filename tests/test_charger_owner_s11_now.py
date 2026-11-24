"""(#1381 charger owner S11) "Now" has an end.

Owner's rule: Now ends at the plan's next block for this charger, or at a
time the user chooses; "until full" is the third choice. Charge now and Start
now are one control. A timed Now is the plan override "force" the owner
already holds (persisted, expires by itself, S8's timed claims); the untimed
Now is the stored ``always_max`` — what every Always (max) charger has today,
so those users keep exactly what they had ("until full").
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.select import SEMPerChargerSelect


def _select(stored="min_plus_solar", overrides=None):
    from homeassistant.components.select import SelectEntityDescription
    sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
    sel.coordinator = MagicMock()
    sel.coordinator.config = {"ev_chargers": [{"id": "ev_charger", "charge_mode": stored}]}
    sel.coordinator._plan_overrides = overrides if overrides is not None else {}
    sel.coordinator.now_minutes_for = MagicMock(return_value=95)
    sel.coordinator.async_request_refresh = AsyncMock()

    def _set(cid, action, minutes, value=None):
        now = dt_util.utcnow()
        sel.coordinator._plan_overrides = po.set_override(
            sel.coordinator._plan_overrides, cid, action,
            now + timedelta(minutes=minutes), now)
    sel.coordinator.set_plan_override = MagicMock(side_effect=_set)

    def _clear(cid):
        sel.coordinator._plan_overrides = po.clear_override(sel.coordinator._plan_overrides, cid)
    sel.coordinator.clear_plan_override = MagicMock(side_effect=_clear)
    sel.entity_description = SelectEntityDescription(
        key="charger_ev_charger_charge_mode", options=["sun", "sun_tariff", "now", "off"])
    sel._charger_id = "ev_charger"
    sel._config_key = "charge_mode"
    sel._value = "sun_tariff"
    sel.hass = MagicMock()
    sel._entry = MagicMock()
    return sel


@pytest.mark.asyncio
async def test_picking_now_starts_a_timed_now_until_the_next_block():
    sel = _select()
    with patch.object(sel, "async_write_ha_state"):
        await sel.async_select_option("now")
    sel.coordinator.set_plan_override.assert_called_once_with(
        "ev_charger", "force", 95, po.USER_NOW)
    assert sel.current_option == "now"
    assert sel.extra_state_attributes["now_until"] is not None
    # the stored strategy is untouched: the plan resumes it at the end
    assert sel.coordinator.config["ev_chargers"][0]["charge_mode"] == "min_plus_solar"


@pytest.mark.asyncio
async def test_picking_another_mode_ends_the_timed_now():
    sel = _select()
    with patch.object(sel, "async_write_ha_state"):
        await sel.async_select_option("now")
        with patch("custom_components.solar_energy_management.persist_per_charger_option") as w:
            await sel.async_select_option("sun")
    sel.coordinator.clear_plan_override.assert_called_once_with("ev_charger")
    w.assert_called_once()
    assert w.call_args.args[-1] == "sun"


@pytest.mark.asyncio
async def test_an_untimed_now_is_left_alone():
    """A charger already on the stored always_max ("until full") gets no
    timer: picking Now again changes nothing."""
    sel = _select(stored="always_max")
    with patch.object(sel, "async_write_ha_state"):
        await sel.async_select_option("now")
    sel.coordinator.set_plan_override.assert_not_called()


def test_the_select_shows_now_while_a_timed_now_runs():
    now = dt_util.utcnow()
    ov = po.set_override({}, "ev_charger", "force", now + timedelta(minutes=30), now)
    sel = _select(overrides=ov)
    assert sel._shown_mode("min_plus_solar") == "now"
    assert sel._shown_mode is not None
    sel.coordinator._plan_overrides = {}
    assert sel._shown_mode("min_plus_solar") == "sun_tariff"


def test_a_skip_is_not_now():
    now = dt_util.utcnow()
    ov = po.set_override({}, "ev_charger", "skip", now + timedelta(minutes=30), now)
    sel = _select(overrides=ov)
    assert sel._shown_mode("min_plus_solar") == "sun_tariff"
    assert sel.extra_state_attributes["now_until"] is None


def _coord_with_plan(blocks):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._energy_plan_shadow = {"blocks": blocks}
    return c


def _iso(dt):
    return dt.isoformat()


def test_now_ends_at_the_next_block_for_this_charger():
    now = dt_util.utcnow().replace(microsecond=0)
    c = _coord_with_plan([
        {"id": "ev:ev_charger", "start": _iso(now + timedelta(hours=3)), "end": _iso(now + timedelta(hours=5))},
        {"id": "ev:other", "start": _iso(now + timedelta(hours=1)), "end": _iso(now + timedelta(hours=2))},
    ])
    assert c.now_minutes_for("ev_charger", now) == 180


def test_without_a_block_ahead_now_runs_two_hours():
    """(#1381 D22) Another device's block never sets Now's end."""
    now = dt_util.utcnow().replace(microsecond=0)
    c = _coord_with_plan([
        {"id": "battery", "start": _iso(now - timedelta(hours=1)), "end": _iso(now + timedelta(hours=4))},
    ])
    assert c.now_minutes_for("ev_charger", now) == 120


def test_without_a_plan_now_runs_two_hours():
    c = _coord_with_plan([])
    assert c.now_minutes_for("ev_charger") == 120
    c._energy_plan_shadow = None
    assert c.now_minutes_for("ev_charger") == 120


def test_now_stays_inside_the_override_bounds():
    now = dt_util.utcnow().replace(microsecond=0)
    c = _coord_with_plan([
        {"id": "ev:ev_charger", "start": _iso(now + timedelta(days=3)), "end": _iso(now + timedelta(days=3, hours=1))},
    ])
    assert c.now_minutes_for("ev_charger", now) == 24 * 60
