"""#901 — the per-language localize files are an ASSET, not a Lovelace resource.

Since #738 ``sem-localize.js`` is a loader that lazily injects
``sem-localize.<lang>.js`` for the user's own language. The siblings must be
COPIED to ``/config/www`` (the loader fetches them over ``/local``) but must
never be registered as Lovelace resources.

Upgraded installs still carry 15 of them, registered by the pre-#738
``generate_dashboard`` path and never touched again — HA-PROD, 02.09.2026,
running 2.1.0-beta.5:

    2.1.0-beta.5  x2   dist/sem-cards.js, sem-localize.js
    1.7.6-beta.13 x15  sem-localize.{de,fr,es,...}.js

Two consequences, both real:

* the same language table is written twice from two different URLs — the stale
  resource and the loader's fresh injection — and last write wins, so a cached
  1.7.6 copy can beat the current one (the #240 class, closed for the bundle
  and left open for the siblings);
* every registered resource is fetched at frontend boot, so ~1.3 MB of
  language tables loads on every page for a user who needs at most one.

What these tests pin: one predicate answers "may this file be a Lovelace
resource", BOTH registration paths use it, and the restart path sweeps
whatever an older version registered.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.solar_energy_management as sem_module
from custom_components.solar_energy_management import (
    _async_register_frontend_resources,
    _is_localize_sibling,
    _registrable_card_files,
)

_STATIC = "/local/custom_components/solar_energy_management/dashboard"


def _hass_with_resources(resources):
    hass = MagicMock()
    hass.data = {"lovelace": MagicMock(resources=resources)}
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()

    async def _exec(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_exec)
    return hass


def _storage_mode_resources(initial_items=None):
    items = list(initial_items or [])
    r = MagicMock()
    r.loaded = True
    r.async_load = AsyncMock()
    r.async_items = MagicMock(return_value=items)
    r.async_create_item = AsyncMock()
    r.async_update_item = AsyncMock()
    r.async_delete_item = AsyncMock()
    return r


def _item(uid, url):
    return {"id": uid, "url": url, "type": "module"}


class TestPredicate:
    @pytest.mark.parametrize("name", [
        "sem-localize.de.js",
        "sem-localize.zh.js",
        "sem-localize.pt.js",
        f"{_STATIC}/card/sem-localize.fr.js",
        f"{_STATIC}/card/sem-localize.no.js?v=1.7.6-beta.13-d12eae1f",
    ])
    def test_siblings_are_recognised(self, name):
        assert _is_localize_sibling(name) is True

    @pytest.mark.parametrize("name", [
        "sem-localize.js",
        f"{_STATIC}/card/sem-localize.js",
        f"{_STATIC}/card/sem-localize.js?v=2.1.0-beta.5-1d547e3e",
        "dist/sem-cards.js",
        f"{_STATIC}/card/dist/sem-cards.js",
        "sem-config-card.js",
    ])
    def test_the_loader_and_the_bundle_are_not_siblings(self, name):
        """The loader IS a resource — deleting it costs every card its
        translations (#453). The predicate must not overreach."""
        assert _is_localize_sibling(name) is False

    def test_registrable_keeps_the_loader_and_drops_every_sibling(self):
        installed = [
            "sem-localize.js",
            "sem-localize.de.js",
            "sem-localize.fr.js",
            "sem-localize.zh.js",
        ]
        assert _registrable_card_files(installed) == ["sem-localize.js"]


class TestRestartPathSweep:
    @pytest.mark.asyncio
    async def test_stale_siblings_are_deregistered(self):
        """The upgrade case: entries an older version registered are gone
        after one restart, without the user calling any service."""
        stale = [
            _item("a1", f"{_STATIC}/card/sem-localize.de.js?v=1.7.6-beta.13-e898c7e8"),
            _item("a2", f"{_STATIC}/card/sem-localize.fr.js?v=1.7.6-beta.13-88f31a02"),
        ]
        keep = [
            _item("b1", f"{_STATIC}/card/dist/sem-cards.js?v=2.1.0-beta.5-8b7a0ed9"),
            _item("b2", f"{_STATIC}/card/sem-localize.js?v=2.1.0-beta.5-1d547e3e"),
        ]
        res = _storage_mode_resources(stale + keep)
        hass = _hass_with_resources(res)

        await _async_register_frontend_resources(hass)

        deleted = {c.args[0] for c in res.async_delete_item.call_args_list}
        assert {"a1", "a2"} <= deleted, (
            f"per-language resources survived the restart path: {deleted}"
        )
        assert "b1" not in deleted and "b2" not in deleted, (
            "the bundle or the localize LOADER was deleted — that is the "
            "#453 delivery channel, not a sibling"
        )

    @pytest.mark.asyncio
    async def test_clean_install_deletes_nothing(self):
        """A fresh install has no siblings registered; the sweep must be a
        no-op there rather than churning the store on every restart."""
        keep = [
            _item("b1", f"{_STATIC}/card/dist/sem-cards.js?v=2.1.0-beta.5-8b7a0ed9"),
            _item("b2", f"{_STATIC}/card/sem-localize.js?v=2.1.0-beta.5-1d547e3e"),
        ]
        res = _storage_mode_resources(keep)
        hass = _hass_with_resources(res)

        await _async_register_frontend_resources(hass)

        assert res.async_delete_item.call_count == 0


class TestServicePathUsesTheSamePredicate:
    def test_generate_dashboard_filters_through_the_helper(self):
        """Both paths, one rule. If the service path stops filtering, it
        re-registers on the next call everything the restart path just
        swept — the two-writer loop #901 is about."""
        import inspect

        src = inspect.getsource(sem_module)
        assert "_registrable_card_files(installed_cards)" in src, (
            "the generate_dashboard resource path no longer filters its "
            "registration set through _registrable_card_files"
        )
