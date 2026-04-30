"""Energy calculation module for SEM coordinator."""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .types import PowerReadings, EnergyTotals, CostData, PerformanceMetrics
from ..utils.time_manager import TimeManager

_LOGGER = logging.getLogger(__name__)

# Minimum power thresholds to prevent ghost accumulation
MIN_POWER_THRESHOLD = 10  # Watts

# Maximum integration gap — skip cycle if sensors were unavailable longer
# than this (prevents energy spikes from sensor restarts / integration updates)
MAX_INTEGRATION_GAP_SECONDS = 120  # 2 minutes

# Threshold for hardware reconciliation (kWh)
RECONCILIATION_THRESHOLD = 0.5

# Environmental impact constants
GRID_CO2_KG_PER_KWH = 0.128  # Swiss grid average
CO2_KG_PER_TREE_PER_YEAR = 22  # EPA estimate


class EnergyCalculator:
    """Calculates energy totals from power readings over time."""

    def __init__(self, config: Dict[str, Any], time_manager: TimeManager):
        """Initialize energy calculator."""
        self.config = config
        self._time_manager = time_manager

        # Accumulators for energy integration
        self._daily_accumulators: Dict[str, float] = {}
        self._monthly_accumulators: Dict[str, float] = {}
        self._yearly_accumulators: Dict[str, float] = {}
        self._lifetime_accumulators: Dict[str, float] = {}

        # Last update time for integration
        self._last_update: Optional[datetime] = None

        # Cost rates
        self._import_rate = config.get("electricity_import_rate", 0.3387)
        self._export_rate = config.get("electricity_export_rate", 0.075)

        # Hardware EV energy reconciliation
        self._hass: Optional[HomeAssistant] = None
        self._ev_daily_energy_sensor: Optional[str] = None
        self._lifetime_seeded: bool = False
        self._yearly_seeded: bool = False
        # Auto-detected from recorder statistics (first solar energy entry)
        self._install_year_decimal: Optional[float] = None

    def calculate_energy(self, power: PowerReadings) -> EnergyTotals:
        """Calculate energy totals by integrating power over time."""
        now = dt_util.now()
        today = now.date()  # Midnight-based reset — matches HA Energy Dashboard
        ev_day = self._time_manager.get_current_meter_day_sunrise_based()  # Sunrise-based for EV only
        month_key = f"{today.year}_{today.month}"
        year_key = f"{today.year}"

        # Calculate time delta
        if self._last_update is None:
            # First update - use config interval as safe default
            interval_hours = self.config.get("update_interval", 30) / 3600
        else:
            interval_seconds = (now - self._last_update).total_seconds()
            if interval_seconds < 0:
                # Clock went backwards (NTP correction, etc.) — skip
                self._last_update = now
                return self._build_current_totals(today, month_key, year_key)
            if interval_seconds > MAX_INTEGRATION_GAP_SECONDS:
                _LOGGER.warning(
                    "Energy integration gap: %.0fs > %ds limit — skipping cycle "
                    "to prevent accumulator spike (sensor restart/update?)",
                    interval_seconds, MAX_INTEGRATION_GAP_SECONDS,
                )
                self._last_update = now
                return self._build_current_totals(today, month_key, year_key)
            interval_hours = interval_seconds / 3600

        self._last_update = now

        # Check for day/month/year rollover and reset accumulators
        self._check_rollover(today, month_key, year_key)

        # Integrate power to energy
        energy = EnergyTotals()

        # Solar energy
        if power.solar_power >= MIN_POWER_THRESHOLD:
            solar_increment = (power.solar_power * interval_hours) / 1000  # kWh
            self._accumulate("solar", today, month_key, year_key, solar_increment)
        energy.daily_solar = self._get_daily("solar", today)
        energy.monthly_solar = self._get_monthly("solar", month_key)
        energy.yearly_solar = self._get_yearly("solar", year_key)

        # Home consumption
        if power.home_consumption_power >= MIN_POWER_THRESHOLD:
            home_increment = (power.home_consumption_power * interval_hours) / 1000
            self._accumulate("home", today, month_key, year_key, home_increment)
        energy.daily_home = self._get_daily("home", today)
        energy.monthly_home = self._get_monthly("home", month_key)
        energy.yearly_home = self._get_yearly("home", year_key)

        # EV charging (sunrise-based reset — night charging must stay in one bucket)
        # Category "ev_daily_sun" survives midnight rollover (excluded from cleanup)
        if power.ev_power >= MIN_POWER_THRESHOLD:
            ev_increment = (power.ev_power * interval_hours) / 1000
            self._accumulate("ev_daily_sun", ev_day, month_key, year_key, ev_increment)

        energy.daily_ev = self._get_daily("ev_daily_sun", ev_day)
        energy.yearly_ev = self._get_yearly("ev", year_key)

        # Grid import
        if power.grid_import_power >= MIN_POWER_THRESHOLD:
            import_increment = (power.grid_import_power * interval_hours) / 1000
            self._accumulate("grid_import", today, month_key, year_key, import_increment)
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)

        # Grid export
        if power.grid_export_power >= MIN_POWER_THRESHOLD:
            export_increment = (power.grid_export_power * interval_hours) / 1000
            self._accumulate("grid_export", today, month_key, year_key, export_increment)
        energy.daily_grid_export = self._get_daily("grid_export", today)
        energy.monthly_grid_export = self._get_monthly("grid_export", month_key)
        energy.yearly_grid_export = self._get_yearly("grid_export", year_key)

        # Battery charge
        if power.battery_charge_power >= MIN_POWER_THRESHOLD:
            charge_increment = (power.battery_charge_power * interval_hours) / 1000
            self._accumulate("battery_charge", today, month_key, year_key, charge_increment)
        energy.daily_battery_charge = self._get_daily("battery_charge", today)
        energy.monthly_battery_charge = self._get_monthly("battery_charge", month_key)
        energy.yearly_battery_charge = self._get_yearly("battery_charge", year_key)

        # Battery discharge
        if power.battery_discharge_power >= MIN_POWER_THRESHOLD:
            discharge_increment = (power.battery_discharge_power * interval_hours) / 1000
            self._accumulate("battery_discharge", today, month_key, year_key, discharge_increment)
        energy.daily_battery_discharge = self._get_daily("battery_discharge", today)
        energy.monthly_battery_discharge = self._get_monthly("battery_discharge", month_key)
        energy.yearly_battery_discharge = self._get_yearly("battery_discharge", year_key)

        # Sanity checks — warn and cap if values exceed physical limits
        battery_capacity = self.config.get("battery_capacity_kwh", 15)
        max_daily_battery = battery_capacity * 3  # 3 full cycles/day is generous limit
        inverter_kwp = self.config.get("system_size_kwp", 10)
        max_daily_solar = inverter_kwp * 16  # 16 peak sun hours is extreme max

        if energy.daily_battery_discharge > max_daily_battery:
            _LOGGER.warning(
                "Battery discharge %.1f kWh exceeds %.0f kWh daily limit (3x %.0f kWh capacity) — capping",
                energy.daily_battery_discharge, max_daily_battery, battery_capacity,
            )
            self._daily_accumulators[f"battery_discharge_{today}"] = max_daily_battery
            energy.daily_battery_discharge = max_daily_battery

        if energy.daily_battery_charge > max_daily_battery:
            _LOGGER.warning(
                "Battery charge %.1f kWh exceeds %.0f kWh daily limit — capping",
                energy.daily_battery_charge, max_daily_battery,
            )
            self._daily_accumulators[f"battery_charge_{today}"] = max_daily_battery
            energy.daily_battery_charge = max_daily_battery

        if energy.daily_solar > max_daily_solar:
            _LOGGER.warning(
                "Solar %.1f kWh exceeds %.0f kWh daily limit (%d kWp × 16h) — capping",
                energy.daily_solar, max_daily_solar, inverter_kwp,
            )
            self._daily_accumulators[f"solar_{today}"] = max_daily_solar
            energy.daily_solar = max_daily_solar

        return energy

    def _build_current_totals(self, today: date, month_key: str, year_key: str) -> EnergyTotals:
        """Return current accumulated totals without integrating new power.

        Used when a gap is detected to avoid energy spikes.
        """
        ev_day = self._time_manager.get_current_meter_day_sunrise_based()
        energy = EnergyTotals()
        energy.daily_solar = self._get_daily("solar", today)
        energy.monthly_solar = self._get_monthly("solar", month_key)
        energy.yearly_solar = self._get_yearly("solar", year_key)
        energy.daily_home = self._get_daily("home", today)
        energy.monthly_home = self._get_monthly("home", month_key)
        energy.yearly_home = self._get_yearly("home", year_key)
        energy.daily_ev = self._get_daily("ev_daily_sun", ev_day)
        energy.yearly_ev = self._get_yearly("ev", year_key)
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)
        energy.daily_grid_export = self._get_daily("grid_export", today)
        energy.monthly_grid_export = self._get_monthly("grid_export", month_key)
        energy.yearly_grid_export = self._get_yearly("grid_export", year_key)
        energy.daily_battery_charge = self._get_daily("battery_charge", today)
        energy.monthly_battery_charge = self._get_monthly("battery_charge", month_key)
        energy.yearly_battery_charge = self._get_yearly("battery_charge", year_key)
        energy.daily_battery_discharge = self._get_daily("battery_discharge", today)
        energy.monthly_battery_discharge = self._get_monthly("battery_discharge", month_key)
        energy.yearly_battery_discharge = self._get_yearly("battery_discharge", year_key)
        return energy

    def set_ev_daily_energy_sensor(self, hass: HomeAssistant, entity_id: Optional[str]) -> None:
        """Set hardware EV daily energy sensor for reconciliation."""
        self._hass = hass
        self._ev_daily_energy_sensor = entity_id
        if entity_id:
            _LOGGER.info("EV energy reconciliation enabled: %s", entity_id)

    async def async_detect_install_date(self, hass: HomeAssistant) -> None:
        """Detect system install date from recorder statistics.

        Queries the statistics table for the earliest solar energy entry.
        The statistics table is never purged, so this finds the true
        first day the system produced energy — more accurate than any
        manual configuration.
        """
        if self._install_year_decimal is not None:
            return

        try:
            from homeassistant.components.recorder import get_instance

            def _query_first_solar_stat():
                """Find earliest solar statistics entry."""
                import sqlite3
                db_url = hass.config.config_dir + "/home-assistant_v2.db"
                conn = sqlite3.connect(db_url)
                cur = conn.cursor()
                cur.execute("""
                    SELECT MIN(s.start_ts)
                    FROM statistics s
                    JOIN statistics_meta sm ON s.metadata_id = sm.id
                    WHERE sm.statistic_id LIKE '%solar%'
                       OR sm.statistic_id LIKE '%inverter%ertrag%'
                       OR sm.statistic_id LIKE '%gesamtenergieertrag%'
                       OR sm.statistic_id LIKE '%pv%energy%'
                """)
                row = cur.fetchone()
                conn.close()
                return row[0] if row and row[0] else None

            first_ts = await get_instance(hass).async_add_executor_job(
                _query_first_solar_stat
            )

            if first_ts:
                first_dt = datetime.fromtimestamp(first_ts)
                self._install_year_decimal = round(
                    first_dt.year + first_dt.month / 12, 2
                )
                _LOGGER.info(
                    "System install date auto-detected from statistics: %s (%.2f)",
                    first_dt.strftime("%Y-%m-%d"),
                    self._install_year_decimal,
                )
            else:
                _LOGGER.debug("No solar statistics found — using current year as fallback")

        except Exception as e:
            _LOGGER.debug("Could not detect install date from statistics: %s", e)

    def seed_lifetime_from_hardware(self, hass: HomeAssistant, ed_config) -> None:
        """Seed lifetime accumulators from hardware energy counters.

        Reads total energy from the HA Energy Dashboard sensors (which
        represent all-time hardware counters) and uses them as the baseline
        for lifetime tracking. Only runs once — skipped if lifetime
        accumulators already have data.
        """
        if self._lifetime_seeded:
            return
        if not ed_config:
            return

        # Read hardware total to compare
        def _read(entity_id):
            if not entity_id:
                return 0.0
            state = hass.states.get(entity_id)
            if state and state.state not in ("unknown", "unavailable", None):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
            return 0.0

        # Read all hardware counters first
        solar = _read(ed_config.solar_energy)
        grid_import = _read(ed_config.grid_import_energy)
        grid_export = _read(ed_config.grid_export_energy)
        batt_charge = _read(ed_config.battery_charge_energy)
        batt_discharge = _read(ed_config.battery_discharge_energy)

        _LOGGER.debug(
            "Lifetime seed check: hw solar=%.0f import=%.0f export=%.0f "
            "batt_c=%.0f batt_d=%.0f",
            solar, grid_import, grid_export, batt_charge, batt_discharge,
        )

        # ALL key sensors must be available before seeding.
        # Include battery — they can take 30-60s longer to load (#110).
        if solar < 100 or grid_import < 10 or grid_export < 10:
            _LOGGER.debug(
                "Lifetime seed waiting: solar=%.0f import=%.0f export=%.0f "
                "(all must be > threshold)",
                solar, grid_import, grid_export,
            )
            return
        if (batt_charge < 1 or batt_discharge < 1) and (batt_charge + batt_discharge) < 10:
            _LOGGER.debug(
                "Lifetime seed waiting for battery: charge=%.0f discharge=%.0f",
                batt_charge, batt_discharge,
            )
            return

        # Check if ALL sensors are properly seeded (not just solar).
        # Re-seed any sensor that is <50% of the hardware counter —
        # this fixes the race condition where solar loaded first but
        # grid/battery were unavailable during initial seeding (#110).
        current = self._lifetime_accumulators
        needs_seed = False
        checks = [
            ("lifetime_solar", solar),
            ("lifetime_grid_import", grid_import),
            ("lifetime_grid_export", grid_export),
            ("lifetime_battery_charge", batt_charge),
            ("lifetime_battery_discharge", batt_discharge),
        ]
        for key, hw_value in checks:
            stored = current.get(key, 0)
            if hw_value > 100 and stored < hw_value * 0.5:
                _LOGGER.info(
                    "Lifetime re-seed needed: %s stored=%.0f hw=%.0f (%.0f%%)",
                    key, stored, hw_value, (stored / hw_value * 100) if hw_value > 0 else 0,
                )
                needs_seed = True
                break

        if not needs_seed and current.get("lifetime_solar", 0) > solar * 0.9:
            self._lifetime_seeded = True
            return

        # Seed (or re-seed) all lifetime accumulators from hardware
        self._lifetime_accumulators["lifetime_solar"] = solar
        self._lifetime_accumulators["lifetime_grid_import"] = grid_import
        self._lifetime_accumulators["lifetime_grid_export"] = grid_export
        self._lifetime_accumulators["lifetime_battery_charge"] = batt_charge
        self._lifetime_accumulators["lifetime_battery_discharge"] = batt_discharge
        home = max(0, solar + grid_import + batt_discharge - grid_export - batt_charge)
        self._lifetime_accumulators["lifetime_home"] = home

        # Seed EV from hardware counter (KEBA total energy etc.)
        ev_total = 0.0
        for dev in ed_config.device_consumption:
            energy_sensor = dev.get("stat_consumption", "")
            if any(p in energy_sensor.lower() for p in ["keba", "ev", "charger", "wallbox", "easee"]):
                ev_total = _read(energy_sensor)
                break
        if ev_total > 0:
            self._lifetime_accumulators["lifetime_ev"] = ev_total

        self._lifetime_seeded = True
        _LOGGER.info(
            "Lifetime seeded from hardware: solar=%.0f import=%.0f export=%.0f "
            "batt_charge=%.0f batt_discharge=%.0f home=%.0f ev=%.0f kWh",
            solar, grid_import, grid_export, batt_charge, batt_discharge, home, ev_total,
        )

    async def seed_yearly_from_statistics(self, hass: HomeAssistant, ed_config) -> None:
        """Seed yearly accumulators from HA recorder statistics.

        On first install mid-year, yearly sensors would start at zero.
        This reads cumulative energy stats from the HA recorder for
        Jan 1 to now and seeds the yearly accumulators. Runs once.
        """
        if self._yearly_seeded:
            return
        if not ed_config:
            return

        year_key = str(dt_util.now().year)

        # If yearly accumulators already have significant data, skip
        current_total = sum(
            v for k, v in self._yearly_accumulators.items()
            if k.endswith(year_key)
        )
        if current_total > 10:
            self._yearly_seeded = True
            _LOGGER.debug("Yearly accumulators already have %.1f kWh, skipping seed", current_total)
            return

        try:
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )
        except ImportError:
            _LOGGER.debug("Recorder not available for yearly seeding")
            return

        # Build entity → category mapping from Energy Dashboard config
        entity_map = {}
        if ed_config.solar_energy:
            entity_map[ed_config.solar_energy] = "solar"
        if ed_config.grid_import_energy:
            entity_map[ed_config.grid_import_energy] = "grid_import"
        if ed_config.grid_export_energy:
            entity_map[ed_config.grid_export_energy] = "grid_export"
        if ed_config.battery_charge_energy:
            entity_map[ed_config.battery_charge_energy] = "battery_charge"
        if ed_config.battery_discharge_energy:
            entity_map[ed_config.battery_discharge_energy] = "battery_discharge"

        if not entity_map:
            _LOGGER.debug("No energy entities in ED config for yearly seeding")
            return

        # Query statistics from Jan 1 of current year
        now = dt_util.now()
        start_time = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        entity_ids = list(entity_map.keys())

        try:
            stats = await statistics_during_period(
                hass, start_time, None, entity_ids, "hour", None, {"sum"}
            )
        except Exception as e:
            _LOGGER.warning("Failed to query recorder statistics for yearly seeding: %s", e)
            return

        if not stats:
            _LOGGER.debug("No recorder statistics available for yearly seeding")
            return

        # Extract yearly energy: difference between latest and first sum
        seeded = {}
        for entity_id, category in entity_map.items():
            entity_stats = stats.get(entity_id, [])
            if len(entity_stats) < 2:
                seeded[category] = 0.0
                continue
            first_sum = entity_stats[0].get("sum", 0.0) or 0.0
            last_sum = entity_stats[-1].get("sum", 0.0) or 0.0
            yearly_energy = max(0, last_sum - first_sum)
            seeded[category] = yearly_energy
            self._yearly_accumulators[f"{category}_{year_key}"] = yearly_energy

        # Derive home consumption from energy balance
        solar = seeded.get("solar", 0)
        grid_import = seeded.get("grid_import", 0)
        grid_export = seeded.get("grid_export", 0)
        batt_charge = seeded.get("battery_charge", 0)
        batt_discharge = seeded.get("battery_discharge", 0)
        home = max(0, solar + grid_import + batt_discharge - grid_export - batt_charge)
        self._yearly_accumulators[f"home_{year_key}"] = home
        seeded["home"] = home

        # Seed EV from device consumption (same pattern as lifetime)
        ev_total = 0.0
        if hasattr(ed_config, "device_consumption") and ed_config.device_consumption:
            for dev in ed_config.device_consumption:
                energy_sensor = dev.get("stat_consumption", "")
                if any(p in energy_sensor.lower() for p in ["keba", "ev", "charger", "wallbox", "easee"]):
                    ev_stats = stats.get(energy_sensor, [])
                    if not ev_stats:
                        # Try querying separately
                        try:
                            ev_result = await statistics_during_period(
                                hass, start_time, None, [energy_sensor], "hour", None, {"sum"}
                            )
                            ev_stats = ev_result.get(energy_sensor, [])
                        except Exception:
                            pass
                    if len(ev_stats) >= 2:
                        ev_total = max(0, (ev_stats[-1].get("sum", 0) or 0) - (ev_stats[0].get("sum", 0) or 0))
                    break
        if ev_total > 0:
            self._yearly_accumulators[f"ev_{year_key}"] = ev_total
            seeded["ev"] = ev_total

        self._yearly_seeded = True
        _LOGGER.info(
            "Yearly accumulators seeded from recorder: solar=%.1f import=%.1f export=%.1f "
            "batt_charge=%.1f batt_discharge=%.1f home=%.1f ev=%.1f kWh",
            seeded.get("solar", 0), seeded.get("grid_import", 0), seeded.get("grid_export", 0),
            seeded.get("battery_charge", 0), seeded.get("battery_discharge", 0),
            home, ev_total,
        )

    def _reconcile_ev_energy(self, today: date, month_key: str) -> None:
        """Cross-check integrated EV energy against hardware counter.

        If the hardware counter (e.g. KEBA daily energy) reports more energy
        than our power integration, adopt the hardware value. This catches
        energy missed due to restarts, missed cycles, or external charging.
        """
        if not self._hass or not self._ev_daily_energy_sensor:
            return

        state = self._hass.states.get(self._ev_daily_energy_sensor)
        if not state or state.state in ("unknown", "unavailable", None):
            return

        try:
            hardware_kwh = float(state.state)
        except (ValueError, TypeError):
            return

        calculated_kwh = self._get_daily("ev_daily_sun", today)

        if hardware_kwh > calculated_kwh + RECONCILIATION_THRESHOLD:
            _LOGGER.info(
                "EV energy reconciliation: hardware=%.2f kWh > calculated=%.2f kWh, adopting hardware value",
                hardware_kwh, calculated_kwh,
            )
            daily_key = f"ev_daily_sun_{today}"
            self._daily_accumulators[daily_key] = hardware_kwh

            # Also adjust monthly accumulator by the same delta
            delta = hardware_kwh - calculated_kwh
            monthly_key_full = f"ev_{month_key}"
            self._monthly_accumulators[monthly_key_full] = (
                self._monthly_accumulators.get(monthly_key_full, 0.0) + delta
            )

    def calculate_costs(self, energy: EnergyTotals) -> CostData:
        """Calculate costs and savings from energy totals."""
        costs = CostData()

        # Daily calculations
        costs.daily_costs = round(energy.daily_grid_import * self._import_rate, 2)
        costs.daily_export_revenue = round(energy.daily_grid_export * self._export_rate, 2)
        costs.daily_net_cost = round(costs.daily_costs - costs.daily_export_revenue, 2)

        # Savings = what we would have paid if all consumption came from grid
        total_consumption = energy.daily_home + energy.daily_ev
        costs.daily_savings = round(
            (total_consumption - energy.daily_grid_import) * self._import_rate, 2
        )
        costs.daily_savings = max(0, costs.daily_savings)

        # Battery savings = value of battery discharge at import rate
        costs.daily_battery_savings = round(
            energy.daily_battery_discharge * self._import_rate, 2
        )

        # Monthly calculations
        costs.monthly_costs = round(energy.monthly_grid_import * self._import_rate, 2)
        costs.monthly_export_revenue = round(energy.monthly_grid_export * self._export_rate, 2)
        costs.monthly_net_cost = round(costs.monthly_costs - costs.monthly_export_revenue, 2)

        monthly_consumption = energy.monthly_home
        costs.monthly_savings = round(
            (monthly_consumption - energy.monthly_grid_import) * self._import_rate, 2
        )
        costs.monthly_savings = max(0, costs.monthly_savings)

        # Yearly calculations
        costs.yearly_costs = round(energy.yearly_grid_import * self._import_rate, 2)
        costs.yearly_export_revenue = round(energy.yearly_grid_export * self._export_rate, 2)
        costs.yearly_net_cost = round(costs.yearly_costs - costs.yearly_export_revenue, 2)
        yearly_consumption = energy.yearly_home + energy.yearly_ev
        costs.yearly_savings = round(
            max(0, (yearly_consumption - energy.yearly_grid_import) * self._import_rate), 2
        )
        costs.yearly_battery_savings = round(
            energy.yearly_battery_discharge * self._import_rate, 2
        )

        # Environmental impact (CO2 avoided by self-consuming solar)
        daily_self_consumed = max(0, energy.daily_solar - energy.daily_grid_export)
        yearly_self_consumed = max(0, energy.yearly_solar - energy.yearly_grid_export)
        lifetime_solar = self._get_lifetime("solar")
        lifetime_export = self._get_lifetime("grid_export")
        lifetime_self_consumed = max(0, lifetime_solar - lifetime_export)

        costs.daily_co2_avoided_kg = round(daily_self_consumed * GRID_CO2_KG_PER_KWH, 2)
        costs.yearly_co2_avoided_kg = round(yearly_self_consumed * GRID_CO2_KG_PER_KWH, 1)
        costs.yearly_trees_equivalent = round(
            costs.yearly_co2_avoided_kg / CO2_KG_PER_TREE_PER_YEAR, 1
        )
        costs.lifetime_co2_avoided_kg = round(lifetime_self_consumed * GRID_CO2_KG_PER_KWH, 1)
        costs.lifetime_trees_equivalent = round(
            costs.lifetime_co2_avoided_kg / CO2_KG_PER_TREE_PER_YEAR, 1
        )

        # ROI calculation
        lifetime_grid_import = self._get_lifetime("grid_import")
        lifetime_grid_export = self._get_lifetime("grid_export")
        lifetime_batt_discharge = self._get_lifetime("battery_discharge")

        costs.lifetime_grid_cost = round(lifetime_grid_import * self._import_rate, 2)
        solar_savings = round(lifetime_self_consumed * self._import_rate, 2)
        export_revenue = round(lifetime_grid_export * self._export_rate, 2)
        battery_savings = round(lifetime_batt_discharge * self._import_rate, 2)
        costs.lifetime_total_savings = round(solar_savings + export_revenue, 2)

        system_cost = self.config.get("system_investment_cost", 0)
        if system_cost > 0:
            costs.roi_percentage = round(
                (costs.lifetime_total_savings / system_cost) * 100, 1
            )
            # Calculate annual savings from lifetime data + system age
            # Auto-detected from recorder statistics (first solar energy entry)
            install_year_decimal = self._install_year_decimal or dt_util.now().year
            now_decimal = dt_util.now().year + (dt_util.now().month / 12)
            age_years = max(0.5, now_decimal - install_year_decimal)
            if costs.lifetime_total_savings > 100:
                costs.roi_annual_savings = round(costs.lifetime_total_savings / age_years, 0)
                remaining = system_cost - costs.lifetime_total_savings
                if remaining > 0 and costs.roi_annual_savings > 0:
                    costs.roi_payback_years = round(age_years + (remaining / costs.roi_annual_savings), 1)
                elif remaining <= 0:
                    costs.roi_payback_years = round(age_years, 1)  # Already paid off

        return costs

    def calculate_performance(
        self, power: PowerReadings, energy: EnergyTotals
    ) -> PerformanceMetrics:
        """Calculate performance metrics."""
        metrics = PerformanceMetrics()

        # Self consumption rate = (solar - export) / solar
        if energy.daily_solar > 0:
            solar_used = energy.daily_solar - energy.daily_grid_export
            metrics.self_consumption_rate = round(
                (solar_used / energy.daily_solar) * 100, 1
            )
            metrics.self_consumption_rate = max(0, min(100, metrics.self_consumption_rate))

        # Autarky rate = (consumption - import) / consumption
        total_consumption = energy.daily_home + energy.daily_ev
        if total_consumption > 0:
            own_supply = total_consumption - energy.daily_grid_import
            metrics.autarky_rate = round((own_supply / total_consumption) * 100, 1)
            metrics.autarky_rate = max(0, min(100, metrics.autarky_rate))

        # Simple efficiency estimates
        metrics.solar_efficiency = 85.0 if power.solar_power > 0 else 0.0
        metrics.battery_efficiency = 95.0 if abs(power.battery_power) > 50 else 100.0

        return metrics

    def _accumulate(
        self, category: str, today: date, month_key: str, year_key: str, increment: float
    ) -> None:
        """Accumulate energy increment for a category."""
        daily_key = f"{category}_{today}"
        monthly_key = f"{category}_{month_key}"
        yearly_key = f"{category}_{year_key}"

        if daily_key not in self._daily_accumulators:
            self._daily_accumulators[daily_key] = 0.0
        if monthly_key not in self._monthly_accumulators:
            self._monthly_accumulators[monthly_key] = 0.0
        if yearly_key not in self._yearly_accumulators:
            self._yearly_accumulators[yearly_key] = 0.0

        self._daily_accumulators[daily_key] += increment
        self._monthly_accumulators[monthly_key] += increment
        self._yearly_accumulators[yearly_key] += increment

        # Lifetime (never resets)
        lifetime_key = f"lifetime_{category}"
        if lifetime_key not in self._lifetime_accumulators:
            self._lifetime_accumulators[lifetime_key] = 0.0
        self._lifetime_accumulators[lifetime_key] += increment

    def _get_daily(self, category: str, today: date) -> float:
        """Get daily accumulated energy."""
        key = f"{category}_{today}"
        return round(self._daily_accumulators.get(key, 0.0), 2)

    def _get_monthly(self, category: str, month_key: str) -> float:
        """Get monthly accumulated energy."""
        key = f"{category}_{month_key}"
        return round(self._monthly_accumulators.get(key, 0.0), 2)

    def _get_yearly(self, category: str, year_key: str) -> float:
        """Get yearly accumulated energy."""
        key = f"{category}_{year_key}"
        return round(self._yearly_accumulators.get(key, 0.0), 2)

    def _get_lifetime(self, category: str) -> float:
        """Get lifetime accumulated energy."""
        key = f"lifetime_{category}"
        return round(self._lifetime_accumulators.get(key, 0.0), 2)

    def _check_rollover(self, today: date, month_key: str, year_key: str = None) -> None:
        """Check for day/month rollover and cleanup old accumulators.

        EV keys (ev_daily_sun_*) are excluded — they use sunrise-based dates
        and get cleaned up separately (older than yesterday).
        """
        yesterday = str(today - timedelta(days=1))

        # Remove daily accumulators from previous days
        # Skip ev_daily_sun keys (sunrise-based, cleaned separately below)
        keys_to_remove = [
            k for k in self._daily_accumulators.keys()
            if not k.endswith(str(today)) and not k.startswith("ev_daily_sun")
        ]
        # Clean old EV keys (older than yesterday — keeps today + yesterday)
        keys_to_remove += [
            k for k in self._daily_accumulators.keys()
            if k.startswith("ev_daily_sun")
            and not k.endswith(str(today))
            and not k.endswith(yesterday)
        ]
        for key in keys_to_remove:
            del self._daily_accumulators[key]

        # Remove monthly accumulators from previous months
        keys_to_remove = [
            k for k in self._monthly_accumulators.keys()
            if not k.endswith(month_key)
        ]
        for key in keys_to_remove:
            del self._monthly_accumulators[key]

        # Remove yearly accumulators from previous years
        if year_key:
            keys_to_remove = [
                k for k in self._yearly_accumulators.keys()
                if not k.endswith(year_key)
            ]
            for key in keys_to_remove:
                del self._yearly_accumulators[key]
        # Note: _lifetime_accumulators never get cleaned up (by design)

    def get_state(self) -> Dict[str, Any]:
        """Get calculator state for persistence."""
        return {
            "daily_accumulators": self._daily_accumulators.copy(),
            "monthly_accumulators": self._monthly_accumulators.copy(),
            "yearly_accumulators": self._yearly_accumulators.copy(),
            "lifetime_accumulators": self._lifetime_accumulators.copy(),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "yearly_seeded": self._yearly_seeded,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore calculator state from persistence."""
        if state:
            self._daily_accumulators = state.get("daily_accumulators", {})
            self._monthly_accumulators = state.get("monthly_accumulators", {})
            self._yearly_accumulators = state.get("yearly_accumulators", {})
            self._lifetime_accumulators = state.get("lifetime_accumulators", {})
            self._yearly_seeded = state.get("yearly_seeded", False)
            last_update = state.get("last_update")
            if last_update:
                self._last_update = datetime.fromisoformat(last_update)
