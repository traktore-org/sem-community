"""#1048 C2 — a phase over its limit sheds loads, not only chargers.

RienduPre (#1048): a 23 A limit per phase, L3 at 30 A, the pool heat pump on
L3 and the house heat pump on all three. The phase guard acted on chargers
only — it clamps an increase to the headroom and stops a charger outright —
so with no car charging it watched the fuse go.

After the chargers are filtered, a phase still over its limit (or over with
no car drawing) now asks for its loads:

* those known to draw on it (that line, or all three) first, highest
  priority number first, until the amps they free cover the excess; one of
  unknown phase per cycle only when they cannot;
* critical loads, hands-off loads and chargers are never taken;
* a load the surplus controller owns is HELD for it (#649, one writer per
  load); one of load management's own is switched off;
* nothing taken comes back, and no known load of a latched phase starts,
  until the guard's own recovery latch clears — margin on every phase for
  its recovery cycles, the rule the chargers wait for — so it does not flap.

The guard reacts once per coordinator cycle.
"""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.const import LoadManagementState
from custom_components.solar_energy_management.coordinator.active_phase_guard import (
    ActivePhaseGuard,
)
from custom_components.solar_energy_management.coordinator.dual_phase_guard import (
    _phase_result,
)
from custom_components.solar_energy_management.features.phase_shed import (
    order_candidates,
    over_phases,
    relief_a,
    single_phase_supply,
)
from custom_components.solar_energy_management.load_management import (
    LoadManagementCoordinator,
)

ROOT = Path(__file__).resolve().parents[1]
LIMIT_A = 23.0
ENFORCING = {"phase_guard_enabled": True,
             "phase_guard_enforcement_enabled": True}


def _snapshot(l1=10.0, l2=12.0, l3=30.0, *, limit=LIMIT_A, phase_count=3):
    keys = ("l1",) if phase_count == 1 else ("l1", "l2", "l3")
    values = {"l1": l1, "l2": l2, "l3": l3}
    grid = {k: _phase_result(values[k], limit) for k in keys}
    unsafe = [f"grid:{k}:over_limit" for k, v in grid.items() if not v["safe"]]
    return {"mode": "observer", "topology": "grid_only",
            "phase_count": phase_count, "grid": grid, "inverter": {},
            "safe": not unsafe, "data_fresh": True,
            "stop_reason": ",".join(unsafe)}


# ── The phase's arithmetic ───────────────────────────────────────────────

def test_l3_at_30_against_23_is_7_amps_over():
    assert over_phases(_snapshot()) == {"L3": 7.0}
    assert over_phases(_snapshot(l3=22.0)) == {}


def test_the_worse_lane_counts_and_an_unread_phase_is_never_over():
    snap = _snapshot(l3=25.0)
    snap["topology"] = "hybrid_load_port"
    snap["inverter"] = {"l3": _phase_result(31.0, LIMIT_A)}
    assert over_phases(snap) == {"L3": 8.0}
    snap["grid"]["l3"] = {"current_a": None, "margin_a": None,
                          "limit_a": LIMIT_A, "safe": False,
                          "data_fresh": False, "reason": "stale"}
    snap["inverter"] = {}
    assert over_phases(snap) == {}, "a stale reading sheds nothing on a guess"
    # …even one that still carries its last numbers
    snap["grid"]["l3"] = {**_phase_result(31.0, LIMIT_A), "data_fresh": False}
    assert over_phases(snap) == {}


@pytest.mark.parametrize("load, watts, amps", [
    ("L3", 2000.0, 2000.0 / 230.0),
    ("3ph", 6000.0, 6000.0 / 690.0),
    ("L1", 2000.0, 0.0),
    ("unknown", 2000.0, 0.0),
])
def test_what_switching_a_load_off_frees_on_l3(load, watts, amps):
    assert relief_a(load, watts, "L3") == pytest.approx(amps)


def test_on_a_one_phase_supply_every_load_is_on_it():
    snap = _snapshot(l1=30.0, phase_count=1)
    assert single_phase_supply(snap)
    assert over_phases(snap) == {"L1": 7.0}
    assert relief_a("unknown", 2300.0, "L1", single_phase=True) == pytest.approx(10.0)


def test_the_order_is_known_first_then_unknown_each_by_priority():
    rows = [
        ("heat_pump", {"phase": "3ph", "priority": 3}, 6000.0),
        ("pool_heat_pump", {"phase": "L3", "priority": 7}, 2000.0),
        ("kettle", {"phase": "L1", "priority": 9}, 2000.0),
        ("dryer", {"phase": "unknown", "priority": 6}, 2500.0),
        ("fridge", {"priority": 8}, 150.0),
    ]
    known, unknown = order_candidates(rows, "L3")
    assert [d for d, _, _ in known] == ["pool_heat_pump", "heat_pump"]
    assert [d for d, _, _ in unknown] == ["fridge", "dryer"]


# ── The guard decides WHEN loads answer ──────────────────────────────────

def test_with_no_car_charging_the_loads_answer_at_once():
    g = ActivePhaseGuard()
    g.update(_snapshot(), ENFORCING)
    assert g.phase_shed_request(ev_drawing=False) == {"L3": 7.0}


def test_with_a_car_charging_the_chargers_answer_first():
    """Stopping the car is the guard's first answer; a phase still over on
    the next cycle asks the loads too."""
    g = ActivePhaseGuard()
    g.update(_snapshot(), ENFORCING)
    assert g.phase_shed_request(ev_drawing=True) == {}
    g.update(_snapshot(l3=28.0), ENFORCING)
    assert g.phase_shed_request(ev_drawing=True) == {"L3": 5.0}


def test_an_observing_guard_sheds_nothing():
    g = ActivePhaseGuard()
    g.update(_snapshot(), {"phase_guard_enabled": True})
    assert g.phase_shed_request(ev_drawing=False) == {}
    assert g.loads_may_return


def test_the_loads_wait_for_the_latch_the_chargers_wait_for():
    g = ActivePhaseGuard()
    g.update(_snapshot(), ENFORCING)
    assert g.latched_phases == {"L3"} and not g.loads_may_return
    # under the limit, but the recovery margin (2 A) is asked for 3 cycles
    for _ in range(2):
        g.update(_snapshot(l3=20.0), ENFORCING)
        assert g.latched_phases == {"L3"} and not g.loads_may_return
    g.update(_snapshot(l3=20.0), ENFORCING)
    assert g.control_authorized and g.loads_may_return
    assert g.latched_phases == frozenset()


def test_a_margin_too_thin_keeps_them_down():
    g = ActivePhaseGuard()
    g.update(_snapshot(), ENFORCING)
    for _ in range(5):
        g.update(_snapshot(l3=22.0), ENFORCING)   # 1 A < the 2 A asked
    assert not g.loads_may_return


# ── Load management throws the switches ──────────────────────────────────

def _info(name, phase, priority, *, mode="peak_only", surplus=False, **kw):
    base = dict(
        switch_entity=f"switch.{name}", power_entity=f"sensor.{name}_power",
        friendly_name=name, power_rating=1000.0, is_available=True,
        priority=priority, is_critical=False, is_controllable=True,
        has_control_handle=True, user_hands_off=False,
        device_type="individual_device", control_mode=mode,
        surplus_managed=surplus, phase=phase,
        control={"type": "switch", "entity": f"switch.{name}"},
    )
    base.update(kw)
    return base


@pytest.fixture
def lm(mock_hass):
    entry = MagicMock()
    entry.options = {"load_management_enabled": True, "target_peak_limit": 5.0}
    entry.entry_id = "e"
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ) as MockDiscovery, patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        draws = {}
        disc = MagicMock()
        disc.get_device_current_state = MagicMock(
            side_effect=lambda info: {
                "is_on": draws.get(info["friendly_name"], 0) > 0,
                "current_power": draws.get(info["friendly_name"], 0)})
        disc.turn_on_device = AsyncMock(return_value=True)
        disc.turn_off_device = AsyncMock(return_value=True)
        MockDiscovery.return_value = disc
        MockStore.return_value = MagicMock(
            async_load=AsyncMock(return_value=None), async_save=AsyncMock())
        c = LoadManagementCoordinator(mock_hass, entry)
        c.hass.services.async_call = AsyncMock()
        c.hass.states.get = MagicMock(return_value=MagicMock(state="on"))
        c._device_discovery = disc
        c._observer_mode = False
        c.draws = draws
        yield c


def _switched_off(lm):
    return [c.args[2]["entity_id"] for c in lm.hass.services.async_call.await_args_list
            if c.args[:2] == ("switch", "turn_off")]


def _house(lm, pool_w=2000.0, hp_w=6000.0):
    lm._devices["pool"] = _info("pool_heat_pump", "L3", 7)
    lm._devices["hp"] = _info("heat_pump", "3ph", 3)
    lm._devices["kettle"] = _info("kettle", "L1", 9)
    lm.draws.update({"pool_heat_pump": pool_w, "heat_pump": hp_w, "kettle": 2000.0})


@pytest.mark.asyncio
async def test_riendupre_the_pool_pump_goes_first(lm):
    """Limit 23 A, L3 at 30 A, pool heat pump on L3, heat pump three-phase:
    the pool pump goes — it alone frees 8.7 A — and the heat pump and the
    L1 kettle keep running."""
    _house(lm)
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == ["pool"]
    assert _switched_off(lm) == ["switch.pool_heat_pump"]
    assert lm._devices["pool"]["shed_reason"] == "PHASE"
    assert lm._devices["pool"]["shed_phase"] == "L3"


@pytest.mark.asyncio
async def test_when_the_first_cannot_cover_it_the_next_known_goes_too(lm):
    _house(lm, pool_w=1000.0)        # 4.3 A < 7 A
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == ["pool", "hp"]
    assert "switch.kettle" not in _switched_off(lm)


@pytest.mark.asyncio
async def test_unknown_loads_only_after_the_known_ones_one_per_cycle(lm):
    lm._devices["dryer"] = _info("dryer", "unknown", 6)
    lm._devices["oven"] = _info("oven", "unknown", 8)
    lm._devices["kettle"] = _info("kettle", "L1", 9)
    lm.draws.update({"dryer": 2500.0, "oven": 3000.0, "kettle": 2000.0})
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == ["oven"], "one per cycle — the meter answers"
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == ["dryer"]
    assert "switch.kettle" not in _switched_off(lm), "a load on L1 never answers for L3"


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [
    {"is_critical": True},
    {"user_hands_off": True},
    {"control_mode": "off"},
    {"device_type": "ev_charger"},
    {"is_available": False},
])
async def test_never_taken(lm, kw):
    lm._devices["pool"] = _info("pool_heat_pump", "L3", 7, **kw)
    lm.draws["pool_heat_pump"] = 2000.0
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == [] and _switched_off(lm) == []
    assert verdict["path"] == "nothing_on_phase"


@pytest.mark.asyncio
async def test_a_surplus_load_is_held_for_its_owner_never_switched_here(lm):
    lm._devices["pool"] = _info("pool_heat_pump", "L3", 7, mode="surplus",
                                surplus=True)
    lm.draws["pool_heat_pump"] = 2000.0
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == ["pool"]
    assert verdict["shed"] == {"pool": "L3"} and verdict["hold"]["pool"] == "L3"
    assert _switched_off(lm) == [], "#649: one writer per load"
    assert lm.get_load_management_data()["devices"]["pool"]["is_shed"]


@pytest.mark.asyncio
async def test_nothing_comes_back_before_the_latch_clears(lm):
    _house(lm)
    await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    lm.draws["pool_heat_pump"] = 0.0          # it is off now
    lm._last_restore_time = None
    lm._devices["pool"]["last_turned_off"] -= timedelta(hours=1)
    # the peak is fine, the phase is under its limit — the latch still stands
    await lm.process_phase_guard({}, may_restore=False)
    await lm._restore_loads()
    assert "pool" in lm._devices_shed
    # the latch clears: it comes back through the ordinary restore
    await lm.process_phase_guard({}, may_restore=True)
    await lm._restore_loads()
    assert "pool" not in lm._devices_shed
    assert "shed_phase" not in lm._devices["pool"]


@pytest.mark.asyncio
async def test_a_registry_rebuild_mid_episode_keeps_it_down(lm):
    """A drag or a config change rebuilds the load manager's rows; the
    phase shed is remembered by the load manager, not by the row."""
    _house(lm)
    await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    lm.draws["pool_heat_pump"] = 0.0
    lm._devices["pool"] = _info("pool_heat_pump", "L3", 7)      # rebuilt row
    lm._last_restore_time = None
    await lm.process_phase_guard({}, may_restore=False)
    await lm._restore_loads()
    assert "pool" in lm._devices_shed
    shown = lm.get_load_management_data()["devices"]["pool"]
    assert shown["is_shed"] and shown["shed_reason"] == "PHASE"
    assert shown["shed_phase"] == "L3"


@pytest.mark.asyncio
async def test_held_surplus_loads_return_one_at_a_time(lm):
    for name in ("pool_heat_pump", "spa"):
        lm._devices[name] = _info(name, "L3", 7, mode="surplus", surplus=True)
        lm.draws[name] = 1000.0
    await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert set(lm._phase_held) == {"pool_heat_pump", "spa"}
    lm._last_restore_time = None
    first = await lm.process_phase_guard({}, may_restore=True)
    assert len(first["shed"]) == 1
    second = await lm.process_phase_guard({}, may_restore=True)
    assert second["path"] == "waiting:restore_delay"


@pytest.mark.asyncio
async def test_while_latched_known_surplus_loads_on_it_do_not_start(lm):
    lm._devices["pool"] = _info("pool_heat_pump", "L3", 7, mode="surplus", surplus=True)
    lm._devices["hp"] = _info("heat_pump", "3ph", 3, mode="surplus", surplus=True)
    lm._devices["kettle"] = _info("kettle", "L1", 9, mode="surplus", surplus=True)
    lm._devices["dryer"] = _info("dryer", "unknown", 6, mode="surplus", surplus=True)
    verdict = await lm.process_phase_guard({}, may_restore=False, latched={"L3"})
    assert verdict["hold"] == {"pool": "L3", "hp": "L3"}, (
        "unknown starts are not held on a guess; L1 is not latched")
    assert (await lm.process_phase_guard({}, may_restore=True))["hold"] == {}


@pytest.mark.asyncio
async def test_observer_mode_takes_nothing(lm):
    _house(lm)
    lm._observer_mode = True
    verdict = await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    assert verdict["thrown"] == [] and verdict["path"] == "observer:withheld"
    assert _switched_off(lm) == []


@pytest.mark.asyncio
async def test_a_phase_shed_does_not_hold_the_peak_in_shedding(lm):
    """The peak's state machine keeps SHEDDING in the warning zone while it
    has loads of its own down; the guard's are not the peak's."""
    _house(lm)
    await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
    warning, _ = lm._effective_levels()
    peak = (warning + lm._target_peak_limit) / 2
    assert lm._determine_load_management_state(peak, 0.0) == LoadManagementState.WARNING


@pytest.mark.asyncio
async def test_the_shed_is_announced_and_the_notice_withdrawn(lm):
    _house(lm)
    with patch("homeassistant.components.persistent_notification.async_create") as create, \
         patch("homeassistant.components.persistent_notification.async_dismiss") as dismiss:
        await lm.process_phase_guard({"L3": 7.0}, may_restore=False)
        assert create.call_args.kwargs["notification_id"] == "sem_phase_shed"
        assert "L3" in create.call_args.args[1]
        lm.draws["pool_heat_pump"] = 0.0
        lm._last_restore_time = None
        lm._devices["pool"]["last_turned_off"] -= timedelta(hours=1)
        await lm.process_phase_guard({}, may_restore=True)
        await lm._restore_loads()
        dismiss.assert_called_with(lm.hass, "sem_phase_shed")


# ── The surplus controller honours the hold ──────────────────────────────

def test_a_held_device_does_not_start():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        _would_start,
    )
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    dev = SwitchDevice(MagicMock(), device_id="pool", name="Pool", rated_power=2000.0)
    assert dev.can_activate() and _would_start(dev)
    dev._phase_hold = "L3"
    assert not dev.can_activate()
    assert not _would_start(dev)


@pytest.mark.asyncio
async def test_the_surplus_controller_backs_a_taken_load_off(mock_hass):
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )

    from .test_508_phase2_surplus_peak import _make_device
    sc = SurplusController(mock_hass)
    pool = _make_device("pool", priority=7, is_active=True, consumption=2000.0)
    spa = _make_device("spa", priority=8, is_active=True, consumption=1500.0)
    pool._phase_hold, pool._phase_shed = "L3", True
    spa._phase_hold, spa._phase_shed = None, False
    sc.register_device(pool)
    sc.register_device(spa)
    await sc.update(5000.0)
    pool.deactivate.assert_called_once()
    spa.deactivate.assert_not_called()


def test_the_declarative_path_sheds_it_too():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    tree = ast.parse((ROOT / "coordinator" / "surplus_controller.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_desired_intents")
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_phase_shed"
               for n in ast.walk(fn))
    assert SurplusController._desired_intents


# ── The coordinator wires it after the chargers ──────────────────────────

def _coordinator(lm=None, enforcer=None, config=None):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = dict(config or ENFORCING)
    c._load_manager = lm
    c._observer_mode = False
    c._active_phase_guard = enforcer
    c._phase_guard_snapshot = {}
    sc = MagicMock()
    c.devices = {"pool": MagicMock(), "spa": MagicMock()}
    sc._devices = c.devices
    c._surplus_controller = sc
    return c


@pytest.mark.asyncio
async def test_the_guards_request_reaches_load_management_and_the_holds_the_loads():
    g = ActivePhaseGuard()
    g.update(_snapshot(), ENFORCING)
    lm = MagicMock()
    lm.process_phase_guard = AsyncMock(return_value={
        "over": {"L3": 7.0}, "thrown": ["pool"], "latched": ["L3"],
        "hold": {"pool": "L3"}, "shed": {"pool": "L3"}, "path": "shed:1"})
    c = _coordinator(lm, g)
    c._phase_guard_snapshot = g.update(_snapshot(), ENFORCING)
    await c._phase_guard_loads(MagicMock(ev_power=0.0))
    kwargs = lm.process_phase_guard.await_args.kwargs
    assert lm.process_phase_guard.await_args.args[0] == {"L3": 7.0}
    assert kwargs["may_restore"] is False and kwargs["latched"] == {"L3"}
    assert c.devices["pool"]._phase_hold == "L3" and c.devices["pool"]._phase_shed is True
    assert c.devices["spa"]._phase_hold is None and c.devices["spa"]._phase_shed is False
    assert c._phase_guard_snapshot["loads"]["thrown"] == ["pool"]


@pytest.mark.asyncio
async def test_a_guard_switched_off_leaves_no_hold_behind():
    lm = MagicMock()
    lm.process_phase_guard = AsyncMock(return_value={"hold": {}, "shed": {}})
    c = _coordinator(lm, None, config={"phase_guard_enabled": False})
    c.devices["pool"]._phase_hold = "L3"
    await c._phase_guard_loads(MagicMock(ev_power=0.0))
    assert lm.process_phase_guard.await_args.kwargs == {"may_restore": True}
    assert c.devices["pool"]._phase_hold is None


@pytest.mark.asyncio
async def test_without_load_management_the_guard_says_so():
    g = ActivePhaseGuard()
    c = _coordinator(None, g)
    c._phase_guard_snapshot = g.update(_snapshot(), ENFORCING)
    await c._phase_guard_loads(MagicMock(ev_power=0.0))
    assert c._phase_guard_snapshot["loads"]["path"] == "load_management_off"


def test_it_runs_after_the_chargers_and_before_the_peak():
    """Step order in the cycle: the guard is evaluated (7.5a), the chargers
    filtered, then the loads (7.5a2) — before the peak's restore reads the
    hold (7.5b)."""
    src = (ROOT / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_async_update_data")
    lines = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", getattr(n.func, "id", None))
            if name in ("update_active_phase_guard", "filter_charger_decision",
                        "_phase_guard_loads", "process_peak_update"):
                lines.setdefault(name, []).append(n.lineno)
    assert (max(lines["update_active_phase_guard"])
            < max(lines["filter_charger_decision"])
            < min(lines["_phase_guard_loads"])
            < min(lines["process_peak_update"]))
