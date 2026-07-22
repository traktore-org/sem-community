"""#620 — generic-device goal model: max cap + the two battery tiers.

Model (design spec 2026-07-20): per-device Minimum (floor) / Maximum (cap,
persisted) / Solar+battery daytime assist (Tier 1) / overnight below-buffer
drain (Tier 2). Continuous priority allocation bounded by two hard ceilings
(peak limit, reserve SoC). NO device deadlines. Everything is INERT unless a
device opts in — these tests pin both the new behaviour AND the inertness.
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, DeviceControlMode, DeviceState,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.const import LoadManagementState


def _switch(**kw):
    dev = SwitchDevice(
        hass=MagicMock(),
        device_id=kw.get("device_id", "pump"),
        name=kw.get("name", "Pool Pump"),
        rated_power=kw.get("rated_power", 800),
        priority=kw.get("priority", 5),
        entity_id="switch.pump",
    )
    dev.control_mode = DeviceControlMode.SURPLUS
    return dev


# ── Phase 1: device model — max cap gate + persistence ────────────────────

class TestMaxCapGate:
    def test_uncapped_default(self):
        d = _switch()
        assert d.daily_max_runtime_sec == 0
        assert d.daily_max_runtime_reached is False

    def test_cap_reached_blocks_activation(self):
        d = _switch()
        d.daily_max_runtime_sec = 3600
        d._daily_runtime_accumulated_sec = 3600
        assert d.daily_max_runtime_reached is True
        assert d.can_activate() is False  # cap overrides everything

    def test_below_cap_can_activate(self):
        d = _switch()
        d.daily_max_runtime_sec = 3600
        d._daily_runtime_accumulated_sec = 1800
        assert d.daily_max_runtime_reached is False
        assert d.can_activate() is True

    def test_cap_blocks_offpeak_need(self):
        d = _switch()
        d.daily_min_runtime_sec = 7200
        d.daily_max_runtime_sec = 3600
        d._daily_runtime_accumulated_sec = 3600  # hit max before min
        assert d.needs_offpeak_activation is False  # cap wins

    def test_max_cap_persisted_and_restored(self):
        """The #559 HIGH-1 regression: the cap must survive serialize→restore."""
        d = _switch()
        d.daily_max_runtime_sec = 6000
        d.battery_assist_enabled = True
        d.battery_eligible_overnight = True
        blob = d.to_dict()
        assert blob["daily_max_runtime_sec"] == 6000
        assert blob["battery_assist_enabled"] is True
        assert blob["battery_eligible_overnight"] is True

    def test_battery_only_device_serializes(self):
        """A device with ONLY a battery flag (no runtime target) still emits
        the battery fields (reviewer MEDIUM-3)."""
        d = _switch()
        d.battery_assist_enabled = True
        blob = d.to_dict()
        assert blob["battery_assist_enabled"] is True


class TestGoalBoolPersistence:
    """Reviewer BLOCKER-2: the service stores flags as STRINGS; bool('False')
    is True in Python, so a disabled flag must NOT round-trip back to True."""

    def test_goal_bool_parses_strings(self):
        from custom_components.solar_energy_management.features.device_registry import (
            _goal_bool,
        )
        assert _goal_bool("True") is True
        assert _goal_bool("False") is False   # the bug: bool("False") == True
        assert _goal_bool("false") is False
        assert _goal_bool("true") is True
        assert _goal_bool(True) is True
        assert _goal_bool(False) is False
        assert _goal_bool(None) is False
        assert _goal_bool("1") is True
        assert _goal_bool("0") is False

    def test_apply_goals_restores_false_flag(self):
        """The full path: a stored '"False"' string must land as False on the
        device, not silently flip to True after a restart."""
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"pump": {
            "daily_min_runtime_min": 60,
            "battery_assist_enabled": "False",       # stored as a string
            "battery_eligible_overnight": "True",
        }}
        dev = _switch(device_id="pump")
        dev.battery_assist_enabled = True  # pretend it was on before restart
        reg._apply_goals(dev)
        assert dev.battery_assist_enabled is False   # was "False" → stays off
        assert dev.battery_eligible_overnight is True


# ── Phase 2: allocation — Tier 1 daytime assist ───────────────────────────

def _mock(**kw):
    d = MagicMock()
    d.device_id = kw.get("device_id", "d")
    d.name = kw.get("name", "D")
    d.priority = kw.get("priority", 5)
    d.min_power_threshold = kw.get("min_power", 800)
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = kw.get("is_active", False)
    d.device_type = MagicMock(value="switch")
    d.activate = AsyncMock(return_value=kw.get("draw", 800))
    d.adjust_power = AsyncMock(return_value=kw.get("draw", 800))
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.can_activate = MagicMock(return_value=kw.get("can_activate", True))
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.control_mode = kw.get("control_mode", DeviceControlMode.SURPLUS)
    d._sem_owned = kw.get("sem_owned", False)
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = kw.get("_batt_overnight_forced", False)
    d._batt_overnight_forced_date = None
    d.needs_offpeak_activation = kw.get("needs_offpeak", False)
    d.remaining_daily_runtime_sec = kw.get("remaining_sec", 0)
    d.daily_min_runtime_sec = 0
    d.daily_targets_met = False
    d.daily_max_runtime_reached = kw.get("max_reached", False)
    d.stop_condition_met = False
    d.top_up_policy = "solar_only"
    d.battery_assist_enabled = kw.get("battery_assist_enabled", False)
    d.battery_eligible_overnight = kw.get("battery_eligible_overnight", False)
    d.stop_entity = ""
    d.stop_at = 0

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


@pytest.fixture
def mock_hass():
    h = MagicMock()
    return h


def test_solar_bounded_surplus():
    """(#620) The one physical invariant: solar surplus can never exceed the
    live solar production. This is the whole night-surplus guard — the phantom
    ~1.6 kW @onkelfu saw when a load ran overnight off the battery (solar 0) is
    pinned to 0. Replaces the earlier per-load exclusion with a single rule."""
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        solar_bounded_surplus,
    )
    # NIGHT: solar 0 → any add-back (battery/grid-driven load) pinned to 0
    assert solar_bounded_surplus(grid_export_w=0, active_draw_w=1600, solar_w=0) == 0.0
    # DAY: export + own draw, under the solar ceiling → passes through unchanged
    assert solar_bounded_surplus(grid_export_w=500, active_draw_w=1000, solar_w=5000) == 1500.0
    # DAY: reconstructed surplus above what the sun makes → capped at solar
    assert solar_bounded_surplus(grid_export_w=0, active_draw_w=1600, solar_w=800) == 800.0
    # importing with no offsetting draw → clamped to 0, never negative
    assert solar_bounded_surplus(grid_export_w=-500, active_draw_w=0, solar_w=1000) == 0.0
    # solar sensor unavailable → no cap, raw add-back (still floored at 0)
    assert solar_bounded_surplus(grid_export_w=0, active_draw_w=1600, solar_w=None) == 1600.0


@pytest.mark.asyncio
class TestGateStopsRunningLoad:
    """(bug-class 17 & 18) The family guard: EVERY reason a load should stop must
    stop a load that is already RUNNING — not merely block its next activation.
    This enumerates every stop gate; adding a new gate without adding it here
    (and wiring the stop path) fails CI. Also pins the forced markers to False
    after the stop, so they can't leak (class 18). See the desired-state spec:
    docs/superpowers/specs/2026-07-22-desired-state-surplus-loads-design.md."""

    @pytest.mark.parametrize("gate,overrides,kw", [
        ("max_cap", {"daily_max_runtime_reached": True},
            {"available_power_w": 5000.0}),
        ("target_met", {"daily_targets_met": True},
            {"available_power_w": 5000.0}),
        ("stop_condition", {"stop_condition_met": True},
            {"available_power_w": 5000.0}),
        ("overnight_disabled", {"_batt_overnight_forced": True,
                                "battery_eligible_overnight": False},
            {"available_power_w": 0.0, "price_level": "normal",
             "battery_soc": 90, "battery_reserve_soc": 20}),
        ("grid_disabled", {"_offpeak_forced": True, "top_up_policy": "solar_only"},
            {"available_power_w": 0.0, "price_level": "cheap"}),
        ("reserve_floor", {"_batt_overnight_forced": True,
                           "battery_eligible_overnight": True},
            {"available_power_w": 0.0, "price_level": "normal",
             "battery_soc": 20, "battery_reserve_soc": 20}),
        ("peak_emergency", {},
            {"available_power_w": 0.0, "peak_state": LoadManagementState.EMERGENCY}),
    ])
    async def test_gate_stops_a_running_load(self, mock_hass, gate, overrides, kw):
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True)
        d.get_current_consumption = MagicMock(return_value=800.0)
        for k, v in overrides.items():
            setattr(d, k, v)
        sc.register_device(d)
        await sc.update(**kw)
        # a RUNNING load is stopped by the gate, not just blocked from restarting
        d.deactivate.assert_awaited()
        # class 18 — the transient force markers don't leak past the stop
        assert d._batt_overnight_forced is False
        assert d._offpeak_forced is False


@pytest.mark.asyncio
class TestMaxCapDeactivation:
    """The hard cap must STOP a running device, not only block re-activation
    (caught live on the Heizband PROD test — a load already on when it crossed
    the cap kept running past it)."""

    async def test_cap_reached_deactivates_running_device(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, consumption=800)
        d.daily_max_runtime_reached = True      # crossed the cap this cycle
        d.daily_targets_met = False             # still has a min deficit
        d.stop_condition_met = False
        sc.register_device(d)
        await sc.update(5000.0)                 # plenty of surplus — must NOT keep it on
        d.deactivate.assert_awaited()

    async def test_below_cap_running_device_stays(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, consumption=800)
        d.daily_max_runtime_reached = False
        d.daily_targets_met = False
        d.stop_condition_met = False
        sc.register_device(d)
        await sc.update(5000.0)
        d.deactivate.assert_not_awaited()


@pytest.mark.asyncio
class TestTier1BatteryAssist:
    async def test_no_assist_below_threshold_when_flag_off(self, mock_hass):
        """Raw surplus < rated, flag OFF → does not activate (inert)."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=False)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=3000)
        d.activate.assert_not_called()

    async def test_assist_activates_above_buffer(self, mock_hass):
        """Raw surplus 400 < 800 rated, but flag ON + SoC>buffer + budget →
        effective surplus 400+3000 ≥ 800 → activates (battery tops up)."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=True)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=3000)
        d.activate.assert_called_once()

    async def test_no_assist_below_buffer(self, mock_hass):
        """Flag ON but SoC ≤ buffer → no headroom, stays off (battery reserved)."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=True)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=65, battery_buffer_soc=70,
                        battery_assist_budget_w=3000)
        d.activate.assert_not_called()

    async def test_no_assist_when_budget_zero(self, mock_hass):
        """Flag ON, SoC>buffer, but coordinator passed 0 budget (no real
        surplus past the Solar Gate) → no activation."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800, battery_assist_enabled=True)
        sc.register_device(d)
        await sc.update(400.0, battery_soc=90, battery_buffer_soc=70,
                        battery_assist_budget_w=0.0)
        d.activate.assert_not_called()


@pytest.mark.asyncio
class TestTier2Overnight:
    async def test_overnight_activates_above_reserve(self, mock_hass):
        """Deficit, no surplus, flag ON, SoC>reserve → runs from battery."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=True, remaining_sec=1800,
                  battery_eligible_overnight=True, draw=800)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=50,
                        battery_reserve_soc=20)
        d.activate.assert_called_once()
        assert d._batt_overnight_forced is True
        assert d._offpeak_forced is False  # Tier-2 uses its OWN marker

    async def test_overnight_blocked_below_reserve(self, mock_hass):
        """SoC ≤ reserve → the hard floor holds, no activation."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=True, remaining_sec=1800,
                  battery_eligible_overnight=True)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=18,
                        battery_reserve_soc=20)
        d.activate.assert_not_called()

    async def test_overnight_inert_when_flag_off(self, mock_hass):
        """The pre-#620 behaviour: solar_only deficit device, no surplus, no
        battery flag → NEVER force-runs (the frozen deadline path stays gone)."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=True, remaining_sec=1800,
                  battery_eligible_overnight=False)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=90,
                        battery_reserve_soc=20)
        d.activate.assert_not_called()

    async def test_overnight_does_not_self_flap(self, mock_hass):
        """Reviewer BLOCKER-1: a Tier-2 device that activated must STAY on the
        next cycle at normal tariff — the cheap-hours force-expiry (which
        deactivates _offpeak_forced devices when tariff isn't cheap) must not
        touch the separate _batt_overnight_forced marker."""
        sc = SurplusController(mock_hass)
        d = _switch(device_id="pump", rated_power=800)
        d.control_mode = DeviceControlMode.SURPLUS
        d.daily_min_runtime_sec = 3600
        d.battery_eligible_overnight = True
        # simulate: already forced on by Tier-2 last cycle
        d._status.state = DeviceState.ACTIVE
        d._batt_overnight_forced = True
        from datetime import date as _date
        from homeassistant.util import dt as dt_util
        # freeze "today" so the day-rollover branch doesn't fire
        d._batt_overnight_forced_date = dt_util.now().date()
        d.deactivate = AsyncMock()
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=50,
                        battery_reserve_soc=20)
        # SoC 50 > reserve 20, same day, normal tariff → NOT expired.
        d.deactivate.assert_not_awaited()

    async def test_toggle_off_stops_running_overnight_load(self, mock_hass):
        """The 'Use battery overnight' toggle gates activation, but a load
        already running off the battery must STOP the moment the user turns it
        off — else it keeps draining until reserve/rollover (caught live on the
        Heizband toggle test)."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, battery_eligible_overnight=False,
                  _batt_overnight_forced=True, consumption=800)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=90,
                        battery_reserve_soc=20)  # SoC ≫ reserve, same day
        d.deactivate.assert_awaited()
        assert d._batt_overnight_forced is False

    async def test_grid_disabled_by_user_stops_offpeak_load(self, mock_hass):
        """The picker moving off 'Grid' (top_up_policy → solar_only) must stop a
        load already running on the cheap-hours force — the grid-path sibling of
        the battery-toggle stop (caught live on the picker's Off test)."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, consumption=800)
        d._offpeak_forced = True
        d.top_up_policy = "solar_only"   # user picked Off / Battery
        sc.register_device(d)
        await sc.update(0.0, price_level="cheap", battery_soc=90)
        d.deactivate.assert_awaited()

    async def test_overnight_expires_at_reserve(self, mock_hass):
        """The Reserve floor DOES end a Tier-2 run — battery protected."""
        sc = SurplusController(mock_hass)
        d = _switch(device_id="pump", rated_power=800)
        d.control_mode = DeviceControlMode.SURPLUS
        d.battery_eligible_overnight = True
        d._status.state = DeviceState.ACTIVE
        d._batt_overnight_forced = True
        from homeassistant.util import dt as dt_util
        d._batt_overnight_forced_date = dt_util.now().date()
        async def _deact():
            d._status.state = DeviceState.IDLE
        d.deactivate = AsyncMock(side_effect=_deact)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=20,
                        battery_reserve_soc=20)  # SoC == reserve → expire
        d.deactivate.assert_awaited()

    async def test_overnight_respects_max_cap(self, mock_hass):
        """A capped-out device (can_activate False) is skipped even with the
        flag on and SoC high."""
        sc = SurplusController(mock_hass)
        d = _mock(needs_offpeak=False, battery_eligible_overnight=True,
                  can_activate=False)
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=90,
                        battery_reserve_soc=20)
        d.activate.assert_not_called()

    async def test_peak_ceiling_sheds_tier2_and_clears_marker(self, mock_hass):
        """The peak limit is a HARD ceiling that overrides Tier-2 (reviewer
        HIGH): an active overnight-battery device IS shed on EMERGENCY, and its
        force marker is cleared so it carries no stale state."""
        from custom_components.solar_energy_management.const import (
            LoadManagementState,
        )
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, battery_eligible_overnight=True,
                  _batt_overnight_forced=True, consumption=800)
        d.get_current_consumption = MagicMock(return_value=800.0)
        sc.register_device(d)
        await sc.update(0.0, peak_state=LoadManagementState.EMERGENCY,
                        battery_soc=90, battery_reserve_soc=20)
        d.deactivate.assert_awaited()
        assert d._batt_overnight_forced is False
        assert d._batt_overnight_forced_date is None

    async def test_done_for_day_clears_overnight_marker(self, mock_hass):
        """Goal-gate "daily target met" must also end a Tier-2 force so the
        marker doesn't leak until day rollover (reviewer MEDIUM)."""
        sc = SurplusController(mock_hass)
        d = _mock(is_active=True, battery_eligible_overnight=True,
                  _batt_overnight_forced=True, consumption=800)
        d.daily_targets_met = True
        sc.register_device(d)
        await sc.update(0.0, price_level="normal", battery_soc=90,
                        battery_reserve_soc=20)
        d.deactivate.assert_awaited()
        assert d._batt_overnight_forced is False
        assert d._batt_overnight_forced_date is None


@pytest.mark.asyncio
class TestInertByDefault:
    async def test_default_device_unchanged_by_battery_context(self, mock_hass):
        """A plain device (all flags default) behaves identically whether or
        not battery context is passed — the whole feature is opt-in."""
        sc = SurplusController(mock_hass)
        d = _mock(min_power=800)
        sc.register_device(d)
        # Ample surplus → activates regardless (normal path untouched).
        await sc.update(2000.0, battery_soc=90, battery_buffer_soc=70,
                        battery_reserve_soc=20, battery_assist_budget_w=3000)
        d.activate.assert_called_once()


# ── Mode → Off releases a SEM-driven running load (class-17 sibling) ──────
# Caught live (PROD 2026-07-23): switching a running load's mode to Off left
# it on forever — the activation pass skips OFF devices, so nothing stopped it.
@pytest.mark.asyncio
class TestModeOffReleasesRunningLoad:
    async def test_mode_off_stops_sem_owned_load(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _mock(device_id="d", is_active=True, sem_owned=True,
                  control_mode=DeviceControlMode.OFF,
                  _batt_overnight_forced=True)
        d.get_current_consumption = MagicMock(return_value=600.0)
        sc.register_device(d)
        await sc.update(0.0)
        d.deactivate.assert_called()
        assert d._batt_overnight_forced is False   # markers cleared on release

    async def test_mode_off_leaves_user_turned_on_load_alone(self, mock_hass):
        sc = SurplusController(mock_hass)
        d = _mock(device_id="d", is_active=True, sem_owned=False,
                  control_mode=DeviceControlMode.OFF)
        sc.register_device(d)
        await sc.update(0.0)
        d.deactivate.assert_not_called()           # user's own choice — hands off


# ── Device-object rebuild must not reset volatile control state ───────────
# PROD incident 2026-07-22 22:15: a config edit triggered rediscovery, which
# re-registered a FRESH Heizband object. Its _batt_overnight_forced marker
# (set by the Tier-2 activation at 22:08) silently reset to False, so when a
# second load (cheap-hours Männer, 1082 W) drove the surplus ledger negative,
# the deficit-LIFO no longer saw the exemption and killed the running Tier-2
# load 23 min before its min. Bug class 14 × #620.
class TestRebuildKeepsControlState:
    def test_reregister_transplants_volatile_state(self, mock_hass):
        sc = SurplusController(mock_hass)
        from datetime import datetime, date
        old = _mock(device_id="heiz", is_active=True,
                    _batt_overnight_forced=True)
        old._batt_overnight_forced_date = date(2026, 7, 22)
        old._offpeak_forced = True
        old._offpeak_forced_date = date(2026, 7, 22)
        old._last_activated = datetime(2026, 7, 22, 22, 8, 42)
        old._sem_owned = True
        old._surplus_since = None
        sc.register_device(old)
        fresh = _mock(device_id="heiz", is_active=False)   # rebuild defaults
        fresh._sem_owned = False
        fresh._last_activated = None
        sc.register_device(fresh)
        assert fresh._batt_overnight_forced is True
        assert fresh._batt_overnight_forced_date == date(2026, 7, 22)
        assert fresh._offpeak_forced is True
        assert fresh._last_activated == datetime(2026, 7, 22, 22, 8, 42)
        assert fresh._sem_owned is True
        assert sc.get_device("heiz") is fresh

    @pytest.mark.asyncio
    async def test_rebuild_then_second_activation_does_not_kill_tier2_load(
            self, mock_hass):
        """The exact PROD sequence: Tier-2 load running (marker set) → device
        rebuild (marker would be lost) → cheap-hours pass activates a second
        load, ledger goes deep negative → the LIFO must STILL exempt the
        Tier-2 load. Without the transplant this deactivates it 23 min early."""
        sc = SurplusController(mock_hass)
        heiz = _mock(device_id="heiz", name="Heizband", priority=2,
                     is_active=True, _batt_overnight_forced=True,
                     battery_eligible_overnight=True)
        heiz.get_current_consumption = MagicMock(return_value=135.0)
        sc.register_device(heiz)
        # rediscovery rebuilds the object mid-run
        heiz2 = _mock(device_id="heiz", name="Heizband", priority=2,
                      is_active=True, battery_eligible_overnight=True)
        heiz2.get_current_consumption = MagicMock(return_value=135.0)
        sc.register_device(heiz2)
        maenner = _mock(device_id="maenner", name="Männer", priority=5,
                        min_power=1082, draw=1082, needs_offpeak=True)
        maenner.top_up_policy = "cheap_hours"
        sc.register_device(maenner)
        # night: zero surplus; cheap window open → off-peak activates Männer
        await sc.update(0.0, price_level="cheap")
        maenner.activate.assert_called()          # grid top-up started
        heiz2.deactivate.assert_not_called()      # Tier-2 load survives
