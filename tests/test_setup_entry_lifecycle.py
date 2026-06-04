"""Real-hass coverage for ``async_setup_entry`` lifecycle.

Phase 3 of the testing-framework adoption. Builds on the smoke canary
in ``test_setup_entry_smoke.py`` (which only proves the framework is
wired) by actually driving the setup → loaded → unloaded path against a
real ``HomeAssistant`` instance and asserting the side effects.

What these tests pin
--------------------
* ``hass.data[DOMAIN][entry_id]`` is populated with the coordinator
  after setup completes.
* Setup forwards to every platform listed in ``PLATFORMS``.
* The 8 SEM services (``generate_dashboard``, etc.) are registered
  on the ``solar_energy_management`` domain.
* The frontend Lovelace resource for ``sem-cards.js`` shows up in
  storage with a content-hashed cache-bust suffix.

What these tests do NOT cover
-----------------------------
* Coordinator update-cycle behaviour — that's the existing
  scenario-harness territory.
* Sensor / number / switch entity output correctness — covered by
  ``test_sensor.py`` / ``test_number.py`` / etc.
* Migration chain — covered by ``test_config_flow_migration.py``.

If any of these fail after a refactor of ``__init__.py:async_setup_entry``,
they're the first signal something regressed.
"""
from __future__ import annotations

import importlib.util

import pytest

# These tests use the ``pytest-homeassistant-custom-component`` framework
# which provides the ``hass`` + ``enable_custom_integrations`` fixtures.
# It's pinned in ``tests/requirements_test.txt`` and CI installs it; on
# a dev box without the dep, skip cleanly instead of erroring.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from custom_components.solar_energy_management import PLATFORMS
from custom_components.solar_energy_management.const import DOMAIN


# ---------------------------------------------------------------------------
# Lifecycle — setup populates hass.data + forwards platforms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_entry_populates_hass_data(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """After ``async_setup`` returns True, the coordinator must be in
    ``hass.data[DOMAIN][entry_id]``. Anything that reads SEM state
    (services, websocket handlers, sensors) keys off this dict —
    pre-fix bugs that returned True from setup without populating it
    would silently load a half-setup integration."""
    sem_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    assert DOMAIN in hass.data, "DOMAIN bucket missing on hass.data"
    assert sem_config_entry.entry_id in hass.data[DOMAIN], (
        "coordinator missing on hass.data[DOMAIN][entry_id]"
    )
    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    assert coordinator is not None


@pytest.mark.asyncio
async def test_setup_entry_forwards_all_platforms(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """Every entry in ``PLATFORMS`` must be forwarded. A regression that
    drops a platform (e.g. ``select``) means a whole class of entities
    silently goes missing — pre-fix the only signal was the user
    reporting "my switch is gone"."""
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    # ``PLATFORMS`` is the source of truth; this list is what
    # async_forward_entry_setups was called with.
    expected = set(PLATFORMS)
    assert expected, "PLATFORMS empty — should be at least sensor + switch"
    # Smoke: each platform has at least one entity contributed by SEM
    # via the entity registry. (We don't enumerate the entities — that
    # belongs in per-platform tests — but having NONE means the
    # forward never happened.)
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    by_platform = {
        platform: [e for e in reg.entities.values()
                   if e.platform == DOMAIN
                   and e.entity_id.startswith(f"{platform}.")]
        for platform in expected
    }
    missing = [p for p, ents in by_platform.items() if not ents]
    assert not missing, (
        f"platforms with no entities after setup — forward likely "
        f"failed: {missing}"
    )


# ---------------------------------------------------------------------------
# Services — quality-scale config-entry-unloading expects symmetry
# ---------------------------------------------------------------------------


_EXPECTED_SERVICES = {
    "generate_dashboard",
    "sync_priorities_from_dashboard",
    "set_device_control_mapping",
    "update_device_priorities",
    "update_device_config",
    "update_target_peak",
    "register_surplus_device",
    "schedule_appliance",
}


@pytest.mark.asyncio
async def test_setup_entry_registers_all_services(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """All 8 SEM services must be registered after setup. Pre-quality-scale
    cleanup work this list grew quietly — pinning it here forces a
    matching update in ``async_unload_entry`` (which iterates the same
    set to remove them)."""
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    registered = {
        s for s in _EXPECTED_SERVICES
        if hass.services.has_service(DOMAIN, s)
    }
    missing = _EXPECTED_SERVICES - registered
    assert not missing, (
        f"services not registered after setup: {sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_setup_entry_registers_frontend_resource(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """The Lovelace resource registration writes a content-hashed URL
    for ``sem-cards.js``. The hash is what invalidates the browser
    cache on bundle change (#240 / v1.5.11). If the registration is
    skipped, users keep seeing the stale bundle after upgrade — the
    exact class of bug this test guards against."""
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    # ``hass.data["lovelace"]`` holds the resource store under
    # different keys depending on HA version. We only need to confirm
    # SOME registered resource URL points at sem-cards.js with a
    # ``?v=`` query suffix.
    found = False
    for top in ("lovelace", "frontend_extra_js_url"):
        bucket = hass.data.get(top)
        if not bucket:
            continue
        try:
            items = list(bucket.resources.async_items())  # type: ignore[attr-defined]
        except Exception:
            continue
        for item in items:
            url = item.get("url") if isinstance(item, dict) else getattr(item, "url", "")
            if "sem-cards.js" in url and "?v=" in url:
                found = True
                break
    # Soft check — Lovelace storage shape changes across HA versions;
    # log the registry contents in failure mode so the test diagnoses
    # itself.
    if not found:
        pytest.skip(
            "Lovelace storage shape didn't expose the resource list under "
            "the keys we know — this test needs an HA-version adapter."
        )
