"""#996 — the platforms follow the capability verdict the way they follow
the hardware modules (#923): a control a house cannot use is not built,
its leftover registry row is swept, and it comes back when the house
changes. UNKNOWN builds everything.

Real registry (the ``hass`` fixture), test-double coordinator."""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.solar_energy_management import number, switch  # noqa: E402
from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    Module, Presence, all_unknown,
)

PLAIN = {**all_unknown(),
         Module.DYNAMIC_TARIFF: Presence.ABSENT, Module.EXPORT_LIMIT: Presence.ABSENT,
         Module.SOLAR_FORECAST: Presence.ABSENT}
DYNAMIC = {**all_unknown(), Module.DYNAMIC_TARIFF: Presence.PRESENT}


def _entry(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, title="SEM #996")
    entry.add_to_hass(hass)
    return entry


def _coordinator(hass, entry, presence):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass.config.currency = "EUR"
    coordinator.setup_presence = presence
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def _run(platform_module, hass, entry):
    added: list = []
    await platform_module.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    # (#1428) the platform reports what it built; setup's ONE sweep removes the rest
    from custom_components.solar_energy_management.entity_sweep import sweep_stale_entities
    sweep_stale_entities(hass, entry)
    return {e.entity_description.key for e in added}


def _seed(hass, entry, platform, unique_id):
    er.async_get(hass).async_get_or_create(platform, DOMAIN, unique_id, config_entry=entry)


def _exists(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id) is not None


@pytest.mark.asyncio
async def test_a_flat_tariff_gets_no_price_knobs_and_the_leftovers_go(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, PLAIN)
    _seed(hass, entry, "number", f"{entry.entry_id}_cheap_price_threshold")
    keys = await _run(number, hass, entry)
    assert not {"cheap_price_threshold", "expensive_price_threshold",
                "export_guard_engage_s", "export_guard_release_s"} & keys
    assert {"electricity_import_rate", "update_interval"} <= keys
    assert not _exists(hass, "number", f"{entry.entry_id}_cheap_price_threshold")


@pytest.mark.asyncio
async def test_the_house_turns_dynamic_and_the_knobs_come_back(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, DYNAMIC)
    _seed(hass, entry, "number", f"{entry.entry_id}_cheap_price_threshold")
    keys = await _run(number, hass, entry)
    assert {"cheap_price_threshold", "expensive_price_threshold"} <= keys
    # The sweep keeps a row whose entity is built again.
    assert _exists(hass, "number", f"{entry.entry_id}_cheap_price_threshold")


@pytest.mark.asyncio
async def test_no_export_limit_no_export_guard_switches(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, PLAIN)
    _seed(hass, entry, "switch", "sem_export_guard_enabled")
    keys = await _run(switch, hass, entry)
    assert not {"export_guard_enabled", "export_guard_override_external",
                "forecast_spending_enabled", "battery_charge_pacing_enabled"} & keys
    assert "observer_mode" in keys
    assert not _exists(hass, "switch", "sem_export_guard_enabled")


@pytest.mark.asyncio
async def test_unknown_builds_everything(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, all_unknown())
    keys = await _run(switch, hass, entry)
    assert {"export_guard_enabled", "forecast_spending_enabled"} <= keys
    keys = await _run(number, hass, entry)
    assert {"cheap_price_threshold", "export_guard_engage_s"} <= keys
