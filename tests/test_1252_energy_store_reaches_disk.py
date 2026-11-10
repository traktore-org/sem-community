"""#1252 — the energy store only reached disk at a clean stop.

Each cycle queued ``async_save_energy_delayed``. That timer re-arms on every
call, so under the running update loop it never fires. On a home without a
battery nothing else wrote the store, so a power cut lost the day's EV
sessions, learned signs and hints. The cycle now writes it for real, at most
once per ``ENERGY_SAVE_INTERVAL`` (the way the daily store is written).
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

COORD = Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"


def _attr_calls(name):
    tree = ast.parse(COORD.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == name]


def test_the_cycle_does_not_queue_a_save_that_never_fires():
    assert not _attr_calls("async_save_energy_delayed"), (
        "a re-arming delayed save never lands while the update loop runs")


def test_the_cycle_persist_writes_the_energy_store_throttled():
    assert len(_attr_calls("async_save_energy_throttled")) >= 2, (
        "the step-13 persist and the battery night record both write it")


def _storage():
    from custom_components.solar_energy_management.coordinator.storage import (
        SEMStorage,
    )
    with patch("custom_components.solar_energy_management.coordinator.storage.Store"):
        st = SEMStorage(MagicMock(), "e1252")
    st._energy_store, st._daily_store = MagicMock(), MagicMock()
    saved = []

    async def _save(data):
        saved.append(data)

    st._energy_store.async_save = _save
    st._loaded = True
    return st, saved


def test_a_burst_of_cycles_is_one_write_not_one_per_cycle():
    st, saved = _storage()

    async def run():
        for _ in range(50):
            await st.async_save_energy_throttled()

    asyncio.run(run())
    assert len(saved) == 1
    st._energy_store.async_delay_save.assert_not_called()


def test_the_data_written_is_the_energy_data():
    st, saved = _storage()
    st._energy_data["finished_ev_sessions"] = [{"kwh": 7.5}]
    asyncio.run(st.async_save_energy_throttled())
    assert saved[0]["finished_ev_sessions"] == [{"kwh": 7.5}]


def test_the_first_save_is_written_on_a_host_that_just_booted():
    """``time.monotonic()`` counts from boot. With uptime under the interval
    the first save was refused — the minutes a record most needs to survive
    an unclean reboot. A fast CI machine showed it (#1266)."""
    st, saved = _storage()
    st._energy_data["finished_ev_sessions"] = [{"kwh": 1.0}]
    with patch("custom_components.solar_energy_management.coordinator.storage"
               ".time.monotonic", return_value=5.0):
        asyncio.run(st.async_save_energy_throttled())
        asyncio.run(st.async_save_energy_throttled())
    assert len(saved) == 1


def test_the_first_daily_save_is_written_on_a_host_that_just_booted():
    st, _ = _storage()
    written = []

    async def _save(data):
        written.append(data)

    st._daily_store.async_save = _save
    with patch("custom_components.solar_energy_management.coordinator.storage"
               ".time.monotonic", return_value=5.0):
        asyncio.run(st.async_save_daily_throttled())
        asyncio.run(st.async_save_daily_throttled())
    assert len(written) == 1

