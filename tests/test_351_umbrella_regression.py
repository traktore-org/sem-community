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

    @pytest.mark.xfail(
        strict=True,
        reason="#351 M6 — fleet ev_charging used as per-charger gate; "
        "fix should read this charger's draw from per_charger snapshot.",
    )
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

    @pytest.mark.xfail(
        strict=True,
        reason="#351 M11 — night-skip notification fires even when "
        "charger's mode disallows night charging.",
    )
    @pytest.mark.asyncio
    async def test_skip_not_sent_for_solar_only_mode(self) -> None:
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
        coord.config = {
            "ev_chargers": [
                {"id": "x", "ev_charging_mode": "solar_only"},
            ],
        }
        coord._effective_states_per_charger = {}

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

    @pytest.mark.xfail(
        strict=True,
        reason="#351 L1 — _update_battery_session_tracking reads "
        "config[update_interval] instead of self.update_interval.",
    )
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

        kwh = coord._battery_session.total_kwh
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

    @pytest.mark.xfail(
        strict=True,
        reason="#351 L2 — calculate_energy_flows lacks deprecation "
        "marker; risk of test pinning wrong attribution model.",
    )
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
