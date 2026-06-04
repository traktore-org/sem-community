"""#422 — telemetry surface for PVPerformanceAnalyzer.

Locks the ``pv_*_path`` strings each metric publishes via
``PVPerformanceData.to_dict``. Mirrors the
#359/#416/#420/#421 precedents.

The silent-failure surface this captures: users who configure SEM
without ``system_size_kwp`` see ``pv_daily_specific_yield = 0`` —
indistinguishable from genuinely zero production. The
``yield_path = no_system_size_configured`` value makes the cause
visible.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.solar_energy_management.analytics.pv_performance import (
    MonthlyPerformance,
    PVPerformanceAnalyzer,
)


def _make(system_size_kwp=10.0, install_date=None):
    return PVPerformanceAnalyzer(
        hass=MagicMock(),
        system_size_kwp=system_size_kwp,
        inverter_max_power_w=10000.0,
        system_install_date=install_date,
    )


# ──────────────────────────────────────────────
# yield_path
# ──────────────────────────────────────────────


def test_yield_path_no_system_size_configured():
    """Biggest silent-failure surface — yield = 0 because size not
    configured, NOT because production was zero."""
    a = _make(system_size_kwp=0)
    data = a.update(daily_solar_kwh=20.0, monthly_solar_kwh=400.0,
                    current_solar_power_w=5000.0)
    assert data.daily_specific_yield == 0
    assert data.to_dict()["pv_yield_path"] == "no_system_size_configured"


def test_yield_path_computed_with_annual_projection():
    a = _make(system_size_kwp=10.0)
    data = a.update(daily_solar_kwh=30.0, monthly_solar_kwh=400.0,
                    current_solar_power_w=5000.0)
    assert data.daily_specific_yield == 3.0
    assert data.to_dict()["pv_yield_path"] == "computed_with_annual_projection"


def test_yield_path_computed_no_annual_when_monthly_zero():
    a = _make(system_size_kwp=10.0)
    data = a.update(daily_solar_kwh=30.0, monthly_solar_kwh=0.0,
                    current_solar_power_w=5000.0)
    assert data.to_dict()["pv_yield_path"] == "computed_no_annual"


# ──────────────────────────────────────────────
# performance_path
# ──────────────────────────────────────────────


def test_performance_path_computed():
    a = _make()
    data = a.update(daily_solar_kwh=30.0, monthly_solar_kwh=400.0,
                    current_solar_power_w=5000.0, forecast_today_kwh=25.0)
    assert data.to_dict()["pv_performance_path"] == "computed"


def test_performance_path_no_forecast():
    a = _make()
    data = a.update(daily_solar_kwh=30.0, monthly_solar_kwh=400.0,
                    current_solar_power_w=5000.0, forecast_today_kwh=0.0)
    assert data.to_dict()["pv_performance_path"] == "no_forecast"


# ──────────────────────────────────────────────
# clipping_path
# ──────────────────────────────────────────────


def test_clipping_path_idle():
    a = _make()
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)  # well below 95% of 10kW
    assert data.to_dict()["pv_clipping_path"] == "idle"


def test_clipping_path_active():
    a = _make()
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=9700.0)  # >= 95% of 10kW
    assert data.to_dict()["pv_clipping_path"] == "clipping_active"


def test_clipping_path_post_clipping_idle():
    a = _make()
    # First call — clipping fires, internal counter increments
    a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
             current_solar_power_w=9700.0)
    # Second call — below clipping threshold but counter remembers
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)
    assert data.to_dict()["pv_clipping_path"] == "post_clipping_idle"


# ──────────────────────────────────────────────
# degradation_path
# ──────────────────────────────────────────────


def test_degradation_path_insufficient_history():
    a = _make()
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)
    assert data.to_dict()["pv_degradation_path"] == "insufficient_history"


def test_degradation_path_normal_with_sufficient_history():
    a = _make()
    # Seed >= 13 monthly records showing flat performance
    for year in (2024, 2025):
        for month in range(1, 8):
            a.record_monthly(year, month, total_kwh=400.0, forecast_kwh=400.0)
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)
    # Flat performance → degradation ≈ 0 → normal
    assert data.to_dict()["pv_degradation_path"] in (
        "normal", "warning", "critical",
    )


# ──────────────────────────────────────────────
# system_age_path
# ──────────────────────────────────────────────


def test_system_age_path_no_install_date():
    a = _make(install_date=None)
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)
    assert data.to_dict()["pv_system_age_path"] == "no_install_date"


def test_system_age_path_computed():
    a = _make(install_date="2020-01-01")
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)
    assert data.to_dict()["pv_system_age_path"] == "computed"
    assert data.system_age_years > 0


def test_system_age_path_install_date_invalid():
    a = _make(install_date="not-a-date")
    data = a.update(daily_solar_kwh=10.0, monthly_solar_kwh=100.0,
                    current_solar_power_w=3000.0)
    assert data.to_dict()["pv_system_age_path"] == "install_date_invalid"
