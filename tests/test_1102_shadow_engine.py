"""(#1102) The three-layer load engine runs beside the imperative passes.

Every real install switches loads with the passes in ``SurplusController.update()``;
the layers only switch in observer mode. Before they may lead, every difference
must be seen. These pin that the comparison:

* changes NOTHING the passes do (actions and device state, over many cycles),
* is pure (a dry walk leaves controller and devices as they were),
* catches the known differences (D1 comfort banking cut by the force expiry,
  D2 the per-load threshold against the −100 W band),
* stays quiet for a Legionella own run (both engines keep it),
* keeps its sensor summary small and its log bounded.
"""
from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.engine_shadow import (
    EngineShadow, SUMMARY_MAX_BYTES,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import PlanVerdict
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    LoadIntent, SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.tests.test_desired_state import _PDev, _SCENARIOS


class _LogDev(_PDev):
    """A parity device that also writes down every actuation it receives."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []
        for k in ("comfort_state", "runs_without_surplus"):
            if k in kw:
                setattr(self, k, kw[k])

    async def activate(self, target):
        self.calls.append(("on", round(float(target))))
        return await super().activate(target)

    async def deactivate(self):
        self.calls.append(("off",))
        return await super().deactivate()

    async def adjust_power(self, target):
        self.calls.append(("adjust", round(float(target))))
        return await super().adjust_power(target)


def _state(dev) -> dict:
    """What the passes leave on a device, comparable across runs."""
    return {k: repr(v) for k, v in vars(dev).items()
            if k not in ("calls", "status", "_controller")
            and not isinstance(v, MagicMock)}


async def _cycles(specs, kws, *, shadow: bool):
    sc = SurplusController(MagicMock())
    devs = [_LogDev(**s) for s in specs]
    for d in devs:
        sc.register_device(d)
    if not shadow:
        def _off(*a, **k):
            raise RuntimeError("shadow disabled for the baseline run")
        real = sc._desired_intents
        sc._desired_intents = lambda *a, **k: _off() if k.get("dry") else real(*a, **k)
    for kw in kws:
        await sc.update(**kw)
    return sc, devs


def _sequence(kw):
    """Four cycles around the scenario's own inputs: as given, more sun, none, as given."""
    p = float(kw.get("available_power_w", 0.0))
    return [kw, {**kw, "available_power_w": p + 2500.0},
            {**kw, "available_power_w": 0.0}, kw]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(_SCENARIOS))
async def test_the_shadow_changes_nothing_the_passes_do(name):
    specs, kw = _SCENARIOS[name]
    seq = _sequence(kw)
    with_s, dev_s = await _cycles(specs, seq, shadow=True)
    without, dev_n = await _cycles(specs, seq, shadow=False)
    assert [d.calls for d in dev_s] == [d.calls for d in dev_n], name
    assert [_state(d) for d in dev_s] == [_state(d) for d in dev_n], name
    assert with_s._tier1_budget_left == without._tier1_budget_left


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_dry_walk_leaves_everything_as_it_was():
    sc = SurplusController(MagicMock())
    # the layer-1 Off branch releases an adopted load (writes three flags) …
    adopted = _LogDev("adopted", 1, control_mode=DeviceControlMode.OFF, is_active=True, draw=900)
    adopted._sem_owned = True
    adopted._offpeak_forced = True
    # … and layer 2 books what the battery paid for an assisted load
    assisted = _LogDev("assisted", 2, min_power=800, battery_assist_enabled=True)
    for d in (adopted, assisted):
        sc.register_device(d)
    await sc.update(available_power_w=300.0, battery_soc=90, battery_buffer_soc=70,
                    battery_assist_budget_w=3000.0)
    sc._tier1_budget_left = 3000.0
    kw = dict(remaining_surplus=300.0, reclaim_w=0.0, battery_priority=None,
              price_level="normal", peak_freeze=False, peak_shed=False, peak_shed_all=False)
    before = [copy.deepcopy(_state(d)) for d in (adopted, assisted)]
    budget = sc._tier1_budget_left

    dry = sc._desired_intents(sc.get_devices_sorted(), dry=True, **kw)
    assert [_state(d) for d in (adopted, assisted)] == before
    assert sc._tier1_budget_left == budget
    assert dry["assisted"].on and dry["assisted"].source == "tier1_battery"

    # the same walk NOT dry does write — so the check above has teeth
    sc._desired_intents(sc.get_devices_sorted(), **kw)
    assert adopted._sem_owned is False
    assert sc._tier1_budget_left < budget


@pytest.mark.unit
@pytest.mark.asyncio
async def test_d1_comfort_banking_is_cut_by_the_old_force_expiry():
    """#1102: a 'Solar only' boiler with a willing band and an open planned
    block. The old banking pass starts it and marks it as a cheap-hours run;
    next cycle the old expiry stops it ('cheap-hours disabled by user'). The
    layers keep it for the whole block. The record says so."""
    sc = SurplusController(MagicMock())
    boiler = _LogDev("boiler", 1, min_power=3000, rated_power=3000,
                     top_up_policy="solar_only", comfort_state="willing")
    sc.register_device(boiler)
    # (#1102) the heater ladder plans only up to Keep at: the tank reads 45 °C
    # against Keep at 50, so the planned block is a real goal
    boiler._comfort_reading = lambda: 45.0
    boiler._comfort_thresholds_c = lambda: (50.0, 5.0, 36.0)
    boiler._comfort_direction = lambda: "heat"
    block = {"boiler": PlanVerdict(in_block=True, comfort_in_block=True, reason="planned block")}
    await sc.update(available_power_w=0.0, price_level="normal", plan_windows=block)
    assert boiler.calls == [("on", 3000)]          # banking pass started it
    boiler._can_act = False                        # the minimum off time after a stop
    await sc.update(available_power_w=0.0, price_level="normal", plan_windows=block)
    assert boiler.calls[-1] == ("off",)            # the old expiry cut it

    rec = [r for r in sc.engine_shadow.records() if r["device_id"] == "boiler"]
    assert rec and rec[-1]["event"] == "start" and rec[-1]["kinds"] == ["on_off"]
    assert rec[-1]["old"]["on"] is False and rec[-1]["new"]["on"] is True
    assert "planned block" in rec[-1]["new"]["reason"]
    assert sc.engine_shadow.summary()["by_kind"] == {"on_off": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_d2_one_threshold_per_load_against_the_old_band():
    """Two running 800 W loads, the sun now carries 1550 W. The old pass
    stops a load only below −100 W in total, so both stay; the layers give
    each load its own threshold, so the second stops."""
    sc = SurplusController(MagicMock())
    sc.regulation_offset = 0.0
    a = _LogDev("a", 1, min_power=800, is_active=True, draw=800)
    b = _LogDev("b", 2, min_power=800, is_active=True, draw=800)
    for d in (a, b):
        sc.register_device(d)
    await sc.update(available_power_w=1550.0)
    assert a.is_active and b.is_active               # old engine kept both
    diffs = {r["device_id"]: r for r in sc.engine_shadow.records()}
    assert set(diffs) == {"b"}
    assert diffs["b"]["old"]["on"] is True and diffs["b"]["new"]["on"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_legionella_own_run_is_no_difference():
    sc = SurplusController(MagicMock())
    tank = _LogDev("tank", 1, min_power=3000, rated_power=3000, is_active=True,
                   draw=3000, runs_without_surplus=True)
    sc.register_device(tank)
    for _ in range(3):
        await sc.update(available_power_w=0.0, price_level="normal")
    assert tank.is_active
    assert sc.engine_shadow.records() == []


@pytest.mark.unit
def test_changes_only_and_a_bounded_small_summary():
    shadow = EngineShadow()
    intent_on = LoadIntent(True, 3000.0, "cheap_grid", "x" * 300, "load_plan_window")
    devs = []
    for i in range(300):
        d = MagicMock()
        d.device_id = f"dev_{i}"
        d.name = "A long device name " * 5
        d.is_active = False
        d.locked_by_operator = False
        d._phase_hold = None
        d.daily_max_runtime_reached = False
        d._check_dependencies = lambda: True
        d._external_off_until = None
        d.min_off_seconds = 0
        d._last_deactivated = None
        d.activation_delay_seconds = 0
        devs.append(d)
    intents = {d.device_id: intent_on for d in devs}
    shadow.compare(intents, devs, was_on={})
    shadow.compare(intents, devs, was_on={})          # unchanged: nothing new
    assert len(shadow.records()) == 200               # the ring holds 200
    s = shadow.summary()
    assert s["disagreements"] == 300 and s["open"] == 300
    assert len(json.dumps(s, default=str)) <= SUMMARY_MAX_BYTES
    assert "cycles" not in s                          # never a per-cycle change
    shadow.compare({}, devs, was_on={})               # every difference ends
    assert shadow.summary()["open"] == 0
    assert shadow.records()[-1]["event"] == "end"
