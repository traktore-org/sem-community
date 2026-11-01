"""#1257 — a saved Deye snapshot follows its battery when the number changes.

The store key is the battery's place in the Energy Dashboard list (b1, b2).
Remove one and the later batteries move up, so their saved settings were
looked for under a number that held none, or another battery's. The snapshot
names its entities: the one that is this battery's moves to this number, with
its safety latch.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.battery_adapters import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye_snapshot_store import (
    DeyeSnapshotStore,
)

from .test_deye_snapshot_store import (  # noqa: F401  (fixture)
    _States,
    _valid_deye_config,
    fake_store_class,
)

ENTRY = "entry-1"


def _snap(bid, mapping):
    return {"schema_version": 2, "config_entry_id": ENTRY, "battery_id": bid,
            "entity_mapping": [list(m) for m in mapping], "marker": bid}


A = (("grid_charge_switch", "switch.a"),)
B = (("grid_charge_switch", "switch.b"),)


def _store(bid):
    return DeyeSnapshotStore(MagicMock(), ENTRY, bid)


async def test_the_snapshot_moves_to_the_new_number(fake_store_class):
    await _store("b3").async_save(_snap("b3", B))
    await _store("b2").async_save(_snap("b2", A))        # the removed battery's
    mine = _store("b2")
    assert await mine.async_adopt_sibling_snapshot(B) is True
    moved = await mine.async_load()
    assert moved["battery_id"] == "b2" and moved["marker"] == "b3"
    # the displaced one goes to the number the first left
    back = await _store("b3").async_load()
    assert back["battery_id"] == "b3" and back["marker"] == "b2"


async def test_nothing_moves_when_the_number_holds_its_own(fake_store_class):
    await _store("b2").async_save(_snap("b2", B))
    await _store("b3").async_save(_snap("b3", B))
    assert await _store("b2").async_adopt_sibling_snapshot(B) is False
    assert (await _store("b3").async_load())["marker"] == "b3"


async def test_nothing_moves_when_no_sibling_matches(fake_store_class):
    await _store("b1").async_save(_snap("b1", A))
    mine = _store("b2")
    assert await mine.async_adopt_sibling_snapshot(B) is False
    assert await mine.async_load() is None
    assert (await _store("b1").async_load())["marker"] == "b1"


async def test_another_entry_is_never_touched(fake_store_class):
    other = DeyeSnapshotStore(MagicMock(), "entry-2", "b3")
    await other.async_save({**_snap("b3", B), "config_entry_id": "entry-2"})
    assert await _store("b2").async_adopt_sibling_snapshot(B) is False
    assert (await other.async_load())["marker"] == "b3"


async def test_a_latched_snapshot_keeps_its_latch(fake_store_class):
    await _store("b3").async_save(_snap("b3", B))
    await _store("b3").async_set_unsafe(True)
    mine = _store("b2")
    assert await mine.async_adopt_sibling_snapshot(B) is True
    assert await _store("b2").async_load_latch() is True
    assert await _store("b3").async_load_latch() is False


async def test_a_store_that_fails_costs_nothing(fake_store_class):
    mine = _store("b2")
    mine.async_load = AsyncMock(side_effect=OSError("disk"))
    assert await mine.async_adopt_sibling_snapshot(B) is False


async def test_a_battery_that_moved_up_gets_its_settings_back(fake_store_class):
    """The whole road: b3's snapshot, the adapter now b2, recovery puts the
    inverter back and clears it."""
    config, states = _valid_deye_config()
    hass = MagicMock()
    hass.states = _States(states)
    hass.services = SimpleNamespace(async_call=AsyncMock(return_value=None))

    def build(bid):
        return DeyeBatteryAdapter(hass, {
            **config, "config_entry_id": ENTRY, "battery_id": bid,
            "deye_observer_mode": False, "deye_actuation_enabled": True,
            "deye_readback_attempts": 1,
            "deye_snapshot_store": DeyeSnapshotStore(hass, ENTRY, bid)})

    before = build("b3")
    assert await before._take_snapshot("session") is not None
    assert await DeyeSnapshotStore(hass, ENTRY, "b3").async_load() is not None

    after = build("b2")                  # the battery above it was removed
    assert await DeyeSnapshotStore(hass, ENTRY, "b2").async_load() is None
    await after.async_recover_pending()
    assert after.last_intent.value == "normal"
    assert hass.services.async_call.await_count > 0       # the restore wrote
    assert await DeyeSnapshotStore(hass, ENTRY, "b2").async_load() is None
    assert await DeyeSnapshotStore(hass, ENTRY, "b3").async_load() is None
