"""Energy assistant — proactive smart recommendations.

Analyzes usage patterns and generates actionable tips:
- EV charging optimization (shift to solar hours)
- Surplus utilization (add hot water diverter, etc.)
- Price-responsive suggestions (night charging at cheap hours)
- Overall optimization score (0-100)
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class EnergyTip:
    """A single energy optimization tip."""
    category: str          # ev, surplus, price, general
    title: str
    description: str
    estimated_savings: Optional[str] = None  # e.g., "5 CHF/month"
    priority: int = 5      # 1=urgent, 10=nice-to-know
    created: Optional[datetime] = None


@dataclass
class EnergyAssistantData:
    """Energy assistant output data."""
    optimization_score: int = 0     # 0-100
    current_tip: Optional[str] = None
    tip_category: Optional[str] = None
    tips_count: int = 0
    self_consumption_trend: str = "stable"
    grid_dependency_trend: str = "stable"
    ev_solar_percentage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "energy_optimization_score": self.optimization_score,
            "energy_tip": self.current_tip or "No recommendations at this time",
            "energy_tip_category": self.tip_category or "none",
            "energy_tips_count": self.tips_count,
            "energy_self_consumption_trend": self.self_consumption_trend,
            "energy_grid_dependency_trend": self.grid_dependency_trend,
            "energy_ev_solar_percentage": round(self.ev_solar_percentage, 1),
        }


class EnergyAssistant:
    """Generates energy optimization recommendations."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._tips: List[EnergyTip] = []
        self._tip_rotation_index: int = 0
        self._last_analysis: Optional[datetime] = None
        self._last_data = EnergyAssistantData()
        self._daily_stats: List[Dict[str, float]] = []

    @property
    def assistant_data(self) -> EnergyAssistantData:
        return self._last_data

    def analyze(
        self,
        daily_solar_kwh: float = 0.0,
        daily_home_kwh: float = 0.0,
        daily_ev_kwh: float = 0.0,
        daily_grid_import_kwh: float = 0.0,
        daily_grid_export_kwh: float = 0.0,
        daily_battery_charge_kwh: float = 0.0,
        daily_battery_discharge_kwh: float = 0.0,
        solar_to_ev_kwh: float = 0.0,
        grid_to_ev_kwh: float = 0.0,
        self_consumption_rate: float = 0.0,
        autarky_rate: float = 0.0,
        current_price_level: Optional[str] = None,
        forecast_remaining_kwh: float = 0.0,
        forecast_tomorrow_kwh: float = 0.0,
        best_surplus_window: str = "",
        peak_time_today: str = "",
        battery_soc: float = 0.0,
        has_heat_pump: bool = False,
        has_hot_water: bool = False,
    ) -> EnergyAssistantData:
        """Run analysis and generate recommendations."""
        self._tips = []
        now = datetime.now()

        # Track daily stats for trend analysis
        self._record_daily_stats(
            daily_solar_kwh, daily_home_kwh, daily_ev_kwh,
            daily_grid_import_kwh, daily_grid_export_kwh,
            self_consumption_rate, autarky_rate,
        )

        # Generate tips based on current data
        self._analyze_ev_charging(
            daily_ev_kwh, solar_to_ev_kwh, grid_to_ev_kwh, forecast_remaining_kwh,
        )
        self._analyze_surplus(
            daily_grid_export_kwh, daily_solar_kwh,
            has_heat_pump, has_hot_water,
        )
        self._analyze_self_consumption(
            self_consumption_rate, daily_grid_export_kwh, daily_solar_kwh,
        )
        self._analyze_price(current_price_level, daily_grid_import_kwh)
        self._analyze_battery(
            daily_battery_charge_kwh, daily_battery_discharge_kwh,
            daily_grid_import_kwh,
        )
        self._analyze_forecast_scheduling(
            forecast_remaining_kwh, forecast_tomorrow_kwh,
            best_surplus_window, peak_time_today,
            battery_soc, daily_solar_kwh,
        )

        # Calculate optimization score
        score = self._calculate_score(
            self_consumption_rate, autarky_rate,
            daily_grid_export_kwh, daily_solar_kwh,
            daily_ev_kwh, solar_to_ev_kwh,
        )

        # EV solar percentage
        ev_solar_pct = 0.0
        if daily_ev_kwh > 0 and solar_to_ev_kwh > 0:
            ev_solar_pct = (solar_to_ev_kwh / daily_ev_kwh) * 100

        # Rotate through tips
        current_tip = None
        tip_category = None
        if self._tips:
            self._tips.sort(key=lambda t: t.priority)
            idx = self._tip_rotation_index % len(self._tips)
            current_tip = self._tips[idx].description
            tip_category = self._tips[idx].category
            self._tip_rotation_index += 1

        self._last_data = EnergyAssistantData(
            optimization_score=score,
            current_tip=current_tip,
            tip_category=tip_category,
            tips_count=len(self._tips),
            self_consumption_trend=self._get_trend("self_consumption"),
            grid_dependency_trend=self._get_trend("grid_import"),
            ev_solar_percentage=ev_solar_pct,
        )

        self._last_analysis = now
        return self._last_data

    def _analyze_ev_charging(
        self,
        daily_ev_kwh: float,
        solar_to_ev_kwh: float,
        grid_to_ev_kwh: float,
        forecast_remaining_kwh: float,
    ) -> None:
        """Analyze EV charging patterns."""
        if daily_ev_kwh <= 0:
            return

        solar_pct = (solar_to_ev_kwh / daily_ev_kwh * 100) if daily_ev_kwh > 0 else 0

        if solar_pct < 50 and daily_ev_kwh > 2:
            self._tips.append(EnergyTip(
                category="ev",
                title="EV charging mostly from grid",
                description=(
                    f"Only {solar_pct:.0f}% of EV charging is from solar. "
                    f"Shifting charging to 10:00-15:00 could significantly reduce grid usage."
                ),
                estimated_savings="5-15 CHF/month",
                priority=2,
                created=datetime.now(),
            ))

        if forecast_remaining_kwh > daily_ev_kwh * 2:
            self._tips.append(EnergyTip(
                category="ev",
                title="Good solar day ahead",
                description=(
                    f"Solar forecast shows {forecast_remaining_kwh:.1f} kWh remaining today. "
                    f"Solar charging should cover your EV needs — consider deferring grid charging."
                ),
                priority=4,
                created=datetime.now(),
            ))

    def _analyze_surplus(
        self,
        daily_export_kwh: float,
        daily_solar_kwh: float,
        has_heat_pump: bool,
        has_hot_water: bool,
    ) -> None:
        """Analyze surplus/export patterns."""
        if daily_solar_kwh <= 0:
            return

        export_pct = (daily_export_kwh / daily_solar_kwh * 100)

        if export_pct > 50 and not has_hot_water:
            self._tips.append(EnergyTip(
                category="surplus",
                title="High solar export",
                description=(
                    f"{export_pct:.0f}% of solar is exported. "
                    f"Adding a hot water diverter would capture ~{daily_export_kwh * 0.4:.1f} kWh/day."
                ),
                estimated_savings="10-20 CHF/month",
                priority=3,
                created=datetime.now(),
            ))

        if export_pct > 60 and not has_heat_pump:
            self._tips.append(EnergyTip(
                category="surplus",
                title="Consider heat pump solar boost",
                description=(
                    f"With {export_pct:.0f}% export rate, an SG-Ready heat pump "
                    f"could use solar surplus for water/space heating."
                ),
                priority=5,
                created=datetime.now(),
            ))

    def _analyze_self_consumption(
        self,
        self_consumption_rate: float,
        daily_export_kwh: float,
        daily_solar_kwh: float,
    ) -> None:
        """Analyze self-consumption rate."""
        if self_consumption_rate > 80:
            self._tips.append(EnergyTip(
                category="general",
                title="Excellent self-consumption",
                description=(
                    f"Self-consumption at {self_consumption_rate:.0f}% — well optimized. "
                    f"Your system is efficiently using solar production."
                ),
                priority=8,
                created=datetime.now(),
            ))
        elif self_consumption_rate < 40 and daily_solar_kwh > 5:
            self._tips.append(EnergyTip(
                category="general",
                title="Low self-consumption",
                description=(
                    f"Self-consumption at {self_consumption_rate:.0f}%. "
                    f"Consider shifting loads to midday or adding battery storage."
                ),
                priority=2,
                created=datetime.now(),
            ))

    def _analyze_price(
        self, price_level: Optional[str], daily_grid_import_kwh: float
    ) -> None:
        """Generate price-based recommendations."""
        if not price_level:
            return

        if price_level in ("cheap", "very_cheap", "negative"):
            self._tips.append(EnergyTip(
                category="price",
                title="Cheap electricity now",
                description=(
                    f"Electricity price is currently {price_level}. "
                    f"Good time to charge EV or run appliances from grid."
                ),
                priority=3,
                created=datetime.now(),
            ))
        elif price_level in ("expensive", "very_expensive"):
            self._tips.append(EnergyTip(
                category="price",
                title="Expensive electricity",
                description=(
                    f"Electricity price is {price_level}. "
                    f"Minimize grid import — use battery and defer non-essential loads."
                ),
                priority=2,
                created=datetime.now(),
            ))

    def _analyze_battery(
        self,
        charge_kwh: float,
        discharge_kwh: float,
        grid_import_kwh: float,
    ) -> None:
        """Analyze battery usage patterns."""
        if charge_kwh <= 0 and discharge_kwh <= 0:
            return

        if discharge_kwh > 0 and grid_import_kwh > discharge_kwh * 2:
            self._tips.append(EnergyTip(
                category="general",
                title="Battery could offset more grid import",
                description=(
                    f"Battery discharged {discharge_kwh:.1f} kWh but grid import was "
                    f"{grid_import_kwh:.1f} kWh. Consider adjusting battery strategy "
                    f"to cover peak consumption hours."
                ),
                priority=4,
                created=datetime.now(),
            ))

    def _analyze_forecast_scheduling(
        self,
        forecast_remaining_kwh: float,
        forecast_tomorrow_kwh: float,
        best_surplus_window: str,
        peak_time_today: str,
        battery_soc: float,
        daily_solar_kwh: float,
    ) -> None:
        """Generate forecast-aware scheduling recommendations."""
        now = datetime.now()
        hour = now.hour

        # Best time to run appliances
        if best_surplus_window and forecast_remaining_kwh > 3:
            self._tips.append(EnergyTip(
                category="forecast",
                title="Best window for large appliances",
                description=(
                    f"Run dishwasher, washing machine, or dryer during "
                    f"{best_surplus_window} — expected {forecast_remaining_kwh:.1f} kWh "
                    f"solar surplus remaining today."
                ),
                priority=2,
                created=now,
            ))

        # Battery full soon — use surplus
        if battery_soc >= 85 and forecast_remaining_kwh > 2 and hour < 15:
            self._tips.append(EnergyTip(
                category="forecast",
                title="Battery nearly full — use surplus now",
                description=(
                    f"Battery at {battery_soc:.0f}% with {forecast_remaining_kwh:.1f} kWh "
                    f"solar still expected. Start large appliances to avoid export."
                ),
                priority=2,
                created=now,
            ))

        # Low solar tomorrow — act today
        if (forecast_tomorrow_kwh < 5 and forecast_remaining_kwh > 3
                and hour < 16 and daily_solar_kwh > 5):
            self._tips.append(EnergyTip(
                category="forecast",
                title="Low solar tomorrow — use surplus today",
                description=(
                    f"Tomorrow's forecast is only {forecast_tomorrow_kwh:.1f} kWh. "
                    f"Consider running appliances today while "
                    f"{forecast_remaining_kwh:.1f} kWh surplus is still available."
                ),
                priority=3,
                created=now,
            ))

        # Good solar tomorrow — defer loads
        if (forecast_tomorrow_kwh > 15 and forecast_remaining_kwh < 2
                and hour >= 14):
            self._tips.append(EnergyTip(
                category="forecast",
                title="Strong solar tomorrow — defer loads",
                description=(
                    f"Tomorrow's forecast is {forecast_tomorrow_kwh:.1f} kWh. "
                    f"Consider deferring large appliances to tomorrow for free solar."
                ),
                priority=4,
                created=now,
            ))

        # Evening: charge EV tonight if tomorrow is weak
        if (hour >= 18 and forecast_tomorrow_kwh < 8
                and forecast_tomorrow_kwh > 0):
            self._tips.append(EnergyTip(
                category="forecast",
                title="Weak solar tomorrow — charge EV tonight",
                description=(
                    f"Tomorrow: only {forecast_tomorrow_kwh:.1f} kWh expected. "
                    f"Night charging recommended to ensure the EV is ready."
                ),
                priority=3,
                created=now,
            ))

    def _calculate_score(
        self,
        self_consumption_rate: float,
        autarky_rate: float,
        export_kwh: float,
        solar_kwh: float,
        ev_kwh: float,
        solar_to_ev_kwh: float,
    ) -> int:
        """Calculate optimization score (0-100)."""
        score = 0.0

        # Self-consumption (40 points max)
        score += min(40, self_consumption_rate * 0.4)

        # Autarky (30 points max)
        score += min(30, autarky_rate * 0.3)

        # EV solar charging (20 points max)
        if ev_kwh > 0:
            ev_solar_pct = (solar_to_ev_kwh / ev_kwh * 100)
            score += min(20, ev_solar_pct * 0.2)
        else:
            score += 10  # No EV charging needed = neutral

        # Low export bonus (10 points max)
        if solar_kwh > 0:
            export_pct = (export_kwh / solar_kwh * 100)
            score += max(0, 10 - export_pct * 0.1)

        return max(0, min(100, int(score)))

    def _record_daily_stats(
        self,
        solar: float, home: float, ev: float,
        grid_import: float, grid_export: float,
        self_consumption: float, autarky: float,
    ) -> None:
        """Record daily stats for trend analysis."""
        today = date.today().isoformat()
        # Only keep one entry per day
        if self._daily_stats and self._daily_stats[-1].get("date") == today:
            self._daily_stats[-1] = {
                "date": today,
                "self_consumption": self_consumption,
                "grid_import": grid_import,
                "grid_export": grid_export,
            }
        else:
            self._daily_stats.append({
                "date": today,
                "self_consumption": self_consumption,
                "grid_import": grid_import,
                "grid_export": grid_export,
            })

        # Keep last 30 days
        if len(self._daily_stats) > 30:
            self._daily_stats = self._daily_stats[-30:]

    def _get_trend(self, metric: str) -> str:
        """Calculate trend for a metric over recent days."""
        if len(self._daily_stats) < 3:
            return "stable"

        recent = self._daily_stats[-7:]  # Last 7 days
        if len(recent) < 3:
            return "stable"

        values = [d.get(metric, 0) for d in recent]
        first_half = sum(values[:len(values)//2]) / max(1, len(values)//2)
        second_half = sum(values[len(values)//2:]) / max(1, len(values) - len(values)//2)

        if second_half > first_half * 1.1:
            return "rising"
        elif second_half < first_half * 0.9:
            return "falling"
        return "stable"

    def get_all_tips(self) -> List[Dict[str, Any]]:
        """Get all current tips for display."""
        return [
            {
                "category": t.category,
                "title": t.title,
                "description": t.description,
                "savings": t.estimated_savings,
                "priority": t.priority,
            }
            for t in sorted(self._tips, key=lambda t: t.priority)
        ]
