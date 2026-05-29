"""Unit tests for _async_register_frontend_resources (#283).

The reporter ran YAML-mode Lovelace, where ``hass.data["lovelace"].resources``
is a ``ResourceYAMLCollection`` that doesn't implement the mutating methods
(``async_create_item`` / ``async_update_item`` / ``async_delete_item``).
The integration was crashing the registration block with a generic warning,
leaving the user with a blank dashboard and no idea what to add to
configuration.yaml.

These tests pin down the YAML-mode guard:
  - It must NOT crash when ``async_create_item`` is missing.
  - It must log a warning that contains the bundle URL the user needs to add.
  - The storage-mode happy path must still register the resources (sanity).
"""
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management import (
    _async_register_frontend_resources,
)


@pytest.fixture(autouse=True)
def _stub_add_extra_js_url():
    """``add_extra_js_url`` reaches into ``hass.data["frontend_extra_module_url"]``
    which our minimal hass mock doesn't carry. The localize-script
    registration is incidental to the YAML-mode-guard test — stub it
    so the function under test doesn't bail at the outer try."""
    with patch(
        "custom_components.solar_energy_management.add_extra_js_url",
        MagicMock(),
    ):
        yield


def _hass_with_resources(resources):
    """Mock just enough of hass for the registration block to run."""
    hass = MagicMock()
    hass.data = {"lovelace": MagicMock(resources=resources)}
    hass.http = MagicMock()
    hass.http.register_static_path = MagicMock()
    # async_add_executor_job runs the callable directly in tests.
    async def _exec(fn, *args):
        return fn(*args)
    hass.async_add_executor_job = AsyncMock(side_effect=_exec)
    return hass


def _yaml_mode_resources():
    """A ResourceYAMLCollection-like stub — no mutating methods."""
    r = MagicMock(spec=["loaded", "async_load", "async_items"])
    r.loaded = True
    # async_load isn't actually called when loaded=True, but it's defined.
    r.async_load = AsyncMock()
    r.async_items = MagicMock(return_value=[])
    # Critical: NO async_create_item / async_update_item / async_delete_item.
    # ``spec=`` above already restricts the attrs — getattr would raise
    # AttributeError. hasattr(r, "async_create_item") returns False.
    return r


def _storage_mode_resources(initial_items=None):
    """A ResourceStorageCollection-like stub — full CRUD."""
    items = list(initial_items or [])
    r = MagicMock()
    r.loaded = True
    r.async_load = AsyncMock()
    r.async_items = MagicMock(return_value=items)
    r.async_create_item = AsyncMock()
    r.async_update_item = AsyncMock()
    r.async_delete_item = AsyncMock()
    return r


# ──────────────────────────────────────────────────────────────────────
# YAML mode — the #283 reporter's regime
# ──────────────────────────────────────────────────────────────────────

class TestYAMLMode:
    @pytest.mark.asyncio
    async def test_does_not_crash_when_create_item_missing(self, caplog):
        """The whole point of #283: don't blow up the registration block."""
        hass = _hass_with_resources(_yaml_mode_resources())
        # Pre-flight: confirm the stub really lacks the method (so the test
        # is asserting against a faithful YAML-mode shape, not a typo).
        assert not hasattr(hass.data["lovelace"].resources, "async_create_item")

        with caplog.at_level(logging.WARNING):
            # Must complete without raising — and without logging a
            # "Could not register" generic warning, because the YAML-mode
            # guard catches the sentinel BEFORE the generic except handler.
            await _async_register_frontend_resources(hass)

    @pytest.mark.asyncio
    async def test_logs_instructions_with_bundle_url(self, caplog):
        """User-facing fix: the log must tell them what to add to YAML."""
        hass = _hass_with_resources(_yaml_mode_resources())

        with caplog.at_level(logging.WARNING):
            await _async_register_frontend_resources(hass)

        # The warning message must:
        #   1. Mention YAML-mode so the user knows what's happening.
        #   2. Contain a `url: ...sem-cards.js...` line so they can paste.
        #   3. Mention configuration.yaml so they know where it goes.
        joined = "\n".join(rec.message for rec in caplog.records)
        assert "YAML-mode" in joined or "YAML mode" in joined, joined
        assert "sem-cards.js" in joined, joined
        assert "configuration.yaml" in joined, joined

    @pytest.mark.asyncio
    async def test_does_not_call_mutating_methods(self):
        """Belt-and-braces: even with the catch in place, none of the
        async_create_item / update / delete calls fired. If a future
        refactor accidentally moves work above the guard, this catches it."""
        r = _yaml_mode_resources()
        hass = _hass_with_resources(r)
        await _async_register_frontend_resources(hass)
        # The spec=[...] restriction on the mock means a call to a missing
        # method would have raised AttributeError, but the test would also
        # have failed via the call_count assertion below if the impl
        # somehow worked around it.
        assert not hasattr(r, "async_create_item")


# ──────────────────────────────────────────────────────────────────────
# Storage mode — happy path sanity check
# ──────────────────────────────────────────────────────────────────────

class TestStorageMode:
    @pytest.mark.asyncio
    async def test_storage_mode_still_registers_bundle(self):
        """The YAML guard mustn't accidentally divert storage-mode users."""
        r = _storage_mode_resources(initial_items=[])
        hass = _hass_with_resources(r)
        await _async_register_frontend_resources(hass)
        # Bundle and diagram resources should both have been registered.
        # Two creates: cards bundle + diagram card.
        assert r.async_create_item.call_count >= 2
        urls = [call.args[0]["url"] for call in r.async_create_item.call_args_list]
        assert any("sem-cards.js" in u for u in urls), urls
        assert any("sem-system-diagram-card.js" in u for u in urls), urls
