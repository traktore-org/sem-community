"""#1419 / #1381 — a device does nothing until the user turns SEM control on.

@RienduPre: at night the peak shed switched off two cameras ("Camera enabled"
switches), a bedroom plug and a TV display, during a 10 kW car charge they
could not relieve. The rows were old pattern-discovery rows with no Mode.

The rules pinned here:

1. Permission: a load row whose Mode nobody chose does nothing. A charger
   row is governed by its charge mode and is not affected.
2. Old pattern rows are not loaded; one Repair names them.
3. Security devices (camera, alarm panel, lock, siren — HA's own domains)
   are never a load: not listed, not offered, never paired as a control.
4. Shedding holds when everything SEM may shed covers less than a quarter of
   the need, and what it already shed for that comes back.
5. update_device_config refuses an unknown id BEFORE it writes anything.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.features import (
    load_device_discovery as LDD,
)
from custom_components.solar_energy_management.features.device_axes import (
    may_actuate,
    mode_permits,
)
from custom_components.solar_energy_management.features.device_registry import (
    DEFAULT_DISCOVERED_CONTROL_MODE,
)
from custom_components.solar_energy_management.features.load_management import (
    SHED_MIN_COVER_SHARE,
    LoadManagementCoordinator,
    LoadManagementState,
)

LM = "custom_components.solar_energy_management.features.load_management"
IR = "custom_components.solar_energy_management.coordinator.repair_issues.ir"


# -- 1. permission ----------------------------------------------------------

def test_a_row_with_no_chosen_mode_does_nothing():
    assert may_actuate({"has_control_handle": True}) is False
    assert mode_permits({}) is False
    assert mode_permits({"control_mode": "off"}) is False
    assert mode_permits({"control_mode": "nonsense"}) is False


@pytest.mark.parametrize("mode", ["surplus", "peak_only"])
def test_a_mode_the_user_turned_on_permits(mode):
    assert may_actuate({"has_control_handle": True, "control_mode": mode}) is True


def test_a_charger_row_is_governed_by_its_charge_mode_not_this():
    row = {"device_type": "ev_charger", "has_control_handle": True}
    assert mode_permits(row) is True and may_actuate(row) is True


def test_a_charger_typed_row_the_user_set_to_off_stays_off():
    """Found on .175: an Energy-Dashboard row typed ev_charger at Mode Off."""
    row = {"device_type": "ev_charger", "has_control_handle": True,
           "control_mode": "off"}
    assert may_actuate(row) is False


def test_new_devices_start_off():
    """#805 already made a newly found device start at Off; #1419 keeps it."""
    assert DEFAULT_DISCOVERED_CONTROL_MODE == "off"


# -- 3. security devices ------------------------------------------------------

class _Reg:
    """A fake entity registry."""

    def __init__(self, entries):
        self._e = {e.entity_id: e for e in entries}

    def async_get(self, eid):
        return self._e.get(eid)

    def entries_for(self, dev):
        return [e for e in self._e.values() if e.device_id == dev]


def _e(eid, dev, *, cat=None, key=None, dc=None):
    return SimpleNamespace(entity_id=eid, device_id=dev, entity_category=cat,
                           translation_key=key, original_device_class=dc,
                           device_class=None, original_name=None)


def _patch_registry(monkeypatch, entries):
    reg = _Reg(entries)
    monkeypatch.setattr(LDD.entity_registry, "async_get", lambda _hass: reg)
    monkeypatch.setattr(
        LDD.entity_registry, "async_entries_for_device",
        lambda r, dev, include_disabled_entities=True: r.entries_for(dev))
    return reg


def _e2(eid, dev, *, cat=None, key=None, name=None, dc=None):
    e = _e(eid, dev, cat=cat, key=key, dc=dc)
    e.original_name = name
    return e


DEVICES = [
    # security devices
    _e("camera.voortuin", "cam"), _e("switch.voortuin_camera_enabled", "cam"),
    _e("sensor.voortuin_power", "cam", dc="power"),
    _e("alarm_control_panel.house", "alarm"), _e("switch.alarm_chime", "alarm"),
    _e("siren.hall", "siren"), _e("switch.hall_siren_volume", "siren"),
    _e("lock.front_door", "door"), _e("switch.front_door_auto_lock", "door"),
    # the reviewer's cases: names say "child"/"key", metadata says door lock
    _e("lock.child_room_door", "kids"), _e("switch.child_room_light", "kids"),
    _e("lock.front_door_key_lock", "front2"), _e("switch.front2_relay", "front2"),
    # a smart lock with an unmarked switch and a power sensor is still a lock
    _e("lock.smart", "smart"), _e("switch.smart_auto_lock", "smart"),
    _e("sensor.smart_power", "smart", dc="power"),
    # a washer whose only lock is unmarked: safe side (security, with a Repair)
    _e("lock.washer_lock", "washer2"), _e("switch.washer2", "washer2"),
    # loads whose lock HA marks as a setting
    _e("switch.washer_power", "washer"), _e("sensor.washer_power", "washer", dc="power"),
    _e("lock.washer_child_lock", "washer", cat="config"),
    _e("climate.heat_pump", "hp"), _e("sensor.heat_pump_power", "hp", dc="power"),
    _e("lock.heat_pump_key_lock", "hp", key="key_lock"),
    _e("climate.trv_kitchen", "trv"), _e("sensor.trv_kitchen_power", "trv", dc="power"),
    _e2("lock.trv_kitchen_x", "trv", name="Child lock"),   # integration's own name
    _e("switch.dishwasher", "plug"), _e("sensor.dishwasher_power", "plug", dc="power"),
    _e("switch.template_helper", None),
]


@pytest.mark.parametrize("eid, expected", [
    ("camera.voortuin", True),
    ("switch.voortuin_camera_enabled", True),
    ("sensor.voortuin_power", True),
    ("switch.alarm_chime", True),
    ("switch.hall_siren_volume", True),
    ("switch.front_door_auto_lock", True),
    ("switch.child_room_light", True),       # "child" in a door's id is a door
    ("switch.front2_relay", True),           # "key_lock" in an id is a door
    ("switch.smart_auto_lock", True),        # a lock with a power sensor
    ("switch.washer2", True),                # unmarked lock: safe side
    ("switch.washer_power", False),          # config child lock: a load
    ("sensor.heat_pump_power", False),       # integration's key_lock: a load
    ("climate.trv_kitchen", False),          # integration's "Child lock" name
    ("switch.dishwasher", False),
    ("switch.template_helper", False),
    ("switch.unknown_to_registry", False),
    (None, False),
])
def test_security_is_the_device_role(monkeypatch, eid, expected):
    _patch_registry(monkeypatch, DEVICES)
    assert LDD.is_security_entity(MagicMock(), eid) is expected


def test_a_user_may_choose_a_lock_only_device_but_never_a_camera(monkeypatch):
    _patch_registry(monkeypatch, DEVICES)
    h = MagicMock()
    assert LDD.is_security_entity(h, "switch.washer2", chosen=True) is False
    assert LDD.is_security_entity(h, "switch.voortuin_camera_enabled", chosen=True) is True


def test_a_lock_only_exclusion_is_always_named(monkeypatch):
    """lock.washer_lock hides the washer (safe side) — a Repair names it even
    when SEM never knew the device, with how to keep it."""
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry,
    )
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg.hass = MagicMock()
    for k in ("_control_mode_overrides", "_priority_overrides", "_critical_overrides",
              "_service_registrations", "_device_goals"):
        setattr(reg, k, {})
    with patch(f"{IR}.async_create_issue") as create:
        reg._note_security_exclusion("energy_dashboard_washer", "Washer", always=True)
        reg._note_security_exclusion("energy_dashboard_cam", "Cam")   # unknown, strong
    calls = [c for c in create.call_args_list
             if c.kwargs.get("issue_id") == "security_devices_not_used"]
    assert len(calls) == 1
    assert calls[0].kwargs["translation_placeholders"]["names"] == "Washer"


def test_a_security_switch_is_never_paired_as_a_control(monkeypatch):
    _patch_registry(monkeypatch, DEVICES)
    disc = LDD.LoadDeviceDiscovery.__new__(LDD.LoadDeviceDiscovery)
    disc.hass = MagicMock()
    disc._entity_registry = MagicMock()
    disc._entity_registry.async_get = MagicMock(return_value=None)  # no category
    assert disc.is_not_a_control("switch.voortuin_camera_enabled") is True
    assert disc.is_not_a_control("switch.washer_power") is False
    assert disc.is_not_a_control("switch.smart_auto_lock") is True


def test_the_rule_lives_in_one_place():
    """The registry and both services ask the one function."""
    import inspect
    from custom_components.solar_energy_management.features import device_registry
    import custom_components.solar_energy_management as pkg
    assert "is_security_entity" in inspect.getsource(device_registry)
    src = inspect.getsource(pkg)
    # register_surplus_device, set_device_control_mapping, schedule_appliance
    assert src.count("is_security_entity(hass") == 3
    assert LDD.SECURITY_DOMAINS == frozenset({"camera", "alarm_control_panel", "siren"})


# -- 2. old pattern rows: not loaded, one Repair names them ------------------

class _Store:
    def __init__(self, data):
        self.data = copy.deepcopy(data)

    async def async_load(self):
        return copy.deepcopy(self.data)


@pytest.fixture
def lm(mock_hass):
    entry = MagicMock()
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "e"
    with patch(f"{LM}.LoadDeviceDiscovery") as MD, patch(f"{LM}.Store"):
        disc = MagicMock()
        disc.turn_off_device = AsyncMock(return_value=True)
        disc.turn_on_device = AsyncMock(return_value=True)
        MD.return_value = disc
        c = LoadManagementCoordinator(mock_hass, entry)
    c._device_discovery = disc
    c._live = {}
    disc.get_device_current_state = MagicMock(
        side_effect=lambda info: c._live.get(
            info.get("switch_entity"), {"is_on": False, "current_power": 0}))
    st = MagicMock()
    st.state = "on"
    mock_hass.states.get = MagicMock(return_value=st)
    return c


def _pattern(switch, name):
    return {"switch_entity": switch, "device_type": "smart_switch",
            "friendly_name": name, "source": "pattern", "power_rating": 8.0,
            "is_available": True, "is_controllable": True, "priority": 5}


UPGRADE_STORE = {"devices": {
    # two old pattern rows — the reporter's cameras
    "load_device_achtertuin_camera_enabled": _pattern(
        "switch.achtertuin_camera_enabled", "Achtertuin Camera"),
    "load_device_voortuin_camera_enabled": _pattern(
        "switch.voortuin_camera_enabled", "Voortuin Camera"),
    # the charger row stays
    "load_device_ev_charger_1": {"device_type": "ev_charger",
                                 "switch_entity": "number.wb", "charger_id": "ev_charger_1"},
    # an Energy-Dashboard device SEM controls today: the registry wrote its mode
    "energy_dashboard_pool": {"switch_entity": "switch.pool", "control_mode": "peak_only",
                              "is_available": True, "is_controllable": True,
                              "priority": 9, "power_rating": 2000},
    # a service device the user turned on
    "heizband": {"switch_entity": "switch.heizband", "control_mode": "surplus",
                 "is_available": True, "is_controllable": True,
                 "priority": 8, "power_rating": 1000},
    # an Energy-Dashboard device added later: the registry default, Off
    "energy_dashboard_new": {"switch_entity": "switch.new", "control_mode": "off",
                             "is_available": True, "is_controllable": True,
                             "priority": 7, "power_rating": 1500},
}}


@pytest.mark.asyncio
async def test_upgrade_pipeline(lm):
    """Upgrade an install: old camera rows gone with one Repair naming them,
    the devices SEM controls today still shed, a new device stays Off."""
    lm._store = _Store(UPGRADE_STORE)
    with patch(f"{IR}.async_create_issue") as create:
        await lm._load_device_configuration()
    assert "load_device_achtertuin_camera_enabled" not in lm._devices
    assert "load_device_voortuin_camera_enabled" not in lm._devices
    assert "load_device_ev_charger_1" in lm._devices
    issues = [c for c in create.call_args_list
              if c.kwargs.get("issue_id") == "old_found_loads_removed"]
    assert len(issues) == 1
    names = issues[0].kwargs["translation_placeholders"]["names"]
    assert "Achtertuin Camera" in names and "Voortuin Camera" in names

    for sw in ("switch.pool", "switch.heizband", "switch.new"):
        lm._live[sw] = {"is_on": True, "current_power": 1500}
    can = dict(lm._get_devices_for_shedding())
    assert "energy_dashboard_pool" in can          # unchanged by the upgrade
    assert "energy_dashboard_new" not in can       # Off until turned on


def test_an_old_row_is_decided_by_its_source_not_its_id():
    from custom_components.solar_energy_management.features.load_management import (
        is_old_found_row,
    )
    assert is_old_found_row("load_device_cam", {"source": "pattern"})
    assert is_old_found_row("load_device_cam", {"device_type": "smart_switch"})
    assert not is_old_found_row("load_device_pool", {"source": "service_registration"})
    assert not is_old_found_row("load_device_ev_charger_1", {"device_type": "ev_charger"})
    assert not is_old_found_row("energy_dashboard_x", {"source": "pattern"})


@pytest.mark.asyncio
async def test_no_repair_without_old_rows(lm):
    lm._store = _Store({"devices": {"heizband": UPGRADE_STORE["devices"]["heizband"]}})
    with patch(f"{IR}.async_create_issue") as create:
        await lm._load_device_configuration()
    assert not [c for c in create.call_args_list
                if c.kwargs.get("issue_id") == "old_found_loads_removed"]


# -- 4. shedding too small to matter ------------------------------------------

def _load(lm, did, power_w, priority=5):
    lm._devices[did] = {
        "switch_entity": f"switch.{did}", "friendly_name": did,
        "power_rating": power_w, "is_available": True, "priority": priority,
        "is_critical": False, "is_controllable": True, "control_mode": "peak_only",
    }
    lm._live[f"switch.{did}"] = {"is_on": True, "current_power": power_w}


async def _pass(lm, state, *, avg_kw, import_w):
    lm._state = state
    lm._last_grid_import_w = float(import_w)
    await lm._execute_load_management(avg_kw, avg_kw)


@pytest.mark.asyncio
async def test_the_reviewers_case_sheds_nothing(lm):
    """4.85 kW against a 5.0 kW target (aim 4.7): need 150 W, three loads of
    5/5/10 W. Before: one camera shed per pass, no Repair. Now: held."""
    for did, w in (("cam1", 5), ("cam2", 5), ("tv", 10)):
        _load(lm, did, w)
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.2, import_w=4850)
    assert lm._devices_shed == []
    assert lm.get_load_management_data()["shed_path"] == "held:too_small"
    create.assert_not_called()


@pytest.mark.asyncio
async def test_loads_that_cover_the_share_are_still_shed(lm):
    _load(lm, "pool", 2000, priority=9)
    await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.6, import_w=5600)
    assert lm._devices_shed == ["pool"]


@pytest.mark.asyncio
async def test_small_loads_shed_earlier_come_back_while_the_big_load_runs(lm):
    """The night: the cameras were shed, a 10 kW car keeps the state at
    SHEDDING, so the NORMAL-only restore never came. Now they come back."""
    _load(lm, "cam1", 5)
    lm._devices_shed = ["cam1"]
    lm._devices["cam1"]["shed_draw_w"] = 5.0
    lm._live["switch.cam1"] = {"is_on": False, "current_power": 0}
    lm._last_restore_time = None
    await _pass(lm, LoadManagementState.SHEDDING, avg_kw=6.0, import_w=5900)
    assert lm.get_load_management_data()["shed_path"] == "restore:too_small"
    assert lm._devices_shed == []        # back on, one per pass


@pytest.mark.asyncio
async def test_a_shed_that_does_not_move_the_meter_does_not_end_shedding(lm):
    """Reviewer: the meter did not answer the first shed (a load drew less
    than its rating), so the REMAINING sheddable looked too small and the
    rest stayed on while the first stayed off. The episode counts both.

    Import 5.1 kW, aim 4.7 → need 400 W; a quarter is 100 W. Loads 100 + 60.
    After the first shed with no change at the meter, 60 W remain (under a
    quarter) but the episode holds 160 W (over) — shedding goes on."""
    _load(lm, "a", 100, priority=9)
    _load(lm, "b", 60, priority=8)
    await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.2, import_w=5100)
    assert lm._devices_shed == ["a"]
    lm._live["switch.a"] = {"is_on": False, "current_power": 0}
    plan = lm._shed_plan()
    assert plan["too_small"] is False


def test_the_share_is_a_quarter():
    assert SHED_MIN_COVER_SHARE == 0.25


# -- one permission check, structurally ------------------------------------

def test_no_actuation_path_reads_the_off_mode_itself():
    """Every "is it Off?" question on a device object goes through
    device_axes.device_mode_permits, and on a load row through mode_permits."""
    import ast
    import pathlib
    root = pathlib.Path(LDD.__file__).resolve().parents[1]
    offenders = []
    # The seam (``ControllableDevice.send``) is NOT the place for a mode guard:
    # switching a load to Off while SEM drives it must still send ONE stop to
    # release it (surplus_controller, class 17), and a charger's mode is its
    # charge mode. So the guard lives in the deciders, and this test makes
    # sure every decider asks the one function.
    for path in list(root.glob("coordinator/*.py")) + list(root.glob("devices/*.py")) \
            + list(root.glob("features/*.py")) + [root / "__init__.py"]:
        if path.name == "device_axes.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            parts = [node.left, *node.comparators]
            text = " ".join(ast.unparse(p) for p in parts)
            if ("DeviceControlMode.OFF" in text
                    or ("control_mode" in text and "'off'" in text)):
                offenders.append(f"{path.name}:{node.lineno} {ast.unparse(node)}")
    assert offenders == []


def test_device_objects_ask_the_same_modes():
    from custom_components.solar_energy_management.devices.base import DeviceControlMode
    from custom_components.solar_energy_management.features.device_axes import (
        device_mode_permits,
    )
    assert device_mode_permits(SimpleNamespace(control_mode=DeviceControlMode.OFF)) is False
    assert device_mode_permits(SimpleNamespace(control_mode=DeviceControlMode.PEAK_ONLY))
    assert device_mode_permits(SimpleNamespace(control_mode=DeviceControlMode.SURPLUS))
    assert device_mode_permits(SimpleNamespace()) is False
