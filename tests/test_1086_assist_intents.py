"""#1086 Part A — Assist explain/write intents.

Exercises the real ``homeassistant.helpers.intent`` dispatch
(``intent.async_handle``), not a hand-built ``Intent`` object — the
same path Assist itself uses once a sentence resolves to one of these
intent types.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.assist_intents import (
    INTENT_GOOD_TO_CHARGE,
    INTENT_SET_TARGET_SOC,
    INTENT_TONIGHT_COST,
    INTENT_WHY_BATTERY,
    INTENT_WHY_CHARGER,
    async_register_intents,
)
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator.decision_log import (
    DecisionLog,
    KIND_BATTERY,
)


def _fake_coordinator(hass, **config):
    coord = SimpleNamespace()
    coord.hass = hass
    coord.config = config
    coord.decision_log = DecisionLog()
    coord._battery_adapters = {}
    coord._energy_plan_shadow = None
    return coord


def _add_entry(hass, coordinator):
    entry = MockConfigEntry(domain=DOMAIN, title="SEM")
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    return entry


@pytest.fixture(autouse=True)
def _register(hass):
    async_register_intents(hass)


async def test_why_battery_with_no_decision_logged_says_no_answer(hass):
    _add_entry(hass, _fake_coordinator(hass))
    response = await intent.async_handle(hass, "test", INTENT_WHY_BATTERY, {})
    assert "don't have an answer" in response.speech["plain"]["speech"]


async def test_why_battery_reads_the_last_decision(hass):
    coordinator = _fake_coordinator(hass)
    coordinator.decision_log.record(
        device_id="primary", kind=KIND_BATTERY, verb="normal",
        reason_code="battery_normal", text="holding steady",
        quiet_first_rest=False)
    _add_entry(hass, coordinator)
    response = await intent.async_handle(hass, "test", INTENT_WHY_BATTERY, {})
    speech = response.speech["plain"]["speech"]
    assert speech and "don't have an answer" not in speech


async def test_why_charger_with_no_chargers_configured(hass):
    _add_entry(hass, _fake_coordinator(hass))
    response = await intent.async_handle(hass, "test", INTENT_WHY_CHARGER, {})
    assert "don't have an answer" in response.speech["plain"]["speech"]


async def test_why_charger_unknown_name_declines_rather_than_guesses(hass):
    coordinator = _fake_coordinator(
        hass, ev_chargers=[{"id": "c1", "name": "Carport"}])
    _add_entry(hass, coordinator)
    response = await intent.async_handle(
        hass, "test", INTENT_WHY_CHARGER, {"name": {"value": "Garage"}})
    assert "don't know which charger" in response.speech["plain"]["speech"]


async def test_tonight_cost_reads_the_stamped_plan(hass):
    coordinator = _fake_coordinator(hass)
    coordinator._energy_plan_shadow = {"total_cost": 1.23, "slots": []}
    _add_entry(hass, coordinator)
    response = await intent.async_handle(hass, "test", INTENT_TONIGHT_COST, {})
    assert "1.23" in response.speech["plain"]["speech"]


async def test_tonight_cost_with_no_plan_says_so(hass):
    _add_entry(hass, _fake_coordinator(hass))
    response = await intent.async_handle(hass, "test", INTENT_TONIGHT_COST, {})
    assert "don't have tonight's plan" in response.speech["plain"]["speech"]


async def test_good_to_charge_now_reads_the_current_slot(hass):
    from homeassistant.util import dt as dt_util
    now = dt_util.now()
    coordinator = _fake_coordinator(hass)
    coordinator._energy_plan_shadow = {"slots": [{
        "start": (now - timedelta(minutes=5)).isoformat(),
        "end": (now + timedelta(minutes=25)).isoformat(),
        "cheap": True,
    }]}
    _add_entry(hass, coordinator)
    response = await intent.async_handle(hass, "test", INTENT_GOOD_TO_CHARGE, {})
    assert "cheap hour" in response.speech["plain"]["speech"]
    assert "not" not in response.speech["plain"]["speech"]


async def test_good_to_charge_now_with_no_matching_slot(hass):
    coordinator = _fake_coordinator(hass)
    coordinator._energy_plan_shadow = {"slots": []}
    _add_entry(hass, coordinator)
    response = await intent.async_handle(hass, "test", INTENT_GOOD_TO_CHARGE, {})
    assert "don't have a plan" in response.speech["plain"]["speech"]


async def test_set_target_soc_refused_while_write_intents_are_off(hass):
    coordinator = _fake_coordinator(
        hass, ev_chargers=[{"id": "c1", "name": "Carport"}],
        assist_write_intents_enabled=False)
    _add_entry(hass, coordinator)
    response = await intent.async_handle(
        hass, "test", INTENT_SET_TARGET_SOC, {"percent": {"value": 80}})
    assert "read-only" in response.speech["plain"]["speech"]


async def test_set_target_soc_writes_when_enabled(hass, monkeypatch):
    coordinator = _fake_coordinator(
        hass, ev_chargers=[{"id": "c1", "name": "Carport"}],
        assist_write_intents_enabled=True)
    _add_entry(hass, coordinator)
    calls = []
    monkeypatch.setattr(
        "custom_components.solar_energy_management.persist_per_charger_option",
        lambda hass_, entry_, coord_, cid, key, value: calls.append(
            (cid, key, value)))
    response = await intent.async_handle(
        hass, "test", INTENT_SET_TARGET_SOC,
        {"name": {"value": "Carport"}, "percent": {"value": 80}})
    assert calls == [("c1", "ev_target_soc", 80.0)]
    assert response.response_type == intent.IntentResponseType.ACTION_DONE
    assert "80" in response.speech["plain"]["speech"]


async def test_set_target_soc_unknown_charger_declines(hass):
    coordinator = _fake_coordinator(
        hass, ev_chargers=[{"id": "c1", "name": "Carport"}],
        assist_write_intents_enabled=True)
    _add_entry(hass, coordinator)
    response = await intent.async_handle(
        hass, "test", INTENT_SET_TARGET_SOC,
        {"name": {"value": "Garage"}, "percent": {"value": 80}})
    assert "don't know which charger" in response.speech["plain"]["speech"]
