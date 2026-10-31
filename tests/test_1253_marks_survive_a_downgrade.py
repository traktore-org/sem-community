"""#1253 — going back a version no longer clears hands-off load marks.

SEM 2.0.0 and older rewrite the device file with the keys they know. The
hands-off latch (``legacy_flags_adopted``) and the user's load modes
(``control_modes_user``) were lost, so the next start took the file for one
from before the latch: it cleared every hands-off mark and ignored the modes.
A copy of the two lives in a file of its own, which older versions never write.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

PUMP = "energy_dashboard_pump"
DRYER = "energy_dashboard_dryer"

# what a 2.0.0 build leaves: only the keys it knows
OLD_BUILD_FILE = {
    "controllable_overrides": {PUMP: False},
    "control_modes": {DRYER: "peak_only"},
}


def _reg(main, copy):
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg._store = MagicMock()
    reg._store.async_load = AsyncMock(return_value=main)
    reg._store.async_save = AsyncMock()
    reg._copy_store = MagicMock()
    reg._copy_store.async_load = AsyncMock(return_value=copy)
    reg._copy_store.async_save = AsyncMock()
    reg._load_manager = None
    for name in ("_manual_mappings", "_priority_overrides", "_control_mode_overrides",
                 "_dependency_overrides", "_critical_overrides",
                 "_controllable_overrides", "_rated_power_overrides",
                 "_service_registrations", "_device_goals"):
        setattr(reg, name, {})
    reg._ratings_to_recheck = set()
    reg._user_control_modes = set()
    reg._legacy_flags_adopted = False
    return reg


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_save_writes_the_copy():
    reg = _reg(None, None)
    reg._legacy_flags_adopted = True
    reg._user_control_modes = {DRYER}
    _run(reg._save_storage())
    reg._copy_store.async_save.assert_awaited_once_with(
        {"legacy_flags_adopted": True, "control_modes_user": [DRYER]})


def test_a_file_an_older_build_rewrote_is_restored_from_the_copy():
    reg = _reg(dict(OLD_BUILD_FILE),
               {"legacy_flags_adopted": True, "control_modes_user": [DRYER]})
    _run(reg._load_storage())
    assert reg._controllable_overrides == {PUMP: False}, "the hands-off mark stayed"
    assert reg._user_control_modes == {DRYER}
    assert reg._legacy_flags_adopted is True


def test_the_restored_keys_are_written_back_to_the_device_file():
    reg = _reg(dict(OLD_BUILD_FILE),
               {"legacy_flags_adopted": True, "control_modes_user": [DRYER]})
    _run(reg._load_storage())
    saved = reg._store.async_save.await_args.args[0]
    assert saved["legacy_flags_adopted"] is True
    assert saved["control_modes_user"] == [DRYER]


def test_a_mode_the_older_build_dropped_is_not_marked_as_the_users():
    reg = _reg({**OLD_BUILD_FILE, "control_modes": {}},
               {"legacy_flags_adopted": True, "control_modes_user": [DRYER]})
    _run(reg._load_storage())
    assert reg._user_control_modes == set()


def test_no_copy_is_the_old_migration():
    """A store from before the latch, with no copy: the marks are SEM's own
    arithmetic and go, as #888 decided."""
    reg = _reg(dict(OLD_BUILD_FILE), None)
    _run(reg._load_storage())
    assert reg._controllable_overrides == {}
    assert reg._legacy_flags_adopted is True


def test_a_file_that_has_the_latch_is_not_overwritten_by_the_copy():
    reg = _reg({**OLD_BUILD_FILE, "legacy_flags_adopted": False,
                "control_modes_user": []},
               {"legacy_flags_adopted": True, "control_modes_user": [DRYER]})
    _run(reg._load_storage())
    assert reg._legacy_flags_adopted is False
    assert reg._user_control_modes == set()


def test_a_failing_copy_does_not_fail_the_real_save():
    reg = _reg(None, None)
    reg._copy_store.async_save = AsyncMock(side_effect=OSError("disk"))
    _run(reg._save_storage())
    reg._store.async_save.assert_awaited_once()


def test_an_unreadable_copy_changes_nothing():
    reg = _reg(dict(OLD_BUILD_FILE), None)
    reg._copy_store.async_load = AsyncMock(side_effect=OSError("disk"))
    _run(reg._load_storage())
    assert reg._user_control_modes == set()
