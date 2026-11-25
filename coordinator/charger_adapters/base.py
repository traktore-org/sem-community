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

import inspect
import logging

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from ...utils.switch_sense import reads_running, switch_service

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

    async def command_park_off(self) -> None:
        """(park-on-disconnect) The car is GONE — leave the box OFF and cold
        so a later plug-in cannot auto-start a charge SEM never asked for.

        Default is ``command_disable`` — right for every brand whose "off"
        is a held switch / 0 A (Wallbox, Easee, go-e, OCPP). KEBA overrides
        it: its ``command_disable`` routes through the quota-hold stop, which
        is meant to bound a DRAWING session and would write a fresh energy
        quota the next plug-in inherits. A gone car needs a plain disable."""
        await self.command_disable()

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

    def status_answer(self) -> Optional[bool]:
        """(#1422) Does the brand's status say the charger charges?

        True / False when a status sensor answers; None when there is no
        status or it gives no answer, so ``actual_charging`` falls back to
        the power. Default None: a brand that reads no status (KEBA)."""
        return None

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
        - ``(None, False)`` — no usable answer: the switch is present but
          reads anything other than ``on``/``off`` (``unavailable`` /
          ``unknown``, Wallbox locked / eco-smart). SEM cannot drive it →
          surface.
        - ``(True/False, True)`` — the switch lets the charge run / stops
          it: on / off, or off / on for a switch named for the pause
          (#1042, V2C's "Pause session").
        """
        dev = self._device
        ent = getattr(dev, "start_stop_entity", None)
        if not ent or not str(ent).startswith(("switch.", "input_boolean.")):
            return (None, True)
        st = dev.hass.states.get(ent)
        # (#945) ``on``/``off`` are the only answers a switch can give. A
        # third value is not "off" — reading it that way would accuse the
        # box of refusing an assertion it was never coherently told, which
        # is this issue's whole shape — so it joins the unreadable case and
        # waits out the hold.
        running = reads_running(dev.hass, ent, getattr(st, "state", None))
        if running is None:
            return (None, False)
        return (running, True)

    def resume_pressable(self) -> bool:
        """(#1399) True when the start surface is a ``button.`` HA would
        press now: the entity exists and is not ``unavailable``.

        An integration may make its resume button available only while the
        charger is paused (#1399: operation mode Connected_Finished with a
        final stop), and HA skips a press on an unavailable entity without
        an error. So "pressable" is the box's own answer to "does it need a
        resume?" there. A never-pressed button reads ``unknown``, which is
        pressable. Anything that cannot be read answers False: a press is a
        start, and a start needs evidence."""
        dev = getattr(self, "_device", None)
        ent = str(getattr(dev, "start_stop_entity", None) or "")
        if not ent.startswith("button."):
            return False
        # Only where the button IS the session start: elsewhere a press
        # claims nothing and ``start_session`` would send its own start too.
        starts_here = getattr(dev, "enable_entity_is_session_start", None)
        try:
            if callable(starts_here) and starts_here() is False:
                return False
            st = dev.hass.states.get(ent)
        except Exception:  # noqa: BLE001 — a read never costs a cycle
            return False
        if st is None:
            return False
        state = getattr(st, "state", None)
        return isinstance(state, str) and state not in ("", "unavailable")

    async def ensure_enabled(self) -> bool:
        """Idempotently assert the start/stop surface ON. (#1399) Returns
        True when the command left for the box, False when it was withheld
        (observer mode, a yield), refused, or there was nothing to send.

        ``switch.``/``input_boolean.`` → ``turn_on``. Not idempotent everywhere
        (#976: on OCPP it asks for a new transaction), which is why the
        reconciler only emits ENABLE while the switch reads ``off``.
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
            return False
        ent = str(ent)
        if ent.startswith(("switch.", "input_boolean.")):
            # (#1042) turn_off for a switch named for the pause
            sent = await dev.send(ent.split(".")[0],
                                  switch_service(getattr(dev, "hass", None),
                                                 ent, run=True),
                                  {"entity_id": ent}, why="ensure_enabled")
        elif ent.startswith("button."):
            try:
                sent = await dev.send("button", "press", {"entity_id": ent},
                                      why="ensure_enabled (#804 resume surface)")
            except Exception as e:  # noqa: BLE001 — a refused press is news, not a crash
                # (#1399) The integration may refuse a press its cached state
                # still allowed ("resume" on a box that has already
                # resumed). Nothing was started, so nothing is claimed, and
                # the current write after this action still goes out.
                _LOGGER.info("%s: %s refused the press: %s",
                             getattr(dev, "name", "charger"), ent, e)
                return False
        else:
            return False
        left = sent is not False
        # (#940) Claim the SESSION only when this write IS the session start.
        #
        # ``_session_active`` is not a contactor flag — it is the flag
        # ``GenericAdapter.command_current`` reads to decide whether to call
        # ``start_session`` at all. Setting it here unconditionally (#536)
        # was a latch scoped wider than its evidence (bug class 83): on a
        # charger whose start is a charge-mode select or a brand service,
        # asserting the enable switch says nothing about that mechanism —
        # and because the reconciler prepends this ENABLE on exactly the
        # cycle where the switch is off (the transition out of a stop), the
        # brand's start was suppressed on the ONE cycle that needed it. The
        # box stayed on its stop mode, dropped the switch, and five
        # re-asserts later SEM filed "enable switch will not stay on"
        # against hardware that was doing what it was told (#939/#940,
        # @alexmc1510).
        #
        # ``is not False``, not truthiness: only a device that positively
        # answers "my start is somewhere else" withholds the claim. A stub
        # device that cannot answer keeps the historical behaviour rather
        # than acquiring a second start it never asked for.
        starts_here = getattr(dev, "enable_entity_is_session_start", None)
        claims = True
        if callable(starts_here):
            try:
                claims = starts_here() is not False
            except Exception as e:  # noqa: BLE001 — a probe never costs a cycle
                _LOGGER.debug("enable_entity_is_session_start() failed: %s", e)
        if claims:
            dev._session_active = True
            if left:
                # (#1399) SEM said yes again, as ``start_session`` records it
                # (#935): this claim skips that start, so it says so here,
                # or a park from the last stop outlives this charge.
                await self._forget_park(dev)
        return left

    @staticmethod
    async def _forget_park(dev) -> None:
        remember = getattr(dev, "_remember_parked", None)
        if not callable(remember):
            return
        try:
            res = remember(False)
            if inspect.isawaitable(res):
                await res
        except Exception as e:  # noqa: BLE001 — bookkeeping never costs a cycle
            _LOGGER.debug("_remember_parked(False) failed: %s", e)

    async def report_enable_blocked(self, now: "float | None" = None) -> None:
        """Surface an enable switch SEM cannot keep on — once it has been one
        for longer than a restart's warm-up (#945).

        Neither condition that reaches this hook is a rejected command, and
        both used to be reported as one: they fed the device's 3-strike
        COMMAND counter (#462), which files its Repair after three CYCLES —
        ~30 s — so every HA restart raised a persistent ERROR Repair while
        the charger's own integration was still loading. The device owns the
        wall clock now (#611's threshold, the same one #824 applies to this
        very entity); below it this stays the reconciler's WARNING, which is
        already logged.

        Round one (2.1.0-beta.17) held only the FIRST of the two, and the
        distinction it drew was wrong:

        * the switch is unreadable / uncontrollable — missing, ``unavailable``,
          or a brand status of *locked*. Nothing can be inferred yet, and a
          restart looks exactly like this, so it waits out the hold.
        * the switch is READABLE and sits ``off`` while SEM wants to charge,
          with the #536 re-assert budget spent. That was called evidence
          ("SEM wrote ``turn_on`` five times and watched it come back off")
          and kept the three-cycle speed. But the three cycles that file the
          Repair are the ones on which SEM sends NOTHING — the reconciler
          returns the report ALONE so a successful write cannot flap it — and
          a restart reaches this branch too, roughly 80 s after the switch
          entity appears still ``off`` because its integration has not
          reached the box yet. alexmc1510 restarted onto beta.22 and got the
          same notice with the other sentence in it (#945 round 2).

        So both wait, on ONE episode clock, and each keeps its own sentence.
        The fear that a readable switch would retire the hold it is waiting
        on was already answered in the same fix, on the other side: the
        retire is keyed on the emitted ACTIONS, not on "can I read the
        entity?" — and it now includes the re-asserts, which ARE the episode.
        A charger with no readable enable switch at all files nothing: there
        is no surface here to be blocked.
        """
        dev = self._device
        enabled, controllable = None, True
        try:
            enabled, controllable = self.enable_state()
        except Exception as e:  # noqa: BLE001 — never let a report throw
            _LOGGER.debug("enable_state() failed in report: %s", e)
        if controllable and enabled is not False:
            # Nothing here is blocked. Either there is no readable enable
            # switch AT ALL (``(None, True)`` — KEBA, a service, a button),
            # or the switch has come back ``on`` between the decision's
            # ``observe()`` and this report: the reconciler awaits actions
            # before reporting, so the world can move underneath it. Both
            # answer "no evidence", and the issue id is shared with the
            # write path — a verdict invented here would be a verdict about
            # somebody else's command.
            _LOGGER.debug(
                "enable-blocked reported on a surface that is not blocked "
                "(enabled=%s) — nothing to surface (#945)", enabled)
            return
        note = getattr(dev, "_note_enable_blocked", None)
        if not callable(note):
            return
        try:
            from ..repair_issues import (
                ENABLE_UNREADABLE, ENABLE_WILL_NOT_HOLD)
            error = ENABLE_WILL_NOT_HOLD if controllable else ENABLE_UNREADABLE
            if not note(now, error):
                _LOGGER.debug(
                    "enable switch not asserted (%s) — holding the Repair "
                    "until it outlasts a restart's warm-up (#945)", error)
        except Exception as e:  # noqa: BLE001 — a repair never costs a cycle
            _LOGGER.debug("enable-blocked surface failed: %s", e)

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
        # the coordinator owns the rule (config without switching, the
        # sequencer's belief with it); the adapter's own phases are the
        # fallback when no coordinator is bound
        phases = None
        rule = getattr(coord, "_wpa_phases_for", None)
        if callable(rule):
            try:
                phases, _ok = rule(cid)
            except Exception:  # noqa: BLE001
                phases = None
        phases = int(phases) if phases in (1, 3) else int(self.phases)
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
                                      self.nominal_watts_per_amp(phases),
                                      int(self.max_current_a))
