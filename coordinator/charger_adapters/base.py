"""ChargerAdapter protocol — the actuator's only contract to hardware.

Every brand-specific behaviour the actuator currently knows about
becomes a method on this protocol. The actuator says
``adapter.command_idle()``; the adapter does whatever the brand needs
(``set_current(0)`` for Wallbox, ``keba.disable`` for KEBA, both for
some configurations).

The handshake threshold (500 W) and the actually-charging cutoff are
adapter properties — different brands report different idle power
(KEBA ~110 W handshake, OpenEVSE near-zero, OCPP varies). Hardcoded
500 W in the actuator pre-architecture; abstracted here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only
    from ..charger_types import ChargerIntent, ChargerPower


class ChargerAdapter(ABC):
    """Encapsulates one charger brand's hardware behaviour.

    Each adapter wraps a :class:`CurrentControlDevice` (which holds
    the HA service-call configuration) but adds the brand-specific
    logic on top — the conditions under which to call which service,
    when to re-assert disable, how to interpret the power reading.

    The actuator's only contract with hardware is this protocol.
    Pre-architecture the same logic was spread across
    ``ev_control.py`` (terminal-state guard, solar-mode self-charge
    guard, ramp clamp at 6 A) and ``devices/base.py``
    (stop_session brand dispatch).
    """

    # ─── Idle debounce — solar-flicker resilience ──────────────
    #
    # Per-charger consecutive-idle counter. Incremented each time
    # the actuator sees ``intent=IDLE`` for this charger, reset on
    # any non-IDLE intent. The actuator skips ``command_idle()``
    # while the counter is below ``IDLE_DEBOUNCE_THRESHOLD``,
    # holding the previous setpoint (which keeps KEBA's contactor
    # closed + authorization valid).
    #
    # Live-confirmed PROD 2026-06-02 15:08+: a single 10-second
    # solar-sensor flicker drove SEM to ``intent=idle`` for one
    # cycle, triggering ``keba.disable`` → KEBA stuck in
    # "authorization rejected" → contactor refused subsequent
    # ``set_current`` until physical replug. Debouncing for 1 cycle
    # absorbs the flicker; a real cloud (5-30 minutes) crosses
    # the threshold on cycle 2 and idle is applied normally.
    #
    # The cost during the debounce window: KEBA continues to draw
    # its prior setpoint (e.g. 6900 W at 10 A) for up to one cycle
    # while surplus is below 6 A worth of solar — i.e. ~10 s of
    # grid import. ~0.014 kWh / cycle. Cheap insurance against the
    # auth-rejected cascade.
    IDLE_DEBOUNCE_THRESHOLD: int = 4

    def __init__(self) -> None:
        # Subclasses MUST call ``super().__init__()`` to initialise
        # the debounce counter. Tracked centrally so the actuator's
        # ``attempt_idle`` / ``reset_idle_debounce`` dispatch sees
        # consistent state regardless of brand.
        self._consecutive_idle_count: int = 0

    def attempt_idle(self) -> bool:
        """Record an IDLE intent; return True if the actuator should
        execute ``command_idle()`` this cycle, False to debounce
        (keep the previous setpoint, contactor closed).

        Default threshold: execute on the 2nd consecutive idle
        (skip the 1st). Brands without a self-resume / auth-stick
        quirk can override to return True immediately.
        """
        self._consecutive_idle_count += 1
        return self._consecutive_idle_count >= self.IDLE_DEBOUNCE_THRESHOLD

    def reset_idle_debounce(self) -> None:
        """Reset the consecutive-idle counter. Called by the actuator
        on any non-IDLE intent."""
        self._consecutive_idle_count = 0

    # ─── Capability properties ────────────────────────────────

    @property
    @abstractmethod
    def min_current_a(self) -> int:
        """Minimum current the brand will accept. Below this the
        firmware either rejects the command (KEBA: silently retains
        last setpoint) or stops charging (Wallbox: pause).

        The actuator's amp-clamp uses this to decide whether to
        snap up (Wallbox) or call ``command_idle()`` (KEBA)."""

    @property
    @abstractmethod
    def max_current_a(self) -> int:
        """Hardware max current (from device config, not solar surplus)."""

    @property
    @abstractmethod
    def phases(self) -> int:
        """1 or 3. Used for W ↔ A conversion."""

    @property
    @abstractmethod
    def voltage(self) -> int:
        """Per-phase voltage. EU = 230, US = 120."""

    @property
    @abstractmethod
    def handshake_power_w(self) -> float:
        """Maximum power the brand reports when plugged but idle.
        KEBA: ~110 W (BMS communication + LEDs). Wallbox: ~0.
        Used by ``is_self_charging`` to distinguish "really
        charging" from "plugged in idle"."""

    @property
    @abstractmethod
    def can_command_zero(self) -> bool:
        """True if ``command_current(0)`` actually stops the
        charger. False on KEBA — must use ``command_idle()`` /
        ``command_disable()`` which invoke the brand-specific
        disable service.

        The actuator never asks this directly — the adapter
        handles the dispatch internally. Exposed only for tests
        + the AST lint that forbids ``adapter.command_current(0)``
        on adapters where ``can_command_zero`` is False."""

    # ─── Commands ──────────────────────────────────────────────

    @abstractmethod
    async def command_current(self, amps: int) -> None:
        """Set charging current. Must call the brand's service
        with the appropriate parameter. The adapter is responsible
        for translating below-``min_current_a`` requests into
        ``command_idle()``."""

    @abstractmethod
    async def command_idle(self) -> None:
        """Stop charging — temporary (waiting for surplus, target
        reached, battery priority). The contactor opens. The
        adapter chooses between ``set_current(0)`` and the brand's
        disable service.

        Idempotent — safe to call every cycle while the charger is
        already idle. Adapters should suppress duplicate service
        calls when ``last_intent == IDLE`` and ``power_w <
        handshake_power_w``."""

    @abstractmethod
    async def command_max(self) -> None:
        """Set the charger to its hardware max — the ``always_max``
        mode / NOW strategy. Equivalent to
        ``command_current(max_current_a)`` but explicit so the
        adapter can do brand-specific things (e.g. set 3-phase
        on configurations that support it)."""

    @abstractmethod
    async def command_disable(self) -> None:
        """User-explicit OFF (``charge_mode = off``). The contactor
        MUST open. Distinguished from ``command_idle`` because:

        1. The dashboard sensor must read "Disabled (user)" not
           "Idle (waiting surplus)".
        2. On brands that self-resume (KEBA), disable must be
           re-asserted every cycle the firmware is still drawing
           power. The adapter encapsulates that re-assertion.

        Idempotent."""

    # ─── Observation ───────────────────────────────────────────

    @abstractmethod
    def is_self_charging(self, power: "ChargerPower") -> bool:
        """True if the charger is drawing real power without SEM
        having commanded it to.

        Catches the #315/#346/#353 class of bugs at the source:
        KEBA self-resumes on plug-in, ignores ``set_current(0)``,
        retains last setpoint when commanded below 6 A. The
        adapter knows whether the brand has these quirks.

        Default heuristic: ``power.power_w > handshake_power_w``
        AND ``last_commanded_intent in (IDLE, DISABLE)``. The
        adapter overrides if the brand needs different logic."""

    @abstractmethod
    def actual_charging(self, power: "ChargerPower") -> bool:
        """Whether the charger is delivering real power right now.

        Prefers ``power.power_w > handshake_power_w`` over the
        brand's binary sensor (KEBA's ``charging_state`` lags real
        draw by ~5 s per #289). The actuator and dashboard sensors
        read this method, not ``power.charging``."""

    # ─── Helpers ───────────────────────────────────────────────

    def watts_for_amps(self, amps: int) -> float:
        """How much power ``amps`` corresponds to at this charger's
        phases × voltage."""
        return float(amps) * self.phases * self.voltage

    def amps_for_watts(self, watts: float) -> int:
        """Round-toward-zero conversion from watts to amps. The
        actuator should clamp the result to
        ``[min_current_a, max_current_a]`` itself; this is a
        plain conversion."""
        if self.phases * self.voltage <= 0:
            return 0
        return int(watts // (self.phases * self.voltage))
