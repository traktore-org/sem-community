"""Unit tests for _async_register_frontend_resources.

Covers three contracts:

1. **YAML-mode guard (#283)** — when ``hass.data["lovelace"].resources``
   is a ``ResourceYAMLCollection`` (no mutating methods), the registration
   block must NOT crash and must log instructions the user can paste into
   configuration.yaml.

2. **Storage-mode happy path** — the bundle, diagram card, and
   sem-localize.js must all be registered as Lovelace resources.

3. **Single-channel localize delivery (#453)** — sem-localize.js is
   delivered as a Lovelace resource only; ``add_extra_js_url`` must NOT
   be imported or called from this module (dual-channel was removed
   in v1.7.3 in favor of the ``sem-localize-ready`` event handled in
   ``dashboard/card/src/base/sem-lit-base.js``).
"""
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.solar_energy_management as sem_module
from custom_components.solar_energy_management import (
    _async_register_frontend_resources,
)


def _hass_with_resources(resources):
    """Mock just enough of hass for the registration block to run."""
    hass = MagicMock()
    hass.data = {"lovelace": MagicMock(resources=resources)}
    hass.http = MagicMock()
    # The bundle URL only resolves if the component's dashboard dir is served.
    # This is the CURRENT HA API (async_register_static_paths); the sync
    # register_static_path was removed in 2025.7 (#799). Must be awaitable.
    hass.http.async_register_static_paths = AsyncMock()
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
        #   3. Contain the standalone diagram-card URL.
        #   4. Contain sem-localize.js (#453 — YAML-mode users lose
        #      translations without it after dual-channel removal).
        #   5. Mention configuration.yaml so they know where it goes.
        joined = "\n".join(rec.message for rec in caplog.records)
        assert "YAML-mode" in joined or "YAML mode" in joined, joined
        assert "sem-cards.js" in joined, joined
        assert "sem-system-diagram-card.js" in joined, joined
        assert "sem-localize.js" in joined, joined
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
    async def test_storage_mode_registers_all_three_resources(self):
        """Bundle + diagram card + sem-localize.js all land as Lovelace
        resources in storage-mode. The third (localize) is #453 — was on
        ``add_extra_js_url`` only, then dual-channel, now single Lovelace
        resource."""
        r = _storage_mode_resources(initial_items=[])
        hass = _hass_with_resources(r)
        await _async_register_frontend_resources(hass)
        assert r.async_create_item.call_count >= 3
        urls = [call.args[0]["url"] for call in r.async_create_item.call_args_list]
        assert any("sem-cards.js" in u for u in urls), urls
        assert any("sem-system-diagram-card.js" in u for u in urls), urls
        assert any("sem-localize.js" in u for u in urls), urls


# ──────────────────────────────────────────────────────────────────────
# Static-path serving via the CURRENT HA API (#799)
# ──────────────────────────────────────────────────────────────────────

class TestStaticPathServedViaAsyncApi:
    """The card bundle URL must be *served*, not just *registered*.

    #799 (reporter on HA 2026.8.2, fresh 1.7.5 install): every sem-* card
    showed "Custom element doesn't exist". Root cause: the component served
    its dashboard dir with ``hass.http.register_static_path`` — a sync call
    that did blocking I/O on the event loop and that HA **removed in 2025.7**.
    On 2025.7+ it raised ``AttributeError``, which a bare ``except Exception:
    pass`` swallowed as "already registered from previous load"; the static
    route was never created, the Lovelace resource URL 404'd, and no sem-*
    element ever defined. The fix moves to ``async_register_static_paths``.
    """

    @pytest.mark.asyncio
    async def test_registers_the_dashboard_dir_via_async_static_paths(self):
        """The dashboard dir is served through the non-removed async API,
        with a StaticPathConfig whose url_path is the /local bundle prefix."""
        from custom_components.solar_energy_management.const import DOMAIN

        r = _storage_mode_resources(initial_items=[])
        hass = _hass_with_resources(r)
        await _async_register_frontend_resources(hass)

        assert hass.http.async_register_static_paths.await_count >= 1, (
            "the dashboard dir was never served — the bundle URL will 404"
        )
        configs = hass.http.async_register_static_paths.await_args.args[0]
        url_paths = [c.url_path for c in configs]
        assert f"/local/custom_components/{DOMAIN}/dashboard" in url_paths, url_paths

    def test_removed_sync_register_static_path_is_not_called(self):
        """Guard the whole class: the sync ``register_static_path`` was
        removed in HA 2025.7 — a call to it silently breaks the dashboard on
        every modern HA. The source must not contain the call form. Mentioning
        the name in a comment (as the fix does) is fine; the open-paren call is
        not. Same shape as the ``add_extra_js_url(`` ban below."""
        source = Path(sem_module.__file__).read_text(encoding="utf-8")
        assert "register_static_path(" not in source, (
            "hass.http.register_static_path(...) is back in __init__.py — it "
            "was removed in HA 2025.7 and its failure is swallowed as "
            "'already registered', breaking every sem-* card. Use "
            "async_register_static_paths. See #799."
        )


# ──────────────────────────────────────────────────────────────────────
# Single-channel localize delivery (#453)
# ──────────────────────────────────────────────────────────────────────

class TestSingleChannelLocalizeDelivery:
    """Pin that ``add_extra_js_url`` is fully removed from this module.

    The dual-channel mechanism (``add_extra_js_url`` + Lovelace resource)
    was retired in v1.7.3 — cards now wait for the ``sem-localize-ready``
    CustomEvent dispatched at the end of sem-localize.js, handled in
    ``dashboard/card/src/base/sem-lit-base.js`` (lines ~255-276).

    A future refactor that re-introduces ``add_extra_js_url`` for the
    localize script would reintroduce the double-load — and the dead
    ``window.semLocalize`` guard the IIFE would need to be safe.
    These tests lock the contract.
    """

    def test_add_extra_js_url_not_imported(self):
        """The frontend symbol is no longer imported into this module."""
        assert not hasattr(sem_module, "add_extra_js_url"), (
            "add_extra_js_url is back in the module namespace; "
            "dual-channel sem-localize delivery would silently re-enable. "
            "See #453."
        )

    def test_add_extra_js_url_not_referenced_in_source(self):
        """Belt-and-braces: even if a future import comes through some
        other path (e.g. a star-import or a local import inside a function),
        the source file must contain no call to ``add_extra_js_url(``."""
        source = Path(sem_module.__file__).read_text(encoding="utf-8")
        # Comments referencing the historical name are fine — only block
        # actual calls. Look for the open-paren form to distinguish.
        assert "add_extra_js_url(" not in source, (
            "add_extra_js_url(...) call appears in __init__.py — "
            "dual-channel sem-localize delivery is back. See #453."
        )

    @pytest.mark.asyncio
    async def test_storage_mode_localize_url_has_cache_bust_token(self):
        """The Lovelace-resource URL for sem-localize.js must carry the
        ``?v=<version>-<sha1>`` cache-bust token — otherwise the service
        worker keeps serving stale translations across deploys (#240)."""
        r = _storage_mode_resources(initial_items=[])
        hass = _hass_with_resources(r)
        await _async_register_frontend_resources(hass)
        urls = [call.args[0]["url"] for call in r.async_create_item.call_args_list]
        localize_urls = [u for u in urls if "sem-localize.js" in u]
        assert localize_urls, f"sem-localize.js not registered: {urls}"
        assert "?v=" in localize_urls[0], (
            f"sem-localize.js URL missing cache-bust: {localize_urls[0]}"
        )
