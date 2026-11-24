"""#1419 — the peak shed switched off loads nobody can see or set.

@RienduPre (2.3.0-beta.25): at night the peak shed turned off a bedroom plug
and a camera's "enabled" switch. Both were ``load_device_*`` rows that
LoadManagement's pattern discovery had made on its own — any ``switch.*`` it
could pair with a power sensor by name. They were not on the Devices card, the
user could not mark them critical or set their Mode, and
``update_device_config`` answered "not found".

Root cause: two facts.

1. Pattern discovery still ran on 2.x. LoadManagement starts it 30 s after its
   own start, which #1106 moved before the first refresh, and only the unified
   registry's start — much later — sets the flag that turns it off.
2. ``_sync_to_load_manager`` keeps every ``load_device_*`` id (#436). That rule
   is for charger rows, but pattern rows share the prefix, so they stayed for
   ever. #779 and #781 took out two kinds of them; the rest stayed.

Fix: pattern discovery is gone, saved pattern rows are not loaded, and the sync
keeps only CHARGER ``load_device_*`` rows. A row that leaves the roster while
SEM holds it off is put back from the shed ledger, not left off.

Point 5 of the same report: a shed load turned back on by hand stayed listed as
shed, and because a restore tries only the first listed load, it blocked the
restore of every other one.
"""
from __future__ import annotations

import copy
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.features import shed_ledger as SL
from custom_components.solar_energy_management.features import (
    load_device_discovery as LDD,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
    LoadManagementState,
    is_charger_load_row,
)

LM = "custom_components.solar_energy_management.features.load_management"


class FakeStore:
    def __init__(self, data=None):
        self.data = copy.deepcopy(data)

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)

    def async_delay_save(self, fn, _delay=0):
        self.data = copy.deepcopy(fn())


def _state(value):
    s = MagicMock()
    s.state = value
    s.attributes = {}
    return s


def _plug(switch, priority=5):
    """A row as pattern discovery saved it (``smart_switch``, no Mode)."""
    return {
        "switch_entity": switch,
        "power_entity": "sensor.slaapkamer_power",
        "device_type": "smart_switch",
        "description": "Smart Switch with Power Monitoring",
        "friendly_name": switch,
        "power_rating": 8.0,
        "is_available": True,
        "priority": priority,
        "is_critical": False,
        "has_control_handle": True,
        "user_hands_off": False,
        "is_controllable": True,
        "source": "pattern",
    }


def _charger_row():
    return {
        "device_type": "ev_charger",
        "switch_entity": "number.wallbox_max_current",
        "power_entity": "sensor.wallbox_power",
        "charger_id": "ev_charger_1",
        "priority": 3,
        "is_critical": False,
    }


SAVED = {
    "devices": {
        "load_device_slaapkamer_apparatuur": _plug("switch.slaapkamer_apparatuur"),
        "load_device_achtertuin_camera_enabled": _plug(
            "switch.achtertuin_camera_enabled"),
        "load_device_ev_charger_1": _charger_row(),
        "energy_dashboard_dishwasher": {
            "device_type": "individual_device", "power_entity": "sensor.dw_power",
            "switch_entity": "switch.dw", "source": "unified_registry",
        },
    },
}


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
    c.states = {}
    c.calls = []
    mock_hass.states.get = MagicMock(side_effect=lambda e: c.states.get(e))

    async def call(domain, service, data, blocking=False):
        c.calls.append((domain, service, data["entity_id"]))
        c.states[data["entity_id"]] = _state("on" if service == "turn_on" else "off")
    mock_hass.services.async_call = AsyncMock(side_effect=call)

    async def turn_off(info):
        c.states[info["switch_entity"]] = _state("off")
        return True
    disc.turn_off_device = AsyncMock(side_effect=turn_off)

    async def turn_on(info):
        c.calls.append(("switch", "turn_on", info["switch_entity"]))
        c.states[info["switch_entity"]] = _state("on")
        return True
    disc.turn_on_device = AsyncMock(side_effect=turn_on)
    disc.get_device_current_state = MagicMock(
        side_effect=lambda info: {
            "is_on": c.states[info["switch_entity"]].state == "on",
            "current_power": 100})
    return c


def _seat(lm, did, switch, priority):
    lm.states[switch] = _state("on")
    lm._devices[did] = {
        "switch_entity": switch, "friendly_name": did, "power_rating": 100,
        "is_available": True, "priority": priority, "is_critical": False,
        "is_controllable": True, "has_control_handle": True,
        "control_mode": "peak_only",
        "last_turned_on": dt_util.now() - timedelta(hours=2),
    }


async def _shed(lm, did):
    assert await lm._shed_device(did, "EMERGENCY") is True
    # past the minimum off time, so a restore is allowed
    lm._devices[did]["last_turned_off"] = dt_util.now() - timedelta(hours=1)


# -- 1. no code makes a pattern row any more -------------------------------

def test_pattern_discovery_is_gone():
    """The only code that made ``load_device_<switch>`` rows is retired."""
    assert not hasattr(LDD.LoadDeviceDiscovery, "discover_controllable_devices")


@pytest.mark.asyncio
async def test_discovery_without_the_registry_adds_no_pattern_row(lm):
    """The race: LoadManagement's own discovery ran before the registry's
    start set the flag. Whatever the switches look like, no row comes of it
    but the Energy Dashboard's own devices."""
    lm._unified_registry_active = False
    lm._device_discovery.discover_from_energy_dashboard = AsyncMock(return_value={
        "energy_dashboard_dishwasher": {"power_entity": "sensor.dw_power"}})
    lm._device_discovery.discover_controllable_devices = MagicMock(return_value={
        "load_device_slaapkamer_apparatuur": _plug("switch.slaapkamer_apparatuur")})
    lm._store = FakeStore()
    await lm._discover_devices()
    assert "load_device_slaapkamer_apparatuur" not in lm._devices
    assert "energy_dashboard_dishwasher" in lm._devices


# -- 2. saved pattern rows are not loaded ----------------------------------

@pytest.mark.asyncio
async def test_saved_pattern_rows_are_not_loaded(lm):
    lm._store = FakeStore(SAVED)
    await lm._load_device_configuration()
    assert set(lm._devices) == {
        "load_device_ev_charger_1", "energy_dashboard_dishwasher"}


@pytest.mark.asyncio
async def test_a_pattern_row_shed_before_the_update_is_put_back(lm):
    """SEM shed the plug, then HA restarted on the new code. The row is not
    loaded, but the ledger still names the switch: it goes back on."""
    lm._store = FakeStore(SAVED)
    lm.disk.data = {"records": {"load_device_slaapkamer_apparatuur": SL.make_record(
        SL.KIND_SWITCH, "switch", "switch.slaapkamer_apparatuur", found_on=True)}}
    await lm._ledger.async_load()
    lm.states["switch.slaapkamer_apparatuur"] = _state("off")
    await lm._load_device_configuration()
    assert await lm.async_recover_pass() == 0
    assert lm.calls == [("switch", "turn_on", "switch.slaapkamer_apparatuur")]


@pytest.mark.asyncio
async def test_shed_candidates_hold_no_pattern_row(lm):
    """The harm itself: the camera switch was a live shed candidate."""
    for ent in ("switch.slaapkamer_apparatuur", "switch.achtertuin_camera_enabled",
                "switch.dw", "number.wallbox_max_current"):
        lm.states[ent] = _state("on")
    lm._devices = copy.deepcopy(SAVED["devices"])
    # (#1419) even loaded, a row with no mode the user chose is never shed
    assert "load_device_achtertuin_camera_enabled" not in dict(
        lm._get_devices_for_shedding())
    lm._store = FakeStore(SAVED)
    await lm._load_device_configuration()
    assert "load_device_achtertuin_camera_enabled" not in dict(
        lm._get_devices_for_shedding())


# -- 3. the sync keeps only CHARGER load_device_* rows ---------------------

class _FakeLoadManager:
    def __init__(self, devices, shed=None):
        self._devices = dict(devices)
        self._devices_shed = list(shed or [])
        self._save_device_configuration = AsyncMock()


class _Surplus:
    def get_device(self, _did):
        return None


def _reg(lm, service_regs=None):
    # A discovery that answers "not a setting" — a bare MagicMock answers a
    # truthy mock, and the old #781 prune then dropped every row (vacuous).
    disc = MagicMock()
    disc.is_config_surface = MagicMock(return_value=False)
    r = UnifiedDeviceRegistry(MagicMock(), _Surplus(), lm, disc)
    r._has_battery = False
    r._devices = []
    if service_regs is not None:
        r._service_registrations = dict(service_regs)
    r.hass.states.get = MagicMock(return_value=None)
    return r


def test_sync_drops_a_lone_pattern_row():
    """#779 kept a pattern row with no Energy Dashboard twin as "the device's
    only representation". It was also invisible and could not be set: gone."""
    fake = _FakeLoadManager(copy.deepcopy(SAVED["devices"]))
    assert _reg(fake)._sync_to_load_manager() is True
    assert "load_device_slaapkamer_apparatuur" not in fake._devices
    assert "load_device_achtertuin_camera_enabled" not in fake._devices
    assert "load_device_ev_charger_1" in fake._devices


def test_sync_keeps_every_charger_row_and_a_service_registration():
    fake = _FakeLoadManager({
        "load_device_ev_charger": {"device_type": "ev_charger"},
        "load_device_ev_charger_2": {"device_type": "ev_charger"},
    })
    reg = _reg(fake, service_regs={"load_device_pool": {
        "name": "Pool", "entity_id": "switch.pool", "control_type": "switch"}})
    reg._service_lm_row = MagicMock(return_value={"device_type": "registered"})
    reg._sync_to_load_manager()
    assert {"load_device_ev_charger", "load_device_ev_charger_2",
            "load_device_pool"} <= set(fake._devices)


def test_an_ed_row_marked_ev_is_not_spared_by_its_type():
    """Only the ``load_device_`` charger rows are spared — an Energy
    Dashboard EV row the registry no longer derives still leaves."""
    fake = _FakeLoadManager({"energy_dashboard_old_ev": {"device_type": "ev_charger"}})
    _reg(fake)._sync_to_load_manager()
    assert "energy_dashboard_old_ev" not in fake._devices


def test_charger_row_test():
    assert is_charger_load_row("load_device_ev_charger_1", _charger_row())
    assert not is_charger_load_row("load_device_x", _plug("switch.x"))
    assert not is_charger_load_row("energy_dashboard_ev", {"device_type": "ev_charger"})
    assert not is_charger_load_row("load_device_x", None)


# -- 4. a row that leaves while shed is put back ---------------------------

@pytest.mark.asyncio
async def test_a_shed_row_that_leaves_the_roster_is_put_back(lm):
    """Pre-fix the clean-up forgot the record of a removed row: the load SEM
    switched off stayed off with nobody to turn it back on."""
    _seat(lm, "energy_dashboard_plug", "switch.plug", 5)
    await _shed(lm, "energy_dashboard_plug")
    assert lm.states["switch.plug"].state == "off"
    del lm._devices["energy_dashboard_plug"]       # the registry dropped it
    await lm.process_peak_update(1.0, 1.0, grid_import_w=1000)
    assert ("switch", "turn_on", "switch.plug") in lm.calls
    assert "energy_dashboard_plug" not in lm._devices_shed
    assert "energy_dashboard_plug" not in lm._ledger.records


@pytest.mark.asyncio
async def test_a_removed_row_changed_by_hand_is_left_alone(lm):
    _seat(lm, "energy_dashboard_plug", "switch.plug", 5)
    await _shed(lm, "energy_dashboard_plug")
    del lm._devices["energy_dashboard_plug"]
    lm.states["switch.plug"] = _state("on")          # the user, not SEM
    lm.calls.clear()
    await lm.process_peak_update(1.0, 1.0, grid_import_w=1000)
    assert lm.calls == []
    assert "energy_dashboard_plug" not in lm._ledger.records


# -- 5. a load turned on by hand ------------------------------------------

@pytest.mark.asyncio
async def test_a_load_turned_on_by_hand_does_not_block_the_others(lm):
    _seat(lm, "a", "switch.a", 9)      # restored first (highest number)
    _seat(lm, "b", "switch.b", 5)
    await _shed(lm, "a")
    await _shed(lm, "b")
    lm.states["switch.a"] = _state("on")            # by hand
    lm._cleanup_shed_list()
    lm._state = LoadManagementState.NORMAL
    lm.calls.clear()
    await lm._restore_loads()
    assert lm.calls == [("switch", "turn_on", "switch.b")]
    assert lm._devices_shed == []


@pytest.mark.asyncio
async def test_a_load_turned_on_by_hand_is_not_listed_as_shed(lm):
    _seat(lm, "a", "switch.a", 9)
    _seat(lm, "b", "switch.b", 5)
    await _shed(lm, "a")
    await _shed(lm, "b")
    lm.states["switch.a"] = _state("on")
    lm._cleanup_shed_list()
    data = lm.get_load_management_data()
    assert data["devices"]["a"]["is_shed"] is False
    assert data["devices"]["b"]["is_shed"] is True
    assert data["devices_shed_list"] == ["b"]
    assert data["devices_shed"] == 1
    # …and SEM does not shed it again while the peak lasts: it is theirs
    assert "a" not in dict(lm._get_devices_for_shedding())


@pytest.mark.asyncio
async def test_a_load_turned_on_then_off_by_hand_is_not_turned_on(lm):
    """Somebody switched it on, then off again: their choice, not SEM's to
    undo when the peak ends."""
    _seat(lm, "a", "switch.a", 9)
    await _shed(lm, "a")
    lm.states["switch.a"] = _state("on")
    lm._cleanup_shed_list()
    lm.states["switch.a"] = _state("off")
    lm._state = LoadManagementState.NORMAL
    lm.calls.clear()
    await lm._restore_loads()
    assert lm.calls == []
    assert lm._devices_shed == []
