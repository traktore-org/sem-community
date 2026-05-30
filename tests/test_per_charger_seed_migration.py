"""Tests for the v3→v4 per-charger seeding migration (#255).

Seeds each charger's per-charger value from the matching global where unset, so a
later removal of the duplicate global EV settings never silently resets a user's
configured value. Behaviour-neutral today (per-charger already falls back to global).
"""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management import async_migrate_entry


def _entry(options, data=None, version=3):
    e = MagicMock()
    e.version = version
    e.minor_version = 1
    e.options = options
    e.data = data or {}
    return e


def _seeded_charger(hass, idx=0):
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    return kwargs["options"]["ev_chargers"][idx], kwargs


@pytest.mark.asyncio
async def test_seeds_all_eight_from_global():
    hass = MagicMock()
    entry = _entry(
        options={"ev_chargers": [{"id": "ev_charger", "name": "EV"}]},
        data={
            "daily_ev_target": 8, "daily_ev_target_max": 50,
            "ev_target_soc": 70, "ev_target_soc_max": 90,
            "ev_min_current": 6, "ev_night_initial_current": 10,
            "ev_kwh_per_100km": 18, "ev_target_type": "soc",
        },
    )
    assert await async_migrate_entry(hass, entry) is True
    c, kwargs = _seeded_charger(hass)
    assert kwargs["version"] == 6  # bumped in v5→v6 (#277 Phase B)  # bumped in v4→v5 (#277)
    assert c["daily_ev_target"] == 8
    assert c["daily_ev_target_max"] == 50
    assert c["ev_target_soc"] == 70
    assert c["ev_target_soc_max"] == 90
    assert c["ev_min_current"] == 6
    assert c["ev_night_initial_current"] == 10
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
        options={"ev_chargers": [{"id": "c1"}]},
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
    assert hass.config_entries.async_update_entry.call_args.kwargs["version"] == 6  # bumped in v5→v6 (#277 Phase B)  # bumped in v4→v5 (#277)


@pytest.mark.asyncio
async def test_unset_global_not_seeded():
    hass = MagicMock()
    entry = _entry(options={"ev_chargers": [{"id": "c1"}]}, data={})
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    # nothing to seed from → charger keeps only its identity keys
    assert "daily_ev_target" not in c


@pytest.mark.asyncio
async def test_phase4_charging_mode_and_phases_seeded():
    """#255 Phase 4: ev_charging_mode + ev_phases are also seeded per-charger."""
    hass = MagicMock()
    entry = _entry(
        options={"ev_chargers": [{"id": "c1"}]},
        data={"ev_charging_mode": "minpv", "ev_phases": 1},
    )
    await async_migrate_entry(hass, entry)
    c, _ = _seeded_charger(hass)
    assert c["ev_charging_mode"] == "minpv"
    assert c["ev_phases"] == 1


def test_phase4_globals_removed_from_descriptions():
    """The converted globals are no longer global entities (#255 Phase 4)."""
    from custom_components.solar_energy_management.number import NUMBER_TYPES
    from custom_components.solar_energy_management.select import SELECT_TYPES
    assert "ev_phases" not in {n.key for n in NUMBER_TYPES}
    assert "ev_charging_mode" not in {s.key for s in SELECT_TYPES}
    # ev_stall_cooldown stays global (tuning constant)
    assert "ev_stall_cooldown" in {n.key for n in NUMBER_TYPES}
