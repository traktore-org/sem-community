"""Canary smoke test for the ``pytest-homeassistant-custom-component`` bootstrap.

Phase 1 of the testing-framework adoption (see
``/home/sem/.claude/plans/are-we-taking-about-distributed-token.md``).

What this test proves
---------------------
1. ``pytest-homeassistant-custom-component`` is installed and importable.
2. The ``hass`` fixture spins up a real ``HomeAssistant`` instance
   (state machine, registries, service dispatch — not a MagicMock).
3. The ``sem_config_entry`` fixture constructs a ``MockConfigEntry`` at
   SEM's current schema version (v7).
4. The entry can be registered with ``hass`` and the SEM config
   entry lifecycle (``async_setup_entry`` → ``async_unload_entry``)
   runs without crashing under the new framework.

What this test does NOT cover
-----------------------------
Behavioural correctness of setup itself — that's covered by Phase 3's
``test_config_flow_migration.py``, ``test_options_flow_multicharger.py``,
and ``test_services_real.py``. The canary's job is to prove the
framework is wired and the existing dict-mocked suite still passes
alongside it.

If this test fails, do NOT skip it: the failure is the first signal
that something about the framework adoption is wrong (wrong pin,
incompatible HA version, missing optional dep, etc.).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.const import DOMAIN


# ---------------------------------------------------------------------------
# Framework wiring
# ---------------------------------------------------------------------------


def test_pytest_homeassistant_custom_component_installed() -> None:
    """The framework package must be importable."""
    import pytest_homeassistant_custom_component  # noqa: F401
    from pytest_homeassistant_custom_component.common import (  # noqa: F401
        MockConfigEntry,
        async_test_home_assistant,
    )


# ---------------------------------------------------------------------------
# Fixtures self-check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hass_fixture_yields_real_homeassistant(hass) -> None:
    """The ``hass`` fixture must yield a true HomeAssistant instance.

    Pytest-HA's plugin ``hass`` (the one we want) supersedes the legacy
    MagicMock fixture that was renamed to ``mock_hass``. We assert we
    received an actual ``HomeAssistant`` instance with a working state
    machine — surfaces the MagicMock fixture doesn't simulate.
    """
    from homeassistant.core import HomeAssistant

    assert isinstance(hass, HomeAssistant)

    # Real state machine — async_set works and is observable.
    hass.states.async_set("sensor.canary", "42")
    state = hass.states.get("sensor.canary")
    assert state is not None
    assert state.state == "42"


def test_sem_config_entry_uses_current_schema_version(sem_config_entry) -> None:
    """The pre-seeded entry must match the integration's current schema.

    If SEM bumps its config-entry version, this test fails and the
    fixture must be updated to keep parity. That's the signal we want.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    assert isinstance(sem_config_entry, MockConfigEntry)
    assert sem_config_entry.domain == DOMAIN
    assert sem_config_entry.version == 12
    assert sem_config_entry.minor_version == 1
    # Multi-charger schema — wrapped list, not legacy flat keys.
    assert "ev_chargers" in sem_config_entry.data
    assert isinstance(sem_config_entry.data["ev_chargers"], list)


# ---------------------------------------------------------------------------
# Lifecycle smoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_entry_can_register_with_hass(
    hass, sem_config_entry
) -> None:
    """``MockConfigEntry.add_to_hass`` must work against the real instance.

    This is the precondition for any Phase 2/3 test that drives the
    coordinator. If this fails, the rest of the framework migration
    can't proceed.
    """
    sem_config_entry.add_to_hass(hass)

    # The entry registry should now know about us.
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].entry_id == sem_config_entry.entry_id
    assert entries[0].version == 12
