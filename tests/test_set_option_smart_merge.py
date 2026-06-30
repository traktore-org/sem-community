"""Contract tests for the set_option service helpers (#462/#464).

The actual ``solar_energy_management.set_option`` service handler is a
closure inside ``_async_register_phase_services`` in ``__init__.py`` —
hard to test directly without a full HA harness. So the structural
pieces it depends on are pulled out to module-level pure helpers:

* ``_merge_ev_chargers_by_id`` — smart-merge to prevent the #464
  cross-talk where a partial Config-card submit could drop sibling
  chargers.
* ``_coerce_switch_on`` — YAML-string-safe switch intent (#485 G3).
* ``_SET_OPTION_STRUCTURAL_KEYS`` — the source-of-truth set.

These tests lock the contract behind those three names so future edits
can't silently regress the #464 cross-talk or the #462 reload-on-every-
tweak behavior.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management import (
    _SET_OPTION_STRUCTURAL_KEYS,
    _coerce_switch_on,
    _merge_ev_chargers_by_id,
)


# ─────────────────────────────────────────────────────────────────
# _merge_ev_chargers_by_id — the #464 cross-talk fix
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMergeEvChargersById:
    """The smart-merge contract.

    Bug being fixed: in v1.7.2 the set_option service did a naïve
    full-replace of ``ev_chargers``. If the Config card's cached
    ``_options`` was stale or only contained the changed charger,
    saving back dropped the sibling — and the next reload came up
    missing it. Reported as #464 "Both Chargers reacht on config
    changes of one charger".
    """

    def test_single_charger_field_update_preserves_other_fields(self):
        """An update touching one field on one charger keeps the rest."""
        existing = [
            {"id": "A", "name": "Garage", "charge_mode": "off",
             "ev_target_soc": 80, "vehicle_soc_entity": "sensor.car_a_soc"},
        ]
        incoming = [
            {"id": "A", "ev_target_soc": 90},
        ]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert len(result) == 1
        a = result[0]
        assert a["id"] == "A"
        assert a["ev_target_soc"] == 90               # incoming wins
        assert a["name"] == "Garage"                  # preserved
        assert a["charge_mode"] == "off"              # preserved
        assert a["vehicle_soc_entity"] == "sensor.car_a_soc"  # preserved

    def test_partial_submit_preserves_sibling_charger(self):
        """The #464 reproducer — partial list must not drop siblings."""
        existing = [
            {"id": "A", "name": "Garage", "charge_mode": "min_plus_solar"},
            {"id": "B", "name": "Driveway", "charge_mode": "solar_only"},
        ]
        # User only changed charger A; UI only sends A.
        incoming = [
            {"id": "A", "charge_mode": "off"},
        ]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert len(result) == 2, "sibling charger B was dropped — #464 regression"
        by_id = {c["id"]: c for c in result}
        assert by_id["A"]["charge_mode"] == "off"
        assert by_id["B"]["charge_mode"] == "solar_only"
        assert by_id["B"]["name"] == "Driveway"

    def test_full_list_submit_works_as_before(self):
        """The "good citizen" path — Config card submits the full list."""
        existing = [
            {"id": "A", "charge_mode": "min_plus_solar"},
            {"id": "B", "charge_mode": "solar_only"},
        ]
        incoming = [
            {"id": "A", "charge_mode": "off"},
            {"id": "B", "charge_mode": "always_max"},
        ]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert len(result) == 2
        by_id = {c["id"]: c for c in result}
        assert by_id["A"]["charge_mode"] == "off"
        assert by_id["B"]["charge_mode"] == "always_max"

    def test_new_charger_appended(self):
        """A charger with a fresh id is added; existing ones unchanged."""
        existing = [
            {"id": "A", "charge_mode": "min_plus_solar"},
        ]
        incoming = [
            {"id": "B", "name": "Driveway", "charge_mode": "solar_only"},
        ]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert len(result) == 2
        by_id = {c["id"]: c for c in result}
        assert by_id["A"]["charge_mode"] == "min_plus_solar"   # preserved
        assert by_id["B"]["name"] == "Driveway"
        assert by_id["B"]["charge_mode"] == "solar_only"

    def test_empty_existing_takes_incoming(self):
        """First-time charger add — incoming becomes the canonical list."""
        result = _merge_ev_chargers_by_id([], [{"id": "A", "name": "Garage"}])
        assert result == [{"id": "A", "name": "Garage"}]

    def test_empty_incoming_returns_existing_clones(self):
        """No-op submit — existing chargers come through unchanged."""
        existing = [
            {"id": "A", "charge_mode": "off"},
            {"id": "B", "charge_mode": "solar_only"},
        ]
        result = _merge_ev_chargers_by_id(existing, [])
        assert len(result) == 2
        # Identity check — the returned dicts are FRESH copies, so
        # mutating one of them doesn't bleed back into ``existing``.
        result[0]["charge_mode"] = "always_max"
        assert existing[0]["charge_mode"] == "off"

    def test_incoming_without_id_is_dropped(self):
        """An incoming dict missing an id is dropped, not appended.

        Contract changed post-beta.4 (#462/#464 follow-up): id-less
        entries are untargetable by every per-charger write path, and at
        registration they get assigned a positional ``ev_charger_<idx>``
        id that can collide with a real sibling — a ghost charger. The
        Config card's nested editors used to materialize exactly this
        shape (``newChargers[idx] = {}``).
        """
        existing = [{"id": "A", "charge_mode": "off"}]
        incoming = [{"name": "Stray", "charge_mode": "solar_only"}]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert len(result) == 1
        # Existing 'A' preserved; stray ghost dropped
        assert result[0].get("id") == "A"
        assert not any(c.get("name") == "Stray" for c in result)

    def test_non_dict_entries_are_skipped(self):
        """Defensive — garbage entries on either side never raise."""
        existing = [{"id": "A", "charge_mode": "off"}, "not-a-dict", None]
        incoming = [None, {"id": "A", "charge_mode": "always_max"}, 42]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert len(result) == 1
        assert result[0]["id"] == "A"
        assert result[0]["charge_mode"] == "always_max"

    def test_none_inputs_treated_as_empty(self):
        """``None`` (the entry's ``options.get("ev_chargers")`` shape) is OK."""
        assert _merge_ev_chargers_by_id(None, None) == []
        assert _merge_ev_chargers_by_id(None, [{"id": "A"}]) == [{"id": "A"}]
        assert _merge_ev_chargers_by_id([{"id": "A"}], None) == [{"id": "A"}]

    def test_merge_does_not_mutate_inputs(self):
        """Pure function — caller's lists/dicts stay intact."""
        existing = [{"id": "A", "name": "Garage", "charge_mode": "off"}]
        incoming = [{"id": "A", "charge_mode": "always_max"}]
        existing_snapshot = [dict(c) for c in existing]
        incoming_snapshot = [dict(c) for c in incoming]
        _merge_ev_chargers_by_id(existing, incoming)
        assert existing == existing_snapshot
        assert incoming == incoming_snapshot


# ─────────────────────────────────────────────────────────────────
# Merge order (#485 G2) — existing order is load-bearing
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMergeOrderPreserved:
    """Charger list order is load-bearing (#485 G2).

    Index 0 is the fleet primary for the strategy sensors and default
    surplus priorities derive from list position. The merge must keep
    the EXISTING order regardless of the incoming list's order or
    completeness — the pre-fix incoming-first iteration let a partial
    submit (or the setup-time heal, whose ``incoming`` is the poisoned
    options list) silently reorder the fleet.
    """

    def test_partial_submit_keeps_existing_order(self):
        existing = [{"id": "A", "name": "1"}, {"id": "B", "name": "2"}]
        incoming = [{"id": "B", "charge_mode": "off"}]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert [c["id"] for c in result] == ["A", "B"]
        assert result[1]["charge_mode"] == "off"

    def test_reversed_full_submit_keeps_existing_order(self):
        existing = [{"id": "A"}, {"id": "B"}]
        incoming = [{"id": "B", "x": 1}, {"id": "A", "y": 2}]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert [c["id"] for c in result] == ["A", "B"]
        assert result[0]["y"] == 2
        assert result[1]["x"] == 1

    def test_heal_shape_options_subset_keeps_data_order(self):
        """The heal calls merge(existing=data, incoming=options)."""
        data = [{"id": "A", "name": "1"}, {"id": "B", "name": "2"}]
        poisoned_options = [{"id": "B", "charge_mode": "solar_only"}]
        result = _merge_ev_chargers_by_id(data, poisoned_options)
        assert [c["id"] for c in result] == ["A", "B"]

    def test_new_chargers_append_in_incoming_order(self):
        existing = [{"id": "A"}]
        incoming = [{"id": "C"}, {"id": "B"}]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert [c["id"] for c in result] == ["A", "C", "B"]

    def test_duplicate_existing_ids_deduped_keeping_first(self):
        existing = [{"id": "A", "v": 1}, {"id": "A", "v": 2}]
        result = _merge_ev_chargers_by_id(existing, [])
        assert len(result) == 1
        assert result[0]["v"] == 1


# ─────────────────────────────────────────────────────────────────
# _coerce_switch_on (#485 G3) — YAML string truthiness
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCoerceSwitchOn:
    """set_option switch routing: string "off" must not turn ON."""

    @pytest.mark.parametrize("value", ["off", "Off", "OFF", "false", "0", "no", "", " off "])
    def test_falsy_strings_turn_off(self, value):
        assert _coerce_switch_on(value) is False

    @pytest.mark.parametrize("value", ["on", "true", "1", "yes", True, 1])
    def test_truthy_values_turn_on(self, value):
        assert _coerce_switch_on(value) is True

    @pytest.mark.parametrize("value", [False, 0, None])
    def test_falsy_natives_turn_off(self, value):
        assert _coerce_switch_on(value) is False


# ─────────────────────────────────────────────────────────────────
# _SET_OPTION_STRUCTURAL_KEYS — visibility lock
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestStructuralKeysVisibility:
    """The structural-key set is the contract — guard its identity."""

    def test_set_is_frozen(self):
        """frozenset so callers can't mutate it from the outside."""
        assert isinstance(_SET_OPTION_STRUCTURAL_KEYS, frozenset)

    def test_known_structural_members_present(self):
        """Adding a new entity-wiring key here is a contract change.

        Removing one is too. Both should be deliberate.
        """
        expected = {
            "battery_soc_sensor",
            "heat_pump_relay1_entity", "heat_pump_relay2_entity",
            "heat_pump_climate_entity", "heat_pump_power_sensor",
            "heat_pump_temperature_sensor",
            "heat_pump_invert_sg_ready",
            "hot_water_entity", "hot_water_power_sensor",
            "hot_water_temperature_sensor",
            "ev_chargers",
            "battery_force_discharge_control_entity",
            "battery_discharge_control_entity",  # #528 — discharge-limit (protection) entity
            "battery_force_discharge_entities",
            "battery_discharge_control_entities",
            "battery_strategy_entities",
            "battery_strategy_control_entity",
            "battery_setpoint_bidirectional",
        }
        assert _SET_OPTION_STRUCTURAL_KEYS == expected

    def test_common_tunables_not_in_structural(self):
        """Negative space — these must stay OUT of the reload set."""
        for k in (
            "charge_mode", "ev_target_soc", "daily_ev_target",
            "target_peak_limit", "tariff_mode", "minimum_solar_power",
            "night_charging", "observer_mode", "cheap_price_threshold",
        ):
            assert k not in _SET_OPTION_STRUCTURAL_KEYS, (
                f"'{k}' is a runtime tunable — adding it to the structural "
                "set would re-introduce the #462 reload-on-every-tweak bug."
            )
