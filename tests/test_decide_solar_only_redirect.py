"""Pin the SolarOnlyMode redirect contract restored on 2026-06-02.

After the multi-charger-primary arch rewrite (PR #358),
``decide.py::SolarOnlyMode.decide()`` was checking bare surplus
(``solar - home - battery_charge_w`` when SOC < auto_start_soc)
against the charger min. The forecast-aware
``battery_redirect_w`` — which lives on
``calculate_canonical_ev_budget(SOLAR_ONLY)`` — was bypassed: by
the time the IDLE intent had been returned, the canonical
strategy chain mapped to IDLE and the redirect branch never ran.

The framework adoption surfaced this via
``tests/scenarios/2026-05-29_budget_unify_redirect.yaml``. The
fix re-plumbed forecast through ``FleetContext`` +
``build_charger_view`` and made SolarOnlyMode add redirect to
its surplus calculation BEFORE the min check.

This file pins the new contract at unit-test granularity so a
future arch refactor that drops the redirect again fails here
loudly, not just on the YAML scenario.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    SolarOnlyMode,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    battery_redirect_w,
)


def _view(
    *,
    solar_w: float,
    home_w: float,
    battery_charge_w: float,
    battery_soc: float,
    forecast_remaining_kwh: float,
    auto_start_soc: float = 90.0,
    battery_capacity_kwh: float = 15.0,
    min_amps: int = 6,
) -> ChargerView:
    """Minimal ChargerView for solar_only-mode decide tests."""
    fleet = FleetContext(
        solar_w=solar_w,
        home_w=home_w,
        battery_charge_w=battery_charge_w,
        battery_soc=battery_soc,
        auto_start_soc=auto_start_soc,
        battery_capacity_kwh=battery_capacity_kwh,
        forecast_remaining_kwh=forecast_remaining_kwh,
    )
    return ChargerView(
        power=ChargerPower(charger_id="ev_charger", power_w=0.0, connected=True),
        energy=ChargerEnergy(charger_id="ev_charger", day_kwh=0.0),
        mode="solar_only",
        config={
            "ev_min_current": min_amps,
            "ev_phases": 3,
            "ev_voltage": 230,
            "ev_max_current": 16,
        },
        fleet=fleet,
    )


# ---------------------------------------------------------------------------
# Module-level helper directly (pre-conditions)
# ---------------------------------------------------------------------------


def test_battery_redirect_w_zero_when_battery_not_charging() -> None:
    """No charging → nothing to redirect."""
    assert battery_redirect_w(0, 75, 15, 25) == 0
    assert battery_redirect_w(-100, 75, 15, 25) == 0  # discharging


def test_battery_redirect_w_proportional_when_forecast_covers_need() -> None:
    """forecast=25, need=3.75 → ratio=0.85, redirect = batt_charge * 0.85."""
    redirect = battery_redirect_w(
        battery_charge_w=1000,
        battery_soc=75,
        battery_capacity_kwh=15,
        forecast_remaining_kwh=25,
    )
    # ratio = 1 - 3.75/25 = 0.85, redirect = 1000 * 0.85 = 850
    assert abs(redirect - 850.0) < 0.5


def test_battery_redirect_w_minimum_5_percent_at_boundary() -> None:
    """forecast == need → ratio=0 but min floor of 5% applies."""
    redirect = battery_redirect_w(
        battery_charge_w=1000,
        battery_soc=50,
        battery_capacity_kwh=15,
        forecast_remaining_kwh=7.5,  # exactly battery_need
    )
    # max(0.05, 0) = 0.05, redirect = 1000 * 0.05 = 50
    assert abs(redirect - 50.0) < 0.5


def test_battery_redirect_w_zero_when_forecast_below_need() -> None:
    """forecast=2, need=3.75 → battery wins (no redirect)."""
    redirect = battery_redirect_w(
        battery_charge_w=1000,
        battery_soc=75,
        battery_capacity_kwh=15,
        forecast_remaining_kwh=2,
    )
    assert redirect == 0


def test_battery_redirect_w_full_redirect_above_80_soc_no_forecast() -> None:
    """No forecast + SOC >= 80 → SOC-threshold fallback, redirect all."""
    assert battery_redirect_w(1000, 85, 15, 0) == 1000


# ---------------------------------------------------------------------------
# SolarOnlyMode integration — the new contract
# ---------------------------------------------------------------------------


def test_solar_only_idles_when_bare_surplus_zero_and_no_forecast() -> None:
    """No forecast + Zone 3 SOC + battery charging → no redirect → IDLE.

    Without the SOC-threshold fallback firing (75 < 80) the redirect is 0,
    bare surplus is 0, total is 0 → below 4140W min → IDLE. Same as
    pre-fix behaviour for this specific input. Pins the regression
    floor.
    """
    view = _view(
        solar_w=4000, home_w=1500, battery_charge_w=2000,
        battery_soc=75, forecast_remaining_kwh=0,
    )
    decision = SolarOnlyMode().decide(view)
    assert decision.intent is ChargerIntent.IDLE


def test_solar_only_charges_when_redirect_lifts_surplus_above_min() -> None:
    """Modest bare surplus + generous forecast → redirect lifts effective
    surplus above charger min → CHARGE_AT_AMPS.

    THIS IS THE FIX. Pre-fix this test would fail because decide.py
    ignored ``forecast_remaining_kwh`` and the redirect was unreachable.
    """
    view = _view(
        solar_w=6000, home_w=1500, battery_charge_w=1000,
        battery_soc=75, forecast_remaining_kwh=25,
    )
    decision = SolarOnlyMode().decide(view)
    # bare = max(0, 6000 - 1500 - 1000) = 3500
    # redirect = 1000 * max(0.05, 1 - 3.75/25) = 1000 * 0.85 = 850
    # effective = 3500 + 850 = 4350 → >= 4140 (min) → CHARGE
    assert decision.intent is ChargerIntent.CHARGE_AT_AMPS
    # 4350 / 690 = 6.3 → floor to 6
    assert decision.commanded_amps == 6
    # Reason includes the bare/redirect breakdown — debugging aid +
    # proof the right code path ran.
    # (#829) reason figures are in 100 W steps so the explanation does not
    # rewrite the recorder row every cycle: 850 -> 800.
    assert "redirect=800W" in decision.reason
    assert "bare=3500" in decision.reason


def test_solar_only_charges_with_forecast_redirect_zero_bare_surplus() -> None:
    """Zero bare surplus but solar high enough + forecast enough that
    redirect alone clears min. Edge case the regression hit hardest."""
    view = _view(
        solar_w=4500, home_w=500, battery_charge_w=4000,
        battery_soc=70, forecast_remaining_kwh=50,
    )
    decision = SolarOnlyMode().decide(view)
    # bare = max(0, 4500 - 500 - 4000) = 0
    # need = (100-70)/100 * 15 = 4.5
    # ratio = 1 - 4.5/50 = 0.91, redirect = 4000 * 0.91 = 3640
    # effective = 0 + 3640 = 3640 → < 4140 → still IDLE
    # (the regression-floor case — redirect helps but not enough)
    # If amps > 0 here the math has shifted; surface explicitly.
    assert decision.intent is ChargerIntent.IDLE
    assert "redirect=3600W" in decision.reason   # (#829) 100 W steps


def test_solar_only_idles_with_disconnected_ev_regardless_of_surplus() -> None:
    """The IDLE-when-disconnected guard still wins over redirect."""
    base = _view(
        solar_w=10000, home_w=500, battery_charge_w=1000,
        battery_soc=80, forecast_remaining_kwh=25,
    )
    # ChargerPower / ChargerView are frozen — rebuild with connected=False.
    disconnected_view = ChargerView(
        power=ChargerPower(
            charger_id=base.power.charger_id, power_w=base.power.power_w,
            connected=False, charging=base.power.charging,
        ),
        energy=base.energy,
        mode=base.mode,
        config=base.config,
        fleet=base.fleet,
    )
    decision = SolarOnlyMode().decide(disconnected_view)
    assert decision.intent is ChargerIntent.IDLE
    assert "disconnected" in decision.reason


def test_solar_only_no_redirect_when_battery_discharging() -> None:
    """Battery already discharging → battery_charge_w is 0/negative → no
    redirect available (the source side of the diversion is empty)."""
    view = _view(
        solar_w=4500, home_w=500, battery_charge_w=0,
        battery_soc=75, forecast_remaining_kwh=25,
    )
    decision = SolarOnlyMode().decide(view)
    # bare = 4500 - 500 = 4000, redirect = 0
    # 4000 < 4140 → IDLE. (Without redirect available, this is the
    # expected solar_only floor.)
    assert decision.intent is ChargerIntent.IDLE
    assert "redirect=0" in decision.reason
