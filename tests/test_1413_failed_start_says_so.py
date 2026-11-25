"""#1413 — the Plan page said the battery charged after a start that failed.

Two readers claimed a charge SEM had not started:

* The decision log. ``actuate_battery`` wrote the FORCE_CHARGE row BEFORE
  ``command_force_charge``, so a start the adapter refused still logged
  "The plan charges the battery from the grid now". A charge that ended
  by itself (the mode went back, the permit did not turn on) kept that row
  too. The sale had the same order (class 192: a write's "no" is read
  before anything claims the result).
* The plan. ``_charge_command_share`` left a pack out only when the
  inverter refused the charge. A charge SEM gave up because the hold would
  not write the charge target (``_target_not_set``: the reserve on a
  Powerwall) did not count, so the next plan showed the block again.

Now the row is written after the command, from its answer: the watts sent,
or "has not started" with no watts. A charge target SEM could not set is
remembered like a refusal, and the plan names it.
"""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    actuate_battery as actuate_mod,
)
from custom_components.solar_energy_management.coordinator import (
    reason_codes as RC,
)
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)

from .test_1367_plan_only_sendable_charge import _plan
from .test_1377_powerwall_charge import (
    MODE, PERMIT, RESERVE, _adapter, _Hass, _stop, _Store,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (  # noqa: E402
    GenericChargeAdapter,
)


@pytest.fixture(autouse=True)
def _no_cloud_wait(monkeypatch):
    """(#1377) the waits for a cloud read are pinned in
    test_1377_cloud_read_lag.py; here every read counts at once"""
    monkeypatch.setattr(GenericChargeAdapter, "SHOW_WITHIN_S", 0.0)
    monkeypatch.setattr(GenericChargeAdapter, "AWAY_FOR_S", 0.0)


class _BadStore(_Store):
    """A hold record that cannot be read: the hold writes no target."""

    async def async_load(self):
        raise OSError("disk")


class _FirstSaveFails(_Store):
    """A hold record whose first save fails, then works."""

    def __init__(self):
        super().__init__()
        self.fail = True

    async def async_save(self, data):
        if self.fail:
            self.fail = False
            raise OSError("disk full")
        await super().async_save(data)


class _Clock:
    """The actuator's clock, moved by hand."""

    def __init__(self, monkeypatch):
        self.t = 1000.0
        monkeypatch.setattr(actuate_mod, "_now", lambda: self.t)

    def wait(self, s):
        self.t += s


WAIT = actuate_mod.NOT_STARTED_AFTER_S


def _sc():
    sc = SurplusController(MagicMock())
    sc.hass.bus.async_fire = MagicMock()
    return sc


def _plan_charge():
    """The decision ``decide_battery`` makes inside a plan block."""
    return BatteryDecision(
        battery_id="b1", intent=BatteryIntent.FORCE_CHARGE, target_soc=100.0,
        charge_power_w=5000.0, duration_min=240, reason="plan block",
        reason_code=RC.BATTERY_PLAN_CHARGE)


def _sale():
    return BatteryDecision(
        battery_id="b1", intent=BatteryIntent.FORCE_DISCHARGE,
        discharge_power_w=3000.0, floor_soc=20.0, reason="arbitrage",
        reason_code=RC.BATTERY_SELL)


def _rows(sc):
    return [(r["new"], r["reason_code"]) for r in sc.decision_log.records()]


NOT_STARTED = ("force_charge", RC.BATTERY_CHARGE_NOT_STARTED)
CHARGING = ("force_charge 5000 W", RC.BATTERY_PLAN_CHARGE)


# ── the row says what came of the start (a Powerwall-shaped setup) ────

class TestTheRowFollowsTheAnswer:
    async def test_the_report_a_reserve_the_hold_will_not_write(self):
        """Mode already "autonomous", the hold cannot write the reserve:
        nothing starts, and the row says so, never "the plan charges"."""
        sc = _sc()
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _BadStore())
        for _ in range(4):
            await actuate_battery(_plan_charge(), a, controller=sc)
        assert hass.calls == []
        assert _rows(sc) == [NOT_STARTED], "one row, and it says not started"
        row = sc.decision_log.records()[0]
        assert RESERVE in row["text"], "the adapter's own words, for the hover"

    async def test_twin_a_charge_that_starts_logs_the_plan_charge(self):
        sc = _sc()
        a = _adapter(_Hass(), _Store(), _Store())
        for _ in range(3):
            await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [CHARGING]

    async def test_a_mode_that_goes_back_by_itself_ends_the_charging_row(self):
        sc = _sc()
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_plan_charge(), a, controller=sc)
        await actuate_battery(_plan_charge(), a, controller=sc)   # seen on
        hass.put(MODE, "self_consumption")          # the inverter's own logic
        for _ in range(3):
            await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [CHARGING, NOT_STARTED]
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_a_mode_that_refuses_ends_with_not_started(self):
        sc = _sc()
        hass = _Hass()
        hass.refuse_mode = True
        a = _adapter(hass, _Store(), _Store())
        for _ in range(6):
            await actuate_battery(_plan_charge(), a, controller=sc)
        assert a.charge_refused is True
        assert _rows(sc)[-1] == NOT_STARTED

    async def test_an_unreadable_reserve_says_not_started_then_charging(
            self, monkeypatch):
        """Asked again each cycle (not given up): the row waits out the
        window, then says so; the charge that follows is logged."""
        clock, sc = _Clock(monkeypatch), _sc()
        hass = _Hass(mode="autonomous", reserve="unavailable")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT - 10)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [], "inside the window: maybe a wait"
        clock.wait(10)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [NOT_STARTED]
        assert RESERVE in sc.decision_log.records()[0]["text"]
        hass.put(RESERVE, "0")
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [NOT_STARTED, CHARGING]

    async def test_watch_only_still_records_the_would_row(self):
        sc = _sc()
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _BadStore())
        await actuate_battery(_plan_charge(), a, observer=True, controller=sc)
        rows = sc.decision_log.records()
        assert [(r["new"], r["reason_code"], r["observer"]) for r in rows] == [
            ("force_charge 5000 W", RC.BATTERY_PLAN_CHARGE, True)]
        assert hass.calls == []


async def _async_none(*a, **k):
    return None


class _Stub:
    """An adapter that answers the way the brand adapters do: an intent it
    holds and an error it names, set by the command itself."""

    supports_forced_charge = True
    supports_forced_discharge = True

    def __init__(self, *, intent=None, error=None, ret=None):
        self.last_intent, self.last_error = None, None
        self._then = (intent, error, ret)

    async def command_force_charge(self, *a):
        self.last_intent, self.last_error, ret = self._then
        return ret

    async def command_force_discharge(self, *a):
        self.last_intent, self.last_error, ret = self._then
        return ret


class TestEveryAnswerShape:
    async def test_a_mode_still_on_its_way_writes_no_row(self):
        """No error yet, no charge yet (a hold select that has not shown
        its option): nothing happened, so nothing is claimed."""
        sc = _sc()
        await actuate_battery(_plan_charge(), _Stub(), controller=sc)
        assert _rows(sc) == []

    async def test_a_failed_resend_while_the_charge_stands_writes_no_row(self):
        sc = _sc()
        a = _Stub(intent=BatteryIntent.FORCE_CHARGE)
        await actuate_battery(_plan_charge(), a, controller=sc)
        a._then = (BatteryIntent.FORCE_CHARGE, "setpoint write failed", None)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [CHARGING], "the earlier start still stands"

    async def test_a_true_answer_is_a_start(self):
        sc = _sc()
        await actuate_battery(_plan_charge(), _Stub(ret=True), controller=sc)
        assert _rows(sc) == [CHARGING]

    async def test_a_brand_error_is_not_started_once_the_window_passed(
            self, monkeypatch):
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(intent=BatteryIntent.NORMAL, error="start_forced_charge failed")
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == []
        clock.wait(WAIT)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [NOT_STARTED]
        assert sc.decision_log.records()[0]["text"] == "start_forced_charge failed"

    async def test_an_error_left_by_another_command_is_not_the_text(
            self, monkeypatch):
        """A discharge limit failed earlier; the start then neither sets
        nor clears ``last_error`` (a mode still on its way)."""
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub()
        a.last_error = "limit write failed"
        a._then = (None, "limit write failed", None)
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT)
        await actuate_battery(_plan_charge(), a, controller=sc)
        rows = sc.decision_log.records()
        assert _rows(sc) == [NOT_STARTED]
        assert "limit" not in rows[0]["text"]

    async def test_the_window_starts_again_after_another_intent(
            self, monkeypatch):
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(error="waiting for select.mode to read charge")
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT - 10)
        a.command_normal = _async_none
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.NORMAL), a, controller=sc)
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT - 10)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert NOT_STARTED not in _rows(sc)


class TestTheSaleFollowsTheSameRule:
    async def test_a_sale_that_fails_says_not_started(self, monkeypatch):
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(error="power strategy reads nom — discharge setpoint withheld")
        for _ in range(3):
            await actuate_battery(_sale(), a, controller=sc)
            clock.wait(WAIT)
        assert _rows(sc) == [("force_discharge", RC.BATTERY_SELL_NOT_STARTED)]

    async def test_a_false_answer_with_an_error_is_not_started(self, monkeypatch):
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(error="Deye write failed", ret=False)
        await actuate_battery(_sale(), a, controller=sc)
        clock.wait(WAIT)
        await actuate_battery(_sale(), a, controller=sc)
        assert _rows(sc) == [("force_discharge", RC.BATTERY_SELL_NOT_STARTED)]

    async def test_a_failed_reassert_between_two_true_answers_writes_nothing(
            self, monkeypatch):
        """A Deye sale answers True or False and records no intent: one
        False between two Trues is no row churn."""
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(ret=True)
        await actuate_battery(_sale(), a, controller=sc)
        a._then = (None, "Deye write failed", False)
        await actuate_battery(_sale(), a, controller=sc)
        clock.wait(30)
        a._then = (None, None, True)
        await actuate_battery(_sale(), a, controller=sc)
        assert _rows(sc) == [("force_discharge 3000 W", RC.BATTERY_SELL)]

    async def test_twin_a_sale_that_goes_out(self):
        sc = _sc()
        for a in (_Stub(intent=BatteryIntent.FORCE_DISCHARGE), _Stub(ret=True)):
            sc = _sc()
            await actuate_battery(_sale(), a, controller=sc)
            assert _rows(sc) == [("force_discharge 3000 W", RC.BATTERY_SELL)]


# ── planned waits on real adapters write no "not started" row ─────────

class TestAPlannedWaitIsNotAFailure:
    """Review (M1, M2): a start that lands a cycle or two later names an
    error meanwhile ("waiting for …", "setpoint withheld"), or leaves one
    from another command. Neither is a failed start."""

    async def test_a_direction_select_that_shows_a_cycle_later(self, monkeypatch):
        from unittest.mock import AsyncMock, Mock, patch

        from .test_809_869_setpoint_models import DIR, SCALE, SP, _state
        _Clock(monkeypatch)
        for decision, start_dir, want in (
                (_sale(), "charge", "force_discharge 3000 W"),
                (_plan_charge(), "discharge", "force_charge 5000 W")):
            st = {SP: _state(0, lo=0, hi=5000), DIR: _state(start_dir)}
            hass = MagicMock()
            hass.states.get = Mock(side_effect=lambda e, st=st: st.get(e))

            async def call(domain, service, data=None, st=st, **kw):
                if service == "select_option":
                    st[DIR] = _state(data["option"])
            hass.services.async_call = AsyncMock(side_effect=call)
            a = GenericBatteryAdapter(hass, {
                "battery_force_discharge_control_entity": SP,
                "battery_max_discharge_power": 5000,
                "battery_max_charge_power": 5000,
                "battery_setpoint_model": "direction_select",
                "battery_power_direction_entity": DIR, "battery_id": "b1"})
            sc = _sc()
            with patch(SCALE, return_value=1.0):
                await actuate_battery(decision, a, controller=sc)
                assert a.last_error, "the first cycle waits and says so"
                for _ in range(2):
                    await actuate_battery(decision, a, controller=sc)
            assert [r["new"] for r in sc.decision_log.records()] == [want]

    async def test_a_power_strategy_that_shows_late(self, monkeypatch):
        from .test_978_strategy_readback import CFG, _rig
        clock = _Clock(monkeypatch)
        for decision, want in ((_plan_charge(), "force_charge 2200 W"),
                               (_sale(), "force_discharge 1700 W")):
            hass, _st = _rig(lag_reads=4)
            a = GenericBatteryAdapter(hass, dict(CFG, battery_id="b1"))
            sc = _sc()
            for _ in range(4):
                await actuate_battery(decision, a, controller=sc)
                clock.wait(10)
            news = [r["new"] for r in sc.decision_log.records()]
            assert news and news[-1].startswith(want.split(" ")[0])
            assert not any(r["reason_code"] in (
                RC.BATTERY_CHARGE_NOT_STARTED, RC.BATTERY_SELL_NOT_STARTED)
                for r in sc.decision_log.records())

    async def test_a_hold_mode_settling_after_a_failed_limit(self, monkeypatch):
        from . import test_1362_charge_sets_the_mode as T
        clock, sc = _Clock(monkeypatch), _sc()
        hass = T._Hass()
        a = T._adapter(hass)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
            discharge_limit_w=1500.0, reason="ev clamp"), a, controller=sc)
        left = a.last_error
        hass.refuse.add(T.MODE)                  # the mode has not shown yet
        charge = BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_CHARGE, target_soc=90.0,
            charge_power_w=3000.0, duration_min=120, reason="plan block",
            reason_code=RC.BATTERY_PLAN_CHARGE)
        await actuate_battery(charge, a, controller=sc)
        clock.wait(20)
        hass.refuse.discard(T.MODE)
        hass.put(T.MODE, T.UTILITY)
        await actuate_battery(charge, a, controller=sc)
        rows = [r for r in sc.decision_log.records() if r["new"].startswith("force")]
        assert left, "the limit left an error behind"
        assert [(r["new"], r["reason_code"]) for r in rows] == [
            ("force_charge 3000 W", RC.BATTERY_PLAN_CHARGE)]

    def test_the_window_covers_the_hold_modes_own_wait(self):
        """The hold re-sends once after ``SHOW_WITHIN_S`` and refuses after
        another; each step may end a cycle late, and a cycle is up to 60 s."""
        from custom_components.solar_energy_management.coordinator.battery_adapters import (
            hold_select,
        )
        assert WAIT >= 2 * (hold_select.SHOW_WITHIN_S + 60.0)

    async def test_an_old_refusal_does_not_mark_a_new_starts_wait(
            self, monkeypatch):
        """Review: ``charge_refused`` is kept for 24 h. A new start whose
        first cycle only waits (no error of its own) is not "not started"."""
        _Clock(monkeypatch)
        sc = _sc()
        a = _Stub()
        a.charge_refused = True
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == []
        a._then = (None, "the select did not take it", None)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [NOT_STARTED], "its own 'no' with the give-up: at once"

    async def test_a_start_that_went_out_starts_the_window_again(
            self, monkeypatch):
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(error="waiting for select.mode to read charge")
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT - 10)
        a._then = (BatteryIntent.FORCE_CHARGE, None, None)
        await actuate_battery(_plan_charge(), a, controller=sc)
        a._then = (None, "start_forced_charge failed", None)
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT - 10)
        await actuate_battery(_plan_charge(), a, controller=sc)
        assert _rows(sc) == [CHARGING]

    async def test_a_switch_from_charge_to_sale_starts_the_window_again(
            self, monkeypatch):
        clock, sc = _Clock(monkeypatch), _sc()
        a = _Stub(error="waiting")
        await actuate_battery(_plan_charge(), a, controller=sc)
        clock.wait(WAIT - 10)
        await actuate_battery(_sale(), a, controller=sc)
        clock.wait(WAIT - 10)
        await actuate_battery(_sale(), a, controller=sc)
        assert _rows(sc) == []

    async def test_a_charge_refusal_does_not_end_a_sale_at_once(
            self, monkeypatch):
        _Clock(monkeypatch)
        sc = _sc()
        a = _Stub(error="Deye write failed", ret=False)
        a.charge_refused = True
        await actuate_battery(_sale(), a, controller=sc)
        assert _rows(sc) == []


# ── the plan: a charge target SEM could not set counts like a refusal ─

class TestTheAdapterRemembersTheTarget:
    async def test_a_target_the_hold_will_not_write_is_remembered(self):
        a = _adapter(_Hass(mode="autonomous", reserve="0"), _Store(), _BadStore())
        assert a.charge_target_unset is False
        await actuate_battery(_plan_charge(), a)
        assert a.charge_target_unset is True
        assert a.charge_refused is False, "the inverter refused nothing"

    async def test_the_mode_write_path_too(self):
        a = _adapter(_Hass(), _Store(), _BadStore())
        await actuate_battery(_plan_charge(), a)
        assert a.charge_target_unset is True

    async def test_the_plan_still_knows_after_the_block_ends(self):
        a = _adapter(_Hass(mode="autonomous", reserve="0"), _Store(), _BadStore())
        await actuate_battery(_plan_charge(), a)
        await actuate_battery(_stop(), a)
        assert a.charge_target_unset is True

    async def test_a_target_written_later_clears_it(self):
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _FirstSaveFails())
        await actuate_battery(_plan_charge(), a)
        assert a.charge_target_unset is True
        await actuate_battery(_stop(), a)              # the next block
        await actuate_battery(_plan_charge(), a)
        assert float(hass.read(RESERVE)) == 100
        assert hass.read(PERMIT) == "on"
        assert a.charge_target_unset is False

    async def test_the_memory_ends(self):
        a = _adapter(_Hass(mode="autonomous", reserve="0"), _Store(), _BadStore())
        await actuate_battery(_plan_charge(), a)
        ca = a._charge_adapter
        ca._sel_unset_at -= ca.REFUSAL_MEMORY_S + 1
        assert a.charge_target_unset is False

    async def test_the_switch_path_keeps_its_own_rule(self):
        """Without the select pair the switch starts the charge and the
        target is a limit: a target the hold will not write starts the
        charge anyway, and nothing leaves the plan."""
        hass = _Hass(reserve="0")
        a = GenericBatteryAdapter(hass, {
            "battery_force_charge_switch": PERMIT,
            "battery_target_soc_entity": RESERVE, "battery_id": "b1",
            "charge_target_hold": ChargeTargetHold(
                hass, _BadStore(), configured=(RESERVE,))})
        await actuate_battery(_plan_charge(), a)
        assert hass.read(PERMIT) == "on", "the charge started"
        assert float(hass.read(RESERVE)) == 0, "the hold wrote nothing"
        assert a.charge_target_unset is False


def _pack(**kw):
    return SimpleNamespace(charge_command_configured=True, **kw)


class TestThePlanLeavesItOut:
    def test_the_share(self):
        coord = SimpleNamespace(_live_battery_adapters=lambda: [
            ("b1", _pack(charge_refused=False, charge_target_unset=True))])
        share, unable = SEMCoordinator._charge_command_share(coord, None)
        assert share == 0 and unable == ["b1"]
        assert coord._charge_unset_ids == {"b1"}
        assert coord._charge_refused_ids == set()

    def test_a_refusal_keeps_its_own_word(self):
        coord = SimpleNamespace(_live_battery_adapters=lambda: [
            ("b1", _pack(charge_refused=True, charge_target_unset=True))])
        SEMCoordinator._charge_command_share(coord, None)
        assert coord._charge_refused_ids == {"b1"}
        assert coord._charge_unset_ids == set()

    def test_the_plan_names_why(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": _pack(charge_target_unset=True)})
        assert not any(r["id"] == "battery" for r in plan.get("demands", []))
        assert {"id": "battery", "why": "charge_target_unset",
                "label": None} in plan["not_scheduled"]

    def test_two_packs_only_the_one_that_can_charge_is_planned(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": _pack(), "b2": _pack(charge_target_unset=True)},
                     caps={"b1": 10.0, "b2": 5.0}, deficit=6.0)
        row = next(r for r in plan["demands"] if r["id"] == "battery")
        assert abs(row["needed_kwh"] - 4.0) < 0.01         # 10 of 15 kWh
        assert {"id": "battery:b2", "why": "charge_target_unset",
                "label": None} in plan["not_scheduled"]

    def test_twin_a_pack_that_can_charge_is_planned(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": _pack(charge_target_unset=False)})
        assert any(r["id"] == "battery" for r in plan.get("demands", []))

    def test_the_words_exist_in_every_language(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        d = json.loads((root / "dashboard" / "translations.json").read_text())
        assert len(d) == 16
        key = "energy_plan_why_charge_target_unset"
        en = d["en"][key]
        for lang, table in d.items():
            assert table.get(key, "").strip(), lang
            assert lang == "en" or table[key] != en, f"{lang}: English left"


# ── the guard: no forced start is logged before its command ──────────

_FORCED = {"FORCE_CHARGE": "command_force_charge",
           "FORCE_DISCHARGE": "command_force_discharge"}


def _forced_branch_faults(func: ast.AST) -> list:
    """In each ``if decision.intent is BatteryIntent.FORCE_*`` branch: no
    bare ``record_battery`` call, and ``_record_forced_start`` comes after
    the command it reads the answer of."""
    faults = []
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare)
                and isinstance(test.comparators[0], ast.Attribute)
                and test.comparators[0].attr in _FORCED):
            continue
        name = test.comparators[0].attr
        calls = [c for stmt in node.body for c in ast.walk(stmt)
                 if isinstance(c, ast.Call)]

        def _named(c, n):
            f = c.func
            return (isinstance(f, ast.Name) and f.id == n) or (
                isinstance(f, ast.Attribute) and f.attr == n)

        if any(_named(c, "record_battery") for c in calls):
            faults.append(f"{name}: record_battery in the branch")
        cmd = [c.lineno for c in calls if _named(c, _FORCED[name])]
        rec = [c.lineno for c in calls if _named(c, "_record_forced_start")]
        if not cmd or not rec or min(rec) < max(cmd):
            faults.append(f"{name}: the row is not written after the command")
    return faults


class TestGuard:
    def test_the_dispatch_logs_each_forced_start_after_its_command(self):
        tree = ast.parse(inspect.getsource(actuate_mod))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_dispatch_battery")
        assert _forced_branch_faults(fn) == []
        seen = {n.test.comparators[0].attr for n in ast.walk(fn)
                if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.comparators[0], ast.Attribute)
                and n.test.comparators[0].attr in _FORCED}
        assert seen == set(_FORCED), "both forced branches were checked"

    def test_the_guard_catches_the_old_order(self):
        old = textwrap.dedent("""
            async def _dispatch_battery(decision, adapter):
                if decision.intent is BatteryIntent.FORCE_CHARGE:
                    record_battery(_log, decision, value_w=1)
                    ret = await adapter.command_force_charge(1, 2, 3)
                if decision.intent is BatteryIntent.FORCE_DISCHARGE:
                    _record_forced_start(_log, decision, adapter, None, 1, "x")
                    ret = await adapter.command_force_discharge(1, 2)
        """)
        fn = ast.parse(old).body[0]
        faults = _forced_branch_faults(fn)
        assert any("FORCE_CHARGE: record_battery" in f for f in faults)
        assert any("FORCE_DISCHARGE: the row is not written after" in f
                   for f in faults)
