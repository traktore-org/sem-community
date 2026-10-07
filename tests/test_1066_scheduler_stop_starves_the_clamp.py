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
from custom_components.solar_energy_management.coordinator.decide_battery import (
    _SCHEDULER_STOP_STATES, decide_battery, forced_op_may_run,
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


def _view(*, sched=None, gate=None, may_run=True, ev=True, solar=0.0,
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
        forced_op_may_run=may_run,
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

    def _evening(self, may_run):
        return _view(sched=_sched("not_needed"), may_run=may_run,
                     perms={"may_assist_ev": False})

    def test_once_the_stop_has_landed_the_packs_are_capped_at_the_house(self):
        d = decide_battery(self._evening(may_run=False))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(1076.0 / 2)
        assert "may not feed the car" in d.reason

    def test_while_a_forced_op_may_run_the_stop_still_goes_first(self):
        d = decide_battery(self._evening(may_run=True))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    def test_the_old_code_path_is_what_the_reporter_saw(self):
        """The default view keeps the old precedence — that IS the line in
        the report. Pins that the default is not what fixed it."""
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
        bare = decide_battery(_view(sched=None, may_run=False, **kw))
        with_sched = decide_battery(_view(sched=sched, gate=gate,
                                          may_run=False, **kw))
        assert (with_sched.intent, with_sched.discharge_limit_w,
                with_sched.reason) == (bare.intent, bare.discharge_limit_w,
                                       bare.reason), kw
        seen.add(bare.intent)
    # Not vacuous: the grid reaches every protection outcome.
    assert {BatteryIntent.LIMIT_DISCHARGE, BatteryIntent.NORMAL} <= seen


@pytest.mark.parametrize("sched,gate", _STOP_VERDICTS)
def test_while_a_forced_op_may_run_every_verdict_still_stops(sched, gate):
    d = decide_battery(_view(sched=sched, gate=gate, may_run=True))
    assert d.intent in (BatteryIntent.STOP_FORCE_CHARGE,
                        BatteryIntent.STOP_FORCE_DISCHARGE)


def test_a_scheduled_charge_in_its_block_still_wins_over_the_clamp():
    d = decide_battery(_view(sched=_sched("scheduled"),
                             gate=_gate(covered=True, in_block=True),
                             may_run=False))
    assert d.intent is BatteryIntent.FORCE_CHARGE


# ─────────────────────────────────────────────────────────────────
# 3. forced_op_may_run reads what LANDED
# ─────────────────────────────────────────────────────────────────

class _Stub:
    def __init__(self, last, **flags):
        self.last_intent = last
        for k, v in flags.items():
            setattr(self, k, v)


class TestForcedOpMayRun:
    def test_no_adapter_keeps_the_old_precedence(self):
        assert forced_op_may_run(None) is True

    def test_a_fresh_adapter_may_have_one_from_a_prior_instance(self):
        assert forced_op_may_run(_Stub(None)) is True

    @pytest.mark.parametrize("last", [BatteryIntent.FORCE_CHARGE,
                                      BatteryIntent.FORCE_DISCHARGE])
    def test_a_forced_op_runs(self, last):
        assert forced_op_may_run(_Stub(last)) is True

    @pytest.mark.parametrize("last", [
        BatteryIntent.STOP_FORCE_CHARGE, BatteryIntent.STOP_FORCE_DISCHARGE,
        BatteryIntent.NORMAL, BatteryIntent.LIMIT_DISCHARGE, BatteryIntent.OFF])
    def test_after_any_other_landed_command_nothing_runs(self, last):
        assert forced_op_may_run(_Stub(last)) is False

    @pytest.mark.parametrize("flag", ["_forcible_charging", "_forcible_discharging"])
    def test_huaweis_own_flags_are_asked_too(self, flag):
        assert forced_op_may_run(_Stub(BatteryIntent.NORMAL, **{flag: True})) is True

    def test_a_stand_in_we_cannot_read_keeps_the_stop(self):
        assert forced_op_may_run(MagicMock()) is True

    def test_the_coordinator_hands_it_to_the_view(self):
        """One producer of BatteryView; it must pass the adapter's answer."""
        tree = ast.parse((ROOT / "coordinator/coordinator.py").read_text(
            encoding="utf-8"))
        sites = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "BatteryView"]
        assert sites
        for call in sites:
            kw = {k.arg: k.value for k in call.keywords}
            assert "forced_op_may_run" in kw
            v = kw["forced_op_may_run"]
            assert (isinstance(v, ast.Call)
                    and getattr(v.func, "id", None) == "forced_op_may_run"
                    and [getattr(a, "id", None) for a in v.args] == ["adapter"])


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
    if hasattr(ad, "_orphan_guard"):
        ad._orphan_cleared = True
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
    if hasattr(ad, "_orphan_guard"):
        ad._orphan_cleared = True
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
    v = _view(sched=_sched("not_needed"), may_run=forced_op_may_run(ad),
              n=1, **kw)
    d = decide_battery(v)
    await actuate_battery(d, ad)
    return d


@pytest.mark.asyncio
async def test_a_limitable_battery_is_capped_and_released():
    """Huawei-shaped: a real limit entity. Cycle 1 stops (fresh adapter),
    cycle 2 writes the cap, the car leaves and the cap goes back to max."""
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
    assert 1076.0 <= float(hass.table[ent].state) < 5000.0
    d3 = await _cycle(ad)                       # steady: no flap back to STOP
    assert d3.intent is BatteryIntent.LIMIT_DISCHARGE
    d4 = await _cycle(ad, ev=False)             # the car leaves
    assert d4.intent is BatteryIntent.NORMAL
    assert float(hass.table[ent].state) == 5000.0, "the cap outlived the car"


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
    """Honest retry (#589): a stop that did not land leaves the intent, so the
    next cycle stops again instead of moving on to the clamp."""
    hass = _hass({})
    ad = GenericBatteryAdapter(hass, {"battery_max_discharge_power": 5000,
                                      "battery_force_charge_switch": "switch.fc"})
    ad._last_intent = BatteryIntent.FORCE_CHARGE
    from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
        ChargeCommandStatus,
    )
    failed = Mock(status=ChargeCommandStatus.FAILED, message="dropped")
    ad._charge_adapter = Mock(stop_forced_charge=AsyncMock(return_value=failed))
    for _ in range(2):
        d = await _cycle(ad)
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE
    assert ad.last_intent is BatteryIntent.FORCE_CHARGE
