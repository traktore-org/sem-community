"""Energy calculation module for SEM coordinator."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .types import (
    PowerReadings, EnergyTotals, CostData, PerformanceMetrics,
    PowerFlows, EnergyFlows,
)
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

        # Cost accumulators (incremental, rate-weighted) — fixes dynamic tariff mid-day recalculation
        self._daily_cost_accumulators: Dict[str, float] = {}
        self._monthly_cost_accumulators: Dict[str, float] = {}
        self._yearly_cost_accumulators: Dict[str, float] = {}

        # Last update time for integration
        self._last_update: Optional[datetime] = None

        # Cost rates
        self._import_rate = config.get("electricity_import_rate", 0.3387)
        self._export_rate = config.get("electricity_export_rate", 0.075)

        # Rate history for 7-day averaging (dynamic tariffs)
        self._rate_history: deque = deque(maxlen=30)

        # Accumulated savings/costs (running totals for accurate ROI)
        self._accumulated_savings: float = 0.0
        self._accumulated_battery_savings: float = 0.0
        self._accumulated_cost: float = 0.0
        self._accumulated_export_revenue: float = 0.0
        self._accumulated_grid_import_kwh: float = 0.0
        self._accumulated_self_consumed_kwh: float = 0.0
        self._accumulated_export_kwh: float = 0.0

        # Hardware EV energy reconciliation
        self._hass: Optional[HomeAssistant] = None
        self._ev_daily_energy_sensor: Optional[str] = None
        self._lifetime_seeded: bool = False
        self._yearly_seeded: bool = False
        self._yearly_seed_attempts: int = 0
        # Auto-detected from recorder statistics (first solar energy entry)
        self._install_year_decimal: Optional[float] = None

    def _ev_reset_day(self, now: datetime):
        """Return today's EV-day bucket key, deadline-based (#279 follow-up).

        Mirrors the per-charger reset boundary so the GLOBAL daily_ev_energy
        sensor doesn't wipe at sunrise (~05:30 in summer) and instead rolls
        at the user's actual ``Charge by`` deadline (default 07:00). For
        multi-charger setups, uses the LATEST deadline across configured
        chargers — the global counter survives until ALL chargers have
        rolled over, otherwise a charger with a later deadline would see
        a phantom mid-night reset.

        Falls back to the legacy sunrise-based boundary only when no
        chargers + no global default are configured (transition / pre-setup).
        """
        from ..consts.core import DEFAULT_EV_TARGET_TIME

        # Gather all charger target_times + the global default
        ev_chargers = self.config.get("ev_chargers") or []
        deadlines = []
        for c in ev_chargers:
            tt = c.get("ev_target_time") or self.config.get("ev_target_time")
            if tt:
                deadlines.append(str(tt))
        if not deadlines:
            global_tt = self.config.get("ev_target_time") or DEFAULT_EV_TARGET_TIME
            if global_tt:
                deadlines.append(str(global_tt))

        if not deadlines:
            # Pure fallback — pre-#279 behaviour.
            return self._time_manager.get_current_meter_day_sunrise_based()

        # Pick the LATEST deadline so the global counter doesn't roll over
        # before the slowest-deadline charger has finished its bucket.
        latest = max(deadlines)
        return self._time_manager.get_current_meter_day_offset_based(latest)

    def calculate_energy(
        self, power: PowerReadings,
        power_flows: "Optional[PowerFlows]" = None,
    ) -> EnergyTotals:
        """Calculate energy totals by integrating power over time."""
        now = dt_util.now()
        today = now.date()  # Midnight-based reset — matches HA Energy Dashboard
        # EV: deadline-based reset (#279 follow-up). The per-charger counter
        # already rolls at each charger's Charge-by time; the GLOBAL
        # daily_ev_energy stayed on sunrise-based reset until now, so users
        # saw it wipe ~05:30 in summer even though the deadline was 07:00.
        # User-reported on 2026-05-29 06:28 local: counter showed 0 well
        # before the 07:00 deadline. Fix: use the same deadline-based
        # boundary the per-charger counters use.
        ev_day = self._ev_reset_day(now)
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
        # FLEET-READ: ``ev_daily_sun`` is the fleet daily total — matches
        # ``sensor.sem_daily_ev_energy``. Per-charger daily energy lives
        # on ``charger_<id>_daily_energy`` populated separately.
        if power.ev_power >= MIN_POWER_THRESHOLD:
            ev_increment = (power.ev_power * interval_hours) / 1000  # FLEET-READ: same fleet integration as the gate above.
            self._accumulate("ev_daily_sun", ev_day, month_key, year_key, ev_increment)

        energy.daily_ev = self._get_daily("ev_daily_sun", ev_day)
        energy.yearly_ev = self._get_yearly("ev", year_key)

        # Grid import
        if power.grid_import_power >= MIN_POWER_THRESHOLD:
            import_increment = (power.grid_import_power * interval_hours) / 1000
            self._accumulate("grid_import", today, month_key, year_key, import_increment)
            self._accumulate_cost("cost_import", today, month_key, year_key, import_increment * self._import_rate)
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)

        # Grid export
        if power.grid_export_power >= MIN_POWER_THRESHOLD:
            export_increment = (power.grid_export_power * interval_hours) / 1000
            self._accumulate("grid_export", today, month_key, year_key, export_increment)
            self._accumulate_cost("cost_export", today, month_key, year_key, export_increment * self._export_rate)
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
            self._accumulate_cost("cost_batt_savings", today, month_key, year_key, discharge_increment * self._import_rate)
        energy.daily_battery_discharge = self._get_daily("battery_discharge", today)
        energy.monthly_battery_discharge = self._get_monthly("battery_discharge", month_key)
        energy.yearly_battery_discharge = self._get_yearly("battery_discharge", year_key)

        # Solar self-consumption savings (incremental, rate-weighted for dynamic tariff accuracy)
        # Only tracks savings from solar — battery discharge savings are in cost_batt_savings.
        #
        # v1.7.0: use flow-attributed solar_to_home + solar_to_ev when
        # ``power_flows`` is passed (computed by ``calculate_power_flows``).
        # The legacy subtraction heuristic
        # ``(home + ev) - import - discharge`` undercounts savings whenever
        # the grid is simultaneously charging the battery (cheap-tariff
        # daytime, mixed solar+grid moments) because ``import_incr`` is the
        # raw grid pull — including the grid → battery slice that DIDN'T
        # displace any home consumption. Same bug class as the autarky
        # mis-attribution; see ``calculate_performance`` for the symmetric
        # fix.
        if power_flows is not None:
            solar_self_consumed = (
                ((power_flows.solar_to_home + power_flows.solar_to_ev)
                 * interval_hours) / 1000
            )
        else:
            home_incr = (power.home_consumption_power * interval_hours) / 1000 if power.home_consumption_power >= MIN_POWER_THRESHOLD else 0.0
            # FLEET-READ: legacy fallback path. ``power_flows`` is the
            # preferred input in the v1.7.0+ coordinator pipeline; this
            # branch only fires for the two-arg test fixtures that
            # pre-date the per-cycle ``calculate_power_flows`` call.
            ev_incr = (power.ev_power * interval_hours) / 1000 if power.ev_power >= MIN_POWER_THRESHOLD else 0.0
            import_incr = (power.grid_import_power * interval_hours) / 1000 if power.grid_import_power >= MIN_POWER_THRESHOLD else 0.0
            discharge_incr = (power.battery_discharge_power * interval_hours) / 1000 if power.battery_discharge_power >= MIN_POWER_THRESHOLD else 0.0
            # Solar self-consumed = total consumption minus what came from grid or battery discharge
            solar_self_consumed = max(0.0, (home_incr + ev_incr) - import_incr - discharge_incr)
        if solar_self_consumed > 0.0:
            self._accumulate_cost("cost_savings", today, month_key, year_key, solar_self_consumed * self._import_rate)

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
        ev_day = self._ev_reset_day(dt_util.now())
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

        # Stop retrying after 3 attempts — recorder may not be compatible
        # (e.g. Python 3.14 blocking call detection in HA core)
        self._yearly_seed_attempts += 1
        if self._yearly_seed_attempts > 3:
            self._yearly_seeded = True
            _LOGGER.info(
                "Yearly seeding skipped after %d failed attempts — "
                "yearly accumulators will build up from daily tracking",
                self._yearly_seed_attempts - 1,
            )
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
            first_sum = entity_stats[0].get("sum") if entity_stats[0].get("sum") is not None else 0.0
            last_sum = entity_stats[-1].get("sum") if entity_stats[-1].get("sum") is not None else 0.0
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
                        last_ev = ev_stats[-1].get("sum") if ev_stats[-1].get("sum") is not None else 0
                        first_ev = ev_stats[0].get("sum") if ev_stats[0].get("sum") is not None else 0
                        ev_total = max(0, last_ev - first_ev)
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
        """Calculate costs and savings from energy totals.

        Uses incremental cost accumulators so dynamic tariff rate changes mid-day
        do not retroactively recalculate the entire day's cost at the new rate.
        """
        costs = CostData()

        now = dt_util.now()
        today = now.date()
        month_key = f"{today.year}_{today.month}"
        year_key = str(today.year)

        # Daily calculations — from incremental cost accumulators
        costs.daily_costs = self._get_daily_cost("cost_import", today)
        costs.daily_export_revenue = self._get_daily_cost("cost_export", today)
        costs.daily_net_cost = round(costs.daily_costs - costs.daily_export_revenue, 2)
        costs.daily_savings = max(0, self._get_daily_cost("cost_savings", today))
        costs.daily_battery_savings = max(0, self._get_daily_cost("cost_batt_savings", today))
        # #351 M2 — headline total spans both. Pre-fix users comparing
        # daily_savings to import costs saw battery_to_ev portion
        # missing.
        costs.daily_total_savings = round(
            costs.daily_savings + costs.daily_battery_savings, 2,
        )

        # Monthly calculations
        costs.monthly_costs = self._get_monthly_cost("cost_import", month_key)
        costs.monthly_export_revenue = self._get_monthly_cost("cost_export", month_key)
        costs.monthly_net_cost = round(costs.monthly_costs - costs.monthly_export_revenue, 2)
        costs.monthly_savings = max(0, self._get_monthly_cost("cost_savings", month_key))
        costs.monthly_battery_savings = max(0, self._get_monthly_cost("cost_batt_savings", month_key))
        costs.monthly_total_savings = round(
            costs.monthly_savings + costs.monthly_battery_savings, 2,
        )

        # Yearly calculations
        costs.yearly_costs = self._get_yearly_cost("cost_import", year_key)
        costs.yearly_export_revenue = self._get_yearly_cost("cost_export", year_key)
        costs.yearly_net_cost = round(costs.yearly_costs - costs.yearly_export_revenue, 2)
        costs.yearly_savings = max(0, self._get_yearly_cost("cost_savings", year_key))
        costs.yearly_battery_savings = max(0, self._get_yearly_cost("cost_batt_savings", year_key))
        costs.yearly_total_savings = round(
            costs.yearly_savings + costs.yearly_battery_savings, 2,
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

        # ROI calculation — hybrid: accumulated (accurate) + estimated past (avg rate)
        lifetime_grid_import = self._get_lifetime("grid_import")
        lifetime_grid_export = self._get_lifetime("grid_export")

        # Use 7-day avg rate for the estimated (pre-accumulation) portion
        avg_import = self._get_avg_import_rate()
        avg_export = self._get_avg_export_rate()

        # Pre-SEM portion: lifetime minus what we've already accurately accumulated.
        # Battery discharge is deliberately NOT estimated here (#499): the
        # solar-charged share of pre-SEM discharge is already inside
        # ``lifetime_self_consumed`` (solar − export includes solar that was
        # routed through the battery), and the grid-charged share's net
        # arbitrage benefit can't be reconstructed from lifetime counters.
        pre_sem_self_consumed = max(0, lifetime_self_consumed - self._accumulated_self_consumed_kwh)
        pre_sem_export = max(0, lifetime_grid_export - self._accumulated_export_kwh)
        pre_sem_grid_import = max(0, lifetime_grid_import - self._accumulated_grid_import_kwh)

        # Estimated past savings (using smoothed avg rate)
        estimated_past_savings = pre_sem_self_consumed * avg_import
        estimated_past_revenue = pre_sem_export * avg_export

        # Total: accumulated real savings + estimated past. Battery savings
        # are included from the accumulated (flow-attributed) side only —
        # ``cost_savings`` counts direct solar→home/EV, so battery discharge
        # savings are additional, not a double count (#499).
        costs.lifetime_grid_cost = round(
            self._accumulated_cost + pre_sem_grid_import * avg_import, 2
        )
        costs.lifetime_total_savings = round(
            self._accumulated_savings + self._accumulated_battery_savings
            + self._accumulated_export_revenue
            + estimated_past_savings + estimated_past_revenue, 2
        )

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
        self, power: PowerReadings, energy: EnergyTotals,
        energy_flows: "Optional[EnergyFlows]" = None,
    ) -> PerformanceMetrics:
        """Calculate performance metrics.

        ``energy_flows`` (v1.7.0+ — optional for back-compat with the
        legacy two-arg call shape) provides flow-attributed daily
        kWh totals. When supplied, the autarky calculation uses
        ``grid_to_home + grid_to_ev`` instead of the raw
        ``daily_grid_import``. The legacy formula treated every kWh
        imported from the grid as a penalty against autarky — but a
        kWh that flowed grid → battery (e.g. overnight cheap-tariff
        charging) doesn't reduce the home's own-supply share. Live
        evidence captured on HA-PROD 2026-06-01: 9.38 kWh grid_import
        with 2.9 kWh going to the battery left autarky pinned at 0 %
        while self_consumption was 98.1 % — clearly the formula was
        mis-attributing the grid → battery slice.
        """
        metrics = PerformanceMetrics()

        # Self consumption rate = (solar - export) / solar — direction-of-
        # flow-agnostic; whatever solar didn't go to the grid was
        # consumed locally (by home, battery, or EV). No flow attribution
        # needed.
        if energy.daily_solar > 0:
            solar_used = energy.daily_solar - energy.daily_grid_export
            metrics.self_consumption_rate = round(
                (solar_used / energy.daily_solar) * 100, 1
            )
            metrics.self_consumption_rate = max(0, min(100, metrics.self_consumption_rate))

        # Autarky rate — share of consumption supplied from "own"
        # sources (solar + battery) vs grid.
        #
        # When ``energy_flows`` is provided we use ONLY flow-attributed
        # values — all calendar-midnight aligned, so no temporal-
        # mismatch bug. Earlier fix used ``daily_home + daily_ev`` for
        # the denominator but ``daily_ev`` resets at SUNRISE (per #279
        # EV-target arc) while ``flow_grid_to_ev`` resets at calendar
        # midnight; pre-sunrise EV charging then appeared in the grid
        # penalty but not in the consumption total, pinning autarky
        # at single digits. HA-PROD 2026-06-01 saw exactly this:
        # ``flow_grid_to_ev = 6.2 kWh`` (pre-sunrise) while
        # ``daily_ev = 0`` (sunrise window started later) → autarky
        # 9 % instead of a realistic ~42 %.
        #
        # New definition (all from ``energy_flows``, calendar-aligned):
        # * own_supply  = solar_to_home + solar_to_ev
        #               + battery_to_home + battery_to_ev
        # * grid_supply = grid_to_home + grid_to_ev
        # * total      = own_supply + grid_supply
        # * autarky    = own_supply / total × 100
        #
        # Treating ``battery_to_X`` as own supply is an approximation
        # — strictly some battery discharge originated from cheap-
        # tariff grid charge, not solar. SEM doesn't track battery-
        # energy provenance, so the "all-battery-is-own" rule
        # matches user intuition ("my battery is mine").
        #
        # Legacy two-arg callers (no energy_flows) keep the v1.6.x
        # behaviour. They share the bug class, but their existing
        # tests pin the old numbers so we don't quietly retcon them.
        if energy_flows is not None:
            own_supply = (
                getattr(energy_flows, "solar_to_home", 0.0)
                + getattr(energy_flows, "solar_to_ev", 0.0)
                + getattr(energy_flows, "battery_to_home", 0.0)
                + getattr(energy_flows, "battery_to_ev", 0.0)
            )
            grid_supply = (
                getattr(energy_flows, "grid_to_home", 0.0)
                + getattr(energy_flows, "grid_to_ev", 0.0)
            )
            total_consumption = own_supply + grid_supply
            if total_consumption > 0:
                metrics.autarky_rate = round(
                    (own_supply / total_consumption) * 100, 1,
                )
                metrics.autarky_rate = max(0, min(100, metrics.autarky_rate))
        else:
            # Legacy path — kept for v1.6.x compatibility and the
            # two-arg call shape used in pre-v1.7.0 test fixtures.
            total_consumption = energy.daily_home + energy.daily_ev
            if total_consumption > 0:
                own_supply = total_consumption - energy.daily_grid_import
                metrics.autarky_rate = round(
                    (own_supply / total_consumption) * 100, 1,
                )
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

    def _accumulate_cost(
        self, category: str, today: date, month_key: str, year_key: str, increment: float
    ) -> None:
        """Accumulate a cost increment for a category (no lifetime — ROI uses separate accumulators)."""
        daily_key = f"{category}_{today}"
        monthly_key = f"{category}_{month_key}"
        yearly_key = f"{category}_{year_key}"
        if daily_key not in self._daily_cost_accumulators:
            self._daily_cost_accumulators[daily_key] = 0.0
        if monthly_key not in self._monthly_cost_accumulators:
            self._monthly_cost_accumulators[monthly_key] = 0.0
        if yearly_key not in self._yearly_cost_accumulators:
            self._yearly_cost_accumulators[yearly_key] = 0.0
        self._daily_cost_accumulators[daily_key] += increment
        self._monthly_cost_accumulators[monthly_key] += increment
        self._yearly_cost_accumulators[yearly_key] += increment

    def _get_daily_cost(self, category: str, today: date) -> float:
        """Get daily accumulated cost."""
        return round(self._daily_cost_accumulators.get(f"{category}_{today}", 0.0), 2)

    def _get_monthly_cost(self, category: str, month_key: str) -> float:
        """Get monthly accumulated cost."""
        return round(self._monthly_cost_accumulators.get(f"{category}_{month_key}", 0.0), 2)

    def _get_yearly_cost(self, category: str, year_key: str) -> float:
        """Get yearly accumulated cost."""
        return round(self._yearly_cost_accumulators.get(f"{category}_{year_key}", 0.0), 2)

    def _get_avg_import_rate(self) -> float:
        """7-day average import rate, falling back to current rate."""
        if not self._rate_history:
            return self._import_rate
        recent = list(self._rate_history)[-7:]
        total = sum(r["import_rate"] for r in recent)
        return total / len(recent)

    def _get_avg_export_rate(self) -> float:
        """7-day average export rate, falling back to current rate."""
        if not self._rate_history:
            return self._export_rate
        recent = list(self._rate_history)[-7:]
        total = sum(r["export_rate"] for r in recent)
        return total / len(recent)

    def _snapshot_daily_costs(self, today: date) -> None:
        """Snapshot today's costs into accumulated totals before daily reset.

        Called from _check_rollover when the day changes.
        """
        # Read today's energy values before they get cleaned up
        today_str = str(today)
        daily_grid_import = self._daily_accumulators.get(f"grid_import_{today_str}", 0.0)
        daily_grid_export = self._daily_accumulators.get(f"grid_export_{today_str}", 0.0)
        daily_solar = self._daily_accumulators.get(f"solar_{today_str}", 0.0)
        daily_self_consumed = max(0, daily_solar - daily_grid_export)

        # Use incremental cost accumulators (rate-weighted, accurate for dynamic tariffs)
        daily_cost = self._daily_cost_accumulators.get(f"cost_import_{today_str}", 0.0)
        daily_export_revenue = self._daily_cost_accumulators.get(f"cost_export_{today_str}", 0.0)
        daily_savings = self._daily_cost_accumulators.get(f"cost_savings_{today_str}", 0.0)
        daily_battery_savings = self._daily_cost_accumulators.get(f"cost_batt_savings_{today_str}", 0.0)

        # Accumulate into running totals
        self._accumulated_savings += daily_savings
        self._accumulated_battery_savings += daily_battery_savings
        self._accumulated_cost += daily_cost
        self._accumulated_export_revenue += daily_export_revenue
        self._accumulated_grid_import_kwh += daily_grid_import
        self._accumulated_self_consumed_kwh += daily_self_consumed
        self._accumulated_export_kwh += daily_grid_export

        # Store today's rate for averaging; also record whether snapshot had meaningful data
        # (used by _check_rollover to detect trivial snapshots that should be retried).
        #
        # #499: use the day's VOLUME-WEIGHTED average (cost ÷ kWh) instead of
        # the rate in effect at midnight. For spot tariffs midnight is
        # systematically among the cheapest hours, which biased the 7-day
        # average — and with it the pre-SEM ROI estimate — low. Falls back to
        # the current rate on days without (positive) cost data.
        if daily_grid_import > 0.05 and daily_cost > 0:
            day_import_rate = daily_cost / daily_grid_import
        else:
            day_import_rate = self._import_rate
        if daily_grid_export > 0.05 and daily_export_revenue > 0:
            day_export_rate = daily_export_revenue / daily_grid_export
        else:
            day_export_rate = self._export_rate
        self._rate_history.append({
            "date": today_str,
            "import_rate": round(day_import_rate, 4),
            "export_rate": round(day_export_rate, 4),
            "energy_kwh": round(daily_solar + daily_grid_import, 4),
        })

    def _check_rollover(self, today: date, month_key: str, year_key: str = None) -> None:
        """Check for day/month rollover and cleanup old accumulators.

        EV keys (ev_daily_sun_*) are excluded — they use sunrise-based dates
        and get cleaned up separately (older than yesterday).
        """
        yesterday = today - timedelta(days=1)
        yesterday_str = str(yesterday)

        # Snapshot yesterday's costs before cleaning up (for accumulated ROI)
        has_yesterday_data = any(
            k.endswith(yesterday_str) and not k.startswith("ev_daily_sun")
            for k in self._daily_accumulators
        )
        # A prior snapshot is only considered valid if it captured non-zero energy.
        # If the system restarted around midnight and snapshotted before real data
        # accumulated, allow a re-snapshot when meaningful data is now present. (#225)
        prior_snapshot = next(
            (r for r in self._rate_history if r.get("date") == yesterday_str), None
        )
        already_snapshotted = prior_snapshot is not None and prior_snapshot.get("energy_kwh", 1.0) > 0
        if has_yesterday_data and not already_snapshotted:
            self._snapshot_daily_costs(yesterday)

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
            and not k.endswith(yesterday_str)
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

        # Clean up cost accumulators — mirror the energy accumulator cleanup
        today_str = str(today)
        cost_daily_remove = [
            k for k in self._daily_cost_accumulators
            if not k.endswith(today_str)
        ]
        for key in cost_daily_remove:
            del self._daily_cost_accumulators[key]

        cost_monthly_remove = [
            k for k in self._monthly_cost_accumulators
            if not k.endswith(month_key)
        ]
        for key in cost_monthly_remove:
            del self._monthly_cost_accumulators[key]

        if year_key:
            cost_yearly_remove = [
                k for k in self._yearly_cost_accumulators
                if not k.endswith(year_key)
            ]
            for key in cost_yearly_remove:
                del self._yearly_cost_accumulators[key]

    def get_state(self) -> Dict[str, Any]:
        """Get calculator state for persistence."""
        return {
            "daily_accumulators": self._daily_accumulators.copy(),
            "monthly_accumulators": self._monthly_accumulators.copy(),
            "yearly_accumulators": self._yearly_accumulators.copy(),
            "lifetime_accumulators": self._lifetime_accumulators.copy(),
            "daily_cost_accumulators": self._daily_cost_accumulators.copy(),
            "monthly_cost_accumulators": self._monthly_cost_accumulators.copy(),
            "yearly_cost_accumulators": self._yearly_cost_accumulators.copy(),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "yearly_seeded": self._yearly_seeded,
            "rate_history": list(self._rate_history),
            "accumulated_savings": self._accumulated_savings,
            "accumulated_battery_savings": self._accumulated_battery_savings,
            "accumulated_cost": self._accumulated_cost,
            "accumulated_export_revenue": self._accumulated_export_revenue,
            "accumulated_grid_import_kwh": self._accumulated_grid_import_kwh,
            "accumulated_self_consumed_kwh": self._accumulated_self_consumed_kwh,
            "accumulated_export_kwh": self._accumulated_export_kwh,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore calculator state from persistence."""
        if state:
            self._daily_accumulators = state.get("daily_accumulators", {})
            self._monthly_accumulators = state.get("monthly_accumulators", {})
            self._yearly_accumulators = state.get("yearly_accumulators", {})
            self._lifetime_accumulators = state.get("lifetime_accumulators", {})
            self._daily_cost_accumulators = state.get("daily_cost_accumulators", {})
            self._monthly_cost_accumulators = state.get("monthly_cost_accumulators", {})
            self._yearly_cost_accumulators = state.get("yearly_cost_accumulators", {})
            self._yearly_seeded = state.get("yearly_seeded", False)
            self._rate_history = deque(state.get("rate_history", []), maxlen=30)
            self._accumulated_savings = state.get("accumulated_savings", 0.0)
            self._accumulated_battery_savings = state.get("accumulated_battery_savings", 0.0)
            self._accumulated_cost = state.get("accumulated_cost", 0.0)
            self._accumulated_export_revenue = state.get("accumulated_export_revenue", 0.0)
            self._accumulated_grid_import_kwh = state.get("accumulated_grid_import_kwh", 0.0)
            self._accumulated_self_consumed_kwh = state.get("accumulated_self_consumed_kwh", 0.0)
            self._accumulated_export_kwh = state.get("accumulated_export_kwh", 0.0)
            last_update = state.get("last_update")
            if last_update:
                self._last_update = datetime.fromisoformat(last_update)
