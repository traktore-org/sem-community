"""Controllable device base classes for surplus-based energy management.

Uniform device abstraction where ALL consumers
are managed through a priority queue with minimum power thresholds.

Device Types:
- SwitchDevice: on/off (hot water relay, smart plugs)
- CurrentControlDevice: variable current (EV chargers)
- SetpointDevice: numerical target (heat pump temp, battery)
- ScheduleDevice: start signal with deadline (dishwasher, washer)
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

# #392: KEBA's failsafe watchdog (and similar device-side timers on other
# chargers) requires periodic *writes* to refresh — reads alone don't
# count. SEM's _set_current dedup used to suppress writes when the
# commanded value hadn't changed, which silently starved the watchdog
# during steady-state charging until the device dropped to fallback and
# charging halted. A same-value re-write at the refresh interval keeps it fed.
#
# The interval is a DEVICE capability, not a global constant: the failsafe
# timeout varies per brand and per user config. The generic default below
# assumed a 300 s KEBA failsafe (heartbeat at 1/5 of it). PROD showed a KEBA
# P30 whose failsafe trips near ~60 s — so a 60 s heartbeat RACES it
# (max_current oscillating 6↔12 A every ~60 s while SEM held 12 A, exporting
# the unused surplus). ``watchdog_refresh_interval_s`` resolves the real
# interval per charger, set comfortably under the shortest common failsafe.
DEFAULT_WRITE_HEARTBEAT_INTERVAL_S = 60.0
# Back-compat alias (older imports / tests reference this name).
WRITE_HEARTBEAT_INTERVAL_S = DEFAULT_WRITE_HEARTBEAT_INTERVAL_S
# Brands whose device-side failsafe can trip under the generic 60 s heartbeat.
# Refresh below the shortest common failsafe timeout so a steady-state command
# can't starve it. KEBA is set BELOW the ~10 s coordinator cycle so a steady
# command is re-asserted EVERY cycle — PROD showed a KEBA P30 reverting to its
# 6 A failsafe current in well under 30 s (offered current oscillating 6↔9/12 A,
# pausing the car to ~120 W), so 30 s still raced it. Per-cycle re-writes outrun
# any failsafe with a timeout ≥ ~1 cycle; a box that reverts sub-cycle is a
# device-side failsafe-config problem SEM cannot out-write.
_BRAND_WATCHDOG_REFRESH_S = {
    "keba": 5.0,
}

# #546 — managed-neutralize failsafe timeout. Long enough that the per-cycle
# current writes never let it trip during normal charging (vs the old 30 s that
# the box out-reverted to 6 A → the 6↔9 A flap), short enough that a genuine
# controller-death still lands the car on the charging floor within 10 min.
# Persisted so it overwrites the box's short built-in failsafe.
FAILSAFE_TIMEOUT_S = 600

# #740 — the dead-man's OFF timeout. When SEM STOPS a session, the failsafe
# re-arms with fallback 0 A ("disables the running charging process
# completely" — the documented keba semantics of fallback 0): a masterless,
# rebooting, or disable-defeating box locks itself off within this window
# and STAYS off until SEM's next start sequence re-arms the charging
# failsafe. 10 s is the keba integration's minimum accepted timeout. This
# is the inversion the #546 live test never tried: the watchdog cannot be
# turned off over UDP — so point it at 0 instead of fighting it.
FAILSAFE_OFF_TIMEOUT_S = 10

from ..consts.core import KEBA_IDLE_GUARD_KWH, DEFAULT_DEVICE_RATED_POWER
from ..coordinator.units import energy_state_to_kwh, power_state_to_watts

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class DeviceState(Enum):
    """Device operational state."""
    IDLE = "idle"
    ACTIVE = "active"
    BLOCKED = "blocked"
    ERROR = "error"
    SCHEDULED = "scheduled"


class DeviceType(Enum):
    """Device control type."""
    SWITCH = "switch"
    CURRENT_CONTROL = "current_control"
    SETPOINT = "setpoint"
    SCHEDULE = "schedule"
    CLIMATE = "climate"


class DeviceControlMode(Enum):
    """How SEM is allowed to control this device (#49).

    Hierarchy: off < peak_only < surplus
    Each level adds capability on top of the previous.

    - off:            SEM monitors but never controls this device
    - peak_only:      SEM can shed (turn off) to protect peak limit,
                      restores to pre-shed state. Never proactively turns on.
    - surplus:        SEM activates when surplus available, deactivates when
                      surplus drops. Also includes peak protection (shedding).

    Stopping surplus charging at a target (kWh or SOC %) is handled separately
    by the per-charger Max ceiling (``*_max``) of the charge-target range (#245),
    not by a control mode.
    """
    OFF = "off"
    PEAK_ONLY = "peak_only"
    SURPLUS = "surplus"


@dataclass
class DeviceStatus:
    """Current status of a controllable device."""
    state: DeviceState = DeviceState.IDLE
    current_consumption_w: float = 0.0
    allocated_power_w: float = 0.0
    last_activated: Optional[datetime] = None
    last_deactivated: Optional[datetime] = None
    error_message: Optional[str] = None
    activation_count: int = 0


class ControllableDevice(ABC):
    """Base class for all controllable devices in the surplus management system.

    Each device has a priority (1=highest, 10=lowest) and a minimum power
    threshold that must be met before the device is activated.

    The surplus controller iterates devices by priority, allocating surplus
    to each device that meets its minimum threshold.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        energy_entity_id: Optional[str] = None,
    ):
        self.hass = hass
        self.device_id = device_id
        self.name = name
        self.priority = max(1, min(10, priority))
        self.min_power_threshold = min_power_threshold
        self.entity_id = entity_id
        self.power_entity_id = power_entity_id
        # #600 — a kWh-only load device (no power sensor) can supply a
        # TOTAL_INCREASING energy counter; live power is derived from it. A
        # power sensor always wins; the deriver is the fallback. Lazily created.
        self.energy_entity_id = energy_entity_id
        self._energy_deriver = None
        self._status = DeviceStatus()
        self._enabled = True
        self._managed_externally = False
        self.control_mode = DeviceControlMode.PEAK_ONLY  # Default: peak protection only (#49)

        # Power-change cooldown
        self._min_power_change_interval: float = 0.0  # seconds, 0 = disabled
        self._last_power_change_time: Optional[datetime] = None

        # Anti-cycling: minimum on/off duration (protects compressors, relays)
        self.min_on_seconds: int = 0   # 0 = disabled. E.g., 300 for heat pump
        self.min_off_seconds: int = 0  # 0 = disabled. E.g., 180 for heat pump
        self._last_activated: Optional[datetime] = None
        self._last_deactivated: Optional[datetime] = None

        # Sustained surplus: require surplus for N seconds before activation
        self.activation_delay_seconds: int = 0  # 0 = activate immediately
        self._surplus_since: Optional[datetime] = None

        # Daily runtime tracking (Feature 2)
        self.daily_min_runtime_sec: int = 0  # 0 = disabled
        # (#620) daily MAXIMUM runtime cap — the device never runs past this in
        # a day (pump wear / waste protection). 0 = uncapped. Persisted +
        # restored (the #559 HIGH-1 was an un-persisted cap lost on restart).
        self.daily_max_runtime_sec: int = 0  # 0 = uncapped
        self._daily_runtime_accumulated_sec: float = 0.0
        self._daily_runtime_last_check: Optional[datetime] = None
        self._daily_runtime_meter_day: Optional[date] = None
        self._offpeak_forced: bool = False

        # (#620) Battery use, two tiers gated by the existing Buffer + Reserve
        # SoC. Tier 1 (``battery_assist_enabled``) = the "Solar + battery" mode:
        # the battery assists this device above the Buffer SoC when real surplus
        # exists (self-consumption max, mirrors the EV #545) — automatic, no
        # per-cycle drain of stored house energy. Tier 2
        # (``battery_eligible_overnight``) = the opt-in to draw BELOW the buffer,
        # down to the Reserve SoC, when there is no surplus (spends stored house
        # energy at night). Both default off — a bare switch load never touches
        # the battery until the user chooses a battery mode. The allocation that
        # CONSUMES these flags lands in surplus_controller (#620 Phase 2).
        self.battery_assist_enabled: bool = False
        self.battery_eligible_overnight: bool = False

        # (#559) Goal engine — grounded core. daily_min_runtime_sec (above,
        # pre-#559 "Feature 2") is the only target; solar_only default means
        # a switch load never grid-forces. cheap_hours is kept for the HW/HP
        # off-peak pass. Opt-in (0/empty = disabled); only meaningful in SURPLUS.
        self.top_up_policy: str = "solar_only"         # solar_only | cheap_hours
        # (#559 Phase 3) external completion condition (e.g. car SOC sensor)
        self.stop_entity: str = ""
        self.stop_at: float = 0.0
        # Off-peak force bookkeeping: a cheap-hours force expires at day
        # rollover (the deficit was YESTERDAY's) so it can't re-fill the new
        # day's target from grid overnight.
        self._offpeak_forced_date: Optional[date] = None
        # (#620) Tier-2 overnight battery force marker — SEPARATE from the
        # cheap-hours ``_offpeak_forced`` so the cheap-hours force-expiry (which
        # deactivates at non-cheap tariff) can't kill a battery-overnight run
        # every cycle. Tier 2 expires on its own terms: the Reserve floor, the
        # daily target met, or the day rollover.
        self._batt_overnight_forced: bool = False
        self._batt_overnight_forced_date: Optional[date] = None

        # Appliance dependencies (#122): device only activates when dependencies are met
        self.depends_on: List[str] = []  # device_ids that must be active
        self.dependency_mode: str = "must_active"  # must_active | must_inactive
        self._controller = None  # set by SurplusController after registration

        # (arc) Ownership + observed-state reconciliation. `_sem_owned` is True
        # while SEM is the reason the load is on (it called activate()). The
        # DeviceReconciler clears it when an external actor (the user, another
        # automation) changed the physical state, so SEM stops fighting a manual
        # on/off and stops crediting runtime to a load it isn't actually driving.
        self._sem_owned: bool = False
        # Monotonic anchor for the "belief says on but the entity reads off"
        # drift grace window (a transient unavailable/poll gap must not flip us).
        self._observed_off_since: Optional[float] = None
        # Wall-clock cooldown after an external OFF: don't immediately re-activate
        # (respect a possible user turn-off) until it elapses.
        self._external_off_until: Optional[datetime] = None

    @property
    def device_type(self) -> DeviceType:
        """Return the device type."""
        raise NotImplementedError

    @property
    def is_active(self) -> bool:
        """Return True if device is currently consuming power."""
        return self._status.state == DeviceState.ACTIVE

    def _brand_key(self) -> str:
        """Best-effort charger brand token from the configured service /
        entities (e.g. ``keba`` from ``keba.set_current``). Empty when
        unknown."""
        svc = (getattr(self, "charger_service", "") or "").strip().lower()
        if "." in svc:
            brand = svc.split(".", 1)[0]
            if brand:
                return brand
        # Fallback: sniff entity ids / device name for a known brand token.
        blob = " ".join(
            x for x in (
                (getattr(self, "current_entity_id", "") or "").lower(),
                (getattr(self, "charger_service_entity_id", "") or "").lower(),
                (getattr(self, "name", "") or "").lower(),
            ) if x
        )
        for token in _BRAND_WATCHDOG_REFRESH_S:
            if token in blob:
                return token
        return ""

    @property
    def watchdog_refresh_interval_s(self) -> float:
        """Max seconds between identical writes before the charger's
        device-side failsafe watchdog may trip. ``_set_current`` re-writes the
        same value at this cadence to keep the watchdog fed (#392). Brand-aware:
        KEBA's failsafe needs a faster refresh than the generic default.
        ``_watchdog_refresh_override_s`` (set from config when present) wins, for
        unusual failsafe settings."""
        override = getattr(self, "_watchdog_refresh_override_s", None)
        if override:
            try:
                val = float(override)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
        return _BRAND_WATCHDOG_REFRESH_S.get(
            self._brand_key(), DEFAULT_WRITE_HEARTBEAT_INTERVAL_S,
        )

    @property
    def is_enabled(self) -> bool:
        """Return True if device is enabled for surplus control."""
        return self._enabled

    @property
    def managed_externally(self) -> bool:
        """When True, SurplusController skips this device (managed by coordinator directly)."""
        return self._managed_externally

    @managed_externally.setter
    def managed_externally(self, value: bool) -> None:
        self._managed_externally = value

    @property
    def status(self) -> DeviceStatus:
        """Return current device status."""
        return self._status

    # --- Power-change cooldown helpers ---

    def _is_power_change_allowed(self) -> bool:
        """Check if enough time has passed since last power change."""
        if self._min_power_change_interval <= 0:
            return True
        if self._last_power_change_time is None:
            return True
        elapsed = (datetime.now() - self._last_power_change_time).total_seconds()
        return elapsed >= self._min_power_change_interval

    def _record_power_change(self) -> None:
        """Record that a power change just occurred."""
        self._last_power_change_time = datetime.now()

    # --- Daily runtime tracking helpers ---

    def update_daily_runtime(self, meter_day: date) -> None:
        """Accumulate runtime if device is active. Called every coordinator cycle."""
        now = datetime.now()

        # Reset on meter day rollover
        if self._daily_runtime_meter_day is not None and meter_day != self._daily_runtime_meter_day:
            _LOGGER.debug(
                "%s: daily runtime reset (%.0fs) on meter day rollover",
                self.name, self._daily_runtime_accumulated_sec,
            )
            self._daily_runtime_accumulated_sec = 0.0
            self._daily_runtime_last_check = now
        self._daily_runtime_meter_day = meter_day

        # Don't accumulate the daily solar budget when SEM isn't managing the
        # device (Off): a device switched to Off while running would otherwise
        # keep counting minutes it no longer owns (#559 alex "Issue 6").
        _managed = self.control_mode != DeviceControlMode.OFF
        # (arc Phase 4) Credit runtime on OBSERVED reality, not just belief: a
        # load whose entity reads OFF isn't running, even while the reconciler's
        # 45s drift grace hasn't corrected the belief yet. Unobservable (None —
        # no control entity / entity unavailable) falls back to belief, so
        # devices without a readable entity behave exactly as before.
        _really_on = self.is_active and self.observed_on() is not False
        if self._daily_runtime_last_check is not None and _really_on and _managed:
            elapsed = (now - self._daily_runtime_last_check).total_seconds()
            if 0 < elapsed <= 120:  # ignore jumps > 120s (restart recovery)
                self._daily_runtime_accumulated_sec += elapsed

        if self.is_active:
            self.calibrate_rated_power()

        self._daily_runtime_last_check = now

    def observed_power_w(self) -> Optional[float]:
        """#600 — the device's live consumption in W: the power sensor if
        present and readable, else derived from an energy (kWh) counter, else
        None. A power sensor ALWAYS wins; the energy deriver is the fallback for
        kWh-only devices (e.g. Viessmann ViCare yearly counter)."""
        # #641 — this read did NO unit conversion at all. A heat-pump or
        # pool-pump power sensor reporting kW taught ``calibrate_rated_power`` a
        # ~3 W rated power, which collapses the activation threshold and makes
        # runtime-on-solar credit and shed decisions garbage, silently.
        if self.hass and self.power_entity_id:
            watts = power_state_to_watts(self.hass.states.get(self.power_entity_id))
            if watts is not None:
                return watts
        if self.hass and self.energy_entity_id:
            # Same gap on the energy side: a raw float went into
            # ``EnergyRateDeriver`` with no unit check, so a Wh counter derived
            # a 1000x power.
            energy = energy_state_to_kwh(self.hass.states.get(self.energy_entity_id))
            if self._energy_deriver is None:
                from ..coordinator.energy_rate_deriver import EnergyRateDeriver
                self._energy_deriver = EnergyRateDeriver()
            rated = getattr(self, "rated_power", None)
            cap = rated * 2 if rated else None
            return self._energy_deriver.update(energy, time.monotonic(), max_power_w=cap)
        return None

    def calibrate_rated_power(self) -> None:
        """(#559/#576) Learn the device's real draw from its power sensor.

        Runs every cycle while the device is ON: if the sensor reports a
        larger draw than the current ``rated_power``, adopt it as both the
        rated power and the surplus-activation threshold. Promoted from
        ``SwitchDevice`` to the base (#576) so EVERY device type — switch,
        heat pump, climate — "sees where it goes", not just switches.

        #600 — reads via ``observed_power_w`` so a kWh-only device (energy
        counter, no power sensor) still calibrates from its derived power.
        No-op for devices without any consumption signal or a ``rated_power``
        (e.g. the modulating EV, which measures draw its own way)."""
        rated = getattr(self, "rated_power", None)
        if rated is None or not self.hass or not self.is_active:
            return
        observed = self.observed_power_w()
        if observed is None:
            return
        if observed > self.rated_power:
            _LOGGER.info(
                "%s: calibrated rated_power %.0fW -> %.0fW from %s",
                self.name, self.rated_power, observed,
                self.power_entity_id or self.energy_entity_id,
            )
            self.rated_power = observed
            self.min_power_threshold = observed

    @property
    def remaining_daily_runtime_sec(self) -> float:
        """Seconds of runtime still needed to meet daily target."""
        return max(0, self.daily_min_runtime_sec - self._daily_runtime_accumulated_sec)

    @property
    def daily_max_runtime_reached(self) -> bool:
        """(#620) True when the device has hit its daily MAXIMUM runtime cap —
        it must not run again today. 0 = uncapped (never reached). The
        allocation passes exclude a capped device for the rest of the day."""
        if self.daily_max_runtime_sec <= 0:
            return False
        return self._daily_runtime_accumulated_sec >= self.daily_max_runtime_sec

    @property
    def has_runtime_deficit(self) -> bool:
        """Runtime target not yet met — **independent of whether the device is
        currently active**. This is the deficit that drives the overnight-battery
        and cheap-grid intents in the desired-state model: those sources must
        KEEP a running load on until the deficit closes, so they can't use the
        ``not is_active`` gate that ``needs_offpeak_activation`` carries."""
        if self.daily_min_runtime_sec <= 0:
            return False
        if not self._enabled:
            return False
        if self.daily_max_runtime_reached:  # (#620) cap overrides the deficit
            return False
        return self.remaining_daily_runtime_sec > 0

    @property
    def needs_offpeak_activation(self) -> bool:
        """True if device has a runtime deficit, is enabled, and not already
        active. The activation-side view of ``has_runtime_deficit``."""
        return self.has_runtime_deficit and not self.is_active

    # --- (#559) goal engine — grounded core (runtime target + stop condition) ---

    @property
    def daily_targets_met(self) -> bool:
        """Runtime minimum target achieved. No target configured = False —
        the stop condition is an independent gate, not a target.

        (#688) This is a FLOOR, not a stop. True means the PAID sources
        (battery assist, overnight battery drain, cheap-grid top-up) have
        nothing left to guarantee and stand down — free solar surplus may
        carry the load on up to ``daily_max_runtime_sec``, which is the only
        hard stop. Mirrors the EV floor/ceiling contract (#245). Do not
        re-wire this as a deactivation gate: that made any Max above the Min
        unreachable by construction.
        """
        if self.daily_min_runtime_sec <= 0:
            return False
        return self._daily_runtime_accumulated_sec >= self.daily_min_runtime_sec

    @property
    def stop_condition_met(self) -> bool:
        """(#559 Phase 3) external completion condition — e.g. the car's SOC
        sensor reached the target %. Unavailable sensor = condition NOT met
        (the surplus/target bounds still limit the device)."""
        if not self.stop_entity or self.stop_at <= 0 or not self.hass:
            return False
        state = self.hass.states.get(self.stop_entity)
        if not state or state.state in ("unknown", "unavailable", None):
            return False
        try:
            return float(state.state) >= self.stop_at
        except (ValueError, TypeError):
            return False

    def enable(self) -> None:
        """Enable device for surplus control."""
        self._enabled = True

    def disable(self) -> None:
        """Disable device from surplus control."""
        self._enabled = False

    @abstractmethod
    async def activate(self, available_watts: float) -> float:
        """Activate device with available surplus power.

        Args:
            available_watts: Power available for this device.

        Returns:
            Actual power consumed by the device (W).
        """

    @abstractmethod
    async def deactivate(self) -> None:
        """Deactivate the device."""

    @abstractmethod
    async def adjust_power(self, available_watts: float) -> float:
        """Adjust device power level (for variable-power devices).

        Args:
            available_watts: New power available for this device.

        Returns:
            Actual power consumed after adjustment (W).
        """

    def can_activate(self) -> bool:
        """Check if device can be activated (respects dependencies, min_off, activation_delay)."""
        # (#620) daily maximum cap — a capped-out device never re-activates
        # today. Gated first: it overrides surplus, off-peak and deadline
        # passes alike (the cap is a hard "done for today").
        if self.daily_max_runtime_reached:
            return False
        # Dependency check (#122): all depends_on devices must be in required state
        if not self._check_dependencies():
            return False
        # (arc) Respect a recent EXTERNAL off — if the user (or another
        # automation) just turned this load off, don't immediately turn it back
        # on and fight them. The DeviceReconciler sets this window when it sees
        # a SEM-active load go off at the entity.
        if self._external_off_until and datetime.now() < self._external_off_until:
            return False
        if self.min_off_seconds > 0 and self._last_deactivated:
            elapsed = (datetime.now() - self._last_deactivated).total_seconds()
            if elapsed < self.min_off_seconds:
                return False
        # Sustained surplus check: surplus must persist for activation_delay_seconds
        if self.activation_delay_seconds > 0:
            if self._surplus_since is None:
                self._surplus_since = datetime.now()
                return False
            elapsed = (datetime.now() - self._surplus_since).total_seconds()
            if elapsed < self.activation_delay_seconds:
                return False
        return True

    def _check_dependencies(self) -> bool:
        """Check if all dependency constraints are satisfied (#122)."""
        if not self.depends_on or not self._controller:
            return True
        for dep_id in self.depends_on:
            dep_device = self._controller.get_device(dep_id)
            if dep_device is None:
                continue  # Unknown device — don't block
            dep_active = dep_device.status.state == DeviceState.ACTIVE
            if self.dependency_mode == "must_active" and not dep_active:
                return False
            if self.dependency_mode == "must_inactive" and dep_active:
                return False
        return True

    @property
    def blocked_by_dependency(self) -> Optional[str]:
        """Return the device_id blocking this device, or None if not blocked."""
        if not self.depends_on or not self._controller:
            return None
        for dep_id in self.depends_on:
            dep_device = self._controller.get_device(dep_id)
            if dep_device is None:
                continue
            dep_active = dep_device.status.state == DeviceState.ACTIVE
            if self.dependency_mode == "must_active" and not dep_active:
                return dep_id
            if self.dependency_mode == "must_inactive" and dep_active:
                return dep_id
        return None

    def reset_surplus_timer(self) -> None:
        """Reset surplus timer when surplus drops below device threshold."""
        self._surplus_since = None

    def can_deactivate(self) -> bool:
        """Check if device can be deactivated (respects min_on_seconds)."""
        if self.min_on_seconds > 0 and self._last_activated:
            elapsed = (datetime.now() - self._last_activated).total_seconds()
            if elapsed < self.min_on_seconds:
                return False
        return True

    def record_activated(self) -> None:
        """Record activation timestamp for anti-cycling."""
        self._last_activated = datetime.now()
        # (arc) SEM turned this on → SEM owns the on-state.
        self._sem_owned = True
        self._observed_off_since = None

    def record_deactivated(self) -> None:
        """Record deactivation timestamp for anti-cycling."""
        self._last_deactivated = datetime.now()
        self._sem_owned = False
        self._observed_off_since = None

    def mark_reconciled_off(self, cooldown_until: "Optional[datetime]" = None) -> None:
        """(arc) The reconciler observed this SEM-active load is physically OFF.

        Flip the internal belief to IDLE **without** issuing a service call (the
        load is already off), clear ownership + the drift anchor, stamp the
        anti-flicker timer, and optionally hold a re-activate cooldown so SEM
        doesn't immediately fight a user's manual off.
        """
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0
        # Stamp BOTH deactivation clocks: the base one (min_on / can_deactivate)
        # and the DeviceStatus one that Switch/Climate ``activate()`` read for
        # their own min_off anti-flicker — so re-activation is gated even on a
        # path that skips can_activate().
        now = datetime.now()
        self._last_deactivated = now
        self._status.last_deactivated = now
        self._sem_owned = False
        self._observed_off_since = None
        if cooldown_until is not None:
            self._external_off_until = cooldown_until

    def observed_on(self):
        """(arc) The device's observed on/off state from HA, or None when it
        can't be read (no control entity, or unavailable/unknown).

        On/off loads use the control entity's state; a ``climate`` entity is
        "on" whenever its hvac_mode is not ``off``. Returning None means "don't
        know" — the reconciler leaves the belief untouched rather than guessing.
        """
        if not self.entity_id or not self.hass:
            return None
        state = self.hass.states.get(self.entity_id)
        if not state or state.state in ("unavailable", "unknown", None):
            return None
        s = str(state.state).lower()
        if s == "off":
            return False
        if s == "on":
            return True
        # climate.* and water_heater.* report their active MODE as the state
        # string (e.g. "heat", "cool", "eco", "heat_pump") — anything but "off"
        # means running. Don't add per-domain guards here; ClimateDevice
        # overrides observed_on() where mode-matching matters.
        return True

    def get_current_consumption(self) -> float:
        """Get current power consumption in W from HA entity or estimate."""
        if self.power_entity_id:
            # #641 — unit-aware; this copy had no conversion either.
            watts = power_state_to_watts(self.hass.states.get(self.power_entity_id))
            if watts is not None:
                return watts
        return self._status.current_consumption_w

    @property
    def desired_state(self) -> str:
        """(arc Phase 3) SEM's intent for this device, as an explicit model.

        - ``off``  — SEM never drives it (control_mode = off)
        - ``on``   — SEM wants it drawing (it's active under SEM management)
        - ``idle`` — SEM is not allocating to it right now

        Formalizes the OFF / IDLE / ON trichotomy the EV reconciler uses, for
        the card and diagnostics — so "why is this load on?" is answerable.
        """
        if self.control_mode == DeviceControlMode.OFF:
            return "off"
        return "on" if (self.is_active and self._sem_owned) else "idle"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize device info for sensors/diagnostics."""
        obs = self.observed_on()
        d = {
            "device_id": self.device_id,
            "name": self.name,
            "type": self.device_type.value,
            "priority": self.priority,
            "min_power_threshold": self.min_power_threshold,
            "state": self._status.state.value,
            "current_consumption_w": self._status.current_consumption_w,
            "allocated_power_w": self._status.allocated_power_w,
            "enabled": self._enabled,
            "activation_count": self._status.activation_count,
            # (arc Phase 3) intent + reality + ownership, for the card and
            # field debugging: is it on because SEM wants it on, or externally?
            "desired_state": self.desired_state,
            "observed_on": obs,
            "sem_owned": self._sem_owned,
        }
        if (self.daily_min_runtime_sec > 0 or self.daily_max_runtime_sec > 0
                or self.battery_assist_enabled or self.battery_eligible_overnight):
            d.update({
                "daily_min_runtime_sec": self.daily_min_runtime_sec,
                "daily_runtime_accumulated_sec": round(self._daily_runtime_accumulated_sec, 1),
                "top_up_policy": self.top_up_policy,
                "remaining_daily_runtime_sec": round(self.remaining_daily_runtime_sec, 1),
                "offpeak_forced": self._offpeak_forced,
                # (#620) max cap + battery tiers — surfaced for the card + the
                # allocation, and PERSISTED (the max cap is restored across a
                # restart, closing the #559 HIGH-1 un-persisted-cap bug).
                "daily_max_runtime_sec": self.daily_max_runtime_sec,
                "daily_max_runtime_reached": self.daily_max_runtime_reached,
                "battery_assist_enabled": self.battery_assist_enabled,
                "battery_eligible_overnight": self.battery_eligible_overnight,
            })
        # Dependency info (#122)
        if self.depends_on:
            d["depends_on"] = self.depends_on
            d["dependency_mode"] = self.dependency_mode
            blocked = self.blocked_by_dependency
            d["blocked_by"] = blocked
        return d


class ComfortBandMixin:
    """(#705) The thermal comfort band, shared by every device class that
    can hold a room at a temperature — ClimateDevice (Phase 1) and
    SwitchDevice heaters (Phase 2).

    A MIXIN rather than per-class copies on purpose: the one-mode-fixed /
    siblings-left-blind shape is this codebase's most-repeated bug class,
    and a band duplicated into SwitchDevice would drift the first time a
    fix lands in one copy.

    Subclass hooks:
    - ``_comfort_direction()`` — "cool" or "heat". Default heat (switch
      loads are heaters; a switch-driven cooler is follow-up work).
      ClimateDevice derives it from ``hvac_mode``.
    - ``_comfort_fallback_reading()`` — a thermometer of last resort when
      no ``comfort_entity`` is configured. Default None (a relay has
      nothing to fall back to); ClimateDevice reads its entity's own
      ``current_temperature``.
    """

    # Class-level defaults: a device that never received comfort goals
    # carries a disengaged band instead of AttributeErrors.
    comfort_entity: str = ""
    comfort_target: float = 0.0
    comfort_offset: float = 0.0
    comfort_limit: float = 0.0

    def _comfort_direction(self) -> str:
        return "heat"

    def _comfort_fallback_reading(self):
        return None

    def _install_unit_is_f(self) -> bool:
        """True when the install's display unit is Fahrenheit.

        Exact °F spellings only — anything unrecognised is assumed °C,
        the same contract as temperature_state_to_celsius. A substring
        test here once classified a mock repr as Fahrenheit.
        """
        try:
            unit = str(getattr(getattr(self.hass.config, "units", None),
                               "temperature_unit", "") or "").strip()
        except Exception:  # noqa: BLE001 — unit lookup must never kill the band
            unit = ""
        return unit in ("°F", "F", "fahrenheit", "Fahrenheit")

    def _comfort_thresholds_c(self):
        """(target, offset, limit) in °C.

        The user TYPES the thresholds in the install's display unit —
        HA's own convention for every temperature input; a °F user must
        never be asked to think in °C. Comparison happens in °C because
        the readings are normalised there. The offset is a temperature
        DIFFERENCE and converts linearly (Δ°F × 5/9); converting it
        affinely like the absolute temperatures would shift the banked
        bound by −17.8 °C.
        """
        t, o, l = self.comfort_target, self.comfort_offset, self.comfort_limit
        if self._install_unit_is_f():
            return ((t - 32.0) * 5.0 / 9.0,
                    o * 5.0 / 9.0,
                    (l - 32.0) * 5.0 / 9.0)
        return (t, o, l)

    def _comfort_reading(self):
        """The room temperature in °C, or None.

        An explicit ``comfort_entity`` reads that sensor's state (its own
        unit_of_measurement decides the conversion — the #727 contract);
        without one the subclass fallback answers, if it has one.
        """
        if not self.hass:
            return None
        if self.comfort_entity:
            state = self.hass.states.get(self.comfort_entity)
            if state is None:
                return None
            from ..coordinator.units import temperature_state_to_celsius
            return temperature_state_to_celsius(state, None)
        return self._comfort_fallback_reading()

    @property
    def comfort_state(self) -> str:
        """forced / willing / banked / disengaged.

        Direction from ``_comfort_direction()``: cool forces ABOVE the
        limit and banks down to target − offset; heat is the mirror.
        Boundary readings count as crossed. DISENGAGED — fields unset,
        thermometer silent, or a band on the wrong side of its target —
        behaves byte-for-byte like a device without a band: a dead
        sensor never forces a run and never parks the device.
        """
        if not (self.comfort_target and self.comfort_limit):
            return "disengaged"
        cooling = self._comfort_direction() == "cool"
        if ((cooling and self.comfort_limit <= self.comfort_target)
                or (not cooling and self.comfort_limit >= self.comfort_target)):
            if not getattr(self, "_comfort_misconfig_warned", False):
                self._comfort_misconfig_warned = True
                _LOGGER.warning(
                    "%s: comfort band misconfigured (direction=%s target=%.1f "
                    "limit=%.1f) — cool needs limit > target, heat needs "
                    "limit < target; band disengaged",
                    self.name, "cool" if cooling else "heat",
                    self.comfort_target, self.comfort_limit,
                )
            return "disengaged"
        temp = self._comfort_reading()
        if temp is None:
            return "disengaged"
        target_c, offset_c, limit_c = self._comfort_thresholds_c()
        if cooling:
            if temp >= limit_c:
                return "forced"
            if temp <= target_c - offset_c:
                return "banked"
        else:
            if temp <= limit_c:
                return "forced"
            if temp >= target_c + offset_c:
                return "banked"
        return "willing"

    # The band speaks through the three generic properties every surplus
    # pass already reads — no new controller clauses; peak shed,
    # anti-cycling, priority and LIFO apply to comfort runs unchanged.

    @property
    def has_runtime_deficit(self) -> bool:
        """FORCED reads as a deficit ⇒ the deficit-driven paid passes
        engage exactly per the user's #620 source-axis opt-ins. The daily
        max cap outranks the force: a unit that has run its configured
        maximum is done, breach or no breach."""
        if super().has_runtime_deficit:
            return True
        if self.daily_max_runtime_reached:
            return False
        return self._enabled and self.comfort_state == "forced"

    @property
    def stop_condition_met(self) -> bool:
        """BANKED reads as the stop condition ⇒ surplus stops feeding a
        room already conditioned past target ∓ offset. ORs with the
        existing ``stop_entity`` override — they compose."""
        if super().stop_condition_met:
            return True
        return self.comfort_state == "banked"

    @property
    def daily_targets_met(self) -> bool:
        """A met runtime floor must NOT stand the paid sources down while
        comfort is breached — the floor is about runtime, the breach is
        about now."""
        if self.comfort_state == "forced":
            return False
        return super().daily_targets_met


class SwitchDevice(ComfortBandMixin, ControllableDevice):
    """On/off device (hot water relay, smart plugs, etc.).

    When surplus >= min_power_threshold, the switch is turned on.
    When surplus drops, the switch is turned off.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        min_on_time: int = 300,
        # (#688) 300 s (was 60): a deferrable load like a pool pump should not be
        # re-startable a minute after it stopped. With min_on also 300 s this caps
        # cycling at a ~10-min period and lets min_on hold the load through a
        # passing cloud instead of stopping. Overridden per-load via the
        # min_off_time_min goal; subclasses (hot water) pass their own.
        min_off_time: int = 300,
        daily_min_runtime_sec: int = 0,
        daily_max_runtime_sec: int = 0,        # (#620) 0 = uncapped
        battery_assist_enabled: bool = False,  # (#620) Tier 1 — Solar + battery
        battery_eligible_overnight: bool = False,  # (#620) Tier 2 — overnight
        energy_entity_id: Optional[str] = None,
    ):
        # (#576) 1 kW default for a sensor-less / discovery-zero switch: a saner
        # floor than 0 W (which left the activation threshold tiny, so the
        # switch turned on at any surplus and imported the rest from grid).
        # When a power sensor IS present, calibrate_rated_power() learns the
        # real draw and snaps up from here.
        rp = rated_power if (rated_power and rated_power > 0) else DEFAULT_DEVICE_RATED_POWER
        super().__init__(
            hass, device_id, name, priority,
            min_power_threshold or rp,
            entity_id, power_entity_id,
            energy_entity_id=energy_entity_id,
        )
        self.rated_power = rp
        # (#644) ONE anti-cycle mechanism: the legacy min_on_time/min_off_time
        # knobs map onto the base-layer min_on_seconds/min_off_seconds, whose
        # epochs (_last_activated/_last_deactivated) are rebuild-transplanted
        # (#620 _VOLATILE_CONTROL_FIELDS). Pre-#644 the subclasses kept a
        # SECOND clock on _status.last_* — wiped on every rediscovery rebuild,
        # so a compressor could short-cycle 20 s after stopping.
        self.min_on_seconds = int(min_on_time)
        self.min_off_seconds = int(min_off_time)
        self.daily_min_runtime_sec = daily_min_runtime_sec
        self.daily_max_runtime_sec = daily_max_runtime_sec
        self.battery_assist_enabled = battery_assist_enabled
        self.battery_eligible_overnight = battery_eligible_overnight

    @property
    def min_on_time(self) -> int:
        """(#644) alias of the unified anti-cycle knob."""
        return self.min_on_seconds

    @min_on_time.setter
    def min_on_time(self, v: int) -> None:
        self.min_on_seconds = int(v)

    @property
    def min_off_time(self) -> int:
        """(#644) alias of the unified anti-cycle knob."""
        return self.min_off_seconds

    @min_off_time.setter
    def min_off_time(self, v: int) -> None:
        self.min_off_seconds = int(v)

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SWITCH

    def adopt_if_running(self) -> bool:
        """(#559) Re-own a switch that is physically ON at (re-)registration.

        After an HA restart SEM's internal state is IDLE while the switch
        it turned on is still ON — orphaned: no goal gate, force expiry or
        surplus logic would ever stop it. Adopting it as ACTIVE puts it
        back under normal control (and its runtime counts again).
        """
        if not self.entity_id or not self.hass or self.is_active:
            return False
        state = self.hass.states.get(self.entity_id)
        if not state or state.state != "on":
            return False
        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        self._status.last_activated = datetime.now()
        self._last_activated = self._status.last_activated  # (#644) unified clock
        self._sem_owned = True  # (arc) re-own on restart → SEM manages it
        _LOGGER.info(
            "%s: switch %s was ON at registration — re-owned as active",
            self.name, self.entity_id,
        )
        return True

    async def activate(self, available_watts: float) -> float:
        if not self.entity_id:
            return 0.0

        # Anti-flicker: minimum off time — the UNIFIED clock (#644): the
        # base-layer epoch survives rediscovery rebuilds via the transplant.
        if self._last_deactivated:
            elapsed = (datetime.now() - self._last_deactivated).total_seconds()
            if elapsed < self.min_off_seconds:
                return 0.0

        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_on",
                {"entity_id": self.entity_id},
                blocking=True,
            )
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            self._status.last_activated = datetime.now()
            self._last_activated = self._status.last_activated  # (#644) unified clock
            self._status.activation_count += 1
            _LOGGER.info("Activated switch device %s (%dW)", self.name, self.rated_power)
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to activate %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

    async def deactivate(self) -> None:
        if not self.entity_id:
            return

        # Anti-flicker: minimum on time — the UNIFIED clock (#644).
        if self._last_activated:
            elapsed = (datetime.now() - self._last_activated).total_seconds()
            if elapsed < self.min_on_seconds:
                return

        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_off",
                {"entity_id": self.entity_id},
                blocking=True,
            )
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._status.allocated_power_w = 0.0
            self._status.last_deactivated = datetime.now()
            self._last_deactivated = self._status.last_deactivated  # (#644) unified clock
            _LOGGER.info("Deactivated switch device %s", self.name)
        except Exception as e:
            _LOGGER.error("Failed to deactivate %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)

    async def adjust_power(self, available_watts: float) -> float:
        # Switch devices are on/off only - no adjustment possible
        if self.is_active:
            return self.rated_power
        return 0.0


class ClimateDevice(ComfortBandMixin, ControllableDevice):
    """On/off surplus control for a ``climate.*`` entity (#569).

    An air-conditioner / heat pump exposed only as a ``climate.*`` entity has
    no switch to flip and no ``number`` to write — you drive it with
    ``climate.set_hvac_mode`` and ``climate.set_temperature``. This is the
    on/off analog of :class:`SwitchDevice` for such units:

    - surplus available → set the configured ``hvac_mode`` (e.g. ``cool``) and,
      if given, a comfort ``target_temperature`` — i.e. turn the unit ON;
    - surplus drops → ``hvac_mode: off`` — turn the unit OFF.

    The active ``hvac_mode`` is configurable, so one type covers AC-cooling
    (``cool``) and heating (``heat`` / ``heat_cool``). Unlike
    :class:`SetpointDevice` (which only nudges a heat-pump setpoint and never
    turns the unit off), this drives real on/off load shifting and so slots
    into the priority / peak-shed / daily-goal machinery like a switch.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        hvac_mode: str = "cool",
        target_temperature: Optional[float] = None,
        min_on_time: int = 300,
        min_off_time: int = 60,
        daily_min_runtime_sec: int = 0,
        daily_max_runtime_sec: int = 0,        # (#620) 0 = uncapped
        battery_assist_enabled: bool = False,  # (#620) Tier 1 — Solar + battery
        battery_eligible_overnight: bool = False,  # (#620) Tier 2 — overnight
        energy_entity_id: Optional[str] = None,
        comfort_entity: str = "",          # (#705) temp sensor; "" = the
        comfort_target: float = 0.0,       # climate entity's own thermometer
        comfort_offset: float = 0.0,
        comfort_limit: float = 0.0,        # 0.0 = band disabled — a true 0 °C
                                           # threshold needs 0.1 (sentinel)
    ):
        super().__init__(
            hass, device_id, name, priority,
            min_power_threshold or rated_power,
            entity_id, power_entity_id,
            energy_entity_id=energy_entity_id,
        )
        self.rated_power = rated_power
        self.hvac_mode = hvac_mode or "cool"
        self.target_temperature = target_temperature
        # (#644) unified anti-cycle knobs (see SwitchDevice)
        self.min_on_seconds = int(min_on_time)
        self.min_off_seconds = int(min_off_time)  # routes via the property below
        self.daily_min_runtime_sec = daily_min_runtime_sec
        self.daily_max_runtime_sec = daily_max_runtime_sec
        self.battery_assist_enabled = battery_assist_enabled
        self.battery_eligible_overnight = battery_eligible_overnight
        # (#705) thermal comfort band — the HotWaterController three-
        # temperature pattern (min/solar-target/max), generalized and
        # mirrored for cooling. target+limit both set AND a live reading
        # = engaged; anything less = disengaged = pre-#705 behaviour.
        self.comfort_entity = comfort_entity or ""
        self.comfort_target = float(comfort_target or 0.0)
        self.comfort_offset = float(comfort_offset or 0.0)
        self.comfort_limit = float(comfort_limit or 0.0)

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.CLIMATE

    # (#705) Compressor guard: while the comfort band is engaged, the
    # off→on gap is floored at 180 s regardless of the configured window.
    # The band makes cycling TEMPERATURE-driven — sharp edges at
    # target − offset — and the #569 default of 60 s is below the safe
    # restart floor for compressor head-pressure equalisation. The
    # configured value still wins when it is stricter, and a disengaged
    # band keeps the configured window untouched. CLIMATE-ONLY: resistive
    # switch heaters (Phase 2) cycle safely and keep their own window.
    _COMFORT_MIN_OFF_FLOOR_S = 180

    @property
    def min_off_seconds(self) -> int:
        base = int(getattr(self, "_min_off_configured", 60))
        if self.comfort_state != "disengaged":
            return max(base, self._COMFORT_MIN_OFF_FLOOR_S)
        return base

    @min_off_seconds.setter
    def min_off_seconds(self, value) -> None:
        self._min_off_configured = int(value)

    def _comfort_direction(self) -> str:
        return "cool" if self.hvac_mode == "cool" else "heat"

    def _comfort_fallback_reading(self):
        """Zero-config thermometer: the climate entity's own
        ``current_temperature``. The attribute carries no unit — it is in
        the install's display unit, so conversion follows
        ``hass.config.units``; anything unrecognised is assumed °C."""
        if not self.entity_id:
            return None
        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None
        raw = (state.attributes or {}).get("current_temperature")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if self._install_unit_is_f():
            return (value - 32.0) * 5.0 / 9.0
        return value

    def adopt_if_running(self) -> bool:
        """(#559) Re-own a climate unit that SEM is running at (re-)registration.

        After a restart SEM's internal state is IDLE while the AC it turned on
        is still cooling. A climate entity reports its active mode as the
        state (``cool``/``heat``/…), or ``off`` when idle.

        We only adopt when the entity's state matches **our** configured
        ``hvac_mode`` — i.e. the unit is running in the mode SEM would have set.
        A unit the user has manually put into a *different* mode (e.g. ``heat``
        while we manage ``cool``) is left alone: adopting it would let a later
        ``deactivate()`` send ``hvac_mode: off`` and kill the user's manual run.
        """
        if not self.entity_id or not self.hass or self.is_active:
            return False
        state = self.hass.states.get(self.entity_id)
        if not state or state.state != self.hvac_mode:
            return False
        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        self._status.last_activated = datetime.now()
        self._last_activated = self._status.last_activated  # (#644) unified clock
        self._sem_owned = True  # (arc) re-own on restart → SEM manages it
        _LOGGER.info(
            "%s: climate %s was %s at registration — re-owned as active",
            self.name, self.entity_id, state.state,
        )
        return True

    def observed_on(self):
        """(arc) A climate unit counts as "on" for reconciliation only when it's
        in the mode SEM drives it in. A user switching it to a *different* active
        mode (SEM=cool → user picks heat/fan) reads as OFF from SEM's view, so
        the reconciler stops crediting SEM's goal and won't fight the manual
        change — mirroring adopt_if_running's ``state == hvac_mode`` check."""
        if not self.entity_id or not self.hass:
            return None
        state = self.hass.states.get(self.entity_id)
        if not state or state.state in ("unavailable", "unknown", None):
            return None
        return str(state.state).lower() == str(self.hvac_mode).lower()

    async def activate(self, available_watts: float) -> float:
        if not self.entity_id:
            return 0.0

        # Anti-flicker: minimum off time — the UNIFIED clock (#644): the
        # base-layer epoch survives rediscovery rebuilds via the transplant.
        if self._last_deactivated:
            elapsed = (datetime.now() - self._last_deactivated).total_seconds()
            if elapsed < self.min_off_seconds:
                return 0.0

        # Set the mode first. If THIS fails the unit never turned on — report
        # ERROR and bail.
        try:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": self.entity_id, "hvac_mode": self.hvac_mode},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.error("Failed to activate %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

        # The mode is committed — the unit is now ON. Mark ACTIVE *before* the
        # optional setpoint write so a set_temperature failure can't leave us
        # thinking the unit is idle (which would re-issue set_hvac_mode every
        # cycle — the unit would run uncontrolled). B1.
        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        self._status.last_activated = datetime.now()
        self._last_activated = self._status.last_activated  # (#644) unified clock
        self._status.activation_count += 1

        if self.target_temperature is not None:
            try:
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": self.entity_id,
                     "temperature": self.target_temperature},
                    blocking=True,
                )
            except Exception as e:
                # Non-fatal: the unit is running in the right mode, only the
                # comfort setpoint didn't take. Stay ACTIVE.
                _LOGGER.warning(
                    "%s: set hvac_mode but not target temperature: %s",
                    self.name, e,
                )

        if self.target_temperature is not None:
            _LOGGER.info(
                "Activated climate device %s → %s @ %.1f°C (%dW)",
                self.name, self.hvac_mode, self.target_temperature,
                self.rated_power,
            )
        else:
            _LOGGER.info(
                "Activated climate device %s → %s (%dW)",
                self.name, self.hvac_mode, self.rated_power,
            )
        return self.rated_power

    async def deactivate(self) -> None:
        if not self.entity_id:
            return

        # Anti-flicker: minimum on time — the UNIFIED clock (#644).
        if self._last_activated:
            elapsed = (datetime.now() - self._last_activated).total_seconds()
            if elapsed < self.min_on_seconds:
                return

        try:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": self.entity_id, "hvac_mode": "off"},
                blocking=True,
            )
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._status.allocated_power_w = 0.0
            self._status.last_deactivated = datetime.now()
            self._last_deactivated = self._status.last_deactivated  # (#644) unified clock
            _LOGGER.info("Deactivated climate device %s", self.name)
        except Exception as e:
            _LOGGER.error("Failed to deactivate %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)

    async def adjust_power(self, available_watts: float) -> float:
        # Climate devices are on/off only — no proportional adjustment.
        if self.is_active:
            return self.rated_power
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "hvac_mode": self.hvac_mode,
            "target_temperature": self.target_temperature,
        })
        return d


class CurrentControlDevice(ControllableDevice):
    """Variable-current device (EV chargers).

    Power is proportionally adjusted based on available surplus.
    Supports multi-phase charging with configurable current limits.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        priority: int = 5,
        min_current: float = 6.0,
        max_current: float = 32.0,
        phases: int = 3,
        voltage: float = 230.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        current_entity_id: Optional[str] = None,
        charger_service: Optional[str] = None,
        charger_service_entity_id: Optional[str] = None,
        min_power_change_interval: float = 30.0,
    ):
        min_power = min_current * phases * voltage
        super().__init__(
            hass, device_id, name, priority, min_power,
            entity_id, power_entity_id,
        )
        self.min_current = min_current
        self.max_current = max_current
        self.phases = phases
        self.voltage = voltage
        self.current_entity_id = current_entity_id
        # #523 (RienduPre): a valid HA service is always ``domain.service``.
        # A junk value with no dot (his Wallbox config carried a stray
        # ``charger_service='0'`` — a leftover that even propagated to a
        # sibling whose own config was None) used to reach the service
        # branch and crash ``domain, service = charger_service.split('.', 1)``
        # with "not enough values to unpack" on EVERY 10 s cycle, blocking
        # current control even though a perfectly good ``current_entity_id``
        # number was configured. Treat a dot-less service as absent so
        # control correctly falls through to the number entity. Guards all
        # three split sites (set_current / start / stop) at once.
        if isinstance(charger_service, str) and "." not in charger_service:
            if charger_service.strip():
                _LOGGER.warning(
                    "%s: ignoring invalid charger_service %r (not a "
                    "'domain.service') — using entity control instead",
                    name, charger_service,
                )
            charger_service = None
        self.charger_service = charger_service
        self.charger_service_entity_id = charger_service_entity_id
        # #546 — failsafe handling (managed-neutralize, default). SEM arms a
        # LONG non-tripping failsafe that overwrites the box's short built-in one
        # (which can't be disabled over UDP on a real P30). Set False
        # (``keba_arm_failsafe``) for boxes that CAN disable it at the charger
        # (evcc-style) — then a Repair guides the user. ``steady_failsafe``
        # (default on) controls persistence of the managed failsafe.
        self.arm_failsafe_enabled: bool = True
        self.steady_failsafe: bool = True
        # #546 — HA entity reporting the LIVE offered current (e.g.
        # sensor.keba_p30_max_current). Service-controlled chargers (KEBA) have
        # no in-SEM live-offer value — ``max_current`` is the static config cap.
        # Plumbed from the ``ev_current_sensor`` config; read by the
        # EV-OFFER-PROBE (observe-only). "" = no live source (probe shows "?").
        self.current_sensor_entity_id: str = ""
        # #548 — HA entity reporting the charger's STATUS enum (e.g.
        # sensor.wallbox_pulsar_status). For status-rich chargers (Wallbox)
        # this is authoritative for "is it actually charging?" — the cloud
        # power reading lags ~90 s, so a power-only ``actual_charging`` makes
        # the reconciler wrongly read "converged" and stop re-issuing the
        # stop (OFF mode never takes). The adapter reads this enum directly.
        # Plumbed from the ``ev_charging_sensor`` config; "" = power-only.
        self.charging_status_entity: str = ""
        self.service_param_name: str = "current"  # Overridden per integration (#82)
        self.service_device_id: Optional[str] = None  # For Easee/Zaptec device_id
        self.needs_pilot_cycle: bool = False  # True = disable/enable cycle for session start
        self.global_services: bool = True  # True = services don't need entity_id (KEBA-style)
        # Start/stop control — per-integration (#82)
        # Entities: switch/button/select entity_ids for start/stop
        self.start_stop_entity: Optional[str] = None  # switch or button entity
        self.charge_mode_entity: Optional[str] = None  # select entity (go-e, OpenWB)
        self.charge_mode_start: Optional[str] = None  # select option for "start"
        self.charge_mode_stop: Optional[str] = None  # select option for "stop"
        # Service-based start/stop (Easee action_command)
        self.start_service: Optional[str] = None  # e.g. "easee.action_command"
        self.start_service_data: Optional[Dict] = None  # e.g. {"action_command": "resume"}
        self.stop_service: Optional[str] = None
        self.stop_service_data: Optional[Dict] = None
        self._current_setpoint: float = 0.0
        # #392: monotonic timestamp of the last successful write to the
        # device's current-control surface. Used by _set_current to decide
        # whether to skip a same-value write (recent) or force a heartbeat
        # refresh (interval elapsed).
        self._last_write_at: float = 0.0
        # #462 follow-up: consecutive set-current failures → Repair issue
        # at 3 (cleared on the next successful write).
        self._actuation_failures: int = 0
        self._actuation_repair_raised: bool = False
        # #485 H5: whether this instance has cleared a possible STALE
        # persistent Repair left by a previous device instance.
        self._stale_repair_checked: bool = False
        self._session_active: bool = False
        # #553 — SEM's belief that the KEBA runaway-cap energy target is
        # armed (set by stop_session, cleared by start_session). Surfaced in
        # the diagnose service's ev_actuation block.
        self._idle_guard_armed: bool = False
        self._min_power_change_interval = min_power_change_interval

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.CURRENT_CONTROL

    def can_stop_charging(self) -> bool:
        """Whether SEM has ANY mechanism that can actually open the contactor.

        #627. ``stop_session`` walks four brand mechanisms and, if none is
        configured, falls through to ``_set_current(0)`` — and its warning
        says so ("relying on _set_current(0) alone"). But #487 taught
        ``_set_current`` to SKIP the write when the control number's own
        ``min`` is above 0, because HA core rejects out-of-range writes:
        "the actual stop is the adapter's job". Each layer defers to the
        other, so on a charger configured with *only* a ``number.*`` current
        entity whose min is 6 A, **nothing stops it at all**. onkelfu's
        install commanded STOP 130 consecutive times while the car pulled
        4.1 kW — 3.5 kW of it out of the house batteries — and SEM logged a
        warning at counts 3, 12 and 60, then went quiet.

        A capability that is asserted rather than checked is the same shape
        as the bug: the reconciler believed the stop was taking because
        nothing told it otherwise. So the capability is computed here, from
        the same fields ``stop_session`` actually dispatches on, and the
        reconciler surfaces it instead of counting.
        """
        if self.stop_service:
            return True
        if self.charge_mode_entity and self.charge_mode_stop:
            return True
        if self.start_stop_entity:
            return True
        if self.charger_service:
            domain = str(self.charger_service).split(".", 1)[0]
            try:
                if self.hass.services.has_service(domain, "disable"):
                    return True
            except Exception:  # noqa: BLE001 — capability probe, never raise
                pass
        # Last resort: a 0 A write, which only stops the car if the control
        # entity can express 0. ``_bound_to_entity_range`` returns the
        # skip-flag for exactly that question.
        entity = self.current_entity_id or self.charger_service_entity_id
        if not entity:
            return False
        try:
            _bounded, skip = self._bound_to_entity_range(entity, 0)
        except Exception:  # noqa: BLE001
            return True  # unknown → don't cry wolf
        return not skip

    # Dynamic 1p/3p phase switching lived here until #659:
    # ``check_phase_switch`` + ``_set_phases``, plus the ``min_phases`` /
    # ``max_phases`` / ``phase_switch_entity`` / hysteresis fields. The
    # implementation looked complete — switch- and number-entity actuation,
    # up/down hysteresis, min_power_threshold recomputation — and it could
    # never run, dead on two independent axes:
    #
    #   * No production caller. The only one there ever was, the legacy
    #     ``_execute_ev_control``, was deleted as dead in 561e28a
    #     (2026-06-22), which also removed the method's unit tests. What
    #     remained were two ``AsyncMock`` assignments in test fixtures.
    #   * No way to configure it. ``phase_switch_entity`` was written
    #     nowhere outside this file — not in config_flow.py, __init__.py,
    #     services.yaml or the config card. It was always None, so the very
    #     first line returned early even if something had called it.
    #
    # This is the #219-shaped trap: a contributor answering a go-e/Wattpilot
    # 1p/3p request finds working-looking code, adds only the config key, and
    # ships switching that still never runs.
    #
    # To actually implement it: add the config key, call it from the live EV
    # actuation path (charger_adapters / ev_control), and test the
    # interplay with ``min_power_threshold`` — changing phases changes the
    # charger's minimum, which the budget logic reads. ``self.phases``,
    # ``watts_to_current`` and ``current_to_watts`` below are the live
    # surface and are unaffected.

    def watts_to_current(self, watts: float) -> float:
        """Convert watts to amperes."""
        return watts / (self.phases * self.voltage)

    def current_to_watts(self, current: float) -> float:
        """Convert amperes to watts."""
        return current * self.phases * self.voltage

    async def activate(self, available_watts: float) -> float:
        target_current = min(
            self.max_current,
            max(self.min_current, self.watts_to_current(available_watts))
        )
        return await self._set_current(target_current)

    async def deactivate(self) -> None:
        await self._set_current(0)
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0
        self._current_setpoint = 0.0
        self._last_write_at = 0.0  # #392: reset heartbeat tracker on full stop

    async def adjust_power(self, available_watts: float) -> float:
        if not self.is_active:
            return 0.0
        # Cooldown: skip adjustment if interval hasn't elapsed
        if not self._is_power_change_allowed():
            return self._status.current_consumption_w
        target_current = min(
            self.max_current,
            max(self.min_current, self.watts_to_current(available_watts))
        )
        return await self._set_current(target_current)

    def _bound_to_entity_range(
        self, entity_id: str, current: float,
    ) -> tuple:
        """Bound a current command to the target number entity's range.

        Returns ``(bounded_current, skip_write)``. ``skip_write`` is
        True for a stop intent (``current <= 0``) on an entity whose
        minimum is above 0 — the write would be rejected by HA core's
        range validation before reaching the charger (#487), so the
        caller must rely on the adapter's stop mechanism instead.
        Unreadable entities/attributes leave the command untouched.
        """
        state = self.hass.states.get(entity_id) if entity_id else None
        attrs = getattr(state, "attributes", None)
        if not isinstance(attrs, dict):
            return current, False

        def _as_float(value):
            # Real numerics/strings only — duck-typed mocks support
            # __float__ and would fabricate bounds.
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    return None
            return None

        ent_min = _as_float(attrs.get("min"))
        ent_max = _as_float(attrs.get("max"))

        if current <= 0:
            return current, bool(ent_min is not None and ent_min > 0)
        if ent_max is not None and current > ent_max:
            current = ent_max
        if ent_min is not None and current < ent_min:
            current = ent_min
        return current, False

    def effective_max_current(self) -> float:
        """Highest current SEM can ACTUALLY command — the configured
        ``max_current`` clamped to the control number entity's own max.

        A charger configured at 32 A whose ``number.*_max_charging_current``
        entity caps at 16 A can only be driven to 16 A. Resolving CHARGE_MAX
        to the hardware 32 A made the reconciler command 32, the device clamp
        to 16, and the two never converge → a perpetual false 'drift' that
        spammed ``WRITE 32A`` + ``clamping 32 A → 16 A`` every cycle (#536
        logs). Service-controlled chargers (KEBA) have no current entity, so
        this returns the configured max unchanged.
        """
        eff = float(self.max_current)
        ent = self.current_entity_id
        if not ent:
            return eff
        attrs = getattr(self.hass.states.get(ent), "attributes", None)
        if isinstance(attrs, dict):
            ent_max = attrs.get("max")
            if ent_max is not None and not isinstance(ent_max, bool):
                try:
                    eff = min(eff, float(ent_max))
                except (TypeError, ValueError):
                    pass
        return eff

    async def _set_current(self, current: float) -> float:
        """Set charging current via entity or service."""
        current = round(current, 0)

        # #392 heartbeat dedup: skip the write only when the value didn't
        # change AND we've written recently. Without the time guard, a long
        # steady-state period (always_max holding 16 A, solar plateau) would
        # silently starve KEBA's failsafe watchdog → device drops to fallback
        # current → SEM still thinks it commanded 16 A and never re-writes.
        # Forcing a same-value re-write at WRITE_HEARTBEAT_INTERVAL_S keeps
        # the device watchdog refreshed and re-converges state after any
        # silent device-side reset (replug, KEBA reboot, failsafe trip).
        now = time.monotonic()
        if (
            abs(current - self._current_setpoint) < 1.0
            and self.is_active
            and (now - self._last_write_at) < self.watchdog_refresh_interval_s
        ):
            return self._status.current_consumption_w

        # Entity-platform services have strict schemas — sending the
        # per-integration param name produced "extra keys not allowed"
        # on EVERY command (#462, RienduPre, for number.set_value).
        # Generalized to the whole misconfigured-but-recoverable shape
        # (#485 K1): input_number.set_value and select.select_option
        # configured as the charger service bounced identically.
        _svc = (self.charger_service or "").strip().lower()
        _entity_svc_domain = _svc.split(".", 1)[0] if "." in _svc else ""

        # #487: HA core validates number writes against the ENTITY's
        # min/max BEFORE anything reaches the charger. Wallbox exposes
        # min=6 (IEC 61851), so writing 0 A to stop is structurally
        # impossible — it raised out_of_range every idle cycle (167×
        # in RienduPre's log) and, since the actuation Repair landed,
        # would false-trip it. Likewise a configured max above the
        # entity's max (Links: 6-16 A) bounced every ramp-up command.
        # Bound the write to the entity's range; a 0 A stop intent
        # skips the write entirely — the actual stop is the adapter's
        # job (pause switch / stop_session), and the number entity
        # cannot express it.
        _entity_target = None
        if _entity_svc_domain in ("number", "input_number"):
            _entity_target = self.current_entity_id or self.charger_service_entity_id
        elif not self.charger_service and self.current_entity_id:
            _entity_target = self.current_entity_id
        skip_entity_write = False
        if _entity_target:
            bounded, skip_entity_write = self._bound_to_entity_range(
                _entity_target, current,
            )
            if not skip_entity_write and bounded != current:
                _LOGGER.debug(
                    "%s: clamping commanded %.0f A into %s's range → %.0f A",
                    self.name, current, _entity_target, bounded,
                )
                current = bounded

        try:
            if skip_entity_write:
                # Stop intent on a number entity that can't express 0 A.
                _LOGGER.debug(
                    "%s: 0 A stop not writable to %s (entity min > 0) — "
                    "relying on the adapter stop path (pause switch / "
                    "stop_session) (#487)",
                    self.name, _entity_target,
                )
            elif _entity_svc_domain in ("number", "input_number"):
                # Map it to the entity write it was meant to be.
                target = self.current_entity_id or self.charger_service_entity_id
                await self.hass.services.async_call(
                    _entity_svc_domain, "set_value",
                    {"entity_id": target, "value": current},
                    blocking=True,
                )
            elif _entity_svc_domain == "select":
                # Amps exposed as a select: options are amp strings.
                target = self.current_entity_id or self.charger_service_entity_id
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": target, "option": str(int(current))},
                    blocking=True,
                )
            elif self.charger_service:
                # Service-based control — param name varies per integration (#82)
                domain, service = self.charger_service.split(".", 1)
                service_data = {self.service_param_name: current}
                # Some integrations need device_id (Easee, Zaptec)
                if self.service_device_id:
                    service_data["device_id"] = self.service_device_id
                # Pass entity_id only if service requires it (non-global services)
                elif self.charger_service_entity_id and not self.global_services:
                    service_data["entity_id"] = self.charger_service_entity_id
                await self.hass.services.async_call(
                    domain, service,
                    service_data,
                    blocking=True,
                )
            elif self.current_entity_id:
                # Number entity control
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self.current_entity_id, "value": current},
                    blocking=True,
                )

            self._clear_actuation_failure()

            self._current_setpoint = current
            self._last_write_at = now  # #392: heartbeat tracker
            self._record_power_change()
            consumed = self.current_to_watts(current) if current >= self.min_current else 0.0
            self._status.current_consumption_w = consumed
            self._status.allocated_power_w = consumed
            if current >= self.min_current:
                if not self.is_active:
                    self._status.activation_count += 1
                    self._status.last_activated = datetime.now()
                self._status.state = DeviceState.ACTIVE
            else:
                self._status.state = DeviceState.IDLE
                self._status.last_deactivated = datetime.now()
            self._last_deactivated = self._status.last_deactivated  # (#644) unified clock
            return consumed

        except Exception as e:
            _LOGGER.error("Failed to set current on %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            self._record_actuation_failure(e)
            return self._status.current_consumption_w

    def _record_actuation_failure(self, error: Exception) -> None:
        """Track consecutive set-current failures; raise a Repair at 3.

        RienduPre's #462 install failed EVERY current command for days
        with the evidence buried in per-cycle ERROR log lines — the user
        saw "SEM doesn't react" with no actionable surface. Three
        consecutive failures now raise a user-visible Repair naming the
        device and the error; it clears on the next successful write.
        """
        self._actuation_failures += 1
        if self._actuation_failures < 3 or self._actuation_repair_raised:
            return
        self._actuation_repair_raised = True
        try:
            from ..coordinator import repair_issues as _ri
            _ri.raise_charger_actuation_failed(
                self.hass, self.device_id,
                name=self.name, error=str(error),
            )
        except Exception as exc:  # noqa: BLE001 — never fail the cycle over a repair
            _LOGGER.debug("actuation-failure repair raise failed: %s", exc)

    def _clear_actuation_failure(self) -> None:
        """Reset the failure streak; clear the Repair after a good write."""
        if self._actuation_failures == 0 and not self._actuation_repair_raised:
            # #485 H5: the Repair is persistent (survives restart) but
            # these flags are instance state. After the reload that
            # fixing the config causes, the new instance's successful
            # writes hit this early-return and the stale ERROR Repair
            # stayed in the UI forever. Delete it once per instance —
            # async_delete_issue is a no-op when no issue exists.
            if not self._stale_repair_checked:
                self._stale_repair_checked = True
                try:
                    from ..coordinator import repair_issues as _ri
                    _ri.clear_charger_actuation_failed(self.hass, self.device_id)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug("stale actuation-repair clear failed: %s", exc)
            return
        self._actuation_failures = 0
        if not self._actuation_repair_raised:
            return
        self._actuation_repair_raised = False
        try:
            from ..coordinator import repair_issues as _ri
            _ri.clear_charger_actuation_failed(self.hass, self.device_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("actuation-failure repair clear failed: %s", exc)

    async def arm_failsafe(self) -> None:
        """Arm a NON-TRIPPING managed failsafe (#546 — managed-neutralize).

        Background: SEM's old failsafe (30 s, persist=0) left the box reverting
        to its built-in 6 A floor mid-charge → the 6↔9 A flap (Guido PROD
        2026-06-24). evcc avoids this by DISABLING the KEBA failsafe — but live
        testing on a real P30 showed the failsafe can't be disabled over UDP
        (``timeout=0`` is accepted but the box keeps it on; likely a safety
        design — you can't switch off the watchdog that guards UDP control). So
        SEM NEUTRALISES it instead: a **long** timeout (``FAILSAFE_TIMEOUT_S``,
        600 s) the per-cycle current writes keep feeding, **persisted** so it
        OVERWRITES the box's short built-in failsafe, with the fallback at the
        charging FLOOR (not 6 A). It can't trip during normal charging, and a
        genuine 10-min controller-death lands the car on the floor, not 6 A.

        ``arm_failsafe_enabled`` (config ``keba_arm_failsafe``, default True)
        can be set False for boxes that CAN disable the failsafe at the charger
        (evcc-style); then SEM doesn't touch it and a Repair guides the user to
        disable it. ``steady_failsafe`` (default on) controls persistence."""
        if not bool(getattr(self, "arm_failsafe_enabled", True)):
            _LOGGER.debug(
                "%s: not arming the charger failsafe (keba_arm_failsafe off) — "
                "a Repair guides disabling the box's own failsafe", self.name,
            )
            return
        domain = (self.charger_service or "").split(".", 1)[0]
        if not domain or not self.hass.services.has_service(domain, "set_failsafe"):
            return
        try:
            fallback_a = max(6, int(round(self.min_current)))
            steady = bool(getattr(self, "steady_failsafe", True))
            persist = 1 if steady else 0
            await self.hass.services.async_call(
                domain, "set_failsafe",
                {"failsafe_timeout": FAILSAFE_TIMEOUT_S,
                 "failsafe_fallback": fallback_a, "failsafe_persist": persist},
                blocking=True,
            )
            _LOGGER.info(
                "%s: KEBA failsafe set non-tripping (timeout=%ds, fallback=%dA, "
                "persist=%d)", self.name, FAILSAFE_TIMEOUT_S, fallback_a, persist,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to set charger failsafe: %s", e)

    async def arm_failsafe_off(self) -> None:
        """(#740) Re-arm the failsafe as a dead-man's OFF after a stop.

        The charging arm (``arm_failsafe``) points the fallback at the
        charging floor so a dead controller mid-charge lands the car on
        the floor. That same persisted floor is what fed an Off-mode car
        in ~3 kW bites through a SEM restart (PROD 2026-08-08, #740):
        masterless, the watchdog re-authorised a CHARGING current. After
        a SEM-initiated stop the correct dead-man state is OFF —
        fallback 0 A, short timeout, persisted — so the box itself
        enforces "off means off" across restarts, UDP loss, and firmware
        auto-start retries, until the next start sequence re-arms the
        charging failsafe. Same opt-out as the charging arm.
        """
        if not bool(getattr(self, "arm_failsafe_enabled", True)):
            return
        domain = (self.charger_service or "").split(".", 1)[0]
        if not domain or not self.hass.services.has_service(domain, "set_failsafe"):
            return
        try:
            await self.hass.services.async_call(
                domain, "set_failsafe",
                {"failsafe_timeout": FAILSAFE_OFF_TIMEOUT_S,
                 "failsafe_fallback": 0, "failsafe_persist": 1},
                blocking=True,
            )
            _LOGGER.info(
                "%s: failsafe re-armed as dead-man's OFF (timeout=%ds, "
                "fallback=0A, persisted) — the box holds the no while "
                "SEM is away (#740)", self.name, FAILSAFE_OFF_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to arm the dead-man's-off failsafe: %s", e)

    def _energy_target_sensor_id(self) -> Optional[str]:
        """Entity id of the box's OWN energy-target register sensor, if the
        charger integration exposes one (KEBA: ``sensor.*_energy_target``).

        Discovered once via the entity registry as a sibling of the configured
        power sensor's device — same strategy as the SOC / temperature sibling
        discovery. None when undiscoverable (non-KEBA, no registry entry)."""
        cached = getattr(self, "_energy_target_sensor_cache", None)
        if cached:
            return cached
        # NO negative caching (PROD 2026-07-18): the first lookup can run
        # before the entity registry is ready at boot — caching that None
        # permanently killed the guard backstop for the process lifetime
        # (the armed flag is instance state and resets on reload, so the
        # sensor check was the ONLY durable detector — and it was dark).
        # Retry every call until found; cache only a positive hit.
        found = None
        try:
            anchor = self.power_entity_id or self.current_sensor_entity_id
            if anchor and self.hass is not None:
                # Strategy 1 — device-registry sibling (integrations that
                # attach entities to a device).
                from homeassistant.helpers import entity_registry as er
                reg = er.async_get(self.hass)
                ent = reg.async_get(anchor)
                if ent is not None and ent.device_id:
                    for other in er.async_entries_for_device(reg, ent.device_id):
                        if other.entity_id.endswith("energy_target"):
                            found = other.entity_id
                            break
                # Strategy 2 — name derivation. The KEBA integration is a
                # hub-style YAML platform whose entities carry NO device_id
                # (PROD 2026-07-18: device-registry discovery structurally
                # blind → the guard backstop never fired). Derive the
                # register sensor from the anchor's naming:
                # sensor.<box>_charging_power → sensor.<box>_energy_target.
                if not found:
                    obj = anchor.split(".", 1)[-1]
                    for suf in ("_charging_power", "_power", "_max_current"):
                        if obj.endswith(suf):
                            cand = "sensor." + obj[: -len(suf)] + "_energy_target"
                            if self.hass.states.get(cand) is not None:
                                found = cand
                            break
                # Strategy 3 — unique prefix match across all states.
                if not found:
                    prefix = anchor.split(".", 1)[-1].split("_", 1)[0]
                    cands = [
                        eid for eid in self.hass.states.async_entity_ids("sensor")
                        if eid.endswith("_energy_target")
                        and eid.split(".", 1)[-1].startswith(prefix)
                    ]
                    if len(cands) == 1:
                        found = cands[0]
        except Exception:  # noqa: BLE001 — discovery must never break a command
            found = None
        if found:
            self._energy_target_sensor_cache = found
        elif not getattr(self, "_energy_target_warned", False):
            self._energy_target_warned = True
            _LOGGER.debug(
                "%s: energy-target register sensor not discoverable (yet) — "
                "the guard backstop retries each charge command", self.name,
            )
        return found

    async def ensure_energy_guard_released(self) -> None:
        """(#553 follow-up) Verify the box actually RELEASED the runaway-cap
        energy target — and re-send the release if not.

        ``start_session`` sends ``set_energy 0`` exactly once, fire-and-forget.
        KEBA speaks lossy UDP: PROD 2026-07-17 showed the release datagram
        dropped — the box kept its armed 1 kWh target, terminated every new
        session within seconds (session_energy 9.1 ≥ target 1.0), and the car
        burst-cycled for 25 minutes while SEM faithfully wrote currents into a
        session the box kept killing. SEM reconciles the *current* every
        cycle; the guard register must be reconciled the same way, not
        trusted from one write.

        Checks SEM's own armed flag AND (when discoverable) the box's
        ``energy_target`` sensor; either says armed → re-send ``set_energy 0``.
        Cheap no-op in the common case (flag False + sensor 0/absent).
        """
        armed = bool(getattr(self, "_idle_guard_armed", False))
        if not armed:
            sensor = self._energy_target_sensor_id()
            if sensor:
                st = self.hass.states.get(sensor) if self.hass else None
                if st is not None and st.state not in (
                    "unknown", "unavailable", None, "",
                ):
                    try:
                        armed = float(st.state) > 0
                    except (ValueError, TypeError):
                        armed = False
        if not armed:
            return
        domain = (self.charger_service or "").split(".", 1)[0]
        if not (domain and self.hass.services.has_service(domain, "set_energy")):
            return
        try:
            await self.hass.services.async_call(
                domain, "set_energy", {"energy": 0}, blocking=True,
            )
            self._idle_guard_armed = False
            _LOGGER.info(
                "%s: released a STALE energy-target guard the box still held "
                "(lost/unapplied set_energy release, #553) — charging can "
                "proceed unbounded again", self.name,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "%s: stale energy-target guard release failed (%s) — the box "
                "may keep ending sessions at the runaway cap", self.name, e,
            )

    async def start_session(self, energy_target_kwh: float = 0) -> None:
        """Start a charging session.

        Uses the charger profile to determine the correct start method (#82):
        - KEBA: service enable + optional failsafe/energy target
        - Easee: action_command service with "resume"
        - Wallbox/Heidelberg: switch entity turn_on
        - Zaptec/ChargePoint: button entity press
        - go-eCharger/OpenWB: select entity set mode
        - Fallback: probe for domain.enable service (KEBA pattern)
        """
        try:
            # 1. Profile-based start (preferred)
            if self.start_service:
                domain, service = self.start_service.split(".", 1)
                data = dict(self.start_service_data or {})
                if self.service_device_id:
                    data["device_id"] = self.service_device_id
                await self.hass.services.async_call(domain, service, data, blocking=True)
            elif self.charge_mode_entity and self.charge_mode_start:
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": self.charge_mode_entity, "option": self.charge_mode_start},
                    blocking=True,
                )
            elif self.start_stop_entity:
                domain = self.start_stop_entity.split(".")[0]
                if domain in ("switch", "input_boolean"):
                    await self.hass.services.async_call(
                        domain, "turn_on",
                        {"entity_id": self.start_stop_entity}, blocking=True,
                    )
                elif domain == "button":
                    await self.hass.services.async_call(
                        "button", "press",
                        {"entity_id": self.start_stop_entity}, blocking=True,
                    )
            elif self.charger_service:
                # 2. KEBA-style fallback: probe for enable/disable services
                domain = self.charger_service.split(".", 1)[0]

                # Failsafe: a no-op by default now (#546, evcc-style — SEM
                # doesn't arm the KEBA failsafe; a Repair guides disabling it at
                # the box). Only arms when opted in via ``keba_arm_failsafe``.
                await self.arm_failsafe()

                # Set energy target if supported (KEBA). #553: when SEM has
                # no target, EXPLICITLY clear the register (0 = no limit) —
                # stop_session() arms a ~1 Wh idle-guard there so a firmware
                # auto-start (#315) self-terminates at the box; every real
                # SEM start must release that guard or the session would end
                # at 1 Wh. SEM owns the KEBA session-energy register.
                if self.hass.services.has_service(domain, "set_energy"):
                    await self.hass.services.async_call(
                        domain, "set_energy",
                        {"energy": energy_target_kwh if energy_target_kwh > 0 else 0},
                        blocking=True,
                    )
                    self._idle_guard_armed = False

                # Pilot cycle: disable/enable for cars that need fresh signal
                if self.needs_pilot_cycle and self.hass.services.has_service(domain, "disable"):
                    await self.hass.services.async_call(domain, "disable", {}, blocking=True)
                    await asyncio.sleep(3)

                # Enable charger. The historically-working sequence
                # (v1.5.0–v1.6.x) is: set_failsafe → set_energy →
                # (optional pilot cycle) → enable. ``keba.authorize`` is
                # NOT in this sequence — it's an RFID-flow primitive for
                # installs that require per-session card auth, and adding
                # it speculatively risks toggling KEBA into an
                # auth-rejected state. The auth-rejected behaviour we
                # observed on PROD 2026-06-02 15:08 UTC is mitigated
                # structurally by ``ChargerAdapter.attempt_idle()`` (the
                # IDLE-debounce — see ``actuate.py``), which prevents
                # ``keba.disable`` from firing on transient solar dips.
                if self.hass.services.has_service(domain, "enable"):
                    await self.hass.services.async_call(domain, "enable", {}, blocking=True)

            self._session_active = True
            _LOGGER.info("Charging session started for %s", self.name)
        except Exception as e:
            _LOGGER.error("Failed to start session on %s: %s", self.name, e)

    async def stop_session(self) -> None:
        """Stop the charging session.

        Uses the charger profile to determine the correct stop method (#82).

        Logs which mechanism fired and warns if none did (which means we're
        relying on ``_set_current(0)`` alone to stop charging — that works
        on chargers where 0 A == pause, but NOT on KEBA where 0 A is
        documented as "minimum" and the contactor stays closed without an
        explicit ``keba.disable`` call (v1.6.3 PROD soak regression).
        """
        stop_method = None
        try:
            if self.stop_service:
                domain, service = self.stop_service.split(".", 1)
                data = dict(self.stop_service_data or {})
                if self.service_device_id:
                    data["device_id"] = self.service_device_id
                await self.hass.services.async_call(domain, service, data, blocking=True)
                stop_method = f"stop_service={self.stop_service}"
            elif self.charge_mode_entity and self.charge_mode_stop:
                await self.hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": self.charge_mode_entity, "option": self.charge_mode_stop},
                    blocking=True,
                )
                stop_method = f"charge_mode={self.charge_mode_stop}"
            elif self.start_stop_entity:
                domain = self.start_stop_entity.split(".")[0]
                if domain in ("switch", "input_boolean"):
                    await self.hass.services.async_call(
                        domain, "turn_off",
                        {"entity_id": self.start_stop_entity}, blocking=True,
                    )
                    stop_method = f"{domain}.turn_off={self.start_stop_entity}"
                elif domain == "button":
                    # Stop buttons have different entity_ids than start buttons
                    # The stop entity is typically named *_stop_charging*
                    stop_entity = self.start_stop_entity.replace("resume", "stop").replace("start", "stop")
                    if "_charging" not in stop_entity:
                        stop_entity = stop_entity.replace("_stop", "_stop_charging")
                    await self.hass.services.async_call(
                        "button", "press",
                        {"entity_id": stop_entity}, blocking=True,
                    )
                    stop_method = f"button.press={stop_entity}"
            elif self.charger_service:
                # KEBA-style fallback
                domain = self.charger_service.split(".", 1)[0]
                if self.hass.services.has_service(domain, "disable"):
                    await self.hass.services.async_call(domain, "disable", {}, blocking=True)
                    stop_method = f"{domain}.disable"
                    # #553 — BOX-LEVEL runaway cap (#315): KEBA firmware
                    # auto-restarts a session at its stored setpoint when the
                    # car retries (~every 10 min), even after keba.disable.
                    # While SEM is alive its policing (#552) kills each rogue
                    # start within a cycle; this 1 kWh session-energy target
                    # (the keba library MINIMUM — smaller values are rejected,
                    # live-verified) bounds the damage when SEM is NOT
                    # policing (down/restarting): the box then ends a rogue
                    # session itself at 1 kWh instead of charging unbounded.
                    # Every SEM start releases the guard (start_session writes
                    # the real target, or 0 = no limit). Note: SEM owns this
                    # register — user-set box limits are overwritten.
                    #
                    # Own try (review H1): a set_energy failure must neither
                    # skip the _session_active reset below nor mask that the
                    # disable itself succeeded.
                    if self.hass.services.has_service(domain, "set_energy"):
                        try:
                            await self.hass.services.async_call(
                                domain, "set_energy",
                                {"energy": KEBA_IDLE_GUARD_KWH}, blocking=True,
                            )
                            self._idle_guard_armed = True
                            _LOGGER.debug(
                                "stop_session(%s): armed %.1f kWh runaway-cap "
                                "energy target (#553)", self.name,
                                KEBA_IDLE_GUARD_KWH,
                            )
                        except Exception as guard_err:  # noqa: BLE001
                            _LOGGER.warning(
                                "stop_session(%s): idle-guard set_energy "
                                "failed (%s) — box auto-start protection "
                                "not armed this stop (#553)",
                                self.name, guard_err,
                            )
                else:
                    _LOGGER.warning(
                        "stop_session(%s): charger_service=%s configured but "
                        "%s.disable service is not registered — falling back to "
                        "_set_current(0) which does NOT stop KEBA-style contactors. "
                        "Check that the underlying charger integration is loaded.",
                        self.name, self.charger_service, domain,
                    )

            await self._set_current(0)
            # (#740) whatever stop path fired, leave the box holding a
            # standing NO: the dead-man's-off failsafe survives SEM's
            # absence, which per-cycle policing (#552) never could.
            await self.arm_failsafe_off()
            self._session_active = False
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._current_setpoint = 0.0
            self._last_write_at = 0.0  # #392: reset heartbeat tracker on session stop

            if stop_method is None:
                # No brand-specific stop fired — relying on _set_current(0) alone.
                # That works on Wallbox / Easee / go-e / OpenEVSE (firmware treats
                # 0 A as pause) but NOT on KEBA (0 A is "minimum", contactor stays
                # closed; needs keba.disable). Warning so this case is visible in
                # PROD logs the next time the bug class re-emerges.
                _LOGGER.warning(
                    "stop_session(%s): no brand-specific stop mechanism "
                    "configured (stop_service=None, charge_mode_entity=None, "
                    "start_stop_entity=None, charger_service=None). Relying on "
                    "_set_current(0) alone — confirm your charger firmware "
                    "treats 0 A as a stop signal, not as a minimum hold.",
                    self.name,
                )
            else:
                _LOGGER.info(
                    "Charging session stopped for %s via %s",
                    self.name, stop_method,
                )
        except Exception as e:
            _LOGGER.error("Failed to stop session on %s: %s", self.name, e)

    # update_energy_target() removed (#553 review L1): zero callers, and a
    # mid-session set_energy write would overwrite the idle-guard register.


    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "min_current": self.min_current,
            "max_current": self.max_current,
            "phases": self.phases,
            "current_setpoint": self._current_setpoint,
            "session_active": self._session_active,
            "managed_externally": self._managed_externally,
        })
        return d


class SetpointDevice(ControllableDevice):
    """Numerical setpoint device (heat pump temperature, battery charge).

    When surplus is available, the setpoint is boosted (e.g., +2C for heat pump).
    When surplus drops, the setpoint returns to normal.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        min_power_threshold: float = 0.0,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        climate_entity_id: Optional[str] = None,
        min_setpoint: float = 18.0,
        max_setpoint: float = 55.0,
        normal_setpoint: float = 21.0,
        boost_offset: float = 2.0,
        min_power_change_interval: float = 300.0,
        energy_entity_id: Optional[str] = None,
    ):
        super().__init__(
            hass, device_id, name, priority,
            min_power_threshold or rated_power,
            entity_id, power_entity_id,
            energy_entity_id=energy_entity_id,
        )
        self.rated_power = rated_power
        self.climate_entity_id = climate_entity_id
        self.min_setpoint = min_setpoint
        self.max_setpoint = max_setpoint
        self.normal_setpoint = normal_setpoint
        self.boost_offset = boost_offset
        self._boosted = False
        self._min_power_change_interval = min_power_change_interval

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SETPOINT

    async def activate(self, available_watts: float) -> float:
        if not self.climate_entity_id:
            return 0.0

        target = min(self.max_setpoint, self.normal_setpoint + self.boost_offset)
        try:
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self.climate_entity_id, "temperature": target},
                blocking=True,
            )
            self._boosted = True
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            self._status.last_activated = datetime.now()
            self._last_activated = self._status.last_activated  # (#644) unified clock
            self._status.activation_count += 1
            _LOGGER.info("Boosted %s setpoint to %.1f", self.name, target)
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to boost %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

    async def deactivate(self) -> None:
        if not self.climate_entity_id or not self._boosted:
            return

        try:
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self.climate_entity_id, "temperature": self.normal_setpoint},
                blocking=True,
            )
            self._boosted = False
            self._status.state = DeviceState.IDLE
            self._status.current_consumption_w = 0.0
            self._status.allocated_power_w = 0.0
            self._status.last_deactivated = datetime.now()
            self._last_deactivated = self._status.last_deactivated  # (#644) unified clock
            _LOGGER.info("Restored %s setpoint to %.1f", self.name, self.normal_setpoint)
        except Exception as e:
            _LOGGER.error("Failed to restore %s setpoint: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)

    async def adjust_power(self, available_watts: float) -> float:
        # Setpoint devices are either boosted or not
        if not self._is_power_change_allowed():
            return self._status.current_consumption_w
        if self.is_active:
            return self.rated_power
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "normal_setpoint": self.normal_setpoint,
            "boost_offset": self.boost_offset,
            "boosted": self._boosted,
        })
        return d


class ScheduleDevice(ControllableDevice):
    """Deadline-scheduled device (dishwasher, washing machine).

    User sets a deadline and estimated runtime/energy. The scheduler
    monitors surplus and starts the appliance when sufficient solar is
    available. If the deadline approaches without enough solar, it
    starts anyway using grid power.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
        rated_power: float,
        priority: int = 5,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        deadline: Optional[datetime] = None,
        estimated_runtime_minutes: int = 120,
        estimated_energy_kwh: float = 1.0,
    ):
        super().__init__(
            hass, device_id, name, priority,
            rated_power * 0.8,  # Start when 80% of rated power available
            entity_id, power_entity_id,
        )
        self.rated_power = rated_power
        self.deadline = deadline
        self.estimated_runtime_minutes = estimated_runtime_minutes
        self.estimated_energy_kwh = estimated_energy_kwh
        self._started = False
        self._start_time: Optional[datetime] = None

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SCHEDULE

    @property
    def must_start_by(self) -> Optional[datetime]:
        """Calculate latest start time to meet deadline."""
        if not self.deadline:
            return None
        return self.deadline - timedelta(minutes=self.estimated_runtime_minutes)

    @property
    def is_deadline_approaching(self) -> bool:
        """Check if we must start now to meet deadline."""
        latest = self.must_start_by
        if not latest:
            return False
        return datetime.now() >= latest

    def schedule(
        self,
        deadline: datetime,
        estimated_runtime_minutes: int = 120,
        estimated_energy_kwh: float = 1.0,
    ) -> None:
        """Set or update the schedule."""
        self.deadline = deadline
        self.estimated_runtime_minutes = estimated_runtime_minutes
        self.estimated_energy_kwh = estimated_energy_kwh
        self._started = False
        self._start_time = None
        self._status.state = DeviceState.SCHEDULED
        _LOGGER.info(
            "Scheduled %s: deadline=%s, runtime=%dmin, energy=%.1fkWh",
            self.name, deadline, estimated_runtime_minutes, estimated_energy_kwh,
        )

    async def activate(self, available_watts: float) -> float:
        if not self.entity_id or self._started:
            return 0.0

        try:
            await self.hass.services.async_call(
                "homeassistant", "turn_on",
                {"entity_id": self.entity_id},
                blocking=True,
            )
            self._started = True
            self._start_time = datetime.now()
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            self._status.last_activated = datetime.now()
            self._last_activated = self._status.last_activated  # (#644) unified clock
            self._status.activation_count += 1
            _LOGGER.info("Started scheduled device %s", self.name)
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to start %s: %s", self.name, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0

    async def deactivate(self) -> None:
        # Scheduled devices generally should not be interrupted once started
        # Only deactivate if not yet started
        if self._started:
            _LOGGER.debug("Not deactivating %s - already running", self.name)
            return

        self._status.state = DeviceState.SCHEDULED if self.deadline else DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0

    async def adjust_power(self, available_watts: float) -> float:
        if self._started:
            return self.rated_power
        return 0.0

    def clear_schedule(self) -> None:
        """Clear the current schedule."""
        self.deadline = None
        self._started = False
        self._start_time = None
        self._status.state = DeviceState.IDLE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "estimated_runtime_minutes": self.estimated_runtime_minutes,
            "estimated_energy_kwh": self.estimated_energy_kwh,
            "started": self._started,
            "must_start_by": self.must_start_by.isoformat() if self.must_start_by else None,
            "is_deadline_approaching": self.is_deadline_approaching,
        })
        return d


def surplus_device_from_spec(
    hass: HomeAssistant, device_id: str, spec: Dict[str, Any]
) -> "ControllableDevice":
    """Build a live surplus device from a stored/service spec (#569).

    Single source of truth for the three service-device build sites (the
    ``register_surplus_device`` handler, the registry's create path, and the
    restart-rehydrate path) so a new device type only has to be added here.

    ``spec["device_type"]`` selects the class (default ``"switch"``):

    - ``"climate"`` → :class:`ClimateDevice` (reads ``hvac_mode`` /
      ``target_temperature``);
    - anything else → :class:`SwitchDevice`.

    The caller still applies ``control_mode``, ``depends_on`` and goals — this
    only constructs the object.
    """
    dtype = (spec.get("device_type") or "switch").lower()
    name = spec.get("name") or device_id
    rated_power = spec.get("rated_power", 1000)
    priority = spec.get("priority", 5)
    entity_id = spec.get("entity_id", "")
    power_entity_id = spec.get("power_entity_id")
    energy_entity_id = spec.get("energy_entity_id")
    # #600 — autodetect-FIRST: a kWh-only load device (energy sensor, no power
    # sensor) first tries to find a companion power sensor on the same device;
    # only when none exists does the device fall back to deriving power from the
    # energy counter (EnergyRateDeriver). A power sensor always beats derivation.
    if energy_entity_id and not power_entity_id:
        try:
            from ..ha_energy_reader import (
                _find_power_sensor_on_device, _POWER_DERIVE_RULES,
            )
            found = _find_power_sensor_on_device(
                hass, energy_entity_id, _POWER_DERIVE_RULES["load"],
            )
            if found:
                power_entity_id = found
        except Exception:  # noqa: BLE001 — best-effort autodetect
            pass
    if dtype == "climate":
        target = spec.get("target_temperature")
        return ClimateDevice(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            entity_id=entity_id,
            power_entity_id=power_entity_id,
            energy_entity_id=energy_entity_id,
            hvac_mode=spec.get("hvac_mode", "cool"),
            target_temperature=float(target) if target is not None else None,
            # (#705) thermal comfort band — optional, 0/"" = disengaged.
            comfort_entity=str(spec.get("comfort_entity", "") or ""),
            comfort_target=float(spec.get("comfort_target", 0.0) or 0.0),
            comfort_offset=float(spec.get("comfort_offset", 0.0) or 0.0),
            comfort_limit=float(spec.get("comfort_limit", 0.0) or 0.0),
        )
    return SwitchDevice(
        hass=hass,
        device_id=device_id,
        name=name,
        rated_power=rated_power,
        priority=priority,
        entity_id=entity_id,
        power_entity_id=power_entity_id,
        energy_entity_id=energy_entity_id,
    )
