"""#896 — what SEM shed is put back after an unload, a stop or a crash.

The shed list lived in memory only. The circuit that fed the user's router
and HA host was shed, SEM died with it, and every shed circuit stayed off.
Now a record goes to disk BEFORE the switch is thrown, and a later start (or
the unload / HA stop itself) turns the load back on — only while it still
shows the shed value, so a hand change is never overwritten.
"""
from __future__ import annotations

import copy
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.features import shed_ledger as SL
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)

LM = "custom_components.solar_energy_management.features.load_management"
ENT = "switch.fridge"


class FakeStore:
    """A disk: save keeps a copy, load returns it."""

    def __init__(self):
        self.data = None

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)

    def async_delay_save(self, fn, _delay=0):
        self.data = copy.deepcopy(fn())


def _state(value, **attrs):
    s = MagicMock()
    s.state = value
    s.attributes = attrs
    return s


@pytest.fixture
def lm(mock_hass):
    entry = MagicMock()
    entry.options = {"load_management_enabled": True}
    entry.entry_id = "e"
    with patch(f"{LM}.LoadDeviceDiscovery") as MD, patch(f"{LM}.Store"):
        disc = MagicMock()
        MD.return_value = disc
        c = LoadManagementCoordinator(mock_hass, entry)
    c._device_discovery = disc
    c.disk = FakeStore()
    c._ledger = SL.ShedLedger(c.disk)
    c.states = {ENT: _state("on")}
    c.calls = []
    c.seen_at_write = []
    mock_hass.states.get = MagicMock(side_effect=lambda e: c.states.get(e))

    async def call(domain, service, data, blocking=False):
        c.calls.append((domain, service, data["entity_id"]))
        c.states[data["entity_id"]] = _state("on" if service == "turn_on" else "off")
    mock_hass.services.async_call = AsyncMock(side_effect=call)

    async def turn_off(info):
        c.seen_at_write.append(copy.deepcopy(c.disk.data))   # disk BEFORE the write
        c.states[info["switch_entity"]] = _state("off")
        return True
    disc.turn_off_device = AsyncMock(side_effect=turn_off)

    async def turn_on(info):
        c.states[info["switch_entity"]] = _state("on")
        return True
    disc.turn_on_device = AsyncMock(side_effect=turn_on)
    disc.get_device_current_state = MagicMock(
        side_effect=lambda info: {"is_on": c.states[info["switch_entity"]].state == "on",
                                  "current_power": 100})
    c._devices["fridge"] = {
        "switch_entity": ENT, "friendly_name": "Fridge", "power_rating": 100,
        "is_available": True, "priority": 9, "is_critical": False,
        "is_controllable": True, "has_control_handle": True,
        "last_turned_on": dt_util.now() - timedelta(hours=2),
    }
    return c


async def _shed(lm):
    assert await lm._shed_device("fridge", "EMERGENCY") is True


@pytest.mark.asyncio
async def test_record_is_on_disk_before_the_switch_is_thrown(lm):
    await _shed(lm)
    assert lm.seen_at_write[0]["records"]["fridge"]["entity"] == ENT
    assert lm.seen_at_write[0]["records"]["fridge"]["found_on"] is True


@pytest.mark.asyncio
async def test_shed_then_unload_restores_and_clears_the_record(lm):
    await _shed(lm)
    assert await lm.async_shutdown() == 1
    assert lm.calls == [("switch", "turn_on", ENT)]
    assert lm.states[ENT].state == "on"
    assert lm.disk.data["records"] == {}


@pytest.mark.asyncio
async def test_ha_stop_event_restores(lm):
    await _shed(lm)
    await lm._async_on_ha_stop(None)
    assert lm.calls == [("switch", "turn_on", ENT)]


@pytest.mark.asyncio
async def test_crash_then_setup_restores_from_disk(lm):
    await _shed(lm)
    # crash: memory gone, disk stays
    lm._devices_shed.clear()
    lm._ledger = SL.ShedLedger(lm.disk)
    await lm._ledger.async_load()
    assert await lm.async_recover_pass() == 0
    assert lm.calls == [("switch", "turn_on", ENT)]
    assert lm.disk.data["records"] == {}


@pytest.mark.asyncio
async def test_hand_change_in_between_writes_nothing(lm):
    await _shed(lm)
    lm._devices_shed.clear()
    lm.states[ENT] = _state("on")          # the user switched it on again
    assert await lm.async_recover_pass() == 0
    assert lm.calls == []
    assert lm.disk.data["records"] == {}   # record dropped


@pytest.mark.asyncio
async def test_hand_off_after_a_normal_restore_is_not_revived(lm):
    """The record goes with the restore; a later hand-off must not read as ours."""
    await _shed(lm)
    lm._devices["fridge"]["last_turned_off"] = dt_util.now() - timedelta(hours=1)
    await lm._restore_device("fridge")
    assert lm.disk.data["records"] == {}
    lm.states[ENT] = _state("off")         # the user turns it off by hand
    await lm.async_recover_pass()
    lm.calls.clear()
    await lm.async_restore_all_shed()
    assert lm.calls == []


@pytest.mark.asyncio
async def test_observer_records_and_writes_nothing(lm):
    lm._observer_mode = True
    lm._device_discovery.turn_off_device = AsyncMock(return_value=True)
    await lm._shed_device("fridge", "EMERGENCY")
    assert lm._ledger.records == {} and lm.disk.data is None
    assert lm.calls == []


@pytest.mark.asyncio
async def test_observer_on_at_unload_writes_nothing_and_keeps_the_record(lm):
    await _shed(lm)
    lm._observer_mode = True
    assert await lm.async_shutdown() == 0
    assert lm.calls == []
    assert "fridge" in lm.disk.data["records"]


@pytest.mark.asyncio
async def test_device_removed_since_drops_the_record(lm):
    await _shed(lm)
    lm._devices_shed.clear()
    del lm._devices["fridge"]
    await lm.async_recover_pass()
    assert lm.calls == [] and lm.disk.data["records"] == {}


@pytest.mark.asyncio
async def test_unreadable_entity_waits_then_restores(lm):
    await _shed(lm)
    lm._devices_shed.clear()
    lm.states[ENT] = _state("unavailable")     # its integration is not up yet
    assert await lm.async_recover_pass() == 1
    assert lm.calls == []
    lm.states[ENT] = _state("off")
    assert await lm.async_recover_pass() == 0
    assert lm.calls == [("switch", "turn_on", ENT)]


@pytest.mark.asyncio
async def test_old_record_is_still_restored_and_logged(lm, caplog):
    await _shed(lm)
    lm._devices_shed.clear()
    lm._ledger.records["fridge"]["at"] = (dt_util.now() - timedelta(hours=30)).isoformat()
    with caplog.at_level(logging.WARNING):
        await lm.async_recover_pass()
    assert lm.calls == [("switch", "turn_on", ENT)]
    assert "shed record" in caplog.text


@pytest.mark.asyncio
async def test_a_live_shed_is_left_to_the_running_manager(lm):
    await _shed(lm)                            # still in _devices_shed
    await lm.async_recover_pass()
    assert lm.calls == []
    assert "fridge" in lm._ledger.records


@pytest.mark.asyncio
async def test_failed_shed_leaves_no_record(lm):
    lm._device_discovery.turn_off_device = AsyncMock(return_value=False)
    assert await lm._shed_device("fridge", "EMERGENCY") is False
    assert lm._ledger.records == {}


@pytest.mark.asyncio
async def test_setpoint_load_returns_to_what_it_was(lm):
    lm._devices["rod"] = {
        "control": {"type": "setpoint", "entity": "number.rod_w"},
        "friendly_name": "Rod", "is_available": True, "priority": 9,
        "has_control_handle": True, "last_turned_on": dt_util.now() - timedelta(hours=2)}
    lm.states["number.rod_w"] = _state("2500", min=0, max=3000)
    lm._can_shed_device = MagicMock(return_value=True)
    with patch(f"{LM}.resolved_control_type", return_value="setpoint"):
        await lm._shed_device("rod", "EMERGENCY")
    rec = lm._ledger.records["rod"]
    assert rec["kind"] == SL.KIND_SETPOINT and rec["found"] == 2500.0
    lm._devices_shed.clear()
    await lm.async_recover_pass()
    assert lm.calls[-1][1] == "set_value"


@pytest.mark.asyncio
async def test_setup_registers_the_stop_listener(lm, mock_hass):
    mock_hass.async_create_task = lambda coro: coro.close()
    lm._load_device_configuration = AsyncMock()
    await lm.async_initialize()
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    assert mock_hass.bus.async_listen_once.call_args[0][0] == EVENT_HOMEASSISTANT_STOP


@pytest.mark.asyncio
async def test_never_switch_off_on_every_shed_path(lm):
    lm._devices["fridge"]["is_critical"] = True
    for reason in ("EMERGENCY", "PROGRESSIVE", "PHASE"):
        assert await lm._shed_device("fridge", reason) is False
    assert lm._ledger.records == {} and lm.states[ENT].state == "on"
    assert lm._get_devices_for_shedding() == []
    assert lm._shed_plan()["candidates"] == []


# ── load management OFF must not strand what SEM shed ──────────────────────


@pytest.mark.asyncio
async def test_lm_on_shed_then_off_and_restart_restores(lm, mock_hass):
    """LM on -> shed -> LM off + restart: no manager exists; the stand-alone
    helper reads the same file and puts the load back."""
    await _shed(lm)
    with patch("homeassistant.helpers.storage.Store", return_value=lm.disk):
        helper = SL.OrphanRecovery(mock_hass, observer=False)
    mock_hass.async_create_task = lambda coro: coro.close()
    assert await helper.async_start() is True
    assert await helper.async_pass() == 0
    assert lm.calls == [("switch", "turn_on", ENT)]
    assert lm.disk.data["records"] == {}


@pytest.mark.asyncio
async def test_orphan_helper_obeys_hand_change_and_observer(lm, mock_hass):
    await _shed(lm)
    with patch("homeassistant.helpers.storage.Store", return_value=lm.disk):
        watching = SL.OrphanRecovery(mock_hass, observer=True)
    await watching.ledger.async_load()
    await watching.async_pass()
    assert lm.calls == [] and "fridge" in lm.disk.data["records"]
    lm.states[ENT] = _state("on")                    # changed by hand
    with patch("homeassistant.helpers.storage.Store", return_value=lm.disk):
        helper = SL.OrphanRecovery(mock_hass, observer=False)
    await helper.ledger.async_load()
    await helper.async_pass()
    assert lm.calls == [] and lm.disk.data["records"] == {}


@pytest.mark.asyncio
async def test_lm_switched_off_at_runtime_restores_everything(lm):
    await _shed(lm)
    await lm.async_sync_enabled(False)
    assert lm.calls == [("switch", "turn_on", ENT)]
    assert lm._enabled is False and lm.disk.data["records"] == {}


@pytest.mark.asyncio
async def test_runtime_off_in_observer_writes_nothing(lm):
    await _shed(lm)
    lm._observer_mode = True
    await lm.async_sync_enabled(False)
    assert lm.calls == [] and "fridge" in lm.disk.data["records"]


@pytest.mark.asyncio
async def test_unload_restores_shed_loads_before_batteries_and_chargers():
    """async_unload_entry calls the shed restore first."""
    from custom_components.solar_energy_management import async_unload_entry
    order = []
    coord = MagicMock()
    coord._observer_mode = False
    coord._load_manager.async_shutdown = AsyncMock(
        side_effect=lambda: order.append("shed"))
    coord._shed_orphans.async_shutdown = AsyncMock(
        side_effect=lambda: order.append("orphans"))
    coord.async_release_export_guard = AsyncMock(
        side_effect=lambda **k: order.append("export"))
    coord.export_release_recipes = MagicMock(return_value=[])
    coord._ev_devices = {}

    async def batteries(_c):
        order.append("batteries")
        return {}
    hass = MagicMock()
    hass.data = {"solar_energy_management": {"e1": coord}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = MagicMock(entry_id="e1", disabled_by=None)
    base = "custom_components.solar_energy_management"
    with patch(f"{base}.coordinator.battery_adapters.base.async_release_batteries_on_unload",
               batteries), patch(f"{base}._async_end_store", AsyncMock()), \
            patch(f"{base}._async_say_the_park_is_unpaid", AsyncMock()), \
            patch(f"{base}.async_pending_pacing_release", AsyncMock(return_value=None),
                  create=True):
        try:
            await async_unload_entry(hass, entry)
        except Exception:  # noqa: BLE001 — only the order matters here
            pass
    assert order[:2] == ["shed", "orphans"]
    assert "batteries" in order and order.index("shed") < order.index("batteries")
