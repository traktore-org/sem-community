"""#1140 — a Repair outlives the thing it is about.

Change the grid sensor, and the old sensor's "unavailable" Repair stayed in
Settings for good. Five Repairs had this shape: ``sensor_unavailable``,
``sensor_stale``, ``battery_control_write_not_taken``,
``battery_force_discharge_unsupported`` and ``charger_actuation_failed`` —
and the two non-persistent battery watches beside them, which an options
reload keeps too. Each is cleared only by the check that raised it, and that
check runs only for what SEM still reads, writes or drives.

Bug class 84 (left open (2)), the rest of #1139: a Repair keyed on what the
config no longer holds. A sensor Repair's owner is the reader, and only the
reader knows what it reads (the Energy Dashboard picks are found at run
time), so the sweep runs in the cycle, once a full window of reads is in.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import CoreState
from homeassistant.helpers import issue_registry as ir

from custom_components.solar_energy_management.charger_refs import REFS_KEY
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.coordinator import (
    repair_issues as ri,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)

REPAIR_ISSUES_PY = (
    Path(__file__).resolve().parent.parent / "coordinator" / "repair_issues.py")
MONO = "time.monotonic"


def _ids(hass):
    return {i for (d, i) in ir.async_get(hass).issues if d == DOMAIN}


#: Every Repair keyed on one thing (an entity, a device, a contact) → what
#: clears it once that thing leaves SEM. A new keyed Repair must answer.
KEYED = {
    "raise_sensor_unavailable": "#1140 sweep: the entities the reader reads",
    "raise_sensor_stale": "#1140 sweep: the entities the reader reads",
    "raise_battery_control_write_not_taken":
        "#1140 sweep: the battery entities the config names",
    "raise_battery_force_discharge_unsupported":
        "#1140 sweep: the battery entities the config names",
    "raise_battery_operating_mode_unexpected":
        "#1140 sweep: the battery entities the config names (non-persistent, "
        "but an options reload keeps it)",
    "raise_deye_system_work_mode_invalid":
        "#1140 sweep: the battery entities the config names (non-persistent, "
        "but an options reload keeps it)",
    "raise_charger_actuation_failed":
        "#1140 sweep: the devices SEM drives — chargers and loads",
    "raise_charger_failsafe_suspected": "#1139 setup sweep: the chargers",
    "raise_charger_stop_unenforceable": "#1139 setup sweep: the chargers",
    "raise_charger_stop_war_stand_down": "#1139 setup sweep: the chargers",
    "raise_charger_phase_count_mismatch": "#1139 setup sweep: the chargers",
    "raise_soc_cap_unenforceable": "#1139 setup sweep: the chargers",
    "raise_charger_control_entity_broken":
        "#1139 setup sweep: the (charger, entity) pairs",
    "raise_heat_pump_relay_unavailable":
        "clear_orphan_heat_pump_relay_repairs, once per coordinator (#448)",
    "raise_hot_water_entity_unavailable":
        "clear_orphan_hot_water_repairs, once per coordinator (#454)",
    "raise_hot_water_temperature_sensor_unavailable":
        "clear_orphan_hot_water_repairs, once per coordinator (#454)",
    "raise_external_write_seen":
        "keyed on the device (charger:<id> or battery); every known device is "
        "cleared each cycle its writes stop or its mode is not observe "
        "(#1079), and a restart drops the non-persistent Repair",
    "raise_power_sensor_not_found":
        "keyed on the fixed source (grid/solar/battery); each is cleared the "
        "cycle the dashboard read finds its sensor or stops counting it "
        "(#1188), and a restart drops the non-persistent Repair",
    "raise_unseen_power_row":
        "keyed on the fixed kind (solar/battery); cleared on a reader's "
        "first look and every cycle nothing is left alone (#1236), and a "
        "restart drops the non-persistent Repair",
    "raise_heat_pump_contact_values_missing":
        "keyed on the fixed slot (relay1/relay2), and both slots are cleared "
        "every cycle their contact is complete or gone (#801)",
}

#: How each #1140 Repair is filed — the REAL raisers — and which owner keeps
#: it: the id the sweep must match is the one production files.
RAISE = {
    "raise_sensor_unavailable": ("read", lambda h, x: (
        ri.raise_sensor_unavailable(h, x, minutes_unavailable=10))),
    "raise_sensor_stale": ("read", lambda h, x: (
        ri.raise_sensor_stale(h, x, minutes_stale=12))),
    "raise_battery_control_write_not_taken": ("battery", lambda h, x: (
        ri.raise_battery_control_write_not_taken(
            h, entity_id=x, wanted="1 W", seen="0 W", strikes=3))),
    "raise_battery_force_discharge_unsupported": ("battery", lambda h, x: (
        ri.raise_battery_force_discharge_unsupported(h, x, error="e"))),
    "raise_battery_operating_mode_unexpected": ("battery", lambda h, x: (
        ri.raise_battery_operating_mode_unexpected(
            h, x, mode="fully_fed_to_grid", expected="self"))),
    "raise_deye_system_work_mode_invalid": ("battery", lambda h, x: (
        ri.raise_deye_system_work_mode_invalid(h, x, reason="r"))),
    "raise_charger_actuation_failed": ("device", lambda h, x: (
        ri.raise_charger_actuation_failed(h, x, name="x", error="e"))),
}
ARG = {"read": "read_entities", "battery": "battery_entities",
       "device": "device_ids"}


def _keyed_raisers(src: str | None = None) -> set[str]:
    """Every ``raise_*`` whose issue id is built from one of its own
    parameters other than ``hass`` — a Repair per thing. The id may be the
    ``issue_id`` keyword or the third positional argument, and may be built
    into a local first."""
    tree = ast.parse(src if src is not None else REPAIR_ISSUES_PY.read_text())
    found = set()
    for node in tree.body:
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("raise_")):
            continue
        params = {a.arg for a in node.args.args + node.args.kwonlyargs}
        params.discard("hass")
        local: dict[str, set] = {}
        for st in ast.walk(node):
            if isinstance(st, ast.Assign):
                reads = {n.id for n in ast.walk(st.value)
                         if isinstance(n, ast.Name)}
                for t in st.targets:
                    if isinstance(t, ast.Name):
                        local.setdefault(t.id, set()).update(reads)

        def keyed(expr, params=params, local=local):
            names = {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}
            names |= {r for n in list(names) for r in local.get(n, ())}
            return bool(names & params)

        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            fn = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
            if fn != "async_create_issue":
                continue
            ids = [kw.value for kw in call.keywords if kw.arg == "issue_id"]
            ids += call.args[2:3]
            if any(keyed(e) for e in ids):
                found.add(node.name)
    return found


# ── the class: every keyed Repair says what clears it ───────────────────

def test_every_keyed_repair_says_who_clears_it_when_its_thing_leaves():
    found = _keyed_raisers()
    assert found >= {"raise_sensor_unavailable", "raise_charger_actuation_failed"}
    assert found == set(KEYED), (
        "A Repair keyed on one entity/device changed. Decide in KEYED what "
        "clears it once that entity or device leaves SEM's settings — a "
        "Repair with no answer stays in Settings for good (#1140).")


def test_the_detector_sees_each_way_to_key_an_id():
    """Its twin: positional, built into a local, async, keyword — each one
    is found; a fixed id is not."""
    src = textwrap.dedent('''
        def raise_a(hass, entity_id):
            ir.async_create_issue(hass, DOMAIN, f"a_{entity_id}")
        def raise_b(hass, *, device_id):
            iid = _b_issue_id(device_id)
            ir.async_create_issue(hass, domain=DOMAIN, issue_id=iid)
        async def raise_c(hass, slot):
            ir.async_create_issue(hass, domain=DOMAIN, issue_id=f"c_{slot}")
        def raise_d(hass, removed):
            ir.async_create_issue(hass, domain=DOMAIN, issue_id="d")
    ''')
    assert _keyed_raisers(src) == {"raise_a", "raise_b", "raise_c"}


def test_the_1140_answers_are_the_ones_tested_here():
    assert {k for k, v in KEYED.items() if v.startswith("#1140")} == set(RAISE)


# ── the sweep, on every #1140 Repair ────────────────────────────────────

@pytest.mark.parametrize("name", sorted(RAISE))
async def test_a_repair_of_a_thing_sem_no_longer_uses_goes(hass, name):
    kind, raise_it = RAISE[name]
    raise_it(hass, "sensor.old")
    raise_it(hass, "sensor.new")
    (old,) = {i for i in _ids(hass) if i.endswith("sensor.old")}
    (new,) = {i for i in _ids(hass) if i.endswith("sensor.new")}

    cleared = ri.clear_orphan_repairs(hass, **{ARG[kind]: {"sensor.new"}})

    assert cleared == 1
    assert old not in _ids(hass)
    assert new in _ids(hass)


@pytest.mark.parametrize("name", sorted(RAISE))
async def test_an_unknown_owner_leaves_its_kind_alone(hass, name):
    """``None`` is "not known", never "nothing": every other kind is swept
    to empty and this one stays."""
    kind, raise_it = RAISE[name]
    raise_it(hass, "sensor.old")
    others = {k: set() for k in ARG.values() if k != ARG[kind]}
    ri.clear_orphan_repairs(hass, **others)
    assert any(i.endswith("sensor.old") for i in _ids(hass))


async def test_the_kinds_do_not_keep_each_other(hass):
    """An entity a battery Repair may name does not keep a sensor Repair of
    the same id, and the other way round."""
    ri.raise_sensor_unavailable(hass, "number.setpoint")
    ri.raise_battery_force_discharge_unsupported(hass, "sensor.grid", error="e")
    ri.clear_orphan_repairs(hass, read_entities={"sensor.grid"},
                            battery_entities={"number.setpoint"})
    assert not _ids(hass)


async def test_other_repairs_are_not_touched(hass):
    ri.raise_soc_cap_unenforceable(hass, "ev_charger_9", name="x",
                                   target_soc=80.0)
    ri.raise_hot_water_entity_unavailable(hass, "switch.boiler",
                                          minutes_unavailable=6)
    ri.raise_no_recorder(hass)
    ri.raise_split_grid_guessed(hass, import_entity="sensor.a",
                                export_entity="sensor.b")
    before = _ids(hass)
    assert ri.clear_orphan_repairs(
        hass, read_entities=set(), battery_entities=set(),
        device_ids=set()) == 0
    assert _ids(hass) == before


# ── the reader knows what it reads ──────────────────────────────────────

def _reader(hass, **config):
    r = SensorReader(hass, config)
    r._sign_vote_warmup = 0
    return r


async def test_the_reader_names_what_it_read_and_starts_again(hass):
    hass.states.async_set("sensor.new_grid", "-500", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.pv", "1200", {"unit_of_measurement": "W"})
    r = _reader(hass, grid_power_sensor="sensor.new_grid",
                solar_production_sensor="sensor.pv")
    for _ in range(3):
        r.read_power()

    read, cycles = r.entities_read()

    assert {"sensor.new_grid", "sensor.pv"} <= read
    assert "sensor.old_grid" not in read
    assert cycles == 3
    assert r.entities_read() == (frozenset(), 0)


async def test_an_unavailable_entity_is_still_read(hass):
    """A sensor that is down is one SEM reads — its Repair has an owner."""
    hass.states.async_set("sensor.new_grid", "unavailable")
    r = _reader(hass, grid_power_sensor="sensor.new_grid")
    r.read_power()
    assert "sensor.new_grid" in r.entities_read()[0]


# ── the cycle: when the sweep runs, and what it keeps ───────────────────

def _coordinator(hass, reader, *, config=None, devices=(), chargers=(),
                 options=None):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = hass
    c._sensor_reader = reader
    c.config = dict(config or {})
    c._battery_adapters = {}
    c._ed_resolve_pending = False
    c._ed_answered = True
    c._surplus_controller = SurplusController(hass)
    for dev in devices:
        c._surplus_controller.register_device(dev)
    c._ev_devices = {d.device_id: d for d in chargers}
    c._ev_device = None
    c.config_entry = SimpleNamespace(
        options=dict({REFS_KEY: []} if options is None else options))
    return c


def _load(hass, did):
    """A load driven by current, built the way features/device_registry.py
    builds one — it files ``charger_actuation_failed`` under its own id."""
    return CurrentControlDevice(
        hass=hass, device_id=did, name=did, priority=5, min_current=6,
        max_current=16, phases=1, voltage=230.0,
        current_entity_id=f"number.{did}_current")


def _cycles(c, n, t0, step=10.0):
    for k in range(n):
        with patch(MONO, return_value=t0 + k * step):
            c._sensor_reader.read_power()
            c._sweep_orphan_repairs()


async def test_a_changed_grid_sensor_takes_its_old_repair_with_it(hass):
    """The reported case: ``sensor.old_grid`` left the settings with its
    "unavailable" Repair. The new grid sensor is down too — that Repair is
    the reader's own, and it stays."""
    ri.raise_sensor_unavailable(hass, "sensor.old_grid", minutes_unavailable=30)
    ri.raise_sensor_stale(hass, "sensor.old_grid", minutes_stale=30)
    hass.states.async_set("sensor.new_grid", "unavailable")
    c = _coordinator(hass, _reader(hass, grid_power_sensor="sensor.new_grid"))
    t0 = 1000.0

    _cycles(c, 29, t0)                    # 280 s: the window is not up
    assert ri._sensor_issue_id("sensor.old_grid") in _ids(hass)
    _cycles(c, 3, t0 + 290)               # 300 s and on
    left = _ids(hass)
    assert not {ri._sensor_issue_id("sensor.old_grid"),
                ri._stale_issue_id("sensor.old_grid")} & left
    assert ri._sensor_issue_id("sensor.new_grid") in left


async def test_the_battery_and_device_repairs_keep_only_their_owners(hass):
    hass.states.async_set("sensor.grid", "100")
    c = _coordinator(
        hass, _reader(hass, grid_power_sensor="sensor.grid"),
        config={"battery_force_discharge_control_entity": "number.fd",
                "battery_strategy_entities": ["select.s1", "select.s2"],
                "ev_chargers": [{"id": "ev_charger_parked"}]},
        devices=[_load(hass, "pool_pump")],
        chargers=[_load(hass, "ev_charger")])
    for eid in ("number.fd", "select.s2", "number.old_fd"):
        ri.raise_battery_force_discharge_unsupported(hass, eid, error="e")
    for did in ("pool_pump", "ev_charger", "ev_charger_parked", "old_pump"):
        ri.raise_charger_actuation_failed(hass, did, name=did, error="e")

    _cycles(c, 31, 0.0)

    left = _ids(hass)
    assert ri._battery_force_discharge_issue_id("number.old_fd") not in left
    assert ri._actuation_issue_id("old_pump") not in left
    for eid in ("number.fd", "select.s2"):
        assert ri._battery_force_discharge_issue_id(eid) in left
    for did in ("pool_pump", "ev_charger", "ev_charger_parked"):
        assert ri._actuation_issue_id(did) in left


async def test_the_late_found_primary_charger_keeps_its_repair(hass):
    """No charger yet and no saved list: the start-up retry may still find
    ``ev_charger`` (#1139's rule). With a saved list, no charger is the
    user's answer and the Repair goes."""
    hass.states.async_set("sensor.grid", "100")
    ri.raise_charger_actuation_failed(hass, "ev_charger", name="x", error="e")
    c = _coordinator(hass, _reader(hass, grid_power_sensor="sensor.grid"),
                     options={})
    _cycles(c, 31, 0.0)
    assert ri._actuation_issue_id("ev_charger") in _ids(hass)

    c.config_entry.options[REFS_KEY] = []
    _cycles(c, 3, 4000.0)                 # the next hourly sweep
    assert ri._actuation_issue_id("ev_charger") not in _ids(hass)


async def test_it_repeats_hourly_for_an_owner_that_leaves_while_sem_runs(hass):
    hass.states.async_set("sensor.grid", "100")
    c = _coordinator(hass, _reader(hass, grid_power_sensor="sensor.grid"),
                     devices=[_load(hass, "pool_pump")])
    ri.raise_charger_actuation_failed(hass, "pool_pump", name="x", error="e")
    _cycles(c, 31, 0.0)
    assert ri._actuation_issue_id("pool_pump") in _ids(hass)

    c._surplus_controller.unregister_device("pool_pump")  # gone from the ED
    _cycles(c, 3, 400.0)                   # before the hour: still there
    assert ri._actuation_issue_id("pool_pump") in _ids(hass)
    _cycles(c, 3, 300.0 + 3600.0)
    assert ri._actuation_issue_id("pool_pump") not in _ids(hass)


@pytest.mark.parametrize("why", ["starting", "ed_pending"])
async def test_nothing_goes_before_sem_has_read_a_full_window(hass, why):
    """While HA starts, or the Energy Dashboard sensors are still being
    found, the reads are not the ones SEM will make: the clock waits."""
    ri.raise_sensor_unavailable(hass, "sensor.ed_grid", minutes_unavailable=9)
    c = _coordinator(hass, _reader(hass))
    if why == "starting":
        hass.set_state(CoreState.starting)
    else:
        c._ed_resolve_pending = True
    _cycles(c, 100, 0.0)
    assert ri._sensor_issue_id("sensor.ed_grid") in _ids(hass)
    assert c._orphan_sweep_at is None
    hass.set_state(CoreState.running)


async def test_a_thin_window_leaves_the_sensor_repairs_alone(hass):
    """Two reads say too little about what SEM reads; the other kinds,
    known from the config, are still swept."""
    ri.raise_sensor_unavailable(hass, "sensor.old", minutes_unavailable=9)
    ri.raise_charger_actuation_failed(hass, "old_pump", name="x", error="e")
    c = _coordinator(hass, _reader(hass))
    with patch(MONO, return_value=0.0):
        c._sweep_orphan_repairs()          # starts the clock
    _cycles(c, 2, 400.0)
    left = _ids(hass)
    assert ri._sensor_issue_id("sensor.old") in left
    assert ri._actuation_issue_id("old_pump") not in left


async def test_an_energy_dashboard_sem_could_not_read_leaves_them_alone(hass):
    """Then SEM reads its fallback keys, not the sensors it normally reads:
    the window says nothing about those."""
    ri.raise_sensor_unavailable(hass, "sensor.ed_grid", minutes_unavailable=9)
    hass.states.async_set("sensor.grid", "100")
    c = _coordinator(hass, _reader(hass, grid_power_sensor="sensor.grid"))
    c._ed_answered = False
    _cycles(c, 31, 0.0)
    assert ri._sensor_issue_id("sensor.ed_grid") in _ids(hass)


async def test_a_found_soc_sensor_that_is_down_keeps_its_repair(hass):
    """(review) SOC detection reads only a sensor that answers. After a
    restart with the SOC sensor still down it is never read — but it is
    still the one SEM reads, so its Repair stays."""
    hass.states.async_set("sensor.home_battery_power", "-300",
                          {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.home_battery_soc", "unavailable")
    hass.states.async_set("sensor.grid", "100")
    ri.raise_sensor_unavailable(hass, "sensor.home_battery_soc",
                                minutes_unavailable=20)
    r = _reader(hass)
    r.set_energy_dashboard_config(EnergyDashboardConfig(
        solar_power="sensor.pv", grid_import_power="sensor.grid",
        battery_power="sensor.home_battery_power"))
    c = _coordinator(hass, r)
    _cycles(c, 31, 0.0)
    assert ri._sensor_issue_id("sensor.home_battery_soc") in _ids(hass)


async def test_a_swept_sensor_read_again_files_a_fresh_repair(hass):
    """(review) The sweep clears what the reader's memos still point at:
    a sensor dropped mid-run (a live Energy Dashboard edit) and then put
    back while still down must be filed again, not trusted to a Repair
    that is gone."""
    hass.states.async_set("sensor.x", "unavailable")
    r = _reader(hass, grid_power_sensor="sensor.x")
    with patch(MONO, return_value=0.0):
        r.read_power()
    with patch(MONO, return_value=400.0):
        r.read_power()                     # 400 s down: Repair filed
    assert ri._sensor_issue_id("sensor.x") in _ids(hass)

    r.config.grid_power_sensor = None      # dropped without a reload
    c = _coordinator(hass, r)
    r.entities_read()                      # the window starts now
    _cycles(c, 31, 1000.0)
    assert ri._sensor_issue_id("sensor.x") not in _ids(hass)

    r.config.grid_power_sensor = "sensor.x"   # back, still down
    for t in (5000.0, 5400.0):
        with patch(MONO, return_value=t):
            r.read_power()
    assert ri._sensor_issue_id("sensor.x") in _ids(hass)


# ── the split-grid pick that is dropped (sibling) ───────────────────────

async def test_a_dropped_split_grid_pick_takes_both_its_repairs(hass):
    r = _reader(hass)
    for eid in ("sensor.old_import", "sensor.export"):
        ri.raise_sensor_unavailable(hass, eid, minutes_unavailable=9)
        ri.raise_sensor_stale(hass, eid, minutes_stale=12)
    r._sensor_repair_raised.add("sensor.old_import")
    r._sensor_unavailable_since["sensor.old_import"] = 1.0

    r._forget_split_grid_picks(
        {"import": "sensor.old_import", "export": "sensor.export"},
        keep=("sensor.new_import", "sensor.export"))

    left = _ids(hass)
    assert not {ri._sensor_issue_id("sensor.old_import"),
                ri._stale_issue_id("sensor.old_import")} & left
    assert {ri._sensor_issue_id("sensor.export"),
            ri._stale_issue_id("sensor.export")} <= left
    # a pick adopted again starts its own outage clock
    assert "sensor.old_import" not in r._sensor_repair_raised
    assert "sensor.old_import" not in r._sensor_unavailable_since


async def test_a_rediscovery_keeps_the_outage_repair_of_its_picks(hass):
    """(review) A rediscovery mostly picks the same meters again, so it does
    not clear their "unavailable" Repair or reset its clock."""
    r = _reader(hass)
    r._split_grid_discovery["import"] = "sensor.imp"
    ri.raise_sensor_unavailable(hass, "sensor.imp", minutes_unavailable=9)
    r._sensor_repair_raised.add("sensor.imp")
    r.invalidate_split_grid_cache()
    assert ri._sensor_issue_id("sensor.imp") in _ids(hass)
    assert "sensor.imp" in r._sensor_repair_raised


# ── the call site ───────────────────────────────────────────────────────

def test_every_cycle_sweeps_after_it_reads():
    """Deleting the call leaves every test above green — so pin it: the
    cycle calls the sweep after its first read, outside any ``if``."""
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(SEMCoordinator._async_update_data)))
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            reads = [i for i, st in enumerate(block) if _is_first_read(st)]
            if not reads:
                continue
            sweeps = [i for i, st in enumerate(block) if _holds_sweep(st)]
            assert sweeps and sweeps[0] > reads[0], (
                "the sweep must sit beside the cycle's first read_power, "
                "after it and in the same block")
            return
    raise AssertionError("read_power() not found in _async_update_data")


def _is_first_read(st) -> bool:
    return (isinstance(st, ast.Assign)
            and [getattr(t, "id", None) for t in st.targets] == ["power"]
            and isinstance(st.value, ast.Call)
            and getattr(st.value.func, "attr", None) == "read_power")


def _holds_sweep(st) -> bool:
    def direct(x):
        return (isinstance(x, ast.Expr) and isinstance(x.value, ast.Call)
                and getattr(x.value.func, "attr", None) == "_sweep_orphan_repairs")
    return direct(st) or (isinstance(st, ast.Try) and any(direct(x) for x in st.body))
