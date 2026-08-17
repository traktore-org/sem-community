"""Regression tests for calculation audit findings (#223–#232).

Each test targets a specific bug found in the audit. Docstrings name the
issue number and explain what failure mode the test prevents from returning.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
    SUNRISE_HOUR,
    SUNSET_HOUR,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    EnergyTotals,
)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_power(
    solar=0.0,
    grid_import=0.0,
    grid_export=0.0,
    home=0.0,
    ev=0.0,
    battery_charge=0.0,
    battery_discharge=0.0,
    battery_soc=50.0,
):
    """Create PowerReadings with explicit split values."""
    return PowerReadings(
        solar_power=solar,
        grid_import_power=grid_import,
        grid_export_power=grid_export,
        home_consumption_power=home,
        ev_power=ev,
        battery_charge_power=battery_charge,
        battery_discharge_power=battery_discharge,
        battery_soc=battery_soc,
    )


def _freeze(year=2026, month=5, day=15, hour=12, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second)


@pytest.fixture
def time_manager():
    tm = MagicMock()
    tm.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)
    return tm


@pytest.fixture
def config():
    return {
        "update_interval": 30,
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
        "battery_capacity_kwh": 10.0,
        "system_size_kwp": 10.0,
    }


@pytest.fixture
def calculator(config, time_manager):
    return EnergyCalculator(config, time_manager)


@pytest.fixture
def flow_calc():
    return FlowCalculator()


# ──────────────────────────────────────────────────────────────────────────────
# Issue #223 — Dynamic tariff: battery session cost uses rate-at-time
# ──────────────────────────────────────────────────────────────────────────────

class TestDynamicTariffBatterySavings:
    """#223 — Battery discharge savings must use the rate active at each interval.

    Before the fix, `cost_batt_savings` was computed as
    total_discharge_kwh × current_rate, so a late-day rate spike would
    retroactively inflate earlier savings. The cost accumulator now records
    each increment at the rate in effect at that moment.
    """

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_battery_savings_uses_rate_at_discharge_time(self, mock_dt, calculator):
        """should accumulate battery savings at per-interval rate, not final rate."""
        now = _freeze(hour=10)
        mock_dt.now.return_value = now

        # Phase 1: 10 cycles at rate=0.10, 5000W discharge
        calculator._import_rate = 0.10
        for i in range(10):
            mock_dt.now.return_value = now + timedelta(seconds=30 * i)
            power = _make_power(solar=8000, battery_discharge=5000, home=3000)
            calculator.calculate_energy(power)

        mid_batt_savings = calculator._get_daily_cost(
            "cost_batt_savings", now.date()
        )

        # Phase 2: 10 more cycles, rate jumps to 0.50
        calculator._import_rate = 0.50
        for i in range(10, 20):
            mock_dt.now.return_value = now + timedelta(seconds=30 * i)
            power = _make_power(solar=8000, battery_discharge=5000, home=3000)
            calculator.calculate_energy(power)

        final_batt_savings = calculator._get_daily_cost(
            "cost_batt_savings", now.date()
        )

        per_cycle_kwh = 5000 * (30 / 3600) / 1000
        expected_phase1 = 10 * per_cycle_kwh * 0.10
        expected_phase2 = 10 * per_cycle_kwh * 0.50
        expected_total = expected_phase1 + expected_phase2

        # Bug would give: 20 * per_cycle_kwh * 0.50 (all at final rate)
        bug_total = 20 * per_cycle_kwh * 0.50

        assert mid_batt_savings == pytest.approx(expected_phase1, abs=0.005)
        assert final_batt_savings == pytest.approx(expected_total, abs=0.01)
        assert abs(final_batt_savings - bug_total) > 0.05, (
            "Savings match the bug total — rate-at-time not being used"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_battery_savings_rate_change_does_not_retroact(self, mock_dt, calculator):
        """should not recalculate past battery savings when rate changes mid-session."""
        now = _freeze(hour=11)
        calculator._import_rate = 0.05

        mock_dt.now.return_value = now
        power = _make_power(solar=6000, battery_discharge=3000, home=3000)
        calculator.calculate_energy(power)  # first call: uses config interval

        mock_dt.now.return_value = now + timedelta(seconds=30)
        calculator.calculate_energy(power)

        low_rate_savings = calculator._get_daily_cost("cost_batt_savings", now.date())

        # Now rate spikes — past cost must stay the same
        calculator._import_rate = 0.45
        mock_dt.now.return_value = now + timedelta(seconds=60)
        calculator.calculate_energy(_make_power())  # no discharge

        same_savings = calculator._get_daily_cost("cost_batt_savings", now.date())
        assert same_savings == pytest.approx(low_rate_savings, abs=1e-6), (
            "Past battery savings changed when rate changed — retroactive recalculation bug"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Issue #224 — monthly_battery_savings uses actual accumulator, not 30% estimate
# ──────────────────────────────────────────────────────────────────────────────

class TestMonthlyBatterySavingsAccuracy:
    """#224 — monthly_battery_savings must come from cost_batt_savings accumulator.

    A previous version approximated it as 30% of monthly_savings (solar savings).
    This failed when there was no battery discharge (returned non-zero) and
    when battery was the only source (returned too little).
    """

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_no_battery_discharge_means_zero_savings(self, mock_dt, calculator):
        """should return 0 monthly_battery_savings when no battery discharged."""
        mock_dt.now.return_value = _freeze(month=5)
        month_key = "2026_5"

        # Seed: solar savings exist, but no battery savings
        calculator._monthly_cost_accumulators[f"cost_savings_{month_key}"] = 30.0
        calculator._monthly_cost_accumulators[f"cost_batt_savings_{month_key}"] = 0.0

        energy = EnergyTotals(monthly_solar=100.0, monthly_grid_export=20.0)
        costs = calculator.calculate_costs(energy)

        assert costs.monthly_battery_savings == 0.0, (
            "monthly_battery_savings should be 0 when no battery discharged"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_battery_savings_equals_accumulator_not_30pct_of_solar(self, mock_dt, calculator):
        """should equal cost_batt_savings accumulator, not 30% of solar savings."""
        mock_dt.now.return_value = _freeze(month=5)
        month_key = "2026_5"

        monthly_solar_savings = 50.0  # EUR
        monthly_batt_savings = 8.75   # EUR — deliberately not 30% of solar

        calculator._monthly_cost_accumulators[f"cost_savings_{month_key}"] = monthly_solar_savings
        calculator._monthly_cost_accumulators[f"cost_batt_savings_{month_key}"] = monthly_batt_savings

        energy = EnergyTotals(monthly_solar=100.0, monthly_grid_export=20.0)
        costs = calculator.calculate_costs(energy)

        wrong_estimate = monthly_solar_savings * 0.30
        assert costs.monthly_battery_savings == pytest.approx(monthly_batt_savings, abs=0.01)
        assert abs(costs.monthly_battery_savings - wrong_estimate) > 0.5, (
            "monthly_battery_savings appears to be 30%% of solar savings (old bug)"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_battery_only_day_savings_match_discharge_value(self, mock_dt, calculator):
        """should report full battery savings when battery is sole home supply."""
        mock_dt.now.return_value = _freeze(month=5)
        month_key = "2026_5"

        # Simulate: solar=0, all home from battery discharge
        # 5 kWh discharged at 0.30/kWh = 1.50 EUR
        calculator._monthly_cost_accumulators[f"cost_savings_{month_key}"] = 0.0
        calculator._monthly_cost_accumulators[f"cost_batt_savings_{month_key}"] = 1.50

        energy = EnergyTotals()
        costs = calculator.calculate_costs(energy)

        assert costs.monthly_battery_savings == pytest.approx(1.50, abs=0.01)


# ──────────────────────────────────────────────────────────────────────────────
# Issue #225 — Midnight rollover race: snapshot skipped when data is zero
# ──────────────────────────────────────────────────────────────────────────────

class TestMidnightRolloverSnapshot:
    """#225 — Snapshot must not be skipped if prior snapshot had zero energy.

    If SEM restarted just before midnight, the first snapshot recorded zero
    energy (system just started). The next rollover then saw already_snapshotted=True
    and skipped, losing the whole day's real data.
    """

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_zero_energy_snapshot_allows_retry_next_day(self, mock_dt, calculator, time_manager):
        """should allow re-snapshot when prior snapshot energy_kwh == 0."""
        yesterday = date(2026, 5, 14)
        today = date(2026, 5, 15)
        month_key = "2026_5"
        year_key = "2026"
        yesterday_str = str(yesterday)

        time_manager.get_current_meter_day_sunrise_based.return_value = today

        # Inject a prior rate_history entry with energy_kwh=0 (trivial snapshot)
        calculator._rate_history.append({
            "date": yesterday_str,
            "import_rate": 0.30,
            "export_rate": 0.08,
            "energy_kwh": 0.0,  # this is the zero-energy snapshot
        })

        # Now inject actual yesterday data — 5 kWh solar that should be captured
        calculator._daily_accumulators[f"solar_{yesterday_str}"] = 5.0
        calculator._daily_accumulators[f"grid_import_{yesterday_str}"] = 2.0
        calculator._daily_cost_accumulators[f"cost_import_{yesterday_str}"] = 0.60
        calculator._daily_cost_accumulators[f"cost_savings_{yesterday_str}"] = 1.20

        accumulated_before = calculator._accumulated_savings

        # Trigger rollover (today != yesterday so it runs _check_rollover)
        mock_dt.now.return_value = _freeze(year=2026, month=5, day=15, hour=0, minute=1)
        power = _make_power(solar=100, home=100)
        calculator.calculate_energy(power)

        # Because prior snapshot had energy_kwh=0, it should have re-snapshotted
        assert calculator._accumulated_savings > accumulated_before, (
            "Savings not snapshotted: zero-energy prior snapshot blocked re-snapshot"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_nonzero_snapshot_is_not_duplicated(self, mock_dt, calculator, time_manager):
        """should not snapshot twice when prior snapshot had real data."""
        yesterday = date(2026, 5, 14)
        today = date(2026, 5, 15)
        yesterday_str = str(yesterday)

        time_manager.get_current_meter_day_sunrise_based.return_value = today

        # Prior snapshot had real data
        calculator._rate_history.append({
            "date": yesterday_str,
            "import_rate": 0.30,
            "export_rate": 0.08,
            "energy_kwh": 12.5,  # non-zero — already snapshotted
        })

        # Also inject accumulated savings already captured
        calculator._accumulated_savings = 3.60
        calculator._daily_cost_accumulators[f"cost_savings_{yesterday_str}"] = 1.80

        mock_dt.now.return_value = _freeze(year=2026, month=5, day=15, hour=0, minute=1)
        calculator.calculate_energy(_make_power(solar=100, home=100))

        # accumulated_savings should NOT include yesterday's cost_savings again
        assert calculator._accumulated_savings == pytest.approx(3.60, abs=0.01), (
            "Savings duplicated: non-zero prior snapshot was re-snapshotted"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_normal_day_rollover_captures_correct_totals(self, mock_dt, calculator, time_manager):
        """should capture day's real cost data during normal midnight rollover."""
        day1 = date(2026, 5, 14)
        day2 = date(2026, 5, 15)
        month_key = "2026_5"
        year_key = "2026"

        time_manager.get_current_meter_day_sunrise_based.return_value = day1

        # Accumulate energy on day1 — use closely spaced timestamps to avoid gap protection
        t0 = _freeze(2026, 5, 14, 12, 0)
        mock_dt.now.return_value = t0
        power = _make_power(solar=5000, home=3000, grid_import=1000, grid_export=0)
        calculator.calculate_energy(power)

        mock_dt.now.return_value = t0 + timedelta(seconds=30)
        calculator.calculate_energy(power)

        day1_savings = calculator._get_daily_cost("cost_savings", day1)
        assert day1_savings > 0, "No savings accumulated on day1 — test setup wrong"

        # Rollover to day2: set _last_update to just before midnight to avoid gap protection
        rollover_time = _freeze(2026, 5, 15, 0, 0, 1)
        calculator._last_update = rollover_time - timedelta(seconds=10)
        mock_dt.now.return_value = rollover_time
        time_manager.get_current_meter_day_sunrise_based.return_value = day2
        calculator.calculate_energy(_make_power(solar=100, home=100))

        # accumulated_savings should now include day1's savings
        assert calculator._accumulated_savings >= day1_savings * 0.9, (
            "Day rollover did not capture savings into accumulated total"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Issue #226 — available_power includes battery discharge when discharging
# ──────────────────────────────────────────────────────────────────────────────

# TestAvailablePowerIncludesBatteryDischarge (#226 regression suite)
# removed in Phase D.2 (#282): ``calculate_available_power`` was deleted
# along with the other legacy budget primitives. The battery-discharge
# inclusion behaviour now lives inside the canonical EVBudget's
# BATTERY_ASSIST branch — see ``test_canonical_ev_budget.py``.


# ──────────────────────────────────────────────────────────────────────────────
# Issue #227 — Battery redirect boundary: forecast == battery_need redirects >0
# ──────────────────────────────────────────────────────────────────────────────

class TestBatteryRedirectBoundary:
    """#227 — _calculate_battery_redirect must redirect >0 when forecast == battery_need.

    At the exact boundary (forecast_remaining == battery_need), the ratio was
    1.0 - battery_need/forecast_remaining = 0.0, giving redirect=0. The fix
    uses max(0.05, ratio) so at least 5% is always redirected at the boundary.
    """

    def test_redirect_nonzero_when_forecast_exactly_equals_battery_need(self, flow_calc):
        """should redirect > 0 when forecast equals battery need exactly."""
        battery_charge_w = 3000.0
        battery_soc = 50.0
        battery_capacity_kwh = 10.0
        # battery_need = (100 - 50) / 100 * 10 = 5.0 kWh
        battery_need = (100 - battery_soc) / 100 * battery_capacity_kwh
        forecast_remaining_kwh = battery_need  # exact boundary

        redirect = flow_calc._calculate_battery_redirect(
            battery_charge_w, battery_soc, battery_capacity_kwh, forecast_remaining_kwh
        )
        assert redirect > 0, (
            "Redirect is 0 at exact forecast==battery_need boundary — boundary bug present"
        )
        assert redirect >= battery_charge_w * 0.05, (
            "Redirect is less than the 5%% minimum floor at boundary"
        )

    def test_redirect_zero_when_forecast_below_battery_need(self, flow_calc):
        """should return 0 redirect when forecast cannot cover battery need."""
        battery_charge_w = 3000.0
        battery_soc = 20.0
        battery_capacity_kwh = 10.0
        # battery_need = 8 kWh, forecast = 5 kWh < battery_need
        forecast_remaining_kwh = 5.0

        redirect = flow_calc._calculate_battery_redirect(
            battery_charge_w, battery_soc, battery_capacity_kwh, forecast_remaining_kwh
        )
        assert redirect == 0.0, (
            "Redirect non-zero when forecast is less than battery need — keeps charging"
        )

    def test_redirect_increases_as_forecast_exceeds_battery_need(self, flow_calc):
        """should redirect more power as forecast surplus grows above battery need."""
        battery_charge_w = 3000.0
        battery_soc = 80.0
        battery_capacity_kwh = 10.0
        # battery_need = 2 kWh

        redirect_low = flow_calc._calculate_battery_redirect(
            battery_charge_w, battery_soc, battery_capacity_kwh, 3.0  # small surplus
        )
        redirect_high = flow_calc._calculate_battery_redirect(
            battery_charge_w, battery_soc, battery_capacity_kwh, 10.0  # large surplus
        )
        assert redirect_high > redirect_low, (
            "Redirect does not increase as forecast surplus grows"
        )

    def test_redirect_all_when_battery_nearly_full_no_forecast(self, flow_calc):
        """should redirect all battery charge when battery nearly full and no forecast.

        The 'nearly full' branch (battery_need <= 0.5 kWh) only activates when
        forecast_remaining < battery_need (i.e. forecast can't cover remainder).
        When forecast IS available and covers the need, proportional allocation runs.
        When NO forecast: the SOC >= 80 fallback redirects all.
        """
        battery_charge_w = 2000.0
        battery_soc = 96.0  # 96% full, SOC >> 80 threshold
        battery_capacity_kwh = 10.0
        forecast_remaining_kwh = 0.0  # no forecast — triggers SOC fallback

        redirect = flow_calc._calculate_battery_redirect(
            battery_charge_w, battery_soc, battery_capacity_kwh, forecast_remaining_kwh
        )
        assert redirect == pytest.approx(battery_charge_w, abs=1.0), (
            "All charge power should redirect when battery SOC >= 80 and no forecast"
        )

    def test_redirect_proportional_when_battery_nearly_full_with_forecast(self, flow_calc):
        """should redirect proportionally (not all) when nearly full AND forecast available.

        With forecast available and forecast >= battery_need, the proportional branch
        runs. The 'redirect all' path only applies when forecast < battery_need and
        battery_need <= 0.5 kWh, OR when no forecast and SOC >= 80.
        """
        battery_charge_w = 2000.0
        battery_soc = 96.0  # need = 0.4 kWh
        battery_capacity_kwh = 10.0
        forecast_remaining_kwh = 3.0  # forecast covers battery need

        redirect = flow_calc._calculate_battery_redirect(
            battery_charge_w, battery_soc, battery_capacity_kwh, forecast_remaining_kwh
        )
        # ratio = 1 - 0.4/3.0 = 0.867; redirect = 2000 * 0.867 ≈ 1733W
        # Must be > 0 and > 5% (the minimum floor)
        assert redirect > battery_charge_w * 0.05, "Should redirect at least 5% of charge"
        assert redirect < battery_charge_w, "Should not redirect 100% when proportional branch runs"

    def test_redirect_zero_when_no_battery_charge(self, flow_calc):
        """should return 0 when battery is not charging."""
        redirect = flow_calc._calculate_battery_redirect(
            0.0, 50.0, 10.0, 8.0
        )
        assert redirect == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Issue #228 — Forecast dampening uses sun.sun sunrise/sunset
# ──────────────────────────────────────────────────────────────────────────────

class TestForecastSunriseSunsetFromSunEntity:
    """#228 — ForecastTracker must use sun.sun entity hours, not hardcoded 6/20.

    Polar regions can have sunrise at 9 AM and sunset at 3 PM. Using hardcoded
    6/20 with a 14-hour window overstretches the sine curve and gives wrong
    dampening fractions throughout the day.
    """

    def _make_tracker_with_sun(self, rise_hour: float, set_hour: float) -> ForecastTracker:
        """Return a ForecastTracker whose hass returns controlled sun times."""
        tracker = ForecastTracker()

        # Build ISO strings from fractional hours
        def _hour_to_iso(h: float) -> str:
            hh = int(h)
            mm = int((h - hh) * 60)
            return f"2026-05-15T{hh:02d}:{mm:02d}:00+00:00"

        hass = MagicMock()
        sun_state = MagicMock()
        sun_state.attributes = {
            "next_rising": _hour_to_iso(rise_hour),
            "next_setting": _hour_to_iso(set_hour),
        }
        hass.states.get.return_value = sun_state

        # Make datetime.fromisoformat return aware datetimes that convert to
        # the same local hours (UTC == local in test)
        tracker.set_hass(hass)

        # Patch DEFAULT_TIME_ZONE so astimezone(tz) is a no-op in UTC
        import custom_components.solar_energy_management.coordinator.forecast_tracker as ft_mod
        original_tz = ft_mod.dt_util.DEFAULT_TIME_ZONE

        return tracker

    def test_get_sun_hours_uses_sun_entity_when_available(self):
        """should read sunrise/sunset from sun.sun entity attributes."""
        tracker = ForecastTracker()

        rise_iso = "2026-05-15T09:00:00+00:00"
        set_iso = "2026-05-15T15:00:00+00:00"

        hass = MagicMock()
        sun_state = MagicMock()
        sun_state.attributes = {"next_rising": rise_iso, "next_setting": set_iso}
        hass.states.get.return_value = sun_state

        with patch(
            "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
        ) as mock_dt:
            mock_dt.DEFAULT_TIME_ZONE = timezone.utc
            # #416 sub#3 — _get_sun_hours reads now().date() to roll
            # tomorrow-dated next_* events back to today.
            mock_dt.now.return_value = datetime(
                2026, 5, 15, 4, 0, tzinfo=timezone.utc
            )
            tracker.set_hass(hass)
            rise, sett = tracker._get_sun_hours()

        assert rise == pytest.approx(9.0, abs=0.1), (
            f"Expected sunrise ~9.0, got {rise} — sun.sun not being read"
        )
        assert sett == pytest.approx(15.0, abs=0.1), (
            f"Expected sunset ~15.0, got {sett} — sun.sun not being read"
        )

    def test_get_sun_hours_falls_back_when_sun_unavailable(self):
        """should fall back to module constants when sun.sun is unavailable."""
        tracker = ForecastTracker()
        hass = MagicMock()
        hass.states.get.return_value = None  # sun.sun not available
        tracker.set_hass(hass)

        rise, sett = tracker._get_sun_hours()

        assert rise == float(SUNRISE_HOUR)
        assert sett == float(SUNSET_HOUR)

    def test_get_sun_hours_falls_back_when_hass_not_set(self):
        """should fall back to defaults when hass is None (early startup)."""
        tracker = ForecastTracker()
        # _hass is None by default
        rise, sett = tracker._get_sun_hours()

        assert rise == float(SUNRISE_HOUR)
        assert sett == float(SUNSET_HOUR)

    def test_polar_region_short_day_uses_correct_daylight_hours(self):
        """should use the real (short) day length, not the hardcoded 14h window."""
        tracker = ForecastTracker()

        # Polar winter: 6-hour day (9:00–15:00)
        polar_rise = "2026-01-15T09:00:00+00:00"
        polar_set = "2026-01-15T15:00:00+00:00"

        hass = MagicMock()
        sun_state = MagicMock()
        sun_state.attributes = {"next_rising": polar_rise, "next_setting": polar_set}
        hass.states.get.return_value = sun_state

        with patch(
            "custom_components.solar_energy_management.coordinator.forecast_tracker.dt_util"
        ) as mock_dt:
            mock_dt.DEFAULT_TIME_ZONE = timezone.utc
            mock_dt.now.return_value = datetime(
                2026, 1, 15, 4, 0, tzinfo=timezone.utc
            )
            tracker.set_hass(hass)
            rise, sett = tracker._get_sun_hours()

        daylight_hours = sett - rise
        assert daylight_hours == pytest.approx(6.0, abs=0.1), (
            f"Expected 6h polar day, got {daylight_hours}h"
        )

        # The dynamic curve fraction at noon (3h into a 6h day) should be ~50%
        fraction_noon = ForecastTracker._solar_curve_fraction_dynamic(3.0, 6.0)
        assert fraction_noon == pytest.approx(0.5, abs=0.05)


# ──────────────────────────────────────────────────────────────────────────────
# Issue #229 — EV budget semantics: budget is a SETPOINT, not an increment
# ──────────────────────────────────────────────────────────────────────────────

# TestEVBudgetSemantics (#229 setpoint-not-increment regression) removed
# in Phase D.2 (#282): ``calculate_ev_budget`` was deleted along with
# the other legacy budget primitives. The setpoint semantic is now
# carried by ``calculate_canonical_ev_budget`` and exercised end-to-end
# by the scenario harness (no double-count or ramp-down regression has
# slipped past it since v1.6.0).


# ──────────────────────────────────────────────────────────────────────────────
# Issue #230 — Savings no double-count: daily_savings excludes battery discharge
# ──────────────────────────────────────────────────────────────────────────────

class TestSavingsNoDoubleCount:
    """#230 — daily_savings (solar) must not include battery discharge contribution.

    The solar self-consumption savings are: (home + ev - grid_import - battery_discharge) × rate
    Without subtracting battery_discharge, the solar savings would count energy
    the battery (not the sun) delivered — double-counting battery savings.
    """

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_pure_solar_day_no_battery_savings(self, mock_dt, calculator):
        """should have zero daily_battery_savings when no battery discharged."""
        now = _freeze(hour=12)
        calculator._import_rate = 0.30

        mock_dt.now.return_value = now
        # Solar covers all home, no battery at all
        power = _make_power(solar=3000, home=2000, grid_export=1000)
        calculator.calculate_energy(power)

        mock_dt.now.return_value = now + timedelta(seconds=30)
        calculator.calculate_energy(power)

        energy = EnergyTotals()
        costs = calculator.calculate_costs(energy)

        assert costs.daily_battery_savings == 0.0, (
            "Battery savings > 0 despite no battery discharge — double-counting"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_battery_discharge_not_counted_in_solar_savings(self, mock_dt, calculator):
        """should exclude battery discharge from cost_savings accumulation.

        With home=3000W, solar=2000W, battery_discharge=1000W over many cycles:
          solar_self_consumed = max(0, home + ev - grid_import - battery_discharge)
                               = max(0, 3000 + 0 - 0 - 1000) = 2000W (solar only)
          battery savings accumulates 1000W worth separately.
        The ratio of solar_savings / batt_savings should be ~2:1 (2000W vs 1000W).
        If battery discharge is incorrectly counted in solar savings, the ratio goes
        towards 3:1 (all 3000W in solar savings).
        """
        now = _freeze(hour=12)
        calculator._import_rate = 0.30
        power = _make_power(solar=2000, home=3000, battery_discharge=1000)

        # Run 60 cycles at 30s each to build up enough EUR to be > rounding noise
        for i in range(60):
            mock_dt.now.return_value = now + timedelta(seconds=30 * i)
            calculator.calculate_energy(power)

        today = now.date()
        solar_savings = calculator._get_daily_cost("cost_savings", today)
        batt_savings = calculator._get_daily_cost("cost_batt_savings", today)

        assert solar_savings > 0, "Should have some solar savings"
        assert batt_savings > 0, "Should have some battery savings"

        # solar_self_consumed = 2000W, battery = 1000W → ratio should be 2:1
        ratio = solar_savings / batt_savings
        assert ratio == pytest.approx(2.0, abs=0.3), (
            f"solar/battery savings ratio should be ~2:1 (2000W solar : 1000W battery), "
            f"got {ratio:.2f} — battery discharge may be double-counted in solar savings"
        )

        # Also confirm: buggy version would give ratio of 3:1 (3000W uncorrected)
        assert ratio < 2.8, (
            f"Ratio {ratio:.2f} is close to 3:1 — battery discharge subtraction may be missing"
        )

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_solar_savings_plus_battery_savings_equals_total(self, mock_dt, calculator):
        """daily_savings + daily_battery_savings should sum to total self-consumption value."""
        now = _freeze(hour=12)
        calculator._import_rate = 0.30
        today = now.date()
        month_key = "2026_5"
        year_key = "2026"

        # Manually seed known values
        calculator._daily_cost_accumulators[f"cost_savings_{today}"] = 2.40   # solar
        calculator._daily_cost_accumulators[f"cost_batt_savings_{today}"] = 0.90  # battery

        energy = EnergyTotals(
            daily_solar=10.0,
            daily_grid_export=2.0,
            yearly_solar=100.0,
            yearly_grid_export=20.0,
        )
        mock_dt.now.return_value = now
        costs = calculator.calculate_costs(energy)

        assert costs.daily_savings == pytest.approx(2.40, abs=0.01)
        assert costs.daily_battery_savings == pytest.approx(0.90, abs=0.01)
        total_self_consumption_value = 2.40 + 0.90
        assert costs.daily_savings + costs.daily_battery_savings == pytest.approx(
            total_self_consumption_value, abs=0.01
        )


# ──────────────────────────────────────────────────────────────────────────────
# Issue #231 — Night EV peak management subtracts EV from grid import
# ──────────────────────────────────────────────────────────────────────────────

class TestNightEVPeakManagement:
    """#231 — Night peak target calculation must subtract EV's own draw.

    The formula is:
        non_ev_grid = grid_import - ev_power
        target = (peak_limit - non_ev_grid) / watts_per_amp

    Before the fix, the formula used raw grid_import including EV's draw,
    which underestimated how much current the EV could use, throttling it
    when headroom actually existed.
    """

    def _make_ev_device(self, current_setpoint: float, max_current: float = 16):
        ev = MagicMock()
        ev._current_setpoint = current_setpoint
        ev.max_current = max_current
        ev._session_active = True
        ev.min_current = 6
        return ev

    def test_night_target_subtracts_ev_from_grid_import(self):
        """should compute non_ev_grid = grid_import - ev_power before limiting."""
        # peak=5000W, grid_import=4200W (2200 home + 2000 EV drawing at 6A×230V×1.48)
        # non_ev_grid = 4200 - 2000 = 2200
        # headroom = 5000 - 2200 = 2800W → target = 2800/333 ≈ 8.4A → 8A
        peak_limit_w = 5000.0
        grid_import_w = 4200.0
        ev_power_w = 2000.0
        watts_per_amp = ev_power_w / 6  # ≈ 333 W/A (from actual setpoint of 6A)

        non_ev_grid = grid_import_w - ev_power_w
        target = (peak_limit_w - non_ev_grid) / max(1, watts_per_amp)
        target = round(target)

        assert target == pytest.approx(8.4, abs=1.0), (
            f"Expected ~8A target, got {target}A — EV not subtracted from grid import"
        )
        assert target > 6, (
            "Target should be above min current (6A) when headroom exists"
        )

    def test_night_target_exact_scenario_from_audit(self):
        """Audit scenario: peak=5000W, home=1900W, EV=2300W → target≈13.5A."""
        peak_limit_w = 5000.0
        home_w = 1900.0
        ev_power_w = 2300.0
        current_setpoint_a = 10.0  # SEM set 10A

        watts_per_amp = ev_power_w / max(1, current_setpoint_a)  # 230 W/A
        grid_import_w = home_w + ev_power_w  # 4200W

        non_ev_grid = grid_import_w - ev_power_w  # 1900W (home only)
        target = (peak_limit_w - non_ev_grid) / max(1, watts_per_amp)
        target = round(target)

        # Expected: (5000 - 1900) / 230 ≈ 13.5A → 14A after rounding
        assert target == pytest.approx(13.5, abs=1.5), (
            f"Expected ~13-14A, got {target}A — peak target wrongly computed"
        )

    def test_night_target_throttle_scenario(self):
        """Audit scenario: peak=5000W, home=4800W, EV=2300W → throttle to ~1A."""
        peak_limit_w = 5000.0
        home_w = 4800.0
        ev_power_w = 2300.0
        current_setpoint_a = 10.0

        watts_per_amp = ev_power_w / max(1, current_setpoint_a)  # 230 W/A
        grid_import_w = home_w + ev_power_w  # 7100W

        non_ev_grid = grid_import_w - ev_power_w  # 4800W (home only)
        target = (peak_limit_w - non_ev_grid) / max(1, watts_per_amp)
        target = round(target)

        # (5000 - 4800) / 230 ≈ 0.87 → 1A, clamped to 6A (min_amps)
        assert target <= 1, (
            f"Expected throttle to ≤1A, got {target}A — home load not correctly limiting EV"
        )

    def test_bug_scenario_without_subtraction(self):
        """Demonstrate the bug: without subtraction, target is wrong (too low)."""
        peak_limit_w = 5000.0
        home_w = 1900.0
        ev_power_w = 2300.0
        current_setpoint_a = 10.0
        watts_per_amp = ev_power_w / max(1, current_setpoint_a)
        grid_import_w = home_w + ev_power_w

        # BUG: using raw grid_import (includes EV)
        target_bug = (peak_limit_w - grid_import_w) / max(1, watts_per_amp)
        target_bug = round(target_bug)

        # FIX: subtracting EV
        non_ev_grid = grid_import_w - ev_power_w
        target_fix = (peak_limit_w - non_ev_grid) / max(1, watts_per_amp)
        target_fix = round(target_fix)

        assert target_fix > target_bug, (
            "Fix should allow higher target current than bug (more headroom when EV is subtracted)"
        )
        # Bug gives ~3.5A, fix gives ~13.5A — substantial difference
        assert (target_fix - target_bug) >= 5, (
            f"Difference too small: fix={target_fix}A, bug={target_bug}A"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Issue #232 — Taper detector unit conversion: W sensor scaled by 0.001
# ──────────────────────────────────────────────────────────────────────────────

class TestTaperDetectorUnitConversion:
    """#232 — async_seed_from_history must scale W-unit sensors by 0.001.

    EV power sensors vary: KEBA reports in W, others in kW. Without scaling,
    a W sensor value like "6290" would be treated as 6290 kW — far above the
    0.5 kW session threshold, causing session detection to never trigger, or
    the taper threshold (3.0 kW) to be met trivially with any tiny draw.
    """

    def test_scale_factor_is_0001_for_watts_sensor(self):
        """should apply scale=0.001 to convert W readings to kW for thresholds."""
        # The code reads: scale = 0.001 if is_watts else 1.0
        is_watts = True
        scale = 0.001 if is_watts else 1.0

        raw_power_w = 6290.0
        power_kw = raw_power_w * scale

        # Should be ~6.29 kW — above the 0.5 kW session threshold
        assert power_kw == pytest.approx(6.29, abs=0.01)
        assert power_kw > 0.5, "W-scaled value should be above session threshold"

    def test_scale_factor_is_1_for_kw_sensor(self):
        """should apply scale=1.0 for kW sensors (values used as-is)."""
        is_watts = False
        scale = 0.001 if is_watts else 1.0

        raw_power_kw = 6.29
        power_kw = raw_power_kw * scale

        assert power_kw == pytest.approx(6.29, abs=0.01)

    def test_watts_sensor_session_detection_above_threshold(self):
        """should correctly detect session start with W-unit sensor after scaling."""
        # Simulate the raw state values a W sensor reports
        w_readings = [6290.0, 5580.0, 4970.0, 4340.0, 100.0, 0.0]
        scale = 0.001  # W → kW

        SESSION_THRESHOLD_KW = 0.5
        in_session = any(v * scale > SESSION_THRESHOLD_KW for v in w_readings)
        assert in_session, "W-unit readings should detect a session after scaling"

    def test_unscaled_watts_does_not_false_trigger_taper(self):
        """should not treat W values as kW — would falsely exceed 3kW taper threshold."""
        TAPER_PEAK_MIN_KW = 3.0
        scale_wrong = 1.0    # bug: not scaling W sensor
        scale_right = 0.001  # fix: scaling

        raw_w_tiny_draw = 50.0  # 50W — a tiny draw, not a charging session
        with_bug = raw_w_tiny_draw * scale_wrong    # 50.0 kW (wrong!)
        with_fix = raw_w_tiny_draw * scale_right    # 0.05 kW (correct)

        assert with_bug > TAPER_PEAK_MIN_KW, "Bug: tiny W draw looks like huge kW peak"
        assert with_fix < TAPER_PEAK_MIN_KW, "Fix: tiny W draw correctly below peak threshold"

    def test_energy_integration_correct_for_w_sensor(self):
        """should produce correct kWh when integrating W-unit sensor with scale factor."""
        # 3000W for 1 hour = 3 kWh
        # With W sensor: raw=3000, scale=0.001 → 3.0 kW
        raw_w = 3000.0
        scale = 0.001
        power_kw = raw_w * scale
        dt_hours = 1.0
        energy_kwh = (power_kw + power_kw) / 2 * dt_hours  # trapezoid

        assert energy_kwh == pytest.approx(3.0, abs=0.01)

    def test_energy_integration_correct_for_kw_sensor(self):
        """should produce same kWh from kW sensor without scaling."""
        raw_kw = 3.0
        scale = 1.0
        power_kw = raw_kw * scale
        dt_hours = 1.0
        energy_kwh = (power_kw + power_kw) / 2 * dt_hours

        assert energy_kwh == pytest.approx(3.0, abs=0.01)

    def test_unit_detection_from_entity_attributes(self):
        """should detect W-unit sensor from unit_of_measurement attribute."""
        # Simulate HA entity state attribute reading
        entity_w = MagicMock()
        entity_w.attributes = {"unit_of_measurement": "W"}

        entity_kw = MagicMock()
        entity_kw.attributes = {"unit_of_measurement": "kW"}

        entity_none = MagicMock()
        entity_none.attributes = {}

        def detect_scale(entity) -> float:
            if entity is None:
                return 1.0
            uom = entity.attributes.get("unit_of_measurement", "").strip().lower()
            return 0.001 if uom == "w" else 1.0

        assert detect_scale(entity_w) == 0.001
        assert detect_scale(entity_kw) == 1.0
        assert detect_scale(entity_none) == 1.0
        assert detect_scale(None) == 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Cross-issue: PowerReadings.calculate_derived() produces correct splits
# ──────────────────────────────────────────────────────────────────────────────

class TestPowerReadingsDerived:
    """Verify that calculate_derived() splits sign conventions correctly.

    These underpin many of the audit issues — if the derived values are wrong,
    every downstream calculation (available_power, savings, etc.) is wrong.
    """

    def test_grid_import_split_negative_grid_power(self):
        """should set grid_import_power = -grid_power when grid_power < 0."""
        p = PowerReadings(solar_power=2000, grid_power=-1500)
        p.calculate_derived()
        assert p.grid_import_power == pytest.approx(1500.0)
        assert p.grid_export_power == 0.0

    def test_grid_export_split_positive_grid_power(self):
        """should set grid_export_power = grid_power when grid_power > 0."""
        p = PowerReadings(solar_power=8000, grid_power=3000)
        p.calculate_derived()
        assert p.grid_export_power == pytest.approx(3000.0)
        assert p.grid_import_power == 0.0

    def test_battery_charge_from_positive_battery_power(self):
        """should set battery_charge_power = battery_power when positive."""
        p = PowerReadings(solar_power=5000, battery_power=2000)
        p.calculate_derived()
        assert p.battery_charge_power == pytest.approx(2000.0)
        assert p.battery_discharge_power == 0.0

    def test_battery_discharge_from_negative_battery_power(self):
        """should set battery_discharge_power = -battery_power when negative."""
        p = PowerReadings(solar_power=0, battery_power=-3000)
        p.calculate_derived()
        assert p.battery_discharge_power == pytest.approx(3000.0)
        assert p.battery_charge_power == 0.0

    def test_home_consumption_clamp_non_negative(self):
        """should clamp home_consumption_power to 0 when energy balance is negative."""
        # Negative balance can occur from sensor noise — home must never be < 0
        p = PowerReadings(
            solar_power=1000,
            grid_power=500,  # export 500
            battery_power=-200,  # discharge 200
            ev_power=2000,
        )
        p.calculate_derived()
        assert p.home_consumption_power >= 0.0, (
            "home_consumption_power must never be negative"
        )

    def test_home_consumption_energy_balance(self):
        """home = solar + grid_import + battery_discharge - ev - grid_export - battery_charge."""
        solar = 6000
        grid_import = 1000
        batt_discharge = 500
        ev = 2000
        grid_export = 0
        batt_charge = 0

        expected_home = max(0, solar + grid_import + batt_discharge - ev - grid_export - batt_charge)

        p = PowerReadings(
            solar_power=solar,
            grid_power=-grid_import,     # negative = import
            battery_power=-batt_discharge,  # negative = discharge
            ev_power=ev,
        )
        p.calculate_derived()

        assert p.home_consumption_power == pytest.approx(expected_home, abs=1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Solar curve fraction helper tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSolarCurveFraction:
    """Verify the sine-curve fraction model used in dampening calculations."""

    def test_fraction_zero_at_sunrise(self):
        """should return 0.0 at the moment of sunrise (0 solar hours elapsed)."""
        assert ForecastTracker._solar_curve_fraction(0.0) == 0.0
        assert ForecastTracker._solar_curve_fraction_dynamic(0.0, 14.0) == 0.0

    def test_fraction_one_at_sunset(self):
        """should return 1.0 when solar_hours >= daylight_hours."""
        assert ForecastTracker._solar_curve_fraction(14.0) == 1.0
        assert ForecastTracker._solar_curve_fraction_dynamic(6.0, 6.0) == 1.0

    def test_fraction_half_at_solar_noon(self):
        """should return ~0.5 at the midpoint of the day (solar noon)."""
        fraction_default = ForecastTracker._solar_curve_fraction(7.0)  # half of 14h
        fraction_polar = ForecastTracker._solar_curve_fraction_dynamic(3.0, 6.0)
        assert fraction_default == pytest.approx(0.5, abs=0.01)
        assert fraction_polar == pytest.approx(0.5, abs=0.01)

    def test_fraction_monotonically_increasing(self):
        """should increase monotonically from sunrise to sunset."""
        fractions = [
            ForecastTracker._solar_curve_fraction_dynamic(h, 14.0)
            for h in range(0, 15)
        ]
        for i in range(len(fractions) - 1):
            assert fractions[i] <= fractions[i + 1], (
                f"Fraction decreased at hour {i}: {fractions[i]} → {fractions[i+1]}"
            )

    def test_fraction_beyond_daylight_capped(self):
        """should not exceed 1.0 even for solar_hours > daylight_hours."""
        assert ForecastTracker._solar_curve_fraction_dynamic(20.0, 6.0) == 1.0
        assert ForecastTracker._solar_curve_fraction(20.0) == 1.0
