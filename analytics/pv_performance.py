"""PV performance monitoring and degradation analysis.

Metrics:
- Specific yield (kWh/kWp) — normalized production
- Performance ratio — actual vs forecast
- Weather-normalized performance
- Degradation detection via monthly trend analysis
- Loss analysis: inverter clipping, curtailment estimation
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

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

    # #422 — telemetry attribution per metric. Each ``*_path`` records
    # which branch produced the value (e.g. ``no_size_configured`` vs
    # ``computed``), so users hitting unexpected zeros can self-diagnose.
    yield_path: str = "uninitialized"
    performance_path: str = "uninitialized"
    clipping_path: str = "uninitialized"
    degradation_path: str = "uninitialized"
    system_age_path: str = "uninitialized"

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
            # #422 — telemetry surface (mirrors #359/#416/#420 pattern).
            "pv_yield_path": self.yield_path,
            "pv_performance_path": self.performance_path,
            "pv_clipping_path": self.clipping_path,
            "pv_degradation_path": self.degradation_path,
            "pv_system_age_path": self.system_age_path,
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
                data.system_age_path = "computed"
            except ValueError:
                data.system_age_path = "install_date_invalid"
        else:
            data.system_age_path = "no_install_date"

        # Specific yield (kWh/kWp)
        if self.system_size_kwp > 0:
            data.daily_specific_yield = daily_solar_kwh / self.system_size_kwp
            data.monthly_specific_yield = monthly_solar_kwh / self.system_size_kwp
            # Annualize from monthly (rough estimate)
            # (#645) HA-local — the OS clock is often UTC in the container.
            # ``today.day`` is the divisor for the month-to-date average, so a
            # naive clock divides by the wrong day count at a month boundary.
            today = dt_util.now().date()
            if data.monthly_specific_yield > 0 and today.day > 0:
                daily_avg = data.monthly_specific_yield / today.day
                data.annual_specific_yield = daily_avg * 365
                data.yield_path = "computed_with_annual_projection"
            else:
                data.yield_path = "computed_no_annual"
        else:
            # Silent-failure surface: zero yield because system_size_kwp
            # wasn't configured, not because production was zero. Users
            # seeing pv_daily_specific_yield = 0 need to know which.
            data.yield_path = "no_system_size_configured"

        # Performance vs forecast
        if forecast_today_kwh > 0:
            data.performance_vs_forecast = (daily_solar_kwh / forecast_today_kwh) * 100
            data.daily_performance_ratio = data.performance_vs_forecast
            data.performance_path = "computed"
        else:
            data.performance_path = "no_forecast"

        # Clipping detection
        if current_solar_power_w >= self.inverter_max_power_w * 0.95:
            self._clipping_minutes += 1  # Approximate: 1 call ≈ 10s
            data.clipping_losses_kwh = (
                self._clipping_minutes * 10 / 3600 *
                (current_solar_power_w - self.inverter_max_power_w * 0.95) / 1000
            )
            data.clipping_path = "clipping_active"
        elif self._clipping_minutes > 0:
            data.clipping_path = "post_clipping_idle"
        else:
            data.clipping_path = "idle"

        # Track daily peak
        if current_solar_power_w > self._daily_peak_power:
            self._daily_peak_power = current_solar_power_w

        # Degradation analysis from monthly history
        data.estimated_annual_degradation = self._estimate_degradation()
        if len(self._monthly_history) < 13:
            data.degradation_path = "insufficient_history"
        elif data.estimated_annual_degradation > 2.0:
            data.degradation_trend = "critical"
            data.degradation_path = "critical"
        elif data.estimated_annual_degradation > 1.0:
            data.degradation_trend = "warning"
            data.degradation_path = "warning"
        elif data.estimated_annual_degradation >= 0:
            data.degradation_trend = "normal"
            data.degradation_path = "normal"

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

        # Keep the retention window — one constant, read by the recorder
        # and by restore_state, so the two can never disagree.
        if len(self._monthly_history) > self.MAX_MONTHS:
            self._monthly_history = self._monthly_history[-self.MAX_MONTHS:]

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
        for _month, records in by_month.items():
            if len(records) < 2:
                continue
            records.sort(key=lambda r: r.year)
            for i in range(1, len(records)):
                prev = records[i - 1]
                curr = records[i]
                # (#867) Divide by the YEARS BETWEEN them. Comparing
                # consecutive same-month records treats every pair as exactly
                # one year apart, but a gap — an outage, a skipped
                # zero-production month, a pack of history restored from an
                # older store — makes a multi-year drift price as one year's
                # rate: three years of a real 1.5 %/yr decline reported as
                # 4.5 %/yr, a 3x overstatement that the 0-5 % clamp below
                # hides rather than fixes. Degradation is a number someone may
                # call an installer about; it must not read a data gap as
                # decay.
                span_years = curr.year - prev.year
                if span_years <= 0:
                    # A duplicate month (a re-record after a restart) spans no
                    # time and says nothing about decay.
                    continue
                if prev.specific_yield > 0:
                    total_change = (
                        (curr.specific_yield - prev.specific_yield) / prev.specific_yield * 100
                    )
                    # Negative = degradation, per year of actual elapsed time
                    degradation_rates.append(-total_change / span_years)

        if not degradation_rates:
            return 0.0

        # Average degradation rate, clamped to reasonable range
        avg = sum(degradation_rates) / len(degradation_rates)
        return max(0, min(5.0, avg))  # 0-5% range

    def reset_daily(self) -> None:
        """Reset daily tracking counters."""
        self._daily_peak_power = 0.0
        self._clipping_minutes = 0

    #: Retention for the degradation comparison. 13 months is the minimum
    #: that can compare a month against itself a year earlier; 36 gives the
    #: estimate three same-month pairs to average over.
    MAX_MONTHS = 36

    def export_state(self) -> Dict[str, Any]:
        """The monthly history, for the store.

        (#867) Without this the list lived only in memory: created empty in
        ``__init__`` and never written anywhere. Degradation needs 13 months
        of evidence, and no process that restarts on every upgrade will ever
        hold 13 months of anything. The verdict was 0.0 on installs with
        years of production, and would have stayed 0.0 even once something
        started recording.
        """
        return {"monthly_history": [
            {"year": r.year, "month": r.month, "total_kwh": r.total_kwh,
             "specific_yield": r.specific_yield, "forecast_kwh": r.forecast_kwh,
             "performance_ratio": r.performance_ratio}
            for r in self._monthly_history
        ]}

    def restore_state(self, state: Optional[Dict[str, Any]]) -> None:
        """Load the monthly history back.

        Stored state outlives the code that wrote it, so a row that does not
        parse is SKIPPED rather than fatal — losing one month costs a little
        precision, and raising here would cost the whole integration its
        startup. The retention cap is applied on the way in too: a store
        written by a future version with a larger cap must not smuggle more
        history past this one's rule.
        """
        rows = (state or {}).get("monthly_history")
        if not isinstance(rows, list):
            self._monthly_history = []
            return
        restored: List[MonthlyPerformance] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                restored.append(MonthlyPerformance(
                    year=int(row["year"]),
                    month=int(row["month"]),
                    total_kwh=float(row.get("total_kwh", 0.0)),
                    specific_yield=float(row.get("specific_yield", 0.0)),
                    forecast_kwh=float(row.get("forecast_kwh", 0.0)),
                    performance_ratio=float(row.get("performance_ratio", 0.0)),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        self._monthly_history = restored[-self.MAX_MONTHS:]

    def has_month(self, year: int, month: int) -> bool:
        """(#867) Already recorded? The recorder is driven from a per-cycle
        rollover check, so it must be idempotent: asking this is what keeps a
        month from being appended once per cycle for a whole month."""
        return any(r.year == year and r.month == month
                   for r in self._monthly_history)

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
