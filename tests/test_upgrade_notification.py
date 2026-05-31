"""Tests for the v1.6.14 upgrade-notification helper.

Background. After a SEM HACS update + HA restart, ``add_extra_js_url``
serves a new content-hashed ``sem-localize.js`` URL — but the user's
browser still has the OLD frontend bootstrap cached, which references
the OLD URL. Soft reload (F5) hits the cached bootstrap → loads stale
``sem-localize.js`` → cards render raw translation keys.
HA-TEST 2026-05-31 repro: ``TODAY_PLAN_TITLE``, ``plan_strip_idle``
etc. visible until Ctrl+Shift+R.

The helper at ``__init__._maybe_emit_upgrade_notification`` solves
this by detecting a version change at setup and firing a one-shot
``persistent_notification`` with hard-refresh instructions. These
tests pin the contract:

1. First install (stored=None) → record current, no notification.
2. Same version → no notification, no Store write.
3. Upgrade (different version) → notification fired AND Store updated.
4. Notification ID is per-version (so an upgrade replaces the
   previous version's notification rather than stacking).
5. Failure of any sub-step is swallowed by the caller.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management import (
    _maybe_emit_upgrade_notification,
)


def _make_entry(entry_id="abc123"):
    e = MagicMock()
    e.entry_id = entry_id
    return e


def _patches(stored_version, current_version):
    """Build a (Store-mock, async_get_integration-mock) pair.

    Returns three things the caller patches in: ``store_mock``
    (the constructed Store instance), ``store_class`` (the factory —
    asserted with), and ``integration_class``.
    """
    store_instance = MagicMock()
    store_instance.async_load = AsyncMock(
        return_value=({"version": stored_version} if stored_version else None)
    )
    store_instance.async_save = AsyncMock()
    store_class = MagicMock(return_value=store_instance)

    integration = MagicMock()
    integration.version = current_version
    integration_getter = AsyncMock(return_value=integration)

    return store_instance, store_class, integration_getter


@pytest.mark.asyncio
async def test_first_install_silent_record():
    """No stored version → record current, no notification fired."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = _make_entry()

    store, store_cls, integration_get = _patches(None, "1.6.14")
    with patch(
        "custom_components.solar_energy_management.Store"
        if False else "homeassistant.helpers.storage.Store",
        store_cls,
    ), patch(
        "homeassistant.loader.async_get_integration", integration_get,
    ):
        await _maybe_emit_upgrade_notification(hass, entry)

    # Stored.
    store.async_save.assert_called_once_with({"version": "1.6.14"})
    # NOT notified.
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_same_version_no_op():
    """Stored == current → neither save nor notify."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = _make_entry()

    store, store_cls, integration_get = _patches("1.6.14", "1.6.14")
    with patch(
        "homeassistant.helpers.storage.Store", store_cls,
    ), patch(
        "homeassistant.loader.async_get_integration", integration_get,
    ):
        await _maybe_emit_upgrade_notification(hass, entry)

    store.async_save.assert_not_called()
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_upgrade_emits_notification():
    """Upgrade: stored=1.6.12, current=1.6.14 → save + notify."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = _make_entry()

    store, store_cls, integration_get = _patches("1.6.12", "1.6.14")
    with patch(
        "homeassistant.helpers.storage.Store", store_cls,
    ), patch(
        "homeassistant.loader.async_get_integration", integration_get,
    ):
        await _maybe_emit_upgrade_notification(hass, entry)

    # Updated.
    store.async_save.assert_called_once_with({"version": "1.6.14"})
    # Notified.
    hass.services.async_call.assert_called_once()
    call = hass.services.async_call.call_args
    assert call.args[0] == "persistent_notification"
    assert call.args[1] == "create"
    body = call.args[2]
    assert "v1.6.14" in body["title"]
    assert "Ctrl+Shift+R" in body["message"]
    assert "hard-refresh" in body["message"].lower()
    assert "today_plan_title" in body["message"]  # specific bug reference
    # Per-version notification ID so a new upgrade replaces the prior banner.
    assert body["notification_id"] == "sem_upgrade_1_6_14"


@pytest.mark.asyncio
async def test_notification_id_per_version():
    """Different upgrades produce different notification_ids — so the
    HA notifications drawer doesn't suppress the new banner as a
    duplicate of an older one."""
    ids: list[str] = []
    for prev, cur in [("1.6.12", "1.6.13"), ("1.6.13", "1.6.14")]:
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        entry = _make_entry()
        store, store_cls, integration_get = _patches(prev, cur)
        with patch(
            "homeassistant.helpers.storage.Store", store_cls,
        ), patch(
            "homeassistant.loader.async_get_integration", integration_get,
        ):
            await _maybe_emit_upgrade_notification(hass, entry)
        ids.append(hass.services.async_call.call_args.args[2]["notification_id"])
    assert ids == ["sem_upgrade_1_6_13", "sem_upgrade_1_6_14"]
    assert len(set(ids)) == 2


@pytest.mark.asyncio
async def test_per_entry_store_key():
    """Two SEM entries (rare but possible) → independent ``Store``
    instances keyed by ``entry_id``."""
    keys: list[str] = []
    for eid in ("entry_alpha", "entry_beta"):
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        entry = _make_entry(eid)
        _, store_cls, integration_get = _patches(None, "1.6.14")
        with patch(
            "homeassistant.helpers.storage.Store", store_cls,
        ), patch(
            "homeassistant.loader.async_get_integration", integration_get,
        ):
            await _maybe_emit_upgrade_notification(hass, entry)
        # 3rd positional arg is the store key
        keys.append(store_cls.call_args.args[2])
    assert keys == [
        "sem_seen_version_entry_alpha",
        "sem_seen_version_entry_beta",
    ]
