"""Desired-state loads refactor — Phase 1: the pure decision model.

Spec: docs/superpowers/specs/2026-07-22-desired-state-surplus-loads-design.md.
These pin ``compute_load_intent`` (the MANAGEMENT layer's pure precedence walk)
and the ``has_runtime_deficit`` device property. No wiring into the controller
yet — this phase is additive and cannot change live behaviour.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent, LoadIntent, reconcile_load,
)
from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, DeviceControlMode, DeviceState,
)


def _dev(**kw):
    """A minimal device stand-in for the pure intent function (getattr-based)."""
    d = SimpleNamespace(
        control_mode=kw.get("control_mode", DeviceControlMode.SURPLUS),
        is_active=kw.get("is_active", False),
        daily_max_runtime_reached=kw.get("daily_max_runtime_reached", False),
        daily_targets_met=kw.get("daily_targets_met", False),
        stop_condition_met=kw.get("stop_condition_met", False),
        rated_power=kw.get("rated_power", 1000.0),
        min_power_threshold=kw.get("min_power_threshold", 1000.0),
        has_runtime_deficit=kw.get("has_runtime_deficit", False),
        battery_eligible_overnight=kw.get("battery_eligible_overnight", False),
        top_up_policy=kw.get("top_up_policy", "solar_only"),
    )
    d.get_current_consumption = lambda: kw.get("consumption", 0.0)
    return d


# ── Not SEM-driven ────────────────────────────────────────────────────────
def test_off_mode_is_left_alone():
    on = compute_load_intent(_dev(control_mode=DeviceControlMode.OFF, is_active=True,
                                  consumption=900), remaining_surplus_w=5000)
    assert on.on is True and on.source is None          # SEM doesn't touch it
    off = compute_load_intent(_dev(control_mode=DeviceControlMode.OFF, is_active=False),
                              remaining_surplus_w=5000)
    assert off.on is False and off.source is None

def test_peak_only_user_managed_but_sheds():
    keep = compute_load_intent(_dev(control_mode=DeviceControlMode.PEAK_ONLY, is_active=True,
                                    consumption=900), remaining_surplus_w=0)
    assert keep.on is True and keep.source is None
    shed = compute_load_intent(_dev(control_mode=DeviceControlMode.PEAK_ONLY, is_active=True),
                               remaining_surplus_w=0, is_shed_target=True)
    assert shed.on is False


# ── Stop gates (precedence over any run reason) ───────────────────────────
def test_peak_shed_wins():
    i = compute_load_intent(_dev(is_active=True), remaining_surplus_w=5000, is_shed_target=True)
    assert i.on is False and "peak" in i.reason

def test_done_gates_stop_even_with_surplus():
    for gate in ("daily_max_runtime_reached", "daily_targets_met", "stop_condition_met"):
        i = compute_load_intent(_dev(is_active=True, **{gate: True}), remaining_surplus_w=5000)
        assert i.on is False, gate

def test_cap_beats_deficit_sources():
    # capped device with a deficit + battery eligible → still OFF (cap wins)
    i = compute_load_intent(_dev(is_active=True, daily_max_runtime_reached=True,
                                 has_runtime_deficit=True, battery_eligible_overnight=True),
                            remaining_surplus_w=0, soc_above_reserve=True)
    assert i.on is False


# ── Sources ───────────────────────────────────────────────────────────────
def test_solar_source():
    i = compute_load_intent(_dev(min_power_threshold=800, rated_power=800),
                            remaining_surplus_w=1000)
    assert i.on is True and i.source == "solar" and i.power_w == 800

def test_tier1_assist_lifts_below_threshold():
    # raw surplus 400 < 800 threshold, but +500 battery headroom → on via tier1
    i = compute_load_intent(_dev(min_power_threshold=800),
                            remaining_surplus_w=400, tier1_headroom_w=500)
    assert i.on is True and i.source == "tier1_battery"

def test_tier2_overnight_battery():
    i = compute_load_intent(_dev(has_runtime_deficit=True, battery_eligible_overnight=True),
                            remaining_surplus_w=0, soc_above_reserve=True)
    assert i.on is True and i.source == "tier2_battery"

def test_tier2_blocked_below_reserve():
    i = compute_load_intent(_dev(has_runtime_deficit=True, battery_eligible_overnight=True),
                            remaining_surplus_w=0, soc_above_reserve=False)
    assert i.on is False                                 # hard reserve floor

def test_cheap_grid_source():
    i = compute_load_intent(_dev(has_runtime_deficit=True, top_up_policy="cheap_hours"),
                            remaining_surplus_w=0, price_is_cheap=True)
    assert i.on is True and i.source == "cheap_grid"

def test_cheap_grid_needs_cheap_window():
    i = compute_load_intent(_dev(has_runtime_deficit=True, top_up_policy="cheap_hours"),
                            remaining_surplus_w=0, price_is_cheap=False)
    assert i.on is False

def test_no_source_off():
    i = compute_load_intent(_dev(), remaining_surplus_w=0)
    assert i.on is False and i.source is None


# ── peak_freeze: block new, keep running ──────────────────────────────────
def test_peak_freeze_blocks_new_but_keeps_running():
    blocked = compute_load_intent(_dev(is_active=False, min_power_threshold=800),
                                  remaining_surplus_w=1000, peak_freeze=True)
    assert blocked.on is False                           # don't add load under peak risk
    kept = compute_load_intent(_dev(is_active=True, min_power_threshold=800),
                               remaining_surplus_w=1000, peak_freeze=True)
    assert kept.on is True                               # running load stays


# ── has_runtime_deficit device property + needs_offpeak refactor ──────────
def _switch():
    return SwitchDevice(hass=MagicMock(), device_id="p", name="P", rated_power=800,
                        entity_id="switch.p")

def test_has_runtime_deficit_independent_of_active():
    d = _switch()
    d.control_mode = DeviceControlMode.SURPLUS
    d.daily_min_runtime_sec = 3600
    assert d.has_runtime_deficit is True                 # deficit, idle
    d._status.state = DeviceState.ACTIVE
    assert d.has_runtime_deficit is True                 # STILL true while running
    assert d.needs_offpeak_activation is False           # ...but activation view is not

def test_deficit_false_when_met_or_capped():
    d = _switch()
    d.daily_min_runtime_sec = 3600
    d._daily_runtime_accumulated_sec = 3600              # met
    assert d.has_runtime_deficit is False
    d._daily_runtime_accumulated_sec = 1800
    d.daily_max_runtime_sec = 1800                       # capped
    assert d.has_runtime_deficit is False


# ── Phase 2: reconcile_load (the single actuator) ─────────────────────────
def _rec_dev(**kw):
    d = MagicMock()
    d.is_active = kw.get("is_active", False)
    d.can_activate = MagicMock(return_value=kw.get("can_activate", True))
    d.can_deactivate = MagicMock(return_value=kw.get("can_deactivate", True))
    d.get_current_consumption = MagicMock(return_value=kw.get("consumption", 800.0))
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    async def _act(p): d.is_active = True; return kw.get("consumption", 800.0)
    async def _deact(): d.is_active = False
    async def _adj(p): return kw.get("consumption", 800.0)
    d.activate = AsyncMock(side_effect=_act)
    d.deactivate = AsyncMock(side_effect=_deact)
    d.adjust_power = AsyncMock(side_effect=_adj)
    return d


@pytest.mark.asyncio
async def test_reconcile_activates_idle_load():
    d = _rec_dev(is_active=False)
    await reconcile_load(d, LoadIntent(True, 800, "solar", "x"))
    d.activate.assert_awaited()
    d.record_activated.assert_called()
    assert d._batt_overnight_forced is False and d._offpeak_forced is False


@pytest.mark.asyncio
async def test_reconcile_respects_min_off_anti_cycle():
    d = _rec_dev(is_active=False, can_activate=False)
    consumed = await reconcile_load(d, LoadIntent(True, 800, "solar", "x"))
    d.activate.assert_not_called()
    assert consumed == 0.0


@pytest.mark.asyncio
async def test_reconcile_stops_a_running_load():
    d = _rec_dev(is_active=True)
    d._batt_overnight_forced = True     # was running off battery
    await reconcile_load(d, LoadIntent(False, 0, None, "cap"))
    d.deactivate.assert_awaited()
    d.record_deactivated.assert_called()
    assert d._batt_overnight_forced is False   # markers cleared on stop


@pytest.mark.asyncio
async def test_reconcile_off_held_by_min_on():
    d = _rec_dev(is_active=True, can_deactivate=False)
    await reconcile_load(d, LoadIntent(False, 0, None, "cap"))
    d.deactivate.assert_not_called()    # min-on anti-flicker holds it on


@pytest.mark.asyncio
async def test_reconcile_adjusts_active_load():
    d = _rec_dev(is_active=True)
    await reconcile_load(d, LoadIntent(True, 900, "solar", "x"))
    d.adjust_power.assert_awaited()
    d.deactivate.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_markers_derive_from_source():
    for src, batt, grid in [("tier2_battery", True, False),
                            ("cheap_grid", False, True),
                            ("solar", False, False)]:
        d = _rec_dev(is_active=False)
        await reconcile_load(d, LoadIntent(True, 800, src, "x"))
        assert d._batt_overnight_forced is batt, src
        assert d._offpeak_forced is grid, src


@pytest.mark.asyncio
async def test_reconcile_noop_when_off_and_idle():
    d = _rec_dev(is_active=False)
    consumed = await reconcile_load(d, LoadIntent(False, 0, None, "x"))
    d.activate.assert_not_called()
    d.deactivate.assert_not_called()
    assert consumed == 0.0
