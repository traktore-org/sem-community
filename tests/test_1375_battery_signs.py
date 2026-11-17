"""#1375 — one "Battery direction is wrong" tap turned over EVERY battery.

@BerndWilli60's home (the one of #1373): b1 a SolarEdge battery whose power
sensor reads + while it DISCHARGES (SEM's lock for it is "negate", right),
b2 a Zendure read as a pair of power sensors (charge into the pack, discharge
out of it: its direction is declared, not guessed). He pressed the button for
one battery; ``battery_sign_user_flip`` then negated both, so b1 read
charging while its discharge counter rose and b2 discharging while its charge
counter rose, and the house load went below zero.

Now the tap names one battery (saved as its power sensor), a two-sensor
battery is never turned over on a home of several, and an old one-for-all
flag names no battery on a home of several. A one-battery home reads as
before.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

from .test_1373_own_battery_soc import (
    EDGE_COUNTERS, EDGE_POWER, FLOW_FROM, FLOW_TO, _W, _KWH,
    _device, _edge, _edge_src, _ed, _entity, _flow, _flow_src, _read, _reader,
)

HUAWEI = "sensor.battery_1_lade_entladeleistung"
LEGACY = {"battery_sign_user_flip": True}
NAMED_B1 = {"battery_sign_user_flip_sensors": [EDGE_POWER]}


def _two_batteries(hass, *, edge_w=472, charge_w=256, discharge_w=0, **config):
    """The reporter's home, b1 locked "negate" as SEM learned it. The pair
    reads charge_w into the pack and discharge_w out of it."""
    _edge(hass)
    _flow(hass)
    hass.states.async_set(EDGE_POWER, str(edge_w), _W)
    hass.states.async_set(FLOW_TO, str(charge_w), _W)
    hass.states.async_set(FLOW_FROM, str(discharge_w), _W)
    r = _reader(hass, _ed(hass, _edge_src(), _flow_src()), **config)
    r._battery_sign_detected["b1"] = True
    r._battery_sign_inverted["b1"] = True
    r._battery_brand_seed_done["b1"] = True
    r._battery_lock_sensors = {"b1": EDGE_POWER}
    return r


def _one_battery(hass, entity, raw, *, locked_negate=None, **config):
    for counter in EDGE_COUNTERS:
        hass.states.async_set(counter, "100", _KWH)
    hass.states.async_set(entity, str(raw), _W)
    src = {"type": "battery", "stat_energy_to": EDGE_COUNTERS[0],
           "stat_energy_from": EDGE_COUNTERS[1], "stat_rate": entity}
    r = _reader(hass, _ed(hass, src), **config)
    if locked_negate is not None:
        r._battery_sign_detected[r._FLEET_BID] = True
        r._battery_sign_inverted[r._FLEET_BID] = locked_negate
        r._battery_brand_seed_done[r._FLEET_BID] = True
        r._battery_lock_sensors = {r._FLEET_BID: entity}
    return r


# ── 1. the reporter's home ──────────────────────────────────────────────


async def test_the_old_global_flag_no_longer_turns_both_over(hass):
    """Before: b1 +472 (reads charging, its discharge counter rises) and
    b2 −256 (reads discharging, its charge counter rises). Now the pair reads
    its declared direction at once; b1 keeps what it read until its own
    counters vote, then follows them."""
    r = _two_batteries(hass, **LEGACY)
    out = _read(r, 1)
    assert out.batteries["b2"].power_w == pytest.approx(256)     # charging
    assert out.batteries["b1"].power_w == pytest.approx(472)     # as before
    for n in range(8):                       # b1's discharge counter rises
        hass.states.async_set(EDGE_COUNTERS[1], str(100 + 0.1 * (n + 1)), _KWH)
        out = _read(r, 1)
    assert out.batteries["b1"].power_w == pytest.approx(-472)    # discharging
    assert out.batteries["b2"].power_w == pytest.approx(256)
    assert out.battery_power == pytest.approx(-216)
    assert out.home_consumption_power >= 0


async def test_no_flag_reads_the_same(hass):
    out = _read(_two_batteries(hass))
    assert out.batteries["b1"].power_w == pytest.approx(-472)
    assert out.batteries["b2"].power_w == pytest.approx(256)


async def test_the_named_battery_is_the_one_turned_over(hass):
    out = _read(_two_batteries(hass, **NAMED_B1))
    assert out.batteries["b1"].power_w == pytest.approx(472)
    assert out.batteries["b2"].power_w == pytest.approx(256)
    assert out.battery_power == pytest.approx(728)


async def test_a_pair_is_never_turned_over(hass):
    """Named by either of its sensors, or by both: still as declared."""
    both = {"battery_sign_user_flip_sensors": [FLOW_TO, FLOW_FROM]}
    out = _read(_two_batteries(hass, **both))
    assert out.batteries["b2"].power_w == pytest.approx(256)
    assert out.batteries["b1"].power_w == pytest.approx(-472)
    out = _read(_two_batteries(hass, discharge_w=300, charge_w=0, **both))
    assert out.batteries["b2"].power_w == pytest.approx(-300)


async def test_a_flip_for_a_battery_no_longer_there_does_nothing(hass):
    gone = {"battery_sign_user_flip_sensors": ["sensor.removed_battery"]}
    out = _read(_two_batteries(hass, **gone))
    assert out.batteries["b1"].power_w == pytest.approx(-472)
    assert out.batteries["b2"].power_w == pytest.approx(256)


async def test_the_old_flag_does_not_hold_the_counter_check(hass):
    """While a flip is on, saved signs wait to be judged again (#1193). The
    old flag names no battery on a home of several, so nothing waits."""
    r = _two_batteries(hass, **LEGACY)
    assert r._battery_flip_on(2) is False
    assert r._battery_flip_on(1) is True
    assert _two_batteries(hass, **NAMED_B1)._battery_flip_on(2) is True


async def test_a_dark_cycle_does_not_turn_the_total_over(hass):
    """One battery not read this cycle: the read is the one-battery path.
    Neither an old flag nor a named battery turns that total over."""
    for cfg in (LEGACY, NAMED_B1):
        r = _two_batteries(hass, **cfg)
        hass.states.async_set(EDGE_POWER, "unavailable", _W)
        out = _read(r)
        assert out.battery_power >= 0, cfg


# ── 2. one battery: nothing changes ─────────────────────────────────────


@pytest.mark.parametrize("flip,expected", [(False, 800), (True, -800)])
async def test_a_huawei_battery_reads_as_before(hass, flip, expected):
    """The owner's home: one battery, + charging. The old flag still means
    that battery."""
    cfg = {"battery_sign_user_flip": True} if flip else {}
    r = _one_battery(hass, HUAWEI, 800, **cfg)
    assert _read(r).battery_power == pytest.approx(expected)


@pytest.mark.parametrize("flip,expected", [(False, -472), (True, 472)])
async def test_a_solaredge_battery_reads_as_before(hass, flip, expected):
    cfg = {"battery_sign_user_flip": True} if flip else {}
    r = _one_battery(hass, EDGE_POWER, 472, locked_negate=True, **cfg)
    assert _read(r).battery_power == pytest.approx(expected)


async def test_a_list_left_from_two_batteries_does_not_turn_one_over(hass):
    r = _one_battery(hass, HUAWEI, 800, **NAMED_B1)
    assert _read(r).battery_power == pytest.approx(800)


async def test_one_pair_keeps_the_old_flip(hass):
    """Unchanged since #1215: with ONE battery the tap reads as it did."""
    _flow(hass)
    hass.states.async_set(FLOW_TO, "1200", _W)
    hass.states.async_set(FLOW_FROM, "0", _W)
    r = _reader(hass, _ed(hass, _flow_src()), **LEGACY)
    assert _read(r).battery_power == pytest.approx(-1200)


# ── 3. the dashboard tap names the battery ──────────────────────────────


async def _press(options, reader, data):
    from custom_components.solar_energy_management import (
        _async_register_phase_services,
    )
    hass = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    await _async_register_phase_services(hass, MagicMock())
    handlers = {c.args[1]: c.args[2]
                for c in hass.services.async_register.call_args_list}
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = dict(options)
    entry.runtime_data = MagicMock()
    entry.runtime_data._sensor_reader = reader
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_reload = AsyncMock()
    saved = {}
    hass.config_entries.async_update_entry = (
        lambda e, options: saved.update(options=options))
    call = MagicMock()
    call.data = data
    result = await handlers["flip_battery_sign"](call)
    return result, saved.get("options")


async def test_with_several_batteries_the_tap_asks_which(hass):
    r = _two_batteries(hass)
    result, saved = await _press(LEGACY, r, {})
    assert result["ok"] is False and result["error"] == "battery_needed"
    assert [b["sensor"] for b in result["batteries"]] == [EDGE_POWER]
    assert saved is None                          # nothing was changed


async def test_the_tap_flips_the_named_battery_and_drops_the_old_flag(hass):
    r = _two_batteries(hass)
    result, saved = await _press(LEGACY, r, {"battery": EDGE_POWER})
    assert result["ok"] is True and result["user_flip"] is True
    assert saved["battery_sign_user_flip_sensors"] == [EDGE_POWER]
    assert saved["battery_sign_user_flip"] is False


async def test_a_second_tap_on_the_same_battery_flips_it_back(hass):
    r = _two_batteries(hass)
    result, saved = await _press(NAMED_B1, r, {"battery": EDGE_POWER})
    assert result["user_flip"] is False
    assert saved["battery_sign_user_flip_sensors"] == []


async def test_the_tap_refuses_a_two_sensor_battery(hass):
    r = _two_batteries(hass)
    result, saved = await _press({}, r, {"battery": FLOW_TO})
    assert result["ok"] is False and result["error"] == "not_flippable"
    assert saved is None


async def test_with_one_battery_the_tap_needs_no_name(hass):
    r = _one_battery(hass, HUAWEI, 800)
    result, saved = await _press({}, r, {})
    assert result["ok"] is True
    assert saved["battery_sign_user_flip"] is True
    assert "battery_sign_user_flip_sensors" not in saved


def test_the_diagnostics_redact_the_named_batteries():
    from custom_components.solar_energy_management.diagnostics import (
        REDACT_BATTERY_SIGN_KEYS, REDACT_CONFIG_KEYS,
    )
    assert "user_flip_sensors" in REDACT_BATTERY_SIGN_KEYS
    assert "battery_sign_user_flip_sensors" in REDACT_CONFIG_KEYS


# ── 4. a SOC named like one, with no unit (the #1373 review) ────────────


def _soc_home(hass, extra=()):
    entry, dev = _device(hass, "lone_pack")
    _entity(hass, entry, dev, "sensor.lone_pack_power", _W, 0)
    for eid, attrs, value in extra:
        _entity(hass, entry, dev, eid, attrs, value)
    return SensorReader(hass, {"update_interval": 10})


async def test_a_bare_soc_name_is_found_last(hass):
    r = _soc_home(hass, [("sensor.lone_pack_soc_value", {}, 47)])
    assert r._auto_detect_battery_soc("sensor.lone_pack_power") == (
        "sensor.lone_pack_soc_value")
    assert r._soc_candidate_exists("sensor.lone_pack_power") is True


async def test_a_percent_soc_beats_a_bare_one(hass):
    pct = {"unit_of_measurement": "%"}
    r = _soc_home(hass, [("sensor.lone_pack_soc_value", {}, 47),
                         ("sensor.lone_pack_soc_pct", pct, 52)])
    assert r._auto_detect_battery_soc("sensor.lone_pack_power") == (
        "sensor.lone_pack_soc_pct")


async def test_a_bare_soc_setting_or_code_stays_out(hass):
    """The #1373 cases: a code reads 0, a setting is not the level."""
    r = _soc_home(hass, [("sensor.lone_pack_soc_status", {}, 0),
                         ("sensor.lone_pack_soc_limit", {}, 10),
                         ("sensor.lone_pack_min_soc", {}, 10)])
    assert r._auto_detect_battery_soc("sensor.lone_pack_power") is None
    assert r._soc_candidate_exists("sensor.lone_pack_power") is False


async def test_a_bare_soc_name_is_not_taken_for_one_of_a_fleet(hass):
    _edge(hass)
    _flow(hass)
    entry, dev = _device(hass, "seu25")
    _entity(hass, entry, dev, "sensor.seu25_soc_value", {}, 47)
    ed = _ed(hass, _edge_src(soc=None), _flow_src())
    r = _reader(hass, ed)
    assert r._auto_detect_battery_soc(EDGE_POWER) != "sensor.seu25_soc_value"


# ── 5. review: migration, stale flag, renamed sensor, whole-word SOC ────


def _home(config, inverted, **w):
    """Both batteries DISCHARGE 1500 W (a shows +1500, b shows -1500, so a
    needs "negate" and b does not) unless ``w`` sets a sensor's watts. The
    saved locks are ``inverted`` (a, b)."""
    from .test_1205_sign_follows_its_battery import _Home, _w
    store = {"battery_detected": {"b1": True, "b2": True},
             "battery_inverted": {"b1": inverted[0], "b2": inverted[1]},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_learned_on": {"b1": "sensor.a_power",
                                    "b2": "sensor.b_power"}}
    home = _Home(["a", "b"], store=store, config=config)
    for name, watts in w.items():
        home.states[f"sensor.{name}_power"] = _w(watts)
    return home


def _watts(home, cycles):
    out = []
    for _ in range(cycles):
        p = home.cycle()
        out.append((p.batteries["b1"].power_w, p.batteries["b2"].power_w))
    return out


def test_the_migration_changes_no_battery_in_any_cycle(caplog):
    """Locks wrong the way round, flag on: develop read (-1500, -1500) every
    cycle (right). So does this build, from the first cycle, and the
    counters then confirm it."""
    caplog.set_level("INFO")
    home = _home(dict(LEGACY), (False, True))
    assert _watts(home, 8) == [(-1500, -1500)] * 8
    assert home.signs() == {"b1": True, "b2": False}
    said = [r.getMessage() for r in caplog.records if "#1375" in r.getMessage()]
    assert len(said) == 1 and "judged again" in said[0]


def test_a_sign_the_counters_contradict_is_kept_then_follows_them():
    """Locks right, flag on: develop read (+1500, +1500), wrong. This build
    reads that too until the counters vote (the baseline cycle and 3 votes:
    4 cycles, about 40 s), then follows them."""
    home = _home(dict(LEGACY), (True, False))
    cycles = _watts(home, 8)
    assert cycles[:3] == [(1500, 1500)] * 3
    assert cycles[3:] == [(-1500, -1500)] * 5
    assert home.signs() == {"b1": True, "b2": False}


def test_an_idle_battery_keeps_what_it_read_over_50_cycles():
    """Under 100 W nothing votes: before the update a read -50, so it reads
    -50 for good, never the opposite."""
    home = _home(dict(LEGACY), (False, True), a=50, b=-50)
    assert set(_watts(home, 50)) == {(-50, -50)}


def test_a_pair_reads_its_declared_direction_from_the_first_cycle():
    from .test_1205_sign_follows_its_battery import _Home, _w
    home = _Home(["a"], pair=True, config=dict(LEGACY))
    home.states["sensor.verto_discharge_power"] = _w(300)
    home.states["sensor.verto_charge_power"] = _w(0)
    for _ in range(6):
        out = home.cycle()
        assert out.batteries["b2"].power_w == pytest.approx(-300)
        assert out.batteries["b1"].power_w == pytest.approx(-1500)  # as before


def test_the_migration_runs_once_and_not_with_a_list_or_one_battery():
    home = _home(dict(LEGACY), (False, True))
    home.cycle()
    home.reader.legacy_flip_cleared = False
    home.cycle(3)
    assert home.reader.legacy_flip_cleared is False
    listed = _home({**LEGACY, **NAMED_B1}, (False, True))
    listed.cycle()
    assert listed.reader.legacy_flip_cleared is False
    assert listed.reader._raw_config["battery_sign_user_flip"] is True


async def test_one_battery_keeps_its_old_flag_untouched(hass):
    r = _one_battery(hass, HUAWEI, 800, **LEGACY)
    assert _read(r).battery_power == pytest.approx(-800)
    assert r.legacy_flip_cleared is False
    assert r._raw_config["battery_sign_user_flip"] is True


def _fake_coordinator(saved=True):
    fake = MagicMock()
    fake._storage.async_save_energy_now = AsyncMock(return_value=saved)
    return fake


async def test_the_coordinator_saves_the_cleared_flag_once_without_a_reload():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    fake = _fake_coordinator()
    fake._sensor_reader.legacy_flip_cleared = True
    fake._sensor_reader._raw_config = {"battery_sign_user_flip": True}
    fake.config_entry.options = {"battery_sign_user_flip": True, "x": 1}
    await SEMCoordinator._save_cleared_battery_flip(fake)
    saved = fake.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert saved == {"battery_sign_user_flip": False,
                     "battery_sign_user_flip_sensors": [], "x": 1}
    assert fake._skip_options_reload == saved
    assert fake._sensor_reader.legacy_flip_cleared is False
    assert fake._sensor_reader._raw_config == {
        "battery_sign_user_flip": False, "battery_sign_user_flip_sensors": []}
    fake.hass.config_entries.async_update_entry.reset_mock()
    await SEMCoordinator._save_cleared_battery_flip(fake)
    fake.hass.config_entries.async_update_entry.assert_not_called()


async def test_no_entry_to_write_keeps_the_flag_and_the_request():
    """(#1375) Cleared in memory only once saved: with no entry the request
    stays and the flag is not touched (the migration runs once a start)."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    fake = _fake_coordinator()
    fake.config_entry = None
    fake._sensor_reader.legacy_flip_cleared = True
    fake._sensor_reader._raw_config = {"battery_sign_user_flip": True}
    await SEMCoordinator._save_cleared_battery_flip(fake)
    assert fake._sensor_reader.legacy_flip_cleared is True
    assert fake._sensor_reader._raw_config == {"battery_sign_user_flip": True}


def test_the_migration_runs_once_a_start_though_the_flag_stays():
    home = _home(dict(LEGACY), (False, True))
    home.cycle()
    assert home.reader.legacy_flip_cleared is True
    home.reader.legacy_flip_cleared = False           # nothing wrote it
    home.cycle(3)
    assert home.reader.legacy_flip_cleared is False
    assert home.reader._raw_config["battery_sign_user_flip"] is True


@pytest.mark.parametrize("named,expected", [
    ([HUAWEI], -800), (["sensor.removed_battery"], 800)])
async def test_a_named_battery_that_is_the_one_left_still_flips(
        hass, named, expected):
    """b2 was flipped on two batteries, b1 removed: the list applies to the
    battery left when it names it, and to no other."""
    r = _one_battery(hass, HUAWEI, 800, battery_sign_user_flip_sensors=named)
    assert _read(r).battery_power == pytest.approx(expected)


async def test_the_tap_on_the_battery_left_turns_its_old_flip_off(hass):
    r = _one_battery(hass, HUAWEI, 800)
    opts = {"battery_sign_user_flip": False,
            "battery_sign_user_flip_sensors": [HUAWEI]}
    result, saved = await _press(opts, r, {})
    assert result["user_flip"] is False
    assert saved["battery_sign_user_flip_sensors"] == []
    assert saved["battery_sign_user_flip"] is False


async def test_a_renamed_sensor_in_the_list_does_not_hold_the_check(hass):
    gone = ["sensor.renamed_away"]
    r = _two_batteries(hass, battery_sign_user_flip_sensors=gone)
    ed = r._energy_dashboard_config
    assert r._battery_flip_on(2, ed) is False
    assert _read(r).batteries["b1"].power_w == pytest.approx(-472)
    live = _two_batteries(hass, battery_sign_user_flip_sensors=[EDGE_POWER])
    assert live._battery_flip_on(2, live._energy_dashboard_config) is True


@pytest.mark.parametrize("name", [
    "plug_socket_temperature", "pack_soc_state", "pack_soc_type",
    "pack_socle_value", "pack_status_soc"])
async def test_a_bare_name_must_hold_soc_as_a_word(hass, name):
    r = _soc_home(hass, [(f"sensor.{name}", {}, 47)])
    assert r._auto_detect_battery_soc("sensor.lone_pack_power") is None
    assert r._soc_candidate_exists("sensor.lone_pack_power") is False


@pytest.mark.parametrize("name", [
    "lone_pack_soc", "lone_pack_battery_soc_value", "lone_pack_state_of_charge"])
async def test_a_bare_name_with_the_word_is_found(hass, name):
    r = _soc_home(hass, [(f"sensor.{name}", {}, 47)])
    assert r._auto_detect_battery_soc("sensor.lone_pack_power") == f"sensor.{name}"


# ── 6. a restart before the options write landed ────────────────────────


def _restart(store, config):
    """A new run restored from the saved sign store, as after a restart."""
    from .test_1205_sign_follows_its_battery import _Home
    return _Home(["a", "b"], store=store, config=config)


def test_a_restart_before_the_write_does_not_turn_the_signs_over_twice():
    """Run 1 migrates and saves its sign store; the options write never
    lands, so run 2 starts with the old flag still on. It must read what run
    1 read in every cycle (develop: -1500 throughout), and run 3, after the
    write landed, the same."""
    run1 = _home(dict(LEGACY), (False, True))
    first = _watts(run1, 6)
    assert first == [(-1500, -1500)] * 6
    store = run1.reader.export_sign_state()
    assert store["legacy_flip_migrated"] is True
    run2 = _restart(store, dict(LEGACY))                 # flag still on
    assert _watts(run2, 8) == first[:1] * 8
    assert run2.reader.legacy_flip_cleared is False
    store2 = run2.reader.export_sign_state()
    run3 = _restart(store2, {"battery_sign_user_flip": False,
                             "battery_sign_user_flip_sensors": []})
    assert _watts(run3, 8) == first[:1] * 8


def test_the_marker_goes_with_a_reset_and_a_damaged_store_is_ignored():
    home = _home(dict(LEGACY), (False, True))
    home.cycle()
    assert home.reader.export_sign_state()["legacy_flip_migrated"] is True
    home.reader.reset_sign_state()
    assert "legacy_flip_migrated" not in home.reader.export_sign_state()
    home.reader.restore_sign_state({"legacy_flip_migrated": "yes"})
    assert "legacy_flip_migrated" not in home.reader.export_sign_state()


async def test_a_failed_options_write_leaves_the_flag_and_asks_again(caplog):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    fake = _fake_coordinator()
    fake._sensor_reader.legacy_flip_cleared = True
    fake._sensor_reader._raw_config = {"battery_sign_user_flip": True}
    fake.config_entry.options = {}
    fake.hass.config_entries.async_update_entry.side_effect = RuntimeError("x")
    fake._flip_save_failed_said = False
    await SEMCoordinator._save_cleared_battery_flip(fake)          # does not raise
    assert fake._sensor_reader.legacy_flip_cleared is True
    assert fake._sensor_reader._raw_config == {"battery_sign_user_flip": True}
    assert fake._skip_options_reload is None


# ── 7. the store first, the flag after ──────────────────────────────────


async def test_the_flag_is_cleared_only_after_the_sign_store_is_saved():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    order = []
    fake = _fake_coordinator()
    fake._storage.set_sign_state.side_effect = lambda st: order.append("state")
    fake._storage.async_save_energy_now = AsyncMock(
        side_effect=lambda: order.append("saved") or True)
    fake.hass.config_entries.async_update_entry.side_effect = (
        lambda *a, **k: order.append("options"))
    fake._sensor_reader.legacy_flip_cleared = True
    fake._sensor_reader._raw_config = {"battery_sign_user_flip": True}
    fake.config_entry.options = {}
    await SEMCoordinator._save_cleared_battery_flip(fake)
    assert order == ["state", "saved", "options"]


async def test_a_store_that_did_not_save_leaves_the_flag_and_retries():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    fake = _fake_coordinator(saved=False)
    fake._sensor_reader.legacy_flip_cleared = True
    fake._sensor_reader._raw_config = {"battery_sign_user_flip": True}
    fake.config_entry.options = {}
    await SEMCoordinator._save_cleared_battery_flip(fake)
    fake.hass.config_entries.async_update_entry.assert_not_called()
    assert fake._sensor_reader.legacy_flip_cleared is True
    assert fake._sensor_reader._raw_config == {"battery_sign_user_flip": True}


def test_a_restart_before_the_store_was_saved_migrates_once_and_reads_the_same():
    """Run 1 migrated in memory; the store holding it never reached the disk
    and the flag is still set. Run 2 restores the OLD locks and migrates
    them once: it reads what run 1 read in every cycle."""
    run1 = _home(dict(LEGACY), (False, True))
    first = _watts(run1, 6)
    old_store = {"battery_detected": {"b1": True, "b2": True},
                 "battery_inverted": {"b1": False, "b2": True},
                 "battery_basis": "sensor", "battery_counters": "own",
                 "battery_learned_on": {"b1": "sensor.a_power",
                                        "b2": "sensor.b_power"}}
    run2 = _restart(old_store, dict(LEGACY))
    assert _watts(run2, 6) == first
    assert run2.reader.legacy_flip_cleared is True
