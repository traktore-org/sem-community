"""Storage module for SEM coordinator.

Handles persistence of energy data across Home Assistant restarts.
Uses two storage strategies:
- Energy totals: Frequently updated, uses delayed save (batched writes)
- Daily baselines: Infrequently updated, uses immediate save
"""
import logging
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
        """Load daily baselines from storage."""
        try:
            stored = await self._daily_store.async_load()
            if stored:
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
        """Validate restored energy data is within sane ranges (#37).

        Catches corrupted storage (partial writes, disk errors) before
        the values propagate into energy sensors.
        """
        if not isinstance(data, dict):
            return False
        accumulators = data.get("accumulators", {})
        if not isinstance(accumulators, dict):
            return False
        for key, value in accumulators.items():
            if not isinstance(value, (int, float)):
                _LOGGER.warning("Non-numeric accumulator %s=%s", key, value)
                return False
            # Sane range: no single accumulator should exceed 100 MWh
            if abs(value) > 100_000:
                _LOGGER.warning(
                    "Accumulator %s=%.1f kWh exceeds 100 MWh limit", key, value
                )
                return False
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

    def set_device_runtime(self, device_id: str, accumulated_sec: float, meter_day: str) -> None:
        """Persist a device's daily runtime."""
        if "device_runtimes" not in self._daily_data:
            self._daily_data["device_runtimes"] = {}
        self._daily_data["device_runtimes"][device_id] = {
            "accumulated_sec": accumulated_sec,
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
        """Export state for EnergyCalculator."""
        return {
            "daily_accumulators": dict(self._daily_data.get("daily_accumulators", {})),
            "monthly_accumulators": dict(self._daily_data.get("monthly_accumulators", {})),
            "yearly_accumulators": dict(self._daily_data.get("yearly_accumulators", {})),
            "lifetime_accumulators": dict(self._daily_data.get("lifetime_accumulators", {})),
            "last_update": self._energy_data.get("last_update"),
            "yearly_seeded": self._daily_data.get("yearly_seeded", False),
        }

    def import_energy_calculator_state(self, state: Dict[str, Any]) -> None:
        """Import state from EnergyCalculator."""
        if "daily_accumulators" in state:
            self._daily_data["daily_accumulators"] = state["daily_accumulators"]
        if "monthly_accumulators" in state:
            self._daily_data["monthly_accumulators"] = state["monthly_accumulators"]
        if "yearly_accumulators" in state:
            self._daily_data["yearly_accumulators"] = state["yearly_accumulators"]
        if "lifetime_accumulators" in state:
            self._daily_data["lifetime_accumulators"] = state["lifetime_accumulators"]
        if "yearly_seeded" in state:
            self._daily_data["yearly_seeded"] = state["yearly_seeded"]

    def export_forecast_tracker_state(self) -> Dict[str, Any]:
        """Export state for ForecastTracker."""
        return dict(self._daily_data.get("forecast_tracker", {}))

    def import_forecast_tracker_state(self, state: Dict[str, Any]) -> None:
        """Import state from ForecastTracker."""
        if state:
            self._daily_data["forecast_tracker"] = state
