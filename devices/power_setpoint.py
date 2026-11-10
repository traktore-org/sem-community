"""(#880) A surplus load whose control is a watt setpoint, not a switch.

SEM's surplus allocator has always handed each device the watts it may
have — ``activate(available_watts)`` and ``adjust_power(available_watts)``
are on the base contract and the controller calls both every cycle. Every
implementation but the EV chargers' threw the number away: ``SwitchDevice``
turns the entity fully on and reports its nameplate, so a my-PV AC-THOR or
any other modulating load ran at whatever it felt like, and the allocator's
remaining-surplus arithmetic was wrong on top.

@jonasbkarlsson reproduced it on a plain Home Assistant number helper, so no
integration is implicated: "SEM correctly detects available/distributable PV
surplus, but never writes a value to the configured Number control entity.
The allocated surplus therefore remains at 0 W."

This class is the missing one. It writes the allocation, clamped to the
entity's own min/max and quantised to its step, and reports what it wrote.

Two things it deliberately does NOT do:

* check observer mode — the controller does that before calling
  (``coordinator/surplus_controller.py``);
* set ``_sem_owned`` — ownership is recorded at the one choke point,
  ``_activate_owned``, and guarded by
  ``tests/test_load_ownership_choke_point.py``. Bug class 17 lives here.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple

from homeassistant.core import HomeAssistant

from ..coordinator.power_control import native_power_scale
from ..consts.core import DEFAULT_DEVICE_RATED_POWER
from .base import ControllableDevice, DeviceState, DeviceType
from ..coordinator.units import finite_float

_LOGGER = logging.getLogger(__name__)

#: Floor for an entity that declares no bounds. A number entity should carry
#: min/max, but a template one need not, and refusing to drive it would be
#: worse than driving it between zero and its nameplate.
_DEFAULT_MIN_W: float = 0.0

#: Domains whose entities take a numeric setpoint. Both spell the service
#: ``set_value``, but in their OWN domain — writing ``number.set_value`` to an
#: ``input_number`` entity is the same silent no-op #880 is about.
SETPOINT_DOMAINS: Tuple[str, ...] = ("number", "input_number")


def setpoint_domain(entity_id: Optional[str]) -> str:
    """The service domain that can write ``entity_id``'s value."""
    domain = str(entity_id or "").split(".", 1)[0]
    return domain if domain in SETPOINT_DOMAINS else "number"


def device_class_for_control(entity_id: Optional[str]):
    """Which device class drives this control entity (#880).

    THE producer. It lives here, beside the class it may return, because
    the first cut of #880 put it in ``features/device_registry.py`` and a
    fourth construction site — ``surplus_device_from_spec``, which every
    service-registered device goes through at every restart — went on
    building a ``SwitchDevice`` for a ``number`` entity. A helper whose
    whole purpose is "so the factory and the shed path cannot disagree"
    that one of the factories does not call is worse than no helper: it
    reads as covered.

    The import is function-local because ``base`` imports this module.
    """
    from .base import SwitchDevice
    domain = str(entity_id or "").split(".", 1)[0]
    return PowerSetpointDevice if domain in SETPOINT_DOMAINS else SwitchDevice


class PowerSetpointDevice(ControllableDevice):
    """A load whose draw SEM sets in watts, through a ``number`` entity."""

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
        energy_entity_id: Optional[str] = None,
    ) -> None:
        # (#576/#744) The same two floors ``SwitchDevice`` applies, for the
        # same reason and from the same source: ``_get_power_rating`` returns
        # 0 W for a load that is OFF right now, or has no power sensor at
        # all. Taking that 0 at face value made ``min_power_threshold`` zero,
        # so ``effective_surplus >= 0`` was true at every cycle of a dark
        # night: the allocator "activated" the heater into 0 W of surplus,
        # ``_write`` clamped it to the entity's floor, the belief never
        # flipped ACTIVE — so ``calibrate_rated_power`` could never run and
        # learn the real number — and the reporter's symptom reproduced
        # itself through the fix. 0 W here means NOT MEASURED YET.
        rp = (float(rated_power) if (rated_power and rated_power > 0)
              else DEFAULT_DEVICE_RATED_POWER)
        super().__init__(
            hass, device_id, name, priority,
            min_power_threshold or rp,
            entity_id, power_entity_id,
            energy_entity_id=energy_entity_id,
        )
        self.rated_power = rp
        #: (#744) Label the invention — the 1 kW above is a placeholder.
        self.rated_power_measured = bool(rated_power and rated_power > 0)

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SETPOINT

    # ── the entity's own bounds, read live ────────────────────────────
    def _bounds(self, scale: Optional[float] = None) -> Tuple[float, float, float]:
        """``(min, max, step)`` from the entity, in the ENTITY's own unit.

        ``scale`` is passed in by every caller that has already asked for it
        — the probe logs a WARNING on each refusal, and asking three times a
        cycle turned one misconfigured entity into ~1 200 lines an hour.
        """
        if scale is None:
            scale = self.scale_to_watts()
        scale = scale or 1.0
        low, high, step = _DEFAULT_MIN_W, float(self.rated_power or 0.0) / scale, 1.0
        state = self.hass.states.get(self.entity_id) if self.entity_id else None
        attrs = getattr(state, "attributes", None) or {}
        for key in ("min", "max", "step"):
            if key not in attrs:
                continue
            try:
                value = float(attrs[key])
            except (TypeError, ValueError):
                continue
            if key == "min":
                low = value
            elif key == "max":
                high = value
            elif value > 0:
                step = value
        if high < low:
            low, high = high, low
        return low, high, step

    def scale_to_watts(self) -> Optional[float]:
        """Native-unit-to-watts for this entity, or ``None`` — don't write.

        ONE rule (#749), the same one the battery power-setpoint path uses:
        a ``kW`` entity is written kilowatts, a unitless helper means watts
        (@jonasbkarlsson's case), and an entity that declares amperes — or
        is named like an ampere register — takes nothing from us. Writing
        3200 into a 0-32 A knob is the sibling defect #882 refused.
        """
        if not self.entity_id:
            return None
        return native_power_scale(self.hass, self.entity_id)

    def _clamp(self, watts: float, scale: Optional[float] = None) -> float:
        """The value this entity will actually accept for ``watts``."""
        low, high, step = self._bounds(scale)
        try:
            value = float(watts)
        except (TypeError, ValueError):
            return low
        value = max(low, min(value, high))
        if step > 0:
            value = round(value / step) * step
        return max(low, min(value, high))

    def expected_draw_w(self, watts: float) -> Optional[float]:
        """(#1335) The watts this load will draw when sent ``watts``: the
        value its entity accepts (bounds, step, unit). The load walk books
        this, so a heater sent less than its rating is booked what it takes
        — not its rating, which would read as a shortfall and stop it. None
        = the entity does not read as a power setpoint (nothing is written)."""
        if not self.entity_id:
            return None
        scale = self.scale_to_watts()
        if scale is None:
            return None
        try:
            return self._clamp(float(watts) / scale, scale) * scale
        except (TypeError, ValueError):
            return None

    async def _write(self, watts: float) -> float:
        """Write the setpoint and record it. Returns the WATTS it represents."""
        if not self.entity_id:
            return 0.0
        scale = self.scale_to_watts()
        if scale is None:
            _LOGGER.warning(
                "Not writing %.0fW to %s — it does not read as a power "
                "setpoint (see #882)", watts, self.entity_id,
            )
            return 0.0
        native = self._clamp(float(watts) / scale, scale)
        await self.send(setpoint_domain(self.entity_id), "set_value",
                        {"entity_id": self.entity_id, "value": native})
        written_w = native * scale
        self._status.current_consumption_w = written_w
        self._status.allocated_power_w = written_w
        return written_w

    # ── belief follows the number (#559 / #766 / #914) ────────────────
    def _observed_watts(self) -> Optional[float]:
        """What the entity says the load is drawing, or ``None`` — unreadable.

        SEM's command for this device IS the entity's value, so reading it
        back answers "is it running, and at what?" in one go. The precedent
        is ``hot_water_controller`` (#914): a device whose command is not an
        on/off switch writes its own observation, and the docstring on
        ``_adoptable_now`` says so in as many words.
        """
        if not self.entity_id or not self.hass:
            return None
        state = self.hass.states.get(self.entity_id)
        if not state or state.state in ("unavailable", "unknown", None):
            return None
        scale = self.scale_to_watts()
        if scale is None:
            return None
        try:
            native = finite_float(state.state)
        except (TypeError, ValueError):
            return None
        low, _high, _step = self._bounds(scale)
        return None if native <= low else native * scale

    def _believe_running(self, watts: float, how: str) -> bool:
        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = watts
        self._status.allocated_power_w = watts
        self._status.last_activated = datetime.now()
        self._last_activated = self._status.last_activated   # (#644)
        owned = self._adopt_ownership()                      # (#779) gated
        _LOGGER.info(
            "%s: %s %s at %.0fW — belief adopted, %s",
            self.name, self.entity_id, how, watts,
            "under normal control" if owned
            else f"left to the user (mode {self.control_mode.value})",
        )
        return True

    def adopt_if_running(self) -> bool:
        """(#559) Re-own a setpoint that is already non-zero at registration.

        Without this the allocator believes the load is idle after a restart
        and counts its watts as spendable surplus a second time — while the
        heater goes on drawing them, answerable to nobody.
        """
        if self.is_active:
            return False
        watts = self._observed_watts()
        if watts is None:
            return False
        return self._believe_running(watts, "was already set")

    def sync_belief_to_observation(self) -> bool:
        """(#766) The per-cycle twin. A setpoint moved by someone else —
        the box's own schedule, an automation, a hand — is the same fact."""
        watts = self._observed_watts()
        if watts is None:
            if self.is_active:
                self._status.state = DeviceState.IDLE
                self._status.current_consumption_w = 0.0
                self._status.allocated_power_w = 0.0
                self._sem_owned = False
                self._status.last_deactivated = datetime.now()
                self._last_deactivated = self._status.last_deactivated
                _LOGGER.info("%s: %s went to its floor outside SEM — belief "
                             "released", self.name, self.entity_id)
                return True
            return False
        if self.is_active:
            # Running either way; just keep the books on the live number.
            if abs(float(self._status.current_consumption_w or 0.0) - watts) < 1.0:
                return False
            self._status.current_consumption_w = watts
            self._status.allocated_power_w = watts
            return True
        return self._believe_running(watts, "was set outside SEM")

    async def activate(self, available_watts: float) -> float:
        if not self.entity_id:
            return 0.0
        # Anti-flicker: minimum off time — the UNIFIED clock (#644).
        if self.min_off_seconds > 0 and self._last_deactivated:
            elapsed = (datetime.now() - self._last_deactivated).total_seconds()
            if elapsed < self.min_off_seconds:
                return 0.0
        try:
            written = await self._write(available_watts)
        except Exception as e:  # noqa: BLE001 — one device must not end the pass
            _LOGGER.error("Failed to set %s to %.0fW: %s", self.name,
                          available_watts, e)
            self._status.state = DeviceState.ERROR
            self._status.error_message = str(e)
            return 0.0
        if written <= 0:
            return 0.0
        self._status.state = DeviceState.ACTIVE
        self._status.last_activated = datetime.now()
        self._last_activated = self._status.last_activated   # (#644)
        self._status.activation_count += 1
        _LOGGER.info("Set %s to %.0fW (surplus)", self.name, written)
        return written

    async def adjust_power(self, available_watts: float) -> float:
        """The whole point of the class: follow the surplus while running."""
        if not self.is_active:
            return 0.0
        try:
            return await self._write(available_watts)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to adjust %s to %.0fW: %s", self.name,
                          available_watts, e)
            return float(self._status.current_consumption_w or 0.0)

    async def deactivate(self) -> None:
        if not self.entity_id:
            return
        # Anti-flicker: minimum on time — the UNIFIED clock (#644).
        if self.min_on_seconds > 0 and self._last_activated:
            elapsed = (datetime.now() - self._last_activated).total_seconds()
            if elapsed < self.min_on_seconds:
                return
        scale = self.scale_to_watts()
        if scale is None:
            # The one method that had no unit gate. An entity the write path
            # refuses must not be written by the STOP path either — that is
            # how a 0 lands on an ampere knob, and on OCPP a 0 A profile is
            # persisted (#976).
            _LOGGER.warning(
                "Not stopping %s — %s does not read as a power setpoint",
                self.name, self.entity_id,
            )
            return
        low, _high, _step = self._bounds(scale)
        try:
            await self.send(setpoint_domain(self.entity_id), "set_value",
                            {"entity_id": self.entity_id, "value": low})
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to stop %s: %s", self.name, e)
            return
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0
        self._status.last_deactivated = datetime.now()
        self._last_deactivated = self._status.last_deactivated
        _LOGGER.info("Stopped %s (setpoint → %s)", self.name, low)
