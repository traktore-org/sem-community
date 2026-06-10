"""Contract tests for the set_option service helpers (#462/#464).

The actual ``solar_energy_management.set_option`` service handler is a
closure inside ``_async_register_phase_services`` in ``__init__.py`` —
hard to test directly without a full HA harness. So the structural
pieces it depends on are pulled out to module-level pure helpers:

* ``_merge_ev_chargers_by_id`` — smart-merge to prevent the #464
  cross-talk where a partial Config-card submit could drop sibling
  chargers.
* ``_set_option_needs_reload`` — gate that determines whether a write
  is structural (needs reload) or a runtime tunable (in-memory mirror
  is sufficient). Restores the per-charger select.py-style
  skip-reload optimization for the service path so a Config-card
  tweak doesn't destroy + recreate the coordinator on every change.
* ``_SET_OPTION_STRUCTURAL_KEYS`` — the source-of-truth set.

These tests lock the contract behind those three names so future edits
can't silently regress the #464 cross-talk or the #462 reload-on-every-
tweak behavior.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management import (
    _SET_OPTION_STRUCTURAL_KEYS,
    _merge_ev_chargers_by_id,
    _set_option_needs_reload,
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
# _set_option_needs_reload — the #462 reload-scope gate
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSetOptionNeedsReload:
    """Reload gate for the set_option service path.

    Background: v1.7.2-beta.2 added an always-reload to ``set_option``
    so heat-pump entity rewires (#448) would take effect. Side effect:
    every Config-card tunable tweak (mode/threshold/switch) triggered
    a full coordinator reload, destroying the SensorReader's split-
    grid discovery state (candidate root cause for #461) and the
    per-charger context across the multi-charger loop (candidate for
    #462/#464). The gate restores the in-memory mirror for non-
    structural keys.
    """

    def test_heat_pump_entity_keys_need_reload(self):
        """Structural entity-wiring keys still force a reload (#448 path)."""
        assert _set_option_needs_reload(["heat_pump_relay1_entity"])
        assert _set_option_needs_reload(["heat_pump_relay2_entity"])
        assert _set_option_needs_reload(["heat_pump_climate_entity"])
        assert _set_option_needs_reload(["heat_pump_temperature_sensor"])
        assert _set_option_needs_reload(["heat_pump_power_sensor"])

    def test_hot_water_entity_keys_need_reload(self):
        """Hot water wiring keys reload too (#454 path)."""
        assert _set_option_needs_reload(["hot_water_entity"])
        assert _set_option_needs_reload(["hot_water_temperature_sensor"])
        assert _set_option_needs_reload(["hot_water_power_sensor"])

    def test_ev_chargers_list_needs_reload(self):
        """List-shape changes need reload so actuator bindings refresh."""
        assert _set_option_needs_reload(["ev_chargers"])

    def test_runtime_tunables_skip_reload(self):
        """Modes / thresholds / switches don't reload — coordinator reads them each cycle."""
        # Numbers
        assert not _set_option_needs_reload(["ev_target_soc"])
        assert not _set_option_needs_reload(["daily_ev_target"])
        assert not _set_option_needs_reload(["target_peak_limit"])
        assert not _set_option_needs_reload(["cheap_price_threshold"])
        assert not _set_option_needs_reload(["minimum_solar_power"])
        # Modes
        assert not _set_option_needs_reload(["charge_mode"])
        assert not _set_option_needs_reload(["tariff_mode"])
        # Switches
        assert not _set_option_needs_reload(["observer_mode"])
        assert not _set_option_needs_reload(["night_charging"])
        # Multi-key tunable batch
        assert not _set_option_needs_reload([
            "ev_target_soc", "daily_ev_target", "target_peak_limit",
        ])

    def test_mixed_payload_reloads_when_any_key_structural(self):
        """One structural key in a mixed batch is enough to force reload."""
        assert _set_option_needs_reload([
            "ev_target_soc", "heat_pump_relay1_entity",
        ])
        assert _set_option_needs_reload([
            "charge_mode", "hot_water_entity",
        ])

    def test_empty_payload_does_not_reload(self):
        """No keys = no reload (caller short-circuits earlier anyway)."""
        assert not _set_option_needs_reload([])

    def test_keys_accept_any_iterable(self):
        """Accepts list, set, dict_keys, generator — caller-friendly."""
        assert _set_option_needs_reload({"ev_chargers"})
        assert _set_option_needs_reload({"ev_chargers": None}.keys())
        assert _set_option_needs_reload(k for k in ("ev_chargers",))


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
            "heat_pump_relay1_entity", "heat_pump_relay2_entity",
            "heat_pump_climate_entity", "heat_pump_power_sensor",
            "heat_pump_temperature_sensor",
            "hot_water_entity", "hot_water_power_sensor",
            "hot_water_temperature_sensor",
            "ev_chargers",
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
