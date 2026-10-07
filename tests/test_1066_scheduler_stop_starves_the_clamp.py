"""#1066 — the night scheduler's idle verdict starved every protection branch.

@RienduPre, 2.2.0-beta.12, 2× Sessy, ``may_assist_ev: false``. Evening peak:
the car drew 4 kW and the packs gave 3.4 kW, 2.3 kW of it into the car. SEM's
own line at that moment::

    last_decisions.b1: intent=stop_force_charge,
                       reason="scheduler not_needed → ensure not force-charging"

Three faults, stacked:

1. ``decide_battery`` answered the scheduler's stop verdicts (idle, not
   needed, target reached, not profitable, outside the plan block) BEFORE
   the protection branches. With the night scheduler on there is ALWAYS a
   verdict, so the EV clamp, the #620 grid-funded clamp, the #879 house hold
   and the #892 morning window could never run — on every brand. The module
   docstring already said the stop wins only "while the adapter is still in
   FORCE_CHARGE intent"; nothing asked. (Class 20, shadowed branch.)
2. The clamp never read ``may_assist_ev``. The charger side asks it first
   (``decide._battery_assist_split``); the battery side, which is what keeps
   the inverter from covering the car on the meter, did not. (Class 88.)
3. Asked to limit with no discharge-limit entity — a Sessy has none — the
   brand writers recorded the watts as the limit in force and returned.
   Nothing went out, nothing said so.

What these tests pin: an idle scheduler verdict is invisible once no forced op
can be running (an isolation check over the whole protection grid); the stop
still wins while one may be; the permission holds the clamp in every arm; the
adapters say when they cannot cap; and, through real adapters across cycles,
the limit is written once the stop has landed and released when the car
leaves.
"""
from __future__ import annotations

import ast
import itertools
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    active_discharge_limit, actuate_battery, quantise_discharge_limit_w,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.goodwe import (
    GoodWeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_diag import (
    battery_actuation_diag,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent, BatteryRuntime, BatteryView, FleetContext,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    _SCHEDULER_STOP_STATES, STOP_FIRST_TRIES, decide_battery, forced_ops,
    stop_misses,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    HELD, SinkVerdict,
)

ROOT = Path(__file__).resolve().parents[1]
NO_LIMIT = BatteryControlAdapter.NO_DISCHARGE_LIMIT_ERROR


# ─────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────

def _sched(state, **kw):
    """A SchedulerDecision-shaped object. ``from_arbitrage`` defaults False,
    as the real dataclass does (a bare MagicMock attribute is truthy)."""
    m = MagicMock()
    m.state = MagicMock(value=state)
    m.from_arbitrage = False
    m.from_forecast_spend = False
    m.price_forced = False
    m.charge_power_w = 3000.0
    m.target_soc = 90.0
    m.duration_min = 60
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def _gate(*, covered, in_block=False):
    g = MagicMock()
    g.covered = covered
    g.in_block = in_block
    g.next_block_start = None
    g.reason = "uncovered"
    g.block_power_w = 0.0
    return g


def _view(*, sched=None, gate=None, forced=(None, None), misses=0, ev=True, solar=0.0,
          home=1076.0, soc=66.0, n=2, perms=None, protection=True,
          grid_funded=0.0, house=None, window=False, boost=None,
          wants_pack=False, spendable=0.0, mode="auto"):
    cfg = {"battery_mode": mode, "battery_max_discharge_power": 2200.0,
           "battery_discharge_protection_enabled": protection,
           "battery_morning_drain_floor_soc": 50.0}
    verdicts = {"house": SinkVerdict("house", house, "t")} if house else {}
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config=cfg,
        fleet=FleetContext(solar_w=solar, home_w=home, battery_soc=soc,
                           battery_count=n, buffer_soc=30.0,
                           battery_assist_min_surplus_w=1200.0),
        charging_state="idle",
        ev_charging=ev, ev_connected=ev,
        home_consumption_w=home,
        scheduler_decision=sched,
        plan_gate=gate,
        battery_permissions=perms,
        grid_funded_load_w=grid_funded,
        sink_verdicts=verdicts,
        morning_window_open=window,
        battery_boost_floor_soc=boost,
        ev_wants_pack=wants_pack,
        battery_spendable_kwh=spendable,
        sem_forced_charge=forced[0],
        sem_forced_discharge=forced[1],
        sem_stop_misses=misses,
    )


#: Every verdict that, when the scheduler is on, ends in a STOP.
_STOP_VERDICTS = [
    (_sched(s), None) for s in _SCHEDULER_STOP_STATES
] + [
    (_sched("scheduled"), _gate(covered=True, in_block=False)),   # outside block
    (_sched("scheduled"), _gate(covered=False)),                   # uncovered
    (_sched("scheduled"), None),                                   # no gate
    (_sched("not_profitable", from_arbitrage=True), None),         # arbitrage idle
]


# ─────────────────────────────────────────────────────────────────
# 1. The reporter's evening
# ─────────────────────────────────────────────────────────────────

class TestTheReportersEvening:
    """20:30, no sun, 1076 W of house, 4 kW of car, two packs, the scheduler
    on and saying ``not_needed``, ``may_assist_ev`` off."""

    def _evening(self, forced):
        return _view(sched=_sched("not_needed"), forced=forced,
                     perms={"may_assist_ev": False})

    def test_once_the_stop_has_landed_the_packs_are_capped_at_the_house(self):
        d = decide_battery(self._evening(forced=(False, None)))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(1076.0 / 2)
        assert "may not feed the car" in d.reason

    @pytest.mark.parametrize("charge", [None, True])
    def test_while_a_forced_charge_may_run_the_stop_still_goes_first(self, charge):
        d = decide_battery(self._evening(forced=(charge, False)))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    def test_the_old_code_path_is_what_the_reporter_saw(self):
        """The default view (nothing known) keeps the old precedence — that
        IS the line in the report. Pins that the default is not what fixed it."""
        v = _view(sched=_sched("not_needed"), perms={"may_assist_ev": False})
        assert decide_battery(v).reason == (
            "scheduler not_needed → ensure not force-charging")


# ─────────────────────────────────────────────────────────────────
# 2. Isolation: an idle verdict says nothing once nothing can run
# ─────────────────────────────────────────────────────────────────

_GRID = list(itertools.product(
    (True, False),                      # ev plugged in
    (0.0, 3000.0),                      # solar
    (66.0, 20.0),                       # soc (above / below the 30 % buffer)
    (None, {"may_assist_ev": False}, {"may_assist_ev": True}),
    (True, False),                      # protection switch
    (0.0, 600.0),                       # grid-funded load
    (None, HELD),                       # house verdict
    (False, True),                      # morning window
))


@pytest.mark.parametrize("sched,gate", _STOP_VERDICTS)
def test_an_idle_verdict_changes_nothing_once_no_forced_op_can_run(sched, gate):
    """The class-20 guard. Every protection input × every stop verdict: with
    no forced op running, the decision is exactly the one an install without
    the scheduler gets — intent, watts and the reason a user reads."""
    seen = set()
    for ev, solar, soc, perms, prot, gf, house, window in _GRID:
        kw = dict(ev=ev, solar=solar, soc=soc, perms=perms, protection=prot,
                  grid_funded=gf, house=house, window=window)
        bare = decide_battery(_view(sched=None, forced=(False, False), **kw))
        with_sched = decide_battery(_view(sched=sched, gate=gate,
                                          forced=(False, False), **kw))
        assert (with_sched.intent, with_sched.discharge_limit_w,
                with_sched.reason) == (bare.intent, bare.discharge_limit_w,
                                       bare.reason), kw
        seen.add(bare.intent)
    # Not vacuous: the grid reaches every protection outcome.
    assert {BatteryIntent.LIMIT_DISCHARGE, BatteryIntent.NORMAL} <= seen


@pytest.mark.parametrize("forced", [(None, None), (True, True)])
@pytest.mark.parametrize("sched,gate", _STOP_VERDICTS)
def test_while_its_direction_may_run_every_verdict_still_stops(sched, gate, forced):
    d = decide_battery(_view(sched=sched, gate=gate, forced=forced))
    want = (BatteryIntent.STOP_FORCE_DISCHARGE if sched.from_arbitrage
            else BatteryIntent.STOP_FORCE_CHARGE)
    assert d.intent is want


@pytest.mark.parametrize("sched,gate", _STOP_VERDICTS)
def test_a_verdict_for_the_stopped_direction_says_nothing(sched, gate):
    """Each verdict asks only about ITS direction: a night stop is silent once
    the charge stop landed, even with the discharge never seen."""
    forced = (None, False) if sched.from_arbitrage else (False, None)
    d = decide_battery(_view(sched=sched, gate=gate, forced=forced))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE


def test_a_scheduled_charge_in_its_block_still_wins_over_the_clamp():
    d = decide_battery(_view(sched=_sched("scheduled"),
                             gate=_gate(covered=True, in_block=True),
                             forced=(False, False)))
    assert d.intent is BatteryIntent.FORCE_CHARGE


class TestWhatSemStartedIsStoppedFirst:
    """A forced op SEM started and has not seen stop goes before NORMAL or
    LIMIT_DISCHARGE, whatever branch asked for them (review: an arbitrage
    stop after a night charge left a switch-based charge running; a Deye
    sell records no intent)."""

    @pytest.mark.parametrize("ev", [True, False])
    def test_a_charge_left_running_is_stopped(self, ev):
        d = decide_battery(_view(ev=ev, forced=(True, False)))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    @pytest.mark.parametrize("ev", [True, False])
    def test_a_sale_left_running_is_stopped(self, ev):
        d = decide_battery(_view(ev=ev, forced=(False, True)))
        assert d.intent is BatteryIntent.STOP_FORCE_DISCHARGE

    def test_the_export_held_hold_stops_a_running_sale(self):
        sell = _sched("discharging_arbitrage", from_forecast_spend=True,
                      floor_soc=0.0, discharge_power_w=2000.0)
        v = _view(ev=False, sched=sell, forced=(False, True))
        v = type(v)(**{**v.__dict__, "forecast_sell": (True, 2000.0),
                       "forecast_spending_enabled": True,
                       "battery_spendable_kwh": 0.0})
        assert decide_battery(v).intent is BatteryIntent.STOP_FORCE_DISCHARGE

    def test_unknown_never_sends_a_stop_without_a_scheduler(self):
        """Zero config: no scheduler, nothing known → exactly as before."""
        for ev in (True, False):
            d = decide_battery(_view(ev=ev, forced=(None, None)))
            assert d.intent in (BatteryIntent.NORMAL, BatteryIntent.LIMIT_DISCHARGE)

    def test_both_open_take_turns_discharge_first(self):
        want = {0: BatteryIntent.STOP_FORCE_DISCHARGE,
                1: BatteryIntent.STOP_FORCE_DISCHARGE,
                2: BatteryIntent.STOP_FORCE_CHARGE,
                4: BatteryIntent.STOP_FORCE_DISCHARGE,
                6: BatteryIntent.STOP_FORCE_CHARGE}
        for m, intent in want.items():
            assert decide_battery(_view(forced=(True, True), misses=m)).intent \
                is intent, m

    @pytest.mark.parametrize("forced", [(True, False), (False, True), (True, True)])
    def test_a_stop_that_never_lands_lets_protection_through_every_other_cycle(self, forced):
        """Review round 2: stop-only forever was worse than develop, whose
        NORMAL / LIMIT wrote the limit even when their zero-write failed."""
        for m in range(STOP_FIRST_TRIES):
            assert decide_battery(_view(forced=forced, misses=m)).intent in (
                BatteryIntent.STOP_FORCE_CHARGE, BatteryIntent.STOP_FORCE_DISCHARGE)
        for m in range(STOP_FIRST_TRIES, STOP_FIRST_TRIES + 6):
            d = decide_battery(_view(forced=forced, misses=m))
            if m % 2:
                assert d.intent is BatteryIntent.LIMIT_DISCHARGE, m
                assert d.discharge_limit_w == pytest.approx(538.0)
                assert f"has not landed in {m} cycles" in d.reason
            else:
                assert d.intent in (BatteryIntent.STOP_FORCE_CHARGE,
                                    BatteryIntent.STOP_FORCE_DISCHARGE), m

    @pytest.mark.parametrize("mode,want", [
        ("force_charge", BatteryIntent.FORCE_CHARGE),
        ("off", BatteryIntent.OFF)])
    def test_a_forced_mode_or_off_is_not_overridden(self, mode, want):
        assert decide_battery(_view(mode=mode, forced=(True, True))).intent is want


# ─────────────────────────────────────────────────────────────────
# 3. forced_op_may_run reads what LANDED
# ─────────────────────────────────────────────────────────────────

class _Stub:
    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)


class TestForcedOps:
    def test_no_adapter_is_unknown(self):
        assert forced_ops(None) == (None, None)

    def test_a_fresh_adapter_is_unknown(self):
        assert forced_ops(GenericBatteryAdapter(_hass({}), {})) == (None, None)

    @pytest.mark.parametrize("c,d", [(True, False), (False, True), (False, False)])
    def test_the_flags_are_read_per_direction(self, c, d):
        assert forced_ops(_Stub(_sem_forced_charge=c, _sem_forced_discharge=d)) == (c, d)

    @pytest.mark.parametrize("flag,want", [("_forcible_charging", (True, False)),
                                           ("_forcible_discharging", (False, True))])
    def test_huaweis_own_flags_count_as_started(self, flag, want):
        st = _Stub(_sem_forced_charge=False, _sem_forced_discharge=False,
                   **{flag: True})
        assert forced_ops(st) == want

    def test_a_stand_in_we_cannot_read_is_unknown(self):
        assert forced_ops(MagicMock()) == (None, None)

    def test_the_coordinator_hands_both_to_the_view(self):
        """One producer of BatteryView; it passes the adapter's answer, and
        under observer — which commands nothing — the armed steady state."""
        src = (ROOT / "coordinator/coordinator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        sites = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "BatteryView"]
        assert sites
        for call in sites:
            kw = {k.arg for k in call.keywords}
            assert {"sem_forced_charge", "sem_forced_discharge",
                    "sem_stop_misses"} <= kw
        assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", None) == "_forced" for t in n.targets)]
        assert len(assigns) == 1
        val = assigns[0].value
        assert isinstance(val, ast.IfExp)
        assert ast.unparse(val.test) == "self._observer_mode"
        assert ast.unparse(val.body) == "(False, False)"
        assert ast.unparse(val.orelse) == "forced_ops(adapter)"


# ─────────────────────────────────────────────────────────────────
# 4. may_assist_ev holds the clamp in every arm
# ─────────────────────────────────────────────────────────────────

_NO = {"may_assist_ev": False}


class TestThePermissionHoldsTheClamp:
    def test_with_sun_above_the_gate(self):
        assert decide_battery(_view(solar=4000.0, home=800.0)).intent \
            is BatteryIntent.NORMAL
        d = decide_battery(_view(solar=4000.0, home=800.0, perms=_NO))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(400.0)

    def test_with_solar_plus_battery_on_the_charger(self):
        kw = dict(wants_pack=True, spendable=3.0)
        assert decide_battery(_view(**kw)).intent is BatteryIntent.NORMAL
        assert decide_battery(_view(perms=_NO, **kw)).intent \
            is BatteryIntent.LIMIT_DISCHARGE

    def test_with_the_protection_switch_off(self):
        assert decide_battery(_view(protection=False)).intent \
            is BatteryIntent.NORMAL
        assert decide_battery(_view(protection=False, perms=_NO)).intent \
            is BatteryIntent.LIMIT_DISCHARGE

    def test_a_morning_window_does_not_open_it(self):
        assert "morning window" in decide_battery(_view(window=True)).reason
        d = decide_battery(_view(window=True, perms=_NO))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert "morning window" not in d.reason

    def test_a_boost_does_not_open_it(self):
        assert "battery boost" in decide_battery(_view(boost=20.0)).reason
        d = decide_battery(_view(boost=20.0, perms=_NO))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE

    def test_no_car_no_clamp(self):
        assert decide_battery(_view(ev=False, perms=_NO)).intent \
            is BatteryIntent.NORMAL

    @pytest.mark.parametrize("perms", [None, {}, {"may_assist_ev": None},
                                       {"may_assist_ev": True}])
    def test_unset_or_on_moves_nothing(self, perms):
        for kw in (dict(solar=4000.0, home=800.0), dict(window=True),
                   dict(protection=False), dict(wants_pack=True, spendable=3.0)):
            assert decide_battery(_view(perms=perms, **kw)).intent \
                is BatteryIntent.NORMAL, kw

    def test_a_force_mode_still_outranks_it(self):
        assert decide_battery(_view(perms=_NO, mode="force_charge")).intent \
            is BatteryIntent.FORCE_CHARGE


# ─────────────────────────────────────────────────────────────────
# 5. An adapter with no limit to write says so
# ─────────────────────────────────────────────────────────────────

def _num(value, lo=0.0, hi=5000.0):
    st = Mock()
    st.state = str(value)
    st.attributes = {"min": lo, "max": hi, "unit_of_measurement": "W"}
    return st


def _hass(states):
    table = dict(states)
    hass = MagicMock()
    hass.states.get = Mock(side_effect=lambda e: table.get(e))
    hass.states.async_all = Mock(return_value=[])

    async def _call(domain, service, data=None, **kw):
        ent = str((data or {}).get("entity_id", "") or "")
        if service == "set_value" and ent in table:
            table[ent] = _num(data["value"], -2200.0 if "setpoint" in ent else 0.0)
        if service == "select_option" and ent:
            table[ent] = Mock(state=data["option"], attributes={})
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    hass.table = table
    return hass


def _sessy(hass):
    """The reporter's unit: a strategy select on ``nom`` and a signed power
    setpoint — and no discharge-limit entity, because a Sessy has none."""
    return GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.sessy_1_power_setpoint",
        "battery_strategy_control_entity": "select.sessy_1_power_strategy",
        "battery_setpoint_bidirectional": True,
        "battery_max_discharge_power": 2200,
    })


def _sessy_hass():
    return _hass({
        "number.sessy_1_power_setpoint": _num(0.0, -2200.0, 2200.0),
        "select.sessy_1_power_strategy": Mock(state="nom", attributes={
            "options": ["api", "eco", "idle", "nom", "roi"]}),
    })


_BRANDS = [
    (GenericBatteryAdapter, {}),
    (GoodWeBatteryAdapter, {}),
    (HuaweiBatteryAdapter, {}),
]


@pytest.mark.parametrize("cls,extra", _BRANDS)
@pytest.mark.asyncio
async def test_no_entity_limit_is_said_not_recorded(cls, extra):
    hass = _hass({})
    ad = cls(hass, {"battery_max_discharge_power": 5000, **extra})
    if isinstance(ad, HuaweiBatteryAdapter):
        ad._startup_orphan_checked = True
    await ad.command_limit_discharge(538.0)
    assert ad.last_intent is BatteryIntent.LIMIT_DISCHARGE
    assert ad.last_error == NO_LIMIT
    assert ad.last_discharge_limit_w == -1.0, "a limit nobody wrote was recorded"
    assert active_discharge_limit({"b1": ad}) is None
    # …and the gap stops being an error once no limit is asked for.
    for _ in range(4):                 # Huawei spends cycles on stop retries
        await ad.command_normal()
    assert ad.last_error is None


@pytest.mark.parametrize("cls,extra", _BRANDS)
@pytest.mark.asyncio
async def test_with_an_entity_the_limit_is_written_and_no_error(cls, extra):
    ent = "number.batt_max_discharge"
    hass = _hass({ent: _num(5000.0)})
    ad = cls(hass, {"battery_max_discharge_power": 5000,
                    "battery_discharge_control_entity": ent, **extra})
    if isinstance(ad, HuaweiBatteryAdapter):
        ad._startup_orphan_checked = True
    await ad.command_limit_discharge(538.0)
    assert ad.last_error is None
    assert ad.last_discharge_limit_w == 538.0
    assert float(hass.table[ent].state) == 538.0


@pytest.mark.asyncio
async def test_the_diagnose_block_carries_the_gap():
    hass = _sessy_hass()
    ad = _sessy(hass)
    await ad.command_limit_discharge(538.0)
    coord = MagicMock()
    coord._battery_adapters = {"b1": ad}
    block = battery_actuation_diag(hass, coord)["b1"]
    assert block["last_error"] == NO_LIMIT
    assert block["discharge_limit"] == {"entity": None, "last_commanded_w": -1.0}


# ─────────────────────────────────────────────────────────────────
# 6. Across cycles, through real adapters
# ─────────────────────────────────────────────────────────────────

async def _cycle(ad, **kw):
    kw.setdefault("sched", _sched("not_needed"))
    v = _view(forced=forced_ops(ad), misses=stop_misses(ad), n=1, **kw)
    d = decide_battery(v)
    await actuate_battery(d, ad)
    return d


@pytest.mark.asyncio
async def test_a_limitable_battery_is_capped_and_released():
    """A real limit entity. Cycle 1 stops (fresh adapter), cycle 2 writes the
    cap, the car leaves and the cap goes back to max."""
    ent = "number.batt_max_discharge"
    hass = _hass({ent: _num(5000.0)})
    ad = GenericBatteryAdapter(hass, {"battery_max_discharge_power": 5000,
                                      "battery_discharge_control_entity": ent})
    d1 = await _cycle(ad)
    assert d1.intent is BatteryIntent.STOP_FORCE_CHARGE
    d2 = await _cycle(ad)
    assert d2.intent is BatteryIntent.LIMIT_DISCHARGE
    # the #900 quantiser rounds the house figure UP to its step
    assert float(hass.table[ent].state) == quantise_discharge_limit_w(1076.0, -1.0)
    d3 = await _cycle(ad)                       # steady: no flap back to STOP
    assert d3.intent is BatteryIntent.LIMIT_DISCHARGE
    d4 = await _cycle(ad, ev=False)             # the car leaves
    assert d4.intent is BatteryIntent.NORMAL
    assert float(hass.table[ent].state) == 5000.0, "the cap outlived the car"


@pytest.mark.asyncio
async def test_a_car_plugged_in_after_normal_is_capped_at_once():
    """From NORMAL the last limit is the pack's MAX; the #900 lowering wait
    read the first cap as a dip and let the pack feed the car for six cycles
    (review). The wait is for a limit already in force."""
    ent = "number.batt_max_discharge"
    hass = _hass({ent: _num(5000.0)})
    ad = GenericBatteryAdapter(hass, {"battery_max_discharge_power": 5000,
                                      "battery_discharge_control_entity": ent})
    await _cycle(ad, ev=False)                  # the stop lands
    assert (await _cycle(ad, ev=False)).intent is BatteryIntent.NORMAL
    assert ad.last_discharge_limit_w == 5000.0
    assert (await _cycle(ad)).intent is BatteryIntent.LIMIT_DISCHARGE
    assert float(hass.table[ent].state) == 1250.0
    # …and inside the clamp a dip still waits (#900 unchanged).
    for _ in range(3):
        await _cycle(ad, home=500.0)
    assert float(hass.table[ent].state) == 1250.0


@pytest.mark.asyncio
async def test_the_reporters_sessy_now_says_it_cannot_cap():
    hass = _sessy_hass()
    ad = _sessy(hass)
    await _cycle(ad, perms=_NO)                 # the stop lands
    d = await _cycle(ad, perms=_NO)
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert ad.last_error == NO_LIMIT
    # Nothing was written to the setpoint to fake a cap.
    assert float(hass.table["number.sessy_1_power_setpoint"].state) == 0.0
    assert hass.table["select.sessy_1_power_strategy"].state == "nom"


@pytest.mark.asyncio
async def test_a_failed_stop_keeps_the_stop_first():
    """Honest retry (#589): a stop that did not land leaves the flag, so the
    next cycle stops again instead of moving on to the clamp."""
    from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
        ChargeCommandStatus,
    )
    ad = GenericBatteryAdapter(_hass({}), {"battery_max_discharge_power": 5000,
                                           "battery_force_charge_switch": "switch.fc"})
    ad._last_intent = BatteryIntent.FORCE_CHARGE
    ad._sem_forced_charge = True
    failed = Mock(status=ChargeCommandStatus.FAILED, message="dropped")
    ad._charge_adapter = Mock(stop_forced_charge=AsyncMock(return_value=failed))
    for _ in range(2):
        d = await _cycle(ad)
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE
    assert ad._sem_forced_charge is True
    assert ad._charge_adapter.stop_forced_charge.await_count == 2


@pytest.mark.asyncio
async def test_an_arbitrage_stop_after_a_night_charge_still_ends_the_charge():
    """Review HIGH 1. A switch-based forced charge runs; the target is met
    and the arbitrage verdict (``not_profitable``) takes the slot. Its stop
    is a DISCHARGE stop, which does not turn the switch off. The charge must
    still be stopped — and only then does the clamp run."""
    from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
        ChargeCommandStatus,
    )
    ad = GenericBatteryAdapter(_hass({}), {
        "battery_max_discharge_power": 5000,
        "battery_force_charge_switch": "switch.fc",
        "battery_target_soc_entity": "number.target"})
    started = Mock(status=ChargeCommandStatus.CHARGING, message="")
    stopped = Mock(status=ChargeCommandStatus.IDLE, message="")
    ad._charge_adapter = Mock(start_forced_charge=AsyncMock(return_value=started),
                              stop_forced_charge=AsyncMock(return_value=stopped))
    d = await _cycle(ad, sched=_sched("scheduled"),
                     gate=_gate(covered=True, in_block=True))
    assert d.intent is BatteryIntent.FORCE_CHARGE
    assert ad._sem_forced_charge is True
    arb = _sched("not_profitable", from_arbitrage=True)
    seen = [(await _cycle(ad, sched=arb)).intent for _ in range(4)]
    assert seen == [BatteryIntent.STOP_FORCE_DISCHARGE,
                    BatteryIntent.STOP_FORCE_CHARGE,
                    BatteryIntent.LIMIT_DISCHARGE,
                    BatteryIntent.LIMIT_DISCHARGE], seen
    assert ad._charge_adapter.stop_forced_charge.await_count == 1


def _deye():
    """Review HIGH 2: a real Deye whose sell is a work-mode select. Its sell
    and its stop answer a bool and record no intent."""
    opts = ["Selling First", "Zero Export To Load", "Zero Export To CT"]
    hass = MagicMock()
    st = MagicMock()
    st.state = "Zero Export To Load"
    st.attributes = {"options": opts}
    hass.states.get.return_value = st
    hass.services.async_call = AsyncMock()
    ad = DeyeBatteryAdapter(hass, {
        "battery_platform": "deye",
        "battery_force_discharge_control_entity": "number.deye_export",
        "deye_system_work_mode_control": True,
        "deye_system_work_mode_entity": "select.deye_system_work_mode",
        "deye_system_work_mode_selling_option": "Selling First",
        "deye_system_work_mode_zero_load_option": "Zero Export To Load",
        "deye_system_work_mode_zero_ct_option": "Zero Export To CT",
    })
    ad._observer_mode = False
    ad._actuation_enabled = True

    async def _write(entity, value, domain):
        st.state = value
        return True
    ad._write_and_verify = AsyncMock(side_effect=_write)
    return ad, st


@pytest.mark.asyncio
async def test_a_deye_sale_is_ended_when_nothing_asks_for_it():
    ad, st = _deye()
    assert ad.supports_forced_discharge
    sell = _sched("discharging_arbitrage", floor_soc=0.0, discharge_power_w=3000.0)
    v = _view(ev=False, sched=sell, forced=forced_ops(ad), misses=stop_misses(ad), n=1,
              soc=80.0, mode="allow_arbitrage")
    v = type(v)(**{**v.__dict__, "arbitrage_sell": (True, 3000.0),
                   "config": {**v.config, "battery_grid_arbitrage_enabled": True}})
    d = decide_battery(v)
    assert d.intent is BatteryIntent.FORCE_DISCHARGE
    await actuate_battery(d, ad)
    assert st.state == "Selling First"
    assert ad._sem_forced_discharge is True, "a sale that landed was not noted"
    # The sell block closes with no scheduler verdict at all: NORMAL before
    # the fix, which leaves Deye's work mode alone — the pack sells on.
    d = await _cycle(ad, sched=None, ev=False)
    assert d.intent is BatteryIntent.STOP_FORCE_DISCHARGE
    assert st.state == "Zero Export To Load"
    assert ad._sem_forced_discharge is False
    assert (await _cycle(ad, sched=None, ev=False)).intent is BatteryIntent.NORMAL


@pytest.mark.asyncio
async def test_a_failed_start_notes_nothing():
    from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
        ChargeCommandStatus,
    )
    ad = GenericBatteryAdapter(_hass({}), {
        "battery_max_discharge_power": 5000,
        "battery_force_charge_switch": "switch.fc",
        "battery_target_soc_entity": "number.target"})
    failed = Mock(status=ChargeCommandStatus.FAILED, message="refused")
    ad._charge_adapter = Mock(start_forced_charge=AsyncMock(return_value=failed))
    d = await _cycle(ad, sched=_sched("scheduled"),
                     gate=_gate(covered=True, in_block=True))
    assert d.intent is BatteryIntent.FORCE_CHARGE
    assert ad._sem_forced_charge is None, "a charge that never started was noted"


@pytest.mark.asyncio
async def test_a_sale_whose_stop_is_refused_still_gets_the_cap_out():
    """Review round 2, the MEDIUM: a manual sale lands, then the setpoint
    register refuses every write, the mode goes back to auto and a car is
    plugged in. The stop is retried, and the cap still reaches the limit
    entity — on develop LIMIT wrote it at once."""
    ent = "number.batt_max_discharge"
    sp = "number.batt_setpoint"
    hass = _hass({ent: _num(5000.0), sp: _num(0.0, -2200.0, 2200.0)})
    ad = GenericBatteryAdapter(hass, {
        "battery_max_discharge_power": 5000,
        "battery_discharge_control_entity": ent,
        "battery_force_discharge_control_entity": sp})
    d = await _cycle(ad, sched=None, mode="force_discharge", ev=False)
    assert d.intent is BatteryIntent.FORCE_DISCHARGE
    assert ad._sem_forced_discharge is True
    ad._zero_setpoint = AsyncMock(return_value=False)      # the register refuses
    seen = [(await _cycle(ad, sched=None)).intent for _ in range(STOP_FIRST_TRIES + 4)]
    assert seen[:STOP_FIRST_TRIES] == [BatteryIntent.STOP_FORCE_DISCHARGE] * STOP_FIRST_TRIES
    assert BatteryIntent.LIMIT_DISCHARGE in seen
    assert float(hass.table[ent].state) == 1250.0, "the cap never went out"
    # …and the stop keeps being tried in between.
    assert seen[STOP_FIRST_TRIES:].count(BatteryIntent.STOP_FORCE_DISCHARGE) >= 2
    assert ad._sem_forced_discharge is True
    # The register comes back: the stop lands and the cap is all that remains.
    ad._zero_setpoint = AsyncMock(return_value=True)
    for _ in range(3):
        d = await _cycle(ad, sched=None)
    assert ad._sem_forced_discharge is False
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
