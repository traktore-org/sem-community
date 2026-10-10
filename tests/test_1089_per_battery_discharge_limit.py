"""#1089 — two batteries, one discharge-limit field.

SEM limits each battery through its own slot of
``battery_discharge_control_entities`` (#523, read by
``_per_battery_config``), but neither screen could write that list: the
Config tab and Configure both showed the ONE shared entity. Two Sessys, one
picked: SEM limited the first and the second kept discharging into the car
(@RienduPre, #1078). Bug class 30 — a key the runtime honours with no field.

Pinned here:

* Configure shows one page per battery after the battery page, writes the
  list, empties a slot, and keeps a saved list on a one-battery home;
* what the page writes is what ``_per_battery_config`` hands each battery;
* every per-battery list ``_per_battery_config`` reads has a per-battery row
  on the Config tab (the class guard — the next list key cannot ship
  without a field).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.config_flow import (
    OPTIONS_FLOW_OWNED_KEYS,
    OptionsFlowHandler,
)
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    effective_battery_count,
)

ROOT = Path(__file__).resolve().parent.parent
LIST_KEY = "battery_discharge_control_entities"
FIELD = "battery_discharge_limit_entity"


def _coordinator(slugs, sources=()):
    reader = SimpleNamespace(
        _energy_dashboard_config=SimpleNamespace(battery_power_list=list(sources)))
    return SimpleNamespace(battery_control_slugs=slugs, _sensor_reader=reader)


def _flow(mock_hass, config_entry, options, coordinator=None):
    config_entry.options = options
    mock_hass.data = {DOMAIN: {config_entry.entry_id: coordinator}} if coordinator else {}
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    return flow


async def _page(flow, config_entry, user_input=None):
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: config_entry)):
        result = await flow.async_step_settings_battery_limit(user_input)
    if result.get("type") == "form":
        flow.cur_step = result          # what HA records for the next reply
    return result


def _suggested(result):
    marker = next(m for m in result["data_schema"].schema if m.schema == FIELD)
    return marker.description["suggested_value"]


class TestConfigureHasOneFieldPerBattery:
    @pytest.mark.asyncio
    async def test_the_battery_page_leads_to_the_first_battery(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {}, _coordinator(("b1", "b2")))
        with patch.object(type(flow), "config_entry",
                          new_callable=lambda: property(lambda self: config_entry)):
            result = await flow.async_step_settings({"battery_priority_soc": 30})
        assert result["step_id"] == "settings_battery_limit"
        assert result["description_placeholders"]["battery"] == "B1"

    @pytest.mark.asyncio
    async def test_two_batteries_two_pages_one_list(self, mock_hass, config_entry):
        """The reporter's home: the first Sessy keeps the shared entity, the
        second gets its own."""
        flow = _flow(mock_hass, config_entry, {}, _coordinator(
            ("b1", "b2"), ("sensor.sessy_a_power", "sensor.sessy_b_power")))
        first = await _page(flow, config_entry)
        assert first["step_id"] == "settings_battery_limit"
        assert first["description_placeholders"] == {
            "battery": "B1", "sensor": "sensor.sessy_a_power"}
        second = await _page(flow, config_entry, {})
        assert second["step_id"] == "settings_battery_limit"
        assert second["description_placeholders"] == {
            "battery": "B2", "sensor": "sensor.sessy_b_power"}
        done = await _page(flow, config_entry, {FIELD: "number.sessy_b_maximum_power"})
        assert done["step_id"] == "settings_ev"
        assert flow._data[LIST_KEY] == [None, "number.sessy_b_maximum_power"]

    @pytest.mark.asyncio
    async def test_a_saved_slot_is_shown_and_can_be_emptied(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry,
                     {LIST_KEY: ["number.a_limit", "number.b_limit"]},
                     _coordinator(("b1", "b2")))
        first = await _page(flow, config_entry)
        assert _suggested(first) == "number.a_limit"
        second = await _page(flow, config_entry, {FIELD: "number.a_limit"})
        assert _suggested(second) == "number.b_limit"
        await _page(flow, config_entry, {})          # B2 emptied
        assert flow._data[LIST_KEY] == ["number.a_limit", None]

    @pytest.mark.asyncio
    async def test_a_third_saved_slot_is_kept(self, mock_hass, config_entry):
        """Fewer batteries found today than the list holds: the page edits
        the slots it shows and drops none."""
        flow = _flow(mock_hass, config_entry,
                     {LIST_KEY: ["number.a", "number.b", "number.c"]},
                     _coordinator(("b1", "b2")))
        await _page(flow, config_entry)
        await _page(flow, config_entry, {FIELD: "number.a"})
        await _page(flow, config_entry, {FIELD: "number.b2"})
        assert flow._data[LIST_KEY] == ["number.a", "number.b2", "number.c"]

    @pytest.mark.asyncio
    async def test_without_the_coordinator_the_sensor_is_sems_own(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {}, _coordinator(("b1", "b2")))
        first = await _page(flow, config_entry)
        assert first["description_placeholders"]["sensor"] == "sensor.sem_battery_b1_power"

    @pytest.mark.asyncio
    async def test_one_battery_skips_the_page_and_keeps_the_list(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {LIST_KEY: ["number.a"]}, _coordinator(()))
        result = await _page(flow, config_entry)
        assert result["step_id"] == "settings_ev"
        assert flow._data[LIST_KEY] == ["number.a"]

    @pytest.mark.asyncio
    async def test_sem_not_loaded_skips_the_page(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {})
        result = await _page(flow, config_entry)
        assert result["step_id"] == "settings_ev"
        assert LIST_KEY not in flow._data

    @pytest.mark.asyncio
    async def test_the_save_keeps_the_list_when_the_page_was_skipped(
            self, mock_hass, config_entry):
        """The key is owned by the dialog (omitted = cleared), so a skipped
        page must hand the saved list to the final save itself."""
        flow = _flow(mock_hass, config_entry, {LIST_KEY: ["number.a", "number.b"]},
                     _coordinator(()))
        await _page(flow, config_entry)
        with patch.object(type(flow), "config_entry",
                          new_callable=lambda: property(lambda self: config_entry)):
            result = await flow.async_step_notifications(
                {"enable_charger_notifications": True})
        assert result["type"] == "create_entry"
        assert result["data"][LIST_KEY] == ["number.a", "number.b"]

    def test_the_keys_are_owned(self):
        assert LIST_KEY in OPTIONS_FLOW_OWNED_KEYS
        assert FIELD in OPTIONS_FLOW_OWNED_KEYS


class TestWhatThePageWritesReachesEachBattery:
    """Writer to reader (class 66): the list the page writes, read the way
    the adapters are built."""

    def _pbc(self, config, idx):
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = config
        coord.battery_control_slugs = ("b1", "b2")
        return coord._per_battery_config(idx, 2)

    @pytest.mark.asyncio
    async def test_the_second_battery_gets_its_own_limit(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {}, _coordinator(("b1", "b2")))
        await _page(flow, config_entry)
        await _page(flow, config_entry, {})
        await _page(flow, config_entry, {FIELD: "number.sessy_b_maximum_power"})
        config = {"battery_discharge_control_entity": "number.sessy_a_maximum_power",
                  LIST_KEY: flow._data[LIST_KEY]}
        views = [self._pbc(config, i) for i in range(2)]
        assert [v["battery_discharge_control_entity"] for v in views] == [
            "number.sessy_a_maximum_power", "number.sessy_b_maximum_power"]
        # Two surfaces now — each takes its share of the house, not one
        # battery the whole of it while the other runs free.
        assert effective_battery_count(views) == 2

    def test_before_the_fix_both_batteries_shared_one_entity(self):
        """The reported state: the one field, no list."""
        config = {"battery_discharge_control_entity": "number.sessy_a_maximum_power"}
        views = [self._pbc(config, i) for i in range(2)]
        assert {v["battery_discharge_control_entity"] for v in views} == {
            "number.sessy_a_maximum_power"}
        assert effective_battery_count(views) == 1


class TestEveryPerBatteryListHasARow:
    """Class 30 guard: a per-battery list the runtime reads must have a
    per-battery row on the Config tab."""

    @staticmethod
    def _overlaid_list_keys() -> set[str]:
        src = (ROOT / "coordinator" / "coordinator.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "_per_battery_config")
        keys = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Tuple) and len(node.elts) >= 2
                    and isinstance(node.elts[0], ast.Constant)
                    and str(node.elts[0].value).endswith("_entities")):
                keys.add(node.elts[0].value)
        return keys

    @staticmethod
    def _card_rows() -> set[str]:
        src = (ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js").read_text()
        return set(re.findall(r"_renderBatteryListPicker\(\s*'([a-z_]+)'", src))

    def test_the_scans_find_something(self):
        assert LIST_KEY in self._overlaid_list_keys()
        assert {"battery_force_discharge_entities", "battery_strategy_entities"} <= self._card_rows()

    def test_each_list_has_a_row(self):
        missing = self._overlaid_list_keys() - self._card_rows()
        assert not missing, (
            f"per-battery lists with no per-battery field on the Config tab: {sorted(missing)}")

    def test_the_built_card_has_the_rows(self):
        dist = (ROOT / "dashboard" / "card" / "dist" / "sem-cards.js").read_text()
        assert LIST_KEY in dist, "dist/sem-cards.js not rebuilt after #1089"
        assert "config_help_batt_discharge_entity_each" in dist
