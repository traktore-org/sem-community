"""Hot water controller for Solar Energy Management.

Supports three HA entity types for broad hardware compatibility (#92):
- water_heater.* (Viessmann, Nibe, Daikin Altherma, MQTT)
- climate.* (KNX, Stiebel Eltron, ESPHome thermostat)
- switch.* (Shelly relay, smart plugs, ESPHome GPIO) + separate temp sensor

Includes mandatory Legionella prevention cycle:
- Tracks hours since tank last reached disinfection temperature
- Forces heating to target (60-80°C) if interval exceeded
- Cannot be disabled — only interval and target are configurable
- Auto-adjusts hold duration based on target temperature
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .base import ComfortBandMixin, SwitchDevice, DeviceState
from .tank_goal import (  # noqa: F401 — the shared numbers, re-exported
    LEGIONELLA_HOLD_BAND_K, LEGIONELLA_HOLD_DIP_K, RECOMPUTE, START_MARGIN_K,
    START_MARGIN_STICKY_K, TankGoal, TankInputs, build_tank_goal, differences,
)
from ..utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)

DEFAULT_SOLAR_TARGET_TEMP = 50.0  # Normal solar heating target
DEFAULT_MIN_TEMPERATURE = 40.0    # Minimum useful temperature
DEFAULT_HOT_WATER_POWER = 2000    # Typical immersion heater power

# Legionella prevention defaults
DEFAULT_LEGIONELLA_TARGET = 65.0  # Disinfection temperature
DEFAULT_LEGIONELLA_INTERVAL_HOURS = 72  # Max hours between cycles
#: (#1369) In the last day before a run is due, a sunny hour may
#: start it EARLY. Never later: at the due time it runs as before.
LEGIONELLA_EARLY_WINDOW_H = 24.0
#: (#1368) …and a CHEAP hour may start it too, as late as it can: when the
#: cheap hours still left before the run is due are just enough for it
#: (its last run time × 1.5 + half an hour). So a run due in a high-tariff
#: hour has run in the low tariff before it, and is not much earlier than
#: it must be. Without a view of the coming prices: in the last 12 h.
LEGIONELLA_CHEAP_WINDOW_H = 12.0
LEGIONELLA_CHEAP_MARGIN = 1.5
LEGIONELLA_CHEAP_SLACK_H = 0.5
#: How long a run takes while none has been timed yet (h), and the bounds
#: a timed one is kept in: a tank that was nearly hot gave a short time
#: once, and no run is longer than the limit it is given up at.
LEGIONELLA_DEFAULT_RUN_H = 3.0
LEGIONELLA_MIN_RUN_H = 1.0
#: (#1369) the good hour must hold this long before an early start, and be
#: gone this long before an early run pauses — no start/stop on a passing cloud
LEGIONELLA_EARLY_START_HOLD_MIN = 10.0
# (#1369) START_MARGIN_K, START_MARGIN_STICKY_K, LEGIONELLA_HOLD_BAND_K and
# LEGIONELLA_HOLD_DIP_K are defined once, in ``tank_goal`` (imported above) —
# a probe that wobbles 59.9/60.1 never finished a hold without the dip.
#: (#1369) an early run does not pause this close to its due time — the
#: minimum run would hold it on anyway, and it is due right after
LEGIONELLA_EARLY_PAUSE_MIN_LEAD_H = 1.0
#: (#1369) SEM does not heat blind: a run with no reading this long ends
#: (no disinfection, no block — it runs again when the tank reads)
LEGIONELLA_UNREAD_END_MIN = 15.0
#: (#1369) a missed reading this short is a glitch, not a broken hold
LEGIONELLA_UNREAD_HOLD_GRACE_MIN = 2.0
LEGIONELLA_EARLY_PAUSE_HOLD_MIN = 30.0   # a cloudy spell, not a passing cloud
#: (#1369) A tank that draws power this long without warming this much has
#: a fault (element, thermostat, a heat pump that is not heating the tank).
#: two hours: a tank heated from the bottom can hold a top sensor flat for
#: an hour after a big draw-off
HEAT_CHECK_MINUTES = 120.0
HEAT_MIN_RISE_K = 1.0
#: (#1369) SEM has the heater on, it draws nothing and the tank is below its
#: target for this long: the boiler's own thermostat has cut it off
OWN_THERMOSTAT_MINUTES = 10.0
DEFAULT_LEGIONELLA_MIN_TEMP = 60.0  # Absolute minimum allowed
# (#1102) A run that has not reached its target after this long ends: a 300 l
# tank heats 40 → 65 °C on 3 kW in about 3 h, so 6 h means it cannot.
LEGIONELLA_MAX_RUN_HOURS = 6.0

# Hold duration by target temperature (higher = shorter hold)
LEGIONELLA_HOLD_MINUTES = {
    60: 30,
    65: 20,
    70: 5,
    75: 3,
    80: 3,
}

# (#914) The domains whose command is a SETPOINT, not an on/off state.
_SETPOINT_DOMAINS = ("water_heater", "climate")

# (#914) How close a tank's setpoint must sit to one SEM writes before a
# restart may read it as SEM's boost. Half a degree absorbs a device that
# rounds the written value; a setpoint the user picked sits further away.
_BOOST_SETPOINT_MATCH_K = 0.5


class HotWaterController(SwitchDevice):
    """Hot water controller with multi-entity support and Legionella prevention.

    Supports water_heater, climate, and switch entities.
    The Legionella cycle is mandatory and cannot be disabled.
    """

    #: (#1369) what the "does not warm" repair quotes
    HEAT_CHECK_MINUTES_USED = int(HEAT_CHECK_MINUTES)

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str = "hot_water",
        name: str = "Hot Water",
        rated_power: float = DEFAULT_HOT_WATER_POWER,
        priority: int = 6,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        temperature_entity_id: Optional[str] = None,
        min_temperature: float = DEFAULT_MIN_TEMPERATURE,
        solar_target_temp: float = DEFAULT_SOLAR_TARGET_TEMP,
        legionella_target_temp: float = DEFAULT_LEGIONELLA_TARGET,
        legionella_interval_hours: float = DEFAULT_LEGIONELLA_INTERVAL_HOURS,
        # (#914) heat-pump-shaped, not resistive-element-shaped. The #688
        # floor-raise to 300 s on SwitchDevice never reached this subclass,
        # so a hot-water heat pump restarted after a 60 s pause — pure wear
        # while the circuit water was still coming up. These are the SAME
        # numbers HeatPumpController committed to for its compressor (#508
        # W1: 10 min minimum run / 5 min rest), so this is consistency with
        # a value the repo already stands behind, not a new guess. (#1335) A
        # Legionella run is started by the load engine like any other run,
        # so it waits out the same rest.
        min_on_time: int = 600,
        min_off_time: int = 300,
        daily_min_runtime_sec: int = 0,
        energy_entity_id: Optional[str] = None,
    ):
        super().__init__(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            entity_id=entity_id,
            power_entity_id=power_entity_id,
            min_on_time=min_on_time,
            min_off_time=min_off_time,
            daily_min_runtime_sec=daily_min_runtime_sec,
            energy_entity_id=energy_entity_id,  # #600 — DHW kWh counter → derived power
        )
        self.temperature_entity_id = temperature_entity_id
        # (#1062) The lowest useful temperature: the vacation surplus cap and
        # the setpoint a water_heater is left at when it cannot be turned off.
        # It never STARTS heating — forcing lives on the comfort band's limit
        # ("Run now past"). There is no separate maximum: the solar target is
        # the ceiling SEM heats to (#92), the Legionella target its own.
        self.min_temperature = min_temperature
        self.solar_target_temp = solar_target_temp
        self.legionella_target_temp = max(legionella_target_temp, DEFAULT_LEGIONELLA_MIN_TEMP)
        self.legionella_interval_hours = legionella_interval_hours

        # Detect entity type from domain
        self._entity_domain: Optional[str] = None
        if entity_id:
            self._entity_domain = entity_id.split(".")[0]

        # Legionella tracking
        self._last_legionella_time: Optional[datetime] = None
        self._legionella_cycle_active: bool = False
        # (#1369) heating that does not warm the tank
        self._heat_check = None
        self._cutout_since = None
        self.own_thermostat_c: Optional[float] = None
        self.heating_fault: bool = False
        self.heating_fault_temp: Optional[float] = None
        self._legionella_hold_start: Optional[datetime] = None
        # (#1102) when the running cycle started, and until when a cycle that
        # could not finish waits before it is tried again
        self._legionella_started_at: Optional[datetime] = None
        self._legionella_blocked_until: Optional[datetime] = None
        # (#1335) The run ended (done, could not finish, vacation) while the
        # tank was on. The load engine stops it once and clears this.
        self._legionella_end_pending: bool = False
        # (#1335) The setpoint SEM last wrote to a water_heater / climate
        # tank, so a changed target (Legionella, vacation) is written again.
        self._written_target: Optional[float] = None

        # #594 — vacation mode. Both set each cycle by the coordinator.
        # While ``vacation`` is True there is no comfort heating (no solar-
        # target boost, no cheap-tariff force) and legionella cycles are
        # PAUSED — ``_last_legionella_time`` keeps aging, so a cycle that
        # falls due while away runs promptly on return. When
        # ``vacation_dhw_surplus`` is also True the tank may still soak up
        # solar surplus, but only to ``min_temperature`` (free energy
        # without comfort heating).
        self.vacation: bool = False
        self.vacation_dhw_surplus: bool = False

        # #420 — telemetry surface mirroring #359/#416 classifier_path
        # pattern. Each decision branch sets the corresponding ``*_path``
        # string so the ``load_management_status`` sensor's ``devices``
        # dict can publish them for self-diagnosis. No behavior change.
        self._last_legionella_path: str = "uninitialized"
        self._last_temperature_safety_path: str = "uninitialized"
        self._last_temperature_reading_path: str = "uninitialized"
        self._last_activation_path: str = "uninitialized"
        self._last_deactivation_path: str = "uninitialized"
        self._last_temperature_reading: Optional[float] = None

        # #508 — hot water exists to soak up solar surplus, so it must be
        # a SURPLUS-mode device. The base default is PEAK_ONLY, and
        # SurplusController.update() never proactively activates a
        # non-SURPLUS device — so without this the controller registered
        # but never turned on. Overridable via set_device_control_mapping.
        from .base import DeviceControlMode
        self.control_mode = DeviceControlMode.SURPLUS

        # (#914) One restart adoption per lifetime, decided on the first
        # READABLE observation after registration — see adopt_if_running.
        self._boot_adoption_pending: bool = True

        # (#1369, step 1) the shadow goal: where it differs from today's
        # decision, per field; nothing reads these to decide
        self.tank_goal_diffs: Dict[str, int] = {}
        self.tank_goal_last: Dict[str, Any] = {}
        self.tank_goal_errors: int = 0
        self.tank_goal_skipped: int = 0   # cycles the engine never asked the stop

    # ─── Restart adoption (#914) ─────────────────────────────

    def _adoptable_now(self) -> Optional[bool]:
        """(#914) A water_heater / climate tank is commanded by SETPOINT, not
        by an on/off state — a water_heater reports its operation mode as its
        state ("heat_pump", "eco"), a climate its hvac mode, and neither is
        ever "on". So read the axis SEM writes.

        True only while the entity still holds one of SEM's OWN boost
        setpoints: the solar target, or the legionella target mid-cycle. A
        setpoint SEM never writes — hotter than its target, or anything else
        — is the user's and is never claimed: SEM releases what it commanded
        and nothing more (#847, #908). One that EQUALS SEM's boost cannot be
        told apart from it and is claimed, as #766 claims a switch turned on
        in Solar mode. A climate tank must also be in the ``heat`` mode SEM
        writes, the line ``ClimateDevice.adopt_if_running`` holds.
        """
        if self._entity_domain not in _SETPOINT_DOMAINS:
            return super()._adoptable_now()
        state = self.hass.states.get(self.entity_id)
        if not state or state.state in ("unavailable", None):
            return None
        mode = str(state.state).lower()
        if mode == "off":
            return False
        if self._entity_domain == "climate" and mode != "heat":
            return None if mode == "unknown" else False
        raw = state.attributes.get("temperature")
        if raw is None:
            # HA writes "unknown" for a water_heater without operation modes
            # — permanently. Without a setpoint yet, it is still loading.
            return None if mode == "unknown" else False
        try:
            target = float(raw)
        except (TypeError, ValueError):
            return False
        return any(
            abs(target - boost) <= _BOOST_SETPOINT_MATCH_K
            # (#1369) a band tank's boost is sent at the band's top
            for boost in (self.solar_target_temp, self.legionella_target_temp,
                          self._band_fields_top_c() or self.solar_target_temp)
        )

    def adopt_if_running(self) -> bool:
        """(#914) Re-own a boost SEM left on the tank across a restart.

        #656 leaves loads exactly as they are on a reload or an HA restart
        and relies on SEM re-adopting them when it comes back. The tank was
        registered with no adopter at all, so SEM came back believing it idle
        while its own boost setpoint stayed armed: the reconciler filed the
        tank as external_on, no stop path ever visited it, and the
        appliance's thermostat reheated to SEM's setpoint at any hour.

        Decided ONCE per lifetime, on the first readable observation. An
        entity whose integration is still loading keeps the window open —
        the per-cycle belief sync retries it — and after that SEM never
        claims a setpoint the user sets later.
        """
        if not self._boot_adoption_window_open():
            return False
        if self.is_active:
            # SEM started it itself this lifetime — nothing left to adopt.
            self._boot_adoption_pending = False
            return False
        if self.entity_id and self.hass and self._adoptable_now() is None:
            return False
        self._boot_adoption_pending = False
        return super().adopt_if_running()

    def sync_belief_to_observation(self) -> bool:
        """(#766 / #914) The per-cycle twin. A switch tank follows its switch
        every cycle (#766); a setpoint tank does not — only the restart
        adoption above is retried, until the entity is first readable."""
        if self._entity_domain in _SETPOINT_DOMAINS:
            return self.adopt_if_running()
        return super().sync_belief_to_observation()

    @property
    def entity_domain(self) -> Optional[str]:
        """Return the entity domain (water_heater, climate, or switch)."""
        return self._entity_domain

    @property
    def hours_since_legionella(self) -> float:
        """Hours since last Legionella prevention cycle."""
        if self._last_legionella_time is None:
            return 999.0  # Never run — trigger immediately
        delta = dt_util.now() - self._last_legionella_time
        return delta.total_seconds() / 3600

    @property
    def legionella_overdue(self) -> bool:
        """True if Legionella prevention cycle is overdue."""
        if self._legionella_blocked_until is not None and dt_util.now() < self._legionella_blocked_until:
            return False
        return self.hours_since_legionella > self.legionella_interval_hours

    @property
    def legionella_early_window(self) -> bool:
        """(#1369) The last day before the run is due (and not blocked):
        a sunny hour may start it now instead of at the due time."""
        if self._last_legionella_time is None:
            return False   # never run: it is due already
        if self._legionella_blocked_until is not None and dt_util.now() < self._legionella_blocked_until:
            return False
        h = self.hours_since_legionella
        if self.legionella_blocked_by_stop:
            return False   # the run cannot finish: nothing to start early
        return (self.legionella_interval_hours - LEGIONELLA_EARLY_WINDOW_H) < h <= self.legionella_interval_hours

    def check_heating_works(self) -> Optional[bool]:
        """(#1369) Does heating warm the tank? Only a SWITCHED heater (a
        relay on an element) is checked: a setpoint tank is usually a heat
        pump, whose power sensor may count the house heating too. Counted
        only while SEM runs it and a MEASURED draw (power sensor or energy
        counter) shows at least half its rating. Two hours of that draw with
        less than 1 °C of rise, below the target, is a fault. The fault
        holds until a later run warms the tank again — then it clears, also
        after a restart (the repair outlives the process).

        Returns True when the fault starts, False when it clears, None when
        nothing changed."""
        now = dt_util.now()
        temp = self.get_current_temperature()
        rated = float(getattr(self, "rated_power", 0.0) or 0.0)
        watts = None
        if getattr(self, "power_entity_id", None) or getattr(self, "energy_entity_id", None):
            try:
                watts = self.observed_power_w()
            except Exception:  # noqa: BLE001 — an unread draw counts nothing
                watts = None
        # (#1369) on, but drawing nothing below its target: the boiler's own
        # thermostat cut it off — the user is told at which temperature
        idle_on = (self._entity_domain not in _SETPOINT_DOMAINS
                   and self.is_active and temp is not None and rated > 0
                   and watts is not None and watts < max(50.0, 0.05 * rated)
                   and float(temp) < self._active_target_temp() - 1.0)
        if idle_on:
            if getattr(self, "_cutout_since", None) is None:
                self._cutout_since = now
            elif (now - self._cutout_since).total_seconds() >= OWN_THERMOSTAT_MINUTES * 60:
                self.own_thermostat_c = round(float(temp), 1)
        else:
            self._cutout_since = None
            if watts is not None and rated > 0 and watts >= 0.5 * rated:
                self.own_thermostat_c = None     # it heats again
        running = (self._entity_domain not in _SETPOINT_DOMAINS
                   and self.is_active and temp is not None and rated > 0
                   and watts is not None and watts >= 0.5 * rated)
        if not running:
            self._heat_check = None
            return None
        start = getattr(self, "_heat_check", None)
        if start is None:
            self._heat_check = (now, float(temp))
            return None
        t0, temp0 = start
        if float(temp) - temp0 >= HEAT_MIN_RISE_K:
            self._heat_check = (now, float(temp))
            # a warming tank clears the repair: always when this process
            # raised it, and once after a restart (it may still be filed)
            if getattr(self, "heating_fault", False) or not getattr(self, "_heat_clear_sent", False):
                self.heating_fault = False
                self._heat_clear_sent = True
                return False
            return None
        minutes = (now - t0).total_seconds() / 60.0
        if (minutes >= HEAT_CHECK_MINUTES and not getattr(self, "heating_fault", False)
                and float(temp) < self._active_target_temp() - 2.0):
            self.heating_fault = True
            self.heating_fault_temp = float(temp)
            self._heat_clear_sent = False
            return True
        return None

    def _end_legionella_run(self) -> None:
        """(#1335) The run is over. The device never switches itself: while
        the tank is on, ``own_run_ending`` asks the load engine to stop it
        once, through the one place that switches loads."""
        self._legionella_cycle_active = False
        self._legionella_hold_start = None
        self._legionella_started_at = None
        self._legionella_end_pending = self.is_active
        # (#1369) nothing of this run carries into the next one
        self._unread_since = None
        self._hold_unread_min = 0.0
        self._hold_stopped = False

    @property
    def own_run_ending(self) -> bool:
        """(#1335) The Legionella run ended with the tank still on: stop it."""
        return self._legionella_end_pending is True and self.is_active

    async def _end_unreachable_legionella(self, path: str, why: str,
                                          started: bool = True) -> str:
        """(#1102) End a cycle that cannot reach its target. It is NOT a
        disinfection: ``_last_legionella_time`` stays, and the next try waits
        one full interval, so the run cannot switch the tank on again and
        again on grid power."""
        if started:
            self._end_legionella_run()
        else:
            # (#1369) the run never started: nothing of SEM's is running for
            # it, so nothing may be stopped for it — a sun run goes on
            self._legionella_cycle_active = False
            self._legionella_hold_start = None
            self._legionella_started_at = None
        self._legionella_blocked_until = dt_util.now() + timedelta(
            hours=self.legionella_interval_hours)
        _LOGGER.warning(
            "Legionella cycle for %s ended without reaching %.0f°C: %s. "
            "Next try in %.0f h.", self.name, self.legionella_target_temp, why,
            self.legionella_interval_hours)
        self._last_legionella_path = path
        return f"legionella_{path}"

    def _legionella_unit_max(self) -> "float | None":
        """(#1396) The tank's own max_temp: the live number when it gives one
        (and remembered), else the last known one while a run is on — a tank
        that goes unavailable mid-run keeps its run's reach. None when no
        number was ever seen: then everything is as before."""
        try:
            _lo, hi = self.sp_unit_range(self.entity_id)
        except Exception:  # noqa: BLE001
            hi = None
        if hi is not None:
            self._legionella_known_max = hi
            return hi
        if self._legionella_cycle_active:
            return getattr(self, "_legionella_known_max", None)
        return None

    @property
    def legionella_above_unit_max(self) -> "float | None":
        """(#1396) The tank's max when the set Legionella target is above it
        (the tank cannot reach the target), else None."""
        hi = self._legionella_unit_max()
        if hi is not None and hi < float(self.legionella_target_temp):
            return hi
        return None

    @property
    def legionella_reach_c(self) -> float:
        """(#1396) The temperature a Legionella run waits for: the set target,
        or the tank's own maximum when the tank reports a lower one — it is
        never sent more, so a run waiting for more would never end. A
        Repair says the target cannot be reached."""
        hi = self.legionella_above_unit_max
        return float(hi) if hi is not None else float(self.legionella_target_temp)

    @property
    def legionella_hold_minutes(self) -> int:
        """Hold duration based on target temperature."""
        target = int(self.legionella_target_temp)
        # Find the closest threshold
        for temp in sorted(LEGIONELLA_HOLD_MINUTES.keys()):
            if target <= temp:
                return LEGIONELLA_HOLD_MINUTES[temp]
        return 3  # 80°C+ = 3 minutes

    def _band_fields_top_c(self) -> Optional[float]:
        """(#1369) The top the band's FIELDS set — Keep at + Extra in °C,
        capped at the Legionella target (the hottest SEM ever heats a tank)
        — whatever the thermometer reads now. None without a heating band
        whose limit sits below its target."""
        t, lim = getattr(self, "comfort_target", None), getattr(self, "comfort_limit", None)
        if not (t and lim):
            return None
        if getattr(self, "_comfort_direction", lambda: "heat")() != "heat":
            return None
        try:
            target_c, offset_c, limit_c = self._comfort_thresholds_c()
            top = float(target_c) + max(0.0, float(offset_c or 0.0))
        except (TypeError, ValueError, AttributeError):
            return None
        if limit_c >= target_c:
            return None   # misconfigured: the band is disengaged
        return min(top, float(self.legionella_target_temp))

    def user_stop_c(self) -> Optional[float]:
        """(#1369) The user's own "Stop when" on the tank's temperature, in
        °C — when it reads the tank thermometer or the band's. None for a
        stop on any other sensor (that one says nothing about the tank)."""
        entity = getattr(self, "stop_entity", "") or ""
        at = float(getattr(self, "stop_at", 0.0) or 0.0)
        if not entity or at <= 0:
            return None
        if entity not in {getattr(self, "temperature_entity_id", None),
                          getattr(self, "comfort_entity", None)}:
            return None
        # the stop compares the sensor's own reading, so its own unit says
        # what the typed number means
        unit = ""
        try:
            st = self.hass.states.get(entity) if self.hass else None
            unit = str((st.attributes or {}).get("unit_of_measurement", "")) if st else ""
        except Exception:  # noqa: BLE001 — no unit read: as typed
            unit = ""
        if unit.endswith("F"):
            return (at - 32.0) * 5.0 / 9.0
        return at

    @property
    def legionella_due_within_a_day(self) -> bool:
        """(#1369) A run is due, or due within the early window — whatever
        blocks it. The card names a blocked run only then."""
        if self._last_legionella_time is None:
            return True
        return self.hours_since_legionella > (
            self.legionella_interval_hours - LEGIONELLA_EARLY_WINDOW_H)

    @property
    def legionella_blocked_by_stop(self) -> bool:
        """(#1369) The user's stop sits below the Legionella target: a run
        can never reach it. SEM says so and starts no early run for it."""
        stop = self.user_stop_c()
        return stop is not None and stop < self.legionella_reach_c   # (#1396)

    def band_top_c(self, *, peek: bool = False) -> Optional[float]:
        """(#1369) The top a USABLE comfort band sets, or None when the tank
        has no band, the band is misconfigured or its thermometer is silent
        (then it is disengaged and the old Solar Heating Target caps the
        tank as before)."""
        # ``comfort_state`` is the band as the engine sees it: disengaged
        # while away too, so away keeps the old target (#594)
        # (#1369) ``peek``: the shadow asks without the misconfiguration flag
        state = (self._peek_comfort_state() if peek
                 else getattr(self, "comfort_state", "disengaged"))
        if state == "disengaged":
            return None
        return self._band_fields_top_c()

    def normal_target_temp(self, *, peek: bool = False) -> float:
        """(#1369) The cutoff outside Legionella and the vacation dump: the
        band's top when the tank has a band — the band decides alone, as on
        the my-PV and evcc controllers — else the Solar Heating Target."""
        top = self.band_top_c(peek=peek)
        return top if top is not None else self.solar_target_temp

    def _active_target_temp(self, *, peek: bool = False) -> float:
        """The temperature target for the CURRENT operating context (#594).

        Legionella cycle → ``legionella_target_temp`` (disinfection is never
        run during vacation — the coordinator pauses cycles, see
        ``check_legionella_cycle``). Vacation surplus dump →
        ``min_temperature`` (free solar energy without comfort heating).
        Normal solar boost → ``normal_target_temp()`` (#1369: the band's
        top when there is a band, else ``solar_target_temp``).
        """
        if self._legionella_cycle_active:
            return self.legionella_target_temp
        if self.vacation and self.vacation_dhw_surplus:
            return self.min_temperature
        return self.normal_target_temp(peek=peek)

    # (#1380) the owner's path names -> the ones the #420 telemetry kept
    _TEMP_PATH_LABELS = {
        "sensor": "separate_sensor",
        "sensor_invalid": "separate_sensor_invalid",
        "sensor_unavailable": "separate_sensor_unavailable",
        "sensor_missing": "separate_sensor_missing",
    }

    # (#1380) the tank's own reading leads, as it always did: a picked
    # sensor only answers when the entity gives none
    own_entity_first = True

    @property
    def own_temperature_entity_id(self) -> Optional[str]:
        """A water_heater / climate tank reports its own temperature."""
        return self.entity_id if self._entity_domain in _SETPOINT_DOMAINS else None

    def get_current_temperature(self) -> Optional[float]:
        """Water temperature in °C via the one owner (#1380); records the
        source on ``_last_temperature_reading_path`` (#420 telemetry)."""
        from .temperature import temperature_reading
        r = temperature_reading(self.hass, self)
        self._last_temperature_reading_path = self._TEMP_PATH_LABELS.get(r.path, r.path)
        self._last_temperature_reading = r.value
        return r.value

    def is_temperature_safe(self) -> bool:
        """Check if temperature is below the active target.

        During normal solar boost: cutoff is solar_target_temp — or, with a
        usable comfort band, the band's top (Keep at + Extra, #1369).
        During Legionella cycle: cutoff is legionella_target_temp.

        Records which branch fired on
        ``self._last_temperature_safety_path`` (#420).

        Sensor-unavailable distinction (v1.7.2, 2026-06-07):
        * ``no_sensor_configured`` — user never configured a sensor.
          Returns ``True`` so SEM can drive the device and rely on the
          device's own internal thermostat (by design).
        * ``configured_sensor_broken`` — user DID configure a sensor
          but it is currently ``unavailable`` / ``unknown`` / invalid.
          Returns ``False`` (fail-safe). Without this, a broken
          temperature sensor would let SEM activate the heater
          indefinitely, relying only on the device's thermostat —
          fine when the device's thermostat is healthy, dangerous if
          the sensor failure is correlated with broader hardware issues.
        """
        temp = self.get_current_temperature()
        if temp is None:
            # ``get_current_temperature`` already recorded WHY the read
            # returned None on ``_last_temperature_reading_path``. We
            # use that to split the silent-failure case from the
            # genuinely-unconfigured case.
            reading_path = self._last_temperature_reading_path or "uninitialized"
            if reading_path == "no_source_configured":
                self._last_temperature_safety_path = "no_sensor_configured"
                return True  # No sensor — allow operation (rely on thermostat)
            # Sensor configured but broken — fail-safe.
            self._last_temperature_safety_path = "configured_sensor_broken"
            return False
        if self._legionella_cycle_active:
            if temp < self.legionella_reach_c:        # (#1396) the tank's max at most
                self._last_temperature_safety_path = "in_legionella_cycle_below_target"
                return True
            self._last_temperature_safety_path = "in_legionella_cycle_at_target"
            return False
        if (self.vacation and self.vacation_dhw_surplus
                and not self.comfort_away_heats(self.is_active)):
            # #594 — surplus dump caps at the MINIMUM temperature target,
            # not the solar comfort target. (#1344) A too-cold run is not
            # the dump: the user's limit heats back above itself.
            if temp < self.min_temperature:
                self._last_temperature_safety_path = "vacation_below_min_target"
                return True
            self._last_temperature_safety_path = "vacation_at_min_target"
            return False
        # (#1369) a band decides the top alone; the Solar Heating Target
        # caps only a tank without one
        top = self.band_top_c()
        if top is not None:
            # the band's own thermometer decides, the same reading that
            # engaged it (the tank sensor answers when they are the same)
            band_temp = self._comfort_reading()
            if band_temp is not None:
                temp = float(band_temp)
            if temp < top:
                self._last_temperature_safety_path = "normal_below_band_top"
                return True
            self._last_temperature_safety_path = "normal_at_band_top"
            return False
        if temp < self.solar_target_temp:
            self._last_temperature_safety_path = "normal_below_solar_target"
            return True
        self._last_temperature_safety_path = "normal_at_solar_target"
        return False

    @property
    def start_refusal(self) -> Optional[str]:
        """(#1335) Why ``activate`` would refuse a start right now: ``"sensor"``
        (a temperature sensor is set up but reads nothing — fail-safe) or
        ``"at_target"`` (the tank is at the active target). None = it may
        start. Layer 1 reads this and says so, so a start is never refused
        in silence; ``activate`` keeps the same check as a backstop."""
        if self.is_temperature_safe():
            if self._legionella_cycle_active:
                return None
            lines = [v for v in (self.band_top_c(), self.user_stop_c()) if v is not None]
            # below the user's own "Run now past" it always starts
            if lines and getattr(self, "comfort_state", "") != "forced":
                reading = None
                try:
                    reading = self._comfort_reading()
                except Exception:  # noqa: BLE001
                    reading = None
                if reading is None:
                    reading = self.get_current_temperature()
                if reading is not None:
                    edge = min(lines) - START_MARGIN_K
                    # once refused, it waits a little more: no flip on noise
                    if getattr(self, "_margin_refused", False):
                        edge -= START_MARGIN_STICKY_K
                    refused = float(reading) > edge
                    self._margin_refused = refused
                    if refused:
                        return "at_target"   # (#1369) too close to its top to start
            self._margin_refused = False
            return None
        self._margin_refused = False
        if self._last_temperature_safety_path == "configured_sensor_broken":
            return "sensor"
        return "at_target"

    @property
    def own_run_needs_heat(self) -> bool:
        """(#1369) Does the Legionella run need the heater now? Not while the
        tank holds at or above its target — the hold needs no heat."""
        if not self._legionella_cycle_active:
            return False
        temp = self.get_current_temperature()
        if temp is None:
            return True
        floor = self.legionella_reach_c          # (#1396) the tank's max at most
        if self._legionella_hold_start is not None:
            floor -= LEGIONELLA_HOLD_DIP_K   # the hold's own noise margin
        return temp < floor

    @property
    def runs_without_surplus(self) -> bool:
        """(#1121) A Legionella run heats to its target sun or not;
        ``check_legionella_cycle`` ends it."""
        return self._legionella_cycle_active

    @property
    def stop_condition_met(self) -> bool:
        """(#1062) A running SWITCH boiler stops at the active target.

        The target gate in ``activate`` only refuses a START. A water_heater or
        climate tank holds the setpoint SEM wrote, so its own thermostat stops
        it there; a relay has no setpoint, and a boiler switched on below the
        target kept heating past it for as long as the surplus lasted. Only a
        real reading counts — a sensor that reads nothing is not a hot tank.

        During a Legionella cycle SEM's own stops do not apply: this target and
        a banked comfort band both sit below the disinfection target, and
        ``check_legionella_cycle`` ends the run itself. A stop entity the user
        set still counts, as it did before (#1062).
        """
        met, hold = self._stop_condition(
            getattr(self, "_hold_stopped", False),
            read=self.get_current_temperature,
            read_goal=lambda: self._goal_reading(peek=False),
            band_state=lambda: self.comfort_state,
            target=lambda: self._stop_target_temp(peek=False))
        if hold is not None:
            self._hold_stopped = hold
        return met

    def _goal_reading(self, *, peek: bool):
        """(#1369, C1) ONE thermometer for the start and the stop: the band's
        sensor when a usable band is set, else the tank's. A switched tank's
        stop read the tank sensor while its start read the band's."""
        keep, _extra, limit = self._goal_band_fields()
        # only while the band is engaged: away it is disengaged and the away
        # dump's start compares the TANK sensor with the minimum temperature
        if (keep is not None and limit is not None and limit < keep
                and self._peek_comfort_state() != "disengaged"):
            band = self._comfort_reading()
            if band is not None:
                return band
        return self._peek_tank_reading()[0] if peek else self.get_current_temperature()

    def _stop_target_temp(self, *, peek: bool) -> float:
        """(#1369, C2) The stop's cutoff: ``_active_target_temp``, except that
        away with the dump a too-cold tank heats back above its limit + the
        start gap, not just to the minimum temperature. Setpoint writes keep
        ``_active_target_temp``."""
        base = self._active_target_temp(peek=peek)
        if (self._legionella_cycle_active or getattr(self, "vacation", False) is not True
                or getattr(self, "vacation_dhw_surplus", False) is not True):
            return base
        if not self.comfort_away_heats(self.is_active, peek=peek):
            return base
        limit_c = float(self._comfort_thresholds_c()[2])
        return max(base, limit_c + self.comfort_goal_start_gap_c())

    def _stop_condition(self, hold_stopped, *, read, band_state, target, read_goal=None):
        """(#1369) The stop rule, PURE: ``(met, new_hold_stopped)`` — the new
        hold flag is None when the rule leaves it alone. It writes nothing;
        what it reads comes in as callables (called lazily, in the order the
        rule always asked), so the property passes the getters that keep
        their telemetry and the shadow comparison passes peeks that do not.
        One rule for both: the shadow cannot change a decision by running."""
        if self._legionella_cycle_active:
            # The base stop only (the stop entity) — skip the band's banked.
            if super(ComfortBandMixin, self).stop_condition_met:
                return True, None
            # (#1369) a switched tank in its hold: off a little above the
            # target — the tank holds the heat; before, it heated on to +3 K
            if (self._entity_domain not in _SETPOINT_DOMAINS
                    and self._legionella_hold_start is not None):
                temp = read()
                tgt = self.legionella_reach_c            # (#1396)
                if temp is None:
                    return bool(hold_stopped), None
                # off above target + 0.5; once off, it stays off while the
                # hold needs no heat — no flip on sensor noise
                stopped = temp >= tgt + LEGIONELLA_HOLD_BAND_K or (
                    bool(hold_stopped) and temp >= tgt - LEGIONELLA_HOLD_DIP_K)
                return stopped, stopped
            return False, None
        # the band's banked state ORs with the stop entity (ComfortBandMixin)
        if super(ComfortBandMixin, self).stop_condition_met or band_state() == "banked":
            return True, None
        if self._entity_domain in _SETPOINT_DOMAINS:
            return False, None
        temp = (read_goal or read)()
        return temp is not None and temp >= target(), None

    # ─── The tank's goal, in the shadow (#1369, step 1) ──────────────

    def _peek_tank_reading(self):
        """(#1369) ``get_current_temperature`` without its writes: the tank's
        own reading in °C and whether a missing one is fine (no source is set
        up, the device's own thermostat rules). It leaves
        ``_last_temperature_reading*`` alone (#1380: the one owner reads)."""
        from .temperature import PATH_NONE, temperature_reading
        r = temperature_reading(self.hass, self)
        return r.value, r.path == PATH_NONE

    def _goal_band_fields(self):
        """(keep, extra, limit) in °C for a set heating band, else Nones.
        ``_comfort_thresholds_c`` only reads."""
        t, lim = getattr(self, "comfort_target", None), getattr(self, "comfort_limit", None)
        if not (t and lim) or self._comfort_direction() != "heat":
            return None, None, None
        try:
            keep, extra, limit = self._comfort_thresholds_c()
            return float(keep), float(extra or 0.0), float(limit)
        except (TypeError, ValueError, AttributeError):
            return None, None, None

    def tank_goal_inputs(self) -> TankInputs:
        """(#1369) What the goal reads, from the controller's own fields.
        Read-only. Getters AVOIDED because they write state:
        ``get_current_temperature`` / ``is_temperature_safe`` /
        ``own_run_needs_heat`` (``_last_temperature_*``), ``start_refusal``
        (``_margin_refused``), ``stop_condition_met`` (``_hold_stopped``) and
        ``comfort_state`` / ``comfort_away_heats`` / ``_comfort_band_state``
        (the one-time misconfiguration warning flag). Their stored fields
        are read raw; the band state comes from ``_peek_comfort_state``."""
        keep, extra, limit = self._goal_band_fields()
        tank_c, blind_ok = self._peek_tank_reading()
        user_stop = self.user_stop_c()
        return TankInputs(
            tank_c=tank_c, band_c=self._comfort_reading(),
            keep_c=keep, extra_c=extra, too_cold_c=limit,
            fallback_top_c=float(self.solar_target_temp),
            min_temperature_c=float(self.min_temperature),
            legionella_target_c=float(self.legionella_target_temp),
            user_stop_c=user_stop,
            # the base stop rule (the stop entity) is a plain read; a stop on
            # the tank's or the band's sensor is the goal's own user stop
            other_stop_met=(user_stop is None and bool(
                super(ComfortBandMixin, self).stop_condition_met)),
            legionella_active=self._legionella_cycle_active is True,
            legionella_hold=self._legionella_hold_start is not None,
            hold_stopped=bool(getattr(self, "_hold_stopped", False)),
            margin_refused=bool(getattr(self, "_margin_refused", False)),
            vacation=getattr(self, "vacation", False) is True,
            vacation_dump=getattr(self, "vacation_dhw_surplus", False) is True,
            may_buy=self.comfort_goal_may_buy(),
            switched=self._entity_domain not in _SETPOINT_DOMAINS,
            sensor_expected=not blind_ok,
            start_gap_c=self.comfort_goal_start_gap_c(),
            away_floor_open=(self.is_active and getattr(self, "_comfort_floor_run", False) is True
                             and self.comfort_away_floor_open()),
            now=dt_util.now())

    def tank_goal(self) -> TankGoal:
        """(#1369) The tank's goal this cycle. Nothing decides by it yet."""
        return build_tank_goal(self.tank_goal_inputs())

    def _goal_seen(self, engine_stop=RECOMPUTE) -> Dict[str, Any]:
        """What today's code decided, per compared field. The top is the
        cutoff the engine uses (active target, the user's stop below it).
        PURE (#1369): every read is a peek; ``engine_stop`` is the engine's
        own answer for this cycle where it gave one (True/False), None where
        the engine never asked this cycle (the field is left out and counted
        as skipped), ``RECOMPUTE`` to ask the pure stop rule."""
        keep, _extra, limit = self._goal_band_fields()
        top = self._stop_target_temp(peek=True)
        stop = self.user_stop_c()
        if stop is not None and not self._legionella_cycle_active:
            top = min(top, stop)
        seen = {"top": top, "keep_at": keep, "too_cold_below": limit,
                "band_state": self._peek_comfort_state(),
                "legionella_blocked": self.legionella_blocked_by_stop}
        if engine_stop is RECOMPUTE:
            seen["must_stop"] = self._stop_condition(
                getattr(self, "_hold_stopped", False),
                read=lambda: self._peek_tank_reading()[0],
                read_goal=lambda: self._goal_reading(peek=True),
                band_state=self._peek_comfort_state,
                target=lambda: self._stop_target_temp(peek=True))[0]
        elif engine_stop is not None:
            seen["must_stop"] = bool(engine_stop)
        return seen

    def compare_tank_goal(self, engine_stop=RECOMPUTE) -> None:
        """(#1369) Once per cycle, after the engine decided for this tank:
        count where the goal differs from today's decision. Never raises.
        It writes NOTHING but its own counters — it runs after every
        decision, also the early returns where the engine never reads the
        stop rule, so a write here would change the next cycle's decision."""
        try:
            seen = self._goal_seen(engine_stop)
            if "must_stop" not in seen:
                self.tank_goal_skipped += 1   # the engine did not ask this cycle
            for name, pair in differences(self.tank_goal(), seen).items():
                self.tank_goal_diffs[name] = self.tank_goal_diffs.get(name, 0) + 1
                self.tank_goal_last[name] = pair
                log_on_change(
                    _LOGGER, f"tank_goal:{self.device_id}:{name}", logging.INFO,
                    "%s: the tank goal differs from today's decision on %s "
                    "(shadow only, nothing changed; #1369)", self.name, name)
        except Exception:  # noqa: BLE001 — the shadow must never break a cycle
            self.tank_goal_errors += 1

    # (#594/#1344) it heats for comfort by nature: away pauses it, band or
    # not. The band itself goes quiet while away in the shared mixin; the
    # vacation surplus dump keeps its own cap (``_active_target_temp``).
    away_needs_band = False

    def _comfort_fallback_reading(self):
        """(#1062) The band's thermometer when none is picked: the tank's own
        reading in °C, from the one owner (#1380). The Control tab says
        "device's own thermometer"."""
        if not self.hass:
            return None
        from .temperature import read_device_temperature
        return read_device_temperature(self.hass, self)

    @property
    def needs_offpeak_activation(self) -> bool:
        """Temperature-aware override: don't force-heat at the active target."""
        if self.vacation:
            # #594 — no cheap-tariff comfort forcing while away (the optional
            # surplus dump is solar-surplus-only by design).
            return False
        if not super().needs_offpeak_activation:
            return False
        if not self.is_temperature_safe():
            return False
        return True

    async def activate(self, available_watts: float) -> float:
        """Activate hot water heating with temperature safety check.

        Records the activation branch on ``self._last_activation_path`` (#420):
        ``blocked_unsafe`` / ``water_heater`` / ``climate`` / ``switch_fallback``
        / ``vacation_blocked`` (#594).

        #594: while vacation mode is active there is no comfort heating.
        With the opt-in ``vacation_dhw_surplus`` the tank may still take
        surplus, capped at ``min_temperature`` (see ``_active_target_temp``
        and the vacation branch in ``is_temperature_safe``).
        """
        if (self.vacation and not self.vacation_dhw_surplus
                and not self.comfort_away_heats(self.is_active)):
            # (#1344) the too-cold limit is the one run away leaves
            self._last_activation_path = "vacation_blocked"
            return 0.0
        if not self.is_temperature_safe():
            _LOGGER.info(
                "Hot water at %.1f°C — target %.1f°C reached, skipping",
                self.get_current_temperature() or 0,
                self._active_target_temp(),
            )
            self._last_activation_path = "blocked_unsafe"
            return 0.0

        # Use appropriate control method based on entity type
        if self._entity_domain == "water_heater":
            self._last_activation_path = "water_heater"
            return await self._activate_water_heater()
        elif self._entity_domain == "climate":
            self._last_activation_path = "climate"
            return await self._activate_climate()
        else:
            self._last_activation_path = "switch_fallback"
            return await super().activate(available_watts)

    async def deactivate(self) -> None:
        """Deactivate hot water heating.

        Records the deactivation branch on
        ``self._last_deactivation_path`` (#420).
        """
        if self._entity_domain == "water_heater":
            self._last_deactivation_path = "water_heater"
            await self._deactivate_water_heater()
        elif self._entity_domain == "climate":
            self._last_deactivation_path = "climate"
            await self._deactivate_climate()
        else:
            self._last_deactivation_path = "switch_fallback"
            await super().deactivate()

    @property
    def target_stale(self) -> bool:
        """(#1335) A running water_heater / climate tank holds a setpoint SEM
        wrote for another target (a Legionella run began, vacation moved the
        cap to the minimum). ``adjust_power`` writes the current one."""
        if self._entity_domain not in _SETPOINT_DOMAINS or not self.is_active:
            return False
        written = self._written_target
        return written is not None and abs(written - self._active_target_temp()) > _BOOST_SETPOINT_MATCH_K

    async def adjust_power(self, available_watts: float) -> float:
        """A tank is on or off; only a stale setpoint is written again."""
        if self.target_stale:
            if self._entity_domain == "water_heater":
                await self._activate_water_heater()
            else:
                await self._activate_climate()
        return await super().adjust_power(available_watts)

    def _claim_active(self, target: float) -> float:
        self._written_target = target
        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        return self.rated_power

    async def _activate_water_heater(self) -> float:
        """Activate via water_heater domain.

        (#1335) Claims ACTIVE only when the setpoint really went out: a write
        the seam withheld (observer, yield) moved nothing."""
        try:
            target = self._active_target_temp()
            # (#1081) remembers the tank's own setpoint before SEM moves it
            sent = await self.sp_write_target(
                "water_heater", self.entity_id, target, why="hot water heating")
            if not sent:
                # (#1396) refused by the unit (the next try waits) or withheld
                self._last_activation_path = (
                    "water_heater_refused" if self.sp_refused else "water_heater_withheld")
                return 0.0
            # Try turn_on if supported
            try:
                await self.send(
                    "water_heater", "turn_on",
                    {"entity_id": self.entity_id}, why="hot water heating")
            except Exception:
                pass  # Not all water_heater entities support turn_on
            return self._claim_active(target)
        except Exception as e:
            _LOGGER.error("Failed to activate water_heater: %s", e)
            return 0.0

    async def _deactivate_water_heater(self) -> None:
        """Deactivate via water_heater domain. A withheld write leaves the
        belief as it is (#1335): the tank did not move."""
        try:
            sent = await self.send(
                "water_heater", "turn_off",
                {"entity_id": self.entity_id}, why="hot water off")
        except Exception:
            # (#1081) A tank with no off: its minimum IS SEM's off state, so
            # the setpoint it had is not put back — SEM holds it at the minimum
            log_on_change(
                _LOGGER, f"tank-no-off:{self.device_id}", logging.INFO,
                "%s: tank has no off; SEM holds it at its minimum (#1081)",
                self.name)
            try:
                # (#1396) capped at the tank's range, sent directly
                sent = await self.sp_send_capped(
                    "water_heater", self.entity_id, self.min_temperature,
                    why="hot water off")
            except Exception as e:
                # (#1396) refused: the tank still holds SEM's target. The
                # memo stays and the tank is not counted idle, so the next
                # cycle tries the minimum again.
                _LOGGER.error("Failed to deactivate water_heater: %s", e)
                self._last_deactivation_path = "water_heater_minimum_refused"
                return
            if sent:
                # the memo goes only once the minimum has landed
                self._sp_memo = None
        else:
            if sent:
                # (#1081) off first: the tank's own setpoint goes back after
                await self.sp_restore("hot water off")
        if not sent:
            self._last_deactivation_path = "water_heater_withheld"
            return
        self._written_target = None
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0

    async def _activate_climate(self) -> float:
        """Activate via climate domain (#1335: only a sent write claims ACTIVE)."""
        try:
            target = self._active_target_temp()
            sent = await self.sp_write_target(
                "climate", self.entity_id, target, why="hot water heating")
            if not sent:
                # (#1396) refused by the unit (the next try waits) or withheld
                self._last_activation_path = (
                    "climate_refused" if self.sp_refused else "climate_withheld")
                return 0.0
            await self.send(
                "climate", "set_hvac_mode",
                {"entity_id": self.entity_id, "hvac_mode": "heat"},
                why="hot water heating")
            return self._claim_active(target)
        except Exception as e:
            _LOGGER.error("Failed to activate climate for hot water: %s", e)
            return 0.0

    async def _deactivate_climate(self) -> None:
        """Deactivate via climate domain (#1335: a withheld write moves nothing)."""
        await self.sp_restore("hot water off")   # (#1081) before it is turned off
        try:
            sent = await self.send(
                "climate", "set_hvac_mode",
                {"entity_id": self.entity_id, "hvac_mode": "off"},
                why="hot water off")
        except Exception as e:
            _LOGGER.error("Failed to deactivate climate for hot water: %s", e)
            sent = True
        if not sent:
            self._last_deactivation_path = "climate_withheld"
            return
        self._written_target = None
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0

    # ─── Legionella Prevention ───────────────────────────────

    async def check_legionella_cycle(self, good_hour: bool = False,
                                     sun_holds: Optional[bool] = None,
                                     cheap_hour: bool = False,
                                     cheap_hours_left: Optional[float] = None) -> Optional[str]:
        """Advance the Legionella prevention cycle. Never switches the tank.

        Called every coordinator cycle. Returns a status message or None.

        (#1335) This keeps the run's state only (due, hold, end, timestamps).
        The load engine switches: layer 1 starts the run from
        ``runs_without_surplus`` and stops it from ``own_run_ending``, and
        ``reconcile_load`` does both. So a Legionella start is SEM's own
        command like any other — Mode Off and teardown stop it, the minimum
        run and rest apply, and the decision log names it.

        Logic:
        1. If tank naturally reached ≥60°C → record timestamp, no forced cycle
        2. If overdue (>interval hours) → the run is due, heat to target, hold
        3. If cycle active → check hold duration, complete when done

        Records which branch fired on ``self._last_legionella_path`` (#420):
        ``natural_achievement`` / ``hold_reached_target`` /
        ``hold_in_progress`` / ``heating_to_target`` / ``overdue_start`` /
        ``overdue_no_sensor`` / ``idle`` / ``vacation_paused`` /
        ``vacation_aborted`` (#594).

        #594 vacation: cycles are PAUSED — no disinfection while away.
        ``_last_legionella_time`` is deliberately NOT touched, so
        ``hours_since_legionella`` keeps accumulating; when the interval
        elapses during the vacation, the normal overdue branch fires on the
        first post-vacation cycle (run-on-return). An in-flight cycle ends
        once and re-runs on return via the same overdue path.
        """
        # (#1369) how long the good hour has held, or been gone: the early
        # start and the early pause both wait it out
        now = dt_util.now()
        # (#1369) an early run STARTS on a good hour (80 % of the rating)
        # and keeps going while the sun holds (half the rating)
        holds = good_hour if sun_holds is None else bool(sun_holds)
        # (#1368) a cheap hour counts when the cheap hours left before the
        # run is due are just enough for it — the latest cheap start
        cheap_ok = False
        if cheap_hour and self._last_legionella_time is not None:
            left_h = self.legionella_interval_hours - self.hours_since_legionella
            if self._legionella_cycle_active and getattr(self, "_cheap_run", False):
                # a run the cheap hour started goes on through it: a price
                # forecast that arrives mid-run must not pause it
                cheap_ok = True
            elif cheap_hours_left is None:
                cheap_ok = left_h <= LEGIONELLA_CHEAP_WINDOW_H
            else:
                run_h = min(float(LEGIONELLA_MAX_RUN_HOURS), max(
                    LEGIONELLA_MIN_RUN_H,
                    float(getattr(self, "_legionella_last_run_h", None)
                          or LEGIONELLA_DEFAULT_RUN_H)))
                need_h = run_h * LEGIONELLA_CHEAP_MARGIN + LEGIONELLA_CHEAP_SLACK_H
                cheap_ok = (left_h <= LEGIONELLA_EARLY_WINDOW_H
                            and float(cheap_hours_left) <= need_h)
        if cheap_ok:
            good_hour = holds = True
        elif getattr(self, "_cheap_held", False) and not holds:
            # a tariff does not flicker: when the cheap hour ends the run
            # pauses at once, not after the 30 min a cloud gets
            self._bad_since = now - timedelta(minutes=LEGIONELLA_EARLY_PAUSE_HOLD_MIN)
            self._bad_forced = True
        self._cheap_held = cheap_ok
        if good_hour:
            if getattr(self, "_good_since", None) is None:
                self._good_since = now
        else:
            self._good_since = None
        if holds:
            self._bad_since = None
            self._bad_forced = False
        elif getattr(self, "_bad_since", None) is None:
            self._bad_since = now
        good_held = (getattr(self, "_good_since", None) is not None and
                     (now - self._good_since).total_seconds() >= LEGIONELLA_EARLY_START_HOLD_MIN * 60)
        bad_held = (getattr(self, "_bad_since", None) is not None and
                    (now - self._bad_since).total_seconds() >= LEGIONELLA_EARLY_PAUSE_HOLD_MIN * 60)

        # (#1335) An end the engine already acted on (or that a user beat
        # it to) is done.
        if self._legionella_end_pending and not self.is_active:
            self._legionella_end_pending = False

        temp = self.get_current_temperature()

        # 1. Natural achievement: solar heated to ≥60°C. (#1369) Deliberately
        # 60 °C, not the user's target: 60 is the recognised bar; a higher target
        # is the forced run's margin, and counting it would buy grid heat daily.
        if temp is not None and temp >= DEFAULT_LEGIONELLA_MIN_TEMP and not self._legionella_cycle_active:
            self._last_legionella_time = dt_util.now()
            self._last_legionella_path = "natural_achievement"
            return None

        # 1b. Vacation pause (#594) — after the natural-achievement record
        # (a tank that reached 60°C anyway IS disinfected), before any
        # forced heating.
        if self.vacation:
            if self._legionella_cycle_active:
                self._end_legionella_run()
                _LOGGER.info(
                    "Legionella cycle aborted: vacation mode active — "
                    "will re-run when vacation ends"
                )
                self._last_legionella_path = "vacation_aborted"
                return "legionella_vacation_paused"
            self._last_legionella_path = "vacation_paused"
            return "legionella_vacation_paused" if self.legionella_overdue else None

        # 2. Cycle in progress — check hold
        if self._legionella_cycle_active:
            # (#1369) once the hold runs, a reading inside the noise margin is
            # still the hold — so it also completes there
            if temp is None:
                if getattr(self, "_unread_since", None) is None:
                    self._unread_since = now
                unread_min = (now - self._unread_since).total_seconds() / 60.0
                if unread_min > LEGIONELLA_UNREAD_END_MIN:
                    # (#1369) SEM does not heat blind: end the run, no block
                    self._end_legionella_run()
                    self._legionella_early = False
                    self._unread_since = None
                    self._last_legionella_path = "no_reading"
                    return "legionella_no_sensor"
            else:
                # (#1369) unread minutes are no hold: the hold's clock pauses
                # through them (a glitch under the grace is not counted out)
                if (getattr(self, "_unread_since", None) is not None
                        and self._legionella_hold_start is not None):
                    gap = (now - self._unread_since).total_seconds() / 60.0
                    if gap > LEGIONELLA_UNREAD_HOLD_GRACE_MIN:
                        self._hold_unread_min = float(getattr(self, "_hold_unread_min", 0.0)) + gap
                self._unread_since = None
            reach = self.legionella_reach_c       # (#1396) the tank's max at most
            in_hold = temp is not None and (
                temp >= reach
                or (self._legionella_hold_start is not None
                    and temp >= reach - LEGIONELLA_HOLD_DIP_K))
            if in_hold:
                if self._legionella_hold_start is None:
                    self._legionella_hold_start = dt_util.now()
                    _LOGGER.info(
                        "Legionella cycle: target %.0f°C reached, holding for %d min",
                        self.legionella_target_temp, self.legionella_hold_minutes,
                    )
                    self._last_legionella_path = "hold_reached_target"
                    return f"legionella_holding:{self.legionella_hold_minutes}"

                elapsed = ((dt_util.now() - self._legionella_hold_start).total_seconds() / 60
                           - float(getattr(self, "_hold_unread_min", 0.0)))
                if elapsed >= self.legionella_hold_minutes:
                    # Cycle complete
                    # (#1368) how long this run took, pauses left out: the
                    # next cheap start is timed by it
                    _st = self._legionella_started_at
                    if _st is not None:
                        # earlier parts count only when they belong to
                        # this interval (not a run given up before)
                        _before = (float(getattr(self, "_legionella_run_s", 0.0))
                                   if getattr(self, "_legionella_run_for", None)
                                   == self._last_legionella_time else 0.0)
                        self._legionella_last_run_h = round(
                            (_before + (dt_util.now() - _st).total_seconds()) / 3600.0, 2)
                    self._legionella_run_s = 0.0
                    self._cheap_run = False
                    self._end_legionella_run()
                    self._legionella_blocked_until = None
                    self._last_legionella_time = dt_util.now()
                    _LOGGER.info("Legionella prevention cycle completed at %.0f°C", temp)
                    self._last_legionella_path = "hold_complete"
                    return "legionella_complete"
                self._last_legionella_path = "hold_in_progress"
                return "legionella_holding"
            else:
                # (#1102) Your own stop applies during the run (#1062). When it
                # fires below the target, the run can never finish; before
                # this it stayed open and switched the tank back on, sun or
                # not, every time it cooled below your stop.
                if super(ComfortBandMixin, self).stop_condition_met:
                    return await self._end_unreachable_legionella(
                        "blocked_by_stop",
                        f"your stop ({self.stop_entity} >= {self.stop_at:g}) is below it")
                # (#1369) a dip below the target during the hold: the hold
                # starts over when it is back — time under 60 °C is no hold
                if (self._legionella_hold_start is not None and temp is not None
                        and temp < reach - LEGIONELLA_HOLD_DIP_K):
                    self._legionella_hold_start = None
                    self._hold_unread_min = 0.0
                    self._hold_stopped = False
                started = self._legionella_started_at
                if (started is not None and getattr(self, "_legionella_early", False)
                        and not self.legionella_overdue
                        and (dt_util.now() - started) > timedelta(hours=LEGIONELLA_MAX_RUN_HOURS)):
                    # (#1369) an early run that cannot finish ends WITHOUT a
                    # block: the due run still comes at its due time
                    self._end_legionella_run()
                    self._legionella_early = False
                    # no new early start this interval: it could not finish
                    self._early_spent_for = self._last_legionella_time
                    self._last_legionella_path = "early_timed_out"
                    return "legionella_early_paused"
                if started is not None and (dt_util.now() - started) > timedelta(hours=LEGIONELLA_MAX_RUN_HOURS):
                    return await self._end_unreachable_legionella(
                        "timed_out", f"still below it after {LEGIONELLA_MAX_RUN_HOURS:g} h")
                # (#1369) an EARLY run lives on its sunny hour: when the sun
                # goes well before it is due, it stops — not a disinfection,
                # no block — and runs again at the due time
                hours_left = self.legionella_interval_hours - self.hours_since_legionella
                if (getattr(self, "_legionella_early", False) and bad_held
                        and not self.legionella_overdue
                        and hours_left > LEGIONELLA_EARLY_PAUSE_MIN_LEAD_H):
                    if started is not None:
                        if getattr(self, "_legionella_run_for", None) != self._last_legionella_time:
                            self._legionella_run_s = 0.0
                            self._legionella_run_for = self._last_legionella_time
                        # the wait for the sun to come back is not run time
                        # (a pause at the end of a cheap hour waited nothing)
                        _waited = ((dt_util.now() - self._bad_since).total_seconds()
                                   if getattr(self, "_bad_since", None)
                                   and not getattr(self, "_bad_forced", False) else 0.0)
                        self._legionella_run_s = (
                            float(getattr(self, "_legionella_run_s", 0.0))
                            + max(0.0, (dt_util.now() - started).total_seconds() - _waited))
                    self._cheap_run = False
                    self._end_legionella_run()
                    self._legionella_early = False
                    self._last_legionella_path = "early_paused"
                    return "legionella_early_paused"
                # Still heating towards target
                self._last_legionella_path = "heating_to_target"
                return "legionella_heating"

        # 3. Check if overdue — the run is due. (#1369) In the last day
        # before that, a sunny hour (``good_hour``) starts it early.
        early = (not self.legionella_overdue and good_held
                 and self.legionella_early_window
                 and not self.legionella_blocked_by_stop
                 and getattr(self, "_early_spent_for", object()) != self._last_legionella_time)
        if self.legionella_overdue or early:
            if temp is None and early:
                # an early start needs a reading; the due run says why not
                self._last_legionella_path = "idle"
                return None
            if temp is None:
                _LOGGER.warning("Legionella cycle overdue but no temperature sensor — skipping")
                self._last_legionella_path = "overdue_no_sensor"
                return "legionella_no_sensor"

            # (#1102) your stop already met: the run could not get further.
            # (#1369) …or your stop sits below the target: it never could —
            # no heating for a run that cannot disinfect; the card says why
            if self.legionella_blocked_by_stop:
                return await self._end_unreachable_legionella(
                    "blocked_by_stop",
                    f"your stop ({self.stop_entity} >= {self.stop_at:g}) is below it",
                    started=False)
            if super(ComfortBandMixin, self).stop_condition_met:
                return await self._end_unreachable_legionella(
                    "blocked_by_stop",
                    f"your stop ({self.stop_entity} >= {self.stop_at:g}) is already met",
                    started=False)
            _LOGGER.info(
                "Legionella prevention: %.0f hours since last cycle (max %d), "
                "forcing heat to %.0f°C",
                self.hours_since_legionella,
                self.legionella_interval_hours,
                self.legionella_target_temp,
            )
            self._legionella_cycle_active = True
            self._legionella_hold_start = None
            self._legionella_started_at = dt_util.now()
            self._legionella_end_pending = False
            self._unread_since = None
            self._hold_unread_min = 0.0
            self._hold_stopped = False
            # (#1335) The run is due; layer 1 starts it regardless of sun
            # (``runs_without_surplus``) and ``reconcile_load`` switches it.
            self._legionella_early = bool(early)
            self._cheap_run = bool(early and cheap_ok)
            self._last_legionella_path = "early_start" if early else "overdue_start"
            return "legionella_started"

        self._last_legionella_path = "idle"
        return None

    def record_legionella_cycle(self, timestamp: Optional[datetime] = None) -> None:
        """Manually record a Legionella cycle (e.g. from storage restore)."""
        self._last_legionella_time = timestamp or dt_util.now()

    @property
    def legionella_hold_elapsed_minutes(self) -> Optional[float]:
        """Minutes elapsed in the current legionella hold, or None.

        Returns ``None`` when no hold is in progress. While a hold is
        running this surfaces ``elapsed_minutes`` so users can see
        progress against ``legionella_hold_minutes`` rather than just
        a binary ``legionella_cycle_active`` flag (#420).
        """
        if self._legionella_hold_start is None:
            return None
        delta = dt_util.now() - self._legionella_hold_start
        return round(delta.total_seconds() / 60, 1)

    @property
    def hours_since_legionella_or_none(self) -> Optional[float]:
        """Hours since last legionella cycle, ``None`` when never run.

        Companion to ``hours_since_legionella`` which returns a 999.0
        sentinel when ``_last_legionella_time`` is None. The sentinel
        is convenient for the overdue check (``999 > interval`` always
        fires) but leaks into sensors and ``to_dict``, making it
        indistinguishable from a genuinely very-stale reading. This
        property exposes the unambiguous ``None`` for diagnostics (#420).
        """
        if self._last_legionella_time is None:
            return None
        return round(self.hours_since_legionella, 1)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "entity_domain": self._entity_domain,
            "current_temperature": self.get_current_temperature(),
            "solar_target_temp": self.solar_target_temp,
            "min_temperature": self.min_temperature,
            "temperature_safe": self.is_temperature_safe(),
            "legionella_target_temp": self.legionella_target_temp,
            "legionella_interval_hours": self.legionella_interval_hours,
            "heating_fault": self.heating_fault,          # (#1369)
            "legionella_overdue": self.legionella_overdue,
            "legionella_cycle_active": self._legionella_cycle_active,
            "vacation": self.vacation,  # #594
            "vacation_dhw_surplus": self.vacation_dhw_surplus,  # #594
            "hours_since_legionella": round(self.hours_since_legionella, 1),
            "hours_since_legionella_or_none": self.hours_since_legionella_or_none,
            "legionella_hold_elapsed_minutes": self.legionella_hold_elapsed_minutes,
            "last_legionella_time": self._last_legionella_time.isoformat() if self._last_legionella_time else None,
            # #420 — telemetry surface (mirrors #359/#416 classifier_path
            # pattern). Each ``*_path`` string is set by the corresponding
            # method on every call; reading them tells users which branch
            # fired without needing a debug log.
            "legionella_path": self._last_legionella_path,
            "temperature_safety_path": self._last_temperature_safety_path,
            "temperature_reading_path": self._last_temperature_reading_path,
            "activation_path": self._last_activation_path,
            "deactivation_path": self._last_deactivation_path,
        })
        return d
