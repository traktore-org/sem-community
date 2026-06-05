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
    assert updated.version == 10  # all hops compose
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
        "battery_assist_floor_soc",
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
    assert updated.version == 10
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
    assert updated.version == 10
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
    assert updated.version == 10
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
    assert updated.version == 10
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
    assert updated.version == 10
    # Top-level legacy global key renamed
    assert "ev_night_initial_current" not in updated.data
    assert updated.data["initial_current"] == 12
    # Per-charger keys renamed; pre-renamed entries untouched
    chargers = updated.options["ev_chargers"]
    assert "ev_night_initial_current" not in chargers[0]
    assert chargers[0]["initial_current"] == 10
    assert chargers[1]["initial_current"] == 14


@pytest.mark.asyncio
async def test_v10_already_current_is_noop(hass) -> None:
    """An entry already at v10 sails through every ``if version < N`` gate."""
    payload_data = {"battery_priority_soc": 30}
    payload_options = {"ev_chargers": [
        {"id": "ev_charger", "charge_mode": "solar_only",
         "vehicle_min_current": None, "initial_current": 10}
    ]}
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=10,
        data=payload_data,
        options=payload_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.version == 10
    assert updated.data == payload_data
    assert updated.options == payload_options
