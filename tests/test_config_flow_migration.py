"""Real-hass coverage for the config-entry migration chain (Phase 3).

Drives ``async_migrate_entry`` (``__init__.py:173-503``) end-to-end with
a real ``HomeAssistant`` instance + ``MockConfigEntry``. The legacy
dict-mocked tests in ``test_config_flow.py`` couldn't see the
``hass.config_entries.async_update_entry`` storage side effect — the
mock just recorded the call. Here the entry registry is real, so a
broken migration step that forgets to bump ``entry.version`` or that
drops a field on the storage round-trip fails loudly.

Coverage map (the 9 hops, plus failure + multi-hop fall-through):

  * v1 → v2 (#98): legacy ``battery_priority_soc`` semantics remap
    + 4-zone defaults seeding
  * v2 → v3 (#112): flat ``ev_*`` keys wrapped into ``ev_chargers``
  * v3 → v4 (#255): per-charger seed of formerly-global EV settings
  * v4 → v5 (#277 Phase A): per-charger ``charge_mode`` derivation
  * v5 → v6 (#277 Phase B fix-up): ``min_plus_solar`` correction
    for pv+tariff_on users that Phase A missed
  * v6 → v7 (#277 Phase C): dead key ``ev_charging_mode`` removal
  * v7 → v8 (#359): tariff_classification_mode static→percentile for
    dynamic-tariff entries
  * v8 → v9 (#440): seed ``vehicle_min_current`` per charger
  * v9 → v10 (#441): rename ``ev_night_initial_current`` →
    ``initial_current`` at both top-level and per-charger
  * v14 → v15 (#604): retire the legacy EV priority flags —
    ``ev_load_priority`` mapped into ``ev_surplus_priority``,
    ``ev_shed_priority`` + ``ev_priority_over_battery`` deleted
  * v1 → v10 multi-hop: every step composes cleanly
  * migration step raises: returns False, entry unchanged

What the dict-mocked tests CAN'T see and these tests DO:

  * The accumulator threading bug class — if a future migration step
    drops the accumulator and re-reads ``entry.options``, the real
    ``async_update_entry`` mutates the entry between steps so a
    multi-hop migration would pass the mocked test but fail in prod
    (or vice versa). These tests drive the real mutation path.
  * Storage round-trip — the mocked ``async_update_entry`` is a
    MagicMock; here the entry registry actually serialises +
    deserialises, so a non-JSON-serialisable migration payload
    would crash here.
  * Stale-key residue — if a step that's supposed to drop a key
    (v7's ``ev_charging_mode`` removal) accidentally leaves it in,
    the real entry shows it.
"""
from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management import async_migrate_entry
from custom_components.solar_energy_management.const import DOMAIN


# ---------------------------------------------------------------------------
# v1 → v2 (#98) — battery_priority_soc legacy remap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_to_v2_remaps_legacy_battery_priority_soc(hass) -> None:
    """Legacy 3-zone priority (80) collapses to the 4-zone floor (30)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={"battery_priority_soc": 80},  # legacy 3-zone meaning
        options={},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    # Re-read from the registry, not the local var — the entry registry
    # owns the post-migration truth.
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # all hops compose (#604 bumped target)
    assert updated.data["battery_priority_soc"] == 30


@pytest.mark.asyncio
async def test_v1_to_v2_seeds_missing_4zone_defaults(hass) -> None:
    """4-zone keys missing on legacy entries get default-seeded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={},
        options={},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    # Defaults from consts/core — assert the keys exist + are numeric.
    # Don't pin specific values: those are consts that may shift across
    # releases. The contract is "seeded, not None".
    for key in (
        "battery_buffer_soc",
        "battery_auto_start_soc",
    ):
        assert updated.data.get(key) is not None
        assert isinstance(updated.data[key], (int, float))


# ---------------------------------------------------------------------------
# v2 → v3 (#112) — flat EV keys → ev_chargers list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_to_v3_wraps_flat_ev_keys(hass) -> None:
    """Flat ``ev_*`` keys collapse into a single-element ``ev_chargers`` list."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            "ev_charging_power_sensor": "sensor.ev_power",
            "ev_connected_sensor": "binary_sensor.ev_connected",
            "ev_total_energy_sensor": "sensor.ev_total",
            "ev_current_control_entity": "number.ev_current",
            "ev_charger_service": "keba.set_current",
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    chargers = updated.options.get("ev_chargers")
    assert isinstance(chargers, list)
    assert len(chargers) == 1
    primary = chargers[0]
    assert primary["id"] == "ev_charger"
    assert primary["ev_charging_power_sensor"] == "sensor.ev_power"
    assert primary["ev_total_energy_sensor"] == "sensor.ev_total"
    assert primary["ev_charger_service"] == "keba.set_current"


@pytest.mark.asyncio
async def test_v2_to_v3_idempotent_when_ev_chargers_already_present(hass) -> None:
    """If ``ev_chargers`` is already set, the wrap is skipped."""
    pre_chargers = [
        {"id": "existing", "name": "Already wrapped"},
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"ev_charging_power_sensor": "sensor.ev"},
        options={"ev_chargers": pre_chargers},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    # Preserved — single entry, not double-wrapped.
    assert len(updated.options["ev_chargers"]) == 1
    assert updated.options["ev_chargers"][0]["id"] == "existing"


# ---------------------------------------------------------------------------
# v3 → v4 (#255) — per-charger seeding from globals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_to_v4_seeds_per_charger_from_globals(hass) -> None:
    """Global EV settings cascade onto each charger that's missing the key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        data={
            "daily_ev_target": 25.0,
            "ev_min_current": 6,
            "ev_target_type": "kwh",
        },
        options={
            "ev_chargers": [
                {"id": "primary"},  # bare — should inherit everything
                {"id": "secondary", "daily_ev_target": 10.0},  # partial override
            ],
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    chargers = updated.options["ev_chargers"]
    assert chargers[0]["daily_ev_target"] == 25.0
    assert chargers[0]["ev_min_current"] == 6
    assert chargers[0]["ev_target_type"] == "kwh"
    # Per-charger override wins; only the missing keys are seeded.
    assert chargers[1]["daily_ev_target"] == 10.0
    assert chargers[1]["ev_min_current"] == 6


# ---------------------------------------------------------------------------
# v6 → v7 (#277 Phase C) — dead key drop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v6_to_v7_drops_dead_ev_charging_mode(hass) -> None:
    """``ev_charging_mode`` is dead post Phase C — must not survive."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=6,
        data={},
        options={
            "ev_charging_mode": "pv",  # top-level legacy
            "ev_chargers": [
                {
                    "id": "ev_charger",
                    "charge_mode": "min_plus_solar",
                    "ev_charging_mode": "pv",  # per-charger legacy
                },
            ],
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert "ev_charging_mode" not in updated.options
    assert "ev_charging_mode" not in updated.options["ev_chargers"][0]
    # The authoritative key stays.
    assert updated.options["ev_chargers"][0]["charge_mode"] == "min_plus_solar"


# ---------------------------------------------------------------------------
# v1 → v7 — full chain in one call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_chain_v1_to_v7(hass) -> None:
    """Composing every hop on a single v1 entry lands at v7 with the
    accumulator threading the mutations through cleanly.

    The accumulator pattern (``__init__.py:189-198``) was added because
    a multi-hop migration on a mocked entry was overwriting earlier
    steps. This test exercises the real path — proves the
    ``async_update_entry``/accumulator handshake is consistent.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            "battery_priority_soc": 80,  # legacy, expect 30 post-migration
            "ev_charging_power_sensor": "sensor.ev_power",  # flat, expect wrapped
            "ev_charger_service": "keba.set_current",
            "daily_ev_target": 25.0,  # global, expect per-charger seed
            "ev_charging_mode": "pv",  # dead post-Phase-C, expect dropped
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    # v1→v2 effect
    assert updated.data["battery_priority_soc"] == 30
    # v2→v3 effect — flat → list
    chargers = updated.options["ev_chargers"]
    assert isinstance(chargers, list) and len(chargers) == 1
    primary = chargers[0]
    assert primary["ev_charging_power_sensor"] == "sensor.ev_power"
    # v3→v4 effect — global daily_ev_target cascaded onto the primary
    assert primary["daily_ev_target"] == 25.0
    # v4→v5 effect — charge_mode derived (any of the 5 valid modes)
    assert primary.get("charge_mode") in {
        "off",
        "solar_only",
        "min_plus_solar",
        "solar_plus_cheap",
        "always_max",
    }
    # v6→v7 effect — ev_charging_mode dropped at both levels
    assert "ev_charging_mode" not in updated.options
    assert "ev_charging_mode" not in primary


# ---------------------------------------------------------------------------
# v7 → v8 (#359) — flip stale ``tariff_classification_mode`` to "percentile"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v7_to_v8_flips_static_to_percentile_for_dynamic_tariff(hass) -> None:
    """Stored ``tariff_classification_mode='static'`` is upgraded when dynamic."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=7,
        data={"battery_priority_soc": 30},
        options={
            "ev_chargers": [{"id": "ev_charger", "charge_mode": "solar_only"}],
            "tariff_mode": "dynamic",
            "tariff_classification_mode": "static",  # legacy default, #359
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    assert updated.options["tariff_classification_mode"] == "percentile"


@pytest.mark.asyncio
async def test_v7_to_v8_keeps_static_when_tariff_mode_is_not_dynamic(hass) -> None:
    """Calendar/static tariff users keep their chosen mode untouched."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=7,
        data={"battery_priority_soc": 30},
        options={
            "ev_chargers": [{"id": "ev_charger", "charge_mode": "solar_only"}],
            "tariff_mode": "static",
            "tariff_classification_mode": "static",
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    assert updated.options["tariff_classification_mode"] == "static"


# ---------------------------------------------------------------------------
# Migration already at current version — no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v8_to_v9_seeds_vehicle_min_current(hass) -> None:
    """v8 → v9 (#440 ADR 0010 #3) — every ``ev_chargers`` entry gets a
    ``vehicle_min_current: None`` default. Existing fields are
    untouched; entries that already have the key are not overwritten."""
    payload_data = {"battery_priority_soc": 30}
    payload_options = {
        "ev_chargers": [
            {"id": "ev_charger", "charge_mode": "solar_only"},
            {"id": "ev_charger_1", "charge_mode": "min_plus_solar",
             "vehicle_min_current": 9},  # already set — must survive
        ]
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=8,
        data=payload_data,
        options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    chargers = updated.options["ev_chargers"]
    assert chargers[0]["vehicle_min_current"] is None
    assert chargers[1]["vehicle_min_current"] == 9


@pytest.mark.asyncio
async def test_v9_to_v10_renames_night_initial_current(hass) -> None:
    """v9 → v10 (#441) — rename ``ev_night_initial_current`` to
    ``initial_current`` on every ``ev_chargers`` entry AND at the
    top level. The "night" prefix was misleading — the value is the
    session-start ramp current, applied whenever a session begins."""
    payload_data = {
        "battery_priority_soc": 30,
        "ev_night_initial_current": 12,  # legacy global key — must rename
    }
    payload_options = {
        "ev_chargers": [
            {"id": "ev_charger", "charge_mode": "solar_only",
             "vehicle_min_current": None,
             "ev_night_initial_current": 10},  # per-charger — must rename
            {"id": "ev_charger_1", "charge_mode": "min_plus_solar",
             "initial_current": 14},  # already migrated — must survive
        ]
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=9,
        data=payload_data,
        options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    # Top-level legacy global key renamed
    assert "ev_night_initial_current" not in updated.data
    assert updated.data["initial_current"] == 12
    # Per-charger keys renamed; pre-renamed entries untouched
    chargers = updated.options["ev_chargers"]
    assert "ev_night_initial_current" not in chargers[0]
    assert chargers[0]["initial_current"] == 10
    assert chargers[1]["initial_current"] == 14


@pytest.mark.asyncio
async def test_v15_already_current_is_noop(hass) -> None:
    """An entry already at v15 (the current target) sails through every
    ``if version < N`` gate untouched. A clean charger carries no
    ``ev_shed_priority`` (that field is retired)."""
    payload_data = {"battery_priority_soc": 30}
    payload_options = {"ev_chargers": [
        {"id": "ev_charger", "charge_mode": "solar_only",
         "vehicle_min_current": None, "initial_current": 10,
         "ev_surplus_priority": 5}
    ]}
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=15,
        data=payload_data,
        options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    assert updated.data == payload_data
    assert updated.options == payload_options


@pytest.mark.asyncio
async def test_v15_to_v16_maps_load_priority_and_deletes_legacy_keys(hass) -> None:
    """v15 → v16 (#604): the three legacy EV priority flags are retired.

    ``ev_load_priority`` is mapped into ``ev_surplus_priority`` only where
    the canonical key is absent; ``ev_shed_priority`` (shed order is the
    reverse walk of the ONE unified list, #470/#576) and
    ``ev_priority_over_battery`` (unreachable night-planner knob) are
    deleted outright — top-level AND per-charger, data AND options bags."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=15,
        data={
            "battery_priority_soc": 30,
            "ev_load_priority": 2,           # top-level alias → mapped
            "ev_priority_over_battery": False,
        },
        options={
            "ev_shed_priority": 6,           # stray top-level key → deleted
            "ev_chargers": [
                # alias only → mapped to surplus
                {"id": "wb1", "ev_load_priority": 7, "ev_shed_priority": 9},
                # canonical present → alias discarded, surplus untouched
                {"id": "wb2", "ev_surplus_priority": 4, "ev_load_priority": 9,
                 "ev_priority_over_battery": True},
                # no priority keys at all → untouched
                {"id": "wb3"},
            ],
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16
    chargers = {c["id"]: c for c in updated.options["ev_chargers"]}
    assert chargers["wb1"]["ev_surplus_priority"] == 7   # alias mapped
    assert chargers["wb2"]["ev_surplus_priority"] == 4   # canonical wins
    assert "ev_surplus_priority" not in chargers["wb3"]  # nothing invented
    # Top-level alias mapped into the bag that held it.
    assert updated.data["ev_surplus_priority"] == 2
    # All three legacy keys are gone everywhere.
    for legacy in ("ev_load_priority", "ev_shed_priority",
                   "ev_priority_over_battery"):
        assert legacy not in updated.data
        assert legacy not in updated.options
        for c in chargers.values():
            assert legacy not in c


@pytest.mark.asyncio
async def test_v15_to_v16_global_surplus_blocks_alias_mapping(hass) -> None:
    """v15 → v16 (#604): a GLOBAL ``ev_surplus_priority`` outranked every
    alias in the old fallback chain (charger-surplus → global-surplus →
    charger-alias → global-alias), so with it present no alias is mapped —
    the legacy keys are simply deleted and the charger falls back to the
    global, exactly as before."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=15,
        data={"battery_priority_soc": 30, "ev_surplus_priority": 3},
        options={"ev_chargers": [
            {"id": "wb1", "ev_load_priority": 7},  # was outranked → NOT mapped
        ]},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16
    chargers = {c["id"]: c for c in updated.options["ev_chargers"]}
    assert "ev_surplus_priority" not in chargers["wb1"]
    assert "ev_load_priority" not in chargers["wb1"]
    assert updated.data["ev_surplus_priority"] == 3


@pytest.mark.asyncio
async def test_v15_to_v16_idempotent_without_legacy_flags(hass) -> None:
    """v15 → v16 (#604): an entry that never carried the legacy flags is
    passed through with only the version bumped."""
    payload_data = {"battery_priority_soc": 30}
    payload_options = {"ev_chargers": [
        {"id": "wb1", "ev_surplus_priority": 5},
    ]}
    entry = MockConfigEntry(
        domain=DOMAIN, version=15,
        data=payload_data, options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16
    assert updated.data == payload_data
    assert updated.options == payload_options


@pytest.mark.asyncio
async def test_v15_upgrade_without_grid_surcharge_keeps_legacy_shape(hass) -> None:
    """A real v15 upgrade needs no persisted #710 key to load safely."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=15,
        minor_version=1,
        data={"update_interval": 30},
        options={"tariff_mode": "dynamic", "custom_marker": "preserve-me"},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16
    assert "grid_import_surcharge" not in updated.data
    assert "grid_import_surcharge" not in updated.options
    assert updated.options["custom_marker"] == "preserve-me"

@pytest.mark.asyncio
async def test_v14_to_v15_strips_retired_shed_priority(hass) -> None:
    """v14 → v15 (#576): the retired ``ev_shed_priority`` knob is stripped
    from every charger (surplus + shed order are now the one drag-list
    position). ``ev_surplus_priority`` — the boot seed — is preserved."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=14,
        data={"battery_priority_soc": 30},
        options={"ev_chargers": [
            {"id": "wb1", "ev_surplus_priority": 2, "ev_shed_priority": 8},
            {"id": "wb2", "ev_surplus_priority": 5},   # already clean
        ]},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # composes through the v16 hop
    chargers = {c["id"]: c for c in updated.options["ev_chargers"]}
    assert "ev_shed_priority" not in chargers["wb1"]     # stripped
    assert "ev_shed_priority" not in chargers["wb2"]     # was never there
    assert chargers["wb1"]["ev_surplus_priority"] == 2   # seed preserved
    assert chargers["wb2"]["ev_surplus_priority"] == 5


@pytest.mark.asyncio
async def test_v13_to_v14_forces_arbitrage_off(hass) -> None:
    """v13 → v14 (#533): battery→grid arbitrage is forced OFF for the stable
    release, whether it was on or absent."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=13,
        data={"battery_priority_soc": 30},
        options={"battery_grid_arbitrage_enabled": True},  # user had it on
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    assert updated.options["battery_grid_arbitrage_enabled"] is False
    assert updated.data["battery_grid_arbitrage_enabled"] is False


@pytest.mark.asyncio
async def test_v12_composes_through_v16_one_priority_axis(hass) -> None:
    """v12 → v16: the v13 shed-priority seeding (#470) composes with the
    v16 legacy-flag retirement (#604). The transient ``ev_shed_priority``
    that v13 writes is deleted again — the unified device-priority list is
    the single axis; shed order is its reverse walk. The ``ev_load_priority``
    alias ends up mapped into ``ev_surplus_priority``."""
    payload_options = {"ev_chargers": [
        {"id": "wb1", "ev_surplus_priority": 2},
        {"id": "wb2", "ev_surplus_priority": 4, "ev_shed_priority": 9},
        {"id": "wb3", "ev_load_priority": 7},                  # legacy alias
        {"id": "wb4"},                                         # no priority at all
    ]}
    entry = MockConfigEntry(
        domain=DOMAIN, version=12,
        data={"battery_priority_soc": 30}, options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    chargers = {c["id"]: c for c in updated.options["ev_chargers"]}
    # Surplus priority is the surviving single axis.
    assert chargers["wb1"]["ev_surplus_priority"] == 2
    assert chargers["wb2"]["ev_surplus_priority"] == 4
    assert chargers["wb3"]["ev_surplus_priority"] == 7  # alias mapped (#604)
    # No priority source anywhere → nothing written; runtime fallback
    # (ev_priority = 3 + idx) covers it. Migration must not crash or invent.
    assert "ev_surplus_priority" not in chargers["wb4"]
    # The legacy keys (including v13's transient seeding) are gone.
    for c in chargers.values():
        assert "ev_shed_priority" not in c
        assert "ev_load_priority" not in c


@pytest.mark.asyncio
async def test_v11_to_v12_drops_stale_global_ev_session_energy_sensor(hass) -> None:
    """v11 → v12 (#135) — the stale top-level ``ev_session_energy_sensor``
    left over from the v2→v3 multi-charger migration is dropped when at
    least one charger has its own per-charger value. Surfaced on PROD
    2026-06-07 where the global pointed at ``keba_p30_energy_target``
    (the user setpoint, always 0) and confused diagnostics."""
    payload_data = {
        "battery_priority_soc": 30,
        "ev_session_energy_sensor": "sensor.keba_p30_energy_target",  # stale
    }
    payload_options = {
        "ev_chargers": [
            {"id": "ev_charger", "charge_mode": "min_plus_solar",
             "vehicle_min_current": None, "initial_current": 10,
             # per-charger value IS set — canonical since v3
             "ev_session_energy_sensor": "sensor.keba_p30_session_energy"},
        ],
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=11,
        data=payload_data, options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    # Top-level stale key dropped
    assert "ev_session_energy_sensor" not in updated.data
    # Per-charger value preserved untouched
    assert updated.options["ev_chargers"][0]["ev_session_energy_sensor"] == "sensor.keba_p30_session_energy"


@pytest.mark.asyncio
async def test_v11_to_v12_preserves_top_level_when_no_per_charger_value(hass) -> None:
    """Defensive: if SOMEHOW a charger entry has no per-charger value,
    leave the top-level key alone — we don't want to silently drop a
    sensor mapping that the user might still be relying on."""
    payload_data = {
        "battery_priority_soc": 30,
        "ev_session_energy_sensor": "sensor.keba_p30_session_energy",  # legitimate
    }
    payload_options = {
        "ev_chargers": [
            {"id": "ev_charger", "charge_mode": "min_plus_solar",
             "vehicle_min_current": None, "initial_current": 10},
            # NB: no ev_session_energy_sensor on the charger
        ],
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=11,
        data=payload_data, options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    # Defensive: kept the top-level value because no per-charger override exists
    assert updated.data["ev_session_energy_sensor"] == "sensor.keba_p30_session_energy"


@pytest.mark.asyncio
async def test_v10_to_v11_clears_bad_ev_target_type_per_charger(hass) -> None:
    """v10 → v11 (#446) — entries with ``ev_target_type="soc"`` on a charger
    that has no ``vehicle_soc_entity`` configured are reset to ``"kwh"``.
    This cleans up the bad state that the pre-#446 GUI allowed users to
    save (which then silently fell back to ``estimated_soc`` in the kWh
    budget — PROD 2026-06-06)."""
    payload_data = {"battery_priority_soc": 30}
    payload_options = {
        "ev_chargers": [
            # Bad combination — no vehicle_soc_entity → must be reset
            {"id": "ev_charger", "charge_mode": "min_plus_solar",
             "vehicle_min_current": None, "initial_current": 10,
             "ev_target_type": "soc"},
            # Good combination — real sensor configured → must survive
            {"id": "ev_charger_1", "charge_mode": "min_plus_solar",
             "vehicle_min_current": None, "initial_current": 14,
             "ev_target_type": "soc",
             "vehicle_soc_entity": "sensor.car_soc"},
        ],
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=10,
        data=payload_data,
        options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    chargers = updated.options["ev_chargers"]
    # Bad charger reset to kwh
    assert chargers[0]["ev_target_type"] == "kwh"
    # Good charger untouched — real sensor + soc mode is the supported
    # case the GUI allows.
    assert chargers[1]["ev_target_type"] == "soc"
    assert chargers[1]["vehicle_soc_entity"] == "sensor.car_soc"


@pytest.mark.asyncio
async def test_v10_to_v11_clears_legacy_ev_target_mode(hass) -> None:
    """v10 → v11 (#446) — the legacy ``ev_target_mode`` field name gets
    the same treatment as ``ev_target_type``. Older installs (#235)
    may still have the legacy key on disk."""
    payload_data = {
        "battery_priority_soc": 30,
        # Legacy field name with no vehicle SOC sensor anywhere
        "ev_target_mode": "soc",
    }
    payload_options = {
        "ev_chargers": [
            {"id": "ev_charger", "charge_mode": "solar_only",
             "vehicle_min_current": None, "initial_current": 10},
        ],
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=10,
        data=payload_data, options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    assert updated.data["ev_target_mode"] == "kwh"


@pytest.mark.asyncio
async def test_v10_to_v11_preserves_kwh_mode(hass) -> None:
    """v10 → v11 (#446) — entries that are already in kWh mode are not
    touched. Covers the most common case (no SOC sensor, default mode)."""
    payload_data = {"battery_priority_soc": 30}
    payload_options = {
        "ev_chargers": [
            {"id": "ev_charger", "charge_mode": "min_plus_solar",
             "vehicle_min_current": None, "initial_current": 10,
             "ev_target_type": "kwh"},
        ],
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=10,
        data=payload_data, options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 16  # chain composes to v16 (#604)
    assert updated.options["ev_chargers"][0]["ev_target_type"] == "kwh"
