"""#1421 — a new charger took a removed charger's id, and its sessions.

A new charger got the first free id (``ev_charger``, ``ev_charger_1``, …).
That could be the id of a charger removed before. SEM keeps a charger's data
under its id and keeps it after the charger goes: the charging sessions (the
session list, the month totals, the Excel file), the taper and car-battery
estimate, the day counters, the entities and their history. So the new
charger showed the removed charger's sessions as its own. A heat pump added
to the Configure dialog took a removed pump's number the same way, with its
day runtime and meter reading.

Now a new unit takes an id its kind never had: setup notes every id in
SEM's store, the store also reads the ids it keeps data under (a unit
removed before the note existed), and every place that makes a new id asks
``unit_ids.next_unit_id`` (the Configure dialog, the System card through
``get_config``'s ``charger_ids_used``).
"""
from __future__ import annotations

import json
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.unit_ids import (
    CHARGERS,
    HEAT_PUMPS,
    next_unit_id,
    used_unit_ids,
)


def _storage(energy=None, daily=None):
    from custom_components.solar_energy_management.coordinator.storage import (
        SEMStorage,
    )
    s = SEMStorage(MagicMock(), "e1")
    s._energy_data = energy or {}
    s._daily_data = daily or {}
    return s


SESSION = {"timestamp": "2026-11-20T17:52:00+01:00", "charger_id": "ev_charger_1",
           "energy_kwh": 12.0}


# ── the id rule ──────────────────────────────────────────────────────────

class TestNextUnitId:

    def test_a_charger_id_is_one_no_charger_had(self):
        assert next_unit_id(CHARGERS, []) == "ev_charger"
        assert next_unit_id(CHARGERS, ["ev_charger"]) == "ev_charger_1"
        # ev_charger_1 was removed: its id stays taken
        assert next_unit_id(CHARGERS, ["ev_charger", "ev_charger_1"]) == "ev_charger_2"

    def test_the_dialog_numbers_from_the_list_length(self):
        """The Configure dialog's numbering is kept: the list's length first."""
        assert next_unit_id(CHARGERS, [], start=0) == "ev_charger_0"
        assert next_unit_id(CHARGERS, ["ev_charger", "ev_charger_1"], start=1) == "ev_charger_2"

    def test_a_heat_pump_row_never_takes_the_primary(self):
        assert next_unit_id(HEAT_PUMPS, []) == "heat_pump_2"
        assert next_unit_id(HEAT_PUMPS, ["heat_pump", "heat_pump_2"]) == "heat_pump_3"


# ── what SEM's store says was used ───────────────────────────────────────

class TestStoreIds:

    def test_a_removed_chargers_sessions_keep_its_id(self):
        """A charger removed before the note existed: its sessions count."""
        s = _storage({"ev_intelligence": {"session_history": [SESSION, {"energy_kwh": 1}]}})
        assert s.unit_ids_used(CHARGERS) == {"ev_charger_1"}

    def test_its_car_estimate_and_day_counters_keep_it_too(self):
        s = _storage({"ev_intelligence": {"chargers": {"old_a": {}}}},
                     {"per_charger_daily": {"date": {"old_b": "2026-11-20"},
                                            "values": {}, "calendar": {"old_c": {}}}})
        assert s.unit_ids_used(CHARGERS) == {"old_a", "old_b", "old_c"}

    def test_a_noted_id_counts_with_no_data_under_it(self):
        s = _storage()
        assert s.note_unit_ids(CHARGERS, {"ev_charger", "ev_charger_1"}) is True
        assert s.note_unit_ids(CHARGERS, ["ev_charger"]) is False   # nothing new
        assert s.unit_ids_used(CHARGERS) == {"ev_charger", "ev_charger_1"}
        assert s.unit_ids_used(HEAT_PUMPS) == set()

    def test_the_note_survives_the_json_store(self):
        """HA's store writes JSON: a list of strings, read back the same."""
        s = _storage()
        s.note_unit_ids(CHARGERS, {"ev_charger_1"})
        s.note_unit_ids(HEAT_PUMPS, {"heat_pump_2"})
        back = _storage(json.loads(json.dumps(s._energy_data)))
        assert back.unit_ids_used(CHARGERS) == {"ev_charger_1"}
        assert back.unit_ids_used(HEAT_PUMPS) == {"heat_pump_2"}

    def test_a_heat_pumps_day_runtime_keeps_its_number(self):
        s = _storage(daily={"device_runtimes": {"heat_pump_2": {}, "pool_pump": {},
                                                "heat_pump": {}}})
        assert s.unit_ids_used(HEAT_PUMPS) == {"heat_pump_2"}

    def test_a_bad_part_hides_no_other(self):
        """``ev_intelligence: None`` made the session read raise: the note
        must still answer."""
        s = _storage({"unit_ids_used": {CHARGERS: ["ev_charger_1", 7, None]},
                      "ev_intelligence": None})
        assert s.unit_ids_used(CHARGERS) == {"ev_charger_1"}

    def test_a_heat_pumps_learned_rows_keep_its_number_past_midnight(self):
        """device_runtimes is cleared at midnight; the COP curve, the drift
        rows and the month, year and lifetime kWh are not."""
        s = _storage({"cop_learn_state": {"heat_pump_2": {}},
                      "drift_state": {"heat_pump_3": {}, "pool": {}}},
                     {"monthly_accumulators": {"device:heat_pump_4_2026_11": 3.0,
                                               "device:heat_pump_2026_11": 2.0,
                                               "device:heat_pump#sg3_2026_11": 1.0,
                                               "device:heat_pump_5#sg3_2026_11": 1.0},
                      "yearly_accumulators": {"device:heat_pump_2026": 5.0},
                      "lifetime_accumulators": {"device:heat_pump_6": 9.0, "solar": 1.0}})
        assert s.unit_ids_used(HEAT_PUMPS) == {
            "heat_pump_2", "heat_pump_3", "heat_pump_4", "heat_pump_5", "heat_pump_6"}

    def test_a_bad_record_is_no_answer_not_a_crash(self):
        s = _storage({"unit_ids_used": ["ev_charger"],
                      "ev_intelligence": {"chargers": ["x"], "session_history": [None]}},
                     {"per_charger_daily": "x", "device_runtimes": []})
        assert s.unit_ids_used(CHARGERS) == set()
        assert s.unit_ids_used(HEAT_PUMPS) == set()
        assert s.note_unit_ids(CHARGERS, {"a"}) is True
        assert s.unit_ids_used(CHARGERS) == {"a"}


class TestUsedUnitIds:

    def _entry(self, data=None, options=None, storage=None):
        return SimpleNamespace(data=data or {}, options=options or {},
                               runtime_data=SimpleNamespace(_storage=storage))

    def test_the_lists_the_refs_and_the_store(self):
        entry = self._entry(
            data={"ev_chargers": [{"id": "a"}]},
            options={"ev_chargers": [{"id": "b"}, "junk"],
                     "ev_charger_refs": [{"id": "c"}]},
            storage=_storage({"ev_intelligence": {"session_history": [SESSION]}}))
        assert used_unit_ids(entry, CHARGERS) == {"a", "b", "c", "ev_charger_1"}

    def test_a_read_only_mapping_is_read(self):
        """HA hands entry.data and entry.options as a mappingproxy."""
        from types import MappingProxyType
        entry = SimpleNamespace(data=MappingProxyType({"ev_chargers": [{"id": "a"}]}),
                                options=MappingProxyType({}), runtime_data=None)
        assert used_unit_ids(entry, CHARGERS) == {"a"}

    def test_a_store_with_no_real_answer_adds_nothing(self):
        """``set |= MagicMock()`` turns the set into a mock that iterates
        empty: the saved ids must stay."""
        entry = SimpleNamespace(data={}, options={"ev_chargers": [{"id": "a"}]},
                                runtime_data=MagicMock())
        assert used_unit_ids(entry, CHARGERS) == {"a"}

    def test_no_store_answers_with_the_lists(self):
        entry = self._entry(options={"heat_pumps": [{"id": "heat_pump_3"}]})
        assert used_unit_ids(entry, HEAT_PUMPS) == {"heat_pump_3"}
        assert used_unit_ids(None, CHARGERS) == set()


# ── the Configure dialog ─────────────────────────────────────────────────

def _flow(monkeypatch, options, storage, devices=None):
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
    flow._data = {}
    flow.hass = MagicMock(config=None, data={})
    coordinator = SimpleNamespace(_storage=storage, _ev_devices=devices or {})
    entry = SimpleNamespace(data={}, options=dict(options), entry_id="e1",
                            runtime_data=coordinator)
    monkeypatch.setattr(OptionsFlowHandler, "config_entry",
                        property(lambda self: entry), raising=False)
    flow.async_step_ev_charger_menu = AsyncMock(return_value={"type": "menu"})
    return flow


@pytest.mark.asyncio
async def test_the_dialog_add_skips_a_charger_removed_before(monkeypatch):
    """The removed ev_charger_1 left its sessions; the list holds one charger.
    The old dialog numbered from the length: ev_charger_1 again."""
    flow = _flow(monkeypatch, {"ev_chargers": [{"id": "ev_charger", "name": "A"}]},
                 _storage({"ev_intelligence": {"session_history": [SESSION]}}))
    flow._discovered_pv_strings = lambda: {}
    flow._data["ev_chargers"] = [{"id": "ev_charger", "name": "A"}]
    await flow.async_step_ev_charger_add({
        "charger_name": "New",
        "ev_connected_sensor": "binary_sensor.n_plug",
        "ev_charging_sensor": "binary_sensor.n_charging",
        "ev_charging_power_sensor": "sensor.n_power"})
    assert [c["id"] for c in flow._data["ev_chargers"]] == ["ev_charger", "ev_charger_2"]


@pytest.mark.asyncio
async def test_the_first_charger_page_after_the_last_was_removed(monkeypatch):
    """Refs exist and the list is empty: the last charger was removed, and
    this is a new charger, not the removed ev_charger."""
    storage = _storage()
    storage.note_unit_ids(CHARGERS, {"ev_charger"})
    flow = _flow(monkeypatch, {"ev_chargers": [], "ev_charger_refs": []}, storage)
    flow._data["ev_chargers"] = []
    await flow.async_step_ev_charger({"ev_charging_power_sensor": "sensor.p"})
    assert [c["id"] for c in flow._data["ev_chargers"]] == ["ev_charger_1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("devices", [{"ev_charger": object()}, {}])
async def test_the_flat_key_charger_keeps_its_id_on_the_first_page(monkeypatch, devices):
    """A save from before charger refs, with no list: setup builds its
    flat-key charger as ev_charger, so the page describes that charger and
    keeps the id and its sessions — also on a run that did not build it
    (a skipped or failed build)."""
    storage = _storage()
    storage.note_unit_ids(CHARGERS, {"ev_charger"})
    flow = _flow(monkeypatch, {}, storage, devices=devices)
    await flow.async_step_ev_charger({"ev_charging_power_sensor": "sensor.p"})
    assert [c["id"] for c in flow._data["ev_chargers"]] == ["ev_charger"]


@pytest.mark.asyncio
async def test_a_new_heat_pump_skips_a_removed_pumps_number():
    """heat_pump_2 was removed today; its day runtime and meter reading stay
    under the id. The old add took the lowest free number: heat_pump_2."""
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    storage = _storage(daily={"device_runtimes": {"heat_pump_2": {
        "accumulated_sec": 3600, "counter_baseline_kwh": 4120.5,
        "meter_day": "2026-11-24"}}})
    stub = SimpleNamespace(
        _data={}, _edit_hp_index=None, shown=None,
        config_entry=SimpleNamespace(data={}, options={"heat_pumps": []},
                                     runtime_data=SimpleNamespace(_storage=storage)))
    stub.async_show_form = MethodType(lambda self, **kw: {"type": "form", **kw}, stub)
    stub.async_step_heat_pump_menu = AsyncMock(return_value={"type": "menu"})
    await MethodType(OptionsFlowHandler.async_step_heat_pump_unit, stub)(
        {"heat_pump_climate_entity": "climate.shed"})
    assert [(p["id"], p["name"]) for p in stub._data["heat_pumps"]] == [
        ("heat_pump_3", "Heat Pump 3")]


# ── the reporter's path, through the real setup ──────────────────────────

@pytest.mark.asyncio
async def test_remove_then_add_never_hands_over_the_removed_id(
        sem_real_hass, monkeypatch):
    """Two chargers; ev_charger_1 charged once and is removed with the
    card's ✕ (the real service and reload). Then a new charger: the card's
    list (``get_config``) and the dialog both keep ev_charger_1 out."""
    from custom_components.solar_energy_management.const import DOMAIN

    from .test_1144_saved_site_limit import _unload
    from .test_1149_second_charger_own_wiring import GO
    from .test_1154_removed_first_charger_flat_keys import (
        FIRST,
        _entry,
        _remove,
        _set_up,
    )
    hass = sem_real_hass
    entry = _entry(hass, [FIRST, GO])
    devs = await _set_up(hass, entry)
    try:
        assert list(devs) == ["ev_charger", "ev_charger_1"]
        entry.runtime_data._storage.add_session_to_history(dict(SESSION))
        await _remove(hass, entry, "ev_charger_1", monkeypatch)
        assert list(entry.runtime_data._ev_devices) == ["ev_charger"]
        # the new lifetime read its store from disk: the note came through
        assert "ev_charger_1" in entry.runtime_data._storage._energy_data[
            "unit_ids_used"][CHARGERS]

        resp = await hass.services.async_call(
            DOMAIN, "get_config", {}, blocking=True, return_response=True)
        assert {"ev_charger", "ev_charger_1"} <= set(resp["charger_ids_used"])
        assert "charger_ids_used" not in resp["config"]

        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )
        flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
        flow.hass = hass
        flow._data = {"ev_chargers": [dict(c) for c in entry.options.get(
            "ev_chargers") or entry.data.get("ev_chargers")]}
        flow._discovered_pv_strings = lambda: {}
        flow.async_step_ev_charger_menu = AsyncMock(return_value={"type": "menu"})
        monkeypatch.setattr(OptionsFlowHandler, "config_entry",
                            property(lambda self: entry), raising=False)
        await flow.async_step_ev_charger_add({
            "charger_name": "New",
            "ev_connected_sensor": "binary_sensor.n_plug",
            "ev_charging_sensor": "binary_sensor.n_charging",
            "ev_charging_power_sensor": "sensor.n_power"})
        assert [c["id"] for c in flow._data["ev_chargers"]] == ["ev_charger", "ev_charger_2"]
    finally:
        await _unload(hass, entry)
