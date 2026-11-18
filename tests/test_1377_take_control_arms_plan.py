"""(#1377) Letting SEM take control also turns plan execution on.

One owner: the watch-only switch's turn-off. The card button and a service
call both land there. Turning watch-only ON never touches plan execution.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.switch import SwitchEntityDescription

from custom_components.solar_energy_management.switch import SEMSolarSwitch

PLAN = "switch.sem_energy_plan_actuation"


def _switch(hass, coordinator):
    sw = SEMSolarSwitch(
        coordinator, SwitchEntityDescription(key="observer_mode"), "entry")
    sw.hass = hass
    sw.async_write_ha_state = MagicMock()
    sw._persist_flag = MagicMock()      # entry writes are covered elsewhere
    return sw


@pytest.fixture
def coordinator():
    c = MagicMock()
    c.async_request_refresh = AsyncMock()
    c.config_entry.options = {}
    c.config_entry.data = {}
    return c


@pytest.fixture
def plan_calls(hass):
    calls = []

    async def _turn_on(call):
        calls.append(call.data["entity_id"])

    hass.services.async_register("switch", "turn_on", _turn_on)
    return calls


async def test_take_control_turns_plan_execution_on(hass, coordinator, plan_calls, caplog):
    hass.states.async_set(PLAN, "off")
    sw = _switch(hass, coordinator)
    sw._is_on = True
    with caplog.at_level("INFO"):
        await sw.async_turn_off()
    assert plan_calls == [PLAN]
    assert "turning on plan execution" in caplog.text
    assert coordinator._observer_mode is False


async def test_plan_execution_already_on_is_left_alone(hass, coordinator, plan_calls):
    hass.states.async_set(PLAN, "on")
    sw = _switch(hass, coordinator)
    sw._is_on = True
    await sw.async_turn_off()
    assert plan_calls == []


async def test_watch_only_on_leaves_plan_execution_alone(hass, coordinator, plan_calls):
    hass.states.async_set(PLAN, "off")
    sw = _switch(hass, coordinator)
    sw._is_on = False
    await sw.async_turn_on()
    assert plan_calls == []
    assert coordinator._observer_mode is True


async def test_no_plan_switch_entity_is_fine(hass, coordinator, plan_calls):
    sw = _switch(hass, coordinator)
    sw._is_on = True
    await sw.async_turn_off()
    assert plan_calls == []
    assert sw._is_on is False


async def test_a_failing_plan_switch_does_not_undo_the_handover(hass, coordinator):
    async def _boom(call):
        raise RuntimeError("no")

    hass.services.async_register("switch", "turn_on", _boom)
    hass.states.async_set(PLAN, "off")
    sw = _switch(hass, coordinator)
    sw._is_on = True
    await sw.async_turn_off()
    assert sw._is_on is False
    assert coordinator._observer_mode is False


async def test_restore_and_reload_never_arm_plan_execution(hass, coordinator, plan_calls):
    """Only a turn-off someone asks for flips plan execution. Startup restore,
    an options reload and migrations set state without going through it."""
    from types import SimpleNamespace
    hass.states.async_set(PLAN, "off")
    sw = _switch(hass, coordinator)
    sw._apply_restored_state(SimpleNamespace(state="off"))
    assert sw._is_on is False
    assert plan_calls == []
    assert hass.states.get(PLAN).state == "off"
