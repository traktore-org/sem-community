"""GenericAdapter — covers Wallbox, Easee, go-eCharger, OCPP, etc.

Brands whose firmware handles ``set_current(0)`` as "stop charging"
(unlike KEBA which silently keeps the last setpoint). These adapters
are simpler: ``command_idle`` just sets current to 0; the contactor
opens because the firmware says so.

If a future user reports the KEBA quirks on a different brand
(eg. some OCPP firmware also rejects below-min), file an issue —
the answer is a dedicated adapter subclass, not a flag on this one.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..charger_types import ChargerIntent, ChargerPower
from .base import ChargerAdapter
from .status_enum import classify_charger_status

if TYPE_CHECKING:  # pragma: no cover
    from ...devices.base import CurrentControlDevice

_LOGGER = logging.getLogger(__name__)

# Generic firmware: 6 A IEC 61851 minimum, ~0 W handshake idle.
# Brand-specific values can be overridden by subclasses.
_GENERIC_MIN_CURRENT_A = 6
_GENERIC_HANDSHAKE_POWER_W = 500.0
"""500 W keeps the same handshake threshold as KEBA — any brand
drawing more than this without an SEM command is a self-resume
anomaly regardless of brand."""


class GenericAdapter(ChargerAdapter):
    """Brand-agnostic adapter for chargers whose ``set_current(0)``
    actually stops the contactor."""

    def __init__(self, device: "CurrentControlDevice") -> None:
        super().__init__()
        self._device = device
        self._last_intent: Optional[ChargerIntent] = None

    @property
    def min_current_a(self) -> int:
        return int(getattr(self._device, "min_current", _GENERIC_MIN_CURRENT_A))

    @property
    def max_current_a(self) -> int:
        # Effective max = config max clamped to the control entity's own max,
        # so CHARGE_MAX resolves to a value the device can actually hold
        # (no perpetual clamp-drift; #536). Falls back to config max — the
        # ``isinstance`` guard keeps it robust to mock devices in tests
        # (a MagicMock attr is callable but returns a non-numeric mock).
        eff = getattr(self._device, "effective_max_current", None)
        if callable(eff):
            try:
                v = eff()
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return int(v)
            except (TypeError, ValueError):
                pass
        return int(getattr(self._device, "max_current", 32))

    @property
    def phases(self) -> int:
        return int(getattr(self._device, "phases", 3))

    @property
    def voltage(self) -> int:
        return int(getattr(self._device, "voltage", 230))

    @property
    def handshake_power_w(self) -> float:
        return _GENERIC_HANDSHAKE_POWER_W

    @property
    def can_command_zero(self) -> bool:
        # Generic brands accept set_current(0) as a stop signal.
        return True

    async def command_current(self, amps: int) -> None:
        if amps < self.min_current_a:
            await self.command_idle()
            return
        amps = min(amps, self.max_current_a)
        if not getattr(self._device, "_session_active", False):
            await self._device.start_session(energy_target_kwh=0)
        await self._device._set_current(amps)
        self._last_intent = ChargerIntent.CHARGE_AT_AMPS

    async def command_idle(self) -> None:
        # Generic: setting current to 0 is the canonical stop. When a session
        # is open, stop_session() ALREADY writes 0 A (its no-brand-mechanism
        # fallback) on top of the session-level cleanup — so writing it here
        # too emitted the stop TWICE within milliseconds (#894, @DigitalOptics:
        # an HA automation watching for the 0 A write fired twice). Delegate
        # the 0 A to stop_session; write it directly only when there is no
        # session to tear down. KebaAdapter has always delegated this way.
        if getattr(self._device, "_session_active", False):
            await self._device.stop_session()
        else:
            await self._device._set_current(0)
        self._last_intent = ChargerIntent.IDLE

    async def command_max(self) -> None:
        await self.command_current(self.max_current_a)
        self._last_intent = ChargerIntent.CHARGE_MAX

    async def command_disable(self) -> None:
        # stop_session() is the canonical stop: it dispatches the brand's stop
        # mechanism and, for a generic brand with none, writes 0 A itself. The
        # extra _set_current(0) here duplicated that write — two 0 A dispatches
        # a few ms apart (#894). stop_session owns the stop, exactly as KEBA.
        await self._device.stop_session()
        self._last_intent = ChargerIntent.DISABLE

    def is_self_charging(self, power: ChargerPower) -> bool:
        if power.power_w <= self.handshake_power_w:
            return False
        if self._last_intent is None:
            return True  # cold start: any power = self-resume
        return self._last_intent in (ChargerIntent.IDLE, ChargerIntent.DISABLE)

    # ── #548 (generalised) — status-enum-authoritative observation ─────
    #
    # For cloud-polled brands the power reading lags the contactor (Wallbox
    # ~90 s, Easee ~60 s, Zaptec/Ohme/go-e/OCPP similar). A power-only
    # ``actual_charging`` makes the reconciler read OFF/IDLE as "already
    # converged" while the box still charges (#548). The user already
    # configures the charger's status sensor (``ev_charging_sensor`` →
    # ``charging_status_entity``); the shared classifier
    # (``status_enum.classify_charger_status``) maps every supported brand's
    # status strings to a control class. Strictly additive: no status sensor
    # / unrecognised state → fall back to the power heuristic.

    def _status_raw(self) -> str:
        """Lower-cased charger status-sensor state, or '' when unreadable."""
        eid = getattr(self._device, "charging_status_entity", "") or ""
        hass = getattr(self._device, "hass", None)
        if not eid or hass is None:
            return ""
        st = hass.states.get(eid)
        if st is None or st.state in (None, "", "unavailable", "unknown"):
            return ""
        return str(st.state).strip().lower()

    def _status_class(self) -> str:
        """Control class of the status sensor: charging / not_charging /
        locked / unknown (see ``status_enum``)."""
        return classify_charger_status(self._status_raw())

    def actual_charging(self, power: ChargerPower) -> bool:
        cls = self._status_class()
        if cls == "charging":
            return True
        if cls in ("not_charging", "locked"):
            return False
        # unknown / no status sensor → power-based fallback (unchanged).
        return power.power_w > self.handshake_power_w

    def enable_state(self):
        """App/cloud/schedule-locked brands (Eco-Smart, Easee smart-start,
        Ohme pending-approval, OCPP unavailable, Alfen in-operative) report
        uncontrollable so the reconciler surfaces it instead of fighting a
        contactor it can't drive. Otherwise defer to the switch-based default."""
        if self._status_class() == "locked":
            return (None, False)
        return super().enable_state()

    @property
    def last_intent(self) -> Optional[ChargerIntent]:
        return self._last_intent
