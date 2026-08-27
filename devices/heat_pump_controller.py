"""Heat pump SG-Ready controller for Solar Energy Management.

Implements SG-Ready (Smart Grid Ready) standard for heat pump control:
- State 1 (00): BLOCKED - utility request to reduce consumption
- State 2 (01): NORMAL - standard operation
- State 3 (10): BOOST - recommended increased consumption (solar surplus)
- State 4 (11): FORCE_ON - forced maximum consumption (high surplus/cheap price)

Control is via two relay entities (Shelly/ESPHome) mapped to SG-Ready pins.
Temperature boost via climate entity for additional thermal storage.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant

from .base import SetpointDevice, DeviceState

_LOGGER = logging.getLogger(__name__)


class SGReadyState(IntEnum):
    """SG-Ready states per standard."""
    BLOCKED = 1      # 00 - Utility block
    NORMAL = 2       # 01 - Normal operation
    BOOST = 3        # 10 - Recommended increased consumption
    FORCE_ON = 4     # 11 - Forced maximum consumption


# Relay mapping: (relay1, relay2) for each SG-Ready state.
#
# This is the SG-Ready standard truth table (BWP "SG Ready" label, also what
# Nibe/most heat pumps expect), where ``True`` = contact closed/active and the
# pair is (input1 : input2):
#   1 EVU-Sperre (blocked):        1:0
#   2 Normalbetrieb (normal):      0:0
#   3 verstärkter Betrieb (boost): 0:1
#   4 Anlaufbefehl (forced on):    1:1
#
# #523 (RienduPre, Nibe SG-Ready): the previous map was a plain 2-bit count
# (00/01/10/11) that did NOT match this standard — so SEM's BOOST drove
# (1,0), which a standard pump reads as EVU-block, turning the pump OFF on
# surplus instead of on ("the heat pump never got turned on"). Corrected to
# the standard below (confirmed against alpha innotec / gridX / SMA /
# SolarEdge — it is universal across EMS vendors). Installs whose contacts
# are wired normally-closed (NC) instead of normally-open use the per-pump
# ``invert_sg_ready`` toggle, which flips both contacts.
SG_READY_RELAY_MAP = {
    # SEM never COMMANDS state 1 — it has no ripple-control/Sperrzeiten
    # surface (#664, decided rather than built). The row stays because the
    # table is the SG-Ready standard's truth table, which the SETUP_GUIDE
    # wiring check is verified against (#655/#523).
    SGReadyState.BLOCKED:  (True,  False),  # 1:0
    SGReadyState.NORMAL:   (False, False),  # 0:0
    SGReadyState.BOOST:    (False, True),   # 0:1
    SGReadyState.FORCE_ON: (True,  True),   # 1:1
}


@dataclass
class HeatPumpStatus:
    """Heat pump operational status."""
    sg_ready_state: SGReadyState = SGReadyState.NORMAL
    current_temperature: Optional[float] = None
    target_temperature: Optional[float] = None
    cop: Optional[float] = None  # Coefficient of Performance
    is_solar_boosted: bool = False
    boost_start_time: Optional[datetime] = None


class HeatPumpController(SetpointDevice):
    """SG-Ready heat pump controller.

    Registers as a SetpointDevice in the SurplusController.
    When surplus is available, switches to BOOST or FORCE_ON mode
    and optionally increases the temperature setpoint.

    Typical priority: battery(2) > heat pump(3-4) > EV(5)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str = "heat_pump",
        name: str = "Heat Pump",
        rated_power: float = 2000.0,
        priority: int = 4,
        min_power_threshold: float = 2000.0,
        relay1_entity_id: Optional[str] = None,
        relay2_entity_id: Optional[str] = None,
        climate_entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        temperature_entity_id: Optional[str] = None,
        normal_setpoint: float = 21.0,
        boost_offset: float = 2.0,
        max_setpoint: float = 55.0,
        force_on_threshold: float = 5000.0,
        min_power_change_interval: float = 300.0,
        daily_min_runtime_sec: int = 0,
        invert_sg_ready: bool = False,
        energy_entity_id: Optional[str] = None,
        sg_ready_service: Optional[str] = None,
        sg_ready_service_data: Optional[Dict[str, Any]] = None,
        sg_ready_state_entity: Optional[str] = None,
    ):
        super().__init__(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            min_power_threshold=min_power_threshold,
            climate_entity_id=climate_entity_id,
            power_entity_id=power_entity_id,
            normal_setpoint=normal_setpoint,
            boost_offset=boost_offset,
            max_setpoint=max_setpoint,
            min_power_change_interval=min_power_change_interval,
            energy_entity_id=energy_entity_id,  # #600 — heat-pump kWh counter → derived power
        )
        self.daily_min_runtime_sec = daily_min_runtime_sec
        self.relay1_entity_id = relay1_entity_id
        self.relay2_entity_id = relay2_entity_id
        # #523: opt-in for installs whose SG-Ready contacts are wired
        # normally-closed (NC) instead of normally-open — flips both relays
        # so the SG-Ready standard map drives the physical contacts the right
        # way. Default off (NO wiring, the common case).
        self.invert_sg_ready = bool(invert_sg_ready)
        # (#801) SG-Ready via SERVICE CALL — for heat pumps whose control
        # surface is a command, not a pair of relay switches (Buderus over
        # EMS-ESP was the report). When set, the service is the actuation
        # and the relays are not touched. ``sg_ready_service_data`` may use
        # the placeholders {state} (1–4), {relay1}/{relay2} (the standard
        # truth-table booleans) in any string value.
        self.sg_ready_service = (sg_ready_service or "").strip() or None
        self.sg_ready_service_data = dict(sg_ready_service_data or {})
        self.sg_ready_state_entity = (sg_ready_state_entity or "").strip() or None
        self.temperature_entity_id = temperature_entity_id
        self.force_on_threshold = force_on_threshold
        self._hp_status = HeatPumpStatus()

        # #594 — vacation mode. Set each cycle by the coordinator. While
        # True, SEM stops ENCOURAGING the pump (no SG-Ready boost/force-on,
        # no climate setpoint boost, no cheap-tariff force). SEM never sends
        # a BLOCKING signal for vacation — deactivation returns the pump to
        # SG-Ready NORMAL (state 2), so the pump's own frost/safety logic is
        # untouched.
        self.vacation: bool = False

        # #421 — telemetry surface mirroring #359/#416/#420
        # classifier_path / dampening_path / legionella_path patterns.
        # Each decision branch sets the corresponding ``*_path`` string
        # so the ``load_management_status`` sensor's ``devices`` dict
        # can publish them for self-diagnosis. No behavior change.
        self._last_activation_path: str = "uninitialized"
        self._last_deactivation_path: str = "uninitialized"
        self._last_relay_path: str = "uninitialized"
        self._last_temperature_reading_path: str = "uninitialized"
        self._last_offpeak_path: str = "uninitialized"

        # #508 — the heat pump exists to soak up solar surplus, so it
        # must be a SURPLUS-mode device. The base default is PEAK_ONLY,
        # and SurplusController.update() never proactively activates a
        # non-SURPLUS device — so without this the controller registered
        # but never turned on. A user can still override to peak_only/off
        # via set_device_control_mapping.
        from .base import DeviceControlMode
        self.control_mode = DeviceControlMode.SURPLUS
        # #508 W1 — compressor anti-cycling. On a 10 s coordinator cycle
        # the activate→deactivate path could otherwise short-cycle the
        # compressor. can_activate()/can_deactivate() enforce these.
        self.min_on_seconds = 600   # 10 min minimum run
        self.min_off_seconds = 300  # 5 min compressor rest

    @property
    def sg_ready_state(self) -> SGReadyState:
        return self._hp_status.sg_ready_state

    @property
    def hp_status(self) -> HeatPumpStatus:
        return self._hp_status

    @property
    def energy_split_label(self) -> str:
        """(#769) File this cycle's kWh under the SG-Ready state it ran in.

        On a heat-pump house this is the difference between a claim and a
        measurement. Energy booked in BOOST or FORCE_ON is energy SEM asked
        for; energy booked in NORMAL is energy the pump would have taken from
        its own thermostat anyway. Summed over a winter, the first number is
        "how much SG-Ready actually shifted" — which today is unanswerable.
        """
        return f"sg{int(self._hp_status.sg_ready_state)}"

    @property
    def needs_offpeak_activation(self) -> bool:
        """Temperature-aware override: don't force-boost if already warm.

        Records the decision branch on ``self._last_offpeak_path`` (#421):
        ``parent_declines`` / ``already_warm_skip`` / ``activate``.
        """
        if self.vacation:
            # #594 — no cheap-tariff comfort forcing while away.
            self._last_offpeak_path = "vacation_blocked"
            return False
        if not super().needs_offpeak_activation:
            self._last_offpeak_path = "parent_declines"
            return False
        temp = self.get_current_temperature()
        if temp is not None and temp >= self.max_setpoint - self.boost_offset:
            self._last_offpeak_path = "already_warm_skip"
            return False
        self._last_offpeak_path = "activate"
        return True

    async def activate(self, available_watts: float) -> float:
        """Activate heat pump in boost or force-on mode based on surplus.

        Records the SG-Ready branch on ``self._last_activation_path`` (#421):
        ``boost`` (surplus < force_on_threshold) or
        ``force_on`` (surplus >= threshold). Climate boost is composed via
        a ``+climate`` suffix when ``climate_entity_id`` is configured.

        #594: while vacation mode is active the pump receives NO
        comfort-driven activation — return 0 W without touching the relays
        (``vacation_blocked`` path). The coordinator already deactivated a
        running boost on the vacation transition.
        """
        if self.vacation:
            self._last_activation_path = "vacation_blocked"
            return 0.0
        if available_watts >= self.force_on_threshold:
            target_state = SGReadyState.FORCE_ON
            self._last_activation_path = "force_on"
        else:
            target_state = SGReadyState.BOOST
            self._last_activation_path = "boost"

        relay_ok = await self._set_sg_ready_state(target_state)
        if not relay_ok:
            # #508 C3: a relay write failed — the pump is NOT in the
            # requested SG-Ready state. Do not mark ACTIVE and do not
            # credit rated_power to the surplus pool (that power isn't
            # being drawn). Surface ERROR so the diagnostics show it.
            self._status.state = DeviceState.ERROR
            self._last_activation_path += "+relay_failed"
            _LOGGER.warning(
                "Heat pump activation aborted: SG-Ready relay write failed "
                "(%s) — not crediting %.0fW to surplus",
                self._last_relay_path, self.rated_power,
            )
            return 0.0

        if self.climate_entity_id:
            self._last_activation_path += "+climate"
            # Also boost temperature setpoint if climate entity configured
            await super().activate(available_watts)

        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        self._status.last_activated = datetime.now()
        self._status.activation_count += 1
        self._hp_status.is_solar_boosted = True
        self._hp_status.boost_start_time = datetime.now()

        _LOGGER.info(
            "Heat pump activated: SG-Ready=%s, surplus=%.0fW",
            target_state.name, available_watts,
        )
        return self.rated_power

    async def deactivate(self) -> None:
        """Return heat pump to normal operation.

        Sets ``self._last_deactivation_path = "normal"`` (#421).
        ``+climate`` suffix when climate boost is also reverted.
        """
        await self._set_sg_ready_state(SGReadyState.NORMAL)
        self._last_deactivation_path = "normal"

        # Restore normal temperature
        if self.climate_entity_id:
            await super().deactivate()
            self._last_deactivation_path += "+climate"

        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0
        self._status.last_deactivated = datetime.now()
        self._hp_status.is_solar_boosted = False

        _LOGGER.info("Heat pump returned to normal operation")

    def _relays_for(self, state: SGReadyState) -> tuple[bool, bool]:
        """(relay1_on, relay2_on) for an SG-Ready state, applying the
        per-pump NC-wiring inversion (#523) when configured."""
        r1, r2 = SG_READY_RELAY_MAP[state]
        if self.invert_sg_ready:
            return (not r1, not r2)
        return (r1, r2)

    async def _set_sg_ready_state(self, state: SGReadyState) -> bool:
        """Set SG-Ready state via relay entities.

        Returns ``True`` when the requested state was applied (or there
        are no relays to apply — climate-only installs), ``False`` when a
        physical relay write FAILED. #508 C3: the caller must not credit
        ``rated_power`` to the surplus pool when this returns False — the
        pump did not enter the requested state.

        Records the relay branch on ``self._last_relay_path`` (#421):
        ``both_relays`` / ``relay1_only`` / ``relay2_only`` /
        ``no_relays_configured`` / ``relay1_failed`` / ``relay2_failed``.
        ``no_relays_configured`` is the climate-only path (#437) — a
        valid success, the climate setpoint is the actuation.
        """
        relay1_on, relay2_on = self._relays_for(state)

        # (#801) Service-first: a configured SG-Ready service IS the
        # actuation. Verify-after-write when a state entity is configured
        # — SEM prefers to check that a command landed over assuming it.
        if self.sg_ready_service:
            try:
                domain, service = self.sg_ready_service.split(".", 1)
            except ValueError:
                _LOGGER.error(
                    "SG-Ready service %r is not domain.service",
                    self.sg_ready_service)
                self._last_relay_path = "service_invalid"
                return False
            def _render(v):
                if isinstance(v, str):
                    return (v.replace("{state}", str(int(state)))
                             .replace("{relay1}", str(relay1_on).lower())
                             .replace("{relay2}", str(relay2_on).lower()))
                return v
            data = {k: _render(v) for k, v in self.sg_ready_service_data.items()}
            try:
                await self.hass.services.async_call(
                    domain, service, data, blocking=True)
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("SG-Ready service call failed: %s", e)
                self._last_relay_path = "service_failed"
                return False
            self._last_relay_path = "service"
            if self.sg_ready_state_entity:
                st = self.hass.states.get(self.sg_ready_state_entity)
                got = str(getattr(st, "state", "")).strip()
                if got and got not in (str(int(state)), state.name,
                                       state.name.lower()):
                    # not a failure — the read-back may lag one poll; say
                    # so instead of silently trusting either side
                    _LOGGER.warning(
                        "SG-Ready read-back %s reports %r after commanding "
                        "state %d — verify the mapping (#801)",
                        self.sg_ready_state_entity, got, int(state))
                    self._last_relay_path = "service_unverified"
            return True

        # Prior relay1 value (for restore on a partial relay2 failure, I3).
        prev_relay1_on, _ = self._relays_for(self._hp_status.sg_ready_state)
        relay1_called = False

        if self.relay1_entity_id:
            service = "turn_on" if relay1_on else "turn_off"
            try:
                await self.hass.services.async_call(
                    "homeassistant", service,
                    {"entity_id": self.relay1_entity_id},
                    blocking=True,
                )
                relay1_called = True
            except Exception as e:
                _LOGGER.error("Failed to set SG-Ready relay 1: %s", e)
                self._last_relay_path = "relay1_failed"
                return False

        if self.relay2_entity_id:
            service = "turn_on" if relay2_on else "turn_off"
            try:
                await self.hass.services.async_call(
                    "homeassistant", service,
                    {"entity_id": self.relay2_entity_id},
                    blocking=True,
                )
                if relay1_called:
                    self._last_relay_path = "both_relays"
                else:
                    self._last_relay_path = "relay2_only"
            except Exception as e:
                _LOGGER.error("Failed to set SG-Ready relay 2: %s", e)
                self._last_relay_path = "relay2_failed"
                # I3: relay1 already moved but relay2 didn't — the (r1,r2)
                # pair is now inconsistent (e.g. could read as BLOCKED).
                # Best-effort restore relay1 to its prior value so we
                # leave a coherent prior state, not a curtail signal.
                if relay1_called and relay1_on != prev_relay1_on:
                    try:
                        restore = "turn_on" if prev_relay1_on else "turn_off"
                        await self.hass.services.async_call(
                            "homeassistant", restore,
                            {"entity_id": self.relay1_entity_id},
                            blocking=True,
                        )
                    except Exception:  # noqa: BLE001 — best effort
                        pass
                return False
        elif relay1_called:
            self._last_relay_path = "relay1_only"
        else:
            self._last_relay_path = "no_relays_configured"

        self._hp_status.sg_ready_state = state
        _LOGGER.debug("SG-Ready state set to %s", state.name)
        return True

    def get_current_temperature(self) -> Optional[float]:
        """Read current temperature from sensor.

        Records the source path on
        ``self._last_temperature_reading_path`` (#421).
        """
        if self.temperature_entity_id:
            state = self.hass.states.get(self.temperature_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    val = float(state.state)
                    self._last_temperature_reading_path = "sensor"
                    return val
                except (ValueError, TypeError):
                    self._last_temperature_reading_path = "sensor_invalid"
            elif state:
                self._last_temperature_reading_path = "sensor_unavailable"
            else:
                self._last_temperature_reading_path = "sensor_missing"
        else:
            self._last_temperature_reading_path = "no_sensor_configured"
        return None

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "sg_ready_state": self._hp_status.sg_ready_state.name,
            "sg_ready_value": self._hp_status.sg_ready_state.value,
            "is_solar_boosted": self._hp_status.is_solar_boosted,
            "current_temperature": self.get_current_temperature(),
            "force_on_threshold": self.force_on_threshold,
            "vacation": self.vacation,  # #594
            # #421 — telemetry surface (mirrors #359/#416/#420 pattern).
            "activation_path": self._last_activation_path,
            "deactivation_path": self._last_deactivation_path,
            "relay_path": self._last_relay_path,
            "temperature_reading_path": self._last_temperature_reading_path,
            "offpeak_path": self._last_offpeak_path,
        })
        return d
