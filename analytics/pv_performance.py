"""PV performance monitoring and degradation analysis.

Metrics:
- Specific yield (kWh/kWp) — normalized production
- Performance ratio — actual vs forecast
- Weather-normalized performance
- Degradation detection via monthly trend analysis
- Loss analysis: inverter clipping, curtailment estimation
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class PVPerformanceData:
    """PV system performance metrics."""
    # Specific yield
    daily_specific_yield: float = 0.0      # kWh/kWp today
    monthly_specific_yield: float = 0.0    # kWh/kWp this month
    annual_specific_yield: float = 0.0     # kWh/kWp estimated annual

    # Performance ratio (actual vs expected)
    performance_vs_forecast: float = 0.0   # % (100% = exactly as forecast)
    daily_performance_ratio: float = 0.0   # % PR for today

    # Degradation
    estimated_annual_degradation: float = 0.0  # % per year
    degradation_trend: str = "unknown"          # normal, warning, critical

    # Loss analysis
    clipping_losses_kwh: float = 0.0   # Estimated inverter clipping losses
    curtailment_kwh: float = 0.0       # Grid curtailment losses
    shading_factor: float = 1.0        # 1.0 = no shading

    # System info
    system_size_kwp: float = 0.0
    system_age_years: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pv_daily_specific_yield": round(self.daily_specific_yield, 2),
            "pv_monthly_specific_yield": round(self.monthly_specific_yield, 2),
            "pv_annual_specific_yield": round(self.annual_specific_yield, 1),
            "pv_performance_vs_forecast": round(self.performance_vs_forecast, 1),
            "pv_daily_performance_ratio": round(self.daily_performance_ratio, 1),
            "pv_estimated_annual_degradation": round(self.estimated_annual_degradation, 2),
            "pv_degradation_trend": self.degradation_trend,
            "pv_clipping_losses_kwh": round(self.clipping_losses_kwh, 2),
            "pv_curtailment_kwh": round(self.curtailment_kwh, 2),
        }


@dataclass
class MonthlyPerformance:
    """Monthly performance record for degradation tracking."""
    year: int
    month: int
    total_kwh: float
    specific_yield: float
    forecast_kwh: float
    performance_ratio: float


class PVPerformanceAnalyzer:
    """Analyzes PV system performance and detects degradation."""

    def __init__(
        self,
        hass: HomeAssistant,
        system_size_kwp: float = 10.0,
        inverter_max_power_w: float = 10000.0,
        system_install_date: Optional[str] = None,
    ):
        self.hass = hass
        self.system_size_kwp = system_size_kwp
        self.inverter_max_power_w = inverter_max_power_w
        self.system_install_date = system_install_date
        self._monthly_history: List[MonthlyPerformance] = []
        self._daily_peak_power: float = 0.0
        self._clipping_minutes: int = 0
        self._last_data = PVPerformanceData()

    @property
    def performance_data(self) -> PVPerformanceData:
        return self._last_data

    def update(
        self,
        daily_solar_kwh: float,
        monthly_solar_kwh: float,
        current_solar_power_w: float,
        forecast_today_kwh: float = 0.0,
        forecast_remaining_kwh: float = 0.0,
    ) -> PVPerformanceData:
        """Update performance metrics with current data."""
        data = PVPerformanceData()
        data.system_size_kwp = self.system_size_kwp

        # System age
        if self.system_install_date:
            try:
                install = datetime.fromisoformat(self.system_install_date)
                data.system_age_years = (datetime.now() - install).days / 365.25
            except ValueError:
                pass

        # Specific yield (kWh/kWp)
        if self.system_size_kwp > 0:
            data.daily_specific_yield = daily_solar_kwh / self.system_size_kwp
            data.monthly_specific_yield = monthly_solar_kwh / self.system_size_kwp
            # Annualize from monthly (rough estimate)
            today = date.today()
            days_in_month = 30
            if data.monthly_specific_yield > 0 and today.day > 0:
                daily_avg = data.monthly_specific_yield / today.day
                data.annual_specific_yield = daily_avg * 365

        # Performance vs forecast
        if forecast_today_kwh > 0:
            data.performance_vs_forecast = (daily_solar_kwh / forecast_today_kwh) * 100
            data.daily_performance_ratio = data.performance_vs_forecast

        # Clipping detection
        if current_solar_power_w >= self.inverter_max_power_w * 0.95:
            self._clipping_minutes += 1  # Approximate: 1 call ≈ 10s
            data.clipping_losses_kwh = (
                self._clipping_minutes * 10 / 3600 *
                (current_solar_power_w - self.inverter_max_power_w * 0.95) / 1000
            )

        # Track daily peak
        if current_solar_power_w > self._daily_peak_power:
            self._daily_peak_power = current_solar_power_w

        # Degradation analysis from monthly history
        data.estimated_annual_degradation = self._estimate_degradation()
        if data.estimated_annual_degradation > 2.0:
            data.degradation_trend = "critical"
        elif data.estimated_annual_degradation > 1.0:
            data.degradation_trend = "warning"
        elif data.estimated_annual_degradation >= 0:
            data.degradation_trend = "normal"

        self._last_data = data
        return data

    def record_monthly(
        self,
        year: int,
        month: int,
        total_kwh: float,
        forecast_kwh: float = 0.0,
    ) -> None:
        """Record monthly performance for degradation tracking."""
        specific_yield = total_kwh / self.system_size_kwp if self.system_size_kwp > 0 else 0
        pr = (total_kwh / forecast_kwh * 100) if forecast_kwh > 0 else 0

        record = MonthlyPerformance(
            year=year,
            month=month,
            total_kwh=total_kwh,
            specific_yield=specific_yield,
            forecast_kwh=forecast_kwh,
            performance_ratio=pr,
        )
        self._monthly_history.append(record)

        # Keep last 36 months
        if len(self._monthly_history) > 36:
            self._monthly_history = self._monthly_history[-36:]

    def _estimate_degradation(self) -> float:
        """Estimate annual degradation from monthly history.

        Compares same-month performance across years to account for
        seasonal variation. Returns estimated % degradation per year.
        """
        if len(self._monthly_history) < 13:
            return 0.0  # Need at least 13 months

        # Group by month and compare year-over-year
        by_month: Dict[int, List[MonthlyPerformance]] = {}
        for record in self._monthly_history:
            by_month.setdefault(record.month, []).append(record)

        degradation_rates = []
        for month, records in by_month.items():
            if len(records) < 2:
                continue
            records.sort(key=lambda r: r.year)
            for i in range(1, len(records)):
                prev = records[i - 1]
                curr = records[i]
                if prev.specific_yield > 0:
                    yearly_change = (
                        (curr.specific_yield - prev.specific_yield) / prev.specific_yield * 100
                    )
                    # Negative = degradation
                    degradation_rates.append(-yearly_change)

        if not degradation_rates:
            return 0.0

        # Average degradation rate, clamped to reasonable range
        avg = sum(degradation_rates) / len(degradation_rates)
        return max(0, min(5.0, avg))  # 0-5% range

    def reset_daily(self) -> None:
        """Reset daily tracking counters."""
        self._daily_peak_power = 0.0
        self._clipping_minutes = 0

    def get_monthly_history(self) -> List[Dict[str, Any]]:
        """Get monthly history for frontend display."""
        return [
            {
                "year": r.year,
                "month": r.month,
                "kwh": round(r.total_kwh, 1),
                "specific_yield": round(r.specific_yield, 2),
                "performance_ratio": round(r.performance_ratio, 1),
            }
            for r in self._monthly_history
        ]
