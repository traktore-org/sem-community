"""Tests for SOC zone strategy: _determine_charging_strategy() (and historically also _calculate_solar_ev_budget, removed in Phase D.2 #282 — coverage moved to canonical EVBudget tests and scenario harness).

Codified from real-world scenario on 2026-03-22 where battery drained to 20% SOC.
Investigation confirmed zones held correctly: battery assist stopped at 70% (Zone 2 boundary),
remaining drain was evening home consumption.

Real-world data:
  Solar: 36.65 kWh, Home: 29.98 kWh, EV: 15.52 kWh
  Battery charge: 13.55 kWh, discharge: 9.54 kWh → SOC ended at 20%
  PROD config: battery_priority_soc=90, buffer/auto_start/floor at defaults (70/90/60)
"""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator.charging_control import ChargingContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_power(
    solar_power=3000.0,
    battery_soc=50.0,
    ev_connected=True,
    battery_discharge_power=0.0,
    **kwargs,
) -> PowerReadings:
    """Create PowerReadings with sensible defaults for zone strategy tests."""
    # Accept shorthand aliases used in test scenarios
    if "solar" in kwargs:
        solar_power = kwargs.pop("solar")
    if "home" in kwargs:
        kwargs["home_consumption_power"] = kwargs.pop("home")
    if "battery_charge" in kwargs:
        kwargs["battery_charge_power"] = kwargs.pop("battery_charge")

    p = PowerReadings(
        solar_power=solar_power,
        battery_soc=battery_soc,
        ev_connected=ev_connected,
        battery_discharge_power=battery_discharge_power,
        **kwargs,
    )
    return p


@dataclass
class _MockEnergy:
    """Minimal stand-in for energy data passed to _determine_charging_strategy."""
    daily_ev: float = 0.0


class _MockForecast:
    """Stand-in for forecast reader result."""
    def __init__(self, available=False, remaining=0.0):
        self.available = available
        self.forecast_remaining_today_kwh = remaining


def _build_coordinator(config_overrides=None, current_state=ChargingState.SOLAR_IDLE):
    """Build a minimal coordinator with only what _determine_charging_strategy needs."""
    from custom_components.solar_energy_management.coordinator import SEMCoordinator

    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)

    coord.config = {
        "daily_ev_target": 10,
        "ev_charging_mode": "pv",
        "battery_auto_start_soc": 90,
        "battery_buffer_soc": 70,
        "battery_priority_soc": 30,
        "battery_assist_floor_soc": 60,
        "battery_capacity_kwh": 15,
        "battery_assist_max_power": 4500,
    }
    if config_overrides:
        coord.config.update(config_overrides)

    # time_manager
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=False)

    # state machine
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = current_state

    # forecast reader (default: unavailable)
    coord._forecast_reader = MagicMock()
    coord._forecast_reader.read_forecast = MagicMock(
        return_value=_MockForecast(available=False)
    )
    coord._cycle_forecast = _MockForecast(available=False)
    coord._cycle_vehicle_soc = None

    # flow calculator — only ``calculate_canonical_ev_budget`` is wired
    # after Phase D.2 (#282). The other zone tests don't read its return
    # value (they only assert on the strategy decision), so the MagicMock
    # default is enough.
    coord._flow_calculator = MagicMock()

    # forecast tracker (dampening defaults to 1.0)
    coord._forecast_tracker = MagicMock()
    coord._forecast_tracker.dampening_factor = 1.0
    coord._forecast_tracker.apply_dampening = MagicMock(side_effect=lambda x: x)

    return coord


# ===========================================================================
# Tests for _determine_charging_strategy
# ===========================================================================


class TestDetermineChargingStrategy:
    """Zone transition tests."""

    # --- Zone transitions (tests 1-5) ---

    def test_zone4_full_assist(self):
        """Zone 4: SOC >= auto_start_soc (90%) → battery_assist."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "Zone 4" in reason

    def test_zone3_discharge_assist(self):
        """Zone 3: SOC 70-89% → battery_assist (no forecast)."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "Zone 3" in reason

    def test_zone3_good_forecast_solar_only(self):
        """Zone 3 with good forecast → solar_only (enough solar ahead)."""
        coord = _build_coordinator()
        # remaining_need = 10 - 0 = 10 kWh
        # needs estimated_surplus >= 10 * 1.5 = 15 kWh
        # surplus = forecast_remaining * 0.5, so forecast_remaining >= 30
        forecast = _MockForecast(available=True, remaining=35.0)
        coord._forecast_reader.read_forecast.return_value = forecast
        coord._cycle_forecast = forecast
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert "forecast surplus" in reason

    def test_zone2_surplus_only(self):
        """Zone 2: SOC 30-69% → solar_only."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=50), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert "Zone 2" in reason

    def test_zone1_battery_priority(self):
        """Zone 1: SOC < 30% → idle (battery priority, EV blocked)."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=20), _MockEnergy()
        )
        assert strategy == "idle"
        assert "Zone 1" in reason

    # --- Zone 2 hysteresis (tests 6-7) ---

    def test_hysteresis_stays_battery_assist_above_floor(self):
        """Already SOLAR_SUPER_CHARGING, SOC 65% >= floor 60% → stays battery_assist."""
        coord = _build_coordinator(current_state=ChargingState.SOLAR_SUPER_CHARGING)
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=65), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "hysteresis" in reason.lower()

    def test_hysteresis_drops_below_floor(self):
        """Already SOLAR_SUPER_CHARGING, SOC 55% < floor 60% → solar_only."""
        coord = _build_coordinator(current_state=ChargingState.SOLAR_SUPER_CHARGING)
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=55), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert "Zone 2" in reason

    # --- Edge cases & mode overrides (tests 8-13) ---

    def test_ev_disconnected_returns_idle(self):
        """EV disconnected → idle regardless of SOC."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95, ev_connected=False), _MockEnergy()
        )
        assert strategy == "idle"

    def test_daily_target_reached_solar_continues(self):
        """Daily target reached during day → solar continues (free surplus)."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95, solar_power=3000), _MockEnergy(daily_ev=10.0)
        )
        # Solar keeps charging past target — target only limits night (grid) charging
        assert strategy == "battery_assist"

    def test_daily_target_reached_night_idle(self):
        """Daily target reached during night → idle (don't charge from grid)."""
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy(daily_ev=10.0)
        )
        assert strategy == "idle"

    def test_night_mode_returns_night_grid(self):
        """Night mode active → night_grid regardless of SOC."""
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy()
        )
        assert strategy == "night_grid"

    def test_charge_mode_off_returns_disabled(self):
        """Charge mode = 'off' → "disabled" (not generic "idle").

        Post-v1.6.3 hotfix: explicit-off is a distinct strategy from
        the transient "idle" producers (Zone 1, solar<200W, target met).
        The state machine routes "disabled" to SOLAR_IDLE (terminal stop)
        while "idle" stays in CHARGING_ALLOWED (warm, waiting). Same
        canonical EVBudgetStrategy.IDLE downstream, distinct upstream.
        Pre-C this was ``ev_charging_mode=off``; post-#277 Phase C the
        named ``charge_mode`` is the dispatch authority.
        """
        coord = _build_coordinator(config_overrides={
            "ev_chargers": [{"id": "ev_charger", "charge_mode": "off"}],
        })
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy(),
            charger_cfg={"id": "ev_charger", "charge_mode": "off"},
        )
        assert strategy == "disabled"

    # ``test_charging_mode_minpv_returns_min_pv`` removed in #277 Phase C:
    # the ``minpv`` legacy mode no longer dispatches to ``("min_pv", …)``
    # from ``_determine_charging_strategy``. Per the maintainer's
    # Phase C decision (Q1: zone-adaptive), legacy ``minpv`` users
    # migrated to ``min_plus_solar`` get zone-adaptive day behaviour;
    # the ``min_pv`` strategy value is now only reachable via the
    # night-grid → MIN_PV canonical-budget mapping in
    # ``_canonical_strategy_from_legacy``.

    def test_low_solar_returns_idle(self):
        """Solar < 200W → idle (not enough sun)."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(solar_power=150, battery_soc=80), _MockEnergy()
        )
        assert strategy == "idle"
        assert "200W" in _

    # --- Real-world: PROD config (priority_soc=90, collapsed Zone 2) (tests 14-15) ---

    def test_prod_config_soc80_battery_assist(self):
        """PROD: priority_soc=90 → SOC 80% is Zone 3 (>= buffer 70%), battery_assist."""
        coord = _build_coordinator(config_overrides={"battery_priority_soc": 90})
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "Zone 3" in reason

    def test_prod_config_soc65_idle(self):
        """PROD: priority_soc=90 → SOC 65% < buffer 70%, Zone 2 empty → falls to Zone 2 solar_only.

        With priority_soc=90, Zone 2 is [90%..70%) which is empty since 90 > 70.
        SOC 65% < buffer_soc 70% AND < priority_soc 90%, so it's Zone 1 → idle.
        """
        coord = _build_coordinator(config_overrides={"battery_priority_soc": 90})
        # SOC 65% < buffer_soc 70%, so Zone 3 check fails
        # SOC 65% < priority_soc 90%, so Zone 2 check also fails
        # Falls to Zone 1 → idle
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=65), _MockEnergy()
        )
        assert strategy == "idle"
        assert "Zone 1" in reason


class TestZoneDebounce:
    """Zone-transition debounce: prevents single-cycle blips from flipping
    strategy (and bouncing the battery Charging→Idle→Charging) when a user
    nudges a zone threshold or SOC oscillates near a boundary.
    """

    def test_first_call_adopts_zone_immediately(self):
        """No prior state → debouncer adopts the first observed zone."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert coord._stable_zone == 3

    def test_single_cycle_blip_is_held(self):
        """Zone 2 → Zone 1 for one cycle → still reported as Zone 2."""
        coord = _build_coordinator()
        # Settle in Zone 2
        coord._determine_charging_strategy(_make_power(battery_soc=50), _MockEnergy())
        assert coord._stable_zone == 2

        # Threshold change blips SOC into Zone 1 for a single cycle
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=29), _MockEnergy()
        )
        # Held at Zone 2 (solar_only) because the blip lasted only 1 cycle
        assert strategy == "solar_only"
        assert "Zone 2" in reason
        assert coord._stable_zone == 2
        assert coord._pending_zone == 1
        assert coord._pending_zone_count == 1

    def test_sustained_change_transitions_after_dwell(self):
        """Zone 2 → Zone 1 sustained for 2 cycles → transitions to Zone 1."""
        coord = _build_coordinator()
        coord._determine_charging_strategy(_make_power(battery_soc=50), _MockEnergy())

        # Cycle 1 at new zone: held
        coord._determine_charging_strategy(_make_power(battery_soc=20), _MockEnergy())
        assert coord._stable_zone == 2

        # Cycle 2 at new zone: applied
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=20), _MockEnergy()
        )
        assert strategy == "idle"
        assert "Zone 1" in reason
        assert coord._stable_zone == 1
        assert coord._pending_zone_count == 0

    def test_blip_reverts_resets_pending(self):
        """Zone 2 → 1 → 2 → pending cleared without applying transition."""
        coord = _build_coordinator()
        coord._determine_charging_strategy(_make_power(battery_soc=50), _MockEnergy())

        coord._determine_charging_strategy(_make_power(battery_soc=20), _MockEnergy())
        assert coord._pending_zone == 1

        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=50), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert coord._stable_zone == 2
        assert coord._pending_zone is None
        assert coord._pending_zone_count == 0

    def test_threshold_change_resets_pending(self):
        """Adjusting a threshold mid-flight clears any in-progress candidate
        so the post-change zone is evaluated from scratch."""
        coord = _build_coordinator()
        coord._determine_charging_strategy(_make_power(battery_soc=50), _MockEnergy())

        # Start a pending Zone 1 candidate
        coord._determine_charging_strategy(_make_power(battery_soc=20), _MockEnergy())
        assert coord._pending_zone == 1
        assert coord._pending_zone_count == 1

        # User raises priority_soc from 30 → 35; recompute with new thresholds
        coord.config["battery_priority_soc"] = 35
        coord._determine_charging_strategy(_make_power(battery_soc=50), _MockEnergy())

        # Pending cleared because thresholds changed
        assert coord._pending_zone is None
        assert coord._pending_zone_count == 0

    def test_debounce_cycles_configurable(self):
        """zone_debounce_cycles=1 disables hold (immediate transition)."""
        coord = _build_coordinator(config_overrides={"zone_debounce_cycles": 1})
        coord._determine_charging_strategy(_make_power(battery_soc=50), _MockEnergy())

        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=20), _MockEnergy()
        )
        assert strategy == "idle"
        assert coord._stable_zone == 1

    def test_priority_threshold_bump_no_battery_flap(self):
        """Real-world: user raises Priority SOC from 50 → 51 with SOC=50.

        Without debounce the strategy flips solar_only → idle for one cycle
        then back. With debounce, the brief Zone 2 → 1 blip is held so the
        battery stays in its current state.
        """
        coord = _build_coordinator(config_overrides={"battery_priority_soc": 50})
        # Settle in Zone 2 at SOC=50 (>= priority 50)
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=50), _MockEnergy()
        )
        assert strategy == "solar_only"

        # User bumps Priority SOC to 51. SOC=50 is now < priority → raw Zone 1.
        coord.config["battery_priority_soc"] = 51
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=50), _MockEnergy()
        )
        # Held at Zone 2 — no Charging→Idle blip
        assert strategy == "solar_only"
        assert "Zone 2" in reason


# ===========================================================================
# TestCalculateSolarEvBudget removed in Phase D.2 (#282): the
# ``_calculate_solar_ev_budget`` mixin method was deleted along with
# the other legacy budget primitives. The Zone 3/4 proportional ramp +
# measured-discharge semantics now live in
# ``flow_calculator.calculate_canonical_ev_budget`` (BATTERY_ASSIST
# branch) and are exercised by ``tests/scenarios/2026-05-29_budget_
# unify_battery_assist.yaml`` end-to-end and by the canonical-budget
# unit tests for the per-zone shape.


# TestAutoMode removed in #305: ``_auto_mode_strategy`` was deleted
# as dead code (no charge mode dispatched to it post-#277 Phase C).
# The previous 3 tests exercised the helper directly; if a future
# opt-in ``auto`` mode resurrects the forecast-aware switcher, restore
# both the method and its tests together from the #305 commit.


class TestSelfConsumptionStrategy:
    """Tests for self_consumption mode Zone 4 redirect."""

    def test_zone4_redirects_battery_charge(self):
        """Zone 4 (SOC≥90%): don't subtract battery charge — redirect to EV."""
        coord = _build_coordinator(config_overrides={"ev_charging_mode": "self_consumption"})
        strategy, reason = coord._self_consumption_strategy(
            _make_power(solar=10000, home=500, battery_charge=2000, battery_soc=95),
            _MockEnergy()
        )
        assert strategy == "solar_only"
        # surplus = solar(10000) - home(500) = 9500 (battery charge NOT subtracted)
        assert "9500" in reason

    def test_zone3_battery_charges_first(self):
        """Zone 3 (SOC<90%): battery charges first, EV gets leftover."""
        coord = _build_coordinator(config_overrides={"ev_charging_mode": "self_consumption"})
        strategy, reason = coord._self_consumption_strategy(
            _make_power(solar=5000, home=500, battery_charge=3000, battery_soc=75),
            _MockEnergy()
        )
        assert strategy == "solar_only"
        # surplus = solar(5000) - home(500) - battery(3000) = 1500
        assert "1500" in reason
