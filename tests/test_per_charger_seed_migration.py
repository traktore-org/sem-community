"""Tests for the v3→v4 per-charger seeding migration (#255).

Seeds each charger's per-charger value from the matching global where unset, so a
later removal of the duplicate global EV settings never silently resets a user's
configured value. Behaviour-neutral today (per-charger already falls back to global).
"""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management import async_migrate_entry
from custom_components.solar_energy_management.config_flow import SolarEnergyManagementConfigFlow

# (#758) The chain ends at whatever the config flow declares — see the note
# in test_config_flow_migration.py.
CURRENT = SolarEnergyManagementConfigFlow.VERSION


def _entry(options, data=None, version=3):
    e = MagicMock()
    e.version = version
    e.minor_version = 1
    e.options = options
    e.data = data or {}
    return e


def _seeded_charger(mock_hass, idx=0):
    kwargs = mock_hass.config_entries.async_update_entry.call_args.kwargs
    return kwargs["options"]["ev_chargers"][idx], kwargs


@pytest.mark.asyncio
async def test_seeds_all_eight_from_global():
    hass = MagicMock()
    entry = _entry(
        # #446: pair ev_target_type="soc" with a real vehicle_soc_entity so
        # the v10→v11 cleanup leaves it intact. This test exercises the
        # v4→v5 seed contract, not the v10→v11 cleanup.
        options={"ev_chargers": [{"id": "ev_charger", "name": "EV",
                                  "vehicle_soc_entity": "sensor.car_soc"}]},
        data={
            "daily_ev_target": 8, "daily_ev_target_max": 50,
            "ev_target_soc": 70, "ev_target_soc_max": 90,
            "ev_min_current": 6, "ev_night_initial_current": 10,
            "ev_kwh_per_100km": 18, "ev_target_type": "soc",
        },
    )
    assert await async_migrate_entry(hass, entry) is True
    c, kwargs = _seeded_charger(hass)
    assert kwargs["version"] == CURRENT
    assert c["daily_ev_target"] == 8
    assert c["daily_ev_target_max"] == 50
    assert c["ev_target_soc"] == 70
    assert c["ev_target_soc_max"] == 90
    assert c["ev_min_current"] == 6
    # (#441) v9→v10 renamed ev_night_initial_current → initial_current
    assert c["initial_current"] == 10
    assert c["ev_kwh_per_100km"] == 18
    assert c["ev_target_type"] == "soc"


@pytest.mark.asyncio
async def test_does_not_overwrite_explicit_per_charger():
    hass = MagicMock()
    entry = _entry(
        options={"ev_chargers": [{"id": "c1", "daily_ev_target": 12}]},
        data={"daily_ev_target": 8},
    )
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    assert c["daily_ev_target"] == 12  # explicit per-charger value preserved


@pytest.mark.asyncio
async def test_target_type_legacy_alias_seeded():
    hass = MagicMock()
    entry = _entry(
        # #446: pair the legacy "soc" alias with a real vehicle_soc_entity
        # so the v10→v11 cleanup leaves it intact (the seed is the
        # contract being tested here, not the cleanup).
        options={"ev_chargers": [{"id": "c1",
                                  "vehicle_soc_entity": "sensor.car_soc"}]},
        data={"ev_target_mode": "soc"},  # legacy alias, no ev_target_type
    )
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    assert c["ev_target_type"] == "soc"


@pytest.mark.asyncio
async def test_global_in_options_is_seeded():
    hass = MagicMock()
    entry = _entry(
        options={"daily_ev_target": 9, "ev_chargers": [{"id": "c1"}]},
        data={},
    )
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    assert c["daily_ev_target"] == 9


@pytest.mark.asyncio
async def test_no_chargers_is_safe_and_bumps_version():
    hass = MagicMock()
    entry = _entry(options={}, data={"daily_ev_target": 8})
    assert await async_migrate_entry(hass, entry) is True
    assert hass.config_entries.async_update_entry.call_args.kwargs["version"] == CURRENT


@pytest.mark.asyncio
async def test_unset_global_not_seeded():
    hass = MagicMock()
    entry = _entry(options={"ev_chargers": [{"id": "c1"}]}, data={})
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    # nothing to seed from → charger keeps only its identity keys
    assert "daily_ev_target" not in c


@pytest.mark.asyncio
async def test_phase4_phases_seeded_charging_mode_dropped():
    """#255 Phase 4 seeded ev_charging_mode + ev_phases per-charger.
    #277 Phase C's v6→v7 migration drops ev_charging_mode (the named
    ``charge_mode`` is authoritative); ev_phases is unchanged."""
    hass = MagicMock()
    entry = _entry(
        options={"ev_chargers": [{"id": "c1"}]},
        data={"ev_charging_mode": "minpv", "ev_phases": 1},
    )
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    assert c["ev_phases"] == 1
    # Phase C: dropped by the v6→v7 step.
    assert "ev_charging_mode" not in c
    # Phase A/B/C derivation chain: minpv + factory-default-ish state
    # → catch-all min_plus_solar.
    assert c["charge_mode"] == "min_plus_solar"


def test_phase4_globals_removed_from_descriptions():
    """The converted globals are no longer global entities (#255 Phase 4)."""
    from custom_components.solar_energy_management.number import NUMBER_TYPES
    from custom_components.solar_energy_management.select import SELECT_TYPES
    assert "ev_phases" not in {n.key for n in NUMBER_TYPES}
    assert "ev_charging_mode" not in {s.key for s in SELECT_TYPES}
    # ev_stall_cooldown removed (dead: value never read)
    assert "ev_stall_cooldown" not in {n.key for n in NUMBER_TYPES}
