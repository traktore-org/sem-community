"""Storage module for SEM coordinator.

Handles persistence of energy data across Home Assistant restarts.
Uses two storage strategies:
- Energy totals: Frequently updated, uses delayed save (batched writes)
- Daily baselines: Infrequently updated, uses immediate save
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable

from homeassistant.core import HomeAssistant, Event
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Storage version for migration support
STORAGE_VERSION = 1

# Delayed save interval for energy totals (seconds)
ENERGY_SAVE_DELAY = 60
# Throttle interval for periodic daily-state writes (seconds). The daily store
# previously only reached disk on a graceful HA stop (async_delay_save resets
# its timer on every call, so under the continuous coordinator loop it never
# fired mid-run), so an unclean reboot lost the day's device-runtime progress.
# async_save_daily_throttled writes immediately at most this often instead.
DAILY_SAVE_INTERVAL = 120


class SEMStorage:
    """Handles persistence of SEM data."""

    def __init__(self, hass: HomeAssistant, entry_id: str):
        """Initialize storage handler."""
        self.hass = hass
        self._entry_id = entry_id

        # Storage stores
        self._energy_store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_energy"
        )
        self._daily_store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_daily"
        )

        # Data containers
        self._energy_data: Dict[str, Any] = {}
        self._daily_data: Dict[str, Any] = {}

        # State tracking
        self._loaded = False
        self._shutdown_listener: Optional[Callable] = None
        self._last_daily_save_ts: float = 0.0  # monotonic, for the throttle

    @property
    def is_loaded(self) -> bool:
        """Check if data has been loaded."""
        return self._loaded

    async def async_load(self) -> None:
        """Load all persisted data."""
        await self._load_energy_data()
        await self._load_daily_data()
        self._loaded = True
        self._register_shutdown_listener()

    async def _load_energy_data(self) -> None:
        """Load energy totals from storage."""
        try:
            stored = await self._energy_store.async_load()
            if stored:
                # Validate restored data ranges (#37)
                if not self._validate_energy_data(stored):
                    _LOGGER.warning("Energy data failed validation, starting fresh")
                    self._energy_data = self._get_default_energy_data()
                else:
                    self._energy_data = stored
                    _LOGGER.info(
                        "Loaded energy data: %d accumulators",
                        len(stored.get("accumulators", {})),
                    )
            else:
                _LOGGER.info("No persisted energy data found, starting fresh")
                self._energy_data = self._get_default_energy_data()
        except (OSError, ValueError, TypeError) as e:
            _LOGGER.warning("Failed to load energy data: %s", e)
            self._energy_data = self._get_default_energy_data()

    async def _load_daily_data(self) -> None:
        """Load daily baselines from storage.

        (#563) The calculator's accumulators (daily/monthly/yearly/
        lifetime/cost) live in THIS store — apply the same per-entry
        repair as the energy store so a single bad value (e.g. a
        pre-#551 ×1000-inflated lifetime counter) can never take the
        day's data down with it.
        """
        try:
            stored = await self._daily_store.async_load()
            if stored:
                if not self._validate_daily_data(stored):
                    _LOGGER.warning("Daily data failed validation, starting fresh")
                    self._daily_data = self._get_default_daily_data()
                else:
                    self._daily_data = stored
                    _LOGGER.info(
                        "Loaded daily data: %d baselines",
                        len(stored.get("baselines", {})),
                    )
            else:
                _LOGGER.info("No persisted daily data found, starting fresh")
                self._daily_data = self._get_default_daily_data()
        except (OSError, ValueError, TypeError) as e:
            _LOGGER.warning("Failed to load daily data: %s", e)
            self._daily_data = self._get_default_daily_data()

    @staticmethod
    def _validate_energy_data(data: Dict[str, Any]) -> bool:
        """Validate + repair restored energy data (#37, #563).

        Catches corrupted storage (partial writes, disk errors) before
        the values propagate into energy sensors.

        Returns False only for STRUCTURAL corruption (wrong types) —
        that discards the store. Per-entry problems (non-numeric or
        out-of-range values) are repaired in place by dropping just the
        offending accumulator: #563 proved the all-or-nothing version
        destroyed data — one ×1000-inflated lifetime counter (pre-#551
        Wh-as-kWh reads) tripped the 100 MWh cap on the upgrade restart
        and wiped every daily/monthly/cost accumulator with it. Dropped
        lifetime entries are re-seeded from hardware counters by the
        energy calculator; daily/monthly entries rebuild naturally.
        """
        if not isinstance(data, dict):
            return False

        if not SEMStorage._repair_accumulator_dicts(
            data,
            ("accumulators", "daily_accumulators", "monthly_accumulators",
             "yearly_accumulators", "lifetime_accumulators"),
        ):
            return False

        # Validate last_update timestamp if present
        last_update = data.get("last_update")
        if last_update is not None and not isinstance(last_update, str):
            _LOGGER.warning("Invalid last_update type: %s", type(last_update))
            return False

        return True

    @staticmethod
    def _validate_daily_data(data: Dict[str, Any]) -> bool:
        """Validate + repair the daily store (#563).

        This store holds the calculator's real accumulators; same
        per-entry repair semantics as ``_validate_energy_data``.
        ``solar_counter_baselines`` (#556) is deliberately NOT in the
        whitelist — it holds nested dicts and a date string, which the
        numeric-value repair would mangle."""
        if not isinstance(data, dict):
            return False
        return SEMStorage._repair_accumulator_dicts(
            data,
            ("daily_accumulators", "monthly_accumulators",
             "yearly_accumulators", "lifetime_accumulators",
             "daily_cost_accumulators", "monthly_cost_accumulators",
             "yearly_cost_accumulators"),
        )

    @staticmethod
    def _repair_accumulator_dicts(data: Dict[str, Any], acc_keys) -> bool:
        """Per-entry repair of accumulator dicts inside ``data``.

        Returns False only on STRUCTURAL corruption (an accumulator
        container that is not a dict). Bad entries are repaired in
        place: non-numeric and >100 MWh values are dropped (dropped
        lifetime entries get re-seeded from hardware counters by the
        energy calculator; daily/monthly rebuild naturally), negative
        daily values are clamped to 0."""
        for acc_key in acc_keys:
            accumulators = data.get(acc_key)
            if accumulators is None:
                continue
            if not isinstance(accumulators, dict):
                _LOGGER.warning("Storage key '%s' is not a dict", acc_key)
                return False
            dropped = []
            for key, value in accumulators.items():
                if not isinstance(value, (int, float)):
                    _LOGGER.warning(
                        "Non-numeric accumulator %s.%s=%s — dropping entry",
                        acc_key, key, value,
                    )
                    dropped.append(key)
                    continue
                # Sane range: no single accumulator should exceed 100 MWh
                if abs(value) > 100_000:
                    _LOGGER.warning(
                        "Accumulator %s.%s=%.1f kWh exceeds 100 MWh limit — "
                        "dropping entry (rest of the store is kept)",
                        acc_key, key, value,
                    )
                    dropped.append(key)
                    continue
                # Daily accumulators should never be negative
                if acc_key == "daily_accumulators" and value < -0.01:
                    _LOGGER.warning(
                        "Negative daily accumulator %s=%.2f kWh — resetting to 0",
                        key, value,
                    )
                    accumulators[key] = 0.0
            for key in dropped:
                del accumulators[key]
        return True

    def _get_default_energy_data(self) -> Dict[str, Any]:
        """Get default energy data structure."""
        return {
            "accumulators": {},
            "previous_values": {},
            "last_update": None,
        }

    def _get_default_daily_data(self) -> Dict[str, Any]:
        """Get default daily data structure."""
        return {
            "baselines": {},
            "flow_accumulators": {},
            "daily_accumulators": {},
            "monthly_accumulators": {},
        }

    # Energy data accessors
    def get_accumulator(self, key: str) -> float:
        """Get energy accumulator value."""
        return self._energy_data.get("accumulators", {}).get(key, 0.0)

    def set_accumulator(self, key: str, value: float) -> None:
        """Set energy accumulator value."""
        if "accumulators" not in self._energy_data:
            self._energy_data["accumulators"] = {}
        self._energy_data["accumulators"][key] = value

    def get_previous_value(self, key: str) -> Optional[float]:
        """Get previous power value for delta calculations."""
        return self._energy_data.get("previous_values", {}).get(key)

    def set_previous_value(self, key: str, value: float) -> None:
        """Set previous power value."""
        if "previous_values" not in self._energy_data:
            self._energy_data["previous_values"] = {}
        self._energy_data["previous_values"][key] = value

    def get_last_update(self) -> Optional[datetime]:
        """Get last update timestamp."""
        ts = self._energy_data.get("last_update")
        if ts:
            return datetime.fromisoformat(ts)
        return None

    # Daily data accessors
    def get_baseline(self, key: str) -> float:
        """Get daily baseline value."""
        return self._daily_data.get("baselines", {}).get(key, 0.0)

    def set_baseline(self, key: str, value: float) -> None:
        """Set daily baseline value."""
        if "baselines" not in self._daily_data:
            self._daily_data["baselines"] = {}
        self._daily_data["baselines"][key] = value

    def get_flow_accumulator(self, key: str) -> float:
        """Get flow accumulator value."""
        return self._daily_data.get("flow_accumulators", {}).get(key, 0.0)

    def set_flow_accumulator(self, key: str, value: float) -> None:
        """Set flow accumulator value."""
        if "flow_accumulators" not in self._daily_data:
            self._daily_data["flow_accumulators"] = {}
        self._daily_data["flow_accumulators"][key] = value

    def get_daily_accumulator(self, key: str) -> float:
        """Get daily energy accumulator."""
        return self._daily_data.get("daily_accumulators", {}).get(key, 0.0)

    def set_daily_accumulator(self, key: str, value: float) -> None:
        """Set daily energy accumulator."""
        if "daily_accumulators" not in self._daily_data:
            self._daily_data["daily_accumulators"] = {}
        self._daily_data["daily_accumulators"][key] = value

    def get_monthly_accumulator(self, key: str) -> float:
        """Get monthly energy accumulator."""
        return self._daily_data.get("monthly_accumulators", {}).get(key, 0.0)

    def set_monthly_accumulator(self, key: str, value: float) -> None:
        """Set monthly energy accumulator."""
        if "monthly_accumulators" not in self._daily_data:
            self._daily_data["monthly_accumulators"] = {}
        self._daily_data["monthly_accumulators"][key] = value

    # Device runtime persistence
    def get_device_runtimes(self) -> Dict[str, Dict]:
        """Get all persisted device runtimes."""
        return self._daily_data.get("device_runtimes", {})

    def set_device_runtime(
        self, device_id: str, accumulated_sec: float, meter_day: str,
        accumulated_kwh: float = 0.0,
    ) -> None:
        """Persist a device's daily runtime (+ energy progress, #559)."""
        if "device_runtimes" not in self._daily_data:
            self._daily_data["device_runtimes"] = {}
        self._daily_data["device_runtimes"][device_id] = {
            "accumulated_sec": accumulated_sec,
            "accumulated_kwh": accumulated_kwh,
            "meter_day": meter_day,
        }

    def clear_daily_accumulators(self) -> None:
        """Clear daily accumulators for day rollover."""
        self._daily_data["daily_accumulators"] = {}
        self._daily_data["flow_accumulators"] = {}
        self._daily_data["device_runtimes"] = {}
        _LOGGER.debug("Cleared daily accumulators for new day")

    def clear_monthly_accumulators(self) -> None:
        """Clear monthly accumulators for month rollover."""
        self._daily_data["monthly_accumulators"] = {}
        _LOGGER.debug("Cleared monthly accumulators for new month")

    # Lifetime EV statistics (never reset)
    def get_lifetime_ev_stats(self) -> Dict[str, float]:
        """Get lifetime EV charging statistics."""
        return self._energy_data.get("lifetime_ev", {
            "total_energy_kwh": 0.0,
            "total_solar_kwh": 0.0,
            "total_grid_kwh": 0.0,
            "total_battery_kwh": 0.0,
            "total_cost": 0.0,
            "total_sessions": 0,
        })

    def update_lifetime_ev_stats(self, session_energy: float, solar_energy: float,
                                  grid_energy: float, battery_energy: float,
                                  cost: float) -> None:
        """Add completed session to lifetime stats."""
        stats = self.get_lifetime_ev_stats()
        stats["total_energy_kwh"] = round(stats["total_energy_kwh"] + session_energy, 2)
        stats["total_solar_kwh"] = round(stats["total_solar_kwh"] + solar_energy, 2)
        stats["total_grid_kwh"] = round(stats["total_grid_kwh"] + grid_energy, 2)
        stats["total_battery_kwh"] = round(stats["total_battery_kwh"] + battery_energy, 2)
        stats["total_cost"] = round(stats["total_cost"] + cost, 2)
        stats["total_sessions"] = stats["total_sessions"] + 1
        self._energy_data["lifetime_ev"] = stats

    # EV session state persistence
    def get_ev_session_state(self) -> Dict[str, Any]:
        """Get persisted EV session state for restart recovery."""
        return self._daily_data.get("ev_session", {})

    def set_ev_session_state(self, state: Dict[str, Any]) -> None:
        """Persist EV session state (survives restarts)."""
        self._daily_data["ev_session"] = state

    # EV intelligence persistence (survives restarts and daily resets)
    def get_ev_intelligence_state(self) -> Dict[str, Any]:
        """Get persisted EV intelligence state (taper, SOC, health)."""
        return self._energy_data.get("ev_intelligence", {
            "last_full_charge": None,
            "energy_since_full": 0.0,
            "ev_consumption_profile": {},
            "session_history": [],
            "battery_health_samples": [],
        })

    def set_ev_intelligence_state(self, state: Dict[str, Any]) -> None:
        """Persist EV intelligence state."""
        self._energy_data["ev_intelligence"] = state

    # Sign-detection persistence (#476 item 5) — locked grid/battery
    # sign flags survive restarts so the autodetect can't re-learn a
    # wrong sign from ambiguous post-reboot samples.
    def get_sign_state(self) -> Dict[str, Any]:
        """Get persisted sign-detection lock state."""
        return self._energy_data.get("sign_state", {})

    def set_sign_state(self, state: Dict[str, Any]) -> None:
        """Persist sign-detection lock state."""
        self._energy_data["sign_state"] = state

    # Legionella timestamp persistence (#508 I2) — without this, driving
    # the legionella cycle (#508 C1) would force a disinfection run on
    # every restart, since a None timestamp reads as "overdue".
    def get_legionella_time(self) -> Optional[str]:
        """Get the persisted last-legionella ISO timestamp, or None."""
        return self._energy_data.get("legionella_last_time")

    def set_legionella_time(self, iso_ts: Optional[str]) -> None:
        """Persist the last-legionella ISO timestamp."""
        if iso_ts:
            self._energy_data["legionella_last_time"] = iso_ts

    def add_session_to_history(self, session: Dict[str, Any]) -> None:
        """Append a completed session to bounded history (max 90 entries)."""
        state = self.get_ev_intelligence_state()
        history = state.get("session_history", [])
        history.append(session)
        if len(history) > 90:
            history = history[-90:]
        state["session_history"] = history
        self._energy_data["ev_intelligence"] = state

    def get_session_history(self) -> list:
        """Get EV session history (bounded to 90 entries)."""
        state = self.get_ev_intelligence_state()
        return state.get("session_history", [])

    # Save operations
    async def async_save_energy_delayed(self) -> None:
        """Save energy data with delayed write for performance.

        Batches multiple updates within ENERGY_SAVE_DELAY seconds.
        """
        try:
            def get_data() -> Dict[str, Any]:
                return {
                    **self._energy_data,
                    "last_update": dt_util.now().isoformat(),
                }

            self._energy_store.async_delay_save(get_data, ENERGY_SAVE_DELAY)
            _LOGGER.debug("Scheduled delayed save of energy data")
        except (OSError, TypeError) as e:
            _LOGGER.warning("Failed to schedule energy data save: %s", e)

    async def async_save_daily(self) -> None:
        """Save daily data immediately."""
        try:
            await self._daily_store.async_save(self._daily_data)
            _LOGGER.debug("Saved daily data to storage")
        except (OSError, TypeError) as e:
            _LOGGER.warning("Failed to save daily data: %s", e)

    async def async_save_daily_throttled(self) -> None:
        """Write the daily store to disk immediately, at most once per
        DAILY_SAVE_INTERVAL seconds.

        Deliberately NOT async_delay_save: that resets its delay timer on
        every call, so under the continuous coordinator update loop it never
        fires until updates pause (i.e. only at shutdown). This throttle
        guarantees a real mid-run write, bounding unclean-reboot loss of the
        device-runtime counter (and the rest of the daily state) to one
        interval instead of the whole day.
        """
        now = time.monotonic()
        if now - self._last_daily_save_ts < DAILY_SAVE_INTERVAL:
            return
        self._last_daily_save_ts = now
        await self.async_save_daily()

    async def async_save_all(self) -> None:
        """Save all data immediately (for shutdown)."""
        try:
            # Save energy data immediately
            energy_data = {
                **self._energy_data,
                "last_update": dt_util.now().isoformat(),
            }
            await self._energy_store.async_save(energy_data)
            _LOGGER.debug("Saved energy data on shutdown")

            # Save daily data
            await self._daily_store.async_save(self._daily_data)
            _LOGGER.debug("Saved daily data on shutdown")

            _LOGGER.info("All SEM data saved successfully")
        except (OSError, TypeError) as e:
            _LOGGER.error("Failed to save SEM data: %s", e)

    def _register_shutdown_listener(self) -> None:
        """Register shutdown listener to save data before HA stops."""
        if self._shutdown_listener is None:
            self._shutdown_listener = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP,
                self._handle_shutdown
            )
            _LOGGER.debug("Registered shutdown listener for data persistence")

    async def _handle_shutdown(self, event: Event) -> None:
        """Save all data before shutdown."""
        _LOGGER.info("Handling shutdown, saving all SEM data...")
        await self.async_save_all()

    # State export/import for calculators
    def export_energy_calculator_state(self) -> Dict[str, Any]:
        """Export state for EnergyCalculator.

        #351 M1 — cost accumulators are now round-tripped alongside the
        energy ones. Pre-fix the calculator emitted them via
        ``get_state()`` but this layer dropped them on export and
        ``import_energy_calculator_state`` discarded them; ``daily_savings``
        silently reset to 0 mid-day after any HA restart while
        ``daily_solar`` / ``daily_grid_import`` resumed from storage.
        """
        return {
            "daily_accumulators": dict(self._daily_data.get("daily_accumulators", {})),
            "monthly_accumulators": dict(self._daily_data.get("monthly_accumulators", {})),
            "yearly_accumulators": dict(self._daily_data.get("yearly_accumulators", {})),
            "lifetime_accumulators": dict(self._daily_data.get("lifetime_accumulators", {})),
            "daily_cost_accumulators": dict(self._daily_data.get("daily_cost_accumulators", {})),
            "monthly_cost_accumulators": dict(self._daily_data.get("monthly_cost_accumulators", {})),
            "yearly_cost_accumulators": dict(self._daily_data.get("yearly_cost_accumulators", {})),
            "last_update": self._energy_data.get("last_update"),
            "yearly_seeded": self._daily_data.get("yearly_seeded", False),
            # (#556) solar hardware-counter baselines
            "solar_counter_baselines": dict(
                self._daily_data.get("solar_counter_baselines", {})
            ),
        }

    def import_energy_calculator_state(self, state: Dict[str, Any]) -> None:
        """Import state from EnergyCalculator. See export docstring."""
        if "daily_accumulators" in state:
            self._daily_data["daily_accumulators"] = state["daily_accumulators"]
        if "monthly_accumulators" in state:
            self._daily_data["monthly_accumulators"] = state["monthly_accumulators"]
        if "yearly_accumulators" in state:
            self._daily_data["yearly_accumulators"] = state["yearly_accumulators"]
        if "lifetime_accumulators" in state:
            self._daily_data["lifetime_accumulators"] = state["lifetime_accumulators"]
        # #351 M1 — persist cost accumulators across restarts.
        if "daily_cost_accumulators" in state:
            self._daily_data["daily_cost_accumulators"] = state["daily_cost_accumulators"]
        if "monthly_cost_accumulators" in state:
            self._daily_data["monthly_cost_accumulators"] = state["monthly_cost_accumulators"]
        if "yearly_cost_accumulators" in state:
            self._daily_data["yearly_cost_accumulators"] = state["yearly_cost_accumulators"]
        if "yearly_seeded" in state:
            self._daily_data["yearly_seeded"] = state["yearly_seeded"]
        # (#556) solar hardware-counter baselines
        if "solar_counter_baselines" in state:
            self._daily_data["solar_counter_baselines"] = state["solar_counter_baselines"]

    def export_forecast_tracker_state(self) -> Dict[str, Any]:
        """Export state for ForecastTracker."""
        return dict(self._daily_data.get("forecast_tracker", {}))

    def import_forecast_tracker_state(self, state: Dict[str, Any]) -> None:
        """Import state from ForecastTracker."""
        if state:
            self._daily_data["forecast_tracker"] = state
