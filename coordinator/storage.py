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

# (#668) The keys of ``EnergyCalculator.get_state()`` that this layer carries.
#
# ONE list, deliberately. Before #668 the export and the import each had their
# own hand-written list and they had drifted apart twice: #351 M1 found the
# cost accumulators missing from both, and #668 found nine more still missing
# after it. Neither drift could announce itself — the calculator reads its
# state back with ``state.get(key, default)``, so a dropped key is
# indistinguishable from a fresh install.
#
# ``last_update`` is NOT here and that is intentional: the calculator emits its
# own integration timestamp, but on the way back in we deliberately hand it the
# *save* timestamp from ``_energy_data`` instead (see the export below). It is
# the one key whose two directions legitimately differ.
CALCULATOR_STATE_KEYS: tuple[str, ...] = (
    "daily_accumulators",
    "monthly_accumulators",
    "yearly_accumulators",
    "lifetime_accumulators",
    "daily_cost_accumulators",
    "monthly_cost_accumulators",
    "yearly_cost_accumulators",
    "yearly_seeded",
    # (#556) solar hardware-counter baselines
    "solar_counter_baselines",
    # (#658) EV wallbox-counter baselines
    "ev_counter_baselines",
    # (#628) grid/battery meter baselines, keyed by category
    "meter_baselines",
    # (#628) the CALENDAR-day EV mirror the home balance subtracts, and the
    # first day it was tracking. The latter must persist, or every restart
    # would look like the upgrade day and suppress the balance for good.
    "midnight_ev_baselines",
    "midnight_ev_since",
    # (#724) the deadline that opened the running EV day, and the day key it
    # produced. Both must persist: a restart that re-derives the day from the
    # CURRENT deadline re-buckets a day the user moved the deadline on, which
    # is the very thing ``_ev_reset_day`` defers.
    "ev_day_offset",
    "ev_day_key",
    # (#668) lifetime running totals, summed at each day rollover. Dropped
    # since they were introduced, so ``lifetime_total_savings`` fell back to a
    # 7-day-average-rate ESTIMATE of the entire history after every restart
    # instead of the rate-weighted real figure — a plausible number, which is
    # why it was never reported.
    "accumulated_savings",
    "accumulated_battery_savings",
    "accumulated_cost",
    "accumulated_export_revenue",
    "accumulated_grid_import_kwh",
    "accumulated_self_consumed_kwh",
    "accumulated_export_kwh",
    # (#668) the 7-day rate window those estimates are built from, and the
    # once-per-year cost seeding flag — both also reset on every restart.
    "rate_history",
    "yearly_cost_seeded",
)


def _copy_value(value: Any) -> Any:
    """Shallow-copy containers so a caller cannot mutate the live store."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


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
        """Store the PRIMARY detector's state. (#635) MERGES over the existing
        dict instead of replacing it — the per-charger states under
        ``chargers`` and the bounded ``session_history`` live in the same
        dict and were silently wiped by the wholesale replace every cycle
        (the restart-blank estimated-SOC bug: restore read ``chargers.<cid>``
        that no save path ever preserved)."""
        current = self._energy_data.get("ev_intelligence") or {}
        preserved = {k: current[k] for k in ("chargers", "session_history")
                     if k in current}
        merged = dict(state)
        merged.update(preserved)
        self._energy_data["ev_intelligence"] = merged

    def set_per_charger_intelligence_state(self, cid: str, state: Dict[str, Any]) -> None:
        """(#635) Persist one charger's taper/estimated-SOC state under
        ``ev_intelligence.chargers.<cid>`` — the key the boot-time restore
        has always read but nothing ever wrote."""
        intel = self._energy_data.get("ev_intelligence") or {}
        chargers = intel.get("chargers") or {}
        chargers[cid] = state
        intel["chargers"] = chargers
        self._energy_data["ev_intelligence"] = intel

    # Measured watts-per-amp persistence (#638 night 2) — the learned
    # W/A EMA survives restarts so the overnight packer never falls back
    # to nameplate right after a deploy. In-memory only, the 23:36
    # restart reset it and the 23:46 re-plan sized the EV floor at
    # 6.9 kW nameplate, found no slot under the peak, and yielded a car
    # that then charged at 4.54 kW. Same rule as the sign locks below:
    # learned state that gates behaviour is not allowed to die at boot.
    def get_overnight_plan_state(self) -> Dict[str, Any]:
        """(#638) Tonight's stamped plan + period + demand signature —
        a reboot must not silently reshuffle a night the actuation is
        steering by (Guido's Aug-5 note, made acute 00:20 on 08-09)."""
        return self._energy_data.get("overnight_plan", {})

    def set_overnight_plan_state(self, state: Dict[str, Any]) -> None:
        """(#638) Persist the stamp; saved by the normal delayed-save
        cycle — an abrupt kill before a save degrades to the old
        re-plan-on-boot, never to a corrupt night."""
        self._energy_data["overnight_plan"] = dict(state)

    # (#755) The third number: what each demand actually DID. Durable on
    # purpose — a night spans midnight and the daily bucket empties there,
    # so the per-device runtime accumulators cannot carry a night's outcome.
    # This is also the learner's only training set, which makes losing it at
    # boot a slow, silent regression rather than a visible one.
    def get_demand_outcome_state(self) -> Dict[str, Any]:
        """(#755) The open night's per-demand record plus night history."""
        return self._energy_data.get("demand_outcomes", {})

    def set_demand_outcome_state(self, state: Dict[str, Any]) -> None:
        """(#755) Persist the outcome record; delayed-save like the stamp."""
        self._energy_data["demand_outcomes"] = dict(state)

    def get_ev_wpa_state(self) -> Dict[str, float]:
        """Get the persisted per-charger measured-W/A EMA."""
        return self._energy_data.get("ev_wpa_ema", {})

    def set_ev_wpa_state(self, state: Dict[str, float]) -> None:
        """Persist the per-charger measured-W/A EMA."""
        self._energy_data["ev_wpa_ema"] = dict(state)

    # Sign-detection persistence (#476 item 5) — locked grid/battery
    # sign flags survive restarts so the autodetect can't re-learn a
    # wrong sign from ambiguous post-reboot samples.
    def get_sign_state(self) -> Dict[str, Any]:
        """Get persisted sign-detection lock state."""
        return self._energy_data.get("sign_state", {})

    def set_sign_state(self, state: Dict[str, Any]) -> None:
        """Persist sign-detection lock state."""
        self._energy_data["sign_state"] = state

    # VPP event history persistence (#580) — per-event energy accounting
    # for payment reconciliation (bounded to ~20 records by VppDispatcher).
    def get_vpp_events(self) -> list:
        """Get persisted VPP event records."""
        events = self._energy_data.get("vpp_events", [])
        return events if isinstance(events, list) else []

    def set_vpp_events(self, events: list) -> None:
        """Persist VPP event records."""
        self._energy_data["vpp_events"] = list(events or [])

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

    # Day-rollover decay bookkeeping (#645) — the date the virtual-SOC daily
    # decay LAST RAN, as an ISO date string. Distinct from the coordinator's
    # in-memory ``_tracker_date`` (which only owns the hour-bucket arrays):
    # without a persisted date, a restart that spans midnight initialises
    # "today" and the decay for the day just ended is skipped entirely.
    def get_last_decay_date(self) -> Optional[str]:
        """Get the ISO date the daily virtual-SOC decay last ran, or None."""
        value = self._energy_data.get("last_decay_date")
        return value if isinstance(value, str) else None

    def set_last_decay_date(self, iso_date: Optional[str]) -> None:
        """Persist the ISO date the daily virtual-SOC decay last ran."""
        if iso_date:
            self._energy_data["last_decay_date"] = iso_date

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
            # (#762) No heartbeat here: scheduling a save is not an event
            # (1930 identical lines/day on .175). Saves log on completion/failure.
        except (OSError, TypeError) as e:
            _LOGGER.warning("Failed to schedule energy data save: %s", e)

    async def async_save_energy_now(self) -> None:
        """Write the energy store to disk immediately (#645).

        Deliberately NOT ``async_save_energy_delayed``: ``async_delay_save``
        re-arms its timer on every call, so under the continuous coordinator
        update loop it never fires until updates pause — i.e. only at shutdown
        (same trap ``async_save_daily_throttled`` documents). A value that only
        exists to survive a restart cannot be written by a mechanism that only
        runs at a clean one; an unclean reboot would lose it every time.

        Only for rare, restart-critical writes — the decay date changes at most
        once a day. Do NOT reach for this in the per-cycle path.
        """
        try:
            await self._energy_store.async_save({
                **self._energy_data,
                "last_update": dt_util.now().isoformat(),
            })
            _LOGGER.debug("Saved energy data immediately")
        except (OSError, TypeError) as e:
            _LOGGER.warning("Failed to save energy data: %s", e)

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
        """Hand the stored calculator state back on load.

        Both directions are driven by ``CALCULATOR_STATE_KEYS`` — see the note
        there for why that is one list and not two.

        Keys absent from the store are simply not emitted; ``restore_state``
        applies its own defaults, so an absent key and an explicitly-defaulted
        one are the same thing to the calculator, and emitting a default here
        would only mean guessing its type in a second place.
        """
        state: Dict[str, Any] = {
            key: _copy_value(self._daily_data[key])
            for key in CALCULATOR_STATE_KEYS
            if key in self._daily_data
        }
        # Deliberately the SAVE timestamp, not the calculator's own integration
        # timestamp: it bounds how much downtime the first cycle after a
        # restart would otherwise try to integrate over. The calculator's
        # MAX_INTEGRATION_GAP_SECONDS guard turns a stale one into a single
        # skipped cycle.
        state["last_update"] = self._energy_data.get("last_update")
        return state

    def import_energy_calculator_state(self, state: Dict[str, Any]) -> None:
        """Take the calculator's state on save. See export docstring."""
        for key in CALCULATOR_STATE_KEYS:
            if key in state:
                self._daily_data[key] = state[key]


    def export_forecast_tracker_state(self) -> Dict[str, Any]:
        """Export state for ForecastTracker."""
        return dict(self._daily_data.get("forecast_tracker", {}))

    def import_forecast_tracker_state(self, state: Dict[str, Any]) -> None:
        """Import state from ForecastTracker."""
        if state:
            self._daily_data["forecast_tracker"] = state
