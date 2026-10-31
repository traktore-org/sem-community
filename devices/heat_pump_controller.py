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

from .base import SetpointDevice, DeviceState, ComfortBandMixin
from ..consts.devices import CONTACT_VALUE_SERVICES
from ..utils.select_option import listed_option

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


def _norm_value(v) -> Optional[str]:
    """A configured contact value, or None when the field was left empty.

    ``0`` is a legitimate OFF value for a ``number`` contact, so emptiness
    is decided on the STRING and never on truthiness.
    """
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass
class HeatPumpStatus:
    """Heat pump operational status."""
    sg_ready_state: SGReadyState = SGReadyState.NORMAL
    current_temperature: Optional[float] = None
    target_temperature: Optional[float] = None
    is_solar_boosted: bool = False
    boost_start_time: Optional[datetime] = None


class HeatPumpController(ComfortBandMixin, SetpointDevice):
    """SG-Ready heat pump controller.

    Registers as a SetpointDevice in the SurplusController.
    When surplus is available, switches to BOOST or FORCE_ON mode
    and optionally increases the temperature setpoint.

    Typical priority: battery(2) > heat pump(3-4) > EV(5)

    (#1081 Slice B) ``ComfortBandMixin`` gives this class
    ``comfort_plan_demand()``/``record_comfort_sample()`` for free, the
    same way ``HotWaterController`` already has it — wiring, not new
    logic. The band's four fields (``comfort_entity``, ``comfort_target``,
    ``comfort_offset``, ``comfort_limit``) are set through the existing
    device-goals surface, not a new control; a heat pump nobody set a
    goal on keeps the mixin's class defaults and ``comfort_state`` stays
    ``disengaged`` — byte-for-byte today's behaviour.
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
        relay1_on_value: Optional[str] = None,
        relay1_off_value: Optional[str] = None,
        relay2_on_value: Optional[str] = None,
        relay2_off_value: Optional[str] = None,
        cop: float = 3.0,
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
        # (#801) Per-contact ON/OFF values for a VALUE-domain contact —
        # a ``text``/``number``/``select`` entity instead of a switch. Kept
        # per contact because they are not interchangeable: the reporter's
        # EMS-ESP inputs carry bit strings of different widths (15 and 12).
        # Empty for the switch case, which is what every existing install is.
        self._contact_values = {
            1: (_norm_value(relay1_on_value), _norm_value(relay1_off_value)),
            2: (_norm_value(relay2_on_value), _norm_value(relay2_off_value)),
        }
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
        # (#1081 Slice A) a flat seasonal-average COP until a real curve
        # exists (Slice C); never 0/negative — cost_of_heat() would divide
        # by it.
        self.cop = float(cop) if cop and cop > 0 else 3.0
        self._hp_status = HeatPumpStatus()

        # #594 — vacation mode. Set each cycle by the coordinator. While
        # True, SEM stops ENCOURAGING the pump (no SG-Ready boost/force-on,
        # no climate setpoint boost, no cheap-tariff force). SEM never sends
        # a BLOCKING signal for vacation — deactivation returns the pump to
        # SG-Ready NORMAL (state 2), so the pump's own frost/safety logic is
        # untouched.
        self.vacation: bool = False

        # (#914) One restart adoption per lifetime, decided on the first
        # READABLE observation of the SG-Ready surface — see adopt_if_running.
        self._boot_adoption_pending: bool = True

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
    def comfort_state(self) -> str:
        """(#1081 Slice B, mirrors HotWaterController #594/#1062) vacation
        suspends comfort pre-heat the same way it already suspends SG-Ready
        off-peak forcing — no banked block while away."""
        if self.vacation:
            return "disengaged"
        return super().comfort_state

    def _comfort_fallback_reading(self) -> Optional[float]:
        """No ``comfort_entity`` configured → the pump's own temperature
        sensor, already in °C (#1118)."""
        return self.get_current_temperature()

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

        (#801 review) The contact write's verdict is HONOURED here, the way
        ``activate`` already honours it for #508 C3. It used to be discarded:
        a failed write left the pump physically in BOOST while SEM recorded
        IDLE / 0 W and handed that power to the next device — the mirror of
        the rule C3 states for the activation direction. A pump SEM could not
        stand down stays ACTIVE in its belief, so the next cycle tries again
        and nobody spends its watts twice. The climate setpoint is still
        reverted either way: the two surfaces fail independently.
        """
        relay_ok = await self._set_sg_ready_state(SGReadyState.NORMAL)
        self._last_deactivation_path = "normal" if relay_ok else "relay_failed"

        # Restore normal temperature
        if self.climate_entity_id:
            await super().deactivate()
            self._last_deactivation_path += "+climate"

        if not relay_ok:
            _LOGGER.error(
                "%s: could not return the SG-Ready contacts to NORMAL (%s) — "
                "the pump may still be boosting, so SEM keeps it ACTIVE and "
                "retries rather than giving its power away",
                self.name, self._last_relay_path,
            )
            return

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

    # ─── SG-Ready contacts (#801) ────────────────────────────

    def _contact_service(self, idx: int, entity_id: str, on: bool):
        """The service call that drives contact ``idx`` to ``on``.

        Returns ``(domain, service, payload)``, or None when the contact is
        a VALUE domain whose ON/OFF values were not configured — a write
        SEM must refuse rather than guess at (writing "on" into a bit-string
        field would be a silent no-op the pump never acts on).
        """
        domain = entity_id.split(".", 1)[0]
        spec = CONTACT_VALUE_SERVICES.get(domain)
        if spec is None:
            # Toggle domain — unchanged since the first SG-Ready release.
            return ("homeassistant", "turn_on" if on else "turn_off",
                    {"entity_id": entity_id})
        on_value, off_value = self._contact_values.get(idx, (None, None))
        value = on_value if on else off_value
        if value is None:
            _LOGGER.error(
                "SG-Ready contact %d (%s) is a %s entity but its %s value is "
                "not configured — set both values for this contact (#801)",
                idx, entity_id, domain, "ON" if on else "OFF",
            )
            return None
        svc_domain, service, key = spec
        if service == "select_option":
            # (#1039) the option the select lists, never its label
            value = listed_option(self.hass, entity_id, value)
        if svc_domain in ("number", "input_number"):
            try:
                value = float(value)
            except (TypeError, ValueError):
                _LOGGER.error(
                    "SG-Ready contact %d (%s) needs a NUMBER value, got %r",
                    idx, entity_id, value)
                return None
        return (svc_domain, service, {"entity_id": entity_id, key: value})

    async def _write_contact(self, idx: int, entity_id: str, on: bool) -> None:
        """Drive one SG-Ready contact. Raises on failure, so the callers'
        existing per-relay error handling (and the I3 restore) is unchanged."""
        call = self._contact_service(idx, entity_id, on)
        if call is None:
            raise ValueError(f"SG-Ready contact {idx} is not configured to be writable")
        domain, service, payload = call
        # OBSERVER-GATED: via layer 3 — this device is actuated only through
        # reconcile_load, whose observer branch (_reconcile_load_observe)
        # returns before any device method runs. Nothing IN this file checks
        # observer_mode, so moving heat-pump control off the reconcile_load
        # path loses the gate — do not call this from anywhere else.
        await self.hass.services.async_call(domain, service, payload, blocking=True)

    def _contact_is_on(self, idx: int, entity_id: str, raw: str) -> Optional[bool]:
        """Read one contact's boolean back off its own state, or None when
        the state matches neither the ON nor the OFF value (an unmapped
        third value — SEM says "I cannot tell" rather than guessing)."""
        domain = entity_id.split(".", 1)[0]
        if domain not in CONTACT_VALUE_SERVICES:
            return {"on": True, "off": False}.get(raw)
        on_value, off_value = self._contact_values.get(idx, (None, None))
        if on_value is None or off_value is None:
            return None
        if CONTACT_VALUE_SERVICES[domain][1] == "select_option":
            # (#1039) a select READS the option it lists, so compare with the
            # option SEM writes — a configured label would never match
            on_value = listed_option(self.hass, entity_id, on_value)
            off_value = listed_option(self.hass, entity_id, off_value)
        if self._same_value(domain, raw, on_value):
            return True
        if self._same_value(domain, raw, off_value):
            return False
        return None

    @staticmethod
    def _same_value(domain: str, raw: str, configured: str) -> bool:
        """Does a live state mean the same thing as a configured value?

        (#801 review) A NUMBER entity reports what it holds, not what was
        written: a contact configured ``1`` reads back ``"1.0"``. Comparing
        the strings made every number contact unreadable, which silently
        cost #914 its restart adoption — SEM would never re-own a boost it
        left running. Numbers compare as numbers; everything else compares
        as text, because a bit string's leading zeros are the meaning.
        """
        if domain in ("number", "input_number"):
            try:
                return float(raw) == float(configured)
            except (TypeError, ValueError):
                return False
        return raw == configured.strip().lower()

    # ─── Restart adoption (#914) ─────────────────────────────

    def _read_sg_ready_state(self) -> "tuple[bool, Optional[SGReadyState]]":
        """(#914) The SG-Ready state the pump is in NOW, read from the
        surface SEM writes: the relay pair through the same (NC-inverted,
        #523) truth table ``_set_sg_ready_state`` drives, or a service pump's
        state entity (#801).

        Returns ``(readable, state)``. ``readable`` is False while a
        configured entity cannot be read yet (its integration still loading
        on a restart). A pump with nothing to read — a service pump without
        a state entity, a climate-only pump — is readable with state None:
        there is no evidence to wait for.
        """
        if self.sg_ready_service:
            entities = [self.sg_ready_state_entity] if self.sg_ready_state_entity else []
        elif self.relay1_entity_id and self.relay2_entity_id:
            entities = [self.relay1_entity_id, self.relay2_entity_id]
        else:
            entities = []
        if not entities:
            return True, None
        values = []
        for eid in entities:
            st = self.hass.states.get(eid)
            v = str(getattr(st, "state", "") or "").strip().lower()
            if v in ("", "unavailable", "unknown"):
                return False, None
            values.append(v)
        if self.sg_ready_service:
            for s in SGReadyState:
                if values[0] in (str(int(s)), s.name.lower()):
                    return True, s
            return True, None
        # (#801) A contact's boolean comes off its own surface: "on"/"off"
        # for a switch, the configured ON/OFF value for a text/number/select.
        c1 = self._contact_is_on(1, self.relay1_entity_id, values[0])
        c2 = self._contact_is_on(2, self.relay2_entity_id, values[1])
        if c1 is None or c2 is None:
            return True, None
        pair = (c1, c2)
        for s in SGReadyState:
            if self._relays_for(s) == pair:
                return True, s
        return True, None

    def adopt_if_running(self) -> bool:
        """(#914) Re-own an SG-Ready boost SEM left on across a restart.

        The pump is registered straight into the controller with no adopter,
        and as a SETPOINT device neither the reconciler nor the per-cycle
        switch sync ever looks at it. A reload or an HA restart while SEM had
        it in BOOST left the relays there (#656 leaves loads as they are)
        with SEM believing it idle — nothing returned it to NORMAL, and the
        pump ran its boost through the night.

        Adopted only in BOOST / FORCE_ON, the states SEM commands on surplus:
        NORMAL is nothing of SEM's, BLOCKED SEM never writes (#664). Decided
        once per lifetime, on the first readable observation.
        """
        if not self.hass or not self._boot_adoption_window_open():
            return False
        if self.is_active:
            # SEM started it itself this lifetime — nothing left to adopt.
            self._boot_adoption_pending = False
            return False
        readable, observed = self._read_sg_ready_state()
        if not readable:
            return False
        self._boot_adoption_pending = False
        if observed not in (SGReadyState.BOOST, SGReadyState.FORCE_ON):
            return False
        self._hp_status.sg_ready_state = observed
        self._hp_status.is_solar_boosted = True
        self._hp_status.boost_start_time = datetime.now()
        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        self._status.last_activated = datetime.now()
        self._last_activated = self._status.last_activated  # (#644) unified clock
        owned = self._adopt_ownership()  # (#779) gated, in one place
        _LOGGER.info(
            "%s: SG-Ready %s at registration — belief adopted, %s (#914)",
            self.name, observed.name,
            "re-owned as active" if owned
            else f"left to the user (mode {self.control_mode.value})",
        )
        return True

    def sync_belief_to_observation(self) -> bool:
        """(#914) The per-cycle retry of the restart adoption, until the
        SG-Ready surface is first readable. Nothing more: the pump is not a
        switch, and SEM does not claim a boost it sees start later."""
        return self.adopt_if_running()

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
            # OBSERVER-GATED: via layer 3 — this device is actuated only
            # through reconcile_load, whose observer branch
            # (_reconcile_load_observe) returns before any device method
            # runs. Nothing IN this file checks observer_mode, so moving
            # heat-pump control off the reconcile_load path loses the
            # gate — do not call this from anywhere else.
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
            # Keep the successful command like the relay path below. A
            # lagging read-back is reported separately, not a NORMAL command.
            self._hp_status.sg_ready_state = state
            return True

        # Prior relay1 value (for restore on a partial relay2 failure, I3).
        prev_relay1_on, _ = self._relays_for(self._hp_status.sg_ready_state)
        relay1_called = False

        if self.relay1_entity_id:
            try:
                await self._write_contact(1, self.relay1_entity_id, relay1_on)
                relay1_called = True
            except Exception as e:
                _LOGGER.error("Failed to set SG-Ready relay 1: %s", e)
                self._last_relay_path = "relay1_failed"
                return False

        if self.relay2_entity_id:
            try:
                await self._write_contact(2, self.relay2_entity_id, relay2_on)
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
                        await self._write_contact(
                            1, self.relay1_entity_id, prev_relay1_on)
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
                # (#1118) the sensor's own unit decides — °C out
                from ..coordinator.units import temperature_state_to_celsius
                val = temperature_state_to_celsius(state, None)
                if val is not None:
                    self._last_temperature_reading_path = "sensor"
                    return val
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
            "cop": self.cop,  # #1081 Slice A
            "vacation": self.vacation,  # #594
            # #421 — telemetry surface (mirrors #359/#416/#420 pattern).
            "activation_path": self._last_activation_path,
            "deactivation_path": self._last_deactivation_path,
            "relay_path": self._last_relay_path,
            "temperature_reading_path": self._last_temperature_reading_path,
            "offpeak_path": self._last_offpeak_path,
        })
        return d
