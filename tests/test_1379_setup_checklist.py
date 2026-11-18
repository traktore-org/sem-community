"""#1379 — the first-run checklist the Home card draws.

It reads the same facts as the AI setup tool (#1086) and rides the charger
control diag sensor, so these tests drive ``build_setup_checklist`` with the
same kind of coordinator the #1086 tests use.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers import issue_registry as ir

from custom_components.solar_energy_management import llm as sem_llm
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.setup_status import (
    build_setup_checklist,
)


def _coord(hass, *, watch_only=True, entities=(), report=None, **config):
    return SimpleNamespace(
        hass=hass, config=config, _observer_mode=watch_only,
        _forecast_reader=SimpleNamespace(source=None),
        source_recommendation=MagicMock(return_value=None),
        _configured_entity_ids=lambda: set(entities),
        # (#1379) the hardware row reads only the solar/grid/battery entities
        _sensor_reader=SimpleNamespace(_energy_dashboard_config=SimpleNamespace(
            solar_power=(list(entities) or [None])[0], battery_power_list=[],
            battery_power_pairs=[])),
        _detection_report=report)


def _by_key(checklist):
    return {i["key"]: i for i in checklist["items"]}


async def test_fresh_watch_only_install_with_nothing(sem_real_hass):
    out = await build_setup_checklist(sem_real_hass, _coord(sem_real_hass))
    assert out["watch_only"] is True
    assert (out["done"], out["total"]) == (1, 5)  # only the dashboard
    assert out["must_open"] is False
    assert out["repairs"] == {"count": 0, "first": None, "titles": []}
    assert _by_key(out)["price"]["done"] is False


async def test_detected_but_unconfigured_charger_is_must_do(sem_real_hass):
    report = {"chargers": [{"configured": False, "platform": "keba",
                            "unit": "KEBA P30"}]}
    out = await build_setup_checklist(
        sem_real_hass, _coord(sem_real_hass, watch_only=False, report=report))
    charger = _by_key(out)["charger"]
    assert charger["done"] is False
    assert charger["detected"] == "KEBA P30"
    assert out["must_open"] is True


async def test_a_configured_charger_is_not_must_do_even_if_listed(sem_real_hass):
    report = {"chargers": [{"configured": True, "platform": "keba"}]}
    out = await build_setup_checklist(sem_real_hass, _coord(
        sem_real_hass, watch_only=False, report=report,
        ev_chargers=[{"id": "a", "name": "Garage"}]))
    assert _by_key(out)["charger"]["done"] is True
    assert out["must_open"] is False


async def test_nothing_detected_means_no_must_do(sem_real_hass):
    out = await build_setup_checklist(
        sem_real_hass, _coord(sem_real_hass, watch_only=False,
                              report={"chargers": []}))
    assert out["must_open"] is False
    assert _by_key(out)["charger"]["detected"] is None


async def test_all_done_and_in_control_needs_nothing(sem_real_hass):
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(sem_real_hass)
    reg.async_get_or_create("sensor", "huawei_solar", "pv", suggested_object_id="pv")
    coord = _coord(
        sem_real_hass, watch_only=False, entities=["sensor.pv"],
        ev_chargers=[{"id": "a"}], electricity_import_rate=0.3,
        report={"chargers": [{"configured": True}]})
    coord._forecast_reader = SimpleNamespace(source="forecast_solar")
    out = await build_setup_checklist(sem_real_hass, coord)
    assert (out["done"], out["total"]) == (5, 5)
    assert out["watch_only"] is False and out["must_open"] is False
    assert _by_key(out)["hardware"]["brands"] == ["huawei_solar"]


async def test_open_repairs_are_counted_with_the_first_title(sem_real_hass):
    sem_real_hass.config.language = "en"
    for name in ("first_issue", "second_issue"):
        ir.async_create_issue(
            sem_real_hass, DOMAIN, name, is_fixable=False,
            severity=ir.IssueSeverity.WARNING, translation_key=name)
    out = await build_setup_checklist(sem_real_hass, _coord(sem_real_hass))
    assert out["repairs"]["count"] == 2
    assert out["repairs"]["first"] in ("first_issue", "second_issue")
    # (#1321) every title is published, so the dashboard can name each one
    assert sorted(out["repairs"]["titles"]) == ["first_issue", "second_issue"]


async def test_ai_tool_and_checklist_read_the_same_facts(sem_real_hass):
    coord = _coord(sem_real_hass, ev_chargers=[{"id": "a", "name": "Garage"}],
                   electricity_import_rate=0.3)
    status = await sem_llm.build_setup_status(sem_real_hass, coord)
    out = await build_setup_checklist(sem_real_hass, coord)
    assert status["chargers"]["count"] == _by_key(out)["charger"]["count"] == 1
    assert status["tariff_configured"] is _by_key(out)["price"]["done"] is True
    assert status["watch_only"] is out["watch_only"] is True


def test_the_card_reads_the_checklist_off_the_charger_control_sensor(mock_coordinator):
    """No new entity: the checklist rides the diag sensor the Config card reads."""
    from homeassistant.components.sensor import SensorEntityDescription
    from custom_components.solar_energy_management.sensor import SEMSolarSensor
    checklist = {"watch_only": True, "items": [], "done": 1, "total": 5,
                 "must_open": False, "repairs": {"count": 0, "first": None}}
    mock_coordinator.data = {"diag_charger_control": "none",
                             "setup_checklist": checklist}
    sensor = SEMSolarSensor(
        coordinator=mock_coordinator,
        description=SensorEntityDescription(key="diag_charger_control", name="x"),
        entry_id="e")
    assert sensor.extra_state_attributes["setup_checklist"] == checklist


async def test_helpers_price_and_weather_are_not_hardware(sem_real_hass):
    """(#1379) .175 showed 'Huawei Solar · Input Boolean · Nordpool · …':
    only what SEM reads as solar, grid and battery power counts."""
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(sem_real_hass)
    reg.async_get_or_create("sensor", "huawei_solar", "pv2", suggested_object_id="pv2")
    reg.async_get_or_create("sensor", "nordpool", "price", suggested_object_id="price")
    reg.async_get_or_create("input_boolean", "input_boolean", "x", suggested_object_id="x")
    coord = _coord(sem_real_hass, entities=["sensor.pv2"])
    coord._configured_entity_ids = lambda: {"sensor.pv2", "sensor.price", "input_boolean.x"}
    out = await build_setup_checklist(sem_real_hass, coord)
    assert _by_key(out)["hardware"]["brands"] == ["huawei_solar"]
