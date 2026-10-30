"""#1208 — a saved battery sign this build learned is not moved again.

#1194 reads a battery sensor marked "Inverted" as it is. A sign saved while
the one-battery read still flipped it judged the flipped value, so the first
read moves it once. A store without ``battery_basis`` was taken as such a
store. Two other stores lack it too:

* An older build writes ``sign_state`` again from the keys it knows. After
  going back to it and forward again, SEM moved the sign it had learned
  itself: the battery read charge as discharge until Reset sign detection.
* A home without an Energy Dashboard never settled the move, so the mark was
  never saved. A one-battery "Inverted" dashboard added later moved the sign
  (or locked one against "Fix battery sign") that this build had set.

Now the record of what this build saved sits beside ``sign_state``, in a key
an older build keeps (it saves ``{**self._energy_data}``). If the fleet lock
and the flip are still that, the older build changed nothing to move. A read
without a dashboard settles the move with nothing to change, once the
dashboard read got an answer.
"""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import _parse_prefs

FLEET = "__fleet__"
_HAS_REAL_HA = importlib.util.find_spec(
    "pytest_homeassistant_custom_component") is not None

SOLAR = {"type": "solar", "stat_energy_from": "sensor.pv_energy",
         "stat_rate": "sensor.pv_power"}
GRID = {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
        "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
        "stat_rate": "sensor.grid_power"}
INVERTED = {"type": "battery",
            "stat_energy_from": "sensor.batt1_discharge_energy",
            "stat_energy_to": "sensor.batt1_charge_energy",
            "stat_rate": "sensor.batt1_power_inverted",
            "power_config": {"stat_rate_inverted": "sensor.batt1_power"}}

#: What every build before #1194 saved under ``sign_state``.
OLDER_BUILD_KEYS = ("grid_detected", "grid_inverted", "grid_source",
                    "battery_detected", "battery_inverted")


def _ed():
    prefs = {"energy_sources": [SOLAR, GRID, INVERTED], "device_consumption": []}
    return _parse_prefs(MagicMock(), prefs, quiet=True)


def _reader(raw=1200, flip=False, dashboard=True, answered=True, battery_pick=None,
            brand=None):
    """The real reader. ``raw`` is what the battery sensor shows; + is charge
    on an Inverted sensor. No energy counter reads, so no sign is learned."""
    states = {"sensor.pv_power": "3000", "sensor.grid_power": "0",
              "sensor.batt1_power": str(raw),
              "sensor.batt1_power_inverted": str(-raw)}
    hass = MagicMock()
    hass.states.get = lambda eid: (
        MagicMock(state=states[eid], attributes={"unit_of_measurement": "W"})
        if eid in states else None)
    options = {"battery_sign_user_flip": flip}
    if battery_pick:
        options["battery_power_sensor"] = battery_pick
    reader = SensorReader(hass, options)
    reader._entity_owner = lambda eid: (brand, None)   # None: no brand seed
    reader._sign_vote_warmup = 0
    reader.set_dashboard_answered(answered)
    if dashboard:
        reader.set_energy_dashboard_config(_ed())
    return reader


def _older_build_writes(state: dict) -> dict:
    """An older build restores the locks and saves them from its own keys."""
    return {k: state[k] for k in OLDER_BUILD_KEYS if k in state}


def _run_this_build(raw=1200, flip=False, lock=None):
    """This build on a one-battery Inverted home: ``lock`` is the fleet sign
    it learned (None: none yet). Returns what it saves: (state, record)."""
    reader = _reader(raw, flip)
    if lock is not None:
        reader._battery_sign_detected[FLEET] = True
        reader._battery_sign_inverted[FLEET] = lock
    reader.read_power()
    state, record = reader.export_sign_state(), reader.export_battery_basis()
    assert state["battery_basis"] == "sensor" and record is not None
    return state, record


def _back_again(state, record, raw=1200, flip=False):
    """Forward again: the next start of this build reads the older save."""
    reader = _reader(raw, flip)
    reader.restore_sign_state(state, basis=record)
    return reader


# ── Back to an older build and forward again ───────────────────────────────

@pytest.mark.parametrize("lock", [False, True])
@pytest.mark.parametrize("raw", [1200, -800])
def test_a_sign_this_build_learned_survives_an_older_build(lock, raw):
    """The report: the older build kept the lock as it was. It is this
    build's, judged on the sensor as it is, so it is not moved."""
    state, record = _run_this_build(raw, lock=lock)
    this_build = _reader(raw)
    this_build.restore_sign_state(state, basis=record)
    right = this_build.read_power().battery_power

    older = _older_build_writes(state)
    assert "battery_basis" not in older
    reader = _back_again(older, record, raw)
    assert reader.read_power().battery_power == pytest.approx(right)
    assert reader._battery_sign_inverted[FLEET] is lock
    assert reader.export_sign_state()["battery_basis"] == "sensor"


def test_without_the_record_the_older_save_is_moved_as_before():
    """The twin: no record (a save from before #1208) is a store from before
    #1194, and the lock is moved once, as #1194 does."""
    state, _ = _run_this_build(lock=False)
    reader = _back_again(_older_build_writes(state), None)
    reader.read_power()
    assert reader._battery_sign_inverted[FLEET] is True


def test_a_record_from_a_later_build_with_more_keys_still_counts():
    """A later build may save more in the record; the three keys decide."""
    state, record = _run_this_build(lock=False)
    reader = _back_again(_older_build_writes(state), {**record, "later": 1})
    reader.read_power()
    assert reader._battery_sign_inverted[FLEET] is False


@pytest.mark.parametrize("record", ["garbage", [], {"fleet_locked": "yes"}, {}])
def test_a_damaged_record_is_no_record(record):
    state, _ = _run_this_build(lock=False)
    reader = _back_again(_older_build_writes(state), record)
    reader.read_power()
    assert reader._battery_sign_inverted[FLEET] is True


@pytest.mark.parametrize("this_build_lock", [None, False, True])
def test_a_lock_the_older_build_learned_is_still_moved(this_build_lock):
    """The older build read the flipped value. A lock it learned (none was
    saved, or it learned the other one) judged that value: moved, so the
    battery reads as the older build read it, as #1194 does."""
    state, record = _run_this_build(lock=this_build_lock)
    older = _older_build_writes(state)
    learned = True if this_build_lock is None else not this_build_lock
    older["battery_detected"] = {**older["battery_detected"], FLEET: True}
    older["battery_inverted"] = {**older["battery_inverted"], FLEET: learned}
    reader = _back_again(older, record)
    reader.read_power()
    assert reader._battery_sign_inverted[FLEET] is (not learned)


def test_a_flip_this_build_saved_makes_no_lock():
    """No lock, "Fix battery sign" on in this build: the flip judged the
    sensor as it is. Kept through the older build, it stays a flip."""
    state, record = _run_this_build(flip=True)
    reader = _back_again(_older_build_writes(state), record, flip=True)
    assert reader.read_power().battery_power == pytest.approx(-1200.0)
    assert not reader._battery_sign_detected.get(FLEET)


@pytest.mark.parametrize("flip_before", [False, True])
@pytest.mark.parametrize("lock", [None, False, True])
def test_a_flip_changed_in_the_older_build_is_moved(flip_before, lock):
    """The user turned "Fix battery sign" on or off while the older build
    read the flipped value: that is a change to move, as #1194 does. The
    battery reads as the user set it there."""
    raw = 1200
    state, record = _run_this_build(raw, flip=flip_before, lock=lock)
    flip_now = not flip_before
    older = _older_build_writes(state)
    # what the older build showed: the flip, the lock, then the user flip
    shown = -raw
    if lock:
        shown = -shown
    if flip_now:
        shown = -shown
    reader = _back_again(older, record, raw, flip=flip_now)
    if lock is None and not flip_now:
        # no lock and no flip: nothing to keep, it reads right from the start
        assert reader.read_power().battery_power == pytest.approx(float(raw))
        return
    assert reader.read_power().battery_power == pytest.approx(float(shown))
    assert reader._battery_sign_detected[FLEET] is True


def test_a_brand_default_is_not_a_lock_in_the_record():
    """A brand's default sign is set before any lock and is not saved as one,
    so the record holds no sign without a lock: else the older build's save
    would look changed, and the flip would be locked against."""
    this_build = _reader(flip=True, brand="goodwe")   # the table negates goodwe
    shown = this_build.read_power().battery_power
    assert this_build._battery_sign_inverted[FLEET] is True
    assert not this_build._battery_sign_detected.get(FLEET)
    state, record = this_build.export_sign_state(), this_build.export_battery_basis()
    assert record["fleet_inverted"] is False

    reader = _reader(flip=True, brand="goodwe")
    reader.restore_sign_state(_older_build_writes(state), basis=record)
    assert reader.read_power().battery_power == pytest.approx(shown)
    assert not reader._battery_sign_detected.get(FLEET)


def test_the_record_waits_with_the_move():
    """While an older store's lock still waits to be moved, nothing of it is
    this build's: no record is saved, so a restart still moves it."""
    reader = _reader()
    reader.restore_sign_state({"battery_detected": {FLEET: True},
                               "battery_inverted": {FLEET: True}})
    assert reader.export_battery_basis() is None
    reader.read_power()
    assert reader.export_battery_basis() == {
        "fleet_locked": True, "fleet_inverted": False, "user_flip": False}


def test_the_record_follows_a_reset_and_a_new_store():
    reader = _reader(flip=True)
    assert reader.export_battery_basis() == {
        "fleet_locked": False, "fleet_inverted": False, "user_flip": True}
    reader.restore_sign_state({"battery_detected": {FLEET: True},
                               "battery_inverted": {FLEET: True},
                               "battery_basis": "sensor"})
    assert reader.export_battery_basis()["fleet_inverted"] is True
    reader.reset_sign_state()
    assert reader.export_battery_basis()["fleet_locked"] is False


# ── A home without an Energy Dashboard ─────────────────────────────────────

@pytest.mark.parametrize("pick", [None, "sensor.batt1_power"])
@pytest.mark.parametrize("flip", [False, True])
def test_a_home_without_a_dashboard_saves_the_mark(flip, pick):
    """No build flipped a read without a dashboard: with no fleet lock the
    first read settles the move, so the mark is saved and the record written."""
    reader = _reader(dashboard=False, battery_pick=pick, flip=flip)
    reader.restore_sign_state({"battery_detected": {}, "battery_inverted": {}})
    assert "battery_basis" not in reader.export_sign_state()
    reader.read_power()
    assert reader.export_sign_state()["battery_basis"] == "sensor"
    assert reader.export_battery_basis()["user_flip"] is flip


def test_a_flip_set_without_a_dashboard_stays_a_flip_when_one_is_added():
    """The second report: "Fix battery sign" set on a home without a
    dashboard, then a one-battery Inverted dashboard added while SEM runs.
    The flip judged the sensor as it is; no lock is made against it."""
    reader = _reader(dashboard=False, flip=True)
    reader.restore_sign_state({"battery_detected": {}, "battery_inverted": {}})
    reader.read_power()
    reader.set_energy_dashboard_config(_ed())
    assert reader.read_power().battery_power == pytest.approx(-1200.0)
    assert not reader._battery_sign_detected.get(FLEET)


@pytest.mark.parametrize("lock", [False, True])
def test_a_lock_restored_without_a_dashboard_waits_for_one(lock):
    """No build learns a fleet lock without a dashboard, so a saved one came
    from an older build's dashboard read, maybe the flipped one. It waits
    for the next dashboard read and is moved there, as #1194 does."""
    reader = _reader(dashboard=False)
    reader.restore_sign_state({"battery_detected": {FLEET: True},
                               "battery_inverted": {FLEET: lock}})
    reader.read_power()
    assert reader._battery_sign_inverted[FLEET] is lock
    assert "battery_basis" not in reader.export_sign_state()
    assert reader.export_battery_basis() is None
    reader.set_energy_dashboard_config(_ed())
    reader.read_power()
    assert reader._battery_sign_inverted[FLEET] is (not lock)
    assert reader.export_sign_state()["battery_basis"] == "sensor"


def test_a_dashboard_sem_could_not_read_settles_nothing():
    """No answer: the dashboard may be the one the older build read, so the
    move waits for the read that has it."""
    reader = _reader(dashboard=False, answered=False, flip=True)
    reader.restore_sign_state({"battery_detected": {}, "battery_inverted": {}})
    reader.read_power()
    assert "battery_basis" not in reader.export_sign_state()
    assert reader.export_battery_basis() is None
    # the dashboard read: the flip judged the flipped value, as #1194 says
    reader.set_energy_dashboard_config(_ed())
    reader.read_power()
    assert reader._battery_sign_detected[FLEET] is True


def test_a_reader_never_told_settles_nothing_without_a_dashboard():
    hass = MagicMock()
    hass.states.get = lambda eid: None
    reader = SensorReader(hass, {})
    reader.restore_sign_state({"battery_detected": {FLEET: True},
                               "battery_inverted": {FLEET: True}})
    reader.read_power()
    assert reader.export_battery_basis() is None


# ── The store keeps the record where an older build keeps it ───────────────

def test_the_record_is_a_store_key_of_its_own():
    from custom_components.solar_energy_management.coordinator.storage import (
        SEMStorage,
    )
    storage = SEMStorage.__new__(SEMStorage)
    storage._energy_data = {}
    assert storage.get_battery_sign_basis() is None
    record = {"fleet_locked": True, "fleet_inverted": False, "user_flip": False}
    storage.set_sign_state({"battery_basis": "sensor"})
    storage.set_battery_sign_basis(record)
    assert storage._energy_data["battery_sign_basis"] == record
    assert "battery_sign_basis" not in storage._energy_data["sign_state"]
    # an older build: it writes sign_state again, the rest stays
    storage._energy_data["sign_state"] = {"battery_detected": {}}
    assert storage.get_battery_sign_basis() == record


# ── The real integration ───────────────────────────────────────────────────

_needs_real_hass = pytest.mark.skipif(
    not _HAS_REAL_HA,
    reason="pytest-homeassistant-custom-component not installed; CI runs these")


@_needs_real_hass
@pytest.mark.asyncio
@pytest.mark.parametrize("with_record", [True, False])
async def test_the_coordinator_saves_the_record_and_starts_from_it(
    sem_real_hass, sem_config_entry, hass_storage, with_record,
) -> None:
    """Setup reads the record beside ``sign_state``; a save writes it."""
    from homeassistant.components.energy.data import async_get_manager

    from custom_components.solar_energy_management.const import DOMAIN

    hass = sem_real_hass
    hass.config.components.add("energy")
    manager = await async_get_manager(hass)
    await manager.async_update({"energy_sources": [dict(SOLAR), dict(GRID),
                                                   dict(INVERTED)],
                                "device_consumption": []})
    for eid, value in (("sensor.pv_power", "3000"), ("sensor.grid_power", "0"),
                       ("sensor.batt1_power", "1200"),
                       ("sensor.batt1_power_inverted", "-1200")):
        hass.states.async_set(eid, value, {"unit_of_measurement": "W"})

    entry = sem_config_entry
    entry.add_to_hass(hass)
    # the battery as the dashboard has it, not SEM's own pick
    hass.config_entries.async_update_entry(entry, data={
        k: v for k, v in entry.data.items() if k != "battery_power_sensor"})
    key = f"{DOMAIN}_{entry.entry_id}_energy"
    saved = {"sign_state": {"grid_detected": False, "grid_inverted": False,
                            "battery_detected": {FLEET: True},
                            "battery_inverted": {FLEET: False}}}
    if with_record:
        saved["battery_sign_basis"] = {"fleet_locked": True,
                                       "fleet_inverted": False,
                                       "user_flip": False}
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key,
                         "data": saved}

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    reader = coordinator._sensor_reader
    assert reader._energy_dashboard_config is not None
    assert reader._energy_dashboard_config.battery_power_inverted is True

    # with the record the lock is this build's; without, it is moved (#1194)
    assert reader._battery_sign_inverted[FLEET] is (not with_record)

    await coordinator._storage.async_save_energy_now()
    data = hass_storage[key]["data"]
    assert data["sign_state"]["battery_basis"] == "sensor"
    assert data["battery_sign_basis"] == {
        "fleet_locked": True, "fleet_inverted": not with_record,
        "user_flip": False}
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@_needs_real_hass
@pytest.mark.asyncio
async def test_the_coordinator_settles_a_home_without_a_dashboard(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """No Energy Dashboard, and HA says so: the first read settles the move,
    the flip stays a flip, and the mark is saved."""
    from custom_components.solar_energy_management.const import DOMAIN

    hass = sem_real_hass
    entry = sem_config_entry
    key = f"{DOMAIN}_{entry.entry_id}_energy"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {
        "sign_state": {"grid_detected": False, "grid_inverted": False,
                       "battery_detected": {}, "battery_inverted": {}}}}
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "battery_sign_user_flip": True})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator._sensor_reader._energy_dashboard_config is None
    assert coordinator._ed_answered is True

    await coordinator._storage.async_save_energy_now()
    data = hass_storage[key]["data"]
    assert data["sign_state"]["battery_basis"] == "sensor"
    assert not data["sign_state"]["battery_detected"].get(FLEET)
    assert data["battery_sign_basis"] == {
        "fleet_locked": False, "fleet_inverted": False, "user_flip": True}
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@_needs_real_hass
@pytest.mark.asyncio
async def test_reset_sign_detection_writes_the_record_at_once(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """Reset writes its state to the file at once (#1209); the record beside
    it goes with it, so the file never pairs a reset with the old lock."""
    from custom_components.solar_energy_management.const import DOMAIN

    hass = sem_real_hass
    entry = sem_config_entry
    key = f"{DOMAIN}_{entry.entry_id}_energy"
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    reader = coordinator._sensor_reader
    reader._battery_sign_detected[FLEET] = True
    reader._battery_sign_inverted[FLEET] = True
    coordinator._storage.set_battery_sign_basis(reader.export_battery_basis())
    await coordinator._storage.async_save_energy_now()
    assert hass_storage[key]["data"]["battery_sign_basis"]["fleet_locked"] is True

    await hass.services.async_call(DOMAIN, "reset_sign_detection", {}, blocking=True)
    assert entry.runtime_data is coordinator          # no flip: no reload
    data = hass_storage[key]["data"]
    assert data["sign_state"] == {}
    assert data["battery_sign_basis"] == {
        "fleet_locked": False, "fleet_inverted": False, "user_flip": False}
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
