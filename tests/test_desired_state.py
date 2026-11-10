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
    # user-turned-on load (not SEM-owned): mode Off means hands off
    on = compute_load_intent(_dev(control_mode=DeviceControlMode.OFF, is_active=True,
                                  consumption=900), remaining_surplus_w=5000)
    assert on.on is True and on.source is None          # SEM doesn't touch it
    off = compute_load_intent(_dev(control_mode=DeviceControlMode.OFF, is_active=False),
                              remaining_surplus_w=5000)
    assert off.on is False and off.source is None


def test_off_mode_releases_sem_driven_load():
    """(class-17 sibling, live PROD 2026-07-23) Switching to Off while SEM is
    DRIVING the load must stop it — not strand it running forever."""
    d = _dev(control_mode=DeviceControlMode.OFF, is_active=True, consumption=900)
    d._sem_owned = True
    d._sem_commanded = True          # (#847) SEM issued the ON, so Off undoes it
    i = compute_load_intent(d, remaining_surplus_w=5000)
    assert i.on is False
    assert "SEM-started" in i.reason

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
    # (#688) ``daily_targets_met`` is deliberately NOT in this list: the daily
    # minimum is a floor, not a stop — free surplus carries the load on to the
    # Max cap (see test_688_runtime_floor_ceiling.py). Only the CEILING and the
    # external stop condition are hard stops.
    for gate in ("daily_max_runtime_reached", "stop_condition_met"):
        i = compute_load_intent(_dev(is_active=True, **{gate: True}), remaining_surplus_w=5000)
        assert i.on is False, gate

def test_floor_is_not_a_stop_gate():
    """(#688) The mirror of the above — pinned here too so the precedence walk
    can't quietly reinstate the minimum as a stop."""
    i = compute_load_intent(_dev(is_active=True, daily_targets_met=True),
                            remaining_surplus_w=5000)
    assert i.on is True

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
                            remaining_surplus_w=0, soc_above_reserve=True, is_night=True)
    assert i.on is True and i.source == "tier2_battery"

def test_tier2_blocked_in_daytime_633():
    """(#633) the same inputs with is_night=False must NOT fire tier-2."""
    d = _dev(has_runtime_deficit=True, battery_eligible_overnight=True)
    i = compute_load_intent(d, remaining_surplus_w=0,
                            soc_above_reserve=True, is_night=False)
    assert i.on is False


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
    _controller = None

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
        # (#1335) the D-item shapes: all inert at their defaults
        self.depends_on = list(kw.get("depends_on", []))
        self.dependency_mode = "must_active"
        self.start_reserve_w = float(kw.get("start_reserve_w", 0.0))
        self._phase_hold = kw.get("phase_hold")
        self._phase_shed = False
        self.is_deadline_approaching = kw.get("deadline", False)
        if "comfort" in kw:
            # (state, reading °C, keep-at °C) — a heater band
            state, reading, keep_at = kw["comfort"]
            self.comfort_state = state
            self._comfort_reading = lambda: reading
            self._comfort_thresholds_c = lambda: (keep_at, 5.0, keep_at - 14.0)
            self._comfort_direction = lambda: "heat"

    def _check_dependencies(self):
        for dep_id in self.depends_on:
            dep = self._controller.get_device(dep_id) if self._controller else None
            if dep is not None and not dep.is_active:
                return False
        return True

    @property
    def is_active(self):
        return self._active

    @property
    def needs_offpeak_activation(self):
        return self.has_runtime_deficit and not self._active

    def can_activate(self):
        if isinstance(self._phase_hold, str):
            return False
        return self._can_act and self._check_dependencies()
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
    # (#688) The floor is not a stop: past Min the load KEEPS running on free
    # surplus, up to the Max cap (the scenario above). Name says so.
    "running_load_past_floor_keeps_surplus": (
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


# The two parity gaps that lived here (tier1_assist_activates,
# peak_shedding_one_per_cycle) were closed by #688: the imperative walk now
# debits an active/activated load's full draw minus the Tier-1 battery share,
# which is exactly the battery-aware accounting the desired-state path models.
# Full parity — no xfails left. Add new gaps back as strict xfails only.
_XFAIL: dict = {}


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


# ── #1335: parity per D-item, multi-cycle, power + markers + reason ───────
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)


class _PSet(_PDev):
    """A watt-setpoint load: it draws what it is sent, inside its entity's
    bounds (the shape of ``PowerSetpointDevice``)."""

    def __init__(self, device_id, priority, **kw):
        super().__init__(device_id, priority, **kw)
        self._lo, self._hi = kw.get("bounds", (0.0, 3000.0))
        self.device_type = MagicMock(value="setpoint")

    def _clamp(self, w):
        return max(self._lo, min(float(w), self._hi))

    def expected_draw_w(self, w):
        return self._clamp(w)

    async def activate(self, target):
        self._draw = self._clamp(target)
        self._active = True
        return self._draw

    async def adjust_power(self, target):
        self._draw = self._clamp(target)
        return self._draw


#: The reason families the two engines must agree on. The codes differ in
#: name only (the old passes said "surplus"/"plan_window", layer 1 says
#: "solar"/"comfort_goal").
_FAMILY = {"surplus": "sun", "solar": "sun", "tier1_battery": "sun", "start": "sun",
           "plan_window": "banking", "comfort_goal": "banking",
           "target_met": "paid_end", "overnight_end": "paid_end"}

_BAND_BLOCK = {"boiler": PlanVerdict(in_block=True, comfort_in_block=True,
                                     reason="planned block")}

# id → (device specs, [update kwargs per cycle])
_D_SCENARIOS = {
    # D1 — a banking run holds through its comfort block (layered was right;
    # the old expiry now leaves it to the block).
    "d1_banking_holds_in_its_block": (
        [dict(device_id="boiler", priority=1, min_power=3000,
              top_up_policy="solar_only", comfort=("willing", 45.0, 50.0))],
        [dict(available_power_w=0.0, price_level="normal", plan_windows=_BAND_BLOCK)] * 3,
    ),
    # D2 — the pool runs short: the LOWEST priority stops first, and only
    # past the 100 W band (old was right; layer 2 now runs the deficit stop).
    "d2_lowest_priority_loses_first": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True),
         dict(device_id="b", priority=2, min_power=800, is_active=True),
         dict(device_id="c", priority=3, min_power=800, is_active=True)],
        [dict(available_power_w=1900.0)] * 3,
    ),
    "d2_inside_the_band_both_stay": (
        [dict(device_id="a", priority=1, min_power=800, is_active=True),
         dict(device_id="b", priority=2, min_power=800, is_active=True)],
        [dict(available_power_w=1550.0)] * 2,
    ),
    "d2_a_higher_load_short_of_its_own_threshold_keeps_running": (
        [dict(device_id="a", priority=1, min_power=1000, is_active=True),
         dict(device_id="b", priority=2, min_power=300, is_active=True, draw=300)],
        [dict(available_power_w=1150.0)] * 2,
    ),
    # D3 — a running watt setpoint follows the free power (old was right).
    "d3_setpoint_ramps_to_free_power": (
        [dict(device_id="heater", priority=1, min_power=500, is_active=True,
              draw=1000, kind="setpoint")],
        [dict(available_power_w=2600.0)] * 2,
    ),
    # D4 — the start reserve (#688; layered was right, old now asks it too).
    "d4_start_reserve_waits": (
        [dict(device_id="pump", priority=1, min_power=800, start_reserve_w=200)],
        [dict(available_power_w=900.0)] * 2,
    ),
    "d4_start_reserve_met_starts": (
        [dict(device_id="pump", priority=1, min_power=800, start_reserve_w=200)],
        [dict(available_power_w=1100.0)],
    ),
    # D5 — a cheap-hours grid start must fit the billing slot (#864; old was
    # right, layer 1 now asks it).
    "d5_peak_slot_refuses_a_grid_start": (
        [dict(device_id="pool", priority=1, min_power=800, has_runtime_deficit=True,
              top_up_policy="cheap_hours")],
        [dict(available_power_w=0.0, price_level="cheap",
              peak_slot_allowed_w=500.0, grid_import_w=400.0)] * 2,
    ),
    "d5_peak_slot_with_room_starts": (
        [dict(device_id="pool", priority=1, min_power=800, has_runtime_deficit=True,
              top_up_policy="cheap_hours")],
        [dict(available_power_w=0.0, price_level="cheap",
              peak_slot_allowed_w=5000.0, grid_import_w=400.0)],
    ),
    # D6 — what requires a load stops with it (#122; old was right).
    "d6_dependent_stops_with_its_parent": (
        [dict(device_id="boiler", priority=1, min_power=800, is_active=True,
              depends_on=["heat_pump"]),
         dict(device_id="heat_pump", priority=2, min_power=800, is_active=True)],
        [dict(available_power_w=900.0)] * 2,
    ),
    # D7 — a deadline beats the peak, not a fuse (#1048; old was right).
    "d7_deadline_waits_for_a_phase_hold": (
        [dict(device_id="dishwasher", priority=1, min_power=1800, deadline=True,
              phase_hold="L1")],
        [dict(available_power_w=0.0)] * 2,
    ),
    "d7_deadline_without_a_hold_starts": (
        [dict(device_id="dishwasher", priority=1, min_power=1800, deadline=True)],
        [dict(available_power_w=0.0)],
    ),
    # D8 — a watt setpoint starts at the free power (old was right).
    "d8_setpoint_starts_at_free_power": (
        [dict(device_id="heater", priority=1, min_power=500, kind="setpoint")],
        [dict(available_power_w=2500.0)] * 2,
    ),
    # D9 — a paid run takes only the sun that is left (old's rule kept; the
    # layered "debit nothing" handed its sun to the next load).
    "d9_paid_run_takes_the_sun_left": (
        [dict(device_id="pool", priority=1, min_power=800, draw=2000, is_active=True,
              _offpeak_forced=True, has_runtime_deficit=True, top_up_policy="cheap_hours"),
         dict(device_id="fan", priority=2, min_power=800)],
        [dict(available_power_w=1000.0, price_level="cheap")] * 2,
    ),
    # D10 — a shed paid run carries no stale marker.
    "d10_peak_shed_clears_the_marker": (
        [dict(device_id="towel", priority=1, min_power=800, is_active=True,
              _batt_overnight_forced=True, has_runtime_deficit=True,
              battery_eligible_overnight=True)],
        [dict(available_power_w=0.0, price_level="normal", battery_soc=90,
              battery_reserve_soc=20, peak_state=LoadManagementState.EMERGENCY)],
    ),
}


def _family(code):
    return _FAMILY.get(code, code)


async def _run_cycles(specs, cycles, use_desired):
    hass = MagicMock()
    sc = SurplusController(hass)
    sc._use_desired_state = use_desired
    sc.regulation_offset = 0.0
    for spec in specs:
        spec = dict(spec)
        cls = _PSet if spec.pop("kind", "switch") == "setpoint" else _PDev
        sc.register_device(cls(**spec))
    seen = []
    for kw in cycles:
        await sc.update(**kw)
        last = {}
        for rec in sc.decision_log._records:
            last[rec.device_id] = _family(rec.reason_code)
        seen.append({
            d.device_id: (d.is_active, round(d.get_current_consumption()),
                          bool(d._offpeak_forced), bool(d._batt_overnight_forced),
                          last.get(d.device_id))
            for d in sc._devices.values()})
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(_D_SCENARIOS))
async def test_d_item_parity(name):
    """(#1335) Both engines, the same multi-cycle inputs: the same on/off,
    the same draw (a watt setpoint's too), the same markers, the same reason
    family."""
    specs, cycles = _D_SCENARIOS[name]
    old = await _run_cycles(specs, cycles, use_desired=False)
    new = await _run_cycles(specs, cycles, use_desired=True)
    assert old == new, f"{name}:\n imperative={old}\n layered   ={new}"


@pytest.mark.asyncio
async def test_d_items_say_what_they_pin():
    """The scenarios above are not vacuous: each one lands where its item
    says (checked on the layered engine)."""
    async def last(name):
        specs, cycles = _D_SCENARIOS[name]
        return (await _run_cycles(specs, cycles, use_desired=True))[-1]
    assert (await last("d1_banking_holds_in_its_block"))["boiler"][:3] == (True, 3000, True)
    r = await last("d2_lowest_priority_loses_first")
    assert [r[k][0] for k in "abc"] == [True, True, False]
    assert r["c"][4] == "surplus_short"
    r = await last("d2_inside_the_band_both_stay")
    assert r["a"][0] and r["b"][0]
    r = await last("d2_a_higher_load_short_of_its_own_threshold_keeps_running")
    assert r["a"][0] and not r["b"][0]
    assert (await last("d3_setpoint_ramps_to_free_power"))["heater"][:2] == (True, 2600)
    assert not (await last("d4_start_reserve_waits"))["pump"][0]
    assert (await last("d4_start_reserve_met_starts"))["pump"][0]
    assert not (await last("d5_peak_slot_refuses_a_grid_start"))["pool"][0]
    assert (await last("d5_peak_slot_with_room_starts"))["pool"][:3] == (True, 800, True)
    specs, cycles = _D_SCENARIOS["d6_dependent_stops_with_its_parent"]
    first, second = await _run_cycles(specs, cycles, use_desired=True)
    assert not first["heat_pump"][0] and not first["boiler"][0]
    assert first["boiler"][4] == "dependency"
    # next cycle the pump alone fits again; the boiler waits for it
    assert second["heat_pump"][0] and not second["boiler"][0]
    assert not (await last("d7_deadline_waits_for_a_phase_hold"))["dishwasher"][0]
    assert (await last("d7_deadline_without_a_hold_starts"))["dishwasher"][0]
    assert (await last("d8_setpoint_starts_at_free_power"))["heater"][:2] == (True, 2500)
    r = await last("d9_paid_run_takes_the_sun_left")
    assert r["pool"][:3] == (True, 2000, True) and not r["fan"][0]
    r = await last("d10_peak_shed_clears_the_marker")
    assert r["towel"][:4] == (False, 0, False, False)


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
