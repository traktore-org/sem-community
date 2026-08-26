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

import logging

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from ..charger_types import ChargerPower


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

    # Idle flicker-hold (solar-sensor flicker → spurious IDLE) is now
    # owned by ``ChargerReconciler`` (its own consecutive-idle counter
    # + ``DEFAULT_IDLE_DISABLE_THRESHOLD``). The adapter no longer
    # carries idle-debounce state — the legacy actuate() body that
    # drove it was retired in Task 11.

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
        read this method, not ``power.charging``.

        #548: for brands whose POWER reading lags the contactor
        (cloud-polled — Wallbox ~90 s), override this to read the
        brand's STATUS enum (authoritative, immediate) and fall back
        to the power heuristic only on unknown/unconfigured. See
        ``WallboxAdapter`` for the template + ``docs/MULTI_CHARGER.md``
        "prefer the STATUS enum" for which brands to migrate next."""

    # ─── Helpers ───────────────────────────────────────────────

    async def arm_failsafe(self) -> None:
        """Arm the device-side failsafe benignly. Default: no-op (most
        brands have no failsafe). KEBA overrides."""
        return None

    # ─── Enable-switch reconciliation (#536) ───────────────────
    #
    # Switch-controlled chargers (Wallbox, Heidelberg, …) need an enable
    # switch ON in addition to the current setpoint. SEM used to assert it
    # once via start_session (gated by a latched ``_session_active``) and
    # never re-check it, so a switch that went off (auto-pause / lock /
    # eco-smart / external toggle) left the charger commanded-but-0 W
    # (#536). The reconciler now reads the ACTUAL switch state each cycle
    # and re-asserts it. These defaults work for any brand whose start/stop
    # is a ``switch.``/``input_boolean.`` entity; brands without a readable
    # enable switch (KEBA service control, button start) return N/A.

    def enable_state(self):
        """Return ``(enabled, controllable)`` for the start/stop switch.

        - ``(None, True)``  — no readable enable switch (N/A): KEBA,
          service control, or a ``button.`` start entity.
        - ``(None, False)`` — switch present but ``unavailable``/``unknown``
          (Wallbox locked / eco-smart): SEM cannot drive it → surface.
        - ``(True/False, True)`` — switch on / off.
        """
        dev = self._device
        ent = getattr(dev, "start_stop_entity", None)
        if not ent or not str(ent).startswith(("switch.", "input_boolean.")):
            return (None, True)
        st = dev.hass.states.get(ent)
        if st is None or st.state in ("unavailable", "unknown"):
            return (None, False)
        return (st.state == "on", True)

    async def ensure_enabled(self) -> None:
        """Idempotently assert the start/stop surface ON.

        ``switch.``/``input_boolean.`` → ``turn_on`` (idempotent by nature).
        ``button.`` → ``press`` — (#804 B4a) a button start entity used to be
        INVISIBLE here (early return), while the only presser in the tree
        string-mangled the entity id and was unreachable after a latching
        stop. Now the button is a first-class enable surface: SEM presses
        exactly what the user named, and the reconciler's existing ENABLE
        retry/backoff budget paces the presses — a press has no readable
        state, so pacing by observed charging is the whole design.
        No-op only when no start/stop entity is configured at all."""
        dev = self._device
        ent = getattr(dev, "start_stop_entity", None)
        if not ent:
            return
        ent = str(ent)
        if ent.startswith(("switch.", "input_boolean.")):
            await dev.hass.services.async_call(
                ent.split(".")[0], "turn_on", {"entity_id": ent},
                blocking=True,
            )
        elif ent.startswith("button."):
            await dev.hass.services.async_call(
                "button", "press", {"entity_id": ent}, blocking=True,
            )
        else:
            return
        # Keep SEM's session view consistent with the contactor we just closed.
        dev._session_active = True

    async def report_enable_blocked(self) -> None:
        """Surface an uncontrollable enable switch as an actuation failure
        so the existing repair flow raises it (debounced by the device)."""
        rec = getattr(self._device, "_record_actuation_failure", None)
        if rec is not None:
            rec(RuntimeError("enable switch unavailable/locked — cannot start charging"))

    async def report_failsafe_suspected(self, interval_s: float) -> None:
        """(#823) Raise the failsafe Repair for this charger.

        The reconciler recognised a constant-interval self-re-enable after
        SEM's stop. The fix is a one-time change on the box (a failsafe /
        controller-timeout fallback setting), so the Repair carries the
        learned interval and points there. Warn-once is the reconciler's
        job; this only files the surface (#799: a log line is not one).
        """
        try:
            from ..repair_issues import raise_charger_failsafe_suspected
            dev = self._device
            raise_charger_failsafe_suspected(
                dev.hass, str(getattr(dev, "device_id", "") or
                              getattr(dev, "charger_id", "charger")),
                name=str(getattr(dev, "name", None) or "EV charger"),
                interval_s=float(interval_s),
            )
        except Exception as e:  # noqa: BLE001 — a repair never costs a cycle
            _LOGGER.debug("failsafe repair not raised: %s", e)

    async def clear_failsafe_suspected(self) -> None:
        """(#823) Retire the failsafe Repair once a stop finally holds."""
        try:
            from ..repair_issues import clear_charger_failsafe_suspected
            dev = self._device
            clear_charger_failsafe_suspected(
                dev.hass, str(getattr(dev, "device_id", "") or
                              getattr(dev, "charger_id", "charger")))
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("failsafe repair not cleared: %s", e)

    # (#846) The ONE place amps and watts convert. Both consult the measured
    # W/A when one has been earned for the BELIEVED phase count, and fall
    # back to nameplate otherwise — so the surplus→amps math, the night
    # planner's block sizing, the peak guard and the phase guard all improve
    # from a single change rather than each growing its own opinion (#46).
    def _wpa_context(self):
        """(learner, charger_id, phases) — or None when nothing can be
        measured. ``phases`` is the BELIEF where the coordinator has one,
        nameplate otherwise: the belief anchors this, never the reverse."""
        dev = self._device
        coord = getattr(dev, "_coordinator", None) or getattr(dev, "coordinator", None)
        from ..watts_per_amp import WattsPerAmpLearner
        learner = getattr(coord, "_wpa_learner", None)
        # isinstance, not truthiness: a mocked device hands back a Mock for
        # any attribute, and the conversion then returns a Mock instead of
        # watts. Type-check the collaborator (test_charger_adapters).
        if not isinstance(learner, WattsPerAmpLearner):
            return None
        cid = str(getattr(dev, "charger_id", "") or "")
        if not cid:
            return None
        believed = (getattr(coord, "_phase_believed", {}) or {}).get(cid)
        phases = int(believed) if believed in (1, 3) else int(self.phases)
        return learner, cid, phases

    def nominal_watts_per_amp(self, phases: int | None = None) -> float:
        ph = int(phases) if phases in (1, 3) else int(self.phases)
        return float(ph) * float(self.voltage)

    def watts_for_amps(self, amps: int) -> float:
        """How much power ``amps`` really buys — measured where known,
        nameplate otherwise. Never MORE than nameplate (#846)."""
        ctx = self._wpa_context()
        if ctx is None:
            return float(amps) * self.phases * self.voltage
        learner, cid, phases = ctx
        return learner.watts_for_amps(cid, phases, float(amps),
                                      self.nominal_watts_per_amp(phases))

    def amps_for_watts(self, watts: float) -> int:
        """Round-toward-zero conversion from watts to amps. The
        actuator should clamp the result to
        ``[min_current_a, max_current_a]`` itself; this is a
        plain conversion — measured W/A where known (#846), and always
        rounding DOWN, because handing out an amp the car then exceeds is
        the one direction that can breach a limit."""
        ctx = self._wpa_context()
        if ctx is None:
            if self.phases * self.voltage <= 0:
                return 0
            return int(watts // (self.phases * self.voltage))
        learner, cid, phases = ctx
        return learner.amps_for_watts(cid, phases, float(watts),
                                      self.nominal_watts_per_amp(phases))
