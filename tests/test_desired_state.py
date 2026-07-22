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

def test_peak_only_user_managed_not_shed():
    keep = compute_load_intent(_dev(control_mode=DeviceControlMode.PEAK_ONLY, is_active=True,
                                    consumption=900), remaining_surplus_w=0)
    assert keep.on is True and keep.source is None
    # (ruflo M1) the surplus controller never sheds peak_only loads — the load
    # manager owns their shedding via shed_priority (matches the old peak pass).
    still = compute_load_intent(_dev(control_mode=DeviceControlMode.PEAK_ONLY, is_active=True,
                                     consumption=900), remaining_surplus_w=0, is_shed_target=True)
    assert still.on is True


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


# ─────────────────────────────────────────────────────────────────
# OBSERVER mode — the layer-3 intercept. Layers 1+2 run for real;
# ``reconcile_load(observer=True)`` may ONLY log, never actuate or
# mutate device state. This is the safety invariant for HA-TEST
# (shared real hardware): a WOULD-log, and nothing else.
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observer_would_activate_never_actuates(caplog):
    d = _rec_dev(is_active=False, consumption=800.0)
    import logging
    with caplog.at_level(logging.INFO):
        consumed = await reconcile_load(
            d, LoadIntent(True, 800, "solar", "surplus>threshold"), observer=True)
    d.activate.assert_not_called()
    d.record_activated.assert_not_called()
    d.reset_surplus_timer.assert_not_called()   # no state mutation at all
    assert consumed == 0.0                       # idle load draws nothing
    assert d.is_active is False                  # belief untouched
    assert "WOULD ACTIVATE" in caplog.text


@pytest.mark.asyncio
async def test_observer_would_deactivate_never_actuates(caplog):
    d = _rec_dev(is_active=True, consumption=800.0)
    import logging
    with caplog.at_level(logging.INFO):
        consumed = await reconcile_load(
            d, LoadIntent(False, 0, None, "cap reached"), observer=True)
    d.deactivate.assert_not_called()
    d.record_deactivated.assert_not_called()
    assert consumed == 800.0                     # still drawing (real state)
    assert d.is_active is True                    # belief untouched
    assert "WOULD DEACTIVATE" in caplog.text


@pytest.mark.asyncio
async def test_observer_would_adjust_never_actuates(caplog):
    d = _rec_dev(is_active=True, consumption=600.0)
    import logging
    with caplog.at_level(logging.INFO):
        consumed = await reconcile_load(
            d, LoadIntent(True, 900, "solar", "more surplus"), observer=True)
    d.adjust_power.assert_not_called()
    assert consumed == 600.0
    assert "WOULD ADJUST" in caplog.text


@pytest.mark.asyncio
async def test_observer_idle_emits_no_command(caplog):
    d = _rec_dev(is_active=False)
    import logging
    with caplog.at_level(logging.INFO):
        await reconcile_load(d, LoadIntent(False, 0, None, "no surplus"), observer=True)
    d.activate.assert_not_called()
    d.deactivate.assert_not_called()
    d.reset_surplus_timer.assert_not_called()
    assert "WOULD" not in caplog.text            # nothing to command → nothing logged


@pytest.mark.asyncio
async def test_observer_never_touches_markers():
    d = _rec_dev(is_active=True)
    d._batt_overnight_forced = True
    d._offpeak_forced = True
    await reconcile_load(d, LoadIntent(False, 0, None, "cap"), observer=True)
    # markers reflect real actuation only; observer must not clear them
    assert d._batt_overnight_forced is True
    assert d._offpeak_forced is True


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


# ── Phase 3: parity harness (new desired-state path == old imperative passes) ─
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.const import LoadManagementState


class _PDev:
    """A switch-like device that behaves under BOTH the imperative passes and the
    desired-state path (is_active follows activate/deactivate), for parity."""
    def __init__(self, device_id, priority, **kw):
        self.device_id = device_id
        self.name = device_id
        self.priority = priority
        self.control_mode = kw.get("control_mode", DeviceControlMode.SURPLUS)
        self.is_enabled = True
        self.managed_externally = False
        self.device_type = MagicMock(value="switch")
        self.min_power_threshold = float(kw.get("min_power", 800.0))
        self.rated_power = float(kw.get("rated_power", self.min_power_threshold))
        self.daily_max_runtime_reached = kw.get("daily_max_runtime_reached", False)
        self.daily_targets_met = kw.get("daily_targets_met", False)
        self.stop_condition_met = kw.get("stop_condition_met", False)
        self.has_runtime_deficit = kw.get("has_runtime_deficit", False)
        self.remaining_daily_runtime_sec = 1800 if self.has_runtime_deficit else 0
        self.battery_eligible_overnight = kw.get("battery_eligible_overnight", False)
        self.battery_assist_enabled = kw.get("battery_assist_enabled", False)
        self.top_up_policy = kw.get("top_up_policy", "solar_only")
        self._offpeak_forced = kw.get("_offpeak_forced", False)
        self._offpeak_forced_date = None
        self._batt_overnight_forced = kw.get("_batt_overnight_forced", False)
        self._batt_overnight_forced_date = None
        self._active = kw.get("is_active", False)
        self._draw = float(kw.get("draw", self.rated_power))
        self._can_act = kw.get("can_activate", True)
        self._can_deact = kw.get("can_deactivate", True)
        self.status = MagicMock()
        self.status.allocated_power_w = 0.0

    @property
    def is_active(self):
        return self._active

    @property
    def needs_offpeak_activation(self):
        return self.has_runtime_deficit and not self._active

    def can_activate(self):
        return self._can_act
    def can_deactivate(self):
        return self._can_deact
    def get_current_consumption(self):
        return self._draw if self._active else 0.0
    def record_activated(self):
        pass
    def record_deactivated(self):
        pass
    def reset_surplus_timer(self):
        pass
    async def activate(self, target):
        self._active = True
        return self._draw
    async def deactivate(self):
        self._active = False
    async def adjust_power(self, target):
        return self._draw


# id → (list of device kwargs, update() kwargs)
_SCENARIOS = {
    "abundant_surplus_two_idle": (
        [dict(device_id="a", priority=1, min_power=800),
         dict(device_id="b", priority=2, min_power=800)],
        dict(available_power_w=5000.0),
    ),
    "low_surplus_one_fits_one_not": (
        [dict(device_id="a", priority=1, min_power=800),
         dict(device_id="b", priority=2, min_power=800)],
        dict(available_power_w=1050.0),          # ~1000 distributable → only a
    ),
    "running_load_cap_reached": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True,
              daily_max_runtime_reached=True)],
        dict(available_power_w=5000.0),
    ),
    "running_load_target_met": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True,
              daily_targets_met=True)],
        dict(available_power_w=5000.0),
    ),
    "overnight_battery_activates": (
        [dict(device_id="a", priority=1, min_power=800, has_runtime_deficit=True,
              battery_eligible_overnight=True)],
        dict(available_power_w=0.0, price_level="normal", battery_soc=90,
             battery_reserve_soc=20),
    ),
    "overnight_disabled_stops": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True,
              _batt_overnight_forced=True, battery_eligible_overnight=False)],
        dict(available_power_w=0.0, price_level="normal", battery_soc=90,
             battery_reserve_soc=20),
    ),
    "cheap_grid_activates": (
        [dict(device_id="a", priority=1, min_power=800, has_runtime_deficit=True,
              top_up_policy="cheap_hours")],
        dict(available_power_w=0.0, price_level="cheap"),
    ),
    "grid_disabled_stops": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True,
              _offpeak_forced=True, top_up_policy="solar_only")],
        dict(available_power_w=0.0, price_level="cheap"),
    ),
    "peak_emergency_sheds_all": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True, draw=800),
         dict(device_id="b", priority=2, min_power=800, is_active=True, draw=800)],
        dict(available_power_w=0.0, peak_state=LoadManagementState.EMERGENCY),
    ),
    "off_mode_untouched": (
        [dict(device_id="a", priority=1, min_power=800, control_mode=DeviceControlMode.OFF,
              is_active=True, draw=800)],
        dict(available_power_w=5000.0),
    ),
    "no_surplus_all_off": (
        [dict(device_id="a", priority=1, min_power=800),
         dict(device_id="b", priority=2, min_power=800)],
        dict(available_power_w=0.0),
    ),
    "tier1_assist_activates": (
        [dict(device_id="a", priority=1, min_power=800, battery_assist_enabled=True)],
        dict(available_power_w=500.0, battery_soc=90, battery_buffer_soc=70,
             battery_assist_budget_w=3000.0),
    ),
    "peak_shedding_one_per_cycle": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True, draw=800),
         dict(device_id="b", priority=2, min_power=800, is_active=True, draw=800)],
        dict(available_power_w=0.0, peak_state=LoadManagementState.SHEDDING),
    ),
    "reclaim_above_battery_only": (
        [dict(device_id="above", priority=1, min_power=800),
         dict(device_id="below", priority=3, min_power=800)],
        dict(available_power_w=0.0, reclaim_w=2000.0, battery_priority=2),
    ),
    "peak_warning_freezes_new": (
        [dict(device_id="a", priority=1, min_power=800)],
        dict(available_power_w=5000.0, peak_state=LoadManagementState.WARNING),
    ),
}


async def _run(specs, kw, use_desired):
    hass = MagicMock()
    sc = SurplusController(hass)
    sc._use_desired_state = use_desired
    for s in specs:
        sc.register_device(_PDev(**s))
    await sc.update(**kw)
    return {d.device_id: d.is_active for d in sc._devices.values()}


# Known remaining parity gaps — both trace to the old deficit-LIFO (its ~100 W
# hysteresis band + battery-unaware accounting), which the per-device walk does
# not model yet. MUST be closed before the flag can flip (Phase 4). strict=True
# so a later fix flips the xfail to an error and forces removing the mark.
_XFAIL = {
    "tier1_assist_activates":
        "old activates the tier1 load then the deficit-LIFO kills it (decrements "
        "the full draw without crediting the battery); the new path keeps it on "
        "(arguably correct). Model the LIFO's battery-aware accounting first.",
    "peak_shedding_one_per_cycle":
        "old keeps an active load on within the -100 W LIFO hysteresis band; the "
        "new path stops any sourceless load. Model the band in the walk first.",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    pytest.param(n, marks=pytest.mark.xfail(reason=_XFAIL[n], strict=True))
    if n in _XFAIL else n
    for n in _SCENARIOS
])
async def test_desired_state_parity(name):
    specs, kw = _SCENARIOS[name]
    old = await _run(specs, kw, use_desired=False)
    new = await _run(specs, kw, use_desired=True)
    assert old == new, f"{name}: imperative={old} desired={new}"


@pytest.mark.asyncio
async def test_update_observer_computes_but_never_actuates(caplog):
    """The clean cut, end-to-end. Observer mode runs the FULL real decision
    (layers 1+2 against live inputs) and reconciles through the single seam in
    log-only mode: nothing is actuated, the imperative passes are never reached,
    and allocation data is still produced for the sensors. Works with
    ``_use_desired_state`` OFF (the PROD-shipped default) — observer always takes
    the clean path. This is the invariant that makes HA-TEST safe on shared
    hardware."""
    import logging
    hass = MagicMock()
    sc = SurplusController(hass)
    sc.register_device(_PDev(device_id="a", priority=1, min_power=800, is_active=False))
    assert sc._use_desired_state is False                 # PROD-shipped default
    with caplog.at_level(logging.INFO):
        data = await sc.update(available_power_w=5000.0, observer=True)
    states = {d.device_id: d.is_active for d in sc._devices.values()}
    assert states == {"a": False}                         # nothing actuated
    assert "WOULD ACTIVATE" in caplog.text                # decision made + logged
    assert data.total_surplus_w == 5000.0                 # sensors still fed


# ── ruflo B1/H2 fixes ─────────────────────────────────────────────────────
def test_deadline_force_ignores_surplus():
    d = _dev(min_power_threshold=800, rated_power=800)
    d.is_deadline_approaching = True
    i = compute_load_intent(d, remaining_surplus_w=0)   # no surplus at all…
    assert i.on is True and "deadline" in i.reason      # …still force-started


@pytest.mark.asyncio
async def test_reconcile_resets_debounce_when_idle_no_source():
    d = _rec_dev(is_active=False)
    await reconcile_load(d, LoadIntent(False, 0, None, "no source"))
    d.reset_surplus_timer.assert_called()   # cloud-shadow gap restarts the delay
