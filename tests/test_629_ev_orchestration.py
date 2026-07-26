"""#629 — EV orchestration decomposition slices (behaviour pins)."""
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.ev_night_targets import (
    build_night_target_map,
)


def _coord(chargers=None, config=None, fallback_logged=None,
           soc_need=5.5, daily_kwh=2.0):
    c = MagicMock()
    c.config = config or {}
    c._ev_devices = chargers or {}
    c._night_global_fallback_logged = (
        set() if fallback_logged is None else fallback_logged)
    c._resolve_charger_soc = MagicMock(return_value=80.0)
    c._calculate_remaining_need = MagicMock(return_value=soc_need)
    c._charger_daily_kwh = MagicMock(return_value=daily_kwh)
    return c


class TestNightTargetMap629:
    def test_kwh_mode_per_charger_target_minus_delivered(self):
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a", "daily_ev_target": 8}]},
                   daily_kwh=3.0)
        assert build_night_target_map(c, MagicMock()) == {"a": 5.0}

    def test_kwh_mode_clamps_at_zero(self):
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a", "daily_ev_target": 2}]},
                   daily_kwh=9.0)
        assert build_night_target_map(c, MagicMock()) == {"a": 0}

    def test_global_inheritance_logged_once(self):
        logged = set()
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a"}], "daily_ev_target": 12},
                   fallback_logged=logged, daily_kwh=2.0)
        out = build_night_target_map(c, MagicMock())
        assert out == {"a": 10.0}
        assert logged == {"a"}                    # #259 surfaced once
        build_night_target_map(c, MagicMock())    # second cycle: no re-log
        assert logged == {"a"}

    def test_soc_mode_delegates_to_remaining_need(self):
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a", "ev_target_type": "soc"}]},
                   soc_need=6.25)
        out = build_night_target_map(c, MagicMock())
        assert out == {"a": 6.25}
        c._calculate_remaining_need.assert_called_once()
        _, kwargs = c._calculate_remaining_need.call_args
        assert kwargs.get("bound") == "min"       # the #245 floor, not max

    def test_unconfigured_charger_uses_global_default(self):
        c = _coord(chargers={"x": object()}, config={}, daily_kwh=0.0)
        assert build_night_target_map(c, MagicMock()) == {"x": 10}   # default 10


class TestNightNotificationTruth631:
    """(#631) The night-start notification must quote the SAME remaining the
    decision consumed (the per-charger map), not the stale config snapshot."""

    def _messages(self, data, config=None):
        from custom_components.solar_energy_management.coordinator.notifications import (
            NotificationManager)
        nm = NotificationManager.__new__(NotificationManager)
        nm.config = config or {"daily_ev_target": 8}
        nm.hass = MagicMock()
        return NotificationManager._get_notification_messages(
            nm, "night_charging_active", data)

    def test_prefers_per_charger_map_value(self):
        m = self._messages({"daily_ev_energy": 0.0, "_charger_id": "ev_charger",
                            "night_remaining_map": {"ev_charger": 2.0}})
        assert "2.0" in m["mobile"]           # live map, not the config 8

    def test_fleet_fallback_sums_map(self):
        m = self._messages({"daily_ev_energy": 0.0, "_charger_id": None,
                            "night_remaining_map": {"a": 1.5, "b": 2.5}})
        assert "4.0" in m["mobile"]

    def test_no_map_falls_back_to_config(self):
        m = self._messages({"daily_ev_energy": 3.0, "_charger_id": None,
                            "night_remaining_map": {}})
        assert "5.0" in m["mobile"]           # 8 - 3 legacy path


class TestNightTopUpRate630:
    """(#630) The plain night top-up runs at the peak-managed headroom rate,
    bounded [min, max]; without peak info it keeps the legacy Min creep."""

    def _plan(self, **kw):
        from datetime import datetime
        from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
            plan_night_charge)
        args = dict(now=datetime(2026, 7, 24, 1, 0),
                    remaining_to_min_kwh=8.0, min_amps=10, max_amps=32,
                    watts_per_amp=690.0, night_end="06:00")
        args.update(kw)
        return plan_night_charge(**args)

    def test_top_up_uses_peak_managed_rate(self):
        p = self._plan(peak_managed_amps=16)
        assert p.top_up_amps == 16

    def test_top_up_clamped_to_charger_limits(self):
        assert self._plan(peak_managed_amps=64).top_up_amps == 32
        assert self._plan(peak_managed_amps=4).top_up_amps == 10

    def test_no_peak_info_keeps_legacy_floor(self):
        p = self._plan(peak_managed_amps=None)
        assert p.top_up_amps == 0                 # decide falls back to Min

    def test_decide_plain_topup_uses_rate(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerView, ChargerPower, ChargerEnergy, FleetContext)
        view = ChargerView(
            power=ChargerPower(charger_id="c1", power_w=0.0, connected=True),
            energy=ChargerEnergy(charger_id="c1"),
            mode="min_plus_solar",
            config={"ev_min_current": 10, "ev_phases": 3, "ev_max_current": 32},
            fleet=FleetContext(solar_w=0.0, home_w=500.0, battery_soc=60.0,
                               is_night=True),
            target_kwh=8.0,
            top_up_amps=16,
        )
        d = decide(view)
        assert d.commanded_amps == 16
        assert "peak-managed" in d.reason

    def test_decide_no_topup_info_keeps_min(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerView, ChargerPower, ChargerEnergy, FleetContext)
        view = ChargerView(
            power=ChargerPower(charger_id="c1", power_w=0.0, connected=True),
            energy=ChargerEnergy(charger_id="c1"),
            mode="min_plus_solar",
            config={"ev_min_current": 10, "ev_phases": 3, "ev_max_current": 32},
            fleet=FleetContext(solar_w=0.0, home_w=500.0, battery_soc=60.0,
                               is_night=True),
            target_kwh=8.0,
        )
        d = decide(view)
        assert d.commanded_amps == 10          # legacy Min creep preserved


# (#629 slice 2) TestSolarBudgetDistribution629 — REMOVED in #651.
#
# Three tests over ``ev_night_targets.distribute_solar_budget``, which
# read the canonical ``_cycle_ev_budget.net_w`` and handed it to
# ``SurplusController.distribute_ev_budget``. #629 slice 2 extracted that
# call into its own function and tested it carefully — correctly, but the
# whole chain terminated in ``pcc.budget_w``, which no consumer read. It
# was a well-factored no-op. Both functions are deleted; the live
# allocator is ``decide.self_consumption_surplus_w`` fed by
# ``_solar_committed_w_per_cycle``.
#
# Note what the extraction could not tell us: slice 2 made the dead path
# *cleaner*, which reads as progress. Structure is not reachability.


class TestNightEffectiveState629:
    """(#629 slice 3) The pure per-charger night tri-state resolution."""

    def _resolve(self, charging_state, pc_target, plan, base="BASE"):
        from custom_components.solar_energy_management.coordinator.ev_night_targets import (
            resolve_night_effective_state)
        return resolve_night_effective_state(
            base, charging_state, pc_target, plan,
            "NIGHT_ACTIVE", "TARIFF_WAIT", "TARGET_REACHED")

    def test_day_state_passes_through(self):
        assert self._resolve("SOLAR_ACTIVE", 5.0, None) == "BASE"

    def test_target_met_wins(self):
        assert self._resolve("NIGHT_ACTIVE", 0.05, None) == "TARGET_REACHED"
        assert self._resolve("TARIFF_WAIT", None, None) == "TARGET_REACHED"

    def test_wait_vs_active_follows_plan(self):
        plan = MagicMock(should_wait_for_cheap=True)
        assert self._resolve("NIGHT_ACTIVE", 5.0, plan) == "TARIFF_WAIT"
        plan.should_wait_for_cheap = False
        assert self._resolve("TARIFF_WAIT", 5.0, plan) == "NIGHT_ACTIVE"

    def test_no_plan_defaults_active(self):
        # pc_target > 0.1 but plan missing (defensive) → charge, don't wait
        assert self._resolve("NIGHT_ACTIVE", 5.0, None) == "NIGHT_ACTIVE"


class TestPerChargerMode629:
    """(#629 slice 4) Mode resolution + mismatch diagnostic."""

    def test_resolves_and_no_warning_on_default(self, caplog):
        import logging
        from custom_components.solar_energy_management.coordinator.ev_night_targets import (
            resolve_per_charger_mode)
        c = MagicMock()
        c._effective_charge_mode_for = MagicMock(return_value="solar_only")
        with caplog.at_level(logging.WARNING):
            out = resolve_per_charger_mode(c, "c1", {"id": "c1"})   # no explicit mode
        assert out == "solar_only"
        assert "mode mismatch" not in caplog.text

    def test_warns_on_explicit_disagreement(self, caplog):
        import logging
        from custom_components.solar_energy_management.coordinator.ev_night_targets import (
            resolve_per_charger_mode)
        c = MagicMock()
        c._effective_charge_mode_for = MagicMock(return_value="off")
        with caplog.at_level(logging.WARNING):
            out = resolve_per_charger_mode(c, "c1", {"id": "c1", "charge_mode": "always_max"})
        assert out == "off"
        assert "mode mismatch" in caplog.text


class TestFloorDrivenNightTopUp634:
    """(#634) Mode = daytime axis; the "At least" floor is the guarantee."""

    def _night_view(self, mode, target_kwh, top_up_amps=0):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerView, ChargerPower, ChargerEnergy, FleetContext)
        return ChargerView(
            power=ChargerPower(charger_id="c1", power_w=0.0, connected=True),
            energy=ChargerEnergy(charger_id="c1"),
            mode=mode,
            config={"ev_min_current": 10, "ev_phases": 3, "ev_max_current": 32},
            fleet=FleetContext(solar_w=0.0, home_w=500.0, battery_soc=60.0,
                               is_night=True),
            target_kwh=target_kwh,
            top_up_amps=top_up_amps,
        )

    def test_solar_only_with_floor_tops_up_at_night(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerIntent)
        d = decide(self._night_view("solar_only", target_kwh=0.9))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 10
        assert "solar_only night" in d.reason        # honest mode in the reason

    def test_solar_only_floor_zero_never_grids_at_night(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerIntent)
        d = decide(self._night_view("solar_only", target_kwh=0.0))
        assert d.intent is ChargerIntent.IDLE         # classic #346 behaviour

    def test_solar_only_night_inherits_peak_managed_rate_630(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        d = decide(self._night_view("solar_only", target_kwh=5.0, top_up_amps=16))
        assert d.commanded_amps == 16                 # #630 rate flows through

    def test_min_plus_solar_night_unchanged(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerIntent)
        d = decide(self._night_view("min_plus_solar", target_kwh=2.0))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "min_plus_solar night" in d.reason

    def test_night_lane_gate_floor_aware(self):
        from custom_components.solar_energy_management.coordinator.charging_control import (
            ChargingStateMachine)
        sm = ChargingStateMachine.__new__(ChargingStateMachine)
        sm.hass = MagicMock()
        sm._night_enabled_cached = None      # debounce cache (first call commits)
        sm._night_enabled_pending = None
        sm._night_enabled_pending_cycles = 0
        sm.config = {"ev_chargers": [{"id": "a", "charge_mode": "solar_only",
                                      "daily_ev_target": 1.5}]}
        assert sm._any_night_charging_enabled() is True     # floor > 0 → night lane
        sm._night_enabled_cached = None      # fresh commit for the second config
        sm.config = {"ev_chargers": [{"id": "a", "charge_mode": "solar_only",
                                      "daily_ev_target": 0}]}
        assert sm._any_night_charging_enabled() is False    # floor 0 → classic


class TestPerChargerNightGate634:
    """(#634) The per-charger loop gate mirrors the state machine: solar_only
    joins night charging only with a floor set. This was the THIRD gate —
    caught live 2026-07-24 21:3x: decision charged, loop skipped the charger."""

    def _c(self, config=None):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator)
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = config or {}
        c._effective_charge_mode_for = lambda cfg: cfg.get("charge_mode", "solar_only")
        return c

    def test_solar_only_with_floor_participates(self):
        c = self._c()
        assert c._mode_allows_night_charging({"charge_mode": "solar_only",
                                              "daily_ev_target": 1.5}) is True

    def test_solar_only_floor_zero_skips(self):
        c = self._c()
        assert c._mode_allows_night_charging({"charge_mode": "solar_only",
                                              "daily_ev_target": 0}) is False

    def test_min_plus_solar_always_participates(self):
        c = self._c()
        assert c._mode_allows_night_charging({"charge_mode": "min_plus_solar"}) is True

    def test_global_floor_fallback(self):
        c = self._c(config={"daily_ev_target": 2})
        assert c._mode_allows_night_charging({"charge_mode": "solar_only"}) is True


class TestNightRatePrecedence630:
    """(#630 hold-back) The peak-managed rate must not be shadowed by the
    always-present window deadline: amps = max(deadline_required, top_up)."""

    def _decide(self, deadline_amps, top_up_amps):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerView, ChargerPower, ChargerEnergy, FleetContext)
        view = ChargerView(
            power=ChargerPower(charger_id="c1", power_w=0.0, connected=True),
            energy=ChargerEnergy(charger_id="c1"),
            mode="min_plus_solar",
            config={"ev_min_current": 10, "ev_phases": 3, "ev_max_current": 32},
            fleet=FleetContext(solar_w=0.0, home_w=500.0, battery_soc=60.0,
                               is_night=True),
            target_kwh=6.0,
            deadline_amps=deadline_amps, top_up_amps=top_up_amps,
        )
        return decide(view)

    def test_top_up_wins_over_lazy_deadline(self):
        d = self._decide(deadline_amps=10, top_up_amps=16)
        assert d.commanded_amps == 16
        assert "(peak-managed)" in d.reason

    def test_tight_deadline_wins_over_top_up(self):
        d = self._decide(deadline_amps=24, top_up_amps=16)
        assert d.commanded_amps == 24
        assert "(peak-managed)" not in d.reason

    def test_clamped_to_charger_max(self):
        d = self._decide(deadline_amps=10, top_up_amps=64)
        assert d.commanded_amps == 32


class TestLoadDrawReducesNightRate630:
    """(#630 review hold-back) Integration: a RUNNING cheap-hours load's live
    draw reduces the peak-managed rate the planner computes."""

    def test_grid_funded_draw_shrinks_top_up_amps(self):
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin)
        host = MagicMock()
        host.config = {"ev_max_current": 32, "ev_phases": 3}
        host._night_committed_w = 0.0
        # bind the real method
        import types
        host._compute_night_plan = types.MethodType(
            EVControlMixin._compute_night_plan, host)
        host._tariff_optimized_for = MagicMock(return_value=False)
        host._charger_target_time = MagicMock(return_value=None)
        host.time_manager.get_night_end_time = MagicMock(return_value="06:00")
        host.time_manager.get_night_window_hours = MagicMock(return_value=8.0)
        host._get_peak_limit_w = MagicMock(return_value=12000)
        host._expected_night_home_w = MagicMock(return_value=600)
        host._ev_device = None
        cfg = {"ev_min_current": 6, "ev_phases": 3}

        host._surplus_controller.grid_funded_draw_w = MagicMock(return_value=0.0)
        free = host._compute_night_plan(cfg, 6.0)
        host._surplus_controller.grid_funded_draw_w = MagicMock(return_value=3000.0)
        loaded = host._compute_night_plan(cfg, 6.0)
        assert loaded.top_up_amps < free.top_up_amps   # the load reserved its draw
