"""#1209 — a reload starts from the file, so what SEM saves must be on it.

"Reset sign detection" cleared the learned signs and, when a "Fix sign" flip
was on, reloaded SEM. The cleared state was only queued with HA's delayed
save (``async_delay_save``, 60 s, and it re-arms on every cycle). The reload
built a new store that read the file: the old signs came back, and the next
save wrote them again. The flips were gone, so a sign the user had corrected
read the wrong way.

The same shape hit every reload (an options change, "Fix sign", a removed
charger): the new lifetime read the energy store as it was at the last real
write. And the old store lived on: its queued write and its HA-stop listener
wrote that lifetime's data over the next one's, and brought the files of a
removed SEM back.

Pinned on the real integration, with HA's own storage mock as the disk.
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from homeassistant.const import EVENT_HOMEASSISTANT_STOP  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402

from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402


def _energy_key(entry) -> str:
    return f"{DOMAIN}_{entry.entry_id}_energy"


def _daily_key(entry) -> str:
    return f"{DOMAIN}_{entry.entry_id}_daily"


def _saved_signs(hass_storage, entry) -> dict:
    return ((hass_storage.get(_energy_key(entry)) or {}).get("data") or {}).get(
        "sign_state") or {}


def _lock_signs(coordinator) -> None:
    """A grid and a battery sign learned earlier, as the reader holds them."""
    reader = coordinator._sensor_reader
    reader._grid_sign_detected = True
    reader._grid_sign_inverted = True
    reader._battery_sign_detected["__fleet__"] = True
    reader._battery_sign_inverted["__fleet__"] = True
    coordinator._storage.set_sign_state(reader.export_sign_state())


async def _setup(hass, entry, **options):
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


@pytest.mark.asyncio
@pytest.mark.parametrize("flip", ["grid_sign_user_flip", "battery_sign_user_flip"])
async def test_reset_with_a_flip_on_stays_reset_after_its_reload(
    sem_real_hass, sem_config_entry, hass_storage, flip,
) -> None:
    """The report: the reset reloads SEM, and SEM came back with the old signs."""
    hass = sem_real_hass
    old = await _setup(hass, sem_config_entry, **{flip: True})
    _lock_signs(old)
    await old._storage.async_save_energy_now()
    assert _saved_signs(hass_storage, sem_config_entry).get("grid_detected") is True

    await hass.services.async_call(DOMAIN, "reset_sign_detection", {}, blocking=True)
    await hass.async_block_till_done()

    new = sem_config_entry.runtime_data
    assert new is not old, "a flip was on: the reset must reload SEM"
    assert sem_config_entry.options.get(flip) is False
    reader = new._sensor_reader
    assert reader._grid_sign_detected is False, (
        "the reload read the old grid sign back from the file (#1209)")
    assert reader._battery_sign_detected == {}, (
        "the reload read the old battery sign back from the file (#1209)")
    saved = _saved_signs(hass_storage, sem_config_entry)
    assert saved.get("grid_detected") is not True
    assert not any((saved.get("battery_detected") or {}).values())

    # A later save of the new lifetime keeps it reset.
    await new._storage.async_save_energy_now()
    assert _saved_signs(hass_storage, sem_config_entry).get("grid_detected") is not True


@pytest.mark.asyncio
async def test_reset_without_a_flip_is_on_the_file_at_once(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """No flip, no reload: the reset is still a write a restart must find.
    A queued write only lands once the cycles stop, so an unclean restart
    brought the old signs back."""
    hass = sem_real_hass
    old = await _setup(hass, sem_config_entry)
    _lock_signs(old)
    await old._storage.async_save_energy_now()

    await hass.services.async_call(DOMAIN, "reset_sign_detection", {}, blocking=True)
    await hass.async_block_till_done()

    assert sem_config_entry.runtime_data is old, "no flip: no reload"
    saved = _saved_signs(hass_storage, sem_config_entry)
    assert saved.get("grid_detected") is not True, (
        "the reset waited in the delayed save; the file still holds the old sign")
    assert not any((saved.get("battery_detected") or {}).values())


@pytest.mark.asyncio
async def test_a_reload_keeps_what_waited_in_the_delayed_save(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """The same shape on a plain reload: a sign learned this lifetime, queued
    by the cycle's own save, is not lost to the next lifetime."""
    hass = sem_real_hass
    old = await _setup(hass, sem_config_entry)
    _lock_signs(old)
    old._storage.set_hints_state({"seen": ["h1209"]})
    await old._storage.async_save_energy_delayed()   # what each cycle does
    assert _saved_signs(hass_storage, sem_config_entry).get("grid_detected") is not True

    assert await hass.config_entries.async_reload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    new = sem_config_entry.runtime_data
    assert new is not old
    assert new._sensor_reader._grid_sign_detected is True, (
        "the learned grid sign was lost to the reload")
    assert new._sensor_reader._grid_sign_inverted is True
    assert new._storage.get_hints_state() == {"seen": ["h1209"]}


@pytest.mark.asyncio
async def test_an_ended_lifetime_writes_nothing_more(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """After a reload the old store must not write: not its queued write, not
    at HA stop, not when a late task of the old lifetime asks."""
    hass = sem_real_hass
    old = await _setup(hass, sem_config_entry)
    listeners_before = hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0)
    old._storage.set_hints_state({"seen": ["old"]})
    await old._storage.async_save_energy_delayed()

    assert await hass.config_entries.async_reload(sem_config_entry.entry_id)
    await hass.async_block_till_done()
    new = sem_config_entry.runtime_data

    new._storage.set_hints_state({"seen": ["new"]})
    await new._storage.async_save_energy_now()
    # a late task of the old lifetime
    old._storage.set_hints_state({"seen": ["stale"]})
    await old._storage.async_save_energy_now()
    await old._storage.async_save_energy_delayed()
    await old._storage.async_save_daily()
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done()

    data = hass_storage[_energy_key(sem_config_entry)]["data"]
    assert data.get("hints") == {"seen": ["new"]}, (
        "the old lifetime wrote over the new one's file")
    assert hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0) == listeners_before, (
        "each reload left the old store listening for HA stop")


@pytest.mark.asyncio
async def test_a_removed_sem_leaves_no_store_behind(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """Removal takes SEM's files (#935). The old store's queued write and its
    HA-stop listener used to put them back."""
    hass = sem_real_hass
    coordinator = await _setup(hass, sem_config_entry)
    await coordinator._storage.async_save_energy_delayed()   # what each cycle does
    await coordinator._storage.async_save_daily()

    assert await hass.config_entries.async_remove(sem_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _energy_key(sem_config_entry) not in hass_storage
    assert _daily_key(sem_config_entry) not in hass_storage

    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert _energy_key(sem_config_entry) not in hass_storage, (
        "the removed SEM's energy store came back")
    assert _daily_key(sem_config_entry) not in hass_storage, (
        "the removed SEM's daily store came back")


# ── the shape, as source checks ──────────────────────────────────────────

_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _production_files():
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith(("tests/", "tools/", "scripts/")) or "__pycache__" in rel:
            continue
        yield rel, path


def test_only_sems_own_store_queues_a_write() -> None:
    """A queued write (``async_delay_save``) is what a reload cannot see.
    SEMStorage is closed on unload; a second store that queues needs the
    same close, or a reload starts from its old file."""
    import ast

    queued = []
    for rel, path in _production_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Attribute) and node.attr == "async_delay_save"
                    and isinstance(node.ctx, ast.Load)):
                queued.append(f"{rel}:{node.lineno}")
    assert queued and all(q.startswith("coordinator/storage.py:") for q in queued), queued


def test_every_store_writer_stops_once_the_lifetime_ended() -> None:
    """Each SEMStorage method that writes a store asks ``_ended`` first, so a
    late task of an old lifetime cannot write over the next one's file."""
    import ast

    tree = ast.parse((_ROOT / "coordinator/storage.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SEMStorage")
    writers, unguarded = [], []
    for fn in cls.body:
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        writes = any(
            isinstance(n, ast.Attribute)
            and n.attr in ("async_save", "async_delay_save")
            and isinstance(n.value, ast.Attribute)
            and n.value.attr in ("_energy_store", "_daily_store")
            for n in ast.walk(fn))
        if not writes:
            continue
        writers.append(fn.name)
        asks = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_ended"
            for n in ast.walk(fn))
        if not asks and fn.name != "_async_write_all":
            unguarded.append(fn.name)
    assert {"async_save_energy_delayed", "async_save_energy_now",
            "async_save_daily", "_async_write_all"} <= set(writers), writers
    assert not unguarded, f"store writers that write after the close: {unguarded}"
    # the one writer with no check of its own: only a caller that asked
    # ``_ended`` (async_save_all) or ended the store first (async_close)
    callers = {fn.name for fn in cls.body
               if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef))
               and any(isinstance(n, ast.Attribute) and n.attr == "_async_write_all"
                       for n in ast.walk(fn))}
    assert callers == {"async_save_all", "async_close"}, callers


def test_unload_and_a_failed_setup_end_the_store() -> None:
    """Every reload, disable and removal goes through ``async_unload_entry``;
    a setup that fails after the first cycle is never unloaded, so each of
    its ``ConfigEntryNotReady`` branches ends the store itself."""
    import ast

    tree = ast.parse((_ROOT / "__init__.py").read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}

    def _calls(node, name):
        return [n for n in ast.walk(node) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == name]

    assert any(isinstance(n, ast.Attribute) and n.attr == "async_close"
               for n in ast.walk(fns["_async_end_store"]))
    assert _calls(fns["async_unload_entry"], "_async_end_store")
    setup = fns["async_setup_entry"]
    first_refresh = next(
        n for n in ast.walk(setup) if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "async_config_entry_first_refresh")
    late = [h for h in ast.walk(setup) if isinstance(h, ast.ExceptHandler)
            and h.lineno > first_refresh.lineno
            and any(isinstance(r, ast.Raise) and isinstance(r.exc, ast.Call)
                    and getattr(r.exc.func, "id", "") == "ConfigEntryNotReady"
                    for r in ast.walk(h))]
    assert len(late) >= 2, "expected the first-refresh and the platform branches"
    missing = [h.lineno for h in late if not _calls(h, "_async_end_store")]
    assert not missing, f"ConfigEntryNotReady branches that leave the store open: {missing}"


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["first_refresh", "platforms"])
async def test_a_failed_setup_leaves_no_store_listening(
    sem_real_hass, sem_config_entry, hass_storage, where,
) -> None:
    """HA retries a failed setup with a new store and never unloads the
    old one: it must not stay behind to write at HA stop.

    Checked on the store itself, not a global ``hass.bus.async_listeners()``
    count: the first setup attempt in a test can also be the first thing
    that lazily sets up an unrelated HA component (``http``'s own
    ``stop_server`` listener, found live) -- that is a one-time, permanent
    registration, not a per-attempt leak, and it made this test fail
    reproducibly for a reason that had nothing to do with SEM's storage.
    """
    from unittest.mock import patch

    from homeassistant.config_entries import ConfigEntryState

    from custom_components.solar_energy_management.coordinator.storage import SEMStorage

    hass = sem_real_hass
    sem_config_entry.add_to_hass(hass)
    opened = []
    real_load = SEMStorage.async_load

    async def _load_then_fail(self):
        await real_load(self)
        opened.append(self)
        if where == "first_refresh":
            raise RuntimeError("#1209 a cycle that fails after the load")

    async def _no_platforms(*_a, **_k):
        raise RuntimeError("#1209 platforms fail")

    with patch.object(SEMStorage, "async_load", _load_then_fail), patch.object(
            hass.config_entries, "async_forward_entry_setups",
            _no_platforms if where == "platforms"
            else hass.config_entries.async_forward_entry_setups):
        await hass.config_entries.async_setup(sem_config_entry.entry_id)
        await hass.async_block_till_done()

    assert sem_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert opened, "the store was never loaded: the test reached nothing"
    assert all(st._closed for st in opened)
    assert all(st._shutdown_listener is None for st in opened), (
        "a failed setup left its store listening for HA stop")


def test_a_write_asked_for_while_the_close_writes_is_skipped() -> None:
    """The close ends the store before it waits on the disk: a cycle that
    asks for its queued save in that wait gets nothing armed."""
    import asyncio
    from unittest.mock import MagicMock, patch

    from custom_components.solar_energy_management.coordinator.storage import SEMStorage

    hass = MagicMock()
    with patch("custom_components.solar_energy_management.coordinator.storage.Store"):
        st = SEMStorage(hass, "e1209")
    st._energy_store, st._daily_store = MagicMock(), MagicMock()
    st._loaded = True
    asked = []

    async def _slow_save(_data):
        asked.append(await st.async_save_energy_delayed() or "asked")

    st._energy_store.async_save = _slow_save
    st._daily_store.async_save = MagicMock(side_effect=lambda _d: asyncio.sleep(0))
    asyncio.run(st.async_close())

    assert asked == ["asked"], "the test never asked during the close's write"
    st._energy_store.async_delay_save.assert_not_called()
