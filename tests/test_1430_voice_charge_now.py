"""(#1430) A voice "charge now" is the user's own Now.

Since the four charge modes (#1381 D31), only the user's own Now may run a
charger that stands in Off or a pause. The Assist intent asked for a plain
``force`` without saying it was the user's, so on an Off charger nothing
happened while the speech said "Charging now". The intent now marks the
request as the user's, through the same coordinator entry point the mode
select uses, and the mode rule then lets it through for its minutes only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.assist_intents import (
    INTENT_FORCE_CHARGE_NOW,
    async_register_intents,
)
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.decision_log import DecisionLog


def _coordinator(hass):
    coord = SimpleNamespace()
    coord.hass = hass
    coord.config = {"ev_chargers": [{"id": "c1", "name": "Carport"}],
                    "assist_write_intents_enabled": True}
    coord.decision_log = DecisionLog()
    coord._battery_adapters = {}
    coord._energy_plan_shadow = None
    coord.set_plan_override = MagicMock()
    coord.clear_plan_override = MagicMock()
    coord._calendar_departure_for = MagicMock(return_value=None)
    return coord


@pytest.fixture(autouse=True)
def _register(hass):
    async_register_intents(hass)


async def test_voice_charge_now_is_marked_as_the_users_own_now(hass):
    coord = _coordinator(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="SEM")
    entry.add_to_hass(hass)
    entry.runtime_data = coord
    await intent.async_handle(
        hass, "test", INTENT_FORCE_CHARGE_NOW, {"minutes": {"value": 45}})
    coord.set_plan_override.assert_called_once()
    args, kwargs = coord.set_plan_override.call_args
    assert args == ("c1", "force", 45)
    assert kwargs.get("user_now") is True


def test_a_users_now_runs_an_off_charger_for_its_minutes_then_off_again():
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
    marked = po.set_override({}, "c1", "force", now + timedelta(minutes=45), now,
                             user_now=True)
    plain = po.set_override({}, "c1", "force", now + timedelta(minutes=45), now)
    # the voice request, marked as the user's: an Off charger charges
    assert po.charger_mode_for(marked, "c1", "off", now) == "always_max"
    # an unmarked force (a plan or an automation) leaves Off alone
    assert po.charger_mode_for(plain, "c1", "off", now) == "off"
    # after its minutes the charger is Off again
    later = now + timedelta(minutes=46)
    assert po.charger_mode_for(marked, "c1", "off", later) == "off"
