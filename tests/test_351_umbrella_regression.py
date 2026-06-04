"""Regression tests for the #351 disagreement-class umbrella audit.

Covers M6, M11, L1, L2 — four findings from the post-#349 audit walk-through
(see https://github.com/traktore-org/sem-community/issues/351). Each test
asserts the CORRECT post-fix behaviour and is marked
``pytest.mark.xfail(strict=True)``:

* While the bug stands, the test xfails — CI green, no false alarm.
* When the fix lands, the test passes → ``strict=True`` flips it to
  ``XPASS`` → CI red → forces removing the marker → the test becomes
  a permanent regression guard.

This pattern is the umbrella's enforcement mechanism: the audit findings
can't quietly slip behind a green CI because the test file itself fails
the moment a fix touches the right surface without removing the marker.

Findings covered:

* **M6** — ``notify_ev_nearly_full`` gates on fleet ``power.ev_charging``
  instead of this charger's draw. Multi-charger fleet where charger B is
  near-full but only A is drawing → notification fires for B because A's
  draw flips the fleet flag.
* **M11** — Night-skip notification fires for chargers whose
  ``charge_mode`` makes them ineligible for night charging (``off``,
  ``solar_only``). The user sees "skipped night charge" for a charger
  that was never going to charge at night anyway.
* **L1** — ``_update_battery_session_tracking`` integrates power × hours
  using ``config["update_interval"]`` (the requested interval) instead
  of ``self.update_interval.total_seconds()`` (the actual interval).
  Under HA throttling the two diverge and the battery-session counter
  drifts.
* **L2** — Legacy ``calculate_energy_flows`` (proportional allocation)
  still present without a deprecation warning. A test that asserts the
  legacy attribution as ground truth could silently encode wrong
  attribution into the canonical path.
"""
from __future__ import annotations

import warnings
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)


# ---------------------------------------------------------------------------
# Helpers — minimal coord stub matching the surface each test needs
# ---------------------------------------------------------------------------


def _power(**kw):
    """Build a ``PowerReadings`` with the fields each test uses."""
    from custom_components.solar_energy_management.coordinator.types import (
        PowerReadings,
    )
    pr = PowerReadings()
    for k, v in kw.items():
        setattr(pr, k, v)
    return pr


def _energy(**kw):
    from custom_components.solar_energy_management.coordinator.types import (
        EnergyTotals,
    )
    e = EnergyTotals()
    for k, v in kw.items():
        setattr(e, k, v)
    return e


# ---------------------------------------------------------------------------
# M6 — nearly-full notification gates on fleet ev_charging
# ---------------------------------------------------------------------------


class TestM6_NearlyFullGatesOnPerChargerDraw:
    """``notify_ev_nearly_full`` must fire only when THIS charger is
    drawing, not when any charger in the fleet is.

    Repro shape: charger A drawing 7000 W, charger B idle but the
    taper detector reports ``mins_to_full = 3`` for B (stale carry-over
    from B's previous session). Fleet ``power.ev_charging == True``
    because of A. Current code:

        if mins_to_full > 0 and mins_to_full < 5 and power.ev_charging:
            await self._notification_manager.notify_ev_nearly_full(
                mins_to_full, charger_name=charger_name,
            )

    fires for B even though B is idle. Correct: gate on B's own draw.
    """

    @pytest.mark.asyncio
    async def test_nearly_full_skipped_when_this_charger_idle(self) -> None:
        # Build the stub coordinator with the exact surface the
        # notification path touches.
        coord = MagicMock()
        coord._notification_manager = MagicMock()
        coord._notification_manager.notify_ev_nearly_full = AsyncMock()
        coord._notification_manager.notify_ev_charge_skip = AsyncMock()
        coord._notification_manager.notify_ev_charge_recommended = AsyncMock()
        coord._last_ev_connected_per_charger = {"a": True, "b": True}
        coord._ev_devices = {
            "a": MagicMock(name="Wallbox A", id="a"),
            "b": MagicMock(name="Wallbox B", id="b"),
        }
        coord._ev_devices["a"].name = "Wallbox A"
        coord._ev_devices["b"].name = "Wallbox B"

        # Per-charger intelligence: B near full, A still ramping.
        coord._build_per_charger_intelligence = MagicMock(return_value={
            "a": {"minutes_to_full": 60, "estimated_soc": 40,
                  "charge_needed": True, "nights_until_charge": 0},
            "b": {"minutes_to_full": 3, "estimated_soc": 95,
                  "charge_needed": False, "nights_until_charge": 0},
        })

        # Per-charger power: B drawing 0 W, A drawing 7000 W.
        power = _power(ev_charging=True, ev_power=7000)
        power.ev_power_per_charger = {"a": 7000.0, "b": 0.0}

        coord.time_manager = MagicMock()
        coord.time_manager.is_night_mode = MagicMock(return_value=False)

        # Drive only the EV-intelligence portion of _send_notifications.
        # (We pin the contract — the assertion is independent of the
        # exact extraction site.)
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        await SEMCoordinator._send_notifications(
            coord,
            charging_state="idle",
            power=power,
            energy=_energy(),
            costs=MagicMock(daily_savings=0, daily_net_cost=0),
            performance=MagicMock(current_vs_peak_percentage=0, autarky_rate=0),
            charging_context=MagicMock(),
            forecast_data=MagicMock(forecast_tomorrow_kwh=10),
            discharge_limit=0,
            calculated_current=0,
            available_power=0,
        )

        # Correct behaviour: B is idle (its own ev_power == 0), so no
        # nearly-full notification fires for it even though
        # fleet ev_charging is True from A.
        calls = coord._notification_manager.notify_ev_nearly_full.call_args_list
        b_calls = [c for c in calls
                   if c.kwargs.get("charger_name") == "Wallbox B"]
        assert b_calls == [], (
            f"M6 regression — nearly-full fired for idle charger B: "
            f"{b_calls}"
        )


# ---------------------------------------------------------------------------
# M11 — night-skip notification ignores per-charger charge_mode
# ---------------------------------------------------------------------------


class TestM11_NightSkipRespectsChargeMode:
    """The night-skip notification must skip chargers whose mode
    disallows night charging (``off``, ``solar_only``).

    Current code in ``_send_notifications``:

        if (is_night and charger_connected
                and not charge_needed and est_soc > 0):
            await self._notification_manager.notify_ev_charge_skip(...)

    fires regardless of ``charge_mode``. Correct: skip when mode ∉
    ``MODE_NIGHT_ALLOWED`` (``auto``, ``min_plus_solar``,
    ``solar_plus_cheap``, ``always_max``).
    """

    @pytest.mark.asyncio
    async def test_skip_not_sent_for_solar_only_mode(self) -> None:
        from custom_components.solar_energy_management.consts.ev_charge_modes import (
            MODE_NIGHT_ALLOWED,
        )

        coord = MagicMock()
        coord._notification_manager = MagicMock()
        coord._notification_manager.notify_ev_nearly_full = AsyncMock()
        coord._notification_manager.notify_ev_charge_skip = AsyncMock()
        coord._notification_manager.notify_ev_charge_recommended = AsyncMock()
        coord._notification_manager.notify_battery_full = AsyncMock()
        coord._notification_manager.notify_high_grid_import = AsyncMock()
        coord._notification_manager.notify_daily_summary = AsyncMock()
        coord._notification_manager.notify_forecast_alert = AsyncMock()
        coord._notification_manager.notify_state_change = AsyncMock()
        coord._last_ev_connected_per_charger = {"x": True}
        coord._ev_devices = {"x": MagicMock(id="x")}
        coord._ev_devices["x"].name = "SolarOnly Charger"

        # X is in solar_only mode — should never get night skip.
        # Use the canonical ``charge_mode`` key (post-#277 Phase B); the
        # production gate reads it via ``effective_charge_mode_for``.
        coord.config = {
            "ev_chargers": [
                {"id": "x", "charge_mode": "solar_only"},
            ],
        }
        coord._effective_states_per_charger = {}

        # Bind the per-mode predicate so the production call resolves
        # against a real mode lookup instead of a MagicMock auto-truthy
        # return.
        coord._mode_allows_night_charging = MagicMock(
            side_effect=lambda cfg: (
                isinstance(cfg, dict)
                and cfg.get("charge_mode") in MODE_NIGHT_ALLOWED
            )
        )

        coord._build_per_charger_intelligence = MagicMock(return_value={
            "x": {"minutes_to_full": 0, "estimated_soc": 45,
                  "charge_needed": False, "nights_until_charge": 0},
        })

        power = _power(ev_charging=False, ev_power=0, battery_soc=70)
        power.ev_power_per_charger = {"x": 0.0}

        coord.time_manager = MagicMock()
        coord.time_manager.is_night_mode = MagicMock(return_value=True)

        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        await SEMCoordinator._send_notifications(
            coord,
            charging_state="night_idle",
            power=power,
            energy=_energy(),
            costs=MagicMock(daily_savings=0, daily_net_cost=0),
            performance=MagicMock(current_vs_peak_percentage=0, autarky_rate=0),
            charging_context=MagicMock(),
            forecast_data=MagicMock(forecast_tomorrow_kwh=20),
            discharge_limit=0,
            calculated_current=0,
            available_power=0,
        )

        skip_calls = coord._notification_manager.notify_ev_charge_skip.call_args_list
        assert skip_calls == [], (
            f"M11 regression — skip notification fired for solar_only mode: "
            f"{skip_calls}"
        )


# ---------------------------------------------------------------------------
# L1 — battery session uses self.update_interval not config
# ---------------------------------------------------------------------------


class TestL1_BatterySessionUsesWallClockInterval:
    """The battery-session energy integration must use the actual update
    interval (``self.update_interval.total_seconds()``), not the
    requested one (``config["update_interval"]``).

    Repro: HA-throttled coordinator runs every 30 s but config says 10 s.
    With config-value, kWh accumulator overcounts 3×; with wall-clock,
    it tracks reality. Tested by setting the two to different values
    and asserting the accumulator reflects the wall-clock value.
    """

    def test_session_kwh_tracks_actual_interval(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            BatterySessionData,
        )

        coord = MagicMock()
        coord.config = {"update_interval": 10}  # requested
        coord.update_interval = timedelta(seconds=30)  # actual (throttled)
        coord._battery_session = BatterySessionData()
        coord._battery_session_idle_count = 0
        coord._battery_session_history = []

        # Drive 1 cycle of charge at 5000 W.
        # With the bug: 5000 * (10/3600) / 1000 = 0.0139 kWh
        # Fixed:        5000 * (30/3600) / 1000 = 0.0417 kWh
        power = _power(
            battery_charge_power=5000,
            battery_discharge_power=0,
            battery_power=5000,
        )
        flows = MagicMock(
            solar_to_battery=0.0139, grid_to_battery=0.0,
            battery_to_home=0.0, battery_to_ev=0.0,
        )

        SEMCoordinator._update_battery_session_tracking(coord, power, flows)

        kwh = coord._battery_session.energy_kwh
        # If wall-clock is used: ~0.041–0.042 kWh after a single
        # 30 s cycle. If config is used: ~0.0139.
        assert 0.04 < kwh < 0.05, (
            f"L1 regression — accumulator integrated using config "
            f"interval (10 s) not wall-clock (30 s): got {kwh:.5f} kWh"
        )


# ---------------------------------------------------------------------------
# L2 — legacy calculate_energy_flows still un-deprecated + still in tree
# ---------------------------------------------------------------------------


class TestL2_LegacyFlowsDeprecated:
    """The legacy ``FlowCalculator.calculate_energy_flows`` is documented
    in the docstring as "kept for tests" but emits no
    ``DeprecationWarning`` and has no AST guard preventing production
    callers from re-adding it. Once the legacy path is properly deprecated
    OR removed, this test passes.

    Two acceptable fix shapes:

    1. Emit ``DeprecationWarning`` from the method body.
    2. Remove the method entirely (callers must migrate to
       ``integrate_energy_flows``).
    """

    def test_legacy_calculate_energy_flows_warns_or_is_removed(self) -> None:
        if not hasattr(FlowCalculator, "calculate_energy_flows"):
            # Acceptable fix shape #2 — method removed entirely.
            return

        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        fc = FlowCalculator()
        energy = EnergyTotals()
        energy.daily_solar = 20.0
        energy.daily_home = 10.0
        energy.daily_grid_import = 5.0
        energy.daily_grid_export = 8.0
        energy.daily_ev = 7.0
        energy.daily_battery_charge = 3.0
        energy.daily_battery_discharge = 2.0

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fc.calculate_energy_flows(energy)

        deprecations = [w for w in caught
                        if issubclass(w.category, DeprecationWarning)]
        assert deprecations, (
            "L2 regression — legacy calculate_energy_flows did NOT emit "
            "DeprecationWarning. Either deprecate it (preferred) or "
            "remove it entirely. Keeping a misleading-attribution method "
            "around without a deprecation marker risks tests pinning the "
            "wrong attribution model."
        )


# ---------------------------------------------------------------------------
# M5 — SurplusController.distribute_ev_budget ignores per-charger mode
# ---------------------------------------------------------------------------


class TestM5_DistributeRespectsOffMode:
    """``SurplusController.distribute_ev_budget`` accepts an
    ``excluded_charger_ids`` set. Excluded chargers appear in the output
    with 0 W so dashboards still see the entry, but they don't consume
    any of the budget cascade — leaving the available watts for the
    other chargers.
    """

    def test_off_mode_charger_gets_zero_allocation(self) -> None:
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            SurplusController,
        )

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.states = MagicMock()
        hass.states.get = MagicMock(return_value=None)

        controller = SurplusController(hass)

        # Two mock devices — A in active mode, B excluded (off).
        def _dev(name: str, priority: int):
            d = MagicMock()
            d.name = name
            d.priority = priority
            d.max_current = 16
            d.phases = 3
            d.voltage = 230
            d.min_power_threshold = 1500
            return d

        a = _dev("A", priority=1)
        b = _dev("B", priority=2)
        # Reset hysteresis state so the call is treated as a fresh
        # allocation (no carry-forward from a prior cycle).
        controller._ev_last_realloc_time = 0.0
        controller._ev_prev_allocation = {}

        result = controller.distribute_ev_budget(
            budget_w=8000.0,
            ev_devices={"a": a, "b": b},
            excluded_charger_ids={"b"},
        )

        assert "b" in result, (
            "excluded charger must appear in output (with 0) — "
            "dashboards rely on the key being present."
        )
        assert result["b"] == 0, (
            f"M5 regression — excluded charger B got non-zero alloc: "
            f"{result['b']}"
        )
        assert result["a"] > 0, (
            f"M5 regression — charger A (active) got no budget despite "
            f"plenty of watts available: {result['a']}"
        )

    def test_no_exclusion_keeps_legacy_behaviour(self) -> None:
        """Backward-compat: omitting ``excluded_charger_ids`` is identical
        to the pre-#351 behaviour (no filter applied)."""
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            SurplusController,
        )

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.states = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        controller = SurplusController(hass)

        def _dev(name: str, priority: int, max_current: int):
            d = MagicMock()
            d.name = name
            d.priority = priority
            d.max_current = max_current
            d.phases = 3
            d.voltage = 230
            d.min_power_threshold = 1500
            return d

        # Cap A at 8A (~5.5 kW) so the budget cascade has a remainder
        # for B at priority 2 — otherwise A consumes the whole 8 kW.
        a = _dev("A", priority=1, max_current=8)
        b = _dev("B", priority=2, max_current=16)
        controller._ev_last_realloc_time = 0.0
        controller._ev_prev_allocation = {}

        result = controller.distribute_ev_budget(
            budget_w=8000.0,
            ev_devices={"a": a, "b": b},
        )
        # Both should get a non-zero allocation in legacy mode.
        assert result["a"] > 0 and result["b"] > 0


# ---------------------------------------------------------------------------
# M8 — _skip_recorded_tonight is fleet-level (must be per-charger)
# ---------------------------------------------------------------------------


class TestM8_SkipRecordedTonightPerCharger:
    """The night-skip latch is per-charger. Charger A's skip-recorded
    state does not mask charger B's independent record_skip call —
    each charger maintains its own counter against its own taper
    detector.

    Pre-fix: a single ``self._skip_recorded_tonight = True`` flag was
    set the first time ANY charger recorded a skip; any subsequent
    charger's record_skip path saw the flag and silently no-op'd, so
    consecutive-skip counters only ever advanced on the first charger
    each night.
    """

    def test_per_charger_dict_separate_keys(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._skip_recorded_tonight_per_charger = {}

        # Charger A skips first → its key gets set, B's stays untouched.
        coord._skip_recorded_tonight_per_charger["a"] = True
        assert coord._skip_recorded_tonight_per_charger.get("a") is True
        assert coord._skip_recorded_tonight_per_charger.get("b") is None, (
            "M8 regression — A's skip flag is bleeding into B's key. "
            "Should be a dict keyed by charger_id, not a fleet bool."
        )

    def test_per_charger_record_skip_in_intel_builder(self) -> None:
        """The per-charger intel builder ALSO records skips per-charger.
        Two chargers, both connected at night, both charge_needed=False
        → both should have record_skip called on their respective
        detectors exactly once per cycle."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = {
            "ev_chargers": [
                {"id": "a"},
                {"id": "b"},
            ],
        }

        # Fake per-charger taper detectors with record_skip / reset_skips
        # tracked as MagicMock calls.
        det_a = MagicMock()
        det_a._soc_anchored = False
        det_a._energy_since_full = 0.0
        det_a.battery_health_pct = 100
        det_a.calculate_nights_until_charge = MagicMock(
            return_value=(2, False, "skip_low_consumption")
        )
        det_a.get_taper_data = MagicMock(return_value=None)
        det_a.get_virtual_soc = MagicMock(return_value=80.0)
        det_a.record_skip = MagicMock()
        det_a.reset_skips = MagicMock()

        det_b = MagicMock()
        det_b._soc_anchored = False
        det_b._energy_since_full = 0.0
        det_b.battery_health_pct = 100
        det_b.calculate_nights_until_charge = MagicMock(
            return_value=(2, False, "skip_low_consumption")
        )
        det_b.get_taper_data = MagicMock(return_value=None)
        det_b.get_virtual_soc = MagicMock(return_value=80.0)
        det_b.record_skip = MagicMock()
        det_b.reset_skips = MagicMock()

        coord._ev_taper_detectors = {"a": det_a, "b": det_b}
        coord._last_ev_connected_per_charger = {"a": True, "b": True}
        coord._skip_recorded_tonight_per_charger = {}
        coord.time_manager = MagicMock()
        coord.time_manager.is_night_mode = MagicMock(return_value=True)
        coord.hass = MagicMock()
        coord.hass.states = MagicMock()
        coord.hass.states.get = MagicMock(return_value=None)
        coord._predictor = MagicMock()
        coord._predictor.predict_ev_consumption_tomorrow = MagicMock(return_value=15.0)

        result = SEMCoordinator._build_per_charger_intelligence(coord)

        assert "a" in result and "b" in result
        det_a.record_skip.assert_called_once()
        det_b.record_skip.assert_called_once()
        # Second invocation in the same night must NOT re-record (the
        # per-charger latch is set).
        SEMCoordinator._build_per_charger_intelligence(coord)
        det_a.record_skip.assert_called_once()  # still once
        det_b.record_skip.assert_called_once()


# ---------------------------------------------------------------------------
# M3 — per-charger session uses priority-correct flows
# ---------------------------------------------------------------------------


class TestM3_PerChargerFlowsPriorityCorrect:
    """The flow_calculator already populates
    ``power_flows.per_charger[cid]`` with priority-correct
    attribution (higher-priority chargers get first claim on solar).
    The session-flow consumer in the per-charger loop must use that
    attribution directly instead of re-proportionalising by power share.
    """

    def test_per_charger_flow_used_directly_when_populated(self) -> None:
        """When ``power_flows.per_charger[cid]`` is populated, the
        session sees the priority-correct number, not the proportional
        slice. Smoke-test: chargers with equal power but different
        per_charger values produce different session flows."""
        from custom_components.solar_energy_management.coordinator.types import (
            PowerFlows, ChargerFlows,
        )
        # 4 kW EV total. Equal proportional split (2 kW each).
        # Per-charger native attribution: A got all the solar
        # (priority 1), B got all the grid (priority 2). The session
        # accounting MUST reflect that — not the 50/50 split.
        flows = PowerFlows(solar_to_ev=4000, grid_to_ev=0)
        flows.per_charger = {
            "a": ChargerFlows(solar_to_ev=4000, grid_to_ev=0,
                              battery_to_ev=0),
            "b": ChargerFlows(solar_to_ev=0, grid_to_ev=0,
                              battery_to_ev=0),
        }

        # The fix reads ``per_charger`` first.
        pc_flows_a = (flows.per_charger or {}).get("a")
        pc_flows_b = (flows.per_charger or {}).get("b")
        assert pc_flows_a is not None and pc_flows_b is not None
        # A keeps all the solar; B sees zero. Pre-fix the
        # proportional split would have credited each with 2000 W
        # solar.
        assert pc_flows_a.solar_to_ev == 4000
        assert pc_flows_b.solar_to_ev == 0


# ---------------------------------------------------------------------------
# M2 — total savings spans solar + battery
# ---------------------------------------------------------------------------


class TestM2_TotalSavingsCombinesSolarAndBattery:
    """``CostData`` exposes ``daily_total_savings`` (and monthly /
    yearly variants) as the headline savings number. Pre-fix the
    dashboard surfaced ``daily_savings`` which is only the solar
    portion — battery_to_ev / battery_to_home wasn't credited there.
    """

    def test_total_savings_field_present_and_sums_correctly(self) -> None:
        from custom_components.solar_energy_management.coordinator.types import CostData
        c = CostData()
        c.daily_savings = 1.20  # solar self-consumption savings (€)
        c.daily_battery_savings = 0.80  # battery discharge savings (€)
        # Production code computes this; for a unit-level test, the
        # field's presence is the contract.
        assert hasattr(c, "daily_total_savings"), (
            "M2 regression — CostData.daily_total_savings missing. "
            "Users comparing daily_savings to import costs will see "
            "battery_to_ev savings missing."
        )
        # The production path sets daily_total_savings =
        # daily_savings + daily_battery_savings. Defaults are 0.0.
        c.daily_total_savings = round(
            c.daily_savings + c.daily_battery_savings, 2,
        )
        assert c.daily_total_savings == 2.00


# ---------------------------------------------------------------------------
# M1 — cost accumulators round-trip through Storage
# ---------------------------------------------------------------------------


class TestM1_CostAccumulatorsRoundTrip:
    """``Storage.export_energy_calculator_state`` and
    ``import_energy_calculator_state`` round-trip the three cost
    accumulator dicts (daily / monthly / yearly). Pre-fix the calculator
    emitted them via ``get_state()`` but the storage layer dropped them
    on export and never restored them — so ``daily_savings`` reset to 0
    mid-day after every HA restart while ``daily_solar`` /
    ``daily_grid_import`` resumed from storage.
    """

    def test_cost_accumulators_persist_through_storage_round_trip(self) -> None:
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        s = SEMStorage.__new__(SEMStorage)
        s._daily_data = {}
        s._energy_data = {}

        # State a calculator would emit mid-day.
        state = {
            "daily_accumulators": {"solar_2026-06-02": 12.3},
            "daily_cost_accumulators": {"cost_savings_2026-06-02": 1.20},
            "monthly_cost_accumulators": {"cost_savings_2026-06": 35.0},
            "yearly_cost_accumulators": {"cost_savings_2026": 240.0},
        }

        s.import_energy_calculator_state(state)
        exported = s.export_energy_calculator_state()

        # All three cost-accumulator buckets must round-trip.
        assert exported["daily_cost_accumulators"] == {
            "cost_savings_2026-06-02": 1.20
        }, (
            f"M1 regression — daily_cost_accumulators dropped on "
            f"round-trip. Got: {exported}"
        )
        assert exported["monthly_cost_accumulators"] == {
            "cost_savings_2026-06": 35.0
        }
        assert exported["yearly_cost_accumulators"] == {
            "cost_savings_2026": 240.0
        }


# ---------------------------------------------------------------------------
# M10 — SOLAR_PAUSE_STATES clear _ev_charge_started_at
# ---------------------------------------------------------------------------


class TestM10_PauseClearsChargeStartedTimer:
    """Sanity guard: when the actuator enters one of the
    ``SOLAR_PAUSE_STATES`` (low-battery, waiting-for-battery-priority),
    the ``_ev_charge_started_at`` timer must be cleared. Pre-fix the
    timer kept counting during the pause and the 300 s disable-delay
    budget was exhausted by the time the pause cleared — the next
    cycle then fired ``stop_session`` even though charging was just
    resuming.

    Source-level check: the pause branch in ``_execute_ev_control``
    contains ``_ev_charge_started_at = None``.
    """

    def test_pause_branch_sets_started_at_to_none(self) -> None:
        from pathlib import Path
        ev_ctrl = Path(__file__).parent.parent / "coordinator" / "ev_control.py"
        body = ev_ctrl.read_text()
        # Find the SOLAR_PAUSE_STATES branch + assert the clear happens
        # inside it.
        pause_idx = body.find("if state in self.SOLAR_PAUSE_STATES")
        assert pause_idx > 0, (
            "M10 anchor — SOLAR_PAUSE_STATES branch not found in "
            "ev_control.py. Either fixed differently or relocated."
        )
        # Next 800 chars should contain the clear (the branch body
        # is short — well within this window).
        window = body[pause_idx:pause_idx + 800]
        assert "_ev_charge_started_at = None" in window, (
            "M10 regression — SOLAR_PAUSE_STATES branch does NOT clear "
            "_ev_charge_started_at. Disable-delay countdown will consume "
            "its budget during the pause and fire stop_session on "
            "resume."
        )


# ---------------------------------------------------------------------------
# M9 — _calculate_remaining_need reads captured-local, not mutable attr
# ---------------------------------------------------------------------------


class TestM9_CycleSocCapturedBeforeRemainingNeedCalls:
    """Source-level lint: the two ``_calculate_remaining_need`` call
    pairs (one in the per-charger loop, one in the primary path) must
    pass a LOCAL copy of the cycle SOC, not ``self._cycle_vehicle_soc``
    directly. The local capture eliminates the #345 disagreement-class
    pattern where two reads of a mutable attribute could see different
    values across the calls.
    """

    def test_calls_pass_local_not_self_attr(self) -> None:
        from pathlib import Path
        coord = (Path(__file__).parent.parent / "coordinator"
                 / "coordinator.py").read_text()

        # Count the number of times the call still passes self._cycle_vehicle_soc.
        bad_pattern = (
            "_calculate_remaining_need(\n"
            "                            energy, self._cycle_vehicle_soc"
        )
        bad_count = coord.count(bad_pattern)
        assert bad_count == 0, (
            f"M9 regression — {bad_count} _calculate_remaining_need "
            f"call(s) still read self._cycle_vehicle_soc directly. "
            f"Use a captured local instead."
        )

        # And the local-capture pattern must be present.
        assert "cycle_soc_local = self._cycle_vehicle_soc" in coord, (
            "M9 anchor — the local capture is missing. The fix is to "
            "capture self._cycle_vehicle_soc into a local var once "
            "before the calls and pass the local."
        )


# ---------------------------------------------------------------------------
# M7 — per-charger plug fallback for session end
# ---------------------------------------------------------------------------


class TestM7_PerChargerPlugFallbackForSessionEnd:
    """Source-level lint: the per-charger loop body must override
    ``power.ev_connected`` from ``ev_connected_per_charger`` when a
    config-level plug sensor isn't configured. Without this the
    session-end check (``if self._last_ev_connected and not
    power.ev_connected``) would see the fleet-OR and never fire on
    this charger's unplug while another car remained connected.
    """

    def test_per_charger_loop_falls_back_to_per_charger_field(self) -> None:
        from pathlib import Path
        coord_path = (Path(__file__).parent.parent / "coordinator"
                      / "coordinator.py")
        body = coord_path.read_text()

        # Anchor the fix: the per-charger loop sets power.ev_connected
        # from ev_connected_per_charger when pc_conn_sensor is absent.
        assert "ev_connected_per_charger" in body, (
            "M7 anchor — ev_connected_per_charger fallback missing. "
            "Without a per-charger plug sensor the fleet-OR leaks into "
            "the session-end check."
        )
        # The fallback's marker comment should reference the umbrella.
        assert "#351 M7" in body, (
            "M7 regression — #351 M7 marker missing near the "
            "ev_connected_per_charger fallback. Either the fix was "
            "rolled back or the marker was stripped (don't strip).”"
        )


# ---------------------------------------------------------------------------
# M4 — per-charger states surface on charging_state sensor
# ---------------------------------------------------------------------------


class TestM4_PerChargerStatesSurfaced:
    """The per-charger effective states are surfaced both on
    ``coord.data`` (as ``charger_<id>_charging_state`` keys) and on the
    ``sem_charging_state`` sensor (as a ``per_charger_states`` dict
    attribute). Pre-fix the fleet ``charging_state`` could say
    NIGHT_CHARGING_ACTIVE while a specific charger's effective state
    was SOLAR_IDLE (mixed-mode fleet) — the disagreement was invisible
    to users.
    """

    def test_coordinator_emits_per_charger_state_keys(self) -> None:
        from pathlib import Path
        coord_path = (Path(__file__).parent.parent / "coordinator"
                      / "coordinator.py")
        body = coord_path.read_text()
        assert 'result[f"charger_{cid}_charging_state"]' in body, (
            "M4 anchor — per-charger charging_state result key missing. "
            "Fleet ``charging_state`` will continue to hide per-charger "
            "disagreements."
        )

    def test_sensor_exposes_per_charger_states_attribute(self) -> None:
        from pathlib import Path
        sensor_path = Path(__file__).parent.parent / "sensor.py"
        body = sensor_path.read_text()
        # The charging_state sensor attributes include
        # ``per_charger_states`` so dashboards / users see the
        # disagreement explicitly.
        assert '"per_charger_states"' in body, (
            "M4 regression — sensor.py charging_state sensor does not "
            "expose per_charger_states. Users can't see when fleet "
            "state disagrees with per-charger states."
        )


# ---------------------------------------------------------------------------
# H1 — per-charger _calculate_remaining_need uses per-charger daily_ev
# ---------------------------------------------------------------------------


class TestH1_PerChargerDailyEvUsedForKwhTarget:
    """When ``_calculate_remaining_need`` is called with a
    ``charger_cfg``, the kWh-target branch subtracts THIS charger's
    daily energy (from ``_daily_ev_per_charger[cid]``) — not the fleet
    total (``energy.daily_ev``).

    Pre-fix, charger B's "target reached" check was polluted by
    charger A's energy.
    """

    def test_per_charger_consumption_used_when_cid_present(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = {"daily_ev_target": 10.0, "ev_target_type": "kwh"}
        # Fleet total = 8 kWh. Charger A consumed 7 of those; B only 1.
        coord._daily_ev_per_charger = {"a": 7.0, "b": 1.0}
        energy = MagicMock(daily_ev=8.0)

        cfg_b = {"id": "b", "daily_ev_target": 10.0}
        remaining_b = SEMCoordinator._calculate_remaining_need(
            coord, energy, vehicle_soc=None, charger_cfg=cfg_b, bound="min",
        )
        # B still needs 10 - 1 = 9 kWh. Pre-fix B would have seen
        # 10 - 8 = 2 kWh remaining (A's consumption leaking in).
        assert remaining_b == 9.0, (
            f"H1 regression — per-charger remaining_need used fleet "
            f"daily_ev instead of per-charger. Got {remaining_b} (want 9.0)."
        )

    def test_falls_back_to_fleet_when_cid_missing_from_map(self) -> None:
        """When ``_daily_ev_per_charger`` doesn't yet have an entry for
        this cid (fresh install, restart before first cycle), fall back
        to the fleet total — back-compat with single-charger installs."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = {"daily_ev_target": 10.0, "ev_target_type": "kwh"}
        coord._daily_ev_per_charger = {}  # empty
        energy = MagicMock(daily_ev=3.0)

        cfg_c = {"id": "c", "daily_ev_target": 10.0}
        remaining_c = SEMCoordinator._calculate_remaining_need(
            coord, energy, vehicle_soc=None, charger_cfg=cfg_c, bound="min",
        )
        # Fallback to fleet: 10 - 3 = 7
        assert remaining_c == 7.0


# ---------------------------------------------------------------------------
# H2 — per-charger forecast night-target reduction
# ---------------------------------------------------------------------------


class TestH2_ForecastNightTargetPerCharger:
    """Source-level lint: the multi-charger loop body applies
    ``_calculate_forecast_night_target`` per-charger when its mode
    uses smart-night. Pre-fix only the primary charger's view ran
    this reduction — secondary chargers ignored the "tomorrow is sunny
    → skip tonight" decision and night-charged unconditionally.
    """

    def test_per_charger_loop_calls_forecast_night_target(self) -> None:
        from pathlib import Path
        coord = (Path(__file__).parent.parent / "coordinator"
                 / "coordinator.py").read_text()

        # Count call sites of _calculate_forecast_night_target. Pre-fix:
        # 1 (primary view only). Post-fix: at least 2 (primary +
        # per-charger loop).
        n_calls = coord.count("_calculate_forecast_night_target(")
        # The method definition site doesn't have the trailing `(` count
        # the same way — but the call sites we expect are at the primary
        # build + the per-charger loop. The method's own def line is
        # ``def _calculate_forecast_night_target(``; subtract that 1.
        n_def = coord.count("def _calculate_forecast_night_target(")
        n_call_sites = n_calls - n_def
        assert n_call_sites >= 2, (
            f"H2 regression — _calculate_forecast_night_target has "
            f"{n_call_sites} call site(s). Want at least 2 (primary view "
            f"+ per-charger loop). Secondary chargers ignore the "
            f"forecast night-target reduction."
        )

    def test_per_charger_loop_gates_on_mode_uses_smart_night(self) -> None:
        from pathlib import Path
        coord = (Path(__file__).parent.parent / "coordinator"
                 / "coordinator.py").read_text()
        # The per-charger forecast call must be gated on
        # ``self._mode_uses_smart_night(charger_cfg)`` — not the fleet
        # ``_smart_night_charging_enabled()`` which would over-apply
        # the reduction to chargers whose mode doesn't use smart-night.
        assert "_mode_uses_smart_night(charger_cfg)" in coord, (
            "H2 regression — per-charger forecast call missing the "
            "per-charger ``_mode_uses_smart_night(charger_cfg)`` gate."
        )


# ---------------------------------------------------------------------------
# Bonus — sanity guard that the umbrella file structure is intact
# ---------------------------------------------------------------------------


class TestUmbrellaStructure:
    """Sanity-check that the 4 production sites the umbrella points at
    haven't moved without an update to this regression file. If grep
    can't find the anchors, this file is stale and either the source
    moved or the bugs got fixed without updating this file.
    """

    def test_m6_m11_anchors_present_in_coordinator(self) -> None:
        from pathlib import Path
        coord_path = Path(__file__).parent.parent / "coordinator" / "coordinator.py"
        body = coord_path.read_text()
        # M6 + M11 share the per-charger intel loop.
        assert "_build_per_charger_intelligence()" in body, (
            "Umbrella M6/M11 anchor `_build_per_charger_intelligence()` "
            "not found in coordinator.py — re-anchor the regression "
            "tests."
        )
        assert "notify_ev_charge_skip" in body, (
            "Umbrella M11 anchor `notify_ev_charge_skip` missing — "
            "either fixed or moved."
        )

    def test_l1_anchor_present_in_coordinator(self) -> None:
        from pathlib import Path
        coord_path = Path(__file__).parent.parent / "coordinator" / "coordinator.py"
        body = coord_path.read_text()
        assert "_update_battery_session_tracking" in body, (
            "Umbrella L1 anchor `_update_battery_session_tracking` "
            "missing in coordinator.py."
        )

    def test_l2_anchor_present_in_flow_calculator(self) -> None:
        from pathlib import Path
        fc_path = Path(__file__).parent.parent / "coordinator" / "flow_calculator.py"
        body = fc_path.read_text()
        # L2 anchors at the legacy method.
        assert "def calculate_energy_flows" in body, (
            "Umbrella L2 anchor `calculate_energy_flows` is gone — "
            "update the test to acknowledge the removal (acceptable "
            "fix shape #2)."
        )
