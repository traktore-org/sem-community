"""#1402 — "Start now" at night: the charger state says what SEM does.

At night a charger in "Solar + cheapest hours" waits for its cheap hours.
"Start now" on the plan card is a one-off ``force`` override: it gives
``decide()`` the mode ``always_max``, and SEM sends the full current. The
charger state still said "Tariff mode - Waiting for cheap price window":
the night state is picked from the SAVED mode's plan before ``decide()``
runs, and the loop then kept any night state over the decision.

The same split (the override reaches ``decide()`` only) had two siblings:

* the night gate asked the saved mode, so "Start now" on a Solar-only
  charger did nothing while another charger charged at night — the gate
  left it out of the loop and the police pass kept it stopped;
* "Skip tonight" stopped the charge, and the state still said "Night
  charging active" or "waiting for cheap".

These tests run the real cycle (``CycleRig``): real devices, real loop,
real ``decide()``; only the night clock and the night plan are set.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts.states import (
    NIGHT_STATES,
    ChargingState as CS,
)
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_night_targets import (
    night_state_after_decision,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    NightChargePlan,
)

from .cycle_rig import CycleRig

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 15.0,
    "battery_reserve_soc": 20,
}


def _charger(cid="zap", mode="solar_plus_cheap", **over):
    c = {
        "id": cid, "name": cid, "ev_min_current": 6, "ev_max_current": 16,
        "ev_phases": 3, "ev_voltage": 230,
        "ev_current_control_entity": f"number.{cid}_current",
        "ev_connected_sensor": f"binary_sensor.{cid}_connected",
        "ev_power_sensor": "sensor.ev",
        "charge_mode": mode, "ev_target_type": "kwh", "daily_ev_target": 20,
    }
    c.update(over)
    return c


def _night_rig(chargers, *, wait=True):
    """A night with a plan: ``solar_plus_cheap`` waits for its cheap hours
    when ``wait``; every other mode's plan says charge now."""
    states = {"sensor.solar": 0, "sensor.grid": -500, "sensor.batt": 0,
              "sensor.soc": 50, "sensor.ev": 0}
    for c in chargers:
        states[f"binary_sensor.{c['id']}_connected"] = "on"
        states[f"number.{c['id']}_current"] = 0
    rig = CycleRig(config=dict(WIRED), chargers=chargers, states=states)
    rig.coord.time_manager.is_night_mode = lambda: True
    rig.coord._compute_night_plan = (
        lambda cfg, target, energy=None, night_over=False: NightChargePlan(
            should_wait_for_cheap=(
                wait and cfg.get("charge_mode") == "solar_plus_cheap"),
            reason="test plan"))
    return rig


def _override(rig, cid, action):
    now = dt_util.now()
    rig.coord._plan_overrides = po.set_override(
        rig.coord._plan_overrides, cid, action, now + timedelta(hours=6), now)


def _amps_sent(rig, cid):
    return [c[2].get("value") for c in rig.calls
            if c[2].get("entity_id") == f"number.{cid}_current"]


@pytest.mark.asyncio
class TestStartNowAtNight:

    async def test_the_reported_case_says_charging(self):
        """The #1399 diagnostics: state ``tariff_waiting_for_cheap`` beside
        "plan override — forced to charge". Now the state says charging,
        on the charger's own state and on the fleet state."""
        rig = _night_rig([_charger()])
        res = await rig.tick()
        assert res["charger_zap_charging_state"] == CS.TARIFF_WAITING_FOR_CHEAP
        _override(rig, "zap", "force")
        res = await rig.tick()
        assert "plan override — forced to charge" in res["charging_strategy"]
        assert 16 in _amps_sent(rig, "zap")
        assert res["charger_zap_charging_state"] == CS.NIGHT_CHARGING_ACTIVE
        assert str(res["charging_state"]) == CS.NIGHT_CHARGING_ACTIVE

    async def test_back_to_plan_waits_again(self):
        rig = _night_rig([_charger()])
        _override(rig, "zap", "force")
        await rig.tick()
        rig.coord._plan_overrides = po.clear_override(
            rig.coord._plan_overrides, "zap")
        res = await rig.tick()
        assert res["charger_zap_charging_state"] == CS.TARIFF_WAITING_FOR_CHEAP

    async def test_with_the_night_target_met_it_still_says_charging(self):
        """Target met, so the night state was "Target reached" — while
        Start now sends the full current."""
        rig = _night_rig([_charger(daily_ev_target=0)])
        res = await rig.tick()
        assert res["charger_zap_charging_state"] == CS.NIGHT_TARGET_REACHED
        _override(rig, "zap", "force")
        res = await rig.tick()
        assert 16 in _amps_sent(rig, "zap")
        assert res["charger_zap_charging_state"] == CS.NIGHT_CHARGING_ACTIVE

    async def test_a_solar_only_charger_starts_beside_a_night_charger(self):
        """The gate sibling: on the old code this sent nothing and the
        charger had no state at all — the gate left it out of the loop."""
        rig = _night_rig([_charger(),
                          _charger("sol", mode="solar_only", daily_ev_target=0)])
        res = await rig.tick()
        assert _amps_sent(rig, "sol") == []
        assert "charger_sol_charging_state" not in res
        _override(rig, "sol", "force")
        res = await rig.tick()
        assert _amps_sent(rig, "sol") == [16]
        assert res["charger_sol_charging_state"] == CS.NIGHT_CHARGING_ACTIVE
        # it takes no part in the night plan: no plan row, no notice
        assert "sol" not in rig.coord._night_plan_per_charger
        # the other charger keeps waiting for its cheap hours
        assert res["charger_zap_charging_state"] == CS.TARIFF_WAITING_FOR_CHEAP
        assert _amps_sent(rig, "zap") == []

    @pytest.mark.parametrize("sol_first", [True, False])
    async def test_either_order_and_no_floor_key(self, sol_first):
        """Review find: with the Solar-only charger FIRST in order, the loop
        read a ``pc_target`` no line had set and the cycle failed on every
        turn. With it second, it read the charger before's target. Here the
        Solar-only charger has no ``daily_ev_target`` key at all (the usual
        case), in both orders."""
        sol = _charger("sol", mode="solar_only", priority=1 if sol_first else 9)
        sol.pop("daily_ev_target")
        zap = _charger(priority=5)
        rig = _night_rig([zap, sol])
        _override(rig, "sol", "force")
        res = await rig.tick()
        assert _amps_sent(rig, "sol") == [16]
        assert res["charger_sol_charging_state"] == CS.NIGHT_CHARGING_ACTIVE
        assert res["charger_zap_charging_state"] == CS.TARIFF_WAITING_FOR_CHEAP

    @pytest.mark.parametrize("sol_first", [True, False])
    async def test_a_forced_charger_that_does_not_charge_is_not_charging(
            self, sol_first):
        """Car unplugged: nothing is sent, so the state must not say
        charging — on the old draft it took the other charger's target."""
        sol = _charger("sol", mode="solar_only", priority=1 if sol_first else 9)
        sol.pop("daily_ev_target")
        rig = _night_rig([_charger(priority=5), sol])
        rig.hass.states.set("binary_sensor.sol_connected", "off")
        _override(rig, "sol", "force")
        res = await rig.tick()
        assert _amps_sent(rig, "sol") == []
        assert res.get("charger_sol_charging_state") == CS.NIGHT_DISABLED

    async def test_an_off_charger_stays_hands_off(self):
        """Off outranks a one-off, as for batteries: nothing is sent."""
        rig = _night_rig([_charger(), _charger("off1", mode="off")])
        _override(rig, "off1", "force")
        res = await rig.tick()
        assert _amps_sent(rig, "off1") == []
        assert "charger_off1_charging_state" not in res, (
            "the gate leaves an off charger out of the loop")

    async def test_saved_always_max_with_the_target_met_says_charging(self):
        """Same rule without an override: always_max ignores the plan."""
        rig = _night_rig([_charger(mode="always_max", daily_ev_target=0)])
        res = await rig.tick()
        assert 16 in _amps_sent(rig, "zap")
        assert res["charger_zap_charging_state"] == CS.NIGHT_CHARGING_ACTIVE


@pytest.mark.asyncio
class TestSkipTonight:

    async def test_a_skipped_night_charge_says_disabled(self):
        rig = _night_rig([_charger()], wait=False)
        res = await rig.tick()
        assert res["charger_zap_charging_state"] == CS.NIGHT_CHARGING_ACTIVE
        _override(rig, "zap", "skip")
        res = await rig.tick()
        assert "plan override — stopped" in res["charging_strategy"]
        assert res["charger_zap_charging_state"] == CS.NIGHT_DISABLED

    async def test_a_skipped_wait_does_not_promise_cheap_hours(self):
        rig = _night_rig([_charger()])
        _override(rig, "zap", "skip")
        res = await rig.tick()
        assert res["charger_zap_charging_state"] == CS.NIGHT_DISABLED

    async def test_a_skip_with_the_target_met_still_says_target_reached(self):
        rig = _night_rig([_charger(daily_ev_target=0)])
        _override(rig, "zap", "skip")
        res = await rig.tick()
        assert res["charger_zap_charging_state"] == CS.NIGHT_TARGET_REACHED


class TestTheRule:
    """``night_state_after_decision`` on its own."""

    @pytest.mark.parametrize("state", sorted(NIGHT_STATES))
    def test_always_max_charging_is_night_charging(self, state):
        assert night_state_after_decision(
            state, mode="always_max", charging=True, skipped=False,
        ) == CS.NIGHT_CHARGING_ACTIVE

    @pytest.mark.parametrize("state", sorted(NIGHT_STATES))
    def test_always_max_not_charging_keeps_the_night_state(self, state):
        """Car full, peak stop, car gone: SEM is not charging, so the
        plan's state is not replaced by "charging"."""
        assert night_state_after_decision(
            state, mode="always_max", charging=False, skipped=False) == state

    @pytest.mark.parametrize("mode", ["solar_plus_cheap", "min_plus_solar",
                                      "solar_only"])
    @pytest.mark.parametrize("state", sorted(NIGHT_STATES))
    @pytest.mark.parametrize("charging", [True, False])
    def test_a_plan_mode_keeps_the_plans_state(self, mode, state, charging):
        assert night_state_after_decision(
            state, mode=mode, charging=charging, skipped=False) == state

    @pytest.mark.parametrize("state", [CS.NIGHT_CHARGING_ACTIVE,
                                       CS.TARIFF_WAITING_FOR_CHEAP,
                                       CS.NIGHT_WAITING_FOR_WINDOW])
    def test_a_skip_turns_a_promised_charge_into_disabled(self, state):
        assert night_state_after_decision(
            state, mode="solar_plus_cheap", charging=False, skipped=True,
        ) == CS.NIGHT_DISABLED

    @pytest.mark.parametrize("state", [CS.NIGHT_TARGET_REACHED, CS.NIGHT_IDLE,
                                       CS.NIGHT_DISABLED, CS.NIGHT_TIME_EXPIRED])
    def test_a_skip_keeps_a_state_that_promises_nothing(self, state):
        assert night_state_after_decision(
            state, mode="solar_plus_cheap", charging=False, skipped=True,
        ) == state

    def test_a_skip_that_still_charges_says_charging(self):
        assert night_state_after_decision(
            CS.NIGHT_CHARGING_ACTIVE, mode="solar_plus_cheap", charging=True,
            skipped=True) == CS.NIGHT_CHARGING_ACTIVE

    @pytest.mark.parametrize("state", [CS.SOLAR_IDLE, CS.SOLAR_CHARGING_ACTIVE,
                                       CS.SOLAR_SUPER_CHARGING,
                                       CS.SOLAR_FULL_POWER])
    @pytest.mark.parametrize("skipped", [True, False])
    def test_a_day_state_passes_through(self, state, skipped):
        assert night_state_after_decision(
            state, mode="always_max", charging=True, skipped=skipped) == state

    def test_skips_charger_reads_only_an_active_skip(self):
        now = dt_util.now()
        later = now + timedelta(hours=1)
        assert po.skips_charger(po.set_override({}, "a", "skip", later, now),
                                "a", now)
        assert not po.skips_charger(po.set_override({}, "a", "force", later, now),
                                    "a", now)
        assert not po.skips_charger(po.set_override({}, "b", "skip", later, now),
                                    "a", now)
        assert not po.skips_charger(po.set_override({}, "a", "skip", later, now),
                                    "a", later + timedelta(seconds=1))


class TestTheGate:
    """``_night_gate_skips`` on its own."""

    def _coord(self, overrides=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.hass = None
        coord.config = {}
        coord._plan_overrides = overrides or {}
        return coord

    def _forced(self, cid):
        now = dt_util.now()
        return po.set_override({}, cid, "force", now + timedelta(hours=1), now)

    def test_solar_only_without_a_floor_is_left_out(self):
        coord = self._coord()
        cfg = _charger("s", mode="solar_only", daily_ev_target=0)
        assert coord._night_gate_skips("s", cfg, dt_util.now())

    def test_start_now_lets_it_in(self):
        coord = self._coord(self._forced("s"))
        cfg = _charger("s", mode="solar_only", daily_ev_target=0)
        assert not coord._night_gate_skips("s", cfg, dt_util.now())

    def test_start_now_on_another_charger_does_not(self):
        coord = self._coord(self._forced("other"))
        cfg = _charger("s", mode="solar_only", daily_ev_target=0)
        assert coord._night_gate_skips("s", cfg, dt_util.now())

    def test_an_expired_start_now_does_not(self):
        coord = self._coord(self._forced("s"))
        cfg = _charger("s", mode="solar_only", daily_ev_target=0)
        assert coord._night_gate_skips(
            "s", cfg, dt_util.now() + timedelta(hours=2))

    def test_off_stays_out_with_start_now(self):
        coord = self._coord(self._forced("o"))
        assert coord._night_gate_skips("o", _charger("o", mode="off"),
                                       dt_util.now())

    def test_a_night_mode_is_never_left_out(self):
        coord = self._coord()
        assert not coord._night_gate_skips(
            "z", _charger("z", mode="solar_plus_cheap"), dt_util.now())

    def test_a_vpp_boost_does_not_hide_start_now(self):
        """A grid boost turns the coordinator's mode into always_max; the
        gate still sees the user's Solar-only mode and the override."""
        coord = self._coord(self._forced("s"))
        coord._vpp_ev_override = "boost"
        cfg = _charger("s", mode="solar_only", daily_ev_target=0)
        assert not coord._night_gate_skips("s", cfg, dt_util.now())

    def test_a_bad_override_store_leaves_it_out(self):
        coord = self._coord({"s": "not an override"})
        cfg = _charger("s", mode="solar_only", daily_ev_target=0)
        assert coord._night_gate_skips("s", cfg, dt_util.now())


def _cycle_tree():
    return ast.parse(textwrap.dedent(
        inspect.getsource(SEMCoordinator._async_update_data)))


def _kw_name(call, name):
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Name):
            return kw.value.id
    return None


def _calls_named(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == name) or (
                    isinstance(f, ast.Attribute) and f.attr == name):
                out.append(node)
    return out


def test_the_state_and_decide_read_one_mode():
    """The state is said from the mode ``decide()`` got, not from the saved
    one: both calls pass the same variable as ``mode=``."""
    tree = _cycle_tree()
    # the per-charger loop's view (the legacy ``elif self._ev_device``
    # branch passes ``charger_cfg={}`` and is reached only with no charger
    # in ``_ev_devices``, where ``_ev_device`` is set from)
    view = [c for c in _calls_named(tree, "build_charger_view")
            if _kw_name(c, "charger_cfg") == "charger_cfg"]
    state = _calls_named(tree, "night_state_after_decision")
    assert len(view) == 1 and len(state) == 1
    assert _kw_name(view[0], "mode") is not None
    assert _kw_name(state[0], "mode") == _kw_name(view[0], "mode")
    # …and it runs after the override and the safety gate have changed
    # the decision, so the state says what is sent.
    for later_than in ("apply_to_charger_decision", "filter_charger_decision",
                       "_phase_switch_tick"):
        # the loop's own call is the first one; the legacy branch follows
        first = min(c.lineno for c in _calls_named(tree, later_than))
        assert view[0].lineno < first < state[0].lineno, later_than


def test_the_night_gate_asks_the_override():
    """The gate is ``_night_gate_skips``; no direct mode check takes its
    place in the cycle, where it would read the saved mode only."""
    tree = _cycle_tree()
    assert len(_calls_named(tree, "_night_gate_skips")) == 1
    gate_src = inspect.getsource(SEMCoordinator._night_gate_skips)
    assert "charger_mode_for" in gate_src
